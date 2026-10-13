"""The findings source for the Boards mirror: review findings as Bug (or Issue) work items (B4-P1b).

`/sprd-review` records every finding in `.sdlc/metrics/findings-log.jsonl`; `record_findings.py` keeps it
append-only, one line per finding per review round, so a finding can be traced across rounds. This module reads
that ledger with `record_findings.load_ledger` and `findings_model`, takes the *current* line of each finding
(the latest one for its fingerprint) and returns one projection per finding, in the shape
`ado_sync_sources.projections` documents. It only reads: it writes no file, spawns nothing, makes no network call
and refuses a ledger that resolves outside `repo_root`.

It is a library part, usable two ways like every part of the plugin:

  * Workflow mode — `ado_sync.py --state .sdlc/state.yaml …` hands in the repository root, the parsed
    `.sdlc/ado.yaml` and the discovered `.sdlc/ado/schema.json`.
  * Standalone — `load_findings(repo_root)` on any folder that has the ledger; `cfg` and `schema` default to
    `{}`. What the missing process would have supplied (a work item type, a state) is left out and named in
    the projection's `notes`.

What a finding becomes (design §6.1, "Finding"):

    ref, id       `sdlc:finding:<fp>` and `<fp>`: the first eight hex digits of the sha-256 of the ledger's
                  fingerprint. A fingerprint is `<category>:<file>`, which is not a legal ref, and eight digits
                  are what the `finding_disposition` comment (`ado_sync_comments`) already calls the finding
                  (`Finding <fp> marked fixed.`), so a person can match the comment to the item. Two
                  fingerprints that share the eight digits are refused naming both, never merged.
    title         `[<category>] <fingerprint>` (the ledger's own category and fingerprint), one line, cut to
                  255 characters with a note. `fields["System.Title"]` is the cut form; `title` is whole.
    type          CRITICAL and HIGH are the process's `BugCategory` default type; MEDIUM, LOW and a severity the
                  ledger does not hold are the configured `types.finding`. A process with no usable
                  `BugCategory` falls back to `types.finding` with a note; with neither, no type is named and
                  no state is set: a type is never guessed. `fields["type_name"]` and `fields["type_route"]`
                  (`"BugCategory"` or `"types.finding"`) say which was chosen. They are neutral keys, not
                  reference names, so `ado_sync_model.diff` never turns them into an op; they are present
                  together or not at all.
    state         from the disposition, by the status words `ado_schema_map.STATUS_RULES` knows, resolved on the
                  chosen type with `states.finding.<status>` from the config:
                      OPEN, POSTPONED          open      (a postponed finding is debt, not resolution)
                      FIXED                    closed
                      SPLIT                    deferred  (its work is tracked on the spec it names)
                      ACCEPTED_RISK            closed
                  A SPLIT without a spec id *and* an owner, or an ACCEPTED_RISK missing its evidence or signed
                  by an AI, is not off the books (`findings_model.validate_disposition`): it counts as debt, so
                  it is open here too, and a note says why. A disposition the ledger has no word for sets no
                  state. The board owns State once the item exists (`ado_sync_model.KIND_OWNERSHIP`); this
                  value is what a create sends.
    status        the repository's own word: the lower-case disposition (`open`, `fixed`, `split`,
                  `accepted-risk`, `postponed`), or None for a disposition the ledger has no word for.
    tags          the item's own `sdlc:finding:<fp>` and, when the ledger holds a known severity,
                  `severity:<CRITICAL|HIGH|MEDIUM|LOW>`.
    parent_ref    None: a finding hangs off no item.
    related_refs  a SPLIT's `split_to`, when it names a spec (`0042`, `spec 0042`, `sdlc:spec:0042`):
                  `["sdlc:spec:0042"]`; otherwise [].
    source_path   the ledger. `source_sha` is the first 12 hex of the sha-256 of the finding's mirrored facts
                  (fingerprint, category, severity, disposition, whether it is off the books, the spec it was
                  split to), not of the ledger line: a later review round that re-records an unchanged finding,
                  with a new timestamp or a reworded detail, moves nothing, so the repository side only
                  "moves" when something the board shows has changed.

Nothing a reviewer wrote is ever read into a projection. The ledger's `detail`, a disposition's `reason` and
`review_condition`, an `owner` or an `approver` (names, sometimes addresses) never reach a field, a tag or a
note: the module does not name those keys. `fields.finding` entries in the config are therefore not applied,
and every row says so. A note says what was left out and why, in sentences about the process or the ledger's
shape, never in the ledger's own words.

Honesty: a thing that is not known is absent or None with a note, never defaulted. No ledger, or an empty one,
is no rows: the kind is on only when there is something to mirror.

On import the module registers its loader with `ado_sync_sources` (`SOURCES["finding"]`), extend-only: it sets
its one key and touches no other and registers no parent resolver. The module is looked up lazily, as
`ado_sync_sources_tree` does, so the two can be imported in either order. Whoever drives `projections` for the
kind `finding` must import this module first. If `ado_sync_sources` does not exist, or has no `SOURCES` table,
nothing is registered and `_register()` may be called again.
"""

