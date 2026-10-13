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
    subset of `projection["tags"]` — nothing else. No item yet: every field is an `add` (`NEVER_PUSHED`). An
    existing item: only an `S` field (by `ownership`; a pushed field the map does not name is the repo's) that
    differs after normalisation (trimmed text, case-folded e-mail, tag sets, the Description's marker block) is an
    op (`SDLC_OWNED_DRIFT`); an `A`/`C` field is the board's after create, so it never is. A field the remote
    document does not carry is not compared (the B2-P1 patch builder reads the whole item)."""
    want = dict(projection.get("fields") or {})
    tags = sorted(_plugin_tags(projection.get("tags")))
    if remote is None:
        ops = [{"op": "add", "path": f"/fields/{ref}", "old": None, "new": value, "class": "NEVER_PUSHED"}
               for ref, value in want.items()]
        if tags:
            ops.append({"op": "add", "path": "/fields/System.Tags", "old": None, "new": "; ".join(tags),
                        "class": "NEVER_PUSHED"})
        return sorted(ops, key=lambda o: o["path"])
    ops = []
    for ref, new in want.items():
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
