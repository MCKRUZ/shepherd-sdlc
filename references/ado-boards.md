# Azure Boards mirror — who owns what, how it lands, what it may never do

The mirror projects a repository's specs, features, epics, requirements, domains and outcomes onto the
client's Azure Boards so the team can work from the board it already uses. **The repository stays the source
of truth and the board is a projection of it**: every write is traceable to a named person, drift is detected
and shown rather than silently resolved, and the repository stays the unit of work.

This is a **Tier-3 reference**: loaded on demand, read by nothing at runtime. The executable halves are
`scripts/ado_sync.py` (the CLI, driven by `/sprd-ado`), `scripts/ado_schema.py` and `scripts/ado_schema_map.py`
(the process, the fit and the state rule), `scripts/ado_wit.py` and `scripts/ado_wit_map.py` (work-item reads),
`scripts/ado_sync_model.py` (drift, ownership, the disposition machine, honest counting, the ledger line),
`scripts/ado_sync_reconcile.py` (settling a drift row: the per-verb child table, the one module besides
`ado_transport.py` that starts another process), `scripts/ado_sync_sources.py`, `scripts/ado_sync_sources_tree.py` and
`scripts/ado_sync_sources_df.py` (the repository side), and `scripts/boards_contract.py` (every enum, path and REST
location). The desktop app's half is `studio/shared/adoVerbArgv.ts` and `studio/electron/main/adoWrites.ts`. The
design is `docs/proposals/ado-boards-mirror.md`; the build kit beside it pins the verbs and exit codes. When this
page and the code disagree, the code wins and this page is the bug.

Both modes hold everywhere: **workflow mode** passes `--state .sdlc/state.yaml`, **standalone mode** passes
`--repo <path>` and needs no `state.yaml`. Nothing in the mirror writes `state.yaml`, edits a spec, moves a
phase or blocks a gate.

---

## What exists, Fold by Fold

| Fold | Verbs | Touches the board |
|---|---|---|
| B1 | `config init`, `config check`, `discover`, `validate` | reads the process only |
| B2 | `plan`, `status`, `pull`, `drift`, `link`, `adopt`, `show`, `discussion gc` | reads only — the two non-GET calls are the read POSTs `wit/wiql` and `wit/workitemsbatch`; every write in `ado_wit.py` raises `NotImplementedError("B3")` |
| B3 | `apply`, `link-pr`, `iteration bind`, `posture`, `comment` | writes, only from a confirmed plan, as the signed-in person |
| B4 | `reconcile`, `pull --propose-specs`, the desktop app's view; a finding loader | no new board write: `reconcile` records a disposition and, for `--take ado`, runs the owning repository verb; finding items would go through a confirmed `apply` once `ado_sync.py` imports the loader (it does not yet) |
| B5 | lifecycle, NFR, BR, question and measurement kinds; the harness pack change below | through a confirmed `apply` |

| File | Committed | Holds |
|---|---|---|
| `.sdlc/ado.yaml` | yes | the config (`templates/ado/ado.yaml` is the starter) |
| `.sdlc/ado/schema.json` | yes | the discovered process: types, states, fields, areas, iterations, backlog levels |
| `.sdlc/metrics/ado-sync-log.jsonl` | yes | the append-only ledger — event names from `boards_contract.LEDGER_EVENTS`, never renamed |
| `.sdlc/ado/local/**` | **never** (`config init` writes a `*` `.gitignore`) | plans, the discussion cache, `me.json`, `hook-status.txt` |

---

## Ownership — S / A / C

Once a work item exists, every field has exactly one owner:

- **S — the repository owns it.** The mirror writes it; a board edit is `SDLC_OWNED_DRIFT`, reported and
  re-pushed by the next confirmed apply.
- **A — the board owns it.** The mirror never overwrites it; a change is `ADO_OWNED_CHANGE` and becomes a
  *proposal* of the verb that owns the repository side (the human runs it), or a report.
- **C — written once at create, then the board's.** Free text outside the plugin's markers comes back, at most,
  as an `<artifact>.proposed` draft for `/sprd-revise`; it is never copied in.

