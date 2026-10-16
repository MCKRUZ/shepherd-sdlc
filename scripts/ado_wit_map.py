"""The PURE half of the work-item mirror: a board row in, a patch, a query or a verdict out (B2-P1).

`ado_wit.py` (B2-P2 reads, B3-P1 writes) moves documents between `az` and the repository; everything in this
module is a function of documents and imports no I/O module (nothing that reaches `az`, spawns a process or
touches a file), so the whole translation is tested on fixture JSON. It is a library part, usable two ways like every
part of the plugin:

  * Workflow mode — `ado_sync.py --state .sdlc/state.yaml …` reads the board with `ado_wit`, hands each row to
    `remote_item`, compares it with the repository's projection through `ado_sync_model.diff`, and (from B3) turns
    the difference into a patch with `build_update_patch`.
  * Standalone — a test, a notebook or another script passes a row and a projection as plain dicts; nothing here
    needs a `.sdlc/` directory and nothing here writes one.

What it does, and the rules it keeps:

  * `remote_item` — a `wit/workitems` row (or `az boards work-item show`) into the small document the sync model
    compares. A key the mapping NEEDS raises `AdoImportError("unexpected az shape: missing …")` through
    `ado_map._require` instead of defaulting. It carries NO identity (an assignee is a roster handle or None, never
    a name or an address), no GUID, no relation URL, and no effort value: a field whose value is a person, a
    comment (`System.History`) or an estimate is left out of `fields`, never read.
  * `build_update_patch` — the JSON patch an update would send. Which fields change is decided ONCE, by
    `ado_sync_model.diff` (the repository owns a field only where `OWNERSHIP` says so; a value equal after
    normalising — a case-folded e-mail, the same tag set in another order — is no op), so a plan and the apply that
    follows it cannot disagree. The first op is always `test /rev`: a board edit between read and write makes the
    patch fail as a conflict instead of overwriting the edit. A field the row carries no value for is not compared
    (the board may not have that field at all), and a `None` projection value is "no value", never "blank it".
  * `merge_tags` / `merge_description` — the two shared fields are read, merged and replaced, never overwritten:
    only the plugin-prefixed tags and only the text between the `<!-- sdlc:begin -->` / `<!-- sdlc:end -->` markers
    are the repository's; every other tag and every byte outside the markers is a person's and survives.
  * `build_create_patch` — the patch a create would send: the projection's fields, the configured `area_path`
    (`with_create_fields`; create-time only), the merged tags, the History line, a hyperlink back to the source file
    and (when known) the parent link. No `test` op: there is no revision yet.
  * `wiql_ref_lookup` / `wiql_untagged` / `project_clause` — the WIQL the mirror runs, scoped by the project's NAME
    as a literal (never the current-project macro, which `az boards query` answered with zero bytes). Every value
    that reaches the query text is whitelisted first and a quote is doubled, so a path, a ref or a project name can
    never end the string it sits in.
  * `classify_write_error` — a failed write sorted into a CLOSED enum (`ERROR_CLASSES`); anything not recognised is
    `unknown`, never guessed. `describe_write_error` says, for a `rule`, which patch field it named and why
    (`RULE_REASONS`), never with the board's own words.
  * `file_hyperlink` / `work_item_url` — the two URLs a work item and its parent are linked by.

Effort fields (`Microsoft.VSTS.Scheduling.*`, and the backlog's own effort field) and the read-only fields
(bookkeeping, `System.History`) are REFUSED with `ValueError`, not dropped: a comment written through a field would
skip the comment gate, and an estimate is never the mirror's to write.
"""

import re
from urllib.parse import quote

from ado_map import AdoImportError, _require
from ado_schema_map import refused_fields
from ado_sync_model import (BOOKKEEPING_FIELDS, BOOKKEEPING_PREFIXES, FORBIDDEN_FIELD_PREFIXES, HISTORY_FIELD,
                            IDENTITY_FIELDS, MARKER_BEGIN, MARKER_END, PARENT_REL, diff, ownership_for)
