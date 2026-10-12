"""The activities declaration and its evaluation (spec 0023).

Studio's Workflow tab is meant to list what a stage offers, from the plugin, instead of from a
second hand-written list that would drift the first time a command changed. These tests keep the
declaration honest in two ways: every command, template and cross-reference it names must really
exist (so a typo cannot ship a step that does nothing), and evaluating it must follow one fixed
precedence (done, then blocked, then available) that reads files and never runs anything.
"""

import json
from pathlib import Path

import pytest
import yaml

import activities_model as am
import phase_model as pm

ROOT = Path(__file__).resolve().parent.parent.parent


def act(**over):
    base = {"id": "a", "label": "Do a thing", "command": None, "kind": "run"}
    base.update(over)
    return base


class TestTheShippedDeclarationIsTrue:
    def test_it_validates_with_no_violations(self):
        assert am.validate(am.load()) == []

    def test_it_declares_the_activities_the_plan_depends_on(self):
        data = am.load()
        ids = {phase: [a["id"] for a in acts] for phase, acts in data.items()}
        assert {"intake", "brief", "review", "enhance", "phase-report"} <= set(ids["0"])
        assert {"feature-brief", "rules", "rules-check"} <= set(ids["1"])
        assert {"data", "data-check", "experience"} <= set(ids["2"])
        assert "pipeline-proof" in ids["3"]
        for phase in ("0", "1", "2", "3", "build"):
            assert "coach" in ids[phase]

    def test_the_build_phase_declares_the_sprint_layer(self):
        ids = [a["id"] for a in am.load()["build"]]
        assert ids == ["sprint", "refine", "phase-report", "coach"]

    def test_refinement_starts_at_foundation(self):
        assert "refine" in [a["id"] for a in am.load()["3"]]

    def test_the_sprint_activity_is_never_done_and_starts_nothing(self):
        sprint = next(a for a in am.load()["build"] if a["id"] == "sprint")
        assert "creates" not in sprint and "done_when" not in sprint

    @pytest.mark.parametrize("phase, activity, command, kind", [
        ("0", "intake", "sprd-intake", "run"), ("0", "brief", "sprd-brief", "create"),
        ("0", "review", "sprd-review", "draft"), ("0", "enhance", "sprd-enhance", "draft"),
        ("0", "phase-report", "sprd-phase-report", "run"),
        ("1", "feature-brief", "sprd-feature", "create"), ("1", "rules", "sprd-rules", "create"),
        ("1", "rules-check", "sprd-rules", "check"),
        ("2", "data", "sprd-data", "create"), ("2", "data-check", "sprd-data", "check"),
        ("2", "experience", "sprd-experience", "create"),
        ("3", "pipeline-proof", None, "run"), ("1", "coach", "sprd-coach", "talk"),
        ("build", "sprint", "sprd-sprint", "run"), ("build", "refine", "sprd-refine", "talk"),
        ("build", "phase-report", "sprd-phase-report", "run"), ("build", "coach", "sprd-coach", "talk"),
        ("3", "refine", "sprd-refine", "talk"),
    ])
    def test_each_activity_is_mapped_to_its_command_and_kind(self, phase, activity, command, kind):
        entry = next(a for a in am.load()[phase] if a["id"] == activity)
        assert (entry["command"], entry["kind"]) == (command, kind)

    def test_every_phase_key_is_a_real_phase(self):
        assert set(am.load()) <= set(pm.all_phase_ids())


