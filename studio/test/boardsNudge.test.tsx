// @vitest-environment jsdom
/** The Boards nudge (build kit §5 B6-P3; owner decision 2026-10-15: nothing reads the board on its own). When a person
 * changes something the board mirrors — a spec verb, a hand-off, a decision — the host says so ONCE, in a Notice:
 * "Boards: <spec NNNN | sprint SNN | decision DL-NN> changed here — the board has not heard". Everything after that is
 * a click: **Plan board changes** runs one closed `plan` request, a counts line says what the plugin found, **Review
 * plan** (only when the plan has rows an apply would send) opens the apply dialog on exactly those rows, and its Confirm
 * is the one write. It spawns NOTHING until clicked, never pulls, never reads the discussion, and draws nothing in
 * steering mode, for a host that is not Azure DevOps, or while the Boards block was not read at all.
 *
 * `window.studio` is a PARTIAL double. The plan below is HAND-WRITTEN (unverified): its shape is read from
 * `ado_sync.py` (`_plan_row`, `cmd_plan`), not captured from a live board. */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AdoSyncView } from '../shared/adoTypes'
import type { AdoVerbRequest } from '../shared/adoVerbArgv'
import type { ActorInfo, AdoVerbResult, ConnectionInfo, DecideDecisionResult, SourcedBlock } from '../shared/types'
import { NO_ACTOR, newerPlugin } from '../shared/reasons'
import {
  BoardsChanged, BoardsNudge, boardsTargetOf, nudgeLabel, useBoardsChanged, type BoardsNudgeTarget,
} from '../src/components/ado/BoardsNudge'
import { TodayColumn } from '../src/components/today/TodayColumn'
import { connectionStore, resetConnectionStore } from '../src/stores/connectionStore'
import { CC } from './sprintHomeFixture'

const HASH = '1d0617c03373'
const ACTOR: ActorInfo = { name: '@sam-k', source: 'roster' }
const CAPS = ['ado-plan', 'ado-apply'] as const
const SOURCE = 'ado_sync.py status --json'

const STATUS: AdoSyncView = {
  as_of: '2026-10-12T09:00:00Z', by_class: {}, counts: { conflicts: 0, debt: 0, drifted: 0, linked: 12, open: 0, pending: 1 }, debt: [],
  hook_line: 'ado: 12 linked · 1 pending', last_plan: null, ledger: '.sdlc/metrics/ado-sync-log.jsonl', notes: [], schema: 1,
}
const ADO: SourcedBlock<AdoSyncView> = { source: SOURCE, fetchedAt: 'now', ok: true, data: STATUS, error: null }

/** `plan --json`, hand-written (unverified): three rows an apply would send and one it would not. */
const PLANNED = {
  _provenance: 'hand-written (unverified)',
  _command: ['ado_sync.py', 'plan', '--kind', 'spec', '--id', '0008', '--json'],
  value: {
    ok: true, unavailable: false, reason: null, plan: HASH, posture: 'assisted', executed_as: '@sam-k',
    rows: [
      { ref: 'sdlc:spec:0008', kind: 'spec', id: '0008', action: 'update', reason: null, work_item: 4521, rev: 7, type: 'User Story', ops: [{ op: 'replace', path: '/fields/System.State', old: 'Active', new: 'Ready' }], notes: [] },
      { ref: 'sdlc:epic:E1', kind: 'epic', id: 'E1', action: 'create', reason: null, work_item: null, rev: null, type: 'Epic', ops: [{ op: 'add', path: '/fields/System.Title', old: null, new: 'Claims' }], notes: [] },
      { ref: 'sdlc:spec:0009', kind: 'spec', id: '0009', action: 'held', reason: '#4522 is gone from the board', work_item: 4522, rev: null, type: 'User Story', ops: [], notes: [] },
      { ref: 'sdlc:spec:0008', kind: 'comment', action: 'comment', status: 'draft', reason: null, detail: null, work_item: 4521, target: 'sdlc:spec:0008', text: 'Moved to Ready', ops: [], notes: [] },
    ],
    counts: { create: 1, update: 1, link: 0, ambiguous: 0, unmapped: 0, refused: 0, held: 1, in_sync: 0 },
    comments: { planned: true, draft: 1, skipped: 0, refused: 0, unavailable: null },
  },
}
/** A plan that found nothing an apply would send: only a held row, so there is nothing to review. */
const NOTHING_TO_SEND = {
  ...PLANNED.value, rows: [PLANNED.value.rows[2]],
  counts: { create: 0, update: 0, link: 0, ambiguous: 0, unmapped: 0, refused: 0, held: 1, in_sync: 3 },
  comments: { planned: true, draft: 0, skipped: 0, refused: 0, unavailable: null },
}
const APPLIED = { ok: true, applied: 3 }

