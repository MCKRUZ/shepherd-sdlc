"""data_contract.py summary (spec 0022): the PII count behind the /sprd-data button.

What these protect:
  * A PII COUNT A PERSON CAN TRUST. PII drives the risk tier, so the count must come from the
    document's own PII column, read by header text, and must never be a guess: an odd or blank
    value is reported as unclassified, not folded into either side.
  * NEVER ZERO-AS-DATA. A missing document, a contract with no table, or one still holding only
    template placeholders reports `has_data: false`, never "0 fields, 0 PII".
  * ADVISORY BY CONSTRUCTION. Every path exits 0; only a usage error exits 2.
  * ONE DOCUMENT. `--json` prints a single JSON document and nothing else, identical run to run.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import risk_model

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "data_contract.py"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "documents" / "data-contract.md"
TEMPLATE = ROOT / "templates" / "phases" / "02-design" / "data" / "data-contract.md"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}
RELATIVE = Path("artifacts") / "02-design" / "data" / "data-contract.md"
PII_CLAUSE = "personal or client data handling"


def run(*args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPT), "summary", *args], capture_output=True,
                          text=True, encoding="utf-8", env=ENV, cwd=cwd)


def summary(*args, cwd=None):
    proc = run(*args, "--json", cwd=cwd)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)  # raises if there is any text before or after the document


def contract(tmp_path, header, rows, name="data-contract.md"):
    """A contract whose Fields table has exactly this header and these rows."""
    lines = ["# Data Contract", "", "## Fields", "", "| " + " | ".join(header) + " |",
             "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    lines += ["", "## Consumers & writers", "", "| Field | Read by | Written by |", "|---|---|---|",
              "| x | y | z |", ""]
    path = tmp_path / name
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


STD = ["Field", "Type", "Source", "PII?", "Note"]


def std_row(name, pii):
    return [name, "string", "Core", pii, "n"]


class TestTheShippedFixture:
    def test_counts_the_directly_and_indirectly_identifying_fields_as_pii(self):
        # The template defines `PII?` as no / customer-linked (indirectly identifying) / YES, and
        # its own PII summary lists "the YES / customer-linked fields": both are personal data.
        doc = summary("--doc", str(FIXTURE))
        assert doc["has_data"] is True and doc["field_count"] == 5
        assert doc["pii_fields"] == ["claimant_name", "policy_number"] and doc["pii_count"] == 2
        assert doc["advisory"] is True

    def test_the_customer_linked_ones_are_named_separately_and_nothing_is_left_unclassified(self):
        doc = summary("--doc", str(FIXTURE))
        assert doc["indirect_fields"] == ["policy_number"]
        assert doc["unclassified"] == [] and doc["notes"] == []

    def test_the_json_has_exactly_the_documented_keys(self):
        assert list(summary("--doc", str(FIXTURE))) == [
            "has_data", "notes", "field_count", "pii_fields", "indirect_fields", "pii_count",
            "unclassified", "risk_implication", "advisory"]


class TestRiskImplication:
    def test_with_a_pii_field_it_quotes_the_taxonomy_clause_verbatim(self):
        implication = summary("--doc", str(FIXTURE))["risk_implication"]
        assert implication == PII_CLAUSE
        assert implication in risk_model.TAXONOMY["HIGH"]["lands_here"]

    def test_with_no_pii_field_it_is_null(self, tmp_path):
        doc = summary("--doc", str(contract(tmp_path, STD, [std_row("a", "no"), std_row("b", "no")])))
        assert doc["has_data"] is True and doc["pii_count"] == 0 and doc["risk_implication"] is None

    def test_unclassified_alone_does_not_trigger_it(self, tmp_path):
        doc = summary("--doc", str(contract(tmp_path, STD, [std_row("a", "")])))
        assert doc["risk_implication"] is None


class TestPiiValues:
    def test_yes_y_true_in_any_case_and_decoration_are_pii(self, tmp_path):
        rows = [std_row("a", "yes"), std_row("b", "Y"), std_row("c", "TRUE"), std_row("d", "**YES**"),
                std_row("e", "`Yes`")]
        doc = summary("--doc", str(contract(tmp_path, STD, rows)))
        assert doc["pii_fields"] == ["a", "b", "c", "d", "e"] and doc["pii_count"] == 5

    def test_no_n_false_are_not_pii_and_not_unclassified(self, tmp_path):
        rows = [std_row("a", "no"), std_row("b", "N"), std_row("c", "False")]
        doc = summary("--doc", str(contract(tmp_path, STD, rows)))
        assert doc["pii_fields"] == [] and doc["unclassified"] == [] and doc["field_count"] == 3

    def test_blank_dash_and_placeholder_cells_are_unclassified(self, tmp_path):
        rows = [std_row("a", ""), std_row("b", "—"), std_row("c", "[yes/no]"), std_row("d", "<yes/no>")]
        doc = summary("--doc", str(contract(tmp_path, STD, rows)))
        assert doc["unclassified"] == ["a", "b", "c", "d"] and doc["pii_count"] == 0
        assert doc["notes"] == []  # empty/placeholder needs no explanation; an odd value does

    def test_an_odd_value_is_unclassified_with_a_note_naming_the_field(self, tmp_path):
        doc = summary("--doc", str(contract(tmp_path, STD, [std_row("a", "maybe"), std_row("b", "YES")])))
        assert doc["unclassified"] == ["a"] and doc["pii_fields"] == ["b"]
        assert len(doc["notes"]) == 1 and "'a'" in doc["notes"][0] and "maybe" in doc["notes"][0]

    def test_a_row_shorter_than_the_header_leaves_the_missing_pii_cell_unclassified(self, tmp_path):
        path = contract(tmp_path, STD, [std_row("a", "yes")])
        path.write_text(path.read_text(encoding="utf-8").replace("| a | string | Core | yes | n |", "| a | string |", 1),
                        encoding="utf-8")
        assert summary("--doc", str(path))["unclassified"] == ["a"]


class TestColumnsAreReadByHeaderNotPosition:
    ROWS = [("claim_id", "no"), ("claimant_name", "YES"), ("notes", ""), ("ssn", "yes")]

    def test_reordered_columns_give_the_same_result(self, tmp_path):
        canonical = contract(tmp_path, STD, [std_row(n, p) for n, p in self.ROWS], "a.md")
        reordered = contract(tmp_path, ["PII?", "Note", "Field", "Source", "Type"],
                             [[p, "n", n, "Core", "string"] for n, p in self.ROWS], "b.md")
        assert summary("--doc", str(reordered)) == summary("--doc", str(canonical))

    def test_extra_columns_give_the_same_result(self, tmp_path):
        canonical = contract(tmp_path, STD, [std_row(n, p) for n, p in self.ROWS], "a.md")
        extra = contract(tmp_path, ["Owner", "Field", "Type", "Retention", "Source", "PII?", "Note", "Masked"],
                         [["o", n, "string", "1y", "Core", p, "n", "yes"] for n, p in self.ROWS], "b.md")
        assert summary("--doc", str(extra)) == summary("--doc", str(canonical))

    def test_header_case_and_wording_do_not_matter(self, tmp_path):
        path = contract(tmp_path, ["field name", "pii", "Type"], [["a", "yes", "t"], ["b", "no", "t"]])
        doc = summary("--doc", str(path))
        assert doc["pii_fields"] == ["a"] and doc["field_count"] == 2

    def test_another_table_with_no_pii_column_is_not_mistaken_for_the_fields_table(self, tmp_path):
        path = contract(tmp_path, STD, [std_row("a", "yes")])
        # the Consumers table follows the Fields table in the helper's document
        assert summary("--doc", str(path))["field_count"] == 1


class TestNoDataIsNeverZeroData:
    def assert_no_data(self, doc):
        assert doc["has_data"] is False and doc["field_count"] == 0
        assert doc["pii_fields"] == [] and doc["unclassified"] == [] and doc["pii_count"] == 0
        assert doc["risk_implication"] is None and len(doc["notes"]) == 1 and doc["advisory"] is True

    def test_a_fresh_template_has_no_data_because_every_row_is_a_placeholder(self):
        doc = summary("--doc", str(TEMPLATE))
        self.assert_no_data(doc)
        assert "placeholder" in doc["notes"][0]

    def test_a_missing_document_has_no_data_and_still_exits_zero(self, tmp_path):
        proc = run("--doc", str(tmp_path / "gone.md"), "--json")
        assert proc.returncode == 0
        self.assert_no_data(json.loads(proc.stdout))
        assert "not found" in json.loads(proc.stdout)["notes"][0]

    def test_a_document_with_no_table_has_no_data(self, tmp_path):
        path = tmp_path / "dc.md"
        path.write_text("# Data Contract\n\nNothing here yet.\n", encoding="utf-8")
        self.assert_no_data(summary("--doc", str(path)))

    def test_a_table_without_a_pii_column_has_no_data(self, tmp_path):
        path = contract(tmp_path, ["Field", "Type", "Source"], [["a", "id", "Core"]])
        # the Consumers table in the helper also lacks a PII column
        self.assert_no_data(summary("--doc", str(path)))

    def test_an_empty_file_has_no_data(self, tmp_path):
        path = tmp_path / "dc.md"
        path.write_text("", encoding="utf-8")
        self.assert_no_data(summary("--doc", str(path)))

    def test_a_directory_in_place_of_the_document_has_no_data(self, tmp_path):
        self.assert_no_data(summary("--doc", str(tmp_path)))

    def test_a_placeholder_row_beside_real_rows_is_ignored_not_counted(self, tmp_path):
        rows = [std_row("a", "yes"), ["[field name]", "[id]", "[system]", "[no / YES]", "[handling]"]]
        doc = summary("--doc", str(contract(tmp_path, STD, rows)))
        assert doc["field_count"] == 1 and doc["unclassified"] == []

    def test_the_text_report_says_no_data_rather_than_zero(self, tmp_path):
        out = run("--doc", str(tmp_path / "gone.md")).stdout
        assert "No data" in out and "Fields: 0" not in out


class TestSourcesAndArguments:
    def project(self, tmp_path):
        target = tmp_path / ".sdlc" / RELATIVE
        target.parent.mkdir(parents=True)
        target.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
        state = tmp_path / ".sdlc" / "state.yaml"
        state.write_text("project: x\n", encoding="utf-8")
        return state

    def test_repo_reads_the_default_path_under_sdlc(self, tmp_path):
        self.project(tmp_path)
        assert summary("--repo", str(tmp_path))["pii_fields"] == ["claimant_name", "policy_number"]

    def test_state_reads_the_default_path_beside_the_state_file(self, tmp_path):
        state = self.project(tmp_path)
        assert summary("--state", str(state)) == summary("--repo", str(tmp_path))

    def test_repo_with_no_contract_is_no_data_not_an_error(self, tmp_path):
        doc = summary("--repo", str(tmp_path))
        assert doc["has_data"] is False and "not found" in doc["notes"][0]

    def test_doc_works_with_no_sdlc_directory_at_all(self, tmp_path):
        assert not (tmp_path / ".sdlc").exists()
        assert summary("--doc", str(FIXTURE), cwd=tmp_path)["field_count"] == 5

    def test_doc_overrides_the_default_location(self, tmp_path):
        self.project(tmp_path)
        other = contract(tmp_path, STD, [std_row("only", "no")], "other.md")
        doc = summary("--repo", str(tmp_path), "--doc", str(other))
        assert doc["field_count"] == 1 and doc["pii_count"] == 0

    def test_state_and_repo_together_is_a_usage_error(self, tmp_path):
        assert run("--state", str(tmp_path / "s.yaml"), "--repo", str(tmp_path)).returncode == 2

    def test_no_source_at_all_is_a_usage_error(self):
        assert run("--json").returncode == 2

    def test_no_verb_is_a_usage_error(self):
        proc = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, env=ENV)
        assert proc.returncode == 2

    def test_a_usage_error_prints_no_json_to_stdout(self):
        assert run("--json").stdout == ""


class TestDeterminism:
    def test_json_is_byte_identical_across_runs(self):
        first = run("--doc", str(FIXTURE), "--json").stdout
        assert first == run("--doc", str(FIXTURE), "--json").stdout

    def test_the_text_report_is_byte_identical_across_runs(self):
        assert run("--doc", str(FIXTURE)).stdout == run("--doc", str(FIXTURE)).stdout

    def test_json_is_exactly_one_document(self):
        out = run("--doc", str(FIXTURE), "--json").stdout
        assert json.JSONDecoder().raw_decode(out)[1] == len(out.rstrip("\n"))


class TestTextReport:
    def test_lists_fields_pii_and_the_quoted_risk_line(self):
        proc = run("--doc", str(FIXTURE))
        assert proc.returncode == 0
        assert "Fields: 5" in proc.stdout and "claimant_name" in proc.stdout
        assert PII_CLAUSE in proc.stdout and "indirectly identifying (customer-linked): policy_number" in proc.stdout
        assert "Unclassified" not in proc.stdout
