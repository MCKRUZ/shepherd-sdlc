# Data Handoff
<!-- Phase 2 — Design | Optional artifact -->

> **One page the build team reads.** What data is live and where, how to call it, what a degraded
> result means and what the caller does about it, the smoke tests that proved it, and what is still
> left. It is the data spec's last deliverable: the data work is done when the pipeline runs end to
> end on the target environment and the build team can call it. Owned by Data.

## Handoff identity

**Feature / spec:** [FE-NN · spec name]
**Serves:** [spec NNNN — the build spec that calls this]
**Owner:** [Data — name]

---

## What is live

Only what runs now, on the environment named — not what is planned.

| Object | Environment | Since | Owner |
|--------|-------------|-------|-------|
| [object name — view / function / endpoint / table] | [environment it runs on] | [YYYY-MM-DD] | [who to ask when it breaks] |
| [...] | [...] | [...] | [...] |

---

## How to call it

[How the build team reaches the data: the object, the arguments, and what comes back. Include one
runnable code example they can paste.]

```
[a runnable call, and the shape of what it returns]
```

---

## Degraded results

A result that is not an error and not a full answer. The caller must be told what to do with each.

| Result | Meaning | What the caller does |
|--------|---------|----------------------|
| [e.g. empty set / stale value / partial row] | [what the data layer is telling you] | [show, retry, fall back, or escalate] |
| [...] | [...] | [...] |

---

## Smoke tests

[The command that runs the smoke tests, and a link to the output of the run that passed — a path or
URL a reader can open.]

---

## What is left

- [ ] [anything not yet live, not yet measured, or waiting on a decision — with its `DL-NN`]

---

## Owners

| Area | Owner |
|------|-------|
| [pipeline / serving object / data quality] | [name] |
| [...] | [...] |
