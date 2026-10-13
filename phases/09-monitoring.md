# Phase 9: Monitoring

## Purpose
Establish production observability so the team knows about problems before users do. Configure dashboards, define alerts, write the incident response playbook, and capture a project retrospective so the next project starts smarter.

## Project Type Adaptation

**Before starting Phase 9, read `project_type` from `state.yaml`.**

| project_type | Monitoring Approach |
|--------------|-------------------|
| `service` / `app` | Full infrastructure monitoring: dashboards (RED metrics), alerting rules, on-call rotation, incident response runbook. |
| `library` / `cli` | Package health monitoring: download counts, open issues, version adoption. Alerts = GitHub issue (or ADO Boards work item) triage criteria. No dashboards. |
| `skill` | Qualitative monitoring only. No server, no metrics pipeline. Monitoring = GitHub Issues (or ADO Boards work items) + user feedback. Replace all dashboard / alerting / infrastructure content with: issue triage criteria, user feedback channels, and qualitative quality signals. |

**For `skill` / `library` projects:** The `monitoring-config.md`, `alert-definitions.md`, and `incident-response.md` artifacts should be reframed as: (1) feedback collection channels and issue triage criteria, (2) severity classification with response SLAs, and (3) escalation process. Do not spend time configuring Grafana dashboards or Prometheus rules that will never be used.

**The `project-retrospective.md` applies to all project types without modification.** It is the most important Phase 9 artifact regardless of project type.

## Entry Criteria
- Phase 8 exit gate passed and `phase9-handoff.md` reviewed
- System live in production
- Monitoring infrastructure available (profile-defined)

## Workflow

### Step 0: HITL Gate — Monitoring Scope

> **HITL GATE:** Before configuring any monitoring, read `phase9-handoff.md` and present the following to the human using the `AskUserQuestion` tool — do not use inline markdown for HITL questions: (1) Top 3 things that could go wrong in production — what are the highest-risk failure modes? (2) Who gets paged, and at what threshold? (3) What existing monitoring infrastructure exists — are we adding to Grafana/Datadog/CloudWatch or starting from scratch? (4) For `skill`/`library` projects: confirm we are using the lightweight monitoring path (issue triage + feedback channels, not dashboards). Get explicit monitoring scope approval before proceeding to Step 1.

### Step 1: Monitoring Configuration

**Establish the production baseline first.** Measure response times, throughput, error rates and
resource usage against the NFR targets in `non-functional-requirements.md`. These measurements
become the definition of "normal" that every alert threshold in Step 2 is set against — which is
why they come first. A threshold chosen before the baseline exists is a guess wearing a number.

Measure it; do not estimate it. Where a number genuinely cannot be measured yet, record it as
modeled with a revisit date, and say so in `monitoring-config.md` — the gate asks for exactly that
distinction.

**Then write `monitoring-config.md`** from those measurements: dashboard inventory, metrics
catalog, coverage assessment for P0 features, and the baselines themselves. For `skill` / `library`
projects, reframe it as feedback channels and issue triage criteria — there are no dashboards.

Set up dashboards and metrics collection:
- System health metrics (CPU, memory, disk, network)
- Application metrics (request rate, error rate, latency — RED method)
- Business metrics (what matters to stakeholders: active users, transactions, etc.)
- Dependency health (database, external APIs, queues)

**For `skill` / `library` projects:** Skip infrastructure metrics. Configure: GitHub issue monitoring (ADO Boards work-item monitoring on Azure DevOps), download/install tracking, user feedback channels.

### Step 2: Alert Definitions
Define alerts that require human response:
- For each alert: what triggers it, who gets paged, what the SLA is
- Avoid alert fatigue — every alert must be actionable
- Define: warning threshold (investigate) and critical threshold (wake someone up)
- Set thresholds relative to the baseline from Step 1 — not arbitrary round numbers

