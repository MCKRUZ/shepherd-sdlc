---
spec: "0040"
name: "ado-boards-sync-and-catch-up"
status: ready            # draft | ready | in-flight | merged | deferred
deferred_reason: ""      # required when status is deferred — why this spec was not built
type: feature            # feature | bugfix — a bugfix PR carries the `type:bugfix` label and
                         # must pass repro-gate: its new test FAILS against the pre-fix code
risk: MEDIUM
source: "docs/proposals/ado-boards-mirror.md §7 + plan 2026-10-15"
channel: ""              # optional — delivery surface (see channels/); blank = channel-agnostic
owner: "@MCKRUZ"
developer: "@MCKRUZ"
checker: ""              # non-author approval — filled at hand-off
team: "core"
harness_context: "scripts/ado_sync.py's existing read verbs `pull` and `plan` (Fold B2) and the closed desktop table studio/shared/adoVerbArgv.ts (Fold B4): `sync` runs the pull and plan code paths the CLI already has, in one process, with the pure decisions in scripts/ado_sync_model.py; the desktop's `plan` request rides the same closed table and `runAdoVerb` that main already runs for the seven earlier verbs."
created: "2026-10-15"
sprint: ""               # optional — sprint id (e.g. S07); written by /sprd-sprint slate, never by hand
next_owner: ""           # optional — who holds the next action; set by `handoff`, cleared by `ack`
eng_review: ""           # optional — pending | accepted | returned; Engineering verdict, recorded by name
data_review: ""          # optional — pending | accepted | returned | n-a (n-a needs a reason); Data verdict
depends_on: "0038"       # optional — comma-separated spec ids this spec builds on, e.g. "0007,0009"
---

# Spec 0040 — ado-boards-sync-and-catch-up

<!--
  The durable per-change record of the Build loop. One spec = one branch = one PR.
  Fold B6 of the Azure Boards mirror. Validate with:
    uv run --project scripts scripts/check_spec.py --spec specs/0040-ado-boards-sync-and-catch-up.md
-->

## Goal
A person catches up with the client's Azure Board in one step, only when they say yes, and the desktop app can draw up a plan so its existing apply dialog is finally reachable. A new read verb, `ado_sync.py sync`, runs the mirror's reads in one pass — the fields pull, the drift classified from that pull's own rows (the board is never read a second time), the discussion pull only when the person gave `--discussion`, then the plan — and ends with the same `Next:` line `comment` and `plan` print. The commands that start a working session ask before catching up, never after. Shepherd, the desktop app, gains the eighth and last request of its closed Boards table, `plan`, a read with no `--by`, so the spec card's `Plan changes` draws up the plan on a click and hands it to the `AdoApplyDialog` Fold B4 built, whose Confirm stays the one way a plan reaches the board.

## Why
After Folds B1 to B5 a person who wants to know where the board stands runs `pull`, then `drift`, then `plan`, and often `pull --discussion` too — four commands, each re-reading the board, with three slightly different footers telling them what to run next. A single read verb does the same work with one board read for the fields, one golden footer and one `--json` document a screen can draw. On the desktop side the apply dialog exists, is tested, and is unreachable: the closed table had no `plan`, so the spec card could only show the plugin lines for a person to copy into a terminal. Widening the table by exactly one read verb closes that gap without opening a second write path. Reading the board is not free — it costs `az` calls, notifications nobody asked for when it chains into a plan, and a board read the person did not choose — so the catch-up is asked for, and nothing reads the board when a project or a spec card opens.

## Scope

### In scope
- B6-P0 contracts: `scripts/ado_sync_model.py` (append-only: `SYNC_STAGES`, `apply_next_line(plan)`, `SYNC_NODATA`); `scripts/tests/test_boards_sync_model_b6.py`; `scripts/tests/golden/ado_sync_unavailable.json`; `studio/shared/adoVerbArgv.ts` (the eighth `AdoVerbRequest` member, `plan`, and `ADO_VERB_CAPABILITY.plan = 'ado-plan'`); the B4 and B5 pins in `studio/test/adoVerbArgv.test.ts` and `studio/test/unit/adoWrites.test.ts` extended to the new truth; the build kit's K28, the K9, K11 and K13 notes, its §3 and §4 rows, the Fold B6 block and guardrails 24 to 28; and this spec.
- B6-P1 the `sync` verb: `scripts/ado_sync.py` (edit: the `sync` verb and its parser), and a new `scripts/tests/test_boards_*.py` file.
- B6-P2 catch-up prose: the command files that start a working session (`commands/sprd-ado.md` gains the `sync` section) gain an ask-first catch-up prompt, and a new `scripts/tests/test_boards_*.py` prose pin.
- B6-P3 plan from the desktop: the renderer files under `studio/src/components/SpecCard/` and `studio/src/components/ado/` that draw `Plan changes` and open the existing `AdoApplyDialog`, with their tests under `studio/test/` (new files, or files created after `325ac2b`).
- B6-P4 integration: `CHANGELOG.md` (a `### Fold B6` block under the existing `## 2.1.0` heading), `CLAUDE.md` (the Boards bullet and the Testing lines gain `sync`), `references/ado-boards.md` (the `sync` verb and the ask-first catch-up), and the build kit's Status line.
- New tests only: `scripts/tests/test_boards_*.py` and new `studio/test/` files; a test created after `325ac2b` may have a pin extended to the new truth, never weakened or deleted.

