# Phase 3: Foundation

## Purpose
Build the factory and prove it on real software. Install and adapt the harness, stand up the rails (CI, grader, correctness, security, and deploy-dev workflows plus branch protection), provision the dev environment from code, then run a thin walking skeleton — including at least one HIGH-risk spec — end-to-end through the full Build loop into the client's dev environment. This is the hinge of the engagement: the phase where the documents stop and the software starts. Foundation's product is not a feature; it is a working factory with one part already moving through it.

## Entry Criteria
- Phase 2 exit gate passed and `phase3-handoff.md` reviewed
- The walking-skeleton definition from Phase 2 (the thinnest end-to-end slice that proves the architecture)
- `deep-plan-checkpoint.yaml` and section boundaries available as the source of the skeleton's slices

## Project Type Adaptation

**Before starting Phase 3, read `project_type` from `state.yaml`.**

| project_type | Foundation Focus |
|--------------|-----------------|
| `service` / `app` | Full rails: CI + grader + correctness + security + deploy-dev workflows, IaC dev environment, branch protection, walking skeleton deployed to a real dev environment through the pipeline. All exit conditions apply. |
| `library` / `cli` | Rails without an environment: CI + grader + correctness + security workflows and branch protection apply; `deploy-dev` becomes a publish-to-internal-feed (or a no-op dry-run) since there is no server to deploy. The "walking skeleton" is the thinnest end-to-end invocation path exercised through the loop. |
| `skill` | No compiled deploy target. CI runs lint + scenario checks; the grader and correctness gates still run against changed instruction files; the security gate becomes prompt-safety review. The "walking skeleton" is one end-to-end scenario run through the loop. Prove the rails by forcing each to fail (a planted scenario mismatch for the grader, a failing check for the Stop hook). |

## Workflow

<!-- NOTE: The "do not skip the loop because it's just the skeleton" constraint is stated more than once in this file
     (here, in Step 4, and in the exit gate). This is INTENTIONAL redundancy for LLM compliance — the single most common
     Foundation failure is hand-building the skeleton off the rails to save a day. Repetition at different points improves
     adherence. Do not consolidate. -->

> **CONSTRAINT:** Every walking-skeleton slice MUST run the full Build loop — Intent → Delegate → Discern → merge → deploy — on the real rails. Hand-building the skeleton off the rails "because it's only the skeleton" is prohibited. The skeleton is precisely where the loop and the rails get proven; a skeleton built around the rails teaches the team nothing and hides the rails' defects until Build, where they are expensive.

### Step 0: HITL Gate — Confirm the Rails Plan and the Skeleton Slices

> **HITL GATE:** Read `phase3-handoff.md` and the Phase 2 walking-skeleton definition. Before installing anything, present the following to the human using the `AskUserQuestion` tool — do not use inline markdown for HITL questions: (1) Confirm the skeleton's slices are the right thinnest end-to-end path — and which single slice carries the highest risk (it will run the loop at HIGH). (2) Confirm where the dev environment lives and who holds branch-protection admin, Actions enablement, runner policy, and the secrets vault — these are client access realities, not pod conveniences. (3) Confirm the named Setup Owner's deputy (the both-eyes reviewer of every harness change). (4) For `library`/`cli`/`skill`: confirm what `deploy-dev` means for this target. Do not install the harness or stand up rails until the human confirms the rails plan and the skeleton scope.

Foundation answers four questions and nothing else: Is the harness real and adapted? Are the rails real and enforced? Does the loop actually run? Is the architecture real? Hold every step to one of those four. The full feature backlog, the test and production environments, and any breadth beyond the thinnest skeleton are out of scope — they belong to the Build loop and the hardening passes.

### Step 1: Install and Adapt the Harness

The harness is the project's `CLAUDE.md`, `specs/`, `.claude/` (skills, agents, hooks, settings) — the context and rules every AI agent loads when it starts work in the repo. It lands as a working starting point, not a blank repo.

**1a. Scaffold from the kit.** Install the reusable starter into the repo: the `CLAUDE.md` template, the spec template (`specs/NNNN-name.md`), settings, skills, the grader and security-reviewer agents, the Stop hook, the workflow YAML, and the IaC starters. The kit is not built here — it is the firm's standing asset, improved between engagements. This phase adapts it; it never invents it on the client's clock.

**1b. Adapt `CLAUDE.md` to the client.** Rewrite it in the client's own domain: the domain glossary in their words, the stack standards, the risk taxonomy (Step 3), the gated paths, and the Definition of Checked. A generic `CLAUDE.md` means agents guess the domain, and guesses differ per run. The adaptation happens as reviewed PRs the client's lead engineer reads — the client team's first concrete look at how the pod works.

