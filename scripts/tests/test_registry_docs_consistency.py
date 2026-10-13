"""The registry is the enforcement; the docs and phase bodies have to agree with it.

`check_gates.py` blocks a phase on `artifacts.required` in `phases/phase-registry.yaml` — nothing
else. So the registry is what a team actually experiences. Three other places describe the same
list to a human, and none of them is consulted at gate time:

* the phase definition's `### `<name>`` artifact spec — what Claude reads to know what to produce
* `docs/phase-lifecycle.md`'s **Required Artifacts** table — what a person reads to plan the phase
* the same file's **Optional Artifacts** list — which must not also name a required artifact

When those disagree, the gate wins silently and the team finds out by being blocked on a file
nobody told them to write.

Not hypothetical. The 1.0.0 "Fix 3" migration added twelve required receipts to the registry and
updated none of the prose: `docs/phase-lifecycle.md` was missing eleven of them, still listed
`go-no-go-record.md` and `drill-record.md` as *optional*, and two of the twelve
(`drill-record.md`, `go-no-go-record.md`) had no artifact spec in any phase definition at all —
required by the gate, described nowhere. Issues #31, #33 and #35 were three separate reports of
that one migration. This test is what makes the next such migration fail here instead of at a
client's Phase 9 gate.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = REPO_ROOT / "phases" / "phase-registry.yaml"
LIFECYCLE = REPO_ROOT / "docs" / "phase-lifecycle.md"


def artifact_name(entry) -> str:
    """The filename an artifact entry names, in either the plain or the qualified form.

    Entries are either a bare string or a mapping carrying `path` plus qualifiers such as
    `required_for` (project types) and `root: repo`.
    """
    return entry["path"] if isinstance(entry, dict) else entry


def phases() -> list[dict]:
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))["phases"]


def lifecycle_section(display: str) -> str:
    """The `## Phase N: ...` section of the lifecycle doc, or "" when it has none."""
    key = display.split(":")[0].strip()
    for section in re.split(r"^## ", LIFECYCLE.read_text(encoding="utf-8"), flags=re.M):
        if section.startswith(f"{key}:") or section.startswith(f"{key} "):
            return section
    return ""


def block(section: str, heading: str) -> str:
    match = re.search(rf"### {heading}(.*?)(?=\n### |\Z)", section, re.S)
    return match.group(1) if match else ""


def required_pairs() -> list[tuple[dict, str]]:
    return [(p, artifact_name(a)) for p in phases() for a in p["artifacts"]["required"]]


def test_every_required_artifact_has_a_spec_in_its_phase_definition():
    pairs = required_pairs()
    assert pairs, "no required artifacts parsed — the registry shape changed, not a clean bill"

    missing = []
    for phase, name in pairs:
        body = (REPO_ROOT / phase["definition"]).read_text(encoding="utf-8")
        if f"### `{name}`" not in body:
            missing.append(f"{phase['slug']}: {name} (add a spec to {phase['definition']})")

    assert not missing, (
        "required by the gate, described nowhere — a team hits this as a blocked phase with no "
        "instruction anywhere for what the file should contain:\n  " + "\n  ".join(missing)
    )


def test_every_required_artifact_appears_in_the_lifecycle_docs_required_table():
    missing = []
    for phase, name in required_pairs():
        section = lifecycle_section(phase["display"])
        if not section:
            continue  # the Build loop is continuous and has no numbered phase section
        if name.rstrip("/") not in block(section, "Required Artifacts"):
            missing.append(f"{phase['slug']}: {name}")

    assert not missing, (
        "required by the registry but absent from docs/phase-lifecycle.md's Required Artifacts "
        "table — the doc a person plans the phase from:\n  " + "\n  ".join(missing)
    )


def test_no_required_artifact_is_also_listed_as_optional():
    miscategorised = []
    for phase, name in required_pairs():
        section = lifecycle_section(phase["display"])
        if not section:
            continue
        if name.rstrip("/") in block(section, "Optional Artifacts"):
            miscategorised.append(f"{phase['slug']}: {name}")

    assert not miscategorised, (
        "documented as optional while the gate blocks on it — the exact contradiction that makes "
        "a team skip the artifact and then fail the gate:\n  " + "\n  ".join(miscategorised)
    )


def test_phase_reports_use_the_registry_slug_convention():
    """Report filenames are `<slug>-report.html`, never `phase9-` or `phase09-`.

    Three conventions were in use at once: the phase bodies wrote `phase09-report.html`, the
    registry's optional lists said `phase9-report.html`, and `docs/commands.md` documented
    `<slug>-report.html` — so `03-foundation.md` alone used both padded and unpadded forms.
    `commands/sprd-gate.md` pre-checks the visual report by slug, so a team following the phase
    body wrote a file the gate then failed to find.

    The slug wins because it is what `generate_phase_report.py` is invoked with and the only form
    that survives the non-numeric phases (`build`, `close`).
    """
    offenders = []
    for path in sorted(
        set(REPO_ROOT.glob("phases/*.md"))
        | set(REPO_ROOT.glob("docs/*.md"))
        | set(REPO_ROOT.glob("commands/*.md"))
        | set(REPO_ROOT.glob("references/*.md"))
        | {REGISTRY, REPO_ROOT / "SKILL.md"}
    ):
        if path.name == "CHANGELOG.md":
            continue  # a changelog records what the names used to be
        for match in re.finditer(r"\bphase\d+-(?:report|visual)\.html\b",
                                 path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(REPO_ROOT)}: {match.group(0)}")

    assert not offenders, (
        "report filenames must use the registry slug (e.g. `09-monitoring-report.html`); these "
        "will never match what the gate looks for:\n  " + "\n  ".join(offenders)
    )


def test_every_shipped_command_appears_in_the_command_reference():
    """A command nobody can find might as well not ship.

    `/sprd-spike` and `/sprd-doctor` both shipped and were absent from `docs/commands.md`
    entirely — not in the contents, the overview table, or the additional-commands table. Spikes
    are a first-class part of the method and `/sprd-doctor` is the single most useful command for
    a first-time setup, so a reader working from the reference would conclude neither existed and
    do the work by hand.
    """
    commands_doc = REPO_ROOT / "docs" / "commands.md"
    assert commands_doc.exists(), "docs/commands.md is missing — this check would pass vacuously"
    text = commands_doc.read_text(encoding="utf-8")

    shipped = sorted(p.stem for p in (REPO_ROOT / "commands").glob("*.md"))
    assert shipped, "no command files found — the glob is wrong, not a clean bill of health"

    missing = [c for c in shipped if f"/{c}" not in text]
    assert not missing, (
        "shipped but absent from docs/commands.md — add to the overview table and either a full "
        "section or the additional-commands table:\n  " + "\n  ".join(f"/{c}" for c in missing)
    )


def test_the_additional_commands_count_matches_its_table():
    """The prose count and the table drifted apart once; it reads as authoritative and was wrong."""
    text = (REPO_ROOT / "docs" / "commands.md").read_text(encoding="utf-8")
    section = re.search(r"## Additional Commands \(summaries\)(.*?)(?=\n## |\Z)", text, re.S)
    assert section, "the Additional Commands section was renamed or removed"

    words = {"Six": 6, "Seven": 7, "Eight": 8, "Nine": 9, "Ten": 10, "Eleven": 11, "Twelve": 12,
             "Thirteen": 13, "Fourteen": 14, "Fifteen": 15, "Sixteen": 16, "Seventeen": 17,
             "Eighteen": 18}
    stated = re.search(r"^(\w+) commands have their full flow", section.group(1), re.M)
    assert stated, "the count sentence was reworded — update this check or the sentence"

    rows = [l for l in section.group(1).splitlines() if l.startswith("| `/")]
    assert words.get(stated.group(1)) == len(rows), (
        f"the section says '{stated.group(1)} commands' but the table has {len(rows)} rows"
    )


def test_docs_describe_the_real_placeholder_marker_set():
    """Three docs list Gate 2's markers by hand; all three must match the code.

    `docs/templates-artifacts.md` claimed Gate 2 failed on "any remaining `[bracket text]`". It
    does not — `[INSERT` is in the set, bare brackets are not, and they deliberately cannot be
    (templates use `- [ ]` checkboxes and `[text](links)` throughout). An author trusting that
    sentence would leave `[Describe the situation]` in an ADR and expect the gate to catch it.

    Overstating what a gate checks is worse than understating it: it converts a tripwire into a
    proofreader in the reader's head, and the work stops being done.
    """
    import check_gates

    markers = set(check_gates.PLACEHOLDER_MARKERS)
    assert markers, "PLACEHOLDER_MARKERS is empty — this check would pass vacuously"

    for rel in ("docs/gate-system.md", "docs/scripts.md", "docs/templates-artifacts.md"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        missing = [m for m in markers if m not in text]
        assert not missing, f"{rel} does not mention these real markers: {missing}"

    # The specific false claim, kept as a named regression rather than a general rule.
    overstated = "`[bracket text]`, `TODO`, or `TBD` markers cause the gate to fail"
    assert overstated not in (REPO_ROOT / "docs/templates-artifacts.md").read_text(
        encoding="utf-8"
    ), "the '[bracket text] fails the gate' claim is back; bare brackets are not detected"


@pytest.mark.parametrize("path", [REGISTRY, LIFECYCLE])
def test_sources_exist(path: Path):
    """Guard the guard: a moved or renamed source must fail loudly, not pass vacuously."""
    assert path.exists(), f"{path} is missing — the checks above would silently pass without it"
