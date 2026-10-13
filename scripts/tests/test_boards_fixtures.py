"""The Boards test harness itself: the router, the read-only pin and the no-az seam (B1-P0).

`tests/ado_boards_fixtures.py` is what every `test_boards_*.py` stands on, so its own guarantees
are pinned here: `boards_env` (autouse) forbids a real `az` at the transport seam, `az` swaps in
a `FakeBoardsAz` that answers from the `wit/` fixtures, an unknown route is an AssertionError,
and with `writes=False` a write is one too — while the two read-only POSTs still pass.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401

import json
from pathlib import Path

import pytest

import ado_map
import ado_transport
import boards_contract as bc
import code_host
from tests import ado_boards_fixtures as abf
from tests.ado_fixtures import ADO_REMOTE

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
    fake = abf.FakeBoardsAz()
    for wit_type, name in (("User Story", "type_states_user_story"), ("Bug", "type_states_bug"), ("Issue", "type_states_issue")):
        got = fake(invoke("wit", "states", "project=Claims", f"type={wit_type}"), tmp_path)
        assert json.loads(got) == abf.load_wit(name)
    assert json.loads(fake(invoke("wit", "fields", "project=Claims", "type=Issue"), tmp_path)) == abf.load_wit("type_fields_issue")
    assert json.loads(fake(invoke("wit", "fields", "project=Claims"), tmp_path)) == abf.load_wit("fields")
    with pytest.raises(AssertionError, match="unexpected az call: GET wit/states"):
        fake(invoke("wit", "states", "project=Claims", "type=Epic"), tmp_path)


def test_default_answers_cover_every_hand_written_fixture_and_only_those():
    assert set(abf.DEFAULT_WIT_ANSWERS.values()) == set(abf.WIT_FIXTURE_NAMES)
    for name in abf.WIT_FIXTURE_NAMES:
        assert abf.wit_path(name).is_file(), name


@pytest.mark.parametrize("name", abf.WIT_FIXTURE_NAMES)
def test_each_fixture_command_routes_to_its_own_default_answer(name, tmp_path):
    """A fixture's `_command` is the call it answers; the router must send that call back to it."""
    command = json.loads(abf.wit_path(name).read_text(encoding="utf-8"))["_command"]
    assert command[0] == "az"
    out = abf.FakeBoardsAz()([*command[1:], "-o", "json"], tmp_path)
    assert json.loads(out) == abf.load_wit(name)


@pytest.mark.parametrize("name", [n for n in abf.WIT_FIXTURE_NAMES if n != "account_show"])
def test_each_invoke_fixture_command_agrees_with_wit_routes(name):
    command = json.loads(abf.wit_path(name).read_text(encoding="utf-8"))["_command"]
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


def test_every_name_resolves_to_the_hand_written_file_today():
    assert {abf.wit_source_of(n) for n in abf.WIT_FIXTURE_NAMES} == {"hand-written"}


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
    assert abf.wit_source_of("types") == "hand-written"