**1c. Both-eyes review.** Every harness change is reviewed by the Setup Owner's deputy. The author of the foundation is never its sole approver. Record the harness inventory and adaptation notes in `harness-inventory.md`.

### Step 2: Stand Up the Rails

Build the five workflows and the branch protection that makes them mandatory. The governing principle is **agent proposes, gate disposes**: an agent may produce any change, but only as a reviewable artifact, and a deterministic check plus a named human decides whether it takes effect.

The five workflows:

- **ci** (hard block): build, tests, lint, and coverage (default 80% on new code). The mechanical floor — a red CI is a closed door.
- **grader** (required to run; advises, never blocks): a fresh AI agent that did not write the change reads the spec in the diff and posts a check-by-check verdict pinned to the exact changed lines. "The grader ran" is a required status check; *what* it said is the human Checker's input, not a gate.
- **correctness** (blocks on a high-confidence defect): a fresh AI agent — separate from the grader — hunts the changed lines for plain logic defects (off-by-ones, null paths, inverted conditions). A named human can override on the record.
- **security** (blocks on HIGH): runs the security-reviewer agent. Fires on the `risk:high` label **or** any PR touching a registered gated path (auth, migrations, the pipeline, infra), independent of the spec's tier.
- **deploy-dev** (ships): merge to main deploys the merged artifact to the client's dev environment, and restores the last good version when a deploy fails.

**Branch protection** (branch policies on Azure DevOps) turns the workflows from suggestions into rails. Every PR, to merge, must clear: CI green, the grader has run, correctness passed (or a named-human override is recorded), and a non-author approval. A `risk:high` change adds the security workflow pass and a named human sign-off recorded in the PR. The agent can push only to branches it creates, can never approve or merge its own work, and every agent commit is co-authored so provenance is in the history.

**The Stop hook** is the highest-value automation in the standard: a script that fires when an agent tries to finish its turn and refuses to let it stop on a failing build or red tests. It turns "the tests must pass" from a request the agent might rationalize past into a fact about the world. Wire it in `.claude/` settings.

Wire the build-time security gates from the Phase 2 threat review: register each guarded path with the security workflow so the workflow runs on any PR touching that path. The gate is the workflow plus the path registration.

**Confirm the wiring against the model, path by path.** This is Phase 3's half of the threat review — Phase 2 decided *what* to guard, and this pass proves it got guarded. Walk `threat-model.md`'s guarded-path map and, for each entry, confirm a registration exists and the workflow actually fires on it. Prove one: open a throwaway PR touching a guarded path and watch the security workflow run. A guarded path that was registered but never observed firing is a gate nobody has tested, which is the same failure the rails shakedown exists to prevent.

If Phase 2 produced no threat model, stop and do that review now rather than choosing the guarded paths here from memory — picking them at wiring time is how the security gate ends up protecting whatever seemed sensitive on the day.

Workflow YAML and branch-protection config are HIGH risk — human review on every change, the deputy and the client's DevOps reading them before they merge.

### Step 3: The Risk-Tier Map

Produce `risk-tier-map.md`: every codebase area with its risk tier (HIGH / MEDIUM / LOW) and any security gate registered against it. This is the same taxonomy that lives in `CLAUDE.md` so agents see it too. Anchor it to the standard's taxonomy:

| Tier | What lands here | What it triggers |
|------|-----------------|------------------|
| HIGH | Auth/identity, payments, personal or client data, schema migrations, public API contract changes, infrastructure and pipeline changes, AI-behavior changes (prompts, models, tool definitions), anything hard to undo | Tight agent permissions, the full checking ladder, a security review pass, a named human sign-off |
| MEDIUM | New business logic, external integrations, changes to shared internal services | Standard permissions, grader plus a human Checker |
| LOW | UI within existing patterns, copy, internal tooling, additive CRUD on established rails | Lighter review; the grader and the mechanical gates still run |

The Phase 2 security gates MUST appear on the map with their guarded paths.

### Step 4: Provision the Dev Environment from Code

Draft the IaC for the dev environment (Bicep on the .NET/Azure default; the pattern is stack-independent). HIGH risk — human-reviewed on every change; the environment provisions from code, not from clicks. Run it through the agent-safe IaC funnel: schema-validate → policy-as-code gate → dry-run (`bicep what-if` or equivalent) → human approval → scoped least-privilege apply.

