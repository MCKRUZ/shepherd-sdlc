"""B1-P4 -- Boards discovery (`ado_schema.py`) and the CLI skeleton (`ado_sync.py`): config, discover, validate.

What this pins, and why each line exists (build kit sections 1 K6-K9, K19, 2, 4, 9):
  * `discover` reads the process with serial `devops invoke` GETs and saves `.sdlc/ado/schema.json` sorted,
    with no e-mail and no GUID except the area/iteration `identifier`s (the join key, not a person);
    every recorded argv carries `--detect false`, ends `-o json`, never carries `--project` or
    `--repository`, and never pins a preview revision;
  * a failed required call exits 1 and NAMES the call; "az is not installed" exits 1, still prints the
    `host` block (`cli_state: not_installed`) and does not spawn a second thing to find out why;
  * `--help` on every verb in `ado_sync.VERBS` touches no file, and importing the script creates none;
  * `require_human`: a blank is `Illegal` (1), an agent -- `shepherd:feature-architect` included -- is
    `Refused` (2);
  * `validate` follows the verb table (0 resolvable / 1 gaps / 2 a forbidden field is mapped) and prints
    the fit table plus the recommendations for every kind that is not an item (a fallback fit is not a gap;
    a `types.*` pin the process lacks is); backlog levels that were never read (no team) print "not discovered"
    and one recommendation naming `--team` / `team`, never a 0, a gap or a numbered process addition.

Nothing here spawns `az`: `boards_env` forbids it at the seam and the `az` fixture answers from the `wit/`
fixtures. Reviewers and teams in the fixtures are fictional, and no test writes a real person.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import load_wit, route_key_boards, route_params

import copy
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

import ado_schema
import ado_schema_map as sm
import ado_sync
import ado_sync_config as cfgmod
import boards_contract as bc
import code_host
from ado_map import AdoImportError

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ado_sync.py"
ORG = "https://dev.azure.com/contoso"
NOT_INSTALLED = "The Azure CLI (`az`) is not installed or not on PATH."

NOW = datetime(2026, 10, 13, 9, 30, tzinfo=timezone.utc)
STAMP = "2026-10-13T09:30:00Z"

TEAM = load_wit("projects")["defaultTeam"]["name"]  # the team `discover` falls back to
# B0: the spec's type is the default type of the captured process's requirement category (a custom `Spec` type there)
SPEC_TYPE = next(c["defaultWorkItemType"]["name"] for c in load_wit("type_categories")["value"]
                 if c["referenceName"] == "Microsoft.RequirementCategory")
DEFAULT_CALLS = [
    ("GET core/projects", {"projectId": "Claims"}),
    ("GET wit/workItemTypeCategories", {"project": "Claims"}),
    ("GET wit/workItemTypes", {"project": "Claims"}),
    ("GET wit/fields", {"project": "Claims"}),
    ("GET work/backlogconfiguration", {"project": "Claims", "team": TEAM}),
    ("GET wit/classificationNodes", {"project": "Claims"}),
    ("GET work/iterations", {"project": "Claims", "team": TEAM}),
    ("GET wit/workItemRelationTypes", {"project": "Claims"}),
    # B0: the spec type's fields at the corrected location; its states come from the workItemTypes answer
    ("GET wit/workItemTypesField", {"project": "Claims", "type": SPEC_TYPE}),
    # B0 plan fixes: then every other type a default kind lands on -- Epic and Feature, from their categories
    ("GET wit/workItemTypesField", {"project": "Claims", "type": "Epic"}),
    ("GET wit/workItemTypesField", {"project": "Claims", "type": "Feature"}),
]


# --- helpers ---------------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """A fixed `now`, so `discovered_at` and every age are deterministic."""
    monkeypatch.setattr(ado_schema, "now_utc", lambda: NOW)


def run(capsys, *argv):
    code = ado_sync.main([str(a) for a in argv])
    return code, capsys.readouterr().out


def run_json(capsys, *argv):
    code, out = run(capsys, *argv, "--json")
    return code, json.loads(out)


def seen(fake):
    return [(route_key_boards(c), route_params(c)) for c in fake.calls]


def write_cfg(root: Path, text: str) -> Path:
    path = root / bc.CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def read_schema(root: Path) -> dict:
    return json.loads((root / bc.SCHEMA_FILE).read_text(encoding="utf-8"))


def discovered(root, capsys, *extra):
    """Run `discover` once and hand back the saved schema (the run must succeed)."""
    code, out = run(capsys, "discover", "--repo", root, *extra)
    assert code == 0, out
    return read_schema(root)


def assert_sorted_text(raw: str) -> None:
    def hook(pairs):
        keys = [k for k, _ in pairs]
        assert keys == sorted(keys), keys
        return dict(pairs)
    doc = json.loads(raw, object_pairs_hook=hook)
    assert raw == json.dumps(doc, sort_keys=True, indent=1) + "\n"


def with_file(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- discover: what is read, and what is saved -------------------------------------------------------

def test_discover_json_saves_a_sorted_schema_with_no_identity(az, tmp_path, capsys):
    code, out = run_json(capsys, "discover", "--repo", tmp_path)
    assert code == 0 and out["ok"] is True and out["reused"] is False
    assert out["path"] == bc.SCHEMA_FILE and out["discovered_at"] == STAMP
    assert out["host"]["name"] == "azure-devops" and out["host"]["cli_state"] == "available"
    raw = (tmp_path / bc.SCHEMA_FILE).read_text(encoding="utf-8")
    assert_sorted_text(raw)
    assert "@" not in raw
    schema = json.loads(raw)
    joins = {n["identifier"] for n in schema["areas"] + schema["iterations"]}
    assert joins and set(bc.GUID_RE.findall(raw)) <= joins  # no GUID outside the classification-node join keys
    assert schema["project"] == {"name": "Claims"} and schema["team"] == {"name": TEAM}
    assert schema["schema_version"] == sm.SCHEMA_VERSION and schema["discovered_at"] == STAMP
    assert not list((tmp_path / ".sdlc").rglob("*.tmp"))


def test_discover_reads_the_process_serially_and_nothing_else(az, tmp_path, capsys):
    discovered(tmp_path, capsys)
    assert seen(az) == DEFAULT_CALLS
    assert az.count("account", "show") == 0 and az.written() == []
    schema = read_schema(tmp_path)
    assert schema["commands"] == ["core/projects", "wit/workItemTypeCategories", "wit/workItemTypes", "wit/fields",
                                  "work/backlogconfiguration", "wit/classificationNodes", "work/iterations",
                                  "wit/workItemRelationTypes", f"wit/workItemTypesField type={SPEC_TYPE}",
                                  "wit/workItemTypesField type=Epic", "wit/workItemTypesField type=Feature"]
    story, epic, raid = schema["types"][SPEC_TYPE], schema["types"]["Epic"], schema["types"]["RAID"]
    assert story["states"] and story["fields"]                       # read for the spec's type
    assert epic["states"] and epic["fields"]                         # and for every type a kind lands on
    assert raid["states"] is None and raid["fields"] is None          # never read is unknown, not empty


def test_every_recorded_argv_has_the_seam_shape(az, tmp_path, capsys):
    discovered(tmp_path, capsys)
    assert az.calls
    for argv in az.calls:
        assert argv[:2] == ["devops", "invoke"]
        assert argv[argv.index("--detect") + 1] == "false"
        assert argv[argv.index("--http-method") + 1] == "GET"
        assert argv[argv.index("--org") + 1] == ORG
        assert argv[-2:] == ["-o", "json"] and "--only-show-errors" not in argv
        assert "--project" not in argv and "--repository" not in argv and "--in-file" not in argv
        assert argv[argv.index("--api-version") + 1] == "7.1"
        assert not any(re.search(r"-preview\.\d", word) for word in argv)
    nodes = next(c for c in az.calls if route_key_boards(c) == "GET wit/classificationNodes")
    assert nodes[nodes.index("--query-parameters") + 1] == "$depth=3"
    typed = next(c for c in az.calls if route_key_boards(c) == "GET wit/workItemTypesField")
    assert route_params(typed) == {"project": "Claims", "type": SPEC_TYPE}
    assert typed[typed.index("--query-parameters") + 1] == "$expand=allowedValues"


def test_the_az_contract_matches_the_argv_discover_emits(az, tmp_path, capsys):
    cfg = write_cfg(tmp_path, "version: 1\ntypes:\n  decision: Issue\n")  # a pinned type adds the per-type reads
    discovered(tmp_path, capsys)

    def shape(argv):
        out, in_route = [], False
        for word in argv:
            if word == "--route-parameters":
                in_route = True
            elif word.startswith("--") and word != "--route-parameters":
                in_route = False
            out.append(word.partition("=")[0] + "=" if in_route and "=" in word else word)
        out[out.index("--org") + 1] = "U"
        return tuple(out)

    emitted = {shape(c) for c in az.calls}
    contract = {shape(c) for c in ado_schema.DISCOVER_AZ_CONTRACT}
    assert emitted == contract and len(ado_schema.DISCOVER_AZ_CONTRACT) == len(contract)
    assert cfg.exists()


def test_the_az_contract_is_read_only_and_never_pins_a_preview_revision():
    assert ado_schema.DISCOVER_AZ_CONTRACT
    for argv in ado_schema.DISCOVER_AZ_CONTRACT:
        assert argv[:2] == ["devops", "invoke"] and argv[argv.index("--detect") + 1] == "false"
        assert argv[argv.index("--http-method") + 1] == "GET"
        assert "--project" not in argv and "--repository" not in argv
        assert not any(re.search(r"-preview\.\d", word) for word in argv)
        assert argv[-2:] == ["-o", "json"]


def test_discover_uses_the_team_from_the_flag_then_the_config_then_the_project_default(az, tmp_path, capsys):
    discovered(tmp_path, capsys)
    assert {p["team"] for k, p in seen(az) if k.startswith("GET work/")} == {TEAM}

    az.calls.clear()
    write_cfg(tmp_path, 'version: 1\nteam: "Config Team"\n')
    code, out = run_json(capsys, "discover", "--repo", tmp_path, "--refresh")
    assert code == 0 and out["team"] == "Config Team"
    assert {p["team"] for k, p in seen(az) if k.startswith("GET work/")} == {"Config Team"}

    az.calls.clear()
    code, out = run_json(capsys, "discover", "--repo", tmp_path, "--team", "Flag Team")
    assert code == 0 and out["team"] == "Flag Team" and read_schema(tmp_path)["team"] == {"name": "Flag Team"}
    assert {p["team"] for k, p in seen(az) if k.startswith("GET work/")} == {"Flag Team"}


def test_discover_without_a_team_skips_the_team_reads_and_says_so(az, tmp_path, capsys):
    project = copy.deepcopy(load_wit("projects"))
    project.pop("defaultTeam")
    az.answers["GET core/projects"] = project
    code, out = run_json(capsys, "discover", "--repo", tmp_path)
    assert code == 0 and out["team"] is None and out["counts"]["levels"] is None
    assert out["counts"]["team_iterations"] is None
    assert not [k for k, _ in seen(az) if k.startswith("GET work/")]
    schema = read_schema(tmp_path)
    assert schema["team"] is None and schema["backlog"] is None and schema["team_iterations"] is None
    assert not [c for c in schema["commands"] if c.startswith("work/")]
    assert any("team" in note for note in out["notes"])
    code, text = run(capsys, "discover", "--repo", tmp_path)  # the text names what was not read, never a 0
    assert code == 0 and "team iterations not read, backlog levels not read" in text


def test_discover_reads_the_types_the_config_writes_to_and_skips_pins_the_process_lacks(az, tmp_path, capsys):
    cfgmod.init_config(tmp_path)  # the starter pins Objective, Domain and Domain Requirement, which Agile lacks
    code, out = run_json(capsys, "discover", "--repo", tmp_path)
    assert code == 0, out
    typed = [(k, p["type"]) for k, p in seen(az) if "type" in p]
    assert typed == [("GET wit/workItemTypesField", t) for t in (SPEC_TYPE, "Epic", "Feature", "Issue")]
    assert out["per_type_reads"] == [SPEC_TYPE, "Epic", "Feature", "Issue"]  # the spec's type, the landed, the pin
    schema = read_schema(tmp_path)
    assert schema["types"]["Issue"]["states"] and "Objective" not in schema["types"]


def test_discover_ignores_an_unusable_config_and_says_so(az, tmp_path, capsys):
    write_cfg(tmp_path, "version: [unclosed\n")
    code, out = run_json(capsys, "discover", "--repo", tmp_path)
    assert code == 0 and any("ado.yaml" in note for note in out["notes"])
    # only what the default kinds land on: the spec's type, Epic and Feature (no pin of the unusable file is read)
    assert [p["type"] for k, p in seen(az) if "type" in p] == [SPEC_TYPE, "Epic", "Feature"]


def test_discover_withholds_a_person_from_a_picklist_and_a_default(az, tmp_path, capsys):
    doc = copy.deepcopy(load_wit(f"type_fields_{SPEC_TYPE.lower().replace(' ', '_')}"))
    first, second = doc["value"][1], doc["value"][2]
    first["allowedValues"] = ["person1@example.com", "fine"]
    second["defaultValue"] = "00000000-0000-0000-0000-00000000beef"
    az.answers[f"GET wit/workItemTypesField type={SPEC_TYPE}"] = doc
    code, out = run_json(capsys, "discover", "--repo", tmp_path)
    assert code == 0 and any("withheld" in note for note in out["notes"])
    raw = (tmp_path / bc.SCHEMA_FILE).read_text(encoding="utf-8")
    assert "@" not in raw and "beef" not in raw
    fields = json.loads(raw)["types"][SPEC_TYPE]["fields"]
    assert fields[first["referenceName"]]["allowed_values"] is None
    assert fields[second["referenceName"]]["default"] is None
    assert fields[first["referenceName"]]["_notes"]


# --- discover: reuse and refresh ----------------------------------------------------------------------

def test_a_second_discover_the_same_day_reuses_the_schema_and_refresh_reads_again(az, tmp_path, capsys):
    discovered(tmp_path, capsys)
    before = len(az.calls)
    code, out = run_json(capsys, "discover", "--repo", tmp_path)
    assert code == 0 and out["reused"] is True and out["host"] is None and len(az.calls) == before
    code, out = run_json(capsys, "discover", "--repo", tmp_path, "--refresh")
    assert code == 0 and out["reused"] is False and len(az.calls) == 2 * before


def test_discover_reads_again_when_the_cache_cannot_be_reused(az, tmp_path, capsys, monkeypatch):
    discovered(tmp_path, capsys)
    one_run = len(az.calls)

    run(capsys, "discover", "--repo", tmp_path, "--team", "Another Team")           # another team
    assert len(az.calls) == 2 * one_run

    monkeypatch.setattr(ado_schema, "now_utc", lambda: datetime(2026, 10, 14, 8, 0, tzinfo=timezone.utc))
    run(capsys, "discover", "--repo", tmp_path, "--team", "Another Team")           # a day later
    assert len(az.calls) == 3 * one_run

    write_cfg(tmp_path, "version: 1\ntypes:\n  decision: Issue\n")                  # a pin the cache never read
    before = len(az.calls)
    code, out = run_json(capsys, "discover", "--repo", tmp_path, "--team", "Another Team")
    assert out["reused"] is False and len(az.calls) > before

    (tmp_path / bc.SCHEMA_FILE).write_text("{not json", encoding="utf-8")           # a corrupt cache is replaced
    code, out = run_json(capsys, "discover", "--repo", tmp_path, "--team", "Another Team")
    assert code == 0 and out["reused"] is False and read_schema(tmp_path)["project"] == {"name": "Claims"}


# --- discover: failures ---------------------------------------------------------------------------------

def test_a_failed_required_call_exits_1_and_names_the_call(az, tmp_path, capsys):
    az.fail["workItemTypeCategories"] = "403"
    code, out = run_json(capsys, "discover", "--repo", tmp_path)
    assert code == 1 and out["ok"] is False
    assert "wit/workItemTypeCategories" in out["error"] and "403" in out["error"]
    assert [k for k, _ in seen(az)] == ["GET core/projects", "GET wit/workItemTypeCategories"]  # serial: it stopped
    assert not (tmp_path / bc.SCHEMA_FILE).exists()
    text_code, text = run(capsys, "discover", "--repo", tmp_path)
    assert text_code == 1 and "wit/workItemTypeCategories" in text and "Host:" in text


def test_az_not_installed_exits_1_prints_the_host_block_and_spawns_nothing_else(az, tmp_path, capsys, monkeypatch):
    def spawned(*args, **kwargs):
        raise AssertionError("a second spawn")
    monkeypatch.setattr(subprocess, "run", spawned)
    monkeypatch.setattr(code_host, "cli_state", spawned)  # the probe `host_block` must never use
    az.fail["devops"] = NOT_INSTALLED                     # every discovery call is `devops invoke`
    code, out = run_json(capsys, "discover", "--repo", tmp_path)
    assert code == 1 and out["ok"] is False
    assert out["host"]["cli_state"] == "not_installed" and out["host"]["cli"] == "az"
    assert out["host"]["name"] == "azure-devops"
    assert len(az.calls) == 1 and az.count("account", "show") == 0
    assert not (tmp_path / ".sdlc").exists()
    text_code, text = run(capsys, "discover", "--repo", tmp_path)
    assert text_code == 1 and "not_installed" in text and len(az.calls) == 2


def test_a_remote_that_is_not_azure_devops_exits_1_without_calling_az(az, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(code_host, "origin_url", lambda root: "https://github.com/contoso/claims-api.git")
    code, out = run_json(capsys, "discover", "--repo", tmp_path)
    assert code == 1 and "not an Azure DevOps remote" in out["error"]
    assert out["host"]["name"] == "github" and az.calls == []


def test_an_unexpected_shape_exits_1_and_writes_nothing(az, tmp_path, capsys):
    az.answers["GET wit/workItemTypeCategories"] = {"count": 1, "value": [{"name": "Epic Category"}]}
    code, out = run_json(capsys, "discover", "--repo", tmp_path)
    assert code == 1 and "unexpected az shape" in out["error"] and "wit/workItemTypeCategories" in out["error"]
    assert not (tmp_path / bc.SCHEMA_FILE).exists()


def test_an_unwritable_schema_path_exits_1(az, tmp_path, capsys):
    (tmp_path / ".sdlc").write_text("a file where the folder should be", encoding="utf-8")
    code, out = run_json(capsys, "discover", "--repo", tmp_path)
    assert code == 1 and out["ok"] is False and "schema" in out["error"]


# --- the schema file: save / load / age -------------------------------------------------------------------

def schema_from_fixtures() -> dict:
    return sm.build_schema(
        discovered_at=STAMP, project={"name": "Claims"}, team={"name": "Claims Team"},
        categories=sm.map_categories(load_wit("type_categories")), types=sm.map_types(load_wit("types")),
        states_by_type={}, fields_by_type={}, fields=sm.map_fields(load_wit("fields")),
        backlog=sm.map_backlog_config(load_wit("backlog_config")), nodes=sm.map_nodes(load_wit("classification_nodes")),
        team_iterations=sm.map_team_iterations(load_wit("team_iterations")),
        link_types=sm.map_link_types(load_wit("relation_types")), commands=[])


def test_save_schema_is_sorted_indented_and_round_trips(tmp_path):
    schema = schema_from_fixtures()
    path = ado_schema.save_schema(tmp_path, schema)
    assert path == tmp_path / bc.SCHEMA_FILE and path.read_text(encoding="utf-8").endswith("}\n")
    assert path.read_text(encoding="utf-8") == json.dumps(schema, sort_keys=True, indent=1) + "\n"
    assert ado_schema.load_schema(tmp_path) == json.loads(json.dumps(schema))
    assert not list(path.parent.glob("*.tmp"))


@pytest.mark.parametrize("where, value", [("types.Epic.note", "person1@example.com"),
                                          ("types.Epic.note", "00000000-0000-0000-0000-00000000aaaa"),
                                          ("fields.Custom.X.name", "person2@example.com")])
def test_save_schema_refuses_an_identity_and_writes_nothing(tmp_path, where, value):
    schema = schema_from_fixtures()
    section, ref, key = where.split(".")[0], ".".join(where.split(".")[1:-1]), where.split(".")[-1]
    schema[section].setdefault(ref, {})[key] = value
    with pytest.raises(AdoImportError) as err:
        ado_schema.save_schema(tmp_path, schema)
    assert value not in str(err.value) and key in str(err.value)  # names the place, never the value
    assert not (tmp_path / ".sdlc").exists()


def test_save_schema_allows_the_classification_node_identifiers(tmp_path):
    schema = schema_from_fixtures()
    assert any(bc.GUID_RE.search(n["identifier"]) for n in schema["areas"])
    ado_schema.save_schema(tmp_path, schema)  # does not raise


def test_load_schema_is_none_when_absent_and_loud_when_unusable(tmp_path):
    assert ado_schema.load_schema(tmp_path) is None
    with_file(tmp_path / bc.SCHEMA_FILE, "{not json")
    with pytest.raises(AdoImportError, match="not valid JSON"):
        ado_schema.load_schema(tmp_path)
    with_file(tmp_path / bc.SCHEMA_FILE, "[1, 2]")
    with pytest.raises(AdoImportError, match="discover --refresh"):
        ado_schema.load_schema(tmp_path)
    with_file(tmp_path / bc.SCHEMA_FILE, json.dumps({"schema_version": 99}))
    with pytest.raises(AdoImportError, match="discover --refresh"):
        ado_schema.load_schema(tmp_path)


@pytest.mark.parametrize("stamp, today, age", [
    ("2026-10-13T09:30:00Z", date(2026, 10, 13), 0),
    ("2026-10-13T23:59:59Z", date(2026, 10, 16), 3),
    ("2026-10-13T09:30:00Z", datetime(2026, 10, 20, 1, 0, tzinfo=timezone.utc), 7),
    ("2026-10-13", date(2026, 10, 14), 1),
    ("not a date", date(2026, 10, 13), None),
    (None, date(2026, 10, 13), None),
])
def test_schema_age_days(stamp, today, age):
    assert ado_schema.schema_age_days({"discovered_at": stamp}, today) == age
    assert ado_schema.schema_age_days({}, today) is None


# --- the CLI skeleton --------------------------------------------------------------------------------------

def test_the_verbs_are_the_parser_s_verbs():
    assert {"config", "discover", "validate"} <= set(ado_sync.VERBS)
    parser = ado_sync.build_parser()
    choices = next(a for a in parser._actions if getattr(a, "choices", None)).choices
    assert set(choices) == set(ado_sync.VERBS)
    assert all(callable(handler) for handler in ado_sync.VERBS.values())


def test_help_on_every_verb_touches_no_file(tmp_path, monkeypatch, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    commands = [["--help"], *[[verb, "--help"] for verb in ado_sync.VERBS], ["config", "init", "--help"],
                ["config", "check", "--help"]]
    for argv in commands:
        with pytest.raises(SystemExit) as stop:
            ado_sync.main(argv)
        assert stop.value.code == 0, argv
    capsys.readouterr()
    assert list(empty.iterdir()) == []


def test_the_script_runs_help_for_every_verb_in_an_empty_cwd_and_import_creates_nothing(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    for verb in [None, *ado_sync.VERBS]:
        argv = [sys.executable, str(SCRIPT), *([verb] if verb else []), "--help"]
        done = subprocess.run(argv, cwd=empty, capture_output=True, text=True, env=env, timeout=60)
        assert done.returncode == 0, (verb, done.stderr)
        assert done.stdout.strip()
    probe = f"import sys; sys.path.insert(0, {str(ROOT / 'scripts')!r}); import ado_sync, ado_schema"
    done = subprocess.run([sys.executable, "-c", probe], cwd=empty, capture_output=True, text=True, env=env, timeout=60)
    assert done.returncode == 0, done.stderr
    assert list(empty.iterdir()) == []


def test_agent_stems_are_every_agent_file():
    stems = {p.stem for p in (ROOT / "agents").glob("*.md")}
    assert ado_sync.AGENT_STEMS == frozenset(stems)
    assert {"feature-architect", "requirements-analyst"} <= ado_sync.AGENT_STEMS
    assert bc.DISCIPLINE_AGENTS <= ado_sync.AGENT_STEMS


@pytest.mark.parametrize("name", ["", "   ", None])
def test_require_human_refuses_a_blank_as_illegal(name):
    with pytest.raises(ado_sync.Illegal, match="--by"):
        ado_sync.require_human(name, "--by")


@pytest.mark.parametrize("name", ["shepherd:feature-architect", "Shepherd:Data-Analyst", "feature-architect",
                                  "requirements-analyst", "BIZREQ-ANALYST", "claude", "Claude Code", "release bot",
                                  "automated", "shepherd:claude", "sdlc-orchestrator"])
def test_require_human_refuses_an_agent_as_refused(name):
    with pytest.raises(ado_sync.Refused, match="--by"):
        ado_sync.require_human(name, "--by")


@pytest.mark.parametrize("name, clean", [("Arjun Malhotra", "Arjun Malhotra"), ("  Matt  ", "Matt"), ("@MCKRUZ", "@MCKRUZ"),
                                         ("Daniel Agentis", "Daniel Agentis")])
def test_require_human_returns_the_clean_name_of_a_person(name, clean):
    assert ado_sync.require_human(name, "--by") == clean


def test_the_exit_classes_are_the_documented_ones():
    assert issubclass(ado_sync.Refused, Exception) and issubclass(ado_sync.Illegal, Exception)
    assert not issubclass(ado_sync.Refused, ado_sync.Illegal) and not issubclass(ado_sync.Illegal, ado_sync.Refused)


def test_resolve_repo_root(tmp_path, monkeypatch):
    state = with_file(tmp_path / "proj" / ".sdlc" / "state.yaml", "phase: 1\n")
    ns = ado_sync.build_parser().parse_args(["config", "check", "--state", str(state)])
    assert ado_sync.resolve_repo_root(ns) == (tmp_path / "proj").resolve()
    ns = ado_sync.build_parser().parse_args(["config", "check", "--state", str(tmp_path / "gone.yaml")])
    assert ado_sync.resolve_repo_root(ns) is None
    monkeypatch.chdir(tmp_path)
    ns = ado_sync.build_parser().parse_args(["config", "check"])
    assert ado_sync.resolve_repo_root(ns) == tmp_path.resolve()
    ns = ado_sync.build_parser().parse_args(["config", "check", "--repo", str(tmp_path / "x")])
    assert ado_sync.resolve_repo_root(ns) == (tmp_path / "x").resolve()


def test_a_missing_state_file_exits_1(tmp_path, capsys):
    code, out = run(capsys, "config", "check", "--state", tmp_path / "nope" / "state.yaml")
    assert code == 1 and "state file not found" in out
    code, out = run_json(capsys, "validate", "--state", tmp_path / "nope" / "state.yaml")
    assert code == 1 and out["ok"] is False


def test_host_block_for_reads_the_error_it_is_given(tmp_path):
    ok = ado_sync.host_block_for(tmp_path, None)
    assert set(ok) == {"name", "source", "cli", "cli_state", "detail"}
    assert ok["name"] == "azure-devops" and ok["cli"] == "az" and ok["cli_state"] == "available"
    assert ado_sync.host_block_for(tmp_path, NOT_INSTALLED)["cli_state"] == "not_installed"
    assert ado_sync.host_block_for(tmp_path, "az login required")["cli_state"] == "signed_out"


# --- config init / check ---------------------------------------------------------------------------------------

def test_config_init_writes_the_starter_and_the_local_ignore_file(tmp_path, capsys):
    code, out = run_json(capsys, "config", "init", "--repo", tmp_path)
    assert code == 0 and out["written"] == [bc.CONFIG_FILE, ".sdlc/ado/local/.gitignore"]
    assert (tmp_path / bc.CONFIG_FILE).read_bytes() == cfgmod.STARTER_PATH.read_bytes()
    assert (tmp_path / bc.LOCAL_DIR / ".gitignore").read_bytes() == b"*\n"


def test_config_init_will_not_overwrite_without_force(tmp_path, capsys):
    path = write_cfg(tmp_path, "version: 1\n# mine\n")
    code, out = run(capsys, "config", "init", "--repo", tmp_path)
    assert code == 1 and "already exists" in out and "--force" in out
    assert path.read_text(encoding="utf-8") == "version: 1\n# mine\n" and not (tmp_path / bc.LOCAL_DIR).exists()
    code, out = run_json(capsys, "config", "init", "--repo", tmp_path, "--force")
    assert code == 0 and path.read_bytes() == cfgmod.STARTER_PATH.read_bytes()


def test_config_init_in_workflow_mode_writes_beside_the_state_file(tmp_path, capsys):
    state = with_file(tmp_path / ".sdlc" / "state.yaml", "phase: 1\n")
    code, out = run(capsys, "config", "init", "--state", state)
    assert code == 0 and (tmp_path / bc.CONFIG_FILE).is_file()


def test_config_check_exit_codes(tmp_path, capsys):
    code, out = run(capsys, "config", "check", "--repo", tmp_path)                      # no file
    assert code == 1 and "config init" in out
    write_cfg(tmp_path, "version: [unclosed\n")                                          # not YAML
    assert run(capsys, "config", "check", "--repo", tmp_path)[0] == 1
    write_cfg(tmp_path, "- a\n- list\n")
    assert run(capsys, "config", "check", "--repo", tmp_path)[0] == 1
    write_cfg(tmp_path, "version: 1\nposture: 5\n")                                      # wrong type: invalid
    assert run(capsys, "config", "check", "--repo", tmp_path)[0] == 1
    write_cfg(tmp_path, "version: 1\nbogus: 1\n")                                        # unknown key: refused
    code, out = run(capsys, "config", "check", "--repo", tmp_path)
    assert code == 2 and "refused" in out and "bogus" in out
    write_cfg(tmp_path, "version: 1\nfields:\n  spec:\n    size: Microsoft.VSTS.Scheduling.StoryPoints\n")
    assert run(capsys, "config", "check", "--repo", tmp_path)[0] == 2                   # a scheduling field
    cfgmod.init_config(tmp_path, force=True)
    code, out = run(capsys, "config", "check", "--repo", tmp_path)                      # the starter, no schema
    assert code == 0 and "0 findings" in out and "not discovered" in out


def test_config_check_json_and_the_schema_it_uses_when_one_exists(az, tmp_path, capsys):
    write_cfg(tmp_path, "version: 1\ntypes:\n  decision: Nonexistent\n")
    code, out = run_json(capsys, "config", "check", "--repo", tmp_path)               # no schema: the pin cannot be checked
    assert code == 0 and out["ok"] is True and out["rows"] == [] and out["schema"] is None
    discovered(tmp_path, capsys)
    code, out = run_json(capsys, "config", "check", "--repo", tmp_path)               # now the process can say it has no such type
    assert code == 1 and out["ok"] is False and out["schema"]["age_days"] == 0
    assert out["counts"] == {"refused": 0, "unresolvable": 1, "invalid": 0}
    assert [r["level"] for r in out["rows"]] == ["unresolvable"] and "types.decision" in out["rows"][0]["message"]
    text_code, text = run(capsys, "config", "check", "--repo", tmp_path)
    assert text_code == 1 and "1 finding" in text and "unresolvable:" in text and "Result: gaps (exit 1)" in text


def test_config_check_against_the_starter_reports_what_the_process_does_not_have(az, tmp_path, capsys):
    cfgmod.init_config(tmp_path)
    discovered(tmp_path, capsys)
    code, out = run_json(capsys, "config", "check", "--repo", tmp_path)
    assert code in (1, 2) and out["ok"] is False                       # the starter pins types an Agile process lacks
    messages = " ".join(r["message"] for r in out["rows"])
    assert "types.outcome" in messages and "types.domain" in messages and "types.requirement" in messages


def test_config_check_refuses_a_field_the_discovered_process_never_lets_the_mirror_write(az, tmp_path, capsys):
    discovered(tmp_path, capsys)
    schema = read_schema(tmp_path)
    schema["backlog"]["effort_field"] = "Custom.Sizing"
    ado_schema.save_schema(tmp_path, schema)
    write_cfg(tmp_path, "version: 1\nfields:\n  spec:\n    sizing: Custom.Sizing\n")
    code, out = run_json(capsys, "config", "check", "--repo", tmp_path)
    assert code == 2 and any("Custom.Sizing" in r["message"] for r in out["rows"])


def test_config_check_ignores_a_corrupt_schema_and_says_so(tmp_path, capsys):
    cfgmod.init_config(tmp_path)
    with_file(tmp_path / bc.SCHEMA_FILE, "{not json")
    code, out = run(capsys, "config", "check", "--repo", tmp_path)
    assert code == 0 and "not valid JSON" in out


# --- validate -----------------------------------------------------------------------------------------------------

KINDS_CFG = "version: 1\nkinds: [outcome, domain, requirement, epic, feature, spec]\n"


def use_scrum(az) -> None:
    """A Scrum process whose only portfolio levels are Epic and Feature, built from the synthetic fixtures (never
    captured), so what `validate` says about it cannot move when a capture replaces the hand-written Agile files."""
    backlog = copy.deepcopy(load_wit("two_level_backlog_config"))
    keep = ("Microsoft.EpicCategory", "Microsoft.FeatureCategory")
    backlog["portfolioBacklogs"] = [b for b in backlog["portfolioBacklogs"] if b["id"] in keep]
    az.answers.update({
        "GET wit/workItemTypeCategories": "scrum_categories", "GET wit/workItemTypes": "scrum_types",
        "GET work/backlogconfiguration": backlog,
        "GET wit/workItemTypesField type=Product Backlog Item": "type_fields_user_story"})


def discover_scrum(az, root, capsys, cfg: str = KINDS_CFG) -> dict:
    use_scrum(az)
    write_cfg(root, cfg)
    return discovered(root, capsys, "--team", "Golden Team")


SCRUM_GOLDEN = f"""\
Azure Boards mirror: validate
Schema: read {STAMP} (0 days old), team Golden Team
Config: .sdlc/ado.yaml, 0 findings