const AZURE: ConnectionInfo = {
  repo: 'acme/app', branch: 'main', localFolder: '/p', account: '@sam-k', accountSource: 'roster', rosterHandle: '@sam-k',
  host: 'azure-devops', hostSource: 'remote', cli: { name: 'az', found: true, extension: true, signedIn: 'yes' }, lastPulledAt: null, branchProtected: null,
}
const NOT_AZURE: ConnectionInfo = { ...AZURE, host: 'github', cli: { name: 'gh', found: true, extension: null, signedIn: 'yes' } }

function res(verb: AdoVerbResult['verb'], exitCode: 0 | 1 | 2 | null, json: Record<string, unknown> | null, over: Partial<AdoVerbResult> = {}): AdoVerbResult {
  return { ok: exitCode === 0, exitCode, refused: exitCode === 2, stdout: '', stderr: '', argv: [], verb, json, ...over }
}

let runAdoVerb: ReturnType<typeof vi.fn<(projectPath: string, request: AdoVerbRequest) => Promise<AdoVerbResult>>>
beforeEach(() => {
  runAdoVerb = vi.fn()
  // @ts-expect-error - partial test double: only what the nudge and its dialog reach
  window.studio = { runAdoVerb }
  connectionStore.set(AZURE)
})
afterEach(async () => {
  vi.useRealTimers()
  cleanup()
  // Radix's FocusScope sends its unmount event from a setTimeout(0) scheduled during cleanup (see adoApplyDialog.test).
  await new Promise((resolve) => setTimeout(resolve, 0))
  resetConnectionStore()
  // @ts-expect-error - cleaning up the test double
  delete window.studio
})

const SPEC: BoardsNudgeTarget = { kind: 'spec', id: '0008' }
function mount(over: Partial<Parameters<typeof BoardsNudge>[0]> = {}) {
  const props = { target: SPEC, projectPath: '/p', ado: ADO, capabilities: [...CAPS], actor: ACTOR, onDismiss: vi.fn(), ...over }
  const view = render(<main><BoardsNudge {...props} /></main>)
  return { props, ...view }
}
const buttonNamed = (name: string) => screen.getByRole('button', { name: new RegExp(`^${name}`) }) as HTMLButtonElement
const verbsCalled = () => runAdoVerb.mock.calls.map(([, request]) => request)
const nudge = () => screen.getByTestId('boards-nudge')

describe('the nudge says what changed, once, and spawns nothing', () => {
  it('spawns nothing on mount — nor in a day of timers — and draws one Notice with the plan button and a dismissal', () => {
    vi.useFakeTimers()
    mount()
    expect(nudge().textContent).toContain('Boards: spec 0008 changed here — the board has not heard')
    expect(buttonNamed('Plan board changes').hasAttribute('data-write')).toBe(true)
    expect(screen.queryByRole('button', { name: /^Review plan/ })).toBeNull()
    expect(screen.getByRole('button', { name: 'Dismiss' }).hasAttribute('data-write')).toBe(false)
    act(() => { vi.advanceTimersByTime(24 * 60 * 60 * 1000) })
    expect(runAdoVerb).not.toHaveBeenCalled()
  })

  it.each([
    [{ kind: 'spec', id: '0008' }, 'spec 0008'],
    [{ sprint: 'S07' }, 'sprint S07'],
    [{ kind: 'decision', id: 'DL-03' }, 'decision DL-03'],
  ] as Array<[BoardsNudgeTarget, string]>)('names %j as "%s"', (target, label) => {
    mount({ target })
    expect(nudgeLabel(target)).toBe(label)
    expect(nudge().textContent).toContain(`Boards: ${label} changed here — the board has not heard`)
  })

  it('Dismiss tells the host and asks the plugin nothing', () => {
    const { props } = mount()
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
    expect(props.onDismiss).toHaveBeenCalledTimes(1)
    expect(runAdoVerb).not.toHaveBeenCalled()
  })
})

