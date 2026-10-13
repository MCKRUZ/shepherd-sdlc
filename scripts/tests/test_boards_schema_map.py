"""The pure Boards schema model: az JSON in, a plain-dict picture of the client's process out (B1-P2).

`ado_schema_map.py` reads the discovery documents (categories, types, states, fields, backlog
levels, classification nodes, team iterations, link types) through `ado_map._require`, so a key
it needs raises `AdoImportError("unexpected az shape: missing <what>.<key>")` instead of being
defaulted, and then answers the questions the mirror asks of that picture: which type, which
state, which fields are refused, and how the requirements tree fits the process. Nothing here
spawns anything; every input is a fixture from `wit/` (hand-written, unverified until B0) or
`wit/synthetic/` (a Scrum, a CMMI, a Basic and a two-portfolio-level process nobody will capture).
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401

import ast
import json
import re
from pathlib import Path

import pytest

import ado_schema_map as asm
from boards_contract import GUID_RE, KINDS, TREE_ORDER
from ado_map import AdoImportError
from tests.ado_boards_fixtures import load_wit

MODULE = Path(asm.__file__)
DOMAINS = ["Intake", "Payments", "Fraud", "Disputes"]  # three of them are Area Path nodes in the Agile fixture
STATES_OF = (("User Story", "type_states_user_story"), ("Bug", "type_states_bug"), ("Issue", "type_states_issue"))
FIELDS_OF = (("User Story", "type_fields_user_story"), ("Issue", "type_fields_issue"))


def build(*, types_doc, categories_doc, backlog_doc=None, states=None, fields_by_type=None, nodes_doc=None):
    return asm.build_schema(
        discovered_at="2026-10-13T00:00:00Z",
        project={"name": "Claims", "id": "00000000-0000-0000-0000-000000000020"},
        team={"name": "Claims Team", "id": "00000000-0000-0000-0000-000000000021"},
        categories=asm.map_categories(categories_doc),
        types=asm.map_types(types_doc),
        states_by_type=states or {},
        fields_by_type=fields_by_type or {},
        fields=asm.map_fields(load_wit("fields")),
        backlog=asm.map_backlog_config(backlog_doc) if backlog_doc is not None else None,
        nodes=asm.map_nodes(nodes_doc if nodes_doc is not None else {"value": []}),
        team_iterations=asm.map_team_iterations(load_wit("team_iterations")),
        link_types=asm.map_link_types(load_wit("relation_types")),
        commands=["devops invoke wit workItemTypes"],
    )


def agile_schema(*, all_states=False):
    """Discovery reads states and fields only for the types it will write; `all_states` reads every
    type's states from the types document, as a fully read process would have them."""
    types_doc = load_wit("types")
    states = {t: asm.map_type_states(t, load_wit(f)) for t, f in STATES_OF}
    if all_states:
        states = {t["name"]: asm.map_type_states(t["name"], t["states"]) for t in types_doc["value"]}
    return build(
        types_doc=types_doc, categories_doc=load_wit("type_categories"),
        backlog_doc=load_wit("backlog_config"), nodes_doc=load_wit("classification_nodes"),
        states=states, fields_by_type={t: asm.map_type_fields(t, load_wit(f)) for t, f in FIELDS_OF})


def synthetic_schema(stem, backlog_doc=None):
    """A process whose states ride inside its types document, as `workItemTypes` really answers."""
    types_doc = load_wit(f"{stem}_types")
    states = {t["name"]: asm.map_type_states(t["name"], t["states"]) for t in types_doc["value"]}
    return build(types_doc=types_doc, categories_doc=load_wit(f"{stem}_categories"),
                 backlog_doc=backlog_doc, states=states)