How each kind lands on this process
  kind         mode  type                  level  why
  outcome      tag   -                     -      types.outcome not set and no portfolio level 3 above Epic; rides as `outcome:<slug>` tags
  domain       tag   -                     -      no portfolio level 2 above Epic; no domain names given (tree.domains), so domains ride as `domain:<slug>` tags
  requirement  tag   -                     -      no portfolio level 1 above Epic; rides as `fr:<id>` tags
  epic         item  Epic                  -      default type of EpicCategory
  feature      item  Feature               -      default type of FeatureCategory
  spec         item  Product Backlog Item  -      default type of RequirementCategory

Recommendations
  - outcome: add a work item type for outcomes (for example Objective) and name it in types.outcome, or a third portfolio backlog level above Epic, so each success dimension is its own board item; until then outcomes ride as `outcome:<slug>` tags.
  - domain: add two portfolio backlog levels above Epic (the nearer one holds requirements, the next one holds domains) so each domain is its own board item; until then domains ride as `domain:<slug>` tags.
  - requirement: add a portfolio backlog level above Epic so each FR is its own board item that Epics link to; until then each FR rides as an `fr:<id>` tag.

Result: resolvable (exit 0)
"""


def test_validate_prints_the_fit_table_and_the_recommendations_and_a_fallback_fit_is_not_a_gap(az, tmp_path, capsys):
    discover_scrum(az, tmp_path, capsys)
    calls = len(az.calls)
    code, out = run(capsys, "validate", "--repo", tmp_path)
    assert code == 0
    assert out == SCRUM_GOLDEN
    assert len(az.calls) == calls  # validate reads the saved schema, never the board


def test_validate_json(az, tmp_path, capsys):
    discover_scrum(az, tmp_path, capsys)
    code, out = run_json(capsys, "validate", "--repo", tmp_path)
    assert code == 0 and out["ok"] is True and out["exit"] == 0 and out["gaps"] == [] and out["rows"] == []
    assert out["schema"] == {"discovered_at": STAMP, "age_days": 0, "team": "Golden Team"}
    assert list(out["fit"]) == ["outcome", "domain", "requirement", "epic", "feature", "spec"]
    assert out["fit"]["spec"]["type"] == "Product Backlog Item" and out["fit"]["outcome"]["mode"] == "tag"
    assert out["counts"] == {"refused": 0, "unresolvable": 0, "invalid": 0} and out["resolved"] == {}
    assert len(out["recommendations"]) == 3


def test_validate_only_checks_the_kinds_the_config_names(az, tmp_path, capsys):
    discover_scrum(az, tmp_path, capsys, "version: 1\nkinds: [epic, spec]\n")
    code, out = run_json(capsys, "validate", "--repo", tmp_path)
    assert code == 0 and list(out["fit"]) == ["epic", "spec"] and out["recommendations"] == []
    write_cfg(tmp_path, "version: 1\n")  # no `kinds`: the starter's kinds, which include a spike with no type
    code, out = run_json(capsys, "validate", "--repo", tmp_path)
    assert code == 1 and list(out["fit"]) == ["outcome", "domain", "requirement", "epic", "feature", "spec"]
    assert [g.split(":")[0] for g in out["gaps"]] == ["spike", "decision"]


def test_validate_with_no_config_or_no_schema_is_a_gap(az, tmp_path, capsys):
    code, out = run(capsys, "validate", "--repo", tmp_path)
    assert code == 1 and "config init" in out
    write_cfg(tmp_path, KINDS_CFG)
    code, out = run_json(capsys, "validate", "--repo", tmp_path)
    assert code == 1 and out["ok"] is False and out["schema"] is None and any("discover" in g for g in out["gaps"])
    code, text = run(capsys, "validate", "--repo", tmp_path)
    assert code == 1 and "Result: gaps (exit 1)" in text and "discover" in text and az.calls == []


def test_validate_a_corrupt_schema_is_an_error_not_a_pass(az, tmp_path, capsys):
    write_cfg(tmp_path, KINDS_CFG)
    with_file(tmp_path / bc.SCHEMA_FILE, "{not json")
    code, out = run_json(capsys, "validate", "--repo", tmp_path)
    assert code == 1 and out["ok"] is False and "discover --refresh" in out["error"]


def test_validate_a_type_pin_the_process_lacks_is_a_gap(az, tmp_path, capsys):
    discover_scrum(az, tmp_path, capsys, "version: 1\nkinds: [epic, feature, spec, decision]\n"
                                         "types:\n  decision: Nonexistent\n")
    code, out = run_json(capsys, "validate", "--repo", tmp_path)
    assert code == 1 and out["counts"]["unresolvable"] == 1
    assert any("types.decision" in r["message"] and "Nonexistent" in r["message"] for r in out["rows"])
    assert any(g.startswith("decision:") for g in out["gaps"])


def test_validate_a_kind_with_no_type_is_a_gap_that_lists_the_candidates(az, tmp_path, capsys):
    discover_scrum(az, tmp_path, capsys, "version: 1\nkinds: [epic, feature, spec, spike]\n")
    code, text = run(capsys, "validate", "--repo", tmp_path)
    assert code == 1 and "Gaps" in text and "spike: types.spike not set; candidates present in process: Task" in text
    write_cfg(tmp_path, "version: 1\nkinds: [epic, feature, spec, spike]\ntypes:\n  spike: Task\n")
    code, out = run_json(capsys, "validate", "--repo", tmp_path)
    assert code == 0 and out["resolved"]["spike"]["type"] == "Task"


def test_validate_a_mapped_activity_metric_exits_2(az, tmp_path, capsys):
    discover_scrum(az, tmp_path, capsys, KINDS_CFG + "fields:\n  spec:\n    size: Microsoft.VSTS.Scheduling.StoryPoints\n")
    code, text = run(capsys, "validate", "--repo", tmp_path)
    assert code == 2 and "refused:" in text and "Result: refused (exit 2)" in text
    code, out = run_json(capsys, "validate", "--repo", tmp_path)
    assert code == 2 and out["ok"] is False and out["exit"] == 2


def test_validate_on_a_process_with_two_portfolio_levels_fits_every_kind_as_an_item(az, tmp_path, capsys):
    az.answers.update({
        "GET wit/workItemTypeCategories": "two_level_categories", "GET wit/workItemTypes": "two_level_types",
        "GET work/backlogconfiguration": "two_level_backlog_config",
        "GET wit/workItemTypesField type=Objective": "type_fields_issue"})
    write_cfg(tmp_path, KINDS_CFG + "types:\n  outcome: Objective\n")
    discovered(tmp_path, capsys)
    code, out = run_json(capsys, "validate", "--repo", tmp_path)
    assert code == 0 and out["recommendations"] == [] and out["gaps"] == []
    fit = out["fit"]
    assert (fit["outcome"]["type"], fit["domain"]["type"], fit["requirement"]["type"]) == ("Objective", "Theme", "Initiative")
    assert {entry["mode"] for entry in fit.values()} == {"item"}
    code, text = run(capsys, "validate", "--repo", tmp_path)
    assert code == 0 and "Recommendations" not in text and "Result: resolvable (exit 0)" in text


UNREAD = "backlog levels were not discovered — pass --team or set `team` in .sdlc/ado.yaml so discover can read them"
SCRUM_UNREAD_GOLDEN = f"""\
Azure Boards mirror: validate
Schema: read {STAMP} (0 days old), team not set
Config: .sdlc/ado.yaml, 0 findings