class TestValidationNamesTheActivityAndTheRule:
    def check(self, phases, expect):
        problems = am.validate(phases)
        assert any(expect in p for p in problems), problems

    def test_an_unknown_phase(self):
        self.check({"42": [act()]}, "phase 42")

    def test_a_duplicate_id_within_a_phase(self):
        self.check({"0": [act(id="x"), act(id="x")]}, "duplicate")

    def test_the_same_id_in_two_phases_is_fine(self):
        assert am.validate({"0": [act(id="x")], "1": [act(id="x")]}) == []

    def test_a_kind_that_is_not_one_of_the_five(self):
        self.check({"0": [act(kind="shout")]}, "kind")

    def test_a_missing_label(self):
        self.check({"0": [act(label="")]}, "label")

    def test_a_command_that_has_no_command_file(self):
        self.check({"0": [act(command="sprd-nonesuch")]}, "sprd-nonesuch")

    def test_an_after_that_names_no_activity_in_the_phase(self):
        self.check({"0": [act(after=["ghost"])]}, "ghost")

    def test_a_creates_path_with_no_template(self):
        self.check({"0": [act(creates=[".sdlc/artifacts/00-discovery/not-a-template.md"])]}, "not-a-template")

    def test_a_creates_path_that_has_a_template_is_fine(self):
        assert am.validate({"0": [act(creates=[".sdlc/artifacts/00-discovery/workshop-brief.md"])]}) == []

    def test_review_report_maps_to_the_shared_template(self):
        assert am.validate({"0": [act(creates=[".sdlc/artifacts/00-discovery/review-report.md"])]}) == []

    def test_a_requires_with_an_unknown_kind_of_condition(self):
        self.check({"0": [act(requires={"moon": "full"})]}, "requires")

    def test_a_requires_activity_that_does_not_exist(self):
        self.check({"0": [act(requires={"activity": "ghost"})]}, "ghost")

    def test_a_done_when_with_an_unknown_kind_of_condition(self):
        self.check({"0": [act(done_when={"vibes": "good"})]}, "done_when")


class TestAMalformedFieldIsReportedNotRaised:
    """F12: one badly typed entry used to raise out of validate() and blank every stage."""

    def check(self, activity, expect, phase="0"):
        problems = am.validate({phase: [activity]})
        assert any(expect in p for p in problems), problems
        return problems

    def test_the_probe_that_used_to_raise_returns_a_problem(self):
        bad = {"build": [{"id": "x", "label": "x", "kind": "run", "requires": ["file"]}]}
        problems = am.validate(bad)
        assert problems and all("phase build / activity x" in p for p in problems)
        assert any("requires must be a mapping" in p for p in problems)

    def test_an_unknown_key_is_named(self):
        problems = self.check(act(colour="blue"), "unknown key colour")
        assert "phase 0 / activity a: unknown key colour" in problems

    def test_every_documented_key_is_known(self):
        full = act(creates=[".sdlc/artifacts/00-discovery/workshop-brief.md"], after=[], optional=False,
                   requires={"file": "x.md"}, done_when={"exists": "y.md"})
        assert am.validate({"0": [full]}) == []

    def test_requires_that_is_not_a_mapping(self):
        self.check(act(requires="profile"), "requires must be a mapping")

    def test_done_when_that_is_not_a_mapping(self):
        self.check(act(done_when=["exists"]), "done_when must be a mapping")

    def test_done_when_holding_two_conditions(self):
        self.check(act(done_when={"exists": "a.md", "exists_all": ["b.md"]}), "one condition")

    def test_creates_that_is_not_a_list(self):
        self.check(act(creates=".sdlc/artifacts/00-discovery/workshop-brief.md"), "creates must be a list")

    def test_creates_holding_a_non_string(self):
        self.check(act(creates=[42]), "creates must hold only non-empty strings")

    def test_after_that_is_not_a_list(self):
        self.check(act(after="intake"), "after must be a list")

    def test_after_holding_a_non_string(self):
        self.check(act(after=[None]), "after must hold only non-empty strings")

    def test_a_command_that_is_not_a_string(self):
        self.check(act(command=["sprd-coach"]), "command must be")

    def test_an_optional_that_is_not_a_bool(self):
        self.check(act(optional="yes"), "optional must be true or false")

    def test_an_id_that_is_not_a_string(self):
        self.check(act(id=["a"]), "needs an id")

    def test_a_label_that_is_not_a_string(self):
        self.check(act(label=7), "needs a label")

    def test_a_requires_value_that_is_empty(self):
        self.check(act(requires={"profile": ""}), "requires profile must name")

    def test_done_when_exists_all_that_is_empty(self):
        self.check(act(done_when={"exists_all": []}), "at least one path")

    def test_done_when_json_missing_its_parts(self):
        self.check(act(done_when={"json": {"file": "a.json"}}), "file, key and equals")

    def test_each_bad_field_yields_its_own_problem(self):
        problems = am.validate({"0": [act(requires="x", done_when="y", creates="z", after="w", nope=1)]})
        assert len(problems) == 5 and all(p.startswith("phase 0 / activity a: ") for p in problems)

    @pytest.mark.parametrize("activity", [
        {"id": None, "label": None, "kind": None, "command": 3, "creates": 1, "after": {}, "requires": 1,
         "done_when": 2, "optional": None},
        {"id": [1], "label": [2]},
        {},
    ])
    def test_nothing_in_an_activity_can_make_validate_raise(self, activity):
        assert am.validate({"0": [activity, act(id="ok")]})


