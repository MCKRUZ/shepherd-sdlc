# Phase 7: Documentation

## Purpose
Ensure all documentation reflects the system as built — not as planned. A new team member should be able to understand, run, and operate the system using only the documentation produced in this phase.

## Project Type Adaptation

**Before starting Phase 7, read `project_type` from `state.yaml`.**

| project_type | Documentation Scope |
|--------------|-------------------|
| `service` / `app` | Full documentation suite: README, API docs, RUNBOOK, ADR finalization. All artifacts required. |
| `library` / `cli` | README, API reference (generated from code), CHANGELOG, migration guide if applicable. Skip RUNBOOK — there is no server to operate. Replace `RUNBOOK.md` exit criterion with CHANGELOG + migration guide. |
| `skill` | README (install + usage), SKILL.md refinement, example gallery. Skip API docs and RUNBOOK — there are no endpoints or servers. Replace `api-docs.md` and `RUNBOOK.md` exit criteria with SKILL.md + examples. |

**For `library` / `cli` / `skill` projects:** Mark skipped artifacts as `N/A — {project_type}` in the gate check. Do not spend time writing documentation for components that do not exist.

## Entry Criteria
- Build loop feature-complete (human declaration — it is continuous, with no batch artifact gate) and `phase7-handoff.md` reviewed
- Test results confirm system behavior documented

## Workflow

### Step 0: HITL Gate — Scope the Documentation

> **HITL GATE:** Before writing any documentation, read `phase7-handoff.md` and review the current state of any existing docs. Present the following to the human using the `AskUserQuestion` tool — do not use inline markdown for HITL questions: (1) Who is the primary audience for each document — developers, operators, end users? (2) Which docs already exist and need updating vs. which must be created from scratch? (3) Are there company-specific documentation standards or templates to follow? (4) For `library`/`skill` projects: confirm which artifacts are applicable and which should be skipped. Do not begin Step 1 until the human confirms the documentation scope.

### Step 1: Write the Two Documentation Domains

Phase 7 has two distinct audiences and they are written differently. Do both, in either order.

**The README — for someone who has never seen this repo.** Update it against what was actually
built, using `phase7-handoff.md` for the gaps testing exposed. The setup instructions must work
against a fresh checkout, not against your machine with its history. Step 4 is where that claim
gets tested, so write it to be testable.

**`api-docs.md` — for someone integrating against it.** Read the current endpoint implementations
rather than the design, then diff them against `api-contracts.md` from Phase 2. What the code does
is the fact; the contract is the intention. Where they disagree, both the drift and its reason
belong in the file.

**For `library` / `cli` projects:** `api-docs.md` is the public API reference instead — every
exported function, class and type, generated from the code — plus CHANGELOG entries for this
release.

**For `skill` projects:** there are no endpoints. Refine `SKILL.md` in place of `api-docs.md`:
verify every instruction is current, edge cases are handled, and add an example gallery of 3–5
common invocations with their expected output.

### Step 2: API Documentation — Diff-Based Approach

Verify the API docs against the Phase 2 contracts:
- Load `api-contracts.md` from Phase 2 artifacts
- Diff every endpoint: URL, method, request schema, response schema, auth requirements
- For each drift: document **what** changed, **when** (which phase/section), and **why**
- If drift is unintentional, flag it as a defect for resolution before deployment

This ensures API documentation is verified against the design, not just transcribed from the code.

### Step 3: Runbook — Write for 3am

Write the operational runbook with this principle: **the reader is exhausted, stressed, and seeing this system for the first time during an incident.**

Every procedure must be:
- **Step-by-step** — numbered actions, not paragraphs
- **Copy-pasteable** — exact commands, not "run the deploy script"
- **Observable** — after each step, how do you verify it worked?
- **Recoverable** — if this step fails, what do you do?

Reference the Phase 9 monitoring setup — the runbook's failure scenarios should map to the alerts that will be configured.

**Skip this step for `library` / `cli` / `skill` projects.**

