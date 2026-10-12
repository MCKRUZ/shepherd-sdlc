# The delivery harness — a tour of what's in this repo

This repo contains more than product code. It carries a **delivery harness**: committed files
that set the rules for how work gets built, checked, and shipped here — whether a person or an
AI is doing the work. This page explains each piece in plain terms.

## The 60-second version

| Piece | What it does for you |
|---|---|
| `CLAUDE.md` | The working agreement the AI reads at the start of every session |
| `.claude/settings.json` | What the AI may do freely, must ask about, and can never do |
| `.claude/hooks/` | Barriers: the AI can't finish on a broken build or push unreviewed code |
| `.claude/agents/` | Six AI specialists it can call — two arrive automatically |
| `.claude/skills/` | The team's runbooks for recurring jobs (specs, tests, bugs, PRs) |
| `.mcp.json` | Shared plug-ins that give the AI extra abilities — approve once, done |
| `.github/workflows/` (GitHub) / `.azuredevops/pipelines/` (Azure DevOps) | The pull-request checks that apply to *everyone*, human or AI |
| `specs/`, `.sdlc/`, `infra/` | Feature specs, project phase tracking, infrastructure starter |

## Two ideas explain the whole design

**1. The rules live in the repo, not on anyone's machine.** Clone the repo and you have
everything — the same guardrails, the same AI crew, the same checks as every teammate. Nothing
depends on how your laptop is set up.

**2. Enforcement happens twice.** Files under `.claude/` stop the **AI** on your machine,
early and cheaply. The pull-request checks stop **everyone** at the server, no exceptions.
Same rules, two layers — the AI can't skip the first, and nobody can skip the second.

---

## CLAUDE.md — the working agreement

Every AI session in this repo starts by reading this file: how the team works, the coding
standards for this stack, what the project's words mean. That's why the AI behaves the same
for every developer — everyone's sessions start from the same page.

**Under the hood:** assembled during setup from the standard's base, the stack's coding
standards, and the customer profile. The `{{TOKENS}}` were filled in once at setup; the file
now belongs to this repo.

## .claude/settings.json — the three buckets

Everything the AI could do falls into one of three buckets:

- **Do freely** — building, testing, reading history. Safe, reversible, no nagging.
- **Ask first** — pushing code, or touching sensitive ground: login/security code, database
  migrations, infrastructure, the CI checks themselves. A human clicks yes in the moment.
- **Never** — force-pushing, wiping work, piping downloads into a shell, reading secrets
  files. Refused outright, no prompt.

Two details worth knowing. Your personal settings file can *loosen* "do freely" for yourself,
but can never cancel a team "never" — hard limits are team property. And the AI changing its
own guardrails (this file, or the hooks) is itself an ask-first action.

## .claude/hooks/ — the barriers

A written rule like "always review before pushing" is exactly the kind of thing that gets
forgotten under pressure. So these rules aren't written — they're enforced by machinery:

- **The done-gate.** The AI cannot end its work turn while the build is broken. It says "I'm
  done," the machinery builds the code, and if the build is red the turn is refused and the
  errors are handed back. (Turns that only touched documents skip the build.)
- **The ship-gate.** The AI cannot push code until the required reviews have provably run —
  against the exact version being pushed. Change the code afterward and the evidence no longer
  matches, so the gate demands a fresh review. No "I reviewed it earlier, trust me."

One boundary to remember: these barriers only stop the AI. A human pushing from their own
terminal walks right past them — on purpose. The pull-request checks below catch everyone.

**Under the hood:** each hook is a small script (Windows and Mac/Linux versions). If the
*environment* is broken (a tool missing), they warn and step aside rather than trapping you.
If the *code* is provably broken, they block. Per-repo tuning is via environment variables —
see `.claude/hooks/README.md`.

## .claude/agents/ — the AI crew

Six specialists the AI can hand work to. Each starts with fresh eyes — it sees the code and
the requirements, not the reasoning that produced the code. That's what makes its review
honest.

| Specialist | When it appears | What it does |
|---|---|---|
| `planner` | when asked | plans bigger features before any code is written |
| `architect` | when asked | weighs design decisions that are expensive to reverse |
| `grader` | before a PR | scores the code against the requirements — advice, not a veto |
| `security-reviewer` | **automatically** | reviews any change to login, payments, identity, or secrets — it flags findings during the session; the server-side security check is what blocks a merge |
| `build-error-resolver` | **automatically** | fixes a broken build with minimal changes |
| `debugger` | when asked | tracks down the root cause of a weird failure |

Only the two automatic ones arrive uninvited — they cover the two situations where
*forgetting to ask* is the real risk. The rest wait to be called, so the AI isn't constantly
spawning helpers you didn't ask for.

