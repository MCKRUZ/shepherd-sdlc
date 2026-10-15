"""Create, link, report on and check *data specs* — the specs the Data discipline owns (spec 0039).

A data spec is the data work one build spec cannot ship without: a `type: data` spec whose
`serves: "<parent id>"` names that build spec, worked through /sprd-data, done when real data reaches
what the build spec calls. This is the CLI; every judgement about what a data spec IS lives in
data_spec_model.py (pure text-in/text-out). Four verbs:

  new     scaffold `specs/NNNN-name.md` from templates/phases/build/data-spec.md, point its `serves:` at
          the parent, fill `## Context` from the parent (its acceptance checks and every BR / DL / ADR /
          DOC id it cites, each resolved to the file that defines it), and write the parent's half of the
          link: its `depends_on` gains the new id (so sprint_model.build_order builds the data spec
          first) and its `data_review` moves to `pending`
  target  the same link for a spec that ALREADY exists: mark it `type: data` + `serves:`, append a
          `## Context` if it has none, write the parent's half. Idempotent — a second identical run
          writes nothing and reports every `changed` flag false
  status  read-only: every data spec (or the one named) and where it stands against its parent
  check   advisory: does the Context mention what the parent cites, does every gap in
          data-readiness.md have a decision-log owner, is the hand-off written

Standalone or Workflow (CLAUDE.md design rule):
  - Workflow:   --state .sdlc/state.yaml   (repo root = the directory above .sdlc/; the one place a
                                            ledger line is written, `.sdlc/metrics/spec-log.jsonl`)
  - Standalone: --repo <path>              (any repo; no .sdlc/ needed — no ledger, the data documents
                                            are read from <repo>/.sdlc/artifacts/02-design/data/ when
                                            that exists, else from the repo root itself)

Exit codes: `status` and `check` always exit 0 (a usage error, including an unusable --state, is 2).
`new` / `target`: 0 ok; 1 illegal (a missing or ambiguous spec, malformed frontmatter, a missing
template, a ledger append that failed after the files were written — DRIFT); 2 refused (a spec serving
itself, a data spec as the parent, a dependency cycle, a different `serves` already set, a usage error).
A refusal writes NOTHING. `--json` prints exactly one document on stdout; errors and refusals go to
stderr whatever the flag.

Honest by design: "no data" is `{"has_data": false, "specs": []}`, never a zero; a document that is not
there is "not measured" (`passed: null`), never a pass; a reference that could not be found says so.
Frontmatter writes are targeted line edits (a trailing `# comment` and CRLF line endings survive).
Git is read only through branch_scan.py, which never fetches — run `git fetch` first if the other
branches matter.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import branch_scan  # noqa: E402
import check_spec as cs  # noqa: E402
import data_spec_model as dm  # noqa: E402
import new_spec  # noqa: E402
import sprint_model as sm  # noqa: E402
import track_decisions as td  # noqa: E402

VERBS = ("new", "target", "status", "check")

DATA_TEMPLATE_PATH = new_spec.PLUGIN_ROOT / "templates" / "phases" / "build" / "data-spec.md"
LEDGER_NAME = "spec-log.jsonl"
SPEC_ID_RE = re.compile(r"^\d{4}$")

_PARENT_KEYS = ("depends_on_before", "depends_on_after", "data_review_before", "data_review_after",
                "data_review_note")
# A model refusal's `.kind` -> exit code (data_spec_model.DataSpecError). Everything else is "illegal" (1).
_REFUSED_KINDS = {"parent_is_data", "self_reference", "cycle", "conflicting_serves", "bad_value", "not_data"}

# `check`: what counts as a placeholder inside a Smoke tests section. A markdown link `[t](u)` is content
# (the hand-off is supposed to link its test output); so are HTML tags, comments and autolinks, and a
# task-list marker (`[ ]`, `[x]`, `[X]`) — a ticked smoke test is the hand-off doing its job.
_BRACKET_PLACEHOLDER_RE = re.compile(r"\[(?![ xX]\])[^\]]*\](?!\()")
_ANGLE_PLACEHOLDER_RE = re.compile(
    r"<(?![/!]|https?://|(?:br|a|code|pre|details|summary|p|b|i|em|strong|ul|ol|li|img|span|div|table|tr|td|th)\b)"
    r"[^\s<>][^<>\n]*>", re.IGNORECASE)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_DL_RE = re.compile(r"\bDL-(\d+)\b", re.IGNORECASE)


class CliError(Exception):
    """A refusal or an error: `code` is the exit code; `plain` messages are printed as written
    (DRIFT lines), the rest get an `Error: ` prefix. Always printed to stderr."""

    def __init__(self, code: int, message: str, plain: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.plain = plain


def model_error(exc: dm.DataSpecError) -> CliError:
    return CliError(2 if exc.kind in _REFUSED_KINDS else 1, exc.message)


@dataclass
class Workspace:
    repo_root: Path
    sdlc_dir: Path        # the state file's directory in --state mode; <repo>/.sdlc otherwise
    state_mode: bool

    @property
    def specs_dir(self) -> Path:
        return self.repo_root / "specs"

    @property
    def ledger_path(self) -> Path:
        return self.sdlc_dir / "metrics" / LEDGER_NAME


def resolve_workspace(args) -> Workspace:
    if args.state:
        state_path = Path(args.state)
        if not state_path.exists():
            raise CliError(2, f"State file not found: {state_path}")
        sdlc_dir = state_path.resolve().parent
        return Workspace(sdlc_dir.parent, sdlc_dir, True)
    repo_root = Path(args.repo).resolve()
    return Workspace(repo_root, repo_root / ".sdlc", False)


# --- File I/O (bytes-faithful: no newline translation) ----------------------------------------

def read_exact(path: Path) -> str:
    """The file's text with every line ending as it is on disk — what a rewrite must start from."""
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            return f.read()
    except UnicodeDecodeError as exc:
        raise CliError(1, f"{path} is not valid UTF-8 ({exc.reason}); it was not changed") from exc
    except OSError as exc:
        raise CliError(1, f"could not read {path}: {exc}") from exc


