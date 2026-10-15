# Data Specs — the data work a build spec needs, as a spec of its own

A **data spec** is an ordinary spec (one spec = one branch = one PR) whose work is data: the source
objects, transformation code, serving object and documents a **build spec** needs before it can ship. The
Data discipline owns it, `/sprd-data` works it, and it is done only when the data really flows.

This is a **Tier-3 reference**: loaded on demand, read by no hook. The executable half is
`scripts/data_spec.py` (CLI), `scripts/data_spec_model.py` (pure; the source of truth for every rule below)
and `scripts/branch_scan.py` (read-only ref reads). Reasons: `docs/proposals/data-specs.md`; pinned
interfaces: `docs/proposals/data-specs-build-kit.md`.

## 1. What a data spec is

- **The marker** is `type: data` (the existing `type` field, never `kind:`) plus `serves: "<parent id>"`,
  the build spec it serves. Template: `templates/phases/build/data-spec.md`. Every other key and section is
  a normal spec's, so `check_spec.py` holds it to the same Definition of Ready.
- **Linked both ways by one call.** The parent's `depends_on` gains the data spec's id; the data spec's
  `serves` names the parent. `sprint_model.build_order` already orders by `depends_on`, so the data spec is
  built first with no new logic, and a parent slated without it is warned about.
- **Refused (exit 2, nothing written):** a self-link, a data-spec parent, a `depends_on` cycle.
- **Six documents** (data-contract, data-dictionary, lineage-audit, data-readiness, decision-memo,
  data-handoff) from `templates/phases/02-design/data/` into `.sdlc/artifacts/02-design/data/`.
- **Standalone or workflow.** `--repo` works with no `.sdlc/`; `--state` also appends one
  `data_spec_linked` line (spec ids only, no names) to `.sdlc/metrics/spec-log.jsonl`.

## 2. The four verbs (`scripts/data_spec.py`)

| Verb | Args | Does | Exit | `--json` document |
|---|---|---|---|---|
| `new` | `--serves NNNN --name … [--risk MEDIUM] [--source —] [--owner] [--team] [--all-branches]` | Allocates the next spec id (with the flag: highest id on any local ref, plus one), renders the data-spec template, fills `## Context` from the parent, links the parent (§3), refuses on a cycle | 0 / 1 / 2 | `{"path","id","name","risk","serves","parent_path","parent":{depends_on_before,depends_on_after,data_review_before,data_review_after,data_review_note},"context_refs":{BR:[],DL:[],ADR:[],DOC:[]},"unresolved_refs":[],"refs_scanned"?:[],"unread"?:[]}` |
| `target` | `--spec NNNN --serves NNNN` | Turns an existing spec into a data spec: sets `type`/`serves`, adds `## Context` at the end only if absent, links the parent | 0 / 1 / 2 | `{"path","id","serves","changed":{"type":bool,"serves":bool,"context_added":bool},"parent":{…},"context_refs","unresolved_refs"}` |
| `status` | `[--spec NNNN]` | Read-only: every `type: data` spec, or the one | 0 | `{"has_data":bool,"specs":[status_row…]}`; text: one line per spec, `No data specs.` when none |
| `check` | `--spec NNNN` | Advisory, never gates: `context-coverage`, `readiness-gaps-owned`, `handoff-present` | 0 | `{"spec","findings":[{"name","passed","detail"}]}` |

Every verb also takes `--state <state.yaml>` or `--repo <path>`, and `--json` (exactly one JSON document;
refusals go to stderr; exit codes are unchanged by the flag).

- **Exit codes.** Reads exit 0 always. Writes: 0 ok; 1 illegal (missing parent, malformed file, ledger
  `DRIFT`); 2 usage or refused (self-reference, parent is data, cycle, conflicting `serves`). The parent is
  the one `specs/NNNN-*.md`; two matches exit 1 naming both.
- **`status_row`** is `{id, serves, status, parent_found, parent_depends_on_has_me, parent_data_review,
  acceptance_due}`; `acceptance_due` is true when the data spec is merged and the parent's `data_review`
  is not `accepted`. With no data spec, `status --json` is exactly `{"has_data": false, "specs": []}`.
