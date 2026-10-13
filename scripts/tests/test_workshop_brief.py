"""workshop_brief.py build - the mechanical half of /sprd-brief (spec 0022).

What these protect:
  * NOTHING IS INVENTED. Every contradiction and question on the page is the analyst's own text,
    carried with its CON-NN / Q-NN id and both source references; claims are only accepted with a
    DOC-NNN.
  * A REFUSAL WRITES NOTHING. Every refusal exits 1 with one `Error:` line and leaves no file.
  * THE ONE-PAGE RULE IS MECHANICAL. 5 contradictions, 12 on-page questions, and pre-workshop
    questions go to `emailed_instead` instead of onto the page.
  * DETERMINISTIC. The same inputs give a byte-identical brief, whatever the template's line ending.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "workshop_brief.py"
DOCS = Path(__file__).resolve().parent / "fixtures" / "documents"
TEMPLATE = ROOT / "templates" / "phases" / "00-discovery" / "workshop-brief.md"
SHAPE = ROOT / "templates" / "phases" / "00-discovery" / "workshop-brief.shape.yaml"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

LOGISTICS = {"client_name": "Acme Insurance", "date_time_location": "2026-10-14 09:00, Acme HQ",
             "duration": "3 hours", "attendees": [{"name": "Dana Ortiz", "role": "VP Claims"},
                                                  {"name": "Tom Becker", "role": "Head of IT"}],
             "facilitator": "Sam Kruger (Pod Lead)"}
CLAIMS = [{"text": "The average claim takes 19 days to first payment", "doc_ref": "DOC-003"}]
DECISIONS = ["Is phone intake for large commercial losses in or out of the first release?"]
FIXTURE_FILES = ["--contradictions-file", str(DOCS / "contradiction-list.md"),
                 "--questions-file", str(DOCS / "question-list.md"),
                 "--registry-file", str(DOCS / "document-registry.md")]


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          encoding="utf-8", env=ENV)


def build_args(out, **over):
    """Arguments for a standalone build from the shipped fixtures; `over` replaces a flag's value."""
    flags = {"--contradictions": "CON-01,CON-02", "--questions": "Q-01,Q-03,Q-04,Q-05",
             "--load-bearing": "DOC-001,DOC-003,DOC-002", "--decisions-json": json.dumps(DECISIONS),
             "--logistics-json": json.dumps(LOGISTICS), "--claims-json": json.dumps(CLAIMS)}
    flags.update(over)
    return ["build", "--repo", str(out.parent), *FIXTURE_FILES, "--output", str(out),
            *[a for k, v in flags.items() if v is not None for a in (k, v)]]


def brief(tmp_path):
    out = tmp_path / "brief.md"
    result = run(*build_args(out))
    assert result.returncode == 0, result.stderr
    return out.read_text(encoding="utf-8")


def refused(tmp_path, *extra, **over):
    out = tmp_path / "brief.md"
    result = run(*build_args(out, **over), *extra)
    assert result.returncode == 1
    assert not out.exists()
    assert result.stdout == ""
    lines = result.stderr.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("Error: ")
    return lines[0]


def section(text, heading):
    return re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.S | re.M).group(1)


