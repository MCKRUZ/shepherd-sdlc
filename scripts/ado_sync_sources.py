"""The repository half of the Azure Boards mirror: what the repo says each work item should be (B2-P3).

`projections(repo_root, cfg, schema, kinds)` reads the files a team already keeps and returns one
*projection* per item, so a later step can compare it with the board (`ado_sync_model.diff`,
`classify_drift`) or turn it into a create patch. It only reads: it writes no file, spawns nothing, makes
no network call and never opens a path outside `repo_root` (a source that resolves outside it is refused).

It is a library part, usable two ways like every part of the plugin:

  * Workflow mode — `ado_sync.py --state .sdlc/state.yaml …` hands in the repository root, the parsed
    `.sdlc/ado.yaml` and the discovered `.sdlc/ado/schema.json`.
  * Standalone — point `repo_root` at any folder with `specs/`, `epics.md`, a feature brief or a decision
    log; pass `{}` for `cfg` and `schema`. Nothing needs `.sdlc/`; what the missing context would have
    supplied (a work-item state, an assignee) is left out and named in the projection's `notes`.

A projection is the dict the interface sheet pins, plus `notes`:

  ref, kind, id, title, status, fields, tags, parent_ref, parent_note, related_refs, source_path, source_sha

    `ref`        `sdlc:<kind>:<id without its family prefix>` — `sdlc:spec:0004`, `sdlc:feature:03`,
                 `sdlc:epic:001`, `sdlc:decision:01`, `sdlc:sprint:S07`, `sdlc:spike:0003`.
    `id`         the id as people write it: `0004`, `FE-03`, `EP-001`, `DL-01`, `S07`, `0003`.
    `title`      the bare name (a spec's `name`, a feature's header title, a decision's question, a
                 sprint's goal); `fields["System.Title"]` is `<id> · <title>`, cut to 255 characters.
    `status`     the repository's own word for it (a spec's `ready`, a decision's `open`, a sprint's
                 `planning`), or None when the repository does not hold one — an epic's and a feature's
                 state is the board's, so it is never invented.
    `fields`     by reference name, only what the repository knows: `System.Title`; `System.State` when the
                 process can say which state the status is (`ado_schema_map.resolve_state`, with `states`
                 narrowed to this kind); `System.AssignedTo` only through the roster's `email_for`;
                 `System.IterationPath` from `iterations`; an epic's `Microsoft.VSTS.Common.Priority` (P0..P3
                 as 1..4) and `Microsoft.VSTS.Common.AcceptanceCriteria` (its `**Acceptance criteria:**` items,
                 escaped, one per line) when the type carries them; each `fields.<kind>` entry the config
                 names; and each constant `fields.<kind>.<key>: {field, value}` for every kind, verbatim, named
                 in the extra key `constant_fields` (the model fills it on update only while the board's field
                 is empty and reads a board change to it as the board's). Never an effort, estimate, date or
                 size, and no `System.Description`: that block is built from the file's hyperlink by the patch
                 builder.
    `tags`       a set: the item's own `sdlc:<kind>:<id>`, a spec's `sdlc:status:`, `risk:`, `channel:`,
                 `eng-review:`, `data-review:` and `carried-from:`, and — for a parent or `Related` ref whose
                 requirements-tree kind rides as a tag on this process (`ride_fit`, `ride_tag`) — `domain:<slug>`,
                 `fr:<id>`, and the `outcome:<id>` of each outcome a riding domain maps to (every one a
                 `PLUGIN_TAG_PREFIXES`).
    `parent_ref` the one parent edge the repository declares, or None with `parent_note` saying why (a
                 spec's `FE-NN` in `source:`; a feature's `(epic: …)` header, by id, else by exact title).
    `related_refs`  `Related` edges: a spec's `Traces to` FRs when `tree.spec_traces` is on, else [].
    `source_path`, `source_sha`  the repo-relative file and the first 12 hex of the sha256 of the item's own
                 source text: the whole file for a spec, brief, sprint or spike; an epic's heading block and
                 summary row; a decision's table row. An edit to one epic or decision moves no other
                 (`ado_sync_model.projection_hash` hashes this field with the rest of the projection), and a
                 CRLF checkout of the same commit moves none (CRLF is read as LF before hashing).
    `notes`      sentences about what was left out and why (no assignee email, no state the process can
                 express, a title cut). Never an address, a name or free text from the source.

Honesty: a thing that is not known is absent or None with a note, never defaulted. An id used twice
(two specs `0004`, two briefs for `FE-03`) is refused naming both files rather than one winning.

Two registries make the module extend-only. `SOURCES` maps a kind to its loader: `loader(repo_root, cfg,
schema)` or, for a loader that needs neither, `loader(repo_root)`; it returns projections. Later packages
add kinds (the requirements tree adds `outcome`, `domain` and `requirement`). `PARENT_RESOLVERS` maps a kind
to `resolver(repo_root, row) -> (parent_ref, note)`; `projections` calls it for every row of its kind
and writes the answer into `parent_ref` and `parent_note`. A resolver may answer a third value, the item's
`Related` refs (`ado_sync_sources_tree.epic_links`: an epic's fulfils links, kit K25); `projections` appends
them to `related_refs`, each once, refusing one that is not `sdlc:<kind>:<id>`. `row["source_row"]` is the raw material the
loader read (a spec's frontmatter; an epic's `{"Epic ID", "Title", "Priority", "FR Link"}`; a feature's
`{"epic": <text after "epic:" or None>}`); it is removed before `projections` returns. The spec and feature
resolvers also work on a bare row, re-reading the file at `source_path`. Whoever registers
`PARENT_RESOLVERS["epic"]` must import their module before calling `projections`: with none registered an
epic says so in `parent_note`.

After its loader and resolver, every row of every kind gets two passes, so `plan`, `apply`, `drift` and `pull` see
one projection: the kind's constants (`_constants`, `_apply_constants`) and the tags of the requirements-tree kinds
that ride as tags on this process (`_Rides`: `ride_fit` reads the fit once, `ride_tag` names the tag, and a riding
domain's outcomes come from `ado_sync_sources_tree.load_domains`, imported lazily, only when a row needs them).
"""

