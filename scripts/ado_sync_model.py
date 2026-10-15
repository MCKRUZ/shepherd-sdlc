"""The Azure Boards mirror's pure sync model (B2-P0): drift, dispositions, the ledger line, the plan hash, status.

Every verb that reads the board (`plan`, `pull`, `drift`, `status`, later `reconcile`) decides with these
functions, so the rules live in one pure module: no I/O, no clock, no `az`, and no `ado_*` import (an AST test
holds the import list to the standard library plus `boards_contract`, `findings_model`, `artifact_model` and
`track_decisions`). It is a library part, usable two ways like every part of the plugin:

  * Workflow mode — `ado_sync.py --state .sdlc/state.yaml …` reads `.sdlc/metrics/ado-sync-log.jsonl` and the
    repository's projections, and hands the parsed lines and documents in here.
  * Standalone — any caller (a test, a notebook, another script) passes plain dicts and lists; nothing here needs
    a `.sdlc/` directory, and nothing here writes one.

What it decides:

  * `classify_drift` — the design's §8 matrix: who owns a field a board revision changed (`boards_contract.
    OWNERSHIP`, refined per kind by `KIND_OWNERSHIP`), and so which `DRIFT_CLASSES` member the change is. A
    revision whose only change is `System.History` is a `COMMENT`, not drift. An attachment is listed, never
    `RELATION_DRIFT`. A forbidden (effort) field is named and its value never read. Identity, History and
    free-text values are never copied into the result (the D38 scrub runs on this path, not only for discussion).
  * `diff` — what a push would change: the SDLC-owned (`S`) fields of a projection that differ from the item.
    Only a work item field reference name (`System.Title`, `Microsoft.VSTS.Common.Priority`, `Custom.RiskTier`:
    `REFERENCE_NAME_RE`) is ever an op; a source's neutral key (`description_rows`, `fr_ids`) is its own data.
  * `validate_disposition` / `counts_as_open` — the disposition state machine with honest counting: a
    mislabelled disposition (ACKNOWLEDGED without an owner, NOT_DRIFT without a reason, TAKE_* without a recorded
    child exit 0) is still open.
  * `ledger_entry` — one ledger line; it refuses an unknown event and any e-mail address or GUID anywhere in it.
  * `plan_hash` — the 12-hex handshake a human echoes to `apply --confirm`.
  * `hook_line`, `STATUS_NODATA`, `summarize` — what `status` and the session hook say. Never measured is `None`
    ("no data"), never an integer 0; a 0 appears only after a read that found none.
"""

import hashlib
import json
import re
from datetime import date, datetime
from typing import Final

import boards_contract as bc
from findings_model import is_ai_actor
from track_decisions import add_business_days

LEDGER_EVENTS: Final = bc.LEDGER_EVENTS
DRIFT_CLASSES: Final = bc.DRIFT_CLASSES
AGENT_PREFIX: Final = "shepherd:"  # the only prefix `ai_by` strips (K7); `ado_sync.AGENT_PREFIX` is the same

# boards_contract.GUID_RE without its word boundaries: a GUID glued to a word character ("%2F<guid>") still counts.
_GUID_ANYWHERE: Final = re.compile(bc.GUID_RE.pattern.replace(r"\b", ""))

# --- ownership ----------------------------------------------------------------------------------------------

# Per-kind exceptions to boards_contract.OWNERSHIP, read from the design's §6.1 Ownership column. A kind not
# named here (spec, spike, sprint, lifecycle) uses OWNERSHIP as it is.
KIND_OWNERSHIP: Final[dict[str, dict[str, str]]] = {
    "decision": {"System.State": "A", "System.Title": "C", "System.Description": "C"},  # A: close; C: wording
    "finding": {"System.State": "A"},                    # A: Closed -> a proposal only
    "outcome": {"System.State": "A"},
    "domain": {"System.State": "A"},
    "requirement": {"System.State": "A", "Microsoft.VSTS.Common.Priority": "S",
                    "Microsoft.VSTS.Common.AcceptanceCriteria": "C"},  # S: priority; C: text -> .proposed
    "epic": {"System.State": "A"},                       # the board's roll-up and the team's closing own State
    "feature": {"System.State": "A"},
    "rule": {"System.State": "A", "System.Description": "C"},
    "question": {"System.State": "A"},                   # answered -> a proposal into question-list.md
    "measurement": {"System.State": "A"},
}

# A revision always moves these; none of them is a change anybody made to the item's meaning.
BOOKKEEPING_FIELDS: Final = frozenset({
    "System.Id", "System.Rev", "System.RevisedDate", "System.AuthorizedDate", "System.AuthorizedAs",
    "System.ChangedDate", "System.ChangedBy", "System.Watermark", "System.PersonId", "System.CommentCount",
    "System.Reason", "System.CreatedDate", "System.CreatedBy", "System.BoardColumn", "System.BoardColumnDone",
    "System.BoardLane", "Microsoft.VSTS.Common.StateChangeDate", "Microsoft.VSTS.Common.ActivatedDate",
    "Microsoft.VSTS.Common.ActivatedBy", "Microsoft.VSTS.Common.ResolvedDate", "Microsoft.VSTS.Common.ResolvedBy",
    "Microsoft.VSTS.Common.ResolvedReason", "Microsoft.VSTS.Common.ClosedDate", "Microsoft.VSTS.Common.ClosedBy",
})
BOOKKEEPING_PREFIXES: Final = ("WEF_",)  # the Kanban board's per-board column fields
# Effort fields are refused by the mirror (ado_schema_map.refused_fields); a change is named, its value never read.
FORBIDDEN_FIELD_PREFIXES: Final = ("Microsoft.VSTS.Scheduling.",)
HISTORY_FIELD: Final = "System.History"
# Free text a person typed: the class is reported, the value never copied (it may name people).
FREE_TEXT_FIELDS: Final = frozenset({HISTORY_FIELD, "System.Description", "Microsoft.VSTS.Common.AcceptanceCriteria"})
IDENTITY_FIELDS: Final = frozenset({"System.AssignedTo", "System.ChangedBy", "System.CreatedBy", "System.AuthorizedAs"})

PARENT_REL: Final = "System.LinkTypes.Hierarchy-Reverse"
ATTACHMENT_REL: Final = "AttachedFile"
# A work item field reference name is always dotted (`System.Title`, `Microsoft.VSTS.Common.Priority`,
# `Custom.RiskTier`). A projection key without a dot is a source's neutral data (the requirements tree's
# `description_rows`, `fr_ids`, `priority`, `domain`): never a field op, so a plan never lists `/fields/fr_ids`.
REFERENCE_NAME_RE: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")
MARKER_BEGIN: Final = "<!-- sdlc:begin -->"
MARKER_END: Final = "<!-- sdlc:end -->"

# The item's class is its most severe field's class.
SEVERITY: Final[dict[str, int]] = {"IN_SYNC": 0, "COMMENT": 1, "RELATION_DRIFT": 2, "ADO_OWNED_CHANGE": 3,
                                   "SDLC_OWNED_DRIFT": 4, "CONFLICT": 5, "RETYPED": 6, "MOVED": 7}
SPEC_HANDED_OFF: Final = ("in-flight", "merged")  # a developer change on these is a new hand-off, not a board edit

# Where a field lives in an `ado_wit_map.remote_item` document when it has no raw `fields` copy.
_REMOTE_KEYS: Final = {"System.Title": "title", "System.State": "state", "System.IterationPath": "iteration",
                       "System.AreaPath": "area", "System.WorkItemType": "type"}


def ownership_for(kind: str | None) -> dict[str, str]:
    """`boards_contract.OWNERSHIP` with the kind's §6.1 exceptions laid over it."""
    return {**bc.OWNERSHIP, **KIND_OWNERSHIP.get(kind or "", {})}


# --- people -------------------------------------------------------------------------------------------------

