"""audit_artifacts.py — the advisory engine behind /sprd-audit-artifacts and /sprd-revise.

Connects two facts the tool already has — *when each artifact last changed* (SHA-256 hashes) and
*what depends on what* (declared traceability, via artifact_lineage) — into staleness detection, an
append-only change history, and a forward "what would this change put at risk" impact view.

Three subcommands, all **exit 0 always** (advisory — staleness is never a gate):

  record   append to the ledger. Three modes:
             --scan                      hash-walk every artifact; append `created` for new files and
                                         `snapshot` for drifted ones. The first-ever scan is the
                                         baseline ("history starts now" — the retro-baseline).
             --artifact P [--target ID]  one explicit change entry (the /sprd-revise write).
                 --actor A --reason R [--event revised] [--decision-ref DL-NN] [--phase P]
             --disposition SET           a human's judgement on one staleness candidate.
                 --downstream D --upstream U [--owner O] [--reason R] [--actor A]
  impact   <id|file>   forward lineage: everything downstream that a change here could make stale.
  report   freshness dashboard (default) | --history <id|file> | --json | --since YYYY-MM-DD

The ledger lives in its OWN JSONL (.sdlc/metrics/artifact-log.jsonl), never inside state.yaml's
gate_results (that dict is expanded into phantom rows by audit_gates.extract_gate_history — the trap
this layer must not fall into).

Standalone or Workflow (CLAUDE.md design rule):
  --repo <path>   standalone (reads <repo>/.sdlc)      |   --state .sdlc/state.yaml   in-workflow
"""

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import artifact_lineage as al
import artifact_model as am
import phase_model as pm
import track_specs as ts
import version_model as vm
from track_artifacts import compute_checksum

LEDGER_NAME = "artifact-log.jsonl"
VERSIONS_DIR_NAME = "versions"
REFRESH_DIR_NAME = "refresh"

# Pre-Build authored artifacts the refresh layer may back-propagate into (R1). Frozen layers are
# structurally downstream and are never returned by upstream_of(spec), so they are deliberately
# absent — refreshing the phase artifact lets the forward-staleness engine flag the layer next run.
PRE_BUILD_STEMS = ("requirements", "epics", "feature-brief", "business-rules")

# The single source for the stem -> discipline-agent routing (mirrors /sprd-revise's prose table so
# it cannot silently drift). Emitted per refresh candidate; also the actor-name denylist below.
DISCIPLINE_BY_STEM = {
    "requirements": "requirements-analyst",
    "epics": "feature-architect",
    "feature-brief": "feature-architect",
    "business-rules": "bizreq-analyst",
}

# An --actor may not be an agent: the One Rule is that a *named human* decides. Covers the full
# council so a confirm can't be signed by any discipline agent, not just the routed one.
DISCIPLINE_AGENTS = frozenset({
    "requirements-analyst", "feature-architect", "bizreq-analyst",
    "visual-designer", "conversation-designer", "data-analyst",
})


# --- Path / state plumbing --------------------------------------------------------------------

