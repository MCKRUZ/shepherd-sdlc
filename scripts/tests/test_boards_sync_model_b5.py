"""The breadth Fold's pure contracts in the sync model (B5-P0): the five opt-in kinds and who owns their fields.

Fold B5 (spec 0038) projects five more kinds onto the board, each opt-in: the lifecycle singleton, NFRs, business
rules (`BR-NN`), discovery questions (`Q-NN`) and measurements. `scripts/ado_sync_model.py` grows append-only for
them: `nfr` gets its row in `KIND_OWNERSHIP` (the board owns its State; its Description and AcceptanceCriteria are
written once at create and come back only as `.proposed` text, design D32), and `BREADTH_KINDS` names the five so
the sources (B5-P1) and the tests read one list. The rows the earlier Folds wrote do not move: the pins below hold
them to their literal values. `nfr` is now the last member of `boards_contract.KINDS`, and it is a leaf under its
Domain, never a parent, so `TREE_ORDER` is unchanged. Nothing here reads a file except the starter config and its
shape (to prove the five stay opt-in); nothing writes one.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401

import ast
import json
from pathlib import Path

import pytest
import yaml

import ado_sync
import ado_sync_model as sm
import ado_sync_sources as sources
import boards_contract as bc

MODULE = Path(sm.__file__)
PLUGIN_ROOT = MODULE.parent.parent
TEMPLATE = PLUGIN_ROOT / "templates" / "ado" / "ado.yaml"
SHAPE = PLUGIN_ROOT / "templates" / "ado" / "_schema.yaml"
ALLOWED_IMPORTS = {"re", "hashlib", "json", "datetime", "typing", "boards_contract", "findings_model",
                   "artifact_model", "track_decisions"}
TS = "2026-10-12T09:02:00Z"

TITLE, DESCRIPTION, STATE = "System.Title", "System.Description", "System.State"
ACCEPTANCE, TAGS = "Microsoft.VSTS.Common.AcceptanceCriteria", "System.Tags"
BLOCK = "<div>team notes</div><!-- sdlc:begin --><p>NFR-P01: p95 under 800 ms</p><!-- sdlc:end -->"

# The fourteen kinds B1-P0 wrote, in their order; B5-P0 only appends `nfr` after them.
B1_KINDS = ("outcome", "domain", "epic", "feature", "spec", "spike", "sprint", "decision", "finding", "lifecycle",
            "requirement", "rule", "question", "measurement")
# KIND_OWNERSHIP as Folds B2-B4 left it: every row literal, so a B5 edit to an earlier row fails here.
EARLIER_ROWS = {
    "decision": {"System.State": "A", "System.Title": "C", "System.Description": "C"},
    "finding": {"System.State": "A"},
    "outcome": {"System.State": "A"},
    "domain": {"System.State": "A"},
    "requirement": {"System.State": "A", "Microsoft.VSTS.Common.Priority": "S",
                    "Microsoft.VSTS.Common.AcceptanceCriteria": "C"},
    "epic": {"System.State": "A"},
    "feature": {"System.State": "A"},
    "rule": {"System.State": "A", "System.Description": "C"},
    "question": {"System.State": "A"},
    "measurement": {"System.State": "A"},
}


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


def test_the_grown_model_still_imports_only_the_allowlist():
    imported = _imports()
    assert imported <= ALLOWED_IMPORTS, imported - ALLOWED_IMPORTS
    assert not {n for n in imported if n.startswith("ado_")}


def test_the_grown_model_still_calls_no_io():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"open", "print", "input", "exec", "eval", "__import__"}, called
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"read_text", "write_text", "mkdir", "unlink", "now", "today", "utcnow", "sleep"}, attrs


# --- the kinds ----------------------------------------------------------------------------------------------

def test_nfr_is_appended_as_the_last_kind_and_is_a_leaf():
    assert bc.KINDS[:14] == B1_KINDS, "the fourteen earlier kinds keep their order"
    assert bc.KINDS[-1] == "nfr" and len(bc.KINDS) == 15 and len(set(bc.KINDS)) == 15
    assert bc.TREE_ORDER == ("outcome", "domain", "requirement", "epic", "feature", "spec")
    assert "nfr" not in bc.TREE_ORDER, "an nfr hangs under its Domain; nothing is created beneath it"


def test_the_breadth_kinds_are_the_five_opt_in_kinds_of_fold_b5():
    assert sm.BREADTH_KINDS == ("lifecycle", "nfr", "rule", "question", "measurement")
    assert set(sm.BREADTH_KINDS) <= set(bc.KINDS)
    assert not set(sm.BREADTH_KINDS) & set(bc.TREE_ORDER)


def test_the_breadth_kinds_stay_opt_in():
    starter = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    assert not set(sm.BREADTH_KINDS) & set(starter["kinds"]), "the starter config turns none of them on"
    assert not set(sm.BREADTH_KINDS) & set(ado_sync.DEFAULT_KINDS), "a config without `kinds:` turns none on"
    shape = yaml.safe_load(SHAPE.read_text(encoding="utf-8"))
    assert set(sm.BREADTH_KINDS) <= set(shape["$defs"]["kind_name"]["enum"]), "a person may still turn each on"


def test_plan_and_drift_accept_kind_nfr_because_the_choices_are_the_contract_kinds():
    parser = ado_sync.build_parser()
    verbs = next(a for a in parser._actions if getattr(a, "choices", None)).choices
    for verb in ("plan", "drift"):
        kind = next(a for a in verbs[verb]._actions if "--kind" in a.option_strings)
        assert "nfr" in kind.choices and tuple(kind.choices)[-1] == "nfr", verb


def test_the_sources_layer_knows_nfr_as_a_kind(tmp_path):
    """Before B5-P1 registers its loader `nfr` has no source; it is never an unknown kind."""
    try:
        sources.projections(tmp_path, {}, {}, ["nfr"])
    except ValueError as err:
        assert "unknown kind" not in str(err), err


# --- ownership ----------------------------------------------------------------------------------------------

def test_nfr_ownership_row():
    assert sm.KIND_OWNERSHIP["nfr"] == {"System.State": "A", "System.Description": "C",
                                        "Microsoft.VSTS.Common.AcceptanceCriteria": "C"}


def test_the_earlier_ownership_rows_did_not_move():
    assert {k: v for k, v in sm.KIND_OWNERSHIP.items() if k != "nfr"} == EARLIER_ROWS
    assert set(sm.KIND_OWNERSHIP) == set(EARLIER_ROWS) | {"nfr"}
    assert set(sm.KIND_OWNERSHIP) <= set(bc.KINDS)


def test_lifecycle_uses_the_contract_ownership_as_it_is():
    """Design §6.1: the lifecycle singleton is S all — the repository's state.yaml is its whole truth."""
    assert "lifecycle" not in sm.KIND_OWNERSHIP
    assert sm.ownership_for("lifecycle") == dict(bc.OWNERSHIP)