### Out of scope
- Any new write path to Azure DevOps: `sync` and `plan` are reads that write only a local plan file, the ledger and `.sdlc/ado/local/hook-status.txt`; `apply --confirm <hash> --by <human>` stays the only verb that sends anything to the board, under `posture: assisted`.
- Reading the board on project open, on a timer, on a spec card's mount, or in a session-start hook; a catch-up that runs before the person said yes.
- `--discussion` implied by another flag or added by command prose: `sync` has no `--full`, and the discussion is read only on the person's own ask.
- A ninth `AdoVerbRequest` member, a `--by` on `plan`, and any edit to `studio/shared/reasons.ts`, `studio/test/reasons.test.ts` or anything under `studio/electron/**`.
- A version bump: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `studio/package.json` and `studio/package-lock.json` stay at `2.1.0`.
- The protected core, byte-identical to `325ac2b`: `scorecard.py`, `generate_status.py`, `check_gates.py`, `check_spec.py`, `advance_phase.py`, `phase_model.py`, `new_spec.py`, `sprint.py`, `sprint_model.py`, `spec_transition.py`, `handoff.py`, `track_decisions.py`, `doctor.py`, `github_import.py`, `pipeline_proof_model.py`, `set_setting.py`, `spec_status.py`, `track_specs.py`, `ado_map.py`, `ado_import.py`, `ado_outcomes.py`, `ado_outcomes_map.py`, `host_report.py`, `code_host.py`, `gate_auth.py`, `phases/phase-registry.yaml`, `templates/state-init.yaml`, `agents/section-evaluator.md`, `commands/sprd-coach.md`, `commands/sprd-spec.md`.
- Any test or fixture that existed at `325ac2b` beyond Fold B4's one sanctioned `studio/test/reasons.test.ts` pin.
- Spawning a real `az` anywhere in either suite, and any UPN, e-mail address outside `@example.com`, display name, real GUID or comment text in a committed file or a ledger line.

