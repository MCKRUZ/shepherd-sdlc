// What the four run activities do in the main process (spec 0026): export a stage report, catalogue
// the reference documents, read how far the plain-language summaries have got, read the standing
// picture of review findings. None of them runs a model, and none writes a file from Studio itself:
// the plugin's scripts write the reports and the catalogue, Studio only reads their answer.
//
// Same shape as activities.ts (spec 0024): each is a plain function over (project, plugin scripts
// dir, ...) so tests drive it directly, a fixed argv, and a defensive parse. `registerActivityRunHandlers`
// is the only thing index.ts needs to know about.

import { existsSync, realpathSync, statSync } from 'node:fs'
import { join, resolve, sep } from 'node:path'
import type { IpcMain } from 'electron'
import { runPluginScript } from './project'
import { rawStdout } from './commandRunner'
import { PLUGIN_NOT_FOUND } from '../../shared/pluginId'
import type {
  IntakeCatalogue, IntakeChange, IntakeDocument, NarrativeArtifact, NarrativeCoverage, PhaseReportEntry,
  PhaseReportResult, ReviewStanding, StrictCheckResult,
} from '../../shared/types'

const NO_PLUGIN = PLUGIN_NOT_FOUND
const DOC_ID = /^DOC-\d{3,}$/
const STAGE_ID = /^[A-Za-z0-9]{1,16}$/

const stateFile = (project: string) => join(project, '.sdlc', 'state.yaml')
const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [])

// --- running a script and reading its one JSON document ----------------------------------------

type Parsed = { ok: true; raw: Record<string, unknown>; exitCode: number } | { ok: false; error: string }

/** The plugin's own refusal, when it gave one on its usual "Error:" line (stderr for most scripts,
 * stdout for a few); otherwise null, so a python traceback or a missing-script message never
 * reaches a person. */
function pluginMessage(stdout: string, stderr: string): string | null {
  for (const line of `${stderr}\n${stdout}`.split(/\r?\n/)) {
    const m = /^error:\s*(.+)$/i.exec(line.trim())
    // A Windows console pipe hands a dash from python's stderr over as U+FFFD.
    if (m) return m[1].replace(/�/g, '-').trim()
  }
  return null
}

/** Runs `script` and parses stdout as exactly one JSON object. Only exit codes in `accept` are a
 * result; anything else, or output that is not one object, is one plain error line. */
async function runJson(scriptsDir: string, script: string, args: string[], what: string, accept: readonly number[] = [0]): Promise<Parsed> {
  const entry = await runPluginScript(scriptsDir, script, args)
  const failed = (): Parsed => ({
    ok: false,
    error: pluginMessage(entry.stdout, entry.stderr) ?? `${what} could not be read, so there is nothing to show.`,
  })
  if (entry.exitCode === null || !accept.includes(entry.exitCode)) return failed()
  try {
    const raw: unknown = JSON.parse(rawStdout(entry))
    return isRecord(raw) ? { ok: true, raw, exitCode: entry.exitCode } : failed()
  } catch {
    return failed()
  }
}

const finite = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

// --- phase report ------------------------------------------------------------------------------

const noReports = (error: string): PhaseReportResult => ({ ok: false, error, reports: [] })

function readReport(raw: unknown, project: string): PhaseReportEntry | null {
  if (!isRecord(raw) || !isRecord(raw.artifacts)) return null
  const { phase, phase_name: phaseName, output } = raw
  const found = finite(raw.found), missing = finite(raw.missing), total = finite(raw.total)
  if (typeof phase !== 'string' || typeof phaseName !== 'string' || typeof output !== 'string') return null
  if (found === null || missing === null || total === null) return null
  return {
    phase, phaseName, found, missing, total,
    output: resolve(project, output),
    missingNames: Object.entries(raw.artifacts).filter(([, present]) => present === false).map(([name]) => name),
  }
}

export async function exportPhaseReport(
  projectPath: string,
  scriptsDir: string,
  stageId: string,
  all: boolean,
): Promise<PhaseReportResult> {
  if (!all && !STAGE_ID.test(stageId)) return noReports('That is not a stage Shepherd can write a report for.')
  const args = ['--state', stateFile(projectPath), ...(all ? ['--all'] : ['--phase', stageId]), '--json']
  const result = await runJson(scriptsDir, 'generate_phase_report.py', args, 'The report')
  if (!result.ok) return noReports(result.error)

  const rawReports = all ? result.raw.reports : [result.raw]
  const reports = Array.isArray(rawReports) ? rawReports.map((r) => readReport(r, projectPath)) : []
  const unreadable = reports.length === 0 || reports.some((r) => r === null)
  if (unreadable) return noReports('The report could not be read, so there is nothing to show.')
  const index = all && typeof result.raw.index === 'string' ? resolve(projectPath, result.raw.index) : undefined
  return { ok: true, reports: reports as PhaseReportEntry[], ...(index ? { index } : {}) }
}

