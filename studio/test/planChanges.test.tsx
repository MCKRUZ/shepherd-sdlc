// @vitest-environment jsdom
/** `Plan changes` (build kit §5 B6-P3; K28; guardrails 26 and 28): one button, one closed `plan` request through
 * `runAdoVerb` on the person's click and never otherwise, and ONE digit-honest line about what the plugin printed —
 * `N to create · M to update · K comments`, a count the plugin did not measure reading "no data" rather than a digit,
 * a read that could not be made reading one of Shepherd's own sentences. The plan the plugin printed is handed to the
 * host (`onPlanned`) so an apply dialog can show those very rows; nothing here sends it anywhere.
 *
 * `plan` writes a plan file and a `planned` ledger line, so the button is a `data-write` — and it never runs on mount,
 * on a timer, or after another verb. `window.studio` is a PARTIAL double.
 *
 * The plan documents below are HAND-WRITTEN (unverified): their shape is read from `ado_sync.py` (`cmd_plan`'s `out`),
 * not captured from a live board. */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AdoVerbRequest } from '../shared/adoVerbArgv'
import type { ActorInfo, AdoVerbResult } from '../shared/types'
import { BOARDS_UNREACHABLE, EXIT_HEADING, NO_ACTOR, NO_DATA, newerPlugin, SCHEMA_NOT_DISCOVERED, WORK_ITEMS_NOT_SET_UP } from '../shared/reasons'
import { BRIDGE_MISSING } from '../src/components/ado/AdoApplyDialog'
import { PlanChanges, planCountsLine, planSaid } from '../src/components/ado/PlanChanges'

const HASH = '1d0617c03373'
const ACTOR: ActorInfo = { name: '@sam-k', source: 'roster' }
const CAPS = ['ado-plan'] as const

/** `plan --kind spec --id 0008 --json`, hand-written (unverified): `cmd_plan`'s `out`. */
const PLANNED = {
  _provenance: 'hand-written (unverified)',
  _command: ['ado_sync.py', 'plan', '--kind', 'spec', '--id', '0008', '--json'],
  value: {
    ok: true, unavailable: false, reason: null, plan: HASH, posture: 'assisted', executed_as: '@sam-k',
    rows: [
      { ref: 'sdlc:spec:0008', kind: 'spec', id: '0008', action: 'update', reason: null, work_item: 4521, rev: 7, type: 'User Story', ops: [{ op: 'replace', path: '/fields/System.State', old: 'Active', new: 'Ready' }], notes: [] },
      { ref: 'sdlc:epic:E1', kind: 'epic', id: 'E1', action: 'create', reason: null, work_item: null, rev: null, type: 'Epic', ops: [{ op: 'add', path: '/fields/System.Title', old: null, new: 'Claims' }], notes: [] },
    ],
    counts: { create: 1, update: 2, link: 0, ambiguous: 0, unmapped: 0, refused: 0, held: 0, in_sync: 0 },
    comments: { planned: true, draft: 3, skipped: 0, refused: 0, unavailable: null },
    hook_line: '2 rows pending · 0 drifted · as of 2026-10-15T09:02Z', notes: [], drift: null,
  },
}
const UNAVAILABLE = (reason: string, host: unknown = null) => ({ ok: true, unavailable: true, reason, host, plan: null, rows: [], counts: null })

function res(exitCode: 0 | 1 | 2 | null, json: Record<string, unknown> | null, over: Partial<AdoVerbResult> = {}): AdoVerbResult {
  return { ok: exitCode === 0, exitCode, refused: exitCode === 2, stdout: '', stderr: '', argv: [], verb: 'plan', json, ...over }
}

let runAdoVerb: ReturnType<typeof vi.fn<(projectPath: string, request: AdoVerbRequest) => Promise<AdoVerbResult>>>
beforeEach(() => {
  runAdoVerb = vi.fn()
  // @ts-expect-error - partial test double: only what the control reaches
  window.studio = { runAdoVerb }
})
afterEach(() => {
  vi.useRealTimers()
  cleanup()
  // @ts-expect-error - cleaning up the test double
  delete window.studio
})

/** A disabled kit Button carries its reason as hidden text inside itself, so a name is matched from its start. */
const planButton = (name = 'Plan changes') => screen.getByRole('button', { name: new RegExp(`^${name}`) }) as HTMLButtonElement
const line = () => screen.getByTestId('plan-result')

