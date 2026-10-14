// @vitest-environment jsdom
/** The Azure Boards reconcile dialog (build kit §5 B5-P4; design §12 item 6): the VerbDialog pattern for settling
 * the drift `pull` recorded. One `Segmented` per drifted field (leave open · take the board's · keep the
 * repository's · acknowledge · not drift) beside the field's own diff (the existing `ClashDiff`, Yours / Theirs),
 * a preview that IS the argv line each chosen field would run, and ONE `data-write` Confirm — which runs one
 * `reconcile` per chosen field, in order, as the signed-in person, and stops at the first one the plugin did not
 * settle. Disabled means a reason, always. A result whose JSON carries `proposed` names that `.proposed` file and
 * says the artifact itself was not changed. Steering mode draws nothing.
 *
 * The rows come from the `pull --json` document (`readDriftItems`): `old`/`new` are the board's value when the
 * item was last sent and now — the plugin leaves both out for text and person fields, so a field without them is
 * said to have no printed values, never drawn as an empty diff. Every plugin document below is HAND-WRITTEN
 * (unverified): its shape is read from `ado_sync.py` (`_observe`, `classify_drift`, `_reconcile`) and
 * `ado_sync_reconcile.py` (`proposals`, `write_proposed`), not captured from a live board. */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AdoSyncView } from '../shared/adoTypes'
import type { AdoVerbRequest } from '../shared/adoVerbArgv'
import type { ActorInfo, AdoVerbResult, BoardRow, CommandCenter, ConnectionInfo, SourcedBlock, SpecCard as SpecCardRead } from '../shared/types'
import { CAPABILITIES, EXIT_HEADING, NO_ACTOR, newerPlugin } from '../shared/reasons'
import {
  AdoReconcileDialog, CHOOSE_A_TAKE, NOT_DRIFT_CLASSES, RECONCILE_CONFIRM, readDriftItems, WHOLE_ITEM_CLASSES, type AdoDriftItem,
} from '../src/components/ado/AdoReconcileDialog'
import { SpecCard } from '../src/components/SpecCard/SpecCard'
import { connectionStore, resetConnectionStore } from '../src/stores/connectionStore'

const REF = 'sdlc:spec:0004'
const ACTOR: ActorInfo = { name: '@sam-k', source: 'roster' }
const CAPS = [CAPABILITIES.adoReconcile] as const

/** `pull --json` (hand-written, unverified). Item 1 has three settleable fields (one without printed values), one
 * field a `COMMENT` (not drift: left out) and one the table cannot name (`relations:parent`); item 2 is gone from the
 * board; item 3 is in sync; item 4 could not be read. */
const PULL = {
  ok: true, unavailable: false, reason: null, as_of: '2026-10-13T09:02:00Z', counts: {}, unmatched_ids: [], notes: [],
  items: [
    {
      ref: REF, kind: 'spec', work_item: 4521, rev: 9, class: 'SDLC_OWNED_DRIFT', unavailable: null, attachments: [], ignored: [],
      fields: [
        { field: 'System.State', class: 'SDLC_OWNED_DRIFT', owner: 'S', rev: 8, revised_at: '2026-10-12T10:00:00Z', old: 'Active', new: 'Closed' },
        { field: 'Custom.RiskTier', class: 'SDLC_OWNED_DRIFT', owner: 'S', rev: 9, revised_at: '2026-10-12T11:00:00Z', old: 'MEDIUM', new: 'HIGH' },
        { field: 'System.AssignedTo', class: 'SDLC_OWNED_DRIFT', owner: 'S', rev: 9, revised_at: '2026-10-12T11:00:00Z' },
        { field: 'System.History', class: 'COMMENT', owner: null, rev: 9, revised_at: '2026-10-12T11:00:00Z' },
        { field: 'relations:parent', class: 'ADO_OWNED_CHANGE', owner: 'A', rev: 9, revised_at: null, added: [4400], removed: [] },
      ],
    },
    { ref: 'sdlc:spec:0005', kind: 'spec', work_item: 4522, rev: null, class: 'DELETED_IN_ADO', unavailable: null, fields: [], attachments: [], ignored: [] },
    { ref: 'sdlc:spec:0006', kind: 'spec', work_item: 4523, rev: 3, class: 'IN_SYNC', unavailable: null, fields: [], attachments: [], ignored: [] },
    { ref: 'sdlc:spec:0007', kind: 'spec', work_item: 4524, rev: null, class: null, unavailable: 'the ledger line that linked it has no rev_after; link it again to set the baseline', fields: [], attachments: [], ignored: [] },
  ],
  proposals: [
    { ref: REF, kind: 'spec', field: 'System.State', class: 'SDLC_OWNED_DRIFT', action: 'report', text: 'never taken: a spec\'s State is moved by its own verbs <img src=x onerror="boom()">' },
    { ref: REF, kind: 'spec', field: 'Custom.RiskTier', class: 'SDLC_OWNED_DRIFT', action: 'report', text: 'the repository\'s value is re-pushed on the next apply; `--take sdlc` records that choice' },
    { ref: REF, kind: 'spec', field: 'System.AssignedTo', class: 'SDLC_OWNED_DRIFT', action: 'reconcile', text: '`reconcile … --take ado` runs `spec_transition.py assign --developer @priya-n`' },
    { ref: 'sdlc:spec:0005', kind: 'spec', field: null, class: 'DELETED_IN_ADO', action: 'reconcile', text: 'gone from the board; `--take ack --owner <you>` records that someone knows' },
  ],
}

