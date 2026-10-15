"""Track the phase-spanning product decision-log (.sdlc/decision-log.md).

Product's decision-log captures cross-cutting decisions *before* specs exist — each with a named
owner and a 2-business-day clock — distinct from the per-spec Decision List (silent decisions
inside one spec). This tracker reads the markdown table, lists the OPEN decisions, and flags any
whose 2-business-day (weekend-aware) clock, counted from the `opened` date, has elapsed. It is
advisory: it ALWAYS exits 0. It mirrors track_specs.py — the log is the durable source of truth,
not a separate tracker that can drift.

The decision table columns are: id | decision | owner | opened | due | status
Dates are ISO (YYYY-MM-DD). A decision is OPEN unless its status is a closed word
(closed / resolved / decided / done / cancelled).

Standalone or Workflow:
  - Workflow:   --state .sdlc/state.yaml   (reads <state.parent>/decision-log.md)
  - Standalone: --repo <path>              (reads <repo>/.sdlc/decision-log.md, else <repo>/decision-log.md)

With no verb it reports (advisory, always exit 0). Two verbs own the clock so no one hand-writes it:
  - open   allocate the next DL-NN and write one row (opened = today, due = 2 business days later)
  - decide close a row: status -> decided, resolution and decider recorded in the decision cell
Both are targeted text edits: every byte of the log they do not mean to change is unchanged, and a
refusal (exit 1, message on stderr) leaves the file untouched.

`open --all-branches` also reads the log on every local branch and remote-tracking ref (through
branch_scan.py) so the new id is unused on all of them: two branches opening "the next" decision
would otherwise both write DL-07. It never fetches (run `git fetch` first), a ref whose log cannot
be used is named in `unread` rather than ignored, and without the flag nothing about `open` changes.
"""

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

DECISION_COLUMNS = ["id", "decision", "owner", "opened", "due", "status"]
CLOSED_STATUSES = {
    "closed", "resolved", "decided", "done", "complete", "completed", "cancelled", "canceled",
}
CLOCK_BUSINESS_DAYS = 2
TEMPLATE_PATH = (Path(__file__).resolve().parent.parent
                 / "templates" / "phases" / "01-requirements" / "decision-log.md")


# --- Business-day math (weekend-aware; Mon-Fri are business days) ---

def business_days_elapsed(start: date, end: date) -> int:
    """Count business days strictly after `start`, up to and including `end`. 0 if end <= start."""
    if end <= start:
        return 0
    count = 0
    d = start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:  # Monday=0 .. Friday=4
            count += 1
    return count


def add_business_days(start: date, n: int) -> date:
    """The date `n` business days after `start` (skipping weekends)."""
    d = start
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


def parse_iso_date(s: str) -> date | None:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# --- Decision-log parsing ---

