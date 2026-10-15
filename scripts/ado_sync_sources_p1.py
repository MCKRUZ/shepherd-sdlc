"""The breadth sources for the Boards mirror: NFRs, business rules, discovery questions, the lifecycle item and
measurements (B5-P1).

Fold B5 (spec 0038) opens the rest of the Phase-0, Phase-1 and Build record to the board, each kind opt-in (none is in
the starter `kinds:`). `ado_sync_sources` reads the Build record; this module adds the five kinds of
`ado_sync_model.BREADTH_KINDS` to its extend-only `SOURCES` table, so `plan --kind nfr` and friends plan them through
the same handshake as every other kind:

    nfr          a `NFR-xxx` row of `non-functional-requirements.md`, parented to the Domain whose heading it sits under
    rule         a `BR-NN` row of `business-rules.md`, parented to the Feature whose brief names it
    question     a `Q-NN` entry of `question-list.md`
    lifecycle    one item that mirrors `.sdlc/state.yaml`: the phase, gate and sign-off table in its Description
    measurement  a threshold row of a `success-criteria.md` dimension, parented to that dimension's Outcome

It only reads: it writes no file, spawns nothing, makes no network call and refuses a source that resolves outside
`repo_root`. It is a library part, usable two ways like every part of the plugin:

  * Workflow mode - `ado_sync.py --state .sdlc/state.yaml ...` hands in the repository root, the parsed
    `.sdlc/ado.yaml` and the discovered `.sdlc/ado/schema.json`.
  * Standalone - `load_nfrs(repo_root)` and the others on any folder that has the artifact; `cfg` and `schema` default
    to `{}`. What the missing process would have supplied (a work item type, a state) is left out and named in the
    projection's `notes`.

A projection is the dict `ado_sync_sources` documents (`ref`, `kind`, `id`, `title`, `status`, `fields`, `tags`,
`parent_ref`, `parent_note`, `related_refs`, `source_path`, `source_sha`, plus `notes`). A ref is `sdlc:<kind>:<id
without its family prefix>`: `sdlc:nfr:P01`, `sdlc:rule:01`, `sdlc:question:01`, `sdlc:lifecycle:project`; a
measurement's id has no family prefix, so its ref is the id whole (`sdlc:measurement:1-pass`). The segment is the kind,
so `ado_sync` reads a ledgered ref back to its kind with no table of its own.

  nfr        `NFR ID | Requirement | ...` tables, found by their header (never by position). The title is the
             Requirement cell. The parent is `sdlc:domain:<slug>` of the nearest enclosing heading that is a domain of
             `requirements.md` (`ado_sync_sources_tree.load_domains`); otherwise None with a `no parent` note saying
             why. The `NFR Acceptance Test Plan` repeats NFR ids as references: it defines nothing and is not read.
             A row with no requirement text (or the template's stand-in row) is not an NFR; a row that still holds
             template placeholders is listed with a note naming the columns. `Microsoft.VSTS.Common.Priority` (P0 to
             P3 as 1 to 4) and `Microsoft.VSTS.Common.AcceptanceCriteria` (the row's other filled cells, HTML-escaped,
             one per line) are set only when the resolved type carries them (`ado_schema_map.field_on_type`). A
             column that names an activity metric (Effort, Estimate, Points, Hours) is never pushed, and a note says so.
  rule       the table whose first header is `Rule`, found by its columns: the file has no `## ` heading a shape could
             anchor to. The title is the Condition cell. The parent is the one Feature whose brief names the `BR-NN`;
             two briefs naming it, or none, is no parent and a note, never a guess. An outcome marked `(pending
             DL-NN)` names that decision as its predecessor, in the neutral key `fields["predecessor_refs"]` (the
             design's Predecessor link: not a `Related` edge, so not in `related_refs`). The Approver column is never
             read. The rule's text (its condition, outcome, source and any pending decision, the filled cells only) is
             its Description block, one escaped paragraph each: the field the model's rule row makes C (the design's
             §6.1, `C: text -> .proposed`), so a board edit to it is the board's and comes back only as `.proposed`.
             A rule never sets `Microsoft.VSTS.Common.AcceptanceCriteria`, whatever its type carries: that field is S
             for a rule, so text pushed there would make a person's board edit read as drift `apply` overwrites.
  question   `#### Q-NN: <question>` entries under the Questions section, read through `question-list.shape.yaml`
             (`document_shape.read_document`; a list with no recognised Questions section is read whole, minus its
             Answer Log). A `### Block:` the shape does not declare is read all the same. Answered = an Answer line
             that is not `open` or a template token, or a filled row of the Answer Log; the answer's own text is never
             read into the projection. `fields["block"]`, `["route"]` and (a roster-style `@handle` only)
             `["owner_handle"]` are neutral keys, never an op.
  lifecycle  the one item for `.sdlc/state.yaml`: the title is `<project> · SDLC lifecycle`, its status is `closed`
             when every phase is completed, `in-flight` when any is active or completed, else `open`, and its
             Description is the table of phases in registry order: name, status, gate counts and the sign-off day (and
             the signer only when it is a roster-style handle; a name or an address is never shown). A phase with no
             recorded gate reads "no gate recorded", never a zero count. `fields["description_rows"]` carries the same
             rows as data. A `state.yaml` that is absent is no row; one that is not a mapping is a `ValueError`.
  measurement  one row per threshold row of a dimension's `| Outcome | Threshold | How We'll Measure |` table in
             `success-criteria.md`, read through `ado_sync_sources_tree.load_outcomes` so a measurement and the
             Outcome it hangs under read the same rows (the design's §6.1). The id is `<dimension number>-<slug of the
             Outcome cell>` (`1-pass`); the same Outcome cell twice in one dimension is a `ValueError`. The parent is
             that dimension's Outcome (`sdlc:outcome:<n>-<slug>`, the ref the outcome source makes). The title is the
             row's Outcome cell; the Description block is its threshold and how-measured text (the filled cells only;
             none filled is no block and a note). A row with no Outcome cell is not a measurement; one that still
             holds template placeholders is listed with a note naming the columns. It lands only on the type
             `types.measurement` pins (a Key-Result-style type, validated against the process): there is no default,
             so without one the row has no type, `plan` shows it unmapped (no item), and a note says the threshold
             stays in its Outcome's block. State and any actual-value field are the board's: none is pushed.

Which work item type each kind lands on is chosen here, the way the findings source does, and travels as the neutral
keys `fields["type_name"]` and `["type_route"]` that `ado_sync` reads for a row whose source names one: the kind's own
`types.<kind>` pin when there is one (validated against the process, and never replaced by a default when the process
lacks it); otherwise the design's default - lifecycle on the type epics land on, rule on the type specs land on
(RequirementCategory), nfr on the type requirements land on; a question has no default (`ado_schema_map.CANDIDATES`
lists what to pin), and neither has a measurement (only `types.measurement`). With no type, no type-only field and no
State is set, and a note says why. `states.<kind>` is applied to the chosen type; `fields.<kind>` is not, and a row
says so when the config names one.

Nothing a person is identified by reaches a projection. Text taken from an artifact has any e-mail address or GUID
replaced before it is used, the roster is never read (so no `System.AssignedTo` is set), and an approver, an answerer
or a signer is never copied unless it is already a `@handle`.

Honesty: a thing that is not known is absent or None with a note, never defaulted; an absent artifact is no rows.

On import the module registers its five loaders with `ado_sync_sources` (`SOURCES["nfr"|"rule"|"question"|
"lifecycle"|"measurement"]`), extend-only: it sets its own five keys and touches no other, and registers no parent
resolver. The module is looked up lazily, as `ado_sync_sources_tree` and `ado_sync_sources_df` do, so the three can be
imported in either order. If `ado_sync_sources` does not exist, or has no `SOURCES` table, nothing is registered and `_register()`
may be called again. `ado_sync.py` imports this module.
"""

