# State Machine Documentation

Comprehensive reference for the SDLC plugin's state management system. All project lifecycle state is tracked in a single YAML file that serves as the source of truth for phase progress, gate results, artifact tracking, and transition history.

---

## Table of Contents

1. [State Management Overview](#1-state-management-overview)
2. [state.yaml Format](#2-stateyaml-format)
3. [State Initialization](#3-state-initialization)
4. [Phase Statuses](#4-phase-statuses)
5. [Transition Rules](#5-transition-rules)
6. [Transition Flow (advance_phase.py)](#6-transition-flow-advance_phasepy)
7. [Gate System Integration](#7-gate-system-integration)
8. [History Tracking](#8-history-tracking)
9. [session-handoff.json (Build Loop Continuity — retired from the hook)](#9-session-handoffjson-build-loop-continuity)
10. [Spec Backlog (Build Loop Tracking)](#10-spec-backlog-build-loop-tracking)
11. [State Diagram](#11-state-diagram)
12. [Cross-References](#12-cross-references)

---

## 1. State Management Overview

The SDLC plugin uses a file-based state machine to track a project's progress through 9 phases (ids `0`, `1`, `2`, `3`, `build`, `7`, `8`, `9`, `close`), ordered by the registry `order` field and advanced non-sequentially. Key principles:

- **Single file**: All state lives in `.sdlc/state.yaml` inside the target project. This is the only mutable state file for phase progression.
- **Single source of truth**: Phase progress, gate results, artifact lists, and transition history are all co-located. No external database or service is involved.
- **Atomic writes**: Scripts read the entire file, modify in memory, and write back atomically using `yaml.dump()`. There are no partial updates -- either the full state is written or the file is unchanged.
- **Profile separation**: The selected company profile is frozen at initialization time into `.sdlc/profile.yaml` and is never modified after creation. State and profile are read independently by scripts.
- **Artifact isolation**: Phase artifacts are stored in `.sdlc/artifacts/<slug>/` directories, separate from state, where `<slug>` is the registry `slug` field (`00-discovery`, `03-foundation`, `build`, `close` -- never derived by zero-padding an integer id). The state file tracks artifact paths but does not contain artifact content.

### File Layout in Target Project

```
.sdlc/
  state.yaml          # Mutable -- phase progress and history
  profile.yaml         # Immutable -- frozen copy of selected profile
  constitution.md      # Project constitution (from template)
  artifacts/
    00-discovery/      # Phase 0 artifacts
    01-requirements/   # Phase 1 artifacts
    02-design/         # Phase 2 artifacts
    03-foundation/     # Phase 3 artifacts
    build/             # Build loop artifacts (build-summary.md, phase7-handoff.md)
  sprints/             # Sprint records SNN.md (optional; written by sprint.py, never by hand)
  metrics/             # Append-only JSONL ledgers (gate-log, spec-log, loop-events, sprint-log, ...)
    07-documentation/  # Phase 7 artifacts
    08-deployment/     # Phase 8 artifacts
    09-monitoring/     # Phase 9 artifacts
    close/             # Phase C (Close & Transfer) artifacts
```

---

## 2. state.yaml Format

Below is the complete structure with every field documented. Fields use ISO 8601 timestamps in UTC.

```yaml
version: "1.0"                      # Schema version for forward compatibility
profile_id: "microsoft-enterprise"   # ID of the profile selected during /sprd-setup
project_name: "My Project"           # Human-readable project name, set during /sprd-setup
created_at: "2026-03-20T10:00:00Z"   # ISO 8601 timestamp when state was initialized
project_type: "service"              # Set during Phase 0 discovery; one of: service | app | library | skill | cli
                                     # Starts as null, populated when project type is determined

current_phase: "build"               # Active phase id; int for 0,1,2,3,7,8,9 or string 'build'/'close'
phase_name: "build"                  # Human-readable name of the current phase (mirrors registry)

phases:                              # Map of phase_id to phase tracking data (key may be int or string)
  0:
    name: discovery                  # Phase name from registry
    status: completed                # One of: pending | active | completed | skipped
    entered_at: "2026-03-20T10:00:00Z"   # When this phase became active
    completed_at: "2026-03-21T14:30:00Z" # When this phase was completed (null while active/pending)
    gate_results:                    # Results from the last gate check run (map or list)
      - gate: "G1-integrity"        #   Gate identifier
        artifact: "constitution.md"  #   Artifact being checked
        passed: true                 #   true = passed, false = failed, null = manual review needed
        message: "Artifact exists and is non-empty" # Human-readable explanation
        severity: "MUST"             #   MUST = blocking, SHOULD = advisory, MAY = informational
      - gate: "G2-completeness"
        artifact: "problem-statement.md"
        passed: true
        message: "Artifact exists and has content"
        severity: "MUST"
    artifacts:                       # List of artifact filenames produced in this phase
      - "constitution.md"
      - "problem-statement.md"
      - "stakeholder-map.md"
      - "phase1-handoff.md"
  1:
    name: requirements
    status: completed
    entered_at: "2026-03-21T15:00:00Z"
    completed_at: "2026-03-22T11:00:00Z"
    gate_results: [...]              # Same structure as above
    artifacts:
      - "requirements-spec.md"
      - "acceptance-criteria.md"
      - "phase2-handoff.md"
  # ... phases 2 (design), 3 (foundation) follow the same pattern
  build:
    name: build
    status: active                   # Currently active phase (the Build loop)
    entered_at: "2026-03-25T10:00:00Z"
    completed_at: null               # null because phase is not yet complete
    gate_results: {}                 # Empty until /sprd-gate is run
    artifacts: []                    # Populated as artifacts are created
  7:
    name: documentation
    status: pending                  # Not yet reached
    entered_at: null
    completed_at: null
    gate_results: {}
    artifacts: []
  # ... phases 8, 9, close follow with status: pending

history:                             # Append-only transition log (see Section 8)
                                     # from/to hold phase ids, which can be strings ('build', 'close')
  - from: 0
    to: 1
    at: "2026-03-21T14:30:00Z"
    gate_results:
      passed: 6
      failed: 0
      manual: 1
    justification: "All gates passed, user confirmed"
  - from: 1
    to: 2
    at: "2026-03-22T11:00:00Z"
    gate_results:
      passed: 8
      failed: 0
      manual: 0
  # ... one entry per transition
```

### Field-by-Field Reference

| Field | Type | Set By | Mutability | Description |
|-------|------|--------|------------|-------------|
| `version` | string | init_project.py | Immutable | Schema version, currently "1.0" |
| `profile_id` | string | init_project.py | Immutable | Profile selected at setup |
| `project_name` | string | init_project.py | Immutable | Project name from user input or directory name |
| `created_at` | string | init_project.py | Immutable | ISO 8601 creation timestamp |
| `project_type` | string/null | Phase 0 work | Set once | Determined during discovery; null until set |
| `current_phase` | int\|string | advance_phase.py | Updated on transition | Active phase id (may be a string: build, close) |
| `phase_name` | string | advance_phase.py | Updated on transition | Human-readable name of current phase |
| `phases[N].name` | string | init_project.py | Immutable | Phase name from registry |
| `phases[N].status` | string | advance_phase.py | Updated on transition | pending, active, completed, or skipped |
| `phases[N].entered_at` | string/null | advance_phase.py | Set once per entry | Timestamp when phase became active |
| `phases[N].completed_at` | string/null | advance_phase.py | Set once per completion | Timestamp when phase was completed |
| `phases[N].gate_results` | list/map | check_gates.py | Overwritten each gate run | Results from most recent gate evaluation |
| `phases[N].artifacts` | list | Commands/agents | Appended | Filenames of artifacts produced |
| `history[]` | list | advance_phase.py | Append-only | Transition log entries |

---

## 3. State Initialization

State initialization occurs when a user runs `/sprd-setup`, which calls `init_project.py`.

### Process

1. **Read profile**: `init_project.py` loads the selected profile YAML (e.g., `profiles/microsoft-enterprise/profile.yaml`).
2. **Read template**: The template at `templates/state-init.yaml` is read as raw text.
3. **Variable substitution**: Three placeholders are replaced:
   - `${PROFILE_ID}` -- from `profile.company.profile_id`
   - `${PROJECT_NAME}` -- from `--name` argument or target directory name
   - `${CREATED_AT}` -- current UTC timestamp in ISO 8601 format
4. **Write state file**: The substituted content is written to `.sdlc/state.yaml`.
5. **Freeze profile**: The full profile YAML is copied to `.sdlc/profile.yaml` (never modified after this point).
6. **Create directories**: All 9 artifact directories, one per phase slug (`00-discovery`, `01-requirements`, `02-design`, `03-foundation`, `build`, `07-documentation`, `08-deployment`, `09-monitoring`, `close`), are created under `.sdlc/artifacts/`.

### Initial State

After initialization, the state has these properties:

- `current_phase`: 0
- `phase_name`: "discovery"
- `project_type`: null (set during Phase 0 when the project type is determined)
- Phase 0 status: `active` with `entered_at` set to creation timestamp
- All phases after Discovery: `pending` with `entered_at` and `completed_at` both null
- All `gate_results`: empty map `{}`
- All `artifacts`: empty list `[]`
- `history`: empty list `[]`

---

## 4. Phase Statuses

Each phase has one of four statuses:

| Status | Meaning | entered_at | completed_at |
|--------|---------|------------|--------------|
| `pending` | Phase has not been reached yet | null | null |
| `active` | Phase is currently in progress | Set | null |
| `completed` | Phase finished, all gates passed | Set | Set |
| `skipped` | Phase was explicitly skipped with justification | Set | Set |

Only one phase can be `active` at any time. Skipping requires explicit justification recorded in the transition history.

---

## 5. Transition Rules

Four invariants govern all phase transitions:

### Rule 1: Forward Only
Phases advance in registry `order` (`0`, `1`, `2`, `3`, `build`, `7`, `8`, `9`, `close`), not by id; `build` and `close` are non-numeric ids. The gap where ids 4/5/6 sat is intentional -- batched checking is the rejected anti-pattern; checking happens per-change in the Build loop. The system does not support backward transitions through the normal advance flow. Skipping a phase requires explicit justification recorded in history.

### Rule 2: Gate Required
Every transition from a phase to the next by registry order requires ALL exit gates with `severity: MUST` to pass. Gates with `severity: SHOULD` or `severity: MAY` produce warnings but do not block advancement.

### Rule 3: Atomic Transitions
State updates are all-or-nothing. The `advance_phase.py` script performs all state mutations in memory and writes the entire file in a single `yaml.dump()` call. If gate checking fails or any error occurs before the write, the state file remains unchanged.

### Rule 4: Re-entry Allowed
If issues are discovered in a later phase that require revisiting an earlier phase, re-entry is permitted. This creates a new history entry with `reentry: true`, distinguishing it from the original forward progression. The re-entered phase's status returns to `active`.

### Rule 5: Manual Approval
Every phase is `approval: manual` now; there is no `automatic`. Advancement always requires the `--confirmed` flag / human sign-off, enforced in `advance_phase.py`.

All phases require manual approval:
- Phase 0 (Discovery): manual
- Phase 1 (Requirements): manual
- Phase 2 (Design): manual
- Phase 3 (Foundation): manual
- Build Loop (`build`): manual
- Phase 7 (Documentation): manual
- Phase 8 (Deployment): manual
- Phase 9 (Monitoring): manual
- Phase C (`close`, Close & Transfer): manual

---

## 6. Transition Flow (advance_phase.py)

The `advance_phase.py` script implements the complete transition logic. It accepts two arguments: `--state` (path to state.yaml) and optionally `--confirmed` (human sign-off flag).

### Step-by-Step Execution

```
1. LOAD STATE
   - Read .sdlc/state.yaml
   - Read .sdlc/profile.yaml
   - Extract current_phase from state

2. BOUNDARY CHECK
   - If the current phase is `terminal` (close): print "already complete", exit 0

3. RUN GATE CHECKS
   - Call check_phase_gates(current_phase, state, profile, artifacts_base)
   - Print formatted gate results

4. EVALUATE MUST GATES
   - Collect all results where passed == false AND severity == "MUST"
   - If any MUST failures exist:
     Print "BLOCKED" with failure count
     Exit with code 1 (gate failure)

5. EVALUATE MANUAL GATES
   - Collect all results where passed == null (manual review needed)
   - If manual gates exist AND --confirmed is NOT set:
     Print "REVIEW REQUIRED" with list of manual gates
     Print instructions for stakeholder review
     Exit with code 1

6. DRY RUN CHECK
   - If --confirmed is NOT set (and no blockers):
     Print "Dry run complete -- all automated gates passed"
     Print instructions to re-run with --confirmed
     Exit with code 0

7. ADVANCE STATE (only reached with --confirmed and all MUST gates passing)
   a. Set phases[current_phase].status = "completed"
   b. Set phases[current_phase].completed_at = current UTC timestamp
   c. Store gate result summary in phases[current_phase].gate_results
   d. Set phases[next_phase].status = "active"
   e. Set phases[next_phase].entered_at = current UTC timestamp
   f. Set current_phase to the next phase by registry `order` (look up via phase_model.py -- NOT id+1)
   g. Update phase_name to next phase's name
   h. Append transition entry to history[] array

8. WRITE STATE
   - Write entire state dict to state.yaml via yaml.dump()

9. OUTPUT GUIDANCE
   - Print confirmation of transition
   - Display next phase: name, description, skills, required artifacts
   - Print artifact directory path and phase definition file reference
```

### Return Codes

| Code | Meaning |
|------|---------|
| 0 | Success (advanced) or dry run passed |
| 1 | Gate failure (MUST gates failed or manual approval needed) |
| 2 | System error (missing profile, missing phase definition, file not found) |

---

## 7. Gate System Integration

Gate checks are performed by `check_gates.py` and are invoked both by `/sprd-gate` (standalone check) and by `advance_phase.py` (as part of transition).

### Gate Types

| Gate ID | Name | What It Checks | Severity |
|---------|------|----------------|----------|
| G1-integrity | Artifact Integrity | Required artifacts exist on disk | MUST |
| G2-completeness | Artifact Completeness | Required artifacts are non-empty and have expected content | MUST |
| G3-metrics | Quality Metrics | Code coverage, test pass rates -- quantitative thresholds checked per-change in the Build loop | MUST |
| G4-compliance | Compliance | Framework-specific requirements from profile (e.g., SOC2, HIPAA) | Varies |
| G5-consistency | Cross-Phase Consistency | Detects drift in locked metrics across transitions (budget, timeline, scope, stakeholder roster, quality thresholds, compliance reqs) | SHOULD |
| G6-quality | Quality Standards | Profile-defined quality thresholds | SHOULD |

### Gate Result Structure

Each gate check produces a result object:

```yaml
gate: "G1-integrity"          # Gate identifier
artifact: "requirements.md"   # What was checked (artifact name or check description)
passed: true                  # true | false | null (null = manual review required)
message: "Artifact exists"    # Human-readable explanation
severity: "MUST"              # MUST | SHOULD | MAY
```

### Severity Levels (RFC 2119)

- **MUST**: Blocking. Transition is prevented if any MUST gate fails.
- **SHOULD**: Advisory. Produces a warning but does not block transition.
- **MAY**: Informational. Logged for completeness, never blocks.

### Phase-Specific Gate Behavior

- **Build loop**: the gate prints an INFO-level spec-backlog summary from `track_specs.py` -- counts by status (merged / in-flight / ready / draft) and risk tier, plus the in-flight list. It reads the spec frontmatter directly and does not block.
- **Build loop**: G3-metrics checks profile quality thresholds such as `coverage_minimum` per-change.
- **Compliance phases**: G4-compliance loads framework-specific gates from `profiles/<id>/compliance/<framework>-gates.yaml`.

---

## 8. History Tracking

The `history` array in state.yaml is an append-only audit trail of every phase transition. Entries are never modified or deleted after writing.

### History Entry Structure

```yaml
- from: 3                              # Source phase ID
  to: 4                                # Destination phase ID
  at: "2026-03-25T10:00:00Z"           # ISO 8601 transition timestamp
  gate_results:                         # Summary counts (not full results)
    passed: 12                          #   Number of gates that passed
    failed: 0                           #   Number of gates that failed
    manual: 1                           #   Number of manual-review gates
  justification: "All gates passed"     # Human-readable reason for transition
```

### Re-entry Entries

When a completed phase is re-entered, the history entry includes `reentry: true`:

```yaml
- from: build
  to: 3
  at: "2026-03-28T09:00:00Z"
  reentry: true
  justification: "Foundation rails gap discovered during the Build loop, re-entering Foundation"
```

### Audit Analysis

The `audit_gates.py` script reads the complete history and gate results to produce an effectiveness report. It analyzes:

- Gate pass/fail rates across all completed phases
- Override history (gates that were overridden with justification)
- Patterns suggesting gates that are always passing (may be too lenient) or frequently failing (may need adjustment)

The audit report is used for process improvement and is typically run after several phases are complete or at project retrospective (Phase 9).

---

## 9. session-handoff.json (Build Loop Continuity)

Located at: `.sdlc/artifacts/build/session-handoff.json`

The Build loop often spans multiple Claude Code sessions. The spec is the durable source of truth across them (see section 10); an engagement *may* additionally keep this machine-readable handoff file for its own notes. **Nothing in the plugin reads it any more** — the session-start hook's Build-loop summary of it was retired in 1.6.0 (it was a section-plan progress model competing with the spec backlog). The retired `current_sprint` field is gone: the active sprint lives in `.sdlc/sprints/SNN.md` (section 10) and the hook prints it as `[SHEPHERD-SPRINT]`.

### Complete Schema

```json
{
  "$schema": "session-handoff-v1",
  "phase": "build",
  "last_updated": "2026-03-26T15:00:00Z",
  "session_number": 3,
  "overall_status": "in_progress",
  "sections": [
    {
      "id": "SECTION-001",
      "name": "Authentication Service",
      "status": "complete",
      "agent": "deep-implement",
      "started_at": "2026-03-25T10:00:00Z",
      "completed_at": "2026-03-25T14:30:00Z",
      "evaluator_result": "passed",
      "notes": "TDD approach, 94% coverage"
    },
    {
      "id": "SECTION-004",
      "name": "API Gateway",
      "status": "in_progress",
      "agent": "deep-implement",
      "started_at": "2026-03-26T09:00:00Z",
      "completed_at": null,
      "evaluator_result": null,
      "notes": "Data layer complete, routing in progress"
    }
  ],
  "completed_this_session": ["SECTION-003"],
  "in_progress": ["SECTION-004"],
  "blocked": [],
  "next_actions": [
    {
      "action": "Complete API Gateway routing layer",
      "section": "SECTION-004",
      "priority": "P0",
      "context": "Data layer done, need route definitions and middleware"
    },
    {
      "action": "Write integration tests for SECTION-003",
      "section": "SECTION-003",
      "priority": "P1",
      "context": "Unit tests complete, integration tests deferred"
    }
  ],
  "blockers": [
    {
      "description": "Waiting for API schema from backend team",
      "section": "SECTION-005",
      "resolved": false
    }
  ],
  "decisions_this_session": [
    "Chose WebSocket over SSE for real-time updates"
  ],
  "deviations_this_session": [],
  "context_for_next_session": "SECTION-004 routing layer is 60% done. Start with route registration in gateway.ts."
}
```

### Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `$schema` | string | Schema identifier, always "session-handoff-v1" |
| `phase` | string | Always 'build' |
| `last_updated` | string/null | ISO 8601 timestamp of last update |
| `session_number` | int | Incremented each session |
| `overall_status` | string | "in_progress", "blocked", or "complete" |
| `sections[]` | array | Per-section tracking with status, agent, timestamps |
| `completed_this_session` | array | Section IDs finished in the current/last session |
| `in_progress` | array | Section IDs actively being worked |
| `blocked` | array | Section IDs that cannot proceed |
| `next_actions[]` | array | Prioritized action items for the next session |
| `blockers[]` | array | Active blockers with resolution status |
| `decisions_this_session` | array | Technical decisions made during the session |
| `deviations_this_session` | array | Deviations from the original plan |
| `context_for_next_session` | string | Free-text context for session continuity |

### Hook Integration

Neither session-start hook twin (`shepherd-session-start.sh` / `.ps1`) reads this file. Since 1.6.0 the Build-loop continuity line comes from the sprint layer instead: for every record under `.sdlc/sprints/*.md` whose `state:` is not `closed`, the hook prints

```
[SHEPHERD-SPRINT] S07 (ready) — "Ship the duplicate-claim rail" — 2026-09-28 → 2026-10-09
```

read with grep/sed only (no Python, no JSON, no date arithmetic), silent when the directory is absent. See [hooks.md](hooks.md).

---

## 10. Spec Backlog (Build Loop Tracking)

In the delivery-standard Build loop, the **spec is the unit of work** (one spec = one branch = one PR) and the durable source of truth. Build-loop progress is therefore derived directly from the spec files' own frontmatter -- not from a separate hand-maintained tracker that can drift from reality. The retired `sections-progress.json` model has been removed from the Build loop.

### Where Specs Live

Specs live in `<repo>/specs/NNNN-name.md` -- in version control, alongside the code, **not** under `.sdlc/`. Each spec carries YAML frontmatter:

```yaml
---
spec: "0007"
name: "Authentication Service"
status: in-flight     # draft -> ready -> in-flight -> merged, or deferred (side branch)
risk: HIGH            # HIGH / MEDIUM / LOW
---
```

### Status Values

| Status | Meaning |
|--------|---------|
| `draft` | Spec is being written; not yet ready to build |
| `ready` | Spec is approved and queued in the backlog |
| `in-flight` | Spec is on a branch, being implemented or awaiting merge |
| `merged` | Spec's PR has merged; the change is done |
| `deferred` | The team deliberately chose not to build it; `deferred_reason` says why. Never continues to merged; keeps its number |

### Progress Tracking via track_specs.py

`scripts/track_specs.py` derives the backlog state by scanning the spec files:

1. Scans `<repo>/specs/*.md` and reads each spec's frontmatter `status` and `risk`.
2. Reports totals, a status breakdown (merged / in-flight / ready / draft, plus deferred on its own line once any spec uses it), a risk breakdown (HIGH / MEDIUM / LOW), and the in-flight list (deferred specs are never in it).
3. Can flag a WIP-cap breach with `--wip-cap N` (exits non-zero) when more specs are in-flight than the cap allows.

It runs standalone (`--repo <path>`) or in-workflow (`--state .sdlc/state.yaml`, where the repo root is the directory containing `.sdlc/`). In the Build loop, `check_gates.py` prints this summary as **INFO** -- it reads progress from reality and does not block.

### Sprint Layer (Optional Commitment Windows)

A sprint is a *commitment window over the backlog order* -- never a second backlog, a reordering, or a gate. The layer is additive and advisory; it never writes `state.yaml` and never checks G1-G7.

**Sprint record -- `.sdlc/sprints/SNN.md`** (from `templates/phases/build/sprint.md`; id human-typed, `^S\d{2,}$`):

| Field | Values | Note |
|-------|--------|------|
| `sprint` | `"S07"` | typed at `sprint.py new`, one record per id |
| `goal` | one outcome-shaped sentence | |
| `start`, `end` | ISO dates | `end` defaults to the last business day of a 10-business-day window that starts on `start` (start is day 1: Mon 2026-09-28 -> Fri 2026-10-09) |
| `state` | `planning` -> `ready` -> `closed` | human-triggered, forward only |
| `target` | integer | how many specs to slate -- a count, never a size |
| `mix` | `"HIGH:1,MEDIUM:2,LOW:3"` | by risk tier; counts sum <= `target`; a breach warns, never blocks |
| `board_ref` | free text | manual board mapping only (e.g. "ADO Iteration 6"); nothing reads it |
| `readied_by`, `closed_by` | named humans | |
| `## Slate` / `## Close` | rendered tables | written by `sprint.py`, never hand-edited |

**Spec frontmatter -- five optional keys**, inserted after `status:` by `sprint.py` on first write (values `""`, enumerations, names and spec ids only; `status` is *not* one of them and stays hand-moved):

| Key | Values | Written by | Read by |
|-----|--------|------------|---------|
| `sprint` | `""` or `SNN` | `slate`, `unslate`, `close --carry-to` | `track_specs --sprint` / `by_sprint`, `sprint.py` (the hook reads `.sdlc/sprints/SNN.md`, not this key) |
| `next_owner` | a name | `handoff`; cleared by `ack` | `status`, the `/sprd-refine` agenda |
| `eng_review` | `pending \| accepted \| returned \| n-a` | `verdict --lane eng` | the ready rule |
| `data_review` | `pending \| accepted \| returned \| n-a` | `verdict --lane data` (`n-a` needs `--reason`) | the ready rule |
| `depends_on` | `""` or comma-separated spec ids | `/sprd-refine` proposes, a human confirms | build order, next-up, `slate` warning, ready gap |

**Ledger -- `.sdlc/metrics/sprint-log.jsonl`** (append-only; events `sprint_new`, `slated`, `unslated`, `handoff`, `ack`, `verdict`, `ready`, `closed`, `carried`, `dropped`; `ts` is full ISO UTC). Writers write frontmatter first, then the ledger line; if the append fails the script prints `DRIFT` and exits 1. A spec without the keys behaves exactly as before; a spec with `sprint: ""` and `status: merged` is bucketed `pre-sprint` by `track_specs.py`. See `references/sprint-model.md`.

---

## 11. State Diagram

### Individual Phase Lifecycle

```
                     +---------------------------+
                     |                           |
                     v                           |
  +---------+    +--------+    +-----------+     |
  | pending | -> | active | -> | completed |     |
  +---------+    +--------+    +-----------+     |
                     |                           |
                     |    (re-entry from         |
                     |     later phase)          |
                     |                           |
                     +------ reentry: true ------+
```

A phase starts as `pending`. When the previous phase completes and transitions forward, the next phase becomes `active`. When all exit gates pass and the user confirms, the active phase becomes `completed`. If issues are discovered later, a completed phase may be re-entered (returning to `active`).

### Complete Project Lifecycle

```
  Phase 0       Phase 1          Phase 2        Phase 3
  Discovery --> Requirements --> Design ------> Foundation -->
  [active]      [pending]        [pending]       [pending]
    |              |                |               |
    | gates pass   | gates pass    | gates pass    | gates pass
    | + confirm    | + confirm     | + confirm     | + confirm
    v              v                v               v

  Build Loop                          Phase 7         Phase 8
  (Intent -> Delegate -> Discern) --> Documentation -> Deployment -->
  [pending]                           [pending]        [pending]
    |                                     |               |
    | human declares feature-complete     | gates pass    | gates pass
    | (no batch exit gate) + confirm       | + confirm     | + confirm
    v                                     v               v

  Phase 9          Phase C
  Monitoring -----> Close & Transfer
  [pending]         [pending, terminal]
    |                  |
    | gates pass       | gates pass + confirm
    | + confirm        v
    v               [PROJECT COMPLETE]
```

The Build Loop has no batch exit gate -- checking happens per-change inside the loop; a human declares the backlog feature-complete to leave. Every transition requires gates to pass plus manual `--confirmed` sign-off.

### Transition Decision Tree

```
/sprd-next invoked
  |
  +-> Read state.yaml (current_phase)
  |
  +-> current phase is terminal (close)?
  |     YES -> "Already complete" (exit 0)
  |     NO  -> Continue
  |
  +-> Run check_phase_gates()
  |
  +-> Any MUST gates failed?
  |     YES -> "BLOCKED" (exit 1)
  |     NO  -> Continue
  |
  +-> Any manual gates (passed == null)?
  |     YES -> --confirmed flag set?
  |     |        NO  -> "REVIEW REQUIRED" (exit 1)
  |     |        YES -> Continue
  |     NO  -> Continue
  |
  +-> --confirmed flag set?
  |     NO  -> "Dry run complete" (exit 0)
  |     YES -> Continue
  |
  +-> ADVANCE STATE
  |     - Complete current phase
  |     - Activate next phase
  |     - Append to history
  |     - Write state.yaml
  |
  +-> Print next phase guidance (exit 0)
```

---

## 12. Cross-References

| Topic | File | Description |
|-------|------|-------------|
| Advance logic | `scripts/advance_phase.py` | Full transition implementation |
| Gate checking | `scripts/check_gates.py` | Gate evaluation for all 6 gate types |
| Phase model | `scripts/phase_model.py` | Single source of truth for phase ids, order, slugs (reads phase-registry.yaml) |
| State init | `scripts/init_project.py` | Creates .sdlc/ directory and state.yaml |
| Gate audit | `scripts/audit_gates.py` | Analyzes gate effectiveness across history |
| Status dashboard | `scripts/generate_status.py` | Generates status report from state |
| Phase report | `scripts/generate_phase_report.py` | Generates HTML gate report for stakeholders |
| Profile validation | `scripts/validate_profile.py` | Validates profile YAML against schema |
| State template | `templates/state-init.yaml` | Template with placeholders for initialization |
| Phase registry | `phases/phase-registry.yaml` | Phase definitions, gates, artifacts, skills |
| /sprd-next command | `commands/sprd-next.md` | User-facing command that invokes advance_phase.py |
| /sprd-gate command | `commands/sprd-gate.md` | User-facing command that runs gate checks |
| Session hook | `hooks/shepherd-session-start.ps1` (+ `.sh` twin) | Reads state, frozen layers, and active sprint records at session start |
| Sprint CLI | `scripts/sprint.py` | Sprint records, spec sprint keys, and the sprint ledger (never writes `state.yaml`) |
| Sprint template | `templates/phases/build/sprint.md` | Shape of `.sdlc/sprints/SNN.md` |
| State machine ref | `references/state-machine.md` | Concise reference (progressive disclosure) |
