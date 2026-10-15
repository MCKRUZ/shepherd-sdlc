# Decision Memo
<!-- Phase 2 — Design | Optional artifact -->

> **Why this data design and not another.** The constraints the design had to satisfy, the options
> that were weighed with their evidence, a scorecard of each option against each constraint, and the
> choice — with a named human who made it. The memo records a decision; it does not gate. Owned by
> Data; the matching `decision-log.md` item carries the owner and the clock.

## Memo identity

**Feature / spec:** [FE-NN · spec name]
**Owner:** [Data — name]
**Date:** [YYYY-MM-DD]
**Decision-log ref:** [DL-NN]

---

## Constraints

Number every constraint the design must satisfy (C1, C2, ...) — the Scorecard scores each option
against them. Tick a constraint once the chosen option is shown to meet it.

- [ ] **C1** — [a requirement the design must satisfy, stated so it can be checked]
- [ ] **C2** — [...]

---

## Options

Every option actually weighed, including the ones not chosen. `Evidence` points at what was
measured (a profile query, a benchmark, a vendor limit) — not at an opinion.

| Option | Evidence | Cost | Risk | Reversible? |
|--------|----------|------|------|-------------|
| [option name] | [what was measured, and where it is recorded] | [build and run cost, in the units the team uses] | [what could go wrong] | [yes / no — and what undoing it takes] |
| [...] | [...] | [...] | [...] | [...] |

---

## Scorecard

Each option against each constraint.

| Option | C1 | C2 |
|--------|----|----|
| [option name] | [meets / partly / fails] | [meets / partly / fails] |
| [...] | [...] | [...] |

---

## Decision

**Chosen:** [the option, by name]

**Why:**

[Two or three sentences: which constraints decided it, what was traded away, and what would make
the team revisit.]

**Decided by:** [Name, role — a named human, never an agent]
