# /sdlc-retro — Cross-Ledger Retro Roll-up

Read across the three advisory ledgers at once and surface **what keeps happening** — the retro
question the per-round commands can't answer on their own. It reports four patterns:

1. **Recurring findings** — a `(category, target)` group seen in **>= 2 distinct review rounds** is a
   candidate for a permanent check (this is how "findings become new checks").
2. **Repeat-stale artifacts** — per downstream artifact, how many times it was dispositioned for
   staleness, and whether it is stale **right now**.
3. **Refresh funnel** — per merged spec and by upstream stem: candidates → drifted → refreshed →
   rejected → still open. This doubles as the **tuning signal for the divergence heuristic**.
4. **Disposition debt rollup** — combined honest-counting debt across all three ledgers, each line
   naming its source.

When the sprint team layer's ledger (`.sdlc/metrics/sprint-log.jsonl`, written by `/sdlc-sprint`)
holds at least one event, two more sections appear after the debt block — keyed by spec, lane, and
reason, never by person:

5. **Carry-over recurrence** — per spec, how many *distinct* sprints it was carried out of, with each
   `S06 → S07: reason`; a spec carried out of **>= 2 sprints** is flagged `RECURRING`. This is the
   **only** cross-sprint number the plugin shows — there is deliberately no kept/carried trend
   ("velocity with the points removed").
6. **Bounce causes** — `returned` verdicts grouped by lane (eng, then data) and reason category, with
   the specs each cause touched; rendered only when at least one return exists.

This is a **sibling** to `/sdlc-audit-artifacts` (freshness *now*) and `/sdlc-audit` (gate
effectiveness). This command reads the accumulated *history* and reports the recurring shape of it.
It reads the ledgers, computes nothing about people, and never blocks.

## Instructions

1. **Resolve mode and repo root:**
   - **Workflow mode** (default): look for `.sdlc/state.yaml`. Pass `--state .sdlc/state.yaml`. If
     not found, tell the user to run `/sdlc-setup` first.
   - **Standalone mode** (`--repo <path>`, or no `.sdlc/` found): run against any repo with a
     `.sdlc/` directory. The roll-up is only as deep as the ledgers in that repo — with a thin or
     missing ledger, each section degrades to **"no data"** (never a fabricated zero), and the
     missing context is noted by that "no data" line rather than guessed at.

2. **Run the roll-up** (read-only — writes nothing, ever):
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/retro_report.py --state .sdlc/state.yaml
   ```
   In standalone mode point it at any repo instead:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/retro_report.py --repo /path/to/repo
   ```

3. **Scope by window** (optional). Limit the time-stamped ledger events (finding rounds, refresh /
   reject events, staleness dispositions) to the last N days. Current-state facts — whether an
   artifact is stale *now*, and the debt rollup — always reflect the present regardless of the window:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/retro_report.py --state .sdlc/state.yaml --window-days 30
   ```

4. **Machine-readable output** for dashboards or a client artifact:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/retro_report.py --state .sdlc/state.yaml --json
   ```
   The JSON has a stable top-level shape: `has_data` (a bool per section), `recurring_findings`,
   `repeat_stale`, `refresh_funnel` (`by_spec` + `by_stem`), `debt`, `window_days`, plus the sprint
   sections `carry_over_recurrence` (rows `{spec, carried, sprints, carries, reasons, flagged}`),
   `bounce_causes` (rows `{lane, reason, times, specs}`), and `sprint_ledger_present`. With no sprint
   ledger both lists are empty and their `has_data` flags are false — "no data", never a fabricated 0.

5. **Act on the patterns** (a human's call — this command only surfaces them):
   - A **recurring finding** across rounds is the promotion signal: consider turning it into a
     permanent check (a spec DoR rule, a gate, a lint) so it stops recurring.
   - A **repeat-stale artifact** flagged again and again is a lineage or ownership smell — the
     upstream keeps moving under it. Disposition it in `/sdlc-audit-artifacts`, or fix the source.
   - The **refresh funnel** tunes the divergence heuristic (see below).

## How to read the refresh funnel

The funnel is the **tuning signal for the divergence heuristic** in the refresh layer — the
conservative, deliberately-imperfect drift detector. Read each upstream **stem** line:

- **High rejected / low applied** ("4 rejected / 0 applied") — the heuristic is flagging drift that
  humans keep judging *not affected*. The signal is **noisy** for that stem; the heuristic is too
  eager there.
- **Candidates that never drift** ("0 of N candidates ever drifted") — the heuristic almost never
  fires. The signal may be **too tight (quiet)**; real drift could be slipping through unflagged.
- A healthy stem lands somewhere between: some drift detected, some applied, few rejected.

It is a signal to *tune the heuristic*, not a verdict on anyone's work.

## Arguments

- No arguments: full roll-up over all history (workflow mode, `--repo .`).
- `--state <path>`: workflow mode — the `.sdlc/` beside the state file.
- `--repo <path>`: standalone mode — any repo with a `.sdlc/` present.
- `--window-days <N>`: only count time-stamped ledger events from the last N days.
- `--json`: emit the stable JSON shape with per-section `has_data` flags.

## Important

- The user runs `/sdlc-retro` — never `retro_report.py` by hand. The command owns mode resolution and
  the windowing.
- **Read-only. Writes nothing** — no ledger appends, no `state.yaml`, no artifacts, no files. It is a
  pure read across `findings-log.jsonl`, `artifact-log.jsonl`, and — when present — `sprint-log.jsonl`.
  Re-gating and dispositioning stay where they live (`/sdlc-gate`, `/sdlc-revise`,
  `/sdlc-audit-artifacts`); carrying and dropping stay in `/sdlc-sprint close`.
- **Patterns, not people.** Every pattern is keyed by category, artifact, upstream stem, spec, lane,
  or reason — **never by actor** (the sprint ledger's `by` field is never read). There is deliberately **no flag to rank by person**, in the same spirit as the steering
  scorecard's forbidden metrics: this command never reports velocity, story points, PR count, or
  lines of code, and never attributes a pattern to an individual.
- **Advisory by construction** — `retro_report.py` exits 0 on every path (no stack traces). A
  recurring pattern is a prompt for a human's judgement, never a gate.