def two_level(*, drop_top_level=False, add_pillar=False, hide=None):
    """Two portfolio levels above Epic (Initiative nearest, Theme above it) and a stand-alone
    Objective type; `add_pillar` puts a third level on top, `drop_top_level` removes Theme, `hide`
    marks the named portfolio level hidden in the backlog configuration."""
    types_doc, backlog = load_wit("two_level_types"), load_wit("two_level_backlog_config")
    for level in backlog["portfolioBacklogs"]:
        level["isHidden"] = level["name"] == hide
    if drop_top_level:
        backlog["portfolioBacklogs"] = [b for b in backlog["portfolioBacklogs"] if b["name"] != "Themes"]
    if add_pillar:
        theme = next(b for b in backlog["portfolioBacklogs"] if b["name"] == "Themes")
        pillar = json.loads(json.dumps(theme))
        pillar.update(id="Custom.PillarCategory", name="Pillars", rank=7)
        pillar["workItemTypes"] = [{"name": "Pillar"}]
        pillar["defaultWorkItemType"] = {"name": "Pillar"}
        backlog["portfolioBacklogs"].append(pillar)
        pillar_type = json.loads(json.dumps(next(t for t in types_doc["value"] if t["name"] == "Objective")))
        pillar_type.update(name="Pillar", referenceName="Custom.Pillar")
        types_doc["value"].append(pillar_type)
    states = {t["name"]: asm.map_type_states(t["name"], t["states"]) for t in types_doc["value"]}
    return build(types_doc=types_doc, categories_doc=load_wit("two_level_categories"), backlog_doc=backlog,
                 states=states)


# --- every key the mapping needs raises, naming itself -------------------------------------------

CASES = {
    "map_categories": ("type_categories", lambda d: asm.map_categories(d)),
    "map_types": ("types", lambda d: asm.map_types(d)),
    "map_type_states": ("type_states_user_story", lambda d: asm.map_type_states("User Story", d)),
    "map_type_fields": ("type_fields_user_story", lambda d: asm.map_type_fields("User Story", d)),
    "map_fields": ("fields", lambda d: asm.map_fields(d)),
    "map_backlog_config": ("backlog_config", lambda d: asm.map_backlog_config(d)),
    "map_nodes": ("classification_nodes", lambda d: asm.map_nodes(d)),
    "map_team_iterations": ("team_iterations", lambda d: asm.map_team_iterations(d)),
    "map_link_types": ("relation_types", lambda d: asm.map_link_types(d)),
}
PAIRS = [(mapper, key) for mapper, keys in asm.REQUIRED_KEYS.items() for key in keys]


def targets(doc):
    """The dicts a mapper reads its required keys from: a list document's items, else the document."""
    value = doc.get("value") if isinstance(doc, dict) else None
    return value if isinstance(value, list) else [doc]


def test_required_keys_cover_exactly_the_mappers():
    mappers = {n for n in dir(asm) if n.startswith("map_") and callable(getattr(asm, n))}
    assert set(asm.REQUIRED_KEYS) == set(CASES) == mappers
    assert all(isinstance(keys, tuple) and keys for keys in asm.REQUIRED_KEYS.values())


@pytest.mark.parametrize("mapper, key", PAIRS, ids=[f"{m}-{k}" for m, k in PAIRS])
def test_deleting_a_required_key_raises_naming_it(mapper, key):
    fixture, call = CASES[mapper]
    call(load_wit(fixture))  # the untouched fixture maps cleanly
    doc = load_wit(fixture)
    for item in targets(doc):
        item.pop(key, None)
    with pytest.raises(AdoImportError, match=rf"^unexpected az shape: missing .+\.{re.escape(key)}$"):
        call(doc)


@pytest.mark.parametrize("mapper", sorted(CASES))
def test_a_document_that_is_not_a_list_of_dicts_raises_rather_than_returns_nothing(mapper):
    _, call = CASES[mapper]
    with pytest.raises(AdoImportError, match="missing"):
        call({"count": 0})


# --- the mappers on the Agile fixtures -------------------------------------------------------------

def test_categories_are_keyed_without_the_microsoft_prefix():
    cats = asm.map_categories(load_wit("type_categories"))
    assert set(cats) == {"EpicCategory", "FeatureCategory", "RequirementCategory", "TaskCategory", "BugCategory"}
    assert cats["RequirementCategory"] == {"default_type": "User Story", "types": ["User Story"]}
    custom = load_wit("type_categories")
    custom["value"][0]["referenceName"] = "Custom.InitiativeCategory"
    assert "Custom.InitiativeCategory" in asm.map_categories(custom)


def test_types_carry_reference_name_disabled_transitions_and_required_fields():
    types = asm.map_types(load_wit("types"))
    assert list(types) == ["Epic", "Feature", "User Story", "Task", "Bug", "Issue"]
    story = types["User Story"]
    assert set(story) == {"reference_name", "disabled", "transitions", "required_fields"}
    assert story["reference_name"] == "Microsoft.VSTS.WorkItemTypes.UserStory"
    assert story["disabled"] is False
    assert story["required_fields"] == ["System.Title"]
    assert story["transitions"][""] == ["New"]
    assert story["transitions"]["New"] == ["Ready", "Active", "Resolved", "Closed", "Removed"]


