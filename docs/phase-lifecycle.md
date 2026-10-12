# SDLC Phase Lifecycle Reference

Comprehensive reference for all 9 phases of the Shepherd plugin lifecycle. This document covers phase definitions, entry/exit gates, workflow steps, artifacts, agent orchestration, HITL gates, handoff protocols, project type adaptations, and visual report generation.

---

## Table of Contents

1. [Overview](#overview)
2. [Phase Model](#phase-model)
3. [Phase Registry](#phase-registry)
4. [Entry and Exit Gate Concepts](#entry-and-exit-gate-concepts)
5. [Phase 0: Discovery](#phase-0-discovery)
6. [Phase 1: Requirements](#phase-1-requirements)
7. [Phase 2: Design](#phase-2-design)
8. [Phase 3: Foundation](#phase-3-foundation)
9. [Build Loop](#build-loop)
10. [Phase 7: Documentation](#phase-7-documentation)
11. [Phase 8: Deployment](#phase-8-deployment)
12. [Phase 9: Monitoring](#phase-9-monitoring)
13. [Phase C: Close & Transfer](#phase-c-close--transfer)
14. [Phase Transition Protocol](#phase-transition-protocol)
15. [Visual Phase Report Protocol](#visual-phase-report-protocol)
16. [Handoff Chain](#handoff-chain)

---

## Overview

The Shepherd plugin orchestrates a full Software Development Lifecycle across 9 phases, ordered but non-sequential (ids `0, 1, 2, 3, build, 7, 8, 9, close`). Each phase has a clearly defined purpose, required artifacts, entry/exit gates, and a handoff document that feeds the next phase.

The lifecycle enforces discipline through:

- **Ordered progression by registry `order`, not by id** -- phases advance in the registry's `order` sequence, never by `id + 1`. Two phases (`build` and `close`) carry non-numeric ids, so id arithmetic does not apply. The visible gap where phases 4, 5, and 6 once sat (Implementation / Quality / Testing) is intentional: batched checking -- write everything, then review everything, then test everything -- is the rejected anti-pattern. Checking happens per-change inside the Build loop instead, never as a later batch phase. Re-entry to a completed phase is allowed if issues are discovered downstream.
- **Gate-based transitions** -- every phase has entry gates (prerequisites) and exit gates (deliverable validation). MUST-level gates block advancement; SHOULD-level gates produce warnings; MAY-level gates are informational.
- **Human-in-the-loop (HITL) gates** -- mandatory stopping points where Claude must pause and interact with the human before proceeding. These are marked with `> HITL GATE:` blockquotes in phase definitions.
- **Handoff documents** -- each phase produces a handoff that the next phase reads as its starting context. Open questions (Q-NN / AQ-NN) in handoffs must be resolved before any new-phase work begins.

---

## Phase Model

```
Phase 0: Discovery
    |
    v
Phase 1: Requirements
    |
    v
Phase 2: Design
    |
    v
Phase 3: Foundation
    |
    v
Build Loop (continuous)
    |
    v
Phase 7: Documentation
    |
    v
Phase 8: Deployment
    |
    v
Phase 9: Monitoring
    |
    v
Phase C: Close & Transfer
    |
    v
  [Complete]
```

Phases advance in the registry's `order` sequence, **not** by numeric id. The next phase is always the registry entry with `order + 1` -- never `id + 1`, because `build` and `close` are non-numeric ids. The gap where phases 4, 5, and 6 used to be (Implementation / Quality / Testing) is intentional and permanent: batched checking is the failure mode the standard exists to kill, so checking now happens per-change inside the Build loop. A completed phase MAY be re-entered if issues are discovered downstream; this creates a new history entry with `reentry: true`.

---

## Phase Registry

The file `phases/phase-registry.yaml` is the single source of truth for the phase model, consumed by `scripts/phase_model.py`. It defines every phase with:

- **id** -- phase identifier; an int for `0, 1, 2, 3, 7, 8, 9` or a string for `build` / `close`. Scripts MUST NOT assume ids are integers, contiguous, or that next = current + 1.
- **slug** -- the artifact directory name under `.sdlc/artifacts/<slug>/`. Never derived by zero-padding an int (e.g. `00-discovery`, `03-foundation`, `build`, `close`).
- **order** -- sequence position (0..N). "Next phase" = the registry entry with `order + 1`.
- **terminal** -- `true` on the final phase (`close`); there is no next phase after it.
- **name** -- machine-readable phase name
- **display** -- human-readable label
- **description** -- one-sentence summary of the phase purpose
- **definition** -- path to the full phase markdown file
- **skills.primary** -- slash commands primarily used during the phase
- **skills.secondary** -- optional supplementary skills
- **entry_gate.conditions** -- list of preconditions that must be true before entering
- **exit_gate.conditions** -- list of artifact checks and runtime checks required to leave
- **exit_gate.approval** -- `manual` on **every** phase. There is no `automatic` approval anymore; advancement always requires human sign-off.
- **artifacts.required** -- list of artifacts that MUST be produced
- **artifacts.optional** -- nice-to-have outputs

The `check_gates.py` script reads this registry and validates exit conditions against the actual `.sdlc/` directory contents.

---

## Entry and Exit Gate Concepts

**Entry gates** verify that the prerequisites for starting a phase are met. Typically this means:
- The previous phase's exit gate passed.
- The handoff document from the previous phase has been reviewed.
- Open questions from the handoff have been resolved.

**Exit gates** validate that the phase produced all required deliverables. Each exit condition is one of:
- **Artifact check** (`exists_and_complete`) -- the file exists in `.sdlc/artifacts/<slug>/` and is not empty or a stub.
- **Runtime check** -- a condition that must be verified programmatically (e.g., "Walking skeleton deployed through the real pipeline and verified", "Close gate passed").

**Gate severity levels:**
- **MUST** -- blocks phase advancement. The phase cannot advance until this gate passes.
- **SHOULD** -- produces a warning but does not block advancement. The warning is surfaced to the human.
- **MAY** -- informational only. Logged but does not affect advancement.

**Approval:** Advancement is **always manual**. Every phase carries `approval: manual` -- even if all checks pass, the human must explicitly confirm advancement. The `/sprd-next` command presents a summary and asks for human confirmation before advancing. There is no auto-advancing phase; the old `approval: automatic` mode has been removed entirely.

---

## Phase 0: Discovery

### Purpose

Understand the problem space, quantify impact, map stakeholders, and define scope before writing any requirements. Discovery prevents the common failure mode of jumping into solutions without understanding the problem. It produces a project constitution that anchors all future decisions.

### Entry Gate

| Condition | Type |
|-----------|------|
| Project initiated via `/sprd-setup` | MUST |

### Workflow Steps

| Step | Name | Description |
|------|------|-------------|
| 0 | HITL Gate -- Frame the Problem | Conduct a scoping conversation with the human. Ask: (1) What is the problem in one sentence? (2) Who is most affected? (3) What does success look like? (4) What constraints are non-negotiable? (5) What type of system is this (service/app/library/skill/cli)? Record `project_type` in `state.yaml`. |
| 1 | Problem Identification | Analyze and document the core problem, its root causes, and quantified impact. |
| 2 | Current State Analysis | Map the existing landscape -- what exists today, what has been tried, what failed. |
| 3 | Define Success | Establish measurable success criteria with baselines, targets, stretch targets, and measurement methods. |
| 4 | Scope Boundaries | Draw explicit lines around what is in scope and what is out of scope. Document non-negotiable constraints. |
| 5 | Write Project Constitution | Produce the constitution -- the single document that anchors all future decisions. |
| 6 | Phase Handoff | Package findings into `phase1-handoff.md` with summary, decisions, open questions, risks, and recommended starting point. |
| 7 | Generate Visual Report | Generate self-contained HTML report at `.sdlc/reports/00-discovery-visual.html`. |
| 8 | Generate Phase Report | Run `generate_phase_report.py` to produce `.sdlc/reports/00-discovery-report.html`. |

### HITL Gates

**Step 0 -- Frame the Problem with the Human:** Before writing any artifact, Claude must conduct a brief scoping conversation. The human provides the problem framing, affected users, success definition, non-negotiable constraints, and project type. Claude does not invent the problem framing.

### Required Artifacts

| Artifact | Description |
|----------|-------------|
| `constitution.md` | Project constitution anchoring all decisions. Contains the one-sentence problem, affected stakeholders, success definition, scope boundaries, and guiding principles. |
| `problem-statement.md` | Detailed problem analysis with root causes, quantified impact, and current state assessment. |
| `success-criteria.md` | Measurable success dimensions grouped by theme. Each criterion has baseline, target, stretch target, measurement method, timeline, and acceptance thresholds. |
| `constraints.md` | Technical, business, regulatory, and resource constraints. Each constraint has a rationale and impact assessment. |
| `phase1-handoff.md` | Handoff document containing discovery summary (5-10 bullets), decisions made with rationale, recommended scope, open questions (Q-NN format), risks to monitor, and suggested starting point for Phase 1. |

### Optional Artifacts

- `stakeholder-notes.md` -- raw notes from stakeholder conversations
- `market-research.md` -- competitive analysis or market context
- `document-registry.md` -- document intake index (opt-in via profile documentation)
- `00-discovery-report.html` -- self-contained HTML phase report

### Primary Skills

- `/plan` -- used to structure the discovery exploration

### Agents

No custom agents are spawned during Discovery. The orchestrator manages the workflow directly.

### Exit Gate

| Condition | Check | Type |
|-----------|-------|------|
| `constitution.md` | exists_and_complete | MUST |
| `problem-statement.md` | exists_and_complete | MUST |
| `success-criteria.md` | exists_and_complete | MUST |
| `constraints.md` | exists_and_complete | MUST |
| `phase1-handoff.md` | exists_and_complete | MUST |

**Approval:** manual -- requires human sign-off before advancing.

### Handoff Document

`phase1-handoff.md` contains:
- **Discovery Summary** -- what was learned, in 5-10 bullets
- **Decisions Made** -- what was decided during discovery and the rationale
- **Recommended Scope** -- what Phase 1 should include based on discovery findings
- **Open Questions** -- specific questions Phase 1 must answer before design can start (Q-NN format)
- **Risks to Monitor** -- risks surfaced during discovery with probability/impact rating
- **Suggested Starting Point** -- where Phase 1 should begin and what to tackle first

### Project Type Adaptations

Phase 0 is where `project_type` is established (service/app/library/skill/cli). The project type is recorded in `state.yaml` and determines adaptations in later phases. Phase 0 itself does not vary by project type.

---

## Phase 1: Requirements

### Purpose

Decompose the problem into functional and non-functional requirements with user stories and acceptance criteria. Requirements translate the "what" from Discovery into structured, traceable specifications that Design can act on.

### Entry Gate

| Condition | Type |
|-----------|------|
| Phase 0 exit gate passed | MUST |
| `phase1-handoff.md` reviewed | MUST |
| Open questions from Phase 0 answered or formally escalated | MUST |

### Workflow Steps

| Step | Name | Description |
|------|------|-------------|
| 0 | HITL Gate -- Confirm Scope | Read `phase1-handoff.md`. Confirm with the human: Are open questions (Q-NN) answered? Is prioritization (P0/P1/P2) clear? Are there missing requirements? |
| 1 | Functional Requirements | Document functional requirements with user stories, acceptance criteria, and priority levels. |
| 2 | Non-Functional Requirements | Define NFRs across performance, security, scalability, availability, observability, and maintainability dimensions. |
| 3 | Epics | Group requirements into epics with clear boundaries and dependencies. |
| 3a | Feature Decomposition (conditional) | `/sprd-feature` -- when an epic spans surfaces or personas: the `feature-architect` drafts `feature-brief.md` (features and specs with channel + persona per row, one channel per spec); a named human confirms rows and tiers. |
| 3b | Business Rules and Golden Scenarios (conditional) | `/sprd-rules` -- when the feature encodes policy: the `bizreq-analyst` drafts `business-rules.md` (BR-NN: condition, outcome, source, approver) and `golden-scenarios.md` (SCEN-NN); each approver signs their rules; undecided outcomes become DL-NN items. |
| 4 | Stakeholder Review | Present requirements to the human for validation and gap analysis. |
| 5 | Phase Handoff | Package into `phase2-handoff.md`. |
| 6 | Generate Visual Report | Generate `.sdlc/reports/01-requirements-visual.html`. |
| 7 | Generate Phase Report | Run `generate_phase_report.py`. |

### HITL Gates

**Step 0 -- Confirm Scope Before Writing Requirements:** Claude reads the Phase 0 handoff and confirms with the human that all open questions are answered, prioritization is clear, and no expected requirements were missed. Work does not begin until human confirms scope.

### Required Artifacts

| Artifact | Description |
|----------|-------------|
| `requirements.md` | Functional requirements with user stories, acceptance criteria, and P0/P1/P2 priority. |
| `non-functional-requirements.md` | NFR specifications across all quality dimensions: performance targets, security requirements, scalability limits, availability SLAs, observability needs, maintainability standards. |
| `epics.md` | Requirements grouped into epics with boundaries, dependencies, and estimated effort. |
| `phase2-handoff.md` | Requirements summary (counts by priority, key themes), architectural implications from NFRs, key decisions and rationale, open questions for Phase 2, risks, and recommended design starting point. |

### Optional Artifacts

- `glossary.md` -- domain terminology definitions
- `01-requirements-report.html` -- self-contained HTML phase report
- `feature-brief.md` -- (conditional) epic decomposed into channel-aware features and specs, from `/sprd-feature`
- `business-rules.md` -- (conditional) the BR-NN decision table with a named approver per rule, from `/sprd-rules`
- `golden-scenarios.md` -- (conditional) SCEN-NN input → expected behaviour; seeds acceptance checks and the golden set, from `/sprd-rules`

### Primary Skills

- `/deep-project` -- primary skill for deep requirements analysis
- `/plan` -- secondary skill for structuring the requirements work

### Agents

Requirements are authored directly by Claude with human review at Step 4. Two discipline agents are spawned only when their trigger applies: `feature-architect` (Product, via `/sprd-feature`) and `bizreq-analyst` (Business requirements, via `/sprd-rules`). Both propose; a named human decides, and the sign-offs are recorded at the advance.

### Exit Gate

| Condition | Check | Type |
|-----------|-------|------|
| `requirements.md` | exists_and_complete | MUST |
| `non-functional-requirements.md` | exists_and_complete | MUST |
| `epics.md` | exists_and_complete | MUST |
| `phase2-handoff.md` | exists_and_complete | MUST |

**Approval:** manual

### Handoff Document

`phase2-handoff.md` contains:
- **Requirements summary** -- counts by priority, key themes
- **Architectural implications from NFRs** -- what design options this opens/closes
- **Key decisions made and rationale**
- **Open questions Phase 2 must resolve** (AQ-NN format -- Architectural Questions)
- **Risks and ambiguities to watch**
- **Recommended design starting point**

### Project Type Adaptations

Phase 1 does not vary by project type. All project types produce the same requirements artifacts.

---

## Phase 2: Design

### Purpose

Create software architecture, API contracts, data models, and Architecture Decision Records (ADRs). Design translates requirements into a technical blueprint that Foundation can build the factory around and the Build loop can implement against. This phase integrates with the `/deep-plan` skill for thorough architectural analysis, and defines the walking-skeleton slice (the thinnest end-to-end path that proves the architecture) that Foundation will deploy.

### Entry Gate

| Condition | Type |
|-----------|------|
| Phase 1 exit gate passed | MUST |
| `phase2-handoff.md` reviewed | MUST |

### Workflow Steps

| Step | Name | Description |
|------|------|-------------|
| 0 | HITL Gate -- Resolve Architectural Questions | Extract every AQ-NN from the handoff. Present 2-3 concrete options with trade-offs for each. Collect human decisions for ALL AQs before writing any artifact. These become ADRs. |
| 1 | Spec Synthesis | Synthesize requirements, NFRs, and human decisions into a coherent technical specification. |
| 2 | Launch /deep-plan | Run the /deep-plan skill: research, architecture analysis, component design, interface definitions, and risk assessment. |
| 3 | Map /deep-plan Outputs to SDLC Artifacts | Transform /deep-plan outputs into SDLC-standard artifacts (design-doc.md, api-contracts.md, etc.). |
| 4 | Architecture Decision Records | Write ADRs encoding the human's architectural decisions from Step 0. Each ADR documents context, decision, alternatives considered, and consequences. |
| 5 | Complete Design Artifacts | Fill in any remaining design artifact sections not covered by /deep-plan output. |
| 6 | Data Model | Define data models, schema, and entity relationships. |
| 6a | Data Contract, Readiness, Lineage (conditional) | `/sprd-data` -- when the feature touches customer or personal data: the `data-analyst` drafts `data/data-contract.md` (PII column), `data/data-readiness.md` (advisory) and `data/lineage-audit.md`; a named human confirms the PII classification, which drives the risk tier. |
| 7 | Generate Architecture Diagrams | Produce `architecture-diagrams.html` with required diagram types using Mermaid.js. |
| 7a | Experience (conditional) | `/sprd-experience` -- when the feature has a customer surface: the `visual-designer` (screen) or `conversation-designer` (voice / chat) drafts `experience/user-journey.md`, `experience/surface-layout.md` and `experience/channel-interaction-spec.md`; a named human signs the journey and the contract. |
| 8 | Phase Handoff | Package into `phase3-handoff.md`, including the walking-skeleton definition for Foundation. |
| 9 | Generate Phase Report | Run `generate_phase_report.py`. |

### HITL Gates

**Step 0 -- Resolve Architectural Questions:** Claude extracts every AQ-NN (Architectural Question) from the Phase 2 handoff. For each question, Claude presents 2-3 concrete options with trade-offs and asks the human to decide. ALL AQs must be resolved before any artifact is written. The human's decisions become the basis for ADRs -- Claude encodes them, not invents them.

### Required Artifacts

| Artifact | Description |
|----------|-------------|
| `design-doc.md` | Complete technical design document: architecture overview, component design, interfaces, data flow, security model. |
| `api-contracts.md` | API contract definitions: endpoints, request/response schemas, authentication, error codes. |
| `adrs/` | Directory of Architecture Decision Records. Minimum one ADR. Each has context, decision, alternatives, and consequences. |
| `adr-registry.md` | Index of all ADRs with ID, title, status, and date. |
| `phase3-handoff.md` | Design summary, the walking-skeleton definition, Foundation implications, open questions, risks, and recommended Foundation approach. |
| `spike-findings.md` | The summary of every bounded investigation this design rests on. The code a spike produces is thrown away; this file is the deliverable. |
| `threat-model.md` | Trust boundaries, threats and mitigations per boundary, accepted risks, and the guarded-path map Phase 3 wires its security gates from. |
| `nfr-proving-plan.md` | For every quantified non-functional requirement: how its number will be proved, and the named place that number will be read from. |
| `walking-skeleton-definition.md` | The thin end-to-end slice Phase 3 must ship: named, bounded, and sufficient to exercise every ADR's chosen mechanism at least once. |

### Optional Artifacts

- `data-model.md` -- entity-relationship diagrams and schema definitions
- `sequence-diagrams.md` -- interaction sequences for key flows
- `02-design-report.html` -- self-contained HTML phase report
- `research-notes.md` -- codebase and web research findings from /deep-plan
- `integration-notes.md` -- cross-system integration concerns
- `external-reviews/` -- multi-LLM review outputs
- `deep-plan-checkpoint.yaml` -- session state for Foundation resumption
- `architecture-diagrams.html` -- interactive Mermaid diagrams (recommended)
- `data/data-contract.md`, `data/data-readiness.md`, `data/lineage-audit.md` -- (conditional) the Data seat, from `/sprd-data`
- `experience/user-journey.md`, `experience/surface-layout.md`, `experience/channel-interaction-spec.md` -- (conditional) the Design seat, from `/sprd-experience`

### Primary Skills

- `/deep-plan` -- primary skill; runs thorough architecture analysis
- `/plan` -- secondary skill for structuring design work

### Agents

The orchestrator drives the /deep-plan skill integration directly. Three discipline agents are spawned only when their trigger applies: `data-analyst` (via `/sprd-data`), and `visual-designer` or `conversation-designer` (via `/sprd-experience`, routed by channel). Each proposes; a named human decides, and the sign-offs are recorded at the advance.

### Exit Gate

| Condition | Check | Type |
|-----------|-------|------|
| `design-doc.md` | exists_and_complete | MUST |
| `api-contracts.md` | exists_and_complete | MUST |
| `adrs/` | exists_and_complete | MUST |
| `adr-registry.md` | exists_and_complete | MUST |
| `phase3-handoff.md` | exists_and_complete | MUST |

**Approval:** manual

### Handoff Document

`phase3-handoff.md` contains:
- Design summary and key architectural choices
- The walking-skeleton definition (the thinnest end-to-end slice that proves the architecture, and which slice carries the most risk)
- Foundation implications (what the design means for the rails and the dev environment)
- Open questions for Phase 3
- Technical risks identified during design
- Recommended Foundation approach

### Project Type Adaptations

Phase 2 does not vary by project type. All project types produce the same design artifacts, though the content differs (e.g., a `skill` project has no server architecture but still documents its instruction flow and integration points).

---

## Phase 3: Foundation

### Purpose

Build the factory and prove it on real software. Install and adapt the harness, stand up the rails (CI, grader, correctness, security, and deploy-dev workflows plus branch protection), provision the dev environment from code, then deploy a thin walking skeleton -- including at least one HIGH-risk spec -- end-to-end through the full Build loop into the client's dev environment. This is the hinge of the engagement: the phase where the documents stop and the software starts. Foundation's product is not a feature; it is a working factory with one part already moving through it.

### Entry Gate

| Condition | Type |
|-----------|------|
| Phase 2 exit gate passed | MUST |
| `phase3-handoff.md` reviewed | MUST |
| Walking-skeleton definition and section boundaries from Phase 2 available | MUST |

### Workflow Steps

| Step | Name | Description |
|------|------|-------------|
| 0 | HITL Gate -- Confirm the Rails Plan and the Skeleton Slices | Read `phase3-handoff.md` and the Phase 2 walking-skeleton definition. Before installing anything, confirm with the human: the skeleton's slices and which carries the most risk; where the dev environment lives and who holds branch-protection admin, Actions, runner policy, and the secrets vault; the Setup Owner's deputy; and what `deploy-dev` means for `library`/`cli`/`skill`. |
| 1 | Install and Adapt the Harness | Scaffold from the firm's kit (`CLAUDE.md`, spec template, settings, skills, grader and security-reviewer agents, the Stop hook, workflow YAML, IaC starters). Adapt `CLAUDE.md` to the client's domain, stack standards, risk taxonomy, gated paths, and Definition of Checked, as reviewed PRs. Both-eyes review by the Setup Owner's deputy -- the author is never sole approver. |
| 2 | Stand Up the Rails | Build the five workflows and branch protection (agent proposes, gate disposes): **ci** (hard block), **grader** (required to run, advisory), **correctness** (blocks on a high-confidence defect, named-human override), **security** (blocks on HIGH), **deploy-dev** (merge ships to dev, restores last good on failure). Wire the **Stop hook**. Register Phase 2 security gates against their guarded paths. |
| 3 | The Risk-Tier Map | Produce `risk-tier-map.md`: every codebase area with its tier (HIGH/MEDIUM/LOW) and any registered security gate -- the same taxonomy that lives in `CLAUDE.md`. |
| 4 | Provision the Dev Environment from Code | Draft IaC for the dev environment (HIGH risk; agent-safe IaC funnel: schema-validate -> policy gate -> dry-run -> human approval -> scoped apply). Secrets land in the client's vault, never in code. `N/A` for `library`/`cli`/`skill`. |
| 5 | Run the Walking Skeleton Through the Loop | Author the skeleton's slices as specs and ride each through the full Build loop into dev. At least one HIGH-risk slice runs the loop at HIGH (hard exit condition). Connect the slices end-to-end and run a smoke journey, verified against the Phase 2 definition. |
| 6 | Prove the Rails by Forcing Their Failure | Make each rail fail deliberately and catch it: a failing test proves the Stop hook blocks; a planted spec mismatch proves the grader posts; a planted logic defect proves correctness blocks-and-overrides; a known-bad deploy proves deploy-dev rolls back; a probe PR proves the security gate fires. Record in `pipeline-proof.md`. |
| 7 | The Cadence Plan and the Build Tripwires | Produce `cadence-plan.md`: schedule the Build cadences (daily flow check, weekly intent triage, retro+, setup review) and agree two numbers -- the **WIP cap** and the **review-wait tripwire**. |
| 8 | Phase Handoff | Draft `build-handoff.md` and `foundation-report.md`: the ordered spec backlog, the risk-tier map, the cadence calendar, and open questions. The exit demo runs in the client's own dev environment through the real pipeline. |
| 9 | Generate Visual Report | Generate `.sdlc/reports/03-foundation-visual.html`. |
| 10 | Generate Phase Report | Run `/sprd-gate` to validate and produce `.sdlc/reports/03-foundation-report.html`. |

### HITL Gates

**Step 0 -- Confirm the Rails Plan and the Skeleton Slices:** Before installing the harness or standing up any rail, Claude confirms with the human the skeleton scope and the highest-risk slice, the client access realities (branch-protection admin, Actions, runner policy, secrets vault), the Setup Owner's deputy, and what `deploy-dev` means for non-server targets. Foundation answers four questions and nothing else: Is the harness real and adapted? Are the rails real and enforced? Does the loop actually run? Is the architecture real?

> **CONSTRAINT (intentionally repeated in the phase definition):** Every walking-skeleton slice MUST run the full Build loop on the real rails. Hand-building the skeleton off the rails "because it's only the skeleton" is prohibited -- the skeleton is precisely where the loop and the rails get proven.

### Required Artifacts

| Artifact | Description |
|----------|-------------|
| `foundation-report.md` | Harness summary, rails summary, forced-failure evidence, walking-skeleton outcome (including the HIGH-risk slice and the outcome metric ticking in dev), and open questions. |
| `risk-tier-map.md` | Tier table for every codebase area with rationale, registered security gates (the Phase 2 gates MUST appear), and the risk taxonomy mirrored from `CLAUDE.md`. |
| `cadence-plan.md` | Cadence calendar with owners; the agreed WIP cap; the review-wait tripwire; and the numbers that steer the loop (with the banned activity metrics noted). |
| `build-handoff.md` | Ordered spec backlog ready for triage, the risk-tier map reference, the cadence calendar with WIP cap and review-wait tripwire, open questions, and the proven entry conditions for Build. |
| `data-flow-brief.md` | The one-page brief for the client's security team: what leaves the repo for the model API, what does not, where credentials live, and who can see usage. |

### Optional Artifacts

- `harness-inventory.md` -- what the kit installed and per-file adaptation notes
- `pipeline-proof.md` -- forced-failure evidence, one entry per rail
- `walking-skeleton-spec.md` -- the skeleton slices with per-slice loop evidence (spec, PR, grader verdict, Checker, deploy)
- `03-foundation-report.html` -- the generated phase report

### Primary Skills

- (none primary) -- `/tdd` and `/e2e` as secondary skills during the skeleton's loop runs and the first smoke journey

### Agents

No new custom SDLC agents are introduced; Foundation exercises the harness's own grader and security-reviewer agents and the `build-error-resolver` on build failures, the same agents the Build loop uses.

### Exit Gate

| Condition | Check | Type |
|-----------|-------|------|
| `foundation-report.md` | exists_and_complete | MUST |
| `risk-tier-map.md` | exists_and_complete | MUST |
| `cadence-plan.md` | exists_and_complete | MUST |
| `build-handoff.md` | exists_and_complete | MUST |
| Walking skeleton deployed to the dev environment through the real pipeline and verified against the Phase 2 definition | runtime check | MUST |
| The rails are proven, not just present (Stop hook blocks, gates fire, deploy rolls back) | runtime check | MUST |
| At least one HIGH-risk spec has run the full Build loop | runtime check | MUST |
| The dev environment provisioned from code; secrets in the client's vault | runtime check | MUST |
| The WIP cap and review-wait tripwire are set | runtime check | MUST |

**Approval:** manual

### Handoff Document

`build-handoff.md` is the entry package for the Build loop. It contains:
- The ordered spec backlog ready for the first intent triage
- The risk-tier map reference, including the Phase 2 security gates
- The cadence calendar with the WIP cap and review-wait tripwire
- Open questions carried under their original IDs
- The proven entry conditions for Build (rails, skeleton, dev environment)

### Project Type Adaptations

| project_type | Foundation Focus |
|--------------|-----------------|
| `service` / `app` | Full rails: CI + grader + correctness + security + deploy-dev workflows, IaC dev environment, branch protection, walking skeleton deployed to a real dev environment through the pipeline. All exit conditions apply. |
| `library` / `cli` | Rails without an environment: the CI/grader/correctness/security workflows and branch protection apply; `deploy-dev` becomes a publish-to-internal-feed (or a no-op dry-run). The "walking skeleton" is the thinnest end-to-end invocation path exercised through the loop. |
| `skill` | No compiled deploy target. CI runs lint + scenario checks; the grader and correctness gates run against changed instruction files; the security gate becomes prompt-safety review. The "walking skeleton" is one end-to-end scenario through the loop. Prove the rails by forcing each to fail. |

---

## Build Loop

### Purpose

The continuous middle of the engagement. Every change -- large or small -- runs the same three beats: **Intent** (decide what you want, clearly enough to check, and write it as a spec), **Delegate** (an agent builds it inside bounds a human set, from a plan a human approved), **Discern** (checks and a non-author prove it against the spec, then merge deploys it). The Build loop **replaces the batch Implementation, Quality, and Testing phases** that used to sit at ids 4, 5, and 6.

It is not a phase in the gated sense: there is no artifact exit gate at the end of a loop pass, because checking happens per change. A human declares the backlog feature-complete to leave, which produces `phase7-handoff.md`. The registry marks this entry `continuous: true`; it never auto-advances, and leaving it is always a manual human declaration.

### Why This Is Not a Batched Phase

The visible gap where Implementation / Quality / Testing used to sit is intentional. Batched checking -- write everything, then review everything, then test everything -- is the failure mode the standard exists to kill. When an agent can produce code in minutes, the constraint is not building; it is proving. Checking moves to per-change inside the loop, never a later batch phase. The moment the pod starts skipping the loop for "small" changes is the moment unchecked work creeps back in.

### Entry Gate

| Condition | Type |
|-----------|------|
| Phase 3 (Foundation) exit gate passed | MUST |
| `build-handoff.md` reviewed | MUST |
| Rails proven and walking skeleton deployed | MUST |
| The ordered spec backlog, risk-tier map, and cadence calendar in hand | MUST |
| The WIP cap and review-wait tripwire set | MUST |

### The Three Beats

**Beat 1 -- Intent: decide and write.** Nothing enters the loop as a conversation. A story becomes buildable only by clearing the **Definition of Ready** at weekly intent triage: every acceptance criterion passes the **vague-line test** ("Could two people build different things from this line?"), scope-in and scope-out are both stated, the silent product decisions are surfaced with a named owner, a risk tier is assigned by the Pod Lead, and the harness pattern to reuse is named. Then write the spec -- one file in the repo (`specs/NNNN-name.md`) durable across sessions, with Goal / Why / Scope in-out / Acceptance checks / Risk tier / Delegation plan / Checking plan. A stale spec is a lie; the spec changes in the same PR as the behavior.

**Channel binding (conditional).** A spec with a customer surface is bound to exactly one channel before it is Ready: `/sprd-channel` sets `channel:`, injects the channel's acceptance dimensions as concrete acceptance checks, seeds the harness context if empty, and applies a risk floor that may only raise the tier. An advisory check flags a bound spec that is missing a dimension. Checks that implement a signed `BR-NN` cite it; a spec touching PII-marked fields takes its tier from the data contract.

**Beat 2 -- Delegate: bound and build.** Delegating is drawing the box and approving the plan before the build starts. **Plan mode first, always** -- the agent reads the repo and spec and proposes an approach before writing anything; the Orchestrator corrects or approves. **Three bounds, set per spec:** *Scope* (the file patterns it may touch), *Context* (the one canonical pattern to reuse, named), *Permissions* (what the agent may do without asking -- safe commands auto-allowed, the rest gated). Freedom scales by risk within one change. Fan out only to *explore*; single-thread to *build* shared code. **TDD when the profile or spec requires it** -- and always for a bug fix (write the failing regression test first). The **Stop hook** refuses to let the agent finish on a failing build or red tests.

**Beat 3 -- Discern: prove, then merge.** A change is done when it has been proven against its spec by something other than its author -- not when the code exists. The proving climbs a **five-rung checking ladder**: (1) the done-rule in the harness, (2) the agent re-checks each turn, (3) the blocking Stop hook, (4) the separate **grader** (a fresh agent grading check-by-check against the spec -- where the bug the author's green tests hid goes to die), (5) the human / security gate. In the rails this lands as three layers on every PR: mechanical CI gates (hard block), the grader (required to run, advisory verdict), and the human Checker (hard block, non-author).

**The merge bar** every change clears: CI green; the grader has run; correctness passed or a named-human override recorded; and a **non-author approval -- the author never approves their own work, no exceptions.** A `risk:high` change adds the security workflow pass and a named human sign-off. **Depth scales by risk tier:** LOW stops after the grader's advisory pass and a light human look; MEDIUM gets grader-plus-Checker; HIGH goes all the way up. Merge deploys to dev automatically -- the rails from Foundation.

### HITL Gates

The Build loop's human-in-the-loop discipline is per-change rather than a single Step-0 gate: plan approval in Beat 2, the non-author Checker and (on HIGH) the security sign-off in Beat 3, and the merge bar on every PR. The author never approves their own work.

### Cadences (the week)

Four short meetings replace the ceremony calendar. None asks "what did you do yesterday." They point at the two things that constrain the loop -- the clarity of intent going in, and the review queue coming out:

| Meeting | Length | Replaces | What it does |
|---------|--------|----------|--------------|
| **Flow check** (daily) | 10-15 min | standup | The queue number first: how many changes wait for checking, how long the oldest has waited. Every waiting change gets a Checker; vague specs flagged back to triage; the WIP cap enforced. |
| **Intent triage** (weekly) | 60 min | refinement | Stories become ready specs: vague lines sharpened, silent decisions surfaced, risk tiers assigned, the backlog ordered. Run it with `/sprd-refine` (the agenda, then one spec at a time); the sprint slate it feeds is `/sprd-sprint`. |
| **Retro+** (weekly) | 60 min | retro | Every escaped bug gets the same question -- "which check should have caught it?" -- and the answer becomes a harness improvement. |
| **Setup review** (weekly) | 30-60 min | (new) | The week's harness changes merge: `CLAUDE.md` updates, skill/hook improvements, permission tuning -- versioned, PR'd, deputy-reviewed. |

**Two numbers run the week.** The **WIP cap** keeps the pod from opening more changes than its checking capacity can clear. The **review-wait tripwire** is the alarm on the same constraint: when the median wait crosses the agreed threshold, the pod stops starting new work and clears the queue. The security queue is read separately at every flow check.

### The Numbers That Steer the Loop

Internal dashboard, baseline-and-trend, no vanity targets: **accepted-as-is rate**, **review wait (median)**, **rework/revert rate** and **bounce-back-for-unclear rate**, **escaped bugs** (each answered at Retro+), the **DORA four**, and **security-review wait** on its own line.

**Never tracked, never reported -- the BANNED activity metrics:** velocity, story points, PR count, lines of code. Agents inflate all of them. No activity metrics in client materials, ever.

### Hardening Passes

Some concerns only exist at the integration level -- performance under load, end-to-end journeys, penetration testing. The Quality Engineer plans and runs these as **scheduled hardening passes** (typically one mid-Build and one before deployment prep) using `/e2e` and security tooling. The first hardening pass is also where the test environment gets added alongside dev. A hardening pass runs its own specs through the loop (use the expander pattern: after each integration run, raise specs for 3-5 untested edge cases). Record in `hardening-pass-notes.md`.

### Session Continuity

The loop spans many sessions; the spec is the durable source of truth (the agent re-reads it every session). **One spec = one branch = one PR.** Do not start a new spec while one you own is in-flight and half-built -- finish the in-flight spec first. When `session_health_check.enabled` is true, run the configured command at session start before touching new work; on failure, diagnose and fix the build (spawn `build-error-resolver` if needed) before starting new spec work. At a session boundary, leave the in-flight spec resumable.

### Required Artifacts

| Artifact | Description |
|----------|-------------|
| `phase7-handoff.md` | Produced by the human feature-complete declaration. Names what was built, the current system state in dev, open questions carried forward, deferred items with rationale, and what Documentation must cover that surfaced during Build. |

### Optional Artifacts

- `specs/` -- the spec files (`specs/NNNN-name.md`), the durable per-change record; these live in the repo, not only under `.sdlc/`
- `build-summary.md` -- a rolling summary of merged work, useful for the weekly client async summary and the feature-complete declaration
- `hardening-pass-notes.md` -- per hardening pass: scope, findings, the specs raised, and their resolution

### Primary Skills

- (none primary) -- `/tdd`, `/code-review`, and `/e2e` as secondary skills inside the three beats and the hardening passes

### Agents

The Build loop runs the harness's standing agents inside the beats: the **grader** and **security-reviewer** in CI (Beat 3), and `build-error-resolver` on any build failure. There is no batch agent-orchestration step -- agents are spawned per spec, single-threaded for shared code and fanned out only to explore.

### Exit

The Build loop has **no artifact exit gate**. It is left by a human **feature-complete declaration** -- every committed story has ridden the loop and merged -- which produces `phase7-handoff.md`. `/sprd-gate` for this entry verifies only that `phase7-handoff.md` exists and is complete; it does not batch-check the build, because checking already happened per change. Leaving is always a manual human declaration; there is no auto-advance.

### Project Type Adaptations

The loop's discipline (no spec / no build, plan first, the author never approves their own work, the merge bar) holds identically for every project type. What varies is what the rails ship and what "done" exercises: `service`/`app` deploy to dev; `library`/`cli` publish to an internal feed and prove the invocation path; `skill` runs scenario checks and prompt-safety review against changed instruction files.

---

## Phase 7: Documentation

### Purpose

Prove that someone who isn't the pod can understand, run, and operate the system from its documentation alone -- verified by **cold use**, not by reading. README, API docs, and RUNBOOK are current before deployment, and each is proven by a stranger running it unassisted. Documentation is written for specific audiences: developers (README, API docs), operators (RUNBOOK), and decision-makers (ADRs).

### Entry Gate

| Condition | Type |
|-----------|------|
| Build loop feature-complete | MUST |
| `phase7-handoff.md` reviewed | MUST |

### Workflow Steps

| Step | Name | Description |
|------|------|-------------|
| 0 | HITL Gate -- Scope the Documentation | Read `phase7-handoff.md`. Present to the human: (1) primary audience for each document, (2) which docs exist vs. need creation, (3) company-specific documentation standards, (4) for `library`/`skill` projects, confirm which artifacts apply. |
| 1 | Parallel Documentation Launch | Write README, API docs, and RUNBOOK in parallel. Each targets its specific audience. |
| 2 | API Documentation -- Diff-Based Approach | Compare implemented API against `api-contracts.md` from Phase 2. Document differences and update contracts. |
| 3 | Runbook -- Write for 3am | Write the runbook assuming the reader is an on-call engineer at 3am. Include troubleshooting trees, rollback procedures, and escalation paths. |
| 4 | ADR Finalization | Review all ADRs from Phase 2. Update status (accepted/superseded/deprecated). Add any new ADRs for decisions made during Build. |
| 5 | Cold-Use Verification | Have someone new to the repo run the README checkout unassisted, and have the ops engineer execute the RUNBOOK deploy + rollback + one failure scenario cold. These cold runs are exit conditions, not nice-to-haves. |
| 6 | Phase Handoff | Package into `phase8-handoff.md`. |
| 7 | Generate Reports | Generate `.sdlc/reports/07-documentation-visual.html` and run `generate_phase_report.py`. |

### HITL Gates

**Step 0 -- Scope the Documentation:** Claude reviews the Build handoff and existing documentation state. The human confirms primary audiences, creation vs. update scope, company documentation standards, and which artifacts apply for the project type.

### Required Artifacts

| Artifact | Description |
|----------|-------------|
| `README.md` | Project README with installation, usage, configuration, architecture overview, and contribution guidelines. |
| `api-docs.md` | API reference documentation: endpoints, parameters, responses, authentication, and examples. Required for `service`/`app`/`library`/`cli`. |
| `RUNBOOK.md` | Operational runbook: health checks, common failure modes, troubleshooting trees, rollback procedures, escalation contacts. Required for `service`/`app` only. |
| `phase8-handoff.md` | Documentation summary, deployment prerequisites identified during doc writing, release notes draft, and open questions. |
| `readme-verification.md` | The defect log from someone who did not write the README following it cold, on a clean machine. |
| `runbook-walkthrough.md` | The client's own operations engineer executing a deploy, a rollback, and one failure scenario from the RUNBOOK, cold, using their own permissions. Required for `service`/`app` only. |

### Optional Artifacts

- `CHANGELOG.md` -- version history
- `CONTRIBUTING.md` -- contribution guidelines
- `drift-catalog.md` -- drift between the Phase 2 contracts and what Build shipped
- `07-documentation-report.html` -- self-contained HTML phase report

### Primary Skills

- `/update-docs` -- primary skill for documentation generation

### Agents

No custom SDLC agents are spawned during Documentation. The orchestrator manages parallel documentation writing directly.

### Exit Gate

| Condition | Check | Type |
|-----------|-------|------|
| `README.md` | exists_and_complete | MUST |
| `api-docs.md` | exists_and_complete | MUST |
| `RUNBOOK.md` | exists_and_complete | MUST |
| `phase8-handoff.md` | exists_and_complete | MUST |
| README cold checkout completed by someone new to the repo, unassisted | runtime check | MUST |
| RUNBOOK deploy + rollback + one failure scenario executed cold by the ops engineer | runtime check | MUST |

**Approval:** manual

### Handoff Document

`phase8-handoff.md` contains:
- Documentation completion summary, including the cold-use verification outcomes
- Deployment prerequisites identified during doc writing
- Release notes draft
- Known documentation gaps (deferred)
- Open questions for Deployment phase

### Project Type Adaptations

| project_type | Documentation Scope |
|--------------|-------------------|
| `service` / `app` | Full suite: README, API docs, RUNBOOK, ADR finalization. All artifacts required, including both cold runs. |
| `library` / `cli` | README, API reference (generated from code), CHANGELOG, migration guide if applicable. Skip RUNBOOK. Replace `RUNBOOK.md` exit criterion with CHANGELOG + migration guide; the cold checkout still applies. |
| `skill` | README (install + usage), SKILL.md refinement, example gallery. Skip API docs and RUNBOOK. Replace `api-docs.md` and `RUNBOOK.md` exit criteria with SKILL.md + examples; the cold checkout still applies. |

For `library`/`cli`/`skill` projects, skipped artifacts are marked as `N/A -- {project_type}` in the gate check.

---

## Phase 8: Deployment

### Purpose

Promote to production through the pipeline that has existed since Foundation. Phase 8 adds the rollout decision, the rehearsal, and a named human saying go -- it does not invent a deployment mechanism, because the pipeline already shipped the walking skeleton to dev in Foundation and every merged change since. A good Phase 8 is boring -- it invents nothing.

### Entry Gate

| Condition | Type |
|-----------|------|
| Phase 7 exit gate passed | MUST |
| `phase8-handoff.md` reviewed | MUST |

### Workflow Steps

| Step | Name | Description |
|------|------|-------------|
| 0 | HITL Gate -- Deployment Go/No-Go | Present deployment readiness summary to the human: documentation status, test results, known issues, and the deployment plan. Conduct the recorded go/no-go with every named role asked and answered. |
| 1 | Pre-Deployment Checklist | Verify all deployment prerequisites: environment configuration, secrets management, database migrations, dependency versions. |
| 2 | Rollback Rehearsal in Test | The client's operators rehearse the rollback in the test environment before any production promotion. |
| 3 | Production Promotion | Promote to production through the existing pipeline. Verify production health. |
| 4 | Production Smoke Tests | Run smoke tests against production. Verify critical paths work end-to-end. |
| 5 | Phase Handoff | Package into `phase9-handoff.md`. |
| 6 | Generate Reports | Generate `.sdlc/reports/08-deployment-visual.html` and run `generate_phase_report.py`. |

### HITL Gates

**Step 0 -- Deployment Go/No-Go:** Claude presents the complete deployment readiness summary including documentation status, test results, known issues, and the deployment plan. The recorded go/no-go has every named role asked and answered. No deployment proceeds without human approval.

### Required Artifacts

| Artifact | Description |
|----------|-------------|
| `release-notes.md` | Version release notes: new features, bug fixes, breaking changes, migration instructions, and known issues. |
| `deployment-checklist.md` | Step-by-step deployment checklist: pre-deployment verification, promotion steps, post-deployment validation, and rollback procedure. |
| `smoke-test-results.md` | Production smoke test execution results: which tests ran, pass/fail status, environment details, and any issues encountered. |
| `phase9-handoff.md` | Deployment summary (what, when, where), current system state, monitoring requirements, known issues in production, and escalation contacts. |
| `rollback-rehearsal.md` | The timestamped record of a deploy, a rollback, and a redeploy, run by the client's operators in a real environment before production. |
| `go-no-go-record.md` | The recorded output of the Step 0 ceremony: the decision, every named role's answer and any condition attached, the risks accepted and by whom. |
| `secrets-rotation-record.md` | Production credentials rotated to values the pod has never held, confirmed by name by the client's security function. |

### Optional Artifacts

- `rollback-procedure.md` -- the rehearsed rollback steps
- `deployment-log.md` -- the promotion log
- `08-deployment-report.html` -- self-contained HTML phase report

### Primary Skills

- `/e2e` -- primary skill for smoke test execution

### Agents

No custom SDLC agents are spawned during Deployment. The orchestrator manages the promotion workflow directly.

### Exit Gate

| Condition | Check | Type |
|-----------|-------|------|
| `release-notes.md` | exists_and_complete | MUST |
| `deployment-checklist.md` | exists_and_complete | MUST |
| `smoke-test-results.md` | exists_and_complete | MUST |
| `phase9-handoff.md` | exists_and_complete | MUST |
| Rollback rehearsed in test by the client's operators before production promotion | runtime check | MUST |
| Recorded go/no-go with every named role asked and answered | runtime check | MUST |
| Production smoke tests passing | runtime check | MUST |

**Approval:** manual

### Handoff Document

`phase9-handoff.md` contains:
- **Deployment summary** -- what was deployed, when, where
- **Current system state** -- what is running and how to verify it
- **Monitoring requirements** -- what alerts and dashboards need to be set up
- **Known issues in production** -- anything to watch post-deployment
- **Escalation contacts** -- who to call if something goes wrong

### Project Type Adaptations

| project_type | Deployment Model | Rehearsal | Rollback |
|--------------|-----------------|-----------|---------|
| `service` / `app` | Container or cloud promotion through the existing pipeline. Smoke tests against live endpoints. | Operators rehearse rollback in the test environment | Redeploy previous image/version; reverse DB migrations |
| `library` / `cli` | Package registry publish (npm, PyPI, NuGet). | Install in an isolated environment, run public API smoke tests | Yank the package version; pin consumers to previous version |
| `skill` | File distribution (copy to `.claude/commands/`). | Install skill files on a clean project; run the minimum smoke set | Delete skill files; re-copy previous version |

For `skill`/`library` projects, skip steps referencing staging servers, database migrations, and monitoring dashboards. Focus on: install verification, smoke test execution, rollback documentation, and release artifact creation.

---

## Phase 9: Monitoring

### Purpose

Make production observable, make alerts real (thresholds from measured baselines), prove incident response by drill, and capture the engagement retrospective (the harvest raw material). Monitoring ensures the deployed system is observable, alertable, and maintainable, and feeds **Phase C: Close & Transfer** via `close-handoff.md`.

### Entry Gate

| Condition | Type |
|-----------|------|
| Phase 8 exit gate passed | MUST |
| `phase9-handoff.md` reviewed | MUST |

### Workflow Steps

| Step | Name | Description |
|------|------|-------------|
| 0 | HITL Gate -- Monitoring Scope | Present monitoring plan to the human: which metrics to track, alert thresholds, on-call routing, and dashboard requirements. Get human confirmation of scope. |
| 1 | Monitoring Configuration | Configure health checks, metric collection, log aggregation, and dashboard setup. |
| 2 | Alert Definitions | Define alert rules with thresholds derived from measured baselines (or flagged modeled, with a revisit date), severity levels, routing, and escalation policies. |
| 3 | Incident Response Playbook | Write incident response procedures: detection, triage, mitigation, resolution, and post-incident review steps. |
| 4 | Alert Drill | Execute the alert drill: every critical alert fired and answered from the playbook. |
| 5 | Project Retrospective | Structured retrospective covering what went well, what did not, what to improve, key learnings, and the harvest raw material for the standard. |
| 6 | Phase Handoff | Package into `close-handoff.md` for Phase C. |
| 7 | Generate Reports | Generate `.sdlc/reports/09-monitoring-visual.html` and run `generate_phase_report.py`. |

### HITL Gates

**Step 0 -- Monitoring Scope:** Claude presents the monitoring plan derived from the deployment handoff. The human confirms which metrics to track, alert thresholds, on-call routing, and dashboard requirements.

### Required Artifacts

| Artifact | Description |
|----------|-------------|
| `monitoring-config.md` | Monitoring configuration: health check endpoints, metric collection setup, log aggregation rules, and dashboard definitions. |
| `alert-definitions.md` | Alert rule definitions: metric conditions, thresholds (each from a measured baseline or flagged modeled with a revisit date), severity classification, notification routing, and escalation timelines. |
| `incident-response.md` | Incident response playbook: detection procedures, triage criteria, mitigation steps, resolution procedures, and post-incident review template. |
| `project-retrospective.md` | Structured retrospective: what went well, what did not, improvement areas, key learnings, metrics history, and the harvest raw material for the standard. |
| `close-handoff.md` | Handoff into Phase C: the system's live/observable/drilled state, the retrospective's harvest candidates, the named client Setup Owner, the access inventory to revoke, and open questions. |
| `drill-record.md` | Per critical alert: how it was triggered, the observed detection time, where it routed, who responded, and what changed. The one proof the pager works. |

### Optional Artifacts

- `baseline-data.md` -- the measured baselines behind the alert thresholds
- `09-monitoring-report.html` -- self-contained HTML phase report

### Primary Skills

- `/session-insights` -- secondary skill for retrospective analysis

### Agents

No custom SDLC agents are spawned during Monitoring.

### Exit Gate

| Condition | Check | Type |
|-----------|-------|------|
| `monitoring-config.md` | exists_and_complete | MUST |
| `alert-definitions.md` | exists_and_complete | MUST |
| `incident-response.md` | exists_and_complete | MUST |
| `project-retrospective.md` | exists_and_complete | MUST |
| `close-handoff.md` | exists_and_complete | MUST |
| Every alert threshold derived from a measured baseline (or flagged modeled, with revisit date) | runtime check | MUST |
| Alert drill executed: every critical alert fired and answered from the playbook | runtime check | MUST |

**Approval:** manual

### Handoff Document

Phase 9 is **no longer the final phase**. It hands off into **Phase C: Close & Transfer** via `close-handoff.md`, which carries the live/observable/drilled system state, the retrospective's harvest candidates, the named client Setup Owner, and the access inventory to revoke. The `project-retrospective.md` is the harvest raw material that the close phase feeds back into the delivery standard.

### Project Type Adaptations

| project_type | Monitoring Scope |
|--------------|-----------------|
| `service` / `app` | Full monitoring: health checks, APM, log aggregation, error tracking, uptime monitoring, and alerting dashboards. |
| `library` / `cli` | Download/install metrics, issue tracker monitoring, dependency vulnerability alerts, breaking change detection. No server health checks or APM. |
| `skill` | Usage tracking (if available), user feedback collection, prompt failure monitoring, version adoption tracking. No infrastructure monitoring. |

---

## Phase C: Close & Transfer

### Purpose

Prove the client can run all of it without the pod -- the system, the harness, the loop, and the judgment -- by observed, unassisted use; then exit cleanly and feed the standard. The engagement does not end when the code is done; it ends when the **close gate** passes: the client team ran one real spec end-to-end -- triage, spec, delegate, grade, merge, deploy -- without the pod driving. This phase is **terminal**: there is no handoff out, only a clean exit (access revoked, audited) and a harvest PR back to the delivery standard.

### Entry Gate

| Condition | Type |
|-----------|------|
| Phase 9 exit gate passed | MUST |
| `close-handoff.md` reviewed | MUST |
| The client Setup Owner named before this phase starts | MUST |
| Client engineers available to orchestrate real specs | MUST |

### Workflow Steps

| Step | Name | Description |
|------|------|-------------|
| 0 | HITL Gate -- Confirm the Transfer Is Real Before Testing It | Read `close-handoff.md` and the Phase 9 retrospective. Confirm with the human: client engineers named and available (at least three with pod Checkers, then one solo); the client Setup Owner named and ready to merge harness changes; which real backlog items are the shadow-flip and close-gate candidates; and what pod access exists to revoke. |
| 1 | The Shadow Flip -- Their Hands, Our Eyes | Client engineers take the Orchestrator seat on **at least three real specs** from their own backlog; the pod serves only as Checkers, coaching by question, never by keyboard. Log every place coaching was needed -- each is a transfer gap. |
| 2 | The Harness Audit -- Find Anything Only We Understand | Sweep the repo (read-only `Explore` agent) for skills/hooks/conventions only the pod understands. Every finding becomes a documented fix the **client Setup Owner** merges. "Ask the pod" must return zero results before the gate. The client Setup Owner also ships at least one harness change of their own. |
| 3 | The Close Gate -- One Real Spec, Solo, Observed | One real spec runs the loop end to end with **nobody from the pod driving**. The pod observes silently. Stalls are data; **help voids the run** -- a voided run is re-run on a *different* real spec. Record in `close-gate-evidence.md`. |
| 4 | Hand Over the Record | Deliver the complete engagement record into the client's tooling: `final-handoff-report.md`, every phase report (0-9), the outcomes dashboard re-pointed to client ownership with its quarter-read date, and the debt log with owners and dates. |
| 5 | Revoke Access, Audited | Remove every pod seat, token, repo permission, environment role, and vault access on a checklist, confirmed against the client's audit trail by their security. Rotate any production secrets the pod touched. |
| 6 | The Harvest PR -- Feed the Standard | Open the mandatory improvements PR against the firm's `delivery-standard` repo -- generalized skills, corrected templates, repeatable patterns, with client specifics stripped. Write the retro file into the standard's `retros/`. |
| 7 | Generate Reports | Generate `.sdlc/reports/close-visual.html` and run `/sprd-gate` to produce `.sdlc/reports/close-report.html`. |

### HITL Gates

**Step 0 -- Confirm the Transfer Is Real Before Testing It:** Before scheduling any close activity, Claude confirms the transfer's readiness with the human -- client engineers named and available, the client Setup Owner named and merging, the real-spec candidates, and the access inventory.

> **CONSTRAINT:** The close-gate spec MUST be real work with a real risk tier and real consequences, and the run MUST be unassisted -- any answer, hint, or keyboard touch from the pod voids it. The gap the help revealed is the finding: record it, fix it, and re-run on a *different* real spec.

### Required Artifacts

| Artifact | Description |
|----------|-------------|
| `final-handoff-report.md` | The engagement record in one place: every phase gate and named sign-off, links to all phase reports (0-9), the metrics history, the debt log with owners and dates, and who the client calls now (a future engagement is a new Phase 0). |
| `harness-audit.md` | Findings table (each transfer-risk finding, its location, why it would strand the client), the fixes the client Setup Owner merged, evidence the owner shipped at least one change of their own plus their named deputy, and the zero-result "ask the pod" confirmation. |
| `close-gate-evidence.md` | The shadow-flip record (at least three real specs, who orchestrated, who checked, outcomes, coaching gaps) and the close-gate observation (one real spec end-to-end, client-driven, names and timestamps per loop step, every stall and guardrail event, the merge that deployed, the verdict), plus any re-run record. |
| `access-revocation-checklist.md` | Credential inventory (every seat, token, permission, role, vault access ever granted), removal status with dates, audit-trail confirmation by the client's security, and secret rotation for anything the pod touched. |

### Optional Artifacts

- `outcomes-dashboard-handover.md` -- the dashboard re-pointed to client ownership, caveats intact, quarter-read date on their calendar
- `harvest-pr-notes.md` -- the patterns sent home to the standard, the harvest PR reference, and the retro file
- `close-report.html` -- the generated phase report

### Primary Skills

- (none primary) -- the close gate is run by the client team; the pod observes and audits using the read-only `Explore` agent for the harness audit and the final-report and harvest drafts

### Agents

The harness audit, the final-handoff-report draft, and the harvest-PR draft each use a read-only `Explore` agent to sweep the repo and the engagement record. The close gate itself is run by the client's engineers, not by an agent.

### Exit Gate

| Condition | Check | Type |
|-----------|-------|------|
| `final-handoff-report.md` | exists_and_complete | MUST |
| `harness-audit.md` | exists_and_complete | MUST |
| `close-gate-evidence.md` | exists_and_complete | MUST |
| `access-revocation-checklist.md` | exists_and_complete | MUST |
| Close gate: client team ran one real spec end-to-end without the pod driving, observed and unassisted | runtime check | MUST |
| Pod access revoked and confirmed against the client's audit trail | runtime check | MUST |
| Harvest PR opened against the delivery-standard repo | runtime check | MUST |

**Approval:** manual

### Handoff Document

Close is **terminal**: there is no next phase and no handoff out. The engagement is complete once the close gate passes, pod access is revoked and confirmed, and the harvest PR is opened. If the client wants ongoing help, that is a new agreement with its own Phase 0 -- not a quiet extension of this engagement.

### Project Type Adaptations

The close gate requires a real client team and real backlog specs and cannot be simulated; this holds across project types. The harness audit and access-revocation checklist apply identically. What the close-gate spec exercises follows the project type's Build-loop "done" (deploy for `service`/`app`, publish for `library`/`cli`, scenario run for `skill`).

---

## Phase Transition Protocol

Phase transitions are managed by the `/sprd-next` command, which orchestrates the following sequence:

### 1. Gate Check Execution

The command runs `check_gates.py` against the current phase's exit conditions:

```bash
uv run scripts/check_gates.py --state .sdlc/state.yaml
```

This validates all artifact existence checks and runtime conditions defined in the phase registry.

### 2. Gate Result Evaluation

**If ANY MUST gate fails:**
- Display the failure report with specific blockers
- List remediation suggestions
- Generate the phase HTML report (shows what is missing)
- Do NOT advance the phase

**If all MUST gates pass:**
- Display success message
- Show any SHOULD/MAY warnings
- Generate the final phase HTML report
- Proceed to human sign-off

### 3. HITL Gate -- Human Sign-Off

Every phase carries `approval: manual`. Claude presents the phase summary (what was produced, key decisions made) and asks for confirmation before advancing. The `advance_phase.py` script is NOT called until the human explicitly confirms. There is no auto-advancing phase; the human sign-off step always runs.

### 4. State Update

The `advance_phase.py` script updates `state.yaml`:
- Sets current phase status to `completed` with `completed_at` timestamp
- Sets next phase status to `active` with `entered_at` timestamp
- Sets `current_phase` to the next registry entry **by `order`** (ids are strings; the next phase is the entry with `order + 1`, never `id + 1`)
- Updates `phase_name`
- Appends transition to the `history` array with gate results

### 5. Open Questions Protocol (BLOCKING)

This is the most critical step. After advancing, `/sprd-next` executes a **mandatory, blocking HITL gate**:

1. Read the handoff document that was just produced (e.g., `phase2-handoff.md` when entering Phase 2, `build-handoff.md` when entering the Build loop).
2. Extract ALL Q-NN or AQ-NN items listed under "Open Questions", "What X Must Address", or any similar heading.
3. Display them in a prominent block:

```
BLOCKING: OPEN QUESTIONS MUST BE RESOLVED BEFORE THE NEXT PHASE BEGINS

| ID    | Question          | Needed by        | Proposed default           |
|-------|-------------------|------------------|----------------------------|
| AQ-01 | [question text]   | [who/what needs] | [proposed default]         |
| AQ-02 | [question text]   | [who/what needs] | [proposed default]         |
```

4. For each open question, Claude proposes a reasonable default answer based on all available project context.
5. **WAIT for the user to respond.** Do NOT continue. Do NOT begin writing artifacts.
6. Record resolutions in the handoff document under a "Resolved Questions" section with timestamps.
7. Only after EVERY open question has a confirmed resolution may phase work begin.

If there are no open questions, Claude explicitly states: "No open questions found in the handoff. Proceeding to phase guidance."

### 6. Next Phase Guidance

After the open questions gate is fully resolved, display:
- New phase name and description
- Primary skills to use
- Required artifacts to produce
- Entry criteria (already met by advancing)
- Reference to phase definition file for full details

### Ordered Progression

Phases advance in the registry's `order` sequence, never by `id + 1`. The next phase is the registry entry with `order + 1`. The gap where ids 4, 5, and 6 used to be (Implementation / Quality / Testing) is intentional -- those phases were folded into the continuous Build loop, where checking happens per change. Re-entry to a completed phase is allowed if issues are discovered -- this creates a new history entry with `reentry: true`. There is no `--force` flag for gate checks; exceptional cases use the override protocol documented in `references/validation-rules.md`.

### Gate Severity Summary

| Severity | Effect on Advancement |
|----------|----------------------|
| MUST | Blocks advancement. Phase cannot advance until this passes. |
| SHOULD | Warning. Surfaced to human but does not block. |
| MAY | Informational. Logged only. |

---

## Visual Phase Report Protocol

Every phase generates a self-contained HTML report as one of its final steps. There are two types of visual output:

### Phase Reports (generate_phase_report.py)

Generated by running:
```bash
uv run scripts/generate_phase_report.py --state .sdlc/state.yaml --phase <id>
```

These reports:
- Are self-contained single-file HTML (CSS and JS inlined)
- Can be opened directly in a browser with no server required
- Display all phase artifacts with their content
- Include exit gate status showing phase readiness
- Show missing artifacts as labeled placeholder sections (not errors)

### Visual Reports (/visual-explainer)

Generated using the `/visual-explainer` skill (or equivalent HTML generation). These are interactive stakeholder review artifacts stored at `.sdlc/reports/<slug>-visual.html`.

**Visual standards:**
- Self-contained HTML (no external assets except CDN fonts and Mermaid)
- Dark theme default: `#0f1117` background, `#6c8ef7` accent blue, `#4ade80` green
- Sticky sidebar TOC for navigation between sections
- Zoom controls on all Mermaid diagrams
- Staggered fade-in animations (respecting `prefers-reduced-motion`)
- Light and dark theme support via `prefers-color-scheme`
- Responsive layout (sidebar collapses to horizontal bar on mobile)

**Phase-specific visual report content:**

| Phase | Key Visualizations |
|-------|-------------------|
| Phase 0: Discovery | Personas, scope boundaries, problem-impact mapping |
| Phase 1: Requirements | Requirements by priority, epic breakdown, NFR radar chart |
| Phase 2: Design | Architecture layer diagram, core loop flowchart, data flow, walking-skeleton slice map, trust boundary diagram |
| Phase 3: Foundation | Rails status board (each workflow present/proven), walking-skeleton slice tracker, risk-tier map, cadence calendar with WIP cap and review-wait tripwire |
| Build Loop | Flow/queue dashboard, checking-ladder status, accepted-as-is and review-wait trends, hardening-pass tracker |
| Phase 7: Documentation | Documentation completeness audit, API coverage, README cold-checkout result, RUNBOOK cold-run completeness |
| Phase 8: Deployment | Promotion pipeline status, production smoke test results, rollback-rehearsal record, go/no-go roster |
| Phase 9: Monitoring | Monitoring configuration status, baseline-to-threshold mapping, alert routing overview, alert-drill record |
| Phase C: Close & Transfer | Shadow-flip spec tracker, harness-audit findings, close-gate observation record, access-revocation checklist |

---

## Handoff Chain

The handoff chain is the connective tissue of the SDLC. Each phase reads the previous phase's handoff document as its starting context and produces a handoff for the next phase.

```
Phase 0: Discovery
  produces -> phase1-handoff.md
                |
Phase 1: Requirements
  reads    <- phase1-handoff.md
  produces -> phase2-handoff.md
                |
Phase 2: Design
  reads    <- phase2-handoff.md
  produces -> phase3-handoff.md
                |
Phase 3: Foundation
  reads    <- phase3-handoff.md
  produces -> build-handoff.md
                |
Build Loop
  reads    <- build-handoff.md
  produces -> phase7-handoff.md   (on human feature-complete declaration)
                |
Phase 7: Documentation
  reads    <- phase7-handoff.md
  produces -> phase8-handoff.md
                |
Phase 8: Deployment
  reads    <- phase8-handoff.md
  produces -> phase9-handoff.md
                |
Phase 9: Monitoring
  reads    <- phase9-handoff.md
  produces -> close-handoff.md
                |
Phase C: Close & Transfer
  reads    <- close-handoff.md
  produces -> final-handoff-report.md + harvest PR (terminal: no handoff out)
```

The handoff file names jump `3 -> build -> 7` -- there is no `phase4-handoff.md`, `phase5-handoff.md`, or `phase6-handoff.md`, because the old Implementation / Quality / Testing phases were folded into the continuous Build loop. The Build loop emits `phase7-handoff.md` directly when a human declares the backlog feature-complete.

### Handoff Document Structure

Every handoff document follows a consistent structure:

1. **Summary** -- key findings or outputs from the phase (5-10 bullets)
2. **Decisions Made** -- what was decided and the rationale
3. **Implications for Next Phase** -- what the next phase needs to know about what was produced
4. **Open Questions** -- specific questions the next phase must resolve (Q-NN or AQ-NN format). These are BLOCKING -- the open questions protocol in `/sprd-next` forces resolution before any new-phase work begins.
5. **Risks** -- risks to carry forward with probability/impact ratings
6. **Recommended Starting Point** -- where the next phase should begin and what to tackle first

### Open Question Identifiers

- **Q-NN** -- general open questions (used in Discovery and later phases)
- **AQ-NN** -- architectural questions (introduced in the Phase 2 handoff, resolved at the start of Phase 2)

Every open question must include: the question text, who or what needs the answer, and a proposed default based on project context. The human confirms, adjusts, or replaces each default before phase work begins.

---

*This document reflects the Shepherd plugin phase-registry.yaml v2.0 and the phase definition files `phases/00-discovery.md`, `01-requirements.md`, `02-design.md`, `03-foundation.md`, `build-loop.md`, `07-documentation.md`, `08-deployment.md`, `09-monitoring.md`, and `close.md`.*
