// Everything Studio does to a project goes through the plugin's own scripts, run through
// runCommand() — this file never re-derives phase order, gate logic, or setup steps
// itself. If something Studio needs isn't exposed by a script yet, that's a plugin change,
// not something to approximate here (spec 0008's own harness_context).

import { existsSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { rawStdout, runCommand, type ConsoleEntry } from './commandRunner'
import { PLUGIN_DISPLAY_NAME } from '../../shared/pluginId'
import type { OpenProjectResult, PreviewSetupResult, ProjectStatus, RunSetupResult, SetupPlan } from '../../shared/types'

export type { OpenProjectResult, ProjectStatus, SetupPlan }

function scriptPath(pluginScriptsDir: string, name: string): string {
  return join(pluginScriptsDir, name)
}

function venvPythonPath(pluginScriptsDir: string): string {
  return process.platform === 'win32'
    ? join(pluginScriptsDir, '.venv', 'Scripts', 'python.exe')
    : join(pluginScriptsDir, '.venv', 'bin', 'python')
}

/** argparse's own failure shape: a "usage:" line, then "<script>.py: error: ...". Reached in
 * practice when the installed plugin is older (or newer) than what Studio was built against —
 * a real project on this very machine hit this calling generate_status.py --json against a
 * plugin version that predates the flag. Detected once, here, rather than guessed at
 * differently by the ten-odd call sites that each build their own error text from
 * entry.stderr — a stale plugin is the single most likely explanation for THIS shape of
 * failure specifically, and a raw argparse dump is not something a person should have to
 * decode themselves to learn that. */
const ARGPARSE_MISMATCH = /^usage:[\s\S]*?error: (unrecognized arguments|the following arguments are required|invalid choice)/m

export function explainIfVersionMismatch(entry: ConsoleEntry, scriptName: string): ConsoleEntry {
  if (entry.ok || !ARGPARSE_MISMATCH.test(entry.stderr)) return entry
  return {
    ...entry,
    stderr: `The installed ${PLUGIN_DISPLAY_NAME} plugin doesn't match what Shepherd expects — `
      + `${scriptName} rejected an option Shepherd needs. This project's plugin may be older or `
      + `newer than the one Shepherd was built against. Point Shepherd at a different plugin `
      + `checkout in Settings, or update the installed plugin, then try again.\n\n`
      + `What the script actually said:\n${entry.stderr}`,
  }
}

/** Runs a plugin script inside the PLUGIN's own scripts directory (its dependencies live
 * there, via scripts/pyproject.toml) — not the project directory.
 *
 * When the plugin's venv already exists (the normal case — Claude Code itself has almost
 * certainly already run a plugin script via `uv run` at least once, which builds it),
 * this invokes that venv's own python directly: no `uv` sync-check, no network dependency
 * for what should be an instant, routine call. Verified live: even `uv run --no-sync`
 * resolved the WRONG interpreter in one tested environment — going straight at the venv's
 * python is the only invocation proven reliable throughout this project's own build
 * (see this repo's own session history). Only on true first-use, with no venv built yet,
 * does this fall back to `uv run`, which builds one — a real one-time network cost, not
 * a routine one. */
export async function runPluginScript(
  pluginScriptsDir: string,
  scriptName: string,
  args: string[],
  /** Written to the script's standard input. This is how a CREDENTIAL reaches a script: an
   * argument is visible to anything that can list processes, and the console log records the
   * arguments of every command Studio runs. Standard input is recorded nowhere. */
  input?: string,
): Promise<ConsoleEntry> {
  const venvPython = venvPythonPath(pluginScriptsDir)
  const script = scriptPath(pluginScriptsDir, scriptName)
  const opts = input === undefined ? undefined : { input }
  const entry = existsSync(venvPython)
    ? await runCommand(venvPython, [script, ...args], pluginScriptsDir, opts)
    : await runCommand('uv', ['run', '--project', pluginScriptsDir, script, ...args], pluginScriptsDir, opts)
  return explainIfVersionMismatch(entry, scriptName)
}

export function hasSdlcProject(projectPath: string): boolean {
  return existsSync(join(projectPath, '.sdlc', 'state.yaml'))
}

export async function openProject(pluginScriptsDir: string, projectPath: string): Promise<OpenProjectResult> {
  if (!hasSdlcProject(projectPath)) {
    return { hasProject: false }
  }
  const statePath = join(projectPath, '.sdlc', 'state.yaml')
  const entry = await runPluginScript(pluginScriptsDir, 'generate_status.py', ['--state', statePath, '--json'])
  if (!entry.ok) {
    return { hasProject: true, entry, error: entry.stderr || 'generate_status.py failed' }
  }
  try {
    return { hasProject: true, status: JSON.parse(rawStdout(entry)), entry }
  } catch {
    return { hasProject: true, entry, error: 'generate_status.py returned unparseable JSON' }
  }
}

export function listAvailableProfiles(pluginScriptsDir: string): string[] {
  const pluginRoot = join(pluginScriptsDir, '..')
  const profilesDir = join(pluginRoot, 'profiles')
  if (!existsSync(profilesDir)) return []
  return readdirSync(profilesDir, { withFileTypes: true })
    .filter((e) => e.isDirectory() && existsSync(join(profilesDir, e.name, 'profile.yaml')))
    .map((e) => e.name)
    .sort()
}

function profilePath(pluginScriptsDir: string, profileId: string): string {
  return join(pluginScriptsDir, '..', 'profiles', profileId, 'profile.yaml')
}

export async function previewSetup(
  pluginScriptsDir: string,
  projectPath: string,
  profileId: string,
): Promise<PreviewSetupResult> {
  const entry = await runPluginScript(pluginScriptsDir, 'init_project.py', [
    '--profile', profilePath(pluginScriptsDir, profileId),
    '--target', projectPath,
    '--dry-run', '--json',
  ])
  if (!entry.ok) return { entry, error: entry.stderr || 'init_project.py --dry-run failed' }
  try {
    return { plan: JSON.parse(rawStdout(entry)), entry }
  } catch {
    return { entry, error: 'init_project.py --dry-run returned unparseable JSON' }
  }
}

export async function runSetup(
  pluginScriptsDir: string,
  projectPath: string,
  profileId: string,
): Promise<RunSetupResult> {
  const entry = await runPluginScript(pluginScriptsDir, 'init_project.py', [
    '--profile', profilePath(pluginScriptsDir, profileId),
    '--target', projectPath,
  ])
  return { ok: entry.ok, entry }
}