def test_a_missing_transitions_table_is_none_not_an_empty_one():
    doc = load_wit("types")
    for t in doc["value"]:
        t.pop("transitions")
        t.pop("isDisabled")
    types = asm.map_types(doc)
    assert all(t["transitions"] is None and t["disabled"] is False for t in types.values())
    doc["value"][0]["transitions"] = ["not", "a", "dict"]
    with pytest.raises(AdoImportError, match="transitions"):
        asm.map_types(doc)


def test_states_keep_their_order_and_category():
    states = asm.map_type_states("User Story", load_wit("type_states_user_story"))
    assert [(s["name"], s["category"], s["order"]) for s in states] == [
        ("New", "Proposed", 0), ("Ready", "Proposed", 1), ("Active", "InProgress", 2),
        ("Resolved", "Resolved", 3), ("Closed", "Completed", 4), ("Removed", "Removed", 5)]
    assert not any("_notes" in s for s in states)


def test_an_unknown_state_category_is_kept_and_noted_never_rewritten():
    doc = load_wit("type_states_user_story")
    doc["value"][1]["category"] = "Pending"
    states = asm.map_type_states("User Story", doc)
    assert states[1]["category"] == "Pending"
    assert "Pending" in states[1]["_notes"][0]
    assert "_notes" not in states[0]


def test_type_fields_read_what_the_per_type_route_carries_and_leave_the_rest_unknown():
    fields = asm.map_type_fields("User Story", load_wit("type_fields_user_story"))
    title, risk = fields["System.Title"], fields["Custom.RiskTier"]
    assert set(title) == {"type", "read_only", "always_required", "default", "allowed_values"}
    assert title["always_required"] is True and title["allowed_values"] is None  # [] means unrestricted
    assert title["type"] is None and title["read_only"] is None  # this route does not say
    assert risk["allowed_values"] == ["LOW", "MEDIUM", "HIGH"]
    assert fields["Microsoft.VSTS.Common.Priority"]["default"] == 2


def test_project_fields_say_which_are_custom_identity_and_read_only():
    fields = asm.map_fields(load_wit("fields"))
    assert {r for r, f in fields.items() if f["custom"]} == {"Custom.RiskTier"}
    assert fields["System.AssignedTo"]["is_identity"] is True
    assert fields["System.Id"]["read_only"] is True and fields["System.Title"]["read_only"] is False
    assert fields["Custom.RiskTier"]["is_picklist"] is True
    assert fields["System.Title"]["type"] == "string"


def test_backlog_levels_run_top_down_with_effort_bugs_and_mapped_states():
    backlog = asm.map_backlog_config(load_wit("backlog_config"))
    assert [(lv["id"], lv["kind"], lv["rank"]) for lv in backlog["levels"]] == [
        ("Microsoft.EpicCategory", "portfolio", 4), ("Microsoft.FeatureCategory", "portfolio", 3),
        ("Microsoft.RequirementCategory", "requirement", 2), ("Microsoft.TaskCategory", "task", 1)]
    assert backlog["levels"][0]["types"] == ["Epic"] and backlog["levels"][0]["default_type"] == "Epic"
    assert backlog["effort_field"] == "Microsoft.VSTS.Scheduling.StoryPoints"
    assert backlog["bugs_behavior"] == "asRequirements"
    assert backlog["mapped_states"]["User Story"]["Ready"] == "Proposed"


def test_backlog_levels_are_sorted_by_rank_whatever_order_az_lists_them():
    backlog = asm.map_backlog_config(load_wit("two_level_backlog_config"))
    assert [lv["name"] for lv in backlog["levels"] if lv["kind"] == "portfolio"] == [
        "Themes", "Initiatives", "Epics", "Features"]


