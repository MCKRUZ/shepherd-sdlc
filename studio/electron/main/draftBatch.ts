// Model jobs that produce SEVERAL results at once (spec 0029): one summary per reference document, or the
// two lists of one analysis. It extends spec 0027's machinery rather than adding a path of its own:
//
//   * what Claude may do while a run is going is agentRun.ts, unchanged (read-only tools, an isolated
//     working directory, an agent from a fixed table, and no document text in the prompt);
//   * what a person may be asked is draftBatchPlan.ts: the ids come from the project's own locked
//     catalogue, never from the renderer, and a document's name never reaches a prompt or a path;
//   * what reaches the disk is draftKeep.ts, one audited write per result, and only on Keep
//     (draftBatchDecide.ts). Running, cancelling, failing and discarding write nothing to the project.
//
// THREAT MODEL. A reference document is the likeliest file in a project to carry outside text (a vendor's
// PDF, a customer's brief). A model run that read it can be talked into saying anything, so a reply is
// only ever TEXT that is checked for its shape (draftBatchParse.ts) and shown for a person to keep or
// discard. A batch can also cost real money unattended, so runs go one at a time, the person confirms
// first, the running cost is shown, and Cancel kills the run in progress.

import { randomUUID } from 'node:crypto'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import type { IpcMain } from 'electron'
import { runAgent, type AgentResult } from './agentRun'
import { writeRegistry } from './batchRegistry'
import { parseAnalysis, parseSummary } from './draftBatchParse'
import { planBatch, type BatchPlan, type PlannedDocument } from './draftBatchPlan'
import { discardBatch, keepBatch } from './draftBatchDecide'
import {
  activeBatch, change, entryFor, getBatchState, notify, projectKey, register, sameProject,
  type BatchDeps, type BatchEntry,
} from './draftBatchState'
import { ANALYSIS_TARGETS } from './draftTargets'
import { PLUGIN_NOT_FOUND } from '../../shared/pluginId'
import type {
  BatchCandidate, BatchJob, BatchKind, KeepBatchResult, PreviewBatchResult, RegistryResult, StartBatchResult,
} from '../../shared/types'

export { getBatchState, resetBatchStateForTests } from './draftBatchState'
export { discardBatch, keepBatch } from './draftBatchDecide'
export type { BatchDeps } from './draftBatchState'

const NO_PLUGIN = PLUGIN_NOT_FOUND
const GERUND: Readonly<Record<BatchKind, string>> = { summarise: 'summarising', analyse: 'analysing' }
const ANALYSIS_LABEL = 'Contradictions and open questions'
const labelOf = (doc: PlannedDocument) => `${doc.id} · ${doc.filename}`

// --- preview ---------------------------------------------------------------------------------

/** What a batch would do, for the confirmation. Starts nothing and writes nothing. */
export function previewBatch(projectPath: string, _scriptsDir: string, kind: unknown): PreviewBatchResult {
  const plan = planBatch(projectPath, kind)
  if ('error' in plan) return { ok: false, error: plan.error }
  return { ok: true, kind: plan.kind, documents: plan.documents.map((d) => ({ id: d.id, filename: d.filename })) }
}

// --- starting --------------------------------------------------------------------------------

function newEntry(projectPath: string, plan: BatchPlan, deps: BatchDeps): BatchEntry {
  const job: BatchJob = {
    id: randomUUID(), kind: plan.kind, startedAt: Date.now(), total: plan.prompts.length, done: 0,
    currentLabel: null, costUsd: null, phase: 'running',
  }
  return {
    path: projectPath, key: projectKey(projectPath), job, candidates: [], controller: new AbortController(),
    active: true, deciding: false, send: deps.send, lastPushAt: 0, timer: null,
  }
}

/** Validates, registers the batch and returns at once; the runs go on in the background and every change
 * is pushed through `deps.send`. Nothing is validated by the preview: this runs the same checks again. */
