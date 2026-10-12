# /sdlc-review — Multi-Perspective Artifact Review

Run a structured review of the current phase's artifacts from multiple perspectives.

## Instructions

1. **Read state:** Load `.sdlc/state.yaml` to determine the current phase.

2. **Read artifacts:** Load all artifacts in `.sdlc/artifacts/{NN}-{phase-name}/`.

3. **Determine mode** from arguments:
   - `--council` (default) — 7-viewpoint review (Architecture, Product, Quality, Security, Design, Data, Bizreq)
   - `--adversarial` — Cynical QA perspective, challenge every assumption
   - `--edge-cases` — Exhaustive path analysis, find unhandled conditions
   - `--all` — Run all 3 modes sequentially, produce a combined report

4. **Spawn the `multi-reviewer` agent** via the Agent tool:
   - Provide all artifact paths and the selected mode
   - Include profile context from `.sdlc/profile.yaml` for stack/quality awareness
   - Include frozen layers from `.sdlc/context/layers/` for cross-phase context

5. **Display findings summary:**
   ```
   Review Complete — Phase 2: Design (council mode)
   ================================================
   CRITICAL: 0 | HIGH: 2 | MEDIUM: 4 | LOW: 1

   Top findings:
   1. [HIGH] No rollback strategy defined for database migration (Architecture)
   2. [HIGH] Auth token refresh not specified for offline scenarios (Security)

   Full report: .sdlc/artifacts/02-design/review-report.md
   ```

6. **Record the findings** so they survive the next review (the report itself is overwritten each run):

   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/record_findings.py record \
     --report .sdlc/artifacts/{NN}-{phase}/review-report.md --state .sdlc/state.yaml
   ```

   This parses the report's `## Gate Results` block into the append-only ledger
   `.sdlc/metrics/findings-log.jsonl`, so a finding's disposition can be tracked across rounds and a
   recurring class of finding becomes visible over time. Then surface the standing picture:

   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/record_findings.py report --state .sdlc/state.yaml
   ```

   Show the **open HIGH+ debt count** and any **FIXED_CLAIM_MISMATCH** (a finding marked fixed whose
   file never changed) in your summary to the user.

7. **If CRITICAL or HIGH findings exist:** Recommend addressing them before running `/sdlc-gate`. These are likely to surface as gate failures.

## Arguments

- No arguments: run `--council` mode on current phase
- `--adversarial`: adversarial review mode
- `--edge-cases`: edge case hunting mode
- `--council`: multi-perspective council mode (default)
- `--all`: run all 3 modes, combined report
- `<phase-number>`: review a specific phase (e.g., `/sdlc-review --adversarial 2`)

## When to Use

- **Phase 2 (Design):** `--council` to validate architecture from multiple angles
- **Phase 3 (Foundation):** `--edge-cases` to find gaps in the walking-skeleton spec and the risk-tier map
- **Build loop:** `--adversarial` + `--edge-cases` on a spec or hardening pass — there is no separate Quality phase; checking happens per change inside the loop
- **Any phase:** before running `/sdlc-gate` to catch issues early

## Important

- Reviews are **advisory** — the grader advises, it never blocks (the-rails.md §4). Findings do not
  gate advancement; the open HIGH+ debt count is surfaced so the human Checker can weigh it at the
  merge bar.
- The one factual exception is the **FIXED-claim check**: a finding marked FIXED whose target file
  never changed is a false claim. `record_findings.py report --strict` exits non-zero on it — the
  honesty check may block because it's a fact, not a judgment.
- Findings persist in `.sdlc/metrics/findings-log.jsonl` across runs even though `review-report.md`
  is overwritten — that ledger is what later makes a recurring finding promotable into a permanent
  check (Phase C: "findings become new checks").
- The review report is written as an artifact that stakeholders can review
- Running `/sdlc-review --all` before `/sdlc-next` is recommended for design-heavy phases
