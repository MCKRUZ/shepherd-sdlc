"""The breadth sources for the Boards mirror: NFRs, business rules, discovery questions, the lifecycle item and
measurements (B5-P1).

`scripts/ado_sync_sources_p1.py` reads the five opt-in kinds of `ado_sync_model.BREADTH_KINDS` out of the repository
and registers a loader for each with `ado_sync_sources.SOURCES` when it is imported (`ado_sync.py` imports it, so
`plan --kind nfr` plans NFRs):

  * `nfr`        a row of `non-functional-requirements.md`; its parent is the Domain whose heading it sits under
  * `rule`       a `BR-NN` row of `business-rules.md` (a table with no `## ` heading, read by its columns); its parent
                 is the Feature whose brief names it; a rule `pending DL-NN` names that decision as its predecessor
  * `question`   a `Q-NN` entry of `question-list.md`, read through the shape `question-list.shape.yaml`
  * `lifecycle`  the one item that mirrors `.sdlc/state.yaml`: the phase, gate and sign-off table in its Description
  * `measurement` a threshold row of a `success-criteria.md` dimension; its parent is that dimension's Outcome, and it
                 is an item only on the type `types.measurement` pins (otherwise it stays in the Outcome's block)

Every test runs against the mini repository under `fixtures/boards_repo_p1/` (generic names; every address is
@example.com) or a copy of it in `tmp_path`. The rules held most firmly: a loader reads and never writes (the sha256 of
every fixture file is the same after a full read), a thing that is not known is absent or None with a note and never
a made-up zero, and no address, GUID or person's name reaches any projection field, tag or note, whatever the
artifacts hold.

`ado_sync_sources_p1` registers into the real `ado_sync_sources.SOURCES` when it is imported, which is what this file
wants for the behaviour tests (the module is imported once, at the top). The registration tests use the `p1` fixture
instead: it imports the module afresh against a stand-in hook table and leaves `sys.modules` as it found it.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import HAND_WRITTEN_PROCESS

import ast
import hashlib
import importlib
import json
import re
import shutil
import sys
import types
from pathlib import Path

import pytest
import yaml

import ado_sync
import ado_sync_model as model
import ado_sync_sources as src
import ado_sync_sources_p1 as breadth
import ado_sync_sources_tree as tree
import boards_contract as bc

# B0 (2026-10-14): these scenarios combine the item, history and write fixtures — hand-written for the hand-written
# Agile process, and not captured yet — with a process, so they read that same process even where a capture exists
# (tests/ado_boards_fixtures.py, `BOARDS_PROCESS`). The captured process is exercised in test_boards_captured_process.py.
BOARDS_PROCESS = HAND_WRITTEN_PROCESS

HERE = Path(__file__).resolve().parent
REPO = HERE / "fixtures" / "boards_repo_p1"
MODULE = Path(breadth.__file__)
SCRIPTS = MODULE.parent
ARTIFACTS = ".sdlc/artifacts"
NFR_REL = f"{ARTIFACTS}/01-requirements/non-functional-requirements.md"
RULES_REL = f"{ARTIFACTS}/01-requirements/business-rules.md"
QUESTIONS_REL = f"{ARTIFACTS}/00-discovery/question-list.md"
STATE_REL = ".sdlc/state.yaml"
SUCCESS_REL = f"{ARTIFACTS}/00-discovery/success-criteria.md"
KINDS = ("nfr", "rule", "question", "lifecycle", "measurement")
PINNED = {"ref", "kind", "id", "title", "status", "fields", "tags", "parent_ref", "parent_note", "related_refs",
          "source_path", "source_sha"}
PRIORITY = "Microsoft.VSTS.Common.Priority"
AC = "Microsoft.VSTS.Common.AcceptanceCriteria"


def _states(*pairs):
    return [{"name": n, "category": c, "order": i} for i, (n, c) in enumerate(pairs)]


def _field():
    return {"type": "integer", "read_only": False, "always_required": False, "default": None, "allowed_values": None}


# User Story carries Priority and AcceptanceCriteria; Epic carries Priority only; Issue's fields were never read.
SCHEMA = {
    "types": {
        "User Story": {"states": _states(("New", "Proposed"), ("Active", "InProgress"), ("Closed", "Completed"),
                                         ("Removed", "Removed")),
                       "fields": {PRIORITY: _field(), AC: _field()}},
        "Epic": {"states": _states(("New", "Proposed"), ("Active", "InProgress"), ("Closed", "Completed")),
                 "fields": {PRIORITY: _field()}},
        "Issue": {"states": _states(("To Do", "Proposed"), ("Doing", "InProgress"), ("Done", "Completed")),
                  "fields": None},
    },
    "categories": {
        "RequirementCategory": {"default_type": "User Story", "types": ["User Story"]},
        "EpicCategory": {"default_type": "Epic", "types": ["Epic"]},
    },
}
CFG = {"types": {"nfr": "User Story", "question": "Issue"}}


# --- helpers ---------------------------------------------------------------------------------------------------------

def rows(kinds=KINDS, cfg=None, schema=None, root=REPO):
    return src.projections(root, CFG if cfg is None else cfg, SCHEMA if schema is None else schema, list(kinds))


def of(kind, **kw):
    return {p["id"]: p for p in rows([kind], **kw)}


def copy_repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(REPO, root)
    return root


def tree_sha(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def put(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def edit(root: Path, rel: str, old: str, new: str) -> None:
    path = root / rel
    text = path.read_text(encoding="utf-8")
    assert old in text, (rel, old)
    path.write_text(text.replace(old, new), encoding="utf-8")


def strings(value):
    """Every string in a projection, keys included, however deep."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from strings(k)
            yield from strings(v)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for v in value:
            yield from strings(v)


def src_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def assert_no_identity(obj) -> None:
    for text in strings(obj):
        assert not bc.EMAIL_RE.search(text), f"an address in {text!r}"
        assert not bc.GUID_RE.search(text), f"a GUID in {text!r}"
        assert "example.com" not in text and "Pat Example" not in text, text


@pytest.fixture
def hooks() -> types.ModuleType:
    """A stand-in `ado_sync_sources` hook table: the module registers into this, never into the real one."""
    stub = types.ModuleType("ado_sync_sources")
    stub.SOURCES, stub.PARENT_RESOLVERS = {}, {}
    return stub


@pytest.fixture
def snapshot() -> dict:
    return dict(src.SOURCES)


@pytest.fixture
def p1(monkeypatch, hooks):
    """`ado_sync_sources_p1` imported afresh: its import-time registration lands in `hooks`, and `sys.modules` is
    restored at teardown so a cached copy never hides the registration from the next importer."""
    monkeypatch.setitem(sys.modules, "ado_sync_sources_p1", None)  # recorded: undone at teardown
    del sys.modules["ado_sync_sources_p1"]
    with monkeypatch.context() as inner:
        inner.setitem(sys.modules, "ado_sync_sources", hooks)
        return importlib.import_module("ado_sync_sources_p1")


# --- registration through ado_sync_sources' extend-only tables --------------------------------------------------------

def test_importing_the_module_registers_the_five_breadth_kinds_and_nothing_else(hooks, p1):
    assert set(hooks.SOURCES) == set(KINDS) == set(model.BREADTH_KINDS)
    assert hooks.SOURCES["nfr"] is p1.load_nfrs and hooks.SOURCES["rule"] is p1.load_rules
    assert hooks.SOURCES["question"] is p1.load_questions and hooks.SOURCES["lifecycle"] is p1.load_lifecycle
    assert hooks.SOURCES["measurement"] is p1.load_measurements
    assert hooks.PARENT_RESOLVERS == {}, "each loader names its own parent: no resolver is registered"


def test_registration_is_extend_only_and_repeatable(hooks, p1):
    spec_loader, resolver = object(), object()
    hooks.SOURCES["spec"], hooks.PARENT_RESOLVERS["feature"] = spec_loader, resolver
    assert p1._register(hooks) is True and p1._register(hooks) is True
    assert hooks.SOURCES["spec"] is spec_loader and hooks.PARENT_RESOLVERS["feature"] is resolver
    assert set(hooks.SOURCES) == {"spec", *KINDS} and set(hooks.PARENT_RESOLVERS) == {"feature"}


