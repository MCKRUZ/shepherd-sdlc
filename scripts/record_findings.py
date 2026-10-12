"""record_findings.py — give review findings memory, a disposition, and an honesty check.

The grader (/sprd-review) overwrites its `review-report.md` every run, so a finding and its
history vanish. This tool reads the report's machine-readable `## Gate Results` block and appends
each finding to an append-only ledger, `.sdlc/metrics/findings-log.jsonl`, so the finding survives
the next review and its disposition can be tracked across rounds.

Two things it computes on the accumulated ledger:
  - Open HIGH+ debt — the number the human Checker weighs at the merge bar (advisory; the grader
    advises, never blocks — the-rails.md §4).
  - FIXED-claim check — a finding marked FIXED whose target file is byte-identical to when it was
    OPEN is a false claim (FIXED_CLAIM_MISMATCH). This is factual, not a judgment, so `report
    --strict` may exit non-zero on it; default stays advisory.

Standalone or Workflow (CLAUDE.md design rule):
  record: record_findings.py record --report .sdlc/artifacts/02-design/review-report.md --repo .
          record_findings.py record --report ... --state .sdlc/state.yaml
  report: record_findings.py report --repo .   |   report --state .sdlc/state.yaml [--strict] [--json]
"""

import argparse
import fnmatch
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_spec as cs
import findings_model as fm

# Columns the grader writes in the `## Gate Results` table (see agents/multi-reviewer.md).
FINDING_COLUMNS = ("id", "category", "severity", "target", "disposition", "detail")

# Disposition-evidence fields that ride in a disposition cell like ACCEPTED_RISK(approver=..; date=..).
EVIDENCE_FIELDS = ("split_to", "owner", "approver", "date", "reason", "review_condition")


def compute_sha(file_path: Path) -> str:
    """SHA-256 of a file (first 16 hex chars) — same shape as check_gates.compute_checksum."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()[:16]}"


def _is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c.strip() or "-") for c in cells)


def _parse_table(block: str) -> list[dict]:
    """Parse the first GitHub-flavoured markdown table in a block into header->value dicts."""
    rows, header = [], None
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if _is_separator_row(cells):
            continue
        if header is None:
            header = [c.lower() for c in cells]
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def _parse_disposition_cell(cell: str) -> tuple[str, dict]:
    """'ACCEPTED_RISK(approver=Jane Doe; date=2026-07-06; reason=..; review_condition=..)'
    -> ('ACCEPTED_RISK', {approver:.., date:.., ...}). Bare 'OPEN' -> ('OPEN', {})."""
    cell = (cell or "").strip()
    m = re.match(r"^([A-Za-z_]+)\s*(?:\((.*)\))?\s*$", cell)
    if not m:
        return cell.upper(), {}
    disp = m.group(1).upper()
    fields: dict[str, str] = {}
    if m.group(2):
        for part in m.group(2).split(";"):
            if "=" in part:
                k, _, v = part.partition("=")
                fields[k.strip()] = v.strip()
    return disp, fields


def parse_findings_block(report_text: str) -> tuple[list[dict], str | None]:
    """Extract findings from the top-level `## Gate Results` block. Returns (findings, error).

    A missing block means the review is incomplete — the grader's verdict must be machine-readable,
    not buried in prose (the reference harness's hard-won lesson: reviewers hid the block inside diff
    bodies to dodge parsing). We refuse rather than silently pass.
    """
    m = re.search(r"^##\s+Gate Results\s*$", report_text, re.IGNORECASE | re.MULTILINE)
    if not m:
        return [], "no top-level `## Gate Results` section — the review report is incomplete"
    nxt = re.compile(r"^##\s+", re.MULTILINE).search(report_text, m.end())
    block = report_text[m.end(): nxt.start() if nxt else len(report_text)]
    findings = []
    for row in _parse_table(block):
        f = {col: (row.get(col) or "").strip() for col in FINDING_COLUMNS}
        disp, evidence = _parse_disposition_cell(f["disposition"])
        f["disposition"] = disp
        f.update(evidence)
        if f["id"] or f["category"] or f["detail"]:  # skip blank rows
            findings.append(f)
    if not findings:
        return [], "`## Gate Results` block has no finding rows"
    return findings, None


def resolve_target_sha(target: str, base_dir: Path) -> str | None:
    """Content hash of the file a finding points at, or None if it can't be resolved/read.

    None is honest 'unverifiable' — the FIXED-claim check skips it rather than false-accuse.
    """
    if not target:
        return None
    file_part = target.split(":", 1)[0].strip()
    if not file_part:
        return None
    candidates = [base_dir / file_part, base_dir / ".sdlc" / "artifacts" / file_part]
    for cand in candidates:
        if cand.is_file():
            return compute_sha(cand)
    if "/" not in file_part and "\\" not in file_part:  # bare filename — search
        for match in base_dir.rglob(file_part):
            if match.is_file():
                return compute_sha(match)
    return None


def build_entry(finding: dict, report_name: str, base_dir: Path, timestamp: str) -> dict:
    entry = {
        "timestamp": timestamp,
        "report": report_name,
        "id": finding.get("id", ""),
        "category": finding.get("category", ""),
        "severity": fm.normalize_severity(finding.get("severity")) or finding.get("severity", ""),
        "target": finding.get("target", ""),
        "disposition": fm.normalize_disposition(finding.get("disposition")) or finding.get("disposition", ""),
        "fingerprint": fm.fingerprint(finding),
        "target_sha": resolve_target_sha(finding.get("target", ""), base_dir),
        "detail": finding.get("detail", ""),
    }
    for k in EVIDENCE_FIELDS:
        if finding.get(k):
            entry[k] = finding[k]
    return entry


def load_ledger(ledger_path: Path) -> list[dict]:
    if not ledger_path.exists():
        return []
    out = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def current_state(ledger: list[dict]) -> dict[str, dict]:
    """Latest ledger entry per fingerprint — the finding's current disposition."""
    latest: dict[str, dict] = {}
    for e in ledger:  # ledger is append-only in time order
        fp = e.get("fingerprint")
        if fp:
            latest[fp] = e
    return latest


