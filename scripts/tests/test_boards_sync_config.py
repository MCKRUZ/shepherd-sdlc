"""The Azure Boards mirror's config file: `.sdlc/ado.yaml` and the code that guards it (B1-P3).

`templates/ado/ado.yaml` is the starter every project begins from (the whole key set, including
`comments:` and `discussion:`); `templates/ado/_schema.yaml` is its JSON Schema; and
`ado_sync_config.py` loads, validates and initialises it. `validate_config(cfg, schema)` answers
with one row per finding and never raises:

  refused       a setting that is unsafe or not known (an unknown key, a forbidden activity-metric
                field, free text switched on without a named reviewer, a value outside its enum or
                range). The CLI maps it to exit 2.
  unresolvable  a pin the discovered process cannot honour (a type or a state it does not have).
                Only produced when a schema is given. Exit 1.
  invalid       the file is missing, is not YAML, or a key has the wrong type. Exit 1.

Nothing here spawns anything: the only I/O is the repository's `.sdlc/` folder under `tmp_path`.
No fixture holds an e-mail address, a GUID or comment text, and no reviewer is a real person.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401

import ast
import copy
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

import ado_sync_config as cfgmod
import boards_contract as bc
from ado_sync_config import ConfigError, init_config, load_config, validate_config, write_hook_status
from sprint_model import SPRINT_ID_RE

ROOT = Path(__file__).resolve().parents[2]
STARTER = ROOT / "templates" / "ado" / "ado.yaml"
SHAPE = ROOT / "templates" / "ado" / "_schema.yaml"
MODULE = Path(cfgmod.__file__)

EVENT_NAMES = ("handoff", "spec_deferred", "decision_resolved", "sprint_carried", "gate_passed",
               "verdict_recorded", "finding_disposition", "sprint_dropped", "review_summary", "pr_linked",
               "spec_merged")

# The design's section 6.2, as the parsed starter must read (YAML 1.1 reads a bare on/off as a boolean).
SECTION_6_2 = {
    "version": 1,
    "team": "Claims Team",
    "area_path": "Claims\\SDLC",
    "posture": "plan-only",
    "description_mode": "link",
    "pii_reviewed_by": None,
    "limits": {"writes_per_run": 50, "first_seed": 20},
    "kinds": ["outcome", "domain", "requirement", "epic", "feature", "spec", "spike", "sprint", "decision"],
    "types": {"outcome": "Objective", "domain": "Domain", "requirement": "Domain Requirement",
              "decision": "Issue"},
    "states": {"spec": {"ready": {"category": "Proposed", "prefer": "Approved"}}},
    "fields": {"spec": {"risk": {"field": "Custom.RiskTier",
                                 "values": {"HIGH": "High", "MEDIUM": "Medium", "LOW": "Low"}},
                        "channel": "Custom.Channel"}},
    "identity_field": None,
    "iterations": {"S07": "Claims\\Sprint 7"},
    "tree": {"fit": "auto", "outcome_edge": "related", "spec_traces": False,
             "domain_outcomes": {"claims-intake": ["1-turnaround-time"],
                                 "price-bands": ["1-turnaround-time", "2-margin-consistency"]}},
    "comments": {"transport": "comments-api", "format": "markdown", "trailer": "hash", "include_text": False,
                 "per_item_budget": 50, "max_chars": 4000, "mention_lookup": "cache",
                 "identity_scope_acknowledged_by": None,
                 "events": {"handoff": True, "spec_deferred": True, "decision_resolved": True,
                            "sprint_carried": True, "gate_passed": False, "verdict_recorded": False,
                            "finding_disposition": False, "sprint_dropped": False, "review_summary": False,
                            "pr_linked": False, "spec_merged": False}},
    "discussion": {"enabled": True, "retain_days": 90, "max_comments_per_item": 300, "max_items_per_pull": 50,
                   "mention_window_days": 14, "directive_scan": True},
}


# --- helpers -----------------------------------------------------------------------------------------

def starter() -> dict:
    return yaml.safe_load(STARTER.read_text(encoding="utf-8"))


DELETE = object()


def edit(cfg: dict, **paths) -> dict:
    """A deep copy of `cfg` with nested keys set; `__` separates the levels (`comments__trailer="x"`
    sets `comments.trailer`). A value of `DELETE` removes the key."""
    out = copy.deepcopy(cfg)
    for path, value in paths.items():
        *parents, leaf = path.split("__")
        node = out
        for p in parents:
            node = node.setdefault(p, {})
        if value is DELETE:
            node.pop(leaf, None)
        else:
            node[leaf] = value
    return out


def levels(rows) -> list[str]:
    return [r["level"] for r in rows]


def type_entry(*states, fields=None, disabled=False):
    return {"reference_name": "x", "disabled": disabled,
            "states": [{"name": n, "category": c, "order": i} for i, (n, c) in enumerate(states, 1)] or None,
            "fields": fields}


def make_schema(**overrides) -> dict:
    """The document `.sdlc/ado/schema.json` holds (the shape `ado_schema_map.build_schema` returns)."""
    schema = {
        "schema_version": 1,
        "types": {
            "Epic": type_entry(("New", "Proposed"), ("Active", "InProgress"), ("Closed", "Completed")),
            "Feature": type_entry(("New", "Proposed"), ("Active", "InProgress"), ("Closed", "Completed")),
            "User Story": type_entry(
                ("New", "Proposed"), ("Approved", "Proposed"), ("Active", "InProgress"), ("Closed", "Completed"),
                fields={"Custom.RiskTier": {"allowed_values": ["High", "Medium", "Low"]},
                        "Custom.Channel": {"allowed_values": None},
                        "Microsoft.VSTS.Scheduling.StoryPoints": {"allowed_values": None}}),
            "Issue": type_entry(("To Do", "Proposed"), ("Doing", "InProgress"), ("Done", "Completed")),
            "Objective": type_entry(("New", "Proposed"), ("Done", "Completed")),
            "Domain": type_entry(("New", "Proposed"), ("Done", "Completed")),
            "Domain Requirement": type_entry(("New", "Proposed"), ("Done", "Completed")),
        },
        "categories": {"RequirementCategory": {"default_type": "User Story", "types": ["User Story"]},
                       "EpicCategory": {"default_type": "Epic", "types": ["Epic"]},
                       "FeatureCategory": {"default_type": "Feature", "types": ["Feature"]}},
        "fields": {},
        "backlog": {"effort_field": "Custom.EffortPoints"},
    }
    schema.update(overrides)
    return schema


# --- the starter -------------------------------------------------------------------------------------

def test_the_starter_is_the_design_section_6_2_key_set():
    assert starter() == SECTION_6_2


def test_the_starter_validates_clean_with_no_schema():
    assert validate_config(starter(), None) == []


def test_the_starter_validates_clean_against_the_json_schema_itself():
    errors = list(jsonschema.Draft202012Validator(yaml.safe_load(SHAPE.read_text(encoding="utf-8")))
                  .iter_errors(starter()))
    assert errors == []


def test_the_starter_validates_clean_against_a_process_that_has_what_it_pins():
    assert validate_config(starter(), make_schema()) == []


def test_the_shape_file_is_itself_a_valid_json_schema():
    schema = yaml.safe_load(SHAPE.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["type"] == "object" and schema["additionalProperties"] is False


def test_the_shape_file_name_keeps_it_out_of_the_shape_template_guard():
    assert SHAPE.name.startswith("_") and not SHAPE.name.endswith(".shape.yaml")


def test_the_shape_closes_the_same_sets_the_contract_and_the_design_name():
    schema = yaml.safe_load(SHAPE.read_text(encoding="utf-8"))
    assert set(schema["$defs"]["kind_name"]["enum"]) == set(bc.KINDS) | {"nfr"}
    assert list(schema["properties"]["comments"]["properties"]["events"]["properties"]) == list(EVENT_NAMES)
    assert schema["properties"]["iterations"]["propertyNames"]["pattern"] == SPRINT_ID_RE.pattern


def test_the_starter_holds_no_identity_url_or_preview_version():
    text = STARTER.read_text(encoding="utf-8")
    assert not bc.EMAIL_RE.search(text) and not bc.GUID_RE.search(text)
    assert "http" not in text and "-preview" not in text


# --- refusals: one row per finding, a plain sentence naming the key ---------------------------------

REFUSED = [
    pytest.param(dict(bogus=1), "bogus", id="unknown-top-level-key"),
    pytest.param(dict(comments__bogus=1), "comments.bogus", id="unknown-nested-key"),
    pytest.param(dict(limits__bogus=1), "limits.bogus", id="unknown-limits-key"),
    pytest.param(dict(tree__bogus=True), "tree.bogus", id="unknown-tree-key"),
    pytest.param(dict(discussion__bogus=True), "discussion.bogus", id="unknown-discussion-key"),
    pytest.param(dict(types__widget="Task"), "types.widget", id="unknown-kind-under-types"),
    pytest.param(dict(states__widget={"ready": "Proposed"}), "states.widget", id="unknown-kind-under-states"),
    pytest.param(dict(fields__widget={"x": "Custom.X"}), "fields.widget", id="unknown-kind-under-fields"),
    pytest.param(dict(states__spec__ready__bogus="x"), "states.spec.ready.bogus", id="unknown-state-rule-key"),
    pytest.param(dict(fields__spec__risk__bogus="x"), "fields.spec.risk.bogus", id="unknown-field-rule-key"),
    pytest.param(dict(comments__events__shouted="on"), "comments.events.shouted", id="unknown-comment-event"),
    pytest.param(dict(kinds=SECTION_6_2["kinds"] + ["widget"]), "kinds", id="kind-outside-the-closed-set"),
    pytest.param(dict(description_mode="full"), "pii_reviewed_by", id="full-descriptions-without-a-reviewer"),
    pytest.param(dict(description_mode="full", pii_reviewed_by=""), "pii_reviewed_by", id="blank-reviewer"),
    pytest.param(dict(description_mode="full", pii_reviewed_by="   "), "pii_reviewed_by", id="whitespace-reviewer"),
    pytest.param(dict(comments__include_text=True), "comments.include_text", id="comment-text-without-a-reviewer"),
    pytest.param(dict(comments__trailer="stamp"), "comments.trailer", id="trailer-outside-its-enum"),
    pytest.param(dict(comments__transport="rest"), "comments.transport", id="transport-outside-its-enum"),
    pytest.param(dict(comments__format="rtf"), "comments.format", id="format-outside-its-enum"),
    pytest.param(dict(comments__mention_lookup="directory"), "comments.mention_lookup", id="lookup-outside-its-enum"),
    pytest.param(dict(tree__outcome_edge="child"), "tree.outcome_edge", id="outcome-edge-outside-its-enum"),
    pytest.param(dict(tree__fit="manual"), "tree.fit", id="fit-a-string-other-than-auto"),
    pytest.param(dict(tree__fit={"domain": "ledger"}), "tree.fit.domain", id="fit-mode-outside-its-enum"),
    pytest.param(dict(tree__fit={"outcome": "area"}), "tree.fit.outcome", id="outcome-cannot-fit-as-an-area"),
    pytest.param(dict(tree__fit={"requirement": "area"}), "tree.fit.requirement", id="requirement-cannot-fit-as-an-area"),
    pytest.param(dict(tree__fit={"epic": "item"}), "tree.fit.epic", id="only-the-requirements-tree-is-fitted"),
    pytest.param(dict(posture="autonomous"), "posture", id="posture-outside-its-enum"),
    pytest.param(dict(description_mode="body"), "description_mode", id="description-mode-outside-its-enum"),
    pytest.param(dict(comments__per_item_budget=0), "comments.per_item_budget", id="budget-below-1"),
    pytest.param(dict(comments__per_item_budget=1001), "comments.per_item_budget", id="budget-above-1000"),
    pytest.param(dict(comments__max_chars=100001), "comments.max_chars", id="max-chars-above-100000"),
    pytest.param(dict(comments__mention_lookup="identities"), "identity_scope_acknowledged_by",
                 id="identity-lookup-without-an-acknowledger"),
    pytest.param(dict(comments__mention_lookup="identities", comments__identity_scope_acknowledged_by=" "),
                 "identity_scope_acknowledged_by", id="identity-lookup-with-a-blank-acknowledger"),
    pytest.param(dict(comments__events__handoff="maybe"), "comments.events.handoff", id="event-value-not-on-off"),
    pytest.param(dict(comments__events__gate_passed=5), "comments.events.gate_passed", id="event-value-a-number"),
    pytest.param(dict(discussion__directive_scan="sometimes"), "discussion.directive_scan", id="scan-not-on-off"),
    pytest.param(dict(version=2), "version", id="a-config-version-this-plugin-does-not-read"),
    pytest.param(dict(iterations__seven="Claims\\Sprint 7"), "iterations", id="iteration-key-not-a-sprint-id"),
    pytest.param(dict(limits__writes_per_run=-1), "limits.writes_per_run", id="negative-limit"),
    # forbidden activity metrics: the key, the target, the target's last segment, the scheduling prefix
    pytest.param(dict(fields__spec__points="Custom.Points"), "fields.spec.points", id="activity-metric-as-the-key"),
    pytest.param(dict(fields__spec__estimate="Custom.Anything"), "fields.spec.estimate", id="estimate-as-the-key"),
    pytest.param(dict(fields__spec__size="Effort"), "fields.spec.size", id="effort-as-the-target"),
    pytest.param(dict(fields__spec__size="Custom.Effort"), "fields.spec.size", id="effort-as-the-last-segment"),
    pytest.param(dict(fields__spec__size="Custom.Story Points"), "fields.spec.size", id="story-points-last-segment"),
    pytest.param(dict(fields__spec__size="Microsoft.VSTS.Scheduling.StoryPoints"), "fields.spec.size",
                 id="scheduling-field-string-form"),
    pytest.param(dict(fields__spec__size={"field": "microsoft.vsts.scheduling.OriginalEstimate"}),
                 "fields.spec.size.field", id="scheduling-field-mapping-form-any-case"),
    pytest.param(dict(fields__spec__size={"field": "Custom.Velocity"}), "fields.spec.size.field",
                 id="velocity-mapping-form"),
]


@pytest.mark.parametrize("changes, key", REFUSED)
def test_each_refusal_is_one_refused_row_naming_the_key(changes, key):
    rows = validate_config(edit(starter(), **changes), None)
    assert levels(rows) == ["refused"], rows
    message = rows[0]["message"]
    assert key in message and message.endswith(".") and "\n" not in message
    assert set(rows[0]) == {"level", "message"}


def test_two_independent_findings_are_two_rows():
    rows = validate_config(edit(starter(), bogus=1, comments__include_text=True, posture="x"), None)
    assert levels(rows) == ["refused"] * 3
    assert len({r["message"] for r in rows}) == 3


def test_every_unknown_top_level_key_is_its_own_row():
    rows = validate_config(edit(starter(), one=1, two=2), None)
    assert levels(rows) == ["refused", "refused"]
    assert any("`one`" in r["message"] for r in rows) and any("`two`" in r["message"] for r in rows)


def test_an_unknown_key_row_lists_what_is_allowed_there():
    (row,) = validate_config(edit(starter(), comments__trailer_x=1), None)
    assert "trailer" in row["message"] and "max_chars" in row["message"]
    (event,) = validate_config(edit(starter(), comments__events__shouted="on"), None)
    assert "comment event" in event["message"] and "handoff" in event["message"]


def test_full_descriptions_are_fine_with_a_named_reviewer():
    cfg = edit(starter(), description_mode="full", pii_reviewed_by="@reviewer")
    assert validate_config(cfg, None) == []


def test_comment_text_is_fine_with_a_named_reviewer():
    cfg = edit(starter(), comments__include_text=True, pii_reviewed_by="@reviewer")
    assert validate_config(cfg, None) == []


def test_identity_lookup_is_fine_with_a_named_acknowledger():
    cfg = edit(starter(), comments__mention_lookup="identities", comments__identity_scope_acknowledged_by="@lead")
    assert validate_config(cfg, None) == []


def test_every_bound_of_the_ranges_is_accepted():
    for budget in (1, 1000):
        assert validate_config(edit(starter(), comments__per_item_budget=budget), None) == []
    assert validate_config(edit(starter(), comments__max_chars=100000), None) == []


def test_every_enum_value_is_accepted():
    for key, values in {"posture": ("plan-only", "assisted"), "description_mode": ("link",),
                        "comments__trailer": ("none", "hash", "drafted"),
                        "comments__transport": ("comments-api", "history"),
                        "comments__format": ("markdown", "html"), "comments__mention_lookup": ("cache",),
                        "tree__outcome_edge": ("related", "parent")}.items():
        for value in values:
            assert validate_config(edit(starter(), **{key: value}), None) == [], (key, value)


def test_tree_fit_pins_are_accepted():
    for fit in ("auto", {}, {"outcome": "item", "domain": "area", "requirement": "tag"}, {"domain": "tag"}):
        assert validate_config(edit(starter(), tree__fit=fit), None) == [], fit


def test_on_off_are_accepted_as_words_or_booleans():
    cfg = edit(starter(), comments__events__handoff="on", comments__events__gate_passed="off",
               discussion__directive_scan="off")
    assert validate_config(cfg, None) == []


def test_all_kinds_the_design_names_are_accepted():
    kinds = ["outcome", "domain", "requirement", "epic", "feature", "spec", "spike", "sprint", "decision",
             "finding", "lifecycle", "nfr", "rule", "question", "measurement"]
    assert validate_config(edit(starter(), kinds=kinds), None) == []


def test_a_field_may_map_through_either_form_to_a_non_metric():
    cfg = edit(starter(), fields__spec__owner_note="Custom.Note", fields__epic__lane={"field": "Custom.Lane"})
    assert validate_config(cfg, None) == []


def test_a_scheduling_field_and_an_activity_metric_are_told_apart():
    (scheduling,) = validate_config(edit(starter(), fields__spec__size="Microsoft.VSTS.Scheduling.StoryPoints"), None)
    (metric,) = validate_config(edit(starter(), fields__spec__size="Effort"), None)
    assert "scheduling field" in scheduling["message"] and "activity metric" in metric["message"]


def test_a_forbidden_field_gets_one_row_even_when_key_and_target_both_name_a_metric():
    rows = validate_config(edit(starter(), fields__spec__velocity="Custom.Velocity"), None)
    assert levels(rows) == ["refused"]


# --- invalid: a missing key or a wrong type ---------------------------------------------------------

INVALID = [
    pytest.param(dict(version="1"), "version", id="version-a-string"),
    pytest.param(dict(version=DELETE), "version", id="version-missing"),
    pytest.param(dict(team=5), "team", id="team-a-number"),
    pytest.param(dict(posture=5), "posture", id="posture-a-number"),
    pytest.param(dict(limits=5), "limits", id="limits-a-number"),
    pytest.param(dict(limits__first_seed="twenty"), "limits.first_seed", id="limit-a-string"),
    pytest.param(dict(kinds="spec"), "kinds", id="kinds-a-string"),
    pytest.param(dict(types=["Task"]), "types", id="types-a-list"),
    pytest.param(dict(types__decision=7), "types.decision", id="type-pin-a-number"),
    pytest.param(dict(states__spec__ready=5), "states.spec.ready", id="state-rule-a-number"),
    pytest.param(dict(states__spec__ready={"prefer": "Approved"}), "category", id="state-rule-without-category"),
    pytest.param(dict(fields__spec__risk=5), "fields.spec.risk", id="field-rule-a-number"),
    pytest.param(dict(fields__spec__risk={"values": {"HIGH": "High"}}), "field", id="field-rule-without-field"),
    pytest.param(dict(fields__spec__risk={"field": "Custom.RiskTier", "values": {"HIGH": 1}}),
                 "fields.spec.risk.values.HIGH", id="field-value-a-number"),
    pytest.param(dict(iterations__S07=7), "iterations.S07", id="iteration-path-a-number"),
    pytest.param(dict(tree__spec_traces="yes"), "tree.spec_traces", id="spec-traces-a-string"),
    pytest.param(dict(tree__fit=5), "tree.fit", id="fit-a-number"),
    pytest.param(dict(tree__domain_outcomes={"claims-intake": "1-turnaround-time"}), "tree.domain_outcomes.claims-intake",
                 id="domain-outcomes-a-string"),
    pytest.param(dict(comments__include_text="yes"), "comments.include_text", id="include-text-a-string"),
    pytest.param(dict(comments__per_item_budget="fifty"), "comments.per_item_budget", id="budget-a-string"),
    pytest.param(dict(comments__per_item_budget=50.5), "comments.per_item_budget", id="budget-a-fraction"),
    pytest.param(dict(comments__max_chars=True), "comments.max_chars", id="max-chars-a-boolean"),
    pytest.param(dict(comments__events=["handoff"]), "comments.events", id="events-a-list"),
    pytest.param(dict(comments__trailer=5), "comments.trailer", id="trailer-a-number"),
    pytest.param(dict(discussion__enabled="true"), "discussion.enabled", id="discussion-enabled-a-string"),
    pytest.param(dict(discussion__retain_days="ninety"), "discussion.retain_days", id="retain-days-a-string"),
    pytest.param(dict(comments=None), "comments", id="comments-null"),
]


@pytest.mark.parametrize("changes, key", INVALID)
def test_a_missing_or_wrong_typed_key_is_one_invalid_row(changes, key):
    rows = validate_config(edit(starter(), **changes), None)
    assert levels(rows) == ["invalid"], rows
    assert key in rows[0]["message"] and rows[0]["message"].endswith(".")


@pytest.mark.parametrize("cfg", [None, [], "version: 1", 7])
def test_a_config_that_is_not_a_mapping_is_invalid_not_a_crash(cfg):
    rows = validate_config(cfg, None)
    assert levels(rows) == ["invalid"] and "mapping" in rows[0]["message"]


def test_a_wrong_type_hides_the_enum_row_it_would_also_trigger():
    # `posture: 5` is both the wrong type and outside the enum; the type is the finding.
    assert levels(validate_config(edit(starter(), posture=5), None)) == ["invalid"]


def test_optional_scalars_may_be_null_or_absent():
    cfg = edit(starter(), team=None, area_path=None, identity_field=None, pii_reviewed_by=None,
               comments__identity_scope_acknowledged_by=None)
    assert validate_config(cfg, None) == []
    minimal = {"version": 1}
    assert validate_config(minimal, None) == []


# --- findings that need the discovered process ------------------------------------------------------

def test_a_type_pin_the_process_lacks_is_unresolvable_and_names_kind_and_candidates():
    schema = make_schema()
    cfg = edit(starter(), types__decision="Impediment")
    rows = validate_config(cfg, schema)
    assert levels(rows) == ["unresolvable"]
    message = rows[0]["message"]
    assert "types.decision" in message and "Impediment" in message and message.endswith(".")
    for candidate in ("Epic", "Issue", "User Story"):
        assert candidate in message
    assert validate_config(cfg, None) == []          # schema-dependent: skipped with no schema


def test_a_type_pin_is_matched_case_insensitively_as_azure_devops_does():
    assert validate_config(edit(starter(), types__decision="issue"), make_schema()) == []


def test_a_disabled_type_is_not_offered_as_a_candidate():
    schema = make_schema()
    schema["types"]["Epic"]["disabled"] = True
    (row,) = validate_config(edit(starter(), types__decision="Nope"), schema)
    assert "Epic" not in row["message"] and "Issue" in row["message"]


def test_a_process_with_no_types_leaves_every_pin_unresolvable():
    rows = validate_config(edit(starter()), make_schema(types={}))
    assert set(levels(rows)) == {"unresolvable"} and len(rows) == 4
    assert "no work item types" in rows[0]["message"]


def test_a_schema_with_no_type_table_skips_the_type_checks():
    assert validate_config(starter(), {"schema_version": 1}) == []


def test_a_prefer_state_the_kinds_type_lacks_is_unresolvable():
    cfg = edit(starter(), states__spec__ready={"category": "Proposed", "prefer": "Greenlit"})
    rows = validate_config(cfg, make_schema())
    assert levels(rows) == ["unresolvable"]
    message = rows[0]["message"]
    assert "states.spec.ready.prefer" in message and "Greenlit" in message and "User Story" in message
    for candidate in ("New", "Approved", "Active", "Closed"):
        assert candidate in message
    assert validate_config(cfg, None) == []


def test_a_prefer_state_is_matched_case_insensitively_and_by_the_pinned_type():
    cfg = edit(starter(), types__spec="Issue", states__spec__ready={"category": "Proposed", "prefer": "to do"})
    assert validate_config(cfg, make_schema()) == []
    cfg = edit(starter(), types__spec="Issue", states__spec__ready={"category": "Proposed", "prefer": "Approved"})
    rows = validate_config(cfg, make_schema())
    assert levels(rows) == ["unresolvable"] and "Issue" in rows[0]["message"]


def test_a_prefer_state_for_a_kind_with_no_known_type_is_checked_against_every_type():
    cfg = edit(starter(), states__spike={"ready": {"category": "Proposed", "prefer": "Doing"}})
    assert validate_config(cfg, make_schema()) == []
    cfg = edit(starter(), states__spike={"ready": {"category": "Proposed", "prefer": "Nowhere"}})
    (row,) = validate_config(cfg, make_schema())
    assert row["level"] == "unresolvable" and "states.spike.ready.prefer" in row["message"]


def test_a_prefer_state_is_skipped_when_the_types_states_were_never_read():
    schema = make_schema()
    schema["types"]["User Story"]["states"] = None
    assert validate_config(starter(), schema) == []


def test_a_category_only_state_rule_needs_no_process_lookup():
    cfg = edit(starter(), states__spec__ready="Proposed")
    assert validate_config(cfg, make_schema()) == []


def test_a_field_the_schema_refuses_is_refused_in_both_forms():
    schema = make_schema(refused_fields=["Custom.Forbidden"])
    for target in ("Custom.Forbidden", {"field": "custom.forbidden"}):
        rows = validate_config(edit(starter(), fields__spec__extra=target), schema)
        assert levels(rows) == ["refused"] and "fields.spec.extra" in rows[0]["message"], rows
    assert validate_config(edit(starter(), fields__spec__extra="Custom.Forbidden"), None) == []


def test_the_backlogs_effort_field_is_refused_whatever_it_is_called():
    schema = make_schema()
    for target in ("Custom.EffortPoints", {"field": "custom.effortpoints"}):
        rows = validate_config(edit(starter(), fields__spec__extra=target), schema)
        assert levels(rows) == ["refused"], rows
        assert "effort" in rows[0]["message"].lower()


def test_a_values_entry_absent_from_the_fields_allowed_values_is_refused():
    cfg = edit(starter(), fields__spec__risk={"field": "Custom.RiskTier", "values": {"HIGH": "High", "LOW": "Tiny"}})
    rows = validate_config(cfg, make_schema())
    assert levels(rows) == ["refused"]
    message = rows[0]["message"]
    assert "fields.spec.risk.values" in message and "Tiny" in message and "Custom.RiskTier" in message
    for allowed in ("High", "Medium", "Low"):
        assert allowed in message
    assert validate_config(cfg, None) == []


def test_each_bad_value_is_its_own_row():
    cfg = edit(starter(), fields__spec__risk={"field": "Custom.RiskTier", "values": {"HIGH": "x", "LOW": "y"}})
    assert levels(validate_config(cfg, make_schema())) == ["refused", "refused"]


def test_allowed_values_follow_the_pinned_type_and_a_field_without_a_picklist_is_not_checked():
    schema = make_schema()
    schema["types"]["Issue"]["fields"] = {"Custom.RiskTier": {"allowed_values": ["Critical"]}}
    cfg = edit(starter(), types__spec="Issue", states__spec__ready="Proposed")
    rows = validate_config(cfg, schema)
    assert levels(rows) == ["refused"] * 3 and "Critical" in rows[0]["message"]
    free = edit(starter(), fields__spec__channel={"field": "Custom.Channel", "values": {"x": "anything"}})
    assert validate_config(free, make_schema()) == []


def test_a_field_the_process_does_not_list_is_not_checked_for_values():
    cfg = edit(starter(), fields__spec__stage={"field": "Custom.Stage", "values": {"a": "b"}})
    assert validate_config(cfg, make_schema()) == []


def test_unresolvable_and_refused_findings_come_back_together():
    cfg = edit(starter(), types__decision="Impediment", bogus=1)
    assert sorted(levels(validate_config(cfg, make_schema()))) == ["refused", "unresolvable"]


def test_a_schema_that_is_not_a_mapping_is_treated_as_no_schema():
    assert validate_config(starter(), "not a schema") == []


# --- load_config -------------------------------------------------------------------------------------

def write_config(repo: Path, text: str) -> Path:
    path = repo / bc.CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_load_config_reads_the_starter(tmp_path):
    write_config(tmp_path, STARTER.read_text(encoding="utf-8"))
    assert load_config(tmp_path) == SECTION_6_2


def test_load_config_on_a_missing_file_is_a_missing_error_naming_the_path(tmp_path):
    with pytest.raises(ConfigError) as caught:
        load_config(tmp_path)
    assert caught.value.kind == "missing" and str(tmp_path / bc.CONFIG_FILE) in str(caught.value)


@pytest.mark.parametrize("text", ["version: [1\n", "a: b: c\n", "\t- x\n", ""], ids=["unclosed", "colon", "tab", "empty"])
def test_load_config_on_a_file_that_is_not_yaml_or_is_empty_is_invalid(tmp_path, text):
    write_config(tmp_path, text)
    with pytest.raises(ConfigError) as caught:
        load_config(tmp_path)
    assert caught.value.kind == "invalid" and bc.CONFIG_FILE in str(caught.value).replace("\\", "/")


@pytest.mark.parametrize("text", ["- a\n- b\n", "just text\n", "42\n"], ids=["list", "scalar", "number"])
def test_load_config_on_a_top_level_that_is_not_a_mapping_is_invalid(tmp_path, text):
    write_config(tmp_path, text)
    with pytest.raises(ConfigError) as caught:
        load_config(tmp_path)
    assert caught.value.kind == "invalid" and "mapping" in str(caught.value)


def test_load_config_on_a_directory_in_its_place_is_invalid_not_a_crash(tmp_path):
    (tmp_path / bc.CONFIG_FILE).mkdir(parents=True)
    with pytest.raises(ConfigError) as caught:
        load_config(tmp_path)
    assert caught.value.kind == "invalid"


def test_load_config_on_bytes_that_are_not_utf8_is_invalid(tmp_path):
    path = write_config(tmp_path, "")
    path.write_bytes(b"version: \xff\xfe\n")
    with pytest.raises(ConfigError) as caught:
        load_config(tmp_path)
    assert caught.value.kind == "invalid"


def test_load_config_does_not_validate(tmp_path):
    write_config(tmp_path, "version: 1\nbogus: 1\n")
    assert load_config(tmp_path) == {"version": 1, "bogus": 1}
    assert levels(validate_config(load_config(tmp_path), None)) == ["refused"]


def test_load_config_echoes_no_file_content_in_a_yaml_error(tmp_path):
    write_config(tmp_path, "pii_reviewed_by: [secret-token\n")
    with pytest.raises(ConfigError) as caught:
        load_config(tmp_path)
    assert "secret-token" not in str(caught.value)


# --- init_config -------------------------------------------------------------------------------------

def test_init_config_copies_the_starter_and_ignores_the_local_folder(tmp_path):
    written = init_config(tmp_path)
    assert written == [tmp_path / bc.CONFIG_FILE, tmp_path / bc.LOCAL_DIR / ".gitignore"]
    assert (tmp_path / bc.CONFIG_FILE).read_bytes() == STARTER.read_bytes()
    assert (tmp_path / bc.LOCAL_DIR / ".gitignore").read_bytes() == b"*\n"
    assert load_config(tmp_path) == SECTION_6_2


def test_init_config_creates_nothing_else(tmp_path):
    init_config(tmp_path)
    files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert files == [".sdlc/ado.yaml", ".sdlc/ado/local/.gitignore"]


def test_a_second_init_config_without_force_raises_invalid_naming_the_existing_file(tmp_path):
    init_config(tmp_path)
    (tmp_path / bc.CONFIG_FILE).write_text("version: 1\n# edited by a person\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        init_config(tmp_path)
    assert caught.value.kind == "invalid" and str(tmp_path / bc.CONFIG_FILE) in str(caught.value)
    assert (tmp_path / bc.CONFIG_FILE).read_text(encoding="utf-8") == "version: 1\n# edited by a person\n"


def test_an_init_config_that_refuses_writes_nothing(tmp_path):
    write_config(tmp_path, "version: 1\n")
    with pytest.raises(ConfigError):
        init_config(tmp_path)
    assert not (tmp_path / bc.LOCAL_DIR).exists()


def test_init_config_with_force_overwrites_and_returns_both_paths(tmp_path):
    init_config(tmp_path)
    (tmp_path / bc.CONFIG_FILE).write_text("version: 1\n", encoding="utf-8")
    (tmp_path / bc.LOCAL_DIR / ".gitignore").write_text("something else\n", encoding="utf-8")
    written = init_config(tmp_path, force=True)
    assert written == [tmp_path / bc.CONFIG_FILE, tmp_path / bc.LOCAL_DIR / ".gitignore"]
    assert (tmp_path / bc.CONFIG_FILE).read_bytes() == STARTER.read_bytes()
    assert (tmp_path / bc.LOCAL_DIR / ".gitignore").read_bytes() == b"*\n"


def test_init_config_after_a_hand_removed_config_recreates_it_without_force(tmp_path):
    init_config(tmp_path)
    (tmp_path / bc.CONFIG_FILE).unlink()
    assert init_config(tmp_path)[0] == tmp_path / bc.CONFIG_FILE


def test_init_config_takes_force_by_keyword_only(tmp_path):
    with pytest.raises(TypeError):
        init_config(tmp_path, True)


def test_init_config_on_an_unwritable_path_is_a_config_error_not_an_oserror(tmp_path):
    blocker = tmp_path / ".sdlc"
    blocker.write_text("a file where the folder should be", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        init_config(tmp_path)
    assert caught.value.kind == "invalid"


def test_the_written_starter_validates_clean(tmp_path):
    init_config(tmp_path)
    assert validate_config(load_config(tmp_path), None) == []


def test_init_config_accepts_a_string_path(tmp_path):
    assert init_config(str(tmp_path))[0] == tmp_path / bc.CONFIG_FILE


# --- write_hook_status -------------------------------------------------------------------------------

def test_write_hook_status_writes_the_line_and_a_newline_creating_the_folders(tmp_path):
    line = "3 rows pending · 1 drifted · as of 2026-10-12T09:02Z"
    write_hook_status(tmp_path, line)
    assert (tmp_path / bc.HOOK_STATUS).read_bytes() == (line + "\n").encode("utf-8")


def test_write_hook_status_replaces_the_previous_line(tmp_path):
    write_hook_status(tmp_path, "first")
    write_hook_status(tmp_path, "no data (never pulled)")
    assert (tmp_path / bc.HOOK_STATUS).read_bytes() == b"no data (never pulled)\n"


def test_write_hook_status_writes_only_the_status_file(tmp_path):
    write_hook_status(tmp_path, "x")
    files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert files == [".sdlc/ado/local/hook-status.txt"]


def test_write_hook_status_uses_a_bare_line_feed_on_every_platform(tmp_path):
    write_hook_status(tmp_path, "x")
    assert b"\r" not in (tmp_path / bc.HOOK_STATUS).read_bytes()


# --- the module itself -------------------------------------------------------------------------------

def test_the_paths_are_the_contracts_not_copies():
    assert cfgmod.CONFIG_FILE is bc.CONFIG_FILE and cfgmod.LOCAL_DIR is bc.LOCAL_DIR
    assert cfgmod.HOOK_STATUS is bc.HOOK_STATUS


def test_the_module_imports_no_process_spawner_and_no_transport():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "functools", "os", "pathlib", "re", "typing", "jsonschema", "yaml",
                        "boards_contract", "sprint_model"}, imported
    assert not imported & {"subprocess", "shlex", "ado_transport", "ado_import", "ado_map", "ado_schema_map"}


def test_the_module_has_no_shell_join_or_preview_version_literal():
    text = MODULE.read_text(encoding="utf-8")
    assert "shell=True" not in text and "shlex" not in text and "-preview" not in text


def test_the_module_spawns_nothing_and_az_stays_forbidden(tmp_path, az):
    init_config(tmp_path)
    validate_config(load_config(tmp_path), make_schema())
    write_hook_status(tmp_path, "x")
    assert az.calls == []


def test_the_validator_does_not_mutate_what_it_is_given():
    cfg, schema = edit(starter(), bogus=1), make_schema()
    before = json.dumps([cfg, schema], sort_keys=True, default=str)
    validate_config(cfg, schema)
    assert json.dumps([cfg, schema], sort_keys=True, default=str) == before


ODD_SHAPES = [
    {"version": 1, "fields": {"spec": {1: 2, "risk": {"field": ["a"], "values": [1]}}}},
    {"version": 1, "states": {"spec": {"ready": [1], "draft": {"prefer": 3, "category": None}}}},
    {"version": 1, "types": {"spec": ["x"], "epic": {"a": 1}}, "kinds": [None, 3, ["x"]]},
    {"version": 1, "iterations": {7: "x", "S07": None}, "tree": {"domain_outcomes": {1: [2]}}},
    {"version": 1, "comments": {"events": {"handoff": [1], 5: "on"}, "mention_lookup": ["identities"]}},
    {"version": 1, "posture": yaml.safe_load("2026-10-13"), "team": yaml.safe_load("!!set {a, b}")},
    {"version": 1, "description_mode": ["full"], "pii_reviewed_by": 7, "comments": {"include_text": 1}},
    {1: 1, None: 2, "version": 1},
]


@pytest.mark.parametrize("cfg", ODD_SHAPES, ids=range(len(ODD_SHAPES)))
def test_an_odd_shape_is_findings_never_a_crash(cfg):
    for schema in (None, make_schema(), make_schema(types={}), {"types": {"X": 1}, "categories": [], "backlog": 3}):
        rows = validate_config(cfg, schema)
        assert rows and all(set(r) == {"level", "message"} and r["message"].endswith(".") for r in rows)
        assert {r["level"] for r in rows} <= {"refused", "invalid", "unresolvable"}


def test_validation_is_deterministic():
    cfg = edit(starter(), zeta=1, alpha=2, comments__bogus=3, posture="x")
    assert validate_config(cfg, None) == validate_config(copy.deepcopy(cfg), None)
