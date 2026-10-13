// The Sprint view in the main process (proposal: studio-improvements, Batch 2): read the sprint
// `sprint.py status --json` reports, and write its planning or review page on request. Nothing
// here computes a sprint fact — the plugin does, and Studio draws its answer. Nothing here writes
// except the two pages, and those are the plugin's own scripts writing into .sdlc/reports/.
//
// Same shape as activityRuns.ts (spec 0026): plain functions over (project, plugin scripts dir,
// ...) so tests drive them directly, a fixed argv, ids validated before they reach it, and a
// defensive parse of exactly one JSON document read from `rawStdout` (never the redacted
// `entry.stdout`). `registerSprintHandlers` is all index.ts needs to know.

import { existsSync, realpathSync } from 'node:fs'
import { isAbsolute, join, relative } from 'node:path'
import type { IpcMain } from 'electron'
import { runPluginScript } from './project'
import { rawStdout } from './commandRunner'
import { isSprintId } from '../../shared/sprintModel'
import { readSlateProposal, readSprintList, readSprintLog } from './commandCenterReaders'
import { PLUGIN_NOT_FOUND } from '../../shared/pluginId'
import type {
  SlateProposal, SprintCarriedIn, SprintDecisions, SprintHandoffOpen, SprintListView, SprintLogView, SprintMixTier,
  SprintReadinessGap, SprintRecord, SprintReportKind, SprintReportResult, SprintSlateRow, SprintStatusResult,
  SprintVerdictPending, SprintView,
} from '../../shared/types'

const NO_PLUGIN = PLUGIN_NOT_FOUND
const NOT_A_SPRINT_ID = 'That is not a sprint id Shepherd can read (expected S07, S12, ...).'
const UNREADABLE = 'The sprint could not be read, so there is nothing to show.'
const PAGE_UNWRITTEN = 'The sprint page could not be written.'

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [])
const str = (v: unknown): string => (typeof v === 'string' ? v : '')
const finite = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const stateFile = (project: string) => join(project, '.sdlc', 'state.yaml')

/** `--state` when the project has one, else `--repo`: the scripts run standalone too, and a
 * `--state` that points at a file that is not there is their one-line error, not a sprint. */
export function sourceArgs(projectPath: string): string[] {
  const state = stateFile(projectPath)
  return existsSync(state) ? ['--state', state] : ['--repo', projectPath]
}

/** The plugin's own refusal, when it gave one on its usual "Error:" line; otherwise null, so a
 * python traceback or a missing-script message never reaches a person. */
export function pluginMessage(stdout: string, stderr: string): string | null {
  for (const line of `${stderr}\n${stdout}`.split(/\r?\n/)) {
    const m = /^error:\s*(.+)$/i.exec(line.trim())
    if (m) return m[1].replace(/�/g, '-').trim()
  }
  return null
}

export type Ran = { exitCode: number | null; raw: Record<string, unknown> | null; stdout: string; stderr: string }

/** Runs `script` and parses stdout as exactly one JSON object when it is one; the exit code
 * comes back beside it so each caller decides what counts as an answer. */
export async function run(scriptsDir: string, script: string, args: string[]): Promise<Ran> {
  const entry = await runPluginScript(scriptsDir, script, args)
  let raw: Record<string, unknown> | null = null
  try {
    const parsed: unknown = JSON.parse(rawStdout(entry))
    raw = isRecord(parsed) ? parsed : null
  } catch {
    raw = null
  }
  return { exitCode: entry.exitCode, raw, stdout: entry.stdout, stderr: entry.stderr }
}

// --- reading the view --------------------------------------------------------------------------

/** The project path as given and as the filesystem really has it: the plugin resolves its repo
 * root before printing paths (a macOS temp folder is /var/... to the caller and /private/var/...
 * to the plugin), so a relative path must be tried against both. */
function projectRoots(projectPath: string): string[] {
  try {
    const real = realpathSync.native(projectPath)
    return real === projectPath ? [projectPath] : [projectPath, real]
  } catch {
    return [projectPath]
  }
}