_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def _split_row(line: str) -> list[str]:
    """Cells of a table row. `\\|` is a literal pipe inside a cell (how `open` writes one)."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.strip().replace("\\|", "|") for c in _UNESCAPED_PIPE.split(line)]


def _is_separator(cells: list[str]) -> bool:
    joined = "".join(cells)
    return bool(joined) and set(joined) <= set("-:| ")


def parse_decisions(path: Path) -> list[dict]:
    """Parse the decision table into row dicts keyed by DECISION_COLUMNS."""
    if not path.exists():
        return []

    table_rows: list[list[str]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        cells = _split_row(line)
        if _is_separator(cells):
            continue
        table_rows.append(cells)

    if not table_rows:
        return []

    # Locate a header row (has "id" and "status"/"decision"); parse rows after it.
    header: dict[str, int] | None = None
    start = 0
    for i, cells in enumerate(table_rows):
        lower = [c.lower() for c in cells]
        if "id" in lower and ("status" in lower or "decision" in lower):
            header = {name: lower.index(name) for name in DECISION_COLUMNS if name in lower}
            start = i + 1
            break

    decisions: list[dict] = []
    for cells in table_rows[start:]:
        def get(col: str, cells=cells) -> str:
            if header is not None and header.get(col) is not None and header[col] < len(cells):
                return cells[header[col]]
            pos = DECISION_COLUMNS.index(col)
            return cells[pos] if pos < len(cells) else ""

        row = {col: get(col) for col in DECISION_COLUMNS}
        if not any(row.values()):
            continue
        decisions.append(row)
    return decisions


def is_open(decision: dict) -> bool:
    return decision.get("status", "").strip().lower() not in CLOSED_STATUSES


def summarize(decisions: list[dict], today: date | None = None) -> dict:
    """Open decisions + overdue flags off the 2-business-day clock from `opened`."""
    today = today or date.today()
    open_decisions: list[dict] = []
    overdue: list[dict] = []

    for d in decisions:
        if not is_open(d):
            continue
        rec = dict(d)
        opened = parse_iso_date(d.get("opened", ""))
        if opened is None:
            rec["business_days_open"] = None
            rec["clock_due"] = None
            rec["overdue"] = False
            rec["opened_unparseable"] = True
        else:
            elapsed = business_days_elapsed(opened, today)
            rec["business_days_open"] = elapsed
            rec["clock_due"] = add_business_days(opened, CLOCK_BUSINESS_DAYS).isoformat()
            rec["overdue"] = elapsed > CLOCK_BUSINESS_DAYS
        open_decisions.append(rec)
        if rec["overdue"]:
            overdue.append(rec)

    return {
        "total": len(decisions),
        "open": len(open_decisions),
        "overdue": len(overdue),
        "clock_business_days": CLOCK_BUSINESS_DAYS,
        "open_decisions": open_decisions,
        "overdue_decisions": overdue,
    }


def resolve_log_path(args) -> Path:
    if args.state:
        state_path = Path(args.state)
        if not state_path.exists():
            print(f"Error: State file not found: {state_path}")
            sys.exit(1)
        return state_path.resolve().parent / "decision-log.md"
    repo = Path(args.repo).resolve()
    in_sdlc = repo / ".sdlc" / "decision-log.md"
    return in_sdlc if in_sdlc.exists() else repo / "decision-log.md"


def format_report(summary: dict, log_path: Path) -> str:
    lines = ["Decision Log", "=" * 44]
    if not log_path.exists():
        lines.append(f"No decision-log found at {log_path}.")
        lines.append("(advisory — nothing to track yet)")
        return "\n".join(lines)

    lines.append(f"Total decisions: {summary['total']}")
    lines.append(f"Open: {summary['open']}   Overdue (> {summary['clock_business_days']} business days): {summary['overdue']}")

    if summary["open_decisions"]:
        lines.append("")
        lines.append(f"Open decisions ({summary['clock_business_days']}-business-day clock from 'opened'):")
        for d in summary["open_decisions"]:
            flag = "  OVERDUE" if d.get("overdue") else ""
            bdo = d.get("business_days_open")
            age = "opened date unparseable" if bdo is None else f"{bdo} business day(s) open"
            owner = d.get("owner") or "(no owner)"
            due = d.get("clock_due") or d.get("due") or "?"
            lines.append(f"  {d.get('id') or '?'}  [{owner}]  opened {d.get('opened') or '?'}  "
                         f"due {due}  — {age}{flag}")
            if d.get("decision"):
                lines.append(f"       {d['decision']}")
    else:
        lines.append("")
        lines.append("No open decisions.")

    if summary["overdue_decisions"]:
        lines.append("")
        lines.append("WARNING: overdue decisions need an owner's call:")
        for d in summary["overdue_decisions"]:
            lines.append(f"  {d.get('id') or '?'} — {d.get('owner') or '(no owner)'} "
                         f"(open {d.get('business_days_open')} business days)")

    return "\n".join(lines)


# --- Writing: the `open` and `decide` verbs (targeted text edits) ---

ID_RE = re.compile(r"\bDL-(\d+)\b", re.IGNORECASE)
PLACEHOLDER_SPAN_RE = re.compile(r"\[[^\]]*\]|<[^>]*>")
FIRST_WORD_RE = re.compile(r"\W*(\w+)")
LINE_RE = re.compile(r"[^\n]*\n|[^\n]+")


class LogError(Exception):
    """A refusal: reported on stderr with exit 1, and the log is never written."""


def _read(path: Path) -> str:
    with path.open(encoding="utf-8", newline="") as f:
        return f.read()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(text)


def _split_lines(text: str) -> list[str]:
    """Lines with their endings attached, split on \\n only, so `"".join` restores every byte."""
    return LINE_RE.findall(text)


def _split_eol(line: str) -> tuple[str, str]:
    body = line.rstrip("\r\n")
    return body, line[len(body):]


def _cell_spans(body: str) -> list[tuple[int, int]]:
    """(start, end) of each cell's raw text in a table row, excluding the delimiting pipes."""
    end = len(body.rstrip())
    first = len(body) - len(body.lstrip())
    pipes = [i for i in range(first, end) if body[i] == "|" and (i == 0 or body[i - 1] != "\\")]
    bounds = pipes if pipes and pipes[-1] == end - 1 else pipes + [end]
    return [(a + 1, b) for a, b in zip(bounds, bounds[1:])]


