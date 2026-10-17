/** The command center's Azure Boards block (build kit §5 B4-P2; design §12 item 4): one more LOCAL block named by
 * the literal spawn it came from, `ado_sync.py status --json` — never `az`, never a read of `.sdlc/ado.yaml`,
 * `schema.json` or anything under `.sdlc/ado/`. It rides the same rules as every block: a missing capability
 * disables it with `newerPlugin(cap)` and never spawns the verb; a failure leaves the other blocks ok; a document
 * that is not the status document is "no data", never a zeroed shape; a count the plugin printed as null stays
 * null; local blocks go on invalidation. Nothing here widens `needsYou` (the Today chips are the renderer's). */
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../electron/main/project', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../electron/main/project')>()),
  runPluginScript: vi.fn(),
}))

import { getCommandCenter, invalidateCommandCenter, readAdoStatus, SOURCES } from '../../electron/main/commandCenter'
import { runPluginScript } from '../../electron/main/project'
import { ADO_SYNC_COUNT_KEYS, ADO_SYNC_VIEW_KEYS, type AdoSyncView } from '../../shared/adoTypes'
import { CAPABILITIES, newerPlugin } from '../../shared/reasons'
import type { ConsoleEntry } from '../../shared/types'

const run = vi.mocked(runPluginScript)
const SCRIPTS = '/plugin/scripts'
const GOLDEN = resolve(__dirname, '..', '..', '..', 'scripts', 'tests', 'golden', 'ado_status_nodata.json')
const NODATA = JSON.parse(readFileSync(GOLDEN, 'utf-8')) as AdoSyncView
const entry = (stdout: string, exitCode = 0, stderr = ''): ConsoleEntry => ({ id: 'x', command: 'py', args: [], cwd: '', startedAt: '', durationMs: 0, exitCode, stdout, stderr, ok: exitCode === 0 })
const json = (v: unknown, exitCode = 0) => entry(JSON.stringify(v), exitCode)

/** A pulled mirror: every count measured, one debt row, by ref and field — never by person. */
const PULLED: AdoSyncView = {
  as_of: '2026-10-12T09:02:00Z',
  by_class: { CONFLICT: 1, SDLC_OWNED_DRIFT: 2 },
  counts: { conflicts: 1, debt: 1, drifted: 3, linked: 14, open: 3, pending: 3 },
  debt: [{ ref: 'sdlc:spec:0004', field: 'System.State', class: 'SDLC_OWNED_DRIFT', seen: '2026-10-07', due: '2026-10-09' }],
  hook_line: '3 rows pending · 3 drifted · as of 2026-10-12T09:02Z',
  last_plan: { plan: 'a1b2c3d4e5f6', ts: '2026-10-12T09:00:00Z', rows: 3 },
  ledger: '.sdlc/metrics/ado-sync-log.jsonl',
  notes: [],
  schema: 1,
}

const STATUS = { sprint: null, slate: [], readiness: { ready: 0, total: 0, gaps: [] }, verdicts_pending: [], handoffs_open: [{ spec: '0007', to: '@priya-n', since_business_days: 1 }], mix: {}, mix_warnings: [], wip: { in_flight: 0, cap: null }, build_order: [], next_up: null, dependency_gaps: [], decisions: null, carried_in: [], has_data: false, note: 'no sprint' }
const ALL = { code_host_available: false, error: null, specs: [{ spec: '0007', name: 'x', path: 'specs/0007-x.md', status: 'ready', risk: 'HIGH', owner: '@priya-n', risk_confirmed_by: '' }], host: 'none' }
const TRACK = { total: 1, by_status: {}, in_flight: [], wip_by_team: {}, sprint_filter: null, warnings: [] }
const DECISIONS = { total: 0, open: 0, overdue: 0, clock_business_days: 2, open_decisions: [], overdue_decisions: [], log_path: 'p', exists: false }
const FINDINGS = { tracked: 0, open_debt: 0, fixed_claim_mismatches: 0 }
const SCORECARD = { accepted_as_is_rate: null, review_wait_median_hours: null, security_review_wait_median_hours: null, rework_revert_rate: null, bounce_back_rate: null, escaped_bugs: [], dora: {}, totals: {} }
const SETTINGS = { ok: true, roster: { file: '.sdlc/team.yaml', present: true, errors: [], teams: [], people: [{ handle: '@priya-n' }] } }
const LIST = { sprints: [], active: null, count: 0 }
const LOG = { events: [], count: 0, since: '2026-10-05', path: 'p', exists: false, skipped: 0 }

