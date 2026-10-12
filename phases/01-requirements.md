# Phase 1: Requirements

## Purpose
Decompose the problem statement into a complete, prioritized, and verifiable set of requirements. Every requirement must trace back to a stakeholder need from Phase 0. At phase end, a designer should be able to start architecture without ambiguity about what to build.

## Entry Criteria
- Phase 0 exit gate passed and `phase1-handoff.md` reviewed
- Open questions from Phase 0 answered or formally escalated

## Workflow

### Step 0: HITL Gate — Confirm Scope Before Writing Requirements

> **HITL GATE:** Read `phase1-handoff.md`. Confirm with the human using the `AskUserQuestion` tool — do not use inline markdown for HITL questions: (1) Are the open questions (Q-NN) from Discovery answered? (2) Is the prioritization (P0/P1/P2) clear? (3) Are there any requirements the human expects that weren't captured in Discovery? (4) If document intake was performed in Phase 0, review the document registry — are there requirements implied by the source documents that aren't captured in the handoff? Do not begin writing requirements until the human confirms scope.

### Step 1: Functional Requirements
For each stakeholder pain from the problem statement, define what the system must DO:
- Write in "The system SHALL..." form
- Assign priority: P0 (launch blocker) / P1 (core value) / P2 (enhances) / P3 (future)
- Group by functional domain
- Every P0 must trace to a Phase 0 pain point
- **Source Document traceability (when document intake was performed):** Link each requirement to its source document(s) using DOC-NNN IDs from the document registry. A single requirement MAY trace to multiple documents. Requirements not derived from external documents use "Discovery interview" or "Stakeholder input" as the source.

**Error Specification (REQUIRED for every P0/P1 requirement):** Each requirement must explicitly define:
- **Accepts:** What valid inputs/preconditions does this requirement expect?
- **Returns:** What is the expected output/postcondition on success?
- **Errors:** What happens when inputs are invalid, services are unavailable, or preconditions aren't met? List each error case with the expected behavior.

Vague error handling like "handle invalid input gracefully" is not acceptable. Specify: "If email format is invalid, return 400 with field-level error message identifying the invalid field."

### Step 2: Non-Functional Requirements
Define measurable quality attributes — quantify every single one:
- Performance: response time, throughput, load conditions
- Security: auth model, data classification, compliance
- Scalability: growth projections, headroom needed
- Reliability: uptime SLA, RTO, RPO
- Maintainability: observability, code standards, deployment model

"Fast" is not an NFR. "P95 < 200ms under 1000 concurrent users" is.

**Measurement Basis (REQUIRED for every numeric threshold):** For each quantitative NFR, record WHERE the threshold number came from. Every threshold must be one of:
- **Measured** — derived from profiling, benchmarks, or monitoring data. Cite the source.
- **Industry standard** — a widely-accepted norm for this type of system. Cite the reference.
- **Contractual** — required by a SLA, regulation, or stakeholder agreement. Cite the document.
- **Aspirational** — a best-guess target with no data. Tag it `[aspirational — validate in the Build loop]`.

A threshold tagged `[aspirational]` is not a failure — it is honest. What is not acceptable: a numeric threshold with no stated basis that gets treated as a validated requirement. Aspirational thresholds must be measured during the Build loop and revised if the measurement shows they are unachievable.

### Step 3: Epics
For each P0 and P1 requirement:
- Format: "As a [persona], I want [capability] so that [benefit]"
- Acceptance criteria in Given/When/Then (minimum: happy path + one error scenario)
- Link each epic to its source requirement ID

### Step 3a: Feature Decomposition (conditional — `/sprd-feature`)

**Trigger:** an epic spans more than one customer surface or persona, or needs carving into buildable
specs before Build. When it applies, run `/sprd-feature`: the `feature-architect` agent interviews,
then drafts `feature-brief.md` — one epic decomposed into features and specs, each row carrying its
**channel** and **persona**, with shared logic split out as channel-agnostic specs. **One channel per
spec.**

> **HITL GATE:** The agent proposes the decomposition and the risk tiers; a named human confirms or
> edits every row. Any product choice the brief cannot settle becomes a `DL-NN` decision-log item.

### Step 3b: Business Rules and Golden Scenarios (conditional — `/sprd-rules`)

