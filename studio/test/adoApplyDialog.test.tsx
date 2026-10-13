// @vitest-environment jsdom
/** The Azure Boards apply dialog (build kit §5 B4-P3): the preview IS the plan's rows — the same rows
 * `ado_sync.py plan --json` / `comment --json` printed, nothing recomputed — then one Confirm that sends
 * the plan's 12-hex hash back through `runAdoVerb` and shows the plugin's answer under its exit code alone.
 * The Confirm is a write (`data-write`), is disabled with a reason when the plugin lacks `ado-apply` (or
 * nobody is identified), and never fires twice for one plan. `window.studio` is a PARTIAL double.
 *
 * The plan below is HAND-WRITTEN (unverified): its shape is read from `ado_sync.py` (`_plan_row`,
 * `_update_ops`, `cmd_plan`) and `ado_sync_comments.ROW_KEYS`, not captured from a live board. */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ActorInfo, AdoVerbResult } from '../shared/types'
import { CAPABILITIES, EXIT_HEADING, NO_ACTOR, NO_DATA, newerPlugin, BOARDS_UNREACHABLE, SCHEMA_NOT_DISCOVERED, WORK_ITEMS_NOT_SET_UP } from '../shared/reasons'
import { ADO_VERB_CAPABILITY } from '../shared/adoVerbArgv'
import {
  AdoApplyDialog, APPLY_CONFIRM, BRIDGE_MISSING, opLine, pendingRowCount, readAdoPlan, rowTitle, unavailableSentence,
  type AdoPlanDoc,
} from '../src/components/ado/AdoApplyDialog'

const HASH = '1d0617c03373'
const ACTOR: ActorInfo = { name: '@sam-k', source: 'roster' }

/** `plan --json`, hand-written (unverified). */
const PLAN_JSON = {
  ok: true, unavailable: false, reason: null, plan: HASH, posture: 'assisted', executed_as: '@sam-k',
  rows: [
    {
      ref: 'sdlc:spec:0004', kind: 'spec', id: '0004', action: 'update', reason: null, work_item: 4521, rev: 7, type: 'User Story',
      ops: [
        { op: 'replace', path: '/fields/Custom.RiskTier', old: 'MEDIUM', new: 'HIGH' },
        { op: 'replace', path: '/fields/System.State', old: 'Active', new: 'Ready' },
        { op: 'replace', path: '/fields/System.Tags', add: ['risk:HIGH', 'sdlc:status:ready'], remove: ['risk:MEDIUM'], kept: 0 },
      ],
      notes: [],
    },
    { ref: 'sdlc:epic:E1', kind: 'epic', id: 'E1', action: 'create', reason: null, work_item: null, rev: null, type: 'Epic', ops: [{ op: 'add', path: '/fields/System.Title', old: null, new: 'Claims' }], notes: ['required field Custom.Area has no value'] },
    { ref: 'sdlc:spec:0009', kind: 'spec', id: '0009', action: 'held', reason: '#4522 is gone from the board', work_item: 4522, rev: null, type: 'User Story', ops: [], notes: [] },
    {
      ref: 'sdlc:spec:0004', kind: 'comment', action: 'comment', status: 'draft', reason: null, detail: null, work_item: 4521, target: 'sdlc:spec:0004',
      text: '<img src=x onerror="boom()"> first line\nsecond line', ops: [], notes: [],
    },
  ],
  counts: { create: 1, update: 1 },
}

function plan(): AdoPlanDoc {
  const read = readAdoPlan(PLAN_JSON)
  if (!read) throw new Error('fixture plan did not read')
  return read
}

function answer(exitCode: number | null, over: Partial<AdoVerbResult> = {}): AdoVerbResult {
  return {
    ok: exitCode === 0, exitCode, refused: exitCode === 2, verb: 'apply', json: null,
    stdout: exitCode === 0 ? 'applied 2 rows' : '', stderr: exitCode === 0 ? '' : exitCode === 2 ? 'refused: --by "Claude" is not a person' : 'one row failed: conflict on #4521',
    argv: ['apply', '--confirm', HASH, '--json', '--by', '@sam-k'], ...over,
  }
}

