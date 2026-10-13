/** The marketplace-cache scan reads both plugin ids (brand update D18: both during 2.x, the
 * current id preferred).
 *
 * A packaged 2.x Studio beside a plugin still installed as `claude-code-sdlc` would otherwise
 * report "no plugin"; and a copy cached under `shepherd` must win over one under the old id
 * whatever their versions, or an update would be undone by a stale cache entry. Proven on real
 * directories under a stand-in home, built the way toolingDetect.test.ts builds its stand-in
 * plugins: Node's homedir() reads HOME (POSIX) / USERPROFILE (Windows), so pointing those at a
 * temp directory points the scan there — no fs mock, and the real cache is never read.
 */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { LEGACY_PLUGIN_IDS, PLUGIN_ID } from '../shared/pluginId'
import { detectPluginScripts, PLUGIN_MARKER } from '../electron/main/tooling'

const LEGACY_ID = LEGACY_PLUGIN_IDS[0]
const HOME_VARS = ['HOME', 'USERPROFILE'] as const
const saved = HOME_VARS.map((name) => [name, process.env[name]] as const)

let home: string
let cacheDir: string
let appRoot: string // has no `../scripts`, so the sibling checkout never pre-empts the scan

beforeAll(() => {
  home = mkdtempSync(join(tmpdir(), 'studio-plugin-cache-'))
  cacheDir = join(home, '.claude', 'plugins', 'cache')
  appRoot = join(home, 'app')
  for (const name of HOME_VARS) process.env[name] = home
  // The redirect must hold on this platform, or every test below would read the real cache.
  expect(homedir()).toBe(home)
})

afterEach(() => rmSync(join(home, '.claude'), { recursive: true, force: true }))

afterAll(() => {
  for (const [name, value] of saved) {
    if (value === undefined) delete process.env[name]
    else process.env[name] = value
  }
  rmSync(home, { recursive: true, force: true })
})

/** One cached install: `~/.claude/plugins/cache/<namespace>/<id>/<version>/`, with a manifest
 * declaring its version and (unless told otherwise) the marker a current plugin carries. */
function cachePlugin(namespace: string, id: string, version: string, { marker = true } = {}): string {
  const root = join(cacheDir, namespace, id, version)
  const scripts = join(root, 'scripts')
  mkdirSync(scripts, { recursive: true })
  mkdirSync(join(root, '.claude-plugin'), { recursive: true })
  writeFileSync(join(root, '.claude-plugin', 'plugin.json'), JSON.stringify({ name: id, version }))
  if (marker) writeFileSync(join(scripts, PLUGIN_MARKER), '')
  return scripts
}

describe('detectPluginScripts — the marketplace cache scan', () => {
  it('finds a plugin cached under the current id, and says so with its version', async () => {
    const scripts = cachePlugin('mckruz', PLUGIN_ID, '2.0.0')
    const status = await detectPluginScripts(undefined, appRoot)
    expect(status).toEqual({ found: true, path: scripts, source: 'cache', pluginVersion: '2.0.0' })
  })

  it('still finds a plugin cached only under the pre-2.0 id (LEGACY_PLUGIN_IDS)', async () => {
    const scripts = cachePlugin('mckruz', LEGACY_ID, '1.6.2')
    const status = await detectPluginScripts(undefined, appRoot)
    expect(status).toEqual({ found: true, path: scripts, source: 'cache', pluginVersion: '1.6.2' })
  })

  it('prefers the current id over the old one even when the old copy declares a higher version', async () => {
    const current = cachePlugin('mckruz', PLUGIN_ID, '2.0.0')
    cachePlugin('mckruz', LEGACY_ID, '9.9.9')
    cachePlugin('another-marketplace', LEGACY_ID, '10.0.0')
    const status = await detectPluginScripts(undefined, appRoot)
    expect(status.path).toBe(current)
    expect(status.pluginVersion).toBe('2.0.0')
  })

  it('within one id, the newest version wins', async () => {
    cachePlugin('mckruz', PLUGIN_ID, '2.0.0')
    const newest = cachePlugin('mckruz', PLUGIN_ID, '2.1.0')
    cachePlugin('mckruz', PLUGIN_ID, '2.0.5')
    const status = await detectPluginScripts(undefined, appRoot)
    expect(status.path).toBe(newest)
    expect(status.pluginVersion).toBe('2.1.0')
  })

  it('a copy under the current id without the marker is an older plugin, so a marked copy under the old id is chosen instead', async () => {
    cachePlugin('mckruz', PLUGIN_ID, '2.0.0', { marker: false })
    const legacy = cachePlugin('mckruz', LEGACY_ID, '1.6.2')
    const status = await detectPluginScripts(undefined, appRoot)
    expect(status.path).toBe(legacy)
  })

  it('with a cache but no usable copy under either id, the refusal names the plugin and the marker', async () => {
    cachePlugin('mckruz', PLUGIN_ID, '2.0.0', { marker: false })
    cachePlugin('mckruz', 'some-other-plugin', '3.0.0')
    const status = await detectPluginScripts(undefined, appRoot)
    expect(status.found).toBe(false)
    expect(status.error).toContain('Shepherd')
    expect(status.error).toContain(PLUGIN_MARKER)
  })

  it('with no cache directory at all, the refusal names the directory it looked for', async () => {
    const status = await detectPluginScripts(undefined, appRoot)
    expect(status.found).toBe(false)
    expect(status.error).toContain(cacheDir)
  })
})
