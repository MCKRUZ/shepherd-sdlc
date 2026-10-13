/** The Sprint view's main-process half, against canned plugin output: exactly which script and
 * argv run, how the plugin's keys become the view, that a null stays null (never a zero), and that
 * a bad id never reaches an argv. */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { IpcMain } from 'electron'

vi.mock('../electron/main/project', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../electron/main/project')>()),
  runPluginScript: vi.fn(),
}))

import { getSprintStatus, readSprintView, registerSprintHandlers, renderSprintReport } from '../electron/main/sprint'
import { runPluginScript } from '../electron/main/project'
import type { ConsoleEntry } from '../shared/types'

const run = vi.mocked(runPluginScript)

// No .sdlc/state.yaml under this path on any machine, so the adapter falls back to --repo.
const PROJECT = resolve('/work/proj')
const SCRIPTS = resolve('/plugin/scripts')

const entry = (stdout: string, exitCode = 0, stderr = ''): ConsoleEntry => ({
  id: 'x', command: 'py', args: [], cwd: '', startedAt: '', durationMs: 0,
  exitCode, stdout, stderr, ok: exitCode === 0,
})
const json = (value: unknown, exitCode = 0) => entry(JSON.stringify(value), exitCode)

/** What `sprint.py status --json` prints for a planning sprint with two slated specs. */
const STATUS = {
  sprint: {
    id: 'S07', goal: 'Adjusters file without a phone call', start: '2026-09-28', end: '2026-10-09', state: 'planning',
    target: 4, mix: 'HIGH:1,MEDIUM:2,LOW:1', board_ref: '', readied_by: '', closed_by: '', created: '2026-09-25',
    path: `${PROJECT}/.sdlc/sprints/S07.md`, rel_path: '.sdlc/sprints/S07.md', days: { total: 10, elapsed: 3, remaining: 7 },
  },
  slate: [
    {
      id: '0007', name: 'duplicate-claim-409', risk: 'HIGH', type: 'feature', channel: '', status: 'ready', sprint: 'S07',
      next_owner: '', eng_review: 'accepted', data_review: 'n-a', depends_on: [], dor: 'READY', dor_blocking: [],
      path: `${PROJECT}/specs/0007-duplicate-claim-409.md`, rel_path: 'specs/0007-duplicate-claim-409.md',
    },
    {
      id: '0008', name: 'claim-export', risk: 'MEDIUM', type: 'feature', channel: 'ag-ui', status: 'draft', sprint: 'S07',
      next_owner: '@sam-k', eng_review: '', data_review: 'pending', depends_on: ['0007'], dor: 'NOT READY',
      dor_blocking: ['## Scope Out: missing'], path: `${PROJECT}/specs/0008-claim-export.md`, rel_path: 'specs/0008-claim-export.md',
    },
  ],
  readiness: { ready: 1, total: 2, gaps: [{ spec: '0008', gaps: ['DoR NOT READY', 'status is draft'] }] },
  verdicts_pending: [{ spec: '0008', lane: 'eng', since_business_days: null }, { spec: '0008', lane: 'data', since_business_days: 2 }],
  handoffs_open: [{ spec: '0008', to: '@sam-k', since_business_days: null }],
  mix: { HIGH: { target: 1, actual: 1 }, MEDIUM: { target: 2, actual: 1 }, LOW: { target: 1, actual: 0 } },
  mix_warnings: ['LOW: 0 slated of 1 targeted'],
  wip: { in_flight: 0, cap: null },
  build_order: ['0007', '0008'],
  next_up: '0007',
  dependency_gaps: [],
  decisions: null,
  carried_in: [{ spec: '0007', from_sprint: 'S06', reason: 'blocked on the vendor API' }],
  has_data: true,
}

const NO_SPRINT = {
  sprint: null, slate: [], readiness: { ready: 0, total: 0, gaps: [] }, verdicts_pending: [], handoffs_open: [], mix: {},
  mix_warnings: [], wip: { in_flight: 0, cap: null }, build_order: [], next_up: null, dependency_gaps: [], decisions: null,
  carried_in: [], has_data: false, note: "'S7' is not a sprint id (expected S07, S12, ...) — no data",
}

const FAILURES: Array<[string, () => ConsoleEntry]> = [
  ['the script is missing (python cannot open it)', () => entry('', 2, "python: can't open file 'sprint.py': [Errno 2] No such file or directory")],
  ['it exits with code 1', () => entry(JSON.stringify(STATUS), 1)],
  ['it prints text that is not JSON', () => entry('Sprint S07 — planning')],
  ['it prints JSON that is not one document', () => entry('[1, 2]')],
  ['it prints nothing', () => entry('')],
  ['it prints a document that is not the status', () => json({ ok: true })],
]