class TestHappyPath:
    def test_every_selected_id_and_both_source_refs_are_present(self, tmp_path):
        text = brief(tmp_path)
        for token in ("(CON-01)", "(CON-02)", "(Q-01)", "(Q-03)", "(Q-04)", "(Q-05)",
                      "DOC-001 s2.1", "DOC-003 s4.3", "DOC-007 s3.2", "DOC-001 s5.4"):
            assert token in text

    def test_contradiction_carries_both_quotes_and_the_analysts_question(self, tmp_path):
        item = section(brief(tmp_path), "Where the documents disagree")
        assert ('1. DOC-001 s2.1 says "The portal will replace all existing claim intake channels, '
                'including phone and email."; DOC-003 s4.3 says "Large commercial losses continue '
                'to be taken by phone through the specialty desk." '
                "**Which intake channels must the portal retire in the first release?** (CON-01)") in item

    def test_no_placeholder_remains_and_the_authoring_comment_is_left_out(self, tmp_path):
        text = brief(tmp_path)
        assert "${" not in text
        assert "HARD RULES" not in text

    def test_header_and_reading_section_are_filled_from_logistics_and_registry(self, tmp_path):
        text = brief(tmp_path)
        assert text.startswith("# Workshop Brief — Acme Insurance Outcome Workshop\n")
        assert "**Attendees:** Dana Ortiz (VP Claims), Tom Becker (Head of IT)" in text
        assert "**Facilitator:** Sam Kruger (Pod Lead)" in text
        reading = section(text, "What we read")
        assert reading.startswith("\n3 documents provided by your team")
        assert "DOC-001 (claims-modernization-rfp.pdf: goals, scope, vendor requirements)" in reading
        assert reading.index("DOC-001") < reading.index("DOC-003") < reading.index("DOC-002")

    def test_claims_decisions_and_agenda_survive(self, tmp_path):
        text = brief(tmp_path)
        assert "- The average claim takes 19 days to first payment (DOC-003)" in text
        decisions = section(text, "Decisions we need from the room")
        assert "1. The one success metric" in decisions and "2. The product-owner commitment" in decisions
        assert f"3. {DECISIONS[0]}" in decisions
        assert "| The one metric | 30 min |" in section(text, "Agenda")

    def test_appendices_point_at_the_source_documents_without_inlining_them(self, tmp_path):
        text = brief(tmp_path)
        assert "See `question-list.md`" in section(text, "Appendix A: Full question list")
        assert "### CON-01" not in text and "#### Q-01" not in text

    def test_the_built_brief_passes_the_shape_completeness_check(self, tmp_path):
        out = tmp_path / "brief.md"
        run(*build_args(out))
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_document_completeness.py"),
                                 "--doc", str(out), "--shape", str(SHAPE), "--json"],
                                capture_output=True, text=True, encoding="utf-8", env=ENV)
        assert json.loads(result.stdout) == []


class TestGrouping:
    def test_questions_are_grouped_in_the_question_list_templates_block_order(self, tmp_path):
        out = tmp_path / "brief.md"
        run(*build_args(out, **{"--questions": "Q-05,Q-04,Q-03,Q-01"}))
        questions = section(out.read_text(encoding="utf-8"), "What nobody has written down")
        labels = re.findall(r"^- \*\*(.+?):\*\*", questions, re.M)
        assert labels == ["Problem", "Outcomes", "Success Metric", "Constraints"]

    def test_the_order_of_the_arguments_does_not_change_the_page(self, tmp_path):
        a, b = tmp_path / "a.md", tmp_path / "b.md"
        run(*build_args(a, **{"--questions": "Q-01,Q-03", "--contradictions": "CON-01,CON-02"}))
        run(*build_args(b, **{"--questions": "Q-03,Q-01", "--contradictions": "CON-02,CON-01"}))
        assert a.read_bytes() == b.read_bytes()

    def test_unrecognised_block_sorts_after_the_known_ones(self, tmp_path):
        qs = tmp_path / "q.md"
        qs.write_text((DOCS / "question-list.md").read_text(encoding="utf-8").replace(
            "### Block: Other", "### Block: Budget"), encoding="utf-8")
        out = tmp_path / "brief.md"
        args = build_args(out, **{"--questions": "Q-08,Q-01"})
        args[args.index("--questions-file") + 1] = str(qs)
        # Q-08 is routed to interview, so select a workshop question under the renamed block instead
        qs.write_text(qs.read_text(encoding="utf-8").replace("- **Route:** interview", "- **Route:** workshop"),
                      encoding="utf-8")
        assert run(*args).returncode == 0
        labels = re.findall(r"^- \*\*(.+?):\*\*", section(out.read_text(encoding="utf-8"),
                                                          "What nobody has written down"), re.M)
        assert labels == ["Problem", "Budget"]


