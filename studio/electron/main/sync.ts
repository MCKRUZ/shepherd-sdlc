// Repository sync (spec 0009) — the orchestration layer. Pull, save, and clash resolution,
// built on git.ts (the plugin's own proven git contract), sectionMerge.ts (the pure
// per-section 3-way merge), and settings.ts (Studio's local ancestor bookkeeping — see
// decision 4 in the spec's plan: no scratch clone, every git operation runs straight
// against the person's real project folder, because fetch and the plumbing commands used
// here never touch a working file, so there's nothing to isolate them from).
//
// Everything that talks to the CODE HOST — who is signed in, the pull-request fallback when
// a direct push is refused, the poll that merges Studio's own pull request — goes through the
// provider codeHost.ts resolves for the project (GitHub via gh, Azure DevOps via az; code-host
// providers, Wave 6). This file never names a CLI: it asks the provider, and when the provider
// cannot answer it says why in the §7.1 wording rather than failing on an ENOENT.

import { createHash } from 'node:crypto'
import { rawStdout } from './commandRunner'
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, relative, sep } from 'node:path'
import { hostFeatureReason } from '../../shared/codeHostModel'
import { CodeHostUnavailable, resolveCodeHost as defaultResolveCodeHost, type CodeHost, type Identity, type ResolveCodeHostDeps, type ResolvedCodeHost } from './codeHost'
import { runGit, runGitTolerant, hasOriginRemote } from './git'
import { recordVersion } from './history'
import { runPluginScript } from './project'
import { isAllowlisted, isSafeInProject, resolveInProject } from './projectPaths'
import {
  extractUnits, findShapeForPath, normalizeEol, readShapeFromBytes, reclassifyUnwritableMerges,
  threeWayMerge, writeShapeUpdates, type SectionUnit,
} from './sectionMerge'
import {
  getProjectSettings, getProjectSyncState, readAncestorBlob, saveProjectSyncState, storeAncestorBlob,
} from './settings'
import { forgetTypedActor, getTypedActor, rememberTypedActor, TYPED_NAME_SUFFIX, validateTypedActor } from './typedActor'
import type {
  ArrivedChange, ClashChoice, ClashSection, ConnectionInfo, FileClash, PullResult,
  ProjectSyncState, ResolveClashResult, RosterPerson, SaveResult, SyncState,
} from '../../shared/types'

// --- Allowlist ------------------------------------------------------------------------
// The list now lives in projectPaths.ts, because documents and history need the same one and
// having it here meant only this file ever applied it. Re-exported so existing callers and
// tests keep working.

export { isAllowlisted } from './projectPaths'

// --- sync-state broadcasting -------------------------------------------------------------

const syncListeners = new Set<(state: SyncState) => void>()

export function onSyncState(listener: (state: SyncState) => void): () => void {
  syncListeners.add(listener)
  return () => syncListeners.delete(listener)
}

function emitSyncState(state: SyncState): void {
  for (const l of syncListeners) l(state)
}

// --- small helpers -------------------------------------------------------------------------

// git's core.autocrlf (the common, often-default, Windows setting) converts CRLF<->LF
// between the working tree and the stored blob — meaning a checked-out local file and
// `git show <ref>:<path>`'s raw blob output can differ in bytes for content that is
// otherwise identical. Verified live against a real repo with autocrlf=true: a 2172-byte
// blob (LF) checks out as a 2265-byte working-tree file (CRLF) for the exact same commit.
// Comparing raw bytes directly would treat every such file as "changed" on every pull —
// hashing (and any decision about whether content actually differs) must normalize line
// endings first, or this spec is unusable on one of the most common Windows git configs.
function detectEol(text: string): '\r\n' | '\n' {
  return text.includes('\r\n') ? '\r\n' : '\n'
}

function toEol(text: string, eol: '\r\n' | '\n'): string {
  const normalized = normalizeEol(text)
  return eol === '\n' ? normalized : normalized.replace(/\n/g, '\r\n')
}

function hashBytes(buf: Buffer): string {
  return `sha256:${createHash('sha256').update(normalizeEol(buf.toString('utf-8')), 'utf-8').digest('hex').slice(0, 16)}`
}

function walkFiles(dir: string, projectPath: string, out: string[]): void {
  let entries
  try {
    entries = readdirSync(dir, { withFileTypes: true })
  } catch {
    return
  }
  for (const e of entries) {
    const full = join(dir, e.name)
    // A link is never a document Studio should sync — following one would read whatever it
    // points at (a private key, say) and push it to the repository's owner. Dropped here,
    // and again at the point of use, since this walk is not the only way a path arrives.
    if (e.isSymbolicLink()) continue
    if (e.isDirectory()) walkFiles(full, projectPath, out)
    else if (e.isFile()) {
      const rel = relative(projectPath, full).split(sep).join('/')
      if (isAllowlisted(rel)) out.push(rel)
    }
  }
}

function listLocalAllowlistedFiles(projectPath: string): string[] {
  const out: string[] = []
  walkFiles(join(projectPath, '.sdlc'), projectPath, out)
  walkFiles(join(projectPath, 'specs'), projectPath, out)
  return out
}

async function listRemoteAllowlistedFiles(projectPath: string, branch: string): Promise<string[]> {
  const entry = await runGitTolerant(['ls-tree', '-r', '--name-only', `origin/${branch}`], projectPath)
  if (!entry.ok) return []
  // The remote list is the repository's own view, so it is the untrusted one — it happily
  // names a path that exists locally as a link to somewhere else entirely.
  return entry.stdout.split('\n').map((l) => l.trim()).filter(Boolean)
    .filter(isAllowlisted)
    .filter((rel) => isSafeInProject(projectPath, rel))
}

async function currentBranch(projectPath: string): Promise<string> {
  return (await runGit(['branch', '--show-current'], projectPath)).trim()
}

const hasOrigin = hasOriginRemote

const NOT_CONNECTED =
  'This project is not connected to a shared repository yet, so there is nowhere to save changes for your team. '
  + 'Your work is kept on this computer.'

/** Does the shared branch hold this file, byte for byte as it is here?
 *
 * The question a caller actually wants after saving something is "can somebody else read
 * this?", and that is not the same as "did a commit happen". A save can honestly report
 * nothing to commit because the remote already holds identical content — success — or because
 * it saw no change at all. Asking the remote answers the property rather than the mechanism.
 */
export async function isOnRemote(projectPath: string, relPath: string): Promise<boolean> {
  try {
    const branch = await currentBranch(projectPath)
    const remoteBytes = await readRemoteBlob(projectPath, branch, relPath)
    if (!remoteBytes) return false
    const localFullPath = resolveInProject(projectPath, relPath)
    if (!existsSync(localFullPath)) return false
    return hashBytes(remoteBytes) === hashBytes(readFileSync(localFullPath))
  } catch {
    return false
  }
}

