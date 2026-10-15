"""Spec 0039, DS-P2 — data_spec_model.py: the pure half of a data spec.

The model is text in, text out. Every function here is exercised on in-memory strings (plus the two
real templates, read-only, for the cases where a synthetic fixture would flatter the code): no repo,
no git, no subprocess. What is pinned, and why:

  - purity           the module's AST imports no subprocess / argparse / branch_scan (kit rule 6, G8)
  - byte-preservation  frontmatter writes and the Context replacement touch only the bytes they name —
                     a trailing `# comment` survives and a CRLF file stays CRLF (the same defect
                     test_frontmatter_crlf.py pins for the other frontmatter writers)
  - D4               a named human's `accepted` data verdict is never overwritten (transition table)
  - honesty          an id that was not found says so; a parent that was not read claims nothing
"""

import ast
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import check_spec as cs  # noqa: E402
import data_spec_model as dm  # noqa: E402
import document_shape_cli as dsc  # noqa: E402
import new_spec  # noqa: E402
import sprint_model as sm  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = REPO_ROOT / "scripts" / "data_spec_model.py"
SPEC_TEMPLATE = REPO_ROOT / "templates" / "phases" / "build" / "spec.md"
DATA_TEMPLATE = REPO_ROOT / "templates" / "phases" / "build" / "data-spec.md"


# --- fixtures ----------------------------------------------------------------------------------

def crlf(text: str) -> str:
    return text.replace("\n", "\r\n")


def bare_lf(text: str) -> int:
    """How many line feeds are NOT preceded by a carriage return."""
    return sum(1 for i, c in enumerate(text) if c == "\n" and (i == 0 or text[i - 1] != "\r"))


def parent_spec(depends_on="", data_review="", *, status="draft", extra_body="") -> str:
    """A build spec as new_spec.py scaffolds one: comments on the lines the writers will touch."""
    return (
        "---\n"
        'spec: "0007"\n'
        'name: "duplicate-claim-409"\n'
        f"status: {status}            # draft | ready | in-flight | merged | deferred\n"
        "type: feature            # feature | bugfix — a bugfix PR carries the `type:bugfix` label\n"
        "risk: MEDIUM             # HIGH | MEDIUM | LOW — first-class field\n"
        'owner: "@priya-n"        # the named human accountable\n'
        f'data_review: "{data_review}"          # optional — pending | accepted | returned | n-a\n'
        f'depends_on: "{depends_on}"           # optional — comma-separated spec ids, e.g. "0007,0009"\n'
        "---\n"
        "\n"
        "# Spec 0007 — duplicate-claim-409\n"
        "\n"
        "## Goal\n"
        "A duplicate claim submission is refused.\n"
        "\n"
        "## Acceptance Checks\n"
        "- [ ] a duplicate submission returns 409 with `ERR_DUP_CLAIM`\n"
        f"{extra_body}"
    )


def lines_that_differ(before: str, after: str) -> list[str]:
    """The lines of `before` that are not in `after` (order-insensitive); both sides split on \\n."""
    a, b = before.split("\n"), after.split("\n")
    return [ln for ln in a if ln not in b]


DEPENDS_LINE = 'depends_on: ""           # optional — comma-separated spec ids, e.g. "0007,0009"'


def parent_with_depends(replacement: str) -> str:
    """parent_spec() with its `depends_on` line (the last frontmatter line) replaced by `replacement`."""
    text = parent_spec()
    assert DEPENDS_LINE in text
    return text.replace(DEPENDS_LINE, replacement)


# --- purity ------------------------------------------------------------------------------------

class TestTheModelIsPure:
    def _imports(self) -> set[str]:
        tree = ast.parse(MODEL_PATH.read_text(encoding="utf-8"))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
        return names

    def test_names_no_subprocess_argparse_or_branch_scan(self):
        assert not self._imports() & {"subprocess", "argparse", "branch_scan"}

    def test_imports_only_what_the_kit_allows(self):
        allowed = {"re", "sys", "pathlib", "dataclasses", "typing",
                   "check_spec", "sprint_model", "check_dependencies", "new_spec"}
        assert self._imports() <= allowed

    def test_the_marker_is_type_not_kind(self):
        assert dm.DATA_TYPE == "data"
        assert dm.is_data_spec({"type": "data"})
        assert not dm.is_data_spec({"kind": "data"})


# --- small readers -----------------------------------------------------------------------------

class TestSpecIdFromName:
    def test_reads_the_four_digit_prefix(self):
        assert dm.spec_id_from_name("0007-duplicate-claim-409.md") == "0007"

    @pytest.mark.parametrize("name", ["spec-template.md", "7-x.md", "00071-x.md", "", "x0007-y.md"])
    def test_anything_else_is_none(self, name):
        assert dm.spec_id_from_name(name) is None


class TestIsDataSpec:
    @pytest.mark.parametrize("fm,expected", [
        ({"type": "data"}, True),
        ({"type": " Data "}, True),
        ({"type": "DATA"}, True),
        ({"type": "feature"}, False),
        ({"type": "bugfix"}, False),
        ({"type": ""}, False),
        ({}, False),
        ({"type": None}, False),
    ])
    def test_reads_type(self, fm, expected):
        assert dm.is_data_spec(fm) is expected


class TestDataSpecError:
    def test_carries_a_kind_and_a_message(self):
        err = dm.DataSpecError("self_reference", "spec 0007 cannot serve itself")
        assert err.kind == "self_reference"
        assert "cannot serve itself" in str(err)

    def test_kind_alone_is_enough(self):
        err = dm.DataSpecError(kind="cycle")
        assert err.kind == "cycle" and str(err) == "cycle"

    def test_every_documented_kind_is_declared(self):
        assert set(dm.ERROR_KINDS) == {"missing_parent", "parent_is_data", "self_reference", "cycle",
                                       "malformed", "bad_value", "conflicting_serves", "not_data"}


# --- set_scalar_line ---------------------------------------------------------------------------

