# Data Handoff
<!-- Phase 2 — Design | Optional artifact -->

> **One page the build team reads.** What data is live and where, how to call it, what a degraded
> result means and what the caller does about it, the smoke tests that proved it, and what is still
> left. It is the data spec's last deliverable: the data work is done when the pipeline runs end to
> end on the target environment and the build team can call it. Owned by Data.

## Handoff identity

**Feature / spec:** FE-03 · Claim status lookup
**Serves:** spec 0012 — Claim status lookup screen
**Owner:** Dana Whitfield, Data

---

## What is live

Only what runs now, on the environment named — not what is planned.

| Object | Environment | Since | Owner |
|--------|-------------|-------|-------|
| serving.claim_status_v (view) | staging | 2026-10-14 | Sam Okafor |
| serving.get_claim_status (function) | staging | 2026-10-14 | Sam Okafor |
| claim_status_refresh (hourly job) | staging | 2026-10-14 | Priya Nair |

---

## How to call it

Call the function with a claim id. It returns one row, or no rows when the id does not exist. Status
text and the masked claimant name come back ready to display; do not mask them again.

```
select claim_id, claim_status, claimant_display_name, days_open, refreshed_at
from serving.get_claim_status('CLM-2026-000412');

-- one row: CLM-2026-000412 | under review | J. Whitfield | 37 | 2026-10-14 09:00:00
```

---

## Degraded results

A result that is not an error and not a full answer. The caller must be told what to do with each.

| Result | Meaning | What the caller does |
|--------|---------|----------------------|
| No rows | The claim id does not exist in the copy; it may be newer than the last refresh | Show "we cannot find that claim", and offer the lookup again in an hour |
| `refreshed_at` older than 2 hours | The hourly refresh job has stalled | Show the status with "last updated" beside it, and tell the Data owner |
| `date_of_loss` is null | The claim predates the field being required | Show "not recorded" |

---

## Smoke tests

Run `uv run pytest data/smoke/test_claim_status.py -q` against staging. It passes when the function
returns one row for each of the five claim ids the build spec's acceptance checks use. Output of the
passing run on 2026-10-14: `.sdlc/artifacts/02-design/data/smoke-output-2026-10-14.txt`

---

## What is left

- [x] Staging pipeline runs end to end and exits 0
- [ ] Promote the same objects to production — waiting on DL-12, owner Priya Nair
- [ ] Profile the adjuster note count — DL-09

---

## Owners

| Area | Owner |
|------|-------|
| Pipeline and refresh job | Priya Nair |
| Serving view and function | Sam Okafor |
| Data quality and the profile | Dana Whitfield |