async function readRemoteBlob(projectPath: string, branch: string, relPath: string): Promise<Buffer | null> {
  const entry = await runGitTolerant(['show', `origin/${branch}:${relPath}`], projectPath)
  if (!entry.ok) return null
  return Buffer.from(rawStdout(entry), 'utf-8')
}

async function describeArrival(projectPath: string, branch: string, relPath: string): Promise<ArrivedChange> {
  const entry = await runGitTolerant(
    ['log', '-1', '--format=%an|%ad', `origin/${branch}`, '--', relPath], projectPath,
  )
  if (!entry.ok) return { path: relPath, author: 'unknown', when: '' }
  const [author, when] = entry.stdout.trim().split('|')
  return { path: relPath, author: author || 'unknown', when: when || '' }
}

/** Applies every resolved unit (silent merges plus, in resolveClash, the person's just-made
 * choices) to the local file in one write. A unit with a real span replaces it in place, same
 * as always. A unit with none — the exact case reclassifyUnwritableMerges moved out of the
 * silent path — has nowhere to splice a replacement, so its resolved text is appended instead:
 * the document's own heading-based reading finds it on the next read regardless of position,
 * and appending, unlike skipping, can never make chosen content vanish. Returns whether
 * anything was actually written. */
async function applyResolvedUnits(
  pluginScriptsDir: string,
  localFullPath: string,
  localText: string,
  localEol: '\r\n' | '\n',
  merged: Map<string, string>,
  compareAgainst: (key: string) => string | undefined,
  localUnitsRaw: SectionUnit[],
): Promise<boolean> {
  const updates: Array<[number, number, string]> = []
  let appended = ''
  for (const [key, newText] of merged) {
    if (compareAgainst(key) === newText) continue // unchanged relative to local
    const rawUnit = localUnitsRaw.find((u) => u.key === key)
    if (rawUnit?.span) {
      const out = toEol(newText, localEol)
      if (rawUnit.text !== out) updates.push([rawUnit.span[0], rawUnit.span[1], out])
    } else {
      appended += `\n${toEol(newText, localEol).replace(/\n+$/, '')}\n`
    }
  }
  if (updates.length > 0) await writeShapeUpdates(pluginScriptsDir, localFullPath, updates)
  if (appended) {
    const base = updates.length > 0 ? readFileSync(localFullPath, 'utf-8') : localText
    writeFileSync(localFullPath, base.replace(/\n*$/, '\n') + appended, 'utf-8')
  }
  return updates.length > 0 || appended.length > 0
}

const WHOLE_FILE_KEY = '__whole_file__'

function wholeFileClash(relPath: string, localText: string, remoteText: string): FileClash {
  return {
    path: relPath,
    sections: [{ key: WHOLE_FILE_KEY, heading: relPath, localText, remoteText }],
  }
}

/** Reports a whole-file clash AND remembers it. Reporting alone is what went wrong: the pill
 * counted a clash, but the clash screen reads what was saved, found nothing, and never opened,
 * and save() refuses while a clash is reported, so the file could not be saved at all. A clash
 * Studio raises is one it must be able to resolve, so every path that raises one goes through
 * here. `ancestorHash` is undefined when Studio has never seen the two sides agree. */
function freezeWholeFileClash(
  syncState: ProjectSyncState, relPath: string, ancestorHash: string | undefined,
  localText: string, remoteText: string,
): FileClash {
  syncState.files[relPath] = { ...(ancestorHash ? { ancestorHash } : {}), pendingClashSections: [WHOLE_FILE_KEY] }
  return wholeFileClash(relPath, localText, remoteText)
}

/** How many clashing sections are waiting across the project, counting files already frozen by an
 * earlier pull: the number the indicator shows, so it says what is actually pending. */
function pendingSectionCount(syncState: ProjectSyncState): number {
  return Object.values(syncState.files).reduce((n, f) => n + (f.pendingClashSections?.length ?? 0), 0)
}

// --- the code host, and who is acting ----------------------------------------------------

/** The two things this file needs from outside to answer "who is acting": the project's code
 * host and the roster. Both default to the real ones; a test swaps them for fakes through
 * setCodeHostSeam so nothing here ever needs a live gh or az to be proven. */
export interface CodeHostSeam {
  resolve: (projectPath: string, deps?: ResolveCodeHostDeps) => Promise<ResolvedCodeHost>
  readRoster: (projectPath: string, pluginScriptsDir: string) => Promise<RosterPerson[]>
}

async function defaultReadRoster(projectPath: string, pluginScriptsDir: string): Promise<RosterPerson[]> {
  const settings = await getProjectSettings(projectPath, pluginScriptsDir)
  return settings.roster.people ?? []
}

let seam: CodeHostSeam = { resolve: defaultResolveCodeHost, readRoster: defaultReadRoster }

/** Tests only. Returns the restore function. */
export function setCodeHostSeam(over: Partial<CodeHostSeam>): () => void {
  const before = seam
  seam = { ...seam, ...over }
  return () => { seam = before }
}

/** What tooling detection found, so resolving a host does not re-probe `--version` on every
 * call. Set from index.ts after each detection; undefined until then (the resolver probes). */
let cliFound: ResolveCodeHostDeps['found']

export function noteCliDetection(found: { gh: boolean; az: boolean }): void {
  cliFound = found
}

function resolveHost(projectPath: string): Promise<ResolvedCodeHost> {
  return seam.resolve(projectPath, { found: cliFound })
}

/** The signed-in identity, or null when the host cannot say — which is the ONLY case a typed
 * name may stand in (D-OWNER-5). A sign-in state the resolver already established as 'no' is
 * not probed again; anything else is asked (the provider memoises per poll interval). */
async function identify(resolved: ResolvedCodeHost): Promise<Identity | null> {
  if (!resolved.cli.found || resolved.cli.signedIn === 'no') return null
  try {
    return await resolved.provider.whoAmI()
  } catch {
    return null
  }
}

const bareHandle = (handle: string): string => handle.trim().replace(/^@/, '')

/** The roster handle a host identity resolves to, or null. The rule is the plugin's
 * (validate_team.py `people_by_email`): an Azure DevOps UPN matches a person's `email:`,
 * lower-cased, and nothing else — never a display name, never the UPN's local part. A GitHub
 * login IS the handle, so it matches `handle:` directly (case-insensitively, as GitHub does). */
export function rosterHandleFor(identity: Identity, people: RosterPerson[]): string | null {
  const login = identity.login.trim().toLowerCase()
  if (!login) return null
  const hit = identity.kind === 'upn'
    ? people.find((p) => typeof p.email === 'string' && p.email.trim().toLowerCase() === login)
    : people.find((p) => typeof p.handle === 'string' && bareHandle(p.handle).toLowerCase() === login)
  return hit?.handle ?? null
}