class TestSetScalarLine:
    def test_replaces_the_value_and_keeps_the_trailing_comment_text(self):
        text = parent_spec()
        out = dm.set_scalar_line(text, "type", "data")
        assert "type: data  # feature | bugfix — a bugfix PR carries the `type:bugfix` label\n" in out

    def test_only_the_edited_line_changes(self):
        text = parent_spec()
        out = dm.set_scalar_line(text, "type", "data")
        before, after = text.split("\n"), out.split("\n")
        assert len(before) == len(after)
        assert [a for a, b in zip(before, after) if a != b] == [
            "type: feature            # feature | bugfix — a bugfix PR carries the `type:bugfix` label"
        ]

    def test_the_body_is_byte_identical(self):
        text = parent_spec()
        out = dm.set_scalar_line(text, "type", "data")
        assert out[out.index("\n---\n"):] == text[text.index("\n---\n"):]

    def test_a_crlf_block_stays_crlf_on_a_replaced_line(self):
        text = crlf(parent_spec())
        out = dm.set_scalar_line(text, "type", "data")
        assert bare_lf(out) == 0
        assert out.count("\r\n") == text.count("\r\n")
        assert "type: data  # feature | bugfix — a bugfix PR carries the `type:bugfix` label\r\n" in out

    def test_a_crlf_line_without_a_comment_keeps_its_ending(self):
        text = crlf(parent_spec()).replace("type: feature            # feature | bugfix — a bugfix PR carries the `type:bugfix` label", "type: feature")
        out = dm.set_scalar_line(text, "type", "data")
        assert bare_lf(out) == 0 and "\r\ntype: data\r\n" in out

    def test_a_crlf_inserted_line_is_crlf(self):
        text = crlf(parent_spec())
        out = dm.set_scalar_line(text, "serves", '"0003"')
        assert bare_lf(out) == 0
        assert out.count("\r\n") == text.count("\r\n") + 1
        assert '\r\nserves: "0003"\r\n' in out

    def test_inserts_serves_right_after_the_type_line_when_missing(self):
        out = dm.set_scalar_line(parent_spec(), "serves", '"0003"')
        lines = out.split("\n")
        type_at = next(i for i, ln in enumerate(lines) if ln.startswith("type:"))
        assert lines[type_at + 1] == 'serves: "0003"'

    def test_inserts_after_status_when_there_is_no_type_line(self):
        text = parent_spec().replace(
            "type: feature            # feature | bugfix — a bugfix PR carries the `type:bugfix` label\n", "")
        out = dm.set_scalar_line(text, "serves", '"0003"')
        lines = out.split("\n")
        status_at = next(i for i, ln in enumerate(lines) if ln.startswith("status:"))
        assert lines[status_at + 1] == 'serves: "0003"'

    def test_a_missing_type_key_is_inserted_after_status(self):
        text = parent_spec().replace(
            "type: feature            # feature | bugfix — a bugfix PR carries the `type:bugfix` label\n", "")
        out = dm.set_scalar_line(text, "type", "data")
        lines = out.split("\n")
        status_at = next(i for i, ln in enumerate(lines) if ln.startswith("status:"))
        assert lines[status_at + 1] == "type: data"

    def test_inserts_right_after_the_opening_rule_when_there_is_neither(self):
        out = dm.set_scalar_line('---\nspec: "0001"\n---\n\nbody\n', "type", "data")
        assert out == '---\ntype: data\nspec: "0001"\n---\n\nbody\n'

    def test_an_empty_frontmatter_block_takes_the_line_after_the_opening_rule(self):
        assert dm.set_scalar_line("---\n---\nbody\n", "type", "data") == "---\ntype: data\n---\nbody\n"
        assert dm.set_scalar_line(crlf("---\n---\nbody\n"), "type", "data") == crlf("---\ntype: data\n---\nbody\n")

    def test_an_insert_stays_with_the_comment_lines_that_continue_the_type_entry(self):
        # templates/phases/build/spec.md wraps type's comment onto a second, comment-only line
        text = ("---\nspec: \"0001\"\nstatus: draft\n"
                "type: feature            # feature | bugfix — a bugfix PR carries the label and\n"
                "                         # must pass repro-gate\n"
                "risk: MEDIUM\n---\nbody\n")
        out = dm.set_scalar_line(text, "serves", '"0003"')
        lines = out.split("\n")
        assert lines[3].startswith("type:") and lines[4].lstrip().startswith("# must pass")
        assert lines[5] == 'serves: "0003"' and lines[6] == "risk: MEDIUM"

    def test_a_line_that_already_holds_the_value_is_left_byte_for_byte(self):
        text = ("---\nspec: \"0001\"\nstatus: draft\n"
                "type: data               # a data spec\n"
                'serves: "0007"           # the build spec\n---\nbody\n')
        assert dm.set_scalar_line(text, "type", "data") is text or dm.set_scalar_line(text, "type", "data") == text
        assert dm.set_scalar_line(text, "serves", '"0007"') == text

    def test_a_key_that_is_a_prefix_of_another_key_is_not_confused_with_it(self):
        text = '---\nspec: "0001"\nserves_note: x\n---\nbody\n'
        out = dm.set_scalar_line(text, "serves", '"0003"')
        assert "serves_note: x" in out and 'serves: "0003"' in out

    def test_a_fully_quoted_value_is_written_verbatim(self):
        out = dm.set_scalar_line(parent_spec(), "serves", '"0003"')
        assert 'serves: "0003"\n' in out
        assert cs.parse_frontmatter(out)[0]["serves"] == "0003"

    @pytest.mark.parametrize("value", [
        "a#b", 'a"b', "a'b", "a\nb", "a\rb", "a\r\nb", '"a"b"', '"0007', '0007"', "'a\"b'", '"a#b"', '"a\nb"', '"',
    ])
    def test_refuses_a_hash_a_stray_quote_or_a_line_break(self, value):
        with pytest.raises(ValueError):
            dm.set_scalar_line(parent_spec(), "serves", value)

    @pytest.mark.parametrize("key", ["", "a b", "a:b", "a\nb", "1a", "x-y"])
    def test_refuses_a_key_that_is_not_a_plain_name(self, key):
        with pytest.raises(ValueError):
            dm.set_scalar_line(parent_spec(), key, "x")

    @pytest.mark.parametrize("text", ["# no frontmatter\n", "", "---\nspec: \"0001\"\nnever closed\n"])
    def test_refuses_text_with_no_frontmatter_block(self, text):
        with pytest.raises(ValueError, match="no frontmatter block"):
            dm.set_scalar_line(text, "type", "data")


# --- mark_data ---------------------------------------------------------------------------------

class TestMarkData:
    def test_sets_type_bare_and_serves_quoted(self):
        out = dm.mark_data(parent_spec(), "0003")
        fm, _ = cs.parse_frontmatter(out)
        assert fm["type"] == "data" and fm["serves"] == "0003"
        assert "\ntype: data  # " in out and '\nserves: "0003"\n' in out
        assert dm.is_data_spec(fm)

    def test_idempotent(self):
        once = dm.mark_data(parent_spec(), "0003")
        assert dm.mark_data(once, "0003") == once

    def test_idempotent_on_a_crlf_file(self):
        once = dm.mark_data(crlf(parent_spec()), "0003")
        assert bare_lf(once) == 0
        assert dm.mark_data(once, "0003") == once

    def test_a_different_serves_is_a_conflict(self):
        once = dm.mark_data(parent_spec(), "0003")
        with pytest.raises(dm.DataSpecError) as exc:
            dm.mark_data(once, "0004")
        assert exc.value.kind == "conflicting_serves"
        assert "0003" in str(exc.value)

    @pytest.mark.parametrize("placeholder", ['"NNNN"', '""', "TODO"])
    def test_an_unfilled_serves_is_not_a_conflict(self, placeholder):
        text = dm.set_scalar_line(parent_spec(), "serves", placeholder)
        out = dm.mark_data(text, "0003")
        assert cs.parse_frontmatter(out)[0]["serves"] == "0003"

    def test_the_body_and_every_other_frontmatter_line_survive(self):
        text = parent_spec()
        out = dm.mark_data(text, "0003")
        assert out.split("\n---\n", 1)[1] == text.split("\n---\n", 1)[1]
        assert lines_that_differ(text, out) == [
            "type: feature            # feature | bugfix — a bugfix PR carries the `type:bugfix` label"
        ]

    def test_no_frontmatter_is_malformed(self):
        with pytest.raises(dm.DataSpecError) as exc:
            dm.mark_data("# just a heading\n", "0003")
        assert exc.value.kind == "malformed"

    @pytest.mark.parametrize("parent_id", ["", "7", "x", "0007 ", 'a"b'])
    def test_a_parent_id_that_is_not_a_spec_id_is_a_bad_value(self, parent_id):
        with pytest.raises(dm.DataSpecError) as exc:
            dm.mark_data(parent_spec(), parent_id)
        assert exc.value.kind == "bad_value"

    def test_marks_a_spec_rendered_from_the_real_template(self):
        rendered = new_spec.render_spec(SPEC_TEMPLATE.read_text(encoding="utf-8"), "0002", "claims-profile", "MEDIUM", "—")
        out = dm.mark_data(rendered, "0001")
        fm, _ = cs.parse_frontmatter(out)
        assert fm["type"] == "data" and fm["serves"] == "0001" and fm["spec"] == "0002"
        lines = out.split("\n")
        type_at = next(i for i, ln in enumerate(lines) if ln.startswith("type:"))
        # the wrapped comment line stays with `type:`; `serves` follows the whole entry
        assert lines[type_at + 1].lstrip().startswith("# must pass repro-gate")
        assert lines[type_at + 2] == 'serves: "0001"'
        assert out.split("\n---\n", 1)[1] == rendered.split("\n---\n", 1)[1]

    def test_re_serves_a_spec_rendered_from_the_data_template_without_respacing_type(self):
        rendered = new_spec.render_spec(DATA_TEMPLATE.read_text(encoding="utf-8"), "0002", "claims-profile", "MEDIUM", "—")
        out = dm.mark_data(rendered, "0001")
        assert lines_that_differ(rendered, out) == [
            'serves: "NNNN"           # the build spec this data spec serves (that spec\'s depends_on names this one)'
        ]
        assert cs.parse_frontmatter(out)[0]["serves"] == "0001"


