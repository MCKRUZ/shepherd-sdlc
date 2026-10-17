"""retro_report.py — the cross-ledger retro roll-up behind /sprd-retro.

Three ledgers already record, honestly and append-only, what the advisory layers surfaced round
after round: review findings (findings-log.jsonl), artifact staleness + change history
(artifact-log.jsonl), and — folded into the same artifact ledger — the reverse-propagation refresh
trail (`refreshed` changes + reject dispositions). Each on its own answers "what is open right now".
This tool reads all three at once and answers the *retro* question: what keeps happening.

Four read-only sections, all exit 0 always (advisory — a retro never blocks and never mutates):

  1. RECURRING FINDINGS   — a (category, target) group seen in >= 2 distinct rounds is a candidate
                            for a permanent check ("findings become new checks").
  2. REPEAT-STALE ARTIFACTS — per downstream artifact, how many times it was dispositioned for
                            staleness, and whether it is stale right now.
  3. REFRESH FUNNEL       — per merged spec and by upstream stem: candidates → drifted → refreshed
                            → rejected → still open. Doubles as the divergence-heuristic tuning
                            signal (lots rejected / few applied = noisy; nothing ever drifts = too
                            tight).
  4. DISPOSITION DEBT ROLLUP — combined honest-counting debt across the three ledgers, each line
                            naming its source.

Two more sections read the sprint ledger (sprint-log.jsonl, written by sprint.py) when it exists:

  5. CARRY-OVER RECURRENCE — per spec, how many sprints it was carried out of, which ones, and the
                            recorded reasons; flagged RECURRING at >= 2 (the only cross-sprint number
                            the standard allows — never a kept/carried trend, which is velocity with
                            the points removed).
  6. BOUNCE CAUSES        — `verdict: returned` events grouped by lane (eng | data) and reason
                            category; rendered only when at least one return exists.

One more section reads the Azure Boards mirror's own ledger (`.sdlc/metrics/ado-sync-log.jsonl`, written by
ado_sync.py) when it holds at least one event the mirror wrote:

  7. AZURE BOARDS MIRROR  — three counts, each keyed by a work item, a reason or a drift class: board comments
                            with a line that reads as an instruction (`directive_seen`, per work item, against how
                            many comments were read — the tuning signal for the scan, design D47), the reasons
                            comment drafts were refused (`comment_refused`), and the drift-disposition rollup
                            (open rows, those past the two-business-day line, by class, and each disposition
                            recorded against how many of its lines carry what the disposition claims). The drift
                            numbers are `ado_sync_model.summarize`'s own, the ones `ado_sync.py status` prints.
                            ADDITIVE and absent when there is no such ledger: a repository that never used the
                            mirror prints exactly the text and the JSON it printed before (the frozen pins in
                            test_retro_report.py hold the key set and the "no data" count), and with the ledger
                            every pre-existing key keeps its value. A count nobody measured is `no data` / null —
                            never 0 — and a comment's text, a person and their handle are never read.

Everything is keyed by category / artifact / stem / spec / lane / work item / reason — never by actor. There is
deliberately no flag to rank by person, the `by` field of every sprint event is dropped on read, and the forbidden
activity metrics (velocity, story points, PR count, LOC) are never computed. Patterns, not people.

Standalone or Workflow (CLAUDE.md design rule):
  --repo <path>   standalone (reads <repo>/.sdlc)      |   --state .sdlc/state.yaml   in-workflow
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ado_sync_model as asm
import artifact_model as am
import audit_artifacts as aa
import boards_contract as bc
import findings_model as fm
import sprint_model as sm
import track_specs as ts

FINDINGS_LEDGER_NAME = "findings-log.jsonl"
SPRINT_LEDGER_NAME = "sprint-log.jsonl"
BOARDS_LEDGER_NAME = Path(bc.LEDGER).name  # ado-sync-log.jsonl, the Azure Boards mirror's ledger
OTHER_REASON = "other"  # a reason, class or disposition outside the mirror's own words: counted, never echoed
NO_REASON = "(no reason recorded)"
RECURRENCE_THRESHOLD = 2  # carried out of >= 2 sprints => RECURRING


# --- Loading (never crashes; a non-dict / bad line is skipped, mirroring aa.load_ledger) -------

def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


# --- Window plumbing ---------------------------------------------------------------------------

def cutoff_from(window_days) -> datetime | None:
    """The oldest timestamp still in the window, or None for all-history. A non-positive N is treated
    as no window (never silently drops everything)."""
    if not window_days or window_days <= 0:
        return None
    return datetime.now(timezone.utc) - timedelta(days=window_days)


def in_window(ts: str, cutoff: datetime | None) -> bool:
    """True if `ts` is inside the window. An unparseable timestamp is kept (honest: we don't drop a
    real event just because its clock stamp is malformed)."""
    if cutoff is None:
        return True
    dt = aa._parse_ts(ts)
    if dt is None:
        return True
    return dt >= cutoff


def _safe(fn, default):
    """Run a section builder; on any fault return `default` so one bad ledger never sinks the rest
    (and never a stack trace — the whole tool is advisory)."""
    try:
        return fn()
    except Exception:
        return default


# --- Section 1: recurring findings -------------------------------------------------------------

def recurring_findings(findings: list[dict], cutoff: datetime | None) -> list[dict]:
    """Group findings-log entries by (category, target). A group seen in >= 2 distinct rounds (a round
    = one distinct report timestamp — one `record_findings record` invocation shares one timestamp) is
    a candidate for a permanent check. Keyed by category+target, never by actor."""
    groups: dict[tuple, dict] = {}
    for e in findings:
        if not in_window(e.get("timestamp", ""), cutoff):
            continue
        cat = (e.get("category") or "").strip()
        tgt = (e.get("target") or "").strip()
        if not (cat or tgt):
            continue
        g = groups.setdefault((cat, tgt), {"category": cat, "target": tgt,
                                           "times": 0, "rounds": set(), "dispositions": {}})
        g["times"] += 1
        g["rounds"].add(e.get("timestamp", ""))
        disp = fm.normalize_disposition(e.get("disposition")) or (e.get("disposition") or "?")
        g["dispositions"][disp] = g["dispositions"].get(disp, 0) + 1

    out: list[dict] = []
    for g in groups.values():
        rounds = len(g["rounds"])
        if rounds >= 2:
            out.append({"category": g["category"], "target": g["target"],
                        "times": g["times"], "rounds": rounds, "dispositions": g["dispositions"]})
    out.sort(key=lambda x: (-x["times"], -x["rounds"], x["category"], x["target"]))
    return out


# --- Section 2: repeat-stale artifacts ---------------------------------------------------------

def repeat_stale(art_ledger: list[dict], base_dir: Path, sdlc_dir: Path,
                 cutoff: datetime | None) -> list[dict]:
    """Per downstream artifact: how many staleness disposition entries it accrued in the window
    (flagged), how many are legitimately off the books vs still open, and whether it is stale right
    now (from compute_staleness on the *current* ledger — a now-fact, so it ignores the window).

    Refresh-reject reverse edges (upstream is a specs/* path) are excluded here — they belong to the
    refresh funnel (section 3), so they are not double-counted as staleness flags."""
    by_down: dict[str, list[dict]] = {}
    for e in art_ledger:
        if not am.is_disposition_entry(e):
            continue
        if str(e.get("upstream") or "").startswith("specs/"):
            continue  # refresh-reject edge — counted in the refresh funnel, not here
        if not in_window(e.get("ts", ""), cutoff):
            continue
        down = str(e.get("downstream") or "").strip()
        if down:
            by_down.setdefault(down, []).append(e)

    stale_items = aa.compute_staleness(base_dir, sdlc_dir, art_ledger)
    currently = {i["downstream"] for i in stale_items}

    out: list[dict] = []
    for down in sorted(set(by_down) | currently):
        entries = by_down.get(down, [])
        flagged = len(entries)
        open_ = sum(1 for e in entries if am.counts_as_debt(e))
        dispositioned = flagged - open_
        out.append({"artifact": down, "flagged": flagged, "dispositioned": dispositioned,
                    "open": open_, "currently_stale": down in currently})
    out.sort(key=lambda x: (not x["currently_stale"], -x["flagged"], x["artifact"]))
    return out


# --- Section 3: refresh funnel (also the divergence-heuristic tuning signal) -------------------

def _empty_stem(stem: str) -> dict:
    return {"stem": stem, "detected": 0, "drifted": 0, "refreshed": 0, "rejected": 0, "open": 0}


def _stem_note(agg: dict) -> dict:
    """One honest tuning readout per stem. High rejected/applied ⇒ the divergence signal is noisy;
    candidates that never drift ⇒ it is too tight (quiet)."""
    a = dict(agg)
    applied, rejected = a["refreshed"], a["rejected"]
    detected, drifted = a["detected"], a["drifted"]
    if applied == 0 and rejected > 0:
        note = f"{rejected} rejected / 0 applied — drift signal may be noisy for this stem"
    elif detected > 0 and drifted == 0 and applied == 0 and rejected == 0:
        note = f"0 of {detected} candidate(s) ever drifted — divergence signal may be too tight (quiet)"
    elif rejected > applied and applied > 0:
        note = f"{rejected} rejected / {applied} applied — drift signal may be noisy for this stem"
    elif applied > 0:
        note = f"{applied} applied / {rejected} rejected — signal landing"
    else:
        note = "candidates detected; nothing applied or rejected yet"
    a["note"] = note
    return a


def refresh_funnel(base_dir: Path, sdlc_dir: Path, metrics_dir: Path,
                   art_ledger: list[dict], cutoff: datetime | None) -> dict:
    """Reuse audit_artifacts' own detection/status internals rather than reimplementing the drift
    call. Per merged spec: detected (active candidates) → drifted → refreshed (`refreshed` change
    events attributed to the spec via the source_spec rider) → rejected (NOT_AFFECTED whose upstream
    is this spec) → still open. Aggregated the same way by upstream stem."""
    merged = [s for s in ts.scan_specs(base_dir / "specs") if s.get("status") == "merged"]
    by_spec: list[dict] = []
    stem_agg: dict[str, dict] = {}

    for s in merged:
        spec_node = aa._normalize_artifact_arg(base_dir, s["path"])
        spec_id = aa._spec_id_of(base_dir, spec_node)
        cands, _, _ = aa._detect_candidates(
            base_dir, sdlc_dir, metrics_dir, spec_node, transitive=False, include_coarse=False)
        active = [c for c in cands if not c["already_fresher"]]
        drifted = [c for c in active if c["drift"] and c["confidence"] == "declared"]

        refreshed_targets = [
            e.get("artifact") for e in art_ledger
            if am.is_change_entry(e)
            and am.normalize_event(e.get("event")) == "refreshed"
            and e.get("source_spec") == spec_id and e.get("artifact")
            and in_window(e.get("ts", ""), cutoff)]
        rejected_targets = [
            e.get("downstream") for e in art_ledger
            if am.is_disposition_entry(e) and e.get("upstream") == spec_node
            and am.normalize_disposition(e.get("disposition")) == "NOT_AFFECTED"
            and e.get("downstream") and in_window(e.get("ts", ""), cutoff)]

        _, _, rows = aa._refresh_status_rows(
            base_dir, sdlc_dir, metrics_dir, spec_node, transitive=False, include_coarse=False)
        open_rows = [r for r in rows if _row_is_open(r)]

        by_spec.append({
            "spec": spec_id, "spec_node": spec_node, "name": s.get("name", ""),
            "detected": len(active), "drifted": len(drifted),
            "refreshed": len(refreshed_targets), "rejected": len(rejected_targets),
            "open": len(open_rows),
        })

        for c in active:
            agg = stem_agg.setdefault(c["stem"], _empty_stem(c["stem"]))
            agg["detected"] += 1
            if c["drift"] and c["confidence"] == "declared":
                agg["drifted"] += 1
        for t in refreshed_targets:
            st = aa._pre_build_stem(t) or "?"
            stem_agg.setdefault(st, _empty_stem(st))["refreshed"] += 1
        for t in rejected_targets:
            st = aa._pre_build_stem(t) or "?"
            stem_agg.setdefault(st, _empty_stem(st))["rejected"] += 1
        for r in open_rows:
            st = r.get("stem") or "?"
            stem_agg.setdefault(st, _empty_stem(st))["open"] += 1

    by_spec.sort(key=lambda x: str(x["spec"]))
    by_stem = sorted((_stem_note(a) for a in stem_agg.values()), key=lambda x: x["stem"])
    return {"by_spec": by_spec, "by_stem": by_stem}


def _row_is_open(row: dict) -> bool:
    """A refresh-status row still counts as open debt: OPEN, or a mislabeled off-books disposition."""
    disp = row.get("disposition")
    if disp == "OPEN":
        return True
    return disp in ("ACKNOWLEDGED", "NOT_AFFECTED") and not row.get("off_books")


# --- Section 4: disposition debt rollup --------------------------------------------------------

def _current_findings_state(findings: list[dict]) -> list[dict]:
    """Latest entry per fingerprint — a finding's current disposition (mirrors record_findings)."""
    latest: dict[str, dict] = {}
    for e in findings:
        fp = e.get("fingerprint") or fm.fingerprint(e)
        if fp:
            latest[fp] = e
    return list(latest.values())


def debt_rollup(findings: list[dict], art_ledger: list[dict], base_dir: Path, sdlc_dir: Path,
                funnel: dict) -> dict:
    """Combined honest-counting debt — a now-measurement, so the window never applies. Each source is
    named on its own line by the caller."""
    findings_debt = len(fm.open_debt(_current_findings_state(findings)))
    stale_debt = len(am.open_debt(aa.compute_staleness(base_dir, sdlc_dir, art_ledger)))
    refresh_open = sum(sp["open"] for sp in funnel.get("by_spec", []))
    return {
        "findings": findings_debt,
        "artifact_staleness": stale_debt,
        "refresh_open": refresh_open,
        "total": findings_debt + stale_debt + refresh_open,
    }


# --- Sections 5 + 6: sprint ledger — carry-over recurrence and bounce causes ------------------

def _reason_category(reason) -> str:
    """Collapse a free-text reason into a comparable category: lower-cased, whitespace-normalised,
    trailing punctuation dropped. Empty → NO_REASON (honest: the gap is itself a pattern)."""
    text = " ".join(str(reason or "").split()).strip().rstrip(".!;,").strip().lower()
    return text or NO_REASON


def carry_over_recurrence(sprint_events: list[dict], cutoff: datetime | None) -> list[dict]:
    """Per spec: the distinct sprints it was `carried` out of (in ledger order), where each carry went,
    and the recorded reasons. `carried` >= RECURRENCE_THRESHOLD flags RECURRING. Keyed by spec id —
    the `by` field is never read."""
    per_spec: dict[str, dict] = {}
    for e in sprint_events:
        if str(e.get("event") or "").strip().lower() != "carried":
            continue
        if not in_window(e.get("ts", ""), cutoff):
            continue
        spec = str(e.get("spec") or "").strip()
        if not spec:
            continue
        g = per_spec.setdefault(spec, {"spec": spec, "sprints": [], "carries": []})
        src = str(e.get("sprint") or "").strip() or "?"
        if src not in g["sprints"]:
            g["sprints"].append(src)
        to = str(e.get("to_sprint") or "").strip() or "?"
        reason = str(e.get("reason") or "").strip() or NO_REASON
        g["carries"].append({"from": src, "to": to, "reason": reason})

    out: list[dict] = []
    for g in per_spec.values():
        carried = len(g["sprints"])
        out.append({"spec": g["spec"], "carried": carried, "sprints": g["sprints"],
                    "carries": g["carries"], "reasons": [c["reason"] for c in g["carries"]],
                    "flagged": carried >= RECURRENCE_THRESHOLD})
    out.sort(key=lambda x: (not x["flagged"], -x["carried"], x["spec"]))
    return out


def bounce_causes(sprint_events: list[dict], cutoff: datetime | None) -> list[dict]:
    """`verdict` events whose verdict is `returned`, grouped by (lane, reason category) with the
    distinct specs each cause bounced. Grouped by lane and cause — never by who returned it."""
    groups: dict[tuple, dict] = {}
    for e in sprint_events:
        if str(e.get("event") or "").strip().lower() != "verdict":
            continue
        if sm.normalize_review(e.get("verdict")) != "returned":
            continue
        if not in_window(e.get("ts", ""), cutoff):
            continue
        lane = str(e.get("lane") or "").strip().lower() or "?"
        cause = _reason_category(e.get("reason"))
        g = groups.setdefault((lane, cause), {"lane": lane, "reason": cause, "times": 0, "specs": set()})
        g["times"] += 1
        spec = str(e.get("spec") or "").strip()
        if spec:
            g["specs"].add(spec)

    lane_rank = {lane: i for i, lane in enumerate(sm.LANES)}
    out = [{"lane": g["lane"], "reason": g["reason"], "times": g["times"],
            "specs": sorted(g["specs"])} for g in groups.values()]
    out.sort(key=lambda x: (lane_rank.get(x["lane"], len(lane_rank)), -x["times"], x["reason"]))
    return out


# --- Section 7: the Azure Boards mirror's ledger -----------------------------------------------
#
# Reads only what the mirror's ledger already holds (counts, ids, class names, hashes): never a comment's text, never a
# person. Keyed by work item, reason and class; there is no actor key anywhere in what these return.

NO_DIRECTIVE = {"comments_seen": None, "flagged_comments": None, "flagged_lines": None, "by_work_item": []}
NO_DRIFT = {"as_of": None, "open": None, "drifted": None, "conflicts": None, "debt": None, "by_class": None,
            "debt_rows": None, "dispositions": []}


def _today():
    """Today in UTC (a seam, so the aging of drift debt can be tested)."""
    return datetime.now(timezone.utc).date()


def _id(value):
    """A work item or comment id: a real positive integer; never a bool, never a string that looks like a number."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _line_numbers(value) -> set:
    return ({n for n in value if isinstance(n, int) and not isinstance(n, bool) and n >= 0}
            if isinstance(value, list) else set())


def directive_counts(events: list[dict], cutoff: datetime | None) -> tuple[dict, bool]:
    """Board comments with a line that reads as an instruction (`directive_seen`), per work item, against the comments
    read (`comment_seen`: one per distinct work item + comment id). A comment seen again after an edit is one comment and
    its repeated line is one line; every event is still counted in `events`. `comments_seen` is None when no comment was
    ever read (a denominator nobody measured) and the flagged counts are None with it when nothing was flagged either.
    Returns `(section, has_data)`."""
    seen: set[tuple] = set()
    per_item: dict[int, dict] = {}
    for e in events:
        if not in_window(e.get("ts", ""), cutoff):
            continue
        item, comment = _id(e.get("work_item")), _id(e.get("comment"))
        if item is None or comment is None:
            continue
        name = e.get("event")
        if name == "comment_seen":
            seen.add((item, comment))
        elif name == "directive_seen":
            lines = _line_numbers(e.get("lines"))
            if not lines:
                continue
            g = per_item.setdefault(item, {"work_item": item, "ref": None, "comments": set(), "lines": set(),
                                           "events": 0})
            if g["ref"] is None and isinstance(e.get("ref"), str) and bc.REF_RE.fullmatch(e["ref"]):
                g["ref"] = e["ref"]       # only an sdlc:<kind>:<id> ref is shown; any other string stays unread
            g["events"] += 1
            g["comments"].add(comment)
            g["lines"] |= {(comment, n) for n in lines}
    if not seen and not per_item:
        return dict(NO_DIRECTIVE, by_work_item=[]), False
    rows = [{"work_item": g["work_item"], "ref": g["ref"], "comments": len(g["comments"]), "lines": len(g["lines"]),
             "events": g["events"]} for g in per_item.values()]
    rows.sort(key=lambda r: (-r["lines"], -r["comments"], r["work_item"]))
    return {"comments_seen": len(seen) if seen else None,
            "flagged_comments": sum(r["comments"] for r in rows),
            "flagged_lines": sum(r["lines"] for r in rows),
            "by_work_item": rows}, True


def refusal_counts(events: list[dict], cutoff: datetime | None) -> tuple[list[dict], bool]:
    """The reasons comment drafts were refused, `[{"reason", "times", "work_items"}]`, most frequent first. A reason
    outside `boards_contract.COMMENT_REFUSALS` is counted under `other` and never echoed (a ledger line is not trusted to
    carry only an enum). `has_data` is true once the ledger shows any comment activity at all (a comment posted or a
    draft refused), so an empty list after that is an honest "none", not a missing measurement."""
    attempted = any(e.get("event") in ("commented", "comment_refused") for e in events)
    known = set(bc.COMMENT_REFUSALS)
    groups: dict[str, dict] = {}
    for e in events:
        if e.get("event") != "comment_refused" or not in_window(e.get("ts", ""), cutoff):
            continue
        reason = e.get("reason") if isinstance(e.get("reason"), str) and e.get("reason") in known else OTHER_REASON
        g = groups.setdefault(reason, {"reason": reason, "times": 0, "items": set()})
        g["times"] += 1
        if _id(e.get("work_item")) is not None:
            g["items"].add(e["work_item"])
    rows = [{"reason": g["reason"], "times": g["times"], "work_items": len(g["items"])} for g in groups.values()]
    rows.sort(key=lambda r: (-r["times"], r["reason"]))
    return rows, attempted


def drift_rollup(events: list[dict], cutoff: datetime | None, today) -> tuple[dict, bool]:
    """The drift-disposition rollup. Open rows, rows past the two-business-day line and the open rows by class are
    `ado_sync_model.summarize`'s own numbers (a now-measurement: the window never applies, as it does not for the other
    debt) and are None until a pull was ledgered (`observed`) -- never a fabricated 0. `dispositions` tallies each
    `reconciled` line by its disposition word, with how many of those lines carry what the word claims
    (`ado_sync_model.validate_disposition`: an ACKNOWLEDGED with no owner, a NOT_DRIFT with no reason or a TAKE_* with no
    recorded child exit 0 is recorded, not settled). A class or a disposition outside the model's words is `other`."""
    status = asm.summarize(events, today)
    counts = status["counts"]
    measured = status.get("as_of") is not None
    by_class = None
    if measured and isinstance(status.get("by_class"), dict):
        by_class = {}
        for cls, n in status["by_class"].items():
            key = cls if cls in asm.DRIFT_CLASSES else OTHER_REASON
            by_class[key] = by_class.get(key, 0) + n
        by_class = dict(sorted(by_class.items()))
    tally: dict[str, dict] = {}
    for e in events:
        if e.get("event") != "reconciled" or not in_window(e.get("ts", ""), cutoff):
            continue
        word = str(e.get("disposition") or "").strip().upper()
        word = word if word in asm.DISPOSITIONS else OTHER_REASON
        g = tally.setdefault(word, {"disposition": word, "recorded": 0, "settled": 0})
        g["recorded"] += 1
        g["settled"] += 1 if asm.validate_disposition(e)[0] else 0
    return {"as_of": status["as_of"] if measured else None,
            "open": counts["open"] if measured else None,
            "drifted": counts["drifted"] if measured else None,
            "conflicts": counts["conflicts"] if measured else None,
            "debt": counts["debt"] if measured else None,
            "by_class": by_class,
            "debt_rows": [dict(r) for r in (status.get("debt") or [])] if measured else None,
            "dispositions": sorted(tally.values(), key=lambda g: g["disposition"])}, measured


def boards_section(events: list[dict], cutoff: datetime | None, today) -> dict:
    """The `boards` section of the payload: the three counts, each with its own has_data flag. A block that cannot be
    read is reported as no data (never raised, never a zero); the others still read."""
    directive, has_directive = _safe(lambda: directive_counts(events, cutoff),
                                     (dict(NO_DIRECTIVE, by_work_item=[]), False))
    refused, has_refused = _safe(lambda: refusal_counts(events, cutoff), ([], False))
    drift, has_drift = _safe(lambda: drift_rollup(events, cutoff, today), (dict(NO_DRIFT, dispositions=[]), False))
    return {"ledger": bc.LEDGER,
            "has_data": {"directive_seen": has_directive, "comment_refused": has_refused, "drift_debt": has_drift},
            "directive_seen": directive, "comment_refused": refused, "drift_debt": drift}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def format_boards(b: dict) -> list[str]:
    """The text block for the `boards` section (no trailing blank line)."""
    hd = b["has_data"]
    L = [f"Azure Boards mirror ({BOARDS_LEDGER_NAME} — per work item, reason and class, never per person):",
         "  Comment lines that read as instructions (the scan's tuning signal):"]
    if not hd["directive_seen"]:
        L.append("    no data (no board comment was read)")
    else:
        d = b["directive_seen"]
        read = ("comments read: no data" if d["comments_seen"] is None
                else f"{_plural(d['comments_seen'], 'comment')} read")
        if d["flagged_comments"]:
            flagged = (f"{d['flagged_comments']} had a line that reads as an instruction "
                       f"({_plural(d['flagged_lines'], 'line')})")
        else:
            flagged = "none had a line that reads as an instruction"
        L.append(f"    {read}; {flagged}")
        for r in d["by_work_item"]:
            L.append(f"    • #{r['work_item']} {r['ref'] or '(no ref)'} — {_plural(r['comments'], 'comment')}, "
                     f"{_plural(r['lines'], 'line')}")
    L.append("  Refused comment drafts, by reason:")
    if not hd["comment_refused"]:
        L.append("    no data (no comment was drafted)")
    elif not b["comment_refused"]:
        L.append("    none recorded")
    else:
        for r in b["comment_refused"]:
            L.append(f"    • {r['reason']} — {_plural(r['times'], 'time')} ({_plural(r['work_items'], 'work item')})")
    L.append("  Drift dispositions (an open row is debt in waiting):")
    if not hd["drift_debt"]:
        L.append("    no data (never pulled)")
    else:
        d = b["drift_debt"]
        L.append(f"    open {d['open']} · past the {asm.DEBT_BUSINESS_DAYS}-business-day line {d['debt']} · "
                 f"conflicts {d['conflicts']} · as of {d['as_of']}")
        classes = ", ".join(f"{k} {v}" for k, v in (d["by_class"] or {}).items())
        L.append(f"    by class: {classes or 'none open'}")
        recorded = ", ".join(f"{g['disposition']} {g['recorded']} ({g['settled']} settled)" for g in d["dispositions"])
        L.append(f"    recorded: {recorded or 'none'}")
    return L


# --- Assembly ----------------------------------------------------------------------------------

def build_payload(args) -> dict:
    base_dir, sdlc_dir, metrics_dir = aa.resolve_paths(args)
    cutoff = cutoff_from(getattr(args, "window_days", None))
    art_ledger = load_jsonl(metrics_dir / aa.LEDGER_NAME)
    findings = load_jsonl(metrics_dir / FINDINGS_LEDGER_NAME)

    recurring = _safe(lambda: recurring_findings(findings, cutoff), [])
    stale = _safe(lambda: repeat_stale(art_ledger, base_dir, sdlc_dir, cutoff), [])
    funnel = _safe(lambda: refresh_funnel(base_dir, sdlc_dir, metrics_dir, art_ledger, cutoff),
                   {"by_spec": [], "by_stem": []})
    debt = _safe(lambda: debt_rollup(findings, art_ledger, base_dir, sdlc_dir, funnel),
                 {"findings": 0, "artifact_staleness": 0, "refresh_open": 0, "total": 0})

    sprint_events = load_jsonl(metrics_dir / SPRINT_LEDGER_NAME)
    carry_over = _safe(lambda: carry_over_recurrence(sprint_events, cutoff), [])
    bounces = _safe(lambda: bounce_causes(sprint_events, cutoff), [])

    has_data = {
        "recurring_findings": bool(recurring),
        "repeat_stale": bool(stale),
        "refresh_funnel": any(
            (sp["detected"] + sp["drifted"] + sp["refreshed"] + sp["rejected"] + sp["open"]) > 0
            for sp in funnel.get("by_spec", [])),
        # Debt is a real measurement (possibly 0) whenever either ledger exists; only truly-absent
        # ledgers read "no data" (never a fabricated zero).
        "debt": bool(art_ledger) or bool(findings),
        "carry_over_recurrence": bool(carry_over),
        "bounce_causes": bool(bounces),
    }
    payload = {
        "has_data": has_data,
        "recurring_findings": recurring,
        "repeat_stale": stale,
        "refresh_funnel": funnel,
        "debt": debt,
        "carry_over_recurrence": carry_over,
        "bounce_causes": bounces,
        # True iff sprint-log.jsonl holds at least one event. The text report renders sections 5 + 6
        # only then, so a repo that never used the sprint layer prints exactly the pre-1.6 text.
        "sprint_ledger_present": bool(sprint_events),
        "window_days": getattr(args, "window_days", None),
    }
    # Section 7 exists only when the mirror's ledger holds an event the mirror wrote -- never a phantom block, so a
    # repository that never used the mirror keeps the exact key set and the exact text it always had.
    boards_events = [e for e in load_jsonl(metrics_dir / BOARDS_LEDGER_NAME) if e.get("event") in asm.LEDGER_EVENTS]
    if boards_events:
        payload["boards"] = boards_section(boards_events, cutoff, _today())
    return payload


def format_report(p: dict) -> str:
    hd = p["has_data"]
    wd = p["window_days"]
    window = f"  (last {wd} days)" if wd else "  (all history)"
    L = [f"Retro Roll-up{window}", "=" * 60, ""]

    L.append("Recurring findings (candidates for a permanent check):")
    if not hd["recurring_findings"]:
        L.append("  no data")
    else:
        for g in p["recurring_findings"]:
            disp = ", ".join(f"{k}={v}" for k, v in sorted(g["dispositions"].items())) or "none"
            L.append(f"  • {g['category'] or '—'} @ {g['target'] or '—'}")
            L.append(f"      seen {g['times']} times across {g['rounds']} rounds — "
                     f"candidate for a permanent check")
            L.append(f"      dispositions: {disp}")
    L.append("")

    L.append("Repeat-stale artifacts (artifact-log.jsonl):")
    if not hd["repeat_stale"]:
        L.append("  no data")
    else:
        for r in p["repeat_stale"]:
            cur = " · currently STALE" if r["currently_stale"] else ""
            L.append(f"  • {r['artifact']}")
            L.append(f"      flagged {r['flagged']} times "
                     f"({r['dispositioned']} dispositioned, {r['open']} open){cur}")
    L.append("")

    L.append("Refresh funnel — divergence-heuristic tuning signal (artifact-log.jsonl):")
    if not hd["refresh_funnel"]:
        L.append("  no data")
    else:
        L.append("  by spec:")
        for sp in p["refresh_funnel"]["by_spec"]:
            if (sp["detected"] + sp["refreshed"] + sp["rejected"] + sp["open"]) == 0:
                continue
            name = f" {sp['name']}" if sp.get("name") else ""
            arrow = aa._glyph("→", "->")
            L.append(f"    spec {sp['spec']}{name}: {sp['detected']} detected {arrow} "
                     f"{sp['drifted']} drifted {arrow} {sp['refreshed']} refreshed {arrow} "
                     f"{sp['rejected']} rejected {arrow} {sp['open']} still open")
        L.append("  by upstream stem:")
        for st in p["refresh_funnel"]["by_stem"]:
            L.append(f"    {st['stem']}: {st['detected']} detected · {st['drifted']} drifted · "
                     f"{st['refreshed']} applied · {st['rejected']} rejected · {st['open']} open")
            L.append(f"        {st['note']}")
    L.append("")

    L.append("Disposition debt rollup (honest counting):")
    if not hd["debt"]:
        L.append("  no data")
    else:
        d = p["debt"]
        L.append(f"  findings debt        (findings-log.jsonl):  {d['findings']}")
        L.append(f"  artifact staleness   (artifact-log.jsonl):  {d['artifact_staleness']}")
        L.append(f"  refresh open         (artifact-log.jsonl):  {d['refresh_open']}")
        L.append(f"  total open debt:     {d['total']}")
    L.append("")

    # Sections 5 + 6 exist only when the sprint ledger does — never a phantom block for a repo that
    # has no sprints, so the four legacy sections above stay byte-identical.
    if p.get("sprint_ledger_present"):
        arrow = aa._glyph("→", "->")
        L.append("Carry-over recurrence (sprint-log.jsonl — per spec, never per person):")
        if not hd.get("carry_over_recurrence"):
            L.append("  no data")
        else:
            for r in p["carry_over_recurrence"]:
                n = r["carried"]
                flag = " — RECURRING" if r["flagged"] else ""
                L.append(f"  • spec {r['spec']}: carried out of {n} sprint{'s' if n != 1 else ''} "
                         f"({', '.join(r['sprints'])}){flag}")
                for c in r["carries"]:
                    L.append(f"      {c['from']} {arrow} {c['to']}: {c['reason']}")
        L.append("")

        if hd.get("bounce_causes"):
            L.append("Bounce causes (verdict: returned — by lane and reason, never by who returned it):")
            current_lane = None
            for b in p["bounce_causes"]:
                if b["lane"] != current_lane:
                    current_lane = b["lane"]
                    L.append(f"  {current_lane}:")
                specs = f"; specs {', '.join(b['specs'])}" if b["specs"] else ""
                L.append(f"    • {b['reason']} ({b['times']} time{'s' if b['times'] != 1 else ''}{specs})")
            L.append("")

    # Section 7, only when the payload carries it (the mirror's ledger exists): the text before it is unchanged.
    if p.get("boards"):
        L.extend(format_boards(p["boards"]))
        L.append("")

    L.append("=" * 60)
    L.append("ADVISORY — read-only; patterns, not people; never blocks (exit 0).")
    L.append("Never tracked: velocity, story points, PR count, lines of code. No per-person ranking.")
    return "\n".join(L)


# --- CLI ---------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Cross-ledger retro roll-up: recurring findings, repeat-stale artifacts, the "
                    "refresh funnel, combined disposition debt, and — when sprint-log.jsonl exists — "
                    "carry-over recurrence and bounce causes (read-only, advisory; exit 0)")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--state", help="Path to .sdlc/state.yaml (workflow mode)")
    src.add_argument("--repo", default=".", help="Repo root containing .sdlc/ (standalone; default cwd)")
    p.add_argument("--window-days", dest="window_days", type=int, default=None,
                   help="Only count time-stamped ledger events from the last N days (default: all history)")
    p.add_argument("--json", action="store_true", help="Emit JSON (per-section has_data flags)")
    return p


def main() -> None:
    args = build_parser().parse_args()
    try:
        payload = build_payload(args)
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(format_report(payload))
    except SystemExit:
        raise  # resolve_paths exits 0 on a missing --state; honour it
    except Exception as exc:  # advisory: never a stack trace, never a non-zero exit
        print(f"retro — could not complete the roll-up ({type(exc).__name__}); no data.")
    sys.exit(0)


if __name__ == "__main__":
    main()