How each kind lands on this process
  kind         mode            type                  level  why
  outcome      not discovered  -                     -      {UNREAD}
  domain       not discovered  -                     -      {UNREAD}
  requirement  not discovered  -                     -      {UNREAD}
  epic         item            Epic                  -      default type of EpicCategory
  feature      item            Feature               -      default type of FeatureCategory
  spec         item            Product Backlog Item  -      default type of RequirementCategory

Recommendations
  - outcome, domain, requirement: {UNREAD}; until then it is not known whether this process has portfolio backlog levels above Epic to hold these kinds as board items, so no process addition is recommended.

Result: resolvable (exit 0)
"""


def discover_scrum_without_a_team(az, root, capsys) -> dict:
    """The Scrum process with no --team, no `team` in the config and no default team: backlogconfiguration is
    never read, so the schema's `backlog` is None."""
    use_scrum(az)
    project = copy.deepcopy(load_wit("projects"))
    project.pop("defaultTeam")
    az.answers["GET core/projects"] = project
    write_cfg(root, KINDS_CFG)
    schema = discovered(root, capsys)
    assert schema["backlog"] is None and schema["team"] is None
    return schema


def test_validate_with_backlog_levels_never_read_says_not_discovered_never_a_zero_or_a_gap(az, tmp_path, capsys):
    discover_scrum_without_a_team(az, tmp_path, capsys)
    code, out = run(capsys, "validate", "--repo", tmp_path)
    assert code == 0 and out == SCRUM_UNREAD_GOLDEN
    assert "add two portfolio backlog levels" not in out and "third portfolio backlog level" not in out
    code, js = run_json(capsys, "validate", "--repo", tmp_path)
    assert code == 0 and js["gaps"] == [] and js["schema"]["team"] is None
    assert [js["fit"][k]["mode"] for k in ("outcome", "domain", "requirement")] == ["unknown"] * 3
    assert all(js["fit"][k]["level"] is None and js["fit"][k]["type"] is None for k in ("outcome", "domain", "requirement"))
    (sentence,) = js["recommendations"]
    assert "--team" in sentence and "`team` in .sdlc/ado.yaml" in sentence and not re.search(r"\d", sentence)