# --- cited_refs / is_definition_line -----------------------------------------------------------

class TestCitedRefs:
    PARENT = (
        "---\n"
        'spec: "0007"\n'
        'source: "DL-99 BR-98 ADR-097 DOC-096"\n'
        "---\n"
        "\n"
        "## Goal\n"
        "Honour BR-12 and BR-03; see DL-07, DL-02, ADR-004 and DOC-004 (also DOC-001).\n"
        "BR-03 again, DL-07 again.\n"
    )

    def test_sorted_unique_per_kind(self):
        refs = dm.cited_refs(self.PARENT)
        assert refs == {
            "BR": ["BR-03", "BR-12"],
            "DL": ["DL-02", "DL-07"],
            "ADR": ["ADR-004"],
            "DOC": ["DOC-001", "DOC-004"],
        }

    def test_ignores_the_frontmatter(self):
        refs = dm.cited_refs(self.PARENT)
        assert "DL-99" not in refs["DL"] and "BR-98" not in refs["BR"]
        assert "ADR-097" not in refs["ADR"] and "DOC-096" not in refs["DOC"]

    def test_every_kind_is_present_even_when_nothing_is_cited(self):
        assert dm.cited_refs(parent_spec()) == {"BR": [], "DL": [], "ADR": [], "DOC": []}

    def test_a_text_without_frontmatter_is_read_whole(self):
        assert dm.cited_refs("see BR-03\n")["BR"] == ["BR-03"]

    @pytest.mark.parametrize("text,kind", [
        ("BR-3 is one digit", "BR"),
        ("DL-7 is one digit", "DL"),
        ("ADR-04 is two digits", "ADR"),
        ("DOC-0045 is four digits", "DOC"),
        ("DOC-04 is two digits", "DOC"),
        ("XBR-03 has a prefix", "BR"),
        ("BR-03x has a suffix", "BR"),
    ])
    def test_ids_of_the_wrong_shape_are_not_ids(self, text, kind):
        assert dm.cited_refs(text)[kind] == []

    def test_a_wider_id_is_one_id(self):
        assert dm.cited_refs("BR-100 and DL-123 and ADR-0012")["BR"] == ["BR-100"]
        assert dm.cited_refs("DL-123")["DL"] == ["DL-123"]
        assert dm.cited_refs("ADR-0012")["ADR"] == ["ADR-0012"]

    def test_reads_a_crlf_parent(self):
        assert dm.cited_refs(crlf(self.PARENT))["BR"] == ["BR-03", "BR-12"]


class TestIsDefinitionLine:
    @pytest.mark.parametrize("line", [
        "## BR-03 — duplicate claims are refused",
        "### DL-07: fail closed",
        "# ADR-004",
        "###### BR-03",
        "| BR-03 | duplicate claims | refused |",
        "|BR-03|duplicate claims|",
        "|   BR-03   | x |",
    ])
    def test_a_heading_or_a_table_row_that_leads_with_the_id_defines_it(self, line):
        ref = re.search(r"(BR|DL|ADR)-\d+", line).group(0)
        assert dm.is_definition_line(line, ref)

    @pytest.mark.parametrize("line", [
        "Honour BR-03 when a duplicate arrives.",
        "- BR-03 is cited here",
        "| 1 | BR-03 |",                    # an id in a later cell cites, it does not define
        "## BR-035 — a different rule",     # a longer id is not this id
        "####### BR-03",                    # seven hashes is not a heading
        "##BR-03",                          # no space after the hashes
        "",
    ])
    def test_a_line_that_merely_cites_it_does_not(self, line):
        assert not dm.is_definition_line(line, "BR-03")

    def test_the_reference_is_matched_literally(self):
        assert not dm.is_definition_line("| BRx03 | y |", "BR.03")
        assert dm.is_definition_line("## BR.03", "BR.03")


# --- render_context ----------------------------------------------------------------------------

GOLDEN_CONTEXT = (
    "**Serves:** spec 0007 — `specs/0007-duplicate-claim-409.md`\n"
    "\n"
    "**Parent acceptance checks (read-only copy, taken 2026-10-15):**\n"
    "- [ ] a duplicate submission returns 409 …\n"
    "\n"
    "**Business rules:**\n"
    "- BR-03 — `.sdlc/artifacts/01-requirements/business-rules.md`\n"
    "\n"
    "**Decisions:**\n"
    "- none\n"
    "\n"
    "**Decision records:**\n"
    "- none\n"
    "\n"
    "**Intake documents:**\n"
    "- DOC-004 — `.sdlc/context/intake/DOC-004-vendor-api.md`"
)


class TestRenderContext:
    def render(self, **kw):
        args = dict(
            parent_id="0007",
            parent_rel_path="specs/0007-duplicate-claim-409.md",
            parent_checks=["a duplicate submission returns 409 …"],
            refs={"BR": ["BR-03"], "DL": [], "ADR": [], "DOC": ["DOC-004"]},
            resolved={"BR-03": ".sdlc/artifacts/01-requirements/business-rules.md",
                      "DOC-004": ".sdlc/context/intake/DOC-004-vendor-api.md"},
            today="2026-10-15",
        )
        args.update(kw)
        return dm.render_context(**args)

    def test_matches_the_golden_layout(self):
        assert self.render() == GOLDEN_CONTEXT

    def test_has_no_trailing_newline(self):
        assert not self.render().endswith("\n")

    def test_an_unresolved_ref_says_so_and_never_invents_a_path(self):
        out = self.render(refs={"BR": [], "DL": ["DL-07"], "ADR": [], "DOC": []}, resolved={"DL-07": None})
        assert "- DL-07 — not found in this repository" in out
        assert "**Decisions:**\n- DL-07 — not found in this repository\n" in out

    def test_a_ref_missing_from_resolved_is_unresolved_too(self):
        out = self.render(refs={"BR": ["BR-03"], "DL": [], "ADR": [], "DOC": []}, resolved={})
        assert "- BR-03 — not found in this repository" in out

    def test_empty_everything_prints_none_four_kinds_and_the_checks(self):
        out = self.render(parent_checks=[], refs={"BR": [], "DL": [], "ADR": [], "DOC": []}, resolved={})
        assert out.count("- none") == 5
        assert "**Parent acceptance checks (read-only copy, taken 2026-10-15):**\n- none\n" in out

    def test_a_kind_missing_from_refs_prints_none(self):
        out = self.render(refs={}, resolved={})
        assert out.count("- none") == 4  # the four kinds; the one check is still copied

    def test_parent_checks_are_copied_verbatim_one_unticked_line_each(self):
        out = self.render(parent_checks=["first `check`", "second -> check"])
        assert "- [ ] first `check`\n- [ ] second -> check\n" in out

    def test_kinds_come_in_the_order_br_dl_adr_doc_with_their_labels(self):
        out = self.render(refs={"BR": ["BR-01"], "DL": ["DL-02"], "ADR": ["ADR-003"], "DOC": ["DOC-004"]},
                          resolved={r: f"p/{r}.md" for r in ("BR-01", "DL-02", "ADR-003", "DOC-004")})
        order = [out.index(f"**{dm.REF_LABELS[k]}:**") for k in ("BR", "DL", "ADR", "DOC")]
        assert order == sorted(order)
        assert [dm.REF_LABELS[k] for k in dm.REF_PATTERNS] == ["Business rules", "Decisions", "Decision records", "Intake documents"]

    def test_refs_print_in_the_order_given(self):
        out = self.render(refs={"BR": ["BR-02", "BR-10"], "DL": [], "ADR": [], "DOC": []},
                          resolved={"BR-02": "a.md", "BR-10": "b.md"})
        assert out.index("BR-02") < out.index("BR-10")


