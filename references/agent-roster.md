# Agent Roster — Phase-to-Subagent Mapping

Maps each SDLC phase to the subagents that MUST or SHOULD be spawned via the Agent tool. This is
the authoritative reference for agent orchestration decisions.

**Every agent named in this document exists.** It ships in `agents/` or `harness/agents/`, or it is
a Claude Code built-in (`Explore`, `Plan`). That is enforced by
`scripts/tests/test_agent_references.py` — a spawn that resolves to nothing is a silent no-op, and
the phase carries on as though the work were done.

**Most phase work is not delegated at all.** Phases 0–3, the Build loop and phases 7–9 describe
their work as steps that Claude performs directly. An agent is used where isolation genuinely buys
something: a fresh perspective on work Claude just did, a bounded search, a specialist discipline.
The absence of an agent from a row below is not a gap.

## How to Read This Document

- **Primary agents** are spawned for every project in this phase.
- **Conditional agents** are spawned only when a stated condition is true.
- **Parallel group** — agents within the same group MUST be launched in a single message with
  multiple Agent tool calls.
- **Background** agents run with `run_in_background: true` so they do not block the main workflow.

---

## Phase 0: Discovery

| Role | Agent | Condition | Parallel Group | Background |
|------|-------|-----------|----------------|------------|
| Codebase exploration | `Explore` | Existing codebase to analyze | — | No |
| Cross-document analysis | `discovery-analyst` | Step 0d: document intake ran AND a stakeholder workshop is planned | — | No |

**Notes:** Phase 0 is primarily human-driven. Agent use is minimal — mostly exploratory reads.
The `discovery-analyst` produces `contradiction-list.md` and `question-list.md` for the
workshop brief (`/sprd-brief`); its outputs are questions for humans, never answers.

---

## Phase 1: Requirements

| Role | Agent | Condition | Parallel Group | Background |
|------|-------|-----------|----------------|------------|
| Codebase exploration | `Explore` | Existing codebase to understand | — | No |
| Feature decomposition (Product) | `feature-architect` | Featuring a channel-bound feature (epic→feature→spec, via `/sprd-feature`) | — | No |
| Business rules + scenarios (Bizreq) | `bizreq-analyst` | Business rules (BR-NN) or golden scenarios (SCEN-NN) to capture (via `/sprd-rules`) | — | No |
| Requirements drafting | `requirements-analyst` | Decomposing the problem into FR/NFR with acceptance criteria | — | No |

**Note:** `feature-architect` and `bizreq-analyst` also double as `/sprd-review` council lenses
(Product / Bizreq viewpoints). They draft and interrogate; a named human decides (the One Rule).

---

## Phase 2: Design

| Role | Agent | Condition | Parallel Group | Background |
|------|-------|-----------|----------------|------------|
| Architecture design | `architect` | Always | — | No |
| Security model review | `security-reviewer` | Auth, payments, or sensitive data in scope | — | No |
| Multi-perspective review | `multi-reviewer` | Suggested before `/sprd-gate`; use `--council` mode | — | No |
| Experience design — web | `visual-designer` | A `channel: ag-ui`/web surface is in scope (via `/sprd-experience`) | design-B | No |
| Experience design — voice/chat | `conversation-designer` | A `channel: voice`/`chat` surface is in scope (via `/sprd-experience`) | design-B | No |
| Data contract + readiness | `data-analyst` | Feature touches data or PII (via `/sprd-data`) | — | No |
| Regulatory review | `compliance-checker` | The domain carries regulatory obligations | — | No |
| Codebase exploration | `Explore` | Existing codebase being extended | — | No |

**Parallel group `design-B`:** When a feature spans a web surface and a voice/chat surface, spawn `visual-designer` and `conversation-designer` in the same message — they author different interaction specs and do not conflict. `/sprd-experience` routes to the right one by the spec's `channel:`.

**Backend and frontend design are not separately delegated.** `architect` covers the design of the
system as a whole; splitting it by tier produced two agents arguing about the boundary between
them. Where a tier needs deep specialist attention, that is a spike (`/sprd-spike`), not a
permanent agent.

**Note:** `visual-designer`, `conversation-designer`, and `data-analyst` also double as `/sprd-review` council lenses (Design / Data viewpoints). They propose and draft; a named human decides.

**`/deep-plan` orchestration (steps 1–15):** When `/deep-plan` is invoked in this phase, it manages its own subagents internally (Explore for codebase research, web-search-researcher for web research, opus-plan-reviewer or external LLMs for review). These do not need to be spawned separately — `/deep-plan` handles the orchestration. The agents listed above (`architect`, domain agents, `security-reviewer`) operate alongside `/deep-plan` for SDLC-native work like ADR generation and security review.

---

## Phase 3: Foundation

| Role | Agent | Condition | Parallel Group | Background |
|------|-------|-----------|----------------|------------|
| Section plan generation | `deep-plan:section-writer` | 3+ sections to plan | plan-A | No |
| Implementation planning | `Plan` or `planner` | Complex feature decomposition | — | No |
| Codebase exploration | `Explore` | Need to understand existing code structure | — | No |

**Parallel group `plan-A`:** When multiple section plans have no dependency on each other, spawn one `deep-plan:section-writer` per independent section in a single message.

**`/deep-plan` orchestration (steps 16–22):** `/deep-plan` resumes from the Phase 2 checkpoint and manages `deep-plan:section-writer` subagents internally (batch size up to 7 concurrent). After generation, run `scripts/map_deep_plan_artifacts.py --phase 3` to transform `/deep-plan`'s `sections/section-NN-*.md` files into SDLC's `section-plans/SECTION-NNN.md` format (under `03-foundation/`) using the converged template. The `Plan` and `Explore` agents listed above are for supplementary work alongside `/deep-plan`.

