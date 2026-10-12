# /sdlc-experience — Author the Channel-Shaped Experience for a Surface

Author the **craft** of a surface — the user journey, the surface layout, and the channel interaction
spec — for one channel-bound spec. This is the *author* beat between `/sdlc-feature` (which
*decomposes*) and `/sdlc-channel` (which *binds*): decompose → **author** → bind. It routes by the
feature's channel to the right designer — `ag-ui` to the `visual-designer`, `voice`/`chat` to the
`conversation-designer` — and is interview-driven like `/sdlc-coach`: the designer assesses what's
there, asks focused questions, and drafts as answers arrive. Design **proposes**; a named human
**decides**. Works inside an SDLC project or standalone.

## Instructions

1. **Resolve context:**
   - **Workflow mode** (default): `.sdlc/state.yaml` exists. Read the `feature-brief.md` row (or the
     spec's `channel:` field) for the surface being designed; artifacts land in
     `.sdlc/artifacts/02-design/experience/`.
   - **Standalone mode** (`--repo <path>`, or no `.sdlc/` found): operate on the given repo with
     provisional context; write to `--output` (default alongside the repo) and note the missing context
     in the artifact headers.

2. **Determine the channel and load its descriptor:** Take the channel from `--channel`, the target
   spec's `channel:` field, or the feature-brief row (ask if none is set). Read
   `channels/<channel>.yaml` — its **Acceptance Dimensions** and **Interaction Contract** drive the
   interaction spec. If no descriptor exists for the channel, tell the human to add one
   (`channels/_template.yaml` → `validate_channel.py`) before authoring.

3. **Route to the right designer:**
   - `ag-ui` (and other screen-based surfaces) → spawn the `visual-designer` agent (Design / web); its
     `surface-layout.md` holds screens and its `channel-interaction-spec.md` **is the AG-UI event
     contract**, co-authored with Engineering.
   - `voice` or `chat` → spawn the `conversation-designer` agent (Design / voice + chat); its
     `surface-layout.md` is the **turn-by-turn script** (voice) or **message flow** (chat) and its
     interaction spec is the turn / barge-in / readback (voice) or threading / escalation (chat)
     contract.

4. **Author the three experience artifacts** (interview-driven; the agent drafts from the templates in
   `templates/phases/02-design/experience/`):
   - `user-journey.md` — the journey including abandon / failure / dead-end paths.
   - `surface-layout.md` — channel-adaptive: screens for visual, turn-script for voice, message-flow for
     chat (markdown in-repo, plus a hi-fi/Figma link where relevant).
   - `channel-interaction-spec.md` — the descriptor-dimension → contract → acceptance-check table. Each
     row traces a `channels/<channel>.yaml` Acceptance Dimension to a concrete contract to the
     acceptance check it becomes on the spec. This is the artifact `/sdlc-channel` reads to inject the
     channel's dimensions into the spec's `## Acceptance Checks`.

5. **Confirm the contract and route dead-ends with the human:**

> **HITL GATE:** Present the interaction contract using the `AskUserQuestion` tool. Ask:
> (1) Confirm each interaction-spec row (dimension → contract → acceptance check) — these become graded
>     Acceptance Checks on the spec, so they must pass the vague-line test now.
> (2) Which journey dead-ends / unresolved experience choices become **decision-log** items (owner +
>     2-business-day clock) — the designer never decides these.
> Design proposes; a named human signs the experience section at the Phase-2 gate (captured in state).

6. **Report:**
   ```
   Experience Authored — <channel> surface
   =======================================
   Designer:  visual-designer | conversation-designer  (routed by channel)
   Artifacts: user-journey.md, surface-layout.md, channel-interaction-spec.md
   Contract:  N dimension→check rows ready to inject
   Decisions: M opened on the decision-log (owners: …) | none
   Next: /sdlc-channel to bind this spec's channel: and inject these rows as Acceptance Checks.
   ```

## Arguments

- No arguments: workflow mode — author for the current project's surface.
- `--repo <path>`: standalone mode — author in any repo with no `.sdlc/` present.
- `--channel <id>`: name the channel explicitly (otherwise taken from the spec/feature-brief or asked).
- `--spec <path>`: the target spec whose channel is being designed (sets the routing).
- `--output <path>`: override the output location (standalone).

## Important

- **Routing is by channel, not by preference.** `ag-ui` → `visual-designer`; `voice`/`chat` →
  `conversation-designer`. The one `channel-interaction-spec.md` is channel-shaped: an event contract
  for `ag-ui`, a turn/barge-in/readback contract for `voice`, a threading/escalation contract for `chat`.
- **This command feeds `/sdlc-channel`.** It authors the interaction spec; `/sdlc-channel` reads it to
  inject the channel's acceptance dimensions into the spec. Author, then bind.
- **Persona stays in the experience layer** — journeys and notes are (channel × persona)-aware, but
  persona is never a spec field; only `channel:` lands on the spec.
- These artifacts are **optional** for gate purposes; an unfilled section is an advisory flag. Design
  proposes; a named human signs at the phase gate. The command changes no protected core.
