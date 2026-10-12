# /sdlc-next — Advance to Next Phase

Run exit gate checks for the current phase and advance to the next phase if all gates pass.

## Instructions

1. **Locate state file:** Look for `.sdlc/state.yaml` in the current project directory. If not found, tell the user to run `/sdlc-setup` first.

2. **Read state:** Load `.sdlc/state.yaml` to determine the current phase.

3. **Run gate checks:** Execute the gate checker for the current phase:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/check_gates.py --state .sdlc/state.yaml
   ```

4. **Evaluate results:**

   **If ANY MUST gate fails:**
   - Display the failure report
   - List specific blockers with remediation suggestions
   - Do NOT advance the phase
   - Generate the phase HTML report anyway (shows what's missing): `uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/generate_phase_report.py --state .sdlc/state.yaml --phase <phase-number>`
   - Automatically open the report in the user's default browser (`start` on Windows, `open` on macOS, `xdg-open` on Linux)
   - Suggest actions: create missing artifacts, fix incomplete content, etc.
   - **Offer smart repair:** "Would you like me to attempt auto-repair on the fixable issues?" If yes, spawn the `gate-repair` agent, then re-run gates. See `references/smart-repair.md` for what's repairable.

   **If all MUST gates pass (SHOULD/MAY may still have warnings):**
   - Display success message
   - Show any SHOULD/MAY warnings
   - Generate the final phase HTML report before advancing:
     ```bash
     uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/generate_phase_report.py \
       --state .sdlc/state.yaml --phase <phase-number>
     ```
   - Automatically open the report in the user's default browser (`start` on Windows, `open` on macOS, `xdg-open` on Linux)
   - **Confirm the sign-off questions first.** Each phase's exit gate carries questions only a person can answer, and the human ticks each one (in this conversation or in SDLC Studio, the desktop app — one shared record). Read where they stand:
     ```bash
     uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sign_off_confirmations.py status --state .sdlc/state.yaml --json
     ```
     If `all_confirmed` is false, at least one question is unconfirmed: **do not ask for sign-off yet.** Show each unconfirmed question with its pre-check from `stage_readiness.py --state .sdlc/state.yaml --json` (`judgement[].hint` — what the software could see, never a verdict) and ask the human, one question at a time via `AskUserQuestion`, whether they confirm it. Only when they say yes, record it:
     ```bash
     uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sign_off_confirmations.py confirm        --state .sdlc/state.yaml --question-id <id from status> --actor "<the name the human gave>"
     ```
     Never confirm a question yourself, never treat a hint as a yes, and never record a name the human did not give. A question the human declines stays unconfirmed and the phase does not advance; tell them what remains.
   - **Sprint slate outcome (advisory, Build only):** when the current phase is `build`, put one line
     beside the feature-complete declaration so the human declares with the last sprint's outcome in
     view. Read the most recently closed record in `.sdlc/sprints/SNN.md` (`state: closed`) and count
     its `## Close` table — `slate S07: 5 of 6 merged, 1 carried, 0 dropped`. If a sprint is still open,
     add its readiness from:
     ```bash
     uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py status --state .sdlc/state.yaml --json
     ```
     (`open sprint S08: N slated · M ready`). Skip silently when `.sdlc/sprints/` is absent or the
     JSON's `sprint` is `null`. This line informs the declaration; it never gates it — leaving Build
     stays a human call, and a sprint is never a phase gate.
   - **HITL GATE — Ask for explicit sign-off before advancing:** Present the phase summary (what was produced, key decisions made) and ask: "Does this look correct? Shall I advance to Phase N?" Do NOT call `advance_phase.py` until the human explicitly confirms.
   - **Optional — capture discipline sign-off(s):** After the human confirms the advance, use
     `AskUserQuestion` to offer (optionally) recording per-discipline sign-off on this phase's work:
     "Any discipline sign-offs to record for this phase? (e.g. Design signs the interaction specs,
     Data signs the data contract, Bizreq signs the business rules.)" This is **optional** — skipping
     it advances exactly as before. For each sign-off the human names, capture a
     `Discipline:Section:Name` triple; capture the overall signer name too if given. These feed the
     `advance_phase.py` invocation in step 6 via `--signed-by "<name>"` and one
     `--discipline-signoff "Discipline:Section:Name"` per sign-off (repeatable). No sign-offs → no
     flags → byte-identical state. The named human signs; the agent only records what it is told.