### Step 3: Incident Response Playbook
Write the runbook for common failure modes:
- What does each major alert mean?
- Initial diagnosis steps
- Escalation path
- Communication template

Cross-reference with the RUNBOOK.md failure scenarios from Phase 7. The incident response playbook should cover the same failure modes with a focus on detection and communication rather than resolution steps.

### Step 4: Alert Drill

Fire every critical alert on purpose and answer it from the playbook. Until an alert has fired it
is a configuration, not a control — the threshold may be wrong, the routing may point at a rota
that no longer exists, and the way to find out is not at 3am during a real incident.

This is why the playbook is written first: the drill tests `incident-response.md` as much as it
tests the alert.

For each critical alert in `alert-definitions.md`:
- **Trigger it deliberately** — synthetic load, a forced error, or the provider's own test-fire.
  Record which method was used; a test-fire proves routing but says nothing about the threshold.
- **Time the detection** — from the triggering condition to the page actually arriving. Observed,
  not estimated.
- **Follow the routing** — did it reach the person `alert-definitions.md` says it should?
- **Answer it from `incident-response.md`** — the responder works the playbook, not their memory.
  A step that turns out to be missing or wrong is the point of the exercise, not a failed drill.
- **Record what changed** — thresholds corrected, routing repointed, playbook steps rewritten.

Record the result in `drill-record.md`.

> **HITL GATE:** The drill needs a real responder; Claude cannot page anyone. Use the
> `AskUserQuestion` tool to confirm who is running each drill and when, then capture what actually
> happened. Claude prepares the drill plan and writes the record — it must never report a detection
> time or an outcome it did not observe.

### Step 5: Project Retrospective

Start by gathering whatever user feedback the deployment produced — GitHub issues or ADO Boards
work items, support requests, Slack messages, survey results — and look for patterns rather than
incidents: what
confused people, what they liked, what broke. Where there is no feedback yet, record that as the
finding; "we shipped and heard nothing" is itself worth knowing at Close.

Capture what worked, what didn't, and what to carry forward. The retrospective must address **both** the product and the process:

**Product retrospective:**
- Technical observations — what decisions aged well? Which created debt?
- Team observations — what collaboration patterns worked?

**SDLC process retrospective (required):**
- Which phases were most valuable for this project? Which felt like overhead?
- Which HITL gates caught real issues vs. which were rubber-stamped?
- Which artifacts were referenced later in the lifecycle? Which were written and never read?
- What would you skip next time? What would you add?
- Were the profile thresholds (coverage, file size, etc.) appropriate or should they be adjusted?

**Actionable improvements:**
- Concrete changes for the next project — not "communicate better" but "add a daily async standup during the Build loop"
- Patterns to reuse and patterns to avoid

Incorporate the feedback patterns gathered above, where any exist.

### Step 6: Generate Visual Report

Generate an interactive HTML visual report at `.sdlc/reports/09-monitoring-visual.html` using the `/visual-explainer` skill (or equivalent HTML generation). This report is the stakeholder review artifact.

**Required visualizations for Phase 9 (Monitoring):**
- Monitoring configuration status (health checks, alerts)
- Baseline metrics dashboard
- Alert routing overview
- Post-launch checklist

See the Visual Report Protocol in `SKILL.md` for rendering standards and fallback behavior.

### Step 7: Generate Phase Report
Run `/sprd-gate` to validate exit criteria and automatically generate the phase HTML report at `.sdlc/reports/09-monitoring-report.html`. Share this report with stakeholders for review before requesting sign-off. The report includes artifact inventory and gate status.

## Artifact Specifications

### `monitoring-config.md` (REQUIRED)
Must contain ALL of:
- **Dashboard inventory** — what dashboards exist and what they show
- **Metrics catalog** — every metric being collected, its source, and its meaning
- **Coverage assessment** — is every P0 feature observable? What's the gap?
- **Baseline measurements** — what "normal" looks like for each key metric, measured within the first 48h of production

