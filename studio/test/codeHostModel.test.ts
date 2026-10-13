/** The remote → host rule, on the fixture Python owns.
 *
 * `scripts/tests/fixtures/code_host/remote-urls.json` is read by pytest and by this file, so the
 * TypeScript port of parse_remote cannot drift from the Python one without one side going red.
 * The fixture is reached through test/pluginRoot.ts: Studio ships inside the plugin, so the
 * plugin is the folder above this one, on whichever branch this copy belongs to.
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  cliFor, cliLabel, detectHostFromInputs, hostFeatureReason, parseCodeHostYaml, parseRemote, WORDING,
  type CliStatus,
} from '../shared/codeHostModel'
import { locatePlugin } from './pluginRoot'

interface Row {
  url: string
  host: 'github' | 'azure-devops' | 'none'
  org: string | null
  project: string | null
  repo: string | null
  slug: string | null
  org_url: string | null
}

const plugin = locatePlugin(__dirname)
const fixturePath = join(plugin.root ?? plugin.searched[plugin.searched.length - 1]!, 'scripts', 'tests', 'fixtures', 'code_host', 'remote-urls.json')
const rows = (JSON.parse(readFileSync(fixturePath, 'utf-8')) as Array<Row | { _comment: string }>)
  .filter((r): r is Row => 'url' in r)

describe('parseRemote (shared fixture)', () => {
  it('reads the fixture pytest reads', () => {
    expect(rows.length).toBeGreaterThan(20)
  })

  for (const row of rows) {
    it(`${JSON.stringify(row.url)} → ${row.host}`, () => {
      const got = parseRemote(row.url)
      if (row.host === 'none') {
        expect(got).toBeNull()
        return
      }
      expect(got).not.toBeNull()
      expect(got!.host).toBe(row.host)
      expect(got!.org).toBe(row.org)
      expect(got!.project).toBe(row.project)
      expect(got!.repo).toBe(row.repo)
      expect(got!.slug).toBe(row.slug)
      expect(got!.orgUrl).toBe(row.org_url)
    })
  }

  it('never throws on garbage', () => {
    for (const bad of [null, undefined, '', '   ', 'https://', '://x', 'a@b:', 'https://dev.azure.com//x/_git/y', 'x\ny']) {
      expect(() => parseRemote(bad)).not.toThrow()
      expect(parseRemote(bad)).toBeNull()
    }
  })
})

describe('detectHostFromInputs — the same precedence as scripts/code_host.py', () => {
  const ado = 'https://dev.azure.com/contoso/Claims/_git/claims-api'
  const gh = 'https://github.com/acme/widgets.git'

  it('env beats the file beats the remote; the parsed remote still rides along', () => {
    const d = detectHostFromInputs({ flagOrEnv: 'github', fileHost: { host: 'none' }, remoteUrl: ado })
    expect(d).toMatchObject({ host: 'github', source: 'env' })
    expect(d.remote?.host).toBe('azure-devops')
    expect(detectHostFromInputs({ fileHost: { host: 'none' }, remoteUrl: ado })).toMatchObject({ host: 'none', source: 'file' })
    expect(detectHostFromInputs({ remoteUrl: ado })).toMatchObject({ host: 'azure-devops', source: 'remote' })
  })

  it('an unrecognised env value is ignored and named in the detail, not obeyed', () => {
    const d = detectHostFromInputs({ flagOrEnv: 'bitbucket', remoteUrl: gh })
    expect(d).toMatchObject({ host: 'github', source: 'remote' })
    expect(d.detail).toContain('SHEPHERD_CODE_HOST="bitbucket" ignored')
  })

  it('SHEPHERD_CODE_HOST wins over SDLC_CODE_HOST, and the detail names the one that decided', () => {
    const d = detectHostFromInputs({ flagOrEnv: 'github', legacyEnv: 'azure-devops', remoteUrl: ado })
    expect(d).toMatchObject({ host: 'github', source: 'env', detail: 'SHEPHERD_CODE_HOST=github' })
  })

  it('SDLC_CODE_HOST alone still decides — the pre-2.0 name is read, after the new one', () => {
    const d = detectHostFromInputs({ legacyEnv: 'none', remoteUrl: ado })
    expect(d).toMatchObject({ host: 'none', source: 'env', detail: 'SDLC_CODE_HOST=none' })
    expect(d.remote?.host).toBe('azure-devops')
    // An empty new name counts as unset, as it always did, so the old one is still read.
    expect(detectHostFromInputs({ flagOrEnv: '', legacyEnv: 'none', remoteUrl: ado })).toMatchObject({ host: 'none', source: 'env', detail: 'SDLC_CODE_HOST=none' })
    // And an unrecognised old value is named under the old name — the variable the person set.
    const bad = detectHostFromInputs({ legacyEnv: 'bitbucket', remoteUrl: gh })
    expect(bad).toMatchObject({ host: 'github', source: 'remote' })
    expect(bad.detail).toContain('SDLC_CODE_HOST="bitbucket" ignored')
  })

  it('the file\'s organisation/project/repository stand in for a remote nobody could parse', () => {
    const d = detectHostFromInputs({
      fileHost: { host: 'azure-devops', organization: 'contoso', project: 'Claims', repository: 'claims-api' },
      remoteUrl: 'https://tfs.corp.example/tfs/DefaultCollection/Claims/_git/claims-api',
    })
    expect(d.remote).toMatchObject({ host: 'azure-devops', slug: 'contoso/Claims/claims-api', orgUrl: 'https://dev.azure.com/contoso' })
  })

  it('the manifest is a tie-breaker only: never over a parsed remote', () => {
    expect(detectHostFromInputs({ remoteUrl: null, manifestPacks: ['cicd/azure-devops'] })).toMatchObject({ host: 'azure-devops', source: 'manifest' })
    expect(detectHostFromInputs({ remoteUrl: gh, manifestPacks: ['cicd/azure-devops'] })).toMatchObject({ host: 'github', source: 'remote' })
    const none = detectHostFromInputs({ remoteUrl: 'https://gitlab.com/a/b.git', manifestPacks: [] })
    expect(none).toMatchObject({ host: 'none', source: 'default' })
    expect(none.detail).toContain('unrecognised host "gitlab.com"')
    expect(detectHostFromInputs({ remoteUrl: null }).detail).toContain('no origin remote')
  })

  it('host none still means gh, as before', () => {
    expect(cliFor('none')).toBe('gh')
    expect(cliFor('azure-devops')).toBe('az')
    expect(cliLabel('azure-devops')).toContain('az')
  })
})

describe('parseCodeHostYaml — four keys, comments allowed', () => {
  it('reads the documented file', () => {
    const { settings, error } = parseCodeHostYaml('# which host\nhost: azure-devops   # trailing\norganization: "contoso"\nproject: Claims\nrepository: ~\n')
    expect(error).toBeNull()
    expect(settings).toEqual({ host: 'azure-devops', organization: 'contoso', project: 'Claims' })
  })

  it('refuses an unknown host and a non-mapping, naming the file', () => {
    expect(parseCodeHostYaml('host: bitbucket').error).toContain('.sdlc/code-host.yaml: host must be one of')
    expect(parseCodeHostYaml('- just a list').error).toContain('expected a mapping')
    expect(parseCodeHostYaml('').error).toContain('got null')
  })
})

describe('hostFeatureReason — §7.1, computed from facts, never from a guess', () => {
  const ok: CliStatus = { name: 'az', found: true, extension: true, signedIn: 'yes' }

  it('is null when everything is in place, and when sign-in is simply not probed yet', () => {
    expect(hostFeatureReason({ host: 'azure-devops', cli: ok }, 'board')).toBeNull()
    expect(hostFeatureReason({ host: 'azure-devops', cli: { ...ok, signedIn: 'unknown' } }, 'handoff')).toBeNull()
  })

  it('names the CLI the project actually needs when it is missing', () => {
    const cli: CliStatus = { name: 'az', found: false, extension: null, signedIn: 'unknown', reason: WORDING.azMissing }
    expect(hostFeatureReason({ host: 'azure-devops', cli }, 'board')).toBe('Live pull-request status needs the Azure CLI')
    expect(hostFeatureReason({ host: 'azure-devops', cli }, 'handoff')).toBe('The hand-off completes locally; assigning on Azure DevOps needs az')
    expect(hostFeatureReason({ host: 'azure-devops', cli }, 'saveWhenProtected')).toContain('nothing was saved to the shared branch')
    expect(hostFeatureReason({ host: 'azure-devops', cli }, 'signedInAs')).toBe('unavailable (az not installed)')
    expect(hostFeatureReason({ host: 'github', cli: { ...cli, name: 'gh' } }, 'board')).toBe('Live pull-request status needs the GitHub CLI')
  })

  it('tells a missing extension and a PAT-only sign-in apart', () => {
    expect(hostFeatureReason({ host: 'azure-devops', cli: { ...ok, extension: false } }, 'signedInAs')).toBe('unavailable (azure-devops extension missing)')
    expect(hostFeatureReason({ host: 'azure-devops', cli: { ...ok, signedIn: 'no', reason: WORDING.azPatOnly } }, 'signedInAs')).toBe('unavailable (signed in with a PAT only)')
    expect(hostFeatureReason({ host: 'azure-devops', cli: { ...ok, signedIn: 'no', reason: WORDING.azSignedOut } }, 'signedInAs')).toBe('unavailable (not signed in)')
  })

  it('host none turns the features off with the legacy wording', () => {
    expect(hostFeatureReason({ host: 'none', cli: { ...ok, name: 'gh' } }, 'board')).toBe(WORDING.hostNone)
  })
})
