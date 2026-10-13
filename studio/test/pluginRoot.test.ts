/** Locating the plugin, and refusing to be quiet about not finding it.
 *
 * This exists because of a real, embarrassing failure in this repository's own verification: a
 * window-test run where 31 of 33 tests skipped printed "2 passed" and exited 0. That is
 * indistinguishable from a run that proved everything, and it produced a false report of what
 * had been verified — the exact failure mode the whole product is built to prevent, sitting
 * inside its own test suite.
 *
 * So the property under test is not "can it find a plugin". It is "can a run that proved
 * nothing ever look like a run that proved something".
 */

import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { locatePlugin, requirePlugin } from './pluginRoot'

const created: string[] = []

function tempDir(prefix: string): string {
  const d = mkdtempSync(join(tmpdir(), prefix))
  created.push(d)
  return d
}

/** A checkout that looks real enough to be chosen: the marker script and a Python executable
 * where the environment would put one. */
function fakePluginCheckout(at: string): string {
  mkdirSync(join(at, 'scripts'), { recursive: true })
  writeFileSync(join(at, 'scripts', 'document_shape_cli.py'), '# marker\n')
  const venvBin = process.platform === 'win32'
    ? join(at, 'scripts', '.venv', 'Scripts')
    : join(at, 'scripts', '.venv', 'bin')
  mkdirSync(venvBin, { recursive: true })
  writeFileSync(join(venvBin, process.platform === 'win32' ? 'python.exe' : 'python'), '')
  return at
}

/** A `test/` directory whose parent repository is not a usable plugin, so nothing is found by
 * accident. Mirrors the real `<plugin>/studio/test` shape, two levels below the candidate. */
function isolatedTestDir(): string {
  const d = tempDir('plugin-root-')
  const testDir = join(d, 'studio', 'test')
  mkdirSync(testDir, { recursive: true })
  return testDir
}

afterEach(() => {
  delete process.env.SDLC_PLUGIN_ROOT
  delete process.env.STUDIO_SKIP_PLUGIN_TESTS
  while (created.length) rmSync(created.pop()!, { recursive: true, force: true })
})

describe('a run that proved nothing cannot look like a run that proved something', () => {
  it('THROWS when no plugin can be located, rather than skipping quietly', () => {
    expect(() => requirePlugin(isolatedTestDir())).toThrow(/No usable Shepherd plugin checkout/)
  })

  it('names every place it looked, so the answer is actionable', () => {
    // A failure a person cannot act on is a wall. This one has to say where to point it.
    let message = ''
    try {
      requirePlugin(isolatedTestDir())
    } catch (e) {
      message = (e as Error).message
    }
    expect(message).toMatch(/Looked in:/)
    expect(message).toMatch(/SDLC_PLUGIN_ROOT/)
    expect(message).toMatch(/STUDIO_SKIP_PLUGIN_TESTS=1/)
  })

  it('stays quiet only when somebody says so out loud', () => {
    process.env.STUDIO_SKIP_PLUGIN_TESTS = '1'
    const found = requirePlugin(isolatedTestDir())
    expect(found.available).toBe(false)
  })
})

describe('what counts as a usable checkout', () => {
  it('a checkout with the scripts but no Python environment is not usable', () => {
    // The state the main checkout is actually in when it sits on an older branch: the folder
    // exists, so a naive check says yes, and then every test fails for an unrelated reason.
    const testDir = isolatedTestDir()
    const plugin = tempDir('plugin-nopython-')
    mkdirSync(join(plugin, 'scripts'), { recursive: true })
    writeFileSync(join(plugin, 'scripts', 'document_shape_cli.py'), '# marker\n')
    process.env.SDLC_PLUGIN_ROOT = plugin
    expect(locatePlugin(testDir).available).toBe(false)
  })

  it('a checkout on a branch without the scripts is not usable', () => {
    const testDir = isolatedTestDir()
    const plugin = tempDir('plugin-oldbranch-')
    mkdirSync(join(plugin, 'scripts', '.venv'), { recursive: true })
    process.env.SDLC_PLUGIN_ROOT = plugin
    expect(locatePlugin(testDir).available).toBe(false)
  })

  it('a usable checkout named by the environment is chosen', () => {
    const testDir = isolatedTestDir()
    process.env.SDLC_PLUGIN_ROOT = fakePluginCheckout(tempDir('plugin-good-'))
    const found = locatePlugin(testDir)
    expect(found.available).toBe(true)
    expect(found.python).toContain('.venv')
  })

  it('an unusable environment hint does not stop the containing repository being found', () => {
    // The hint is a hint, not an override. Pointing it somewhere useless should not make the
    // perfectly good plugin this folder actually lives in invisible.
    const base = fakePluginCheckout(tempDir('plugin-parent-'))
    const testDir = join(base, 'studio', 'test')
    mkdirSync(testDir, { recursive: true })
    process.env.SDLC_PLUGIN_ROOT = join(base, 'nowhere-at-all')

    expect(locatePlugin(testDir).root).toBe(base)
  })
})

describe('the plugin this folder lives in', () => {
  it('is the repository two levels up, needing nothing configured', () => {
    // Studio ships inside the plugin, so the parent IS the plugin — including when the work is
    // happening in a git worktree, whose own copy of this folder has its own correct parent.
    // That replaced a search for a sibling checkout plus a scan of its worktrees, which was
    // the machinery that used to pick the wrong plugin (or none) and let the suite go quiet.
    const base = fakePluginCheckout(tempDir('plugin-parent-only-'))
    const testDir = join(base, 'studio', 'test')
    mkdirSync(testDir, { recursive: true })

    expect(locatePlugin(testDir).root).toBe(base)
  })

  it('the real repository is found with no environment variable at all', () => {
    // The regression guard for the original problem, measured against the real layout rather
    // than a fixture. If this ever fails, the integration tests are about to go quiet again.
    delete process.env.SDLC_PLUGIN_ROOT
    expect(locatePlugin(__dirname).available).toBe(true)
  })

  it('the located plugin is one that actually runs', () => {
    // Existence is not usability. A Python executable that cannot execute would make every
    // integration test fail for a reason having nothing to do with what it tests.
    const found = locatePlugin(__dirname)
    const version = execFileSync(found.python, ['--version'], { encoding: 'utf-8' })
    expect(version).toMatch(/^Python 3\./)
  })
})
