# /sdlc-coach — Interactive Phase Coaching

Start or continue a coaching conversation for the current SDLC phase. Coaching mode uses adaptive dialogue instead of rigid step lists to guide the user through phase requirements.

## Instructions

1. **Read state:** Load `.sdlc/state.yaml` to determine the current phase.

2. **Assess state:** Read all artifacts in `.sdlc/artifacts/{NN}-{phase-name}/`:
   - Which artifacts exist?
   - Which are complete vs. still containing placeholders?
   - What decisions remain unmade?

3. **Load context:**
   - Read `references/conversational-coaching.md` for coaching patterns and diagnostic questions
   - Read frozen layers from `.sdlc/context/layers/` for prior phase context
   - Read the phase definition from `phases/{NN}-{phase-name}.md` for requirements

4. **Begin coaching dialogue based on state:**

   **No artifacts exist → Opening mode:**
   - Greet with phase goal in one sentence
   - Ask the first 2-3 diagnostic questions from the phase's "Opening" section
   - Wait for responses before generating any artifacts

   **Some artifacts exist → Progress mode:**
   - Acknowledge what's done ("I see your problem statement and constraints are in place")
   - Identify the most important gap
   - Ask targeted questions from the phase's "Progress Check" section

   **All required artifacts exist → Ready mode:**
   - Confirm all artifacts are present
   - Ask the "Ready Check" questions to validate confidence
   - Suggest running `/sdlc-gate` when the user is satisfied

5. **Respond adaptively to each user interaction:**
   - User provides information → generate or update the relevant artifact, then ask the next question
   - User asks a question → answer from phase context and profile, then guide back to the gap
   - User is stuck → offer 2-3 concrete suggestions based on the state assessment
   - User wants to skip ahead → warn about gate requirements, explain what's needed

6. **Track through artifacts:** The coaching conversation itself is ephemeral — artifacts are the record. After each significant exchange, update the relevant artifact so progress is preserved across sessions.

## Important

- Coaching **never** bypasses gates — it helps users get through them
- The coach always references the phase definition for what's required
- Adapt to the user's knowledge level based on their responses
- Use the coaching patterns in `references/conversational-coaching.md` — don't improvise a different structure
- If the user explicitly asks for the step list instead, switch to `/sdlc` mode