import functools
import hashlib
import html
import importlib
import inspect
import json
import re
import unicodedata
from pathlib import Path

import yaml

import boards_contract as bc
import risk_model as rm
from ado_schema_map import configured_kinds, field_on_type, fit_levels, resolve_state, resolve_type
from artifact_lineage import ID_RE
from check_spec import parse_frontmatter
from document_shape import read_document
from new_spec import SPEC_FILE_RE
from sprint_model import SPRINT_ID_RE, is_forbidden_field, normalize_review
from track_decisions import CLOSED_STATUSES, parse_decisions
from track_specs import scan_specs
from validate_team import email_for

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SHAPES = PLUGIN_ROOT / "templates" / "phases" / "01-requirements"
MAX_TITLE = 255                                  # the work item title limit
SEP = " · "                                      # `<id> · <title>`
PRIORITY = "Microsoft.VSTS.Common.Priority"
ACCEPTANCE = "Microsoft.VSTS.Common.AcceptanceCriteria"
ITERATION = "System.IterationPath"
PRIORITY_VALUE = {"P0": 1, "P1": 2, "P2": 3, "P3": 4}   # the board's 1 (most urgent) to 4
SCHEDULING = "microsoft.vsts.scheduling."
PINNED = frozenset({"ref", "kind", "id", "title", "status", "fields", "tags", "parent_ref", "parent_note",
                    "related_refs", "source_path", "source_sha"})
ROSTER = ".sdlc/team.yaml"
SPRINT_LOG = ".sdlc/metrics/sprint-log.jsonl"
NO_TREE = "no parent: the requirements tree is not loaded, so no epic parent is resolved"

# a sprint's or a decision's own word -> the word `ado_schema_map.STATUS_RULES` knows
_RULE_STATUS = {
    "sprint": {"planning": "draft", "ready": "ready", "closed": "closed"},
    "decision": {"open": "open", "decided": "decided", "closed": "closed"},
}
_DECIDED = frozenset({"decided", "resolved"})

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
_PLACEHOLDER = re.compile(r"^(?:\[[^\]]*\]|<[^>]*>)$")
_EPIC_HEADING = re.compile(r"^###[ \t]+(EP-[A-Z]*\d+)[ \t]*:[ \t]*(.*?)[ \t]*$", re.MULTILINE)
_ANY_HEADING = re.compile(r"^#{1,3}[ \t]+\S", re.MULTILINE)
_EPIC_PRIORITY = re.compile(r"^\*\*Priority:\*\*[ \t]*(P\d)\b", re.MULTILINE | re.IGNORECASE)
_EPIC_LINKED = re.compile(r"^\*\*Linked requirement:\*\*[ \t]*(.*?)[ \t]*$", re.MULTILINE)
_EPIC_CRITERIA = re.compile(r"^\*\*Acceptance criteria:\*\*[ \t]*$", re.MULTILINE | re.IGNORECASE)
_LIST_ITEM = re.compile(r"^[ \t]*[-*+][ \t]+(?:\[[ xX]\][ \t]+)?(.*?)[ \t]*$")
_STAND_IN = re.compile(r"\[[^\]\n]+\](?!\()")  # a template stand-in such as `[condition]`; `[text](url)` is a link
_BRIEF_H1 = re.compile(r"^#[ \t]+Feature Brief\b[ \t]*[—–-]*[ \t]*(FE-[A-Z]*\d+)[ \t]*:[ \t]*(.*?)[ \t]*$",
                       re.IGNORECASE)
_BRIEF_EPIC = re.compile(r"\([ \t]*epic[ \t]*:[ \t]*(.*)\)[ \t]*$", re.IGNORECASE)
_DECISION_ID = re.compile(r"^DL-\d+$", re.IGNORECASE)
_RESOLUTION = re.compile(r"\s+[—–-]+\s+decided by\b.*$", re.DOTALL | re.IGNORECASE)
_SPIKE_H1 = re.compile(r"^#[ \t]+Spike[ \t]+\S+[ \t]*[—–-]+[ \t]*(.*?)[ \t]*$", re.MULTILINE)


# --- small helpers --------------------------------------------------------------------------------------------

def _dig(obj, *keys):
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _one_line(text) -> str:
    """The text on one line: control characters (an escape, a tab, a newline) become a space, runs collapse."""
    return " ".join(_CONTROL.sub(" ", str(text or "")).split())


def _blank(text) -> bool:
    """Nothing, a bracketed template placeholder (`[Epic title]`, `<FE-NN>`), or a lone dash."""
    clean = _one_line(text)
    return not clean or clean in ("—", "-") or bool(_PLACEHOLDER.match(clean))


def _title(ident: str, text, notes: list) -> str:
    clean = _one_line(text)
    full = f"{ident}{SEP}{clean}" if clean else ident
    if len(full) > MAX_TITLE:
        notes.append(f"title cut to {MAX_TITLE} characters, the work item limit")
        full = full[:MAX_TITLE - 1] + "…"
    return full


def _tag(prefix: str, value) -> str | None:
    clean = _one_line(value).replace(";", "-").replace(",", "-")
    return None if not clean or clean in ("—", "-") else f"{prefix}{clean}"


def _suffix(ident: str) -> str:
    """`FE-03` -> `03`; `S07` (no family prefix) stays `S07`."""
    return ident.split("-", 1)[1] if "-" in ident else ident


def _norm_name(text) -> str:
    """For an exact-title match: same words, ignoring case, spacing and `-` / `_` between them."""
    return " ".join(_one_line(text).replace("-", " ").replace("_", " ").casefold().split())