let runAdoVerb: ReturnType<typeof vi.fn>
beforeEach(() => {
  runAdoVerb = vi.fn().mockResolvedValue(answer(0))
  // @ts-expect-error - partial test double: only what the dialog reaches
  window.studio = { runAdoVerb }
})
afterEach(async () => {
  cleanup()
  // Radix's FocusScope sends its unmount event from a setTimeout(0) scheduled during cleanup. Let that timer fire
  // while jsdom is still this file's environment: a file that ends right after closing a dialog otherwise reports an
  // unhandled "parameter 1 is not of type 'Event'" at teardown (Node's own CustomEvent by then). Same-delay timers
  // fire in the order they were set, so one macrotask after cleanup is enough.
  await new Promise((resolve) => setTimeout(resolve, 0))
  // @ts-expect-error - cleaning up the test double
  delete window.studio
})

function mount(over: Partial<Parameters<typeof AdoApplyDialog>[0]> = {}) {
  const props = { open: true, projectPath: '/p', plan: plan(), capabilities: [CAPABILITIES.adoApply], actor: ACTOR, onClose: vi.fn(), onApplied: vi.fn(), ...over }
  render(<main><AdoApplyDialog {...props} /></main>)
  return props
}

const confirmButton = () => screen.getByRole('button', { name: new RegExp(`^${APPLY_CONFIRM}`) }) as HTMLButtonElement
const reasonOf = (el: HTMLElement) => el.getAttribute('title') ?? ''
const describedBy = (el: HTMLElement) => (el.getAttribute('aria-describedby') ?? '').split(/\s+/).map((id) => document.getElementById(id)?.textContent ?? '').join(' ').trim()

