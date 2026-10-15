"""The pure work-item map: board rows in, JSON patches and WIQL out (B2-P1).

`scripts/ado_wit_map.py` is the half of the Boards mirror that touches no process: it reads a work item
into the small document the sync model compares (`remote_item`), builds the JSON patches a create and an
update would send (`build_create_patch`, `build_update_patch`), merges the two shared fields without
overwriting what a person typed (`merge_tags`, `merge_description`), writes the two WIQL queries the mirror
runs (`wiql_ref_lookup`, `wiql_untagged`), sorts a failed write into a closed enum (`classify_write_error`)
and builds the repository link a work item points back at (`file_hyperlink`). Every input is a fixture
(`wit/workitems_batch.json`, hand-written and unverified until the B0 capture) or a literal built here.

No e-mail address is committed in this file (house rule 10): the few the cases need are assembled from parts.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import HAND_WRITTEN_PROCESS

import ast
import copy
import inspect
import json
import re
from pathlib import Path

import pytest

import ado_schema_map as asm
import ado_sync_model as sm
import ado_wit_map as wm
import boards_contract as bc
from ado_map import AdoImportError
from code_host_remote import RemoteInfo, parse_remote
from tests.ado_boards_fixtures import load_wit, wit_path
from tests.ado_fixtures import ADO_REMOTE

# B0 (2026-10-15): the second capture shadowed the item, write and comment fixtures (`WIT_CAPTURED_ITEMS`); this module's
# scenarios pin the hand-written ones' ids and texts, so it reads those (`BOARDS_ITEMS`, tests/ado_boards_fixtures.py).
# The captured answers are exercised in test_boards_captured_items.py.
BOARDS_ITEMS = HAND_WRITTEN_PROCESS

MODULE = Path(wm.__file__)
ALLOWED_IMPORTS = {"re", "typing", "urllib", "ado_map", "ado_schema_map", "ado_sync_model", "boards_contract",
                   "code_host_remote"}
BEGIN, END = "<!-- sdlc:begin -->", "<!-- sdlc:end -->"
REMOTE = parse_remote(ADO_REMOTE)
SHA = "0123456789abcdef0123456789abcdef01234567"
KIM = "kim" + "@corp.com"  # assembled so no address literal is committed
KIM_UPPER = "KIM" + "@Corp.COM"
FORBIDDEN_NEEDLES = ("suppress" + "Notifications", "bypass" + "Rules")


def rows() -> list:
    return copy.deepcopy(load_wit("workitems_batch")["value"])


def spec_row() -> dict:
    return rows()[0]  # 4521: a User Story, spec 0004, in-flight, assigned, child of 4410


def feature_row() -> dict:
    return rows()[1]  # 4410: a Feature


def block_of(html: str) -> str:
    return html[html.index(BEGIN):html.index(END) + len(END)]


def projection(kind="spec", **fields) -> dict:
    """The projection that matches the 4521 fixture row field for field (so the baseline patch is empty)."""
    body = {"System.Title": "0004 · duplicate claim 409", "System.State": "Active",
            "System.Description": block_of(spec_row()["fields"]["System.Description"]),
            "Custom.RiskTier": "MEDIUM", **fields}
    return {"ref": f"sdlc:{kind}:0004", "kind": kind, "id": "0004", "title": "duplicate claim 409",
            "status": "in-flight", "fields": body,
            "tags": {"sdlc:spec:0004", "sdlc:status:in-flight", "sdlc-repo:claims-api", "risk:MEDIUM"},
            "parent_ref": "sdlc:feature:03", "parent_note": None, "related_refs": [],
            "source_path": "specs/0004-duplicate-claim-409.md", "source_sha": SHA}


def schema() -> dict:
    return asm.build_schema(
        discovered_at="2026-10-13T00:00:00Z", project={"name": "Claims"}, team=None,
        categories=asm.map_categories(load_wit("type_categories")), types=asm.map_types(load_wit("types")),
        states_by_type={}, fields_by_type={}, fields=asm.map_fields(load_wit("fields")),
        backlog=asm.map_backlog_config(load_wit("backlog_config")),
        nodes=asm.map_nodes(load_wit("classification_nodes")),
        team_iterations=asm.map_team_iterations(load_wit("team_iterations")),
        link_types=asm.map_link_types(load_wit("relation_types")), commands=["devops invoke wit workItemTypes"])


def patch_for(row: dict, proj: dict) -> list[dict]:
    return wm.build_update_patch(wm.remote_item(row), proj)


def apply_to(row: dict, patch: list[dict]) -> dict:
    """What the board would hold after the patch: field ops only (the test op is a precondition)."""
    out = copy.deepcopy(row)
    for op in patch:
        if op["op"] == "test":
            assert op["value"] == row["rev"]
        elif op["path"].startswith("/fields/"):
            out["fields"][op["path"][len("/fields/"):]] = op["value"]
    out["rev"] = row["rev"] + 1
    return out


# --- purity -------------------------------------------------------------------------------------------------

def test_imports_no_io_module():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative imports"
            imported.add((node.module or "").split(".")[0])
    assert imported <= ALLOWED_IMPORTS, imported - ALLOWED_IMPORTS
    assert {"ado_map", "boards_contract", "code_host_remote"} <= imported
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"open", "print", "input", "exec", "eval", "__import__"}, called


def test_source_names_neither_notification_bypass_nor_rule_bypass():
    source = inspect.getsource(wm)
    for needle in FORBIDDEN_NEEDLES:
        assert needle not in source
    assert not re.search(r"-preview\.\d", source)  # an api-version is the transport's, never spelled here


# --- remote_item: a board row in, the document the model compares out ----------------------------------------

def test_remote_item_reads_the_fixture_row():
    item = wm.remote_item(spec_row())
    assert (item["id"], item["rev"], item["type"], item["state"]) == (4521, 7, "User Story", "Active")
    assert item["iteration"] == "Claims\\Sprint 7" and item["area"] == "Claims\\SDLC\\Intake"
    assert item["title"] == "0004 · duplicate claim 409"
    assert item["tags"] == {"risk:MEDIUM", "sdlc-repo:claims-api", "sdlc:spec:0004", "sdlc:status:in-flight"}
    assert item["assigned_to_handle"] is None  # no roster: an assignee is never guessed from a name


def test_remote_item_maps_the_assignee_through_the_roster_only():
    row = spec_row()
    upn = row["fields"]["System.AssignedTo"]["uniqueName"]
    assert wm.remote_item(row, {upn.lower(): "@MCKRUZ"})["assigned_to_handle"] == "@MCKRUZ"
    row["fields"]["System.AssignedTo"]["uniqueName"] = upn.upper()  # the board's casing is not the roster's
    assert wm.remote_item(row, {upn.lower(): "@MCKRUZ"})["assigned_to_handle"] == "@MCKRUZ"
    assert wm.remote_item(row, {KIM: "@kim"})["assigned_to_handle"] is None  # not on the roster
    row["fields"]["System.AssignedTo"] = f"Kim Lee <{KIM_UPPER}>"  # the native `az boards` string form
    item = wm.remote_item(row, {KIM: "@kim"})
    assert item["assigned_to_handle"] == "@kim"
    assert "System.AssignedTo" not in item["fields"]  # a string-typed identity is withheld like a dict-typed one
    assert not bc.EMAIL_RE.search(json.dumps(item, default=sorted))
    del row["fields"]["System.AssignedTo"]
    assert wm.remote_item(row, {KIM: "@kim"})["assigned_to_handle"] is None


def test_remote_item_carries_no_identity_no_guid_and_no_effort():
    item = wm.remote_item(spec_row())
    text = json.dumps(item, default=sorted)
    assert not bc.EMAIL_RE.search(text) and not bc.GUID_RE.search(text)
    fields = item["fields"]
    assert not {"System.AssignedTo", "System.CreatedBy", "System.ChangedBy", "System.History"} & set(fields)
    assert not any(ref.startswith("Microsoft.VSTS.Scheduling.") for ref in fields)  # an effort value is never read
    assert fields["Custom.RiskTier"] == "MEDIUM" and fields["Microsoft.VSTS.Common.Priority"] == 2
    assert BEGIN in fields["System.Description"]


def test_remote_item_relations_are_ids_and_names_not_urls():
    relations = wm.remote_item(spec_row())["relations"]
    assert {"rel": "System.LinkTypes.Hierarchy-Reverse", "target": 4410, "name": "Parent"} in relations
    assert {"rel": "AttachedFile", "target": None, "name": "Spec.txt"} in relations
    assert {"rel": "ArtifactLink", "target": None, "name": "Pull Request"} in relations
    assert not any("url" in r for r in relations)
    link = {"rel": "Hyperlink", "url": "https://dev.azure.com/contoso/Claims/_git/claims-api?version=GC" + SHA,
            "attributes": {"comment": "source file"}}
    row = spec_row()
    row["relations"].append(link)
    assert wm.remote_item(row)["relations"][-1] == {"rel": "Hyperlink", "target": None, "name": None, "url": link["url"]}


def test_remote_item_absent_optional_keys_read_as_empty():
    row = feature_row()
    row["fields"].pop("System.Tags")
    row.pop("relations")
    item = wm.remote_item(row)
    assert item["tags"] == set() and item["relations"] == [] and item["assigned_to_handle"] is None


@pytest.mark.parametrize("key", ["id", "rev", "fields"])
def test_remote_item_missing_top_level_key_raises(key):
    row = spec_row()
    del row[key]
    with pytest.raises(AdoImportError, match=rf"missing work item\.{key}"):
        wm.remote_item(row)


@pytest.mark.parametrize("key", ["System.WorkItemType", "System.State", "System.Title", "System.IterationPath",
                                 "System.AreaPath"])
def test_remote_item_missing_field_raises(key):
    row = spec_row()
    del row["fields"][key]
    with pytest.raises(AdoImportError, match=re.escape(f"missing work item.fields.{key}")):
        wm.remote_item(row)


def test_remote_item_refuses_an_omitted_row_and_a_non_integer_rev():
    with pytest.raises(AdoImportError):
        wm.remote_item(None)  # errorPolicy=omit leaves a null in the batch
    for key, wrong in (("fields", ["System.State"]), ("relations", {"rel": "x"})):
        row = spec_row()
        row[key] = wrong
        with pytest.raises(AdoImportError, match="not an object or"):
            wm.remote_item(row)
    row = spec_row()
    row["rev"] = "7"
    with pytest.raises(AdoImportError, match="rev"):
        wm.remote_item(row)


# --- merge_tags: read, merge, replace ---------------------------------------------------------------------

def test_merge_tags_keeps_human_tags_and_replaces_plugin_tags():
    existing = "customer-ask;  Needs Review ; sdlc:status:in-flight; risk:LOW; sdlc:spec:0004"
    merged = wm.merge_tags(existing, {"sdlc:spec:0004", "sdlc:status:ready", "risk:MEDIUM"})
    assert merged == "Needs Review; customer-ask; risk:MEDIUM; sdlc:spec:0004; sdlc:status:ready"
    assert wm.merge_tags(merged, {"sdlc:spec:0004", "sdlc:status:ready", "risk:MEDIUM"}) == merged  # idempotent


def test_merge_tags_edges():
    assert wm.merge_tags(None, {"sdlc:spec:0004"}) == "sdlc:spec:0004"
    assert wm.merge_tags("", set()) == ""
    assert wm.merge_tags("a; b; a", set()) == "a; b"  # a duplicate collapses
    assert wm.merge_tags("sdlc:spec:0004; keep", set()) == "keep"  # the plugin tags are the repo's to withdraw


@pytest.mark.parametrize("bad", ["customer-ask", "sdlc:spec:1; sdlc:spec:2", "sdlc:spec:1\nrisk:HIGH", ""])
def test_merge_tags_refuses_a_plugin_tag_that_is_not_one(bad):
    with pytest.raises(ValueError):
        wm.merge_tags("keep", {bad})


# --- merge_description: only between the markers -------------------------------------------------------

def test_merge_description_replaces_only_the_block_and_keeps_both_sides_byte_for_byte():
    existing = f"<div>team notes</div>{BEGIN}<p>old</p>{END}<p>tail — kept</p>"
    merged = wm.merge_description(existing, "<p>new</p>")
    assert merged == f"<div>team notes</div>{BEGIN}<p>new</p>{END}<p>tail — kept</p>"
    assert wm.merge_description(merged, "<p>new</p>") == merged
    assert wm.merge_description(existing, f"{BEGIN}<p>new</p>{END}") == merged  # a marker-wrapped block is unwrapped


def test_merge_description_without_markers_appends_a_block_after_the_human_text():
    assert wm.merge_description("<div>typed by hand</div>", "<p>x</p>") == f"<div>typed by hand</div>{BEGIN}<p>x</p>{END}"
    assert wm.merge_description(None, "<p>x</p>") == f"{BEGIN}<p>x</p>{END}"
    assert wm.merge_description("   ", "<p>x</p>") == f"{BEGIN}<p>x</p>{END}"


@pytest.mark.parametrize("existing", [f"a{BEGIN}b", f"a{END}b", f"{END}a{BEGIN}b", f"{BEGIN}{BEGIN}x"])
def test_merge_description_refuses_markers_it_cannot_pair(existing):
    with pytest.raises(ValueError, match="marker"):
        wm.merge_description(existing, "<p>x</p>")


def test_merge_description_refuses_a_block_that_would_break_the_markers():
    with pytest.raises(ValueError, match="marker"):
        wm.merge_description("<p>x</p>", f"<p>a</p>{END}<p>b</p>")


# --- build_update_patch -----------------------------------------------------------------------------------

def test_update_patch_with_nothing_to_change_is_the_test_op_alone():
    patch = patch_for(spec_row(), projection())
    assert patch == [{"op": "test", "path": "/rev", "value": 7}]
    assert not wm.has_changes(patch)


@pytest.mark.parametrize("change", [{}, {"System.Title": "renamed"}, {"System.State": "Resolved"},
                                    {"Custom.RiskTier": "HIGH"}])
def test_update_patch_first_op_is_always_the_rev_test(change):
    row = spec_row()
    row["rev"] = 12
    patch = patch_for(row, projection(**change))
    assert patch[0] == {"op": "test", "path": "/rev", "value": 12}
    assert [op["op"] for op in patch].count("test") == 1


def test_update_patch_writes_each_changed_repo_owned_field_sorted_by_path():
    patch = patch_for(spec_row(), projection(**{"System.Title": "renamed", "System.State": "Resolved",
                                                 "Custom.RiskTier": "HIGH"}))
    assert patch[1:] == [{"op": "replace", "path": "/fields/Custom.RiskTier", "value": "HIGH"},
                         {"op": "replace", "path": "/fields/System.State", "value": "Resolved"},
                         {"op": "replace", "path": "/fields/System.Title", "value": "renamed"}]
    assert wm.has_changes(patch)


def test_update_patch_does_not_write_a_field_the_item_carries_no_value_for():
    # the board may not have the field at all (a write would be a rule error), so it is not compared
    assert patch_for(spec_row(), projection(**{"Custom.Release": "2026.10"}))[1:] == []
    row = spec_row()
    row["fields"]["Custom.Release"] = ""  # the board holds the field, empty: that is a value to replace
    assert patch_for(row, projection(**{"Custom.Release": "2026.10"}))[1:] == [
        {"op": "replace", "path": "/fields/Custom.Release", "value": "2026.10"}]


def test_update_patch_has_no_op_for_a_value_equal_after_normalising():
    row = spec_row()
    row["fields"]["Custom.ReviewerMail"] = KIM
    assert patch_for(row, projection(**{"Custom.ReviewerMail": KIM_UPPER}))[1:] == []  # a case-folded e-mail
    assert patch_for(row, projection(**{"Custom.ReviewerMail": " " + KIM + " "}))[1:] == []  # trimmed
    assert [op["path"] for op in patch_for(row, projection(**{"Custom.ReviewerMail": "lee" + "@corp.com"}))[1:]] \
        == ["/fields/Custom.ReviewerMail"]
    row["fields"]["System.Tags"] = "sdlc:status:in-flight;risk:MEDIUM ;  sdlc:spec:0004; sdlc-repo:claims-api"
    assert patch_for(row, projection())[1:] == []  # the same tag set in another order and spacing
    remote_html = row["fields"]["System.Description"]
    assert patch_for(row, projection(**{"System.Description": "  " + block_of(remote_html) + " "}))[1:] == []


def test_update_patch_keeps_the_tags_a_person_added():
    row = spec_row()
    row["fields"]["System.Tags"] += "; customer-ask; Needs Review"
    patch = patch_for(row, projection(**{"System.State": "Resolved"}) | {"tags": {
        "sdlc:spec:0004", "sdlc:status:resolved", "sdlc-repo:claims-api", "risk:MEDIUM", "not-ours"}})
    tags = next(op for op in patch if op["path"] == "/fields/System.Tags")
    assert tags["value"] == ("Needs Review; customer-ask; risk:MEDIUM; sdlc-repo:claims-api; sdlc:spec:0004; "
                             "sdlc:status:resolved")  # old status tag gone, human tags kept, "not-ours" never written
    assert apply_to(row, patch)["fields"]["System.Tags"] == tags["value"]


def test_update_patch_rewrites_only_the_description_block():
    row = spec_row()
    row["fields"]["System.Description"] += "<p>postscript from the team</p>"
    patch = patch_for(row, projection(**{"System.Description": f"{BEGIN}<p>spec 0004 moved</p>{END}"}))
    (desc,) = [op for op in patch if op["path"] == "/fields/System.Description"]
    assert desc["value"].startswith("<div>Raised by the intake team after the October incident.</div>" + BEGIN)
    assert desc["value"].endswith(f"<p>spec 0004 moved</p>{END}<p>postscript from the team</p>")
    assert patch_for(apply_to(row, patch), projection(**{"System.Description": f"{BEGIN}<p>spec 0004 moved</p>{END}"}))[1:] == []


def test_update_patch_fills_an_empty_description_and_leaves_an_absent_one_alone():
    row = feature_row()  # no Description key at all
    proj = projection("feature")
    proj["fields"] = {"System.Description": "<p>FE-03</p>"}
    proj["tags"] = {"sdlc:feature:03", "sdlc-repo:claims-api"}
    assert patch_for(row, proj)[1:] == []
    row["fields"]["System.Description"] = ""
    assert patch_for(row, proj)[1:] == [
        {"op": "replace", "path": "/fields/System.Description", "value": f"{BEGIN}<p>FE-03</p>{END}"}]


def test_update_patch_never_writes_a_field_the_board_owns():
    changed = {"System.AssignedTo": KIM, "System.IterationPath": "Claims\\Sprint 8", "System.AreaPath": "Claims\\Other",
               "Microsoft.VSTS.Common.Priority": 1, "Microsoft.VSTS.Common.StackRank": 5.0}
    assert patch_for(spec_row(), projection(**changed))[1:] == []
    # a requirement's State is the board's, its Priority the repo's (the per-kind ownership)
    patch = patch_for(spec_row(), projection("requirement", **{"System.State": "Closed",
                                                                "Microsoft.VSTS.Common.Priority": 1}))
    assert patch[1:] == [{"op": "replace", "path": "/fields/Microsoft.VSTS.Common.Priority", "value": 1}]


def test_update_patch_never_blanks_a_field_from_a_missing_value():
    assert patch_for(spec_row(), projection(**{"Custom.RiskTier": None}))[1:] == []


@pytest.mark.parametrize("ref", ["Microsoft.VSTS.Scheduling.StoryPoints", "microsoft.vsts.scheduling.Effort"])
def test_update_patch_refuses_an_effort_field_even_when_it_equals_the_board(ref):
    with pytest.raises(ValueError, match="effort"):
        patch_for(spec_row(), projection(**{ref: 3}))


@pytest.mark.parametrize("ref", ["System.History", "System.Rev", "System.Id", "WEF_1234_Kanban.Column"])
def test_update_patch_refuses_a_read_only_field_and_the_comment_back_door(ref):
    with pytest.raises(ValueError, match="read-only"):
        patch_for(spec_row(), projection(**{ref: "x"}))


def test_update_patch_without_a_rev_raises_instead_of_guessing():
    remote = wm.remote_item(spec_row())
    del remote["rev"]
    with pytest.raises(AdoImportError, match="rev"):
        wm.build_update_patch(remote, projection())


def test_update_patch_is_idempotent_once_applied():
    proj = projection(**{"System.Title": "renamed", "System.State": "Resolved",
                         "System.Description": f"{BEGIN}<p>moved</p>{END}"})
    proj["tags"] = {"sdlc:spec:0004", "sdlc:status:resolved", "risk:HIGH"}
    patch = patch_for(spec_row(), proj)
    assert len(patch) > 3
    assert patch_for(apply_to(spec_row(), patch), proj) == [{"op": "test", "path": "/rev", "value": 8}]


def test_update_patch_agrees_with_the_model_diff_on_which_paths_change():
    proj = projection(**{"System.Title": "renamed", "System.State": "Resolved"})
    remote = wm.remote_item(spec_row())
    assert [op["path"] for op in wm.build_update_patch(remote, proj)[1:]] \
        == [op["path"] for op in sm.diff(proj, remote, sm.ownership_for("spec"))]


# --- build_create_patch --------------------------------------------------------------------------------------

HYPERLINK = "https://dev.azure.com/contoso/Claims/_git/claims-api?version=GC" + SHA + "&path=/specs/0004.md"
PARENT = "https://dev.azure.com/contoso/_apis/wit/workItems/4410"
HISTORY = "Created from specs/0004-duplicate-claim-409.md by sprd 3f9a1c2b7d04"


def minimal() -> dict:
    return {"ref": "sdlc:spec:0004", "kind": "spec", "id": "0004", "title": "t", "status": "ready",
            "fields": {"System.Title": "0004 · duplicate claim 409", "System.State": "Ready",
                       "System.Description": "<p>spec 0004</p>"},
            "tags": {"sdlc:spec:0004", "sdlc:status:ready"}, "parent_ref": None, "parent_note": None,
            "related_refs": [], "source_path": "specs/0004.md", "source_sha": SHA}


def test_create_patch_golden():
    patch = wm.build_create_patch(minimal(), schema(), HYPERLINK, HISTORY, PARENT)
    assert patch == [
        {"op": "add", "path": "/fields/System.Description", "value": f"{BEGIN}<p>spec 0004</p>{END}"},
        {"op": "add", "path": "/fields/System.State", "value": "Ready"},
        {"op": "add", "path": "/fields/System.Tags", "value": "sdlc:spec:0004; sdlc:status:ready"},
        {"op": "add", "path": "/fields/System.Title", "value": "0004 · duplicate claim 409"},
        {"op": "add", "path": "/fields/System.History", "value": HISTORY},
        {"op": "add", "path": "/relations/-",
         "value": {"rel": "Hyperlink", "url": HYPERLINK, "attributes": {"comment": "source file"}}},
        {"op": "add", "path": "/relations/-",
         "value": {"rel": "System.LinkTypes.Hierarchy-Reverse", "url": PARENT, "attributes": {"name": "Parent"}}},
    ]
    json.dumps(patch)  # JSON-ready


def test_create_patch_has_no_rev_test_and_no_parent_link_when_the_parent_is_unknown():
    patch = wm.build_create_patch(minimal(), schema(), HYPERLINK, HISTORY, None)
    assert not any(op["op"] == "test" for op in patch)
    assert [op["value"]["rel"] for op in patch if op["path"] == "/relations/-"] == ["Hyperlink"]


def test_create_patch_writes_the_plugin_tags_only_and_keeps_a_marker_wrapped_description():
    proj = minimal()
    proj["tags"] = {"sdlc:spec:0004", "customer-ask", "risk:HIGH"}
    proj["fields"]["System.Description"] = f"{BEGIN}<p>x</p>{END}"
    proj["fields"]["System.Tags"] = "from-fields"  # tags come from the projection's tag set, nowhere else
    patch = {op["path"]: op["value"] for op in wm.build_create_patch(proj, schema(), HYPERLINK, HISTORY, None)}
    assert patch["/fields/System.Tags"] == "risk:HIGH; sdlc:spec:0004"
    assert patch["/fields/System.Description"] == f"{BEGIN}<p>x</p>{END}"


def test_create_patch_writes_what_the_model_diff_says_a_push_would():
    proj = projection()
    paths = {op["path"] for op in wm.build_create_patch(proj, schema(), HYPERLINK, HISTORY, PARENT)}
    assert {op["path"] for op in sm.diff(proj, None)} <= paths  # plan and apply cannot disagree about a field


def test_create_patch_skips_a_missing_value_and_requires_a_title():
    proj = minimal()
    proj["fields"]["Custom.RiskTier"] = None
    assert "/fields/Custom.RiskTier" not in {op["path"] for op in
                                             wm.build_create_patch(proj, schema(), HYPERLINK, HISTORY, None)}
    del proj["fields"]["System.Title"]
    with pytest.raises(ValueError, match="System.Title"):
        wm.build_create_patch(proj, schema(), HYPERLINK, HISTORY, None)


def test_create_patch_refuses_an_effort_field_the_process_calls_anything():
    proj = minimal()
    proj["fields"]["Microsoft.VSTS.Scheduling.StoryPoints"] = 3
    with pytest.raises(ValueError, match="effort"):
        wm.build_create_patch(proj, schema(), HYPERLINK, HISTORY, None)
    proj = minimal()
    proj["fields"]["Custom.Effort"] = 3
    custom = schema()
    custom["backlog"]["effort_field"] = "Custom.Effort"  # the backlog names its own effort field
    with pytest.raises(ValueError, match="effort"):
        wm.build_create_patch(proj, custom, HYPERLINK, HISTORY, None)
    proj["fields"]["System.History"] = "a comment through the back door"
    del proj["fields"]["Custom.Effort"]
    with pytest.raises(ValueError, match="read-only"):
        wm.build_create_patch(proj, schema(), HYPERLINK, HISTORY, None)


@pytest.mark.parametrize("history", ["", "   ", "created for " + KIM, "created " + "00000000-0000-0000-0000-" + "000000000003"])
def test_create_patch_refuses_a_history_line_that_is_empty_or_names_a_person(history):
    with pytest.raises(ValueError, match="history"):
        wm.build_create_patch(minimal(), schema(), HYPERLINK, history, None)


@pytest.mark.parametrize("hyperlink", ["", "http://dev.azure.com/x", "https://dev.azure.com/a b", "javascript:alert(1)"])
def test_create_patch_refuses_a_link_that_is_not_an_https_url(hyperlink):
    with pytest.raises(ValueError, match="hyperlink"):
        wm.build_create_patch(minimal(), schema(), hyperlink, HISTORY, None)


@pytest.mark.parametrize("parent", ["https://dev.azure.com/contoso/_apis/wit/workItems/", "4410",
                                    "https://dev.azure.com/contoso/_apis/wit/workItems/4410/../9"])
def test_create_patch_refuses_a_parent_url_that_is_not_a_work_item(parent):
    with pytest.raises(ValueError, match="parent"):
        wm.build_create_patch(minimal(), schema(), HYPERLINK, HISTORY, parent)


# --- WIQL ---------------------------------------------------------------------------------------------------

def wiql_of(fixture: str) -> str:
    # the hand-written stand-in's `_command` (B0 2026-10-15: `wiql_by_tag` is captured too, in another select list)
    command = json.loads(wit_path(fixture, hand_written=True).read_text(encoding="utf-8"))["_command"]
    return command[command.index("--wiql") + 1]


def test_wiql_ref_lookup_matches_the_fixture_query():
    assert wm.wiql_ref_lookup("sdlc:spec:0004", "Claims") == wiql_of("wiql_by_tag")
    assert "[System.AssignedTo]" in wm.wiql_ref_lookup("sdlc:spec:0004", "Claims")


def test_wiql_untagged_golden():
    # B0 (2026-10-15): the project is named as a literal; `az boards query` answered the `@project` macro with zero bytes
    assert wm.wiql_untagged(["Claims\\SDLC"], [], "claims-api", "Claims") == (
        "SELECT [System.Id],[System.WorkItemType],[System.Title],[System.State],[System.Tags],[System.AssignedTo] "
        "FROM WorkItems WHERE [System.TeamProject] = 'Claims' AND ([System.AreaPath] UNDER 'Claims\\SDLC') "
        "AND NOT [System.Tags] CONTAINS 'sdlc-repo:claims-api'")
    assert wm.wiql_untagged(["Claims\\SDLC"], [], "claims-api") == (   # no project: `--project` alone scopes it
        "SELECT [System.Id],[System.WorkItemType],[System.Title],[System.State],[System.Tags],[System.AssignedTo] "
        "FROM WorkItems WHERE ([System.AreaPath] UNDER 'Claims\\SDLC') "
        "AND NOT [System.Tags] CONTAINS 'sdlc-repo:claims-api'")


@pytest.mark.parametrize("build", [lambda p: wm.wiql_ref_lookup("sdlc:spec:0004", p),
                                   lambda p: wm.wiql_untagged(["Claims\\SDLC"], ["Claims\\Sprint 7"], "claims-api", p)],
                         ids=["ref_lookup", "untagged"])
@pytest.mark.parametrize("project", ["Claims", "Claims Ops", "Expedição_2", None])
def test_no_wiql_the_mirror_builds_uses_the_current_project_macro(build, project):
    """B0 (2026-10-15): `[System.TeamProject] = @project` made `az boards query` print zero bytes (exit 0) where items
    matched; the literal name, or no clause with `--project`, returned the rows."""
    wiql = build(project)
    assert "@project" not in wiql and "@" not in wiql
    assert (f"[System.TeamProject] = '{project}'" in wiql) == (project is not None)


@pytest.mark.parametrize("project", ["Claims' OR 1=1 --", "Claims]", "Claims\\x", "Claims\n", " Claims", "", "a;b",
                                     "a\"b", 7])
def test_a_project_name_outside_the_whitelist_is_never_put_in_a_query(project):
    with pytest.raises(ValueError, match="project"):
        wm.wiql_ref_lookup("sdlc:spec:0004", project)
    with pytest.raises(ValueError, match="project"):
        wm.wiql_untagged(["Claims\\SDLC"], [], "claims-api", project)
    with pytest.raises(ValueError, match="project"):
        wm.project_clause(project)


def test_wiql_untagged_selects_assignee_and_matches_the_fixture_query():
    both = wm.wiql_untagged(["Claims\\SDLC"], ["Claims\\Sprint 7"], "claims-api", "Claims")
    assert both == wiql_of("wiql_untagged")
    assert "[System.AssignedTo]" in both
    assert wm.wiql_untagged([], ["Claims\\Sprint 7", "Claims\\Sprint 7"], "claims-api").count("UNDER") == 1  # de-duplicated
    assert "sdlc-repo:" in bc.PLUGIN_TAG_PREFIXES[1]


@pytest.mark.parametrize("path", ["Claims\\O'Brien", "Claims\\Area]", "Claims\\a;b", "Claims\\a(b)", "Claims\\a\nb",
                                  "Claims\\a%27", " Claims", "", "Claims\\café"])
def test_wiql_untagged_refuses_a_path_outside_the_whitelist(path):
    with pytest.raises(ValueError):
        wm.wiql_untagged([path], [], "claims-api")
    with pytest.raises(ValueError):
        wm.wiql_untagged([], [path], "claims-api")


@pytest.mark.parametrize("slug", ["claims'api", "claims]", "claims api", "", "a' OR 1=1 --", "claims\\api"])
def test_wiql_untagged_refuses_a_slug_outside_the_whitelist(slug):
    with pytest.raises(ValueError):
        wm.wiql_untagged(["Claims\\SDLC"], [], slug)


def test_wiql_untagged_refuses_a_path_that_is_not_text():
    with pytest.raises(ValueError):
        wm.wiql_untagged([["Claims"]], [], "claims-api")  # unhashable and not a path: a refusal, not a TypeError


def test_wiql_untagged_needs_somewhere_to_look_and_a_list_of_paths():
    with pytest.raises(ValueError, match="path"):
        wm.wiql_untagged([], [], "claims-api")  # an unscoped query would read the whole project
    with pytest.raises(ValueError):
        wm.wiql_untagged("Claims\\SDLC", [], "claims-api")  # a bare string is not a list of paths


@pytest.mark.parametrize("ref", ["sdlc:spec:0004' OR [System.Id] > 0 --", "spec:0004", "sdlc:spec:", "sdlc:spec:0004\n",
                                 "sdlc:Spec:0004", ""])
def test_wiql_ref_lookup_refuses_anything_but_a_ref(ref):
    with pytest.raises(ValueError):
        wm.wiql_ref_lookup(ref)


# --- classify_write_error: a closed enum --------------------------------------------------------------------

# hand-written (unverified): the wording is taken from the known TF/VS codes, not from a captured response;
# the B0 capture adds real strings and may add rows here, never widen the enum.
STDERR = {
    "conflict": "ERROR: TF26071: This work item has been changed by someone else since you opened it. "
                "You will need to refresh it and discard your changes.",
    "rule": "ERROR: TF401320: Rule Error for field State. Error code: InvalidListValue, InvalidNotEmpty. "
            "The value 'Frozen' is not in the list of supported values.",
    "permission": "ERROR: TF50309: You do not have sufficient permissions to perform this operation. (HTTP 403 Forbidden)",
    "throttled": "ERROR: Request was blocked due to exceeding usage of resource 'WorkItemTrackingResource' in "
                 "namespace 'WorkItemTracking'. (HTTP 429 Too Many Requests)",
    "not_found": "ERROR: TF401232: Work item 4521 does not exist, or you do not have permissions to read it.",
    "unknown": "ERROR: Failed to establish a new connection: [Errno 8] nodename nor servname provided, or not known",
}
ENUM = {"conflict", "rule", "permission", "throttled", "not_found", "unknown"}


@pytest.mark.parametrize("expected", sorted(STDERR))
def test_classify_write_error_over_six_hand_written_strings(expected):
    assert wm.classify_write_error(STDERR[expected]) == expected


@pytest.mark.parametrize("text", [None, "", "   ", 409, b"HTTP 409", ["conflict"], "ERROR: something nobody has seen"])
def test_classify_write_error_never_returns_outside_the_enum(text):
    assert wm.classify_write_error(text) == "unknown"


@pytest.mark.parametrize("text, expected", [
    ("TF401232: Work item 409 does not exist, or you do not have permissions to read it.", "not_found"),
    ("ERROR: Work item 429 was not found (HTTP 404 Not Found)", "not_found"),
    ("ERROR: (HTTP 409 Conflict) the rev test failed", "conflict"),
    ("ERROR: status code: 429, retry later", "throttled"),
    ("ERROR: TF51535: Cannot find field System.Foo.", "rule"),
    ("ERROR: TF401347: Invalid tree name given for work item 12, field 'System.AreaPath'.", "rule"),
    ("ERROR: VS30063: You are not authorized to access https://dev.azure.com (HTTP 401 Unauthorized)", "permission"),
])
def test_classify_write_error_reads_the_code_not_a_number_in_the_message(text, expected):
    assert wm.classify_write_error(text) == expected
    assert wm.classify_write_error(text.upper()) == expected  # the casing az prints is not the casing it was written in


# --- file_hyperlink --------------------------------------------------------------------------------------

def test_file_hyperlink_pins_the_commit():
    url = wm.file_hyperlink(REMOTE, "specs/0004-duplicate-claim-409.md", SHA)
    assert url == f"{REMOTE.web_url}?version=GC{SHA}&path=/specs/0004-duplicate-claim-409.md"
    assert url.startswith("https://dev.azure.com/contoso/Claims/_git/claims-api?version=GC")
    assert wm.file_hyperlink(REMOTE, "/specs/0004-duplicate-claim-409.md", SHA) == url  # a leading slash is the same file


def test_file_hyperlink_encodes_what_would_end_the_query():
    url = wm.file_hyperlink(REMOTE, "specs/a b&c#d?e.md", SHA)
    assert url.endswith("path=/specs/a%20b%26c%23d%3Fe.md")
    assert url.count("&") == 1 and url.count("#") == 0 and url.count("?") == 1


@pytest.mark.parametrize("path", ["", "/", "../secrets.md", "specs/../../x", "specs\\a.md", "specs//a.md", "a\nb.md"])
def test_file_hyperlink_refuses_a_path_that_is_not_inside_the_repository(path):
    with pytest.raises(ValueError, match="path"):
        wm.file_hyperlink(REMOTE, path, SHA)


@pytest.mark.parametrize("sha", ["", "abc", "ABCDEF1234567", "g" * 40, "main", SHA + "0" * 30])
def test_file_hyperlink_refuses_a_sha_that_is_not_a_commit(sha):
    with pytest.raises(ValueError, match="sha"):
        wm.file_hyperlink(REMOTE, "specs/a.md", sha)


def test_file_hyperlink_is_for_an_azure_devops_remote_only():
    github = RemoteInfo("github", "o", None, "r", "o/r", None, "https://github.com/o/r")
    with pytest.raises(ValueError, match="Azure DevOps"):
        wm.file_hyperlink(github, "specs/a.md", SHA)
    with pytest.raises(ValueError, match="Azure DevOps"):
        wm.work_item_url(github, 4410)


def test_work_item_url_is_the_parent_link_form():
    assert wm.work_item_url(REMOTE, 4410) == PARENT
    for bad in (0, -1, True, "4410", None):
        with pytest.raises(ValueError, match="work item id"):
            wm.work_item_url(REMOTE, bad)
