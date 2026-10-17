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