describe('getSprintStatus', () => {
  beforeEach(() => run.mockReset())

  it('runs exactly sprint.py status --repo <project> --json when the project has no state file', async () => {
    run.mockResolvedValue(json(STATUS))
    await getSprintStatus(PROJECT, SCRIPTS)
    expect(run).toHaveBeenCalledTimes(1)
    expect(run).toHaveBeenCalledWith(SCRIPTS, 'sprint.py', ['status', '--repo', PROJECT, '--json'])
  })

  it('adds --sprint <id> only when one is named', async () => {
    run.mockResolvedValue(json(STATUS))
    await getSprintStatus(PROJECT, SCRIPTS, 'S07')
    expect(run).toHaveBeenCalledWith(SCRIPTS, 'sprint.py', ['status', '--repo', PROJECT, '--json', '--sprint', 'S07'])
  })

  it('maps the plugin\'s keys to the view and keeps every null a null', async () => {
    run.mockResolvedValue(json(STATUS))
    const r = await getSprintStatus(PROJECT, SCRIPTS)
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.sprint).toEqual({
      id: 'S07', goal: 'Adjusters file without a phone call', start: '2026-09-28', end: '2026-10-09', state: 'planning',
      target: 4, mix: 'HIGH:1,MEDIUM:2,LOW:1', boardRef: '', readiedBy: '', closedBy: '', created: '2026-09-25',
      path: `${PROJECT}/.sdlc/sprints/S07.md`, relPath: '.sdlc/sprints/S07.md', days: { total: 10, elapsed: 3, remaining: 7 },
    })
    expect(r.slate[1]).toEqual({
      id: '0008', name: 'claim-export', risk: 'MEDIUM', type: 'feature', channel: 'ag-ui', status: 'draft', sprint: 'S07',
      nextOwner: '@sam-k', engReview: '', dataReview: 'pending', dependsOn: ['0007'], dor: 'NOT READY',
      dorBlocking: ['## Scope Out: missing'], path: `${PROJECT}/specs/0008-claim-export.md`, relPath: 'specs/0008-claim-export.md',
    })
    expect(r.readiness).toEqual({ ready: 1, total: 2, gaps: [{ spec: '0008', gaps: ['DoR NOT READY', 'status is draft'] }] })
    expect(r.verdictsPending).toEqual([{ spec: '0008', lane: 'eng', sinceBusinessDays: null }, { spec: '0008', lane: 'data', sinceBusinessDays: 2 }])
    expect(r.handoffsOpen).toEqual([{ spec: '0008', to: '@sam-k', sinceBusinessDays: null }])
    expect(r.mix).toEqual({ HIGH: { target: 1, actual: 1 }, MEDIUM: { target: 2, actual: 1 }, LOW: { target: 1, actual: 0 } })
    expect(r.mixWarnings).toEqual(['LOW: 0 slated of 1 targeted'])
    expect(r.wip).toEqual({ inFlight: 0, cap: null })
    expect(r.buildOrder).toEqual(['0007', '0008'])
    expect(r.nextUp).toBe('0007')
    expect(r.dependencyGaps).toEqual([])
    expect(r.decisions).toBeNull()
    expect(r.carriedIn).toEqual([{ spec: '0007', fromSprint: 'S06', reason: 'blocked on the vendor API' }])
    expect(r.hasData).toBe(true)
    expect(r.note).toBeNull()
  })

  it('reads the decision-log summary when the project keeps one', async () => {
    run.mockResolvedValue(json({ ...STATUS, decisions: { open: 2, overdue: [{ id: 'D-3', decision: 'Pick the queue', owner: '', due: '2026-10-01' }] } }))
    const r = await getSprintStatus(PROJECT, SCRIPTS)
    expect(r.ok && r.decisions).toEqual({ open: 2, overdue: [{ id: 'D-3', decision: 'Pick the queue', owner: '', due: '2026-10-01' }] })
  })

  it('a project with no sprint is a view with sprint null, has_data false and the plugin\'s note — not an error', async () => {
    run.mockResolvedValue(json(NO_SPRINT))
    const r = await getSprintStatus(PROJECT, SCRIPTS, 'S07')
    expect(r).toMatchObject({ ok: true, sprint: null, slate: [], hasData: false, note: NO_SPRINT.note })
  })

  it('derives the repo-relative path for a plugin that prints only the absolute one', async () => {
    const older = {
      ...STATUS,
      sprint: { ...STATUS.sprint, rel_path: undefined },
      slate: STATUS.slate.map(({ rel_path: _drop, ...rest }) => rest),
    }
    run.mockResolvedValue(json(older))
    const r = await getSprintStatus(PROJECT, SCRIPTS)
    expect(r.ok && r.slate.map((s) => s.relPath)).toEqual(['specs/0007-duplicate-claim-409.md', 'specs/0008-claim-export.md'])
    expect(r.ok && r.sprint?.relPath).toBe('.sdlc/sprints/S07.md')
  })

  it('a path outside the project yields no relative path rather than a path with ..', async () => {
    run.mockResolvedValue(json({ ...STATUS, slate: [{ ...STATUS.slate[0], rel_path: undefined, path: resolve('/elsewhere/specs/0007-x.md') }] }))
    const r = await getSprintStatus(PROJECT, SCRIPTS)
    expect(r.ok && r.slate[0].relPath).toBe('')
  })

  it('refuses a sprint id that is not S<NN> before anything runs', async () => {
    for (const bad of ['S7', 's07', 'S07 --json', '--sprint', '../S07', '']) {
      const r = await getSprintStatus(PROJECT, SCRIPTS, bad)
      expect(r).toEqual({ ok: false, error: expect.stringMatching(/not a sprint id/) })
    }
    expect(run).not.toHaveBeenCalled()
  })

  it.each(FAILURES)('is one plain error line, and no view, when %s', async (_name, result) => {
    run.mockResolvedValue(result())
    const r = await getSprintStatus(PROJECT, SCRIPTS)
    expect(r).toEqual({ ok: false, error: expect.stringMatching(/^[^\n]+$/) })
  })

  it('shows the plugin\'s own one-line refusal when it gives one', async () => {
    run.mockResolvedValue(entry('Error: state file not found: /x/.sdlc/state.yaml\n', 1))
    expect(await getSprintStatus(PROJECT, SCRIPTS)).toEqual({ ok: false, error: 'state file not found: /x/.sdlc/state.yaml' })
  })

  it('rejects a status missing the counts the view needs rather than inventing zeros', async () => {
    run.mockResolvedValue(json({ ...STATUS, readiness: { gaps: [] } }))
    expect(await getSprintStatus(PROJECT, SCRIPTS)).toMatchObject({ ok: false })
    run.mockResolvedValue(json({ ...STATUS, wip: {} }))
    const r = await getSprintStatus(PROJECT, SCRIPTS)
    expect(r.ok && r.wip).toEqual({ inFlight: null, cap: null })
  })
})

