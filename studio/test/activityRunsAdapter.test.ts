import { beforeEach, describe, expect, it, vi } from 'vitest'
import { join, resolve, sep } from 'node:path'

vi.mock('../electron/main/project', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../electron/main/project')>()),
  runPluginScript: vi.fn(),
}))

import {
  exportPhaseReport, getNarrativeCoverage, getReviewStanding, registerActivityRunHandlers,
  runIntake, runStrictReviewCheck,
} from '../electron/main/activityRuns'
import { runPluginScript } from '../electron/main/project'
import type { ConsoleEntry } from '../shared/types'

const run = vi.mocked(runPluginScript)

const PROJECT = resolve('/work/proj')
// What the plugin prints for an absolute output path: the project's own, with forward slashes. Built
// from PROJECT so it is absolute on every platform (a literal `C:/...` is relative on macOS and Linux).
const REPORTS = `${PROJECT.split(sep).join('/')}/.sdlc/reports`
const SCRIPTS = resolve('/plugin/scripts')
const STATE = join(PROJECT, '.sdlc', 'state.yaml')

const entry = (stdout: string, exitCode = 0, stderr = ''): ConsoleEntry => ({
  id: 'x', command: 'py', args: [], cwd: '', startedAt: '', durationMs: 0,
  exitCode, stdout, stderr, ok: exitCode === 0,
})
const json = (value: unknown, exitCode = 0) => entry(JSON.stringify(value), exitCode)

// The three ways any of these scripts can fail, as the runner reports them: python cannot open a
// missing script (exit 2 and nothing on stdout), the script refuses (exit 1), or it prints text
// that is not one JSON document.
const FAILURES: Array<[string, () => ConsoleEntry]> = [
  ['the script is missing (python cannot open it)', () => entry('', 2, "python.exe: can't open file 'C:\\plugin\\scripts\\x.py': [Errno 2] No such file or directory")],
  ['it exits with code 1', () => entry('{"phase": "0"}', 1)],
  ['it prints text that is not JSON', () => entry('Report written to: x.html')],
  ['it prints JSON that is not one document', () => entry('[1, 2]')],
  ['it prints nothing', () => entry('')],
]

// --- phase report -----------------------------------------------------------------------------

const REPORT = {
  phase: '0', phase_name: 'Discovery', output: `${REPORTS}/00-discovery-report.html`,
  found: 3, missing: 2, total: 5, exit_criteria: 4,
  artifacts: { 'constitution.md': true, 'problem-statement.md': false, 'success-criteria.md': true, 'constraints.md': false, 'phase1-handoff.md': true },
}

