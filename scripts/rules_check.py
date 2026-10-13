"""Advisory check of business rules against golden scenarios (the mechanical half of /sprd-rules).

Reads business-rules.md (a `BR-NN` decision table), golden-scenarios.md (a `SCEN-NN` table) and the
optional decision-log, and reports what a person would otherwise have to find by reading:
  - a rule with no Source (empty, or a dash) or no Approver,
  - a scenario that references no `BR-NN`,
  - a rule that no scenario references,
  - a rule marked `*(pending DL-NN)*`, and whether that `DL-NN` is in the decision log
    (`unverifiable` when there is no decision log to look in).

Every finding is SHOULD and the process exits 0 on every path except a usage error (2): it is
advisory by construction and can never block the loop. Missing data is reported as `has_data: false`
with a note, never as a zero count. The output carries no timestamps and no paths, so the same
documents give byte-identical output wherever they live.

Both documents are a preamble plus ONE markdown table (no `## ` headings), so the table is parsed
directly and columns are matched by header text, never position.

Standalone or Workflow (CLAUDE.md design rule):
  - Workflow:   --state .sdlc/state.yaml  (or --repo <root>): reads
                .sdlc/artifacts/01-requirements/{business-rules,golden-scenarios}.md and
                .sdlc/decision-log.md; --state also logs to .sdlc/metrics/rules-log.jsonl
  - Standalone: --business-rules P --scenarios P [--decision-log P], no .sdlc/ needed. Explicit
                paths also override the workflow locations.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ARTIFACT_DIR = Path("artifacts") / "01-requirements"
RULES_FILE = "business-rules.md"
SCENARIOS_FILE = "golden-scenarios.md"
DECISION_LOG_FILE = "decision-log.md"

SEVERITY = "SHOULD"
EMPTY_MARKS = {"", "-", "—", "–"}

_PLACEHOLDER_SPAN_RE = re.compile(
    r"\[[^\]]+\](?!\()"
    r"|<(?!/?(?:br|b|i|u|p|em|strong|code|span|sub|sup|hr|a|img|div)\b)[^<>\n]+>",
    re.IGNORECASE,
)
_WHOLE_PLACEHOLDER_RE = re.compile(r"^(?:\[[^\]]+\]|<[^<>\n]+>)$")
_UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")
_SEPARATOR_CELL_RE = re.compile(r":?-+:?")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_RULE_ID_RE = re.compile(r"^BR-(\d+)$", re.IGNORECASE)
_SCENARIO_ID_RE = re.compile(r"^SCEN-(\d+)$", re.IGNORECASE)
_DECISION_ID_RE = re.compile(r"^DL-(\d+)$", re.IGNORECASE)
_RULE_REF_RE = re.compile(r"\bBR-(\d+)\b", re.IGNORECASE)
_DECISION_REF_RE = re.compile(r"\bDL-(\d+)\b", re.IGNORECASE)
# `*(pending DL-03)*`; the template spells the id `<DL-NN>`, so that is tolerated too.
_PENDING_RE = re.compile(r"\(\s*pending\s+<?\s*(DL-(?:\d+|NN))\s*>?\s*\)", re.IGNORECASE)

ID_HEADERS = {"rule": {"rule", "rule id", "id"}, "scenario": {"scenario", "scenario id", "id"},
              "decision": {"id"}}


# --- markdown table reading ---------------------------------------------------------------------

def _split_cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [c.strip() for c in _UNESCAPED_PIPE_RE.split(body)]


def _is_placeholder_row(cells: list[str]) -> bool:
    """More than half of the non-empty cells hold a `[bracketed]` or `<angle>` span (the rule
    document_shape_cli uses): a template's stand-in row, not a record."""
    filled = [c for c in cells if c]
    marked = sum(1 for c in filled if _PLACEHOLDER_SPAN_RE.search(c))
    return marked > 0 and marked * 2 > len(filled)