def _cell_text(body: str, span: tuple[int, int]) -> str:
    return body[span[0]:span[1]].strip().replace("\\|", "|")


def _is_placeholder(cells: list[str]) -> bool:
    """A template example row: at least half its non-empty cells hold a [bracketed] or <angle> span."""
    filled = [c for c in cells if c]
    hits = sum(1 for c in filled if PLACEHOLDER_SPAN_RE.search(c))
    return bool(filled) and hits * 2 >= len(filled)


def _clean(value: str) -> str:
    """One table cell's worth of text: newlines collapse to a space, edges trimmed, pipes escaped."""
    return re.sub(r"\s*[\r\n]+\s*", " ", value).strip().replace("|", "\\|")


class _Table:
    def __init__(self, cols: dict[str, int], width: int, rows: list[int], separator: int):
        self.cols = cols      # column name -> cell index
        self.width = width    # number of header cells
        self.rows = rows      # indexes into `lines` of the data rows
        # Where a new row goes after: the last data row, or — for a table with a header and no
        # rows yet — the separator line. (It was -1, which indexed the END of the file and wrote
        # the row above the document's title.)
        self.last = rows[-1] if rows else separator


def _find_table(lines: list[str]) -> _Table:
    """The first pipe table with an `id` column; columns matched on their first word, any case."""
    i = 0
    while i < len(lines):
        if not lines[i].lstrip().startswith("|"):
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j].lstrip().startswith("|"):
            j += 1
        header, sep = (_split_row(lines[i]), _split_row(lines[i + 1])) if j - i >= 2 else ([], [])
        words = [(m.group(1).lower() if (m := FIRST_WORD_RE.match(c)) else "") for c in header]
        if "id" in words and _is_separator(sep):
            cols: dict[str, int] = {}
            for idx, w in enumerate(words):
                if w in DECISION_COLUMNS and w not in cols:
                    cols[w] = idx
            if len(cols) != len(DECISION_COLUMNS):
                raise LogError(
                    "decision table header not recognised (headers found: "
                    + ", ".join(h or "(blank)" for h in header)
                    + "; need columns starting " + ", ".join(DECISION_COLUMNS) + ")")
            rows = [k for k in range(i + 2, j) if not _is_separator(_split_row(lines[k]))]
            return _Table(cols, len(header), rows, separator=i + 1)
        i = j
    raise LogError("no decision table (| id | decision | owner | opened | due | status |) found in the log")


def _row_cells(line: str) -> list[str]:
    body = _split_eol(line)[0]
    return [_cell_text(body, sp) for sp in _cell_spans(body)]


