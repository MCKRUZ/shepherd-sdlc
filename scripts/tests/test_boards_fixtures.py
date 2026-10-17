"""The Boards test harness itself: the router, the read-only pin and the no-az seam (B1-P0).

`tests/ado_boards_fixtures.py` is what every `test_boards_*.py` stands on, so its own guarantees
are pinned here: `boards_env` (autouse) forbids a real `az` at the transport seam, `az` swaps in
a `FakeBoardsAz` that answers from the `wit/` fixtures, an unknown route is an AssertionError,
and with `writes=False` a write is one too — while the two read-only POSTs still pass.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import HAND_WRITTEN_PROCESS

import json
import re
from pathlib import Path

import pytest

import ado_map
import ado_transport
import boards_contract as bc
import code_host
from tests import ado_boards_fixtures as abf
from tests.ado_fixtures import ADO_REMOTE

# B0 (2026-10-15): the second capture shadowed the item, write and comment fixtures (`WIT_CAPTURED_ITEMS`); this module's
# scenarios pin the hand-written ones' ids and texts, so it reads those (`BOARDS_ITEMS`, tests/ado_boards_fixtures.py).
# The captured answers are exercised in test_boards_captured_items.py.
BOARDS_ITEMS = HAND_WRITTEN_PROCESS

ORG = "https://dev.azure.com/contoso"
SCOPE = ["--detect", "false", "--org", ORG]


def invoke(area, resource, *route, method=None):
    args = ["devops", "invoke", "--area", area, "--resource", resource, "--route-parameters", *route]
    if method:
        args += ["--http-method", method]
    return [*args, "--api-version", "7.1", *SCOPE, "-o", "json"]


# --- route keys ---------------------------------------------------------------------------------

@pytest.mark.parametrize("args, key", [
    (invoke("wit", "workItemTypes", "project=Claims"), "GET wit/workItemTypes"),
    (invoke("wit", "wiql", "project=Claims", method="POST"), "POST wit/wiql"),
    (invoke("wit", "workItems", "project=Claims", "id=7", method="PATCH"), "PATCH wit/workItems"),
    (invoke("wit", "workItems", "project=Claims", "id=7", method="patch"), "PATCH wit/workItems"),
    (["boards", "query", *SCOPE, "--project", "Claims", "--wiql", "SELECT [System.Id] FROM WorkItems"], "boards query"),
    (["repos", "pr", "work-item", "add", "--id", "12", "--work-items", "7", *SCOPE], "repos pr work-item add"),
    (["account", "show"], "account show"),
])
def test_route_key_boards(args, key):
    assert abf.route_key_boards(args) == key


# --- the seam -----------------------------------------------------------------------------------

def test_boards_env_forbids_az_at_the_seam(tmp_path):
    with pytest.raises(AssertionError, match="az spawned"):
        ado_transport.run_az(["account", "show"], tmp_path)
    with pytest.raises(AssertionError, match="az spawned"):
        ado_transport.az_json(["account", "show"], tmp_path)  # az_json reaches run_az through the module
    binary = ado_transport.az_binary()
    assert binary == "/nonexistent/az-forbidden" and not Path(binary).exists()


def test_boards_env_pins_the_remote_and_clears_the_host_env(tmp_path):
    import os
    assert all(name not in os.environ for name in code_host.CODE_HOST_ENV_VARS)
    assert code_host.origin_url(tmp_path) == ADO_REMOTE
    remote = ado_transport.remote(tmp_path)
    assert (remote.org_url, remote.project) == (ORG, "Claims")


def test_az_fixture_replaces_run_az_and_records_argv(az, tmp_path):
    assert ado_transport.run_az is az
    doc = ado_transport.az_json(["devops", "invoke", "--area", "wit", "--resource", "workItemTypes",
                                 "--route-parameters", "project=Claims", "--api-version", "7.1", *SCOPE], tmp_path)
    assert doc == abf.load_wit("types")
    assert az.calls[-1][-2:] == ["-o", "json"] and "--only-show-errors" not in az.calls[-1]
    assert all(c[c.index("--detect") + 1] == "false" for c in az.calls)
    assert az.count("devops", "invoke") == 1 and az.count("account", "show") == 0


# --- the router ---------------------------------------------------------------------------------

def test_unknown_route_is_an_assertion(az, tmp_path):
    with pytest.raises(AssertionError, match=r"^unexpected az call: GET wit/nothingHere$"):
        az(invoke("wit", "nothingHere", "project=Claims"), tmp_path)
    assert len(az.calls) == 1


def test_read_only_fake_refuses_a_write_even_when_answered(tmp_path):
    fake = abf.FakeBoardsAz({"PATCH wit/workItems": {"id": 7}})
    with pytest.raises(AssertionError, match=r"^unexpected az write: PATCH wit/workItems$"):
        fake(invoke("wit", "workItems", "project=Claims", "id=7", method="PATCH"), tmp_path)
    for method in ("POST", "PUT", "DELETE"):
        with pytest.raises(AssertionError, match="unexpected az write"):
            fake(invoke("wit", "workItems", "project=Claims", method=method), tmp_path)
    with pytest.raises(AssertionError, match="unexpected az write: repos pr work-item add"):
        fake(["repos", "pr", "work-item", "add", "--id", "12", "--work-items", "7", *SCOPE], tmp_path)


def test_read_only_fake_passes_the_two_read_posts(tmp_path):
    fake = abf.FakeBoardsAz({"POST wit/wiql": {"workItems": [{"id": 7}]}, "POST wit/workitemsbatch": {"count": 0, "value": []}})
    assert json.loads(fake(invoke("wit", "wiql", "project=Claims", method="POST"), tmp_path)) == {"workItems": [{"id": 7}]}
    assert json.loads(fake(invoke("wit", "workitemsbatch", "project=Claims", method="POST"), tmp_path))["count"] == 0
    assert fake.written() == []


def test_writing_fake_answers_writes_and_lists_them(tmp_path):
    fake = abf.FakeBoardsAz({"PATCH wit/workItems": {"id": 7, "rev": 3}}, writes=True)
    patch = invoke("wit", "workItems", "project=Claims", "id=7", method="PATCH")
    assert json.loads(fake(patch, tmp_path)) == {"id": 7, "rev": 3}
    fake(invoke("wit", "workItemTypes", "project=Claims"), tmp_path)
    assert fake.written() == [patch]


def test_fail_needle_raises_the_transport_error(tmp_path):
    fake = abf.FakeBoardsAz(fail={"workItemTypeCategories": "403 Forbidden"})
    with pytest.raises(ado_map.AdoImportError, match="403 Forbidden"):
        fake(invoke("wit", "workItemTypeCategories", "project=Claims"), tmp_path)
    assert fake.count("devops", "invoke") == 1


def test_answer_forms(tmp_path):
    seen = []
    fake = abf.FakeBoardsAz({"boards query": None, "GET wit/updates": lambda args: seen.append(args) or {"count": 0},
                             "GET wit/workItemTypes": "type_categories"})
    assert fake(["boards", "query", *SCOPE], tmp_path) == ""  # az printed nothing
    assert json.loads(fake(invoke("wit", "updates", "project=Claims", "id=7"), tmp_path)) == {"count": 0}
    assert seen and seen[0][:2] == ["devops", "invoke"]
    assert json.loads(fake(invoke("wit", "workItemTypes", "project=Claims"), tmp_path)) == abf.load_wit("type_categories")


def test_per_type_routes_resolve_by_the_type_route_parameter(tmp_path):
    """B0: at the corrected locations, `workItemTypeStates` and `workItemTypesField`. The hand-written ones
    (`states`, `fields` with a `type`) are answered by nothing — the real az refuses or ignores them."""
    fake = abf.FakeBoardsAz()
    for wit_type, name in (("User Story", "type_states_user_story"), ("Bug", "type_states_bug"), ("Issue", "type_states_issue"),
                           ("Spec", "type_states_spec"), ("RAID", "type_states_raid")):
        got = fake(invoke("wit", "workItemTypeStates", "project=Claims", f"type={wit_type}"), tmp_path)
        assert json.loads(got) == abf.load_wit(name)
    got = fake(invoke("wit", "workItemTypesField", "project=Claims", "type=Issue"), tmp_path)
    assert json.loads(got) == abf.load_wit("type_fields_issue")
    assert json.loads(fake(invoke("wit", "fields", "project=Claims"), tmp_path)) == abf.load_wit("fields")
    with pytest.raises(AssertionError, match="unexpected az call: GET wit/workItemTypeStates"):
        fake(invoke("wit", "workItemTypeStates", "project=Claims", "type=Task"), tmp_path)
    with pytest.raises(AssertionError, match="unexpected az call: GET wit/states"):
        fake(invoke("wit", "states", "project=Claims", "type=User Story"), tmp_path)
    # `fields` with a `type` is the project-wide list (the capture's own finding), never a type's fields
    assert json.loads(fake(invoke("wit", "fields", "project=Claims", "type=Issue"), tmp_path)) == abf.load_wit("fields")


def test_default_answers_cover_every_hand_written_fixture_and_only_those():
    assert set(abf.DEFAULT_WIT_ANSWERS.values()) == set(abf.WIT_FIXTURE_NAMES)
    for name in abf.WIT_FIXTURE_NAMES:
        assert abf.wit_path(name).is_file(), name


def _path(name: str) -> Path:
    """The file `load_wit(name)` reads in this module: the hand-written one for an item the capture shadowed."""
    return abf.wit_path(name, hand_written=name in abf.WIT_CAPTURED_ITEMS)


@pytest.mark.parametrize("name", abf.WIT_FIXTURE_NAMES)
def test_each_fixture_command_routes_to_its_own_default_answer(name, tmp_path):
    """A fixture's `_command` is the call it answers; the router must send that call back to it. (The captured item
    commands are routed to their captured answers in test_boards_captured_items.py.)"""
    command = json.loads(_path(name).read_text(encoding="utf-8"))["_command"]
    assert command[0] == "az"
    out = abf.FakeBoardsAz(writes=abf.is_write_key(abf.route_key_boards(command[1:])))([*command[1:], "-o", "json"], tmp_path)
    assert json.loads(out) == abf.load_wit(name)


def _command_of(name: str) -> list:
    return json.loads(_path(name).read_text(encoding="utf-8"))["_command"]


# Only `devops invoke` fixtures have a WIT_ROUTES row; native verbs (`account show`, `boards query`,
# `boards work-item show`) have none by design.
@pytest.mark.parametrize("name", [n for n in abf.WIT_FIXTURE_NAMES if _command_of(n)[1:3] == ["devops", "invoke"]])
def test_each_invoke_fixture_command_agrees_with_wit_routes(name):
    command = _command_of(name)
    route_name = abf.route_name_of(name)
    row = bc.WIT_ROUTES[route_name]
    assert command[command.index("--area") + 1] == row["area"]
    assert command[command.index("--resource") + 1] == row["resource"]
    i = command.index("--route-parameters") + 1
    params = []
    while i < len(command) and not command[i].startswith("--"):
        params.append(command[i].split("=", 1)[0])
        i += 1
    assert tuple(p for p in params if p) == row["route"]
    assert command[command.index("--api-version") + 1] == row["api_version"]


# --- loading ------------------------------------------------------------------------------------

def test_load_wit_unwraps_value_and_reads_null_as_empty(tmp_path, monkeypatch):
    assert isinstance(abf.load_wit("types"), dict) and abf.load_wit("types")["value"]
    monkeypatch.setattr(abf, "WIT", tmp_path)
    (tmp_path / "empty.json").write_text(json.dumps({"_provenance": abf.HAND_WRITTEN, "_command": None, "value": None}))
    assert abf.load_wit("empty") == []


B0_CAPTURED = {"projects", "type_categories", "types", "fields", "backlog_config", "classification_nodes",
               "team_iterations", "relation_types", "connection_data", "type_states_user_story", "type_states_bug",
               "type_states_issue", "type_fields_user_story", "type_fields_issue", *abf.WIT_CAPTURED_ONLY,
               *abf.WIT_CAPTURED_ITEMS}   # the second capture (2026-10-15): the item, write and comment answers
B0_ITEMS = {"comment_add_response", "comments", "updates", "wiql_by_tag", "workitem_create_response",
            "workitem_show_relations", "workitem_update_response", "workitems_batch"}


def test_every_name_resolves_to_the_capture_where_there_is_one_and_to_the_hand_written_file_otherwise():
    """B0 (2026-10-14): the discovery reads and the identity read resolve to the capture; B0 (2026-10-15): so do the
    item, write and comment answers the second capture reached. The rest of the item, history, discussion and write
    fixtures resolve to the hand-written files (nothing captured them yet)."""
    assert set(abf.WIT_CAPTURED_ITEMS) == B0_ITEMS
    sources = {n: abf.wit_source_of(n) for n in abf.WIT_FIXTURE_NAMES}
    assert {n for n, s in sources.items() if s == "captured"} == B0_CAPTURED
    assert {n for n, s in sources.items() if s != "captured"} == set(abf.WIT_FIXTURE_NAMES) - B0_CAPTURED
    assert set(sources.values()) == {"captured", "hand-written"}
    for name in abf.WIT_CAPTURED_REFERENCE:  # loaded by name, but no route answers with it
        assert abf.wit_source_of(name) == "captured" and name not in abf.DEFAULT_WIT_ANSWERS.values()
    for name in B0_ITEMS:   # each still has its hand-written twin, which the scenario modules read
        assert abf.wit_path(name, hand_written=True).parent == abf.WIT


def test_a_hand_written_fake_answers_from_the_hand_written_file_where_a_capture_exists(tmp_path):
    captured, hand = abf.FakeBoardsAz(), abf.FakeBoardsAz(hand_written=True)
    call = invoke("wit", "workItemTypes", "project=Claims")
    assert json.loads(captured(call, tmp_path)) == abf.load_wit("types") != abf.load_wit("types", hand_written=True)
    assert json.loads(hand(call, tmp_path)) == abf.load_wit("types", hand_written=True)
    # this module reads the hand-written items (`BOARDS_ITEMS`): either fake answers the batch from that file
    batch = invoke("wit", "workitemsbatch", "project=Claims", method="POST")
    hand_batch = abf.load_wit("workitems_batch", hand_written=True)
    assert json.loads(hand(batch, tmp_path)) == json.loads(captured(batch, tmp_path)) == hand_batch
    assert abf.load_wit("workitems_batch") == hand_batch != abf.load_captured("workitems_batch")


def test_a_module_opts_into_the_hand_written_process_by_name():
    class Module:
        BOARDS_PROCESS = abf.HAND_WRITTEN_PROCESS

    class Items:
        BOARDS_ITEMS = abf.HAND_WRITTEN_PROCESS
    assert abf.uses_hand_written_process(Module) and not abf.uses_hand_written_process(object())
    # B0 (2026-10-15): the whole process implies the items; the items alone do not imply the process
    assert abf.uses_hand_written_items(Module) and abf.uses_hand_written_items(Items)
    assert not abf.uses_hand_written_process(Items) and not abf.uses_hand_written_items(object())


def test_the_items_switch_is_on_only_while_a_test_of_an_opted_in_module_runs():
    assert abf._HAND_WRITTEN_ITEMS == [True]      # this module sets BOARDS_ITEMS
    assert abf.load_wit("comments") == abf.load_wit("comments", hand_written=True)
    assert abf.load_wit("types") == abf.load_captured("types")   # a process name is not an item: still the capture


def test_the_identity_read_is_routed_by_its_rest_url(tmp_path):
    """B0: `az rest` of <org>/_apis/connectionData keeps the route key every test answers it by."""
    rest = abf.identity_rest_argv()
    assert rest == ["rest", "--method", "get", "--resource", "499b84ac-1321-427f-aa17-267ca6975798", "--url",
                    f"{ORG}/_apis/connectionData?api-version=7.1-preview", "-o", "json"]
    assert abf.route_key_boards(rest) == "GET core/connectionData" and not abf.is_write_key("GET core/connectionData")
    assert json.loads(abf.FakeBoardsAz()(rest, tmp_path)) == abf.load_wit("connection_data")
    sp = [*rest[:-3], rest[-3] + "&connectOptions=0", *rest[-2:]]   # a refinement rides the URL's query string
    assert abf.query_params(sp) == {"api-version": "7.1-preview", "connectOptions": "0"}
    assert json.loads(abf.FakeBoardsAz()(sp, tmp_path)) == abf.load_wit("connection_data_sp")
    other = [w.replace("_apis/connectionData", "_apis/projects") for w in rest]
    assert abf.route_key_boards(other) == "GET rest /contoso/_apis/projects"
    with pytest.raises(AssertionError, match="unexpected az call: GET rest /contoso/_apis/projects"):
        abf.FakeBoardsAz()(other, tmp_path)
    post = [*rest[:2], "post", *rest[3:]]
    with pytest.raises(AssertionError, match="unexpected az write: POST core/connectionData"):
        abf.FakeBoardsAz()(post, tmp_path)
    assert abf.is_identity_rest_read(rest) and not abf.is_identity_rest_read(other) and not abf.is_identity_rest_read(post)


def test_a_capture_supersedes_the_hand_written_file_with_no_code_change(tmp_path, monkeypatch):
    monkeypatch.setattr(abf, "WIT_CAPTURED", tmp_path)
    captured = {"_provenance": "captured 2026-10-13 (org anonymised)", "_command": ["az", "account", "show"],
                "value": {"user": {"name": "person2@example.com", "type": "user"}}}
    (tmp_path / "account_show.json").write_text(json.dumps(captured))
    assert abf.wit_source_of("account_show") == "captured"
    assert abf.load_wit("account_show") == captured["value"]
    assert abf.wit_path("account_show", hand_written=True).parent == abf.WIT
    assert abf.load_wit("account_show", hand_written=True) != captured["value"]


def test_synthetic_processes_resolve_from_their_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(abf, "WIT_SYNTHETIC", tmp_path)
    (tmp_path / "scrum_types.json").write_text(json.dumps({"_provenance": abf.HAND_WRITTEN, "_command": None,
                                                          "value": {"count": 0, "value": []}}))
    assert abf.wit_source_of("scrum_types") == "synthetic"
    assert abf.load_wit("scrum_types") == {"count": 0, "value": []}
    assert abf.wit_source_of("types") == "captured"            # B0: a name that is not synthetic keeps its own file
    assert abf.wit_source_of("account_show") == "hand-written"


# --- Fold B2 (B2-P0): the item, drift and discussion reads --------------------------------------

B2_INVOKE = {"workitems_batch", "updates", "updates_after_comment", "comments", "comments_page2", "comments_hostile",
             "comment_versions"}
B2_NATIVE = {"wiql_by_tag": ["boards", "query"], "wiql_untagged": ["boards", "query"],
             "workitem_show_relations": ["boards", "work-item", "show"]}
GUID_ANON = re.compile(r"^00000000-0000-0000-0000-\d{12}$")


def test_the_invoke_route_filter_keeps_every_invoke_fixture_and_drops_only_native_verbs():
    invoke_names = {n for n in abf.WIT_FIXTURE_NAMES if _command_of(n)[1:3] == ["devops", "invoke"]}
    # B0: the captured identity read is `az rest`, not a `devops invoke` (its hand-written stand-in still is)
    assert set(abf.WIT_FIXTURE_NAMES) - invoke_names == {"account_show", "connection_data", *B2_NATIVE}
    assert _command_of("connection_data")[:2] == ["az", "rest"]
    assert B2_INVOKE <= invoke_names


@pytest.mark.parametrize("name, route", [
    ("workitems_batch", "workitemsbatch"), ("updates", "updates"), ("updates_after_comment", "updates"),
    ("comments", "comments"), ("comments_page2", "comments"), ("comments_hostile", "comments"),
    ("comment_versions", "comment_versions"), ("type_states_bug", "type_states"), ("projects", "projects"),
])
def test_route_name_of_maps_each_fixture_to_its_wit_routes_row(name, route):
    assert abf.route_name_of(name) == route
    assert route in bc.WIT_ROUTES


@pytest.mark.parametrize("name", sorted(B2_INVOKE | set(B2_NATIVE)))
def test_b2_fixture_commands_are_az_argv_lists(name):
    command = _command_of(name)
    assert isinstance(command, list) and command and all(isinstance(w, str) for w in command)
    assert command[0] == "az"
    assert command[command.index("--org") + 1] == ORG
    if name in B2_NATIVE:
        assert command[1:1 + len(B2_NATIVE[name])] == B2_NATIVE[name]
        assert command[-3:] == ["--only-show-errors", "-o", "json"]


@pytest.mark.parametrize("name", ["wiql_by_tag", "wiql_untagged"])
def test_wiql_commands_are_scoped_boards_queries(name):
    command = _command_of(name)
    assert command[command.index("--detect") + 1] == "false"
    assert command[command.index("--project") + 1] == "Claims"
    assert "--repository" not in command
    wiql = command[command.index("--wiql") + 1]
    assert "[System.AssignedTo]" in wiql
    assert ("sdlc-repo:" in wiql) == (name == "wiql_untagged")


def test_show_relations_command_expands_relations():
    command = _command_of("workitem_show_relations")
    assert command[command.index("--id") + 1] == "4521"
    assert command[command.index("--expand") + 1] == "relations"


def _query(command: list) -> dict:
    i = command.index("--query-parameters") + 1
    out = {}
    while i < len(command) and not command[i].startswith("--"):
        k, _, v = command[i].partition("=")
        out[k] = v
        i += 1
    return out


def test_b2_invoke_commands_carry_their_method_body_and_query():
    batch = _command_of("workitems_batch")
    assert batch[batch.index("--http-method") + 1] == "POST"
    assert batch[batch.index("--media-type") + 1] == "application/json"
    assert "--in-file" in batch
    for name in ("comments", "comments_page2", "comments_hostile"):
        q = _query(_command_of(name))
        assert {k: q[k] for k in ("order", "$top", "includeDeleted")} == {"order": "asc", "$top": "200",
                                                                          "includeDeleted": "true"}, name
        assert ("continuationToken" in q) == (name == "comments_page2"), name
    assert _query(_command_of("comments_page2"))["continuationToken"] == abf.load_wit("comments")["continuationToken"]
    assert abf.route_params(_command_of("comments_hostile"))["workItemId"] != abf.route_params(
        _command_of("comments"))["workItemId"]
    assert abf.route_params(_command_of("updates_after_comment"))["id"] != abf.route_params(_command_of("updates"))["id"]
    assert set(abf.route_params(_command_of("comment_versions"))) == {"project", "workItemId", "commentId"}


@pytest.mark.parametrize("call, name", [
    (invoke("wit", "comments", "project=Claims", "workItemId=4521"), "comments"),
    ([*invoke("wit", "comments", "project=Claims", "workItemId=4521")[:-2], "--query-parameters",
      "continuationToken=abc", "-o", "json"], "comments_page2"),
    (invoke("wit", "comments", "project=Claims", "workItemId=4524"), "comments_hostile"),
    (invoke("wit", "updates", "project=Claims", "id=4521"), "updates"),
    (invoke("wit", "updates", "project=Claims", "id=7"), "updates"),
    (invoke("wit", "updates", "project=Claims", "id=4523"), "updates_after_comment"),
    (invoke("wit", "commentsVersions", "project=Claims", "workItemId=4521", "commentId=502"), "comment_versions"),
    (invoke("wit", "workitemsbatch", "project=Claims", method="POST"), "workitems_batch"),
    (["boards", "query", *SCOPE, "--project", "Claims", "--wiql", "SELECT [System.Id] FROM WorkItems WHERE "
      "[System.Tags] CONTAINS 'sdlc:spec:0004'"], "wiql_by_tag"),
    (["boards", "query", *SCOPE, "--project", "Claims", "--wiql", "SELECT [System.Id] FROM WorkItems WHERE NOT "
      "[System.Tags] CONTAINS 'sdlc-repo:claims-api'"], "wiql_untagged"),
    (["boards", "work-item", "show", "--id", "4521", "--expand", "relations", "--org", ORG], "workitem_show_relations"),
])
def test_same_route_fixtures_resolve_by_route_query_and_wiql_refinements(call, name, tmp_path):
    assert json.loads(abf.FakeBoardsAz()(call, tmp_path)) == abf.load_wit(name)


def test_a_re_answered_bare_key_wins_over_the_default_refinements(tmp_path):
    page2 = [*invoke("wit", "comments", "project=Claims", "workItemId=4521")[:-2], "--query-parameters",
             "continuationToken=abc", "-o", "json"]
    mine = abf.FakeBoardsAz({"GET wit/comments": {"mine": 1}, "GET wit/updates": {"mine": 2}, "boards query": []})
    assert json.loads(mine(page2, tmp_path)) == {"mine": 1}
    assert json.loads(mine(invoke("wit", "comments", "project=Claims", "workItemId=4524"), tmp_path)) == {"mine": 1}
    assert json.loads(mine(invoke("wit", "updates", "project=Claims", "id=4523"), tmp_path)) == {"mine": 2}
    assert json.loads(mine(["boards", "query", "--wiql", "x 'sdlc-repo:claims-api'"], tmp_path)) == []
    both = abf.FakeBoardsAz({"GET wit/comments": {"mine": 1}, "GET wit/comments continuationToken=*": {"next": 1}})
    assert json.loads(both(page2, tmp_path)) == {"next": 1}  # a refinement the test answered itself still wins
    later = abf.FakeBoardsAz()
    later.answers["GET wit/updates"] = {"mine": 3}  # tests also re-answer after construction
    assert json.loads(later(invoke("wit", "updates", "project=Claims", "id=4523"), tmp_path)) == {"mine": 3}


def test_the_b2_reads_pass_a_read_only_fake(tmp_path):
    fake = abf.FakeBoardsAz()
    for name in sorted(B2_INVOKE | set(B2_NATIVE)):
        fake([*_command_of(name)[1:], "-o", "json"], tmp_path)
    assert fake.written() == []


# --- Fold B2 response shapes (hand-written (unverified); the B0 capture corrects them) -----------

def _identities(doc):
    """Every dict that looks like an IdentityRef, anywhere in `doc`."""
    if isinstance(doc, dict):
        if "uniqueName" in doc:
            yield doc
        for v in doc.values():
            yield from _identities(v)
    elif isinstance(doc, list):
        for v in doc:
            yield from _identities(v)


@pytest.mark.parametrize("name", ["wiql_by_tag", "wiql_untagged"])
def test_wiql_fixtures_are_what_boards_query_prints(name):
    rows = abf.load_wit(name)
    assert isinstance(rows, list) and rows
    for row in rows:
        assert {"id", "rev", "url", "fields"} <= set(row)
        assert row["fields"]["System.Id"] == row["id"]
        assert {"System.WorkItemType", "System.Title", "System.State"} <= set(row["fields"])
    tags = [r["fields"].get("System.Tags", "") for r in rows]
    if name == "wiql_by_tag":
        assert all("sdlc:spec:0004" in t for t in tags)
    else:
        assert not any("sdlc-repo:" in t for t in tags)
        assert any("System.AssignedTo" in r["fields"] for r in rows) and any("System.AssignedTo" not in r["fields"]
                                                                              for r in rows)


def test_batch_is_a_count_value_list_with_relations_and_an_omitted_id():
    doc = abf.load_wit("workitems_batch")
    assert doc["count"] == len(doc["value"])
    present = [w for w in doc["value"] if w is not None]
    assert None in doc["value"] and present  # errorPolicy=omit: a deleted id comes back as null (unverified)
    for w in present:
        assert {"id", "rev", "fields", "relations", "url"} <= set(w)
        assert w["fields"]["System.Id"] == w["id"]


def test_show_relations_carries_a_pr_link_an_attachment_and_a_parent():
    doc = abf.load_wit("workitem_show_relations")
    assert {"id", "rev", "fields", "relations"} <= set(doc)
    rels = {r["rel"]: r for r in doc["relations"]}
    assert rels["ArtifactLink"]["url"].startswith("vstfs:///Git/PullRequestId/")
    assert rels["ArtifactLink"]["attributes"]["name"] == "Pull Request"
    assert "/_apis/wit/attachments/" in rels["AttachedFile"]["url"]
    assert rels["AttachedFile"]["url"].endswith("?fileName=Spec.txt")
    assert rels["AttachedFile"]["attributes"]["name"] == "Spec.txt"
    assert rels["System.LinkTypes.Hierarchy-Reverse"]["url"].endswith("/_apis/wit/workItems/4410")


@pytest.mark.parametrize("name", ["updates", "updates_after_comment"])
def test_updates_are_count_value_revisions(name):
    doc = abf.load_wit(name)
    assert doc["count"] == len(doc["value"]) and doc["value"]
    revs = [u["rev"] for u in doc["value"]]
    assert revs == sorted(revs)
    for u in doc["value"]:
        assert {"id", "rev", "revisedBy", "revisedDate", "fields"} <= set(u)
        assert all(set(change) <= {"oldValue", "newValue"} for change in u["fields"].values())


BOOKKEEPING = {"System.Rev", "System.AuthorizedDate", "System.RevisedDate", "System.ChangedDate", "System.Watermark",
               "System.CommentCount", "System.ChangedBy", "System.AuthorizedAs", "System.PersonId"}


def test_updates_after_comment_shows_a_history_only_revision():
    last = abf.load_wit("updates_after_comment")["value"][-1]
    assert set(last["fields"]) - BOOKKEEPING == {"System.History"}
    assert "relations" not in last
    assert any(set(u["fields"]).issuperset({"System.State"}) for u in abf.load_wit("updates")["value"])
    assert any("System.History" in u["fields"] for u in abf.load_wit("updates")["value"])


def test_comment_pages_chain_on_the_body_continuation_token():
    first, second = abf.load_wit("comments"), abf.load_wit("comments_page2")
    assert isinstance(first["continuationToken"], str) and first["continuationToken"]
    assert "continuationToken" not in second
    for doc in (first, second):
        assert {"totalCount", "count", "comments"} <= set(doc) and doc["count"] == len(doc["comments"])
    assert first["totalCount"] == first["count"] + second["count"]
    ids = [c["id"] for c in first["comments"] + second["comments"]]
    assert len(ids) == len(set(ids))
    for c in first["comments"] + second["comments"]:
        assert {"id", "workItemId", "version", "text", "format", "createdBy", "createdDate", "modifiedDate",
                "isDeleted"} <= set(c)
    assert any(c["isDeleted"] for c in second["comments"])


def test_comment_versions_are_a_count_value_list():
    doc = abf.load_wit("comment_versions")
    assert doc["count"] == len(doc["value"]) and len(doc["value"]) >= 2
    assert [v["version"] for v in doc["value"]] == sorted(v["version"] for v in doc["value"])
    for v in doc["value"]:
        assert {"version", "text", "isDeleted", "createdBy", "createdDate"} <= set(v)


def test_comments_hostile_carries_every_hostile_shape():
    doc = abf.load_wit("comments_hostile")
    text = "\n".join(c["text"] for c in doc["comments"])
    assert "<script>" in text
    assert re.search(r"<img src=\"[^\"]*/_apis/wit/attachments/", text)
    assert "\x1b" in text
    assert "plan 3f9a1c2b7d04" in text
    assert "@person1@example.com" in text
    assert "continuationToken" not in doc


@pytest.mark.parametrize("name", sorted(B2_INVOKE | set(B2_NATIVE)))
def test_b2_identities_are_anonymised(name):
    for ident in _identities(abf.load_wit(name)):
        assert ident["uniqueName"].endswith("@example.com"), name
        assert GUID_ANON.match(ident["id"]), name


# --- Fold B3 (B3-P0): the write responses, the recent-comments re-list, the service principal ------------------

B3_WRITES = {"workitem_create_response": "POST wit/workItems", "workitem_update_response": "PATCH wit/workItems",
             "comment_add_response": "POST wit/comments"}
B3_READS = {"comments_recent": "GET wit/comments order=desc", "connection_data_sp": "GET core/connectionData connectOptions=0"}
B3_NAMES = {*B3_WRITES, *B3_READS}


def test_each_fixture_is_the_default_answer_of_exactly_one_route_key():
    from collections import Counter
    assert all(n == 1 for n in Counter(abf.DEFAULT_WIT_ANSWERS.values()).values())
    assert B3_NAMES <= set(abf.WIT_FIXTURE_NAMES)
    for name, key in {**B3_WRITES, **B3_READS}.items():
        assert abf.DEFAULT_WIT_ANSWERS[key] == name


@pytest.mark.parametrize("name", sorted(B3_WRITES))
def test_a_read_only_fake_refuses_every_b3_write_fixture_command(name, tmp_path):
    command = _command_of(name)
    assert abf.is_write_key(abf.route_key_boards(command[1:])) and abf.route_key_boards(command[1:]) == B3_WRITES[name]
    with pytest.raises(AssertionError, match=f"^unexpected az write: {B3_WRITES[name]}$"):
        abf.FakeBoardsAz()([*command[1:], "-o", "json"], tmp_path)


@pytest.mark.parametrize("name", sorted(B3_READS))
def test_the_b3_reads_pass_a_read_only_fake(name, tmp_path):
    fake = abf.FakeBoardsAz()
    assert json.loads(fake([*_command_of(name)[1:], "-o", "json"], tmp_path)) == abf.load_wit(name)
    assert fake.written() == []


def _body_flags(command):
    return {f: command[command.index(f) + 1] for f in ("--http-method", "--media-type", "--api-version") if f in command}


def test_b3_commands_are_the_runbook_s_write_probes():
    create = _command_of("workitem_create_response")
    assert _body_flags(create) == {"--http-method": "POST", "--media-type": "application/json-patch+json",
                                   "--api-version": "7.1"}
    assert abf.route_params(create) == {"project": "Claims", "type": "$Task"} and "--in-file" in create
    update = _command_of("workitem_update_response")
    assert _body_flags(update) == {"--http-method": "PATCH", "--media-type": "application/json-patch+json",
                                   "--api-version": "7.1"}
    assert abf.route_params(update) == {"project": "Claims", "id": "4560"} and "--in-file" in update
    post = _command_of("comment_add_response")
    assert _body_flags(post) == {"--http-method": "POST", "--media-type": "application/json", "--api-version": "7.1-preview"}
    assert abf.route_params(post) == {"project": "Claims", "workItemId": "4521"} and "--in-file" in post
    assert _query(post) == {"format": "markdown"}
    recent = _command_of("comments_recent")
    assert _query(recent) == {"order": "desc", "$top": "20"} and abf.route_params(recent)["workItemId"] == "4521"
    assert recent[recent.index("--api-version") + 1] == "7.1-preview" and "--http-method" not in recent
    sp = _command_of("connection_data_sp")
    assert _query(sp) == {"connectOptions": "0"} and sp[sp.index("--api-version") + 1] == "7.1-preview"
    for name in B3_NAMES:
        command = _command_of(name)
        assert command[:3] == ["az", "devops", "invoke"] and command[command.index("--org") + 1] == ORG


@pytest.mark.parametrize("call, name", [
    (invoke("wit", "workItems", "project=Claims", "type=$User Story", method="POST"), "workitem_create_response"),
    (invoke("wit", "workItems", "project=Claims", "id=4521", method="PATCH"), "workitem_update_response"),
    (invoke("wit", "comments", "project=Claims", "workItemId=4521", method="POST"), "comment_add_response"),
    ([*invoke("wit", "comments", "project=Claims", "workItemId=4521")[:-2], "--query-parameters", "order=desc",
      "$top=20", "-o", "json"], "comments_recent"),
    ([*invoke("wit", "comments", "project=Claims", "workItemId=4524")[:-2], "--query-parameters", "order=desc",
      "$top=20", "-o", "json"], "comments_recent"),
    ([*invoke("wit", "comments", "project=Claims", "workItemId=4521")[:-2], "--query-parameters", "order=asc",
      "$top=200", "includeDeleted=true", "-o", "json"], "comments"),
    (invoke("core", "connectionData", ""), "connection_data"),
    ([*invoke("core", "connectionData", "")[:-2], "--query-parameters", "connectOptions=0", "-o", "json"],
     "connection_data_sp"),
])
def test_b3_same_route_fixtures_resolve_by_method_and_query_refinements(call, name, tmp_path):
    assert json.loads(abf.FakeBoardsAz(writes=True)(call, tmp_path)) == abf.load_wit(name)


def test_a_re_answered_bare_comments_key_also_answers_the_recent_re_list(tmp_path):
    recent = [*invoke("wit", "comments", "project=Claims", "workItemId=4521")[:-2], "--query-parameters", "order=desc",
              "$top=20", "-o", "json"]
    assert json.loads(abf.FakeBoardsAz({"GET wit/comments": {"mine": 1}})(recent, tmp_path)) == {"mine": 1}
    mine = abf.FakeBoardsAz({"GET wit/comments order=desc": {"recent": 1}})
    assert json.loads(mine(recent, tmp_path)) == {"recent": 1}
    sp = abf.FakeBoardsAz({"GET core/connectionData": "connection_data_sp"})
    assert json.loads(sp(invoke("core", "connectionData", ""), tmp_path)) == abf.load_wit("connection_data_sp")


@pytest.mark.parametrize("name, route", [
    ("workitem_create_response", "workitem_create"), ("workitem_update_response", "workitem_update"),
    ("comment_add_response", "comments"), ("comments_recent", "comments"), ("connection_data_sp", "connection_data"),
])
def test_route_name_of_maps_each_b3_fixture_to_its_wit_routes_row(name, route):
    assert abf.route_name_of(name) == route and route in bc.WIT_ROUTES


# --- Fold B3 response shapes (hand-written (unverified); the B0 capture corrects them) -------------------------

def test_the_create_and_update_responses_are_one_work_item_a_revision_apart():
    created, updated = abf.load_wit("workitem_create_response"), abf.load_wit("workitem_update_response")
    for doc in (created, updated):
        assert {"id", "rev", "fields", "_links", "url"} <= set(doc)
        assert isinstance(doc["id"], int) and isinstance(doc["rev"], int)
        assert doc["_links"]["self"]["href"].endswith(f"/_apis/wit/workItems/{doc['id']}")
        assert doc["url"].endswith(f"/_apis/wit/workItems/{doc['id']}")
        assert {"System.WorkItemType", "System.State", "System.Title", "System.AreaPath"} <= set(doc["fields"])
        assert not any(ref.startswith("Microsoft.VSTS.Scheduling.") for ref in doc["fields"])
    assert (created["rev"], updated["id"], updated["rev"]) == (1, created["id"], created["rev"] + 1)
    assert created["fields"]["System.WorkItemType"] == "Task" and created["fields"]["System.State"] == "New"
    assert created["fields"]["System.Title"] == 'sdlc probe & "quote" ✓'
    assert updated["fields"]["System.Title"] == "sdlc probe 2"
    assert updated["fields"]["System.ChangedDate"] > created["fields"]["System.ChangedDate"]


def test_the_comment_post_answers_with_an_id_a_version_and_its_author():
    doc = abf.load_wit("comment_add_response")
    assert {"id", "workItemId", "version", "text", "format", "createdBy", "createdDate"} <= set(doc)
    assert (doc["workItemId"], doc["version"], doc["format"], doc["isDeleted"]) == (4521, 1, "markdown", False)
    assert doc["text"] == "probe from sdlc · sprd 000000000000"
    me = abf.load_wit("connection_data")["authenticatedUser"]["id"]
    assert doc["createdBy"]["id"] == me
    assert doc["id"] not in {c["id"] for c in abf.load_wit("comments")["comments"] + abf.load_wit("comments_page2")["comments"]}


def test_the_recent_re_list_is_newest_first_and_starts_with_the_post():
    doc, posted = abf.load_wit("comments_recent"), abf.load_wit("comment_add_response")
    assert {"totalCount", "count", "comments"} <= set(doc) and doc["count"] == len(doc["comments"]) <= 20
    assert "continuationToken" not in doc
    ids = [c["id"] for c in doc["comments"]]
    assert ids == sorted(ids, reverse=True)
    dates = [c["createdDate"] for c in doc["comments"]]
    assert dates == sorted(dates, reverse=True)
    assert not any(c["isDeleted"] for c in doc["comments"])  # includeDeleted is not asked for on the re-list
    first = doc["comments"][0]
    assert (first["id"], first["text"], first["createdBy"]["id"]) == (posted["id"], posted["text"], posted["createdBy"]["id"])
    assert set(ids[1:]) <= {c["id"] for c in abf.load_wit("comments")["comments"]}


def test_the_service_principal_has_no_account_and_a_client_id_for_a_name():
    sp = abf.load_wit("connection_data_sp")["authenticatedUser"]
    assert "Account" not in (sp.get("properties") or {})
    assert GUID_ANON.match(sp["providerDisplayName"])
    assert sp["descriptor"].startswith("Microsoft.VisualStudio.Services.Claims.AadServicePrincipal;")
    person = abf.load_wit("connection_data")["authenticatedUser"]
    assert sp["id"] != person["id"] and "Account" in person["properties"]


@pytest.mark.parametrize("name", sorted(B3_NAMES))
def test_b3_identities_are_anonymised(name):
    for ident in _identities(abf.load_wit(name)):
        assert ident["uniqueName"].endswith("@example.com"), name
        assert GUID_ANON.match(ident["id"]), name


# --- Fold B3 stderr texts ------------------------------------------------------------------------------------

def test_the_error_loader_drops_the_provenance_line_only():
    # B0 (2026-10-15): `stale_rev` and `rule_violation` now resolve to their captures; the hand-written texts are read
    # by asking for them (the captured ones are pinned in test_boards_captured_items.py)
    for name in abf.WIT_ERROR_NAMES:
        raw = abf.wit_error_path(name, hand_written=True).read_text(encoding="utf-8")
        assert raw.splitlines()[0] == "# " + abf.HAND_WRITTEN
        text = abf.load_wit_error(name, hand_written=True)
        assert text == "\n".join(raw.splitlines()[1:]).strip() and text.startswith("ERROR: ")
        assert not text.startswith("#")
    for name in abf.WIT_CAPTURED_WRITE_ERROR_NAMES:
        raw = abf.wit_error_path(name).read_text(encoding="utf-8")
        assert raw.splitlines()[0].startswith("# captured 2026-10-15 ")
        assert abf.load_wit_error(name) == "\n".join(raw.splitlines()[1:]).strip()


@pytest.mark.parametrize("name, needles", [
    ("stale_rev", ("412", "/rev", "Value: 1")),
    ("rule_violation", ("TF401320", "Rule Error for field")),
    ("permission", ("TF401027", "VS403")),
    ("throttled", ("TF400733", "Retry-After")),
])
def test_each_error_text_says_what_its_card_row_says(name, needles):
    text = abf.load_wit_error(name, hand_written=True)   # the hand-written card rows (B0 2026-10-15 captured two)
    assert all(n in text for n in needles), (name, needles)


def test_a_capture_supersedes_a_hand_written_error_with_no_code_change(tmp_path, monkeypatch):
    monkeypatch.setattr(abf, "WIT_CAPTURED_ERRORS", tmp_path)
    (tmp_path / "stale_rev.txt").write_text("ERROR: captured words\n", encoding="utf-8")
    assert abf.load_wit_error("stale_rev") == "ERROR: captured words"
    assert abf.load_wit_error("stale_rev", hand_written=True).startswith("ERROR: Test operation failed")


# --- Fold B5 (B5-P0): one page of the reporting revisions feed (hand-written (unverified)) ------------------------
#
# `GET {project}/_apis/wit/reporting/workItemRevisions` is the watermark feed B5-P2 (`ado_wit_feed.py`) reads: every
# revision changed since a point, in watermark order, a page at a time. The first call names a `startDateTime`; each
# later call names only the `continuationToken` the previous page returned (the REST reference says the two cannot be
# combined), and the page with `isLastBatch: true` hands back the token to store as the next watermark.

FEED = "workitemrevisions"
FEED_KEY = "GET wit/workItemRevisions"


def test_the_feed_page_is_the_default_answer_of_exactly_one_route_key():
    assert [k for k, v in abf.DEFAULT_WIT_ANSWERS.items() if v == FEED] == [FEED_KEY]
    assert FEED in abf.WIT_FIXTURE_NAMES
    assert abf.route_name_of(FEED) == FEED and FEED in bc.WIT_ROUTES
    assert abf.route_key_boards(_command_of(FEED)[1:]) == FEED_KEY and not abf.is_write_key(FEED_KEY)


def test_the_feed_command_is_the_first_page_call_scoped_to_the_project():
    command = _command_of(FEED)
    assert command[:3] == ["az", "devops", "invoke"] and "--http-method" not in command
    assert (command[command.index("--area") + 1], command[command.index("--resource") + 1]) == ("wit", "workItemRevisions")
    assert abf.route_params(command) == {"project": "Claims"}
    assert command[command.index("--api-version") + 1] == "7.1"
    assert command[command.index("--detect") + 1] == "false" and command[command.index("--org") + 1] == ORG
    q = _query(command)
    assert "startDateTime" in q and "continuationToken" not in q, "a first page names a start, never a token"
    assert q["fields"].split(",") == ["System.Id", "System.Rev", "System.WorkItemType", "System.State",
                                      "System.ChangedDate", "System.Tags"]
    assert not {"System.AssignedTo", "System.ChangedBy", "System.CreatedBy"} & set(q["fields"].split(","))


def test_the_feed_page_is_values_a_token_and_a_last_batch_flag():
    doc = abf.load_wit(FEED)
    assert set(doc) == {"values", "nextLink", "continuationToken", "isLastBatch"}
    assert isinstance(doc["values"], list) and doc["values"]
    assert isinstance(doc["continuationToken"], str) and doc["continuationToken"]
    assert doc["isLastBatch"] is True, "one page: the token it returns is the next watermark"
    assert f"continuationToken={doc['continuationToken']}" in doc["nextLink"]
    assert doc["nextLink"].endswith("api-version=7.1") and "/_apis/wit/reporting/workItemRevisions?" in doc["nextLink"]


def test_each_feed_value_is_one_revision_after_the_start_in_watermark_order():
    command = _command_of(FEED)
    start, wanted = _query(command)["startDateTime"], set(_query(command)["fields"].split(","))
    values = abf.load_wit(FEED)["values"]
    for v in values:
        assert set(v) == {"id", "rev", "fields"}
        assert isinstance(v["id"], int) and isinstance(v["rev"], int)
        assert (v["fields"]["System.Id"], v["fields"]["System.Rev"]) == (v["id"], v["rev"])
        assert set(v["fields"]) <= wanted, "only the fields asked for"
        assert not any(isinstance(x, dict) for x in v["fields"].values()), "no identity reference in the feed"
        assert v["fields"]["System.ChangedDate"] > start
    changed = [v["fields"]["System.ChangedDate"] for v in values]
    assert changed == sorted(changed)
    pairs = [(v["id"], v["rev"]) for v in values]
    assert len(pairs) == len(set(pairs))
    ids = [v["id"] for v in values]
    assert len(set(ids)) < len(ids), "every revision is listed, not only the latest of each item"
    for wid in set(ids):
        revs = [v["rev"] for v in values if v["id"] == wid]
        assert revs == sorted(revs), wid


def test_the_feed_mixes_mirrored_items_with_ones_nobody_mapped():
    values = abf.load_wit(FEED)["values"]
    tags = [v["fields"].get("System.Tags") or "" for v in values]
    assert any("sdlc:spec:0004" in t for t in tags)
    assert any("sdlc-repo:" not in t for t in tags), "an item the board originated is in the feed too"
    assert any("System.Tags" not in v["fields"] for v in values), "an untagged item carries no System.Tags"
    latest_4521 = max((v for v in values if v["id"] == 4521), key=lambda v: v["rev"])
    batch = next(w for w in abf.load_wit("workitems_batch")["value"] if w and w["id"] == 4521)
    assert latest_4521["rev"] == batch["rev"] and latest_4521["fields"]["System.State"] == batch["fields"]["System.State"]


@pytest.mark.parametrize("query", [
    ["startDateTime=2026-10-10T00:00:00Z"],
    ["continuationToken=d2F0ZXJtYXJrLTQ3"],
    [],
])
def test_every_feed_page_call_routes_to_the_page_through_a_read_only_fake(query, tmp_path):
    call = invoke("wit", "workItemRevisions", "project=Claims")[:-2]
    if query:
        call += ["--query-parameters", *query]
    fake = abf.FakeBoardsAz()
    assert json.loads(fake([*call, "-o", "json"], tmp_path)) == abf.load_wit(FEED)
    assert fake.written() == []


def test_a_test_may_answer_the_next_page_itself(tmp_path):
    page2 = {"values": [], "nextLink": "x", "continuationToken": "next", "isLastBatch": True}
    fake = abf.FakeBoardsAz({f"{FEED_KEY} continuationToken=*": page2})
    first = invoke("wit", "workItemRevisions", "project=Claims")[:-2] + ["--query-parameters",
                                                                        "startDateTime=2026-10-10T00:00:00Z"]
    second = invoke("wit", "workItemRevisions", "project=Claims")[:-2] + ["--query-parameters",
                                                                         "continuationToken=d2F0ZXJtYXJrLTQ3"]
    assert json.loads(fake([*first, "-o", "json"], tmp_path)) == abf.load_wit(FEED)
    assert json.loads(fake([*second, "-o", "json"], tmp_path)) == page2


def test_the_feed_page_carries_no_identity_and_no_preview_version():
    text = abf.wit_path(FEED).read_text(encoding="utf-8")
    assert "uniqueName" not in text and "displayName" not in text and "@" not in text
    assert not re.search(r"-preview", text)
    for guid in re.findall(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", text):
        assert GUID_ANON.match(guid), guid