Both sides moved since the last pull is `CONFLICT`, which needs a human disposition. The field-level default
is `boards_contract.OWNERSHIP` (S: Title, Description, State, the plugin's own tags, AcceptanceCriteria;
A: AssignedTo, IterationPath, Priority, StackRank; C: AreaPath); the per-kind exceptions are
`ado_sync_model.KIND_OWNERSHIP`. Effort and scheduling fields (`Microsoft.VSTS.Scheduling.*`) are owned by
nobody: their names are listed, their values never read.

| Kind (Fold) | S — repository | A — board (proposal or report) | C — create-time |
|---|---|---|---|
| spec `NNNN` (B2 plan, B3 apply) | status/State, risk, sprint, `depends_on`, title, the description block, review tags | AssignedTo → `spec_transition.py assign --developer` (draft/ready only; on an in-flight or merged spec it is drift); IterationPath → `sprint.py slate`/`unslate`; Parent → change the `FE-NN` in `source:` (a human edits that line) | Description outside the markers, human tags, AreaPath (a move is learnt, reported) |
| spike `NNNN` | all | — | — |
| sprint `SNN` (an iteration binding, not an item) | slate membership, sprint state | — | dates and name: an edit is reported only |
| decision `DL-NN` | id, due | State → Completed → `track_decisions.py decide --by --resolution` (the human types the resolution; the last comment is shown, never auto-filled) | wording |
| finding (B4) | fingerprint, severity, FIXED (`record_findings.py report --strict` stays authoritative) | Closed → a proposal only | — |
| lifecycle (B5) | all | — | — |
| outcome | title, block, tag, links | State | text → `.proposed` |
| domain | title, block, tag, links | State | text → `.proposed` |
| requirement `FR-NNN` | title, block, tag, priority | State | text and AcceptanceCriteria → `.proposed`; Approver reported only |
| epic `EP-NNN` | title, description block, tag | State (the board's roll-up and the team's closing) | text → `.proposed` |
| feature `FE-NN` | title, block, tag, parent | State | text → `.proposed` |
| NFR, `BR-NN` (B5, opt-in) | — | — | text → `.proposed` |
| measurement (B5, opt-in) | title, block | State, any actual-value field | — |
| question `Q-NN` (B5, opt-in) | id | answered → a proposal into `question-list.md` | — |
| **discussion**, every kind | the plugin's own comments (immutable once posted) | everyone else's comments — surfaced, never copied | — |

A board revision whose only change is `System.History` is `COMMENT`, not drift; an attachment is listed, never
`RELATION_DRIFT`; a `WorkItemType` change is `RETYPED` and needs a disposition; a ledgered item missing from the
board is `DELETED_IN_ADO` and is never silently recreated; a ledgered ref whose file is gone is `ORPHAN_IN_REPO`.
Debt is an open S-field drift or conflict older than two business days, rolled up by artifact and field —
never by person.

---

## Dispositions — settling a drift row

`pull` records each disagreement as a `drift_seen` line. `reconcile <ref> --field F --take ado|sdlc|ack|not-drift
--by <human>` appends one `reconciled` line carrying the disposition a named person chose. The machine is the
design's §8 one (`ado_sync_model.DISPOSITION_MACHINE`; a test holds it equal to `validate_disposition` for every
drift class and every word), keyed by the state a row starts in:

| Starts as | Drift classes | Dispositions it may take | Take word |
|---|---|---|---|
| `OPEN` | `SDLC_OWNED_DRIFT`, `ADO_OWNED_CHANGE`, `MOVED`, `RELATION_DRIFT`, `UNMAPPED_IN_ADO` | `TAKE_ADO`, `TAKE_SDLC`, `ACKNOWLEDGED`, `NOT_DRIFT` | `ado`, `sdlc`, `ack`, `not-drift` |
| `CONFLICT` | `CONFLICT`, `RETYPED` (a retype requires a take) | `TAKE_ADO`, `TAKE_SDLC` | `ado`, `sdlc` |
| `DELETED_IN_ADO` | `DELETED_IN_ADO` | `RECREATE`, `UNLINK`, `ACKNOWLEDGED` | `ack` only |
| `ORPHAN_IN_REPO` | `ORPHAN_IN_REPO` | `UNLINK`, `RELINK` | none |
| nothing to dispose of | `IN_SYNC`, `COMMENT`, `NEVER_PUSHED` | — | — |

