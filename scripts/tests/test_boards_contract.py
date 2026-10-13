"""The Boards-mirror contract module is pure data and agrees with what already exists (B1-P0).

`scripts/boards_contract.py` owns every enum, regex, path and the `WIT_ROUTES` table the later
packages import. These pins keep it importable from anywhere (only `re` / `typing`), keep its
`DISCIPLINE_AGENTS` literal equal to the one `audit_artifacts.py` enforces, and keep every
`devops invoke` location unverified until the B0 capture corrects it by hand.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401

import ast
import re
from pathlib import Path

import pytest

import ado_transport
import audit_artifacts
import boards_contract as bc

MODULE = Path(bc.__file__)

DISCOVERY_ROUTES = {"projects", "type_categories", "types", "type_states", "type_fields", "fields",
                    "backlog_config", "classification_nodes", "team_iterations", "relation_types"}
ITEM_ROUTES = {"workitem_create", "workitem_update", "comments", "comment_versions", "workitemsbatch",
               "updates", "connection_data"}
ROW_KEYS = {"area", "resource", "route", "method", "api_version", "verified"}


def test_imports_only_re_and_typing():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"re", "typing"}, imported


def test_module_calls_no_io():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"open", "print", "input", "exec", "eval", "__import__"}, called


def test_discipline_agents_equal_the_audit_literal():
    assert isinstance(bc.DISCIPLINE_AGENTS, frozenset)
    assert bc.DISCIPLINE_AGENTS == audit_artifacts.DISCIPLINE_AGENTS


def test_wit_routes_keys_are_the_discovery_and_item_routes():
    assert set(bc.WIT_ROUTES) == DISCOVERY_ROUTES | ITEM_ROUTES


@pytest.mark.parametrize("name", sorted(DISCOVERY_ROUTES | ITEM_ROUTES))
def test_every_wit_route_row_is_complete_and_unverified(name):
    row = bc.WIT_ROUTES[name]
    assert set(row) == ROW_KEYS, f"{name}: {sorted(row)}"
    assert row["verified"] is False, f"{name}: only the B0 capture flips verified"
    assert row["area"] in {"core", "wit", "work"}
    assert isinstance(row["resource"], str) and row["resource"]
    assert isinstance(row["route"], tuple) and all(isinstance(p, str) and p for p in row["route"])
    assert row["method"] in {"GET", "POST", "PATCH"}
    assert row["api_version"] in {ado_transport.API_VERSION, ado_transport.PREVIEW_API_VERSION}
    assert not re.search(r"-preview\.\d", row["api_version"])


def test_write_routes_are_writes_and_the_batch_read_is_a_read_post():
    for name, method in (("workitem_create", "POST"), ("workitem_update", "PATCH")):
        row = bc.WIT_ROUTES[name]
        assert row["method"] == method and method in bc.WRITE_METHODS
        assert (row["area"], row["resource"]) not in bc.READ_POSTS
    batch = bc.WIT_ROUTES["workitemsbatch"]
    assert batch["method"] == "POST" and (batch["area"], batch["resource"]) in bc.READ_POSTS
    reads = DISCOVERY_ROUTES | {"comments", "comment_versions", "updates", "connection_data"}
    assert {bc.WIT_ROUTES[n]["method"] for n in reads} == {"GET"}


def test_preview_only_where_the_api_has_no_ga_version():
    preview = {n for n, r in bc.WIT_ROUTES.items() if r["api_version"] == ado_transport.PREVIEW_API_VERSION}
    assert preview == {"comments", "comment_versions", "connection_data"}


def test_project_is_a_route_parameter_never_a_flag():
    assert bc.WIT_ROUTES["projects"]["route"] == ("projectId",)
    assert bc.WIT_ROUTES["connection_data"]["route"] == ()
    for name, row in bc.WIT_ROUTES.items():
        if name not in {"projects", "connection_data"}:
            assert row["route"][0] == "project", name
    assert {"type"} <= set(bc.WIT_ROUTES["type_states"]["route"]) and {"type"} <= set(bc.WIT_ROUTES["type_fields"]["route"])
    assert {"team"} <= set(bc.WIT_ROUTES["backlog_config"]["route"]) and {"team"} <= set(bc.WIT_ROUTES["team_iterations"]["route"])


@pytest.mark.parametrize("handle", ["@MCKRUZ", "@mckruz", "@kim-lee", "@a1", "@Z"])
def test_handle_re_accepts_roster_handles(handle):
    assert bc.HANDLE_RE.fullmatch(handle)


@pytest.mark.parametrize("handle", ["MCKRUZ", "@", "@-kim", "@kim lee", "@kim_lee", "@kim.lee", "@MCKRUZ\n", ""])
def test_handle_re_refuses_anything_else(handle):
    assert not bc.HANDLE_RE.fullmatch(handle)


def test_hash_ref_email_and_guid_patterns():
    assert bc.HASH_RE.match("3f9a1c2b7d0e")
    for bad in ("3F9A1C2B7D0E", "3f9a1c2b7d0", "3f9a1c2b7d0ea", "3f9a1c2b7d0g"):
        assert not bc.HASH_RE.match(bad), bad
    for ref in ("sdlc:spec:0004", "sdlc:fr:001", "sdlc:domain:claims-intake", "sdlc:outcome:Dimension-1"):
        assert bc.REF_RE.match(ref), ref
    for bad in ("sdlc:Spec:0004", "sdlc-repo:x", "sdlc:spec:", "sdlc:spec:a b", "fr:001"):
        assert not bc.REF_RE.match(bad), bad
    assert bc.EMAIL_RE.search("assigned to person1@example.com today")
    assert not bc.EMAIL_RE.search("owner @MCKRUZ")
    assert bc.GUID_RE.search("id 00000000-0000-0000-0000-000000000001 seen")
    assert not bc.GUID_RE.search("sprd 3f9a1c2b7d0e")


def test_kinds_and_tree_order():
    assert len(bc.KINDS) == 14 and len(set(bc.KINDS)) == 14
    assert bc.TREE_ORDER == ("outcome", "domain", "requirement", "epic", "feature", "spec")
    assert set(bc.TREE_ORDER) <= set(bc.KINDS)
    assert bc.FIT_MODES == ("item", "area", "tag")
    assert bc.FULFILS_REL == "System.LinkTypes.Related"
    assert bc.TRAILER_TOKEN == bc.HISTORY_TOKEN == "sprd"


@pytest.mark.parametrize("name, case", [("DRIFT_CLASSES", r"^[A-Z][A-Z_]*$"), ("LEDGER_EVENTS", r"^[a-z][a-z_]*$"),
                                        ("COMMENT_REFUSALS", r"^[a-z][a-z_]*$")])
def test_closed_vocabularies_are_unique_and_snake_case(name, case):
    values = getattr(bc, name)
    assert isinstance(values, tuple) and len(values) == len(set(values)) and values
    assert all(re.match(case, v) for v in values), values


def test_vocabulary_members_the_later_folds_name():
    assert {"IN_SYNC", "ADO_OWNED_CHANGE", "SDLC_OWNED_DRIFT", "CONFLICT", "NEVER_PUSHED"} <= set(bc.DRIFT_CLASSES)
    assert {"discovered", "posture", "planned", "applied", "refused", "commented"} <= set(bc.LEDGER_EVENTS)
    assert {"ai_actor", "email_in_text", "posture"} <= set(bc.COMMENT_REFUSALS)


def test_ownership_letters():
    assert set(bc.OWNERSHIP.values()) <= {"S", "A", "C"}
    assert bc.OWNERSHIP["System.State"] == "S"
    assert bc.OWNERSHIP["System.AssignedTo"] == "A"
    assert bc.OWNERSHIP["System.IterationPath"] == "A"
    assert bc.OWNERSHIP["System.AreaPath"] == "C"
    assert all(re.match(r"^(System|Microsoft\.VSTS)\.", ref) for ref in bc.OWNERSHIP), "process-specific fields live in config"


def test_methods_and_tag_prefixes():
    assert bc.WRITE_METHODS == frozenset({"POST", "PATCH", "PUT", "DELETE"})
    assert bc.READ_POSTS == frozenset({("wit", "wiql"), ("wit", "workitemsbatch")})
    assert bc.PLUGIN_TAG_PREFIXES[0] == "sdlc:"
    assert all(p.endswith(":") for p in bc.PLUGIN_TAG_PREFIXES)
    assert len(set(bc.PLUGIN_TAG_PREFIXES)) == len(bc.PLUGIN_TAG_PREFIXES)


def test_paths_are_repo_relative_under_dot_sdlc():
    paths = {n: getattr(bc, n) for n in ("CONFIG_FILE", "SCHEMA_FILE", "LOCAL_DIR", "HOOK_STATUS", "LEDGER",
                                         "DISCUSSION_DIR", "ME_FILE")}
    for name, p in paths.items():
        assert p.startswith(".sdlc/") and "\\" not in p and ".." not in p, name
    for name in ("HOOK_STATUS", "DISCUSSION_DIR", "ME_FILE"):
        assert paths[name].startswith(bc.LOCAL_DIR + "/"), name
    assert bc.CONFIG_FILE == ".sdlc/ado.yaml" and bc.SCHEMA_FILE == ".sdlc/ado/schema.json"
    assert bc.LEDGER == ".sdlc/metrics/ado-sync-log.jsonl"
