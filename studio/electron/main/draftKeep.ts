// What happens to a finished candidate (spec 0027): Keep writes it, Discard does not. Both are
// recorded, and neither can lose the other's work.
//
// Keep is the one place a model job's text reaches the disk, so it is a single audited write:
//
//   1. Re-validate the target with the same guards a normal document write uses (allowlist, no link,
//      inside the project). The candidate was checked when the job started; the project may have changed
//      since, and this is the boundary that matters.
//   2. If a file is there, capture it into the version history FIRST (`audit_artifacts.py record --scan`)
//      and confirm the capture, because replacing a hand-corrected summary silently is the loss the
//      history exists to prevent. If it cannot be confirmed, nothing is written.
//   3. Write the whole document through a temp file and a rename, so a crash never leaves half a document.
//   4. Record it: the change (`created` or `revised`; the script has no "drafted" event) and the draft
//      outcome. A failure of either is a warning, never a reason to lose the document just written.

import { createHash, randomUUID } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { recordDraftOutcome } from './drafts'
import { runPluginScript } from './project'
import { rawStdout } from './commandRunner'
import { isKeepableTarget } from './draftTargets'
import { resolveProjectDocument } from './projectPaths'
import type { DraftKind, DraftOutcome, KeepDraftResult } from '../../shared/types'

const WHOLE_DOCUMENT = '(whole document)'
const KEPT_REASON = 'Drafted by Claude'
const stateFile = (project: string) => join(project, '.sdlc', 'state.yaml')

/** The same short hash the plugin's change ledger uses (`sha256:` plus the first 16 hex). */
const ledgerHash = (bytes: Buffer): string => `sha256:${createHash('sha256').update(bytes).digest('hex').slice(0, 16)}`

/** The document as it will be written: exactly the candidate's text, ending in one newline. */
export const documentText = (text: string): string => `${text.replace(/\s+$/, '')}\n`

/** What Keep needs to know about one result, whichever job made it: a spec 0027 draft, or one candidate
 * of a spec 0029 batch (which has no `kind`, and no findings to record). */
export interface KeepSubject {
  target: string
  text: string
  kind?: DraftKind
}

/** Decides which targets a caller will write. Keep checks it again at the moment of writing. */
export type TargetPermit = (target: string) => boolean

function checkTarget(projectPath: string, target: string, permit: TargetPermit): { full: string } | { error: string } {
  if (!permit(target)) {
    return { error: `${target} is not a document Shepherd may write a draft to.` }
  }
  try {
    return { full: resolveProjectDocument(projectPath, target) }
  } catch (err) {
    return { error: (err as Error).message }
  }
}

/** Whether the history lists a version with the file's current hash whose content is stored. The plugin's
 * scripts exit 0 whatever happens, so an exit code proves nothing here; reading the history back does. */
async function isCaptured(projectPath: string, scriptsDir: string, target: string, current: Buffer): Promise<boolean> {
  const listed = await runPluginScript(scriptsDir, 'audit_artifacts.py', ['version', 'list', target, '--json', '--state', stateFile(projectPath)])
  if (!listed.ok) return false
  try {
    const versions = (JSON.parse(rawStdout(listed)) as { versions?: Array<{ hash?: string; present?: boolean }> }).versions ?? []
    const wanted = ledgerHash(current)
    return versions.some((v) => v.hash === wanted && v.present === true)
  } catch {
    return false
  }
}

/** Captures the file that is about to be replaced, and proves it. `record --scan` is the normal way; it
 * records only what changed since the ledger last saw it, so on a machine that holds the shared ledger
 * but never stored this file's bytes (a fresh clone — the store is local) it captures nothing. Then an
 * explicit snapshot of this one file does. */
async function captureExisting(projectPath: string, scriptsDir: string, target: string, actor: string): Promise<boolean> {
  const state = stateFile(projectPath)
  const current = readFileSync(resolveProjectDocument(projectPath, target))
  await runPluginScript(scriptsDir, 'audit_artifacts.py', ['record', '--scan', '--state', state])
  if (await isCaptured(projectPath, scriptsDir, target, current)) return true
  await runPluginScript(scriptsDir, 'audit_artifacts.py', [
    'record', '--artifact', target, '--event', 'snapshot', '--actor', actor,
    '--reason', 'Before replacing with a draft by Claude', '--state', state,
  ])
  return isCaptured(projectPath, scriptsDir, target, current)
}

