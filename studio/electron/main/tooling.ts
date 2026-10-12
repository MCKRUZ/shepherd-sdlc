// Locates claude, uv, git, gh, az, and the Shepherd plugin's scripts/ directory on the
// local machine. Spec 0008's Decision List: "detect them, and if either is missing, say so
// with a link rather than installing anything" — auto-detect, VERIFY with a real invocation
// (never trust a found path without running it), and only ask the person to point at the
// right thing when detection or verification fails. Settings then remembers whatever the
// person confirmed, so this only runs again if that override stops working.

import { existsSync, readFileSync } from 'node:fs'
import { readdir } from 'node:fs/promises'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { AZ_ENV } from './az'
import { rawStdout, runCommand } from './commandRunner'
import { missingClaudeFlags } from '../../shared/claudeContract'
import { LEGACY_PLUGIN_IDS, PLUGIN_DISPLAY_NAME, PLUGIN_ID } from '../../shared/pluginId'
import type { ToolStatus, ToolingReport } from '../../shared/types'

export type { ToolStatus, ToolingReport }

// Every probe below goes through runCommand — the same console-logging choke point
// everything else in Studio uses — rather than calling execFile directly. It used to call
// execFile directly, which meant Studio's own startup tool-detection was invisible in the
// console log spec 0008 promises captures every command; caught in this spec's audit
// (2026-09-26). A 5s ceiling on every probe here (unlike ordinary git/gh calls, which have
// none) guards against a broken PATH entry hanging the app before a project is even open.
const PROBE_TIMEOUT_MS = 5000

/** az alone gets a longer ceiling: `az version` is a Python interpreter start plus the CLI's own
 * module load, measured at 3–8 s cold on a laptop (code-host-providers.md §7) — the 5 s probe
 * ceiling would report a working install as missing. Nothing else gets this allowance. */
export const AZ_PROBE_TIMEOUT_MS = 15_000

/** How to actually invoke a resolved binary — usually just the binary itself, but on
 * Windows a .cmd/.bat wrapper (common for the GitHub CLI, and some package-manager
 * installs of git) can't be launched directly by a shell-less spawn, so it's invoked
 * through cmd.exe /c instead. Both fields stay structured argv, never a shell string —
 * commandRunner.runCommand never uses shell:true, and this keeps it that way. */
export interface ResolvedBinary {
  command: string
  prefixArgs: string[]
}

interface ProbeOptions {
  /** The argv that prints a version — `--version` for everything but az. */
  versionArgs?: string[]
  timeoutMs?: number
  /** Merged onto process.env for the probe (az's two AZURE_* vars). */
  env?: Record<string, string>
}

/** The probe's EXACT output (rawStdout), because detectAz parses it as data; a version string
 * carries no credential, but the display copy is the wrong thing to read for anything parsed. */
async function verifyDirect(command: string, probe: Required<ProbeOptions>): Promise<string | null> {
  const entry = await runCommand(command, probe.versionArgs, process.cwd(), { timeoutMs: probe.timeoutMs, env: probe.env })
  return entry.ok ? rawStdout(entry) : null
}

/** Resolves the real, fully-qualified path of `command` via `where` (Windows) or `which`
 * (macOS/Linux) — both real executables, never a shell builtin, so this never needs
 * shell:true either. Returns null if the command isn't on PATH at all. */
async function resolveOnPath(command: string): Promise<string | null> {
  const finder = process.platform === 'win32' ? 'where' : 'which'
  const entry = await runCommand(finder, [command], process.cwd(), { timeoutMs: PROBE_TIMEOUT_MS })
  if (!entry.ok) return null
  const first = entry.stdout.trim().split('\n')[0]?.trim()
  return first || null
}

/** Verifies `command` by actually running it, trying a direct invocation first (the common
 * case — a real .exe/binary on PATH) and falling back to resolving its real path and, on
 * Windows, routing a .cmd/.bat wrapper through cmd.exe /c. Returns both the version string
 * and the ResolvedBinary later calls must use — a direct-exec success and a shimmed success
 * are invoked differently, and a caller needs to know which. */