/** The email the roster records for a handle, or null — an honest answer, not a failure: the
 * caller that needs one (an Azure DevOps reviewer) says so rather than guessing. Handles are
 * matched exactly apart from the leading `@`, as the roster's own rule is. */
export function rosterEmailFor(handle: string, people: RosterPerson[]): string | null {
  const want = bareHandle(handle)
  const hit = people.find((p) => typeof p.handle === 'string' && bareHandle(p.handle) === want)
  const email = hit?.email?.trim()
  return email ? email : null
}

/** Who is acting, in order of trust: the roster's handle for the signed-in identity, the
 * identity itself, a name typed for this session — and the last only while the host cannot
 * identify the person. Once it can, a typed name is forgotten rather than left to shadow it.
 * `account` is the handle without its `@`, the form every actor comparison already uses. */
export function actorFor(
  projectPath: string, identity: Identity | null, people: RosterPerson[],
): Pick<ConnectionInfo, 'account' | 'accountSource' | 'rosterHandle'> {
  if (identity) {
    forgetTypedActor(projectPath)
    const handle = rosterHandleFor(identity, people)
    return handle
      ? { account: bareHandle(handle), accountSource: 'roster', rosterHandle: handle }
      : { account: identity.login, accountSource: 'host', rosterHandle: null }
  }
  const typed = getTypedActor(projectPath)
  return typed
    ? { account: typed, accountSource: 'typed', rosterHandle: null }
    : { account: null, accountSource: null, rosterHandle: null }
}

// --- connection info -----------------------------------------------------------------------

export async function getConnectionInfo(projectPath: string, pluginScriptsDir: string | null = null): Promise<ConnectionInfo> {
  const branch = await currentBranch(projectPath).catch(() => '')

  let repo = ''
  const connected = await hasOrigin(projectPath).catch(() => false)
  if (connected) {
    try {
      repo = (await runGit(['remote', 'get-url', 'origin'], projectPath)).trim()
    } catch {
      // listed but unreadable: treated as not configured
    }
  }

  const resolved = await resolveHost(projectPath)
  const identity = await identify(resolved)
  // Without the plugin there is no roster to read; the identity is then reported as the host
  // gave it, which is still true — just not in the roster's form.
  const people = identity && pluginScriptsDir ? await seam.readRoster(projectPath, pluginScriptsDir).catch(() => []) : []
  const actor = actorFor(projectPath, identity, people)

  // Best-effort display only — never the actual gate. The real gate is whether a direct
  // push gets rejected (finding 9); this is purely for the connection screen to show
  // something before the person ever saves. Null is "couldn't read", not "no".
  let branchProtected: boolean | null = null
  // With no shared repository no host is detected, and the provider is then the null one, which asks nothing.
  try {
    branchProtected = await resolved.provider.isBranchProtected(branch)
  } catch {
    branchProtected = null
  }

  const state = getProjectSyncState(projectPath)
  return {
    repo, branch, localFolder: projectPath, ...actor,
    host: resolved.host, hostSource: resolved.source, cli: resolved.cli,
    lastPulledAt: state.lastPulledAt, branchProtected,
  }
}

/** D-OWNER-5: accept a typed name for this project, for this process, ONLY while the host
 * cannot say who the person is. Refused (a rejected promise, with the reason) when the name
 * fails validation or when the host already identifies them — a typed name must never be a
 * way around a sign-in that works. Resolves to the refreshed connection info. */
export async function setTypedActor(projectPath: string, pluginScriptsDir: string | null, name: unknown): Promise<ConnectionInfo> {
  const check = validateTypedActor(name)
  if (!check.ok) throw new Error(check.error)
  const resolved = await resolveHost(projectPath)
  const identity = await identify(resolved)
  if (identity) {
    const hostName = resolved.host === 'azure-devops' ? 'Azure DevOps' : 'GitHub'
    throw new Error(`${hostName} already identifies you as ${identity.login}; a typed name is only for when it cannot.`)
  }
  rememberTypedActor(projectPath, check.name)
  return getConnectionInfo(projectPath, pluginScriptsDir)
}

// --- pull ------------------------------------------------------------------------------

interface PullOneFileOutcome {
  merged: boolean
  clash?: FileClash
  arrived?: ArrivedChange
}