import hashlib
import html
import importlib
import json
import re
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

import yaml

import boards_contract as bc
import document_shape
import phase_model as pm
from ado_schema_map import field_on_type, resolve_state, resolve_type
from artifact_lineage import ID_RE
from sprint_model import is_forbidden_field
from track_decisions import parse_decisions

__all__ = ["load_nfrs", "load_rules", "load_questions", "load_lifecycle", "load_measurements"]

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
NFR_SHAPE = PLUGIN_ROOT / "templates" / "phases" / "01-requirements" / "non-functional-requirements.shape.yaml"
QUESTION_SHAPE = PLUGIN_ROOT / "templates" / "phases" / "00-discovery" / "question-list.shape.yaml"
STATE_REL = ".sdlc/state.yaml"
MAX_TITLE = 255                                  # the work item title limit
SEP = " · "                                 # `<id> · <title>`
TITLE, STATE, DESCRIPTION = "System.Title", "System.State", "System.Description"
PRIORITY = "Microsoft.VSTS.Common.Priority"
ACCEPTANCE = "Microsoft.VSTS.Common.AcceptanceCriteria"
PRIORITY_VALUE = {"P0": 1, "P1": 2, "P2": 3, "P3": 4}   # the board's 1 (most urgent) to 4
ADDRESS_GONE, ID_GONE = "[address removed]", "[id removed]"
TEST_PLAN = "NFR Acceptance Test Plan"           # the shape's section that repeats NFR ids as references
ROUTES = ("workshop", "pre-workshop", "interview")
OPEN_WORDS = frozenset({"open", "tbd", "unanswered", "pending"})
LIFECYCLE_ID = "project"

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
_GUID = re.compile(bc.GUID_RE.pattern.replace(r"\b", ""))  # as the model reads one: glued to a word still counts
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_PLACEHOLDER = re.compile(r"\[[^\]\n]+\](?!\()|\$\{[^}\n]*\}|<[A-Z]{1,6}-NN>")
_WHOLE_PLACEHOLDER = re.compile(r"^(?:\[[^\]\n]*\]|<[^>\n]*>|\$\{[^}\n]*\})$")
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*$")
_NFR_ID = re.compile(r"^NFR-[A-Z]*\d+$")
_BR_ID = re.compile(r"^BR-\d+$")
_Q_HEAD = re.compile(r"^####[ \t]+(Q-\d+)[ \t]*:[ \t]*(.*?)[ \t]*$")
_BLOCK = re.compile(r"^###[ \t]+Block:[ \t]*(.+?)[ \t]*$")
_LABEL = re.compile(r"^[-*][ \t]+\*\*([^*]+?):\*\*[ \t]*(.*)$")
_PENDING = re.compile(r"\*?\([ \t]*pending[ \t]+<?[ \t]*DL-(\d+)[ \t]*>?[ \t]*\)\*?", re.IGNORECASE)
_PENDING_ANY = re.compile(r"\*?\([ \t]*pending\b[^)]*\)\*?", re.IGNORECASE)
_RULE_ID_HEADERS = frozenset({"rule", "rule id", "br id", "id"})
_NO_TREE = "no parent: requirements.md "