def find_fixed_claim_mismatches(ledger: list[dict]) -> list[dict]:
    """Findings marked FIXED whose target file never changed since they were OPEN.

    For each fingerprint whose latest entry is FIXED with a resolvable target_sha, look back for the
    most recent OPEN/POSTPONED entry with a resolvable target_sha; equal hashes => the fix claim is
    false. Unresolvable hashes are skipped (unverifiable, never a false accusation).
    """
    by_fp: dict[str, list[dict]] = {}
    for e in ledger:
        by_fp.setdefault(e.get("fingerprint"), []).append(e)
    mismatches = []
    for fp, entries in by_fp.items():
        if not fp:
            continue
        latest = entries[-1]
        if fm.normalize_disposition(latest.get("disposition")) != "FIXED" or not latest.get("target_sha"):
            continue
        prior_open = [
            e for e in entries[:-1]
            if fm.normalize_disposition(e.get("disposition")) in ("OPEN", "POSTPONED") and e.get("target_sha")
        ]
        if prior_open and prior_open[-1]["target_sha"] == latest["target_sha"]:
            mismatches.append(latest)
    return mismatches


def findings_rows(ledger: list[dict]) -> list[dict]:
    """One row per fingerprint — the finding's CURRENT state plus how it got there.

    Everything is the latest ledger entry's own words (disposition, severity, target, detail,
    evidence); `off_books` is `findings_model.validate_disposition` applied to that entry, so a
    SPLIT without an id and owner, or an AI signing an ACCEPTED_RISK, reads as still on the books
    exactly as it counts. `rounds` is how many ledger entries carry the fingerprint — one per
    recorded report — which is what "seen N times across reports" means. Order: ledger order of
    first appearance, so the oldest open finding is first."""
    by_fp: dict[str, list[dict]] = {}
    for e in ledger:
        fp = e.get("fingerprint")
        if fp:
            by_fp.setdefault(fp, []).append(e)
    rows = []
    for fp, entries in by_fp.items():
        latest = entries[-1]
        off_books, reason = fm.validate_disposition(latest)
        row = {
            "fingerprint": fp,
            "id": latest.get("id", ""),
            "category": latest.get("category", ""),
            "severity": fm.normalize_severity(latest.get("severity")) or latest.get("severity", ""),
            "target": latest.get("target", ""),
            "disposition": fm.normalize_disposition(latest.get("disposition")) or latest.get("disposition", ""),
            "detail": latest.get("detail", ""),
            "evidence": {k: latest[k] for k in EVIDENCE_FIELDS if latest.get(k)},
            "off_books": off_books,
            "off_books_reason": reason,
            "first_seen": entries[0].get("timestamp"),
            "last_seen": latest.get("timestamp"),
            "rounds": len(entries),
            "report": latest.get("report", ""),
        }
        rows.append(row)
    return rows


