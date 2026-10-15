# Decision Memo
<!-- Phase 2 — Design | Optional artifact -->

> **Why this data design and not another.** The constraints the design had to satisfy, the options
> that were weighed with their evidence, a scorecard of each option against each constraint, and the
> choice — with a named human who made it. The memo records a decision; it does not gate. Owned by
> Data; the matching `decision-log.md` item carries the owner and the clock.

## Memo identity

**Feature / spec:** FE-03 · Claim status lookup
**Owner:** Dana Whitfield, Data
**Date:** 2026-10-13
**Decision-log ref:** DL-11

---

## Constraints

Number every constraint the design must satisfy (C1, C2, ...) — the Scorecard scores each option
against them. Tick a constraint once the chosen option is shown to meet it.

- [x] **C1** — The status screen shows a claim's current status within 2 seconds at the 95th percentile
- [x] **C2** — The lookup never puts load on the claims core system during its nightly batch window
- [ ] **C3** — A status change in the claims core shows on the screen within 15 minutes

---

## Options

Every option actually weighed, including the ones not chosen. `Evidence` points at what was
measured (a profile query, a benchmark, a vendor limit) — not at an opinion.

| Option | Evidence | Cost | Risk | Reversible? |
|--------|----------|------|------|-------------|
| A. Read-only view over a copy refreshed hourly | Benchmark `profiling/status_view_bench.sql:3`: p95 0.4 s over 184,206 rows | Two engineer-days; one scheduled job | Status is up to an hour old | Yes — drop the view and the job |
| B. Live query against the claims core | Core vendor limit of 20 concurrent reads, DOC-014 page 31 | One engineer-day | Breaks C2 and can slow the adjusters' workbench | Yes — remove the connection |
| C. Nightly snapshot table | Snapshot job runtime 22 min, `ops/snapshot_runs.csv:2` | Three engineer-days; one job and one table | Status is up to a day old | No — callers would be built against the snapshot's shape |

---

## Scorecard

Each option against each constraint.

| Option | C1 | C2 | C3 |
|--------|----|----|----|
| A. Hourly view | meets | meets | fails — up to 60 minutes |
| B. Live query | partly — 1.9 s at p95 in the trial, not under load | fails | meets |
| C. Nightly snapshot | meets | meets | fails — up to 24 hours |

---

## Decision

**Chosen:** Option A — a read-only view over a copy refreshed hourly

**Why:**

A is the only option that meets C1 and C2 and can be undone at no cost. It misses C3: a claimant can
see a status that is up to an hour old. We accepted that because no claimant action depends on the
status being fresher than the hour, and the product owner confirmed it. We will revisit if the refresh
can be made to run every 15 minutes within the batch window.

**Decided by:** Dana Whitfield, Data lead