describe('Plan board changes: one click, one plan', () => {
  it('a kind-and-id target is one closed `plan` request for that item; the counts line says what the plugin found', async () => {
    runAdoVerb.mockResolvedValue(res('plan', 0, PLANNED.value))
    mount()
    fireEvent.click(buttonNamed('Plan board changes'))
    await screen.findByTestId('plan-result')
    expect(runAdoVerb).toHaveBeenCalledTimes(1)
    expect(runAdoVerb).toHaveBeenCalledWith('/p', { verb: 'plan', kind: 'spec', id: '0008' })
    expect(screen.getByTestId('plan-result').textContent).toBe('1 to create · 1 to update · 1 comment')
  })

  it('a decision target is a `plan` for that decision', async () => {
    runAdoVerb.mockResolvedValue(res('plan', 0, PLANNED.value))
    mount({ target: { kind: 'decision', id: 'DL-03' } })
    fireEvent.click(buttonNamed('Plan board changes'))
    await screen.findByTestId('plan-result')
    expect(verbsCalled()).toEqual([{ verb: 'plan', kind: 'decision', id: 'DL-03' }])
  })

  it('a sprint target sends `{verb: plan, sprint}` and nothing beside the sprint', async () => {
    runAdoVerb.mockResolvedValue(res('plan', 0, PLANNED.value))
    mount({ target: { sprint: 'S07' } })
    fireEvent.click(buttonNamed('Plan board changes'))
    await screen.findByTestId('plan-result')
    expect(verbsCalled()).toEqual([{ verb: 'plan', sprint: 'S07' }])
    expect(Object.keys(verbsCalled()[0]!).sort()).toEqual(['sprint', 'verb'])
  })

  it('one spawn per click: planning twice is two requests, and never a pull of the fields or the discussion', async () => {
    runAdoVerb.mockResolvedValue(res('plan', 0, PLANNED.value))
    mount()
    fireEvent.click(buttonNamed('Plan board changes'))
    await screen.findByTestId('plan-result')
    fireEvent.click(buttonNamed('Plan board changes'))
    await waitFor(() => expect(runAdoVerb).toHaveBeenCalledTimes(2))
    expect(verbsCalled().every((r) => r.verb === 'plan')).toBe(true)
    expect(verbsCalled().some((r) => r.verb === 'pull' || r.verb === 'pullDiscussion')).toBe(false)
  })

  it('a plugin without ado-plan disables the button with the capability it lacks, and nobody identified says so', () => {
    mount({ capabilities: ['ado-apply'] })
    expect(buttonNamed('Plan board changes').disabled).toBe(true)
    expect(buttonNamed('Plan board changes').getAttribute('title')).toBe(newerPlugin('ado-plan'))
    cleanup()
    mount({ actor: null })
    expect(buttonNamed('Plan board changes').getAttribute('title')).toBe(NO_ACTOR)
    fireEvent.click(buttonNamed('Plan board changes'))
    expect(runAdoVerb).not.toHaveBeenCalled()
  })
})