**Trigger:** the feature encodes policy — eligibility, pricing, coverage, entitlement, anything with a
rule book. When it applies, run `/sprd-rules`: the `bizreq-analyst` agent interviews the domain
experts, then drafts `business-rules.md` (a `BR-NN` decision table: condition → outcome → source →
**approver**) and `golden-scenarios.md` (`SCEN-NN`: input → expected behaviour). Each `BR-NN`
becomes an acceptance check on the spec that implements it; each `SCEN-NN` seeds the golden set at
`/sprd-evals`.

> **HITL GATE:** Each rule's outcome is confirmed by its named approver. A rule whose outcome the
> policy leaves silent or contradictory is a `DL-NN` decision-log item with an owner and a
> two-business-day clock, and the rule carries a *pending* marker until it closes — the analyst
> never guesses an outcome.

Discipline sign-offs are recorded at the phase advance beside the phase's own signature
(`/sprd-next` captures them as `Discipline:Section:Name`).

### Step 4: Stakeholder Review
Walk through with stakeholder before advancing:
- Verify P0 completeness — nothing missing that blocks core value
- Confirm P3 items are genuinely deferred
- Resolve contradictions explicitly
- **NFR threshold validation:** For each numeric NFR, confirm the measurement basis is recorded. For any threshold tagged `[aspirational]`, agree on the Build-loop measurement method *now* — who will measure it, how, and what happens if the measured value exceeds the target. Do not leave this for the Build loop to figure out.

### Step 5: Phase Handoff
Document the architectural implications of NFRs — these drive Phase 2 design decisions.

### Step 6: Generate Visual Report

Generate an interactive HTML visual report at `.sdlc/reports/01-requirements-visual.html` using the `/visual-explainer` skill (or equivalent HTML generation). This report is the stakeholder review artifact.

**Required visualizations for Phase 1 (Requirements):**
- Requirements summary by domain and priority (stacked bar or table with badges)
- Traceability matrix (requirements → Phase 0 personas)
- Epic overview cards with acceptance criteria count
- NFR measurement basis breakdown (measured vs aspirational)

See the Visual Report Protocol in `SKILL.md` for rendering standards and fallback behavior.

### Step 7: Generate Phase Report
Run `/sprd-gate` to validate exit criteria and automatically generate the phase HTML report at `.sdlc/reports/01-requirements-report.html`. Share this report with stakeholders for review before requesting sign-off. The report includes artifact inventory and gate status.

## Artifact Specifications

### `requirements.md` (REQUIRED)
Must contain ALL of:
- **Summary table** — requirement count by priority and domain
- **Functional requirements** — table format: ID | Requirement | Priority | Domain | Source | Source Document(s)
- **Business rules** — behavioral constraints separate from functional requirements
- **Traceability matrix** — every P0/P1 linked to a Phase 0 stakeholder pain

The "Source Document(s)" column is REQUIRED when document intake was performed in Phase 0. Use DOC-NNN references (e.g., `DOC-003:Section 4.2`). Omit this column when no document intake was performed.

### `non-functional-requirements.md` (REQUIRED)
Must contain ALL of:
- Performance, security, scalability, reliability, maintainability sections
- Each NFR as a table row: ID | Requirement | Metric | Test Method | Priority | Measurement Basis
- No vague NFRs — every metric must be measurable and testable
- **Measurement Basis column is mandatory for every numeric threshold.** Valid values: `Measured: [source]`, `Industry standard: [reference]`, `Contractual: [document]`, `[aspirational — validate in the Build loop]`

### `epics.md` (REQUIRED)
Must contain ALL of:
- Epics for every P0 and P1 requirement
- As a / I want / So that format
- Given/When/Then acceptance criteria (2+ scenarios per epic)
- Epic ID linked to requirement ID

### `phase2-handoff.md` (REQUIRED)
Must contain ALL of:
- Requirements summary (counts by priority, key themes)
- Architectural implications from NFRs (what design options this opens/closes)
- Key decisions made and rationale
- **What Design Must Address** — the `AQ-NN` list (see below). This is not optional prose: it is
  the input Phase 2's Step 0 gate reads.
- Open questions Phase 2 must resolve (product/scope questions that are NOT architectural — an
  architectural one belongs above, with an `AQ-NN`)
- Risks and ambiguities to watch
- Recommended design starting point

#### The `What Design Must Address` section

