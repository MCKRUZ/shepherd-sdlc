# Phase 2: Design

## Purpose
Create a software architecture that satisfies the requirements, with explicit decisions recorded as ADRs, API contracts defined, and enough detail that implementation can proceed without architectural ambiguity. Stakeholders should be able to read the design and verify it solves the right problem the right way.

## Entry Criteria
- Phase 1 exit gate passed and `phase2-handoff.md` reviewed
- Architectural implications from NFRs understood

## Workflow

### Step 0: HITL Gate — Resolve Architectural Questions

> **HITL GATE:** Read `phase2-handoff.md`. Extract every AQ-NN (Architectural Question) listed in "What Design Must Address". For each AQ, present 2–3 concrete options with trade-offs to the human using `AskUserQuestion`. Collect human decisions for ALL AQs **before writing any artifact**. These human decisions become the ADRs — Claude encodes them, not invents them.

Do not proceed to Step 1 until all AQs are resolved.

### Step 1: Spec Synthesis

Run the spec synthesis script to combine Phase 0–1 artifacts into a single spec file that `/deep-plan` can consume:

```bash
uv run scripts/synthesize_spec.py --state .sdlc/state.yaml --output planning/spec.md
```

This reads `requirements.md`, `non-functional-requirements.md`, `epics.md`, `constraints.md`, and `phase2-handoff.md` and produces `planning/spec.md`.

### Step 2: Launch /deep-plan (Steps 1–15)

Invoke `/deep-plan` with the synthesized spec. This runs /deep-plan's full research-through-review workflow:

```
/deep-plan @planning/spec.md
```

**What /deep-plan does in this phase:**
1. **Research (steps 6–7):** Analyzes the existing codebase and searches the web for best practices relevant to the architecture. Produces `planning/claude-research.md`.
2. **Interview (steps 8–9):** Conducts a structured Q&A with the human to clarify technical decisions, constraints, and trade-offs. The AQ-NN answers from Step 0 above should be provided as context. Produces `planning/claude-interview.md`.
3. **Spec synthesis (step 10):** Combines all inputs into `planning/claude-spec.md`.
4. **Plan generation (step 11):** Writes the prose architecture blueprint — `planning/claude-plan.md`. This is the primary design artifact. It contains component architecture, data models, API designs, and cross-cutting concerns as prose (not full code — only type signatures, directory trees, and configuration keys).
5. **External review (step 13):** If external LLMs are configured (Gemini, OpenAI), runs a multi-LLM review of the plan. Otherwise, falls back to an Opus subagent review. Produces `planning/reviews/iteration-1-*.md`.
6. **Feedback integration (steps 14–15):** Integrates review feedback into the plan. The human reviews and approves `planning/claude-plan.md` before proceeding.

**Stop /deep-plan after step 15.** The remaining steps (TDD planning, section splitting) belong to Phase 3.

### Step 3: Map /deep-plan Outputs to SDLC Artifacts

Run the artifact mapping script to transform /deep-plan outputs into SDLC locations:

```bash
uv run scripts/map_deep_plan_artifacts.py --state .sdlc/state.yaml --phase 2 --planning-dir planning/
```

This produces:
- `.sdlc/artifacts/02-design/design-doc.md` — skeleton extracted from `claude-plan.md`
- `.sdlc/artifacts/02-design/api-contracts.md` — skeleton extracted from `claude-plan.md`
- `.sdlc/artifacts/02-design/phase3-handoff.md` — section boundaries from the plan
- `.sdlc/artifacts/02-design/research-notes.md` — copy of `claude-research.md`
- `.sdlc/artifacts/02-design/integration-notes.md` — copy of `claude-integration-notes.md`
- `.sdlc/artifacts/02-design/external-reviews/` — copy of review files
- `.sdlc/artifacts/02-design/deep-plan-checkpoint.yaml` — session state for Phase 3 resumption

### Step 4: Architecture Decision Records