def _template_lines() -> set[str]:
    if not TEMPLATE_PATH.exists():
        return set()
    return {_split_eol(ln)[0] for ln in _split_lines(_read(TEMPLATE_PATH)) if ln.strip()}


def _highest_used(lines: list[str], table: _Table, placeholders: set[int]) -> int:
    """Highest DL-NN mentioned anywhere in the log, prose included.

    Two things do not count as use: a placeholder row (an example, not a record) and a line that is
    verbatim shipped template text (the template's own prose cites `DL-01` as an example, and a fresh
    log must still start at DL-01). Anything a person wrote or edited counts, wherever it sits.
    """
    shipped = _template_lines()
    highest = 0
    for idx, line in enumerate(lines):
        if idx in placeholders or _split_eol(line)[0] in shipped:
            continue
        for m in ID_RE.finditer(line):
            highest = max(highest, int(m.group(1)))
    return highest


def _validated_date(value: str | None, flag: str) -> date:
    if value is None:
        return date.today()
    parsed = parse_iso_date(value)
    if parsed is None:
        raise LogError(f"{flag} must be a date as YYYY-MM-DD (got '{value}')")
    return parsed


def _highest_in_logs(texts) -> int:
    """Highest DL-NN used in any of these other logs (each judged against its own table and
    placeholder rows, exactly as the local log is). A text with no usable table raises LogError:
    the caller filters those out first, because naming them is its job, not this function's."""
    highest = 0
    for text in texts:
        lines = _split_lines(text)
        table = _find_table(lines)
        placeholders = {k for k in table.rows if _is_placeholder(_row_cells(lines[k]))}
        highest = max(highest, _highest_used(lines, table, placeholders))
    return highest


def open_decision(log_path: Path, decision: str, owner: str, opened: date, other_logs: list[str] = ()) -> dict:
    """Append one open row (creating the log from the template when absent); returns its fields."""
    decision, owner = _clean(decision), _clean(owner)
    if not decision:
        raise LogError("--decision must not be empty: a decision with no question is not a decision")
    if not owner:
        raise LogError("--owner must name a person or role: an unowned decision never gets decided")

    source = log_path if log_path.exists() else TEMPLATE_PATH
    if not source.exists():
        raise LogError(f"decision-log template not found: {TEMPLATE_PATH}")
    text = _read(source)
    lines = _split_lines(text)
    table = _find_table(lines)
    placeholders = {k for k in table.rows if _is_placeholder(_row_cells(lines[k]))}

    ident = f"DL-{_highest_used(lines, table, placeholders) + 1:02d}"
    if other_logs:  # --all-branches: the id must also clear every other branch's log
        ident = f"DL-{max(int(ident[3:]), _highest_in_logs(other_logs) + 1):02d}"
    due = add_business_days(opened, CLOCK_BUSINESS_DAYS)
    values = {"id": ident, "decision": decision, "owner": owner,
              "opened": opened.isoformat(), "due": due.isoformat(), "status": "open"}
    cells = [""] * table.width
    for name, idx in table.cols.items():
        cells[idx] = values[name]
    row = "| " + " | ".join(cells) + " |"

    if placeholders:
        k = min(placeholders)
        lines[k] = row + _split_eol(lines[k])[1]
    else:
        eol = _split_eol(lines[table.last])[1]
        if eol:
            lines.insert(table.last + 1, row + eol)
        else:  # table ends the file with no final newline: add one, and mirror it on the new row
            lines[table.last] += "\r\n" if "\r\n" in text else "\n"
            lines.insert(table.last + 1, row)
    _write(log_path, "".join(lines))
    return {"id": ident, "opened": values["opened"], "due": values["due"], "owner": owner}


