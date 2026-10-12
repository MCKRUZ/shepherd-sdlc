# /sdlc-evals — Author the Versioned Golden Set for an LLM-Powered Spec

Author the **golden set** — the acceptance criteria for probabilistic behavior — for a spec on an
`llm_powered` channel. Bizreq owns the scenarios, Data owns the data; the two are authored
collaboratively. This command is a thin **wrapper around the existing `eval-builder` harness skill**:
it adds **no new script**, authors **no CI YAML**, and writes a versioned `golden-set.yaml` next to the
spec. Interview-driven like `/sdlc-coach` at the collaboration and calibration steps — it proposes; a
named human decides. Works inside an SDLC project or standalone.

## Instructions

1. **Resolve context:**
   - **Workflow mode** (default): `.sdlc/state.yaml` exists. The repo root is the directory containing
     `.sdlc/`; read the target spec and its `golden-scenarios.md` (`SCEN-NN`) and `data-contract.md`.
   - **Standalone mode** (`--repo <path>`, or no `.sdlc/` found): operate on the given repo with
     provisional context; take scenarios/data from the paths given or asked for.

2. **Confirm the channel is `llm_powered`:** Read the target spec's `channel:` field and
   `channels/<channel>.yaml`. If `llm_powered: true`, **evals are required acceptance criteria** — the
   descriptor's `eval_hooks` name which dimensions become golden-set cases. If `llm_powered` is false or
   the spec has no channel, tell the human evals are advisory here and stop unless `--force` is given.

3. **Gather the inputs (collaborative):** Assemble the cases from **Bizreq's `SCEN-NN` golden scenarios**
   (the behaviors that must hold) and **Data's representative data** (real inputs from the manual
   pre-release checks and the bug/support queue, not invented cases), plus the descriptor's `eval_hooks`.
   Ask focused questions to fill gaps — which failures matter, what the reference answer is for each.

4. **Wrap the `eval-builder` skill (no new script):** Follow the `eval-builder` skill's procedure
   (`harness/skills/eval-builder/SKILL.md`, or the target repo's installed
   `.claude/skills/eval-builder`) — start from real failures small (20–50 tasks), pick graders
   **deterministic-first** (`state_check` / `transcript_constraint` over an `llm_rubric`, and grade the
   **output, not the trajectory**), compose multidimensional success where needed, and write the
   versioned `golden-set.yaml` next to the spec using the skill's shape. **The skill owns the output
   path and the template** — do not hardcode either here (it writes under
   `eval-datasets/specs/<feature>/`).

5. **Confirm the threshold and calibration with the human:**

> **HITL GATE:** Present the drafted golden set using the `AskUserQuestion` tool. Ask:
> (1) Confirm the **pass threshold** and **trial count** the spec requires (agents are stochastic — the
>     suite runs multiple trials from a clean, isolated environment).
> (2) Confirm the LLM judges have been **sanity-checked against human-graded cases** before the
>     regression trip-wire becomes a required check.
> The command proposes calibrated figures; a named human owns the gate.

6. **Report:**
   ```
   Golden Set Authored (llm_powered channel)
   =========================================
   Golden set: <path written by the eval-builder skill>  (versioned next to the spec)
   Cases:      N (from SCEN-NN + representative data); graders deterministic-first
   Threshold:  >= X%  ·  trials: T  ·  judges sanity-checked: yes
   Next: the golden set is the acceptance criteria — eval-regression fires on any prompt/model change.
   ```

## Arguments

- No arguments: workflow mode — author for the current project's spec.
- `--repo <path>`: standalone mode — author in any repo with no `.sdlc/` present.
- `--spec <path>`: the target spec (sets the channel and the golden-set location).
- `--feature <name>`: the feature slug the skill versions the golden set under (otherwise from the spec).
- `--force`: author a golden set even when the channel is not `llm_powered` (advisory case).

## Important

- **This command wraps the existing skill and touches no CI YAML.** It authors no new script; the
  `eval-builder` skill owns the procedure, the golden-set shape, and the output path. `eval-regression`
  and the eval rails are the existing harness — unchanged.
- **Evals are required for `llm_powered` channels** — for those channels the golden set *is* the
  acceptance criteria (invariant 8), not an optional extra.
- **Graders are deterministic-first and grade output, not path.** Use an `llm_rubric` only for what rules
  can't capture, and validate judges against human grades before gating.
- **Known path divergence (pre-existing, out of scope):** the `eval-builder` SKILL references the
  golden-set template at `kit/eval-datasets/golden-set.template.yaml`, but the shipped template lives at
  `harness/eval-datasets/golden-set.template.yaml`. Defer to the skill for the authoritative path; this
  divergence lives inside `harness/**` and is flagged for a separate fix, not resolved here.