describe('PlanChanges: the click is the only trigger', () => {
  it('draws one data-write button and asks the plugin for nothing on mount — not even a day of timers', () => {
    vi.useFakeTimers()
    render(<PlanChanges projectPath="/p" capabilities={[...CAPS]} kind="spec" id="0008" />)
    expect(planButton().hasAttribute('data-write')).toBe(true)
    expect(document.querySelectorAll('[data-write]')).toHaveLength(1)
    act(() => { vi.advanceTimersByTime(24 * 60 * 60 * 1000) })
    expect(runAdoVerb).not.toHaveBeenCalled()
    expect(screen.queryByTestId('plan-result')).toBeNull()
  })

  it('a click is exactly one closed `plan` request for the item, and no other verb', async () => {
    runAdoVerb.mockResolvedValue(res(0, PLANNED.value))
    render(<PlanChanges projectPath="/p" capabilities={[...CAPS]} kind="spec" id="0008" />)
    fireEvent.click(planButton())
    await screen.findByTestId('plan-result')
    expect(runAdoVerb).toHaveBeenCalledTimes(1)
    expect(runAdoVerb).toHaveBeenCalledWith('/p', { verb: 'plan', kind: 'spec', id: '0008' })
    expect(Object.keys(runAdoVerb.mock.calls[0]![1]).sort()).toEqual(['id', 'kind', 'verb'])
  })

  it('a sprint scope is the closed `plan` request with a sprint alone — never a kind or an id beside it', async () => {
    runAdoVerb.mockResolvedValue(res(0, PLANNED.value))
    render(<PlanChanges projectPath="/p" capabilities={[...CAPS]} sprint="S07" label="Plan board changes" />)
    fireEvent.click(planButton('Plan board changes'))
    await screen.findByTestId('plan-result')
    expect(runAdoVerb).toHaveBeenCalledTimes(1)
    expect(runAdoVerb).toHaveBeenCalledWith('/p', { verb: 'plan', sprint: 'S07' })
    expect(Object.keys(runAdoVerb.mock.calls[0]![1]).sort()).toEqual(['sprint', 'verb'])
  })

  it('a second click while the first is running does not start a second plan', async () => {
    let finish: (r: AdoVerbResult) => void = () => {}
    runAdoVerb.mockReturnValue(new Promise<AdoVerbResult>((r) => { finish = r }))
    render(<PlanChanges projectPath="/p" capabilities={[...CAPS]} kind="spec" id="0008" />)
    fireEvent.click(planButton())
    fireEvent.click(screen.getByRole('button', { name: /Planning/ }))
    expect(runAdoVerb).toHaveBeenCalledTimes(1)
    await act(async () => { finish(res(0, PLANNED.value)) })
    expect(runAdoVerb).toHaveBeenCalledTimes(1)
  })

  it('a request the table refuses (no id, a flag-shaped id) never reaches the bridge and says why', async () => {
    render(<PlanChanges projectPath="/p" capabilities={[...CAPS]} kind="spec" id="--all" />)
    fireEvent.click(planButton())
    expect((await screen.findByTestId('plan-result')).getAttribute('data-tone')).toBe('warn')
    expect(runAdoVerb).not.toHaveBeenCalled()
    cleanup()
    render(<PlanChanges projectPath="/p" capabilities={[...CAPS]} />)
    fireEvent.click(planButton())
    expect(await screen.findByText(/needs a kind and an id, or a sprint/)).toBeTruthy()
    expect(runAdoVerb).not.toHaveBeenCalled()
  })
})

