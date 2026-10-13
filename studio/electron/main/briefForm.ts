// The workshop brief form in the main process (spec 0032): read what the brief can be built from, and
// build it. No model runs; the plugin's workshop_brief.py does both and Studio only validates, calls it
// and reads its answer.
//
// The renderer is untrusted. buildBrief therefore re-reads the candidates itself, re-validates every
// selection against them (briefValidate.ts) and starts the build only when all of it holds. The argument
// list is fixed: the flags are constants, ids are matched against the candidates, and everything the
// person typed travels only as the value of a --*-json argument. No shell is involved.

import { realpathSync } from 'node:fs'
import { isAbsolute, join, relative, resolve, sep } from 'node:path'
import type { IpcMain } from 'electron'
import { checkAgainstCandidates, parseSelections, questionIdsForBuild } from './briefValidate'
import { finite, isRecord, runBriefScript, strings } from './briefRun'
import { PLUGIN_NOT_FOUND } from '../../shared/pluginId'
import type {
  BriefCandidatesResult, BriefContradiction, BriefDocument, BriefLimits, BriefQuestion, BriefSelections, BriefSource, BuildBriefResult,
} from '../../shared/types'

const NO_PLUGIN = PLUGIN_NOT_FOUND
const CANDIDATES_UNREADABLE = 'The workshop brief choices could not be read, so there is nothing to show.'
const BUILD_UNREADABLE = 'The brief could not be confirmed: the plugin did not give an answer Shepherd could read.'
// Where `--state <project>/.sdlc/state.yaml` makes the plugin write the brief.
const BRIEF_PATH = '.sdlc/artifacts/00-discovery/workshop-brief.md'

const stateFile = (project: string) => join(project, '.sdlc', 'state.yaml')
const fail = (error: string): { ok: false; error: string } => ({ ok: false, error })
const text = (v: unknown): string | null => (typeof v === 'string' ? v : null)

// --- reading the candidates ---------------------------------------------------------------------

function readAll<T>(raw: unknown, read: (item: unknown) => T | null): T[] | null {
  if (!Array.isArray(raw)) return null
  const items = raw.map(read)
  return items.every((item) => item !== null) ? (items as T[]) : null
}

function readSource(raw: unknown): BriefSource | null {
  if (!isRecord(raw) || (raw.side !== 'A' && raw.side !== 'B')) return null
  const document = text(raw.document), quote = text(raw.quote)
  return document === null || quote === null ? null : { side: raw.side, document, quote }
}

function readContradiction(raw: unknown): BriefContradiction | null {
  if (!isRecord(raw)) return null
  const id = text(raw.id), title = text(raw.title), sources = readAll(raw.sources, readSource)
  if (id === null || title === null || sources === null || typeof raw.recommended !== 'boolean') return null
  return { id, title, severity: text(raw.severity) ?? '', question: text(raw.question) ?? '', sources, recommended: raw.recommended }
}

function readQuestion(raw: unknown): BriefQuestion | null {
  if (!isRecord(raw)) return null
  const id = text(raw.id), question = text(raw.question), block = text(raw.block), route = text(raw.route)
  return id === null || question === null || block === null || route === null ? null : { id, question, block, route }
}

function readDocument(raw: unknown): BriefDocument | null {
  if (!isRecord(raw)) return null
  const id = text(raw.id), filename = text(raw.filename)
  return id === null || filename === null ? null : { id, filename, topics: text(raw.topics) ?? '' }
}

function readRange(raw: unknown): [number, number] | null {
  if (!Array.isArray(raw) || raw.length !== 2) return null
  const low = finite(raw[0]), high = finite(raw[1])
  return low === null || high === null ? null : [low, high]
}

function readLimits(raw: unknown): BriefLimits | null {
  if (!isRecord(raw)) return null
  const contradictions = finite(raw.contradictions), questions = finite(raw.questions)
  const decisions = readRange(raw.decisions), loadBearing = readRange(raw.load_bearing)
  return contradictions === null || questions === null || !decisions || !loadBearing ? null : { contradictions, questions, decisions, loadBearing }
}

function readCandidates(raw: Record<string, unknown>): BriefCandidatesResult {
  const limits = readLimits(raw.limits), standing = finite(raw.standing_decisions)
  const lists = {
    contradictions: readAll(raw.contradictions, readContradiction), questions: readAll(raw.questions, readQuestion),
    documents: readAll(raw.documents, readDocument),
  }
  if (typeof raw.has_data !== 'boolean' || typeof raw.existing_brief !== 'boolean' || typeof raw.provisional_ids !== 'boolean') return fail(CANDIDATES_UNREADABLE)
  if (!limits || standing === null) return fail(CANDIDATES_UNREADABLE)
  // With a missing input the plugin may still list what it did find; the form shows the notes and no lists.
  if (raw.has_data && (!lists.contradictions || !lists.questions || !lists.documents)) return fail(CANDIDATES_UNREADABLE)
  return {
    ok: true, hasData: raw.has_data, notes: strings(raw.notes),
    contradictions: raw.has_data ? lists.contradictions ?? [] : [], questions: raw.has_data ? lists.questions ?? [] : [],
    documents: raw.has_data ? lists.documents ?? [] : [], limits, standingDecisions: standing,
    existingBrief: raw.existing_brief, provisionalIds: raw.provisional_ids,
  }
}

