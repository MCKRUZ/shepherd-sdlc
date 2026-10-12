# Shepherd

Shepherd is an SDLC orchestration plugin for Claude Code. It drives projects through a structured software development lifecycle — gated opening and closing phases around a continuous Build loop — with company-configurable profiles, compliance gates, and quality enforcement.

## Why This Exists

No existing tool combines specification-driven development + quality enforcement + compliance gates + company configurability into one executable workflow. This plugin makes the AI-SDLC methodology executable inside Claude Code.

## Features

- **9 SDLC phases** — Discovery, Requirements, Design, Foundation, the continuous **Build loop**, Documentation, Deployment, Monitoring, Close & Transfer. The gap where batch Implementation/Quality/Testing used to be is intentional — checking happens per change inside the Build loop, never as a later batch phase.
- **Project type routing** — testing, deployment, and monitoring adapt automatically based on `project_type` (service, app, library, skill, cli)
- **Company profiles** — YAML configs for stack, quality thresholds, compliance, conventions
- **7-gate validation** — Integrity, completeness, metrics, compliance, consistency, quality checks at every transition, plus the phase's own exit criteria rendered for the human who signs
- **Frozen layers** — Token-efficient phase summaries enabling cross-phase context continuity
- **3-tier context architecture** — Foundation (always), frozen layers (per-phase), references (on-demand)
- **Narrative enhancement** — Optional stakeholder-friendly `.narrative.md` companions for technical artifacts
- **Conversational coaching** — Adaptive dialogue mode for guided phase completion
- **NFR measurement basis enforcement** — Every numeric threshold must declare its measurement source; aspirational thresholds require an agreed validation plan in the Build loop
- **Test traceability** — the Build loop requires scenario-to-requirement mapping and redundancy audit before test execution
- **Compliance enforcement** — SOC 2, HIPAA, GDPR, PCI-DSS gate definitions
- **Skill orchestration** — Maps phases to existing skills (`/deep-plan`, `/deep-implement`, `/tdd`, `/code-review`, `/security-review`, `/e2e`)
- **State machine** — Tracks progress in `.sdlc/state.yaml` with full audit trail
- **Artifact checksums + dirty tracking** — SHA-256 hashes detect changed artifacts; gate checks skip unchanged files for faster validation
- **Smart repair** — Gate failures on structural issues (missing templates, placeholders) are auto-fixed before escalating to human
- **Dependency graph enforcement** — Section dependency DAG validated in the Build loop; circular dependencies detected; implementation order enforced
- **Multi-perspective review** — `/sprd-review` with adversarial, edge-case, and council modes for thorough artifact review
- **Brainstorming techniques** — SCAMPER, reverse brainstorming, constraint removal, and 3 more structured ideation methods with anti-bias protocol
- **Brownfield detection** — Auto-detects existing codebases and generates workspace analysis before Discovery begins
- **Structured error specs** — P0/P1 requirements must define Accepts/Returns/Errors explicitly
- **Cross-artifact validation** — File-level reference checking between artifacts (SHOULD severity)
- **Question-to-file audit trail** — Open questions written to persistent markdown files for team collaboration
- **Test expansion protocol** — Healer (diagnose failures), Expander (add edge cases), bug-to-test pipeline (RED first)
- **Parallel review resolution** — Batch review findings by file, resolve in parallel, re-verify after fix
- **Advanced elicitation** — Constraint analysis, inverse thinking, pre-mortem, 5 whys, and more for coaching mode
- **Phase-aware context** — Hooks inject current phase reminders and conventions
- **Session health check** — Opt-in pre-flight build verification at session start (Build loop) catches broken builds before the agent compounds them with new work
- **Visual regression testing** — Optional screenshot capture during Build-loop E2E testing with baseline comparison (manual or pixel-diff)
- **Single-change guardrail** — Explicit constraint preventing simultaneous work on multiple specs in the Build loop unless explicitly parallelizable
- **Phase-scoped evaluation criteria** — Quality rubrics that apply to non-code artifacts (requirements, design, foundation) in addition to code
- **Empirical metrics logging** — JSONL instrumentation in gates, frozen layer validation, and section evaluation for evidence-based harness optimization
- **Discipline seats** — Conditional, interview-driven drafting seats that stop at a human confirmation: `/sprd-feature` (epic → channel-aware feature brief, one channel per spec), `/sprd-rules` (business rules as a BR-NN decision table with a named approver, plus golden scenarios), `/sprd-data` (PII-classified data contract that drives the risk tier, readiness, lineage), `/sprd-experience` (journey, surface layout, per-channel interaction contract), `/sprd-channel` (binds a spec to its channel and injects the acceptance dimensions). Sign-offs recorded at the phase advance.
- **Sprint team layer** — Additive, advisory sprints over the spec backlog: `/sprd-sprint` slates a *count* of specs by risk-tier mix into a two-week commitment window (`.sdlc/sprints/SNN.md`), readies the sprint only when every slated spec clears the Definition of Ready **and** its independent Engineering and Data verdicts, shows the advisory build order and next-up, and closes with kept / carried / dropped — each carry or drop with a named human and a reason. `/sprd-refine` renders the refinement agenda (NOT READY specs and why, verdicts pending with business-day age, unacknowledged handoffs, overdue `DL-NN` decisions) and refines one spec or the whole slate. Self-contained planning and review pages (`sprint-SNN-planning.html` / `-review.html`), an `[SHEPHERD-SPRINT]` session-start line, carry-over recurrence in `/sprd-retro`. Never a gate, never gated, never writes `state.yaml`; velocity, story points, estimates, effort and hours are refused (exit 2); no per-person aggregation exists.
- **Document intake** — Opt-in Phase 0 corpus analysis for external reference materials (RFPs, API specs, vendor docs, compliance handbooks) with per-document summaries, DOC-NNN traceability IDs, token-budgeted session-start index (Tier 1.5), and Phase 1 requirement-to-source linking