async function pullOneFile(
  projectPath: string,
  pluginScriptsDir: string,
  branch: string,
  relPath: string,
  syncState: ProjectSyncState,
): Promise<PullOneFileOutcome> {
  // The last line of defence before any read or write: refuses a path that climbs out of the
  // project, is a link, or resolves outside it. A refusal skips the file rather than failing
  // the pull — one hostile entry must not stop the other documents syncing.
  let localFullPath: string
  try {
    localFullPath = resolveInProject(projectPath, relPath)
  } catch {
    return { merged: false }
  }
  const localExists = existsSync(localFullPath)
  const localBytes = localExists ? readFileSync(localFullPath) : null
  const remoteBytes = await readRemoteBlob(projectPath, branch, relPath)

  if (!localBytes && !remoteBytes) return { merged: false }

  const existing = syncState.files[relPath]
  if (existing?.pendingClashSections?.length) {
    return { merged: false } // frozen — waits for resolveClash()
  }

  const localHash = localBytes ? hashBytes(localBytes) : null
  const remoteHash = remoteBytes ? hashBytes(remoteBytes) : null

  if (!existing?.ancestorHash) {
    // True first sync for this file.
    //
    // A file that exists HERE and not on the remote is new work, and gets no ancestor. It used
    // to be baselined against its own current contents, which quietly made it unsaveable: save()
    // pulls before working out what changed, so the new document was recorded as "already in
    // step" moments before the save looked, and the save answered "nothing to save" while
    // reporting success. Nothing Studio created could ever reach the repository — found by
    // producing a hand-over document and then failing to find it in a fresh clone.
    //
    // Leaving the ancestor unset is also the honest description: there is no shared history
    // with the remote yet, because the remote has never seen this file.
    if (localBytes && !remoteBytes) {
      return { merged: false }
    }
    if (localBytes && localHash === remoteHash) {
      storeAncestorBlob(localHash!, localBytes)
      syncState.files[relPath] = { ancestorHash: localHash! }
      return { merged: false }
    }
    if (!localBytes && remoteBytes) {
      writeFileSync(localFullPath, remoteBytes)
      storeAncestorBlob(remoteHash!, remoteBytes)
      syncState.files[relPath] = { ancestorHash: remoteHash! }
      return { merged: true, arrived: await describeArrival(projectPath, branch, relPath) }
    }
    // Both exist and already differ with no known shared history (e.g. a clone with local
    // edits made before Studio's first pull) — never guess which is right.
    return { merged: false, clash: freezeWholeFileClash(syncState, relPath, undefined, localBytes!.toString('utf-8'), remoteBytes!.toString('utf-8')) }
  }

  const ancestorHash = existing.ancestorHash
  if (remoteHash === ancestorHash) return { merged: false } // remote hasn't moved (EOL-insensitive)

  if (localHash === ancestorHash || localBytes === null) {
    // Only remote changed (or the local file is simply gone — treated as no local edit).
    // Written in the local checkout's own EOL style (when a local copy existed) so this
    // doesn't turn into a whole-file EOL-style diff the next time something looks at it.
    if (remoteBytes) {
      const remoteText = remoteBytes.toString('utf-8')
      const out = localBytes ? toEol(remoteText, detectEol(localBytes.toString('utf-8'))) : remoteText
      writeFileSync(localFullPath, out, 'utf-8')
      storeAncestorBlob(remoteHash!, remoteBytes)
      syncState.files[relPath] = { ancestorHash: remoteHash! }
      return { merged: true, arrived: await describeArrival(projectPath, branch, relPath) }
    }
    return { merged: false } // remote deleted it too; deletion propagation is out of scope
  }

  if (localHash === remoteHash) {
    storeAncestorBlob(remoteHash!, remoteBytes!)
    syncState.files[relPath] = { ancestorHash: remoteHash! }
    return { merged: false }
  }

  // Both changed and differ (by content, not just EOL style) — the real case this spec
  // exists for.
  const ancestorBytes = readAncestorBlob(ancestorHash)
  const localText = localBytes.toString('utf-8')
  const remoteText = remoteBytes!.toString('utf-8')

  if (!ancestorBytes) {
    // Can't do a precise compare without the ancestor's bytes — fail safe, not silent.
    return { merged: false, clash: freezeWholeFileClash(syncState, relPath, ancestorHash, localText, remoteText) }
  }

  const shapePath = findShapeForPath(pluginScriptsDir, relPath, localText)
  if (!shapePath) {
    return { merged: false, clash: freezeWholeFileClash(syncState, relPath, ancestorHash, localText, remoteText) }
  }

  // Two passes: a normalized (LF) pass decides WHAT changed — so a checkout's EOL
  // conversion can never manufacture a false clash — and a raw pass against the REAL local
  // file gives the byte spans the eventual write must target. Mixing these up would either
  // hide a real change (comparing on raw, EOL-differing text) or write at the wrong offsets
  // (splicing normalized spans into the real, differently-sized file).
  const localEol = detectEol(localText)
  const ancestorNorm = normalizeEol(ancestorBytes.toString('utf-8'))
  const localNorm = normalizeEol(localText)
  const remoteNorm = normalizeEol(remoteText)

  const [ancestorReadN, localReadN, remoteReadN, localReadRaw] = await Promise.all([
    readShapeFromBytes(pluginScriptsDir, Buffer.from(ancestorNorm, 'utf-8'), shapePath),
    readShapeFromBytes(pluginScriptsDir, Buffer.from(localNorm, 'utf-8'), shapePath),
    readShapeFromBytes(pluginScriptsDir, Buffer.from(remoteNorm, 'utf-8'), shapePath),
    readShapeFromBytes(pluginScriptsDir, localBytes, shapePath),
  ])

  if (!ancestorReadN.matched || !localReadN.matched || !remoteReadN.matched || !localReadRaw.matched) {
    return { merged: false, clash: freezeWholeFileClash(syncState, relPath, ancestorHash, localText, remoteText) }
  }

  const ancestorUnits = extractUnits(ancestorNorm, ancestorReadN)
  const localUnitsForCompare = extractUnits(localNorm, localReadN)
  const remoteUnits = extractUnits(remoteNorm, remoteReadN)
  const localUnitsRaw = extractUnits(localText, localReadRaw) // real spans, for writing only
  const { merged, clashes } = threeWayMerge(ancestorUnits, localUnitsForCompare, remoteUnits)
  reclassifyUnwritableMerges(
    merged, clashes, localUnitsRaw, (key) => localUnitsForCompare.find((u) => u.key === key)?.text,
    ancestorUnits, remoteUnits,
  )

  if (clashes.length > 0) {
    syncState.files[relPath] = { ancestorHash, pendingClashSections: clashes.map((c) => c.key) }
    return { merged: false, clash: { path: relPath, sections: clashes } }
  }

  const wrote = await applyResolvedUnits(
    pluginScriptsDir, localFullPath, localText, localEol, merged,
    (key) => localUnitsForCompare.find((u) => u.key === key)?.text,
    localUnitsRaw,
  )

  storeAncestorBlob(remoteHash!, remoteBytes!)
  syncState.files[relPath] = { ancestorHash: remoteHash! }
  return { merged: wrote, arrived: await describeArrival(projectPath, branch, relPath) }
}

export async function pull(projectPath: string, pluginScriptsDir: string): Promise<PullResult> {
  // Nothing to pull from is a state, not a failure: say so and stop, rather than let `git fetch
  // origin` fail on every cycle and turn the sidebar red for a project that is working as intended.
  if (!(await hasOrigin(projectPath).catch(() => false))) {
    emitSyncState({ kind: 'localOnly' })
    return { ok: true, mergedFiles: [], clashes: [], arrivedChanges: [], entries: [], noRemote: true }
  }
  emitSyncState({ kind: 'pulling' })
  try {
    await runGit(['fetch', 'origin'], projectPath)
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    emitSyncState({ kind: 'error', message })
    return { ok: false, mergedFiles: [], clashes: [], arrivedChanges: [], entries: [], error: message }
  }

  const branch = await currentBranch(projectPath)
  const syncState = getProjectSyncState(projectPath)
  const remoteFiles = await listRemoteAllowlistedFiles(projectPath, branch)
  const allFiles = new Set([...listLocalAllowlistedFiles(projectPath), ...remoteFiles, ...Object.keys(syncState.files)])

  const mergedFiles: string[] = []
  const clashes: FileClash[] = []
  const arrivedChanges: ArrivedChange[] = []

  for (const relPath of allFiles) {
    const outcome = await pullOneFile(projectPath, pluginScriptsDir, branch, relPath, syncState)
    if (outcome.merged) mergedFiles.push(relPath)
    if (outcome.clash) clashes.push(outcome.clash)
    if (outcome.arrived) arrivedChanges.push(outcome.arrived)
  }

  syncState.lastPulledAt = new Date().toISOString()
  saveProjectSyncState(projectPath, syncState)

  // Counts everything waiting, including files frozen by an earlier pull. Counting only what THIS
  // pull newly found made a clash that was still waiting read as "synced" on the next pull.
  const waiting = pendingSectionCount(syncState)
  if (waiting > 0) {
    emitSyncState({ kind: 'clashes', count: waiting })
  } else {
    emitSyncState({ kind: 'idle', lastPulledAt: syncState.lastPulledAt })
  }

  return { ok: true, mergedFiles, clashes, arrivedChanges, entries: [] }
}

// --- clash resolution ------------------------------------------------------------------

