---
spec: "0034"
name: "ado-boards-schema-and-config"
status: ready            # draft | ready | in-flight | merged | deferred
deferred_reason: ""      # required when status is deferred — why this spec was not built
type: feature            # feature | bugfix — a bugfix PR carries the `type:bugfix` label and
                         # must pass repro-gate: its new test FAILS against the pre-fix code
risk: MEDIUM
source: "docs/proposals/ado-boards-mirror.md (the Azure Boards mirror) and docs/proposals/ado-boards-mirror-build-kit.md section 5, Fold B1 (schema, config, transport seam)"
channel: ""              # optional — delivery surface (see channels/); blank = channel-agnostic
owner: "@MCKRUZ"
developer: "@MCKRUZ"
checker: ""              # non-author approval — filled at hand-off
team: "core"
harness_context: "scripts/ado_transport.py plus scripts/tests/ado_fixtures.py: one impure seam that spawns az, pure normalisers that read keys through ado_map._require and raise rather than default, and a FakeAz router keyed on the leading argv words that raises on any call it was not told about. The Boards mirror copies that shape: boards_contract.py is the pure vocabulary, ado_transport.invoke_body is the only new spawn path, and tests/ado_boards_fixtures.py adds the HTTP method to the route key and a read-only default."
created: "2026-10-12"
sprint: ""               # optional — sprint id (e.g. S07); written by /sprd-sprint slate, never by hand
next_owner: ""           # optional — who holds the next action; set by `handoff`, cleared by `ack`
eng_review: ""           # optional — pending | accepted | returned; Engineering verdict, recorded by name
data_review: ""          # optional — pending | accepted | returned | n-a (n-a needs a reason); Data verdict
depends_on: ""           # optional — comma-separated spec ids this spec builds on, e.g. "0007,0009"
---

# Spec 0034 — ado-boards-schema-and-config

<!--
  The durable per-change record of the Build loop. One spec = one branch = one PR.
  Fold B1 of the Azure Boards mirror. Validate with:
    uv run --project scripts scripts/check_spec.py --spec specs/0034-ado-boards-schema-and-config.md
-->

## Goal
A project on Azure DevOps can describe its Boards process to the plugin without the plugin writing anything to the board: `ado_sync.py discover` reads the process (types, states, fields, backlog levels, area and iteration trees, link types) through one new transport path into `.sdlc/ado/schema.json`, `.sdlc/ado.yaml` says how specs, epics, features and requirements map onto that process, and `ado_sync.py validate` prints how each level fits — as an item, an area or a tag — with the process additions an administrator could make.

## Why
The Boards mirror (Folds B2–B5) projects the repository's specs and requirements onto a client's board. Every later Fold needs the same three things first: a vocabulary every module agrees on, a picture of the client's process that was read rather than assumed, and a config file that can refuse an unsafe setting before anything is written. Doing those first, read-only, means the first time the plugin touches a real board it already knows which types, states and fields exist there, and a process that lacks a portfolio level degrades to tags instead of failing. The plugin never alters a process; it recommends.

## Scope

### In scope
- `scripts/boards_contract.py` (new, pure data: kinds, tree order, drift classes, ledger events, field ownership, tag prefixes, regexes, `.sdlc/` paths, `WIT_ROUTES`).
- `scripts/tests/ado_boards_fixtures.py` (new: `boards_env`, `az`, `FakeBoardsAz`, `load_wit`) and the fifteen hand-written fixtures under `scripts/tests/fixtures/code_host/azure_devops/wit/` (an Agile inherited process with a `Custom.RiskTier` picklist), plus `wit/synthetic/` processes for Scrum, CMMI and Basic.
- `scripts/ado_transport.py`: an append-only addition below `invoke()` — `invoke_body` and `check_api_version`; `invoke()`, `az_json()` and `run_az()` byte-identical.
- `scripts/ado_schema_map.py` (new, pure), `scripts/ado_sync_config.py` (new), `templates/ado/ado.yaml` and `templates/ado/_schema.yaml` (new), `scripts/ado_schema.py` (new, the discovery reads), `scripts/ado_sync.py` (new CLI skeleton: `config init`, `discover`, `validate`).
- New tests only: `scripts/tests/test_boards_*.py` and `scripts/tests/test_wit_fixture_provenance.py`.
- The Fold's integration edits: `scripts/capabilities.py` (`ado-config`, `ado-discover`, `ado-validate`), `CHANGELOG.md`, `CLAUDE.md` Testing lines, `docs/architecture.md` §7 (the dated owner amendment), the build kit's Status line, and this spec.