def test_without_the_hook_table_nothing_is_registered_and_nothing_fails(p1, monkeypatch):
    assert p1._register(types.SimpleNamespace()) is False
    assert p1._register(types.SimpleNamespace(SOURCES=None)) is False
    monkeypatch.setitem(sys.modules, "ado_sync_sources", None)  # an import of it now fails
    assert p1._register() is False


def test_the_fresh_import_leaves_the_real_hook_table_and_sys_modules_as_they_were(snapshot, p1):
    assert src.SOURCES == snapshot, "importing the module afresh must not register a source in the real table"
    assert sys.modules["ado_sync_sources"] is src


def test_the_cli_imports_the_module_so_the_real_table_has_every_breadth_kind():
    assert set(model.BREADTH_KINDS) <= set(src.SOURCES), sorted(set(model.BREADTH_KINDS) - set(src.SOURCES))
    assert src.SOURCES["nfr"] is breadth.load_nfrs and src.SOURCES["lifecycle"] is breadth.load_lifecycle
    assert src.SOURCES["measurement"] is breadth.load_measurements
    assert set(KINDS) == set(model.BREADTH_KINDS) and set(KINDS) <= set(bc.KINDS)
    assert re.search(r"^import ado_sync_sources_p1\b", Path(ado_sync.__file__).read_text(encoding="utf-8"), re.M)


def test_the_loaders_answer_through_projections_and_standalone_with_the_repository_alone():
    assert {p["kind"] for p in rows()} == set(KINDS)
    assert [p["kind"] for p in breadth.load_nfrs(REPO)][:1] == ["nfr"]
    assert [p["kind"] for p in breadth.load_lifecycle(REPO)] == ["lifecycle"], "cfg and schema are optional standalone"
    assert {p["kind"] for p in breadth.load_measurements(REPO)} == {"measurement"}


# --- the contract every projection keeps -------------------------------------------------------------------------------

def test_every_projection_carries_the_sheets_keys_and_a_valid_ref():
    out = rows()
    assert {p["kind"] for p in out} == set(KINDS)
    for p in out:
        assert PINNED <= set(p), p["ref"]
        assert bc.REF_RE.fullmatch(p["ref"]) and p["ref"].split(":")[1] == p["kind"], "the ref's segment is the kind"
        assert p["ref"] in p["tags"] and isinstance(p["tags"], set) and isinstance(p["related_refs"], list)
        assert bc.HASH_RE.fullmatch(p["source_sha"])
        assert not Path(p["source_path"]).is_absolute() and "\\" not in p["source_path"]
        assert (REPO / p["source_path"]).is_file()
        assert "System.Title" in p["fields"]
        if p["kind"] == "measurement":  # the design's §6.1: the title is the row's Outcome cell, the id is not in it
            assert p["fields"]["System.Title"] == p["title"] and p["id"].endswith(src_slug(p["title"]))
        else:
            assert p["fields"]["System.Title"].startswith(p["id"] if p["kind"] != "lifecycle" else "Sample")


def test_projections_write_nothing_and_leave_every_fixture_byte_identical():
    before = tree_sha(REPO)
    assert len(before) >= 9
    rows()
    for loader in (breadth.load_nfrs, breadth.load_rules, breadth.load_questions, breadth.load_lifecycle,
                   breadth.load_measurements):
        loader(REPO)
        loader(REPO, CFG, SCHEMA)
    assert tree_sha(REPO) == before


def test_no_address_guid_or_name_reaches_any_projection_field_tag_or_note():
    out = rows()
    assert len(out) >= 15
    assert_no_identity(out)
    for p in out:
        assert "System.AssignedTo" not in p["fields"], "an owner is never resolved to a sign-in address here"


def test_a_missing_artifact_is_no_rows_never_an_error_or_a_placeholder(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    for kind in KINDS:
        assert rows([kind], root=empty) == [], kind


def test_the_module_reads_files_and_writes_spawns_and_prints_nothing():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "rename", "touch", "symlink_to",
                        "write", "run", "Popen", "system"}, attrs
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"open", "print", "input", "exec", "eval", "__import__"}, called
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not imported & {"subprocess", "ado_transport", "ado_wit", "ado_sync", "sprint", "spec_transition",
                           "new_spec", "handoff"}, imported


def test_the_module_has_no_shell_no_join_and_no_preview_revision():
    text = MODULE.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s+subprocess\b", text, re.M)
    assert not re.search(r"shell\s*=\s*True|shlex\.join|-preview\.\d", text)