def read_lenient(path: Path) -> str | None:
    """For read-only verbs: the text, or None when the file cannot be read at all."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            return f.read()
    except OSError:
        return None


def write_exact(path: Path, text: str) -> None:
    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    except OSError as exc:
        raise CliError(1, f"could not write {path}: {exc}") from exc


def append_ledger(ws: Workspace, event: dict, written: int) -> None:
    """One JSON line, `--state` mode only. A failed append after the files were written is DRIFT (exit 1)."""
    path = ws.ledger_path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except OSError as exc:
        raise CliError(
            1,
            f"DRIFT: {written} file(s) were written but the ledger append failed ({path}): {exc}\n"
            "       The specs now disagree with the ledger — re-run the verb once the path is writable.",
            plain=True) from exc


def now_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# --- Reading the specs directory ---------------------------------------------------------------

def index_specs(specs_dir: Path) -> dict[str, list[Path]]:
    """{spec id: [files]} for every `specs/NNNN-*.md`; the installed spec-template.md never matches."""
    out: dict[str, list[Path]] = {}
    if specs_dir.is_dir():
        for path in sorted(specs_dir.iterdir()):
            spec_id = dm.spec_id_from_name(path.name) if path.suffix == ".md" and path.is_file() else None
            if spec_id:
                out.setdefault(spec_id, []).append(path)
    return out


def _names(paths: list[Path], repo_root: Path) -> str:
    shown = [p.relative_to(repo_root).as_posix() for p in paths]
    return " and ".join(shown) if len(shown) <= 2 else ", ".join(shown[:-1]) + " and " + shown[-1]


def locate_spec(index: dict[str, list[Path]], spec_id: str, role: str, ws: Workspace) -> Path:
    paths = index.get(spec_id, [])
    if not paths:
        raise CliError(1, f"no spec {spec_id} found ({role}): expected a file named specs/{spec_id}-<name>.md")
    if len(paths) > 1:
        raise CliError(
            1, f"spec id {spec_id} is ambiguous ({role}): {_names(paths, ws.repo_root)} all match "
               f"specs/{spec_id}-*.md; keep one before linking")
    return paths[0]


def find_one(index: dict[str, list[Path]], spec_id: str | None) -> Path | None:
    """The single file for an id, or None when there is none or more than one (nothing is guessed)."""
    paths = index.get(spec_id or "", [])
    return paths[0] if len(paths) == 1 else None


def build_graph(index: dict[str, list[Path]]) -> dict[str, list[str]]:
    """{spec id: depends_on ids} over EVERY spec in specs/ — the graph a link must not close a cycle in."""
    graph: dict[str, list[str]] = {}
    for spec_id, paths in index.items():
        deps: list[str] = []
        for path in paths:
            text = read_lenient(path)
            if text is None:
                continue
            fm, _ = cs.parse_frontmatter(text)
            for dep in sm.parse_depends_on(fm.get("depends_on")):
                if dep not in deps:
                    deps.append(dep)
        graph[spec_id] = deps
    return graph


def link_cycles(graph: dict[str, list[str]], parent_id: str, data_id: str) -> list[list[str]]:
    """The cycle the link itself closes, as a one-element list (`[]` when it closes none): the path
    `[data_id, ..., parent_id]` of dependencies the data spec already has, which the new edge parent ->
    data turns into a loop. A cycle already elsewhere in the graph neither blocks the link nor hides the
    one it closes (data_spec_model.link_closes_cycle walks from the data spec, not from a DFS back-edge)."""
    path = dm.link_closes_cycle(graph, parent_id, data_id)
    return [path] if path else []


def cycle_message(spec_id: str, parent_id: str, cycle: list[str]) -> str:
    """The refusal's words: the loop written as a chain of `depends_on`, closed on the parent."""
    return (f"linking spec {spec_id} under spec {parent_id} would create a dependency cycle: "
            + " -> ".join([parent_id, *cycle]))


