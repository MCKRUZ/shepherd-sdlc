import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../electron/main/project', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../electron/main/project')>()),
  runPluginScript: vi.fn(),
}))

import { getStageReadiness } from '../electron/main/readiness'
import { runPluginScript } from '../electron/main/project'
import type { ConsoleEntry } from '../shared/types'

// Spec 0024: readiness carries the plugin's activities, definition, warnings and capabilities.
// An old plugin emits none of them, and that must stay distinguishable from "emitted an empty list".

const run = vi.mocked(runPluginScript)

const entry = (stdout: string, ok = true): ConsoleEntry => ({
  id: 'x', command: 'py', args: [], cwd: '', startedAt: '', durationMs: 0,
  exitCode: ok ? 0 : 1, stdout, stderr: '', ok,
})

const BASE = {
  stage: { id: '2', name: 'design', display: 'Phase 2: Design', is_current: true },
  sign_off: { status: 'pending', completed_at: null, signed_off_by: null },
  artifacts: [],
  judgement_conditions: [],
  blocking_count: 0,
  ready: true,
}

const DATA = {
  id: 'data', label: 'Data contract', command: 'sprd-data', kind: 'create', optional: true,
  creates: ['.sdlc/artifacts/02-design/data/data-contract.md'], after: [], status: 'available', reason: null,
}

function plugin(readiness: object, status: () => ConsoleEntry = () => entry(JSON.stringify({ capabilities: ['activities', 'rules-check'] }))) {
  run.mockImplementation(async (_dir, script) =>
    script === 'stage_readiness.py' ? entry(JSON.stringify(readiness)) : status())
}

let n = 0
const freshPlugin = () => `C:/fake/plugin-${++n}/scripts`
const statusCalls = () => run.mock.calls.filter((c) => c[1] === 'generate_status.py')

beforeEach(() => run.mockReset())

describe('getStageReadiness — activities from the plugin', () => {
  it('maps activities, definition and warnings from the plugin document', async () => {
    plugin({ ...BASE, activities: [DATA], definition: 'phases/02-design.md', warnings: ['one declaration is broken'] })
    const r = await getStageReadiness('C:/p', freshPlugin(), '2')
    expect(r.activities).toEqual([DATA])
    expect(r.definition).toBe('phases/02-design.md')
    expect(r.warnings).toEqual(['one declaration is broken'])
  })

  it('leaves activities undefined for an old plugin, and never asks it for capabilities', async () => {
    plugin(BASE)
    const r = await getStageReadiness('C:/p', freshPlugin(), '2')
    expect(r.ok).toBe(true)
    expect(r.activities).toBeUndefined()
    expect('activities' in r).toBe(false)
    expect(r.capabilities).toBeUndefined()
    expect(statusCalls()).toHaveLength(0)
  })

  it('keeps an emitted empty list as an empty list', async () => {
    plugin({ ...BASE, activities: [] })
    expect((await getStageReadiness('C:/p', freshPlugin(), '2')).activities).toEqual([])
  })
})

describe('getStageReadiness — capabilities', () => {
  it('reads them from generate_status.py --json for the project state file', async () => {
    plugin({ ...BASE, activities: [DATA] })
    const r = await getStageReadiness('C:/p', freshPlugin(), '2')
    expect(r.capabilities).toEqual(['activities', 'rules-check'])
    expect(statusCalls()[0][2]).toEqual(['--state', expect.stringMatching(/C:[\\/]p[\\/]\.sdlc[\\/]state\.yaml$/), '--json'])
  })

  it('reads them once per plugin, not once per readiness poll', async () => {
    plugin({ ...BASE, activities: [DATA] })
    const dir = freshPlugin()
    await getStageReadiness('C:/p', dir, '2')
    await getStageReadiness('C:/p', dir, '2')
    await getStageReadiness('C:/p', dir, '2')
    expect(statusCalls()).toHaveLength(1)
  })

  it('reads them separately for a different plugin', async () => {
    plugin({ ...BASE, activities: [DATA] })
    await getStageReadiness('C:/p', freshPlugin(), '2')
    await getStageReadiness('C:/p', freshPlugin(), '2')
    expect(statusCalls()).toHaveLength(2)
  })

  it.each([
    ['the script fails', () => entry('', false)],
    ['the output is not JSON', () => entry('Traceback...')],
    ['the key is absent', () => entry(JSON.stringify({ stages: [] }))],
    ['the key is not a list of strings', () => entry(JSON.stringify({ capabilities: [1, 2] }))],
  ])('yields undefined capabilities, not an error or an empty list, when %s', async (_name, status) => {
    plugin({ ...BASE, activities: [DATA] }, status)
    const r = await getStageReadiness('C:/p', freshPlugin(), '2')
    expect(r.ok).toBe(true)
    expect(r.capabilities).toBeUndefined()
    expect(r.activities).toEqual([DATA])
  })

  it('does not pin a failed read for the session: the next poll tries again', async () => {
    const dir = freshPlugin()
    plugin({ ...BASE, activities: [DATA] }, () => entry('', false))
    await getStageReadiness('C:/p', dir, '2')
    plugin({ ...BASE, activities: [DATA] })
    const r = await getStageReadiness('C:/p', dir, '2')
    expect(r.capabilities).toEqual(['activities', 'rules-check'])
  })
})