// --- opening a report --------------------------------------------------------------------------

export type OpenPath = (path: string) => Promise<string>

/** Electron is loaded on first use: the path check must run, and be testable, without it. */
const openWithSystem: OpenPath = async (path) => (await import('electron')).shell.openPath(path)

const inside = (parent: string, child: string) => child.startsWith(parent + sep)

/** Opens a generated report with the operating system's default program, and only a report: an
 * .html file whose REAL location is inside <project>/.sdlc/reports/. The path crosses from the
 * renderer, so a `..` segment, a link that leads elsewhere, or a folder that is itself a link is
 * refused with one line and nothing is opened. */
export async function openReport(
  projectPath: string,
  reportPath: string,
  open: OpenPath = openWithSystem,
): Promise<{ ok: boolean; error?: string }> {
  const refuse = (error: string) => ({ ok: false, error })
  if (reportPath.replace(/\\/g, '/').split('/').includes('..')) return refuse('Shepherd only opens reports from this project’s .sdlc/reports folder.')
  if (!/\.html$/i.test(reportPath)) return refuse('Shepherd only opens report pages (.html).')

  const reportsDir = join(projectPath, '.sdlc', 'reports')
  const full = resolve(projectPath, reportPath)
  if (!existsSync(reportsDir) || !existsSync(full) || !statSync(full).isFile()) return refuse('That report is not there any more.')

  const realReports = realpathSync.native(reportsDir)
  const realProjectReports = join(realpathSync.native(projectPath), '.sdlc', 'reports')
  const realFull = realpathSync.native(full)
  // The reports folder must be the project's own, not a link elsewhere, and the file must really be in it.
  if (realReports !== realProjectReports || !inside(realReports, realFull)) {
    return refuse('Shepherd only opens reports from this project’s .sdlc/reports folder.')
  }
  try {
    const failure = await open(realFull)
    return failure ? refuse(`The report could not be opened: ${failure.split(/\r?\n/)[0]}`) : { ok: true }
  } catch {
    return refuse('The report could not be opened.')
  }
}

// --- intake ------------------------------------------------------------------------------------

const noCatalogue = (error: string): IntakeCatalogue => ({
  ok: false, error, documents: [], locked: false, priorityOrder: [],
  totals: { documents: 0, estimatedTokens: 0, activeDocuments: 0 },
})

const validIds = (ids: readonly unknown[] | undefined): boolean => (ids ?? []).every((id) => typeof id === 'string' && DOC_ID.test(id))

function intakeArgs(project: string, change: IntakeChange): string[] {
  return [
    '--state', stateFile(project), '--json',
    ...(change.skip?.length ? ['--skip', change.skip.join(',')] : []),
    ...(change.priority?.length ? ['--priority', change.priority.join(',')] : []),
    ...(change.lock ? ['--lock'] : []),
  ]
}

function readDocument(raw: unknown): IntakeDocument | null {
  if (!isRecord(raw) || typeof raw.id !== 'string' || typeof raw.file !== 'string') return null
  return {
    id: raw.id, file: raw.file, type: typeof raw.type === 'string' ? raw.type : '',
    tokens: finite(raw.tokens) ?? 0, skipped: raw.skipped === true, priority: finite(raw.priority),
  }
}

export async function runIntake(projectPath: string, scriptsDir: string, change: IntakeChange = {}): Promise<IntakeCatalogue> {
  if (!validIds(change.skip) || !validIds(change.priority)) return noCatalogue('Those are not document ids Shepherd can use.')
  // Exit 2 is the script's "nothing to catalogue": it prints an empty catalogue. Taken as a result
  // only when the document list really is empty, so a missing script (python's own exit 2, nothing
  // printed) and a half-written answer are still errors.
  const result = await runJson(scriptsDir, 'intake_documents.py', intakeArgs(projectPath, change), 'The document catalogue', [0, 2])
  if (!result.ok) return noCatalogue(result.error)

  const documents = Array.isArray(result.raw.documents) ? result.raw.documents.map(readDocument) : null
  const emptyOnExit2 = result.exitCode !== 2 || documents?.length === 0
  if (!documents || !emptyOnExit2 || documents.some((d) => d === null)) return noCatalogue('The document catalogue could not be read, so there is nothing to show.')
  const read = documents as IntakeDocument[]
  const totals = isRecord(result.raw.totals) ? result.raw.totals : {}
  return {
    ok: true,
    documents: read,
    locked: result.raw.locked === true,
    priorityOrder: strings(result.raw.priority_order),
    totals: {
      documents: finite(totals.documents) ?? read.length,
      estimatedTokens: finite(totals.estimated_tokens) ?? 0,
      activeDocuments: finite(totals.active_documents) ?? read.filter((d) => !d.skipped).length,
    },
  }
}

// --- plain-language summary coverage -----------------------------------------------------------

const noCoverage = (error: string): NarrativeCoverage => ({
  ok: false, error, hasData: false, notes: [], withNarrative: 0, total: 0, artifacts: [],
})