Extract architectural decisions from `planning/claude-plan.md` and the human's AQ-NN answers from Step 0. For each significant decision:

1. Present the decision to the human with options (if not already decided in Step 0)
2. Write an ADR using the template at `templates/phases/02-design/adrs/ADR-template.md`
3. Number sequentially: ADR-001, ADR-002, etc.
4. Store in `adrs/ADR-NNN.md`
5. Register each ADR in `adr-registry.md`

**What warrants an ADR:** Technology selection, structural patterns, integration approach, data storage decisions, security model, API design choices. If the decision would cause significant rework if reversed, it needs an ADR.

### Step 5: Complete Design Artifacts

Review and complete the generated skeletons:

- **`design-doc.md`**: Fill any `<!-- FILL: -->` markers. Ensure it covers architecture overview, component descriptions, key data flows, cross-cutting concerns, and technology choices.
- **`api-contracts.md`**: Fill any gaps. Ensure it covers all endpoints, request/response schemas, authentication, error codes, and versioning strategy.

These skeletons are starting points — the human should review and enrich them.

### Step 6: Data Model
Define the data structures:
- Entities and their relationships
- Key fields and types
- Persistence strategy

### Step 6a: Data Contract, Readiness and Lineage (conditional — `/sprd-data`)

**Trigger:** the feature reads or writes customer or personal data, or depends on data nobody has
checked is actually there. When it applies, run `/sprd-data`: the `data-analyst` agent interviews,
then drafts under `data/`: `data-contract.md` (every field, with an explicit **PII?** column),
`data-readiness.md` (availability / completeness / quality — advisory), and `lineage-audit.md`
(source → transform → sink, with retention and audit points).

> **HITL GATE:** A named human confirms the PII classification on each field — PII is a **risk-tier
> driver** and pushes the dependent specs toward HIGH. Readiness gaps become `DL-NN` decision-log
> items with an owner and a clock; readiness never blocks, and the analyst never decides the fix.

### Step 7: Design-Level Threat Review

Threat modelling belongs here, not only in Phase 3. Phase 3 wires the build-time security gates
*from this review* — without it, that step has no input and the guarded paths get chosen by
whoever is wiring them, on the day, from memory. Phase 3 keeps its own pass: a confirmation that
the gates this review called for actually got wired.

Work from the components, data flows and trust boundaries just defined — a threat review before
there is a design to review is theatre.

For each trust boundary the design crosses:
- **What crosses it** — data, credentials, or control. Name the sensitivity: PII, payment,
  auth material, client-confidential.
- **What could go wrong** — spoofing, tampering, disclosure, denial, elevation. One line each,
  concrete to this system, not a checklist recital.
- **The mitigation** — the design change or control that addresses it, and where it lives.
- **The guarded path** — the file patterns that, once built, must trigger the security workflow
  on any PR touching them. This column is the handoff to Phase 3.

Record the result in `threat-model.md`. Its mitigation map is what Phase 3 registers as guarded
paths, and what the Build loop's HIGH-risk tier is calibrated against.

> **HITL GATE:** Present the trust boundaries and the proposed guarded paths to the human using
> the `AskUserQuestion` tool. Which paths are guarded is a risk decision with a named owner — the
> agent proposes the map, a human accepts it. An unreviewed guarded-path list means the security
> gate protects whatever Claude guessed was sensitive.

### Step 7a: Experience — Journey, Surface Layout, Interaction Contract (conditional — `/sprd-experience`)

**Trigger:** the feature has a customer surface — a screen, a voice line, a chat thread. When it
applies, run `/sprd-experience` after the architecture is chosen (the surface layout depends on it).
It routes by channel: `ag-ui` to the `visual-designer`, `voice` / `chat` to the
`conversation-designer`. The designer drafts under `experience/`: `user-journey.md` (including
abandon, failure and dead-end paths), `surface-layout.md` (screens, or a turn-by-turn script, or a
message flow), and `channel-interaction-spec.md` — the contract the surface and the system agree on,
co-authored with Engineering where it is an event or API contract.