def test_nodes_become_field_form_paths_with_iteration_dates():
    areas, iterations = asm.map_nodes(load_wit("classification_nodes"))
    assert [a["path"] for a in areas] == ["Claims", "Claims\\SDLC", "Claims\\SDLC\\Intake",
                                          "Claims\\SDLC\\Payments", "Claims\\SDLC\\Fraud"]
    assert set(areas[0]) == {"path", "id", "identifier"} and areas[0]["id"] == 1
    assert iterations[1] == {"path": "Claims\\Sprint 7", "id": 11, "identifier": "00000000-0000-0000-0000-000000000202",
                             "start": "2026-10-05T00:00:00Z", "finish": "2026-10-16T00:00:00Z"}
    assert "start" not in iterations[0]
    odd = load_wit("classification_nodes")
    odd["value"][0]["structureType"] = "release"
    with pytest.raises(AdoImportError, match="structureType"):
        asm.map_nodes(odd)


def test_team_iterations_and_link_types():
    assert asm.map_team_iterations(load_wit("team_iterations")) == [
        {"name": "Sprint 7", "path": "Claims\\Sprint 7", "start": "2026-10-05T00:00:00Z", "finish": "2026-10-16T00:00:00Z"}]
    links = asm.map_link_types(load_wit("relation_types"))
    assert "System.LinkTypes.Related" in links and "System.LinkTypes.Hierarchy-Forward" in links
    assert "ArtifactLink" not in links and "Hyperlink" not in links  # resource links, not work-item links
    disabled = load_wit("relation_types")
    disabled["value"][2]["attributes"]["enabled"] = False
    assert "System.LinkTypes.Related" not in asm.map_link_types(disabled)


# --- the assembled schema ------------------------------------------------------------------------

def test_schema_is_json_clean_deterministic_and_carries_no_identity():
    schema = agile_schema()
    text = json.dumps(schema, sort_keys=True)
    assert json.loads(text) == schema  # no tuples, sets or frozensets
    assert text == json.dumps(agile_schema(), sort_keys=True)
    assert "@" not in text
    node_ids = {n["identifier"] for n in schema["areas"] + schema["iterations"]}
    assert set(GUID_RE.findall(text)) <= node_ids  # the project and team GUIDs were dropped
    assert schema["project"] == {"name": "Claims"} and schema["team"] == {"name": "Claims Team"}
    assert schema["discovered_at"] == "2026-10-13T00:00:00Z"


def test_schema_merges_project_field_facts_into_the_per_type_fields():
    types = agile_schema()["types"]
    title = types["User Story"]["fields"]["System.Title"]
    assert title["type"] == "string" and title["read_only"] is False and title["always_required"] is True
    assert types["User Story"]["states"][1]["name"] == "Ready"
    assert types["Epic"]["states"] is None and types["Epic"]["fields"] is None  # never read, not "none"
    assert types["User Story"]["transitions"][""] == ["New"]


def test_schema_refuses_states_or_fields_for_a_type_the_process_lacks():
    with pytest.raises(AdoImportError, match="Ghost"):
        asm.build_schema(
            discovered_at="x", project=None, team=None, categories={}, types={}, states_by_type={"Ghost": []},
            fields_by_type={}, fields={}, backlog=None, nodes=([], []), team_iterations=[], link_types=[],
            commands=[])


def test_schema_keeps_team_iterations_never_read_as_none_and_an_empty_read_as_empty():
    def built(team_iterations):
        return asm.build_schema(
            discovered_at="x", project=None, team=None, categories={}, types={}, states_by_type={},
            fields_by_type={}, fields={}, backlog=None, nodes=([], []), team_iterations=team_iterations,
            link_types=[], commands=[])
    assert built(None)["team_iterations"] is None  # not read: unknown, not "none"
    assert built([])["team_iterations"] == []  # read, and the team has none


def test_field_on_type_and_transition_allowed():
    schema = agile_schema()
    assert schema["types"]["User Story"]["fields"]["Custom.RiskTier"]["allowed_values"] == ["LOW", "MEDIUM", "HIGH"]
    assert asm.field_on_type(schema, "User Story", "Custom.RiskTier")["allowed_values"] == ["LOW", "MEDIUM", "HIGH"]
    assert asm.field_on_type(schema, "user story", "custom.risktier") is not None
    assert asm.field_on_type(schema, "Issue", "Custom.RiskTier") is None  # not on that type
    assert asm.field_on_type(schema, "Epic", "System.Title") is None  # fields never read for Epic
    assert asm.field_on_type(schema, "Nope", "System.Title") is None
    assert asm.transition_allowed(schema, "Issue", "Active", "Closed") is True
    assert asm.transition_allowed(schema, "Issue", "Closed", "Closed") is True
    assert asm.transition_allowed(schema, "Issue", "", "Active") is True
    assert asm.transition_allowed(schema, "Issue", "", "Closed") is False
    assert asm.transition_allowed(schema, "Issue", "Mystery", "Closed") is None
    assert asm.transition_allowed(schema, "Nope", "A", "B") is None
    flat = json.loads(json.dumps(schema))
    flat["types"]["Issue"]["transitions"] = None
    assert asm.transition_allowed(flat, "Issue", "Active", "Closed") is None


