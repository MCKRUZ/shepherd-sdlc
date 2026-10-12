# /sdlc-handoff — Hand a Ready Spec to a Developer

Turn hand-off into one step: create the spec's branch, set its `status`/`developer`
frontmatter, assign the developer on the code host (and request a review from the spec's
checker, when one is set), and optionally start Claude Code on that branch in plan mode.
This is the Delegate beat's tool — the moment the loop's roles change hands.

## Instructions

1. **Resolve mode and repo root:**
   - **Workflow mode** (default): look for `.sdlc/state.yaml`. The repo root is the
     directory containing `.sdlc/`.
   - **Standalone mode** (`--repo <path>`, or no `.sdlc/` found): operate on the given repo.

2. **Confirm the spec and developer with the user** if either wasn't given explicitly — do
   not guess who a spec should go to.

3. **Run the hand-off** (the command owns the script — the user never calls it directly):
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/handoff.py \
     --repo <repo-root> --spec <repo-root>/specs/NNNN-name.md --developer @handle
   ```
   In workflow mode pass `--state .sdlc/state.yaml` instead of `--repo`.

   The assignment step speaks to whichever code host the repository's `origin` remote is on —
   GitHub through `gh`, Azure DevOps through `az` (with the `azure-devops` extension). Detection
   is automatic; pass `--host github|azure-devops|none` only when the user asks to override it
   for this one run (`none` tries `gh`, as before). Do not add it to work around a CLI that is
   missing or signed out — the script already reports that as the assignment failure.

   - **Refused** — the script prints exactly what blocked it (not ready, unknown developer,
     developer is also the checker, team at its WIP limit) and changes nothing. Fix the
     named issue and re-run; do not work around a refusal by editing the spec's frontmatter
     by hand — the refusal exists because the script is about to act on that data.
   - **Team at its WIP limit** — do not add `--over-limit` yourself. Tell the user the team
     is at capacity and ask whether to proceed anyway; only add
     `--over-limit "<their reason>"` on their explicit say-so, and use their own words as
     the reason (it is written into the commit message).
   - **Already in flight** — the script reports the developer already on file and changes
     nothing. This is not an error; report it plainly.
   - **On Azure DevOps, `assignment_error` with the PR still opened** — Azure DevOps names
     reviewers by sign-in identity, not by handle, so the checker becomes a required reviewer
     only when their roster entry in `.sdlc/team.yaml` carries an `email:`. Without one the
     draft PR opens with the gap written into its description and the script reports an
     `assignment_error`; the hand-off itself succeeded. Tell the user to add the checker's
     `email:` (`set_setting.py person @handle --email …`) and request the review by hand this
     once. The developer is named in the PR description — Azure DevOps has no assignee.

4. **Starting the agent:** ask whether to start Claude Code on the branch now.
   - Yes → re-run with `--open` added. This starts a new Claude Code session in plan mode
     with the spec named — it hands off actual control of the terminal, so only do this
     when the user is ready to move to that branch now.
   - No / later → report the exact command the script printed, so the user (or the
     developer) can run it themselves when ready.

5. **Report:**
   ```
   Handed off: spec/NNNN-name -> @handle
   PR: <url> (review requested: @checker) | assignment failed: <reason, if any>
   Next: <the printed command, or "Claude Code starting now">
   ```

## Arguments

- `--spec <path>`: the spec to hand off (required if not already clear from context).
- `--developer <@handle>`: who it's going to (required if not already clear from context).
- `--repo <path>`: standalone mode.
- `--over-limit "<reason>"`: only on the user's explicit instruction (see step 3).
- `--open`: start Claude Code on the branch immediately after a successful hand-off.
- `--host github|azure-devops|none`: override code-host detection for this run only (the
  default follows `origin`, then `SDLC_CODE_HOST`, then `.sdlc/code-host.yaml`).
- `--json`: the outcome — including a refusal and its `kind`, and any `assignment_error` — as
  one JSON document carrying the top-level `host` block.

## Important

- The user runs `/sdlc-handoff` — never `handoff.py` by hand.
- Every refusal leaves the repository untouched — a half-done hand-off (branch created,
  frontmatter not committed, or vice versa) is worse than none. Never retry a refused
  hand-off by fixing only the symptom the script prints without addressing why the
  refusal fired (e.g. don't hand-edit `status: in-flight` into the spec to skip the DoR
  check — that both defeats the check and desyncs from what the script itself would write).
- A hand-off with no code-host access still completes its local half (branch pushed,
  frontmatter committed) — it reports the assignment failure, it does not fail outright.
  Tell the user to assign the PR manually once access is available. "No access" means the
  repository's own CLI — `gh` on GitHub, `az` on Azure DevOps — is missing, lacks its extension,
  or is signed out; the message names which, and never asks for the other host's CLI.
- Owner and developer can be the same person on a small team — only owner-as-checker is
  refused. Do not second-guess a hand-off to the spec's own owner.
