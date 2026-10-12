/** resolveCodeHost: one decision per project, honestly labelled.
 *
 * The `cli` block it returns is what the renderer's hostFeatureReason reads, so every field is
 * checked for what it claims: `found` only from detection, `extension` null until probed,
 * `signedIn` 'unknown' until a probe ran and 'no' only when the CLI itself said so. A missing
 * CLI yields a NullHost that fails fast with the §7.1 wording — and spawns nothing. */

import { describe, expect, it, vi } from 'vitest'
import { WORDING } from '../shared/codeHostModel'
import { AzError } from '../electron/main/az'
import { CODE_HOST_TTL_MS, CodeHostUnavailable, invalidateCodeHost, NullHost, resolveCodeHost, type ResolveCodeHostDeps } from '../electron/main/codeHost'
import { AzureDevOpsHost } from '../electron/main/hosts/azureDevOpsHost'
import { GitHubHost } from '../electron/main/hosts/githubHost'

const ADO = 'https://dev.azure.com/contoso/Claims/_git/claims-api\n'
const GH = 'git@github.com:acme/widgets.git\n'
const azErr = (failure: AzError['failure'], msg = 'nope') => new AzError(msg, failure, { id: '', command: 'az', args: [], cwd: '', startedAt: '', durationMs: 0, exitCode: 1, stdout: '', stderr: msg, ok: false })

let n = 0
function deps(over: Partial<ResolveCodeHostDeps> & { remote?: string | null; files?: Record<string, string> } = {}) {
  const az = vi.fn(async <T,>(args: string[], _cwd: string): Promise<T> => {
    const verb = args.slice(0, 2).join(' ')
    if (verb === 'extension show') return {} as T
    if (verb === 'account show') return { user: { name: 'sam@contoso.com' }, tenantId: 't1' } as unknown as T
    throw new Error(`unexpected az call: ${args.join(' ')}`)
  })
  const gh = vi.fn(async (args: string[], _cwd: string) => (args[0] === 'api' ? 'sam-k\n' : ''))
  const project = `/p/${++n}`
  const d: ResolveCodeHostDeps = {
    runGit: async () => { if (over.remote === null) throw new Error('fatal: No such remote'); return over.remote ?? ADO },
    azJson: az as unknown as ResolveCodeHostDeps['azJson'], runGh: gh, ghJson: async <T,>() => [] as unknown as T,
    env: {}, readFile: (p) => { const parts = p.split(/[\\/]/); return over.files?.[parts.slice(-2).join('/')] ?? over.files?.[parts[parts.length - 1]!] ?? null },
    found: { gh: true, az: true }, ...over,
  }
  return { d, az, gh, project }
}