import hashlib
import importlib
import json
import re
import sys
from pathlib import Path

import boards_contract as bc
import findings_model as fm
from ado_schema_map import resolve_state, resolve_type
from record_findings import findings_rows, load_ledger

__all__ = ["load_findings", "short_fingerprint"]

LEDGER_REL = ".sdlc/metrics/findings-log.jsonl"
MAX_TITLE = 255                     # the work item title limit
SHORT = 8                           # hex digits of the fingerprint's sha-256 that name a finding (as the comments do)
BUG_CATEGORY = "BugCategory"
ROUTE_FINDING = "types.finding"

# a disposition -> the word `ado_schema_map.STATUS_RULES` knows; SPLIT and ACCEPTED_RISK only when off the books
_RULE_STATUS = {"OPEN": "open", "POSTPONED": "open", "FIXED": "closed", "SPLIT": "deferred", "ACCEPTED_RISK": "closed"}
_NEEDS_EVIDENCE = ("SPLIT", "ACCEPTED_RISK")
_SPLIT_TO = re.compile(r"(?:spec[ -]*)?(\d{4})", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]+")


# --- small helpers --------------------------------------------------------------------------------------------

def _one_line(text) -> str:
    """The text on one line: control characters (an escape, a tab, a newline) become a space, runs collapse."""
    return " ".join(_CONTROL.sub(" ", str(text if text is not None else "")).split())


def _named(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def short_fingerprint(fingerprint) -> str:
    """The eight hex digits that name a finding: what the `finding_disposition` comment calls `<fp>`."""
    return hashlib.sha256(str(fingerprint).encode("utf-8")).hexdigest()[:SHORT]


def _split_ref(value) -> str | None:
    """The spec ref a `split_to` names: `0042`, `spec 0042` or `sdlc:spec:0042`. Another kind of ref is not a spec."""
    text = _one_line(value)
    if bc.REF_RE.fullmatch(text):
        return text if text.split(":")[1] == "spec" else None
    found = _SPLIT_TO.fullmatch(text)
    return f"sdlc:spec:{found.group(1)}" if found else None


# --- the ledger -------------------------------------------------------------------------------------------------

def _ledger_rows(root: Path) -> list[dict]:
    """One row per fingerprint, its current state (`record_findings.findings_rows`); [] when there is no ledger.
    A line that is not an object is skipped; one with no fingerprint is given the one `findings_model` derives."""
    path = root / LEDGER_REL
    if not path.is_file():
        return []
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"{LEDGER_REL} resolves outside the repository; it is not read")
    entries = [e for e in load_ledger(path) if isinstance(e, dict)]
    return findings_rows([e if _named(e.get("fingerprint")) else {**e, "fingerprint": fm.fingerprint(e)}
                          for e in entries])


# --- type and state ---------------------------------------------------------------------------------------------

def _bug_type(schema: dict) -> str | None:
    """The default type of the process's `BugCategory`, when the process has one and it is enabled."""
    entry = (schema.get("categories") or {}).get(BUG_CATEGORY)
    name = entry.get("default_type") if isinstance(entry, dict) else None
    info = (schema.get("types") or {}).get(name) if isinstance(name, str) else None
    return name if isinstance(info, dict) and not info.get("disabled") else None


def _type_for(severity: str | None, cfg: dict, schema: dict, notes: list) -> tuple[str | None, str | None]:
    """`(type_name, route)`: CRITICAL and HIGH are the BugCategory default type, everything else the `types.finding`
    pin. `(None, None)` with a note when no type can be named."""
    if severity in fm.DEBT_SEVERITIES:
        name = _bug_type(schema)
        if name is not None:
            return name, BUG_CATEGORY
        notes.append(f"no usable {BUG_CATEGORY} in the process; mirrored as {ROUTE_FINDING}")
    name, why = resolve_type(schema, "finding", cfg)
    if name is None:
        notes.append(f"type not set: {why}")
        return None, None
    return name, ROUTE_FINDING


def _rule_status(disposition: str | None, row: dict, notes: list) -> str | None:
    """The `STATUS_RULES` word a disposition stands for. A SPLIT or ACCEPTED_RISK that is not off the books counts
    as debt, so it is open, and the note says what it lacks (field names only)."""
    if disposition is None:
        notes.append("disposition is not one of OPEN, FIXED, SPLIT, ACCEPTED_RISK, POSTPONED; no state is set")
        return None
    if disposition in _NEEDS_EVIDENCE and not row["off_books"]:
        notes.append(f"{row['off_books_reason']}; it still counts as debt, so the item is mirrored as open")
        return "open"
    return _RULE_STATUS[disposition]