describe('PlanChanges: the one line', () => {
  it('reads `N to create · M to update · K comments` from the plugin\'s own counts, and hands the plan to the host', async () => {
    runAdoVerb.mockResolvedValue(res(0, PLANNED.value))
    const onPlanned = vi.fn()
    render(<PlanChanges projectPath="/p" capabilities={[...CAPS]} kind="spec" id="0008" onPlanned={onPlanned} />)
    fireEvent.click(planButton())
    await screen.findByTestId('plan-result')
    expect(line().textContent).toBe('1 to create · 2 to update · 3 comments')
    expect(line().getAttribute('data-tone')).toBe('ok')
    expect(onPlanned).toHaveBeenCalledTimes(1)
    const doc = onPlanned.mock.calls[0]![0]
    expect(doc.plan).toBe(HASH)
    expect(doc.rows).toHaveLength(PLANNED.value.rows.length)
    expect(doc.unavailable).toBe(false)
  })

  it('a measured zero is a digit; one is singular', () => {
    const zero = { ...PLANNED.value, counts: { create: 0, update: 1 }, comments: { planned: true, draft: 1, unavailable: null } }
    expect(planCountsLine(zero)).toBe('0 to create · 1 to update · 1 comment')
    expect(planCountsLine({ ...zero, comments: { planned: true, draft: 0, unavailable: null } })).toBe('0 to create · 1 to update · 0 comments')
  })

  it('a count the plugin did not print is "no data" — never a digit, whichever of the three is missing', () => {
    const none = planCountsLine({ ...PLANNED.value, counts: { create: null, update: null }, comments: { planned: true, draft: null, unavailable: 'no discovered schema' } })
    expect(none).toBe(`${NO_DATA} to create · ${NO_DATA} to update · ${NO_DATA} comments`)
    expect(none).not.toMatch(/\d/)
    const noCounts = planCountsLine({ ...PLANNED.value, counts: null, comments: null })
    expect(noCounts).not.toMatch(/\d/)
    expect(planCountsLine({ ...PLANNED.value, counts: { create: 2 }, comments: undefined })).toBe(`2 to create · ${NO_DATA} to update · ${NO_DATA} comments`)
    // a negative or fractional "count" is not a count
    expect(planCountsLine({ counts: { create: -1, update: 1.5 }, comments: { draft: Number.NaN } })).not.toMatch(/\d/)
  })

  it('an unavailable read is one of Shepherd\'s own digit-free sentences, with the plugin\'s reason beneath it', async () => {
    const say = async (doc: Record<string, unknown>) => {
      cleanup()
      runAdoVerb.mockResolvedValue(res(0, doc))
      render(<PlanChanges projectPath="/p" capabilities={[...CAPS]} kind="spec" id="0008" />)
      fireEvent.click(planButton())
      return (await screen.findByTestId('plan-result')).textContent ?? ''
    }
    const notSetUp = await say(UNAVAILABLE('not configured: run `ado_sync.py config init`'))
    expect(notSetUp.startsWith(WORK_ITEMS_NOT_SET_UP)).toBe(true)
    expect(notSetUp).toContain('not configured: run `ado_sync.py config init`')
    const noSchema = await say(UNAVAILABLE('no discovered schema: run `ado_sync.py discover` first'))
    expect(noSchema.startsWith(SCHEMA_NOT_DISCOVERED)).toBe(true)
    const unreachable = await say(UNAVAILABLE('could not reach the organisation', { name: 'azure-devops', cli_state: 'signed_out' }))
    expect(unreachable.startsWith(BOARDS_UNREACHABLE)).toBe(true)
    const other = await say(UNAVAILABLE('the repository\'s sources do not agree'))
    expect(other.startsWith(NO_DATA)).toBe(true)
    for (const text of [notSetUp, noSchema, unreachable, other]) expect(text.split(' · ')[0]).not.toMatch(/\d/)
  })

  it('an unavailable plan still reaches the host — as a plan with nothing to send, so no Review plan can stand on it', async () => {
    runAdoVerb.mockResolvedValue(res(0, UNAVAILABLE('not configured')))
    const onPlanned = vi.fn()
    render(<PlanChanges projectPath="/p" capabilities={[...CAPS]} kind="spec" id="0008" onPlanned={onPlanned} />)
    fireEvent.click(planButton())
    await screen.findByTestId('plan-result')
    expect(line().getAttribute('data-tone')).toBe('warn')
    expect(onPlanned).toHaveBeenCalledTimes(1)
    expect(onPlanned.mock.calls[0]![0]).toMatchObject({ unavailable: true, plan: null, rows: [] })
  })

  it('an exit code is the truth: 1 is "Not done" and 2 is "Refused by the plugin", each with the plugin\'s own words, and nothing reaches the host', async () => {
    const onPlanned = vi.fn()
    runAdoVerb.mockResolvedValue(res(1, null, { stderr: 'could not write the plan file' }))
    render(<PlanChanges projectPath="/p" capabilities={[...CAPS]} kind="spec" id="0008" onPlanned={onPlanned} />)
    fireEvent.click(planButton())
    await screen.findByTestId('plan-result')
    expect(line().textContent).toBe(`${EXIT_HEADING[1]} · could not write the plan file`)
    expect(line().getAttribute('data-tone')).toBe('warn')
    cleanup()
    runAdoVerb.mockResolvedValue(res(2, null, { stderr: 'unknown kind' }))
    render(<PlanChanges projectPath="/p" capabilities={[...CAPS]} kind="spec" id="0008" onPlanned={onPlanned} />)
    fireEvent.click(planButton())
    await screen.findByTestId('plan-result')
    expect(line().textContent).toBe(`${EXIT_HEADING[2]} · unknown kind`)
    expect(line().getAttribute('data-tone')).toBe('error')
    expect(onPlanned).not.toHaveBeenCalled()
  })

  it('an exit 0 whose document is not a plan is "no data", never a made-up zero; no bridge is said as a sentence', async () => {
    const onPlanned = vi.fn()
    runAdoVerb.mockResolvedValue(res(0, { ok: true }))
    render(<PlanChanges projectPath="/p" capabilities={[...CAPS]} kind="spec" id="0008" onPlanned={onPlanned} />)
    fireEvent.click(planButton())
    await screen.findByTestId('plan-result')
    expect(line().textContent?.startsWith(NO_DATA)).toBe(true)
    expect(line().textContent).not.toMatch(/\d/)
    cleanup()
    runAdoVerb.mockResolvedValue(null as unknown as AdoVerbResult)
    render(<PlanChanges projectPath="/p" capabilities={[...CAPS]} kind="spec" id="0008" onPlanned={onPlanned} />)
    fireEvent.click(planButton())
    await screen.findByTestId('plan-result')
    expect(line().textContent).toContain(BRIDGE_MISSING)
    expect(onPlanned).not.toHaveBeenCalled()
  })

  it('planSaid is pure: the same answer says the same thing without a DOM', () => {
    expect(planSaid(res(0, PLANNED.value)).line).toBe('1 to create · 2 to update · 3 comments')
    expect(planSaid(res(0, PLANNED.value)).doc?.plan).toBe(HASH)
    expect(planSaid(null).doc).toBeNull()
    expect(planSaid(res(1, null)).line).toBe(EXIT_HEADING[1])
  })
})

