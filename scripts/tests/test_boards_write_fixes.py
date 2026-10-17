"""B0 write fixes — the four defects the first live `apply` (2026-10-15) exposed, pinned where `apply` and `plan` meet them.

  * A — an update cannot go through `az devops invoke` (the extension binds `…/workItems/${type}` for a PATCH and dies
    with `ERROR: 'type'`); it is `az rest --method patch`, which needs an Entra sign-in. A plan that would PATCH a work
    item reads `connectionData` first, and under a personal access token alone the whole plan is refused
    `identity_unknown` (exit 2, nothing sent), with words that say the update transport needs Entra.
  * B — a create whose `System.AssignedTo` the organisation does not know is a `rule` failure of THAT row: the run goes
    on, and the row names the field (`System.AssignedTo`) and the reason (`unknown_identity`), never the board's words.
    It was `unknown`, a stop class, and the five rows after it were deferred as stopped.
  * C — (the WIQL macro) is pinned in test_boards_wit_map.py, test_boards_wit_reads.py and test_boards_sync_cli_b2.py; a
    `drift` whose untagged search printed nothing says so in a note (here).
  * D — every create sets the config's `area_path` (`System.AreaPath`); the plan shows it; an update never sends it; a
    board-side move is the board's (`ADO_OWNED_CHANGE`), never drift. The four items of the live run landed at the
    project root, outside the team's board.

And the comment fact: posting a comment moves the item's `rev` (2 -> 3, captured), so an item this run commented on is
re-read before this run PATCHes it again.

These scenarios combine the hand-written item fixtures with a process, so they read the hand-written process
(`BOARDS_PROCESS`), as the apply tests they build on do. Nothing here spawns `az`.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import HAND_WRITTEN_PROCESS
from tests.ado_boards_fixtures import is_identity_rest_read, load_wit_error, route_key_boards, route_params
from tests.test_boards_sync_apply import (SPEC4, SPEC5, adhoc, apply, assert_clean_record, board, board_row,  # noqa: F401
                                          clock, events_of, fail_with, item_row, linked, load_cfg, load_schema,
                                          plan_doc, put_batch, repo, seed, set_config, title_of, two_updates,
                                          with_rows, written)

import json
from datetime import datetime, timezone

import pytest

import ado_sync
import ado_sync_apply as apply_mod
import ado_sync_model as model
import ado_transport
import ado_wit_map as wm
import boards_contract as bc

BOARDS_PROCESS = HAND_WRITTEN_PROCESS

AREA = "Claims\\SDLC"          # the starter config's `area_path` (templates/ado/ado.yaml)
AREA_OP = "/fields/System.AreaPath"
NOW = datetime(2026, 10, 12, 9, 7, tzinfo=timezone.utc)


def create_rows(doc: dict) -> list[dict]:
    return [r for r in doc["rows"] if r["action"] == "create"]


def creates_sent(board) -> list[list[dict]]:
    return [body for key, _argv, body in written(board) if key == "POST wit/workItems"]


# --- Defect D: the area path at create -------------------------------------------------------------------------

def test_every_create_the_plan_shows_sets_the_configured_area(repo, capsys):
    assert load_cfg(repo)["area_path"] == AREA
    doc = plan_doc(repo, capsys, "--kind", "epic", "--kind", "feature", "--kind", "spec")
    rows = create_rows(doc)
    assert len(rows) == 7
    for row in rows:
        (op,) = [o for o in row["ops"] if o["path"] == AREA_OP]
        assert (op["op"], op["old"], op["new"]) == ("add", None, AREA), row["ref"]


def test_every_create_apply_sends_carries_the_area_and_the_ledger_names_the_field(repo, board, capsys):
    doc = plan_doc(repo, capsys, "--kind", "epic", "--kind", "feature", "--kind", "spec")
    board.calls.clear()
    res = apply(repo, doc)
    assert (res["exit"], res["failed"], res["deferred"]) == (0, [], [])
    bodies = creates_sent(board)
    assert len(bodies) == 7
    for body in bodies:
        assert [op["value"] for op in body if op["path"] == AREA_OP] == [AREA], title_of(body)
    assert all("System.AreaPath" in e["fields"] for e in events_of(repo, "applied") if e["action"] == "create")
    # the moves of 0004 and 0005 are `az rest` PATCHes, which need the Entra sign-in an update needs: it is read once,
    # first (a plan of creates that need no move has no such read: test_boards_live_fixes.py)
    assert [is_identity_rest_read(c) for c in board.calls].count(True) == 1 and is_identity_rest_read(board.calls[0])


def test_with_no_area_configured_a_create_sets_none(repo, board, capsys):
    set_config(repo, area_path="")
    doc = plan_doc(repo, capsys, "--kind", "epic", "--id", "EP-001")
    assert not any(o["path"] == AREA_OP for r in create_rows(doc) for o in r["ops"])
    assert apply(repo, doc)["exit"] == 0
    assert not any(op["path"] == AREA_OP for body in creates_sent(board) for op in body)


def test_the_area_rides_the_create_patch_only_and_the_projections_own_area_wins():
    projection = {"ref": "sdlc:epic:001", "kind": "epic", "fields": {"System.Title": "EP-001 · x"}, "tags": set()}
    patch = wm.build_create_patch(projection, {}, "https://dev.azure.com/contoso/Claims/_git/r", "sprd · created", None,
                                  area_path=AREA)
    assert [op for op in patch if op["path"] == AREA_OP] == [{"op": "add", "path": AREA_OP, "value": AREA}]
    assert "System.AreaPath" not in projection["fields"]                  # the projection itself is not changed
    own = {**projection, "fields": {**projection["fields"], "System.AreaPath": "Claims\\Other"}}
    assert wm.with_create_fields(own, AREA)["fields"]["System.AreaPath"] == "Claims\\Other"
    assert wm.with_create_fields(projection, None) is projection
    assert wm.configured_area({"area_path": "  "}) is None and wm.configured_area({}) is None
    assert wm.configured_area({"area_path": f" {AREA} "}) == AREA
    for bad in ("", " x", "a\nb", 7):
        with pytest.raises(ValueError, match="area"):
            wm.with_create_fields(projection, bad)


def test_an_update_never_sends_the_area_even_when_the_board_moved_the_item(repo, board, capsys):
    moved = board_row()
    moved["fields"]["System.AreaPath"] = "Claims\\Elsewhere"            # a person moved it on the board
    seed(repo, linked(SPEC4, 4521, 7))
    put_batch(board, moved)
    doc = plan_doc(repo, capsys, "--kind", "spec", "--id", "0004", "--no-comments")
    (row,) = doc["rows"]
    assert row["action"] == "update" and AREA_OP not in {o["path"] for o in row["ops"]}
    board.calls.clear()
    assert apply(repo, doc)["exit"] == 0
    (patch,) = [body for key, _argv, body in written(board) if key == "PATCH wit/workItems"]
    assert AREA_OP not in {op["path"] for op in patch}


def test_a_board_side_area_move_is_the_boards_change_never_drift():
    assert bc.OWNERSHIP["System.AreaPath"] == "C"
    ledger_row = {"ref": SPEC4, "kind": "spec", "work_item": 4521, "rev_after": 7, "projection_hash": "0" * 12,
                  "type": "User Story"}
    remote = {"id": 4521, "rev": 8, "type": "User Story"}
    projection = {"ref": SPEC4, "kind": "spec", "fields": {"System.Title": "0004 · x"}, "tags": set()}
    updates = [{"rev": 8, "revisedDate": "2026-10-15T09:04:00Z",
                "fields": {"System.AreaPath": {"oldValue": "Claims", "newValue": AREA}}}]
    got = model.classify_drift(ledger_row, remote, projection, updates)
    assert got["class"] == "ADO_OWNED_CHANGE"
    (field,) = got["fields"]
    assert (field["field"], field["class"], field["owner"]) == ("System.AreaPath", "ADO_OWNED_CHANGE", "C")


# --- Defect B: an unknown identity fails its own row ------------------------------------------------------------

def test_an_assignee_the_organisation_does_not_know_fails_that_row_and_the_run_goes_on(repo, board, capsys):
    doc = plan_doc(repo, capsys, "--kind", "epic", "--kind", "feature", "--kind", "spec")
    assigned = [r["ref"] for r in create_rows(doc) if any(o["path"] == "/fields/System.AssignedTo" for o in r["ops"])]
    assert assigned == [SPEC4, SPEC5]           # both specs' people are on the roster; the board knows only one of them
    text = load_wit_error("identity_unknown")                             # captured 2026-10-15
    assert wm.classify_write_error(text) == "rule"
    fail_with(board, "POST wit/workItems", text, lambda args, body: title_of(body).startswith("0005"))
    board.calls.clear()
    res = apply(repo, doc)
    assert res["exit"] == 1 and res["refused_reason"] is None
    (failed,) = res["failed"]
    assert (failed["ref"], failed["action"], failed["class"], failed["work_item"]) == (SPEC5, "create", "rule", None)
    assert (failed["field"], failed["reason"]) == ("System.AssignedTo", "unknown_identity")
    assert "System.AssignedTo" in failed["detail"] and "people[].email" in failed["detail"]
    assert res["deferred"] == []                                          # nothing was stopped by it
    assert {a["ref"] for a in res["applied"]} == {r["ref"] for r in create_rows(doc)} - {SPEC5}
    assert_clean_record(repo, res)                                        # no address, no board words


def test_a_value_outside_a_picklist_names_its_field_on_an_update(repo, board, two_updates):
    fail_with(board, "PATCH wit/workItems", load_wit_error("rule_violation"),
              lambda args, body: route_params(args)["id"] == "4521")
    res = apply(repo, two_updates)
    (failed,) = res["failed"]
    assert (failed["ref"], failed["class"], failed["field"], failed["reason"]) == (SPEC4, "rule", "System.State",
                                                                                  "value_not_allowed")
    assert "System.State" in failed["detail"] and [a["ref"] for a in res["applied"]] == [SPEC5]


def test_a_stale_rev_from_the_board_is_a_conflict_row_and_the_next_update_runs(repo, board, two_updates):
    fail_with(board, "PATCH wit/workItems", load_wit_error("stale_rev"),       # `Precondition Failed … VS403351`
              lambda args, body: route_params(args)["id"] == "4521")
    res = apply(repo, two_updates)
    assert [(f["ref"], f["class"], f["reason"]) for f in res["failed"]] == [(SPEC4, "conflict", "write_conflict")]
    assert [a["ref"] for a in res["applied"]] == [SPEC5] and res["deferred"] == []


# --- Defect A: the update transport needs an Entra sign-in -------------------------------------------------------

def test_apply_of_updates_under_a_pat_only_sign_in_is_refused_with_the_entra_words(repo, board, two_updates, capsys):
    board.fail["_apis/connectionData"] = "ERROR: Please run 'az login' to setup account."
    capsys.readouterr()
    code = ado_sync.main(["apply", "--confirm", two_updates["plan"], "--by", "@dev-one", "--repo", str(repo)])
    text = capsys.readouterr().out
    assert code == 2 and "(reason: identity_unknown)" in text
    assert ado_sync.UPDATE_NEEDS_ENTRA in text and "Please run" not in text
    assert len(board.calls) == 1 and is_identity_rest_read(board.calls[0]) and written(board) == []
    code = ado_sync.main(["apply", "--confirm", two_updates["plan"], "--by", "@dev-one", "--repo", str(repo), "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert code == 2 and doc["refused_reason"] == "identity_unknown" and doc["applied"] == []


def test_a_refusal_of_a_create_only_plan_does_not_mention_the_update_transport(repo, board, capsys):
    set_config(repo, posture="plan-only")
    doc = plan_doc(repo, capsys, "--kind", "epic", "--id", "EP-001")
    assert not apply_mod.needs_rest_writes(doc["rows"], load_cfg(repo))
    code = ado_sync.main(["apply", "--confirm", doc["plan"], "--by", "@dev-one", "--repo", str(repo)])
    assert code == 2 and ado_sync.UPDATE_NEEDS_ENTRA not in capsys.readouterr().out


def test_needs_rest_writes_is_an_update_or_a_history_comment():
    update, create = {"action": "update"}, {"action": "create"}
    draft = {"action": "comment", "status": "draft"}
    assert apply_mod.needs_rest_writes([create, update], {}) and not apply_mod.needs_rest_writes([create, draft], {})
    history = {"comments": {"transport": "history"}}
    assert apply_mod.needs_rest_writes([draft], history)
    assert not apply_mod.needs_rest_writes([{**draft, "status": "skipped"}], history)
    assert not apply_mod.needs_rest_writes([], {}) and not apply_mod.needs_rest_writes(None, None)


# --- a comment moves the rev: a later PATCH of the same item re-reads it ----------------------------------------

def test_a_patch_after_this_runs_own_comment_tests_the_revision_the_board_is_at(repo, board):
    """Captured 2026-10-15: posting a comment moved the item from rev 2 to 3, and the comments API answer does not say so.
    A History entry (a PATCH guarded by `test /rev`) on the same item later in the run re-reads the rev first."""
    seed(repo, linked(SPEC4, 4521, 7))
    cfg = load_cfg(repo)
    run = apply_mod._Run(repo, "0" * 12, "@dev-one", cfg, load_schema(repo), lambda: NOW,
                         apply_mod._read_ledger(repo))
    run.cap, run.revs[4521] = 10, 7
    run.comment(adhoc(repo, "first, through the comments API"))
    assert [a["transport"] for a in run.applied] == ["comments-api"] and 4521 in run.rev_stale
    moved = board_row()
    moved["rev"] = 8                                                      # what the comment did to the item
    put_batch(board, moved)
    run.transport = "history"
    run.comment(adhoc(repo, "then, through the History field"))
    keys = [route_key_boards(c) for c in board.calls]
    assert keys == ["POST wit/comments", "POST wit/workitemsbatch", "PATCH wit/workItems"]
    (patch,) = [body for key, _argv, body in written(board) if key == "PATCH wit/workItems"]
    assert patch[0] == {"op": "test", "path": "/rev", "value": 8}         # not the 7 this run read before the comment
    assert 4521 not in run.rev_stale and run.failed == []


def test_a_rev_that_cannot_be_re_read_is_a_conflict_and_nothing_is_patched(repo, board):
    seed(repo, linked(SPEC4, 4521, 7))
    run = apply_mod._Run(repo, "0" * 12, "@dev-one", load_cfg(repo), load_schema(repo), lambda: NOW,
                         apply_mod._read_ledger(repo))
    run.cap, run.revs[4521], run.transport = 10, 7, "history"
    run.rev_stale.add(4521)
    board.fail["workitemsbatch"] = "ERROR: timed out"
    run.comment(adhoc(repo, "a fact"))
    assert [(f["class"], f["reason"]) for f in run.failed] == [("conflict", "rev_unread")]
    assert not any(key == "PATCH wit/workItems" for key, _a, _b in written(board)) and run.writes == 0


# --- Defect C: a search that printed nothing says so ------------------------------------------------------------

def test_drift_says_when_the_untagged_search_printed_nothing(repo, board, capsys):
    board.answers["boards query sdlc-repo:"] = None                       # zero bytes, exit 0
    capsys.readouterr()
    assert ado_sync.main(["drift", "--repo", str(repo), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["unmapped"] == [] and any("printed nothing" in n for n in out["notes"])
    wiql = next(c for c in board.calls if c[:2] == ["boards", "query"])
    text = wiql[wiql.index("--wiql") + 1]
    assert "@project" not in text and "[System.TeamProject] = 'Claims'" in text
    assert ado_transport.remote(repo).project == "Claims"


# --- security review of PR #5 (2026-10-16): a project name never carries a cmd.exe expansion character -----------

def test_a_project_name_with_a_cmd_expansion_character_is_refused():
    """On Windows `az` resolves to `az.cmd` and cmd.exe re-parses the argv, so `%VAR%` / `!VAR!` inside the quoted
    WIQL would expand before the board saw it. The whitelist refuses both; the characters Azure DevOps really allows
    in a project name (letters of any script, digits, space, `.()&~^@-`) still pass."""
    import ado_wit_map as wm
    for ok in ("Expedition One", "Claims", "Ops-2026", "R&D (EU)", "Proj~1", "a^b", "Café", "x@y"):
        assert wm.project_clause(ok) == f"[System.TeamProject] = '{ok}'"
    for bad in ("%PATH%", "!X!", "a%b", "bang!", "it's", "x\\y", "[p]", "tab\tname"):
        try:
            wm.project_clause(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should have been refused")
