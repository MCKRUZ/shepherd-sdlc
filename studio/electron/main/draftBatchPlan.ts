// What a batch job (spec 0029) is allowed to be asked, and the words it is asked in. Everything here runs
// BEFORE any process starts, and reads only the catalogue and the summaries folder: a request that fails
// any check is refused with one line and costs nothing.
//
// Nothing from the renderer reaches this file except the kind. The document ids come from the project's
// own `catalog.json`, and a document's name is shown to the person but never put into a prompt or a path
// as it stands: a prompt carries an id (checked against a fixed shape) and absolute paths, and a path is
// built from a slug that can hold only lower-case letters, digits and dashes (see agentRun.ts for why).

import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { hasSdlcProject } from './project'
import type { BatchKind } from '../../shared/types'

export const BATCH_KINDS: readonly BatchKind[] = ['summarise', 'analyse']

const DOC_ID = /^DOC-\d{3,}$/
/** The marker `intake_registry.py` treats as "this summary was never filled in". */
const UNFILLED = '${'
const NO_SAVING = 'You cannot save files in this session: do not try.'

export const NOT_LOCKED = 'Lock the document ids first'
export const NOTHING_TO_SUMMARISE = 'Every document already has a summary'
export const TOO_FEW_SUMMARIES = 'Summarise at least two documents first'

export type Refusal = { error: string }

export interface PlannedDocument {
  id: string
  /** Shown to the person only; it never goes into a prompt. */
  filename: string
  /** Repo-relative file Keep would write. */
  target: string
}

export interface BatchPlan {
  kind: BatchKind
  documents: PlannedDocument[]
  /** The prompts, one per run: a summary per document, or the single analysis. */
  prompts: string[]
}

const refuse = (error: string): Refusal => ({ error })
const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

export const intakeFolder = (project: string) => join(project, '.sdlc', 'context', 'intake')
export const catalogPath = (project: string) => join(intakeFolder(project), 'catalog.json')

// --- the catalogue ---------------------------------------------------------------------------

interface CatalogDocument {
  id: string
  filename: string
}

interface Catalogue {
  locked: boolean
  /** Priority order first, then the rest by id; skipped documents already removed. */
  documents: CatalogDocument[]
}

function readJson(path: string): unknown {
  try {
    return JSON.parse(readFileSync(path, 'utf-8'))
  } catch {
    return null
  }
}

function filenameOf(doc: Record<string, unknown>): string {
  if (typeof doc.filename === 'string' && doc.filename) return doc.filename
  return typeof doc.source_path === 'string' ? doc.source_path.replace(/\\/g, '/').split('/').pop() ?? '' : ''
}

const stringList = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [])

/** The same order `intake_registry.ordered_documents` uses, less the skipped. An entry whose id is not a
 * `DOC-NNN` is dropped here, so nothing but a well-formed id can ever reach a prompt or a path. */
function readCatalogue(project: string): Catalogue | null {
  const raw = readJson(catalogPath(project))
  if (!isRecord(raw) || !Array.isArray(raw.documents)) return null
  const byId = new Map<string, CatalogDocument>()
  for (const entry of raw.documents) {
    if (!isRecord(entry) || typeof entry.doc_id !== 'string' || !DOC_ID.test(entry.doc_id) || byId.has(entry.doc_id)) continue
    byId.set(entry.doc_id, { id: entry.doc_id, filename: filenameOf(entry) })
  }
  const priority = stringList(raw.priority_order).filter((id) => byId.has(id))
  const first = [...new Set(priority)]
  const rest = [...byId.keys()].filter((id) => !first.includes(id)).sort()
  const skipped = new Set(stringList(raw.skipped))
  return {
    locked: raw.locked === true,
    documents: [...first, ...rest].filter((id) => !skipped.has(id)).map((id) => byId.get(id) as CatalogDocument),
  }
}

// --- summaries on disk -----------------------------------------------------------------------

/** The first `DOC-NNN-*.md` in the folder by name: the file `intake_registry.find_summary` looks at. */
function summaryFile(project: string, id: string): string | null {
  try {
    return readdirSync(intakeFolder(project)).filter((n) => n.startsWith(`${id}-`) && n.endsWith('.md')).sort()[0] ?? null
  } catch {
    return null
  }
}