from boards_contract import EMAIL_RE, GUID_RE, HANDLE_RE, PLUGIN_TAG_PREFIXES, REF_RE
from code_host_remote import RemoteInfo

HYPERLINK_REL = "Hyperlink"
HYPERLINK_COMMENT = "source file"
REPO_TAG_PREFIX = "sdlc-repo:"  # the tag that says "this repository owns the item"; one of PLUGIN_TAG_PREFIXES
ERROR_CLASSES = ("conflict", "rule", "permission", "throttled", "not_found", "unknown")

_TAGS = "System.Tags"
_DESCRIPTION = "System.Description"
_TITLE = "System.Title"
_FIELDS = "/fields/"
_WORK_ITEM_TAIL = re.compile(r"/workItems/(\d+)$")
_ITEM_URL = re.compile(r"https://\S+/_apis/wit/workItems/\d+")
_HTTPS_URL = re.compile(r"https://\S+")
_PATH_OK = re.compile(r"[A-Za-z0-9 \\._-]+")  # a classification path: words, spaces, backslash, dot, dash, underscore
_SLUG_OK = re.compile(r"[A-Za-z0-9._-]+")
_REF_OK = re.compile(r"[A-Za-z0-9:-]+")
_SHA_OK = re.compile(r"[0-9a-f]{7,64}")
_EFFORT_PREFIXES = tuple(p.lower() for p in FORBIDDEN_FIELD_PREFIXES)


# --- small readers --------------------------------------------------------------------------------------------