# kind -> the letter for Title, Description, State, AcceptanceCriteria, Tags (design §6.1's Ownership column)
OWNERS = {
    "lifecycle": ("S", "S", "S", "S", "S"),
    "nfr": ("S", "C", "A", "C", "S"),
    "rule": ("S", "C", "A", "S", "S"),
    "question": ("S", "S", "A", "S", "S"),
    "measurement": ("S", "S", "A", "S", "S"),
}


def test_the_owner_table_covers_exactly_the_breadth_kinds():
    assert tuple(OWNERS) == sm.BREADTH_KINDS


@pytest.mark.parametrize("kind", sorted(OWNERS))
def test_each_breadth_kind_s_owner_letters(kind):
    own = sm.ownership_for(kind)
    got = tuple(own[ref] for ref in (TITLE, DESCRIPTION, STATE, ACCEPTANCE, TAGS))
    assert got == OWNERS[kind]
    # what no kind refines: the board's assignment and iteration, the create-time area path
    assert (own["System.AssignedTo"], own["System.IterationPath"], own["System.AreaPath"]) == ("A", "A", "C")
    assert set(own.values()) <= {"S", "A", "C"}


# --- what the ownership does: diff and classify_drift on the breadth kinds --------------------------------------

def projection(kind: str, **over) -> dict:
    p = {"ref": f"sdlc:{kind}:p01", "kind": kind, "id": "P01", "title": "p95 latency", "status": "open",
         "fields": {TITLE: "NFR-P01 · p95 latency", STATE: "New", DESCRIPTION: BLOCK,
                    ACCEPTANCE: "<p>p95 under 800 ms at 50 rps</p>"},
         "tags": {f"sdlc:{kind}:p01"}, "parent_ref": "sdlc:domain:claims-intake", "parent_note": None,
         "related_refs": [], "source_path": ".sdlc/artifacts/01-requirements/non-functional-requirements.md",
         "source_sha": "abc1234"}
    p.update(over)
    return p