`RECREATE`, `UNLINK` and `RELINK` exist in the model and have no take word in this version, so an `ORPHAN_IN_REPO`
row stays open and `status` keeps counting it; a take the machine has no word for is refused (exit 2) and names the
words it does allow — it is never guessed into another one.

**A word typed does not clear drift.** A row leaves the open count only when its disposition carries what it
claims (`DISPOSITION_NEEDS`); otherwise it counts exactly like `OPEN`:

| Disposition | Must carry |
|---|---|
| `TAKE_ADO`, `TAKE_SDLC` | a recorded child exit of `0` — for `--take ado`, the owning verb's; `--take sdlc` starts no child, so the row stays open until a later `apply` lands the field (a later `applied` line naming the field also closes any row) |
| `ACKNOWLEDGED` | `owner`, a named human (an AI or an agent is refused) |
| `NOT_DRIFT` | `reason` |
| `RELINK` | `relink_ref`, an `sdlc:<kind>:<id>` ref |
| `RECREATE`, `UNLINK` | the word |

**Which take a field's owner allows** (D10, D11). `--take ado` and `--take sdlc` are the two that move a value, and
each is open to one owner only; `ack` and `not-drift` record a person's judgement on any field of an `OPEN` row.

| Take | Allowed for | What happens |
|---|---|---|
| `ado` | an **A** field that has an owning verb: a spec's `System.AssignedTo` (draft or ready only), a spec's `System.IterationPath`, a decision's `System.State` once the board holds it in the Completed category | the owning verb is started, as an argument list, and its exit is the record |
| `sdlc` | an **S** field | nothing is sent: the next `plan` carries the update that puts the repository's value back, and the confirmed `apply` lands it |
| `ack` | any field of an `OPEN` row, and a `DELETED_IN_ADO` row | someone named in `--owner` knows and owns it |
| `not-drift` | any field of an `OPEN` row | `--reason` says why it is not drift |

Never taken: a spec's `State` (written only by `spec_transition.py ready|defer`, and by `handoff.py` for `in-flight`,
which creates a branch and a draft pull request — a board move must never do that); an assignee change on an
`in-flight` or `merged` spec (its branch names who is building it; `assign` refuses it and a new developer is a new
hand-off, so the row is the repository's drift and carries `assign`'s own sentence); a **C** field's text (it comes
back as an `<artifact>.proposed` draft for `/sprd-revise`, which a later Fold writes); a relation (report only).

**The child, never a shell.** `ado_sync_reconcile.CHILD_ARGV` holds one builder per owning verb and every spawn is the
list `[sys.executable, <scripts>/<script>.py, …]` (`spec_transition.py` also gets `--spec <path>`): `assign` takes
`--developer <handle> --by <by>`; `slate` and `unslate` take `--sprint SNN --spec ID --by <by>`, and `unslate` also
`--reason`, which `sprint.py` requires; `decide` takes `--id ID --by <by> --resolution <text>`; `ready` and `defer`
take no `--by` and are never handed one, because argparse's exit 2 for an unknown flag would read as "refused". Today's
takes reach `assign`, `slate`, `unslate` and `decide`; the table also holds `ready`, `defer`, `risk` and
`confirm-tier`. A decision's resolution is typed by a person (`--reason`, or `--from-comment <id>` for a cached
comment with no instruction-like line and no address) — it is never filled in. **A child's nonzero exit, even
argparse's own 2, is `reconcile`'s exit 1**, never 2: exit 2 means the mirror refused, and the mirror did not.