# a question's own word -> the word `ado_schema_map.STATUS_RULES` knows
_RULE_STATUS = {"question": {"open": "open", "answered": "closed"}}
# where a kind with no pin of its own lands: the kind whose type it follows, and how a person reads that choice
_FOLLOWS = {"lifecycle": ("epic", "EpicCategory"), "rule": ("spec", "RequirementCategory"),
            "nfr": ("requirement", "the requirement fit")}


# --- small helpers --------------------------------------------------------------------------------------------

def _one_line(text) -> str:
    """The text on one line: control characters (an escape, a tab, a newline) become a space, runs collapse."""
    return " ".join(_CONTROL.sub(" ", str(text if text is not None else "")).split())


def _clean(text) -> str:
    """One line with any e-mail address or GUID taken out: nothing a person is identified by reaches a work item."""
    return _GUID.sub(ID_GONE, bc.EMAIL_RE.sub(ADDRESS_GONE, _one_line(text)))


def _plain(cell) -> str:
    """A table cell or heading without its bold markers and wrapping backticks."""
    return str(cell).replace("**", "").strip().strip("`").strip()


def _blank(text) -> bool:
    """Nothing, a lone dash, or a template placeholder as a whole (`[Epic title]`, `${ANSWER}`)."""
    clean = _one_line(_COMMENT.sub("", str(text if text is not None else "")))
    return not clean or clean in ("-", "–", "—") or bool(_WHOLE_PLACEHOLDER.match(clean))


def _has_placeholder(text) -> bool:
    return bool(_PLACEHOLDER.search(_one_line(_COMMENT.sub("", str(text if text is not None else "")))))


def _filled(text) -> bool:
    """Real text: not blank and holding no placeholder, so a cell that is half a template is not pushed."""
    return not _blank(text) and not _has_placeholder(text)


def _norm(header) -> str:
    return re.sub(r"\s+", " ", _plain(header).lower().replace("’", "'"))


