# /sdlc-channel — Bind a Spec to Its Channel and Inject the Acceptance Dimensions

Bind one spec to its delivery **channel** and overlay that channel's acceptance dimensions onto the
spec's *existing* `## Acceptance Checks`. This is the *bind* beat after `/sdlc-feature` (decompose) and
`/sdlc-experience` (author): decompose → author → **bind**. It reads the channel descriptor and the
Phase-2 interaction spec, injects concrete checks, seeds `harness_context`, sets the `channel:` field,
then runs the **advisory** `check_channel.py` *beside* the byte-for-byte-unchanged `check_spec.py`.
Interview-driven like `/sdlc-coach` at the confirmation step: the command proposes the overlay; a named
human decides.
Command-only — it orchestrates the descriptors and the experience artifacts; it spawns no discipline
agent of its own (though it may compose the `visual-designer`/`conversation-designer` if the interaction
spec is missing). Works inside an SDLC project or standalone.

## Instructions

1. **Resolve context:**
   - **Workflow mode** (default): `.sdlc/state.yaml` exists. The repo root is the directory containing
     `.sdlc/`; the interaction spec is `.sdlc/artifacts/02-design/experience/channel-interaction-spec.md`;
     metrics log to `.sdlc/metrics/channel-log.jsonl`.
   - **Standalone mode** (`--repo <path>`, or no `.sdlc/` found): operate on the given repo with
     provisional context; take the interaction spec from `--interaction-spec` if given.

2. **Resolve the target spec and its channel:** Take the spec from `--spec` (required if ambiguous) and
   the channel from `--channel`, the spec's `channel:` field, or the feature-brief row (ask if none). If
   the spec already sets a *different* `channel:`, stop and confirm with the human — a spec is one
   channel.

3. **Load the descriptor and the interaction spec:** Read `channels/<channel>.yaml` for the channel's
   **Acceptance Dimensions** (`id` / `intent` / `example_check`), `harness_context_seed`, and
   `risk_floor`. Read the Phase-2 `channel-interaction-spec.md` if present — its dimension → contract →
   acceptance-check rows are the concrete, feature-specific checks to inject. If neither the descriptor
   nor the interaction spec exists, tell the human to add the descriptor (`channels/_template.yaml` →
   `validate_channel.py`) or run `/sdlc-experience` first.

4. **Set the `channel:` field and seed `harness_context`:** Set the spec's optional `channel:`
   frontmatter to `<channel>`. If the spec's `harness_context` is empty, seed it from the descriptor's
   `harness_context_seed` (so a first-of-its-kind channel spec passes the DoR `harness_context` check).
   Leave every other field alone.

5. **Inject the acceptance dimensions as concrete `## Acceptance Checks` lines:** For each dimension not
   already covered, add one line to the spec's existing `## Acceptance Checks` section — prefer the
   interaction-spec's contract row where present, else the descriptor's `example_check` — tagged with
   its dimension id, e.g. `- [ ] Caller speech cancels TTS within 200 ms   (channel: barge-in)`. Written
   this way they pass the vague-line test up front. Once injected they are **ordinary acceptance
   checks** — nothing downstream knows they came from a channel.

6. **Confirm the overlay with the human:**

> **HITL GATE:** Present the injected checks and the risk implication using the `AskUserQuestion` tool.
> Ask:
> (1) Confirm the injected `## Acceptance Checks` set (edit any line that could be built two ways).
> (2) Confirm the channel's `risk_floor` implication — it may only **raise** the tier, never lower it
>     (`llm_powered` channels floor at HIGH); the Pod Lead owns the final tier. If the floor raises the
>     tier, re-confirm it at `/sdlc-spec`.

7. **Run the advisory channel check beside the unchanged spec check** (the command owns `check_channel.py`):
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/check_channel.py \
     --spec <repo-root>/specs/NNNN-name.md --channels-dir ${CLAUDE_PLUGIN_ROOT}/channels [--state .sdlc/state.yaml]
   ```
   `check_channel.py` is **advisory — exit 0 always, SHOULD-only**; it flags any descriptor dimension not
   covered by an acceptance check and can never change a ready/not-ready verdict. Then re-run the
   **unchanged** `check_spec.py` to confirm the spec is still READY with the channel bound:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/check_spec.py \
     --spec <repo-root>/specs/NNNN-name.md [--state .sdlc/state.yaml]
   ```

8. **Report:**
   ```
   Channel Bound: specs/NNNN-name.md  ← channel: <channel>
   ============================================
   Injected:   N acceptance checks (dimensions: …)
   harness_context: seeded from descriptor | already set
   Risk floor: <HIGH/MEDIUM/LOW> — tier <raised to …> | unchanged (Pod Lead owns final tier)
   check_channel: all dimensions covered | ADVISE: <uncovered> (exit 0)
   check_spec:  READY | NOT READY (unchanged core)
   Next: /sdlc-evals for the golden set (llm_powered channel); then the Delegate beat.
   ```

## Arguments

- `--spec <path>`: the spec to bind (required when more than one spec is in play).
- `--channel <id>`: the channel to bind (otherwise the spec's `channel:` / feature-brief row / asked).
- No `--repo`/`.sdlc/`: workflow mode. `--repo <path>`: standalone mode.
- `--interaction-spec <path>`: point at a specific `channel-interaction-spec.md` (standalone).

## Important

- **`check_spec.py` is byte-for-byte unmodified.** `/sdlc-channel` never edits it or its verdict; it runs
  `check_channel.py` *beside* it. `check_channel.py` is advisory (exit 0), SHOULD-only, and can never
  flip ready/not-ready.
- **The injected checks are ordinary acceptance checks.** They ride the spec's *existing* section and
  are graded by the existing grader; nothing downstream treats them specially.
- **One channel per spec.** Do not bind a second channel to a spec — decompose into per-surface specs.
- `risk_floor` may only **raise** the tier, never lower it; a named human still owns the final tier at
  `/sdlc-spec`. The command changes no protected core.
