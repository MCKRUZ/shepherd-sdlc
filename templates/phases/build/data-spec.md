---
spec: "NNNN"
name: "short-kebab-name"
status: draft            # draft | ready | in-flight | merged | deferred
deferred_reason: ""      # required when status is deferred — why this spec was not built
type: data               # a data spec: the data work one build spec needs — see references/data-specs.md
serves: "NNNN"           # the build spec this data spec serves (that spec's depends_on names this one)
risk: MEDIUM             # HIGH | MEDIUM | LOW — first-class field; sets review depth. PII raises it, never lowers it
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
  A DATA spec: the data work a build spec needs, owned by the Data discipline and worked through
  /sprd-data. One data spec = one branch = one PR, exactly like any other spec. It is done when the
  end-to-end data flow runs on the target environment and the build team can call the result.

  The build spec it serves lists this spec in its `depends_on`, so the sprint layer builds this one
  first. `data_spec.py new --serves <parent>` writes both links and fills ## Context from the parent.

  This spec clears the Definition of Ready before anyone builds it. Validate with:
    uv run scripts/check_spec.py --spec specs/NNNN-short-kebab-name.md
-->

## Goal
<!-- One sentence: what data exists, where it is served from, and who calls it when this is done. -->

## Why
<!-- The reason the parent spec cannot ship without this data — the outcome, not the mechanics. -->

## Context
<!--
  The bundle /sprd-data loads FIRST: the parent spec, its acceptance checks, and every business
  rule (BR-NN), decision (DL-NN), decision record (ADR-NNN) and intake document (DOC-NNN) the
  parent cites. Written by data_spec.py from the parent; keep it current by hand when the parent
  changes. A reference that could not be found in this repository says so — never guess a path.
-->
**Serves:** spec NNNN — [path to the parent spec]

**Parent acceptance checks (read-only copy, taken YYYY-MM-DD):**
- none

**Business rules:**
- none

**Decisions:**
- none

**Decision records:**
- none

**Intake documents:**
- none

## Scope
<!-- What the data work must not touch is as load-bearing as what it must do. -->

### In scope
<!-- The source objects, transformation code, serving objects and documents this change may touch. -->
-

### Out of scope
<!-- What this change must NOT touch — the parent spec's own code, other teams' tables, production writes. -->
-

## Acceptance Checks
<!--
  The definition of done for a data spec is "the data really flows". These six are pre-seeded;
  keep them, sharpen the names, and add the parent's own data needs below them.
  Each check passes the vague-line test: two people could not build different things from it.
-->
- [ ] The pipeline runs end to end on the target environment named in `data-handoff.md` and exits 0.
- [ ] The serving object named in `data-handoff.md` returns >= 1 row for a real record the parent spec's acceptance checks use.
- [ ] `data-dictionary.md` has a row for every input the parent spec names, with null %, distinct count and min/max from a live profile query cited in that row.
- [ ] `lineage-audit.md` shows a source -> transform -> serve path for every serving object.
- [ ] The smoke tests in the integration example pass and their output is linked from `data-handoff.md`.
- [ ] Every gap in `data-readiness.md` has a `DL-NN` with an owner in `decision-log.md`.

## Deliverables
<!--
  What this spec hands the build team. Documents live in .sdlc/artifacts/02-design/data/ (workflow
  mode) or beside the repo (standalone); code lives in the data repository this project names.
  Status is one of: not started | drafted | live.
-->
| Deliverable | Where | Status |
|-------------|-------|--------|
| `data-contract.md` — fields across the boundary, PII class, source | `.sdlc/artifacts/02-design/data/` | not started |
| `data-dictionary.md` — per input: derivation, null %, distinct, min–max, median, from a live profile | `.sdlc/artifacts/02-design/data/` | not started |
| `lineage-audit.md` — source → transform → serve, build time and serve time, retention | `.sdlc/artifacts/02-design/data/` | not started |
| `data-readiness.md` — gaps with severity and `DL-NN` refs (advisory) | `.sdlc/artifacts/02-design/data/` | not started |
| `decision-memo.md` — constraints, options with evidence, scorecard, decision | `.sdlc/artifacts/02-design/data/` | not started |
| Transformation code — ETL/ELT, preparation, data logic | the data repository | not started |
| Serving code — the object the parent calls (view, function, endpoint, table) | the data repository | not started |
| Integration example with smoke tests — how the build team calls it | the data repository | not started |
| `data-handoff.md` — one page: what is live, how to call it, degraded results, what is left, owners | `.sdlc/artifacts/02-design/data/` | not started |

## Risk Tier
<!--
  HIGH | MEDIUM | LOW (must match the `risk:` frontmatter field). State why this tier.
  Challenges escalate UP, never down, without discussion. The Pod Lead owns the tier.

  A data spec that touches PII or client data is HIGH (the taxonomy in risk_model.py); so is a
  schema migration or a write to a production serving object. MEDIUM covers new transformation
  logic over established sources; LOW covers an additive view on an existing, profiled table.
-->
**Tier:** MEDIUM
**Why this tier:**

## Delegation Plan
<!-- The box the agent works inside. Set per spec. -->
- **Scope (file patterns):** <what the agent may touch; everything else is out>
- **Context (pattern to reuse):** <the one canonical pattern, named — matches `harness_context`>
- **Permissions:** <auto-allowed: build, test, lint, reads, read-only profile queries. Confirm-required: installs, network, any platform write, gated paths>
- **Gated paths touched:** <schema migrations / production serving objects / pipeline, or "none">

## Checking Plan
<!--
  How high this change climbs the checking ladder, set by the risk tier:
  LOW    — grader advisory + light human look
  MEDIUM — grader + non-author Checker
  HIGH   — full ladder: grader + correctness + security pass + named human sign-off in the PR
  The parent's `data_review` moves to accepted only when a named human records it
  (`sprint.py verdict --lane data --verdict accepted --by <name>`) — never by a tool.
-->
**Ladder depth:** MEDIUM
**Specifics:**

## Decision List
<!--
  Silent data decisions this spec leaves unwritten (what does the serving object return for a
  record with no history? which source wins when two disagree?). Each needs a NAMED human answer
  on the agreed clock — the agent must not guess. Leave "none" only if you have genuinely checked.
-->
- none
