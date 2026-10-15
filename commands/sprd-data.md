# /sprd-data — Author the Data Documents for a Feature, or Drive a Data Spec

Give Data a first-class drafting seat: the **data contract** (PII-classified), the **data-readiness**
assessment, and the **lineage / audit** design for a feature or spec — plus, for a data spec, the
**data dictionary**, the **decision memo** and the **handoff**. It sharpens Scope, surfaces the
PII that drives risk tier, and turns readiness gaps into tracked decisions. Interview-driven like
`/sprd-coach`: the `data-analyst` agent assesses what's there, asks focused questions, and drafts as
answers arrive. It **proposes**; a named human **decides** (the One Rule). Works inside an SDLC project
or standalone.

`/sprd-data` also drives a **data spec** (`type: data`, `serves: "<parent>"`): a spec the data team owns,
linked to the build spec that needs its data. A data spec is done when its acceptance checks say the data
really flows — the pipeline runs end to end and the build team can call the result. The contract is
`references/data-specs.md`.

## Instructions

1. **Resolve context:**
   - **Workflow mode** (default): `.sdlc/state.yaml` exists. Read the feature-brief / spec Scope and any
     `data-*` artifacts; outputs land in `.sdlc/artifacts/02-design/data/`.
   - **Standalone mode** (`--repo <path>`, or no `.sdlc/` found): operate on the given repo with
     provisional context; write to `--output` (default alongside the repo) and note the missing context
     in the artifact headers.
   - A data spec works in either mode: `--repo` needs no `.sdlc/`; `--state` also appends one
     `data_spec_linked` line (spec ids only) to `.sdlc/metrics/spec-log.jsonl`.

1a. **Load the Context bundle (data spec):** When `--spec` names a spec whose frontmatter is
   `type: data`, read its `## Context` section first and open every path it lists — the parent spec and
   its acceptance checks, each `BR-NN` business rule, `DL-NN` decision, `ADR-NNN` decision record and
   `DOC-NNN` intake document — **before any interview question**. A line reading
   `not found in this repository` is a gap to ask the human about, never a path to guess.

   If `--spec` names a spec that is **not** a data spec, or there is no data spec yet for the build spec
   in scope, offer to scaffold one (the command layer runs it; the agent has no shell):

   ```bash
   uv run scripts/data_spec.py new --serves <parent id> --name "<name>" --repo <repo>
   ```

   Add `--all-branches` to that call when other branches hold specs, so the new id is unused on every
   local ref (it never fetches — run `git fetch` first). To turn a spec that already exists into the data
   spec instead:

   ```bash
   uv run scripts/data_spec.py target --spec <id> --serves <parent id> --repo <repo>
   ```

   State plainly what the tool writes to the **parent** spec, and nothing else: its `depends_on` gains
   the data spec's id (so the sprint layer builds the data first), and its `data_review` becomes
   `pending` — unless it was already `accepted`, which is **kept**, with a note, because a tool never
   undoes a named human's verdict. Acceptance is only ever
   `sprint.py verdict --lane data --verdict accepted --by <named human>`. A self-link, a parent that is
   itself a data spec, or a `depends_on` cycle is refused and nothing is written.

2. **Assess what exists:** Read the feature-brief's Data touchpoints section, any success-criteria
   baseline, and the current data artifacts — which fields are named, which sources are known, what is
   still unclassified. For a data spec, the Context bundle from step 1a is where this starts.

3. **Run the interview:** Spawn the `data-analyst` agent (Data discipline). It runs the coach-style
   dialogue — which fields the feature reads or writes, their sources and types, which are **PII or
   customer-linked**, whether the data is actually available and complete, and how it flows end to end
   (lineage + retention). It drafts six artifacts from the templates in
   `templates/phases/02-design/data/`:
   - `data-contract.md` — the field table with an explicit **PII?** column.
   - `data-readiness.md` — availability / completeness / quality, with gaps flagged (advisory).
   - `lineage-audit.md` — source → transform → sink flow with retention and audit points.
   - `data-dictionary.md` — per input: derivation, null %, distinct, min–max, median. Every number cites
     the profile query or `file:line` it came from; a value nobody measured reads `not measured`,
     never `0`.
   - `decision-memo.md` — constraints, options with evidence, a scorecard, and the decision, made by a
     named human.
   - `data-handoff.md` — one page: what is live, how to call it, degraded results, smoke tests, what is
     left, owners.

   For a data spec, the handoff and the dictionary are what the spec's pre-seeded acceptance checks read.

4. **Confirm PII and route readiness gaps with the human:**

