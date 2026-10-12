"""The shipped spec templates must satisfy the gate that judges the specs made from them.

Issue #17: the installer laid down a human-prose template with no YAML frontmatter and three of
the seven required sections missing, so the first thing a new pod did — copy the template, fill
it in — produced a spec `check_spec.py` refused. The tool the method hands you failed the
method's own entry test.

The distinction these tests encode is the one that matters:

  * Blocking on UNFILLED CONTENT is correct. A blank template has no acceptance checks and no
    spec name, and it should say so.
  * Blocking on STRUCTURE is the bug. No amount of filling in adds frontmatter or a missing
    `## Risk Tier` heading — the author has to rebuild the document, which is exactly what
    nobody realises until the gate rejects them.

So these assert the structure, and then prove end-to-end that a filled-in template reaches READY.
"""

import re
from pathlib import Path

import pytest

import check_spec

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent

# Both templates a pod can start from: the one the installer copies into `specs/`, and the one
# `/sprd-spec` scaffolds from. They are separate files for separate install paths, so nothing
# stops them drifting apart — which is how #17 happened. These tests are that "nothing".
SHIPPED_TEMPLATES = [
    PLUGIN_ROOT / "harness" / "spec-template.md",
    PLUGIN_ROOT / "templates" / "phases" / "build" / "spec.md",
]


@pytest.fixture(params=SHIPPED_TEMPLATES, ids=lambda p: p.name)
def template(request):
    path = request.param
    assert path.exists(), f"shipped template missing: {path}"
    return path.read_text(encoding="utf-8")


class TestShippedTemplateStructure:
    def test_has_parseable_frontmatter(self, template):
        fm, _ = check_spec.parse_frontmatter(template)
        assert fm, "no YAML frontmatter — a spec built from this can never pass the gate"

    def test_frontmatter_carries_the_keys_the_gate_reads(self, template):
        fm, _ = check_spec.parse_frontmatter(template)
        for key in ("spec", "name", "risk", "harness_context"):
            assert key in fm, f"frontmatter is missing `{key}`, which check_spec.py reads"

    def test_has_every_required_section(self, template):
        _, body = check_spec.parse_frontmatter(template)
        missing = [h for h in check_spec.REQUIRED_SECTIONS if not check_spec.extract_section(body, h)]
        assert not missing, f"missing section(s) filling-in cannot add: {missing}"

    def test_scope_has_both_subsections(self, template):
        _, body = check_spec.parse_frontmatter(template)
        scope = check_spec.extract_section(body, "Scope")
        assert re.search(r"###\s+In scope", scope), "Scope needs an `### In scope` subsection"
        assert re.search(r"###\s+Out of scope", scope), "Scope needs an `### Out of scope` subsection"

    def test_checking_plan_declares_a_ladder_depth(self, template):
        """The gate reads `**Ladder depth:**` literally; prose about the ladder does not count."""
        _, body = check_spec.parse_frontmatter(template)
        plan = check_spec.extract_section(body, "Checking Plan")
        assert re.search(r"\*\*Ladder depth:\*\*\s*[A-Za-z]+", plan)

    def test_blocks_only_on_unfilled_content(self, template):
        """A blank template SHOULD block — but only for reasons a pod can fix by typing.

        Structural failures mean the document itself is wrong, which is the #17 defect.
        """
        # Only these three survive any amount of typing: absent frontmatter, an absent required
        # heading, and an absent `**Ladder depth:**` line. An EMPTY `### In scope` is not here —
        # the heading exists and the author fills it, which is the gate working as intended.
        structural = {"frontmatter", "sections", "checking-plan"}
        blocked = {
            r["check"] for r in check_spec.check_spec_text(template)
            if r["severity"] == "MUST" and not r["passed"]
        }
        assert not (blocked & structural), (
            f"template blocks for structural reasons {sorted(blocked & structural)} — "
            f"filling it in cannot fix these"
        )


def _fill(text: str) -> str:
    """Fill a template the way a pod would: real values in every placeholder slot."""
    text = re.sub(r"^spec:.*$", 'spec: "0001"', text, count=1, flags=re.MULTILINE)
    text = re.sub(r"^name:.*$", 'name: "carrier-idempotency"', text, count=1, flags=re.MULTILINE)
    text = re.sub(r"^harness_context:.*$", 'harness_context: "ClaimsController"', text,
                  count=1, flags=re.MULTILINE)
    text = re.sub(r'^owner:.*$', 'owner: "@priya-n"', text, count=1, flags=re.MULTILINE)
    text = re.sub(r"^risk:.*$", "risk: MEDIUM", text, count=1, flags=re.MULTILINE)
    text = text.replace("# Spec NNNN — <title>", "# Spec 0001 — carrier idempotency")
    text = re.sub(r"\bNNNN\b", "0001", text)
    text = text.replace("short-kebab-name", "carrier-idempotency")

    # Content the author supplies: scope bullets and one real acceptance check.
    text = re.sub(r"(###\s+In scope\n(?:<!--.*?-->\n)?)-\s*$",
                  r"\1- src/Claims/**", text, count=1, flags=re.MULTILINE | re.DOTALL)
    text = re.sub(r"(###\s+Out of scope\n(?:<!--.*?-->\n)?)-\s*$",
                  r"\1- src/Auth/**", text, count=1, flags=re.MULTILINE | re.DOTALL)
    text = re.sub(r"^-\s*\[\s*\]\s*$",
                  '- [ ] a duplicate submission returns 409 with body { "error": "duplicate claim" }',
                  text, count=1, flags=re.MULTILINE)

    # `<what the agent may touch>` style prompts are slots the author types over, so a faithful
    # fill replaces them too. Left in place they read as unfilled placeholders — correctly.
    text = re.sub(r"<[a-z][^<>\n]{3,}>", "the claims submission path", text)
    return text


class TestFilledTemplateIsReady:
    def test_a_filled_template_passes_the_gate(self, template):
        """End-to-end: copy the shipped template, fill it in, and the spec is READY.

        This is the exact sequence from #17's repro, and the one a pod runs on day one.
        """
        blocking = [
            r for r in check_spec.check_spec_text(_fill(template))
            if r["severity"] == "MUST" and not r["passed"]
        ]
        assert not blocking, "filled-in template still blocks: " + "; ".join(
            f'{r["check"]}: {r["message"]}' for r in blocking
        )
