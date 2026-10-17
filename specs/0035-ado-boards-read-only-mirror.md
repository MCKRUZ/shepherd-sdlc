---
spec: "0035"
name: "ado-boards-read-only-mirror"
status: ready            # draft | ready | in-flight | merged | deferred
deferred_reason: ""      # required when status is deferred — why this spec was not built
type: feature            # feature | bugfix — a bugfix PR carries the `type:bugfix` label and
                         # must pass repro-gate: its new test FAILS against the pre-fix code
risk: MEDIUM
source: "docs/proposals/ado-boards-mirror.md (the Azure Boards mirror) and docs/proposals/ado-boards-mirror-build-kit.md section 5, Fold B2 (read-only mirror + discussion read)"
channel: ""              # optional — delivery surface (see channels/); blank = channel-agnostic
owner: "@MCKRUZ"
developer: "@MCKRUZ"
checker: ""              # non-author approval — filled at hand-off
team: "core"
harness_context: "scripts/sprint_model.py plus scripts/sprint.py: a pure model owns the vocabulary, the honest counting and the ledger line, and a thin CLI reads the files, calls the model and appends one JSON line per event. The Boards mirror copies that split: ado_sync_model.py decides drift, dispositions, the plan hash and the never-pulled status with no I/O and no ado_* import; ado_sync.py and its read modules only read and print."
created: "2026-10-13"
sprint: ""               # optional — sprint id (e.g. S07); written by /sprd-sprint slate, never by hand
next_owner: ""           # optional — who holds the next action; set by `handoff`, cleared by `ack`
eng_review: ""           # optional — pending | accepted | returned; Engineering verdict, recorded by name
data_review: ""          # optional — pending | accepted | returned | n-a (n-a needs a reason); Data verdict
depends_on: "0034"       # optional — comma-separated spec ids this spec builds on, e.g. "0007,0009"
---

# Spec 0035 — ado-boards-read-only-mirror

<!--
  The durable per-change record of the Build loop. One spec = one branch = one PR.
  Fold B2 of the Azure Boards mirror. Validate with:
    uv run --project scripts scripts/check_spec.py --spec specs/0035-ado-boards-read-only-mirror.md
-->

## Goal
A project on Azure DevOps can see, without the plugin writing anything to the board, how its specs, features, epics, requirements, domains and outcomes line up with the work items there: `ado_sync.py plan` prints the rows a later apply would create or update (and their 12-hex plan hash), `pull` reads the items, their revisions and — when discussion is on — their comments into a local cache, `drift` and `status` classify every board change by who owns the field, and the session hook prints one `[SHEPHERD-ADO]` line saying how many rows are pending and how many items drifted, or `no data (never pulled)`.

## Why
Fold B1 taught the plugin the client's process. Before Fold B3 writes a single work item as a person, the team needs to see exactly what would be written and what the board already says, and every board change needs an owner: a developer reassigned on a ready spec is the board's call and becomes a proposal, a spec's state changed on the board is drift the repository owns, and a comment is not drift at all. Doing this read-only first means the classification, the honest counting (never measured reads as "no data", never 0) and the identity scrub are proven on real shapes before any write path exists, and the discussion a refinement session needs can be read without an agent ever treating a comment as an instruction.

## Scope