# --- has_section / replace_section_body --------------------------------------------------------

SECTIONED = (
    "---\n"
    'spec: "0002"\n'
    "---\n"
    "\n"
    "# Spec 0002 — x\n"
    "\n"
    "## Goal\n"
    "g\n"
    "\n"
    "## Context\n"
    "<!-- old guidance -->\n"
    "**Serves:** spec NNNN — [path]\n"
    "\n"
    "## Scope\n"
    "\n"
    "### In scope\n"
    "- a\n"
    "\n"
    "## Deliverables\n"
    "| a | b |\n"
    "|---|---|\n"
    "| 1 | 2 |\n"
)
NEW_BODY = "**Serves:** spec 0001 — `specs/0001-x.md`\n\n- none"


class TestHasSection:
    def test_finds_a_section_case_insensitively(self):
        assert dm.has_section(SECTIONED, "Context")
        assert dm.has_section(SECTIONED, "context")
        assert dm.has_section(crlf(SECTIONED), "Context")

    @pytest.mark.parametrize("heading", ["Nope", "In scope", "Cont", "Contexts"])
    def test_absent_headings_are_absent(self, heading):
        assert not dm.has_section(SECTIONED, heading)

    def test_a_deeper_heading_or_a_prose_mention_is_not_a_section(self):
        text = "### Context\n\nsee ## Context for more\n"
        assert not dm.has_section(text, "Context")

    def test_a_heading_with_trailing_text_is_not_that_section(self):
        assert not dm.has_section("## Context (draft)\nbody\n", "Context")

    def test_a_heading_on_the_last_line_with_no_newline(self):
        assert dm.has_section("## Goal\nx\n\n## Context", "Context")


class TestReplaceSectionBody:
    def test_replaces_a_middle_section_and_leaves_every_other_byte(self):
        out = dm.replace_section_body(SECTIONED, "Context", NEW_BODY)
        assert out == SECTIONED.replace(
            "## Context\n<!-- old guidance -->\n**Serves:** spec NNNN — [path]\n\n",
            "## Context\n" + NEW_BODY + "\n\n",
        )

    def test_bytes_outside_the_span_are_identical(self):
        out = dm.replace_section_body(SECTIONED, "Context", NEW_BODY)
        head_end = SECTIONED.index("## Context") + len("## Context")
        tail_start = SECTIONED.index("## Scope")
        assert out.startswith(SECTIONED[:head_end])
        assert out.endswith(SECTIONED[tail_start:])

    def test_the_new_body_reads_back_through_extract_section(self):
        out = dm.replace_section_body(SECTIONED, "Context", NEW_BODY)
        _, body = cs.parse_frontmatter(out)
        assert cs.extract_section(body, "Context").strip() == NEW_BODY.strip()

    def test_the_last_section_ends_with_one_newline_not_a_blank_line(self):
        out = dm.replace_section_body(SECTIONED, "Deliverables", "| x | y |\n|---|---|")
        assert out.endswith("## Deliverables\n| x | y |\n|---|---|\n")
        assert out.startswith(SECTIONED[: SECTIONED.index("## Deliverables")])

    def test_a_trailing_newline_or_two_in_the_body_changes_nothing(self):
        a = dm.replace_section_body(SECTIONED, "Context", NEW_BODY)
        b = dm.replace_section_body(SECTIONED, "Context", NEW_BODY + "\n\n\n")
        assert a == b

    def test_applying_the_same_body_twice_is_the_same_text(self):
        once = dm.replace_section_body(SECTIONED, "Context", NEW_BODY)
        assert dm.replace_section_body(once, "Context", NEW_BODY) == once

    def test_the_replaced_span_covers_a_whole_section_including_its_subsections(self):
        out = dm.replace_section_body(SECTIONED, "Scope", "- nothing")
        assert "### In scope" not in out
        assert "## Scope\n- nothing\n\n## Deliverables\n" in out

    def test_a_section_at_end_of_file_with_no_trailing_newline(self):
        text = "---\nspec: \"0002\"\n---\n\n## Goal\ng\n\n## Context"
        out = dm.replace_section_body(text, "Context", "body")
        assert out == "---\nspec: \"0002\"\n---\n\n## Goal\ng\n\n## Context\nbody\n"

    def test_an_empty_section_is_filled(self):
        text = "## Goal\ng\n\n## Context\n\n## Scope\ns\n"
        assert dm.replace_section_body(text, "Context", "body") == "## Goal\ng\n\n## Context\nbody\n\n## Scope\ns\n"

    def test_the_first_matching_heading_wins(self):
        text = "## Context\none\n\n## Context\ntwo\n"
        assert dm.replace_section_body(text, "Context", "x") == "## Context\nx\n\n## Context\ntwo\n"

    def test_a_deeper_heading_of_the_same_name_is_not_the_section(self):
        text = "## Goal\n### Context\nkeep\n\n## Context\nold\n"
        assert dm.replace_section_body(text, "Context", "new") == "## Goal\n### Context\nkeep\n\n## Context\nnew\n"

    def test_crlf_keeps_every_byte_outside_the_span_and_every_ending(self):
        text = crlf(SECTIONED)
        out = dm.replace_section_body(text, "Context", NEW_BODY)
        assert bare_lf(out) == 0
        head_end = text.index("## Context") + len("## Context")
        tail_start = text.index("## Scope")
        assert out.startswith(text[:head_end])
        assert out.endswith(text[tail_start:])
        assert out == crlf(dm.replace_section_body(SECTIONED, "Context", NEW_BODY))

    def test_a_crlf_body_is_not_doubled(self):
        out = dm.replace_section_body(crlf(SECTIONED), "Context", crlf(NEW_BODY))
        assert "\r\r" not in out and bare_lf(out) == 0
        assert out == crlf(dm.replace_section_body(SECTIONED, "Context", NEW_BODY))

    def test_crlf_last_section(self):
        text = crlf(SECTIONED)
        out = dm.replace_section_body(text, "Deliverables", "x")
        assert out.endswith("## Deliverables\r\nx\r\n") and bare_lf(out) == 0

    def test_a_crlf_document_with_the_heading_on_its_last_line(self):
        out = dm.replace_section_body("## Goal\r\ng\r\n\r\n## Context", "Context", "x")
        assert out == "## Goal\r\ng\r\n\r\n## Context\r\nx\r\n"

    def test_the_heading_must_exist(self):
        with pytest.raises(dm.DataSpecError) as exc:
            dm.replace_section_body(SECTIONED, "Nope", "x")
        assert exc.value.kind == "malformed"
        assert "Nope" in str(exc.value)

    def test_a_deeper_heading_alone_does_not_count(self):
        with pytest.raises(dm.DataSpecError) as exc:
            dm.replace_section_body("### Context\nx\n", "Context", "y")
        assert exc.value.kind == "malformed"

    def test_fills_the_real_data_spec_template_and_touches_nothing_else(self):
        template = DATA_TEMPLATE.read_text(encoding="utf-8")
        ctx = dm.render_context("0001", "specs/0001-x.md", ["a duplicate returns 409"], dm.cited_refs("BR-03 DL-07"), {"BR-03": "br.md", "DL-07": None}, "2026-10-15")
        out = dm.replace_section_body(template, "Context", ctx)
        assert out.startswith(template[: template.index("## Context") + len("## Context")])
        assert out.endswith(template[template.index("## Scope"):])
        assert "**Serves:** spec 0001 — `specs/0001-x.md`" in out
        assert "- DL-07 — not found in this repository" in out
        assert "## Deliverables" in out and "NNNN — [path to the parent spec]" not in out