### `alert-definitions.md` (REQUIRED)
Must contain ALL of:
- **Alert table** — Alert Name | Condition | Severity | Recipient | SLA | Runbook link
- **Per-alert detail for all CRITICAL alerts**: trigger condition (exact query/threshold), why this threshold, what to do when it fires, how to resolve
- **Alert philosophy** — principles used to decide what to alert on vs. observe passively
- **Baseline reference** — how thresholds were derived from the production baseline

### `incident-response.md` (REQUIRED)
Must contain ALL of:
- **Incident classification** — P1/P2/P3 with definitions
- **Response procedures** — per alert type: detect → diagnose → resolve → communicate
- **Escalation matrix** — who to contact at each severity level
- **Communication templates** — what to send users/stakeholders during an incident
- **Post-incident process** — how to write a post-mortem

### `project-retrospective.md` (REQUIRED)
Must contain ALL of:
- **What went well** — with specifics, not platitudes
- **What didn't** — honest assessment, no blame
- **Process improvements** — concrete changes to make to the SDLC for the next project
- **SDLC phase-by-phase review** — which phases added value, which gates caught issues, which artifacts were referenced later
- **Technical debt log** — known debt incurred, with priority and suggested resolution timing
- **Patterns to reuse** — decisions and approaches worth repeating
- **Patterns to avoid** — decisions that created problems
- **User feedback summary** — the patterns in whatever feedback the deployment produced (if any)

### `close-handoff.md` (REQUIRED)

The gate has always required this file and the phase never said how to write it, so it was
produced by guesswork — a required artifact with no specification is a demand nobody can satisfy
deliberately. Close reads it at its opening HITL gate, and the questions asked there are what it
must answer.

Must contain ALL of:
- **Transfer readiness** — is the client team actually ready to run the loop without us? State it
  plainly, including if the answer is no. This is a steering conversation, not a scheduling one.
- **Named client engineers** — who will orchestrate real specs at the close gate, and their
  availability. Close needs at least three working with pod Checkers, then one solo.
- **Named client Setup Owner** — who owns the harness after transfer, and whether they have
  already merged a harness change themselves. "Will be identified later" is not a name.
- **Candidate backlog items** — the real specs proposed for the shadow flip and the close-gate
  spec, each with a note on why it clears the real-spec bar. Not toy work invented for the test.
- **Access inventory to revoke** — every seat, token, repo permission, environment role and vault
  policy held by the pod. This becomes `access-revocation-checklist.md` in Close.
- **Operational state at handover** — what is live, what is monitored, what is still manual, and
  any alert or incident open at the moment of transfer.
- **Known debt and open risks** — carried from the retrospective, with owners on the client side.

> **HITL GATE:** Every name in this file is a real person who has agreed. Ask the human to confirm
> each one; do not infer availability from an org chart. If a name cannot be filled in, record the
> gap explicitly — Close needs to know what is missing, not a plausible-looking list.

### `drill-record.md` (REQUIRED)

The output of Step 4, and the one proof that the pager works. One entry per critical alert, written
as the drill runs rather than reconstructed afterwards from memory.

Must contain, per critical alert:
- **The alert** — its id or name as it appears in `alert-definitions.md`
- **How it was triggered** — synthetic load, forced error, or provider test-fire, and the date
- **Detection time** — from the triggering condition to the page arriving, observed not estimated
- **Routing** — who it actually reached, and whether that is who it was supposed to reach
- **Responder and outcome** — who answered, whether `incident-response.md` was sufficient, and
  what changed as a result

An alert that has never fired is a configuration, not a control. A drill that found nothing wrong
is still worth recording as one — it is the difference between believing it works and having
watched it work.

> **If the drill genuinely did not happen**, say so *in this file*: a line reading
> `WAIVED: <name> — <reason>`. The gate accepts it and reports it, by name, in the record the
> approver signs against. A missing file still blocks. The escape is from the work, not the
> record — an exception nobody can see is how a gate stops being a gate.

