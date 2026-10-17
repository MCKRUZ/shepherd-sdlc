"""Spec 0039, DS-P0 — the data-spec template is a spec first.

`templates/phases/build/data-spec.md` must satisfy the same Definition of Ready `check_spec.py`
holds every spec to (the protected check is imported, never copied), render through
`new_spec.render_spec` with no rendering code of its own, and seed acceptance checks that pass the
vague-line lint — a template that ships a wish ("the data is clean") would teach every data spec
to fail the DoR. Spec 0039 itself must be READY.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import check_spec as cs  # noqa: E402
import new_spec  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "templates" / "phases" / "build" / "data-spec.md"
SPEC_0039 = REPO_ROOT / "specs" / "0039-data-specs.md"
H2 = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)


def _text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _headings(text: str) -> list[str]:
    return H2.findall(text)


def _fill(text: str, heading: str, body: str) -> str:
    """Replace a `## heading` section's body (up to the next `## `), keeping everything else."""
    m = re.search(rf"^## {re.escape(heading)}\s*$", text, flags=re.MULTILINE)
    assert m, f"template has no section {heading}"
    nxt = re.compile(r"^## ", re.MULTILINE).search(text, m.end())
    end = nxt.start() if nxt else len(text)
    return text[: m.end()] + "\n" + body.rstrip("\n") + "\n\n" + text[end:]


class TestTemplateShape:
    def test_has_every_required_section_plus_context_and_deliverables(self):
        headings = _headings(_text())
        for required in cs.REQUIRED_SECTIONS:
            assert required in headings, f"missing required section {required}"
        assert "Context" in headings
        assert "Deliverables" in headings

    def test_context_comes_before_scope(self):
        headings = _headings(_text())
        assert headings.index("Context") < headings.index("Scope")

    def test_marker_is_type_data_with_serves_after_it(self):
        fm_block = _text().split("\n---", 2)[0]
        lines = [ln for ln in fm_block.splitlines()]
        type_idx = next(i for i, ln in enumerate(lines) if ln.startswith("type: data"))
        serves_idx = next(i for i, ln in enumerate(lines) if ln.startswith('serves: "NNNN"'))
        assert serves_idx == type_idx + 1
        assert not any(ln.startswith("kind:") for ln in lines), "the marker is `type`, never `kind`"

    def test_keeps_every_placeholder_literal_render_spec_replaces(self):
        text = _text()
        for literal in ('spec: "NNNN"', 'name: "short-kebab-name"', 'source: "—"', 'created: "YYYY-MM-DD"',
                        "# Spec NNNN — <title>", "**Tier:** MEDIUM", "**Ladder depth:** MEDIUM"):
            assert literal in text, f"render_spec relies on {literal!r}"
        assert re.search(r"^risk: MEDIUM", text, flags=re.MULTILINE)
        assert re.search(r'^owner: ""(?:\s*#.*)?$', text, flags=re.MULTILINE)
        assert re.search(r'^team: ""(?:\s*#.*)?$', text, flags=re.MULTILINE)


class TestSeededAcceptanceChecks:
    def test_six_checks_each_concrete_and_not_vague(self):
        _, body = cs.parse_frontmatter(_text())
        checks = cs.list_items(cs.extract_section(body, "Acceptance Checks"))
        assert len(checks) == 6
        for c in checks:
            assert cs.CONCRETE_RE.search(c), f"no concrete signal: {c}"
            assert not cs.VAGUE_RE.search(c), f"vague word in: {c}"

    def test_rendered_and_filled_template_clears_the_dor_with_no_vague_line(self):
        rendered = new_spec.render_spec(_text(), "0002", "claims-profile", "MEDIUM", "—",
                                        owner="@sam-k", team="core")
        rendered = rendered.replace('serves: "NNNN"', 'serves: "0001"')
        rendered = re.sub(r'^harness_context: ""', 'harness_context: "the daily_claims view"',
                          rendered, count=1, flags=re.MULTILINE)
        filled = _fill(rendered, "Goal", "A `claim_history` view exists for spec 0001.")
        filled = _fill(filled, "Why", "Spec 0001 reads history nobody has profiled.")
        filled = _fill(filled, "Context", "**Serves:** spec 0001 — `specs/0001-x.md`\n\n**Business rules:**\n- none")
        filled = _fill(filled, "Scope", "### In scope\n- the view\n\n### Out of scope\n- the endpoint")
        filled = _fill(filled, "Risk Tier", "**Tier:** MEDIUM\n**Why this tier:** new logic over an established source.")
        filled = _fill(filled, "Delegation Plan",
                       "- **Scope (file patterns):** `gold/claims/**`\n- **Context (pattern to reuse):** the daily_claims view\n"
                       "- **Permissions:** reads auto-allowed\n- **Gated paths touched:** none")
        filled = _fill(filled, "Checking Plan", "**Ladder depth:** MEDIUM\n**Specifics:** grader and a non-author Checker.")
        findings = cs.check_spec_text(filled)
        failing_must = [f for f in findings if f["severity"] == "MUST" and not f["passed"]]
        assert failing_must == [], failing_must
        vague = [f for f in findings if f["check"] == "vague-line"]
        assert vague == [], vague


class TestSpec0039:
    def test_is_ready(self):
        proc = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "check_spec.py"), "--spec", str(SPEC_0039)],
                              capture_output=True, text=True, encoding="utf-8", cwd=str(REPO_ROOT),
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert proc.stdout.strip().splitlines()[-1] == "READY — this spec clears the Definition of Ready."