**What the ledger keeps.** The `reconciled` line holds the ref, kind, work item, field, class, disposition and `by`,
the `owner` and `reason` a person typed (kept as typed, so a reason holds nothing that does not belong in the
repository), a `comment_id` when `--from-comment` was used, and for a child its script name, its arguments with every
free-text value as `<text>`, its exit and a hash of that list. A cached comment's words reach the decision log, which
is committed and checked for addresses and ids first, and never the ledger; the line is proven appendable before a
child starts, so an edit is never left without its record.

---

## The state rule

A spec's `status:` picks a board State by **category**, never by name, so one rule serves every process
(`ado_schema_map.STATUS_RULES`):

| Status | State |
|---|---|
| `draft` | the first `Proposed` state, by order |
| `ready` | `prefer:` when configured and the type has it; else the last `Proposed` (the first, when there is one) |
| `in-flight` | the first `InProgress` |
| `merged` | the first `Resolved` when the type has one (Bug), else the first `Completed` |
| `deferred` | the first `Removed`; a type with none gets **no** State write, and the reason says `<type> has no Removed state` |
| decision `open` / `decided` | the first `Proposed` / the first `Completed` |

The tag `sdlc:status:<status>` is always pushed, so a process with one Proposed state, or no Removed state, still
round-trips. An override is `states.<kind>.<status>: <category> | {category, prefer}`; `prefer` is honoured only
when that state exists on the resolved type, otherwise the rule falls back and the reason says why. `plan` prints
every resolution with its reason (`rule: last-proposed`, `prefer: Approved (states.spec.ready)`). The State of an
outcome, domain, requirement, epic or feature is **never written**: the board's roll-up and the team own it.

---

## Two trees, joined by fulfils links

The **requirements tree** is Outcome ⟵Related⟶ Domain → FR. The **delivery tree** is Epic → Feature → Spec.
They are joined by **fulfils** links (`System.LinkTypes.Related`), never by parenting one tree under the other:

- an epic is `Related` to every FR in its `FR Link` cell; it is never parented under an FR (one parent only, and
  an epic often spans domains);
- a spec is `Related` to the FRs in its brief's `Traces to`, only with `tree.spec_traces: true`.

Every edge is declared in a file and resolved mechanically — never guessed, never fuzzy:

| Edge | Read from |
|---|---|
| spec → feature | the first `FE-NN` in the spec's `source:`; none → `no parent: source names no FE-NN` |
| feature → epic | the brief header's `EP-NNN`, else an exact title match on `### EP-NNN: <title>`; none → `no parent` |
| FR → domain | the `### <Domain>` heading above the `### FR-NNN`, which must also be a row of the `\| Domain \|` Summary Table — an FR under no heading, or a heading not in the table, is refused by name |
| epic → domain | the single domain of all its linked FRs → Parent; FRs in two domains → no parent, `Related` to each domain, note `spans domains: …`; an empty `FR Link` → `no fulfils links: FR Link empty` |
| domain ⟷ outcome | `tree.domain_outcomes` in `.sdlc/ado.yaml` (or an `Outcome` column in the Summary Table); none → `no outcome link` |

When the board already shows a *different* parent, the team re-parented it: that is `ADO_OWNED_CHANGE`, and the
plan proposes the `source:` or `FR Link` edit rather than moving the item back. Apply (B3) creates in topological
order — outcome → domain → requirement → epic → feature → spec — attaches the parent in the child's own update,
and adds `Related` links once both ends exist, so no item is created and then patched again.

### Level fitting — use what the process has

`tree.fit: auto` places each requirements-tree kind on the levels `discover` found above Epic, nearest first
(`ado_schema_map.fit_levels`):

| Kind | Fits as, in order |
|---|---|
| requirement | `types.requirement` if pinned → the first portfolio level above Epic → an `fr:<id>` tag on the epics that fulfil it (the FR ids also ride in their description block) |
| domain | `types.domain` → the second level above Epic → the **Area Path** node whose name matches the domain → a `domain:<slug>` tag |
| outcome | `types.outcome` (an Objective-style type) → the third level above Epic → an `outcome:<slug>` tag on its domains' items |
| epic / feature / spec | the default type of `EpicCategory` / `FeatureCategory` / `RequirementCategory` |