export function startBatch(projectPath: string, scriptsDir: string, kind: unknown, deps: BatchDeps): StartBatchResult {
  const running = activeBatch()
  if (running) return { ok: false, error: `Already running ${GERUND[running.job.kind]}…`, running: running.job }
  const plan = planBatch(projectPath, kind)
  if ('error' in plan) return { ok: false, error: plan.error }
  const previous = entryFor(projectPath)
  if (previous?.candidates.some((c) => c.status === 'ready')) {
    return { ok: false, error: 'Keep or discard the waiting results first' }
  }

  const entry = newEntry(projectPath, plan, deps)
  if (previous?.timer) clearTimeout(previous.timer)
  register(entry)
  notify(entry, true)
  void runPlan(entry, plan, scriptsDir, deps)
  return { ok: true, job: entry.job }
}

/** Stops after the run in progress, killing it, and starts no more. Candidates already finished stay. When
 * a project is named, only that project's batch is stopped. */
export function cancelBatch(projectPath?: string): { ok: boolean; error?: string } {
  const running = activeBatch()
  if (!running) return { ok: true }
  if (projectPath !== undefined && !sameProject(running.key, projectPath)) return { ok: false, error: 'That batch belongs to another project' }
  running.controller.abort()
  if (running.job.phase === 'running') change(running, { job: { ...running.job, phase: 'cancelled', currentLabel: null } }, true)
  return { ok: true }
}

// --- running ---------------------------------------------------------------------------------

/** Never 0 by invention: with no reported cost the total stays null. Rounded to the micro-dollar, so
 * 0.10 + 0.12 + 0.08 is 0.30 and not 0.30000000000000004. */
function addCost(total: number | null, cost: number | null): number | null {
  return cost === null ? total : Math.round(((total ?? 0) + cost) * 1e6) / 1e6
}

const cancelled = (entry: BatchEntry) => entry.controller.signal.aborted

function runOne(entry: BatchEntry, plan: BatchPlan, prompt: string, scriptsDir: string, deps: BatchDeps): Promise<AgentResult> {
  return runAgent({
    kind: plan.kind, prompt, projectPath: entry.path, pluginRoot: resolve(scriptsDir, '..'),
    claudePath: deps.claudePath, signal: entry.controller.signal, launch: deps.launch,
  })
}

/** Records that a run ended: one more done, the cost so far, and its candidates. */
function finishRun(entry: BatchEntry, result: AgentResult, added: readonly BatchCandidate[]): void {
  const cost = result.ok ? result.costUsd : null
  change(entry, {
    job: { ...entry.job, done: entry.job.done + 1, costUsd: addCost(entry.job.costUsd, cost) },
    candidates: [...entry.candidates, ...added],
  })
}

function startRun(entry: BatchEntry, label: string): void {
  change(entry, { job: { ...entry.job, currentLabel: label } })
}

function summaryCandidate(project: string, doc: PlannedDocument, result: AgentResult): BatchCandidate {
  const base = { id: doc.id, target: doc.target, label: labelOf(doc), replacesExisting: existsSync(resolve(project, doc.target)) }
  if (!result.ok) return { ...base, status: 'failed', text: '', error: result.error }
  const parsed = parseSummary(result.text)
  return parsed.ok
    ? { ...base, status: 'ready', text: parsed.value }
    : { ...base, status: 'failed', text: '', error: parsed.error }
}

function analysisCandidates(project: string, result: AgentResult): BatchCandidate[] {
  const failure = (error: string): BatchCandidate[] => [{
    id: 'analysis', target: '', label: 'Analysis', status: 'failed', text: '', error, replacesExisting: false,
  }]
  if (!result.ok) return failure(result.error)
  const parsed = parseAnalysis(result.text)
  if (!parsed.ok) return failure(parsed.error)
  const texts = [parsed.value.contradictions, parsed.value.questions]
  return ANALYSIS_TARGETS.map((target, i): BatchCandidate => ({
    id: target.split('/').pop()!.replace(/\.md$/, ''), target, label: target.split('/').pop()!, status: 'ready',
    text: texts[i], replacesExisting: existsSync(resolve(project, target)),
  }))
}