def test_a_source_that_resolves_outside_the_repository_is_refused(tmp_path):
    root = copy_repo(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text((root / RULES_REL).read_text(encoding="utf-8"), encoding="utf-8")
    (root / RULES_REL).unlink()
    try:
        (root / RULES_REL).symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    with pytest.raises(ValueError, match="outside the repository"):
        rows(["rule"], root=root)


# --- NFRs ----------------------------------------------------------------------------------------------------------------

def test_nfr_rows_are_the_definition_rows_in_id_order_and_the_test_plan_defines_nothing():
    found = of("nfr")
    assert list(found) == ["NFR-OI01", "NFR-P01", "NFR-P02", "NFR-PR01", "NFR-SEC01"]
    assert [p["ref"] for p in found.values()] == ["sdlc:nfr:OI01", "sdlc:nfr:P01", "sdlc:nfr:P02", "sdlc:nfr:PR01",
                                                  "sdlc:nfr:SEC01"]
    assert found["NFR-P01"]["title"] == "Response time (p95)"
    assert found["NFR-P01"]["fields"]["System.Title"] == "NFR-P01 · Response time (p95)"
    assert found["NFR-P01"]["source_path"] == NFR_REL
    assert all(p["status"] is None and p["related_refs"] == [] for p in found.values()), "State is the board's"
    assert "NFR-P03" not in found, "a row with no requirement text is not an NFR"
    assert "NFR-C01" not in found, "the template's stand-in row is not an NFR"


def test_an_nfr_under_a_domain_heading_is_parented_to_that_domain_whatever_its_category_heading():
    found = of("nfr")
    assert found["NFR-OI01"]["parent_ref"] == "sdlc:domain:order-intake"      # `## Order Intake` > `### Performance`
    assert found["NFR-PR01"]["parent_ref"] == "sdlc:domain:pricing-rules"     # directly under `## Pricing Rules`
    assert found["NFR-OI01"]["parent_note"] is None and found["NFR-PR01"]["parent_note"] is None


def test_an_nfr_outside_any_domain_heading_has_no_parent_and_says_why():
    found = of("nfr")
    for ident in ("NFR-P01", "NFR-P02", "NFR-SEC01"):
        assert found[ident]["parent_ref"] is None
        assert found[ident]["parent_note"].startswith("no parent"), ident
        assert "domain heading" in found[ident]["parent_note"]


def test_the_domain_ref_is_the_one_the_domain_source_makes():
    import ado_sync_sources_tree as tree
    domains = {d["ref"] for d in tree.load_domains(REPO)}
    assert {p["parent_ref"] for p in of("nfr").values() if p["parent_ref"]} <= domains


@pytest.mark.parametrize("change, expected", [
    ("missing", "no parent: requirements.md was not found, so no domain is known"),
    ("flat", "no parent: requirements.md declares no domains"),
    ("broken", "no parent: requirements.md does not read as domains (plan --kind domain says why)"),
])
def test_without_usable_domains_every_nfr_is_unparented_with_the_reason(tmp_path, change, expected):
    root = copy_repo(tmp_path)
    req = f"{ARTIFACTS}/01-requirements/requirements.md"
    if change == "missing":
        (root / req).unlink()
    elif change == "flat":
        edit(root, req, "| Order Intake | 2 | 0 | 0 | 2 |\n| Pricing Rules | 1 | 0 | 0 | 1 |\n", "")
        edit(root, req, "### Order Intake\n\n", "")
        edit(root, req, "### Pricing Rules\n\n", "")
    else:
        edit(root, req, "| Pricing Rules | 1 | 0 | 0 | 1 |\n", "")      # a `### Pricing Rules` heading with no row
    found = of("nfr", root=root)
    assert sorted(found) == ["NFR-OI01", "NFR-P01", "NFR-P02", "NFR-PR01", "NFR-SEC01"]
    assert all(p["parent_ref"] is None and p["parent_note"] == expected for p in found.values()), change


def test_priority_and_acceptance_criteria_appear_only_when_the_resolved_type_carries_them():
    story = of("nfr", cfg={"types": {"nfr": "User Story"}})
    assert story["NFR-P01"]["fields"][PRIORITY] == 1 and story["NFR-PR01"]["fields"][PRIORITY] == 2
    assert story["NFR-P01"]["fields"][AC] == ("Threshold: &lt; 300ms<br>Measurement Method: Load test<br>"
                                              "Measurement Basis: Measured: profiling")
    assert story["NFR-SEC01"]["fields"][AC] == "Standard / Reference: OAuth2 with short-lived tokens"
    epic = of("nfr", cfg={"types": {"nfr": "Epic"}})
    assert epic["NFR-P01"]["fields"][PRIORITY] == 1 and all(AC not in p["fields"] for p in epic.values())
    issue = of("nfr", cfg={"types": {"nfr": "Issue"}})
    assert all(PRIORITY not in p["fields"] and AC not in p["fields"] for p in issue.values()), "fields never read"
    assert all(PRIORITY not in p["fields"] and AC not in p["fields"] for p in of("nfr", schema={}).values())
    assert all(PRIORITY not in p["fields"] for p in of("nfr", cfg={}).values()), "no type: no type-only field"


def test_the_chosen_type_travels_with_the_row_as_neutral_keys_and_never_as_an_op():
    found = of("nfr", cfg={"types": {"nfr": "User Story"}})
    for p in found.values():
        assert (p["fields"]["type_name"], p["fields"]["type_route"]) == ("User Story", "types.nfr")
        ops = {op["path"] for op in model.diff(p, None, model.ownership_for("nfr"))}
        assert "/fields/type_name" not in ops and "/fields/type_route" not in ops
        assert {"/fields/System.Title", f"/fields/{PRIORITY}"} <= ops


def test_the_nfr_type_follows_types_requirement_when_it_is_not_pinned_itself():
    found = of("nfr", cfg={"types": {"requirement": "User Story"}})
    assert {p["fields"]["type_route"] for p in found.values()} == {"types.requirement"}
    assert {p["fields"]["type_name"] for p in found.values()} == {"User Story"}
    own = of("nfr", cfg={"types": {"nfr": "Epic", "requirement": "User Story"}})
    assert {p["fields"]["type_name"] for p in own.values()} == {"Epic"}, "the kind's own pin is the more specific"


def test_an_nfr_with_no_resolvable_type_names_no_type_and_says_so():
    for cfg in ({}, {"types": {"nfr": "No Such Type"}}):
        found = of("nfr", cfg=cfg)
        for p in found.values():
            assert "type_name" not in p["fields"] and "type_route" not in p["fields"]
            assert any(n.startswith("type not set") for n in p["notes"]), (cfg, p["notes"])


def test_a_pin_the_process_lacks_is_not_replaced_by_a_default():
    found = of("nfr", cfg={"types": {"nfr": "No Such Type", "requirement": "User Story"}})
    assert all("type_name" not in p["fields"] for p in found.values())


def test_a_row_that_still_holds_template_placeholders_is_listed_and_flagged():
    found = of("nfr")
    note = " ".join(found["NFR-P02"]["notes"])
    assert "placeholder" in note and "Threshold" in note and "Measurement Method" in note
    assert AC not in found["NFR-P02"]["fields"], "an unfilled cell is never pushed"
    assert not [n for n in found["NFR-P01"]["notes"] if "placeholder" in n]


def test_a_column_that_is_an_activity_metric_is_never_pushed_and_the_note_says_so(tmp_path):
    root = copy_repo(tmp_path)
    edit(root, NFR_REL, "| NFR ID | Requirement | Threshold | Measurement Method | Priority |\n"
                        "|--------|-------------|-----------|-------------------|----------|\n"
                        "| NFR-OI01 | Duplicate check latency | < 100ms at p95 | APM trace | P0 |",
         "| NFR ID | Requirement | Effort | Threshold | Priority |\n"
         "|--------|-------------|--------|-----------|----------|\n"
         "| NFR-OI01 | Duplicate check latency | 13 story points | < 100ms at p95 | P0 |")
    p = of("nfr", root=root)["NFR-OI01"]
    assert p["fields"][AC] == "Threshold: &lt; 100ms at p95"
    assert "13" not in json.dumps(p, default=sorted) and "points" not in p["fields"][AC]
    assert any("Effort column is an activity metric" in n for n in p["notes"])


def test_an_nfr_id_defined_twice_is_refused_naming_it(tmp_path):
    root = copy_repo(tmp_path)
    edit(root, NFR_REL, "| NFR-SEC01 | Authentication |", "| NFR-P01 | Authentication |")
    with pytest.raises(ValueError, match="NFR-P01"):
        rows(["nfr"], root=root)


def test_the_nfr_file_is_found_at_the_repository_root_and_with_crlf_line_endings(tmp_path):
    root = copy_repo(tmp_path)
    before = of("nfr", root=root)
    text = (root / NFR_REL).read_bytes().replace(b"\n", b"\r\n")
    (root / NFR_REL).unlink()
    (root / "non-functional-requirements.md").write_bytes(text)
    after = of("nfr", root=root)
    assert list(after) == list(before)
    for ident, p in after.items():
        assert p["source_path"] == "non-functional-requirements.md"
        assert (p["fields"], p["parent_ref"], p["source_sha"]) == (before[ident]["fields"], before[ident]["parent_ref"],
                                                                   before[ident]["source_sha"])


def test_editing_one_nfr_moves_the_source_sha_of_that_row_only(tmp_path):
    root = copy_repo(tmp_path)
    before = of("nfr", root=root)
    edit(root, NFR_REL, "< 300ms | Load test", "< 250ms | Load test")
    after = of("nfr", root=root)
    moved = {i for i in before if before[i]["source_sha"] != after[i]["source_sha"]}
    assert moved == {"NFR-P01"}


def test_text_in_the_artifact_is_scrubbed_of_addresses_and_ids_before_it_reaches_a_field(tmp_path):
    root = copy_repo(tmp_path)
    edit(root, NFR_REL, "< 300ms | Load test | P0 | Measured: profiling",
         "< 300ms | ask pat.example@example.com | P0 | trace 0f8fad5b-d9cb-469f-a165-70867728950e")
    p = of("nfr", root=root)["NFR-P01"]
    assert_no_identity(p)
    assert "[address removed]" in p["fields"][AC] and "[id removed]" in p["fields"][AC]


# --- business rules ------------------------------------------------------------------------------------------------------

def test_rule_rows_are_the_filled_br_rows_of_the_table_in_id_order():
    found = of("rule")
    assert list(found) == ["BR-01", "BR-02", "BR-04", "BR-05", "BR-06"]
    assert found["BR-01"]["ref"] == "sdlc:rule:01" and found["BR-01"]["source_path"] == RULES_REL
    assert found["BR-01"]["title"] == "An order repeats an existing order id"
    assert found["BR-01"]["fields"]["System.Title"] == "BR-01 · An order repeats an existing order id"
    assert "BR-03" not in found, "the template's stand-in row is not a rule"
    assert all(p["status"] is None and p["related_refs"] == [] for p in found.values())


def test_a_rule_is_parented_to_the_one_feature_whose_brief_names_it():
    found = of("rule")
    assert found["BR-01"]["parent_ref"] == "sdlc:feature:01" and found["BR-01"]["parent_note"] is None
    assert found["BR-04"]["parent_ref"] == "sdlc:feature:02" and found["BR-04"]["parent_note"] is None


def test_a_rule_two_briefs_name_is_not_guessed_and_one_no_brief_names_has_no_parent():
    found = of("rule")
    assert found["BR-02"]["parent_ref"] is None
    assert found["BR-02"]["parent_note"] == "no parent: BR-02 is named by several feature briefs (FE-01, FE-02)"
    for ident in ("BR-05", "BR-06"):
        assert found[ident]["parent_ref"] is None
        assert found[ident]["parent_note"] == f"no parent: no feature brief names {ident}"


def test_the_feature_ref_is_the_one_the_feature_source_makes():
    refs = {p["ref"] for p in rows(["feature"], cfg={}, schema={})}
    assert {p["parent_ref"] for p in of("rule").values() if p["parent_ref"]} <= refs


def test_with_no_feature_briefs_every_rule_is_unparented(tmp_path):
    root = copy_repo(tmp_path)
    for brief in (root / ARTIFACTS / "01-requirements").glob("feature-brief-*.md"):
        brief.unlink()
    found = of("rule", root=root)
    assert all(p["parent_ref"] is None and p["parent_note"].startswith("no parent") for p in found.values())


def test_briefs_that_do_not_read_cleanly_leave_the_rules_unparented_and_say_so(tmp_path):
    root = copy_repo(tmp_path)
    put(root, f"{ARTIFACTS}/01-requirements/feature-brief-FE-01-copy.md",
        (root / ARTIFACTS / "01-requirements" / "feature-brief-FE-01.md").read_text(encoding="utf-8"))
    found = of("rule", root=root)                      # FE-01 twice: `plan --kind feature` refuses it
    assert all(p["parent_ref"] is None for p in found.values())
    assert all(p["parent_note"] == "no parent: the feature briefs do not read cleanly (plan --kind feature says why)"
               for p in found.values())


def test_a_rule_pending_a_decision_names_it_as_its_predecessor_and_the_others_name_none():
    found = of("rule")
    assert found["BR-02"]["fields"]["predecessor_refs"] == ["sdlc:decision:03"]
    assert found["BR-02"]["notes"] == []
    assert found["BR-06"]["fields"]["predecessor_refs"] == ["sdlc:decision:09"]
    assert any("DL-09 is not in the decision log" in n for n in found["BR-06"]["notes"])
    for ident in ("BR-01", "BR-04", "BR-05"):
        assert "predecessor_refs" not in found[ident]["fields"]


def test_the_predecessor_is_a_neutral_key_never_a_field_op_and_never_a_related_link():
    p = of("rule")["BR-02"]
    assert "predecessor_refs" not in {op["path"].rsplit("/", 1)[-1] for op in model.diff(p, None)}
    assert p["related_refs"] == []


def test_a_pending_decision_is_not_checked_when_there_is_no_decision_log(tmp_path):
    root = copy_repo(tmp_path)
    (root / ".sdlc" / "decision-log.md").unlink()
    found = of("rule", root=root)
    assert found["BR-02"]["fields"]["predecessor_refs"] == ["sdlc:decision:03"]
    assert any("no decision log" in n and "DL-03" in n for n in found["BR-02"]["notes"])


def test_rule_text_is_its_description_block_and_never_acceptance_criteria_whatever_the_type_carries():
    """The condition, outcome and source ride the Description, which is C for a rule (design §6.1, `C: text ->
    .proposed`); AcceptanceCriteria is S for a rule, so text pushed there would be overwritten on the next apply."""
    story = of("rule", cfg={"types": {"rule": "User Story"}})            # User Story carries AcceptanceCriteria
    assert story["BR-01"]["fields"]["System.Description"] == (
        "<p><strong>Condition:</strong> An order repeats an existing order id</p>"
        "<p><strong>Outcome:</strong> Reject it with a 409</p><p><strong>Source:</strong> policy §3</p>")
    assert story["BR-02"]["fields"]["System.Description"] == (
        "<p><strong>Condition:</strong> The order total exceeds the credit limit</p>"
        "<p><strong>Outcome:</strong> Hold for review</p><p><strong>Pending decision:</strong> DL-03</p>")
    assert all(PRIORITY not in p["fields"] for p in story.values()), "a rule has no priority"
    for cfg, schema in (({"types": {"rule": "User Story"}}, None), ({"types": {"rule": "Issue"}}, None),
                        ({}, None), ({}, {})):
        found = of("rule", cfg=cfg, schema=schema)
        assert found and all(AC not in p["fields"] for p in found.values()), (cfg, schema)
        assert all(p["fields"]["System.Description"].startswith("<p><strong>Condition:</strong> ")
                   for p in found.values()), (cfg, schema)


def test_the_rule_type_defaults_to_the_requirement_category_and_a_pin_wins():
    default = of("rule", cfg={})
    assert {(p["fields"]["type_name"], p["fields"]["type_route"]) for p in default.values()} == {
        ("User Story", "RequirementCategory")}
    pinned = of("rule", cfg={"types": {"rule": "Issue"}})
    assert {(p["fields"]["type_name"], p["fields"]["type_route"]) for p in pinned.values()} == {("Issue", "types.rule")}
    assert AC not in default["BR-01"]["fields"], "the default type carries the field, and a rule still never sets it"
    assert default["BR-01"]["fields"]["System.Description"].startswith("<p><strong>Condition:</strong> ")


# The design's §6.1 Ownership column for the text each breadth kind pushes: the lifecycle is "S all", a measurement
# "S: title, block", an NFR and a `BR-NN` "C: text -> .proposed"; a question pushes no text at all.
TEXT_OWNER = {"nfr": "C", "rule": "C", "question": None, "lifecycle": "S", "measurement": "S"}
ALL_TYPED = {"types": {"nfr": "User Story", "rule": "User Story", "question": "Issue", "measurement": "Issue"}}


def test_the_text_owner_table_covers_exactly_the_breadth_kinds():
    assert set(TEXT_OWNER) == set(model.BREADTH_KINDS) == set(KINDS)


@pytest.mark.parametrize("kind", KINDS)
def test_the_text_each_breadth_kind_pushes_rides_a_field_with_the_design_s_owner_letter(kind):
    own = model.ownership_for(kind)
    found = rows([kind], cfg=ALL_TYPED)
    assert found, kind
    letters = {own[ref] for p in found for ref in p["fields"] if ref in model.FREE_TEXT_FIELDS}
    assert letters == ({TEXT_OWNER[kind]} if TEXT_OWNER[kind] else set()), kind


@pytest.mark.parametrize("kind", ("nfr", "rule"))
def test_a_board_edit_to_a_co_owned_kind_s_text_is_never_an_op_the_next_apply_sends(kind):
    """Spec 0038's Why-this-tier: a wrong owner letter would make a board edit read as drift the repository
    overwrites. Every text field edited on the board, every other field as pushed: the push is empty, and an edit
    to the text the row pushed is the board's change, never drift."""
    own = model.ownership_for(kind)
    classified = 0
    for p in rows([kind], cfg=ALL_TYPED):
        pushed = {ref: v for ref, v in p["fields"].items() if model.REFERENCE_NAME_RE.fullmatch(ref)}
        typed = {ref: "<p>typed on the board</p>" for ref in model.FREE_TEXT_FIELDS - {model.HISTORY_FIELD}}
        remote = {"id": 4601, "rev": 4, "tags": set(p["tags"]), "title": pushed["System.Title"],
                  "fields": {**pushed, **typed}}
        assert model.diff(p, remote, own) == [], p["ref"]
        edits = {ref: {"oldValue": pushed[ref], "newValue": text} for ref, text in typed.items() if ref in pushed}
        if not edits:
            continue  # a row with no filled text pushes none (NFR-P02)
        classified += 1
        ledger = {"ts": "2026-10-12T09:02:00Z", "event": "applied", "ref": p["ref"], "kind": kind, "work_item": 4601,
                  "rev_after": 3, "projection_hash": model.projection_hash(p)}
        update = {"id": 4, "workItemId": 4601, "rev": 4, "revisedDate": "9999-01-01T00:00:00Z",
                  "fields": {"System.Rev": {"oldValue": 3, "newValue": 4}, **edits}}
        got = model.classify_drift(ledger, {**remote, "rev": 4}, p, [update])
        assert got["class"] == "ADO_OWNED_CHANGE", (p["ref"], got)
        assert {f["field"]: f["owner"] for f in got["fields"]} == dict.fromkeys(edits, "C"), p["ref"]
    assert classified >= 2, f"the fixture holds at least two {kind} rows with text"


def test_the_approver_is_never_read_so_no_address_or_name_leaves_the_table():
    found = of("rule")
    assert_no_identity(found)
    assert "BR-04" in found and "approver" not in json.dumps(found["BR-04"], default=sorted).lower()


def test_a_rule_id_defined_twice_is_refused_naming_it(tmp_path):
    root = copy_repo(tmp_path)
    edit(root, RULES_REL, "| BR-05 |", "| BR-01 |")
    with pytest.raises(ValueError, match="BR-01"):
        rows(["rule"], root=root)


def test_the_rule_table_is_found_by_its_columns_not_its_position(tmp_path):
    root = copy_repo(tmp_path)
    edit(root, RULES_REL, "Owned by", "| Note | Where |\n|------|-------|\n| a | b |\n\nOwned by")
    assert list(of("rule", root=root)) == ["BR-01", "BR-02", "BR-04", "BR-05", "BR-06"]


def test_editing_one_rule_moves_the_source_sha_of_that_row_only(tmp_path):
    root = copy_repo(tmp_path)
    before = of("rule", root=root)
    edit(root, RULES_REL, "Flag it for a manual check", "Flag it for a manual weight check")
    after = of("rule", root=root)
    assert {i for i in before if before[i]["source_sha"] != after[i]["source_sha"]} == {"BR-05"}


# --- discovery questions -------------------------------------------------------------------------------------------------

def test_question_rows_are_the_numbered_entries_of_every_block_including_one_the_shape_does_not_declare():
    found = of("question")
    assert list(found) == ["Q-01", "Q-02", "Q-03", "Q-04"], "the template-token entry is not a question"
    assert [p["ref"] for p in found.values()] == [f"sdlc:question:0{n}" for n in (1, 2, 3, 4)]
    assert found["Q-01"]["title"] == "Who owns the order desk?"
    assert found["Q-01"]["fields"]["System.Title"] == "Q-01 · Who owns the order desk?"
    assert found["Q-01"]["source_path"] == QUESTIONS_REL
    assert [p["fields"]["block"] for p in found.values()] == ["Problem", "Problem", "Success Metric", "Compliance"]
    assert [p["fields"]["route"] for p in found.values()] == ["workshop", "pre-workshop", "interview", "workshop"]
    assert all(p["parent_ref"] is None and p["related_refs"] == [] for p in found.values())


def test_a_question_is_answered_by_an_inline_answer_or_a_row_of_the_log_and_open_otherwise():
    found = of("question")
    assert {i: p["status"] for i, p in found.items()} == {"Q-01": "open", "Q-02": "answered", "Q-03": "answered",
                                                          "Q-04": "open"}
    assert found["Q-04"]["tags"] == {"sdlc:question:04", "sdlc:status:open"}
    assert found["Q-03"]["tags"] == {"sdlc:question:03", "sdlc:status:answered"}


def test_the_answer_text_never_reaches_the_projection():
    blob = json.dumps(rows(["question"]), default=sorted)
    assert "Two feeds" not in blob and "Four days" not in blob and "Finance contact" not in blob


def test_the_owner_is_carried_only_as_a_roster_style_handle():
    found = of("question")
    assert found["Q-01"]["fields"]["owner_handle"] == "@priya-n"
    for ident in ("Q-02", "Q-03", "Q-04"):
        assert "owner_handle" not in found[ident]["fields"], "a role, a name or an address is not carried"
    assert_no_identity(found)


def test_the_state_comes_from_the_status_on_the_pinned_type_and_is_absent_without_one():
    found = of("question")                                    # types.question: Issue
    assert found["Q-01"]["fields"]["System.State"] == "To Do"
    assert found["Q-02"]["fields"]["System.State"] == "Done"
    assert (found["Q-01"]["fields"]["type_name"], found["Q-01"]["fields"]["type_route"]) == ("Issue", "types.question")
    bare = of("question", cfg={})
    assert all("System.State" not in p["fields"] and "type_name" not in p["fields"] for p in bare.values())
    assert all(any("types.question not set" in n for n in p["notes"]) for p in bare.values())


def test_a_states_rule_for_questions_is_applied_to_the_chosen_type():
    cfg = {**CFG, "states": {"question": {"closed": {"category": "Completed", "prefer": "Doing"}}}}
    found = of("question", cfg=cfg)
    assert found["Q-02"]["fields"]["System.State"] == "Doing"
    assert found["Q-01"]["fields"]["System.State"] == "To Do"


def test_only_the_questions_section_is_read_and_a_list_without_one_is_read_whole(tmp_path):
    root = copy_repo(tmp_path)
    with open(root / QUESTIONS_REL, "a", encoding="utf-8") as handle:
        handle.write("\n#### Q-09: A heading left in the log\n- **Answer:** open\n")
    assert "Q-09" not in of("question", root=root), "the Answer Log is not the question list"
    edit(root, QUESTIONS_REL, "## Questions\n", "## Open Questions\n")
    whole = of("question", root=root)
    assert set(whole) == {"Q-01", "Q-02", "Q-03", "Q-04"}, "read whole, but never from the Answer Log"


def test_a_question_with_no_text_is_not_a_question_and_a_long_one_is_cut_with_a_note(tmp_path):
    root = copy_repo(tmp_path)
    edit(root, QUESTIONS_REL, "#### Q-04: Is there a data residency rule?", "#### Q-04:")
    edit(root, QUESTIONS_REL, "#### Q-03: What is the baseline order turnaround?", "#### Q-03: " + "long " * 80)
    found = of("question", root=root)
    assert "Q-04" not in found
    title = found["Q-03"]["fields"]["System.Title"]
    assert len(title) == 255 and title.endswith("…")
    assert any("title cut to 255" in n for n in found["Q-03"]["notes"])


def test_editing_one_answer_moves_the_source_sha_of_that_question_only(tmp_path):
    root = copy_repo(tmp_path)
    before = of("question", root=root)
    edit(root, QUESTIONS_REL, "- **Likely answerer:** Legal", "- **Likely answerer:** Legal counsel")
    after = of("question", root=root)
    assert {i for i in before if before[i]["source_sha"] != after[i]["source_sha"]} == {"Q-04"}


def test_a_question_number_used_twice_is_refused_naming_it(tmp_path):
    root = copy_repo(tmp_path)
    edit(root, QUESTIONS_REL, "#### Q-04:", "#### Q-01:")
    with pytest.raises(ValueError, match="Q-01"):
        rows(["question"], root=root)


def test_the_question_text_is_scrubbed_before_it_reaches_a_field(tmp_path):
    root = copy_repo(tmp_path)
    edit(root, QUESTIONS_REL, "Who owns the order desk?", "Does pat.example@example.com own the order desk?")
    p = of("question", root=root)["Q-01"]
    assert "[address removed]" in p["fields"]["System.Title"]
    assert_no_identity(p)


# --- the lifecycle item --------------------------------------------------------------------------------------------------

def test_the_lifecycle_source_yields_exactly_one_row_with_a_state_file_and_none_without(tmp_path):
    (life,) = rows(["lifecycle"])
    assert life["ref"] == "sdlc:lifecycle:project" and life["id"] == "project" and life["kind"] == "lifecycle"
    assert life["source_path"] == STATE_REL
    root = copy_repo(tmp_path)
    (root / STATE_REL).unlink()
    assert rows(["lifecycle"], root=root) == []
    assert breadth.load_lifecycle(root) == []


def test_the_lifecycle_title_is_the_project_and_a_project_with_no_name_is_titled_without_one(tmp_path):
    (life,) = rows(["lifecycle"])
    assert life["title"] == "Sample Order Portal · SDLC lifecycle"
    assert life["fields"]["System.Title"] == "Sample Order Portal · SDLC lifecycle"
    root = copy_repo(tmp_path)
    edit(root, STATE_REL, 'project_name: "Sample Order Portal"', 'project_name: "${PROJECT_NAME}"')
    (bare,) = rows(["lifecycle"], root=root)
    assert bare["fields"]["System.Title"] == "SDLC lifecycle"
    assert any("project" in n and "name" in n for n in bare["notes"])


def test_a_phase_with_no_name_takes_the_registry_s_and_a_long_project_name_is_cut_with_a_note(tmp_path):
    root = copy_repo(tmp_path)
    edit(root, STATE_REL, "    name: design\n", "")
    edit(root, STATE_REL, 'project_name: "Sample Order Portal"', 'project_name: "' + "Portal " * 50 + '"')
    (life,) = rows(["lifecycle"], root=root)
    assert life["fields"]["description_rows"][2]["name"] == "design"
    title = life["fields"]["System.Title"]
    assert len(title) == 255 and title.endswith("\u2026")
    assert any("title cut to 255" in n for n in life["notes"])


def test_the_description_block_is_the_phase_gate_and_sign_off_table_in_phase_order():
    (life,) = rows(["lifecycle"])
    table = life["fields"]["description_rows"]
    assert [r["phase"] for r in table] == ["0", "1", "2", "3", "build"]
    assert table[0] == {"phase": "0", "name": "discovery", "status": "completed", "gate": "6 passed, 0 failed, 1 manual",
                        "signed_off": "2026-09-12 by @priya-n"}
    assert table[1] == {"phase": "1", "name": "requirements", "status": "completed",
                        "gate": "8 passed, 0 failed, 2 manual", "signed_off": "2026-09-26; 2 discipline sign-offs"}
    assert table[2] == {"phase": "2", "name": "design", "status": "active", "gate": "no gate recorded",
                        "signed_off": "not yet"}
    assert [r["gate"] for r in table[3:]] == ["no gate recorded", "no gate recorded"]
    html = life["fields"]["System.Description"]
    assert html.startswith("<p>") and "<table>" in html and html.count("<tr>") == 6
    for word in ("discovery", "requirements", "design", "foundation", "build", "2026-09-12 by @priya-n"):
        assert word in html
    assert "sdlc:begin" not in html, "the markers are the patch builder's"


def test_the_description_is_html_escaped_and_carries_no_address_or_name():
    (life,) = rows(["lifecycle"])
    assert_no_identity(life)
    assert "<script" not in life["fields"]["System.Description"]


def test_a_phase_that_has_no_gate_reads_no_gate_recorded_never_a_zero_count():
    (life,) = rows(["lifecycle"])
    for row in life["fields"]["description_rows"][2:]:
        assert row["gate"] == "no gate recorded" and not re.search(r"\d", row["gate"])


@pytest.mark.parametrize("statuses, expected", [
    (("completed", "active", "pending"), "in-flight"),
    (("completed", "completed", "completed"), "closed"),
    (("pending", "pending", "pending"), "open"),
    (("active", "pending", "pending"), "in-flight"),
])
def test_the_lifecycle_status_is_read_from_the_phase_statuses(tmp_path, statuses, expected):
    root = copy_repo(tmp_path)
    state = yaml.safe_load((root / STATE_REL).read_text(encoding="utf-8"))
    state["phases"] = {str(i): {"name": n, "status": s, "gate_results": {}}
                       for i, (n, s) in enumerate(zip(("discovery", "requirements", "design"), statuses))}
    put(root, STATE_REL, yaml.safe_dump(state))
    (life,) = rows(["lifecycle"], root=root)
    assert life["status"] == expected and f"sdlc:status:{expected}" in life["tags"]


def test_the_lifecycle_state_is_resolved_on_the_type_epics_land_on_unless_it_is_pinned():
    (default,) = rows(["lifecycle"], cfg={})
    assert (default["fields"]["type_name"], default["fields"]["type_route"]) == ("Epic", "EpicCategory")
    assert default["fields"]["System.State"] == "Active"          # in-flight -> the first InProgress state
    (pinned,) = rows(["lifecycle"], cfg={"types": {"lifecycle": "Issue"}})
    assert (pinned["fields"]["type_name"], pinned["fields"]["type_route"]) == ("Issue", "types.lifecycle")
    assert pinned["fields"]["System.State"] == "Doing"
    (via_epic,) = rows(["lifecycle"], cfg={"types": {"epic": "User Story"}})
    assert (via_epic["fields"]["type_name"], via_epic["fields"]["type_route"]) == ("User Story", "types.epic")


def test_a_lifecycle_pin_the_process_lacks_is_not_replaced_by_the_default():
    (life,) = rows(["lifecycle"], cfg={"types": {"lifecycle": "No Such Type"}})
    assert "type_name" not in life["fields"] and "System.State" not in life["fields"]
    assert any("type not set" in n for n in life["notes"])


def test_a_states_rule_for_the_lifecycle_is_applied_even_on_the_default_type():
    cfg = {"states": {"lifecycle": {"in-flight": {"category": "Proposed", "prefer": "New"}}}}
    (life,) = rows(["lifecycle"], cfg=cfg)
    assert life["fields"]["System.State"] == "New"


def test_the_lifecycle_description_is_the_s_owned_block_and_state_is_s_owned_too():
    (life,) = rows(["lifecycle"], cfg={})
    ownership = model.ownership_for("lifecycle")
    assert ownership["System.Description"] == "S" and ownership["System.State"] == "S"
    ops = {op["path"] for op in model.diff(life, None, ownership)}
    assert {"/fields/System.Title", "/fields/System.Description", "/fields/System.State"} <= ops


def test_the_lifecycle_source_sha_is_the_table_not_the_state_file(tmp_path):
    root = copy_repo(tmp_path)
    (before,) = rows(["lifecycle"], root=root)
    edit(root, STATE_REL, '      requirements.md: "0123456789abcdef"', '      requirements.md: "fedcba9876543210"')
    (same,) = rows(["lifecycle"], root=root)
    assert same["source_sha"] == before["source_sha"], "an artifact checksum is not on the board"
    edit(root, STATE_REL, "    status: active", "    status: completed")
    (moved,) = rows(["lifecycle"], root=root)
    assert moved["source_sha"] != before["source_sha"]


def test_a_state_file_with_no_phases_is_still_the_lifecycle_item_and_says_so(tmp_path):
    root = copy_repo(tmp_path)
    put(root, STATE_REL, 'version: "1.0"\nproject_name: "Sample Order Portal"\n')
    (life,) = rows(["lifecycle"], root=root)
    assert life["status"] is None and life["fields"]["description_rows"] == []
    assert "System.State" not in life["fields"] and "No phases" in life["fields"]["System.Description"]


@pytest.mark.parametrize("text", ["phases: [unterminated\n  - a: b: c\n", "- just\n- a list\n"])
def test_a_state_file_that_is_not_a_mapping_is_refused_naming_it(tmp_path, text):
    root = copy_repo(tmp_path)
    put(root, STATE_REL, text)
    with pytest.raises(ValueError, match="state.yaml"):
        rows(["lifecycle"], root=root)


def test_the_signer_is_shown_only_as_a_roster_style_handle(tmp_path):
    root = copy_repo(tmp_path)
    edit(root, STATE_REL, 'signed_off_by: "pat.example@example.com"', 'signed_off_by: "Pat Example"')
    (life,) = rows(["lifecycle"], root=root)
    assert life["fields"]["description_rows"][1]["signed_off"] == "2026-09-26; 2 discipline sign-offs"
    assert_no_identity(life)
    edit(root, STATE_REL, 'signed_off_by: "Pat Example"', "signed_off_by: null")
    (unsigned,) = rows(["lifecycle"], root=root)
    assert unsigned["fields"]["description_rows"][1]["signed_off"] == ("advanced 2026-09-26, no named sign-off; "
                                                                      "2 discipline sign-offs")


# --- measurements --------------------------------------------------------------------------------------------------------

MEASURE_CFG = {"types": {"measurement": "Issue"}}


def test_measurement_rows_are_the_threshold_rows_of_each_dimension_in_document_order():
    assert [p["id"] for p in breadth.load_measurements(REPO)] == [
        "1-pass-exceeds-expectations", "1-partial", "1-fail", "2-pass", "2-partial"]
    found = of("measurement")
    assert set(found) == {"1-pass-exceeds-expectations", "1-partial", "1-fail", "2-pass", "2-partial"}
    assert all(p["ref"] == f"sdlc:measurement:{p['id']}" for p in found.values()), "the id is the ref whole"
    assert not any(i.startswith("3-") for i in found), "a dimension with no threshold table has no measurement"


def test_a_threshold_row_with_no_outcome_cell_is_not_a_measurement():
    found = of("measurement")
    assert {i for i in found if i.startswith("2-")} == {"2-pass", "2-partial"}
    assert not any("Under 50%" in p["title"] for p in found.values())


def test_a_measurement_is_parented_to_its_dimension_s_outcome_the_ref_the_outcome_source_makes():
    outcomes = {o["id"].split("-", 1)[0]: o["ref"] for o in tree.load_outcomes(REPO)}
    assert outcomes == {"1": "sdlc:outcome:1-turnaround-time", "2": "sdlc:outcome:2-adoption",
                        "3": "sdlc:outcome:3-data-quality"}
    for p in of("measurement").values():
        assert p["parent_ref"] == outcomes[p["id"].split("-", 1)[0]] and p["parent_note"] is None, p["ref"]


def test_a_measurement_reads_exactly_the_threshold_rows_its_outcome_carries_in_its_block():
    by_outcome = {o["ref"]: o["fields"]["description_rows"] for o in tree.load_outcomes(REPO)}
    for p in of("measurement").values():
        (row,) = p["fields"]["description_rows"]
        assert row in by_outcome[p["parent_ref"]], p["ref"]


def test_the_title_is_the_row_s_outcome_cell_and_the_block_is_its_threshold_and_how_measured():
    first = of("measurement")["1-pass-exceeds-expectations"]
    assert first["title"] == first["fields"]["System.Title"] == "Pass (exceeds expectations)"
    assert first["fields"]["System.Description"] == (
        "<p><strong>Threshold:</strong> Median under 2 minutes</p>"
        "<p><strong>How We'll Measure:</strong> Timestamp difference in the order log</p>")
    assert first["status"] is None and first["tags"] == {first["ref"]}


def test_a_placeholder_cell_is_left_out_of_the_block_and_the_row_says_which_column(tmp_path):
    partial = of("measurement")["2-partial"]
    assert "[Specific" not in partial["fields"]["System.Description"]
    assert "Sign-in count" in partial["fields"]["System.Description"]
    assert any("template placeholders (Threshold)" in n for n in partial["notes"]), partial["notes"]
    root = copy_repo(tmp_path)
    edit(root, SUCCESS_REL, "| Pass | 80% of desks active weekly | Sign-in count against the desk list |",
         "| Pass | [Specific number/condition] | [Measurement method] |")
    bare = of("measurement", root=root)["2-pass"]
    assert "System.Description" not in bare["fields"], "nothing filled: no block, never an empty or invented one"
    assert any("no threshold or how-measured text" in n for n in bare["notes"]), bare["notes"]


def test_without_a_types_measurement_pin_a_row_has_no_type_and_stays_in_its_outcome_s_block():
    for p in of("measurement").values():
        assert "type_name" not in p["fields"] and "type_route" not in p["fields"], p["ref"]
        assert "System.State" not in p["fields"]
        (note,) = [n for n in p["notes"] if n.startswith("no item: ")]
        assert "types.measurement not set" in note and "stays in the block of Outcome " in note, note
    one = of("measurement")["1-fail"]
    assert any("stays in the block of Outcome 1 · Turnaround time" in n for n in one["notes"]), one["notes"]


def test_a_measurement_never_falls_back_to_a_default_type_even_when_the_process_has_one():
    cfg = {"types": {"requirement": "User Story", "epic": "Epic", "spec": "User Story"}}
    for p in of("measurement", cfg=cfg).values():
        assert "type_name" not in p["fields"] and any(n.startswith("no item: ") for n in p["notes"]), p["ref"]


def test_a_pinned_measurement_type_travels_with_the_row_and_no_state_is_ever_set():
    found = of("measurement", cfg=MEASURE_CFG)
    for p in found.values():
        assert (p["fields"]["type_name"], p["fields"]["type_route"]) == ("Issue", "types.measurement"), p["ref"]
        assert "System.State" not in p["fields"], "State is the board's (A); a measurement has no status to push"
        assert not any(n.startswith("no item: ") for n in p["notes"]), p["notes"]
    assert model.ownership_for("measurement")["System.State"] == "A"


def test_a_measurement_pin_the_process_lacks_is_not_replaced_and_says_so():
    cfg = {"types": {"measurement": "Key Result"}}
    for p in of("measurement", cfg=cfg).values():
        assert "type_name" not in p["fields"]
        assert any("pins 'Key Result' but the process has no such type" in n for n in p["notes"]), p["notes"]


def test_fields_for_measurements_are_not_applied_and_the_row_says_so():
    cfg = {**MEASURE_CFG, "fields": {"measurement": {"actual": "Custom.Actual"}}}
    for p in of("measurement", cfg=cfg).values():
        assert "Custom.Actual" not in p["fields"]
        assert any(n.startswith("fields.measurement is not applied") for n in p["notes"]), p["notes"]


def test_the_same_outcome_cell_twice_in_one_dimension_is_refused_naming_it(tmp_path):
    root = copy_repo(tmp_path)
    edit(root, SUCCESS_REL, "| Fail | Median over 5 minutes |", "| Partial | Median over 5 minutes |")
    with pytest.raises(ValueError, match="measurement 1-partial is defined twice"):
        rows(["measurement"], root=root)


def test_the_same_outcome_cell_in_two_dimensions_is_two_measurements():
    found = of("measurement")
    assert {"1-partial", "2-partial"} <= set(found)
    assert found["1-partial"]["parent_ref"] != found["2-partial"]["parent_ref"]


def test_editing_one_threshold_row_moves_the_source_sha_of_that_row_only(tmp_path):
    root = copy_repo(tmp_path)
    before = {i: p["source_sha"] for i, p in of("measurement", root=root).items()}
    edit(root, SUCCESS_REL, "Median 2 to 5 minutes", "Median 2 to 6 minutes")
    after = {i: p["source_sha"] for i, p in of("measurement", root=root).items()}
    assert {i for i in before if before[i] != after[i]} == {"1-partial"}


def test_measurement_text_is_scrubbed_and_escaped_before_it_reaches_a_field(tmp_path):
    root = copy_repo(tmp_path)
    edit(root, SUCCESS_REL, "| Median under 2 minutes | Timestamp difference in the order log |",
         "| Median under 2 minutes | Report <b>sent</b> to ops.lead@example.com, 0f8fad5b-d9cb-469f-a165-70867728950e |")
    first = of("measurement", root=root)["1-pass-exceeds-expectations"]
    assert_no_identity(first)
    block = first["fields"]["System.Description"]
    assert "&lt;b&gt;sent&lt;/b&gt;" in block and "<b>" not in block
    assert "[address removed]" in block and "[id removed]" in block


def test_measurements_read_the_file_the_outcome_source_reads_and_nothing_else(tmp_path):
    root = copy_repo(tmp_path)
    (root / SUCCESS_REL).rename(root / "success-criteria.md")
    assert tree.load_outcomes(root) == [] and rows(["measurement"], root=root) == [], \
        "a measurement whose Outcome the outcome source cannot see would point at a parent that does not exist"


def test_a_success_criteria_file_with_crlf_line_endings_reads_the_same(tmp_path):
    root = copy_repo(tmp_path)
    path = root / SUCCESS_REL
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert {i: p["title"] for i, p in of("measurement", root=root).items()} == \
        {i: p["title"] for i, p in of("measurement").items()}


def test_a_success_criteria_file_that_resolves_outside_the_repository_is_refused(tmp_path):
    root = copy_repo(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text((root / SUCCESS_REL).read_text(encoding="utf-8"), encoding="utf-8")
    (root / SUCCESS_REL).unlink()
    try:
        (root / SUCCESS_REL).symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    with pytest.raises(ValueError, match="outside the repository"):
        rows(["measurement"], root=root)


# --- through the CLI -----------------------------------------------------------------------------------------------------

def cli_repo(tmp_path, az, capsys, **pins) -> Path:
    """A copy of the mini repository with the starter config (its spec field rules emptied, since they belong to the
    spec kind and are checked against the discovered process), the types a person would pin, and the discovered
    schema. Setup's own az calls are forgotten, so a test counts only what its verb spawned."""
    root = copy_repo(tmp_path)
    assert ado_sync.main(["config", "init", "--repo", str(root)]) == 0
    assert ado_sync.main(["discover", "--repo", str(root)]) == 0
    path = root / bc.CONFIG_FILE
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["fields"] = {}
    cfg["types"] = {**cfg["types"], "nfr": "User Story", "question": "Issue", **pins}
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    capsys.readouterr()
    az.calls.clear()
    az.answers["boards query"] = lambda args: []
    return root


def plan(capsys, root, *kinds):
    argv = ["plan", *[a for k in kinds for a in ("--kind", k)], "--repo", str(root), "--json"]
    code = ado_sync.main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_plan_creates_the_breadth_kinds_on_the_types_they_chose_and_skips_none(tmp_path, az, capsys):
    root = cli_repo(tmp_path, az, capsys)
    code, doc = plan(capsys, root, "lifecycle", "nfr", "rule", "question")
    assert code == 0 and doc["skipped"] == [], doc.get("skipped")
    by_ref = {r["ref"]: r for r in doc["rows"]}
    assert len(by_ref) == 1 + 5 + 5 + 4
    assert {r["action"] for r in doc["rows"]} == {"create"}, {r["ref"]: r.get("reason") for r in doc["rows"]}
    assert by_ref["sdlc:lifecycle:project"]["type"] == "Epic"
    assert by_ref["sdlc:rule:01"]["type"] == "User Story" and by_ref["sdlc:nfr:P01"]["type"] == "User Story"
    assert by_ref["sdlc:question:01"]["type"] == "Issue"
    paths = {r["ref"]: {op["path"] for op in r["ops"]} for r in doc["rows"]}
    assert "/fields/System.Description" in paths["sdlc:lifecycle:project"]
    assert "/fields/System.State" in paths["sdlc:lifecycle:project"] and "/fields/System.State" in paths["sdlc:question:01"]
    leaked = {"type_name", "type_route", "description_rows", "predecessor_refs", "block", "route", "owner_handle"}
    for ref, found in paths.items():
        assert not {p.rsplit("/", 1)[-1] for p in found} & leaked, ref
    assert by_ref["sdlc:rule:01"]["parent"]["ref"] == "sdlc:feature:01"
    assert by_ref["sdlc:nfr:OI01"]["parent"]["ref"] == "sdlc:domain:order-intake"
    assert any("BR-02 is named by several" in n for n in by_ref["sdlc:rule:02"]["notes"])
    assert_no_identity(doc)


def test_plan_with_no_pin_for_a_question_leaves_it_unmapped_with_the_process_s_candidates(tmp_path, az, capsys):
    root = cli_repo(tmp_path, az, capsys)
    cfg = yaml.safe_load((root / bc.CONFIG_FILE).read_text(encoding="utf-8"))
    del cfg["types"]["question"]
    (root / bc.CONFIG_FILE).write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    code, doc = plan(capsys, root, "question")
    assert code == 0 and len(doc["rows"]) == 4 and {r["action"] for r in doc["rows"]} == {"unmapped"}
    assert all("candidates present in process" in r["reason"] for r in doc["rows"]), doc["rows"][0]["reason"]
    assert all(r["type"] is None and not r["ops"] for r in doc["rows"]), "no type: nothing to create"


def test_plan_creates_measurements_on_the_pinned_type_under_their_outcome(tmp_path, az, capsys):
    root = cli_repo(tmp_path, az, capsys, measurement="Issue")
    code, doc = plan(capsys, root, "measurement")
    assert code == 0 and doc["skipped"] == [], doc.get("skipped")
    by_ref = {r["ref"]: r for r in doc["rows"]}
    assert set(by_ref) == {f"sdlc:measurement:{i}" for i in
                           ("1-pass-exceeds-expectations", "1-partial", "1-fail", "2-pass", "2-partial")}
    assert {r["action"] for r in doc["rows"]} == {"create"}, {r["ref"]: r.get("reason") for r in doc["rows"]}
    assert {r["type"] for r in doc["rows"]} == {"Issue"}
    first = by_ref["sdlc:measurement:1-pass-exceeds-expectations"]
    paths = {op["path"] for op in first["ops"]}
    assert {"/fields/System.Title", "/fields/System.Description"} <= paths
    assert "/fields/System.State" not in paths, "State is the board's: a measurement never pushes one"
    leaked = {"type_name", "type_route", "description_rows"}
    for r in doc["rows"]:
        assert not {op["path"].rsplit("/", 1)[-1] for op in r["ops"]} & leaked, r["ref"]
    assert first["parent"]["ref"] == "sdlc:outcome:1-turnaround-time"
    assert by_ref["sdlc:measurement:2-pass"]["parent"]["ref"] == "sdlc:outcome:2-adoption"
    assert_no_identity(doc)


def test_plan_with_no_measurement_pin_shows_every_row_unmapped_with_no_item_and_a_note(tmp_path, az, capsys):
    root = cli_repo(tmp_path, az, capsys)
    code, doc = plan(capsys, root, "measurement")
    assert code == 0 and doc["skipped"] == [], "measurement has a source: it is planned, never 'no source'"
    assert len(doc["rows"]) == 5 and {r["action"] for r in doc["rows"]} == {"unmapped"}
    assert all("types.measurement not set" in r["reason"] for r in doc["rows"]), doc["rows"][0]["reason"]
    assert all(r["type"] is None and not r["ops"] for r in doc["rows"]), "no type: no item, nothing to create"
    assert all(any("stays in the block of Outcome " in n for n in r["notes"]) for r in doc["rows"])


def test_plan_of_a_kind_whose_artifact_is_absent_is_no_rows_not_an_error(tmp_path, az, capsys):
    root = cli_repo(tmp_path, az, capsys)
    for rel in (NFR_REL, RULES_REL, QUESTIONS_REL, STATE_REL, SUCCESS_REL):
        (root / rel).unlink()
    code, doc = plan(capsys, root, "nfr", "rule", "question", "lifecycle", "measurement")
    assert code == 0 and doc["rows"] == [] and doc["skipped"] == []


def test_every_az_call_a_breadth_plan_makes_is_a_read_that_detects_nothing(tmp_path, az, capsys):
    root = cli_repo(tmp_path, az, capsys, measurement="Issue")
    code, _ = plan(capsys, root, "lifecycle", "nfr", "rule", "question", "measurement")
    assert code == 0
    assert az.written() == [], "a plan sends no write"
    assert all("--detect" in call and call[call.index("--detect") + 1] == "false" for call in az.calls)
