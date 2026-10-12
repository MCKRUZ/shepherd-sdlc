/** Both hosts fill the same shapes — proven on the SAME az documents Python's normalisers are
 * tested on (scripts/tests/fixtures/code_host/azure_devops/captured/*.json, real output from a
 * live organisation, anonymised) and on gh-shaped rows beside them. The point of the parity: an
 * Azure DevOps pull request reaches sync.ts's isOursToMerge, its checks rung and its approval
 * rung looking exactly like a GitHub one, with `files: null` as the one deliberate difference
 * (D-OWNER-8: Studio never completes an ADO pull request in v1 — the poll's existing
 * fail-closed branch does the refusing). No az or gh is spawned: azJson is a router over fixtures.
 *
 * Every id, UPN, GUID and branch below is read off the document that carries it
 * (test/adoFixtures.ts) — the anonymiser renames per capture, so nothing is spelled out here.
 * The pure maps are covered row by row in test/codeHostProvidersShapes.test.ts. */

import { describe, expect, it } from 'vitest'
import { WORDING } from '../shared/codeHostModel'
import { AzError, MATERIALIZED_HINT } from '../electron/main/az'
import { CodeHostUnavailable } from '../electron/main/codeHostTypes'
import { ADO_ARGV, AzureDevOpsHost, stripRef } from '../electron/main/hosts/azureDevOpsHost'
import { GitHubHost } from '../electron/main/hosts/githubHost'
import { isOursToMerge, type PrListEntry } from '../electron/main/sync'
import {
  accountShow, configOf, HEAD, isCheckType, policyList, policyRecords, prList, remote, REPO_GUID, reposShow, str, typeIdOf, upn,
  type Dict,
} from './adoFixtures'

const CREATED_ID = 40400 // what the fake `pr create` answers — the one number that is not from a capture
/** The rows the host's `--source-branch HEAD --status active` query must return, in order. */
const expectedOpen = prList.filter((p) => p.status === 'active' && p.sourceRefName === `refs/heads/${HEAD}`)
const answer = <T,>(doc: unknown): T => doc as T

/** The read-only router keyed on the verb — an unexpected call is a failing assertion, which
 * is what pins that the host issues nothing beyond §4.1. */
function fakeAz(opts: { fail?: AzError } = {}) {
  const calls: string[][] = []
  const azJson = async <T,>(args: string[]): Promise<T> => {
    calls.push(args)
    if (opts.fail) throw opts.fail
    const verb = args.slice(0, 3).join(' ')
    if (verb.startsWith('account show')) return answer<T>(accountShow)
    if (verb.startsWith('repos show')) return answer<T>(reposShow)
    // A PolicyEvaluationRecord list's shape does not depend on which PR answered it: route the
    // one this capture filled, so the rollup the host builds has rows to be parity-checked.
    if (verb === 'repos pr policy') return answer<T>(policyRecords)
    if (verb === 'repos pr list') return answer<T>(prList.filter((p) => p.status === 'active' && p.sourceRefName === `refs/heads/${args[args.indexOf('--source-branch') + 1]}`))
    if (verb === 'repos policy list') return answer<T>(policyList)
    if (verb === 'repos pr create') return answer<T>({ pullRequestId: CREATED_ID })
    throw new Error(`unexpected az call: az ${args.join(' ')}`)
  }
  return { azJson, calls }
}

