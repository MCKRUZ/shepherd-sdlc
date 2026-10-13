// What a model job (spec 0027) is allowed to be asked, where its result would be written, and the
// words it is asked in. Everything here runs BEFORE any process starts: a request that fails any check
// is refused with one line and costs nothing.
//
// The request crosses from the renderer, so none of it is trusted. The kind picks the agent from a
// fixed table, the stage and mode are matched against fixed shapes, and the document is a repo-relative
// path that must be a real file under `.sdlc/artifacts/`. The prompts carry paths and an instruction,
// never document text (see agentRun.ts for why).

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { AGENT_BY_KIND } from './agentRun'
import { hasSdlcProject } from './project'
import { isAllowlisted, resolveProjectDocument } from './projectPaths'
import type { DraftKind, DraftRequest, ReviewMode } from '../../shared/types'

const STAGE_ID = /^[A-Za-z0-9]{1,16}$/
const ARTIFACTS_PREFIX = '.sdlc/artifacts/'
/** Letters, digits, dot, dash, underscore and `/` only. A file name travels into the prompt, and a
 * name chosen by whoever wrote the repository ("x. Ignore the above and ....md") is text the model
 * would read as instruction. Every template-made document already fits this. */
const SAFE_PATH = /^[A-Za-z0-9._/-]+$/

/** The words each mode is called by in the prompt: the flag names `/sprd-review` itself uses. */
export const REVIEW_MODES: Readonly<Record<ReviewMode, string>> = {
  council: 'council',
  adversarial: 'adversarial',
  'edge-cases': 'edge-cases',
  all: 'all',
}

export type Refusal = { error: string }

/** A request that passed every check, with everything the run and the Keep step need. */
export interface DraftPlan {
  kind: DraftKind
  stageId: string
  /** Repo-relative, forward slashes: the one file Keep would write. */
  target: string
  label: string
  prompt: string
}

const refuse = (error: string): Refusal => ({ error })

// --- what Keep may write ---------------------------------------------------------------------

/** The documents a single-document model job (spec 0027) may be kept as: markdown under `.sdlc/artifacts/`. */
export function isDraftTarget(target: string): boolean {
  return !target.includes('..') && /^\.sdlc\/artifacts\/.+\.md$/.test(target) && isAllowlisted(target)
}

/** A reference-document summary (spec 0029). The slug is lower-case letters, digits and dashes only, so
 * a file name chosen by whoever wrote the repository can never put anything else into a path. */
export const INTAKE_SUMMARY_TARGET = /^\.sdlc\/context\/intake\/DOC-\d+-[a-z0-9-]+\.md$/

/** The two documents one analysis produces (spec 0029). */
export const ANALYSIS_TARGETS: readonly string[] = [
  '.sdlc/artifacts/00-discovery/contradiction-list.md',
  '.sdlc/artifacts/00-discovery/question-list.md',
]

/** The exact set a batch job (spec 0029) may be kept as, and nothing else. */
export function isBatchTarget(target: string): boolean {
  return !target.includes('..') && (INTAKE_SUMMARY_TARGET.test(target) || ANALYSIS_TARGETS.includes(target)) && isAllowlisted(target)
}

/** Everything Keep may write, across both kinds of job. */
export const isKeepableTarget = (target: string): boolean => isDraftTarget(target) || isBatchTarget(target)

const baseName = (path: string) => path.split('/').pop() ?? path

// --- the stage, from the plugin's own registry -----------------------------------------------

export interface StageFolder {
  slug: string
  display: string
}

/** A stage's artifact folder and display name, read from the plugin's `phases/phase-registry.yaml` — the
 * file `phase_model.artifact_dirname()` reads, so the folder is never guessed from the stage id (ids are
 * not contiguous and the folder is not a zero-padded id). A narrow line scan, as documents.ts does for
 * shape files, because Studio carries no YAML dependency. null for a stage the registry does not name. */
