---
spec: "0043"
name: "claims-profile"
status: ready
type: data
serves: "0042"
risk: HIGH
owner: "@MCKRUZ"
developer: "@sam-k"
checker: "@priya-n"
team: "claims"
harness_context: "the existing claims_gold.daily_claims serving view"
created: "2026-09-25"
depends_on: ""
---

# Spec 0043 — Serve the claim history the duplicate check reads

## Goal

A `claims_gold.claim_history` view exists on the production workspace, keyed by `claim_id`, so
the duplicate-claim check in spec 0042 can ask whether a claim was already processed.

## Why

The duplicate check cannot ship against a table nobody has profiled: today the only history
sits in two bronze tables with different `claim_id` formats, and the build team would otherwise
guess which one is the truth.

## Context

**Serves:** spec 0042 — `specs/0042-duplicate-claim-409.md`

**Parent acceptance checks (read-only copy, taken 2026-09-25):**
- [ ] A duplicate submission returns 409 with body `{ "error": "duplicate claim" }`
- [ ] Two concurrent submissions of the same claim_id persist exactly 1 row

**Business rules:**
- BR-03 — `.sdlc/artifacts/01-requirements/business-rules.md`

**Decisions:**
- DL-07 — `.sdlc/decision-log.md`

**Decision records:**
- none

**Intake documents:**
- DOC-004 — `.sdlc/context/intake/DOC-004-claims-platform.md`

## Scope

### In scope
- The two bronze claim tables, read only
- The `claims_gold.claim_history` view and its profile notebook

### Out of scope
- The claims submission endpoint — spec 0042 owns it
- Any write to a bronze table

## Acceptance Checks
- [ ] The pipeline runs end to end on the target environment named in `data-handoff.md` and exits 0.
- [ ] The serving object named in `data-handoff.md` returns >= 1 row for a real record the parent spec's acceptance checks use.
- [ ] `data-dictionary.md` has a row for every input the parent spec names, with null %, distinct count and min/max from a live profile query cited in that row.

## Deliverables
| Deliverable | Where | Status |
|-------------|-------|--------|
| `data-contract.md` — fields across the boundary, PII class, source | `.sdlc/artifacts/02-design/data/` | drafted |
| `data-handoff.md` — one page: what is live, how to call it | `.sdlc/artifacts/02-design/data/` | not started |

## Risk Tier

**Tier:** HIGH
**Why this tier:** claim history carries member identifiers, which is personal data, and the view
is read on the money path.

## Delegation Plan
- **Scope (file patterns):** the data repository's `gold/claims/**` only
- **Context (pattern to reuse):** the existing `claims_gold.daily_claims` view and its profile notebook
- **Permissions:** reads and read-only profile queries auto-allowed; creating the view needs confirming
- **Gated paths touched:** production serving objects

## Checking Plan

**Ladder depth:** HIGH
**Specifics:** every mechanical check, the grader, a correctness review, a security pass on the
member-identifier columns, and a named human sign-off in the pull request; Priya records the
parent's data verdict.

## Decision List
- **Which bronze table wins when the two disagree on a claim's status?** Resolved by Matt: the
  adjudication table, because the intake table is never updated after submission.