### Out of scope
- Any write to Azure DevOps: no create, update, link or comment verb, and no `--http-method` other than GET except the two read-only POSTs (`wit/wiql`, `wit/workitemsbatch`). Writes are Fold B3 (spec 0036, HIGH).
- Altering a client's process: `validate` prints recommendations; the plugin never adds a type, state, field or level.
- The protected core, byte-identical to `325ac2b`: `scorecard.py`, `generate_status.py`, `check_gates.py`, `check_spec.py`, `advance_phase.py`, `phase_model.py`, `new_spec.py`, `sprint.py`, `sprint_model.py`, `spec_transition.py`, `handoff.py`, `track_decisions.py`, `doctor.py`, `github_import.py`, `pipeline_proof_model.py`, `set_setting.py`, `spec_status.py`, `track_specs.py`, `ado_map.py`, `ado_import.py`, `ado_outcomes.py`, `ado_outcomes_map.py`, `host_report.py`, `code_host.py`, `gate_auth.py`, `phases/phase-registry.yaml`, `templates/state-init.yaml`, `agents/section-evaluator.md`, `commands/sprd-coach.md`, `commands/sprd-spec.md`.
- Any existing test or fixture, including `redact.py` and `test_fixture_provenance.py`; the desktop app (`studio/**`); the session-start hooks.
- Spawning a real `az` anywhere in the suite, and any UPN, e-mail address, display name, real GUID or comment text in a committed file.

## Acceptance Checks
- [ ] `uv run --project scripts pytest scripts/tests/test_boards_contract.py scripts/tests/test_boards_fixtures.py scripts/tests/test_wit_fixture_provenance.py -q` passes: `boards_contract` imports only `re` and `typing` (AST), `boards_contract.DISCIPLINE_AGENTS == audit_artifacts.DISCIPLINE_AGENTS`, the `WIT_ROUTES` keys are the ten discovery routes plus `workitem_create`, `workitem_update`, `comments`, `comment_versions`, `workitemsbatch`, `updates`, `connection_data` with every row `verified: False`, and `HANDLE_RE` accepts `@MCKRUZ`.
- [ ] In the same run: an unanswered route raises `AssertionError("unexpected az call: <route key>")`, `FakeBoardsAz(writes=False)` raises on `PATCH wit/workItems` and answers `POST wit/wiql`, `boards_env` makes `ado_transport.run_az` raise `AssertionError("az spawned")` and `ado_transport.az_binary()` return a path that does not exist, and the provenance test prints the 15 hand-written fixture names.
- [ ] `uv run --project scripts pytest scripts/tests/test_boards_transport_body.py scripts/tests/test_ado_import.py scripts/tests/test_ado_fetchers.py scripts/tests/test_ado_outcomes.py -q` passes: the `invoke_body` argv for GET, POST and PATCH is byte-equal to its golden with `--detect false` present and `-o json` as the last two elements; `check_api_version("7.1-preview.4")` raises and `check_api_version("7.1-preview")` returns it; the temporary body file is unlinked on success and when `run_az` raises; `inspect.getsource(ado_transport.invoke)` equals the constant in the test.
- [ ] `uv run --project scripts pytest scripts/tests/test_boards_schema_map.py -q` passes: deleting any key in `REQUIRED_KEYS` from a fixture raises `AdoImportError` naming that key; `resolve_state(schema, "User Story", "ready", {})` returns the last of the two Proposed states with the reason `rule: last-proposed`; a Bug `merged` resolves to `Resolved`; `resolve_type(schema, "decision", {})` returns `(None, "types.decision not set; candidates present in process: Issue")`; `refused_fields` includes every `Microsoft.VSTS.Scheduling.*` field and the backlog effort field.
- [ ] In the same run, `fit_levels` on the Agile fixture returns requirement `tag`, domain `area` for 3 of 4 domain names and `tag` for the fourth, and outcome `tag`; on a synthetic two-portfolio-level process with an `Objective` type all three are `item` with their level numbers; `recommendations()` is `[]` when every kind fits as an item.
- [ ] `uv run --project scripts pytest scripts/tests/test_boards_sync_config.py scripts/tests/test_shapes_cover_templates.py -q` passes: `templates/ado/ado.yaml` validates with 0 findings; an unknown key and `include_text: true` without `pii_reviewed_by` each return `level: refused`; `init_config` writes `.sdlc/ado/local/.gitignore` containing `*`; a second `init_config` without `force` raises `ConfigError(kind="invalid")`.
- [ ] `uv run --project scripts pytest scripts/tests/test_boards_sync_cli_b1.py -q` passes: `discover --json` over `FakeBoardsAz` writes `.sdlc/ado/schema.json` with sorted keys, no `@`, and no GUID other than area and iteration `identifier` values; every recorded argv carries `--detect false`; `fail={"workItemTypeCategories": "403"}` exits 1 naming the call; az not installed exits 1 with `cli_state: not_installed` in the host block and exactly 1 spawn.
- [ ] In the same run, `require_human("shepherd:feature-architect", "--by")` raises `Refused` (exit 2), `require_human("", "--by")` raises `Illegal` (exit 1), and `ado_sync.py <verb> --help` for every name in `ado_sync.VERBS` leaves an empty temporary working directory empty.
- [ ] `git diff --exit-code 325ac2b -- <the protected list above>` exits 0, `git diff --diff-filter=M --name-only 325ac2b -- scripts/tests studio/test` prints nothing, and `grep -L boards_env scripts/tests/test_boards_*.py | wc -l` prints `0`.
- [ ] `uv run --project scripts pytest scripts/tests -q` exits 0, and `uv run --project scripts pytest scripts/tests/test_release_manifest_agreement.py scripts/tests/test_capabilities.py scripts/tests/test_command_contracts.py scripts/tests/test_registry_docs_consistency.py scripts/tests/test_agent_references.py -q` exits 0 with the three new `capabilities.py` rows proven against `--help`.

