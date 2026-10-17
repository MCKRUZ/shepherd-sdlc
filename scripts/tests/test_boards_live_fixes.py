"""The fixes the live Azure Boards test (RheemDevOps, 2026-10-15..17) called for, each pinned where it was met.

Finding 1 - tag case. Azure Boards tags are case-insensitive and an organisation keeps the FIRST-SEEN casing of a tag.
Spec 0004's plan wanted `risk:HIGH`; the organisation already owned `risk:high`, so the item came back holding
`risk:high`, and every `plan` and `sync` offered the same row, `System.Tags + risk:HIGH - risk:high`, forever. The rule
(written once, as a comment, in `ado_sync_model.py` above `tag_key`):

  * a tag the board holds in ANY casing satisfies the projection's tag;
  * the plugin never issues a Tags op whose only difference is case;
  * when it must write System.Tags for another reason, the value keeps the board's own casing for every tag it keeps
    and the projection's casing only for tags that are genuinely new;
  * a case-only tag change on the board is the board's (owner C), never SDLC_OWNED_DRIFT.

Every test below fails on the code before the fix (the line after each name says what the old code did). The CLI rows
reuse the B6 mini repository and the `FakeBoardsAz` the other Boards tests answer from: nothing here spawns `az`, and
no identity, e-mail address or comment text is written into a fixture.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import HAND_WRITTEN_PROCESS
from tests.test_boards_sync_cli_b6 import (SPEC4, board_row, clock, linked, repo, run_json, seed,  # noqa: F401
                                           synced_batch)
from tests.test_boards_sync_model import change, ledger_row, projection, remote, update

import copy

import pytest

import ado_sync
import ado_sync_model as model
import ado_wit_map as wm
from tests.ado_boards_fixtures import load_wit

BOARDS_PROCESS = HAND_WRITTEN_PROCESS

TAGS = "/fields/System.Tags"


def tag_ops(ops: list[dict]) -> list[dict]:
    return [o for o in ops if o["path"] == TAGS]


def tags_of(value: str) -> set[str]:
    return {t.strip() for t in value.split(";") if t.strip()}


# --- finding 1: the model's diff -------------------------------------------------------------------------------

def test_a_tag_the_board_holds_in_another_casing_is_no_tags_op():
    # old: have != tags was a raw list comparison, so risk:high against risk:HIGH was a replace op
    proj = projection(tags={"sdlc:spec:0004", "risk:HIGH"})
    held = remote(tags={"risk:high", "sdlc:spec:0004", "a-human-tag"})
    assert tag_ops(model.diff(proj, held)) == []


def test_a_real_tag_add_keeps_the_boards_casing_for_every_tag_it_keeps():
    # old: new was "risk:HIGH; sdlc:spec:0004; sdlc:status:ready" -- the projection's casing for the tag the board holds
    proj = projection(tags={"sdlc:spec:0004", "risk:HIGH", "sdlc:status:ready"})
    held = remote(tags={"risk:high", "sdlc:spec:0004", "a-human-tag"})
    ops = tag_ops(model.diff(proj, held))
    assert len(ops) == 1
    op = ops[0]
    assert op["op"] == "replace" and op["class"] == "SDLC_OWNED_DRIFT"
    assert op["old"] == "risk:high; sdlc:spec:0004"          # the board's plugin tags, as held
    assert tags_of(op["new"]) == {"risk:high", "sdlc:spec:0004", "sdlc:status:ready"}
    assert "risk:HIGH" not in op["new"] and "a-human-tag" not in op["new"]   # a person's tag is not the diff's to carry


def test_a_genuinely_new_tag_keeps_the_projections_casing():
    # the board holds no risk: tag at all, so the organisation has no casing to keep: the projection's is the first seen
    proj = projection(tags={"sdlc:spec:0004", "risk:HIGH", "sdlc:status:ready"})
    held = remote(tags={"sdlc:spec:0004", "a-human-tag"})
    (op,) = tag_ops(model.diff(proj, held))
    assert op["op"] == "replace" and tags_of(op["new"]) == {"sdlc:spec:0004", "risk:HIGH", "sdlc:status:ready"}


def test_a_create_sends_the_projections_casing():
    (op,) = tag_ops(model.diff(projection(tags={"sdlc:spec:0004", "risk:HIGH"}), None))
    assert op["op"] == "add" and tags_of(op["new"]) == {"sdlc:spec:0004", "risk:HIGH"}


def test_a_plugin_prefix_the_board_holds_in_any_casing_is_the_repositorys_family():
    # old: "Risk:High" did not start with "risk:", so it was a person's tag, risk:HIGH was never seen as held, and
    # the plan offered "+ risk:HIGH" on every run (the organisation might as well have owned `Risk:High`)
    proj = projection(tags={"sdlc:spec:0004", "risk:HIGH"})
    assert tag_ops(model.diff(proj, remote(tags={"Risk:High", "SDLC:spec:0004"}))) == []
    assert model.is_plugin_tag("Risk:High") and model.is_plugin_tag("SDLC-REPO:claims-api")
    assert not model.is_plugin_tag("Risk") and not model.is_plugin_tag("a-human-tag")


def test_tag_key_and_board_casing_are_the_one_comparison():
    assert model.tag_key(" Risk:HIGH ") == model.tag_key("risk:high") == "risk:high"
    assert model.tag_keys("A; b ;B") == frozenset({"a", "b"})
    assert model.board_casing({"risk:HIGH", "sdlc:status:ready"}, {"risk:high"}) == ["risk:high", "sdlc:status:ready"]
    assert model.board_casing({"risk:HIGH", "risk:high"}, set()) == ["risk:HIGH"]   # one tag, one spelling


# --- finding 1: what the screen shows (`_tags_op`) and what the PATCH sends -------------------------------------

def test_tags_op_adds_and_removes_by_key_not_by_spelling():
    # old: sorted(want - have) listed risk:HIGH as an add and risk:high as a remove
    got = ado_sync._tags_op("replace", {"risk:high", "x"}, {"risk:HIGH", "x"})
    assert got["add"] == [] and got["remove"] == [] and got["kept"] == 1
    got = ado_sync._tags_op("replace", {"risk:high", "x", "sdlc:status:in-flight"},
                            {"risk:HIGH", "x", "sdlc:status:ready"})
    assert got["add"] == ["sdlc:status:ready"] and got["remove"] == ["sdlc:status:in-flight"]


def test_the_patch_sends_the_boards_casing_for_a_kept_tag_and_a_persons_tags_untouched():
    # old: merge_tags sent "risk:HIGH" (the projection's casing) and so replaced the organisation's risk:high
    proj = projection(tags={"sdlc:spec:0004", "risk:HIGH", "sdlc:status:ready"})
    held = remote(tags={"risk:high", "Human Tag", "sdlc:spec:0004"})
    patch = wm.build_update_patch(held, proj)
    (op,) = tag_ops(patch)
    sent = tags_of(op["value"])
    assert sent == {"risk:high", "Human Tag", "sdlc:status:ready", "sdlc:spec:0004"}
    assert "risk:HIGH" not in op["value"]


def test_the_patch_of_a_case_only_difference_is_the_test_op_alone():
    # old: a one-op patch (tags) for nothing but a change of case
    proj = projection(tags={"sdlc:spec:0004", "risk:HIGH"})
    patch = wm.build_update_patch(remote(tags={"risk:high", "sdlc:spec:0004", "Human Tag"}), proj)
    assert not wm.has_changes(patch)


def test_merge_tags_keeps_the_boards_casing_and_still_withdraws_what_the_repository_no_longer_wants():
    assert wm.merge_tags("Risk:High; human", {"risk:HIGH"}) == "Risk:High; human"
    assert wm.merge_tags("Risk:High; human", set()) == "human"          # the board's casing does not make it a person's
    assert wm.merge_tags("risk:high; human", {"risk:MEDIUM"}) == "human; risk:MEDIUM"   # another tag: not held, so new


# --- finding 1: drift ------------------------------------------------------------------------------------------

def classify(old: str, new: str) -> dict:
    proj = projection(tags={"sdlc:spec:0004", "risk:HIGH"})
    got = model.classify_drift(ledger_row(proj), remote(), proj, [update(4, {"System.Tags": change(old, new)})])
    (field,) = got["fields"]
    return {"class": got["class"], "owner": field["owner"], "field_class": field["class"]}


def test_a_case_only_tag_change_on_the_board_is_the_boards():
    # old: _plugin_tags(old) != _plugin_tags(new) compared spellings, so the change was owner S, SDLC_OWNED_DRIFT
    got = classify("risk:high; sdlc:spec:0004", "risk:HIGH; sdlc:spec:0004")
    assert got["owner"] == "C" and got["field_class"] == "ADO_OWNED_CHANGE" and got["class"] == "ADO_OWNED_CHANGE"


def test_a_real_plugin_tag_change_on_the_board_is_still_drift():
    got = classify("risk:high; sdlc:spec:0004", "sdlc:spec:0004")
    assert got["owner"] == "S" and got["field_class"] == "SDLC_OWNED_DRIFT"
    got = classify("risk:high; sdlc:spec:0004", "risk:low; sdlc:spec:0004")
    assert got["owner"] == "S" and got["field_class"] == "SDLC_OWNED_DRIFT"


# --- finding 1: the exact-ref matcher ---------------------------------------------------------------------------

def test_the_exact_ref_matcher_accepts_the_ref_in_any_casing():
    # old: `tag in found` was an exact string match, so an item holding SDLC:spec:0004 was not found for the ref
    items = {4521: {"tags": {"SDLC:spec:0004", "a-human-tag"}}, 4522: {"tags": {"sdlc:spec:0005"}}}
    found = ado_sync._tag_map(items, ["sdlc:spec:0004", "sdlc:spec:0005", "sdlc:spec:0006"])
    assert found == {"sdlc:spec:0004": [4521], "sdlc:spec:0005": [4522], "sdlc:spec:0006": []}


def test_the_key_of_a_ref_is_reported_once_even_when_an_item_holds_it_twice_over():
    found = ado_sync._tag_map({7: {"tags": {"sdlc:spec:0004", "SDLC:spec:0004"}}}, ["sdlc:spec:0004"])
    assert found == {"sdlc:spec:0004": [7]}


def test_another_mirror_ref_is_another_ref_in_any_casing_and_the_same_ref_is_not_another():
    # old: REF_RE.fullmatch("SDLC:spec:0005") was None, so an item carrying another spec's ref in this casing was not
    # seen as carrying one, and `link`/`adopt` would have mapped over it
    item = {"tags": {"SDLC:spec:0004", "SDLC:spec:0005", "sdlc:status:ready"}}
    assert ado_sync._other_refs(item, "sdlc:spec:0004") == ["SDLC:spec:0005"]
    assert ado_sync._other_refs({"tags": {"SDLC:spec:0004"}}, "sdlc:spec:0004") == []


# --- finding 1: through the CLI, on the mini repository and the fake board --------------------------------------

def lowercase_risk(doc: dict) -> dict:
    """`doc` with item 4521's risk tag spelled as the organisation first saw it (`risk:high`)."""
    doc = copy.deepcopy(doc)
    row = board_row(doc)
    tags = [t for t in row["fields"]["System.Tags"].split("; ")]
    row["fields"]["System.Tags"] = "; ".join("risk:high" if t.lower().startswith("risk:") else t for t in tags)
    assert "risk:high" in row["fields"]["System.Tags"]
    return doc