class TestLimits:
    def test_more_than_five_contradictions_is_refused(self, tmp_path):
        cons = "".join(f"### CON-{n:02d}: t\n- **Severity:** minor\n- **Source A — DOC-001 s1:** \"a\"\n"
                       f"- **Source B — DOC-002 s1:** \"b\"\n- **The question for the room:** Why?\n\n"
                       for n in range(1, 7))
        path = tmp_path / "c.md"
        path.write_text("# Contradiction List\n\n## Contradictions\n\n" + cons, encoding="utf-8")
        out = tmp_path / "brief.md"
        args = build_args(out, **{"--contradictions": "CON-01,CON-02,CON-03,CON-04,CON-05,CON-06"})
        args[args.index("--contradictions-file") + 1] = str(path)
        result = run(*args)
        assert result.returncode == 1 and not out.exists()
        assert "6 contradictions" in result.stderr and "limit is 5" in result.stderr

    def test_five_contradictions_is_allowed(self, tmp_path):
        cons = "".join(f"### CON-{n:02d}: t\n- **Severity:** minor\n- **Source A — DOC-001 s1:** \"a\"\n"
                       f"- **Source B — DOC-002 s1:** \"b\"\n- **The question for the room:** Why?\n\n"
                       for n in range(1, 6))
        path = tmp_path / "c.md"
        path.write_text("## Contradictions\n\n" + cons, encoding="utf-8")
        out = tmp_path / "brief.md"
        args = build_args(out, **{"--contradictions": "CON-01,CON-02,CON-03,CON-04,CON-05"})
        args[args.index("--contradictions-file") + 1] = str(path)
        assert run(*args).returncode == 0

    def _many_questions(self, tmp_path, count):
        qs = "".join(f"#### Q-{n:02d}: Question {n}?\n- **Route:** workshop\n\n" for n in range(1, count + 1))
        path = tmp_path / "q.md"
        path.write_text("### Block: Problem\n\n" + qs, encoding="utf-8")
        ids = ",".join(f"Q-{n:02d}" for n in range(1, count + 1))
        out = tmp_path / "brief.md"
        args = build_args(out, **{"--questions": ids})
        args[args.index("--questions-file") + 1] = str(path)
        return out, run(*args)

    def test_more_than_twelve_questions_is_refused(self, tmp_path):
        out, result = self._many_questions(tmp_path, 13)
        assert result.returncode == 1 and not out.exists()
        assert "13 questions" in result.stderr and "limit is 12" in result.stderr

    def test_twelve_questions_is_allowed(self, tmp_path):
        out, result = self._many_questions(tmp_path, 12)
        assert result.returncode == 0 and out.exists()


class TestRefusals:
    def test_unknown_contradiction_id(self, tmp_path):
        assert "unknown contradiction id: CON-09" in refused(tmp_path, **{"--contradictions": "CON-01,CON-09"})

    def test_unknown_question_id(self, tmp_path):
        assert "unknown question id: Q-99" in refused(tmp_path, **{"--questions": "Q-99"})

    def test_unknown_load_bearing_document(self, tmp_path):
        assert "unknown document id: DOC-050" in refused(tmp_path, **{"--load-bearing": "DOC-001,DOC-050"})

    def test_malformed_id_is_unknown_not_a_crash(self, tmp_path):
        assert "unknown question id: banana" in refused(tmp_path, **{"--questions": "banana"})

    def test_claim_without_a_doc_reference(self, tmp_path):
        claims = json.dumps([*CLAIMS, {"text": "An orphan fact", "doc_ref": ""}])
        assert "claim 2 has no DOC-NNN reference" in refused(tmp_path, **{"--claims-json": claims})

    def test_claim_citing_something_that_is_not_a_doc_id(self, tmp_path):
        claims = json.dumps([{"text": "A fact", "doc_ref": "the RFP"}])
        assert "no DOC-NNN reference" in refused(tmp_path, **{"--claims-json": claims})

    def test_interview_routed_question_is_refused(self, tmp_path):
        assert "Q-08 is routed to interview" in refused(tmp_path, **{"--questions": "Q-08"})

    def test_existing_brief_is_not_overwritten_without_force(self, tmp_path):
        out = tmp_path / "brief.md"
        out.write_text("hand-edited", encoding="utf-8")
        result = run(*build_args(out))
        assert result.returncode == 1 and "already exists" in result.stderr
        assert out.read_text(encoding="utf-8") == "hand-edited"

    def test_force_overwrites(self, tmp_path):
        out = tmp_path / "brief.md"
        out.write_text("hand-edited", encoding="utf-8")
        assert run(*build_args(out), "--force").returncode == 0
        assert out.read_text(encoding="utf-8").startswith("# Workshop Brief")

    def test_a_placeholder_smuggled_in_through_an_input_is_refused(self, tmp_path):
        claims = json.dumps([{"text": "Costs ${AMOUNT} a day", "doc_ref": "DOC-003"}])
        assert "unfilled placeholders: ${AMOUNT}" in refused(tmp_path, **{"--claims-json": claims})

    def test_invalid_json_is_refused_not_a_traceback(self, tmp_path):
        assert "--claims-json" in refused(tmp_path, **{"--claims-json": "[not json"})