describe('exportPhaseReport', () => {
  beforeEach(() => run.mockReset())

  it('runs exactly generate_phase_report.py --state <state> --phase <stage> --json', async () => {
    run.mockResolvedValue(json(REPORT))
    await exportPhaseReport(PROJECT, SCRIPTS, '0', false)
    expect(run).toHaveBeenCalledTimes(1)
    expect(run).toHaveBeenCalledWith(SCRIPTS, 'generate_phase_report.py', ['--state', STATE, '--phase', '0', '--json'])
  })

  it('with "all" runs --all --json and no --phase', async () => {
    run.mockResolvedValue(json({ reports: [REPORT], index: `${REPORTS}/index.html` }))
    await exportPhaseReport(PROJECT, SCRIPTS, '0', true)
    expect(run).toHaveBeenCalledWith(SCRIPTS, 'generate_phase_report.py', ['--state', STATE, '--all', '--json'])
  })

  it('maps the plugin\'s numbers and names the missing documents in the stage\'s own order', async () => {
    run.mockResolvedValue(json(REPORT))
    const r = await exportPhaseReport(PROJECT, SCRIPTS, '0', false)
    expect(r.ok).toBe(true)
    expect(r.reports).toEqual([{
      phase: '0', phaseName: 'Discovery', output: resolve(`${REPORTS}/00-discovery-report.html`),
      found: 3, missing: 2, total: 5, missingNames: ['problem-statement.md', 'constraints.md'],
    }])
  })

  it('resolves a relative output path against the project so the renderer only ever holds an absolute one', async () => {
    run.mockResolvedValue(json({ ...REPORT, output: '.sdlc/reports/00-discovery-report.html' }))
    const r = await exportPhaseReport(PROJECT, SCRIPTS, '0', false)
    expect(r.reports[0].output).toBe(join(PROJECT, '.sdlc', 'reports', '00-discovery-report.html'))
  })

  it('maps "all" to one entry per stage plus the index page', async () => {
    run.mockResolvedValue(json({
      reports: [REPORT, { ...REPORT, phase: 'close', phase_name: 'Close', found: 0, missing: 1, total: 1, artifacts: { 'final-handoff-report.md': false } }],
      index: `${REPORTS}/index.html`,
    }))
    const r = await exportPhaseReport(PROJECT, SCRIPTS, '0', true)
    expect(r.ok).toBe(true)
    expect(r.reports.map((x) => x.phase)).toEqual(['0', 'close'])
    expect(r.reports[1].missingNames).toEqual(['final-handoff-report.md'])
    expect(r.index).toBe(resolve(`${REPORTS}/index.html`))
  })

  it('refuses a stage id that is not a plain id, without running anything', async () => {
    for (const bad of ['--all', '0 --json', '../x', '']) {
      expect((await exportPhaseReport(PROJECT, SCRIPTS, bad, false)).ok).toBe(false)
    }
    expect(run).not.toHaveBeenCalled()
  })

  it.each(FAILURES)('is one plain error line, and no counts, when %s', async (_name, result) => {
    for (const all of [false, true]) {
      run.mockResolvedValue(result())
      const r = await exportPhaseReport(PROJECT, SCRIPTS, '0', all)
      expect(r).toEqual({ ok: false, error: expect.stringMatching(/^[^\n]+$/), reports: [] })
    }
  })

  it('shows the plugin\'s own one-line refusal when it gives one', async () => {
    run.mockResolvedValue(entry('', 1, "ERROR: invalid phase id '99'. Valid ids: 0, 1, 2.\n"))
    expect(await exportPhaseReport(PROJECT, SCRIPTS, '99', false)).toEqual({
      ok: false, error: "invalid phase id '99'. Valid ids: 0, 1, 2.", reports: [],
    })
  })

  it('rejects a report missing the fields the panel needs rather than inventing zeros', async () => {
    run.mockResolvedValue(json({ phase: '0', phase_name: 'Discovery' }))
    expect(await exportPhaseReport(PROJECT, SCRIPTS, '0', false)).toMatchObject({ ok: false, reports: [] })
  })
})

// --- intake -----------------------------------------------------------------------------------

const CATALOGUE = {
  documents: [
    { id: 'DOC-001', file: 'docs/intake/a.md', type: 'markdown', tokens: 6, estimation_method: 'word_count', checksum: 'sha256:1', skipped: false, priority: 2 },
    { id: 'DOC-002', file: 'docs/intake/b.txt', type: 'text', tokens: 5, estimation_method: 'word_count', checksum: 'sha256:2', skipped: true, priority: null },
  ],
  locked: false, locked_at: null, provisional: false, skipped: ['DOC-002'], priority_order: ['DOC-001'],
  totals: { documents: 2, estimated_tokens: 11, skipped_documents: 1, active_documents: 1, active_estimated_tokens: 6 },
}

