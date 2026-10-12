# /sdlc-sprint — Slate, Ready, and Close a Sprint

Run a two-week sprint as a **commitment window over the backlog order**: create the sprint record,
slate a *count* of specs by risk-tier mix, watch the slate's readiness every day, mark the sprint
**ready** once every slated spec clears the Definition of Ready and its Engineering and Data verdicts,
and close it with kept / carried / dropped — each carry or drop by a named human, with a reason. The
layer is additive and advisory: it never gates, is never gated, never moves a phase, and never writes
`state.yaml`. Works inside an SDLC project or standalone against any repo with a `specs/` directory.

The command owns `sprint.py`; the user never calls it directly. The pure rules (mix, ready rule, build
order, forbidden metrics) live in `references/sprint-model.md`; the record template is
`templates/phases/build/sprint.md`.

## When it runs

`/sdlc-sprint` is not one moment. Different verbs belong to different points in the two-week rhythm:

| Moment | Verbs | Who | Companion |
|---|---|---|---|
| **Setting up the next sprint** — the current sprint's last week, at the Mon/Wed/Fri review | `new`, `slate`, `unslate` | Product proposes and confirms the slate | `/sdlc-refine --sprint` drives the slated specs to READY and records the Eng/Data verdicts |
| **Sprint planning meeting** — day 0 | `ready` (writes the planning page); `plan` re-renders it on demand | a named human readies it; the team walks the page | the page is the meeting's agenda and record |
| **Every day** — the flow check | `status` *(default)* | anyone | `/sdlc-refine` (no arguments) for the refinement agenda |
| **Whenever work changes hands** | `handoff`, `ack` | the recorder and the recipient | — |
| **Last day** — sprint review and Retro+ | `close` (writes the review page) | a named human confirms every carry and drop | `/sdlc-retro` for the cross-sprint patterns |

## Instructions

1. **Resolve mode and repo root:**
   - **Workflow mode** (default): look for `.sdlc/state.yaml`; pass `--state .sdlc/state.yaml` to
     every call. The repo root is the directory containing `.sdlc/`; specs are `<repo>/specs/*.md`.
   - **Standalone mode** (`--repo <path>`, or no `.sdlc/state.yaml` found): pass `--repo <path>`.
     The sprint record and ledger are created under `<repo>/.sdlc/sprints/` and
     `<repo>/.sdlc/metrics/sprint-log.jsonl`; the output notes the missing engagement context
     (`standalone mode — no .sdlc/state.yaml; engagement context not shown`). A bare `.sdlc/`
     directory without `state.yaml` is still standalone.
   - Every example below shows `--state .sdlc/state.yaml`; substitute `--repo <path>` in standalone
     mode. The two flags are mutually exclusive.

2. **Pick the verb.** No argument means `status`. The sprint id is human-typed and must match
   `S` + two or more digits (`S07`, `S12`); with `--sprint` omitted the *active* sprint is used (the
   highest-numbered sprint not yet closed; when every sprint is closed, the highest-numbered closed
   one — its `status` shows the slate that was reviewed, replayed from the ledger, with `closed by`
   instead of days remaining and a pointer to its review page).

3. **`new` — create the sprint record in `planning`.**

   > **HITL GATE:** Use `AskUserQuestion` to confirm the four planning inputs before writing anything:
   > the **goal** (one outcome-shaped sentence — what is true when the sprint ends, not a list of
   > tickets), the **start date** (the end defaults to the last business day of a 10-business-day
   > window — start is day 1, so Mon 2026-09-28 ends Fri 2026-10-09; `--end` or `--days` override), the **target** (how many specs to slate — a count of items, never a size or an
   > estimate), and the **mix** by risk tier (e.g. `HIGH:1,MEDIUM:2,LOW:3`; counts sum to at most the
   > target). Offer `--board-ref` for a manual board mapping such as "ADO Iteration 6" — nothing reads
   > it; the team updates the board by hand.

   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py new \
     --state .sdlc/state.yaml --sprint S07 --goal "<outcome sentence>" --start 2026-10-05 \
     --target 6 --mix "HIGH:1,MEDIUM:2,LOW:3" --board-ref "ADO Iteration 6" --by "<name>"
   ```
   Exit 1 on a bad id, a bad mix, an end before the start, or an id that already has a record (one
   record per sprint, ever). The record lands at `.sdlc/sprints/S07.md`, rendered from
   `templates/phases/build/sprint.md`.

4. **`slate` — propose, then confirm.** Run it first **without** `--spec`: this prints a proposal and
   writes nothing. Candidates are specs with `status: ready | draft` and an empty `sprint:`; the
   proposal fills each risk-tier bucket in spec-id (backlog) order up to the mix, then the remaining
   slots by id, never exceeding the target. Specs already in this sprint count against the target.
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py slate \
     --state .sdlc/state.yaml --sprint S07
   ```
   Add `--json` to get `{sprint, target, mix, already_slated, candidates, proposal, mix_after,
   mix_warnings, dependency_warnings}` for a table.

   > **HITL GATE:** Show the proposal as a table (spec, name, risk, type, status, DoR) and ask with
   > `AskUserQuestion`: "Slate these N specs into S07? Edit the set (add or remove ids), or confirm."
   > The agent proposes the set; a named human confirms it. If a proposed spec's `depends_on` names a
   > spec that is neither merged nor in the slate, say so and **offer to pull the dependency in**.

   Then write the confirmed set — `--by` is required on the confirm:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py slate \
     --state .sdlc/state.yaml --sprint S07 --by "<name>" --spec 0007 --spec 0009 --spec 0012
   ```
   Rules the script enforces: each spec must exist (only files named `NNNN-*.md` are specs — the
   installed `specs/spec-template.md` is never listed or written), must not be `merged`, and must not
   sit in another sprint (exit 1). A slate **over the target exits 1** unless the human gives
   `--override --reason "<why>"` (the reason lands on the ledger). A **mix breach warns only**; so does
   a `depends_on` pointing outside the slate at an unmerged spec. On first touch the script inserts the
   five optional keys (`sprint`, `next_owner`, `eng_review`, `data_review`, `depends_on`) after
   `status:` — the spec body is byte-identical and `check_spec`'s verdict is unchanged.

   To take a spec back out (reason required, recorded):
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py unslate \
     --state .sdlc/state.yaml --sprint S07 --spec 0012 --by "<name>" --reason "<why it leaves>"
   ```

