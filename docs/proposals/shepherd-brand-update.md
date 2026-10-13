# Proposal: Shepherd — the brand update

> **Status:** **Done** (2026-10-12) — Waves 0–6 executed on `feat/brand-update`; see the PR for the commit-by-commit record.
> Owner picks: palette **Furrow** (+ Spring as a second light accent), mark = the owner's chamfered two-tone frame with
> their two-tone S nested (baseline on the tab), type **Saira** (wordmark/display) + Inter (UI) + JetBrains Mono (code),
> Depth overlay kept at 30 %. Plugin id **`shepherd`** (`shepherd@mckruz`), repo `MCKRUZ/shepherd-sdlc`, Electron appId
> `com.mckruz.shepherd`. The brand record (approvals, boards, official exports, PPTX/PDF) lives in `docs/brand/shepherd/brandkit/`.
> **Branch:** `feat/brand-update` on `splashthree/claude-code-sdlc` (staging an upstream change; base `9d4fcb3`).
> **One line:** rename the plugin, its 32 commands (`/sdlc-*` → `/sprd-*`) and the desktop app to **Shepherd**,
> give it an earth-coloured identity (moss, lake, umber) proposed through Higgsfield, and keep every piece of
> methodology vocabulary (`.sdlc/`, the seven gates, "SDLC" as a noun) exactly where it is.
>
> Verified: every file:line below was checked read-only against the branch by five independent skeptic agents
> (≈190 claims confirmed, 14 corrected, ~40 surfaces added). Counts are indicative; `scripts/dev/rename_brand.py`
> re-derives them at run time rather than trusting this page.

---

## 0. The one idea

**Brand is a surface, not a schema.** Everything a person *reads* — the name, the commands, the hook banner,
the app, the marks, the colours, the guides — becomes Shepherd. Everything a project *stores* — `.sdlc/state.yaml`,
`specs/`, metrics ledgers, gate ids, exit-gate wording (hashed into confirmation ids) — stays byte-for-byte, so no
existing project migrates its data. The one mechanical seam is the slash-command prefix, and `/sprd-upgrade`
carries existing repos across it.

## 1. Decisions already taken (owner, 2026-10-11)

| Question | Decision |
|---|---|
| Product / app name | **Shepherd** (one name for plugin and desktop app; "Studio" is dropped) |
| Command prefix | `/sdlc` → `/sprd`, `/sdlc-<x>` → `/sprd-<x>` (32 commands) |
| Repo name | `splashthree/shepherd-sdlc` (owner renames on GitHub; every URL updated here) |
| `.sdlc/` state directory | **Kept** — the methodology, not the brand |
| Generic "SDLC" | **Kept** where it means the lifecycle; brand surfaces only |
| Palette | Earth: **green, blue, brown** |
| Brand tooling | Higgsfield — CLI 1.1.26 installed and signed in (lite plan, 250 credits). The MCP server is configured but did not connect this session; the `higgsfield-brandkit` **skill** drives the CLI (there is no `brandkit` subcommand) |

## 2. What changes, what stays

### 2a. Renamed — plugin