/** Filled means what `find_summary` means by it: the file is there and holds no `${` placeholder. */
function isFilled(project: string, file: string): boolean {
  try {
    return !readFileSync(join(intakeFolder(project), file), 'utf-8').includes(UNFILLED)
  } catch {
    return false
  }
}

export function hasFilledSummary(project: string, id: string): boolean {
  const file = summaryFile(project, id)
  return file !== null && isFilled(project, file)
}

/** Lower-case, runs of anything but letters and digits made one dash, dashes trimmed from the ends. */
export function slugOf(filename: string): string {
  const stem = filename.replace(/\.[^./\\]*$/, '')
  return stem.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'document'
}

/** Where Keep would write a document's summary. A summary file that is there but never filled in is
 * replaced where it is, so the folder never holds two files for one id (the registry reads the first). */
export function summaryTarget(project: string, doc: CatalogDocument): string {
  const there = summaryFile(project, doc.id)
  const name = there !== null && /^DOC-\d+-[a-z0-9-]+\.md$/.test(there) ? there : `${doc.id}-${slugOf(doc.filename)}.md`
  return `.sdlc/context/intake/${name}`
}

// --- the prompts -----------------------------------------------------------------------------

export const ANALYSIS_MARKERS = {
  contradictions: '=== FILE: contradiction-list.md ===',
  questions: '=== FILE: question-list.md ===',
  end: '=== END ===',
} as const

export function summarisePrompt(project: string, id: string): string {
  return `Summarise the catalog document ${id} (look up its source path in ${catalogPath(project)}) exactly as your instructions describe. `
    + `${NO_SAVING} Reply with ONLY the complete markdown text of the summary file, starting at its first --- line.`
}

export function analysePrompt(project: string): string {
  const folder = intakeFolder(project)
  return `Analyse the intake corpus of this project as your instructions describe, reading ${join(folder, 'index.md')}, `
    + `${catalogPath(project)} and the summaries in ${folder}. ${NO_SAVING} `
    + 'Reply with ONLY the two documents, each introduced by an exact marker line, in this order and nothing else: '
    + `a line ${ANALYSIS_MARKERS.contradictions}, the full markdown of contradiction-list.md, `
    + `a line ${ANALYSIS_MARKERS.questions}, the full markdown of question-list.md, and a final line ${ANALYSIS_MARKERS.end}.`
}

// --- the plan --------------------------------------------------------------------------------

function planSummarise(project: string, catalogue: Catalogue): BatchPlan | Refusal {
  const needing = catalogue.documents.filter((d) => !hasFilledSummary(project, d.id))
  if (needing.length === 0) return refuse(NOTHING_TO_SUMMARISE)
  return {
    kind: 'summarise',
    documents: needing.map((d) => ({ id: d.id, filename: d.filename, target: summaryTarget(project, d) })),
    prompts: needing.map((d) => summarisePrompt(project, d.id)),
  }
}

function planAnalyse(project: string, catalogue: Catalogue): BatchPlan | Refusal {
  const summarised = catalogue.documents.filter((d) => hasFilledSummary(project, d.id))
  if (summarised.length < 2) return refuse(TOO_FEW_SUMMARIES)
  return {
    kind: 'analyse',
    documents: summarised.map((d) => ({ id: d.id, filename: d.filename, target: summaryTarget(project, d) })),
    prompts: [analysePrompt(project)],
  }
}

/** The whole gate in front of a batch. Returns the plan, or the one line that says why not. */
export function planBatch(projectPath: string, kind: unknown): BatchPlan | Refusal {
  if (typeof projectPath !== 'string' || !hasSdlcProject(projectPath)) return refuse('Open a project first.')
  if (typeof kind !== 'string' || !BATCH_KINDS.includes(kind as BatchKind)) return refuse('That is not a job Shepherd can run.')
  const catalogue = readCatalogue(projectPath)
  if (!catalogue || !catalogue.locked) return refuse(NOT_LOCKED)
  return kind === 'summarise' ? planSummarise(projectPath, catalogue) : planAnalyse(projectPath, catalogue)
}