class TestMissingRequiredInput:
    @pytest.mark.parametrize("flag", ["--logistics-json", "--decisions-json", "--load-bearing"])
    def test_a_missing_required_flag_names_itself(self, tmp_path, flag):
        assert flag in refused(tmp_path, **{flag: None})

    def test_logistics_missing_fields_are_all_named(self, tmp_path):
        partial = json.dumps({"client_name": "Acme", "attendees": LOGISTICS["attendees"]})
        message = refused(tmp_path, **{"--logistics-json": partial})
        assert "date_time_location" in message and "duration" in message and "facilitator" in message

    def test_missing_registry_is_refused(self, tmp_path):
        out = tmp_path / "brief.md"
        args = build_args(out)
        args[args.index("--registry-file") + 1] = str(tmp_path / "nope.md")
        result = run(*args)
        assert result.returncode == 1 and "document registry not found" in result.stderr
        assert not out.exists()

    def test_selecting_from_a_missing_question_list_is_refused(self, tmp_path):
        out = tmp_path / "brief.md"
        args = build_args(out)
        args[args.index("--questions-file") + 1] = str(tmp_path / "nope.md")
        result = run(*args)
        assert result.returncode == 1 and "question list not found" in result.stderr
        assert not out.exists()


class TestPreWorkshopRouting:
    def test_pre_workshop_questions_are_emailed_instead_not_placed_or_refused(self, tmp_path):
        out = tmp_path / "brief.md"
        result = run(*build_args(out, **{"--questions": "Q-01,Q-02,Q-07"}), "--json")
        assert result.returncode == 0
        doc = json.loads(result.stdout)
        assert doc["questions"]["ids"] == ["Q-01"]
        assert doc["questions"]["emailed_instead"] == ["Q-02", "Q-07"]
        text = out.read_text(encoding="utf-8")
        assert "(Q-01)" in text and "(Q-02)" not in text and "(Q-07)" not in text

    def test_emailed_questions_do_not_count_against_the_page_limit(self, tmp_path):
        qs = "".join(f"#### Q-{n:02d}: Question {n}?\n- **Route:** "
                     f"{'pre-workshop' if n > 12 else 'workshop'}\n\n" for n in range(1, 15))
        path = tmp_path / "q.md"
        path.write_text("### Block: Problem\n\n" + qs, encoding="utf-8")
        out = tmp_path / "brief.md"
        args = build_args(out, **{"--questions": ",".join(f"Q-{n:02d}" for n in range(1, 15))})
        args[args.index("--questions-file") + 1] = str(path)
        doc = json.loads(run(*args, "--json").stdout)
        assert doc["questions"]["on_page"] == 12
        assert doc["questions"]["emailed_instead"] == ["Q-13", "Q-14"]