5. **`status` — the daily flow check (default; read-only, exit 0 always).**
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py status \
     --state .sdlc/state.yaml --sprint S07
   ```
   Show the output as it comes: the header (`Sprint S07 — "goal"`, state, window, target, mix,
   business days remaining), the **Slate** table (spec, name, risk, type, status, DoR, eng, data, next
   owner), **Readiness** (N of M ready, with each spec's gaps against the ready rule), **Verdicts**
   pending with business-day age, **Handoffs** unacknowledged with age, **Mix** actual vs target
   (`no target` when the mix lacks a tier — never a fabricated 0), **WIP** in-flight vs cap, open and
   overdue **Decisions** (`DL-NN`), the **Build order** and **Next up**, and the footer `ready when: …`.

   The build order is advisory: dependencies first (topological by `depends_on`), then the spec that
   unblocks the most others, then HIGH → MEDIUM → LOW (the longest checking ladder starts first), then
   spec id. **Next up** is the first spec in that order that is READY, has `status: ready`, whose
   dependencies are merged, and that fits under the WIP cap. The human picks; the script suggests.

   The WIP cap comes from `--wip-cap N`, else the bold value on the `WIP cap` line of
   `.sdlc/artifacts/*/cadence-plan.md`, else reads `cap not set`. For a dashboard or the refinement
   agenda use `--json` — its shape is exactly `sprint.build_view(...)`, and it contains **no
   per-person aggregation key** by construction. An unknown or malformed sprint id reads `no data`.

6. **`handoff` / `ack` — own the wait.** Never rely on the next owner noticing.
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py handoff \
     --state .sdlc/state.yaml --spec 0007 --to "<recipient name>" --by "<recorder name>" --note "<what is needed>"
   ```
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py ack \
     --state .sdlc/state.yaml --spec 0007 --by "<recipient name>"
   ```
   `handoff` sets `next_owner`; `ack` clears it (exit 1 if nothing is open; a warning — not an error —
   if `--by` is not the named owner). `status` lists every unacknowledged handoff with its
   business-day age, so a spec never sits between Product, Engineering, and Data unowned.

7. **`verdict` — the independent Engineering and Data checks.** The front door is
   `/sdlc-refine validate --lane eng|data`, which runs this write; it is listed here because
   readiness depends on it.
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py verdict \
     --state .sdlc/state.yaml --spec 0007 --lane eng --verdict accepted --by "<named lead>"
   ```
   `--verdict` is `accepted | returned | pending | n-a`. `n-a` is legal **only** for `--lane data` and
   **only** with `--reason` (exit 1 otherwise). `returned` records without a reason but warns — give
   one; the spec goes back to refinement with it.

8. **`ready` — the sprint-planning moment.** Requires, for **every** slated spec: `check_spec` READY,
   `status` at least `ready` (`ready`, `in-flight` or `merged` — only `draft` falls short; still
   hand-moved), `eng_review: accepted`, `data_review: accepted | n-a`; plus a
   dependency graph with no cycle and no `depends_on` pointing outside the slate at an unmerged spec.
   An empty slate is itself a gap. Forward only — a sprint already `ready` or `closed` exits 1.
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py ready \
     --state .sdlc/state.yaml --sprint S07 --by "<name>"
   ```
   On a gap: exit 1 and every gap listed per spec (`0009: eng_review is pending, needs accepted`);
   nothing is written. Hand the list to `/sdlc-refine --sprint S07`. On success: `state: ready`,
   `readied_by`, a `ready` ledger event, and the **sprint-planning page**
   `.sdlc/reports/sprint-S07-planning.html` (linked from `.sdlc/reports/index.html` when that exists).
   Open the page for the meeting (`open` on macOS, `start` on Windows, `xdg-open` on Linux). A page
   render failure is a warning, not a failure — re-render with `plan`.

   Re-render the page on demand — before `ready`, to run the meeting from a draft that still shows the
   gaps, or after a late change:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py plan \
     --state .sdlc/state.yaml --sprint S07
   ```
   `--output <path>` overrides the default location. `plan` exits 1 only when the sprint does not exist.

9. **`close` — commitment-shaped outcomes, this sprint only.** Kept = slated specs with
   `status: merged`. Every other slated spec is **open** and must be decided.

   > **HITL GATE:** Run `status` first and list the open specs. For **each** one ask with
   > `AskUserQuestion`: "Carry `0009` into S08, or drop it? Give the reason." A carry needs the
   > destination sprint (`--carry-to`); every carry and drop needs a named human and a non-empty
   > reason — the script exits 1 naming any undecided spec, and refuses a spec named in both lists.
   > A carry-to sprint that has no record yet is a warning (create it with `new`), not an error.

   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py close \
     --state .sdlc/state.yaml --sprint S07 --by "<name>" --carry-to S08 \
     --carry "0009=<why it carries>" --drop "0012=<why it is dropped>"
   ```
   Carried specs get `sprint: "S08"`; dropped get `sprint: ""`; kept keep theirs. The script writes
   the `## Close` table (`| spec | outcome (kept | carried → SNN | dropped) | by | reason |`) into
   `.sdlc/sprints/S07.md`, sets `state: closed` and `closed_by`, appends `carried` / `dropped` /
   `closed` events, and renders the **sprint-review page** `.sdlc/reports/sprint-S07-review.html`
   (outcomes, the ledger's carry/drop reasons, carry-over recurrence per spec). `close` **never**
   suggests advancing a phase — leaving Build stays a human declaration in `/sdlc-next`.

10. **Report** (after any write verb; after `status` show the script's own output):
    ```
    Sprint S07 — "<goal>"  (planning | ready | closed) · 2026-10-05 → 2026-10-16 · N business days remaining
    Slate:     6 slated · 4 READY · 2 with gaps (0009: eng_review pending · 0012: DoR NOT READY)
    Verdicts:  1 pending (0009 eng, 3 business days) | no data
    Handoffs:  2 unacknowledged (0007 → <name>, 1 business day) | no data
    Mix:       HIGH 1/1 · MEDIUM 2/2 · LOW 3/3        WIP: 1 in-flight · cap 2
    Next up:   0007 — READY, dependencies merged
    Page:      .sdlc/reports/sprint-S07-planning.html | not yet rendered
    Next: /sdlc-refine --sprint S07 to close the gaps | ready --by <name> when the readiness line reads 6 of 6
    ```
    Every empty section reads `no data` — never a 0 that was not measured.

## Arguments

- No arguments: `status` for the active sprint in workflow mode.
- `new | slate | unslate | status | handoff | ack | verdict | ready | plan | close`: the verb, with
  the flags shown above (`--sprint` defaults to the active sprint on every verb except `new`).
- `--repo <path>`: standalone mode — run against any repo with a `specs/` directory and no
  `.sdlc/state.yaml`; the sprint record and ledger are created under `<repo>/.sdlc/`.
- `--json`: machine-readable output for `status` and the `slate` proposal.
- `--today YYYY-MM-DD`: override today's date for business-day arithmetic (replays, tests).
- `--field KEY=VALUE` (write verbs, repeatable): an extra key on the ledger line. An activity-metric
  key (`velocity`, `points`, `estimate`, `effort`, `hours`, `capacity`, `pr_count`, `loc`, …) is
  **refused with exit 2** before anything is written.

## Important

- The user runs `/sdlc-sprint` — never `sprint.py` by hand. The command owns mode resolution, the
  proposal → confirm dialogue, and the per-spec carry/drop interview at close.
- **Agent proposes, named human decides.** The agent drafts the slate, the build order, and the
  carry/drop split; a human confirms each, and every write carries `--by <name>`. A `--by` that reads
  as an AI or automation is refused (exit 2) — that is labelling, not enforcement.
- **No activity metrics.** The layer never computes velocity, story points, estimates, effort, hours,
  PR count, or lines of code; `--field` with such a key exits 2, the same refusal as `scorecard.py`.
  Nothing aggregates per person. Empty series read `no data`, never 0.
- **Sprints never gate and are never gated.** Every read exits 0; `ready` and `close` check only the
  slate (DoR + verdicts + dependencies), never gates G1–G7; nothing is written to `state.yaml`;
  refinement runs in any phase where specs exist. The WIP cap stays global (`track_specs --wip-cap`) —
  a slate is a commitment window over the backlog order, never a second WIP budget.
- **`status` is still hand-moved** (`draft | ready | in-flight | merged`). The script writes only its
  five keys, and only in `specs/NNNN-*.md`; `check_spec.py` is byte-for-byte unchanged.
- **Exit codes:** reads 0 always; writes 0 ok / 1 illegal, missing precondition, unknown spec, or a
  ready gap / 2 refused. A `DRIFT` line means the frontmatter was written but the ledger append
  failed — re-run the verb once the ledger path is writable.