async function runSummaries(entry: BatchEntry, plan: BatchPlan, scriptsDir: string, deps: BatchDeps): Promise<void> {
  for (let i = 0; i < plan.documents.length && !cancelled(entry); i++) {
    const doc = plan.documents[i]
    startRun(entry, labelOf(doc))
    const result = await runOne(entry, plan, plan.prompts[i], scriptsDir, deps)
    if (!result.ok && result.cancelled) return
    finishRun(entry, result, [summaryCandidate(entry.path, doc, result)])
  }
}

async function runAnalysis(entry: BatchEntry, plan: BatchPlan, scriptsDir: string, deps: BatchDeps): Promise<void> {
  startRun(entry, ANALYSIS_LABEL)
  const result = await runOne(entry, plan, plan.prompts[0], scriptsDir, deps)
  if (!result.ok && result.cancelled) return
  finishRun(entry, result, analysisCandidates(entry.path, result))
}

async function runPlan(entry: BatchEntry, plan: BatchPlan, scriptsDir: string, deps: BatchDeps): Promise<void> {
  try {
    await (plan.kind === 'summarise' ? runSummaries(entry, plan, scriptsDir, deps) : runAnalysis(entry, plan, scriptsDir, deps))
  } catch {
    // runAgent never throws; if something unforeseen does, the batch still ends rather than hanging.
  } finally {
    // No longer active BEFORE the window hears it is over, so a Keep sent the moment it hears is accepted.
    entry.active = false
    const phase = cancelled(entry) ? 'cancelled' : 'finished'
    change(entry, { job: { ...entry.job, phase, currentLabel: null } }, true)
  }
}

// --- registration ----------------------------------------------------------------------------

const noKeep = (error: string): KeepBatchResult => ({ ok: false, error, kept: [], failed: [], warnings: [] })
const noRegistry = (error: string): RegistryResult => ({
  ok: false, error, documents: 0, summarised: 0, missingSummaries: [], indexTokens: 0, indexBudget: 0,
  indexWithinBudget: false, trimmed: [], registryCreated: false, warnings: [],
})

/** The only thing the rest of the main process needs to know about. Cancelling and reading the state need
 * no plugin script, so they work even when the plugin cannot be found: a running batch must stay stoppable. */
export function registerBatchHandlers(
  ipcMain: Pick<IpcMain, 'handle'>,
  resolvePluginScriptsDir: () => Promise<string | null>,
  sendToWindow: BatchDeps['send'],
  getClaudePath: () => string | undefined,
  /** A test seam; production passes nothing and the real CLI runs. */
  launch?: BatchDeps['launch'],
): void {
  const deps = (): BatchDeps => ({ claudePath: getClaudePath(), send: sendToWindow, launch })

  ipcMain.handle('studio:previewBatch', async (_event, projectPath: string, kind: unknown) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? previewBatch(projectPath, scriptsDir, kind) : { ok: false, error: NO_PLUGIN }
  })
  ipcMain.handle('studio:startBatch', async (_event, projectPath: string, kind: unknown) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? startBatch(projectPath, scriptsDir, kind, deps()) : { ok: false, error: NO_PLUGIN }
  })
  ipcMain.handle('studio:cancelBatch', () => cancelBatch())
  ipcMain.handle('studio:getBatchState', (_event, projectPath: string) => getBatchState(projectPath))
  ipcMain.handle('studio:keepBatch', async (_event, projectPath: string, jobId: string, actor: string, ids?: string[]) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? keepBatch(projectPath, scriptsDir, jobId, actor, ids) : noKeep(NO_PLUGIN)
  })
  ipcMain.handle('studio:discardBatch', async (_event, projectPath: string, jobId: string, actor: string, ids?: string[]) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? discardBatch(projectPath, scriptsDir, jobId, actor, ids) : { ok: false, error: NO_PLUGIN, warnings: [] }
  })
  ipcMain.handle('studio:writeRegistry', async (_event, projectPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? writeRegistry(projectPath, scriptsDir) : noRegistry(NO_PLUGIN)
  })
}