/** The repo-relative POSIX path the plugin prints as `rel_path`; derived from the absolute `path`
 * for a plugin that predates it, and '' when neither can be read. */
function relPathOf(raw: Record<string, unknown>, projectPath: string): string {
  if (typeof raw.rel_path === 'string' && raw.rel_path !== '') return raw.rel_path
  const abs = str(raw.path)
  if (!abs || !isAbsolute(abs)) return ''
  for (const root of projectRoots(projectPath)) {
    const rel = relative(root, abs).replace(/\\/g, '/')
    if (rel !== '' && !rel.startsWith('..')) return rel
  }
  return ''
}

function readSlateRow(raw: unknown, projectPath: string): SprintSlateRow | null {
  if (!isRecord(raw) || typeof raw.id !== 'string') return null
  return {
    id: raw.id, name: str(raw.name), risk: str(raw.risk), type: str(raw.type), channel: str(raw.channel),
    status: str(raw.status), sprint: str(raw.sprint), nextOwner: str(raw.next_owner),
    engReview: str(raw.eng_review), dataReview: str(raw.data_review), dependsOn: strings(raw.depends_on),
    dor: raw.dor === 'READY' ? 'READY' : 'NOT READY', dorBlocking: strings(raw.dor_blocking),
    path: str(raw.path), relPath: relPathOf(raw, projectPath),
  }
}

function readSprint(raw: unknown, projectPath: string): SprintRecord | null {
  if (!isRecord(raw) || typeof raw.id !== 'string') return null
  const days = isRecord(raw.days) ? raw.days : {}
  return {
    id: raw.id, goal: str(raw.goal), start: str(raw.start), end: str(raw.end), state: str(raw.state),
    target: finite(raw.target), mix: str(raw.mix), boardRef: str(raw.board_ref), readiedBy: str(raw.readied_by),
    closedBy: str(raw.closed_by), created: str(raw.created), path: str(raw.path), relPath: relPathOf(raw, projectPath),
    days: { total: finite(days.total), elapsed: finite(days.elapsed), remaining: finite(days.remaining) },
  }
}

const readGap = (raw: unknown): SprintReadinessGap | null =>
  isRecord(raw) ? { spec: str(raw.spec), gaps: strings(raw.gaps) } : null
const readVerdict = (raw: unknown): SprintVerdictPending | null =>
  isRecord(raw) ? { spec: str(raw.spec), lane: str(raw.lane), sinceBusinessDays: finite(raw.since_business_days) } : null
const readHandoff = (raw: unknown): SprintHandoffOpen | null =>
  isRecord(raw) ? { spec: str(raw.spec), to: str(raw.to), sinceBusinessDays: finite(raw.since_business_days) } : null
const readCarried = (raw: unknown): SprintCarriedIn | null =>
  isRecord(raw) ? { spec: str(raw.spec), fromSprint: str(raw.from_sprint), reason: str(raw.reason) } : null

function readMix(raw: unknown): Record<string, SprintMixTier> {
  if (!isRecord(raw)) return {}
  const out: Record<string, SprintMixTier> = {}
  for (const [tier, value] of Object.entries(raw)) {
    if (!isRecord(value)) continue
    const actual = finite(value.actual)
    if (actual === null) continue
    out[tier] = { target: finite(value.target), actual }
  }
  return out
}

function readDecisions(raw: unknown): SprintDecisions | null {
  if (!isRecord(raw)) return null
  const open = finite(raw.open)
  if (open === null) return null
  const overdue = Array.isArray(raw.overdue) ? raw.overdue.filter(isRecord).map((d) => ({
    id: str(d.id), decision: str(d.decision), owner: str(d.owner), due: str(d.due),
  })) : []
  return { open, overdue }
}

function list<T>(raw: unknown, read: (item: unknown) => T | null): T[] {
  return Array.isArray(raw) ? raw.map(read).filter((x): x is T => x !== null) : []
}

