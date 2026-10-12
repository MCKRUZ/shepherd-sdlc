import { beforeEach, describe, expect, it, vi } from 'vitest'
import { join } from 'node:path'

vi.mock('../electron/main/project', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../electron/main/project')>()),
  runPluginScript: vi.fn(),
}))

import { getBriefCandidates, registerBriefHandlers } from '../electron/main/briefForm'
import { runPluginScript } from '../electron/main/project'
import { entry, FAILURES, json, PLUGIN_CANDIDATES, PROJECT, SCRIPTS, withCandidates } from './briefPluginFixtures'

const run = vi.mocked(runPluginScript)
const STATE = join(PROJECT, '.sdlc', 'state.yaml')

describe('getBriefCandidates', () => {
  beforeEach(() => { run.mockReset() })

  it('runs exactly workshop_brief.py candidates --state <state> --json, once', async () => {
    run.mockResolvedValue(json(PLUGIN_CANDIDATES))
    await getBriefCandidates(PROJECT, SCRIPTS)
    expect(run).toHaveBeenCalledTimes(1)
    expect(run).toHaveBeenCalledWith(SCRIPTS, 'workshop_brief.py', ['candidates', '--state', STATE, '--json'])
  })

  it('maps the plugin\'s lists and limits into the shape the form uses', async () => {
    run.mockResolvedValue(json(PLUGIN_CANDIDATES))
    const r = await getBriefCandidates(PROJECT, SCRIPTS)
    expect(r).toMatchObject({
      ok: true, hasData: true, notes: [], standingDecisions: 2, existingBrief: false, provisionalIds: false,
      limits: { contradictions: 5, questions: 12, decisions: [3, 5], loadBearing: [3, 5] },
    })
    if (!r.ok) throw new Error('unreachable')
    expect(r.contradictions).toHaveLength(7)
    expect(r.contradictions[0]).toEqual({
      id: 'CON-01', title: 'Contradiction 1', severity: 'blocks-outcome', question: 'Which is right, 1?', recommended: true,
      sources: [{ side: 'A', document: 'DOC-001 s1', quote: 'one thing' }, { side: 'B', document: 'DOC-002 s2', quote: 'another thing' }],
    })
    expect(r.contradictions[2].recommended).toBe(false)
    expect(r.questions[1]).toEqual({ id: 'Q-02', question: 'How many claims per month are re-keyed?', block: 'Problem', route: 'pre-workshop' })
    expect(r.documents[0]).toEqual({ id: 'DOC-001', filename: 'doc-001.pdf', topics: 'goals, scope' })
  })

  it('passes has_data false through as no form: the plugin\'s notes and empty lists, never invented content', async () => {
    const notes = ['contradiction-list.md not found: run the document analysis first.']
    run.mockResolvedValue(json(withCandidates({ has_data: false, notes })))
    const r = await getBriefCandidates(PROJECT, SCRIPTS)
    expect(r).toMatchObject({ ok: true, hasData: false, notes, contradictions: [], questions: [], documents: [] })
  })

  it('reports an existing brief and provisional ids as the plugin says them', async () => {
    run.mockResolvedValue(json(withCandidates({ existing_brief: true, provisional_ids: true })))
    expect(await getBriefCandidates(PROJECT, SCRIPTS)).toMatchObject({ ok: true, existingBrief: true, provisionalIds: true })
  })

  describe.each(FAILURES)('when %s', (_name, failure) => {
    it('is one plain line and no counts', async () => {
      run.mockResolvedValue(failure())
      const r = await getBriefCandidates(PROJECT, SCRIPTS)
      expect(r.ok).toBe(false)
      if (r.ok) return
      expect(r.error.length).toBeGreaterThan(0)
      expect(r.error).not.toMatch(/\r|\n/)
      expect(r).not.toHaveProperty('contradictions')
    })
  })

  it('shows the plugin\'s own Error line, with an absolute path reduced to its file name', async () => {
    const path = join(PROJECT, '.sdlc', 'state.yaml')
    run.mockResolvedValue(entry('', 1, `Error: state file not found: ${path}\n`))
    const r = await getBriefCandidates(PROJECT, SCRIPTS)
    expect(r).toEqual({ ok: false, error: 'state file not found: state.yaml' })
  })

  it.each([
    ['a field of a contradiction is missing', { contradictions: [{ id: 'CON-01' }] }],
    ['the limits are missing', { limits: undefined }],
    ['a limit range is not two numbers', { limits: { ...PLUGIN_CANDIDATES.limits, decisions: [3] } }],
    ['has_data is not a boolean', { has_data: 'yes' }],
    ['a question has no route', { questions: [{ id: 'Q-01', question: 'x?', block: 'b' }] }],
  ])('refuses a plugin answer where %s, rather than showing half a form', async (_name, change) => {
    run.mockResolvedValue(json(withCandidates(change)))
    const r = await getBriefCandidates(PROJECT, SCRIPTS)
    expect(r.ok).toBe(false)
  })
})

describe('registerBriefHandlers', () => {
  const handlers = new Map<string, (...args: unknown[]) => unknown>()
  const ipc = { handle: (channel: string, fn: (...args: unknown[]) => unknown) => { handlers.set(channel, fn) } }
  beforeEach(() => { run.mockReset(); handlers.clear() })

  it('registers the two channels the preload exposes', () => {
    registerBriefHandlers(ipc, async () => SCRIPTS)
    expect([...handlers.keys()].sort()).toEqual(['studio:buildBrief', 'studio:getBriefCandidates'])
  })

  it('answers "plugin scripts not found" for both when the plugin cannot be located, and starts nothing', async () => {
    registerBriefHandlers(ipc, async () => null)
    const none = { ok: false, error: 'Shepherd plugin scripts not found' }
    expect(await handlers.get('studio:getBriefCandidates')!({}, PROJECT)).toEqual(none)
    expect(await handlers.get('studio:buildBrief')!({}, PROJECT, {})).toEqual(none)
    expect(run).not.toHaveBeenCalled()
  })

  it('reads candidates through the located plugin', async () => {
    run.mockResolvedValue(json(PLUGIN_CANDIDATES))
    registerBriefHandlers(ipc, async () => SCRIPTS)
    expect(await handlers.get('studio:getBriefCandidates')!({}, PROJECT)).toMatchObject({ ok: true, hasData: true })
  })

  it('refuses a project path that is not a string', async () => {
    registerBriefHandlers(ipc, async () => SCRIPTS)
    const r = await handlers.get('studio:getBriefCandidates')!({}, 42) as { ok: boolean }
    expect(r.ok).toBe(false)
    expect(run).not.toHaveBeenCalled()
  })
})
