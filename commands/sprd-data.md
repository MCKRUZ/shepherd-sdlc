# /sdlc-data — Author the Data Contract, Readiness, and Lineage for a Feature

Give Data a first-class drafting seat: the **data contract** (PII-classified), the **data-readiness**
assessment, and the **lineage / audit** design for a feature or spec. It sharpens Scope, surfaces the
PII that drives risk tier, and turns readiness gaps into tracked decisions. Interview-driven like
`/sdlc-coach`: the `data-analyst` agent assesses what's there, asks focused questions, and drafts as
answers arrive. It **proposes**; a named human **decides** (the One Rule). Works inside an SDLC project
or standalone.

## Instructions

1. **Resolve context:**
   - **Workflow mode** (default): `.sdlc/state.yaml` exists. Read the feature-brief / spec Scope and any
     `data-*` artifacts; outputs land in `.sdlc/artifacts/02-design/data/`.
   - **Standalone mode** (`--repo <path>`, or no `.sdlc/` found): operate on the given repo with
     provisional context; write to `--output` (default alongside the repo) and note the missing context
     in the artifact headers.

2. **Assess what exists:** Read the feature-brief's Data touchpoints section, any success-criteria
   baseline, and the current data artifacts — which fields are named, which sources are known, what is
   still unclassified.

3. **Run the interview:** Spawn the `data-analyst` agent (Data discipline). It runs the coach-style
   dialogue — which fields the feature reads or writes, their sources and types, which are **PII or
   customer-linked**, whether the data is actually available and complete, and how it flows end to end
   (lineage + retention). It drafts three artifacts from the templates in
   `templates/phases/02-design/data/`:
   - `data-contract.md` — the field table with an explicit **PII?** column.
   - `data-readiness.md` — availability / completeness / quality, with gaps flagged (advisory).
   - `lineage-audit.md` — source → transform → sink flow with retention and audit points.

4. **Confirm PII and route readiness gaps with the human:**

> **HITL GATE:** Present the data findings using the `AskUserQuestion` tool. Ask:
> (1) Confirm the **PII classification** on each field — PII is a **risk-tier driver** (it pushes the
>     dependent specs toward HIGH); the analyst proposes, a named human confirms.
> (2) Which **readiness gaps** (missing / low-quality data) become **decision-log** items (owner +
>     2-business-day clock) — readiness is advisory and never blocks; the analyst never decides the fix.
> Data proposes; a named human signs the data-contract section at the Phase-2 gate (captured in state).

5. **Open decision-log items:** For each readiness gap the human routed, append an entry to the
   decision-log (`templates/phases/01-requirements/decision-log.md` shape) with owner + clock — workflow
   writes `.sdlc/decision-log.md`, standalone writes `<repo>/decision-log.md`. These surface in
   `/sdlc-status` and `track_decisions.py`.

6. **Report:**
   ```
   Data Artifacts Authored
   =======================
   Artifacts: data-contract.md, data-readiness.md, lineage-audit.md
   PII:       N fields classified PII (risk-tier driver: <specs pushed HIGH> | none)
   Readiness: X gaps flagged (advisory) → M decision-log items (owners: …) | ready
   Next: feed PII into the spec's risk tier at /sdlc-spec; readiness gaps ride the decision-log.
   ```

## Arguments

- No arguments: workflow mode — author against the current project's feature/spec.
- `--repo <path>`: standalone mode — author in any repo with no `.sdlc/` present.
- `--feature <id>` / `--spec <path>`: scope the data work to a feature or spec (otherwise inferred/asked).
- `--output <path>`: override the output location (standalone).

## Important

- **PII classification is a risk-tier driver, not a label.** Confirmed PII pushes dependent specs toward
  HIGH; the analyst proposes the classification, a named human confirms it, and the tier is owned at
  `/sdlc-spec` time.
- **Data readiness is advisory** — a gap is a flagged decision, never a block. It becomes a decision-log
  item with an owner and a clock, not a gate failure.
- Product-specific data compliance (e.g. SOC 2 call-recording, retention law) is configured **at build
  time** via the existing per-engagement compliance mechanism — it is not this command's job.
- These artifacts are **optional** for gate purposes; an unfilled section is an advisory flag. Data
  proposes; a named human signs at the phase gate. The command changes no protected core.