# --- resolve_type ----------------------------------------------------------------------------------

def test_resolve_type_defaults_come_from_the_categories():
    schema = agile_schema()
    assert asm.resolve_type(schema, "spec", {}) == ("User Story", "default type of RequirementCategory")
    assert asm.resolve_type(schema, "epic", {}) == ("Epic", "default type of EpicCategory")
    assert asm.resolve_type(schema, "feature", {})[0] == "Feature"


def test_a_kind_with_no_default_names_the_candidates_instead_of_guessing():
    schema = agile_schema()
    assert asm.resolve_type(schema, "decision", {}) == (
        None, "types.decision not set; candidates present in process: Issue")
    assert asm.resolve_type(schema, "spike", {}) == (None, "types.spike not set; candidates present in process: Task")
    assert asm.resolve_type(schema, "sprint", {}) == (None, "types.sprint not set; no candidate types present in process")


def test_a_type_pin_is_honoured_and_an_unresolvable_one_says_why():
    schema = agile_schema()
    assert asm.resolve_type(schema, "decision", {"types": {"decision": "issue"}}) == ("Issue", "types.decision pinned: Issue")
    name, why = asm.resolve_type(schema, "decision", {"types": {"decision": "Decision"}})
    assert name is None and "pins 'Decision'" in why and "no such type" in why
    disabled = json.loads(json.dumps(schema))
    disabled["types"]["Issue"]["disabled"] = True
    name, why = asm.resolve_type(disabled, "decision", {"types": {"decision": "Issue"}})
    assert name is None and "disabled" in why
    assert asm.resolve_type(disabled, "spec", {"types": {"spec": "Bug"}})[0] == "Bug"


def test_a_missing_category_and_an_unknown_kind():
    schema = synthetic_schema("basic")
    name, why = asm.resolve_type(schema, "feature", {})
    assert name is None and "no FeatureCategory" in why
    with pytest.raises(ValueError, match="unknown kind"):
        asm.resolve_type(schema, "story", {})
    assert set(asm.fit_levels(schema, {})) <= set(KINDS)


@pytest.mark.parametrize("stem, spec_type", [("scrum", "Product Backlog Item"), ("cmmi", "Requirement"), ("basic", "Issue")])
def test_other_inherited_processes_yield_their_requirement_type(stem, spec_type):
    schema = synthetic_schema(stem)
    assert asm.resolve_type(schema, "spec", {})[0] == spec_type
    assert asm.resolve_type(schema, "epic", {})[0] == "Epic"


def test_tree_kinds_resolve_through_the_fit():
    name, why = asm.resolve_type(agile_schema(), "requirement", {})
    assert name is None and why.startswith("requirement is fitted as tag, not an item")
    assert asm.resolve_type(two_level(), "requirement", {})[0] == "Initiative"
    assert asm.resolve_type(two_level(), "domain", {})[0] == "Theme"


# --- resolve_state ---------------------------------------------------------------------------------

def test_ready_takes_the_last_proposed_state():
    schema = agile_schema(all_states=True)
    assert asm.resolve_state(schema, "User Story", "ready", {}) == ("Ready", "rule: last-proposed")
    assert asm.resolve_state(schema, "Epic", "ready", {}) == ("New", "rule: last-proposed")
    assert asm.resolve_state(schema, "User Story", "draft", {}) == ("New", "rule: first-proposed")


def test_merged_is_resolved_when_the_type_has_resolved_and_completed_when_it_does_not():
    schema = agile_schema()
    assert asm.resolve_state(schema, "Bug", "merged", {}) == ("Resolved", "rule: first-resolved")
    assert asm.resolve_state(schema, "Issue", "merged", {}) == (
        "Closed", "rule: first-completed (Issue has no Resolved state)")


