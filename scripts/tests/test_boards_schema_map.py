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
import yaml

import ado_schema_map as asm
from ado_sync_config import validate_config
from boards_contract import GUID_RE, KINDS, TREE_ORDER
from ado_map import AdoImportError
from tests.ado_boards_fixtures import load_wit as _load_wit


def load_wit(name: str):
    """B0 (2026-10-14): the rules here are pinned on the hand-written Agile process they were written against (its User
    Story has two Proposed states, its areas sit under an `SDLC` node, its `Resolved` state is in the Resolved
    category), so it is read even where a capture now exists. The captured process — a custom `Spec` requirement type,
    `Resolved` in the InProgress category, a hidden User Story — is mapped in test_boards_captured_process.py."""
    return _load_wit(name, hand_written=True)


MODULE = Path(asm.__file__)
STARTER = Path(__file__).resolve().parents[2] / "templates" / "ado" / "ado.yaml"  # the config every project starts from
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


def starter() -> dict:
    return yaml.safe_load(STARTER.read_text(encoding="utf-8"))


def with_states(schema, type_name, *pairs):
    schema["types"][type_name]["states"] = [{"name": n, "category": c, "order": i} for i, (n, c) in enumerate(pairs)]
    return schema


def test_the_starters_prefer_is_honoured_on_the_spec_type():
    cfg = starter()
    assert cfg["states"] == {"spec": {"ready": {"category": "Proposed", "prefer": "Approved"}}}  # design §6.2 shape
    assert validate_config(cfg, None) == []  # the shape resolve_state reads is the one `config check` passes
    schema = with_states(agile_schema(), "User Story",
                         ("New", "Proposed"), ("Approved", "Proposed"), ("Ready", "Proposed"), ("Active", "InProgress"))
    assert asm.resolve_state(schema, "User Story", "ready", cfg) == ("Approved", "prefer: Approved (states.spec.ready)")
    assert asm.resolve_state(schema, "User Story", "ready", {}) == ("Ready", "rule: last-proposed")
    assert asm.resolve_state(schema, "User Story", "draft", cfg) == ("New", "rule: first-proposed")  # no rule for draft
    assert asm.resolve_state(schema, "Epic", "ready", cfg) == (  # not the spec's type
        "New", "rule: last-proposed; states from backlog mapping")


def test_the_old_states_prefer_shape_is_refused_by_config_check_and_is_not_a_rule():
    old = {"version": 1, "states": {"prefer": {"ready": "Active"}}}
    (row,) = validate_config(old, None)
    assert row["level"] == "refused" and "states.prefer" in row["message"]
    assert asm.resolve_state(agile_schema(), "User Story", "ready", old) == ("Ready", "rule: last-proposed")


def test_a_prefer_the_type_lacks_falls_back_to_the_rules_category_with_a_note():
    schema = agile_schema()  # User Story: New, Ready (Proposed), Active, Resolved, Closed, Removed — no Approved
    assert asm.resolve_state(schema, "User Story", "ready", starter()) == (
        "Ready", "prefer 'Approved' was not found among the states of User Story; states.spec.ready: last-proposed")


def test_prefer_is_matched_case_insensitively_and_a_prefer_outside_its_category_says_so():
    schema = agile_schema()
    cfg = {"states": {"spec": {"ready": {"category": "Proposed", "prefer": "ready"}}}}
    assert asm.resolve_state(schema, "User Story", "ready", cfg) == ("Ready", "prefer: Ready (states.spec.ready)")
    off = {"states": {"spec": {"ready": {"category": "Proposed", "prefer": "active"}}}}
    assert asm.resolve_state(schema, "User Story", "ready", off) == (
        "Active", "prefer: Active (states.spec.ready); Active is InProgress, not Proposed")


def test_a_category_rule_replaces_the_status_rules_category():
    schema = agile_schema()
    cfg = {"states": {"spec": {"ready": "InProgress", "merged": {"category": "Completed"}, "parked": "Proposed"}}}
    assert asm.resolve_state(schema, "User Story", "ready", cfg) == ("Active", "states.spec.ready: first-inprogress")
    assert asm.resolve_state(schema, "User Story", "merged", {}) == ("Resolved", "rule: first-resolved")
    assert asm.resolve_state(schema, "User Story", "merged", cfg) == ("Closed", "states.spec.merged: first-completed")
    assert asm.resolve_state(schema, "User Story", "parked", cfg) == ("New", "states.spec.parked: first-proposed")
    lower = {"states": {"spec": {"ready": "proposed"}}}  # the status rule's own pick for that category
    assert asm.resolve_state(schema, "User Story", "ready", lower) == ("Ready", "states.spec.ready: last-proposed")


