# Data Dictionary
<!-- Phase 2 — Design | Optional artifact -->

> What each input to this feature **actually is** — measured, not believed. One row per input:
> where it comes from, how it is derived, and what a profile of the real data showed (null rate,
> distinct count, range, median). Every number cites the profile query (or `file:line`) it came from;
> a value nobody measured reads `not measured`, never `0`. Owned by Data; pairs with `data-contract.md`.

## Dictionary identity

**Feature / spec:** FE-03 · Claim status lookup
**Serves:** spec 0012 — Claim status lookup screen
**Profiled on:** 2026-10-12 · staging warehouse, claims schema (copy of production taken 2026-10-11)
**Profile source:** `profiling/claim_status_profile.sql`, run from the data team's notebook

---

## Inputs

One row per input the build spec names. `Null %`, `Distinct`, `Min–max` and `Median` come from a
**live profile query** whose text (or `file:line`) goes in `Profile query` — a number with no query
behind it is a belief, not a measurement. A value nobody measured reads `not measured`, never `0`
and never blank. A statistic that cannot apply to the column's type (a median of text) is a dash.

| Input | Source object | Derivation | Null % | Distinct | Min–max | Median | Profile query |
|-------|---------------|------------|--------|----------|---------|--------|---------------|
| claim_id | claims.claim | direct | 0.0 | 184,206 | CLM-2019-000001 – CLM-2026-041877 | — | `profiling/claim_status_profile.sql:4` |
| claim_status | claims.claim | direct | 0.0 | 5 | closed – under review | — | `profiling/claim_status_profile.sql:11` |
| date_of_loss | claims.claim | direct | 1.4 | 2,611 | 2019-01-03 – 2026-10-09 | 2023-05-18 | `profiling/claim_status_profile.sql:19` |
| days_open | claims.claim | `current_date - opened_on` where status is not closed | 0.0 | 412 | 0 – 1,184 | 37 | `profiling/claim_status_profile.sql:27` |
| adjuster_notes_count | claims.claim_note | `count(*)` grouped by claim_id | not measured | not measured | not measured | not measured | DL-09 will profile it once the note table is in staging |

---

## Serving objects

What the build team reads from. One row per object this feature serves its data through.

| Object | Kind | Grain | Keys | Refresh |
|--------|------|-------|------|---------|
| serving.claim_status_v | view | one row per claim | claim_id | hourly |
| serving.get_claim_status | function | one row per claim_id passed in | claim_id | on call |

---

## Notes

The profile ran over every row in staging, not a sample. `claimant_name` and `policy_number` were
left out on purpose: they are personal data and the lookup reads only their masked forms from the
view, so a raw profile of them would put personal data in a document that is committed. 1.4% of
`date_of_loss` is null, all on claims opened before 2020-03 when the field was optional; the screen
shows "not recorded" for those. `adjuster_notes_count` reads `not measured` — the note table is not
in staging yet, and DL-09 owns getting it there.
