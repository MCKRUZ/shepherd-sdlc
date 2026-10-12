# /sdlc-revise — Change One Specific Artifact (and record why)

Adjust a *thing*, not a whole file. Artifacts already carry ids, so you revise `FR-012` or `BR-04`
or one section — the command routes the change to the discipline that owns it, records the why with
an owner and a clock, re-gates, and shows you exactly what the change put at risk.

```
/sdlc-revise FR-012
/sdlc-revise BR-04
/sdlc-revise requirements.md#non-functional-requirements
```

The **One Rule** holds throughout: the discipline agent **proposes** the change; a **named human
decides** it. No agent silently rewrites an artifact.

## Instructions

1. **Resolve mode and repo root:**
   - **Workflow mode** (default): look for `.sdlc/state.yaml`; pass `--state .sdlc/state.yaml` to the
     scripts. If not found, tell the user to run `/sdlc-setup` first.
   - **Standalone mode** (`--repo <path>`, or no `.sdlc/`): operate on the given repo. Note the
     missing engagement context in the change reason.

2. **Resolve the target — id first, heading fallback.**
   - If the argument is an id (`FR-012`, `BR-04`, `EP-3`, `US-007`, `SCEN-02`, `FE-01`, `ADR-004`),
     find the artifact that declares it.
   - If it is `file.md#heading-slug`, resolve to that file and section.
   - If it is a bare file, ask which section/id inside it the user means.
   - If ambiguous, **ask** (`AskUserQuestion`) — never guess which artifact.

3. **Preview the blast radius before you change anything:**
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py impact <target> --state .sdlc/state.yaml
   ```
   Show the human what depends on this target (declared vs. coarse) so they revise with eyes open.

4. **Interview to change it — route to the owning discipline agent.** The agent proposes concrete
   wording; the human confirms or edits.

   **Before applying the confirmed edit, snapshot the pre-image (advisory, exit 0)** so the change is
   reversible — this captures the artifact's *current* content into the local version store lockstep
   with the ledger:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py record --scan --state .sdlc/state.yaml
   ```
   Then apply the confirmed edit to the artifact file. (Step 5a's `record --event revised` then
   captures the post-image, so `/sdlc-version diff`/`rollback` sees both sides of the change.) Content
   capture is best-effort; if the store can't be written the ledger append is byte-identical.

   | Target | Owning discipline agent |
   |--------|-------------------------|
   | `FR-`, `NFR-`, `EP-`, `US-`, `requirements.md`, `epics.md`, `user-stories.md`, `non-functional-requirements.md` | `requirements-analyst` |
   | `BR-`, `business-rules.md`, `SCEN-`, `golden-scenarios.md` | `bizreq-analyst` |
   | `FE-`, `feature-brief.md`, the Spec decomposition | `feature-architect` |
   | user journey / surface layout / interaction spec for **web/visual** (ag-ui) | `visual-designer` |
   | user journey / turn-script / message-flow for **voice or chat** | `conversation-designer` |
   | `data-contract`, data-readiness, lineage-audit | `data-analyst` |

   If no discipline clearly owns it, do the edit conversationally with the user — the One Rule still
   holds (human decides).

5. **Record the why — ledger + decision-log (both, always):**

   a. Append the change to the artifact ledger:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py \
     record --artifact <path> --target <id> --event revised \
     --actor "<name>" --reason "<what changed and why>" --decision-ref DL-NN --state .sdlc/state.yaml
   ```

   b. Open a linked decision-log item so the change carries an **owner and a 2-business-day clock**.
      Read `.sdlc/decision-log.md`, allocate the next `DL-NN` (2-digit; if the file or its table is
      missing, create it from `${CLAUDE_PLUGIN_ROOT}/templates/phases/01-requirements/decision-log.md`),
      and append one row — the `id` must match the `--decision-ref` you passed above:

      ```markdown
      | DL-NN | Revised <target>: <what changed and why> | <owner name> | <today YYYY-MM-DD> | <today + 2 business days> | open |
      ```

      `track_decisions.py` then surfaces it in `/sdlc-status`; close it (`status: decided`) once the
      downstream ripple is dispositioned.

6. **Re-gate the affected phase** — dirty-tracking re-validates only the changed artifact:
   ```
   /sdlc-gate
   ```
   Run the gate for the phase the artifact belongs to and report PASS/FAIL. Fix any MUST failures the
   change introduced before moving on.

7. **Show impact and disposition the ripple.** Re-run the freshness view scoped to what this change
   touched and walk the human through each newly-stale downstream:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py impact <target> --state .sdlc/state.yaml
   ```
   For each downstream the human wants to resolve now, record the disposition (the only other write,
   and only to the ledger):
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/audit_artifacts.py \
     record --disposition <ACKNOWLEDGED|NOT_AFFECTED> \
     --downstream <file> --upstream <path> --owner "<name>" --reason "<why>" --state .sdlc/state.yaml
   ```
   - **Refreshed?** If you fix the downstream now (or re-run `/sdlc-revise` on it), you do **not**
     record anything — a later change hash proves it, so the next scan clears the item automatically.
     `REFRESHED` is derived, never typed.
   - `ACKNOWLEDGED` — accept the debt for now; **names an owner** or it still counts as debt.
   - `NOT_AFFECTED` — the change doesn't ripple here; **give a reason** or it still counts.

8. **Report:**
   ```
   Revised <target> in <path>  (actor: <name>, DL-NN)
   Re-gate: PASS | FAIL (<blockers>)
   Impact: <N> downstream — <k> refreshed, <m> acknowledged, <j> open
   ```

## Arguments

- `<id | file#section | file>`: the thing to revise (id preferred — stable; heading slug is a fallback).
- No target: ask the user what to revise.
- `--repo <path>`: standalone mode (no `.sdlc/` present).

## Important

- `/sdlc-revise` writes **only** three things: the artifact, the change-ledger, and the decision-log.
  It **never** touches `state.yaml`'s gate results or sign-off records — advancing and sign-off remain
  `/sdlc-next`'s job, unchanged.
- **Agent proposes, human decides.** The discipline agent drafts the new wording; a named human
  confirms it and owns the decision-log item. This is the same One Rule as `/sdlc-spec`'s risk tier.
- **Staleness is advisory.** A downstream flagged after your change is a *candidate* — it may already
  account for the change. Disposition it; the tool never blocks on it.
- When behavior changes, the artifact changes here — and if a spec or code already realizes it, that
  change belongs in the **same PR** as the code. A stale artifact lies to the next agent and human.
- **Undo path.** A revise that went wrong is reversible: `/sdlc-version diff <target> prev latest`
  shows what changed and `/sdlc-version rollback <target> prev` restores it (preview → named-human
  confirm), provided the pre-image was captured in step 4. The reverse direction — pulling a built
  spec's shipped reality *up* into these artifacts — is `/sdlc-refresh`.
