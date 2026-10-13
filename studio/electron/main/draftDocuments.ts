// Model jobs that produce one whole document, and the Keep / Discard step that follows (spec 0027).
//
// One job at a time, held in module state: the running job, and, after it finishes, the candidate
// waiting for a person. Nothing is on disk until Keep (draftKeep.ts). A cancelled or failed run
// leaves nothing at all, neither a file nor a ledger line: there is no draft to record until a run has
// produced one. A candidate that is never decided is dropped when the next job starts, unrecorded: no
// person has said what became of it.
//
// What a job may be asked is draftTargets.ts; what the model may do while it runs is agentRun.ts.

import { randomUUID } from 'node:crypto'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import type { IpcMain } from 'electron'
import { runAgent, type AgentLaunch } from './agentRun'
import { discardCandidate, keepCandidate } from './draftKeep'
import { planDraft, type DraftPlan } from './draftTargets'
import { PLUGIN_NOT_FOUND } from '../../shared/pluginId'
import type {
  DraftCandidate, DraftJob, DraftProgressEvent, DraftState, KeepDraftResult, StartDraftResult,
} from '../../shared/types'

const NO_PLUGIN = PLUGIN_NOT_FOUND
const PROGRESS_CHANNEL = 'studio:draftProgress'
const PROGRESS_INTERVAL_MS = 500

export interface DraftDeps {
  /** The person's configured path to `claude`; the bare name when unset. */
  claudePath?: string
  /** Pushes a live update to the window. */
  send: (channel: string, payload: unknown) => void
  /** A test seam: run a stand-in program instead of the real CLI. Absent in production. */
  launch?: AgentLaunch
}

interface RunningJob {
  job: DraftJob
  controller: AbortController
  /** The project the job was started for (see `sameProject`). */
  project: string
}

let running: RunningJob | null = null
let candidate: DraftCandidate | null = null
/** The project the waiting candidate was drafted from. A candidate holds the text made from THAT
 * project's documents, so it may only be shown to, kept in, or discarded from that project. */
let candidateProject = ''
let deciding = false

/** Two spellings of one folder ("/p" and "/p/.") are the same project; two folders are not. */
const projectKey = (projectPath: string) => resolve(projectPath)
const sameProject = (a: string, b: string) => projectKey(a) === projectKey(b)

/** Test-only: forget any job and candidate. A running job's process is not touched. */
export function resetDraftStateForTests(): void {
  running = null
  candidate = null
  candidateProject = ''
  deciding = false
}

/** What this project has running or waiting. Another project's job and candidate are not shown: after
 * a project switch its screen must not adopt them, or Keep would write them into the wrong project. */
export function getDraftState(projectPath: string): DraftState {
  return {
    running: running && sameProject(running.project, projectPath) ? running.job : null,
    candidate: candidate && sameProject(candidateProject, projectPath) ? candidate : null,
  }
}

export function cancelDraft(): { ok: boolean } {
  running?.controller.abort()
  return { ok: true }
}

function newJob(plan: DraftPlan): DraftJob {
  return { id: randomUUID(), kind: plan.kind, stageId: plan.stageId, target: plan.target, label: plan.label, startedAt: Date.now() }
}

/** Pushes progress about twice a second while the job runs, so the elapsed time ticks even when the
 * model is quiet. Returns what to call with a new activity label, and how to stop. */
function startProgress(job: DraftJob, send: DraftDeps['send']) {
  let activity: string | null = null
  const push = () => {
    const event: DraftProgressEvent = { jobId: job.id, activity, elapsedMs: Date.now() - job.startedAt }
    send(PROGRESS_CHANNEL, event)
  }
  push()
  const timer = setInterval(push, PROGRESS_INTERVAL_MS)
  return {
    setActivity: (label: string) => { activity = label },
    stop: () => clearInterval(timer),
  }
}

/** Validates, then runs the job to its end. Resolves with the candidate (nothing written), or with the
 * one line that says why there is none. */
