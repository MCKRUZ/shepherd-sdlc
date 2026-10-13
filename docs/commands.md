# Slash Commands Reference

Comprehensive documentation for all slash commands provided by the Shepherd plugin. These commands orchestrate the full Software Development Lifecycle within Claude Code, managing phase transitions, gate validation, reporting, and process auditing.

---

## Table of Contents

- [Command Overview Table](#command-overview-table)
- [/sprd-setup -- Interactive Setup Wizard](#sprd-setup----interactive-setup-wizard)
- [/sprd -- Phase Guidance](#sprd----phase-guidance)
- [/sprd-status -- Progress Dashboard](#sprd-status----progress-dashboard)
- [/sprd-gate -- Exit Criteria Check](#sprd-gate----exit-criteria-check)
- [/sprd-next -- Advance to Next Phase](#sprd-next----advance-to-next-phase)
- [/sprd-phase-report -- Generate Phase HTML Report](#sprd-phase-report----generate-phase-html-report)
- [/sprd-audit -- Gate Effectiveness Analysis](#sprd-audit----gate-effectiveness-analysis)
- [/sprd-enhance -- Narrative Companions](#sprd-enhance----narrative-companions)
- [/sprd-coach -- Interactive Phase Coaching](#sprd-coach----interactive-phase-coaching)
- [/sprd-review -- Multi-Perspective Review](#sprd-review----multi-perspective-review)
- [/sprd-intake -- Document Corpus Intake](#sprd-intake----document-corpus-intake)
- [/sprd-brief -- Discovery Workshop Brief](#sprd-brief----discovery-workshop-brief)
- [/sprd-spec -- Author a Ready Spec](#sprd-spec----author-a-ready-spec)
- [/sprd-sprint -- Sprint Board](#sprd-sprint----sprint-board)
- [/sprd-refine -- Refinement Agenda](#sprd-refine----refinement-agenda)
- [Additional Commands (summaries)](#additional-commands-summaries)
- [Command Interaction Flow](#command-interaction-flow)
- [Python Script Invocation](#python-script-invocation)
- [Cross-References](#cross-references)

---

## Command Overview Table

| Command | Purpose | Modifies State | Typical Usage |
|---------|---------|:--------------:|---------------|
| `/sprd-setup` | Initialize SDLC for a project | Yes -- creates `.sdlc/` | Once per project, at the very start |
| `/sprd` | Show current phase guidance | No | Start of each work session |
| `/sprd-status` | Display progress dashboard | No | Anytime -- quick status check |
| `/sprd-gate` | Run 7-gate exit criteria check | Yes -- records `gate_results` | Before attempting to advance phases |
| `/sprd-next` | Run gates + advance phase | Yes -- advances `current_phase` | When ready to move to the next phase |
| `/sprd-phase-report` | Generate HTML report | No | Stakeholder reviews, documentation |
| `/sprd-audit` | Analyze gate effectiveness | No | After 3-4+ completed phases |
| `/sprd-enhance` | Generate stakeholder narrative companions | No | Before stakeholder reviews and phase transitions |
| `/sprd-coach` | Adaptive coaching dialogue for the current phase | No | When you want guided conversation instead of the step list |
| `/sprd-review` | Multi-perspective artifact review (council / adversarial / edge-cases) | No | Before `/sprd-gate` on design-heavy phases (2, 3, build) |
| `/sprd-intake` | Catalog + summarize the document corpus | Writes intake summaries/registry | Phase 0 Step 0c, when the profile has a `documentation` section; also runs standalone via `--docs` |
| `/sprd-brief` | Analyze intake corpus + draft workshop brief | No | Phase 0 Step 0d, before a stakeholder workshop; also runs standalone via `--docs` |
| `/sprd-spec` | Author a ready spec (scaffold → DoR → human risk tier) | Writes `specs/NNNN-name.md`; logs spec metrics | The Build-loop Intent beat, before building any change; also runs standalone via `--repo` |
| `/sprd-sprint` | Sprint board — slate a count of specs by risk-tier mix, ready the sprint (DoR + Eng/Data verdicts), show build order and next-up, close with kept / carried / dropped | Writes `.sdlc/sprints/SNN.md`, the five optional spec sprint keys, `sprint-log.jsonl`, sprint pages; **never `state.yaml`** | Any phase where specs exist; daily `status`, `ready` at sprint planning, `close` on the last day; also standalone via `--repo` |
| `/sprd-refine` | Refinement agenda and per-spec refinement for the sprint's slate; records Eng/Data verdicts; routes upstream fixes without regressing a phase | Writes spec bodies via `/sprd-spec`, `eng_review`/`data_review` keys, `DL-NN` decisions; **never `state.yaml`** | The Mon/Wed/Fri cross-functional review and the weekly Intent triage; also standalone via `--repo` |
| `/sprd-handoff` | Hand a ready spec to a developer in one step | Writes the branch + `status`/`developer` frontmatter commit; assigns on the code host (GitHub via `gh`, Azure DevOps via `az` — chosen by the `origin` remote) | The Build-loop Delegate beat, right after `/sprd-spec`; also runs standalone via `--repo` |
| `/sprd-spec-status` | Report a spec's status read from its pull request, on GitHub or Azure DevOps | Writes `status: merged` on the default branch, once, when the PR has actually merged (`--all` never writes) | The Build-loop Discern beat, to see where a change is and who it's waiting on; also runs standalone via `--repo` |
| `/sprd-spike` | Open a bounded spike for a question nobody can answer yet | Writes `spikes/NNNN-name.md` | When a story fails the Definition of Ready because the ground truth is unknown, not because the spec is badly written |
| `/sprd-doctor` | Day-1 environment check — proves the installed harness can actually run here; pack-aware, checks `gh` on GitHub installs and `az` on Azure DevOps installs, never the other (the PR-facing commands pick their CLI from the `origin` remote instead) | No | After `/sprd-setup`, when onboarding a second developer, and any time a gate behaves inexplicably |

---

## /sprd-setup -- Interactive Setup Wizard

### What It Does

Initializes the SDLC lifecycle management structure for a target project. This is the first command to run and is required before any other `/sprd-*` command will function. It creates the `.sdlc/` directory, selects and validates a profile, and configures the project's `CLAUDE.md` with SDLC context.

### Arguments

None. The command is fully interactive.

### Internal Flow

**Step 1: Check Existing Setup**
The command looks for `.sdlc/state.yaml` in the current directory. If it already exists, the user is warned that SDLC is already initialized and presented with two options: view status via `/sprd-status`, or re-initialize (destructive, requires explicit confirmation).

**Step 2: Profile Selection**
Available profiles are listed from the plugin's `profiles/` directory (excluding `_schema.yaml`). Current built-in profiles:

- **microsoft-enterprise** -- C#/.NET 10 + Angular 22 + Azure, SOC 2 compliance, 80% coverage minimum, TDD required.
- **ado-enterprise** -- microsoft-enterprise's stack on Azure Repos + Azure Pipelines; SOC 2 compliance, 80% coverage minimum, TDD required.
- **ado-enterprise-python** -- ado-enterprise's Python sibling: FastAPI + SQLAlchemy + React/Redux Toolkit on the same Azure Repos + Azure Pipelines rails; SOC 2, 80% coverage, TDD required.
- **starter** -- Minimal profile with no compliance gates; a quick start suitable for any stack.

**Step 3: Project Configuration**
The user is prompted for:
- **Project name** (defaults to the current directory name).
- Confirmation that the selected profile settings are appropriate.
- **Database engine** (ado-enterprise-python only): Azure Database for PostgreSQL (default) or Azure SQL. The choice is applied after init — the wizard edits the frozen `.sdlc/profile.yaml` before the harness install re-validates it, and rewrites the Database line in the project's CLAUDE.md after the template append. Advisory metadata only: pack selection never reads the engine, and Alembic is the migration tool either way.

**Step 4: Initialize .sdlc/ Directory**
The init script is invoked:
```bash
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/init_project.py \
  --profile ${CLAUDE_PLUGIN_ROOT}/profiles/<selected-profile>/profile.yaml \
  --target . \
  --name "<project-name>"
```

This creates the following structure:
```
.sdlc/
  state.yaml          # Phase tracking (Phase 0: Discovery active)
  profile.yaml        # Frozen copy of the selected profile
  constitution.md     # Project constitution
  artifacts/          # Per-phase artifact directories (one per phase slug: 00-discovery, 01-requirements, 02-design, 03-foundation, build, 07-documentation, 08-deployment, 09-monitoring, close)
```

**Step 5: Update CLAUDE.md**
The profile's `claude-md-template.md` contents are appended to the project's `CLAUDE.md`. If `CLAUDE.md` does not exist, it is created.

**Step 6: Confirmation Display**
A summary is shown:
```
SDLC initialized successfully!

Profile: <profile-id>
Phase: 0 -- Discovery (active)
Artifacts: .sdlc/artifacts/00-discovery/

Next steps:
1. Run /sprd to see Phase 0 guidance
2. Create your problem statement in .sdlc/artifacts/00-discovery/problem-statement.md
3. Run /sprd-gate when ready to check exit criteria
4. Run /sprd-next to advance to Phase 1
```

**Step 7: Post-Init Validation**
The profile validator runs against the frozen copy to confirm setup health:
```bash
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/validate_profile.py .sdlc/profile.yaml
```

### State Changes

- Creates `.sdlc/state.yaml` with `current_phase: 0` and Phase 0 status set to `active`.
- Creates `.sdlc/profile.yaml` (frozen profile copy).
- Creates `.sdlc/constitution.md`.
- Creates `.sdlc/artifacts/` with one subdirectory per phase slug (`00-discovery`, `01-requirements`, `02-design`, `03-foundation`, `build`, `07-documentation`, `08-deployment`, `09-monitoring`, `close`).
- Appends SDLC context to the target project's `CLAUDE.md`.

### Python Scripts Called

| Script | Purpose |
|--------|---------|
| `init_project.py` | Creates the `.sdlc/` directory structure and initial `state.yaml` |
| `validate_profile.py` | Validates the frozen profile against `_schema.yaml` |

### Error Scenarios

| Scenario | Behavior |
|----------|----------|
| `uv` not installed | Instructs user to install via `pip install uv` or `brew install uv` |
| Profile validation fails | Displays specific validation errors and suggests fixes |
| Directory permissions error | Reports the OS-level error clearly |
| Already initialized | Warns user; offers view-status or destructive re-init with confirmation |

---

## /sprd -- Phase Guidance

### What It Does

Displays actionable guidance for the current (or specified) SDLC phase. This is the primary orientation command -- it tells you what to do, which skills to use, which artifacts to produce, and what the exit criteria are. It is read-only and never modifies state.

### Arguments

| Argument | Description |
|----------|-------------|
| *(none)* | Show guidance for the current phase |
| `<phase-number>` | Show guidance for a specific phase (e.g., `/sprd 3`) |

### Internal Flow

1. **Locate state:** Read `.sdlc/state.yaml`. If missing, instruct user to run `/sprd-setup`.
2. **Read state:** Extract `current_phase` (or use the argument-specified phase).
3. **Load phase definition:** Read the corresponding `phases/XX-phasename.md` file from the plugin.
4. **Load profile:** Read `.sdlc/profile.yaml` for stack and quality configuration.
5. **Display phase context** with the following sections:

### Output Sections

**Header** -- Phase number, name, and active profile ID.

**Purpose** -- One-line description of the phase's goal.

**Resolved Questions from Previous Phase** -- Checks the previous phase's handoff document for a "Resolved Questions" section. If present, lists them as confirmed inputs that MUST inform the current phase's artifacts. If absent, notes that and continues.

**What to Do Next** -- Actionable next steps based on the phase workflow, current artifact state, and resolved questions. References specific skills and commands. Example: *"Write `requirements.md` using resolved questions RQ-1 through RQ-3 as inputs."*

**Required Artifacts** -- A checklist with existence and size status:
```
[x] artifact.md (exists, 1.2KB)
[ ] other-artifact.md (missing)
```

**Skills to Use** -- Primary and secondary skills relevant to the phase.

**Exit Criteria** -- Summary of conditions required to advance, sourced from the phase definition.

**Quick Commands** -- Reminder block:
```
/sprd-gate    -- Check if exit criteria are met
/sprd-next    -- Advance to next phase (runs gate check)
/sprd-status  -- View full progress dashboard
```

**Compliance Callout** -- If the active profile includes compliance frameworks (e.g., SOC 2), any compliance-specific requirements for the phase are highlighted.

### State Changes

None. This command is purely informational.

### When to Use

- At the start of any work session to orient yourself.
- When you need to know what artifact to produce next.
- When reviewing requirements for a phase you haven't started yet (using the phase-number argument).

---

## /sprd-status -- Progress Dashboard

### What It Does

Generates and displays a progress dashboard showing overall SDLC status: current phase, completion percentages, artifact counts, and transition history. This is the quick-glance command for understanding where the project stands.

### Arguments

None.

### Internal Flow

1. **Locate state:** Read `.sdlc/state.yaml`. If missing, instruct user to run `/sprd-setup`.
2. **Read state:** Load current phase, all phase statuses, and transition history.
3. **Generate dashboard:** Execute:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/generate_status.py \
     --state .sdlc/state.yaml
   ```
4. **Display dashboard** with:
   - Current phase name and number.
   - Progress bar (completed phases / total phases).
   - Phase table with status indicators, artifact counts, and timestamps.
   - Recent transition history (if any phase transitions have occurred).
5. **Suggest next action** based on current status:
   - Phase is `active`: suggest `/sprd` for guidance.
   - All gates would pass: suggest `/sprd-next` to advance.
   - Artifacts are missing: list what is needed.
6. **Sprint line (additive, 1.6.0):** read `sprint.py status --json` and print one line — `Sprint S07 (ends 2026-10-09): 6 slated · 4 ready · 1 verdict pending · 2 handoffs unacknowledged` — skipped silently when the view's `sprint` is `null` (no sprint exists). Read-only; it never changes the dashboard's phase table.

### Output Format

A concise markdown table designed to fit on one screen. Generated by `generate_status.py`.

### State Changes

None. This command is purely informational.

### Python Scripts Called

| Script | Purpose |
|--------|---------|
| `generate_status.py` | Reads `state.yaml` and produces the formatted dashboard |
| `sprint.py status --json` | The active sprint's slate, readiness, verdicts and handoffs (one additive line; silent when no sprint exists) |

---

## /sprd-gate -- Exit Criteria Check

### What It Does

Runs the 7-gate validation system against the current (or specified) phase to determine readiness for advancement. Generates an HTML report and opens it in the default browser. Records gate results in state but does NOT advance the phase -- that is exclusively `/sprd-next`'s responsibility.

### The 7-Gate System

| Gate | Name | What It Validates |
|------|------|-------------------|
| G1 | Integrity | Artifact structure and format correctness |
| G2 | Completeness | All required artifacts exist with sufficient content |
| G3 | Metrics | Quantitative thresholds (coverage, size, counts) |
| G4 | Compliance | Regulatory and framework-specific requirements |
| G5 | Cross-Phase Consistency | Detects drift in locked metrics across phase transitions (budget, timeline, scope, stakeholder roster, quality thresholds, compliance reqs). Warns but does not block. |
| G6 | Quality | Content quality, consistency, and cross-references |
| G7 | Exit criteria | The phase's declared `exit_gate.conditions[]` prose checks, rendered for the human who signs. Always REVIEW — never blocks. |

Each gate reports one of three statuses:
- **PASS** -- Criteria fully satisfied.
- **FAIL** -- Criteria not met; includes details on what failed.
- **MANUAL** -- Requires human review and sign-off.

Each gate also has a severity level:
- **MUST** -- Blocking. Phase cannot advance if this gate fails.
- **SHOULD** -- Warning. Phase can advance but issues are flagged.
- **MAY** -- Advisory. Informational only.

### Arguments

| Argument | Description |
|----------|-------------|
| *(none)* | Check the current phase |
| `<phase-number>` | Check a specific phase (e.g., `/sprd-gate 2`) |

### Internal Flow

1. **Locate state:** Read `.sdlc/state.yaml`. If missing, instruct user to run `/sprd-setup`.
2. **Read state:** Determine the current phase (or use the argument-specified phase).
3. **Run gate checks:**
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/check_gates.py \
     --state .sdlc/state.yaml
   ```
   Optionally with `--phase <N>` for a specific phase.
4. **Display results:** For each of the 7 gates, show: gate name, PASS/FAIL/MANUAL status, severity (MUST/SHOULD/MAY), and specific details.
5. **Generate HTML report:**
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/generate_phase_report.py \
     --state .sdlc/state.yaml --phase <phase-number>
   ```
6. **Open report** in the default browser (`start` on Windows, `open` on macOS, `xdg-open` on Linux).
7. **Summarize** with counts of passed/failed/manual checks and an overall verdict:
   - **BLOCKED** -- Any MUST gate failed. Lists specific blockers with remediation suggestions.
   - **REVIEW NEEDED** -- Only manual checks remain. Reminds user to share the HTML report for stakeholder sign-off.
   - **READY** -- All gates pass. Suggests running `/sprd-next` to advance.
8. **Update state:** Record gate results in `.sdlc/state.yaml` under the current phase's `gate_results` field.

### State Changes

- Writes `gate_results` to the current phase entry in `state.yaml`.
- Generates `.sdlc/reports/<slug>-report.html` (registry slug, e.g. `00-discovery-report.html`, `build-report.html`).
- Does NOT modify `current_phase`.

### Python Scripts Called

| Script | Purpose |
|--------|---------|
| `check_gates.py` | Runs all 7 gates and returns structured results |
| `generate_phase_report.py` | Renders artifacts and gate results into a self-contained HTML report |

### Important Distinction

This command is **read-only with respect to phase transitions**. It records gate results but never changes `current_phase`. To actually advance, use `/sprd-next`.

---

## /sprd-next -- Advance to Next Phase

### What It Does

The most consequential command in the SDLC plugin. It runs gate checks, enforces a blocking Human-in-the-Loop (HITL) gate for open questions, advances the phase if all MUST gates pass and the user confirms, and then displays guidance for the new phase.

### Arguments

None. Always operates on the current phase.

### Internal Flow

**Step 1-2: Locate and Read State**
Standard state file lookup from `.sdlc/state.yaml`.

**Step 3: Run Gate Checks**
```bash
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/check_gates.py \
  --state .sdlc/state.yaml
```

**Step 4: Evaluate Gate Results**

*If ANY MUST gate fails:*
- Display the failure report with specific blockers and remediation suggestions.
- Generate and open the HTML phase report (to show what is missing).
- Do NOT advance the phase.

*If all MUST gates pass (SHOULD/MAY may still have warnings):*
- Display success message and any remaining warnings.
- Generate and open the HTML phase report.
- Proceed to the HITL gate (Step 5).

**Step 5: HITL Gate -- Explicit Sign-Off**
Present a phase summary (what was produced, key decisions made) and ask: *"Does this look correct? Shall I advance to Phase N?"* The `advance_phase.py` script is NOT called until the human explicitly confirms.

**Step 6: Advance Phase**
Update `.sdlc/state.yaml`:
- Set current phase status to `completed` with `completed_at` timestamp.
- Set next phase status to `active` with `entered_at` timestamp.
- Set `current_phase` to the next phase by registry order (ids may be strings: `build`, `close` -- not id+1); update `phase_name`.
- Append transition to the `history` array:
  ```yaml
  - from: <current_phase_id>
    to: <next_phase_id>
    at: "<ISO 8601 timestamp>"
    gate_results: { <summary of pass/fail> }
  ```

**Step 7: BLOCKING HITL Gate -- Resolve Open Questions**

This gate is **MANDATORY** and **BLOCKING**. It MUST be completed before any new-phase work begins. There are no exceptions.

Procedure:
1. Read the handoff document produced by the phase just completed (e.g., `phase2-handoff.md`).
2. Extract ALL Q-NN or AQ-NN items listed under "Open Questions", "What X Must Address", or similar headings.
3. Display them in a prominent block:

   ```
   ---------------------------------------------------------------
   BLOCKING: OPEN QUESTIONS MUST BE RESOLVED BEFORE PHASE N BEGINS

   The following questions were raised during the previous phase.
   You MUST answer or confirm defaults for every item below.
   No artifacts will be written until all are resolved.

   | ID    | Question       | Needed by        | Proposed default    |
   |-------|----------------|------------------|---------------------|
   | AQ-01 | [question]     | [who/what]       | [proposed default]  |
   | AQ-02 | [question]     | [who/what]       | [proposed default]  |

   For each question: confirm the default, adjust it, or provide
   your own answer.
   ---------------------------------------------------------------
   ```

4. A reasonable default is proposed for every question based on project context (state, previous handoffs, artifacts, profile). Questions are never left without a proposed default.
5. **Execution halts.** No artifacts are written, no summaries of next steps are provided. The command waits for the user to respond.
6. Once the user confirms or provides answers, resolutions are recorded in the handoff document under a "Resolved Questions" section with timestamps.
7. Only after every open question is resolved does the command proceed.

If there are no open questions in the handoff document, the command explicitly states: *"No open questions found in the handoff. Proceeding to phase guidance."*

**Step 8: Show Next Phase Guidance**
After advancement and HITL resolution, display:
- New phase name and description.
- Primary skills to use.
- Required artifacts to produce.
- Entry criteria (already met by advancing).
- Reference to the phase definition file for full details.

**Step 9: Edge Case -- Final Phase Completion**
When the terminal phase (Phase C: Close & Transfer) passes its close gate, the project is complete. The user is congratulated and informed about post-SDLC re-entry points for future work.

### State Changes

- Updates `gate_results` for the current phase.
- Sets current phase status to `completed` with timestamp.
- Sets next phase status to `active` with timestamp.
- Advances `current_phase` to the next phase by registry order and updates `phase_name`.
- Appends to the `history` array.
- Updates handoff documents with resolved questions.
- Generates `.sdlc/reports/<slug>-report.html` (registry slug, e.g. `00-discovery-report.html`, `build-report.html`).

### Python Scripts Called

| Script | Purpose |
|--------|---------|
| `check_gates.py` | Runs the 7-gate validation system |
| `advance_phase.py` | Updates `state.yaml` with phase transition (called with `--confirmed`) |
| `generate_phase_report.py` | Generates the HTML report before advancement |

### Critical Notes

- Gate checks are mandatory. There is no `--force` flag. For exceptional cases, use the override protocol documented in `references/validation-rules.md`.
- The HITL gate in Step 7 is **non-negotiable**. Open questions MUST be surfaced with proposed defaults and resolved with user confirmation before any new-phase artifact work begins. Skipping this gate undermines the entire HITL workflow.

---

## /sprd-phase-report -- Generate Phase HTML Report

### What It Does

Renders all artifacts for a specified phase (or all phases) into a self-contained HTML report suitable for stakeholder review. Reports include dark-theme styling, Mermaid.js diagram rendering, and gate status indicators. No web server is required -- reports open directly in a browser.

### Arguments

| Argument | Description |
|----------|-------------|
| *(none)* | Generate report for the current phase |
| `<phase-id>` | Generate report for a specific phase (any phase id: 0,1,2,3,build,7,8,9,close) |
| `--all` | Generate individual reports for all phases (any phase id: 0,1,2,3,build,7,8,9,close) plus an `index.html` |

### Internal Flow

1. **Locate state:** Read `.sdlc/state.yaml`. If missing, instruct user to run `/sprd-setup`.
2. **Determine target phase:** Use `current_phase` from state if no argument provided; validate the phase id against the registry.
3. **Run report generator:**

   For a single phase:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/generate_phase_report.py \
     --state .sdlc/state.yaml \
     --phase <phase-id>
   ```

   Output defaults to `.sdlc/reports/<slug>-report.html` (registry slug, e.g. `00-discovery-report.html`).

   For all phases:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/generate_phase_report.py \
     --state .sdlc/state.yaml \
     --all
   ```

4. **Open in browser** automatically (`start` on Windows, `open` on macOS, `xdg-open` on Linux).
5. **Show artifact inventory:** After generating, list:
   - Which required artifacts were found and rendered.
   - Which required artifacts were missing (shown as placeholder sections in the report).
   - Exit gate status (pass/fail/incomplete).

### Output Location

Reports are written to `.sdlc/reports/` in the target project:
- `<slug>-report.html` -- Individual phase report (registry slug, e.g. `00-discovery-report.html`, `build-report.html`).
- `index.html` -- Full project report (generated with `--all`).

### Report Characteristics

- **Self-contained:** All CSS and JavaScript are inlined. A single HTML file with no external dependencies.
- **Dark theme:** Styled for comfortable reading.
- **Mermaid.js diagrams:** Any Mermaid diagram blocks in artifacts are rendered as interactive SVGs.
- **Missing artifacts:** Displayed as labeled placeholder sections, not errors.
- **Gate status:** Included to show phase readiness at the time of report generation.

### State Changes

None. This command generates files but does not modify `state.yaml`.

### Python Scripts Called

| Script | Purpose |
|--------|---------|
| `generate_phase_report.py` | Converts artifacts and gate data into self-contained HTML |

---

## /sprd-audit -- Gate Effectiveness Analysis

### What It Does

Analyzes gate pass/fail patterns across all completed phases to identify which gates are useful and which are candidates for calibration. This is a process improvement tool -- it helps you tune the SDLC to your actual project needs rather than relying on defaults.

### Arguments

| Argument | Description |
|----------|-------------|
| *(none)* | Audit the current project |
| `--compare <path>` | Compare gate effectiveness with another project's `state.yaml` |

### Internal Flow

1. **Locate state:** Read `.sdlc/state.yaml`. If missing, instruct user to run `/sprd-setup`.
2. **Read state:** Extract `gate_results` from every completed phase.
3. **Run audit analysis:**
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_gates.py \
     --state .sdlc/state.yaml
   ```
4. **Display results** with the following sections:

**Gate Effectiveness Summary** -- Table of every gate checked, how many times it ran, and how many times it failed.

**Always-Pass Gates** -- Gates that never failed across all phases. These are candidates for removal (if they never catch anything, they may not be adding value) or tightening (thresholds may be too lenient).

**High-Fail Gates** -- Gates that failed frequently. These may indicate systemic process issues (the team consistently struggles with certain criteria) or overly strict thresholds that need adjustment.

**Override History** -- Any gates that were overridden using the override protocol, including the justification text provided at override time.

**Recommendations** -- Suggested actions based on the analysis patterns.

5. **Cross-project comparison:** If `--compare <other-state.yaml>` is provided, the audit compares gate effectiveness between two projects, highlighting where profiles differ in strictness.

### Prerequisites

Useful auditing requires at least 3-4 completed phases to produce meaningful data. If fewer phases are complete, the command warns that results may not be representative.

### State Changes

None. This command is purely analytical and never modifies state.

### Python Scripts Called

| Script | Purpose |
|--------|---------|
| `audit_gates.py` | Reads gate history from `state.yaml` and produces the effectiveness report |

---

## /sprd-enhance -- Narrative Companions

### What It Does

Generates stakeholder-friendly `.narrative.md` companions for the current phase's technical artifacts. Spawns `narrative-enhancer` agents in parallel (one per artifact); each writes `{artifact-name}.narrative.md` alongside its source following `references/narrative-patterns.md` (executive summary, detailed prose, key decisions in business terms, impact assessment).

### Arguments

- No arguments: enhance all artifacts in the current phase
- `[path]`: enhance a specific artifact
- `--force`: regenerate even if narratives exist
- `--all-phases`: enhance across all completed phases

### State Changes

None. Narratives are optional — `/sprd-gate` does not require them. The technical artifact remains the source of truth.

### When to Use

Before stakeholder reviews, steering meetings, and phase transitions.

---

## /sprd-coach -- Interactive Phase Coaching

### What It Does

Starts or continues an adaptive coaching dialogue for the current phase instead of the rigid step list. Assesses artifact state (none / partial / complete), then opens in the matching mode: diagnostic questions to begin, gap-targeted questions mid-phase, or a ready-check that points to `/sprd-gate`. After each significant exchange it updates the relevant artifact so progress survives the session — the conversation is ephemeral, the artifacts are the record.

### Arguments

None. Mode is derived from artifact state. Coaching patterns come from `references/conversational-coaching.md`.

### State Changes

None directly; artifacts in `.sdlc/artifacts/{NN}-{phase-name}/` are created or updated through the dialogue. Coaching never bypasses gates — it helps users get through them.

### When to Use

When the user prefers guided conversation, is new to the methodology, or is stuck mid-phase. For the step list, use `/sprd`.

---

## /sprd-review -- Multi-Perspective Review

### What It Does

Spawns the `multi-reviewer` agent against the current phase's artifacts in one of three modes: `--council` (default; Architecture / Product / Quality / Security viewpoints plus a consistency-and-ambiguity audit), `--adversarial` (challenge every assumption and estimate), or `--edge-cases` (walk every branch and boundary). Writes `review-report.md` into the phase's artifact directory with CRITICAL/HIGH/MEDIUM/LOW findings, each citing a specific artifact and carrying an actionable recommendation.

### Arguments

- No arguments: `--council` on the current phase
- `--adversarial` | `--edge-cases` | `--council` | `--all` (all three, combined report)
- `<phase-number>`: review a specific phase

### State Changes

None. Findings are advisory and do not block gates, but CRITICAL/HIGH findings usually predict gate failures — address them before `/sprd-gate`.

### When to Use

Phase 2 with `--council`, Phase 3 (Foundation) with `--edge-cases`, the Build Loop with `--adversarial`; any phase before its gate.

---

## /sprd-intake -- Document Corpus Intake

### What It Does

Wraps the entire Phase 0 Step 0c document-intake workflow as one command, so no one runs the
cataloger script by hand. It runs `intake_documents.py` to catalog the corpus (DOC-NNN IDs),
presents a HITL gate for the human to prioritize and prune, writes a token-budgeted summary per
document, generates the human-readable registry and the condensed session-start index, and
locks the catalog so DOC-NNN IDs stay stable for Phase 1 traceability.

### Arguments

- No arguments: workflow mode against the profile's `documentation.intake_path`
- `--docs <path>`: catalog a folder directly (standalone; IDs provisional until locked)
- `--rescan`: re-catalog after documents were added or removed (existing IDs preserved)

### State Changes

Writes `.sdlc/context/intake/` (catalog, summaries, index) and
`.sdlc/artifacts/00-discovery/document-registry.md`. Locks the catalog.

### When to Use

Phase 0 Step 0c, when the profile has a `documentation` section and the client provided
external documents. Prerequisite for `/sprd-brief`.

---

## /sprd-brief -- Discovery Workshop Brief

### What It Does

Prepares a stakeholder discovery workshop from the intake corpus. Spawns the `discovery-analyst` agent to produce `contradiction-list.md` (CON-NN: where documents disagree, two citations each, the resolving question) and `question-list.md` (Q-NN: what no document answers, grouped by agenda block, routed workshop / pre-workshop / interview), then drafts the one-page `workshop-brief.md` through a HITL curation gate — the human chooses which contradictions and questions make the page, the decisions the room must leave with, and logistics. The command drafts; the human edits and distributes. The brief contains questions only — it never proposes outcomes, metrics, or solutions.

### Arguments

- No arguments: workflow mode against the current project's locked intake catalog (requires Phase 0 Step 0c to have run)
- `--docs <path>`: standalone mode against any folder of documents (no `.sdlc/` required; DOC-NNN IDs are provisional)
- `--refresh`: re-run the analysis even if artifacts exist
- `--output <path>`: override the brief's output location

### State Changes

None. Outputs are optional for gate purposes, but every `blocks-outcome` contradiction must be resolved or accepted as a risk before Phase 0 exit, and Q-NN IDs persist into `phase1-handoff.md` open questions.

### When to Use

Phase 0 Step 0d, after document intake, before a multi-stakeholder workshop. Standalone: any time a folder of documents needs contradiction and gap analysis.

---

## /sprd-spec -- Author a Ready Spec

### What It Does

The Build-loop **Intent beat** wrapped as one command: turn a story into a *ready spec* (`specs/NNNN-name.md`) that clears the Definition of Ready before anyone builds it — scaffold → author → enforce the DoR → confirm the risk tier with a human. No spec, no build. The spec is the durable per-change record: one spec = one branch = one PR, living in the repo's `specs/` directory (in version control, not only under `.sdlc/`) because the agent re-reads it every session and the grader grades against it.

The command owns two scripts the user never calls by hand: `new_spec.py` (scaffold + id allocation) and `check_spec.py` (DoR enforcement). It drives Intent so nothing stays implicit — Goal, Why, Scope in/out, testable acceptance checks (each past the vague-line test), silent product decisions surfaced to a Decision List with named owners, and the one existing pattern the change reuses (`harness_context`).

### Arguments

- No arguments: workflow mode — author a spec in the current `.sdlc/` engagement (reads the spec backlog and `risk-tier-map.md` for context).
- `--repo <path>`: standalone mode — author a spec in any repo with no `.sdlc/` present (the missing engagement context is noted in the spec's `source` field).
- `--spec <path>`: validate (and finish authoring) an **existing** spec instead of scaffolding a new one.

### Internal Flow

1. **Resolve mode and repo root** (workflow `.sdlc/` parent, or standalone `--repo`).
2. **Gather Intent** — drive every DoR element; apply the vague-line test (*"could two people build different things from this?"*) to each acceptance check.
3. **Propose a risk tier, never assign it** — recommend HIGH/MEDIUM/LOW with one sentence of justification, then a HITL `AskUserQuestion` gate where the Pod Lead confirms or overrides. Risk challenges escalate up, never down.
4. **Scaffold** via `new_spec.py` (auto-allocated 4-digit id), then write the gathered Intent into the section bodies.
5. **Enforce the DoR** via `check_spec.py` — fix every BLOCK (MUST); judge each ADVISE (SHOULD) vague-line flag. Re-run until it reads `READY`.

### State Changes

Writes `specs/NNNN-name.md` to the repo. In workflow mode (`--state`), each `check_spec.py` run logs to `.sdlc/metrics/spec-log.jsonl`. Does not modify `state.yaml` or advance phases.

### When to Use

The Build loop's Intent beat — before building any change. A spec that `check_spec.py` reports as NOT READY must not enter the Delegate beat (that is the "skipping Intent" failure the loop exists to kill). When behavior changes later, the spec changes in the **same PR** as the code.

---

## /sprd-sprint -- Sprint Board

### What It Does

Gives the spec backlog a two-week **commitment window** without a second backlog, a reordering, or a gate. A named human types a sprint id (`S07`), slates a *count* of specs (`target`) by a **mix of work** — risk tiers, the axis that sets checking depth — and the command shows the slate's readiness every day, **readies** the sprint once every slated spec clears the Definition of Ready and its independent Engineering and Data verdicts, and **closes** it with kept / carried / dropped, each carry or drop with a name and a reason. The command owns `scripts/sprint.py`; users never call the script by hand.

The layer is additive and advisory. `sprint.py` exits 0 on every read; `ready` and `close` check only the slate (DoR + verdicts + dependency gaps), never G1–G7; nothing is ever written to `state.yaml`; `close` never suggests advancing (leaving Build stays a human, release-scoped declaration). Refinement runs in **any phase** where specs exist — neither this command nor `/sprd-refine` reads `current_phase` to decide whether it may run.

Different verbs belong to different points in the two-week rhythm:

| Moment | Verbs | Who |
|---|---|---|
| Setting up the next sprint (current sprint's last week) | `new`, `slate`, `unslate` | Product proposes and confirms the slate; `/sprd-refine --sprint` drives the slated specs to READY |
| Sprint planning meeting (day 0) | `ready` → writes the **sprint-planning page**; `plan` re-renders it on demand | a named human readies it; the team walks the page |
| Every day (the flow check) | `status` *(default)* | anyone |
| Whenever work changes hands | `handoff`, `ack` | the recorder and the recipient |
| Last day (sprint review, Retro+) | `close` → writes the **sprint-review page** | a named human confirms every carry / drop with a reason |

### Arguments

| Verb | Flags | Does |
|---|---|---|
| *(none)* / `status` | `[--sprint S07] [--wip-cap N] [--json]` | The slate (spec, name, risk, type, status, DoR, eng, data, next owner); unacknowledged handoffs and pending verdicts with business-day age; mix actual vs target; WIP vs cap; open/overdue `DL-NN` decisions; the advisory **build order** (dependencies first, then the spec that unblocks the most others, then HIGH → MEDIUM → LOW, then spec id) and **next up** (first spec in that order that is READY, `status: ready`, dependencies merged, under the WIP cap). Defaults to the active sprint — the highest-numbered sprint not yet closed, else the highest-numbered closed one, whose slate is replayed from the ledger and whose header shows `closed by` instead of days remaining |
| `new` | `--sprint S07 --goal "…" --start YYYY-MM-DD [--end D \| --days 10] --target N [--mix "HIGH:1,MEDIUM:2,LOW:3"] [--board-ref "ADO Iteration 6"] --by NAME` | Creates `.sdlc/sprints/S07.md` in `planning`. `end` defaults to the last business day of a 10-business-day window that starts on `start` (start is day 1: Mon 2026-09-28 -> Fri 2026-10-09); mix counts must sum ≤ target; `board_ref` is a manual mapping nothing reads; `--by` is required like every write |
| `slate` | `[--sprint S07]` | **Proposal only, writes nothing:** candidates are specs with `status: ready \| draft` and no sprint, filled into the remaining mix slots in spec-id order. Prints a copy-paste confirm line |
| `slate` | `--sprint S07 --by NAME --spec ID [--spec ID …] [--override --reason R]` | Writes `sprint: "S07"` on each confirmed spec. Over target → exit 1 unless `--override --reason` (recorded); mix breach → warning; a `depends_on` pointing outside the slate at an unmerged spec → warning |
| `unslate` | `[--sprint S07] --spec ID --by NAME --reason R` | Removes a spec from the slate (`sprint: ""`), reason recorded |
| `handoff` / `ack` | `--spec ID --to NAME --by NAME [--note …]` / `--spec ID --by NAME` | Assign-and-acknowledge: sets / clears `next_owner`; `status` lists unacknowledged handoffs with age. `ack` by someone other than `next_owner` warns, never fails |
| `verdict` | `--spec ID --lane eng\|data --verdict accepted\|returned\|pending\|n-a --by NAME [--reason R]` | Records the independent Engineering or Data verdict (`eng_review` / `data_review`). `n-a` is legal for `--lane data` only and only with `--reason`. Usually reached through `/sprd-refine validate` |
| `ready` | `[--sprint S07] --by NAME` | Requires every slated spec: `check_spec` READY, `status: ready`, `eng_review: accepted`, `data_review: accepted \| n-a`, and a dependency graph with no cycle and nothing pointing outside the slate at an unmerged spec; else exit 1 listing the gaps per spec. On success sets `state: ready`, `readied_by`, writes `.sdlc/reports/sprint-S07-planning.html` |
| `plan` | `[--sprint S07] [--output PATH]` | Renders (or re-renders) the planning page on demand — before `ready` to run the meeting from a draft that still shows the gaps, or after a late change |
| `close` | `[--sprint S07] --by NAME [--carry-to S08] [--carry SPEC=REASON …] [--drop SPEC=REASON …]` | kept = `status: merged`; every other slated spec must appear in exactly one `--carry` or `--drop` with a reason, else exit 1 naming the undecided. Carried specs move `sprint:` to `--carry-to`; dropped get `sprint: ""`. Writes `## Close`, sets `state: closed`, `closed_by`, renders `sprint-S07-review.html` |
| all verbs | `--state <.sdlc/state.yaml> \| --repo <path>` | Workflow vs standalone (mutually exclusive). Standalone creates `.sdlc/sprints/` and the ledger under `<repo>/.sdlc/` and the page header notes the missing engagement context. Workflow mode is detected by `state.yaml` presence, never by a bare `.sdlc/` |
| write verbs | `--field KEY=VALUE` (repeatable), `--today YYYY-MM-DD` | Extra ledger keys; date override for business-day maths. Activity-metric keys are refused (see errors) |

### Internal Flow

1. **Resolve mode and repo root** (workflow: `--state`, repo root = parent of `.sdlc/`; standalone: `--repo`).
2. **`new`** — validate the id (`^S\d{2,}$`), dates, target and mix (HITL: goal, dates, target and mix confirmed), render `templates/phases/build/sprint.md` into `.sdlc/sprints/SNN.md`, append `sprint_new` to the ledger.
3. **`slate`** — run the proposal (`sprint.py slate --sprint S07 [--json]`), present it, and stop at an `AskUserQuestion` gate: the human confirms or edits the set. Then run the confirm form with `--by <name> --spec …`. Each spec's frontmatter gains the five keys (`sprint`, `next_owner`, `eng_review`, `data_review`, `depends_on`) on first touch, inserted after `status:`; the body bytes and `check_spec`'s verdict are unchanged.
4. **`status`** (daily) — read-only; pairs with `/sprd-refine` (no args) for the refinement agenda.
5. **`ready`** — run `sprint.py ready --by <name>`; on exit 1 show the gap list per spec and route each gap to `/sprd-refine --spec` (DoR), `/sprd-refine validate` (verdicts) or `/sprd-spec --spec` (status flip). On success the planning page is written and linked from `.sdlc/reports/index.html` (an idempotent block between `<!-- sprints:start -->` and `<!-- sprints:end -->`).
6. **`close`** — derive kept vs open; ask per open spec: carry (to `--carry-to`) or drop, each with a reason and the named human; run `sprint.py close …`; the review page is written.

```bash
# Propose, then confirm, a slate
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py slate --state .sdlc/state.yaml --sprint S07
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py slate --state .sdlc/state.yaml --sprint S07 --by "Pod Lead" --spec 0007 --spec 0009

# The daily view (text, or the JSON /sprd-status and /sprd-refine read)
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py status --state .sdlc/state.yaml --json

# Ready, then close
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py ready --state .sdlc/state.yaml --sprint S07 --by "Pod Lead"
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py close --state .sdlc/state.yaml --sprint S07 --by "Pod Lead" --carry-to S08 --carry "0009=blocked on DL-04"
```

### State Changes

- Writes `.sdlc/sprints/SNN.md` (state, `readied_by`, `closed_by`, the rendered `## Slate` and `## Close` tables).
- Writes **only** the five optional keys on spec files whose basename matches `^\d{4}-` (`specs/spec-template.md` is never listed or written). `status` is not one of them and stays hand-moved — `sprint_model.set_frontmatter` refuses to write it.
- Appends to `.sdlc/metrics/sprint-log.jsonl` (events `sprint_new`, `slated`, `unslated`, `handoff`, `ack`, `verdict`, `ready`, `closed`, `carried`, `dropped`). Frontmatter is written first, then the ledger line; if the append fails the script prints `DRIFT` and exits 1 so the mismatch is never silent.
- Writes `.sdlc/reports/sprint-SNN-planning.html` / `-review.html` and the sprints block in `index.html` (only if it already exists).
- **Never** writes `state.yaml`, never advances a phase, never touches a board (ADO is updated by hand — `board_ref` is a label).

### Python Scripts Called

| Script | Purpose |
|--------|---------|
| `sprint.py` | Every verb; the I/O CLI over the pure `sprint_model.py` (mix, slate proposal, ready rule, build order, frontmatter writer rules) |
| `generate_sprint_report.py` | Imported lazily by `ready`, `plan`, `close` to render the planning / review pages (reuses `generate_phase_report.md_to_html`) |
| `check_spec.py` | Imported for `parse_frontmatter` and the per-spec DoR verdict (`check_spec_text`) — byte-for-byte unchanged |
| `track_decisions.py` | Imported for the open / overdue `DL-NN` decisions shown in `status` and on the pages |
| `track_specs.py --sprint SNN` | The slate's backlog view (`by_sprint`); the WIP cap is enforced globally by `--wip-cap` |

### Error Scenarios

| Situation | Behaviour |
|---|---|
| `status` / `slate` proposal on an unknown or malformed sprint id | prints "no data"; exit 0 (reads never fail) |
| Bad sprint id, existing sprint, mix sum > target, `--end` before `--start` | exit 1 |
| Unknown spec, spec already merged or in another sprint, closed sprint | exit 1 |
| Slate over `target` without `--override --reason` | exit 1 (mix breach is a warning only) |
| `ready` with gaps | exit 1 listing `<spec>: <gap>` per spec and the ready-when rule; nothing written |
| `close` with an undecided open spec, or `--carry` without `--carry-to` | exit 1 naming the spec |
| `verdict --verdict n-a` on `--lane eng`, or on `data` without `--reason` | exit 1 |
| `--field` with an activity-metric key (`velocity`, `story_points`, `pr_count`, `loc`, `points`, `estimate`, `effort`, `hours`, `capacity`, …) | exit 2 — "Refused: '<key>' is an activity metric the standard never tracks (velocity, story points, PR count, lines of code). Steering is on outcomes." |
| A frontmatter value containing `#`, quotes, a newline, or a placeholder token; a `--by`/`--to` that reads as an AI actor | exit 2 (the AI-actor check is labelling, not enforcement) |
| Ledger append failed after frontmatter was written | `DRIFT: N file(s) were written but the ledger append failed`; exit 1 |
| Page render failed at `ready`/`close` | `WARNING … Re-render with: sprint.py plan --sprint SNN`; the verb still exits 0 |

### Metrics Policy

Shown (this sprint only; "no data" when empty): slated / ready / not-ready counts, kept / carried / dropped with names and reasons, pending verdicts and unacknowledged handoffs with business-day age, mix actual vs target, WIP vs cap, carry-over recurrence per spec (in `/sprd-retro`, the only cross-sprint number), overdue `DL-NN` decisions. Refused or never computed: velocity, story points, estimates, effort, hours, PR count, LOC, any per-person aggregation, "% complete" as a sprint number, fabricated zeros. See `references/sprint-model.md`.

---

## /sprd-refine -- Refinement Agenda

### What It Does

Refines **the sprint's specs** — the Mon/Wed/Fri cross-functional review and the weekly Intent triage, made executable. With no arguments it renders the **agenda**: which slated specs are NOT READY and why, vague-line hits, which Engineering/Data verdicts are pending and for how many business days, unacknowledged handoffs, and which `DL-NN` decisions are overdue on their 2-business-day clock. Pointed at one spec it runs the DoR, proposes fixes to vague lines, surfaces silent decisions, proposes the risk tier and `depends_on`, and hands the edit to `/sprd-spec --spec`. It records the independent Engineering and Data **verdicts** that `/sprd-sprint ready` requires, and it routes a gap that lives in a Phase 1 or 2 artifact through the existing no-regression path so the engagement never "goes backwards".

It never approves anything itself, never assigns a tier, never answers a decision, and never edits `check_spec.py`.

### Arguments

| Form | Does | HITL |
|---|---|---|
| *(no args)* | The agenda for the current sprint, composed read-only from `sprint.py status --json` and `track_decisions.py --json`; "next review: Wed" when the cadence plan states the review days | none |
| `--spec <id \| path>` | Refine one spec: `check_spec.py` (+ `check_channel.py` when a channel is bound), propose fixes to vague lines, surface silent decisions to the spec's Decision List or to `.sdlc/decision-log.md` as `DL-NN` (owner + 2-day clock), propose the risk tier, propose `depends_on` when the spec's Scope or Delegation Plan names files, contracts or ids another slated spec introduces, then hand the edit to `/sprd-spec --spec` | tier confirmed; dependencies confirmed; decisions owned by a named human; `status: ready` flipped only after READY and a human's yes |
| `--sprint S07` | **Batch mode:** load the Phase 0–2 context once (constitution, frozen layers, `requirements.md`, `epics.md`, `business-rules.md`, `design-doc.md`, `adr-registry.md`, `api-contracts.md`, `data/data-contract.md`, `risk-tier-map.md`) and check every slated spec against it — mechanically (DoR, `source:` ids resolve, cited upstream artifacts not stale via `audit_artifacts.py report --json` (a `source` artifact in the stale list is a gap), tier vs `risk-tier-map.md`, channel dimensions) and by judgment (the `multi-reviewer` lenses fanned out across specs). One agenda, then fixes one spec at a time | as above, per spec |
| `validate --spec N --lane eng\|data --verdict accepted\|returned\|n-a --by <name> [--reason]` | Records the independent verdict (`sprint.py verdict`). `returned` sends the spec back to refinement with the reason; `n-a` is allowed only from Data and only with a reason | the named lead |
| `--upstream --spec N` | The no-regression path: pick the upstream artifact (`FR-…`, `BR-…`, `ADR-…`), edit it **in place** (human-confirmed diff), record it with `audit_artifacts.py record --event revised`, re-gate that phase with `check_gates.py --phase N` as information, **regenerate that phase's layer** (recorded as `refreshed`), then the spec re-enters refinement. A `DL-NN` is opened only for a product decision or a Phase 0 change. `current_phase` never moves | which artifact; the diff; who made it |
| `--repo <path>` | Standalone, same degradation as `/sprd-sprint` (no `.sdlc/` needed; missing engagement context noted) | — |

### Internal Flow

1. **Resolve mode and the sprint** (active sprint by default; `--sprint` to name one).
2. **Agenda** — read `sprint.py status --json` (readiness gaps, `verdicts_pending`, `handoffs_open`, `dependency_gaps`, `decisions`) and render the agenda; nothing is written.
3. **Per spec** — run the DoR, walk each finding with the human, write through `/sprd-spec --spec`, re-run until READY; then ask for the `status: ready` flip.
4. **Verdicts** — `validate` records `eng_review` / `data_review` by name; both lanes may run in parallel, before anyone builds.
5. **Upstream** — when the gap is upstream, stop and route via `/sprd-revise` + `check_gates.py --phase N` instead of editing the spec around it.

```bash
# The agenda's two read-only sources
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py status --state .sdlc/state.yaml --json
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/track_decisions.py --state .sdlc/state.yaml --json

# Record a verdict
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py verdict --state .sdlc/state.yaml --spec 0007 --lane data --verdict n-a --by "Data Lead" --reason "no data impact — UI copy only"
```

### State Changes

Writes spec bodies only through `/sprd-spec --spec`; writes `eng_review` / `data_review` (and the `verdict` ledger line) through `sprint.py`; appends `DL-NN` items to `.sdlc/decision-log.md`. The `--upstream` path writes through `/sprd-revise` and re-gates with `check_gates.py --phase N` (which records that phase's `gate_results`), but never moves `current_phase`. Never writes `state.yaml` itself.

### Python Scripts Called

| Script | Purpose |
|--------|---------|
| `sprint.py status --json` / `sprint.py verdict` | The agenda's sprint view; the verdict writer |
| `track_decisions.py --json` | Open / overdue `DL-NN` decisions |
| `check_spec.py` (+ `check_channel.py`) | The DoR verdict and vague-line lint per spec (advisory channel lint when bound) |
| `audit_artifacts.py report --json` | Staleness of the upstream artifacts a spec cites (batch mode: a spec whose `source` artifact is in the stale list is flagged and routed to `--upstream`) |
| `check_gates.py --phase N` | Re-gate the phase an upstream fix touched, as information (`--upstream` path only) |
| `audit_artifacts.py record --event revised \| refreshed` | Record the in-place upstream edit, and the regenerated phase layer (`--upstream` path only) |
| `validate_frozen_layer.py --phase N` | Validate the regenerated phase layer (`--upstream` path only) |

### Error Scenarios

| Situation | Behaviour |
|---|---|
| No sprint exists | the agenda says so ("no data") and offers `/sprd-sprint new`; exit 0 |
| Spec not found | exit 1 from `check_spec.py` / `sprint.py`; the command names the path tried |
| `validate --verdict n-a` on the `eng` lane, or without `--reason` | refused (exit 1) — Data may be not-applicable, Engineering may not |
| `--by` reads as an AI actor | refused (exit 2) — verdicts carry a human's name |
| Upstream re-gate fails | the phase's gate report lists the failures; `current_phase` is unchanged and the spec stays in refinement |

---

## Additional Commands (summaries)

Seventeen commands have their full flow documented in their command files rather than here.
One line each; see `commands/<name>.md` for the complete instructions.

| Command | What it does |
|---|---|
| `/sprd-handoff` | Hand a ready spec to a developer in one step — branch, `status`/`developer` frontmatter commit, code-host assignment (+ review request to the checker; on Azure DevOps the checker becomes a required reviewer through their roster `email:`, and a missing one is an `assignment_error` with the PR still opened), optionally starting Claude Code on the branch in plan mode. Refuses (repository untouched) unless the spec is ready, the developer is in the roster and isn't the spec's own checker, and the team is under its WIP limit |
| `/sprd-spec-status` | Report a spec's status read from its pull request — checks, whether the grader ran and its verdict, whether a required security review passed, approvals, merge, and who the change is waiting on in one line. Reads GitHub through `gh` or Azure DevOps through `az`, whichever the repository's remote is on (`--host` overrides for one run). No PR yet or no code-host access are reported plainly, not as errors; a value the host does not record reads `null`, never a false no. Once the PR merges, sets `status: merged` on the default branch, once |
| `/sprd-spike` | Open a bounded spike (`spikes/NNNN-name.md`) for a question the pod cannot yet answer. The deliverable is the written finding, not the code — the code is thrown away, the finding outlives the branch. Backed by `scripts/new_spike.py` |
| `/sprd-doctor` | Verify the installed harness will actually run in this repo — interpreters present, rails scripts executable, required secrets set, branch protection active — and print the fix for anything that will not. **Pack-aware:** reads the installed CI/CD pack from the harness manifest and checks GitHub installs with `gh` (repo secrets, ruleset), Azure DevOps installs with `az` (variable groups read from the installed pipelines, branch policies) — never asks a repo to install the other platform's CLI. The harness fails quietly; this is what makes it fail loudly |
| `/sprd-harness` | Install or refresh the delivery harness independent of a full `/sprd-setup` |
| `/sprd-upgrade` | Bring an installed harness forward safely using the install manifest — updates factory-original files, preserves adaptations, surfaces both-sides changes as `.harness-new` siblings to merge |
| `/sprd-feature` | Decompose an epic into channel-aware features and specs |
| `/sprd-channel` | Bind a spec to its channel and inject the acceptance dimensions |
| `/sprd-experience` | Author the channel-shaped experience for a surface |
| `/sprd-data` | Author the data contract, readiness, and lineage for a feature |
| `/sprd-rules` | Author business rules and golden scenarios |
| `/sprd-evals` | Author the versioned golden set for an LLM-powered spec |
| `/sprd-revise` | Change one specific artifact (id or section) — discipline agent proposes, human decides; records the why to the change-ledger + a linked `DL-NN`, re-gates, shows downstream staleness to disposition |
| `/sprd-audit-artifacts` | Read-only sibling to `/sprd-audit`: artifact freshness dashboard, forward `--impact`, and `--history` change trail (advisory; never blocks) |
| `/sprd-version` | Content history for any pre-Build artifact — list/show/diff versions derived from the change-ledger's hashes; rollback is preview → named-human confirm, append-only ("restored from vX"), `--ack-signoff` for signed-off artifacts; `gc` prunes the local store safely |
| `/sprd-refresh` | Reverse propagation — back-propagate a merged spec's shipped reality into pre-Build artifacts: detect (review-first, divergence-aware) → draft a `.proposed` → named-human apply/reject → status. The One Rule throughout: agent proposes, human decides |
| `/sprd-retro` | Read-only cross-ledger retro roll-up: recurring findings (permanent-check candidates), repeat-stale artifacts, the refresh funnel (divergence-heuristic tuning signal), a disposition-debt rollup, and — when `sprint-log.jsonl` exists — carry-over recurrence per spec (≥2 sprints; the only cross-sprint number) and bounce causes by lane and reason. Patterns, not people; never blocks |

---

## Command Interaction Flow

The typical SDLC lifecycle follows this pattern:

```
/sprd-setup
    |
    v
/sprd          <-- Orient: what phase am I in, what do I do?
    |
    v
  [work]       <-- Produce artifacts, use skills, write code
    |
    v
/sprd-gate     <-- Check: am I ready to advance?
    |
    +-- FAIL --> fix issues --> /sprd-gate (repeat)
    |
    +-- PASS
         |
         v
/sprd-next     <-- Advance: run gates, HITL sign-off, resolve questions
    |
    v
/sprd          <-- Orient to the new phase
    |
    v
  [repeat through Phase 9, then Phase C: Close & Transfer]
```

Supporting commands used at any time:
- `/sprd-status` -- Quick progress check (no prerequisites beyond setup).
- `/sprd-phase-report` -- Generate shareable HTML report for any phase.
- `/sprd-audit` -- Analyze gate effectiveness after several phases complete.

### Session Start Pattern

A typical work session begins with:
1. `/sprd-status` -- See where the project stands.
2. `/sprd` -- Get actionable guidance for the current phase.
3. Work on artifacts.
4. `/sprd-gate` -- Verify progress before ending the session or advancing.

---

## Python Script Invocation

### The uv Runtime

All commands invoke Python scripts through `uv`, a fast Python package manager and runner. The invocation pattern is:

```bash
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts <script-path> [arguments]
```

`${CLAUDE_PLUGIN_ROOT}` is the environment variable Claude Code sets to the plugin's install directory. The `--project ${CLAUDE_PLUGIN_ROOT}/scripts` flag tells `uv` to use the `pyproject.toml` in the plugin's `scripts/` directory for dependency resolution. This ensures scripts have access to their required packages (PyYAML, Jinja2, etc.) without polluting the target project's environment.

### How Scripts Find state.yaml

Scripts receive the path to `state.yaml` via the `--state` argument. This is always relative to or within the target project's `.sdlc/` directory. The calling command is responsible for resolving the correct path before invocation.

### How Scripts Output Results

Scripts write structured output to stdout, which the calling command parses and displays. HTML reports are written directly to `.sdlc/reports/`. Exit codes indicate success (0) or failure (non-zero), with error details on stderr.

### Script Inventory

| Script | Called By | Purpose |
|--------|-----------|---------|
| `init_project.py` | `/sprd-setup` | Creates `.sdlc/` directory structure |
| `validate_profile.py` | `/sprd-setup` | Validates profile YAML against schema |
| `generate_status.py` | `/sprd-status` | Generates progress dashboard |
| `check_gates.py` | `/sprd-gate`, `/sprd-next` | Runs the 7-gate validation system |
| `generate_phase_report.py` | `/sprd-gate`, `/sprd-next`, `/sprd-phase-report` | Renders HTML reports |
| `advance_phase.py` | `/sprd-next` | Updates `state.yaml` with phase transition |
| `audit_gates.py` | `/sprd-audit` | Analyzes gate effectiveness across phases |
| `sprint.py` | `/sprd-sprint`, `/sprd-refine`, `/sprd-status` (read) | Sprint records, slate, verdicts, ready / close; the sprint ledger |
| `generate_sprint_report.py` | `/sprd-sprint` (`ready`, `plan`, `close`) | Renders the sprint-planning and sprint-review HTML pages |
| `track_decisions.py` | `/sprd-status`, `/sprd-refine` | Open / overdue `DL-NN` decisions on their 2-business-day clock |

---

## Cross-References

- **Gate system details:** See [gate-system.md](gate-system.md) for the full 7-gate specification, severity levels, and override protocol.
- **State machine:** See [state-machine.md](state-machine.md) for the `state.yaml` schema and valid phase transitions.
- **Phase lifecycle:** See [phase-lifecycle.md](phase-lifecycle.md) for phase definitions, artifact requirements, and entry/exit criteria.
- **Script internals:** See [scripts.md](scripts.md) for Python script implementation details, dependencies, and extension points.
- **Validation rules:** See [references/validation-rules.md](../references/validation-rules.md) for gate override protocol and validation rule definitions.
- **Sprint layer:** See [references/sprint-model.md](../references/sprint-model.md) for the sprint lifecycle, the slate and the mix, the ready rule, the build-order heuristic, the five spec keys, the ledger, and the metrics policy behind `/sprd-sprint` and `/sprd-refine`.