describe('readAdoPlan — the plan document as the plugin printed it', () => {
  it('reads the hash, the rows and who az will send as; a document that is not a plan is null, never an empty plan', () => {
    const doc = plan()
    expect(doc.plan).toBe(HASH)
    expect(doc.rows).toHaveLength(PLAN_JSON.rows.length)
    expect(doc.executedAs).toBe('@sam-k')
    expect(doc.posture).toBe('assisted')
    expect(doc.unavailable).toBe(false)
    expect(readAdoPlan(null)).toBeNull()
    expect(readAdoPlan([])).toBeNull()
    expect(readAdoPlan('plan')).toBeNull()
    expect(readAdoPlan({ ok: true, rows: [] })).toBeNull()
    expect(readAdoPlan({ plan: 'not-a-hash', rows: [] })).toBeNull()
  })

  it('a comment verb\'s single `row` is a one-row plan; `plan: null` (plan-only) has no hash to confirm', () => {
    const row = PLAN_JSON.rows[3]
    const one = readAdoPlan({ ok: true, plan: HASH, posture: 'assisted', apply_offered: true, row })
    expect(one?.rows).toHaveLength(1)
    expect(one?.rows[0]?.text).toContain('second line')
    const planOnly = readAdoPlan({ ok: true, plan: null, posture: 'plan-only', apply_offered: false, row })
    expect(planOnly?.plan).toBeNull()
    expect(planOnly?.rows).toHaveLength(1)
  })

  it('an unavailable read keeps the plugin\'s reason verbatim, and says whether az was the reason (a host block)', () => {
    const doc = readAdoPlan({ ok: true, unavailable: true, reason: 'no discovered schema: run `ado_sync.py discover` first', host: null, plan: null, rows: [], counts: null })
    expect(doc?.unavailable).toBe(true)
    expect(doc?.reason).toBe('no discovered schema: run `ado_sync.py discover` first')
    expect(doc?.rows).toEqual([])
  })

  it('the four no-data sentences are words, digit-free, picked from what the plugin said it could not do', () => {
    const say = (reason: string, host: unknown = null) => unavailableSentence(readAdoPlan({ ok: true, unavailable: true, reason, host, plan: null, rows: [] })!)
    expect(say('not configured: .sdlc/ado.yaml does not exist (run `ado_sync.py config init`)')).toBe(WORK_ITEMS_NOT_SET_UP)
    expect(say('no discovered schema: run `ado_sync.py discover` first, so there is a process to read against')).toBe(SCHEMA_NOT_DISCOVERED)
    expect(say('az could not be started', { cli: 'az' })).toBe(BOARDS_UNREACHABLE)
    // Anything else is "no data" with the plugin's own reason beneath — never a guess at which of the four.
    expect(say('the repository\'s sources do not agree: spec 0004')).toBe(NO_DATA)
    for (const sentence of [WORK_ITEMS_NOT_SET_UP, SCHEMA_NOT_DISCOVERED, BOARDS_UNREACHABLE, NO_DATA]) expect(sentence).not.toMatch(/\d/)
  })

  it('counts what an apply would send: creates, updates and drafted comments — not a held, refused or skipped row', () => {
    expect(pendingRowCount(plan())).toBe(3)
    const doc = readAdoPlan({ plan: HASH, rows: [{ ref: 'sdlc:spec:0001', action: 'refused' }, { ref: 'sdlc:spec:0002', action: 'comment', status: 'skipped' }, { ref: 'sdlc:spec:0003', action: 'comment', status: 'refused' }] })!
    expect(pendingRowCount(doc)).toBe(0)
  })

  it('names a row by its ref (`spec 0004`), else the work item it was addressed to, else "work item"', () => {
    const [update, , , comment] = plan().rows
    expect(rowTitle(update!)).toBe('spec 0004')
    expect(rowTitle(comment!)).toBe('spec 0004')
    expect(rowTitle({ ...comment!, ref: null, target: '#4521' })).toBe('#4521')
    expect(rowTitle({ ...comment!, ref: null, target: null })).toBe('work item')
  })

  it('writes an op the way the plan prints it: `field  old → new`, a tag change as + and -, `(none)` for nothing', () => {
    expect(opLine({ op: 'replace', path: '/fields/System.State', old: 'Active', new: 'Ready' })).toBe('System.State  Active → Ready')
    expect(opLine({ op: 'add', path: '/fields/System.Title', old: null, new: 'Claims' })).toBe('System.Title  (none) → Claims')
    expect(opLine({ op: 'replace', path: '/fields/System.Tags', add: ['risk:HIGH'], remove: ['risk:MEDIUM'], kept: 0 })).toBe('System.Tags  + risk:HIGH  - risk:MEDIUM')
  })
})

describe('AdoApplyDialog — the preview is the plan', () => {
  it('draws one row per plan row, in the plan\'s order, with each op and note the plan carried', () => {
    mount()
    const dialog = screen.getByTestId('ado-apply-dialog')
    const rows = Array.from(dialog.querySelectorAll<HTMLElement>('[data-plan-row]'))
    expect(rows).toHaveLength(PLAN_JSON.rows.length)
    expect(rows.map((r) => r.getAttribute('data-action'))).toEqual(['update', 'create', 'held', 'comment'])
    const update = rows[0]!
    expect(update.textContent).toContain('spec 0004')
    expect(update.textContent).toContain('#4521')
    expect(Array.from(update.querySelectorAll('[data-plan-op]')).map((o) => o.textContent)).toEqual([
      'Custom.RiskTier  MEDIUM → HIGH', 'System.State  Active → Ready', 'System.Tags  + risk:HIGH  + sdlc:status:ready  - risk:MEDIUM',
    ])
    expect(rows[1]!.textContent).toContain('required field Custom.Area has no value')
    expect(rows[2]!.textContent).toContain('#4522 is gone from the board')
    expect(rows[2]!.querySelectorAll('[data-plan-op]')).toHaveLength(0)
  })

  it('a comment row shows the exact text the board will carry — as text, never as markup', () => {
    mount()
    const comment = document.querySelector('[data-plan-row][data-action="comment"]') as HTMLElement
    const text = comment.querySelector('[data-plan-text]') as HTMLElement
    expect(text.textContent).toBe('<img src=x onerror="boom()"> first line\nsecond line')
    expect(comment.querySelector('img')).toBeNull()
    expect(comment.textContent).toContain('draft')
  })

  it('shows the exact line it will run, who it is recorded against and who az will send as, before anything runs', () => {
    mount()
    expect(screen.getByTestId('ado-apply-argv').textContent).toBe(`Run: ado_sync.py apply --confirm ${HASH} --json --by @sam-k`)
    expect(screen.getByTestId('ado-apply-actor').textContent).toContain('@sam-k')
    expect(screen.getByTestId('ado-apply-sender').textContent).toContain('@sam-k')
    expect(runAdoVerb).not.toHaveBeenCalled()
  })

  it('says so when az has not been read yet, rather than naming nobody as a person', () => {
    mount({ plan: readAdoPlan({ ...PLAN_JSON, executed_as: null })! })
    expect(screen.getByTestId('ado-apply-sender').textContent).toContain('not been read yet')
  })

  it('renders nothing while closed', () => {
    mount({ open: false })
    expect(screen.queryByTestId('ado-apply-dialog')).toBeNull()
    expect(document.querySelectorAll('[data-write]')).toHaveLength(0)
  })
})

