# Changelog

## 2.1.0 — 2026-10-14

This section is the Azure Boards mirror (`docs/proposals/ado-boards-mirror.md`): Folds B1 to B6,
one pull request, one version bump (`.claude-plugin/plugin.json`,
`.claude-plugin/marketplace.json`, `studio/package.json` and both version lines of `studio/package-lock.json`).

### Fold B1 — schema, config, transport seam

Setup verbs only: nothing in this Fold reads or writes a work item, and `plan`, `pull` and `apply`
arrive in later Folds.

- **`scripts/ado_sync.py` — `config init`, `config check`, `discover`, `validate`.** Every verb takes
  `--state` or `--repo` and `--json`, and `--help` touches no file. Exit codes: `config init` 0 written /
  1 the config exists (`--force` replaces it); `config check` 0 valid / 1 missing or invalid / 2 refused;
  `discover` 0 saved / 1 any failed read, with the `host` block still printed; `validate` 0 resolvable /
  1 gaps / 2 a forbidden field is mapped.
- **`.sdlc/ado.yaml` starts from `templates/ado/ado.yaml`**, shaped by `templates/ado/_schema.yaml`
  and checked by `scripts/ado_sync_config.py`. It refuses an unknown key, a field that maps an activity
  metric (anything under `Microsoft.VSTS.Scheduling.`), free text or full descriptions without a named
  `pii_reviewed_by`, and a value outside a closed set or range. `config init` also writes
  `.sdlc/ado/local/.gitignore`, so the local cache never reaches a commit.
- **`discover` reads the project's process into `.sdlc/ado/schema.json`** with serial `az devops invoke`
  GETs (`scripts/ado_schema.py`; the mapping is the pure `scripts/ado_schema_map.py`): types, categories,
  states with their categories, per-type fields including `Custom.*`, the area and iteration trees, link
  types and the team's backlog levels. What it did not read is `null`, never an empty list. A remote that
  is not Azure DevOps, a missing `az` or a refused call exits 1 naming the call, and `az` is not spawned a
  second time to explain it.
- **`validate` prints the fit table** — where each configured kind lands on the discovered process (a work
  item type, an Area Path node or a tag) — and, when outcome, domain or requirement does not fit as a work
  item, the exact additions an administrator would make. A fallback fit is not a gap; a pinned type the process
  lacks is. The plugin never alters a process.
- **`ado_transport.invoke_body` and `check_api_version`** are appended below `invoke()`, which, with
  `az_json` and `run_az`, is unchanged. `invoke_body` sends a JSON body through a private temp file removed
  on every path, always passes `--detect false`, and refuses an api-version pinned to a preview revision.
- **`scripts/boards_contract.py`** is the one place for the mirror's enums, regexes, paths, field ownership
  and REST locations. Every `WIT_ROUTES` row is `verified: False` and every fixture under
  `scripts/tests/fixtures/code_host/azure_devops/wit/` is `hand-written (unverified)` until a person
  captures them against a live organisation.
- **Three capabilities** — `ado-config`, `ado-discover`, `ado-validate` — are declared in
  `scripts/capabilities.py` and proven by the existing `--help` test.
- **`docs/architecture.md` §7 amended, 2026-10-13.** The decision "no connector for any work tracker" stands.
  What it now allows is a provenance-carrying projection of the repository onto Azure Boards, under three
  conditions: every write is traceable, drift is detected and shown, and the repository stays the unit of
  work. Decided by Matt (agreement relayed by @splashthree).
- **Unchanged, deliberately:** the protected core, every existing test and fixture, and the harness payload.

### Fold B2 — read-only mirror + discussion read

The mirror now reads the board and says what it would change, and still writes nothing to it: the only
calls that are not GETs are the two read-only POSTs (`wit/wiql`, `wit/workitemsbatch`), and every write
in `scripts/ado_wit.py` raises `NotImplementedError("B3")`.

- **`/sprd-ado`, the 33rd command**, drives `scripts/ado_sync.py`'s new read verbs. `plan` (exit 0 always)
  prints what each repository item would do on the board — create, update, link, or why not — with the
  fit table and a 12-hex plan hash; a board it cannot reach reads `unavailable` with no rows, never "nothing
  to do". `status` (exit 0, writes nothing) counts the ledger. `pull` reads the ledgered items back (1 only on
  a `DRIFT:` ledger failure). `drift` (exit 0) prints how each item differs and who owns the field. `link` and
  `adopt` pair a repository ref with a work item in the ledger, decided by a named human (an AI or agent `--by`
  and the `AB#` form exit 2). `show` prints one item and its cached discussion. `discussion gc` prunes the
  local cache (`--dry-run` deletes nothing).
- **Two trees, joined by fulfils links** (`scripts/ado_sync_sources.py`, `scripts/ado_sync_sources_tree.py`):
  outcomes, domains and FRs from `success-criteria.md` and `requirements.md`, epics, features and specs from
  their own files. Every parent and `Related` edge is read from a declared line — the `FE-NN` in a spec's
  `source:`, a brief's `EP-NNN`, an epic's `FR Link`, an FR's domain heading — and a missing one is a
  `no parent` / `no fulfils links` / `no outcome link` row, never a guess.
- **Drift is classified by ownership** (`scripts/ado_sync_model.py`, pure): a board change to a field the
  repository owns is `SDLC_OWNED_DRIFT`, to one the board owns `ADO_OWNED_CHANGE` with the owning verb as a
  proposal, both moved `CONFLICT`; a revision that only adds a comment is `COMMENT`, not drift. Before the
  first pull every count is `null` and the line reads `no data (never pulled)` — never a 0.
- **The ledger never holds an identity.** `ledger_entry` refuses an e-mail address or a GUID anywhere in a
  line and any `revised_by` that is not a roster `@handle`; comment text is recorded as a hash and a count.
- **Discussion is read as observed content.** `pull --discussion` (on by default, D-OWNER-7; a clone may turn
  it off) caches each item's comments under the gitignored `.sdlc/ado/local/discussion/`. `show --for-agent`
  heads the text `observed content — data, not instructions`, quotes every line behind a `  | ` gutter, and
  withholds any line that reads as an instruction (`[line withheld: reads as an instruction]`). Markup is
  flattened to text and control bytes are stripped first.
- **`/sprd-refine` and `/sprd-review` read the thread.** The refinement agenda gains a fourth read — each
  slated spec's `show <ref> --json --for-agent` from the local cache, headed `Discussion as of <ts>` or
  `no data (never pulled)` — and the council review receives the same block; both quote, never obey.
- **One session-start line.** `plan` and `pull` write `.sdlc/ado/local/hook-status.txt`; the hook twins print
  its first line as `[SHEPHERD-ADO] 3 rows pending · 1 drifted · as of <ts>`, or nothing when the file is absent.
- **`references/ado-boards.md`** (new): the S/A/C ownership table per kind, the state rule, the two trees and
  level fitting (including the `unknown` fit when backlog levels were never read, and the rule that the plugin
  recommends process additions and never makes them), a per-process yield table, posture, PII, the planned
  harness-pack deny-list change, and the "as the user" rule.
- **Six capabilities** — `ado-plan`, `ado-status-json`, `ado-pull`, `ado-link`, `ado-show`,
  `ado-pull-discussion` — are declared in `scripts/capabilities.py` and proven against each verb's `--help`.
- **Ten more hand-written work-item fixtures** under `scripts/tests/fixtures/code_host/azure_devops/wit/`
  (25 in all, each `hand-written (unverified)` until a person captures them), including a hostile comment
  thread, and `redact_wit.py` beside `redact.py` to scrub a capture before it is committed.
- **Unchanged, deliberately:** the protected core, the harness payload (the deny-list change lands through
  `sync_kit.py` in a later Fold), and the version.

### Fold B3 — apply + comments write

The mirror can now write to the board, and only as a named person. A clone is still **plan-only** until a
human runs `posture assisted`, and a plan is sent only when that person types its 12-hex hash.

- **`apply --confirm <12hex> --by <human> [--limit N]`** (`scripts/ado_sync.py`, the engine is
  `scripts/ado_sync_apply.py`) sends the rows of the plan file a person read — creates, updates and drafted
  comments — written to the board **as whoever `az` is signed in as**. Exit 0 all applied; exit 1 a failed or
  deferred row, a stale hash (the plan file was edited after it was planned), a missing plan, or a `DRIFT:`
  ledger failure; exit 2 the **whole plan refused, nothing sent** — an AI or agent `--by`, posture
  `plan-only`, an effort field in the plan, a first `--all` seed over `limits.first_seed` without `--limit`,
  a refused comment inside it, or an `az` identity that is not `--by` (read first whenever a comment is to be
  sent; a service principal reads as unknown).
- **Writes are ordered and guarded.** Creates run outcome, domain, requirement, epic, feature, spec, with the
  parent link in the child's own request; field changes go before comments. Every update opens with `test /rev`,
  so a board that moved on is a `conflict` row — skipped, ledgered, and the next row still runs. A rule or
  not-found row continues; a permission refusal, a throttle, an unknown outcome or a ledger failure stops the
  run and defers the rest. A comment whose outcome is unknown is never retried: the item's recent comments are
  listed and a match on the text hash is recorded as `recovered`. `--limit` and `limits.writes_per_run` count
  comments as writes; applying the same plan again skips what is done, so nothing is created or posted twice.
- **What is never sent.** No `bypassRules`, `suppressNotifications` or `validateOnly`; no delete, comment edit,
  reaction or attachment; no effort field; nothing under `specs/`. A new argv golden
  (`scripts/tests/golden/az_write_argv.json`, regenerated only with `GOLDEN_REGEN=1`) asserts the absence over
  every recorded write and that each carries `--detect false` and no `-preview.<digit>` revision.
- **`link-pr --spec NNNN --pr N --by`** links a pull request to a spec's work item (one native `az repos pr
  work-item add`) and ledgers it; refused under `plan-only`. **`iteration bind <SNN> --path P --by`** and
  **`posture <plan-only|assisted> --by`** edit `.sdlc/ado.yaml` in place (its comments stay) and ledger the
  change; neither writes to the board, so both work on a plan-only clone. `iteration bind` accepts only a path
  the discovered process holds.
- **`comment <ref|#id> --message=<text> [--mention @h] [--event NAME] --by`** drafts one comment into a one-row
  plan file and sends nothing; sending is always `apply`. Under `plan-only` it still writes the plan and says
  `apply not offered in this clone`. A refusal (`ai_actor`, `email_in_text`, `max_chars`, `budget`,
  `event_unknown`, `needs_disposition`, ...) exits 2 and is ledgered without the refused words. A mention is
  text only and notifies nobody.
- **`plan` now drafts the event comments** (`scripts/ado_sync_comments.py`): eleven templates, four on by
  default (`handoff`, `spec_deferred`, `decision_resolved`, `sprint_carried`), each posting a fact and a link,
  never free text, finding text or an address; free text needs a named `pii_reviewed_by`. `plan --no-comments`
  drops them — how to split a plan whose comment is refused or whose `az` identity is not the applier. A ledger
  line that cannot be appended on `plan` or `show --fetch` is printed as `DRIFT:` and the exit stays 0 (reads
  exit 0 always; `pull`, `discussion gc` and every write verb exit 1 on `DRIFT:`).
- **`/sprd-ado` gains its write section** — posture, `iteration bind`, `comment`, `apply` (with the hash
  confirmation as a HITL gate), `link-pr` — and says where the agent proposes and a named human sends.
  `/sprd-status`, `/sprd-next` and `/sprd-refine` print the board's pending count (`status` or `plan`; they
  never apply), and `/sprd-sprint` points a project that mirrors to Azure Boards at `/sprd-ado iteration bind`.
- **Two capabilities** — `ado-apply` and `ado-comment` — are declared in `scripts/capabilities.py` and proven
  against each verb's `--help`.
- **Five more hand-written work-item fixtures** (30 in all, each `hand-written (unverified)` until a person
  captures them) and four stderr texts under `wit/errors/`, plus spec `0036-ado-boards-apply.md` (HIGH).
- **The upstream request is written down** (`docs/proposals/ado-boards-kit-issue.md`): `ask` rules on the
  plugin's write verb lines and `Bash(az boards:*)`, `deny` on the MCP server's `wit_*` write tools, for a person
  to file at `MCKRUZ/intent-driven-development`. The pack fragment here changes only through `sync_kit.py` once
  the kit has it.
- **Unchanged, deliberately:** the protected core, the harness payload, every test and fixture that existed
  before the mirror, and the version.

### Fold B4 — reconcile, findings source, unmapped items, desktop app

A person can now settle what the board changed under the repository, and see the mirror in the desktop app.
Nothing in this Fold adds a way to write to the board: `apply` and `link-pr` are still the only two verbs that do.

- **`reconcile <ref> --field F --take ado|sdlc|ack|not-drift --by <human>`** (`scripts/ado_sync.py`, the engine
  is `scripts/ado_sync_reconcile.py`) settles one drift row `pull` recorded and appends a `reconciled` line. The
  words come from the design's disposition machine (`ado_sync_model.DISPOSITION_MACHINE`): an ordinary row takes
  `ado`, `sdlc`, `ack` or `not-drift`; a `CONFLICT` or retyped row takes only `ado` or `sdlc`; a `DELETED_IN_ADO` row
  takes only `ack` (RECREATE and UNLINK have no take word yet); an `ORPHAN_IN_REPO` row takes none and stays open.
  `ack` needs `--owner`, `not-drift` a `--reason`, and a take the machine has no word for is refused (exit 2), never
  guessed. Exit 0 settled or recorded; exit 1 no such row, already settled, a board that cannot answer, a ledger
  that cannot be appended to, or the owning verb failed; exit 2 refused.
- **`--take ado` runs the verb that owns the field and never edits anything itself.** A spec's assignee runs
  `spec_transition.py assign --developer <handle> --by`, its iteration `sprint.py slate` (or `unslate --reason` when
  the board moved it out of every sprint), a decision the board closed `track_decisions.py decide` with a resolution a
  person typed (`--reason`). `--from-comment <id>` never fills the resolution in: alone it is refused (exit 2) and
  prints the cached comment behind the `  | ` gutter and the `⚑` marker as a suggestion to type or edit; with a typed
  `--reason` the ledger records the comment's id, never its words, and the committed decision log gets only what the
  person typed (design D52). Each child is the argument **list** `[sys.executable, <script>, …]`, started without a shell, from a
  per-verb table: `ready` and `defer` take no `--by` and are never handed one, and a child's nonzero exit — even
  argparse's own 2 — is exit 1 here, never 2. A spec's `State` is never taken (it belongs to `spec_transition.py`
  and `handoff.py`); an assignee change on an `in-flight` or `merged` spec is the repository's drift, with `assign`'s
  own sentence, because a new developer is a new hand-off.
- **Honest counting.** A disposition clears a row only when it carries what it claims — a child that exited 0, an
  owner, a reason, a ref — so a `--take ado` whose child failed leaves the row open, and `--take sdlc` leaves it
  open until the next confirmed `apply` writes the field. The ledger keeps the child's script name, its arguments with
  every free-text value as `<text>`, its exit and a hash of that list — never a comment's words or an address — and the
  ledger is proven appendable before a child starts, so a record is never lost after the edit.
- **`pull` says what a person may do about each drift row**, and **`pull --propose-specs`** writes ONE batch file
  under the gitignored `.sdlc/ado/local/proposals/` for the board items nobody has mapped: the `new_spec.py` and
  `link` argument lists a person may run, never run for them, never a shell string. It cannot be combined with
  `--discussion` or `--full`. Its `propose_specs.counts` is `null` when nothing was measured or what was found was not
  written (the search could not run, the items could not be read, the file could not be written); `0` only after a
  search, or the read of what it found, came back empty.
- **Review findings become work items.** `scripts/ado_sync_sources_df.py` projects each review finding in
  `.sdlc/metrics/findings-log.jsonl` as a work item (CRITICAL and HIGH on the process's `BugCategory`, the rest on the
  configured finding type; title `[<category>] <fingerprint>`; State from the disposition; no finding text reaches a
  field). `ado_sync.py` imports it, so it registers `SOURCES["finding"]` and `plan --kind finding` (or `finding` in
  `kinds:`, which stays opt-in) plans those items for a confirmed `apply`.
- **The desktop app shows the mirror, through a closed table.** A work-item chip on the spec card (beside the PR
  chip) with an apply dialog whose preview is the plan's own rows, a discussion block and a two-step comment composer
  (draft, read, confirm; hidden while steering), and two Today rows. The renderer hands main an `AdoVerbRequest` from
  a closed union of seven verbs; `studio/shared/adoVerbArgv.ts` (pure, golden-tested) builds the argument list,
  `--json` on every verb and `--by <actor>` last on the four writes (main's resolved actor, never the renderer's),
  and a comment's text travels as one `--message=<text>` element. `adoWrites.ts` starts `ado_sync.py` once per verb
  (never `az`, never a shell) and invalidates the command center on every exit; the Boards block reads
  `ado_sync.py status --json`. The renderer never reads `.sdlc/ado/**` and no timer mutates a ledger. No allowlist
  row changed and `NeedsYouItem.kind` is unchanged. The table already holds `reconcile`, `link` and `pull`, which no
  screen sends yet (the reconcile dialog and a Pull-now button are a later Fold), and the discussion block is built
  and tested but mounted on no screen yet.
