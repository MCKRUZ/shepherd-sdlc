// Which code host a project is on, and the provider that talks to it (code-host providers,
// Wave 6-A). One decision per project, the same precedence as scripts/code_host.py — env →
// .sdlc/code-host.yaml → origin remote → harness-manifest tie-breaker → none — so Studio and the
// plugin scripts it runs never disagree about which CLI a repository needs.
//
// D4: neither gh nor az blocks opening a project. What a missing CLI costs is reported per
// feature (shared/codeHostModel.ts hostFeatureReason) from the `cli` block returned here, and
// it is reported honestly: `found` is a fact from tooling detection, `extension` is null until
// probed, `signedIn` is 'unknown' until a probe actually ran. A NullHost stands in when the CLI
// cannot be spawned at all, so a feature fails fast with the §7.1 wording instead of an ENOENT.

import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  CODE_HOST_ENV, CODE_HOST_FILE, LEGACY_CODE_HOST_ENV, cliFor, detectHostFromInputs, parseCodeHostYaml, WORDING,
  type CliName, type CliStatus, type Detection,
} from '../../shared/codeHostModel'
import { azJson as defaultAzJson, AzError } from './az'
import { CodeHostUnavailable, type CodeHost, type CreatePullRequestResult, type Identity, type Memo, type PrListEntry, type RepoView } from './codeHostTypes'
import { hasOriginRemote, runGh as defaultRunGh, runGit as defaultRunGit } from './git'
import { AzureDevOpsHost } from './hosts/azureDevOpsHost'
import { GitHubHost, type GitHubHostDeps } from './hosts/githubHost'

export * from './codeHostTypes'

/** The poll interval: whoAmI / repoView / the extension probe are re-read once per tick. */
export const CODE_HOST_TTL_MS = 120_000

/** Every method rejects with the same CodeHostUnavailable — the reason is fixed when the host is. */
export class NullHost implements CodeHost {
  readonly kind = 'none' as const
  constructor(public readonly reason: string, readonly cli: CliName = 'gh', readonly state: CodeHostUnavailable['state'] = 'no_host') {}
  private refuse<T>(): Promise<T> { return Promise.reject(new CodeHostUnavailable(this.reason, this.state)) }
  whoAmI(): Promise<Identity> { return this.refuse() }
  repoView(): Promise<RepoView> { return this.refuse() }
  isBranchProtected(): Promise<boolean | null> { return this.refuse() }
  createPullRequest(): Promise<CreatePullRequestResult> { return this.refuse() }
  listOpenPullRequests(): Promise<PrListEntry[]> { return this.refuse() }
  mergePullRequest(): Promise<string> { return this.refuse() }
}

// ── per-project memo ───────────────────────────────────────────────────────────────────────

const memos = new Map<string, Map<string, { expires: number; value: Promise<unknown> }>>()

export function memoFor(projectPath: string, now: () => number = Date.now): Memo {
  return <T>(key: string, fn: () => Promise<T>): Promise<T> => {
    let table = memos.get(projectPath)
    if (!table) memos.set(projectPath, (table = new Map()))
    const hit = table.get(key)
    if (hit && hit.expires > now()) return hit.value as Promise<T>
    const value = fn()
    table.set(key, { expires: now() + CODE_HOST_TTL_MS, value })
    // A rejection is not kept: the next call probes again, so one transient failure cannot
    // pin "unavailable" for a whole poll interval.
    value.catch(() => { if (table.get(key)?.value === value) table.delete(key) })
    return value
  }
}

/** Forget what was probed — after `az login`, a tool-path override, or when a project closes. */
export function invalidateCodeHost(projectPath?: string): void {
  if (projectPath === undefined) memos.clear()
  else memos.delete(projectPath)
}

// ── resolution ─────────────────────────────────────────────────────────────────────────────

export interface ResolveCodeHostDeps extends GitHubHostDeps {
  runGit?: (args: string[], cwd: string) => Promise<string>
  azJson?: <T>(args: string[], cwd: string) => Promise<T>
  env?: Record<string, string | undefined>
  readFile?: (path: string) => string | null
  /** From tooling detection (index.ts). When a CLI is absent here it is probed with `--version`. */
  found?: Partial<Record<CliName, boolean>>
  /** Default true: run the extension check and whoAmI so `cli` says what it knows. */
  probe?: boolean
  now?: () => number
}

export interface ResolvedCodeHost extends Detection {
  cli: CliStatus
  provider: CodeHost
}

function readLocal(path: string): string | null {
  try { return existsSync(path) ? readFileSync(path, 'utf-8') : null } catch { return null }
}