async function verifyBinary(
  command: string,
  options: ProbeOptions = {},
): Promise<{ version: string; output: string; resolved: ResolvedBinary } | { error: string }> {
  const probe: Required<ProbeOptions> = {
    versionArgs: options.versionArgs ?? ['--version'], timeoutMs: options.timeoutMs ?? PROBE_TIMEOUT_MS, env: options.env ?? {},
  }
  const firstLine = (stdout: string) => stdout.trim().split('\n')[0]
  const direct = await verifyDirect(command, probe)
  if (direct !== null) {
    return { version: firstLine(direct), output: direct, resolved: { command, prefixArgs: [] } }
  }

  const resolvedPath = await resolveOnPath(command)
  if (resolvedPath === null) {
    return { error: `'${command}' was not found on PATH` }
  }

  const isWindowsScript = process.platform === 'win32' && /\.(cmd|bat)$/i.test(resolvedPath)
  const resolved: ResolvedBinary = isWindowsScript
    ? { command: 'cmd.exe', prefixArgs: ['/c', resolvedPath] }
    : { command: resolvedPath, prefixArgs: [] }

  const entry = await runCommand(
    resolved.command, [...resolved.prefixArgs, ...probe.versionArgs], process.cwd(), { timeoutMs: probe.timeoutMs, env: probe.env },
  )
  if (!entry.ok) {
    // Some tools print their real error to stdout, not stderr — fall back to it before
    // resorting to the bare exit code, which explains nothing about what actually went wrong.
    return { error: entry.stderr || entry.stdout || `exited with code ${entry.exitCode}` }
  }
  const output = rawStdout(entry)
  return { version: firstLine(output), output, resolved }
}

async function detect(overridePath: string | undefined, command: string): Promise<ToolStatus & { resolved?: ResolvedBinary }> {
  const result = await verifyBinary(overridePath ?? command)
  if ('error' in result) {
    return { found: false, error: result.error }
  }
  return { found: true, path: overridePath ?? command, version: result.version, resolved: result.resolved }
}

/** `claude --help`, read once per (binary, version): the probe costs a process start, and what
 * the CLI accepts cannot change until the binary does. Exported for tests only. */
export const helpProbeCache = new Map<string, string[]>()

async function probeClaudeFlags(command: string, version: string): Promise<string[]> {
  const key = `${command}@${version}`
  const cached = helpProbeCache.get(key)
  if (cached) return cached
  const entry = await runCommand(command, ['--help'], process.cwd(), { timeoutMs: PROBE_TIMEOUT_MS })
  // An unreadable help text reports every flag missing (shared/claudeContract.ts): "could not
  // read what the CLI accepts" must never be shown as "accepts everything".
  const missing = missingClaudeFlags(entry.ok ? rawStdout(entry) : '')
  helpProbeCache.set(key, missing)
  return missing
}

/** claude and uv are both just PATH lookups — verified by actually running them, never
 * trusted from `which`/`where` alone (a stale PATH entry can point at nothing executable).
 *
 * Claude additionally has its `--help` read for the flags Studio emits (studio-improvements
 * F1): a flag the installed CLI does not know fails every model call at once with
 * `unknown option`, and until this probe nothing looked before leaping. `missingFlags` is set
 * only when something is missing, so an absent key still reads "fine". */
export async function detectClaude(overridePath?: string): Promise<ToolStatus> {
  const { resolved: _resolved, ...status } = await detect(overridePath, 'claude')
  if (!status.found) return status
  const missing = await probeClaudeFlags(overridePath ?? 'claude', status.version ?? '')
  return missing.length > 0 ? { ...status, missingFlags: missing } : status
}

export async function detectUv(overridePath?: string): Promise<ToolStatus> {
  const { resolved: _resolved, ...status } = await detect(overridePath, 'uv')
  return status
}

/** git and gh additionally need the resolved invocation strategy (see ResolvedBinary) handed
 * to git.ts, since a Windows .cmd shim changes how every LATER call must be spawned too, not
 * just this detection probe. */
export async function detectGit(overridePath?: string): Promise<ToolStatus & { resolved?: ResolvedBinary }> {
  return detect(overridePath, 'git')
}

export async function detectGh(overridePath?: string): Promise<ToolStatus & { resolved?: ResolvedBinary }> {
  return detect(overridePath, 'gh')
}

/** Every az spawn in Studio carries these (az.ts has the why): no unprompted extension install,
 * no telemetry fork, warnings off stderr, JSON out. Appended here too because detection runs
 * BEFORE az.ts has been told how to invoke az, so it cannot go through runAz. */
const AZ_PROBE_FLAGS = ['-o', 'json', '--only-show-errors']

