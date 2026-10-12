# /sdlc-enhance — Generate Narrative Enhancement

Generate stakeholder-friendly narrative companions for SDLC artifacts.

## Instructions

1. **Read state:** Load `.sdlc/state.yaml` to determine the current phase.

2. **Locate artifacts:** Find all files in `.sdlc/artifacts/{NN}-{phase-name}/`:
   - Include: `.md` files that are technical artifacts
   - Exclude: files already ending in `.narrative.md`
   - Exclude: artifacts that already have a `.narrative.md` companion (unless `--force` is specified)

3. **For each artifact to enhance:**
   - Spawn `narrative-enhancer` agents in **parallel** (single message with multiple Agent tool calls) — artifacts in the same phase are always independent
   - Provide each agent with:
     - Full path to the source artifact
     - Project profile context from `.sdlc/profile.yaml` (for audience awareness)
     - Reference to `references/narrative-patterns.md` for transformation rules
   - The agent writes `{artifact-name}.narrative.md` alongside the source file

4. **Report results:**
   ```
   Narrative Enhancement Complete
   ==============================
   Enhanced: X artifacts
   Skipped:  Y (already have narratives)

   Generated:
     - problem-statement.narrative.md (487 words)
     - success-criteria.narrative.md (623 words)

   Coverage: X/Z artifacts have narrative companions
   ```

## Arguments

- No arguments: enhance all artifacts in the current phase
- `[path]`: enhance a specific artifact (e.g., `/sdlc-enhance .sdlc/artifacts/01-requirements/requirements.md`)
- `--force`: regenerate narratives even if they already exist
- `--all-phases`: enhance artifacts across all completed phases (not just current)

## Important

- Narratives are **optional** — gate checks do NOT require them
- They are recommended before stakeholder reviews and phase transitions
- The `narrative-enhancer` agent handles all generation — do not write narratives inline
- Narratives are companions, not replacements for technical artifacts
- **No activity metrics in client-facing narratives** — the `narrative-enhancer` agent must never surface velocity, story points, PR/commit counts, lines of code, or "AI productivity" claims, even if a source artifact contains them. Outcomes and quality only (per the delivery standard).