def remote(kind: str, **over) -> dict:
    r = {"id": 4601, "rev": 4, "type": "User Story", "state": "New", "assigned_to_handle": None,
         "iteration": "Claims\\Sprint 7", "area": "Claims\\SDLC", "tags": {f"sdlc:{kind}:p01"},
         "title": "NFR-P01 · p95 latency", "relations": [],
         "fields": {TITLE: "NFR-P01 · p95 latency", STATE: "New", DESCRIPTION: BLOCK,
                    ACCEPTANCE: "<p>p95 under 800 ms at 50 rps</p>"}}
    r.update(over)
    return r


def ledger_row(proj: dict) -> dict:
    return {"ts": TS, "event": "applied", "ref": proj["ref"], "kind": proj["kind"], "work_item": 4601,
            "rev_after": 3, "projection_hash": sm.projection_hash(proj)}


def update(fields: dict) -> dict:
    return {"id": 4, "workItemId": 4601, "rev": 4, "revisedDate": "9999-01-01T00:00:00Z",
            "fields": {"System.Rev": {"oldValue": 3, "newValue": 4},
                       "System.ChangedDate": {"oldValue": "2026-10-11T09:00:00Z", "newValue": "2026-10-12T09:00:00Z"},
                       **fields}}


def classify(kind: str, fields: dict) -> dict:
    proj = projection(kind)
    return sm.classify_drift(ledger_row(proj), remote(kind, rev=4), proj, [update(fields)])


def test_an_nfr_push_replaces_only_its_title_and_tags_once_it_exists():
    proj = projection("nfr")
    rem = remote("nfr", tags={"sdlc:nfr:p01", "sdlc:status:old"},
                 fields={TITLE: "NFR-P01 · old words", STATE: "Active", DESCRIPTION: "<p>edited on the board</p>",
                         ACCEPTANCE: "<p>p95 under 2 s</p>"})
    ops = sm.diff(proj, rem, sm.ownership_for("nfr"))
    assert [(o["path"], o["class"]) for o in ops] == [("/fields/System.Tags", "SDLC_OWNED_DRIFT"),
                                                      ("/fields/System.Title", "SDLC_OWNED_DRIFT")]


def test_an_nfr_create_writes_its_create_time_text_once():
    ops = sm.diff(projection("nfr"), None, sm.ownership_for("nfr"))
    assert {o["path"] for o in ops} == {f"/fields/{ref}" for ref in (TITLE, STATE, DESCRIPTION, ACCEPTANCE, TAGS)}
    assert {o["class"] for o in ops} == {"NEVER_PUSHED"}


STATE_EDIT = {STATE: {"oldValue": "New", "newValue": "Active"}}
MARKED_EDIT = {DESCRIPTION: {"oldValue": BLOCK, "newValue": BLOCK.replace("800 ms", "2 s")}}
ACCEPTANCE_EDIT = {ACCEPTANCE: {"oldValue": "<p>p95 under 800 ms at 50 rps</p>", "newValue": "<p>p95 under 2 s</p>"}}
TITLE_EDIT = {TITLE: {"oldValue": "NFR-P01 · p95 latency", "newValue": "NFR-P01 · latency"}}


def _expected(letter: str) -> str:
    return "SDLC_OWNED_DRIFT" if letter == "S" else "ADO_OWNED_CHANGE"


@pytest.mark.parametrize("kind", sorted(OWNERS))
def test_a_board_state_change_on_each_breadth_kind(kind):
    assert classify(kind, STATE_EDIT)["class"] == _expected(OWNERS[kind][2])


@pytest.mark.parametrize("kind", sorted(OWNERS))
def test_a_board_edit_inside_the_markers_on_each_breadth_kind(kind):
    assert classify(kind, MARKED_EDIT)["class"] == _expected(OWNERS[kind][1])


@pytest.mark.parametrize("kind", sorted(OWNERS))
def test_a_board_acceptance_criteria_edit_on_each_breadth_kind(kind):
    assert classify(kind, ACCEPTANCE_EDIT)["class"] == _expected(OWNERS[kind][3])


@pytest.mark.parametrize("kind", sorted(OWNERS))
def test_a_board_title_edit_on_each_breadth_kind_is_drift_the_repository_owns(kind):
    assert classify(kind, TITLE_EDIT)["class"] == "SDLC_OWNED_DRIFT"


def test_an_nfr_text_edit_is_the_board_s_and_its_words_are_never_copied_out():
    got = classify("nfr", {**MARKED_EDIT, **ACCEPTANCE_EDIT})
    assert got["class"] == "ADO_OWNED_CHANGE"
    assert {f["field"]: f["owner"] for f in got["fields"]} == {DESCRIPTION: "C", ACCEPTANCE: "C"}
    blob = json.dumps(got)
    assert "800 ms" not in blob and "2 s" not in blob, "free text is classified, never copied"
