"""Every agent this plugin names must be an agent that exists.

Spawning an agent that does not exist is the worst kind of failure this repo can ship: it does
not raise, it does not warn, and the phase carries on as though the work were done. A team runs
Phase 7, the definition says the API documentation is being generated, and `api-docs.md` simply
never appears.

Not hypothetical. Phases 7, 8 and 9 spawned seven agents by name and **six did not exist**
(`doc-updater`, `backend-architect`, `devops-automator`, `e2e-runner`, `performance-benchmarker`,
`feedback-synthesizer`). `references/agent-roster.md` and `docs/agents.md` documented **thirteen**
that did not exist, six of them in the Build-loop table — the most-exercised part of the product —
and `docs/agents.md` asserted they were "Built-in Claude Code subagents" supplied by the runtime.
They never were. That false belief is the likeliest reason nobody built them.

What may be named:

* `agents/*.md` — the SDLC agents that ship in this plugin
* `harness/agents/*.md` — installed into the client repo by `/sprd-harness`
* a small allowlist of Claude Code built-ins and sibling-plugin agents, listed explicitly below so
  that adding to it is a deliberate act rather than a typo that silently passes
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Claude Code built-ins and agents supplied by the sibling plugins this one already depends on.
# Deliberately explicit: an agent that is not shipped here and not on this list does not exist.
EXTERNAL_AGENTS = {
    "Explore",
    "Plan",
    "general-purpose",
    "deep-plan:section-writer",
    "deep-plan:opus-plan-reviewer",
    "deep-implement:code-reviewer",
    "opus-plan-reviewer",
    "web-search-researcher",
}

# Files that are allowed to name a non-existent agent, because naming it is the point.
HISTORICAL = {"CHANGELOG.md"}


def shipped_agents() -> set[str]:
    plugin = {p.stem for p in (REPO_ROOT / "agents").glob("*.md")}
    harness = {
        p.stem for p in (REPO_ROOT / "harness" / "agents").glob("*.md") if p.stem != "README"
    }
    return plugin | harness


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def agent_names_in(text: str) -> set[str]:
    """Backticked names sitting in an agent position: an agent table column, or a spawn.

    Naive "any backticked token in any table cell" produces nonsense — `build` and `close` are
    phase slugs, `draft` is a spec status. Only columns whose *header* names agents are read.
    """
    names: set[str] = set()

    for m in re.finditer(r"Agent\(\s*([A-Za-z][\w:-]*)", text):
        names.add(m.group(1))

    lines = text.splitlines()
    agent_columns: list[int] = []
    for i, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            agent_columns = []
            continue
        # A header row is the one followed by the |---|---| separator.
        if i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            agent_columns = [
                idx for idx, head in enumerate(_cells(line)) if "agent" in head.lower()
            ]
            continue
        if not agent_columns:
            continue
        cells = _cells(line)
        for idx in agent_columns:
            if idx < len(cells):
                names.update(re.findall(r"`([A-Za-z][\w:-]*)`", cells[idx]))

    return names


def test_agents_actually_ship():
    """Guard the guard — an empty roster would make every check below pass vacuously."""
    agents = shipped_agents()
    assert len(agents) >= 15, f"only found {len(agents)} agents; the globs are wrong"
    assert "build-error-resolver" in agents and "section-evaluator" in agents


def test_every_spawned_agent_exists():
    """`Agent(<name>, ...)` in a phase definition must resolve to something."""
    available = shipped_agents() | EXTERNAL_AGENTS
    unresolved = []

    for path in sorted((REPO_ROOT / "phases").glob("*.md")):
        for m in re.finditer(r"Agent\(\s*([A-Za-z][\w:-]*)", path.read_text(encoding="utf-8")):
            if m.group(1) not in available:
                unresolved.append(f"{path.name}: Agent({m.group(1)})")

    assert not unresolved, (
        "these spawns resolve to nothing — they fail silently and the phase reports the work as "
        "done:\n  " + "\n  ".join(unresolved)
    )


def documentation_files() -> list[str]:
    """Every doc that presents agents as usable.

    `harness/agents/README.md` is deliberately excluded: it is a catalogue of *external* agents a
    team may choose to pull from third-party marketplaces, and naming them is the point. Nothing
    in this repo spawns them.
    """
    rels = ["SKILL.md"]
    rels += sorted(f"docs/{p.name}" for p in (REPO_ROOT / "docs").glob("*.md"))
    rels += sorted(f"references/{p.name}" for p in (REPO_ROOT / "references").glob("*.md"))
    return [r for r in rels if Path(r).name not in HISTORICAL]


@pytest.mark.parametrize("rel", documentation_files())
def test_reference_docs_only_name_agents_that_exist(rel: str):
    """The roster calls itself authoritative; two-thirds of it was once fiction.

    Scoped to every doc rather than a hand-listed pair, because the first pass at this fix
    corrected `references/agent-roster.md` and `docs/agents.md` and left the same claims standing
    in `SKILL.md` — the file Claude actually reads — plus `docs/integrations.md` and
    `references/skill-mapping.md`. A hand-maintained list of files to check drifts exactly the
    way the thing it is checking drifted.
    """
    available = shipped_agents() | EXTERNAL_AGENTS
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")

    phantom = {n for n in agent_names_in(text) if n not in available}

    # The corrective note in docs/agents.md names the old phantoms deliberately, but in prose —
    # only agent-table columns and spawns are inspected, so the note is not flagged.
    assert not phantom, (
        f"{rel} presents these as usable agents, and they do not exist:\n  "
        + "\n  ".join(sorted(phantom))
        + "\n\nEither build them, or describe the work as a step in the phase definition."
    )