### Step 4: ADR Finalization

Close any ADRs that were open during implementation and surface undocumented decisions:

```
Agent(Explore, "Search the git history from the start of the Build loop for significant technical decisions that are not recorded in the adrs/ directory. Look for: architectural changes, dependency additions, pattern choices, and rejected alternatives mentioned in commit messages or implementation-notes.md. List each undocumented decision with context.")
```

For each undocumented decision found:
- Write a new ADR with: context, decision, consequences, and alternatives considered
- Update `adr-registry.md` with the new entries
- Mark all open ADRs as accepted or superseded based on implementation outcomes

### Step 5: Phase Handoff
Summarize what was documented, what's out of date, and what monitoring should cover.

### Step 6: Generate Visual Report

Generate an interactive HTML visual report at `.sdlc/reports/07-documentation-visual.html` using the `/visual-explainer` skill (or equivalent HTML generation). This report is the stakeholder review artifact.

**Required visualizations for Phase 7 (Documentation):**
- Documentation completeness audit table (doc → status)
- API documentation coverage
- README sections checklist
- Runbook completeness

See the Visual Report Protocol in `SKILL.md` for rendering standards and fallback behavior.

### Step 7: Generate Phase Report
Run `/sprd-gate` to validate exit criteria and automatically generate the phase HTML report at `.sdlc/reports/07-documentation-report.html`. Share this report with stakeholders for review before requesting sign-off. The report includes artifact inventory and gate status.

## Artifact Specifications

### `README.md` (REQUIRED)
Must contain ALL of:
- **Project description** — what it does and why
- **Prerequisites** — tools, runtimes, accounts needed
- **Local setup** — step-by-step, someone new can follow it exactly
- **Running the project** — dev, test, and production modes
- **Configuration** — key settings and where they live
- **Contributing** — how to make changes (branch strategy, PR process)

### `api-docs.md` (REQUIRED — `service` / `app` / `library` / `cli`)
Must contain ALL of:
- All current endpoints or public API surface (not just changes)
- Request/response schemas with examples
- Authentication model
- Error catalog with HTTP status codes and resolution guidance
- Changelog — what changed from the Phase 2 API contracts, with rationale for each drift

### `RUNBOOK.md` (REQUIRED — `service` / `app` only)
Must contain ALL of:
- **Deployment procedure** — step by step, including pre/post checks
- **Configuration reference** — every env var, secret, and flag with description and valid values
- **Common operations** — restart, scale up/down, database migration, rollback
- **Failure scenarios** — top 5 failure modes with diagnosis steps and resolution
- **Monitoring cross-reference** — which Phase 9 alerts map to which failure scenarios

### `phase8-handoff.md` (REQUIRED)
Must contain ALL of:
- **Documentation inventory** — what was updated vs. created
- **Gaps** — anything that couldn't be documented (and why)
- **Deployment checklist** — all pre-deployment steps from this phase
- **Operations readiness** — is the runbook sufficient for an on-call engineer?
- **ADR status** — all ADRs finalized, or list of any remaining open decisions

### `readme-verification.md` (REQUIRED)

The defect log from someone who did not write the README following it cold, on a clean machine.

Phase 7's entire purpose is to prove a stranger can run the system. The proof is not that the README
exists or reads well — it is that a specific person, with no context, got to a working system by
following it, and here is every place they stalled.

Must contain:
- **Who verified it, and when** — a named person who did not write the documentation
- **From what starting point** — clean clone, which OS, which toolchain versions
- **Every stall, as it happened** — the step, what was missing or wrong, what they did instead
- **What was fixed** — the README change each stall produced
- **The re-run** — did a second cold pass get through without help

"A little help from the author" is a **failed** verification, not a passed one with an asterisk. Log
it as a stall.

> **HITL GATE:** Claude cannot perform this — the whole value is a human without context. Ask who
> did it and when; refuse to accept the pod's own author as the verifier.