### `what-healthy-table.md` (OPTIONAL)

Per failure scenario and per user journey: what healthy looks like, what degraded looks like, who is
woken, and who is merely told in the morning.

This table is the entire output of the monitoring design session, and it currently survives only if
somebody folds it into `monitoring-config.md`. Waking the wrong person at 3am is a design defect,
and this is where that design is recorded.

Must contain, per row: the scenario, the healthy signal, the degraded signal, the paging threshold,
who is paged, and who is informed without being paged.

> **Optional by design.** Its absence does not by itself mean the phase went badly, so the gate
> does not block on it — but the approver is asked about it at sign-off. Write it when the work
> happens; a receipt written later from memory is worth less than no receipt at all.

### `fatigue-review-record.md` (OPTIONAL)

Every proposed alert replayed against hypercare history, with its would-have-fired count.

An alert that fires weekly without anyone acting is not monitoring; it is training the team to
ignore the pager. This is the pass that catches it before go-live rather than three months in.

Must contain, per alert: how often it would have fired over the observed period, how many of those
warranted action, and the decision — kept, threshold raised, or cut.

> **Optional by design.** Its absence does not by itself mean the phase went badly, so the gate
> does not block on it — but the approver is asked about it at sign-off. Write it when the work
> happens; a receipt written later from memory is worth less than no receipt at all.

### `outcome-metric-first-read.md` (OPTIONAL)

The engagement's headline number, read honestly for the first time in production, with its caveats
attached.

The caveats are the artifact. A first read with no cohort caveat, no partial-period warning and no
note about what changed alongside is a number that will be quoted for a year without them.

Must contain: the number, the window, where it was read from, every caveat, and who read it with the
sponsor.

> **Optional by design.** Its absence does not by itself mean the phase went badly, so the gate
> does not block on it — but the approver is asked about it at sign-off. Write it when the work
> happens; a receipt written later from memory is worth less than no receipt at all.
## Exit Criteria
- [ ] All P0 features have at least one observable metric
- [ ] At least one alert exists for each CRITICAL failure mode
- [ ] Incident response playbook covers top 5 alert types
- [ ] Every critical alert has been fired in a drill and answered from the playbook, with the
      detection time, routing and outcome recorded in `drill-record.md`
- [ ] Project retrospective completed with actionable improvements
- [ ] Stakeholder reviewed and approved (manual gate)

## HTML Report
The phase report is generated automatically when you run `/sprd-gate` or `/sprd-next`. It is written to `.sdlc/reports/09-monitoring-report.html` and is fully self-contained — share it with stakeholders as the review artifact for the manual sign-off gate.

To regenerate at any time: `/sprd-phase-report`

## Guidance
- A metric no one watches is noise. Every dashboard must have an owner who reviews it.
- Alert fatigue kills observability. If an alert fires more than once a week non-critically, raise the threshold or eliminate it. The team that ignores alerts is the team that misses the real incident.
- Set alert thresholds from measured baselines, not intuition. "500ms feels like a good threshold" is not engineering — measure the p95 under normal load and alert at 2x.
- The retrospective is for the team, not management — write honestly or it has no value. "Everything went great" is never true and never useful.
- Technical debt logged now is managed; technical debt unlogged becomes a crisis.

## Coaching Prompts

When operating in coaching mode (`/sprd-coach`) for this phase:

### Opening (no monitoring configured)
- "What metrics matter most — latency, error rate, throughput, business KPIs?"
- "What alert thresholds make sense? When should someone get paged?"
- "What baseline measurements do you have from before this change?"

### Progress Check (some monitoring in place)
- "Monitoring configuration covers [X] metrics. Are there business-level metrics to add?"
- "Alert routing is set up for [teams]. Is that the right escalation path?"

### Ready Check (monitoring complete)
- "Monitoring is configured with baselines. Want to do a dry-run alert test?"
- "Is there a runbook for when alerts fire? Who's the first responder?"