def test_in_flight_and_deferred_and_what_a_type_cannot_say():
    schema = agile_schema(all_states=True)
    assert asm.resolve_state(schema, "Task", "in-flight", {}) == ("Active", "rule: first-inprogress")
    assert asm.resolve_state(schema, "Epic", "deferred", {}) == ("Removed", "rule: first-removed")
    state, why = asm.resolve_state(schema, "Bug", "deferred", {})
    assert state is None and "Bug" in why and "Removed" in why
    assert asm.resolve_state(schema, "Bug", "tuesday", {}) == (None, "no state rule for status 'tuesday'")
    assert asm.resolve_state(schema, "Nope", "ready", {}) == (None, "type 'Nope' is not in the process")
    schema["types"]["Issue"]["states"] = None
    assert asm.resolve_state(schema, "Issue", "ready", {}) == (None, "no states were discovered for Issue")


def test_prefer_wins_over_the_rule_and_a_bad_prefer_falls_back_with_a_note():
    schema = agile_schema()
    cfg = {"states": {"prefer": {"ready": "active"}}}
    assert asm.resolve_state(schema, "User Story", "ready", cfg) == ("Active", "prefer: Active")
    per_type = {"states": {"prefer": {"ready": "Active", "User Story": {"ready": "New"}}}}
    assert asm.resolve_state(schema, "User Story", "ready", per_type) == ("New", "prefer: New")
    assert asm.resolve_state(schema, "Bug", "ready", per_type) == ("Active", "prefer: Active")
    several = {"states": {"prefer": {"ready": ["Waiting", "Ready"]}}}
    assert asm.resolve_state(schema, "User Story", "ready", several) == ("Ready", "prefer: Ready")
    bad = {"states": {"prefer": {"ready": "Waiting"}}}
    state, why = asm.resolve_state(schema, "User Story", "ready", bad)
    assert state == "Ready" and why == "prefer 'Waiting' is not a state of User Story; rule: last-proposed"


def test_states_fall_back_to_the_backlog_mapping_when_the_type_was_never_read():
    schema = agile_schema()
    assert schema["types"]["Task"]["states"] is None  # discovery read states for three types only
    state, why = asm.resolve_state(schema, "Task", "in-flight", {})
    assert (state, why) == ("Active", "rule: first-inprogress; states from backlog mapping")
    assert asm.resolve_state(schema, "Feature", "ready", {}) == ("New", "rule: last-proposed; states from backlog mapping")


@pytest.mark.parametrize("stem, status, expected", [
    ("scrum", "ready", "Approved"), ("scrum", "in-flight", "Committed"), ("scrum", "merged", "Done"),
    ("cmmi", "ready", "Proposed"), ("cmmi", "merged", "Resolved"),
    ("basic", "draft", "To Do"), ("basic", "in-flight", "Doing"), ("basic", "merged", "Done")])
def test_other_processes_resolve_their_own_state_names(stem, status, expected):
    schema = synthetic_schema(stem)
    spec_type, _ = asm.resolve_type(schema, "spec", {})
    assert asm.resolve_state(schema, spec_type, status, {})[0] == expected


# --- refused fields --------------------------------------------------------------------------------

def test_refused_fields_cover_every_scheduling_field_and_the_effort_field():
    schema = agile_schema()
    refused = asm.refused_fields(schema)
    assert isinstance(refused, frozenset)
    scheduling = {r for r in schema["fields"] if r.startswith("Microsoft.VSTS.Scheduling.")}
    assert scheduling and scheduling <= refused
    assert schema["backlog"]["effort_field"] in refused
    assert "System.Title" not in refused and "Custom.RiskTier" not in refused
    custom = json.loads(json.dumps(schema))
    custom["backlog"]["effort_field"] = "Custom.Points"
    assert "Custom.Points" in asm.refused_fields(custom)
    bare = json.loads(json.dumps(schema))
    bare["fields"], bare["backlog"] = {}, None
    assert "Microsoft.VSTS.Scheduling.StoryPoints" in asm.refused_fields(bare)


# --- fit_levels ------------------------------------------------------------------------------------