> **HITL GATE:** Present the data findings using the `AskUserQuestion` tool. Ask:
> (1) Confirm the **PII classification** on each field — PII is a **risk-tier driver** (it pushes the
>     dependent specs toward HIGH); the analyst proposes, a named human confirms.
> (2) Which **readiness gaps** (missing / low-quality data) become **decision-log** items (owner +
>     2-business-day clock) — readiness is advisory and never blocks; the analyst never decides the fix.
> (3) For a data spec: who **decides** the decision memo (`Decided by`) — a named human, never the
>     analyst.
> Data proposes; a named human signs the data-contract section at the Phase-2 gate (captured in state).

5. **Open decision-log items:** For each readiness gap the human routed, open a decision-log item with
   owner + clock. The command layer runs this — the agent has no shell:

   ```bash
   uv run scripts/track_decisions.py open --decision "<gap>" --owner "<@handle>" --all-branches --repo <repo>
   ```

   In workflow mode pass `--state .sdlc/state.yaml` instead of `--repo`. `--all-branches` reads the
   decision log on every local ref, so two branches never allocate the same `DL-NN`; it never fetches,
   so run `git fetch` first. The script allocates the next `DL-NN`, stamps `opened` and the
   two-business-day `due`, and creates the log when absent — workflow writes `.sdlc/decision-log.md`,
   standalone writes `<repo>/decision-log.md`. These surface in `/sprd-status` and `track_decisions.py`.

5a. **Check the data spec (data spec only):** Look at where it stands. Both reads are advisory and exit 0
   — they never gate:

   ```bash
   uv run scripts/data_spec.py check --spec <id> --repo <repo>
   ```

   `check` reports Context coverage (every reference the parent cites is listed), whether every
   readiness gap has an owner, and whether the handoff is present with its smoke tests. A source file
   that is absent reads `not measured`, never a pass or a fail.

   ```bash
   uv run scripts/data_spec.py status --repo <repo>
   ```

   `status` shows where every data spec stands against its parent, and whether the parent's
   `data_review` is due for a named human's acceptance. In workflow mode pass `--state` instead of
   `--repo`.

6. **Report:**
   ```
   Data Artifacts Authored
   =======================
   Artifacts: data-contract.md, data-readiness.md, lineage-audit.md, data-dictionary.md, decision-memo.md, data-handoff.md
   PII:       N fields classified PII (risk-tier driver: <specs pushed HIGH> | none)
   Readiness: X gaps flagged (advisory) → M decision-log items (owners: …) | ready
   Linked spec:  <data id> serves <parent id> (parent depends_on: yes; data_review: pending | accepted | …)
   Done when:   <N of 6> pre-seeded acceptance checks ticked
   Next: feed PII into the spec's risk tier at /sprd-spec; readiness gaps ride the decision-log.
   ```
   Both new lines are read, never invented: `Linked spec` from `data_spec.py status` (step 5a), `Done when`
   by counting the ticked boxes among the six pre-seeded checks in the spec's `## Acceptance Checks`.
   With no data spec the line reads `Linked spec:  none` and the `Done when` line is left out.

## Arguments

- No arguments: workflow mode — author against the current project's feature/spec.
- `--repo <path>`: standalone mode — author in any repo with no `.sdlc/` present.
- `--feature <id>`: scope the data work to a feature (otherwise inferred/asked).
- `--spec <id|path>`: scope the data work to a spec. A data spec id or path loads its `## Context` bundle
  first (step 1a); a build spec that has no data spec yet is offered the scaffold.
- `--all-branches`: passed through to `track_decisions.py open` and `data_spec.py new` — read the
  decision log and `specs/` on every local ref so a new `DL-NN` or spec id is unused on all of them.
  Run `git fetch` first; it never fetches.
- `--output <path>`: override the output location (standalone).

## Important

- **PII classification is a risk-tier driver, not a label.** Confirmed PII pushes dependent specs toward
  HIGH; the analyst proposes the classification, a named human confirms it, and the tier is owned at
  `/sprd-spec` time.
- **Data readiness is advisory** — a gap is a flagged decision, never a block. It becomes a decision-log
  item with an owner and a clock, not a gate failure.
- **The agent has no shell and does not query a data platform.** Every number it writes cites the query
  or `file:line` a person supplied, or reads `not measured`; live evidence (`--live`) is a deferred
  design — see `docs/proposals/data-specs.md` §Deferred. The contract for a data spec — the marker, the
  link, the `data_review` transition, the `## Context` layout, what "done" means — is
  `references/data-specs.md`.
- **A tool links; a named human accepts.** `data_spec.py` writes `depends_on` and `data_review: pending`
  on the parent and never `accepted`; the agent never edits the parent's frontmatter.
- Product-specific data compliance (e.g. SOC 2 call-recording, retention law) is configured **at build
  time** via the existing per-engagement compliance mechanism — it is not this command's job.
- These artifacts are **optional** for gate purposes; an unfilled section is an advisory flag. Data
  proposes; a named human signs at the phase gate. The command changes no protected core.