def _is_separator(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return False
    cells = [c for c in _split_cells(stripped) if c]
    return bool(cells) and all(_SEPARATOR_CELL_RE.fullmatch(c) for c in cells)


def _tables(text: str):
    """Yield (headers, rows) for each pipe table outside code fences; headers are lower-cased with
    markdown emphasis stripped, rows are lists of cells padded to the header width."""
    lines = text.splitlines()
    in_fence, i = False, 0
    while i < len(lines):
        line = lines[i]
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        starts_table = (not in_fence and line.strip().startswith("|")
                        and i + 1 < len(lines) and _is_separator(lines[i + 1]))
        if not starts_table:
            i += 1
            continue
        headers = [re.sub(r"[`*_]", "", h).strip().lower() for h in _split_cells(line)]
        rows, i = [], i + 2
        while i < len(lines) and lines[i].strip().startswith("|"):
            cells = _split_cells(lines[i])
            rows.append(cells + [""] * (len(headers) - len(cells)))
            i += 1
        yield headers, rows


def _first_table_with(text: str, id_headers: set[str]):
    """(headers, rows) of the first table that has an id column, else None."""
    for headers, rows in _tables(text):
        if any(h in id_headers for h in headers):
            return headers, rows
    return None


def _column(headers: list[str], names: set[str]) -> int | None:
    return next((i for i, h in enumerate(headers) if h in names), None)


def _cell(row: list[str], index: int | None) -> str:
    return row[index].strip() if index is not None and index < len(row) else ""


def _is_unfilled(cell: str) -> bool:
    """Empty, or still wholly a template `[placeholder]`. A dash is a deliberate "none yet" in
    Source, so callers that treat a dash as missing check EMPTY_MARKS themselves."""
    return not cell or bool(_WHOLE_PLACEHOLDER_RE.match(cell))


# --- the three documents ------------------------------------------------------------------------

def _read(path: Path | None) -> tuple[str | None, str | None]:
    """(text, note). A missing or unreadable file is a note, never a crash."""
    if path is None:
        return None, None
    if not path.is_file():
        return None, f"{path.name} not found"
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace"), None
    except OSError as e:
        return None, f"{path.name} could not be read: {e.strerror or e}"


def _rule_id(cell: str) -> str | None:
    m = _RULE_ID_RE.match(re.sub(r"[`*_]", "", cell).strip())
    return f"BR-{int(m.group(1)):02d}" if m else None


def parse_rules(text: str, name: str) -> tuple[list[dict], str | None]:
    """The real `BR-NN` rows of the rules table, and a note when there is nothing to assess."""
    table = _first_table_with(text, ID_HEADERS["rule"])
    if table is None:
        return [], f"{name} has no rules table (a table with a Rule column)"
    headers, rows = table
    idc, srcc, appc, outc = (_column(headers, ID_HEADERS["rule"]), _column(headers, {"source"}),
                             _column(headers, {"approver"}), _column(headers, {"outcome"}))
    rules = []
    for row in rows:
        rid = _rule_id(_cell(row, idc))
        if rid is None or _is_placeholder_row(row):
            continue
        outcome = _cell(row, outc) if outc is not None else " | ".join(row)
        m = _PENDING_RE.search(outcome)
        rules.append({"id": rid, "source_cell": _cell(row, srcc), "approver_cell": _cell(row, appc),
                      "pending": m.group(1).upper() if m else None})
    return rules, None if rules else f"{name} has no rules yet (only template placeholders)"


def parse_scenarios(text: str, name: str) -> tuple[list[dict], str | None]:
    table = _first_table_with(text, ID_HEADERS["scenario"])
    if table is None:
        return [], f"{name} has no scenarios table (a table with a Scenario column)"
    headers, rows = table
    idc = _column(headers, ID_HEADERS["scenario"])
    scenarios = []
    for row in rows:
        m = _SCENARIO_ID_RE.match(re.sub(r"[`*_]", "", _cell(row, idc)).strip())
        if m is None or _is_placeholder_row(row):
            continue
        refs = sorted({f"BR-{int(n):02d}" for n in _RULE_REF_RE.findall(" | ".join(row))})
        scenarios.append({"id": f"SCEN-{int(m.group(1)):02d}", "references": refs})
    return scenarios, None if scenarios else f"{name} has no scenarios yet (only template placeholders)"


def parse_decision_ids(text: str) -> set[str]:
    """The DL-NN ids the log records: its table rows, else any DL-NN the text mentions."""
    table = _first_table_with(text, ID_HEADERS["decision"])
    if table is None:
        return {f"DL-{int(n):02d}" for n in _DECISION_REF_RE.findall(text)}
    headers, rows = table
    idc = _column(headers, ID_HEADERS["decision"])
    ids = set()
    for row in rows:
        m = _DECISION_ID_RE.match(re.sub(r"[`*_]", "", _cell(row, idc)).strip())
        if m and not _is_placeholder_row(row):
            ids.add(f"DL-{int(m.group(1)):02d}")
    return ids


def _normal_decision(dl: str) -> str:
    m = _DECISION_REF_RE.fullmatch(dl)
    return f"DL-{int(m.group(1)):02d}" if m else dl


# --- the report ---------------------------------------------------------------------------------

def _finding(check: str, subject: str, message: str) -> dict:
    return {"check": check, "severity": SEVERITY, "subject": subject, "message": message}


def _rule_findings(rules: list[dict]) -> list[dict]:
    out = []
    for r in rules:
        if _is_unfilled(r["source_cell"]) or r["source_cell"] in EMPTY_MARKS:
            out.append(_finding("source-missing", r["id"],
                                f"{r['id']} has no Source - cite the policy it comes from, or open a decision-log item"))
        if _is_unfilled(r["approver_cell"]):
            out.append(_finding("approver-missing", r["id"],
                                f"{r['id']} has no Approver - a named person must confirm each rule"))
    return out


def _decision_state(pending: str | None, decision_ids: set[str] | None) -> str | None:
    if pending is None:
        return None
    if decision_ids is None:
        return "unverifiable"
    return "present" if _normal_decision(pending) in decision_ids else "missing"


def build_report(rules_doc, scenarios_doc, decision_doc, notes: list[str]) -> dict:
    """Pure assembly. Each *_doc is the parsed rows, or None when that document gave no data;
    decision_doc is the set of DL ids, or None when there is no decision log."""
    rules = rules_doc or []
    scenarios = scenarios_doc or []
    cross_checked = bool(rules_doc) and bool(scenarios_doc)
    referenced: dict[str, list[str]] = {r["id"]: [] for r in rules}
    for s in scenarios:
        for ref in s["references"]:
            if ref in referenced:
                referenced[ref].append(s["id"])

    findings = _rule_findings(rules)
    for s in scenarios:
        if not s["references"]:
            findings.append(_finding("scenario-no-rule", s["id"],
                                     f"{s['id']} references no BR-NN - tie it to the rule it exercises"))
    if cross_checked:
        findings += [_finding("rule-no-scenario", r["id"], f"{r['id']} is not referenced by any scenario")
                     for r in rules if not referenced[r["id"]]]
    for r in rules:
        state = _decision_state(r["pending"], decision_doc)
        if state == "missing":
            findings.append(_finding("pending-missing", r["id"],
                                     f"{r['id']} is pending {r['pending']}, which is not in the decision log"))
        elif state == "unverifiable":
            findings.append(_finding("pending-unverifiable", r["id"],
                                     f"{r['id']} is pending {r['pending']}, but there is no decision log to check it against"))

    rule_rows = [{"id": r["id"], "source": r["source_cell"] or None, "approver": r["approver_cell"] or None,
                  "pending": r["pending"], "pending_decision": _decision_state(r["pending"], decision_doc),
                  "scenarios": referenced[r["id"]]} for r in rules]
    return {
        "has_data": bool(rules or scenarios),
        "notes": notes,
        "rules": rule_rows,
        "scenarios": [{"id": s["id"], "references": s["references"]} for s in scenarios],
        "findings": findings,
        "counts": {"rules": len(rules), "scenarios": len(scenarios),
                   "pending": sum(1 for r in rules if r["pending"]), "findings": len(findings)},
        "advisory": True,
    }


def analyse(rules_path: Path | None, scenarios_path: Path | None, log_path: Path | None) -> dict:
    notes: list[str] = []
    rules_doc = scenarios_doc = decision_doc = None

    text, note = _read(rules_path)
    if rules_path is None:
        notes.append("no business-rules path given")
    elif text is None:
        notes.append(note)
    else:
        rules_doc, note = parse_rules(text, rules_path.name)
        notes += [note] if note else []

    text, note = _read(scenarios_path)
    if scenarios_path is None:
        notes.append("no golden-scenarios path given")
    elif text is None:
        notes.append(note)
    else:
        scenarios_doc, note = parse_scenarios(text, scenarios_path.name)
        notes += [note] if note else []

    text, note = _read(log_path)
    if text is not None:
        decision_doc = parse_decision_ids(text)
    elif log_path is not None and note:
        notes.append(f"{note}; pending rules cannot be verified")
    if rules_doc and not scenarios_doc:
        notes.append("rules were not cross-checked against scenarios: there are no scenarios to check them against")
    if scenarios_doc and not rules_doc:
        notes.append("scenarios were not cross-checked against rules: there are no rules to check them against")
    return build_report(rules_doc, scenarios_doc, decision_doc, notes)


def format_report(report: dict) -> str:
    bar = "=" * 50
    lines = ["Business Rules Check", bar]
    lines += [f"  NOTE    {n}" for n in report["notes"]]
    for r in report["rules"]:
        if r["pending"]:
            lines.append(f"  PENDING {r['id']} - waiting on {r['pending']} ({r['pending_decision']})")
    for f in report["findings"]:
        lines.append(f"  ADVISE  [{f['severity']}] {f['message']}")
    lines.append(bar)
    c = report["counts"]
    if not report["has_data"]:
        lines.append("ADVISORY - no rules or scenarios to assess (advisory check - never blocks).")
    elif report["findings"]:
        lines.append(f"ADVISORY - {c['findings']} finding(s) across {c['rules']} rule(s) and "
                     f"{c['scenarios']} scenario(s) (SHOULD; never blocks).")
    else:
        lines.append(f"ADVISORY - {c['rules']} rule(s) and {c['scenarios']} scenario(s), no findings "
                     "(advisory check - never blocks).")
    return "\n".join(lines)


def log_metrics(report: dict, metrics_dir: Path) -> None:
    """Append a summary entry to .sdlc/metrics/rules-log.jsonl (mirrors check_channel's log)."""
    metrics_dir.mkdir(parents=True, exist_ok=True)
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), **report["counts"],
             "advisories": [{"check": f["check"], "subject": f["subject"]} for f in report["findings"]]}
    with open(metrics_dir / "rules-log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# --- paths and entry point ----------------------------------------------------------------------

def resolve_paths(args) -> tuple[Path | None, Path | None, Path | None, Path | None]:
    """(rules, scenarios, decision_log, sdlc_dir). An explicit path beats the workflow location."""
    sdlc_dir = None
    rules = scenarios = log = None
    if args.state:
        sdlc_dir = Path(args.state).parent
    elif args.repo:
        sdlc_dir = Path(args.repo) / ".sdlc"
    if sdlc_dir is not None:
        rules, scenarios = sdlc_dir / ARTIFACT_DIR / RULES_FILE, sdlc_dir / ARTIFACT_DIR / SCENARIOS_FILE
        log = sdlc_dir / DECISION_LOG_FILE
        if args.repo and not log.exists() and (Path(args.repo) / DECISION_LOG_FILE).exists():
            log = Path(args.repo) / DECISION_LOG_FILE  # standalone repos keep it at the root
    pick = lambda explicit, default: Path(explicit) if explicit else default  # noqa: E731
    return (pick(args.business_rules, rules), pick(args.scenarios, scenarios),
            pick(args.decision_log, log), sdlc_dir if args.state else None)


def main():
    parser = argparse.ArgumentParser(
        description="Advisory check of business rules against golden scenarios (never blocks)")
    parser.add_argument("--state", default=None, help="Path to .sdlc/state.yaml (workflow mode; also logs metrics)")
    parser.add_argument("--repo", default=None, help="Project root (reads <repo>/.sdlc/...)")
    parser.add_argument("--business-rules", default=None, help="Explicit path to business-rules.md")
    parser.add_argument("--scenarios", default=None, help="Explicit path to golden-scenarios.md")
    parser.add_argument("--decision-log", default=None, help="Explicit path to decision-log.md")
    parser.add_argument("--json", action="store_true", help="Emit the result as one JSON document")
    args = parser.parse_args()

    if args.state and args.repo:
        parser.error("give --state or --repo, not both")
    if not (args.state or args.repo or args.business_rules or args.scenarios or args.decision_log):
        parser.error("give --state, --repo, or at least one of --business-rules/--scenarios/--decision-log")

    rules_path, scenarios_path, log_path, sdlc_dir = resolve_paths(args)
    report = analyse(rules_path, scenarios_path, log_path)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(report, indent=2) if args.json else format_report(report))

    if sdlc_dir is not None and Path(args.state).exists() and report["has_data"]:
        log_metrics(report, sdlc_dir / "metrics")
    sys.exit(0)


if __name__ == "__main__":
    main()