def decide_decision(log_path: Path, ident: str, by: str, resolution: str, decided: date) -> dict:
    """Close one row in place: status cell -> decided, resolution and decider appended to the decision."""
    by, resolution = _clean(by), _clean(resolution)
    if not by:
        raise LogError("--by must name the person who decided")
    if not resolution:
        raise LogError("--resolution must say what was decided")
    if not log_path.exists():
        raise LogError(f"no decision-log at {log_path}")

    lines = _split_lines(_read(log_path))
    table = _find_table(lines)
    wanted = ident.strip().upper()
    for k in table.rows:
        body = _split_eol(lines[k])[0]
        spans = _cell_spans(body)
        if len(spans) < table.width or _cell_text(body, spans[table.cols["id"]]).upper() != wanted:
            continue
        status = _cell_text(body, spans[table.cols["status"]])
        if status.lower() in CLOSED_STATUSES:
            raise LogError(f"{wanted} is already '{status}'; a closed decision is not reopened here")
        suffix = f" — decided by {by} on {decided.isoformat()}: {resolution}"
        edits = {table.cols["status"]: "decided", table.cols["decision"]: None}
        for idx in sorted(edits, reverse=True):  # later cell first, so earlier spans stay valid
            a, b = spans[idx]
            raw = body[a:b]
            lead = raw[:len(raw) - len(raw.lstrip())]
            tail = raw[len(raw.rstrip()):]
            content = raw.strip()
            new = "decided" if edits[idx] else (content + suffix if content else suffix.lstrip())
            body = body[:a] + lead + new + tail + body[b:]
        lines[k] = body + _split_eol(lines[k])[1]
        _write(log_path, "".join(lines))
        return {"id": wanted, "status": "decided", "decided": decided.isoformat(), "by": by}
    raise LogError(f"no decision {wanted} in {log_path}")


def resolve_write_target(args) -> tuple[Path, Path]:
    """(log path, repo root) for a verb; a log that does not exist yet goes in <repo>/.sdlc/."""
    if args.state:
        state_path = Path(args.state)
        if not state_path.exists():
            raise LogError(f"State file not found: {state_path}")
        sdlc_dir = state_path.resolve().parent
        return sdlc_dir / "decision-log.md", sdlc_dir.parent
    repo = Path(args.repo).resolve()
    for candidate in (repo / ".sdlc" / "decision-log.md", repo / "decision-log.md"):
        if candidate.exists():
            return candidate, repo
    return repo / ".sdlc" / "decision-log.md", repo


def run_open_all_branches(args, log_path: Path, repo_root: Path, shown: str) -> None:
    """`open --all-branches`: the same verb, with an id that clears every local ref's decision log.

    The scan is read-only and never fetches. A ref whose log has no usable table, or whose tree git
    could not read, is named in `unread` (and is not counted as checked); outside a git repository
    the verb proceeds on the local log alone, and says so. When nothing at all could be read (git
    missing or refusing the directory, a partial clone on a git too old to read it safely) `unread`
    holds one `(all refs)` entry and the text line says "could not read refs: <why>" — never a
    "checked" count that nobody earned. The base text lines are the ones `run_verb` prints without
    the flag; a test pins that the two cannot drift apart.
    """
    import branch_scan  # only this flag needs it, so every other importer of this module is unaffected

    scan = branch_scan.scan_file(repo_root, shown)
    readable: dict[str, str] = {}
    unread = list(scan.unread)
    for ref, text in scan.texts.items():
        try:
            _find_table(_split_lines(text))
        except LogError as e:
            unread.append({"ref": ref, "reason": str(e)})
        else:
            readable[ref] = text
    unread.sort(key=lambda u: u["ref"])
    unusable = {u["ref"] for u in unread}
    refs_scanned = [r for r in scan.refs_scanned if r not in unusable]

    result = open_decision(log_path, args.decision, args.owner, _validated_date(args.opened, "--opened"),
                           other_logs=list(readable.values()))
    result["path"] = shown
    result["refs_scanned"] = refs_scanned
    result["unread"] = unread
    text = (f"Decision opened: {result['id']}  [{result['owner']}]\n"
            f"  Due {result['due']} ({CLOCK_BUSINESS_DAYS} business days after {result['opened']})")
    text += f"\n  Ids checked on {branch_scan.checked_summary(scan.is_git, refs_scanned, unread)}"
    if unread and not args.json:  # stdout keeps its one extra line; what was skipped goes to stderr
        print("Warning: could not use the decision log on " + ", ".join(
            f"{u['ref']} ({u['reason']})" for u in unread), file=sys.stderr)
    print(json.dumps(result, indent=2) if args.json else text)