/** `reconcile --json` (hand-written, unverified): `_reconcile`'s `out`. */
function reconciled(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    ok: true, ref: REF, kind: 'spec', field: 'System.AssignedTo', class: 'SDLC_OWNED_DRIFT', take: 'ado', disposition: 'TAKE_ADO', by: '@sam-k', owner: null,
    settled: true, settled_why: 'off the books',
    child: { verb: 'assign', argv: ['assign', '--developer', '@priya-n'], exit: 0, stdout: 'assigned 0004 to @priya-n', stderr: '' }, notes: [], ...over,
  }
}

function res(exitCode: 0 | 1 | 2 | null, json: Record<string, unknown> | null, over: Partial<AdoVerbResult> = {}): AdoVerbResult {
  return { ok: exitCode === 0, exitCode, refused: exitCode === 2, stdout: '', stderr: '', argv: [], verb: 'reconcile', json, ...over }
}

const items = readDriftItems(PULL)
const itemOf = (ref: string): AdoDriftItem => {
  const found = items.find((i) => i.ref === ref)
  if (!found) throw new Error(`no ${ref} in the fixture`)
  return found
}

let runAdoVerb: ReturnType<typeof vi.fn<(projectPath: string, request: AdoVerbRequest) => Promise<AdoVerbResult>>>
beforeEach(() => {
  runAdoVerb = vi.fn()
  // @ts-expect-error - partial test double: only what the dialog reaches
  window.studio = { runAdoVerb }
})
afterEach(async () => {
  cleanup()
  // Radix's FocusScope sends its unmount event from a setTimeout(0) scheduled during cleanup (see adoApplyDialog.test).
  await new Promise((resolve) => setTimeout(resolve, 0))
  resetConnectionStore()
  // @ts-expect-error - cleaning up the test double
  delete window.studio
})

function mount(over: Partial<Parameters<typeof AdoReconcileDialog>[0]> = {}) {
  const props = { open: true, projectPath: '/p', item: itemOf(REF), capabilities: [...CAPS], actor: ACTOR, onClose: vi.fn(), onSettled: vi.fn(), ...over }
  const utils = render(<main><AdoReconcileDialog {...props} /></main>)
  return { props, ...utils }
}

const group = (field: string) => screen.getByRole('group', { name: `Take for ${field}` })
const pick = (field: string, label: string) => fireEvent.click(within(group(field)).getByRole('button', { name: label }))
const confirmButton = () => screen.getByRole('button', { name: new RegExp(`^${RECONCILE_CONFIRM}`) }) as HTMLButtonElement
const preview = () => screen.getByTestId('reconcile-preview')
const verbsCalled = () => runAdoVerb.mock.calls.map(([, request]) => request)

// ── readDriftItems ───────────────────────────────────────────────────────────────────────────────