def _natural(ident: str) -> list:
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.split(r"(\d+)", str(ident)) if t]


def _inside(root: Path, path: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.resolve().relative_to(root.resolve()).as_posix()


def _fingerprint(data: bytes) -> str:
    """The first 12 hex of the sha256 of `data` with CRLF read as LF. Git for Windows checks a commit out CRLF by
    default (autocrlf), so hashing the bytes as they lie would give the same commit two fingerprints -- a ledger written
    on one machine would then read "the repo moved" on another. Only the line ending is unified; a BOM or a lone CR is
    a real byte and still moves it."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()[:12]


def _read(root: Path, path: Path) -> tuple[str, str]:
    """`(text, sha)` of a source file; refuses one that resolves outside the repository."""
    if not _inside(root, path):
        raise ValueError(f"{path.name} resolves outside the repository; it is not read")
    data = path.read_bytes()
    return data.decode("utf-8", errors="replace"), _fingerprint(data)


def _read_optional(root: Path, path: Path) -> str | None:
    """The text of a sidecar (roster, ledger), or None when it is absent, unreadable or outside the repo."""
    try:
        return _read(root, path)[0] if path.is_file() else None
    except (OSError, ValueError):
        return None


def _row(kind: str, ident: str, title: str, status, fields: dict, tags: set, source_path: str, sha: str,
         notes: list, source_row: dict) -> dict:
    return {"ref": f"sdlc:{kind}:{_suffix(ident)}", "kind": kind, "id": ident, "title": _one_line(title),
            "status": status, "fields": fields, "tags": tags, "parent_ref": None, "parent_note": None,
            "related_refs": [], "source_path": source_path, "source_sha": sha, "notes": notes,
            "source_row": source_row}


def _unique(kind: str, seen: dict, ident: str, rel: str) -> None:
    if ident in seen:
        raise ValueError(f"{kind} {ident} is named by both {seen[ident]} and {rel}; an id is used once")
    seen[ident] = rel


# --- the roster, the sprint ledger, state and configured fields ------------------------------------------------

def _roster(root: Path) -> dict:
    text = _read_optional(root, root / ROSTER)
    try:
        data = yaml.safe_load(text) if text else None
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _assignee(roster: dict, handle, notes: list) -> str | None:
    """The sign-in identity of a roster handle, only through `validate_team.email_for`; None says nobody."""
    handle = str(handle or "").strip()
    if not bc.HANDLE_RE.fullmatch(handle):
        return None  # blank, a role or a name: there is no handle to look up
    email = email_for(roster, handle)
    if email:
        return email
    notes.append(f"no assignee: no email for {handle} on the roster ({ROSTER})")
    return None


def _carried(root: Path) -> dict[tuple[str, str], set[str]]:
    """`(spec id, sprint it was carried into) -> {the sprints it was carried out of}` from the sprint ledger."""
    out: dict[tuple[str, str], set[str]] = {}
    for line in (_read_optional(root, root / SPRINT_LOG) or "").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("event") != "carried":
            continue
        spec, came_from, into = (str(event.get(k) or "").strip() for k in ("spec", "sprint", "to_sprint"))
        if spec and SPRINT_ID_RE.fullmatch(came_from) and SPRINT_ID_RE.fullmatch(into):
            out.setdefault((spec, into), set()).add(came_from)
    return out


def _state(kind: str, status, cfg: dict, schema: dict, notes: list) -> str | None:
    """The process state a status resolves to, or None with a note: a state is never defaulted. `states` is
    narrowed to this kind (the caller that knows the kind), so two kinds on one type do not disagree."""
    if not status:
        return None
    type_name, why = resolve_type(schema, kind, cfg)
    if type_name is None:
        notes.append(f"state not set: {why}")
        return None
    rules = cfg.get("states")
    narrowed = {**cfg, "states": {kind: rules[kind]} if isinstance(rules, dict) and kind in rules else {}}
    name, reason = resolve_state(schema, type_name, _RULE_STATUS.get(kind, {}).get(status, status), narrowed)
    if name is None:
        notes.append(f"state not set: {reason}")
    return name


def _extra_fields(kind: str, raw: dict, cfg: dict, notes: list) -> dict:
    """The `fields.<kind>` entries of the config: the source value, through the `values` table when there is one."""
    rules = _dig(cfg, "fields", kind)
    out: dict = {}
    if not isinstance(rules, dict):
        return out
    for key in sorted(rules):
        rule = rules[key]
        if isinstance(rule, dict) and "value" in rule:
            continue  # a constant: no source value; `projections` writes it for every kind (`_constants`)
        ref = rule.get("field") if isinstance(rule, dict) else rule
        table = rule.get("values") if isinstance(rule, dict) else None
        if not isinstance(ref, str) or not ref.strip():
            continue
        if is_forbidden_field(key) or is_forbidden_field(ref) or ref.lower().startswith(SCHEDULING):
            notes.append(f"{kind}.{key} -> {ref} is not written: it names an activity metric the standard never tracks")
            continue
        value = rm.normalize_tier(raw.get(key)) if key == "risk" else _one_line(raw.get(key))
        if _blank(value):
            continue
        if isinstance(table, dict):
            if value not in table:
                notes.append(f"{kind}.{key} {value!r} has no entry in fields.{kind}.{key}.values; the field is not written")
                continue
            value = table[value]
        out[ref] = value
    return out


# --- documents: a markdown table, the epics file, the feature briefs -------------------------------------------

def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _table(text: str) -> list[dict]:
    """The rows of the first pipe table in `text`, each keyed by its header cell."""
    lines = [ln for ln in text.splitlines() if ln.lstrip().startswith("|")]
    if len(lines) < 2:
        return []
    header = _cells(lines[0])
    return [dict(zip(header, _cells(ln))) for ln in lines[2:]]


@functools.lru_cache(maxsize=None)
def _shape(stem: str) -> dict:
    return yaml.safe_load((SHAPES / f"{stem}.shape.yaml").read_text(encoding="utf-8"))


def _table_in(text: str, stem: str, label: str) -> list[dict]:
    """The table in the shape's `label` field, read with `document_shape.read_document`; [] when the document
    does not match its shape or the field is absent."""
    for block in read_document(text, _shape(stem)).get("blocks", []):
        field = (block.get("fields") or {}).get(label) if block.get("kind") == "section" else None
        if field:
            return _table(field["value"])
    return []


def _epics_path(root: Path) -> Path | None:
    for rel in (".sdlc/artifacts/01-requirements/epics.md", "epics.md"):
        if (root / rel).is_file():
            return root / rel
    artifacts = root / ".sdlc" / "artifacts"
    found = sorted(artifacts.rglob("epics.md")) if artifacts.is_dir() else []
    return found[0] if found else None


def _epic_records(root: Path) -> tuple[list[dict], str | None]:
    """`(epics, path)`: every `### EP-NNN:` heading and every Epic Summary row, merged by id. An epic with no
    real title (a template placeholder) is not an epic. Estimate and persona are never read into a field; each
    epic's `sha` covers its own heading block and summary row only, so editing one epic moves no other."""
    path = _epics_path(root)
    if path is None:
        return [], None
    text = _read(root, path)[0]
    where = _rel(root, path)
    heads: dict[str, dict] = {}
    head_at: dict[str, str] = {}
    for m in _EPIC_HEADING.finditer(text):
        ident = m.group(1).upper()
        _unique("epic", head_at, ident, f"{where} (a second heading)")
        nxt = _ANY_HEADING.search(text, m.end())
        body = text[m.end():nxt.start() if nxt else len(text)]
        priority, linked = _EPIC_PRIORITY.search(body), _EPIC_LINKED.search(body)
        heads[ident] = {"title": m.group(2), "priority": priority.group(1).upper() if priority else "",
                        "linked": "" if not linked or _blank(linked.group(1)) else _one_line(linked.group(1)),
                        "criteria": _epic_criteria(body),
                        "slice": text[m.start():nxt.start() if nxt else len(text)]}
    rows: dict[str, dict] = {}
    row_at: dict[str, str] = {}
    for row in _table_in(text, "epics", "Epic Summary"):
        ident = (row.get("Epic ID") or "").strip().upper()
        if not re.fullmatch(r"EP-[A-Z]*\d+", ident):
            continue
        _unique("epic", row_at, ident, f"{where} (a second Epic Summary row)")
        rows[ident] = row
    out = []
    for ident in sorted(set(heads) | set(rows), key=_natural):
        head, row = heads.get(ident, {}), rows.get(ident, {})
        title = next((t for t in (head.get("title"), row.get("Title")) if not _blank(t)), "")
        if not title:
            continue
        priority = head.get("priority") or (row.get("Priority") or "").strip().upper()
        fr_link = "" if _blank(row.get("FR Link")) else _one_line(row.get("FR Link"))
        own = head.get("slice", "") + "\n" + "|".join(f"{k}={v}" for k, v in row.items())
        out.append({"id": ident, "title": _one_line(title), "priority": priority if re.fullmatch(r"P\d", priority) else "",
                    "fr_link": fr_link or head.get("linked", ""), "criteria": head.get("criteria", ([], 0)),
                    "sha": _fingerprint(own.encode("utf-8"))})
    return out, where


def _epic_criteria(body: str) -> tuple[list[str], int]:
    """`(criteria, placeholders)` of an epic's `**Acceptance criteria:**` list: each item's text on one line, its
    checkbox and bold markers removed, in order; the list ends at the first line that is neither an item nor blank
    (the `**Definition of Done:**` label, a `---`). An item that still holds a template stand-in (`[condition]`;
    a markdown link is not one) is left out and counted, so the note can say how many. A CRLF checkout reads as the LF
    one (Git for Windows' autocrlf), so the field -- and the projection hash -- is the same on every machine."""
    body = body.replace("\r\n", "\n")
    found = _EPIC_CRITERIA.search(body)
    if not found:
        return [], 0
    items, placeholders = [], 0
    for line in body[found.end():].split("\n")[1:]:
        if not line.strip():
            continue
        item = _LIST_ITEM.match(line)
        if not item:
            break
        text = _one_line(item.group(1).replace("**", ""))
        if _STAND_IN.search(text) or _PLACEHOLDER.match(text):
            placeholders += 1
        elif not _blank(text):
            items.append(text)
    return items, placeholders


def _brief_paths(root: Path) -> list[Path]:
    artifacts = root / ".sdlc" / "artifacts"
    found: dict[Path, Path] = {}
    for path in [*(artifacts.rglob("feature-brief*.md") if artifacts.is_dir() else []), *root.glob("feature-brief*.md")]:
        if path.is_file():
            found.setdefault(path.resolve(), path)
    return sorted(found.values(), key=lambda p: _rel(root, p))


def _brief_header(text: str) -> dict | None:
    """`{"id", "title", "epic"}` from the first heading of a feature brief; None when it names no real feature
    (the unfilled template reads `<FE-NN>` and `[Feature title]`)."""
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    m = _BRIEF_H1.match(first)
    if not m:
        return None
    rest, epic = m.group(2), None
    em = _BRIEF_EPIC.search(rest)
    if em:
        epic, rest = em.group(1).strip(), rest[:em.start()]
    return None if _blank(rest) else {"id": m.group(1).upper(), "title": _one_line(rest), "epic": epic}


def _briefs(root: Path) -> list[dict]:
    """Every feature brief with a real header: `{id, title, epic, path, sha, text}`; one id twice is refused."""
    out, seen = [], {}
    for path in _brief_paths(root):
        text, sha = _read(root, path)
        head = _brief_header(text)
        if head is None:
            continue
        _unique("feature", seen, head["id"], _rel(root, path))
        out.append({**head, "path": _rel(root, path), "sha": sha, "text": text})
    return out


def _distinct(text, family: str) -> list[str]:
    """The ids of one family (`FE`, `EP`, `FR`) in `text`, in order, each once, as `FE-03`."""
    out: list[str] = []
    for m in ID_RE.finditer(str(text or "")):
        if m.group(1) == family and m.group(0).upper() not in out:
            out.append(m.group(0).upper())
    return out


# --- specs ------------------------------------------------------------------------------------------------------

def load_specs(repo_root, cfg: dict, schema: dict) -> list[dict]:
    root = Path(repo_root)
    roster, carried = _roster(root), _carried(root)
    traces = bool(_dig(cfg, "tree", "spec_traces"))
    briefs = {b["id"]: b for b in _briefs(root)} if traces else {}
    out, seen = [], {}
    for scanned in scan_specs(root / "specs"):
        path = Path(scanned["path"])
        text, sha = _read(root, path)
        fm = parse_frontmatter(text)[0]
        ident = str(scanned["id"]).strip()
        if not ident.isdigit():  # the legacy "????" id: a spec with no `spec:` key is named by its file
            m = SPEC_FILE_RE.match(path.name)
            if not m:
                continue
            ident = m.group(1)
        rel = _rel(root, path)
        _unique("spec", seen, ident, rel)
        status, notes = scanned["status"], []
        fields = {"System.Title": _title(ident, scanned["name"], notes)}
        state = _state("spec", status, cfg, schema, notes)
        if state:
            fields["System.State"] = state
        assignee = _assignee(roster, fm.get("developer"), notes)
        if assignee:
            fields["System.AssignedTo"] = assignee
        sprint = (fm.get("sprint") or "").strip()
        iteration = _dig(cfg, "iterations", sprint) if SPRINT_ID_RE.fullmatch(sprint) else None
        if isinstance(iteration, str) and iteration:
            fields[ITERATION] = iteration
        fields.update(_extra_fields("spec", fm, cfg, notes))
        tags = {f"sdlc:spec:{ident}", _tag("sdlc:status:", status), _tag("risk:", rm.normalize_tier(fm.get("risk"))),
                _tag("channel:", fm.get("channel")), _tag("eng-review:", normalize_review(fm.get("eng_review"))),
                _tag("data-review:", normalize_review(fm.get("data_review")))}
        tags |= {f"carried-from:{s}" for s in carried.get((ident, sprint), ())}
        row = _row("spec", ident, scanned["name"], status, fields, tags - {None}, rel, sha, notes, dict(fm))
        features = _distinct(fm.get("source"), "FE")
        if traces and len(features) == 1 and features[0] in briefs:
            row["related_refs"] = _spec_traces(briefs[features[0]], scanned["name"])
        out.append(row)
    return out


def _spec_traces(brief: dict, spec_name: str) -> list[str]:
    """The FRs in the `Traces to` cell of the brief's Spec decomposition row for this spec; a US id is not an FR."""
    for row in _table_in(brief["text"], "feature-brief", "Spec decomposition"):
        if _norm_name(row.get("Spec name")) == _norm_name(spec_name):
            return [f"sdlc:fr:{_suffix(fr)}" for fr in _distinct(row.get("Traces to"), "FR")]
    return []


def _raw_of(repo_root, row: dict) -> dict | None:
    """The raw source a resolver reads: the loader's `source_row`, else the file at `source_path` re-read."""
    if isinstance(row.get("source_row"), dict):
        return row["source_row"]
    root = Path(repo_root)
    try:
        path = root / str(row.get("source_path") or "")
        text = _read(root, path)[0] if path.is_file() else None
    except (OSError, ValueError):
        return None
    if text is None:
        return None
    if row.get("kind") == "feature":
        head = _brief_header(text)
        return None if head is None else {"epic": head["epic"]}
    return parse_frontmatter(text)[0]


def spec_parent(repo_root, row: dict) -> tuple[str | None, str | None]:
    """A spec's feature is the one `FE-NN` its `source:` names (D-OWNER-5, variant A); several are not guessed."""
    raw = _raw_of(repo_root, row)
    if raw is None:
        return None, "no parent: the spec file could not be read"
    features = _distinct(raw.get("source"), "FE")
    if not features:
        return None, "no parent: source names no FE-NN"
    if len(features) > 1:
        return None, f"no parent: source names several features ({', '.join(features)})"
    return f"sdlc:feature:{_suffix(features[0])}", None


# --- features and epics -----------------------------------------------------------------------------------------

def load_features(repo_root, cfg: dict, schema: dict) -> list[dict]:
    root = Path(repo_root)
    out = []
    for brief in _briefs(root):
        notes: list = []
        fields = {"System.Title": _title(brief["id"], brief["title"], notes)}
        out.append(_row("feature", brief["id"], brief["title"], None, fields, {f"sdlc:feature:{_suffix(brief['id'])}"},
                        brief["path"], brief["sha"], notes, {"epic": brief["epic"]}))
    return out


def feature_parent(repo_root, row: dict) -> tuple[str | None, str | None]:
    """A feature's epic is the `EP-NNN` its header names; with a name only, the one epic whose title is the
    same words; otherwise no parent and the reason."""
    raw = _raw_of(repo_root, row)
    epic = None if raw is None else raw.get("epic")
    if epic is None or not _one_line(epic):
        return None, "no parent: header names no epic"
    ids = _distinct(epic, "EP")
    if len(ids) == 1:
        return f"sdlc:epic:{_suffix(ids[0])}", None
    if len(ids) > 1:
        return None, f"no parent: header names several epics ({', '.join(ids)})"
    matches = [e for e in _epic_records(Path(repo_root))[0] if _norm_name(e["title"]) == _norm_name(epic)]
    if len(matches) == 1:
        return f"sdlc:epic:{_suffix(matches[0]['id'])}", None
    if matches:
        return None, f"no parent: header epic {_one_line(epic)!r} matches several epics ({', '.join(e['id'] for e in matches)})"
    return None, f"no parent: header epic {_one_line(epic)!r} matches no epic title"


def load_epics(repo_root, cfg: dict, schema: dict) -> list[dict]:
    root = Path(repo_root)
    records, rel = _epic_records(root)
    type_name = resolve_type(schema, "epic", cfg)[0] if records else None
    has_priority = type_name is not None and field_on_type(schema, type_name, PRIORITY) is not None
    has_criteria = type_name is not None and field_on_type(schema, type_name, ACCEPTANCE) is not None
    out = []
    for e in records:
        notes: list = []
        fields = {"System.Title": _title(e["id"], e["title"], notes)}
        if has_priority and e["priority"] in PRIORITY_VALUE:
            fields[PRIORITY] = PRIORITY_VALUE[e["priority"]]
        criteria, stand_ins = e["criteria"]
        if has_criteria and criteria:
            fields[ACCEPTANCE] = "<br>".join(html.escape(c, quote=False) for c in criteria)
        if has_criteria and stand_ins:
            notes.append(f"{stand_ins} acceptance criteri{'on' if stand_ins == 1 else 'a'} left out: "
                         "still a template stand-in")
        row = _row("epic", e["id"], e["title"], None, fields, {f"sdlc:epic:{_suffix(e['id'])}"}, rel, e["sha"], notes,
                   {"Epic ID": e["id"], "Title": e["title"], "Priority": e["priority"], "FR Link": e["fr_link"]})
        row["parent_note"] = NO_TREE  # replaced when the tree's resolver is registered
        out.append(row)
    return out


# --- decisions, sprints, spikes ---------------------------------------------------------------------------------

def load_decisions(repo_root, cfg: dict, schema: dict) -> list[dict]:
    root = Path(repo_root)
    path = next((p for p in (root / ".sdlc" / "decision-log.md", root / "decision-log.md") if p.is_file()), None)
    if path is None:
        return []
    _read(root, path)  # refuses a log that resolves outside the repository
    rel, roster = _rel(root, path), _roster(root)
    out, seen = [], {}
    for d in parse_decisions(path):
        ident = (d.get("id") or "").strip().upper()
        question = _RESOLUTION.sub("", d.get("decision") or "")
        if not _DECISION_ID.match(ident) or _blank(question):
            continue  # the template's example row, or a row with no question
        _unique("decision", seen, ident, rel)
        word = (d.get("status") or "").strip().lower()
        status = "open" if word not in CLOSED_STATUSES else ("decided" if word in _DECIDED else "closed")
        notes: list = []
        fields = {"System.Title": _title(ident, question, notes)}
        state = _state("decision", status, cfg, schema, notes)
        if state:
            fields["System.State"] = state
        assignee = _assignee(roster, d.get("owner"), notes)
        if assignee:
            fields["System.AssignedTo"] = assignee
        fields.update(_extra_fields("decision", d, cfg, notes))
        tags = {f"sdlc:decision:{_suffix(ident)}", _tag("sdlc:status:", status)}
        sha = _fingerprint(json.dumps(d, sort_keys=True).encode("utf-8"))  # this row only, not the whole log
        out.append(_row("decision", ident, question, status, fields, tags - {None}, rel, sha, notes, dict(d)))
    return out


def load_sprints(repo_root, cfg: dict, schema: dict) -> list[dict]:
    root = Path(repo_root)
    folder = root / ".sdlc" / "sprints"
    out = []
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        ident = path.stem
        if not SPRINT_ID_RE.fullmatch(ident):
            continue  # SNN.md, the template
        text, sha = _read(root, path)
        fm = parse_frontmatter(text)[0]
        status = (fm.get("state") or "planning").strip().lower()
        goal, notes = _one_line(fm.get("goal")), []
        fields = {"System.Title": _title(ident, goal, notes)}
        state = _state("sprint", status, cfg, schema, notes)
        if state:
            fields["System.State"] = state
        fields.update(_extra_fields("sprint", fm, cfg, notes))
        tags = {f"sdlc:sprint:{ident}", _tag("sdlc:status:", status)}
        out.append(_row("sprint", ident, goal or ident, status, fields, tags - {None}, _rel(root, path), sha, notes, dict(fm)))
    return out


def load_spikes(repo_root, cfg: dict, schema: dict) -> list[dict]:
    root = Path(repo_root)
    folder = root / "spikes"
    out, seen = [], {}
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        text, sha = _read(root, path)
        fm = parse_frontmatter(text)[0]
        ident = str(fm.get("spike") or "").strip()
        if not ident.isdigit():
            m = SPEC_FILE_RE.match(path.name)  # a spike is numbered like a spec: spikes/NNNN-name.md
            if not m or fm.get("spike"):
                continue  # a `spike:` that is not a number is the template's "NNNN"; no number at all is no spike
            ident = m.group(1)
        rel = _rel(root, path)
        _unique("spike", seen, ident, rel)
        h1 = _SPIKE_H1.search(text)
        question = h1.group(1) if h1 and not _blank(h1.group(1)) else fm.get("name")
        status, notes = (fm.get("status") or "open").strip().lower(), []
        fields = {"System.Title": _title(ident, question, notes)}
        state = _state("spike", status, cfg, schema, notes)
        if state:
            fields["System.State"] = state
        fields.update(_extra_fields("spike", fm, cfg, notes))
        tags = {f"sdlc:spike:{ident}", _tag("sdlc:status:", status)}
        out.append(_row("spike", ident, question, status, fields, tags - {None}, rel, sha, notes, dict(fm)))
    return out


# --- the registries and the one entry point ---------------------------------------------------------------------

SOURCES: dict = {"epic": load_epics, "feature": load_features, "spec": load_specs, "spike": load_spikes,
                 "sprint": load_sprints, "decision": load_decisions}
PARENT_RESOLVERS: dict = {"spec": spec_parent, "feature": feature_parent}


def _call(loader, root: Path, cfg: dict, schema: dict) -> list:
    """A loader written for `(repo_root)` is called with that alone; one that takes three, with all three."""
    try:
        params = list(inspect.signature(loader).parameters.values())
    except (TypeError, ValueError):
        params = []
    positional = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    wide = len(positional) >= 3 or any(p.kind is p.VAR_POSITIONAL for p in params)
    return list(loader(root, cfg, schema) if wide else loader(root))


def _checked(kind: str, row) -> dict:
    """A loader's row, completed and checked: the sheet's keys present, the ref well formed and of this kind."""
    if not isinstance(row, dict):
        raise ValueError(f"the source for kind {kind!r} returned a {type(row).__name__}, not a projection")
    missing = sorted(PINNED - set(row))
    if missing:
        raise ValueError(f"the source for kind {kind!r} returned a projection with no {', '.join(missing)}")
    if not bc.REF_RE.fullmatch(str(row["ref"])):
        raise ValueError(f"the source for kind {kind!r} returned the ref {row['ref']!r}, which is not sdlc:<kind>:<id>")
    if row["kind"] != kind:
        raise ValueError(f"the source for kind {kind!r} returned a projection of kind {row['kind']!r}")
    row = dict(row)
    row["tags"], row["related_refs"] = set(row["tags"]), list(row["related_refs"])
    row.setdefault("notes", [])
    return row


def _resolve(kind: str, resolver, root: Path, row: dict) -> None:
    """Write a resolver's answer into `row`: `(parent_ref, note)`, or `(parent_ref, note, related_refs)` whose refs
    are appended to the row's own `related_refs` (each once, in order). A ref that is not `sdlc:<kind>:<id>` is a
    ValueError naming the resolver's kind and the row."""
    answer = tuple(resolver(root, dict(row)))  # a copy: `source_row` is dropped by the caller
    if len(answer) not in (2, 3):
        raise ValueError(f"the parent resolver for kind {kind!r} returned {len(answer)} values for {row['ref']}; it "
                         "answers (parent_ref, note) or (parent_ref, note, related_refs)")
    row["parent_ref"], row["parent_note"] = answer[0], answer[1]
    if row["parent_ref"] is not None and not bc.REF_RE.fullmatch(str(row["parent_ref"])):
        raise ValueError(f"the parent resolver for kind {kind!r} returned {row['parent_ref']!r} for "
                         f"{row['ref']}, which is not sdlc:<kind>:<id>")
    related = list(answer[2] or []) if len(answer) == 3 else []
    for ref in related:
        if not bc.REF_RE.fullmatch(str(ref)):
            raise ValueError(f"the parent resolver for kind {kind!r} returned the related ref {ref!r} for "
                             f"{row['ref']}, which is not sdlc:<kind>:<id>")
    row["related_refs"] = list(dict.fromkeys([*row["related_refs"], *(str(r) for r in related)]))


def projections(repo_root, cfg: dict, schema: dict, kinds: list[str]) -> list[dict]:
    """One projection per item of each kind, kinds in the order asked (each once), items in id order.

    `cfg` is the parsed `.sdlc/ado.yaml` and `schema` the discovered process; either may be `{}`/None when
    the caller has neither (the parts that need them are left out and noted). A kind the module does not know,
    or one no package has registered a source for, is a ValueError naming it, never an empty answer."""
    root, cfg, schema = Path(repo_root), cfg or {}, schema or {}
    if not isinstance(cfg, dict) or not isinstance(schema, dict):
        raise ValueError("cfg and schema must each be a mapping (the parsed .sdlc/ado.yaml and .sdlc/ado/schema.json)")
    wanted = list(dict.fromkeys(kinds))
    for kind in wanted:
        if kind not in bc.KINDS:
            raise ValueError(f"unknown kind {kind!r}; the kinds are {', '.join(bc.KINDS)}")
        if kind not in SOURCES:
            raise ValueError(f"kind {kind!r} has no source loaded (SOURCES has: {', '.join(sorted(SOURCES))})")
    out: list[dict] = []
    rides = _Rides(root, cfg, schema)
    for kind in wanted:
        resolver = PARENT_RESOLVERS.get(kind)
        constants = _constants(kind, cfg)
        rows = []
        for raw in _call(SOURCES[kind], root, cfg, schema):
            row = _checked(kind, raw)
            if resolver is not None:
                _resolve(kind, resolver, root, row)
            row.pop("source_row", None)
            _apply_constants(kind, row, constants)
            rides.apply(row)
            rows.append(row)
        out.extend(sorted(rows, key=lambda r: _natural(r["id"])))
    return out


# --- constants and the tree kinds that ride as tags ---------------------------------------------------------------

def _constants(kind: str, cfg: dict) -> dict:
    """`{reference name: value}` of the kind's constant rules, `fields.<kind>.<key>: {field, value}`: a value no
    artifact carries (a process's always-required ValueArea, say), written verbatim. A rule naming an activity metric
    or a scheduling field is left out here as in `_extra_fields` (`config check` refuses it, and a refused config
    plans nothing)."""
    rules = _dig(cfg, "fields", kind)
    out: dict = {}
    for key in sorted(rules) if isinstance(rules, dict) else []:
        rule = rules[key]
        if not (isinstance(rule, dict) and "value" in rule and "values" not in rule):
            continue
        ref, value = rule.get("field"), rule.get("value")
        if (not isinstance(ref, str) or not ref.strip() or isinstance(value, (dict, list)) or value is None
                or is_forbidden_field(key) or is_forbidden_field(ref) or ref.lower().startswith(SCHEDULING)):
            continue
        out[ref.strip()] = value
    return out


def _apply_constants(kind: str, row: dict, constants: dict) -> None:
    """Write each constant into the row's `fields` and name it in `constant_fields`, which `ado_sync_model` reads: a
    constant is set at create and filled on update only while the board's field is empty, and a board-side change to it
    is the board's (never drift). The repository's own value wins: a field the source already set keeps it, noted."""
    applied = []
    for ref, value in constants.items():
        if ref in row["fields"]:
            row["notes"].append(f"fields.{kind} constant for {ref} not used: the source sets {ref} itself")
            continue
        row["fields"][ref] = value
        applied.append(ref)
    if applied:
        row["constant_fields"] = sorted(applied)


RIDE_SEGMENTS = {"outcome": "outcome", "domain": "domain", "fr": "requirement"}  # a ref's segment -> its tree kind


def ride_fit(cfg: dict, schema: dict) -> dict:
    """`{tree kind: its fit entry}` (`ado_schema_map.fit_levels`) for the requirements-tree kinds this config mirrors
    (`configured_kinds`); {} when it mirrors none. Only a kind fitted as `tag` (or `area`) rides."""
    kinds = [k for k in bc.RIDE_TAG_PREFIXES if k in configured_kinds(cfg)]
    if not kinds:
        return {}
    fit = fit_levels(schema or {}, cfg or {})
    return {k: fit[k] for k in kinds}


def ride_tag(ref, fits: dict) -> str | None:
    """The tag a requirements-tree ref rides as on the item that points at it -- `sdlc:domain:order-intake` ->
    `domain:order-intake`, `sdlc:fr:001` -> `fr:001`, `sdlc:outcome:1-turnaround-time` -> `outcome:1-turnaround-time`
    -- when its kind is mirrored and fitted as a tag (`fits` is `ride_fit`); None when it is an item, its fit is not
    known (backlog levels never read), or it is not a tree ref. A domain fitted to an Area Path also rides as its tag:
    setting `System.AreaPath` from the fit is not implemented, and the item says so (`_Rides`)."""
    parts = str(ref or "").split(":")
    kind = RIDE_SEGMENTS.get(parts[1]) if len(parts) == 3 and parts[0] == "sdlc" else None
    entry = fits.get(kind) if kind else None
    if not isinstance(entry, dict) or entry.get("mode") not in ("tag", "area"):
        return None
    return f"{bc.RIDE_TAG_PREFIXES[kind]}{parts[2]}"


def _domain_slug(name: str) -> str:
    """The slug `ado_sync_sources_tree` makes of a domain name, so a configured name matches the ref it names."""
    folded = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")


class _Rides:
    """The tags a projection gains for the tree kinds that ride (design D36 on a process with nothing above Epic): for
    its parent and each `Related` ref of a riding kind, that ref's tag; and for each domain that rides, the tag of each
    outcome the domain maps to (`ado_sync_sources_tree.load_domains`: `tree.domain_outcomes` and the Summary Table's
    Outcome column, never inferred) when outcomes ride too -- the domain has no item to carry that edge. The fit and the
    domain map are read once per `projections` call, and only when a row points at a riding kind."""

    def __init__(self, root: Path, cfg: dict, schema: dict):
        self.root, self.cfg, self.schema = root, cfg, schema
        self._fits = None
        self._outcomes = None
        self._why_not = None  # why the domain -> outcome map could not be read (the row says so; nothing is guessed)

    @property
    def fits(self) -> dict:
        if self._fits is None:
            self._fits = ride_fit(self.cfg, self.schema)
        return self._fits

    def outcomes_of(self, domain_ref: str) -> list[str]:
        """The outcome refs a domain maps to. A map that contradicts the artifacts (`tree.domain_outcomes` naming a
        domain or an outcome nobody defined) adds no outcome tag and leaves the reason in `_why_not`: the domain and
        FR tags still ride, and `plan --kind domain` stops on the same contradiction."""
        if self._outcomes is None:
            tree = importlib.import_module("ado_sync_sources_tree")  # lazily: importing it registers it
            try:
                domains = tree.load_domains(self.root, self.cfg)
            except ValueError as exc:
                domains, self._why_not = [], str(exc)
            self._outcomes = {d["ref"]: [r for r in [d["parent_ref"], *d["related_refs"]] if r] for d in domains}
        return self._outcomes.get(domain_ref, [])

    def apply(self, row: dict) -> None:
        refs = [str(r) for r in [row.get("parent_ref"), *row.get("related_refs", [])] if r]
        if not any(r.split(":")[1] in RIDE_SEGMENTS for r in refs if r.count(":") == 2) or not self.fits:
            return  # no tree ref on the row (most rows): the fit is not even computed
        tags: list[str] = []
        for ref in refs:
            tag = ride_tag(ref, self.fits)
            if tag is None:
                continue
            tags.append(tag)
            if not ref.startswith("sdlc:domain:"):
                continue
            area = self._area_path(ref)
            if area:
                row["notes"].append(f"{ref} matches the Area Path {area}, but setting System.AreaPath from the fit is "
                                    f"not implemented; it rides as the tag {tag}")
            if (self.fits.get("outcome") or {}).get("mode") == "tag":  # an outcome item would hold the edge itself
                tags += [t for t in (ride_tag(o, self.fits) for o in self.outcomes_of(ref)) if t]
                if self._why_not:
                    row["notes"].append(f"no outcome tags for {ref}: {self._why_not}")
        row["tags"] = set(row["tags"]) | set(tags)

    def _area_path(self, domain_ref: str) -> str | None:
        entry = self.fits.get("domain") or {}
        if entry.get("mode") != "area":
            return None
        slug = domain_ref.split(":", 2)[2]
        return next((v.get("area_path") for name, v in (entry.get("names") or {}).items()
                     if isinstance(v, dict) and v.get("mode") == "area" and _domain_slug(name) == slug), None)