def resolve_paths(args) -> tuple[Path, Path, Path]:
    """(base_dir, sdlc_dir, metrics_dir) from --state (the .sdlc beside it) or --repo (<repo>/.sdlc)."""
    if getattr(args, "state", None):
        state_path = Path(args.state)
        if not state_path.exists():
            print(f"Error: State file not found: {state_path}")
            sys.exit(0)  # advisory — never a hard failure
        sdlc = state_path.resolve().parent
        return sdlc.parent, sdlc, sdlc / "metrics"
    repo = Path(args.repo).resolve()
    return repo, repo / ".sdlc", repo / ".sdlc" / "metrics"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_ledger(ledger_path: Path) -> list[dict]:
    if not ledger_path.exists():
        return []
    out = []
    for line in ledger_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Only object entries are ledger records. A valid-JSON non-object line (null, 42, a
            # bare string/array — e.g. from a hand-edit or partial write) is skipped, not appended,
            # so downstream .get() calls never hit a non-dict and the exit-0 invariant holds.
            if isinstance(obj, dict):
                out.append(obj)
    return out


def append_entries(metrics_dir: Path, entries: list[dict]) -> Path:
    metrics_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = metrics_dir / LEDGER_NAME
    with open(ledger_path, "a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return ledger_path


def load_state(sdlc_dir: Path) -> dict:
    state_path = sdlc_dir / "state.yaml"
    if not state_path.exists():
        return {}
    try:
        return yaml.safe_load(state_path.read_text(encoding="utf-8", errors="replace")) or {}
    except yaml.YAMLError:
        return {}


# --- Content-addressed version store ----------------------------------------------------------
# The object store is the ledger's hashes rehydrated to bytes: a blob's filename IS the 16-hex the
# ledger already records (via track_artifacts.compute_checksum), so there is no second index that can
# drift from freshness. It is a LOCAL safety net (gitignored) — every read degrades to "content not
# captured" and every write is best-effort, so a store fault never changes an advisory command's
# exit code or stdout. All content↔hash lockstep is enforced at the single `record_change` seam.

def versions_dir_of(sdlc_dir: Path) -> Path:
    return sdlc_dir / VERSIONS_DIR_NAME


def refresh_dir_of(sdlc_dir: Path) -> Path:
    return sdlc_dir / REFRESH_DIR_NAME


def hash_bytes(data: bytes) -> str:
    """The ledger-form hash of in-memory bytes — identical to compute_checksum of a file holding the
    same bytes (the hash-join invariant): `sha256:` + first 16 hex of the SHA-256 digest."""
    return f"sha256:{hashlib.sha256(data).hexdigest()[:16]}"


def capture_bytes(versions_dir: Path, data: bytes) -> str | None:
    """Best-effort: store `data` at objects/<xx>/<16hex>; return its hash, or None on any I/O error.
    Idempotent write-if-absent (atomic temp→rename). Swallows errors so a capture failure can never
    change a caller's exit code or stdout — the ledger stays the source of truth, the blob a bonus."""
    try:
        h = hash_bytes(data)
        rel = vm.object_relpath(h)
        if not rel:
            return None
        dest = versions_dir / rel
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.parent / (dest.name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, dest)
        return h
    except OSError:
        return None


def capture_file(versions_dir: Path, path: Path) -> str | None:
    """Best-effort capture of a file's current bytes into the store."""
    try:
        return capture_bytes(versions_dir, path.read_bytes())
    except OSError:
        return None


def read_blob(versions_dir: Path, h: str) -> bytes | None:
    """The captured bytes for a hash, or None if the blob is absent/unreadable (degrade, never crash)."""
    rel = vm.object_relpath(h)
    if not rel:
        return None
    p = versions_dir / rel
    try:
        return p.read_bytes() if p.is_file() else None
    except OSError:
        return None


def present_hashes_in_store(versions_dir: Path) -> set[str]:
    """Every ledger-form hash whose blob currently exists in the object store."""
    out: set[str] = set()
    objects = versions_dir / "objects"
    if not objects.exists():
        return out
    try:
        for shard in objects.iterdir():
            if shard.is_dir():
                for blob in shard.iterdir():
                    if blob.is_file() and not blob.name.endswith(".tmp"):
                        out.add(f"sha256:{blob.name}")
    except OSError:
        return out
    return out


def record_change(base_dir: Path, metrics_dir: Path, versions_dir: Path,
                  entries: list[dict], *, contents: dict[str, bytes] | None = None) -> Path:
    """THE single lockstep seam: capture each change entry's content, then append every entry.

    For scan/revise the on-disk file already IS the post-image, so the current file is captured. For
    the canonical mutate flows (rollback / refresh apply) the file is still the pre-image at append
    time, so the caller passes the known post-image bytes in `contents` (the object is materialized
    up front — capture here is then an idempotent no-op). Capture is best-effort; the ledger append
    is unconditional, so stdout / exit / the ledger are byte-identical whether or not the store is
    writable. Disposition entries carry no content and pass straight through."""
    contents = contents or {}
    for e in entries:
        if not am.is_change_entry(e):
            continue
        art = e.get("artifact")
        if not art:
            continue
        if art in contents:
            capture_bytes(versions_dir, contents[art])
        else:
            capture_file(versions_dir, base_dir / art)
    return append_entries(metrics_dir, entries)


# --- Artifact scanning & identity -------------------------------------------------------------

def scan_hashes(base_dir: Path, sdlc_dir: Path) -> dict[str, str]:
    """Current SHA of every tracked node (same node namespace as artifact_lineage)."""
    hashes: dict[str, str] = {}
    for node in al.discover_nodes(base_dir, sdlc_dir):
        p = base_dir / node
        if p.is_file():
            try:
                hashes[node] = compute_checksum(p)
            except OSError:
                continue  # unreadable file (e.g. mode 000) — skip, never crash the advisory scan
    return hashes


_SLUG_TO_ID = {p["slug"]: pm.normalize_id(p["id"]) for p in pm.all_phases()}


def phase_id_of(node: str) -> str:
    """Best-effort phase id a node belongs to (for the ledger's `phase` field). '' if unknown."""
    parts = node.split("/")
    if ".sdlc" in parts and "artifacts" in parts:
        i = parts.index("artifacts")
        if i + 1 < len(parts):
            return _SLUG_TO_ID.get(parts[i + 1], "") or ""
    if "context/layers/phase" in node:
        import re
        m = re.search(r"context/layers/phase([^/-]+)-", node)
        if m and pm.get_phase(m.group(1)):
            return pm.normalize_id(m.group(1))
    if node.startswith("specs/"):
        return "build"
    return ""


def resolve_target_node(base_dir: Path, sdlc_dir: Path, target: str, nodes: list[str]) -> str | None:
    """Resolve an id (FR-012) or a path to a known node. None if it can't be placed."""
    target = (target or "").strip()
    if not target:
        return None
    if al.ID_RE.fullmatch(target):
        return al.find_id_declarations(base_dir, nodes).get(target)
    # A path (absolute, repo-relative, or bare filename).
    return al._resolve_path_ref(base_dir, sdlc_dir, nodes[0] if nodes else ".", target, set(nodes)) \
        or _rel_if_node(base_dir, target, set(nodes))


def _rel_if_node(base_dir: Path, target: str, node_set: set) -> str | None:
    try:
        rel = (base_dir / target).resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        rel = target
    return rel if rel in node_set else None


def _parse_ts(ts: str):
    try:
        dt = datetime.fromisoformat(str(ts))
    except (ValueError, TypeError):
        return None
    # Ledger timestamps are tz-aware (now_iso); a bare-date --since (the documented YYYY-MM-DD form)
    # parses naive. Coerce naive to UTC so `da < db` never mixes aware/naive and raises TypeError.
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _ts_lt(a: str, b: str) -> bool:
    """True if timestamp a is strictly before b (parsed; falls back to string order)."""
    da, db = _parse_ts(a), _parse_ts(b)
    if da is not None and db is not None:
        return da < db
    return str(a) < str(b)


# --- Staleness ---------------------------------------------------------------------------------

def compute_staleness(base_dir: Path, sdlc_dir: Path, ledger: list[dict]) -> list[dict]:
    """One item per (upstream→downstream) edge where the upstream changed *after* the downstream
    last did. Each item carries its resolved disposition (recorded, else OPEN) so honest counting
    can run over the list."""
    graph = al.build_graph(base_dir, sdlc_dir)
    latest = am.latest_change_per_artifact(ledger)
    dispositions = am.latest_dispositions(ledger)

    items: list[dict] = []
    for e in graph:
        up, down = e["upstream"], e["downstream"]
        cu, cd = latest.get(up), latest.get(down)
        if not cu or not cd:
            continue
        t_up, t_down = cu.get("ts", ""), cd.get("ts", "")
        if not _ts_lt(t_down, t_up):
            continue  # downstream is at least as fresh as the upstream change — not stale
        up_hash = cu.get("hash") or ""
        key = am.staleness_key(down, up, up_hash)
        recorded = dispositions.get(key)
        item = {
            "downstream": down,
            "upstream": up,
            "upstream_hash": up_hash,
            "basis": e["basis"],
            "confidence": e["confidence"],
            "upstream_changed": t_up,
            "downstream_changed": t_down,
            "disposition": "OPEN",
        }
        if recorded:
            item["disposition"] = am.normalize_disposition(recorded.get("disposition")) or "OPEN"
            for k in ("owner", "reason"):
                if recorded.get(k):
                    item[k] = recorded[k]
        items.append(item)
    return items


# --- record ------------------------------------------------------------------------------------

def do_scan(base_dir: Path, sdlc_dir: Path, metrics_dir: Path, actor: str) -> int:
    ledger = load_ledger(metrics_dir / LEDGER_NAME)
    first_run = not any(am.is_change_entry(e) for e in ledger)
    latest = am.latest_change_per_artifact(ledger)
    hashes = scan_hashes(base_dir, sdlc_dir)
    ts = now_iso()
    actor = actor or ("baseline" if first_run else "scan")

    new_entries: list[dict] = []
    created = drifted = 0
    for node, sha in sorted(hashes.items()):
        prev = latest.get(node)
        if prev is None:
            new_entries.append(am.change_entry(
                ts=ts, artifact=node, event="created", phase=phase_id_of(node),
                hash=sha, actor=actor, reason="baseline" if first_run else "first seen"))
            created += 1
        elif prev.get("hash") != sha:
            new_entries.append(am.change_entry(
                ts=ts, artifact=node, event="snapshot", phase=phase_id_of(node),
                hash=sha, prev_hash=prev.get("hash"), actor=actor, reason="drift detected by scan"))
            drifted += 1

    if not new_entries:
        print("Artifact scan: no changes since the last ledger entry (nothing to record).")
        return 0
    record_change(base_dir, metrics_dir, versions_dir_of(sdlc_dir), new_entries)
    if first_run:
        print(f"Baseline recorded: {created} artifact(s) hashed — history starts now.")
    else:
        print(f"Recorded {len(new_entries)} change(s): {created} new, {drifted} drifted.")
    return 0


def do_change(args, base_dir: Path, sdlc_dir: Path, metrics_dir: Path) -> int:
    node = _normalize_artifact_arg(base_dir, args.artifact)
    ledger = load_ledger(metrics_dir / LEDGER_NAME)
    prev = am.latest_change_per_artifact(ledger).get(node)
    p = base_dir / node
    try:
        sha = compute_checksum(p) if p.is_file() else None
    except OSError:
        sha = None  # unreadable file — record the change with an unknown hash, never crash
    entry = am.change_entry(
        ts=now_iso(), artifact=node, event=args.event, target=args.target or "",
        phase=args.phase or phase_id_of(node), hash=sha,
        prev_hash=prev.get("hash") if prev else None,
        actor=args.actor or "", reason=args.reason or "", decision_ref=args.decision_ref or "")
    record_change(base_dir, metrics_dir, versions_dir_of(sdlc_dir), [entry])
    tgt = f" ({args.target})" if args.target else ""
    print(f"Recorded {entry['event']} of {node}{tgt} by {args.actor or 'unknown'}"
          + (f" — ref {args.decision_ref}" if args.decision_ref else ""))
    return 0


def do_disposition(args, base_dir: Path, sdlc_dir: Path, metrics_dir: Path) -> int:
    disp = am.normalize_disposition(args.disposition)
    if disp not in am.SETTABLE_DISPOSITIONS:
        print(f"record --disposition: '{args.disposition}' is not a recordable disposition "
              f"(choose one of {', '.join(am.SETTABLE_DISPOSITIONS)}). REFRESHED is DERIVED from the "
              f"ledger — update the downstream artifact and re-scan; you cannot type it. Nothing recorded.")
        return 0
    nodes = al.discover_nodes(base_dir, sdlc_dir)
    down = resolve_target_node(base_dir, sdlc_dir, args.downstream, nodes) or args.downstream
    up = resolve_target_node(base_dir, sdlc_dir, args.upstream, nodes) or args.upstream
    ledger = load_ledger(metrics_dir / LEDGER_NAME)
    up_change = am.latest_change_per_artifact(ledger).get(up)
    up_hash = args.upstream_hash or (up_change.get("hash") if up_change else "") or ""
    entry = am.disposition_entry(
        ts=now_iso(), downstream=down, upstream=up, upstream_hash=up_hash,
        disposition=args.disposition, owner=args.owner or "", reason=args.reason or "",
        actor=args.actor or "")
    append_entries(metrics_dir, [entry])
    off, why = am.validate_disposition(entry)
    tag = "off the books" if off else f"STILL COUNTS as debt ({why})"
    print(f"Recorded disposition {entry['disposition']} for {down} <- {up}: {tag}.")
    return 0


def _normalize_artifact_arg(base_dir: Path, artifact: str) -> str:
    try:
        return (base_dir / artifact).resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return artifact.replace("\\", "/")


def cmd_record(args) -> int:
    base_dir, sdlc_dir, metrics_dir = resolve_paths(args)
    if args.disposition:
        if not (args.downstream and args.upstream):
            print("record --disposition needs --downstream and --upstream (nothing recorded).")
            return 0
        return do_disposition(args, base_dir, sdlc_dir, metrics_dir)
    if args.scan:
        return do_scan(base_dir, sdlc_dir, metrics_dir, args.actor or "")
    if args.artifact:
        return do_change(args, base_dir, sdlc_dir, metrics_dir)
    print("record: choose a mode — --scan, --artifact <path>, or --disposition <SET> "
          "(nothing recorded).")
    return 0


# --- impact ------------------------------------------------------------------------------------

def cmd_impact(args) -> int:
    base_dir, sdlc_dir, _ = resolve_paths(args)
    nodes = al.discover_nodes(base_dir, sdlc_dir)
    node = resolve_target_node(base_dir, sdlc_dir, args.target, nodes)
    if not node:
        print(f"Impact — could not resolve '{args.target}' to a known artifact.")
        print("(advisory — nothing to assess)")
        return 0
    graph = al.build_graph(base_dir, sdlc_dir)
    rows = al.downstream_of(graph, node)
    if args.json:
        print(json.dumps({"target": node, "downstream": rows}, indent=2))
        return 0
    print(f"Impact — if {node} changes, {len(rows)} downstream artifact(s) may go stale:")
    if not rows:
        print("  (no declared or inferred downstream)")
    for r in sorted(rows, key=lambda x: (x["confidence"], x["node"])):
        label = "declared" if r["confidence"] == "declared" else "COARSE (phase-order guess)"
        path = " -> ".join(r["path"][1:]) if len(r["path"]) > 2 else r["node"]
        print(f"  • {r['node']}   [{label}]" + (f"   via {path}" if len(r["path"]) > 2 else ""))
    print("(advisory — a downstream may already account for the change; disposition each in "
          "/sprd-audit-artifacts)")
    return 0


# --- report ------------------------------------------------------------------------------------

def cmd_report(args) -> int:
    base_dir, sdlc_dir, metrics_dir = resolve_paths(args)
    ledger = load_ledger(metrics_dir / LEDGER_NAME)

    if args.history:
        return _report_history(base_dir, sdlc_dir, ledger, args)

    full_latest = am.latest_change_per_artifact(ledger)
    has_history = bool(full_latest)
    items = compute_staleness(base_dir, sdlc_dir, ledger)
    latest, items, scope = _apply_scope(base_dir, sdlc_dir, full_latest, items, args)

    debt = am.open_debt(items)
    # "dispositioned" == legitimately off the books (ACKNOWLEDGED w/ owner, NOT_AFFECTED w/ reason).
    # Defined as the complement of debt so the footer count always reconciles with the per-node line.
    acknowledged = [i for i in items if not am.counts_as_debt(i)]
    stale_downstreams = sorted({i["downstream"] for i in items})

    if args.json:
        print(json.dumps({
            "has_history": has_history,
            "scope": scope,
            "artifacts_tracked": len(full_latest),
            "artifacts_shown": len(latest),
            "stale": len(stale_downstreams),
            "open": len(debt),
            "acknowledged": len(acknowledged),
            "items": items,
        }, indent=2))
        return 0

    print(_format_freshness(sdlc_dir, latest, items, debt, acknowledged, scope, has_history))
    return 0


def _apply_scope(base_dir: Path, sdlc_dir: Path, latest: dict, items: list[dict], args):
    """Restrict the freshness view to --artifact, --phase, and/or --since. Returns
    (scoped_latest, scoped_items, scope_label)."""
    scope = "all"
    if getattr(args, "artifact", None):
        nodes = al.discover_nodes(base_dir, sdlc_dir)
        node = resolve_target_node(base_dir, sdlc_dir, args.artifact, nodes) or \
            _normalize_artifact_arg(base_dir, args.artifact)
        latest = {k: v for k, v in latest.items() if k == node}
        items = [i for i in items if i["downstream"] == node]
        scope = f"artifact:{node}"
    elif getattr(args, "phase", None):
        pid = pm.normalize_id(args.phase)
        latest = {k: v for k, v in latest.items() if phase_id_of(k) == pid}
        items = [i for i in items if phase_id_of(i["downstream"]) == pid]
        scope = f"phase:{pid}"
    if getattr(args, "since", None):
        latest = {k: v for k, v in latest.items() if not _ts_lt(v.get("ts", ""), args.since)}
        items = [i for i in items if i["downstream"] in latest]
        scope = f"{scope}+since:{args.since}" if scope != "all" else f"since:{args.since}"
    return latest, items, scope


def _report_history(base_dir: Path, sdlc_dir: Path, ledger: list[dict], args) -> int:
    nodes = al.discover_nodes(base_dir, sdlc_dir)
    node = resolve_target_node(base_dir, sdlc_dir, args.history, nodes) or \
        _normalize_artifact_arg(base_dir, args.history)
    trail = am.changes_for(ledger, node)
    if args.since:
        trail = [e for e in trail if not _ts_lt(e.get("ts", ""), args.since)]
    if args.json:
        print(json.dumps({"artifact": node, "history": trail}, indent=2))
        return 0
    print(f"History — {node}")
    print("=" * 50)
    if not trail:
        print("  (no recorded changes — run `record --scan` to seed a baseline)")
        return 0
    for e in trail:
        who = e.get("actor") or "unknown"
        tgt = f" [{e['target']}]" if e.get("target") else ""
        why = f' — "{e["reason"]}"' if e.get("reason") else ""
        ref = f" ({e['decision_ref']})" if e.get("decision_ref") else ""
        print(f"  {e.get('ts', '?')[:19]}  {e.get('event', '?'):9}{tgt}  by {who}{why}{ref}")
    return 0


def _glyph(preferred: str, fallback: str) -> str:
    """`preferred` if the console can encode it, else a plain-ASCII `fallback`.

    A default Windows console is cp1252 and cannot encode '←' or '✓'. Printing one raises
    UnicodeEncodeError and kills the process with a NON-ZERO exit — precisely what this advisory
    module promises never to do — and it fires on the happy path, since the arrow prints for every
    stale item and the check for every signed-off phase. So the tool would die exactly when it had
    something to report. Resolved per call rather than at import because stdout may be replaced
    after this module loads (test capture, redirection, a wrapping harness).
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        preferred.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return fallback
    return preferred


def _format_freshness(sdlc_dir, latest, items, debt, acknowledged, scope, has_history) -> str:
    state = load_state(sdlc_dir)
    phases = state.get("phases", {}) if isinstance(state, dict) else {}

    header = "Artifact Freshness" + ("" if scope == "all" else f"  (scope: {scope})")
    lines = [header, "=" * 50]
    if not latest:
        if not has_history:
            lines.append("No artifact history yet.")
            lines.append("Run `record --scan` to seed a baseline (history starts now); nothing is")
            lines.append("fabricated about the past.")
        else:
            lines.append(f"No tracked artifacts match this scope ({scope}).")
        lines.append("=" * 50)
        lines.append("ADVISORY — nothing to assess (advisory surface — never blocks).")
        return "\n".join(lines)

    arrow = _glyph("←", "<-")
    stale_by_down: dict[str, list[dict]] = {}
    for i in items:
        stale_by_down.setdefault(i["downstream"], []).append(i)

    for node in sorted(latest):
        c = latest[node]
        when = c.get("ts", "?")[:10]
        who = c.get("actor") or "?"
        node_items = stale_by_down.get(node, [])
        if not node_items:
            status = "FRESH"
        else:
            n_open = len(am.open_debt(node_items))
            status = f"STALE ({n_open} open, {len(node_items) - n_open} dispositioned)"
        signed = _signoff_note(node, phases)
        lines.append(f"  {node}")
        lines.append(f"      changed {when} by {who}   {signed}   {status}")
        for i in node_items:
            disp = am.normalize_disposition(i.get("disposition")) or "OPEN"
            owner = f" {i['owner']}" if i.get("owner") else ""
            conf = "" if i["confidence"] == "declared" else " [coarse]"
            lines.append(f"         {arrow} {i['upstream']}{conf}  ({disp}{owner})")

    lines.append("=" * 50)
    lines.append(f"{len(latest)} artifact(s) tracked · "
                 f"{len({i['downstream'] for i in items})} stale · "
                 f"{len(debt)} open · {len(acknowledged)} dispositioned")
    lines.append("ADVISORY — staleness is a candidate a human dispositions, never a gate (exit 0).")
    return "\n".join(lines)


def _signoff_note(node: str, phases: dict) -> str:
    pid = phase_id_of(node)
    pdata = phases.get(pid) if isinstance(phases, dict) else None
    if isinstance(pdata, dict):
        if pdata.get("sign_off") or pdata.get("signed_by"):
            return f"signed-off {_glyph('✓', '(y)')}"
        if pdata.get("status") == "completed":
            return "phase completed"
    return "unsigned"


# --- Torn-write-safe content mutate (shared by rollback and refresh apply) --------------------
# Canonical order: capture pre-image -> materialize post-image -> append ledger -> os.replace LAST.
# The post-image bytes are known before the real file is touched (a rollback target blob, or a
# refresh .proposed), so a torn write is always recoverable: if the ledger's latest hash for a node
# differs from disk and the post-image blob exists, redo the replace. A one-line journal makes that
# recovery fire ONLY for an interrupted mutate — never for ordinary, not-yet-scanned drift.

def _pending_path(versions_dir: Path) -> Path:
    return versions_dir / "pending.json"


def _write_pending(versions_dir: Path, node: str, want_hash: str) -> None:
    try:
        versions_dir.mkdir(parents=True, exist_ok=True)
        _pending_path(versions_dir).write_text(
            json.dumps({"node": node, "hash": want_hash}), encoding="utf-8")
    except OSError:
        pass


def _clear_pending(versions_dir: Path) -> None:
    try:
        _pending_path(versions_dir).unlink()
    except OSError:
        pass


def _atomic_write(target: Path, data: bytes) -> None:
    """Write-temp-in-same-dir -> atomic rename (the final durable step of the mutate order)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / (target.name + ".sdlc-tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)


def recover_pending(base_dir: Path, versions_dir: Path) -> None:
    """Torn-write recovery: complete an interrupted mutate. Fires only when the journal marks a
    mutate as in-flight (written just before os.replace, cleared right after), so ordinary
    not-yet-scanned drift is never clobbered. Best-effort and silent — a recovery fault never
    changes a command's output or exit code."""
    p = _pending_path(versions_dir)
    if not p.exists():
        return
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _clear_pending(versions_dir)
        return
    node, want = rec.get("node"), rec.get("hash")
    if node and want:
        target = base_dir / node
        try:
            cur = compute_checksum(target) if target.is_file() else None
        except OSError:
            cur = None
        if want != cur:
            data = read_blob(versions_dir, want)
            if data is not None:
                try:
                    _atomic_write(target, data)
                except OSError:
                    pass
    _clear_pending(versions_dir)


def mutate_artifact(base_dir: Path, metrics_dir: Path, versions_dir: Path, node: str,
                    new_bytes: bytes, *, event: str, target_id: str = "", actor: str = "",
                    reason: str = "", decision_ref: str = "", source_spec: str = "") -> tuple[bool, str]:
    """The canonical torn-write-safe mutate — shared verbatim by rollback and refresh apply.

    Returns (ok, message):
      ok=False -> nothing written (a structural precondition failed); message says why.
      ok=True  -> message is the new post-image hash, or a 'ledger ahead of disk' note if the final
                  os.replace faulted (recover_pending reconciles it on the next run)."""
    target = base_dir / node
    # 1. Capture the pre-image. Reversibility is a precondition: no capture, no mutate (R6).
    if target.is_file():
        if capture_file(versions_dir, target) is None:
            return False, "capture failed — this change is not reversible; nothing written"
    # 2. Materialize the post-image object from the known bytes (idempotent write-if-absent).
    post_hash = capture_bytes(versions_dir, new_bytes)
    if post_hash is None:
        return False, "could not materialize the new content in the store; nothing written"
    # 3. Append the ledger change. record_change captures the post-image from `contents` (the file on
    #    disk is still the PRE-image until step 4), so it must be passed explicitly here.
    prev = am.latest_change_per_artifact(load_ledger(metrics_dir / LEDGER_NAME)).get(node)
    entry = am.change_entry(
        ts=now_iso(), artifact=node, event=event, target=target_id, phase=phase_id_of(node),
        hash=post_hash, prev_hash=prev.get("hash") if prev else None,
        actor=actor, reason=reason, decision_ref=decision_ref)
    if source_spec:
        entry["source_spec"] = source_spec  # additive rider; artifact_model.change_entry is unchanged
    record_change(base_dir, metrics_dir, versions_dir, [entry], contents={node: new_bytes})
    # 4. os.replace LAST, journalled so an interruption here reconciles on the next run.
    try:
        _write_pending(versions_dir, node, post_hash)
        _atomic_write(target, new_bytes)
        _clear_pending(versions_dir)
    except OSError:
        return True, (f"{post_hash} recorded, but writing {node} failed — the ledger is ahead of "
                      f"disk and will reconcile on the next run")
    return True, post_hash


def _signoff_guard(node: str, sdlc_dir: Path, ack: bool) -> tuple[bool, str]:
    """R5: changing a signed-off / completed-phase artifact needs explicit --ack-signoff. When the
    sign-off status can't be read (e.g. --repo with no state.yaml), stay conservative and still
    require the flag with a generic warning — never silently mutate a possibly-signed artifact."""
    state = load_state(sdlc_dir)
    if not state:
        if not ack:
            return False, ("cannot read sign-off status (no state.yaml) — pass --ack-signoff to "
                           "confirm you accept changing a possibly signed-off artifact; nothing written")
        return True, ""
    phases = state.get("phases", {}) if isinstance(state, dict) else {}
    note = _signoff_note(node, phases)
    if note in ("signed-off ✓", "phase completed") and not ack:
        return False, (f"{node} is {note} — pass --ack-signoff to confirm changing a signed-off "
                       f"artifact (the override is recorded); nothing written")
    return True, ""


def _confirm_guards(node: str, sdlc_dir: Path, args, diffhash: str) -> tuple[bool, str]:
    """Human-confirm hardening for a --confirm mutate: a named human actor (never a discipline
    agent), an echoed --reviewed <diffhash> proving they saw *this* diff (no blanket escape), then
    the R5 sign-off gate. Any failure -> refuse, nothing written (exit 0 at the caller)."""
    actor = (getattr(args, "actor", "") or "").strip()
    if not actor:
        return False, "--confirm needs --actor <name> (a named human owns the change); nothing written"
    if actor.lower() in DISCIPLINE_AGENTS:
        return False, (f"--actor {actor!r} is a discipline agent — an agent proposes, a named human "
                       f"decides (the One Rule); pass a human name. Nothing written")
    reviewed = vm.hash_hex(getattr(args, "reviewed", "") or "").strip().lower()
    if not reviewed:
        return False, ("re-run without --confirm to preview the diff, then pass --reviewed <diffhash> "
                       "to confirm you saw it; nothing written")
    if not vm.hash_hex(diffhash).lower().startswith(reviewed):
        return False, (f"--reviewed does not match the current diff ({diffhash}) — the content changed "
                       f"since you previewed it; re-preview. Nothing written")
    return _signoff_guard(node, sdlc_dir, getattr(args, "ack_signoff", False))


def _unified(a: bytes, b: bytes, a_label: str, b_label: str) -> str:
    a_lines = a.decode("utf-8", errors="replace").splitlines(keepends=True)
    b_lines = b.decode("utf-8", errors="replace").splitlines(keepends=True)
    return "".join(difflib.unified_diff(a_lines, b_lines, fromfile=a_label, tofile=b_label))


def _rollback_preview_path(sdlc_dir: Path, node: str) -> Path:
    return refresh_dir_of(sdlc_dir) / "_rollback" / (node.replace("/", "__") + ".preview")


def _write_rollback_preview(sdlc_dir: Path, node: str, text: str) -> None:
    try:
        p = _rollback_preview_path(sdlc_dir, node)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    except OSError:
        pass


def _clear_rollback_preview(sdlc_dir: Path, node: str) -> None:
    try:
        _rollback_preview_path(sdlc_dir, node).unlink()
    except OSError:
        pass


# --- version: content history / diff / rollback / gc ------------------------------------------

def _resolve_artifact(base_dir: Path, sdlc_dir: Path, arg: str) -> str:
    """Resolve an id (FR-012) or a path to a repo-relative node — the join key shared with the
    ledger and lineage graph. Falls back to the normalized path so an as-yet-unknown artifact still
    gets a stable key (never split by a basename-vs-relpath mismatch)."""
    nodes = al.discover_nodes(base_dir, sdlc_dir)
    return resolve_target_node(base_dir, sdlc_dir, arg, nodes) or _normalize_artifact_arg(base_dir, arg)


def _versions_of(base_dir: Path, metrics_dir: Path, versions_dir: Path, node: str) -> list[dict]:
    """The derived version list for one node: ledger changes, current file (baseline synthesis),
    and the set of hashes actually present in the store (so `present` is honest)."""
    ledger = load_ledger(metrics_dir / LEDGER_NAME)
    p = base_dir / node
    try:
        cur = compute_checksum(p) if p.is_file() else None
    except OSError:
        cur = None
    return vm.versions_for(ledger, node, current_hash=cur,
                           present_hashes=present_hashes_in_store(versions_dir))


def _not_captured_note() -> str:
    """The shared 'why + what to do' appended to every missing-blob message — stated ONCE here, not
    per call-site. Honest multi-machine story: the object store is a local, gitignored safety net, so
    a version's bytes exist only on the machine that captured them. Two short advisory lines: the
    honest cause, then the remedy (start capturing here, or flip the documented .gitignore override)."""
    return (
        "The version store is local and gitignored, so a version's bytes live only on the machine "
        "that captured them — a fresh clone/CI, a `gc` prune, or a store fault all read this.\n"
        "Run the `record --scan` step (via /sprd-audit-artifacts or /sprd-next) on this machine to "
        "capture from now on, or see references/artifact-versioning.md for the documented .gitignore "
        "override that commits the store for team-portable history."
    )


def do_version_list(args, base_dir, sdlc_dir, metrics_dir, versions_dir) -> int:
    node = _resolve_artifact(base_dir, sdlc_dir, args.artifact)
    versions = _versions_of(base_dir, metrics_dir, versions_dir, node)
    if getattr(args, "json", False):
        print(json.dumps({"artifact": node, "versions": versions}, indent=2))
        return 0
    print(f"Version history — {node}")
    print("=" * 50)
    if not versions:
        print("  (no versions — run `record --scan` to seed a baseline, or edit via /sprd-revise)")
        return 0
    for v in versions:
        when = (v.get("ts") or "")[:10] or "----------"
        who = v.get("actor") or "?"
        rf = f"  (restored from v{v['restored_from']})" if v.get("restored_from") else ""
        tag = "" if v["present"] else "  [content not captured]"
        print(f"  v{v['n']:<3} {v['event']:9} {v['hash']}  {when} {who}{rf}{tag}")
    print("=" * 50)
    print("ADVISORY — content snapshots are a local, gitignored safety net (exit 0).")
    uncaptured = sum(1 for v in versions if not v["present"])
    if uncaptured == len(versions):
        # Fresh-clone / post-gc case: nothing captured on this machine. Explain once as a footer so
        # the per-row [content not captured] tags don't read as a bug.
        print(_not_captured_note())
    elif uncaptured:
        # Mixed history: one line, not the full note — show/diff on that version give the remedy.
        print(f"{uncaptured} version(s) not captured on this machine — "
              "see references/artifact-versioning.md.")
    return 0


def do_version_show(args, base_dir, sdlc_dir, metrics_dir, versions_dir) -> int:
    node = _resolve_artifact(base_dir, sdlc_dir, args.artifact)
    versions = _versions_of(base_dir, metrics_dir, versions_dir, node)
    row, note = vm.resolve_version(versions, args.ref)
    if row is None:
        print(f"show — {note} ({node})")
        return 0
    data = read_blob(versions_dir, row["hash"]) if row["present"] else None
    if data is None:
        print(f"show — v{row['n']} content not captured for this version (hash {row['hash']}).")
        print(_not_captured_note())
        return 0
    sys.stdout.write(data.decode("utf-8", errors="replace"))
    return 0


def do_version_diff(args, base_dir, sdlc_dir, metrics_dir, versions_dir) -> int:
    node = _resolve_artifact(base_dir, sdlc_dir, args.artifact)
    versions = _versions_of(base_dir, metrics_dir, versions_dir, node)
    if not versions:
        print(f"diff — no version history for {node} (no data).")
        return 0
    if len(versions) < 2 and not (args.a and args.b):
        print(f"diff — only one version of {node}; nothing to compare.")
        return 0
    row_a, na = vm.resolve_version(versions, args.a or "prev")
    if row_a is None:
        print(f"diff — {na} ({node})")
        return 0
    row_b, nb = vm.resolve_version(versions, args.b or "latest")
    if row_b is None:
        print(f"diff — {nb} ({node})")
        return 0
    da = read_blob(versions_dir, row_a["hash"]) if row_a["present"] else None
    db = read_blob(versions_dir, row_b["hash"]) if row_b["present"] else None
    if da is None:
        print(f"diff — v{row_a['n']} content not captured for this version (hash {row_a['hash']}).")
        print(_not_captured_note())
        return 0
    if db is None:
        print(f"diff — v{row_b['n']} content not captured for this version (hash {row_b['hash']}).")
        print(_not_captured_note())
        return 0
    text = _unified(da, db, f"{node}@v{row_a['n']}", f"{node}@v{row_b['n']}")
    if not text.strip():
        print(f"diff — v{row_a['n']} and v{row_b['n']} are identical.")
        return 0
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def do_version_rollback(args, base_dir, sdlc_dir, metrics_dir, versions_dir) -> int:
    node = _resolve_artifact(base_dir, sdlc_dir, args.artifact)
    versions = _versions_of(base_dir, metrics_dir, versions_dir, node)
    if not versions:
        print(f"rollback — no version history for {node} (nothing to restore).")
        return 0
    row, note = vm.resolve_version(versions, args.ref)
    if row is None:
        print(f"rollback — {note} ({node})")
        return 0
    # Edge E2: refuse a rollback to an uncaptured version — never os.replace from a missing object.
    target_bytes = read_blob(versions_dir, row["hash"]) if row["present"] else None
    if target_bytes is None:
        print(f"rollback — v{row['n']} content not captured — cannot restore (hash {row['hash']}); "
              f"nothing written.")
        print(_not_captured_note())
        return 0
    p = base_dir / node
    try:
        cur_bytes = p.read_bytes() if p.is_file() else b""
    except OSError:
        cur_bytes = b""
    if hash_bytes(cur_bytes) == row["hash"]:
        print(f"rollback — {node} already matches v{row['n']} ({row['hash']}); nothing to do.")
        return 0
    diff_text = _unified(cur_bytes, target_bytes, f"{node}@current", f"{node}@v{row['n']}")
    diffhash = hash_bytes(diff_text.encode("utf-8"))

    if not getattr(args, "confirm", False):
        _write_rollback_preview(sdlc_dir, node, diff_text)
        print(f"Rollback preview — restore {node} to v{row['n']} ({row['event']}, {row['hash']}):")
        print("-" * 50)
        sys.stdout.write(diff_text if diff_text.endswith("\n") else diff_text + "\n")
        print("-" * 50)
        print(f"To apply: version rollback {args.artifact} {args.ref} --confirm --actor <you> "
              f"--reviewed {diffhash}")
        print("ADVISORY — preview only; nothing written (exit 0).")
        return 0

    ok, msg = _confirm_guards(node, sdlc_dir, args, diffhash)
    if not ok:
        print(f"rollback — {msg}")
        return 0
    ok, msg = mutate_artifact(
        base_dir, metrics_dir, versions_dir, node, target_bytes, event="revised",
        actor=args.actor, reason=f"rollback to v{row['n']} ({row['hash']})",
        decision_ref=getattr(args, "decision_ref", "") or "")
    if not ok:
        print(f"rollback — {msg}")
        return 0
    _clear_rollback_preview(sdlc_dir, node)
    print(f"Rolled back {node} to v{row['n']} content ({row['hash']}) by {args.actor}.")
    print(f"Recorded as a new, append-only version — the rollback is itself reversible and renders "
          f"'restored from v{row['n']}'.")
    print("Re-gate the affected phase with /sprd-gate (this command writes no state.yaml).")
    return 0


def do_version_gc(args, base_dir, sdlc_dir, metrics_dir, versions_dir) -> int:
    keep = args.keep if args.keep is not None else 10
    ledger = load_ledger(metrics_dir / LEDGER_NAME)
    present = present_hashes_in_store(versions_dir)
    if not present:
        print("gc — the object store is empty (no data); nothing to prune.")
        return 0
    arts = sorted({e.get("artifact") for e in ledger
                   if am.is_change_entry(e) and e.get("artifact")})
    state = load_state(sdlc_dir)
    signoff_known = bool(state)
    phases = state.get("phases", {}) if isinstance(state, dict) else {}

    # Cross-ledger refcount: an object survives if ANY artifact retains it in its newest N (or is its
    # latest), OR it belongs to a sign-off-protected artifact. Dedup means one blob can be a prunable
    # old version of A yet the protected latest of B — the union below keeps it either way.
    retained: set[str] = set()
    protected: set[str] = set()
    for art in arts:
        versions = vm.versions_for(ledger, art, present_hashes=present)
        if not versions:
            continue
        for r in (versions[-keep:] if keep > 0 else versions):
            if r["hash"]:
                retained.add(r["hash"])
        retained.add(versions[-1]["hash"])  # the latest is always retained
        # Sign-off protection (W4): protect every hash of a signed-off artifact; when sign-off is
        # unknowable (no state.yaml) treat every artifact as protected — gc no-ops rather than risk it.
        note = _signoff_note(art, phases)
        if (not signoff_known) or note in ("signed-off ✓", "phase completed"):
            for r in versions:
                if r["hash"]:
                    protected.add(r["hash"])

    keepset = retained | protected
    evictable = sorted(h for h in present if h not in keepset)
    kept = len(present) - len(evictable)

    if not evictable:
        why = " (sign-off status unknown — everything protected)" if not signoff_known else ""
        print(f"gc — nothing to prune: all {len(present)} stored object(s) are retained "
              f"(keep={keep}){why}.")
        return 0

    if not getattr(args, "apply", False):
        print(f"gc preview — {len(evictable)} object(s) prunable, {kept} retained (keep={keep}):")
        for h in evictable:
            print(f"  • {h}   {vm.object_relpath(h)}")
        print("Run with --apply to delete. ADVISORY — preview only; nothing deleted (exit 0).")
        return 0

    deleted = 0
    for h in evictable:
        rel = vm.object_relpath(h)
        if not rel:
            continue
        try:
            (versions_dir / rel).unlink()
            deleted += 1
        except OSError:
            continue
    print(f"gc — pruned {deleted} object(s); {kept} retained (keep={keep}). "
          f"Pruned versions now render 'content not captured'; the ledger is unchanged.")
    print(_not_captured_note())
    return 0


def cmd_version(args) -> int:
    base_dir, sdlc_dir, metrics_dir = resolve_paths(args)
    versions_dir = versions_dir_of(sdlc_dir)
    recover_pending(base_dir, versions_dir)  # complete any mutate interrupted mid-os.replace
    fn = _VERSION_DISPATCH.get(args.version_cmd)
    if fn is None:
        print("version: choose list | show | diff | rollback | gc")
        return 0
    return fn(args, base_dir, sdlc_dir, metrics_dir, versions_dir)


# The dispatch is the single source of truth for the version verbs.
_VERSION_DISPATCH = {
    "list": do_version_list,
    "show": do_version_show,
    "diff": do_version_diff,
    "rollback": do_version_rollback,
    "gc": do_version_gc,
}


# --- refresh: reverse-propagation (detect read-only; draft/apply/reject/status write) ---------
# Traceability is declared forward (requirement -> spec); this reads it BACKWARD to surface the
# pre-Build upstreams a merged spec's shipped reality implies an edit to. `detect`/`scan` are pure
# reads (side-effect-free): they list candidates and a conservative drift verdict, never write.
# `draft` seeds a `.proposed` copy of each eligible upstream (a discipline agent then edits ONLY
# that file — the real artifact stays untouched); a NAMED HUMAN `apply`s (the One Rule) through the
# shared canonical mutate order, or `reject`s to NOT_AFFECTED. `status` self-counts the spec's
# upstream dispositions from the ledger (REFRESHED via the additive `source_spec` rider, honest).

def _resolve_spec_node(base_dir: Path, spec_arg: str) -> str | None:
    """Resolve a --spec argument to a repo-relative `specs/*.md` node, or None. Accepts a repo-relative
    path, an absolute path inside the repo, or a bare filename resolved under specs/."""
    if not spec_arg:
        return None
    node = _normalize_artifact_arg(base_dir, spec_arg)
    if node.startswith("specs/") and (base_dir / node).is_file():
        return node
    cand = f"specs/{Path(spec_arg).name}"
    return cand if (base_dir / cand).is_file() else None


def _spec_id_of(base_dir: Path, spec_node: str) -> str:
    try:
        fm = al.read_yaml_frontmatter((base_dir / spec_node).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        fm = {}
    return str(fm.get("spec") or Path(spec_node).stem)


def _safe_checksum(p: Path) -> str:
    try:
        return compute_checksum(p) if p.is_file() else ""
    except OSError:
        return ""


def _pre_build_stem(node: str) -> str | None:
    """The PRE_BUILD_STEMS entry a node matches by filename stem (R1 filter), else None. Mirrors the
    `== or startswith` convention artifact_lineage uses for id ownership."""
    stem = Path(node).stem.lower()
    for s in PRE_BUILD_STEMS:
        if stem == s or stem.startswith(s):
            return s
    return None


def _spec_referenced_ids(spec_text: str) -> set[str]:
    return {m.group(0) for m in al.ID_RE.finditer(spec_text)}


def _id_substantiated_in(base_dir: Path, target_node: str, spec_ids: set[str]) -> bool:
    """True if some in-vocabulary id the spec cites, owned by the target's stem, ACTUALLY appears in
    the target file. The lineage graph maps an id to its owner stem without checking the id exists
    there, so a spec citing a phantom id (FR-999 no upstream declares) would otherwise surface a
    fabricated candidate. This is the R2 honesty guard: a phantom id yields no real candidate."""
    try:
        up_text = (base_dir / target_node).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    stem = Path(target_node).stem.lower()
    for sid in spec_ids:
        m = al.ID_RE.fullmatch(sid)
        if not m:
            continue
        owner_stem = al.ID_OWNER_STEM.get(m.group(1))
        if owner_stem and (stem == owner_stem or stem.startswith(owner_stem)) and sid in up_text:
            return True
    return False


# A "salient" token: a number with a time/size/percent unit, a 3+ digit code, or a decimal — the
# tokens most likely to encode a shipped-reality delta (an SLA, a status code, a limit).
_SALIENT_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:ms|s|sec|secs|second|seconds|min|mins|minute|minutes|"
    r"hr|hrs|hour|hours|day|days|%|kb|mb|gb)\b"
    r"|\b\d{3,}\b"
    r"|\b\d+\.\d+\b",
    re.IGNORECASE)


def _md_section(text: str, header_kw: str) -> str:
    """Concatenated body of every `##`-style section whose header contains header_kw (case-insensitive)."""
    out, capture = [], False
    for ln in text.splitlines():
        if ln.lstrip().startswith("#"):
            capture = header_kw.lower() in ln.lower()
            continue
        if capture:
            out.append(ln)
    return "\n".join(out)


def _divergence_signal(spec_text: str, upstream_text: str) -> tuple[bool, str]:
    """CONSERVATIVE, advisory drift heuristic (documented as needs-tuning). A salient token present in
    the spec's Acceptance/Scope sections but ABSENT from the upstream is treated as a drift signal.
    No signal -> trace-only (no auto-draft without --draft). Whitespace-insensitive substring match
    keeps false positives down (e.g. '4h' matches '4 hours'); it never raises."""
    if not spec_text or not upstream_text:
        return False, ""
    acc = "\n".join(_md_section(spec_text, kw) for kw in ("acceptance", "scope"))
    up_norm = re.sub(r"\s+", "", upstream_text.lower())
    for m in _SALIENT_RE.finditer(acc):
        tok = m.group(0)
        norm = re.sub(r"\s+", "", tok.lower())
        if norm and norm not in up_norm:
            return True, f"spec acceptance/scope mentions {tok.strip()!r}, absent upstream"
    return False, ""


def _detect_candidates(base_dir: Path, sdlc_dir: Path, metrics_dir: Path, spec_node: str, *,
                       transitive: bool, include_coarse: bool) -> tuple[list[dict], dict, str]:
    """Read-only: the pre-Build upstreams a spec traces to, each with a drift verdict + already-fresher
    flag. Side-effect-free. Returns (candidates, spec_meta, spec_ts)."""
    try:
        spec_text = (base_dir / spec_node).read_text(encoding="utf-8", errors="replace")
    except OSError:
        spec_text = ""
    fm = al.read_yaml_frontmatter(spec_text)
    spec_meta = {"status": str(fm.get("status") or "").strip().lower(), "source": fm.get("source")}
    spec_ids = _spec_referenced_ids(spec_text)

    graph = al.build_graph(base_dir, sdlc_dir)
    rows = al.upstream_of(graph, spec_node)
    ledger = load_ledger(metrics_dir / LEDGER_NAME)
    latest = am.latest_change_per_artifact(ledger)
    spec_ts = (latest.get(spec_node) or {}).get("ts", "")

    candidates: list[dict] = []
    seen: set[str] = set()
    for r in rows:
        node = r["node"]
        stem = _pre_build_stem(node)
        if not stem:
            continue                                     # R1: pre-Build authored artifacts only
        conf = r.get("confidence", "declared")
        if conf == "coarse" and not include_coarse:
            continue                                     # coarse guesses are opt-in
        depth = len(r.get("path", [node])) - 1
        if depth > 1 and not transitive:
            continue                                     # depth-1 declared by default
        bases = r.get("bases") or []
        basis = bases[0] if bases else "coarse-phase-order"   # R3/E4 empty-bases guard
        if basis == "id-reference" and not _id_substantiated_in(base_dir, node, spec_ids):
            continue                                     # R2: drop a candidate a phantom id conjured
        if node in seen:
            continue
        seen.add(node)
        up_change = latest.get(node)
        up_hash = (up_change or {}).get("hash") or _safe_checksum(base_dir / node)
        already_fresher = bool(spec_ts and up_change and _ts_lt(spec_ts, up_change.get("ts", "")))
        try:
            up_text = (base_dir / node).read_text(encoding="utf-8", errors="replace")
        except OSError:
            up_text = ""
        drift, detail = _divergence_signal(spec_text, up_text)
        candidates.append({
            "stem": stem, "target": node, "basis": basis, "confidence": conf, "depth": depth,
            "upstream_hash": up_hash or "", "discipline": DISCIPLINE_BY_STEM.get(stem, ""),
            "already_fresher": already_fresher, "drift": drift, "drift_detail": detail,
        })
    candidates.sort(key=lambda c: (c["confidence"] != "declared", c["target"]))
    return candidates, spec_meta, spec_ts


def do_refresh_detect(args, base_dir, sdlc_dir, metrics_dir) -> int:
    spec_node = _resolve_spec_node(base_dir, args.spec)
    if not spec_node:
        print(f"refresh detect — could not find spec '{args.spec}' (expected a specs/*.md path); "
              f"nothing detected.")
        return 0
    candidates, meta, _ = _detect_candidates(
        base_dir, sdlc_dir, metrics_dir, spec_node,
        transitive=getattr(args, "transitive", False),
        include_coarse=getattr(args, "include_coarse", False))
    spec_id = _spec_id_of(base_dir, spec_node)

    if getattr(args, "json", False):
        print(json.dumps({"spec": spec_id, "spec_node": spec_node, "status": meta["status"],
                          "candidates": candidates}, indent=2))
        return 0

    print(f"Refresh detection — spec {spec_id} ({spec_node})")
    print("=" * 50)
    if meta["status"] and meta["status"] != "merged":
        print(f"NOTE: spec status is '{meta['status']}', not 'merged' — this reflects intended, not "
              f"yet-shipped, reality.")
    active = [c for c in candidates if not c["already_fresher"]]
    fresher = [c for c in candidates if c["already_fresher"]]
    if not active and not fresher:
        src = meta.get("source")
        src_note = "—" if src in (None, "", "—") else src
        print("No traceable upstream — add an FR/EP/US/BR id to `source:` (or reference one in the "
              f"spec body) so a refresh can trace back to it.  (spec source: {src_note})")
        print("=" * 50)
        print("ADVISORY — nothing to refresh; nothing written (exit 0).")
        return 0

    force = getattr(args, "draft", False)
    n_elig = 0
    print("Upstream artifacts this spec traces to:")
    for c in active:
        declared = c["confidence"] == "declared"
        eligible = declared and (c["drift"] or force)
        n_elig += 1 if eligible else 0
        disc = f"[{c['discipline']}]" if c["discipline"] else ""
        conf = "" if declared else "  COARSE (phase-order guess)"
        verdict = f"DRIFT — {c['drift_detail']}" if c["drift"] else "trace-only (no drift detected)"
        print(f"  • {c['target']}   {disc}{conf}")
        print(f"        basis: {c['basis']}   {verdict}")
        arrow = _glyph("→", "->")
        if eligible:
            extra = "" if c["drift"] else " --draft"
            print(f"        {arrow} would draft:  refresh draft --spec {args.spec}{extra}")
        elif declared:
            print(f"        {arrow} review only (pass --draft to propose anyway)")
        else:
            print(f"        {arrow} review only (coarse guess — never auto-drafted)")
    for c in fresher:
        print(f"  • {c['target']}   [already fresher — changed after the spec; suppressed]")
    print("=" * 50)
    print(f"{len(active)} candidate(s), {n_elig} draft-eligible, {len(fresher)} already-fresher. "
          f"Coarse guesses are never auto-drafted.")
    print("ADVISORY — review-first; nothing drafted or written (exit 0).")
    return 0


def do_refresh_scan(args, base_dir, sdlc_dir, metrics_dir) -> int:
    specs = ts.scan_specs(base_dir / "specs")
    merged = [s for s in specs if s.get("status") == "merged"]
    results: list[dict] = []
    for s in merged:
        spec_node = _normalize_artifact_arg(base_dir, s["path"])
        cands, _, _ = _detect_candidates(
            base_dir, sdlc_dir, metrics_dir, spec_node,
            transitive=getattr(args, "transitive", False),
            include_coarse=getattr(args, "include_coarse", False))
        active = [c for c in cands if not c["already_fresher"]]
        drifted = [c for c in active if c["drift"] and c["confidence"] == "declared"]
        results.append({
            "spec": s["id"], "spec_node": spec_node, "name": s["name"],
            "candidates": len(active), "drifted": len(drifted),
            "targets": [c["target"] for c in active],
            "drifted_targets": [c["target"] for c in drifted],
        })

    if getattr(args, "json", False):
        total_drift = sum(r["drifted"] for r in results)
        print(json.dumps({"merged_specs": len(merged), "drifted_total": total_drift,
                          "results": results}, indent=2))
        return 0

    print("Refresh scan — merged specs vs their pre-Build upstreams")
    print("=" * 50)
    if not merged:
        print("  (no merged specs — nothing to back-propagate)")
        print("=" * 50)
        print("ADVISORY — nothing to refresh; nothing written (exit 0).")
        return 0
    total_drift = 0
    for r in results:
        if r["candidates"] == 0:
            continue
        total_drift += r["drifted"]
        flag = f"   {_glyph('⚠', '(!)')} {r['drifted']} may have drifted" if r["drifted"] else ""
        print(f"  spec {r['spec']} {r['name']}: {r['candidates']} upstream candidate(s){flag}")
        for t in r["drifted_targets"]:
            print(f"        drift {_glyph('→', '->')} {t}")
    print("=" * 50)
    print(f"{len(merged)} merged spec(s); {total_drift} upstream artifact(s) may have drifted from a "
          f"merged spec.")
    print("ADVISORY — review one with `refresh detect --spec <spec>` (exit 0).")
    return 0


# --- refresh write path: draft -> apply/reject -> status --------------------------------------
# A `.proposed` per eligible upstream + a per-spec candidates.json (pins the draft-time upstream hash
# and the routed discipline). All under .sdlc/refresh/<spec-stem>/ — gitignored, transient, deleted on
# apply AND reject. The spec-stem keys the dir (always filesystem-safe); the frontmatter spec id keys
# the ledger `source_spec` rider so REFRESHED is attributable per spec.

def _refresh_spec_dir(sdlc_dir: Path, spec_node: str) -> Path:
    return refresh_dir_of(sdlc_dir) / Path(spec_node).stem


def _proposed_path(sdlc_dir: Path, spec_node: str, stem: str) -> Path:
    return _refresh_spec_dir(sdlc_dir, spec_node) / f"{stem}.proposed"


def _candidates_path(sdlc_dir: Path, spec_node: str) -> Path:
    return _refresh_spec_dir(sdlc_dir, spec_node) / "candidates.json"


def _load_candidates(sdlc_dir: Path, spec_node: str) -> dict:
    p = _candidates_path(sdlc_dir, spec_node)
    if not p.is_file():
        return {}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_candidates(sdlc_dir: Path, spec_node: str, data: dict) -> None:
    try:
        p = _candidates_path(sdlc_dir, spec_node)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def _clear_draft(sdlc_dir: Path, spec_node: str, stem: str) -> None:
    """Remove one stem's `.proposed` and drop it from candidates.json; delete the spec dir when the
    last draft is resolved. Best-effort — a cleanup fault never changes exit code or stdout."""
    try:
        _proposed_path(sdlc_dir, spec_node, stem).unlink()
    except OSError:
        pass
    data = _load_candidates(sdlc_dir, spec_node)
    if data:
        remaining = [c for c in data.get("candidates", []) if c.get("stem") != stem]
        if remaining:
            data["candidates"] = remaining
            _save_candidates(sdlc_dir, spec_node, data)
        else:
            try:
                _candidates_path(sdlc_dir, spec_node).unlink()
            except OSError:
                pass
    spec_dir = _refresh_spec_dir(sdlc_dir, spec_node)
    try:
        if spec_dir.is_dir() and not any(spec_dir.iterdir()):
            spec_dir.rmdir()
    except OSError:
        pass


def _discipline_of(node: str) -> str:
    return DISCIPLINE_BY_STEM.get(_pre_build_stem(node) or "", "")


def _eligible_candidates(candidates: list[dict], *, force: bool, stem: str | None) -> list[dict]:
    """The draftable subset: declared, not already-fresher, and (drifted OR --draft). Coarse guesses
    are never draftable (mirrors detect). Optionally narrowed to one stem."""
    out = [c for c in candidates
           if c["confidence"] == "declared" and not c["already_fresher"] and (c["drift"] or force)]
    if stem:
        out = [c for c in out if c["stem"] == stem]
    return out


def do_refresh_draft(args, base_dir, sdlc_dir, metrics_dir) -> int:
    spec_node = _resolve_spec_node(base_dir, args.spec)
    if not spec_node:
        print(f"refresh draft — could not find spec '{args.spec}' (expected a specs/*.md path); "
              f"nothing drafted.")
        return 0
    spec_id = _spec_id_of(base_dir, spec_node)
    candidates, meta, _ = _detect_candidates(
        base_dir, sdlc_dir, metrics_dir, spec_node,
        transitive=getattr(args, "transitive", False),
        include_coarse=getattr(args, "include_coarse", False))
    force = getattr(args, "draft", False)
    eligible = _eligible_candidates(candidates, force=force, stem=getattr(args, "stem", None))

    if not eligible:
        drifted = [c for c in candidates
                   if c["confidence"] == "declared" and not c["already_fresher"] and c["drift"]]
        if drifted and not force:  # unreachable given the filter, kept for clarity of intent
            print("refresh draft — drifted candidates exist; nothing selected.")
        elif any(c["confidence"] == "declared" and not c["already_fresher"] for c in candidates):
            print("refresh draft — no drift detected on any declared upstream; nothing drafted. "
                  "Pass --draft to propose a refresh anyway (review-first default).")
        else:
            print("refresh draft — no draftable upstream for this spec (no declared, in-vocabulary "
                  "candidate). Add an FR/EP/US/BR id to `source:`. Nothing drafted.")
        return 0

    existed = _candidates_path(sdlc_dir, spec_node).is_file()
    records: list[dict] = []
    written: list[str] = []
    for c in eligible:
        target = c["target"]
        try:
            cur = (base_dir / target).read_bytes()
        except OSError:
            continue  # can't read the upstream — skip it (best-effort), never crash
        pp = _proposed_path(sdlc_dir, spec_node, c["stem"])
        try:
            pp.parent.mkdir(parents=True, exist_ok=True)
            pp.write_bytes(cur)  # seed with the CURRENT upstream; the discipline agent edits this copy
        except OSError:
            continue
        records.append({
            "stem": c["stem"], "target": target, "basis": c["basis"],
            "upstream_hash": hash_bytes(cur),  # PINNED to the exact bytes copied (staleness guard)
            "discipline": c["discipline"],
            "proposed": _proposed_path(sdlc_dir, spec_node, c["stem"]).name,
        })
        written.append(c["stem"])

    if not records:
        print("refresh draft — could not stage any draft (upstream unreadable or store not "
              "writable); nothing drafted.")
        return 0
    _save_candidates(sdlc_dir, spec_node, {
        "spec_id": spec_id, "spec_node": spec_node, "candidates": records})

    if getattr(args, "json", False):
        print(json.dumps({"spec": spec_id, "spec_node": spec_node,
                          "drafted": written, "candidates": records,
                          "overwrote_existing": existed}, indent=2))
        return 0

    if existed:
        print(f"refresh draft — re-drafting spec {spec_id}: previous drafts overwritten with the "
              f"current upstream content.")
    print(f"Staged {len(records)} draft(s) for spec {spec_id} under .sdlc/refresh/{Path(spec_node).stem}/:")
    for r in records:
        disc = f"  {_glyph('→', '->')} have {r['discipline']} edit it" if r["discipline"] else ""
        print(f"  • {r['stem']}.proposed   (from {r['target']}){disc}")
    print("-" * 50)
    print("The agent edits ONLY the .proposed; the real artifact stays untouched (the One Rule).")
    print(f"Then a named human runs:  refresh apply --spec {args.spec} <stem> --actor <you>")
    print("ADVISORY — only the .proposed drafts were written; no artifact changed (exit 0).")
    return 0


def _candidate_for_stem(args, base_dir, sdlc_dir, metrics_dir, spec_node, stem) -> dict | None:
    """The candidate record for one stem — from candidates.json if present (carries the pinned
    draft-time hash), else a fresh detect (so `reject` can target a never-drafted candidate)."""
    for c in _load_candidates(sdlc_dir, spec_node).get("candidates", []):
        if c.get("stem") == stem:
            return c
    cands, _, _ = _detect_candidates(
        base_dir, sdlc_dir, metrics_dir, spec_node,
        transitive=getattr(args, "transitive", False),
        include_coarse=getattr(args, "include_coarse", False))
    for c in cands:
        if c["stem"] == stem:
            return {"stem": stem, "target": c["target"], "basis": c["basis"],
                    "upstream_hash": c["upstream_hash"], "discipline": c["discipline"]}
    return None


def do_refresh_apply(args, base_dir, sdlc_dir, metrics_dir) -> int:
    spec_node = _resolve_spec_node(base_dir, args.spec)
    if not spec_node:
        print(f"refresh apply — could not find spec '{args.spec}' (expected a specs/*.md path); "
              f"nothing written.")
        return 0
    spec_id = _spec_id_of(base_dir, spec_node)
    stem = args.stem
    data = _load_candidates(sdlc_dir, spec_node)
    rec = next((c for c in data.get("candidates", []) if c.get("stem") == stem), None)
    if rec is None:
        print(f"refresh apply — no draft for stem '{stem}' of spec {spec_id}. "
              f"Run `refresh draft --spec {args.spec}` first; nothing written.")
        return 0
    target = rec["target"]
    proposed = _proposed_path(sdlc_dir, spec_node, stem)
    if not proposed.is_file():
        print(f"refresh apply — the {stem}.proposed draft is missing; re-run `refresh draft`. "
              f"Nothing written.")
        return 0
    try:
        new_bytes = proposed.read_bytes()
    except OSError:
        print(f"refresh apply — could not read the {stem}.proposed draft; nothing written.")
        return 0

    # Staleness guard: the upstream must not have moved on disk since the draft pinned it.
    pinned = rec.get("upstream_hash", "")
    cur_hash = _safe_checksum(base_dir / target)
    if pinned and cur_hash and cur_hash != pinned:
        print(f"refresh apply — {target} moved since the draft (pinned {pinned}, now {cur_hash}); "
              f"re-run `refresh detect`/`draft` so the proposal reflects the current upstream. "
              f"Nothing written.")
        return 0
    if hash_bytes(new_bytes) == cur_hash:
        print(f"refresh apply — the {stem}.proposed draft is identical to {target} (the agent made "
              f"no edit); nothing to apply. Nothing written.")
        return 0

    try:
        cur_bytes = (base_dir / target).read_bytes() if (base_dir / target).is_file() else b""
    except OSError:
        cur_bytes = b""
    diff_text = _unified(cur_bytes, new_bytes, f"{target}@current", f"{target}@proposed({spec_id})")
    diffhash = hash_bytes(diff_text.encode("utf-8"))

    # Preview until the human echoes the diffhash (mirrors rollback's preview->confirm handshake).
    if not (getattr(args, "reviewed", None) or "").strip():
        print(f"Refresh preview — apply {stem}.proposed to {target} (from spec {spec_id}):")
        print("-" * 50)
        sys.stdout.write(diff_text if diff_text.endswith("\n") else diff_text + "\n")
        print("-" * 50)
        print(f"To apply: refresh apply --spec {args.spec} {stem} --actor <you> --reviewed {diffhash}")
        print("ADVISORY — preview only; nothing written (exit 0).")
        return 0

    ok, msg = _confirm_guards(target, sdlc_dir, args, diffhash)
    if not ok:
        print(f"refresh apply — {msg}")
        return 0
    ok, msg = mutate_artifact(
        base_dir, metrics_dir, versions_dir_of(sdlc_dir), target, new_bytes,
        event="refreshed", target_id=spec_id, actor=args.actor,
        reason=getattr(args, "reason", "") or f"auto-refresh from merged spec {spec_id}",
        decision_ref=getattr(args, "decision_ref", "") or "", source_spec=spec_id)
    if not ok:
        print(f"refresh apply — {msg}")
        return 0
    _clear_draft(sdlc_dir, spec_node, stem)
    print(f"Refreshed {target} from spec {spec_id} by {args.actor} (recorded as a `refreshed` "
          f"change, attributed to the spec; rollback via /sprd-version).")
    _print_apply_impact(base_dir, sdlc_dir, target)
    print("Open a DL-NN decision-log item for this refresh, then re-gate the affected phase with "
          "/sprd-gate (this command writes no state.yaml).")
    return 0


def _print_apply_impact(base_dir: Path, sdlc_dir: Path, target: str) -> None:
    """Read-only forward impact of the refresh: what may now go stale downstream (the forward
    engine flags it on the next /sprd-status). Never writes; a lineage fault is swallowed."""
    try:
        graph = al.build_graph(base_dir, sdlc_dir)
        rows = al.downstream_of(graph, target)
    except Exception:
        return
    if not rows:
        return
    print(f"  Impact — {len(rows)} downstream artifact(s) may now be stale relative to {target}:")
    for r in sorted(rows, key=lambda x: (x["confidence"], x["node"]))[:8]:
        label = "declared" if r["confidence"] == "declared" else "coarse"
        print(f"      • {r['node']}  [{label}]")


def do_refresh_reject(args, base_dir, sdlc_dir, metrics_dir) -> int:
    spec_node = _resolve_spec_node(base_dir, args.spec)
    if not spec_node:
        print(f"refresh reject — could not find spec '{args.spec}' (expected a specs/*.md path); "
              f"nothing recorded.")
        return 0
    spec_id = _spec_id_of(base_dir, spec_node)
    stem = args.stem
    rec = _candidate_for_stem(args, base_dir, sdlc_dir, metrics_dir, spec_node, stem)
    if rec is None:
        print(f"refresh reject — no candidate upstream for stem '{stem}' of spec {spec_id}; "
              f"nothing recorded.")
        return 0
    target = rec["target"]
    # R4: record NOT_AFFECTED as (downstream = the upstream artifact, upstream = the spec). This
    # reverse edge is absent from the forward lineage graph, so compute_staleness never renders it —
    # the rejection lives only in this refresh view. Pin to the spec's hash (sticky-reject caveat).
    entry = am.disposition_entry(
        ts=now_iso(), downstream=target, upstream=spec_node,
        upstream_hash=_safe_checksum(base_dir / spec_node), disposition="NOT_AFFECTED",
        owner=getattr(args, "owner", "") or "", reason=getattr(args, "reason", "") or "",
        actor=getattr(args, "actor", "") or "")
    append_entries(metrics_dir, [entry])
    _clear_draft(sdlc_dir, spec_node, stem)
    off, why = am.validate_disposition(entry)
    tag = "off the books" if off else f"STILL COUNTS as debt ({why})"
    print(f"Recorded NOT_AFFECTED — {target} judged unaffected by spec {spec_id}: {tag}.")
    if not (getattr(args, "reason", "") or "").strip():
        print("  Pass --reason TEXT so the rejection is off the books (honest counting).")
    return 0


def _refresh_status_rows(base_dir, sdlc_dir, metrics_dir, spec_node, *, transitive, include_coarse):
    """(spec_id, meta, rows) for one spec. Each row: {target, stem, discipline, disposition,
    off_books, drift}. Universe = active candidates ∪ this-spec REFRESHED ∪ this-spec dispositions."""
    spec_id = _spec_id_of(base_dir, spec_node)
    candidates, meta, _ = _detect_candidates(
        base_dir, sdlc_dir, metrics_dir, spec_node,
        transitive=transitive, include_coarse=include_coarse)
    ledger = load_ledger(metrics_dir / LEDGER_NAME)
    refreshed = {e.get("artifact") for e in ledger
                 if am.is_change_entry(e) and am.normalize_event(e.get("event")) == "refreshed"
                 and e.get("source_spec") == spec_id and e.get("artifact")}
    disp_by_target: dict[str, dict] = {}
    for e in ledger:  # ledger is time-ordered; last write wins
        if am.is_disposition_entry(e) and e.get("upstream") == spec_node and e.get("downstream"):
            disp_by_target[e["downstream"]] = e

    meta_by_target: dict[str, dict] = {}
    for c in candidates:
        if not c["already_fresher"]:  # active OPEN universe (already-fresher isn't this spec's debt)
            meta_by_target.setdefault(c["target"], {"stem": c["stem"], "drift": c["drift"]})
    for t in refreshed | set(disp_by_target):
        meta_by_target.setdefault(t, {"stem": _pre_build_stem(t) or "", "drift": False})

    rows = []
    for t, m in meta_by_target.items():
        if t in refreshed:
            disp, off = "REFRESHED", True   # derived from a real content change — trustworthy
        elif t in disp_by_target:
            e = disp_by_target[t]
            disp = am.normalize_disposition(e.get("disposition")) or "OPEN"
            off, _ = am.validate_disposition(e)
        else:
            disp, off = "OPEN", False
        rows.append({"target": t, "stem": m["stem"], "discipline": _discipline_of(t),
                     "disposition": disp, "off_books": off, "drift": m.get("drift", False)})
    rows.sort(key=lambda r: r["target"])
    return spec_id, meta, rows


def _status_counts(rows: list[dict]) -> dict:
    refreshed = sum(1 for r in rows if r["disposition"] == "REFRESHED")
    open_debt = sum(1 for r in rows
                    if r["disposition"] == "OPEN"
                    or (r["disposition"] in ("ACKNOWLEDGED", "NOT_AFFECTED") and not r["off_books"]))
    off_books = sum(1 for r in rows
                    if r["disposition"] in ("ACKNOWLEDGED", "NOT_AFFECTED") and r["off_books"])
    return {"total": len(rows), "open": open_debt, "refreshed": refreshed, "off_books": off_books}


def do_refresh_status(args, base_dir, sdlc_dir, metrics_dir) -> int:
    transitive = getattr(args, "transitive", False)
    include_coarse = getattr(args, "include_coarse", False)

    if getattr(args, "spec", None):
        spec_node = _resolve_spec_node(base_dir, args.spec)
        if not spec_node:
            print(f"refresh status — could not find spec '{args.spec}'; no data.")
            return 0
        spec_id, meta, rows = _refresh_status_rows(
            base_dir, sdlc_dir, metrics_dir, spec_node,
            transitive=transitive, include_coarse=include_coarse)
        counts = _status_counts(rows)
        if getattr(args, "json", False):
            print(json.dumps({"spec": spec_id, "spec_node": spec_node,
                              "counts": counts, "rows": rows}, indent=2))
            return 0
        print(f"Refresh status — spec {spec_id} ({spec_node})")
        print("=" * 50)
        if not rows:
            print("  (no upstream candidates and no recorded refresh activity — no data)")
            print("=" * 50)
            print("ADVISORY — nothing to report (exit 0).")
            return 0
        for r in rows:
            disc = f"  [{r['discipline']}]" if r["discipline"] else ""
            flag = "" if r["off_books"] or r["disposition"] == "OPEN" else f"  {_glyph('⚠', '(!)')} still counts"
            print(f"  {r['target']}{disc}")
            print(f"      {r['disposition']}{flag}")
        print("=" * 50)
        print(f"{counts['total']} upstream(s): {counts['open']} open · {counts['refreshed']} refreshed "
              f"· {counts['off_books']} off the books")
        print("ADVISORY — honest counting; a mislabeled disposition still counts as debt (exit 0).")
        return 0

    # No --spec: a rollup across every merged spec.
    merged = [s for s in ts.scan_specs(base_dir / "specs") if s.get("status") == "merged"]
    rollup = []
    for s in merged:
        sn = _normalize_artifact_arg(base_dir, s["path"])
        _, _, rows = _refresh_status_rows(base_dir, sdlc_dir, metrics_dir, sn,
                                          transitive=transitive, include_coarse=include_coarse)
        c = _status_counts(rows)
        rollup.append({"spec": s["id"], "name": s["name"], **c})
    if getattr(args, "json", False):
        print(json.dumps({"merged_specs": len(merged),
                          "open_total": sum(r["open"] for r in rollup),
                          "results": rollup}, indent=2))
        return 0
    print("Refresh status — all merged specs")
    print("=" * 50)
    if not merged:
        print("  (no merged specs — no data)")
        print("=" * 50)
        print("ADVISORY — nothing to report (exit 0).")
        return 0
    for r in rollup:
        if r["total"] == 0:
            continue
        print(f"  spec {r['spec']} {r['name']}: {r['open']} open · {r['refreshed']} refreshed "
              f"· {r['off_books']} off the books")
    print("=" * 50)
    print(f"{len(merged)} merged spec(s); {sum(r['open'] for r in rollup)} open upstream refresh(es). "
          f"Detail one with `refresh status --spec <spec>`.")
    print("ADVISORY — honest counting (exit 0).")
    return 0


def cmd_refresh(args) -> int:
    base_dir, sdlc_dir, metrics_dir = resolve_paths(args)
    recover_pending(base_dir, versions_dir_of(sdlc_dir))  # complete any interrupted mutate first
    fn = _REFRESH_DISPATCH.get(args.refresh_cmd)
    if fn is None:
        print("refresh: choose detect | scan | draft | apply | reject | status")
        return 0
    return fn(args, base_dir, sdlc_dir, metrics_dir)


# The dispatch is the single source of truth for the refresh verbs.
_REFRESH_DISPATCH = {
    "detect": do_refresh_detect,
    "scan": do_refresh_scan,
    "draft": do_refresh_draft,
    "apply": do_refresh_apply,
    "reject": do_refresh_reject,
    "status": do_refresh_status,
}


# --- CLI ---------------------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Advisory artifact change-ledger, staleness, and impact (never blocks; exit 0)")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    src = common.add_mutually_exclusive_group()
    src.add_argument("--state", help="Path to .sdlc/state.yaml (workflow mode)")
    src.add_argument("--repo", default=".", help="Repo root containing .sdlc/ (standalone; default cwd)")

    p_rec = sub.add_parser("record", parents=[common], help="Append change or disposition entries")
    p_rec.add_argument("--scan", action="store_true", help="Hash-walk artifacts; record new/drifted files")
    p_rec.add_argument("--artifact", help="Record one explicit change to this artifact path")
    p_rec.add_argument("--target", help="Sub-artifact id the change touched (e.g. FR-012)")
    p_rec.add_argument("--event", default="revised", help="Change event (created/revised/refreshed/snapshot)")
    p_rec.add_argument("--phase", help="Phase id the artifact belongs to (inferred if omitted)")
    p_rec.add_argument("--actor", help="Who made the change")
    p_rec.add_argument("--reason", help="Why the change was made")
    p_rec.add_argument("--decision-ref", dest="decision_ref", help="Linked decision-log id (DL-NN)")
    p_rec.add_argument("--disposition", help="Record a staleness disposition (OPEN/ACKNOWLEDGED/NOT_AFFECTED; REFRESHED is derived, not recordable)")
    p_rec.add_argument("--downstream", help="Downstream artifact for a disposition")
    p_rec.add_argument("--upstream", help="Upstream artifact for a disposition")
    p_rec.add_argument("--upstream-hash", dest="upstream_hash", help="Pin the disposition to this upstream hash")
    p_rec.add_argument("--owner", help="Owner (required for ACKNOWLEDGED to be off the books)")

    p_imp = sub.add_parser("impact", parents=[common], help="Forward: what a change here could make stale")
    p_imp.add_argument("target", help="An id (FR-012) or an artifact path")
    p_imp.add_argument("--json", action="store_true", help="Emit JSON")

    p_rep = sub.add_parser("report", parents=[common], help="Freshness dashboard / history")
    p_rep.add_argument("--history", help="Backward change trail for an id or artifact path")
    p_rep.add_argument("--artifact", help="Scope the dashboard to one artifact (id or path)")
    p_rep.add_argument("--phase", help="Scope the dashboard to one phase id")
    p_rep.add_argument("--since", help="Filter to changes on/after this ISO date")
    p_rep.add_argument("--json", action="store_true", help="Emit JSON")

    _add_version_cli(sub, common)
    _add_refresh_cli(sub, common)

    args = parser.parse_args()
    if args.command == "record":
        rc = cmd_record(args)
    elif args.command == "impact":
        rc = cmd_impact(args)
    elif args.command == "version":
        rc = cmd_version(args)
    elif args.command == "refresh":
        rc = cmd_refresh(args)
    else:
        rc = cmd_report(args)
    # Advisory by construction — never a non-zero exit.
    sys.exit(0 if rc is None else 0)


def _add_version_cli(sub, common) -> None:
    """`version` subcommand group: content history / diff / rollback / gc. Leaf-level --state/--repo
    so the flag follows the verb (audit_artifacts.py version list <art> --repo <path>)."""
    p_ver = sub.add_parser("version", help="Artifact content version history (list/show/diff/rollback/gc)")
    vsub = p_ver.add_subparsers(dest="version_cmd", required=True)

    v_list = vsub.add_parser("list", parents=[common], help="List v1..vN for an artifact")
    v_list.add_argument("artifact", help="An id (FR-012) or an artifact path")
    v_list.add_argument("--json", action="store_true", help="Emit JSON")

    v_show = vsub.add_parser("show", parents=[common], help="Print the content of one version")
    v_show.add_argument("artifact", help="An id (FR-012) or an artifact path")
    v_show.add_argument("ref", nargs="?", default="latest", help="vN | latest | prev | <hashprefix>")

    v_diff = vsub.add_parser("diff", parents=[common],
                             help="Unified diff between two versions (default prev->latest)")
    v_diff.add_argument("artifact", help="An id (FR-012) or an artifact path")
    v_diff.add_argument("a", nargs="?", default=None, help="from ref (default: prev)")
    v_diff.add_argument("b", nargs="?", default=None, help="to ref (default: latest)")

    v_rb = vsub.add_parser("rollback", parents=[common],
                           help="Restore an artifact to an earlier version (preview by default)")
    v_rb.add_argument("artifact", help="An id (FR-012) or an artifact path")
    v_rb.add_argument("ref", nargs="?", default="prev", help="vN | latest | prev | <hashprefix>")
    v_rb.add_argument("--confirm", action="store_true", help="Apply the rollback (default: preview)")
    v_rb.add_argument("--actor", help="Named human owning the change (required with --confirm)")
    v_rb.add_argument("--reviewed", help="Echo the diffhash from the preview to confirm you saw it")
    v_rb.add_argument("--ack-signoff", dest="ack_signoff", action="store_true",
                      help="Acknowledge changing a signed-off / completed-phase artifact")
    v_rb.add_argument("--decision-ref", dest="decision_ref", help="Linked decision-log id (DL-NN)")

    v_gc = vsub.add_parser("gc", parents=[common],
                           help="Prune old snapshots, keeping the newest N per artifact (preview by default)")
    v_gc.add_argument("--keep", type=int, default=10, help="Retain the newest N versions per artifact")
    v_gc.add_argument("--apply", action="store_true", help="Actually delete (default: preview)")


def _add_refresh_cli(sub, common) -> None:
    """`refresh` subcommand group: reverse-propagation. detect/scan read-only; draft/apply/reject/
    status are the draft+confirm write path (a named human `apply`s — the One Rule)."""
    p_ref = sub.add_parser(
        "refresh", help="Reverse-propagation: surface & confirm the pre-Build edits a merged spec implies")
    rsub = p_ref.add_subparsers(dest="refresh_cmd", required=True)

    r_det = rsub.add_parser("detect", parents=[common],
                            help="List the pre-Build upstreams a spec traces to (review-only)")
    r_det.add_argument("--spec", required=True, help="Path to the spec (specs/NNNN-*.md)")
    r_det.add_argument("--draft", action="store_true",
                       help="Mark all declared candidates draft-eligible, not only drifted ones")
    r_det.add_argument("--transitive", action="store_true",
                       help="Include transitive (depth>1) declared upstreams")
    r_det.add_argument("--include-coarse", dest="include_coarse", action="store_true",
                       help="Include coarse phase-order guesses (listed, never auto-drafted)")
    r_det.add_argument("--json", action="store_true", help="Emit JSON")

    r_scan = rsub.add_parser("scan", parents=[common],
                             help="Detect across all merged specs (backs the /sprd-status drift nudge)")
    r_scan.add_argument("--transitive", action="store_true",
                        help="Include transitive declared upstreams")
    r_scan.add_argument("--include-coarse", dest="include_coarse", action="store_true",
                        help="Include coarse phase-order guesses")
    r_scan.add_argument("--json", action="store_true", help="Emit JSON")

    r_draft = rsub.add_parser("draft", parents=[common],
                              help="Seed a .proposed copy per eligible upstream for a discipline agent to edit")
    r_draft.add_argument("--spec", required=True, help="Path to the spec (specs/NNNN-*.md)")
    r_draft.add_argument("stem", nargs="?", default=None,
                         help="Draft only this stem (default: every eligible upstream)")
    r_draft.add_argument("--draft", action="store_true",
                         help="Draft declared candidates even without a drift signal (review-first default)")
    r_draft.add_argument("--transitive", action="store_true", help="Include transitive declared upstreams")
    r_draft.add_argument("--include-coarse", dest="include_coarse", action="store_true",
                         help="Include coarse guesses (still never draft-eligible)")
    r_draft.add_argument("--json", action="store_true", help="Emit JSON")

    r_app = rsub.add_parser("apply", parents=[common],
                            help="Apply a reviewed .proposed to its upstream (named human; preview until --reviewed)")
    r_app.add_argument("--spec", required=True, help="Path to the spec (specs/NNNN-*.md)")
    r_app.add_argument("stem", help="Which drafted stem to apply (e.g. requirements)")
    r_app.add_argument("--actor", help="Named human owning the change (never a discipline agent)")
    r_app.add_argument("--reviewed", help="Echo the diffhash from the preview to confirm you saw it")
    r_app.add_argument("--ack-signoff", dest="ack_signoff", action="store_true",
                       help="Acknowledge changing a signed-off / completed-phase artifact")
    r_app.add_argument("--reason", help="Why the refresh was applied")
    r_app.add_argument("--decision-ref", dest="decision_ref", help="Linked decision-log id (DL-NN)")

    r_rej = rsub.add_parser("reject", parents=[common],
                            help="Record NOT_AFFECTED for an upstream a spec does not ripple to")
    r_rej.add_argument("--spec", required=True, help="Path to the spec (specs/NNNN-*.md)")
    r_rej.add_argument("stem", help="Which candidate stem to reject (e.g. business-rules)")
    r_rej.add_argument("--reason", help="Why it is unaffected (REQUIRED to be off the books)")
    r_rej.add_argument("--owner", help="Who judged it unaffected")
    r_rej.add_argument("--actor", help="Who recorded the disposition")
    r_rej.add_argument("--transitive", action="store_true", help="Include transitive declared upstreams")
    r_rej.add_argument("--include-coarse", dest="include_coarse", action="store_true",
                       help="Include coarse guesses when resolving the stem")

    r_stat = rsub.add_parser("status", parents=[common],
                             help="Per-spec upstream refresh dispositions (honest counting)")
    r_stat.add_argument("--spec", help="Path to one spec (default: rollup across all merged specs)")
    r_stat.add_argument("--transitive", action="store_true", help="Include transitive declared upstreams")
    r_stat.add_argument("--include-coarse", dest="include_coarse", action="store_true",
                        help="Include coarse guesses")
    r_stat.add_argument("--json", action="store_true", help="Emit JSON")


if __name__ == "__main__":
    main()