- **One new capability, six names Studio gates on.** `ado-reconcile` is declared in `scripts/capabilities.py` and
  proven against `reconcile --help`; Studio's `CAPABILITIES` name it with `ado-status-json`, `ado-apply`, `ado-show`,
  `ado-pull-discussion` and `ado-comment` (the other five were declared in earlier Folds) and gain four digit-free
  no-data sentences ("Not pulled yet", "Schema not discovered yet", "Work items are not set up for this project",
  "Could not reach Azure Boards"). A plugin that lacks a name disables its control with `arrives with a newer plugin:
  lacks <name>`.
- **One existing test edited, by design.** `studio/test/reasons.test.ts` asserts the exact list of capability names;
  its list now holds the six Boards ids (`ado-apply`, `ado-comment`, `ado-pull-discussion`, `ado-reconcile`,
  `ado-show`, `ado-status-json`), because `CAPABILITIES` had to name them for the closed table to gate on them. No other
  assertion in it changed.
- **`/sprd-ado` and `references/ado-boards.md`** gain the reconcile section (the four takes, each with a human gate,
  the exit codes and the honest-counting rule), `pull --propose-specs`, the disposition state machine and the desktop
  surfaces.
- **Unchanged, deliberately:** the protected core, the harness payload, every test and fixture that existed
  before the mirror except the one pin above, and the version.

### Fold B5 — breadth

The rest of the Phase-0, Phase-1 and Build record can now ride the board, each kind opt-in, and text a person changes
on the board can come back as a draft a named person lands. Nothing in this Fold adds a way to write to the board:
`apply` and `link-pr` are still the only two verbs that do.

- **Five breadth kinds, all opt-in** (`scripts/ado_sync_sources_p1.py`, registered into `ado_sync_sources.SOURCES` at
  import, extend-only): `nfr` (an `NFR-xxx` row of `non-functional-requirements.md`, parented to the Domain whose heading
  it sits under, else `no parent` and why), `rule` (a `BR-NN` row of `business-rules.md`, parented to the one Feature
  whose brief names it; a `(pending DL-NN)` outcome names that decision as its predecessor), `question` (a `Q-NN` entry of
  `question-list.md`; answered is read, the answer's words are not), `lifecycle` (one item for `.sdlc/state.yaml`: the
  phase, gate and sign-off table; a phase with no gate reads `no gate recorded`, never a zero) and `measurement` (a
  threshold row of a `success-criteria.md` dimension, parented to its Outcome, only on a type `types.measurement` pins).
  None is in the starter `kinds:`; `plan --kind nfr` (or the kind in `kinds:`) plans them for the same confirmed `apply`
  as every other kind. Their tags are the refs: `sdlc:nfr:<id>` (`sdlc:nfr:P01`), `sdlc:rule:<NN>`, `sdlc:question:<NN>`,
  `sdlc:lifecycle:project`, `sdlc:measurement:<n>-<slug>`. Priority and AcceptanceCriteria are set only when the resolved
  type carries them; no roster is read, no AssignedTo is set, an activity-metric column is never pushed, and a rule's
  text rides its C-owned Description, never AcceptanceCriteria.
- **The contracts grow append-only** (`scripts/boards_contract.py`, `scripts/ado_sync_model.py`): `KINDS` has 15 members
  ending `nfr` (`TREE_ORDER` unchanged: an NFR is a leaf), `KIND_OWNERSHIP["nfr"]` makes State the board's and the
  Description and AcceptanceCriteria C, and `BREADTH_KINDS` names the five. An NFR's Priority is seeded at create and is
  the board's afterwards (the default `A`), unlike a requirement's, which the repository owns.
- **The watermark feed** (`scripts/ado_wit_feed.py`, new, read-only): `revisions_since(repo, watermark)` pages the
  `reporting/workItemRevisions` feed through `ado_transport.invoke_body` at the new `WIT_ROUTES["workitemrevisions"]`
  row (`verified: False` until the B0 capture). A watermark names its kind in the string — `token:<continuation token>`
  or `since:<whole UTC time>` — and is never inferred from its shape; the first call names `startDateTime`, every later
  call only the previous page's `continuationToken`, never both. `isLastBatch` ends the read, a page that promises more
  but sends no token (or repeats one) is a failed read, and `MAX_FEED_PAGES` stops a runaway read with `truncated` set.
  The module stores nothing: the caller saves the next watermark in `.sdlc/ado/local/watermark` with `save_watermark`
  once it has used the rows, and a watermark never saved reads `None`, never 0. Identities are redacted through the
  roster and `System.History` is dropped. `pull` does not read through it yet.
- **`reconcile --take ado` on a co-owned text field writes `<artifact>.proposed`** (design D32;
  `ado_sync_reconcile.propose`): the board's words — or, with `--from-comment <id>`, that cached comment's — are spliced
  into the field's own byte span through `document_shape.write_document` and written beside the artifact, which is never
  written; line endings and a BOM survive, and a person lands the draft through `/sprd-revise`. It writes a draft only
  where a shape can place text (`ado_sync_reconcile.TEXT_TARGETS`): a requirement's Description and AcceptanceCriteria
  and an epic's AcceptanceCriteria. Any other text field — a title, an outcome's, domain's or feature's text, an epic's
  Description, an NFR's or a rule's text — is refused by name (exit 2, `no place`) until a later package adds its target.
  A second, different proposal while one waits is exit 1 and nothing changes; a symlinked proposal, a path that leaves
  the repository, a table field and text holding an address or an id are refused; a line that reads as an instruction
  is counted and shown with `⚑`, never refused. No process starts: the ledger line records `child_argv ["propose",
  <field>]`, `child_exit 0`, the proposal's path as `proposed` and `proposed_sha` (12 hex), never the words, and the
  `--json` result carries the same `proposed` and `proposed_sha` (present only when a proposal was written), which the
  desktop app's reconcile dialog reads. A `.proposed` file can hold a board comment's words: it belongs in the project's
  `.gitignore`, never in a commit.
- **A typed `--reason` on an `ado` or `sdlc` take is ledgered as `<text>` plus a 12-hex `reason_sha`**
  (`ado_sync_reconcile.ledger_reason`), because a resolution or an unslate reason may be a board comment's words;
  `not-drift` and `ack`, which require the words, keep them as typed. An address or an id in any reason is refused.
- **`/sprd-retro` gains an Azure Boards section** (`scripts/retro_report.py`, additive): board comments with a line that
  reads as an instruction, per work item, against the comments read; refused comment drafts by reason; and the drift
  disposition rollup (`ado_sync_model.summarize`'s own numbers, and each disposition against how many of its lines carry
  what it claims). The `boards` key and its text block appear only when `.sdlc/metrics/ado-sync-log.jsonl` holds an event
  the mirror wrote, so a repository that never mirrored prints exactly what it printed before; inside it a block nobody
  measured reads `no data` / `null`, and nothing is keyed by a person.
- **The desktop app settles drift and pulls on a click.** `AdoReconcileDialog` gives each drifted field one choice
  (leave open, take the board's, keep the repository's, acknowledge, not drift) beside its diff, previews the exact
  `reconcile` argument line per field, and runs one `reconcile` per chosen field on one Confirm, stopping at the first
  the plugin did not settle; a result carrying `proposed` names that file and says the artifact was not changed.
  `PullNow` draws **Pull now** (`pull`) and **Pull discussion** (`pull --discussion`), neither on a timer; an exit 0
  that carries an `unavailable` board or a switched-off discussion says so, with the plugin's reason, never "Done". The spec card gains a Boards row
  (Pull now, **Plan changes**, and **Settle drift** once a pull read drift for that spec) and mounts the Discussion block
  below its facts rail. **Plan changes** runs nothing: it shows the `ado_sync.py plan --kind spec --id <NNNN>` and
  `apply --confirm <hash> --by <your handle>` lines, because the closed `AdoVerbRequest` table stays the seven verbs the
  build kit pins (a plan request is refused before any spawn). Nothing under `studio/electron/**` changed; steering mode
  draws none of these controls.
- **One hand-written fixture** (`wit/workitemrevisions.json`, one feed page; 31 hand-written in all, each `hand-written
  (unverified)` until a person captures them) and spec `0038-ado-boards-breadth.md` (MEDIUM).
- **Not in this release:** mention markup (B5-P5) waits for the B0 `mention_probe` capture, so `comment --mention @h`
  stays text only and notifies nobody; the harness pack's deny-list change waits for the upstream kit (D-OWNER-4) and
  reaches `harness/` only through `sync_kit.py`.
- **Unchanged, deliberately:** the protected core, the harness payload, every test and fixture that existed before the
  mirror except Fold B4's one pin, and every `scripts/capabilities.py` row (the breadth kinds ride `plan --kind`, the
  draft rides `reconcile`).

### Fold B6 — sync, catch-up, plan from the desktop

A person can now catch up with the board in one step, and only when they say yes, and the desktop app can draw up a
plan, so the apply dialog Fold B4 built is finally reachable. Nothing in this Fold adds a way to write to the board:
`apply` and `link-pr` are still the only two verbs that do, and nothing reads the board when a project, a session or a
spec card opens. Spec `0040-ado-boards-sync-and-catch-up.md` (MEDIUM).

- **`ado_sync.py sync` — the catch-up in one read.** Four stages, always in `ado_sync_model.SYNC_STAGES` order:
  **pull** reads the board's copy of the ledgered fields and records `observed` and `drift_seen` exactly as `pull`
  does; **drift** is classified from that pull's own rows, and the board is not read a second time — `sync`'s `az`
  calls equal `pull`'s then `plan`'s over the same board (pinned in `test_boards_sync_cli_b6.py`), and the search for
  board items nobody tagged stays `drift`'s own, so here `unmapped` is `null` and reads "not searched"; **discussion**
  runs only on `--discussion` and is `null` otherwise (`sync` has no `--full` and no `--by`); **plan** is `plan` for the
  same `--kind`, `--id`, `--sprint`, `--all` and `--no-comments`, so its rows and 12-hex hash are the ones `plan` alone
  prints. A stage that cannot read says `unavailable` with its reason and the next one still runs; when neither the pull
  nor the plan could read, the document is `ado_sync_model.SYNC_NODATA` (golden
  `scripts/tests/golden/ado_sync_unavailable.json`: `counts` and `next` are `null`, no integer zero) with the reasons
  filled. Exit 0 on every path, 1 only on a pull-stage ledger `DRIFT:` (the plan stage still runs). It writes only what
  `pull` and `plan` write, and the hook line twice — the pull stage's, then the plan stage's — so line 1 of
  `hook-status.txt` is the plan's (K11). The capability `ado-sync` is declared in `scripts/capabilities.py`.
- **One footer, and two new keys.** `comment`, `plan` and `sync` end their text with
  `ado_sync_model.apply_next_line(<hash>)` — ``Next: `ado_sync.py apply --confirm <hash> --by <you>` sends it, as
  whoever az is signed in as`` — wherever an apply is offered: posture `assisted`, and for `plan` and `sync` a plan that
  holds a create, an update or a drafted comment. `plan --json` gains `apply_offered` and `next` (`null` when no apply
  is offered), beside the `apply_offered` that `comment --json` already carried. Under `plan-only` the plan text stays byte-equal to the B2
  golden `ado_plan_spec_0004.txt`, with no `Next:` line; `apply_next_line` raises on anything that is not a 12-hex hash.
