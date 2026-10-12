import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

vi.mock('../electron/main/project', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../electron/main/project')>()),
  runPluginScript: vi.fn(),
}))
vi.mock('../electron/main/readiness', () => ({ getStageReadiness: vi.fn() }))

import { registerActivityHandlers, runActivityCheck, startActivity } from '../electron/main/activities'
import { runPluginScript } from '../electron/main/project'
import { getStageReadiness } from '../electron/main/readiness'
import type { ConsoleEntry, StageActivity, StageReadiness } from '../shared/types'

const run = vi.mocked(runPluginScript)
const readiness = vi.mocked(getStageReadiness)

const entry = (stdout: string, ok = true): ConsoleEntry => ({
  id: 'x', command: 'py', args: [], cwd: '', startedAt: '', durationMs: 0,
  exitCode: ok ? 0 : 1, stdout, stderr: '', ok,
})

const sha = (path: string) => createHash('sha256').update(readFileSync(path)).digest('hex')

// --- the two checks ---------------------------------------------------------------------------

describe('runActivityCheck', () => {
  beforeEach(() => run.mockReset())

  it('rules-check runs exactly rules_check.py --repo <project> --json', async () => {
    run.mockResolvedValue(entry(JSON.stringify({ has_data: true, notes: [], findings: [] })))
    await runActivityCheck('C:/proj', 'C:/plugin/scripts', 'rules-check')
    expect(run).toHaveBeenCalledTimes(1)
    expect(run).toHaveBeenCalledWith('C:/plugin/scripts', 'rules_check.py', ['--repo', 'C:/proj', '--json'])
  })

  it('data-check runs exactly data_contract.py summary --repo <project> --json', async () => {
    run.mockResolvedValue(entry(JSON.stringify({ has_data: true })))
    await runActivityCheck('C:/proj', 'C:/plugin/scripts', 'data-check')
    expect(run).toHaveBeenCalledTimes(1)
    expect(run).toHaveBeenCalledWith('C:/plugin/scripts', 'data_contract.py', ['summary', '--repo', 'C:/proj', '--json'])
  })

  it('maps rules findings to subject and message, and keeps the plugin notes', async () => {
    run.mockResolvedValue(entry(JSON.stringify({
      has_data: true, notes: ['no decision log'],
      findings: [{ check: 'rule-no-scenario', severity: 'advisory', subject: 'BR-02', message: 'BR-02 is not referenced by any scenario' }],
    })))
    expect(await runActivityCheck('p', 's', 'rules-check')).toEqual({
      ok: true, check: 'rules-check', hasData: true, notes: ['no decision log'],
      findings: [{ subject: 'BR-02', message: 'BR-02 is not referenced by any scenario' }],
    })
  })

  it('maps the personal-data summary, including the risk sentence', async () => {
    run.mockResolvedValue(entry(JSON.stringify({
      has_data: true, notes: [], field_count: 5, pii_count: 2, pii_fields: ['email', 'dob'],
      indirect_fields: [], unclassified: [], risk_implication: 'any PII field', advisory: true,
    })))
    expect(await runActivityCheck('p', 's', 'data-check')).toEqual({
      ok: true, check: 'data-check', hasData: true, notes: [], fieldCount: 5, piiCount: 2,
      piiFields: ['email', 'dob'], riskImplication: 'any PII field',
    })
  })

  it('reports has_data false as hasData false with the plugin\'s note, so nothing reads as "no problems" or a zero count', async () => {
    run.mockResolvedValue(entry(JSON.stringify({
      has_data: false, notes: ['data-contract.md not found'], field_count: 0, pii_count: 0,
      pii_fields: [], risk_implication: null,
    })))
    const r = await runActivityCheck('p', 's', 'data-check')
    expect(r).toMatchObject({ ok: true, hasData: false, notes: ['data-contract.md not found'], riskImplication: null })
    const rules = await runActivityCheck('p', 's', 'rules-check')
    expect(rules).toMatchObject({ ok: true, hasData: false })
  })

  it.each([
    ['the script is missing (python cannot open it)', () => entry('', false)],
    ['it exits with code 1', () => ({ ...entry('{"has_data": true}', false), exitCode: 1 })],
    ['it prints text that is not JSON', () => entry('ADVISORY - 0 finding(s)')],
    ['it prints JSON that is not one document', () => entry('[1, 2]')],
    ['it prints nothing', () => entry('')],
  ])('is one plain error line, and no count, when %s', async (_name, result) => {
    for (const id of ['rules-check', 'data-check']) {
      run.mockResolvedValue(result())
      const r = await runActivityCheck('p', 's', id)
      expect(r.ok).toBe(false)
      expect(r).toEqual({ ok: false, error: expect.stringMatching(/^[^\n]+$/) })
      expect(Object.keys(r)).toEqual(['ok', 'error'])
    }
  })

  it('refuses an activity Studio has no check for, without running anything', async () => {
    const r = await runActivityCheck('p', 's', 'rm-rf')
    expect(r.ok).toBe(false)
    expect(run).not.toHaveBeenCalled()
  })
})