def _slug(name: str) -> str:
    """The domain slug `ado_sync_sources_tree` makes, so a heading matches the domain it names."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")


def _natural(ident: str) -> list:
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.split(r"(\d+)", str(ident)) if t]


def _suffix(ident: str) -> str:
    """`NFR-P01` -> `P01`, `Q-03` -> `03`; an id with no family prefix (`project`) stays whole."""
    return ident.split("-", 1)[1] if "-" in ident else ident


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def _cut(full: str, notes: list) -> str:
    """The title cut to the work item limit, with a note when it was."""
    if len(full) > MAX_TITLE:
        notes.append(f"title cut to {MAX_TITLE} characters, the work item limit")
        return full[:MAX_TITLE - 1] + "…"
    return full


def _title(ident: str, text, notes: list) -> str:
    """`<id> · <text>` on one line, cut to the work item limit with a note."""
    clean = _clean(text)
    return _cut(f"{ident}{SEP}{clean}" if clean else ident, notes)


def _unique(kind: str, seen: dict, ident: str, rel: str) -> None:
    if ident in seen:
        raise ValueError(f"{kind} {ident} is defined twice in {rel}; an id is used once")
    seen[ident] = rel


def _inside(root: Path, path: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.resolve().relative_to(root.resolve()).as_posix()


def _read(root: Path, path: Path) -> tuple[str, str]:
    """`(text with LF newlines, first 12 hex of the sha-256 of the stored bytes)`; refuses a file outside the repository
    and one that is not UTF-8 text."""
    if not _inside(root, path):
        raise ValueError(f"{path.name} resolves outside the repository; it is not read")
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(f"{path.name} is not UTF-8 text") from None
    return text.replace("\r\n", "\n"), hashlib.sha256(data).hexdigest()[:12]


def _artifact(root: Path, phase_dir: str, name: str) -> Path | None:
    """The artifact where the project keeps it (`.sdlc/artifacts/<phase>/<name>`), else at the repository root, else
    the first one found anywhere under `.sdlc/artifacts`."""
    for path in (root / ".sdlc" / "artifacts" / phase_dir / name, root / name):
        if path.is_file():
            return path
    base = root / ".sdlc" / "artifacts"
    found = sorted(base.rglob(name)) if base.is_dir() else []
    return next((p for p in found if p.is_file()), None)


def _shape(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _row(kind: str, ident: str, title: str, status, fields: dict, tags: set, rel: str, sha: str, notes: list,
         parent_ref=None, parent_note=None, ref=None) -> dict:
    ref = ref or f"sdlc:{kind}:{_suffix(ident)}"
    return {"ref": ref, "kind": kind, "id": ident, "title": _clean(title), "status": status, "fields": fields,
            "tags": {ref, *tags}, "parent_ref": parent_ref, "parent_note": parent_note, "related_refs": [],
            "source_path": rel, "source_sha": sha, "notes": notes}


# --- markdown tables, with the headings above them ------------------------------------------------------------

def _split_row(line: str) -> list[str]:
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    return [c.replace("\\|", "|").strip() for c in re.split(r"(?<!\\)\|", body)]


def _is_separator(line: str) -> bool:
    cells = _split_row(line)
    return bool(cells) and all(re.fullmatch(r":?-+:?", c) for c in cells)


def _scan_tables(text: str, skip: tuple = ()) -> list[dict]:
    """Every pipe table outside a code fence as `{"headings": [(level, text)], "header": [...], "rows": [[...]]}`, in
    document order; `headings` are the headings above it, outermost first. A table that starts inside a `skip` span
    (a `(start, end)` character range) is left out; its headings still count."""
    out: list[dict] = []
    lines = text.split("\n")
    offsets, at = [], 0
    for line in lines:
        offsets.append(at)
        at += len(line) + 1

    def skipped(i: int) -> bool:
        return any(a <= offsets[i] < b for a, b in skip)

    stack: list[tuple[int, str]] = []
    fenced, i = False, 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced:
            heading = _HEADING.match(line)
            if heading:
                level = len(heading.group(1))
                stack = [h for h in stack if h[0] < level] + [(level, _plain(heading.group(2)))]
            elif (stripped.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|")
                  and _is_separator(lines[i + 1])):
                header, rows, j = _split_row(stripped), [], i + 2
                while j < len(lines) and lines[j].strip().startswith("|"):
                    rows.append(_split_row(lines[j]))
                    j += 1
                if not skipped(i):
                    out.append({"headings": list(stack), "header": header, "rows": rows})
                i = j
                continue
        i += 1
    return out


def _priority(text) -> str | None:
    """P0..P3 when `text` names exactly one; None for blank, unfilled ("P0 / P1") or anything else."""
    found = set(re.findall(r"\bP([0-3])\b", str(text or "")))
    return f"P{found.pop()}" if len(found) == 1 else None


# --- type, state and the fields only some types carry ---------------------------------------------------------

def _pin(cfg: dict, kind: str) -> str | None:
    types = cfg.get("types")
    value = types.get(kind) if isinstance(types, dict) else None
    return value if isinstance(value, str) and value else None


def _type_for(kind: str, cfg: dict, schema: dict, notes: list) -> tuple[str | None, str | None]:
    """`(type_name, route)` a kind lands on, or `(None, None)` with a note. The kind's own `types.<kind>` pin is
    validated against the process and, when the process lacks it, is not replaced by a default. With no pin: the
    type the kind it follows lands on (`_FOLLOWS`), or - a question - nothing, for the process must name one."""
    follows = _FOLLOWS.get(kind)
    if _pin(cfg, kind) is not None or follows is None:
        name, why = resolve_type(schema, kind, cfg)
        route = f"types.{kind}"
    else:
        other, label = follows
        name, why = resolve_type(schema, other, cfg)
        route = f"types.{other}" if _pin(cfg, other) is not None else label
    if name is None:
        notes.append(f"type not set: {why}")
        return None, None
    return name, route


def _state_for(kind: str, status, type_name, cfg: dict, schema: dict, notes: list) -> str | None:
    """The process state a status resolves to on `type_name`, or None with a note: a state is never defaulted. `states`
    is narrowed to this kind and the kind is pinned to the chosen type, so its `states.<kind>` rule applies to it even
    when the type came from a default."""
    if not status or type_name is None:
        return None
    types = cfg.get("types")
    rules = cfg.get("states")
    narrowed = {**cfg, "types": {**(types if isinstance(types, dict) else {}), kind: type_name},
                "states": {kind: rules[kind]} if isinstance(rules, dict) and kind in rules else {}}
    word = _RULE_STATUS.get(kind, {}).get(status, status)
    name, reason = resolve_state(schema, type_name, word, narrowed)
    if name is None:
        notes.append(f"state not set: {reason}")
    return name


def _typed(fields: dict, type_name, route) -> None:
    if type_name is not None:
        fields["type_name"], fields["type_route"] = type_name, route


def _only_when_carried(fields: dict, schema: dict, type_name, ref: str, value) -> None:
    """Set `ref` only when the resolved type carries it (a field the type lacks would fail the create)."""
    if value is not None and type_name is not None and field_on_type(schema, type_name, ref) is not None:
        fields[ref] = value


def _unapplied(kind: str, cfg: dict, notes: list) -> None:
    configured = (cfg.get("fields") or {}).get(kind) if isinstance(cfg.get("fields"), dict) else None
    if isinstance(configured, dict):  # a constant `{field, value}` is applied by `ado_sync_sources.projections`
        configured = {k: r for k, r in configured.items() if not (isinstance(r, dict) and "value" in r)}
    if configured:
        notes.append(f"fields.{kind} is not applied: a {kind}'s fields are its title, the ones the type carries and "
                     "its tags")


def _criteria(lines: list[str]) -> str | None:
    """Acceptance criteria as the field holds them: HTML, one escaped line each."""
    return "<br>".join(html.escape(line, quote=False) for line in lines) if lines else None


def _labelled_block(lines: list[tuple[str, str]]) -> str:
    """A Description block: one escaped `<p><strong>label:</strong> text</p>` paragraph per (label, text) pair."""
    return "".join(f"<p><strong>{html.escape(label, quote=False)}:</strong> {html.escape(text, quote=False)}</p>"
                   for label, text in lines)


# --- decisions and the domains and features a row hangs under -------------------------------------------------

def _decision_ids(root: Path) -> dict[int, str] | None:
    """`{number: "DL-03"}` for the decision log, or None when there is none."""
    path = next((p for p in (root / ".sdlc" / "decision-log.md", root / "decision-log.md") if p.is_file()), None)
    if path is None:
        return None
    _read(root, path)  # refuses a log that resolves outside the repository
    out: dict[int, str] = {}
    for d in parse_decisions(path):
        m = re.fullmatch(r"DL-(\d+)", (d.get("id") or "").strip().upper())
        if m:
            out.setdefault(int(m.group(1)), m.group(0))
    return out


def _domains(root: Path) -> tuple[dict[str, str], str | None]:
    """`({domain slug: name}, why-not)`: the domains of `requirements.md`, or an empty map and the `no parent`
    sentence that says why there are none. The tree source is imported lazily, because importing it registers it."""
    tree = importlib.import_module("ado_sync_sources_tree")
    try:
        rows = tree.load_domains(root)
    except ValueError:
        return {}, _NO_TREE + "does not read as domains (plan --kind domain says why)"
    if rows:
        return {r["id"]: r["title"] for r in rows}, None
    if not (root / tree.REQUIREMENTS_REL).is_file():
        return {}, _NO_TREE + "was not found, so no domain is known"
    return {}, _NO_TREE + "declares no domains"


def _briefs_naming(root: Path) -> tuple[dict[int, list[str]], str | None]:
    """`({BR number: [FE ids of the briefs naming it]}, why-not)` over every feature brief; `BR-01` and `BR-1` are one
    rule. Features come from `ado_sync_sources.load_features`, so a brief means here what it means there."""
    sources = importlib.import_module("ado_sync_sources")
    try:
        features = sources.load_features(root, {}, {})
    except ValueError:
        return {}, "no parent: the feature briefs do not read cleanly (plan --kind feature says why)"
    named: dict[int, list[str]] = {}
    for feature in features:
        text, _ = _read(root, root / feature["source_path"])
        for m in ID_RE.finditer(text):
            if m.group(1) == "BR":
                ids = named.setdefault(int(re.search(r"\d+", m.group(0)).group(0)), [])
                if feature["id"] not in ids:
                    ids.append(feature["id"])
    return named, None


# --- NFRs -----------------------------------------------------------------------------------------------------

def _test_plan_spans(text: str) -> tuple:
    """The `(start, end)` of the Acceptance Test Plan section, found through the shape (aliases included)."""
    doc = document_shape.read_document(text, _shape(NFR_SHAPE))
    return tuple((b["start"], b["end"]) for b in doc["blocks"]
                 if b.get("kind") == "section" and b.get("heading") == TEST_PLAN)


def load_nfrs(repo_root, cfg: dict | None = None, schema: dict | None = None) -> list[dict]:
    """One projection per NFR row of `non-functional-requirements.md`, in document order; [] when there is no file."""
    root, cfg, schema = Path(repo_root), cfg or {}, schema or {}
    path = _artifact(root, "01-requirements", "non-functional-requirements.md")
    if path is None:
        return []
    text, _ = _read(root, path)
    rel = _rel(root, path)
    domains, why = _domains(root)
    base_notes: list[str] = []
    type_name, route = _type_for("nfr", cfg, schema, base_notes)
    _unapplied("nfr", cfg, base_notes)
    out, seen = [], {}
    for table in _scan_tables(text, _test_plan_spans(text)):
        header = [_norm(h) for h in table["header"]]
        if not header or header[0] != "nfr id":
            continue
        labels = [_plain(h) for h in table["header"]]
        priority_col = header.index("priority") if "priority" in header else None
        for cells in table["rows"]:
            ident = _plain(cells[0]).upper() if cells else ""
            if not _NFR_ID.fullmatch(ident) or len(cells) < 2 or _blank(cells[1]):
                continue  # not an NFR row, or no requirement text (the template's stand-in row)
            _unique("NFR", seen, ident, rel)
            notes = list(base_notes)
            marked = [labels[i] for i in range(1, min(len(cells), len(labels))) if _has_placeholder(cells[i])]
            if marked:
                notes.append(f"the row still holds template placeholders ({', '.join(marked)}); fill it in before it "
                             "goes on a board")
            lines = []
            for i in range(2, min(len(cells), len(labels))):
                if i == priority_col or not _filled(cells[i]):
                    continue
                if is_forbidden_field(labels[i]):
                    notes.append(f"the {labels[i]} column is an activity metric the standard never tracks; it is not "
                                 "pushed")
                    continue
                lines.append(f"{labels[i]}: {_clean(cells[i])}")
            fields = {TITLE: _title(ident, cells[1], notes)}
            _typed(fields, type_name, route)
            priority = _priority(cells[priority_col]) if priority_col is not None and priority_col < len(cells) else None
            _only_when_carried(fields, schema, type_name, PRIORITY, PRIORITY_VALUE.get(priority))
            _only_when_carried(fields, schema, type_name, ACCEPTANCE, _criteria(lines))
            parent, note = None, why or "no parent: not under a domain heading"
            for _, heading in reversed(table["headings"]):
                if _slug(heading) in domains:
                    parent, note = f"sdlc:domain:{_slug(heading)}", None
                    break
            sha = _digest({"header": table["header"], "cells": cells, "parent": parent})
            out.append(_row("nfr", ident, cells[1], None, fields, set(), rel, sha, notes, parent, note))
    return out


# --- business rules -------------------------------------------------------------------------------------------

def load_rules(repo_root, cfg: dict | None = None, schema: dict | None = None) -> list[dict]:
    """One projection per filled `BR-NN` row of `business-rules.md`, in document order; [] when there is no file."""
    root, cfg, schema = Path(repo_root), cfg or {}, schema or {}
    path = _artifact(root, "01-requirements", "business-rules.md")
    if path is None:
        return []
    text, _ = _read(root, path)
    rel = _rel(root, path)
    named, briefs_why = _briefs_naming(root)
    decisions = _decision_ids(root)
    base_notes: list[str] = []
    type_name, route = _type_for("rule", cfg, schema, base_notes)
    _unapplied("rule", cfg, base_notes)
    out, seen = [], {}
    for table in _scan_tables(text):
        header = [_norm(h) for h in table["header"]]
        if not header or header[0] not in _RULE_ID_HEADERS:
            continue
        col = {name: header.index(name) for name in ("condition", "outcome", "source") if name in header}
        condition, outcome = col.get("condition", 1), col.get("outcome", 2)
        for cells in table["rows"]:
            ident = _plain(cells[0]).upper() if cells else ""
            if not _BR_ID.fullmatch(ident) or len(cells) <= condition or _blank(cells[condition]):
                continue  # not a rule row, or the template's stand-in row
            _unique("rule", seen, ident, rel)
            notes = list(base_notes)
            number = int(ident[3:])
            if briefs_why is not None:
                parent, note = None, briefs_why
            else:
                features = sorted(named.get(number, []), key=_natural)
                parent, note = None, f"no parent: no feature brief names {ident}"
                if len(features) == 1:
                    parent, note = f"sdlc:feature:{_suffix(features[0])}", None
                elif features:
                    note = f"no parent: {ident} is named by several feature briefs ({', '.join(features)})"
            body = cells[outcome] if len(cells) > outcome else ""
            pending = _PENDING.search(body)
            fields = {TITLE: _title(ident, cells[condition], notes)}
            lines = [("Condition", _clean(cells[condition]))]
            then = _clean(_PENDING_ANY.sub("", body)).strip(" *")
            if _filled(then):
                lines.append(("Outcome", then))
            if "source" in col and col["source"] < len(cells) and _filled(cells[col["source"]]):
                lines.append(("Source", _clean(cells[col["source"]])))
            if pending:
                wanted = int(pending.group(1))
                lines.append(("Pending decision", f"DL-{pending.group(1)}"))
                name = (decisions or {}).get(wanted, f"DL-{pending.group(1)}")
                fields["predecessor_refs"] = [f"sdlc:decision:{_suffix(name)}"]
                if decisions is None:
                    notes.append(f"no decision log was found, so DL-{pending.group(1)} is not checked")
                elif wanted not in decisions:
                    notes.append(f"DL-{pending.group(1)} is not in the decision log")
            _typed(fields, type_name, route)
            # The text goes to the Description, which is C for a rule (ado_sync_model.KIND_OWNERSHIP["rule"]), and
            # never to AcceptanceCriteria, which is S for a rule: a board edit there would read as drift to overwrite.
            fields[DESCRIPTION] = _labelled_block(lines)
            sha = _digest({"header": table["header"], "cells": cells, "parent": parent})
            out.append(_row("rule", ident, cells[condition], None, fields, set(), rel, sha, notes, parent, note))
    return out


# --- discovery questions --------------------------------------------------------------------------------------

def _question_regions(text: str) -> tuple[str, str]:
    """`(the question entries' text, the Answer Log's text)`. The Questions section when the shape finds one, else the
    whole document minus its Answer Log; the log is never a list of questions."""
    doc = document_shape.read_document(text, _shape(QUESTION_SHAPE))
    spans = {b["heading"]: (b["start"], b["end"]) for b in doc["blocks"] if b.get("kind") == "section"}
    log = spans.get("Answer Log")
    log_text = text[log[0]:log[1]] if log else text
    if "Questions" in spans:
        return text[spans["Questions"][0]:spans["Questions"][1]], log_text
    return (text[:log[0]] + text[log[1]:] if log else text), log_text


def _entries(region: str) -> list[dict]:
    """The `#### Q-NN: <question>` entries of a region, each with its `### Block:` and its bullet lines; an entry whose
    id is still a template token (`Q-${NN}`) ends the entry before it and is not one itself."""
    out, block, current = [], "", None
    for line in region.split("\n"):
        head, group = _Q_HEAD.match(line), _BLOCK.match(line)
        if group:
            block, current = _plain(group.group(1)), None
        elif head:
            current = {"id": head.group(1).upper(), "question": head.group(2), "block": block, "lines": [line.strip()]}
            out.append(current)
        elif line.startswith("#"):
            current = None
        elif current is not None:
            current["lines"].append(line.strip())
    return out


def _answered_in_log(log_text: str) -> set[str]:
    """Question ids with a filled Answer cell in a table of the log."""
    out: set[str] = set()
    for table in _scan_tables(log_text):
        header = [_norm(h) for h in table["header"]]
        if len(header) < 2 or header[0] != "id" or "answer" not in header:
            continue
        col = header.index("answer")
        for cells in table["rows"]:
            if cells and re.fullmatch(r"Q-\d+", _plain(cells[0]).upper()) and col < len(cells) and _filled(cells[col]):
                out.add(_plain(cells[0]).upper())
    return out


def load_questions(repo_root, cfg: dict | None = None, schema: dict | None = None) -> list[dict]:
    """One projection per numbered entry of `question-list.md`, in document order; [] when there is no file."""
    root, cfg, schema = Path(repo_root), cfg or {}, schema or {}
    path = _artifact(root, "00-discovery", "question-list.md")
    if path is None:
        return []
    text, _ = _read(root, path)
    rel = _rel(root, path)
    region, log_text = _question_regions(text)
    logged = _answered_in_log(log_text)
    base_notes: list[str] = []
    type_name, route = _type_for("question", cfg, schema, base_notes)
    _unapplied("question", cfg, base_notes)
    out, seen = [], {}
    for entry in _entries(region):
        if _blank(entry["question"]):
            continue
        ident = entry["id"]
        _unique("question", seen, ident, rel)
        labels = {}
        for line in entry["lines"][1:]:
            m = _LABEL.match(line)
            if m:
                labels.setdefault(m.group(1).strip(), m.group(2))
        answer = labels.get("Answer", "")
        inline = _filled(answer) and _one_line(_COMMENT.sub("", answer)).lower() not in OPEN_WORDS
        status = "answered" if inline or ident in logged else "open"
        notes = list(base_notes)
        fields = {TITLE: _title(ident, entry["question"], notes)}
        _typed(fields, type_name, route)
        state = _state_for("question", status, type_name, cfg, schema, notes)
        if state:
            fields[STATE] = state
        if entry["block"]:
            fields["block"] = _clean(entry["block"])
        if _one_line(labels.get("Route", "")).lower() in ROUTES:
            fields["route"] = _one_line(labels["Route"]).lower()
        answerer = _one_line(labels.get("Likely answerer", ""))
        if bc.HANDLE_RE.fullmatch(answerer):
            fields["owner_handle"] = answerer
        sha = _digest({"lines": entry["lines"], "answered_in_log": ident in logged})
        out.append(_row("question", ident, entry["question"], status, fields, {f"sdlc:status:{status}"}, rel, sha,
                        notes))
    return out


# --- the lifecycle item ---------------------------------------------------------------------------------------

def _day(value) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10]).isoformat()
        except ValueError:
            return None
    return None


def _gate_cell(results) -> str:
    """`6 passed, 0 failed, 1 manual` from a recorded gate; a phase with none reads "no gate recorded", never zeros."""
    parts = []
    if isinstance(results, dict):
        for key in ("passed", "failed", "manual"):
            value = results.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                parts.append(f"{value} {key}")
    return ", ".join(parts) if parts else "no gate recorded"


def _signoff_cell(data: dict, results) -> str:
    """The sign-off day, and the signer only when it is already a roster-style `@handle`."""
    if _clean(data.get("status")).lower() == "completed":
        when = _day(data.get("completed_at")) or "date not recorded"
        signer = results.get("signed_off_by") if isinstance(results, dict) else None
        if isinstance(signer, str) and signer.strip():
            text = f"{when} by {signer.strip()}" if bc.HANDLE_RE.fullmatch(signer.strip()) else when
        else:
            text = f"advanced {when}, no named sign-off"
    else:
        text = "not yet"
    sign_offs = data.get("sign_offs")
    count = sum(1 for e in sign_offs if isinstance(e, dict)) if isinstance(sign_offs, list) else 0
    return f"{text}; {count} discipline sign-off{'' if count == 1 else 's'}" if count else text


def _phase_rows(phases) -> list[dict]:
    ordered = sorted(((str(k).strip(), v) for k, v in phases.items()),
                     key=lambda kv: (pm.phase_order(kv[0]) if pm.phase_order(kv[0]) is not None else 10 ** 6, kv[0]))
    rows = []
    for phase, data in ordered:
        data = data if isinstance(data, dict) else {}
        results = data.get("gate_results")
        rows.append({"phase": _clean(phase), "name": _clean(data.get("name")) or _clean(pm.phase_name(phase)),
                     "status": _clean(data.get("status")) or "not recorded", "gate": _gate_cell(results),
                     "signed_off": _clean(_signoff_cell(data, results))})
    return rows


def _lifecycle_status(rows: list[dict]) -> str | None:
    states = [r["status"].lower() for r in rows]
    if not states:
        return None
    if all(s == "completed" for s in states):
        return "closed"
    return "in-flight" if any(s in ("active", "completed") for s in states) else "open"


def _description(rows: list[dict]) -> str:
    if not rows:
        return "<p>No phases are recorded in state.yaml yet.</p>"
    columns = (("phase", "Phase"), ("name", "Name"), ("status", "Status"), ("gate", "Gate"),
               ("signed_off", "Signed off"))
    head = "".join(f"<th>{label}</th>" for _, label in columns)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(r[key], quote=False)}</td>" for key, _ in columns) + "</tr>"
                   for r in rows)
    return ("<p>The phase, gate and sign-off record in <code>state.yaml</code>. It is read from the repository; "
            f"change it there.</p><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")


def load_lifecycle(repo_root, cfg: dict | None = None, schema: dict | None = None) -> list[dict]:
    """The one projection of `.sdlc/state.yaml`; [] when there is no state file. A file that is not a mapping raises
    `ValueError`."""
    root, cfg, schema = Path(repo_root), cfg or {}, schema or {}
    path = root / STATE_REL
    if not path.is_file():
        return []
    text, _ = _read(root, path)
    try:
        state = yaml.safe_load(text)
    except yaml.YAMLError:
        raise ValueError(f"{STATE_REL} is not valid YAML; the lifecycle item is not projected") from None
    if not isinstance(state, dict):
        raise ValueError(f"{STATE_REL} is not a mapping; the lifecycle item is not projected")
    notes: list[str] = []
    project = _clean(state.get("project_name"))
    if not project or _has_placeholder(project):
        project = ""
        notes.append("state.yaml names no project, so the title carries none")
    title = f"{project}{SEP}SDLC lifecycle" if project else "SDLC lifecycle"
    phases = state.get("phases")
    rows = _phase_rows(phases) if isinstance(phases, dict) else []
    status = _lifecycle_status(rows)
    type_name, route = _type_for("lifecycle", cfg, schema, notes)
    _unapplied("lifecycle", cfg, notes)
    fields = {TITLE: _cut(title, notes)}
    _typed(fields, type_name, route)
    fields[DESCRIPTION] = _description(rows)
    fields["description_rows"] = rows
    state_name = _state_for("lifecycle", status, type_name, cfg, schema, notes)
    if state_name:
        fields[STATE] = state_name
    sha = _digest({"project": project, "rows": rows})
    return [_row("lifecycle", LIFECYCLE_ID, title, status, fields, {f"sdlc:status:{status}"} if status else set(),
                 STATE_REL, sha, notes)]


# --- measurements ---------------------------------------------------------------------------------------------

MEASUREMENT_COLUMNS = (("outcome", "Outcome"), ("threshold", "Threshold"), ("measure", "How We'll Measure"))


def _measurement_block(lines: list[tuple[str, str]]) -> str:
    """The Description block: the threshold and how-measured text, one escaped paragraph each."""
    return _labelled_block(lines)


def load_measurements(repo_root, cfg: dict | None = None, schema: dict | None = None) -> list[dict]:
    """One projection per threshold row of each `success-criteria.md` dimension, in document order, parented to that
    dimension's Outcome; [] when there is no file, no dimension or no threshold table. Lands only on the type
    `types.measurement` pins; without one a row has no type and a note says it stays in its Outcome's block."""
    root, cfg, schema = Path(repo_root), cfg or {}, schema or {}
    tree = importlib.import_module("ado_sync_sources_tree")
    path = root / tree.SUCCESS_REL
    if not path.is_file():
        return []
    _read(root, path)  # refuses a file that resolves outside the repository, or one that is not UTF-8
    rel = _rel(root, path)
    name, why = resolve_type(schema, "measurement", cfg)
    base_notes: list[str] = []
    _unapplied("measurement", cfg, base_notes)
    out, seen = [], {}
    for outcome in tree.load_outcomes(root):
        number = str(outcome["id"]).split("-", 1)[0]
        where = _clean(outcome["fields"].get(TITLE) or outcome["title"])
        rows = outcome["fields"].get("description_rows") or []
        for position, raw in enumerate(rows, start=1):
            cell = raw.get("outcome", "")
            if _blank(cell):
                continue  # no Outcome cell: not a measurement (nothing to title it by)
            notes = list(base_notes)
            slug = _slug(_clean(cell))
            if not slug:
                slug = f"row-{position}"
                notes.append(f"the Outcome cell has no letter or digit to name it by, so it is named by its position "
                             f"({slug})")
            ident = f"{number}-{slug}"
            _unique("measurement", seen, ident, rel)
            marked = [label for key, label in MEASUREMENT_COLUMNS if _has_placeholder(raw.get(key, ""))]
            if marked:
                notes.append(f"the row still holds template placeholders ({', '.join(marked)}); fill it in before it "
                             "goes on a board")
            fields = {TITLE: _cut(_clean(cell), notes)}
            if name is None:
                notes.append(f"no item: {why}; the threshold stays in the block of {where} (pin types.measurement to "
                             "a Key-Result-style type to make it an item)")
            else:
                _typed(fields, name, "types.measurement")
            lines = [(label, _clean(raw.get(key, ""))) for key, label in MEASUREMENT_COLUMNS[1:]
                     if _filled(raw.get(key, ""))]
            if lines:
                fields[DESCRIPTION] = _measurement_block(lines)
            else:
                notes.append("no threshold or how-measured text is filled in, so no block is written")
            fields["description_rows"] = [{key: _clean(raw.get(key, "")) for key, _ in MEASUREMENT_COLUMNS}]
            parent = outcome["ref"]
            sha = _digest({"parent": parent, "row": raw})
            out.append(_row("measurement", ident, cell, None, fields, set(), rel, sha, notes, parent, None,
                            ref=f"sdlc:measurement:{ident}"))
    return out


# --- registration -----------------------------------------------------------------------------------------

def _register(hooks=None) -> bool:
    """Add this module's five entries to `ado_sync_sources`' extend-only table; True when they were added.

    `hooks` is the module (or any object with a `SOURCES` dict); by default it is looked up in `sys.modules` and
    imported lazily. A module that does not exist yet, or lacks the table, registers nothing and returns False -
    a real import error inside it is not swallowed. Only this module's own keys are set."""
    if hooks is None:
        hooks = sys.modules.get("ado_sync_sources")
        if hooks is None:
            try:
                hooks = importlib.import_module("ado_sync_sources")
            except ModuleNotFoundError as exc:
                if exc.name != "ado_sync_sources":
                    raise
                return False
    sources = getattr(hooks, "SOURCES", None)
    if not isinstance(sources, dict):
        return False
    sources.update({"nfr": load_nfrs, "rule": load_rules, "question": load_questions, "lifecycle": load_lifecycle,
                    "measurement": load_measurements})
    return True


_register()