interface RecomputedClashState {
  merged: Map<string, string>
  clashes: ClashSection[]
  /** Real spans against the actual local file on disk — used only for writing. See
   * pullOneFile's two-pass comment for why this must be separate from the units the
   * comparison itself ran on. */
  localUnitsRaw: ReturnType<typeof extractUnits>
  localEol: '\r\n' | '\n'
  localText: string
  remoteBytes: Buffer
  shapePath: string | null
}

/** Recomputes a file's clash state fresh from durable sources (the local file on disk, a
 * fresh fetch of the remote, and the frozen ancestor blob) rather than trusting any
 * in-memory cache — so resolving a clash works correctly even after Studio was closed and
 * reopened mid-resolution, per spec 0009's own acceptance check. Shared by resolveClash()
 * and getPendingClashes() so there is exactly one place this logic lives. Same EOL-safe
 * two-pass approach as pullOneFile — see its comment for why one pass isn't enough. */
async function recomputeClashState(
  projectPath: string,
  pluginScriptsDir: string,
  filePath: string,
  ancestorHash: string | undefined,
  wholeFile: boolean,
): Promise<RecomputedClashState | { error: string }> {
  const branch = await currentBranch(projectPath)
  const localFullPath = join(projectPath, filePath)
  if (!existsSync(localFullPath)) {
    return { error: `${filePath} no longer exists locally` }
  }
  const localBytes = readFileSync(localFullPath)
  const remoteBytes = await readRemoteBlob(projectPath, branch, filePath)
  const ancestorBytes = ancestorHash ? readAncestorBlob(ancestorHash) : null

  // A whole-file clash is settled by choosing one of two complete texts, so it needs no shared
  // starting version; a section-by-section one cannot be told apart from an edit without it.
  if (!remoteBytes || (!ancestorBytes && !wholeFile)) {
    return { error: 'Could not recover the versions needed to resolve this clash — try pulling again' }
  }

  const localText = localBytes.toString('utf-8')
  const remoteText = remoteBytes.toString('utf-8')
  const localEol = detectEol(localText)
  const shapePath = wholeFile ? null : findShapeForPath(pluginScriptsDir, filePath, localText)

  if (!shapePath || !ancestorBytes) {
    return {
      merged: new Map(), shapePath: null, localText, remoteBytes, localEol,
      localUnitsRaw: [{ key: '__whole_file__', heading: filePath, text: localText }],
      clashes: [{ key: '__whole_file__', heading: filePath, localText, remoteText }],
    }
  }

  const ancestorNorm = normalizeEol(ancestorBytes.toString('utf-8'))
  const localNorm = normalizeEol(localText)
  const remoteNorm = normalizeEol(remoteText)

  const [ancestorReadN, localReadN, remoteReadN, localReadRaw] = await Promise.all([
    readShapeFromBytes(pluginScriptsDir, Buffer.from(ancestorNorm, 'utf-8'), shapePath),
    readShapeFromBytes(pluginScriptsDir, Buffer.from(localNorm, 'utf-8'), shapePath),
    readShapeFromBytes(pluginScriptsDir, Buffer.from(remoteNorm, 'utf-8'), shapePath),
    readShapeFromBytes(pluginScriptsDir, localBytes, shapePath),
  ])
  if (!ancestorReadN.matched || !localReadN.matched || !remoteReadN.matched || !localReadRaw.matched) {
    return {
      merged: new Map(), shapePath, localText, remoteBytes, localEol,
      localUnitsRaw: [{ key: '__whole_file__', heading: filePath, text: localText }],
      clashes: [{ key: '__whole_file__', heading: filePath, localText, remoteText }],
    }
  }

  const ancestorUnits = extractUnits(ancestorNorm, ancestorReadN)
  const localUnitsForCompare = extractUnits(localNorm, localReadN)
  const remoteUnits = extractUnits(remoteNorm, remoteReadN)
  const localUnitsRaw = extractUnits(localText, localReadRaw)
  const result = threeWayMerge(ancestorUnits, localUnitsForCompare, remoteUnits)
  reclassifyUnwritableMerges(
    result.merged, result.clashes, localUnitsRaw,
    (key) => localUnitsForCompare.find((u) => u.key === key)?.text, ancestorUnits, remoteUnits,
  )
  return { merged: result.merged, clashes: result.clashes, localUnitsRaw, localEol, localText, remoteBytes, shapePath }
}

/** When each side of a clash was last changed, so a person can tell which is newer and who made the
 * other. Best effort: a missing piece is left out rather than guessed. */
async function clashMetadata(projectPath: string, filePath: string): Promise<Pick<FileClash, 'localModifiedAt' | 'remote'>> {
  const out: Pick<FileClash, 'localModifiedAt' | 'remote'> = {}
  try {
    out.localModifiedAt = statSync(join(projectPath, filePath)).mtime.toISOString()
  } catch { /* the file may have gone since the clash was found */ }
  const branch = await currentBranch(projectPath)
  const entry = await runGitTolerant(
    ['log', '-1', '--format=%an%x00%aI%x00%s', `origin/${branch}`, '--', filePath], projectPath,
  )
  if (entry.ok) {
    // The commit's own subject line, shown as written; it is repository content, not a credential.
    const [author, when, subject] = rawStdout(entry).trim().split('\0')
    if (when) out.remote = { author: author || 'unknown', when, subject: subject ?? '' }
  }
  return out
}

/** Every currently-pending clash across the whole project, recomputed fresh — what the
 * renderer calls to populate the clash screen after any pull (including one that happened
 * on the periodic background timer, whose result the renderer never otherwise sees). */
export async function getPendingClashes(projectPath: string, pluginScriptsDir: string): Promise<FileClash[]> {
  const syncState = getProjectSyncState(projectPath)
  const out: FileClash[] = []
  for (const [filePath, fileState] of Object.entries(syncState.files)) {
    if (!fileState.pendingClashSections?.length) continue
    const wholeFile = fileState.pendingClashSections.includes(WHOLE_FILE_KEY)
    const state = await recomputeClashState(projectPath, pluginScriptsDir, filePath, fileState.ancestorHash, wholeFile)
    if ('error' in state) continue
    // Nothing left to decide: the two sides now hold the same text (someone took a version by
    // hand, or the same change arrived both ways). Leaving it pending would keep the indicator
    // amber over a clash with no question in it.
    if (wholeFile && normalizeEol(state.localText) === normalizeEol(state.remoteBytes.toString('utf-8'))) {
      const remoteHash = hashBytes(state.remoteBytes)
      storeAncestorBlob(remoteHash, state.remoteBytes)
      syncState.files[filePath] = { ancestorHash: remoteHash }
      saveProjectSyncState(projectPath, syncState)
      continue
    }
    const stillPending = state.clashes.filter((c) => fileState.pendingClashSections!.includes(c.key))
    if (stillPending.length > 0) out.push({ path: filePath, sections: stillPending, ...(await clashMetadata(projectPath, filePath)) })
  }
  return out
}

