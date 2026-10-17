"""The Boards-mirror contract module is pure data and agrees with what already exists (B1-P0).

`scripts/boards_contract.py` owns every enum, regex, path and the `WIT_ROUTES` table the later
packages import. These pins keep it importable from anywhere (only `re` / `typing`), keep its
`DISCIPLINE_AGENTS` literal equal to the one `audit_artifacts.py` enforces, and keep every
`devops invoke` location unverified until the B0 capture corrects it by hand.

The first capture (2026-10-14) verified the discovery rows and the reporting feed, corrected the per-type
states and fields locations, and moved the identity read to `REST_ROUTES` (`az rest`). The section at the end
checks every row against the capture's own locations list, so a row a later capture has not reached is still
held to what Azure DevOps says exists.
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
FEED_ROUTES = {"workitemrevisions"}  # Fold B5 (B5-P0): the reporting revisions feed B5-P2's watermark pull reads


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
    assert set(bc.WIT_ROUTES) == DISCOVERY_ROUTES | ITEM_ROUTES | FEED_ROUTES


# B0 (2026-10-14): the rows the capture read (or, for the reporting feed, found released in its locations list).
# Exactly these are verified; every item, write, discussion and identity row is still not — the capture did not reach
# them, and the identity read is no `devops invoke` location at all (REST_ROUTES).
VERIFIED_BY_B0 = DISCOVERY_ROUTES | FEED_ROUTES | {"workitem_create"}   # the create POST was reached by probe 17 (2026-10-14)
# B0 write fixes (2026-10-15, the first live apply and its probes): the batch read, the history read, the comments POST
# and GET, and the update — reached through `az rest` (REST_ROUTES["workitem_update"]), since `devops invoke` cannot
# PATCH a work item. `comment_versions` was not reached; `connection_data` is no invoke location at all.
VERIFIED_BY_B0 |= {"workitemsbatch", "updates", "comments", "workitem_update"}
UNVERIFIED_AFTER_B0 = {"comment_versions", "connection_data"}


def test_exactly_the_rows_no_capture_reached_are_unverified():
    assert {n for n, row in bc.WIT_ROUTES.items() if not row["verified"]} == UNVERIFIED_AFTER_B0
    assert set(bc.WIT_ROUTES) == VERIFIED_BY_B0 | UNVERIFIED_AFTER_B0


@pytest.mark.parametrize("name", sorted(DISCOVERY_ROUTES | ITEM_ROUTES))
def test_every_wit_route_row_is_complete_and_verified_only_where_the_capture_reached(name):
    row = bc.WIT_ROUTES[name]
    assert set(row) == ROW_KEYS, f"{name}: {sorted(row)}"
    assert row["verified"] is (name in VERIFIED_BY_B0), f"{name}: only the B0 capture flips verified"
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
    assert len(bc.KINDS) == 15 and len(set(bc.KINDS)) == 15
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


# --- Fold B5 (B5-P0): the reporting revisions feed and the `nfr` kind ---------------------------------------------

def test_the_feed_route_row_is_complete_and_verified_by_the_capture():
    row = bc.WIT_ROUTES["workitemrevisions"]
    assert set(row) == ROW_KEYS
    assert row == {"area": "wit", "resource": "workItemRevisions", "route": ("project",), "method": "GET",
                   "api_version": ado_transport.API_VERSION, "verified": True}   # B0: released 7.1 in the locations
    assert row["method"] not in bc.WRITE_METHODS and (row["area"], row["resource"]) not in bc.READ_POSTS
    assert not re.search(r"-preview", row["api_version"]), "the reporting revisions feed has a GA version"


def test_the_feed_route_is_the_only_route_fold_b5_adds():
    assert set(bc.WIT_ROUTES) - (DISCOVERY_ROUTES | ITEM_ROUTES) == FEED_ROUTES
    assert list(bc.WIT_ROUTES)[-1] == "workitemrevisions"


def test_nfr_is_the_last_kind_and_never_a_parent():
    assert bc.KINDS[-1] == "nfr" and bc.KINDS.count("nfr") == 1
    assert bc.KINDS[:-1] == ("outcome", "domain", "epic", "feature", "spec", "spike", "sprint", "decision", "finding",
                             "lifecycle", "requirement", "rule", "question", "measurement")
    assert "nfr" not in bc.TREE_ORDER


# --- B0 (2026-10-14): the capture's corrections, and every row checked against its locations list ------------------

from tests.ado_boards_fixtures import load_wit, wit_source_of  # noqa: E402

LOCATIONS = load_wit("invoke_locations")  # the wit/work/core subset of `az devops invoke`'s own locations list
ORG_LEVEL = {"relation_types"}  # `_apis/wit/workItemRelationTypes`: the `project` it is sent is not part of the route


def _locations(area: str, resource: str) -> list[dict]:
    return [loc for loc in LOCATIONS if loc["area"] == area and loc["resourceName"].lower() == resource.lower()]


def _version(text) -> float:
    return float(str(text).removesuffix("-preview"))


def test_the_locations_list_is_the_capture():
    assert wit_source_of("invoke_locations") == "captured"
    assert {loc["area"] for loc in LOCATIONS} == {"wit", "work", "core"} and len(LOCATIONS) == 106


def test_the_three_corrected_rows_name_the_locations_the_capture_found():
    assert (bc.WIT_ROUTES["type_states"]["resource"], bc.WIT_ROUTES["type_fields"]["resource"]) == (
        "workItemTypeStates", "workItemTypesField")
    (states,) = _locations("wit", "workItemTypeStates")
    assert states["routeTemplate"] == "{project}/_apis/{area}/workitemtypes/{type}/states"
    (fields,) = _locations("wit", "workItemTypesField")
    assert fields["routeTemplate"] == "{project}/_apis/{area}/workitemtypes/{type}/fields/{field}"
    assert _locations("wit", "states") == []                       # what the hand-written row named does not exist
    assert all("{type}" not in loc["routeTemplate"] for loc in _locations("wit", "fields"))  # `fields` has no type
    assert _locations("core", "connectionData") == []              # nor is the identity read a core location
    assert bc.WIT_ROUTES["connection_data"]["verified"] is False


@pytest.mark.parametrize("name", sorted(set(bc.WIT_ROUTES) - {"connection_data"}))
def test_every_invoke_row_has_a_location_its_version_and_route_fit(name):
    """GA rows are released at 7.1, preview rows are not released at all (`0.0`) yet serve 7.1, and every route
    parameter a row sends is one its location's template names — verified rows and the not-yet-captured ones alike."""
    row = bc.WIT_ROUTES[name]
    fitting = [loc for loc in _locations(row["area"], row["resource"])
               if _version(loc["minVersion"]) <= _version(row["api_version"]) <= _version(loc["maxVersion"])]
    assert fitting, f"{name}: no {row['area']}/{row['resource']} location serves {row['api_version']}"
    released = {loc["releasedVersion"] for loc in fitting}
    if row["api_version"] == ado_transport.PREVIEW_API_VERSION:
        assert released == {"0.0"}, f"{name}: a preview row whose location has a released version {released}"
    else:
        assert ado_transport.API_VERSION in released, f"{name}: a GA row whose location is released at {released}"
    sent = set(row["route"]) - ({"project"} if name in ORG_LEVEL else set())
    assert any(all(re.search(r"\{[*$]?" + re.escape(p) + r"\}", loc["routeTemplate"]) for p in sent)
               for loc in fitting), f"{name}: {sorted(sent)} not all in {[loc['routeTemplate'] for loc in fitting]}"