describe('runIntake', () => {
  beforeEach(() => run.mockReset())

  it('with no change runs exactly intake_documents.py --state <state> --json', async () => {
    run.mockResolvedValue(json(CATALOGUE))
    await runIntake(PROJECT, SCRIPTS)
    expect(run).toHaveBeenCalledTimes(1)
    expect(run).toHaveBeenCalledWith(SCRIPTS, 'intake_documents.py', ['--state', STATE, '--json'])
  })

  it('maps skip, priority and lock to flags: ids comma-joined, priority order kept, lock only when true', async () => {
    run.mockResolvedValue(json(CATALOGUE))
    await runIntake(PROJECT, SCRIPTS, { skip: ['DOC-003', 'DOC-005'] })
    await runIntake(PROJECT, SCRIPTS, { priority: ['DOC-004', 'DOC-001'] })
    await runIntake(PROJECT, SCRIPTS, { lock: true })
    await runIntake(PROJECT, SCRIPTS, { lock: false, skip: [], priority: [] })
    const argvs = run.mock.calls.map((c) => c[2])
    expect(argvs).toEqual([
      ['--state', STATE, '--json', '--skip', 'DOC-003,DOC-005'],
      ['--state', STATE, '--json', '--priority', 'DOC-004,DOC-001'],
      ['--state', STATE, '--json', '--lock'],
      ['--state', STATE, '--json'],
    ])
  })

  it.each([
    ['a flag smuggled in as an id', { skip: ['--lock'] }],
    ['a free-text id', { skip: ['DOC-001 --lock'] }],
    ['a short id', { priority: ['DOC-1'] }],
    ['an empty id', { priority: [''] }],
    ['a lowercase id', { skip: ['doc-001'] }],
    ['a comma inside an id', { skip: ['DOC-001,DOC-002'] }],
    ['a newline', { skip: ['DOC-001\n'] }],
    ['a non-string', { skip: [1 as unknown as string] }],
  ])('refuses %s before anything runs', async (_name, change) => {
    const r = await runIntake(PROJECT, SCRIPTS, change)
    expect(r.ok).toBe(false)
    expect(r.error).toMatch(/^[^\n]+$/)
    expect(r.documents).toEqual([])
    expect(run).not.toHaveBeenCalled()
  })

  it('accepts ids with more than three digits', async () => {
    run.mockResolvedValue(json(CATALOGUE))
    await runIntake(PROJECT, SCRIPTS, { skip: ['DOC-1000'] })
    expect(run.mock.calls[0][2]).toContain('DOC-1000')
  })

  it('maps the catalogue: id, file, type, tokens, skipped, priority, the lock, the order and the totals', async () => {
    run.mockResolvedValue(json(CATALOGUE))
    expect(await runIntake(PROJECT, SCRIPTS)).toEqual({
      ok: true,
      documents: [
        { id: 'DOC-001', file: 'docs/intake/a.md', type: 'markdown', tokens: 6, skipped: false, priority: 2 },
        { id: 'DOC-002', file: 'docs/intake/b.txt', type: 'text', tokens: 5, skipped: true, priority: null },
      ],
      locked: false,
      priorityOrder: ['DOC-001'],
      totals: { documents: 2, estimatedTokens: 11, activeDocuments: 1 },
    })
  })

  it('passes locked: true through', async () => {
    run.mockResolvedValue(json({ ...CATALOGUE, locked: true }))
    expect((await runIntake(PROJECT, SCRIPTS)).locked).toBe(true)
  })

  it('reads a folder with no documents (the script exits 2 and prints an empty catalogue) as an empty catalogue, not an error', async () => {
    run.mockResolvedValue(json({
      documents: [], locked: false, priority_order: [],
      totals: { documents: 0, estimated_tokens: 0, active_documents: 0 }, message: 'No matching documents found in docs/intake',
    }, 2))
    expect(await runIntake(PROJECT, SCRIPTS)).toEqual({
      ok: true, documents: [], locked: false, priorityOrder: [],
      totals: { documents: 0, estimatedTokens: 0, activeDocuments: 0 },
    })
  })

  it('does not mistake exit 2 with documents in it, or a missing script, for an empty folder', async () => {
    run.mockResolvedValue(json(CATALOGUE, 2))
    expect((await runIntake(PROJECT, SCRIPTS)).ok).toBe(false)
    run.mockResolvedValue(entry('', 2, "python.exe: can't open file"))
    expect((await runIntake(PROJECT, SCRIPTS)).ok).toBe(false)
  })

  it('shows a locked catalogue\'s refusal as the script\'s own first line, with no table', async () => {
    run.mockResolvedValue(entry('', 1, 'Error: catalog is locked; DOC-NNN ids are stable \uFFFD edit catalog.json by hand to unlock\n'))
    const r = await runIntake(PROJECT, SCRIPTS, { skip: ['DOC-001'] })
    expect(r).toEqual({
      ok: false, error: 'catalog is locked; DOC-NNN ids are stable - edit catalog.json by hand to unlock',
      documents: [], locked: false, priorityOrder: [], totals: { documents: 0, estimatedTokens: 0, activeDocuments: 0 },
    })
  })

  it('reads the script\'s refusal from stdout too (some plugin scripts print their Error: line there)', async () => {
    run.mockResolvedValue(entry('Error: State file not found: x\n', 1))
    expect(await runIntake(PROJECT, SCRIPTS)).toMatchObject({ ok: false, error: 'State file not found: x' })
  })

  it.each(FAILURES)('is one plain error line, and no table, when %s', async (_name, result) => {
    run.mockResolvedValue(result())
    const r = await runIntake(PROJECT, SCRIPTS)
    expect(r).toEqual({
      ok: false, error: expect.stringMatching(/^[^\n]+$/), documents: [], locked: false,
      priorityOrder: [], totals: { documents: 0, estimatedTokens: 0, activeDocuments: 0 },
    })
  })
})