> **HITL GATE:** Design proposes; a named human signs the journey and the interaction contract, with
> Engineering co-signing the contract. At Build, `/sprd-channel` binds each surface spec to its one
> channel and injects the channel's acceptance dimensions from this contract as concrete checks.

Discipline sign-offs are recorded at the phase advance beside the phase's own signature
(`/sprd-next` captures them as `Discipline:Section:Name`).

### Step 8: Generate Architecture Diagrams

Generate visual architecture diagrams using the `/visual-explainer` skill (or equivalent HTML diagram generation). Replace all ASCII art in `design-doc.md` with proper rendered diagrams. Output a self-contained HTML file at `.sdlc/reports/architecture-diagrams.html`.

**Required diagrams:**
1. **Architecture Layer Diagram** — All system layers with components, color-coded by layer, showing trust boundaries to external systems.
2. **Core Loop / Game Loop / Request Flow** — The primary data/control flow as a Mermaid flowchart showing the circular or sequential path through the system.
3. **Data Flow** — Step-by-step resolution of the primary use case, from input through processing to output. Use Mermaid with color-coded nodes by layer.
4. **Implementation Section Dependencies** — A DAG showing the implementation sections from `phase3-handoff.md` with their dependency relationships and parallelization opportunities.
5. **Trust Boundary / Security Diagram** — Security model showing trusted process boundary, external systems, and data flow across trust boundaries.

**Rendering approach:**
- Use **Mermaid.js** (CDN) for flowcharts, data flows, dependency graphs, and security diagrams. Use `theme: 'base'` with `themeVariables` matching the project's visual style.
- Use **CSS Grid cards** for architecture layer diagrams where card content (component lists, descriptions) matters more than connections.
- Include **zoom controls** (+/−/reset) on every Mermaid diagram container.
- Include a **sticky sidebar TOC** for navigation between diagrams.
- Match the visual style to the SDLC phase reports (dark theme: `#0f1117` background, `#6c8ef7` accent blue, `#4ade80` green).
- The HTML file must be **self-contained** — no external assets except CDN links for fonts and Mermaid.

**If `/visual-explainer` skill is available:** Invoke it with a prompt describing all 5 diagrams, the project's architecture details from `design-doc.md`, and the desired output path. The skill handles aesthetic choices, Mermaid theming, and responsive layout.

**If not available:** Generate the HTML directly using the Mermaid CDN patterns. The diagrams must still be proper rendered flowcharts — never fall back to ASCII art in the final artifacts.

### Step 9: Phase Handoff
Review and complete `phase3-handoff.md` (generated in Step 3). Ensure it contains:
- Design summary and key decisions
- Section breakdown for implementation (logical units of work)
- Recommended implementation order with dependency rationale
- Interface contracts between sections
- Open technical questions for implementation phase
- Risks identified during design

### Step 10: Generate Phase Report
Run `/sprd-gate` to validate exit criteria and automatically generate the phase HTML report at `.sdlc/reports/02-design-report.html`. Share this report with stakeholders for review before requesting sign-off. The report includes artifact inventory and gate status.

## Artifact Specifications

### `design-doc.md` (REQUIRED)
Must contain ALL of:
- **Architecture overview** — component diagram and responsibilities
- **Component descriptions** — what each does and what it owns
- **Key data flows** — how data moves through the system for primary use cases
- **Cross-cutting concerns** — error handling, logging, security, configuration
- **Technology choices** — with rationale (reference the ADRs)

### `api-contracts.md` (REQUIRED)
Must contain ALL of:
- All endpoints / interfaces
- Request and response schemas (table or code block)
- Authentication requirements per endpoint
- Error response format and error codes
- Versioning strategy