def run_verb(args) -> None:
    log_path, repo_root = resolve_write_target(args)
    try:
        shown = log_path.relative_to(repo_root).as_posix()
    except ValueError:
        shown = log_path.as_posix()

    if args.verb == "open" and getattr(args, "all_branches", False):
        run_open_all_branches(args, log_path, repo_root, shown)
        return

    if args.verb == "open":
        result = open_decision(log_path, args.decision, args.owner, _validated_date(args.opened, "--opened"))
        result["path"] = shown
        text = (f"Decision opened: {result['id']}  [{result['owner']}]\n"
                f"  Due {result['due']} ({CLOCK_BUSINESS_DAYS} business days after {result['opened']})")
    else:
        result = decide_decision(log_path, args.id, args.by, args.resolution,
                                 _validated_date(args.decided, "--decided"))
        result["path"] = shown
        text = f"Decision {result['id']} decided by {result['by']} on {result['decided']}"
    print(json.dumps(result, indent=2) if args.json else text)


# --- CLI ---

def build_parser() -> argparse.ArgumentParser:
    # SUPPRESS defaults: a value given before the verb must survive the verb's own parser.
    common = argparse.ArgumentParser(add_help=False)
    src = common.add_mutually_exclusive_group()
    src.add_argument("--state", default=argparse.SUPPRESS, help="Path to .sdlc/state.yaml (workflow mode)")
    src.add_argument("--repo", default=argparse.SUPPRESS,
                     help="Target repo root (standalone mode; default: cwd)")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="Emit the result as JSON")

    parser = argparse.ArgumentParser(
        description="Track the phase-spanning product decision-log (advisory); "
                    "`open` and `decide` write to it", parents=[common])
    verbs = parser.add_subparsers(dest="verb", metavar="{open,decide}")

    op = verbs.add_parser("open", parents=[common],
                          help="Open a decision: next DL-NN, opened today, due in 2 business days")
    op.add_argument("--decision", required=True, help="The open question a human must decide")
    op.add_argument("--owner", required=True, help="Named owner (person or role)")
    op.add_argument("--phase", help="Phase the decision opens in (accepted for context; not stored)")
    op.add_argument("--opened", help="Opened date YYYY-MM-DD (default: today)")
    op.add_argument("--all-branches", action="store_true",
                    help="Also read decision-log.md on every local branch and remote-tracking ref "
                         "(run `git fetch` first) so the new id is unused on all of them")

    de = verbs.add_parser("decide", parents=[common],
                          help="Close a decision: status -> decided, resolution recorded in the row")
    de.add_argument("--id", required=True, help="Decision id, e.g. DL-03")
    de.add_argument("--by", required=True, help="Who decided")
    de.add_argument("--resolution", required=True, help="What was decided")
    de.add_argument("--decided", help="Decided date YYYY-MM-DD (default: today)")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.state = getattr(args, "state", None)
    args.json = getattr(args, "json", False)
    args.all_branches = getattr(args, "all_branches", False)
    explicit_repo = hasattr(args, "repo")
    if args.state and explicit_repo:
        parser.error("argument --repo: not allowed with argument --state")
    args.repo = getattr(args, "repo", ".")

    if args.verb:
        try:
            run_verb(args)
        except LogError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    log_path = resolve_log_path(args)
    decisions = parse_decisions(log_path)
    summary = summarize(decisions)

    if args.json:
        print(json.dumps({**summary, "log_path": str(log_path), "exists": log_path.exists()}, indent=2))
    else:
        print(format_report(summary, log_path))

    # Advisory tracker — always exit 0.
    sys.exit(0)


if __name__ == "__main__":
    main()