export async function resolveClash(
  projectPath: string,
  pluginScriptsDir: string,
  filePath: string,
  sectionKey: string,
  choice: ClashChoice,
  combinedText: string | undefined,
): Promise<ResolveClashResult> {
  const syncState = getProjectSyncState(projectPath)
  const fileState = syncState.files[filePath]
  if (!fileState?.pendingClashSections?.length) {
    return { ok: false, fileFullyResolved: false, error: `No pending clash for ${filePath}` }
  }

  const wholeFile = fileState.pendingClashSections.includes(WHOLE_FILE_KEY)
  const state = await recomputeClashState(projectPath, pluginScriptsDir, filePath, fileState.ancestorHash, wholeFile)
  if ('error' in state) {
    return { ok: false, fileFullyResolved: false, error: state.error }
  }
  const { merged, clashes, localUnitsRaw, localEol, localText, remoteBytes, shapePath } = state
  const localFullPath = join(projectPath, filePath)

  const clash = clashes.find((c) => c.key === sectionKey)
  if (!clash) {
    return { ok: false, fileFullyResolved: false, error: `Section '${sectionKey}' is not a pending clash for ${filePath}` }
  }
  const resolvedText = choice === 'local' ? clash.localText : choice === 'remote' ? clash.remoteText : (combinedText ?? clash.localText)
  merged.set(sectionKey, resolvedText)

  const remainingClashKeys = fileState.pendingClashSections.filter((k) => k !== sectionKey)
  if (remainingClashKeys.length > 0) {
    syncState.files[filePath] = { ...(fileState.ancestorHash ? { ancestorHash: fileState.ancestorHash } : {}), pendingClashSections: remainingClashKeys }
    saveProjectSyncState(projectPath, syncState)
    return { ok: true, fileFullyResolved: false }
  }

  // Every clash in this file is now resolved — apply everything (silent merges + resolved
  // clashes) in one write, then advance the ancestor.
  const wholeFileText = merged.get(WHOLE_FILE_KEY)
  if (wholeFileText !== undefined) {
    merged.delete(WHOLE_FILE_KEY) // a whole-file clash never carries any other key alongside it
    const out = toEol(wholeFileText, localEol)
    if (out !== localText) writeFileSync(localFullPath, out, 'utf-8')
  }
  if (merged.size > 0 && shapePath) {
    await applyResolvedUnits(
      pluginScriptsDir, localFullPath, localText, localEol, merged,
      (key) => localUnitsRaw.find((u) => u.key === key)?.text,
      localUnitsRaw,
    )
  }

  const remoteHash = hashBytes(remoteBytes)
  storeAncestorBlob(remoteHash, remoteBytes)
  syncState.files[filePath] = { ancestorHash: remoteHash }
  saveProjectSyncState(projectPath, syncState)

  return { ok: true, fileFullyResolved: true }
}

// --- approval settings (spec 0009's shared prerequisite) -------------------------------

interface ApprovalStageSetting {
  approval_required: boolean
  approver: string | null
}

/** The stage a changed path belongs to, derived from its artifact folder's own slug
 * (`.sdlc/artifacts/01-requirements/...` -> `requirements`) — never hardcoded against
 * phase_model.py's own ordering, which the plugin owns. A path with no artifact-folder
 * segment (specs/**, .sdlc/state.yaml, ...) has no stage, so it never gates on approval. */