describe('readDriftItems — the rows of the document `pull --json` printed', () => {
  it('keeps an item only when it has something to settle, in the plugin\'s order, and joins each field\'s proposal by ref and field', () => {
    expect(items.map((i) => i.ref)).toEqual([REF, 'sdlc:spec:0005'])
    const spec = itemOf(REF)
    expect(spec.workItem).toBe(4521)
    expect(spec.fields.map((f) => f.field)).toEqual(['System.State', 'Custom.RiskTier', 'System.AssignedTo', 'relations:parent'])
    expect(spec.fields[0]).toMatchObject({ class: 'SDLC_OWNED_DRIFT', owner: 'S', hasValues: true, old: 'Active', new: 'Closed' })
    expect(spec.fields[0]!.proposal).toMatchObject({ action: 'report' })
    expect(spec.fields[2]!.proposal?.text).toContain('spec_transition.py assign')
  })

  it('a field the plugin printed no old/new for (a text or person field) has no values — never an empty diff', () => {
    const assigned = itemOf(REF).fields.find((f) => f.field === 'System.AssignedTo')!
    expect(assigned.hasValues).toBe(false)
    const parent = itemOf(REF).fields.find((f) => f.field === 'relations:parent')!
    expect(parent.hasValues).toBe(false)
  })

  it('not-drift classes (comment, in sync, never pushed) and an unreadable item are left out; a lost item is one whole-item row', () => {
    expect(itemOf(REF).fields.some((f) => f.field === 'System.History')).toBe(false)
    expect(items.some((i) => i.ref === 'sdlc:spec:0006' || i.ref === 'sdlc:spec:0007')).toBe(false)
    const gone = itemOf('sdlc:spec:0005')
    expect(gone.fields).toHaveLength(1)
    expect(gone.fields[0]).toMatchObject({ field: null, class: 'DELETED_IN_ADO', hasValues: false })
    expect(gone.fields[0]!.proposal?.text).toContain('records that someone knows')
  })

  it('a value that is a number, null or a list reads as text; a document that is not a pull is no items at all', () => {
    const doc = { items: [{ ref: REF, kind: 'spec', work_item: 1, class: 'SDLC_OWNED_DRIFT', fields: [
      { field: 'Custom.Count', class: 'SDLC_OWNED_DRIFT', owner: 'S', rev: 2, old: 3, new: null },
      { field: 'System.Tags', class: 'SDLC_OWNED_DRIFT', owner: 'S', rev: 2, old: 'a; b', new: ['a'] },
    ] }], proposals: 'nope' }
    const [only] = readDriftItems(doc)
    expect(only!.fields[0]).toMatchObject({ old: '3', new: '(none)', hasValues: true })
    expect(only!.fields[1]).toMatchObject({ old: 'a; b', new: '["a"]' })
    for (const bad of [null, undefined, [], 'pull', 4, {}, { items: 'x' }, { items: [null, 3, 'x'] }]) expect(readDriftItems(bad), JSON.stringify(bad)).toEqual([])
  })
})

// ── the dialog ───────────────────────────────────────────────────────────────────────────────────

describe('AdoReconcileDialog: one Segmented per drifted field, the diff beside it', () => {
  it('draws a Take group for each field the table can name, all on "Leave open"; the unnameable row is said, not offered', () => {
    mount()
    const groups = screen.getAllByRole('group').filter((g) => (g.getAttribute('aria-label') ?? '').startsWith('Take for '))
    expect(groups.map((g) => g.getAttribute('aria-label'))).toEqual(['Take for System.State', 'Take for Custom.RiskTier', 'Take for System.AssignedTo'])
    for (const g of groups) {
      expect(within(g).getAllByRole('button').map((b) => b.textContent)).toEqual(['Leave open', "Take the board's", "Keep the repository's", 'Acknowledge', 'Not drift'])
      expect(within(g).getByRole('button', { name: 'Leave open' }).getAttribute('aria-pressed')).toBe('true')
      expect(within(g).getAllByRole('button').filter((b) => b.getAttribute('aria-pressed') === 'true')).toHaveLength(1)
    }
    const parent = document.querySelector('[data-field="relations:parent"]') as HTMLElement
    expect(parent.querySelector('[role="group"]')).toBeNull()
    expect(parent.textContent).toContain('/sprd-ado reconcile')
  })

  it('shows the field\'s diff with the existing ClashDiff (Yours / Theirs), and says so when the plugin printed no values', () => {
    mount()
    const state = document.querySelector('[data-field="System.State"]') as HTMLElement
    expect(state.textContent).toContain('Yours')
    expect(state.textContent).toContain('Theirs')
    expect(state.textContent).toContain('Active')
    expect(state.textContent).toContain('Closed')
    const assigned = document.querySelector('[data-field="System.AssignedTo"]') as HTMLElement
    expect(within(assigned).getByTestId('reconcile-no-values').textContent).toMatch(/does not print/)
    expect(assigned.textContent).not.toContain('Yours')
  })

  it('shows the plugin\'s proposal for a field as characters, never markup', () => {
    mount()
    const state = document.querySelector('[data-field="System.State"]') as HTMLElement
    expect(state.textContent).toContain('never taken')
    expect(state.querySelector('img')).toBeNull()
    expect(state.innerHTML).toContain('&lt;img src=x onerror="boom()"&gt;')
  })

  it('the preview IS the argv line each chosen field would run, updated as choices change; fields left open have no line', () => {
    mount()
    expect(within(preview()).queryAllByRole('listitem')).toHaveLength(0)
    pick('System.State', "Take the board's")
    expect(within(preview()).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Run: ado_sync.py reconcile sdlc:spec:0004 --field System.State --take ado --json --by @sam-k',
    ])
    pick('Custom.RiskTier', 'Not drift')
    fireEvent.change(screen.getByLabelText('Reason for Custom.RiskTier'), { target: { value: 'the team re-planned "S09"' } })
    const lines = within(preview()).getAllByRole('listitem').map((li) => li.textContent)
    expect(lines[1]).toBe(`Run: ado_sync.py reconcile sdlc:spec:0004 --field Custom.RiskTier --take not-drift ${JSON.stringify('--reason=the team re-planned "S09"')} --json --by @sam-k`)
    pick('System.State', 'Leave open')
    expect(within(preview()).getAllByRole('listitem')).toHaveLength(1)
  })

  it('acknowledge asks for an owner and not-drift for a reason — and the preview carries them as one --flag=value element each', () => {
    mount()
    pick('System.AssignedTo', 'Acknowledge')
    fireEvent.change(screen.getByLabelText('Owner for System.AssignedTo'), { target: { value: '@priya-n' } })
    expect(within(preview()).getAllByRole('listitem')[0]!.textContent).toBe('Run: ado_sync.py reconcile sdlc:spec:0004 --field System.AssignedTo --take ack --owner=@priya-n --json --by @sam-k')
    expect(screen.queryByLabelText('Reason for System.AssignedTo')).toBeNull()
    pick('System.AssignedTo', "Keep the repository's")
    expect(screen.queryByLabelText('Owner for System.AssignedTo')).toBeNull()
    // an optional reason rides along on a take that has one to give (a decision's resolution, a slate removal)
    fireEvent.change(screen.getByLabelText('Reason for System.AssignedTo (optional)'), { target: { value: 'left the team' } })
    expect(within(preview()).getAllByRole('listitem')[0]!.textContent).toContain(`${JSON.stringify('--reason=left the team')}`)
  })
})

