"""B0 — the mirror on the process the first capture read (2026-10-14), end to end through discovery and planning.

`wit/captured/` holds a real organisation's answers (anonymised: `contoso`, project `Claims`, team `Claims Team`,
areas renamed, `Iteration N` read as `Sprint N`, free text masked). `load_wit()` serves them with no code change,
so every discovery test that reads the default fixtures now reads the capture. The plan/apply scenarios still read
the hand-written process their hand-written item fixtures belong to (`BOARDS_PROCESS` in tests/ado_boards_fixtures.py);
this module is where the captured process itself is exercised:

  * the facts the capture settled, as the mappers read them — every type's `states` in the workItemTypes answer equal
    the per-type `workItemTypeStates` answer (why discovery no longer spends a call on them), a type's fields and
    their allowed values only at `workItemTypesField`, a custom `Spec` requirement type with the client's own risk
    picklist, a hidden User Story, and `Resolved` in the InProgress category;
  * `discover`, `config check`, `validate` and `plan` on that process: what each says, and that none of it needed a
    product change beyond the three corrected locations.

Nothing here spawns `az`: `boards_env` forbids it at the seam and `az` answers from the fixtures.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import load_wit, route_key_boards, route_params, wit_source_of

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

import ado_schema
import ado_schema_map as asm
import ado_sync
import ado_sync_model as model
import boards_contract as bc

MINI = Path(__file__).resolve().parent / "fixtures" / "boards_repo"
NOW = datetime(2026, 10, 14, 9, 30, tzinfo=timezone.utc)
CAPTURED_TYPES = ("User Story", "Bug", "Issue", "Epic", "Feature", "Spec", "RAID")  # the per-type states captured
CAPTURED_FIELDS = ("User Story", "Issue", "Epic", "Feature", "Spec")                # the per-type fields captured
DISCOVERY = ["GET core/projects", "GET wit/workItemTypeCategories", "GET wit/workItemTypes", "GET wit/fields",
             "GET work/backlogconfiguration", "GET wit/classificationNodes", "GET work/iterations",
             "GET wit/workItemRelationTypes"]


def stem(type_name: str) -> str:
    return type_name.lower().replace(" ", "_")


def types_by_name() -> dict[str, dict]:
    return {t["name"]: t for t in load_wit("types")["value"]}


def schema(**extra) -> dict:
    """The schema `discover` builds from the capture, with states for the types named in `states_for`."""
    states_for = extra.pop("states_for", ("Spec", "Epic", "Feature"))
    return asm.build_schema(
        discovered_at="2026-10-14T09:30:00Z", project=load_wit("projects"), team={"name": "Claims Team"},
        categories=asm.map_categories(load_wit("type_categories")), types=asm.map_types(load_wit("types")),
        states_by_type={n: asm.map_type_states(n, {"value": types_by_name()[n]["states"]}) for n in states_for},
        fields_by_type={"Spec": asm.map_type_fields("Spec", load_wit("type_fields_spec"))},
        fields=asm.map_fields(load_wit("fields")), backlog=asm.map_backlog_config(load_wit("backlog_config")),
        nodes=asm.map_nodes(load_wit("classification_nodes")),
        team_iterations=asm.map_team_iterations(load_wit("team_iterations")),
        link_types=asm.map_link_types(load_wit("relation_types")), commands=[], **extra)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(ado_schema, "now_utc", lambda: NOW)


def run(capsys, *argv):
    code = ado_sync.main([str(a) for a in argv])
    return code, capsys.readouterr().out


def run_json(capsys, *argv):
    code, out = run(capsys, *argv, "--json")
    return code, json.loads(out)


@pytest.fixture
def repo(tmp_path, az) -> Path:
    """The mini repository with the starter config, against a board that holds no item yet."""
    root = tmp_path / "repo"
    shutil.copytree(MINI, root)
    az.answers["boards query"] = []
    assert ado_sync.main(["config", "init", "--repo", str(root)]) == 0
    return root


# --- what the loader serves ------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["projects", "type_categories", "types", "fields", "backlog_config",
                                  "classification_nodes", "team_iterations", "relation_types", "connection_data",
                                  *[f"type_states_{stem(t)}" for t in CAPTURED_TYPES],
                                  *[f"type_fields_{stem(t)}" for t in CAPTURED_FIELDS]])
def test_the_default_fixture_is_the_capture(name):
    assert wit_source_of(name) == "captured"


@pytest.mark.parametrize("mapper, name", [
    ("map_categories", "type_categories"), ("map_types", "types"), ("map_fields", "fields"),
    ("map_backlog_config", "backlog_config"), ("map_nodes", "classification_nodes"),
    ("map_team_iterations", "team_iterations"), ("map_link_types", "relation_types")])
def test_every_mapper_reads_its_captured_document_and_every_key_it_requires_is_there(mapper, name):
    doc = load_wit(name)
    getattr(asm, mapper)(doc)                                                  # no AdoImportError: the shape is known
    items = [doc] if mapper == "map_backlog_config" else doc["value"]
    for key in asm.REQUIRED_KEYS[mapper]:
        assert all(key in item for item in items), (mapper, key)


# --- the facts the capture settled ---------------------------------------------------------------------------------

@pytest.mark.parametrize("type_name", CAPTURED_TYPES)
def test_a_types_states_in_the_types_answer_are_the_per_type_answer(type_name):
    """Why discovery reads states from workItemTypes and spends no `workItemTypeStates` call: equal, in order."""
    per_type = load_wit(f"type_states_{stem(type_name)}")
    assert per_type["value"] == types_by_name()[type_name]["states"]
    assert asm.map_type_states(type_name, per_type) == asm.map_type_states(
        type_name, {"value": types_by_name()[type_name]["states"]})


@pytest.mark.parametrize("type_name", CAPTURED_FIELDS)
def test_a_types_fields_and_allowed_values_come_only_from_the_per_type_location(type_name):
    per_type = load_wit(f"type_fields_{stem(type_name)}")["value"]
    project_wide = load_wit("fields")["value"]
    assert len(per_type) < len(project_wide) and not any("allowedValues" in f for f in project_wide)
    assert {f["referenceName"] for f in per_type} == {f["referenceName"] for f in types_by_name()[type_name]["fields"]}
    allowed = {f["referenceName"]: f["allowedValues"] for f in per_type}
    states = [s["name"] for s in types_by_name()[type_name]["states"]]
    assert sorted(allowed["System.State"]) == sorted(states)                    # $expand=allowedValues is honoured
    mapped = asm.map_type_fields(type_name, {"value": per_type})
    assert allowed["System.Title"] == [] and mapped["System.Title"]["allowed_values"] is None   # [] = unrestricted


def test_the_spec_type_is_custom_with_the_clients_own_risk_picklist():
    fields = asm.map_type_fields("Spec", load_wit("type_fields_spec"))
    assert fields["System.State"]["allowed_values"] and len(fields["System.State"]["allowed_values"]) == 6
    assert fields["Custom.RiskTier"]["allowed_values"] == ["High", "Low", "Medium"]
    assert {"Custom.RiskTier", "Custom.CheckingPlan", "Custom.AcceptanceChecks", "Custom.Scope"} <= set(fields)
    project = asm.map_fields(load_wit("fields"))
    assert project["Custom.RiskTier"]["custom"] and project["Custom.RiskTier"]["is_picklist"]
    assert [s["name"] for s in types_by_name()["Spec"]["states"]] == ["New", "In-Dev", "In QA", "Blocked",
                                                                      "Ready for Release", "Closed"]
    assert types_by_name()["Spec"]["referenceName"].endswith(".Spec") and "RAID" in types_by_name()


def test_the_requirement_category_defaults_to_spec_and_user_story_is_hidden():
    categories = asm.map_categories(load_wit("type_categories"))
    assert categories["RequirementCategory"] == {"default_type": "Spec", "types": ["Spec", "User Story"]}
    assert "User Story" in categories["HiddenCategory"]["types"]
    assert asm.resolve_type(schema(), "spec", {}) == ("Spec", "default type of RequirementCategory")
    assert [n for n, t in asm.map_types(load_wit("types")).items() if t["disabled"]] == ["User Story"]
    assert asm.resolve_type(schema(), "spec", {"types": {"spec": "User Story"}}) == (
        None, "types.spec pins 'User Story' but it is disabled in this process")          # never a guess
    backlog = asm.map_backlog_config(load_wit("backlog_config"))
    requirement = next(level for level in backlog["levels"] if level["kind"] == "requirement")
    assert requirement["types"] == ["Spec", "User Story"] and requirement["default_type"] == "User Story"
    assert [lv["name"] for lv in backlog["levels"] if lv["kind"] == "portfolio"] == ["Epics", "Features"]


def test_resolved_is_in_progress_on_this_process_so_a_merged_epic_lands_on_closed():
    """The hand-written Agile process put `Resolved` in the Resolved category; this one does not, for Epic, Feature and
    User Story. The status rules follow the category, never the name."""
    s = schema()
    for type_name in ("Epic", "Feature", "User Story"):
        resolved = next(st for st in types_by_name()[type_name]["states"] if st["name"] == "Resolved")
        assert resolved["category"] == "InProgress", type_name
    assert asm.resolve_state(s, "Epic", "merged", {})[0] == "Closed"
    assert asm.resolve_state(s, "Spec", "merged", {})[0] == "Ready for Release"   # the Spec type's Resolved state
    assert asm.resolve_state(s, "Spec", "in-flight", {})[0] == "In-Dev"
    assert asm.resolve_state(s, "Spec", "ready", {})[0] == "New"                  # its only Proposed state
    assert asm.resolve_state(s, "Spec", "closed", {})[0] == "Closed"


def test_the_areas_are_flat_under_the_project_and_domains_fit_them_by_name():
    s = schema()
    assert [a["path"] for a in s["areas"]] == ["Claims", "Claims\\Intake", "Claims\\Payments", "Claims\\Fraud",
                                               "Claims\\Claims Team"]
    assert len(s["iterations"]) == 12 and len(s["team_iterations"]) == 11
    assert {i["path"] for i in s["team_iterations"]} <= {i["path"] for i in s["iterations"]}  # joined by path
    fit = asm.fit_levels(s, {"tree": {"domains": ["Intake", "Payments", "Disputes"]}})
    assert fit["domain"]["names"]["Intake"] == {"mode": "area", "area_path": "Claims\\Intake"}
    assert fit["domain"]["names"]["Disputes"]["mode"] == "tag"


def test_the_captured_identity_is_a_person_the_roster_can_name():
    who = model.executing_identity(load_wit("connection_data"), {"person1@example.com": "@dev-one"})
    assert who == {"handle": "@dev-one", "id": load_wit("connection_data")["authenticatedUser"]["id"],
                   "service_principal": False}


# --- the CLI on the captured process -------------------------------------------------------------------------------

def test_discover_reads_the_captured_process_with_one_per_type_call_and_no_states_call(repo, az, capsys):
    az.calls.clear()
    code, out = run_json(capsys, "discover", "--repo", repo)
    assert code == 0 and out["ok"] and out["team"] == "Claims Team"
    keys = [route_key_boards(c) for c in az.calls]
    assert keys[:len(DISCOVERY)] == DISCOVERY
    # one per landed type: the spec's type, Epic and Feature (their categories), and the decision pin
    assert keys[len(DISCOVERY):] == ["GET wit/workItemTypesField"] * 4
    assert [route_params(c)["type"] for c in az.calls[len(DISCOVERY):]] == ["Spec", "Epic", "Feature", "Issue"]
    assert not any(k in keys for k in ("GET wit/workItemTypeStates", "GET wit/states"))
    assert out["per_type_reads"] == ["Spec", "Epic", "Feature", "Issue"]
    assert out["counts"] == {**out["counts"], "types": 17, "fields": 106, "areas": 5, "iterations": 12,
                             "team_iterations": 11, "levels": 4}
    saved = json.loads((repo / bc.SCHEMA_FILE).read_text(encoding="utf-8"))
    assert saved["types"]["Spec"]["states"] == asm.map_type_states("Spec", load_wit("type_states_spec"))
    assert saved["types"]["Spec"]["fields"]["Custom.RiskTier"]["allowed_values"] == ["High", "Low", "Medium"]
    assert saved["types"]["RAID"]["states"] is None and saved["types"]["RAID"]["fields"] is None  # never read
    raw = (repo / bc.SCHEMA_FILE).read_text(encoding="utf-8")
    assert "@" not in raw and set(bc.GUID_RE.findall(raw)) <= {n["identifier"] for n in saved["areas"] + saved["iterations"]}


def test_the_starter_config_meets_the_captured_process_with_gaps_and_no_refusal(repo, az, capsys):
    """The starter maps risk HIGH/MEDIUM/LOW to High/Medium/Low — the spelling of this process's own picklist — so
    `config check` refuses nothing; what is left are pins this process does not have (gaps, exit 1)."""
    assert ado_sync.main(["discover", "--repo", str(repo)]) == 0
    capsys.readouterr()
    code, text = run(capsys, "config", "check", "--repo", repo)
    assert code == 1 and "refused" not in text.split("Result:")[0] and "Result: gaps (exit 1)" in text
    assert "Custom.RiskTier" not in text
    assert "`states.spec.ready.prefer` names the state 'Approved', but the type Spec has no state" in text


def test_validate_on_the_captured_process_fits_epic_feature_and_spec_as_items(repo, az, capsys):
    assert ado_sync.main(["discover", "--repo", str(repo)]) == 0
    capsys.readouterr()
    code, out = run_json(capsys, "validate", "--repo", repo)
    assert code == 1 and [g.split(":")[0] for g in out["gaps"]] == ["spike"]
    assert {k: (out["fit"][k]["mode"], out["fit"][k]["type"]) for k in ("epic", "feature", "spec")} == {
        "epic": ("item", "Epic"), "feature": ("item", "Feature"), "spec": ("item", "Spec")}
    assert {out["fit"][k]["mode"] for k in ("outcome", "domain", "requirement")} == {"tag"}  # no level above Epic


def test_plan_creates_a_spec_on_the_custom_type_with_the_clients_risk_spelling(repo, az, capsys):
    assert ado_sync.main(["discover", "--repo", str(repo)]) == 0
    capsys.readouterr()
    az.calls.clear()
    code, out = run_json(capsys, "plan", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 0 and out["counts"]["create"] == 1 and az.written() == []
    (row,) = out["rows"]
    assert (row["action"], row["type"], row["ref"]) == ("create", "Spec", "sdlc:spec:0004")
    ops = {op["path"]: op.get("new") for op in row["ops"]}
    assert ops["/fields/Custom.RiskTier"] == "High" and ops["/fields/System.State"] == "New"
    saved = json.loads((repo / bc.SCHEMA_FILE).read_text(encoding="utf-8"))
    assert ops["/fields/System.IterationPath"] in {i["path"] for i in saved["iterations"]}
    assert {route_key_boards(c) for c in az.calls} == {"boards query"}              # a plan reads, never writes