// --- narrative coverage -----------------------------------------------------------------------

const NARRATIVE = {
  has_data: true, notes: ['staleness unknown for 1 narrative(s)'],
  phases: [{ phase: '00-discovery', artifacts: [
    { name: 'constitution', path: 'x', status: 'present', narrative: 'y', stale: false },
    { name: 'problem-statement', path: 'x', status: 'present', narrative: 'y', stale: null },
    { name: 'constraints', path: 'x', status: 'none', narrative: null, stale: null },
  ] }],
  coverage: { with_narrative: 2, total: 3 },
}

describe('getNarrativeCoverage', () => {
  beforeEach(() => run.mockReset())

  it('runs exactly narrative_status.py --state <state> --phase <stage> --json', async () => {
    run.mockResolvedValue(json(NARRATIVE))
    await getNarrativeCoverage(PROJECT, SCRIPTS, '0')
    expect(run).toHaveBeenCalledTimes(1)
    expect(run).toHaveBeenCalledWith(SCRIPTS, 'narrative_status.py', ['--state', STATE, '--phase', '0', '--json'])
  })

  it('flattens the artifacts and carries the counts, the plugin\'s notes and the unknown staleness', async () => {
    run.mockResolvedValue(json(NARRATIVE))
    expect(await getNarrativeCoverage(PROJECT, SCRIPTS, '0')).toEqual({
      ok: true, hasData: true, notes: ['staleness unknown for 1 narrative(s)'], withNarrative: 2, total: 3,
      artifacts: [
        { name: 'constitution', status: 'present', stale: false },
        { name: 'problem-statement', status: 'present', stale: null },
        { name: 'constraints', status: 'none', stale: null },
      ],
    })
  })

  it('passes has_data false through as hasData false with the plugin\'s own note, never as "0 of 0"', async () => {
    run.mockResolvedValue(json({
      has_data: false, notes: ['no artifacts found in the selected phase folder(s)'],
      phases: [{ phase: '00-discovery', artifacts: [] }], coverage: { with_narrative: 0, total: 0 },
    }))
    expect(await getNarrativeCoverage(PROJECT, SCRIPTS, '0')).toMatchObject({
      ok: true, hasData: false, notes: ['no artifacts found in the selected phase folder(s)'], artifacts: [],
    })
  })

  it('handles the "unknown phase" answer (no phases at all) as hasData false', async () => {
    run.mockResolvedValue(json({ has_data: false, notes: ["unknown phase '99'"], phases: [], coverage: { with_narrative: 0, total: 0 } }))
    expect(await getNarrativeCoverage(PROJECT, SCRIPTS, '99')).toMatchObject({ ok: true, hasData: false, artifacts: [] })
  })

  it('refuses a stage id that is not a plain id, without running anything', async () => {
    expect((await getNarrativeCoverage(PROJECT, SCRIPTS, '--all-phases')).ok).toBe(false)
    expect(run).not.toHaveBeenCalled()
  })

  it.each(FAILURES)('is one plain error line, and no counts, when %s', async (_name, result) => {
    run.mockResolvedValue(result())
    expect(await getNarrativeCoverage(PROJECT, SCRIPTS, '0')).toEqual({
      ok: false, error: expect.stringMatching(/^[^\n]+$/), hasData: false, notes: [], withNarrative: 0, total: 0, artifacts: [],
    })
  })
})

