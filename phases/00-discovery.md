# Phase 0: Discovery

## Purpose
Understand the problem space deeply enough that a stakeholder who has never heard of the project can read the artifacts and make an informed decision about whether to proceed, what scope to approve, and what success looks like. This phase produces evidence, not assumptions.

## Entry Criteria
- Project initiated via `/sprd-setup`
- State machine created with Phase 0 active

## Workflow

### Step 0: HITL Gate — Frame the Problem with the Human

> **HITL GATE:** Before writing any artifact, conduct a brief scoping conversation. Ask the human using the `AskUserQuestion` tool — do not use inline markdown for HITL questions: (1) What is the problem in one sentence? (2) Who is most affected? (3) What does success look like? (4) What constraints are non-negotiable? (5) What type of system is this? Choose one: **service** (backend API / server process), **app** (user-facing application with UI), **library** (shared code package / SDK), **skill** (Claude Code skill / AI plugin / prompt-based tool), **cli** (command-line tool). Record the answer as `project_type` in `state.yaml` — it determines which later-phase templates apply. Use these answers to anchor the artifacts — do not invent the problem framing. **CRITICAL: Never fabricate stakeholder personas.** Only create persona cards for people the human actually identifies. If the human says "just me," there is one stakeholder. Do not add hypothetical reviewers, end users, or other personas unless the human names them.

### Step 0b: Brownfield Detection (Conditional)

If the project directory contains existing source code (not just `.sdlc/`), run a workspace scan before writing artifacts:

1. **Detect existing codebase:** Check for `src/`, `lib/`, `app/`, `package.json`, `*.csproj`, `*.sln`, `Cargo.toml`, `go.mod`, or other language markers
2. **If brownfield (existing code found):**
   - Spawn an `Explore` agent to analyze the codebase
   - Generate a brief workspace analysis in `.sdlc/artifacts/00-discovery/workspace-analysis.md`:
     - **Tech stack:** Languages, frameworks, databases, cloud services detected
     - **Architecture:** High-level structure (monolith, microservices, serverless, etc.)
     - **Code metrics:** Approximate file count, line count, test coverage if detectable
     - **Dependencies:** Key external dependencies and their versions
     - **Entry points:** Main files, API routes, CLI commands
   - This analysis feeds into Steps 1-4 — the problem statement and design should account for existing code
3. **If greenfield (no existing code):** Skip this step entirely

> CHECKPOINT: If workspace analysis was generated, confirm with the human: "I've analyzed the existing codebase. Does this summary look accurate? Any systems or patterns I missed?"

### Step 0c: Document Intake (Conditional)

If the project profile includes a `documentation` section, process external reference documents
before writing discovery artifacts.

**Run `/sprd-intake`.** The command owns the whole workflow: it runs the cataloger
(`intake_documents.py`), presents the HITL prioritization gate, writes a token-budgeted summary
per document (DOC-NNN IDs), generates the registry and the session-start index, and locks the
catalog so DOC-NNN IDs stay stable for Phase 1 traceability. Do not run the cataloger script by
hand — `/sprd-intake` is the entry point. See `commands/sprd-intake.md` for the full step list,
arguments (`--docs`, `--rescan`), and budgets.

If the profile does NOT include a `documentation` section, skip this step entirely.

### Step 0d: Discovery Workshop Prep (Conditional)

When discovery involves a stakeholder workshop — multiple stakeholders, a client engagement, or
anyone beyond the single human running this session — prepare the workshop from the intake
corpus instead of walking into the room cold. Ask the human at the Step 0 scoping conversation:
"Will discovery involve a stakeholder workshop, or is this a solo/internal discovery?" Skip this
step entirely for solo discovery.

Requires Step 0c (document intake) to have run. If there is no document corpus, the analysis
has nothing to read — proceed with the question list only, sourced from the scoping conversation.

1. **Cross-document analysis:** Spawn the `discovery-analyst` agent to compare the corpus and
   produce two artifacts in `.sdlc/artifacts/00-discovery/` (templates in
   `templates/phases/00-discovery/`):
   - `contradiction-list.md` — where the documents disagree (CON-NN entries, each with two
     verbatim citations and the question that resolves it)
   - `question-list.md` — what no document answers (Q-NN entries, grouped by workshop agenda
     block, routed `workshop` / `pre-workshop` / `interview`)

2. **Send the cheap questions now:** Questions routed `pre-workshop` are answerable by email —
   send them before the workshop so room time is spent only on what the room can uniquely answer.

3. **Draft the brief:** Run `/sprd-brief` (or follow its steps inline). The human curates what
   makes the page — which contradictions, which questions, the decisions the room must leave
   with, logistics.

> **HITL GATE:** The workshop brief is curated, not generated. The human chooses its contents
> via the `/sprd-brief` curation gate, edits the draft, and distributes it themselves. The brief
> contains questions only — never draft outcomes, metrics, or solutions into it; the workshop
> exists to produce those in the stakeholders' words.

4. **After the workshop:** Record answers in the `question-list.md` and `contradiction-list.md`
   answer/resolution logs (who answered, what, when). Resolved content feeds Steps 1-5;
   questions still open at phase exit carry into `phase1-handoff.md` under the SAME Q-NN IDs.