# --- link_parent -------------------------------------------------------------------------------

class TestLinkParentDataReviewTable:
    """D4 — a tool must not silently undo a named human's verdict."""

    @pytest.mark.parametrize("before,after", [
        ("", "pending"),
        ("n-a", "pending"),
        ("returned", "pending"),
        ("pending", "pending"),
    ])
    def test_moves_to_pending_or_stays(self, before, after):
        out, info = dm.link_parent(parent_spec(data_review=before), "0009", "0007")
        assert info["data_review_before"] == before
        assert info["data_review_after"] == after
        assert info["data_review_note"] is None
        assert cs.parse_frontmatter(out)[0]["data_review"] == after

    def test_accepted_is_kept_with_a_note(self):
        text = parent_spec(data_review="accepted")
        out, info = dm.link_parent(text, "0009", "0007")
        assert info["data_review_before"] == "accepted" and info["data_review_after"] == "accepted"
        assert info["data_review_note"] == (
            "data_review was accepted by a named human and was kept; "
            "re-verdict with `sprint.py verdict --lane data` if this data work changes that"
        )
        assert cs.parse_frontmatter(out)[0]["data_review"] == "accepted"
        assert 'data_review: "accepted"          # optional' in out  # the line is not even touched

    def test_accepted_is_kept_whatever_its_case(self):
        out, info = dm.link_parent(parent_spec(data_review="Accepted"), "0009", "0007")
        assert info["data_review_after"] == "Accepted" and info["data_review_note"]
        assert cs.parse_frontmatter(out)[0]["data_review"] == "Accepted"

    def test_an_unknown_value_is_kept_and_named_in_the_note(self):
        out, info = dm.link_parent(parent_spec(data_review="in-review"), "0009", "0007")
        assert info["data_review_after"] == "in-review"
        assert "in-review" in info["data_review_note"]
        assert cs.parse_frontmatter(out)[0]["data_review"] == "in-review"

    def test_a_parent_with_no_data_review_line_gets_pending_after_status(self):
        text = parent_spec().replace('data_review: ""          # optional — pending | accepted | returned | n-a\n', "")
        assert "data_review" not in text
        out, info = dm.link_parent(text, "0009", "0007")
        assert info["data_review_before"] == "" and info["data_review_after"] == "pending"
        assert cs.parse_frontmatter(out)[0]["data_review"] == "pending"


class TestLinkParentDependsOn:
    def test_an_empty_depends_on_becomes_the_data_id(self):
        out, info = dm.link_parent(parent_spec(), "0009", "0007")
        assert info["depends_on_before"] == "" and info["depends_on_after"] == "0009"
        assert cs.parse_frontmatter(out)[0]["depends_on"] == "0009"

    def test_an_existing_dependency_is_kept_and_the_data_id_appended(self):
        out, info = dm.link_parent(parent_spec(depends_on="0007"), "0009", "0007")
        assert info["depends_on_before"] == "0007"
        assert info["depends_on_after"] == "0007,0009"
        assert cs.parse_frontmatter(out)[0]["depends_on"] == "0007,0009"
        assert sm.parse_depends_on(cs.parse_frontmatter(out)[0]["depends_on"]) == ["0007", "0009"]

    def test_a_spaced_list_is_appended_to_and_normalised(self):
        out, info = dm.link_parent(parent_spec(depends_on="0003, 0004"), "0009", "0007")
        assert info["depends_on_after"] == "0003,0004,0009"

    def test_a_depends_on_line_that_is_absent_is_inserted(self):
        text = parent_spec().replace('depends_on: ""           # optional — comma-separated spec ids, e.g. "0007,0009"\n', "")
        out, info = dm.link_parent(text, "0009", "0007")
        assert cs.parse_frontmatter(out)[0]["depends_on"] == "0009"

    def test_relinking_changes_nothing_and_the_text_is_identical(self):
        once, first = dm.link_parent(parent_spec(depends_on="0007"), "0009", "0007")
        assert first["changed"] is True
        twice, second = dm.link_parent(once, "0009", "0007")
        assert second["changed"] is False
        assert twice == once
        assert second["depends_on_before"] == second["depends_on_after"] == "0007,0009"
        assert second["data_review_before"] == second["data_review_after"] == "pending"

    def test_already_listed_and_accepted_is_unchanged_but_still_notes_the_verdict(self):
        text = parent_spec(depends_on="0009", data_review="accepted")
        out, info = dm.link_parent(text, "0009", "0007")
        assert out == text and info["changed"] is False
        assert info["data_review_note"]

    def test_an_already_listed_spaced_dependency_is_not_rewritten(self):
        text = parent_spec(depends_on="0003, 0009", data_review="pending")
        out, info = dm.link_parent(text, "0009", "0007")
        assert out == text and info["changed"] is False
        assert info["depends_on_before"] == info["depends_on_after"] == "0003, 0009"


class TestLinkParentTouchesExactlyTwoLines:
    def test_only_depends_on_and_data_review_differ_and_both_keep_their_comment(self):
        text = parent_spec()
        out, info = dm.link_parent(text, "0009", "0007")
        assert info["changed"] is True
        before, after = text.split("\n"), out.split("\n")
        assert len(before) == len(after)
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        assert len(changed) == 2
        assert [b for _, b in changed] == [
            'data_review: "pending"  # optional — pending | accepted | returned | n-a',
            'depends_on: "0009"  # optional — comma-separated spec ids, e.g. "0007,0009"',
        ]
        assert out.split("\n---\n", 1)[1] == text.split("\n---\n", 1)[1]

    def test_a_crlf_parent_stays_crlf(self):
        text = crlf(parent_spec())
        out, info = dm.link_parent(text, "0009", "0007")
        assert info["changed"] is True
        assert bare_lf(out) == 0
        assert out.count("\r\n") == text.count("\r\n")
        assert [a for a, b in zip(text.split("\r\n"), out.split("\r\n")) if a != b] == [
            'data_review: ""          # optional — pending | accepted | returned | n-a',
            'depends_on: ""           # optional — comma-separated spec ids, e.g. "0007,0009"',
        ]

    def test_a_crlf_insert_is_crlf(self):
        text = crlf(parent_spec().replace('data_review: ""          # optional — pending | accepted | returned | n-a\n', "")
                    .replace('depends_on: ""           # optional — comma-separated spec ids, e.g. "0007,0009"\n', ""))
        out, _ = dm.link_parent(text, "0009", "0007")
        assert bare_lf(out) == 0
        assert 'depends_on: "0009"\r\n' in out and 'data_review: "pending"\r\n' in out

    def test_links_a_spec_rendered_from_the_real_template(self):
        rendered = new_spec.render_spec(SPEC_TEMPLATE.read_text(encoding="utf-8"), "0001", "duplicate-claim-409", "HIGH", "—")
        out, info = dm.link_parent(rendered, "0002", "0001")
        assert info["changed"] and info["depends_on_after"] == "0002" and info["data_review_after"] == "pending"
        diff = [(a, b) for a, b in zip(rendered.split("\n"), out.split("\n")) if a != b]
        assert len(diff) == 2 and len(rendered.split("\n")) == len(out.split("\n"))
        for _, b in diff:
            assert "  # optional" in b