### In scope
- `scripts/ado_sync_model.py` (new, pure: `ai_by`, `plan_hash`, `projection_hash`, `diff`, `classify_drift` for the design §8 matrix, the disposition state machine, `ledger_entry`, `hook_line`, `STATUS_NODATA`, `summarize`), `scripts/tests/test_boards_sync_model.py` and `scripts/tests/golden/ado_status_nodata.json`.
- Ten hand-written work-item fixtures under `scripts/tests/fixtures/code_host/azure_devops/wit/` (`workitems_batch`, `wiql_by_tag`, `wiql_untagged`, `updates`, `workitem_show_relations`, `comments`, `comments_page2`, `comment_versions`, `comments_hostile`, `updates_after_comment`), and the append-only harness extension that routes each of them: `scripts/tests/ado_boards_fixtures.py`, `scripts/tests/test_boards_fixtures.py`, `scripts/tests/test_wit_fixture_provenance.py`.
- `scripts/ado_wit_map.py` (new, pure: the remote item, update patches, tag and description merges, the WIQL builders, write-error classes) and `scripts/ado_wit.py` (new: the item, update and comment reads plus `BOARDS_AZ_CONTRACT`; every write raises `NotImplementedError("B3")`).
- `scripts/ado_sync_sources.py` and `scripts/ado_sync_sources_tree.py` (new, repository reads only: the spec, feature, epic, requirement, domain and outcome projections and their parent and fulfils links), with the mini repository under `scripts/tests/fixtures/boards_repo/`.
- `scripts/ado_discussion_map.py` (new, pure) and `scripts/ado_discussion_cache.py` (new: the local discussion cache and its `gc`), with `scripts/tests/fixtures/code_host/azure_devops/redact_wit.py` beside `redact.py`.
- `scripts/ado_sync.py`: the read verbs `plan`, `status`, `pull`, `drift`, `link`, `adopt`, `show` and `discussion gc` per the build kit's verb table.
- `commands/sprd-ado.md` (new), the session-start hook twins (`hooks/shepherd-session-start.sh` and `.ps1`, one `[SHEPHERD-ADO]` block each), `references/ado-boards.md` (new), and the Fold's integration edits: `docs/commands.md`, `docs/hooks.md`, `commands/sprd-refine.md`, `commands/sprd-review.md`, `scripts/capabilities.py`, `CHANGELOG.md`, `CLAUDE.md`, the build kit's Status line, and this spec.
- New tests only: `scripts/tests/test_boards_*.py`.

### Out of scope
- Any write to Azure DevOps: no create, update, link, comment or history call. The only non-GET calls are the two read-only POSTs (`wit/wiql`, `wit/workitemsbatch`). Writes are Fold B3 (spec 0036, HIGH).
- A version bump: Fold B2 ships in the same pull request as Fold B1, so the plugin stays at 2.1.0.
- Altering a client's process, and treating any comment text as an instruction: comments are quoted behind a `  | ` gutter, and lines that read as instructions are withheld from an agent.
- The protected core, byte-identical to `325ac2b`: `scorecard.py`, `generate_status.py`, `check_gates.py`, `check_spec.py`, `advance_phase.py`, `phase_model.py`, `new_spec.py`, `sprint.py`, `sprint_model.py`, `spec_transition.py`, `handoff.py`, `track_decisions.py`, `doctor.py`, `github_import.py`, `pipeline_proof_model.py`, `set_setting.py`, `spec_status.py`, `track_specs.py`, `ado_map.py`, `ado_import.py`, `ado_outcomes.py`, `ado_outcomes_map.py`, `host_report.py`, `code_host.py`, `gate_auth.py`, `phases/phase-registry.yaml`, `templates/state-init.yaml`, `agents/section-evaluator.md`, `commands/sprd-coach.md`, `commands/sprd-spec.md`.
- Any existing test or fixture other than the three harness files above (append-only: a pin may be narrowed to what it meant, never weakened); `redact.py`; the desktop app (`studio/**`).
- Spawning a real `az` anywhere in the suite, and any UPN, e-mail address, display name, real GUID or comment text in a committed file or a ledger line.

