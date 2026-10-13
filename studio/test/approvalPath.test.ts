/** Saving a document, with and without an approval step, against a REAL git remote.
 *
 * Spec 0010's approval checks were the last part with no verification at all, on the grounds
 * that they "need a real code host". Two thirds of that turns out to be wrong: the mechanism
 * is ordinary git. A pending draft is a branch, and what makes it pending is that the push to
 * the shared branch was REFUSED — which a local repository can refuse just as well as GitHub
 * can. Only opening the pull request itself needs GitHub.
 *
 * So this builds a bare repository to act as the remote, clones it, and saves for real:
 *
 *   approval off   → the change lands on the shared branch, with who and why recorded
 *   push refused   → the shared branch is left exactly as it was, and the work is parked on
 *                    a branch of its own instead
 *
 * The refusal is done with a server-side hook, which is how branch protection behaves from
 * the client's point of view: the push is simply rejected. That is also the app's own stated
 * gate — "the real gate is whether a direct push gets rejected", never a guess about settings.
 *
 * A later pass found the last sentence above was wrong in one respect: "who opened it" is just
 * a name Studio stores locally the moment a draft's pull request is created, so the REFUSAL is
 * provable here without a second machine — seed the same persisted state a real save would
 * have left, then call save() for real as a different actor and watch it refuse before it ever
 * touches the network. What still needs GitHub is the pull request itself, which is why the
 * seed is written directly rather than produced by driving a whole save through this fixture.
 */

import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import {
  getLastSeenCommit, getProjectSyncState, initSettingsPath, saveProjectSyncState, setLastSeenCommit,
} from '../electron/main/settings'
import { pull, save } from '../electron/main/sync'
import { getDocumentChanges, openDocument, setField } from '../electron/main/documents'
import { listVersions } from '../electron/main/history'
import { requirePlugin } from './pluginRoot'

// Located once, in one place, and LOUD when it cannot be found — a run that skipped the
// integration tests used to report success, which is how a run that proved nothing came
// to look like a run that proved everything. See test/pluginRoot.ts.
const PLUGIN = requirePlugin(__dirname)

const PLUGIN_ROOT = PLUGIN.root
const SCRIPTS_DIR = PLUGIN.scriptsDir
const VENV_PYTHON = PLUGIN.python
const REQUIREMENTS = '.sdlc/artifacts/01-requirements/requirements.md'

const available = PLUGIN.available

let workspace = ''
let origin = ''
let project = ''

function git(args: string[], cwd: string): string {
  return execFileSync('git', args, { cwd, encoding: 'utf-8' }).trim()
}

/** Refuse every push to the shared branch, the way a protected branch does — from the
 * client's side the two are indistinguishable, which is the whole point. */
function protectSharedBranch(branch: string): void {
  const hookDir = join(origin, 'hooks')
  mkdirSync(hookDir, { recursive: true })
  writeFileSync(
    join(hookDir, 'pre-receive'),
    `#!/bin/sh\nwhile read _old _new ref; do\n  if [ "$ref" = "refs/heads/${branch}" ]; then\n    echo "protected branch" >&2\n    exit 1\n  fi\ndone\nexit 0\n`,
    { mode: 0o755 },
  )
}

function unprotect(): void {
  rmSync(join(origin, 'hooks', 'pre-receive'), { force: true })
}

/** Change one field the way the document layer does, so the save has something real to push. */
async function editSomething(value: string): Promise<void> {
  const doc = await openDocument(project, SCRIPTS_DIR, REQUIREMENTS)
  const section = doc.sections.find((s) => Object.values(s.fields).some((f) => f && !f.empty))!
  const [label] = Object.entries(section.fields).find(([, f]) => f && !f.empty)!
  const result = await setField(project, SCRIPTS_DIR, REQUIREMENTS, section.key, label, value)
  expect(result.ok, result.error).toBe(true)
}

