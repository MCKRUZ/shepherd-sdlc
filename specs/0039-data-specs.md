---
spec: "0039"
name: "data-specs"
status: draft            # draft | ready | in-flight | merged | deferred
deferred_reason: ""      # required when status is deferred — why this spec was not built
type: feature            # feature | bugfix — a bugfix PR carries the `type:bugfix` label and
                         # must pass repro-gate: its new test FAILS against the pre-fix code
risk: MEDIUM
source: "docs/proposals/data-specs-build-kit.md (the kit) and docs/proposals/data-specs.md (the design): a data spec linked to the build spec it serves, a Context bundle, three more data documents, branch-safe ids, and the done-when-the-data-flows checklist"
channel: ""              # optional — delivery surface (see channels/); blank = channel-agnostic
owner: "@MCKRUZ"
developer: ""            # who drives the agent and approves the plan — filled at hand-off
checker: ""              # non-author approval — filled at hand-off
team: "core"
harness_context: "scripts/sprint_model.py set_frontmatter + scripts/new_spec.py render_spec: every frontmatter write is a targeted line edit that keeps the trailing comment and the line endings, and a new spec is the shipped template with its placeholder literals replaced — data_spec.py composes those two and adds no rendering or YAML regeneration of its own"
created: "2026-10-15"
sprint: ""               # optional — sprint id (e.g. S07); written by /sprd-sprint slate, never by hand
next_owner: ""           # optional — who holds the next action; set by `handoff`, cleared by `ack`
eng_review: ""           # optional — pending | accepted | returned; Engineering verdict, recorded by name
data_review: ""          # optional — pending | accepted | returned | n-a (n-a needs a reason); Data verdict
depends_on: ""           # optional — comma-separated spec ids this spec builds on, e.g. "0007,0009"
---

# Spec 0039 — data-specs

## Goal
A data team can create a **data spec** (`type: data`, `serves: "<parent>"`) that is linked as a dependency of the build spec it serves, carries a Context bundle of every business rule, decision, decision record and intake document the parent cites, is worked through `/sprd-data` into six data documents, and is done only when its pre-seeded acceptance checks say the data really flows; and both `DL-NN` and spec ids can be allocated without colliding with an unmerged branch.

## Why
A build spec says what to build and nothing about where its data lives, how it is prepared or what serves it; the data team has no spec that tells them what the build needs, so the business rules, decision log, decision records and intake documents sit in the project with no document that connects them to a data deliverable, and nothing proves the data works before the build starts. The spec frontmatter already has `depends_on` and `data_review`, but no tool fills them and no spec is marked as data work. Separately, `track_decisions.py open` and `new_spec.py` scan only the current checkout, so two branches allocate the same `DL-07` or the same `0034` — this spec is numbered 0039 by hand for exactly that reason.

## Scope

### In scope
- New `scripts/data_spec.py` (verbs `new`, `target`, `status`, `check`) and pure `scripts/data_spec_model.py`; new `scripts/branch_scan.py` (read-only `git for-each-ref` / `git show` / `git ls-tree`, never a fetch).
- `scripts/track_decisions.py`: an additive `open --all-branches` flag and an `other_logs` keyword on `open_decision`; output without the flag byte-identical.
- New templates with shapes and round-trip fixtures: `templates/phases/build/data-spec.md` and `templates/phases/02-design/data/{data-dictionary,decision-memo,data-handoff}.md`.
- `commands/sprd-data.md`, `agents/data-analyst.md` (prose only; the tools list is unchanged), `phases/activities.yaml`, `scripts/capabilities.py`, `references/data-specs.md`, `docs/proposals/data-specs.md`, `docs/proposals/data-specs-build-kit.md`, `docs/commands.md` (one row), `CHANGELOG.md` (`## Unreleased`), `CLAUDE.md` (one Key Features bullet and Testing lines), this spec.
- New tests only: `scripts/tests/test_data_spec_template.py`, `test_branch_scan.py`, `test_track_decisions_all_branches.py`, `test_data_spec_model.py`, `test_data_spec_cli.py`, and the four fixtures under `scripts/tests/fixtures/documents/`.

### Out of scope
- `scripts/new_spec.py`, `scripts/check_spec.py`, `scripts/check_gates.py`, `scripts/sprint.py`, `scripts/sprint_model.py`, `scripts/spec_transition.py`, `scripts/advance_phase.py`, `scripts/phase_model.py`, `phases/phase-registry.yaml`, `templates/phases/build/spec.md` and its shape, `harness/**`: byte-identical to the base commit. A data spec needs none of them changed — `check_spec.py` already ignores unknown frontmatter keys and extra sections.
- Any existing test or fixture, with one deliberate exception: `scripts/tests/test_activities_model.py`'s exact list of the build phase's activities gains `data-spec`, because that pin exists to notice exactly this kind of declared addition and must move with the declaration. Every other pin that no longer holds is a defect in this change, not in the pin.
- `/sprd-data --live` (read-only platform queries by the agent) and platform packs under `harness/packs/tools/<platform>/`: written up in `docs/proposals/data-specs.md` §Deferred, not built. The `data-analyst` agent keeps `Read, Write, Edit, Grep, Glob` and gets no shell.
- Writing `data_review: accepted` on a parent, or any `status` change on any spec: acceptance stays `sprint.py verdict --lane data --verdict accepted --by <named human>`.
- A version bump: `CHANGELOG.md` gains `## Unreleased`; numbering is decided at release because 2.1.0–2.5.0 are claimed by unmerged work.
- `.sdlc/team.yaml` and any stored credential.