## Acceptance Checks
- [ ] `uv run --project scripts pytest scripts/tests/test_boards_sync_model_b6.py -q` passes: `ado_sync_model.SYNC_STAGES == ("pull", "drift", "discussion", "plan")`; `apply_next_line("0a1b2c3d4e5f")` returns exactly ``Next: `ado_sync.py apply --confirm 0a1b2c3d4e5f --by <you>` sends it, as whoever az is signed in as`` and a value that is not a 12-hex hash (`""`, `"ZZZ"`, upper case, 11 or 13 characters, a trailing newline, `None`) raises `ValueError`; `SYNC_NODATA` equals `scripts/tests/golden/ado_sync_unavailable.json` byte for byte (`sort_keys`, indent 2) and holds 0 integer zeros and 0 `false` values; the model's import set equals the 8 modules it imported before this Fold.
- [ ] `cd studio && npx vitest run test/adoVerbArgv.test.ts test/unit/adoWrites.test.ts test/reasons.test.ts` passes: `ADO_VERBS` is `['apply', 'reconcile', 'link', 'pull', 'pullDiscussion', 'show', 'comment', 'plan']` and the build kit's §3 sheet block names the same 8 verbs in that order; `{ verb: 'plan', kind: 'spec', id: '0004' }` builds `['plan', '--kind', 'spec', '--id', '0004', '--json']` and `{ verb: 'plan', sprint: 'S07' }` builds `['plan', '--sprint', 'S07', '--json']`, each with 0 `--by`; `{ verb: 'plan' }`, `{ verb: 'plan', sprint: '7' }` and `{ verb: 'plan', kind: 'spec' }` are refused with 0 spawns; `{ verb: 'planSpec' }` is still refused; `ADO_VERB_CAPABILITY.plan === 'ado-plan'`.
- [ ] `git diff --name-only e0a430e -- studio/shared/reasons.ts studio/test/reasons.test.ts` prints nothing (`e0a430e` is the commit Fold B6 starts from), so `reasons.CAPABILITIES` keeps its 19 ids.
- [ ] A new `scripts/tests/test_boards_*.py` file pins `ado_sync.py sync` against `FakeBoardsAz(writes=False)`: `"sync" in ado_sync.VERBS`; the stages run in `SYNC_STAGES` order; the `az.calls` recorded by `sync` equal those recorded by `pull` then `plan` over the same fixtures, so the drift stage adds 0 board reads; without `--discussion` 0 comment-route calls are made and the document's `discussion` is `null`; with `--discussion` the discussion stage runs and `discussion` is a JSON object; 0 write routes are called.
- [ ] `sync --json` prints exactly 1 JSON document and exits 0 on every path except a pull-stage ledger `DRIFT`, which prints `DRIFT:` and exits 1; with nothing readable (no `.sdlc/ado.yaml`, no discovered schema, or `az` unreachable) the document has exactly the keys of `scripts/tests/golden/ado_sync_unavailable.json`, `"unavailable": true`, `"counts": null`, `"next": null`, and 0 integer zeros.
- [ ] `sync` writes `.sdlc/ado/local/hook-status.txt` twice — the pull stage's line, then the plan stage's — so its line 1 after `sync` is the plan stage's `ado_sync_model.hook_line(...)`; under `posture: assisted` the text output of `comment`, `plan` and `sync` each ends with exactly `ado_sync_model.apply_next_line(<hash>)`; under `posture: plan-only` the `plan` text stays byte-equal to `scripts/tests/golden/ado_plan_spec_0004.txt` (0 `Next:` lines).
- [ ] `sync` accepts `--kind K` (repeat), `--id ID` (repeat), `--sprint SNN`, `--all`, `--discussion` and `--no-comments` and has 0 `--full` and 0 `--by` options; `sync --help` run from an empty temporary directory leaves it empty (gate G9).
- [ ] A new `scripts/tests/test_boards_*.py` prose pin passes: every `commands/*.md` file that names `ado_sync.py sync` asks the person before the invocation and says the discussion is read only on the person's own ask (the words "only on" beside `--discussion`); `uv run --project scripts pytest scripts/tests/test_command_contracts.py -q` passes, so every `sync` flag the prose names exists in `ado_sync.py sync --help`.
- [ ] Nothing reads the board on project open: `grep -l 'ado_sync.py' hooks/shepherd-session-start.sh hooks/shepherd-session-start.ps1 | wc -l` prints `0`, and opening a project or a spec card in the desktop app sends 0 `{ verb: 'plan' }` and 0 `{ verb: 'pull' }` requests.
- [ ] `cd studio && npx vitest run` over the spec card tests passes: a click on `Plan changes` sends exactly 1 `{ verb: 'plan', kind: 'spec', id: <the card's spec id> }` request through `runAdoVerb`, and its exit-0 `plan --json` document opens the existing `AdoApplyDialog` with the plan's rows; the dialog's Confirm sends exactly 1 `{ verb: 'apply', confirm: <that hash> }`; a document with `"unavailable": true` shows the dialog's could-not-be-drawn-up state with 0 Confirm buttons; a plugin without `ado-plan` disables `Plan changes` with `newerPlugin('ado-plan')`.
- [ ] Source pins pass: 0 `useEffect` bodies under `studio/src/components/SpecCard/` or `studio/src/components/ado/` name `plan`; `studio/src/components/SpecCard/SpecCard.tsx` holds 0 `verb: '` literals; `git diff --name-only 325ac2b -- studio/electron` lists only the files Fold B4 changed; `grep -rn 'ado/local' studio/src | wc -l` prints `0` (gate G16).
- [ ] `git diff --exit-code 325ac2b -- <the protected list above>` exits 0; `git diff --diff-filter=M --name-only 325ac2b -- scripts/tests studio/test` prints only `studio/test/reasons.test.ts`; `grep -L boards_env scripts/tests/test_boards_*.py | wc -l` prints `0`; the four version files read `2.1.0` and `CHANGELOG.md` holds a `### Fold B6` block under the existing `## 2.1.0` heading.
- [ ] `uv run --project scripts pytest scripts/tests -q` exits 0, and `cd studio && npm ci && npm run typecheck && npm run typecheck:test && STUDIO_SKIP_LIVE_MODEL=1 npm test` exits 0 with `bundleSize` run, not skipped.