- **`check`** reports `passed: null` and `not measured` when its source file is absent, never a pass or a
  fail. `readiness-gaps-owned`: every `DL-NN` in `data-readiness.md`'s Gaps table has a decision-log owner.
  `handoff-present`: `data-handoff.md` exists and `## Smoke tests` holds no `[bracketed]` placeholder.

## 3. The `data_review` transition (D4)

Linking writes two lines in the parent and nothing else, each keeping its trailing `# comment` (line
endings preserved). `depends_on` `"0007"` plus `0009` becomes `"0007,0009"`, deduplicated.

| Parent `data_review` before | After linking | Note |
|---|---|---|
| `""` (not recorded), `n-a`, `returned` | `pending` | data work now exists, so the old answer no longer holds |
| `pending` | `pending` | unchanged |
| `accepted` | `accepted` (**kept**) | result carries `data_review_note`: a named human's verdict was kept |

A tool never writes `accepted` or any `status`. Acceptance is only
`uv run scripts/sprint.py verdict --repo <r> --spec <parent> --lane data --verdict accepted --by "<named human>"`
(which refuses an AI `--by`); a person re-verdicts if the new data work warrants it.

## 4. The `## Context` layout

`## Context` is the bundle `/sprd-data` loads first, rewritten in place (bytes outside it are untouched).
It lists the parent, a dated read-only copy of its acceptance checks, and every reference the parent's
**body** cites: `BR-NN` business rules, `DL-NN` decisions, `ADR-NNN` decision records, `DOC-NNN` intake
documents. A reference resolves to the Markdown file under `.sdlc/artifacts`, `.sdlc`, `docs`, `specs`
(searched in that order) that *defines* it: a heading naming it, or a table row starting with it.

```
**Serves:** spec 0007 — `specs/0007-duplicate-claim-409.md`

**Parent acceptance checks (read-only copy, taken 2026-10-15):**
- [ ] a duplicate submission returns 409 …

**Business rules:**
- BR-03 — `.sdlc/artifacts/01-requirements/business-rules.md`

**Decisions:**
- none

**Decision records:**
- none

**Intake documents:**
- DOC-004 — `.sdlc/context/intake/DOC-004-vendor-api.md`
```

**A reference that cannot be found says `not found in this repository`** (``- DL-07 — not found in this
repository``), never a guessed path; an empty list reads `- none`. Keep Context current by hand when the
parent changes: `target` never rewrites an existing one, and `check` names any reference it lacks.

## 5. Done means the data flows

Six checks are pre-seeded in the template; keep them, sharpen the names, add the parent's own data needs
below. The grader grades the PR against these lines; `check` is the early, advisory look. A person runs
and cites the check-3 profile query today; a cell nobody measured reads `not measured`, never `0`.

```
- [ ] The pipeline runs end to end on the target environment named in `data-handoff.md` and exits 0.
- [ ] The serving object named in `data-handoff.md` returns >= 1 row for a real record the parent spec's acceptance checks use.
- [ ] `data-dictionary.md` has a row for every input the parent spec names, with null %, distinct count and min/max from a live profile query cited in that row.
- [ ] `lineage-audit.md` shows a source -> transform -> serve path for every serving object.
- [ ] The smoke tests in the integration example pass and their output is linked from `data-handoff.md`.
- [ ] Every gap in `data-readiness.md` has a `DL-NN` with an owner in `decision-log.md`.
```

## 6. Branch-safe ids

`track_decisions.py open --all-branches` and `data_spec.py new --all-branches` read the decision log (or
`specs/`) on every **local** ref (`refs/heads`, `refs/remotes`) via `git show` / `git ls-tree` and take the
highest id plus one. They **never fetch**: run `git fetch` first or an unfetched branch is invisible. An
unreadable ref is named in `unread`, never dropped; outside a git repository the call proceeds locally
with `refs_scanned: []`. Without the flag, output is byte-identical to before.

## 7. Not built

`/sprd-data --live` (read-only platform queries by the agent) and platform packs are designed only; see
`docs/proposals/data-specs.md` §Deferred. The `data-analyst` agent has no shell and queries no platform.