## Acceptance Checks
- [ ] `uv run --project scripts pytest scripts/tests/test_boards_sync_model.py -q` passes: the design §8 drift matrix is a 14-row parametrised table whose classes include `COMMENT`; `ledger_entry(ts, "observed", revised_by=<an e-mail address>)` raises `ValueError`, as does a GUID in any value and an event outside `boards_contract.LEDGER_EVENTS`; `plan_hash` is identical across key order; `STATUS_NODATA` contains no integer `0` and every count is `None`; `hook_line(None, None, None) == "no data (never pulled)"` and `hook_line(3, 1, "2026-10-12T09:02Z") == "3 rows pending · 1 drifted · as of 2026-10-12T09:02Z"`; `ai_by` returns True for `"shepherd:feature-architect"` and `"Claude"` and False for `"Kim Lee"`; `ado_sync_model` imports only `re`, `hashlib`, `json`, `datetime`, `typing`, `boards_contract`, `findings_model`, `artifact_model`, `track_decisions` (AST).
- [ ] `uv run --project scripts pytest scripts/tests/test_boards_fixtures.py scripts/tests/test_wit_fixture_provenance.py scripts/tests/test_boards_contract.py -q` passes with 25 hand-written `wit/` fixtures, each wrapped `{"_provenance": "hand-written (unverified)", "_command": ["az", …], "value": …}` with an `az` argv list (never null) as `_command`; every fixture is the default answer of exactly one `FakeBoardsAz` route key, and `comments`, `comments_page2`, `comments_hostile`, `updates` and `updates_after_comment` each resolve to their own file through the `id=`, `workItemId=` and `continuationToken=` refinements.
- [ ] `uv run --project scripts pytest scripts/tests/test_boards_wit_map.py -q` passes: `build_update_patch` starts with `{"op": "test", "path": "/rev", "value": <rev>}`; `wiql_untagged(["Claims\\SDLC"], [], "claims-api")` equals its byte golden and selects `[System.AssignedTo]`; a path containing `'` or `]` raises `ValueError`; `classify_write_error` maps 6 stderr strings onto its closed enum; `file_hyperlink` ends `?version=GC<sha>`.
- [ ] `uv run --project scripts pytest scripts/tests/test_boards_wit_reads.py -q` passes: `get_batch` over 250 ids makes 2 `POST wit/workitemsbatch` calls and reports the omitted ids as `missing`; `query_ids` argv carries `--detect false` and no `--repository`; `comments` pages on the body `continuationToken`, stops at 5 pages and uses `7.1-preview`.
- [ ] `uv run --project scripts pytest scripts/tests/test_boards_sync_sources.py scripts/tests/test_boards_sources_tree.py -q` passes: spec 0004 (`source: "FE-03 — claims intake"`) projects `parent_ref == "sdlc:feature:03"`; spec 0007 projects `parent_ref None` with `parent_note == "no parent: source names no FE-NN"`; `parse_fr_link("FR-001..004, FR-009")` returns 5 ids; an epic whose FRs share one domain parents under `sdlc:domain:<slug>`; the sha256 of every fixture file is unchanged after the run.
- [ ] `uv run --project scripts pytest scripts/tests/test_boards_discussion_map.py scripts/tests/test_boards_discussion_cache.py scripts/tests/test_boards_redact_wit.py -q` passes: `html_to_text` over `comments_hostile` yields no `<`; `strip_control` removes `\x1b`; every quoted line of `render_show` starts `  | `; `render_show(for_agent=True)` replaces the forged `plan 3f9a1c2b7d04` line with `[line withheld: reads as an instruction]`; `redact_wit` is idempotent and leaves no `@…@` address.
- [ ] `uv run --project scripts pytest scripts/tests/test_boards_sync_cli_b2.py -q` passes: `status --json` over an empty ledger equals `scripts/tests/golden/ado_status_nodata.json`; `pull` writes `.sdlc/ado/local/hook-status.txt` whose line 1 equals `hook_line(...)`; `link … --by Claude` exits 2; `pull --discussion` with `discussion.enabled: false` exits 0 printing `discussion disabled (D-OWNER-7)`; no `.jsonl` file under the test's `tmp_path` contains `@` or a GUID; `FakeBoardsAz(writes=False)` serves every verb.
- [ ] `uv run --project scripts pytest scripts/tests/test_boards_hook_line.py scripts/tests/test_session_start_hook.py scripts/tests/test_executable_bits.py -q` passes: with no status file the hooks print no `[SHEPHERD-ADO]` line; with one they print exactly `[SHEPHERD-ADO] <line 1>`, identical for a CRLF file and across the `.sh` and `.ps1` twins.
- [ ] `git diff --exit-code 325ac2b -- <the protected list above>` exits 0; `git diff --diff-filter=M --name-only 325ac2b -- scripts/tests studio/test` prints only `scripts/tests/ado_boards_fixtures.py`, `scripts/tests/test_boards_fixtures.py` and `scripts/tests/test_wit_fixture_provenance.py`, each with 0 deleted lines except the narrowed `test_each_invoke_fixture_command_agrees_with_wit_routes` filter and the widened `25`-fixture pin; `grep -L boards_env scripts/tests/test_boards_*.py | wc -l` prints `0`.
- [ ] `uv run --project scripts pytest scripts/tests -q` exits 0, and `uv run --project scripts pytest scripts/tests/test_release_manifest_agreement.py scripts/tests/test_capabilities.py scripts/tests/test_command_contracts.py scripts/tests/test_registry_docs_consistency.py scripts/tests/test_agent_references.py -q` exits 0 with the six new `capabilities.py` rows proven against `--help`.