### `adrs/` directory (REQUIRED — minimum one ADR)
Each ADR must contain:
- **Context** — the situation that forced a decision
- **Decision** — what was chosen
- **Alternatives considered** — what was rejected and why
- **Consequences** — positive and negative outcomes of the decision

Use the template at `templates/phases/02-design/adrs/ADR-template.md`. Name files `ADR-NNN.md` with sequential three-digit numbering.

### `adr-registry.md` (REQUIRED)
Must contain ALL of:
- **Active ADRs table** — ADR number, title, status, date, and what it decides
- **Superseded ADRs table** — historical record of replaced decisions
- **Proposed ADRs table** — decisions under review

Use the template at `templates/phases/02-design/adr-registry.md`. Every ADR in the `adrs/` directory must have a corresponding entry in this registry.

### `phase3-handoff.md` (REQUIRED)
Must contain ALL of:
- Design summary and key decisions
- Section breakdown for implementation (logical units of work)
- Recommended implementation order with dependency rationale
- Interface contracts between sections (what each section needs from others)
- Open technical questions for implementation phase
- Risks identified during design

### `architecture-diagrams.html` (RECOMMENDED)
A self-contained HTML page with rendered architecture diagrams (Mermaid + CSS). Must include:
- Architecture layer diagram (components by layer)
- Primary flow diagram (core loop or request path)
- Data flow diagram (step-by-step processing)
- Implementation section dependency graph (DAG)
- Trust boundary / security model diagram

Generated via `/visual-explainer` skill or equivalent HTML generation. Stored at `.sdlc/reports/architecture-diagrams.html`. Share with stakeholders as a visual companion to `design-doc.md`.

### `threat-model.md` (REQUIRED)

The output of Step 7, and the input Phase 3 wires its security gates from.

Must contain ALL of:
- **Trust boundaries** — every boundary the design crosses, and what crosses it
- **Threats per boundary** — concrete to this system; a recital of STRIDE with no system in it is
  not a threat model
- **Mitigations** — the design change or control for each, and where it lives
- **The guarded-path map** — file patterns that must trigger the security workflow once built.
  This is the handoff to Phase 3, which registers them and confirms they fire.
- **Accepted risks** — anything knowingly not mitigated, with the named human who accepted it

> **Required for every engagement, not only the ones handling auth, payments or PII.** Promoted to
> a hard artifact gate in 1.0.0, on the major version and with the migration note the earlier
> RECOMMENDED note asked for. Every system has guarded paths — deploy credentials and CI secrets
> at minimum — and Phase 3 has nothing to wire its security gates from without this map.
>
> **If the review genuinely did not happen**, say so *in this file*: a line reading
> `WAIVED: <name> — <reason>`. The gate accepts it and reports it, by name, in the record the
> approver signs against. A missing file still blocks. The escape is from the work, not the
> record — an exception nobody can see is how a gate stops being a gate.

### Optional Artifacts (from /deep-plan)
- `research-notes.md` — codebase and web research findings
- `integration-notes.md` — cross-system integration concerns
- `external-reviews/` — multi-LLM review outputs (Gemini, OpenAI, Opus)
- `deep-plan-checkpoint.yaml` — session state for Phase 3 resumption

### `spike-findings.md` (REQUIRED)

The summary of every bounded investigation this design rests on. One spike answers one question
that nobody could answer from documentation, against the live system.

The code a spike produces is thrown away. **This file is the deliverable** — a finding that is not
written down was not a spike, it was a detour.

Must contain, per spike:
- **The question** — phrased so an answer would be recognisable. Not "look at the carrier API" but
  "does the carrier API deduplicate on our idempotency key, or do retries create duplicate claims?"
- **What was tested against** — which system, which environment, which version. Sandbox and live
  behave differently and the difference is usually the finding
- **What was observed** — raw enough that someone else could check it
- **The assumption, and whether it survived** — including "still unknown," which is a real result
- **What it changes** — the spec now writable, the ADR to revise, the risk newly visible