/** The Azure CLI, needed only when a project's repository is on Azure DevOps (code-host
 * providers, D4: never required to open a project). Verified by `az version -o json` — a real
 * invocation, with az's own longer ceiling — then the azure-devops extension is looked up
 * LOCALLY (`az extension show`, no network). `extension` is tri-state on purpose: false only
 * when az itself said the extension is absent; null when the probe could not run at all. */
export async function detectAz(overridePath?: string): Promise<ToolStatus & { resolved?: ResolvedBinary }> {
  const env = { ...AZ_ENV }
  const result = await verifyBinary(overridePath ?? 'az', { versionArgs: ['version', ...AZ_PROBE_FLAGS], timeoutMs: AZ_PROBE_TIMEOUT_MS, env })
  if ('error' in result) {
    return { found: false, error: result.error, extension: null }
  }
  // `az version -o json` prints `{"azure-cli": "2.x.y", ...}`; the first line of that is `{`.
  let version = result.version
  try {
    const parsed = JSON.parse(result.output) as { 'azure-cli'?: unknown }
    if (typeof parsed['azure-cli'] === 'string') version = parsed['azure-cli']
  } catch { /* an older az printing plain text keeps its first line */ }

  const ext = await runCommand(
    result.resolved.command, [...result.resolved.prefixArgs, 'extension', 'show', '--name', 'azure-devops', ...AZ_PROBE_FLAGS],
    process.cwd(), { timeoutMs: AZ_PROBE_TIMEOUT_MS, env },
  )
  // A non-zero exit is az saying "no such extension"; a null exit code is the probe itself
  // failing (timeout, spawn error) — not knowing must not read as "missing".
  const extension = ext.ok ? true : ext.exitCode === null ? null : false
  return { found: true, path: overridePath ?? 'az', version, extension, resolved: result.resolved }
}

/** A directory name that looks like a semver version — used to pick the newest installed
 * plugin version when more than one is present. */
function compareVersions(a: string, b: string): number {
  const pa = a.split('.').map((n) => parseInt(n, 10) || 0)
  const pb = b.split('.').map((n) => parseInt(n, 10) || 0)
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const diff = (pa[i] ?? 0) - (pb[i] ?? 0)
    if (diff !== 0) return diff
  }
  return 0
}

/** The file that marks a usable plugin `scripts/` directory. `capabilities.py` rather than
 * `generate_status.py` (the old marker): the capabilities list is what lets this Studio tell an
 * older plugin from a current one, so a directory without it is an older plugin by definition. */
export const PLUGIN_MARKER = 'capabilities.py'

/** The directory names the cache scan looks under, in preference order: the current id, then
 * every id the same plugin was installed under before 2.0. */
const PLUGIN_IDS: readonly string[] = [PLUGIN_ID, ...LEGACY_PLUGIN_IDS]

/** The version `.claude-plugin/plugin.json` beside a `scripts/` directory declares, when
 * readable — so Settings can say WHICH plugin is driving this session, not only where it is. */
function readPluginVersion(scriptsDir: string): string | undefined {
  try {
    const manifest = JSON.parse(readFileSync(join(scriptsDir, '..', '.claude-plugin', 'plugin.json'), 'utf-8'))
    return typeof manifest.version === 'string' ? manifest.version : undefined
  } catch {
    return undefined
  }
}

function foundPlugin(path: string, source: NonNullable<ToolStatus['source']>): ToolStatus {
  const pluginVersion = readPluginVersion(path)
  return pluginVersion ? { found: true, path, source, pluginVersion } : { found: true, path, source }
}

/** The plugin checkout Studio ships inside, when it is one: `studio/` sits in the plugin's own
 * repository, so `<APP_ROOT>/../scripts` is that plugin's scripts directory. Null when there is
 * no such directory (a packaged build, or a Studio copied elsewhere) or it lacks the marker. */
export function siblingPluginScripts(appRoot: string | undefined = process.env.APP_ROOT): string | null {
  if (!appRoot) return null
  const scripts = join(appRoot, '..', 'scripts')
  return existsSync(join(scripts, PLUGIN_MARKER)) ? scripts : null
}