Phase 2 opens with a blocking human gate that extracts every **AQ-NN** (Architectural Question)
from this section and puts 2–3 concrete options to the human for each. The answers become the
ADRs — the signed, this-is-why records the rest of the engagement rests on.

If this section is missing or thin, that gate has no defined input and Claude improvises the
architectural questions. The ADRs then trace back to identifiers no one ever assigned. Write it.

Format — one line per question, numbered sequentially from `AQ-01`:

```markdown
## What Design Must Address

- **AQ-01:** Does the claims intake API need idempotency, or can duplicates be reconciled
  downstream? *(Driven by: REQ-014, NFR-003)*
- **AQ-02:** Is the policyholder record the system of record, or a cache of the carrier's?
  *(Driven by: REQ-021)*
```

Rules:
- **One architectural question per `AQ-NN`.** If answering it needs two decisions, it is two.
- **It is architectural if the answer changes the shape of the system** — a component boundary, a
  data flow, a technology choice, a consistency or failure model. If it only changes what a screen
  says, it is a product question and belongs under "Open questions" instead.
- **Cite what drove it.** Every AQ names the REQ/NFR ids that raised it, so Phase 2 can weigh the
  options against real constraints rather than taste.
- **Do not answer them here.** Phase 1 states the question; Phase 2's human gate decides it. An
  AQ that arrives pre-answered has skipped the gate that exists to get a human's name on it.

### `decision-log.md` (REQUIRED — the approver checks it, the gate cannot)

Every unmade product decision this phase surfaced and could not answer: numbered, owned by a named
person, and aged on the agreed clock (two business days by default).

> **Location:** this file lives at `.sdlc/decision-log.md`, **not** in this phase's artifact
> directory. It is phase-spanning — a decision opens here in Requirements and closes in a later
> phase in the same file. `scripts/track_decisions.py` reads it and `/sprd-status` surfaces
> anything past its clock. Because it sits outside `.sdlc/artifacts/01-requirements/`, the exit
> gate cannot check it mechanically, so the approver is asked about it at sign-off instead.

The Definition of Ready depends on this file. A spec cannot enter the Build loop with an open
decision belonging to its story, because the agent will otherwise pick one — silently, and
plausibly. "Fail open or fail closed?" is not a detail an agent should decide on a Tuesday.

Must contain, per entry:
- **`DL-NN`** — a stable id, referenced by the specs that are blocked on it
- **The decision** — stated as a question with the options, not as a topic
- **Owner** — a named human who can actually answer it, not a role
- **Opened** and **due** — the clock, so an unanswered decision becomes visible rather than old
- **The answer, when it comes**, with who gave it and when

At the gate the log is either empty or fully owned. An entry with no owner is the failure mode
this file exists to prevent.

**Do not confuse it with a spec's own `## Decision List` section**, which captures the silent
decisions *inside one spec* and is enforced per-spec by `check_spec.py` at Definition of Ready.
Phase-scoped versus spec-scoped: a `DL-NN` logged here can later seed a spec's Decision List when
that story is specced. They do not overlap, and neither replaces the other.

> **HITL GATE:** Claude drafts the questions and never the answers. Put each open decision to the
> named owner using `AskUserQuestion`, and record what they say. Do not infer an answer from the
> requirements, and do not let an entry stand with an unnamed owner.

### `scope-out-record.md` (OPTIONAL)

The explicit not-in-v1 list, and the confirmation that the sponsor has seen it.

Everything cut is remembered by somebody as merely deferred. This is the record that the cut was
visible at the time — the difference between a scope decision and a later surprise.

Must contain: each excluded item, why, whether it is deferred or dropped, and the date the sponsor
saw the list.

> **Optional by design.** Its absence does not by itself mean the phase went badly, so the gate
> does not block on it — but the approver is asked about it at sign-off. Write it when the work
> happens; a receipt written later from memory is worth less than no receipt at all.

### `adversarial-review-record.md` (OPTIONAL)

What fresh reviewers found when they attacked the requirements from the product, quality and
security angles — reviewers who did not write the draft.

Must contain: who reviewed, from which angle, and every catch with what changed as a result. A
review that found nothing is a finding too, and worth recording as one.

> **Optional by design.** Its absence does not by itself mean the phase went badly, so the gate
> does not block on it — but the approver is asked about it at sign-off. Write it when the work
> happens; a receipt written later from memory is worth less than no receipt at all.

