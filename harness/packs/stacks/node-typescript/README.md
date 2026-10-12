# Node / TypeScript stack pack

Realizes the core kit's stack-shaped blanks so a Node + TypeScript repo installs ready-to-adapt
instead of full of `{{TOKENS}}`. Pair it with a CI/CD pack (`packs/cicd/github` or
`packs/cicd/azure-devops`) — this pack supplies the *commands*; the CI/CD pack supplies the
*pipeline* that runs them.

Selected by a profile declaring `stack.backend.language: typescript` (e.g.
`shepherd/profiles/starter`).

## What it fills

| Core blank | This pack supplies |
|---|---|
| `CLAUDE.md` → `## Stack standards — {{STACK}} profile` | `claude/stack-standards.md` (lean; `@import`s the two rules below) |
| `CLAUDE.md` → `@./.claude/rules/project-structure.md` | `rules/project-structure.md` |
| `CLAUDE.md` → `@./.claude/rules/testing.md` | `rules/testing.md` |
| the generic `api-pattern` skill | `skills/api-pattern-node` (layering / boundary validation / `Result<T, E>`) |
| `ci.yml` → `<<CI_RESTORE_CMD>> <<CI_BUILD_CMD>> <<CI_TEST_CMD>>` etc. | `ci-profile.yaml` (consumed by the CI/CD pack) |
| `settings.json` → node tooling perms | `settings.fragment.json` (merged) |

It contributes **no** `mcp.fragment.json`: no MCP server is Node-specific, and the core's `.mcp.json`
already carries context7 for library lookups.

## Where each file lands in the repo

```
claude/stack-standards.md      → replaces the {{STACK}} section of CLAUDE.md
rules/project-structure.md     → .claude/rules/project-structure.md   (@imported)
rules/testing.md               → .claude/rules/testing.md             (@imported)
skills/api-pattern-node/       → .claude/skills/api-pattern-node/
settings.fragment.json         → merged into .claude/settings.json
ci-profile.yaml                → consumed by the CI/CD pack (not copied as-is)
```

## What it composes with

`toolchain.id: node` is mapped by **both** CI/CD packs (`github` → `actions/setup-node@v7` /
`node-version`; `azure-devops` → `UseNode@1` / `version`), so this pack runs on either platform
unchanged. Both packs list `node-typescript` in their `requires_stack_pack`.

## The repo's side of the contract

Unlike the .NET pack, this one carries **no `{{SOLUTION_OR_PROJECT}}`-style token** — `npm ci` and
`tsc --project tsconfig.json` both find their inputs by convention from the repo root, so there is
nothing repo-specific to fill. What the repo must supply instead is **devDependencies**: `typescript`,
`vitest`, `@vitest/coverage-v8`, and `eslint`. `npx` resolves each from the repo's own
`node_modules` (installed by `npm ci`) — it is not an arbitrary registry fetch. A repo missing one of
these fails at that command, loudly.

The `{{LIST_NON_OBVIOUS_BEHAVIORS}}` gotchas line in `stack-standards.md` is genuinely per-repo and
is filled during Phase 3 repo adaptation, not by the pack.

## Adapting it

- **Bundler instead of `tsc`?** A repo building with tsup/esbuild/swc swaps `commands.build` for its
  own single-line invocation. Keep `session_health.command` as a `--noEmit` type-check regardless —
  a health check answers "does this still type-check?" and must not write build output.
- **Coverage filename:** `commands.test` renames vitest's cobertura report to
  `coverage/coverage.cobertura.xml`. That name is not cosmetic — it is what both CI/CD packs' coverage-floor
  step globs for. If you change `commands.test`, keep the rename.
- **The floor lives in one place** (`coverage.floor_percent`). Don't also pass
  `--coverage.thresholds.lines` in `commands.test`; that would hard-code a second number with nothing
  keeping the two in sync. Wire the threshold into the repo's local `npm test` script instead.

## Provenance

**Authored 2026-07-16 against the `starter` profile — not harvested from a live repo.** There is no
`HARVEST.md` here because there is no harvest lineage to claim: the .NET pack's commands came out of a
realized .NET pipeline, these were written against upstream documentation and the seam's existing
contract. Verified as of that date against:

- **nodejs/Release** (`README.md` release schedule) — 24.x "Krypton" is **Active LTS** (2025-10-28 →
  maintenance 2026-10-20); 22.x is already Maintenance LTS and 26.x is Current. Hence `24.x`.
  Revisit when 26.x enters Active LTS on 2026-10-28.
- **Vitest coverage config reference** (`vitest.dev/config/coverage`) — `coverage.reportsDirectory`
  (default `./coverage`), `coverage.reporter` (CLI form `--coverage.reporter=<name>`, repeated for
  arrays), and the documented requirement to pass `--coverage.enabled` when using dot-notation
  coverage flags rather than a bare `--coverage`. Per-reporter options (the `['cobertura', { file }]`
  tuple) are **config-file only** — not expressible on the CLI, which is why the rename exists.
- **istanbul-reports** (`lib/cobertura/index.js`) — the cobertura reporter's filename default is
  `opts.file || 'cobertura-coverage.xml'`, which is what makes the rename necessary against the
  gate's `coverage.cobertura.xml` glob.
- **Claude Code permissions reference** — rules evaluate deny → ask → allow, and specificity does not
  reorder them; this is why `settings.fragment.json` ships no blanket `Bash(npx:*)` ask rule.

**Not yet exercised on a real Node repo.** The commands are documented-correct and the coverage path
is matched against the gate's glob by inspection, but no pipeline has run them end to end. First use
on a live repo should confirm the cobertura rename and the `tsc` build step against that repo's real
layout.
