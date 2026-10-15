"""data_spec_model.py — Single source of truth for what a *data spec* is, and the pure text-in/text-out
operations the data_spec.py CLI performs on spec files. NO I/O, no subprocess, no argparse, no git.

A data spec is a spec the Data discipline owns, worked through /sprd-data and linked to the build
spec it serves (spec 0039, build kit docs/proposals/data-specs-build-kit.md). The vocabulary:

  - Marker      `type: data` (the existing `type:` field) plus `serves: "<parent id>"` (D1). There is
                no `kind:` — that word already means three other things in this plugin.
  - Link        the PARENT's `depends_on` gains the data spec's id and the data spec's `serves:` points
                back, both written by one call (D3) — so sprint_model.build_order already builds the
                data spec first, with no new ordering logic.
  - Data lane   the parent's `data_review` goes to `pending` only from "", "n-a" or "returned"; an
                `accepted` verdict is a named human's and is KEPT, with a note (D4). Acceptance is
                never written here — it stays `sprint.py verdict --lane data --verdict accepted --by`.
  - Context     one `## Context` section holding the bundle /sprd-data loads first: the parent, a
                read-only copy of its acceptance checks, and every BR / DL / ADR / DOC id it cites.

Honest by design: an id that could not be found is printed as "not found in this repository", never
guessed; a refusal is a DataSpecError carrying a `kind` the CLI maps to an exit code.

Frontmatter writes are targeted line edits — never a parse-and-regenerate — so a trailing `# comment`
and the file's CRLF line endings survive. `depends_on` / `data_review` go through
sprint_model.set_frontmatter (the layer that owns those keys); `type` / `serves` go through
set_scalar_line below, which behaves the same way.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_spec as cs  # noqa: E402
import sprint_model as sm  # noqa: E402
from check_dependencies import detect_cycles  # noqa: E402
from new_spec import SPEC_FILE_RE  # noqa: E402

DATA_TYPE = "data"
SERVES_KEY = "serves"
CONTEXT_HEADING = "Context"
DELIVERABLES_HEADING = "Deliverables"
LINKED_EVENT = "data_spec_linked"

# The id families a parent spec can cite. Widths match what each family's own document allocates:
# BR-NN and DL-NN are two digits or more, ADR-NNN three or more, DOC-NNN exactly three.
REF_PATTERNS = {
    "BR": r"\bBR-\d{2,}\b",
    "DL": r"\bDL-\d{2,}\b",
    "ADR": r"\bADR-\d{3,}\b",
    "DOC": r"\bDOC-\d{3}\b",
}
REF_LABELS = {
    "BR": "Business rules",
    "DL": "Decisions",
    "ADR": "Decision records",
    "DOC": "Intake documents",
}
# The CLI (another package) searches these, in this order, *.md only, to resolve a cited id to a
# file. The model only declares them: it reads no file.
RESOLVE_ROOTS = (".sdlc/artifacts", ".sdlc", "docs", "specs")

# D4: the only `data_review` values this layer moves to `pending`. `accepted` is a person's verdict.
REVIEW_TO_PENDING = ("", "n-a", "returned")

ERROR_KINDS = (
    "missing_parent", "parent_is_data", "self_reference", "cycle",
    "malformed", "bad_value", "conflicting_serves", "not_data",
)

ACCEPTED_NOTE = (
    "data_review was accepted by a named human and was kept; "
    "re-verdict with `sprint.py verdict --lane data` if this data work changes that"
)

_ID_RE = re.compile(r"^\d{4,}$")
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


class DataSpecError(Exception):
    """A refusal. `.kind` is one of ERROR_KINDS; the CLI maps a kind to an exit code (missing_parent,
    malformed -> 1; self_reference, parent_is_data, cycle, conflicting_serves, bad_value, not_data -> 2)."""

    def __init__(self, kind: str, message: str = ""):
        self.kind = kind
        self.message = message or kind
        super().__init__(self.message)


# --- Small readers -----------------------------------------------------------------------------

def spec_id_from_name(filename: str) -> str | None:
    """'0007-duplicate-claim-409.md' -> '0007'; anything that does not start `NNNN-` -> None."""
    m = SPEC_FILE_RE.match(filename or "")
    return m.group(1) if m else None


def is_data_spec(fm: dict) -> bool:
    """True when the frontmatter says `type: data` (case-insensitive). Reads `type` only — never `kind`."""
    return str(fm.get("type") or "").strip().lower() == DATA_TYPE


def _require_id(value: str, role: str) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise DataSpecError("bad_value", f"{role} {value!r} is not a spec id (expected digits, e.g. 0007)")
    return value


# --- Frontmatter writer ------------------------------------------------------------------------

def _check_scalar_value(value) -> str:
    """The exact string a caller may hand set_scalar_line. ValueError otherwise.

    Refuses newline, carriage return and '#' (parse_frontmatter would truncate at it) anywhere, and a
    quote character anywhere EXCEPT as one matching pair wrapping the whole value ('"0007"'): the caller
    decides quoting, so a quoted value is allowed, but a stray quote (a'b, "a"b") would be silently
    stripped by the reader and is refused.
    """
    if not isinstance(value, str):
        raise ValueError(f"frontmatter value {value!r} must be a string")
    inner = value
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
    names = {"\n": "newline", "\r": "carriage return", "#": "'#'", '"': "double quote", "'": "single quote"}
    for ch, name in names.items():
        if ch in inner:
            raise ValueError(
                f"frontmatter value {value!r} contains a {name}; only a bare word or one fully-quoted word is allowed"
            )
    return value


def _comment_of(line: str) -> str:
    """The trailing `# comment` of a frontmatter line ('' if none). A '#' opens a comment only when
    outside quotes and preceded by whitespace — the YAML rule check_spec._strip_comment applies."""
    quote = ""
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and i > 0 and line[i - 1] in " \t":
            return line[i:].rstrip("\r")
    return ""


def _value_of(line: str) -> str:
    """The raw value text of a `key: value  # comment` line (comment and CR stripped)."""
    after = line.partition(":")[2].rstrip("\r")
    comment = _comment_of(line)
    if comment:
        after = after[: after.rindex(comment)]
    return after.strip()


def _after_entry(lines: list[str], idx: int) -> int:
    """Index just past the entry at `idx`: the line itself plus any comment-only continuation lines
    directly under it (spec.md's `type:` carries a two-line comment that must stay with it)."""
    j = idx + 1
    while j < len(lines) and re.match(r"^[ \t]+#", lines[j]):
        j += 1
    return j


def set_scalar_line(text: str, key: str, value: str) -> str:
    """Return `text` with `key: <value>` set in the frontmatter block; every other byte identical.

    `value` is written VERBATIM after `key: ` — the caller decides quoting (see _check_scalar_value).
    Replaces an existing `key:` line keeping its trailing `  # comment`; a line that already holds
    exactly this value is left untouched (so re-marking a data spec does not re-space its comment).
    When the key is absent it is inserted after the `type:` line, else after `status:`, else right
    after the opening `---` — after any comment-only lines that continue that entry. A CRLF block stays
    CRLF. ValueError: a refused value, a bad key, or no frontmatter block.
    """
    _check_scalar_value(value)
    if not isinstance(key, str) or not _KEY_RE.match(key):
        raise ValueError(f"frontmatter key {key!r} is not a plain key name")
    if not text.startswith("---"):
        raise ValueError("no frontmatter block (text does not start with ---)")
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError("no frontmatter block (opening --- never closed)")

    head, tail = text[:end], text[end:]
    lines = head.split("\n")  # lines[0] == "---" (possibly with a trailing \r)
    cr = "\r" if lines[0].endswith("\r") else ""
    new_core = f"{key}: {value}"
    key_re = re.compile(rf"^{re.escape(key)}\s*:")

    for i, line in enumerate(lines[1:], start=1):
        if key_re.match(line):
            if _value_of(line) == value.strip():
                return text
            comment = _comment_of(line)
            lines[i] = new_core + (f"  {comment}" if comment else "") + ("\r" if line.endswith("\r") else "")
            return "\n".join(lines) + tail

    insert_at = 1
    for anchor in (re.compile(r"^type\s*:"), re.compile(r"^status\s*:")):
        found = next((i for i, ln in enumerate(lines[1:], start=1) if anchor.match(ln)), None)
        if found is not None:
            insert_at = _after_entry(lines, found)
            break
    lines.insert(insert_at, new_core + cr)
    return "\n".join(lines) + tail


def _set_sprint_key(text: str, key: str, value: str) -> str:
    """sprint_model.set_frontmatter, plus the one thing it does not do: it rewrites the line it edits
    without its '\\r', which would leave a bare LF inside a CRLF block. Restore it."""
    out = sm.set_frontmatter(text, key, value)
    if not text.startswith("---\r\n"):
        return out
    end = out.find("\n---", 3)
    head, tail = out[:end], out[end:]
    head = "\n".join(ln if ln.endswith("\r") else ln + "\r" for ln in head.split("\n"))
    return head + tail


def mark_data(text: str, parent_id: str) -> str:
    """Make `text` a data spec serving `parent_id`: `type: data` (bare) and `serves: "<parent_id>"`.

    Idempotent (a second call returns identical text). DataSpecError: `conflicting_serves` when
    `serves` already names a DIFFERENT spec (an unfilled placeholder like "NNNN" is not a spec),
    `malformed` with no frontmatter, `bad_value` for an id that is not a spec id.
    """
    _require_id(parent_id, "parent id")
    fm, _ = cs.parse_frontmatter(text)
    if not fm:
        raise DataSpecError("malformed", "no parseable frontmatter block")
    existing = str(fm.get(SERVES_KEY) or "").strip()
    if existing and existing != parent_id and not cs.PLACEHOLDER_RE.search(existing):
        raise DataSpecError(
            "conflicting_serves",
            f"this spec already serves spec {existing}; it is not re-pointed at {parent_id} without a person doing it",
        )
    out = set_scalar_line(text, "type", DATA_TYPE)
    return set_scalar_line(out, SERVES_KEY, f'"{parent_id}"')


# --- The Context bundle ------------------------------------------------------------------------

def cited_refs(parent_text: str) -> dict[str, list[str]]:
    """Every BR / DL / ADR / DOC id the parent's BODY cites (frontmatter excluded), sorted and unique
    per kind. All four kinds are always present, possibly as []."""
    _, body = cs.parse_frontmatter(parent_text)
    return {kind: sorted(set(re.findall(pattern, body))) for kind, pattern in REF_PATTERNS.items()}


def is_definition_line(line: str, ref: str) -> bool:
    """True when `line` is where `ref` is *defined* rather than merely cited: a markdown heading that
    names it, or a table row whose first cell is it."""
    r = re.escape(ref)
    return bool(re.search(rf"^#{{1,6}} .*\b{r}\b", line) or re.search(rf"^\|\s*{r}\s*\|", line))


def render_context(parent_id: str, parent_rel_path: str, parent_checks: list[str],
                   refs: dict[str, list[str]], resolved: dict[str, str | None], today: str) -> str:
    """The body of a data spec's `## Context` section. No trailing newline — the caller adds it.

    `resolved` maps a ref to the repo-relative path it was found at, or None when it was not found
    (printed as "not found in this repository" — a path is never guessed). A kind with no refs, and an
    empty check list, print `- none`.
    """
    blocks = [f"**Serves:** spec {parent_id} — `{parent_rel_path}`"]

    check_lines = [f"- [ ] {c}" for c in parent_checks] or ["- none"]
    blocks.append("\n".join([f"**Parent acceptance checks (read-only copy, taken {today}):**", *check_lines]))

    for kind in REF_PATTERNS:
        entries = []
        for ref in refs.get(kind) or []:
            path = resolved.get(ref)
            entries.append(f"- {ref} — `{path}`" if path else f"- {ref} — not found in this repository")
        blocks.append("\n".join([f"**{REF_LABELS[kind]}:**", *(entries or ["- none"])]))

    return "\n\n".join(blocks)


def _heading_re(heading: str) -> re.Pattern:
    # `[ \t]*` and an optional \r, not `\s*`: \s would swallow the line break (and blank lines after it).
    return re.compile(rf"^##[ \t]+{re.escape(heading)}[ \t]*(?=\r?$)", re.IGNORECASE | re.MULTILINE)


def has_section(text: str, heading: str) -> bool:
    """True when a `## <heading>` line exists (case-insensitive)."""
    return _heading_re(heading).search(text) is not None


def replace_section_body(text: str, heading: str, body: str) -> str:
    """Replace the body of `## <heading>` with `body`; every byte outside the section is identical.

    The span runs from the end of the heading line to the start of the next `## ` line (or EOF) and is
    rewritten as: line break + body + blank line when a section follows, line break + body at EOF.
    The document's own line ending (LF or CRLF) is used. DataSpecError(malformed) when the heading is absent.
    """
    m = _heading_re(heading).search(text)
    if not m:
        raise DataSpecError("malformed", f"no `## {heading}` section to fill")
    nxt = re.compile(r"^##[ \t]", re.MULTILINE).search(text, m.end())
    stop = nxt.start() if nxt else len(text)

    rest = text[m.end():]
    if rest.startswith("\r\n"):
        eol = "\r\n"
    elif rest.startswith("\n"):
        eol = "\n"
    else:  # heading on the last line with no break after it: follow the rest of the document
        eol = "\r\n" if "\r\n" in text else "\n"

    clean = body.replace("\r\n", "\n").rstrip("\n").replace("\n", eol)
    new_span = eol + clean + eol + (eol if nxt else "")
    return text[: m.end()] + new_span + text[stop:]


def context_coverage(data_text: str, parent_text: str) -> list[str]:
    """Every id the parent cites that the data spec's `## Context` section does not mention, sorted.
    A section that is absent mentions nothing, so every cited id is reported. HTML comments (the
    template's guidance) do not count as mentions."""
    _, body = cs.parse_frontmatter(data_text)
    section = cs.extract_section(body, CONTEXT_HEADING) or ""
    section = _HTML_COMMENT_RE.sub("", section)
    missing = []
    for ids in cited_refs(parent_text).values():
        for ref in ids:
            if not re.search(rf"\b{re.escape(ref)}\b", section):
                missing.append(ref)
    return sorted(missing)


# --- The link ----------------------------------------------------------------------------------

def link_parent(parent_text: str, data_id: str, parent_id: str) -> tuple[str, dict]:
    """Write the parent's half of the link (D3/D4): `depends_on` gains `data_id`, `data_review`
    moves to `pending` only from ""/"n-a"/"returned" (an `accepted` verdict is kept, with a note).

    Returns (new_text, info) with info keys depends_on_before, depends_on_after, data_review_before,
    data_review_after, data_review_note (str | None), changed. When both values already hold the
    targets, nothing is written, `changed` is False and new_text is parent_text exactly.
    Refuses: self_reference, parent_is_data, malformed (no frontmatter), bad_value (not a spec id).
    """
    _require_id(data_id, "data spec id")
    _require_id(parent_id, "parent id")
    if data_id == parent_id:
        raise DataSpecError("self_reference", f"spec {data_id} cannot serve itself")
    fm, _ = cs.parse_frontmatter(parent_text)
    if not fm:
        raise DataSpecError("malformed", f"parent spec {parent_id} has no parseable frontmatter block")
    if is_data_spec(fm):
        raise DataSpecError("parent_is_data", f"spec {parent_id} is itself a data spec; a data spec serves a build spec")

    deps_before = str(fm.get("depends_on") or "").strip()
    if "[" in deps_before or "]" in deps_before:
        raise DataSpecError("malformed", f"spec {parent_id}'s depends_on is a YAML list; it must be a comma-separated string")
    deps = sm.parse_depends_on(deps_before)
    needs_dep = data_id not in deps
    deps_after = ",".join(deps + [data_id]) if needs_dep else deps_before

    review_before = str(fm.get("data_review") or "").strip()
    review_key = review_before.lower()
    note = None
    if review_key in REVIEW_TO_PENDING:
        review_after = "pending"
    elif review_key == "pending":
        review_after = review_before
    elif review_key == "accepted":
        review_after = review_before
        note = ACCEPTED_NOTE
    else:
        review_after = review_before
        note = (f"data_review is {review_before!r}, which this tool does not change; it was kept "
                f"(only '', 'n-a' and 'returned' move to 'pending')")
    needs_review = review_after != review_before

    out = parent_text
    try:
        if needs_dep:
            out = _set_sprint_key(out, "depends_on", deps_after)
        if needs_review:
            out = _set_sprint_key(out, "data_review", review_after)
    except ValueError as exc:  # sprint_model refused a value (a placeholder token already in depends_on, ...)
        raise DataSpecError("bad_value", str(exc)) from exc

    return out, {
        "depends_on_before": deps_before,
        "depends_on_after": deps_after,
        "data_review_before": review_before,
        "data_review_after": review_after,
        "data_review_note": note,
        "changed": out != parent_text,
    }


def cycle_after_link(graph: dict[str, list[str]], parent_id: str, data_id: str) -> list[list[str]]:
    """The dependency cycles the link would create. `graph` maps every spec id to its parse_depends_on
    list; it is copied, never changed. The parent gains an edge to the data spec (the parent depends
    on it); `[]` means the link is safe."""
    g = {node: list(deps) for node, deps in graph.items()}
    g.setdefault(parent_id, [])
    g.setdefault(data_id, [])
    if data_id not in g[parent_id]:
        g[parent_id].append(data_id)
    return detect_cycles(g)


def ledger_event(data_id: str, parent_id: str, ts: str) -> dict:
    """The one `.sdlc/metrics/spec-log.jsonl` line a link writes: four keys, no names."""
    return {"ts": ts, "event": LINKED_EVENT, "spec": data_id, "serves": parent_id}


def status_row(data_fm: dict, data_status: str, parent_fm: dict | None) -> dict:
    """One data spec's row for `data_spec.py status`: where it is and what its parent shows.

    `parent_fm` is None when the parent file could not be found: the parent-derived values are then
    None and `acceptance_due` is False — nothing is claimed about a parent that was not read.
    `acceptance_due` is True once the data spec has merged and the parent's data lane is not yet
    `accepted` (a named human records that with `sprint.py verdict --lane data`).
    """
    spec_id = str(data_fm.get("spec") or "").strip()
    row = {
        "id": spec_id,
        "serves": str(data_fm.get(SERVES_KEY) or "").strip(),
        "status": data_status,
        "parent_found": parent_fm is not None,
        "parent_depends_on_has_me": None,
        "parent_data_review": None,
        "acceptance_due": False,
    }
    if parent_fm is not None:
        review = str(parent_fm.get("data_review") or "").strip()
        row["parent_depends_on_has_me"] = spec_id in sm.parse_depends_on(parent_fm.get("depends_on"))
        row["parent_data_review"] = review
        row["acceptance_due"] = data_status == "merged" and review.lower() != "accepted"
    return row