def test_a_category_the_type_lacks_is_not_replaced_by_the_status_rule():
    schema = agile_schema()
    cfg = {"types": {"finding": "Bug"}, "states": {"finding": {"merged": "Removed"}}}
    assert asm.resolve_state(schema, "Bug", "merged", {}) == ("Resolved", "rule: first-resolved")
    assert asm.resolve_state(schema, "Bug", "merged", cfg) == (None, "Bug has no Removed state (states.finding.merged)")


def test_a_rule_applies_to_the_type_its_kind_resolves_to_and_to_no_other():
    schema = agile_schema(all_states=True)
    cfg = {"types": {"decision": "Issue"},
           "states": {"spec": {"ready": "InProgress"}, "decision": {"decided": {"category": "Completed", "prefer": "Closed"}}}}
    assert asm.resolve_state(schema, "User Story", "ready", cfg)[0] == "Active"  # spec -> RequirementCategory default
    assert asm.resolve_state(schema, "Epic", "ready", cfg) == ("New", "rule: last-proposed")
    assert asm.resolve_state(schema, "Issue", "decided", cfg) == ("Closed", "prefer: Closed (states.decision.decided)")
    moved = {"types": {"spec": "Task"}, "states": {"spec": {"ready": "InProgress"}}}  # the rule follows the pin
    assert asm.resolve_state(schema, "Task", "ready", moved) == (  # Task is also TaskCategory's default (spike)
        "Active", "states.spec.ready: first-inprogress; Task is pinned by types.spec and is also the default type "
                  "for spike; the pin is more specific")
    assert asm.resolve_state(schema, "User Story", "ready", moved) == ("Ready", "rule: last-proposed")
    fitted = {"states": {"requirement": {"ready": "InProgress"}}}  # a tree kind's type comes from the fit
    assert asm.resolve_state(two_level(), "Initiative", "ready", fitted) == (
        "Active", "states.requirement.ready: first-inprogress")
    mapped = {"types": {"spike": "Task"}, "states": {"spike": {"ready": "InProgress"}}}
    assert asm.resolve_state(agile_schema(), "Task", "ready", mapped) == (
        "Active", "states.spike.ready: first-inprogress; states from backlog mapping")


def test_two_kinds_on_one_type_whose_rules_disagree_are_not_guessed():
    schema = agile_schema()
    cfg = {"types": {"decision": "Issue", "question": "Issue"},
           "states": {"decision": {"open": "Completed"}, "question": {"open": "Proposed"}}}
    assert asm.resolve_state(schema, "Issue", "open", cfg) == (
        None, "states.decision.open and states.question.open apply to Issue and disagree; pass a config whose "
              "`states` holds only the kind being resolved")
    scoped = {**cfg, "states": {"question": cfg["states"]["question"]}}  # the caller knows the kind
    assert asm.resolve_state(schema, "Issue", "open", scoped) == ("Active", "states.question.open: first-proposed")
    agree = {**cfg, "states": {"decision": {"open": "Completed"}, "question": {"open": "completed"}}}
    assert asm.resolve_state(schema, "Issue", "open", agree) == ("Closed", "states.decision.open: first-completed")


def test_the_shipped_starter_read_with_safe_load_resolves_ready_to_its_prefer():
    cfg = yaml.safe_load(STARTER.read_text(encoding="utf-8"))  # templates/ado/ado.yaml, exactly as shipped
    assert "spec" not in cfg["types"]  # the starter pins no spec type: spec is found as RequirementCategory's default
    schema = with_states(agile_schema(), "User Story", ("New", "Proposed"), ("Approved", "Proposed"), ("Ready", "Proposed"))
    state, why = asm.resolve_state(schema, "User Story", "ready", cfg)
    assert (state, why) == ("Approved", "prefer: Approved (states.spec.ready)") and "prefer" in why
    assert asm.resolve_state(schema, "User Story", "ready", {}) == ("Ready", "rule: last-proposed")  # without it
    pinned = {**cfg, "types": {**cfg["types"], "spec": "user story"}}  # a pin naming the same type, any case
    assert asm.resolve_state(schema, "User Story", "ready", pinned) == ("Approved", "prefer: Approved (states.spec.ready)")


def test_an_unknown_prefer_name_falls_back_to_the_rule_and_says_it_was_not_found():
    schema = with_states(agile_schema(), "User Story", ("New", "Proposed"), ("Approved", "Proposed"), ("Ready", "Proposed"))
    cfg = {"states": {"spec": {"ready": {"category": "Proposed", "prefer": "Greenlit"}}}}
    assert asm.resolve_state(schema, "User Story", "ready", cfg) == (
        "Ready", "prefer 'Greenlit' was not found among the states of User Story; states.spec.ready: last-proposed")
    bare = {"states": {"spec": {"ready": {"prefer": "Greenlit"}}}}  # no category: the status rule's own fallback
    assert asm.resolve_state(schema, "User Story", "ready", bare) == (
        "Ready", "prefer 'Greenlit' was not found among the states of User Story; rule: last-proposed")
    draft = {"states": {"spec": {"draft": {"category": "Proposed", "prefer": "Greenlit"}}}}
    assert asm.resolve_state(schema, "User Story", "draft", draft) == (
        "New", "prefer 'Greenlit' was not found among the states of User Story; states.spec.draft: first-proposed")