Secrets land in the client's vault (Key Vault and GitHub secrets on GitHub; Key-Vault-backed variable groups on Azure DevOps) — never in code, never in `CLAUDE.md`, never in a spec. A secret in the repo is the one unrecoverable mistake of the phase: a rotation event and an audit-log review, not an edit. Draft the data-flow brief for client security: what goes to the API, what doesn't, where keys live, who can see usage.

**For `library`/`cli`/`skill`:** there is no environment to provision. Record `N/A — {project_type}` for the IaC artifacts and proceed; the rails still apply.

### Step 5: Run the Walking Skeleton Through the Loop

Author the skeleton's slices as specs (`specs/NNNN-name.md`) from the Phase 2 slices, then ride each through the full Build loop. See `phases/build-loop.md` for the full loop discipline — the skeleton is the loop's dress rehearsal, and nothing gets skipped because it is "only the skeleton."

**5a. The first slice.** Run the full loop end-to-end for the first time on this engagement: Intent (the slice triaged into a ready spec), Delegate (the agent in plan mode, bounded per spec, the Stop hook refusing to finish on a failing build), Discern (the CI gates and grader on the PR, a human Checker on the merge), then the automatic deploy to dev. Anything broken in the rails — a gate that doesn't fire, a grader that doesn't post, a deploy that doesn't roll back — gets found and fixed here, while it is cheap.

**5b. At least one HIGH-risk slice.** The slice touching the riskiest seam (the regulated integration, the sensitive data path) runs the loop at HIGH risk: tight agent permissions, the security workflow firing on the `risk:high` label, a named human sign-off recorded in the PR. The HIGH path of the loop gets proven before Build ever relies on it. **This is a hard exit condition.**

**5c. The remaining slices and the outcome metric.** The rest of the skeleton's slices ride the loop. The slice that emits the **outcome metric** gets special attention: it makes the engagement's success metric measurable from day one of Build. Any build-time security gate touching these slices fires on its first qualifying PR — proven, not just configured. If no slice touches a gate's guarded path, prove it with a probe PR (a throwaway change to that path, opened solely to confirm the gate fires, then closed unmerged).

**5d. The skeleton end-to-end.** The slices connect into the running skeleton in the dev environment. Verify the running software against the Phase 2 walking-skeleton definition: does it prove the architecture, end to end, under the rails? Run a first end-to-end smoke journey — an automated test walking the same path a user would — across the skeleton.

> **CHECKPOINT:** The skeleton is not done when each slice compiles. It is done when every slice has ridden the full loop, the slices connect end-to-end in the real dev environment, the smoke journey passes, and the running software is verified against the Phase 2 definition. Record the per-slice loop evidence (spec, PR, grader verdict, Checker, deploy) in `walking-skeleton-spec.md`.

### Step 6: Prove the Rails by Forcing Their Failure

A rail that has only ever seen green has not been tested — it has been assumed. Before Foundation closes, make each rail fail deliberately and catch it. Record each proof in `pipeline-proof.md`:

- A failing test proves the **Stop hook** actually blocks an agent from finishing.
- A PR with a planted spec mismatch proves the **grader** actually posts the miss.
- A PR with a planted logic defect (an off-by-one, a flipped condition) proves the **correctness gate** blocks *and* that the override clears it: open it, watch the gate go red anchored to the exact line, record the override label, watch it go green, close it unmerged.
- A known-bad deploy proves **deploy-dev** restores the last good version.
- A probe PR touching a guarded path proves the **security gate** fires.

The shakedown is not optional polish — it is the difference between a rail and a decoration.

### Step 7: The Cadence Plan and the Build Tripwires

Produce `cadence-plan.md`: schedule the Build cadences that begin in this phase and run all through Build — the daily flow check, weekly intent triage, retro+, and the setup review. Agree two numbers and record them:

- **WIP cap** — the limit on how many changes may be in flight at once (default: no more than two concurrent agent streams per Orchestrator). It keeps the pod from opening more changes than its checking capacity can clear.
- **Review-wait tripwire** — the wait-time threshold that, once crossed, stops new work starting until the review queue clears (default: median one working day). Review is the loop's real bottleneck; this number is how the pod refuses to bury it.

One number for the whole project only works when every team has the same checking capacity. A project with teams of very different sizes can replace it with `cadence-plan.md`'s optional `## WIP Limits` table instead — one row per team (matching `.sdlc/team.yaml`), each with its own WIP limit and its own review/security-review alarm hours (defaults: 24h / 48h when left blank). `scripts/track_specs.py` and `scripts/scorecard.py` both read it and behave exactly as before when it's absent.

### Step 8: Phase Handoff

