# Cadence Plan
<!-- Phase 3 — Foundation | Required artifact -->

> The standing meetings and the two numbers that run the Build loop. The constraint on parallelism
> is **checking capacity, not headcount** — never open more agent streams than the team can review
> without the queue growing.

## The week

| Meeting | Length | Replaces | Output |
|---------|--------|----------|--------|
| Flow check (daily) | 10–15 min | standup | A Checker assigned to every waiting change; vague specs flagged; WIP cap enforced (queue number first) |
| Intent triage | 60 min | refinement | Stories → ready specs; risk tiers assigned; decision lists answered |
| Retro+ | 60 min | retro | Every escaped bug answered with "which check should have caught it?"; harness backlog |
| Setup review | 30–60 min | (new) | Versioned harness changes merged; Setup Owner's deputy reviews |
| Cross-functional review (Mon/Wed/Fri) | 30 min | (new) | Sprint slate readiness, verdicts, decisions — which slated specs are NOT READY and why, which Engineering/Data verdicts are pending and for how long, which decision-log items are overdue (`/sprd-refine` renders the agenda) |

## Client cadence
- Biweekly 45-min steering: live demo in dev + outcome scorecard + decision list + gate status.
- Weekly 5-bullet async summary.
- **No activity metrics in client materials, ever.** Outcomes and demos only.

## The two numbers
- **WIP cap:** no Orchestrator runs more than **[2]** concurrent agent streams. The cap is enforced **globally**, across every sprint and every spec in flight, by `track_specs --wip-cap` — a sprint's slate is a commitment window over the backlog order, never a second WIP budget.
- **Review-wait tripwire:** halt new streams when median review wait exceeds **[one working day]**.
- Security-review wait is tracked **separately** (it clears slower and would hide in an average).
- **Sprint length:** [10 business days] — the commitment window `/sprd-sprint new` defaults to; `end` is the last business day of a window this many business days long, `start` counted as day 1 (Mon 2026-09-28 → Fri 2026-10-09).
- **Review-turnaround target:** [not set] (per lane — Engineering and Data; the sprint agenda flags verdicts waiting beyond it, and reads "no target set" when this line is left blank).

These two numbers are the project-wide default. A project with teams of very different sizes can
replace them with the per-team table below — the same limit for a 3-checker team and an
8-checker team hides the slow team's queue until reviews are days old.

## WIP Limits
<!--
  OPTIONAL — delete this section to keep the single project-wide numbers above. Read by
  scripts/track_specs.py and scripts/scorecard.py. One row per team; a team name must match an
  entry in .sdlc/team.yaml. review_alarm_hours / security_alarm_hours may be left blank — they
  default to 24 and 48 respectively, and the tools say so when a default is used.
-->

| team | wip_limit | review_alarm_hours | security_alarm_hours |
|------|-----------|---------------------|-----------------------|
| [team-name] | [N] | [hours, optional] | [hours, optional] |

## Hardening passes (scheduled, not a gating phase)
- Mid-Build: [date/trigger] — adds the test environment.
- Before Phase 8: [date/trigger] — load, E2E journeys, pen-test.
