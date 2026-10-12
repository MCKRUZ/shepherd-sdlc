# Provenance — .NET stack pack

Honest record of where each piece came from, per the baseline diff decision: harvest the proven
.NET pipeline content from `microsoft-agentic-harness`, leave its drift.

## Harvested from `microsoft-agentic-harness` (the realized pipeline)

- **`ci-profile.yaml` commands** — lifted from that repo's realized `.github/workflows/ci.yml`:
  `dotnet restore/build/test` with `--no-restore` / `--no-build` / `--configuration Release`,
  `--collect:"XPlat Code Coverage" --results-directory coverage`, on `setup-dotnet@v5` / `10.x`.
  These are real, working commands, not the core kit's `<<PLACEHOLDER>>` templates.
- **The eval-gate convention** — `--filter "Category=OwaspAgentic"` as a second hard gate for
  agentic behavior (that repo's "OWASP Agentic Top-10 Gate"). Carried as `eval_gate` (disabled by
  default; a repo enables it when it ships agent behavior that must not regress).

## Authored fresh (from the delivery standard's own conventions)

The rules, skill, and CLAUDE stack block are **not** copied from that repo — they crystallize the
standard's documented .NET conventions (immutability, `Result<T>` with `Success/Fail/
ValidationFailure`, FluentValidation auto-discovered via the MediatR `ValidationBehavior`, keyed DI,
`IOptionsMonitor<T>`, `WebApplicationFactory` + in-memory DB, `MethodName_Scenario_ExpectedResult`,
80% floor). These are authored so the pack states the standard, not one repo's take on it.

## Deliberately left behind (the drift the baseline diff flagged)

- **GitNexus skills + hook wiring** — that repo's `.claude/skills/gitnexus/*` and its `PreToolUse`
  GitNexus hooks are a repo-specific code-intelligence integration, not general craft. Not harvested.
- **The Postgres `services:` block + `Dashboards/init-db` schema step** — repo-specific to that
  codebase's observability tests. The CI/CD pack keeps this as an optional, DELETE-if-unused block
  (as the core `ci.yml` already does), not a .NET default.
- **Renamed gates/rails** — `stop-build-gate`, `correctness-review`, `security-review` and the
  flattened `.github/*-rubric.md` layout are that repo's older-fork drift. The pack tracks the
  current kit's names (`stop-gate`, `correctness`, `security`, `profile/rubrics/`), not the fork's.

## Built since (this pack is now installable)

- **CI/CD packs** — DONE. `packs/cicd/github` (adapts the core `workflows/` to consume
  `ci-profile.yaml`) and `packs/cicd/azure-devops` (net-new). This stack pack declares commands;
  those realize them via the `«stack pack: ci-profile.*»` seam markers.
- **Profile-aware install** — DONE. `install_harness.py --profile <profile.yaml>` composes core +
  the stack pack (`stack.backend.language`) + the CI/CD pack (`stack.ci_cd.platform`): overlay maps
  from each `pack.yaml`, a deep JSON merge for `settings.fragment.json`, and a CLAUDE.md
  stack-section splice. The two axes degrade independently (a stack/platform with no pack installs
  neutral core + a WARNING; setup never fails for a missing pack). `/sprd-setup` passes the profile.

## Still to build

- **Consolidation** — the core `kit/workflows/*` originals are now shadowed by the CI/CD pack
  overlay; removing them (and repointing `kit/README.md` + `PLUGIN-SYNC.md`) is a later cleanup.
- **Value binding** — the profile drives which packs compose, not repo-specific values yet. Tokens
  like `<<COVERAGE_THRESHOLD>>` are authored as runnable reference literals annotated by a token in
  a comment; wiring `quality.coverage_minimum` through would need the packs re-authored with
  value-position tokens + a fill pass — a deliberate future increment, not a bolt-on.
- **Version scheme** — `pack.yaml version` is `0.1.0`; the kit has no version-stamp mechanism yet
  (the drift-detector work), so `kit_min_version` is intentionally omitted until that exists.