def ai_by(name: str, agent_stems: frozenset[str]) -> bool:
    """True when a `--by` name reads as an AI or an agent (K7): strip a leading `shepherd:` (only that prefix,
    any case), then refuse on `is_ai_actor`, an `agents/*.md` stem, or a discipline agent. A blank is not an AI
    (`require_human` refuses it as Illegal). Labelling, not identity: it refuses the obvious only."""
    clean = str(name or "").strip()
    if not clean:
        return False
    stem = clean[len(AGENT_PREFIX):].strip() if clean.lower().startswith(AGENT_PREFIX) else clean
    lowered = stem.lower()
    return bool(is_ai_actor(stem) or stem in agent_stems or lowered in agent_stems
                or lowered in bc.DISCIPLINE_AGENTS)


# --- canonical JSON and hashes ------------------------------------------------------------------------------

def _canon(value):
    """JSON-ready: sets sorted into lists, tuples into lists, dict keys as they are."""
    if isinstance(value, (set, frozenset)):
        items = [_canon(v) for v in value]
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    if isinstance(value, dict):
        return {k: _canon(v) for k, v in value.items()}
    return value


def plan_hash(rows: list[dict]) -> str:
    """sha256 of the rows as compact sorted-key JSON, first 12 hex — stable across key order, not row order.
    A set inside a row is hashed as its sorted list (for JSON-native rows this is exactly the pinned formula)."""
    text = json.dumps(_canon(rows), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def projection_hash(projection: dict) -> str:
    """The 12-hex fingerprint of a projection (the ledger's `projection_hash`): moved = the repo side changed."""
    text = json.dumps(_canon(projection), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


# --- small readers --------------------------------------------------------------------------------------------

def _tags(value) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {t.strip() for t in value.split(";") if t.strip()}
    return {str(t).strip() for t in value if str(t).strip()}


def _plugin_tags(tags) -> set[str]:
    return {t for t in _tags(tags) if t.startswith(bc.PLUGIN_TAG_PREFIXES)}


def constant_fields(projection: dict | None) -> frozenset[str]:
    """The fields a projection carries as constants (`constant_fields`, set by `ado_sync_sources` for each
    `fields.<kind>.<key>: {field, value}` rule it applied): written at create, filled on update only while the
    board's field is empty, and the board's afterwards (`C`), whatever `OWNERSHIP` says of the field."""
    named = (projection or {}).get("constant_fields")
    if not isinstance(named, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(r for r in named if isinstance(r, str))


def _marker_block(html) -> str | None:
    """The text between the sdlc markers, or None when the markers are absent."""
    text = str(html or "")
    begin, end = text.find(MARKER_BEGIN), text.find(MARKER_END)
    if begin < 0 or end < begin:
        return None
    return text[begin + len(MARKER_BEGIN):end].strip()


def _is_identity(ref: str, value) -> bool:
    if ref in IDENTITY_FIELDS or isinstance(value, dict):
        return True
    return isinstance(value, str) and bool(bc.EMAIL_RE.search(value) or _GUID_ANYWHERE.search(value))


def _norm(value):
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text.casefold() if bc.EMAIL_RE.fullmatch(text) else text
    if isinstance(value, (set, frozenset, list, tuple)):
        return frozenset(_norm(v) for v in value)
    return value


def _remote_value(remote: dict, ref: str):
    fields = remote.get("fields")
    if isinstance(fields, dict) and ref in fields:
        return fields[ref]
    key = _REMOTE_KEYS.get(ref)
    return remote.get(key) if key else None


def _knows(remote: dict, ref: str) -> bool:
    fields = remote.get("fields")
    return (isinstance(fields, dict) and ref in fields) or (_REMOTE_KEYS.get(ref) in remote)


# --- diff: what a push would change ---------------------------------------------------------------------------

def diff(projection: dict, remote: dict | None, ownership: dict = bc.OWNERSHIP) -> list[dict]:
    """The ops a push would make, sorted by path: `{"op", "path", "old", "new", "class"}`.

    It compares `projection["fields"]` (the values the mirror pushes, by reference name) and the plugin-prefixed
    subset of `projection["tags"]` — nothing else; a `fields` key that is not a reference name (`REFERENCE_NAME_RE`:
    a source's neutral data, such as the requirements tree's `description_rows`) is never an op, so neither patch
    builder can send it. No item yet: every field is an `add` (`NEVER_PUSHED`). An
    existing item: only an `S` field (by `ownership`; a pushed field the map does not name is the repo's) that
    differs after normalisation (trimmed text, case-folded e-mail, tag sets, the Description's marker block) is an
    op (`SDLC_OWNED_DRIFT`); an `A`/`C` field is the board's after create, so it never is. A field the remote
    document does not carry is not compared (the B2-P1 patch builder reads the whole item). A constant (a field the
    projection names in `constant_fields`, from a `fields.<kind>.<key>: {field, value}` rule) is pushed at create and,
    on an existing item, only while the board's field is empty (`NEVER_PUSHED`): whatever the board holds there
    afterwards is the board's, whatever `ownership` says of the field."""
    want = {ref: value for ref, value in (projection.get("fields") or {}).items()
            if isinstance(ref, str) and REFERENCE_NAME_RE.fullmatch(ref)}
    tags = sorted(_plugin_tags(projection.get("tags")))
    if remote is None:
        ops = [{"op": "add", "path": f"/fields/{ref}", "old": None, "new": value, "class": "NEVER_PUSHED"}
               for ref, value in want.items()]
        if tags:
            ops.append({"op": "add", "path": "/fields/System.Tags", "old": None, "new": "; ".join(tags),
                        "class": "NEVER_PUSHED"})
        return sorted(ops, key=lambda o: o["path"])
    ops = []
    constants = constant_fields(projection)
    for ref, new in want.items():
        if ref in constants:
            held = remote.get("fields")
            if isinstance(held, dict) and new is not None and _remote_value(remote, ref) in (None, ""):
                ops.append({"op": "add", "path": f"/fields/{ref}", "old": None, "new": new, "class": "NEVER_PUSHED"})
            continue
        if ref == "System.Tags" or ownership.get(ref, "S") != "S" or not _knows(remote, ref):
            continue
        old = _remote_value(remote, ref)
        if ref == "System.Description":
            same = (_marker_block(old) or "") == (_marker_block(new) or str(new or "").strip())
        else:
            same = _norm(old) == _norm(new)
        if not same:
            ops.append({"op": "add" if old is None else "replace", "path": f"/fields/{ref}", "old": old, "new": new,
                        "class": "SDLC_OWNED_DRIFT"})
    have = sorted(_plugin_tags(remote.get("tags")))
    if ownership.get("System.Tags", "S") == "S" and "tags" in remote and have != tags:
        ops.append({"op": "replace" if have else "add", "path": "/fields/System.Tags",
                    "old": "; ".join(have) if have else None, "new": "; ".join(tags), "class": "SDLC_OWNED_DRIFT"})
    return sorted(ops, key=lambda o: o["path"])


# --- classify_drift: the design §8 matrix ---------------------------------------------------------------------

def _field_class(kind: str | None, own: dict, ref: str, change: dict, projection: dict,
                 repo_moved: bool) -> tuple[str, str | None]:
    """(class, owner) for one field a board revision changed."""
    old, new = change.get("oldValue"), change.get("newValue")
    if ref == HISTORY_FIELD:
        return "COMMENT", None
    if ref == "System.WorkItemType":
        return "RETYPED", "S"
    if ref == "System.TeamProject":
        return "MOVED", "C"
    if ref == "System.Tags":
        owner = "S" if _plugin_tags(old) != _plugin_tags(new) else "C"  # human tags are the board's
    elif ref in constant_fields(projection):
        owner = "C"  # a constant is written once; what the board does with it afterwards is the board's
    elif ref == "System.Description":
        owner = own.get(ref, "S")
        if owner == "S" and _marker_block(old) == _marker_block(new):
            owner = "C"  # only the text outside the markers moved
    else:
        owner = own.get(ref) or ("S" if ref in (projection.get("fields") or {}) else "C")
    if ref == "System.AssignedTo" and kind == "spec" and projection.get("status") in SPEC_HANDED_OFF:
        return "SDLC_OWNED_DRIFT", owner
    if owner == "S":
        return ("CONFLICT" if repo_moved else "SDLC_OWNED_DRIFT"), owner
    return "ADO_OWNED_CHANGE", owner


def _target(url) -> int | None:
    m = re.search(r"/workItems/(\d+)$", str(url or ""))
    return int(m.group(1)) if m else None


def _entry(entries: dict, key: str, cls: str, owner: str | None, rev, revised_at) -> dict:
    e = entries.get(key)
    if e is None:
        e = entries[key] = {"field": key, "class": cls, "owner": owner, "rev": rev, "revised_at": revised_at}
    elif SEVERITY[cls] >= SEVERITY[e["class"]]:
        e.update({"class": cls, "owner": owner})
    e.update({"rev": rev, "revised_at": revised_at})
    return e


def classify_drift(ledger_row: dict | None, remote: dict | None, projection: dict | None,
                   updates: list[dict]) -> dict:
    """The drift class of one item, and of each field the board changed since the ledger's `rev_after`.

    `ledger_row` is the item's last ledger line (`ref`, `kind`, `work_item`, `rev_after`, `projection_hash`) or
    None when never ledgered; `remote` the current item (`ado_wit_map.remote_item`) or None when ADO omitted it;
    `projection` the repo's current projection or None when its source is gone; `updates` the raw `wit/updates`
    revisions. Returns `{"class", "fields": [{"field", "class", "owner", "rev", "revised_at", "old"?, "new"?}],
    "attachments": [{"name", "url", "rev"}], "ignored": [field names]}`.

    Existence first: never ledgered and not on the board -> `NEVER_PUSHED`; on the board but not ledgered ->
    `UNMAPPED_IN_ADO` (link or adopt it); ledgered but gone from ADO -> `DELETED_IN_ADO`; ledgered but its source
    gone -> `ORPHAN_IN_REPO`. Then the §8 matrix per field, with revisions at or below `rev_after` skipped ((id, rev)
    dedup). A rev that moved past `rev_after` with no updates read raises ValueError: an unread change is never
    called IN_SYNC."""
    if ledger_row is None:
        if remote is None and projection is None:
            raise ValueError("nothing to classify: no ledger line, no remote item and no projection")
        return _result("NEVER_PUSHED" if remote is None else "UNMAPPED_IN_ADO")
    if remote is None:
        return _result("DELETED_IN_ADO")
    if projection is None:
        return _result("ORPHAN_IN_REPO")
    rev_after = ledger_row.get("rev_after")
    rev_now = remote.get("rev")
    if not updates and isinstance(rev_after, int) and isinstance(rev_now, int) and rev_now > rev_after:
        raise ValueError(f"work item {remote.get('id')} moved from rev {rev_after} to {rev_now} but no updates "
                         "were read; read wit/updates before classifying (never a fabricated IN_SYNC)")
    kind = projection.get("kind") or ledger_row.get("kind")
    own = ownership_for(kind)
    pushed = ledger_row.get("projection_hash")
    repo_moved = pushed is not None and projection_hash(projection) != pushed
    entries: dict[str, dict] = {}
    attachments: list[dict] = []
    ignored: list[str] = []
    for upd in sorted(updates, key=lambda u: u.get("rev") if isinstance(u.get("rev"), int) else -1):
        rev = upd.get("rev")
        if isinstance(rev_after, int) and isinstance(rev, int) and rev <= rev_after:
            continue
        fields = upd.get("fields") or {}
        revised_at = (fields.get("System.ChangedDate") or {}).get("newValue") or upd.get("revisedDate")
        for ref, change in fields.items():
            if ref in BOOKKEEPING_FIELDS or ref.startswith(BOOKKEEPING_PREFIXES):
                continue
            if ref.startswith(FORBIDDEN_FIELD_PREFIXES):
                if ref not in ignored:
                    ignored.append(ref)
                continue
            change = change if isinstance(change, dict) else {}
            cls, owner = _field_class(kind, own, ref, change, projection, repo_moved)
            e = _entry(entries, ref, cls, owner, rev, revised_at)
            old, new = change.get("oldValue"), change.get("newValue")
            if ref in FREE_TEXT_FIELDS or _is_identity(ref, old) or _is_identity(ref, new):
                e.pop("old", None)
                e.pop("new", None)
            else:
                e.setdefault("old", old)
                e["new"] = new
        relations = upd.get("relations") or {}
        for side in ("added", "removed"):
            for rel in relations.get(side) or []:
                name = rel.get("rel")
                if name == ATTACHMENT_REL:
                    if side == "added":
                        attachments.append({"name": (rel.get("attributes") or {}).get("name"), "url": rel.get("url"),
                                            "rev": rev})
                    continue
                parent = name == PARENT_REL
                key = "relations:parent" if parent else f"relations:{name}"
                e = _entry(entries, key, "ADO_OWNED_CHANGE" if parent else "RELATION_DRIFT", "A" if parent else None,
                           rev, revised_at)
                e.setdefault("added", [])
                e.setdefault("removed", [])
                e[side].append(_target(rel.get("url")))
    if (ledger_row.get("type") and remote.get("type") and ledger_row["type"] != remote["type"]
            and "System.WorkItemType" not in entries):
        _entry(entries, "System.WorkItemType", "RETYPED", "S", rev_now, None)
    worst = max((e["class"] for e in entries.values()), key=SEVERITY.__getitem__, default="IN_SYNC")
    return _result(worst, list(entries.values()), attachments, ignored)


def _result(cls: str, fields=None, attachments=None, ignored=None) -> dict:
    return {"class": cls, "fields": fields or [], "attachments": attachments or [], "ignored": sorted(ignored or [])}


# --- dispositions ---------------------------------------------------------------------------------------------

DISPOSITIONS: Final = ("OPEN", "TAKE_ADO", "TAKE_SDLC", "ACKNOWLEDGED", "NOT_DRIFT", "RECREATE", "UNLINK", "RELINK")
# The design §8 state machine; a drift class not named here takes DEFAULT_DISPOSITIONS.
DISPOSITIONS_BY_CLASS: Final[dict[str, tuple[str, ...]]] = {
    "CONFLICT": ("TAKE_ADO", "TAKE_SDLC"),
    "RETYPED": ("TAKE_ADO", "TAKE_SDLC"),  # RETYPED -> CONFLICT: it requires a take
    "DELETED_IN_ADO": ("RECREATE", "UNLINK", "ACKNOWLEDGED"),
    "ORPHAN_IN_REPO": ("UNLINK", "RELINK"),
}
DEFAULT_DISPOSITIONS: Final = ("TAKE_ADO", "TAKE_SDLC", "ACKNOWLEDGED", "NOT_DRIFT")
NOT_DRIFT_CLASSES: Final = ("IN_SYNC", "COMMENT", "NEVER_PUSHED")  # nothing to dispose of
DEBT_CLASSES: Final = ("SDLC_OWNED_DRIFT", "CONFLICT", "RETYPED")  # open on an S field -> debt after 2 business days
DEBT_BUSINESS_DAYS: Final = 2


def _disposition(value) -> str | None:
    if value is None or not str(value).strip():
        return "OPEN"
    word = str(value).strip().upper().replace("-", "_")
    return word if word in DISPOSITIONS else None


def validate_disposition(row: dict) -> tuple[bool, str]:
    """(off_books, reason) for one drift row `{"class", "disposition"?, "owner"?, "reason"?, "child_exit"?,
    "relink_ref"?}`. Off the books only when the disposition is legal for the class AND carries what it claims:
    ACKNOWLEDGED a human owner, NOT_DRIFT a reason, TAKE_* a recorded child exit 0, RELINK a ref. A mislabelled
    one counts exactly like OPEN — you cannot clear drift by typing a word."""
    cls = row.get("class")
    if cls not in DRIFT_CLASSES:
        return False, f"unknown drift class {cls!r} — counts as open"
    if cls in NOT_DRIFT_CLASSES:
        return True, f"not drift: {cls}"
    disp = _disposition(row.get("disposition"))
    if disp is None:
        return False, f"unknown disposition {row.get('disposition')!r} — counts as open"
    if disp == "OPEN":
        return False, "open"
    allowed = DISPOSITIONS_BY_CLASS.get(cls, DEFAULT_DISPOSITIONS)
    if disp not in allowed:
        return False, f"{disp} is not a disposition for {cls} (allowed: {', '.join(allowed)}) — still open"
    if disp == "ACKNOWLEDGED":
        owner = str(row.get("owner") or "").strip()
        if not owner:
            return False, "ACKNOWLEDGED missing required field(s): owner — still open"
        if ai_by(owner, frozenset()):
            return False, "ACKNOWLEDGED owner must be a named human, not an AI or an agent — still open"
    if disp == "NOT_DRIFT" and not str(row.get("reason") or "").strip():
        return False, "NOT_DRIFT missing required field(s): reason — still open"
    if disp in ("TAKE_ADO", "TAKE_SDLC"):
        code = row.get("child_exit")
        if isinstance(code, bool) or code != 0:
            return False, f"{disp} without a recorded child exit 0 (got {code!r}) — still open"
    if disp == "RELINK" and not bc.REF_RE.fullmatch(str(row.get("relink_ref") or "")):
        return False, "RELINK needs relink_ref, an sdlc:<kind>:<id> ref — still open"
    return True, disp.lower()


def counts_as_open(row: dict) -> bool:
    """A drift row is open unless it is legitimately off the books."""
    off_books, _ = validate_disposition(row)
    return not off_books


# --- the ledger line ------------------------------------------------------------------------------------------

_HANDLE_KEYS: Final = ("revised_by", "executed_as")  # identities from ADO: a handle, None, or "unknown" — never a name


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for v in value:
            yield from _strings(v)


def ledger_id(work_item: int, rev: int) -> str:
    """The design's ledger id for an item revision: `ado-sync:<wi>:<rev>`."""
    return f"ado-sync:{work_item}:{rev}"


def ledger_entry(ts: str, event: str, **fields) -> dict:
    """One `.sdlc/metrics/ado-sync-log.jsonl` line: `{"ts", "event", **fields}` with sets written sorted.

    ValueError on an event outside `boards_contract.LEDGER_EVENTS`, on an e-mail address or a GUID in any string
    anywhere in the line (keys and nested values included), on a `revised_by`/`executed_as` that is not a handle,
    None or "unknown", and on anything JSON cannot write. The caller appends `json.dumps(entry) + "\\n"`."""
    if event not in LEDGER_EVENTS:
        raise ValueError(f"unknown ledger event {event!r}; events are boards_contract.LEDGER_EVENTS")
    if not isinstance(ts, str) or not ts.strip():
        raise ValueError("a ledger line needs a ts string")
    entry = {"ts": ts, "event": event, **_canon(fields)}
    for text in _strings(entry):
        if bc.EMAIL_RE.search(text):
            raise ValueError("a ledger line may not carry an e-mail address (use a roster @handle)")
        if _GUID_ANYWHERE.search(text):
            raise ValueError("a ledger line may not carry a GUID (identities and ADO ids stay off the record)")
    for key in _HANDLE_KEYS:
        value = entry.get(key)
        if value is not None and value != "unknown" and not (isinstance(value, str) and bc.HANDLE_RE.fullmatch(value)):
            raise ValueError(f"{key} must be a roster @handle, null or 'unknown' — never a name")
    try:
        json.dumps(entry)
    except (TypeError, ValueError) as err:
        raise ValueError(f"a ledger line must be JSON: {err}") from None
    return entry


# --- the hook line and status ---------------------------------------------------------------------------------

NEVER_PULLED: Final = "no data (never pulled)"


def _count(value, what: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{what} must be a non-negative integer or None, not {value!r}")
    return value


def hook_line(pending: int | None, drifted: int | None, as_of: str | None) -> str:
    """Line 1 of `.sdlc/ado/local/hook-status.txt`: `3 rows pending · 1 drifted · as of 2026-10-12T09:02Z`, or
    `no data (never pulled)` when there has been no pull (`as_of` None). A count never measured reads as words,
    never 0: `no plan yet`, `drift no data`."""
    pending, drifted = _count(pending, "pending"), _count(drifted, "drifted")
    if as_of is None:
        return NEVER_PULLED
    if not isinstance(as_of, str) or not as_of.strip() or "\n" in as_of or "\r" in as_of:
        raise ValueError("as_of must be a one-line timestamp string")
    rows = "no plan yet" if pending is None else f"{pending} row{'' if pending == 1 else 's'} pending"
    drift = "drift no data" if drifted is None else f"{drifted} drifted"
    return f"{rows} · {drift} · as of {as_of.strip()}"


COUNT_KEYS: Final = ("linked", "pending", "drifted", "open", "conflicts", "debt")

# The never-pulled `status --json` document (golden: scripts/tests/golden/ado_status_nodata.json). It contains no
# integer 0 and no false: every count is None because nothing was ever measured.
STATUS_NODATA: Final[dict] = {
    "schema": 1,
    "ledger": bc.LEDGER,
    "as_of": None,
    "hook_line": NEVER_PULLED,
    "last_plan": None,
    "counts": dict.fromkeys(COUNT_KEYS),
    "by_class": None,
    "debt": None,
    "notes": ["no data: the mirror has never pulled — every count is unmeasured, not zero"],
}


def _nodata() -> dict:
    return json.loads(json.dumps(STATUS_NODATA))  # a deep copy (the model imports no copy module)


def _day(ts) -> date | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def summarize(ledger: list[dict], today) -> dict:
    """The `status --json` document from parsed ledger lines (append order) and `today` (a date).

    An empty ledger (or one with no recognised event) is `STATUS_NODATA`. Otherwise:
      * `linked` — distinct refs with an int `work_item` on a `linked`/`adopted`/`applied` line (the ledger was
        read, so 0 is honest), less those whose last off-books `reconciled` line for the item is UNLINK.
      * `pending` — None until a `planned` line exists; then the distinct refs of the latest plan (all `planned`
        lines sharing the last one's `plan` hash; a header line with `ref: null` marks a plan that found nothing)
        without a later `applied` line for that ref and plan.
      * `as_of` — the ts of the last `observed` line (a pull writes at least one; `ref: null` when nothing is
        ledgered). No `observed` line = never pulled: drifted/open/conflicts/debt stay None.
      * drift rows — the latest `drift_seen` per (ref, field); a row is cleared by a later off-books `reconciled`
        line for that (ref, field) (or for the ref with no field) or a later `applied` line whose `fields` name
        the field. `drifted` = refs with an open row; `conflicts` = open CONFLICT/RETYPED rows; `debt` = open
        `DEBT_CLASSES` rows first seen more than 2 business days before `today` (track_decisions.add_business_days)
        — rolled up by ref and field, never by actor."""
    if isinstance(today, datetime):
        today = today.date()
    events = [e for e in ledger if isinstance(e, dict) and e.get("event") in LEDGER_EVENTS]
    if not events:
        return _nodata()
    doc = _nodata()
    counts = doc["counts"]
    doc["notes"] = []

    # linked
    linked: dict[str, int] = {}
    for i, e in enumerate(events):
        if e["event"] in ("linked", "adopted", "applied") and isinstance(e.get("work_item"), int) and e.get("ref"):
            linked[e["ref"]] = i
        if (e["event"] == "reconciled" and e.get("ref") in linked and not e.get("field")
                and _disposition(e.get("disposition")) == "UNLINK" and linked[e["ref"]] < i):
            del linked[e["ref"]]
    counts["linked"] = len(linked)

    # pending + last plan
    planned = [(i, e) for i, e in enumerate(events) if e["event"] == "planned" and e.get("plan")]
    if planned:
        plan = planned[-1][1]["plan"]
        lines = [(i, e) for i, e in planned if e["plan"] == plan]
        refs = {e["ref"] for _, e in lines if e.get("ref")}
        first = lines[0][0]
        applied = {e.get("ref") for i, e in enumerate(events)
                   if i > first and e["event"] == "applied" and e.get("plan") == plan}
        counts["pending"] = len(refs - applied)
        doc["last_plan"] = {"plan": plan, "ts": lines[-1][1].get("ts"), "rows": len(refs)}

    observed = [e for e in events if e["event"] == "observed"]
    if not observed:
        doc["notes"].append("never pulled: drift counts are no data")
        doc["hook_line"] = hook_line(counts["pending"], None, None)
        return doc
    doc["as_of"] = observed[-1].get("ts")

    rows: dict[tuple, tuple[int, dict]] = {}
    for i, e in enumerate(events):
        if e["event"] == "drift_seen" and e.get("ref"):
            rows[(e["ref"], e.get("field"))] = (i, dict(e))
    open_rows = []
    for (ref, field), (i, row) in rows.items():
        merged = dict(row)
        cleared = False
        for e in events[i + 1:]:
            if e.get("ref") != ref:
                continue
            if e["event"] == "applied" and field in (e.get("fields") or []):
                cleared = True
            elif e["event"] == "reconciled" and e.get("field") in (field, None):
                merged.update({k: v for k, v in e.items() if k not in ("ts", "event", "class")})
                if not counts_as_open(merged):
                    cleared = True
        if not cleared and counts_as_open(merged):
            open_rows.append(row)
    counts["open"] = len(open_rows)
    counts["drifted"] = len({r["ref"] for r in open_rows})
    counts["conflicts"] = sum(1 for r in open_rows if r.get("class") in ("CONFLICT", "RETYPED"))
    by_class: dict[str, int] = {}
    for r in open_rows:
        by_class[r.get("class")] = by_class.get(r.get("class"), 0) + 1
    doc["by_class"] = dict(sorted(by_class.items()))
    debt = []
    for r in open_rows:
        seen = _day(r.get("ts"))
        if r.get("class") not in DEBT_CLASSES:
            continue
        if seen is None:
            doc["notes"].append(f"{r['ref']} {r.get('field')}: unreadable ts, not aged")
            continue
        due = add_business_days(seen, DEBT_BUSINESS_DAYS)
        if today > due:
            debt.append({"ref": r["ref"], "field": r.get("field"), "class": r["class"], "seen": seen.isoformat(),
                         "due": due.isoformat()})
    doc["debt"] = sorted(debt, key=lambda d: (d["seen"], d["ref"], str(d["field"])))
    counts["debt"] = len(doc["debt"])
    doc["hook_line"] = hook_line(counts["pending"], counts["drifted"], doc["as_of"])
    return doc


# === Fold B3 (B3-P0): the write path's pure contracts. Appended; nothing above this line changed. ================
#
# `apply_plan` (ado_sync_apply.py, B3-P2) reports through `apply_result`. The comment drafter (ado_sync_comments.py,
# B3-P3) keys every row with `idem_key`, refuses with `comment_refusal` and fingerprints with `text_sha` (its own
# `idem_key` and `text_sha` are these two). `apply` refuses a whole plan whose comments would post under another
# name with `identity_refusal`, and the design §7 recovery on an unknown outcome is `recovered_comment`. Pure like
# the rest: the caller reads the ledger, the board and the config, and hands plain values in.

# --- comment events and idempotency keys ----------------------------------------------------------------------

# The closed set of comment events (design §8a; `comments.events` in templates/ado/ado.yaml and its shape file —
# pinned by test). A `--event` outside it is refused `event_unknown`.
COMMENT_EVENTS: Final = ("handoff", "spec_deferred", "decision_resolved", "sprint_carried", "gate_passed",
                         "verdict_recorded", "finding_disposition", "sprint_dropped", "review_summary", "pr_linked",
                         "spec_merged")
AD_HOC: Final = "ad_hoc"  # a person's own `comment --message` with no `--event`: keyed like an event, no template

# event -> (key template, its parts in order). The key is a comment row's identity across plans: a `commented`
# ledger line carrying it means the event is on the board and is never drafted again. Free text never enters a
# key: a deferral's reason is reduced to the first 8 hex of its sha256, an ad hoc message to its `text_sha`.
IDEM_KEY_RULES: Final[dict[str, tuple[str, tuple[str, ...]]]] = {
    "handoff": ("handoff:{ref}:{ts}", ("ref", "ts")),
    "spec_deferred": ("deferred:{ref}:{reason}", ("ref", "reason")),
    "decision_resolved": ("decision:{decision}:decided:{date}", ("decision", "date")),
    "sprint_carried": ("carried:{ref}:{from_sprint}:{to_sprint}", ("ref", "from_sprint", "to_sprint")),
    "gate_passed": ("gate:{phase}:{signoff_date}", ("phase", "signoff_date")),
    "verdict_recorded": ("verdict:{ref}:{lens}:{verdict}:{ts}", ("ref", "lens", "verdict", "ts")),
    "finding_disposition": ("finding:{fp}:{disposition}", ("fp", "disposition")),
    "sprint_dropped": ("dropped:{ref}:{sprint}", ("ref", "sprint")),
    "review_summary": ("review:{ref}:{round}", ("ref", "round")),
    "pr_linked": ("pr:{ref}:{pr}", ("ref", "pr")),
    "spec_merged": ("merged:{ref}", ("ref",)),
    AD_HOC: ("comment:{ref}:{text}", ("ref", "text")),
}
TARGET_RE: Final = re.compile(r"^(?:sdlc:[a-z]+:[A-Za-z0-9-]+|#[1-9]\d*)$")  # `comment <ref|#id>`
_KEY_TOKEN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]*$")
_DECISION_ID: Final = re.compile(r"^DL-\d+$")
_DAY: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_COUNT_TEXT: Final = re.compile(r"^[1-9]\d*$")
_DAY_PARTS: Final = ("date", "signoff_date")
_COUNT_PARTS: Final = ("round", "pr")


def _is_count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


def _key_part(event: str, name: str, value) -> str:
    if name == "ref":
        pattern = TARGET_RE if event == AD_HOC else bc.REF_RE
        if isinstance(value, str) and pattern.fullmatch(value):
            return value
        raise ValueError(f"{event}: ref {value!r} is not an sdlc:<kind>:<id> ref"
                         + (" or a #<work item>" if event == AD_HOC else ""))
    if name in ("reason", "text"):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{event}: {name} must be non-empty text (it is hashed, never written)")
        return _sha(value.strip())[:8] if name == "reason" else text_sha(value)
    if name in _COUNT_PARTS:
        if _is_count(value) or (isinstance(value, str) and _COUNT_TEXT.fullmatch(value)):
            return str(int(value))
        raise ValueError(f"{event}: {name} must be a positive integer, not {value!r}")
    if name == "decision":
        pattern, what = _DECISION_ID, "a DL-<n> id"
    elif name in _DAY_PARTS:
        pattern, what = _DAY, "a YYYY-MM-DD day"
    else:
        pattern, what = _KEY_TOKEN, "one token (letters, digits, ._:+-)"
    if isinstance(value, str) and pattern.fullmatch(value):
        return value
    raise ValueError(f"{event}: {name} {value!r} is not {what}")


def idem_key(event: str, **parts) -> str:
    """The idempotency key of one comment row (design §8a): `handoff:sdlc:spec:0004:2026-10-12T08:14Z`.

    ValueError on an event outside `IDEM_KEY_RULES`, a missing or unexpected part, or a part that is not what its
    name says: `ref` an `sdlc:<kind>:<id>` ref (an ad hoc comment may also target `#<work item>`), `decision` a
    `DL-<n>` id, `date`/`signoff_date` a `YYYY-MM-DD` day, `round`/`pr` a positive integer, any other part one
    token (letters, digits, `._:+-`, no space). `reason` and `text` are hashed — the key never carries what a person
    wrote — and every key passes `ledger_entry` (no e-mail address, no GUID)."""
    if event not in IDEM_KEY_RULES:
        raise ValueError(f"unknown comment event {event!r}; events are COMMENT_EVENTS (or {AD_HOC!r})")
    template, names = IDEM_KEY_RULES[event]
    missing = [n for n in names if n not in parts]
    extra = sorted(set(parts) - set(names))
    if missing or extra:
        raise ValueError(f"{event} key takes {', '.join(names)}"
                         + (f"; missing {', '.join(missing)}" if missing else "")
                         + (f"; unexpected {', '.join(extra)}" if extra else ""))
    key = template.format(**{n: _key_part(event, n, parts[n]) for n in names})
    if bc.EMAIL_RE.search(key) or _GUID_ANYWHERE.search(key):
        raise ValueError(f"{event}: a key may not carry an e-mail address or a GUID")
    return key


def commented_keys(ledger: list[dict]) -> frozenset[str]:
    """The idempotency keys already on the board: the `idem_key` of every `commented` line (a recovered post is one
    too). A `comment_refused` line is not: a refused row may be drafted again once the reason is gone."""
    return frozenset(e["idem_key"] for e in ledger if isinstance(e, dict) and e.get("event") == "commented"
                     and isinstance(e.get("idem_key"), str))


def budget_used(ledger: list[dict], work_item: int) -> int:
    """How many plugin comments this clone's ledger has posted on one item (`comments.per_item_budget`). Always an
    integer — the ledger was read, so 0 is honest. A `claimed` trailer from another clone is never counted."""
    return sum(1 for e in ledger if isinstance(e, dict) and e.get("event") == "commented"
               and e.get("work_item") == work_item and not isinstance(e.get("work_item"), bool))


# --- the trailer and text_sha ---------------------------------------------------------------------------------

TRAILER_MODES: Final = ("none", "hash", "drafted")       # `comments.trailer` (templates/ado/_schema.yaml, pinned)
COMMENT_TRANSPORTS: Final = ("comments-api", "history")  # `comments.transport`
DRAFTED_WORDS: Final = "drafted with Shepherd"           # the `drafted` trailer's board-visible words (brand rule)
# ` · sprd <12hex>` (K27) or ` · drafted with Shepherd · sprd <12hex>`, at the very end of the last line.
TRAILER_RE: Final = re.compile(r"[ \t]*·[ \t]*(?:" + re.escape(DRAFTED_WORDS) + r"[ \t]*·[ \t]*)?"
                               + re.escape(bc.TRAILER_TOKEN) + r"[ \t]+([0-9a-f]{12})[ \t]*\Z")


def _normalised(text) -> str:
    if not isinstance(text, str):
        raise ValueError(f"comment text must be a str, not {type(text).__name__}")
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def with_trailer(body: str, plan: str | None, mode: str) -> str:
    """The text as posted: `body` with the `mode` trailer appended to its last line — `none` (body only), `hash`
    (` · sprd <plan>`) or `drafted` (` · drafted with Shepherd · sprd <plan>`). ValueError on another mode or, for
    a trailed mode, a `plan` that is not 12 lower-case hex."""
    if mode not in TRAILER_MODES:
        raise ValueError(f"trailer mode {mode!r} is not one of {', '.join(TRAILER_MODES)}")
    if not isinstance(body, str):
        raise ValueError("comment body must be a str")
    text = body.rstrip()
    if mode == "none":
        return text
    if not (isinstance(plan, str) and bc.HASH_RE.fullmatch(plan)):
        raise ValueError(f"a {mode} trailer needs the 12-hex plan hash, not {plan!r}")
    middle = f"{DRAFTED_WORDS} · " if mode == "drafted" else ""
    return f"{text} · {middle}{bc.TRAILER_TOKEN} {plan}"


def strip_trailer(text: str) -> tuple[str, str | None]:
    """(body, plan hash | None): the text with line endings unified and outer whitespace trimmed, less a plugin
    trailer at its very end. A `· sprd <hash>` anywhere else is the person's text and stays."""
    norm = _normalised(text)
    found = TRAILER_RE.search(norm)
    if not found:
        return norm, None
    return norm[:found.start()].rstrip(), found.group(1)


def text_sha(text: str) -> str:
    """The first 12 hex of sha256 over a comment's BODY: line endings unified, outer whitespace trimmed and a plugin
    trailer removed first, so a plan row (drafted before its plan hash exists) and the comment the board later lists
    (trailed with that hash) agree under every trailer mode. Mandatory on every comment row, `trailer: none`
    included: it is what the recovery re-list matches. (`ado_discussion_map`'s `text_sha` is a different thing — a
    change detector over the raw text.) ValueError on anything that is not a str."""
    body, _ = strip_trailer(text)
    return _sha(body)[:12]


# --- comment refusals (boards_contract.COMMENT_REFUSALS) ------------------------------------------------------

NEEDS_DISPOSITION_CLASSES: Final = ("DELETED_IN_ADO", "RETYPED")
# Every COMMENT_REFUSALS member has exactly one rule (pinned by test): these six are decided while drafting, in this
# order (the first that applies is the row's refusal); the other three only at apply, where the posture is read and
# the executing identity is known.
COMMENT_DRAFT_REFUSALS: Final = ("ai_actor", "event_unknown", "needs_disposition", "email_in_text", "max_chars",
                                 "budget")
COMMENT_APPLY_REFUSALS: Final = ("posture", "identity_unknown", "identity_mismatch")
_ANY_PLAN: Final = "0" * 12  # a trailer is as long for every plan, so the length can be judged before the hash


def comment_refusal(text: str, *, by: str, agent_stems: frozenset[str], event: str | None = None, max_chars: int,
                    trailer: str = "hash", budget_used: int, budget: int, drift_class: str | None = None) -> str | None:
    """The `COMMENT_DRAFT_REFUSALS` member a drafted comment row is refused for, or None. In order: `ai_actor`
    (`ai_by` on `--by`), `event_unknown` (an `event` outside `COMMENT_EVENTS`; None is an ad hoc comment),
    `needs_disposition` (the item is `DELETED_IN_ADO` or `RETYPED`), `email_in_text` (any address — a `@handle` is
    not one), `max_chars` (the text as posted, trailer included, over `comments.max_chars`), `budget`
    (`budget_used` already at `comments.per_item_budget`). An empty message is not a refusal but an illegal
    request (the verb exits 1): ValueError, as for a count that was not counted."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("an empty comment is not a refusal: the verb exits 1 (message empty)")
    if trailer not in TRAILER_MODES:
        raise ValueError(f"trailer mode {trailer!r} is not one of {', '.join(TRAILER_MODES)}")
    if not _is_count(max_chars) or not _is_count(budget):
        raise ValueError("max_chars and budget must be positive integers")
    if isinstance(budget_used, bool) or not isinstance(budget_used, int) or budget_used < 0:
        raise ValueError(f"budget_used must be a counted integer (0 or more), not {budget_used!r}")
    if ai_by(by, agent_stems):
        return "ai_actor"
    if event is not None and event not in COMMENT_EVENTS:
        return "event_unknown"
    if drift_class in NEEDS_DISPOSITION_CLASSES:
        return "needs_disposition"
    if bc.EMAIL_RE.search(text):
        return "email_in_text"
    if len(with_trailer(text, _ANY_PLAN, trailer)) > max_chars:
        return "max_chars"
    if budget_used >= budget:
        return "budget"
    return None


# --- the executing identity -------------------------------------------------------------------------------------

SERVICE_PRINCIPAL_DESCRIPTOR: Final = "Microsoft.VisualStudio.Services.Claims.AadServicePrincipal"


def executing_identity(connection_data: dict, roster_emails: dict[str, str]) -> dict:
    """Who `az` is signed in as, from a `connectionData` document: `{"handle", "id", "service_principal"}`.

    `handle` is the roster's `@handle` for the sign-in account (`authenticatedUser.properties.Account`, looked up
    lower-cased in `roster_emails`, as `validate_team.people_by_email` builds it) or None; `id` the identity id a
    posted comment's `createdBy.id` is compared with (`me.json`); `service_principal` is True when the descriptor
    names an AAD service principal, or there is no account and the display name is a client id. The account and
    the display name are read and dropped. ValueError when there is no `authenticatedUser` object."""
    user = connection_data.get("authenticatedUser") if isinstance(connection_data, dict) else None
    if not isinstance(user, dict):
        raise ValueError("connectionData has no authenticatedUser object")
    properties = user.get("properties") if isinstance(user.get("properties"), dict) else {}
    account = properties.get("Account")
    email = account.get("$value") if isinstance(account, dict) else None
    handle = None
    if isinstance(email, str) and email.strip() and isinstance(roster_emails, dict):
        found = roster_emails.get(email.strip().lower())
        handle = found if isinstance(found, str) and bc.HANDLE_RE.fullmatch(found) else None
    ident_id = user.get("id") if isinstance(user.get("id"), str) and user.get("id") else None
    name = user.get("providerDisplayName")
    principal = (str(user.get("descriptor") or "").startswith(SERVICE_PRINCIPAL_DESCRIPTOR)
                 or (email is None and isinstance(name, str) and bool(_GUID_ANYWHERE.fullmatch(name.strip()))))
    return {"handle": handle, "id": ident_id, "service_principal": principal}


def identity_refusal(by_handle: str | None, me_handle: str | None) -> str | None:
    """`identity_unknown` when either side is not a roster `@handle` (a service principal, an account outside the
    roster, a `--by` the roster does not know), `identity_mismatch` when they differ (case-insensitive), else None:
    a comment is confirmed only into the name of the person `az` is signed in as (design §8a, whole plan, exit 2)."""
    def handle(value):
        return value.casefold() if isinstance(value, str) and bc.HANDLE_RE.fullmatch(value) else None
    by, me = handle(by_handle), handle(me_handle)
    if by is None or me is None:
        return "identity_unknown"
    return None if by == me else "identity_mismatch"


# --- apply results --------------------------------------------------------------------------------------------

APPLY_RESULT_KEYS: Final = ("applied", "failed", "deferred", "refused_reason", "exit")  # the interface sheet's shape
APPLY_ACTIONS: Final = ("create", "update", "comment")
# == ado_wit_map.ERROR_CLASSES (pinned by test; the model imports no ado_* module)
WRITE_ERROR_CLASSES: Final = ("conflict", "rule", "permission", "throttled", "not_found", "unknown")
# A failed row's class: what the write's stderr reads as, or one of apply's own two — a posted comment whose
# `createdBy` is not `--by` (ledgered, row closed), and a write that landed but whose ledger line could not be
# appended (`DRIFT`).
FAILURE_CLASSES: Final = (*WRITE_ERROR_CLASSES, "created_by_mismatch", "drift")
STOP_CLASSES: Final = ("permission", "throttled", "drift")  # the run stops; every later row is deferred `stopped`
RECOVER_CLASSES: Final = ("unknown",)  # a timeout or an unread non-2xx after a possible commit: re-list, never re-post
DEFER_REASONS: Final = ("limit", "writes_per_run", "stopped", "parent_failed")
# Whole-plan refusals (exit 2, nothing sent): the comment vocabulary plus apply's own two.
APPLY_REFUSALS: Final = (*bc.COMMENT_REFUSALS, "forbidden_field", "first_seed")


def _apply_row(part: str, row) -> dict:
    if not isinstance(row, dict):
        raise ValueError(f"an {part} row must be a dict")
    action, ref, wid = row.get("action"), row.get("ref"), row.get("work_item")
    if action not in APPLY_ACTIONS:
        raise ValueError(f"{part} row action {action!r} is not one of {', '.join(APPLY_ACTIONS)}")
    if ref is None:
        if not (action == "comment" and _is_count(wid)):
            raise ValueError(f"{part} row: only a comment on a #<work item> may have no ref")
    elif not (isinstance(ref, str) and bc.REF_RE.fullmatch(ref)):
        raise ValueError(f"{part} row ref {ref!r} is not an sdlc:<kind>:<id> ref")
    if "recovered" in row and (action != "comment" or not isinstance(row["recovered"], bool)):
        raise ValueError(f"{part} row: recovered is a bool on a comment row only")
    if part == "applied":
        if not _is_count(wid):
            raise ValueError(f"applied row work_item must be a positive integer, not {wid!r}")
        rev = row.get("rev_after")
        if rev is not None and not _is_count(rev):
            raise ValueError(f"applied row rev_after must be a positive integer or None, not {rev!r}")
        if action == "comment":
            transport = row.get("transport")
            if transport not in COMMENT_TRANSPORTS:
                raise ValueError(f"applied comment transport {transport!r} is not one of "
                                 f"{', '.join(COMMENT_TRANSPORTS)}")
            if transport == "comments-api" and not _is_count(row.get("comment_id")):
                raise ValueError("an applied comments-api row carries the comment_id the board answered with")
    elif part == "failed":
        if row.get("class") not in FAILURE_CLASSES:
            raise ValueError(f"failed row class {row.get('class')!r} is not one of FAILURE_CLASSES")
        if wid is not None and not _is_count(wid):
            raise ValueError(f"failed row work_item must be a positive integer or None, not {wid!r}")
    elif row.get("why") not in DEFER_REASONS:
        raise ValueError(f"deferred row why {row.get('why')!r} is not one of {', '.join(DEFER_REASONS)}")
    for text in _strings(row):
        if bc.EMAIL_RE.search(text) or _GUID_ANYWHERE.search(text):
            raise ValueError(f"an {part} row may not carry an e-mail address or a GUID (never copy az stderr)")
    return _canon(row)


def apply_result(*, applied=(), failed=(), deferred=(), refused_reason: str | None = None) -> dict:
    """What `apply_plan` returns: exactly `APPLY_RESULT_KEYS`, rows checked and copied, `exit` derived.

    `applied` rows: `{"ref", "action", "work_item", "rev_after"}` (+ a comment's `transport`, `comment_id` on the
    comments API, `recovered`); `failed` rows: `{"ref", "action", "work_item" | None, "class"}`; `deferred` rows:
    `{"ref", "action", "why"}`. `ref` is an `sdlc:` ref (None only for a comment on a `#<work item>`). Exit 2 when
    `refused_reason` (an `APPLY_REFUSALS` member) is set — and then nothing was sent, so `applied` and `failed` must
    be empty; else 1 when any row failed (a stop, a conflict, a `DRIFT`); else 0 (a row deferred by `--limit` or
    `writes_per_run` is the person's choice, not a failure). ValueError on a row outside its shape, or any e-mail
    address or GUID in it: raw `az` stderr can name people and never rides in a result."""
    if refused_reason is not None and refused_reason not in APPLY_REFUSALS:
        raise ValueError(f"refused_reason {refused_reason!r} is not one of APPLY_REFUSALS")
    out = {"applied": [_apply_row("applied", r) for r in applied],
           "failed": [_apply_row("failed", r) for r in failed],
           "deferred": [_apply_row("deferred", r) for r in deferred],
           "refused_reason": refused_reason}
    if refused_reason is not None and (out["applied"] or out["failed"]):
        raise ValueError("a refused plan sent nothing: it has no applied or failed row")
    out["exit"] = 2 if refused_reason is not None else 1 if out["failed"] else 0
    return out


# --- recovery on an unknown outcome (design §7) --------------------------------------------------------------

RECOVERY_WINDOW_MINUTES: Final = 10
RECENT_COMMENTS_QUERY: Final = {"order": "desc", "$top": "20"}  # the re-list; == wit/comments_recent's `_command`


def _instant(ts) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def recovered_comment(want_sha: str, listed: list, me_id: str | None, sent_at: str) -> dict | None:
    """The comment an unknown-outcome POST already created, or None: the first of `listed` (the raw re-list,
    `RECENT_COMMENTS_QUERY`, newest first) that is not deleted, was created by `me_id` (`me.json`'s identity id,
    case-insensitive) within `RECOVERY_WINDOW_MINUTES` of `sent_at`, and whose `text_sha` is `want_sha` (the plan
    row's). Returns `{"comment_id", "version", "recovered": True}` — ledgered as `commented{recovered: true}`
    instead of a second POST. None with an unknown `me_id`: authorship that cannot be proved is never claimed.
    ValueError on a `want_sha` that is not 12 hex or a `sent_at` that is not a zoned ISO time."""
    if not (isinstance(want_sha, str) and bc.HASH_RE.fullmatch(want_sha)):
        raise ValueError(f"want_sha must be a 12-hex text_sha, not {want_sha!r}")
    sent = _instant(sent_at)
    if sent is None:
        raise ValueError(f"sent_at must be an ISO time with a zone, not {sent_at!r}")
    if not isinstance(me_id, str) or not me_id.strip():
        return None
    for c in listed if isinstance(listed, list) else []:
        if not isinstance(c, dict) or c.get("isDeleted") is True:
            continue
        cid = c["id"] if "id" in c else c.get("commentId")
        author = c.get("createdBy").get("id") if isinstance(c.get("createdBy"), dict) else None
        made = _instant(c.get("createdDate"))
        if (not _is_count(cid) or not isinstance(author, str) or author.casefold() != me_id.strip().casefold()
                or made is None or abs((made - sent).total_seconds()) > RECOVERY_WINDOW_MINUTES * 60):
            continue
        if isinstance(c.get("text"), str) and text_sha(c["text"]) == want_sha:
            version = c.get("version")
            return {"comment_id": cid, "version": version if _is_count(version) else None, "recovered": True}
    return None


# === Fold B4 (B4-P0): the reconcile disposition enums. Appended; nothing above this line changed. ================
#
# `reconcile <ref> --field F --take ado|sdlc|ack|not-drift` (ado_sync_reconcile.py, B4-P1a) records a disposition on
# a drift row in these words. The machine is the design's §8 one, keyed by the state a row starts in: an ordinary
# drift row starts OPEN; a CONFLICT row (a RETYPED one reads as a CONFLICT: it requires a take), a DELETED_IN_ADO row
# and an ORPHAN_IN_REPO row each start in their own state with a narrower set. `validate_disposition` and
# `counts_as_open` above decide with `DISPOSITIONS_BY_CLASS` / `DEFAULT_DISPOSITIONS`; a test holds this table equal
# to theirs for every drift class and every word, so the named machine and the honest counting cannot drift apart.

DISPOSITION_MACHINE: Final[dict[str, tuple[str, ...]]] = {
    "OPEN": ("TAKE_ADO", "TAKE_SDLC", "ACKNOWLEDGED", "NOT_DRIFT"),
    "CONFLICT": ("TAKE_ADO", "TAKE_SDLC"),
    "DELETED_IN_ADO": ("RECREATE", "UNLINK", "ACKNOWLEDGED"),
    "ORPHAN_IN_REPO": ("UNLINK", "RELINK"),
}
CONFLICT_CLASSES: Final = ("CONFLICT", "RETYPED")  # both start in the CONFLICT state
# What a disposition must carry to take a row off the books (else it still counts as open): TAKE_* a recorded child
# exit of 0, ACKNOWLEDGED a named human owner, NOT_DRIFT a reason, RELINK an sdlc:<kind>:<id> ref; None = the word.
DISPOSITION_NEEDS: Final[dict[str, str | None]] = {
    "TAKE_ADO": "child_exit", "TAKE_SDLC": "child_exit", "ACKNOWLEDGED": "owner", "NOT_DRIFT": "reason",
    "RECREATE": None, "UNLINK": None, "RELINK": "relink_ref",
}
# `reconcile --take` (the build kit's verb table; studio/shared/adoVerbArgv.ts `TAKES` is held to this order by
# test). The four words name the OPEN row's four dispositions; RECREATE, UNLINK and RELINK have no take word.
RECONCILE_TAKES: Final = ("ado", "sdlc", "ack", "not-drift")
TAKE_DISPOSITION: Final[dict[str, str]] = {"ado": "TAKE_ADO", "sdlc": "TAKE_SDLC", "ack": "ACKNOWLEDGED",
                                           "not-drift": "NOT_DRIFT"}


def machine_state(cls) -> str | None:
    """The state a drift row of class `cls` starts in: "CONFLICT" for `CONFLICT_CLASSES`, the class itself for
    DELETED_IN_ADO and ORPHAN_IN_REPO, "OPEN" for every other drift class; None for a class with nothing to dispose
    of (`NOT_DRIFT_CLASSES`) or a value that is not a drift class."""
    if cls not in DRIFT_CLASSES or cls in NOT_DRIFT_CLASSES:
        return None
    if cls in CONFLICT_CLASSES:
        return "CONFLICT"
    if cls in ("DELETED_IN_ADO", "ORPHAN_IN_REPO"):
        return cls
    return "OPEN"


def dispositions_for(cls) -> tuple[str, ...]:
    """The dispositions a drift row of class `cls` may take, in machine order; () when there is nothing to dispose
    of. Equal to what `validate_disposition` allows for the class."""
    state = machine_state(cls)
    return DISPOSITION_MACHINE[state] if state else ()


def disposition_for_take(cls, take) -> str | None:
    """The disposition `reconcile --take <take>` records on a row of class `cls`, or None when `take` is not one of
    `RECONCILE_TAKES` (case-sensitive, as argparse's choices are) or its disposition is not one the machine allows
    for the class — `ack`/`not-drift` on a CONFLICT, `ado`/`sdlc`/`not-drift` on a DELETED_IN_ADO row, any take on
    an ORPHAN_IN_REPO row or on a row with nothing to dispose of. The caller refuses that take; it never guesses."""
    disp = TAKE_DISPOSITION.get(take) if isinstance(take, str) else None
    return disp if disp is not None and disp in dispositions_for(cls) else None


# === Fold B5 (B5-P0): the breadth kinds. Appended; nothing above this line changed. ================================
#
# Fold B5 (spec 0038) projects five more kinds, each opt-in (none is in the starter config's `kinds:`): the lifecycle
# singleton, NFRs, business rules (`BR-NN`), discovery questions (`Q-NN`) and measurements. Their ownership, read from
# the design's §6.1 Ownership column:
#   * lifecycle — S all: `state.yaml` is its whole truth, so it uses `boards_contract.OWNERSHIP` as it is (no row).
#   * nfr — the row below: the board owns State; Description and AcceptanceCriteria are written once at create and come
#     back only as `.proposed` text (D32), so both are C. Title and the plugin tags stay S.
#   * rule, question, measurement — their rows above (B2-P0) already say it: State is the board's, and a rule's
#     Description is C. They do not move.
# `nfr` is the last member of `boards_contract.KINDS` (appended by this package); it is a leaf under its Domain, never a
# parent, so `boards_contract.TREE_ORDER` does not name it.

KIND_OWNERSHIP["nfr"] = {"System.State": "A", "System.Description": "C",
                         "Microsoft.VSTS.Common.AcceptanceCriteria": "C"}  # C: text -> .proposed (D32)

# The kinds Fold B5 adds sources for, in the order the design's §6.1 lists them; each is opt-in.
BREADTH_KINDS: Final = ("lifecycle", "nfr", "rule", "question", "measurement")


# === Fold B6 (B6-P0): the sync verb's contracts. Appended; nothing above this line changed. ========================
#
# Fold B6 (spec 0040) adds one read verb, `ado_sync.py sync`, that runs the mirror's reads in one pass so a person can
# catch up with the board in one step: the fields pull, then the drift read from that pull's own rows (the board is
# never asked twice), then — only when the person gave `--discussion` — the discussion pull, then the plan. Three
# contracts are pinned here so the CLI (B6-P1), the command prose (B6-P2) and the desktop app (B6-P3) agree:
#   * SYNC_STAGES — the stage names, in the order `sync` runs them (and the keys its `--json` document uses).
#   * apply_next_line(plan) — the ONE footer every verb that drafts a plan prints (`comment`, `plan`, `sync`); a
#     plan-only clone prints none (the apply is not offered there), so no footer is ever printed without a hash.
#   * SYNC_NODATA — the `sync --json` document when NOTHING could be read (golden:
#     scripts/tests/golden/ado_sync_unavailable.json). Every stage says it is unavailable and every count is None:
#     nothing was measured, so nothing reads 0 (house rule 2).

SYNC_STAGES: Final = ("pull", "drift", "discussion", "plan")


def apply_next_line(plan: str) -> str:
    """The one golden footer under a plan a person may send (`comment`, `plan` and `sync` all print it): the line
    below with the plan's 12-hex hash substituted for `{plan}`. Anything that is not exactly a 12-hex hash
    (`boards_contract.HASH_RE`) raises ValueError: a footer never offers an apply it cannot name."""
    if not isinstance(plan, str) or not bc.HASH_RE.fullmatch(plan):
        raise ValueError(f"plan must be the plan's 12-hex hash, not {plan!r}")
    return f"Next: `ado_sync.py apply --confirm {plan} --by <you>` sends it, as whoever az is signed in as"


# The `sync --json` document when nothing could be read: no stage ran to a result, so `reason`, `as_of`, `scope`,
# `counts`, `next`, `hook_line` and `drift_error` are None and `discussion` (which runs only on `--discussion`) is None.
SYNC_NODATA: Final[dict] = {
    "ok": True,
    "unavailable": True,
    "reason": None,
    "verb": "sync",
    "as_of": None,
    "scope": None,
    "pull": {"unavailable": True, "reason": None},
    "drift": {"unavailable": True, "reason": None},
    "discussion": None,
    "plan": {"unavailable": True, "reason": None},
    "counts": None,
    "next": None,
    "hook_line": None,
    "drift_error": None,
}