/** Writes the whole file by way of a temp file beside it. The temp name is random and created
 * exclusively (`wx`): a predictable name could be pre-planted as a link in a repository, and a plain
 * write would follow it out of the project. A temp file is never left behind, whatever fails. */
export function writeWhole(full: string, text: string): void {
  mkdirSync(dirname(full), { recursive: true })
  const temp = `${full}.${randomUUID()}.tmp`
  try {
    writeFileSync(temp, text, { encoding: 'utf-8', flag: 'wx' })
    renameSync(temp, full)
  } catch (err) {
    rmSync(temp, { force: true })
    throw err
  }
}

async function recordChange(
  projectPath: string, scriptsDir: string, target: string, event: 'created' | 'revised', actor: string,
): Promise<string | null> {
  const args = [
    'record', '--artifact', target, '--event', event, '--actor', actor, '--reason', KEPT_REASON,
    '--state', stateFile(projectPath),
  ]
  const entry = await runPluginScript(scriptsDir, 'audit_artifacts.py', args)
  return entry.ok && entry.stdout.startsWith('Recorded') ? null : 'The change was not added to the document history.'
}

async function recordFindings(projectPath: string, scriptsDir: string, full: string): Promise<string | null> {
  const entry = await runPluginScript(scriptsDir, 'record_findings.py', ['record', '--report', full, '--state', stateFile(projectPath)])
  if (entry.ok) return null
  return entry.stdout.includes('INPUT_INCOMPLETE')
    ? 'The review was saved, but it has no Gate Results table, so no findings were recorded.'
    : 'The review was saved, but its findings could not be recorded.'
}

const joinWarnings = (warnings: Array<string | null>): string | undefined => {
  const present = warnings.filter((w): w is string => Boolean(w))
  return present.length > 0 ? present.join(' ') : undefined
}

/** Writes the candidate. Returns ok:false (nothing written) for a refused target or an unconfirmed
 * capture of the file being replaced; otherwise ok:true, with a warning for anything unrecorded. */
export async function keepCandidate(
  projectPath: string, scriptsDir: string, candidate: KeepSubject, actor: string, permit: TargetPermit = isKeepableTarget,
): Promise<KeepDraftResult> {
  const checked = checkTarget(projectPath, candidate.target, permit)
  if ('error' in checked) return { ok: false, error: checked.error }
  const { full } = checked

  const existed = existsSync(full)
  // A target that is a folder, or a file that cannot be read, cannot be captured: the same refusal.
  if (existed && !(await captureExisting(projectPath, scriptsDir, candidate.target, actor).catch(() => false))) {
    return { ok: false, error: `The existing ${candidate.target.split('/').pop()} could not be saved to its history first, so it was not replaced.` }
  }

  const text = documentText(candidate.text)
  try {
    writeWhole(full, text)
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : 'The document could not be written.' }
  }

  const changeWarning = await recordChange(projectPath, scriptsDir, candidate.target, existed ? 'revised' : 'created', actor)
  const findingsWarning = candidate.kind === 'review' ? await recordFindings(projectPath, scriptsDir, full) : null
  const outcome = await recordOutcome(projectPath, scriptsDir, candidate, 'accepted', actor, text.length)
  return {
    ok: true,
    written: candidate.target,
    ...(candidate.kind === 'review' ? { findingsRecorded: findingsWarning === null } : {}),
    warning: joinWarnings([changeWarning, findingsWarning, outcome]),
  }
}

async function recordOutcome(
  projectPath: string, scriptsDir: string, candidate: KeepSubject, outcome: DraftOutcome, actor: string, charsKept: number,
): Promise<string | null> {
  const result = await recordDraftOutcome(
    projectPath, scriptsDir, candidate.target, WHOLE_DOCUMENT, outcome, actor, candidate.text.length, charsKept,
  )
  return result.ok ? null : 'The draft outcome was not recorded.'
}

/** Writes nothing. Records that the draft was offered and not kept. */
export async function discardCandidate(
  projectPath: string, scriptsDir: string, candidate: KeepSubject, actor: string,
): Promise<{ ok: boolean; error?: string; warning?: string }> {
  const warning = await recordOutcome(projectPath, scriptsDir, candidate, 'discarded', actor, 0)
  return { ok: true, ...(warning ? { warning } : {}) }
}