If the design depends on no unverified assumption, say that explicitly and name who confirmed it.
An empty file is not the same claim as "we checked, and there were none."

> **HITL GATE:** Claude does not run spikes — they touch live systems with real credentials. Ask
> the human which integrations and behaviours this design assumes, and refuse to advance until each
> has a recorded finding or a named waiver.

> **If it genuinely did not happen**, say so *in this file*: a line reading
> `WAIVED: <name> — <reason>`. The gate accepts it and reports it, by name, in the record the
> approver signs against. A missing file still blocks. The escape is from the work, not the
> record — an exception nobody can see is how a gate stops being a gate.

### `nfr-proving-plan.md` (REQUIRED)

For every quantified non-functional requirement: how its number will be proved, and the named place
that number will be read from.

A threshold with no proving plan is a wish with a decimal point. Phase 9 reads this file back when
the system is live and the target is either met or it is not — if the method was never agreed, that
conversation becomes an argument about what the number meant.

Must contain, per NFR:
- **The requirement id and its threshold**
- **The verification method** — the load profile, the query, the test, the measurement window
- **Where the number is read** — a named dashboard, log query, or report. Not "monitoring"
- **Who reads it, and when** — the person and the phase
- **What happens if it misses** — revise the target, change the design, or accept it with a name

Aspirational thresholds are honest and belong here too; what is not acceptable is a number nobody
has agreed how to check.

> **HITL GATE:** The measurement method is an engineering commitment, not a documentation task.
> Confirm each with the Quality Engineer before writing it down.

> **If it genuinely did not happen**, say so *in this file*: a line reading
> `WAIVED: <name> — <reason>`. The gate accepts it and reports it, by name, in the record the
> approver signs against. A missing file still blocks. The escape is from the work, not the
> record — an exception nobody can see is how a gate stops being a gate.

### `walking-skeleton-definition.md` (REQUIRED)

The thin end-to-end slice Phase 3 must ship: named, bounded, and sufficient to exercise every ADR's
chosen mechanism at least once.

This is the *definition*, written in design. Phase 3 produces `walking-skeleton-spec.md`, the
*evidence* that the thing was built and rode the full loop — and its checkpoint verifies the running
software against this file. Without it, that comparison has nothing to compare against, and "the
skeleton is done" becomes a matter of opinion.

Must contain:
- **The slice** — the one user-visible path it proves, end to end
- **Every ADR it exercises** — with the mechanism each one chose. An ADR no slice touches is an
  architectural decision nobody will test until it is expensive
- **The boundaries** — what is deliberately stubbed, and what that defers
- **Done means** — the observable condition that ends Phase 3, agreed now rather than argued later

> **HITL GATE:** Present the proposed slice and its ADR coverage to the Setup Owner and Quality
> Engineer. A skeleton that misses an ADR is the common failure and it is invisible until Phase 3
> is over.

> **If it genuinely did not happen**, say so *in this file*: a line reading
> `WAIVED: <name> — <reason>`. The gate accepts it and reports it, by name, in the record the
> approver signs against. A missing file still blocks. The escape is from the work, not the
> record — an exception nobody can see is how a gate stops being a gate.
### `consistency-check-record.md` (OPTIONAL)

Requirements traced against the design in both directions, with every orphan resolved.

Both directions is the point. Forward finds requirements the design forgot; backward finds design
nobody asked for, which is the more expensive of the two and the one no checklist catches.

Must contain: the two traces, every orphan found, and its resolution — designed, deferred with an
owner, or removed.

> **Optional by design.** Its absence does not by itself mean the phase went badly, so the gate
> does not block on it — but the approver is asked about it at sign-off. Write it when the work
> happens; a receipt written later from memory is worth less than no receipt at all.
### `data/data-contract.md`, `data/data-readiness.md`, `data/lineage-audit.md` (OPTIONAL — conditional, `/sprd-data`)

