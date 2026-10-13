/** The six gh argv Studio issued before the provider layer existed, pinned byte for byte.
 *
 * The provider seam promises zero behaviour change for every GitHub repository Studio already
 * opens. That promise is only as good as this file: a flag "tidied" in githubHost.ts, or a gh
 * call that stops being the ONLY thing a method runs, goes red here instead of changing what
 * happens on someone's protected branch. The expected arrays are the literals from sync.ts at
 * the time the seam was cut (lines 227, 237, 831, 908, 909, 916–919, 968) — not computed. */

import { describe, expect, it, vi } from 'vitest'
import { GitHubHost, GITHUB_ARGV, type GitHubHostDeps } from '../electron/main/hosts/githubHost'

const SIX = {
  whoAmI: ['api', 'user', '--jq', '.login'],
  rulesets: ['api', 'repos/{owner}/{repo}/rulesets'],
  prCreateNoReviewer: ['pr', 'create', '--base', 'main', '--head', 'shepherd/1758700000000', '--title', 'Edited requirements', '--body', 'Saved from Shepherd.\n\nEdited requirements'],
  prCreateReviewer: ['pr', 'create', '--base', 'main', '--head', 'shepherd/1758700000000', '--title', 'Edited requirements', '--body', 'Saved from Shepherd.\n\nEdited requirements', '--reviewer', 'priya-n'],
  repoOwner: ['repo', 'view', '--json', 'owner', '--jq', '.owner.login'],
  prList: ['pr', 'list', '--head', 'shepherd/1758700000000', '--state', 'open', '--json', 'number,headRefName,author,headRepositoryOwner,files,statusCheckRollup,reviews'],
  prMerge: ['pr', 'merge', '7', '--merge'],
}

const create = { base: 'main', head: 'shepherd/1758700000000', title: 'Edited requirements', body: 'Saved from Shepherd.\n\nEdited requirements' }

describe('GITHUB_ARGV golden', () => {
  it('is exactly what sync.ts issued', () => {
    expect(GITHUB_ARGV.whoAmI()).toEqual(SIX.whoAmI)
    expect(GITHUB_ARGV.rulesets()).toEqual(SIX.rulesets)
    expect(GITHUB_ARGV.prCreate({ ...create, reviewer: null })).toEqual(SIX.prCreateNoReviewer)
    // sync.ts stripped the roster `@` itself before pushing --reviewer; the host does the same.
    expect(GITHUB_ARGV.prCreate({ ...create, reviewer: '@priya-n' })).toEqual(SIX.prCreateReviewer)
    expect(GITHUB_ARGV.prCreate({ ...create, reviewer: 'priya-n' })).toEqual(SIX.prCreateReviewer)
    expect(GITHUB_ARGV.repoOwner()).toEqual(SIX.repoOwner)
    expect(GITHUB_ARGV.prList('shepherd/1758700000000')).toEqual(SIX.prList)
    expect(GITHUB_ARGV.prMerge(7)).toEqual(SIX.prMerge)
  })
})

describe('GitHubHost runs nothing but those argv', () => {
  it('one call per method, through runGh/ghJson, in /p', async () => {
    const runGh = vi.fn(async (args: string[], _cwd: string) => {
      if (args[0] === 'api') return 'matt\n'
      if (args[0] === 'repo') return 'MCKRUZ\n'
      return 'https://github.com/MCKRUZ/x/pull/7\n'
    })
    const ghJson = vi.fn(async <T,>(args: string[], _cwd: string): Promise<T> => (args[0] === 'api' ? [{ enforcement: 'active' }] : [{ number: 7 }]) as unknown as T)
    const host = new GitHubHost('/p', { runGh, ghJson: ghJson as unknown as GitHubHostDeps['ghJson'] })

    expect(await host.whoAmI()).toEqual({ login: 'matt', kind: 'login' })
    expect((await host.repoView()).headOwnerKey).toBe('MCKRUZ')
    expect(await host.isBranchProtected('main')).toBe(true)
    expect(await host.createPullRequest({ ...create, reviewer: '@priya-n' })).toEqual({ url: 'https://github.com/MCKRUZ/x/pull/7' })
    expect(await host.listOpenPullRequests('shepherd/1758700000000')).toEqual([{ number: 7 }])
    expect(await host.mergePullRequest(7)).toBe('https://github.com/MCKRUZ/x/pull/7')

    expect(runGh.mock.calls.map((c) => c[0])).toEqual([SIX.whoAmI, SIX.repoOwner, SIX.prCreateReviewer, SIX.prMerge])
    expect(ghJson.mock.calls.map((c) => c[0])).toEqual([SIX.rulesets, SIX.prList])
    for (const c of [...runGh.mock.calls, ...ghJson.mock.calls]) expect(c[1]).toBe('/p')
  })

  it('an empty login is an error, not an Identity with no name', async () => {
    const host = new GitHubHost('/p', { runGh: async () => '\n', ghJson: async <T,>() => [] as unknown as T })
    await expect(host.whoAmI()).rejects.toThrow(/no login/)
  })
})