function manifestPacks(text: string | null): string[] | null {
  if (text === null) return null
  try {
    const packs = (JSON.parse(text) as { packs?: unknown }).packs
    return Array.isArray(packs) ? packs.filter((p): p is string => typeof p === 'string') : []
  } catch { return null }
}

export async function resolveCodeHost(projectPath: string, deps: ResolveCodeHostDeps = {}): Promise<ResolvedCodeHost> {
  const runGit = deps.runGit ?? defaultRunGit
  const azJson = deps.azJson ?? defaultAzJson
  const env = deps.env ?? process.env
  const readFile = deps.readFile ?? readLocal
  const memo = deps.memo ?? memoFor(projectPath, deps.now)

  // No remote is a state, not a failure: ask `git remote` (which succeeds when empty) before reading an
  // address that cannot exist, so a new project does not log a failed command on every screen. A caller
  // that injects its own `runGit` (the unit tests) keeps exactly the call it always made.
  const noRemote = !deps.runGit && !(await hasOriginRemote(projectPath))
  const remoteUrl = noRemote ? null : await runGit(['remote', 'get-url', 'origin'], projectPath).then((s) => s.trim() || null, () => null)
  const fileText = readFile(join(projectPath, CODE_HOST_FILE))
  const file = fileText === null ? { settings: null, error: null } : parseCodeHostYaml(fileText)
  const detection = detectHostFromInputs({
    flagOrEnv: env[CODE_HOST_ENV] ?? null, legacyEnv: env[LEGACY_CODE_HOST_ENV] ?? null,
    fileHost: file.settings, fileError: file.error, remoteUrl,
    manifestPacks: manifestPacks(readFile(join(projectPath, '.claude', 'harness-manifest.json'))),
  })

  const cliName = cliFor(detection.host)
  const cli: CliStatus = { name: cliName, found: false, extension: null, signedIn: 'unknown' }
  const hostDeps = { runGh: deps.runGh, ghJson: deps.ghJson, azJson, memo, env }
  cli.found = deps.found?.[cliName] ?? await memo(`found:${cliName}`, async () => {
    if (cliName === 'az') return azJson(['version'], projectPath).then(() => true, () => false)
    return (deps.runGh ?? defaultRunGh)(['--version'], projectPath).then(() => true, () => false)
  })

  const missing = detection.host === 'azure-devops' ? WORDING.azMissing : detection.host === 'github' ? WORDING.ghMissing : WORDING.hostNone
  if (!cli.found) {
    return { ...detection, cli: { ...cli, reason: missing }, provider: new NullHost(missing, cliName, 'not_installed') }
  }
  if (detection.host === 'none') cli.reason = WORDING.hostNone // features off; gh is still tried, as before

  let provider: CodeHost
  if (detection.host === 'azure-devops') {
    if (!detection.remote) {
      const reason = `${detection.detail}; ${CODE_HOST_FILE} must name organization, project and repository when origin cannot be parsed`
      return { ...detection, cli: { ...cli, reason }, provider: new NullHost(reason, 'az', 'no_host') }
    }
    if (deps.probe !== false) {
      cli.extension = await memo('extension', () => azJson(['extension', 'show', '--name', 'azure-devops'], projectPath).then(() => true, (err: unknown) => {
        if (err instanceof AzError && err.failure === 'exit') return false
        throw err
      })).catch(() => null)
      if (cli.extension === false) {
        return { ...detection, cli: { ...cli, reason: WORDING.azExtensionMissing }, provider: new NullHost(WORDING.azExtensionMissing, 'az', 'extension_missing') }
      }
    }
    provider = new AzureDevOpsHost(projectPath, detection.remote, hostDeps)
  } else {
    provider = new GitHubHost(projectPath, hostDeps)
  }

  if (deps.probe !== false) {
    try {
      await provider.whoAmI()
      cli.signedIn = 'yes'
    } catch (err) {
      if (err instanceof CodeHostUnavailable && (err.state === 'signed_out' || err.state === 'pat_only')) {
        cli.signedIn = 'no'
        cli.reason = err.reason
      } else if (cliName === 'gh' && /gh auth login|HTTP 401|authentication/i.test(err instanceof Error ? err.message : '')) {
        cli.signedIn = 'no'
        cli.reason = WORDING.ghSignedOut
      } else {
        // The probe itself failed (network, a timeout): not knowing is not "no".
        cli.signedIn = 'unknown'
        cli.reason = cli.reason ?? (err instanceof Error ? err.message : String(err))
      }
    }
  }
  return { ...detection, cli, provider }
}
