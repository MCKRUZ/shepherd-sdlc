# The delivery rails — Azure DevOps operator's guide

This is the Azure Pipelines realization of the delivery standard's rails. The spec is
`delivery-standard/docs/the-rails.md`; the one rule everything hangs off is **the agent proposes, a gate
disposes**. This page is the operator's guide: what the gates are, what you must do to take them live,
and — the part most teams skip — how to **prove they actually catch things**.

> On install, files land as: `azure-pipelines/*.yml` → `.azuredevops/pipelines/`, `scripts/*.sh` →
> `scripts/rails/`, `branch-policies/policies.json` → `.azuredevops/rails/branch-policies.json`. The
> neutral rubrics and `diff-anchors.sh` come from the core/profile layer (`.azuredevops/rails/rubrics/`,
> `scripts/rails/diff-anchors.sh`). Adjust the paths in the prompts if your install layout differs.

## The gates

| Gate | File | Fires on | Blocks or advises |
| --- | --- | --- | --- |
| **build-and-test** | `ci.yml` | every PR | **Blocks** (hard gate) — includes the enforced coverage floor |
| **spec-gate** | `ci.yml` (stage in the build-and-test pipeline) | every PR | **Blocks** — a source change with no spec in the diff is a fact; `no-spec:chore` PR label is the recorded escape |
| **eval-gate** *(optional)* | `ci.yml` | every PR | **Blocks** — keep only if you ship an eval-fixture suite |
| **dependency-gate** | `ci.yml` (stage) | every PR | **Blocks** when the change INTRODUCES a High/Critical advisory (`accepted-risk:dependency` = recorded override) |
| **dependency-scan** | `dependency-scan.yml` | weekly + manual | **Advises** — raises/updates one advisory work item; never blocks |
| **grader** | `grader.yml` | every PR | **Advises** — never blocks; required to RUN |
| **correctness-review** | `correctness.yml` | every PR; reviews when source changed | **Blocks** on a high-confidence defect |
| **security-review** | `security.yml` | every PR; reviews on gated paths / `risk:high` | **Blocks** on HIGH |
| **deploy-dev** | `deploy-dev.yml` | successful CI on main (merge) | n/a — it ships; rolls back on failure |
| **deploy-promote** | `deploy-promote.yml` | **manual only** — never a trigger | n/a — it ships to test/prod once the target Environment's approval check is signed; rolls back on failure |
| **eval-regression** | `eval-regression.yml` | PRs touching the agentic surface | **Blocks** on degradation |
| **eval-suite** | `eval-suite.yml` | manual + scheduled | **Advises** — never gates PRs |

Branch policies (`branch-policies.json`, applied by `configure-branch-policies.sh`) make the blocking
checks mandatory and require a non-author approval + code-owner review on gated paths.

## The merge bar (what branch policies enforce)

Every PR, to merge, must clear (the-rails.md §4):

- **CI green** — `build-and-test` (build, tests, and the enforced coverage floor; plus `eval-gate` if
  kept). Hard block (blocking build validation).
- **Spec present** — the `spec-gate` stage of the same build-validation run: a PR touching source
  carries its committed spec in the diff, *or* the `no-spec:chore` PR label records the exemption. A red
  stage fails the run, which blocks completion — no extra policy needed.
- **The grader has run** — the `grader` build validation completed and posted its verdict thread. The
  verdict can say anything; the *running* is required. (The grader pipeline always concludes success, so
  requiring it gates "did it run," never "what it said.")
- **Correctness review passed** — `correctness-review` found no high-confidence defect, *or* a named
  human recorded the `accepted-risk:correctness` PR label.
- **A non-author approval** — the minimum-approver-count policy with `creatorVoteCounts: false`.

A `risk:high` change additionally requires **security-review passed** plus a named human sign-off. The
`security-review` build validation trivially passes when no gated path changed and no `risk:high` label
is present, and blocks on a HIGH finding when it does — so listing it as required enforces "HIGH adds
security" without leaving low-risk PRs stuck.

## Go-live — what a human must do (not automatable from here)