def test_the_kind_of_a_type_comes_from_the_pins_then_the_category_defaults():
    schema = agile_schema(all_states=True)
    assert asm.resolve_state(schema, "Epic", "ready", {"states": {"epic": {"ready": "InProgress"}}}) == (
        "Active", "states.epic.ready: first-inprogress")  # EpicCategory -> epic
    assert asm.resolve_state(schema, "Feature", "ready", {"states": {"feature": {"ready": "InProgress"}}}) == (
        "Active", "states.feature.ready: first-inprogress")  # FeatureCategory -> feature
    assert asm.resolve_state(schema, "Task", "ready", {"states": {"spike": {"ready": "InProgress"}}}) == (
        "Active", "states.spike.ready: first-inprogress")  # TaskCategory -> spike
    assert asm.resolve_state(schema, "Bug", "merged", {"states": {"finding": {"merged": "Completed"}}}) == (
        "Closed", "states.finding.merged: first-completed")  # BugCategory -> finding
    assert asm.resolve_type(schema, "spike", {})[0] is None  # a state rule never gives spike a type of its own
    elsewhere = {"types": {"spike": "Issue"}, "states": {"spike": {"ready": "Completed"}}}  # pinned away from Task
    assert asm.resolve_state(schema, "Task", "ready", elsewhere) == ("New", "rule: last-proposed")
    assert asm.resolve_state(schema, "Issue", "ready", elsewhere) == ("Closed", "states.spike.ready: first-completed")


def test_a_pin_is_more_specific_than_a_category_default_and_the_reason_says_so():
    schema = with_states(agile_schema(), "User Story", ("New", "Proposed"), ("Approved", "Proposed"),
                         ("Ready", "Proposed"), ("Active", "InProgress"))
    both = {"types": {"decision": "User Story"},
            "states": {"spec": {"ready": {"category": "Proposed", "prefer": "Approved"}}, "decision": {"ready": "InProgress"}}}
    assert asm.resolve_state(schema, "User Story", "ready", both) == (
        "Active", "states.decision.ready: first-inprogress; User Story is pinned by types.decision and is also the "
                  "default type for spec; the pin is more specific, so states.spec.ready is not applied")
    only_default = {"types": {"decision": "User Story"}, "states": {"spec": both["states"]["spec"]}}
    assert asm.resolve_state(schema, "User Story", "ready", only_default) == (
        "Ready", "rule: last-proposed; User Story is pinned by types.decision and is also the default type for spec; "
                 "the pin is more specific, so states.spec.ready is not applied")
    also_pinned = {**only_default, "types": {"decision": "User Story", "spec": "User Story"}}  # two pins, one rule
    assert asm.resolve_state(schema, "User Story", "ready", also_pinned) == ("Approved", "prefer: Approved (states.spec.ready)")


@pytest.mark.parametrize("cfg", [
    {"states": "Proposed"}, {"states": {"spec": "Proposed"}}, {"states": {"spec": {"ready": [1]}}},
    {"states": {"spec": {"ready": {"category": None, "prefer": 3}}}}, {"states": {"nfr": {"ready": "InProgress"}}}],
    ids=["states-not-a-map", "kind-not-a-map", "rule-a-list", "rule-wrong-typed", "kind-outside-KINDS"])
def test_a_wrong_typed_state_rule_reads_as_not_set(cfg):
    assert asm.resolve_state(agile_schema(), "User Story", "ready", cfg) == ("Ready", "rule: last-proposed")


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
    assert fit["requirement"]["mode"] == "unknown" and "backlog levels were not discovered" in fit["requirement"]["reason"]
    assert fit["epic"]["mode"] == "item" and fit["epic"]["type"] == "Epic"  # categories still say so


