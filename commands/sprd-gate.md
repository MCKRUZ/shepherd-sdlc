# /sdlc-gate — Run Exit Criteria Check

Run the 7-gate validation system for the current (or specified) SDLC phase without advancing.

## Instructions

1. **Locate state file:** Look for `.sdlc/state.yaml` in the current project directory. If not found, tell the user to run `/sdlc-setup` first.

2. **Read state:** Load `.sdlc/state.yaml` to determine the current phase.

3. **Check visual report exists:** Before running gates, verify that the phase visual report exists at `.sdlc/reports/<slug>-visual.html`, where `<slug>` is the phase's registry slug (e.g. `00-discovery-visual.html`, `build-visual.html`). Also verify that artifact sub-pages exist and are linked from the main report.
   - If the visual report is **missing**: STOP. Tell the user: "The phase visual report has not been generated yet. The visual report is the primary stakeholder review artifact and must exist before running gate checks. Generate it now?" If yes, generate the visual report with artifact sub-pages first, then proceed with gates.
   - If sub-pages are **missing**: WARN but proceed. Note which artifacts lack sub-pages in the gate output.

4. **Run gate checks:** Execute the gate checker:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/check_gates.py --state .sdlc/state.yaml
   ```
   Optionally specify a phase: `--phase <N>`

5. **Display results:** Show each gate result with:
   - Gate name (G1-integrity, G2-completeness, G3-metrics, G4-compliance, G5-consistency, G6-quality, G7-exit-criteria)
   - PASS / FAIL / MANUAL status
   - Severity (MUST / SHOULD / MAY)
   - Details on what passed or failed

6. **Generate phase report:** Always generate the HTML report after running gates, regardless of pass/fail status:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/generate_phase_report.py \
     --state .sdlc/state.yaml --phase <phase-number>
   ```
   The script writes `.sdlc/reports/<slug>-report.html` (registry slug, e.g. `00-discovery-report.html`,
   `build-report.html`). After generating, automatically open the report in the user's default browser:
   ```bash
   start .sdlc/reports/<slug>-report.html    # Windows
   open .sdlc/reports/<slug>-report.html     # macOS
   xdg-open .sdlc/reports/<slug>-report.html # Linux
   ```
   This is the artifact stakeholders review before the manual gate sign-off.

7. **Update index:** After generating the phase report, update `.sdlc/reports/index.html` with the current phase status and report link. If `index.html` does not exist, create it.

8. **Smart Repair (optional):** If MUST gates failed, offer the user: "Would you like me to attempt auto-repair on the fixable issues?"
   - If yes: spawn the `gate-repair` agent with the failure list
   - The agent classifies failures as repairable vs. not, fixes what it can, and reports changes
   - Re-run gate checks on repaired artifacts
   - Show the human what was repaired and what still needs manual attention
   - See `references/smart-repair.md` for what's auto-repairable vs. not

9. **Summarize:** At the bottom:
   - Count of passed / failed / manual checks
   - If any MUST gates failed: **BLOCKED** — list specific blockers with remediation suggestions
   - If only manual checks remain: **REVIEW NEEDED** — list what needs human verification. Remind the user to share the HTML report for stakeholder sign-off.
   - If all pass: **READY** — suggest running `/sdlc-next` to advance

10. **Update state:** Record gate results in `.sdlc/state.yaml` under the current phase's `gate_results` field. Do NOT advance the phase — that's `/sdlc-next`'s job.

## Dirty Tracking

Gate checks use artifact checksums to skip re-validation of unchanged files. The first run validates everything. After `advance_phase.py` snapshots checksums on phase completion, subsequent runs in the new phase only fully check new or modified artifacts — unchanged artifacts are reported as PASS (skipped).

To manually snapshot checksums (create a baseline without advancing):
```bash
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/track_artifacts.py \
  --state .sdlc/state.yaml --snapshot
```

## Arguments
- No arguments: check current phase
- `<phase-number>`: check a specific phase (e.g., `/sdlc-gate 2`)

## Important
- This command is **read-only with respect to phase transitions** — it records gate results but never changes `current_phase`.
- Use `/sdlc-next` to actually advance after gates pass.
