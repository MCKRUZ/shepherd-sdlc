"""The Boards mirror's pure sync model: drift, dispositions, the ledger line, the plan hash, the status (B2-P0).

`scripts/ado_sync_model.py` is what every later verb (`plan`, `pull`, `drift`, `status`, `reconcile`) decides
with, so its rules are pinned here as tables: the design's §8 drift matrix (one row per board change, 14 of
them, `COMMENT` included), the disposition state machine with honest counting, the ledger line that refuses an
e-mail address or a GUID, the stable plan hash, the never-pulled `status --json` document (no integer 0
anywhere: never measured is `None`), the hook line's two forms, and the `--by` check that refuses an AI or an
agent. The module imports only the standard library and four plugin modules (AST test), never an `ado_*`.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import HAND_WRITTEN_PROCESS

import ast
import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

import ado_sync
import ado_sync_model as sm
import boards_contract as bc
from tests import ado_boards_fixtures as abf

# B0 (2026-10-15): the second capture shadowed the item, write and comment fixtures (`WIT_CAPTURED_ITEMS`); this module's
# scenarios pin the hand-written ones' ids and texts, so it reads those (`BOARDS_ITEMS`, tests/ado_boards_fixtures.py).
# The captured answers are exercised in test_boards_captured_items.py.
BOARDS_ITEMS = HAND_WRITTEN_PROCESS

MODULE = Path(sm.__file__)
PLUGIN_ROOT = MODULE.parent.parent
GOLDEN = Path(__file__).resolve().parent / "golden" / "ado_status_nodata.json"
STEMS = frozenset(p.stem for p in (PLUGIN_ROOT / "agents").glob("*.md"))
ALLOWED_IMPORTS = {"re", "hashlib", "json", "datetime", "typing", "boards_contract", "findings_model",
                   "artifact_model", "track_decisions"}

KIM = "kim" + "@corp.com"  # the card's value; assembled so no address literal is committed (house rule 10)
A_GUID = "00000000-0000-0000-0000-000000000003"
TS = "2026-10-12T09:02:00Z"


# --- purity -------------------------------------------------------------------------------------------------

def _imports() -> set[str]:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative imports"
            names.add((node.module or "").split(".")[0])
    return names


def test_imports_only_the_allowlist():
    imported = _imports()
    assert imported <= ALLOWED_IMPORTS, imported - ALLOWED_IMPORTS
    assert not {n for n in imported if n.startswith("ado_")}
    assert {"boards_contract", "findings_model", "track_decisions"} <= imported


def test_module_calls_no_io():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"open", "print", "input", "exec", "eval", "__import__"}, called
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"read_text", "write_text", "mkdir", "unlink", "now", "today", "utcnow"}, attrs


# --- builders -----------------------------------------------------------------------------------------------

PERSON_2 = {"displayName": "Person 2", "uniqueName": "person2@example.com", "id": "00000000-0000-0000-0000-000000000003"}
PERSON_3 = {"displayName": "Person 3", "uniqueName": "person3@example.com", "id": "00000000-0000-0000-0000-000000000004"}
WI = "https://dev.azure.com/contoso/00000000-0000-0000-0000-000000000020/_apis/wit/workItems/"
DESCRIPTION = "<div>team notes</div><!-- sdlc:begin --><p>spec 0004</p><!-- sdlc:end -->"


def projection(kind="spec", status="ready", **over) -> dict:
    p = {"ref": f"sdlc:{kind}:0004", "kind": kind, "id": "0004", "title": "duplicate claim 409", "status": status,
         "fields": {"System.Title": "0004 · duplicate claim 409", "System.State": "Ready",
                    "System.Description": DESCRIPTION},
         "tags": {f"sdlc:{kind}:0004", "sdlc:status:ready"}, "parent_ref": "sdlc:feature:03", "parent_note": None,
         "related_refs": [], "source_path": "specs/0004-duplicate-claim-409.md", "source_sha": "abc1234"}
    p.update(over)
    return p


def ledger_row(proj: dict, rev_after: int = 3, **over) -> dict:
    row = {"ts": TS, "event": "applied", "ref": proj["ref"], "kind": proj["kind"], "work_item": 4521,
           "rev_after": rev_after, "projection_hash": sm.projection_hash(proj)}
    row.update(over)
    return row


def remote(rev: int = 4, **over) -> dict:
    r = {"id": 4521, "rev": rev, "type": "User Story", "state": "Ready", "assigned_to_handle": "@MCKRUZ",
         "iteration": "Claims\\Sprint 7", "area": "Claims\\SDLC", "tags": {"sdlc:spec:0004", "sdlc:status:ready"},
         "title": "0004 · duplicate claim 409", "relations": []}
    r.update(over)
    return r


def update(rev: int, fields: dict | None = None, relations: dict | None = None, by: dict = PERSON_2) -> dict:
    u = {"id": rev, "workItemId": 4521, "rev": rev, "revisedBy": by, "revisedDate": "9999-01-01T00:00:00Z",
         "fields": {"System.Rev": {"oldValue": rev - 1, "newValue": rev},
                    "System.ChangedDate": {"oldValue": "2026-10-11T09:00:00Z", "newValue": "2026-10-12T09:00:00Z"},
                    "System.Watermark": {"oldValue": 40 + rev, "newValue": 41 + rev},
                    **(fields or {})}}
    if relations is not None:
        u["relations"] = relations
    return u


def change(old, new) -> dict:
    return {k: v for k, v in (("oldValue", old), ("newValue", new)) if v is not None}


def link(rel: str, target: int | str, name: str | None = None) -> dict:
    url = target if isinstance(target, str) else f"{WI}{target}"
    return {"rel": rel, "url": url, "attributes": {"name": name or rel}}


# --- the design §8 drift matrix: one row per board change -> its class ---------------------------------------

MATRIX = [
    ("AssignedTo on a draft/ready spec", "spec", "ready",
     {"System.AssignedTo": change(PERSON_2, PERSON_3)}, None, "ADO_OWNED_CHANGE"),
    ("AssignedTo on an in-flight/merged spec", "spec", "in-flight",
     {"System.AssignedTo": change(PERSON_2, PERSON_3)}, None, "SDLC_OWNED_DRIFT"),
    ("IterationPath", "spec", "ready",
     {"System.IterationPath": change("Claims\\Sprint 7", "Claims\\Sprint 8")}, None, "ADO_OWNED_CHANGE"),
    ("spec State", "spec", "ready",
     {"System.State": change("Ready", "Active"), "System.Reason": change("Ready", "Work started")}, None,
     "SDLC_OWNED_DRIFT"),
    ("decision State -> Completed", "decision", "open",
     {"System.State": change("Active", "Closed")}, None, "ADO_OWNED_CHANGE"),
    ("finding State -> Completed", "finding", "OPEN",
     {"System.State": change("Active", "Closed")}, None, "ADO_OWNED_CHANGE"),
    ("Title/Description/AcceptanceCriteria on a C-class item", "decision", "open",
     {"System.Title": change("DL-04 · pick the queue", "DL-04 · pick the message queue")}, None, "ADO_OWNED_CHANGE"),
    ("Title/Description on an S-class item (spec, link mode)", "spec", "ready",
     {"System.Title": change("0004 · duplicate claim 409", "duplicate claims")}, None, "SDLC_OWNED_DRIFT"),
    ("an sdlc:* tag removed", "spec", "ready",
     {"System.Tags": change("customer; sdlc:spec:0004; sdlc:status:ready", "customer; sdlc:status:ready")}, None,
     "SDLC_OWNED_DRIFT"),
    ("Parent link moved", "spec", "ready", None,
     {"added": [link("System.LinkTypes.Hierarchy-Reverse", 4411, "Parent")],
      "removed": [link("System.LinkTypes.Hierarchy-Reverse", 4410, "Parent")]}, "ADO_OWNED_CHANGE"),
    ("other relations removed/added", "spec", "ready", None,
     {"added": [link("System.LinkTypes.Related", 4600, "Related")]}, "RELATION_DRIFT"),
    ("AreaPath changed", "spec", "ready",
     {"System.AreaPath": change("Claims\\SDLC", "Claims\\SDLC\\Intake")}, None, "ADO_OWNED_CHANGE"),
    ("WorkItemType changed", "spec", "ready",
     {"System.WorkItemType": change("User Story", "Bug")}, None, "RETYPED"),
    ("a revision whose only field change is System.History", "spec", "ready",
     {"System.History": change(None, "<div>looks good to me</div>")}, None, "COMMENT"),
]


def test_the_matrix_has_the_fourteen_classified_rows_of_the_design():
    assert len(MATRIX) == 14
    assert {row[-1] for row in MATRIX} <= set(bc.DRIFT_CLASSES)
    assert "COMMENT" in {row[-1] for row in MATRIX}


@pytest.mark.parametrize("label, kind, status, fields, relations, expected", MATRIX, ids=[r[0] for r in MATRIX])
def test_drift_matrix(label, kind, status, fields, relations, expected):
    proj = projection(kind, status)
    got = sm.classify_drift(ledger_row(proj), remote(), proj, [update(4, fields, relations)])
    assert got["class"] == expected, got
    assert got["fields"], "a classified change names its field"
    assert {f["class"] for f in got["fields"]} <= set(bc.DRIFT_CLASSES)
    blob = json.dumps(got)
    assert not bc.EMAIL_RE.search(blob) and "Person " not in blob, "no identity is copied out of an update"
    assert "looks good" not in blob, "comment text is never copied"


def test_an_attachment_is_listed_never_relation_drift():
    proj = projection()
    added = {"added": [link("AttachedFile", "https://dev.azure.com/contoso/_apis/wit/attachments/x?fileName=Spec.txt",
                            "Spec.txt")]}
    got = sm.classify_drift(ledger_row(proj), remote(), proj, [update(4, None, added)])
    assert got["class"] == "IN_SYNC" and got["fields"] == []
    assert [a["name"] for a in got["attachments"]] == ["Spec.txt"]


def test_a_forbidden_field_is_named_and_its_value_never_read():
    proj = projection()
    got = sm.classify_drift(ledger_row(proj), remote(), proj,
                            [update(4, {"Microsoft.VSTS.Scheduling.StoryPoints": change(3, 13)})])
    assert got["class"] == "IN_SYNC" and got["fields"] == []
    assert got["ignored"] == ["Microsoft.VSTS.Scheduling.StoryPoints"]
    assert "13" not in json.dumps(got)


EDGES = [
    ("never pushed", None, None, projection(), [], "NEVER_PUSHED"),
    ("on the board, not in the ledger or the repo", None, remote(), None, [], "UNMAPPED_IN_ADO"),
    ("deleted in ADO", "ledgered", None, projection(), [], "DELETED_IN_ADO"),
    ("source file gone", "ledgered", remote(), None, [], "ORPHAN_IN_REPO"),
    ("nothing moved", "ledgered", remote(rev=3), projection(), [], "IN_SYNC"),
    ("bookkeeping only", "ledgered", remote(), projection(), [update(4, {"System.BoardColumn": change("New", "Doing")})],
     "IN_SYNC"),
    ("an already-seen revision is skipped", "ledgered", remote(), projection(),
     [update(3, {"System.State": change("New", "Ready")})], "IN_SYNC"),
    ("moved to another project", "ledgered", remote(), projection(),
     [update(4, {"System.TeamProject": change("Claims", "Archive")})], "MOVED"),
    ("AssignedTo on a merged spec", "ledgered", remote(), projection(status="merged"),
     [update(4, {"System.AssignedTo": change(PERSON_2, PERSON_3)})], "SDLC_OWNED_DRIFT"),
    ("a human tag", "ledgered", remote(), projection(),
     [update(4, {"System.Tags": change("sdlc:spec:0004; sdlc:status:ready", "customer; sdlc:spec:0004; "
                                                                           "sdlc:status:ready")})], "ADO_OWNED_CHANGE"),
    ("epic Description outside the markers", "ledgered", remote(), projection("epic"),
     [update(4, {"System.Description": change(DESCRIPTION, DESCRIPTION.replace("team notes", "more notes"))})],
     "ADO_OWNED_CHANGE"),
    ("spec Description inside the markers", "ledgered", remote(), projection(),
     [update(4, {"System.Description": change(DESCRIPTION, DESCRIPTION.replace("spec 0004", "spec 4"))})],
     "SDLC_OWNED_DRIFT"),
    ("AcceptanceCriteria on a requirement", "ledgered", remote(), projection("requirement"),
     [update(4, {"Microsoft.VSTS.Common.AcceptanceCriteria": change("<p>a</p>", "<p>b</p>")})], "ADO_OWNED_CHANGE"),
    ("a History beside a State change is the State change", "ledgered", remote(), projection(),
     [update(4, {"System.State": change("Ready", "Active"), "System.History": change(None, "<p>go</p>")})],
     "SDLC_OWNED_DRIFT"),
]


@pytest.mark.parametrize("label, ledgered, rem, proj, updates, expected", EDGES, ids=[e[0] for e in EDGES])
def test_drift_edges(label, ledgered, rem, proj, updates, expected):
    row = ledger_row(proj or projection()) if ledgered else None
    assert sm.classify_drift(row, rem, proj, updates)["class"] == expected


def test_both_sides_moved_on_an_s_field_is_a_conflict():
    pushed = projection()
    now = projection(status="in-flight", fields={**pushed["fields"], "System.State": "Active"})
    got = sm.classify_drift(ledger_row(pushed), remote(), now, [update(4, {"System.State": change("Ready", "Closed")})])
    assert got["class"] == "CONFLICT"
    # the repo moving does not escalate a board-owned change
    got = sm.classify_drift(ledger_row(pushed), remote(), now,
                            [update(4, {"System.IterationPath": change("Claims\\Sprint 7", "Claims\\Sprint 8")})])
    assert got["class"] == "ADO_OWNED_CHANGE"


def test_a_rev_that_moved_with_no_updates_read_is_never_called_in_sync():
    proj = projection()
    with pytest.raises(ValueError, match="updates"):
        sm.classify_drift(ledger_row(proj, rev_after=3), remote(rev=5), proj, [])


def test_nothing_to_classify_is_an_error():
    with pytest.raises(ValueError):
        sm.classify_drift(None, None, None, [])


def test_field_entries_carry_safe_values_only():
    proj = projection()
    got = sm.classify_drift(ledger_row(proj), remote(), proj, [update(4, {
        "System.IterationPath": change("Claims\\Sprint 7", "Claims\\Sprint 8"),
        "System.AssignedTo": change(PERSON_2, PERSON_3),
        "System.History": change(None, "<p>secret plan</p>"),
        "System.Description": change(DESCRIPTION, DESCRIPTION.replace("notes", "n")),
    })])
    by = {f["field"]: f for f in got["fields"]}
    assert by["System.IterationPath"]["new"] == "Claims\\Sprint 8" and by["System.IterationPath"]["rev"] == 4
    for field in ("System.AssignedTo", "System.History", "System.Description"):
        assert "old" not in by[field] and "new" not in by[field], field
    assert "secret" not in json.dumps(got)


def test_the_hand_written_updates_classify_as_the_matrix_says():
    proj = projection()
    updates = abf.load_wit("updates")["value"]
    got = sm.classify_drift(ledger_row(proj, rev_after=1), remote(rev=updates[-1]["rev"]), proj, updates)
    by = {f["field"]: f["class"] for f in got["fields"]}
    assert by["System.State"] == "SDLC_OWNED_DRIFT"
    assert by["System.IterationPath"] == "ADO_OWNED_CHANGE"
    assert by["System.AssignedTo"] == "ADO_OWNED_CHANGE"
    assert by["relations:ArtifactLink"] == "RELATION_DRIFT"
    assert by["System.History"] == "COMMENT"
    assert [a["name"] for a in got["attachments"]] == ["Spec.txt"]
    assert got["class"] == "SDLC_OWNED_DRIFT"
    assert not bc.EMAIL_RE.search(json.dumps(got["fields"]))


def test_the_hand_written_comment_revision_is_a_comment_not_drift():
    proj = projection()
    updates = abf.load_wit("updates_after_comment")["value"]
    got = sm.classify_drift(ledger_row(proj, rev_after=updates[0]["rev"]), remote(rev=updates[-1]["rev"]), proj,
                            updates)
    assert got["class"] == "COMMENT"
    assert [f["field"] for f in got["fields"]] == ["System.History"]


# --- diff: what a push would change ---------------------------------------------------------------------------

def test_diff_against_nothing_adds_every_projected_field():
    ops = sm.diff(projection(), None)
    assert {o["path"] for o in ops} == {"/fields/System.Title", "/fields/System.State", "/fields/System.Description",
                                        "/fields/System.Tags"}
    assert {o["op"] for o in ops} == {"add"} and {o["class"] for o in ops} == {"NEVER_PUSHED"}
    assert all(set(o) == {"op", "path", "old", "new", "class"} for o in ops)


def test_diff_of_an_equal_remote_is_empty():
    proj = projection()
    rem = remote(fields={"System.Description": DESCRIPTION}, tags={"sdlc:spec:0004", "sdlc:status:ready", "customer"})
    assert sm.diff(proj, rem) == []


def test_diff_replaces_s_fields_and_leaves_board_owned_ones():
    proj = projection(fields={"System.Title": "0004 · duplicate claim 409", "System.State": "Active",
                              "System.AssignedTo": "person1@example.com", "System.IterationPath": "Claims\\Sprint 8"})
    ops = sm.diff(proj, remote(tags={"sdlc:spec:0004", "sdlc:status:in-flight"}))
    assert [(o["op"], o["path"], o["old"], o["new"]) for o in ops] == [
        ("replace", "/fields/System.State", "Ready", "Active"),
        ("replace", "/fields/System.Tags", "sdlc:spec:0004; sdlc:status:in-flight", "sdlc:spec:0004; sdlc:status:ready"),
    ]
    assert {o["class"] for o in ops} == {"SDLC_OWNED_DRIFT"}


def test_diff_honours_a_kind_ownership_map():
    proj = projection("decision", fields={"System.Title": "DL-04 · new words"})
    rem = remote(title="DL-04 · old words", tags=set(proj["tags"]))
    assert sm.diff(proj, rem, sm.ownership_for("decision")) == []  # a decision's wording is the board's
    assert [o["path"] for o in sm.diff(proj, rem)] == ["/fields/System.Title"]


@pytest.mark.parametrize("key", ["description_rows", "fr_ids", "priority", "domain", "System", "System.", ".Title",
                                 "System Title", "1System.Title"])
def test_a_field_key_that_is_not_a_reference_name_is_never_an_op(key):
    """A source's neutral key (the requirements tree's `description_rows`, `fr_ids`) is its own data, never a push."""
    proj = projection("requirement", fields={"System.Title": "FR-001 · Reject duplicates", key: ["FR-001"]})
    assert [o["path"] for o in sm.diff(proj, None)] == ["/fields/System.Tags", "/fields/System.Title"]
    rem = remote(title="FR-001 · old words", tags=set(proj["tags"]))
    assert [o["path"] for o in sm.diff(proj, rem)] == ["/fields/System.Title"]


@pytest.mark.parametrize("key", ["System.Title", "Microsoft.VSTS.Common.Priority", "Custom.RiskTier", "Org_X.Field_2"])
def test_a_dotted_reference_name_is_one(key):
    assert sm.REFERENCE_NAME_RE.fullmatch(key)


def test_ownership_for_layers_the_kind_on_the_contract():
    assert sm.ownership_for("spec") == dict(bc.OWNERSHIP)
    assert sm.ownership_for("epic")["System.State"] == "A"
    assert sm.ownership_for("decision")["System.Title"] == "C"
    assert set(sm.KIND_OWNERSHIP) <= set(bc.KINDS)
    assert all(v in {"S", "A", "C"} for m in sm.KIND_OWNERSHIP.values() for v in m.values())


def test_projection_hash_ignores_set_order_and_moves_with_content():
    a = projection(tags={"b", "a", "c"})
    b = projection(tags={"c", "a", "b"})
    assert sm.projection_hash(a) == sm.projection_hash(b)
    assert bc.HASH_RE.fullmatch(sm.projection_hash(a))
    assert sm.projection_hash(projection(status="merged")) != sm.projection_hash(a)


# --- dispositions ---------------------------------------------------------------------------------------------

DISPOSITIONS = [
    ({"class": "SDLC_OWNED_DRIFT"}, False),
    ({"class": "SDLC_OWNED_DRIFT", "disposition": "OPEN"}, False),
    ({"class": "SDLC_OWNED_DRIFT", "disposition": "ACKNOWLEDGED", "owner": "@MCKRUZ"}, True),
    ({"class": "SDLC_OWNED_DRIFT", "disposition": "ACKNOWLEDGED"}, False),
    ({"class": "SDLC_OWNED_DRIFT", "disposition": "ACKNOWLEDGED", "owner": "  "}, False),
    ({"class": "SDLC_OWNED_DRIFT", "disposition": "ACKNOWLEDGED", "owner": "Claude"}, False),
    ({"class": "SDLC_OWNED_DRIFT", "disposition": "ACKNOWLEDGED", "owner": "shepherd:feature-architect"}, False),
    ({"class": "ADO_OWNED_CHANGE", "disposition": "NOT_DRIFT", "reason": "the team re-planned the sprint"}, True),
    ({"class": "ADO_OWNED_CHANGE", "disposition": "NOT_DRIFT"}, False),
    ({"class": "ADO_OWNED_CHANGE", "disposition": "TAKE_ADO", "child_exit": 0}, True),
    ({"class": "ADO_OWNED_CHANGE", "disposition": "TAKE_ADO"}, False),
    ({"class": "ADO_OWNED_CHANGE", "disposition": "TAKE_ADO", "child_exit": 1}, False),
    ({"class": "ADO_OWNED_CHANGE", "disposition": "TAKE_ADO", "child_exit": False}, False),
    ({"class": "CONFLICT", "disposition": "TAKE_SDLC", "child_exit": 0}, True),
    ({"class": "CONFLICT", "disposition": "ACKNOWLEDGED", "owner": "@MCKRUZ"}, False),
    ({"class": "CONFLICT", "disposition": "NOT_DRIFT", "reason": "x"}, False),
    ({"class": "RETYPED", "disposition": "ACKNOWLEDGED", "owner": "@MCKRUZ"}, False),
    ({"class": "RETYPED", "disposition": "TAKE_ADO", "child_exit": 0}, True),
    ({"class": "DELETED_IN_ADO", "disposition": "UNLINK"}, True),
    ({"class": "DELETED_IN_ADO", "disposition": "RECREATE"}, True),
    ({"class": "DELETED_IN_ADO", "disposition": "ACKNOWLEDGED", "owner": "@MCKRUZ"}, True),
    ({"class": "DELETED_IN_ADO", "disposition": "TAKE_ADO", "child_exit": 0}, False),
    ({"class": "ORPHAN_IN_REPO", "disposition": "RELINK", "relink_ref": "sdlc:spec:0009"}, True),
    ({"class": "ORPHAN_IN_REPO", "disposition": "RELINK"}, False),
    ({"class": "ORPHAN_IN_REPO", "disposition": "RELINK", "relink_ref": "spec 9"}, False),
    ({"class": "ORPHAN_IN_REPO", "disposition": "UNLINK"}, True),
    ({"class": "ORPHAN_IN_REPO", "disposition": "ACKNOWLEDGED", "owner": "@MCKRUZ"}, False),
    ({"class": "SDLC_OWNED_DRIFT", "disposition": "FIXED"}, False),
    ({"class": "NOT_A_CLASS", "disposition": "UNLINK"}, False),
    ({"class": "COMMENT"}, True),
    ({"class": "IN_SYNC"}, True),
    ({"class": "SDLC_OWNED_DRIFT", "disposition": "take-sdlc", "child_exit": 0}, True),
]


@pytest.mark.parametrize("row, off_books", DISPOSITIONS, ids=[f"{r['class']}-{r.get('disposition')}-{i}"
                                                              for i, (r, _) in enumerate(DISPOSITIONS)])
def test_disposition_state_machine_counts_honestly(row, off_books):
    ok, reason = sm.validate_disposition(row)
    assert ok is off_books, reason
    assert isinstance(reason, str) and reason
    assert sm.counts_as_open(row) is (not off_books)


# --- the ledger line ------------------------------------------------------------------------------------------

def test_ledger_entry_refuses_an_email():
    with pytest.raises(ValueError):
        sm.ledger_entry(TS, "observed", revised_by=KIM)


def test_ledger_entry_refuses_a_guid():
    with pytest.raises(ValueError):
        sm.ledger_entry(TS, "observed", ref="sdlc:spec:0004", notes=[f"identity {A_GUID}"])
    with pytest.raises(ValueError):
        sm.ledger_entry(TS, "observed", ref=A_GUID)
    with pytest.raises(ValueError, match="GUID"):
        sm.ledger_entry(TS, "observed", child_argv=["x%2F" + A_GUID])  # glued to a word character


def test_ledger_entry_refuses_identities_nested_anywhere():
    with pytest.raises(ValueError):
        sm.ledger_entry(TS, "drift_seen", fields=[{"old": {"uniqueName": "person2" + "@example.com"}}])
    with pytest.raises(ValueError):
        sm.ledger_entry(TS, "drift_seen", **{"by": "@MCKRUZ", "notes": ["mail person3" + "@example.com"]})


def test_ledger_entry_refuses_an_unknown_event():
    with pytest.raises(ValueError, match="unknown ledger event"):
        sm.ledger_entry(TS, "synced", ref="sdlc:spec:0004")


def test_ledger_entry_refuses_a_display_name_where_a_handle_belongs():
    with pytest.raises(ValueError):
        sm.ledger_entry(TS, "drift_seen", revised_by="Person 2")
    with pytest.raises(ValueError):
        sm.ledger_entry(TS, "applied", executed_as="Person 2")
    for ok in ("@priya-n", None):
        assert sm.ledger_entry(TS, "drift_seen", revised_by=ok)["revised_by"] == ok
    assert sm.ledger_entry(TS, "applied", executed_as="unknown")["executed_as"] == "unknown"


def test_ledger_entry_is_one_json_line_with_ts_and_event_first():
    e = sm.ledger_entry(TS, "observed", ref="sdlc:spec:0004", kind="spec", work_item=4521, rev_before=3,
                        rev_after=4, fields=["System.State"], plan="3f9a1c2b7d04", projection_hash="0123456789ab",
                        notes=[], tags={"b", "a"})
    assert list(e)[:2] == ["ts", "event"] and e["event"] == "observed"
    assert e["tags"] == ["a", "b"]  # a set is written sorted
    line = json.dumps(e)
    assert "\n" not in line and json.loads(line) == e
    assert set(bc.LEDGER_EVENTS) == set(sm.LEDGER_EVENTS)


def test_ledger_entry_refuses_what_json_cannot_write():
    with pytest.raises(ValueError):
        sm.ledger_entry(TS, "observed", when=date(2026, 10, 12))


def test_ledger_id_is_the_design_form():
    assert sm.ledger_id(4521, 7) == "ado-sync:4521:7"


# --- the plan hash --------------------------------------------------------------------------------------------

ROWS = [{"ref": "sdlc:spec:0004", "op": "update", "ops": [{"op": "replace", "path": "/fields/System.State",
                                                          "old": "Ready", "new": "Active"}]},
        {"ref": "sdlc:feature:03", "op": "create", "ops": []}]


def test_plan_hash_is_the_pinned_formula_and_stable_across_key_order():
    expected = hashlib.sha256(json.dumps(ROWS, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]
    assert sm.plan_hash(ROWS) == expected
    reordered = [dict(reversed(list(r.items()))) for r in ROWS]
    assert sm.plan_hash(reordered) == expected
    assert bc.HASH_RE.fullmatch(expected)


def test_plan_hash_moves_with_content_and_order_of_rows():
    assert sm.plan_hash(ROWS) != sm.plan_hash(list(reversed(ROWS)))
    assert sm.plan_hash(ROWS[:1]) != sm.plan_hash(ROWS)
    assert sm.plan_hash([{"tags": {"b", "a"}}]) == sm.plan_hash([{"tags": ["a", "b"]}])


# --- the hook line --------------------------------------------------------------------------------------------

def test_hook_line_never_pulled():
    assert sm.hook_line(None, None, None) == "no data (never pulled)"


def test_hook_line_golden():
    assert sm.hook_line(3, 1, "2026-10-12T09:02Z") == "3 rows pending · 1 drifted · as of 2026-10-12T09:02Z"


@pytest.mark.parametrize("pending, drifted, as_of, line", [
    (1, 0, "2026-10-12T09:02Z", "1 row pending · 0 drifted · as of 2026-10-12T09:02Z"),
    (0, 0, "2026-10-12T09:02Z", "0 rows pending · 0 drifted · as of 2026-10-12T09:02Z"),
    (None, 2, "2026-10-12T09:02Z", "no plan yet · 2 drifted · as of 2026-10-12T09:02Z"),
    (4, None, None, "no data (never pulled)"),
])
def test_hook_line_other_forms(pending, drifted, as_of, line):
    assert sm.hook_line(pending, drifted, as_of) == line


@pytest.mark.parametrize("args", [(-1, 0, "t"), (True, 0, "t"), (1, "2", "t"), (1, 1, "a\nb"), (1, 1, 5)])
def test_hook_line_refuses_what_is_not_a_count_or_one_line(args):
    with pytest.raises(ValueError):
        sm.hook_line(*args)


# --- the never-pulled status ----------------------------------------------------------------------------------

def _scalars(doc):
    if isinstance(doc, dict):
        for v in doc.values():
            yield from _scalars(v)
    elif isinstance(doc, list):
        for v in doc:
            yield from _scalars(v)
    else:
        yield doc


def test_status_nodata_has_no_integer_zero_and_every_count_is_none():
    assert not [v for v in _scalars(sm.STATUS_NODATA) if isinstance(v, (int, float)) and v == 0]
    assert False not in [v for v in _scalars(sm.STATUS_NODATA) if isinstance(v, bool)]
    assert sm.STATUS_NODATA["counts"] and all(v is None for v in sm.STATUS_NODATA["counts"].values())
    assert sm.STATUS_NODATA["as_of"] is None
    assert sm.STATUS_NODATA["hook_line"] == sm.hook_line(None, None, None)


def test_status_nodata_equals_the_golden_file():
    text = GOLDEN.read_text(encoding="utf-8")
    assert json.loads(text) == sm.STATUS_NODATA
    assert ": 0" not in text and ":0" not in text


def test_summarize_of_an_empty_ledger_is_the_nodata_document_and_a_copy():
    doc = sm.summarize([], date(2026, 10, 13))
    assert doc == sm.STATUS_NODATA
    doc["counts"]["pending"] = 5
    assert sm.STATUS_NODATA["counts"]["pending"] is None


def L(event, ts="2026-10-05T09:00:00Z", **fields):
    return sm.ledger_entry(ts, event, **fields)


def test_summarize_counts_after_reads_and_ages_debt_in_business_days():
    ledger = [
        L("applied", ref="sdlc:spec:0004", work_item=4521, rev_after=3, plan="aaaaaaaaaaaa"),
        L("linked", ref="sdlc:spec:0005", work_item=4523, rev_after=1),
        L("planned", ts="2026-10-06T09:00:00Z", plan="3f9a1c2b7d04", ref="sdlc:spec:0004"),
        L("planned", ts="2026-10-06T09:00:00Z", plan="3f9a1c2b7d04", ref="sdlc:feature:03"),
        L("observed", ts="2026-10-08T09:00:00Z", ref="sdlc:spec:0004", work_item=4521, rev_after=5,
          **{"class": "SDLC_OWNED_DRIFT"}),
        L("drift_seen", ts="2026-10-08T09:00:00Z", ref="sdlc:spec:0004", field="System.State",
          **{"class": "SDLC_OWNED_DRIFT"}),
        L("drift_seen", ts="2026-10-08T09:00:00Z", ref="sdlc:spec:0004", field="System.IterationPath",
          **{"class": "ADO_OWNED_CHANGE"}),
        L("drift_seen", ts="2026-10-12T09:00:00Z", ref="sdlc:spec:0005", field="System.WorkItemType",
          **{"class": "RETYPED"}),
        L("drift_seen", ts="2026-10-08T09:00:00Z", ref="sdlc:spec:0005", field="System.Title",
          **{"class": "SDLC_OWNED_DRIFT"}),
        L("reconciled", ts="2026-10-09T09:00:00Z", ref="sdlc:spec:0005", field="System.Title",
          disposition="ACKNOWLEDGED", owner="@MCKRUZ", by="@MCKRUZ"),
        L("observed", ts="2026-10-12T09:02:00Z", ref=None),
    ]
    doc = sm.summarize(ledger, date(2026, 10, 13))
    assert doc["as_of"] == "2026-10-12T09:02:00Z"
    assert doc["counts"] == {"linked": 2, "pending": 2, "drifted": 2, "open": 3, "conflicts": 1, "debt": 1}
    assert doc["by_class"] == {"ADO_OWNED_CHANGE": 1, "RETYPED": 1, "SDLC_OWNED_DRIFT": 1}
    # 2026-10-08 (Thu) + 2 business days = 2026-10-12 (Mon); the 13th is past it. The RETYPED row is a day old.
    assert doc["debt"] == [{"ref": "sdlc:spec:0004", "field": "System.State", "class": "SDLC_OWNED_DRIFT",
                            "seen": "2026-10-08", "due": "2026-10-12"}]
    assert doc["last_plan"] == {"plan": "3f9a1c2b7d04", "ts": "2026-10-06T09:00:00Z", "rows": 2}
    assert doc["hook_line"] == "2 rows pending · 2 drifted · as of 2026-10-12T09:02:00Z"


def test_summarize_never_pulled_keeps_drift_as_no_data_but_counts_what_was_read():
    ledger = [L("linked", ref="sdlc:spec:0004", work_item=4521, rev_after=3),
              L("planned", plan="3f9a1c2b7d04", ref=None)]
    doc = sm.summarize(ledger, date(2026, 10, 13))
    assert doc["counts"]["linked"] == 1 and doc["counts"]["pending"] == 0  # a plan ran and found nothing to do
    assert {k: doc["counts"][k] for k in ("drifted", "open", "conflicts", "debt")} == dict.fromkeys(
        ("drifted", "open", "conflicts", "debt"))
    assert doc["as_of"] is None and doc["by_class"] is None and doc["debt"] is None
    assert doc["hook_line"] == "no data (never pulled)"


def test_summarize_clears_a_drift_row_that_was_applied_or_reconciled():
    ledger = [
        L("drift_seen", ref="sdlc:spec:0004", field="System.State", **{"class": "SDLC_OWNED_DRIFT"}),
        L("drift_seen", ref="sdlc:spec:0004", field="System.AssignedTo", **{"class": "ADO_OWNED_CHANGE"}),
        L("observed", ts="2026-10-06T09:00:00Z", ref="sdlc:spec:0004"),
        L("applied", ts="2026-10-07T09:00:00Z", ref="sdlc:spec:0004", work_item=4521, fields=["System.State"],
          plan="3f9a1c2b7d04"),
        L("reconciled", ts="2026-10-07T09:00:00Z", ref="sdlc:spec:0004", field="System.AssignedTo",
          disposition="TAKE_ADO", child_exit=0, by="@MCKRUZ"),
    ]
    doc = sm.summarize(ledger, date(2026, 10, 30))
    assert doc["counts"]["open"] == 0 and doc["counts"]["drifted"] == 0 and doc["debt"] == []


def test_summarize_ignores_a_line_that_is_not_an_event():
    assert sm.summarize([{"nope": 1}, "x"], date(2026, 10, 13)) == sm.STATUS_NODATA


# --- --by: a named human, never an AI or an agent -------------------------------------------------------------

AI_BY = [
    ("shepherd:feature-architect", True),
    ("Kim Lee", False),
    ("Claude", True),
    ("@MCKRUZ", False),
    ("feature-architect", True),
    ("Shepherd:Data-Analyst", True),
    ("sdlc-orchestrator", True),
    ("shepherd:section-evaluator", True),
    ("Copilot", True),
    ("release bot", True),
    ("Priya N", False),
    ("", False),
]


@pytest.mark.parametrize("name, refused", AI_BY)
def test_ai_by(name, refused):
    assert sm.ai_by(name, STEMS) is refused


def test_ai_by_strips_only_the_shepherd_prefix():
    assert sm.ai_by("shepherd:Kim Lee", STEMS) is False
    assert sm.ai_by("other:feature-architect", frozenset()) is False  # no other prefix is stripped


def test_ai_by_agrees_with_the_cli_require_human():
    for name, refused in AI_BY:
        if not name.strip():
            continue
        try:
            ado_sync.require_human(name, "--by")
            cli_refused = False
        except ado_sync.Refused:
            cli_refused = True
        assert cli_refused is refused, name


# === Fold B4 (B4-P0): the reconcile disposition enums. Appended; nothing above this line changed. ============
#
# The design §8 state machine, keyed by the state a drift row starts in, as `reconcile` (B4-P1a) records it:
# OPEN -> TAKE_ADO | TAKE_SDLC | ACKNOWLEDGED(owner) | NOT_DRIFT(reason); CONFLICT -> TAKE_ADO | TAKE_SDLC;
# DELETED_IN_ADO -> RECREATE | UNLINK | ACKNOWLEDGED; ORPHAN_IN_REPO -> UNLINK | RELINK. The tests hold the named
# table equal to what `validate_disposition` / `counts_as_open` decide with, for every class and every word.

MACHINE = {
    "OPEN": ("TAKE_ADO", "TAKE_SDLC", "ACKNOWLEDGED", "NOT_DRIFT"),
    "CONFLICT": ("TAKE_ADO", "TAKE_SDLC"),
    "DELETED_IN_ADO": ("RECREATE", "UNLINK", "ACKNOWLEDGED"),
    "ORPHAN_IN_REPO": ("UNLINK", "RELINK"),
}
# What each disposition carries when it is genuinely off the books (the honest-counting fields).
FULL = {"TAKE_ADO": {"child_exit": 0}, "TAKE_SDLC": {"child_exit": 0}, "ACKNOWLEDGED": {"owner": "@MCKRUZ"},
        "NOT_DRIFT": {"reason": "the team re-planned the sprint"}, "RECREATE": {}, "UNLINK": {},
        "RELINK": {"relink_ref": "sdlc:spec:0009"}}
STATE_OF = [
    ("SDLC_OWNED_DRIFT", "OPEN"), ("ADO_OWNED_CHANGE", "OPEN"), ("MOVED", "OPEN"), ("RELATION_DRIFT", "OPEN"),
    ("UNMAPPED_IN_ADO", "OPEN"), ("CONFLICT", "CONFLICT"), ("RETYPED", "CONFLICT"),
    ("DELETED_IN_ADO", "DELETED_IN_ADO"), ("ORPHAN_IN_REPO", "ORPHAN_IN_REPO"),
    ("IN_SYNC", None), ("COMMENT", None), ("NEVER_PUSHED", None), ("NOT_A_CLASS", None), (None, None),
]


def test_the_disposition_machine_is_the_design_s_four_rows():
    assert sm.DISPOSITION_MACHINE == MACHINE
    assert list(sm.DISPOSITION_MACHINE) == ["OPEN", "CONFLICT", "DELETED_IN_ADO", "ORPHAN_IN_REPO"]
    assert sm.CONFLICT_CLASSES == ("CONFLICT", "RETYPED")


def test_state_of_covers_every_drift_class():
    assert {c for c, _ in STATE_OF if c in bc.DRIFT_CLASSES} == set(bc.DRIFT_CLASSES)


@pytest.mark.parametrize("cls, state", STATE_OF, ids=[str(c) for c, _ in STATE_OF])
def test_a_drift_row_starts_in_its_machine_state(cls, state):
    assert sm.machine_state(cls) == state
    assert sm.dispositions_for(cls) == (MACHINE[state] if state else ())


def test_the_machine_is_the_table_validate_disposition_decides_with():
    for cls in bc.DRIFT_CLASSES:
        if cls in sm.NOT_DRIFT_CLASSES:
            assert sm.dispositions_for(cls) == (), cls
        else:
            assert sm.dispositions_for(cls) == sm.DISPOSITIONS_BY_CLASS.get(cls, sm.DEFAULT_DISPOSITIONS), cls


def test_every_disposition_but_open_names_what_it_needs_and_the_machine_uses_them_all():
    assert set(sm.DISPOSITION_NEEDS) == set(sm.DISPOSITIONS) - {"OPEN"}
    assert {d for row in sm.DISPOSITION_MACHINE.values() for d in row} == set(sm.DISPOSITION_NEEDS)
    assert sm.DISPOSITION_NEEDS == {"TAKE_ADO": "child_exit", "TAKE_SDLC": "child_exit", "ACKNOWLEDGED": "owner",
                                    "NOT_DRIFT": "reason", "RECREATE": None, "UNLINK": None, "RELINK": "relink_ref"}


EVERY_PAIR = [(cls, disp) for cls in bc.DRIFT_CLASSES for disp in sm.DISPOSITIONS if disp != "OPEN"]


@pytest.mark.parametrize("cls, disp", EVERY_PAIR, ids=[f"{c}-{d}" for c, d in EVERY_PAIR])
def test_validate_disposition_honours_the_machine_for_every_class_and_word(cls, disp):
    row = {"class": cls, "disposition": disp, **FULL[disp]}
    allowed = cls in sm.NOT_DRIFT_CLASSES or disp in sm.dispositions_for(cls)
    ok, reason = sm.validate_disposition(row)
    assert ok is allowed, reason
    assert sm.counts_as_open(row) is (not allowed)


NEEDY = [(state, disp) for state, row in MACHINE.items() for disp in row if FULL[disp]]


@pytest.mark.parametrize("state, disp", NEEDY, ids=[f"{s}-{d}" for s, d in NEEDY])
def test_a_disposition_without_what_it_needs_still_counts_as_open(state, disp):
    cls = "SDLC_OWNED_DRIFT" if state == "OPEN" else state
    assert sm.counts_as_open({"class": cls, "disposition": disp}) is True
    assert sm.counts_as_open({"class": cls, "disposition": disp, **FULL[disp]}) is False
    blank = {k: (1 if k == "child_exit" else "  ") for k in FULL[disp]}
    assert sm.counts_as_open({"class": cls, "disposition": disp, **blank}) is True


def test_the_take_words_are_the_verb_table_s_and_name_four_dispositions():
    assert sm.RECONCILE_TAKES == ("ado", "sdlc", "ack", "not-drift")
    assert tuple(sm.TAKE_DISPOSITION) == sm.RECONCILE_TAKES
    assert sm.TAKE_DISPOSITION == {"ado": "TAKE_ADO", "sdlc": "TAKE_SDLC", "ack": "ACKNOWLEDGED", "not-drift": "NOT_DRIFT"}
    assert set(sm.TAKE_DISPOSITION.values()) == set(MACHINE["OPEN"])


TAKES = [
    ("SDLC_OWNED_DRIFT", "ado", "TAKE_ADO"), ("SDLC_OWNED_DRIFT", "sdlc", "TAKE_SDLC"),
    ("ADO_OWNED_CHANGE", "ack", "ACKNOWLEDGED"), ("ADO_OWNED_CHANGE", "not-drift", "NOT_DRIFT"),
    ("CONFLICT", "ado", "TAKE_ADO"), ("CONFLICT", "sdlc", "TAKE_SDLC"), ("CONFLICT", "ack", None),
    ("CONFLICT", "not-drift", None), ("RETYPED", "not-drift", None), ("RETYPED", "sdlc", "TAKE_SDLC"),
    ("DELETED_IN_ADO", "ack", "ACKNOWLEDGED"), ("DELETED_IN_ADO", "ado", None), ("DELETED_IN_ADO", "not-drift", None),
    ("ORPHAN_IN_REPO", "ado", None), ("ORPHAN_IN_REPO", "ack", None),
    ("IN_SYNC", "ado", None), ("COMMENT", "ack", None), ("NOT_A_CLASS", "ado", None),
    ("SDLC_OWNED_DRIFT", "mine", None), ("SDLC_OWNED_DRIFT", "ADO", None), ("SDLC_OWNED_DRIFT", None, None),
]


@pytest.mark.parametrize("cls, take, disp", TAKES, ids=[f"{c}-{t}" for c, t, _ in TAKES])
def test_disposition_for_take(cls, take, disp):
    assert sm.disposition_for_take(cls, take) == disp


def test_a_take_the_machine_allows_is_off_the_books_once_it_carries_its_field():
    for cls in bc.DRIFT_CLASSES:
        for take in sm.RECONCILE_TAKES:
            disp = sm.disposition_for_take(cls, take)
            if disp is None:
                continue
            assert disp in sm.dispositions_for(cls), (cls, take)
            assert sm.counts_as_open({"class": cls, "disposition": disp, **FULL[disp]}) is False, (cls, take)
