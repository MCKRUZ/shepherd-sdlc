# Proposal: Data Specs — a spec for the data a build spec needs

**Status:** Design, 2026-10-15. The interfaces and the build packages are pinned in `docs/proposals/data-specs-build-kit.md`; where this document and the kit disagree, the kit wins for the build.
**Author:** drafted 2026-10-15 against Shepherd 2.0.0 (`master` at `c53c232`), from a teammate's issue. The issue's drafts predate the `/sprd-*` rename and the 2.0.0 numbering; this document uses the current names throughout.
**Related:** `specs/0039-data-specs.md` (the spec), `references/data-specs.md` (the contract a reader or an agent loads), `docs/proposals/sprint-team-layer.md` (the layer this reuses), `commands/sprd-data.md`, `agents/data-analyst.md`.
**Build target:** this repository (the plugin). Nothing built here touches a code host, a data platform or a credential.

---

## In brief

A **data spec** is the data team's own spec: a spec with `type: data` and `serves: "<parent id>"`, linked both ways to the build spec it serves, carrying a `## Context` section that lists every business rule, decision, decision record and intake document the parent cites, worked through `/sprd-data` into six documents, and done only when its pre-seeded acceptance checks say the data really flows. `DL-NN` and spec ids can no longer collide with an unmerged branch. Letting the agent read a data platform (`--live`) and a cheat-sheet per platform (packs) are designed here and deliberately not built.

## Problem

Seven problems, in the order a data engineer meets them.

| # | The problem | What it costs |
|---|---|---|
| 1 | A build spec says what to build and nothing about where its data lives, how it is prepared, or what serves it. | The build team guesses at tables and columns, or finds the gap in review. The answer sits in somebody's head. |
| 2 | The data team has no spec. Nothing tells them what the build needs, in what shape, ahead of what. | Data work happens beside the backlog instead of in it, so the sprint layer cannot slate it, order it, or give it a non-author checker. |
| 3 | Business rules (`BR-NN`), decisions (`DL-NN`), decision records (`ADR-NNN`) and intake documents (`DOC-NNN`) exist, but nothing connects them to a data deliverable. | An engineer re-reads the project to find the three rules and one vendor document that bear on one table, or misses one. |
| 4 | `/sprd-data` stops at interview documents: the contract, readiness and lineage. There is no dictionary of what each input means and how it was measured, no memo of why option X won, no one-page handoff of how to call the result. | The reasoning lives in a chat; the build team has no page to read. |
| 5 | Nothing proves the data works. A pipeline can run green while its serving object returns no rows, and a profile number can be pasted with no query behind it. | The same "assumed, not tested" failure `pipeline_proof.py` exists to catch for delivery rails, with nothing to catch it for data. |
| 6 | `depends_on` and `data_review` already exist on every spec and the sprint layer reads both, but no tool fills them and no spec is marked as data work. | Build order cannot put data first, because nothing says the build spec depends on it; the Data verdict is written by hand or not at all. |
| 7 | `DL-NN` and spec ids collide across branches. `track_decisions.py open` and `new_spec.py` read only the current checkout, so two branches allocate the same `DL-07`, or the same `0034`. | Two different decisions under one id, found at merge or never. This feature's own spec is numbered 0039 by hand because 0034–0038 exist only on the `ado-boards-mirror` branch: the collision it fixes. |

## Decisions

The kit's §1 is the pinned form. This is the same set with the reasons written out. D1, D2, D4 and D10 were settled by the requesting owner on 2026-10-15 and are recorded in the Decision List of spec 0039; the rest are this design's own, and a reviewer may overturn them.