## Acceptance Checks
- [ ] In a repository whose parent spec is `specs/0001-duplicate-claim-409.md`, `uv run scripts/data_spec.py new --repo <r> --serves 0001 --name "claims profile"` creates `specs/0002-claims-profile.md` with `type: data`, `serves: "0001"` and a filled `## Context`, and the parent file differs from before in exactly 2 lines (`depends_on: "0002"` and `data_review: "pending"`), each keeping its trailing `# comment`.
- [ ] `data_spec.py new` against a parent whose `data_review` is `accepted` leaves it `accepted`, and the `--json` document carries `"data_review_note"` saying a named human's verdict was kept.
- [ ] `data_spec.py new --serves 0002` where 0002 is itself `type: data`, `data_spec.py target --spec 0001 --serves 0001`, and a link that would close a `depends_on` cycle each exit 2 and leave every file under `specs/` byte-identical.
- [ ] `data_spec.py status --repo <r> --json` on a repository with no data spec prints exactly `{"has_data": false, "specs": []}`.
- [ ] In a repository whose `master` log holds `DL-01`..`DL-03` and whose `feature` branch commits `DL-07`, `uv run scripts/track_decisions.py open --all-branches --decision "x" --owner "@priya-n" --json` on `master` allocates `DL-08`; the same call without the flag allocates `DL-04` and its JSON keys are exactly `id`, `opened`, `due`, `owner`, `path`.
- [ ] `grep -c '"fetch"' scripts/branch_scan.py` prints `0`, and the only new module importing `subprocess` is `scripts/branch_scan.py`.
- [ ] `uv run --project scripts pytest scripts/tests/test_shapes_cover_templates.py scripts/tests/test_shaped_templates_roundtrip.py -q` passes with `data-spec`, `data-dictionary`, `decision-memo` and `data-handoff` among the parametrised ids.
- [ ] `git diff --exit-code <base> -- scripts/new_spec.py scripts/check_spec.py scripts/sprint.py scripts/sprint_model.py scripts/spec_transition.py templates/phases/build/spec.md templates/phases/build/spec.shape.yaml harness` exits 0, and `git diff --diff-filter=M --name-only <base> -- scripts/tests` prints exactly one path, `scripts/tests/test_activities_model.py` (the build-phase activities pin, which gains `data-spec`).
- [ ] `uv run --project scripts pytest scripts/tests/test_capabilities.py scripts/tests/test_command_contracts.py scripts/tests/test_agent_references.py -q` passes with `data-spec`, `data-spec-status` and `decision-open-all-branches` declared in `scripts/capabilities.py`.
- [ ] `git grep -c '/sdlc-' -- commands/sprd-data.md agents/data-analyst.md references/data-specs.md docs/proposals/data-specs.md templates/phases/build/data-spec.md` finds 0 matches.

## Risk Tier
**Tier:** MEDIUM
**Why this tier:** every write lands in the repository's own files — spec frontmatter, a decision log, new templates — through targeted line edits with refusals pinned by tests, and nothing here touches a code host, a data platform, credentials or a gated path, which alone would read LOW; it is MEDIUM because it changes `track_decisions.py`, a script every `/sprd-*` command that opens a decision relies on, and because a wrong `depends_on` edit would silently reorder what the sprint layer builds first. Nothing is hard to undo. The Pod Lead may raise it.

## Delegation Plan
- **Scope (file patterns):** the In scope list above, and nothing else; a file outside it is **stop and ask** (the kit's house rule 11 returns `status: blocked`).
- **Context (pattern to reuse):** `sprint_model.set_frontmatter` for `depends_on` and `data_review`, `new_spec.render_spec` for the template, `track_decisions._highest_used` for id allocation — matches `harness_context`.
- **Permissions:** auto-allowed: reads, `uv run --project scripts pytest`, `uv run scripts/*.py --help`, `git` reads (`for-each-ref`, `show`, `ls-tree`, `diff`). Confirm-required: any `git fetch`, `git push`, `npm install`, or edit outside the scope list.
- **Gated paths touched:** none.

## Checking Plan
**Ladder depth:** MEDIUM
**Specifics:** CI runs the plugin suite; the kit's gates G1–G11 run after every merged level (protected core byte-identical to the base, no existing test modified other than the build-phase activities pin, the `new_spec.py` and `track_decisions.py` goldens, registries agree, `--help` creates nothing, no `fetch`, this spec READY); the grader grades against the Acceptance Checks above; a non-author Checker reads the `data_review` transition table (D4 in the kit) against `scripts/data_spec_model.py` and runs the kit's §7 smoke run by hand.

## Decision List
- **The marker is `type: data` plus `serves:`, not `kind: data`.** `kind` already names three other things in this codebase; `type` is the field a spec already has for its class. Decided 2026-10-15 by @splashthree (the requesting owner). Answer: `type: data`.
- **A parent's `data_review: accepted` is kept, not reset to `pending`, when a data spec is linked.** A tool must not undo a named human's verdict; the result says so in `data_review_note` and a person re-verdicts if the new data work warrants it. Decided 2026-10-15 by @splashthree. Answer: keep `accepted`; `""`, `n-a` and `returned` become `pending`.
- **`--live` and platform packs are designed, not built.** Giving the data agent a shell against a client data platform is a security posture for the owner to set; until then every unmeasured number reads `not measured`. Decided 2026-10-15 by @splashthree. Answer: `docs/proposals/data-specs.md` §Deferred.
- **`data_spec.py` is a new script; `new_spec.py` is imported, never edited.** `new_spec.py` is protected core and its `--json` shape is pinned exactly by an existing test. Decided 2026-10-15 by @splashthree. Answer: new script.
