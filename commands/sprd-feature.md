# /sdlc-feature — Decompose an Epic into Channel-Aware Features and Specs

Drive the **epic → feature → spec** decomposition that the plugin lacks today — the "featuring" hop
where you decide *how* a feature is delivered (which customer channels, which personas) and carve it
into buildable specs. Output is `feature-brief.md`, authored on every channel-bound feature. This is
interview-driven like `/sdlc-coach`: the `feature-architect` agent assesses what's there, asks focused
questions, and drafts the brief as answers arrive — it **proposes**, a named human **decides** (the One
Rule). Works inside an SDLC project or standalone against any repo.

## Instructions

1. **Resolve context:**
   - **Workflow mode** (default): `.sdlc/state.yaml` exists. Read the epic from
     `.sdlc/artifacts/01-requirements/epics.md`, the requirements from `requirements.md`, and any
     `user-stories.md`; the brief lands in `.sdlc/artifacts/01-requirements/feature-brief.md`.
   - **Standalone mode** (`--repo <path>`, or no `.sdlc/` found): operate on the given repo with
     provisional context. Note the missing engagement context in the brief's header and write it to the
     given `--output` (default alongside the repo).

2. **Assess what exists:** Read the epic and any prior requirements/persona/channel-sensing work. The
   feature-brief sits **below** the epic — it decomposes one epic into features + specs; it does not
   replace `epics.md` or the stories. If no epic is available, ask the human to name the epic and its
   outcome before decomposing.

3. **Run the interview:** Spawn the `feature-architect` agent (Product discipline). It runs the
   coach-style dialogue — which epic; the single coherent slice of value (the feature); who the customer
   is and how they reach it (the channel is **sensed** here); whether there is shared "brains" logic
   multiple surfaces reuse (a channel-agnostic spec); and any product choice not yet decided that the
   agent must not guess. It drafts `feature-brief.md` from
   `templates/phases/01-requirements/feature-brief.md` — each `##` section names its owning discipline,
   with a Channels × personas narrative and a decomposition table whose rows carry **channel + persona**
   columns. Channel-agnostic rows (`channel: —`) are first-class — the shared brains the surfaces build
   on. **One channel per spec.**

4. **Confirm the decomposition and the proposed risk tiers with the human:**

> **HITL GATE:** Present the proposed decomposition using the `AskUserQuestion` tool — this is what
> makes the brief decided rather than generated. Ask:
> (1) Confirm or edit the spec decomposition (each row's name, channel, and persona; channel-agnostic
>     brains split out from per-channel surfaces).
> (2) Confirm the **proposed risk tier** on each row (the agent proposes HIGH / MEDIUM / LOW with a
>     reason — channel-agnostic brains tend HIGH; in-pattern read-only surfaces can be MEDIUM — but a
>     named human owns the tier; risk escalates **up, never down**, and `llm_powered` channels floor at
>     HIGH). The final tier is re-confirmed per spec at `/sdlc-spec` time.
> (3) Which unmade product choices become **decision-log** items (the agent never answers these).

5. **Open decision-log items:** For each undecided product choice the human named, append an entry to
   the phase-spanning decision-log (`templates/phases/01-requirements/decision-log.md` shape) with a
   **named owner** and a **2-business-day clock**. Workflow mode writes `.sdlc/decision-log.md`;
   standalone writes `<repo>/decision-log.md` (or `--output`'s directory). Surface the open + overdue
   items (the command owns this read):
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/track_decisions.py \
     --state .sdlc/state.yaml --json
   ```
   In standalone mode pass `--repo <repo-root>` instead of `--state`. The script is advisory (exit 0);
   `/sdlc-status` surfaces the same open/overdue list.

6. **Report:**
   ```
   Feature Brief Drafted
   =====================
   Brief:        .sdlc/artifacts/01-requirements/feature-brief.md
   Epic:         EP-... (feature FE-...)
   Decomposition: N specs (X channel-agnostic brains, Y per-channel surfaces) — risk mix confirmed
   Decisions:    M opened on the decision-log (owners: …) | none
   Next: /sdlc-experience per surface (authors journeys + interaction spec), then /sdlc-spec +
         /sdlc-channel to build each row.
   ```

## Arguments

- No arguments: workflow mode — decompose against the current project's epic.
- `--repo <path>`: standalone mode — decompose in any repo with no `.sdlc/` present.
- `--epic <id>`: name the epic to decompose (otherwise inferred from `epics.md` or asked).
- `--output <path>`: override the output location for the brief (standalone).

## Important

- **The agent proposes; a named human decides.** The `feature-architect` never assigns a risk tier and
  never answers a decision-log item — both need a named human. Proposing is fine; deciding is not.
- `feature-brief.md` is an **optional** artifact — `/sdlc-gate` never requires it, so gates never demand
  it. An unfilled discipline section is an advisory flag; formal acceptance happens at the Phase-1 gate
  via the discipline sign-off captured in state.
- **One channel per spec.** A feature on N surfaces decomposes into per-surface specs plus channel-
  agnostic shared-logic specs — preserving one spec = one branch = one PR.
- The decision-log is **phase-spanning and distinct from a spec's per-spec Decision List**: it captures
  cross-cutting product decisions (owner + 2-day clock) *before* specs exist; a phase decision can later
  seed a spec's Decision List when it is specced.
- The chain closes on the spec's existing `source:` field (FR → EP → feature-brief → US → spec). The
  brief adds the missing feature tier; it changes no protected core.