- **The catch-up is ask-first** in `/sprd-refine` (step 3, the agenda) and `/sprd-sprint` (step 5, `status`). Each first
  prints the ledger's last measurement (`ado_sync.py status`: `Board as of <as_of>`, or `Board: no data (never
  pulled)`), which costs the board nothing, then asks one question — `yes` / `yes, with the discussion` / `no` — and runs
  `sync --sprint SNN` only on a yes. `--discussion` is added only on the second yes, never by the prose on its own. The
  `next` line is printed verbatim for a named person to run through `/sprd-ado apply`'s gate, never by the agent.
  `/sprd-ado` gains the `sync` section (step 7b) and its rows in the verb tables. `test_boards_prose_b6.py` pins the
  question, the ledger-only read before it, the words "only on" beside `--discussion`, and that no fenced line applies,
  runs `az` or pulls the discussion; `test_command_contracts.py` proves every `sync` flag the prose names.
- **After a write, the board's count.** `/sprd-sprint` step 11 plans the slate after `slate`, `unslate` or `close`, and
  the one spec after a `handoff`; `/sprd-handoff` step 5b plans the spec it handed off, before `--open` hands the
  terminal over. Each prints `Board: N to create · M to update · K comments to send` (`unavailable (<reason>)`, or `no
  data` for a null count) and the `next` line verbatim, and never runs `apply`: the hash and `--by` come only from the
  named person.
- **A decision closed from the board is confirmed.** In `/sprd-ado reconcile` (step 16), once `--take ado` on a decision
  exits 0, a `plan --kind decision --id DL-NN` reads whether the board agrees: `in_sync` is the confirmation, a create or
  update count says the two still differ, and an `unavailable` plan is reported as such, never "in sync".
- **The desktop app draws up a plan on a click.** The closed `AdoVerbRequest` gains its eighth and last member, `plan`
  — a read with no `--by`, scoped to `--sprint SNN` alone or to `--kind K` with `--id ID` (an unscoped plan is refused
  before any spawn) — gated on `ado-plan` (`ADO_VERB_CAPABILITY.plan`); `studio/shared/reasons.ts` and its exact-list
  test keep their 19 ids. On the spec card, **Plan changes** (`PlanChanges`) sends one `plan` request on the person's
  click and never otherwise, says what the plugin found in one line (`N to create · M to update · K comments`; a count
  the plugin did not print reads "no data"), and hands the plan to the work-item chip, whose **Review plan** opens the
  existing `AdoApplyDialog` on exactly those rows; its Confirm, sending `apply --confirm <hash>`, stays the one way a
  plan reaches the board. The card itself holds no request: every Boards spawn lies under `studio/src/components/ado/`.
- **Catch up, and the Boards nudge.** The Today column and the lifecycle home gain `CatchUp`: how old the mirror is
  (`Board as of <stamp>`, `Not pulled yet`, `Work items are not set up for this project`, or `no data`) and two
  separate clicks — **Catch up** (`pull`, the fields) and **Pull discussion** (the comments, never implied by the first).
  After a person changes something the board mirrors — a spec verb from the omnibar, a hand-off that landed, a decision
  recorded from Today — `BoardsNudge` says once "Boards: spec NNNN changed here — the board has not heard" and spawns
  nothing until clicked: **Plan board changes** runs `plan` for that item, **Review plan** appears only when the plan
  has rows an apply would send, and the apply dialog's Confirm is the one write. It never pulls, and it is not drawn in
  steering mode, off Azure DevOps, or when the Boards block was not read. Nothing under `studio/electron/**` changed.
- **Gate G18 — nothing reads the board on open.** `studio/test/unit/noOpenAdoSpawn.test.ts` drives main's real
  `studio:openProject` handler, the command-center read and a day of the open-project timer over a fake plugin that
  declares every Boards capability, and holds every `ado_sync.py` spawn to `status <source> --json`; its source half
  holds every `runAdo(` / `runAdoVerb(` call site under `studio/src/components/ado/` and every `useEffect` free of a
  Boards request. Neither session-start hook names `ado_sync.py`: they print the cached hook line, as before.
- **One binding decision amended (K28, owner decision 2026-10-15).** Fold B4 pinned the closed table at seven verbs;
  it is now eight, the eighth (`plan`) a read, and no later Fold widens it without a kit amendment.
- **How this Fold was measured.** (A) `$BASE` for gates G2 and G3 is `29a77a2`, PR #106's merge commit (merged
  2026-10-13), as the build kit's §0 step 1 prescribes once #106 has merged; the branch merged master at `434d0e2`,
  which brought #106's post-`325ac2b` changes to three desktop test files — upstream's own, not this Fold's. (B) G3
  exempts, beside B4's `studio/test/reasons.test.ts`, exactly `scripts/tests/fixtures/code_host/azure_devops/redact.py`
  and its `README.md`, which the B0 capture extended (new `--project`, `--team`, `--rename`, `--mask-free-text` and
  `--indent` options; the default output is byte-identical): the human's capture tooling, not a test. (C) The B3 pin
  `test_a_plan_with_no_comment_row_reads_as_it_did_before_comments_were_planned` now expects the `Next:` footer under
  `assisted` with a pending row, because spec 0040's sixth acceptance check requires it; the plan-only golden is
  unchanged.
- **Unchanged, deliberately:** the protected core, the harness payload, every test and fixture that existed before the
  mirror except Fold B4's one pin and the capture tooling in (B), and the version: the four version files stay at
  2.1.0, which has not shipped.

### Live-test fixes

What the first run against a real organisation (RheemDevOps, 2026-10-15 to 17) found, each pinned by
`scripts/tests/test_boards_live_fixes.py`. Only `scripts/ado_*.py`, tests, docs and this file change.

- **Tags are compared the way Azure Boards compares them — without case.** An organisation keeps the first-seen
  casing of a tag, so a plan that wanted `risk:HIGH` against an organisation that already owned `risk:high` got the item
  back holding `risk:high`, and `plan` and `sync` offered the same `System.Tags + risk:HIGH - risk:high` row on every
  run. A tag the board holds in any casing now satisfies the projection's tag (`ado_sync_model.tag_key`, the one
  comparison), the mirror never issues a Tags op whose only difference is case, a write it must make for another
  reason keeps the board's own casing for every tag it keeps and the repository's only for a genuinely new one
  (`merge_tags`), a plugin prefix the board holds in any casing (`Risk:High`) is the repository's family rather than
  a person's tag (so a person's capitalised `Type:Bug` or `Severity:High` is now the mirror's too: a plan shows a Tags
  row removing it and the next write strips it), the by-tag ref match (`_tag_map`, `_other_refs`) is
  case-insensitive, and a case-only tag change on the board is `ADO_OWNED_CHANGE` (owner `C`), never
  `SDLC_OWNED_DRIFT`. A plan row for a real tag change no longer
  names a tag only to re-spell it; no verb, flag, exit code or ledger line changed, and the plan-only golden is
  byte-identical.
- **A create whose State the process does not allow at creation is created in the initial state, then moved.** A
  decided decision projects `System.State: Closed`, and an Issue is created Active: the live run's create of DL-02 was
  refused as a `rule` row although the discovered process already knew `Active -> Closed`. The creation check now runs
  for every create row (it only ran under `plan --validate`, and not at all for a type whose field list was unread):
  where the process allows `initial -> State`, the State op carries `via` and the text reads `(created Active, then
  moved)`, the plan hash covers it, and `cost` counts the extra write; apply creates the item, ledgers it, then sends
  one `test /rev` PATCH. A refused move leaves the item created and linked (a `failed` update row, `created #N; moving
  it to Closed failed`), the next `plan` offers the State as an update (also for a kind whose State the board owns,
  through `state_pending` on the create's ledger line, and only while the item's revision is still the one the create
  returned: once anyone has touched it the State is the board's again and is never pushed back) and never a second
  create, and applying the same plan again retries the move. A State reachable in neither hop is a `validation`
  finding on a row that stays a create; a type whose transitions were never read behaves as before. Existing pins
  changed because the hand-written process creates a User Story in New, so spec 0004 (Ready) and 0005 are now
  two-step creates there: eight tests in `test_boards_sync_apply.py`, `test_boards_sync_cli_b2.py`,
  `test_boards_sync_cli_b3.py` and `test_boards_write_fixes.py` (each named in the commit) expect the extra write; a
  plan with a move now needs the Entra sign-in an update needs.
- **Review follow-up to the two fixes above.** `state_pending` used to outlive the board's own change of State: a
  person who closed the item by hand left the flag on the create's ledger line, so a later reopen was pushed back to
  Closed. The exception for an owed move now holds only while the item's revision is still the one the create
  returned (`ado_sync_model.ownership_for_link` takes the board's item), the same revision the move tests. The
  one-hop creation finding (`Issue does not allow creation -> Closed`, said under `plan --validate` when the second
  hop is not known) has its pin back.
- **Two-step creates told truthfully where a count or a dialog repeats them.** The `writes_per_run` note called a
  row what is a write: one two-step create at a cap of 1 read `2 rows is over limits.writes_per_run (1)`. When a move
  is among the writes it now reads `2 writes (1 row, 1 of them a create then a move) is over limits.writes_per_run
  (1)`; with no two-step row the note is word for word what it was. Shepherd's apply dialog dropped `via`, so a
  create in Active then moved to Closed was drawn as one write in Closed; it now keeps `via` and ends that op's line
  with the plugin's words, `(created Active, then moved)`. The dialog shows a row count (`pendingRowCount`, a row is a
  row however many writes it sends) and never a write count, so it has none to correct; the plan's `cost` block is
  where writes are counted.

## 2.0.0 — 2026-10-12

### Shepherd — the brand update

The plugin and its desktop app are now **Shepherd** — one name for both; "SDLC Studio" and the
Tōgō working brand retire (`docs/proposals/shepherd-brand-update.md`). Brand is a surface, not a
schema: everything a person *reads* changes, everything a project *stores* does not, and no
existing project migrates its data.

- **Plugin id `shepherd`.** Install with `/plugin marketplace add MCKRUZ/shepherd-sdlc` then
  `/plugin install shepherd@mckruz`; the marketplace is still `mckruz` and the repository is
  `MCKRUZ/shepherd-sdlc` (GitHub redirects the old URL). Claude Code derives the agent namespace
  from the plugin's `name`, so agents are `shepherd:<agent>`. The `sdlc-orchestrator` agent keeps
  its name — it orchestrates the SDLC.
- **Commands `/sdlc-*` → `/sprd-*`** (`/sdlc` → `/sprd`; all 32). No aliases — 64 commands is
  worse than one rename. The session-start banner lists the new names every session.
- **Hook files and markers.** `hooks/sdlc-session-start.{sh,ps1}` → `hooks/shepherd-session-start.*`;
  `[SDLC]`, `[SDLC-PHASE]`, `[SDLC-SPRINT]`, `[SDLC-CONVENTION]`, `[SDLC-HEALTH]` and
  `[SDLC-CONTEXT:…]`/`[/SDLC-CONTEXT:…]` → `[SHEPHERD…]`/`[/SHEPHERD…]`. Only the model reads
  them; no script or screen parses a marker.
- **`SHEPHERD_CODE_HOST` is read first; `SDLC_CODE_HOST` is still read.** A shell or pipeline
  that already sets the old name needs no change.
- **The desktop app is Shepherd** (`appId` `com.mckruz.shepherd`). Its userData folder is
  unchanged, so settings, recent projects, synced objects and local preferences stay where they
  are — no migration code. macOS asks Gatekeeper's first-run and folder-access questions once
  more for the new bundle id; on Windows the new installer sits beside the old app (both share
  the data folder, so one runs at a time) and the old one uninstalls normally.
- **Harness payload generated through `sync_kit.py`'s rename map.** `harness/` is still copied
  from the kit; its brand strings are rewritten in place as bytes, and `sync_kit.py --check` is
  the invariant (`harness == rename(kit)`). Repositories installed before the rename see
  `ONBOARDING.md`, `docs/harness.md` and `.github/RAILS.md` as UPDATE on their first
  `/sprd-upgrade`; adapted copies become CONFLICT and are shown, never overwritten.
- **Generated HTML reports re-themed.** The phase, index and sprint pages use the Shepherd
  palette (parchment by default, bark when the system prefers dark) and their footers read
  "Shepherd — …". Stdout, exit codes and `--json` shapes are unchanged.
- **Unchanged, deliberately:** the `.sdlc/` directory, `specs/`, every metrics ledger, gate ids,
  exit-gate wording (hashed into confirmation ids), and "SDLC" wherever it names the lifecycle
  rather than the brand. Already-written artifacts keep `/sdlc-*` in their prose — owner content
  is never rewritten.

---

## Migration — Shepherd

**Nothing in `.sdlc/` migrates.** State, specs, ledgers, sign-offs and confirmation ids are
byte-for-byte what they were. The steps below are about what is installed, not what is stored.

1. **Reinstall the plugin under its new id.** In Claude Code:
   `/plugin marketplace add MCKRUZ/shepherd-sdlc`, then `/plugin install shepherd@mckruz`. Then
   uninstall `claude-code-sdlc@mckruz`, so the old commands and session-start hook do not sit
   beside the new ones.
2. **Run `/sprd-upgrade` in each project.** It re-installs the renamed harness payload and
   rewrites the `(auto-injected by /sdlc-setup)` section of the project's `CLAUDE.md` to the
   `/sprd-*` names. A hand-adapted harness file is shown as CONFLICT, not overwritten.
3. **Rename your habits, not your data.** `/sdlc-status` is `/sprd-status`, `/sdlc-next` is
   `/sprd-next`, and so on — the prefix is the only change. `SDLC_CODE_HOST` keeps working;
   `SHEPHERD_CODE_HOST` wins when both are set.
4. **Desktop app:** install Shepherd 2.0.0 and open the same projects — nothing to re-add.
   Upgrade the app before the plugin if you run both: a 1.x app cannot find a 2.0 plugin, while
   the 2.0 app finds either.

---

## 1.7.0 — 2026-10-06

### SDLC Studio — the command center

The desktop app reorganises around the Build loop (`docs/proposals/togo-command-center.md`, built
as eight packages with disjoint file ownership, integrated and verified end to end). The sidebar
retires; a top band (the mark and project name, the **omnibar** trigger, the needs-you chip, the
sync chip, Console · Appearance · Settings · `…`) and an SVG **lifecycle strip** of the nine
stations replace it; a project in the Build loop lands on the **sprint home**, every other
project on the **lifecycle home**. What a team sees:

- **The sprint home.** Four lanes that are the loop — Ready, Building, Checking, Merged — as a
  partition of the plugin's own `status`, `dor`, `verdicts_pending` and the pull request's
  `waiting_on`; the hand-off **baton** on the Building→Checking edge; a Today column ("needs you"
  by exact handle, "Team is waiting on", "since yesterday" from `sprint.py log`); **In the room**
  (who holds what — dots, never digits); **Refining** for the next sprint with the checker's own
  DoR gaps; **How it is going** from the steering scorecard. `j`/`k` move, `↵` opens the spec
  card, `h` hands off, `v` records a verdict.
- **The omnibar.** ⌘K takes plain words — `verdict 0002 accepted`, `hand 0006 to Sam`,
  `defer 0003 to S08 because …`, `decide DL-02 …`, `new sprint` — resolves ids and names only
  against the board and the roster, and opens a dialog that shows the exact `sprint.py` line, who
  it is recorded against and what the plugin will check. Nothing runs before Confirm; the answer
  is the plugin's stdout/stderr verbatim under **Done** / **Not done** / **Refused by the plugin**
  (exit 0 / 1 / 2). A name the roster does not know is a visible gap, never a guess.
- **Planning, the spec card, close, steering.** Planning: the refined backlog READY-first, the
  slate in the plugin's build order with Builder / Checker pickers, what the plugin says, its
  deterministic proposal, and one **Commit** that runs `slate → ready → plan → report` and stops at
  the first non-zero exit. The spec card, opened in place: Definition of Ready verbatim, the
  **checking ladder** coloured only by the code host's conclusions (correctness is always "no
  data"), the findings ledger with the plugin's dispositions, and a **Hand off** foot disabled
  with `handoff.py`'s own refusal. Close: outcomes, kept, open specs each carried or dropped with a
  reason. **Steering mode** (`g t`): the standard's numbers on tiles at 56 px, read-only, no chat,
  no console, zero write controls.
- **The truth rule, enforced.** The renderer never spawns, never joins across sources and never
  derives a status: the main process assembles one `CommandCenter` read model with per-block
  provenance ("`sprint.py status --json`", "as of 10:42") and runs every write through a closed
  argv table with the signed-in person as `--by`. "no data" is never a fabricated zero (a count
  of zero recorded events reads "none recorded in this window", the plugin's own wording); no
  velocity, points, PR counts, lines or hours anywhere; a disabled control always carries its
  reason, as a tooltip and as its accessible description.
- **Visual direction** (`docs/proposals/togo-command-center-visual.md`): 46 colour tokens and six
  type tokens, every text pair ≥ 4.5:1 and every edge ≥ 3:1 in both themes (measured); the Depth
  gradient gains one home — the steering lockup; brand figures for every empty state; three new
  choreography rows (`batonPass`, `verdictSeal`, `stripDraw`) that quieten with familiarity and
  whose end state equals a cold reload.
- **The cockpit round** (the owner's v12 critique, rounds 3–4 on the same branch). The sprint
  home's first screen is now a cockpit: the four lanes in ONE row with Today as a 300 px right
  rail from 1240 px of width, the home grid's row sized to the window (`100dvh − chrome`, the
  chrome measured live from the grid's own top, `lanes/cockpitLayout.ts` + `useCockpitChrome.ts`)
  so every lane is visible without scrolling at 1440×900, wells and rail ending on one line 24 px
  above the fold and the band below never sliced on it; cards scroll inside a lane; Today is a
  capped strip with a bottom fade under 1240. The chat starts **collapsed** to a 40 px rail on the
  sprint home and planning (`stores/chatStore.ts`, per area, remembered per machine; the band's
  Chat toggle, the `…` row and ⌘\ reopen it; it stays mounted so the a11y pins hold). The
  business-day bar spans the header; a mix short of target is a warn-tone chip. Planning's slate
  names every row (`minmax(12rem,1fr)` floor, pickers on a second line under 820 px). The spec
  card's scroll region is masked under the sticky Hand off foot; the findings caption no longer
  overlaps its chip. Steering mode pages (snap-y, each row a page ≥ the room's height) so no tile
  straddles the fold, and no description truncates. "Since yesterday" shows the ledger line's
  full sentence (two lines allowed), once. People rings stack later-above with the you-ring last.
  `main#main { position: relative }` keeps the root from ever scrolling (the review and closing
  screens were offset 8 px). The constellation's anchor plates draw under their bodies (`useFrame`
  priority −1). One Escape-owner list (`shortcuts/escOwners.ts`) so a menu or hover card answers
  Esc alone. Focus returns to the acted-on card only after the refreshed read.
- **Radix under the kit** — the one dependency added: `@radix-ui/react-{dialog,tooltip,hover-card,
  tabs,dropdown-menu,popover}` + `cmdk` under `Dialog` / `Tooltip` / `HoverCard` / `Tabs` / the `…`
  menu / the palette; the kit keeps the `#overlays` portal, literal `role="dialog" aria-modal`, the
  catalogue's motion and the disabled-carries-its-reason rule. Main chunk 737 → 772.7 kB
  (test mode, Vite's report; ≤ 800, `bundleSize.test`).
- **Mechanics** — the command-center cache carries an `epoch`: a block whose spawn started before a
  write and settled after it is handed to its caller but never stored. A host error that already
  names the failure is said once, with Retry. Scope `<!-- -->` comments are stripped; an empty
  section reads "no data — the section is empty". Provenance reads mono lower-case.
- **QA tooling** — `test/e2e/cc/overlap.spec.ts` measures the shell's landmarks in the real window
  (1280×800 and 1440×900, light and dark, four screens: inside the viewport, no unintended
  intersection, the root never scrolls, lane bottoms == rail bottom == fold − 24, a chip never
  crosses its caption); `cockpit.spec.ts` walks the command center end to end against the real
  plugin; `steering.spec.ts` checks the paging. The capture script grew the same probe
  (`SHOT_OVERLAP=1 SHOT_WIDTHS="1280x800,1440x900,1680x1000"`, exit 3 on a violation) beside its
  ghost probe and GPU-line check. Verified on this checkout: typecheck clean; vitest 299 files ·
  3344 passed · 7 skipped; pytest 3622 passed · 19 skipped, protected list clean; Playwright 173
  passed · 3 skipped; `observatory-v14` captured (59 shots at 1280×800 · 1440×900 · 1680×1000,
  light and dark; 0 GPU console lines; overlap probe 0 violations; ghost probe 0 deviating rows,
  worst 1/255, at 1.2 / 1.6 / 2.0 / 2.5 s). The user guide (`docs/guide/togo-user-guide.html`) is
  rebuilt on `observatory-v14` with "The cockpit" and "Keyboard and the omnibar" passages;
  `docs/proposals/togo-before-after.md` is the owner's before/after.

### Plugin — additive sprint and spec verbs (1.7.0)

Every existing verb keeps its text and exit codes (goldens pinned); the protected core is
byte-for-byte unchanged. New, all additive and tested:

- `sprint.py list [--json]` (sprints with 1-based `ordinal`, `active`), `sprint.py log [--since]
  [--sprint] [--json]` (the ledger's lines verbatim, undated lines kept, corrupt ones counted),
  `sprint.py carry --spec --to --reason --by` (one `carried` event in close's exact shape) and
  `sprint.py edit --sprint --goal --by` (`sprint_edited`, appended to `sprint_model.EVENTS`).
- `spec_transition.py confirm-tier --by` (writes `risk_confirmed_by`; `risk` clears it on a tier
  change and reports `confirmation_cleared`) and `assign [--developer] [--checker] --by` (roster-
  checked; refuses `developer == checker` with `handoff.py`'s own sentence).
- `handoff.py --check` — the dry run: the same refusal kinds and messages as the live hand-off,
  before any git operation, plus `would{branch, developer, checker, team, in_flight_after}`.
- `spec_readiness.py --spec --json` gains `ladder{tier, touches_gated_path, rungs[]}` from
  `risk_model.required_rungs`; `--all [--json]` reads the whole backlog in one pass.
- `record_findings.py report --json` gains `findings[]` (one row per fingerprint with its latest
  disposition, `off_books`, `first_seen`/`last_seen`/`rounds`) and `recurrence{}`; `--spec PATH`
  attributes findings to a spec by its scope paths.
- `spec_status.py --all` rows carry `deferred_reason`; `capabilities.py` declares `sprint-list`,
  `sprint-log`, `sprint-carry`, `sprint-edit`, `sprint-write`, `confirm-tier`, `assign-roles`,
  `handoff-check`, `findings-json`, `readiness-all` — each proven against the real `--help`.

### SDLC Studio — upgrade round 2: the instrument, the ceremonies, the craft

A second design round on the desktop app, planned in `docs/proposals/studio-upgrade-2.md` from
five independent design lenses and two judges, built as eight packages with disjoint file
ownership, reviewed adversarially and verified end to end. What a team sees:

- **Brand in the product.** The solid Macron stays the mark everywhere in the UI; a sanctioned
  gradient treatment — *Depth* (`#6FD1D4 → #0A3F47`, theme-aware) — lives only at hero size
  (Welcome, the opening card, the dock icon). The dock icon is finally SDLC Studio's tile, not the
  scaffold's; `docs/brand/togo/build-assets.mjs` regenerates every export deterministically;
  the brandbook says exactly where Depth may live.
- **Readable everywhere.** Dark-mode links and plate text use a dedicated accent-text pair;
  every section label passes AA; the small type scale no longer letter-spaces body text.
- **Every screen reads in order.** A `PageHeader` (area eyebrow · title · lede) on Stage, Board,
  Sprint, Settings and Closing; a stage summary strip (documents · current step · sign-off);
  a document outline with gap markers; Board rows as columns with status chips and a one-line
  notice; Sprint title first with a fact strip and grouped verdicts; the spec page gains a facts
  rail and an inline dependency neighbourhood; honest empty states with figures drawn in the
  product's own vocabulary; "today" and "—" where a zero would have lied.
- **The instrument.** Fresnel-rimmed bodies, a lighting rig with contact pools and a theme-aware
  grid; a viewing reticle on the Spine that marks the stage you are reading; ledger plates on
  the Closing rail naming who signed what; hover and focus affordances in 3D; an "In a graph"
  shortcut group and palette actions; scene arrival with prefetch and crossfades; a Board graph
  fitted to its bodies and plates.
- **Ceremonies.** Sign-off, hand-off and the opening each play as one timeline from the
  choreography catalogue; dialogs, toasts and hover cards animate; the theme change reveals as a
  dusk sweep; flourishes quieten after the tenth open. Every end state equals a cold reload;
  everything is off under reduced motion and in tests.
- **Found, not hidden.** The 1 px ghost strip over the Sprint title was measured with a probe
  (`SHOT_PROBE=ghost`) and bisected to its cause; sticky headers are now transparent at rest and
  solid only once content has scrolled under them.
- **A window that fits the display.** The app opens at the person's last size and place when that
  still lands on a connected display, else sized to the work area (up to 1680×1050, never under
  1180×720) instead of a fixed 1280×800, and its rendering scales with the window's width (1.0
  at 1440, 1.3 at 2560) so a wide display is not a field of small type; the guide's screenshots
  are embedded at their full 1440-px width as high-quality JPEGs (2× on the Linux and Windows
  runners via `SHOT_SCALE=2`; macOS fixes the device scale to the display). Steering mode is one board: Outcomes, Delivery and the actions on the
  first screen at 1440×900.
- **Not adopted: MUI.** A second component system would fork the one token set the app just
  gained and add ~300 KB to a main chunk with 188 KB of room; three.js and GSAP carry the round.

### Code-host providers — GitHub and Azure DevOps

The code lives in Azure DevOps repositories as well as GitHub ones, and until now every
pull-request-facing read and write went through `gh` alone — an Azure DevOps project got
pipelines and a board built from spec files, with no live "who is this waiting on" and a hand-off
whose draft PR could never open. `docs/proposals/code-host-providers.md` adds Azure DevOps through
the Azure CLI as a second provider **without changing a byte of GitHub behaviour**: the same
argv (pinned by `scripts/tests/test_gh_argv_golden.py`), the same text, and every existing test
unmodified. The host is **chosen by the repository**, never by a global setting.

- **Detection and override** (`scripts/code_host.py`). `origin` → `github` / `azure-devops` /
  `none`, with `--host` on every host-touching script, `SDLC_CODE_HOST`, and a per-clone
  `.sdlc/code-host.yaml` (written by `set_setting.py code-host`) ahead of it; the harness
  manifest breaks the tie only when there is no usable remote. `none` falls through to `gh`
  exactly as before. Two axes stay apart: the code host comes from the remote, the CI platform
  from the installed pack — GitHub + Azure Pipelines is legitimate, and a mismatch is reported,
  never resolved silently. Every `--json` carries a top-level `host` block
  (`{name, source, cli, cli_state, detail}`) so a reader sees *why* a host was chosen.
- **One `az` module, gh-shaped returns** (`ado_import.py` with `ado_map.py`, `ado_transport.py`,
  `ado_pipelines.py`). Each function mirrors the GitHub function it stands in for by name and
  signature (`code_host.PROVIDER_FUNCTIONS`, pinned by `test_provider_parity.py`) and returns
  the dict shape `gh` returns today, so the pure models and the honesty paths are reused, not
  re-implemented. `AdoImportError` subclasses `GitHubImportError`, so every existing `except`
  already catches an `az` failure.
- **Read-back, not just a write target.** `spec_status.py` (per spec and `--all`),
  `connection_report.py`, `pipeline_proof.py`'s PR reads, `gate_auth.py status` (variable
  groups) read Azure DevOps as they read GitHub, and `gate_inventory.py` finds the gate
  pipelines under `.azuredevops/pipelines/` on an Azure Pipelines install. `handoff.py` opens a
  draft PR with the checker as `--required-reviewers <email>` and names the developer in the
  description (ADO has no assignee); a checker with no roster `email` is an `assignment_error`
  with the local half still complete. `gate_auth.py set` / `clear` print the manual `az`
  command rather than writing a variable group from here.
- **Scorecard import on either host** (`import_outcomes.py`, `ado_outcomes.py`). GitHub
  delegates literally to the frozen `scorecard.import_events`; Azure DevOps maps PR completions,
  vote threads, environment deployment records and `incident`-tagged Bugs into the same ledger
  with `ado-*` ids that never collide with `gh-*`. What Azure DevOps does not record is said,
  never zeroed: a `review_wait` with no request timestamp has no `wait_hours` key and is counted
  on its own line; an unreadable category reads "not imported".
- **Identity.** The roster key stays `@handle`; `people[].email` (optional, unique,
  case-insensitive) is the only way an Azure DevOps sign-in resolves to a handle. Nothing
  guesses from a display name or a UPN prefix.
- **Honesty rules** (`host_report.py`). `cli_state` is read from the outcome of the call the
  script just made, never from a second probe; it reads `unknown` when nothing could be
  determined; `updatedAt`, vote time and request time are `null` on Azure DevOps because the
  host has no such field; "unavailable" rides the `host` block and is never a false `no`.
- **Fixtures with provenance.** `scripts/tests/fixtures/code_host/azure_devops/captured/` is
  real `az` output captured 2026-10-05 from a live organisation and anonymised; its
  `CAPTURE-NOTES.md` records every fact that changed the design (reviewers' `isRequired` is
  `null` not `false`, `lastMergeCommit` sits on every active PR, system-comment prose is never
  parsed — the typed `properties` bag is, environments need `--api-version 7.1-preview` exactly,
  the CLI's default account decides the token). Hand-written documents stay marked
  `hand-written (unverified)` and `test_fixture_provenance.py` lists what is still unverified.
- **Protected and unchanged:** `scorecard.py`, `github_import.py`, `doctor.py`, `check_gates.py`,
  `check_spec.py`, `advance_phase.py`, `phase_model.py`, `new_spec.py`, `harness/**`,
  `pipeline_proof_model.py`; `sprint.py` text and exit codes; the doctor's text goldens.
- **Docs:** `references/code-host-providers.md` is the on-demand contract; README gains a
  **Code hosts** subsection (which features need which CLI, `az login
  --allow-no-subscriptions` for guest identities, `email:` in `team.yaml`,
  `.sdlc/code-host.yaml`); the commands that named `gh` now name both CLIs.

### SDLC Studio — the brand and the Observatory UI

The desktop app keeps its name, **SDLC Studio**, and gains one visual identity; the plugin id `claude-code-sdlc`, the `studio/` folder and the `window.studio` bridge are unchanged, and the window title, `productName`, favicon and Welcome lockup carry the identity. The identity is deterministic SVG — a solid mark ("Macron", with "Lens" and "Seam" alternates), a wordmark, a teal–cyan accent (`#0E7C86`, 4.95:1 on white) with a 50–900 scale for light and dark, Inter for UI and JetBrains Mono for code — recorded in `docs/brand/togo/` (`palette.json`, PNG exports, `togo.ico`, `brandbook.html`). Two standalone HTML guides for teams live in `docs/guide/`: how to stand the tool up, and how to use the app. The install path is unchanged (`/plugin marketplace add MCKRUZ/claude-code-sdlc`, `/plugin install claude-code-sdlc@mckruz`); the desktop app's bundle id is `com.mckruz.sdlc-studio`.

The app's screens had grown one spec at a time, each carrying its own Tailwind strings, so there
was no dark theme, no shared control vocabulary, no keyboard route through the app and nothing
that told a screen reader which tab was selected. The Observatory (`docs/proposals/studio-observatory.md`,
spec 0033) gives every screen one visual system and adds two 3D scenes that draw strictly what the
plugin reports. Renderer only: `studio/shared/**`, `studio/electron/**` and the Content-Security-Policy
line are byte-identical, and `test/noNewIpcInRenderer.test.ts` fails if any of the new layers
reaches for `window.studio`.

- **Tokens and a dark theme.** `src/theme/` holds the design tokens; dark is a remap of the colour
  ramps, so every screen flips at once. Theme (System / Light / Dark) and Density (Comfortable /
  Compact) are per-person `localStorage` preferences under Settings › Appearance and the sidebar's
  Appearance button; Inter Variable and JetBrains Mono Variable ship as bundled woff2.
- **A UI kit with typed contracts** (`src/ui/contract.ts`): Button, Card, Chip, Notice, Eyebrow,
  Segmented, Tabs, DataTable, DefinitionList, Dialog, Toast, HoverCard, StatTile, NoData, and the
  rest — with the strings existing tests pin spelled out literally (Button's `type` attribute
  first, `bg-brand-600` on primary). `DocumentsTab`, the last byte-pinned screen, moved onto the
  kit; its byte-equality test became a named behaviour suite written before the component changed.
- **One motion rule.** Animations are Auto / On / Off: Auto honours the OS reduced-motion
  setting, On is an explicit per-person opt-in over it, Off disables everything, and under test
  no tween is ever created. GSAP choreographies are scoped per component and the global timeline
  pauses when the window is hidden.
- **Command palette and shortcuts.** ⌘K (Ctrl+K) or `/` opens the palette from anywhere;
  `src/shortcuts/shortcutMap.ts` is the single keyboard map (`g` `b` for the Board, `[` / `]`
  between stages, `1`–`3` for a stage's tabs, ⌘J console, ⌘, Settings) and the Shortcuts help
  (⌘/ or `?`) renders the same data. ⌘W/Q/R/1–9 and the F-keys stay with Electron and the OS.
- **Focus model.** A skip link to `main#main`, page headings that take focus on navigation,
  roving tabs with `aria-controls`, `aria-pressed` on every segmented control, a `#overlays`
  portal root with focus trap and restore, and an Escape that closes the innermost layer and
  never discards an unsaved edit (the field editor, hand-off form and an open AI proposal
  register as dirty). The Board and Sprint e2e now assert selected state with `aria-pressed`
  rather than class names.
- **Lifecycle Spine, Dependency Constellation, Ambient field** (`src/scenes/`). Each scene is a
  lazily loaded canvas with a Graph / Table toggle where the Table twin is the real content —
  what shows when WebGL is unavailable, the window is under 400 px, the canvas crashed, or Studio
  is under test. Honesty notes: the Spine draws the stage order and the sign-off state
  `stage_readiness.py` reports and computes nothing; the Constellation's node size comes from the
  risk tier alone, a `depends_on` id with no spec is a ghost drawn from the id, and prose length
  influences nothing; a null from the plugin reads "no data", never a 0; no per-person totals
  anywhere. The Ambient field renders only behind the entry screens, gated by
  `AMBIENT_ENABLED && motion.enabled() && canUseWebGL()`.
- **Absorbed from `studio-improvements.md` Batch 4:** F11 (a picked activity renders in the main
  slot via `FocusedActivityHost`, the left column keeps only the list) and the accessibility
  basics (landmarks, progressbar, tabs, `aria-pressed`, axe pass in `test/e2e/a11y.spec.ts`).
- **Bundle** (`vite build --mode=test`, 2026-10-05): main chunk 574.8 KB against the 800 KB
  budget `test/bundleSize.test.ts` enforces; `scene-core` 941.8 KB loaded on the first canvas
  mount only; per-scene chunks 2–18 KB; CSS 60 KB.
- **Integration fixes found by the real-window run (Wave 3).** `SceneShell` short-circuited
  `useOnScreen(ref) && usePageVisible()`, so a figure scrolling off screen changed the hook count
  and React #311 unmounted the whole window — jsdom's inert IntersectionObserver never showed it;
  `test/scenes/sceneShellHooks.test.tsx` now flips a firing observer. Spine table rows gained a
  visually-hidden "Go to " prefix so their names no longer collide with the sidebar's stage
  buttons (`/^Build Loop/`). "Not delivered" on the Foundation explainer is a real `<h3>` again,
  not the Notice's `<p>` title. HistoryPanel's Compare / Restore dropped a `disabledReason` that
  repeated the row's sentence and leaked into the buttons' accessible names. The constellation's
  sr-only summary says "not yet ready" so it adds nothing to the sprint spec's "NOT READY" count.
- **Tests:** vitest 180 files, 2167 passed, 5 skipped (pre-existing); `npm run typecheck` clean;
  Playwright real-window suite with `STUDIO_SKIP_LIVE_MODEL=1`: 101 passed, 6 skipped (need
  `gh` sign-in or a live model), 2 failed — both pre-existing at `acab7cf` and both in
  `sprint.spec.ts`, where the plugin's own wording conflicts with the pin: the readiness card's
  gap lines also say "NOT READY" (count 6, pin 3) and the no-sprint note from `sprint.py` wins
  over Studio's sentence in `shared/sprintModel.ts` (frozen); the 6 serial tests after the
  first of those did not run. Pinned tests (studio-observatory.md §8.3) changed
  only where listed: `documentsTab.test.ts` (byte-equal → behaviour suite), `board.spec.ts`
  (`bg-brand-600` / `bg-slate-900` class pins → `aria-pressed="true"`), `a11y.spec.ts` (waits for
  the stage heading before its one-shot DOM check), and the four activity-panel specs
  (`runActivities`, `batchJobs`, `modelRunner`, `briefForm`) which now press the row's "Open" and
  read the panel inside `[data-testid="focused-activity-host"]` — the F11 placement the design
  itself introduced; every panel testid and sentence is unchanged.

- **Studio can sign off a phase and advance it, without leaving the window.** Until now the only
  thing in Studio that finished a phase was Build's declare-complete flow; every other phase
  (Discovery → Requirements, and on) still needed `/sdlc-next` in Claude Code. The new "Sign off"
  panel on a stage's home (shown only once every document is complete and every judgement
  question is confirmed) runs the same sequence `/sdlc-next` does: check the exit gates, draft and
  validate a condensed "frozen layer" summary of the phase (the one step needing a real Claude
  call — every artifact is read and pasted in, since Claude cannot read files in this call),
  snapshot the artifact record, then advance, with optional discipline sign-offs. A refusal names
  exactly which step stopped it and shows the plugin's own words. `advanceAfterDeclaration`
  (previously Build-only) is now the shared advance step for both flows. `.sdlc/context/layers/`
  is now synced — previously absent from the allowlist, so a frozen layer would have stayed
  local forever.

### Studio — the sprint layer surfaced, CLI compatibility, hardening

Studio shipped with no sprint surface at all: `phases/activities.yaml` declared nothing for the
Build phase, nothing in `studio/` called `sprint.py`, and a team running `/sdlc-sprint` saw their
sprint only in a terminal. One defect meanwhile disabled every model-backed feature on an older
Claude Code, and a handful of medium defects would have bitten a team daily. This change (Batches
1–2 of `docs/proposals/studio-improvements.md`) fixes those and gives the sprint a read-only view.

- **Works on every current Claude Code.** Studio passed `--permission-prompts none` to every
  `claude` call — a flag Claude Code 2.1.289 has and 2.1.239 does not, so on the older CLI every
  chat, draft, review and sign-off failed with `unknown option` and the test fake, which accepted
  any flag, could not see it. The shared safe arguments are now `--permission-mode dontAsk
  --strict-mcp-config` (both CLIs; `dontAsk` auto-denies anything not pre-approved, which was the
  old flag's intent). `shared/claudeContract.ts` names every flag Studio emits
  (`REQUIRED_CLAUDE_FLAGS`) and `tooling.ts` runs `claude --help` once per detected version to
  report `missingFlags` on the Claude tool status; Tooling and Settings say "Claude Code <ver>
  lacks <flags> — update with `claude update`" and the model buttons stay enabled only when
  nothing is missing. A zero-cost contract test parses the real CLI's help.
- **Studio drives the plugin beside it.** Auto-detect preferred the newest *cached marketplace*
  plugin, never the checkout Studio ships in (the README said the opposite). Unpackaged, Studio
  now prefers `<APP_ROOT>/../scripts` when it carries `capabilities.py` (the marker), and Settings
  and Tooling show which plugin path and version are in use.
- **Build ends from Closing, not from the generic sign-off.** The stage sign-off panel had no
  stage check, so Build could be signed off around `declare_complete.py`. For `build` the panel
  now says so and links to Closing; `signOff.ts` refuses `build` outright.
- **Sign-off fails closed and cannot lose a layer.** A `check_gates.py` error (non-zero exit with
  no MUST lines) was read as "no failures"; a failed re-sign-off could overwrite the previous
  phase layer with an unreviewed draft. The gate step now fails closed, and the previous layer is
  set aside as `.superseded-<YYYYMMDD>` (the name `/sdlc-next` uses) before any draft is written
  and put back if no draft validates — a failed re-sign-off leaves the layer exactly as it was.
- **Sprint records sync.** `.sdlc/sprints/SNN.md` was not on the sync allowlist (the spec keys and
  the ledger were), so a sprint planned in Studio stayed local. Added; the layers entry is
  narrowed to `*.md` so `.superseded-<date>` copies stay local.
- **Redacted stdout is never parsed as data.** Twenty-eight call sites parsed `entry.stdout` —
  the console copy, where `token:` and `auth:` values are rewritten — as JSON. Every one now
  reads `rawStdout(entry)`, and a vitest lint fails the suite on any new `JSON.parse(x.stdout)`.
- **Path allowlist checked after normalisation.** `specs/../.git/config` passed the allowlist
  because the match ran before the path was resolved; `..` segments are now rejected first.
- **The board tells the truth.** The dead "group by epic" is replaced by **group by sprint** (rows
  carry `sprint`, `nextOwner`, `engReview`, `dataReview`, `dependsOn` from `spec_status.py`), a
  sprint chip sits on each card, the status filter gains `deferred`, "Nothing is waiting on you"
  is no longer claimed when nobody is signed in, and "waiting on me" counts `next_owner == me`.
- **Test infrastructure.** `vitest.config.ts` gives setup hooks the same 29s ceiling tests have:
  the draft and batch suites build a real project (`init_project.py` through the plugin's venv,
  then a git repository) in `beforeEach`, and with the sprint-view suites added the full parallel
  run pushed those hooks past the 10s default on one machine while they passed alone. The work is
  real, not a hang. Suite: 133 files, 1771 tests (+173), 5 skipped without a live model.
  The installed `specs/spec-template.md` — a phantom board row and a Closing "unreadable spec"
  blocker — is excluded by `spec_status.py` and `declare_complete.py` with the same `^\d{4}-`
  filter `track_specs` and `sprint.py` already apply.
- **The plugin declares the Build activities.** `phases/activities.yaml` gains a `"build":` block
  — `sprint` (run, `/sdlc-sprint`; never "done", always available), `refine` (talk,
  `/sdlc-refine`), `phase-report`, `coach` — and `refine` under Foundation (`"3"`), so Guide and
  Workflow show the sprint layer with no Studio list to update. `activities_model.validate()` no
  longer raises on a malformed entry: unknown keys, wrong types, a `done_when` with the wrong
  arity are each a named problem (`phase <p> / activity <id>: …`), and `stage_readiness.py`
  degrades to no activities plus a warning rather than failing the report.
- **Capabilities and `--json` for the sprint scripts.** `capabilities.py` gains `sprint-status`,
  `sprint-plan` and `sprint-report` (proven against live `--help` by `test_capabilities.py`).
  `sprint.py status --json` slate rows gain `rel_path` (repo-relative, POSIX) and the sprint
  object gains `rel_path`; a malformed or unknown `--sprint` prints exactly ONE JSON document
  (`sprint: null`, empty lists, `has_data: false`, a `note` saying why) with exit 0 instead of
  prose. `sprint.py plan --json` and `generate_sprint_report.py --json` print `{ok, sprint,
  kind, output, rel_output}` (or `{ok: false, error}` with the existing exit code). Text output
  and exit codes without the flags are byte-identical.
- **The Sprint view.** A `Sprint` entry beside Board in the Build sidebar group, plus the
  `sprint` panel in Build › Workflow (`PANEL_CONTROLS.sprint`, capability `sprint-status`).
  `electron/main/sprint.ts` runs `sprint.py status --json` over a fixed argv with the sprint id
  validated before it reaches the command line (`studio:getSprintStatus`), and renders the
  planning or review page through `generate_sprint_report.py --json`
  (`studio:renderSprintReport`), opened with the existing `studio:openReport`. `SprintBoard.tsx`
  shows the header, slate, readiness gaps, verdicts pending, open handoffs, mix against target,
  WIP, the advisory build order and next-up, dependency gaps, decisions due and carried-in specs;
  `shared/sprintModel.ts` holds the pure helpers. Read-only — no write verb runs from Studio yet
  (Batch 3). Honest by design: `has_data: false` and `null` read "no data", never 0; no
  per-person aggregation; no velocity, points or estimates anywhere.
- **Protected core byte-for-byte unchanged:** `check_spec.py`, `check_gates.py`,
  `advance_phase.py`, `phase_model.py`, `phase-registry.yaml`, `section-evaluator`, `harness/**`,
  `/sdlc-coach`, `/sdlc-spec`, `new_spec.py`, `scorecard.py`, `generate_status.py`,
  `templates/state-init.yaml`. See `docs/proposals/studio-improvements.md`.

### Sprint team layer — `/sdlc-sprint` and `/sdlc-refine`

The Build loop had a backlog, a Definition of Ready, and a WIP cap — and no way for a team to
commit to a set of specs for two weeks without reaching for a board and the velocity chart that
comes with it. Two documents shipped contradicting the standard's own rule meanwhile: the
retrospective template asked for "Sprint velocity (avg)" and `docs/integrations.md` said "there is
no sprint plan". This change adds a sprint layer that is a *commitment window over the backlog
order* — never a second backlog, a reordering, or a gate — and fixes both sentences.

- **`/sdlc-sprint` — the sprint board.** A named human types a sprint id (`S07`), slates a *count* of
  specs by a mix of risk tiers (`HIGH:1,MEDIUM:2,LOW:3` — the axis that sets checking depth; a mix
  breach warns, over-target exits 1 unless `--override --reason`), sees the slate's readiness every
  day (`status`, with the advisory build order and next-up), **readies** the sprint once every
  slated spec clears the DoR **and** its independent Engineering and Data verdicts, and **closes**
  it with kept / carried / dropped — each carry or drop with a name and a reason. `ready` writes the
  self-contained sprint-planning page, `close` the review page. Backed by the pure
  `sprint_model.py` (mirrors `findings_model.py`), the I/O CLI `sprint.py`, and
  `generate_sprint_report.py`; the sprint record is `.sdlc/sprints/SNN.md`, the ledger
  `.sdlc/metrics/sprint-log.jsonl`. Two new commands.
- **`/sdlc-refine` — refinement with an agenda.** The Mon/Wed/Fri cross-functional review and the
  weekly Intent triage, made executable: NOT READY specs and why, verdicts pending with their
  business-day age, unacknowledged handoffs, overdue `DL-NN` decisions; then one spec at a time
  through `check_spec` and `/sdlc-spec`. `validate --lane eng|data` records the verdicts `ready`
  requires; `--upstream` fixes a Phase 1/2 gap by editing the artifact in place (human-confirmed
  diff), recording it to the artifact ledger, re-gating that phase with `check_gates.py --phase N`
  as information, and regenerating that phase's layer — so the engagement never regresses a phase
  and earlier-phase artifacts can change during refinement as the normal case.
- **Phase layers are living, not frozen.** The "frozen layer" was a prose rule nothing enforced,
  and it contradicted refinement: a summary of artifacts that changed is a false summary. Layers
  are now regenerated whenever a source artifact changes (refinement, `/sdlc-revise`,
  `/sdlc-refresh`), the previous version kept as `.superseded-<date>`, the regeneration recorded as
  `refreshed`. Sign-offs in `state.yaml` are never rewritten; the `## Locked Metrics` heading keeps
  its name because the G5 gate reads it literally. `references/frozen-layers.md`, `SKILL.md`,
  `/sdlc-next` step 5 and the layer template say so; file and script names keep "frozen" for
  compatibility.
- **Five optional spec keys, one writer.** `sprint`, `next_owner`, `eng_review`, `data_review`,
  `depends_on` — `""` by default, values are enumerations, names and spec ids only, written solely
  by `sprint.py` on files matching `^\d{4}-` (the installed `specs/spec-template.md` is never listed
  or written). `status` is not one of them and stays hand-moved; a spec without the keys behaves
  exactly as before, and a test proves `check_spec`'s verdict is unchanged after insertion.
  `track_specs.py` gains `by_sprint` and `--sprint SNN` with legacy output byte-identical.
- **Never a gate, never gated, never `state.yaml`.** Reads exit 0 always; `ready` and `close` check
  only the slate, never G1–G7; `close` never suggests advancing — leaving Build stays a release-
  scoped human declaration. Writers write frontmatter first, then the ledger line, and print `DRIFT`
  (exit 1) if the append fails so the mismatch is never silent.
- **The metrics policy, enforced.** `FORBIDDEN_FIELDS = scorecard.FORBIDDEN_TYPES ∪ {points,
  estimate, effort, hours, capacity}` is refused with exit 2 and scorecard's wording; no per-person
  aggregation exists in any JSON; empty series read "no data", never 0; an AI `--by` is refused as
  labelling, not enforcement. `/sdlc-retro` gains carry-over recurrence per spec (≥ 2 sprints — the
  only cross-sprint number) and bounce causes by lane and reason. The retrospective's velocity row
  is now "Sprint commitment outcomes"; `docs/integrations.md` now says a sprint is a time-boxed
  commitment overlay on the backlog order.
- **Session start knows the sprint.** Both hook twins print `[SDLC-SPRINT] S07 (ready) — "goal" —
  start → end` per non-closed record (grep only, never throws), the Build reminder points at
  `/sdlc-refine`, and the stale `session-handoff.json` section summary — a section-plan progress
  model competing with the spec backlog — is retired. First session-start hook test.
- **Protected core byte-for-byte unchanged:** `check_spec.py`, `check_gates.py`, `advance_phase.py`,
  `phase_model.py`, `phase-registry.yaml`, `section-evaluator`, `harness/**`, `/sdlc-coach`,
  `/sdlc-spec`, `new_spec.py`, `scorecard.py`, `generate_status.py`, `templates/state-init.yaml`.
  See `references/sprint-model.md` and `docs/proposals/sprint-team-layer.md`.

## 1.6.2 — 2026-09-28

- **Sign-off questions can now be ticked, with a pre-check beside each.** Every phase's exit gate
  carries questions only a person can answer ("Scope boundaries are unambiguous"). They were a
  plain list. Each now has a box that a named person ticks — recorded with who and when in
  `.sdlc/metrics/confirmation-log.jsonl` (append-only, so two people ticking on two machines never
  overwrite each other, and synced by Studio) — and, on the right, what the software could see:
  "Looks done — 4 dimensions each state pass and fail thresholds and where they are read from.
  Confirm you agree." / "Not yet — 2 of 3 dimensions have a named source" / "Needs your
  judgement". A hint is a pre-check, never a verdict: "Looks done" leaves its box empty. Hints
  exist for Phase 0's four questions and Phase 1's architectural-question and decision-log ones;
  every other question says it needs judgement. `/sdlc-next` now reads the record and will not ask
  for sign-off while a question is unconfirmed (`sign_off_confirmations.py`, `confirmation_hints.py`;
  `stage_readiness.py --json` gains `judgement` and `confirmed_count`). A question reworded later
  gets a new id, so a tick is never carried onto a question nobody read. `advance_phase.py` and
  the phase registry are unchanged — the rule is in the command's instructions, so someone
  running the low-level script by hand can still skip it.
- **Fixed: a remote-added section could be silently deleted from the shared copy.** Found by
  this release's own automated correctness review, before it shipped. A document missing a
  required section still reading as sections (above) meant a document whose local copy never
  had a section at all no longer fell back to the safe whole-file comparison. When a teammate
  added that section and pushed, the silent per-section merge computed the right value but had
  no local text to write it into, skipped the write, and still advanced the shared history —
  so the very next save, with no further edit, pushed the local file over the remote's, taking
  the new section with it. Such a change now falls the whole document back to a whole-file
  clash, which never needs a place to write into a section: a choice replaces the entire file.
- **Fixed: 1.6.0's new shape fields could show a real document as having a gap it didn't have,
  and hide its content.** A labeled block matched its label word for word, so a document that
  wrote `**In scope (v1) — both halves of the one problem:**` where the template says
  `**In scope:**` read as missing the field: the completeness check reported it, and Studio drew
  "Not in this document" with the real text out of sight. A labeled block now also matches its
  label followed by a qualifier, ending at a word boundary (`**Included:**` is not `**In:**`).
  Inline labels stay exact, since `**Owner email:**` is a different field from `**Owner:**`.
  Measured on a real project: 1.6.1 added two findings versus 1.5.2, both in one section, and
  this removes both.
- **Studio: the stage list no longer says "Signed off" for a stage nobody signed.** The plugin's
  `stage_state: 'signed_off'` only means the stage's status is `completed`; the name is reported
  separately. A finished stage now reads "Completed" unless a name was recorded, and "Signed off"
  (with the name on hover) when one was. On a real project two of three finished stages had no
  name recorded and were both labelled "Signed off".
- **Studio: the stage list only highlights a stage while its documents are showing.** It kept the
  last stage clicked ringed on the Build board and Settings, which read as "these are that
  stage's things".
- **Studio: opening a project now shows a blocking "Opening…" overlay with a running clock.**
  Opening reads the project through the plugin and can take seconds; with nothing on screen it
  looked as if the click had done nothing, so people clicked again. Picking a folder or clicking
  a recent project now covers the window, names the project and counts the seconds, and takes the
  keyboard as well as the pointer, until the open finishes or fails.
- **Studio: the sidebar is now the only navigation.** The window had a list of phases beside a
  row of tabs (Documents, Build, How it is going, Closing Build, Settings) that looked as if they
  belonged to the phase picked; only Documents did. The tabs and the old header are gone. The
  sidebar shows the project, its progress, and the journey grouped as Foundation, Build, Ship and
  Close, joined by a rail. Build Loop, the one stage with screens of its own, opens Board, How it
  is going, Closing and Documents beneath itself. Settings, Console and the sync status sit in the
  footer. A stage signed off by a named person gets a solid tick and their name; one completed
  with no name recorded gets an outlined tick and says so. The current stage shows how many of its
  documents are complete. Build Loop reads "Specs, checks and close-out" rather than "Not
  started", since specs are built before the plugin marks the stage as reached.
- **Studio: a sync clash the header reports can now always be resolved.** When a file existed on
  both sides and differed, and Studio had no shared starting point for it (or it was not a
  document the plugin reads section by section), the pull reported a whole-file clash but never
  saved it. The header counted it ("4 sections need your input"), the clash screen, which reads
  what was saved, found nothing and never opened, the next pull raised it again, and saving was
  refused, so that file could not be saved from Studio at all. Every clash is now saved when it
  is raised, resolved by choosing mine, theirs or a combination without needing a shared starting
  version, counted in the header by what is actually waiting (including files frozen by an earlier
  pull), and cleared automatically if the two sides come to agree. Tested against a real git
  remote with a second clone as the teammate.
- **Documents that reword the template's headings now match their shape.** Measured across 70
  real documents in four projects, 55 did not match their template's headings and reached Studio
  as raw text, because a document that misses any required heading is read as free text. A heading
  now also matches by an `aliases:` entry the shape lists, or as the same words with numbering,
  case and punctuation ignored, or the template heading followed by a qualifier ("3. Deployment
  steps", "Deployment procedure (deploy-dev)"); none of these equates different words. Nine aliases
  are seeded from real documents. On the same 70 documents, 25 now match, up from 15. A document
  whose structure genuinely differs (a per-endpoint layout, say) still falls back to raw text.
- **Claude is now told to keep a template's headings.** `SKILL.md` gains a "Writing Artifacts" rule:
  start from the template, keep its `##` headings exactly (extra sections are welcome), and run the
  phase's readiness check before moving on. The phase guides only pointed at a template before.
- **A document missing a required section no longer turns to raw text.** Until now one missing
  required heading made Studio show the whole document as plain, uneditable text. The sections that
  are found are now shown as normal, the missing one is named in a notice above the document and in
  the readiness list, and only a document in which no section is recognized at all is plain text.
  Every section shown was found by its heading, so it is definitely that section; that is why the
  original "never a partial match" rule no longer earns its cost. `read` reports this as contract 3,
  so Studio flags an older plugin. On 70 real documents in four projects, 54 now show as sections,
  up from 15 in 1.6.1 (token-tracker: 13 of 13).
- **Fixed: Studio was rewriting document text that looked like a secret.** Studio masks anything
  shaped like `token: value` in its console and error messages, which is right for a panel a person
  might paste into a bug report. But the same masked text was what `git show` returned as a
  document's content, so a spec containing `id-token: write` (a GitHub Actions permission) arrived
  on the person's machine as `id-token=***`, was compared against the remote as if it were real,
  and showed as a clash that looked identical on screen. The same path carried the plugin's reading
  of a document (what Studio displays and edits), the text Claude combines or drafts for a
  document, and version and diff text. A command's entry now carries the exact output separately,
  never serialized to the window or the log, and those five places use it; everything shown or
  logged is still masked. Output is also decoded as a stream, so a multi-byte character (an em dash,
  a curly quote) cut by a chunk boundary is no longer turned into a replacement character. On the
  one project Studio had opened, one file was affected (two lines) and the remote's copy was intact.
- **Studio: the clash screen now shows how the two versions differ, and when each changed.** It put
  two full versions side by side and left the reading to the person; on a real project two versions
  of a 178-line spec differed in two words and looked identical. It now says in a sentence how much
  differs ("2 lines differ, out of 178"), shows only the changed lines with a little context, folds
  the identical stretches into one row each, and marks only the words that changed inside a line.
  Each side says when it was last changed: "Last saved" for your copy, and for theirs the time, who
  made the change and their own words for why. Neither side is coloured as removed or added, since
  both are somebody's version; they are labelled Yours and Theirs. The side-by-side full text is one
  click away.

## 1.6.1 — 2026-09-28

- **Studio: the stage list on the left is now navigable.** It was a set of inert rows and the
  stage screen was hard-wired to the project's current phase, so a signed-off phase such as
  Discovery could not be reached at all. Clicking a stage now shows that stage's documents and
  what is missing from it; the clicked stage is highlighted, and opening a project returns to
  its current stage. Covered by an end-to-end test that clicks a finished stage and back.

## 1.6.0 — 2026-09-28

Studio showed roughly half of every real document as raw markdown: template shapes covered only
the sections the phase gate requires, so every other section — real content, just not
gate-mandatory — fell through as unstyled text. A document that drifted from its template fared
worse: deleting any one section un-shaped the whole document.

- **Every section of every shaped template is now a field.** 92 previously-unshaped `##` sections
  across 28 shapes are declared, all `required: false`, so the phase gate and
  `check_document_completeness.py` behave exactly as before. `test_shapes_cover_templates.py`
  fails when a template gains a section its shape does not declare.
- **A document may drift from its template without losing its fields.** A section whose fields
  are all optional can be absent without turning the whole document into raw text; a missing
  *required* section still does. An undeclared `## ` section a person added is read as an
  editable `custom` section (one whole-body "Content" field) instead of raw text. This amends
  spec 0007's "never a partial match" rule; `document_shape.py`'s docstring and
  `docs/templates-artifacts.md` state the amended rule.
- **`document_shape_cli.py read` now states its contract** (`"contract": 2`). Studio recognises
  an older plugin by that key's absence rather than by version number — the 1.5.2 incident was a
  version that had not been bumped for months — and shows a banner pointing at
  `claude plugin update`.
- **Studio renders document markdown in read mode** (headings, lists, real tables, checklists)
  through `react-markdown` + `remark-gfm`. Raw HTML is dropped, links draw as text and images as
  their description, so a document a colleague edited cannot navigate the window or fetch a
  remote URL. Edit mode still shows the source, so saves stay byte-exact.
- **Fixed: the Design stage crashed on a project with an `adrs/` folder.** `stage_readiness.py`
  treated every registered artifact as one file, and reading a folder as text raises
  `PermissionError` on Windows, so Studio showed a raw traceback instead of the stage. A folder
  artifact is now reported as a folder (present, and non-empty by the gate's own rule), Studio
  lists it without offering to open it as a document, and opening a folder returns a clear
  message instead of throwing.

## 1.5.2 — 2026-09-26

The version had not been bumped since 1.5.1 despite substantial work landing on `master` in the
interim (SDLC Studio, the optional desktop add-on in `studio/`, in particular) — so an installed
copy had no way to know it was behind, and `claude plugin update` reported "already at the
latest" against a marketplace entry that genuinely was. Caught in person: Studio, run from an
installed copy still on 1.5.1, called `generate_status.py --json` and got a raw argparse
rejection back, because 1.5.1's copy of that script predates the `--json` flag.

- **Studio no longer shows a raw argparse dump for this.** `runPluginScript()` (the one
  chokepoint every plugin-script call goes through) now recognises argparse's own failure shape
  — a `usage:` line followed by `error: unrecognized arguments` or similar — and leads with a
  plain-language explanation that a plugin-version mismatch is the likely cause, while still
  showing the raw detail underneath for anyone who wants it.
- **This entry, and the version bump that comes with it,** is what actually fixes the reported
  symptom for anyone already on 1.5.1: nothing to install by hand, just `claude plugin update`.

## 1.5.1 — 2026-08-28

The discipline seats shipped in July as commands and agents (`/sdlc-feature`, `/sdlc-rules`,
`/sdlc-data`, `/sdlc-experience`, `/sdlc-channel`) and `/sdlc-version` in 1.3.0 — but the phase
guides a team plans a phase from never mentioned them, and the registry listed none of their
artifacts, so the gate reports and `/sdlc-coach` could not see them either. Documentation only;
no script changes.

- **Phase guides.** `phases/01-requirements.md` gains Steps 3a (`/sdlc-feature`) and 3b
  (`/sdlc-rules`); `phases/02-design.md` gains Steps 6a (`/sdlc-data`) and 7a
  (`/sdlc-experience`); `phases/build-loop.md` describes channel binding at Intent. Each step
  states its trigger, its HITL gate and that sign-offs are recorded at the advance.
- **Registry.** The nine discipline artifacts are listed as **optional** (conditional, not
  required — a feature with no customer surface has no journey to write), and each phase's exit
  gate gains two human-judged `check:` lines that ask whether the trigger applied and, if so,
  whether the artifact exists and its owner signed. No `exists_and_complete` gate is added, so no
  existing engagement is blocked.
- **Docs.** `docs/phase-lifecycle.md` carries the steps, artifacts and agents; the README lists
  the seats as a feature. Mirrors the delivery standard's new §2 "The discipline seats".

## 1.5.0 — 2026-08-11

1.4.0 taught the install, the doctor, and the PR-flow rails to follow the platform the
profile chose — but the only profile choosing Azure DevOps was still C#/.NET + Angular.
`ado-enterprise-python` is that same enterprise seat with the stack swapped: Python 3.13 /
FastAPI / SQLAlchemy 2.0 / pytest (uv-managed) + React / Redux Toolkit / Playwright, on
Azure Container Apps. No installer or pack edit — the `python`, `react`, and
`azure-devops` packs already existed and were already mapped; this is the first profile to
compose all three, and the proof the seams hold: the realized Azure Pipelines carry the uv
/ mypy / pytest / ruff commands and the 80% floor with zero axis warnings.

### The Python/React sibling of ado-enterprise

- `profiles/ado-enterprise-python/` mirrors `ado-enterprise` file-for-file: same SOC 2
  gates verbatim (they were already stack-agnostic), same conventions, same rails. The
  stack-shaped parts moved with the stack — 400-line file cap (the python pack's own
  standard, not the .NET 800), session health via the pack's offline `compileall` command,
  and the four .NET/Angular Build-loop evaluation criteria replaced by five Python/React
  ones (Pydantic-at-the-boundary and immutable-RTK-state block at `fail`; typed
  signatures, domain exceptions, and API contract docs advise at `warn`).
- `references/azure-patterns.md` re-realized for Python: `azure-identity` +
  `azure-keyvault-secrets`, App Insights via `azure-monitor-opentelemetry`, FastAPI health
  endpoint + exception handlers, SQLAlchemy 2.0 + Alembic. The skills list names only
  verified microsoft/skills `-py` entries — the two dotnet entries with no Python analogue
  were dropped, not renamed on faith.

### The database is a setup-time question, not a fork

- One profile supports both engines. It ships `azure-postgresql`; `/sdlc-setup` Step 3 now
  asks *PostgreSQL or Azure SQL?* for this profile and, on Azure SQL, edits the frozen
  `.sdlc/profile.yaml` after init (before the installer re-validates it) and rewrites the
  one `- **Database:**` line in the project's CLAUDE.md. Safe by construction: nothing
  mechanical branches on the engine — pack selection reads `backend.language` and
  `ci_cd.platform` only — and Alembic is the migration tool either way. This is the
  setup wizard's first profile-conditional prompt.

## 1.4.0 — 2026-08-10

`ado-enterprise` (1.3.0) declared the profile; nothing behind it actually ran differently
yet. `/sdlc-setup` would compose the Azure Pipelines pack, but `install_harness.py` still
laid down the GitHub-only payload underneath it, `doctor.py` still demanded `gh` on a repo
that had never heard of it, and the review-gate hook had no idea `az repos pr create` was
a PR. Five folds (0 already shipped, A–E here) close that gap end to end: install, doctor,
and the PR-flow rails now follow the platform the profile actually chose.

### The installer stops shipping GitHub files to Azure DevOps repos

- `_copy_core` in `install_harness.py` now reads `stack.ci_cd.platform` and, on
  `azure-devops`, drops the GitHub-only payload (`workflows/`, rulesets, `CODEOWNERS`,
  `apply-branch-protection.sh`) and redirects the neutral governance content — rubrics,
  `eval-bypasses.md`, `dependency-exceptions.md` — to `.azuredevops/rails/`, which is
  where the ADO pipelines actually read them. This fixes a live bug: `<<RUBRIC_DIR>>` was
  pointing at a path nothing had created.
- `rails-telemetry.schema.json` deliberately stays at `.github/` on both platforms — both
  packs' telemetry pipelines commit their report to `.github/rails-telemetry.json` on
  purpose, so a fleet collector watching a mixed GitHub/Azure fleet has one canonical path
  to read.
- GitHub-Actions and core-only installs are unaffected — the identity layout is
  byte-for-byte unchanged, pinned by the untouched `enterprise-tree.txt` golden.

### `doctor.py` follows the pack it was installed with

- `installed_platform()` reads the composed pack ids out of the install manifest, and the
  platform-facing checks follow it: Azure DevOps installs are checked with `az` (+ the
  `azure-devops` extension) and are never told to install `gh` for a platform they don't
  use — the tools check, the repo-secrets check (now `required_variable_groups()`,
  reading `- group: NAME` references straight out of the installed pipelines), and the
  branch-protection check (`az repos policy list`, enforcing = `isEnabled AND isBlocking`)
  all branch on it. `.azuredevops/` joined the residual-token scan roots, so a stray
  `<<GATED_PATHS>>` in `security.yml` no longer goes unseen.
- GitHub and core-only installs get the same checks as before — the `gh` bodies are
  renamed, not rewritten.

### PR-flow rails reach Azure DevOps

- `review-gate.sh` / `review-gate.ps1` now gate `az repos pr create` the same way they
  gate `git push` / `gh pr create`, segment-anchored so a mention inside a quoted string
  still walks free. Hardening this payload also closed two bypasses in the GitHub twins:
  a leading `VAR=value` prefix (`AZURE_DEVOPS_EXT_PAT=... az repos pr create` is a
  documented `az` auth pattern, and `FOO=1 git push` was its GitHub sibling) no longer
  hides the trigger, and the PowerShell twin now splits on newlines the way the shell
  version always did, so a multi-line command with the trigger on a later line can't walk
  past it on Windows.
- The Azure DevOps pack ships its own settings fragment: read-only `az repos pr show`
  allowed (`az` has no `pr view` — the GitHub-shaped assumption was caught by adversarial
  review before it shipped), mutating `az` and `configure-branch-policies.sh` behind
  `ask`, `.azuredevops/**` gated exactly like `.github/**`. GitHub installs get none of
  it.
- `pr-writer` names both platforms now, including the verified `--labels risk:high` flag
  for `az repos pr create`.

### Keyless Foundry auth for the ADO LLM gates (opt-in)

- The three Claude gates (grader, correctness, security) can authenticate with a per-run
  Entra token minted from a WIF service connection instead of a stored
  `ANTHROPIC_API_KEY`. It's opt-in per pipeline via four compile-time `FOUNDRY_*`
  variables — leave them empty and the emitted steps and `run-claude-review.sh`'s
  behavior are byte-identical to today.
- `run-claude-review.sh` fails **closed** with an actionable message on a missing
  resource or an unresolved model alias (Foundry has no alias resolution, proven by a
  live spike against a sandbox deployment), and scrubs any unresolved ADO `$(macro)`
  literal so a foundry-less pipeline can never leak one into the CLI environment.
- `doctor.py` needed no change for this: it reads what the pipelines reference, so a
  variable group nobody wired stops being demanded, by construction.
- Live-drilled, not just unit-tested: the review-gate ran against a real ADO repo
  (`az repos pr create` denied without a receipt, allowed with one), and the Foundry
  chain authenticated end-to-end against a sandbox deployment.

### Fixed: a Windows clone would have installed broken hooks

`review-gate.sh` checked out with CRLF under `autocrlf` on the Windows CI leg — bash
rejects `set -uo pipefail\r` and exits 1 before the hook body runs, so every `sh`
trigger test failed before it could assert anything. This wasn't a test-only problem:
the same checkout happens on a real Windows clone of this plugin, which would have
installed hooks and rails scripts that never ran. `.gitattributes` now pins `*.sh` to
LF everywhere; `.ps1` stays platform-default (pwsh tolerates CRLF).

### The rails

899 passed. Verified additively at every step: install+upgrade agree byte-for-byte on
the merged settings, the GitHub golden tree stays untouched, and upgrading an existing
GitHub or core-only install changes nothing except the review-gate bypass hardening
above (which applies everywhere, GitHub included).

## 1.3.0 — 2026-08-07

An artifact could always be changed. Nothing recorded that it had been, or noticed what the change
put at risk. This connects two facts the tool already held — *when* each artifact changed (SHA-256)
and *what depends on what* (declared traceability) — so staleness falls out of them for free.

### Changing a pre-Build artifact, and auditing the trail

- `/sdlc-revise` — change one artifact by id or section, record why (optionally against a `DL-NN`
  decision), re-gate, and see what downstream may now be stale.
- `/sdlc-audit-artifacts` — the read-only sibling of `/sdlc-audit`: a freshness dashboard, plus
  `--impact` (what a change here would put at risk) and `--history` (an artifact's change trail).
  Commands 21 → 23.
- `artifact_lineage.py` harvests `upstream → downstream` edges, cycle-safe. `audit_artifacts.py` is
  the engine; its ledger is a standalone JSONL (`.sdlc/metrics/artifact-log.jsonl`), never inside
  `gate_results` — that dict is expanded into phantom rows by `audit_gates.extract_gate_history`,
  and `/sdlc-audit` output is byte-identical with or without this layer.
- **Advisory throughout.** Staleness is a candidate a human dispositions, never a gate.

**Honest counting, same rule as findings.** `artifact_model.py` owns the disposition state machine:
`ACKNOWLEDGED` is off the books only with an owner, `NOT_AFFECTED` only with a reason, and
`REFRESHED` is **derived from the ledger, never a word anyone types** — a downstream that changed
after its upstream simply stops being stale. A typed `REFRESHED` is exactly the relabelling the
machine exists to reject, so it is rejected and still counts as debt.

### The freshness dashboard died on a Windows console

The advisory surface promises exit 0 always, and broke that promise on the happy path. The
dashboard printed two glyphs a default Windows console (cp1252) cannot encode — an arrow on every
stale line, a check on every signed-off phase. Printing either raises `UnicodeEncodeError` and kills
the process with exit 1. The tool worked right up until it had something to report, then crashed
instead of reporting it. Both now degrade to ASCII when, and only when, the console cannot encode
them; a UTF-8 terminal is unchanged.

**Why the suite could not catch it:** pytest captures as UTF-8 and CI is Linux, so both instruments
are blind to this by construction. `TestNarrowConsoleEncoding` binds stdout to a real cp1252 stream
— the first check in the suite that reproduces what a Windows user actually sees — and one case
pins the UTF-8 rendering so the fallback cannot quietly become everyone's default.

### Known limit, stated rather than discovered later

On a corpus that declares little, the **coarse** phase-order fallback dominates: a representative
ten-artifact project harvested 2 declared edges and 18 coarse ones. Coarse edges are always labeled
as inferences and only ever added where an artifact declares no upstream at all, but "you changed a
requirement, so every design document may be stale" is a tautology, not information. The dashboard
is most useful where traceability is actually declared.

### The rails

- 65 new checks across `artifact_model`, `artifact_lineage`, and `audit_artifacts`, plus the three
  narrow-console cases above. 658 passed, 7 skipped.
- `docs/commands.md` said "Ten commands" above a twelve-row table. Caught by
  `test_registry_docs_consistency` only *after* the merge — the PR branch predated that check, so
  the branch was green and only the merge result was red.

## 1.2.0 — 2026-08-03

Finishes what 1.0.0 started. Fix 3 was written because "the approver was shown a file list and
asked to sign" — it fixed that in the terminal and left the report alone. The report is the thing
the approver actually opens.

### The phase report now carries the judgement calls

- `<slug>-report.html` renders the registry's prose exit conditions in a **Before you sign**
  section, above the artifacts rather than below ten of them. Unticked, because nothing in the
  pipeline can know the answers — only the signer can.
- The sidebar's Exit Gate Status gains an **N decisions for a human** row, so a page whose file
  checks are all green can no longer read as "everything passed" while four questions are open.
- `generate_report()` returns `exit_criteria` alongside `found`/`missing`.

**Why it mattered:** `check_gates.py` has surfaced these as G7 REVIEW items since 1.0.0, but
`build_gate_items()` was built from the artifact list alone. A Phase 0 with every required file
present and complete produced a report showing five green ticks and no indication that scope
boundaries, metric sources, and persona provenance were still nobody's confirmed answer. The
terminal told the truth; the artifact of record did not.

### The rails that catch the next one

- `scripts/tests/test_phase_report_exit_criteria.py` — sixteen checks. The registry reader excludes
  machine-checked artifact conditions, every criterion reaches the page, criteria are escaped, the
  section precedes the artifacts, and the report's list is pinned equal to what `check_gates.py`
  renders in the terminal so the two readers of that registry field cannot drift apart.
- All six mutations proven to fail, starting with the real defect. 598 passed, 6 skipped.

## 1.1.0 — 2026-08-01

Regenerated `harness/` from the canonical kit. Three additions to the delivery standard: the
second half of the deploy rail, the standard's first position on third-party components, and
fleet-level visibility of gate outcomes.

**Nothing changes in an installed repo until you upgrade it and re-apply branch protection.**
That is why this is a minor version rather than a major one — but read the migration note, because
one of the additions is a new blocking gate.

### Deploy promotion and rollback

- `deploy-promote.yml` (both CI/CD packs) — dev→test→prod, manual trigger only. The go/no-go is
  the target environment's own approval mechanism (GitHub required reviewers / Azure DevOps
  environment checks), and the workflow **refuses to run** against an environment that has none.
  It also refuses to promote a build the source environment has never run, so nobody can skip test.
- `ROLLBACK.md`, `ALERTS.md`, `INCIDENT-PLAYBOOK.md` — the Phase 8/9 skeletons, installed at their
  final names to be filled in.
- **Fixes drift:** both pack copies of `deploy-dev.yml` still hard-failed every merge; only the
  core file had received the `DEPLOY_WIRED` guard. The pack copies are what clients install.

### A position on third-party components

- `dependency-gate` (a job in `ci.yml`) — **a new blocking gate.** Diff-scoped: it compares this
  branch against the target branch and blocks only on a vulnerable package the change *introduces*.
  A CVE published overnight against untouched code will not redden open PRs.
- `dependency-scan.yml` — weekly, reports the standing stock as an issue/work item, never blocks.
- `dependabot.yml` (github pack) — upgrade PRs that ride the full merge bar; nothing auto-merges.
- Override is `accepted-risk:dependency`, with `dependency-exceptions.md` as its ledger.

### Fleet visibility

- `rails-telemetry.yml` — weekly, commits `.github/rails-telemetry.json`: what ran, every override
  by name, and which checks branch protection **actually requires** against which gate jobs exist.
  That last comparison is the point: a gate that has been unrequired still runs, still reports, and
  blocks nothing, and no amount of counting tells you which one you have.
- `rails-telemetry.schema.json` — fixed at version 1 now, before the install wave, so it is not
  retrofitted across live repos.
- No external calls: it reads the repo's own history through the platform's API and writes into the
  same repo. Counts are per gate, never per author.

### The rail that catches the next release mistake

`scripts/tests/test_release_manifest_agreement.py` asserts that `.claude-plugin/plugin.json` and
`.claude-plugin/marketplace.json` agree on version and on plugin name, that the version is semver,
and that it is the newest release heading in this file.

It exists because this release nearly shipped wrong. `RELEASING.md` step 3 has always said to bump
both manifests — "they must match" — but only `plugin.json` was bumped, so merging after the 1.0.1
stack let git **auto-merge** `marketplace.json` back to 1.0.1. No conflict, no marker, no failing
test: a valid JSON file holding the wrong number. The two values have different readers —
`plugin.json` is stamped into every installed repo's manifest and is what `/sdlc-upgrade` compares
against, while `marketplace.json` is what decides an update is on offer — so the lagging one would
have published a release nobody was told about.

Verified the same way as the 1.0.1 rails: every check proven by reintroducing the defect it targets
and confirming it fails.

### Migration

1. `/sdlc-upgrade` — new files install; anything you adapted is left alone.
2. **Re-apply branch protection.** `dependency-gate` is a new required status check. Until you
   re-apply, it runs and reports but does not block; after you re-apply, a PR introducing a
   High/Critical advisory will be stopped.
3. Configure **required reviewers** on `test` and `prod` environments before using
   `deploy-promote` — it fails closed without them, deliberately.
4. Run the new shakedown drills in `RAILS.md`. The dependency gate especially: unlike every other
   rail it fails *silent and green* when misconfigured, so planting a known-vulnerable package is
   the only way to know it is wired.
## 1.0.1 — 2026-08-01

**A patch release, and entirely corrective.** 1.0.0 changed what the gates enforce and left the
prose describing the old behaviour; everything here reconciles the two. Eight issues (#29–#36)
turned out to be four root causes.

**Nothing here makes a gate stricter.** One requirement is *removed* — Phase 1 no longer blocks on
`decision-list.md`, a file nothing ever produced, so no passing gate regresses. The receipts that
already blocked (`threat-model.md`, `drill-record.md`, `go-no-go-record.md`) still block; the
difference is that the plugin now tells you what to write and ships a template.

> **Ordering:** this releases from 1.0.0 and must land **before** the 1.1.0 kit sync, which is
> based on the same 1.0.0 tree.

### The 1.0.0 receipt migration is now actually wired (#31, #33, #34, #35)

1.0.0 added twelve required receipts to `phases/phase-registry.yaml` and updated almost none of the
prose around them. `check_gates.py` blocks on `artifacts.required` and nothing else, so the registry
was the only thing telling the truth — and it was telling it to nobody. Four separately-reported
issues turned out to be one unfinished migration.

**Two receipts were required by the gate and described nowhere.** A team hit them as a blocked phase
with no instruction anywhere for what the file should contain:

- `drill-record.md` — Phase 9 now has a **Step 4: Alert Drill** (the playbook is written first, so
  the drill tests `incident-response.md` as much as it tests the alert), an artifact spec, and a
  template. Steps 4–6 renumbered to 5–7.
- `go-no-go-record.md` — the Step 0 ceremony already existed and is the most consequential HITL
  gate in the lifecycle; only its receipt was missing. Added a spec, a template, and a line in
  Step 0 to record the decision *as it happens*. Silence is not agreement: a role that was not
  polled is recorded as not polled.

**`docs/phase-lifecycle.md` was missing eleven of the twelve** from its Required Artifacts tables,
and listed `go-no-go-record.md` and `drill-record.md` as *optional* — the direct contradiction that
makes a team skip an artifact and then fail the gate on it. All corrected.

**`threat-model.md` was documented `RECOMMENDED — required for any system handling auth, payments
or PII`** while the registry blocked on it unconditionally. The registry is right and the promotion
was deliberate: the phase body's own note asked for it to be promoted "on a major version with a
migration note", which is exactly what 1.0.0 was. The prose now says REQUIRED, with the `WAIVED:`
escape spelled out. Every system has guarded paths — deploy credentials and CI secrets at minimum —
and Phase 3 has nothing to wire its security gates from without the map.

**`decision-list.md` is gone; the work it named was already done by two shipped mechanisms.** The
phase-spanning `.sdlc/decision-log.md` (`DL-NN`, read by `track_decisions.py`, surfaced by
`/sdlc-status`) and a spec's own `## Decision List` section (enforced per-spec by `check_spec.py` at
Definition of Ready) already cover it, and three places in the repo warn against confusing the two.
A third file would have been the confusion. Dropped from `artifacts.required`; the Phase 1 spec now
points at the decision log; and because that log lives outside the phase's artifact directory where
the gate cannot see it, the exit gate gains a prose check so the approver is still asked — the same
pattern the `close` phase already uses for its off-gate receipts.

**A runaway code fence in `phases/01-requirements.md`** swallowed 59 lines, turning three artifact
specifications and a section heading into sample code. This was the migration's insertion landing
inside an existing fence. The fence now wraps only the `AQ-NN` example it was meant to.

### Report filenames use one convention (#36)

Three were in use simultaneously: the phase bodies wrote `phase09-report.html`, the registry's
optional lists said `phase9-report.html`, and `docs/commands.md` documented `<slug>-report.html`.
`03-foundation.md` alone used both the padded and unpadded forms.

Two things were actually broken by it, not merely untidy. `commands/sdlc-gate.md` pre-checks the
**visual** report by slug, so a team following the phase definition wrote `phase09-visual.html`
while the gate looked for `09-monitoring-visual.html` and reported it missing. And the registry's
`artifacts.optional` entries could never match a real file under either of the other conventions,
so those entries were dead.

All 38 references now use `<slug>-report.html` / `<slug>-visual.html`. The slug wins because it is
what `generate_phase_report.py` is invoked with, and the only form that survives the non-numeric
`build` and `close` phases.

### `/sdlc-spike` and `/sdlc-doctor` are documented (#32)

Both shipped and appeared nowhere in `docs/commands.md` — not the contents, the overview table, or
the additional-commands table. Spikes are a first-class part of the method with their own Phase 2
step, and `/sdlc-doctor` is the single most useful command for a first-time setup (it catches the
missing interpreter, the rails script without its executable bit, the unset secret — each of which
otherwise fails silently). A reader working from the reference would conclude neither existed.

Both added, and the stale "Eight commands" count corrected to ten.

### Gate 2 catches less than the docs claimed (#30)

`docs/templates-artifacts.md` stated that Gate 2 fails on "any remaining `[bracket text]`, `TODO`,
or `TBD`". It does not. The real set is exactly six strings — `TODO`, `TBD`, `${`, `PLACEHOLDER`,
`[INSERT`, `<!-- REQUIRED:` — and **bare bracket prose is not among them**, deliberately: templates
use `- [ ]` checkboxes and `[text](links)` throughout, so a general bracket rule would fail nearly
every artifact.

The consequence is that `[Describe the situation]` left in an ADR passes completeness. Overstating
what a gate checks is worse than understating it — it turns a tripwire into a proofreader in the
reader's head, and then the proofreading stops being done. All three docs that list the markers now
state the real set and name the gap.

The same docs described `<!-- REQUIRED: ... -->` as "not a placeholder to fill, but a validation
hint", which reads as *leave it in place* — while its presence is exactly what fails the artifact.
It is a template-enforcement marker: **delete it once you have written the section it names.** That
deletion is the completeness contract, and nothing had ever said so.

### Thirteen agents that never existed (#29)

Phases 7, 8 and 9 instructed Claude to spawn seven subagents by name. **Six did not exist.** The
reference documents were worse: `references/agent-roster.md` — which calls itself "the
authoritative reference for agent orchestration decisions" — and `docs/agents.md` between them
presented **thirteen** non-existent agents as usable, six of those in the Build-loop table, the
most-exercised part of the product. `SKILL.md`, the file Claude actually reads, carried the same
list plus a worked `Agent(backend-architect, ...)` example.

**A spawn that resolves to nothing does not raise and does not warn.** The phase carries on as
though the work were done. A team ran Phase 7, the definition said the API documentation was being
generated, and `api-docs.md` never appeared.

The root cause was a single false claim: `docs/agents.md` listed these under **"Built-in Claude
Code subagents — Claude Code runtime — 13+"**. They were never runtime built-ins. Believing they
came free is why nobody built them. Only `Explore` and `Plan` come from the runtime; everything
else ships in `agents/` (13) or `harness/agents/` (6).

**The fix follows what already worked.** Phases 0–3 and the Build loop spawn nothing via
`Agent(...)` and never did — they describe their work as steps. Phases 7–9 now do the same:

| Was delegated to a non-existent agent | Now |
|---|---|
| README + API docs (`doc-updater`, `backend-architect`) | Written directly — `07-documentation.md` Steps 1–2 |
| Staging/production deploy (`devops-automator`) | Executed directly from `RUNBOOK.md` — `08-deployment.md` Steps 2, 4 |
| Smoke tests (`e2e-runner`) | Executed directly — `08-deployment.md` Step 3 |
| Performance baseline (`performance-benchmarker`) | Measured directly, before any threshold is set — `09-monitoring.md` Step 1 |
| Feedback synthesis (`feedback-synthesizer`) | Part of the retrospective — `09-monitoring.md` Step 5 |
| Tests, API work, spikes (`test-writer-fixer`, `api-tester`, `rapid-prototyper`, `tdd-guide`) | The `test-writer` / `api-pattern` skills and `/sdlc-spike` |

`build-error-resolver` spawns are kept — it genuinely ships. The distinction now stated in the docs
is that a **skill** runs in the main context with the surrounding work in view, which is what
authoring needs, while an **agent** starts cold, which is what reviewing needs. That, not a persona
name, is what decides whether something should be delegated.

`docs/phase-lifecycle.md` had said "No custom SDLC agents are spawned during Documentation /
Deployment / Monitoring" the whole time. It was right, and nothing reconciled it against the phase
files that disagreed.

### The rails that catch the next one

`scripts/tests/test_registry_docs_consistency.py` asserts that:

- every registry-required artifact has a `### <name>` spec in its phase definition, appears in
  `docs/phase-lifecycle.md`'s Required Artifacts table, and is not simultaneously listed as optional
- report filenames use the registry slug, never `phase9-` or `phase09-`
- every shipped command appears in `docs/commands.md`, and the additional-commands count matches
  its own table
- all three docs that list Gate 2's placeholder markers match `check_gates.PLACEHOLDER_MARKERS`,
  with the specific `[bracket text]` false claim kept as a named regression

`scripts/tests/test_agent_references.py` asserts that every agent named in an `Agent(...)` spawn or
an agent-table column — across `phases/`, `SKILL.md`, all of `docs/` and all of `references/` —
ships in `agents/` or `harness/agents/`, or appears on an explicit allowlist of Claude Code
built-ins and sibling-plugin agents. It parses the tables rather than pattern-matching backticks,
so phase slugs and spec statuses are not mistaken for agent names. Its file list is derived by glob:
the first pass at this fix corrected two documents by hand and left the same claims standing in
three others, which is exactly how the original drift happened.

Every check was verified by reintroducing the original defect and confirming it fails — a guard
that has never failed is a configuration, not a control.

## 1.0.0 — 2026-07-31

**Breaking. Gates that previously passed will now block.** Read the migration note before upgrading
an engagement that is mid-flight.

### Human work now leaves a receipt (Fix 3)

Of the 110 artifacts across the standard's ten worked-example ledgers, 65 were machine artifacts,
**3** were human receipts — all in Phase C — and **42** were human work that left no trace at all.
The threat review. Every spike. The cold README checkout. The rollback rehearsal. The alert drill.
The go/no-go. Each one load-bearing, each one unauditable a year later.

They were triaged rather than mechanically converted, because "add an artifact for each of the 42"
would have been wrong for 24 of them and the standard warns against exactly that kind of scaffolding
growth. See `FIX-3-TRIAGE.md` in the delivery-standard repo for the full reasoning.

**Twelve required receipts** — the phase now blocks without them:

| Phase | Receipt |
|---|---|
| 1 | `decision-list.md` |
| 2 | `spike-findings.md`, `threat-model.md`, `nfr-proving-plan.md`, `walking-skeleton-definition.md` |
| 3 | `data-flow-brief.md` |
| 7 | `readme-verification.md`, `runbook-walkthrough.md` (service/app only) |
| 8 | `rollback-rehearsal.md`, `go-no-go-record.md`, `secrets-rotation-record.md` |
| 9 | `drill-record.md` |

Four of these already existed as optional entries (`go-no-go-record.md`, `drill-record.md`) or had a
spec but no registry entry (`threat-model.md`); the rest are new.

**Eleven optional receipts**, recorded when the work happens and surfaced to the approver at
sign-off rather than blocking: `po-decision-record.md`, `tooling-record.md`, `workshop-brief.md`,
`scope-out-record.md`, `adversarial-review-record.md`, `consistency-check-record.md`,
`spec-audit-record.md`, `rollout-shape-decision.md`, `what-healthy-table.md`,
`fatigue-review-record.md`, `outcome-metric-first-read.md`.

**Six items got no artifact deliberately** — branch protection, the deployed skeleton, the security
gates having fired, the outcome metric ticking, the per-merge metrics line and the provenance log.
These are states of the world, not documents. A markdown file asserting "branch protection is on" is
weaker than reading the setting, and goes stale silently. `/sdlc-doctor` already checks one of them;
two others are fleet observability, tracked separately.

**Six more got none** because they are already inside a parent artifact the gate checks (error
specs, the traceability matrix, user stories, the data model), or because the receipt would be
ceremony: the non-author approval is recorded by GitHub and enforced by branch protection, and a
"the grader was read" receipt records a claim rather than a fact.

### Waivers, in the artifact and never silent

Some of this work genuinely will not happen — there is no live carrier sandbox to spike against, no
client ops engineer to walk the RUNBOOK. A gate with no escape gets worked around, and the
workaround leaves no trace, so the escape is built in and made loud.

A required receipt may carry `WAIVED: <name> — <reason>`. The gate accepts it and reports it, **by
name**, in the record the approver signs against. Both halves are required: a waiver naming nobody
is the thing being prevented. A *missing* file still blocks — the escape is from the work, not from
the record.

### `risk-signoff` — the HIGH-risk sign-off is now enforced

The standard has always required a named human to accept the risk on a `risk:high` change — "a
person, by name. Not a thumbs-up." It was convention in a PR comment that nothing templated and
nothing checked.

A new required status check fails any `risk:high` PR with no line of the form
`SIGNED-OFF-BY: <name> — <sentence>` in the body or a comment. The sentence is required; a bare name
does not satisfy it. It is a check rather than a committed receipt because a file under `.sdlc/`
would describe a merge that already happened, and the acceptance has to exist before the merge.

Added to `branch-protection.json`'s required contexts. Existing repos must re-apply the ruleset
(`scripts/rails/apply-branch-protection.sh`) or the check will run without being required.

---

## Migration — engagements already in flight

**The failure is loud and local.** On the next `/sdlc-gate` the phase reports each missing receipt by
name, with the artifact spec in the phase body describing what it must contain. Nothing silently
changes behaviour; nothing is deleted.

**You have three honest options per receipt:**

1. **Write it** — if the work happened, record it now while people still remember. This is the case
   for most of them, and the reason the receipts exist.
2. **Waive it** — if the work genuinely did not happen, create the file with
   `WAIVED: <name> — <reason>`. The gate accepts it and the record says who decided and why.
3. **Do the work** — if it did not happen and should have, the gate has just told you something
   worth knowing. That is the point.

**What we do not recommend:** reverting to 0.10.0 to clear the gate. A phase that closed without a
threat model closed without a threat model; the previous version simply did not ask.

**Re-apply branch protection** so `risk-signoff` becomes required rather than merely present.

**Phase 7 is project-type aware.** `runbook-walkthrough.md` is required only for `service` and `app`
projects — a library, CLI or skill has no RUNBOOK to walk, and the gate now agrees with the phase
body about that.

---

## 0.10.0 — 2026-07-16

- **Every stale CI pin bumped, none blind.** `setup-dotnet` v4→**v6**, `checkout` v4→**v7**,
  `upload-artifact` v4→**v7**, `download-artifact` v4→**v8** (38 pins). `setup-node@v7` and
  `setup-python@v6` were already current. The filed issue named only setup-dotnet; the others were
  found by inventorying the whole surface and were *three and four* majors behind.
- **`NodeTool@0` is deprecated and was silently wrong.** The ADO pack mapped `node` to it; Learn says
  verbatim "This version of the task is deprecated; use `UseNode@1`". The migration renames the
  input — `versionSpec` → `version` — so bumping the task without the input would emit a broken
  pipeline. This is exactly the non-uniformity the `toolchain_map` exists to absorb: the fix is two
  values in one file, and the node stack pack never learned a thing. (`UseDotNet@2` and
  `UsePythonVersion@0` are confirmed current — no `@3`/`@1` successor exists for either.)
- **Runner floor:** the node24 line (setup-dotnet v5+, checkout v5+, upload-artifact v6+) requires
  **Actions Runner ≥ v2.327.1**. GitHub-hosted is well past it; a stale self-hosted runner fails all
  of them together. That is the one precondition this release carries.
- **Recorded because no release note says it:** setup-dotnet v5 dropped `signed` and `validated`
  from `dotnet-quality`, and passing them now *throws*. Visible only by diffing `src/setup-dotnet.ts`.
  The kit doesn't use the input; a client repo might.
- **Client-repo warning, documented in the pack:** setup-dotnet ≥ v5.4.0 validates `global.json`
  strictly, so `"version": "10.0.*"` now hard-errors (upstream #753, open). The wildcard was never
  supported per Microsoft's docs — the action was lax since 2022. This kit ships no `global.json`,
  but a client repo with a wildcard one fails at Setup toolchain.
- Verified as **not** applicable rather than assumed: checkout v7's new fork-PR block (its source
  returns early unless `workflow_run.event` starts with `pull_request` *and* the head repo is a fork;
  the deploy job is gated to `main` and checks out no fork ref), and download-artifact v5's path
  change (scoped to downloads *by ID*; deploy-dev downloads by name).
- The flagship golden test now pins `setup-dotnet@v6` / `dotnet-version: '10.x'`. It had **no**
  version assertion, which is why the pin rotted unnoticed — the Node profile had one and stayed
  current. A test cannot detect upstream staleness; that stays a periodic human check.

## 0.9.0 — 2026-07-16

- **The eval-gate seam is finished; the last .NET leak is closed.** The optional eval-gate job bound
  only its `--filter` to the stack and hardcoded `dotnet test` around it, so every stack — Node,
  Python — was shipped a .NET invocation. Binding the filter alone was the design error: a filter
  value is meaningless without the runner flag that consumes it, and that flag's syntax is
  runner-specific (`--filter "Category=X"` / `-t "@x"` / `-m "x"`). `<<CI_EVAL_TEST_FILTER>>` is
  replaced by `<<CI_EVAL_CMD>>`, filled from a whole `ci-profile.eval_gate.command`. The seam
  vocabulary is still nine tokens. A Node repo's pipeline now contains no `dotnet` anywhere, which
  the golden test asserts over the whole file rather than just the blocking job.
- **The .NET eval gate was fake, on every SDK, and now fails closed.** `dotnet test --filter`
  matching ZERO tests exits **0** — "No test matches the given testcase filter" is a *warning*, and
  the trx is still written with `total="0"` and `outcome="Completed"`. Verified empirically on SDK
  8.0.129, 9.0.316 and 10.0.301. So the flagship profile's gate would have gone green having run
  nothing, and its trx artifact would have looked like a clean pass. The command now ends with
  `-- RunConfiguration.TreatNoTestsAsError=true`, verified on all three SDKs in all three states:
  zero-match → 1, matching filter → 0, failing fixture → 1. (`/p:FailIfNoTestsFound` and
  `/FailWhenNoTestsFound` do not exist — they appear in no shipped SDK. Microsoft.Testing.Platform
  fails closed natively with exit 8; classic VSTest `dotnet test` does not.)
- **Recorded, because it is a silent-green trap:** `Category=` is xUnit's trait key. MSTest and NUnit
  spell it `TestCategory=`, and on MSTest a `Category=` filter matches zero tests *even when every
  fixture is correctly tagged* — which, before the setting above, was exit 0.
- **The Node eval gate would have been fake, and now fails closed.** `vitest run -t` matching ZERO
  tests exits **0** (verified on vitest 3.2.7 and 4.1.10) — so a renamed or typo'd tag would have
  passed the gate green having run nothing. The declared command carries a guard. The obvious guards
  don't work and were each verified not to: `--passWithNoTests=false` covers a different condition
  (no test *files*), the JSON's `success` is `true` on a zero-match run, and `numTotalTests` counts
  *collected*, not matched. Only `numPassedTests + numFailedTests` discriminates. Prior to this the
  Node pack's own comment recommended the unguarded command as the adaptation path.
- **The Python eval gate is real without a guard**, for a reason worth recording: pytest counts
  `testscollected` *after* deselection, so a marker matching nothing is "no tests collected" and
  exits 5. `--strict-markers` is kept but does **not** protect the `-m` expression — it catches a
  marker typo'd on a *test*, the mirror-image hole.
- `eval_gate.command` is covered by the single-line rule and fails the install closed when absent —
  a rule that held for four commands but not the fifth was a gap, not a policy.
- The eval results contract is now a plain `eval-results/` directory (the ADO pack no longer
  publishes from `$(Agent.TempDirectory)`): a platform variable inside a stack-declared command would
  leak ADO's vocabulary into the stack layer, which is the coupling the seam exists to break.

## 0.8.0 — 2026-07-16

- **Angular frontend pack.** The flagship microsoft-enterprise profile declares `angular-17`, which
  until now degraded to the framework-agnostic UX reviewer plus a warning. It now composes an
  Angular-aware `ux-reviewer` over the generic one — checks for the states the async pipe swallows,
  `OnPush` subtrees that never repaint after an in-place mutation, NG0100 (dev-only, so it goes
  silent rather than away in production), resolver-blocked navigation, `[disabled]` vs `disable()`,
  subscription teardown, and focus management on navigation. Version-gated: the reviewer reads
  `@angular/core` from `package.json` before citing syntax, because a v17 repo should not be
  reviewed against v20 features.
- **`angularjs` is explicitly unsupported** rather than merely unlisted — AngularJS 1.x is a
  different framework, and it degrades with a warning instead of quietly pulling the Angular pack
  (the same distinction that keeps `react-native` off the React web pack).
- **Every axis the flagship profile declares now has a pack**: a warning-free install is now pinned
  by a test, so any future axis that silently degrades fails the suite.

## 0.7.0 — 2026-07-16

- **Two new stack packs: `node-typescript` and `python`.** Every shipped profile now composes a
  realized stack instead of degrading to the neutral core: starter (typescript/node) and
  creative-tooling (python/uv) join microsoft-enterprise (csharp). Each pack brings its stack
  standards (spliced into `CLAUDE.md`), deep rules, an `api-pattern` skill, tooling permissions
  merged into `settings.json`, and a `ci-profile.yaml` — so its pipeline is realized through the
  mechanical seam rather than hand-adapted. Both are authored, not harvested; each README says so.
- **starter and creative-tooling now declare `ci_cd.platform: github-actions`.** Without it the
  CI/CD axis degraded and those repos kept the core's placeholder pipelines — which carry .NET
  reference commands. The core installs the same workflow files either way; declaring the platform
  replaces placeholders with realized ones.
- **The customer profile's `quality.coverage_minimum` now sets the CI coverage floor**, overriding
  the stack pack's declared default (the profile is the later, more specific layer). starter states
  60; its gate now enforces 60, where the pack's default would have imposed 80.
- The coverage gate accepts any cobertura report under `coverage/` (`coverage.cobertura.xml`,
  `cobertura-coverage.xml`, `coverage.xml`) — report names differ per stack and none is wrong, so
  the platform adapts instead of each stack renaming its output.

## 0.6.0 — 2026-07-16

- **The stack↔CI/CD seam is now mechanical.** It was documentation-only: the CI/CD packs hardcoded
  .NET commands with comments naming where a human had copied them from `ci-profile.yaml`, a file
  the installer never read and that never reached a repo. Composing a non-.NET stack with either
  CI/CD pack would have installed a .NET pipeline. The packs' workflows now carry a closed
  vocabulary of nine `<<CI_*>>` seam tokens which the installer fills at compose time from the
  resolved stack pack's `ci-profile.yaml` (commands, toolchain version, coverage floor) and the
  CI/CD pack's own `toolchain_map` (platform knowledge: which setup action installs a toolchain and
  what its version input is called). Adding a stack is now one `ci-profile.yaml`, not a per-stack
  copy of every pipeline.
- Fail-closed: an unmapped `toolchain.id`, a missing ci-profile value, a multi-line command, or a
  residual seam token in an installed file each fail the install with a clean error — a literal
  token can never reach a client repo. Phase-3 repo blanks (`{{SOLUTION_OR_PROJECT}}`,
  `<<CI_WORKFLOW_NAME>>`, …) pass through untouched.
- Degrade-independent: a CI/CD pack composed without a stack pack keeps its seam tokens and prints a
  warning naming the files to hand-adapt, rather than failing.
- Azure DevOps templates generalized: `use-dotnet.yml` → `setup-toolchain.yml`,
  `dotnet-restore-build-test.yml` → `restore-build-test.yml`.

## 0.5.0 — 2026-07-16

- **spec-gate** (harness): a deterministic blocking check — a pull request that changes source
  without a committed `specs/NNNN-*.md` in the diff is refused. "No spec, no build" was previously
  a grader warning; it is now mechanical. Recorded escape: the `no-spec:chore` label plus a reason
  in the PR description. Added to the required-status-check set on both CI platforms (the merge bar
  is now five blocking checks).
- **Coverage floor enforced** (harness): the GitHub CI rail gained the cobertura-parsing floor step
  the Azure DevOps pack already had — a sub-threshold run now exits non-zero instead of uploading a
  low number to a report nobody reads. Fails closed when no coverage report is produced.
- **Stop hook runs tests by default**: `RAILS_STOP_RUN_TESTS=0` opts out (was opt-in). The AI can no
  longer end a turn on red tests in a default install.
- Shakedown drills added for both new gates in the core and both CI/CD packs.

## 0.4.0 — 2026-07-16

- Install manifest: `install_harness.py` writes `.claude/harness-manifest.json` — plugin version,
  composed packs, and a sha256 of every file *as installed* (the pristine baseline that makes
  adaptation detectable later).
- `/sdlc-upgrade` + `scripts/upgrade_harness.py`: safe upgrades for installed harnesses. Files
  still factory-original are replaced with the new version; repo-adapted files are left alone;
  files changed on both sides are written beside the original as `<file>.harness-new` for a
  deliberate merge. Dry-run by default; `--apply` to execute. Legacy installs (no manifest) are
  adopted on first apply.

## 0.3.0 — 2026-07-16

- Profile-aware pack composition: the harness installer composes packs along four axes — stack
  (`stack.backend.language`), CI/CD (`stack.ci_cd.platform`), frontend (`stack.frontend`), and
  tools (`tools: [...]`) — on top of the neutral core; each axis degrades independently with a
  WARNING when no pack exists.
- Team `.mcp.json` composition: the installer writes the team's shared MCP server set at the repo
  root (core servers plus pack additions), re-merged on every run.
- CLAUDE.md splice data-loss fix: installing the harness no longer loses locally edited content in
  the governance `CLAUDE.md` sections it manages.
- Commands reference plugin files via `${CLAUDE_PLUGIN_ROOT}` instead of hardcoded install paths.
- Secret-scan gate added to the harness payload.
- Stop-gate hook fixed to the exit-0 + JSON block contract, so the block reason reaches Claude.

## 0.2.0

- SDLC lifecycle + initial harness payload.