> **If it genuinely did not happen**, say so *in this file*: a line reading
> `WAIVED: <name> — <reason>`. The gate accepts it and reports it, by name, in the record the
> approver signs against. A missing file still blocks. The escape is from the work, not the
> record — an exception nobody can see is how a gate stops being a gate.

### `runbook-walkthrough.md` (REQUIRED)

The client's own operations engineer executing a deploy, a rollback, and one failure scenario from
the RUNBOOK, cold, using their own permissions.

Their own permissions is the load-bearing part. A walkthrough performed with the pod's access proves
the RUNBOOK works for people who will not be here next month.

Must contain:
- **Who walked it** — the client's operator, named, and the date
- **The three exercises** — deploy, rollback, and one failure scenario, each with what happened
- **Permission gaps found** — every place they lacked access the RUNBOOK assumed
- **Timings** — how long the rollback actually took, which is the number an incident cares about
- **What was rewritten** — the RUNBOOK changes each gap produced

> **HITL GATE:** This requires a real person from the client's operations function and a real
> environment. Ask who it will be and when it is scheduled; do not accept a pod member standing in.

> **If it genuinely did not happen**, say so *in this file*: a line reading
> `WAIVED: <name> — <reason>`. The gate accepts it and reports it, by name, in the record the
> approver signs against. A missing file still blocks. The escape is from the work, not the
> record — an exception nobody can see is how a gate stops being a gate.
### `spec-audit-record.md` (OPTIONAL)

Five to ten specs, weighted to HIGH-risk and recently-changed, with their acceptance checks executed
by hand against the running system.

The grader checked these once, at merge, against the diff. This is the trust-but-verify pass that
asks whether the spec library still describes the system that actually exists.

Must contain: which specs were sampled and why those, each check re-executed with its result, and
every divergence found between the spec and reality.

> **Optional by design.** Its absence does not by itself mean the phase went badly, so the gate
> does not block on it — but the approver is asked about it at sign-off. Write it when the work
> happens; a receipt written later from memory is worth less than no receipt at all.
## Exit Criteria
- [ ] README allows a new developer to set up and run the project from scratch
- [ ] API docs are current with the implementation (not the plan)
- [ ] RUNBOOK covers deployment, configuration, and top failure scenarios (service/app only)
- [ ] All ADRs finalized — no open decisions remaining
- [ ] Stakeholder reviewed and approved (manual gate)

## HTML Report
The phase report is generated automatically when you run `/sprd-gate` or `/sprd-next`. It is written to `.sdlc/reports/07-documentation-report.html` and is fully self-contained — share it with stakeholders as the review artifact for the manual sign-off gate.

To regenerate at any time: `/sprd-phase-report`

## Guidance
- Test your README against a fresh checkout — clone the repo to a temp directory and follow the instructions verbatim. If any step requires knowledge not in the README, the README is incomplete.
- The runbook is for 3am incidents. Every time you write "see the wiki" or "ask the team", you've failed the person who will be alone at 3am.
- API docs written after the fact must be verified against the running system, not the design. Run actual requests and paste actual responses.
- ADRs from implementation that were never recorded are debt — close them now or they become tribal knowledge that walks out the door.
- Documentation is not a phase to rush through. The 30 minutes you save skipping docs costs the next developer 3 hours of reverse engineering.

## Coaching Prompts

When operating in coaching mode (`/sprd-coach`) for this phase:

### Opening (no docs started)
- "Who's the audience for this documentation — developers, operators, end users?"
- "What documentation types do you need — API docs, user guide, operator manual?"
- "Is there existing documentation that needs updating vs. creating from scratch?"

### Progress Check (some docs written)
- "API docs cover [X] of [Y] endpoints. Want me to generate the rest?"
- "The user guide is drafted. Does the tone match your audience?"

### Ready Check (all docs complete)
- "Documentation suite is complete. Any areas that need more detail?"
- "Have you had someone outside the team review the docs for clarity?"
