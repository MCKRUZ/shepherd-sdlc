/** The decision log through the plugin's verbs (togo-command-center.md §2.4): fixed argv, the
 * owner defaulting to the actor, `--by` always the actor, refusals as the plugin's stderr. */
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../electron/main/project', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../electron/main/project')>()),
  runPluginScript: vi.fn(),
}))
vi.mock('../../electron/main/commandCenter', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../electron/main/commandCenter')>()),
  invalidateCommandCenter: vi.fn(),
}))

import { decideDecision, getDecisions, openDecision } from '../../electron/main/decisions'
import { runPluginScript } from '../../electron/main/project'
import { invalidateCommandCenter } from '../../electron/main/commandCenter'
import { NO_ACTOR } from '../../shared/reasons'
import type { ConsoleEntry } from '../../shared/types'

const run = vi.mocked(runPluginScript)
const PROJECT = '/work/proj'
const SCRIPTS = '/plugin/scripts'
const ACTOR = { name: '@priya-n', source: 'roster' as const }
const entry = (exitCode: number, stdout = '', stderr = ''): ConsoleEntry => ({ id: 'x', command: 'py', args: [], cwd: '', startedAt: '', durationMs: 0, exitCode, stdout, stderr, ok: exitCode === 0 })
const json = (v: unknown, exitCode = 0) => entry(exitCode, JSON.stringify(v))

beforeEach(() => { run.mockReset(); vi.mocked(invalidateCommandCenter).mockClear() })

describe('getDecisions', () => {
  it('reads track_decisions.py --json and returns the report, exists:false included', async () => {
    const report = { total: 0, open: 0, overdue: 0, clock_business_days: 2, open_decisions: [], overdue_decisions: [], log_path: 'p', exists: false }
    run.mockResolvedValue(json(report))
    expect(await getDecisions(PROJECT, SCRIPTS)).toMatchObject({ total: 0, exists: false, openDecisions: [] })
    expect(run).toHaveBeenCalledWith(SCRIPTS, 'track_decisions.py', ['--repo', PROJECT, '--json'])
  })
  it('rejects with the plugin\'s words when the answer is not the report — never an all-zero view', async () => {
    run.mockResolvedValue(entry(1, '', 'Traceback: boom'))
    await expect(getDecisions(PROJECT, SCRIPTS)).rejects.toThrow('Traceback: boom')
  })
})

describe('openDecision', () => {
  it('runs open with the decision, the owner given, --json; reads back the plugin\'s id and dates', async () => {
    run.mockResolvedValue(json({ id: 'DL-04', opened: '2026-10-06', due: '2026-10-08', owner: '@matt', path: '.sdlc/decision-log.md' }))
    const r = await openDecision(PROJECT, SCRIPTS, 'Fail open or closed?', '@matt', ACTOR)
    expect(r).toEqual({ ok: true, id: 'DL-04', opened: '2026-10-06', due: '2026-10-08', owner: '@matt', path: '.sdlc/decision-log.md' })
    expect(run).toHaveBeenCalledWith(SCRIPTS, 'track_decisions.py', ['open', '--repo', PROJECT, '--decision', 'Fail open or closed?', '--owner', '@matt', '--json'])
    expect(invalidateCommandCenter).toHaveBeenCalledWith(PROJECT)
  })
  it('the owner defaults to the actor; no owner and no actor refuses before spawning', async () => {
    run.mockResolvedValue(json({ id: 'DL-05', opened: '', due: '', owner: '@priya-n' }))
    await openDecision(PROJECT, SCRIPTS, 'Q', undefined, ACTOR)
    expect(run.mock.calls[0][2]).toContain('@priya-n')
    expect(await openDecision(PROJECT, SCRIPTS, 'Q', '', null)).toEqual({ ok: false, stderr: NO_ACTOR }); expect(run).toHaveBeenCalledTimes(1)
  })
  it('a refusal (exit 1) is the plugin\'s stderr', async () => {
    run.mockResolvedValue(entry(1, '', 'Error: no decision table'))
    expect(await openDecision(PROJECT, SCRIPTS, 'Q', '@matt', ACTOR)).toEqual({ ok: false, stderr: 'Error: no decision table' })
  })
  it('an empty or multi-line decision never spawns', async () => {
    expect((await openDecision(PROJECT, SCRIPTS, '  ', '@matt', ACTOR)).ok).toBe(false)
    expect((await openDecision(PROJECT, SCRIPTS, 'a\nb', '@matt', ACTOR)).ok).toBe(false)
    expect(run).not.toHaveBeenCalled()
  })
})

describe('decideDecision', () => {
  it('runs decide with --by the actor and reads the plugin\'s row back', async () => {
    run.mockResolvedValue(json({ id: 'DL-01', status: 'decided', decided: '2026-10-06', by: '@priya-n', path: '.sdlc/decision-log.md' }))
    const r = await decideDecision(PROJECT, SCRIPTS, 'DL-01', 'Fail closed', ACTOR)
    expect(r).toEqual({ ok: true, id: 'DL-01', status: 'decided', decided: '2026-10-06', by: '@priya-n', path: '.sdlc/decision-log.md' })
    expect(run).toHaveBeenCalledWith(SCRIPTS, 'track_decisions.py', ['decide', '--repo', PROJECT, '--id', 'DL-01', '--by', '@priya-n', '--resolution', 'Fail closed', '--json'])
  })
  it('no actor, a bad id or an empty resolution refuse before spawning', async () => {
    expect(await decideDecision(PROJECT, SCRIPTS, 'DL-01', 'x', null)).toEqual({ ok: false, stderr: NO_ACTOR })
    expect(await decideDecision(PROJECT, SCRIPTS, '01', 'x', ACTOR)).toMatchObject({ ok: false, stderr: expect.stringMatching(/not a decision id/) })
    expect((await decideDecision(PROJECT, SCRIPTS, 'DL-01', ' ', ACTOR)).ok).toBe(false)
    expect(run).not.toHaveBeenCalled()
  })
  it('the plugin\'s refusal comes back verbatim', async () => {
    run.mockResolvedValue(entry(1, '', 'Error: no decision DL-09 in .sdlc/decision-log.md'))
    expect(await decideDecision(PROJECT, SCRIPTS, 'DL-09', 'x', ACTOR)).toEqual({ ok: false, stderr: 'Error: no decision DL-09 in .sdlc/decision-log.md' })
  })
})
