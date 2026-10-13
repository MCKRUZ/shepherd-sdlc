# Sprint Model — a commitment window over the backlog order

A **sprint** is a named, two-week **commitment window** over the spec backlog: a human slates a *count*
of specs by a *mix of work* (risk tiers), readies the sprint once every slated spec clears the Definition
of Ready and its Engineering and Data verdicts, and closes it with **kept / carried / dropped**, each with a
name and a reason. It is never a second backlog, never a gate, and never gated.

This is a **Tier-3 reference**: loaded on demand, product-agnostic, and read by nothing at runtime. The
executable half is `scripts/sprint_model.py` (pure arithmetic — the single source of truth for every rule
below), `scripts/sprint.py` (the `/sprd-sprint` CLI) and `scripts/generate_sprint_report.py` (the
planning and review pages). `/sprd-refine` drives the slated specs to READY and records the verdicts.

---

## Lifecycle and states

The sprint record lives at `.sdlc/sprints/SNN.md` (template `templates/phases/build/sprint.md`). Its id is
human-typed and must match `^S\d{2,}$` (`S07`, `S12`, `S100`) so several repos can share one convention.

| State | Entered by | Meaning | Leaves via |
|---|---|---|---|
| `planning` | `new` | The record exists; specs are being slated and refined | `ready` |
| `ready` | `ready --by <name>` | Every slated spec passed the ready rule; the planning page is written | `close` |
| `closed` | `close --by <name>` | Outcomes recorded; the review page is written | — (terminal) |

States move **forward only** and only on a human's verb. Nothing moves a sprint on a timer, and nothing in
`.sdlc/state.yaml` is written by any sprint verb.

| Moment in the two-week rhythm | Verbs | Who |
|---|---|---|
| Setting up the next sprint (last week of the current one) | `new`, `slate`, `unslate` | Product proposes and confirms the slate |
| Sprint planning meeting (day 0) | `ready`; `plan` re-renders the page on demand | a named human readies it; the team walks the page |
| Every day (the flow check) | `status` | anyone |
| Whenever work changes hands | `handoff`, `ack` | recorder and recipient |
| Last day (sprint review and Retro+) | `close` | a named human confirms every carry and drop |

The sprint's `start` and `end` are ISO dates; `end` defaults to the **last business day of a
10-business-day window** that starts on `start` — start counts as day 1, so Mon 2026-09-28 ends Fri
2026-10-09 (weekends excluded, via `track_decisions.add_business_days`). `status` counts the window
inclusively: on the last day one business day remains. `board_ref` (e.g. "ADO Iteration 6") is a manual
mapping for humans — nothing reads it, and nothing touches a board.

## The slate and the mix

| Field | Values | Rule |
|---|---|---|
| `target` | integer | how many specs to slate — a **count of items, never a size** |
| `mix` | `"HIGH:1,MEDIUM:2,LOW:3"` | by **risk tier**, the axis that sets checking depth; counts must sum to `<= target`; unknown tiers, negative or repeated counts are rejected |

`slate` with no specs **proposes** a slate and writes nothing: candidates are specs with `status: ready`
or `draft`, no `sprint:`, and not merged or in-flight; each tier bucket is filled in spec-id (backlog)
order up to its mix count, then any remaining slots by id, never exceeding `target`. A human confirms or
edits the set; only then is `sprint:` written on each spec.

| Situation at `slate` | Behaviour |
|---|---|
| Slate would exceed `target` | **exit 1** unless `--override --reason <text>` (the reason is recorded in the ledger) |
| Slate breaches the mix (over, under, or a tier with no target) | **warning only** — the mix is advisory |
| A slated spec's `depends_on` names a spec that is neither merged nor in this slate | **warning**, with the suggestion to pull the dependency in |
| A spec is merged, or already in another sprint | refused for that spec (exit 1) |

`status` shows the mix as **actual vs target** per tier. A tier with no target reads "no target", never a
fabricated 0. WIP is reported against the cap from `cadence-plan.md`; the cap itself is enforced globally
by `track_specs --wip-cap`, never per sprint.

## The ready rule

`ready --sprint SNN --by <name>` is **conjunctive**. Every slated spec must satisfy all of:

| Check | Source | Gap wording |
|---|---|---|
| Definition of Ready is READY (no failed MUST finding) | `check_spec.check_spec_text` | `DoR: NOT READY (<blocking findings>)` |
| `status` at least `ready` (`ready`, `in-flight` or `merged` — only `draft` falls short) | spec frontmatter (hand-moved, as today) | `status is draft, not ready` |
| `eng_review: accepted` | Engineering verdict, recorded by name | `eng_review is pending, needs accepted` |
| `data_review: accepted` or `n-a` | Data verdict, recorded by name; `n-a` only from the data lane and only with a reason | `data_review is not recorded, needs accepted or n-a` |
| No dependency cycle inside the slate | `check_dependencies.detect_cycles` | `<id>: dependency cycle: A -> B -> A` |
| No `depends_on` pointing outside the slate at an unmerged spec | spec frontmatter | `<id>: depends on X (status draft), which is outside the slate and not merged` |

If any spec has a gap, `ready` exits 1 and lists every gap per spec — it never rounds a partial slate to
ready. An empty slate is itself a gap. On success it sets `state: ready`, records `readied_by`, appends a
`ready` event, and writes the **planning page**. The ready rule checks only the slate — never gates G1–G7.

## Dependencies and build order

`depends_on` holds comma-separated spec ids (`"0007,0009"`). From it, `status` derives an **advisory**
build order and a **next up** suggestion; the human picks.

| Step | Rule |
|---|---|
| 1. Dependencies first | topological order over `depends_on` within the slate (`check_dependencies.topological_sort`) |
| 2. Unblocks the most others | among specs whose dependencies are done, the one with the most transitive dependents in the slate goes first |
| 3. HIGH → MEDIUM → LOW | the longest checking ladder starts first |
| 4. Spec id | backlog order settles what is left |

**Next up** is the first spec in that order whose DoR is READY, whose `status` is `ready`, whose
dependencies are all merged, and — when a WIP cap is given — only while the in-flight count is below the
cap (otherwise "none": the queue is full, not the backlog). A cycle is reported as a ready gap, never
silently reordered.

## The five spec keys

`sprint.py` inserts the keys after the `status:` line on first write (or right after the opening `---`).
Values hold only enumerations, names, and spec ids — a writer refuses `#`, quotes, newlines, and any
placeholder token — so `check_spec`'s frontmatter parsing and DoR verdict are unchanged before and after.

| Key | Values | Written by | Read by |
|---|---|---|---|
| `sprint` | `""` or `SNN` | `slate`, `unslate`, `close --carry-to` | `track_specs` (`by_sprint`, `--sprint`), `status`, `/sprd-refine` |
| `next_owner` | a name, or `""` | `handoff --to`; cleared by `ack` | `status` (unacknowledged handoffs with business-day age), the agenda |
| `eng_review` | `pending \| accepted \| returned \| n-a` | `verdict --lane eng` (via `/sprd-refine validate`) | the ready rule |
| `data_review` | `pending \| accepted \| returned \| n-a` | `verdict --lane data` (`n-a` needs `--reason`) | the ready rule |
| `depends_on` | `""` or `"0007,0009"` | `/sprd-refine` proposes, a human confirms; `slate` may add | build order, next up, slate warning, ready gap |

`status` (draft → ready → in-flight → merged) is **not** one of them: it stays the protected, hand-moved
field, and no sprint verb writes it. Only files whose basename matches `^\d{4}-` are ever listed or written,
so the installed `specs/spec-template.md` is never touched.

## The ledger

`.sdlc/metrics/sprint-log.jsonl` is append-only, one JSON object per line, `ts` in full ISO (UTC). Every
write verb writes the spec frontmatter first, then the ledger line; if the append fails it prints `DRIFT`
and exits 1 so the two can be reconciled by hand.

| `event` | Fields | Emitted by |
|---|---|---|
| `sprint_new` | `sprint, by` | `new` (`--by` is required, like every write) |
| `slated` / `unslated` | `sprint, spec, by, reason?` | `slate` / `unslate` |
| `handoff` / `ack` | `spec, to?, by` | `handoff` / `ack` |
| `verdict` | `spec, lane: eng \| data, verdict, by, reason?` | `verdict` |
| `ready` / `closed` | `sprint, by` | `ready` / `close` |
| `carried` / `dropped` | `sprint, spec, to_sprint?, by, reason` | `close` |