class TestLinkParentRefusals:
    def test_a_spec_cannot_serve_itself(self):
        with pytest.raises(dm.DataSpecError) as exc:
            dm.link_parent(parent_spec(), "0007", "0007")
        assert exc.value.kind == "self_reference"

    def test_a_data_spec_cannot_be_the_parent(self):
        data_parent = dm.mark_data(parent_spec(), "0003")
        with pytest.raises(dm.DataSpecError) as exc:
            dm.link_parent(data_parent, "0009", "0007")
        assert exc.value.kind == "parent_is_data"

    def test_a_parent_with_no_frontmatter_is_malformed(self):
        with pytest.raises(dm.DataSpecError) as exc:
            dm.link_parent("# Spec 0007\n\nno frontmatter\n", "0009", "0007")
        assert exc.value.kind == "malformed"

    def test_a_depends_on_written_as_a_yaml_list_is_malformed_not_corrupted(self):
        text = parent_spec().replace('depends_on: ""', 'depends_on: [0003, 0004]')
        with pytest.raises(dm.DataSpecError) as exc:
            dm.link_parent(text, "0009", "0007")
        assert exc.value.kind == "malformed"

    @pytest.mark.parametrize("block", [
        'depends_on:\n  - "0003"',
        "depends_on:\n  - 0003\n  - 0004",
        'depends_on:\n- "0003"',                                   # a block item need not be indented
        'depends_on:   # the dependencies\n\n  # one for now\n  - "0003"',   # blank and comment-only lines in between
    ])
    def test_a_depends_on_written_as_a_yaml_block_list_is_malformed_not_orphaned(self, block):
        with pytest.raises(dm.DataSpecError) as exc:
            dm.link_parent(parent_with_depends(block), "0009", "0007")
        assert exc.value.kind == "malformed"
        assert "YAML list" in exc.value.message and "comma-separated" in exc.value.message

    def test_the_block_list_refusal_uses_the_flow_list_wording(self):
        messages = []
        for replacement in ("depends_on: [0003]", 'depends_on:\n  - "0003"'):
            with pytest.raises(dm.DataSpecError) as exc:
                dm.link_parent(parent_with_depends(replacement), "0009", "0007")
            messages.append(exc.value.message)
        assert messages[0] == messages[1]

    def test_a_crlf_block_list_is_refused_too(self):
        with pytest.raises(dm.DataSpecError) as exc:
            dm.link_parent(crlf(parent_with_depends('depends_on:\n  - "0003"')), "0009", "0007")
        assert exc.value.kind == "malformed"

    def test_an_empty_depends_on_followed_by_another_key_is_still_a_plain_empty_value(self):
        text = parent_with_depends('depends_on:\nowner2: "@sam-k"')
        out, info = dm.link_parent(text, "0009", "0007")
        assert info["depends_on_before"] == "" and info["depends_on_after"] == "0009"
        assert 'owner2: "@sam-k"' in out

    def test_a_bullet_in_the_body_right_after_the_frontmatter_is_not_a_dependency_list(self):
        text = parent_with_depends("depends_on:").replace("---\n\n# Spec 0007", "---\n- a body bullet\n\n# Spec 0007")
        out, info = dm.link_parent(text, "0009", "0007")
        assert info["depends_on_after"] == "0009" and "- a body bullet" in out

    def test_a_quoted_empty_value_with_no_list_still_links(self):
        out, info = dm.link_parent(parent_spec(), "0009", "0007")
        assert info["depends_on_after"] == "0009" and out != parent_spec()

    def test_a_placeholder_already_in_depends_on_is_a_bad_value_not_a_crash(self):
        text = parent_spec(depends_on="TBD")
        with pytest.raises(dm.DataSpecError) as exc:
            dm.link_parent(text, "0009", "0007")
        assert exc.value.kind == "bad_value"

    @pytest.mark.parametrize("data_id,parent_id", [("9", "0007"), ("0009", ""), ("", "0007"), ("NNNN", "0007")])
    def test_ids_that_are_not_spec_ids_are_bad_values(self, data_id, parent_id):
        with pytest.raises(dm.DataSpecError) as exc:
            dm.link_parent(parent_spec(), data_id, parent_id)
        assert exc.value.kind == "bad_value"

    def test_a_refusal_returns_nothing_to_write(self):
        # the model only ever returns text; a refusal is an exception, so a caller cannot half-write
        with pytest.raises(dm.DataSpecError):
            dm.link_parent(parent_spec(), "0007", "0007")


# --- cycle_after_link --------------------------------------------------------------------------

class TestCycleAfterLink:
    def test_finds_the_cycle_the_link_would_close(self):
        # 0007 already depends on 0009; making 0009 serve... 0007 would need 0009 -> 0007 -> 0009
        cycles = dm.cycle_after_link({"0007": ["0009"], "0009": []}, "0009", "0007")
        assert cycles, "expected a cycle"
        flat = {n for c in cycles for n in c}
        assert flat == {"0007", "0009"}
        assert any(c[0] == c[-1] for c in cycles)

    def test_a_clean_link_has_no_cycle(self):
        assert dm.cycle_after_link({"0007": []}, "0007", "0009") == []

    def test_the_graph_is_not_mutated(self):
        graph = {"0007": ["0003"], "0003": []}
        dm.cycle_after_link(graph, "0007", "0009")
        assert graph == {"0007": ["0003"], "0003": []}

    def test_a_longer_cycle_through_a_third_spec(self):
        graph = {"0001": ["0002"], "0002": ["0003"], "0003": []}
        # 0003 serving... 0001: 0003 depends on 0001 -> 0001 -> 0002 -> 0003 -> 0001
        assert dm.cycle_after_link(graph, "0003", "0001")

    def test_a_parent_and_data_spec_that_are_not_yet_in_the_graph_are_added(self):
        assert dm.cycle_after_link({}, "0007", "0009") == []

    def test_an_edge_that_is_already_there_is_not_a_cycle(self):
        assert dm.cycle_after_link({"0007": ["0009"], "0009": []}, "0007", "0009") == []

    def test_a_self_link_is_a_cycle(self):
        assert dm.cycle_after_link({"0007": []}, "0007", "0007")


# --- link_closes_cycle -------------------------------------------------------------------------

