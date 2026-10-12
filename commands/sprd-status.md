# /sdlc-status — SDLC Progress Dashboard

Display the current SDLC progress for this project.

## Instructions

1. **Locate state file:** Look for `.sdlc/state.yaml` in the current project directory. If not found, tell the user to run `/sdlc-setup` first.

2. **Read state:** Load `.sdlc/state.yaml` to get current phase, phase statuses, and history.

3. **Generate dashboard:** Run the status generator:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/generate_status.py --state .sdlc/state.yaml
   ```

4. **Display:** Show the generated dashboard to the user. Include:
   - Current phase name and number
   - Progress bar (completed phases / total)
   - Phase table with status, artifact count, timestamps
   - Recent transition history (if any)

5. **Channel rollup + decision-log:** Two additive reads that surface the multi-discipline layer
   without touching `generate_status.py`:

   - **By-channel spec backlog** — derive the per-channel rollup from spec frontmatter:
     ```bash
     uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/track_specs.py --state .sdlc/state.yaml --json
     ```
     Render the `by_channel` block (spec counts per delivery surface; `channel-agnostic` and
     `unassigned` are first-class buckets). If the JSON has no `by_channel` key or every spec is
     `unassigned`, skip this — no project has bound a `channel:` yet.

   - **Open + overdue decisions** — surface the phase-spanning decision-log:
     ```bash
     uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/track_decisions.py --state .sdlc/state.yaml --json
     ```
     List **open** decisions and flag those **overdue** past the 2-business-day clock (owner + due
     shown). If `track_decisions.py` or `.sdlc/decision-log.md` is absent, read `.sdlc/decision-log.md`
     directly for open items, or skip silently if neither exists. Advisory only (exit 0) — never blocks.

   - **Artifact staleness rollup** — surface how many artifacts have drifted out of date with the
     things they depend on:
     ```bash
     uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py report --state .sdlc/state.yaml --json
     ```
     If `has_history` is true, render one line — `Artifacts: N stale (X acknowledged, Y open)` —
     using `stale`, `acknowledged`, and `open` from the JSON. If `has_history` is false (no ledger
     yet) or the script is absent, skip silently — no baseline has been recorded. Advisory only
     (exit 0) — never blocks. See `/sdlc-audit-artifacts` for the full dashboard.

   - **Merged-spec drift nudge** — surface pre-Build artifacts a merged spec implies an edit to
     (reverse propagation), so the drift is visible without anyone remembering to look:
     ```bash
     uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py refresh scan --state .sdlc/state.yaml --json
     ```
     If `drifted_total` is 0 (every merged spec is faithful) or there are no merged specs, skip
     silently. Otherwise, for each `results[]` entry with `drifted > 0`, render one nudge line —
     `↩ {drifted} upstream artifact(s) may have drifted from merged spec {spec} — /sdlc-refresh detect --spec {spec_node}`.
     Entries whose upstreams are all trace-only (`drifted == 0`) produce no line. If the script is
     absent, skip silently. Advisory only (exit 0) — never blocks. See `/sdlc-refresh` for the
     draft+confirm path.

   - **Active sprint** — one additive read of the sprint team layer:
     ```bash
     uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/sprint.py status --state .sdlc/state.yaml --json
     ```
     If `sprint` is `null` (no sprint record exists) or the script is absent, skip silently. Otherwise
     render one line from the JSON — `Sprint S07 (ends 2026-10-09): 6 slated · 4 ready · 1 verdict
     pending · 2 handoffs unacknowledged` — using `sprint.id`, `sprint.end`, `readiness.total`,
     `readiness.ready`, `len(verdicts_pending)`, and `len(handoffs_open)`. Read-only (exit 0) and
     advisory — a sprint never gates a phase. See `/sdlc-sprint` for the full board.

6. **Suggest next action:** Based on current phase status:
   - If phase is `active`: suggest running `/sdlc` for phase guidance
   - If all gates would pass: suggest running `/sdlc-next` to advance
   - If artifacts are missing: list what's needed

## Output Format

Use the markdown table format from `generate_status.py`. Keep it concise — the dashboard should fit in one screen.