Ages shown by `status` come from the ledger: a pending verdict is aged from the spec's latest `slated`
event, an unacknowledged handoff from its latest `handoff`. Any field whose key names an activity metric
is refused before anything is written (see the metrics policy).

## Close

`close --sprint SNN --by <name>` derives **kept** (specs with `status: merged`) versus **open**. Every open
spec must be named in a `--carry SPEC=REASON` (with `--carry-to SNN`, which rewrites its `sprint:`) or a
`--drop SPEC=REASON` (which clears `sprint:`); an undecided open spec exits 1 by name. The `## Close`
table (`| spec | outcome | by | reason |`) is written into the sprint record, `state: closed` and
`closed_by` are set, `carried` / `dropped` / `closed` events are appended, and the **review page** is
rendered. `close` never suggests advancing a phase.

## The planning and review pages

Both are self-contained HTML in the visual language of the phase reports, written to `.sdlc/reports/` and
linked from `index.html` between idempotent `<!-- sprints:start -->` / `<!-- sprints:end -->` markers.

| Page | Written | Sections |
|---|---|---|
| `sprint-SNN-planning.html` | by `ready`; re-rendered on demand by `plan` (before `ready`, to run the meeting from a draft that still shows the gaps) | header (id, goal, start → end, board ref, readied by); commitment table; mix and capacity; build order and next up; dependencies; one spec card per slated spec (Goal, Why, acceptance-check count, tier and why, harness context, Decision List); open decisions; carried in; footer |
| `sprint-SNN-review.html` | by `close` | the same, plus the `## Close` outcomes and the ledger's carry / drop reasons |

Every empty section reads **"no data"**. The footer always carries the standard's guardrail: *Never
tracked: velocity, story points, PR count, lines of code.*

## What "doesn't lock the gates" means

| Guarantee | How the layer keeps it |
|---|---|
| Refinement runs in **any phase** where specs exist | no sprint verb reads `current_phase`; standalone `--repo` mode needs no `.sdlc/` at all |
| An upstream gap is fixed **without regressing the phase** | `/sprd-refine --upstream` edits the Phase 1/2 artifact in place (human-confirmed diff), records it to the artifact ledger, re-gates that phase with `check_gates.py --phase N` as information, and regenerates that phase's layer; `current_phase` never moves |
| Earlier-phase artifacts are **expected to change** during refinement, and layers follow them | Phase layers are living summaries, not locks: regenerated when a source changes, previous version kept as `.superseded-<date>`, regeneration recorded as `refreshed` (see `references/frozen-layers.md`) |
| A sprint is **never a gate and never gated** | every read verb exits 0; `ready` and `close` check only the slate, never G1–G7; nothing writes `.sdlc/state.yaml` |
| Leaving Build stays a **human declaration** | `close` never suggests advancing; `/sprd-next` gains one advisory line |
| The protected core is **byte-for-byte unchanged** | `check_spec.py`, `check_gates.py`, `advance_phase.py`, `phase_model.py`, the registry, `new_spec.py`, `scorecard.py`, `harness/**`, `/sprd-coach`, `/sprd-spec` are imported from, never edited |
| **Standalone or workflow** | `--state <.sdlc/state.yaml>` or `--repo <path>`; workflow mode is detected by `state.yaml` presence, never by a bare `.sdlc/` directory |

## Metrics policy

| Shown (this sprint only; "no data" when empty) | Refused |
|---|---|
| slated / ready / not-ready counts; kept / carried / dropped at close, each with a named human and a reason | velocity, story points, estimates, effort, hours, capacity — `FORBIDDEN_FIELDS`, exit 2 |
| pending verdicts and unacknowledged handoffs with business-day age | PR count, commit count, lines of code — never computed |
| mix actual vs target; WIP vs cap | any per-person aggregation — no such key exists in any JSON |
| carry-over recurrence per spec (the only cross-sprint number, in `/sprd-retro`) | cross-sprint trends of kept / carried counts ("velocity with the points removed") |
| overdue decision-log items | "% complete" as a sprint number; fabricated zeros |

`FORBIDDEN_FIELDS` is a superset of `scorecard.FORBIDDEN_TYPES`, so a metric the scorecard refuses cannot
re-enter through the sprint's side door. A `--by` name that looks like an AI actor is refused too — as
labelling, not enforcement: the standard wants a named human behind every commitment.
