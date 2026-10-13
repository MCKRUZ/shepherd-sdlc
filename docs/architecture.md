# System Architecture

Comprehensive architectural documentation for Shepherd -- a Claude Code plugin that orchestrates a full 9-phase Software Development Lifecycle with company-configurable profiles, compliance gates, and quality enforcement.

---

## Table of Contents

1. [Plugin Anatomy](#1-plugin-anatomy)
2. [Component Relationships](#2-component-relationships)
3. [Data Flow](#3-data-flow)
4. [Directory Structure](#4-directory-structure)
5. [Progressive Disclosure Strategy](#5-progressive-disclosure-strategy)
6. [Two-Directory Model](#6-two-directory-model)
7. [What this deliberately does not integrate with](#7-what-this-deliberately-does-not-integrate-with)
8. [Cross-References](#8-cross-references)

---

## 1. Plugin Anatomy

### 1.1 Plugin Manifest (`.claude-plugin/plugin.json`)

The plugin manifest is **metadata only** — name, version, description, author, homepage,
license, keywords. It does not register components; there is no component or profile
registry inside it. The marketplace entry (`.claude-plugin/marketplace.json`) declares
`"source": "."`, so the whole repository directory ships as the plugin payload.

```json
{
  "name": "shepherd",
  "version": "1.3.0",
  "description": "SDLC orchestration for Claude Code + one-command install of the full delivery harness (...)",
  "author": { "name": "Matt Kruczek", "url": "https://github.com/MCKRUZ" },
  "homepage": "https://github.com/MCKRUZ/shepherd-sdlc",
  "repository": "https://github.com/MCKRUZ/shepherd-sdlc",
  "license": "MIT",
  "keywords": ["sdlc", "lifecycle", "compliance", "quality", "orchestration", "..."]
}
```

(Abridged — see `.claude-plugin/plugin.json` for the current contents; the `version` there is
the source of truth.)

### 1.2 Component Discovery (by convention, not registration)

Every component is discovered from its conventional location in the plugin directory:

| Component | Location | How it is discovered |
|-----------|----------|----------------------|
| Main skill | `SKILL.md` | Loaded when the plugin activates. |
| Slash commands | `commands/*.md` | One file per command, picked up by filename. |
| Agents | `agents/*.md` | One file per agent definition. |
| Hooks | `hooks/` | Session/phase context-injection scripts, wired via hook configuration. |
| **Profiles** | `profiles/*/profile.yaml` | **Runtime directory listing** — `/sprd-setup` lists `profiles/` (excluding `_schema.yaml`) and presents every profile found, including ones it has never seen. Adding a profile is creating the directory; no registration step exists. |
| Scripts | `scripts/*.py` | Invoked explicitly by commands/hooks via `uv run`. |

Two consequences of the profiles row: a new profile ships automatically (the payload is the
whole directory), and its `company.profile_id` must equal its directory name — compliance
gates resolve at `profiles/<profile_id>/compliance/`, and
`scripts/tests/test_validate_profile.py::TestOnDiskProfiles` pins both properties for every
profile on disk.

### 1.3 Component Loading Sequence

When Claude Code activates the plugin, it loads components in this order:

1. **`SKILL.md`** -- The skill definition is loaded first. It contains the plugin's purpose, trigger phrases (e.g., "start sdlc", "sdlc setup", "run phase gate"), the command table, phase overview, human-in-the-loop protocol, visual report protocol, and agent orchestration protocol. This is the primary context document that Claude reads to understand what the plugin does and how to use it.

2. **`commands/`** -- Seven slash command definitions are registered. Each is a markdown file that tells Claude how to handle that command:

   | Command File | Slash Command | Purpose |
   |-------------|---------------|---------|
   | `sprd-setup.md` | `/sprd-setup` | Interactive setup wizard -- select profile, initialize `.sdlc/` |
   | `sprd.md` | `/sprd` | Show current phase guidance, next action, required artifacts |
   | `sprd-status.md` | `/sprd-status` | Progress dashboard with phase table and completion % |
   | `sprd-gate.md` | `/sprd-gate` | Run exit criteria checks for current phase (does not advance) |
   | `sprd-next.md` | `/sprd-next` | Advance to next phase if all MUST gates pass |
   | `sprd-phase-report.md` | `/sprd-phase-report` | Generate visual HTML report for current phase |
   | `sprd-audit.md` | `/sprd-audit` | Analyze gate effectiveness across completed phases |

3. **`agents/`** -- Four custom agent definitions are loaded. These are specialized Claude sub-agents spawned during specific phases:

   | Agent File | Agent Name | Role |
   |-----------|------------|------|
   | `sdlc-orchestrator.md` | SDLC Orchestrator | Master coordinator -- routes skills, enforces gates, manages state |
   | `requirements-analyst.md` | Requirements Analyst | Decomposes problems into requirements, user stories, acceptance criteria |
   | `compliance-checker.md` | Compliance Checker | Validates artifacts against SOC 2, HIPAA, GDPR, PCI-DSS frameworks |
   | `section-evaluator.md` | Section Evaluator | Discriminator in generator-evaluator loop -- assesses section implementations against plan criteria |

4. **`hooks/`** -- Two PowerShell hooks are registered for session lifecycle events:

   | Hook File | Trigger | Behavior |
   |----------|---------|----------|
   | `shepherd-session-start.ps1` | Session start | Reads `.sdlc/state.yaml`, outputs current phase context banner, displays session handoff summary for long-running phases |
   | `sdlc-phase-inject.ps1` | PreToolUse (file edits) | Injects phase-aware reminders when Claude edits files (e.g., "Build Loop: write the spec first, build from an approved plan, prove against the spec before merge.") |

---

## 2. Component Relationships

### 2.1 Architecture Diagram

```
+------------------------------------------------------------------+
|                     PLUGIN DIRECTORY (immutable)                   |
|                                                                    |
|  +------------+     loads      +---------------------------+       |
|  | plugin.json| ------------> |         SKILL.md          |       |
|  +------------+               | (entry point, triggers,   |       |
|                               |  protocols, phase table)  |       |
|                               +---------------------------+       |
|                                 |           |           |          |
|                       references|   defines |  defines  |          |
|                                 v           v           v          |
|  +------------------+  +-------------+  +-----------+              |
|  |   references/    |  |  commands/  |  |  agents/  |              |
|  | (on-demand docs) |  |  (7 slash   |  | (4 custom |              |
|  |                  |  |   commands) |  |  agents)  |              |
|  +------------------+  +------+------+  +-----------+              |
|                               |                                    |
|                     invoke via uv run                              |
|                               |                                    |
|  +----------------------------v-----------+   +----------------+   |
|  |            scripts/                    |   |    hooks/       |   |
|  | validate_profile.py  init_project.py   |   | session-start  |   |
|  | check_gates.py       advance_phase.py  |   | phase-inject   |   |
|  | generate_status.py   audit_gates.py    |   +-------+--------+   |
|  | generate_phase_report.py               |           |            |
|  | synthesize_spec.py                     |           |            |
|  | map_deep_plan_artifacts.py             |           |            |
|  +-----+-----------+---------------------+           |            |
|        |           |                                  |            |
|  +-----v----+ +----v-----------+                      |            |
|  | phases/   | | profiles/     |                      |            |
|  | (9 phase  | | (_schema.yaml |                      |            |
|  |  defs +   | | + company     |                      |            |
|  |  registry)| |   configs)    |                      |            |
|  +----------+  +------+--------+                      |            |
|                       |                               |            |
|  +--------------------+--------+                      |            |
|  |     templates/              |                      |            |
|  | state-init.yaml             |                      |            |
|  | phases per-slug templates   |                      |            |
|  | constitution.md             |                      |            |
|  | design-doc.md               |                      |            |
|  +-----------------------------+                      |            |
+-----|------------------------------|------------------+            |
      |  copied at init             |  read/write at runtime        |
      v                             v                               |
+------------------------------------------------------------------+|
|                  TARGET PROJECT DIRECTORY (mutable)               ||
|                                                                   |
|  +---.sdlc/-----------------------------------------------+      |
|  |                                                         |      |
|  |  state.yaml  <-- scripts read/write, hooks read --------+------+
|  |  profile.yaml  (frozen copy of selected profile)        |
|  |  constitution.md                                        |
|  |  reports/  (generated HTML reports)                     |
|  |                                                         |
|  |  artifacts/  (one dir per phase slug)                   |
|  |  +-- 00-discovery/    (problem-statement.md, etc.)      |
|  |  +-- 01-requirements/ (requirements.md, epics.md, etc.) |
|  |  +-- 02-design/       (design-doc.md, adrs/, etc.)      |
|  |  +-- 03-foundation/   (foundation-report.md,           |
|  |  |                     risk-tier-map.md, walking skel.) |
|  |  +-- build/           (specs/, build-summary.md,        |
|  |  |                     per-change work)                 |
|  |  +-- 07-documentation/ (README.md, api-docs.md, etc.)   |
|  |  +-- 08-deployment/   (release-notes.md, etc.)          |
|  |  +-- 09-monitoring/   (monitoring-config.md, etc.)      |
|  |  +-- close/           (final-handoff-report.md,         |
|  |  |                     harness-audit.md)                |
|  +--------------------------------------------------------+      |
+-------------------------------------------------------------------+
```

### 2.2 Interaction Patterns

**SKILL.md references commands and agents.** The skill definition contains the command table and agent orchestration protocol. When a user says "start sdlc" or types `/sprd-setup`, Claude reads the SKILL.md context to determine which command handles the request and which agents to spawn.

**Commands call Python scripts via `uv run`.** Slash commands instruct Claude to execute Python automation. The invocation pattern is:

```bash
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts <script-name>.py --arg value
```

The `--project` flag ensures `uv` resolves dependencies from the scripts' `pyproject.toml` regardless of the current working directory.

**Scripts read/write `.sdlc/state.yaml` in the target project.** All Python scripts receive the path to the target project's `.sdlc/` directory via CLI arguments (`--state`, `--target`). Scripts never modify plugin source files.

**Hooks read `state.yaml` to inject context.** The session-start hook reads `state.yaml` to determine the current phase and display a context banner. The phase-inject hook reads it on every file edit to provide phase-appropriate reminders.

**Profiles are frozen at init time.** During `/sprd-setup`, the selected profile is copied from the plugin's `profiles/` directory into `.sdlc/profile.yaml` in the target project. This frozen copy is what scripts and hooks read at runtime -- the plugin's source profiles are never referenced after initialization.

**Phase definitions are referenced by `phase-registry.yaml`.** The registry maps phase ids to definition files (`phases/00-discovery.md`, `01-requirements.md`, `02-design.md`, `03-foundation.md`, `build-loop.md`, `07-documentation.md`, `08-deployment.md`, `09-monitoring.md`, `close.md`), along with entry/exit gate conditions, skill mappings, and required artifacts. Phase ids are strings (`build` and `close` are non-numeric), and the registry `order` field drives sequence -- not the id.

**Templates are copied to `.sdlc/artifacts/` during init.** The `init_project.py` script creates the full artifact directory structure and copies the constitution template. Phase-specific templates serve as scaffolds for artifact creation.

**References are loaded on demand.** Documents in `references/` are never loaded into context automatically. They are pulled in only when Claude needs specific details about validation rules, agent assignments, skill mappings, or compliance frameworks.

---

## 3. Data Flow

### 3.1 Complete Lifecycle Data Flow

```
  User                 Claude Code              Plugin Scripts           Target .sdlc/
   |                       |                          |                       |
   |  "start sdlc"         |                          |                       |
   |---------------------->|                          |                       |
   |                       |  load SKILL.md           |                       |
   |                       |  (triggers matched)      |                       |
   |                       |                          |                       |
   |  /sprd-setup          |                          |                       |
   |---------------------->|                          |                       |
   |                       |  validate_profile.py --->|                       |
   |                       |  init_project.py ------->|-----> state.yaml      |
   |                       |                          |-----> profile.yaml    |
   |                       |                          |-----> artifacts/<slug> |
   |                       |                          |-----> constitution.md |
   |                       |                          |                       |
   |  (phase work)         |                          |                       |
   |---------------------->|                          |                       |
   |                       |  write artifacts ------->|-----> artifacts/NN/   |
   |                       |                          |                       |
   |  /sprd-gate           |                          |                       |
   |---------------------->|                          |                       |
   |                       |  check_gates.py -------->|<----- state.yaml     |
   |                       |                          |<----- artifacts/NN/  |
   |                       |<-- gate results ---------|                       |
   |<-- pass/fail report --|                          |                       |
   |                       |                          |                       |
   |  /sprd-next           |                          |                       |
   |---------------------->|                          |                       |
   |                       |  advance_phase.py ------>|<----- state.yaml     |
   |                       |                          |-----> state.yaml     |
   |                       |                          |       (atomic update)|
   |<-- next phase info ---|                          |                       |
   |                       |                          |                       |
   |  (new session)        |                          |                       |
   |---------------------->|                          |                       |
   |                       |  session-start hook ---->|<----- state.yaml     |
   |                       |<-- phase context --------|                       |
   |                       |                          |                       |
   |  (edit file)          |                          |                       |
   |---------------------->|                          |                       |
   |                       |  phase-inject hook ----->|<----- state.yaml     |
   |                       |<-- phase reminder -------|<----- profile.yaml   |
```

### 3.2 Detailed Step Descriptions

**Step 1: Plugin Activation.** When a user opens a project that has this plugin installed, Claude Code reads `plugin.json` and loads `SKILL.md` into context. This gives Claude full awareness of the SDLC methodology, available commands, agent orchestration rules, and human-in-the-loop protocol. No target project state exists yet.

**Step 2: Project Setup (`/sprd-setup`).** The user invokes the setup wizard. Claude runs two scripts in sequence:

1. `validate_profile.py` -- Validates the selected profile YAML against `profiles/_schema.yaml`. Checks required fields (`company`, `stack`, `quality`), type constraints, value ranges (e.g., `coverage_minimum` between 0-100), and optional compliance/conventions blocks. Returns a list of errors or confirms validity.

2. `init_project.py` -- Creates the `.sdlc/` directory structure in the target project:
   - Reads `templates/state-init.yaml` and substitutes `${PROFILE_ID}`, `${PROJECT_NAME}`, and `${CREATED_AT}` with actual values
   - Writes `state.yaml` with Phase 0 (Discovery) set as active
   - Copies the profile as a frozen `profile.yaml`
   - Creates 9 artifact subdirectories, one per phase slug (`00-discovery`, `01-requirements`, `02-design`, `03-foundation`, `build`, `07-documentation`, `08-deployment`, `09-monitoring`, `close`)
   - Copies the constitution template

**Step 3: Phase Work.** During each phase, Claude guides the user through the phase definition's workflow. Artifacts are written to `.sdlc/artifacts/<slug>/`, where the directory name is the phase's `slug` field -- not a zero-padded integer (`build` and `close` are non-numeric). Each phase has required and optional artifacts defined in `phase-registry.yaml`. Within the Build Loop, session continuity is maintained per-spec through `session-handoff.json` -- a structured JSON file tracking spec/section progress, blockers, and next actions across sessions.

**Step 4: Gate Checking (`/sprd-gate`).** The `check_gates.py` script reads `state.yaml` to determine the current phase, then validates artifacts against the 7-gate system:

| Gate | What It Checks | Severity |
|------|---------------|----------|
| G1: Integrity | Required artifacts exist, are non-empty, parse correctly, no placeholder content (`TODO`, `TBD`, `${VAR}`) | MUST |
| G2: Completeness | All required sections present, cross-references valid, no missing content areas | MUST |
| G3: Metrics | Quantitative thresholds from profile (coverage >= `coverage_minimum`, file size <= `max_file_lines`, function length <= `max_function_lines`); checked per-change inside the Build Loop, not in a batch phase | MUST or SHOULD (varies by phase) |
| G4: Compliance | Correct labeling -- requirement priorities, ADR statuses, compliance framework mappings, risk severities | MUST or SHOULD (varies by phase) |
| G5: Cross-Phase Consistency | Detects drift in locked metrics across phase transitions (budget, timeline, scope, stakeholder roster, quality thresholds, compliance reqs); warns via decision log, does not block | SHOULD |
| G6: Quality | Holistic assessment -- clarity, accuracy, internal consistency, alignment with prior phase artifacts | MUST or SHOULD (varies by phase) |
| G7: Exit criteria | The phase's declared `exit_gate.conditions[]` prose checks, surfaced so the approver sees the checklist they are signing against | REVIEW (never blocks) |

Gate severity varies by phase. Phase 2 (Design) and the Build Loop apply the gates most strictly, while Phase 0 (Discovery) only requires G1 and G2 as MUST. G7 is silent for Phases 0-2, which declare no prose exit conditions.

**Step 5: Phase Advancement (`/sprd-next`).** The `advance_phase.py` script:
1. Runs `check_gates.py` internally to verify all MUST gates pass
2. If gates fail, returns a blockers report without modifying state
3. If gates pass, atomically updates `state.yaml`:
   - Sets current phase status to `completed` with `completed_at` timestamp
   - Records gate results in the phase's `gate_results` field
   - Appends a transition record to `history`
   - Sets the next phase to `active` with `entered_at` timestamp (next phase = the registry entry with `order` + 1, not id + 1)
   - Updates `current_phase` and `phase_name` at the top level
4. Outputs guidance for the next phase (skills, required artifacts, phase definition path)

All phases use `approval: manual` in the registry, so advancement is always manual -- every phase transition requires human confirmation. There is no auto-advance.

**Step 6: Session Start Hook.** On every new Claude Code session, `shepherd-session-start.ps1`:
1. Checks if `.sdlc/state.yaml` exists in the current directory
2. Parses the current phase number and name
3. Outputs a context banner: `[SHEPHERD] Phase N: PhaseName -- description`
4. During the Build Loop, reads `session-handoff.json` and displays a continuity summary with active spec/section, blockers, and next steps

**Step 7: Phase-Inject Hook.** On every file edit operation, `sdlc-phase-inject.ps1`:
1. Reads current phase from `state.yaml`
2. Outputs a phase-specific reminder:
   - Phase 0: "Focus on understanding the problem, not writing code."
   - Build Loop: "Write the spec first. Build from an approved plan. Prove against the spec before merge."
3. Reads `profile.yaml` for convention reminders (commit format, naming, immutability rules)

---

## 4. Directory Structure

### 4.1 Plugin Directory (Source)

```
shepherd/                          Plugin root (installed or symlinked)
|
|-- plugin.json                            Plugin manifest -- discovery entry point
|-- SKILL.md                               Skill definition -- loaded on activation
|-- CLAUDE.md                              Development instructions for contributors
|
|-- commands/                              7 slash command definitions
|   |-- sprd.md                            /sprd -- current phase guidance
|   |-- sprd-setup.md                      /sprd-setup -- project initialization wizard
|   |-- sprd-status.md                     /sprd-status -- progress dashboard
|   |-- sprd-gate.md                       /sprd-gate -- run exit criteria checks
|   |-- sprd-next.md                       /sprd-next -- advance to next phase
|   |-- sprd-phase-report.md               /sprd-phase-report -- generate HTML report
|   +-- sprd-audit.md                      /sprd-audit -- gate effectiveness analysis
|
|-- agents/                                4 custom agent definitions
|   |-- sdlc-orchestrator.md               Master coordinator agent
|   |-- requirements-analyst.md            Requirements decomposition agent
|   |-- compliance-checker.md              Compliance validation agent
|   +-- section-evaluator.md               Implementation quality evaluator agent
|
|-- phases/                                9 phase definitions + registry
|   |-- phase-registry.yaml                Master registry -- all phases, gates, artifacts
|   |-- 00-discovery.md                    Phase 0 definition
|   |-- 01-requirements.md                 Phase 1 definition
|   |-- 02-design.md                       Phase 2 definition
|   |-- 03-foundation.md                   Phase 3 definition
|   |-- build-loop.md                      Build Loop definition
|   |-- 07-documentation.md                Phase 7 definition
|   |-- 08-deployment.md                   Phase 8 definition
|   |-- 09-monitoring.md                   Phase 9 definition
|   +-- close.md                           Phase C: Close & Transfer
|
|-- profiles/                              Company/stack configurations
|   |-- _schema.yaml                       Profile validation schema (RFC 2119)
|   |-- microsoft-enterprise/
|   |   |-- profile.yaml                   C#/.NET 10 + Angular 22 + Azure + SOC 2
|   |   |-- claude-md-template.md          CLAUDE.md template for target projects
|   |   +-- switchboard-rules.json         Agent routing rules for this profile
|   |-- ado-enterprise/
|   |   +-- profile.yaml                   microsoft-enterprise's stack on Azure Repos + Azure Pipelines
|   |-- ado-enterprise-python/
|   |   +-- profile.yaml                   ado-enterprise's Python sibling (FastAPI + React, same rails)
|   |-- starter/
|   |   +-- profile.yaml                   Minimal profile, no compliance
|   +-- creative-tooling/
|       +-- profile.yaml                   Python/uv plugin development profile
|
|-- references/                            Progressive disclosure documents
|   |-- state-machine.md                   State format and transition rules
|   |-- validation-rules.md                7-gate validation system details
|   |-- skill-mapping.md                   Phase-to-skill mapping
|   |-- agent-roster.md                    Phase-to-agent mapping with parallel groups
|   |-- compliance-frameworks.md           SOC 2, HIPAA, GDPR, PCI-DSS gates
|   |-- acceptance-criteria.md             Acceptance criteria guidelines
|   |-- deep-plan-integration.md           /deep-plan skill integration guide
|   |-- knowledge-base.md                  Domain knowledge reference
|   +-- scenarios.yaml                     Test scenarios for validation
|
|-- templates/                             Artifact scaffolds
|   |-- state-init.yaml                    Initial state.yaml template (variable placeholders)
|   |-- constitution.md                    Project constitution template
|   |-- design-doc.md                      Design document template
|   |-- requirements.md                    Requirements document template
|   |-- test-plan.md                       Test plan template
|   |-- release-checklist.md               Release checklist template
|   +-- phases/                            Per-phase artifact templates
|       |-- 00-discovery/                  constitution.md, problem-statement.md, ...
|       |-- 01-requirements/               requirements.md, epics.md, user-stories.md, ...
|       |-- 02-design/                     design-doc.md, api-contracts.md, adrs/, ...
|       |-- 03-foundation/                 foundation-report.md, risk-tier-map.md, ...
|       |-- build/                          specs/, session-handoff.json, build-summary.md, ...
|       |-- 07-documentation/              (uses target project docs)
|       |-- 08-deployment/                 deployment-checklist.md, ...
|       |-- 09-monitoring/                 monitoring-config.md, ...
|       +-- close/                         final-handoff-report.md, harness-audit.md, ...
|
|-- scripts/                               Python automation (uv runtime)
|   |-- pyproject.toml                     Python project config (dependencies: pyyaml)
|   |-- uv.lock                            Locked dependency versions
|   |-- validate_profile.py                Validate profile YAML against schema
|   |-- init_project.py                    Initialize .sdlc/ in target project
|   |-- check_gates.py                     Run 7-gate validation for current phase
|   |-- advance_phase.py                   Advance to next phase (atomic state update)
|   |-- generate_status.py                 Generate progress dashboard data
|   |-- generate_phase_report.py           Generate self-contained HTML report
|   |-- audit_gates.py                     Analyze gate effectiveness across phases
|   |-- synthesize_spec.py                 Synthesize spec from Phase 0-1 artifacts
|   |-- map_deep_plan_artifacts.py         Map /deep-plan output to SDLC artifacts
|   |-- code_host.py                       Which code host a repo is on (github / azure-devops / none) and its CLI state
|   |-- ado_import.py                      The az twin of the gh reads/writes, same dict shapes (+ ado_map, ado_transport, ado_pipelines)
|   |-- ado_outcomes.py                    Scorecard outcome events from Azure DevOps history
|   |-- import_outcomes.py                 Host-neutral scorecard import (GitHub delegates to scorecard.py)
|   |-- host_report.py                     The top-level `host` block every host-touching --json carries
|   +-- tests/                             Script test suite
|       |-- conftest.py                    Shared fixtures
|       |-- test_check_gates.py            Gate validation tests
|       +-- fixtures/code_host/            remote-urls.json (shared with Studio's vitest); azure_devops/ hand-written
|                                          documents and azure_devops/captured/ real az output with provenance
|
+-- hooks/                                 PowerShell context injection
    |-- shepherd-session-start.ps1             Session start -- phase context banner
    +-- sdlc-phase-inject.ps1              PreToolUse -- phase-aware edit reminders
```

### 4.2 Target Project Directory (Runtime)

```
target-project/                            User's project (where code lives)
+-- .sdlc/                                 Created by /sprd-setup
    |-- state.yaml                         Phase tracking, history, gate results
    |-- profile.yaml                       Immutable copy of selected profile
    |-- constitution.md                    Project constitution (scope, constraints)
    |-- reports/                           Generated HTML reports (named by registry slug)
    |   |-- 00-discovery-report.html
    |   |-- 01-requirements-report.html
    |   +-- ...
    +-- artifacts/                          Phase work products (one dir per phase slug)
        |-- 00-discovery/
        |   |-- constitution.md
        |   |-- problem-statement.md
        |   |-- success-criteria.md
        |   |-- constraints.md
        |   +-- phase1-handoff.md
        |-- 01-requirements/
        |   |-- requirements.md
        |   |-- non-functional-requirements.md
        |   |-- epics.md
        |   +-- phase2-handoff.md
        |-- 02-design/
        |   |-- design-doc.md
        |   |-- api-contracts.md
        |   |-- adr-registry.md
        |   |-- adrs/
        |   +-- phase3-handoff.md
        |-- 03-foundation/
        |   |-- foundation-report.md
        |   |-- risk-tier-map.md
        |   |-- cadence-plan.md
        |   +-- build-handoff.md
        |-- build/
        |   |-- specs/                       (optional, per-change specs)
        |   |-- build-summary.md             (optional)
        |   +-- phase7-handoff.md
        |-- 07-documentation/
        |   |-- README.md
        |   |-- api-docs.md
        |   |-- RUNBOOK.md
        |   +-- phase8-handoff.md
        |-- 08-deployment/
        |   |-- release-notes.md
        |   |-- deployment-checklist.md
        |   |-- smoke-test-results.md
        |   +-- phase9-handoff.md
        |-- 09-monitoring/
        |   |-- monitoring-config.md
        |   |-- alert-definitions.md
        |   |-- incident-response.md
        |   |-- project-retrospective.md
        |   +-- close-handoff.md
        +-- close/
            |-- final-handoff-report.md
            |-- harness-audit.md
            |-- close-gate-evidence.md
            +-- access-revocation-checklist.md
```

### 4.4 Platform-Aware Harness Install

`scripts/install_harness.py` composes the delivery harness from a `core/` payload plus
the packs a profile selects (`packs/cicd/<id>`, `packs/stacks/<id>`). `_copy_core` — the
step that lays down the platform-neutral `core/` payload before any pack overlay runs —
consults the profile's `stack.ci_cd.platform` via a layout table
(`_CORE_LAYOUT_BY_PLATFORM`) and changes what it copies and where:

- **`github-actions` / core-only (no `platform` set):** the identity layout. `core/`
  copies byte-for-byte into the target project, unchanged from every install before this
  table existed.
- **`azure-devops`:** the GitHub-only payload — `workflows/`, the profile rulesets,
  `CODEOWNERS`, `apply-branch-protection.sh` — is dropped entirely (an Azure DevOps repo
  has no use for it), and the platform-neutral governance content that both CI/CD packs
  read — `profile/rubrics/`, `eval-bypasses.md`, `dependency-exceptions.md` — is
  redirected to `.azuredevops/rails/`, the path the Azure Pipelines pack's own YAML
  actually reads. `rails-telemetry.schema.json` is the one deliberate exception: it stays
  at `.github/` on **both** platforms, because both packs' telemetry pipelines commit
  their report to the single canonical `.github/rails-telemetry.json` path, so a
  fleet-level collector can read a mixed GitHub/Azure fleet without knowing which
  platform produced any given repo's report.

This is why a repo installed with the `ado-enterprise` profile never receives a
`.github/workflows/` directory at all — the platform-aware core install and the
`packs/cicd/azure-devops` overlay agree on `.azuredevops/` as the one home for CI/CD,
governance rubrics, and rails state. `scripts/doctor.py` (§ see `docs/scripts.md`) reads
the same installed-pack signal at runtime, which is why its checks (interpreters,
required secrets, branch protection) run against `gh` on a GitHub install and `az` on an
Azure DevOps one without being told which platform a given repo uses.

### 4.5 State Machine (`state.yaml`)

The state file is initialized from `templates/state-init.yaml` with variable substitution:

```yaml
version: "1.0"
profile_id: "microsoft-enterprise"       # From ${PROFILE_ID}
project_name: "my-project"               # From ${PROJECT_NAME}
created_at: "2026-03-26T12:00:00+00:00"  # From ${CREATED_AT}
project_type: null                        # Set during Phase 0: service | app | library | skill | cli

current_phase: 0
phase_name: "discovery"

phases:
  0:
    name: discovery
    status: active          # active | completed | pending | skipped
    entered_at: "2026-03-26T12:00:00+00:00"
    completed_at: null
    gate_results: {}        # Populated by check_gates.py
    artifacts: []           # Populated as artifacts are created
  1:
    name: requirements
    status: pending
    entered_at: null
    completed_at: null
    gate_results: {}
    artifacts: []
  # ... remaining phase keys are strings: 2, 3, "build", 7, 8, 9, "close" --
  # each follows the same structure

history: []                 # Append-only log of phase transitions
```

Each phase tracks its own status lifecycle: `pending` -> `active` -> `completed` (or `skipped`). Gate results are stored per-phase so historical audit is possible.

---

## 5. Progressive Disclosure Strategy

The plugin is designed to minimize context window consumption. Claude's context is a finite resource, and loading everything at once would waste capacity needed for actual project work. The disclosure hierarchy is:

### 5.1 Layer 1: Always Loaded (Activation)

**`SKILL.md`** (~4KB) is the only document loaded automatically when the plugin activates. It contains:
- Plugin purpose and trigger phrases
- Command table (7 commands, one-line descriptions each)
- Phase overview table (9 phases with key skills)
- Human-in-the-loop protocol (when to stop and ask)
- Visual report protocol (when and how to generate reports)
- Agent orchestration protocol (mandatory spawns, parallel rules)
- Pointer to `references/` for deeper details

This single document gives Claude enough context to handle any SDLC-related request and know where to look for more detail.

### 5.2 Layer 2: Loaded on Phase Entry

**Phase definitions** (`phases/<slug>.md`, slug-named -- e.g. the Build Loop is `build-loop.md`) are loaded only when the user enters that phase. Each definition contains:
- Purpose statement
- Entry criteria
- Detailed workflow with numbered steps
- HITL GATE markers (mandatory human interaction points)
- CHECKPOINT markers (agent-enforced stopping points)
- Required and optional artifacts
- Exit criteria

Only the current phase's definition is in context at any time. Previous phase definitions are not retained.

### 5.3 Layer 3: Loaded on Explicit Request

**Reference documents** (`references/`) are loaded only when Claude needs specific details:

| Document | When Loaded | Size |
|----------|------------|------|
| `validation-rules.md` | When running gate checks or explaining gate failures | ~3KB |
| `agent-roster.md` | When spawning agents or planning parallel execution | ~2KB |
| `skill-mapping.md` | When determining which Claude Code skills to invoke | ~2KB |
| `state-machine.md` | When explaining state transitions or debugging state | ~2KB |
| `compliance-frameworks.md` | When checking compliance gates (SOC 2, HIPAA, etc.) | ~4KB |
| `deep-plan-integration.md` | When integrating with /deep-plan skill in Phases 2-3 | ~2KB |
| `acceptance-criteria.md` | When writing or evaluating acceptance criteria | ~1KB |
| `knowledge-base.md` | When domain-specific knowledge is needed | ~2KB |

### 5.4 Layer 4: Never Loaded Into Context

**Templates** are copied to the target project's `.sdlc/artifacts/` directory at initialization time by `init_project.py`. They are never loaded into Claude's context window -- Claude writes artifacts directly based on phase workflow guidance.

**HTML Reports** generated by `generate_phase_report.py` are self-contained HTML files written to `.sdlc/reports/`. They are designed to be opened in a browser, not consumed by Claude. Reports include visual elements (tables, charts, status badges) that would be wasted in a text-only context.

**Profile schema** (`profiles/_schema.yaml`) is only consumed by `validate_profile.py` during setup. Claude does not need the raw schema in context.

### 5.5 Disclosure Triggers

| Trigger | What Gets Loaded |
|---------|-----------------|
| Plugin activation | `SKILL.md` only |
| `/sprd-setup` | Profile selection UI (no extra docs) |
| `/sprd` or `/sprd-status` | Current phase definition |
| `/sprd-gate` | Current phase definition + `validation-rules.md` |
| Agent spawn | `agent-roster.md` (if routing needed) |
| Compliance check | `compliance-frameworks.md` |
| Phase 2-3 with /deep-plan | `deep-plan-integration.md` |

---

## 6. Two-Directory Model

### 6.1 The Separation Principle

The plugin operates across two distinct directory trees that serve fundamentally different purposes:

**Plugin Directory** -- Contains the plugin's source code, definitions, and templates. This directory is **immutable during use**. It may be installed globally, symlinked, or cloned as a Git repository. No script, hook, or command ever writes to this directory during normal operation. It is the "program" that runs the SDLC.

**Target Project Directory** -- Contains the user's actual project code and the `.sdlc/` subdirectory where all runtime state lives. This directory is **mutable**. Every artifact, state change, report, and configuration update happens here. It is the "data" the program operates on.

### 6.2 Why This Matters

This separation provides several critical guarantees:

1. **Multi-project support.** A single plugin installation can manage multiple projects simultaneously. Each project has its own `.sdlc/` directory with independent state.

2. **Plugin updates are safe.** Updating the plugin (new phase definitions, improved scripts, additional templates) does not affect any project's state. Projects keep their frozen `profile.yaml` and `state.yaml` intact.

3. **Clean version control.** The `.sdlc/` directory can be committed to the project's Git repository, giving the team full visibility into SDLC progress. The plugin source is tracked separately (or not at all, if installed as a dependency).

4. **No cross-contamination.** A bug in one project's state cannot corrupt the plugin or affect other projects.

### 6.3 Path Resolution in Scripts

All Python scripts receive explicit paths to both directories:

```bash
# Plugin root is resolved from the script's own location:
PLUGIN_ROOT = Path(__file__).resolve().parent.parent

# Target project paths come from CLI arguments:
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts check_gates.py \
    --state /path/to/target/.sdlc/state.yaml \
    --phase 0
```

The `--project ${CLAUDE_PLUGIN_ROOT}/scripts` flag tells `uv` where `pyproject.toml` lives (`${CLAUDE_PLUGIN_ROOT}` is the environment variable Claude Code sets to the plugin's install directory), ensuring correct dependency resolution regardless of the shell's current working directory.

### 6.4 Path Resolution in Hooks

PowerShell hooks resolve the target project from the current working directory:

```powershell
$sdlcDir = Join-Path $PWD ".sdlc"
$stateFile = Join-Path $sdlcDir "state.yaml"

if (-not (Test-Path $stateFile)) {
    exit 0  # Not an SDLC-managed project; do nothing
}
```

Hooks gracefully exit when the current directory has no `.sdlc/` folder, allowing the plugin to be installed globally without interfering with non-SDLC projects.

### 6.5 Initialization Creates the Bridge

The `/sprd-setup` command is the only operation that spans both directories:

1. Reads profile from **plugin directory**: `profiles/<name>/profile.yaml`
2. Validates against schema in **plugin directory**: `profiles/_schema.yaml`
3. Reads state template from **plugin directory**: `templates/state-init.yaml`
4. Writes everything to **target directory**: `.sdlc/state.yaml`, `.sdlc/profile.yaml`, `.sdlc/artifacts/`, `.sdlc/constitution.md`

After initialization, all subsequent operations read from and write to the target directory only (scripts reference the plugin directory only for phase definitions and the phase registry, which are read-only).

---

## 7. What this deliberately does not integrate with

**Decided 2026-09-24 by Matt. Revisit only with a reason, not with a request.**

This system has no connector for Jira, Azure Boards, Linear, or any other work tracker, and
that is a design decision rather than a missing feature. (Amended 2026-10-13: still no connector, but a
provenance-carrying projection is now allowed under three conditions. See "Amendment, 2026-10-13" at the end
of this section.)

The unit of work is a spec file in the repository. Its live status is read from the pull
request that its branch opened — which checks ran, who approved, whether it merged. The work
item and the change are therefore the same object, and cannot disagree with each other. Every
external tracker reintroduces exactly the drift this model exists to prevent: two records of
the same work, updated by different people at different times, one of them quietly wrong.

The cost is accepted openly: this does not meet a client where they already are. The judgement
is that being one coherent thing beats being everything to everyone.

### Two code hosts, one model

The spec-is-the-work-item model needs a code host to read the pull request from, and the code
lives on two: GitHub and Azure DevOps. Both are first-class. Until the code-host provider layer
(`docs/proposals/code-host-providers.md`), `handoff.py` and `spec_status.py` spoke to GitHub
through `gh` and nothing else, so an Azure DevOps project got pipelines and a board built from
spec files with no live "who is this waiting on". That gap is closed, and closed the sanctioned
way — a second **code host**, not a tracker connector.

**The repository chooses the host.** `scripts/code_host.py` reads the `origin` remote
(`github.com` → `github`; `dev.azure.com`, `*.visualstudio.com`, `ssh.dev.azure.com` →
`azure-devops`; anything else → `none`, which falls through to `gh` exactly as every repository
behaved before). `--host` on any host-touching script, the `SHEPHERD_CODE_HOST` variable (or
`SDLC_CODE_HOST`, the pre-2.0 name — still read), or a per-clone `.sdlc/code-host.yaml` (written
by `set_setting.py code-host`) sit ahead of the remote; the harness manifest breaks the tie only
when there is no usable remote. There is no global
setting and no profile field: the profile describes the CI pack, and the host is a property of
the clone.

**Two axes, never merged.** The *code host* (pull requests, reviewers, identity, branch
policies) comes from the remote; the *CI platform* (pipeline directories, runs, secrets) comes
from `.claude/harness-manifest.json`, as `doctor.py` has always read it. GitHub + Azure Pipelines
is a legitimate combination; `connection_report.py --json` reports `host` and `ci_platform` side
by side and notes a disagreement without failing on it.

**One `az` module, gh-shaped returns.** `scripts/ado_import.py` (with `ado_map.py` for the pure
translation, `ado_transport.py` for the one impure seam, `ado_pipelines.py` for runs, jobs and
variable groups) exposes the same names and signatures as the GitHub functions it stands in for
(`code_host.PROVIDER_FUNCTIONS`, pinned by `test_provider_parity.py`) and returns the dict shapes
`gh` returns today, so every pure model and every honesty path is reused rather than duplicated.
Each consuming script dispatches at its own call site, which is why the existing monkeypatch
seams — and every existing test — are untouched, and why `test_gh_argv_golden.py` can prove the
GitHub argv byte-identical. `AdoImportError` subclasses `GitHubImportError`, so the frozen
`scorecard.py` already catches an `az` failure; the scorecard import for either host is the new
`import_outcomes.py` (GitHub delegating to `scorecard.import_events`, Azure DevOps through
`ado_outcomes.py` with `ado-*` ids that never collide with `gh-*`).

**Identity.** The roster key stays `@handle` on both hosts. Azure DevOps names people by sign-in
identity (UPN), so `people[].email` in `.sdlc/team.yaml` — optional, unique — is the only way a
UPN resolves to a handle; nothing guesses from a display name. On hand-off the checker becomes a
required reviewer through that email, the developer is named in the description (Azure DevOps
has no assignee), and a missing email is an `assignment_error` with the local half complete.

**Honesty.** Every host-touching `--json` carries a top-level `host` block
(`{name, source, cli, cli_state, detail}`, `scripts/host_report.py`) read from the outcome of
the call the script just made; `cli_state` is `unknown` when nothing could be determined, never
a false no. A field Azure DevOps does not record (`updatedAt`, vote time, request time) is
`null`, a `review_wait` with no request timestamp has no `wait_hours` key, and an unreadable
category reads "not imported" — never a zero.

**Fixture provenance convention.** `scripts/tests/fixtures/code_host/azure_devops/captured/`
holds real `az` output captured 2026-10-05 from a live organisation and anonymised, each file
wrapped `{_provenance, _command, _secs, value}`; `CAPTURE-NOTES.md` beside it lists every fact
that changed the design. The folder above it keeps the older hand-written documents, marked
`_provenance: "hand-written (unverified)"`, as the only evidence for shapes no real organisation
exercised (a draft PR, a `rejected` evaluation, a non-empty `boards query`).
`test_fixture_provenance.py` fails on a missing key and lists what is still hand-written, so an
unverified shape stays visible until a capture lands. `remote-urls.json` is shared with Studio's
vitest port so the Python and TypeScript detection rules cannot drift. The contract is
`references/code-host-providers.md`.

The tracker decision above is unchanged: a second code host is a second place to read the pull
request from, not a second record of the work.

### Amendment, 2026-10-13 — a projection is not a connector

**Decided 2026-10-13 by Matt** (his agreement relayed by @splashthree), for the reasons set out in
`docs/proposals/ado-boards-mirror.md`. The 2026-09-24 decision is amended, not reversed. It now reads:

> No tracker connector; a provenance-carrying projection is allowed under the three conditions in
> `docs/proposals/ado-boards-mirror.md` §1.

A connector would make the tracker a second record of the work. A projection does not: the spec file
stays the unit of work, and the board is a view of it that a team already uses and that the plugin
keeps in step. Three conditions keep it a view, and any change that breaks one is out of bounds:

1. **Provenance on every write.** A work item the plugin touches carries the `sdlc:<kind>:<id>` tag, a
   `Hyperlink` to the source file at a commit, and a ledger line with the plan hash, the named human and
   the executing identity.
2. **Drift is first-class.** Every board revision the ledger did not produce is detected, classified by
   who owns the field, and shown; nothing is silently overwritten in either direction.
3. **The repository stays the unit of work.** `status`, `risk`, `merged` and the spec text are never
   written from the board; a reverse write goes only through the plugin verb that owns the field, under
   the same named `--by`.

Scope: Azure DevOps Boards only. Jira, Linear and every other tracker stay out. The mirror is built in
stages: setup and process discovery first (`ado_sync.py config`, `discover`, `validate`, which touch no
work item), then a read-only mirror, then writes. The plugin reads and plans by default and writes to a
board only when the project's `posture` is `assisted` and a named person confirms the plan.

---

## 8. Cross-References

This document covers the system architecture at a high level. For detailed documentation on specific subsystems, see:

| Document | Contents |
|----------|----------|
| `references/state-machine.md` | State format, field definitions, transition rules, history schema |
| `references/validation-rules.md` | 7-gate validation system, per-gate checks, severity matrix by phase |
| `references/skill-mapping.md` | Phase-to-skill mapping, when to invoke each Claude Code skill |
| `references/agent-roster.md` | Phase-to-agent mapping, parallel execution groups, spawn conditions |
| `references/compliance-frameworks.md` | SOC 2, HIPAA, GDPR, PCI-DSS gate definitions and artifact requirements |
| `references/deep-plan-integration.md` | How `/deep-plan` integrates with Phases 2-3, checkpoint/resume flow |
| `phases/phase-registry.yaml` | Master registry of all 9 phases with entry/exit gates and artifact lists |
| `profiles/_schema.yaml` | Profile validation schema with required fields and value constraints |
