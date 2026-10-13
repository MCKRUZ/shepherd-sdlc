# Decision Log
<!-- Phase 1 — Requirements | Optional artifact -->

> **Location:** this file lives at `.sdlc/decision-log.md` — a single, **phase-spanning** file. A
> decision opens in one phase (e.g. `DL-01` in Requirements) and closes in a later phase (e.g. Design)
> in the **same file**; it is not per-phase. `scripts/track_decisions.py` reads it to list open
> decisions and flag any past its clock, and `/sprd-status` surfaces them.

Owned by **Product**. The decision log captures **cross-cutting product decisions** that must be made
before specs exist — the ones an agent must not silently guess. Each open decision gets a **named
owner** and a **2-business-day clock** (weekend-aware): `due` is two business days after `opened`.

This is distinct from a spec's per-spec **Decision List**, which captures silent decisions *inside one
spec*. Spec-scoped vs phase-scoped — they don't overlap; a phase decision here can later seed a spec's
Decision List when it is specced.

The agent **proposes** a decision and its owner; a **named human** decides — it never answers a
`DL-NN` itself. When a decision closes, set its status to `decided` and record the resolution (and who
decided) in the phase that closed it.

---

| id    | decision                                   | owner        | opened       | due (2 business days) | status |
|-------|--------------------------------------------|--------------|--------------|-----------------------|--------|
| DL-01 | [the open question a human must decide]     | [name/role]  | [YYYY-MM-DD] | [YYYY-MM-DD]          | open   |

*Add one row per decision. `status` is `open` or `decided`.*