Draft `build-handoff.md` (and `foundation-report.md`): the ordered spec backlog ready for triage, the risk-tier map (including the Phase 2 security gates), the cadence calendar with the WIP cap and review-wait tripwire, and the open questions under their original IDs. The exit demo runs in the client's own dev environment, through the real pipeline, with the outcome metric ticking — never on a laptop.

### Step 9: Generate Visual Report

Generate an interactive HTML visual report at `.sdlc/reports/03-foundation-visual.html` using the `/visual-explainer` skill (or equivalent HTML generation). This report is the stakeholder review artifact.

**Required visualizations for Phase 3 (Foundation):**
- Rails status board — the five workflows + branch protection, each marked present / proven (with the forced-failure evidence)
- Walking-skeleton slice tracker — each slice with its risk tier, loop status, and deploy state
- Risk-tier map (the codebase areas, their tiers, and registered security gates)
- Cadence calendar with the WIP cap and review-wait tripwire

See the Visual Report Protocol in `SKILL.md` for rendering standards and fallback behavior.

### Step 10: Generate Phase Report

Run `/sprd-gate` to validate exit criteria and automatically generate the phase HTML report at `.sdlc/reports/03-foundation-report.html`. Share this report with stakeholders for review before requesting sign-off. The report includes artifact inventory and gate status.

## Standalone or Workflow

Foundation is normally the fourth opening phase, reading `.sdlc/state.yaml`, the Phase 2 walking-skeleton definition, and the section boundaries. It also runs standalone against an existing repo with no `.sdlc/` present — pointed at a codebase that needs the factory retrofitted. In standalone mode: derive the risk-tier map from a workspace scan rather than the Phase 2 handoff, treat the thinnest currently-shippable change as the "walking skeleton" to prove the loop, write artifacts to an explicit output path, and note the missing Phase 0–2 context in each artifact's header. The exit conditions (rails proven by forced failure, one HIGH-risk spec through the loop, skeleton deployed through the real pipeline) hold in both modes.

## Artifact Specifications

### `foundation-report.md` (REQUIRED)
Must contain ALL of:
- **Harness summary** — what was installed and how `CLAUDE.md` was adapted to the client's domain
- **Rails summary** — the five workflows, branch-protection config, the Stop hook, and which guarded paths are registered
- **Forced-failure evidence** — a line per rail proven by forced failure (cross-reference `pipeline-proof.md`)
- **Walking-skeleton outcome** — the slices, the HIGH-risk slice, the end-to-end verification against the Phase 2 definition, the outcome metric ticking in dev
- **Open questions** — carried under their original IDs into Build

### `risk-tier-map.md` (REQUIRED)
Must contain ALL of:
- **Tier table** — every codebase area with its tier (HIGH / MEDIUM / LOW) and rationale
- **Registered security gates** — each guarded path and the workflow that fires on it (the Phase 2 gates MUST appear here)
- **The risk taxonomy** — what lands in each tier and what it triggers (mirrors `CLAUDE.md`)

### `cadence-plan.md` (REQUIRED)
Must contain ALL of:
- **Cadence calendar** — flow check (daily), intent triage, retro+, setup review (weekly), with owners
- **WIP cap** — the agreed concurrent-stream limit, with the reasoning if it differs from the default
- **Review-wait tripwire** — the agreed wait threshold and what happens when it is crossed
- **The numbers that steer the loop** — accepted-as-is rate, review wait, rework/revert, escaped bugs, the DORA four, security-review wait (on its own line). Explicitly note the banned activity metrics: velocity, story points, PR count, lines of code.

### `build-handoff.md` (REQUIRED)
Must contain ALL of:
- **Ordered spec backlog** — ready for the first intent triage
- **Risk-tier map reference** — including the Phase 2 security gates
- **Cadence calendar** — with the WIP cap and review-wait tripwire
- **Open questions** — under their original IDs
- **Entry conditions for Build** — what is proven and ready (rails, skeleton, dev environment)

### Optional Artifacts
- `harness-inventory.md` — what the kit installed and the per-file adaptation notes
- `pipeline-proof.md` — the forced-failure evidence, one entry per rail
- `walking-skeleton-spec.md` — the skeleton slices with per-slice loop evidence (spec, PR, grader verdict, Checker, deploy)
- `03-foundation-report.html` — the generated phase report

### `data-flow-brief.md` (REQUIRED)

The one-page brief for the client's security team: what leaves the repo for the model API, what does
not, where credentials live, and who can see usage.

This is a contractual artifact as much as a technical one. The standard promises the client's
security function a written answer to "what are you sending, and where does it go" before any agent
runs against their code. A verbal answer in a meeting is not that.