// --- review standing and the strict check -----------------------------------------------------

const STANDING = { tracked: 3, open_debt: 1, fixed_claim_mismatches: 0 }

describe('getReviewStanding', () => {
  beforeEach(() => run.mockReset())

  it('runs exactly record_findings.py report --state <state> --json', async () => {
    run.mockResolvedValue(json(STANDING))
    await getReviewStanding(PROJECT, SCRIPTS)
    expect(run).toHaveBeenCalledTimes(1)
    expect(run).toHaveBeenCalledWith(SCRIPTS, 'record_findings.py', ['report', '--state', STATE, '--json'])
  })

  it('maps the three numbers', async () => {
    run.mockResolvedValue(json(STANDING))
    expect(await getReviewStanding(PROJECT, SCRIPTS)).toEqual({ ok: true, tracked: 3, openDebt: 1, fixedClaimMismatches: 0 })
  })

  it('a project with nothing tracked is ok with tracked 0 (the panel reads it as "none recorded")', async () => {
    run.mockResolvedValue(json({ tracked: 0, open_debt: 0, fixed_claim_mismatches: 0 }))
    expect(await getReviewStanding(PROJECT, SCRIPTS)).toEqual({ ok: true, tracked: 0, openDebt: 0, fixedClaimMismatches: 0 })
  })

  it('rejects a document without the three numbers rather than showing zeros', async () => {
    run.mockResolvedValue(json({ tracked: 3 }))
    expect(await getReviewStanding(PROJECT, SCRIPTS)).toMatchObject({ ok: false, tracked: 0, openDebt: 0, fixedClaimMismatches: 0 })
  })

  it.each(FAILURES)('is one plain error line, and no counts, when %s', async (_name, result) => {
    run.mockResolvedValue(result())
    expect(await getReviewStanding(PROJECT, SCRIPTS)).toEqual({
      ok: false, error: expect.stringMatching(/^[^\n]+$/), tracked: 0, openDebt: 0, fixedClaimMismatches: 0,
    })
  })
})

