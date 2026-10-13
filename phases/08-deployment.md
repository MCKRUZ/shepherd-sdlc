# Phase 8: Deployment

## Purpose
Deploy the system to production safely, with documented rollback capability, verified smoke tests, and a release artifact that stakeholders can distribute. No surprises — every step is planned and verified.

## Project Type Adaptation

**Before starting Phase 8, read `project_type` from `state.yaml`.**

| project_type | Deployment Model | Staging | Rollback |
|--------------|-----------------|---------|---------|
| `service` / `app` | Container / cloud deploy. Run full staging environment. Execute smoke tests against live endpoints. | Required — must be a running environment, not a local copy | Redeploy previous image/version; reverse DB migrations |
| `library` / `cli` | Package registry publish (npm, PyPI, NuGet). Staging = local install test in a fresh environment. | Install the package in an isolated environment and run the public API smoke tests | Yank the package version from the registry; pin consumers to previous version |
| `skill` | File distribution (copy to `.claude/commands/`). No server, no process. Staging = fresh install on a clean project. | Install the skill files in a new project; run the minimum smoke test set | Delete the skill files; re-copy the previous version |

**For `skill` / `library` projects:** Skip steps that reference staging servers, database migrations, health checks, and monitoring dashboards — they do not apply. Focus on: (1) install verification, (2) smoke test execution, (3) rollback documentation (file deletion / version revert), and (4) release artifact creation (GitHub release on GitHub; Azure Artifacts or a pipeline artifact on Azure DevOps / package publish).

## Entry Criteria
- Phase 7 exit gate passed and `phase8-handoff.md` reviewed
- Deployment environment provisioned
- Secrets and configuration ready

## Workflow

### Step 0: HITL Gate — Deployment Go/No-Go

> **HITL GATE (most critical gate in the lifecycle):** Before any deployment activity, read `phase8-handoff.md` and present the following to the human using the `AskUserQuestion` tool — do not use inline markdown for HITL questions: (1) Deployment target and strategy — blue/green, rolling, canary, or direct replacement? (2) Rollback plan — what is the trigger condition, what is the exact procedure? (3) Who must be notified before, during, and after deployment? (4) Is this staging-only or staging + production? (5) Deployment window — when does it start, how long is the maintenance window? **Do NOT proceed to Step 1 without explicit human go/no-go.** A deployment without human approval is not a deployment — it is an incident.

Record the outcome in `go-no-go-record.md` as the ceremony happens: the decision, and every named
role's answer with any condition they attached. Write it during the gate, not afterwards — the
point of the record is that it captures what people actually said before anyone knew how the
deployment went.

### Step 1: Pre-Deployment Checklist
Verify all deployment prerequisites:
- All tests passing on the deployment candidate
- Configuration reviewed for target environment
- Database migrations tested on a copy of production data
- Rollback procedure documented and tested
- Stakeholders notified of deployment window

**Rollback verification:** Before deploying forward, verify the rollback procedure works. Deploy, then roll back, then redeploy. If you can't roll back in staging, you can't roll back in production.

### Step 2: Staging Deployment

Execute the staging deployment using the procedure in `RUNBOOK.md` — the runbook is the
authority, and a deployment that needs a step the runbook does not contain has found a defect in
the runbook. Verify every service starts without errors, then check the health endpoints. Report
failures with the full error context rather than a summary; the context is what makes the next
step possible.

**On build failure during deployment:** spawn `build-error-resolver` immediately. Do not attempt
manual fixes first — a hand-patched build hides the cause and the same failure returns in
production.

```
# Only if the deployment build fails:
Agent(build-error-resolver, "Deployment build failed. Analyze the build output, identify root cause, and fix. Verify the fix compiles and passes tests before re-attempting deployment.")
```

### Step 3: Smoke Test Execution

Run the smoke test suite against staging: one test per P0 user story, minimum. Capture screenshots
as evidence and record pass/fail per test with timestamps.

**Every smoke test must be non-destructive** — read operations and harmless writes only. A smoke
test that mutates real state is an outage waiting for the day someone runs it against production.

Verify:
- One test per P0 user story (minimum)
- Core integrations are live
- Monitoring and alerting are receiving data
- Document results — pass/fail per test

