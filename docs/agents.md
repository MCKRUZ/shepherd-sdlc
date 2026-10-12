# Agent Orchestration

Authoritative reference for how the Shepherd plugin spawns, coordinates, and manages agents across the SDLC lifecycle.

---

## Table of Contents

1. [Agent Architecture Overview](#1-agent-architecture-overview)
2. [Custom Agents](#2-custom-agents)
3. [Harness and Built-in Subagents Used by SDLC](#3-harness-and-built-in-subagents-used-by-sdlc)
4. [Phase-to-Agent Mapping](#4-phase-to-agent-mapping)
5. [Parallel Execution Rules](#5-parallel-execution-rules)
6. [Mandatory vs Optional Spawns](#6-mandatory-vs-optional-spawns)
7. [Background Agent Policy](#7-background-agent-policy)
8. [Automatic Escalation Rules](#8-automatic-escalation-rules)
9. [Cross-References](#9-cross-references)

---

## 1. Agent Architecture Overview

Agents in the Shepherd plugin are invoked through Claude Code's `Agent()` tool, not inline within the main conversation context. This is a deliberate architectural choice with several consequences:

- **Context isolation.** Each agent receives only the task-specific context it needs (state file, profile, phase artifacts) and returns a structured result. The main context window is protected from the full volume of agent reasoning and intermediate output.
- **Composability.** The sdlc-orchestrator agent can spawn other agents, creating multi-level orchestration without polluting the user-facing conversation.
- **Parallelism.** Independent agents can be spawned simultaneously in a single message via multiple `Agent()` tool calls, enabling concurrent work across domains.

There are three categories of agents:

| Category | Defined In | Count | Examples |
|----------|-----------|-------|---------|
| SDLC agents | `agents/*.md` | 14 | sdlc-orchestrator, compliance-checker, requirements-analyst, section-evaluator, gate-repair, multi-reviewer, narrative-enhancer, discovery-analyst, document-summarizer, feature-architect, bizreq-analyst, data-analyst, visual-designer, conversation-designer |
| Harness agents | `harness/agents/*.md`, installed into the target repo | 6 | architect, build-error-resolver, debugger, grader, planner, security-reviewer |
| Claude Code built-ins | Claude Code runtime | 2 used here | `Explore`, `Plan` |

SDLC agents carry SDLC-specific system prompts, tool permissions, and output format contracts and live in the plugin. Harness agents are installed into the client repo by `/sprd-harness`, so they are available to any session in that repo, not only to `/sprd` commands.

> **The runtime supplies almost nothing.** An earlier version of this table claimed thirteen-plus
> "built-in Claude Code subagents" including `backend-architect` and `code-reviewer`. Those do not
> exist. Believing they came free with the runtime is why phases 7–9 spent several releases
> spawning agents that were never built — and a spawn that resolves to nothing fails **silently**,
> so the phase reported the work as done. If an agent is not in one of the three rows above, it is
> not available; `scripts/tests/test_agent_references.py` now enforces that.

---

## 2. Custom Agents

### 2.1 sdlc-orchestrator

**File:** `agents/sdlc-orchestrator.md`
**Tools:** Read, Write, Edit, Bash, Grep, Glob

The orchestrator is the central coordination agent for the entire SDLC lifecycle. It is the only agent that both reads and writes `.sdlc/state.yaml`.

**Responsibilities:**

1. **Phase coordination** -- Reads the current phase from `state.yaml`, consults the phase definition in the phase's slug-named `phases/<slug>.md` (e.g. `build` -> `phases/build-loop.md`), and guides the user through the correct sequence of activities.
2. **Gate enforcement** -- Before any phase transition, runs `scripts/check_gates.py` and blocks advancement if MUST-level gates fail.
3. **Skill routing** -- Maps the current phase to the appropriate Claude Code skills:
   - Phase 0-1: `/plan`, `/deep-project`
   - Phase 2: `/deep-plan` (steps 1-15), preceded by `synthesize_spec.py`, followed by `map_deep_plan_artifacts.py --phase 2`, then ADR generation
   - Phase 3 (Foundation): finish `/deep-plan` (steps 16-22), writing `section-plans/` under `03-foundation/`, then stand up the harness + rails + dev infra and run a walking skeleton through the Build loop. After `/deep-plan` resumes from its checkpoint, run `map_deep_plan_artifacts.py --phase 3`.
   - Build Loop: per-change Intent->Delegate->Discern -- `/deep-implement`-style building with `/tdd`, `/code-review` + `/security-review` and `/e2e` run per change (not batched)
   - Phase 7: `/update-docs`
4. **State management** -- Updates `state.yaml` with gate results, phase transitions, timestamps, and session metadata.
5. **Profile awareness** -- Reads `.sdlc/profile.yaml` to determine the project's stack, quality thresholds, compliance requirements, and conventions. All downstream decisions respect profile configuration.

**When spawned:** Complex phase transitions, multi-step workflows, `/sprd-next` command execution, and any scenario requiring cross-phase state awareness.

**Key files accessed:**
- `.sdlc/state.yaml` (read/write)
- `.sdlc/profile.yaml` (read)
- `phases/phase-registry.yaml` (read)
- `scripts/check_gates.py` (execute)
- `scripts/synthesize_spec.py` (execute)
- `scripts/map_deep_plan_artifacts.py` (execute)

---

### 2.2 compliance-checker

**File:** `agents/compliance-checker.md`
**Tools:** Read, Grep, Glob, Bash

The compliance checker validates regulatory compliance gates at phase transitions. It is the enforcement mechanism for organizations that configure compliance frameworks in their profile.

**Supported frameworks:**

| Framework | Focus Areas |
|-----------|-------------|
| SOC 2 (Type II) | Access controls (CC6.1), system boundaries (CC6.6), change management (CC7.1), vulnerability management (CC7.2), code review (CC8.1), monitoring (CC7.2) |
| HIPAA | Access controls (164.312(a)), transmission security (164.312(e)), audit controls (164.312(b)), person authentication (164.312(d)), contingency plan (164.308(a)(7)) |
| GDPR | Data protection by design (Art. 25), lawful basis (Art. 6), right to erasure (Art. 17), data portability (Art. 20), security of processing (Art. 32), records of processing (Art. 30) |
| PCI-DSS | Network segmentation (Req 1), stored data protection (Req 3), secure coding (Req 6.5), code review (Req 6.6), testing controls (Req 11), change control (Req 6.4) |

**How it operates:**

1. Reads `.sdlc/profile.yaml` to determine which frameworks apply.
2. Loads compliance gate definitions from the profile's `compliance/` directory (e.g., `soc2-gates.yaml`).
3. Filters gates to only those relevant to the current phase transition.
4. Checks each gate using one of four verification methods:
   - `artifact_exists` -- Verifies the file or directory exists on disk.
   - `artifact_content` -- Verifies the artifact contains required keywords or sections.
   - `metric` -- Reports a metric requirement (may require external tool execution).
   - `manual` -- Flags for human review with specific instructions.
5. Reports each gate as PASS, FAIL, or MANUAL with severity level.
6. Provides specific remediation actions for every failure.

**Output format:** A structured compliance report listing every gate with its result, severity, and remediation guidance. Example:

```
Compliance Check: SOC 2 -- Phase 2 -> Phase 3
=====================================================
[PASS] [MUST] CC6.1: Access control requirements defined
[FAIL] [MUST] CC6.6: System boundaries not documented in design-doc.md
  -> Add a "Trust Boundaries" section to .sdlc/artifacts/02-design/design-doc.md
[MANUAL] [MUST] CC8.1: Peer review required -- verify review is documented
=====================================================
Result: BLOCKED -- 1 failure requires remediation
```

**Key principle:** Compliance gates at MUST severity are non-negotiable. The agent will never suggest workarounds that bypass compliance requirements. It helps the user satisfy the requirement properly.

**When spawned:** Phase transitions in projects with compliance profiles, explicit compliance audit requests via `/sprd-audit`.

---

### 2.3 requirements-analyst

**File:** `agents/requirements-analyst.md`
**Tools:** Read, Write, Edit, Grep, Glob

The requirements analyst specializes in eliciting, structuring, and validating software requirements. It is the primary agent for Phases 0 and 1 and is heavily human-in-the-loop (HITL).

**Responsibilities:**

1. **Discovery interview (Phase 0):**
   - Asks probing questions about the problem space.
   - Identifies stakeholders and their concerns.
   - Helps craft a structured problem statement.
   - Documents assumptions and constraints.
   - Reads existing artifacts from `.sdlc/artifacts/00-discovery/`.

2. **Requirements decomposition (Phase 1):**
   - Breaks the approved problem statement into functional requirements.
   - Identifies non-functional requirements (performance, security, scalability).
   - Assigns priority labels (P0-P3) based on stakeholder input.
   - Writes measurable acceptance criteria in Given/When/Then format.

3. **Requirements validation:**
   - Checks for conflicting requirements.
   - Ensures completeness against the problem statement scope.
   - Verifies all P0/P1 requirements have acceptance criteria.
   - Flags gaps or ambiguities.
   - Checks compliance requirements: SOC 2 (auth/authz defined?), HIPAA (PHI access controls?), GDPR (privacy requirements specified?).

**Output format:** Structured requirements documents using templates from the plugin. Each requirement follows the pattern `REQ-XXX: [Description] [Priority: PX]`. Each acceptance criterion uses Given/When/Then format. Compliance gaps are flagged explicitly.

**Key principle:** "Ask, don't assume." When uncertain about a requirement's scope or priority, the analyst asks the user rather than making assumptions. Clarifying now prevents building the wrong thing.

**When spawned:** Phase 0 (discovery interviews), Phase 1 (requirements gathering and decomposition).

---

### 2.4 section-evaluator

**File:** `agents/section-evaluator.md`
**Tools:** Read, Grep, Glob, Bash

The section evaluator is the "discriminator" in a generator-evaluator loop. It assesses whether a completed section implementation satisfies its plan's verification criteria and quality standards. Its job is to be rigorous, not lenient.

**Responsibilities:**

1. **Verify exit criteria** -- Checks every exit criterion from the section plan. Each must have evidence of satisfaction (passing test, file exists, behavior confirmed).
2. **Grade against rubric** -- Applies the Evaluator Contract's grading rubric point by point.
3. **Check interface compliance** -- Verifies exposed interfaces match the Interfaces table in the section plan.
4. **Validate test quality** -- Confirms coverage targets are met and TDD test stubs from the plan are implemented.
5. **Flag deviations** -- Any deviation from Implementation Guidance must be documented in `implementation-notes.md`.

**How it operates:**

1. Reads the section plan from `.sdlc/artifacts/03-foundation/section-plans/SECTION-NNN.md` and extracts: Exit Criteria, Verification Criteria (methodology table), Evaluator Contract (grading rubric, fail conditions, warn conditions), Interfaces table, Test Strategy, and TDD Test Stubs.
2. Reads the implementation: identifies created/modified files, reads `implementation-notes.md` for decisions and deviations, checks test files for coverage of TDD stubs.
3. Reads profile evaluation criteria from `.sdlc/profile.yaml` under `quality.evaluation_criteria` and applies any additional company-specific quality standards. If a criterion's `severity` field is missing, it defaults to `warn` (non-blocking).
4. Evaluates each criterion against its specified Verification Method and Pass Condition, recording PASS / FAIL / WARN with evidence.
5. Applies the five-category grading rubric: functional completeness, test quality, interface compliance, code quality, and deviation accountability.
6. Produces a structured evaluation report with a final verdict: PASS, FAIL, or CONDITIONAL PASS.

**Verdicts:**
- **PASS** -- All exit criteria met, all rubric categories pass, no blocking issues.
- **CONDITIONAL PASS** -- Exit criteria met with warnings. The section is complete but improvements are recommended.
- **FAIL** -- One or more fail conditions triggered. The implementation agent must address blocking issues and the evaluator re-runs.

**Key principles:**
- Be specific. "Tests look good" is not an evaluation. "12/14 TDD stubs implemented, missing edge case for null input on UserService.Create" is.
- Fail conditions from the Evaluator Contract are non-negotiable. If triggered, the verdict MUST be FAIL regardless of other results.
- Warn conditions are signal for improvement but do not block section completion.
- Deviations are acceptable when documented. The evaluator penalizes only undocumented deviations.
- Quality thresholds (coverage, file size, function size) come from `.sdlc/profile.yaml`, not from assumptions.

**When spawned:** in the Build Loop, after each spec/section completes. Foreground, blocking -- the section is not marked complete until the evaluator produces a PASS or CONDITIONAL PASS.

---

### 2.5 gate-repair

Fixes simple, structural gate failures automatically before escalating to the human. Spawned by the orchestrator after `/sprd-gate` or `/sprd-next` finds failures.

**Repairable (will fix):** missing artifacts that have a template (copies and fills obvious fields), missing required H2 sections (adds header with a structured TODO), missing frontmatter fields (infers from state/profile), unambiguous `${VARIABLE}` placeholders, empty required files (scaffolds from template).

**Not repairable (escalates):** missing substantive content (requirements, design decisions, acceptance criteria), code quality issues, security findings, compliance gaps, anything requiring domain knowledge, ambiguous placeholders.

**Principles:** minimal fixes only (structure, never content), transparent (reports every change for human review), conservative (when in doubt, escalate), idempotent. See `references/smart-repair.md` for the full repair classification.

**When spawned:** any phase, after a gate check fails on structural issues. Foreground; the human reviews the repair report before re-running gates.

---

### 2.6 multi-reviewer

Reviews phase artifacts from multiple perspectives. Spawned by `/sprd-review` with one of three modes:

| Mode | Stance | Focus |
|------|--------|-------|
| `--council` (default) | Four viewpoints: Architecture, Product, Quality, Security — 2-3 findings each, plus a consistency and ambiguity audit (cross-artifact contradictions, unresolved references, locked-metric drift) | Balanced coverage before a gate |
| `--adversarial` | Cynical QA: challenge every assumption, decision, estimate, and justification | Weak reasoning, untested assumptions, scope creep |
| `--edge-cases` | Walk every branch, boundary, and state transition | Missing paths, boundary conditions, race conditions, data edge cases |

Writes `review-report.md` into the phase's artifact directory with findings rated CRITICAL/HIGH/MEDIUM/LOW, each with a specific artifact reference and an actionable recommendation. Findings are advisory — they do not block gates, but CRITICAL/HIGH findings usually predict gate failures.

**When spawned:** `/sprd-review`, recommended before gates on phases 2 and 3, and per-change in the Build Loop.

---

### 2.7 narrative-enhancer

Transforms technical artifacts into prose-rich `.narrative.md` companions for non-technical stakeholders (PMs, executives, business analysts). Spawned in parallel by `/sprd-enhance` — one agent per artifact.

Output structure (per `references/narrative-patterns.md`): executive summary, 500-1000 word detailed narrative (tables become contextualized prose, metrics get interpreted, technical terms get business language), key decisions in business terms, impact assessment.

**Principles:** the technical artifact remains the source of truth; no information invention — every claim traces to the source; simplify vocabulary, never meaning. Narratives are optional for gates but recommended before stakeholder reviews.

**When spawned:** `/sprd-enhance`, typically before phase transitions and steering reviews.

---

### 2.8 discovery-analyst

Cross-document analysis for discovery: finds where the intake corpus disagrees with itself and what no document answers. Spawned in Phase 0 Step 0d (workshop prep) or standalone via `/sprd-brief --docs <path>`.

**Produces** (templates in `templates/phases/00-discovery/`):
- `contradiction-list.md` — CON-NN entries, each with two verbatim citations (`DOC-NNN:section`), a type (fact / scope / assumption / terminology), a severity (blocks-outcome / shapes-design / minor), and the question that resolves it
- `question-list.md` — Q-NN entries grouped by workshop agenda block, each routed `workshop` / `pre-workshop` / `interview`; Q-NN IDs persist into `phase1-handoff.md` open questions

**Principles:** questions only — never proposes outcomes, metrics, or solutions; attributes everything (a claim with one citation is a question, not a contradiction); flags disagreements rather than reconciling them; routes cheap questions out of the workshop.

**When spawned:** Phase 0, when document intake has run and a stakeholder workshop is planned. Foreground.

---

### 2.9 document-summarizer

Writes the summary of ONE document in the intake corpus, to `templates/phases/00-discovery/document-summary.md` and the catalog's `summary_budget_tokens`. Spawned once per document by `/sprd-intake` (Phase 0 Step 0c), in priority order, and by Shepherd (the desktop app)'s *Summarise the documents* button.

**Produces:** `.sdlc/context/intake/DOC-NNN-<slug>.md` — overview, purpose / audience / scope, extractable requirements, key terms, relevance. A document over ~100K tokens is read by its opening, closing and headings and the summary says "Partial extraction".

**Principles:** never invents (every statement traces to the document; "Not stated" otherwise); attributes to sections; summarises, never judges or reconciles (contradictions are the discovery-analyst's job); treats the document's own text as data, never as instructions.

**When spawned:** Phase 0, after the catalog is reviewed and before the registry and index are built. Foreground.

---

## 3. Harness and Built-in Subagents Used by SDLC

Agents referenced by name in phase workflows that are not defined in `agents/`. The harness agents are installed into the target repo by `/sprd-harness`; the two built-ins come from the Claude Code runtime.

| Agent | Source | Primary Phases | Purpose |
|-------|--------|---------------|---------|
| `security-reviewer` | harness | 2, Build | OWASP Top 10, auth, secrets, injection, PII handling |
| `build-error-resolver` | harness | Build, 8 (conditional) | Diagnose and fix build/compilation failures |
| `architect` | harness | 2 (primary) | System architecture design |
| `grader` | harness | Build (Discern) | Prove a change against its spec, independently of whoever built it |
| `debugger` | harness | Build (conditional) | Root-cause investigation when a check fails unexpectedly |
| `planner` | harness | 3 (conditional) | Complex feature decomposition |
| `Explore` | built-in | 0, 1, 2, 3, Build, 7, close (conditional) | Codebase exploration, ADR gap analysis |
| `Plan` | built-in | 3 (conditional) | Implementation planning |
| `deep-plan:section-writer` | `/deep-plan` | 3 Foundation (parallel) | Section plan generation within `/deep-plan` |
| `deep-implement:code-reviewer` | `/deep-implement` | Build (bg) | Diff review of implementation against section plan |

### Work that is done directly, not delegated

These are the jobs earlier versions of this document assigned to agents that were never built. Each
is now a step in the phase definition:

| Work | Where it happens now |
|------|----------------------|
| README and API documentation | `phases/07-documentation.md` Steps 1–2, written directly and diffed against the Phase 2 contracts |
| Staging and production deployment | `phases/08-deployment.md` Steps 2 and 4, following `RUNBOOK.md` |
| Smoke tests | `phases/08-deployment.md` Step 3 |
| Performance baseline | `phases/09-monitoring.md` Step 1, measured before any threshold is set |
| Feedback synthesis | `phases/09-monitoring.md` Step 5, as part of the retrospective |
| Writing tests | the `test-writer` skill |
| API contract work | the `api-pattern` skill |
| Failure investigation | the `diagnose` skill, or the `debugger` agent |
| Spikes and prototypes | `/sprd-spike` |

A skill runs in the main context with the surrounding work in view, which is what authoring needs.
An agent starts cold, which is what reviewing needs. That distinction — not a persona name — is
what decides whether something should be delegated.

---

## 4. Phase-to-Agent Mapping

Every agent named below exists. Where a phase does most of its work directly, that is stated
rather than filled out with agents that would have to be invented.

### Phase 0: Discovery

| Agent | Mode | Condition |
|-------|------|-----------|
| `Explore` | Foreground | Existing codebase to analyze |
| `document-summarizer` | Foreground, once per document | Document intake is configured and the catalog is reviewed |
| `discovery-analyst` | Foreground | Document intake ran AND a stakeholder workshop is planned |

Phase 0 is primarily human-driven. `discovery-analyst` produces questions for humans, never answers.

### Phase 1: Requirements

| Agent | Mode | Condition |
|-------|------|-----------|
| `Explore` | Foreground | Existing codebase to understand |
| `requirements-analyst` | Foreground | Decomposing the problem into FR/NFR with acceptance criteria |
| `feature-architect` | Foreground | Featuring a channel-bound feature (via `/sprd-feature`) |
| `bizreq-analyst` | Foreground | Business rules or golden scenarios to capture (via `/sprd-rules`) |

### Phase 2: Design

| Agent | Mode | Condition | Parallel Group |
|-------|------|-----------|----------------|
| `architect` | Foreground | Always | -- |
| `security-reviewer` | Foreground | Auth, payments, or sensitive data in scope | -- |
| `compliance-checker` | Foreground | The domain carries regulatory obligations | -- |
| `data-analyst` | Foreground | Feature touches data or PII (via `/sprd-data`) | -- |
| `visual-designer` | Foreground | A web/`ag-ui` surface is in scope | design-B |
| `conversation-designer` | Foreground | A voice/chat surface is in scope | design-B |
| `multi-reviewer` | Foreground | Suggested before `/sprd-gate`; `--council` mode | -- |
| `Explore` | Foreground | Existing codebase being extended | -- |

**Parallel group `design-B`:** When a feature spans a web surface and a voice/chat surface, spawn `visual-designer` and `conversation-designer` in a single message. They author different interaction specs and do not conflict.

Design is not split by tier. `architect` covers the system as a whole; a tier needing deep specialist attention is a spike (`/sprd-spike`), not a permanent agent.

### Phase 3: Foundation

| Agent | Mode | Condition | Parallel Group |
|-------|------|-----------|----------------|
| `deep-plan:section-writer` | Foreground | 3+ sections to plan | plan-A |
| `Plan` or `planner` | Foreground | Complex feature decomposition | -- |
| `Explore` | Foreground | Need to understand existing code structure | -- |

Foundation completes the section-planning that began in `/deep-plan` AND stands up the factory: install/adapt the harness, bring up CI/CD rails + gates + dev infra, and run a walking skeleton end-to-end through the Build loop. The agents above cover the section-planning work; the rails, harness and dev-infra setup is HITL plus scripted automation (`/sprd-harness`, `scripts/rails/*`, `/sprd-doctor`), not an agent.

### Build Loop

Building is not delegated to a domain agent. The Delegate beat is Claude building from an approved
plan under the rails, and the checking ladder is what makes that safe -- not a specialist persona.
The agents below serve the Discern beat, where a subagent buys something real: a perspective that
did not write the code.

| Agent | Mode | Condition |
|-------|------|-----------|
| `section-evaluator` | Foreground (blocking) | Discern beat -- after each change |
| `grader` | Foreground | Discern beat -- proves the change against its spec |
| `security-reviewer` | Foreground | Change touches auth/payments/secrets/PII |
| `multi-reviewer` | Foreground | Suggested; `--adversarial` and `--edge-cases` |
| `deep-implement:code-reviewer` | Background | Diff review against the spec/section plan |
| `build-error-resolver` | Foreground (immediate) | Build, compile, or test compilation fails |
| `debugger` or `Explore` | Foreground | A check fails unexpectedly |
| `gate-repair` | Foreground | A gate fails because the harness is wrong, not the change |

**Authoring work uses skills, not agents:** tests come from `test-writer`, API surfaces from `api-pattern`, specs from `spec-writer`, PR bodies from `pr-writer`, LLM golden sets from `eval-builder`, failure investigation from `diagnose`.

**Mandatory:**
- `build-error-resolver` on ANY build failure -- do not attempt manual fixes first.
- `security-reviewer` on ANY change touching auth, payments, secrets, or PII.
- `section-evaluator` after EACH change -- foreground and blocking; the change does not merge until it returns PASS or CONDITIONAL PASS.

### Phase 7: Documentation

| Agent | Mode | Condition |
|-------|------|-----------|
| `Explore` | Foreground | Always -- search git history for undocumented decisions |

The documentation itself is written directly. Phase 7 has two audiences -- the README for a stranger, `api-docs.md` for an integrator -- written from the implementation and diffed against the Phase 2 contracts. Run the `Explore` ADR gap analysis afterwards, so it reads the finished documents.

### Phase 8: Deployment

| Agent | Mode | Condition |
|-------|------|-----------|
| `build-error-resolver` | Foreground (immediate) | Deployment build fails |

Deployment and smoke tests are executed directly, following `RUNBOOK.md`. This phase is mostly HITL with human approval gates; Step 0's go/no-go is the most consequential gate in the lifecycle.

### Phase 9: Monitoring

No agents are spawned during Monitoring. The baseline is measured, `monitoring-config.md` is written from those measurements, the alert drill is run by a real human responder -- Claude cannot page anyone -- and the retrospective is written with the client.

### Phase C: Close & Transfer

No agents are spawned during Close. The phase exists to prove the client can run the system without the pod; delegating it would defeat the point.

---

## 5. Parallel Execution Rules

1. **Same-message spawning.** Agents in the same parallel group MUST be launched in one message with multiple `Agent()` calls. Sequential spawning wastes wall-clock time for no benefit.
2. **Independence is the precondition.** Only group agents whose work cannot conflict -- different files, different documents, different test domains.
3. **Background for non-blocking work only.** If the current phase gate needs the output, it runs foreground.
4. **Sequential agents have explicit ordering.** When one agent's output feeds the next, the first must complete before the second starts. This is stated in the phase mapping tables.

---

## 6. Mandatory vs Optional Spawns

### Mandatory (no user prompt needed)

| Trigger | Agent | Notes |
|---------|-------|-------|
| Build or compilation failure | `build-error-resolver` | Immediately. Do not attempt manual fixes first. |
| Change touches auth, payments, secrets, or PII | `security-reviewer` | Foreground. STOP on CRITICAL/HIGH findings. |
| Build Loop (Discern beat) | `section-evaluator` | Foreground and blocking, after every change. |

### Optional (suggest to user)

| Situation | Agent | Notes |
|-----------|-------|-------|
| Design-heavy phase before the gate | `multi-reviewer` | `--council`, `--adversarial`, or `--edge-cases`. |
| A gate fails and the harness looks wrong | `gate-repair` | Repair the harness; never weaken the gate to pass. |
| A check fails for reasons nobody can explain | `debugger` | Root cause before remediation. |

---

## 7. Background Agent Policy

Run with `run_in_background: true`:
- `deep-implement:code-reviewer` -- diff review against the spec/section plan

Never background:
- Security reviews (always foreground, always blocking)
- Build error resolution (always foreground, always blocking)
- Spec/section evaluation (it decides whether the change merges)
- Any work producing artifacts required by the current phase gate

---

## 8. Automatic Escalation Rules

| Trigger | Agent | Behavior |
|---------|-------|----------|
| Build or compilation failure | `build-error-resolver` | Spawn immediately. Do not attempt manual fixes first. |
| Code touches auth, payments, secrets, or PII | `security-reviewer` | Foreground. STOP on CRITICAL/HIGH findings. |
| Gate check fails unexpectedly | `Explore` or `debugger` | Investigate root cause before attempting fixes. |
| A gate fails because the harness is wrong | `gate-repair` | Repair the harness, never the threshold. |
| CRITICAL/HIGH security finding | -- | Fix inline, then re-run `security-reviewer` to confirm. The fix belongs to whoever holds the context. |

---

## 9. Cross-References

- **Phase lifecycle and gate definitions:** See [phase-lifecycle.md](phase-lifecycle.md) for complete phase entry/exit criteria and gate mechanics.
- **Profile configuration and evaluation criteria:** See [profiles.md](profiles.md) for how `quality.evaluation_criteria` in profile YAML drives section-evaluator behavior.
- **Scripts and automation:** See [scripts.md](scripts.md) for `check_gates.py`, `synthesize_spec.py`, `map_deep_plan_artifacts.py`, and other automation used by agents.
- **Agent definition files:** `agents/sdlc-orchestrator.md`, `agents/compliance-checker.md`, `agents/requirements-analyst.md`, `agents/section-evaluator.md`.
- **Authoritative phase-to-agent mapping:** `references/agent-roster.md` is the source of truth. This document synthesizes and explains that mapping.