describe('getSprintStatus in a project with a state file', () => {
  let project = ''
  beforeEach(() => {
    run.mockReset()
    project = mkdtempSync(join(tmpdir(), 'studio-sprint-adapter-'))
    mkdirSync(join(project, '.sdlc'), { recursive: true })
    writeFileSync(join(project, '.sdlc', 'state.yaml'), 'project_name: x\n')
  })
  afterEach(() => rmSync(project, { recursive: true, force: true }))

  it('runs in workflow mode: --state <project>/.sdlc/state.yaml, never --repo', async () => {
    run.mockResolvedValue(json(STATUS))
    await getSprintStatus(project, SCRIPTS)
    expect(run).toHaveBeenCalledWith(SCRIPTS, 'sprint.py', ['status', '--state', join(project, '.sdlc', 'state.yaml'), '--json'])
    run.mockResolvedValue(json({ ok: true, sprint: 'S07', kind: 'planning', output: '/x', rel_output: '.sdlc/reports/sprint-S07-planning.html' }))
    await renderSprintReport(project, SCRIPTS, 'S07', 'planning')
    expect(run).toHaveBeenLastCalledWith(SCRIPTS, 'sprint.py', ['plan', '--state', join(project, '.sdlc', 'state.yaml'), '--sprint', 'S07', '--json'])
  })
})