# --- Resolving a cited id to the file that defines it ------------------------------------------

class RefResolver:
    """Finds, for a BR / DL / ADR / DOC id, the first markdown file under RESOLVE_ROOTS (in that order,
    paths sorted) holding a line that DEFINES it. Each file is read at most once per resolver."""

    def __init__(self, repo_root: Path, skip: Path | None = None):
        self.repo_root = repo_root
        self.skip = skip.resolve() if skip is not None else None
        self._paths: list[Path] | None = None
        self._lines: dict[Path, list[str]] = {}

    def _candidates(self) -> list[Path]:
        if self._paths is None:
            seen: set[Path] = set()
            paths: list[Path] = []
            for root in dm.RESOLVE_ROOTS:
                base = self.repo_root / root
                if not base.is_dir():
                    continue
                for path in sorted(base.rglob("*.md")):
                    if path in seen or not path.is_file():
                        continue
                    seen.add(path)
                    if self.skip is not None and path.resolve() == self.skip:
                        continue
                    paths.append(path)
            self._paths = paths
        return self._paths

    def _read_lines(self, path: Path) -> list[str]:
        if path not in self._lines:
            text = read_lenient(path)
            self._lines[path] = text.splitlines() if text is not None else []
        return self._lines[path]

    def resolve(self, ref: str) -> str | None:
        for path in self._candidates():
            if any(dm.is_definition_line(line, ref) for line in self._read_lines(path)):
                return path.relative_to(self.repo_root).as_posix()
        return None


def resolve_ref(repo_root: Path, ref: str, skip: Path | None = None) -> str | None:
    """Repo-relative posix path of the first file defining `ref`, or None. `skip` is the data spec being
    written (its own Context must not resolve a reference to itself)."""
    return RefResolver(Path(repo_root), skip).resolve(ref)


def build_context(ws: Workspace, parent_id: str, parent_path: Path, parent_text: str, skip: Path):
    """(Context body, refs by kind, unresolved ids) for a data spec serving `parent_id`."""
    _, parent_body = cs.parse_frontmatter(parent_text)
    refs = dm.cited_refs(parent_text)
    checks = cs.list_items(cs.extract_section(parent_body, "Acceptance Checks") or "")
    resolver = RefResolver(ws.repo_root, skip)
    resolved = {ref: resolver.resolve(ref) for ids in refs.values() for ref in ids}
    body = dm.render_context(parent_id, new_spec.repo_relative(parent_path, ws.repo_root),
                             checks, refs, resolved, today_iso())
    unresolved = [ref for kind in dm.REF_PATTERNS for ref in refs[kind] if resolved[ref] is None]
    return body, refs, unresolved