### Step 4: Production Deployment
Deploy to production following the same procedure:
- Execute pre-production gate checklist
- Deploy using the same runbook procedure validated in staging — same steps, not a variant
- Run the same smoke tests against production
- Confirm monitoring dashboards show healthy state

**For `skill` / `library` projects:** Production deployment = package publish or file distribution. Verify install works in a clean environment.

### Step 5: Phase Handoff
Document the deployment state and what monitoring needs to cover.

### Step 6: Generate Visual Report

Generate an interactive HTML visual report at `.sdlc/reports/08-deployment-visual.html` using the `/visual-explainer` skill (or equivalent HTML generation). This report is the stakeholder review artifact.

**Required visualizations for Phase 8 (Deployment):**
- Deployment readiness checklist (items → pass/fail)
- Environment configuration status
- Release notes summary
- Rollback plan overview

See the Visual Report Protocol in `SKILL.md` for rendering standards and fallback behavior.

### Step 7: Generate Phase Report
Run `/sprd-gate` to validate exit criteria and automatically generate the phase HTML report at `.sdlc/reports/08-deployment-report.html`. Share this report with stakeholders for review before requesting sign-off. The report includes artifact inventory and gate status.

## Artifact Specifications

### `release-notes.md` (REQUIRED)
Must contain ALL of:
- **Version** — semantic version and release date
- **Summary** — what this release delivers (2–3 sentences for stakeholders)
- **New features** — user-facing capabilities added
- **Bug fixes** — issues resolved
- **Breaking changes** — anything that requires consumer action
- **Known limitations** — things that don't work yet or have caveats
- **Upgrade path** — if applicable, how to upgrade from previous version

### `deployment-checklist.md` (REQUIRED)
Must contain ALL of:
- **Pre-deployment** — environment checks, configuration verification, notification steps
- **Deployment steps** — ordered, each with: action, expected outcome, how to verify
- **Post-deployment verification** — smoke tests, health checks, monitoring confirmation
- **Rollback procedure** — exact steps to revert, with decision criteria ("roll back if X")
- **Rollback verification** — evidence that rollback was tested in staging before production
- **Sign-off** — who approved and when

### `smoke-test-results.md` (REQUIRED)
Must contain ALL of:
- **Environment** — staging and production results (separate sections)
- **Test results table** — Test | P0 Story | Environment | Result | Notes
- **Issues found** — any failures, their severity, and resolution
- **Screenshot evidence** — references to captured screenshots per test
- **Deployment decision** — go/no-go with rationale

### `phase9-handoff.md` (REQUIRED)
Must contain ALL of:
- **Deployment summary** — what was deployed, when, where
- **Current system state** — what's running and how to verify it
- **Monitoring requirements** — what alerts and dashboards need to be set up
- **Known issues in production** — anything to watch post-deployment
- **Escalation contacts** — who to call if something goes wrong

### `rollback-rehearsal.md` (REQUIRED)

The timestamped record of a deploy, a rollback, and a redeploy, run by the client's operators in a
real environment before production.

The standard already says a rollback that has never run is a wish. This file is the wish becoming a
fact, and it is the single most useful document in the repository at 3am.

Must contain:
- **The timeline** — deploy, the decision to roll back, rollback complete, redeploy, each stamped
- **Time back to healthy** — the number the incident commander will want, measured not estimated
- **Who ran it** — the client's operators, named
- **What broke that was not expected** — the rehearsal's actual output. A rehearsal where nothing
  surprised anyone was probably not run against anything real
- **The trigger conditions** — written down in advance: what makes someone decide to roll back

> **HITL GATE:** Do not accept a described rollback procedure in place of an executed one. Ask when
> it was run, in which environment, and by whom.

> **If it genuinely did not happen**, say so *in this file*: a line reading
> `WAIVED: <name> — <reason>`. The gate accepts it and reports it, by name, in the record the
> approver signs against. A missing file still blocks. The escape is from the work, not the
> record — an exception nobody can see is how a gate stops being a gate.

### `secrets-rotation-record.md` (REQUIRED)

Production credentials rotated to values the pod has never held, confirmed by the client's security
function.

This is the handoff made literal. Everything else at close is a document; this is the moment the
client's system stops being reachable by us. It is also the single most audit-relevant fact of the
whole engagement.

