# /sdlc-phase-report — Generate Phase HTML Report

Render all artifacts for the current (or specified) phase into a self-contained HTML report for stakeholder review.

## Instructions

1. **Locate state file:** Look for `.sdlc/state.yaml` in the current project directory. If not found, tell the user to run `/sdlc-setup` first.

2. **Determine target phase:**
   - No argument → use `current_phase` from state file
   - Phase-id argument (e.g., `/sdlc-phase-report 2`) → use that phase id
   - Validate the id against the registry (`0`, `1`, `2`, `3`, `build`, `7`, `8`, `9`, `close`)

3. **Run report generator:**

   For a single phase:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/generate_phase_report.py \
     --state .sdlc/state.yaml \
     --phase <phase-id>
   ```

   The output defaults to `.sdlc/reports/<slug>-report.html`, where `<slug>` is the phase's registry
   slug (e.g. `00-discovery-report.html`, `build-report.html`); pass `--output` only to override it.

   For all phases (produces individual reports **and** `index.html`):
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/generate_phase_report.py \
     --state .sdlc/state.yaml \
     --all
   ```

   Where `${CLAUDE_PLUGIN_ROOT}` is the environment variable Claude Code sets to the plugin's install directory.

4. **Handle output:**
   - On success: automatically open the report in the user's default browser:
     ```bash
     start .sdlc/reports/<slug>-report.html    # Windows
     open .sdlc/reports/<slug>-report.html     # macOS
     xdg-open .sdlc/reports/<slug>-report.html # Linux
     ```
   - On failure: display the error from the script and suggest checking that artifact files exist

5. **Update project index:** After generating the phase report, create or update `.sdlc/reports/index.html`:
   - If `index.html` does not exist: create it with project header, mission, constitution link, and all 9 phases (0, 1, 2, 3, build, 7, 8, 9, close) showing current status
   - If `index.html` exists: update the phase status badges, dates, and report links to reflect current state
   - The index is the single entry point for all project documentation

6. **Show artifact inventory:** After generating, list what was included:
   - Which required artifacts were found and rendered
   - Which required artifacts were missing (shown as placeholder sections in the report)
   - Exit gate status (pass/fail/incomplete)

## Arguments

- No argument: generate report for current phase
- `<phase-id>`: generate report for a specific phase (`0`–`3`, `build`, `7`–`9`, `close`)
- `--all`: generate reports for all phases and output an index HTML

## Output Location

Reports are written to `.sdlc/reports/` in the target project directory:
- `<slug>-report.html` for individual phase reports (e.g. `00-discovery-report.html`, `build-report.html`)
- `index.html` for the full project report (with `--all`)

## Notes

- Reports are self-contained single-file HTML (CSS and JS inlined)
- Stakeholders can open them directly in a browser — no server required
- Missing artifacts appear as labeled placeholder sections (not errors)
- The report includes exit gate status to show phase readiness
