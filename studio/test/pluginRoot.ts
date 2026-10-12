/** Locating the plugin the integration tests run against — and refusing to be quiet about it.
 *
 * Studio drives the Shepherd plugin's own scripts, so its most valuable tests need a
 * real plugin checkout with a real Python environment. When one cannot be located, those tests
 * skip. That is the right behaviour: somebody who has cloned Studio alone should still be able
 * to run its unit tests.
 *
 * What is NOT right is what used to happen next. A run where 31 of 33 window tests skipped
 * printed "2 passed" and exited 0, which is indistinguishable from a run that proved
 * everything. It caused a false report of what had been verified — the same failure this whole
 * product is built to prevent, sitting in its own test suite.
 *
 * So an unavailable plugin is now an ERROR by default, naming what was looked for and how to
 * point at the right place, and a person who genuinely wants the Studio-only tests says so out
 * loud with STUDIO_SKIP_PLUGIN_TESTS=1. Silence is no longer one of the options.
 *
 * WHERE IT LOOKS. Studio lives in `studio/` inside the plugin's own repository, so the plugin
 * is simply the directory this folder sits in. That one fact replaced an earlier search that
 * hunted for a sibling checkout and then scanned its git worktrees: when Studio ships inside
 * the repository, a worktree carries its own copy of this folder, so the parent directory is
 * already the right plugin for whichever branch the tests are running on. Nothing to search.
 *
 * What CAN still be missing is the Python environment under `scripts/.venv` — a fresh clone
 * has no such thing. That is the case these tests now fail loudly on, which is correct: the
 * environment is buildable, and a run that quietly proved nothing is worse than a red one.
 */

import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'

/** A file every usable plugin checkout has, and older ones do not — so a checkout on a branch
 * that predates Studio's needs is correctly treated as unusable rather than half-usable. */
const MARKER = join('scripts', 'document_shape_cli.py')

function venvPython(root: string): string {
  return process.platform === 'win32'
    ? join(root, 'scripts', '.venv', 'Scripts', 'python.exe')
    : join(root, 'scripts', '.venv', 'bin', 'python')
}

function isUsable(root: string): boolean {
  return existsSync(join(root, MARKER)) && existsSync(venvPython(root))
}

function candidates(testDir: string): string[] {
  const out: string[] = []
  // An explicit override still wins, which is what makes it possible to run this suite
  // against a different checkout than the one it happens to live in.
  if (process.env.SDLC_PLUGIN_ROOT) out.push(process.env.SDLC_PLUGIN_ROOT)

  // `studio/test` → `studio` → the plugin repository. Studio is a folder inside the plugin,
  // so its parent is the plugin, on whatever branch or worktree this copy belongs to.
  out.push(resolve(testDir, '..', '..'))
  return out
}

export interface PluginLocation {
  root: string | null
  scriptsDir: string
  python: string
  available: boolean
  searched: string[]
}

export function locatePlugin(testDir: string): PluginLocation {
  const searched = candidates(testDir)
  const root = searched.find(isUsable) ?? null
  return {
    root,
    scriptsDir: root ? join(root, 'scripts') : '',
    python: root ? venvPython(root) : '',
    available: root !== null,
    searched,
  }
}

/** Call once per integration test file, at module scope.
 *
 * Throws when no plugin can be located, unless the person has explicitly opted out. Throwing at
 * module scope fails the file loudly rather than letting it report success having run nothing.
 */
export function requirePlugin(testDir: string): PluginLocation {
  const found = locatePlugin(testDir)
  if (found.available) return found
  if (process.env.STUDIO_SKIP_PLUGIN_TESTS === '1') return found

  throw new Error(
    'No usable Shepherd plugin checkout was located, so the tests that prove Studio actually '
    + 'drives the plugin cannot run.\n\n'
    + `A usable checkout has both ${MARKER} and a Python environment under scripts/.venv.\n\n`
    + 'Looked in:\n'
    + found.searched.map((c) => `  - ${c}`).join('\n')
    + '\n\nPoint at one with SDLC_PLUGIN_ROOT=<path>, or run the Studio-only tests deliberately '
    + 'with STUDIO_SKIP_PLUGIN_TESTS=1. This used to skip quietly and report success, which is '
    + 'how a run that proved nothing came to look like a run that proved everything.',
  )
}