describe('renderSprintReport', () => {
  beforeEach(() => run.mockReset())

  const WRITTEN = (kind: string) => ({ ok: true, sprint: 'S07', kind, output: `${PROJECT}/.sdlc/reports/sprint-S07-${kind}.html`, rel_output: `.sdlc/reports/sprint-S07-${kind}.html` })

  it('writes the planning page with sprint.py plan --sprint <id> --json and returns where it went, repo-relative', async () => {
    run.mockResolvedValue(json(WRITTEN('planning')))
    const r = await renderSprintReport(PROJECT, SCRIPTS, 'S07', 'planning')
    expect(run).toHaveBeenCalledWith(SCRIPTS, 'sprint.py', ['plan', '--repo', PROJECT, '--sprint', 'S07', '--json'])
    expect(r).toEqual({ ok: true, relOutput: '.sdlc/reports/sprint-S07-planning.html' })
  })

  it('writes the review page with generate_sprint_report.py --sprint <id> --kind review --json', async () => {
    run.mockResolvedValue(json(WRITTEN('review')))
    const r = await renderSprintReport(PROJECT, SCRIPTS, 'S07', 'review')
    expect(run).toHaveBeenCalledWith(SCRIPTS, 'generate_sprint_report.py', ['--repo', PROJECT, '--sprint', 'S07', '--kind', 'review', '--json'])
    expect(r).toEqual({ ok: true, relOutput: '.sdlc/reports/sprint-S07-review.html' })
  })

  it('passes the plugin\'s own refusal on, in its words, whatever the exit code', async () => {
    run.mockResolvedValue(json({ ok: false, error: 'sprint S09 does not exist (/p/.sdlc/sprints/S09.md) — run `new` first' }, 1))
    expect(await renderSprintReport(PROJECT, SCRIPTS, 'S09', 'planning'))
      .toEqual({ ok: false, error: 'sprint S09 does not exist (/p/.sdlc/sprints/S09.md) — run `new` first' })
  })

  it('refuses a bad id or an unknown kind before anything runs', async () => {
    expect(await renderSprintReport(PROJECT, SCRIPTS, 'S7', 'planning')).toMatchObject({ ok: false })
    expect(await renderSprintReport(PROJECT, SCRIPTS, 'S07 --output /etc/x', 'planning')).toMatchObject({ ok: false })
    // The kind crosses from the renderer, so a value the type forbids is still checked.
    expect(await renderSprintReport(PROJECT, SCRIPTS, 'S07', 'summary' as never)).toMatchObject({ ok: false })
    expect(run).not.toHaveBeenCalled()
  })

  it.each([
    ['ok without a path', () => json({ ok: true, sprint: 'S07' })],
    ['a success document on a failing exit', () => json(WRITTEN('planning'), 1)],
    ['prose', () => entry('Planning page written to: /p/.sdlc/reports/sprint-S07-planning.html')],
    ['nothing', () => entry('', 2)],
  ])('is one plain error line when the plugin prints %s', async (_name, result) => {
    run.mockResolvedValue(result())
    expect(await renderSprintReport(PROJECT, SCRIPTS, 'S07', 'planning')).toEqual({ ok: false, error: expect.stringMatching(/^[^\n]+$/) })
  })
})

describe('readSprintView', () => {
  it('needs the top-level keys the status always has, and nothing it does not', () => {
    expect(readSprintView({ slate: [], readiness: { ready: 0, total: 0 }, has_data: false }, PROJECT)).toBeNull()
    expect(readSprintView({ sprint: null, readiness: { ready: 0, total: 0 }, has_data: false }, PROJECT)).toBeNull()
    expect(readSprintView({ sprint: null, slate: [], readiness: { ready: 0, total: 0 }, has_data: 'no' }, PROJECT)).toBeNull()
    const minimal = readSprintView({ sprint: null, slate: [], readiness: { ready: 0, total: 0 }, has_data: false }, PROJECT)
    expect(minimal).toMatchObject({ ok: true, sprint: null, hasData: false, decisions: null, nextUp: null, note: null, wip: { inFlight: null, cap: null } })
  })

  it('drops a slate row without an id by refusing the whole view, never by showing a shorter slate', () => {
    expect(readSprintView({ ...STATUS, slate: [{ name: 'nameless' }] }, PROJECT)).toBeNull()
  })
})

describe('registerSprintHandlers', () => {
  it('registers exactly the two channels the preload exposes, and answers without a plugin in one line', async () => {
    const handlers = new Map<string, (...args: unknown[]) => unknown>()
    type IpcHandler = Parameters<IpcMain['handle']>[1]
    registerSprintHandlers({ handle: (channel: string, fn: IpcHandler) => { handlers.set(channel, fn as (...args: unknown[]) => unknown) } }, async () => null)
    expect([...handlers.keys()].sort()).toEqual(['studio:getSprintStatus', 'studio:renderSprintReport'])
    expect(await handlers.get('studio:getSprintStatus')!({}, PROJECT)).toEqual({ ok: false, error: 'Shepherd plugin scripts not found' })
    expect(await handlers.get('studio:renderSprintReport')!({}, PROJECT, 'S07', 'planning')).toEqual({ ok: false, error: 'Shepherd plugin scripts not found' })
  })
})