describe('Review plan: only when the plan has rows an apply would send', () => {
  it('is absent before the plan, and present after a plan with pending rows — a read, so not a write control', async () => {
    runAdoVerb.mockResolvedValue(res('plan', 0, PLANNED.value))
    mount()
    expect(screen.queryByRole('button', { name: /^Review plan/ })).toBeNull()
    fireEvent.click(buttonNamed('Plan board changes'))
    await screen.findByRole('button', { name: /^Review plan/ })
    expect(buttonNamed('Review plan').hasAttribute('data-write')).toBe(false)
    expect(screen.queryByTestId('ado-apply-dialog')).toBeNull()
  })

  it.each([
    ['a plan with nothing an apply would send', res('plan', 0, NOTHING_TO_SEND)],
    ['a plan that could not be drawn up', res('plan', 0, { ok: true, unavailable: true, reason: 'not configured', host: null, plan: null, rows: [], counts: null })],
    ['a plan that failed', res('plan', 1, null, { stderr: 'could not write the plan file' })],
  ])('is absent for %s', async (_label, answer) => {
    runAdoVerb.mockResolvedValue(answer)
    mount()
    fireEvent.click(buttonNamed('Plan board changes'))
    await screen.findByTestId('plan-result')
    expect(screen.queryByRole('button', { name: /^Review plan/ })).toBeNull()
  })

  it('a later plan with nothing to send takes Review plan away: the nudge holds the newest plan, not the first', async () => {
    runAdoVerb.mockResolvedValueOnce(res('plan', 0, PLANNED.value))
    mount()
    fireEvent.click(buttonNamed('Plan board changes'))
    await screen.findByRole('button', { name: /^Review plan/ })
    runAdoVerb.mockResolvedValueOnce(res('plan', 0, NOTHING_TO_SEND))
    fireEvent.click(buttonNamed('Plan board changes'))
    await waitFor(() => expect(screen.queryByRole('button', { name: /^Review plan/ })).toBeNull())
  })

  it('opens the apply dialog on the plan\'s rows — as many rows as the plan has — and runs nothing by opening it', async () => {
    runAdoVerb.mockResolvedValue(res('plan', 0, PLANNED.value))
    mount()
    fireEvent.click(buttonNamed('Plan board changes'))
    fireEvent.click(await screen.findByRole('button', { name: /^Review plan/ }))
    const dialog = await screen.findByTestId('ado-apply-dialog')
    expect(dialog.querySelectorAll('[data-plan-row]')).toHaveLength(PLANNED.value.rows.length)
    expect(Array.from(dialog.querySelectorAll('[data-plan-row]')).map((r) => r.getAttribute('data-action'))).toEqual(['update', 'create', 'held', 'comment'])
    expect(within(dialog).getByTestId('ado-apply-argv').textContent).toBe(`Run: ado_sync.py apply --confirm ${HASH} --json --by @sam-k`)
    expect(verbsCalled()).toEqual([{ verb: 'plan', kind: 'spec', id: '0008' }])
  })

  it('Confirm sends the plan\'s hash once; after an exit 0 the plan is dropped, the answer stays to be read, and closing it dismisses the nudge', async () => {
    runAdoVerb.mockResolvedValueOnce(res('plan', 0, PLANNED.value))
    const { props } = mount()
    fireEvent.click(buttonNamed('Plan board changes'))
    fireEvent.click(await screen.findByRole('button', { name: /^Review plan/ }))
    runAdoVerb.mockResolvedValueOnce(res('apply', 0, APPLIED, { stdout: 'applied 3 rows' }))
    fireEvent.click(await screen.findByRole('button', { name: /^Confirm — apply to Azure Boards/ }))
    await waitFor(() => expect(runAdoVerb).toHaveBeenCalledWith('/p', { verb: 'apply', confirm: HASH }))
    // the answer is the plugin's, under its exit code alone, and still on screen
    const result = await screen.findByTestId('ado-apply-result')
    expect(result.textContent).toContain('applied 3 rows')
    expect(props.onDismiss).not.toHaveBeenCalled()
    // the plan that was sent is gone: there is nothing left to review, and the counts line is not the old plan's
    expect(screen.queryByRole('button', { name: /^Review plan/ })).toBeNull()
    expect(screen.queryByTestId('plan-result')).toBeNull()
    fireEvent.click(within(screen.getByTestId('ado-apply-dialog')).getAllByRole('button', { name: 'Close' })[0]!)
    expect(props.onDismiss).toHaveBeenCalledTimes(1)
    // exactly one plan and one apply: the nudge never chained a second spawn
    expect(verbsCalled().map((r) => r.verb)).toEqual(['plan', 'apply'])
  })

  it('an apply that did not land keeps the plan, so it can be read again; closing the dialog does not dismiss the nudge', async () => {
    runAdoVerb.mockResolvedValueOnce(res('plan', 0, PLANNED.value))
    const { props } = mount()
    fireEvent.click(buttonNamed('Plan board changes'))
    fireEvent.click(await screen.findByRole('button', { name: /^Review plan/ }))
    runAdoVerb.mockResolvedValueOnce(res('apply', 1, null, { stderr: 'one row failed: conflict on #4521' }))
    fireEvent.click(await screen.findByRole('button', { name: /^Confirm — apply to Azure Boards/ }))
    expect((await screen.findByTestId('ado-apply-result')).textContent).toContain('one row failed: conflict on #4521')
    fireEvent.click(within(screen.getByTestId('ado-apply-dialog')).getAllByRole('button', { name: 'Close' })[0]!)
    expect(props.onDismiss).not.toHaveBeenCalled()
    expect(screen.queryByTestId('ado-apply-dialog')).toBeNull()
    expect(screen.getByRole('button', { name: /^Review plan/ })).toBeTruthy()
  })

  it('without ado-apply the dialog still reads, its Confirm says which capability a newer plugin brings, and nothing is sent', async () => {
    runAdoVerb.mockResolvedValue(res('plan', 0, PLANNED.value))
    mount({ capabilities: ['ado-plan'] })
    fireEvent.click(buttonNamed('Plan board changes'))
    fireEvent.click(await screen.findByRole('button', { name: /^Review plan/ }))
    const confirm = (await screen.findByRole('button', { name: /^Confirm — apply to Azure Boards/ })) as HTMLButtonElement
    expect(confirm.disabled).toBe(true)
    expect(confirm.getAttribute('title')).toBe(newerPlugin('ado-apply'))
    fireEvent.click(confirm)
    expect(verbsCalled().map((r) => r.verb)).toEqual(['plan'])
  })
})