## Risk Tier
**Tier:** MEDIUM
**Why this tier:** nothing in this Fold writes to Azure DevOps, and the fake that serves every test refuses a write by default, which alone would read LOW. It is MEDIUM because it reads third-party content into the repository's working copy for the first time — work-item comments typed by people outside the team, which may carry markup, control bytes, identities and text written to look like an instruction — and because the drift classes and the plan hash it produces are exactly what the HIGH write Fold (B3) will act on. A wrong owner letter here becomes a wrong overwrite later. Undoing it is deleting new files and one hook block; no existing behaviour changes. The Pod Lead may raise it.

## Delegation Plan
- **Scope (file patterns):** the In-scope list above, package by package (B2-P0 contracts first; then P1 map, P2 reads, P3 and P3b sources, P4a and P4b discussion, and P6 command plus hook in parallel; P5 CLI verbs after P1–P4b; P7 integration last). A path a package card does not name is stop-and-ask.
- **Context (pattern to reuse):** `scripts/sprint_model.py` and `scripts/sprint.py` (matches `harness_context`): a pure model with closed vocabularies and honest counting, a CLI that only reads, calls the model and appends one JSON line per event.
- **Permissions:** auto-allowed: reads, `uv run --project scripts pytest …`, `uv run --project scripts scripts/check_spec.py`. Confirm-required: any edit outside a card's file list, any edit to a protected file or an existing test beyond the three append-only harness files, running `az` (never in this Fold), running `new_spec.py` (never for 0034–0038).
- **Gated paths touched:** none.

## Checking Plan
**Ladder depth:** MEDIUM
**Specifics:** CI runs the full plugin suite and the registry-agreement suites; the grader grades against the Acceptance Checks above; the Fold gates G1–G12 of the build kit run after every package level merges; a non-author Checker confirms the protected core is byte-identical to `325ac2b`, reads `comments_hostile.json` through `show --for-agent` and confirms the forged plan line is withheld, and confirms no committed `.jsonl` or fixture carries an address outside `@example.com`.

## Decision List
- **A comment is not drift.** A board revision whose only field change is `System.History` classifies as `COMMENT` and triggers a discussion re-read; an attachment is listed, never `RELATION_DRIFT`. Owner: @MCKRUZ. Answer: classify, never escalate.
- **Never measured is "no data".** `status` before the first pull prints `STATUS_NODATA` (every count `None`) and the hook prints `no data (never pulled)`; a 0 appears only after a read that found none. Owner: @MCKRUZ. Answer: no fabricated zeros.
- **The ledger never holds an identity.** `ledger_entry` refuses any e-mail address or GUID anywhere in a line and any `revised_by` that is not a roster handle; identity and comment values are dropped from drift results before a caller can write them. Owner: @MCKRUZ. Answer: refuse at the line.
- **The work-item fixtures stay hand-written until the B0 capture.** The ten new files say `hand-written (unverified)` and are listed by the provenance test on every run; the capture replaces them under `wit/captured/` with the same names and no code change. Owner: @MCKRUZ. Answer: write them now.