def _state(type_name: str, status: str, cfg: dict, schema: dict, notes: list) -> str | None:
    """The process state a status resolves to on `type_name`, or None with a note: a state is never defaulted.
    `states` is narrowed to `finding`, so a rule written for another kind is not applied to a finding."""
    rules = cfg.get("states")
    own = {"finding": rules["finding"]} if isinstance(rules, dict) and "finding" in rules else {}
    narrowed = {**cfg, "states": own}
    name, reason = resolve_state(schema, type_name, status, narrowed)
    if name is None:
        notes.append(f"state not set: {reason}")
    return name


# --- one finding -> one projection ------------------------------------------------------------------------------

def _projection(row: dict, cfg: dict, schema: dict) -> dict:
    notes: list[str] = []
    fingerprint = row["fingerprint"]
    ident = short_fingerprint(fingerprint)
    ref = f"sdlc:finding:{ident}"
    category = _one_line(row.get("category")) or "uncategorized"
    severity = fm.normalize_severity(row.get("severity"))
    disposition = fm.normalize_disposition(row.get("disposition"))

    title = f"[{category}] {_one_line(fingerprint)}"
    fields = {"System.Title": title}
    if len(title) > MAX_TITLE:
        notes.append(f"title cut to {MAX_TITLE} characters, the work item limit")
        fields["System.Title"] = title[:MAX_TITLE - 1] + "…"

    tags = {ref}
    if severity:
        tags.add(f"severity:{severity}")
    else:
        notes.append("severity is not one of CRITICAL, HIGH, MEDIUM, LOW; no severity tag, and the type is "
                     f"{ROUTE_FINDING}")

    type_name, route = _type_for(severity, cfg, schema, notes)
    if type_name is not None:
        fields["type_name"], fields["type_route"] = type_name, route
    status = _rule_status(disposition, row, notes)
    if type_name is not None and status is not None:
        state = _state(type_name, status, cfg, schema, notes)
        if state:
            fields["System.State"] = state

    related: list[str] = []
    if disposition == "SPLIT":
        split_to = (row.get("evidence") or {}).get("split_to")
        split_ref = _split_ref(split_to)
        if split_ref:
            related.append(split_ref)
        elif _one_line(split_to):
            notes.append("split_to names no spec (a four-digit id or sdlc:spec:<id>); no Related link")

    configured = (cfg.get("fields") or {}).get("finding") if isinstance(cfg.get("fields"), dict) else None
    if configured:
        notes.append("fields.finding is not applied: a finding's fields are its title, its state and its tags; the "
                     "ledger's text never reaches a work item field")

    facts = {"fingerprint": fingerprint, "category": category, "severity": severity, "disposition": disposition,
             "off_books": bool(row["off_books"]), "split_to": related[0] if related else None}
    sha = hashlib.sha256(json.dumps(facts, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return {"ref": ref, "kind": "finding", "id": ident, "title": title,
            "status": disposition.lower().replace("_", "-") if disposition else None, "fields": fields, "tags": tags,
            "parent_ref": None, "parent_note": None, "related_refs": related, "source_path": LEDGER_REL,
            "source_sha": sha, "notes": notes}


def load_findings(repo_root, cfg: dict | None = None, schema: dict | None = None) -> list[dict]:
    """One projection per finding in `.sdlc/metrics/findings-log.jsonl`, in the order each fingerprint first appears.
    `cfg` is the parsed `.sdlc/ado.yaml` and `schema` the discovered process; either may be None or `{}`."""
    root, cfg, schema = Path(repo_root), cfg or {}, schema or {}
    out: list[dict] = []
    seen: dict[str, str] = {}
    for row in _ledger_rows(root):
        projection = _projection(row, cfg, schema)
        ident = projection["id"]
        if ident in seen:
            raise ValueError(f"the findings {seen[ident]!r} and {row['fingerprint']!r} share the short form {ident}; "
                             "a finding is named once")
        seen[ident] = row["fingerprint"]
        out.append(projection)
    return out


# --- registration -----------------------------------------------------------------------------------------

def _register(hooks=None) -> bool:
    """Add `SOURCES["finding"]` to `ado_sync_sources`' extend-only table; True when it was added.

    `hooks` is the module (or any object with a `SOURCES` dict); by default it is looked up in `sys.modules` and
    imported lazily. A module that does not exist yet, or lacks the table, registers nothing and returns False —
    a real import error inside it is not swallowed. Only this module's own key is set."""
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
    sources["finding"] = load_findings
    return True


_register()
