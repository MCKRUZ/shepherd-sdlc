# Data Dictionary
<!-- Phase 2 — Design | Optional artifact -->

> What each input to this feature **actually is** — measured, not believed. One row per input:
> where it comes from, how it is derived, and what a profile of the real data showed (null rate,
> distinct count, range, median). Every number cites the profile query (or `file:line`) it came from;
> a value nobody measured reads `not measured`, never `0`. Owned by Data; pairs with `data-contract.md`.

## Dictionary identity

**Feature / spec:** [FE-NN · spec name]
**Serves:** [spec NNNN — the build spec this data work serves]
**Profiled on:** [YYYY-MM-DD · environment the profile ran against]
**Profile source:** [where the profile queries live — a notebook, a SQL file, a dashboard]

---

## Inputs

One row per input the build spec names. `Null %`, `Distinct`, `Min–max` and `Median` come from a
**live profile query** whose text (or `file:line`) goes in `Profile query` — a number with no query
behind it is a belief, not a measurement. A value nobody measured reads `not measured`, never `0`
and never blank. A statistic that cannot apply to the column's type (a median of text) is a dash.

| Input | Source object | Derivation | Null % | Distinct | Min–max | Median | Profile query |
|-------|---------------|------------|--------|----------|---------|--------|---------------|
| [input name] | [table / view / file it is read from] | [direct, or the expression that derives it] | [e.g. 3.2 — or `not measured`] | [count — or `not measured`] | [lowest – highest — or `not measured`] | [value — or `not measured`] | [query text, or `file:line`] |
| [...] | [...] | [...] | [...] | [...] | [...] | [...] | [...] |

---

## Serving objects

What the build team reads from. One row per object this feature serves its data through.

| Object | Kind | Grain | Keys | Refresh |
|--------|------|-------|------|---------|
| [object name] | [view / function / endpoint / table] | [one row per what] | [the key columns a caller filters on] | [e.g. hourly, on write, nightly] |
| [...] | [...] | [...] | [...] | [...] |

---

## Notes

[Anything a reader needs to read the numbers correctly: how the sample was drawn, columns that were
skipped and why, surprises the profile turned up, and anything that is `not measured` yet with the
decision-log item that will measure it.]