def test_plan_offers_no_row_for_a_risk_tag_the_board_holds_in_lower_case(repo, az, capsys):
    # old: counts.update == 1 and the row was System.Tags + risk:HIGH - risk:high, on every plan, forever
    az.answers["POST wit/workitemsbatch"] = lowercase_risk(synced_batch())
    seed(repo, linked(SPEC4, 4521, rev=8))
    code, doc = run_json(capsys, "plan", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 0
    assert doc["counts"]["update"] == 0 and doc["counts"]["in_sync"] == 1 and doc["rows"] == []


def test_plan_row_for_a_real_tag_change_never_names_the_risk_tag_the_board_already_holds(repo, az, capsys):
    # the board is behind (in-flight, MEDIUM) AND holds risk:high; the golden's row, less the risk tag's churn
    doc = lowercase_risk(load_wit("workitems_batch"))
    az.answers["POST wit/workitemsbatch"] = doc
    seed(repo, linked(SPEC4, 4521))
    code, plan = run_json(capsys, "plan", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 0 and plan["counts"]["update"] == 1
    (row,) = plan["rows"]
    (op,) = tag_ops(row["ops"])
    assert op["add"] == ["data-review:n-a", "eng-review:accepted", "sdlc:status:ready"]
    assert op["remove"] == ["sdlc:status:in-flight"]
    assert not any("risk" in t.lower() for t in op["add"] + op["remove"])


def test_sync_no_longer_reports_the_case_only_tag_as_a_change(repo, az, capsys):
    az.answers["POST wit/workitemsbatch"] = lowercase_risk(synced_batch())
    seed(repo, linked(SPEC4, 4521, rev=8))
    code, doc = run_json(capsys, "sync", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 0 and doc["counts"]["update"] == 0


# ====================================================================================================================
# Finding 2 - born Closed. A create whose State the process does not allow at creation, but allows from the type's
# initial state, is two writes: the create (born in the initial state) and one guarded PATCH that moves it.
#
# Decision DL-02 is `decided`, so its projection carried `System.State: Closed`; the create of an Issue with State Closed
# was refused by the board as a `rule` row (`value_not_allowed`, field System.State), although the discovered schema
# KNEW an Issue is created Active and moves Active -> Closed. Why the plan said nothing: `validation` was only computed
# under `plan --validate` (the key was absent otherwise), and under `--validate` the transition check sat below
# `if facts is None: continue`, so a type whose field list was not read (or did not list System.State) was never asked.
# The creation check now runs for every create row; the row says what apply will do on its State op:
#
#     {"op": "add", "path": "/fields/System.State", "old": null, "new": "Closed", "via": "Active"}
#
# (`new` is where the item ends, `via` where it is born; the text shows `(created Active, then moved)`; the plan hash
# covers it; `cost.writes` and `cost.az_spawns` count the PATCH). A State reachable in neither hop is a `validation`
# finding on a row that stays a create. A schema whose transitions were never read behaves exactly as before.
#
# These scenarios run on the apply tests' mini repository (posture assisted) and its `FakeBoardsAz(writes=True)`, over the
# hand-written process: an Issue is created Active (`"": ["Active"]`, `Active: ["Closed"]`, `Closed: ["Active"]`) and a
# User Story is created New (`New: ["Ready", ...]`), so decision DL-02 (Closed) and spec 0004 (Ready) are two-step
# creates, DL-01 (Active) and spec 0007 (New) are not. Every test says which of the old code's behaviours it fails on,
# or - where it pins what must NOT change - that it passes before and after.
# ====================================================================================================================

from tests import test_boards_sync_apply as ap
from tests.ado_boards_fixtures import is_identity_rest_read, load_wit_error, route_params

import json

import ado_schema_map as sm
import ado_sync_apply as apply_mod
import boards_contract as bc
from ado_map import AdoImportError

STATE = "/fields/System.State"
DL02, DL01 = "sdlc:decision:02", "sdlc:decision:01"
DECIDED = ("decision", "DL-02", "Issue", "Active", "Closed", DL02)    # kind, id, type, born in, ends in, ref
READY = ("spec", "0004", "User Story", "New", "Ready", "sdlc:spec:0004")
MOVES = pytest.mark.parametrize("case", [DECIDED, READY], ids=["decision-owned-by-the-board", "spec-owned-by-the-repo"])


@pytest.fixture
def apply_board(monkeypatch):
    return ap.make_board(monkeypatch)


@pytest.fixture
def apply_repo(tmp_path, apply_board, capsys):
    root = ap.build_repo(tmp_path)
    capsys.readouterr()
    apply_board.calls.clear()
    return root


def plan_of(root, capsys, kind: str, ident: str, *extra) -> dict:
    return ap.plan_doc(root, capsys, "--kind", kind, "--id", ident, "--no-comments", *extra)


def state_op(row: dict) -> dict:
    (op,) = [o for o in row["ops"] if o["path"] == STATE]
    return op


def edit_schema(root, **types) -> None:
    """Replace what the saved schema knows of some types (`Issue={"transitions": {...}}`): the board answers nothing here."""
    path = root / bc.SCHEMA_FILE
    schema = json.loads(path.read_text(encoding="utf-8"))
    for name, changes in types.items():
        schema["types"][name].update(changes)
    path.write_text(json.dumps(schema, sort_keys=True, indent=1) + "\n", encoding="utf-8")


def sent_of(board, key: str) -> list[tuple]:
    return [s for s in ap.written(board) if s[0] == key]


def state_of(body: list[dict]):
    return next((op["value"] for op in body if op["path"] == STATE), None)


def batch_row_from_create(body: list[dict], wid: int, rev: int, type_name: str, state: str) -> dict:
    """What the board holds for an item a create just made, read back as the batch answers it: the fields the create
    sent (less the identity, which is the board's), in `state` at `rev`. No relation, no person."""
    fields = {op["path"][len("/fields/"):]: op["value"] for op in body if op["path"].startswith("/fields/")
              and op["path"] not in ("/fields/System.History", "/fields/System.AssignedTo")}
    fields.update({"System.Id": wid, "System.WorkItemType": type_name, "System.State": state})
    fields.setdefault("System.IterationPath", "Claims")
    return {"id": wid, "rev": rev, "fields": fields}


def refuse_moves(board, text: str):
    """Every PATCH the board is sent is refused with `text` (the creates still succeed). Returns the handler that
    answered them before, to put back when the board is well again."""
    healthy = board.answers["PATCH wit/workItems"]
    ap.fail_with(board, "PATCH wit/workItems", text)
    return healthy


# --- finding 2: the plan says it -------------------------------------------------------------------------------------

def test_plan_marks_a_create_the_process_does_not_allow_at_creation_as_created_then_moved(apply_repo, capsys):
    # old: the State op was {"op","path","old","new"} with no `via`, the text had no such words, cost was 0 writes
    doc = plan_of(apply_repo, capsys, "decision", "DL-02")
    (row,) = doc["rows"]
    assert row["action"] == "create" and row["type"] == "Issue"
    assert state_op(row) == {"op": "add", "path": STATE, "old": None, "new": "Closed", "via": "Active"}
    assert [o for o in row["ops"] if "via" in o] == [state_op(row)]            # no other op carries the mark
    assert "validation" not in row                                              # nothing to flag: the process allows the move
    code = ado_sync.main(["plan", "--kind", "decision", "--id", "DL-02", "--no-comments", "--repo", str(apply_repo)])
    text = capsys.readouterr().out
    assert code == 0 and "System.State" in text
    (line,) = [ln for ln in text.splitlines() if ln.startswith("  System.State")]
    assert line.endswith("(none) -> Closed  (created Active, then moved)")      # one line, on the State op itself
    assert "cost: 1 write, 1 create, 0 links  (az spawns on apply: 2)" in text


def test_plan_json_counts_the_extra_patch_as_a_write_and_an_az_spawn(apply_repo, capsys):
    # old: {"writes": 0, "creates": 1, "links": 0, "az_spawns": 1}
    out = run_plan_json(apply_repo, capsys, "decision", "DL-01", "DL-02")
    assert [r["action"] for r in out["rows"]] == ["create", "create"] and out["counts"]["create"] == 2
    assert out["cost"] == {"writes": 1, "creates": 2, "links": 0, "az_spawns": 3}      # DL-01 is one write, DL-02 two


def run_plan_json(root, capsys, kind: str, *ids, extra=()) -> dict:
    argv = ["plan", "--kind", kind, *[a for i in ids for a in ("--id", i)], "--no-comments", *extra, "--repo",
            str(root), "--json"]
    assert ado_sync.main(argv) == 0
    return json.loads(capsys.readouterr().out)


def test_the_plan_hash_covers_the_mark(apply_repo, capsys):
    # old: there was no mark, so there was nothing for a hash to cover
    doc = plan_of(apply_repo, capsys, "decision", "DL-02")
    plain = json.loads(json.dumps(doc["rows"]))
    del state_op(plain[0])["via"]
    assert model.plan_hash(plain) != model.plan_hash(doc["rows"]) == doc["plan"]


def test_a_state_the_process_allows_at_creation_is_planned_exactly_as_before(apply_repo, capsys):
    # passes before and after: DL-01 is open (Active, an Issue's first state), spec 0007 a draft (New, a User Story's)
    out = run_plan_json(apply_repo, capsys, "decision", "DL-01")
    (row,) = out["rows"]
    assert state_op(row) == {"op": "add", "path": STATE, "old": None, "new": "Active"} and "validation" not in row
    out = run_plan_json(apply_repo, capsys, "spec", "0007")
    (row,) = out["rows"]
    assert state_op(row) == {"op": "add", "path": STATE, "old": None, "new": "New"} and "validation" not in row
    assert out["cost"] == {"writes": 0, "creates": 1, "links": 0, "az_spawns": 1}
    code = ado_sync.main(["plan", "--kind", "spec", "--id", "0007", "--no-comments", "--repo", str(apply_repo)])
    assert code == 0 and "then moved" not in capsys.readouterr().out


def test_validate_has_nothing_to_flag_on_a_two_step_row_and_the_hash_is_the_same_with_it(apply_repo, capsys):
    plain = run_plan_json(apply_repo, capsys, "decision", "DL-02")
    checked = run_plan_json(apply_repo, capsys, "decision", "DL-02", extra=["--validate"])
    assert checked["rows"][0]["validation"] == []        # old: ["Issue does not allow creation -> Closed"]
    del checked["rows"][0]["validation"]
    assert checked["rows"] == plain["rows"]


def test_a_state_reachable_in_neither_hop_is_a_finding_on_a_row_that_stays_a_create(apply_repo, capsys):
    # old: no `validation` key at all without --validate, and under --validate the one-hop sentence only
    edit_schema(apply_repo, Issue={"transitions": {"": ["Active"], "Active": ["Active"], "Closed": ["Active"]}})
    out = run_plan_json(apply_repo, capsys, "decision", "DL-02")
    (row,) = out["rows"]
    assert row["action"] == "create"
    assert row["validation"] == ["Issue does not allow creation -> Closed, nor Active -> Closed"]
    assert state_op(row) == {"op": "add", "path": STATE, "old": None, "new": "Closed"}   # no mark: the State is not dropped
    assert out["cost"]["writes"] == 0 and out["cost"]["az_spawns"] == 1
    code = ado_sync.main(["plan", "--kind", "decision", "--id", "DL-02", "--no-comments", "--repo", str(apply_repo)])
    assert code == 0 and "  validate: Issue does not allow creation -> Closed, nor Active -> Closed" in capsys.readouterr().out
    checked = run_plan_json(apply_repo, capsys, "decision", "DL-02", extra=["--validate"])
    assert checked["rows"][0]["validation"] == ["Issue does not allow creation -> Closed, nor Active -> Closed"]


def test_the_transition_check_does_not_need_the_types_field_list(apply_repo, capsys):
    # old: `if facts is None: continue` came before the State check, so a type whose fields were never read was never asked
    edit_schema(apply_repo, Issue={"fields": None,
                                   "transitions": {"": ["Active"], "Active": ["Active"], "Closed": ["Active"]}})
    checked = run_plan_json(apply_repo, capsys, "decision", "DL-02", extra=["--validate"])
    assert checked["rows"][0]["validation"] == ["Issue does not allow creation -> Closed, nor Active -> Closed"]


def test_transitions_that_were_never_read_are_unknown_not_disallowed(apply_repo, capsys):
    # passes before and after: None is "unknown", so the create is one write with the State in it and nothing is said
    edit_schema(apply_repo, Issue={"transitions": None})
    out = run_plan_json(apply_repo, capsys, "decision", "DL-02", extra=["--validate"])
    (row,) = out["rows"]
    assert state_op(row) == {"op": "add", "path": STATE, "old": None, "new": "Closed"}
    assert row["validation"] == [] and out["cost"] == {"writes": 0, "creates": 1, "links": 0, "az_spawns": 1}


# old: there was no `creation_states` or `creation_route`: only `transition_allowed`, which answers one hop
def test_creation_route_reads_the_discovered_transitions_and_nothing_else():
    types = {"Issue": {"transitions": {"": ["Active", "Draft"], "Active": ["Closed"], "Draft": ["Active"]}},
             "Bare": {"transitions": None}, "NoCreation": {"transitions": {"Active": ["Closed"]}},
             "Lonely": {"transitions": {"": ["New"]}}}
    schema = {"types": types}
    assert sm.creation_states(schema, "issue") == ["Active", "Draft"] and sm.creation_states(schema, "Bare") is None
    assert sm.creation_states(schema, "NoCreation") is None and sm.creation_states(schema, "Missing") is None
    assert sm.creation_route(schema, "Issue", "Draft") == ("direct", None)
    assert sm.creation_route(schema, "Issue", "closed") == ("two_step", "Active")      # case-insensitive, the first target
    assert sm.creation_route(schema, "Issue", "Removed") == ("unreachable", "Active")
    assert sm.creation_route(schema, "Bare", "Closed") == ("unknown", None)
    assert sm.creation_route(schema, "NoCreation", "Closed") == ("unknown", None)
    assert sm.creation_route(schema, "Lonely", "Closed") == ("unknown", "New")         # New's own transitions: not read
    assert sm.creation_route({"types": {}}, "Issue", "Closed") == ("unknown", None)


# old: there was no `creation_move`, so a `via` key was an unread extra key on any op of any row
def test_the_mark_belongs_on_the_state_op_of_a_create_row_and_names_another_state():
    good = {"action": "create", "ref": DL02, "ops": [{"op": "add", "path": STATE, "old": None, "new": "Closed",
                                                      "via": "Active"}]}
    assert model.creation_move(good) == ("Active", "Closed")
    assert model.creation_move({"action": "create", "ops": [{"op": "add", "path": STATE, "new": "Active"}]}) is None
    assert model.creation_move({"action": "update", "ops": []}) is None and model.creation_move("x") is None
    for bad in ({**good, "action": "update"},
                {**good, "ops": [{"op": "add", "path": "/fields/System.Title", "new": "x", "via": "Active"}]},
                {**good, "ops": [{"op": "add", "path": STATE, "new": "Closed", "via": "closed"}]},
                {**good, "ops": [{"op": "add", "path": STATE, "new": "Closed", "via": " Active"}]},
                {**good, "ops": [{"op": "add", "path": STATE, "new": "Closed", "via": "Act\nive"}]},
                {**good, "ops": [{"op": "add", "path": STATE, "new": "Closed", "via": 7}]},
                {**good, "ops": [good["ops"][0], good["ops"][0]]}):
        with pytest.raises(ValueError, match="via"):
            model.creation_move(bad)


# old: `build_create_patch` had no `initial_state` and there was no `build_state_move_patch`
def test_the_create_patch_is_born_in_the_initial_state_and_the_move_is_one_guarded_patch():
    projection = {"ref": DL02, "kind": "decision", "fields": {"System.Title": "DL-02 · x", "System.State": "Closed"},
                  "tags": set()}
    args = (projection, {}, "https://dev.azure.com/contoso/Claims/_git/r", "sprd · created", None)
    assert wm.build_create_patch(*args)[0] == {"op": "add", "path": STATE, "value": "Closed"}          # as before
    born = wm.build_create_patch(*args, initial_state="Active")
    assert [op["value"] for op in born if op["path"] == STATE] == ["Active"] and "Closed" not in json.dumps(born)
    assert projection["fields"]["System.State"] == "Closed"                       # the projection itself is untouched
    for bad in ("", " Active", "Act\nive", 7):
        with pytest.raises(ValueError, match="state"):
            wm.build_create_patch(*args, initial_state=bad)
    with pytest.raises(ValueError, match="no System.State"):
        wm.build_create_patch({**projection, "fields": {"System.Title": "DL-02 · x"}}, *args[1:], initial_state="Active")
    assert wm.build_state_move_patch(1, "Closed") == [{"op": "test", "path": "/rev", "value": 1},
                                                      {"op": "replace", "path": STATE, "value": "Closed"}]
    for rev in (0, -1, True, "1", None):
        with pytest.raises(ValueError, match="rev"):
            wm.build_state_move_patch(rev, "Closed")
    with pytest.raises(ValueError, match="state"):
        wm.build_state_move_patch(1, "")


# --- finding 2: apply sends the create, then one guarded PATCH ------------------------------------------------------

def test_apply_creates_in_the_initial_state_then_moves_it_with_one_patch_tested_on_the_creates_rev(
        apply_repo, apply_board, capsys):
    # old: ONE create whose body carried System.State = Closed (the board refused it)
    doc = plan_of(apply_repo, capsys, "decision", "DL-02")
    apply_board.calls.clear()
    seen = {}

    def on_update(args):                  # what the ledger holds the moment the board is asked to move the item
        seen["applied_before_the_move"] = [(e["action"], e["work_item"]) for e in ap.events_of(apply_repo, "applied")]
        return original(args)
    original = apply_board.answers["PATCH wit/workItems"]
    apply_board.answers["PATCH wit/workItems"] = on_update
    res = ap.apply(apply_repo, doc)
    assert (res["exit"], res["failed"], res["deferred"], res["refused_reason"]) == (0, [], [], None)
    assert [(k, a) for k, a, _ in ap.written(apply_board)] == [("POST wit/workItems", ap.written(apply_board)[0][1]),
                                                              ("PATCH wit/workItems", ap.written(apply_board)[1][1])]
    (_, create_argv, create_body), (_, patch_argv, patch_body) = ap.written(apply_board)
    assert state_of(create_body) == "Active" and "Closed" not in json.dumps(create_body)   # born in the initial state
    assert route_params(create_argv)["type"] == "Issue" and route_params(patch_argv)["id"] == "5001"
    assert patch_body == [{"op": "test", "path": "/rev", "value": 1}, {"op": "replace", "path": STATE, "value": "Closed"}]
    assert seen["applied_before_the_move"] == [("create", 5001)]       # the create was ledgered (linked) before the PATCH
    assert [(a["action"], a["work_item"], a["rev_after"]) for a in res["applied"]] == [("create", 5001, 1),
                                                                                       ("update", 5001, 2)]
    create, move = ap.events_of(apply_repo, "applied")
    assert (create["action"], create["rev_before"], create["rev_after"], create["state_pending"]) == ("create", None, 1,
                                                                                                     "Closed")
    assert (move["action"], move["fields"], move["rev_before"], move["rev_after"]) == ("update", ["System.State"], 1, 2)
    assert "state_pending" not in move and move["work_item"] == 5001 and move["ref"] == DL02
    assert is_identity_rest_read(apply_board.calls[0])                 # the move is an `az rest` PATCH: az call 0
    ap.assert_clean_record(apply_repo, res)


def test_a_two_step_create_counts_both_writes_against_the_run(apply_repo, apply_board, capsys):
    # old: a create was one write, so writes_per_run 2 sent the create and DL-01's create and a third row was deferred
    doc = ap.plan_doc(apply_repo, capsys, "--kind", "decision", "--id", "DL-02", "--id", "DL-03", "--no-comments")
    ap.set_config(apply_repo, limits={"writes_per_run": 2, "first_seed": 50})
    res = ap.apply(apply_repo, doc)
    assert [(a["ref"], a["action"]) for a in res["applied"]] == [(DL02, "create"), (DL02, "update")]
    assert [(d["ref"], d["action"], d["why"]) for d in res["deferred"]] == [("sdlc:decision:03", "create",
                                                                              "writes_per_run")]
    assert res["exit"] == 0


@pytest.mark.parametrize("cap, why", [("writes_per_run", "writes_per_run"), ("limit", "limit")])
def test_a_move_the_run_has_no_room_for_is_deferred_and_the_same_plan_applied_again_sends_it(
        apply_repo, apply_board, capsys, cap, why):
    # old: no move existed. Honest reading of the existing rule: the create (a write that fits) is sent and linked, the
    # move is deferred with the cap's own word and exit stays 0 ("a row deferred by --limit or writes_per_run is the
    # person's choice"); applying the same plan again sends the move, never a second create.
    doc = plan_of(apply_repo, capsys, "decision", "DL-02")
    if cap == "writes_per_run":
        ap.set_config(apply_repo, limits={"writes_per_run": 1, "first_seed": 50})
    first = ap.apply(apply_repo, doc, limit=1 if cap == "limit" else None)
    assert first["exit"] == 0 and first["failed"] == []
    assert [(a["ref"], a["action"]) for a in first["applied"]] == [(DL02, "create")]
    assert first["deferred"] == [{"ref": DL02, "action": "update", "why": why}]
    assert [(e["action"], e.get("state_pending")) for e in ap.events_of(apply_repo, "applied")] == [("create", "Closed")]
    assert len(sent_of(apply_board, "POST wit/workItems")) == 1 and sent_of(apply_board, "PATCH wit/workItems") == []
    ap.set_config(apply_repo, limits={"writes_per_run": 50, "first_seed": 50})
    again = ap.apply(apply_repo, doc)
    assert again["exit"] == 0 and again["deferred"] == [] and again["failed"] == []
    assert [(a["ref"], a["action"], a["work_item"], a["rev_after"]) for a in again["applied"]] == [(DL02, "update", 5001, 2)]
    (_, _, patch), = sent_of(apply_board, "PATCH wit/workItems")
    assert patch == [{"op": "test", "path": "/rev", "value": 1}, {"op": "replace", "path": STATE, "value": "Closed"}]
    assert len(sent_of(apply_board, "POST wit/workItems")) == 1                           # never a second create
    third = ap.apply(apply_repo, doc)
    assert (third["applied"], third["deferred"], third["failed"]) == ([], [], [])        # and nothing is owed any more
    assert len(ap.written(apply_board)) == 2


def test_the_plan_notes_the_move_when_the_writes_would_pass_the_cap(apply_repo, capsys):
    # old: 1 create <= writes_per_run 1, so the plan said nothing; the create and its move are 2 writes
    ap.set_config(apply_repo, limits={"writes_per_run": 1, "first_seed": 50})
    out = run_plan_json(apply_repo, capsys, "decision", "DL-02")
    # reworded (was "2 rows is over ..."): it is 1 row and 2 writes, and the cap counts writes
    assert any("2 writes (1 row, 1 of them a create then a move) is over limits.writes_per_run (1)" in n
               for n in out["notes"]), out["notes"]
    out = run_plan_json(apply_repo, capsys, "decision", "DL-01")
    assert not any("writes_per_run" in n for n in out["notes"])


def test_the_writes_per_run_note_counts_rows_exactly_as_before_when_no_row_is_two_step():
    cfg = {"limits": {"writes_per_run": 2, "first_seed": 50}}
    notes = ado_sync._plan_notes(cfg, [], False, {"create": 2, "update": 1})
    assert notes == ["3 rows is over limits.writes_per_run (2); an apply stops at 2, and the next plan covers the rest"]
    notes = ado_sync._plan_notes(cfg, [], False, {"create": 1, "update": 0}, comments=2)
    assert notes == ["3 rows is over limits.writes_per_run (2); an apply stops at 2, and the next plan covers the rest"]
    assert ado_sync._plan_notes(cfg, [], False, {"create": 1, "update": 1}) == []             # at the cap: nothing said
    # a move is the one thing that turns the count into writes: 3 rows, 2 of them a create then a move, are 5 writes
    notes = ado_sync._plan_notes(cfg, [], False, {"create": 2, "update": 1}, moves=2)
    assert notes == ["5 writes (3 rows, 2 of them a create then a move) is over limits.writes_per_run (2); "
                     "an apply stops at 2, and the next plan covers the rest"]
    # and it can pass the cap by the move alone: 1 row at a cap of 1 is fine until its move is counted
    one = {"limits": {"writes_per_run": 1, "first_seed": 50}}
    assert ado_sync._plan_notes(one, [], False, {"create": 1, "update": 0}) == []
    assert len(ado_sync._plan_notes(one, [], False, {"create": 1, "update": 0}, moves=1)) == 1


# --- finding 2: a move the board refuses ----------------------------------------------------------------------------

def next_plan_row(root, capsys, board, case, state: str, rev: int, create_body) -> dict:
    """The one row `plan` offers for the item the board now holds (`state` at `rev`), after a create whose move failed."""
    kind, ident, type_name, _born, _final, _ref = case
    ap.put_batch(board, batch_row_from_create(create_body, 5001, rev, type_name, state))
    doc = plan_of(root, capsys, kind, ident)
    return doc


@MOVES
def test_a_move_the_board_refuses_as_a_rule_leaves_the_item_created_and_the_next_plan_shows_an_update(
        apply_repo, apply_board, capsys, case):
    # old: the board was sent the final State on the create, which it refused: no item, a `rule` row for the create
    kind, ident, type_name, born, final, ref = case
    doc = plan_of(apply_repo, capsys, kind, ident)
    refuse_moves(apply_board, load_wit_error("rule_violation"))
    res = ap.apply(apply_repo, doc)
    assert res["exit"] == 1 and res["deferred"] == []
    assert [(a["ref"], a["action"], a["work_item"]) for a in res["applied"]] == [(ref, "create", 5001)]
    (failed,) = res["failed"]
    assert (failed["ref"], failed["action"], failed["work_item"], failed["class"]) == (ref, "update", 5001, "rule")
    assert failed["field"] == "System.State" and failed["reason"] == "value_not_allowed"
    assert failed["detail"].startswith(f"created #5001; moving it to {final} failed: ")
    create, = [e for e in ap.events_of(apply_repo, "applied")]
    assert create["action"] == "create" and create["work_item"] == 5001 and create["state_pending"] == final
    assert len(sent_of(apply_board, "POST wit/workItems")) == 1 and len(sent_of(apply_board, "PATCH wit/workItems")) == 1
    ap.assert_clean_record(apply_repo, res)
    # the next plan: the item exists (linked), so it is an update from the born state to the final one, never a create
    create_body = sent_of(apply_board, "POST wit/workItems")[0][2]
    again = next_plan_row(apply_repo, capsys, apply_board, case, born, 1, create_body)
    (row,) = again["rows"]
    assert row["action"] == "update" and row["work_item"] == 5001 and row["rev"] == 1
    assert row["ops"] == [{"op": "replace", "path": STATE, "old": born, "new": final}]
    assert [r for r in again["rows"] if r["action"] == "create"] == []


@MOVES
# old: as above: there was no move, so no `update` failed row and no item to plan an update for
def test_a_move_the_board_refuses_as_stale_is_a_conflict_row_and_the_next_plan_shows_an_update(
        apply_repo, apply_board, capsys, case):
    kind, ident, type_name, born, final, ref = case
    doc = plan_of(apply_repo, capsys, kind, ident)
    refuse_moves(apply_board, load_wit_error("stale_rev"))           # `Precondition Failed ... VS403351`, captured
    res = ap.apply(apply_repo, doc)
    assert res["exit"] == 1
    (failed,) = res["failed"]
    assert (failed["ref"], failed["action"], failed["work_item"], failed["class"], failed["reason"]) == (
        ref, "update", 5001, "conflict", "write_conflict")
    assert failed["detail"].startswith(f"created #5001; moving it to {final} failed: ")
    assert [(a["ref"], a["action"]) for a in res["applied"]] == [(ref, "create")]
    (line,) = ap.events_of(apply_repo, "conflict")
    assert (line["ref"], line["work_item"], line["why"], line["rev_before"]) == (ref, 5001, "write_conflict", 1)
    assert [e["action"] for e in ap.events_of(apply_repo, "applied")] == ["create"]       # still linked
    create_body = sent_of(apply_board, "POST wit/workItems")[0][2]
    again = next_plan_row(apply_repo, capsys, apply_board, case, born, 1, create_body)
    (row,) = again["rows"]
    assert row["action"] == "update" and row["ops"] == [{"op": "replace", "path": STATE, "old": born, "new": final}]
    ap.assert_clean_record(apply_repo, res)


# old: the create itself failed (`create sdlc:decision:02  rule ...`) and no item existed
def test_the_cli_says_the_item_was_created_before_it_says_why_the_move_failed(apply_repo, apply_board, capsys):
    doc = plan_of(apply_repo, capsys, "decision", "DL-02")
    refuse_moves(apply_board, load_wit_error("rule_violation"))
    capsys.readouterr()
    code = ado_sync.main(["apply", "--confirm", doc["plan"], "--by", "@dev-one", "--repo", str(apply_repo)])
    text = capsys.readouterr().out
    assert code == 1
    assert "  create sdlc:decision:02 -> #5001 (rev 1)" in text
    (line,) = [ln for ln in text.splitlines() if ln.startswith("  update sdlc:decision:02 #5001")]
    assert line.startswith("  update sdlc:decision:02 #5001  rule (value_not_allowed): created #5001; moving it to "
                           "Closed failed: ")
    assert load_wit_error("rule_violation") not in text                    # a fixed sentence, never the board's words


# old: a refused create was refused again on the same plan: two POSTs, no item, no PATCH
def test_the_same_plan_applied_again_after_a_refused_move_tries_the_move_never_a_second_create(
        apply_repo, apply_board, capsys):
    doc = plan_of(apply_repo, capsys, "decision", "DL-02")
    refuse_moves(apply_board, load_wit_error("rule_violation"))
    assert ap.apply(apply_repo, doc)["exit"] == 1
    again = ap.apply(apply_repo, doc)                                       # still refused: the same row, the move only
    assert [(f["action"], f["class"]) for f in again["failed"]] == [("update", "rule")] and again["applied"] == []
    assert len(sent_of(apply_board, "POST wit/workItems")) == 1 and len(sent_of(apply_board, "PATCH wit/workItems")) == 2


# old: no item was ever created for DL-02, so there was nothing to move and no update row to plan
def test_after_a_refused_move_the_new_plan_applies_and_ends_the_exception(apply_repo, apply_board, capsys):
    # the whole recovery: create, refused move, plan (an update row), apply (the move lands), plan (nothing owed)
    doc = plan_of(apply_repo, capsys, "decision", "DL-02")
    healthy = refuse_moves(apply_board, load_wit_error("rule_violation"))
    assert ap.apply(apply_repo, doc)["exit"] == 1
    create_body = sent_of(apply_board, "POST wit/workItems")[0][2]
    apply_board.answers["PATCH wit/workItems"] = healthy
    ap.put_batch(apply_board, batch_row_from_create(create_body, 5001, 1, "Issue", "Active"))
    replan = plan_of(apply_repo, capsys, "decision", "DL-02")
    (row,) = replan["rows"]
    assert row["action"] == "update" and row["ops"] == [{"op": "replace", "path": STATE, "old": "Active",
                                                         "new": "Closed"}]
    res = ap.apply(apply_repo, replan)
    assert (res["exit"], res["failed"], res["deferred"]) == (0, [], [])
    assert [(a["ref"], a["action"], a["work_item"], a["rev_after"]) for a in res["applied"]] == [(DL02, "update", 5001, 2)]
    (_, _, patch), = sent_of(apply_board, "PATCH wit/workItems")[-1:]
    assert patch == [{"op": "test", "path": "/rev", "value": 1}, {"op": "replace", "path": STATE, "value": "Closed"}]
    assert len(sent_of(apply_board, "POST wit/workItems")) == 1                              # one item, ever
    last = ap.events_of(apply_repo, "applied")[-1]
    assert (last["action"], last["fields"]) == ("update", ["System.State"]) and "state_pending" not in last
    # nothing is owed now: the board holds Closed, and a State the board later changes is the board's again
    ap.put_batch(apply_board, batch_row_from_create(create_body, 5001, 2, "Issue", "Closed"))
    assert plan_of(apply_repo, capsys, "decision", "DL-02")["rows"] == []
    ap.put_batch(apply_board, batch_row_from_create(create_body, 5001, 3, "Issue", "Active"))   # a person reopened it
    assert plan_of(apply_repo, capsys, "decision", "DL-02")["rows"] == []


def test_a_board_owned_state_is_not_pushed_when_nothing_is_owed(apply_repo, apply_board, capsys):
    # passes before and after: a decision's State is the board's once the item exists (`A`); only an owed move changes that
    ap.seed(apply_repo, ap.linked(DL02, 5001, 1, type="Issue"))                      # a plain link: nothing is owed
    row = ap.item_row(5001, "sdlc-repo:claims-api; sdlc:decision:02; sdlc:status:decided", rev=1)
    row["fields"].update({"System.WorkItemType": "Issue", "System.State": "Active"})
    ap.put_batch(apply_board, row)
    out = run_plan_json(apply_repo, capsys, "decision", "DL-02")
    assert out["rows"] == [] and out["counts"]["update"] == 0 and out["counts"]["in_sync"] == 1


# --- finding 2: the plan file is what apply does -------------------------------------------------------------------

def test_a_plan_whose_mark_was_removed_no_longer_hashes_to_its_id_and_nothing_is_sent(apply_repo, apply_board, capsys):
    # old: there was no mark to remove, so a plan could only be edited into the one-step create it never showed
    doc = plan_of(apply_repo, capsys, "decision", "DL-02")
    edited = json.loads(json.dumps(doc))
    del state_op(edited["rows"][0])["via"]
    assert edited["plan"] == doc["plan"]                                                  # the id is still the old one
    apply_board.calls.clear()
    with pytest.raises(ValueError, match="do not hash to its id"):
        ap.apply(apply_repo, edited)
    assert ap.written(apply_board) == [] and apply_board.calls == []


def test_a_plan_written_before_the_mark_existed_is_sent_as_it_showed_one_create_with_its_state(apply_repo, apply_board,
                                                                                               capsys):
    # passes before and after: a row with no mark (a plan file an older `plan` wrote, its own hash recomputed) is one
    # write whose body carries the State it showed, and no PATCH follows
    doc = plan_of(apply_repo, capsys, "decision", "DL-02")
    rows = json.loads(json.dumps(doc["rows"]))
    state_op(rows[0]).pop("via", None)          # (the old code's plan has none to remove)
    old = ap.with_rows(doc, rows)
    assert old["plan"] != doc["plan"] and not apply_mod.needs_rest_writes(old["rows"], ap.load_cfg(apply_repo))
    res = ap.apply(apply_repo, old)
    assert [(a["ref"], a["action"]) for a in res["applied"]] == [(DL02, "create")]
    ((key, _argv, body),) = ap.written(apply_board)
    assert key == "POST wit/workItems" and state_of(body) == "Closed"
    assert not any(is_identity_rest_read(c) for c in apply_board.calls)


# old: a `via` key was ignored, so the create was sent (with the final State)
def test_a_malformed_mark_is_refused_before_anything_is_sent(apply_repo, apply_board, capsys):
    doc = plan_of(apply_repo, capsys, "decision", "DL-02")
    apply_board.calls.clear()
    for bad in ("closed", " Active", "", 7):
        rows = json.loads(json.dumps(doc["rows"]))
        state_op(rows[0])["via"] = bad
        with pytest.raises(ValueError, match="via"):
            ap.apply(apply_repo, ap.with_rows(doc, rows))
    assert ap.written(apply_board) == [] and apply_board.calls == []


def test_a_two_step_plan_needs_the_entra_sign_in_an_update_needs_and_is_refused_whole_without_it(
        apply_repo, apply_board, capsys):
    # old: a create-only plan read no identity, so the create was sent and the move (an `az rest` PATCH) would have died
    doc = plan_of(apply_repo, capsys, "decision", "DL-02")
    assert apply_mod.needs_rest_writes(doc["rows"], ap.load_cfg(apply_repo))
    assert not apply_mod.needs_rest_writes(plan_of(apply_repo, capsys, "decision", "DL-01")["rows"],
                                           ap.load_cfg(apply_repo))
    apply_board.fail["_apis/connectionData"] = "ERROR: Please run 'az login' to setup account."
    apply_board.calls.clear()
    capsys.readouterr()
    code = ado_sync.main(["apply", "--confirm", doc["plan"], "--by", "@dev-one", "--repo", str(apply_repo)])
    text = capsys.readouterr().out
    assert code == 2 and "(reason: identity_unknown)" in text and ado_sync.UPDATE_NEEDS_ENTRA in text
    assert ap.written(apply_board) == [] and len(apply_board.calls) == 1 and is_identity_rest_read(apply_board.calls[0])


def test_a_create_that_is_not_a_move_still_reads_no_identity(apply_repo, apply_board, capsys):
    # passes before and after: a plan of creates that need no move sends them through `az devops invoke` alone
    doc = plan_of(apply_repo, capsys, "decision", "DL-01")
    apply_board.calls.clear()
    res = ap.apply(apply_repo, doc)
    assert res["exit"] == 0 and [(a["action"]) for a in res["applied"]] == ["create"]
    assert not any(is_identity_rest_read(c) for c in apply_board.calls) and len(ap.written(apply_board)) == 1


# old: no move existed; the second create was sent and nothing was a `throttled` failure
def test_a_move_that_hits_a_throttle_stops_the_run_like_any_other_write(apply_repo, apply_board, capsys):
    doc = ap.plan_doc(apply_repo, capsys, "--kind", "decision", "--id", "DL-02", "--id", "DL-03", "--no-comments")
    refuse_moves(apply_board, load_wit_error("throttled"))
    res = ap.apply(apply_repo, doc)
    assert [(f["action"], f["class"]) for f in res["failed"]] == [("update", "throttled")]
    assert [(d["ref"], d["action"], d["why"]) for d in res["deferred"]] == [("sdlc:decision:03", "create", "stopped")]
    assert [(a["ref"], a["action"]) for a in res["applied"]] == [(DL02, "create")]
    assert res["exit"] == 1 and len(sent_of(apply_board, "POST wit/workItems")) == 1


# ====================================================================================================================
# Review of the two commits above (tag case, two-step create), 2026-10-17. Two findings, both MEDIUM.
#
#   * `state_pending` outlived the board's own change of State. `ownership_for_link` made System.State the repository's
#     for as long as the create's `applied` line carried `state_pending`, and only a later `applied`/`linked`/`adopted`
#     line cleared it. A person who closed the item by hand (or a move that landed whose answer or ledger line was
#     lost) left the flag in place, so a LATER board-side reopen was pushed back to Closed, overwriting the person's
#     change. The exception now holds only while the board is as the create left it: `remote["rev"]` is still the
#     `rev_after` the create returned (the revision the move itself tests).
#   * the one-hop creation finding (`<Type> does not allow creation -> <State>`, said when the second hop is not
#     known) lost its only pin when the b2 --validate test was edited for the two-step create.
# ====================================================================================================================

def board_at(board, create_body, state: str, rev: int) -> None:
    """The board answers the item DL-02's create made (#5001) as `state` at `rev`: what a batch read returns after
    someone has edited it."""
    ap.put_batch(board, batch_row_from_create(create_body, 5001, rev, "Issue", state))


@pytest.mark.parametrize("failure", ["rule_violation", "throttled"])
def test_a_state_the_board_has_moved_on_from_is_the_boards_and_is_not_pushed_back(apply_repo, apply_board, capsys,
                                                                                   failure):
    # old: after a person closed the item (rev 2) and reopened it (rev 3), the plan offered `System.State Active ->
    # Closed` again, because `state_pending` was still on the create's ledger line. `throttled` is a move whose outcome
    # is unknown (it may have landed): its create line keeps `state_pending` the same way.
    doc = plan_of(apply_repo, capsys, "decision", "DL-02")
    refuse_moves(apply_board, load_wit_error(failure))
    assert ap.apply(apply_repo, doc)["exit"] == 1
    (create,) = ap.events_of(apply_repo, "applied")
    assert create["action"] == "create" and create["state_pending"] == "Closed" and create["rev_after"] == 1
    create_body = sent_of(apply_board, "POST wit/workItems")[0][2]
    # nobody has touched the item: the owed move is still the repository's to push (the recovery the existing pins cover)
    board_at(apply_board, create_body, "Active", 1)
    (row,) = plan_of(apply_repo, capsys, "decision", "DL-02")["rows"]
    assert row["action"] == "update" and row["ops"] == [{"op": "replace", "path": STATE, "old": "Active", "new": "Closed"}]
    # a person closes it by hand: the board holds what the repository wants, so there is nothing to say
    board_at(apply_board, create_body, "Closed", 2)
    assert plan_of(apply_repo, capsys, "decision", "DL-02")["rows"] == []
    # and reopens it: a decision's State is the board's once anyone has touched the item, so it is not pushed back
    board_at(apply_board, create_body, "Active", 3)
    again = run_plan_json(apply_repo, capsys, "decision", "DL-02")
    assert again["rows"] == [] and again["counts"]["update"] == 0 and again["counts"]["in_sync"] == 1
    assert len(sent_of(apply_board, "PATCH wit/workItems")) == 1                          # nothing was ever sent to push it


def test_the_owed_move_ends_with_the_boards_first_change_to_the_item_whatever_that_change_was(apply_repo, apply_board,
                                                                                               capsys):
    # old: a rev that moved to 2 with the State still Active (a person edited something else) kept the exception, so
    # the plan still pushed the State; the move would have been refused as stale anyway (`test /rev 1`)
    doc = plan_of(apply_repo, capsys, "decision", "DL-02")
    refuse_moves(apply_board, load_wit_error("rule_violation"))
    assert ap.apply(apply_repo, doc)["exit"] == 1
    create_body = sent_of(apply_board, "POST wit/workItems")[0][2]
    board_at(apply_board, create_body, "Active", 2)
    assert plan_of(apply_repo, capsys, "decision", "DL-02")["rows"] == []


def test_ownership_for_link_gives_the_repository_the_state_only_while_the_board_is_as_the_create_left_it():
    # old: `ownership_for_link(kind, link)` read only the link, so the revision was never asked
    owed = {"state_pending": "Closed", "rev_after": 4}
    board_state = model.ownership_for("decision")["System.State"]
    assert board_state == "A"                                                        # a decision's State is the board's
    assert model.ownership_for_link("decision", owed, {"rev": 4})["System.State"] == "S"
    assert model.ownership_for_link("decision", owed, {"rev": 5})["System.State"] == board_state
    assert model.ownership_for_link("decision", owed, {"rev": 3})["System.State"] == board_state
    # nothing owed: no exception, whatever the revisions say
    assert model.ownership_for_link("decision", {"rev_after": 4}, {"rev": 4})["System.State"] == board_state
    assert model.ownership_for_link("decision", {"state_pending": " ", "rev_after": 4}, {"rev": 4}) \
        == model.ownership_for("decision")
    # a revision that cannot be compared ends it: nothing is pushed on a guess
    for link, held in [({"state_pending": "Closed"}, {"rev": 4}), ({"state_pending": "Closed", "rev_after": "4"}, {"rev": 4}),
                       ({"state_pending": "Closed", "rev_after": 4}, {"rev": None}), (owed, {}), (owed, None),
                       ({"state_pending": "Closed", "rev_after": True}, {"rev": True}), (None, {"rev": 4})]:
        assert model.ownership_for_link("decision", link, held)["System.State"] == board_state, (link, held)
    # only System.State changes, and a kind that already owns it (spec) is unchanged
    assert {**model.ownership_for_link("decision", owed, {"rev": 4}), "System.State": board_state} \
        == model.ownership_for("decision")
    assert model.ownership_for_link("spec", owed, {"rev": 9}) == model.ownership_for("spec")


# --- the one-hop creation finding (the pin the two-step create's edit of the b2 test removed) ----------------------

@pytest.mark.parametrize("transitions", [{"": ["Active"]}, {"": []}], ids=["initial-state-not-listed", "no-creation-state"])
def test_validate_says_the_one_hop_sentence_when_the_second_hop_is_not_known(apply_repo, capsys, transitions):
    # passes before and after this commit: it restores the pin of `_state_findings`' `unknown` branch, which the
    # two-step create's edit of test_boards_sync_cli_b2.py::test_plan_validate_checks_the_process_locally_and_still_
    # never_writes left with no test. The route is `unknown` because the initial state's own transitions are not read
    # (`{"": ["Active"]}` has no "Active" row; `{"": []}` lists no state to create in), and creation -> Closed is refused.
    edit_schema(apply_repo, Issue={"transitions": transitions})
    assert sm.creation_route(json.loads((apply_repo / bc.SCHEMA_FILE).read_text(encoding="utf-8")), "Issue",
                             "Closed")[0] == "unknown"
    plain = run_plan_json(apply_repo, capsys, "decision", "DL-02")
    (plain_row,) = plain["rows"]
    assert "validation" not in plain_row                                       # said under --validate only: it is not `unreachable`
    checked = run_plan_json(apply_repo, capsys, "decision", "DL-02", extra=["--validate"])
    (row,) = checked["rows"]
    assert row["action"] == "create"
    assert row["validation"] == ["Issue does not allow creation -> Closed"]    # the one-hop sentence, no `nor` clause
    assert state_op(row) == {"op": "add", "path": STATE, "old": None, "new": "Closed"}      # no `via`: nothing is two-step
    assert checked["cost"]["writes"] == 0 and checked["cost"]["az_spawns"] == 1
    code = ado_sync.main(["plan", "--kind", "decision", "--id", "DL-02", "--no-comments", "--validate", "--repo",
                          str(apply_repo)])
    text = capsys.readouterr().out
    assert code == 0 and "  validate: Issue does not allow creation -> Closed" in text and "nor" not in text


def test_validate_says_nothing_when_the_creation_row_allows_the_state_or_the_transitions_are_unread(apply_repo, capsys):
    # passes before and after: the one-hop sentence needs `creation -> State` to be KNOWN refused; a creation row that
    # lists the State, or no transitions at all, is not a finding
    edit_schema(apply_repo, Issue={"transitions": {"": ["Active", "Closed"]}})
    row, = run_plan_json(apply_repo, capsys, "decision", "DL-02", extra=["--validate"])["rows"]
    assert row["validation"] == [] and "via" not in state_op(row)
    edit_schema(apply_repo, Issue={"transitions": None})
    row, = run_plan_json(apply_repo, capsys, "decision", "DL-02", extra=["--validate"])["rows"]
    assert row["validation"] == []