| Surface | Today → Becomes | Where |
|---|---|---|
| Plugin id | `claude-code-sdlc` → `shepherd-sdlc` *(§9 open call)* | `.claude-plugin/plugin.json:2,9-10`, `marketplace.json:10`, `SKILL.md:2,12`, `scripts/pyproject.toml:2,4` + `uv lock`; prose in README (title, L68 clone URL, L72-75 symlink names, L89, L296 tree, L312-315 ADR-001), CLAUDE.md:1, `docs/{agents,architecture,commands,gate-system,phase-lifecycle,profiles,scripts,templates-artifacts}.md` L3 intros, `docs/architecture.md:31-36,317`, `docs/scripts.md:102,1318-1320`, `references/acceptance-criteria.md:3`, `agents/sdlc-orchestrator.md:15`, five `profiles/*/claude-md-template.md:4`. ≈198 lines / 79 files repo-wide, about half in Studio (below) |
| Agent namespace | `claude-code-sdlc:<agent>` → `shepherd-sdlc:<agent>` | `commands/sdlc-intake.md:35`, `scripts/tests/test_document_summarizer_agent.py:58-59` (also builds the path `commands/sdlc-intake.md`), `specs/0027,0029,0030` (history — left), Studio `shared/types.ts:911`, `chatArgs.ts:40` fallback + 8 Studio test files (`chatArgs.test.ts:20,163` fixture and `:246` bare-id assertion included) |
| Marketplace / install | `mckruz` · `MCKRUZ/claude-code-sdlc` · `claude-code-sdlc@mckruz` → `splashthree` · `splashthree/shepherd-sdlc` · `shepherd-sdlc@splashthree` | `marketplace.json:2-7`, README:53-54, `release.yml:125`, `studio/README.md:245`, `docs/guide/togo-setup-guide.html:176-180`, `harness/README.md` (via kit map §6). **Not** the deliberate MCKRUZ URLs in Studio test fixtures (`redact.test.ts:37,102-103`, `githubHostArgv`/`mergeGate` owners) — the URL pass is scoped to manifests and docs |
| Slash commands | `/sdlc`, `/sdlc-*` → `/sprd`, `/sprd-*` | ≈1,160 lines / 200 files: commands 190, docs 454, references 99, scripts 71, phases 68, agents 33 (five have it in frontmatter `description:` L3), templates 15, harness 15 (kit map), profiles 16, hooks 4, SKILL/README/CLAUDE/RELEASING |
| Command files | `commands/sdlc-*.md` (32) → `commands/sprd-*.md` | `git mv`; ≈51 `commands/sdlc-*` path refs in 19 files; path-joined names the regex cannot see: `test_document_summarizer_agent.py:58`, Studio `draftTargets.ts:123` + `draftDocuments.test.ts:135`; `test_command_contracts.py:428-434` ALLOWLIST key `"sdlc-setup.md"`; `test_sdlc_next_confirmations.py:11`; bare filenames in `docs/architecture.md:74-80,325-330` |
| Markdown anchors | `(#sdlc-setup----…)` → `(#sprd-setup----…)` | `docs/commands.md:10-24` (15 TOC links; no test catches a dead anchor), `docs/hooks.md:17` |
| Bare command names | `command: sdlc-*` → `command: sprd-*` | `phases/activities.yaml` (29; validated against `commands/<name>.md` by `activities_model.py:129`), `test_activities_model.py:54-64,95,164`; Studio fixtures in the quoted TS form `command: 'sdlc-*'` — `GuideTab.test.tsx:21-22`, `activityTalk.test.tsx:10`, `focusedActivityHost.test.tsx:20,36`, `stageHomeTabs.test.tsx:16-17`, `workflowEmptyStep.test.tsx:20`, `ActivityPanelRouting.test.tsx:84`, `activitiesAdapter.test.ts:113`, `readinessActivities.test.ts:32` |
| Hook files | `hooks/sdlc-session-start.{sh,ps1}` → `hooks/shepherd-session-start.*` | `git mv` (keeps 100755; `test_executable_bits.py`), `hooks.json:8`, self-headers `.sh:2-3`/`.ps1:1`, `test_session_start_hook.py:29-30,59`, `docs/hooks.md:17,36-37,42,44,158`, `docs/architecture.md:95,297,418`, `docs/state-machine.md:479,662`, `docs/profiles.md:331`, `references/context-tiers.md:87` |
| Hook markers | `[SDLC]`, `[SDLC-PHASE]`, `[SDLC-SPRINT]`, `[SDLC-CONTEXT:*]`, `[/SDLC-CONTEXT:*]`, `[SDLC-CONVENTION]`, `[SDLC-HEALTH]` → `[SHEPHERD…]` / `[/SHEPHERD…]` | pattern `\[/?SDLC` (the closing tags at `.sh:143,163` / `.ps1:140,160` must move with the openers); `test_session_start_hook.py` (16 lines); docs: `docs/hooks.md`, `references/context-tiers.md:89-91`, CLAUDE.md:101, README:43, SKILL.md:65, `docs/architecture.md:300`, `docs/integrations.md:227`, `docs/state-machine.md:393,482`, `docs/templates-artifacts.md:714`, `phases/build-loop.md:126`, `templates/phases/00-discovery/phase1-handoff.md`. No script or Studio code parses them — model-facing only |
| Env var | `SDLC_CODE_HOST` → `SHEPHERD_CODE_HOST`, **old name still read** | Python: `code_host.py:40,118`, `gate_auth.py:137` (security-gated file, see §2c), `set_setting.py:52,450` (writes the name into `.sdlc/code-host.yaml`'s header), `handoff.py:16`; tests must `delenv` **both** names (`test_ado_fetchers.py:33`, `test_ado_import.py:32`, `test_gh_argv_golden.py:182`) + a new fallback-order test. Studio: `shared/codeHostModel.ts:21,146`, `electron/main/codeHost.ts:113`, `SettingsSections.tsx:15` ("from SDLC_CODE_HOST"), `codeHostModel.test.ts:78`, `codeHostResolve.test.ts:97-98`. Docs: README:126, `references/code-host-providers.md:34`, two commands, `docs/architecture.md:714`, `docs/scripts.md:1261`, setup guide :325. `SDLC_PLUGIN_ROOT` (`studio/test/pluginRoot.ts:49`) is test-only and **kept** |
| Printed hints (strings only) | `/sdlc-…` → `/sprd-…` | `doctor.py:165,556,588`, `upgrade_harness.py:183`, `advance_phase.py:12,208`, `audit_artifacts.py` (7), `stage_readiness.py:264`, `intake_documents.py:518`, `brief_candidates.py:27`, `map_deep_plan_artifacts.py:358-359` |
| Report footers + HTML report theme | `claude-code-sdlc — …` → `Shepherd — …`; the generated HTML reports' indigo/violet dark CSS → Shepherd palette | `generate_phase_report.py:121-129,304-316,617,631,717,737,1024-1035,1314,1320`, `generate_sprint_report.py:533-573,617`, `test_generate_sprint_report.py:132`. Text goldens (`generate_phase_report-*`) pin stdout, not HTML |
| Goldens (re-pinned) | 7 text goldens | `fixtures/golden/doctor-*.txt` (L3, L12), `upgrade_harness-*.txt` (L41/51/55). `golden_support.py` has no write mode — edit in step (paths are already `<REPO>`-normalised) |
| Templates copied into projects | `/sdlc-*` and "Studio" | `templates/frozen-layer.md:18` (re-injected every session), `templates/phases/build/{spec,sprint}.md:17,19`, `templates/phases/01-requirements/decision-log.md:7`, `templates/phases/03-foundation/pipeline-proof.md:6` ("Studio: Gather pipeline evidence"), `templates/team/_schema.yaml:7`, `templates/review-report.md:2` — 12 files |
| Other "SDLC Studio"/"Studio" in plugin text | → "Shepherd" | `commands/sdlc-next.md:36`, `docs/agents.md:265`, `docs/scripts.md:1271`, `phases/activities.yaml:3`, SKILL.md:100, `references/code-host-providers.md:42,60,83,142`, CLAUDE.md:19,63,72,86,101 (+≈20 bare "Studio"), `specs/README.md:1,3,25`, docstrings `capabilities.py:1-6,55`, `spec_readiness.py:15`, `activities_model.py:5` |
| `.github/` (security-gated) | "SDLC Studio", `togo-*` artifact, install hint, `/sdlc-` lines | `release.yml:1,65,97,119,125-126,131`, `grader.yml:97-102`, `studio.yml:1,3` (workflow *name* and header are safe; **job names at :57,122 are required checks and stay**), `dependency-scan.yml:146,156,175,178` |
| Version | 1.7.0 → **2.0.0** | `plugin.json:3`, `marketplace.json:12` (`test_release_manifest_agreement.py` pins agreement), **`studio/package.json:3` + `package-lock.json`** (electron-builder's `${version}`; otherwise the dmg is `Shepherd_0.1.0.dmg`), "plugin 1.7.0" meta lines in `docs/guide/*.html`, CHANGELOG top entry |

### 2b. Renamed — desktop app

| Surface | Today → Becomes | Where |
|---|---|---|
| Name | `PRODUCT_NAME = 'SDLC Studio'` → `'Shepherd'` (feeds Welcome h1, TopBand SR name, lockups); `<title>`, window title, `productName`, `artifactName` expands `${productName}` | `brand/TogoWordmark.tsx:8`, `index.html:27`, `electron/main/index.ts:946`, `electron-builder.json:3-4` |
| Sentences | 10 "SDLC Studio" + ≈56 bare "Studio" user-visible lines → "Shepherd" | `LifecycleHome.tsx:36`, `NewProjectScreen.tsx:77`, `GateAuthPanel.tsx:90`, `SettingsScreen.tsx:176,261,338`, `ExplainScorecard.tsx:153`, `AppearanceSection.tsx:54`, `ToolingIssues.tsx:30,141,143`, `today/TodayColumn.tsx:149-150`, `verbDialogModel.ts:121`, `DocumentView.tsx:307`, `SettingsSections.tsx:184-193`, `SignOffQuestions.tsx:91,94`, `BriefPicks.tsx:126`, `ExplainGates.tsx:56` (pinned by `e2e/board.spec.ts:303`), `SyncChip.tsx:40`, refusal strings in `electron/main/*.ts` |
| Plugin-not-found strings | `'claude-code-sdlc plugin scripts not found'` (≈45 lines in `index.ts:201-911`) + `NO_PLUGIN` consts → one `PLUGIN_ID` constant in `studio/shared/pluginId.ts` and messages built from it | `activities.ts:16`, `activityRuns.ts:20`, `briefForm.ts:19`, `draftBatch.ts:39`, `draftDocuments.ts:22`, `sprint.ts:24`, `project.ts:37-39`, `tooling.ts:1,243-244,257,274,292`, `package.json:5`; tests `sprintAdapter.test.ts:266-267`, `activityRunsAdapter.test.ts:402`, `briefMainCandidates.test.ts:100`, `pluginVersionMismatch.test.ts:29,40`, … |
| Plugin cache scan | `…/<ns>/claude-code-sdlc/<version>` → scans **both** `shepherd-sdlc` and `claude-code-sdlc`, newest version of the new id first | `tooling.ts:274` (today a single literal with no fallback and no test covering the scan — a packaged 2.0 app beside a not-yet-reinstalled plugin would otherwise show "no plugin") |
| Text that leaves the app | PR body "Saved from Shepherd.", PR-title fallback "Shepherd save …", branch prefix `shepherd/<ts>`, system prompt "Shepherd's chat panel" | `sync.ts:979,994-995` (in-flight PRs survive: `isOursToMerge` compares the exact stored `pendingPrBranch`, `sync.ts:1052-1080`), `chatArgs.ts:58`; tests `githubHostArgv.test.ts:15-22`, `codeHostProviders.test.ts:131,136`, `mergeGate` |
| Hard-coded `/sdlc-*` | 4 source sites + `commands/sdlc-review.md` path | `SignOffPanel.tsx:260`, `SpecCard/FindingsLedger.tsx:64`, `shared/sprintModel.ts:195-198`, `draftTargets.ts:123`; tests: 39 lines / 17 files (`sprintModel.test.ts:117-124`, `SprintBoard.test.tsx:264,282,435`, `e2e/activities.spec.ts:141-142` reads the real sibling plugin's guide text, `e2e/sprint.spec.ts:243`, …) |
| Generated brand SVGs | `aria-label "SDLC Studio — Steering"`, live `<text>SDLC Studio</text>` in Inter, header comments | `brand/figures/ccStaticSvg.ts:42,46,55,65,78,87-88,90-91` → `public/brand/cc/*.svg` (12) regenerated with `CC_WRITE_ASSETS=1 npx vitest run test/ccBrandAssets.test.ts`; `ccBrandAssets.test.ts:71` pins `>SDLC Studio<` |
| Brand components | `TogoMark/TogoWordmark/TogoLockup`, `TogoMarkVariant` → `ShepherdMark/…` | 3 files, `ui/contract.ts:241-248`, 6 source importers, `test/togoMark.test.tsx`; `TogoWordmark.tsx:1-2` carries the Tōgō rule "never a display serif", rewritten for §5c |
| Icon & splash | `public/favicon.ico` is a hand-placed Tōgō tile **outside** the deterministic pipeline (`index.html:5`, `index.ts:950`); preload splash is a white square on `#282c34` (`preload/index.ts:228,240`) | `build-assets.mjs` gains `studio/public/favicon.ico` as an output so determinism covers it; splash → tile on bark |
| Electron ids | `appId com.mckruz.sdlc-studio` → `com.splashthree.shepherd`. **userData is unaffected**: Electron names that folder from `package.json` `name` (`sdlc-studio`, kept — there is no `productName` in `package.json`), so settings, recent projects, `sync-objects/` (`settings.ts:101-103`) and localStorage stay where they are and **no migration code is needed**. Windows AUMID comes from `app.getName()` (`index.ts:93`) and is unchanged too | `electron-builder.json:3`; consequences in §7 |
| Metadata & CI | `studio/package.json:5` description, `studio/README.md:1-6,11,18,99,121,232,244-245,254-256,320-321,398-414`, `studio.yml:1,3,184`, `dependency-scan.yml` step names; screenshot script `test/screenshots/capture-observatory-v2.mjs:493` (`heading name: 'SDLC Studio'`) | — |
| Tests pinning the product name (Wave 3 gate) | `e2e/e2e.spec.ts:74` (`title toBe 'SDLC Studio'`), `welcomeScreen.test.tsx:29`, `topBand.test.tsx:36,128`, `ccFigures.test.tsx:113`, `todayColumn.test.tsx:113`, `appToolingGate.test.tsx:36`, `toolingIssuesOptional.test.tsx:24`, `appearance.test.tsx:171-172`, `SprintBoard.test.tsx:367`, `draftBatchPlan.test.ts:84,145`, `chatArgs.test.ts:186`, `activityTalk.test.tsx:63` | — |

### 2c. Kept on purpose

| Surface | Why it stays |
|---|---|
| `.sdlc/` directory, `specs/`, `.sdlc/metrics/*.jsonl` shapes, gate ids, **exit-gate wording** | Project data and the methodology's home. `sign_off_confirmations.py:56-60` hashes exit-gate wording into confirmation ids — rewording any exit gate orphans ticks. `phase-registry.yaml:37` is an *entry*-gate string, safe to touch |
| "SDLC" in prose, SKILL.md triggers ("start sdlc", "sdlc status"), manifest keyword/category `sdlc` | The lifecycle, not the brand; triggers keep working for people who say "sdlc" |
| `sdlc-orchestrator` agent name | It orchestrates the SDLC |
| `SDLC_CODE_HOST` (as fallback), `SDLC_PLUGIN_ROOT` (test-only) | Already in shells and CI |
| Studio internals: `package.json name sdlc-studio` (= userData folder + AUMID), `localStorage studio.*`, IPC `studio:*`, `STUDIO_*`/`TOGO_*` env, gradient id `togo-depth-*`, shader key `togo-body-v2`, MCP server `sdlc-studio-chat` (tool names `mcp__sdlc-studio-chat__*`), temp dir `sdlc-studio-claude`, `[Studio]` chat marker (`ActivitiesPanel.tsx:401` ↔ `chatArgs.ts:101`; it is shown verbatim in the chat transcript — acceptable, it labels the sender), `data-mark-*` test hooks | Never read as brand by a person; renaming only churns tests, and the folder name carries data |
| CI **job** names `studio.yml:57,122` | Registered required checks — renaming leaves PRs waiting forever (the file says so at L54-56) |
| `docs/proposals/*`, `specs/00xx-*` (incl. in-flight 0006/0016/0033), past CHANGELOG entries (incl. L86,122 brand links and L216 "plugin id unchanged"), `@MCKRUZ` handles, `profiles/creative-tooling/profile.yaml:4` company, `ci.yml:58` kit repo, `harness/profile/rails-telemetry.schema.json $id mckruz.dev`, `docs/feature-parity-analysis.md` | History, attribution, examples. Only the new 2.0.0 entry speaks. These paths are **excluded** from the mechanical pass |
| Author credit in `plugin.json` | MIT; Matt Kruczek remains author; `homepage`/`repository` move to the fork |

### 2d. Protected-core and security-gated touch list

`.github/workflows/security.yml:76-83` gates `advance_phase.py`, `gate_auth.py`, `install_harness.py`, `harness/`,
`studio/electron/`, `.github/` — the PR will carry a security review by construction.

| File | Lines | Change | Nature |
|---|---|---|---|
| `scripts/advance_phase.py` | 12, 208 | docstring + printed hint `Run /sprd to see…` | string only; no test pins it |
| `scripts/doctor.py` | 165, 556, 588 | header + fix hint | string only; 4 goldens re-pinned |
| `scripts/upgrade_harness.py` | 183 | appended-section note | string only; 3 goldens re-pinned. **No new logic** — the CLAUDE.md `/sdlc-*` section migration is a model step in `commands/sprd-upgrade.md` (D16) |
| `scripts/gate_auth.py` | 137 | read `SHEPHERD_CODE_HOST` then `SDLC_CODE_HOST` | **logic** (two-name env lookup) — new test; security review |
| `scripts/install_harness.py` | 4, 328 | docstrings | string only |
| `scripts/sync_kit.py` | new `RENAMES` + byte-level rewrite in copy **and** `--check` | **logic** (§6) — new `test_sync_kit.py` |
| `phases/phase-registry.yaml` | 37 | entry-gate doc string | string only |
| `harness/**` | 15 slash lines + id lines | **regenerated** via the kit map — will show a diff; guard is `sync_kit.py --check` IN SYNC, not an empty `git diff` | generated |
| `check_spec.py`, `check_gates.py`, `phase_model.py`, `new_spec.py`, `scorecard.py`, `generate_status.py`, `section-evaluator`, `templates/state-init.yaml` | — | **byte-identical** | `git diff --stat` empty |

## 3. The plugin rename — method (`scripts/dev/rename_brand.py`, re-runnable)

| Step | Mechanism | Guard |
|---|---|---|
| 1 | `git mv commands/sdlc*.md commands/sprd*.md`; `git mv hooks/sdlc-session-start.* hooks/shepherd-session-start.*` | `test_registry_docs_consistency.py:156` requires every `commands/<stem>.md` to appear as `/<stem>` in `docs/commands.md` — same commit |
| 2 | Boundary-safe substitution over `git ls-files` **minus** `CHANGELOG.md`, `docs/proposals/`, `specs/00*`, `scripts/.coverage`, `scripts/sync_kit.py`, `scripts/dev/rename_brand.py`: `(?<![\w.])/sdlc\b` → `/sprd` | Verified on today's tree: all 68 `[\w.]/sdlc…` path tokens are preceded by a word char and none match; all ≈1,160 matches are real command names (plus history-only `/sdlc-repair`, `/sdlc-triage`, `/sdlc-board` in excluded files). Untracked copies (`claude-code-sdlc/`, `.claude/worktrees/*`) never touched |
| 3 | Paths and bare names: `commands/sdlc-` → `commands/sprd-`; `command: sdlc-` and `command: 'sdlc-` → `sprd-`; `sdlc-session-start` → `shepherd-session-start`; markdown anchors `(#sdlc-` → `(#sprd-`; hand-edit the two path-joined names (`test_document_summarizer_agent.py:58`, `draftTargets.ts:123`/`draftDocuments.test.ts:135`) and `docs/architecture.md:74-80,325-330` | `activities_model.py:129` |
| 4 | Plugin id, in order, **scoped to manifests + docs + Studio source (not test fixtures with deliberate MCKRUZ URLs)**: `MCKRUZ/claude-code-sdlc` → `splashthree/shepherd-sdlc` → `claude-code-sdlc@mckruz` → `shepherd-sdlc@splashthree` → `claude-code-sdlc:` → `shepherd-sdlc:` → bare `claude-code-sdlc` in prose/error strings → manifest/SKILL `name` → `pyproject` + `uv lock` | `test_release_manifest_agreement.py:80-87` |
| 5 | Hook markers `\[/?SDLC` → `[SHEPHERD` / `[/SHEPHERD` in the two hook files, their tests and the 12 doc sites | `test_session_start_hook.py` asserts raw bytes of both files (L323-324) |
| 6 | `SHEPHERD_CODE_HOST` first, `SDLC_CODE_HOST` second — Python (`code_host.py`, `gate_auth.py`, `set_setting.py` header text) and Studio (`codeHostModel.ts`, `codeHost.ts`, `SettingsSections.tsx`); tests `delenv` both | new fallback-order tests (Python + vitest) |
| 7 | Hand edits: README, SKILL.md intro, CLAUDE.md, manifest descriptions, `release.yml`/`grader.yml`/`studio.yml`/`dependency-scan.yml`, five `claude-md-template.md` (L1/L4/L7), `commands/sprd-setup.md:132-140` fallback block, HTML report CSS in the two report generators | — |
| 8 | CHANGELOG `## 2.0.0 — <date>` + `## Migration — Shepherd` block (parser `^## (\d+\.\d+\.\d+)\b` ignores non-release headings; precedent at L1141). Past entries untouched | `test_release_manifest_agreement.py:59` |
| 9 | Untrack `scripts/.coverage` (binary SQLite with absolute paths) | `.gitignore` |

## 4. The desktop app — method

Everything in §2b, plus:

| Area | Change | Files |
|---|---|---|
| One id constant | `studio/shared/pluginId.ts` exports `PLUGIN_ID = 'shepherd-sdlc'`, `LEGACY_PLUGIN_IDS = ['claude-code-sdlc']`; messages and the cache scan use them | `tooling.ts`, 6 `NO_PLUGIN` consts, `index.ts`, `project.ts`, `ToolingIssues.tsx:30`, `chatArgs.ts:40` |
| Fonts | add `@fontsource-variable/fraunces` (import **`/standard.css`** — `wght.css` has no `opsz` axis), new `--font-display` token in `type.css`, wordmark uses it; Inter + JetBrains Mono unchanged | `package.json`, `package-lock.json`, `index.css:5-6`, `type.css:7-9`, `base.css:7` |
| Mark | `ShepherdMark.tsx` with new `MARK_GEOMETRY`, `DEPTH_GRADIENT` vector, and the draw-in hooks `data-mark-stem` / `data-mark-hook` (OpeningOverlay `:78-84` reads `[data-mark-bar]`/`[data-mark-disc]` and animates scaleX + stroke-dashoffset — updated for stem rise + hook trace) | `OpeningOverlay.tsx:78-84`, `openingOverlay.test.ts:59-63`, `welcomeScreen.test.tsx:35-39`, `steering.test.tsx:52-53`, `ccStaticSvg.ts:81,87-88` |
| Non-tokenised colours | 58 Tailwind `slate-*` classes in 20 files (`bg-slate-900` ×14, `text-slate-800` ×11, `bg-slate-50` canvas) → tokens; `dark.css:23` scrim `rgb(11 17 32)`, `:104-114` slate→navy remap, `:203-235` literal navy exceptions; `ui/Select.tsx:24-25` data-URI chevrons `%2364748B`/`%238392AA`; `scenes/core/materials/BodyMaterial.ts:89` rim `#334155`; `base.css:202-209` glow | — |
| Motion | `motion/presets.ts:65-67` "seam" (the Macron's gesture) — kept, re-described for the crook; `SignOffPanel.tsx:88`, `lanes/LaneCard.tsx:118` unchanged | — |

## 5. The identity — proposal (Higgsfield, three stops where the owner picks)

The brandkit skill is **palette → logo → typography → brandbook** and stops for an explicit human pick at each of
the first three. Review boards come from `brandkit.py preview` as HTML; PNG screenshots need Playwright Chromium
(not installed). **Plan: open the HTML boards directly at the three stops — no install needed to choose.** Installs
(D12) happen after the picks, before `logo-export` and the brandbook build. Logos: `higgsfield generate create
recraft_v4_1 --model_type vector … --resolution 2k`, **10 credits each** (verified with `generate cost … --prompt …`);
three concepts ≈ 30 of 250, one revision round ≈ 30 more.

### 5a. Palette — three boards

| Board | Primary accent | Secondary | Ground / warm neutral | Status-colour clash? |
|---|---|---|---|---|
| **P1 "Pasture" (recommended)** | Moss `#3F6B35` (6.2:1 on white) | Lake `#2F5D7C` (7.1:1) | Umber `#6B4A2B` (8.0:1) + sand/bark surfaces | Moss is dark olive; `stage_signed #16A34A` is bright emerald (3.3:1 on white) — same family, very different lightness. Judged on the board; fallback is P2 |
| P2 "Loam" | Umber `#6B4A2B` | Moss | Lake as information colour | None — brown shares no status hue |
| P3 "Lakeside" | Lake `#2F5D7C` | Moss | Umber ground | Lake is slate, `status_running #0EA5E9` is sky — distinct, but blue-on-blue on the Build board |

**P1 token sketch** (ramps finished by hand after the pick, like Tōgō's `palette.json`):

| Role | Light | Dark | Note |
|---|---|---|---|
| accent 50…900 | `#F3F7F0 #E3EDDD #C7E0BC #9DC58E #6FA55F #4F8545 #3F6B35 #2F5229 #243F20 #192D17` | remap: 600/700 unchanged, 800/900 → `#9DC58E #C7E0BC` (Tōgō's pattern) | primary = 600 |
| accent-text / focus | `#3F6B35` | `#9DC58E` (9.6:1 on dark-0) | `tokenContrast.test.ts:187` re-pinned (lowercase) |
| secondary (lake) 300/500/600/700 | `#8FB8D3 #3B739A #2F5D7C #244B66` | | links, steering tint, chart series 2 |
| umber 600/700/800 | `#7C5A36 #6B4A2B #553A21` | | warm emphasis, icon ground |
| surface 0…3 | `#F7F4EE #FFFFFF #EFEAE1 #E9E3D9` (sand) | `#14120F #1C1915 #25211C #2E2923` (bark) | surface-3 lightened so accent-text stays ≥ 4.8:1 on it (`#E6DFD3` gave 4.71 — too thin for the lane/plan pairs) |
| ink 1…4 | `#1C1915 #3D3630 #6B625A #A69D94` | | ink-4 is *decorative* by test: `tokenContrast.test.ts:171-172` requires < 3:1 on surface-1 (`#9C938A` is just over) |
| semantic (unchanged) | signed `#16A34A` · warn `#D97706` · error `#DC2626` · running `#0EA5E9` | | the four meanings never move |
| `--mark-depth-a/b` | `#9DC58E → #192D17` | `#9DC58E → #3F6B35` | one gradient, one vector, 48 px+ only (rule kept) |

`ui/tokenContrast.test.ts` **pins** 32 written ratio pairs (64 assertions) rather than merely checking — they are
re-pinned in Wave 4 along with the §2 numbers they cite from `togo-command-center-visual.md`.

### 5b. Mark — three concepts

| Concept | Idea | Why it fits | Pipeline fit |
|---|---|---|---|
| **A "Crook" (recommended)** | One stroke: a vertical stem ending in a hooked arc — the shepherd's crook, read also as the hook that *pulls a spec through the gates* | Single object like the Macron, so both sanctioned motions survive: draw-in (stem rises, hook traced, then fills) and seam | Stem rect + arc on the 64 grid, one axis at x 32; Depth vector stem→hook |
| B "Fold" | A low arc over three discs — the fold holding the flock (or Data/Design/Bizreq around the spec) | Warm, communal; reads at 16 px as arc + dots | Four shapes; tile uses arc + one disc |
| C "Hill & Star" | A low hill arc with one point above it — horizon and guiding star | Simplest; strongest as an app icon | Two shapes; weakest link to the name |

**How Recraft and the hand-drawn mark meet.** Recraft returns complex paths; the repo depends on clean
`MARK_GEOMETRY`, byte-identical SVG copies and one Depth vector. The skill forbids redrawing a *selected* Recraft SVG,
and `lock_authoritative_logo` is for an *owner-supplied official* logo. So: Recraft boards are **exploration**; the
chosen idea is redrawn as geometry (`mark-a-crook.svg` + `-ink`, `-white`, `-depth`; `tile.svg`, `tile-depth.svg`) and
the owner supplies that SVG as the official logo → `lock_authoritative_logo` (origin `user_supplied`, source = our
file). Alternates B and C ship as `mark-b-*` / `mark-c-*`. Tile geometry keeps a light centre pixel at 16 px
(`brandAssets.test.ts:78` samples (8,8) white) or that pin is re-pinned deliberately.

### 5c. Typography — three pairings

| Pairing | Display / wordmark | UI | Code | Why |
|---|---|---|---|---|
| **T1 (recommended)** | **Fraunces** variable (`standard.css`, opsz 72, wt 600, tracking −0.01em) | Inter Variable (kept) | JetBrains Mono (kept) | Pastoral warmth in the one place type is brand; zero UI regression — `cv11/ss01` and every type-scale token stay. Replaces Tōgō's "one face, never a display serif" rule (`TogoWordmark.tsx:1-2`) with "one UI face + one display face for the wordmark only" |
| T2 | Bricolage Grotesque variable | Inter | JetBrains Mono | Characterful grotesque; more "tool" than "field" |
| T3 | Source Serif 4 variable | Inter | JetBrains Mono | Quieter serif; the safe choice |

All three exist as `@fontsource-variable/*` 5.3.x and bundle under the CSP `font-src 'self'` (`index.html:24`). Every
brand SVG with live `<text>` — `wordmark.svg`, `wordmark-white.svg`, `lockup.svg`, and the generated
`cc/steering-lockup-depth.svg` (`ccStaticSvg.ts:90-91`) — gets **outlined** text so it renders without the font installed.

### 5d. Deliverables (mirror of Tōgō's set so tests and pipeline keep their shape)

| Path | Content |
|---|---|
| `docs/brand/shepherd/palette.json` | source of record: ramps, dark remap, ink, surfaces, focus, contrast figures, semantic-unchanged, typography |
| `docs/brand/shepherd/brandbook.html` | the 9 sections (name · mark A/Depth/tile/wordmark/lockup/B/C · construction & clear space · minimum sizes · colour · typography · voice · do/don't · file inventory). `brandbookConsistency.test.ts:56-59` derives required sentences from `build-assets.mjs` constants ("six PNG members, 16, 32 and 48 flat, 64–256 Depth.", "Depth from 64.", "flat at 16 and 32") — reproduced word for word |
| `docs/brand/shepherd/mark-*.svg`, `tile*.svg`, `wordmark*.svg`, `lockup.svg` | hand-drawn geometry, outlined text |
| `docs/brand/shepherd/build-assets.mjs` | today's script with `SHIPPED_SVGS`, `tileFor`, glob `mark-*/tile*` kept; names → `shepherd.ico`, `shepherd-tile-512.png`; **new output** `studio/public/favicon.ico`; still deterministic (`node … && git status --porcelain` clean — on the same librsvg version; CI never runs it, `brandAssets.test.ts` compares committed bytes) |
| `docs/brand/shepherd/exports/` | 70 PNGs + `shepherd.ico` |
| `docs/brand/shepherd/brandkit/` | Higgsfield record: `state.json` (**committed only with the owner's explicit yes — D17**), `reviews/*.html`, `logo/`, `brandbook/shepherd-brand-guidelines-v1.{pptx,pdf}` |
| `studio/build/icon.{png,ico,icns}`, `studio/public/brand/*`, `studio/public/favicon.ico`, `studio/public/brand/cc/*.svg` | generated |
| `docs/guide/shepherd-setup-guide.html` (hand-authored: own teal CSS ramp at :10-24, inline Macron :91-92, install block :176-183 whose sentence "the plugin keeps its id claude-code-sdlc" becomes false, :325, :563) and `shepherd-user-guide.template.html` (:16-38 CSS, :133-134 mark, :268, :538-541 "teal macron over a disc") | rewritten by hand; the user guide is then regenerated (§8 Wave 5) |

Tools the export needs and that are **not installed**: ImageMagick (`logo-export`, brandbook), Poppler
(`pdftoppm pdfimages pdffonts`), LibreOffice (`soffice`), Playwright Chromium (board PNGs). `rsvg-convert`, fontconfig,
node, python3 are present.

## 6. The harness — generated copy, handled without breaking the invariant

`harness/` is regenerated from `MCKRUZ/intent-driven-development` (`kit/`) by `scripts/sync_kit.py` (rmtree + copytree;
`--check` = byte-level `filecmp`), and `ci.yml`'s `sync-check` fails on any drift. Brand strings in the kit: installed
files `ONBOARDING.md:6,51,59,78,86`, `HARNESS.md:183`, `packs/cicd/azure-devops/RAILS.md:133`, `mcp.fragment.json:2`
(merged into the project's `.mcp.json`); not-installed `harness/README.md:18,22-27,68,86,164-165`,
`pack.yaml:129`, `stacks/dotnet/HARVEST.md:44`, `stacks/node-typescript/README.md:9`.

| Option | Verdict |
|---|---|
| Hand-edit `harness/` | ✗ CI red forever |
| Fork the kit and point `ci.yml` at it | ✗ heavy, splits the standard |
| **Teach `sync_kit.py` a rename map** — `RENAMES` = the §3 boundary regex `(?<![\w.])/sdlc\b` → `/sprd`, `MCKRUZ/claude-code-sdlc` → `splashthree/shepherd-sdlc`, `claude-code-sdlc@mckruz` → `shepherd-sdlc@splashthree`, bare `claude-code-sdlc` → `shepherd-sdlc`; applied **in place, as bytes, after copytree** (so `harness/*.sh` keep 100755 — `test_executable_bits.py`) and inside `--check` (invariant becomes `harness == rename(kit)`); never touches `harness/profile/*.json` `$id` | ✓ small, tested (`test_sync_kit.py`), upstream kit untouched |

Costs to say out loud: (1) Wave 2 needs a kit checkout — none exists locally (`../delivery-standard` absent); clone
`MCKRUZ/intent-driven-development` main as CI does, and **sync first as its own commit** so any kit drift since 1.7.0
is separate from the brand diff. (2) `sync_kit.py` diverges from upstream; every upstream merge touching `harness/`
needs a re-run before `sync-check` is green again — the rename script replays it. (3) Repos installed before the rename
classify `ONBOARDING.md`, `docs/harness.md`, `.github/RAILS.md` as UPDATE on the first `/sprd-upgrade`; adapted copies
become CONFLICT and are shown, not overwritten.

## 7. Backward-compatibility ledger

| Who | What breaks | What carries them |
|---|---|---|
| Users typing `/sdlc-*` | Commands no longer exist (no aliases — 64 commands is worse than one rename) | CHANGELOG migration block; `/sprd-upgrade` Step 4 (model-driven, D16) rewrites the `(auto-injected by /sdlc-setup)` CLAUDE.md section to `/sprd-*`; the session-start banner lists the new names every session |
| Installed plugin `claude-code-sdlc@mckruz` | New id → reinstall: `/plugin marketplace add splashthree/shepherd-sdlc`, `/plugin install shepherd-sdlc@splashthree`. On this machine `~/.claude/settings.json` `enabledPlugins` and `installed_plugins.json` still list the old id — uninstall it after | README + CHANGELOG |
| Project data | nothing — `.sdlc/`, specs, ledgers, exit-gate ids unchanged. Already-written artifacts (frozen layers, specs, sprint records) keep `/sdlc-*` in their prose — owner content, never rewritten | — |
| Shells/CI with `SDLC_CODE_HOST` | nothing — still read | docs list both |
| Hook-marker readers | only the model | — |
| Desktop (all) | settings, recent projects, `sync-objects/`, localStorage **stay** (userData folder unchanged) | — |
| Desktop (macOS) | new bundle id → Gatekeeper first-run again, folder-access (TCC) grants re-asked once, Keychain items re-created | CHANGELOG note |
| Desktop (Windows) | new `appId` → NSIS installs beside the old app; both share the userData folder so the single-instance lock (`index.ts:95`) means one runs at a time | CHANGELOG note; old app uninstalls normally |
| Desktop ↔ plugin version skew | a 2.0 app finds both `shepherd-sdlc` and `claude-code-sdlc` caches (prefers new); a 1.x app cannot find a 2.0 plugin | upgrade the app first |
| Repos with the old harness payload | `ONBOARDING.md` says `/sdlc-doctor` until re-synced | `/sprd-upgrade` re-installs the renamed payload |
| Upstream (MCKRUZ) | nothing — this is the fork's brand. Fork `master` stays mergeable: renames are mechanical and replayable | `scripts/dev/rename_brand.py` + `sync_kit.py` re-run after each upstream sync |

## 8. Rollout — waves (each wave is a PR-ready commit; Waves 2–5 are agent fan-outs with adversarial verification)

| Wave | Scope | Gate |
|---|---|---|
| **0 — Kit sync** | clone the kit, `sync_kit.py` (no rename yet), commit any drift separately; untrack `scripts/.coverage` | `sync_kit.py --check` IN SYNC; pytest green |
| **1 — Identity** | HTML boards: palette ×3 → **owner picks**; marks ×3 (30 credits) → **owner picks**; type ×3 → **owner picks**; redraw mark on the grid; `palette.json`; D12 installs; `logo-export`; brandbook export | three explicit picks; `brandkit/state.json` has all three approvals |
| **2 — Plugin rename** | §3 steps 1–9; `sync_kit.py` rename map; CHANGELOG 2.0.0; `rename_brand.py` kept | `uv run --project scripts python -m pytest scripts/tests -q`; `sync_kit.py --check`; `git grep -nP '(?<![\w.])/sdlc\b' -- . ':!CHANGELOG.md' ':!docs/proposals' ':!specs' ':!scripts/sync_kit.py' ':!scripts/dev' ':!scripts/tests/test_sync_kit.py'` → exit 1 (no matches; `-E` has no lookbehind and would exit 128 looking like "0 matches"; `test_sync_kit.py` pins the upstream strings on purpose) |
| **3 — App rename** | §2b + §4 id constant, cache scan, env fallback, product-name test re-pins, favicon/splash | `npm run typecheck && npm run typecheck:test && STUDIO_SKIP_LIVE_MODEL=1 npm test` |
| **4 — App identity** | tokens/dark/base/type/index.css + font packages; `ShepherdMark.tsx` + OpeningOverlay hooks; slate classes → tokens; cc figures regen; `build-assets.mjs` run → `build/icon.*`, `public/brand/*`, `favicon.ico`; re-pin `tokens.test.ts` (:58-65,102-106,126,146-154,216-217,229-240,304-305), `tokenContrast.test.ts` (32 pairs + :187), `ccVisualSpec.test.ts:104-129`, `brandAssets.test.ts` (:14,58,76-79,83,100,111,120), `ccBrandAssets.test.ts:59,69-71`, `shepherdMark.test.tsx`, `brandbookConsistency.test.ts:12-16,41-43`, `openingOverlay.test.ts:59-63`, `welcomeScreen.test.tsx:35-39`, `steering.test.tsx:52-53` | all of Wave 3 + `npm run test:e2e`; `node docs/brand/shepherd/build-assets.mjs && git status --porcelain docs/brand studio/public studio/build` clean |
| **5 — Docs & guides** | `brandbook.html`; setup guide by hand; user guide: rebuild app, re-capture screenshots (`SHOT_PREFIX=observatory-v30 node test/screenshots/capture-observatory-v2.mjs` — needs vite build, Electron, `scripts/.venv`, `gh` login; PNGs are gitignored), bump the prefix default in `build-user-guide.mjs:10,26` and the `:112` pin, run `node docs/guide/build-user-guide.mjs`; `docs/commands.md` (+anchors), `docs/architecture.md`, `docs/scripts.md`, `studio/README.md`; mark this proposal Done | `test_registry_docs_consistency.py`; `test_command_contracts.py`; dead-anchor check (`grep -o '(#[^)]*)' docs/commands.md` vs headings) |
| **6 — Verify & ship** | RELEASING.md order: suite → both manifests + `studio/package.json` at 2.0.0 → CHANGELOG → PR `feat/brand-update → master` on splashthree → tag `v2.0.0` after merge (`release.yml:57-64` requires tag == `plugin.json`); screenshots of Welcome, TopBand, Build board, Steering, light + dark; `npm run build` → `release/2.0.0/Shepherd_2.0.0.dmg`; owner renames the repo (GitHub redirects the old URL) | PR CI green incl. `sync-check` and the security review; brand screenshots attached |

Not in scope: the untracked working files at the repo root (`claude-code-sdlc/`, zips, `scratch-sprint/`,
`TOGO-PR-DESCRIPTION.md`, `onboarding-flow-map*`, `team-relevance-files/`, `operating-model/`). `profiles/plugin-self/`
and the root `.sdlc/` (except the tracked `.sdlc/team.yaml`, which has no brand string) are untracked; their four
`/sdlc-` lines get updated locally so this repo's own `/sprd-status` keeps working, but they are not committed.

## 9. The one open call — resolved (owner, 2026-10-11)

**Plugin id is `shepherd`**, installed as **`shepherd@mckruz`** (the marketplace stays `mckruz`; the repo becomes
`shepherd-sdlc`). One mechanical consequence the owner should know: Claude Code derives the agent namespace from the
plugin's `name`, and Studio reads the same manifest field for `--agent` (`chatArgs.ts:34-41`), so agents are
**`shepherd:<agent>`** — `shepherd-sdlc:<agent>` is not a separate choice. Every `shepherd-sdlc` in §2–§8 reads
`shepherd`; every `shepherd-sdlc@splashthree` reads `shepherd@mckruz`; URLs read `MCKRUZ/shepherd-sdlc`
(D3 updated). The id is one constant on each side (`plugin.json` / `studio/shared/pluginId.ts`).

## 10. Decisions with recommended defaults

| # | Decision | Default |
|---|---|---|
| D1 | Version | **2.0.0** everywhere incl. `studio/package.json` |
| D2 | `/sdlc-*` aliases | **None** |
| D3 | Marketplace name | **`mckruz`** (install `shepherd@mckruz`); author credit kept; URLs → `MCKRUZ/shepherd-sdlc` (owner decision 2026-10-11 — the fork branch stages an upstream change) |
| D4 | Hook markers | **`[SHEPHERD…]`** incl. closing tags |
| D5 | `SDLC_CODE_HOST` | **`SHEPHERD_CODE_HOST` first, old still read** (Python + Studio) |
| D6 | `sdlc-orchestrator` | **Keep** |
| D7 | Hook filenames | **Rename** via `git mv` |
| D8 | Electron `appId` | **`com.mckruz.shepherd`** (follows the §9 decision that this ships upstream); `package.json name` (userData folder, AUMID) **kept** — no migration code; macOS re-grants once, Windows side-by-side |
| D9 | Harness | **`sync_kit.py` rename map** (byte-level, in-place, boundary regex) |
| D10 | `docs/brand/togo/`, `docs/guide/togo-*` | **Removed / renamed** (history in git); proposals and specs untouched and excluded from the sweep |
| D11 | Recraft output | **Exploration only; redraw on the 64 grid; owner supplies that SVG as the official logo (`lock_authoritative_logo`)** |
| D12 | Brew installs (ImageMagick, Poppler, LibreOffice cask, Playwright Chromium) | **Install after the three picks** — needs your yes before brew runs |
| D13 | Palette / mark / type | **P1 Pasture · A Crook · T1 Fraunces + Inter + JetBrains Mono** — your picks at the three stops |
| D14 | Studio internals (`sdlc-studio` package name, MCP name, `studio.*` keys, CI job names, `[Studio]` marker) | **Keep** |
| D15 | Rename script | **Kept** at `scripts/dev/rename_brand.py` for replay after upstream syncs |
| D16 | CLAUDE.md `/sdlc-*` section migration for existing repos | **Model step in `commands/sprd-upgrade.md`**; `upgrade_harness.py` stays string-only |
| D17 | Commit `docs/brand/shepherd/brandkit/state.json` | **Yes** (the skill requires your explicit yes) |
| D18 | Plugin cache scan | **Both ids during 2.x**, new id preferred |
| D19 | Generated HTML reports (phase/sprint) | **Re-themed to Shepherd** (CSS strings only) |

## 11. Verification recipe

```bash
# plugin
uv run --project scripts python -m pytest scripts/tests -q
uv run --project scripts scripts/sync_kit.py --kit <kit-checkout>/kit --check
git grep -nP '(?<![\w.])/sdlc\b' -- . ':!CHANGELOG.md' ':!docs/proposals' ':!specs' ':!scripts/sync_kit.py' ':!scripts/dev'; echo "exit $?"   # expect 1
git grep -n 'claude-code-sdlc' -- . ':!CHANGELOG.md' ':!docs/proposals' ':!specs' ':!scripts/sync_kit.py' ':!scripts/dev' ':!studio/test'      # expect only LEGACY_PLUGIN_IDS
uv run scripts/validate_profile.py profiles/microsoft-enterprise/profile.yaml
uv run scripts/init_project.py --profile profiles/microsoft-enterprise/profile.yaml --target /tmp/shep && uv run scripts/doctor.py --repo /tmp/shep --offline
bash hooks/shepherd-session-start.sh | head -3        # banner reads [SHEPHERD] … /sprd-status
SHEPHERD_CODE_HOST=azure-devops uv run scripts/code_host.py --repo /tmp/shep --json; SDLC_CODE_HOST=azure-devops uv run scripts/code_host.py --repo /tmp/shep --json
# app
cd studio && npm ci && npm run typecheck && npm run typecheck:test && STUDIO_SKIP_LIVE_MODEL=1 npm test && npm run test:e2e
node ../docs/brand/shepherd/build-assets.mjs && git status --porcelain ../docs/brand ../studio/public ../studio/build   # clean
node ../docs/guide/build-user-guide.mjs && git status --porcelain ../docs/guide                                        # clean (same machine, same shots)
npm run build && ls release/2.0.0/                                                                                      # Shepherd_2.0.0.dmg
```