5. **Generate (or regenerate) the Phase Layer:** After HITL sign-off, before advancing state. The
   layer is a living summary — the same procedure regenerates it later whenever a source artifact
   changes (see `references/frozen-layers.md`, "Living, not frozen"):
   1. Read ALL artifacts in `.sdlc/artifacts/{NN}-{phase-name}/`
   2. Read the frozen layer template from `${CLAUDE_PLUGIN_ROOT}/templates/frozen-layer.md`
   3. Condense all artifact content into the template structure, targeting 1500–2000 tokens:
      - Extract locked metrics (budget, timeline, scope, stakeholders) with explicit values
      - Summarize constraints, risks, and key outcomes
      - Fill the traceability footer mapping each source artifact to sections extracted
      - Fill YAML frontmatter with phase metadata and estimated token count (word_count × 1.3)
   4. If a layer already exists for this phase (from a prior completion or a refinement refresh), rename it to `{name}.superseded-<YYYYMMDD>` before writing the new one — history is kept, the hook loads only the current file
   5. Write the frozen layer to `.sdlc/context/layers/phase{N}-{name}.md`
   6. Validate:
      ```bash
      uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/validate_frozen_layer.py \
        --state .sdlc/state.yaml --phase <phase-number>
      ```
   7. If validation fails, fix issues and re-validate before proceeding
   8. See `references/frozen-layers.md` for format details and condensation strategy