def _integer(value, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdoImportError(f"unexpected az shape: {what} is not an integer")
    return value


def _control(text: str) -> bool:
    return any(ord(c) < 32 or ord(c) == 127 for c in text)


def _split_tags(value) -> list[str]:
    """The tags of a `System.Tags` string (`;`-separated) or of any iterable, trimmed, de-duplicated, in order."""
    if value is None:
        return []
    parts = value.split(";") if isinstance(value, str) else [str(t) for t in value]
    out: list[str] = []
    for part in parts:
        tag = part.strip()
        if tag and tag not in out:
            out.append(tag)
    return out


def _plugin_tags(value) -> set[str]:
    return {t for t in _split_tags(value) if t.startswith(PLUGIN_TAG_PREFIXES)}


def _is_effort(ref: str) -> bool:
    return ref.lower().startswith(_EFFORT_PREFIXES)


def _is_read_only(ref: str) -> bool:
    return ref in BOOKKEEPING_FIELDS or ref.startswith(BOOKKEEPING_PREFIXES) or ref == HISTORY_FIELD


def _assignee_email(value) -> str | None:
    """The lower-cased address of an `AssignedTo` value: an identity dict (`uniqueName`) or the native
    `Name <address>` / bare-address string. Used to look a handle up and then thrown away."""
    if isinstance(value, dict):
        raw = value.get("uniqueName")
    elif isinstance(value, str):
        tail = re.search(r"<([^<>]+)>\s*$", value)
        raw = tail.group(1) if tail else value
    else:
        return None
    raw = raw.strip() if isinstance(raw, str) else ""
    return raw.lower() if EMAIL_RE.fullmatch(raw) else None


def _handle(value, roster_emails: dict[str, str] | None) -> str | None:
    email = _assignee_email(value)
    if email is None or not roster_emails:
        return None
    handle = {str(k).lower(): v for k, v in roster_emails.items()}.get(email)
    return handle if isinstance(handle, str) and HANDLE_RE.fullmatch(handle) else None


def _relation(raw) -> dict:
    """A relation as ids and names: the work item it points at (None for an attachment, a pull request or an
    external link), the name the board gave it, and — for a hyperlink only — the URL the repository wrote."""
    rel = _require(raw, "rel", "work item.relations[]")
    url = raw.get("url")
    attributes = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {}
    tail = _WORK_ITEM_TAIL.search(url) if isinstance(url, str) else None
    out = {"rel": rel, "target": int(tail.group(1)) if tail else None, "name": attributes.get("name")}
    if rel == HYPERLINK_REL and isinstance(url, str):
        out["url"] = url
    return out


def remote_item(row: dict, roster_emails: dict[str, str] | None = None) -> dict:
    """A work item row into the document `ado_sync_model` compares:
    `{"id", "rev", "type", "state", "assigned_to_handle", "iteration", "area", "tags": set, "title",
    "relations": [{"rel", "target", "name"}], "fields": {ref: value}}`.

    `roster_emails` is `{lower-case address: @handle}` (`validate_team.people_by_email`); without it, or for an
    assignee who is not on it, `assigned_to_handle` is None — a handle is never made up from a name. `fields` holds
    the scalar fields the row carries (the description, a custom field, the priority), so the model can compare the
    repository-owned ones; it leaves out every identity-typed value, `System.History` and every effort field.
    `relations` is `[]` when the row has none (the board omits the key then) — the batch read always expands them."""
    item_id = _integer(_require(row, "id", "work item"), "work item.id")
    rev = _integer(_require(row, "rev", "work item"), "work item.rev")
    raw_fields = _require(row, "fields", "work item")
    relations = row.get("relations") or []
    if not isinstance(raw_fields, dict) or not isinstance(relations, list):
        raise AdoImportError("unexpected az shape: work item.fields is not an object or work item.relations is "
                             "not a list")
    scalar = {ref: value for ref, value in raw_fields.items()
              if not isinstance(value, dict) and ref not in IDENTITY_FIELDS and ref != HISTORY_FIELD
              and not _is_effort(ref)}
    return {
        "id": item_id,
        "rev": rev,
        "type": _require(raw_fields, "System.WorkItemType", "work item.fields"),
        "state": _require(raw_fields, "System.State", "work item.fields"),
        "assigned_to_handle": _handle(raw_fields.get("System.AssignedTo"), roster_emails),
        "iteration": _require(raw_fields, "System.IterationPath", "work item.fields"),
        "area": _require(raw_fields, "System.AreaPath", "work item.fields"),
        "tags": set(_split_tags(raw_fields.get(_TAGS))),
        "title": _require(raw_fields, _TITLE, "work item.fields"),
        "relations": [_relation(r) for r in relations],
        "fields": scalar,
    }


# --- the two shared fields: read, merge, replace --------------------------------------------------------------

def merge_tags(existing: str | None, plugin_tags: set[str]) -> str:
    """The tags a write sends: every tag the board holds that is NOT plugin-prefixed (a person's), plus exactly
    `plugin_tags` (the repository's — a plugin tag it no longer wants is withdrawn). `; `-joined and sorted.
    A `plugin_tags` member that is not plugin-prefixed, or that would add a second tag through a `;`, raises."""
    wanted = set()
    for tag in plugin_tags:
        if (not isinstance(tag, str) or tag != tag.strip() or ";" in tag or _control(tag)
                or not tag.startswith(PLUGIN_TAG_PREFIXES)):
            raise ValueError(f"not a plugin tag the mirror may write: {tag!r} (it must start with one of "
                             f"{', '.join(PLUGIN_TAG_PREFIXES)} and be a single tag)")
        wanted.add(tag)
    kept = {t for t in _split_tags(existing) if not t.startswith(PLUGIN_TAG_PREFIXES)}
    return "; ".join(sorted(kept | wanted))


def _inner(block) -> str:
    """The text of a block to put between the markers: the inside of a marker-wrapped block, else the block."""
    text = "" if block is None else str(block)
    begin, end = text.find(MARKER_BEGIN), text.find(MARKER_END)
    if begin >= 0 or end >= 0:
        if begin < 0 or end < begin + len(MARKER_BEGIN):
            raise ValueError("the block's sdlc markers do not pair up (a begin marker and a later end marker)")
        text = text[begin + len(MARKER_BEGIN):end]
    if MARKER_BEGIN in text or MARKER_END in text:
        raise ValueError("the block contains an sdlc marker of its own; it would break the markers around it")
    return text.strip()


def merge_description(existing_html: str | None, block: str) -> str:
    """The description a write sends: `block` between the sdlc markers, and every byte outside them untouched.
    No markers yet: the block is appended after whatever a person wrote. Unpaired markers raise rather than guess
    where a person's text ends. With several pairs, the first is the repository's."""
    wrapped = f"{MARKER_BEGIN}{_inner(block)}{MARKER_END}"
    text = "" if existing_html is None else str(existing_html)
    begin = text.find(MARKER_BEGIN)
    end = text.find(MARKER_END, begin + len(MARKER_BEGIN)) if begin >= 0 else text.find(MARKER_END)
    if begin < 0 and end < 0:
        return text + wrapped if text.strip() else wrapped
    if begin < 0 or end < 0:
        raise ValueError("the work item's description has unpaired sdlc markers; fix it by hand before the "
                         "mirror writes to it")
    return text[:begin] + wrapped + text[end + len(MARKER_END):]


# --- patches ------------------------------------------------------------------------------------------------

def _check_fields(fields: dict, refused: frozenset[str]) -> None:
    for ref in fields:
        if _is_effort(ref) or ref in refused:
            raise ValueError(f"{ref}: effort fields (points, estimates, hours) are never written")
        if _is_read_only(ref):
            raise ValueError(f"{ref} is a read-only field; the mirror does not write it (comments go through "
                             "the comment gate)")


def has_changes(patch: list[dict]) -> bool:
    """True when a patch holds any op besides the `test /rev` precondition."""
    return any(op.get("op") != "test" for op in patch)


def build_update_patch(remote: dict, projection: dict) -> list[dict]:
    """`[{"op": "test", "path": "/rev", "value": <rev>}, *field ops]` for an item `remote_item` read.

    The field ops are exactly `ado_sync_model.diff(projection, remote, ownership_for(kind))`, sorted by path; Tags
    and Description are re-expressed as the merge of the board's current value and the repository's (a person's
    tags and the text outside the markers survive). A patch of the test op alone changes nothing — see
    `has_changes`. Raises `AdoImportError` for a remote with no integer `rev`, `ValueError` for an effort or a
    read-only field in the projection."""
    rev = _integer(_require(remote, "rev", "remote item"), "remote item.rev")
    fields = projection.get("fields") or {}
    _check_fields(fields, frozenset())
    held = remote.get("fields") if isinstance(remote.get("fields"), dict) else {}
    patch = [{"op": "test", "path": "/rev", "value": rev}]
    for op in diff(projection, remote, ownership_for(projection.get("kind"))):
        ref, new = op["path"][len(_FIELDS):], op["new"]
        if ref == _TAGS:
            value = merge_tags("; ".join(sorted(remote.get("tags") or ())), _plugin_tags(projection.get("tags")))
            if set(_split_tags(value)) == set(remote.get("tags") or ()):
                continue
        elif new is None:
            continue  # no value is not an instruction to blank the field
        elif ref == _DESCRIPTION:
            value = merge_description(held.get(_DESCRIPTION), new)
            if value == held.get(_DESCRIPTION):
                continue
        else:
            value = new
        patch.append({"op": op["op"], "path": op["path"], "value": value})
    return patch


def _history(line) -> str:
    if not isinstance(line, str) or not line.strip():
        raise ValueError("the history line is empty; a create records where the item came from")
    if EMAIL_RE.search(line) or GUID_RE.search(line):
        raise ValueError("the history line carries an e-mail address or a GUID; it is board-visible prose")
    return line


def _hyperlink(url) -> str:
    if not isinstance(url, str) or not _HTTPS_URL.fullmatch(url):
        raise ValueError("the hyperlink must be an https URL without spaces")
    return url


def _parent(url) -> str | None:
    if url is None:
        return None
    if not isinstance(url, str) or not _ITEM_URL.fullmatch(url):
        raise ValueError("the parent url must be a work item URL (https://…/_apis/wit/workItems/<id>)")
    return url


AREA_PATH = "System.AreaPath"


def configured_area(cfg) -> str | None:
    """The `.sdlc/ado.yaml` `area_path` a create sets, trimmed, or None when none is configured (absent or blank)."""
    area = cfg.get("area_path") if isinstance(cfg, dict) else None
    return area.strip() if isinstance(area, str) and area.strip() else None


def with_create_fields(projection: dict, area_path: str | None) -> dict:
    """`projection` with the fields a create also sets that no source supplies: `System.AreaPath` from the config's
    `area_path` (`.sdlc/ado.yaml`, "create-time only"), unless the projection already names an area. A copy when
    anything is added, else `projection` itself; the projection's own hash is not this copy's (the area is the
    config's, and an update never sends it: `System.AreaPath` is `C` in `OWNERSHIP`, the board's once created, so a
    board-side move is the board's call, never drift). Without it the first live apply (B0, 2026-10-15) put every
    created item at the project root, outside the team's board. Raises `ValueError` for an area that is not one line
    of text."""
    if area_path is None:
        return projection
    if not isinstance(area_path, str) or not area_path.strip() or area_path != area_path.strip() or _control(area_path):
        raise ValueError(f"area_path {area_path!r} is not an area path (one line of text, no surrounding spaces)")
    fields = projection.get("fields") or {}
    if AREA_PATH in fields:
        return projection
    return {**projection, "fields": {**fields, AREA_PATH: area_path}}


def build_create_patch(projection: dict, schema: dict, hyperlink: str, history_line: str,
                       parent_url: str | None, *, area_path: str | None = None) -> list[dict]:
    """The JSON patch a create sends: an `add` per projection field (what `ado_sync_model.diff` calls a push to an
    item that does not exist yet), `System.AreaPath` when `area_path` is configured (`with_create_fields`), the
    plugin tags only, the description inside the markers, then the History line, the source `hyperlink` and the
    parent link when `parent_url` is known. `schema` names the effort fields to refuse; whether a field exists on the
    type is `plan --validate`'s question, not this one. Raises `ValueError` for an effort or read-only field, a
    projection with no title, or a line, link, URL or area that is not what its name says."""
    projection = with_create_fields(projection, area_path)
    fields = projection.get("fields") or {}
    _check_fields(fields, refused_fields(schema))
    title = fields.get(_TITLE)
    if not isinstance(title, str) or not title.strip():
        raise ValueError(f"the projection has no {_TITLE}; a work item cannot be created without one")
    history, link, parent = _history(history_line), _hyperlink(hyperlink), _parent(parent_url)
    ops = []
    for op in diff(projection, None):
        ref, value = op["path"][len(_FIELDS):], op["new"]
        if ref == _TAGS or value is None:
            continue  # tags come from the projection's tag set below; no value is not a value
        if ref == _DESCRIPTION:
            if not str(value).strip():
                continue
            _inner(value)  # unpaired markers raise
            value = str(value) if MARKER_BEGIN in str(value) else merge_description(None, value)
        ops.append({"op": "add", "path": op["path"], "value": value})
    tags = _plugin_tags(projection.get("tags"))
    if tags:
        ops.append({"op": "add", "path": f"{_FIELDS}{_TAGS}", "value": merge_tags(None, tags)})
    ops.sort(key=lambda o: o["path"])
    ops.append({"op": "add", "path": f"{_FIELDS}{HISTORY_FIELD}", "value": history})
    ops.append({"op": "add", "path": "/relations/-",
                "value": {"rel": HYPERLINK_REL, "url": link, "attributes": {"comment": HYPERLINK_COMMENT}}})
    if parent:
        ops.append({"op": "add", "path": "/relations/-",
                    "value": {"rel": PARENT_REL, "url": parent, "attributes": {"name": "Parent"}}})
    return ops


# --- WIQL ---------------------------------------------------------------------------------------------------

# No `[System.TeamProject] = @project`: `az boards query` with that macro printed zero bytes (exit 0) on a board where
# items matched (B0, 2026-10-15); the literal project name returned the rows. So the project is named as a literal
# (`project_clause`), and `az boards query --project` scopes the call as before.
_WIQL_SELECT = ("SELECT [System.Id],[System.WorkItemType],[System.Title],[System.State],[System.Tags],"
                "[System.AssignedTo] FROM WorkItems")
# A project name: letters and digits of any script, space and the punctuation Azure DevOps allows in one, but no
# quote, bracket, backslash or control character (the doubling in `_literal` stays the second lock). `%` and `!`
# are refused as well: on Windows `az` resolves to `az.cmd`, cmd.exe re-parses the argv, and `%VAR%` / `!VAR!`
# would be expanded inside the quoted WIQL (security review of PR #5, 2026-10-16).
_PROJECT_OK = re.compile(r"[\w .()&~^@-]+")


def _literal(value, pattern: re.Pattern, what: str) -> str:
    """A value for inside a WIQL string literal: whitelisted whole, then any quote doubled (the whitelist already
    refuses one — the doubling is the second lock)."""
    if not isinstance(value, str) or value != value.strip() or not pattern.fullmatch(value):
        raise ValueError(f"{what} {value!r} is outside the whitelist for a WIQL string "
                         f"({pattern.pattern}); it is never put in a query")
    return value.replace("'", "''")


def project_clause(project: str | None) -> str | None:
    """`[System.TeamProject] = '<project>'` for the remote's project NAME (whitelisted, quotes doubled), or None when
    no project is given (the query is then scoped by `az boards query --project` alone). Never the WIQL macro."""
    if project is None:
        return None
    return f"[System.TeamProject] = '{_literal(project, _PROJECT_OK, 'project')}'"


def _where(*conditions: str | None) -> str:
    present = [c for c in conditions if c]
    return f" WHERE {' AND '.join(present)}" if present else ""


def wiql_ref_lookup(ref: str, project: str | None = None) -> str:
    """The query that finds the work items tagged with one `sdlc:<kind>:<id>` ref, in `project` when given."""
    if not isinstance(ref, str) or not REF_RE.fullmatch(ref):
        raise ValueError(f"{ref!r} is not an sdlc:<kind>:<id> ref; it is never put in a query")
    return _WIQL_SELECT + _where(project_clause(project), f"[System.Tags] CONTAINS '{_literal(ref, _REF_OK, 'ref')}'")


def wiql_untagged(area_paths: list[str], iteration_paths: list[str], repo_slug: str, project: str | None = None) -> str:
    """The query that finds the items under the mirror's area or iteration paths that this repository has not
    tagged (`sdlc-repo:<slug>`): the candidates for `link` and `adopt`, in `project` when given. It selects
    `[System.AssignedTo]` so an unmapped item shows who holds it. Paths, the slug and the project are whitelisted (a
    quote or a `]` is refused); with no path at all it raises, since an unscoped query would read the whole project."""
    for paths in (area_paths, iteration_paths):
        if isinstance(paths, (str, bytes)) or not isinstance(paths, (list, tuple)):
            raise ValueError("area and iteration paths are lists of paths, not a single string")
    areas = dict.fromkeys(_literal(p, _PATH_OK, "area path") for p in area_paths)
    iterations = dict.fromkeys(_literal(p, _PATH_OK, "iteration path") for p in iteration_paths)
    clauses = [f"[System.AreaPath] UNDER '{p}'" for p in areas]
    clauses += [f"[System.IterationPath] UNDER '{p}'" for p in iterations]
    if not clauses:
        raise ValueError("no area or iteration path to search under; an unscoped query would read the whole project")
    slug = _literal(repo_slug, _SLUG_OK, "repository slug")
    return _WIQL_SELECT + _where(project_clause(project), f"({' OR '.join(clauses)})",
                                 f"NOT [System.Tags] CONTAINS '{REPO_TAG_PREFIX}{slug}'")


# --- write errors -------------------------------------------------------------------------------------------

def _status(code: int) -> str:
    """An HTTP status in the places `az` prints one (`HTTP 409`, `status code: 409`, `(409 …)`) — never a bare
    number, which may be a work item id."""
    return rf"(?:\bhttp(?:/\d(?:\.\d)?)?|\bstatus(?: code)?|\()\D{{0,6}}{code}\b"


def _any(*patterns: str) -> re.Pattern:
    return re.compile("|".join(patterns), re.IGNORECASE)


# Checked in this order: a stale revision and a throttle are named by their own words, "does not exist, or you do
# not have permissions to read it" is a missing item (not a refused write), and a rule error is the last specific
# reading before `unknown`. The wording was first taken from the REST reference and the known TF/VS codes; the B0
# capture of 2026-10-15 added what a real board answers (`captured/errors/` under the test fixtures):
#   * a stale `test /rev` through `az rest`: `Precondition Failed(… VS403351: Test Operation for path /rev failed …
#     "typeKey":"TestPatchOperationFailedException" …)` -> conflict;
#   * a value outside a picklist: `Bad Request(… "RuleValidationErrors":[…] … is not in the list of supported values
#     … "typeKey":"RuleValidationException" …)` -> rule;
#   * a create carrying `System.AssignedTo` for an address the organisation does not know: `The identity value '…' for
#     field 'Assigned To' is an unknown identity.` -> rule, so that row fails and the run goes on (it was `unknown`,
#     a stop class, and the five rows after it were deferred as stopped);
#   * an update `az rest` could not mint an Entra token for (a personal access token alone; the transport's
#     `REST_NO_TOKEN_WRITE`) -> permission: nothing was sent, and no later update could be. `apply` refuses such a
#     plan before anything is sent (`identity_unknown`); this row is the second lock.
_ERROR_ROWS = (
    ("throttled", _any(r"too many requests", r"exceeding usage", r"\bthrottl", r"TF400733", r"rate limit",
                       _status(429))),
    ("conflict", _any(r"TF26071", r"changed by someone else", r"\bconflict\b", r"test operation failed",
                      r"VS403351", r"precondition failed", r"TestPatchOperationFailedException",
                      r"test operation for path /rev failed", _status(412))),
    ("not_found", _any(r"TF401232", r"does not exist", r"\bnot found\b", r"cannot be found", _status(404))),
    ("permission", _any(r"TF50309", r"TF401027", r"not authorized", r"\bunauthorized\b", r"\bforbidden\b",
                        r"access denied", r"do not have (?:sufficient )?permissions? to", _status(401),
                        _status(403), r"could not mint an Entra token for Azure DevOps, so the update was not sent")),
    ("rule", _any(r"rule error", r"TF401320", r"TF51535", r"TF401347", r"TF26194",
                  r"is not in the list of supported values", r"invalid(?:list)?value", r"RuleValidationErrors",
                  r"RuleValidationException", r"is an unknown identity")),
)


def classify_write_error(stderr: str) -> str:
    """The `ERROR_CLASSES` member a failed write's stderr reads as: `conflict` (the `test /rev` failed), `rule`
    (the process refused a value or a transition), `permission`, `throttled`, `not_found` or `unknown`. Anything
    else — and anything that is not text — is `unknown`; the enum is closed."""
    if not isinstance(stderr, str) or not stderr.strip():
        return "unknown"
    return next((name for name, pattern in _ERROR_ROWS if pattern.search(stderr)), "unknown")


# What a `rule` refusal was about (B0, 2026-10-15): a closed word and the field the patch carried that it names, so a
# failed row can say which field to fix without carrying the board's own text (which can name people).
RULE_REASONS = ("unknown_identity", "value_not_allowed")
_RULE_REASON_ROWS = (
    ("unknown_identity", _any(r"is an unknown identity")),
    ("value_not_allowed", _any(r"is not in the list of supported values", r"invalid(?:list)?value")),
)
_FIELD_REF_IN_ERROR = re.compile(r'"fieldReferenceName"\s*:\s*"([A-Za-z][A-Za-z0-9_.]*)"', re.IGNORECASE)
_FIELD_NAME_IN_ERROR = re.compile(r"\b(?:for field|the field) '([^'\n]{1,128})'", re.IGNORECASE)


def describe_write_error(stderr, patch_fields) -> dict:
    """`{"reason", "field"}` of a failed write that `classify_write_error` reads as `rule`, else both None.

    `reason` is a `RULE_REASONS` member or None. `field` is one of `patch_fields` (the reference names the patch
    carried) and nothing else: a `fieldReferenceName` the board's answer names, else the display name it quotes (`for
    field 'Assigned To'`, `The field 'State'`) matched, spaces dropped and case folded, to the last segment of exactly
    one patch field, else — for an unknown identity — the patch's one identity field. A name that matches no field,
    or several, is None: the field is never guessed, and no text of the answer is returned."""
    out = {"reason": None, "field": None}
    if classify_write_error(stderr) != "rule":
        return out
    fields = [f for f in dict.fromkeys(patch_fields or []) if isinstance(f, str)]
    out["reason"] = next((name for name, pattern in _RULE_REASON_ROWS if pattern.search(stderr)), None)
    named = [m.group(1) for m in _FIELD_REF_IN_ERROR.finditer(stderr) if m.group(1) in fields]
    if not named:
        shown = {re.sub(r"\s+", "", m.group(1)).casefold() for m in _FIELD_NAME_IN_ERROR.finditer(stderr)}
        named = [f for f in fields if f.rsplit(".", 1)[-1].casefold() in shown]
        if len(named) > 1:
            named = []
    if not named and out["reason"] == "unknown_identity":
        identities = [f for f in fields if f in IDENTITY_FIELDS]
        named = identities if len(identities) == 1 else []
    out["field"] = named[0] if named else None
    return out


# --- URLs ---------------------------------------------------------------------------------------------------

def _azure(remote_info: RemoteInfo, what: str) -> RemoteInfo:
    if remote_info.host != "azure-devops" or not remote_info.org_url:
        raise ValueError(f"{what} needs an Azure DevOps remote; this one is {remote_info.host}")
    return remote_info


def file_hyperlink(remote_info: RemoteInfo, path: str, sha: str) -> str:
    """The link a work item carries back to its source file at the commit it was written from:
    `<repo web url>?version=GC<sha>&path=/<path>`. `path` is relative to the repository root (no `..`, no empty
    segment, no backslash); characters that would end the query are percent-encoded; `sha` is a lower-case commit id."""
    _azure(remote_info, "a file hyperlink")
    if not isinstance(sha, str) or not _SHA_OK.fullmatch(sha):
        raise ValueError(f"{sha!r} is not a commit sha (7 to 64 lower-case hex digits)")
    text = path[1:] if isinstance(path, str) and path.startswith("/") else path
    if (not isinstance(text, str) or not text or "\\" in text or _control(text)
            or any(seg in ("", ".", "..") for seg in text.split("/"))):
        raise ValueError(f"path {path!r} is not a file inside the repository")
    return f"{remote_info.web_url}?version=GC{sha}&path=/{quote(text, safe='/')}"


def work_item_url(remote_info: RemoteInfo, work_item_id: int) -> str:
    """The URL a parent link points at: `<org url>/_apis/wit/workItems/<id>` (the project is not needed)."""
    _azure(remote_info, "a work item URL")
    if isinstance(work_item_id, bool) or not isinstance(work_item_id, int) or work_item_id < 1:
        raise ValueError(f"{work_item_id!r} is not a work item id (a positive integer)")
    return f"{remote_info.org_url.rstrip('/')}/_apis/wit/workItems/{work_item_id}"