describe('AdoReconcileDialog: one data-write Confirm, disabled with a reason', () => {
  it('has exactly one data-write control, and it is the Confirm', () => {
    mount()
    const writes = document.querySelectorAll('[data-write]')
    expect(writes).toHaveLength(1)
    expect(writes[0]).toBe(confirmButton())
  })

  it('is disabled until a take is chosen (the reason says so), and a take that needs words says which are missing', () => {
    mount()
    expect(confirmButton().disabled).toBe(true)
    expect(confirmButton().getAttribute('title')).toBe(CHOOSE_A_TAKE)
    pick('System.State', 'Acknowledge')
    expect(confirmButton().disabled).toBe(true)
    expect(confirmButton().getAttribute('title')).toContain('System.State: owner is required')
    pick('System.State', 'Not drift')
    expect(confirmButton().getAttribute('title')).toContain('System.State: reason is required')
    fireEvent.change(screen.getByLabelText('Reason for System.State'), { target: { value: 'planned' } })
    expect(confirmButton().disabled).toBe(false)
    expect(confirmButton().getAttribute('title') ?? '').toBe('')
  })

  it('no signed-in person, and a plugin without ado-reconcile, are reasons — the plugin\'s capability sentence verbatim', () => {
    const { unmount } = mount({ actor: null })
    pick('System.State', "Take the board's")
    expect(confirmButton().disabled).toBe(true)
    expect(confirmButton().getAttribute('title')).toBe(NO_ACTOR)
    unmount()
    mount({ capabilities: ['ado-show'] })
    pick('System.State', "Take the board's")
    expect(confirmButton().disabled).toBe(true)
    expect(confirmButton().getAttribute('title')).toBe(newerPlugin('ado-reconcile'))
    expect(runAdoVerb).not.toHaveBeenCalled()
  })

  it('sends one closed reconcile per chosen field, in the dialog\'s order, with no actor in the request; then Confirm is gone', async () => {
    runAdoVerb.mockResolvedValue(res(0, reconciled()))
    const { props } = mount()
    pick('System.State', "Take the board's")
    pick('System.AssignedTo', 'Acknowledge')
    fireEvent.change(screen.getByLabelText('Owner for System.AssignedTo'), { target: { value: '@priya-n' } })
    fireEvent.click(confirmButton())
    await waitFor(() => expect(screen.getAllByTestId('reconcile-result')).toHaveLength(2))
    expect(verbsCalled()).toEqual([
      { verb: 'reconcile', ref: REF, field: 'System.State', take: 'ado' },
      { verb: 'reconcile', ref: REF, field: 'System.AssignedTo', take: 'ack', owner: '@priya-n' },
    ])
    for (const request of verbsCalled()) expect(Object.keys(request).some((k) => /by|actor/i.test(k))).toBe(false)
    expect(screen.getAllByTestId('reconcile-result').map((r) => r.getAttribute('data-exit-code'))).toEqual(['0', '0'])
    expect(screen.getAllByTestId('reconcile-result')[0]!.textContent).toContain(EXIT_HEADING[0])
    expect(screen.getAllByTestId('reconcile-result')[0]!.textContent).toContain('off the books')
    expect(props.onSettled).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('button', { name: new RegExp(`^${RECONCILE_CONFIRM}`) })).toBeNull()
    expect(screen.getAllByRole('button', { name: /^Close/ }).length).toBeGreaterThan(0)
    expect(document.querySelectorAll('[data-write]')).toHaveLength(0)
  })

  it('one click is one run: a double click does not send twice', async () => {
    let release: (value: AdoVerbResult) => void = () => {}
    runAdoVerb.mockImplementation(() => new Promise<AdoVerbResult>((resolve) => { release = resolve }))
    mount()
    pick('System.State', "Keep the repository's")
    const button = confirmButton()   // it relabels itself while it runs, so keep the element
    fireEvent.click(button)
    fireEvent.click(button)
    expect(runAdoVerb).toHaveBeenCalledTimes(1)
    release(res(0, reconciled({ take: 'sdlc', settled: false, settled_why: 'still open until `apply` writes the field', child: null })))
    await screen.findByTestId('reconcile-result')
    expect(runAdoVerb).toHaveBeenCalledTimes(1)
  })

  it('stops at the first field the plugin did not settle: the rest are listed as not run, and a failed first settles nothing', async () => {
    runAdoVerb.mockResolvedValue(res(1, null, { stderr: 'no drift is recorded for sdlc:spec:0004 System.State: run `pull` first' }))
    const { props } = mount()
    pick('System.State', "Take the board's")
    pick('Custom.RiskTier', "Keep the repository's")
    fireEvent.click(confirmButton())
    await screen.findAllByTestId('reconcile-result')
    expect(runAdoVerb).toHaveBeenCalledTimes(1)
    const rows = screen.getAllByTestId('reconcile-result')
    expect(rows[0]!.getAttribute('data-exit-code')).toBe('1')
    expect(rows[0]!.textContent).toContain(EXIT_HEADING[1])
    expect(rows[0]!.textContent).toContain('run `pull` first')
    expect(rows[1]!.getAttribute('data-exit-code')).toBe('none')
    expect(rows[1]!.textContent).toMatch(/not run/i)
    expect(props.onSettled).not.toHaveBeenCalled()
  })

  it('a refusal (exit 2) is said as the plugin\'s own; what settled before it still re-reads the host', async () => {
    runAdoVerb.mockResolvedValueOnce(res(0, reconciled({ field: 'System.State' })))
    runAdoVerb.mockResolvedValueOnce(res(2, null, { stderr: 'Refused: --take ado is not a way to settle that row' }))
    const { props } = mount()
    pick('System.State', "Keep the repository's")
    pick('Custom.RiskTier', "Take the board's")
    fireEvent.click(confirmButton())
    await waitFor(() => expect(screen.getAllByTestId('reconcile-result')).toHaveLength(2))
    const rows = screen.getAllByTestId('reconcile-result')
    expect(rows[1]!.getAttribute('data-exit-code')).toBe('2')
    expect(rows[1]!.textContent).toContain(EXIT_HEADING[2])
    expect(rows[1]!.textContent).toContain('Refused: --take ado is not a way to settle that row')
    expect(props.onSettled).toHaveBeenCalledTimes(1)
  })

  it('a bridge without runAdoVerb is a sentence — nothing is run', async () => {
    // @ts-expect-error - the bridge of an older app
    window.studio = {}
    mount()
    pick('System.State', "Take the board's")
    fireEvent.click(confirmButton())
    const row = await screen.findByTestId('reconcile-result')
    expect(row.getAttribute('data-exit-code')).toBe('none')
    expect(row.textContent).toContain(EXIT_HEADING[1])
    expect(row.textContent).toContain('Shepherd')
    expect(runAdoVerb).not.toHaveBeenCalled()
  })

  it('a #<work item> row never reaches the bridge: the table refuses an sdlc-less ref and the dialog says so', async () => {
    const odd: AdoDriftItem = { ...itemOf(REF), ref: '#4521' }
    mount({ item: odd })
    pick('System.State', "Take the board's")
    expect(confirmButton().disabled).toBe(true)
    expect(confirmButton().getAttribute('title')).toContain("ref '#4521' is not an sdlc:<kind>:<id> ref")
    expect(runAdoVerb).not.toHaveBeenCalled()
  })

  it('a whole-item row (gone from the board) is shown with the plugin\'s proposal and no control Shepherd cannot honour', () => {
    mount({ item: itemOf('sdlc:spec:0005') })
    expect(screen.queryAllByRole('group').filter((g) => (g.getAttribute('aria-label') ?? '').startsWith('Take for '))).toHaveLength(0)
    expect(screen.getByTestId('reconcile-fields').textContent).toContain('records that someone knows')
    expect(screen.getByTestId('reconcile-fields').textContent).toContain('/sprd-ado reconcile')
    expect(confirmButton().disabled).toBe(true)
    expect(confirmButton().getAttribute('title')).toBe(CHOOSE_A_TAKE)
  })
})

