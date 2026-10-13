# Build Loop

## Purpose
The continuous middle of the engagement. Every change — large or small — runs the same three beats: **Intent** (decide what you want, clearly enough to check, and write it as a spec), **Delegate** (an agent builds it inside bounds a human set, from a plan a human approved), **Discern** (checks and a non-author prove it against the spec, then merge deploys it). The Build loop replaces the batch Implementation, Quality, and Testing phases. It is not a phase: there is no artifact exit gate at the end of a loop pass, because checking happens per change. A human declares the backlog feature-complete to leave.

## Why This Is Not a Batched Phase
The visible gap where Implementation / Quality / Testing used to sit is intentional. Batched checking — write everything, then review everything, then test everything — is the failure mode the standard exists to kill. When an agent can produce code in minutes, the constraint is not building; it is proving. Checking moves to per-change inside the loop, never a later batch phase. The moment the pod starts skipping the loop for "small" changes is the moment unchecked work creeps back in. Small and risky is exactly the cheap-to-type, expensive-to-get-wrong case: the worst bugs in agent-built code ship inside changes someone decided were too small to bother checking.

## Entry Criteria
- Phase 3 (Foundation) exit gate passed and `build-handoff.md` reviewed
- The rails proven (Stop hook blocks, gates fire, deploy-dev rolls back) and the walking skeleton deployed
- The ordered spec backlog, risk-tier map, and cadence calendar in hand
- The WIP cap and review-wait tripwire set (one project-wide, or per team via `cadence-plan.md`'s optional `## WIP Limits` table)

## The Three Beats

### Beat 1 — Intent: decide and write

Nothing enters the loop as a conversation. A story becomes buildable only by clearing the **Definition of Ready** at weekly intent triage:

- **Every acceptance criterion passes the vague-line test.** The test: "Could two people build different things from this line?" If yes, the line is a wish, not a check. "Handle errors gracefully" is a wish; "a duplicate submission returns 409 with `{ "error": "duplicate claim" }`" is a check.
- **Scope in and scope out are both stated.** What the change must not touch is as load-bearing as what it must do.
- **The silent decisions are answered.** A real product choice left unwritten (fail open or fail closed? what does a blocked user see?) does not disappear — the agent makes it for you, fast, under no supervision, and you find out what it chose when something breaks. Surface each onto the decision list, with a named human owner and an answer clock.
- **A risk tier is assigned** by the Pod Lead and recorded in the spec.
- **The harness context is named** — which existing pattern this change reuses, so the agent extends the codebase instead of inventing a second way to do something it already does.

Then write the spec — one file in the repo, durable across sessions:

**The spec format (`specs/NNNN-name.md`):**
- **Goal** — one sentence: what capability exists when this is done
- **Why** — the reason this change matters
- **Scope in / Scope out** — the file patterns it may touch, and what it must not
- **Acceptance checks** — testable, each passing the vague-line test
- **Risk tier** — HIGH / MEDIUM / LOW
- **Owner / Developer / Checker / Team** — the named human accountable for intent and decisions;
  who drives the agent and approves the plan; who gives the non-author approval — the author
  never approves their own work; and the team this spec belongs to. Owner is required before a
  spec is Ready; developer and checker are filled at hand-off (Beat 2)
- **Delegation plan** — what the agent may touch, what is gated, the named pattern to reuse
- **Checking plan** — how high this change climbs the checking ladder (Beat 3)

The spec outlives the chat that produced it: the agent reads it every session, the grader grades against it, and when behavior changes later, the spec changes in the same PR. A stale spec is a lie that misleads the next reader and the next agent.

**Tooling for Intent.** `/sprd-spec` wraps this beat: it scaffolds the spec from the template (`scripts/new_spec.py` allocates the next `NNNN` id), drives the Definition of Ready, proposes a risk tier for a human to confirm (the agent never assigns the tier), and enforces the DoR with `scripts/check_spec.py` — a mechanical floor (required sections, a valid risk tier, scope in *and* out, no unfilled placeholders) plus a **vague-line lint** that flags acceptance checks likely to fail the vague-line test. The lint advises; the real vague-line test is your judgment. A spec that `check_spec.py` reports NOT READY does not enter the loop — building from it is the "skipping Intent" failure this loop exists to kill. Both scripts run standalone (point `--spec`/`--repo` at any repo) or in the workflow (with `--state`, each check logs to `.sdlc/metrics/spec-log.jsonl`).

**Channel binding (conditional).** A spec with a customer surface is bound to exactly one channel before it is Ready: `/sprd-channel` sets the spec's `channel:` field, injects that channel's acceptance dimensions (from `channels/<id>.yaml` and the Phase 2 `channel-interaction-spec.md`) as concrete lines under `## Acceptance Checks`, seeds `harness_context` if it is empty, and applies the channel's risk floor — which may raise the tier, never lower it. `check_channel.py` then advises (never blocks) when a bound spec is missing a dimension; `check_spec.py` is untouched. Checks that trace to a signed `BR-NN` cite it; a spec touching fields the data contract marks PII takes its tier from that classification.

**The team roster (conditional).** A project may keep `.sdlc/team.yaml` — every person who may hold a role on a spec, their code-host handle, their team, and which stages they sign off (`scripts/validate_team.py` guards its shape; a worked example lives at `templates/team/team.example.yaml`). When a roster is present, `check_spec.py` confirms a spec's `owner` and `team` name a real entry in it, blocking otherwise. With no roster, that cross-check is skipped and says so — a project without one still works, it just isn't confirming names against anything. The roster never decides who *may* approve a change; that stays with branch protection on the code host. See `references/team-model.md`.

**The risk taxonomy** (it lives in the harness so agents see it too):

| Tier | What lands here | What it triggers |
|------|-----------------|------------------|
| HIGH | Auth/identity, payments, personal or client data handling, schema migrations, public API contract changes, infrastructure and pipeline changes, AI-behavior changes (prompts, models, tool definitions), anything hard to undo | Tight agent permissions, the full checking ladder, a security review pass, a named human sign-off |
| MEDIUM | New business logic, external integrations, changes to shared internal services | Standard permissions, grader plus a human Checker |
| LOW | UI within existing patterns, copy, internal tooling, additive CRUD on established rails | Lighter review; the grader and the mechanical gates still run |

Risk challenges escalate up, never down, without discussion — anyone (human or agent) can raise a tier on the spot; lowering one always takes a discussion with the Pod Lead, who owns the tier.

Intent is the highest-leverage hour anyone spends in the loop. When the agent can produce the code in minutes, what decides whether you get what you wanted is how clearly you said it — vague intent doesn't get fixed downstream, it gets built, fast, wrong.

### Beat 2 — Delegate: bound and build

Delegating is not "go build it." It is drawing the box the agent works inside and approving its plan before it starts.

**Plan mode first, always.** The agent starts in plan mode: it reads the repo and the spec and proposes an approach — which files it will touch, how it will satisfy each acceptance check — before it may write anything. The Orchestrator corrects or approves the plan, and looks for the one decision the plan glosses over. Correcting a plan costs a sentence; correcting a finished build costs a redo. The most dangerous decisions in agent-built code are the ones nobody noticed being made — plan approval is where they get noticed.

**Three bounds, set per spec:**
- **Scope** — the file patterns the change may touch. Everything else is out, and "if you think something outside this needs to change, stop and ask" is part of the handoff.
- **Context** — the one canonical pattern to reuse, named explicitly. An agent not pointed at the existing pattern will happily invent a second one, and now the codebase has two.
- **Permissions** — what the agent may do without asking. The harness auto-allows the safe commands (build, test, lint, reads) and forces a human confirm on the rest: package installs, network calls, anything under a gated path like migrations or auth.

**Freedom by risk, within one change.** The parts that are cheap to undo get a loose leash ("implement the log throttling however reads cleanest"); the parts expensive to get wrong get a tight one ("for the keying and the auth check, follow the plan exactly — deviate only by asking"). Stay out of the keystrokes on the easy stuff; stay in the big calls on the hard stuff.

**One agent or many.** Fan out to *explore*: independent investigations (three candidate approaches, each written up by its own agent) run in parallel because they touch nothing shared. Single-thread to *build*: one feature writing into shared code paths gets exactly one agent, start to finish, because parallel agents in the same files clobber each other. The test: are the pieces independent (fan out) or tangled (single-thread)? Spread out to explore, line up to commit.

**TDD inside Delegate (when the profile or the spec requires it).** When TDD applies, the agent writes the failing test first (red), implements the minimum to pass (green), then refactors while the test stays green. For a bug fix, this is mandatory regardless of profile: write the regression test that reproduces the bug (it fails, proving the bug exists), fix the code, watch it pass, and add the test to the permanent suite. Never fix a bug without a test that would have caught it. Tests must encode *why* the behavior matters, not just *what* it does — a test that can't fail when the business logic changes is wrong.

**The box is enforced, not requested.** The permission rules hold whether or not anyone is watching, and the **Stop hook** refuses to let the agent finish with failing tests or a broken build. This hook is the single highest-value automation in the standard: it turns "the tests must pass" from a request the agent might rationalize past into a fact about the world.

**Tooling for hand-off.** `/sprd-handoff` / `scripts/handoff.py --spec <path> --developer @handle` turns hand-off — branch, frontmatter, code-host assignment, starting the agent — into one step, so the moment the loop's roles change hands isn't four manual steps that each get skipped differently. It refuses, changing nothing, unless the spec passes the Definition of Ready, the developer is in the roster and isn't also the spec's own checker, and the team is under its WIP limit (`## WIP Limits` in `cadence-plan.md`) — `--over-limit "<reason>"` overrides the last one and the reason lands in the commit message. The branch, the `status: in-flight` / `developer` commit, and the push all happen over plain `git`, so the local half still works with no code-host access; only the draft PR (and the assignment + review request riding on it) needs the repository's code-host CLI — `gh` on GitHub, `az` on Azure DevOps, chosen by the `origin` remote — and its failure is reported, not fatal. `--open` starts Claude Code on the branch in plan mode; without it, the command prints the exact one to run.

### Beat 3 — Discern: prove, then merge

Written is cheap now; checked is the bar. A change is done when it has been proven against its spec by something other than its author — not when the code exists. The proving climbs a **five-rung checking ladder**, each rung catching what the one below cannot:

| Rung | The check | What it catches that the rung below can't |
|------|-----------|--------------------------------------------|
| 1 | The done-rule in the harness | Sets the bar ("done means checked, not typed"); persuasion only |
| 2 | The agent re-checks each turn | The agent's own mechanical slips: the broken import, the test it broke two steps back |
| 3 | The blocking Stop hook | The agent declaring itself done anyway — it cannot finish with red tests or a broken build. But a hook enforces the tests that exist; it cannot enforce a test nobody wrote |
| 4 | The separate grader | The hole the author was blind to: it grades check-by-check against the spec, not against the tests, so it catches the case the author never thought to test |
| 5 | The human / security gate | The judgment calls no machine should own: the risk acceptance, the product call, the security sign-off on a HIGH change |

Rung 4 is where the bug the author's green test suite hid goes to die — and it only works because Intent wrote checkable acceptance criteria for it to grade against. The ladder is the payoff of the spec.

In the rails, the ladder lands as three layers on every PR:
- **Mechanical gates in CI** (hard blocks): build, tests, lint, 80% coverage on new code.
- **The grader in CI** (required to run, advisory verdict): a fresh agent reads the spec in the diff and posts a check-by-check verdict as a PR comment, pinned to the exact changed lines. It cannot be skipped — "the grader has run" is a required status check — but its verdict does not block. The human Checker reads it and makes the call.
- **The human Checker** (hard block): non-author approval on every PR. On HIGH risk, also a security review pass and a named human sign-off recorded in the PR.

**The merge bar** every change clears:
- CI green (build, tests, lint, coverage)
- The grader has run
- Correctness passed, or a named-human override recorded
- A non-author approval — **the author never approves their own work**, no exceptions; this rule survives every collapse of pod size

A `risk:high` change adds the security workflow pass and a named human sign-off recorded in the PR.

**The depth scales by risk tier.** You do not run every change up all five rungs — that recreates the review bottleneck the loop exists to remove. LOW stops after the grader's advisory pass and a light human look; MEDIUM gets the standard grader-plus-Checker treatment; HIGH goes all the way up. One depth for everything fails in both directions — reading a typo fix as hard as an auth change burns the pod's scarce review attention, and waving an auth change through on a glance ships the instability.

The tier-to-ladder mapping is encoded once in `scripts/risk_model.py` (the single source of truth: every tier blocks on CI, runs the grader, runs correctness, and requires a non-author approval; HIGH adds a security pass and a named sign-off; a gated path forces the security pass regardless of tier). `check_spec.py` enforces it at Intent time — a spec's **Checking Plan** ladder depth must equal its risk tier (a HIGH spec that declares a LOW climb, or omits the security pass and sign-off, fails the Definition of Ready). The tier on the spec is not a label; it sets the climb, mechanically.

**Failed checks come back to the same Orchestrator,** who drives the fix on the same branch. Every gate, including a fresh grader run, runs again on the updated PR before merge. Re-run the gate that flagged the issue to confirm the fix — never self-certify.

**Tooling for "where is this change."** `/sprd-spec-status` / `scripts/spec_status.py --spec <path>` reads a spec's pull request — checks, whether the grader ran and its verdict, whether the security review was required and its result, approvals, and whether it merged — so the answer comes from the code host, not from anyone interpreting the PR by hand or a status field going stale. It reports **who the change is waiting on** in one line, from the first unmet rung of the ladder above ("waiting for a non-author approval; requested from @priya-n 2 days ago"). The grader's PR comment carries a machine-readable `## Acceptance Check Verdicts` block (`harness/profile/rubrics/grader.md`) — one row per acceptance check, `covered` or `not-covered`, that block wins over its own prose if the two ever disagree. No pull request yet is reported, not an error; no code-host access reports what was read locally and says the rest is unavailable, never "not started." Once the PR merges, `spec_status.py` sets the spec's `status` to `merged` in a commit straight onto the default branch — best effort (a protected default branch may reject it, which is reported, not fatal) and idempotent (re-running it once merged changes nothing further).

Merge deploys to the client's dev environment automatically — the rails from Foundation. A true emergency merge past a gate requires the Pod Lead plus one other human, an exception label, and a retro agenda item. Two exceptions in a month means the gate or the specs are wrong — fix that, don't keep excepting.

## Session Continuity

The Build loop spans many sessions. Context windows fill; people pause. The spec is the durable source of truth across sessions — the agent re-reads it every session, so a spec kept current *is* the handoff. Beyond the spec:

- **A spec in flight is the unit of handoff.** One spec = one branch = one PR. A spec's `status` frontmatter moves draft → ready → in-flight → merged, or sideways to deferred (with a `deferred_reason`) when the team deliberately chooses not to build it — a deferred spec never continues to merged, and keeps its number so the hand-over report and decision log stay readable. The spec file IS the progress tracker — `scripts/track_specs.py` derives the backlog (counts by status and risk, the in-flight list, WIP-cap breaches) straight from the specs, so there is no separate progress file to drift from reality. Do not start a new spec while one you own is in-flight and half-built — finishing the in-flight spec before starting the next is how the loop avoids compounding half-done work across sessions. The Build gate reports this backlog as information; it never batch-gates on a count.
- **Session health check.** When `session_health_check.enabled` is true in the profile, run the configured command (via the Bash tool) at session start before touching new work. On failure, do not start new spec work — diagnose and fix the build first (spawn `build-error-resolver` if needed). This catches a broken build before you compound it.
- **Governed specs may carry the sprint keys.** A spec slated into a sprint carries five optional frontmatter keys — `sprint`, `next_owner`, `eng_review`, `data_review`, `depends_on` — written only by `scripts/sprint.py` (through `/sprd-sprint` and `/sprd-refine`), never by hand. They hold enumerations, names and spec ids only; `status` is not one of them and stays hand-moved. A spec without the keys behaves exactly as before. The session-start hook prints the active sprint (`[SHEPHERD-SPRINT] S07 (ready) — "goal" — start → end`) so every session opens knowing the commitment window and its end date.
- **At a session boundary**, leave the in-flight spec's branch and PR in a state the next session can resume from: the spec current, the plan recorded, the failing/passing test state obvious. If the engagement uses a machine-readable handoff file, update it with the in-flight specs, what's blocked, and the next action. The 60 seconds this costs saves 30 minutes of context reconstruction next session.

## The Week: Cadences

Four short meetings replace the ceremony calendar. None asks "what did you do yesterday" — when agents do the building, that answer is "the agents wrote a lot," and the number means nothing. The meetings point at the two things that actually constrain the loop: the clarity of intent going in, and the review queue coming out.

| Meeting | Length | Replaces | What it does |
|---------|--------|----------|--------------|
| **Flow check** (daily) | 10-15 min | standup | The queue number first: how many changes wait for checking, how long the oldest has waited. Walk in-flight changes nearest-done first. Every waiting change gets a Checker; vague specs get flagged back to triage; the WIP cap gets enforced; one commitment each. |
| **Intent triage** (weekly) | 60 min | refinement | Stories become ready specs: vague lines sharpened, silent decisions surfaced onto the decision list, risk tiers assigned, the backlog ordered. Run it with `/sprd-refine` — the agenda first (NOT READY specs, pending Engineering/Data verdicts, overdue decisions), then one spec at a time. The slate it feeds is `/sprd-sprint`. |
| **Retro+** (weekly) | 60 min | retro | Every escaped bug gets the same question — "which check should have caught it?" — and the answer becomes a harness improvement, not a resolution to try harder. |
| **Setup review** (weekly) | 30-60 min | (new) | The week's harness changes merge: `CLAUDE.md` updates, skill and hook improvements, permission tuning — versioned, PR'd, reviewed by the Setup Owner's deputy. |

**Two numbers run the week.** The **WIP cap** keeps the pod from opening more changes than its checking capacity can clear — agents can always write more code; the constraint is proving it. The **review-wait tripwire** is the alarm on the same constraint: when the median wait crosses the agreed threshold, the pod stops starting new work and clears the queue. The security queue is read separately at every flow check — it clears slower, and averaged in with the rest it hides until something HIGH has quietly waited a week. When teams differ enough in checking capacity that one project-wide number hides a slow team's queue, `cadence-plan.md`'s optional `## WIP Limits` table sets both numbers per team instead — `scripts/track_specs.py` reports each team's in-flight count against its own limit, and `scripts/scorecard.py` shows the review-wait numbers against each team's own alarm threshold. A project without that table behaves exactly as before.

## Hardening Passes

Quality in the loop is per-change; some concerns only exist at the integration level — performance under load, end-to-end journeys across many features, penetration testing. The Quality Engineer plans and runs these as **scheduled hardening passes** (typically one mid-Build and one before deployment prep) using the end-to-end (`/e2e`) and security tooling. The first hardening pass is also where the test environment gets added alongside dev. Hardening is scheduled work inside the flow — specs, triage, the loop — not a phase that gates all other work.

A hardening pass runs its own specs through the loop. Use the expander pattern: after each successful integration test run, identify 3–5 untested edge cases (boundary conditions, error paths, concurrent/timing scenarios, data edges — empty, null, max-length, Unicode) and add specs for them. Record findings and the resulting specs in `hardening-pass-notes.md`.

## The Numbers That Steer the Loop

Internal dashboard, baseline-and-trend, no vanity targets:
- **Accepted-as-is rate** — agent work merged without rework. The trust signal: rising means intent and bounds are working.
- **Review wait (median)** — the real bottleneck indicator. If it grows, stop opening streams; more building throughput cannot fix a checking constraint.
- **Rework / revert rate** and **bounce-back-for-unclear rate** — intent quality signals. A spec that bounces back as unbuildable is a triage miss, not an agent failure.
- **Escaped bugs** — every one answered at Retro+ with "which check should have caught it?"
- **The DORA four** — deploy frequency, lead time, change-fail rate, time-to-recover, watched as trends.
- **Security-review wait** — on its own line, always.

**Never tracked, never reported:** velocity, story points, PR count, lines of code. Agents inflate all of them — measured teams have doubled PR volume while actual delivery stayed flat. No activity metrics in client materials, ever; demos and outcomes don't lie.

**Tooling for the scorecard.** `scripts/scorecard.py` records loop outcomes to `.sdlc/metrics/loop-events.jsonl` (`record --type spec_merged|spec_reverted|spec_bounced|escaped_bug|deploy|incident|review_wait`) and renders the scorecard (`report --window-days 14`) for the biweekly steering. It is deliberately separate from the gate-calibration and DoR metric logs — those measure the harness; this measures delivery. When there is no data for a metric it reads "no data," never a fabricated zero. It **refuses** to record the forbidden activity metrics, and `steering-scorecard.md` (the client-facing artifact) carries the never-tracked guardrail. The numbers are baseline-and-trend; the tool computes them, the pod reads the trend.

**The scorecard builds itself.** `scorecard.py import --repo <path> --since <date>` (GitHub) or `import_outcomes.py --repo <path> --since <date>` (either host — GitHub delegates to the same frozen import; Azure DevOps reads Azure Repos through `az`, with `ado-*` event ids that never collide) reads the code host's own history through its CLI — no credential of its own, it reuses whichever sign-in is already on the machine — and appends the same event types `record` writes by hand: every merged PR becomes a `spec_merged` event (accepted-as-is means no commits pushed after the first approval; a PR merged with no review at all counts as accepted-as-is, since nothing was ever asked to be reworked), every reviewed PR's review-request-to-first-approval gap becomes a `review_wait` event (flagged `security` when the PR carries the `risk:high` label — the same label the security workflow gates on), GitHub Deployments become `deploy` events, and closed `incident`-labelled issues become `incident` events. Importing twice over the same window adds nothing new — every imported event carries the host's own id and is matched on it. A period with no activity reports "no data," never a zero, and any failure to reach the host (no network, no auth) aborts the whole import before anything is written, leaving the existing log untouched. What Azure DevOps does not record is said rather than zeroed: a review with no request timestamp yields a `review_wait` event with no `wait_hours` key, counted on its own line, and a category that could not be read reports "not imported". Hand-recording with `record` still works exactly as before; the two are complementary, not a replacement.

## Leaving the Loop

There is no batch exit gate. The loop ends when a **human declares the backlog feature-complete** — every story that the engagement committed to has ridden the loop and merged. Sprints (`/sprd-sprint`) are commitment windows *inside* Build — a closed sprint reports kept / carried / dropped for its own slate and never suggests leaving the loop; the declaration is release-scoped, not sprint-scoped. That declaration produces `phase7-handoff.md`: the entry package for Phase 7 Documentation. The handoff names what was built, the current state of the system in dev, the open questions carried forward, the deferred items with their rationale, and anything the documentation phase must cover that surfaced during Build.

## Standalone or Workflow

In the workflow, the loop reads `.sdlc/state.yaml`, the spec backlog, the risk-tier map, and the cadence calendar from Foundation. It also runs standalone: a single spec can ride the full three-beat loop against any repo with no `.sdlc/` present — write the spec to `specs/NNNN-name.md`, assign a provisional risk tier, run plan-mode → bounded build → checking-ladder → non-author review, and note the missing engagement context in the spec header. The loop's discipline (no spec/no build, plan first, the author never approves their own work, the merge bar) holds identically in both modes; only the surrounding cadences and dashboards require the full engagement.

## Artifact Specifications

### `phase7-handoff.md` (REQUIRED)
Produced by the human feature-complete declaration. Must contain ALL of:
- **What was built** — the merged spec backlog, organized for a reader who wasn't in the room
- **System state** — what is running in dev and verified
- **Open questions** — carried under their original IDs into Documentation
- **Deferred items** — anything not built, with rationale
- **Documentation focus** — what Phase 7 must cover based on what surfaced during Build (drift from the Phase 2 contracts, novel patterns, operational concerns)

### Optional Artifacts
- `specs/` — the spec files (`specs/NNNN-name.md`), the durable per-change record. These live in the repo, not only under `.sdlc/`.
- `build-summary.md` — a rolling summary of merged work, useful for the weekly client async summary and the feature-complete declaration
- `hardening-pass-notes.md` — per hardening pass: scope, findings, the specs raised, and their resolution

## Exit
The Build loop has **no artifact exit gate**. It is left by a human feature-complete declaration that produces `phase7-handoff.md`. `/sprd-gate` for this phase verifies only that `phase7-handoff.md` exists and is complete — it does not batch-check the build, because checking already happened per change inside the loop.

## Next Phase
The Build loop hands off into **Phase 7: Documentation** (`phases/07-documentation.md`) — when Build is feature-complete, the close begins: proving a stranger can understand, run, and operate the system from its documentation alone. `phase7-handoff.md` is the entry package.

## Guidance
- **Skipping Intent** — typing the wish straight to the agent ("add rate limiting, go") — builds something plausible and fast, and the undescribed case is the one it gets wrong. Everything enters through a ready spec, every time.
- **The author grading itself** is checking theater — it catches nothing the author didn't already think of. The author never approves, no exceptions.
- **One review depth for everything** recreates the bottleneck (every typo behind a human) or ships the incident (auth waved through on a glance). The tier sets the climb.
- **"Too small to bother"** is the expensive case. The discipline is the same at forty lines as at four hundred.
- **The unbounded handoff** — no scope, no named pattern, no permissions — makes the agent fill every gap with a guess and touch three things nobody wanted touched.
- **Fanning out a build** clobbers shared files. Fan out only to explore; one agent writes shared code.
- **The rotting spec** lies to the next agent and the next human. The spec changes in the same PR as the behavior.
- **A hook that passes by hiding the failure** (skipping the flaky test to go green) is the rail lying to you. Fix the cause; never suppress the check.
- **Ignoring the queue number** silts the loop up invisibly until nothing merges. The tripwire makes stopping automatic, not heroic.

## Coaching Prompts

When operating in coaching mode (`/sprd-coach`) for this loop:

### Opening (starting Build)
- "What's the next ready spec? Does every acceptance check pass the vague-line test — could two people build different things from it?"
- "What's the risk tier, and what's the one existing pattern this change should reuse?"
- "What are the silent product decisions in this story that nobody's answered yet?"

### Progress Check (specs in flight)
- "How long has the oldest PR waited for a Checker? Are we past the review-wait tripwire?"
- "Did the grader catch anything the tests missed on the last merge? That's rung 4 doing its job."

### Ready Check (approaching feature-complete)
- "Is the backlog actually feature-complete, or are there specs hiding as 'too small to spec'?"
- "Has every escaped bug been answered at Retro+ with 'which check should have caught it?'"