def test_the_org_level_row_really_has_no_project_in_its_template():
    (loc,) = _locations("wit", "workItemRelationTypes")
    assert "{project}" not in loc["routeTemplate"] and loc["routeTemplate"].startswith("_apis/")


def test_rest_routes_are_the_identity_read_and_the_update_and_agree_with_the_transport():
    """B0 (2026-10-14) the identity read; B0 write fixes (2026-10-15) the update, which `devops invoke` cannot send."""
    assert set(bc.REST_ROUTES) == {"connection_data", "workitem_update"} and set(bc.REST_ROUTES) <= set(bc.WIT_ROUTES)
    row = bc.REST_ROUTES["connection_data"]
    assert row == {"path": "_apis/connectionData", "method": "GET", "api_version": ado_transport.PREVIEW_API_VERSION,
                   "verified": True}
    update = bc.REST_ROUTES["workitem_update"]
    assert update == {"path": "{project}/_apis/wit/workitems/{id}", "method": "PATCH",
                      "api_version": ado_transport.API_VERSION, "verified": True}
    assert {r["path"] for r in bc.REST_ROUTES.values() if r["method"] == "GET"} == ado_transport.REST_READS
    assert {r["path"] for r in bc.REST_ROUTES.values() if r["method"] == "PATCH"} == ado_transport.REST_WRITES
    assert {r["method"] for r in bc.REST_ROUTES.values()} == {"GET", "PATCH"}
    assert update["method"] == bc.WIT_ROUTES["workitem_update"]["method"]   # the same write, by another transport
    assert re.findall(r"\{([a-z]+)\}", update["path"]) == list(bc.WIT_ROUTES["workitem_update"]["route"])
    assert bc.ADO_RESOURCE_ID == ado_transport.ADO_RESOURCE_ID == "499b84ac-1321-427f-aa17-267ca6975798"
    assert not any(re.search(r"-preview\.\d", r["api_version"]) for r in bc.REST_ROUTES.values())


def test_page_tokens_are_read_body_first_then_the_extensions_own_key():
    assert bc.PAGE_TOKEN_KEYS == ("continuationToken", "continuation_token")