**Repos with a user interface get a seventh specialist: `ux-reviewer`.** It reviews screens
the way the grader reviews code — do all the states exist (loading, empty, error, success), is
it keyboard-reachable, does it follow the house pattern — and drives the changed flow in a
real browser when it can. On React and Angular repos it arrives framework-aware (it also catches the
framework's own UX failure modes). Advisory, like the grader: it reports, a human decides.

## .claude/skills/ — the runbooks

Standard procedures the AI follows when the situation matches. The rules they lock in:

- **No spec, no build** — a feature starts as a written spec with checkable acceptance criteria (`spec-writer`).
- **A bug fix starts with a failing test** — reproduce first, fix second, prove third (`diagnose`).
- **Tests explain *why*** — every test maps back to a requirement (`test-writer`).
- **New code follows the house pattern** — find how this codebase already does it and copy that, don't invent (`api-pattern`).
- **PRs tell the reviewer what to check** — the change mapped to the requirements, with a test plan (`pr-writer`).
- **AI-powered features get a fixed test suite before they're built** (`eval-builder`).

Each runbook can only use the tools its job needs — the spec writer, for example, can't run
commands at all.

## .mcp.json — the shared plug-ins

Plug-ins give the AI extra abilities. This file is the team's shared set: open the repo once,
approve the list once, and they're simply there — the same for every developer.

| Plug-in | What it adds | Comes with |
|---|---|---|
| `context7` | looks up accurate docs for code libraries | every repo |
| `sequential-thinking` | a step-by-step reasoning aid for hard problems | every repo |
| `playwright` | drives a real browser, for end-to-end testing | every repo |
| `microsoft-learn` | official Microsoft and Azure documentation | .NET repos |
| `github` | reads and manages issues, PRs, and CI runs — you sign in with your own GitHub account | GitHub repos |
| `azure-devops` | reads work items, PRs, and pipelines — you sign in with your own account | Azure DevOps repos |

Two hard rules protect this file. **Exact versions only** — a plug-in that always pulls
"latest" is an open door for tampered software. **No passwords or keys, ever** — plug-ins that
need access sign in per developer, with that developer's own account.

Personal plug-ins stay in your own machine's config — this file is only for what the whole
team should share. Tools that install themselves (like GitNexus) come with printed
instructions instead: `.claude/tools/<tool>/SETUP.md`.

## The pull-request checks — .github/workflows/ or .azuredevops/pipelines/

On GitHub these are Actions workflows in `.github/workflows/`; on Azure DevOps the same
checks are Azure Pipelines in `.azuredevops/pipelines/`. Either way they run at the server
and apply to every change, no matter who or what wrote it. The principle: **work can be
proposed by anyone; only a gate lets it through.**

| Check | Power | Why |
|---|---|---|
| Build & tests (starts with a secret scan, ends by enforcing the coverage floor) | **blocks** | a broken build, a committed credential, or coverage below the floor is a fact — facts block |
| Spec gate | **blocks** | a source change with no spec is a fact — the "no spec, no build" rule, enforced by a machine; a labeled, recorded exemption is the only way past |
| Grader (AI review vs. the standards) | **advises only** | an AI's "looks good" must never replace the human approver's judgment — the review must *happen*, but a human weighs it |
| Correctness review | **blocks** | only on a concrete, demonstrable defect — and a human can overrule it with a visible, recorded label |
| Security review | **blocks** | on serious findings in sensitive code |
| Deploy to dev | ships | after a green merge; rolls itself back on failure |
| Eval checks | blocks / advises | for AI-powered features: blocks if quality measurably drops |

On top sits **branch protection** (on Azure DevOps: **branch policies** — same idea, the
platform's own mechanism): the blocking checks are mandatory, and a person who didn't
write the change must approve it. Everything above in one sentence: *machines verify the
facts; a human makes the call.*

Before trusting any of this, run the drills in `.github/RAILS.md`: deliberately break the
build, plant a defect, commit a fake secret — and watch each gate catch it. A gate you've
never seen catch anything is decoration.

## The smaller pieces

- **`specs/`** — one spec per feature. The starting point of all build work.
- **`.sdlc/`** — which project phase we're in, plus the record of decisions and artifacts.
- **`.github/profile/rubrics/`** (GitHub) / **`.azuredevops/rails/rubrics/`** (Azure DevOps) —
  the written standards the AI reviewers judge against. On Azure DevOps the override and
  accepted-risk ledgers live beside them in `.azuredevops/rails/`.
- **`scripts/rails/`** — helper scripts the checks use (change scoping, plus the one-time
  branch setup: `apply-branch-protection.sh` on GitHub, `configure-branch-policies.sh` on
  Azure DevOps).
- **`infra/`** — an infrastructure starting point. Adapt it; don't use it as-is.
- **`.claude/harness-manifest.json`** — the install receipt: which harness version this repo
  has and a fingerprint of every file *as installed*. It's how an upgrade can tell "still
  factory-original, safe to update" from "this repo adapted it, hands off."
- **`docs/harness.md`** — this page.

## Where it came from, how it updates

The harness was installed once from a plugin and then adapted to this repo. There's no live
connection back: nothing upstream can change this repo behind your back. Updating is a
deliberate act — update the plugin, run `/sprd-upgrade` — and the manifest above is what
keeps it safe: files you never touched are brought forward; files this repo adapted are left
alone; a file that changed on *both* sides is reported side-by-side for a person (or the AI,
with a person watching) to merge deliberately. Nothing is ever silently overwritten.

A few things are personal-machine only and stay out of the repo on purpose: review evidence,
your personal settings, and self-installing tools' data.
