# Templates and Artifacts Reference

Comprehensive reference for the Shepherd template system -- the structured artifact
definitions that drive every phase of the SDLC lifecycle.

---

## Table of Contents

1. [Template System Overview](#1-template-system-overview)
2. [Directory Structure](#2-directory-structure)
3. [Phase 0: Discovery Artifacts](#3-phase-0-discovery-artifacts)
4. [Phase 1: Requirements Artifacts](#4-phase-1-requirements-artifacts)
5. [Phase 2: Design Artifacts](#5-phase-2-design-artifacts)
6. [Phase 3: Foundation Artifacts](#6-phase-3-foundation-artifacts)
7. [Build Loop Artifacts](#7-build-loop-artifacts)
8. [Later Phase Artifacts (Documentation, Deployment, Monitoring, Close)](#8-later-phase-artifacts-documentation-deployment-monitoring-close)
9. [Handoff Document Protocol](#9-handoff-document-protocol)
10. [Artifact Lifecycle](#10-artifact-lifecycle)
11. [Cross-References](#11-cross-references)

---

## 1. Template System Overview

Templates define the required structure and sections for every SDLC artifact. They are the
contract between phase work and gate validation -- a template declares what must exist, and the
gate system checks that it does.

### Core Principles

- **Templates are blueprints, not content.** They contain placeholder markers (`[brackets]`,
  `TODO`, `TBD`) that must be replaced with real project-specific content during phase work, and
  `<!-- REQUIRED: ... -->` comments that must be **deleted** once the section they mark is written.
- **Stored in the plugin directory.** Templates live under `templates/` inside the
  Shepherd plugin repository, not in target projects.
- **Copied at initialization.** When `/sprd-setup` runs, templates are copied to the target
  project's `.sdlc/artifacts/` directory, organized by phase.
- **Gate validation depends on templates.** Gate 1 (Existence) checks that every required
  artifact file exists. Gate 2 (Completeness) fails the artifact if it still contains any of
  exactly six strings: `TODO`, `TBD`, `${`, `PLACEHOLDER`, `[INSERT`, or `<!-- REQUIRED:`
  (`check_gates.py`, `PLACEHOLDER_MARKERS`).

  **Know what this does *not* catch.** Ordinary bracket prose — `[Describe the situation]`,
  `[Project Name]` — is **not** detected, because templates legitimately use `- [ ]` checkboxes
  and `[text](links)` and a general bracket rule would fail every artifact that has either. So a
  carelessly half-filled artifact can pass Gate 2. The `<!-- REQUIRED: -->` comments are what
  carry the real completeness contract: each one names a section that must be written, and
  deleting it is the author's assertion that it was. Gate 2 is a tripwire for an untouched
  template, not a proofreader.
- **Phase-specific organization.** Each phase has its own template subdirectory, named by its
  phase slug (`00-discovery`, `03-foundation`, `build`, `close`, ...), containing the artifacts
  required for that phase.

### Template Types

| Type | Description | Example |
|------|-------------|---------|
| **Markdown artifacts** | Structured documents with sections, tables, and placeholder content | `constitution.md`, `requirements.md` |
| **JSON tracking files** | Machine-readable state for session continuity (legacy; nothing in the plugin reads it since 1.6.0) | `session-handoff.json` |
| **Sprint records** | Sprint commitment window written to `.sdlc/sprints/SNN.md` by `sprint.py` | `sprint.md` |
| **YAML state** | Project state machine definition | `state-init.yaml` |
| **Handoff documents** | Phase transition records with open questions and risk summaries | `phase1-handoff.md`, `phase2-handoff.md`, `phase3-handoff.md`, `build-handoff.md`, `phase7-handoff.md`, `phase8-handoff.md`, `phase9-handoff.md`, `close-handoff.md` (the chain jumps 3 → `build-handoff` → 7 — there is no phase4/5/6-handoff) |

### Root-Level Quick-Start Templates

In addition to the phase-organized templates, six root-level files provide simplified versions
for rapid project bootstrapping:

| File | Purpose |
|------|---------|
| `state-init.yaml` | Initial state machine (used by all projects) |
| `constitution.md` | Simplified constitution template |
| `design-doc.md` | Simplified design document template |
| `requirements.md` | Simplified requirements template |
| `test-plan.md` | Simplified test plan template |
| `release-checklist.md` | Simplified release checklist template |

These root-level templates are shorter, less prescriptive versions of their phase-specific
counterparts. The phase-specific versions under `phases/` are the authoritative templates used
by the full SDLC workflow.

### Template Shapes (optional, machine-readable)

A template written as prose has no reliable machine structure — a heading someone renamed, or a
bold label swapped for a different word, and a tool trying to read it either guesses or breaks
something. Spec 0007 adds an optional **shape** file beside a template: `<name>.shape.yaml`,
documented in full at `templates/_shape-schema.yaml`. A shape declares a template's `## `
sections in order and, within them, the fields worth exposing to a form — each field's label,
its type (from a fixed list: `text`, `longtext`, `enum`, `boolean`, `number`, `date`, `checklist`,
`table`), whether it's required, and how the library finds its value (`inline`: same line as the
label; `labeled_block`: the label alone on its line, value below it; `section`: no label, the
field is the whole section body — used for a table, or where a `<!-- REQUIRED: -->` marker covers
an entire section rather than one bold-label line).

Two scripts do the work, and neither touches a template's own wording — a shape only *describes*
what's there:

- **`scripts/validate_shape.py <shape.yaml>`** checks a shape file itself: an unknown field type,
  a duplicate section heading, a repeating section with no numbering pattern — every error names
  the line it came from.
- **`scripts/document_shape.py`** is the read/write library. It never parses a document into a
  model and regenerates it — every recognized field is a byte span into the *original* text, and
  a write replaces only that span, so a document round-trips byte-for-byte when nothing changed,
  and a real edit changes only the bytes it targets. A document in which **no** section
  is recognized reads as **all free text with a warning**. One that merely lacks a **required**
  section still reads as sections, with the gap reported in `warnings` and shown to the reader:
  every section that is shown was found by its heading, so it is definitely the one it says it is.
  A section whose fields are all optional may be absent silently, since a shape now covers every section of its template, not just the gate-required
  ones. A `## ` section the shape doesn't declare — one a person added to their own document — is
  read as an editable section of its own (`custom: true`, one whole-body "Content" field) rather
  than raw text. A section is found by its heading as the shape writes it, by an `aliases:` entry,
  or by the same words with numbering, case and punctuation ignored, or with a qualifier after them
  (`3. Deployment steps`, `Deployment procedure (deploy-dev)`); none of these ever equates different
  words. `scripts/tests/test_shapes_cover_templates.py` fails when a template gains a
  section its shape doesn't declare. A repeating section (like `requirements.md`'s `### FR-001`, `###
  FR-002`, ...) allocates its next number by scanning the *whole* document, including free text,
  so a number already in use — even one never captured by the shape — is never reused. Every
  document created from a shaped template from now on carries a stamp
  (`<!-- template: <id> v<version> -->` right after the title); a document from before the stamp
  existed reads and writes as all free text, exactly like an unshaped one.

**Coverage today:** the 28 templates that already carry a `<!-- REQUIRED: -->` marker (the
existing completeness convention — see §1's Core Principles) are shaped; the other 36 are not,
and read/write exactly as before (a shape is additive — nothing about an unshaped template
changes). A repeating series identified by something other than a sequential number (API
Contracts' per-endpoint sections, keyed by method + path) or a bold label written without a colon
("**As a** ...") isn't modeled at field granularity — the enclosing section is still shaped as one
field, so presence/absence and round-trip fidelity hold; only the finer-grained per-field read is
out of scope for now.

**The advisory completeness check**, `scripts/check_document_completeness.py`, uses shapes to
report a required field that's absent or empty — including a required *section* deleted outright,
the gap the string-only Gate 2 scan (§1) cannot see, since a deleted section leaves no marker
behind to find. This is a **new, separate, additive check** — `check_gates.py` (the protected
core) is unchanged, and this check exits 0 always; whether it ever blocks a gate is a later,
deliberate decision.

---

## 2. Directory Structure

```
templates/
├── state-init.yaml                          # State machine init (${PROFILE_ID}, ${PROJECT_NAME}, ${CREATED_AT})
├── constitution.md                          # Root-level simplified constitution
├── design-doc.md                            # Root-level simplified design document
├── requirements.md                          # Root-level simplified requirements
├── test-plan.md                             # Root-level simplified test plan
├── release-checklist.md                     # Root-level simplified release checklist
└── phases/
    ├── 00-discovery/
    │   ├── constitution.md                  # Project identity and governing principles
    │   ├── problem-statement.md             # Why this project exists
    │   ├── success-criteria.md              # Measurable outcomes with Pass/Partial/Fail
    │   ├── constraints.md                   # Non-negotiable boundaries (tech/business/legal)
    │   ├── contradiction-list.md            # Detected conflicts across discovery inputs
    │   ├── document-registry.md             # Index of intake documents (DOC-NNN)
    │   ├── document-summary.md              # Per-document corpus summaries
    │   ├── question-list.md                 # Open discovery questions
    │   ├── workshop-brief.md                # Discovery workshop preparation brief
    │   └── phase1-handoff.md                # Handoff to Requirements phase
    ├── 01-requirements/
    │   ├── requirements.md                  # Functional requirements (FR-NNN format)
    │   ├── non-functional-requirements.md   # NFRs: performance, security, scalability
    │   ├── epics.md                         # Epic breakdown (EP-NNN format)
    │   ├── user-stories.md                  # User stories (US-NNN format)
    │   └── phase2-handoff.md                # Handoff to Design phase
    ├── 02-design/
    │   ├── design-doc.md                    # Architecture, components, data model, sequences
    │   ├── api-contracts.md                 # Endpoints, schemas, events, error catalog
    │   ├── adrs/
    │   │   └── ADR-template.md              # Architecture Decision Record template
    │   ├── adr-registry.md                  # Index of all ADRs with status tracking
    │   └── phase3-handoff.md                # Handoff to Foundation phase
    ├── 03-foundation/
    │   ├── foundation-report.md             # Walking-skeleton + harness/rails stand-up report
    │   ├── risk-tier-map.md                 # HIGH/MEDIUM/LOW risk tiers + registered security gates
    │   ├── cadence-plan.md                  # Cadence calendar, WIP cap, review-wait tripwire, sprint length, review-turnaround target
    │   ├── build-handoff.md                 # Ordered spec backlog; handoff into the Build loop
    │   └── section-plans/
    │       ├── SECTION-template.md          # Pure SDLC section plan format
    │       └── SECTION-template-deep-plan.md # Hybrid SDLC + /deep-plan format
    ├── build/
    │   ├── phase7-handoff.md                # Feature-complete declaration; exits into Documentation
    │   ├── build-summary.md                 # Rolling merged-work summary
    │   ├── sprint.md                        # Sprint record shape (.sdlc/sprints/SNN.md); filled by sprint.py new
    │   └── session-handoff.json             # Legacy session continuity state (not read by the hook)
    ├── 07-documentation/
    │   ├── api-docs.md                      # API documentation
    │   ├── RUNBOOK.md                       # Operational runbook
    │   └── phase8-handoff.md                # Handoff to Deployment phase
    ├── 08-deployment/
    │   ├── deployment-checklist.md          # Pre-deployment verification
    │   ├── release-notes.md                 # Version changelog
    │   ├── smoke-test-results.md            # Post-deployment smoke tests
    │   └── phase9-handoff.md                # Handoff to Monitoring phase
    ├── 09-monitoring/
    │   ├── alert-definitions.md             # Alert rules and thresholds
    │   ├── drill-record.md                  # Proof each critical alert fired and was answered
    │   ├── incident-response.md             # Incident classification and procedures
    │   ├── monitoring-config.md             # Dashboard and metrics configuration
    │   └── project-retrospective.md         # Final project retrospective
    └── close/
        ├── final-handoff-report.md          # Closing handoff to the client
        ├── harness-audit.md                 # Audit of the delivered harness
        ├── close-gate-evidence.md           # Evidence the client ran a real spec unassisted
        └── access-revocation-checklist.md   # Pod access teardown checklist
```

> Note: `close-handoff.md` (Monitoring → Close) lives under `09-monitoring/` as that phase's
> handoff artifact; the `close/` directory holds the terminal Close & Transfer deliverables.

---

## 3. Phase 0: Discovery Artifacts

Discovery establishes project identity, defines the problem, and sets boundaries. All four
artifacts plus the handoff document are required to pass the Phase 0 exit gate.

### constitution.md -- Project Identity Document

The constitution is the foundational document that defines what the project is and how decisions
are made. It is referenced throughout every subsequent phase.

**Required sections:**

| Section | Purpose | What Must Be Filled In |
|---------|---------|----------------------|
| **Project Identity** | Basic project metadata | Project name, profile ID, creation date |
| **Mission Statement** | Why this project exists in one paragraph | Problem being solved, who benefits, core value proposition |
| **Governing Principles** | Decision-making framework (minimum 3) | Each principle needs a name, statement, and "In Practice" example |
| **Decision Authority** | Who decides what | Authority matrix for architecture, scope, schedule, quality decisions |
| **Amendment Process** | How to change the constitution | Threshold for changes, approval process, version tracking |
| **Version History** | Change log | Version number, date, changes made, approver |

**Special field -- `project_type`:** During Phase 0, the constitution must declare a `project_type`
value of one of: `service`, `app`, `library`, `skill`, or `cli`. This value is written into
`state.yaml` and controls which profile-specific gates and artifact requirements apply in later
phases.

### problem-statement.md -- Why This Project Exists

Defines the problem in rigorous, measurable terms. This is not a solution proposal -- it
describes the current state and quantifies the pain.

**Required sections:**

| Section | Purpose | What Must Be Filled In |
|---------|---------|----------------------|
| **Executive Summary** | One-paragraph problem description | Non-technical summary accessible to any stakeholder |
| **Stakeholder Personas** | Who is affected | Name/role, their pain, impact severity, current workaround |
| **Current State: Process Flow** | How things work today | Description of current workflow or system behavior |
| **Current State: Metrics** | Quantified baseline | Current performance numbers that will be compared against success criteria |
| **Root Cause Analysis (Five Whys)** | Why the problem persists | Chain of causation from symptom to root cause |
| **Problem Scope** | Boundaries of the problem | What is in scope, what is explicitly out of scope |
| **Opportunity Statement** | What solving this enables | Future state description, projected improvement |

### success-criteria.md -- How We Know It Worked

Defines measurable outcomes with explicit thresholds for Pass, Partial success, and Fail. This
document is the accountability contract -- it prevents scope creep and goal-post shifting.

**Required sections:**

| Section | Purpose | What Must Be Filled In |
|---------|---------|----------------------|
| **Measurable Success Dimensions** (min. 3) | What we measure | Each dimension needs: what we measure, Pass/Partial/Fail thresholds with specific numbers, data collection method |
| **Non-Negotiable Requirements** | Hard fail conditions | Specific conditions that constitute absolute failure regardless of other metrics |
| **Time to Value** | When we expect results | Milestones with dates for when each dimension becomes measurable |
| **Success Owner** | Who is accountable | Named individual responsible for measuring and reporting results |

Each dimension uses a structured table:

```markdown
| Outcome | Threshold | How We'll Measure |
|---------|-----------|------------------|
| Pass    | [Specific number/condition] | [Measurement method] |
| Partial | [Specific number/condition] | [Measurement method] |
| Fail    | [Specific number/condition] | [Measurement method] |
```

"Better" is not a valid threshold. "20% faster" is.

### constraints.md -- Non-Negotiable Boundaries

Documents every constraint that limits the solution space, with rationale for each. An
undocumented constraint is a surprise waiting to happen.

**Required sections:**

| Section | Purpose | What Must Be Filled In |
|---------|---------|----------------------|
| **Constraint Register** (min. 3 entries) | Master list | Each constraint (C-NN) with type, rationale, solution impact, owner |
| **Technical Constraints: Must Use / Cannot Use** | Technology boundaries | Required and prohibited technologies with justification |
| **Technical Constraints: Integration Requirements** | External system dependencies | Systems that must be integrated, their APIs, SLAs |
| **Technical Constraints: Performance / Scale Envelope** | Performance boundaries | Throughput, latency, concurrency, and data volume limits |
| **Business Constraints: Timeline** | Schedule boundaries | Hard deadlines, milestone dates, external dependencies |
| **Business Constraints: Budget** | Cost boundaries | Financial constraints affecting technology choices |
| **Business Constraints: Team / Resource** | People boundaries | Available roles, FTEs, skill levels, availability windows |
| **Legal and Compliance Constraints** | Regulatory boundaries | Applicable regulations, data residency, audit requirements |
| **Assumptions** | What we take for granted | Stated assumptions with validation method and owner |
| **Constraint Change Protocol** | How constraints change | Process for requesting and approving constraint modifications |

**Constraint types:** Technical, Business, Legal/Compliance, Resource, Time.

### phase1-handoff.md -- Handoff to Requirements

Bridges Discovery to Requirements. See [Section 9: Handoff Document Protocol](#9-handoff-document-protocol)
for the standard format.

**Phase-specific content:**

- **Discovery Summary:** Compressed version of all four discovery artifacts
- **Decisions Made in Discovery:** Decision table (D-NN format) with rationale and approver
- **Open Questions Requiring Resolution:** Q-NN numbered items that Requirements MUST address
- **Personas to Interview:** Stakeholders with specific information gaps to close
- **Constraints to Translate into Requirements:** Which constraints become formal requirements
- **Known Risks Entering Requirements:** Risk table with descriptions and suggested mitigation
- **Artifacts Produced:** Checklist of all Discovery artifacts and their completion status
- **Exit Gate Status:** Checklist of gate conditions with approval signature

---

## 4. Phase 1: Requirements Artifacts

Requirements translates discovery insights into formal, traceable requirements that drive design
decisions.

### requirements.md -- Functional Requirements

**Required sections:**

| Section | Purpose | What Must Be Filled In |
|---------|---------|----------------------|
| **Overview** | Requirements scope summary | Total count, priority distribution, coverage statement |
| **Functional Requirements** (FR-NNN) | Individual requirements | Each FR needs: description, priority (P0/P1/P2), acceptance criteria, source (traceability to discovery) |
| **Requirement Traceability** | Links to discovery | Matrix mapping FRs to problem-statement sections and success criteria |
| **Prioritization Rationale** | Why priorities were set | Explanation of P0/P1/P2 classification methodology |
| **Requirements Review Notes** | Stakeholder feedback | Review date, attendees, decisions, changes made |

Each functional requirement follows this structure:
- **ID:** `FR-NNN`
- **Description:** What the system must do (unambiguous, single-requirement-statement)
- **Priority:** P0 (must ship) / P1 (should ship) / P2 (nice to have)
- **Acceptance Criteria:** Verifiable conditions in Given/When/Then or checklist format
- **Source:** Which discovery artifact or stakeholder this traces to

### non-functional-requirements.md -- Quality Attributes

**Required sections:**

| Section | Purpose | What Must Be Filled In |
|---------|---------|----------------------|
| **Performance** | Speed and throughput | Response time targets, throughput minimums, resource limits |
| **Reliability and Availability** | Uptime guarantees | SLA targets, MTTR, failover requirements, backup strategy |
| **Scalability** | Growth handling | Horizontal/vertical scaling strategy, load projections |
| **Security** | Protection requirements | Authentication, authorization, encryption, audit logging |
| **Maintainability** | Long-term health | Code standards, documentation requirements, dependency policy |
| **Compliance** | Regulatory requirements | Specific regulations, audit requirements, data handling rules |
| **NFR Acceptance Test Plan** | How NFRs are verified | Test method, tools, target values, and pass criteria for each NFR |

### epics.md -- Epic Breakdown

Groups related functionality into epics, prioritized by P0/P1/P2.

**Required sections:**

| Section | Purpose | What Must Be Filled In |
|---------|---------|----------------------|
| **Epic Map** | Visual overview | Table mapping epics to priorities, story counts, and target release (a sprint window is set later, at `/sprd-sprint slate`, never here) |
| **P0 Epics** (EP-NNN) | Must-ship functionality | Goal, user value, constituent stories (US-NNN refs), acceptance criteria, dependencies |
| **P1 Epics** | Should-ship functionality | Same structure as P0 |
| **P2 Epics** | Nice-to-have functionality | Same structure as P0 |
| **Epic Summary** | Aggregate statistics | Total epics, story counts per priority, estimated effort |

### user-stories.md -- User Stories

Individual user stories in standard format, linked to epics.

**Required sections:**

| Section | Purpose | What Must Be Filled In |
|---------|---------|----------------------|
| **Story Map** | Visual overview | Table mapping stories to epics, priorities, and effort estimates |
| **P0 Stories** (US-NNN) | Must-ship stories | As a [persona], I want [goal], so that [benefit]; acceptance criteria; epic reference |
| **P1 Stories** | Should-ship stories | Same structure as P0 |
| **P2 Stories** | Nice-to-have stories | Same structure as P0 |
| **Story Summary** | Aggregate statistics | Total stories, counts per priority, estimated total effort |

### phase2-handoff.md -- Handoff to Design

**Phase-specific content:**

- **Requirements Summary:** Total FRs, NFRs, epics, and stories with priority breakdown
- **Decisions Made in Requirements:** D-NN decision table
- **Architectural Questions Raised by Requirements:** Questions that only design can answer
- **NFRs That Directly Shape Architecture:** Which quality attributes constrain design choices
- **P0 Flows That Need System Diagrams:** User stories requiring sequence diagram treatment
- **Open Items from Requirements:** Unresolved questions carried forward
- **Artifacts Produced in Requirements:** Completion checklist

---

## 5. Phase 2: Design Artifacts

Design translates requirements into technical architecture, component design, and API contracts.

### design-doc.md -- Architecture and Design

The central design document covering system architecture, component design, and data model.

**Required sections:**

| Section | Purpose | What Must Be Filled In |
|---------|---------|----------------------|
| **Architecture Overview: System Context** | External view | How the system fits into its environment, external actors |
| **Architecture Overview: Architecture Diagram** | Visual structure | Mermaid diagram with components, boundaries, data flows |
| **Component Design** (per component) | Internal design | Purpose, responsibility, public API, dependencies, error handling |
| **Data Model: Core Entities** | Data structure | Entity definitions, relationships, cardinality |
| **Data Model: Data Flow** | Data movement | How data moves between components and storage |
| **Data Model: Storage Design** | Persistence strategy | Database choices, schema design, migration strategy |
| **Sequence Diagrams: P0 Flows** | Behavioral design | Mermaid sequence diagrams for every P0 user story |
| **Cross-Cutting Concerns** | Shared infrastructure | Authentication, authorization, error handling, observability |
| **Architecture Decision Records** | Decision index | Table linking to ADR files in `adrs/` directory |
| **Design Review Notes** | Stakeholder feedback | Review date, attendees, changes made |

### api-contracts.md -- API Contract Definitions

Formal API specifications including endpoints, schemas, events, and error handling.

**Required sections:**

| Section | Purpose | What Must Be Filled In |
|---------|---------|----------------------|
| **Overview** | API summary | Base URL, versioning scheme, authentication method, rate limiting |
| **Endpoints** (`[METHOD] /[path]`) | Each API endpoint | Path, method, description, auth requirements, request/response schemas with examples, error responses, rate limits |
| **Data Schemas** (`[EntityName]`) | Shared data types | Field name, type, required flag, constraints, description |
| **Events** (if applicable) | Async contracts | Event name, trigger, payload schema, consumers |
| **Error Catalog** | Standardized errors | Error code, HTTP status, description, resolution, example response body |
| **External APIs Consumed** | Third-party dependencies | API name, purpose, auth method, rate limits, fallback strategy |
| **Contract Versioning** | Change management | Versioning strategy, deprecation policy, breaking change process |

### adrs/ + ADR-template.md -- Architecture Decision Records

Each significant architectural decision is recorded in its own file using the ADR template.
Files are named `ADR-NNN.md` and stored in the `adrs/` directory.

**ADR template structure:**

| Section | Purpose | What Must Be Filled In |
|---------|---------|----------------------|
| **Header** | Metadata | ADR number, title (imperative present tense), date, status (Proposed/Accepted/Deprecated/Superseded) |
| **Context** | Why a decision is needed | Situation description, forces at play, constraints (2-4 sentences minimum) |
| **Decision** | What was decided | Clear, unambiguous statement of the decision |
| **Rationale** | Why this option won | Reasoning that led to this choice over alternatives |
| **Alternatives Considered** | What else was evaluated | Each alternative with pros/cons |
| **Consequences** | Impact of the decision | Positive outcomes, negative trade-offs, and risks |
| **Implementation Notes** | How to apply the decision | Concrete guidance for implementers |
| **Review Trigger** | When to reconsider | Conditions that should prompt revisiting this decision |

**ADR statuses:** Proposed, Accepted, Deprecated, Superseded (by ADR-NNN).

### adr-registry.md -- ADR Index

Tracks all ADRs across the project in a single lookup table.

**Sections:** Active ADRs, Superseded ADRs, Proposed (Under Review). Each entry records the ADR
number, title, date, and current status.

### phase3-handoff.md -- Handoff to Foundation

**Phase-specific content:**

- **Design Summary:** Architecture style, component count, key technology choices
- **Decisions Locked in Design:** D-NN table with ADR cross-references
- **Natural Section Boundaries:** How the design breaks into implementable sections
- **P0 Stories and Their Technical Requirements:** Story-to-component mapping with complexity
- **Integration Points Requiring Coordination:** Cross-section dependencies
- **Technical Risks for Foundation:** Risk table with recommended spikes
- **Open Design Questions:** AQ-NN items that Foundation should be aware of

---

## 6. Phase 3: Foundation Artifacts

Foundation is the hinge where documents stop and software starts. It builds the factory --
installs/adapts the harness, stands up the CI/CD rails, gates, and dev infrastructure -- and
deploys a thin "walking skeleton" end-to-end into the dev environment. Its required artifacts are
`foundation-report.md`, `risk-tier-map.md`, `cadence-plan.md`, and `build-handoff.md`. The
`section-plans/` sub-directory holds the per-change planning templates that the Build loop draws
from.

### foundation-report.md -- Walking Skeleton and Rails Report

Records that the factory is real: the harness is installed/adapted, the CI/CD pipeline and gates
are live, dev infrastructure is provisioned, and a thin end-to-end walking skeleton is deployed
into dev.

**Required sections:**

| Section | Purpose | What Must Be Filled In |
|---------|---------|----------------------|
| **Overview** | Foundation summary | What was stood up, where the walking skeleton is deployed |
| **Harness Setup** | The installed factory | Which harness/profile was installed or adapted, and how |
| **CI/CD Rails and Gates** | Pipeline state | Pipeline stages, the gates wired in, where they run |
| **Dev Infrastructure** | Provisioned environment | Environments, services, and access stood up for the build loop |
| **Walking Skeleton** | Thin end-to-end slice | The minimal end-to-end path proven deployed into dev |

### risk-tier-map.md -- Risk Tier Map

Tiers project risks and registers the security gates that guard the higher tiers.

**Required sections:**

| Section | Purpose | What Must Be Filled In |
|---------|---------|----------------------|
| **HIGH tier** | Highest-risk areas | Areas demanding the strictest checking, with rationale |
| **MEDIUM tier** | Moderate-risk areas | Areas with standard checking |
| **LOW tier** | Lowest-risk areas | Areas with lightweight checking |
| **Registered Security Gates** | Gate registry | Which security gates apply to which tier and where they fire |

### cadence-plan.md -- Cadence Plan

Sets the rhythm of the Build loop: when work happens, how much is in flight, and the tripwire
that flags stalled review.

**Required sections:**

| Section | Purpose | What Must Be Filled In |
|---------|---------|----------------------|
| **Cadence Calendar** | When work happens | The recurring rhythm of build/review beats |
| **WIP Cap** | Concurrency limit | Maximum changes allowed in flight at once |
| **Review-Wait Tripwire** | Stall detector | The threshold at which a change waiting on review raises a flag |
| **Sprint length** | Commitment window | Business days per sprint (default 10); `/sprd-sprint new` derives `end` from it |
| **Review-turnaround target** | Verdict clock | Per lane (Engineering, Data); the sprint agenda flags verdicts waiting beyond it; `[not set]` is an allowed final value and reads "no target set" |
| **Cross-functional review** (Mon/Wed/Fri) | Sprint refinement slot | Slate readiness, pending verdicts, overdue decisions -- `/sprd-refine` renders the agenda |

### build-handoff.md -- Handoff into the Build Loop

The ordered spec backlog that the Build loop consumes -- the bridge from Foundation into
continuous build.

**Required sections:**

| Section | Purpose | What Must Be Filled In |
|---------|---------|----------------------|
| **Ordered Spec Backlog** | The build queue | Specs in implementation order, with dependencies |
| **Build Start Conditions** | Readiness checklist | Rails live, gates wired, walking skeleton deployed, owners assigned |
| **Constraints** | Build-loop ground rules | Coding standards, branching strategy, review requirements |
| **Key Risks Entering Build** | Carried-forward risks | Risks with active mitigations from the risk-tier map |

### section-plans/ -- Per-Change Section Plans

Section plans are the atomic unit of build work. They live under `03-foundation/section-plans/`,
and the Build loop draws from them per change. Each section gets its own file (`SECTION-NNN.md`)
based on one of two templates.

#### SECTION-template.md -- Pure SDLC Format

The standard section plan template with structured fields for gate validation and traceability.

**Required fields:**

| Field | Purpose | What Must Be Filled In |
|-------|---------|----------------------|
| **Header metadata** | Section identity | Owner, sprint window (`[SNN]`, blank until slated at `/sprd-sprint slate`), estimated effort (S/M/L/XL), status |
| **Goal** | What this section delivers | One sentence describing the capability that exists when complete |
| **Epics / Stories Covered** | Traceability | List of EP-NNN and US-NNN identifiers this section implements |
| **Entry Criteria** | Prerequisites | Conditions that must be true before work begins |
| **Exit Criteria** | Definition of done | Specific, verifiable conditions (minimum 2) that mark completion |
| **Dependencies** | Ordering constraints | Other sections or external systems required |
| **Implementation Guidance** | Developer instructions | Key algorithms, patterns, pitfalls, and approach guidance |
| **Interfaces** | What this section exposes | Table of functions/APIs/events with type (internal/external) and contract |
| **Test Strategy** | Quality requirements | Coverage target by test type (unit/integration/e2e), key scenarios |
| **Risk** | Section-specific risks | Risks and mitigations specific to this section |
| **Verification Criteria** | How to verify each exit criterion | Pass condition, verification method, who verifies |
| **Evaluator Contract** | Grading rubric for section evaluator agent | Evaluation scope, grading rubric (5 dimensions), fail conditions (blocking), warn conditions (non-blocking) |

#### SECTION-template-deep-plan.md -- Hybrid SDLC + /deep-plan Format

A converged template that combines SDLC structured fields with full /deep-plan implementation
prose. This is the recommended template when using the `/deep-plan` skill integration.

**Differences from the pure template:**

| Aspect | Pure SDLC | Hybrid SDLC + /deep-plan |
|--------|-----------|--------------------------|
| **Implementation Guidance** | Brief notes and pitfalls | Full /deep-plan prose: architecture decisions, code patterns, directory structure, function signatures, step-by-step instructions |
| **Test Strategy** | Coverage targets and key scenarios | Coverage targets plus a **TDD Test Stubs** subsection carrying the relevant slice of `claude-plan-tdd.md` |
| **Self-containment** | May reference external docs | Fully self-contained -- a developer can read only this section and start implementing |
| **deep-implement compatibility** | Standard implementation | `/deep-implement` reads the Implementation Guidance section as its primary input |

The Implementation Guidance section in the hybrid template is designed to carry the full
`/deep-plan` prose content verbatim. The structured SDLC fields (Goal, Epics, Entry/Exit
Criteria, Dependencies, Interfaces) wrap the section for gate validation and traceability,
while the prose carries the actual implementation instructions.

**Evaluator Contract (both templates):**

Both section plan templates include an Evaluator Contract that defines the grading rubric the
section evaluator agent uses after implementation completes:

1. **Functional completeness** -- all exit criteria pass conditions met
2. **Test quality** -- coverage target met, edge cases covered
3. **Interface compliance** -- exposed interfaces match the Interfaces table
4. **Code quality** -- functions within profile size limits, no deep nesting, immutability patterns
5. **Deviation accountability** -- any deviation from Implementation Guidance is documented with rationale

**Fail conditions (blocking):** exit criterion not met, coverage below target, interface contract
broken without documented ADR.

**Warn conditions (non-blocking):** code style deviations, missing edge case tests outside
critical path.

---

## 7. Build Loop Artifacts

The Build loop is the continuous middle of the SDLC. It replaces the old batch
Implementation/Quality/Testing phases: every change runs three beats -- **Intent** (decide and
write a spec), **Delegate** (bound and build from an approved plan), and **Discern** (prove the
change against its spec, by someone other than the author, then merge). There is no artifact exit
gate -- checking happens per change inside the loop, and a human declares the backlog
feature-complete to leave.

The loop's durable per-change record is `specs/` (the spec files in the repo). Under the `build/`
template directory it tracks rolling state in `build-summary.md`, ships the sprint-record shape
(`sprint.md`, optional), keeps the legacy `session-handoff.json`, and emits `phase7-handoff.md`
when the human declares the work feature-complete.

### specs/ -- Per-Change Specifications

Each change gets a spec file in the repo (`specs/NNNN-name.md`), written during the Intent beat.
The spec is the contract the change is built against and the artifact the Discern beat proves
against. Specs are the Build loop's durable per-change record; they live in the repository, not
under the template tree.

### build-summary.md -- Rolling Merged-Work Summary

A continuously updated summary of work merged through the Build loop -- what has shipped, what is
in flight, and the current state of the backlog. It is the human-readable counterpart to the
spec backlog described below.

### Spec Backlog -- Progress Derived from Spec Frontmatter

The Build loop tracks progress from the spec files themselves, not from a separate JSON tracker.
Each spec (`specs/NNNN-name.md`, in version control) carries a `status` in its frontmatter, and
`scripts/track_specs.py` derives the backlog state by scanning those files. The spec is the unit
of work: one spec = one branch = one PR.

**Spec frontmatter (relevant fields):**

```yaml
---
spec: "0007"
name: "Authentication Service"
status: in-flight     # draft -> ready -> in-flight -> merged, or deferred (side branch)
risk: HIGH            # HIGH / MEDIUM / LOW
---
```

**`track_specs.py` reports:**

| Output | Description |
|--------|-------------|
| Total specs | Count of `specs/*.md` with parseable frontmatter |
| Status breakdown | Counts by `status` (`draft`, `ready`, `in-flight`, `merged`; `deferred` gets its own line once any spec uses it — never pre-seeded at zero) |
| Risk breakdown | Counts by `risk` tier (`HIGH`, `MEDIUM`, `LOW`) |
| In-flight list | The specs currently on a branch awaiting merge |
| WIP-cap breach | With `--wip-cap N`, flags (and exits non-zero) when in-flight specs exceed `N` |

It runs standalone (`--repo <path>`) or in-workflow (`--state .sdlc/state.yaml`). See
[specs/](#specs--per-change-specifications) above for the spec format. With `--sprint SNN` it
reports only that sprint's slate, and its summary carries a `by_sprint` partition (each `SNN`,
`unassigned`, `pre-sprint` for specs merged before the sprint layer existed).

**Optional sprint keys.** A spec slated by `/sprd-sprint` carries five more frontmatter keys --
`sprint`, `next_owner`, `eng_review`, `data_review`, `depends_on` -- written only by
`scripts/sprint.py` (values are enumerations, names and spec ids; `""` by default). `status`
is not one of them and stays hand-moved. `templates/phases/build/spec.md` ships the keys blank;
a spec without them behaves exactly as before.

### sprint.md -- Sprint Record

Shape of `.sdlc/sprints/SNN.md`, the optional two-week commitment window over the spec backlog
(`/sprd-sprint`). `sprint.py new` fills the frontmatter and the H1; `slate`, `unslate`, `ready` and `close`
render the `## Slate` table and `close` writes `## Close` -- never hand-edit them. `status` is
read-only: it prints the live view (`/sprd-sprint status`) and touches no file.

| Field | Purpose | Values |
|-------|---------|--------|
| `sprint` | Human-typed id | `S07` (`^S\d{2,}$`) |
| `goal` | One outcome-shaped sentence | prose |
| `start` / `end` | The window | ISO dates; `end` defaults to the last business day of a 10-business-day window that starts on `start` (start is day 1: Mon 2026-09-28 -> Fri 2026-10-09) |
| `state` | Lifecycle | `planning` -> `ready` -> `closed`, forward only |
| `target` | How many specs to slate | an integer count, never a size |
| `mix` | Slate shape by risk tier | `"HIGH:1,MEDIUM:2,LOW:3"`; sum <= `target`; a breach warns |
| `board_ref` | Manual board mapping | e.g. `ADO Iteration 6`; nothing reads it |
| `readied_by` / `closed_by` | Named humans | set at `ready` / `close` |
| `## Slate` | Rendered from spec frontmatter by `slate` / `unslate` / `ready` / `close` | spec, name, risk, type, status, DoR, eng, data, next owner |
| `## Close` | Written at `close` | spec, outcome (kept / carried -> SNN / dropped), by, reason |

Companion outputs: the append-only ledger `.sdlc/metrics/sprint-log.jsonl` and the self-contained
pages `.sdlc/reports/sprint-SNN-planning.html` (at `ready`, or on demand) and
`sprint-SNN-review.html` (at `close`). See `references/sprint-model.md`.

### session-handoff.json -- Session Continuity State

Legacy JSON file for Build-loop continuity across Claude Code sessions. An engagement may still
keep it for its own notes, but **nothing in the plugin reads it** since 1.6.0 -- the session-start
hook's summary of it was retired (it was a section-plan progress model competing with the spec
backlog), and the retired `current_sprint` field is gone: the active sprint lives in
`.sdlc/sprints/SNN.md` and the hook prints it as `[SHEPHERD-SPRINT]`.

**Schema version:** `session-handoff-v1`

```json
{
  "$schema": "session-handoff-v1",
  "phase": "build",
  "last_updated": null,
  "session_number": 1,
  "overall_status": "in_progress",
  "sections": [
    {
      "id": "SECTION-001",
      "name": "",
      "status": "not_started",
      "agent": null,
      "started_at": null,
      "completed_at": null,
      "evaluator_result": null,
      "notes": ""
    }
  ],
  "completed_this_session": [],
  "in_progress": [],
  "blocked": [],
  "next_actions": [
    {
      "action": "",
      "section": "",
      "priority": "P0",
      "context": ""
    }
  ],
  "blockers": [],
  "decisions_this_session": [],
  "deviations_this_session": [],
  "context_for_next_session": ""
}
```

**Key arrays:**

| Array | Purpose |
|-------|---------|
| `completed_this_session` | Section IDs finished in the current session |
| `in_progress` | Section IDs actively being worked on |
| `blocked` | Section IDs that cannot proceed |
| `next_actions` | Prioritized action items for the next session (P0/P1/P2) |
| `blockers` | Description of what is blocking progress |
| `decisions_this_session` | Implementation decisions made this session |
| `deviations_this_session` | Deviations from design documented this session |

The `context_for_next_session` field is a free-text summary that provides the next session with
everything it needs to continue work without re-reading all artifacts.

### phase7-handoff.md -- Exits the Build Loop into Documentation

The Build loop has no batch exit gate. It ends when a human declares the backlog
feature-complete; that declaration is `phase7-handoff.md`, which carries the work directly into
Documentation.

**Phase-specific content:**

- **What Was Built:** The capabilities that now exist, mapped to the specs that delivered them
- **System State:** Current state of the deployed system and its build/test status
- **Open Questions:** Q-NN items the Documentation phase must address
- **Deferred Items:** Work consciously left out, with justification
- **Documentation Focus:** Areas Documentation should prioritize for the cold-use verification

---

## 8. Later Phase Artifacts (Documentation, Deployment, Monitoring, Close)

### Phase 7: Documentation (2 artifacts + handoff)

| Artifact | Purpose |
|----------|---------|
| `api-docs.md` | API documentation for consumers |
| `RUNBOOK.md` | Operational runbook for deployment and maintenance |
| `phase8-handoff.md` | Handoff to Deployment with documentation summary |

### Phase 8: Deployment (3 artifacts + handoff)

| Artifact | Purpose |
|----------|---------|
| `deployment-checklist.md` | Pre-deployment verification steps |
| `release-notes.md` | Version changelog with features, fixes, and breaking changes |
| `smoke-test-results.md` | Post-deployment smoke test results per environment |
| `phase9-handoff.md` | Handoff to Monitoring with deployment summary |

### Phase 9: Monitoring (5 artifacts + handoff)

| Artifact | Purpose |
|----------|---------|
| `alert-definitions.md` | Alert rules, thresholds, and notification routing |
| `drill-record.md` | Per critical alert: trigger, detection time, routing, responder, outcome — the proof the pager works |
| `incident-response.md` | Incident classification levels and response procedures |
| `monitoring-config.md` | Dashboard inventory and metrics configuration |
| `project-retrospective.md` | Final project retrospective covering the entire SDLC cycle |
| `close-handoff.md` | Handoff to Close & Transfer with monitoring baseline summary |

### Phase C: Close & Transfer (4 artifacts, terminal)

The terminal phase. It proves the client can run everything without the pod -- shadow-flip,
harness audit, the close gate (the client runs one real spec end-to-end unassisted), and access
revocation.

| Artifact | Purpose |
|----------|---------|
| `final-handoff-report.md` | The closing handoff report to the client |
| `harness-audit.md` | Audit of the delivered harness against the delivery standard |
| `close-gate-evidence.md` | Evidence the client ran a real spec end-to-end unassisted |
| `access-revocation-checklist.md` | Pod access teardown checklist |

Phase 9 hands off to Phase C (Close & Transfer) via `close-handoff.md`. Phase C is terminal;
`final-handoff-report.md` is the project's closing document.

---

## 9. Handoff Document Protocol

Every phase transition produces a handoff document. These documents follow a standard format
and serve as the primary communication channel between phases.

### Standard Handoff Structure

All handoff documents follow this structure. The chain is `phase1-handoff.md`,
`phase2-handoff.md`, `phase3-handoff.md`, `build-handoff.md`, `phase7-handoff.md`,
`phase8-handoff.md`, `phase9-handoff.md`, `close-handoff.md` -- note the 3 → `build-handoff` → 7
jump, since the Build loop replaces the old phase 4/5/6 (there is no phase4/5/6-handoff):

1. **Phase Summary** -- compressed summary of work done in the completing phase
2. **Decisions Made** -- D-NN formatted decision table with rationale and approver
3. **What Next Phase Must Address** -- specific items the receiving phase is responsible for
4. **Open Questions** -- Q-NN or AQ-NN numbered items requiring resolution
5. **Known Risks** -- Risk table with descriptions and suggested mitigations
6. **Artifacts Produced** -- Checklist of all artifacts from the completing phase
7. **Exit Gate Status** -- Checklist of gate conditions with approval signature

### Open Question Protocol (Q-NN Format)

Open questions use a numbered format (Q-01, Q-02, ... or AQ-01, AQ-02 for architectural
questions) and are tracked across phase boundaries.

**Critical behavior:** The `/sprd-next` command checks handoff documents for unresolved Q-NN
items. When entering a new phase, the SDLC system:

1. Reads the handoff document that was just produced
2. Extracts ALL Q-NN and AQ-NN items from "Open Questions", "What X Must Address", or similar headings
3. Displays them in a prominent block that cannot be overlooked
4. Requires that the receiving phase address each item before its own exit gate

Unresolved Q-NN items from a previous phase are a gate failure condition. They must be either
answered, explicitly deferred with justification, or determined to be no longer applicable.

### Decision Format (D-NN)

Decisions are tracked in tables throughout handoff documents:

```markdown
| Decision | What Was Decided | Rationale | Who Approved |
|----------|-----------------|-----------|-------------|
| D-01     | [Decision text] | [Why]     | [Name]      |
```

Decisions made in earlier phases are binding on later phases unless formally overridden
through an ADR or constitution amendment.

---

## 10. Artifact Lifecycle

Every artifact follows a predictable lifecycle from template to validated deliverable.

### Lifecycle Stages

```
1. TEMPLATE          Templates exist in plugin's templates/ directory (references)
       |
2. AUTHORED          Phase work creates the artifact in .sdlc/artifacts/{phase}/,
                     using the template as a reference (init_project does NOT seed it)
       |
3. IN PROGRESS       Phase work replaces placeholders with real content
       |
4. GATE 1: EXISTS    Gate checks that the artifact file exists at expected path
       |
5. GATE 2: COMPLETE  Gate scans for unfilled placeholders ([brackets], TODO, TBD)
       |
6. GATE 6: QUALITY   Gate evaluates content quality (profile-specific criteria)
       |
7. RECORDED          Artifact path added to state.yaml phase artifacts list
```

### Gate Interaction Details

**Gate 1 -- Existence Check:** Verifies that every artifact required by the current phase's
profile configuration exists as a file at the expected path under `.sdlc/artifacts/`. A missing
file is a hard gate failure.

**Gate 2 -- Completeness Check:** Scans artifact content for placeholder patterns:
- `[bracket text]` -- unfilled template placeholders
- `TODO` -- explicit incomplete markers
- `TBD` -- to-be-determined markers

Any remaining placeholder causes a gate failure. The gate reports which specific placeholders
remain unfilled so the author knows exactly what to complete.

**Gate 6 -- Quality Check:** Profile-specific quality evaluation. Different profiles may set
different quality thresholds. For example, the `microsoft-enterprise` profile may require
security review sign-off, while the `starter` profile may skip it.

### State Tracking

When a phase completes (all gates pass), the artifact paths are recorded in `state.yaml`:

```yaml
phases:
  0:
    name: discovery
    status: complete
    completed_at: "2025-03-20T14:30:00Z"
    artifacts:
      - "artifacts/00-discovery/constitution.md"
      - "artifacts/00-discovery/problem-statement.md"
      - "artifacts/00-discovery/success-criteria.md"
      - "artifacts/00-discovery/constraints.md"
      - "artifacts/00-discovery/phase1-handoff.md"
```

### Placeholder Conventions

Templates use these placeholder patterns consistently:

| Pattern | Meaning | Example |
|---------|---------|---------|
| `[Text in brackets]` | Must be replaced with project-specific content. **Not detected by Gate 2** — see the note in §1; leaving these in place does not fail the gate | `[Project Name]`, `[Specific number/condition]` |
| `${VARIABLE}` | System-replaced during initialization. Gate 2 fails while any remain | `${PROFILE_ID}`, `${PROJECT_NAME}`, `${CREATED_AT}` |
| `<!-- REQUIRED: ... -->` | Marks a section that must be written. **Delete the comment once you have written that section** — Gate 2 fails the artifact while any remain, which is how an untouched template is caught | `<!-- REQUIRED: risk-entry -- all attributes filled in -->` |
| `NNN` in identifiers | Sequential numbering placeholder | `FR-NNN`, `RISK-NNN`, `ADR-NNN` |

---

## 11. Cross-References

| Document | Relationship to Templates |
|----------|--------------------------|
| [gate-system.md](gate-system.md) | Gates 1, 2, and 6 validate artifact existence, completeness, and quality |
| [state-machine.md](state-machine.md) | `state-init.yaml` template initializes the state machine; completed artifacts are recorded in state |
| [integrations.md](integrations.md) | `/deep-plan` integration maps to `SECTION-template-deep-plan.md`; `/deep-implement` reads the Implementation Guidance section |
| [phase-lifecycle.md](phase-lifecycle.md) | Phase definitions in `phases/` reference which templates are required for each phase |
| `profiles/_schema.yaml` | Profile configuration determines which artifacts are required vs. optional per phase |
| `scripts/check_gates.py` | Python script that implements Gate 1 and Gate 2 checks against artifact templates |
| `agents/section-evaluator.md` | Agent that evaluates completed sections against their Evaluator Contract |
| `scripts/sprint.py` | Fills `sprint.md` into `.sdlc/sprints/SNN.md` and writes the five optional spec sprint keys |
| [references/sprint-model.md](../references/sprint-model.md) | The sprint lifecycle, the ready rule, the mix, the metrics policy |