1. **Adapt every placeholder.** Search the installed files for `<<...>>` and replace: build/test commands
   + service provisioning in `ci.yml`; gated-path regex in `security.yml` (keep it in sync with the
   required-reviewer path filters in `branch-policies.json` and the security rubric); source pathspec in
   `correctness.yml`; spec directory in `grader.yml`; every deploy/rollback step in `deploy-dev.yml`; and
   the org/project/repo/`<<CODE_OWNER>>` values in `branch-policies.json`.
2. **Ensure Node is on the agents.** The LLM gates install the Claude CLI with `npx @anthropic-ai/claude-code`;
   the `microsoft-hosted ubuntu-latest` image ships Node, and each gate also runs `UseNode@1`.
3. **Create the gate pipelines.** Pipelines → New pipeline → Azure Repos Git → Existing YAML → point at
   each `.azuredevops/pipelines/<gate>.yml`. Name them exactly `build-and-test`, `grader`,
   `correctness-review`, `security-review`, `eval-regression` (the build-validation contexts must match
   the `displayName`s in `branch-policies.json`).
4. **Add the API key as a variable group.** Pipelines → Library → new variable group `<<VARIABLE_GROUP>>`,
   ideally **linked to Azure Key Vault**, exposing `ANTHROPIC_API_KEY` (and `EVAL_LLM_API_KEY` for the
   eval gates). There is a real per-PR token cost. Until this is set, security/correctness **fail closed
   on the PRs they review** (by design) and the grader stays green/no-op. *Running Claude through
   Microsoft Foundry? The three LLM gates can go keyless instead — see "Keyless auth via Microsoft
   Foundry" below.*
5. **Allow the OAuth token + PR write.** In each gate pipeline's settings, allow the job to access the
   OAuth token (`System.AccessToken`), and grant the **build service identity** (`<Project> Build
   Service (<Org>)`) the **"Contribute to pull requests"** permission on the repo, so the rails can post
   threads. This includes the `build-and-test` pipeline: its `spec-gate` stage reads the PR's labels via
   the REST API to honor the `no-spec:chore` exemption (read-only; without the token the gate still runs,
   just without the escape).
6. **Apply branch policies.**
   ```bash
   scripts/rails/configure-branch-policies.sh --dry-run   # review the plan
   scripts/rails/configure-branch-policies.sh             # apply (prompts to confirm)
   ```
   This is the only sanctioned way to change branch policy — edit the JSON, re-run the script. Do not
   hand-edit policies in the Azure DevOps UI.
7. **Wire and rehearse `deploy-dev`.** It ships as a STARTER whose placeholder deploy/rollback steps
   must be adapted. Until they are, the job runs, warns that deploy is not wired, and stops — a job
   red on every merge by design teaches the team that red is normal. Create a dev **Environment**,
   wire the steps, set the pipeline variable `DEPLOY_WIRED = true`, then rehearse the rollback
   (§9 shakedown) before trusting it.
8. **Put an approval check on every promotion target, then wire `deploy-promote`.** Pipelines →
   Environments → `test` / `prod` → Approvals and checks → Approvals. That approval **is** the
   go/no-go; without it, promotion beyond dev is automatic. Unlike `deploy-dev`, `deploy-promote`
   **fails** rather than warns when unwired — a human asked for the promotion and is waiting.
   Note the coupling: `deploy-dev` tags the CI build `deployed-dev` on success, and
   `deploy-promote` refuses to promote a build that does not carry its source environment's tag.
   Remove that tagging step and dev becomes a dead end — nothing will ever be promotable.
   `System.AccessToken` therefore needs build **tag write** as well as build read.

## Keyless auth via Microsoft Foundry (optional)

The default gate auth is the `ANTHROPIC_API_KEY` variable group (step 4 above). If the engagement
runs Claude through **Microsoft Foundry**, the three LLM gates can instead authenticate with a
short-lived Entra token minted per-run from a **service connection** — no static Claude credential
stored anywhere, revocation and audit through Entra. Opt-in per gate pipeline; leaving the
`FOUNDRY_*` variables empty keeps the api-key path byte-for-byte.

Provisioning (once, by whoever owns the Azure side):

1. **Foundry resource + model deployments.** Note the deployment NAMES — Foundry does not
   auto-resolve the `sonnet`/`opus` aliases the rails pass, so the pins below must name real
   deployments in the resource.