def append_context(text: str, body: str) -> str:
    """`text` plus a `## Context` section at the very end, in the document's own line ending."""
    eol = "\r\n" if "\r\n" in text else "\n"
    clean = body.replace("\r\n", "\n").rstrip("\n").replace("\n", eol)
    lead = eol if text.endswith("\n") else eol + eol
    return text + lead + "## Context" + eol + clean + eol


def parent_info(info: dict) -> dict:
    return {key: info[key] for key in _PARENT_KEYS}


def emit(args, doc: dict, text: str) -> None:
    print(json.dumps(doc, indent=2) if args.json else text)


# --- new ---------------------------------------------------------------------------------------

def allocate_id(ws: Workspace, all_branches: bool):
    """(new id, scan or None). With --all-branches the id is the max over this checkout's specs/ AND
    every local ref's specs/, plus one — so no branch the checkout can see already uses it."""
    local = new_spec.next_spec_id(ws.specs_dir)
    if not all_branches:
        return local, None
    is_git, refs_scanned, names_by_ref, unread = branch_scan.scan_dir(ws.repo_root, "specs")
    highest = int(local) - 1
    for names in names_by_ref.values():
        for name in names:
            spec_id = dm.spec_id_from_name(name) if name.endswith(".md") else None
            if spec_id:
                highest = max(highest, int(spec_id))
    return f"{highest + 1:04d}", (is_git, refs_scanned, unread)


def cmd_new(args, ws: Workspace) -> None:
    risk = args.risk.strip().upper()
    if risk not in new_spec.VALID_RISK:
        raise CliError(1, f"--risk must be one of {', '.join(new_spec.VALID_RISK)} (got '{args.risk}')")
    parent_id = args.serves

    index = index_specs(ws.specs_dir)
    parent_path = locate_spec(index, parent_id, "the spec to serve", ws)
    parent_text = read_exact(parent_path)
    parent_fm, _ = cs.parse_frontmatter(parent_text)
    if not parent_fm:
        raise CliError(1, f"spec {parent_id} has no parseable frontmatter block; it was not changed")
    if dm.is_data_spec(parent_fm):
        raise CliError(2, f"spec {parent_id} is itself a data spec; a data spec serves a build spec")

    if not DATA_TEMPLATE_PATH.exists():
        raise CliError(1, f"Data spec template not found: {DATA_TEMPLATE_PATH}")
    slug = new_spec.slugify(args.name)
    if not slug:
        raise CliError(1, "--name produced an empty slug. Use a descriptive name.")

    new_id, scan = allocate_id(ws, args.all_branches)
    out_path = ws.specs_dir / f"{new_id}-{slug}.md"
    if out_path.exists():
        raise CliError(1, f"Spec already exists: {out_path}")

    # Universal newlines on the template (its render regexes anchor on `$`); the result is written as is.
    template = DATA_TEMPLATE_PATH.read_text(encoding="utf-8")
    text = new_spec.render_spec(template, new_id, slug, risk, args.source, args.owner, args.team)
    try:
        text = dm.mark_data(text, parent_id)
        body, refs, unresolved = build_context(ws, parent_id, parent_path, parent_text, out_path)
        text = dm.replace_section_body(text, dm.CONTEXT_HEADING, body)
        new_parent_text, info = dm.link_parent(parent_text, new_id, parent_id)
    except dm.DataSpecError as exc:
        raise model_error(exc) from exc

    cycles = link_cycles(build_graph(index), parent_id, new_id)
    if cycles:
        raise CliError(2, cycle_message(new_id, parent_id, cycles[0]))

    # Every refusal is behind us: only now does anything reach the disk.
    ws.specs_dir.mkdir(parents=True, exist_ok=True)
    write_exact(out_path, text)
    written = 1
    if info["changed"]:
        try:
            write_exact(parent_path, new_parent_text)
        except CliError as exc:
            raise CliError(1, f"{exc.message}; the data spec {out_path.name} was written, so finish the link "
                              f"with: data_spec.py target --spec {new_id} --serves {parent_id}") from exc
        written = 2
    if ws.state_mode:
        append_ledger(ws, dm.ledger_event(new_id, parent_id, now_ts()), written)

    doc = {
        "path": new_spec.repo_relative(out_path, ws.repo_root),
        "id": new_id,
        "name": slug,
        "risk": risk,
        "serves": parent_id,
        "parent_path": new_spec.repo_relative(parent_path, ws.repo_root),
        "parent": parent_info(info),
        "context_refs": refs,
        "unresolved_refs": unresolved,
    }
    lines = [
        f"Spec created: {out_path}",
        f"  Risk tier: {risk}",
        f"  Serves: spec {parent_id} (parent depends_on: {info['depends_on_after']}; "
        f"data_review: {info['data_review_after']})",
    ]
    if scan is not None:
        is_git, refs_scanned, unread = scan
        doc["refs_scanned"] = refs_scanned
        doc["unread"] = unread
        lines.append(f"  Ids checked on {len(refs_scanned)} branch(es)"
                     + ("" if is_git else " (not a git repository)"))
        if unread and not args.json:
            print("Warning: could not read specs/ on " + ", ".join(
                f"{u['ref']} ({u['reason']})" for u in unread), file=sys.stderr)
    if info["data_review_note"] and not args.json:
        print(f"Note: {info['data_review_note']}", file=sys.stderr)
    lines += ["  Next: fill the body (Goal, Why, Scope, Acceptance Checks, plans), then validate:",
              f"    uv run scripts/check_spec.py --spec {out_path}"]
    emit(args, doc, "\n".join(lines))