| # | Decision | Why |
|---|---|---|
| D1 | A data spec is marked by the existing `type` field set to `data`, plus a new `serves: "<parent id>"` key. There is no `kind:` field. | `type` is already the field a spec uses for its class (`feature`, `bugfix`), so a data spec is one more class, not a new axis. `kind` already names three other things in this codebase (an activity's kind in `phases/activities.yaml`, the `kind` on a transition error, and `--kind` on the sprint report); a fourth meaning would make every search for it ambiguous. `serves` is new because nothing existing says which spec this one exists for. |
| D2 | The work lives in a new `scripts/data_spec.py` over a pure `scripts/data_spec_model.py`. `new_spec.py` is imported (`next_spec_id`, `render_spec`, `slugify`, `SPEC_FILE_RE`) and never edited. | `new_spec.py` is protected core and an existing test pins its `--json` document to exactly `path`, `id`, `name`, `risk`; a `--type` flag or a `serves` key would break that pin on purpose. Importing it gives id allocation and template rendering unchanged. The model imports no `subprocess` and no `argparse`, so every rule is a unit test and the CLI stays thin. |
| D3 | The link runs from the parent: the parent's `depends_on` gains the data spec's id, and the data spec's `serves` points back. One call writes both. | `sprint_model.build_order` already orders by `depends_on`, so the data spec is built first with no new ordering logic. A parent slated without it is warned about, and the ready rule already refuses a slate whose dependency is outside it and unmerged. The back-pointer makes the link findable from either end and lets `status` report a half-made one (`parent_depends_on_has_me`). |
| D4 | Linking moves the parent's `data_review` to `pending` only from `""`, `n-a` or `returned`; `pending` stays; **`accepted` is kept** and the result carries `data_review_note`. The tool never writes `accepted`: that stays `sprint.py verdict --lane data --verdict accepted --by <named human>`. | The Data verdict is a named person's act. A tool that reset `accepted` would silently undo it; a tool that wrote `accepted` would forge it. The three unanswered states become `pending` because data work now exists and the old answer no longer holds. The existing verb already refuses an AI `--by`, so nothing new is needed to keep the rule. |
| D5 | `track_decisions.py open --all-branches` is an additive flag. It reads the decision log on every **local** ref (`refs/heads`, `refs/remotes`) through `git show` and never fetches; its help says "run `git fetch` first". Without the flag, output is byte-identical to today. | The collision is in the allocator, so the fix is in the allocator. A flag rather than the default because reading every ref costs more than reading one file, and remote refs are only as fresh as the last fetch: the tool should neither reach for the network behind a person's back nor pretend to be current. Existing goldens pin the unflagged output. `track_decisions.py` is not in the protected core (spec 0021 added its verbs), so it can take an additive edit. |
| D6 | `data_spec.py new --all-branches` applies the same scan to spec ids, with `git ls-tree <ref> specs/`. | Spec ids collide the same way, and this very branch is the evidence. |
| D7 | The data-spec template keeps the `# Spec NNNN — <title>` heading and every placeholder literal that `spec.md` has. | `new_spec.render_spec` then fills it unchanged: no new rendering code, and a data spec is filled and checked by the machinery every spec already uses. `check_spec.py` ignores unknown frontmatter keys and extra sections, so the Definition of Ready applies as it stands. |
| D8 | `## Context` is one section-anchored shape field and `## Deliverables` is one table field. | Same reasoning as `spec.shape.yaml`: list-marker labels such as `**Business rules:**` cannot be inline fields, so the whole section is the field. Rewriting `## Context` in place is `data_spec_model.replace_section_body` — the span from the end of the `## Context` line to the next `## ` heading, with every other byte and the line endings untouched; the shape is for reading and editing the document, not consulted at write time. |
| D9 | No version bump. `CHANGELOG.md` gets `## Unreleased`. | 2.1.0–2.5.0 are claimed by Boards folds that have not merged, so any number chosen now may collide: the same family of problem as problem 7. Numbering is decided at release. |
| D10 | `--live` and platform packs are written up in this document and not built. The `data-analyst` agent's tools stay `Read, Write, Edit, Grep, Glob`. | Giving an agent a shell against a client data platform is a security posture for the owner to set, not a package for a builder to finish. Deferring keeps the agent's tool list pinned, and every unmeasured number reads `not measured` in the meantime. |
| D11 | Spec 0039's id is written by hand, never allocated with `new_spec.py`; its tier is MEDIUM. | Allocating it on a branch is exactly the collision problem 7 describes. MEDIUM because every write lands in the repository's own files through targeted edits, with no code host, platform, credential or gated path; not LOW because it changes `track_decisions.py`, which every command that opens a decision relies on, and a wrong `depends_on` edit would silently reorder what the sprint layer builds first. |

## What ships

Rows 1, 2, 3, 6 and 7 of the kit's executive table. Rows 4 and 5 are the two Deferred sections below. The exact contracts (signatures, JSON keys, exit codes, golden strings) are the kit's §3; this table says where each piece lands.

| # | Piece | In one sentence | How it lands |
|---|---|---|---|
| 1 | Data spec and link | A data-homework card stapled to the build card it serves. | `templates/phases/build/data-spec.md` and its shape: the spec frontmatter plus `type: data` and `serves`, and sections Goal, Why, **Context**, Scope, Acceptance Checks, **Deliverables**, Risk Tier, Delegation Plan, Checking Plan, Decision List. `data_spec.py new` creates one; `target` turns an existing spec into one; `status` lists them read-only and says whether each link is whole and whether acceptance is due. `data_spec_model.link_parent` writes the parent's `depends_on` and `data_review` through `sprint_model.set_frontmatter`, so only those two lines change and their trailing comments survive. |
| 2 | Context section | The card lists every rule, decision and document it must respect. | `cited_refs` reads the parent's body for `BR-`, `DL-`, `ADR-` and `DOC-` references; each is resolved to the Markdown file that defines it, searching `.sdlc/artifacts`, `.sdlc`, `docs`, `specs` in that order; `render_context` writes the block. A reference that cannot be found says `not found in this repository`: a guessed path would be worse than a gap, because a person would trust it. `/sprd-data` loads Context first (a new step 1a), and `check`'s `context-coverage` names any cited reference Context lacks. |
| 3 | Three new documents | What each field means, why we chose X, how to use the result. | `data-dictionary.md`, `decision-memo.md` and `data-handoff.md` join the three existing data documents under `templates/phases/02-design/data/`, each with a shape and a filled round-trip fixture (the shape tests fail by name without one). The dictionary's guidance says a cell nobody measured reads `not measured`, never `0`. `/sprd-data` step 3 lists six artifacts; `data-analyst` gains a "When driven for a data spec" subsection; `phases/activities.yaml` declares the new paths and a build-stage activity. |
| 6 | Branch-safe ids | Two branches cannot both name a decision `DL-07`, or a spec `0034`. | `scripts/branch_scan.py` is the one new module that imports `subprocess` (argument lists, never a shell, never `fetch`; `git for-each-ref`, `git show`, `git ls-tree`). A ref that cannot be read is named in `unread` rather than dropped, and outside a git repository the call proceeds on the local files with `refs_scanned: []`. `track_decisions.open_decision` gains an `other_logs` keyword, defaulting to empty. |
| 7 | Done means the data flows | The card is not done until the pipe returns real rows. | Six pre-seeded acceptance checks in the template (listed in `references/data-specs.md` §5), each concrete enough to pass the vague-line lint. They are graded in the PR like any acceptance checks. `data_spec.py check` is the early, advisory look: three findings, exit 0, `not measured` with `passed: null` when its source file is absent. `status` flags `acceptance_due` when the data spec is merged and the parent's `data_review` is not `accepted`; recording it is `sprint.py verdict --lane data`, by a person. |

Around the edges: three capability entries (`data-spec`, `data-spec-status`, `decision-open-all-branches`) in `scripts/capabilities.py` so Shepherd, the desktop app, can tell a current plugin from an older one; one row in `docs/commands.md`; one Key Features bullet and the Testing lines in `CLAUDE.md`; `CHANGELOG.md` under `## Unreleased`. The protected core (`new_spec.py`, `check_spec.py`, `sprint.py`, `sprint_model.py`, `spec_transition.py`, `spec.md` and its shape, `harness/**` among them) is byte-for-byte unchanged, and the only existing test edited is the build phase's exact activity list in `scripts/tests/test_activities_model.py`, which gains `data-spec` because that pin exists to notice exactly such an addition.

**Standalone or workflow.** Every verb takes `--repo <path>` or `--state <state.yaml>`; with no `.sdlc/` it still works, and only `--state` mode appends the one ledger line (`data_spec_linked`, spec ids only, never a name) to `.sdlc/metrics/spec-log.jsonl`. `--help` touches no filesystem. This is the plugin's Standalone-or-Workflow rule applied to a new command.

**One data spec, start to finish.**

1. A build spec `0001` exists and cites `BR-03` and `DOC-004` in its body.
2. `uv run scripts/data_spec.py new --repo <r> --serves 0001 --name "claims profile" --owner @sam-k` creates `specs/0002-claims-profile.md`, fills its Context from `0001`, and writes `depends_on` and `data_review` on `0001`.
3. `/sprd-data --spec 0002` has `data-analyst` read Context first, interview, and draft the six documents. Each readiness gap the human routes becomes a decision-log item opened with `track_decisions.py open ... --all-branches`.
4. `data_spec.py check --spec 0002` shows what is still missing; `check_spec.py` holds the spec to the Definition of Ready as for any spec.
5. The sprint layer's build order puts `0002` before `0001`. The data team builds; the PR is graded against the six checks.
6. After merge, `data_spec.py status` shows `acceptance_due`. A named human records `sprint.py verdict --lane data --verdict accepted --by "<name>"`; no tool does it for them.

## Deferred: live evidence mode (`--live`)

Design only. Nothing in this section is built, and the agent's tool list does not change.

**What it would be.** An opt-in mode of `/sprd-data` in which the `data-analyst` fills the measured parts of the data documents (the dictionary's null %, distinct count, min–max and median; the lineage's real objects; the handoff's smoke-test output) from the platform the project names, instead of a person pasting numbers in.

**Rules it would hold.**

| Rule | Meaning |
|---|---|
| Read-only | The agent may run queries and CLI reads against the named platform and nothing else: no DDL, no DML, no job or pipeline run, no write of any kind. |
| Every number is cited | A number in an artifact cites the query that produced it, or a `file:line` it was read from. A number with no citation reads `not measured`. This is what acceptance check 3 already asks of a person today. |
| Cost or visibility needs a named human | Anything that costs money (starting compute that is not running, a scan the platform bills by volume) or is visible outside the repository (creating or changing an object, running a job, posting a message) needs a named human's approval, per action, recorded with their name. An AI never approves. |
| Measured beats documented | When a result disagrees with a document (a field type in the contract, a row count in a README, a retention period in a decision record), the artifact shows both values, marks the row as a mismatch, and opens a decision-log item with an owner. Neither value is silently chosen, and the measurement does not overwrite the document. |
| Credentials are never the plugin's | The plugin never stores, reads, writes or logs a credential. Access is the person's own existing sign-in, as the code-host reads already reuse the machine's `gh` or `az` sign-in. |

**The security posture to decide before anything is built.** Today `data-analyst` has `Read, Write, Edit, Grep, Glob` and no shell, and the build kit pins that list as unchanged. A shell against a client data platform changes what the agent is. These are the questions for the owner, and none has an answer yet:

1. **A shell, or no shell.** There are three ways to hand the agent a read, in rising order of exposure. (a) An evidence file: a person, or Shepherd, runs a plugin script that executes only the table below and writes the results to a file; the agent reads the file and cites it, and its tool list does not change. This is today's manual path made repeatable. (b) A typed tool: the table's verbs exposed as tools with typed arguments (for example through an MCP server), so the agent chooses a verb and values and never composes a command. (c) A scoped shell: `Bash` limited by pattern to the one script. Pattern-matching a command line is weaker than validating a typed argument, so (c) is the last resort. The design's lean is (a) first.
2. **Aggregates, or rows.** Anything a query returns enters the model's context and the session transcript. The lean is aggregates only (counts, null %, distinct counts, min, max), no row samples. A min or max of a text or date column is itself a real value, so for any field the data contract marks `YES` for PII the profile reads `withheld (PII)` rather than a value.
3. **Tier.** The template's own guidance already says a data spec that touches PII or client data is HIGH. A spec that uses `--live` reads client data, so it would ride the full ladder: the grader, a correctness pass, a security pass and a named human sign-off. The credential path should also be treated as a gated path, which forces the security pass regardless of tier.
4. **Who approves a cost-bearing read, and where that is recorded.** A ledger line with a named `--by`, in the pattern the sprint layer's verbs use.
5. **Where results land.** What is written into an artifact travels with the repository. An artifact should hold the query and the aggregate, never the rows, and a client's data should not land in a repository the client does not own.
6. **Untrusted text.** Query output and platform metadata (column comments, table descriptions, job names) can be written by anyone with write access to the platform. This is the threat model `studio/electron/main/agentRun.ts` already works to, and the discipline of `ado_sync.py show --for-agent`: the agent quotes such text and never obeys it.

**What an allowlisted read-only command table would look like.** Modelled on `agentRun.ts`, where the whole of what Claude may do is one argument list: an allow-list of `Read`, `Grep` and `Glob`, an isolated working directory, a fixed agent table the renderer cannot name into, and no document text in the prompt. Two other pieces of this codebase already work this way for reads: `pipeline_proof.py` is read-only by construction and a test pins the exact set of `gh` calls it makes, and `ado_transport.py` is the one `az` spawner, argument lists only, never a shell. A live-evidence table is the same idea for a data platform: a small closed set of named verbs, each a fixed statement or call with typed slots, run by a plugin script, with the model choosing a verb and values and never a statement. The rows below are illustrative; the real table belongs to a platform pack and to the security review.

| Verb | Fixed form | Slots | Returns |
|---|---|---|---|
| `describe-object` | the platform's describe or show statement | the object name | column names and types |
| `row-count` | a count over the object | the object name | one integer |
| `column-profile` | count, count of non-null, count of distinct, min, max and the dialect's median over one column | the object name and the column name; min and max refused for a PII-classified column | five numbers, one row |
| `key-presence` | a count over a serving object where its key equals a bound value | the serving object, its key column, the key as a bound parameter | one integer |
| `last-run-status` | the platform's read call for a job or pipeline run | the job id from `data-handoff.md` | state and end time |

Object and column names are validated as plain identifiers against the objects the project names, never concatenated from free text; values travel as bound parameters; output is capped in size and rows; and the statement text goes into the citation, so a reader can re-run it.

**Until then.** A person runs the profile query and cites it in the row, which is exactly what acceptance check 3 asks. Every `data-dictionary.md` cell nobody measured reads `not measured`, never `0`, and the agent states what it could not check instead of filling the gap.

## Deferred: platform packs

Design only. A platform pack is a cheat-sheet and a set of conventions for one data platform, so each engagement does not rediscover them.

**Shape.** It follows `harness/packs/tools/gitnexus`, because a platform is an optional, multi-select tool a team wires in, with no stack or CI/CD pack required: `harness/packs/tools/<platform>/pack.yaml` and the files it names. A new axis would buy nothing and need resolver code; the tools axis already means "optional, any number, the id is the directory".

| Manifest key | In `gitnexus` | In a platform pack |
|---|---|---|
| `pack{id,axis,name,version}` | `gitnexus`, `tools`, a name, `0.1.0` | the platform's id (`databricks` first), `tools`, a name, `0.1.0` |
| `provides` | a config file and a setup guide | the pack's documents (below) |
| `overlays` | `{src, dest}` pairs for `.gitnexusignore` and a `SETUP.md` | `{src, dest}` pairs landing the documents under `.claude/tools/<platform>/`; documents, nothing that runs |
| `setup` | `summary`, `commands`, `note`: printed, never run | printed only: sign in with the platform's own CLI, and name the workspace, catalog and schema in `data-handoff.md` |
| `requires` | `{}` | `{}` |

It is installed by `install_harness._resolve_tools` from the top-level `tools:` list of a profile (for example `tools: [gitnexus, databricks]`). The id is the pack's directory name; an id with no pack, or a manifest with no `overlays` map, is a warning and a skip, and setup never fails for it. Tools packs compose after the stack, CI/CD and frontend packs and are additive. The installer stays a pure file composer: it prints the setup commands and runs no third-party binary.

**Databricks first.** What the pack would hold:

| Document | Holds | Serves |
|---|---|---|
| Connection rules | How a developer signs in (the platform CLI's own profile in their home directory; a token never in the repository, an overlay or `.mcp.json`); how a project names its workspace, catalog and schema (in `data-handoff.md`, never in the pack); which environment is the target. | acceptance check 1; the `--live` table |
| Read commands | The small closed list of read-only calls (list, describe, get a run's status) with their output shape. | the `--live` table; a person's manual reads today |
| Profile queries | One template per dictionary column: null %, distinct count, min–max, median, with the platform dialect's median or percentile function named. | `data-dictionary.md`, acceptance check 3 |
| Validation | How to show the pipeline ran end to end on the target and the serving object returns at least one row; the smoke-test pattern and where its output is linked. | `data-handoff.md`, acceptance checks 1, 2 and 5 |
| Known pitfalls | Symptom, cause, fix, one entry per trap, added only after an engagement has hit it. The kind of entry expected: naming of objects across catalog, schema and table; compute that has to be running before a read; scans billed by volume. Those are examples to verify against the platform's documentation and a real engagement before they ship, not claims made here. | the analyst and the reviewer |

**Boundary.** A pack never replaces the platform's own CI/CD, and the plugin never deploys to the platform. The platform's own deployment tooling ships the pipeline; the repository's CI/CD pack (`cicd/github` or `cicd/azure-devops`) still runs the repository's rails. A data pack documents how to read the platform and how to evidence a pipeline, never how to ship one. No credential, workspace address or per-client value goes in a pack: it is shared across engagements, for the same reason `gitnexus` refuses to carry one repository's index counts.

**Why deferred.** `harness/**` is byte-for-byte frozen for spec 0039, and a pack is an addition under it. More to the point, the pitfalls and the profile queries are knowledge an engagement earns, and writing them from memory before one has used them would produce confident text that has never met the platform.

## Non-goals

- **No gate.** No phase gate, ready rule or `advance_phase.py` check reads a data spec's state. `check` is advisory and exits 0, like `check_channel.py` and the readiness assessment.
- **No second backlog.** A data spec is a spec: one branch, one PR, one tier, one checker. There is no data tracker beside `specs/`.
- **No acceptance by a tool.** No script writes `data_review: accepted` or any spec `status`.
- **No platform access, credential or deploy** in anything that ships now.
- **No change to the spec machinery.** `new_spec.py`, `check_spec.py`, `sprint.py`, `sprint_model.py`, `spec_transition.py`, `spec.md` and `harness/**` stay as they are; the Definition of Ready is the one that exists.
- **No hidden network read.** `--all-branches` never fetches; a stale remote ref is a stated limit, not something the tool papers over.
- **No velocity, points, hours or lines of code** in any output, ledger line or document.
- **Not a data catalogue or lineage tool.** The six documents are written and signed by people; the plugin does not crawl a platform to build them.
- **No version bump** in this change.

## Alternatives considered

| Alternative | Why it is attractive | Why it loses |
|---|---|---|
| Put the data work inside the build spec (a Data section or a checklist). | One file, nothing new to learn. | One spec is one branch and one PR, and the data work is a different owner, a different reviewer and often a different repository. Folded in, the build cannot be ordered behind it, a non-author checker cannot be the data person, and the `data_review` verdict would be a team grading its own homework. The sprint layer can only order and check what is a spec. |
| A project-local skill that walks a team through it, as the teammate's drafts read. | Fast to write, no plugin change. | A skill is guidance, not enforcement: it cannot write the link in both directions, refuse a cycle, keep the parent's comments, or allocate an id across branches, and each project would re-implement it differently. It has no `--json` for Shepherd to draw and no test that a rule still holds. The data-spec rules are mechanical, so they belong in a script with refusals pinned by tests, and the judgement stays with the agent and a person. |
| Paste evidence into the interview and let `data-analyst` write it up. | No new documents, no new verbs. | Numbers with no query behind them cannot be checked or repeated, and an interview produces documents, not proof. Which rules bear on a table is also a lookup, not a judgement: a script reading the parent's references is the same every time, where a model recalling them is not. This is problem 5 again. |

## Open questions

1. **Should `check` ever gate?** Today it is advisory, and the six acceptance checks are enforced by the checking ladder's grader, which reads them in the PR. If a data spec can merge with a placeholder handoff, the gap is only as visible as the grader's comment. Making `handoff-present` block `acceptance_due` would be a deliberate step, taken after measuring how often the advisory line is ignored.
2. **Should `--all-branches` become the default?** It is a flag because reading every ref costs a `git show` each and a remote ref is only as fresh as the last fetch. Neither the cost on a repository with many branches nor how often an unflagged call reuses an id has been measured. Until it is, the flag stays and the help says to fetch first.
3. **Is an `accepted` verdict from before the data spec existed still true?** D4 keeps it, because undoing a person's verdict is worse, and says so in a note. But a parent accepted when it needed no data work and then handed a data dependency may deserve a fresh look. Whether `sprint.py ready` should warn is a decision about the sprint layer, which this change does not touch.
4. **One parent only.** `serves` holds one id, and a second `serves` naming a different parent is refused. A shared dataset that two build specs need would be two data specs or a list. Nothing here decides which, because no case has appeared yet.
5. **Where does the spec live when the data code does not?** The template's Deliverables table puts transformation and serving code in "the data repository this project names", while the spec, the `serves` link and the parent are found by id under this repository's `specs/`. The tool reads and writes only the repository it is pointed at, so a data spec in another repository cannot be linked by it. Whether the data team's spec and PR live in the application repository, or the link is made across two, is not decided here.
6. **The `--live` posture.** The six questions in the Deferred section are open and belong to the owner. None of them is answered by building something.
