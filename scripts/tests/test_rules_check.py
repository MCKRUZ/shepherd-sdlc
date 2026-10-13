"""rules_check.py — the advisory check behind /sprd-rules (spec 0022).

What these protect:
  * ADVISORY BY CONSTRUCTION. Every path exits 0 (a usage error is 2), including missing documents.
  * NO DATA IS NOT ZERO. A missing document, or one holding only template placeholders, reports
    `has_data: false` with a note and empty lists - never a clean bill of health.
  * ONE DOCUMENT. `--json` prints a single JSON document and nothing else.
  * DETERMINISM. The same documents give byte-identical output, wherever they live.
  * COLUMNS BY HEADER. Reordered or extra columns give the same answer.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "rules_check.py"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

RULES_HEADER = ("| Rule  | Condition | Outcome | Source | Approver |\n"
                "|-------|-----------|---------|--------|----------|\n")
SCEN_HEADER = ("| Scenario | Input | Expected behavior |\n"
               "|----------|-------|-------------------|\n")
DL_HEADER = ("| id | decision | owner | opened | due (2 business days) | status |\n"
             "|----|----------|-------|--------|-----------------------|--------|\n")

TEMPLATE_RULES = (ROOT / "templates/phases/01-requirements/business-rules.md").read_text(encoding="utf-8")
TEMPLATE_SCENARIOS = (ROOT / "templates/phases/01-requirements/golden-scenarios.md").read_text(encoding="utf-8")
TEMPLATE_DECISION_LOG = (ROOT / "templates/phases/01-requirements/decision-log.md").read_text(encoding="utf-8")


def rules_doc(*rows):
    return "# Business Rules\n\nPreamble prose.\n\n---\n\n" + RULES_HEADER + "\n".join(rows) + "\n\n*Footer.*\n"


def scen_doc(*rows):
    return "# Golden Scenarios\n\nPreamble prose.\n\n---\n\n" + SCEN_HEADER + "\n".join(rows) + "\n\n*Footer.*\n"


def dl_doc(*rows):
    return "# Decision Log\n\nProse citing DL-01 as an example.\n\n" + DL_HEADER + "\n".join(rows) + "\n"


CLEAN_RULES = rules_doc(
    "| BR-01 | amount > 10k | escalate | policy 4.2 | Jane Doe |",
    "| BR-02 | amount <= 10k | approve | policy 4.3 | Jane Doe |",
)
CLEAN_SCENARIOS = scen_doc(
    "| SCEN-01 | a 12k claim (BR-01) | escalated |",
    "| SCEN-02 | a 5k claim | approved per BR-02 |",
)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def project(tmp_path, rules=None, scenarios=None, log=None):
    """A workflow-mode project: returns (state_path, repo_root)."""
    sdlc = tmp_path / ".sdlc"
    sdlc.mkdir(parents=True, exist_ok=True)
    state = write(sdlc / "state.yaml", "project: demo\n")
    art = sdlc / "artifacts" / "01-requirements"
    if rules is not None:
        write(art / "business-rules.md", rules)
    if scenarios is not None:
        write(art / "golden-scenarios.md", scenarios)
    if log is not None:
        write(sdlc / "decision-log.md", log)
    return state, tmp_path


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          encoding="utf-8", env=ENV)


def report(tmp_path, rules=None, scenarios=None, log=None):
    _, repo = project(tmp_path, rules, scenarios, log)
    proc = run("--repo", str(repo), "--json")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def checks(doc):
    return sorted((f["check"], f["subject"]) for f in doc["findings"])


class TestCleanAndTemplates:
    def test_documents_where_everything_is_sourced_approved_and_referenced_have_no_findings(self, tmp_path):
        doc = report(tmp_path, CLEAN_RULES, CLEAN_SCENARIOS)
        assert doc["has_data"] is True and doc["findings"] == [] and doc["advisory"] is True
        assert doc["counts"] == {"rules": 2, "scenarios": 2, "pending": 0, "findings": 0}
        assert [r["scenarios"] for r in doc["rules"]] == [["SCEN-01"], ["SCEN-02"]]
        assert [s["references"] for s in doc["scenarios"]] == [["BR-01"], ["BR-02"]]

    def test_fresh_templates_are_no_data_not_a_clean_bill_of_health(self, tmp_path):
        doc = report(tmp_path, TEMPLATE_RULES, TEMPLATE_SCENARIOS)
        assert doc["has_data"] is False and doc["rules"] == [] and doc["scenarios"] == []
        assert doc["findings"] == []
        assert any("placeholders" in n for n in doc["notes"])

    def test_a_half_filled_rule_is_a_real_rule_not_a_placeholder(self, tmp_path):
        # 1 of 5 non-empty cells bracketed: not more than half, so it is a record.
        rules = rules_doc("| BR-01 | amount > 10k | escalate | policy 4.2 | [to confirm] |")
        doc = report(tmp_path, rules, scen_doc("| SCEN-01 | x (BR-01) | y |"))
        assert [r["id"] for r in doc["rules"]] == ["BR-01"]
        assert checks(doc) == [("approver-missing", "BR-01")]


class TestFindingKinds:
    def test_a_rule_with_no_source_is_flagged_for_empty_and_dash_forms(self, tmp_path):
        rules = rules_doc(
            "| BR-01 | c | o |  | Jane |",
            "| BR-02 | c | o | — | Jane |",
            "| BR-03 | c | o | - | Jane |",
            "| BR-04 | c | o | policy 1 | Jane |",
        )
        scen = scen_doc("| SCEN-01 | BR-01 BR-02 BR-03 BR-04 | ok |")
        doc = report(tmp_path, rules, scen)
        assert checks(doc) == [("source-missing", "BR-01"), ("source-missing", "BR-02"), ("source-missing", "BR-03")]

    def test_a_rule_with_no_approver_is_flagged(self, tmp_path):
        rules = rules_doc("| BR-01 | c | o | policy 1 |  |", "| BR-02 | c | o | policy 1 | Jane |")
        doc = report(tmp_path, rules, scen_doc("| SCEN-01 | BR-01 BR-02 | ok |"))
        assert checks(doc) == [("approver-missing", "BR-01")]

    def test_a_scenario_referencing_no_rule_is_flagged(self, tmp_path):
        scen = scen_doc("| SCEN-01 | a (BR-01) | ok |", "| SCEN-02 | nothing relevant | ok |")
        doc = report(tmp_path, rules_doc("| BR-01 | c | o | policy 1 | Jane |"), scen)
        assert checks(doc) == [("scenario-no-rule", "SCEN-02")]

    def test_a_rule_no_scenario_references_is_flagged(self, tmp_path):
        rules = rules_doc("| BR-01 | c | o | p | Jane |", "| BR-02 | c | o | p | Jane |")
        doc = report(tmp_path, rules, scen_doc("| SCEN-01 | only BR-01 | ok |"))
        assert checks(doc) == [("rule-no-scenario", "BR-02")]

    def test_every_finding_is_severity_should(self, tmp_path):
        rules = rules_doc("| BR-01 | c | o |  |  |")
        doc = report(tmp_path, rules, scen_doc("| SCEN-01 | none | ok |"))
        assert len(doc["findings"]) == 4  # source, approver, scenario-no-rule, rule-no-scenario
        assert {f["severity"] for f in doc["findings"]} == {"SHOULD"}
        assert all(set(f) == {"check", "severity", "subject", "message"} for f in doc["findings"])

    def test_scenario_references_are_case_and_zero_padding_tolerant(self, tmp_path):
        doc = report(tmp_path, rules_doc("| BR-01 | c | o | p | Jane |"), scen_doc("| SCEN-01 | see br-1 | ok |"))
        assert doc["findings"] == [] and doc["rules"][0]["scenarios"] == ["SCEN-01"]


class TestPendingRules:
    RULES = rules_doc("| BR-01 | c | o | p | Jane |",
                      "| BR-02 | c | hold *(pending DL-03)* | — | Jane |")
    SCEN = scen_doc("| SCEN-01 | BR-01 BR-02 | ok |")

    def test_a_pending_rule_is_listed_with_its_decision_id(self, tmp_path):
        log = dl_doc("| DL-03 | the question | Pat | 2026-10-01 | 2026-10-05 | open |")
        doc = report(tmp_path, self.RULES, self.SCEN, log)
        rule = next(r for r in doc["rules"] if r["id"] == "BR-02")
        assert rule["pending"] == "DL-03" and rule["pending_decision"] == "present"
        assert doc["counts"]["pending"] == 1
        assert [f["check"] for f in doc["findings"]] == ["source-missing"]

    def test_a_pending_marker_whose_decision_is_not_in_the_log_is_flagged(self, tmp_path):
        log = dl_doc("| DL-01 | other | Pat | 2026-10-01 | 2026-10-05 | open |")
        doc = report(tmp_path, self.RULES, self.SCEN, log)
        assert ("pending-missing", "BR-02") in checks(doc)
        assert next(r for r in doc["rules"] if r["id"] == "BR-02")["pending_decision"] == "missing"

    def test_with_no_decision_log_each_pending_rule_is_unverifiable_not_missing(self, tmp_path):
        doc = report(tmp_path, self.RULES, self.SCEN)
        assert ("pending-unverifiable", "BR-02") in checks(doc)
        assert not any(f["check"] == "pending-missing" for f in doc["findings"])
        assert next(r for r in doc["rules"] if r["id"] == "BR-02")["pending_decision"] == "unverifiable"

    def test_a_fresh_decision_log_template_does_not_count_its_example_row_as_a_record(self, tmp_path):
        doc = report(tmp_path, self.RULES, self.SCEN, TEMPLATE_DECISION_LOG)
        assert ("pending-missing", "BR-02") in checks(doc)

    def test_a_decision_log_without_a_table_falls_back_to_mentions(self, tmp_path):
        doc = report(tmp_path, self.RULES, self.SCEN, "# Decision log\n\nDL-03: undecided, owner Pat.\n")
        assert not any(f["check"].startswith("pending-") for f in doc["findings"])

    def test_the_template_spelling_of_the_marker_is_tolerated(self, tmp_path):
        rules = rules_doc("| BR-01 | c | hold *(pending <DL-NN>)* | policy 1 | Jane |")
        doc = report(tmp_path, rules, scen_doc("| SCEN-01 | BR-01 | ok |"), dl_doc(
            "| DL-01 | q | Pat | 2026-10-01 | 2026-10-05 | open |"))
        assert doc["rules"][0]["pending"] == "DL-NN"
        assert checks(doc) == [("pending-missing", "BR-01")]

    def test_a_rule_without_a_pending_marker_has_null_pending(self, tmp_path):
        doc = report(tmp_path, CLEAN_RULES, CLEAN_SCENARIOS)
        assert all(r["pending"] is None and r["pending_decision"] is None for r in doc["rules"])


class TestColumnsByHeader:
    def test_reordered_and_extra_columns_give_the_same_answer(self, tmp_path):
        reordered = ("# Business Rules\n\n| Notes | Approver | Source | Outcome | Condition | Rule |\n"
                     "|---|---|---|---|---|---|\n"
                     "| n | Jane | policy 1 | o | c | BR-01 |\n"
                     "| n |  |  | o | c | BR-02 |\n")
        canonical = rules_doc("| BR-01 | c | o | policy 1 | Jane |", "| BR-02 | c | o |  |  |")
        scen = scen_doc("| SCEN-01 | BR-01 BR-02 | ok |")
        a = report(tmp_path / "a", reordered, scen)
        b = report(tmp_path / "b", canonical, scen)
        assert a == b and checks(a) == [("approver-missing", "BR-02"), ("source-missing", "BR-02")]

    def test_headers_are_case_insensitive_and_scenario_columns_can_move(self, tmp_path):
        scen = ("# S\n\n| EXPECTED | INPUT | SCENARIO |\n|---|---|---|\n| ok | BR-01 | SCEN-07 |\n")
        doc = report(tmp_path, rules_doc("| BR-01 | c | o | p | Jane |"), scen)
        assert doc["scenarios"] == [{"id": "SCEN-07", "references": ["BR-01"]}] and doc["findings"] == []


class TestNoData:
    def test_missing_documents_are_a_note_and_empty_lists(self, tmp_path):
        doc = report(tmp_path)
        assert doc["has_data"] is False and doc["rules"] == [] and doc["scenarios"] == []
        assert doc["findings"] == [] and doc["notes"]

    def test_a_document_with_no_table_is_a_note_not_an_error(self, tmp_path):
        doc = report(tmp_path, "# Business Rules\n\nJust prose, no table.\n", CLEAN_SCENARIOS)
        assert any("no rules table" in n for n in doc["notes"])
        assert doc["rules"] == [] and len(doc["scenarios"]) == 2

    def test_rules_without_scenarios_are_not_reported_unreferenced(self, tmp_path):
        doc = report(tmp_path, CLEAN_RULES)
        assert doc["has_data"] is True and doc["findings"] == []
        assert any("not cross-checked" in n for n in doc["notes"])

    def test_scenarios_without_rules_are_not_reported_as_referencing_nothing_wrongly(self, tmp_path):
        doc = report(tmp_path, None, scen_doc("| SCEN-01 | no ref | ok |"))
        assert checks(doc) == [("scenario-no-rule", "SCEN-01")]

    def test_a_table_in_a_code_fence_is_ignored(self, tmp_path):
        fenced = "# R\n\n```\n" + RULES_HEADER + "| BR-01 | c | o | p | J |\n```\n"
        assert report(tmp_path, fenced, CLEAN_SCENARIOS)["rules"] == []

    def test_text_report_for_no_data_says_so(self, tmp_path):
        _, repo = project(tmp_path)
        proc = run("--repo", str(repo))
        assert proc.returncode == 0 and "no rules or scenarios to assess" in proc.stdout


class TestPathsAndModes:
    def test_standalone_explicit_paths_need_no_sdlc_directory(self, tmp_path):
        r = write(tmp_path / "any" / "rules.md", CLEAN_RULES)
        s = write(tmp_path / "other" / "scen.md", CLEAN_SCENARIOS)
        proc = run("--business-rules", str(r), "--scenarios", str(s), "--json")
        doc = json.loads(proc.stdout)
        assert proc.returncode == 0 and doc["has_data"] is True and doc["findings"] == []
        assert not (tmp_path / ".sdlc").exists()

    def test_explicit_decision_log_is_used_standalone(self, tmp_path):
        r = write(tmp_path / "rules.md", rules_doc("| BR-01 | c | hold *(pending DL-02)* | p | J |"))
        s = write(tmp_path / "scen.md", scen_doc("| SCEN-01 | BR-01 | ok |"))
        log = write(tmp_path / "dl.md", dl_doc("| DL-02 | q | P | 2026-10-01 | 2026-10-05 | open |"))
        doc = json.loads(run("--business-rules", str(r), "--scenarios", str(s), "--decision-log", str(log), "--json").stdout)
        assert doc["rules"][0]["pending_decision"] == "present" and doc["findings"] == []

    def test_only_one_explicit_path_is_enough(self, tmp_path):
        r = write(tmp_path / "rules.md", CLEAN_RULES)
        proc = run("--business-rules", str(r), "--json")
        doc = json.loads(proc.stdout)
        assert proc.returncode == 0 and doc["counts"]["rules"] == 2
        assert any("golden-scenarios" in n for n in doc["notes"])

    def test_state_and_repo_give_identical_output(self, tmp_path):
        state, repo = project(tmp_path, rules_doc("| BR-01 | c | o |  | J |"), CLEAN_SCENARIOS)
        assert run("--state", str(state), "--json").stdout == run("--repo", str(repo), "--json").stdout

    def test_an_explicit_path_overrides_the_workflow_location(self, tmp_path):
        _, repo = project(tmp_path, CLEAN_RULES, CLEAN_SCENARIOS)
        other = write(tmp_path / "elsewhere.md", rules_doc("| BR-09 | c | o | p | J |"))
        doc = json.loads(run("--repo", str(repo), "--business-rules", str(other), "--json").stdout)
        assert [r["id"] for r in doc["rules"]] == ["BR-09"]

    def test_repo_mode_finds_a_decision_log_at_the_repo_root(self, tmp_path):
        _, repo = project(tmp_path, rules_doc("| BR-01 | c | hold *(pending DL-02)* | p | J |"),
                          scen_doc("| SCEN-01 | BR-01 | ok |"))
        write(repo / "decision-log.md", dl_doc("| DL-02 | q | P | 2026-10-01 | 2026-10-05 | open |"))
        assert json.loads(run("--repo", str(repo), "--json").stdout)["findings"] == []


class TestUsageErrors:
    def test_no_input_at_all_exits_2(self):
        assert run().returncode == 2 and run("--json").returncode == 2

    def test_both_state_and_repo_exit_2(self, tmp_path):
        state, repo = project(tmp_path)
        assert run("--state", str(state), "--repo", str(repo)).returncode == 2


class TestOutputContract:
    def test_json_is_exactly_one_document_with_the_documented_shape(self, tmp_path):
        _, repo = project(tmp_path, rules_doc("| BR-01 | c | hold *(pending DL-01)* | p | J |"),
                          scen_doc("| SCEN-01 | BR-01 | ok |"))
        proc = run("--repo", str(repo), "--json")
        doc = json.loads(proc.stdout)  # raises on any text before or after the document
        assert set(doc) == {"has_data", "notes", "rules", "scenarios", "findings", "counts", "advisory"}
        assert set(doc["rules"][0]) == {"id", "source", "approver", "pending", "pending_decision", "scenarios"}

    def test_output_is_byte_identical_across_runs_and_locations(self, tmp_path):
        rules = rules_doc("| BR-01 | c | hold *(pending DL-01)* |  |  |")
        scen = scen_doc("| SCEN-01 | nothing | ok |")
        _, repo_a = project(tmp_path / "a", rules, scen)
        _, repo_b = project(tmp_path / "b", rules, scen)
        first = run("--repo", str(repo_a), "--json").stdout
        assert first == run("--repo", str(repo_a), "--json").stdout == run("--repo", str(repo_b), "--json").stdout
        text = run("--repo", str(repo_a)).stdout
        assert text == run("--repo", str(repo_b)).stdout

    def test_text_report_lists_pending_rules_with_their_decision_id_and_findings(self, tmp_path):
        _, repo = project(tmp_path, rules_doc("| BR-01 | c | hold *(pending DL-01)* |  | J |"),
                          scen_doc("| SCEN-01 | BR-01 | ok |"))
        out = run("--repo", str(repo)).stdout
        assert "PENDING BR-01" in out and "DL-01" in out and "ADVISE  [SHOULD]" in out
        assert out.rstrip().endswith("(SHOULD; never blocks).")

    def test_an_unreadable_path_that_is_a_directory_is_a_note_not_a_crash(self, tmp_path):
        proc = run("--business-rules", str(tmp_path), "--json")
        assert proc.returncode == 0 and json.loads(proc.stdout)["has_data"] is False


class TestMetricsLog:
    def test_state_mode_appends_one_entry_per_run_with_data(self, tmp_path):
        state, _ = project(tmp_path, rules_doc("| BR-01 | c | o |  | J |"), scen_doc("| SCEN-01 | BR-01 | ok |"))
        run("--state", str(state))
        run("--state", str(state))
        lines = (state.parent / "metrics" / "rules-log.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        entry = json.loads(lines[0])
        assert entry["rules"] == 1 and entry["findings"] == 1
        assert entry["advisories"] == [{"check": "source-missing", "subject": "BR-01"}]

    def test_repo_mode_and_no_data_runs_write_no_log(self, tmp_path):
        state, repo = project(tmp_path / "a", CLEAN_RULES, CLEAN_SCENARIOS)
        run("--repo", str(repo))
        assert not (state.parent / "metrics").exists()
        state2, _ = project(tmp_path / "b")
        run("--state", str(state2))
        assert not (state2.parent / "metrics").exists()

    def test_the_log_never_changes_the_output(self, tmp_path):
        state, _ = project(tmp_path, CLEAN_RULES, CLEAN_SCENARIOS)
        assert run("--state", str(state), "--json").stdout == run("--state", str(state), "--json").stdout


@pytest.mark.parametrize("name", ["rules_check.py"])
def test_the_script_does_not_import_from_the_protected_core_or_shape_cli(name):
    source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
    for module in ("check_spec", "check_gates", "phase_model", "advance_phase", "document_shape_cli"):
        assert f"import {module}" not in source and f"from {module}" not in source
