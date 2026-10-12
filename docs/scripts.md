# Scripts Reference

Detailed documentation for all Python automation scripts in the `scripts/` directory.

---

## Table of Contents

- [1. Script System Overview](#1-script-system-overview)
- [2. uv Runtime](#2-uv-runtime)
- [3. Script Reference](#3-script-reference)
  - [validate_profile.py](#validate_profilepy)
  - [init_project.py](#init_projectpy)
  - [check_gates.py](#check_gatespy)
  - [advance_phase.py](#advance_phasepy)
  - [generate_phase_report.py](#generate_phase_reportpy)
  - [generate_status.py](#generate_statuspy)
  - [audit_gates.py](#audit_gatespy)
  - [synthesize_spec.py](#synthesize_specpy)
  - [map_deep_plan_artifacts.py](#map_deep_plan_artifactspy)
  - [risk_model.py](#risk_modelpy)
  - [new_spec.py](#new_specpy)
  - [check_spec.py](#check_specpy)
  - [track_specs.py](#track_specspy)
  - [scorecard.py](#scorecardpy)
  - [generate_handoff_report.py](#generate_handoff_reportpy)
  - [sprint.py](#sprintpy)
  - [generate_sprint_report.py](#generate_sprint_reportpy)
  - [retro_report.py](#retro_reportpy)
  - [doctor.py](#doctorpy)
  - [code_host.py](#code_hostpy)
  - [ado_import.py](#ado_importpy)
  - [import_outcomes.py](#import_outcomespy)
- [4. Dependencies](#4-dependencies)
- [5. Error Handling](#5-error-handling)
- [6. Cross-References](#6-cross-references)

---

## 1. Script System Overview

All scripts in this project share a common design philosophy:

- **Python 3.12+** required (uses `Path | None` union syntax, modern type hints)
- **Run via uv** -- the universal Python package manager acts as the runtime
- **Stateless execution** -- each script reads input files, processes them, and writes output; no persistent in-memory state between invocations
- **Exit codes** -- `0` = success, `1` = failure (with structured error details on stderr), `2` = configuration/usage error (some scripts)
- **Plugin-root aware** -- scripts resolve the plugin root via `Path(__file__).resolve().parent.parent`, enabling them to locate schemas, templates, and phase definitions regardless of the caller's working directory
- **YAML-centric** -- `state.yaml`, `profile.yaml`, and `phase-registry.yaml` are the core data files; all scripts use PyYAML for reading and writing

Commands invoke scripts using:

```bash
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/<script>.py [args]
```

---

## 2. uv Runtime

### What uv Is

[uv](https://github.com/astral-sh/uv) is a fast Python package manager and project tool written in Rust. It replaces pip, pip-tools, virtualenv, and pyenv in a single binary. The SDLC plugin uses uv because:

- It resolves and installs dependencies 10-100x faster than pip
- It creates isolated virtual environments automatically per project
- It ensures reproducible script execution across machines
- Commands can invoke scripts without manually activating a virtualenv

### Installation

```bash
# Using pip (any platform)
pip install uv

# macOS via Homebrew
brew install uv

# Windows via winget
winget install astral-sh.uv

# Standalone installer (Linux/macOS)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Syncing Dependencies

Before first use (or after updating `pyproject.toml`):

```bash
cd ${CLAUDE_PLUGIN_ROOT}/scripts
uv sync
```

This creates a `.venv/` inside `scripts/` and installs all dependencies declared in `pyproject.toml`.

### How Commands Invoke Scripts

Slash commands (e.g., `/sprd-gate`, `/sprd-next`) invoke scripts with the `--project` flag pointing to the scripts directory. This tells uv which `pyproject.toml` governs the environment:

```bash
uv run --project /path/to/shepherd/scripts /path/to/shepherd/scripts/check_gates.py --state .sdlc/state.yaml --phase 0
```

The `--project` flag is critical -- without it, uv would look for a `pyproject.toml` in the caller's working directory instead of the plugin's scripts directory.

---

## 3. Script Reference

---

### validate_profile.py

**Purpose:** Validate a company profile YAML file against the canonical schema (`profiles/_schema.yaml`). This is the first script run during project initialization and acts as a gatekeeper ensuring profile correctness before any SDLC state is created.

**CLI:**

```bash
uv run scripts/validate_profile.py <profile.yaml>
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `<profile.yaml>` | Yes | Path to the profile YAML file to validate (positional) |

**Input:** A single profile YAML file path. The schema is loaded automatically from `profiles/_schema.yaml` relative to the plugin root.

**Validation Process:**

1. **Load schema** from `profiles/_schema.yaml` (resolved via `SCHEMA_PATH = Path(__file__).resolve().parent.parent / "profiles" / "_schema.yaml"`)
2. **Load profile** YAML from the provided path
3. **Run validation checks** in sequence:

| Check | What It Validates |
|-------|-------------------|
| Required fields | Top-level fields declared in schema `required` array |
| `version` | Must be a string |
| `company.name` | Required string |
| `company.profile_id` | Required string |
| `stack.backend_language` | Required; enum validation against allowed languages |
| `stack.backend_framework` | Required string |
| `stack.frontend_framework` | Optional; enum if present |
| `stack.cloud_provider` | Required; enum (`azure`, `aws`, `gcp`, `on-prem`, `hybrid`) |
| `stack.ci_cd` | Required string |
| `quality.coverage_minimum` | Numeric range 0-100 |
| `quality.max_file_lines` | Numeric, minimum 1 |
| `quality.max_function_lines` | Numeric, minimum 1 |
| `compliance.frameworks` | List; each item validated against enum (`soc2`, `hipaa`, `gdpr`, `pci-dss`, `iso27001`, `fedramp`, `none`) |
| `compliance.change_approval` | Enum (`peer-review`, `manager-approval`, `change-board`, `none`) |
| `conventions` | Type-checked as dict if present |

**Helper Functions:**

- `load_yaml(path)` -- Safe YAML loading via `yaml.safe_load`
- `validate_required(data, required, context)` -- Checks required field presence, returns error list with field paths
- `validate_type(value, expected_type, context)` -- Type checking (`string`, `int`, `float`, `list`, `dict`)
- `validate_enum(value, allowed, context)` -- Enum membership validation
- `validate_range(value, minimum, maximum, context)` -- Numeric range validation

**Output on success:**

```
PASS -- microsoft-enterprise.yaml is valid
```

**Output on failure:**

```
FAIL -- 3 validation error(s):
  x company: missing required field 'profile_id'
  x stack.cloud_provider: 'digital-ocean' not in allowed values: azure, aws, gcp, on-prem, hybrid
  x quality.coverage_minimum: 150 > maximum 100
```

**Exit codes:** `0` (valid), `1` (invalid or file not found)

---

### init_project.py

**Purpose:** Initialize the `.sdlc/` directory structure in a target project. This is the bootstrapping script that creates the entire SDLC workspace, including artifact directories for all 9 phases, the initial state file, and a frozen copy of the selected profile.

**CLI:**

```bash
uv run scripts/init_project.py --profile <profile.yaml> --target <project-dir> [--name <project-name>]
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--profile` | Yes | Path to the company profile YAML |
| `--target` | Yes | Path to the target project directory |
| `--name` | No | Project name (defaults to target directory name) |

**Process:**

1. **Load and validate profile** -- Reads the profile YAML (does not re-run full schema validation; assumes prior `validate_profile.py` pass)
2. **Check for existing `.sdlc/`** -- If `.sdlc/` already exists, prints a warning and exits without modifying anything (safe re-run behavior)
3. **Create directory structure** -- one **empty** artifact directory per phase (slugs from the registry), plus the context directories:
   ```
   .sdlc/
     artifacts/
       00-discovery/       (empty -- artifacts are authored later, not seeded)
       01-requirements/
       02-design/
       03-foundation/
       build/
       07-documentation/
       08-deployment/
       09-monitoring/
       close/
     context/
       layers/             (frozen per-phase layers)
       intake/             (document-intake summaries; opt-in via profile.documentation)
     state.yaml
     profile.yaml
     constitution.md       (only if templates/constitution.md exists)
   ```
4. **Generate `state.yaml`** from `templates/state-init.yaml` with variable substitution:
   - `${PROFILE_ID}` -- replaced with `profile.company.profile_id`
   - `${PROJECT_NAME}` -- replaced with `--name` argument or target directory name
   - `${CREATED_AT}` -- replaced with current UTC timestamp in ISO 8601 format
5. **Copy frozen profile** -- Writes the profile to `.sdlc/profile.yaml` (via `yaml.dump`, `sort_keys=False`) so the project retains its configuration even if the source profile changes
6. **Copy the constitution template** -- Copies `templates/constitution.md` to `.sdlc/constitution.md` if it exists

> **Note:** `init_project.py` does **not** seed phase-artifact templates. The artifact directories are created empty; the files under `templates/phases/<slug>/` are references the phase docs and agents author artifacts from — auto-seeding placeholder files would fail the completeness gate (G2) on every fresh project. The exceptions written at init are `constitution.md` and `state.yaml`.

**Key Constants:**

- `PLUGIN_ROOT` -- Resolved plugin directory (`Path(__file__).resolve().parent.parent`)
- `TEMPLATES_DIR` -- `templates/` under the plugin root (`${CLAUDE_PLUGIN_ROOT}`)
- `PHASE_DIRS` -- Ordered list of 9 phase directory names (the phase slugs from `phase-registry.yaml`; not derived by zero-padding ints -- `build` and `close` are non-numeric)

**Output on success:**

```
Created .sdlc/ in /path/to/project
  Profile: microsoft-enterprise
  Artifacts: 9 phase directories
  Context: frozen layers + intake directories
  State: Phase 0 (Discovery) active
```

If `.sdlc/` already exists, the script prints `Warning: <path>/.sdlc already exists. Skipping creation.` and exits `0` without modifying anything.

**Exit codes:** `0` (success), `1` (profile not found or load error)

---

### check_gates.py

**Purpose:** Run the 7-gate validation system against a specific SDLC phase. This is the most complex script (~11KB) and serves as the quality enforcement engine. It reads the phase registry to determine which artifacts are required, then runs each gate check against the artifacts directory.

**CLI:**

```bash
uv run scripts/check_gates.py --state <state.yaml> --phase <N>
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--state` | Yes | Path to `.sdlc/state.yaml` |
| `--phase` | Yes | Phase id (`0`, `1`, `2`, `3`, `build`, `7`, `8`, `9`, `close` -- may be a string) to check |

**Key Functions:**

- `get_phase_registry()` -- Loads `phases/phase-registry.yaml` from the plugin root
- `get_compliance_gates(profile)` -- Loads framework-specific gates from `profiles/<profile_id>/compliance/<framework>-gates.yaml`
- `check_artifact_exists(artifacts_dir, artifact)` -- Gate 1: Verifies file/directory existence and non-emptiness
- `check_artifact_not_empty(artifacts_dir, artifact)` -- Gate 1: Ensures files have content (>0 bytes)
- `check_artifact_complete(artifacts_dir, artifact)` -- Gate 2: Scans for placeholder patterns
- `check_phase_gates(phase_id, state, profile, artifacts_base)` -- Main orchestrator; runs all gates and returns results list
- `format_results(results)` -- Formats gate results for human-readable output

**Gate Details:**

#### Gate 1: Integrity (G1-integrity)

Checks that all required artifacts for the phase exist and are well-formed.

- **File existence:** Verifies each required artifact file is present in `.sdlc/artifacts/<phase-dir>/`
- **Non-empty check:** Files must have content (>0 bytes)
- **Directory children:** If the artifact is a directory (e.g., `section-plans/`), verifies it contains at least one child item
- **Severity:** MUST

#### Gate 2: Completeness (G2-completeness)

Scans artifact content for placeholder patterns that indicate incomplete work.

**Detected patterns:**
- `TODO` -- Unfinished work markers
- `TBD` -- "To be determined" placeholders
- `${...}` -- Unresolved template variables
- `PLACEHOLDER` -- Explicit placeholder text
- `[INSERT` -- Template insertion points (e.g., `[INSERT DESCRIPTION HERE]`)
- `<!-- REQUIRED:` -- marks a section that must be written; **delete the comment once you have written it**, or the artifact never passes

For each artifact, the script reads the file content and checks against these patterns. If any match is found, the artifact fails the completeness gate.

Ordinary bracket prose (`[Describe the situation]`) is deliberately **not** in the list: templates
use `- [ ]` checkboxes and `[text](links)`, so a general bracket rule would fail nearly every
artifact. The consequence is that a carelessly half-filled artifact can pass — the check is a
tripwire for an untouched template, not a proofreader.

**Build loop:** the gate prints a spec-backlog summary via `track_specs.py` instead of a section consistency check. It scans `<repo>/specs/*.md`, reads each spec's frontmatter `status` (`draft`/`ready`/`in-flight`/`merged`, or `deferred`) and `risk` (`HIGH`/`MEDIUM`/`LOW`), and reports as `INFO`:
- Total specs
- Status breakdown (merged / in-flight / ready / draft)
- Risk breakdown (HIGH / MEDIUM / LOW)
- The in-flight list

`check_gates.py` is protected core, so this line's four-status breakdown is unchanged — a deferred spec is still counted in the total but does not get its own number here. `track_specs.py`'s own report and `--json` output do break it out (see [`track_specs.py`](#track_specspy) below).

This is informational and does not block — progress is read directly from the spec files (the unit of work: one spec = one branch = one PR), so it cannot drift from a separately maintained tracker.

**Severity:** MUST (the completeness gate itself); the spec-backlog summary is INFO

#### Gate 3: Metrics (G3-metrics)

Enforced per-change in the Build loop (coverage, file/function line counts). Checks quantitative thresholds from the profile.

- **Coverage minimum:** `quality.coverage_minimum` from profile (0-100 range)
- **File line limits:** `quality.max_file_lines` from profile
- **Function line limits:** `quality.max_function_lines` from profile

**Severity:** applied per change inside the Build loop

#### Gate 4: Compliance (G4-compliance)

Loads compliance-specific gates from the profile's compliance directory.

- Reads `compliance.frameworks` from the profile (e.g., `["soc2", "hipaa"]`)
- For each framework, loads `profiles/<profile_id>/compliance/<framework>-gates.yaml`
- Runs each compliance gate check against the phase artifacts
- Examples: requirements must have priority labels (P0-P3), design decisions need ADR status, test cases must map to requirements

**Severity:** MUST for compliance-enabled profiles, SHOULD for others

#### Gate 5: Cross-Phase Consistency (G5-consistency)

Detects drift in locked metrics across phase transitions (budget, timeline, scope, stakeholder roster, quality thresholds, compliance requirements).

- Compares locked values between successive phases for unexplained changes
- Warns rather than blocks -- divergence is surfaced, not fatal
- Discrepancies are documented via the decision log

**Severity:** SHOULD (warns, does not block)

#### Gate 6: Quality (G6-quality)

Checks review status and traceability.

- Verifies artifacts have been reviewed (review status markers)
- Checks traceability links between artifacts (requirements to tests, designs to implementations)

**Severity:** MUST for phases 2, 5; SHOULD for others

**Output Format:**

Results are returned as a list of dictionaries:

```json
[
  {
    "gate": "G1-integrity",
    "artifact": "problem-statement.md",
    "passed": true,
    "message": "File 'problem-statement.md' exists",
    "severity": "MUST"
  },
  {
    "gate": "G2-completeness",
    "artifact": "requirements.md",
    "passed": false,
    "message": "Placeholder pattern found: TODO (line 42)",
    "severity": "MUST"
  }
]
```

**Gate Application by Phase:**

| Phase | G1 | G2 | G3 | G4 | G5 Consistency | G6 Quality |
|-------|:--:|:--:|:--:|:--:|:--:|:--:|
| 0 Discovery | MUST | MUST | -- | -- | -- | SHOULD |
| 1 Requirements | MUST | MUST | -- | MUST | SHOULD | SHOULD |
| 2 Design | MUST | MUST | -- | MUST | SHOULD | MUST |
| 3 Foundation | MUST | MUST | -- | -- | SHOULD | SHOULD |
| build (Build Loop) | MUST | MUST | SHOULD | SHOULD | SHOULD | SHOULD |
| 7 Documentation | MUST | MUST | -- | -- | SHOULD | SHOULD |
| 8 Deployment | MUST | MUST | -- | MUST | SHOULD | SHOULD |
| 9 Monitoring | MUST | MUST | -- | -- | SHOULD | SHOULD |
| close (Close & Transfer) | MUST | MUST | -- | -- | SHOULD | MUST |

**Exit codes:** `0` (all MUST gates pass), `1` (any MUST gate fails)

---

### advance_phase.py

**Purpose:** Advance the SDLC project to the next phase. Supports a dry-run mode for gate preview and a confirmed mode for actual state transition. This script imports `check_phase_gates` and `format_results` directly from `check_gates.py` to reuse the gate logic.

**CLI:**

```bash
# Dry-run: show gate results without advancing
uv run scripts/advance_phase.py --state .sdlc/state.yaml

# Confirmed: advance after gate checks pass
uv run scripts/advance_phase.py --state .sdlc/state.yaml --confirmed
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--state` | Yes | Path to `.sdlc/state.yaml` |
| `--confirmed` | No | Human sign-off flag; without it, the script only checks gates (dry-run) |

**Process:**

1. **Load state and profile** from `.sdlc/state.yaml` and `.sdlc/profile.yaml`
2. **Check phase boundary** -- if the current phase is terminal (`close`), reports completion and exits
3. **Run all gate checks** for the current phase via `check_phase_gates()`
4. **Print gate results** using `format_results()` (always shown, even in confirmed mode)
5. **If any MUST gate fails:** exit with code `1`, print blockers
6. **If dry-run (no `--confirmed`):** exit with code `0`, print message that `--confirmed` is needed
7. **If confirmed and all gates pass:** update `state.yaml` atomically:
   - Set current phase status to `completed` with `completed_at` timestamp
   - Set next phase status to `active` with `entered_at` timestamp
   - Set `current_phase` to the next phase by registry `order` (via `phase_model.py` -- not `id+1`; ids may be strings)
   - Update `phase_name` string
   - Append transition record to `history` array:
     ```yaml
     - from: <current_phase_id>
       to: <next_phase_id>
       at: "2026-03-26T12:00:00+00:00"
       gate_results: { passed: N, failed: 0, total: N }
     ```
8. **Print next phase guidance:**
   - Phase display name and description
   - Primary and secondary skills
   - Required and optional artifacts
   - Artifact directory path
   - Phase definition file path

**Key Functions:**

- `get_phase_registry()` / `get_phase_def(phase_id)` -- Load and look up phase definitions
- `now_iso()` -- Generate UTC ISO 8601 timestamp
- `advance(state_path, confirmed)` -- Main logic; returns `0` (success), `1` (gate failure), `2` (config error)
- `save_yaml(path, data)` -- Atomic YAML write with `default_flow_style=False`

**Output (confirmed, success):**

```
Gate Results for Phase 0 (Discovery):
  [PASS] G1-integrity: problem-statement.md -- File exists
  [PASS] G2-completeness: problem-statement.md -- No placeholders found
  ...

[OK] Advanced: Phase 0 (discovery) -> Phase 1 (requirements)

==================================================
Now entering: Phase 1 -- Requirements
==================================================
Elicit, analyze, and document functional and non-functional requirements.

Primary skills:   requirements-analysis, stakeholder-interview
Secondary skills: domain-modeling

Required artifacts:
  - requirements.md
  - non-functional-requirements.md
  - epics.md
Optional artifacts:
  - stakeholder-analysis.md
  - phase2-handoff.md

Artifact directory: .sdlc/artifacts/phase01/
Phase definition:   phases/01-requirements.md

Run /sprd to see full phase guidance.
```

(Artifact directories use the phase `slug` from the registry -- e.g. `03-foundation/`, `build/`, `close/` -- never a zero-padded id.)

**Exit codes:** `0` (success or dry-run pass), `1` (gate failure), `2` (configuration error)

---

### generate_phase_report.py

**Purpose:** Render SDLC phase artifacts as self-contained HTML reports. This is the largest script (~40KB) and produces polished, stakeholder-ready reports that can be opened directly in any browser without a server.

**CLI:**

```bash
# Single phase
uv run scripts/generate_phase_report.py --state .sdlc/state.yaml --phase 0

# Single phase with custom output path
uv run scripts/generate_phase_report.py --state .sdlc/state.yaml --phase 0 --output .sdlc/reports/00-discovery-report.html

# All phases (generates individual reports + index.html)
uv run scripts/generate_phase_report.py --state .sdlc/state.yaml --all
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--state` | Yes | Path to `.sdlc/state.yaml` |
| `--phase` | No | Phase number to render (0-9); mutually exclusive with `--all` |
| `--all` | No | Generate reports for all phases plus an index page |
| `--output` | No | Custom output path (defaults to `.sdlc/reports/<slug>-report.html`, e.g. `00-discovery-report.html`, `build-report.html`) |

**Process:**

1. **Load state** to determine project metadata and phase statuses
2. **Resolve artifact directory** from the registry slug (`.sdlc/artifacts/<slug>/`), falling back to the project root and `docs/` when an artifact is not there
3. **For each phase:**
   - Look up required and optional artifacts from `PHASE_INFO` metadata
   - Find each artifact file via `find_artifact()` (searches `.sdlc/artifacts/`, project root, `docs/`)
   - Convert Markdown content to HTML via `md_to_html()`
   - Embed into the HTML template with navigation and styling
4. **For `--all` mode:** additionally generates `index.html` with a timeline view of all phases

**Key Components:**

- **`PHASE_INFO` dict** -- Maps each phase number to its display name and list of `(filename, label)` artifact tuples
- **`md_to_html(text)`** -- Minimal GitHub-flavored Markdown to HTML converter handling:
  - Headings (h1-h6)
  - Code blocks with language class
  - Tables with thead/tbody
  - Unordered lists
  - Bold, italic, inline code, links
  - HTML escaping for security
- **`find_artifact(project_root, phase_num, filename)`** -- Searches multiple locations for an artifact file
- **`build_nav_items()` / `build_gate_items()`** -- Generate sidebar navigation and gate status indicators

**Visual Features:**

- Dark theme default (`#0f1117` background, `#6c8ef7` accent, `#4ade80` green)
- Phase timeline navigation bar across the top
- Sidebar table of contents with found/missing status indicators
- Gate status summary showing artifact presence
- Responsive layout (sidebar collapses on mobile)
- All CSS and JS inlined -- no external dependencies
- Missing artifacts appear as labeled placeholder sections (not errors)

**Output:** Self-contained HTML files in `.sdlc/reports/`:

```
.sdlc/reports/
  00-discovery-report.html
  01-requirements-report.html
  ...
  index.html            (only with --all)
```

**Exit codes:** `0` (success), `1` (state file not found or phase invalid)

---

### generate_status.py

**Purpose:** Generate a text-based status dashboard summarizing SDLC progress. Provides a quick overview of all phases, their completion status, and artifact counts.

**CLI:**

```bash
# Print to stdout
uv run scripts/generate_status.py --state .sdlc/state.yaml

# Write to file
uv run scripts/generate_status.py --state .sdlc/state.yaml --output status.md
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--state` | Yes | Path to `.sdlc/state.yaml` |
| `--output` | No | Write dashboard to file instead of stdout |

**Process:**

1. **Load state** and extract project metadata (`project_name`, `profile_id`, `current_phase`)
2. **Calculate progress** -- count completed phases, compute percentage
3. **Generate ASCII progress bar** -- 20-character bar with `#` (filled) and `-` (empty)
4. **Build phase table** -- iterate all 9 phases, show status icon, name, artifact count, and timestamps
5. **Count artifacts** per phase by scanning `.sdlc/artifacts/<phase-dir>/`

**Status Icons:**

| Status | Icon |
|--------|------|
| `completed` | `[x]` |
| `active` | `[>]` |
| `pending` | `[ ]` |
| `skipped` | `[-]` |

**Output Example:**

```markdown
# SDLC Status Dashboard
**Project:** my-app
**Profile:** microsoft-enterprise
**Current Phase:** 2 -- Design

**Progress:** [####------------] 20% (2/9 phases)

## Phases
| # | Phase          | Status | Artifacts | Entered    | Completed  |
|---|----------------|--------|-----------|------------|------------|
| 0 | Discovery      | [x]    | 3         | 2026-03-01 | 2026-03-05 |
| 1 | Requirements   | [x]    | 5         | 2026-03-05 | 2026-03-15 |
| 2 | Design         | [>]    | 2         | 2026-03-15 | --         |
| 3 | Foundation     | [ ]    | 0         | --         | --         |
| build | Build Loop | [ ]    | 0         | --         | --         |
...
| close | Close & Transfer | [ ] | 0       | --         | --         |
```

**Exit codes:** `0` (success), `1` (state file not found)

---

### audit_gates.py

**Purpose:** Analyze gate effectiveness across completed SDLC phases. Identifies gates that are too lenient (always pass), too strict (consistently fail), or frequently overridden. Useful for tuning gate configuration over time and across projects.

**CLI:**

```bash
# Single project audit
uv run scripts/audit_gates.py --state .sdlc/state.yaml

# Compare two projects side-by-side
uv run scripts/audit_gates.py --state .sdlc/state.yaml --compare /other-project/.sdlc/state.yaml
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--state` | Yes | Path to `.sdlc/state.yaml` |
| `--compare` | No | Path to another `state.yaml` for cross-project comparison |

**Process:**

1. **Extract gate history** via `extract_gate_history(state)`:
   - Iterates all phases in `state.phases`
   - Collects `gate_results` from each completed phase
   - Handles both list and dict formats for gate results
   - Returns flat list of gate result records with phase attribution
2. **Analyze gates** via `analyze_gates(results)`:
   - Aggregates per-gate statistics using `defaultdict`:
     - `total` -- total number of checks
     - `passed` -- count of passed checks
     - `failed` -- count of failed checks
     - `manual` -- count of manual/overridden checks
     - `phases_seen` -- set of phases where the gate was evaluated
     - `overrides` -- list of override records with justifications
3. **Format report** via `format_report(gate_stats, state)`:
   - **Summary section:** project name, total gates evaluated, overall pass rate
   - **Always-Pass Gates:** gates with 0 failures and >0 evaluations (candidates for tightening or removal)
   - **High-Fail Gates:** gates with >50% failure rate (possible process issues or overly strict thresholds)
   - **Override History:** table of all manual overrides with gate name, phase, and justification
   - **Recommendations:** actionable suggestions based on the analysis

**Output Sections:**

```
# Gate Effectiveness Audit
Project: my-app | Phases analyzed: 5

## Summary
Total gate evaluations: 42
Overall pass rate: 85.7%

## Always-Pass Gates (candidates for tightening or removal)
  - G1-integrity: passed 15x across phases [0, 1, 2, 3, 4]

## High-Fail Gates (>50% failure rate -- possible process issues)
  - G3-metrics: failed 4/6 (67%)

## Override History
| Gate | Phase | Justification |
|------|-------|---------------|
| G2-completeness | 3 | TDD stubs intentionally contain TODO markers |

## Recommendations
- 1 always-pass gate(s) detected. Consider tightening or removing.
- 1 override(s) recorded. Review whether overridden gates should be relaxed.
```

**Cross-Project Comparison:** When `--compare` is provided, the script runs the full analysis pipeline on both state files and prints both reports separated by a divider. This enables manual comparison of gate configurations across projects.

**Exit codes:** `0` (success), `1` (state file not found)

---

### synthesize_spec.py

**Purpose:** Synthesize Phase 0 (Discovery) and Phase 1 (Requirements) artifacts into a single consolidated specification file. This spec serves as the primary input for `/deep-plan` integration, providing a self-contained project description.

**CLI:**

```bash
uv run scripts/synthesize_spec.py --state .sdlc/state.yaml [--output <path>]
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--state` | Yes | Path to `.sdlc/state.yaml` |
| `--output` | No | Output file path (defaults to `.sdlc/artifacts/spec.md`) |

**Process:**

1. **Resolve artifacts base** from `state.yaml` parent directory
2. **Read Phase 0 artifacts** (optional enrichment):
   - `00-discovery/problem-statement.md`
   - `00-discovery/constraints.md`
   - `00-discovery/success-criteria.md`
3. **Read Phase 1 artifacts** (primary content):
   - `01-requirements/requirements.md` (REQUIRED -- script exits with error if missing/empty)
   - `01-requirements/non-functional-requirements.md`
   - `01-requirements/epics.md`
   - `01-requirements/phase2-handoff.md`
4. **Assemble specification** by concatenating sections with headers:
   - `# Project Specification` (with synthesis timestamp and source path)
   - `## Problem Statement` (from Phase 0, if available)
   - `## Requirements` (from Phase 1, always present)
   - `## Non-Functional Requirements` (if available)
   - `## Epics & User Stories` (if available)
   - `## Constraints` (from Phase 0, if available)
   - `## Success Criteria` (from Phase 0, if available)
   - `## Phase 2 Handoff Notes` (if available)
5. **Write output** to the specified path

**Key Function:**

- `read_artifact(path)` -- Returns file content as stripped string, or empty string if file does not exist. Uses `encoding="utf-8"` with `errors="replace"` for robustness.

**Output:** A single Markdown file combining all early-phase artifacts into a format consumable by `/deep-plan`.

**Exit codes:** `0` (success), `1` (`requirements.md` missing or empty, state file not found)

---

### map_deep_plan_artifacts.py

**Purpose:** Transform `/deep-plan` section outputs into SDLC-formatted phase artifacts. This is the bridge between the `/deep-plan` planning system and the SDLC artifact structure. Supports both Phase 2 (Design) and Phase 3 (Foundation) mapping modes. The script is idempotent and safe to re-run.

**CLI:**

```bash
# Phase 2 mapping (after /deep-plan steps 1-15)
uv run scripts/map_deep_plan_artifacts.py --state .sdlc/state.yaml --phase 2 --planning-dir planning/

# Phase 3 mapping (after /deep-plan steps 16-22)
uv run scripts/map_deep_plan_artifacts.py --state .sdlc/state.yaml --phase 3 --planning-dir planning/
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--state` | Yes | Path to `.sdlc/state.yaml` |
| `--phase` | Yes | Target phase (2 or 3) |
| `--planning-dir` | Yes | Path to the `/deep-plan` planning directory |

**Key Functions:**

- `copy_if_exists(src, dest)` -- Copies a file or directory if source exists; creates parent directories as needed; handles both files (`shutil.copy2`) and directories (`shutil.copytree` with overwrite)
- `extract_sections_by_heading(content, level)` -- Parses Markdown into a dict of `{heading: content}` by heading level
- `parse_section_manifest(index_content)` -- Extracts the `SECTION_MANIFEST` from `sections/index.md` using a regex match on `<!-- SECTION_MANIFEST ... END_MANIFEST -->` comment blocks
- `parse_project_config(index_content)` -- Extracts project configuration values from the index
- `transform_section_to_sdlc(section_name, number, content, tdd_content, manifest)` -- Converts a `/deep-plan` section file into the SDLC converged template format
- `map_phase_2(planning_dir, artifacts_dir)` -- Phase 2 specific mapping (design artifacts)
- `map_phase_3(planning_dir, artifacts_dir)` -- Phase 3 specific mapping (section plans)

**Phase 3 Mapping Process (primary use case):**

1. **Read section manifest** from `planning/sections/index.md`
2. **Fallback discovery** -- if no manifest found, glob for `section-*.md` files directly
3. **Read TDD plan** from `planning/claude-plan-tdd.md`
4. **For each section in manifest:**
   - Locate the corresponding `/deep-plan` file at `planning/sections/<section-name>.md`
   - Transform to SDLC format via `transform_section_to_sdlc()`
   - Write to `.sdlc/artifacts/03-foundation/section-plans/SECTION-NNN.md` (zero-padded 3-digit number)
5. **Copy supplementary files:**
   - `claude-plan-tdd.md` -> `.sdlc/artifacts/03-foundation/tdd-plan.md`
   - `sections/index.md` -> `.sdlc/artifacts/03-foundation/dependency-map.md`

**Converged Template Format:**

The output uses `SECTION-template-deep-plan.md` which preserves both systems' requirements:

- **SDLC structured fields:** Goal, Epics/Stories, Entry/Exit Criteria, Dependencies, Interfaces, Test Strategy, Risk
- **`/deep-plan` prose:** Full implementation guidance in a dedicated "Implementation Guidance" section, self-contained enough for `/deep-implement` to consume

**Output Structure:**

```
.sdlc/artifacts/03-foundation/
  section-plans/
    SECTION-001.md
    SECTION-002.md
    ...
    SECTION-NNN.md
  tdd-plan.md
  dependency-map.md
```

**Exit codes:** `0` (success), `1` (state file or planning directory not found)

---

### risk_model.py

**Purpose:** Single source of truth for the risk taxonomy and the checking ladder. A spec's risk tier (`HIGH`/`MEDIUM`/`LOW`, assigned by a human at triage) sets how high its change climbs the checking ladder in the Discern beat. This module encodes that mapping once so `check_spec.py` and any other consumer resolve review depth the same way. It is a library module (imported), not a CLI — it has no `main()`.

**Imported by:** `check_spec.py`, `track_specs.py`, `generate_handoff_report.py` (indirectly via `track_specs`).

**What scales by tier:** the *depth* of human review and whether the security pass + named sign-off are mandatory — never whether checking happens at all. Every tier blocks on CI, runs the grader (advises), runs the correctness gate (blocks on a defect), and requires a non-author approval. HIGH adds a blocking security pass and a named human sign-off recorded in the PR. The security pass also fires path-triggered (any PR touching a gated path), independent of tier.

**Public API:**

| Function | Returns | Description |
|----------|---------|-------------|
| `normalize_tier(tier)` | `str \| None` | Canonical upper-case tier from any source, or `None` if invalid |
| `is_valid_tier(tier)` | `bool` | Whether the value names a valid tier |
| `resolve_ladder(tier, touches_gated_path=False)` | `dict \| None` | The required ladder booleans for a tier (`ci_blocks`, `grader_runs`, `correctness_blocks_on_defect`, `non_author_approval`, `security_pass_required`, `named_signoff_required`, plus `review_depth`). `touches_gated_path=True` forces the security pass |
| `required_rungs(tier, touches_gated_path=False)` | `list[str]` | Human-readable list of gates a tier must clear, in ladder order |

**Module constants:** `RISK_TIERS = ("HIGH", "MEDIUM", "LOW")`, `TAXONOMY` (what lands in each tier and what it triggers — mirrored in `CLAUDE.md` so agents see it).

**Exit codes:** N/A (library module).

---

### new_spec.py

**Purpose:** Scaffold a new Build-loop spec (`specs/NNNN-name.md`) from the spec template. Specs are the durable per-change unit of the Build loop — one spec = one branch = one PR — and live in the target repo's `specs/` directory (in the repo, not under `.sdlc/`), so the agent and grader read them from version control like any source file.

**CLI:**

```bash
# Workflow mode (repo root = .sdlc parent)
uv run scripts/new_spec.py --state .sdlc/state.yaml --name "duplicate claim 409" --risk HIGH

# Standalone mode (any repo, no .sdlc/ required)
uv run scripts/new_spec.py --repo <path> --name "duplicate claim 409" --risk HIGH --source REQ-123
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--state` | One of `--state`/`--repo` | Path to `.sdlc/state.yaml` (workflow mode) |
| `--repo` | One of `--state`/`--repo` | Target repo root (standalone; default cwd) |
| `--name` | Yes | Short descriptive name (becomes the kebab-case slug and frontmatter `name`) |
| `--risk` | No | Risk tier `HIGH`/`MEDIUM`/`LOW` (default `MEDIUM`) — the agent proposes, a human confirms |
| `--source` | No | Originating story / REQ-id (default `—`) |

**Process:**

1. **Resolve repo root** from `--state` (`.sdlc` parent) or `--repo`
2. **Allocate id** — scan `specs/*.md`, take the highest 4-digit prefix + 1 (`0001` when none), so ids stay stable and gap-free across sessions
3. **Render the template** (`templates/phases/build/spec.md`) — fill frontmatter `spec`/`name`/`risk`/`source`/`created`, the title, and sync the body `**Tier:**` and `**Ladder depth:**` lines to the chosen risk (both agreements that `check_spec.py` enforces)
4. **Write** `specs/NNNN-slug.md` (errors if it already exists)

**Exit codes:** `0` (created), `1` (invalid `--risk`, empty slug, template missing, state file missing, or spec already exists)

---

### check_spec.py

**Purpose:** Enforce the Definition of Ready (DoR) on a Build-loop spec — the "Intent rail": a story becomes buildable only by clearing the DoR. Checks the mechanical floor of that bar (structure, risk tier, scope in/out, no placeholders, field/section agreement, checking-ladder depth) plus an advisory vague-line lint on acceptance checks.

**CLI:**

```bash
# Standalone
uv run scripts/check_spec.py --spec specs/0001-duplicate-claim-409.md

# Workflow (also logs metrics to .sdlc/metrics/spec-log.jsonl)
uv run scripts/check_spec.py --spec specs/0001-duplicate-claim-409.md --state .sdlc/state.yaml
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--spec` | Yes | Path to `specs/NNNN-name.md` |
| `--state` | No | Path to `.sdlc/state.yaml` — enables empirical metrics logging |

**Checks (MUST blocks, exit 1; SHOULD advises, exit 0 — mirrors `check_gates.py` severities):**

| Severity | Check |
|----------|-------|
| MUST | Parseable YAML frontmatter present |
| MUST | `name` set (not the template default) |
| MUST | `risk` is one of HIGH/MEDIUM/LOW |
| MUST | All required sections present (Goal, Why, Scope, Acceptance Checks, Risk Tier, Delegation Plan, Checking Plan) |
| MUST | Scope > In scope **and** Scope > Out of scope both non-empty |
| MUST | At least one acceptance check |
| MUST | No unfilled template placeholders (`TODO`, `TBD`, `NNNN`, `<title>`, …) |
| MUST | Risk Tier section agrees with frontmatter `risk` |
| MUST | Checking Plan `**Ladder depth:**` declared and equal to the risk tier |
| SHOULD | `harness_context` names the ONE existing pattern reused |
| SHOULD | Vague-line lint — acceptance checks carrying vague words or lacking a concrete signal |
| SHOULD | HIGH spec's Checking Plan names the security pass and the named sign-off |

**Key functions:** `parse_frontmatter`, `extract_section` / `extract_subsection`, `list_items`, `check_spec_text` (the orchestrator, importable — reused by `track_specs.py`), `log_spec_metrics`, `format_results`.

**Exit codes:** `0` (ready, possibly with advisories), `1` (any MUST fails, or spec not found)

---

### track_specs.py

**Purpose:** Track the Build-loop spec backlog from the specs themselves. In the spec-driven Build loop the spec IS the unit of work and the durable source of truth, so backlog progress is derived from each spec's frontmatter `status` — never from a separate hand-maintained tracker that can drift. This replaced the section-plan progress model (`sections-progress.json`) in the Build loop.

**CLI:**

```bash
# Workflow
uv run scripts/track_specs.py --state .sdlc/state.yaml [--wip-cap 3] [--json]

# Standalone
uv run scripts/track_specs.py --repo <path>

# One sprint's slate only (the frontmatter `sprint:` written by sprint.py)
uv run scripts/track_specs.py --state .sdlc/state.yaml --sprint S07 [--json]
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--state` | One of `--state`/`--repo` | Path to `.sdlc/state.yaml` (workflow mode) |
| `--repo` | One of `--state`/`--repo` | Target repo root (standalone; default cwd) |
| `--wip-cap` | No | Flag when more than N specs are in-flight (the cap itself lives in `cadence-plan.md`; the cap is global — a sprint's slate is never a second WIP budget) |
| `--sprint` | No | Only the specs whose frontmatter `sprint:` equals `SNN` exactly (applied before summarizing, so every count is for that slate); the text title becomes "Spec Backlog — sprint SNN" and the JSON gains `sprint_filter` |
| `--json` | No | Emit the summary as JSON |

**Output:** Total specs; breakdown by status (`draft`/`ready`/`in-flight`/`merged`, plus `deferred` on its own line once any spec uses it — never pre-seeded at zero, so a project that has never deferred a spec sees unchanged output) and by risk tier; the in-flight list (one spec = one branch = one PR; deferred specs are never in it); WIP-cap warnings. Invoked by `check_gates.py` to print the Build gate's INFO spec-backlog summary (that line stays the original four statuses — see above), and by `generate_handoff_report.py` for the handoff report's spec-backlog and deferred-items sections.

**Sprint layer (1.6.0, additive):** each scanned row carries `sprint` and `next_owner` (default `""`), and the summary gains `by_sprint` — a bucket → count map that *partitions* the specs (the counts sum to `total`): one bucket per `SNN` found, `unassigned` (no sprint, not merged), and `pre-sprint` (no sprint **and** merged — delivered before the sprint layer existed). The text report's "By sprint:" block renders only when at least one spec carries a non-empty sprint, so the legacy output is byte-identical for backlogs that never used sprints. Files whose frontmatter `spec:` id is not numeric (the installed `specs/spec-template.md` carries `spec: "NNNN"`) are skipped, so the template is no longer counted as a phantom draft here, in the Build gate's backlog line, or in the handoff report.

**Key functions:** `scan_specs` (parses every `specs/*.md` frontmatter), `summarize`, `wip_warnings`, `filter_by_sprint`, `sprint_bucket`, `sprint_ids`, `is_spec_id` — all importable; constants `UNASSIGNED_BUCKET`, `PRE_SPRINT_BUCKET`.

**Exit codes:** `0` (no warnings), `1` (a WIP-cap breach was flagged) — unchanged by the sprint additions

---

### scorecard.py

**Purpose:** Record and report the Build-loop steering scorecard — the numbers that steer the loop, baseline-and-trend. The delivery-standard steers on **outcomes, not activity**. This tool records loop outcome events to `.sdlc/metrics/loop-events.jsonl` and reports the scorecard from them. It is deliberately separate from `gate-log.jsonl` (gate calibration) and `spec-log.jsonl` (DoR data): those measure the harness; this measures delivery.

**CLI:**

```bash
# Record an outcome event
uv run scripts/scorecard.py record --state .sdlc/state.yaml --type spec_merged --field accepted_as_is=true --field risk=HIGH

# Report the scorecard
uv run scripts/scorecard.py report --state .sdlc/state.yaml [--window-days 14] [--json]
```

**Subcommands & arguments:**

| Subcommand | Argument | Description |
|------------|----------|-------------|
| `record` / `report` | `--state` / `--repo` | `.sdlc/state.yaml` (workflow) or repo root (standalone; default cwd) |
| `record` | `--type` | Event type (see below) |
| `record` | `--field key=value` | Repeatable; bools/ints/floats coerced, else string |
| `report` | `--window-days` | Label only (date filtering is the caller's job) |
| `report` | `--json` | Emit the scorecard as JSON |

**Event types:** `spec_merged` (`accepted_as_is`, `risk`), `spec_reverted`, `spec_bounced`, `escaped_bug` (`which_check`), `deploy` (`env`, `succeeded`, `lead_time_hours`, `caused_failure`), `incident` (`ttr_hours`), `review_wait` (`wait_hours`, `security`).

**Reported metrics:** accepted-as-is rate, rework/revert rate, bounce-back rate, review-wait median (security-review wait on its own line), the DORA four (deploy count, lead-time median, change-fail rate, time-to-recover median), and escaped bugs. Missing data reads **"no data"**, never a fabricated zero.

**Refused by design:** recording `velocity`, `story_points`, `pr_count`, `lines_of_code`, `commits` exits `2` — the activity metrics the standard never tracks. `compute_scorecard`, `load_events`, `format_report`, `_pct`, `_hrs` are importable (reused by `generate_handoff_report.py`).

**Exit codes:** `0` (success), `1` (unknown event type, bad `--field`, or state file missing), `2` (a forbidden activity metric was passed to `record`)

---

### generate_handoff_report.py

**Purpose:** Draft the Phase C (Close & Transfer) `final-handoff-report.md` from the engagement's own records — the deterministic first pass of close.md Step 4 ("Hand over the record"), run before the Explore agent enriches the narrative. It fills the existing handoff-report template's mechanical sections from real data and marks the judgment sections with `[Fill: ...]` slots.

**CLI:**

```bash
# Workflow mode
uv run scripts/generate_handoff_report.py --state .sdlc/state.yaml

# Standalone mode (no .sdlc/ — notes the missing context in the report header)
uv run scripts/generate_handoff_report.py --repo <path>

# Custom output / regenerate over a prior draft
uv run scripts/generate_handoff_report.py --state .sdlc/state.yaml --output handoff.md --force
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--state` | One of `--state`/`--repo` | Path to `.sdlc/state.yaml` (workflow mode) |
| `--repo` | One of `--state`/`--repo` | Repo root containing `.sdlc/` (standalone; defaults to cwd) |
| `--output` | No | Output path (defaults to `.sdlc/artifacts/close/final-handoff-report.md`) |
| `--force` | No | Overwrite an existing report (refuses by default, to protect human edits) |

**Sections filled from records:**

| Section | Source |
|---------|--------|
| Phase report index | `phase_model.all_phases()` + presence of `<slug>-report.html` in `.sdlc/reports/` |
| Engagement record | per-phase gate status, completion date, and approver from `state.yaml` `phases[]` |
| Metrics history | `scorecard.compute_scorecard()` over `.sdlc/metrics/loop-events.jsonl` |
| Spec backlog | `track_specs.summarize(scan_specs())` over `specs/` |

**Sections left as `[Fill: ...]` slots (judgment, not data):** outcomes against the Phase 0 statement, the technical debt log, open items with owners/dates, and the outcomes-dashboard handover.

**Honest by design:** missing metrics read "no data", never a fabricated zero (inherited from `scorecard.py`). A standalone run with no `state.yaml` adds a "Standalone draft" banner noting the engagement context is absent.

**Exit codes:** `0` (drafted), `1` (state file not found, or the report exists and `--force` was not given)

---

### sprint.py

**Purpose:** The I/O CLI of the sprint team layer (`/sprd-sprint`, `/sprd-refine`; users never call it by hand). A sprint is a *commitment window over the backlog order* — never a second backlog, a reordering, or a gate. A named human types a sprint id (`S07`), slates a *count* of specs by a mix of risk tiers, readies the sprint once every slated spec clears the Definition of Ready and its Engineering and Data verdicts, and closes it with kept / carried / dropped, each with a name and a reason. Every rule lives in the pure `sprint_model.py` (mirrors `findings_model.py`: sprint states, `parse_mix`, `propose_slate`, `ready_gaps`, `build_order` / `next_up` reusing `check_dependencies.detect_cycles` / `topological_sort`, `outcomes`, `set_frontmatter`, `FORBIDDEN_FIELDS`, the business-day adapters over `track_decisions`); this file only reads and writes files.

**CLI:**

```bash
# Create the record (planning); end defaults to the last business day of a 10-business-day window (start is day 1: Mon 2026-09-28 -> Fri 2026-10-09)
uv run scripts/sprint.py new --repo <path> --sprint S07 --goal "Ship the duplicate-claim rail" --start 2026-09-28 [--end D | --days 10] --target 6 [--mix "HIGH:1,MEDIUM:2,LOW:3"] [--board-ref "ADO Iteration 6"] --by "Pod Lead"

# Propose a slate (writes nothing), then confirm it
uv run scripts/sprint.py slate --state .sdlc/state.yaml --sprint S07 [--json]
uv run scripts/sprint.py slate --state .sdlc/state.yaml --sprint S07 --by "Pod Lead" --spec 0007 --spec 0009 [--override --reason R]
uv run scripts/sprint.py unslate --state .sdlc/state.yaml --sprint S07 --spec 0009 --by "Pod Lead" --reason "pulled into S08"

# The daily view (text, or the JSON /sprd-status and /sprd-refine read)
uv run scripts/sprint.py status --state .sdlc/state.yaml [--sprint S07] [--wip-cap N] [--json]

# Handoffs and verdicts
uv run scripts/sprint.py handoff --state .sdlc/state.yaml --spec 0007 --to "Eng Lead" --by "Pod Lead" [--note "..."]
uv run scripts/sprint.py ack --state .sdlc/state.yaml --spec 0007 --by "Eng Lead"
uv run scripts/sprint.py verdict --state .sdlc/state.yaml --spec 0007 --lane eng --verdict accepted --by "Eng Lead"
uv run scripts/sprint.py verdict --state .sdlc/state.yaml --spec 0007 --lane data --verdict n-a --by "Data Lead" --reason "UI copy only — no data impact"

# Ready (writes the planning page), re-render it on demand, close (writes the review page)
uv run scripts/sprint.py ready --state .sdlc/state.yaml --sprint S07 --by "Pod Lead"
uv run scripts/sprint.py plan --state .sdlc/state.yaml --sprint S07 [--output PATH]
uv run scripts/sprint.py close --state .sdlc/state.yaml --sprint S07 --by "Pod Lead" --carry-to S08 --carry "0009=blocked on DL-04" --drop "0011=descoped after workshop"
```

**Verbs (flat argparse subparsers; every verb takes `--state | --repo`, `--today YYYY-MM-DD`, and — on writes — repeatable `--field KEY=VALUE`):**

| Verb | Kind | Does |
|------|------|------|
| `new` | write | Renders `templates/phases/build/sprint.md` into `.sdlc/sprints/SNN.md` in `planning`. Id must match `^S\d{2,}$`, one record per id, `--target` ≥ 1, mix validated by `sprint_model.parse_mix` (sum ≤ target), `--end` not before `--start` (default: the last business day of a `--days`-long window, start counted as day 1), `--by` required like every write. Ledger `sprint_new` (`sprint, by`) |
| `slate` (no `--spec`) | read | **Proposal only, writes nothing:** candidates are specs with `status: ready \| draft` and empty `sprint:`; `propose_slate` fills the *remaining* mix slots in spec-id order. Prints a copy-paste confirm line; `--json` for the machine form. An unknown or malformed sprint id prints `Slate proposal: no data — …` and exits 0 (reads never fail) |
| `slate --spec …` | write | Each spec must exist, not be merged, not sit in another sprint (already in this one → skipped). Over target → exit 1 unless `--override --reason`; mix breach and a `depends_on` pointing outside the slate at an unmerged spec → WARNING only. Writes `sprint: "SNN"`, re-renders the record's `## Slate` table, ledger `slated` |
| `unslate` | write | Sets `sprint: ""` with a non-empty `--reason`; ledger `unslated` |
| `status` *(default)* | read | Header, slate table (spec, name, risk, type, status, DoR, eng, data, next owner), readiness (N of M ready + per-spec gaps), pending verdicts and unacknowledged handoffs with business-day age, mix actual vs target ("no target" when a tier is not in the mix), WIP vs cap, open/overdue `DL-NN` decisions, dependency-gap warnings, the advisory **build order** and **next up**. `--sprint` defaults to the active sprint (the highest-numbered sprint not yet closed; when every sprint is closed, the highest-numbered one). On a **closed** sprint the slate is replayed from the ledger (`slated` − `unslated` + `carried`/`dropped`), the header omits "remaining" and names `closed by`, and an empty slate reads `no data — closed; see .sdlc/reports/sprint-SNN-review.html` |
| `handoff` / `ack` | write | Sets / clears `next_owner`; `ack` by someone other than `next_owner` warns, never fails; ledger `handoff` / `ack` |
| `verdict` | write | Writes `eng_review` / `data_review` (`pending \| accepted \| returned \| n-a`). `n-a` is legal for `--lane data` only and only with `--reason`; `returned` without a reason records but warns. Ledger `verdict` |
| `ready` | write | Sprint must be in `planning` (forward only). `sprint_model.ready_gaps` → exit 1 listing `<spec>: <gap>` lines and the ready-when rule, nothing written; else `state: ready`, `readied_by`, ledger `ready`, then the planning page (render failure is a WARNING; the verb still exits 0) |
| `plan` | render | Renders (or re-renders) the planning page on demand, before or after `ready`. Exit 1 if the sprint does not exist |
| `close` | write | kept = slated specs with `status: merged`; every other slated spec must appear in exactly one `--carry SPEC=REASON` or `--drop SPEC=REASON`, else exit 1 naming the undecided. `--carry` requires `--carry-to SNN` (a carry-to sprint with no record yet is a warning). Carried specs get `sprint: "<carry-to>"`, dropped `sprint: ""`; writes the `## Close` table, `state: closed`, `closed_by`, ledger `carried` / `dropped` then `closed`, then the review page — rendered from the view computed **before** the writes (patched to `state: closed`), so the page shows the slate that was reviewed, not the frontmatter after carries moved on |

**The ready rule (D3):** every slated spec `check_spec` READY **and** `status: ready` **and** `eng_review: accepted` **and** `data_review: accepted \| n-a`, plus a dependency graph with no cycle, no unknown id, and no `depends_on` pointing outside the slate at an unmerged spec. An empty slate is itself a gap. G1–G7 are never consulted.

**Build order (D7, advisory):** topological by `depends_on`, then the spec that unblocks the most others, then HIGH → MEDIUM → LOW (the longest checking ladder starts first), then spec id. **Next up** is the first spec in that order that is READY, `status: ready`, with every dependency merged, and under the WIP cap (`--wip-cap`, else the first `**N**` on a "WIP cap" line in `.sdlc/artifacts/*/cadence-plan.md`; `null` / "cap not set" otherwise).

**Reads / writes:**

| Path | Role |
|------|------|
| `specs/*.md` matching `new_spec.SPEC_FILE_RE` (`^\d{4}-`) | Read for frontmatter (`check_spec.parse_frontmatter`) and the DoR verdict (`check_spec.check_spec_text`: READY iff no failed MUST). **Written** only for the five keys `sprint`, `next_owner`, `eng_review`, `data_review`, `depends_on` (inserted after `status:` on first touch, else right after the opening `---`; values are enumerations, names and spec ids — `#`, quotes, newlines and placeholder tokens are refused). `status` cannot be written: `sprint_model.set_frontmatter` rejects any key outside the five. The installed `specs/spec-template.md` is never listed or written. Files are read and written as bytes, so untouched bytes stay identical |
| `.sdlc/sprints/SNN.md` | The sprint record (frontmatter, `## Slate` rendered from spec frontmatter, `## Close` written at close) |
| `.sdlc/metrics/sprint-log.jsonl` | Append-only ledger; `ts` is `datetime.now(timezone.utc).isoformat()`; events `sprint_new`, `slated`, `unslated`, `handoff`, `ack`, `verdict`, `ready`, `closed`, `carried`, `dropped`. **Frontmatter first, then the ledger line** — if the append fails the script prints `DRIFT: N file(s) were written but the ledger append failed` and exits 1 |
| `.sdlc/decision-log.md` (else `<repo>/decision-log.md`) | Read through `track_decisions` for the open / overdue decisions; absent → `decisions: null` |
| `.sdlc/reports/sprint-SNN-planning.html` / `-review.html` | Written via a **lazy** import of `generate_sprint_report` inside `ready` / `plan` / `close` (that module imports `sprint.build_view` at top level) |
| `.sdlc/state.yaml` | **Never written** — tested byte-for-byte across the whole lifecycle in `--state` mode |

**`status --json` / `build_view(repo_root, sprint_id, today=None, wip_cap=None)`** — the exact JSON `/sprd-status` and `/sprd-refine` read: `sprint` (`null` when none; else id, goal, start, end, state, target, mix, board_ref, readied_by, closed_by, created, path, `days: {total, elapsed, remaining}` in business days), `slate` (rows: id, name, risk, type, channel, status, sprint, next_owner, eng_review, data_review, `depends_on: []`, `dor`, `dor_blocking: []`, path), `readiness {ready, total, gaps}`, `verdicts_pending` / `handoffs_open` (with `since_business_days` or `null`), `mix`, `mix_warnings`, `wip {in_flight, cap}`, `build_order`, `next_up`, `dependency_gaps`, `decisions`, `carried_in`, `has_data`. Ages come from the ledger (verdict: since the spec's latest `slated` event; handoff: since the latest `handoff`) — a spec slated by hand with no ledger line reads "no data", never 0. **No per-person aggregation key exists.**

**Refused by design (exit 2, same wording as `scorecard.py`):** any `--field` whose key is in `sprint_model.FORBIDDEN_FIELDS` (`scorecard.FORBIDDEN_TYPES` ∪ `points`, `estimate`, `effort`, `hours`, `capacity`; case-insensitive, `-`/space → `_`) — "Refused: '<key>' is an activity metric the standard never tracks (velocity, story points, PR count, lines of code). Steering is on outcomes."; a `--by` / `--to` that `findings_model.is_ai_actor` flags (the message says this is labelling, not enforcement); a malformed frontmatter value.

**Standalone or Workflow:** `--repo <path>` creates `.sdlc/sprints/` and the ledger under `<repo>/.sdlc/` and the text header notes "(standalone mode — no .sdlc/state.yaml; engagement context not shown)"; `--state .sdlc/state.yaml` sets the repo root to the directory containing `.sdlc/`. Workflow mode is detected by the presence of `state.yaml`, never by a bare `.sdlc/`. `--help` for the script and every verb does no filesystem work and exits 0 from any cwd.

**Exit codes:** reads (`status`, `slate` proposal) `0` always — even for an unknown or malformed sprint id ("no data"); writes `0` ok, `1` illegal / missing precondition / unknown spec / ready gap / DRIFT, `2` refused; `plan` `0` rendered, `1` sprint does not exist. Argparse usage errors exit `2` as argparse does.

---

### generate_sprint_report.py

**Purpose:** Render a sprint's **planning page** (default) or **review page** as one self-contained HTML file — the artifact the team runs the sprint-planning meeting from, and the record it reviews the sprint against (D8). Mirrors `generate_phase_report.py`: inline CSS copied from its palette, no `<script>`, no external URL anywhere; markdown snippets go through `generate_phase_report.md_to_html` so the page shares the phase reports' visual language. Normally written by `sprint.py ready` (planning), re-rendered by `sprint.py plan`, and by `sprint.py close` (review); also a standalone CLI.

**CLI:**

```bash
# Standalone
uv run scripts/generate_sprint_report.py --repo <path> --sprint S07

# Workflow (repo root = parent of .sdlc/)
uv run scripts/generate_sprint_report.py --state .sdlc/state.yaml --sprint S07 [--kind planning|review] [--output PATH]
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--state` | One of `--state`/`--repo` | Path to `.sdlc/state.yaml` (workflow mode) |
| `--repo` | One of `--state`/`--repo` | Target repo root (standalone; default cwd) |
| `--sprint` | Yes | Sprint id, e.g. `S07` (must match `^S\d{2,}$`) |
| `--kind` | No | `planning` (default) or `review` |
| `--output` | No | Output path (default `.sdlc/reports/sprint-SNN-<kind>.html`; a relative path resolves against the repo root) |

**Python API:** `generate(repo_root, sprint_id, kind="planning", output=None, today=None, view=None) -> Path`. Raises `SprintNotFound` (a `ValueError`) for a missing sprint record, `ValueError` for a bad id or kind. The view is `sprint.build_view` (the exact JSON of `sprint.py status --json`), resolved **lazily** at call time via `resolve_build_view()` so `sprint.py` can import this module inside its `ready` / `plan` / `close` functions without a circular import; tests inject `view=` directly. The sprint record is checked before `build_view` is called.

**Sections (proposal §4), in order:**

| Section | Content | Source |
|---------|---------|--------|
| Header | sprint id + Planning/Review; Generated / Project / mode chips; goal, window start → end, state badge, business days total · elapsed · remaining, target, `board_ref` (or "— (manual mapping only)"), readied by `<name> on <date>` (review adds closed by) | sprint record + the ledger's latest `ready` / `closed` event |
| Commitment | the slate: spec, name, risk, type, channel, DoR, eng, data, next owner; "N of M slated specs ready"; per-spec gaps against the ready rule; verdicts pending and handoffs awaiting acknowledgement with business-day age | `build_view` (spec frontmatter + `check_spec`) |
| Mix and capacity | mix string + target ("a count, never a size"); tier target/actual ("no target" when a tier is not in the mix); advisory mix warnings; WIP in flight / WIP cap (`view.wip.cap`, else the bold value on the cadence plan's "WIP cap" line, else "no cap set") / review-turnaround target (only from a cadence-plan line containing "review-turnaround"; bracketed template values read as unset → "no target set") | sprint record, `cadence-plan.md` |
| Build order and next up | the D7 heuristic sentence, the arrow chain, a numbered list with risk/DoR badges, "← depends on …", "· unblocks N"; "Next up: `<id>` `<name>`" with the why, or "no data — no slated spec is READY with merged dependencies inside the WIP cap" | `sprint_model.build_order` / `next_up` |
| Dependencies | spec \| depends on (ids outside the slate badged) \| unblocks; `dependency_gaps` or the all-clear line | `depends_on` |
| Spec cards | one `<article class="card" id="spec-NNNN">` per slated spec from the body at `row.path`: acceptance-check count (`check_spec.list_items`), harness context, source, status, eng/data; Goal, Why, Risk tier, Decision list via `check_spec.extract_section` → `md_to_html` (absent section → "no data — section absent"); DoR blocking findings | spec bodies |
| Open decisions | "Open: n · overdue (2-business-day clock): n"; id \| decision \| owner \| due \| touches slated spec (a spec id appearing in the decision text — advisory substring match); `decisions: null` → "no data — no decision-log found" | `track_decisions` |
| Carried in | spec \| from sprint \| reason | the ledger's `carried` events whose `to_sprint` is this sprint |
| Outcomes (review only, first) | "Kept (merged): n · open at close: n"; the record's `## Close` table as-is; this sprint's `carried` / `dropped` ledger rows (spec, outcome, by, reason, date); "Carry-over recurrence (per spec, 2+ sprints)" — the only cross-sprint number, keyed by spec, never by person | `sprint_model.outcomes`, sprint record, ledger |
| Footer | "Never tracked: velocity, story points, PR count, lines of code." (constant `GUARDRAIL`) | the standard's guardrail |

**Honesty rules:** every empty section, table or series renders "no data" (`None` counts too), never a fabricated zero; no per-person aggregation exists anywhere (names appear only as the recorded by / owner / next-owner strings); the ledger is read tolerantly (malformed lines skipped). Standalone mode's header chip reads "standalone mode — no state.yaml, so the engagement context (phase, profile, gates) is not shown"; the project name is `state.yaml`'s `project_name` in workflow mode, else the repo directory name.

**Output / side effects:** `<repo>/.sdlc/reports/sprint-SNN-planning.html` or `sprint-SNN-review.html` (parent dirs created). **Only if `<repo>/.sdlc/reports/index.html` already exists**, an idempotent block between `<!-- sprints:start -->` and `<!-- sprints:end -->` (inserted before `</body>`, replaced in place on rerun; everything outside the markers byte-identical) listing every `sprint-*-{planning,review}.html` in the reports dir. It never creates `index.html`, never edits `generate_phase_report.py`, and writes nothing else — no `state.yaml`, no ledger, no spec files.

**Key functions:** `generate`, `render_page`, the per-section `render_*`, `splice_sprints_block`, `sprints_block`, `sprint_pages`, `update_index`, `read_ledger`, `latest_event_date`, `cadence_targets`, `is_workflow`, `resolve_repo_root`; constants `KINDS`, `NO_DATA`, `GUARDRAIL`, `SPRINTS_START` / `SPRINTS_END`.

**Exit codes:** `0` (rendered — prints "Sprint S07 planning page written to: <path> (workflow|standalone mode)"), `1` (sprint record missing, invalid sprint id, invalid kind, or `--state` file not found; errors to stderr as `Error: ...`)

---

### retro_report.py

**Purpose:** The read-only cross-ledger retro roll-up behind `/sprd-retro` — what keeps happening, not what is open right now. Four legacy sections read the findings and artifact ledgers (recurring findings as permanent-check candidates, repeat-stale artifacts, the refresh funnel, the combined disposition-debt rollup); two more read `.sdlc/metrics/sprint-log.jsonl` when it exists. Advisory: writes nothing, exit 0 on every path.

**CLI:**

```bash
uv run scripts/retro_report.py --state .sdlc/state.yaml [--window-days 30] [--json]
uv run scripts/retro_report.py --repo <path>
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--state` | One of `--state`/`--repo` | Path to `.sdlc/state.yaml` (workflow mode) |
| `--repo` | One of `--state`/`--repo` | Repo root containing `.sdlc/` (standalone; default cwd) |
| `--window-days` | No | Only count time-stamped ledger events from the last N days (default: all history; an unparseable `ts` is kept) |
| `--json` | No | Emit JSON with per-section `has_data` flags |

**Sprint sections (1.6.0, additive):**

| Section | Content |
|---------|---------|
| **Carry-over recurrence** | `carried` events grouped **by spec**: the number of *distinct* source sprints, which ones, and each carry's `from → to: reason` ("(no reason recorded)" when absent); flagged `RECURRING` at ≥ 2 (`RECURRENCE_THRESHOLD`). This is the only cross-sprint number the standard allows — no kept/carried trend is computed (that would be velocity with the points removed). With a ledger but no carries the block reads "no data", never 0 |
| **Bounce causes** | `verdict: returned` events grouped by `(lane, reason category)` where the category is the lower-cased, whitespace-normalised, trailing-punctuation-stripped reason; rows `{lane, reason, times, specs}` ordered eng then data, then times desc. Rendered in text only when at least one return exists |

Both sections appear in the text report only when the sprint ledger holds at least one event, slotted between the debt block and the footer, so the four legacy sections and the footer are byte-identical with or without a ledger. The ledger's `by` field is never read or emitted; a forbidden activity-metric field smuggled into a ledger line is never aggregated. JSON keys: `has_data`, `recurring_findings`, `repeat_stale`, `refresh_funnel`, `debt`, `window_days`, `carry_over_recurrence`, `bounce_causes`, `sprint_ledger_present`.

**Imports:** `sprint_model` (`LANES`, `normalize_review`) — the retro now depends on `scripts/sprint_model.py` existing.

**Exit codes:** `0` always (advisory — a retro never blocks and never mutates)

---

### doctor.py

**Purpose:** Backs `/sprd-doctor` — a day-1 check that the installed harness will actually run in a repo, not just that it was copied into one. Checks the things that fail quietly: a hook registered with a missing interpreter, a rails script installed without its executable bit, a repo secret the gates need that nobody set.

**CLI:**

```bash
uv run scripts/doctor.py                 # in the client repo
uv run scripts/doctor.py --repo <path>   # check a different repo
uv run scripts/doctor.py --offline       # skip the checks that need gh/az
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--repo` | No | Repo to check (default: current directory) |
| `--offline` | No | Skip the checks that need `gh`/`az` (repo secrets, branch protection) |

**Process:**

1. **`installed_platform(repo)`** reads the composed CI/CD pack id out of `.claude/harness-manifest.json` and returns `"github"` or `"azure-devops"`. Every check below that touches the platform's CLI branches on this instead of a fixed assumption.
2. Runs eight sections in order, printing `PASS`/`FAIL`/`WARN` per line with a `fix:` line attached to anything not `PASS`:
   - **Tools** — required interpreters present (`pwsh`, `uv`, `node`, etc.) plus `gh` on GitHub installs or `az` (+ the `azure-devops` extension) on Azure DevOps installs, never the other
   - **Harness** — the harness was actually installed (`.claude/harness-manifest.json` exists), otherwise the rest of the report is meaningless
   - **Hooks** — registered hooks resolve to a present interpreter
   - **Permissions** — installed rails scripts carry the executable bit (Windows: `WARN`, POSIX permission bits aren't visible there)
   - **Unfinished setup** — residual `<<TOKEN>>` placeholders left in installed files, each mapped to the phase that fills it (`TOKEN_OWNER`); `.azuredevops/` is a scan root alongside `.github/`
   - **MCP** — required MCP servers configured
   - **Repo secrets** *(needs network)* — GitHub: `required_secrets()` reads the names referenced by installed workflows and checks each via `gh secret list`. Azure DevOps: `required_variable_groups()` reads `- group: NAME` references out of the installed pipelines (quote-aware, so a `<<VARIABLE_GROUP>>` sentinel or template expression is reported as unfinished setup rather than a missing group) and checks each via `az pipelines variable-group list`
   - **Branch protection** *(needs network)* — GitHub: the active ruleset. Azure DevOps: `az repos policy list`, where "enforcing" means `isEnabled AND isBlocking` — an enabled-but-optional policy is advice, not a gate
3. Exits `1` if any `FAIL` was recorded (warnings never fail the run); prints a one-line summary either way.

**Platform-aware, not platform-agnostic:** nothing here asks a GitHub repo to authenticate `az`, or an Azure DevOps repo to install `gh`. A repo that `installed_platform()` cannot recognize as Azure DevOps gets the GitHub checks — the same behavior every install had before the CI/CD packs existed.

**Exit codes:** `0` (no failures; warnings may be present), `1` (at least one failure — the harness is not fully working)

---

### code_host.py

**Purpose:** Answer one question every pull-request-facing script asks first: which code host is this repository on, and which CLI talks to it? GitHub (`gh`) and Azure DevOps (`az` with the `azure-devops` extension) are both first-class, and **the repository chooses** — detection keys off the `origin` remote, never a global setting or a profile field (the profile describes the CI pack; the host is a property of the clone). The module is also the documented provider contract: `PROVIDER_FUNCTIONS` names every GitHub function `ado_import.py` mirrors, with its signature and return shape, pinned by `scripts/tests/test_provider_parity.py`.

**Usage:**
```bash
uv run scripts/code_host.py --repo <path> [--json] [--no-probe]
uv run scripts/code_host.py --state .sdlc/state.yaml --json
uv run scripts/code_host.py --repo <path> --host azure-devops --json   # override for this run
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--state` / `--repo` | No | Workflow mode / standalone mode (default: cwd); works with no `.sdlc/` present |
| `--host` | No | `github`, `azure-devops` or `none` — override detection for this invocation |
| `--json` | No | Exactly one JSON document |
| `--no-probe` | No | Skip the local CLI probes (`gh auth status` / `az account show`); `cli_state` reads `unknown` |

**Override precedence** (`detect_host()` reports which one won as `source`): `--host` flag → `SHEPHERD_CODE_HOST` env (or `SDLC_CODE_HOST`, the pre-2.0 name — still read; the new name wins when both are set) → `.sdlc/code-host.yaml` (written by `set_setting.py code-host --host …`; travels with the clone) → the parsed `origin` remote (`code_host_remote.parse_remote`, shared fixture `scripts/tests/fixtures/code_host/remote-urls.json`) → the harness manifest's CI pack as a tie-breaker only when there is no usable remote → `none`. `none` falls through to `gh` (`cli_for("none") == "gh"`), so every repository that existed before this layer behaves exactly as it did.

**Two axes, never merged:** `detect_host()` owns the code host (PRs, identity, policies); `installed_ci_platform()` owns the CI platform (pipeline dirs, runs, secrets) — a ten-line twin of `doctor.installed_platform()` pinned to agree with it, so `doctor.py` is never imported. A GitHub repository on Azure Pipelines is legitimate; nothing resolves the mismatch silently.

**Output:** the `host` block `{name, source, cli, cli_state, detail}` that every host-touching `--json` carries (`host_report.py` renders it from the outcome of the call a script just made, never from a second probe). `cli_state` ∈ `available` / `not_installed` / `extension_missing` / `signed_out` / `unknown`; `detail` names the fix (`run az extension add --name azure-devops`, `run az login`, …) and, on Azure DevOps, the rule that the CLI's **default account decides the token** (a guest identity signs in with `az login --allow-no-subscriptions`; an identity that never opened the organisation in a browser gets HTTP 403 "has not been materialized"). `unknown` is never read as "no".

**Identity:** `resolve_person(roster, identity)` — GitHub: `@` + login when that handle is in the roster; Azure DevOps: the handle whose `people[].email` equals the UPN case-insensitively; otherwise `None`. A provider never guesses a handle from a display name or a UPN prefix.

**Exit codes:** `0` always; `2` on a usage error.

**Consumers:** `spec_status.py`, `handoff.py`, `connection_report.py`, `gate_auth.py`, `pipeline_proof.py` (PR reads), `gate_inventory.py` (CI axis), `import_outcomes.py`, and Shepherd (the desktop app), which reads the block before enabling a PR feature and shows the `detail` as the reason a control is off.

---

### ado_import.py

**Purpose:** The Azure DevOps provider — the `az` twin of every `gh` read and write the plugin makes, returning **the same dict shapes `gh` returns today** so the pure models (`spec_status`'s verdict parser, `pipeline_proof_model`, `github_import.map_*`) are reused verbatim rather than re-implemented. A library module with no CLI; the consuming scripts dispatch to it at their own call sites when `code_host.detect_host()` says `azure-devops`, which is why the existing GitHub monkeypatch seams and every existing test are untouched.

**Shape:** `ado_import.py` holds the PR-side fetchers (`whoami`, `repo_view`, `find_pr_for_branch`, `fetch_pr_comment_bodies`, `fetch_pr_events`, `fetch_all_pull_requests`, `fetch_pr_checks`, `fetch_branch_policies`, `create_draft_pr`, `complete_pr`); `ado_pipelines.py` the pipeline side (`fetch_runs`, `run_jobs`, `secret_names` from variable groups); `ado_map.py` the **pure** translators (`map_pr`, `map_checks`, `map_reviews`, `map_runs`, `map_jobs`, `map_policies`, `map_threads` — az document in, gh-shaped dict out, no subprocess); `ado_transport.py` the one impure seam (`run_az` / `az_json`: UTF-8 forced, 60 s timeout, `AZURE_EXTENSION_USE_DYNAMIC_INSTALL=no` and `AZURE_CORE_COLLECT_TELEMETRY=no` on every spawn, always `--only-show-errors --detect false --org --project [--repository]` from the parsed remote). `AZ_CONTRACT` lists every argv prefix; `test_az_contract.py` checks each against local `az … --help` and skips cleanly when the extension is absent.

**Errors:** `AdoImportError` **is a subclass of** `github_import.GitHubImportError`, so every existing `except GitHubImportError` — including the frozen `scorecard.py` — already catches an `az` failure. A normaliser that meets an az document missing a key it needs raises rather than defaulting, because a default is how "nothing here" gets fabricated from a field rename.

**Honesty inside the shapes:** `updatedAt = None` and `reviews[].submittedAt = None` (Azure DevOps has no such fields); `author.login` is the UPN and `handle` is set only when the roster resolves it; an unknown enum maps to the conservative reading and leaves a `_notes[]` entry; bulk rows past the checks cap carry `_checks_unavailable: True`; `files = None` when iterations were not fetched. On hand-off the checker is `--required-reviewers <roster email>` and the developer is named in the description (no assignee on Azure DevOps); a missing email is the caller's `assignment_error`, never a failed local half.

**Fixtures:** `scripts/tests/fixtures/code_host/azure_devops/captured/*.json` is real `az` output captured 2026-10-05 and anonymised (wrapped `{_provenance, _command, _secs, value}`; `CAPTURE-NOTES.md` records every fact it settled — `isRequired` is `null` not `false`, `lastMergeCommit` sits on every active PR, system-comment prose is never parsed, environments need `--api-version 7.1-preview` exactly). The hand-written documents one directory up stay marked `hand-written (unverified)`; `tests/ado_fixtures.load(name)` prefers the captured file and `test_fixture_provenance.py` lists what is still unverified.

---

### import_outcomes.py

**Purpose:** The host-neutral `scorecard.py import`. `scorecard.py` is protected and knows only GitHub, so this verb sits beside it: on GitHub (and `none`) it calls the frozen `scorecard.import_events` literally — no second GitHub import exists; on Azure DevOps it runs `ado_outcomes.collect_report` (PR completions, vote threads, environment deployment records, `incident`-tagged Bugs → the same event shapes through `github_import.map_*`), deduplicates on `gh_id` against the existing ledger and appends with `scorecard.append_events`. `ado-*` ids (`ado-pr-merge:<id>`, `ado-pr-review:<id>`, `ado-deploy:<env>:<rec>`, `ado-wi:<id>`) never collide with `gh-*`, so one ledger carries both hosts' history.

**Usage:**
```bash
uv run scripts/import_outcomes.py --repo <path> --since 2026-09-01 [--json]
uv run scripts/import_outcomes.py --state .sdlc/state.yaml --since 2026-09-01 --host azure-devops
```

**Arguments:**

| Argument | Required | Description |
|----------|----------|-------------|
| `--state` / `--repo` | No | Workflow / standalone (default: cwd; the ledger is created if absent) |
| `--since` | Yes | Only activity on/after this date (`YYYY-MM-DD`) |
| `--host` | No | Override code-host detection for this run (flag > env > `.sdlc/code-host.yaml` > origin) |
| `--json` | No | One JSON document carrying the top-level `host` block |

**Honest by design:** output phrasing matches `scorecard.py import` ("Imported: no data" / "Imported N event(s): …" / "Error: …" exit 1). What Azure DevOps cannot record is **said, never zeroed**: a vote with no thread leaves `accepted_as_is` unknown rather than `true`; a `review_wait` with no request timestamp has no `wait_hours` key (omitted, never `None`) and is counted on its own line; a category that could not be read reports "not imported (…)" and contributes nothing. Nothing is written until every category has been read, so a failure leaves the ledger exactly as it was. `scorecard.py`, `github_import.py` and hand-recording with `record` are unchanged.

---

## 4. Dependencies

Defined in `scripts/pyproject.toml`:

```toml
[project]
name = "shepherd-scripts"
version = "0.1.0"
description = "Automation scripts for the Shepherd plugin"
requires-python = ">=3.12"
dependencies = [
    "pyyaml>=6.0",
    "jsonschema>=4.20",
]

[project.optional-dependencies]
test = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
]
```

| Dependency | Version | Purpose |
|------------|---------|---------|
| **PyYAML** | >=6.0 | YAML parsing and serialization for `state.yaml`, `profile.yaml`, `phase-registry.yaml`, and compliance gate files |
| **jsonschema** | >=4.20 | JSON Schema validation (available for structured validation beyond YAML) |
| **pytest** | >=7.0 (dev) | Test runner for script unit tests |
| **pytest-cov** | >=4.0 (dev) | Coverage reporting for pytest |
| **Python** | >=3.12 | Required for modern type hint syntax (`Path \| None`, `list[str]`) |

**Build system:** Hatchling (`hatchling.build`)

**Test configuration:** Tests live in `scripts/tests/`, run with `uv run pytest` or `uv run pytest --cov`.

---

## 5. Error Handling

All scripts follow consistent error handling conventions:

- **Errors to stderr:** Critical errors are written to `sys.stderr` (some scripts use `print(..., file=sys.stderr)`)
- **Structured messages:** Error messages include file paths and field names for easy debugging:
  ```
  Error: State file not found: /path/to/.sdlc/state.yaml
  Error: requirements.md not found or empty in 01-requirements/
  company: missing required field 'profile_id'
  ```
- **Non-zero exit codes:** All failures produce exit code `1` (or `2` for configuration errors in `advance_phase.py`), propagated to the calling command
- **Graceful degradation:** Where possible, scripts continue with warnings rather than hard failures:
  - `init_project.py` warns and skips if `.sdlc/` exists
  - `synthesize_spec.py` treats Phase 0 artifacts as optional
  - `map_deep_plan_artifacts.py` warns on missing section files and skips them
  - `generate_phase_report.py` shows placeholder sections for missing artifacts
  - `sprint.py ready` / `close` warn (and still exit 0) when the sprint page fails to render — `sprint.py plan` re-renders it; a failed *ledger* append, by contrast, is loud (`DRIFT`, exit 1) because it means the frontmatter and the ledger disagree
- **YAML round-trip safety:** State updates use `yaml.dump()` with `default_flow_style=False` and `allow_unicode=True` to preserve human readability

---

## 6. Cross-References

| Document | Relationship |
|----------|-------------|
| [commands.md](commands.md) | Documents which slash commands invoke which scripts |
| [gate-system.md](gate-system.md) | Detailed gate semantics and severity rules |
| [architecture.md](architecture.md) | Overall plugin architecture and data flow |
| [profiles.md](profiles.md) | Profile YAML structure and schema reference |
| `phases/phase-registry.yaml` | Phase definitions consumed by `check_gates.py` and `advance_phase.py` |
| `scripts/phase_model.py` | Single source of truth for phase ids, order, and slugs (reads `phase-registry.yaml`) |
| `profiles/_schema.yaml` | Schema consumed by `validate_profile.py` |
| `templates/state-init.yaml` | State template consumed by `init_project.py` |
| `templates/phases/03-foundation/section-plans/SECTION-template-deep-plan.md` | Converged template consumed by `map_deep_plan_artifacts.py` |
| `templates/phases/build/sprint.md` | Sprint-record template rendered by `sprint.py new` into `.sdlc/sprints/SNN.md` |
| `scripts/sprint_model.py` | Pure rules of the sprint layer (mix, slate proposal, ready rule, build order, frontmatter writer, `FORBIDDEN_FIELDS`) consumed by `sprint.py`, `generate_sprint_report.py`, `retro_report.py` |
| [references/sprint-model.md](../references/sprint-model.md) | The sprint lifecycle, the ready rule, the mix, the ledger, and the metrics policy behind `sprint.py` |