def test_backlog_levels_never_read_make_the_tree_kinds_unknown_never_a_fallback():
    schema = agile_schema()
    schema["backlog"] = None  # no --team, no `team`, no default team: backlogconfiguration was never read
    fit = asm.fit_levels(schema, {"tree": {"domains": DOMAINS}})
    for kind in ("requirement", "domain", "outcome"):
        assert {k: fit[kind][k] for k in ("mode", "type", "level", "reason")} == {
            "mode": "unknown", "type": None, "level": None, "reason": LEVELS_UNREAD}, kind
    assert fit["domain"]["names"] == {n: {"mode": "unknown", "area_path": None} for n in DOMAINS}
    assert [(fit[k]["mode"], fit[k]["type"]) for k in ("epic", "feature", "spec")] == [
        ("item", "Epic"), ("item", "Feature"), ("item", "User Story")]
    assert asm.resolve_type(schema, "requirement", {}) == (
        None, f"it is not known whether requirement is an item on this process: {LEVELS_UNREAD}")
    pinned = asm.fit_levels(schema, {"tree": {"fit": {"requirement": "item", "domain": "area", "outcome": "tag"},
                                              "domains": DOMAINS}})
    assert pinned["requirement"] == {"mode": "unknown", "type": None, "level": None,
                                     "reason": f"tree.fit pins requirement to item, but {LEVELS_UNREAD}"}
    assert pinned["domain"]["mode"] == "area" and pinned["outcome"]["mode"] == "tag"  # these need no levels
    typed = two_level()
    typed["backlog"] = None
    fit = asm.fit_levels(typed, {"types": {"outcome": "Objective", "requirement": "Initiative"}})
    assert [(fit[k]["mode"], fit[k]["type"], fit[k]["level"]) for k in ("outcome", "requirement", "domain")] == [
        ("item", "Objective", None), ("item", "Initiative", None), ("unknown", None, None)]  # a pin needs no level


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


LEVELS_UNREAD = ("backlog levels were not discovered — pass --team or set `team` in .sdlc/ado.yaml so discover can "
                 "read them")
UNREAD_GOLDEN = (
    f"outcome, domain, requirement: {LEVELS_UNREAD}; until then it is not known whether this process has portfolio "
    "backlog levels above Epic to hold these kinds as board items, so no process addition is recommended.")
NUMBERED_ADDITION = re.compile(r"add (two|a second|a) portfolio backlog level|third portfolio backlog level")


def test_backlog_levels_never_read_are_one_sentence_and_never_a_count_of_none():
    schema = agile_schema()
    schema["backlog"] = None  # no --team, no `team`, no default team: backlogconfiguration was never read
    sentences = asm.recommendations(asm.fit_levels(schema, {"tree": {"domains": DOMAINS}}), schema)
    assert sentences == [UNREAD_GOLDEN]
    read = asm.recommendations(asm.fit_levels(agile_schema(), {"tree": {"domains": DOMAINS}}), agile_schema())
    assert all(NUMBERED_ADDITION.search(s) for s in read)  # a read that found 0 levels above Epic still counts them


def test_backlog_levels_never_read_leave_the_other_sentences_where_they_were():
    schema = two_level()
    schema["backlog"] = None
    fit = asm.fit_levels(schema, {"types": {"outcome": "Objective"}, "tree": {"domains": ["A", "B"]}})
    (sentence,) = asm.recommendations(fit, schema)  # outcome is an item through its pin; it waits on no level
    assert sentence.startswith(f"domain, requirement: {LEVELS_UNREAD}; ")
    assert "these kinds" in sentence and "--team" in sentence and "`team` in .sdlc/ado.yaml" in sentence
    assert not NUMBERED_ADDITION.search(sentence)
    fit = asm.fit_levels(schema, {"types": {"outcome": "Nope"}})
    first, second = asm.recommendations(fit, schema)
    assert first.startswith("outcome: not fitted as an item (types.outcome pins 'Nope'")
    assert second.startswith(f"domain, requirement: {LEVELS_UNREAD}; ")
    assert second.endswith("so no process addition is recommended.") and not NUMBERED_ADDITION.search(second)
    only = asm.recommendations({"requirement": fit["requirement"]}, schema)
    assert len(only) == 1 and only[0].startswith(f"requirement: {LEVELS_UNREAD}; ") and "this kind" in only[0]
    basic = synthetic_schema("basic")  # no backlog read and no FeatureCategory: the type gap keeps its own sentence
    sentences = asm.recommendations(asm.fit_levels(basic, {}), basic)
    assert sentences[0] == UNREAD_GOLDEN
    assert any(s.startswith("feature: no work item type resolves") for s in sentences[1:])


def test_backlog_levels_never_read_give_exactly_one_sentence_naming_team_and_no_count():
    schema = agile_schema()
    schema["backlog"] = None
    sentences = asm.recommendations(asm.fit_levels(schema, {}), schema)
    assert sentences == [UNREAD_GOLDEN]
    (sentence,) = sentences
    assert "--team" in sentence and "set `team` in .sdlc/ado.yaml" in sentence
    assert not NUMBERED_ADDITION.search(sentence) and not re.search(r"\d", sentence)  # no level count, not even 0
    read = agile_schema()  # the same process with its backlog read keeps the numbered additions
    assert asm.recommendations(asm.fit_levels(read, {"tree": {"domains": DOMAINS}}), read) == AGILE_GOLDEN


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