/** Runs `workshop_brief.py candidates --state <state> --json`. Writes nothing. */
export async function getBriefCandidates(projectPath: unknown, scriptsDir: string): Promise<BriefCandidatesResult> {
  if (typeof projectPath !== 'string' || projectPath === '') return fail('Open a project first.')
  const result = await runBriefScript(scriptsDir, ['candidates', '--state', stateFile(projectPath), '--json'], CANDIDATES_UNREADABLE)
  return result.ok ? readCandidates(result.raw) : fail(result.error)
}

// --- building -----------------------------------------------------------------------------------

function buildArgs(project: string, s: BriefSelections, questionIds: string[], force: boolean): string[] {
  const { logistics: l } = s
  return [
    'build', '--state', stateFile(project),
    ...(s.contradictions.length ? ['--contradictions', s.contradictions.join(',')] : []),
    ...(questionIds.length ? ['--questions', questionIds.join(',')] : []),
    '--load-bearing', s.loadBearing.join(','),
    '--decisions-json', JSON.stringify(s.decisions),
    '--logistics-json', JSON.stringify({
      client_name: l.clientName, date_time_location: l.dateTimeLocation, duration: l.duration,
      attendees: l.attendees.map((a) => ({ name: a.name, role: a.role })), facilitator: l.facilitator,
    }),
    '--claims-json', JSON.stringify(s.claims.map((c) => ({ text: c.text, doc_ref: c.docRef }))),
    '--json',
    ...(force ? ['--force'] : []),
  ]
}

const realOr = (path: string) => {
  try { return realpathSync.native(path) } catch { return resolve(path) }
}

/** The plugin prints the brief's absolute path; the screen holds a repo-relative, forward-slash one.
 * Both sides are resolved first so a short Windows name or a link cannot make it look outside the project. */
function repoRelative(project: string, absolute: string): string {
  const rel = relative(realOr(project), realOr(absolute))
  return rel === '' || rel.startsWith('..') || isAbsolute(rel) ? BRIEF_PATH : rel.split(sep).join('/')
}

function readBuilt(raw: Record<string, unknown>, project: string): BuildBriefResult | null {
  const path = text(raw.path)
  const contradictions = isRecord(raw.contradictions) ? finite(raw.contradictions.on_page) : null
  const questions = isRecord(raw.questions) ? raw.questions : null
  const questionsOnPage = questions ? finite(questions.on_page) : null
  if (path === null || contradictions === null || questionsOnPage === null || !Array.isArray(questions?.emailed_instead)) return null
  const lint = (Array.isArray(raw.lint) ? raw.lint : []).flatMap((l) => {
    const line = isRecord(l) ? finite(l.line) : null
    return line !== null && isRecord(l) && typeof l.message === 'string' ? [{ line, message: l.message }] : []
  })
  return {
    ok: true, path: repoRelative(project, path), contradictionsOnPage: contradictions, questionsOnPage,
    emailedInstead: strings(questions?.emailed_instead), notes: strings(raw.notes), lint,
  }
}

/** Validates `selections` itself and, only if all of it holds, runs the fixed `workshop_brief.py build`. */
export async function buildBrief(projectPath: unknown, scriptsDir: string, selections: unknown): Promise<BuildBriefResult> {
  if (typeof projectPath !== 'string' || projectPath === '') return fail('Open a project first.')
  const parsed = parseSelections(selections)
  if (!parsed.ok) return fail(parsed.error)

  const candidates = await getBriefCandidates(projectPath, scriptsDir)
  if (!candidates.ok) return fail(candidates.error)
  if (!candidates.hasData) return fail(`The brief cannot be built yet. ${candidates.notes.join(' ')}`.trim())
  const refusal = checkAgainstCandidates(parsed.value, candidates)
  if (refusal) return fail(refusal)

  const force = parsed.value.replaceExisting && candidates.existingBrief
  const args = buildArgs(projectPath, parsed.value, questionIdsForBuild(parsed.value, candidates), force)
  const result = await runBriefScript(scriptsDir, args, BUILD_UNREADABLE)
  return result.ok ? readBuilt(result.raw, projectPath) ?? fail(BUILD_UNREADABLE) : fail(result.error)
}

// --- registration -------------------------------------------------------------------------------

export function registerBriefHandlers(
  ipcMain: Pick<IpcMain, 'handle'>,
  resolvePluginScriptsDir: () => Promise<string | null>,
): void {
  ipcMain.handle('studio:getBriefCandidates', async (_event, projectPath: unknown) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? getBriefCandidates(projectPath, scriptsDir) : fail(NO_PLUGIN)
  })
  ipcMain.handle('studio:buildBrief', async (_event, projectPath: unknown, selections: unknown) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? buildBrief(projectPath, scriptsDir, selections) : fail(NO_PLUGIN)
  })
}