export async function startDraft(
  projectPath: string, scriptsDir: string, request: unknown, deps: DraftDeps,
): Promise<StartDraftResult> {
  if (running) return { ok: false, error: `Already drafting ${running.job.label}`, running: running.job }
  const plan = planDraft(projectPath, scriptsDir, request)
  if ('error' in plan) return { ok: false, error: plan.error }

  const job = newJob(plan)
  const active: RunningJob = { job, controller: new AbortController(), project: projectKey(projectPath) }
  running = active
  candidate = null
  const progress = startProgress(job, deps.send)

  try {
    const result = await runAgent({
      kind: plan.kind,
      prompt: plan.prompt,
      projectPath,
      pluginRoot: resolve(scriptsDir, '..'),
      claudePath: deps.claudePath,
      signal: active.controller.signal,
      onActivity: progress.setActivity,
      launch: deps.launch,
    })
    if (!result.ok) return { ok: false, error: result.error, ...(result.cancelled ? { cancelled: true } : {}) }
    candidate = {
      jobId: job.id,
      kind: plan.kind,
      stageId: plan.stageId,
      target: plan.target,
      text: result.text,
      costUsd: result.costUsd,
      replacesExisting: existsSync(resolve(projectPath, plan.target)),
    }
    candidateProject = projectKey(projectPath)
    return { ok: true, candidate }
  } finally {
    progress.stop()
    running = null
  }
}

// --- deciding --------------------------------------------------------------------------------

type Waiting = { candidate: DraftCandidate } | { error: string }

function waiting(projectPath: string, jobId: unknown, actor: unknown): Waiting {
  if (typeof actor !== 'string' || !actor.trim()) return { error: 'Say who is deciding, so the record can name them.' }
  if (!candidate || candidate.jobId !== jobId) return { error: 'That draft is no longer waiting.' }
  if (!sameProject(candidateProject, projectPath)) return { error: 'That draft belongs to another project, so it cannot be kept or discarded here.' }
  if (deciding) return { error: 'That draft is already being decided.' }
  return { candidate }
}

/** Runs one decision on the waiting candidate. The candidate is cleared only when the decision ended
 * the draft; a refusal leaves it in place so the person can still discard it. */
async function decide<T extends { ok: boolean }>(
  projectPath: string, jobId: unknown, actor: unknown, act: (c: DraftCandidate, who: string) => Promise<T>,
): Promise<T | { ok: false; error: string }> {
  const found = waiting(projectPath, jobId, actor)
  if ('error' in found) return { ok: false, error: found.error }
  deciding = true
  try {
    const result = await act(found.candidate, (actor as string).trim())
    if (result.ok) candidate = null
    return result
  } finally {
    deciding = false
  }
}

export function keepDraft(projectPath: string, scriptsDir: string, jobId: unknown, actor: unknown): Promise<KeepDraftResult> {
  return decide(projectPath, jobId, actor, (c, who) => keepCandidate(projectPath, scriptsDir, c, who))
}

export function discardDraft(
  projectPath: string, scriptsDir: string, jobId: unknown, actor: unknown,
): Promise<{ ok: boolean; error?: string; warning?: string }> {
  return decide(projectPath, jobId, actor, (c, who) => discardCandidate(projectPath, scriptsDir, c, who))
}

// --- registration ----------------------------------------------------------------------------

/** The only thing index.ts needs to know about. */
export function registerDraftHandlers(
  ipcMain: Pick<IpcMain, 'handle'>,
  resolvePluginScriptsDir: () => Promise<string | null>,
  sendToWindow: DraftDeps['send'],
  getClaudePath: () => string | undefined,
  /** A test seam; production passes nothing and the real CLI runs. */
  launch?: DraftDeps['launch'],
): void {
  ipcMain.handle('studio:startDraft', async (_event, projectPath: string, request: unknown) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return { ok: false, error: NO_PLUGIN }
    return startDraft(projectPath, scriptsDir, request, { claudePath: getClaudePath(), send: sendToWindow, launch })
  })
  ipcMain.handle('studio:cancelDraft', () => cancelDraft())
  ipcMain.handle('studio:getDraftState', (_event, projectPath: string) => getDraftState(projectPath))
  ipcMain.handle('studio:keepDraft', async (_event, projectPath: string, jobId: string, actor: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? keepDraft(projectPath, scriptsDir, jobId, actor) : { ok: false, error: NO_PLUGIN }
  })
  ipcMain.handle('studio:discardDraft', async (_event, projectPath: string, jobId: string, actor: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? discardDraft(projectPath, scriptsDir, jobId, actor) : { ok: false, error: NO_PLUGIN }
  })
}
