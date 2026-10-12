# /sdlc-harness — Install or update the delivery harness

Install (or refresh) the standard-aligned delivery harness in the current repo, independent of a
full `/sdlc-setup`. Use this to add the harness to a repo that already has `.sdlc/`, or to pull the
latest harness after a plugin update (the harvest loop).

## Instructions

### Step 1: Install the harness
Run the installer from the plugin's bundled payload. Idempotent by default — existing files are
left in place and reported as SKIPPED.
```bash
uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/install_harness.py \
  --payload ${CLAUDE_PLUGIN_ROOT}/harness --target .
```
- To overwrite existing harness files with the plugin's current version (e.g. after an update),
  add `--force`. Review the diff before committing — `--force` will replace local edits.

### Step 2: Report
Summarize what was written vs skipped, then remind the user:
- Fill any remaining `{{PLACEHOLDER}}` tokens in `CLAUDE.md` and the workflows/pipelines.
- **Prove the rails** before trusting them — the shakedown drills in `.github/RAILS.md`
  (the same path holds the ADO guide on azure-devops installs — the pack deliberately overlays it).
- Apply branch protection if on GitHub (needs `gh`, signed in):
  `bash scripts/rails/apply-branch-protection.sh`.
  On Azure DevOps, configure branch policies instead — needs `az` + the `azure-devops` extension:
  `bash scripts/rails/configure-branch-policies.sh --dry-run` to preview, then re-run without the
  flag to apply. Which host the repository is on is read from its `origin` remote
  (`uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/code_host.py --repo .`
  says which, and whether that CLI is usable); neither CLI is needed for the install itself.

## What it installs
`CLAUDE.md` (governance), `specs/spec-template.md`, `.claude/{settings.json,hooks,agents,skills}`,
`.github/workflows/` (ci, grader, correctness, security, deploy-dev, eval-regression, eval-suite)
+ `RAILS.md`, `.github/{profile/rubrics,rulesets,CODEOWNERS,eval-bypasses.md}`, `scripts/rails/`,
`eval-datasets/`, `prompts/`, and `infra/`. On `platform: azure-devops` profiles the platform
surface is realized as `.azuredevops/pipelines/` (the same rails as Azure Pipelines) and
`.azuredevops/rails/` (rubrics + `branch-policies.json` — build-validation and required-reviewer
policies standing in for rulesets and CODEOWNERS); `.github/RAILS.md` still carries the operator
guide. See `.claude/agents/README.md` for the agent/skill
catalog and the on-demand menu.

## Error Handling
- If uv is not installed: `pip install uv` or `brew install uv`.
- If the payload is missing: the plugin may be mid-update; retry, or run `/plugin update`.