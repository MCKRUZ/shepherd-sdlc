# /sdlc-brief — Generate the Discovery Workshop Brief

Run cross-document analysis on the intake corpus and draft the one-page workshop brief, with
the human curating what makes the page. Works inside an SDLC project or standalone against any
folder of documents.

## Instructions

1. **Resolve context:**
   - If `.sdlc/state.yaml` exists: workflow mode. Corpus is the locked intake catalog
     (`.sdlc/context/intake/`); outputs go to `.sdlc/artifacts/00-discovery/`.
   - If not (or `--docs <path>` given): standalone mode. Corpus is the given folder; outputs
     go alongside it. Note in output headers that DOC-NNN IDs are provisional.

2. **Ensure intake exists (workflow mode):** If the catalog or per-document summaries are
   missing, stop and tell the human to run document intake first (Phase 0, Step 0c) — the
   brief is built on the summaries, not raw files. In standalone mode, read the documents
   directly.

3. **Run the analysis:** Spawn the `discovery-analyst` agent to produce `contradiction-list.md`
   and `question-list.md` (templates in `templates/phases/00-discovery/`). Skip if both exist
   and `--refresh` was not given.

4. **Curate with the human:**

> **HITL GATE:** Present the analysis to the human using the `AskUserQuestion` tool — this is
> the step that makes the brief curated rather than generated. Ask:
> (1) Which contradictions make the one page? (show all `blocks-outcome` and `shapes-design`
> entries with their resolving questions; recommend the top 3-5)
> (2) Which questions make the one page? (show the workshop-routed list; recommend 8-12 across
> the agenda blocks; confirm the pre-workshop-routed ones get emailed instead)
> (3) What are the 3-5 decisions the room must leave with?
> (4) Logistics: date/time/location, attendees with roles, duration, facilitator.

5. **Draft the brief:** Fill `templates/phases/00-discovery/workshop-brief.md` with the curated
   content. Hard rules from the template: one page above the appendices; questions only — no
   proposed outcomes, metrics, or solutions; every claim carries a DOC-NNN reference.

6. **Report:**
   ```
   Workshop Brief Drafted
   ======================
   Brief:           .sdlc/artifacts/00-discovery/workshop-brief.md
   Contradictions:  N total (X blocks-outcome, Y shapes-design) — Z on the page
   Questions:       N total — Z on the page, W routed pre-workshop (email these now)
   Next: Pod Lead edits, then sends to attendees. The brief is not sent by this command.
   ```

## Arguments

- No arguments: workflow mode against the current project's intake
- `--docs <path>`: standalone mode against a folder of documents
- `--refresh`: re-run the discovery-analyst even if analysis artifacts exist
- `--output <path>`: override the output location for the brief

## Important

- **The command drafts; the Pod Lead sends.** Never deliver the brief to anyone — the human
  reviews and distributes it.
- The brief proposes no outcomes. If a draft section reads like an answer instead of a
  question, rewrite it as the question.
- `Q-NN` and `CON-NN` IDs are stable once the brief is published — they persist into the
  workshop's answer log and `phase1-handoff.md`.
- These artifacts are optional for gate purposes: `/sdlc-gate` does not require them, but a
  multi-stakeholder engagement that skips them is flying blind into its workshop.