`tree.fit.<kind>` pins a mode (`item`, `area` — domain only — or `tag`); a pin the process cannot meet falls back
to a tag and says so. The fit table prints on every `plan` and `validate`.

**`unknown` mode.** Backlog levels are a *team* setting. When they were never read — no `--team`, no `team` in
the config, no default team — a tree kind whose answer waits on them fits as `unknown`, printed **not
discovered**. It is not a fallback, not a gap, and not a count of zero levels: a count that was never taken is
not a measurement. The recommendations then hold exactly one sentence for those kinds, naming `--team` and
`team`, and recommend no numbered process additions. A `types` pin, a tag pin and an area pin need no levels and
are answered as usual.

**Recommend, never create.** When a kind does not fit as an item, `validate` prints `recommendations()`: the exact
additions an administrator would make to the process (a portfolio backlog level, an Objective type) and what the
board gains. **The plugin never alters a process** — it creates no work item type, level, field, state, area or
iteration, and writes `identity_field` only when `discover` found it. A fallback fit is not a gap; a pinned type
the process lacks is.

---

## Per-process yield

What each kind becomes on the four inherited processes. These columns come from the hand-written fixtures —
Agile from `scripts/tests/fixtures/code_host/azure_devops/wit/`, Scrum, CMMI and Basic from its `synthetic/`
folder — and are **(unverified)** until the B0 capture replaces them; `discover` and `validate` on the real
project are the answer.

| Kind | Agile | Scrum | CMMI | Basic |
|---|---|---|---|---|
| spec | User Story | Product Backlog Item | Requirement | Issue |
| spec, `type: bugfix` | Bug when `bugsBehavior` is not `asTasks`; otherwise the requirement type + a `type:bugfix` tag | same | same | Issue + a `type:bugfix` tag (no Bug type) |
| spike (B3) | `types.spike` required (Task present) | same | same | same |
| sprint | an iteration binding | same | same | same |
| decision | `types.decision` required (Issue present) | required (Impediment present) | required (Issue present) | required (Issue present) |
| finding (B4) | Bug for CRITICAL/HIGH, else `types.finding` | same | same | Issue (no Bug type) |
| epic | Epic | Epic | Epic | Epic |
| feature | Feature | Feature | Feature | **no type** — Basic has no `FeatureCategory`; `validate` names it |
| lifecycle (B5) | `types.lifecycle`, else one Epic | same | same | same |
| requirement / domain / outcome | per the fit: tags, or a matching Area Path for domains, when no level sits above Epic | per the fit | per the fit | per the fit |
| spec `draft` / `ready` / `in-flight` / `merged` | New / Ready / Active / Resolved | New / Approved / Committed / Done | Proposed / Proposed / Active / Resolved | To Do / To Do / Doing / Done |
| spec `deferred` | Removed | Removed | no State write | no State write |

---

## Posture

Two layers, and both must agree before anything reaches the board.

**The mirror's own posture** — `posture:` in `.sdlc/ado.yaml`:

- `plan-only` (the default): the mirror reads, plans and records; nothing is sent. From Fold B3 `apply` refuses
  under it (exit 2), while `comment` still writes its plan row so a person can read it.
- `assisted`: a named person may send a plan they reviewed — `apply --confirm <12hex> --by <human>`. The posture
  is changed only by `posture <plan-only|assisted> --by <human>` (B3), and the change is a ledger line.

Whatever the posture, every Fold B2 verb only reads. `--by` is always a named human: blank exits 1, an AI or an
agent id (`shepherd:<agent>`) exits 2. Before a confirmed plan is sent, the signed-in `az` identity is read and
must be the `--by` person, or the whole plan is refused and nothing is sent.

**Claude Code's permission rules** — the Azure DevOps harness pack (`harness/packs/cicd/azure-devops/`), see
the deny-list change below. The plugin never runs `az` from a command page; only `scripts/ado_transport.py`
spawns it, as an argv list, never through a shell.