# --- target ------------------------------------------------------------------------------------

def cmd_target(args, ws: Workspace) -> None:
    spec_id, parent_id = args.spec, args.serves
    if spec_id == parent_id:
        raise CliError(2, f"spec {spec_id} cannot serve itself")

    index = index_specs(ws.specs_dir)
    spec_path = locate_spec(index, spec_id, "the spec to mark as a data spec", ws)
    parent_path = locate_spec(index, parent_id, "the spec to serve", ws)
    spec_text = read_exact(spec_path)
    parent_text = read_exact(parent_path)
    fm_before, _ = cs.parse_frontmatter(spec_text)
    if not fm_before:
        raise CliError(1, f"spec {spec_id} has no parseable frontmatter block; it was not changed")

    try:
        text = dm.mark_data(spec_text, parent_id)
        body, refs, unresolved = build_context(ws, parent_id, parent_path, parent_text, spec_path)
        context_added = not dm.has_section(text, dm.CONTEXT_HEADING)
        if context_added:
            text = append_context(text, body)
        new_parent_text, info = dm.link_parent(parent_text, spec_id, parent_id)
    except dm.DataSpecError as exc:
        raise model_error(exc) from exc

    cycles = link_cycles(build_graph(index), parent_id, spec_id)
    if cycles:
        raise CliError(2, cycle_message(spec_id, parent_id, cycles[0]))

    changed = {
        "type": str(fm_before.get("type") or "").strip() != dm.DATA_TYPE,
        "serves": str(fm_before.get(dm.SERVES_KEY) or "").strip() != parent_id,
        "context_added": context_added,
    }
    written = 0
    if text != spec_text:
        write_exact(spec_path, text)
        written += 1
    if info["changed"]:
        try:
            write_exact(parent_path, new_parent_text)
        except CliError as exc:
            raise CliError(1, f"{exc.message}; run the verb again to finish the link") from exc
        written += 1
    if written and ws.state_mode:
        append_ledger(ws, dm.ledger_event(spec_id, parent_id, now_ts()), written)

    doc = {
        "path": new_spec.repo_relative(spec_path, ws.repo_root),
        "id": spec_id,
        "serves": parent_id,
        "changed": changed,
        "parent": parent_info(info),
        "context_refs": refs,
        "unresolved_refs": unresolved,
    }
    if info["data_review_note"] and not args.json:
        print(f"Note: {info['data_review_note']}", file=sys.stderr)
    done = [name for name, flag in (("type", changed["type"]), ("serves", changed["serves"]),
                                    ("Context", changed["context_added"])) if flag]
    headline = f"Spec updated: {spec_path}" if written else f"Spec unchanged: {spec_path}"
    lines = [
        headline,
        f"  Serves: spec {parent_id} (parent depends_on: {info['depends_on_after']}; "
        f"data_review: {info['data_review_after']})",
        "  Changed: " + (", ".join(done) if done else "nothing in this spec")
        + ("; the parent's link was written" if info["changed"] else ""),
    ]
    emit(args, doc, "\n".join(lines))