describe('when the nudge is not drawn', () => {
  it.each([
    ['no Boards block was read (null)', { ado: null }],
    ['no Boards block was read (absent)', { ado: undefined }],
    ['steering mode is read-only', { steering: true }],
  ])('%s: nothing at all — no Notice, no button, no request', (_label, over) => {
    const { container } = mount(over)
    expect(container.querySelector('main')!.innerHTML).toBe('')
    expect(document.querySelectorAll('[data-write], button')).toHaveLength(0)
    expect(runAdoVerb).not.toHaveBeenCalled()
  })

  it('a project whose host is not Azure DevOps hears nothing about a board it does not have', () => {
    connectionStore.set(NOT_AZURE)
    const { container } = mount()
    expect(container.querySelector('main')!.innerHTML).toBe('')
    expect(runAdoVerb).not.toHaveBeenCalled()
  })

  it('a host not yet known is not "not Azure DevOps": the nudge is drawn and the plugin decides at the click', () => {
    resetConnectionStore()
    mount()
    expect(nudge()).toBeTruthy()
  })
})

describe('what changed → what the nudge names (the host\'s mapping)', () => {
  const sprint = (request: object) => ({ kind: 'sprint', request }) as Parameters<typeof boardsTargetOf>[0]

  it('a spec verb names that spec; a sprint verb names the sprint', () => {
    expect(boardsTargetOf(sprint({ verb: 'handoff', spec: '0008', to: '@sam-k' }))).toEqual({ kind: 'spec', id: '0008' })
    expect(boardsTargetOf(sprint({ verb: 'ack', spec: '0008' }))).toEqual({ kind: 'spec', id: '0008' })
    expect(boardsTargetOf(sprint({ verb: 'unslate', spec: '0008', reason: 'x' }))).toEqual({ kind: 'spec', id: '0008' })
    expect(boardsTargetOf(sprint({ verb: 'verdict', spec: '0008', lane: 'eng', verdict: 'accepted' }))).toEqual({ kind: 'spec', id: '0008' })
    expect(boardsTargetOf(sprint({ verb: 'carry', spec: '0008', to: 'S08', reason: 'x' }))).toEqual({ kind: 'spec', id: '0008' })
    expect(boardsTargetOf(sprint({ verb: 'ready', sprint: 'S07' }))).toEqual({ sprint: 'S07' })
    expect(boardsTargetOf(sprint({ verb: 'close', sprint: 'S07', carry: {}, drop: {} }))).toEqual({ sprint: 'S07' })
    expect(boardsTargetOf(sprint({ verb: 'new', sprint: 'S09', goal: 'g', start: '2026-10-19', target: 4 }))).toEqual({ sprint: 'S09' })
    expect(boardsTargetOf(sprint({ verb: 'slate', sprint: 'S07', specs: ['0008', '0009'] }))).toEqual({ sprint: 'S07' })
    expect(boardsTargetOf(sprint({ verb: 'edit', sprint: 'S07', goal: 'g' }))).toEqual({ sprint: 'S07' })
  })

  it('the omnibar\'s other writes: a pull that slates, a defer, a tier confirmation and a decision each name what they changed', () => {
    expect(boardsTargetOf({ kind: 'pull', spec: '0008', path: 'specs/0008-x.md', slated: false, ready: true, sprint: 'S07' })).toEqual({ kind: 'spec', id: '0008' })
    expect(boardsTargetOf({ kind: 'defer', spec: '0008', path: 'specs/0008-x.md', reason: 'r' })).toEqual({ kind: 'spec', id: '0008' })
    expect(boardsTargetOf({ kind: 'confirm-tier', spec: '0008', path: 'specs/0008-x.md' })).toEqual({ kind: 'spec', id: '0008' })
    expect(boardsTargetOf({ kind: 'decide', id: 'DL-03', resolution: 'Fail closed' })).toEqual({ kind: 'decision', id: 'DL-03' })
  })

  it('what writes nothing, or whose id the host does not know, names nothing — never a guess', () => {
    expect(boardsTargetOf({ kind: 'close', sprint: 'S07' })).toBeNull()
    expect(boardsTargetOf({ kind: 'new-sprint', sprint: 'S09' })).toBeNull()
    expect(boardsTargetOf({ kind: 'decision', text: 'Fail open or closed?' })).toBeNull()
  })
})