2. **Service connection** (Project settings → Service connections → Azure Resource Manager →
   **Workload identity federation**), scoped to the resource's subscription/RG. **Pre-authorize it
   for the three gate pipelines** (Service connections → the connection → Security → Pipeline
   permissions) — PR-triggered build validations have an awkward first-use approval flow otherwise.
   Note the fail-closed shape while a connection is wrong or unauthorized: resource authorization
   happens at queue time, before any step conditions run, so **every** PR run of that gate fails —
   including PRs that need no review — until the connection is fixed.
3. **RBAC**: grant the service connection's identity a data-plane role on the Foundry resource —
   **`Cognitive Services User`**. (Some tenants also offer "Azure AI User"; not all have it —
   verified absent in at least one enterprise tenant. `Contributor` alone does NOT include the
   data plane: the symptom is `401 Principal does not have access to API/Operation`, which is
   authorization, not a bad credential.)
4. **Fill the four YAML variables** in `grader.yml`, `correctness.yml`, `security.yml`
   (compile-time values — in the YAML, not the pipeline UI):
   `FOUNDRY_RESOURCE`, `FOUNDRY_SERVICE_CONNECTION`, `FOUNDRY_SONNET_DEPLOYMENT`,
   `FOUNDRY_OPUS_DEPLOYMENT`. At run time an `AzureCLI@2` step mints the token
   (`az account get-access-token --resource https://cognitiveservices.azure.com`) and hands it
   to the CLI as `ANTHROPIC_FOUNDRY_AUTH_TOKEN` (marked secret, never logged).
5. **The variable group**: the claude gates no longer need `ANTHROPIC_API_KEY` — you may drop the
   `- group:` reference from those three pipelines (keep it wherever `EVAL_LLM_API_KEY` is used;
   the eval gates are out of scope for foundry mode). `/sprd-doctor` reads what the pipelines
   reference, so a dropped group is simply no longer demanded — by design.
6. **Verify** with one drill PR: the gate's log shows `Mint Foundry token (…)` followed by a
   normal review; fail-closed semantics are unchanged (a gated change whose review cannot run
   still BLOCKS — now including "token could not be minted").

Local testing gotcha: a developer reproducing the gate locally from inside a Claude Code
*desktop* session inherits `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST` and the CLI defers to the
app ("Foundry credentials are managed by the desktop app"). Scrub the environment first
(`env -i HOME=... PATH=... CLAUDE_CODE_USE_FOUNDRY=1 ...`) — CI agents are clean by nature.

## Solo-repo accommodation (read this)