describe('the two hosts fill identical shapes', () => {
  const ghRow: PrListEntry = {
    number: 1, headRefName: HEAD, author: { login: 'octocat' }, headRepositoryOwner: { login: 'acme' },
    files: [{ path: '.sdlc/artifacts/01-requirements/requirements.md' }],
    statusCheckRollup: [{ status: 'COMPLETED', conclusion: 'SUCCESS' }], reviews: [{ state: 'APPROVED' }],
  }
  const shapeOf = (pr: PrListEntry) => ({
    number: typeof pr.number, headRefName: typeof pr.headRefName, authorLogin: typeof pr.author?.login,
    headOwner: typeof pr.headRepositoryOwner?.login,
    checks: (pr.statusCheckRollup ?? []).map((c) => [typeof c.status, c.conclusion === null ? 'null' : typeof c.conclusion]),
    reviews: (pr.reviews ?? []).map((r) => typeof r.state),
  })

  it('listOpenPullRequests → the same PrListEntry the GitHub side returns, except files', async () => {
    expect(expectedOpen.length).toBeGreaterThan(0) // the capture has an active row on HEAD, or this proves nothing
    const gh = new GitHubHost('/p', { runGh: async () => '', ghJson: async <T,>() => answer<T>([ghRow]) })
    const { azJson, calls } = fakeAz()
    const ado = new AzureDevOpsHost('/p', remote, { azJson, env: {} })
    const [fromGh] = await gh.listOpenPullRequests(HEAD)
    const fromAdo = await ado.listOpenPullRequests(HEAD)
    expect(fromAdo.map((p) => p.number)).toEqual(expectedOpen.map((p) => p.pullRequestId))
    const first = fromAdo[0]!
    // gh's twin with the same arity of checks and reviews, so what is compared is the types alone.
    const twin: PrListEntry = {
      ...fromGh!,
      statusCheckRollup: (first.statusCheckRollup ?? []).map((c) => ({ status: 'COMPLETED', conclusion: c.conclusion === null ? null : 'SUCCESS' })),
      reviews: (first.reviews ?? []).map(() => ({ state: 'APPROVED' })),
    }
    expect(shapeOf(first)).toEqual(shapeOf(twin))
    expect(first.statusCheckRollup).toHaveLength(policyRecords.filter((r) => isCheckType(typeIdOf(configOf(r)))).length)
    expect(first.headRepositoryOwner?.login).toBe(REPO_GUID)
    expect(first.files).toBeNull()
    expect(calls[0]).toEqual(ADO_ARGV.prList(remote, HEAD))
    expect(calls[0]).toEqual(expect.arrayContaining(['--detect', 'false', '--org', remote.orgUrl, '--project', remote.project, '--repository', remote.repo, '--source-branch', HEAD, '--status', 'active']))
    expect(calls[1]).toEqual(ADO_ARGV.prPolicyList(remote, first.number))
    expect(calls[1]).toEqual(['repos', 'pr', 'policy', 'list', '--id', String(first.number), '--org', remote.orgUrl])
    expect(calls).toHaveLength(1 + fromAdo.length) // one policy read per open PR, and nothing else
  })

  it('whoAmI / repoView: a UPN and the repository GUID, the two comparands isOursToMerge needs', async () => {
    const { azJson, calls } = fakeAz()
    const ado = new AzureDevOpsHost('/p', remote, { azJson, env: {} })
    const user = accountShow.user as Dict
    expect(str(user.name)).toMatch(/@/) // a UPN, not a display name
    expect(await ado.whoAmI()).toEqual({ login: user.name, kind: 'upn', tenant: accountShow.tenantId })
    const view = await ado.repoView()
    expect(view).toEqual({
      id: REPO_GUID, name: reposShow.name, ownerLogin: null, defaultBranch: stripRef(reposShow.defaultBranch), webUrl: reposShow.webUrl,
      isFork: typeof reposShow.isFork === 'boolean' ? reposShow.isFork : null, headOwnerKey: REPO_GUID,
    })
    expect(remote.repo).toBe(reposShow.name) // the remote was read off this very document
    const branch = view.defaultBranch ?? 'main'
    expect(await ado.isBranchProtected(branch)).toBe(policyList.some((c) => c.isEnabled === true && c.isBlocking === true))
    expect(calls[0]).toEqual(ADO_ARGV.whoAmI())
    expect(calls[1]).toEqual(ADO_ARGV.repoShow(remote))
    expect(calls.at(-1)).toEqual(ADO_ARGV.policyList(remote, REPO_GUID, branch))
    expect(calls.at(-1)).toEqual(expect.arrayContaining(['--detect', 'false', '--org', remote.orgUrl, '--project', remote.project, '--repository-id', REPO_GUID, '--branch', branch]))
    expect(calls.at(-1)).not.toContain('--repository')
  })

  it('isOursToMerge accepts the ADO-filled entry with the raw UPN and the GUID — and the files:null path refuses to merge', async () => {
    const ado = new AzureDevOpsHost('/p', remote, { azJson: fakeAz().azJson, env: {} })
    const [pr] = await ado.listOpenPullRequests(HEAD)
    const view = await ado.repoView()
    const author = upn(expectedOpen[0]!.createdBy)
    const stranger = 'someone-else@example.com'
    expect(author).toMatch(/@/)
    expect(stranger).not.toBe(author)
    expect(isOursToMerge(pr!, HEAD, author, view.headOwnerKey)).toBe(true)
    expect(isOursToMerge(pr!, HEAD, stranger, view.headOwnerKey)).toBe(false)
    expect(isOursToMerge(pr!, HEAD, author, 'some-other-repo')).toBe(false)
    expect(isOursToMerge(pr!, `${HEAD}-other`, author, view.headOwnerKey)).toBe(false)
    // sync.ts: `const prFiles = (pr.files ?? []).map((f) => f.path); if (prFiles.length === 0) return { merged: false }`
    expect((pr!.files ?? []).map((f) => f.path)).toEqual([])
    await expect(ado.mergePullRequest(pr!.number)).rejects.toMatchObject({ name: 'CodeHostUnavailable', state: 'fail_closed' })
  })

  it('createPullRequest mirrors the save fallback: a normal (non-draft) PR, reviewer by email only when resolved', async () => {
    const { azJson, calls } = fakeAz()
    const ado = new AzureDevOpsHost('/p', remote, { azJson, env: {} })
    const result = await ado.createPullRequest({ base: 'master', head: 'shepherd/1', title: 'Edited', body: 'Saved from Shepherd.\n\n-x\nline two', reviewer: 'priya@contoso.com' })
    expect(result.url).toBe(`${remote.webUrl}/pullrequest/${CREATED_ID}`)
    expect(result.note).toMatch(/does not complete Azure DevOps pull requests/)
    expect(calls[0]).toEqual(['repos', 'pr', 'create', '--detect', 'false', '--org', remote.orgUrl, '--project', remote.project, '--repository', remote.repo,
      '--source-branch', 'shepherd/1', '--target-branch', 'master', '--title', 'Edited',
      '--description', 'Saved from Shepherd.', '', ' -x', 'line two', '--required-reviewers', 'priya@contoso.com'])
    expect(calls[0]).not.toContain('--draft')
    expect(ADO_ARGV.prCreate(remote, { base: 'm', head: 'h', title: 't', body: 'b', reviewer: null })).not.toContain('--required-reviewers')
  })

  it('PAT-only and signed-out are told apart, with the §7.1 reason exact and the materialized hint in the message', async () => {
    const fail = new AzError("Please run 'az login'", 'signed_out', { id: '', command: 'az', args: [], cwd: '', startedAt: '', durationMs: 0, exitCode: 1, stdout: '', stderr: '', ok: false })
    const pat = await new AzureDevOpsHost('/p', remote, { azJson: fakeAz({ fail }).azJson, env: { AZURE_DEVOPS_EXT_PAT: 'x' } }).whoAmI().catch((e: unknown) => e)
    expect(pat).toBeInstanceOf(CodeHostUnavailable)
    expect(pat).toMatchObject({ reason: WORDING.azPatOnly, state: 'pat_only' })
    expect((pat as Error).message).toContain(MATERIALIZED_HINT)
    const out = await new AzureDevOpsHost('/p', remote, { azJson: fakeAz({ fail }).azJson, env: {} }).whoAmI().catch((e: unknown) => e)
    expect(out).toMatchObject({ reason: WORDING.azSignedOut, state: 'signed_out' })
  })
})
