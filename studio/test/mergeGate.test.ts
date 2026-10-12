/** Which pull request Studio is willing to merge on its own.
 *
 * Spec 0010's security pass found this merging `prs[0]` from a name search. A search is not
 * an exact filter and it returns other people's pull requests too — on a public repository,
 * anyone's, opened from a fork. Studio then merged it into the protected default branch with
 * the user's credentials, which is precisely the branch protection and review requirement
 * that sent the save down the pull-request path in the first place, undone.
 *
 * Every case below is a way that could happen. The rule is deliberately all-or-nothing:
 * Studio merges the exact branch it pushed, opened by the signed-in account, from this
 * repository rather than a fork.
 */

import { describe, expect, it } from 'vitest'
import { isOursToMerge, type PrListEntry } from '../electron/main/sync'

const OURS: PrListEntry = {
  number: 7,
  headRefName: 'shepherd/1758700000000',
  author: { login: 'matt' },
  headRepositoryOwner: { login: 'MCKRUZ' },
}

const pushed = 'shepherd/1758700000000'

describe('isOursToMerge', () => {
  it('merges the branch this Studio pushed, from this account, in this repository', () => {
    expect(isOursToMerge(OURS, pushed, 'matt', 'MCKRUZ')).toBe(true)
  })

  it('refuses a different branch that merely looks like ours', () => {
    expect(isOursToMerge({ ...OURS, headRefName: 'shepherd/9999999999999' }, pushed, 'matt', 'MCKRUZ')).toBe(false)
    expect(isOursToMerge({ ...OURS, headRefName: 'shepherd/1758700000000-evil' }, pushed, 'matt', 'MCKRUZ')).toBe(false)
  })

  it('refuses a pull request somebody else opened', () => {
    expect(isOursToMerge({ ...OURS, author: { login: 'a-stranger' } }, pushed, 'matt', 'MCKRUZ')).toBe(false)
  })

  it('refuses one whose branch lives in a fork', () => {
    expect(isOursToMerge({ ...OURS, headRepositoryOwner: { login: 'a-stranger' } }, pushed, 'matt', 'MCKRUZ')).toBe(false)
  })

  it('refuses everything when Studio has no pull request outstanding', () => {
    expect(isOursToMerge(OURS, null, 'matt', 'MCKRUZ')).toBe(false)
    expect(isOursToMerge(OURS, undefined, 'matt', 'MCKRUZ')).toBe(false)
    expect(isOursToMerge(OURS, '', 'matt', 'MCKRUZ')).toBe(false)
  })

  it('refuses when it cannot tell who is signed in or whose repository this is', () => {
    // Not knowing must never read as "fine" — that is how an unknown becomes a merge.
    expect(isOursToMerge(OURS, pushed, null, 'MCKRUZ')).toBe(false)
    expect(isOursToMerge(OURS, pushed, 'matt', null)).toBe(false)
  })

  it('refuses when the pull request itself reports no author or head owner', () => {
    expect(isOursToMerge({ ...OURS, author: null }, pushed, 'matt', 'MCKRUZ')).toBe(false)
    expect(isOursToMerge({ ...OURS, headRepositoryOwner: null }, pushed, 'matt', 'MCKRUZ')).toBe(false)
    expect(isOursToMerge({ ...OURS, author: {} }, pushed, 'matt', 'MCKRUZ')).toBe(false)
  })
})

// Code-host providers (Wave 6-B): the same gate, fed an Azure DevOps pull request. The provider
// fills PrListEntry from az's shapes — the author is a UPN (what the host writes on the PR, never
// the roster handle), the "owner" is the repository GUID (`repository.id`, what a fork would
// differ in), and `files` is null because Studio does not complete ADO pull requests in v1
// (D-OWNER-8). The gate itself is untouched: these cases prove it needs no host-specific branch.
describe('isOursToMerge — an Azure DevOps entry', () => {
  const REPO_GUID = '00000000-0000-0000-0000-000000000003'
  const ADO_OURS: PrListEntry = {
    number: 40347,
    headRefName: 'shepherd/1758700000000',
    author: { login: 'person1@example.com' },
    headRepositoryOwner: { login: REPO_GUID },
    files: null,
  }

  it('merges when the UPN and the repository id both match the host\'s own answers', () => {
    expect(isOursToMerge(ADO_OURS, pushed, 'person1@example.com', REPO_GUID)).toBe(true)
  })

  it('refuses the roster handle in place of the UPN — the host did not write the handle on the PR', () => {
    expect(isOursToMerge(ADO_OURS, pushed, 'sam-k', REPO_GUID)).toBe(false)
    expect(isOursToMerge(ADO_OURS, pushed, '@sam-k', REPO_GUID)).toBe(false)
  })

  it('refuses a fork: a different repository id on the head', () => {
    expect(isOursToMerge({ ...ADO_OURS, headRepositoryOwner: { login: '11111111-1111-1111-1111-111111111111' } }, pushed, 'person1@example.com', REPO_GUID)).toBe(false)
  })

  it('refuses when the repository id could not be read (repos show gave no id)', () => {
    expect(isOursToMerge(ADO_OURS, pushed, 'person1@example.com', null)).toBe(false)
  })

  it('files: null is accepted by the type and is the poll\'s fail-closed signal, not the gate\'s concern', () => {
    // The gate answers "is this ours"; what the PR changes is the poll's next question, and
    // `(pr.files ?? []).length === 0` there is what refuses to merge an ADO pull request.
    expect(isOursToMerge(ADO_OURS, pushed, 'person1@example.com', REPO_GUID)).toBe(true)
    expect((ADO_OURS.files ?? []).length).toBe(0)
  })
})
