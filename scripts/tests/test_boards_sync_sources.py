"""The repository half of the Boards mirror: what the repo says each work item should be (B2-P3).

`ado_sync_sources.projections(repo_root, cfg, schema, kinds)` reads the spec, spike, sprint, decision, epic
and feature files and returns one projection per item. It writes nothing, spawns nothing and reads only
inside the repository. Every test here runs against the mini repository under `fixtures/boards_repo/`
(generic names) or a copy of it in `tmp_path`; the first one proves the mini repository is byte-identical
after a full read.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401

import ast
import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

import ado_sync_sources as src
import boards_contract as bc

HERE = Path(__file__).resolve().parent
REPO = HERE / "fixtures" / "boards_repo"
STARTER = yaml.safe_load((HERE.parent.parent / "templates" / "ado" / "ado.yaml").read_text(encoding="utf-8"))
MODULE = Path(src.__file__)
TEMPLATES = HERE.parent.parent / "templates" / "phases"
PINNED = {"ref", "kind", "id", "title", "status", "fields", "tags", "parent_ref", "parent_note", "related_refs",
          "source_path", "source_sha"}
ALL_KINDS = ["epic", "feature", "spec", "spike", "sprint", "decision"]
FIXTURE_KINDS = ["epic", "feature", "spec", "sprint", "decision"]  # the mini repository has no spikes
PRIORITY = "Microsoft.VSTS.Common.Priority"
ITERATION = "System.IterationPath"


def _states(*pairs):
    return [{"name": n, "category": c, "order": i} for i, (n, c) in enumerate(pairs)]


def _field(ref):
    return {"type": "integer", "read_only": False, "always_required": False, "default": None, "allowed_values": None}


SCHEMA = {
    "types": {
        "User Story": {"states": _states(("New", "Proposed"), ("Ready", "Proposed"), ("Active", "InProgress"),
                                         ("Resolved", "Resolved"), ("Closed", "Completed"), ("Removed", "Removed")),
                       "fields": {PRIORITY: _field(PRIORITY)}},
        "Epic": {"states": _states(("New", "Proposed"), ("Active", "InProgress"), ("Closed", "Completed")),
                 "fields": {PRIORITY: _field(PRIORITY)}},
        "Feature": {"states": _states(("New", "Proposed"), ("Active", "InProgress"), ("Closed", "Completed")),
                    "fields": None},
        "Issue": {"states": _states(("To Do", "Proposed"), ("Doing", "InProgress"), ("Done", "Completed")),
                  "fields": None},
    },
    "categories": {
        "RequirementCategory": {"default_type": "User Story", "types": ["User Story"]},
        "EpicCategory": {"default_type": "Epic", "types": ["Epic"]},
        "FeatureCategory": {"default_type": "Feature", "types": ["Feature"]},
    },
}


def rows(kinds, cfg=None, schema=None, root=REPO):
    return src.projections(root, STARTER if cfg is None else cfg, SCHEMA if schema is None else schema, kinds)


def one(kind, ident, **kw):
    found = [p for p in rows([kind], **kw) if p["id"] == ident]
    assert len(found) == 1, (kind, ident, [p["id"] for p in rows([kind], **kw)])
    return found[0]


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


# --- the contract and the guards ---------------------------------------------------------------------------

def test_every_projection_carries_the_sheets_keys_and_a_valid_ref():
    out = rows(FIXTURE_KINDS)
    assert {p["kind"] for p in out} == set(FIXTURE_KINDS)
    for p in out:
        assert PINNED <= set(p), p["ref"]
        assert bc.REF_RE.fullmatch(p["ref"]) and p["kind"] in bc.KINDS
        assert p["ref"] in p["tags"]
        assert isinstance(p["tags"], set) and isinstance(p["related_refs"], list) and isinstance(p["fields"], dict)
        assert bc.HASH_RE.fullmatch(p["source_sha"])
        assert not Path(p["source_path"]).is_absolute() and "\\" not in p["source_path"]
        assert "source_row" not in p, "the resolver's raw material is not part of the projection"


def test_projections_write_nothing_and_leave_the_mini_repository_byte_identical():
    before = tree_sha(REPO)
    rows(FIXTURE_KINDS)
    rows(ALL_KINDS, cfg={}, schema={})
    assert tree_sha(REPO) == before, "a read changed, added or removed a file"


def test_source_sha_is_the_fingerprint_of_the_items_own_source_text_so_it_moves_with_the_item_alone(tmp_path):
    p = one("spec", "0004")
    assert p["source_path"] == "specs/0004-duplicate-claim-409.md"
    assert p["source_sha"] == hashlib.sha256((REPO / p["source_path"]).read_bytes()).hexdigest()[:12]
    before = {p["ref"]: p["source_sha"] for p in rows(["epic", "decision"])}
    assert one("epic", "EP-001")["source_path"] == "epics.md"
    assert len(set(before.values())) == len(before), "each epic and decision has a fingerprint of its own"
    root = copy_repo(tmp_path)
    epics, log = root / "epics.md", root / ".sdlc" / "decision-log.md"
    epics.write_text(epics.read_text(encoding="utf-8").replace("I do not have to ask.", "nobody has to ask."),
                     encoding="utf-8")
    log.write_text(log.read_text(encoding="utf-8").replace("Which channel ships first?", "Which channel ships second?"),
                   encoding="utf-8")
    after = {p["ref"]: p["source_sha"] for p in rows(["epic", "decision"], root=root)}
    assert {ref for ref in before if before[ref] != after[ref]} == {"sdlc:epic:002", "sdlc:decision:01"}


def test_the_module_is_read_only_and_imports_no_transport_or_process_spawner():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not imported & {"subprocess", "ado_transport", "socket", "urllib", "requests", "shutil", "os"}, imported
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "rename", "touch", "chmod",
                        "symlink_to", "write"}, attrs
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"open", "print", "input", "exec", "eval", "__import__"}, called


def test_no_email_is_read_except_through_the_rosters_email_for():
    text = MODULE.read_text(encoding="utf-8")
    assert '"email"' not in text and "'email'" not in text and "EMAIL_RE" not in text
    assert "email_for" in text


def test_unknown_kinds_and_kinds_with_no_source_are_named_never_skipped(monkeypatch):
    with pytest.raises(ValueError, match="bogus"):
        rows(["bogus"])
    monkeypatch.delitem(src.SOURCES, "decision")
    with pytest.raises(ValueError, match="decision"):
        rows(["spec", "decision"])


def test_kinds_come_back_in_the_order_asked_each_in_id_order_and_never_twice():
    out = rows(["spec", "epic", "spec"])
    assert [p["kind"] for p in out] == ["spec"] * 3 + ["epic"] * 3
    assert [p["id"] for p in out if p["kind"] == "spec"] == ["0004", "0005", "0007"]
    assert [p["id"] for p in out if p["kind"] == "epic"] == ["EP-001", "EP-002", "EP-003"]


def test_a_loader_registered_by_a_later_package_is_called_with_whichever_arguments_it_takes(monkeypatch):
    def projection(kind, ident):
        return {"ref": f"sdlc:{kind}:{ident}", "kind": kind, "id": ident, "title": "t", "status": None, "fields": {},
                "tags": [f"sdlc:{kind}:{ident}"], "parent_ref": None, "parent_note": None, "related_refs": [],
                "source_path": "x.md", "source_sha": "0" * 12}

    calls = []

    def one_arg(repo_root):
        calls.append(("one", Path(repo_root)))
        return [projection("outcome", "1")]

    def three_args(repo_root, cfg, schema):
        calls.append(("three", cfg is STARTER and schema is SCHEMA))
        return [projection("domain", "a")]

    monkeypatch.setitem(src.SOURCES, "outcome", one_arg)
    monkeypatch.setitem(src.SOURCES, "domain", three_args)
    out = rows(["outcome", "domain"])
    assert [p["ref"] for p in out] == ["sdlc:outcome:1", "sdlc:domain:a"]
    assert calls == [("one", REPO), ("three", True)]
    assert out[0]["tags"] == {"sdlc:outcome:1"} and out[0]["notes"] == []


def test_a_loader_that_returns_a_malformed_projection_is_named(monkeypatch):
    monkeypatch.setitem(src.SOURCES, "outcome", lambda repo_root: [{"ref": "sdlc:outcome:1", "kind": "outcome"}])
    with pytest.raises(ValueError, match="outcome"):
        rows(["outcome"])
    bad_ref = {"ref": "not a ref", "kind": "outcome", "id": "1", "title": "t", "status": None, "fields": {},
               "tags": set(), "parent_ref": None, "parent_note": None, "related_refs": [], "source_path": "x",
               "source_sha": "0" * 12}
    monkeypatch.setitem(src.SOURCES, "outcome", lambda repo_root: [bad_ref])
    with pytest.raises(ValueError, match="not a ref"):
        rows(["outcome"])


# --- specs ---------------------------------------------------------------------------------------------------

def test_spec_0004_names_its_feature_from_the_FE_id_in_source():
    p = one("spec", "0004")
    assert (p["ref"], p["title"], p["status"]) == ("sdlc:spec:0004", "duplicate claim 409", "ready")
    assert p["parent_ref"] == "sdlc:feature:03" and p["parent_note"] is None
    assert p["fields"]["System.Title"] == "0004 · duplicate claim 409"


def test_spec_0007_whose_source_is_a_document_has_no_parent_and_says_so():
    p = one("spec", "0007")
    assert p["parent_ref"] is None
    assert p["parent_note"] == "no parent: source names no FE-NN"


def test_the_FE_id_is_found_wherever_it_sits_in_source():
    p = one("spec", "0005")  # "FE-03 claims intake, story US-002"
    assert p["parent_ref"] == "sdlc:feature:03" and p["parent_note"] is None


def _source(root: Path, name: str, value: str):
    path = root / "specs" / name
    lines = path.read_text(encoding="utf-8").splitlines()
    lines = [f'source: "{value}"' if ln.startswith("source:") else ln for ln in lines]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_a_source_naming_two_features_is_not_guessed_and_one_naming_it_twice_is_not_two(tmp_path):
    root = copy_repo(tmp_path)
    _source(root, "0004-duplicate-claim-409.md", "FE-03 and FE-04")
    _source(root, "0005-claim-status-card.md", "FE-03, FE-03")
    two = one("spec", "0004", root=root)
    assert two["parent_ref"] is None
    assert two["parent_note"] == "no parent: source names several features (FE-03, FE-04)"
    twice = one("spec", "0005", root=root)
    assert twice["parent_ref"] == "sdlc:feature:03" and twice["parent_note"] is None


def test_the_spec_resolver_works_on_any_row_with_no_source_row_at_all():
    row = {"ref": "sdlc:spec:0004", "kind": "spec", "id": "0004", "source_path": "specs/0004-duplicate-claim-409.md"}
    assert src.PARENT_RESOLVERS["spec"](REPO, row) == ("sdlc:feature:03", None)
    gone = {**row, "source_path": "specs/9999-gone.md"}
    ref, note = src.PARENT_RESOLVERS["spec"](REPO, gone)
    assert ref is None and note.startswith("no parent:")


def test_spec_tags_say_the_status_the_tier_the_channel_and_the_review_verdicts():
    assert one("spec", "0004")["tags"] == {"sdlc:spec:0004", "sdlc:status:ready", "risk:HIGH", "eng-review:accepted",
                                           "data-review:n-a"}
    assert one("spec", "0005")["tags"] == {"sdlc:spec:0005", "sdlc:status:in-flight", "risk:MEDIUM", "channel:ag-ui",
                                           "carried-from:S06"}
    assert one("spec", "0007")["tags"] == {"sdlc:spec:0007", "sdlc:status:draft", "risk:LOW"}


def test_carried_from_names_the_sprint_the_spec_was_carried_out_of_into_its_current_one(tmp_path):
    p = one("spec", "0005")  # carried S05 -> S06 and S06 -> S07; its sprint is S07
    assert "carried-from:S06" in p["tags"] and "carried-from:S05" not in p["tags"]
    root = copy_repo(tmp_path)
    ledger = root / ".sdlc" / "metrics" / "sprint-log.jsonl"
    ledger.write_text("not json\n[1]\n" + ledger.read_text(encoding="utf-8"), encoding="utf-8")
    assert "carried-from:S06" in one("spec", "0005", root=root)["tags"], "a malformed line is skipped, not fatal"
    ledger.unlink()
    assert not {t for t in one("spec", "0005", root=root)["tags"] if t.startswith("carried-from:")}


def test_specs_are_found_by_scan_specs_so_the_template_and_files_with_no_id_are_not_specs(tmp_path):
    root = copy_repo(tmp_path)
    shutil.copy(TEMPLATES / "build" / "spec.md", root / "specs" / "spec-template.md")
    put(root, "specs/notes.md", "no frontmatter here\n")
    put(root, "specs/0009-no-key.md", '---\nname: "no key"\nstatus: ready\nrisk: LOW\nsource: "docs/x.md"\n---\n# x\n')
    put(root, "specs/scratch.md", '---\nname: "scratch"\nstatus: draft\n---\n# x\n')
    out = rows(["spec"], root=root)
    assert [p["id"] for p in out] == ["0004", "0005", "0007", "0009"]
    assert next(p for p in out if p["id"] == "0009")["ref"] == "sdlc:spec:0009", "a spec with no `spec:` key is named by its file"


def test_two_specs_with_one_id_are_refused_naming_both_files(tmp_path):
    root = copy_repo(tmp_path)
    shutil.copy(root / "specs" / "0004-duplicate-claim-409.md", root / "specs" / "0004-copy.md")
    with pytest.raises(ValueError) as err:
        rows(["spec"], root=root)
    assert "0004-copy.md" in str(err.value) and "0004-duplicate-claim-409.md" in str(err.value)


def test_a_long_title_is_cut_to_the_work_item_limit_and_the_projection_says_so(tmp_path):
    root = copy_repo(tmp_path)
    path = root / "specs" / "0007-reporting-export.md"
    path.write_text(path.read_text(encoding="utf-8").replace("reporting export", "very " * 80 + "long"), encoding="utf-8")
    p = one("spec", "0007", root=root)
    assert len(p["fields"]["System.Title"]) == 255 and p["fields"]["System.Title"].endswith("…")
    assert any("255" in n for n in p["notes"])


def test_a_title_is_one_line_whatever_the_source_wrote(tmp_path):
    root = copy_repo(tmp_path)
    path = root / "specs" / "0007-reporting-export.md"
    path.write_text(path.read_text(encoding="utf-8").replace('name: "reporting export"', 'name: "reporting\x1b[31m\t  export"'),
                    encoding="utf-8")
    title = one("spec", "0007", root=root)["fields"]["System.Title"]
    assert "\x1b" not in title and "\t" not in title and "  " not in title and title.startswith("0007 · ")


# --- who it is assigned to -------------------------------------------------------------------------------------

def test_assigned_to_is_the_rosters_email_for_the_developer():
    assert one("spec", "0004")["fields"]["System.AssignedTo"] == "dev.one@example.com"


def test_a_developer_with_no_email_gives_no_assignee_and_a_note_never_a_guess():
    p = one("spec", "0005")  # @dev-two is on the roster with no email
    assert "System.AssignedTo" not in p["fields"]
    assert any("@dev-two" in n and "no email" in n for n in p["notes"])
    assert "example.com" not in " ".join(p["notes"])


def test_a_spec_with_no_developer_has_no_assignee_and_nothing_to_explain():
    p = one("spec", "0007")
    assert "System.AssignedTo" not in p["fields"] and all("assignee" not in n for n in p["notes"])


def test_a_missing_roster_is_a_note_not_a_crash(tmp_path):
    root = copy_repo(tmp_path)
    (root / ".sdlc" / "team.yaml").unlink()
    p = one("spec", "0004", root=root)
    assert "System.AssignedTo" not in p["fields"] and any("@dev-one" in n for n in p["notes"])
    (root / ".sdlc" / "team.yaml").write_text("people: [unbalanced", encoding="utf-8")
    assert "System.AssignedTo" not in one("spec", "0004", root=root)["fields"]


def test_the_email_comes_through_email_for_and_nowhere_else(monkeypatch):
    seen = []
    monkeypatch.setattr(src, "email_for", lambda roster, handle: seen.append(handle) or "stub@example.com")
    assert one("spec", "0005")["fields"]["System.AssignedTo"] == "stub@example.com"
    assert "@dev-two" in seen


# --- state, iteration and configured fields ---------------------------------------------------------------------

def test_the_state_is_the_process_state_the_status_resolves_to():
    assert one("spec", "0004")["fields"]["System.State"] == "Ready"      # starter prefer 'Approved' is not on the type
    assert one("spec", "0005")["fields"]["System.State"] == "Active"
    assert one("spec", "0007")["fields"]["System.State"] == "New"


def test_a_state_rule_is_honoured_when_the_type_has_the_preferred_state():
    schema = copy.deepcopy(SCHEMA)
    schema["types"]["User Story"]["states"] = _states(("New", "Proposed"), ("Approved", "Proposed"), ("Ready", "Proposed"),
                                                      ("Active", "InProgress"))
    assert one("spec", "0004", schema=schema)["fields"]["System.State"] == "Approved"


def test_a_state_is_resolved_for_the_kind_so_two_kinds_on_one_type_do_not_disagree():
    cfg = {"types": {"spec": "Issue", "sprint": "Issue"},
           "states": {"spec": {"ready": "Proposed"}, "sprint": {"ready": "InProgress"}}}
    assert one("spec", "0004", cfg=cfg)["fields"]["System.State"] == "To Do"
    assert one("sprint", "S07", cfg=cfg)["fields"]["System.State"] == "Doing"


def test_a_state_the_process_cannot_say_is_left_out_with_the_reason_never_defaulted():
    sprint = one("sprint", "S07")  # no `types.sprint` pin and no candidate type
    assert "System.State" not in sprint["fields"]
    assert any(n.startswith("state not set:") for n in sprint["notes"])
    for spec in (one("spec", "0004", schema={}),
                 next(p for p in src.projections(REPO, STARTER, None, ["spec"]) if p["id"] == "0004")):
        assert "System.State" not in spec["fields"] and any(n.startswith("state not set:") for n in spec["notes"])
    assert "System.State" not in one("epic", "EP-001")["fields"], "an epic's status is the board's, not the repo's"


def test_a_spec_slated_into_a_bound_sprint_carries_its_iteration_path():
    assert one("spec", "0004")["fields"][ITERATION] == "Claims\\Sprint 7"
    assert ITERATION not in one("spec", "0007")["fields"]
    unbound = copy.deepcopy(STARTER)
    unbound["iterations"] = {}
    assert ITERATION not in one("spec", "0004", cfg=unbound)["fields"]


def test_configured_fields_map_the_spec_value_through_the_values_table():
    p = one("spec", "0004")
    assert p["fields"]["Custom.RiskTier"] == "High" and "Custom.Channel" not in p["fields"]
    q = one("spec", "0005")
    assert q["fields"]["Custom.RiskTier"] == "Medium" and q["fields"]["Custom.Channel"] == "ag-ui"


def test_a_value_the_table_does_not_name_is_left_out_with_a_note(tmp_path):
    cfg = copy.deepcopy(STARTER)
    del cfg["fields"]["spec"]["risk"]["values"]["HIGH"]
    p = one("spec", "0004", cfg=cfg)
    assert "Custom.RiskTier" not in p["fields"] and any("HIGH" in n for n in p["notes"])


def test_a_field_that_maps_an_activity_metric_is_never_emitted():
    cfg = copy.deepcopy(STARTER)
    cfg["fields"]["spec"] = {"risk": "Microsoft.VSTS.Scheduling.Effort", "points": "Custom.Points", "team": "Custom.Team"}
    p = one("spec", "0004", cfg=cfg)
    assert p["fields"]["Custom.Team"] == "core"
    assert not {k for k in p["fields"] if "Scheduling" in k or "Points" in k}
    assert sum("activity metric" in n for n in p["notes"]) == 2


def test_no_effort_or_estimate_reaches_any_projection():
    text = json.dumps(rows(FIXTURE_KINDS), default=sorted).lower()
    assert "estimate" not in text and "scheduling" not in text and "story point" not in text


def test_spec_traces_off_by_default_and_the_FRs_of_the_brief_row_when_on():
    assert one("spec", "0004")["related_refs"] == []
    cfg = copy.deepcopy(STARTER)
    cfg["tree"]["spec_traces"] = True
    assert one("spec", "0004", cfg=cfg)["related_refs"] == ["sdlc:fr:001", "sdlc:fr:002"]
    assert one("spec", "0005", cfg=cfg)["related_refs"] == [], "a US id is not an FR"
    assert one("spec", "0007", cfg=cfg)["related_refs"] == [], "no feature, no row, nothing guessed"


# --- features ---------------------------------------------------------------------------------------------------

def test_a_feature_brief_is_one_feature_under_the_epic_its_header_names_by_id():
    p = one("feature", "FE-03")
    assert (p["ref"], p["title"], p["status"]) == ("sdlc:feature:03", "Claims intake", None)
    assert p["fields"] == {"System.Title": "FE-03 · Claims intake"}
    assert p["parent_ref"] == "sdlc:epic:001" and p["parent_note"] is None
    assert p["tags"] == {"sdlc:feature:03"} and p["source_path"] == "feature-brief-FE-03.md"


def _brief(root: Path, header: str, name="feature-brief-FE-03.md"):
    path = root / name
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0] = header
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_a_name_only_header_matches_an_epic_title_exactly_or_has_no_parent(tmp_path):
    root = copy_repo(tmp_path)
    _brief(root, "# Feature Brief — FE-03: Claims intake   (epic: claims  INTAKE)")
    p = one("feature", "FE-03", root=root)
    assert p["parent_ref"] == "sdlc:epic:001", "same words, any case or spacing, is an exact title match"
    _brief(root, "# Feature Brief — FE-03: Claims intake   (epic: Claims)")
    p = one("feature", "FE-03", root=root)
    assert p["parent_ref"] is None and p["parent_note"] == "no parent: header epic 'Claims' matches no epic title"
    _brief(root, "# Feature Brief — FE-03: Claims intake   (epic: EP-CLAIMS)")
    assert one("feature", "FE-03", root=root)["parent_ref"] is None


def test_an_epic_title_two_epics_share_is_ambiguous_not_picked(tmp_path):
    root = copy_repo(tmp_path)
    epics = root / "epics.md"
    epics.write_text(epics.read_text(encoding="utf-8").replace("### EP-002: Claim status", "### EP-002: Claims intake"),
                     encoding="utf-8")
    _brief(root, "# Feature Brief — FE-03: Claims intake   (epic: Claims intake)")
    p = one("feature", "FE-03", root=root)
    assert p["parent_ref"] is None and "matches several epics" in p["parent_note"] and "EP-001, EP-002" in p["parent_note"]


def test_an_id_in_the_header_wins_over_a_name_and_a_header_with_no_epic_says_so(tmp_path):
    root = copy_repo(tmp_path)
    _brief(root, "# Feature Brief — FE-03: Claims intake   (epic: EP-002 — Claims intake)")
    assert one("feature", "FE-03", root=root)["parent_ref"] == "sdlc:epic:002"
    _brief(root, "# Feature Brief — FE-03: Claims intake")
    p = one("feature", "FE-03", root=root)
    assert p["parent_ref"] is None and p["parent_note"] == "no parent: header names no epic"


def test_feature_briefs_are_found_under_the_artifacts_folder_and_an_unfilled_template_is_no_feature(tmp_path):
    root = copy_repo(tmp_path)
    folder = root / ".sdlc" / "artifacts" / "01-requirements"
    folder.mkdir(parents=True)
    shutil.copy(TEMPLATES / "01-requirements" / "feature-brief.md", folder / "feature-brief.md")
    assert [p["id"] for p in rows(["feature"], root=root)] == ["FE-03"]
    (folder / "feature-brief-FE-07.md").write_text(
        "# Feature Brief — FE-07: Claim export   (epic: EP-003 — Claims export)\n", encoding="utf-8")
    out = rows(["feature"], root=root)
    assert [(p["id"], p["parent_ref"]) for p in out] == [("FE-03", "sdlc:epic:001"), ("FE-07", "sdlc:epic:003")]
    assert out[1]["source_path"] == ".sdlc/artifacts/01-requirements/feature-brief-FE-07.md"


def test_two_briefs_for_one_feature_are_refused_naming_both(tmp_path):
    root = copy_repo(tmp_path)
    shutil.copy(root / "feature-brief-FE-03.md", root / "feature-brief-copy.md")
    with pytest.raises(ValueError, match="FE-03") as err:
        rows(["feature"], root=root)
    assert "feature-brief-copy.md" in str(err.value)


# --- epics ------------------------------------------------------------------------------------------------------

def test_epics_are_the_summary_table_and_every_epic_heading_and_never_the_estimate():
    out = {p["id"]: p for p in rows(["epic"])}
    assert set(out) == {"EP-001", "EP-002", "EP-003"}, "EP-003 is only a heading, not a table row"
    p = out["EP-001"]
    assert (p["ref"], p["title"], p["status"]) == ("sdlc:epic:001", "Claims intake", None)
    assert p["fields"] == {"System.Title": "EP-001 · Claims intake", PRIORITY: 1}
    assert out["EP-002"]["fields"][PRIORITY] == 2 and out["EP-003"]["fields"][PRIORITY] == 3
    assert p["tags"] == {"sdlc:epic:001"} and p["related_refs"] == []


def test_the_epic_priority_is_written_only_to_a_type_known_to_carry_the_field():
    no_field = copy.deepcopy(SCHEMA)
    no_field["types"]["Epic"]["fields"] = {"System.Title": _field("System.Title")}
    assert PRIORITY not in one("epic", "EP-001", schema=no_field)["fields"]
    assert PRIORITY not in one("epic", "EP-001", schema={})["fields"], "fields never read: unknown, so not written"


def test_the_epic_parent_comes_from_the_registered_resolver_which_is_given_the_source_row(monkeypatch):
    seen = {}

    def resolver(repo_root, row):
        seen[row["id"]] = (Path(repo_root), row)
        return "sdlc:domain:intake", "fulfils FR-001..004"

    monkeypatch.setitem(src.PARENT_RESOLVERS, "epic", resolver)
    out = rows(["epic"])
    p = next(p for p in out if p["id"] == "EP-001")
    assert (p["parent_ref"], p["parent_note"]) == ("sdlc:domain:intake", "fulfils FR-001..004")
    root, row = seen["EP-001"]
    assert root == REPO and row["ref"] == "sdlc:epic:001"
    assert row["source_row"] == {"Epic ID": "EP-001", "Title": "Claims intake", "Priority": "P0", "FR Link": "FR-001..004"}
    assert seen["EP-002"][1]["source_row"]["FR Link"] == "FR-010"
    assert seen["EP-003"][1]["source_row"]["FR Link"] == "", "a heading-only epic with no Linked requirement"
    assert all("source_row" not in p for p in out)


def test_a_resolvers_third_value_is_appended_to_related_refs_each_once(monkeypatch):
    """`(parent_ref, note, related_refs)`: the requirements tree's epic resolver answers an epic's fulfils links (K25)."""
    monkeypatch.setitem(src.PARENT_RESOLVERS, "epic", lambda r, row: (
        "sdlc:domain:intake", "fulfils FR-001..002", ["sdlc:fr:001", "sdlc:fr:002", "sdlc:fr:001"]))
    p = one("epic", "EP-001")
    assert (p["parent_ref"], p["parent_note"]) == ("sdlc:domain:intake", "fulfils FR-001..002")
    assert p["related_refs"] == ["sdlc:fr:001", "sdlc:fr:002"]
    monkeypatch.setitem(src.PARENT_RESOLVERS, "epic", lambda r, row: (None, "no fulfils links: FR Link empty", []))
    assert one("epic", "EP-001")["related_refs"] == []


@pytest.mark.parametrize("answer, match", [
    ((None, None, ["FR-001"]), "related ref 'FR-001'"),
    ((None, None, ["sdlc:fr:001"], "extra"), "returned 4 values"),
    ((None,), "returned 1 values"),
])
def test_a_resolver_answer_of_the_wrong_shape_is_refused(monkeypatch, answer, match):
    monkeypatch.setitem(src.PARENT_RESOLVERS, "epic", lambda r, row: answer)
    with pytest.raises(ValueError, match=match):
        rows(["epic"])


def test_with_no_epic_resolver_loaded_the_epic_says_why_it_has_no_parent(monkeypatch):
    monkeypatch.delitem(src.PARENT_RESOLVERS, "epic", raising=False)
    p = one("epic", "EP-001")
    assert p["parent_ref"] is None and p["parent_note"].startswith("no parent:")
    assert "requirements tree" in p["parent_note"]


def test_the_epic_fr_link_is_the_table_cell_and_falls_back_to_the_linked_requirement_in_the_body(tmp_path, monkeypatch):
    root = copy_repo(tmp_path)
    epics = root / "epics.md"
    text = epics.read_text(encoding="utf-8")
    text = text.replace("| P0 | 3 | FR-001..004 |", "| P0 | 3 |  |")          # EP-001: empty cell, body says FR-001..004
    text = text.replace("**Linked requirement:** FR-010", "**Linked requirement:** FR-099")  # EP-002: cell says FR-010
    epics.write_text(text, encoding="utf-8")
    seen = {}
    monkeypatch.setitem(src.PARENT_RESOLVERS, "epic", lambda r, row: seen.update({row["id"]: row}) or (None, None))
    rows(["epic"], root=root)
    assert seen["EP-001"]["source_row"]["FR Link"] == "FR-001..004"
    assert seen["EP-002"]["source_row"]["FR Link"] == "FR-010"


def test_an_unfilled_epics_template_is_no_epics_and_a_missing_file_is_none(tmp_path):
    root = copy_repo(tmp_path)
    (root / "epics.md").unlink()
    assert rows(["epic"], root=root) == []
    folder = root / ".sdlc" / "artifacts" / "01-requirements"
    folder.mkdir(parents=True)
    shutil.copy(TEMPLATES / "01-requirements" / "epics.md", folder / "epics.md")
    assert rows(["epic"], root=root) == []


def test_two_epics_with_one_id_are_refused(tmp_path):
    root = copy_repo(tmp_path)
    epics = root / "epics.md"
    epics.write_text(epics.read_text(encoding="utf-8").replace("### EP-003: Claims export", "### EP-001: Claims export"),
                     encoding="utf-8")
    with pytest.raises(ValueError, match="EP-001"):
        rows(["epic"], root=root)


# --- decisions --------------------------------------------------------------------------------------------------

def test_a_decision_is_the_question_and_never_the_resolution_text():
    out = {p["id"]: p for p in rows(["decision"])}
    assert set(out) == {"DL-01", "DL-02", "DL-03"}
    one_, two = out["DL-01"], out["DL-02"]
    assert (one_["ref"], one_["title"], one_["status"]) == ("sdlc:decision:01", "Which channel ships first?", "open")
    assert (two["title"], two["status"]) == ("How long are claim drafts kept?", "decided")
    assert "thirty days" not in json.dumps(two, default=sorted) and "decided by" not in json.dumps(two, default=sorted)
    assert two["fields"]["System.Title"] == "DL-02 · How long are claim drafts kept?"
    assert one_["tags"] == {"sdlc:decision:01", "sdlc:status:open"} and one_["parent_ref"] is None


def test_a_decision_states_come_from_the_pinned_type_and_a_handle_owner_is_the_assignee():
    out = {p["id"]: p for p in rows(["decision"])}
    assert out["DL-01"]["fields"]["System.State"] == "To Do" and out["DL-02"]["fields"]["System.State"] == "Done"
    assert out["DL-01"]["fields"]["System.AssignedTo"] == "dev.one@example.com"
    assert "System.AssignedTo" not in out["DL-03"]["fields"], "a role is not a person"
    assert out["DL-03"]["notes"] == [], "nothing to explain about a role"


def test_the_decision_log_template_row_is_not_a_decision_and_a_root_log_is_read(tmp_path):
    root = copy_repo(tmp_path)
    shutil.copy(TEMPLATES / "01-requirements" / "decision-log.md", root / ".sdlc" / "decision-log.md")
    assert rows(["decision"], root=root) == []
    (root / ".sdlc" / "decision-log.md").unlink()
    shutil.copy(REPO / ".sdlc" / "decision-log.md", root / "decision-log.md")
    assert [p["id"] for p in rows(["decision"], root=root)] == ["DL-01", "DL-02", "DL-03"]


def test_a_decision_status_that_is_not_closed_is_open_as_track_decisions_reads_it(tmp_path):
    root = copy_repo(tmp_path)
    log = root / ".sdlc" / "decision-log.md"
    log.write_text(log.read_text(encoding="utf-8").replace("| open    |\n| DL-02", "| pending |\n| DL-02"), encoding="utf-8")
    assert one("decision", "DL-01", root=root)["status"] == "open"
    log.write_text(log.read_text(encoding="utf-8").replace("| decided |", "| Cancelled |"), encoding="utf-8")
    assert one("decision", "DL-02", root=root)["status"] == "closed"


# --- sprints and spikes -----------------------------------------------------------------------------------------

def test_a_sprint_is_its_id_and_goal_and_carries_no_date_or_target():
    p = one("sprint", "S07")
    assert (p["ref"], p["title"], p["status"]) == ("sdlc:sprint:S07", "Ship claims intake", "ready")
    assert p["fields"]["System.Title"] == "S07 · Ship claims intake"
    assert p["tags"] == {"sdlc:sprint:S07", "sdlc:status:ready"}
    assert p["parent_ref"] is None and p["parent_note"] is None
    keys = " ".join(p["fields"]).lower()
    assert "date" not in keys and "target" not in keys and "start" not in keys


def test_the_sprint_template_is_not_a_sprint_and_a_sprint_with_no_goal_is_just_its_id(tmp_path):
    root = copy_repo(tmp_path)
    shutil.copy(TEMPLATES / "build" / "sprint.md", root / ".sdlc" / "sprints" / "SNN.md")
    put(root, ".sdlc/sprints/S08.md", '---\nsprint: "S08"\ngoal: ""\nstate: planning\n---\n# Sprint S08\n')
    out = rows(["sprint"], root=root)
    assert [p["id"] for p in out] == ["S07", "S08"]
    assert out[1]["fields"]["System.Title"] == "S08" and out[1]["status"] == "planning"


def test_a_spike_is_its_question_and_not_its_box(tmp_path):
    root = copy_repo(tmp_path)
    put(root, "spikes/0003-carrier-dedup.md",
        '---\nspike: "0003"\nname: "carrier-dedup"\nstatus: open\nbox: "1 working day"\nopened_by: "@dev-one"\n'
        'unblocks: "—"\ncreated: "2026-10-04"\n---\n\n# Spike 0003 — Does the carrier deduplicate on our idempotency key?\n')
    shutil.copy(TEMPLATES / "build" / "spike.md", root / "spikes" / "spike-template.md")
    out = rows(["spike"], root=root)
    assert [p["id"] for p in out] == ["0003"]
    p = out[0]
    assert (p["ref"], p["status"]) == ("sdlc:spike:0003", "open")
    assert p["title"] == "Does the carrier deduplicate on our idempotency key?"
    assert p["fields"]["System.Title"] == "0003 · Does the carrier deduplicate on our idempotency key?"
    assert p["tags"] == {"sdlc:spike:0003", "sdlc:status:open"}
    assert "working day" not in json.dumps(p, default=sorted)


def test_a_repository_with_none_of_it_projects_nothing_for_every_kind(tmp_path):
    assert rows(ALL_KINDS, root=tmp_path) == []


# --- standalone mode ---------------------------------------------------------------------------------------------

def test_a_bare_folder_of_specs_projects_with_no_sdlc_directory_at_all(tmp_path):
    shutil.copytree(REPO / "specs", tmp_path / "specs")
    out = rows(["spec"], cfg={}, schema={}, root=tmp_path)
    assert [p["id"] for p in out] == ["0004", "0005", "0007"]
    assert out[0]["parent_ref"] == "sdlc:feature:03"
    assert "System.AssignedTo" not in out[0]["fields"] and any("@dev-one" in n for n in out[0]["notes"])
    assert not (tmp_path / ".sdlc").exists()