class TestLinkClosesCycle:
    """The new edge is parent -> data (the parent depends on the data spec), so it closes a cycle exactly
    when the parent is already reachable from the data spec."""

    # The review finding: an unrelated 0001 <-> 0002 loop makes detect_cycles report THAT loop and
    # nothing else, so the loop 0005 -> 0006 -> 0003 -> 0002 -> 0001 -> 0005 went unseen.
    HIDDEN = {"0001": ["0002", "0005"], "0002": ["0001"], "0003": ["0002"], "0005": [], "0006": ["0003"]}

    def test_the_cycle_an_unrelated_cycle_used_to_hide_is_found(self):
        assert dm.link_closes_cycle(self.HIDDEN, "0005", "0006") == ["0006", "0003", "0002", "0001", "0005"]

    def test_cycle_after_link_alone_does_miss_it_which_is_why_the_cli_no_longer_filters_it(self):
        # pins the premise: filtering detect_cycles' answer to "cycles through both ids" yields nothing here
        through_both = [c for c in dm.cycle_after_link(self.HIDDEN, "0005", "0006") if "0005" in c and "0006" in c]
        assert through_both == []

    def test_a_direct_dependency_of_the_data_spec_on_the_parent(self):
        assert dm.link_closes_cycle({"0003": ["0001"], "0001": []}, "0001", "0003") == ["0003", "0001"]

    def test_a_longer_chain_returns_the_whole_path_in_order(self):
        graph = {"0003": ["0002"], "0002": ["0001"], "0001": []}
        assert dm.link_closes_cycle(graph, "0001", "0003") == ["0003", "0002", "0001"]

    def test_the_shortest_path_is_returned_when_there_are_two(self):
        graph = {"0009": ["0004", "0001"], "0004": ["0002"], "0002": ["0001"], "0001": []}
        assert dm.link_closes_cycle(graph, "0001", "0009") == ["0009", "0001"]

    def test_a_clean_link_closes_nothing(self):
        assert dm.link_closes_cycle({"0007": [], "0009": []}, "0007", "0009") == []

    def test_an_unrelated_cycle_alone_closes_nothing(self):
        graph = {"0001": ["0002"], "0002": ["0001"], "0003": [], "0004": []}
        assert dm.link_closes_cycle(graph, "0003", "0004") == []

    def test_a_walk_through_an_unrelated_cycle_terminates_without_the_parent(self):
        graph = {"0004": ["0001"], "0001": ["0002"], "0002": ["0001"], "0003": []}
        assert dm.link_closes_cycle(graph, "0003", "0004") == []

    def test_a_parent_that_already_depends_on_the_data_spec_closes_nothing(self):
        # the link is already written; relinking adds no edge and no cycle
        assert dm.link_closes_cycle({"0007": ["0009"], "0009": []}, "0007", "0009") == []

    def test_ids_the_graph_does_not_hold_are_nodes_with_no_dependencies(self):
        assert dm.link_closes_cycle({}, "0007", "0009") == []
        assert dm.link_closes_cycle({"0009": ["0007"]}, "0007", "0009") == ["0009", "0007"]

    def test_a_self_link_is_a_one_node_path(self):
        assert dm.link_closes_cycle({"0007": []}, "0007", "0007") == ["0007"]

    def test_the_graph_is_not_mutated(self):
        graph = {"0007": ["0003"], "0003": ["0001"], "0001": []}
        before = {k: list(v) for k, v in graph.items()}
        dm.link_closes_cycle(graph, "0001", "0007")
        assert graph == before

    def test_agrees_with_cycle_after_link_whenever_the_graph_had_no_other_cycle(self):
        for graph, parent, data in [
            ({"0007": ["0009"], "0009": []}, "0009", "0007"),
            ({"0001": ["0002"], "0002": ["0003"], "0003": []}, "0003", "0001"),
            ({"0007": []}, "0007", "0009"),
            ({"0007": ["0003"], "0003": []}, "0003", "0009"),
        ]:
            assert bool(dm.link_closes_cycle(graph, parent, data)) == bool(dm.cycle_after_link(graph, parent, data))


# --- real_table_rows ---------------------------------------------------------------------------

GAPS_HEADER = "| Gap | Impact | Severity | Decision-log ref |\n|-----|--------|----------|------------------|\n"


class TestRealTableRows:
    def test_a_header_only_table_has_no_real_rows(self):
        assert dm.real_table_rows("\n" + GAPS_HEADER) == []

    def test_template_stand_in_rows_are_not_real(self):
        section = ("\nEach gap is advisory.\n\n" + GAPS_HEADER
                   + "| [e.g. field missing for X% of records] | [what breaks] | [low / med / high] | [DL-NN] |\n"
                   + "| [...] | [...] | [...] | [...] |\n\n---\n")
        assert dm.real_table_rows(section) == []

    def test_the_real_data_readiness_template_has_none(self):
        template = (REPO_ROOT / "templates" / "phases" / "02-design" / "data" / "data-readiness.md").read_text(encoding="utf-8")
        section = cs.extract_section(cs.parse_frontmatter(template)[1], "Gaps")
        assert section is not None and "| Gap |" in section
        assert dm.real_table_rows(section) == []

    def test_real_rows_are_returned_in_document_order_stripped(self):
        section = (GAPS_HEADER + "| no phone for 4% | cannot dedupe | low | DL-04 |\n"
                   "| [...] | [...] | [...] | [...] |\n"
                   "  | stale feed | wrong totals | high | DL-05 |  \n")
        assert dm.real_table_rows(section) == ["| no phone for 4% | cannot dedupe | low | DL-04 |",
                                               "| stale feed | wrong totals | high | DL-05 |"]

    def test_an_empty_row_is_not_a_gap(self):
        assert dm.real_table_rows(GAPS_HEADER + "|  |  |  |  |\n|||\n") == []

    def test_a_row_with_exactly_half_its_cells_bracketed_is_real(self):
        # the heuristic document_shape_cli add-row uses: MORE than half, never exactly half
        assert dm.real_table_rows(GAPS_HEADER + "| BR-01 | [to confirm] | low | DL-02 |\n") == [
            "| BR-01 | [to confirm] | low | DL-02 |"]

    def test_a_markdown_link_or_an_html_tag_is_content_not_a_placeholder(self):
        row = "| see [the dump](https://x.example/d) | breaks<br>joins | high | DL-02 |"
        assert dm.real_table_rows(GAPS_HEADER + row + "\n") == [row]

    def test_alignment_colons_in_the_separator_are_still_a_separator(self):
        section = "| Gap | Impact |\n|:----|-------:|\n| a real gap | breaks |\n"
        assert dm.real_table_rows(section) == ["| a real gap | breaks |"]

    def test_every_table_in_the_section_counts_and_prose_between_them_does_not(self):
        section = ("| A | B |\n|---|---|\n| one | 1 |\n\nA sentence with a | pipe in it.\n\n"
                   "| C | D |\n|---|---|\n| [x] | [y] |\n| two | 2 |\n")
        assert dm.real_table_rows(section) == ["| one | 1 |", "| two | 2 |"]

    def test_a_row_inside_an_html_comment_is_ignored(self):
        section = GAPS_HEADER + "<!-- | commented out | gap | low | DL-09 | -->\n"
        assert dm.real_table_rows(section) == []

    def test_a_block_with_no_separator_is_not_hidden_it_is_counted(self):
        # not a header-and-rows table, but never reported as "no rows" either
        assert dm.real_table_rows("| a gap | breaks | DL-04 |\n") == ["| a gap | breaks | DL-04 |"]

    def test_crlf_text_reads_the_same(self):
        section = GAPS_HEADER + "| a real gap | breaks | low | DL-04 |\n"
        assert dm.real_table_rows(crlf(section)) == dm.real_table_rows(section)

    def test_nothing_and_no_table_are_no_rows(self):
        assert dm.real_table_rows("") == [] and dm.real_table_rows("Just prose, no table.\n") == []

    @pytest.mark.parametrize("row", [
        "| [e.g. field missing] | [what breaks] | [low / med / high] | [DL-NN] |",
        "| [...] | [...] | [...] | [...] |",
        "| DL-01 | [the open question] | [owner] | open |",
        "| BR-01 | [to confirm] |",
        "| BR-01 | [to confirm] | low | DL-02 |",
        "| a gap | <what breaks> | <severity> | DL-02 |",
        "| see [the dump](https://x.example/d) | breaks<br>joins | high | DL-02 |",
        "| a real gap | breaks | low | DL-04 |",
        "|  |  |",
        "| only | [one] |",
    ])
    def test_the_placeholder_heuristic_is_the_one_add_row_uses(self, row):
        assert dm.is_placeholder_row(row) == dsc._is_placeholder_row(row)


# --- ledger_event ------------------------------------------------------------------------------

class TestLedgerEvent:
    def test_exactly_four_keys_and_no_name(self):
        ev = dm.ledger_event("0009", "0007", "2026-10-15T09:00:00+00:00")
        assert ev == {"ts": "2026-10-15T09:00:00+00:00", "event": "data_spec_linked", "spec": "0009", "serves": "0007"}
        assert list(ev) == ["ts", "event", "spec", "serves"]
        assert dm.LINKED_EVENT == "data_spec_linked"

    def test_serialises_to_one_json_line(self):
        import json
        line = json.dumps(dm.ledger_event("0009", "0007", "t"))
        assert "\n" not in line and json.loads(line)["spec"] == "0009"