describe('AdoApplyDialog — Confirm', () => {
  it('is a write, enabled with the capability and an actor; one click sends the plan\'s hash once and shows "Done" with the plugin\'s words', async () => {
    const props = mount()
    const confirm = confirmButton()
    expect(confirm.hasAttribute('data-write')).toBe(true)
    expect(confirm.disabled).toBe(false)
    fireEvent.click(confirm)
    await waitFor(() => expect(screen.getByTestId('ado-apply-result')).toBeTruthy())
    expect(runAdoVerb).toHaveBeenCalledTimes(1)
    expect(runAdoVerb).toHaveBeenCalledWith('/p', { verb: 'apply', confirm: HASH })
    const result = screen.getByTestId('ado-apply-result')
    expect(within(result).getByText(EXIT_HEADING[0])).toBeTruthy()
    expect(result.textContent).toContain('applied 2 rows')
    expect(props.onApplied).toHaveBeenCalledTimes(1)
    // The plan was sent; the way to send it again is gone, so a double click cannot become a second apply.
    expect(screen.queryByRole('button', { name: new RegExp(`^${APPLY_CONFIRM}`) })).toBeNull()
  })

  it('exit 2 reads "Refused by the plugin" with its stderr verbatim; exit 1 "Not done"; neither says the board changed', async () => {
    runAdoVerb.mockResolvedValueOnce(answer(2))
    const first = mount()
    fireEvent.click(confirmButton())
    const refused = await screen.findByTestId('ado-apply-result')
    expect(within(refused).getByText(EXIT_HEADING[2])).toBeTruthy()
    expect(refused.textContent).toContain('refused: --by "Claude" is not a person')
    expect(refused.getAttribute('data-exit-code')).toBe('2')
    expect(first.onApplied).not.toHaveBeenCalled()
    cleanup()

    runAdoVerb.mockResolvedValueOnce(answer(1))
    const second = mount()
    fireEvent.click(confirmButton())
    const failed = await screen.findByTestId('ado-apply-result')
    expect(within(failed).getByText(EXIT_HEADING[1])).toBeTruthy()
    expect(failed.textContent).toContain('one row failed: conflict on #4521')
    expect(second.onApplied).not.toHaveBeenCalled()
  })

  it('a refusal made in Shepherd before the plugin was asked (exitCode null) is "Not done" with its reason', async () => {
    runAdoVerb.mockResolvedValueOnce(answer(null, { stderr: 'Sign in or type your name' }))
    mount()
    fireEvent.click(confirmButton())
    const result = await screen.findByTestId('ado-apply-result')
    expect(result.getAttribute('data-exit-code')).toBe('none')
    expect(within(result).getByText(EXIT_HEADING[1])).toBeTruthy()
    expect(result.textContent).toContain('Sign in or type your name')
  })

  it('without ado-apply it is disabled with the newer-plugin reason — on the title and as its description — and a click runs nothing', () => {
    mount({ capabilities: ['sprint-status'] })
    const confirm = confirmButton()
    const reason = newerPlugin(ADO_VERB_CAPABILITY.apply)
    expect(confirm.disabled).toBe(true)
    expect(reasonOf(confirm)).toBe(reason)
    expect(describedBy(confirm)).toBe(reason)
    fireEvent.click(confirm)
    expect(runAdoVerb).not.toHaveBeenCalled()
    // The preview still reads: seeing the plan needs no capability.
    expect(document.querySelectorAll('[data-plan-row]')).toHaveLength(PLAN_JSON.rows.length)
  })

  it('capabilities not known yet (undefined) leave the plugin to decide: enabled', () => {
    mount({ capabilities: undefined })
    expect(confirmButton().disabled).toBe(false)
  })

  it('nobody identified: disabled with NO_ACTOR, ahead of the capability reason', () => {
    mount({ actor: null, capabilities: [] })
    const confirm = confirmButton()
    expect(confirm.disabled).toBe(true)
    expect(reasonOf(confirm)).toBe(NO_ACTOR)
    fireEvent.click(confirm)
    expect(runAdoVerb).not.toHaveBeenCalled()
  })

  it('a plan with no hash to confirm (plan-only comment) is disabled with the table\'s own sentence — never a request with a made-up hash', () => {
    mount({ plan: readAdoPlan({ plan: null, posture: 'plan-only', row: PLAN_JSON.rows[3] })! })
    const confirm = confirmButton()
    expect(confirm.disabled).toBe(true)
    expect(reasonOf(confirm)).toContain('12-hex hash')
    fireEvent.click(confirm)
    expect(runAdoVerb).not.toHaveBeenCalled()
  })

  it('a bridge with no runAdoVerb (an older preload) says so instead of throwing', async () => {
    // @ts-expect-error - a bridge without the Boards verb
    window.studio = {}
    const props = mount()
    fireEvent.click(confirmButton())
    expect((await screen.findByTestId('ado-apply-result')).textContent).toContain(BRIDGE_MISSING)
    expect(props.onApplied).not.toHaveBeenCalled()
  })

  it('Cancel closes without running anything', () => {
    const props = mount()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(props.onClose).toHaveBeenCalledTimes(1)
    expect(runAdoVerb).not.toHaveBeenCalled()
  })
})