/** The view, or null when the document is not the one `status --json` prints. The top-level keys
 * must be there; a null the plugin reports stays null. */
export function readSprintView(raw: Record<string, unknown>, projectPath: string): SprintView | null {
  if (!('sprint' in raw) || !Array.isArray(raw.slate) || !isRecord(raw.readiness) || typeof raw.has_data !== 'boolean') return null
  const slate = raw.slate.map((r) => readSlateRow(r, projectPath))
  if (slate.some((r) => r === null)) return null
  const ready = finite(raw.readiness.ready), total = finite(raw.readiness.total)
  if (ready === null || total === null) return null
  const wip = isRecord(raw.wip) ? raw.wip : {}
  return {
    ok: true,
    sprint: raw.sprint === null ? null : readSprint(raw.sprint, projectPath),
    slate: slate as SprintSlateRow[],
    readiness: { ready, total, gaps: list(raw.readiness.gaps, readGap) },
    verdictsPending: list(raw.verdicts_pending, readVerdict),
    handoffsOpen: list(raw.handoffs_open, readHandoff),
    mix: readMix(raw.mix),
    mixWarnings: strings(raw.mix_warnings),
    wip: { inFlight: finite(wip.in_flight), cap: finite(wip.cap) },
    buildOrder: strings(raw.build_order),
    nextUp: typeof raw.next_up === 'string' && raw.next_up !== '' ? raw.next_up : null,
    dependencyGaps: strings(raw.dependency_gaps),
    decisions: readDecisions(raw.decisions),
    carriedIn: list(raw.carried_in, readCarried),
    hasData: raw.has_data,
    note: typeof raw.note === 'string' && raw.note !== '' ? raw.note : null,
  }
}

// --- the two calls -----------------------------------------------------------------------------

/** `sprint.py status --json`, for the active sprint or the one named. Read-only. */
export async function getSprintStatus(projectPath: string, scriptsDir: string, sprintId?: string): Promise<SprintStatusResult> {
  if (sprintId !== undefined && !isSprintId(sprintId)) return { ok: false, error: NOT_A_SPRINT_ID }
  const args = ['status', ...sourceArgs(projectPath), '--json', ...(sprintId !== undefined ? ['--sprint', sprintId] : [])]
  const ran = await run(scriptsDir, 'sprint.py', args)
  if (ran.exitCode !== 0 || ran.raw === null) return { ok: false, error: pluginMessage(ran.stdout, ran.stderr) ?? UNREADABLE }
  return readSprintView(ran.raw, projectPath) ?? { ok: false, error: UNREADABLE }
}

/** Writes the planning page (`sprint.py plan --json`) or the review page
 * (`generate_sprint_report.py --kind review --json`). The scripts print `{ok, rel_output}` on
 * success and `{ok: false, error}` with their usual exit code on a refusal, which is passed on in
 * their words. */
export async function renderSprintReport(
  projectPath: string, scriptsDir: string, sprintId: string, kind: SprintReportKind,
): Promise<SprintReportResult> {
  if (!isSprintId(sprintId)) return { ok: false, error: NOT_A_SPRINT_ID }
  if (kind !== 'planning' && kind !== 'review') return { ok: false, error: 'Shepherd writes a planning page or a review page.' }
  const [script, args] = kind === 'planning'
    ? ['sprint.py', ['plan', ...sourceArgs(projectPath), '--sprint', sprintId, '--json']] as const
    : ['generate_sprint_report.py', [...sourceArgs(projectPath), '--sprint', sprintId, '--kind', 'review', '--json']] as const
  const ran = await run(scriptsDir, script, [...args])
  const { raw } = ran
  if (raw !== null && raw.ok === true && ran.exitCode === 0 && typeof raw.rel_output === 'string' && raw.rel_output !== '') {
    return { ok: true, relOutput: raw.rel_output }
  }
  const refusal = raw !== null && raw.ok === false && typeof raw.error === 'string' && raw.error !== '' ? raw.error : null
  return { ok: false, error: refusal ?? pluginMessage(ran.stdout, ran.stderr) ?? PAGE_UNWRITTEN }
}

