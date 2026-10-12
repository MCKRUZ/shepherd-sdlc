// Document history — versions, comparing them, and restoring one (spec 0010).
//
// All of it is the plugin's own audit_artifacts.py; nothing here keeps its own history.
// Three things about that script shape this file, all verified against it:
//
//  1. `version list --json` gives WHO saved each version but drops WHY — version_model's row
//     builder copies n/hash/event/ts/actor/present and leaves `reason` behind. The reason
//     lives in the change ledger, reachable via `report --history --json`. Both lists are in
//     the same ledger order, so they join by position — with one offset: a synthesized `v1`
//     baseline has no ledger row of its own.
//  2. It ALWAYS exits 0, including for refusals and "couldn't read that". Success has to be
//     read from stdout, never from the exit code.
//  3. Restoring is preview-then-confirm: the preview prints a diff and its hash, and the
//     confirm must echo that hash back. That is what proves a person saw the exact change
//     before it was applied, so this file never short-circuits it.

import { runPluginScript } from './project'
import { rawStdout } from './commandRunner'
import { UnsafePathError, resolveProjectDocument } from './projectPaths'
import type { DocumentVersion, RestorePreview } from '../../shared/types'

export interface RawVersion {
  n: number
  hash: string
  event: string
  ts: string
  actor: string
  present: boolean
  restored_from?: number
}

export interface RawChange {
  ts?: string
  actor?: string
  reason?: string
  event?: string
}

async function auditArtifacts(
  pluginScriptsDir: string,
  projectPath: string,
  args: string[],
): Promise<{ ok: boolean; stdout: string; stderr: string }> {
  const entry = await runPluginScript(pluginScriptsDir, 'audit_artifacts.py', [...args, '--repo', projectPath])
  // stdout is the plugin's own output about a document (version text, diffs, JSON that quotes it): data, so exact.
  return { ok: entry.ok, stdout: rawStdout(entry), stderr: entry.stderr }
}

/** The document path reaches the plugin as a POSITIONAL argument, so two things have to be
 * true before it is passed along: it must be one of the project's own editable documents
 * (the same check the document layer makes — history and editing must not disagree about
 * what is in bounds), and it must not begin with a dash, which the plugin's own argument
 * parser would read as a flag rather than a filename. */
function checkedRelPath(projectPath: string, relPath: string): string {
  if (relPath.startsWith('-')) {
    throw new UnsafePathError(`${relPath} is not a document name Shepherd will pass on.`)
  }
  resolveProjectDocument(projectPath, relPath)
  return relPath
}

/** The same check as a message instead of a throw, so a refusal reaches the person as an
 * explanation in the window rather than an exception crossing the process boundary. */
function refuseRelPath(projectPath: string, relPath: string): string | null {
  try {
    checkedRelPath(projectPath, relPath)
    return null
  } catch (err) {
    return (err as Error).message
  }
}

/** Join each version to its reason. Pure, and separated out because the offset rule is the
 * subtle part: both lists are in ledger order, but a SYNTHESIZED baseline version (an artifact
 * that existed before the ledger did) has no ledger row of its own, so everything after it is
 * shifted by one. Getting this wrong attributes every reason to the wrong version — which
 * looks plausible and is completely wrong, the worst kind of bug in a history view. */
export function joinVersionsWithReasons(versions: RawVersion[], changes: RawChange[]): DocumentVersion[] {
  const offset = versions[0]?.event === 'baseline' ? 1 : 0
  return versions.map((v, i) => {
    const change = i - offset >= 0 ? changes[i - offset] : undefined
    return {
      n: v.n,
      hash: v.hash,
      event: v.event,
      when: v.ts || '',
      actor: v.actor || '',
      reason: (change?.reason ?? '').trim(),
      present: v.present,
      ...(v.restored_from !== undefined ? { restoredFrom: v.restored_from } : {}),
    }
  })
}

export async function listVersions(
  projectPath: string,
  pluginScriptsDir: string,
  relPath: string,
): Promise<DocumentVersion[]> {
  if (refuseRelPath(projectPath, relPath)) return []
  const listed = await auditArtifacts(pluginScriptsDir, projectPath, ['version', 'list', checkedRelPath(projectPath, relPath), '--json'])
  let versions: RawVersion[] = []
  try {
    versions = (JSON.parse(listed.stdout).versions ?? []) as RawVersion[]
  } catch {
    return []
  }
  if (versions.length === 0) return []

  // The "why" for each version, joined by position (see this file's header).
  let changes: RawChange[] = []
  const history = await auditArtifacts(pluginScriptsDir, projectPath, ['report', '--history', checkedRelPath(projectPath, relPath), '--json'])
  try {
    changes = (JSON.parse(history.stdout).history ?? []) as RawChange[]
  } catch {
    changes = []
  }

  return joinVersionsWithReasons(versions, changes)
}

/** Refusals and "content not captured" both come back as ordinary stdout with exit 0, so
 * detect them by their documented prefix rather than by status. */
