/** The whole model-runner path through its IPC handlers (spec 0027): the five channels the preload
 * invokes, a run on the stand-in `claude`, the candidate, and Keep, against a real project. The channel
 * names are asserted against the preload source so the two cannot drift apart. */

import { readFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { registerDraftHandlers, resetDraftStateForTests } from '../electron/main/draftDocuments'
import type { DraftState, KeepDraftResult, StartDraftResult } from '../shared/types'
import { fakeClaude, makeProject, NARRATIVE_REL, SOURCE_REL } from './draftHarness'
import { requirePlugin } from './pluginRoot'

const PLUGIN = requirePlugin(__dirname)

type Handler = (event: unknown, ...args: unknown[]) => unknown

function register(scriptsDir: string | null, launch?: ReturnType<typeof fakeClaude>['launch']) {
  const handlers = new Map<string, Handler>()
  const sent: Array<{ channel: string; payload: unknown }> = []
  registerDraftHandlers(
    { handle: (channel: string, fn: Handler) => { handlers.set(channel, fn) } } as never,
    async () => scriptsDir,
    (channel, payload) => { sent.push({ channel, payload }) },
    () => undefined,
    launch,
  )
  const call = <T>(channel: string, ...args: unknown[]) => handlers.get(channel)!({}, ...args) as Promise<T>
  return { handlers, sent, call }
}

describe('registerDraftHandlers', () => {
  beforeEach(() => resetDraftStateForTests())

  it('registers exactly the channels the preload invokes, and pushes progress on the preload\'s channel', () => {
    const preload = readFileSync(join(__dirname, '..', 'electron', 'preload', 'index.ts'), 'utf-8')
    const invoked = [...preload.matchAll(/ipcRenderer\.invoke\('(studio:(?:start|cancel|get|keep|discard)Draft\w*)'/g)].map((m) => m[1]).sort()
    expect(invoked).toEqual(['studio:cancelDraft', 'studio:discardDraft', 'studio:getDraftState', 'studio:keepDraft', 'studio:startDraft'])
    expect([...register('x').handlers.keys()].sort()).toEqual(invoked)
    expect(preload).toContain("ipcRenderer.on('studio:draftProgress'")
  })

  it('says the plugin is missing, on every channel that needs it, and starts nothing', async () => {
    const fake = fakeClaude('success')
    const { call } = register(null, fake.launch)
    const missing = { ok: false, error: 'Shepherd plugin scripts not found' }
    expect(await call('studio:startDraft', 'C:/p', { kind: 'enhance', stageId: '1', document: SOURCE_REL })).toEqual(missing)
    expect(await call('studio:keepDraft', 'C:/p', 'j', 'Matt K')).toEqual(missing)
    expect(await call('studio:discardDraft', 'C:/p', 'j', 'Matt K')).toEqual(missing)
    expect(fake.hasRun()).toBe(false)
  })
})

describe.skipIf(!PLUGIN.available)('start, read the state, keep: the whole path', () => {
  let project = ''
  beforeEach(() => {
    resetDraftStateForTests()
    project = makeProject(PLUGIN)
  })
  afterEach(() => rmSync(project, { recursive: true, force: true }))

  it('runs a summary on the stand-in, holds it as a candidate, and writes it only on Keep', async () => {
    const fake = fakeClaude('slow', { text: '# In plain words\n\nIt works.' })
    const { call, sent } = register(PLUGIN.scriptsDir, fake.launch)

    const started = await call<StartDraftResult>('studio:startDraft', project, { kind: 'enhance', stageId: '1', document: SOURCE_REL })
    if (!started.ok) throw new Error(started.error)
    expect(started.candidate).toMatchObject({ target: NARRATIVE_REL, costUsd: 0.12, replacesExisting: false, text: '# In plain words\n\nIt works.' })

    const state = await call<DraftState>('studio:getDraftState', project)
    expect(state).toEqual({ running: null, candidate: started.candidate })
    expect(() => readFileSync(join(project, NARRATIVE_REL))).toThrow() // nothing on disk yet

    const progress = sent.filter((s) => s.channel === 'studio:draftProgress')
    expect(progress.length).toBeGreaterThan(0)
    expect(progress[0].payload).toMatchObject({ jobId: started.candidate.jobId, elapsedMs: expect.any(Number) })

    const kept = await call<KeepDraftResult>('studio:keepDraft', project, started.candidate.jobId, 'Matt K')
    expect(kept).toEqual({ ok: true, written: NARRATIVE_REL })
    expect(readFileSync(join(project, NARRATIVE_REL), 'utf-8')).toBe('# In plain words\n\nIt works.\n')
    expect(await call<DraftState>('studio:getDraftState', project)).toEqual({ running: null, candidate: null })
  })

  it('cancels a running job through the cancel channel', async () => {
    const fake = fakeClaude('hang')
    const { call } = register(PLUGIN.scriptsDir, fake.launch)

    const run = call<StartDraftResult>('studio:startDraft', project, { kind: 'enhance', stageId: '1', document: SOURCE_REL })
    for (let i = 0; i < 100 && !fake.hasRun(); i++) await new Promise((r) => setTimeout(r, 50))
    expect((await call<DraftState>('studio:getDraftState', project)).running?.label).toBe('requirements.narrative.md')

    expect(await call('studio:cancelDraft')).toEqual({ ok: true })
    expect(await run).toMatchObject({ ok: false, cancelled: true })
    expect(await call<DraftState>('studio:getDraftState', project)).toEqual({ running: null, candidate: null })
  })
})