describe('runStrictReviewCheck', () => {
  beforeEach(() => run.mockReset())

  it('runs exactly record_findings.py report --state <state> --json --strict', async () => {
    run.mockResolvedValue(json(STANDING))
    await runStrictReviewCheck(PROJECT, SCRIPTS)
    expect(run).toHaveBeenCalledWith(SCRIPTS, 'record_findings.py', ['report', '--state', STATE, '--json', '--strict'])
  })

  it('exit code 0 is a clean result with no mismatches', async () => {
    run.mockResolvedValue(json(STANDING))
    expect(await runStrictReviewCheck(PROJECT, SCRIPTS)).toEqual({ ok: true, mismatches: 0 })
  })

  it('exit code 2 is a RESULT carrying the plugin\'s count, not an error', async () => {
    run.mockResolvedValue(json({ tracked: 3, open_debt: 1, fixed_claim_mismatches: 1 }, 2))
    expect(await runStrictReviewCheck(PROJECT, SCRIPTS)).toEqual({ ok: true, mismatches: 1 })
  })

  it('exit code 2 with nothing on stdout is a missing script (python\'s own exit code), not a finding', async () => {
    run.mockResolvedValue(entry('', 2, "python.exe: can't open file 'x.py'"))
    expect(await runStrictReviewCheck(PROJECT, SCRIPTS)).toEqual({ ok: false, error: expect.stringMatching(/^[^\n]+$/), mismatches: 0 })
  })

  it('exit code 2 whose JSON carries no count is an error, not "0 mismatches"', async () => {
    run.mockResolvedValue(json({ tracked: 3 }, 2))
    expect(await runStrictReviewCheck(PROJECT, SCRIPTS)).toMatchObject({ ok: false, mismatches: 0 })
  })

  it('exit code 1 is an error', async () => {
    run.mockResolvedValue(entry('Error: State file not found: x', 1))
    expect(await runStrictReviewCheck(PROJECT, SCRIPTS)).toEqual({ ok: false, error: 'State file not found: x', mismatches: 0 })
  })

  it.each([
    ['it prints text that is not JSON', () => entry('FIXED-claim check: clean')],
    ['it prints JSON that is not one document', () => entry('[1]')],
    ['it prints nothing', () => entry('')],
  ])('is one plain error line, and no count, when %s', async (_name, result) => {
    run.mockResolvedValue(result())
    expect(await runStrictReviewCheck(PROJECT, SCRIPTS)).toEqual({ ok: false, error: expect.stringMatching(/^[^\n]+$/), mismatches: 0 })
  })
})

// --- registration -----------------------------------------------------------------------------

describe('registerActivityRunHandlers', () => {
  it('registers the six channels the preload bridge invokes, and answers plainly when the plugin is not found', async () => {
    const handlers = new Map<string, (...args: never[]) => Promise<unknown>>()
    const opened: string[] = []
    registerActivityRunHandlers(
      { handle: (channel: string, fn: never) => { handlers.set(channel, fn) } },
      async () => null,
      async (p) => { opened.push(p); return '' },
    )
    expect([...handlers.keys()].sort()).toEqual([
      'studio:exportPhaseReport', 'studio:getNarrativeCoverage', 'studio:getReviewStanding',
      'studio:openReport', 'studio:runIntake', 'studio:runStrictReviewCheck',
    ])

    const call = (channel: string, ...args: unknown[]) => (handlers.get(channel) as (...a: unknown[]) => Promise<unknown>)({}, ...args)
    const NO_PLUGIN = 'Shepherd plugin scripts not found'
    expect(await call('studio:exportPhaseReport', 'p', '0', false)).toEqual({ ok: false, error: NO_PLUGIN, reports: [] })
    expect(await call('studio:runIntake', 'p')).toMatchObject({ ok: false, error: NO_PLUGIN, documents: [] })
    expect(await call('studio:getNarrativeCoverage', 'p', '0')).toMatchObject({ ok: false, error: NO_PLUGIN, total: 0 })
    expect(await call('studio:getReviewStanding', 'p')).toMatchObject({ ok: false, error: NO_PLUGIN, tracked: 0 })
    expect(await call('studio:runStrictReviewCheck', 'p')).toEqual({ ok: false, error: NO_PLUGIN, mismatches: 0 })
    // Opening a report is a path check and an operating-system call; it never needed the plugin,
    // so a missing plugin is not what refuses it.
    expect(await call('studio:openReport', 'p', 'x.html')).toMatchObject({ ok: false })
    expect(opened).toEqual([])
  })
})