describe('AdoReconcileDialog: what a `.proposed` result says', () => {
  async function runOne(json: Record<string, unknown>) {
    runAdoVerb.mockResolvedValue(res(0, json))
    mount()
    pick('System.State', "Take the board's")
    fireEvent.click(confirmButton())
    return screen.findByTestId('reconcile-result')
  }

  it('names the .proposed path the plugin printed and says the artifact itself was not changed', async () => {
    const row = await runOne(reconciled({ proposed: '.sdlc/artifacts/01-requirements/requirements.md.proposed', proposed_sha: 'abcdef012345', child: { verb: 'propose', argv: ['propose', 'System.Description'], exit: 0, stdout: 'Wrote …', stderr: '' } }))
    const said = within(row).getByTestId('reconcile-proposed')
    expect(said.textContent).toContain('.sdlc/artifacts/01-requirements/requirements.md.proposed')
    expect(said.textContent).toContain('.sdlc/artifacts/01-requirements/requirements.md itself was not changed')
    expect(said.textContent).toContain('/sprd-revise')
  })

  it('reads a proposed path given as an object, and says the same of a propose child with no path key (the plugin\'s stdout names it)', async () => {
    let row = await runOne(reconciled({ proposed: { path: 'specs/0004-x.md.proposed' } }))
    expect(within(row).getByTestId('reconcile-proposed').textContent).toContain('specs/0004-x.md itself was not changed')
    cleanup()
    runAdoVerb.mockReset()
    row = await runOne(reconciled({ child: { verb: 'propose', argv: ['propose', 'System.Description'], exit: 0, stdout: 'Wrote specs/0004-x.md.proposed: the board\'s words sit in the field; specs/0004-x.md is not changed.', stderr: '' } }))
    expect(within(row).getByTestId('reconcile-proposed').textContent).toMatch(/not changed/)
    expect(row.textContent).toContain('Wrote specs/0004-x.md.proposed')
  })

  it('says nothing about a draft when the result has none; a child\'s words are the plugin\'s, shown verbatim as characters', async () => {
    const row = await runOne(reconciled({ child: { verb: 'assign', argv: ['assign'], exit: 0, stdout: 'assigned <b>0004</b>', stderr: '' }, notes: ['the next `plan` carries the update'] }))
    expect(within(row).queryByTestId('reconcile-proposed')).toBeNull()
    expect(row.textContent).toContain('assigned <b>0004</b>')
    expect(row.querySelector('b')).toBeNull()
    expect(row.textContent).toContain('the next `plan` carries the update')
  })
})