/** Which plugin drives this session, in this order (studio-improvements F2):
 *
 *   1. a path the person set in Settings — they said so, and it is checked, not trusted;
 *   2. the checkout Studio ships in (`siblingPluginScripts`) — the README's promise that "the
 *      plugin Studio drives is always the one beside it", which used to be false: the cache
 *      scan below ran first and picked an older marketplace copy over the checkout;
 *   3. the newest marketplace-cached version under ~/.claude/plugins/cache/<namespace>/
 *      <plugin id>/<version>/ (verified against a real local install) that carries the
 *      marker — `shepherd` first, then the pre-2.0 ids (LEGACY_PLUGIN_IDS):
 *      a packaged 2.x Studio beside a not-yet-reinstalled plugin still finds it, and a
 *      cached copy under the current id always wins over one under the old, whatever
 *      their versions.
 *
 * Every result says which of the three it was (`source`) and the version it declares. */
export async function detectPluginScripts(
  overridePath?: string,
  appRoot: string | undefined = process.env.APP_ROOT,
): Promise<ToolStatus> {
  if (overridePath) {
    return existsSync(join(overridePath, PLUGIN_MARKER))
      ? foundPlugin(overridePath, 'override')
      : {
          found: false,
          error: `${PLUGIN_MARKER} not found under ${overridePath} — Shepherd needs the scripts/ folder of a current ${PLUGIN_DISPLAY_NAME} plugin`,
        }
  }

  const sibling = siblingPluginScripts(appRoot)
  if (sibling) return foundPlugin(sibling, 'sibling')

  const cacheDir = join(homedir(), '.claude', 'plugins', 'cache')
  if (!existsSync(cacheDir)) {
    return { found: false, error: `Plugin cache directory not found: ${cacheDir}` }
  }

  // `rank` is the id's position in PLUGIN_IDS — 0 for the current id — so the sort below can
  // prefer it before it ever compares versions.
  const candidates: { dir: string; rank: number }[] = []
  try {
    const namespaces = await readdir(cacheDir, { withFileTypes: true })
    for (const ns of namespaces) {
      if (!ns.isDirectory()) continue
      for (let rank = 0; rank < PLUGIN_IDS.length; rank++) {
        const pluginDir = join(cacheDir, ns.name, PLUGIN_IDS[rank])
        if (!existsSync(pluginDir)) continue
        const versions = await readdir(pluginDir, { withFileTypes: true })
        for (const v of versions) {
          if (v.isDirectory()) candidates.push({ dir: join(pluginDir, v.name), rank })
        }
      }
    }
  } catch (err) {
    return { found: false, error: err instanceof Error ? err.message : String(err) }
  }

  const withScripts = candidates
    .map(({ dir, rank }) => ({ dir, rank, scripts: join(dir, 'scripts') }))
    .filter(({ scripts }) => existsSync(join(scripts, PLUGIN_MARKER)))

  if (withScripts.length === 0) {
    return {
      found: false,
      error: `no ${PLUGIN_DISPLAY_NAME} plugin with ${PLUGIN_MARKER} under ~/.claude/plugins/cache — install or update the plugin, or point Shepherd at a checkout's scripts/ folder`,
    }
  }

  withScripts.sort((a, b) => a.rank - b.rank || compareVersions(b.dir.split(/[\\/]/).pop()!, a.dir.split(/[\\/]/).pop()!))
  return foundPlugin(withScripts[0].scripts, 'cache')
}

export interface DetectAllToolingResult extends ToolingReport {
  /** Only set when found — the resolved invocation strategy git.ts needs to actually run
   * git/gh commands, not just detect them. */
  gitResolved?: ResolvedBinary
  ghResolved?: ResolvedBinary
  azResolved?: ResolvedBinary
}

/** Everything at once. Which of these BLOCK opening a project is not decided here: claude, uv,
 * pluginScripts and git do; gh and az never do (ToolingReport's comment) — the renderer applies
 * that rule, and the main process only reports what it found. */
export async function detectAllTooling(overrides: {
  claudePath?: string
  uvPath?: string
  pluginScriptsPath?: string
  gitPath?: string
  ghPath?: string
  azPath?: string
}): Promise<DetectAllToolingResult> {
  const [claude, uv, pluginScripts, gitDetect, ghDetect, azDetect] = await Promise.all([
    detectClaude(overrides.claudePath),
    detectUv(overrides.uvPath),
    detectPluginScripts(overrides.pluginScriptsPath),
    detectGit(overrides.gitPath),
    detectGh(overrides.ghPath),
    detectAz(overrides.azPath),
  ])
  const { resolved: gitResolved, ...git } = gitDetect
  const { resolved: ghResolved, ...gh } = ghDetect
  const { resolved: azResolved, ...az } = azDetect
  return { claude, uv, pluginScripts, git, gh, az, gitResolved, ghResolved, azResolved }
}
