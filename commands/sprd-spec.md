# /sdlc-spec — Author a Ready Spec for the Build Loop

Turn a story into a **ready spec** (`specs/NNNN-name.md`) that clears the Definition of Ready
before anyone builds it. This is the Intent beat of the Build loop wrapped as one command: scaffold
→ author → enforce the DoR → confirm the risk tier with a human. No spec, no build.

The spec is the durable per-change record — one spec = one branch = one PR. It lives in the repo's
`specs/` directory (in version control, not only under `.sdlc/`), because the agent re-reads it every
session and the grader grades against it.

## Instructions

1. **Resolve mode and repo root:**
   - **Workflow mode** (default): look for `.sdlc/state.yaml`. The repo root is the directory
     containing `.sdlc/`. Read the spec backlog and `risk-tier-map.md` from Foundation for context.
   - **Standalone mode** (`--repo <path>`, or no `.sdlc/` found): operate on the given repo with
     provisional context. Note the missing engagement context in the spec's `source` field.

2. **Gather Intent.** From the story or the user's request, draft the spec content. Drive the
   Definition of Ready — do not let any of these stay implicit:
   - **Goal** — one sentence: what capability exists when this is done.
   - **Why** — the outcome that makes this worth building.
   - **Scope in / Scope out** — both stated. What the change must not touch is load-bearing.
   - **Acceptance checks** — each one testable. Apply the **vague-line test** to every line:
     *"Could two people build different things from this?"* If yes, rewrite it with a concrete
     value (a status code, a JSON body, a count, a path) until they couldn't.
   - **Silent decisions** — surface every unwritten product choice (fail open or closed? what does
     a blocked user see?) onto the spec's Decision List with a **named human owner** and an answer
     clock. The agent must not guess these.
   - **Harness context** — name the ONE existing pattern this change reuses, so the agent extends
     the codebase instead of inventing a second way to do something.

3. **Propose a risk tier — never assign it.** Recommend HIGH / MEDIUM / LOW from the risk taxonomy
   (`risk-tier-map.md`), with one sentence of justification, then get a human to confirm it.

   > **HITL GATE:** Use `AskUserQuestion`: "I propose **<TIER>** for this spec because <reason>.
   > HIGH = auth/data/migrations/API/infra/AI-behavior/hard-to-undo; MEDIUM = new logic /
   > integrations / shared services; LOW = UI-in-pattern / copy / internal tooling. Confirm or
   > override?" The Pod Lead owns the tier. Risk challenges escalate **up, never down**.

4. **Scaffold the file** (the command owns the script — the user never calls it directly):
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/new_spec.py \
     --repo <repo-root> --name "<short name>" --risk <CONFIRMED_TIER> --source "<story/REQ-id>"
   ```
   In workflow mode pass `--state .sdlc/state.yaml` instead of `--repo`. Then write the gathered
   Intent into the section bodies, replacing every `<...>` fill-marker and the `harness_context`
   frontmatter field.

5. **Enforce the Definition of Ready** (the mechanical floor + vague-line lint):
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/check_spec.py \
     --spec <repo-root>/specs/NNNN-name.md [--state .sdlc/state.yaml]
   ```
   - **BLOCK (MUST)** findings — fix them. The spec is not ready until they clear.
   - **ADVISE (SHOULD)** findings — the vague-line lint flags acceptance checks that *might* be
     wishes. Apply the real vague-line test to each: tighten it, or accept it with a reason. The
     lint surfaces candidates; the judgment is yours, exactly as the grader advises but never blocks.
   Re-run until the spec reads `READY`. With `--state`, each run logs to `.sdlc/metrics/spec-log.jsonl`.

6. **Report:**
   ```
   Spec ready: specs/NNNN-name.md
   Risk tier:  <TIER> (human-confirmed)
   Checks:     N acceptance checks, all past the vague-line test
   Decisions:  M surfaced to the Decision List (owners: …) | none
   Next: open branch spec/NNNN-*, start the agent in plan mode against this spec (Delegate beat).
   ```

## Arguments

- No arguments: workflow mode — author a spec in the current `.sdlc/` engagement.
- `--repo <path>`: standalone mode — author a spec in any repo with no `.sdlc/` present.
- `--spec <path>`: validate (and finish authoring) an **existing** spec instead of scaffolding a new
  one — runs steps 5–6 against the given file.

## Important

- The user runs `/sdlc-spec` — never `new_spec.py` or `check_spec.py` by hand. The command owns the
  scaffold, the authoring, the human risk-tier gate, and the DoR enforcement.
- **The agent never assigns the risk tier** and never answers a Decision List item — both need a
  named human. Proposing a tier is fine; deciding it is not.
- A ready spec is the prerequisite for the Delegate beat. Do not start building from a spec that
  `check_spec.py` reports as NOT READY — that is the "skipping Intent" failure the loop exists to kill.
- When behavior changes later, the spec changes **in the same PR** as the code. A stale spec lies to
  the next agent and the next human.