## Installation

### Via the plugin marketplace (recommended)

One marketplace add, one install — brings the orchestration commands **and** the delivery harness:

```
/plugin marketplace add MCKRUZ/shepherd-sdlc
/plugin install shepherd@mckruz
```

Then, per project: `/sprd-setup` initializes `.sdlc/` **and installs the full delivery harness**
(governance `CLAUDE.md`, `.claude/{settings,hooks,agents,skills}`, 7 CI workflows in
`.github/workflows/` — 5 rail gates plus 2 eval workflows — of which five checks (build-and-test,
spec-gate, grader, correctness-review, security-review) block at merge via the
branch-protection ruleset, and `infra/` starters). To add or refresh just the
harness in an existing repo, use `/sprd-harness`. Requires Claude Code v2.1.196+ (`source: "."`).

### As a Claude Code Skill (local dev)

```bash
# Clone the repo
git clone https://github.com/MCKRUZ/shepherd-sdlc.git

# Symlink to your Claude Code skills directory
# Windows
mklink /D "%USERPROFILE%\.claude\skills\shepherd" "path\to\shepherd-sdlc"

# macOS/Linux
ln -s /path/to/shepherd-sdlc ~/.claude/skills/shepherd
```

### Dependencies

The plugin uses Python scripts via [uv](https://github.com/astral-sh/uv):

```bash
# Install uv (if not already installed)
pip install uv
# or
brew install uv

# Install script dependencies
cd shepherd-sdlc/scripts
uv sync
```

### Code hosts

The plugin talks to the repository's code host for the pull-request-facing work — a spec's
live status, the hand-off's draft PR, the connection report, branch policies, pipeline evidence,
the gates' credentials, and the scorecard import. Two hosts are supported, and **the repository
chooses**, by its `origin` remote: a GitHub remote uses the GitHub CLI (`gh`), an Azure DevOps
remote (`dev.azure.com`, `*.visualstudio.com`, `ssh.dev.azure.com`) uses the Azure CLI (`az`)
with the `azure-devops` extension. Neither CLI is required to open a project, run the gates, or
read a board built from the spec files; it is required only for the features that read or write
pull requests, and each of those says which CLI it is missing instead of failing.

| Feature | GitHub | Azure DevOps |
|---|---|---|
| `/sprd-spec-status`, `/sprd-handoff` (the draft PR and reviewer request), `connection_report.py`, `pipeline_proof.py`'s PR reads, `gate_auth.py status` | `gh`, signed in | `az` + `azure-devops` extension, signed in |
| Scorecard import | `scorecard.py import` or `import_outcomes.py` | `import_outcomes.py` |
| `gate_auth.py set` / `clear` | `gh` | prints the manual `az` command (variable groups are not written from here) |
| Pipelines, secrets, `/sprd-doctor` | follow the **installed CI pack** (`.claude/harness-manifest.json`), not the remote — a GitHub repository on Azure Pipelines is a legitimate mix and is reported, never resolved silently |

Setting up `az`: `az extension add --name azure-devops`, then sign in. The CLI's **default account
decides the token**, so a guest or contractor identity in the organisation's tenant must sign in
as that identity with `az login --allow-no-subscriptions`; and an identity that has never opened
the organisation in a browser gets HTTP 403 "identity … has not been materialized" until it has
signed in once there interactively. `code_host.py --repo <path>` says which host was detected,
why, and whether its CLI answered.

Two optional files complete the Azure DevOps side. Azure DevOps names people by sign-in identity
(UPN), not by handle, so a roster entry in `.sdlc/team.yaml` gains an optional `email:` — the only
way a PR's reviewer is resolved to an `@handle`; nothing guesses it from a display name, and a
checker without one is reported as an `assignment_error` on hand-off, not invented. When the
remote cannot be recognised (GitHub Enterprise Server, an unusual proxy), `.sdlc/code-host.yaml`
pins the host for that clone — written with
`uv run scripts/set_setting.py --repo <path> code-host --host azure-devops` (plus
`--organization`, `--project`, `--repository` when the remote cannot be parsed at all). A one-off
override is `--host` on any host-touching script, or the `SHEPHERD_CODE_HOST` environment
variable (`SDLC_CODE_HOST` is still read, so existing shells and CI keep working).
Full rules: `references/code-host-providers.md`.

## Quick Start

```
1. /sprd-setup          → Select profile, initialize .sdlc/ AND install the delivery harness
2. /sprd                → See Phase 0: Discovery guidance
3. Create artifacts     → Write problem-statement.md in .sdlc/artifacts/00-discovery/
4. /sprd-gate           → Check if exit criteria are met
5. /sprd-next           → Advance to Phase 1: Requirements
6. /sprd-status         → View progress dashboard
```

## Documentation

For in-depth technical documentation, see the guides in [`docs/`](docs/):

| Guide | Description |
|-------|-------------|
| [Architecture](docs/architecture.md) | Plugin anatomy, component relationships, data flow diagrams, two-directory model, progressive disclosure strategy |
| [Phase Lifecycle](docs/phase-lifecycle.md) | All 9 phases in depth — workflows, artifacts, HITL gates, skills, agents, handoff protocol, project type adaptations |
| [Gate System](docs/gate-system.md) | 7-gate validation — integrity, completeness, metrics, compliance, consistency, quality, exit criteria — severity levels, override protocol |
| [Profiles](docs/profiles.md) | Schema reference (every field), built-in profiles, custom profile creation, compliance framework integration, evaluation criteria |
| [Commands](docs/commands.md) | All 30 slash commands — internal flow, state changes, Python scripts called, error scenarios, examples |
| [Agents](docs/agents.md) | 13 custom agents + built-in subagent orchestration, phase-to-agent mapping, parallel execution rules, mandatory spawns |
| [State Machine](docs/state-machine.md) | state.yaml format, transition rules, history tracking, the spec backlog, sprint records (`.sdlc/sprints/`) |
| [Templates & Artifacts](docs/templates-artifacts.md) | Template directory structure, per-phase artifact details, handoff document protocol, artifact lifecycle |
| [Scripts](docs/scripts.md) | All Python scripts (incl. `phase_model.py`, the phase-identity source of truth) — CLI args, inputs/outputs, exit codes, gate implementation details, uv runtime |
| [Integrations](docs/integrations.md) | How /deep-plan, /deep-implement, /tdd, /code-review map into SDLC phases, artifact transformation pipeline |
| [Hooks](docs/hooks.md) | Session-start and phase-inject hooks — what they read, what they inject, the active-sprint line, convention reminders |

## Commands

| Command | Purpose |
|---------|---------|
| `/sprd-setup` | Interactive setup wizard — select profile, initialize project |
| `/sprd` | Show current phase guidance, next action, required artifacts |
| `/sprd-status` | Progress dashboard with phase table and completion % |
| `/sprd-gate` | Run 7-gate exit criteria check (does not advance) |
| `/sprd-next` | Advance to next phase if all MUST gates pass |
| `/sprd-enhance` | Generate narrative companions for stakeholder review (optional) |
| `/sprd-coach` | Interactive coaching mode — adaptive dialogue for current phase |
| `/sprd-intake` | Catalog and summarize an external document corpus (Phase 0, opt-in) |
| `/sprd-brief` | Prep a stakeholder workshop brief from the document corpus |
| `/sprd-spec` | Author a ready Build-loop spec (`specs/NNNN-name.md`) and enforce the Definition of Ready |
| `/sprd-sprint` | Sprint board — slate N specs by risk-tier mix, ready the sprint (DoR + Eng/Data verdicts), close with kept / carried / dropped; advisory, never a gate |
| `/sprd-refine` | Refinement agenda for the sprint's specs — DoR gaps, pending verdicts, overdue decisions; refine one spec or the slate; record Eng/Data verdicts |
| `/sprd-phase-report` | Generate phase HTML report with artifact inventory |
| `/sprd-review` | Multi-perspective artifact review (council, adversarial, or edge-case modes) |
| `/sprd-audit` | Analyze gate effectiveness across completed phases |
| `/sprd-feature` | Decompose an epic into channel-aware features and specs (`feature-brief.md`) |
| `/sprd-experience` | Author per-channel journeys, surface layout, and the channel interaction spec |
| `/sprd-data` | Author the data contract, data-readiness, and lineage/audit (Data) |
| `/sprd-rules` | Capture business rules (BR-NN) and golden scenarios (SCEN-NN) (Bizreq) |
| `/sprd-channel` | Bind a spec's `channel:` and inject that channel's acceptance dimensions |
| `/sprd-evals` | Author a versioned golden set next to a spec (wraps the harness eval-builder) |

## Profiles

### microsoft-enterprise
Full enterprise stack with compliance:
- **Stack:** C#/.NET 10, Angular 22, SQL Server, Azure
- **Quality:** 80% coverage minimum, 100% critical paths, TDD required
- **Compliance:** SOC 2 gates at every phase transition
- **Conventions:** Conventional commits, immutable patterns, no console.log
- **Health check:** `dotnet build --no-restore --verbosity quiet` at session start (Build loop)
- **Visual verification:** Screenshot capture with manual baseline comparison
- **Evaluation criteria:** Phase-scoped rubrics for requirements (testability, traceability), design (ADR completeness, interface specificity), foundation (section plan verifiability), and Build-loop code (Result pattern, immutable state, FluentValidation, API docs)

### ado-enterprise
microsoft-enterprise's stack, hosted on Azure DevOps:
- **Stack:** C#/.NET 10, Angular 22, SQL Server, Azure (identical to microsoft-enterprise)
- **Repos & CI/CD:** Azure Repos + Azure Pipelines (`.azuredevops/pipelines/`, branch policies via `az repos policy`)
- **Quality / Compliance / Conventions:** same as microsoft-enterprise (80% coverage, TDD, SOC 2 gates)
- **Install is platform-aware:** the harness installer ships no GitHub payload to an ADO
  repo — no `workflows/`, rulesets, or `CODEOWNERS`. Rubrics and the other rail-governance
  content land in `.azuredevops/rails/` instead of `.github/`, matching what the Azure
  Pipelines pack actually reads.
- **`/sprd-doctor` is pack-aware:** it checks an ADO install with `az` (variable groups,
  branch policies) and never asks it to authenticate `gh`. PR-flow rails (the review-gate
  hook, `pr-writer`) recognize `az repos pr create` the same way they recognize `gh pr
  create`.
- **The code host is read through `az` too:** `/sprd-spec-status` (checks, grader verdict,
  approvals, who it is waiting on), `/sprd-handoff`'s draft PR with the checker as a required
  reviewer, the connection report, branch policies, pipeline evidence and the scorecard import
  (`import_outcomes.py`) all read and write Azure Repos pull requests. The repository's
  `origin` remote decides the host; see **Code hosts** under Installation.

### ado-enterprise-python
ado-enterprise's Python sibling — same rails, FastAPI + React stack:
- **Stack:** Python 3.13 / FastAPI / SQLAlchemy 2.0 / pytest (uv-managed); TypeScript / React / Redux Toolkit / Playwright
- **Repos & CI/CD:** Azure Repos + Azure Pipelines (identical rails to ado-enterprise); Azure Container Apps
- **Database:** setup-time choice — Azure Database for PostgreSQL (default) or Azure SQL, Alembic migrations either way; `/sprd-setup` asks and edits the frozen profile
- **Quality / Compliance / Conventions:** same bar as ado-enterprise (80% coverage, TDD, SOC 2 gates verbatim), with the python pack's 400-line file cap
- **Health check:** `uv run --frozen --no-sync python -m compileall -q src` at session start (Build loop)
- **Evaluation criteria:** same phase-scoped rubrics for requirements/design/foundation; Build-loop code criteria are Python/React — Pydantic boundary validation and immutable Redux Toolkit state (fail), typed public signatures, domain exceptions, API contract docs (warn)

### starter
Minimal profile for quick start:
- **Stack:** Configurable (defaults to TypeScript/Node)
- **Quality:** 60% coverage minimum, no TDD requirement
- **Compliance:** None
- **Conventions:** Conventional commits

### creative-tooling
Python profile for creative-pipeline tooling (ComfyUI technique registry / inventory projects):
- **Stack:** Python (uv-run scripts), pytest
- **Quality:** 80% coverage minimum, TDD + code review + security review required, 400-line file cap
- **Compliance:** None (audit trail kept)
- **Evaluation criteria:** Registry/profile schema compliance, skill prompt clarity, inventory
  resolution via `inventory.resolve()`, cross-reference integrity, data freshness

### Creating Custom Profiles
Copy `profiles/starter/profile.yaml` and modify for your stack. Validate with:
```bash
uv run scripts/validate_profile.py profiles/my-profile/profile.yaml
```
See `profiles/_schema.yaml` for the full schema.

## Project Types

Phase 0 captures `project_type`, which is stored in `state.yaml` and controls how testing (in the Build loop), Deployment, and Monitoring execute:

| Type | Description | Testing (Build loop) | Deployment (8) | Monitoring (9) |
|------|-------------|----------------------|----------------|----------------|
| `service` | Backend API / server process | Unit + integration + E2E + API contract tests | Staging server deploy + DB migrations | Full infrastructure monitoring + alerting |
| `app` | User-facing application with UI | Same as service | Same as service | Same as service |
| `library` | Shared code package / SDK | Unit tests for public API surface | Package registry publish | Download counts + issue triage |
| `skill` | Claude Code skill / AI plugin | Scenario-based testing against requirement list | File distribution + install verification | Qualitative feedback channels + issue triage |
| `cli` | Command-line tool | Unit + integration + invocation tests | Binary distribution | Same as library |

## SDLC Phases

| # | Phase | Primary Skills | Key Artifacts |
|---|-------|---------------|---------------|
| 0 | Discovery | `/plan` | problem-statement.md, constitution.md (incl. project_type) |
| 1 | Requirements | `/deep-project` | requirements.md, non-functional-requirements.md (with Measurement Basis) |
| 2 | Design | `/deep-plan` | design-doc.md, ADRs |
| 3 | Foundation | `/deep-plan` | foundation-report.md, risk-tier-map.md, cadence-plan.md, build-handoff.md |
| build | Build Loop | `/tdd`, `/code-review`, `/security-review`, `/e2e` | `specs/NNNN-*.md`, phase7-handoff.md (no batch gate — human declares feature-complete) |
| 7 | Documentation | `/update-docs` | README, RUNBOOK |
| 8 | Deployment | CI/CD | release notes (approach varies by project_type) |
| 9 | Monitoring | Manual | monitoring config (approach varies by project_type) |
| close | Close & Transfer | — | final-handoff-report.md, harness-audit.md, close-gate-evidence.md, access-revocation-checklist.md |

## 7-Gate Validation System

Every phase transition runs through seven gates:

1. **Integrity** — Required artifacts exist and are well-formed
2. **Completeness** — Artifacts contain all required sections, no placeholders
3. **Metrics** — Quantitative thresholds met (coverage, file size)
4. **Compliance** — Correct labeling (priorities, ADR status, compliance mapping)
5. **Consistency** — Locked metrics checked against frozen layers from prior phases
6. **Quality** — Phase-scoped evaluation criteria from profile (e.g., requirement testability in Phase 1, ADR completeness in Phase 2, code patterns in the Build loop)
7. **Exit criteria** — The phase's own prose exit conditions from the registry, rendered as review items for the human who signs the advance

Gates 1–6 pass or fail. Gate 7 always reports REVIEW: its conditions are judgments ("The rails are proven, not just present") that no script can settle, so it shows the approver the checklist rather than deciding for them. Phases 0–2 declare no prose conditions, so Gate 7 is silent there.

All gate results are logged to `.sdlc/metrics/gate-log.jsonl` for empirical tracking of gate effectiveness.

Gates have severity levels:
- **MUST** — Blocks transition if failed
- **SHOULD** — Generates warning
- **MAY** — Informational

## Project Structure

```
shepherd-sdlc/
├── plugin.json              # Plugin manifest
├── SKILL.md                 # Main skill entry point
├── commands/                # 32 slash commands (/sprd, /sprd-setup, /sprd-status, /sprd-next, /sprd-gate, /sprd-enhance, /sprd-coach, /sprd-review, /sprd-intake, /sprd-brief, /sprd-spec, /sprd-spike, /sprd-sprint, /sprd-refine, /sprd-handoff, /sprd-spec-status, /sprd-audit, /sprd-audit-artifacts, /sprd-channel, /sprd-data, /sprd-doctor, /sprd-evals, /sprd-experience, /sprd-feature, /sprd-harness, /sprd-phase-report, /sprd-refresh, /sprd-retro, /sprd-revise, /sprd-rules, /sprd-upgrade, /sprd-version)
├── agents/                  # 14 agents (orchestrator, requirements-analyst, compliance-checker, section-evaluator, narrative-enhancer, gate-repair, multi-reviewer, discovery-analyst, document-summarizer, feature-architect, visual-designer, conversation-designer, data-analyst, bizreq-analyst)
├── profiles/                # Company/stack YAML profiles
├── channels/                # Channel descriptor library (ag-ui, voice, chat) + schema
├── phases/                  # Phase definitions (0,1,2,3,build,7,8,9,close)
├── references/              # Progressive disclosure docs
├── templates/               # Artifact templates
├── scripts/                 # Python automation (uv)
└── hooks/                   # PowerShell hooks for context injection
```

## Architecture

This plugin follows **ADR-001: Shepherd is a Claude Code plugin that executes AI-SDLC methodology.**

- **AI-SDLC** = the methodology (phases, validation, templates)
- **Shepherd** = the execution engine (commands, hooks, profiles, scripts)
- The plugin references AI-SDLC patterns but adapts them for Claude Code's command/hook/agent system

## Contributing

1. Fork the repo
2. Create a feature branch: `feat/my-feature`
3. Follow the conventional commit format: `type: description`
4. Submit a PR with a clear description

## License

MIT