## Risk Tier
**Tier:** MEDIUM
**Why this tier:** `sync` and `plan` only read the board; the local files they write (a plan file, ledger lines, the hook status line) already exist for `pull` and `plan`. The one write to the external system stays Fold B3's `apply` handshake — a 12-hex plan hash, a human `--by`, `posture: assisted` — and the desktop app reaches it only through the apply dialog's existing Confirm, after a person's click drew the plan up. It is not LOW because it makes that write path one click closer for everyone with the desktop app, widens a closed table that was pinned as final, and changes what a working session does at its start: a catch-up that ran without asking would read a client's board, spend `az` calls and could chain into a plan nobody wanted. Nothing under `studio/electron/**` changes, so no security-gated path is touched. Undoing it is removing the verb, one union member and the prompts; no existing behaviour changes. The Pod Lead may raise it.

## Delegation Plan
- **Scope (file patterns):** the In-scope list above, package by package: B6-P0 contracts first; then B6-P1 (the `sync` verb), B6-P2 (catch-up prose) and B6-P3 (plan from the desktop) in parallel; B6-P4 (integration) last. A path a package card does not name is stop-and-ask.
- **Context (pattern to reuse):** `scripts/ado_sync.py`'s `pull` and `plan` verbs (matches `harness_context`) for the stages, `scripts/ado_sync_model.py` for every decision (`SYNC_STAGES`, `apply_next_line`, `SYNC_NODATA`, `hook_line`), and `studio/shared/adoVerbArgv.ts` with `runAdoVerb` for every desktop request; `studio/src/components/ado/AdoApplyDialog.tsx` is reused as it is.
- **Permissions:** auto-allowed: reads, `uv run --project scripts pytest …`, `uv run --project scripts scripts/check_spec.py`, `npx vitest run …`, `npm run typecheck`, `npm run typecheck:test`. Confirm-required: any edit outside a card's file list, any edit to a protected file or to a test that existed at `325ac2b`, running `az` (never in this Fold), and running `new_spec.py` (never for 0034 to 0038 or 0040).
- **Gated paths touched:** none. `studio/electron/**` and `harness/**` are untouched.

## Checking Plan
**Ladder depth:** MEDIUM
**Specifics:** CI runs the full plugin suite, the registry-agreement suites, the write argv golden (gate G13) and the whole desktop suite with `bundleSize` live (gate G15); the grader grades against the Acceptance Checks above; the Fold gates G1 to G17 of the build kit run after every package level merges; a non-author Checker confirms the protected core is byte-identical to `325ac2b`, that `AdoVerbRequest` has exactly 8 members with `plan` last and no `--by` on it, that no `useEffect` or session-start hook runs `sync`, `pull` or `plan` on its own, and that the command prose asks before every catch-up.

## Decision List
- **The closed table widens by exactly one read verb.** `AdoVerbRequest` gains `plan` and nothing else; the pinned count is 8, `plan` carries no `--by`, and no later Fold widens the table without a kit amendment (build kit K28). Owner decision 2026-10-15. Owner: @MCKRUZ. Answer: one read verb, `plan`.
- **A board catch-up is ask-first.** A command that would catch up with the board asks the person in one line and runs `ado_sync.py sync` only on a yes; `--discussion` is added only on the person's own ask. Owner decision 2026-10-15. Owner: @MCKRUZ. Answer: ask, then run.
- **Nothing reads the board on project open.** Opening a project, opening a spec card and starting a session read only local files; the session-start hook prints the cached hook line and spawns no `ado_sync.py`. Owner decision 2026-10-15. Owner: @MCKRUZ. Answer: no read without a person's click or yes.
- **One footer.** `comment`, `plan` and `sync` print the same `Next:` line, `ado_sync_model.apply_next_line(<hash>)`, wherever an apply is offered; a plan-only clone prints none. Owner: @MCKRUZ. Answer: one golden form, pinned in the model.
- **No version bump, and spec id 0040.** Fold B6 lands under the unshipped `## 2.1.0` heading with no version-file change; it takes spec id 0040 because 0039 is taken by another branch (build kit K13). Owner: @MCKRUZ. Answer: 2.1.0 unchanged, id 0040 written by hand.