describe('AdoReconcileDialog: steering mode', () => {
  it('draws nothing at all — no dialog, no control, nothing run', () => {
    const { container } = mount({ steering: true })
    expect(container.innerHTML).toBe('<main></main>')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.querySelectorAll('[data-write]')).toHaveLength(0)
    expect(runAdoVerb).not.toHaveBeenCalled()
  })
})

// ── reached from the spec card, after a Pull now ─────────────────────────────────────────────────

describe('SpecCard offers the dialog after a Pull now that read drift', () => {
  const ROW: BoardRow = {
    spec: '0004', name: 'claim-export', path: 'specs/0004-claim-export.md', title: 'Claim export', status: 'draft',
    risk: 'MEDIUM', team: 'platform', channel: '', owner: '@sam-k', developer: '', checker: '@priya-n', branch: '',
    sprint: 'S07', nextOwner: '', engReview: '', dataReview: '', dependsOn: [], pullRequest: null,
  }
  const LADDER = { tier: 'MEDIUM', touchesGatedPath: null, rungs: ['CI (lint, unit) — blocks'] }
  const block = <T,>(data: T | null): SourcedBlock<T> => ({ source: 'ado_sync.py status --json', fetchedAt: 'now', ok: data !== null, data, error: null })
  const card = {
    spec: '0004', path: ROW.path,
    readiness: block({ ok: true, spec: '0004', risk: 'MEDIUM', status: 'draft', ready: true, blocking: [], advisory: [], passed: [], ladder: LADDER }),
    ladder: block(LADDER),
    status: block({ spec: '0004', branch: 'spec/0004-claim-export', code_host_available: true, pull_request: null }),
    findings: block({ tracked: 0, openDebt: 0, fixedClaimMismatches: 0, findings: [], recurrence: {}, attribution: { method: 'scope-paths', attributed: 0, unattributed: 0 } }),
    channel: null, handoffCheck: block({ ok: true }),
  } as unknown as SpecCardRead
  const STATUS: AdoSyncView = {
    as_of: '2026-10-12T09:00:00Z', by_class: {}, counts: { conflicts: 0, debt: 0, drifted: 3, linked: 12, open: 3, pending: 0 }, debt: [],
    hook_line: 'ado: 12 linked · 3 drifted', last_plan: null, ledger: '.sdlc/metrics/ado-sync-log.jsonl', notes: [], schema: 1,
  }
  const AZURE: ConnectionInfo = {
    repo: 'acme/app', branch: 'main', localFolder: '/p', account: '@sam-k', accountSource: 'roster', rosterHandle: '@sam-k',
    host: 'azure-devops', hostSource: 'remote', cli: { name: 'az', found: true, extension: true, signedIn: 'yes' }, lastPulledAt: null, branchProtected: null,
  }
  const ALL = [CAPABILITIES.adoStatus, 'ado-pull', 'ado-pull-discussion', 'ado-show', 'ado-comment', 'ado-apply', 'ado-plan', CAPABILITIES.adoReconcile]
  let getCommandCenter: ReturnType<typeof vi.fn>

  function answerPull(json: Record<string, unknown>) {
    runAdoVerb.mockImplementation(async (_p, request) => {
      if (request.verb === 'pull') return res(0, json, { verb: 'pull' })
      if (request.verb === 'reconcile') return res(0, reconciled({ field: request.field }), { verb: 'reconcile' })
      return res(0, request.verb === 'show' ? { ok: true, rendered: `Work item #4521 (${REF})\nDiscussion not pulled yet.`, notes: [] } : {}, { verb: request.verb })
    })
  }

  async function mountCard(over: Partial<Parameters<typeof SpecCard>[0]> = {}) {
    getCommandCenter = vi.fn().mockResolvedValue({ ado: block(STATUS) } as unknown as CommandCenter)
    // @ts-expect-error - partial test double: only what the card, the chip, the block and the dialog reach
    window.studio = { getSpecCard: vi.fn().mockResolvedValue(card), openDocument: vi.fn().mockResolvedValue({ ok: true, path: ROW.path, shaped: true, warnings: [], sections: [] }), getCommandCenter, runAdoVerb }
    connectionStore.set(AZURE)
    render(<main><SpecCard projectPath="/p" row={ROW} actor={ACTOR} capabilities={ALL} onBack={vi.fn()} onHandOff={vi.fn()} {...over} /></main>)
    await screen.findByTestId('spec-ladder')
  }

  it('shows nothing to settle until a pull has read drift for this spec', async () => {
    answerPull(PULL)
    await mountCard()
    expect(screen.queryByRole('button', { name: /Settle drift/ })).toBeNull()
  })

  it('a pull that read drift for this spec offers Settle drift (not a write itself); the dialog\'s Confirm is the write, and the chip is re-read after it settles', async () => {
    answerPull(PULL)
    await mountCard()
    await waitFor(() => expect(screen.getByTestId('ado-chip').getAttribute('data-state')).toBe('status'))
    fireEvent.click(within(screen.getByTestId('spec-boards')).getByRole('button', { name: 'Pull now' }))
    const settle = await screen.findByRole('button', { name: /Settle drift/ })
    expect(settle.hasAttribute('data-write')).toBe(false)
    expect(screen.getByTestId('spec-facts').contains(settle)).toBe(false)
    expect(getCommandCenter).toHaveBeenCalledTimes(2)   // the pull itself refreshed the chip
    fireEvent.click(settle)
    const dialog = await screen.findByTestId('ado-reconcile-dialog')
    expect(within(dialog).getAllByRole('group').filter((g) => (g.getAttribute('aria-label') ?? '').startsWith('Take for '))).toHaveLength(3)
    fireEvent.click(within(within(dialog).getByRole('group', { name: 'Take for System.State' })).getByRole('button', { name: "Keep the repository's" }))
    fireEvent.click(within(dialog).getByRole('button', { name: new RegExp(`^${RECONCILE_CONFIRM}`) }))
    await within(dialog).findByTestId('reconcile-result')
    expect(verbsCalled().filter((r) => r.verb === 'reconcile')).toEqual([{ verb: 'reconcile', ref: REF, field: 'System.State', take: 'sdlc' }])
    await waitFor(() => expect(getCommandCenter).toHaveBeenCalledTimes(3))
  })

  it('a run that settled nothing leaves Settle drift on offer, and the next opening starts fresh: nothing chosen, Confirm back', async () => {
    runAdoVerb.mockImplementation(async (_p, request) => {
      if (request.verb === 'pull') return res(0, PULL, { verb: 'pull' })
      if (request.verb === 'reconcile') return res(1, null, { verb: 'reconcile', stderr: 'no drift is recorded for sdlc:spec:0004 System.State: run `pull` first' })
      return res(0, request.verb === 'show' ? { ok: true, rendered: `Work item #4521 (${REF})\nDiscussion not pulled yet.`, notes: [] } : {}, { verb: request.verb })
    })
    await mountCard()
    fireEvent.click(within(screen.getByTestId('spec-boards')).getByRole('button', { name: /^Pull now/ }))
    fireEvent.click(await screen.findByRole('button', { name: /Settle drift/ }))
    let dialog = await screen.findByTestId('ado-reconcile-dialog')
    fireEvent.click(within(within(dialog).getByRole('group', { name: 'Take for System.State' })).getByRole('button', { name: "Take the board's" }))
    fireEvent.click(within(dialog).getByRole('button', { name: new RegExp(`^${RECONCILE_CONFIRM}`) }))
    await within(dialog).findByTestId('reconcile-result')
    expect(within(dialog).queryByRole('button', { name: new RegExp(`^${RECONCILE_CONFIRM}`) })).toBeNull()
    fireEvent.click(within(dialog).getAllByRole('button', { name: /^Close/ }).at(-1)!)
    await waitFor(() => expect(screen.queryByTestId('ado-reconcile-dialog')).toBeNull())
    fireEvent.click(screen.getByRole('button', { name: /Settle drift/ }))
    dialog = await screen.findByTestId('ado-reconcile-dialog')
    expect(within(dialog).queryByTestId('reconcile-result')).toBeNull()
    expect(within(within(dialog).getByRole('group', { name: 'Take for System.State' })).getByRole('button', { name: 'Leave open' }).getAttribute('aria-pressed')).toBe('true')
    expect(within(dialog).getByRole('button', { name: new RegExp(`^${RECONCILE_CONFIRM}`) })).toBeTruthy()
  })

  it('drift read for another spec, or none, offers nothing; steering offers nothing at all', async () => {
    answerPull({ ...PULL, items: PULL.items.filter((i) => i.ref !== REF) })
    await mountCard()
    fireEvent.click(within(screen.getByTestId('spec-boards')).getByRole('button', { name: 'Pull now' }))
    await screen.findByTestId('fields-pull-result')
    expect(screen.queryByRole('button', { name: /Settle drift/ })).toBeNull()
    cleanup()
    answerPull(PULL)
    await mountCard({ steering: true })
    expect(screen.queryByTestId('spec-boards')).toBeNull()
    expect(screen.queryByRole('button', { name: /Settle drift/ })).toBeNull()
    expect(screen.queryByTestId('ado-reconcile-dialog')).toBeNull()
  })
})