// --- the command center's sprint reads (togo-command-center.md §2.2) --------------------------
//
// Each is a read (exit 0 always on the plugin side), answers `{ ok, data | error }` and parses
// nothing beyond the one document. The caller wraps the answer in a `SourcedBlock`; the
// capability check (`sprint-list`, `sprint-log`) is the caller's too, so an older plugin is
// never asked for a verb it lacks.

export type Read<T> = { ok: true; data: T } | { ok: false; error: string }

/** `sprint.py list --json`: every sprint record with its 1-based ordinal and the active id. */
export async function getSprintList(projectPath: string, scriptsDir: string): Promise<Read<SprintListView>> {
  const ran = await run(scriptsDir, 'sprint.py', ['list', ...sourceArgs(projectPath), '--json'])
  const data = ran.exitCode === 0 && ran.raw ? readSprintList(ran.raw) : null
  return data ? { ok: true, data } : { ok: false, error: pluginMessage(ran.stdout, ran.stderr) ?? (ran.stderr.trim() || UNREADABLE) }
}

/** `sprint.py log [--since D] [--sprint SNN] --json`: the ledger lines verbatim. `since` is the
 * filter the person picked, as YYYY-MM-DD — never a number Studio reports. */
export async function getSprintLog(projectPath: string, scriptsDir: string, since?: string, sprintId?: string): Promise<Read<SprintLogView>> {
  if (since !== undefined && !/^\d{4}-\d{2}-\d{2}$/.test(since)) return { ok: false, error: 'since must be a date (YYYY-MM-DD)' }
  if (sprintId !== undefined && !isSprintId(sprintId)) return { ok: false, error: NOT_A_SPRINT_ID }
  const args = ['log', ...sourceArgs(projectPath), ...(since ? ['--since', since] : []), ...(sprintId ? ['--sprint', sprintId] : []), '--json']
  const ran = await run(scriptsDir, 'sprint.py', args)
  const data = ran.exitCode === 0 && ran.raw ? readSprintLog(ran.raw) : null
  return data ? { ok: true, data } : { ok: false, error: pluginMessage(ran.stdout, ran.stderr) ?? (ran.stderr.trim() || UNREADABLE) }
}

/** `sprint.py slate --sprint SNN --json` with no `--spec`: the plugin's deterministic, read-only
 * proposal. Nothing is written — the write path is `runSprintVerb({verb:'slate'})`. */
export async function getSlateProposal(projectPath: string, scriptsDir: string, sprintId: string): Promise<Read<SlateProposal>> {
  if (!isSprintId(sprintId)) return { ok: false, error: NOT_A_SPRINT_ID }
  const ran = await run(scriptsDir, 'sprint.py', ['slate', ...sourceArgs(projectPath), '--sprint', sprintId, '--json'])
  const data = ran.exitCode === 0 && ran.raw ? readSlateProposal(ran.raw) : null
  return data ? { ok: true, data } : { ok: false, error: pluginMessage(ran.stdout, ran.stderr) ?? (ran.stderr.trim() || UNREADABLE) }
}

// --- registration ------------------------------------------------------------------------------

export function registerSprintHandlers(
  ipcMain: Pick<IpcMain, 'handle'>,
  resolvePluginScriptsDir: () => Promise<string | null>,
): void {
  ipcMain.handle('studio:getSprintStatus', async (_event, projectPath: string, sprintId?: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? getSprintStatus(projectPath, scriptsDir, sprintId) : { ok: false, error: NO_PLUGIN }
  })
  ipcMain.handle('studio:renderSprintReport', async (_event, projectPath: string, sprintId: string, kind: SprintReportKind) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? renderSprintReport(projectPath, scriptsDir, sprintId, kind) : { ok: false, error: NO_PLUGIN }
  })
}