let project = ''
let caps: string[] = []
let adoAnswer: ConsoleEntry = json(NODATA)

/** Answers each script the way the plugin would; `broken` names scripts that fail. */
function plugin(broken: Partial<Record<string, ConsoleEntry>> = {}) {
  run.mockImplementation(async (_dir, script, args) => {
    if (broken[script]) return broken[script]!
    switch (script) {
      case 'generate_status.py': return json({ project_name: 'p', current_phase: { id: 'build' }, stages: [], capabilities: caps })
      case 'sprint.py': return args[0] === 'status' ? json(STATUS) : args[0] === 'list' ? json(LIST) : args[0] === 'log' ? json(LOG) : entry('', 1, 'unexpected verb')
      case 'spec_status.py': return json(ALL)
      case 'track_specs.py': return json(TRACK)
      case 'track_decisions.py': return json(DECISIONS)
      case 'record_findings.py': return json(FINDINGS)
      case 'scorecard.py': return json(SCORECARD)
      case 'project_settings.py': return json(SETTINGS)
      case 'ado_sync.py': return adoAnswer
    }
    return entry('', 2, `no such script ${script}`)
  })
}
const calls = (script: string) => run.mock.calls.filter((c) => c[1] === script).map((c) => c[2])
const noActor = { actor: null }

beforeEach(() => {
  run.mockReset()
  project = mkdtempSync(join(tmpdir(), 'cc-ado-'))
  mkdirSync(join(project, '.sdlc'))
  writeFileSync(join(project, '.sdlc', 'state.yaml'), 'current_phase: build\n')
  invalidateCommandCenter(project, 'all')
  caps = ['sprint-status', 'sprint-list', 'sprint-log', CAPABILITIES.adoStatus]
  adoAnswer = json(NODATA)
})
afterEach(() => { vi.useRealTimers(); rmSync(project, { recursive: true, force: true }) })

describe('the ado block', () => {
  it('is named by its literal source, ado_sync.py status --json, and that is the only spawn it makes', async () => {
    plugin()
    const cc = await getCommandCenter(project, SCRIPTS, 1, noActor)
    expect(SOURCES.ado).toBe('ado_sync.py status --json')
    expect(cc.ado).toMatchObject({ source: 'ado_sync.py status --json', ok: true, error: null })
    expect(calls('ado_sync.py')).toEqual([['status', '--state', join(project, '.sdlc', 'state.yaml'), '--json']])
    // Never `az`: not as a script, not as an argument, not as a path under the plugin.
    expect(run.mock.calls.every(([, script, args]) => script !== 'az' && !args.includes('az'))).toBe(true)
  })

  it('carries the never-pulled document as it is: every count null, never a zero', async () => {
    plugin()
    const cc = await getCommandCenter(project, SCRIPTS, 1, noActor)
    expect(cc.ado!.data).toEqual(NODATA)
    for (const k of ADO_SYNC_COUNT_KEYS) expect(cc.ado!.data!.counts[k], k).toBeNull()
    expect(cc.ado!.data!.as_of).toBeNull(); expect(cc.ado!.data!.debt).toBeNull(); expect(cc.ado!.data!.by_class).toBeNull()
  })

  it('carries a pulled document key for key, a measured zero staying a zero', async () => {
    adoAnswer = json({ ...PULLED, counts: { ...PULLED.counts, conflicts: 0, debt: 0 }, debt: [] })
    plugin()
    const cc = await getCommandCenter(project, SCRIPTS, 1, noActor)
    expect(cc.ado!.data).toEqual({ ...PULLED, counts: { ...PULLED.counts, conflicts: 0, debt: 0 }, debt: [] })
    expect(cc.ado!.data!.counts.conflicts).toBe(0)
  })

  it('a plugin without ado-status-json disables the block with newerPlugin(cap) and never spawns the verb', async () => {
    caps = ['sprint-status']
    plugin()
    const cc = await getCommandCenter(project, SCRIPTS, 1, noActor)
    expect(cc.ado).toMatchObject({ source: SOURCES.ado, ok: false, data: null, error: newerPlugin(CAPABILITIES.adoStatus) })
    expect(calls('ado_sync.py')).toEqual([])
  })

  it('a failing status leaves every other block ok, with the plugin\'s stderr verbatim', async () => {
    plugin({ 'ado_sync.py': entry('', 1, 'Traceback: boom') })
    const cc = await getCommandCenter(project, SCRIPTS, 1, noActor)
    expect(cc.ado).toMatchObject({ ok: false, data: null, error: 'Traceback: boom' })
    expect(cc.sprint.ok && cc.board.ok && cc.decisions.ok && cc.findings.ok && cc.scorecard.ok && cc.roster.ok).toBe(true)
  })

  it('a document that is not the status document is "no data", never a zeroed shape', async () => {
    adoAnswer = json({ ok: true })
    plugin()
    const cc = await getCommandCenter(project, SCRIPTS, 1, noActor)
    expect(cc.ado).toMatchObject({ ok: false, data: null })
    expect(cc.ado!.error).toBeTruthy()   // the plugin's own words (every block's rule), never a made-up zero
    plugin({ 'ado_sync.py': entry('') })
    invalidateCommandCenter(project)
    expect((await getCommandCenter(project, SCRIPTS, 1, noActor)).ado).toMatchObject({ ok: false, data: null, error: 'ado_sync.py gave no readable answer' })
  })

  it('is a local block: a second read is a cache hit, an invalidation (any write) reads it again', async () => {
    plugin()
    await getCommandCenter(project, SCRIPTS, 1, noActor)
    await getCommandCenter(project, SCRIPTS, 1, noActor)
    expect(calls('ado_sync.py')).toHaveLength(1)
    invalidateCommandCenter(project)
    adoAnswer = json(PULLED)
    const after = await getCommandCenter(project, SCRIPTS, 1, noActor)
    expect(calls('ado_sync.py')).toHaveLength(2)
    expect(after.ado!.data).toEqual(PULLED)
  })

  it('leaves needsYou exactly as it was: the Today chips are the renderer\'s, no NeedsYouItem is added', async () => {
    adoAnswer = json(PULLED)
    plugin()
    const withAdo = await getCommandCenter(project, SCRIPTS, 1, { actor: { name: '@priya-n', source: 'roster' } })
    invalidateCommandCenter(project, 'all')
    caps = ['sprint-status', 'sprint-list', 'sprint-log']
    const without = await getCommandCenter(project, SCRIPTS, 1, { actor: { name: '@priya-n', source: 'roster' } })
    expect(withAdo.needsYou).toEqual(without.needsYou)
    expect(withAdo.needsYou.map((i) => i.kind)).toEqual(['ack'])
  })

  it('keeps every earlier source name: the ado row is appended, none renamed', () => {
    expect(Object.keys(SOURCES)).toEqual(['sprint', 'sprints', 'board', 'decisions', 'findings', 'scorecard', 'roster', 'log', 'capabilities', 'ado'])
  })
})