Azure DevOps forbids a PR author from satisfying their own approval when `creatorVoteCounts: false`, so on
a single-maintainer repo the "non-author approval" rule cannot be self-satisfied. Grant the maintainer
(or the Project Administrators group) the **"Bypass policies when completing pull requests"** permission
on the repo — they can then complete their own PRs today, while every change to the protected branch still
rides a PR and its blocking build validations (the bypass waives only the human-approval requirement a
solo repo can't satisfy, not the CI gates). This is honest, not hidden: the human-review rule is fully
wired and becomes real the moment a second reviewer (or a review bot) joins — remove the bypass then.

## Gate integrity (known residual risk)

These pipelines run the **PR's own copy** of the pipeline YAML, the rubric, and the gated-path regex. A
PR could in principle weaken its own gate (rewrite the rubric to force PASS, edit the regex to exclude its
path, neutralize the enforce step). Mitigations in place: the verdict file is written/read **outside** the
working tree (`$(Agent.TempDirectory)`) and any committed copy is deleted before review (so a planted
PASS can't pass); and changes to `.azuredevops/**` are a gated path requiring code-owner review. The real
closure is a **non-author review of rails changes** — exactly what the approver-count + required-reviewer
policies enforce once a second reviewer exists (remove the owner bypass then). Do not point the gate
pipelines at **fork** PRs with secrets exposed — keep the variable group scoped so forked-PR runs cannot
read the API key (the Azure analogue of never switching to `pull_request_target`).

## Prove the rails — the SHAKEDOWN DRILL (the-rails.md §9)

> A pipeline that has never caught anything is not proven — it is merely present. A rail that has only
> ever seen green has not been tested; it has been *assumed*.

Before trusting these, force each one to fail and confirm it is caught. A blocking gate is only proven
when **both its block and its escape** have been seen to work.

- **CI / eval-gate** — introduce a failing test (and a sub-threshold coverage change), open a PR. The
  `build-and-test` build validation must go red and block completion — the coverage miss goes red at the
  `Enforce coverage floor` step (restore-build-test.yml), which names the measured percentage and
  the floor it missed. Already exercised by every real PR.
- **spec-gate** — open a throwaway PR that touches a file under `src/` with **no spec in the diff**. The
  `spec-gate` stage must go **red** (failing the `build-and-test` build validation), listing the touched
  source files and the escape. Then apply the `no-spec:chore` PR label and re-queue; confirm it goes
  **green** — the recorded exemption clears it. Abandon the PR. A blocking gate is only proven when both
  its block and its escape have been seen to work.
- **grader** — open a PR whose **spec file claims something the diff does not do** (or whose stated
  intent and implementation disagree). The grader's PR comment thread must call out the mismatch. (No
  verdict blocks — you are confirming it *posts the miss* and that the `grader` build validation still
  reports success.)
- **correctness** — open a throwaway PR with a planted high-confidence defect under source (e.g. an
  inverted null check, or an off-by-one that drops a row). The `correctness-review` build validation must
  go **red** with `CORRECTNESS_VERDICT: BLOCK`, anchored to the exact changed line, and block completion.
  Then apply the `accepted-risk:correctness` PR label and re-queue; confirm it goes **green** — the
  override clears it. Abandon the PR. Do this before relying on it as a required policy.
- **security** — open a **probe PR touching a guarded path** (e.g. add a comment in a file under
  `**/Auth/`) with a planted HIGH issue. The `security-review` build validation must go red. Abandon it.
- **deploy-dev** — stage a **known-bad deploy** (a deliberately broken artifact or a health check pointed
  at a failing build). The deployment must fail and the `on.failure` steps must **restore the last
  known-good version** — the rollback the rails rehearse. Run deploy → roll back → redeploy against the
  dev Environment, with the rollback trigger condition written down in advance, not invented mid-incident.
- **deploy-promote** — three drills, and the first two are the ones people skip:
  1. **The gate holds.** Run a promotion. It must **pause** on the target Environment's approval
     check and not proceed until a named person signs. If it sails through, no approval is
     configured and promotion is automatic — the standard's most protected stop, silently absent.
  2. **You cannot skip an environment.** Try to promote a build straight to `prod` that carries only
     the `deployed-dev` tag. The preflight must **refuse** it. This also proves the tagging step in
     `deploy-dev` actually ran — if nothing is promotable at all, that step failed silently.
  3. **The rollback still works up here.** Repeat the known-bad deploy against **test** via
     `deploy-promote`, executed by the client's own operators with their own permissions — the
     Phase 8 rehearsal, run before prod is ever a target.
- **dependency-gate** — open a throwaway PR adding a package with a **published advisory**. The
  stage must go **red**, naming the package and advisory. Apply the `accepted-risk:dependency` PR
  label and confirm it clears. Abandon the PR. Run this one even if you skip others: every other
  rail fails loudly when misconfigured, this one fails **silent and green** — a scan that cannot
  parse its tool's output reports no findings, which looks exactly like a clean repo.
- **eval-regression** — open a PR touching `prompts/**` that degrades a key metric past the trip-wire (or
  point the runner at a fixture that regresses). The `eval-regression` build validation must go red.
- **secret scan** — open a throwaway PR that commits a **fake but realistic credential** (e.g. an invented
  `AKIA…`-style key in a config file — never a real one). The `build-and-test` build validation must go red
  at its first step, `Secret scan (gitleaks)`, with the planted string redacted in the log. Abandon the PR.

A rail that has never failed safely has not been proven. The shakedown is not optional polish — it is the
difference between a rail and a decoration.

## Watch the rails

Health shows up in the DORA four — deploy frequency, lead time, change-fail rate, time-to-recover — read
as trends. **Never** velocity, story points, PR count, or LOC: agents inflate every one of those. The
rails are healthy when changes flow and fail rarely, not when the agents are busy. Log every agent
recommendation, applied artifact, and gate outcome centrally, with co-authorship on commits, so any
change is traceable to the identity that produced it.