# --- status ------------------------------------------------------------------------------------

def status_line(row: dict) -> str:
    head = f"{row['id']} serves {row['serves'] or '(none)'} — status {row['status'] or 'unset'}"
    if not row["parent_found"]:
        return f"{head}; parent not found; acceptance due: unknown"
    in_parent = "yes" if row["parent_depends_on_has_me"] else "no"
    review = row["parent_data_review"] or "not set"
    due = "yes" if row["acceptance_due"] else "no"
    return f"{head}; in parent depends_on: {in_parent}; parent data_review: {review}; acceptance due: {due}"


def cmd_status(args, ws: Workspace) -> None:
    index = index_specs(ws.specs_dir)
    rows: list[dict] = []
    seen_non_data = False
    for spec_id in sorted(index):
        if args.spec and spec_id != args.spec:
            continue
        for path in index[spec_id]:
            text = read_lenient(path)
            if text is None:
                continue
            fm, _ = cs.parse_frontmatter(text)
            if not dm.is_data_spec(fm):
                seen_non_data = True
                continue
            serves = str(fm.get(dm.SERVES_KEY) or "").strip()
            parent_path = find_one(index, serves) if SPEC_ID_RE.match(serves) else None
            parent_text = read_lenient(parent_path) if parent_path else None
            parent_fm = cs.parse_frontmatter(parent_text)[0] if parent_text is not None else None
            rows.append(dm.status_row({**fm, "spec": spec_id}, str(fm.get("status") or "").strip(), parent_fm))

    doc = {"has_data": bool(rows), "specs": rows}
    if rows:
        emit(args, doc, "\n".join(status_line(r) for r in rows))
        return
    if args.spec and args.spec not in index:
        message = f"No spec {args.spec} in specs/."
    elif args.spec and seen_non_data:
        message = f"Spec {args.spec} is not a data spec."
    else:
        message = "No data specs."
    if args.json:
        print(json.dumps(doc, indent=2))
        if message != "No data specs.":
            print(message, file=sys.stderr)
    else:
        print(message)


# --- check -------------------------------------------------------------------------------------

def _finding(name: str, passed, detail: str) -> dict:
    return {"name": name, "passed": passed, "detail": detail}


def data_docs_dir(ws: Workspace) -> Path:
    if ws.state_mode:
        return ws.sdlc_dir / "artifacts" / "02-design" / "data"
    workflow = ws.repo_root / ".sdlc" / "artifacts" / "02-design" / "data"
    return workflow if workflow.is_dir() else ws.repo_root


def _read_doc(path: Path) -> tuple[str | None, str | None]:
    """(text, None) | (None, None) when absent | (None, reason) when present but unreadable."""
    if not path.exists():
        return None, None
    text = read_lenient(path)
    return (text, None) if text is not None else (None, f"{path.name} could not be read")


def check_context_coverage(index, spec_text: str) -> dict:
    name = "context-coverage"
    fm, _ = cs.parse_frontmatter(spec_text)
    serves = str(fm.get(dm.SERVES_KEY) or "").strip()
    if not SPEC_ID_RE.match(serves):
        return _finding(name, None, "parent not found — this spec's `serves:` names no spec")
    paths = index.get(serves, [])
    if not paths:
        return _finding(name, None, f"parent not found — no spec {serves} in specs/")
    if len(paths) > 1:
        return _finding(name, None, f"parent not found — spec id {serves} matches {len(paths)} files")
    parent_text = read_lenient(paths[0])
    if parent_text is None:
        return _finding(name, None, f"parent not found — {paths[0].name} could not be read")
    missing = dm.context_coverage(spec_text, parent_text)
    if missing:
        return _finding(name, False, "Context does not mention: " + ", ".join(missing))
    cited = sum(len(ids) for ids in dm.cited_refs(parent_text).values())
    if not cited:
        return _finding(name, True, f"the parent (spec {serves}) cites no BR / DL / ADR / DOC id")
    return _finding(name, True, f"Context mentions all {cited} id(s) the parent (spec {serves}) cites")