@pytest.fixture
def project(tmp_path):
    (tmp_path / ".sdlc" / "artifacts" / "00-discovery").mkdir(parents=True)
    return tmp_path


def evaluate(project, activities, phase="0"):
    return am.evaluate(project, phase, data={phase: activities})


class TestEvaluation:
    def test_returns_the_declared_order_with_the_documented_fields(self, project):
        out = evaluate(project, [act(id="b", creates=["x"], after=["a"]), act(id="a", optional=False)])
        assert [e["id"] for e in out] == ["b", "a"]
        assert set(out[0]) == {"id", "label", "command", "kind", "optional", "creates", "after", "status", "reason"}
        assert out[1]["optional"] is False

    def test_an_unknown_phase_has_no_activities(self, project):
        assert am.evaluate(project, "42", data={"0": [act()]}) == []

    def test_with_nothing_required_and_nothing_to_finish_an_activity_is_available(self, project):
        e = evaluate(project, [act()])[0]
        assert (e["status"], e["reason"]) == ("available", None)

    def test_an_activity_with_no_done_when_is_never_done(self, project):
        (project / "anything.txt").write_text("x")
        assert evaluate(project, [act(done_when=None)])[0]["status"] == "available"

    # --- requires ---
    def test_a_profile_requirement_is_blocked_with_the_key_named_when_there_is_no_profile(self, project):
        e = evaluate(project, [act(requires={"profile": "documentation.intake_path"})])[0]
        assert e["status"] == "blocked" and "documentation.intake_path" in e["reason"]

    def test_a_profile_requirement_is_blocked_when_the_key_is_empty(self, project):
        (project / ".sdlc" / "profile.yaml").write_text("documentation:\n  intake_path: ''\n", encoding="utf-8")
        assert evaluate(project, [act(requires={"profile": "documentation.intake_path"})])[0]["status"] == "blocked"

    def test_a_profile_requirement_is_met_by_a_nested_value(self, project):
        (project / ".sdlc" / "profile.yaml").write_text("documentation:\n  intake_path: docs/\n", encoding="utf-8")
        assert evaluate(project, [act(requires={"profile": "documentation.intake_path"})])[0]["status"] == "available"

    def test_an_activity_requirement_blocks_until_that_activity_is_done_and_names_it(self, project):
        acts = [act(id="first", label="Catalogue the documents", done_when={"exists": "marker.txt"}),
                act(id="second", requires={"activity": "first"})]
        out = evaluate(project, acts)
        assert out[1]["status"] == "blocked" and "Catalogue the documents" in out[1]["reason"]
        (project / "marker.txt").write_text("x")
        assert evaluate(project, acts)[1]["status"] == "available"

    def test_a_file_requirement_blocks_until_the_file_exists(self, project):
        acts = [act(requires={"file": ".sdlc/artifacts/00-discovery/epics.md"})]
        assert evaluate(project, acts)[0]["status"] == "blocked"
        (project / ".sdlc" / "artifacts" / "00-discovery" / "epics.md").write_text("x")
        assert evaluate(project, acts)[0]["status"] == "available"

    # --- done_when ---
    def test_exists_marks_done_once_the_file_exists(self, project):
        acts = [act(done_when={"exists": ".sdlc/artifacts/00-discovery/workshop-brief.md"})]
        assert evaluate(project, acts)[0]["status"] == "available"
        (project / ".sdlc" / "artifacts" / "00-discovery" / "workshop-brief.md").write_text("x")
        assert evaluate(project, acts)[0]["status"] == "done"

    def test_exists_all_needs_every_file(self, project):
        acts = [act(done_when={"exists_all": ["a.md", "b.md"]})]
        (project / "a.md").write_text("x")
        assert evaluate(project, acts)[0]["status"] == "available"
        (project / "b.md").write_text("x")
        assert evaluate(project, acts)[0]["status"] == "done"

    def test_json_done_when_reads_a_key_from_a_json_file(self, project):
        catalog = project / ".sdlc" / "catalog.json"
        acts = [act(done_when={"json": {"file": ".sdlc/catalog.json", "key": "locked", "equals": True}})]
        catalog.write_text(json.dumps({"locked": False}))
        assert evaluate(project, acts)[0]["status"] == "available"
        catalog.write_text(json.dumps({"locked": True}))
        assert evaluate(project, acts)[0]["status"] == "done"

    def test_a_json_file_that_is_missing_or_unreadable_is_simply_not_done(self, project):
        acts = [act(done_when={"json": {"file": ".sdlc/catalog.json", "key": "locked", "equals": True}})]
        assert evaluate(project, acts)[0]["status"] == "available"
        (project / ".sdlc" / "catalog.json").write_text("{not json")
        assert evaluate(project, acts)[0]["status"] == "available"

    # --- precedence ---
    def test_done_wins_even_when_a_requirement_is_no_longer_met(self, project):
        (project / "result.md").write_text("x")
        e = evaluate(project, [act(requires={"file": "gone.md"}, done_when={"exists": "result.md"})])[0]
        assert e["status"] == "done" and e["reason"] is None

    def test_blocked_beats_available(self, project):
        assert evaluate(project, [act(requires={"file": "missing.md"})])[0]["status"] == "blocked"

    def test_evaluating_reads_only_and_writes_nothing(self, project):
        before = sorted(str(p) for p in project.rglob("*"))
        evaluate(project, [act(requires={"profile": "a.b"}, done_when={"exists": "x"})])
        assert sorted(str(p) for p in project.rglob("*")) == before