describe('the context a Today column tells the host through', () => {
  it('is absent by default (a column with no host above it tells nobody) and carries the host\'s function when one is provided', () => {
    const seen: Array<ReturnType<typeof useBoardsChanged>> = []
    const Probe = () => { seen.push(useBoardsChanged()); return null }
    render(createElement(Probe))
    expect(seen[0]).toBeNull()
    const notify = vi.fn()
    render(createElement(BoardsChanged.Provider, { value: notify }, createElement(Probe)))
    expect(seen[seen.length - 1]).toBe(notify)
  })
})

describe('a decision recorded from the Today column tells the host through the context', () => {
  const decided: DecideDecisionResult = { ok: true, id: 'DL-01', status: 'decided', decided: '2026-10-15', by: '@arjun-m' }
  const refusal: DecideDecisionResult = { ok: false, stderr: 'DL-01 is already decided' }
  type Decide = (id: string, resolution: string) => Promise<DecideDecisionResult>
  function column(onDecide: Decide, notify: ((t: BoardsNudgeTarget) => void) | null) {
    const tree = createElement(TodayColumn, { cc: CC, onRun: vi.fn(), onDecide, onConfirmTier: vi.fn(), onSince: vi.fn(), onActed: vi.fn(), claudeLine: null })
    render(notify ? createElement(BoardsChanged.Provider, { value: notify }, tree) : tree)
    const item = screen.getByTestId('needs-you-list').querySelector('[data-needs-you-item][data-kind="decide"]') as HTMLElement
    fireEvent.click(within(item).getByRole('button', { name: 'Decide' }))
    fireEvent.change(within(item).getByLabelText('Resolution for DL-01'), { target: { value: 'Fail closed' } })
    fireEvent.click(within(item).getByRole('button', { name: 'Record' }))
  }

  it('Decide then Record that the plugin accepted names the decision once; a refusal names nothing', async () => {
    const notify = vi.fn()
    column(vi.fn<Decide>().mockResolvedValue(decided), notify)
    await waitFor(() => expect(notify).toHaveBeenCalledTimes(1))
    expect(notify).toHaveBeenCalledWith({ kind: 'decision', id: 'DL-01' })
    cleanup()
    const refused = vi.fn()
    column(vi.fn<Decide>().mockResolvedValue(refusal), refused)
    await screen.findByTestId('needs-you-outcome')
    expect(refused).not.toHaveBeenCalled()
  })

  it('a Today column with no host above it records the decision just the same', async () => {
    const onDecide = vi.fn<Decide>().mockResolvedValue(decided)
    column(onDecide, null)
    await waitFor(() => expect(onDecide).toHaveBeenCalledWith('DL-01', 'Fail closed'))
    expect((await screen.findByTestId('needs-you-outcome')).textContent).toContain('decided')
  })
})