### `feature-brief.md` (OPTIONAL — conditional, `/sprd-feature`)

One epic decomposed into features and specs. Must contain: the channels × personas narrative; a
decomposition table whose rows carry channel and persona (channel-agnostic rows marked `—`); the
proposed risk tier per row; and the product choices left open as `DL-NN` references.

> **Conditional by design.** Required when its trigger applies; absent otherwise, and the phase
> report says so. The gate does not block on it — the approver is asked at sign-off whether the
> trigger applied and, if it did, whether the artifact exists and its owner signed.

### `business-rules.md` (OPTIONAL — conditional, `/sprd-rules`)

The `BR-NN` decision table. Must contain, per rule: condition, outcome, the source policy it cites,
and a named approver. An undecided outcome is marked *pending* and references its `DL-NN`.

> **Conditional by design.** Required when its trigger applies; absent otherwise, and the phase
> report says so. The gate does not block on it — the approver is asked at sign-off whether the
> trigger applied and, if it did, whether the artifact exists and its owner signed.

### `golden-scenarios.md` (OPTIONAL — conditional, `/sprd-rules`)

The `SCEN-NN` table: input → expected behaviour, including the tricky and ambiguous cases. Seeds the
golden set for any LLM-powered spec (`/sprd-evals`) and the acceptance checks for the rest.

> **Conditional by design.** Required when its trigger applies; absent otherwise, and the phase
> report says so. The gate does not block on it — the approver is asked at sign-off whether the
> trigger applied and, if it did, whether the artifact exists and its owner signed.

## Exit Criteria
- [ ] All P0 requirements documented with source traceability
- [ ] Every NFR quantified with a measurable metric
- [ ] Every numeric NFR threshold has a Measurement Basis entry (measured / industry standard / contractual / aspirational)
- [ ] Every `[aspirational]` NFR has an agreed Build-loop measurement method documented
- [ ] Epics exist for all P0 and P1 requirements
- [ ] Each epic has happy path AND at least one error scenario
- [ ] Stakeholder reviewed and approved (manual gate)
- [ ] No unresolved P0 conflicts or ambiguities
- [ ] `phase2-handoff.md` has a **What Design Must Address** section, and every architectural
      implication recorded above appears there as a numbered `AQ-NN` — Phase 2's opening gate
      reads this list and has no other input
- [ ] If document intake was performed: every P0 requirement sourced from an external document has a DOC-NNN reference in the Source Document(s) column
- [ ] *(conditional)* Where an epic spans surfaces or personas: `feature-brief.md` exists, every row
      confirmed by a named human, one channel per spec
- [ ] *(conditional)* Where the feature encodes policy: every `BR-NN` has a named approver and either
      a signed outcome or a `DL-NN` with an owner and a clock; discipline sign-offs recorded at the
      advance

## HTML Report
The phase report is generated automatically when you run `/sprd-gate` or `/sprd-next`. It is written to `.sdlc/reports/01-requirements-report.html` and is fully self-contained — share it with stakeholders as the review artifact for the manual sign-off gate.

To regenerate at any time: `/sprd-phase-report`

## Guidance
- Requirements describe WHAT, not HOW. "The system SHALL use PostgreSQL" is a design decision, not a requirement.
- If you can't write an acceptance test for a requirement, it isn't specific enough.
- Contradictions between stakeholders are normal — surface them explicitly, don't silently pick one.
- P3 items should be documented, not ignored — they become Phase 2 scope inputs.

## Coaching Prompts

When operating in coaching mode (`/sprd-coach`) for this phase:

### Opening (no artifacts yet)
- "Who are the end users? Walk me through a typical day in their life."
- "What are the absolute must-have features vs. nice-to-haves?"
- "What are the non-functional requirements — performance, security, compliance?"
- "How will we know this project succeeded? What's the measurable outcome?"

### Progress Check (some artifacts exist)
- "Your requirements cover functional needs well. Have you considered [gap from NFR checklist]?"
- "These acceptance criteria need to be measurable. How would you test [criterion]?"

### Ready Check (all artifacts present)
- "Requirements are looking complete. Any features you're unsure about including?"
- "Are the priority labels (P0-P3) accurate? Would stakeholders agree with the ranking?"