6. **Advance phase:**

   - **First, snapshot the artifact ledger (advisory, exit 0):** capture any direct edits to this
     phase's artifacts before they freeze, so the change history and staleness stay current even for
     edits made outside `/sdlc-revise`:
     ```bash
     uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py record --scan --state .sdlc/state.yaml
     ```
     This appends only to `.sdlc/metrics/artifact-log.jsonl` (the audit trail) and captures each
     changed artifact's **content** lockstep into the local version store (`.sdlc/versions/`), so the
     edit is diffable and roll-back-able via `/sdlc-version`. Content capture is best-effort — a store
     fault leaves the ledger append and this command byte-identical. It never modifies artifacts or
     `state.yaml`, and never blocks the advance. If the script is absent, skip it.

   - **Then, optionally surface merged-spec drift (advisory, exit 0):** if any specs reached
     `status: merged` during the loop just completed, offer to back-propagate what they shipped into
     the pre-Build artifacts. Run the read-only scan and, for any spec with drifted upstreams, suggest
     the human run `/sdlc-refresh detect --spec <path>`:
     ```bash
     uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py refresh scan --state .sdlc/state.yaml
     ```
     This writes nothing and never blocks — it only points at candidates a named human may choose to
     refresh. Skip silently if there are no merged specs or the script is absent.

   Then perform the advance via `advance_phase.py` (it applies the state updates below and records any
   discipline sign-offs captured in step 4 on the phase's existing sign-off record):
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/advance_phase.py \
     --state .sdlc/state.yaml --confirmed \
     [--signed-by "<name>"] \
     [--discipline-signoff "Design:interaction-specs:<name>"]   # repeatable; omit both if none
   ```
   The `--signed-by` / `--discipline-signoff` flags are **optional**; with neither, the resulting
   state is byte-identical to a no-flags advance. The script updates `.sdlc/state.yaml`:
   - Set current phase status to `completed` with `completed_at` timestamp
   - Set next phase status to `active` with `entered_at` timestamp
   - Increment `current_phase`
   - Update `phase_name`
   - Append transition to `history` array:
     ```yaml
     - from: <current_phase_id>
       to: <next_phase_id>
       at: "<ISO 8601 timestamp>"
       gate_results: { <summary of pass/fail> }
     ```

7. **BLOCKING HITL GATE — Surface and resolve open questions before ANY new-phase work:**

   This gate is **MANDATORY** and **BLOCKING**. You MUST complete it before proceeding to step 8 or writing any artifacts for the new phase. There are NO exceptions.

   **Procedure:**
   1. Read the handoff document that was just produced (e.g., `phase2-handoff.md` when entering Phase 2).
   2. Extract ALL Q-NN or AQ-NN items listed under "Open Questions", "What X Must Address", or any similar heading.
   3. Display them in a prominent, impossible-to-miss block:

      > ---
      > **BLOCKING: OPEN QUESTIONS MUST BE RESOLVED BEFORE PHASE N BEGINS**
      >
      > The following questions were raised during the previous phase. You MUST answer or confirm defaults for every item below. No artifacts will be written until all are resolved.
      >
      > | ID | Question | Needed by | Proposed default |
      > |----|----------|-----------|------------------|
      > | AQ-01 | [question text] | [who/what needs it] | [your proposed default based on project context] |
      > | AQ-02 | [question text] | [who/what needs it] | [your proposed default based on project context] |
      >
      > For each question: confirm the proposed default, adjust it, or provide your own answer.
      > ---

   4. For each open question, you MUST propose a reasonable default answer based on everything you know about the project (state.yaml, previous handoffs, artifacts, profile). NEVER leave a question without a proposed default.
   5. **WAIT for the user to respond.** Do NOT continue to step 8. Do NOT begin writing any artifacts. Do NOT summarize next steps as if work can begin.
   6. **Write questions to file for audit trail:** In addition to displaying questions in chat, write them to `.sdlc/artifacts/{NN}-{phase-name}/open-questions.md` with this format:
      ```markdown
      # Open Questions — Phase {N}: {Name}
      Generated: {ISO timestamp}
      Status: PENDING

      | ID | Question | Needed by | Proposed Default | Answer |
      |----|----------|-----------|------------------|--------|
      | AQ-01 | [question] | [who] | [default] | |
      | AQ-02 | [question] | [who] | [default] | |

      Instructions: Fill in the Answer column, then confirm with Claude.
      ```
      This creates a durable audit trail of every decision. For team projects, others can review and fill answers asynchronously.
   7. **WAIT for the user to respond.** Do NOT continue to step 8.
   8. If the user confirms or provides answers, update `open-questions.md` with answers and set Status to RESOLVED. Also record in the handoff document under a "Resolved Questions" section with timestamps.
   9. Only after EVERY open question has a confirmed resolution may you proceed to step 8.

   **If there are no open questions** in the handoff document, explicitly state: "No open questions found in the handoff. Proceeding to phase guidance." Then continue to step 8.

   **NEVER skip this gate.** NEVER start Phase N artifacts while open questions remain unresolved. Violating this gate undermines the entire HITL workflow.

8. **Show next phase guidance:** After advancing AND after the HITL gate in step 7 is fully resolved, display:
    - New phase name and description
    - Primary skills to use
    - Required artifacts to produce
    - Entry criteria (already met by advancing)
    - Reference to phase definition file for full details

    **Reminder: Do NOT begin writing any of these artifacts until the HITL gate (step 7) is fully resolved.** If you skipped step 7 or the user has not confirmed answers to all open questions, STOP and go back to step 7 now.

9. **Edge case — end of lifecycle:** Phase 9 (Monitoring) is NOT the last phase. When Phase 9's gates pass, advance normally — `advance_phase.py` moves the project to Phase C (`close`, Close & Transfer), which has its own exit criteria (final-handoff-report.md, harness-audit.md, close-gate-evidence.md, access-revocation-checklist.md, plus the observed close-gate, access-revocation, and harvest-PR checks). The project is complete only when the `close` phase's own exit criteria pass. If the project is already at `close` (the terminal phase — `terminal: true` in the registry), `advance_phase.py` reports "Engagement complete" and exits without changing state; congratulate the user and mention the post-SDLC re-entry points for future work.

## Important
- This command modifies state — it advances `current_phase` in state.yaml.
- Gate checks are mandatory — there is no `--force` flag. Use the override protocol documented in `references/validation-rules.md` for exceptional cases.
- The HITL gate in step 7 is **non-negotiable**. Open questions MUST be surfaced with proposed defaults and resolved with user confirmation before any new-phase artifact work begins.