def test_fit_on_the_agile_process_falls_back_to_areas_and_tags():
    fit = asm.fit_levels(agile_schema(), {"tree": {"domains": DOMAINS}})
    assert list(fit) == list(TREE_ORDER)
    assert all(set(v) >= {"mode", "type", "level", "reason"} for v in fit.values())
    assert fit["requirement"]["mode"] == "tag" and fit["requirement"]["type"] is None
    assert "no portfolio level 1 above Epic" in fit["requirement"]["reason"] and "fr:<id>" in fit["requirement"]["reason"]
    names = fit["domain"]["names"]
    assert sorted(v["mode"] for v in names.values()) == ["area", "area", "area", "tag"]
    assert names["Intake"] == {"mode": "area", "area_path": "Claims\\SDLC\\Intake"}
    assert names["Disputes"] == {"mode": "tag", "area_path": None}
    assert fit["domain"]["mode"] == "area" and "3 of 4" in fit["domain"]["reason"]
    assert fit["outcome"]["mode"] == "tag" and "outcome:<slug>" in fit["outcome"]["reason"]
    assert [(fit[k]["mode"], fit[k]["type"]) for k in ("epic", "feature", "spec")] == [
        ("item", "Epic"), ("item", "Feature"), ("item", "User Story")]


def test_domain_names_match_an_area_node_by_slug_never_the_project_root():
    schema = agile_schema()
    names = asm.fit_levels(schema, {"tree": {"domains": ["intake", "Claims", "Claims Intake"]}})["domain"]["names"]
    assert names["intake"]["mode"] == "area"
    assert names["Claims"]["mode"] == "tag"  # the root is the project, not a division of it
    assert names["Claims Intake"]["mode"] == "tag"
    assert asm.fit_levels(schema, {})["domain"] == {
        "mode": "tag", "type": None, "level": None, "names": {},
        "reason": "no portfolio level 2 above Epic; no domain names given (tree.domains), so domains ride as `domain:<slug>` tags"}


def test_fit_on_a_two_level_process_is_all_items_with_their_level_numbers():
    fit = asm.fit_levels(two_level(), {"types": {"outcome": "Objective"}})
    assert [(fit[k]["mode"], fit[k]["type"], fit[k]["level"]) for k in ("requirement", "domain", "outcome")] == [
        ("item", "Initiative", 1), ("item", "Theme", 2), ("item", "Objective", None)]
    assert fit["outcome"]["reason"] == "types.outcome pinned: Objective"
    assert "portfolio level 1 above Epic (Initiatives)" in fit["requirement"]["reason"]
    assert fit["domain"]["names"] == {}
    assert [(fit[k]["mode"], fit[k]["type"]) for k in ("epic", "feature", "spec")] == [
        ("item", "Epic"), ("item", "Feature"), ("item", "User Story")]


def test_outcome_without_a_pin_takes_the_third_level_else_a_tag():
    third = asm.fit_levels(two_level(add_pillar=True), {})
    assert (third["outcome"]["mode"], third["outcome"]["type"], third["outcome"]["level"]) == ("item", "Pillar", 3)
    none = asm.fit_levels(two_level(), {})  # an Objective type exists but nobody named it: never guessed
    assert none["outcome"]["mode"] == "tag" and none["outcome"]["type"] is None


def test_a_pinned_type_that_the_process_lacks_is_a_tag_with_the_reason():
    fit = asm.fit_levels(two_level(), {"types": {"outcome": "Goal"}})
    assert fit["outcome"]["mode"] == "tag"
    assert "pins 'Goal'" in fit["outcome"]["reason"]


def test_tree_fit_pins_override_the_automatic_fit():
    pinned = asm.fit_levels(two_level(), {"tree": {"fit": {"requirement": "tag", "domain": "tag"}}})
    assert pinned["requirement"]["mode"] == "tag" and "tree.fit" in pinned["requirement"]["reason"]
    assert pinned["domain"]["mode"] == "tag"
    assert pinned["epic"]["mode"] == "item"  # epic, feature and spec are never pinned away
    area = asm.fit_levels(agile_schema(), {"tree": {"fit": {"domain": "tag"}, "domains": DOMAINS}})
    assert area["domain"]["mode"] == "tag" and {v["mode"] for v in area["domain"]["names"].values()} == {"tag"}
    forced = asm.fit_levels(two_level(), {"tree": {"fit": {"domain": "area"}, "domains": ["Fraud"]}})
    assert forced["domain"]["mode"] == "tag"  # no Area Path node matches, so the pin cannot be met
    wrong = asm.fit_levels(two_level(), {"tree": {"fit": {"requirement": "area"}}})
    assert wrong["requirement"]["mode"] == "tag" and "domain only" in wrong["requirement"]["reason"]
    unmet = asm.fit_levels(agile_schema(), {"tree": {"fit": {"requirement": "item"}}})
    assert unmet["requirement"]["mode"] == "tag" and "pins requirement to item" in unmet["requirement"]["reason"]
    assert asm.fit_levels(agile_schema(), {"tree": {"fit": "auto"}}) == asm.fit_levels(agile_schema(), {})
    assert asm.fit_levels(agile_schema(), {"tree": None, "types": None})["requirement"]["mode"] == "tag"