class TestTheShippedDeclarationAgainstARealProject:
    def test_intake_is_blocked_without_the_profile_key_and_brief_waits_for_it(self, project):
        by_id = {e["id"]: e for e in am.evaluate(project, "0")}
        assert by_id["intake"]["status"] == "blocked" and "documentation.intake_path" in by_id["intake"]["reason"]
        assert by_id["brief"]["status"] == "blocked"

    def test_a_locked_catalog_finishes_intake_and_opens_the_brief(self, project):
        (project / ".sdlc" / "profile.yaml").write_text("documentation:\n  intake_path: docs/\n", encoding="utf-8")
        (project / ".sdlc" / "context" / "intake").mkdir(parents=True)
        (project / ".sdlc" / "context" / "intake" / "catalog.json").write_text(json.dumps({"locked": True}))
        by_id = {e["id"]: e for e in am.evaluate(project, "0")}
        assert by_id["intake"]["status"] == "done" and by_id["brief"]["status"] == "available"

    def test_a_written_workshop_brief_marks_the_brief_done(self, project):
        (project / ".sdlc" / "artifacts" / "00-discovery" / "workshop-brief.md").write_text("# Brief\n")
        assert {e["id"]: e for e in am.evaluate(project, "0")}["brief"]["status"] == "done"

    def test_the_coach_is_always_available(self, project):
        assert {e["id"]: e for e in am.evaluate(project, "1")}["coach"]["status"] == "available"


class TestLoading:
    def test_an_invalid_file_raises_an_error_that_says_what_is_wrong(self, tmp_path):
        bad = tmp_path / "a.yaml"
        bad.write_text("'0': not-a-list\n", encoding="utf-8")
        with pytest.raises(am.ActivitiesError, match="list"):
            am.load(bad)

    def test_unparseable_yaml_raises_the_same_error(self, tmp_path):
        bad = tmp_path / "a.yaml"
        bad.write_text(": : :\n\t- [", encoding="utf-8")
        with pytest.raises(am.ActivitiesError):
            am.load(bad)

    def test_a_missing_file_raises_the_same_error(self, tmp_path):
        with pytest.raises(am.ActivitiesError, match="not found"):
            am.load(tmp_path / "nope.yaml")

    def test_phase_keys_are_normalised_to_strings(self, tmp_path):
        f = tmp_path / "a.yaml"
        f.write_text("0:\n  - {id: a, label: A, kind: run, command: null}\n", encoding="utf-8")
        assert list(am.load(f)) == ["0"]