---

## Build Loop (`build`)

The Build loop replaces the former batch Implementation/Quality/Testing phases (4/5/6). It is **continuous**: every change runs the same three beats — Intent (decide + write a spec), Delegate (bound + build from an approved plan), Discern (prove against the spec by someone other than the author, then merge). There is **no batch artifact exit gate** — checking happens per change, not as a later batch phase.

**Building is not delegated to a domain agent.** The Delegate beat is Claude building from an
approved plan, under the rails — the checking ladder is what makes that safe, not a specialist
persona. The agents below serve the Discern beat, where the value of a subagent is real: a
perspective that did not write the code.

| Role | Agent | Condition | Parallel Group | Background |
|------|-------|-----------|----------------|------------|
| Spec/section evaluation | `section-evaluator` | Discern beat — after each change | — | No (foreground, blocking) |
| Independent grading | `grader` | Discern beat — proves the change against its spec | — | No (foreground) |
| Security review (rolling) | `security-reviewer` | Change touches auth/payments/secrets/PII | — | No (foreground) |
| Adversarial + edge-case review | `multi-reviewer` | Suggested; use `--adversarial` and `--edge-cases` | — | No |
| Diff review | `deep-implement:code-reviewer` | Discern beat — review vs the spec/plan | — | Yes |
| Build error resolution | `build-error-resolver` | Build, compile, or test compilation fails | — | No (immediate) |
| Root cause investigation | `debugger` or `Explore` | A check fails unexpectedly | — | No |
| Gate repair | `gate-repair` | A gate fails and the cause is the harness, not the change | — | No |

**Skills, not agents, for the authoring work:** tests come from the `test-writer` skill, API
surfaces from `api-pattern`, specs from `spec-writer`, PR bodies from `pr-writer`, LLM golden sets
from `eval-builder`, and failure investigation from `diagnose`. A skill runs in the main context
with the surrounding work in view, which is what authoring needs; an agent starts cold, which is
what reviewing needs.

**Mandatory spawns:**
- `build-error-resolver` on ANY build failure — do not attempt manual fixes first.
- `security-reviewer` on ANY change that handles auth, payments, secrets, or PII. STOP all other work on CRITICAL/HIGH findings; fix before merging.
- `section-evaluator` in the Discern beat after EACH change — foreground, blocking. The change is not merged until the evaluator produces a PASS or CONDITIONAL PASS verdict. On FAIL, the build agent must address blocking issues and the evaluator re-runs.

**Remediation:** CRITICAL/HIGH findings are fixed inline, then `security-reviewer` re-runs to confirm. The fix belongs to whoever holds the context, not to a separate agent that would have to rebuild it.

**Session handoff:** At the end of each session (or when the context window is nearing limits), the orchestrator MUST update `session-handoff.json` in `.sdlc/artifacts/build/`. At session start, it MUST read this file before beginning work. See `phases/build-loop.md`.

---

## Phase 7: Documentation

| Role | Agent | Condition | Parallel Group | Background |
|------|-------|-----------|----------------|------------|
| ADR gap analysis | `Explore` | Always — search git history for undocumented decisions | — | No |

**The documentation itself is written directly**, not delegated. Phase 7's two domains — the README
for a stranger, `api-docs.md` for an integrator — are written from the implementation and diffed
against the Phase 2 contracts. See `phases/07-documentation.md` Steps 1–2.

**Sequential:** run the `Explore` ADR gap analysis after the documents are written — it reads their
output to avoid re-reporting decisions that are now recorded.

---

## Phase 8: Deployment

| Role | Agent | Condition | Parallel Group | Background |
|------|-------|-----------|----------------|------------|
| Build error resolution | `build-error-resolver` | Deployment build fails | — | No (immediate) |

**Deployment and smoke tests are executed directly**, following `RUNBOOK.md` — the runbook is the
authority, and a deploy that needs a step the runbook lacks has found a defect in the runbook. This
phase is mostly HITL with human approval gates; Step 0's go/no-go is the most consequential gate in
the lifecycle.

**Mandatory:** If the deployment build fails at any point, spawn `build-error-resolver` immediately. Do not attempt manual fixes.

---

## Phase 9: Monitoring

No agents are spawned during Monitoring.

The baseline is measured, `monitoring-config.md` is written from those measurements, the alert
drill is run by a **real human responder** — Claude cannot page anyone — and the retrospective is
written with the client. See `phases/09-monitoring.md`.

---

## Automatic Escalation Rules

These apply to ALL phases:

| Trigger | Agent | Behavior |
|---------|-------|----------|
| Build or compilation failure | `build-error-resolver` | Spawn immediately. Do not attempt manual fixes first. |
| Code touches auth, payments, secrets, or PII | `security-reviewer` | Foreground. STOP on CRITICAL/HIGH findings. |
| Gate check fails unexpectedly | `Explore` or `debugger` | Investigate root cause before attempting fixes. |
| A gate fails because the harness is wrong, not the change | `gate-repair` | Repair the harness; never weaken the gate to pass. |

---

## Background Agent Policy

Run with `run_in_background: true`:
- `deep-implement:code-reviewer` — diff review against the spec/section plan

Never background:
- Security reviews (always foreground, always blocking)
- Build error resolution (always foreground, always blocking)
- Spec/section evaluation (foreground and blocking — it decides whether the change merges)
- Any work producing artifacts required by the current phase gate