describe('PlanChanges: disabled means a reason', () => {
  it('a plugin without ado-plan disables it with the capability it lacks, and a click runs nothing', () => {
    render(<PlanChanges projectPath="/p" capabilities={['ado-status-json']} kind="spec" id="0008" />)
    const button = planButton()
    expect(button.disabled).toBe(true)
    expect(button.getAttribute('title')).toBe(newerPlugin('ado-plan'))
    fireEvent.click(button)
    expect(runAdoVerb).not.toHaveBeenCalled()
  })

  it('capabilities not known yet leave the plugin to answer: the button is live', () => {
    render(<PlanChanges projectPath="/p" capabilities={null} kind="spec" id="0008" />)
    expect(planButton().disabled).toBe(false)
    cleanup()
    render(<PlanChanges projectPath="/p" capabilities={undefined} kind="spec" id="0008" />)
    expect(planButton().disabled).toBe(false)
  })

  it('nobody identified: disabled with NO_ACTOR, main would refuse every verb; a named actor leaves it live; the missing capability is said first', () => {
    render(<PlanChanges projectPath="/p" capabilities={[...CAPS]} kind="spec" id="0008" actor={null} />)
    expect(planButton().disabled).toBe(true)
    expect(planButton().getAttribute('title')).toBe(NO_ACTOR)
    cleanup()
    render(<PlanChanges projectPath="/p" capabilities={[...CAPS]} kind="spec" id="0008" actor={ACTOR} />)
    expect(planButton().disabled).toBe(false)
    cleanup()
    render(<PlanChanges projectPath="/p" capabilities={[]} kind="spec" id="0008" actor={null} />)
    expect(planButton().getAttribute('title')).toBe(newerPlugin('ado-plan'))
  })

  it('steering mode draws nothing at all: no button, no line, no request', () => {
    const { container } = render(<PlanChanges projectPath="/p" capabilities={[...CAPS]} kind="spec" id="0008" steering />)
    expect(container.innerHTML).toBe('')
    expect(document.querySelectorAll('[data-write], button')).toHaveLength(0)
    expect(runAdoVerb).not.toHaveBeenCalled()
  })
})

describe('PlanChanges holds no timer and no effect', () => {
  const code = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, '').split(/\r?\n/).map((l) => l.replace(/(^|\s)\/\/.*$/, '')).join('\n')
  const source = code(readFileSync(resolve(__dirname, '..', 'src', 'components', 'ado', 'PlanChanges.tsx'), 'utf-8'))

  it('never schedules anything and never reaches the bridge itself: a click is the only trigger', () => {
    expect(source).not.toMatch(/setInterval|setTimeout|requestAnimationFrame|useEffect|useLayoutEffect/)
    expect(source).not.toMatch(/window\.studio|child_process|['"`]az['"`]/)
    expect(source.match(/data-write/g)).toHaveLength(1)
    // the only request it can build is the closed `plan`
    expect([...source.matchAll(/verb: '(\w+)'/g)].map((m) => m[1])).toEqual(['plan', 'plan'])
    expect(source).not.toMatch(/pullDiscussion|verb: 'pull'|verb: 'apply'/)
  })
})