The Data seat's three artifacts. The contract must carry a PII column on every field; the readiness
assessment flags gaps as `DL-NN` references; the lineage names retention and audit points.

> **Conditional by design.** Required when its trigger applies; absent otherwise, and the phase
> report says so. The gate does not block on it — the approver is asked at sign-off whether the
> trigger applied and, if it did, whether the artifact exists and its owner signed.

### `experience/user-journey.md`, `experience/surface-layout.md`, `experience/channel-interaction-spec.md` (OPTIONAL — conditional, `/sprd-experience`)

The Design seat's three artifacts for one channel-bound surface. The journey must include failure
paths; the layout is channel-adaptive; the interaction spec lists each of the channel's acceptance
dimensions with the contract element and the concrete acceptance check that will be injected into
the spec at `/sprd-channel`.

> **Conditional by design.** Required when its trigger applies; absent otherwise, and the phase
> report says so. The gate does not block on it — the approver is asked at sign-off whether the
> trigger applied and, if it did, whether the artifact exists and its owner signed.

## Exit Criteria
- [ ] `design-doc.md` covers all major components and cross-cutting concerns
- [ ] At least one ADR exists for each significant technology/pattern decision
- [ ] `adr-registry.md` lists all ADRs with correct statuses
- [ ] `api-contracts.md` covers all system interfaces
- [ ] Design reviewed and approved by stakeholder (manual gate)
- [ ] Implementation sections are clearly defined in the handoff
- [ ] *(recommended)* Architecture diagrams rendered as HTML, not ASCII art, at
      `.sdlc/reports/architecture-diagrams.html` — see the RECOMMENDED artifact spec above.
      Raised to the approver at sign-off; not a hard block.
- [ ] *(only if `/deep-plan` was used)* `deep-plan-checkpoint.yaml` exists — Phase 3 reads it as
      the source of the walking skeleton's slices. A Phase 2 done without `/deep-plan` has no
      checkpoint to produce, so this is conditional rather than required.
- [ ] *(conditional)* Where the feature touches personal data: the data contract's PII
      classification is confirmed by a named human and every dependent spec's tier reflects it
- [ ] *(conditional)* Where the feature has a customer surface: the journey and the interaction
      contract are signed (Engineering co-signs the contract); discipline sign-offs recorded at the
      advance

## HTML Report
The phase report is generated automatically when you run `/sprd-gate` or `/sprd-next`. It is written to `.sdlc/reports/02-design-report.html` and is fully self-contained — share it with stakeholders as the review artifact for the manual sign-off gate.

To regenerate at any time: `/sprd-phase-report`

## Guidance
- A good design doc lets a new developer understand the system without asking questions.
- ADRs are most valuable for decisions that seem obvious — document WHY, not just WHAT.
- API contracts should be defined before implementation begins, not inferred from it.
- Over-specified design is better than under-specified — wrong designs get caught in review.
- `/deep-plan`'s external review (multi-LLM) adds independent architecture critique — review the findings in `external-reviews/` before finalizing.
- The `planning/` directory is preserved alongside `.sdlc/artifacts/` for /deep-plan's internal session continuity and any future re-runs.

## Coaching Prompts

When operating in coaching mode (`/sprd-coach`) for this phase:

### Opening (no artifacts yet)
- "What are the key architectural drivers — what matters most: performance, maintainability, time-to-market?"
- "What existing systems does this need to integrate with?"
- "Where are the trust boundaries? What's inside your control vs. external?"
- "What technology choices have already been made vs. what's still open?"

### Progress Check (some artifacts exist)
- "Your architecture covers the core flow. Have you considered the failure modes?"
- "I see [N] ADRs. Are there any decisions you're still uncertain about?"

### Ready Check (all artifacts present)
- "Design looks comprehensive. Are the security boundaries clearly defined?"
- "Any areas where the design feels over-engineered or under-specified?"
