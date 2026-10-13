---
spec: "NNNN"
name: "short-kebab-name"
status: draft            # draft | ready | in-flight | merged | deferred
deferred_reason: ""      # required when status is deferred — why this spec was not built
type: feature            # feature | bugfix — a bugfix PR carries the `type:bugfix` label and
                         # must pass repro-gate: its new test FAILS against the pre-fix code
risk: MEDIUM             # HIGH | MEDIUM | LOW — first-class field; sets review depth
source: "—"              # the story / REQ-id this spec realizes, or — if standalone
channel: ""              # optional — delivery surface (see channels/); blank = channel-agnostic
owner: ""                # the named human accountable for intent and decisions (DoR requires this)
developer: ""            # who drives the agent and approves the plan — filled at hand-off
checker: ""              # non-author approval — filled at hand-off
team: ""                 # the team this spec belongs to (see .sdlc/team.yaml, if present)
harness_context: ""      # the ONE existing pattern this change reuses (DoR requires this named)
created: "YYYY-MM-DD"
sprint: ""               # optional — sprint id (e.g. S07); written by /sprd-sprint slate, never by hand
next_owner: ""           # optional — who holds the next action; set by `handoff`, cleared by `ack`
eng_review: ""           # optional — pending | accepted | returned; Engineering verdict, recorded by name
data_review: ""          # optional — pending | accepted | returned | n-a (n-a needs a reason); Data verdict
depends_on: ""           # optional — comma-separated spec ids this spec builds on, e.g. "0007,0009"
---

# Spec NNNN — <title>

<!--
  The durable per-change record of the Build loop. One spec = one branch = one PR.
  No spec, no build. The agent re-reads this every session; the grader grades against it;
  when behavior changes later, this file changes in the same PR. A stale spec is a lie.

  This spec clears the Definition of Ready before anyone builds it. Validate with:
    uv run scripts/check_spec.py --spec specs/NNNN-short-kebab-name.md
-->

## Goal
<!-- One sentence: what capability exists when this is done. -->

## Why
<!-- The reason this change matters — the outcome, not the mechanics. -->

## Scope
<!-- What the change must not touch is as load-bearing as what it must do. -->

### In scope
<!-- The file patterns / areas this change may touch. -->
-

### Out of scope
<!-- What this change must NOT touch. "Stop and ask" if something here needs to change. -->
-

## Acceptance Checks
<!--
  Each check is testable and passes the vague-line test:
  "Could two people build different things from this line?" If yes, it is a wish, not a check.
  WISH:  "handle errors gracefully"
  CHECK: "a duplicate submission returns 409 with body { \"error\": \"duplicate claim\" }"
-->
- [ ]

## Risk Tier
<!--
  HIGH | MEDIUM | LOW (must match the `risk:` frontmatter field). State why this tier.
  Challenges escalate UP, never down, without discussion. The Pod Lead owns the tier.

  HIGH   — auth/identity, payments, PII/client data, schema migrations, public API contract
           changes, IaC/pipeline changes, prompt/model/tool-definition changes, anything hard
           to undo. Triggers: tight permissions, full checking ladder, security pass, named sign-off.
  MEDIUM — new business logic, external integrations, changes to shared internal services.
           Triggers: standard permissions, grader + human Checker.
  LOW    — UI within existing patterns, copy, internal tooling, additive CRUD on established rails.
           Triggers: lighter review; grader + mechanical gates still run.
-->
**Tier:** MEDIUM
**Why this tier:**

## Delegation Plan
<!-- The box the agent works inside. Set per spec. -->
- **Scope (file patterns):** <what the agent may touch; everything else is out>
- **Context (pattern to reuse):** <the one canonical pattern, named — matches `harness_context`>
- **Permissions:** <auto-allowed: build, test, lint, reads. Confirm-required: installs, network, gated paths>
- **Gated paths touched:** <auth / migrations / infra / pipeline, or "none">

## Checking Plan
<!--
  How high this change climbs the checking ladder, set by the risk tier:
  LOW    — grader advisory + light human look
  MEDIUM — grader + non-author Checker
  HIGH   — full ladder: grader + correctness + security pass + named human sign-off in the PR
-->
**Ladder depth:** MEDIUM
**Specifics:**

## Decision List
<!--
  Silent product decisions this story leaves unwritten (fail open or closed? what does a blocked
  user see?). Each needs a NAMED human answer on the agreed clock — the agent must not guess.
  Leave "none" only if you have genuinely checked there are none.
-->
- none