// ── what is mirrored, and what is reused ─────────────────────────────────────────────────────────

describe('the dialog mirrors the plugin and reuses the kit — held to the plugin\'s own text', () => {
  const PLUGIN = resolve(__dirname, '..', '..')
  const read = (...p: string[]) => readFileSync(resolve(PLUGIN, ...p), 'utf-8')
  const code = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, '').split(/\r?\n/).map((l) => l.replace(/(^|\s)\/\/.*$/, '')).join('\n')
  const source = read('studio', 'src', 'components', 'ado', 'AdoReconcileDialog.tsx')

  it('NOT_DRIFT_CLASSES is ado_sync_model.NOT_DRIFT_CLASSES, in its order', () => {
    const m = /^NOT_DRIFT_CLASSES: Final = \(([^)]*)\)/m.exec(read('scripts', 'ado_sync_model.py'))
    expect(m, 'NOT_DRIFT_CLASSES in scripts/ado_sync_model.py').not.toBeNull()
    expect([...m![1]!.matchAll(/"([^"]+)"/g)].map((w) => w[1])).toEqual([...NOT_DRIFT_CLASSES])
  })

  it('WHOLE_ITEM_CLASSES are the two classes `pull` records as a row with no field', () => {
    const m = /if r\["class"\] in \(([^)]*)\):\s*\n\s*rows\.append\(\{"field": None/.exec(read('scripts', 'ado_sync.py'))
    expect(m, '_drift_events whole-item rows in scripts/ado_sync.py').not.toBeNull()
    expect([...m![1]!.matchAll(/"([^"]+)"/g)].map((w) => w[1])).toEqual([...WHOLE_ITEM_CLASSES])
  })

  it('reuses the existing ClashDiff and the kit\'s Segmented; reaches the plugin only through runAdoVerb; holds no timer', () => {
    expect(source).toMatch(/import \{ ClashDiff \} from '\.\.\/ClashDiff'/)
    expect(source).toMatch(/\bSegmented\b[^\n]*from '\.\.\/\.\.\/ui'/)
    const body = code(source)
    expect([...new Set([...body.matchAll(/studio\.(\w+)/g)].map((m) => m[1]))]).toEqual(['runAdoVerb'])
    expect(body).not.toMatch(/setInterval|setTimeout|requestAnimationFrame/)
    expect(body).not.toMatch(/child_process|\bspawn\(|\bexec\(|['"`]az['"`]/)
    // exactly one control that writes: the Confirm
    expect(body.match(/data-write/g)).toHaveLength(1)
  })
})