function refusal(stdout: string, verb: string): string | null {
  const line = stdout.split('\n').map((l) => l.trim()).find((l) => l.startsWith(`${verb} —`))
  return line ? line.slice(verb.length + 2).trim() : null
}

export async function getVersionText(
  projectPath: string,
  pluginScriptsDir: string,
  relPath: string,
  ref: string,
): Promise<{ ok: boolean; text?: string; error?: string }> {
  const refusedPath = refuseRelPath(projectPath, relPath)
  if (refusedPath) return { ok: false, error: refusedPath }
  const shown = await auditArtifacts(pluginScriptsDir, projectPath, ['version', 'show', checkedRelPath(projectPath, relPath), ref])
  const refused = refusal(shown.stdout, 'show')
  if (refused) return { ok: false, error: refused }
  return { ok: true, text: shown.stdout }
}

export async function diffVersions(
  projectPath: string,
  pluginScriptsDir: string,
  relPath: string,
  a: string,
  b: string,
): Promise<{ ok: boolean; diff?: string; error?: string }> {
  const refusedPath = refuseRelPath(projectPath, relPath)
  if (refusedPath) return { ok: false, error: refusedPath }
  const out = await auditArtifacts(pluginScriptsDir, projectPath, ['version', 'diff', checkedRelPath(projectPath, relPath), a, b])
  const refused = refusal(out.stdout, 'diff')
  if (refused) return { ok: false, error: refused }
  return { ok: true, diff: out.stdout }
}

const DIFF_HASH_RE = /--reviewed\s+(\S+)/
const SIGNOFF_HINT = 'ack-signoff'

export async function previewRestore(
  projectPath: string,
  pluginScriptsDir: string,
  relPath: string,
  ref: string,
): Promise<RestorePreview> {
  const refusedPath = refuseRelPath(projectPath, relPath)
  if (refusedPath) return { ok: false, diffHash: '', diff: '', needsSignOffAck: false, error: refusedPath }
  const out = await auditArtifacts(pluginScriptsDir, projectPath, ['version', 'rollback', checkedRelPath(projectPath, relPath), ref])
  const refused = refusal(out.stdout, 'rollback')
  if (refused) {
    return { ok: false, diffHash: '', diff: '', needsSignOffAck: false, error: refused }
  }

  const hash = out.stdout.match(DIFF_HASH_RE)?.[1]
  if (!hash) {
    return {
      ok: false, diffHash: '', diff: '', needsSignOffAck: false,
      error: 'Could not read the confirmation hash from the preview — not restoring.',
    }
  }

  // The preview prints the diff between two "-----" rules.
  const lines = out.stdout.split('\n')
  const rules = lines.map((l, i) => (l.trim().startsWith('---------') ? i : -1)).filter((i) => i >= 0)
  const diff = rules.length >= 2 ? lines.slice(rules[0] + 1, rules[1]).join('\n') : out.stdout

  return { ok: true, diffHash: hash, diff, needsSignOffAck: out.stdout.includes(SIGNOFF_HINT) }
}

export async function confirmRestore(
  projectPath: string,
  pluginScriptsDir: string,
  relPath: string,
  ref: string,
  actor: string,
  diffHash: string,
  ackSignOff: boolean,
): Promise<{ ok: boolean; error?: string }> {
  if (!actor.trim()) {
    return { ok: false, error: 'Restoring needs a named person — the change is recorded against them.' }
  }
  const refusedPath = refuseRelPath(projectPath, relPath)
  if (refusedPath) return { ok: false, error: refusedPath }
  const args = ['version', 'rollback', checkedRelPath(projectPath, relPath), ref, '--confirm', '--actor', actor, '--reviewed', diffHash]
  if (ackSignOff) args.push('--ack-signoff')

  const out = await auditArtifacts(pluginScriptsDir, projectPath, args)
  const refused = refusal(out.stdout, 'rollback')
  if (refused) return { ok: false, error: refused }
  if (!out.stdout.includes('Rolled back')) {
    return { ok: false, error: out.stdout.trim() || 'The restore did not report success.' }
  }
  return { ok: true }
}

/** Record a save as a version, with the real person and the real reason. Nothing creates a
 * version automatically — without this call the history stays empty and "who saved it and
 * why" is never populated. Called after a successful save, never on read. */
export async function recordVersion(
  projectPath: string,
  pluginScriptsDir: string,
  relPath: string,
  actor: string,
  reason: string,
): Promise<{ ok: boolean; error?: string }> {
  const refusedPath = refuseRelPath(projectPath, relPath)
  if (refusedPath) return { ok: false, error: refusedPath }
  const out = await auditArtifacts(pluginScriptsDir, projectPath, [
    'record', '--artifact', checkedRelPath(projectPath, relPath), '--actor', actor, '--reason', reason, '--event', 'revised',
  ])
  if (!out.stdout.includes('Recorded')) {
    return { ok: false, error: out.stdout.trim() || out.stderr.trim() || 'The version was not recorded.' }
  }
  return { ok: true }
}
