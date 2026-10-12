"""Map /deep-plan outputs to SDLC artifact locations.

Transforms artifacts from /deep-plan's planning/ directory into the SDLC
expected paths under .sdlc/artifacts/. Supports Phase 2 and Phase 3 modes.
Idempotent — safe to re-run.
"""

import argparse
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
CONVERGED_TEMPLATE = (
    PLUGIN_ROOT
    / "templates"
    / "phases"
    / "03-foundation"
    / "section-plans"
    / "SECTION-template-deep-plan.md"
)


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def read_file(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    return ""


def copy_if_exists(src: Path, dest: Path) -> bool:
    """Copy a file or directory if source exists. Returns True if copied."""
    if not src.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
    else:
        shutil.copy2(src, dest)
    return True


def extract_sections_by_heading(content: str, level: int = 2) -> dict[str, str]:
    """Extract markdown sections by heading level. Returns {heading: content}."""
    pattern = rf"^{'#' * level}\s+(.+)$"
    parts: dict[str, str] = {}
    current_heading = None
    current_lines: list[str] = []

    for line in content.split("\n"):
        match = re.match(pattern, line)
        if match:
            if current_heading is not None:
                parts[current_heading] = "\n".join(current_lines).strip()
            current_heading = match.group(1).strip()
            current_lines = []
        elif current_heading is not None:
            current_lines.append(line)

    if current_heading is not None:
        parts[current_heading] = "\n".join(current_lines).strip()

    return parts


def parse_section_manifest(index_content: str) -> list[str]:
    """Parse SECTION_MANIFEST from sections/index.md."""
    match = re.search(
        r"<!--\s*SECTION_MANIFEST\s*\n(.*?)\nEND_MANIFEST\s*-->",
        index_content,
        re.DOTALL,
    )
    if not match:
        return []
    return [line.strip() for line in match.group(1).strip().split("\n") if line.strip()]


def parse_project_config(index_content: str) -> dict[str, str]:
    """Parse PROJECT_CONFIG from sections/index.md."""
    match = re.search(
        r"<!--\s*PROJECT_CONFIG\s*\n(.*?)\nEND_PROJECT_CONFIG\s*-->",
        index_content,
        re.DOTALL,
    )
    if not match:
        return {}
    config = {}
    for line in match.group(1).strip().split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            config[key.strip()] = value.strip()
    return config


# ---------------------------------------------------------------------------
# Phase 2: Design artifact mapping
# ---------------------------------------------------------------------------


def build_design_doc_skeleton(plan_content: str) -> str:
    """Extract architecture-relevant content from claude-plan.md into design-doc.md skeleton."""
    sections = extract_sections_by_heading(plan_content, level=2)

    doc_lines = ["# Design Document", ""]
    doc_lines.append("<!-- Generated from /deep-plan's claude-plan.md. ")
    doc_lines.append("     Review and complete any sections marked with FILL. -->")
    doc_lines.append("")

    # Map common /deep-plan headings to SDLC design-doc sections
    heading_map = {
        "Architecture Overview": [
            "Architecture", "System Architecture", "High-Level Architecture",
            "Architecture Overview", "Overview",
        ],
        "Component Descriptions": [
            "Components", "Component Design", "Modules", "System Components",
            "Component Descriptions",
        ],
        "Key Data Flows": [
            "Data Flow", "Data Flows", "Key Flows", "Sequence",
            "Key Data Flows",
        ],
        "Cross-Cutting Concerns": [
            "Cross-Cutting", "Cross-Cutting Concerns", "Observability",
            "Error Handling", "Logging", "Security",
        ],
        "Technology Choices": [
            "Technology", "Tech Stack", "Technology Choices",
            "Technology Selection", "Stack",
        ],
    }

    for sdlc_heading, candidates in heading_map.items():
        doc_lines.append(f"## {sdlc_heading}")
        doc_lines.append("")
        matched = False
        for candidate in candidates:
            for plan_heading, plan_body in sections.items():
                if candidate.lower() in plan_heading.lower():
                    doc_lines.append(plan_body)
                    matched = True
                    break
            if matched:
                break
        if not matched:
            doc_lines.append(f"<!-- FILL: Extract {sdlc_heading.lower()} from the design plan -->")
        doc_lines.append("")

    # Append any plan sections not already mapped
    mapped_headings = set()
    for candidates in heading_map.values():
        for candidate in candidates:
            for plan_heading in sections:
                if candidate.lower() in plan_heading.lower():
                    mapped_headings.add(plan_heading)

    remaining = {h: b for h, b in sections.items() if h not in mapped_headings}
    if remaining:
        doc_lines.append("## Additional Design Notes")
        doc_lines.append("")
        for heading, body in remaining.items():
            doc_lines.append(f"### {heading}")
            doc_lines.append("")
            doc_lines.append(body)
            doc_lines.append("")

    return "\n".join(doc_lines)


def build_api_contracts_skeleton(plan_content: str) -> str:
    """Extract API/interface content from claude-plan.md."""
    sections = extract_sections_by_heading(plan_content, level=2)

    doc_lines = ["# API Contracts", ""]
    doc_lines.append("<!-- Generated from /deep-plan's claude-plan.md. -->")
    doc_lines.append("")

    api_keywords = [
        "api", "endpoint", "interface", "contract", "route", "rest",
        "graphql", "grpc", "request", "response",
    ]

    matched_any = False
    for heading, body in sections.items():
        if any(kw in heading.lower() for kw in api_keywords):
            doc_lines.append(f"## {heading}")
            doc_lines.append("")
            doc_lines.append(body)
            doc_lines.append("")
            matched_any = True

    if not matched_any:
        doc_lines.append("<!-- FILL: Extract API contracts from the design plan -->")
        doc_lines.append("<!-- Include: endpoints, request/response schemas, auth, error codes, versioning -->")

    return "\n".join(doc_lines)


def build_phase3_handoff_skeleton(plan_content: str) -> str:
    """Extract section boundaries from claude-plan.md for phase3-handoff.md."""
    sections = extract_sections_by_heading(plan_content, level=2)

    doc_lines = ["# Phase 3 Handoff: Design → Planning", ""]

    # Design summary
    doc_lines.append("## Design Summary")
    doc_lines.append("")
    doc_lines.append("<!-- FILL: One-paragraph summary of the architecture and key decisions -->")
    doc_lines.append("")

    # Section breakdown — try to find implementation/section headings in the plan
    doc_lines.append("## Proposed Section Breakdown")
    doc_lines.append("")
    section_keywords = [
        "section", "implementation", "phase", "milestone", "component",
        "module", "sprint", "work breakdown",
    ]

    matched_any = False
    for heading, body in sections.items():
        if any(kw in heading.lower() for kw in section_keywords):
            doc_lines.append(f"### {heading}")
            doc_lines.append("")
            doc_lines.append(body)
            doc_lines.append("")
            matched_any = True

    if not matched_any:
        doc_lines.append("<!-- FILL: List proposed implementation sections with scope and order -->")
    doc_lines.append("")

    doc_lines.append("## Implementation Order Rationale")
    doc_lines.append("")
    doc_lines.append("<!-- FILL: Why sections are ordered this way -->")
    doc_lines.append("")

    doc_lines.append("## Open Technical Questions")
    doc_lines.append("")
    doc_lines.append("<!-- FILL: Questions for the planning phase to resolve -->")

    return "\n".join(doc_lines)


def write_checkpoint(
    dest_dir: Path,
    planning_dir: Path,
    session_id: str | None = None,
) -> None:
    """Write deep-plan-checkpoint.yaml for Phase 3 resumption."""
    checkpoint = {
        "version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "planning_dir": str(planning_dir.resolve()),
        "completed_through_step": 15,
        "session_id": session_id,
        "files": {
            "spec": str(planning_dir / "spec.md"),
            "research": str(planning_dir / "claude-research.md"),
            "interview": str(planning_dir / "claude-interview.md"),
            "plan": str(planning_dir / "claude-plan.md"),
            "integration_notes": str(planning_dir / "claude-integration-notes.md"),
        },
    }
    dest = dest_dir / "deep-plan-checkpoint.yaml"
    with open(dest, "w") as f:
        yaml.dump(checkpoint, f, default_flow_style=False, sort_keys=False)
    print(f"  Checkpoint: {dest}")


def map_phase_2(planning_dir: Path, artifacts_dir: Path) -> None:
    """Map /deep-plan Phase 2 outputs to SDLC artifacts."""
    dest = artifacts_dir / "02-design"
    dest.mkdir(parents=True, exist_ok=True)

    plan_content = read_file(planning_dir / "claude-plan.md")
    if not plan_content:
        print("Warning: claude-plan.md not found — skipping design-doc transformation")
    else:
        # design-doc.md skeleton
        design_doc = build_design_doc_skeleton(plan_content)
        (dest / "design-doc.md").write_text(design_doc, encoding="utf-8")
        print(f"  design-doc.md: skeleton generated")

        # api-contracts.md skeleton
        api_doc = build_api_contracts_skeleton(plan_content)
        (dest / "api-contracts.md").write_text(api_doc, encoding="utf-8")
        print(f"  api-contracts.md: skeleton generated")

        # phase3-handoff.md skeleton
        handoff = build_phase3_handoff_skeleton(plan_content)
        (dest / "phase3-handoff.md").write_text(handoff, encoding="utf-8")
        print(f"  phase3-handoff.md: skeleton generated")

    # Copy optional artifacts
    if copy_if_exists(planning_dir / "claude-research.md", dest / "research-notes.md"):
        print(f"  research-notes.md: copied")
    if copy_if_exists(planning_dir / "claude-integration-notes.md", dest / "integration-notes.md"):
        print(f"  integration-notes.md: copied")
    if copy_if_exists(planning_dir / "reviews", dest / "external-reviews"):
        print(f"  external-reviews/: copied")

    # Write checkpoint for Phase 3 resumption
    write_checkpoint(dest, planning_dir)


# ---------------------------------------------------------------------------
# Phase 3: Planning artifact mapping
# ---------------------------------------------------------------------------


def transform_section_to_sdlc(
    section_name: str,
    section_number: int,
    section_content: str,
    tdd_content: str,
    manifest_entries: list[str],
) -> str:
    """Transform a /deep-plan section file into SDLC SECTION-NNN.md format."""
    # Extract a title from the section content (first # heading)
    title_match = re.match(r"^#\s+(.+)", section_content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else section_name.replace("-", " ").title()

    # Clean the section content — remove the first heading (we'll use our own)
    body = re.sub(r"^#\s+.+\n*", "", section_content, count=1).strip()

    # Extract dependencies from manifest context
    deps_lines = []
    for entry in manifest_entries:
        if entry != section_name:
            deps_lines.append(f"| {entry} | Interface | See implementation guidance |")

    deps_table = "\n".join(deps_lines) if deps_lines else "| (none) | — | — |"

    # Try to extract TDD stubs for this section
    section_tdd = ""
    if tdd_content:
        tdd_sections = extract_sections_by_heading(tdd_content, level=2)
        for heading, tdd_body in tdd_sections.items():
            if section_name.replace("-", " ") in heading.lower() or \
               f"section {section_number:02d}" in heading.lower() or \
               f"section-{section_number:02d}" in heading.lower():
                section_tdd = tdd_body
                break

    n = f"{section_number:03d}"
    doc = f"""# Section {section_number}: {title}

**Owner:** [Assign at /sprd-sprint commit]
**Sprint(s):** [Assign at /sprd-sprint commit]
**Estimated effort:** [S / M / L / XL]
**Status:** Not Started

---

## Goal

{title}

## Epics / Stories Covered

| Epic/Story ID | Title | P-Level |
|--------------|-------|---------|
| [Map from requirements] | {title} | [P0-P3] |

## Entry Criteria

- [ ] Previous dependent sections completed (see Dependencies)

## Exit Criteria

- [ ] All unit tests passing for components in this section
- [ ] Code reviewed and approved
- [ ] Implementation matches design intent

## Dependencies

| Depends On | Type | Notes |
|-----------|------|-------|
{deps_table}

## Implementation Guidance

{body}

## Interfaces

| Interface | Type | Contract |
|-----------|------|---------|
| [Extract from implementation guidance] | [Internal / External] | [Contract] |

## Test Strategy

| Test Type | What to Test | Coverage Target |
|-----------|-------------|----------------|
| Unit | Core logic in this section | 80%+ |
| Integration | Interfaces with dependent sections | All happy + error paths |

### TDD Test Stubs

{section_tdd if section_tdd else "[Extract from claude-plan-tdd.md for this section]"}

## Risk

| Risk | Mitigation |
|------|-----------|
| [Section-specific risk] | [Mitigation strategy] |
"""
    return doc


def map_phase_3(planning_dir: Path, artifacts_dir: Path) -> None:
    """Map /deep-plan Phase 3 outputs to SDLC artifacts (Foundation)."""
    dest = artifacts_dir / "03-foundation"
    section_plans_dir = dest / "section-plans"
    section_plans_dir.mkdir(parents=True, exist_ok=True)

    sections_dir = planning_dir / "sections"
    index_content = read_file(sections_dir / "index.md")
    manifest = parse_section_manifest(index_content)

    if not manifest:
        print("Warning: No SECTION_MANIFEST found in sections/index.md")
        print("  Looking for section files directly...")
        section_files = sorted(sections_dir.glob("section-*.md")) if sections_dir.exists() else []
        manifest = [f.stem for f in section_files if f.name != "index.md"]

    tdd_content = read_file(planning_dir / "claude-plan-tdd.md")

    section_count = 0
    for i, section_name in enumerate(manifest, start=1):
        # Find the corresponding /deep-plan section file
        section_file = sections_dir / f"{section_name}.md"
        if not section_file.exists():
            print(f"  Warning: {section_file.name} not found, skipping")
            continue

        section_content = section_file.read_text(encoding="utf-8", errors="replace")
        sdlc_section = transform_section_to_sdlc(
            section_name, i, section_content, tdd_content, manifest,
        )

        output_file = section_plans_dir / f"SECTION-{i:03d}.md"
        output_file.write_text(sdlc_section, encoding="utf-8")
        section_count += 1

    print(f"  section-plans/: {section_count} SECTION files created")

    # Copy TDD plan
    if copy_if_exists(planning_dir / "claude-plan-tdd.md", dest / "tdd-plan.md"):
        print(f"  tdd-plan.md: copied")

    # Copy dependency info from index
    if index_content:
        (dest / "dependency-map.md").write_text(index_content, encoding="utf-8")
        print(f"  dependency-map.md: copied from sections/index.md")


def main():
    parser = argparse.ArgumentParser(
        description="Map /deep-plan outputs to SDLC artifact locations"
    )
    parser.add_argument(
        "--state", required=True, help="Path to .sdlc/state.yaml"
    )
    parser.add_argument(
        "--phase", required=True, type=int, choices=[2, 3],
        help="SDLC phase to map artifacts for (2=Design, 3=Foundation)",
    )
    parser.add_argument(
        "--planning-dir", required=True,
        help="Path to /deep-plan's planning/ directory",
    )
    args = parser.parse_args()

    state_path = Path(args.state)
    if not state_path.exists():
        print(f"Error: State file not found: {state_path}")
        sys.exit(1)

    sdlc_dir = state_path.parent
    artifacts_base = sdlc_dir / "artifacts"
    planning_dir = Path(args.planning_dir)

    if not planning_dir.exists():
        print(f"Error: Planning directory not found: {planning_dir}")
        sys.exit(1)

    print(f"Mapping /deep-plan artifacts → Phase {args.phase}")

    if args.phase == 2:
        map_phase_2(planning_dir, artifacts_base)
    else:
        map_phase_3(planning_dir, artifacts_base)

    print("Done.")


if __name__ == "__main__":
    main()