class TestJson:
    def test_exactly_one_document_with_the_documented_shape(self, tmp_path):
        out = tmp_path / "brief.md"
        result = run(*build_args(out), "--json")
        assert result.returncode == 0
        doc = json.loads(result.stdout)  # one document and nothing else, or this raises
        assert set(doc) == {"path", "contradictions", "questions", "claims", "load_bearing",
                            "provisional_ids", "lint", "notes"}
        assert Path(doc["path"]) == out.resolve()
        assert doc["contradictions"] == {"total": 2, "on_page": 2, "ids": ["CON-01", "CON-02"]}
        assert doc["questions"] == {"total": 8, "on_page": 4, "ids": ["Q-01", "Q-03", "Q-04", "Q-05"],
                                    "emailed_instead": []}
        assert doc["claims"] == 1 and doc["load_bearing"] == ["DOC-001", "DOC-003", "DOC-002"]
        assert doc["lint"] == []

    def test_a_refusal_prints_nothing_on_stdout_even_with_json(self, tmp_path):
        out = tmp_path / "brief.md"
        result = run(*build_args(out, **{"--questions": "Q-99"}), "--json")
        assert result.returncode == 1 and result.stdout == ""

    def test_text_report_is_the_default(self, tmp_path):
        result = run(*build_args(tmp_path / "brief.md"))
        assert result.stdout.startswith("Workshop Brief Drafted")
        assert "4 on the page" in result.stdout

    def test_selecting_nothing_still_builds_and_says_so(self, tmp_path):
        out = tmp_path / "brief.md"
        doc = json.loads(run(*build_args(out, **{"--contradictions": None, "--questions": None,
                                                 "--claims-json": None}), "--json").stdout)
        assert doc["contradictions"]["on_page"] == 0 and doc["questions"]["on_page"] == 0
        assert any("No contradictions selected" in n for n in doc["notes"])
        assert any("No claims supplied" in n for n in doc["notes"])
        assert "${" not in out.read_text(encoding="utf-8")


class TestLint:
    def test_a_decision_that_states_an_outcome_is_flagged_with_its_line(self, tmp_path):
        out = tmp_path / "brief.md"
        decisions = json.dumps(["Phone intake stays in release one"])
        doc = json.loads(run(*build_args(out, **{"--decisions-json": decisions}), "--json").stdout)
        lines = out.read_text(encoding="utf-8").split("\n")
        assert len(doc["lint"]) == 1
        flagged = doc["lint"][0]
        assert lines[flagged["line"] - 1] == "3. Phone intake stays in release one"
        assert "question mark" in flagged["message"]

    def test_the_two_standing_template_decisions_are_exempt(self, tmp_path):
        doc = json.loads(run(*build_args(tmp_path / "brief.md"), "--json").stdout)
        assert doc["lint"] == []

    def test_a_question_without_a_question_mark_is_flagged_but_the_build_succeeds(self, tmp_path):
        qs = tmp_path / "q.md"
        qs.write_text("### Block: Problem\n\n#### Q-01: Tell us the cost per day\n- **Route:** workshop\n",
                      encoding="utf-8")
        out = tmp_path / "brief.md"
        args = build_args(out, **{"--questions": "Q-01"})
        args[args.index("--questions-file") + 1] = str(qs)
        result = run(*args, "--json")
        doc = json.loads(result.stdout)
        assert result.returncode == 0 and out.exists()
        assert len(doc["lint"]) == 1

    def test_the_trailing_id_is_ignored_when_judging_the_question_mark(self, tmp_path):
        doc = json.loads(run(*build_args(tmp_path / "brief.md"), "--json").stdout)
        assert doc["lint"] == []  # every on-page line ends "? (Q-NN)"


