# Kit issue — permission rules for the Azure Boards mirror (design D21, D-OWNER-4)

**For the human who files it.** This is the issue text for `MCKRUZ/intent-driven-development` (the upstream kit,
the source of the Azure DevOps pack that Shepherd copies into `harness/` with `scripts/sync_kit.py`). No agent files
it: open a new issue there, paste everything below the rule, and put the issue's number in the design's owner table
(`docs/proposals/ado-boards-mirror.md`, D-OWNER-4) when it exists. It is due before Fold B5-P6 — the one step that
mirrors the change into this repository's pack fragment, and only through `sync_kit.py`, never by hand.

Before filing, confirm two things against the kit's own checkout, because this repository could not:

1. the tool names the Azure DevOps MCP server (`@azure-devops/mcp`, pinned `2.8.1` in
   `harness/packs/cicd/azure-devops/mcp.fragment.json`) exposes for work-item writes — start the server and read its
   tool list, then correct the names in section 3 if they differ;
2. whether Claude Code expands `${CLAUDE_PLUGIN_ROOT}` inside a permission rule (section 2) — the quick test is in
   the acceptance list.

---

## Title

Azure DevOps pack: `ask` on the Azure Boards write verbs and `az boards`, `deny` on the MCP server's work-item write tools

## Background

Shepherd (the plugin that installs this kit's harness) is adding an Azure Boards mirror. It reads a client's board,
plans what the board would need to match the repository's specs, and — only when a named person has switched the
repository to `posture: assisted` and typed the plan's 12-hex hash — writes that plan to the board **as that
person**. Every board write goes through one path: a plan file, a named human's `--by`, an identity check, and a
ledger line.

The Azure DevOps pack in this kit currently puts `Bash(az devops invoke:*)` on `ask`, allows read-only `az repos` and
`az pipelines` calls, and ships `@azure-devops/mcp` in its MCP fragment. Two things in that posture no longer fit
once the mirror exists:

- `Bash(az boards:*)` is not covered by any rule, so an agent can create or edit a work item with `az boards` without
  a prompt and without the plan, the hash, the identity check or the ledger line.
- The MCP server ships work-item create / update / link tools. A call to one of them is a board write by an agent
  that carries none of the same four things, and Claude Code's permission rules are the only layer that can stop it
  before it happens.

An earlier note in Shepherd's sprint-team layer recommended the opposite for `az boards` (deny it, because the team
updated the board by hand). That recommendation is withdrawn: the board is now written through the mirror, and a
person's own use of `az boards` stays reachable behind a prompt.

## What we are asking for

Three changes to the Azure DevOps pack's settings fragment (`settings.fragment.json`; in Shepherd it is
`harness/packs/cicd/azure-devops/settings.fragment.json`, merged into `.claude/settings.json` by the installer).

### 1. `ask` for `az boards`

```json
"Bash(az boards:*)"
```