describe('App wires exactly one nudge, and never from the open path', () => {
  const code = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, '').split(/\r?\n/).map((l) => l.replace(/(^|\s)\/\/.*$/, '')).join('\n')
  const app = code(readFileSync(resolve(__dirname, '..', 'src', 'App.tsx'), 'utf-8'))

  it('mounts one <BoardsNudge>, hands it the command center\'s own Boards block and withdraws it in steering', () => {
    expect(app.match(/<BoardsNudge\b/g)).toHaveLength(1)
    expect(app).toMatch(/useState<BoardsNudgeTarget \| null>\(null\)/)
    expect(app).toMatch(/ado=\{commandCenter\?\.ado\}/)
    expect(app).toMatch(/steering=\{area === 'steering'\}/)
    expect(app).toMatch(/<BoardsChanged\.Provider value=\{setBoardsNudge\}>/)
  })

  it('sets it from the omnibar\'s Done and a hand-off that landed, clears it on dismissal and with the project, and nowhere else', () => {
    const sets = [...app.matchAll(/setBoardsNudge\(([^)]*)\)/g)].map((m) => m[1])
    // in file order: the project change, the omnibar's Done, the nudge's own dismissal, the hand-off
    expect(sets).toEqual(['null', 'changed', 'null', '{ kind: \'spec\', id: openSpec.spec }'])
    expect(app).toMatch(/boardsTargetOf\(verbIntent\.intent\)/)
  })
})

describe('the nudge holds no effect and no timer', () => {
  const code = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, '').split(/\r?\n/).map((l) => l.replace(/(^|\s)\/\/.*$/, '')).join('\n')
  const source = code(readFileSync(resolve(__dirname, '..', 'src', 'components', 'ado', 'BoardsNudge.tsx'), 'utf-8'))

  it('never schedules anything, never reaches the bridge itself, never builds a pull', () => {
    expect(source).not.toMatch(/setInterval|setTimeout|requestAnimationFrame|useEffect|useLayoutEffect/)
    expect(source).not.toMatch(/window\.studio|child_process|['"`]az['"`]/)
    expect(source).not.toMatch(/pullDiscussion|verb: 'pull'|runAdo\(|runAdoVerb\(/)
    expect(source).not.toMatch(/ado\/local|\.sdlc\/ado|ado\.yaml|schema\.json|me\.json/)
  })
})