# --- status_row --------------------------------------------------------------------------------

class TestStatusRow:
    DATA_FM = {"spec": "0009", "type": "data", "serves": "0007"}

    def row(self, status, parent_fm):
        return dm.status_row(self.DATA_FM, status, parent_fm)

    def test_the_row_has_exactly_these_keys(self):
        row = self.row("draft", {"depends_on": "0009", "data_review": "pending"})
        assert list(row) == ["id", "serves", "status", "parent_found", "parent_depends_on_has_me",
                             "parent_data_review", "acceptance_due"]

    def test_a_row_carries_the_ids_and_status_as_given(self):
        row = self.row("in-flight", {"depends_on": "0003,0009", "data_review": "pending"})
        assert row["id"] == "0009" and row["serves"] == "0007" and row["status"] == "in-flight"
        assert row["parent_found"] is True and row["parent_depends_on_has_me"] is True
        assert row["parent_data_review"] == "pending"

    @pytest.mark.parametrize("status,review,due", [
        ("merged", "accepted", False),
        ("merged", "pending", True),
        ("merged", "", True),
        ("merged", "returned", True),
        ("merged", "n-a", True),
        ("merged", "Accepted", False),
        ("in-flight", "pending", False),
        ("in-flight", "accepted", False),
        ("ready", "pending", False),
        ("draft", "", False),
        ("deferred", "pending", False),
    ])
    def test_acceptance_is_due_only_after_merge_and_before_a_named_human_accepts(self, status, review, due):
        assert self.row(status, {"depends_on": "0009", "data_review": review})["acceptance_due"] is due

    def test_a_parent_missing_depends_on_does_not_list_the_data_spec(self):
        assert self.row("draft", {"depends_on": "0003", "data_review": ""})["parent_depends_on_has_me"] is False
        assert self.row("draft", {})["parent_depends_on_has_me"] is False

    def test_a_parent_that_was_not_found_claims_nothing(self):
        row = self.row("merged", None)
        assert row["parent_found"] is False
        assert row["parent_depends_on_has_me"] is None
        assert row["parent_data_review"] is None
        assert row["acceptance_due"] is False

    def test_a_parent_with_no_data_review_reads_as_empty_not_none(self):
        assert self.row("draft", {"depends_on": "0009"})["parent_data_review"] == ""

    def test_a_data_spec_with_no_serves_reads_as_empty(self):
        assert dm.status_row({"spec": "0009"}, "draft", None)["serves"] == ""


# --- context_coverage --------------------------------------------------------------------------

class TestContextCoverage:
    PARENT = (
        "---\nspec: \"0007\"\nsource: \"DL-99\"\n---\n\n"
        "## Goal\nHonour BR-03 and BR-12, per DL-07 and ADR-004, using DOC-004.\n"
    )

    def data_spec(self, context_body: str, *, with_section=True) -> str:
        section = f"## Context\n{context_body}\n\n" if with_section else ""
        return f'---\nspec: "0009"\ntype: data\nserves: "0007"\n---\n\n## Goal\ng\n\n{section}## Scope\ns\n'

    def test_reports_every_cited_ref_the_context_does_not_name(self):
        data = self.data_spec("- BR-03 — `br.md`\n- DL-07 — `dl.md`")
        assert dm.context_coverage(data, self.PARENT) == ["ADR-004", "BR-12", "DOC-004"]

    def test_a_context_that_names_everything_has_no_gaps(self):
        data = self.data_spec("BR-03 BR-12 DL-07 ADR-004 DOC-004")
        assert dm.context_coverage(data, self.PARENT) == []

    def test_a_missing_context_section_reports_everything(self):
        data = self.data_spec("", with_section=False)
        assert dm.context_coverage(data, self.PARENT) == ["ADR-004", "BR-03", "BR-12", "DL-07", "DOC-004"]

    def test_the_parent_frontmatter_is_not_a_citation(self):
        data = self.data_spec("BR-03 BR-12 DL-07 ADR-004 DOC-004")
        assert "DL-99" not in dm.context_coverage(data, self.PARENT)

    def test_a_parent_that_cites_nothing_has_nothing_to_cover(self):
        assert dm.context_coverage(self.data_spec("nothing"), parent_spec()) == []

    def test_a_ref_named_only_in_another_section_does_not_count(self):
        data = self.data_spec("BR-03").replace("## Goal\ng", "## Goal\nBR-12 DL-07 ADR-004 DOC-004")
        assert dm.context_coverage(data, self.PARENT) == ["ADR-004", "BR-12", "DL-07", "DOC-004"]

    def test_a_longer_id_is_not_the_id(self):
        data = self.data_spec("BR-035 BR-120 DL-070 ADR-0049 DOC-0045")
        assert dm.context_coverage(data, self.PARENT) == ["ADR-004", "BR-03", "BR-12", "DL-07", "DOC-004"]

    def test_guidance_in_an_html_comment_is_not_a_mention(self):
        data = self.data_spec("<!-- e.g. BR-03, DL-07, ADR-004, DOC-004 and BR-12 -->")
        assert dm.context_coverage(data, self.PARENT) == ["ADR-004", "BR-03", "BR-12", "DL-07", "DOC-004"]

    def test_reads_crlf_files(self):
        data = crlf(self.data_spec("BR-03 BR-12 DL-07 ADR-004"))
        assert dm.context_coverage(data, crlf(self.PARENT)) == ["DOC-004"]

    def test_a_rendered_context_covers_what_it_was_rendered_from(self):
        refs = dm.cited_refs(self.PARENT)
        resolved = {r: f"{r}.md" for ids in refs.values() for r in ids}
        resolved["DL-07"] = None  # an unresolved id is still *named*, and so still covered
        template = DATA_TEMPLATE.read_text(encoding="utf-8")
        ctx = dm.render_context("0007", "specs/0007-x.md", ["a duplicate returns 409"], refs, resolved, "2026-10-15")
        data = dm.replace_section_body(template, "Context", ctx)
        assert dm.context_coverage(data, self.PARENT) == []

    def test_the_unfilled_template_covers_nothing_it_is_asked_about(self):
        template = DATA_TEMPLATE.read_text(encoding="utf-8")
        assert dm.context_coverage(template, self.PARENT) == ["ADR-004", "BR-03", "BR-12", "DL-07", "DOC-004"]


# --- declared constants ------------------------------------------------------------------------

class TestDeclaredConstants:
    def test_the_headings_and_keys(self):
        assert dm.SERVES_KEY == "serves"
        assert dm.CONTEXT_HEADING == "Context" and dm.DELIVERABLES_HEADING == "Deliverables"

    def test_the_four_id_families_and_their_labels(self):
        assert list(dm.REF_PATTERNS) == ["BR", "DL", "ADR", "DOC"]
        assert dm.REF_LABELS == {"BR": "Business rules", "DL": "Decisions",
                                 "ADR": "Decision records", "DOC": "Intake documents"}

    def test_the_resolve_roots_are_searched_in_this_order(self):
        assert dm.RESOLVE_ROOTS == (".sdlc/context", ".sdlc/artifacts", ".sdlc", "docs", "specs")

    def test_context_is_searched_before_artifacts_so_a_doc_resolves_to_its_summary(self):
        # /sprd-intake --registry writes a `| DOC-NNN |` row under .sdlc/artifacts; the summary file
        # (.sdlc/context/intake/DOC-NNN-<slug>.md) must be found first
        assert dm.RESOLVE_ROOTS.index(".sdlc/context") < dm.RESOLVE_ROOTS.index(".sdlc/artifacts")

    def test_only_these_review_values_move_to_pending(self):
        assert dm.REVIEW_TO_PENDING == ("", "n-a", "returned")
        assert "accepted" not in dm.REVIEW_TO_PENDING and "pending" not in dm.REVIEW_TO_PENDING