def test_hidden_levels_and_a_missing_backlog_are_not_levels():
    schema = two_level(hide="Initiatives")
    assert [lv["hidden"] for lv in schema["backlog"]["levels"] if lv["name"] == "Initiatives"] == [True]
    fit = asm.fit_levels(schema, {})
    assert (fit["requirement"]["type"], fit["requirement"]["level"]) == ("Theme", 1)  # the nearest visible level
    schema["backlog"] = None
    fit = asm.fit_levels(schema, {})
    assert fit["requirement"]["mode"] == "tag" and "backlog levels were not discovered" in fit["requirement"]["reason"]
    assert fit["epic"]["mode"] == "item" and fit["epic"]["type"] == "Epic"  # categories still say so


# --- recommendations -------------------------------------------------------------------------------

AGILE_GOLDEN = [
    "outcome: add a work item type for outcomes (for example Objective) and name it in types.outcome, or a third "
    "portfolio backlog level above Epic, so each success dimension is its own board item; until then outcomes ride "
    "as `outcome:<slug>` tags.",
    "domain: add two portfolio backlog levels above Epic (the nearer one holds requirements, the next one holds "
    "domains) so each domain is its own board item; until then domains ride as Area Path nodes where one matches "
    "(3 of 4) and as `domain:<slug>` tags otherwise.",
    "requirement: add a portfolio backlog level above Epic so each FR is its own board item that Epics link to; "
    "until then each FR rides as an `fr:<id>` tag.",
]


def test_recommendations_name_the_process_addition_per_unfitted_kind():
    schema = agile_schema()
    fit = asm.fit_levels(schema, {"tree": {"domains": DOMAINS}})
    assert asm.recommendations(fit, schema) == AGILE_GOLDEN


def test_recommendations_scale_with_the_levels_that_already_exist():
    schema = two_level(drop_top_level=True)
    fit = asm.fit_levels(schema, {"types": {"outcome": "Objective"}})
    sentences = asm.recommendations(fit, schema)
    assert len(sentences) == 1 and sentences[0].startswith(
        "domain: add a second portfolio backlog level above Epic (the nearer one holds requirements)")
    bare = asm.fit_levels(agile_schema(), {})
    assert asm.recommendations(bare, agile_schema())[1].endswith("until then domains ride as `domain:<slug>` tags.")


def test_recommendations_are_empty_when_every_kind_fits_as_an_item():
    schema = two_level()
    fit = asm.fit_levels(schema, {"types": {"outcome": "Objective"}})
    assert asm.recommendations(fit, schema) == []


def test_a_kind_with_no_type_at_all_is_recommended_too():
    schema = synthetic_schema("basic")
    sentences = asm.recommendations(asm.fit_levels(schema, {}), schema)
    assert any(s.startswith("feature: no work item type resolves") and "types.feature" in s for s in sentences)


# --- the module's own discipline --------------------------------------------------------------------

def imported_names():
    names = set()
    for node in ast.walk(ast.parse(MODULE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    return names


def test_the_module_is_pure():
    names = imported_names()
    assert names <= {"re", "typing", "ado_map", "boards_contract"}, names
    assert not names & {"subprocess", "pathlib", "ado_transport", "os", "sys", "json", "tempfile"}


def test_the_module_spells_no_preview_revision_and_joins_no_command():
    text = MODULE.read_text(encoding="utf-8")
    assert not re.search(r"-preview\.\d", text)
    assert not re.search(r"shell=True|shlex\.join", text)
    assert not re.search(r'" "\.join\((args|argv|cmd)', text)