Into `permissions.ask`. `az boards query` is a read, but `ask` takes precedence over `allow` in Claude Code, so a
carve-out for reads would be shadowed anyway (the fragment's own header says the same of `az repos policy`); the
prompt is cheap and the mirror never uses this form — its own reads go through the plugin's script.

### 2. `ask` on the plugin's write verb lines

Into `permissions.ask`, in the form the plugin's command pages use:

```json
"Bash(uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/ado_sync.py apply:*)",
"Bash(uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/ado_sync.py reconcile:*)",
"Bash(uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/ado_sync.py link:*)",
"Bash(uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/ado_sync.py link-pr:*)",
"Bash(uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/ado_sync.py iteration bind:*)",
"Bash(uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/ado_sync.py posture:*)"
```

Why these six: `apply` and `link-pr` write to the board; `reconcile` (the verb that acts on what a pull found; it
follows `apply` and is not built yet) changes the repository or the ledger from what the board says; `link` records that a repository item *is* a given work item, which
every later write relies on; `iteration bind` and `posture` change what the mirror will do next. Each already refuses an
AI or agent `--by` (exit 2) and `apply` refuses any plan whose hash the person did not type, so the rule corroborates
those checks with a prompt a human sees — it is the second layer, not the only one.

Not asked for: `config`, `discover`, `validate`, `plan`, `status`, `pull`, `drift`, `show` and `discussion gc` read the
board or write only under `.sdlc/`; `comment` only drafts a plan file (sending is `apply`). `adopt` makes the same
decision as `link` and can sit beside it if you prefer — the design lists `link` alone.

**Unverified, and the reason for this section's fallback.** Whether Claude Code expands `${CLAUDE_PLUGIN_ROOT}` inside a
permission rule is not established, and no rule in the kit's `harness/` uses a token like it today. If the command the
agent runs carries the installed absolute path, a rule that still holds the literal token would never match. The
fallback is the literal path of the installed plugin:

```json
"Bash(uv run --project <plugin root>/scripts <plugin root>/scripts/ado_sync.py apply:*)"
```

(and the same five verbs), where `<plugin root>` is the directory the plugin is installed in. The installer would have to
write it, and it changes with the plugin's version, so prefer the token form if it is honoured. Please settle which form
works with the acceptance test below, and ship that one.

### 3. `deny` on the MCP server's work-item write tools

Into `permissions.deny` (the key is new to this fragment). The names below are the work-item write tools of
`@azure-devops/mcp` `2.8.1` as we understand them — **verify against the server's tool list before merging**:

```json
"mcp__azure-devops__wit_create_work_item",
"mcp__azure-devops__wit_update_work_item",
"mcp__azure-devops__wit_update_work_items_batch",
"mcp__azure-devops__wit_add_child_work_items",
"mcp__azure-devops__wit_add_work_item_comment",
"mcp__azure-devops__wit_work_items_link",
"mcp__azure-devops__wit_work_item_unlink",
"mcp__azure-devops__wit_link_work_item_to_pull_request"
```

A `wit_*` wildcard (`mcp__azure-devops__wit_*`) would be shorter and would not rot when the server adds a write tool,
but it would also deny the read tools (`wit_get_work_item`, `wit_my_work_items`, `wit_list_backlogs` and the rest). Reads
through the MCP server should stay allowed for interactive questions, so list the writes. If your Claude Code version
does not take a wildcard in an MCP rule at all, the explicit list above is the only form.

## Why this belongs in the kit and not in each client repository

The mirror's guarantees — a named human, a plan the person read, the identity the board will record, an append-only
ledger — hold only if no other path writes the board. A client repository that adds the MCP server (the pack does this
for it) and never edits its settings would have an open side door. The pack is where both halves are installed, so it is
where they should be closed.

## What the kit's change does not do

- It does not stop the plugin's own scripts. Shepherd spawns `az` from inside its Python script, which Claude Code's
  permission rules cannot see (the fragment's header already says this of `doctor.py`); the script's own checks are the
  control there, and these rules are the control for everything an agent runs directly.
- It does not alter any process, permission or setting on the client's Azure DevOps organisation.
- It does not touch the read-only `allow` entries.

## Acceptance

1. In a scratch repository with the pack installed, a call to any tool in section 3 is refused without a prompt, and
   a read tool of the same server (for example `mcp__azure-devops__wit_get_work_item`, name as we understand it) is
   still allowed.
2. `az boards work-item show --id 1` in the agent's shell produces a permission prompt.
3. With Shepherd installed, asking the agent to run `ado_sync.py posture plan-only --by "Test"` produces a permission
   prompt, then runs on approval. **This is the test that decides token form against literal path** — if it runs with no
   prompt, the rule did not match and the other form is needed.
4. The same prompt appears for `apply`, `link-pr`, `iteration bind`, `link` and `reconcile`; none appears for `plan`
   or `status`.
5. Shepherd's `sync_kit.py --check` is clean after the change is mirrored: its invariant is that `harness/` equals the
   kit under the rename map, so the pack fragment here is regenerated from the kit with `sync_kit.py --kit <path>`, not
   edited.

## For reference — what Shepherd does meanwhile

Nothing in Shepherd waits for this issue to land: the mirror is plan-only by default, every write verb refuses an AI
name, and the write path is covered by an argv golden that fails if an option which silences notifications, skips the
process's rules or only validates is ever sent. Shepherd's `references/ado-boards.md` describes the rule change as
planned and says it reaches this repository's pack only through `sync_kit.py`. Until the kit has these rules the
permission posture is open: a client that needs it closed sooner can add the same lines to its own
`.claude/settings.json` by hand.