describe('readAdoStatus', () => {
  it('reads the never-pulled golden and a pulled document, keeping only the keys the plugin documents', () => {
    expect(readAdoStatus(NODATA)).toEqual(NODATA)
    expect(readAdoStatus({ ...PULLED, a_future_key: 1 })).toEqual(PULLED)
    expect(Object.keys(readAdoStatus(PULLED)!).sort()).toEqual([...ADO_SYNC_VIEW_KEYS].sort())
  })

  it('refuses a document missing a key or a count, or with a wrongly typed one — it is never coerced', () => {
    for (const key of ADO_SYNC_VIEW_KEYS) {
      const { [key]: _gone, ...rest } = PULLED
      expect(readAdoStatus(rest), `without ${key}`).toBeNull()
    }
    for (const key of ADO_SYNC_COUNT_KEYS) {
      const { [key]: _gone, ...counts } = PULLED.counts
      expect(readAdoStatus({ ...PULLED, counts }), `without counts.${key}`).toBeNull()
      expect(readAdoStatus({ ...PULLED, counts: { ...PULLED.counts, [key]: '3' } }), `counts.${key} as text`).toBeNull()
      expect(readAdoStatus({ ...PULLED, counts: { ...PULLED.counts, [key]: -1 } }), `counts.${key} negative`).toBeNull()
    }
    expect(readAdoStatus({ ...PULLED, hook_line: 3 })).toBeNull()
    expect(readAdoStatus({ ...PULLED, notes: 'none' })).toBeNull()
    expect(readAdoStatus({ ...PULLED, debt: [{ ref: 'sdlc:spec:0004' }] })).toBeNull()
    expect(readAdoStatus({ ...PULLED, by_class: { CONFLICT: 'one' } })).toBeNull()
    expect(readAdoStatus({ ...PULLED, last_plan: { plan: 'a1b2c3d4e5f6' } })).toBeNull()
  })

  it('refuses what is not a document at all', () => {
    for (const bad of [null, undefined, 'status', 3, [], [NODATA], {}]) expect(readAdoStatus(bad)).toBeNull()
  })
})