def check_readiness_gaps_owned(ws: Workspace) -> dict:
    name = "readiness-gaps-owned"
    text, problem = _read_doc(data_docs_dir(ws) / "data-readiness.md")
    if text is None:
        return _finding(name, None, f"not measured — {problem or 'data-readiness.md not present'}")
    section = cs.extract_section(_HTML_COMMENT_RE.sub("", text), "Gaps")
    if section is None:
        return _finding(name, False, "no ## Gaps section — 0 gaps reference a DL-NN")
    gap_rows = dm.real_table_rows(section)
    shown: dict[int, str] = {}
    for match in _DL_RE.finditer(section):
        shown.setdefault(int(match.group(1)), f"DL-{match.group(1)}")
    if not shown:
        if not gap_rows:   # a Gaps table with only its header or template stand-ins records no gap: nothing to own
            return _finding(name, True, "no gaps recorded")
        return _finding(name, False, f"{len(gap_rows)} gap(s), 0 reference a DL-NN")

    log_path = next((p for p in (ws.sdlc_dir / "decision-log.md", ws.repo_root / "decision-log.md")
                     if p.exists()), None)
    if log_path is None:
        return _finding(name, False, "no decision log found; cannot confirm an owner for "
                        + ", ".join(shown[k] for k in sorted(shown)))
    try:
        decisions = td.parse_decisions(log_path)
    except OSError as exc:
        return _finding(name, None, f"not measured — the decision log could not be read ({exc})")
    owners: dict[int, bool] = {}
    for row in decisions:
        m = re.fullmatch(r"DL-(\d+)", (row.get("id") or "").strip(), re.IGNORECASE)
        if m:
            owned = bool(td.PLACEHOLDER_SPAN_RE.sub("", row.get("owner") or "").strip())
            owners[int(m.group(1))] = owners.get(int(m.group(1)), False) or owned
    problems = []
    for key in sorted(shown):
        if key not in owners:
            problems.append(f"{shown[key]} (not in the decision log)")
        elif not owners[key]:
            problems.append(f"{shown[key]} (no owner)")
    if problems:
        return _finding(name, False, "not owned in the decision log: " + ", ".join(problems))
    return _finding(name, True, f"{len(shown)} gap(s) reference " + ", ".join(shown[k] for k in sorted(shown))
                    + "; each has an owner in the decision log")


def check_handoff_present(ws: Workspace) -> dict:
    name = "handoff-present"
    text, problem = _read_doc(data_docs_dir(ws) / "data-handoff.md")
    if text is None:
        return _finding(name, None, f"not measured — {problem or 'data-handoff.md not present'}")
    section = cs.extract_section(text, "Smoke tests")
    if section is None:
        return _finding(name, False, "data-handoff.md has no ## Smoke tests section")
    content = _HTML_COMMENT_RE.sub("", section)
    if not content.strip():
        return _finding(name, False, "the ## Smoke tests section is empty")
    placeholders = _BRACKET_PLACEHOLDER_RE.findall(content) + _ANGLE_PLACEHOLDER_RE.findall(content)
    if placeholders:
        return _finding(name, False, f"the ## Smoke tests section still holds {len(placeholders)} placeholder(s), "
                                     f"e.g. {placeholders[0]}")
    return _finding(name, True, "data-handoff.md is present and its Smoke tests section has no placeholder")