def recurrence_of(rows: list[dict]) -> dict[str, int]:
    """fingerprint -> rounds, for the rows given (filtered or not)."""
    return {r["fingerprint"]: r["rounds"] for r in rows}


_SCOPE_PATH_RE = re.compile(r"`([^`\n]+)`")


def scope_paths(spec_text: str) -> list[str]:
    """The backticked paths under the spec's `## Scope` > `### In scope` — the only place a spec
    says what files a change may touch. Returns [] when the section or the backticks are absent;
    nothing is inferred from prose."""
    _fm, body = cs.parse_frontmatter(spec_text)
    scope = cs.extract_section(body, "Scope")
    if scope is None:
        return []
    inside = cs.extract_subsection(scope, "In scope")
    if inside is None:
        return []
    paths = []
    for line in cs.strip_comments_and_blanks(inside):
        for raw in _SCOPE_PATH_RE.findall(line):
            cleaned = raw.strip().replace("\\", "/")
            if cleaned.startswith("./"):
                cleaned = cleaned[2:]
            if cleaned and cleaned not in paths:
                paths.append(cleaned)
    return paths


def target_under(target: str, scope_path: str) -> bool:
    """Does a finding's target file fall under one scope path? Globs (`src/Claims/**`, `*.cs`)
    match with fnmatch where `**` reads as "anything"; a plain path matches itself or anything
    beneath it as a directory. Case-sensitive, like the paths themselves."""
    file_part = str(target or "").split(":", 1)[0].strip().replace("\\", "/")
    if file_part.startswith("./"):
        file_part = file_part[2:]
    if not file_part:
        return False
    if any(ch in scope_path for ch in "*?["):
        return fnmatch.fnmatchcase(file_part, scope_path.replace("**", "*"))
    scope = scope_path.rstrip("/")
    return file_part == scope or file_part.startswith(scope + "/")


def attribute_to_spec(rows: list[dict], paths: list[str]) -> tuple[list[dict], dict]:
    """The rows whose target is under one of the spec's scope paths, and the honest tally.

    The ledger has no spec id — a finding is keyed by category and target FILE — so "this spec's
    findings" can only ever mean "findings at files this spec says it touches". The method is
    named in the payload so a card can say so, and `unattributed` is stated, never hidden."""
    if not paths:
        return [], {"method": "scope-paths", "scope_paths": [], "attributed": 0, "unattributed": len(rows)}
    mine = [r for r in rows if any(target_under(r["target"], p) for p in paths)]
    return mine, {"method": "scope-paths", "scope_paths": paths,
                  "attributed": len(mine), "unattributed": len(rows) - len(mine)}


def resolve_base_and_metrics(args) -> tuple[Path, Path]:
    """(repo_base_dir, metrics_dir) from --state (the .sdlc beside it) or --repo (<repo>/.sdlc)."""
    if args.state:
        state_path = Path(args.state)
        if not state_path.exists():
            print(f"Error: State file not found: {state_path}")
            sys.exit(1)
        sdlc = state_path.resolve().parent
        return sdlc.parent, sdlc / "metrics"
    repo = Path(args.repo).resolve()
    return repo, repo / ".sdlc" / "metrics"


def cmd_record(args) -> int:
    report_path = Path(args.report)
    if not report_path.exists():
        print(f"Error: Review report not found: {report_path}")
        return 1
    base_dir, metrics_dir = resolve_base_and_metrics(args)
    findings, err = parse_findings_block(report_path.read_text(encoding="utf-8"))
    if err:
        print(f"INPUT_INCOMPLETE: {err}")
        return 1
    metrics_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = metrics_dir / "findings-log.jsonl"
    ts = datetime.now(timezone.utc).isoformat()
    with open(ledger_path, "a", encoding="utf-8") as f:
        for finding in findings:
            f.write(json.dumps(build_entry(finding, report_path.name, base_dir, ts)) + "\n")
    debt = fm.open_debt(findings)
    print(f"Recorded {len(findings)} finding(s) to {ledger_path.name} — {len(debt)} open HIGH+ debt this review.")
    return 0