def test_validate_with_backlog_levels_never_read_still_honours_a_type_pin(az, tmp_path, capsys):
    discover_scrum_without_a_team(az, tmp_path, capsys)
    write_cfg(tmp_path, KINDS_CFG + "types:\n  outcome: Impediment\n")
    code, js = run_json(capsys, "validate", "--repo", tmp_path)
    assert code == 0 and js["gaps"] == []
    assert (js["fit"]["outcome"]["mode"], js["fit"]["outcome"]["type"], js["fit"]["outcome"]["level"]) == (
        "item", "Impediment", None)  # a pin needs no level; its level number was never read, so it is null
    assert [js["fit"][k]["mode"] for k in ("domain", "requirement")] == ["unknown", "unknown"]
    assert js["recommendations"] == [
        f"domain, requirement: {UNREAD}; until then it is not known whether this process has portfolio backlog levels "
        "above Epic to hold these kinds as board items, so no process addition is recommended."]


def test_validate_never_spawns_az(az, tmp_path, capsys):
    write_cfg(tmp_path, KINDS_CFG)
    ado_schema.save_schema(tmp_path, schema_from_fixtures())
    code, out = run_json(capsys, "validate", "--repo", tmp_path)
    assert code == 0 and az.calls == []


# --- hygiene the gates also check ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("module", [ado_schema, ado_sync])
def test_the_new_modules_have_no_subprocess_no_shell_join_and_no_preview_revision(module):
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s+subprocess\b", source, re.M)
    assert not re.search(r"shell=True|shlex\.join|\" \"\.join\((args|argv|cmd)", source)
    assert not re.search(r"-preview\.\d", source)


def test_ado_sync_never_imports_the_protected_clis_or_subprocess():
    # the CLI spawns the protected CLIs as argv lists from ado_sync_reconcile, never imports them; ado_* siblings are fine
    import ast
    tree = ast.parse(Path(ado_sync.__file__).read_text(encoding="utf-8"))
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not names & {"subprocess", "sprint", "spec_transition", "handoff", "new_spec", "track_decisions",
                        "advance_phase", "check_gates"}


def test_default_kinds_are_the_starter_kinds():
    starter = yaml.safe_load(cfgmod.STARTER_PATH.read_text(encoding="utf-8"))
    assert list(ado_sync.DEFAULT_KINDS) == starter["kinds"]
