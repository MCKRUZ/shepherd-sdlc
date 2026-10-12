# /sdlc-doctor — Day-1 Environment Check

Verify that the installed harness will actually run in this repo, and tell the developer exactly what to do about anything that won't.

The harness fails quietly. A hook registered with a missing interpreter, a rails script installed without its executable bit, a secret the gates read that nobody set — each leaves a repo that looks configured and has no working checking ladder. This command finds the failures that are invisible when they happen.

Run it after `/sdlc-setup`, when onboarding a second developer, and any time a gate behaves in a way nobody can explain.

## Instructions

1. **Run the check** from the repo root:
   ```bash
   uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py
   ```
   Add `--offline` to skip the checks that need the platform CLI — `gh` on GitHub installs (repo secrets, branch protection), `az` on Azure DevOps installs (variable groups, branch policies). Add `--repo <path>` to check a repo other than the current directory.

2. **Report the results verbatim.** Each line is already `PASS` / `FAIL` / `WARN` with the fix attached. Do not summarise away the fix lines — they are the actionable part.

3. **Explain what each failure means, in plain terms**, before offering to act. What matters is the consequence, not the check name:
   - *missing `pwsh`* — the hooks are registered but can never run, so an agent can finish a turn on a red build and nothing objects
   - *script not executable* — the gate shells out and gets `Permission denied`; because the gates fail closed, this reads as a blocked merge with a confusing reason
   - *missing secret (GitHub) / missing variable group (ADO)* — the named workflows/pipelines fail closed on every PR
   - *no active ruleset (GitHub) / no branch policies (ADO)* — the gates run and report, but a red PR can still merge

4. **Offer to fix what is safely fixable.** `chmod +x` on the installed scripts is safe and mechanical — offer it. Providing a credential is not: it needs a real value from the human, so give them the platform-appropriate fix and let them run it — on GitHub the exact `gh secret set` command; on Azure DevOps the variable group to create and link (Key-Vault-backed, via `az pipelines variable-group`). Never invent a secret value.

5. **Treat `WARN` as information, not a problem.** A warning marks something that could not be determined (Windows cannot see POSIX permission bits; `gh`/`az` may not be authenticated) or setup a later phase is meant to finish (an unfilled `<<TOKEN>>` carries the phase that fills it). Do not push the user to "clear" warnings.

6. **If the harness is not installed at all**, stop and point at `/sdlc-setup`. The rest of the report is meaningless without it.

## Arguments

- `--offline` — skip the checks that need `gh`/`az` (secrets / variable groups, branch protection / branch policies)
- `--repo <path>` — check a different repo (default: current directory)

## Exit codes

`0` — no failures (warnings may be present). `1` — at least one failure; the harness is not fully working.

## Notes

The doctor is **pack-aware**: it reads the installed CI/CD pack from `.claude/harness-manifest.json` and the platform-facing checks follow it — an Azure DevOps install is checked with `az` (variable groups, branch policies) and is never told to install `gh` for a platform it does not use.

That is the **CI platform** axis. The **code host** — which CLI the PR-facing commands (`/sdlc-spec-status`, `/sdlc-handoff`, `connection_report.py`, `pipeline_proof.py`'s PR reads) speak to — is a separate question answered by the repository's `origin` remote, not by the pack: a GitHub remote means `gh`, an Azure DevOps remote means `az`. The two usually agree, but a GitHub repository running Azure Pipelines is legitimate; `connection_report.py --json` reports both (`host`, `ci_platform`) and notes a mismatch without failing. Neither CLI is needed to open a project or run the gates. `code_host.py --repo <path>` prints which host was detected and why.

Required secrets (GitHub) / variable-group references (ADO) are read from **this repo's installed workflows/pipelines**, not from a fixed list. A repo that has adapted `ANTHROPIC_API_KEY` to `CLAUDE_CODE_OAUTH_TOKEN`, or deleted the eval workflows, is checked against what it actually runs — the doctor must never tell someone to "fix" a working setup.

See `ONBOARDING.md` in the repo root for the day-1 checklist this command automates.