def cmd_check(args, ws: Workspace) -> None:
    index = index_specs(ws.specs_dir)
    paths = index.get(args.spec, [])
    if len(paths) != 1:
        detail = (f"no spec {args.spec} in specs/" if not paths else
                  f"spec id {args.spec} is ambiguous: {_names(paths, ws.repo_root)}")
        findings = [_finding("spec-found", False, detail)]
    else:
        text = read_lenient(paths[0])
        if text is None:
            findings = [_finding("spec-found", False, f"{paths[0].name} could not be read")]
        else:
            findings = [check_context_coverage(index, text), check_readiness_gaps_owned(ws),
                        check_handoff_present(ws)]
    labels = {True: "PASS", False: "FAIL", None: "n/a "}
    text_out = "\n".join(f"{labels[f['passed']]} {f['name']}: {f['detail']}" for f in findings)
    emit(args, {"spec": args.spec, "findings": findings}, text_out)


# --- CLI ---------------------------------------------------------------------------------------

def _spec_id(value: str) -> str:
    if not SPEC_ID_RE.match(value):
        raise argparse.ArgumentTypeError(f"{value!r} is not a spec id (expected four digits, e.g. 0007)")
    return value


def build_parser() -> argparse.ArgumentParser:
    # SUPPRESS defaults: a value given before the verb must survive the verb's own parser.
    common = argparse.ArgumentParser(add_help=False)
    src = common.add_mutually_exclusive_group()
    src.add_argument("--state", default=argparse.SUPPRESS, help="Path to .sdlc/state.yaml (workflow mode)")
    src.add_argument("--repo", default=argparse.SUPPRESS, help="Target repo root (standalone mode; default: cwd)")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="Print exactly one JSON document on stdout; errors go to stderr")

    parser = argparse.ArgumentParser(
        description="Create, link, report on and check data specs (type: data, serves: <build spec>)",
        parents=[common])
    verbs = parser.add_subparsers(dest="verb", metavar="{" + ",".join(VERBS) + "}", required=True)

    new = verbs.add_parser("new", parents=[common],
                           help="Scaffold a data spec for a build spec and write both halves of the link")
    new.add_argument("--serves", required=True, type=_spec_id, help="Id of the build spec this data spec serves")
    new.add_argument("--name", required=True, help="Short descriptive name (becomes the kebab-case slug)")
    new.add_argument("--risk", default="MEDIUM", help="Risk tier: HIGH | MEDIUM | LOW (default: MEDIUM)")
    new.add_argument("--source", default="—", help="Originating story / REQ-id (default: an em dash)")
    new.add_argument("--owner", default="", help="Code-host handle of the accountable owner (e.g. @sam-k)")
    new.add_argument("--team", default="", help="Team this spec belongs to")
    new.add_argument("--all-branches", action="store_true",
                     help="Also read specs/ on every local branch and remote-tracking ref (run `git fetch` "
                          "first) so the new id is unused on all of them")

    target = verbs.add_parser("target", parents=[common],
                              help="Make an existing spec a data spec serving a build spec (idempotent)")
    target.add_argument("--spec", required=True, type=_spec_id, help="Id of the spec to mark as a data spec")
    target.add_argument("--serves", required=True, type=_spec_id, help="Id of the build spec it serves")

    status = verbs.add_parser("status", parents=[common],
                              help="Every data spec and where it stands against its parent (read-only)")
    status.add_argument("--spec", type=_spec_id, help="Only this spec")

    check = verbs.add_parser("check", parents=[common],
                             help="Advisory: context coverage, readiness-gap owners, hand-off written")
    check.add_argument("--spec", required=True, type=_spec_id, help="Id of the data spec to check")
    return parser


HANDLERS = {"new": cmd_new, "target": cmd_target, "status": cmd_status, "check": cmd_check}


def main(argv=None) -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # the output carries em dashes; the Windows default is cp1252
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    args.state = getattr(args, "state", None)
    args.json = getattr(args, "json", False)
    if args.state and hasattr(args, "repo"):
        parser.error("argument --repo: not allowed with argument --state")
    args.repo = getattr(args, "repo", ".")
    try:
        HANDLERS[args.verb](args, resolve_workspace(args))
    except CliError as exc:
        print(exc.message if exc.plain else f"Error: {exc.message}", file=sys.stderr)
        sys.exit(exc.code)
    sys.exit(0)


if __name__ == "__main__":
    main()