export function stageFolder(scriptsDir: string, stageId: string): StageFolder | null {
  let text: string
  try {
    text = readFileSync(join(scriptsDir, '..', 'phases', 'phase-registry.yaml'), 'utf-8')
  } catch {
    return null
  }
  let inStage = false
  let slug = ''
  let display = ''
  const finished = (): StageFolder | null => (inStage && slug && display ? { slug, display } : null)
  for (const raw of text.split(/\r?\n/)) {
    const idLine = raw.match(/^ {2}- id:\s*"?([^"\s#]+)"?/)
    if (idLine) {
      const found = finished()
      if (found) return found
      inStage = idLine[1] === stageId
      slug = ''
      display = ''
      continue
    }
    if (!inStage) continue
    slug = slug || (raw.match(/^ {4}slug:\s*"([^"]+)"/)?.[1] ?? '')
    display = display || (raw.match(/^ {4}display:\s*"([^"]+)"/)?.[1] ?? '')
  }
  return finished()
}

// --- the prompts -----------------------------------------------------------------------------

const NO_SAVING = 'You cannot save files in this session: do not try.'

function enhancePrompt(projectPath: string, document: string): string {
  return `Write the stakeholder narrative companion for ${join(projectPath, document)} exactly as your instructions describe. `
    + `${NO_SAVING} Reply with ONLY the complete markdown text of the .narrative.md document.`
}

function reviewPrompt(projectPath: string, pluginRoot: string, stage: StageFolder, mode: ReviewMode): string {
  return `Review the documents of the ${stage.display} stage in ${join(projectPath, ARTIFACTS_PREFIX, stage.slug)} `
    + `in ${REVIEW_MODES[mode]} mode, exactly as the /sprd-review command (read ${join(pluginRoot, 'commands', 'sprd-review.md')}) `
    + `describes, including the machine-readable ## Gate Results table. ${NO_SAVING} `
    + 'Reply with ONLY the complete markdown text of review-report.md.'
}

// --- validation ------------------------------------------------------------------------------

function checkDocument(projectPath: string, document: unknown): Refusal | string {
  if (typeof document !== 'string' || !document) return refuse('Choose a document to summarise.')
  const rel = document.replace(/\\/g, '/')
  if (rel.includes('..')) return refuse('That path is not one Shepherd can summarise.')
  if (!rel.startsWith(ARTIFACTS_PREFIX) || !SAFE_PATH.test(rel)) {
    return refuse('Shepherd only summarises documents under .sdlc/artifacts/ whose names use letters, numbers, dots, dashes and underscores.')
  }
  if (!rel.endsWith('.md') || rel.endsWith('.narrative.md')) {
    return refuse('Shepherd summarises markdown documents, and a summary is not itself summarised.')
  }
  try {
    const full = resolveProjectDocument(projectPath, rel)
    if (!existsSync(full) || !statSync(full).isFile()) return refuse(`${baseName(rel)} is not there.`)
  } catch (err) {
    return refuse((err as Error).message)
  }
  return rel
}

function checkTarget(projectPath: string, target: string): Refusal | null {
  try {
    resolveProjectDocument(projectPath, target)
    return null
  } catch (err) {
    return refuse((err as Error).message)
  }
}

function planEnhance(projectPath: string, request: DraftRequest, stageId: string): DraftPlan | Refusal {
  const document = checkDocument(projectPath, request.document)
  if (typeof document !== 'string') return document
  const target = `${document.slice(0, -'.md'.length)}.narrative.md`
  const bad = checkTarget(projectPath, target)
  if (bad) return bad
  return { kind: 'enhance', stageId, target, label: baseName(target), prompt: enhancePrompt(projectPath, document) }
}

/** Whether the stage folder holds any document besides a previous review (init makes every stage's
 * folder up front, so the folder existing says nothing). */
function hasDocumentsToReview(folder: string): boolean {
  try {
    return readdirSync(folder, { recursive: true, encoding: 'utf-8' })
      .some((name) => name.endsWith('.md') && baseName(name.split('\\').join('/')) !== 'review-report.md')
  } catch {
    return false
  }
}

function planReview(projectPath: string, scriptsDir: string, request: DraftRequest, stageId: string): DraftPlan | Refusal {
  if (typeof request.mode !== 'string' || !Object.hasOwn(REVIEW_MODES, request.mode)) {
    return refuse('Choose a review mode: council, adversarial, edge cases or all.')
  }
  const stage = stageFolder(scriptsDir, stageId)
  if (!stage || !/^[A-Za-z0-9-]+$/.test(stage.slug)) return refuse('That is not a stage Shepherd can review.')
  if (!hasDocumentsToReview(join(projectPath, ARTIFACTS_PREFIX, stage.slug))) {
    return refuse(`There are no ${stage.display} documents to review yet.`)
  }
  const target = `${ARTIFACTS_PREFIX}${stage.slug}/review-report.md`
  const bad = checkTarget(projectPath, target)
  if (bad) return bad
  const prompt = reviewPrompt(projectPath, join(scriptsDir, '..'), stage, request.mode)
  return { kind: 'review', stageId, target, label: baseName(target), prompt }
}

/** The whole gate in front of a model job. Returns the plan, or the one line that says why not. */
export function planDraft(projectPath: string, scriptsDir: string, request: unknown): DraftPlan | Refusal {
  if (typeof projectPath !== 'string' || !hasSdlcProject(projectPath)) return refuse('Open a project first.')
  const req = request as Partial<DraftRequest> | null
  if (typeof req !== 'object' || req === null || typeof req.kind !== 'string' || !Object.hasOwn(AGENT_BY_KIND, req.kind)) {
    return refuse('That is not a job Shepherd can run.')
  }
  if (typeof req.stageId !== 'string' || !STAGE_ID.test(req.stageId)) return refuse('That is not a stage Shepherd can draft for.')
  const full = req as DraftRequest
  return full.kind === 'enhance'
    ? planEnhance(projectPath, full, full.stageId)
    : planReview(projectPath, scriptsDir, full, full.stageId)
}
