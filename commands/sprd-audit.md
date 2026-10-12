# /sdlc-audit — Gate Effectiveness Analysis

Analyze gate results across completed phases in the current project's `state.yaml` to identify which gates are useful and which are candidates for adjustment.

## Instructions

1. **Locate state file:** Look for `.sdlc/state.yaml` in the current project directory. If not found, tell the user to run `/sdlc-setup` first.

2. **Read state:** Load `.sdlc/state.yaml` and extract `gate_results` from every completed phase.

3. **Run audit analysis:** Execute the audit script:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_gates.py --state .sdlc/state.yaml
   ```

4. **Display results:** Show the audit report with:
   - **Gate effectiveness summary** — table of every gate that was checked, how many times it ran, and how many times it failed
   - **Always-pass gates** — gates that never failed across all phases (candidates for removal or tightening)
   - **High-fail gates** — gates that failed frequently (may indicate process issues or overly strict thresholds)
   - **Override history** — any gates that were overridden, with justification text
   - **Recommendations** — suggested actions based on the analysis

5. **Optionally compare profiles:** If `--compare <other-state.yaml>` is provided, compare gate effectiveness between two projects.

## Arguments
- No arguments: audit current project
- `--compare <path>`: compare with another project's state.yaml

## Important
- This command is **read-only** — it analyzes existing data, never modifies state.
- Useful gate auditing requires at least 3-4 completed phases to have meaningful data. If fewer phases are complete, warn the user that results may not be representative.