describe('AdoApplyDialog — a plan that could not be drawn up', () => {
  const unavailable = (reason: string, host: unknown = null) => readAdoPlan({ ok: true, unavailable: true, reason, host, plan: null, rows: [], counts: null })!

  it.each([
    ['not configured: .sdlc/ado.yaml does not exist (run `ado_sync.py config init`)', null, WORK_ITEMS_NOT_SET_UP],
    ['no discovered schema: run `ado_sync.py discover` first', null, SCHEMA_NOT_DISCOVERED],
    ['az exited with an error', { cli: 'az' }, BOARDS_UNREACHABLE],
  ])('%s → the heading is words, the plugin\'s reason sits beneath it, there are no rows, and Confirm carries that reason', (reason, host, sentence) => {
    mount({ plan: unavailable(reason, host) })
    const notice = screen.getByTestId('ado-apply-unavailable')
    expect(within(notice).getByText(sentence)).toBeTruthy()
    expect(sentence).not.toMatch(/\d/)
    expect(notice.textContent).toContain(reason)
    expect(document.querySelectorAll('[data-plan-row]')).toHaveLength(0)
    const confirm = confirmButton()
    expect(confirm.disabled).toBe(true)
    expect(reasonOf(confirm)).toBe(reason)
    fireEvent.click(confirm)
    expect(runAdoVerb).not.toHaveBeenCalled()
  })
})