def format_report(ledger: list[dict]) -> tuple[str, int]:
    """Human-readable findings report. Returns (text, mismatch_count)."""
    states = list(current_state(ledger).values())
    debt = fm.open_debt(states)
    mismatches = find_fixed_claim_mismatches(ledger)
    disp_tally: dict[str, int] = {}
    for s in states:
        d = fm.normalize_disposition(s.get("disposition")) or "?"
        disp_tally[d] = disp_tally.get(d, 0) + 1

    lines = ["Findings Ledger", "=" * 44, ""]
    lines.append(f"Distinct findings tracked: {len(states)}")
    lines.append("Dispositions: " + (", ".join(f"{k}={v}" for k, v in sorted(disp_tally.items())) or "none"))
    lines.append("")
    lines.append(f"Open HIGH+ debt (Checker weighs this): {len(debt)}")
    for d in debt:
        sev = fm.normalize_severity(d.get("severity")) or "?"
        lines.append(f"  - [{sev}] {d.get('category', '?')} @ {d.get('target') or '—'}: {d.get('detail', '')}")
    lines.append("")
    if mismatches:
        lines.append(f"FIXED_CLAIM_MISMATCH: {len(mismatches)} finding(s) marked FIXED but the file never changed:")
        for m in mismatches:
            lines.append(f"  - {m.get('category', '?')} @ {m.get('target') or '—'} (fingerprint {m.get('fingerprint')})")
    else:
        lines.append("FIXED-claim check: clean (no fixed-but-unchanged findings).")
    return "\n".join(lines), len(mismatches)


def cmd_report(args) -> int:
    _, metrics_dir = resolve_base_and_metrics(args)
    ledger = load_ledger(metrics_dir / "findings-log.jsonl")
    spec_path = Path(args.spec) if getattr(args, "spec", None) else None
    if spec_path is not None and not spec_path.exists():
        print(f"Error: Spec not found: {spec_path}")
        return 1

    rows = findings_rows(ledger)
    attribution = None
    if spec_path is not None:
        rows, attribution = attribute_to_spec(rows, scope_paths(spec_path.read_text(encoding="utf-8")))

    if args.json:
        states = list(current_state(ledger).values())
        # The three counts stay project-wide (they are what they always were); only the listing
        # narrows under --spec, and the attribution block says by how much.
        payload = {
            "tracked": len(states),
            "open_debt": len(fm.open_debt(states)),
            "fixed_claim_mismatches": len(find_fixed_claim_mismatches(ledger)),
            "findings": rows,
            "recurrence": recurrence_of(rows),
        }
        if attribution is not None:
            payload["attribution"] = attribution
        print(json.dumps(payload, indent=2))
        mism = payload["fixed_claim_mismatches"]
    else:
        text, mism = format_report(ledger)
        print(text)
        if attribution is not None:
            print("")
            print(f"Findings under {spec_path.name}'s scope paths: {attribution['attributed']} "
                  f"({attribution['unattributed']} elsewhere in the ledger)")
            for r in rows:
                print(f"  - [{r['severity'] or '?'}] {r['category'] or '?'} @ {r['target'] or '—'}: "
                      f"{r['disposition']} (seen {r['rounds']}x)")
    return 2 if (args.strict and mism) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Record and report review findings with dispositions")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    src = common.add_mutually_exclusive_group()
    src.add_argument("--state", help="Path to .sdlc/state.yaml (workflow mode)")
    src.add_argument("--repo", default=".", help="Repo root containing .sdlc/ (standalone; default cwd)")

    p_rec = sub.add_parser("record", parents=[common], help="Parse a review report and append its findings")
    p_rec.add_argument("--report", required=True, help="Path to review-report.md")

    p_rep = sub.add_parser("report", parents=[common], help="Report open debt + the FIXED-claim check")
    p_rep.add_argument("--strict", action="store_true", help="Exit 2 if any FIXED_CLAIM_MISMATCH (factual, may block)")
    p_rep.add_argument("--json", action="store_true", help="Emit a JSON summary")
    p_rep.add_argument("--spec", default=None, metavar="PATH",
                       help="Narrow the findings listing to targets under this spec's `## Scope` In paths "
                            "(the ledger has no spec id; attribution is by path and says so)")

    args = parser.parse_args()
    sys.exit(cmd_record(args) if args.command == "record" else cmd_report(args))


if __name__ == "__main__":
    main()