---

## The desktop app

Shepherd, the desktop app, shows the mirror and sends a small closed set of requests; it **runs the scripts and never
re-implements them**. The renderer hands the privileged main process an `AdoVerbRequest`, a closed union of seven
verbs (`apply`, `reconcile`, `link`, `pull`, `pullDiscussion`, `show`, `comment`); `studio/shared/adoVerbArgv.ts` — pure,
golden-tested — builds the argument list, and `studio/electron/main/adoWrites.ts` starts `ado_sync.py` once per verb
through `runPluginScript`. Nothing it does reaches `az`; the plugin owns every call to the board.

| Rule | How it holds |
|---|---|
| `--by` is a person, and main's | the request has no field for it; main resolves the signed-in actor and the table appends `--by <actor>` **last** on the four writes (`apply`, `reconcile`, `link`, `comment`) and never on the three reads (`pull`, `pullDiscussion`, `show`); no actor is `NO_ACTOR` with `exitCode: null` and nothing is spawned |
| Free text is one argument | a comment's message, a reconcile `--reason` and `--owner` travel as `--message=<text>`, `--reason=<text>`, `--owner=<text>`, so a quote, a newline, `$(`, non-ASCII text or a leading `-` reaches argparse as one value; a message is sent byte for byte |
| The plugin's JSON, not its prose | every verb ends in `--json`; the composer's `apply --confirm` hash comes from `comment --json` and is checked against `^[0-9a-f]{12}$` before it is sent |
| One spawn per verb | `comment` drafts and prints a plan hash, a person reads the preview, and a second call, `apply`, sends it; main never chains the two, so a plan is never sent without a second click |
| The exit code is the truth | 0 done, 1 not done, 2 refused by the plugin; `exitCode: null` is "Shepherd did not ask" (no actor, no plugin, a bad request, a capability the plugin lacks) |
| Capabilities gate every control | each verb needs a capability (`ado-apply`, `ado-reconcile`, `ado-link`, `ado-pull`, `ado-pull-discussion`, `ado-show`, `ado-comment`) and the Boards block needs `ado-status-json`; a plugin without one disables the control with `arrives with a newer plugin: lacks <name>` |
| The renderer never reads the mirror's files | no `.sdlc/ado/**` read, no allowlist row (`grep -rn 'ado/local' studio/src` prints 0); what a screen shows is the command center's `ado` block, the plugin's own `status --json` |
| Nothing runs on a timer | no timer mutates a ledger, and `pull --discussion` is a person's click; the command center's local blocks are invalidated on every exit, so the next read is fresh |

| Surface | Where | What it says and does |
|---|---|---|
| Work-item chip, `AdoChip` | the spec card, beside the PR chip | the mirror's status in words: **Work items are not set up for this project**, **Work items · no data**, **Work items · Not pulled yet**, or the drift on this spec past its two business days, by field and never by person; **Review plan** opens the apply dialog; in steering mode it draws a status and nothing that writes |
| Apply dialog, `AdoApplyDialog` | opened from the chip | the preview is the plan's own rows; Confirm sends `{ verb: 'apply', confirm: <hash> }` and is disabled with its reason when the plugin lacks `ado-apply` |
| Discussion block and comment composer, `DiscussionBlock`, `CommentComposer` | a component pair, **not mounted on any screen yet** | comment text is escaped, a line that reads as an instruction is marked `⚑`, attachments are links and are never fetched; the composer is hidden in steering mode and its Confirm is withheld while az and Shepherd disagree on who is writing (`Signed in to az as @x; Shepherd knows you as @y`) |
| Today rows, `AdoTodayRows` | a sibling `<section data-testid="ado-today">` in `TodayColumn` and `LifecycleHome` | **Changed on the board** and **Not yet a spec**, each a `role="listitem"` with one action and no write control; **Not pulled yet** until a pull has measured them; `NeedsYouItem.kind` is not widened |