## Risk Tier
**Tier:** MEDIUM
**Why this tier:** every verb in this Fold reads; nothing writes to Azure DevOps and nothing a person sees on a board changes, which alone would read LOW. It is MEDIUM because it adds a second spawn path to the one impure seam the code-host providers depend on (`invoke_body` writes a request body to a temporary file), and because the schema and config it produces are what the HIGH write Fold (B3) will trust. A wrong state or type mapping here becomes a wrong write later. Undoing it is deleting new files; no existing behaviour changes. The Pod Lead may raise it.

## Delegation Plan
- **Scope (file patterns):** the In-scope list above, package by package (B1-P0 contracts first; P1 transport, P2 schema map and P3 config in parallel; P4 discovery and CLI; P5 integration last). A path a package card does not name is stop-and-ask.
- **Context (pattern to reuse):** `scripts/ado_transport.py` and `scripts/tests/ado_fixtures.py` (matches `harness_context`): one seam spawns az, normalisers raise through `ado_map._require`, and the fake router raises on any call it was not told about.
- **Permissions:** auto-allowed: reads, `uv run --project scripts pytest …`, `uv run --project scripts scripts/check_spec.py`. Confirm-required: any edit outside a card's file list, any edit to a protected file or an existing test, running `az` (never in this Fold), running `new_spec.py` (never for 0034–0038).
- **Gated paths touched:** none.

## Checking Plan
**Ladder depth:** MEDIUM
**Specifics:** CI runs the full plugin suite and the registry-agreement suites; the grader grades against the Acceptance Checks above; the Fold gates G1–G11 of the build kit run after every package level merges; a non-author Checker confirms the protected core is byte-identical to `325ac2b`, reads one hand-written fixture against the REST reference, and confirms `discover` against `FakeBoardsAz` spawns no process.

## Decision List
- **The work-item fixtures are hand-written until the B0 capture.** Every `wit/` file says `hand-written (unverified)` and the provenance test lists them on every run; the capture lands under `wit/captured/` with the same names and replaces them with no code change. Owner: @MCKRUZ. Answer: write them now.
- **`WIT_ROUTES` is the single correction point.** Every `devops invoke` location starts `verified: False`; the B0 capture's `invoke_locations.json` corrects resource names and route templates there and nowhere else, and the B0 live capture of 2026-10-14/15 (see `scripts/tests/fixtures/code_host/azure_devops/wit/captured/CAPTURE-NOTES.md`) has since flipped `verified` to True on the rows it reached, so a row still marked `verified: False` is one the capture did not reach. Owner: @MCKRUZ. Answer: one table.
- **The test fake is read-only by default.** `FakeBoardsAz(writes=False)` refuses any write method outside the two read-only POSTs, and the native write verbs, even when an answer is registered; a write test opts in with `writes=True`. Owner: @MCKRUZ. Answer: refuse by default.
- **The plugin fits the client's process rather than requiring one.** A missing portfolio level falls back to an area path or a tag, and `validate` names the addition an administrator could make. Owner: @MCKRUZ. Answer: fit, recommend, never alter.