// --- starting an activity ---------------------------------------------------------------------

const DATA_PATHS = [
  '.sdlc/artifacts/02-design/data/data-contract.md',
  '.sdlc/artifacts/02-design/data/data-readiness.md',
  '.sdlc/artifacts/02-design/data/lineage-audit.md',
]

function activity(overrides: Partial<StageActivity> = {}): StageActivity {
  return {
    id: 'data', label: 'Data contract', command: 'sprd-data', kind: 'create', optional: true,
    creates: DATA_PATHS, after: [], status: 'available', reason: null, ...overrides,
  }
}

function stage(...activities: StageActivity[]): StageReadiness {
  return {
    ok: true, stageId: '2', name: 'design', display: 'Phase 2: Design', isCurrent: true,
    documents: [], findings: [], judgement: [], signOff: { status: 'pending', signedOffBy: null, completedAt: null },
    ready: true, activities,
  }
}

describe('startActivity', () => {
  let root: string
  let project: string
  let scriptsDir: string

  beforeEach(() => {
    readiness.mockReset()
    root = mkdtempSync(join(tmpdir(), 'start-activity-'))
    project = join(root, 'project')
    scriptsDir = join(root, 'plugin', 'scripts')
    mkdirSync(project, { recursive: true })
    mkdirSync(scriptsDir, { recursive: true })
    const templates = join(root, 'plugin', 'templates', 'phases', '02-design', 'data')
    mkdirSync(templates, { recursive: true })
    for (const p of DATA_PATHS) writeFileSync(join(templates, p.split('/').pop()!), `# template for ${p}\n`)
  })

  afterEach(() => rmSync(root, { recursive: true, force: true }))

  it('writes every file the activity declares and opens the first', async () => {
    readiness.mockResolvedValue(stage(activity()))
    const r = await startActivity(project, scriptsDir, '2', 'data')
    expect(r).toEqual({ ok: true, created: DATA_PATHS, existing: [], opened: DATA_PATHS[0] })
    for (const p of DATA_PATHS) expect(existsSync(join(project, p))).toBe(true)
    expect(readiness).toHaveBeenCalledWith(project, scriptsDir, '2')
  })

  it('never overwrites: an existing data-contract.md stays byte-identical and the other two are reported as created', async () => {
    readiness.mockResolvedValue(stage(activity()))
    const existing = join(project, DATA_PATHS[0])
    mkdirSync(join(project, '.sdlc', 'artifacts', '02-design', 'data'), { recursive: true })
    writeFileSync(existing, '# My contract — written by a person\n\n| email | PII |\n')
    const before = sha(existing)

    const r = await startActivity(project, scriptsDir, '2', 'data')

    expect(sha(existing)).toBe(before)
    expect(r.ok).toBe(true)
    expect(r.created).toEqual([DATA_PATHS[1], DATA_PATHS[2]])
    expect(r.existing).toEqual([DATA_PATHS[0]])
    expect(r.opened).toBe(DATA_PATHS[0])
  })

  it.each([
    ['a path outside .sdlc/artifacts', ['docs/notes.md']],
    ['a path with a ".." segment', ['.sdlc/artifacts/02-design/../../../escape.md']],
  ])('refuses %s and writes nothing', async (_name, creates) => {
    readiness.mockResolvedValue(stage(activity({ creates })))
    const r = await startActivity(project, scriptsDir, '2', 'data')
    expect(r.ok).toBe(false)
    expect(r.created).toEqual([])
    expect(r.error).toBeTruthy()
    expect(existsSync(join(project, 'docs'))).toBe(false)
    expect(existsSync(join(root, 'escape.md'))).toBe(false)
    expect(existsSync(join(project, '.sdlc', 'artifacts'))).toBe(false)
  })

  it('stops at the first file that fails and reports what was already created', async () => {
    readiness.mockResolvedValue(stage(activity({ creates: [DATA_PATHS[0], '.sdlc/artifacts/02-design/data/no-template.md', DATA_PATHS[2]] })))
    const r = await startActivity(project, scriptsDir, '2', 'data')
    expect(r.ok).toBe(false)
    expect(r.created).toEqual([DATA_PATHS[0]])
    expect(r.error).toMatch(/no template/i)
    expect(existsSync(join(project, DATA_PATHS[2]))).toBe(false)
  })

  it('refuses a blocked activity with the plugin\'s own reason, writing nothing', async () => {
    readiness.mockResolvedValue(stage(activity({ status: 'blocked', reason: 'Finish the requirements first.' })))
    const r = await startActivity(project, scriptsDir, '2', 'data')
    expect(r).toEqual({ ok: false, created: [], existing: [], error: 'Finish the requirements first.' })
    expect(existsSync(join(project, '.sdlc'))).toBe(false)
  })

  it.each([
    ['an activity that is not a create', activity({ kind: 'check' })],
    ['an activity id the stage does not have', activity({ id: 'other' })],
  ])('refuses %s', async (_name, declared) => {
    readiness.mockResolvedValue(stage(declared))
    const r = await startActivity(project, scriptsDir, '2', 'data')
    expect(r.ok).toBe(false)
    expect(r.created).toEqual([])
    expect(existsSync(join(project, '.sdlc'))).toBe(false)
  })

  it('refuses when the plugin reports no activities at all (an older plugin)', async () => {
    readiness.mockResolvedValue({ ...stage(), activities: undefined })
    expect((await startActivity(project, scriptsDir, '2', 'data')).ok).toBe(false)
  })
})

// --- registration -----------------------------------------------------------------------------

describe('registerActivityHandlers', () => {
  it('registers the four channels the preload bridge invokes, and answers plainly when the plugin is not found', async () => {
    const handlers = new Map<string, (...args: never[]) => Promise<unknown>>()
    registerActivityHandlers(
      { handle: (channel: string, fn: never) => { handlers.set(channel, fn) } },
      async () => null,
    )
    expect([...handlers.keys()].sort()).toEqual(['studio:getStageGuide', 'studio:runActivityCheck', 'studio:startActivity', 'studio:startDocument'])

    const call = (channel: string, ...args: unknown[]) => (handlers.get(channel) as (...a: unknown[]) => Promise<unknown>)({}, ...args)
    expect(await call('studio:startActivity', 'p', '2', 'data')).toMatchObject({ ok: false, created: [], existing: [] })
    expect(await call('studio:runActivityCheck', 'p', 'rules-check')).toMatchObject({ ok: false })
    expect(await call('studio:getStageGuide', 'phases/x.md')).toMatchObject({ ok: false })
    expect(await call('studio:startDocument', 'p', 'a.md')).toMatchObject({ ok: false })
  })
})