class TestModes:
    def test_both_state_and_repo_is_a_usage_error(self, tmp_path):
        result = run("build", "--state", str(tmp_path / "state.yaml"), "--repo", str(tmp_path))
        assert result.returncode == 2

    def test_neither_is_a_usage_error(self):
        assert run("build").returncode == 2

    def test_no_verb_is_a_usage_error(self):
        assert run().returncode == 2

    def test_standalone_is_marked_provisional(self, tmp_path):
        doc = json.loads(run(*build_args(tmp_path / "brief.md"), "--json").stdout)
        assert doc["provisional_ids"] is True
        assert any("provisional" in n for n in doc["notes"])

    def _project(self, tmp_path):
        folder = tmp_path / ".sdlc" / "artifacts" / "00-discovery"
        folder.mkdir(parents=True)
        (tmp_path / ".sdlc" / "state.yaml").write_text("phase: 0\n", encoding="utf-8")
        for name in ("contradiction-list", "question-list", "document-registry"):
            (folder / f"{name}.md").write_bytes((DOCS / f"{name}.md").read_bytes())
        return folder

    @pytest.mark.parametrize("via", ["state", "repo"])
    def test_workflow_defaults_read_and_write_the_discovery_folder(self, tmp_path, via):
        folder = self._project(tmp_path)
        source = ["--state", str(tmp_path / ".sdlc" / "state.yaml")] if via == "state" else ["--repo", str(tmp_path)]
        result = run("build", *source, "--contradictions", "CON-01", "--questions", "Q-01",
                     "--load-bearing", "DOC-001", "--decisions-json", json.dumps(DECISIONS),
                     "--logistics-json", json.dumps(LOGISTICS), "--json")
        assert result.returncode == 0, result.stderr
        doc = json.loads(result.stdout)
        assert Path(doc["path"]) == (folder / "workshop-brief.md").resolve()
        assert doc["provisional_ids"] is False
        assert not any("provisional" in n for n in doc["notes"])

    def test_missing_state_file_is_refused(self, tmp_path):
        result = run("build", "--state", str(tmp_path / "nope.yaml"))
        assert result.returncode == 1 and "state file not found" in result.stderr

    def test_standalone_default_output_sits_beside_the_explicit_inputs(self, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        for name in ("contradiction-list", "question-list", "document-registry"):
            (folder / f"{name}.md").write_bytes((DOCS / f"{name}.md").read_bytes())
        result = run("build", "--repo", str(tmp_path),
                     "--registry-file", str(folder / "document-registry.md"),
                     "--questions-file", str(folder / "question-list.md"),
                     "--questions", "Q-01", "--load-bearing", "DOC-001",
                     "--decisions-json", json.dumps(DECISIONS), "--logistics-json", json.dumps(LOGISTICS))
        assert result.returncode == 0, result.stderr
        assert (folder / "workshop-brief.md").is_file()
        assert not (tmp_path / ".sdlc").exists()

    def test_json_arguments_may_be_files(self, tmp_path):
        logistics, decisions = tmp_path / "l.json", tmp_path / "d.json"
        logistics.write_text(json.dumps(LOGISTICS), encoding="utf-8")
        decisions.write_text(json.dumps(DECISIONS), encoding="utf-8")
        out = tmp_path / "brief.md"
        result = run(*build_args(out, **{"--logistics-json": str(logistics), "--decisions-json": str(decisions)}))
        assert result.returncode == 0, result.stderr


class TestDeterminism:
    def test_two_runs_are_byte_identical_and_carry_no_timestamp(self, tmp_path):
        a, b = tmp_path / "a" / "brief.md", tmp_path / "b" / "brief.md"
        for out in (a, b):
            out.parent.mkdir()
            assert run(*build_args(out)).returncode == 0
        assert a.read_bytes() == b.read_bytes()
        assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:", a.read_text(encoding="utf-8"))

    def _build_with_template(self, monkeypatch, tmp_path, template_bytes):
        import workshop_brief
        template = tmp_path / "template.md"
        template.write_bytes(template_bytes)
        monkeypatch.setattr(workshop_brief, "TEMPLATE_PATH", template)
        out = tmp_path / "brief.md"
        with pytest.raises(SystemExit) as exit_info:
            workshop_brief.main([*build_args(out), "--force"])
        assert exit_info.value.code == 0
        return out.read_bytes()

    def test_lf_template_gives_lf_only(self, monkeypatch, tmp_path):
        data = self._build_with_template(monkeypatch, tmp_path, TEMPLATE.read_bytes().replace(b"\r\n", b"\n"))
        assert b"\r" not in data and data.endswith(b"\n")

    def test_crlf_template_gives_crlf_throughout(self, monkeypatch, tmp_path):
        lf = TEMPLATE.read_bytes().replace(b"\r\n", b"\n")
        data = self._build_with_template(monkeypatch, tmp_path, lf.replace(b"\n", b"\r\n"))
        assert data.count(b"\r\n") == data.count(b"\n") and data.endswith(b"\r\n")
        assert b"${" not in data

    def test_crlf_and_lf_briefs_differ_only_in_line_endings(self, monkeypatch, tmp_path):
        lf = TEMPLATE.read_bytes().replace(b"\r\n", b"\n")
        a = self._build_with_template(monkeypatch, tmp_path, lf)
        b = self._build_with_template(monkeypatch, tmp_path, lf.replace(b"\n", b"\r\n"))
        assert b.replace(b"\r\n", b"\n") == a