These artifacts are optional for gate purposes (`/sprd-gate` does not require them), but every
`blocks-outcome` contradiction must be resolved or explicitly accepted as a risk before Phase 0
exit.

### Step 1: Problem Identification
Conduct stakeholder interviews or document the problem statement. Dig until you have:
- **Observable symptoms** — what people actually experience, not the inferred cause
- **Quantified impact** — time lost, cost, frequency, scale. "A lot" is not a metric.
- **Who is affected** — named personas with specific roles and specific pains
- **Why it matters now** — urgency, trigger, business context

Use Five Whys or equivalent root cause analysis. Don't stop at the first "why".

### Step 2: Current State Analysis
Document what exists today:
- How does the process/system work right now? (flow diagram)
- What metrics describe the current state? (with benchmarks for comparison)
- What tools, systems, or workarounds are in use?
- Where does the current state fail most painfully?

### Step 3: Define Success
For each stakeholder, define what "solved" looks like in measurable terms:
- What specific outcome changes?
- How will we measure it?
- What is the baseline today?
- What is the target? What is a stretch target?
- What counts as partial success vs. failure?

### Step 4: Scope Boundaries
Draw explicit lines:
- **In scope:** What this project MUST address in v1
- **Out of scope:** What it explicitly excludes (and why — prevents scope creep arguments later)
- **Assumptions:** Stated facts taken as given. Each assumption is a risk if wrong.
- **Constraints:** Non-negotiables that shape the solution space

### Step 5: Write Project Constitution
Establish the project's governing document:
- Fill in the Project Identity and Mission Statement
- Define 3–5 governing principles specific to this project (not generic)
- Document decision authority — who approves phase transitions, architecture decisions, scope changes
- This document is referenced by all subsequent phases and amended as the project evolves

### Step 6: Phase Handoff
Package everything Phase 1 needs:
- Summary of key findings (5–10 bullets)
- Decisions already made (and the rationale)
- Open questions Phase 1 must answer
- Risks to carry forward
- Recommended starting point for requirements

### Step 7: Generate Visual Report

Generate an interactive HTML visual report at `.sdlc/reports/00-discovery-visual.html` using the `/visual-explainer` skill (or equivalent HTML generation). This report is the stakeholder review artifact.

**Required visualizations for Phase 0 (Discovery):**
- Stakeholder persona cards with pain points
- Current state flow diagram (ASCII → Mermaid)
- Success criteria dashboard (baseline → target → stretch per dimension)
- Scope boundaries (in-scope vs out-of-scope)
- Document corpus overview (when document intake was performed): document type distribution, token budget utilization, topic cluster map

See the Visual Report Protocol in `SKILL.md` for rendering standards and fallback behavior.

### Step 8: Generate Phase Report
Run `/sprd-gate` to validate exit criteria and automatically generate the phase HTML report at `.sdlc/reports/00-discovery-report.html`. Share this report with stakeholders for review before requesting sign-off. The report includes artifact inventory and gate status.

## Artifact Specifications

### `constitution.md` (REQUIRED)
Must contain ALL of:
- **Project Identity** — name, profile, creation date
- **Project Type** — one of: `service`, `app`, `library`, `skill`, `cli`. This field drives template selection in Phases 6–9.
- **Mission Statement** — one paragraph, written for a non-technical audience
- **Governing Principles** — 3–5 specific principles for this project (not copy-paste boilerplate)
- **Decision Authority** — who approves what, at what level
- **Amendment Process** — how the document gets updated as the project evolves

### `problem-statement.md` (REQUIRED)
Must contain ALL of:
- **Executive Summary** — 2–3 sentences: problem, who has it, business impact
- **Problem Definition** — observable symptoms, specific and concrete
- **Stakeholder Personas** — table with: Persona, Role, Specific Pain Points, Goals
- **Current State Analysis** — process flow (ASCII diagram), current metrics vs benchmarks
- **Root Cause Analysis** — Five Whys or equivalent, ending at the actual root cause
- **What Solved Looks Like** — end state description per stakeholder

Use real numbers. Use a table for stakeholders. Use an ASCII flow diagram for current state.

### `success-criteria.md` (REQUIRED)
Must contain ALL of:
- **Overall success definition** — one sentence that captures the spirit
- **Measurable dimensions** — grouped by theme (efficiency, quality, adoption, etc.)
- **Per-criterion structure**: Baseline → Target → Stretch target → Measurement method → Timeline
- **Acceptance thresholds** per criterion: ✅ Success / ⚠️ Partial / ❌ Failure

Do not write vague criteria. "Faster" is not a success criterion. "Reduces X from Y to Z by date D" is.

### `constraints.md` (REQUIRED)
Must contain ALL of:
- **Technical constraints** — technology choices, compatibility requirements, infrastructure limits
- **Operational constraints** — team size, skills, support model, deployment environment
- **Timeline constraints** — hard deadlines and their source (contractual, business event, etc.)
- **Budget/resource constraints** — if applicable
- **Rationale column** — for each constraint, WHY it exists. Undocumented constraints get challenged.