describe.skipIf(!available)('saving a document through a real remote', () => {
  let branch = ''

  beforeAll(async () => {
    workspace = mkdtempSync(join(tmpdir(), 'studio-approval-'))
    initSettingsPath(join(workspace, 'userData'))

    origin = join(workspace, 'origin.git')
    project = join(workspace, 'project')
    git(['init', '--bare', '--initial-branch=main', origin], workspace)
    git(['clone', origin, project], workspace)
    git(['config', 'user.email', 'test@example.com'], project)
    git(['config', 'user.name', 'Test Person'], project)

    execFileSync(VENV_PYTHON, [
      join(SCRIPTS_DIR, 'init_project.py'),
      '--profile', join(PLUGIN_ROOT!, 'profiles', 'microsoft-enterprise', 'profile.yaml'),
      '--target', project,
    ], { cwd: SCRIPTS_DIR })

    mkdirSync(join(project, '.sdlc', 'artifacts', '01-requirements'), { recursive: true })
    writeFileSync(
      join(project, REQUIREMENTS),
      readFileSync(join(SCRIPTS_DIR, 'tests', 'fixtures', 'documents', 'requirements.md')),
    )

    git(['add', '-A'], project)
    git(['commit', '-m', 'initial project'], project)
    git(['push', '-u', 'origin', 'main'], project)
    branch = git(['branch', '--show-current'], project)
    expect(branch).toBe('main')

    // Sync once before touching anything. This is not test scaffolding — it is what opening
    // a project does, and it is what establishes the shared starting point every later save
    // is measured against. Without it the very first edit looks like "local and remote
    // already disagree and I have no idea which is right", which Studio correctly refuses to
    // guess about. (The first version of this test skipped it and read the refusal as a bug.)
    const firstPull = await pull(project, SCRIPTS_DIR)
    expect(firstPull.ok, firstPull.error).toBe(true)
    expect(firstPull.clashes).toHaveLength(0)
  }, 180_000)

  afterAll(() => {
    if (workspace) rmSync(workspace, { recursive: true, force: true })
  })

  it('with no approval step, the change lands on the shared branch with who and why', async () => {
    await editSomething('EDITED WITH APPROVAL OFF')

    const result = await save(project, SCRIPTS_DIR, 'tightened the wording', {
      actor: 'matt', onlyPath: REQUIREMENTS,
    })
    expect(result.ok, result.error).toBe(true)
    expect(result.outcome).toBe('pushed_directly')

    // The remote really has it — read from the bare repository, not from the local copy.
    const onRemote = git(['show', `main:${REQUIREMENTS}`], origin)
    expect(onRemote).toContain('EDITED WITH APPROVAL OFF')

    // "still records who changed it and why"
    const versions = await listVersions(project, SCRIPTS_DIR, REQUIREMENTS)
    const latest = versions[versions.length - 1]
    expect(latest.actor).toBe('matt')
    expect(latest.reason).toBe('tightened the wording')
  }, 120_000)

  it('when the shared branch refuses the push, it is left exactly as it was', async () => {
    const before = git(['rev-parse', 'main'], origin)
    protectSharedBranch('main')
    try {
      await editSomething('EDITED WHILE THE BRANCH WAS PROTECTED')
      // Opening the pull request needs GitHub, which is not here — so the save reports a
      // failure at that step. What matters for this check is what it did to the repository
      // BEFORE that point, which is asserted below.
      await save(project, SCRIPTS_DIR, 'a change that needs approval', {
        actor: 'matt', onlyPath: REQUIREMENTS,
      })

      // The signed-off version stays in place for everyone else — the shared branch has not
      // moved at all.
      expect(git(['rev-parse', 'main'], origin)).toBe(before)
      expect(git(['show', `main:${REQUIREMENTS}`], origin)).not.toContain('WHILE THE BRANCH WAS PROTECTED')

      // And the work is parked on a branch of its own, which is what a pending draft IS.
      const branches = git(['branch', '--list', 'shepherd/*'], origin)
      expect(branches, 'no shepherd/* branch was pushed').toMatch(/shepherd\//)

      const parked = branches.split('\n')[0].trim().replace(/^\*?\s*/, '')
      expect(git(['show', `${parked}:${REQUIREMENTS}`], origin)).toContain('WHILE THE BRANCH WAS PROTECTED')
    } finally {
      unprotect()
    }
  }, 120_000)

  // "While a draft waits for approval, only the person who created it can change it —
  // everyone else is refused, with a clear reason." A pending draft is a parked branch plus
  // whoever's name Studio recorded when it pushed it — both already sitting in this project's
  // persisted sync state, so the refusal (and the owner's own save still landing) can be
  // proven directly, with no second machine and no GitHub involved.
  describe('only the owner may change a pending draft', () => {
    it('refuses someone else, and still lets the owner save', async () => {
      const beforeRemote = git(['rev-parse', 'main'], origin)

      const state = getProjectSyncState(project)
      state.pendingPrBranch = 'studio/seeded-pending'
      state.pendingDraftOwner = 'priya'
      state.pendingDraftFiles = [REQUIREMENTS]
      saveProjectSyncState(project, state)

      await editSomething('A STRANGER TRYING TO SNEAK IN A CHANGE')
      const refused = await save(project, SCRIPTS_DIR, 'not my draft to change', {
        actor: 'matt', onlyPath: REQUIREMENTS,
      })
      expect(refused.ok).toBe(false)
      expect(refused.error).toContain('priya')
      expect(refused.error).toContain('still waiting for approval')

      // Refused before it ever touched the network — the remote hasn't moved, and Studio's
      // own record of the pending draft is untouched.
      expect(git(['rev-parse', 'main'], origin)).toBe(beforeRemote)
      expect(getProjectSyncState(project).pendingPrBranch).toBe('studio/seeded-pending')

      // The owner naming themselves is a different story — their own save goes through (this
      // single-checkout fixture has one shared working copy, so it is priya's save that lands
      // whatever text is on disk right now — the gate is about WHO may publish, not a claim
      // that the bytes themselves are re-authored).
      const owners = await save(project, SCRIPTS_DIR, 'the actual owner finishing their draft', {
        actor: 'priya', onlyPath: REQUIREMENTS,
      })
      expect(owners.ok, owners.error).toBe(true)
      expect(git(['show', `main:${REQUIREMENTS}`], origin)).toContain('A STRANGER TRYING TO SNEAK IN A CHANGE')

      // And landing it resolves the draft — nothing is left pending to block the next save.
      expect(getProjectSyncState(project).pendingPrBranch).toBeFalsy()
    }, 120_000)
  })

  // "Changes made since the person last opened it are marked, with who made each one and
  // why." This needed a repository with history and a second author — both of which the
  // fixture above can provide, by pushing from a separate clone the way a colleague would.
  describe('changes since the person last looked', () => {
    let colleague = ''

    beforeAll(() => {
      colleague = join(workspace, 'colleague')
      git(['clone', origin, colleague], workspace)
      git(['config', 'user.email', 'priya@example.com'], colleague)
      git(['config', 'user.name', 'Priya N'], colleague)

      const theirCopy = join(colleague, REQUIREMENTS)
      writeFileSync(theirCopy, `${readFileSync(theirCopy, 'utf-8')}\n<!-- a note from a colleague -->\n`)
      git(['add', REQUIREMENTS], colleague)
      git(['commit', '-m', 'clarified the dedup rule'], colleague)
      git(['push', 'origin', 'main'], colleague)
      git(['fetch', 'origin'], project)
    })

    it('names who changed it, when, and why', async () => {
      const branchName = git(['branch', '--show-current'], project)
      const changes = await getDocumentChanges(project, REQUIREMENTS, getLastSeenCommit(project, REQUIREMENTS), branchName)

      const theirs = changes.find((c) => c.reason === 'clarified the dedup rule')
      expect(theirs, `colleague's change not listed: ${JSON.stringify(changes)}`).toBeTruthy()
      expect(theirs!.author).toBe('Priya N')
      expect(theirs!.when).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    }, 60_000)

    it('marking it seen clears it, and only then', async () => {
      const branchName = git(['branch', '--show-current'], project)
      // Reading must not have cleared anything on its own — that is the point of "mark as
      // seen" being a separate, explicit act rather than a side effect of opening.
      await getDocumentChanges(project, REQUIREMENTS, getLastSeenCommit(project, REQUIREMENTS), branchName)
      expect(getLastSeenCommit(project, REQUIREMENTS)).toBeNull()

      setLastSeenCommit(project, REQUIREMENTS, git(['rev-parse', `origin/${branchName}`], project))
      const after = await getDocumentChanges(project, REQUIREMENTS, getLastSeenCommit(project, REQUIREMENTS), branchName)
      expect(after).toHaveLength(0)
    }, 60_000)
  })
})