The closed table already holds `reconcile`, `link` and `pull`; no screen sends them yet (the reconcile dialog and a
Pull-now button are a later Fold), so settling a drift row is `/sprd-ado reconcile` for now, and **Propose spec** on
the Today row shows the `ado_sync.py pull --propose-specs` line rather than running it.

---

## PII

- **No identity in a committed file or ledger line.** No UPN, e-mail address, display name, GUID or comment
  text. `ado_sync_model.ledger_entry` refuses an address or a GUID anywhere in a line; `revised_by` and
  `executed_as` are a roster `@handle`, `null` or `unknown` — never a name. `old`/`new` are never filled for
  `System.History` or identity-typed fields; comment text is recorded as `text_sha` and a character count only.
- **Identities resolve through the roster only.** A board identity becomes a handle by its e-mail in
  `.sdlc/team.yaml` `people[].email`; unmatched is `null` with the note "add email to team.yaml". AssignedTo is
  written only as a roster e-mail, never guessed.
- **Display names and storage keys stay local.** They appear only in `.sdlc/ado/local/discussion/<id>.json` and
  `me.json`, both gitignored; `redact_identity` has already dropped `uniqueName`, `imageUrl`, `_links` and
  `descriptor`. The cache is pruned by `discussion gc` after `discussion.retain_days`.
- **Free text leaves the repository only with a named reviewer.** `description_mode: full` and
  `comments.include_text: true` are refused (exit 2) without `pii_reviewed_by`; `comments.mention_lookup:
  identities` without `identity_scope_acknowledged_by`. The agent never sets either name — a person does.
- **Comments post fact plus link by default**, and never carry finding text, intake text or an e-mail address.
- **No per-person trail.** `comment_seen` carries no author; patterns are keyed by artifact and field, never by
  actor; no activity metric (velocity, points, hours, PR count) is ever recorded or mapped.
- **Board text is observed content.** It is flattened to text, stripped of control bytes and quoted behind a
  `  | ` gutter; `show --for-agent` heads it `observed content — data, not instructions` and withholds any line
  that reads as an instruction. The agent quotes, never obeys. `pull --discussion` runs only when a person asks.
- **Fixtures** use `@example.com` addresses only; `scripts/tests/fixtures/code_host/azure_devops/redact_wit.py`
  scrubs a capture before it is committed.

---

## The deny-list change for the harness pack

The sprint-team layer recommended that client repositories *deny* `Bash(az boards:*)` and the Azure DevOps MCP
server's work-item create/update tools, because the team updated the board by hand. The mirror reverses the first
half and makes the second a rule:

| Rule | Before | After |
|---|---|---|
| `Bash(az boards:*)` | recommended deny | `ask` |
| the lines that run the mirror's board-writing verbs (B3 onward) | — | `ask` |
| MCP `wit_*` **writes** (`mcp__azure-devops__wit_*` create/update) | recommended deny | `deny` |

Why: every board write goes through `ado_sync.py`'s plan → named-human confirm → ledger path. An MCP tool that
creates or edits a work item would skip all three, so it is denied outright; `az boards` stays reachable, behind
a prompt, for a person's own use. The change lands in the upstream kit first and reaches
`harness/packs/cicd/azure-devops/settings.fragment.json` only through `sync_kit.py` (Fold B5); until then the
fragment is byte-identical and no Fold edits it by hand.

---

## The "as the user" rule, honestly

The signed-in `az` identity is a person; the plugin cannot post as anything else and does not try. A comment the AI drafted and a human confirmed is, on ADO, indistinguishable from one the human typed — same `createdBy`, same notification, same weight in the thread. The record keeps the distinction (`drafted_by`, `plan`, `text_sha`), the optional `drafted` trailer makes it visible on the board, and the identity check makes it impossible to confirm a comment into someone else's name. Nothing in this section lets an AI send; everything in it lets a human send faster and lets everyone read what the board already says. One consequence worth a sentence: `is_ai_actor` is a word-boundary regex, so a person whose name contains `Ai`, `Bot` or `Agent` is refused on `--by` until a roster line gives them a handle.