Format as a table: Constraint | Type | Rationale | Impact if violated.

### `phase1-handoff.md` (REQUIRED)
Must contain ALL of:
- **Discovery Summary** — what was learned, in 5–10 bullets
- **Decisions Made** — what was decided during discovery and the rationale
- **Recommended Scope** — what Phase 1 should include based on discovery findings
- **Open Questions** — specific questions Phase 1 must answer before design can start
- **Risks to Monitor** — risks surfaced during discovery with probability/impact rating
- **Suggested Starting Point** — where Phase 1 should begin and what to tackle first

### `po-decision-record.md` (OPTIONAL)

The Product Owner arrangement, in writing: a named PO with committed hours per week, or a signed
proxy rider naming who decides in their place.

This is an SOW precondition with billing teeth. It is optional here because the contract is its
home of record — a copy in `.sdlc/` that disagrees with the signed document is worse than no copy.
Record it when the decision is made outside the contract, or link to where it lives.

Must contain: the mode chosen, the named person, their committed hours, the date agreed, and who
agreed it.

> **Optional by design.** Its absence does not by itself mean the phase went badly, so the gate
> does not block on it — but the approver is asked about it at sign-off. Write it when the work
> happens; a receipt written later from memory is worth less than no receipt at all.

### `tooling-record.md` (OPTIONAL)

Anthropic access live under the client's own account, or a signed fallback rider with a date to
migrate.

The other precondition with billing teeth, and optional for the same reason: the rider is a contract
artifact. What belongs here is the operational fact — whose account, whose keys, whose audit trail,
and the date the fallback expires if one is in use.

> **Optional by design.** Its absence does not by itself mean the phase went badly, so the gate
> does not block on it — but the approver is asked about it at sign-off. Write it when the work
> happens; a receipt written later from memory is worth less than no receipt at all.

### `workshop-brief.md` (OPTIONAL)

The outcome-workshop brief as it was actually sent: questions only.

The brief is curated by a human from Claude's draft and must never propose outcomes, metrics or
solutions — a brief that answers its own questions produces a workshop that confirms what we already
assumed. Today it is drafted, edited, sent, and never kept.

Must contain: the questions as sent, who curated them, who received it, and the date.

> **Optional by design.** Its absence does not by itself mean the phase went badly, so the gate
> does not block on it — but the approver is asked about it at sign-off. Write it when the work
> happens; a receipt written later from memory is worth less than no receipt at all.
## Exit Criteria
- [ ] `constitution.md` contains: project identity, mission statement, governing principles, decision authority
- [ ] `problem-statement.md` contains: exec summary, persona table, current state metrics, root cause analysis
- [ ] `success-criteria.md` contains at least 3 measurable dimensions with pass/fail thresholds
- [ ] `constraints.md` documents all known constraints with rationale
- [ ] `phase1-handoff.md` contains open questions and risks
- [ ] All artifacts reviewed and approved by stakeholder (manual gate)
- [ ] Scope boundaries are unambiguous

## HTML Report
The phase report is generated automatically when you run `/sprd-gate` or `/sprd-next`. It is written to `.sdlc/reports/00-discovery-report.html` and is fully self-contained — share it with stakeholders as the review artifact for the manual sign-off gate.

To regenerate at any time: `/sprd-phase-report`

## Guidance
- Resist the urge to jump to solutions. A proposed solution in a problem statement is a scope assumption.
- If you can't quantify the impact, dig harder — the number exists somewhere.
- Stakeholder personas must come from the HITL interview — never fabricate them. If the human identifies one stakeholder, there is one persona card. Do not pad the list with hypothetical users.
- Every assumption in `constraints.md` is a risk. The riskiest ones belong in the handoff.
- The handoff package is a first-class artifact. A Phase 1 team should be able to start with only that file.

## Coaching Prompts

When operating in coaching mode (`/sprd-coach`) for this phase:

### Opening (no artifacts yet)
- "What problem are you trying to solve? Tell me in plain language."
- For structured ideation, see `references/brainstorming-techniques.md` for techniques like SCAMPER, reverse brainstorming, and constraint removal.
- "Who are the main stakeholders — the people who care about the outcome?"
- "What constraints are you working with? Budget, timeline, technology, team size?"
- "Has anyone validated that this problem is worth solving?"

### Progress Check (some artifacts exist)
- "I see your problem statement. Is this the root cause, or a symptom of something deeper?"
- "Your constraints mention [X]. How firm is that? Would it change if the scope changes?"

### Ready Check (all artifacts present)
- "Your discovery artifacts look solid. Are you confident about the scope boundaries before we lock them?"
- "Anything missing from the stakeholder map? Anyone we'd regret not consulting?"

### Document Intake (when configured)
- "I see N documents in your intake folder. Which ones are most critical for understanding the project scope?"
- "The RFP mentions [X] — does that align with your understanding of the core problem?"
- "Several documents reference [compliance requirement]. Should this be a non-negotiable constraint?"
- "Documents DOC-003 and DOC-007 seem to contradict each other on [topic]. Which takes precedence?"