Must contain:
- **What goes to the API** — code context from the repo, specs, diffs. Be specific
- **What does not** — the material tagged out of agent context, and the mechanism that keeps it out
- **Where keys live** — their vault, their tenant, their audit trail
- **Who sees usage** — the account, the billing view, the log retention
- **The training position** — the contractual terms covering whether their data trains a model
- **Who signed it** — a named person in the client's security function, with a date

> **HITL GATE:** This is reviewed and accepted by the client's security team, not by us. Do not mark
> it complete on the strength of the pod's own reading.

> **If it genuinely did not happen**, say so *in this file*: a line reading
> `WAIVED: <name> — <reason>`. The gate accepts it and reports it, by name, in the record the
> approver signs against. A missing file still blocks. The escape is from the work, not the
> record — an exception nobody can see is how a gate stops being a gate.
## Exit Criteria
- [ ] `foundation-report.md`, `risk-tier-map.md`, `cadence-plan.md`, and `build-handoff.md` exist and are complete
- [ ] The harness is installed, adapted to the client, committed, and reviewed by the Setup Owner's deputy (never sole-approved by its author)
- [ ] The pipeline runs: CI hard gates, the grader required to run, correctness blocking on a high-confidence defect, security on `risk:high`, deploy-dev on merge — all reviewed by the client's DevOps
- [ ] Branch protection (branch policies on ADO) enforces CI green + grader-ran + correctness-passed + non-author approval; `risk:high` adds the security workflow and a named sign-off
- [ ] The dev environment is provisioned from code; secrets live in the client's vault, never in code (N/A for `library`/`cli`/`skill`)
- [ ] The build-time security gates from Phase 2 are wired, and each has fired on a real PR
- [ ] The walking skeleton is deployed to the dev environment through the real pipeline and verified against the Phase 2 definition
- [ ] At least one HIGH-risk spec has run the full Build loop
- [ ] The rails are proven, not just present: the Stop hook blocks, the grader posts, the correctness gate blocks-and-overrides, deploy-dev rolls back, the security gate fires
- [ ] The outcome metric is measurable in dev
- [ ] The Build cadences are scheduled and the WIP cap and review-wait tripwire are set
- [ ] Stakeholder reviewed and approved (manual gate)

## HTML Report
The phase report is generated automatically when you run `/sprd-gate` or `/sprd-next`. It is written to `.sdlc/reports/03-foundation-report.html` and is fully self-contained — share it with stakeholders as the review artifact for the manual sign-off gate.

To regenerate at any time: `/sprd-phase-report`

## Next Phase
Foundation hands off into the **Build loop** (`phases/build-loop.md`) — the continuous middle where every change from here to feature-complete rides the same three beats on the rails this phase proved. `build-handoff.md` is the entry package.

## Guidance
- The skeleton is precisely where the loop must be proven. A skeleton hand-built off the rails teaches the team nothing and hides the rails' defects until Build, when they are expensive.
- A pipeline that exists but was never exercised is a decoration. The rails are proven by a change breaking and being caught, not by the YAML being present.
- A generic `CLAUDE.md` means agents guess the domain. The adaptation in the open is the point of the phase, not a formality to rush past.
- IaC and pipeline changes are HIGH risk because they are hard to undo and run in production later. The Setup Owner is never the sole approver of their own foundation.
- A secret in the repo is the one unrecoverable mistake. The client's vault from day one — never in code, never in `CLAUDE.md`, never in a spec.
- A feature-rich skeleton is Build scope wearing a Foundation badge. Hold it to the thinnest end-to-end path; let the backlog carry the rest.
- The exit demo runs in the client's own dev environment through the real pipeline, or it has not proven what Foundation exists to prove.

## Coaching Prompts

When operating in coaching mode (`/sprd-coach`) for this phase:

### Opening (no rails yet)
- "What's the thinnest end-to-end slice that proves the architecture? Which single slice carries the most risk?"
- "Who holds branch-protection admin and the secrets vault on the client side? Is that access real yet?"
- "Who's the Setup Owner's deputy — the both-eyes reviewer of every harness change?"

### Progress Check (rails standing up)
- "The five workflows exist. Have you proven each one fails safely, or just that they're green?"
- "Has any HIGH-risk slice run the full loop yet? That path needs proving before Build relies on it."

### Ready Check (skeleton deployed)
- "The skeleton's in dev. Is it deployed through the real pipeline, and verified against the Phase 2 definition?"
- "Are the WIP cap and review-wait tripwire set? Build's bottleneck is checking, not building."