Must contain:
- **Every credential rotated** — what it was for, and where it now lives
- **The rotation date**, per credential
- **Confirmation by the client's security function** — a named person, not the pod
- **Anything deliberately not rotated**, with the reason and who accepted the risk
- **The audit-trail reference** — where this can be independently confirmed later

> **HITL GATE:** The pod cannot sign this off. It is confirmed by the client's security function,
> by name, or it is not confirmed.

> **If it genuinely did not happen**, say so *in this file*: a line reading
> `WAIVED: <name> — <reason>`. The gate accepts it and reports it, by name, in the record the
> approver signs against. A missing file still blocks. The escape is from the work, not the
> record — an exception nobody can see is how a gate stops being a gate.

### `go-no-go-record.md` (REQUIRED)

The recorded output of the Step 0 ceremony: the decision to deploy, with every named role's answer
captured at the time it was given.

The gate itself already happens — Step 0 is the most consequential HITL gate in the lifecycle. What
was missing was the receipt. A go/no-go that leaves no record is indistinguishable, a quarter later,
from a deployment nobody was asked about, and "who approved this?" is the first question after any
production incident.

Must contain:
- **The decision** — go, no-go, or go-with-conditions, and the date and time it was made
- **Every role polled** — named person, their answer, and any condition they attached. A role that
  was not polled is recorded as not polled, not as assent
- **What was being deployed** — the version or release, so the record ties to a specific artifact
- **Known risks accepted at the time**, and who accepted each
- **The conditions**, if any, and who owns clearing them before or after cutover

Silence is not agreement. An unrecorded answer is a missing answer.

> **HITL GATE:** The answers belong to the people who gave them. Capture them with
> `AskUserQuestion` during the ceremony — Claude records the decision and must never supply an
> answer on a named person's behalf.

> **If it genuinely did not happen**, say so *in this file*: a line reading
> `WAIVED: <name> — <reason>`. The gate accepts it and reports it, by name, in the record the
> approver signs against. A missing file still blocks. The escape is from the work, not the
> record — an exception nobody can see is how a gate stops being a gate.

### `rollout-shape-decision.md` (OPTIONAL)

Cutover, pilot or parallel-run — chosen by the client, in writing, before the go/no-go ceremony
rather than during it.

Must contain: the shape chosen and why, what happens to work already in flight, the fallback, and
the conditions that would trigger it. Named owner, dated.

> **Optional by design.** Its absence does not by itself mean the phase went badly, so the gate
> does not block on it — but the approver is asked about it at sign-off. Write it when the work
> happens; a receipt written later from memory is worth less than no receipt at all.

## Exit Criteria
- [ ] Staging deployment successful
- [ ] All staging smoke tests passing
- [ ] Production deployment successful
- [ ] All production smoke tests passing
- [ ] Rollback procedure documented and tested
- [ ] Stakeholder sign-off received (manual gate)

## HTML Report
The phase report is generated automatically when you run `/sprd-gate` or `/sprd-next`. It is written to `.sdlc/reports/08-deployment-report.html` and is fully self-contained — share it with stakeholders as the review artifact for the manual sign-off gate.

To regenerate at any time: `/sprd-phase-report`

## Guidance
- Staging is not optional. "We'll test in production" is not a deployment strategy.
- The rollback procedure must be tested before the deployment, not written for the first time during an incident. Deploy → rollback → redeploy in staging before touching production.
- Smoke tests in production should be non-destructive — read operations and harmless writes only. If your smoke test can corrupt data, it's not a smoke test.
- The release notes are for people who didn't build the system. Write for that audience.
- The HITL Gate on this phase is the most critical in the entire lifecycle. A bad commit can be reverted. A bad deployment can take down production.

## Coaching Prompts

When operating in coaching mode (`/sprd-coach`) for this phase:

### Opening (no deployment artifacts)
- "What's your deployment strategy — blue/green, canary, rolling?"
- "Do you have a rollback plan if something goes wrong?"
- "What environments need to be set up or updated?"

### Progress Check (some artifacts ready)
- "Release notes drafted. Does the changelog capture all user-facing changes?"
- "Rollback plan covers [scenarios]. Are there others to consider?"

### Ready Check (all artifacts ready)
- "Deployment artifacts are ready. Have all stakeholders signed off?"
- "Is there a smoke test plan for post-deployment verification?"