function stageForPath(relPath: string): string | null {
  const m = relPath.match(/^\.sdlc\/artifacts\/\d+-([a-z0-9-]+)\//)
  return m ? m[1] : null
}

/** `known: false` means the settings could not be read at all — which is NOT the same as
 * "no approval required", though the two used to be conflated. Whether that distinction
 * matters depends on the caller: opening a pull request without a reviewer is recoverable,
 * because a person still merges it; merging automatically without one is not. So the answer
 * carries the uncertainty and each caller decides, rather than one silent default deciding
 * for both. */
async function approvalSettingsForFiles(
  pluginScriptsDir: string,
  projectPath: string,
  changedFiles: string[],
): Promise<{ required: boolean; approver: string | null; known: boolean }> {
  const entry = await runPluginScript(pluginScriptsDir, 'approval_settings.py', [projectPath, '--json'])
  let byStage: Record<string, ApprovalStageSetting> = {}
  let known = true
  try {
    byStage = (JSON.parse(rawStdout(entry)).settings ?? {}) as Record<string, ApprovalStageSetting>
  } catch {
    byStage = {}
    known = false
  }

  for (const relPath of changedFiles) {
    const stage = stageForPath(relPath)
    const setting = stage ? byStage[stage] : undefined
    if (setting?.approval_required) {
      return { required: true, approver: setting.approver, known }
    }
  }
  return { required: false, approver: null, known }
}

/** Who the pull request asks for review. GitHub takes the approver's login (the provider
 * tolerates a leading `@`); Azure DevOps takes an EMAIL, which only the roster can supply — a
 * handle with no `email:` in .sdlc/team.yaml opens the pull request without a reviewer and
 * says so in `note`, rather than guessing an address or failing the save. */
async function reviewerFor(
  resolved: ResolvedCodeHost,
  approval: { required: boolean; approver: string | null },
  projectPath: string,
  pluginScriptsDir: string,
): Promise<{ reviewer: string | null; note?: string }> {
  if (!approval.required || !approval.approver) return { reviewer: null }
  if (resolved.host !== 'azure-devops') return { reviewer: approval.approver.replace(/^@/, '') }
  const people = await seam.readRoster(projectPath, pluginScriptsDir).catch(() => [] as RosterPerson[])
  const email = rosterEmailFor(approval.approver, people)
  if (email) return { reviewer: email }
  return {
    reviewer: null,
    note: `${approval.approver} has no email: in .sdlc/team.yaml, which is what Azure DevOps needs to request a review — the pull request was opened without a reviewer.`,
  }
}

// --- save --------------------------------------------------------------------------------

export interface SaveOptions {
  /** Save only this document, leaving other changed files for their own save. Spec 0010 saves
   * one document at a time with its own reason; spec 0009's whole-project save is what you get
   * when this is omitted. */
  onlyPath?: string
  /** Who is saving, and why — recorded as a version so the document's history can answer "who
   * saved this and why" later. Without these the save still happens, but no version is
   * recorded, because a version attributed to nobody is worse than no version. */
  actor?: string
}

/** Whether a save must be refused because a draft opened by someone else is still waiting on
 * approval. Fails closed: an actor Studio cannot identify is never treated as the owner, so an
 * unidentified caller is refused rather than let through. A pending draft with no recorded
 * owner (state written before this existed) blocks nobody — there is nothing to compare against. */
export function blocksSave(
  pendingOwner: string | null | undefined,
  actor: string | null | undefined,
): boolean {
  if (!pendingOwner) return false
  return !actor || actor !== pendingOwner
}

export async function save(
  projectPath: string,
  pluginScriptsDir: string,
  changeNote: string,
  options: SaveOptions = {},
): Promise<SaveResult> {
  if (!(await hasOrigin(projectPath).catch(() => false))) {
    emitSyncState({ kind: 'localOnly' })
    return { ok: false, entries: [], error: NOT_CONNECTED }
  }
  emitSyncState({ kind: 'saving' })

  const before = getProjectSyncState(projectPath)

  if (before.pendingPrBranch && blocksSave(before.pendingDraftOwner, options.actor)) {
    const owner = before.pendingDraftOwner || 'someone else'
    const files = before.pendingDraftFiles?.length ? ` (covering ${before.pendingDraftFiles.join(', ')})` : ''
    return {
      ok: false,
      entries: [],
      error: `A draft opened by ${owner} is still waiting for approval${files} — only they can change it until it is resolved.`,
    }
  }

  const alreadyClashed = Object.entries(before.files).filter(([, s]) => s.pendingClashSections?.length)
  if (alreadyClashed.length > 0) {
    emitSyncState({ kind: 'clashes', count: pendingSectionCount(before) })
    return { ok: false, entries: [], error: `${alreadyClashed.length} file(s) still have unresolved clashes — resolve them first.` }
  }

  const pullResult = await pull(projectPath, pluginScriptsDir)
  if (!pullResult.ok) {
    return { ok: false, entries: pullResult.entries, error: pullResult.error }
  }
  if (pullResult.clashes.length > 0) {
    return { ok: false, entries: pullResult.entries, error: 'New changes arrived that clash with your edits — resolve them before saving.' }
  }

  const branch = await currentBranch(projectPath)
  const baseSha = (await runGit(['rev-parse', `origin/${branch}`], projectPath)).trim()

  const state = getProjectSyncState(projectPath)
  // Everything committed and pushed below is read from this list, so this is the one place
  // the containment check has to hold for the save path — a file that is really a link
  // elsewhere on the machine must never become a blob in someone else's repository.
  const changedFiles = listLocalAllowlistedFiles(projectPath).filter((relPath) => {
    if (options.onlyPath && relPath !== options.onlyPath) return false
    let fullPath: string
    try {
      fullPath = resolveInProject(projectPath, relPath)
    } catch {
      return false
    }
    if (!existsSync(fullPath)) return false
    const hash = hashBytes(readFileSync(fullPath))
    return state.files[relPath]?.ancestorHash !== hash
  })

  if (changedFiles.length === 0) {
    return { ok: true, entries: [], error: 'Nothing to save — no changes since the last sync.' }
  }

  // Record each saved document as a version BEFORE pushing, so the history reflects what was
  // saved even if the push is then rejected and turns into a pull request. Best-effort: a
  // failure to record history must never block the save itself.
  if (options.actor) {
    for (const relPath of changedFiles) {
      await recordVersion(projectPath, pluginScriptsDir, relPath, options.actor, changeNote)
        .catch(() => undefined)
    }
  }

  const tmpDir = mkdtempSync(join(tmpdir(), 'studio-index-'))
  const indexFile = join(tmpDir, 'index')
  const env = { GIT_INDEX_FILE: indexFile }

  try {
    await runGit(['read-tree', baseSha], projectPath, { env })
    for (const relPath of changedFiles) {
      const bytes = readFileSync(join(projectPath, relPath))
      const blobSha = (await runGit(['hash-object', '-w', '--stdin'], projectPath, { input: bytes.toString('utf-8') })).trim()
      await runGit(['update-index', '--add', '--cacheinfo', `100644,${blobSha},${relPath}`], projectPath, { env })
    }
    const newTree = (await runGit(['write-tree'], projectPath, { env })).trim()
    // A name the person typed because the host could not identify them (D-OWNER-5) is labelled
    // in Studio's own commit message, so the repository's history says which saves carried an
    // unverified name. The plugin's ledgers get the plain name — they match on `@handle`.
    const typedInUse = Boolean(options.actor) && options.actor === getTypedActor(projectPath)
    const commitMessage = typedInUse ? `${changeNote}${TYPED_NAME_SUFFIX}` : changeNote
    const newCommit = (await runGit(['commit-tree', newTree, '-p', baseSha, '-m', commitMessage], projectPath)).trim()

    const directPush = await runGitTolerant(['push', 'origin', `${newCommit}:refs/heads/${branch}`], projectPath)

    if (directPush.ok) {
      for (const relPath of changedFiles) {
        const bytes = readFileSync(join(projectPath, relPath))
        const hash = hashBytes(bytes)
        storeAncestorBlob(hash, bytes)
        state.files[relPath] = { ancestorHash: hash }
      }
      // Landed straight on the shared branch — any earlier draft this Studio was tracking is
      // superseded (this only reaches here when it was the owner's own save going through, per
      // the block above), so there is nothing left pending.
      state.pendingPrBranch = null
      state.pendingDraftOwner = null
      state.pendingDraftFiles = undefined
      saveProjectSyncState(projectPath, state)
      emitSyncState({ kind: 'idle', lastPulledAt: state.lastPulledAt })
      return { ok: true, outcome: 'pushed_directly', entries: [directPush] }
    }

    // Rejected (most likely branch protection) — branch + PR fallback.
    const branchName = `shepherd/${Date.now()}`
    const pushBranch = await runGitTolerant(['push', 'origin', `${newCommit}:refs/heads/${branchName}`], projectPath)
    if (!pushBranch.ok) {
      return { ok: false, entries: [directPush, pushBranch], error: pushBranch.stderr || 'Could not push — check network and permissions.' }
    }

    const approval = await approvalSettingsForFiles(pluginScriptsDir, projectPath, changedFiles)
    const resolved = await resolveHost(projectPath)
    const review = await reviewerFor(resolved, approval, projectPath, pluginScriptsDir)

    let prUrl: string
    let hostNote: string | undefined
    try {
      const created = await resolved.provider.createPullRequest({
        base: branch, head: branchName,
        title: (changeNote.split('\n')[0] || `Shepherd save ${branchName}`).slice(0, 72),
        body: `Saved from Shepherd.\n\n${changeNote}`,
        reviewer: review.reviewer,
      })
      prUrl = created.url
      hostNote = created.note
    } catch (err) {
      // The CLI could not do it here (absent, extension missing, signed out): the §7.1
      // sentence for this feature, which also says the truth — the branch is pushed, but
      // nothing reached the shared branch. A real failure of a real call is passed on as said.
      const unavailable = err instanceof CodeHostUnavailable
        ? hostFeatureReason({ host: resolved.host, cli: resolved.cli }, 'saveWhenProtected')
        : null
      return { ok: false, entries: [directPush, pushBranch], error: unavailable ?? (err instanceof Error ? err.message : String(err)) }
    }
    const note = [review.note, hostNote].filter((n): n is string => Boolean(n)).join(' ')

    for (const relPath of changedFiles) {
      const bytes = readFileSync(join(projectPath, relPath))
      const hash = hashBytes(bytes)
      storeAncestorBlob(hash, bytes)
      state.files[relPath] = { ancestorHash: hash }
    }
    // Remember exactly which branch this was, so the merge poller can recognise its OWN
    // pull request rather than whichever one a name search happens to return first.
    state.pendingPrBranch = branchName
    // ...and who opened it, so a later save from anyone else is refused rather than
    // silently opening a competing draft the poller would then have no way to track.
    state.pendingDraftOwner = options.actor ?? null
    state.pendingDraftFiles = changedFiles
    saveProjectSyncState(projectPath, state)

    emitSyncState(
      approval.required
        ? { kind: 'waitingForApproval', approver: approval.approver ?? 'the named approver' }
        : { kind: 'waitingForChecks' },
    )

    return { ok: true, outcome: 'opened_pull_request', prUrl, entries: [directPush, pushBranch], ...(note ? { note } : {}) }
  } finally {
    try { rmSync(tmpDir, { recursive: true, force: true }) } catch { /* best effort cleanup */ }
  }
}

// --- pull-request polling (Studio-driven — never GitHub's native auto-merge; finding 8) ----

export interface PrListEntry {
  number: number
  headRefName: string
  author?: { login?: string } | null
  headRepositoryOwner?: { login?: string } | null
  /** `null` is Azure DevOps in v1 (D-OWNER-8): the host does not say what the pull request
   * changes, so the poll's "can't tell what it changes, so don't merge it" branch refuses. */
  files?: Array<{ path: string }> | null
  statusCheckRollup?: Array<{ status: string; conclusion: string | null }>
  reviews?: Array<{ state: string }>
}

/** Is this pull request the one THIS Studio opened?
 *
 * It used to merge `prs[0]` from a `head:studio/` search. That is a search, not an exact
 * filter, and it includes pull requests opened by anyone — on a public repository, anyone at
 * all, from a fork. Studio then merged it into the protected default branch with the user's
 * own credentials, which laundered a stranger's commit past the very branch protection and
 * review requirement that sent the save down this path in the first place.
 *
 * Three things must all hold: the head branch is the exact one Studio pushed and remembered,
 * the pull request was opened by the signed-in account, and the branch lives in this
 * repository rather than a fork. */
export function isOursToMerge(pr: PrListEntry, pushedBranch: string | null | undefined, account: string | null, repoOwner: string | null): boolean {
  if (!pushedBranch || pr.headRefName !== pushedBranch) return false
  if (!account || (pr.author?.login ?? '') !== account) return false
  if (!repoOwner || (pr.headRepositoryOwner?.login ?? '') !== repoOwner) return false
  return true
}

/** Called alongside the periodic pull tick. Merges an open Studio-opened PR itself, once
 * Studio personally observes checks green (and, when the affected stage requires it, an
 * APPROVED review) — GitHub's own `--auto` merges on the server even while Studio is closed,
 * which would violate the spec's "no background work while Studio is closed" scope. */
export async function pollAndMergeOpenPullRequest(
  projectPath: string,
  pluginScriptsDir: string,
): Promise<{ merged: boolean; prUrl?: string }> {
  const syncState = getProjectSyncState(projectPath)
  const pushedBranch = syncState.pendingPrBranch
  if (!pushedBranch) return { merged: false } // this Studio has no pull request outstanding

  // The two comparands isOursToMerge needs, straight from the host: the raw identity (a GitHub
  // login, an Azure DevOps UPN — never the roster handle, which is not what the host writes on
  // a pull request) and the owner key (the owner login on GitHub, the repository GUID on ADO).
  let provider: CodeHost
  let account: string | null = null
  let repoOwner: string | null = null
  try {
    provider = (await resolveHost(projectPath)).provider
    account = (await provider.whoAmI()).login.trim() || null
    repoOwner = (await provider.repoView()).headOwnerKey
  } catch {
    return { merged: false } // can't establish whose it is, so don't merge anything
  }

  let prs: PrListEntry[]
  try {
    prs = await provider.listOpenPullRequests(pushedBranch)
  } catch {
    return { merged: false }
  }

  const pr = prs.find((candidate) => isOursToMerge(candidate, pushedBranch, account, repoOwner))
  if (!pr) {
    // The list call above succeeded but found nothing open under our name for this branch —
    // it was merged or closed outside Studio. Forgetting it here is what stops a draft closed
    // without merging from permanently refusing every future save (see blocksSave): otherwise
    // nothing would ever clear pendingDraftOwner again.
    const after = getProjectSyncState(projectPath)
    if (after.pendingPrBranch === pushedBranch) {
      after.pendingPrBranch = null
      after.pendingDraftOwner = null
      after.pendingDraftFiles = undefined
      saveProjectSyncState(projectPath, after)
    }
    return { merged: false }
  }

  const checks = pr.statusCheckRollup ?? []
  const checksGreen = checks.length === 0
    || checks.every((c) => c.status === 'COMPLETED' && (c.conclusion === 'SUCCESS' || c.conclusion === 'NEUTRAL' || c.conclusion === 'SKIPPED'))
  if (!checksGreen) {
    emitSyncState({ kind: 'waitingForChecks' })
    return { merged: false }
  }

  // Whether approval is required is a question about the files THIS pull request changes.
  // It used to be asked about every changed file in the local working tree, which has no
  // necessary relationship to the pull request being merged — someone could edit a
  // stage needing no approval locally and unlock the merge of one that does.
  const prFiles = (pr.files ?? []).map((f) => f.path)
  if (prFiles.length === 0) return { merged: false } // can't tell what it changes (ADO's `files: null` included), so don't merge it

  const approval = await approvalSettingsForFiles(pluginScriptsDir, projectPath, prFiles)
  if (!approval.known) return { merged: false } // can't tell whether approval is needed, so don't merge

  if (approval.required) {
    const approved = (pr.reviews ?? []).some((r) => r.state === 'APPROVED')
    if (!approved) {
      emitSyncState({ kind: 'waitingForApproval', approver: approval.approver ?? 'the named approver' })
      return { merged: false }
    }
  }

  try {
    const out = await provider.mergePullRequest(pr.number)
    const after = getProjectSyncState(projectPath)
    after.pendingPrBranch = null // merged — this Studio has nothing outstanding again
    after.pendingDraftOwner = null
    after.pendingDraftFiles = undefined
    saveProjectSyncState(projectPath, after)
    emitSyncState({ kind: 'idle', lastPulledAt: after.lastPulledAt })
    return { merged: true, prUrl: out.trim() }
  } catch {
    return { merged: false }
  }
}
