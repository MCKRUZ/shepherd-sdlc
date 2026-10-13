# State Machine Reference

## Overview

The SDLC state machine tracks project progress through 9 phases. Phases have **string ids** and run in a defined **order**, not a contiguous integer sequence. State is persisted in `.sdlc/state.yaml` in the target project directory.

The phase ids and their order are defined by the registry (`phases/phase-registry.yaml`) and consumed through `scripts/phase_model.py` — the single source of truth. The lifecycle order is:

```
0 → 1 → 2 → 3 → build → 7 → 8 → 9 → close
(Discovery, Requirements, Design, Foundation, Build Loop,
 Documentation, Deployment, Monitoring, Close & Transfer)
```

Ids are strings (`"0"`, `"1"`, `"2"`, `"3"`, `"build"`, `"7"`, `"8"`, `"9"`, `"close"`). The numeric gap where `4`/`5`/`6` used to be (Implementation/Quality/Testing) is intentional: those batch phases were replaced by the continuous **Build loop**, where checking happens per change rather than as a later batch phase.

## State File Format

```yaml
version: "1.0"
profile_id: "microsoft-enterprise"
project_name: "my-project"
created_at: "2026-03-17T10:00:00Z"

current_phase: "0"        # Active phase id (string)
phase_name: "discovery"   # Human-readable phase name

phases:
  "0":
    name: discovery
    status: active         # pending | active | completed | skipped
    entered_at: "..."      # ISO 8601 timestamp
    completed_at: null      # null until phase exits
    gate_results:           # Map of gate_id → pass/fail + details
      artifact-check:
        passed: true
        checked_at: "..."
    artifacts:              # Files produced during this phase
      - path: ".sdlc/artifacts/00-discovery/problem-statement.md"
        created_at: "..."

history:                    # Append-only transition log
  - from: "0"
    to: "1"
    at: "..."
    gate_results: { ... }
```

Phase keys in `phases:` are the string ids — `"0"`, `"1"`, …, `"build"`, …, `"close"`. The `from`/`to` fields in `history` are likewise string ids.

## Phase Statuses

| Status | Meaning |
|--------|---------|
| `pending` | Phase has not been entered yet |
| `active` | Currently working in this phase |
| `completed` | All exit gates passed, phase done |
| `skipped` | Phase intentionally skipped (requires justification) |

## Transition Rules

1. **Forward by order** — the next phase is the registry entry with `order + 1`, never `id + 1` (ids are strings and may be non-numeric). The lifecycle sequence is `0 → 1 → 2 → 3 → build → 7 → 8 → 9 → close`. Skipping requires explicit justification recorded in history.
2. **Always manual** — advancement is never automatic. Every transition requires explicit human approval (`/sprd-next` after the gate passes); there is no auto-advance.
3. **Gate required** — transition out of a phase requires ALL of that phase's exit gates to pass before advancement. The **Build loop** (`build`) is the exception: it has no batch artifact exit gate — checking happens per change, and a human declares the backlog feature-complete to leave.
4. **Re-entry allowed** — a completed phase MAY be re-entered if issues are discovered. This creates a new history entry with `reentry: true`.
5. **Atomic transitions** — state.yaml is updated atomically. If gate checking fails mid-way, no transition occurs.
6. **Terminal phase** — `close` (Close & Transfer) is the terminal phase; it has no next.

## Gate Check Flow

```
/sprd-next invoked
  → Read state.yaml → get current_phase (string id)
  → Load phase-registry.yaml via phase_model.py → get exit_gates for current phase
  → Run check_gates.py with phase + profile context
  → For each gate:
      Check artifact existence
      Check artifact completeness (non-empty, required sections)
      Check quality thresholds (coverage, review status)
      Record result in gate_results
  → If ALL gates pass AND human approves:
      Set current phase status = completed
      Resolve next phase = registry entry with order + 1
      Set next phase status = active
      Update current_phase to the next phase id (string)
      Append to history
  → If ANY gate fails:
      Return failure report with specific blockers
      Suggest remediation actions
```

The `build` phase has no batch artifact gate; leaving it is a human declaration that the backlog is feature-complete (plus the `phase7-handoff.md` handoff). The resolution of "next phase" is always by registry `order`, computed through `phase_model.py` — never by incrementing the id.

## Artifact Directories

Each phase stores artifacts in `.sdlc/artifacts/<slug>/`, where `<slug>` is the registry's `slug` field — never derived by zero-padding the id:

```
.sdlc/artifacts/
├── 00-discovery/
│   ├── problem-statement.md
│   └── stakeholder-notes.md
├── 01-requirements/
│   ├── requirements.md
│   └── acceptance-criteria.md
├── 02-design/
│   ├── design-doc.md
│   ├── api-contracts.md
│   └── adrs/
├── 03-foundation/
│   ├── foundation-report.md
│   └── section-plans/
├── build/
│   ├── specs/
│   └── (source code — tracked via git; checking is per change)
├── 07-documentation/
├── 08-deployment/
│   └── release-notes.md
├── 09-monitoring/
│   └── monitoring-config.md
└── close/
    └── final-handoff-report.md
```

There are no `04-implementation/`, `05-quality/`, or `06-testing/` directories — that work happens continuously inside `build/`.

## Commands That Modify State

| Command | Effect on State |
|---------|----------------|
| `/sprd-setup` | Creates initial state.yaml |
| `/sprd-next` | Advances current_phase if gates pass |
| `/sprd-gate` | Records gate_results but does NOT advance |
| `/sprd-status` | Read-only — no state changes |
| `/sprd` | Read-only — no state changes |