function readArtifact(raw: unknown): NarrativeArtifact | null {
  if (!isRecord(raw) || typeof raw.name !== 'string') return null
  return { name: raw.name, status: raw.status === 'present' ? 'present' : 'none', stale: typeof raw.stale === 'boolean' ? raw.stale : null }
}

export async function getNarrativeCoverage(projectPath: string, scriptsDir: string, stageId: string): Promise<NarrativeCoverage> {
  if (!STAGE_ID.test(stageId)) return noCoverage('That is not a stage Shepherd can read summaries for.')
  const result = await runJson(scriptsDir, 'narrative_status.py', ['--state', stateFile(projectPath), '--phase', stageId, '--json'], 'The summary coverage')
  if (!result.ok) return noCoverage(result.error)

  const { raw } = result
  const coverage = isRecord(raw.coverage) ? raw.coverage : null
  const withNarrative = finite(coverage?.with_narrative), total = finite(coverage?.total)
  const phases = Array.isArray(raw.phases) ? raw.phases : null
  if (typeof raw.has_data !== 'boolean' || withNarrative === null || total === null || !phases) {
    return noCoverage('The summary coverage could not be read, so there is nothing to show.')
  }
  const artifacts = phases.flatMap((p) => (isRecord(p) && Array.isArray(p.artifacts) ? p.artifacts : []))
    .map(readArtifact).filter((a): a is NarrativeArtifact => a !== null)
  return { ok: true, hasData: raw.has_data, notes: strings(raw.notes), withNarrative, total, artifacts }
}

// --- review findings ---------------------------------------------------------------------------

const noStanding = (error: string): ReviewStanding => ({ ok: false, error, tracked: 0, openDebt: 0, fixedClaimMismatches: 0 })

function readStanding(raw: Record<string, unknown>): Omit<ReviewStanding, 'ok' | 'error'> | null {
  const tracked = finite(raw.tracked), openDebt = finite(raw.open_debt), mismatches = finite(raw.fixed_claim_mismatches)
  return tracked === null || openDebt === null || mismatches === null ? null : { tracked, openDebt, fixedClaimMismatches: mismatches }
}

const STANDING_UNREADABLE = 'The review findings could not be read, so there is nothing to show.'

export async function getReviewStanding(projectPath: string, scriptsDir: string): Promise<ReviewStanding> {
  const result = await runJson(scriptsDir, 'record_findings.py', ['report', '--state', stateFile(projectPath), '--json'], 'The review findings')
  if (!result.ok) return noStanding(result.error)
  const standing = readStanding(result.raw)
  return standing ? { ok: true, ...standing } : noStanding(STANDING_UNREADABLE)
}

/** `--strict` exits 2 when a finding is marked fixed but its file never changed. That is the answer
 * the button exists to give, so it arrives as a result with the plugin's count, not as an error. */
export async function runStrictReviewCheck(projectPath: string, scriptsDir: string): Promise<StrictCheckResult> {
  const args = ['report', '--state', stateFile(projectPath), '--json', '--strict']
  const result = await runJson(scriptsDir, 'record_findings.py', args, 'The strict check', [0, 2])
  if (!result.ok) return { ok: false, error: result.error, mismatches: 0 }
  const standing = readStanding(result.raw)
  return standing
    ? { ok: true, mismatches: standing.fixedClaimMismatches }
    : { ok: false, error: STANDING_UNREADABLE, mismatches: 0 }
}

// --- registration ------------------------------------------------------------------------------

export function registerActivityRunHandlers(
  ipcMain: Pick<IpcMain, 'handle'>,
  resolvePluginScriptsDir: () => Promise<string | null>,
  open: OpenPath = openWithSystem,
): void {
  ipcMain.handle('studio:exportPhaseReport', async (_event, projectPath: string, stageId: string, all: boolean) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? exportPhaseReport(projectPath, scriptsDir, stageId, all === true) : noReports(NO_PLUGIN)
  })
  ipcMain.handle('studio:openReport', (_event, projectPath: string, reportPath: string) => openReport(projectPath, reportPath, open))
  ipcMain.handle('studio:runIntake', async (_event, projectPath: string, change?: IntakeChange) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? runIntake(projectPath, scriptsDir, change) : noCatalogue(NO_PLUGIN)
  })
  ipcMain.handle('studio:getNarrativeCoverage', async (_event, projectPath: string, stageId: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? getNarrativeCoverage(projectPath, scriptsDir, stageId) : noCoverage(NO_PLUGIN)
  })
  ipcMain.handle('studio:getReviewStanding', async (_event, projectPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? getReviewStanding(projectPath, scriptsDir) : noStanding(NO_PLUGIN)
  })
  ipcMain.handle('studio:runStrictReviewCheck', async (_event, projectPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? runStrictReviewCheck(projectPath, scriptsDir) : { ok: false, error: NO_PLUGIN, mismatches: 0 }
  })
}