describe('resolveCodeHost', () => {
  it('Azure DevOps from origin: az found, extension present, signed in', async () => {
    const { d, az, project } = deps()
    const r = await resolveCodeHost(project, d)
    expect(r).toMatchObject({ host: 'azure-devops', source: 'remote', cli: { name: 'az', found: true, extension: true, signedIn: 'yes' } })
    expect(r.cli.reason).toBeUndefined()
    expect(r.provider).toBeInstanceOf(AzureDevOpsHost)
    expect(az.mock.calls.map((c) => c[0].slice(0, 2).join(' '))).toEqual(['extension show', 'account show'])
  })

  it('az missing → NullHost with the §7.1 reason, nothing spawned, "not installed" (never "not signed in")', async () => {
    const { d, az, project } = deps({ found: { gh: true, az: false } })
    const r = await resolveCodeHost(project, d)
    expect(r.cli).toEqual({ name: 'az', found: false, extension: null, signedIn: 'unknown', reason: WORDING.azMissing })
    expect(r.provider).toBeInstanceOf(NullHost)
    await expect(r.provider.whoAmI()).rejects.toMatchObject({ name: 'CodeHostUnavailable', state: 'not_installed', reason: WORDING.azMissing })
    expect(az).not.toHaveBeenCalled()
  })

  it('extension missing → NullHost; sign-in stays unknown because it was never probed', async () => {
    const { d, az, project } = deps()
    az.mockImplementation(async <T,>(args: string[]): Promise<T> => { if (args[0] === 'extension') throw azErr('exit', 'extension not installed'); return {} as T })
    const r = await resolveCodeHost(project, d)
    expect(r.cli).toMatchObject({ found: true, extension: false, signedIn: 'unknown', reason: WORDING.azExtensionMissing })
    expect(r.provider).toBeInstanceOf(NullHost)
    expect(az.mock.calls.some((c) => c[0][0] === 'account')).toBe(false)
  })

  it('PAT-only → signedIn no with the PAT wording; the real provider stays (az login fixes it within a tick)', async () => {
    const { d, az, project } = deps({ env: { AZURE_DEVOPS_EXT_PAT: 'secret' } })
    az.mockImplementation(async <T,>(args: string[]): Promise<T> => { if (args[0] === 'account') throw azErr('signed_out', "Please run 'az login'"); return {} as T })
    const r = await resolveCodeHost(project, d)
    expect(r.cli).toMatchObject({ extension: true, signedIn: 'no', reason: WORDING.azPatOnly })
    expect(r.provider).toBeInstanceOf(AzureDevOpsHost)
  })

  it('a probe that fails for another reason is unknown, not no', async () => {
    const { d, az, project } = deps()
    az.mockImplementation(async <T,>(args: string[]): Promise<T> => { if (args[0] === 'account') throw new Error('ETIMEDOUT'); return {} as T })
    const r = await resolveCodeHost(project, d)
    expect(r.cli).toMatchObject({ signedIn: 'unknown', reason: 'ETIMEDOUT' })
  })

  it('GitHub from origin: gh, no extension concept, signed in via the existing argv', async () => {
    const { d, gh, project } = deps({ remote: GH })
    const r = await resolveCodeHost(project, d)
    expect(r).toMatchObject({ host: 'github', cli: { name: 'gh', found: true, extension: null, signedIn: 'yes' } })
    expect(r.provider).toBeInstanceOf(GitHubHost)
    expect(gh.mock.calls[0]![0]).toEqual(['api', 'user', '--jq', '.login'])
  })

  it('GitHub signed out is read off gh\'s own words; gh missing gets the mirror wording', async () => {
    const { d, gh, project } = deps({ remote: GH })
    gh.mockRejectedValue(new Error('To get started with GitHub CLI, please run:  gh auth login'))
    expect((await resolveCodeHost(project, d)).cli).toMatchObject({ signedIn: 'no', reason: WORDING.ghSignedOut })
    const { d: d2, project: p2 } = deps({ remote: GH, found: { gh: false, az: true } })
    expect((await resolveCodeHost(p2, d2)).cli.reason).toBe(WORDING.ghMissing)
  })

  it('SHEPHERD_CODE_HOST wins; host none still tries gh but says the features are off', async () => {
    const { d, project } = deps({ env: { SHEPHERD_CODE_HOST: 'none' } })
    const r = await resolveCodeHost(project, d)
    expect(r).toMatchObject({ host: 'none', source: 'env', cli: { name: 'gh', reason: WORDING.hostNone } })
    expect(r.provider).toBeInstanceOf(GitHubHost)
  })

  it('SDLC_CODE_HOST alone still works (the pre-2.0 name), and SHEPHERD_CODE_HOST wins when both are set', async () => {
    const { d, project } = deps({ env: { SDLC_CODE_HOST: 'none' } })
    expect(await resolveCodeHost(project, d)).toMatchObject({ host: 'none', source: 'env' })
    const { d: d2, project: p2 } = deps({ env: { SHEPHERD_CODE_HOST: 'github', SDLC_CODE_HOST: 'none' } })
    const r2 = await resolveCodeHost(p2, d2)
    expect(r2).toMatchObject({ host: 'github', source: 'env' })
    expect(r2.provider).toBeInstanceOf(GitHubHost)
  })

  it('.sdlc/code-host.yaml stands in for an unparseable remote; without the three fields az has no scope', async () => {
    const files = { 'code-host.yaml': 'host: azure-devops\norganization: contoso\nproject: Claims\nrepository: claims-api\n' }
    const { d, project } = deps({ remote: 'https://tfs.corp.example/tfs/DefaultCollection/Claims/_git/claims-api', files })
    const r = await resolveCodeHost(project, d)
    expect(r).toMatchObject({ host: 'azure-devops', source: 'file' })
    expect(r.remote?.orgUrl).toBe('https://dev.azure.com/contoso')
    const { d: d2, project: p2 } = deps({ remote: null, files: { 'code-host.yaml': 'host: azure-devops\n' } })
    const r2 = await resolveCodeHost(p2, d2)
    expect(r2.provider).toBeInstanceOf(NullHost)
    expect(r2.cli.reason).toContain('.sdlc/code-host.yaml must name organization, project and repository')
  })

  it('the manifest breaks the tie only when there is no remote', async () => {
    const files = { 'harness-manifest.json': JSON.stringify({ packs: ['cicd/azure-devops'] }) }
    const { d, project } = deps({ remote: null, files })
    expect(await resolveCodeHost(project, d)).toMatchObject({ host: 'azure-devops', source: 'manifest' })
    const { d: d2, project: p2 } = deps({ remote: GH, files })
    expect(await resolveCodeHost(p2, d2)).toMatchObject({ host: 'github', source: 'remote' })
  })

  it('whoAmI / extension are read once per poll interval and again after it, or after invalidate', async () => {
    let clock = 1_000_000
    const { d, az, project } = deps({ now: () => clock })
    await resolveCodeHost(project, d)
    await resolveCodeHost(project, d)
    expect(az).toHaveBeenCalledTimes(2)
    clock += CODE_HOST_TTL_MS + 1
    await resolveCodeHost(project, d)
    expect(az).toHaveBeenCalledTimes(4)
    invalidateCodeHost(project)
    await resolveCodeHost(project, d)
    expect(az).toHaveBeenCalledTimes(6)
  })

  it('a probe that REJECTED (timeout, not an answer) is not memoised; an answer of "missing" is', async () => {
    const { d, az, project } = deps()
    az.mockRejectedValueOnce(azErr('timeout', 'Timed out'))
    const first = await resolveCodeHost(project, d)
    expect(first.cli.extension).toBeNull() // not probed successfully → unknown, never false
    const second = await resolveCodeHost(project, d)
    expect(second.cli.extension).toBe(true)
    const { d: d2, az: az2, project: p2 } = deps()
    az2.mockRejectedValueOnce(azErr('exit', 'extension not installed'))
    expect((await resolveCodeHost(p2, d2)).cli.extension).toBe(false)
    expect((await resolveCodeHost(p2, d2)).cli.extension).toBe(false) // az answered; kept for the tick
    expect(new CodeHostUnavailable('r', 'unknown', 'h').message).toBe('r h')
  })
})
