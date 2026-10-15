// @vitest-environment jsdom
/** `Catch up` (build kit §5 B6-P3; owner decision 2026-10-15: nothing reads the board on project open — a staleness
 * line and a button instead; Pull discussion stays its own click). `CatchUp` is a section beside the Today column's
 * Azure Boards rows: one line saying how old the mirror is — in the four states `adoChipView` derives — and
 * `PullNow` (both buttons, the first relabelled `Catch up`). `Catch up` sends the closed `pull` request and nothing
 * else; `Pull discussion` is a second, separate click. No effect and no timer: a day of fake timers spawns nothing.
 *
 * `window.studio` is a PARTIAL double. Every plugin document below is HAND-WRITTEN (unverified): its shape is read
 * from `ado_sync.py` (`cmd_pull`, `summarize`), not captured from a live board; the never-pulled form is the plugin's
 * own golden. */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AdoSyncView } from '../shared/adoTypes'
import type { AdoVerbRequest } from '../shared/adoVerbArgv'
import type { AdoVerbResult, ChatActivity, CommandCenter, ConnectionInfo, ProjectStage, ProjectStatus, SourcedBlock, SprintVerbResult } from '../shared/types'
import { NO_DATA, NOT_PULLED_YET, newerPlugin, WORK_ITEMS_NOT_SET_UP } from '../shared/reasons'
import { CatchUp, catchUpLine } from '../src/components/ado/CatchUp'
import { TodayColumn } from '../src/components/today/TodayColumn'
import { LifecycleHome } from '../src/components/LifecycleHome'
import { StageReadinessProvider } from '../src/components/StageReadinessContext'
import { connectionStore, resetConnectionStore } from '../src/stores/connectionStore'
import { resetChatTurnStore } from '../src/stores/chatTurnStore'
import { readinessWith } from './activityFixtures'
import { block as sourced, CC, EMPTY_CC, withCc } from './sprintHomeFixture'

const SOURCE = 'ado_sync.py status --json'
const GOLDEN = resolve(__dirname, '..', '..', 'scripts', 'tests', 'golden', 'ado_status_nodata.json')
/** The plugin's own never-pulled document, read from its golden (so a key it adds or renames turns this red). */
const NEVER_PULLED = JSON.parse(readFileSync(GOLDEN, 'utf-8')) as AdoSyncView
// Hand-written (unverified): a pulled mirror, in the shape `ado_sync_model.summarize` documents.
const PULLED = {
  _provenance: 'hand-written (unverified)',
  _command: ['ado_sync.py', 'status', '--json'],
  value: {
    as_of: '2026-10-12T09:02:00Z', by_class: { CONFLICT: 1 },
    counts: { conflicts: 1, debt: 0, drifted: 1, linked: 5, open: 1, pending: 2 },
    debt: [], hook_line: '2 rows pending · 1 drifted · as of 2026-10-12T09:02Z', last_plan: null, ledger: '.sdlc/metrics/ado-sync-log.jsonl', notes: [], schema: 1,
  } satisfies AdoSyncView,
}
/** `pull --json` (hand-written, unverified): `cmd_pull`'s `out`. */
const PULL_DONE = {
  ok: true, unavailable: false, reason: null, as_of: '2026-10-15T09:02:00Z', items: [], counts: {}, unmatched_ids: [], proposals: [],
  recorded: { observed: 3, drift_seen: 1 }, hook_line: '1 rows pending · 1 drifted · as of 2026-10-15T09:02Z', notes: [],
}
const DISCUSSION_DONE = { ok: true, discussion: 'pulled', as_of: '2026-10-15T09:02:00Z', skipped: 0, unmatched_ids: [], cost: 'cost: 0 items read', items: [] }

const adoBlock = (data: AdoSyncView | null, error: string | null = null): SourcedBlock<AdoSyncView> => sourced(SOURCE, data, error)
const CAPS = ['ado-pull', 'ado-pull-discussion'] as const
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
  // @ts-expect-error - partial test double: only what the section reaches
  window.studio = { runAdoVerb }
  connectionStore.set(AZURE)
})
afterEach(() => {
  vi.useRealTimers()
  cleanup()
  resetChatTurnStore()
  resetConnectionStore()
  // @ts-expect-error - cleaning up the test double
  delete window.studio
})

const buttonNamed = (name: string) => screen.getByRole('button', { name: new RegExp(`^${name}`) }) as HTMLButtonElement
const verbsCalled = () => runAdoVerb.mock.calls.map(([, request]) => request)
const section = () => screen.getByTestId('ado-catch-up')
const lineOf = () => screen.getByTestId('catch-up-line')

describe('the staleness line: the four states adoChipView derives, in words', () => {
  it('a pulled mirror says `Board as of <stamp>` with the plugin\'s own as-of', () => {
    render(<CatchUp projectPath="/p" ado={adoBlock(PULLED.value)} capabilities={[...CAPS]} />)
    expect(lineOf().textContent).toBe('Board as of 2026-10-12 09:02')
    expect(lineOf().getAttribute('data-state')).toBe('status')
  })

  it('a mirror that never pulled says `Not pulled yet` — the plugin\'s own never-pulled document, not a zeroed shape', () => {
    render(<CatchUp projectPath="/p" ado={adoBlock(NEVER_PULLED)} capabilities={[...CAPS]} />)
    expect(lineOf().textContent).toBe(NOT_PULLED_YET)
    expect(lineOf().getAttribute('data-state')).toBe('not-pulled')
  })

  it('a project whose host is not Azure DevOps says work items are not set up — and offers no button that would ask a board that is not there', () => {
    connectionStore.set(NOT_AZURE)
    render(<CatchUp projectPath="/p" ado={adoBlock(PULLED.value)} capabilities={[...CAPS]} />)
    expect(lineOf().textContent).toBe(WORK_ITEMS_NOT_SET_UP)
    expect(lineOf().getAttribute('data-state')).toBe('not-set-up')
    expect(section().querySelectorAll('button, [data-write]')).toHaveLength(0)
  })

  it.each([
    ['an absent block', undefined],
    ['a null block', null],
    ['a block the plugin could not answer', adoBlock(null, 'arrives with a newer plugin: lacks ado-status-json')],
  ])('%s says `no data` — and the buttons are still there to catch up', (_label, ado) => {
    render(<CatchUp projectPath="/p" ado={ado} capabilities={[...CAPS]} />)
    expect(lineOf().textContent).toBe(NO_DATA)
    expect(lineOf().getAttribute('data-state')).toBe('no-data')
    expect(buttonNamed('Catch up').disabled).toBe(false)
  })

  it('no digit anywhere in a no-data state: not in the line, not in the section', () => {
    const states: Array<SourcedBlock<AdoSyncView> | null | undefined> = [undefined, null, adoBlock(null, 'no readable answer'), adoBlock(NEVER_PULLED)]
    for (const ado of states) {
      cleanup()
      render(<CatchUp projectPath="/p" ado={ado} capabilities={[...CAPS]} />)
      expect(lineOf().textContent ?? '').not.toMatch(/\d/)
      expect(section().textContent ?? '').not.toMatch(/\d/)
    }
    cleanup()
    connectionStore.set(NOT_AZURE)
    render(<CatchUp projectPath="/p" ado={adoBlock(NEVER_PULLED)} capabilities={[...CAPS]} />)
    expect(section().textContent ?? '').not.toMatch(/\d/)
  })

  it('catchUpLine is pure: the same four sentences without a DOM, a stamp that is not a date kept as the plugin wrote it', () => {
    expect(catchUpLine({ block: adoBlock(PULLED.value), notSetUp: false }).text).toBe('Board as of 2026-10-12 09:02')
    expect(catchUpLine({ block: adoBlock(NEVER_PULLED), notSetUp: false }).text).toBe(NOT_PULLED_YET)
    expect(catchUpLine({ block: null, notSetUp: false }).text).toBe(NO_DATA)
    expect(catchUpLine({ block: adoBlock(PULLED.value), notSetUp: true }).text).toBe(WORK_ITEMS_NOT_SET_UP)
    expect(catchUpLine({ block: adoBlock({ ...PULLED.value, as_of: 'someday' }), notSetUp: false }).text).toBe('Board as of someday')
  })
})

describe('the two buttons: each its own click, each a data-write', () => {
  it('draws Catch up and Pull discussion, two data-write buttons, and spawns nothing on mount — nor in a day of timers', () => {
    vi.useFakeTimers()
    render(<CatchUp projectPath="/p" ado={adoBlock(PULLED.value)} capabilities={[...CAPS]} />)
    expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(['Catch up', 'Pull discussion'])
    expect(section().querySelectorAll('[data-write]')).toHaveLength(2)
    act(() => { vi.advanceTimersByTime(24 * 60 * 60 * 1000) })
    expect(runAdoVerb).not.toHaveBeenCalled()
  })

  it('Catch up is one closed `pull` request with no id — the fields, never the discussion', async () => {
    runAdoVerb.mockResolvedValue(res('pull', 0, PULL_DONE))
    render(<CatchUp projectPath="/p" ado={adoBlock(PULLED.value)} capabilities={[...CAPS]} />)
    fireEvent.click(buttonNamed('Catch up'))
    await screen.findByTestId('fields-pull-result')
    expect(verbsCalled()).toEqual([{ verb: 'pull' }])
    expect('id' in verbsCalled()[0]!).toBe(false)
    expect(screen.getByTestId('fields-pull-result').textContent).toContain('2026-10-15 09:02')
  })

  it('Pull discussion stays its own click: Catch up never sends it, and it never sends Catch up', async () => {
    runAdoVerb.mockResolvedValue(res('pull', 0, PULL_DONE))
    render(<CatchUp projectPath="/p" ado={adoBlock(PULLED.value)} capabilities={[...CAPS]} />)
    fireEvent.click(buttonNamed('Catch up'))
    await screen.findByTestId('fields-pull-result')
    expect(verbsCalled().some((r) => r.verb === 'pullDiscussion')).toBe(false)
    runAdoVerb.mockResolvedValue(res('pullDiscussion', 0, DISCUSSION_DONE))
    fireEvent.click(buttonNamed('Pull discussion'))
    await screen.findByTestId('discussion-pull-result')
    expect(verbsCalled()).toEqual([{ verb: 'pull' }, { verb: 'pullDiscussion' }])
  })

  it('tells the host after a pull that READ the board, with the plugin\'s answer; an unreachable board tells it nothing', async () => {
    const onPulled = vi.fn()
    runAdoVerb.mockResolvedValue(res('pull', 0, PULL_DONE))
    render(<CatchUp projectPath="/p" ado={adoBlock(PULLED.value)} capabilities={[...CAPS]} onPulled={onPulled} />)
    fireEvent.click(buttonNamed('Catch up'))
    await waitFor(() => expect(onPulled).toHaveBeenCalledTimes(1))
    expect(onPulled.mock.calls[0]![0]).toBe('fields')
    expect(onPulled.mock.calls[0]![1].json).toEqual(PULL_DONE)
    cleanup()
    onPulled.mockClear()
    runAdoVerb.mockResolvedValue(res('pull', 0, { ok: true, unavailable: true, reason: 'could not reach the organisation', host: { name: 'azure-devops' } }))
    render(<CatchUp projectPath="/p" ado={adoBlock(PULLED.value)} capabilities={[...CAPS]} onPulled={onPulled} />)
    fireEvent.click(buttonNamed('Catch up'))
    await screen.findByTestId('fields-pull-result')
    expect(onPulled).not.toHaveBeenCalled()
  })

  it('a plugin without the pull capabilities disables each button with the capability it lacks', () => {
    render(<CatchUp projectPath="/p" ado={adoBlock(PULLED.value)} capabilities={['ado-status-json']} />)
    expect(buttonNamed('Catch up').disabled).toBe(true)
    expect(buttonNamed('Catch up').getAttribute('title')).toBe(newerPlugin('ado-pull'))
    expect(buttonNamed('Pull discussion').getAttribute('title')).toBe(newerPlugin('ado-pull-discussion'))
    fireEvent.click(buttonNamed('Catch up'))
    expect(runAdoVerb).not.toHaveBeenCalled()
  })

  it('steering mode draws nothing: no line, no button, no request', () => {
    const { container } = render(<CatchUp projectPath="/p" ado={adoBlock(PULLED.value)} capabilities={[...CAPS]} steering />)
    expect(container.innerHTML).toBe('')
    expect(document.querySelectorAll('[data-write], button')).toHaveLength(0)
    expect(runAdoVerb).not.toHaveBeenCalled()
  })
})

describe('CatchUp holds no effect and no timer', () => {
  const code = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, '').split(/\r?\n/).map((l) => l.replace(/(^|\s)\/\/.*$/, '')).join('\n')
  const root = resolve(__dirname, '..')
  const read = (rel: string) => code(readFileSync(resolve(root, rel), 'utf-8'))

  it('CatchUp never schedules anything, reads nothing on mount and never reaches the bridge itself', () => {
    const body = read('src/components/ado/CatchUp.tsx')
    expect(body).not.toMatch(/setInterval|setTimeout|requestAnimationFrame|useEffect|useLayoutEffect/)
    expect(body).not.toMatch(/window\.studio|child_process|['"`]az['"`]/)
    expect(body).not.toMatch(/ado\/local|\.sdlc\/ado|ado\.yaml|schema\.json|me\.json/)
  })

  it('PullNow keeps its pins with the new labels prop: no timer, no effect, no bridge — and the defaults are unchanged', () => {
    const body = read('src/components/ado/PullNow.tsx')
    expect(body).not.toMatch(/setInterval|setTimeout|requestAnimationFrame|useEffect|window\.studio/)
    expect(body).toMatch(/labels\?: Partial<Record<PullKind, string>>/)
    expect(body).toMatch(/fields: 'Pull now', discussion: 'Pull discussion'/)
  })

  it('PullNow without `labels` still reads Pull now / Pull discussion; a label replaces only the one it names', async () => {
    const { PullNow } = await import('../src/components/ado/PullNow')
    render(<PullNow projectPath="/p" capabilities={[...CAPS]} />)
    expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(['Pull now', 'Pull discussion'])
    cleanup()
    render(<PullNow projectPath="/p" capabilities={[...CAPS]} labels={{ discussion: 'Read the comments' }} />)
    expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(['Pull now', 'Read the comments'])
  })
})

// ── the two Today renderers ──────────────────────────────────────────────────────────────────────

const ok: SprintVerbResult = { ok: true, exitCode: 0, refused: false, stdout: '', stderr: '', argv: [], verb: 'ack' }
const ADO_CAPS = [...CC.capabilities, ...CAPS]

function mountColumn(cc: CommandCenter, extra: Partial<Parameters<typeof TodayColumn>[0]> = {}) {
  render(<TodayColumn cc={cc} onRun={vi.fn().mockResolvedValue(ok)} onDecide={vi.fn()} onConfirmTier={vi.fn()} onSince={vi.fn()} onActed={vi.fn()} claudeLine={null} {...extra} />)
  return screen.getByTestId('today')
}

describe('in the Today column', () => {
  it('is a sibling <section data-testid="ado-catch-up"> beside the Azure Boards rows — whose own data-write count stays 0', () => {
    const today = mountColumn(withCc({ ado: adoBlock(PULLED.value), capabilities: ADO_CAPS }))
    expect(section().tagName).toBe('SECTION')
    expect(section().parentElement).toBe(today)
    expect(Array.from(today.children).every((c) => c.tagName === 'SECTION')).toBe(true)
    expect(screen.getByTestId('ado-today').parentElement).toBe(today)
    expect(screen.getByTestId('ado-today').contains(section())).toBe(false)
    expect(screen.getByTestId('ado-today').querySelectorAll('[data-write]')).toHaveLength(0)
    expect(section().querySelectorAll('[data-write]')).toHaveLength(2)
    expect(lineOf().textContent).toBe('Board as of 2026-10-12 09:02')
    expect(screen.getByTestId('needs-you-list').contains(section())).toBe(false)
  })

  it('reads the command center\'s own ado block and capabilities, and the project it names', async () => {
    runAdoVerb.mockResolvedValue(res('pull', 0, PULL_DONE))
    mountColumn(withCc({ ado: adoBlock(NEVER_PULLED), capabilities: ADO_CAPS, projectPath: '/the/project' }))
    expect(lineOf().textContent).toBe(NOT_PULLED_YET)
    fireEvent.click(buttonNamed('Catch up'))
    await screen.findByTestId('fields-pull-result')
    expect(runAdoVerb).toHaveBeenCalledWith('/the/project', { verb: 'pull' })
  })

  it('a pull that read the board asks the host to re-read (`onActed`), so the line above the button stops saying what is no longer true', async () => {
    runAdoVerb.mockResolvedValue(res('pull', 0, PULL_DONE))
    const onActed = vi.fn()
    mountColumn(withCc({ ado: adoBlock(NEVER_PULLED), capabilities: ADO_CAPS }), { onActed })
    fireEvent.click(buttonNamed('Catch up'))
    await waitFor(() => expect(onActed).toHaveBeenCalledTimes(1))
  })

  it('the empty fixture (no ado block, a bare capability list) reads `no data` with every disabled control carrying the sanctioned reason', () => {
    mountColumn(EMPTY_CC)
    expect(lineOf().textContent).toBe(NO_DATA)
    for (const button of section().querySelectorAll<HTMLButtonElement>('button')) {
      expect(button.disabled).toBe(true)
      expect(button.getAttribute('title')).toMatch(/^arrives with a newer plugin: lacks ado-pull/)
    }
    expect(runAdoVerb).not.toHaveBeenCalled()
  })

  it('draws in the strip as well, and spawns nothing on its own', () => {
    vi.useFakeTimers()
    mountColumn(withCc({ ado: adoBlock(PULLED.value), capabilities: ADO_CAPS }), { strip: true })
    expect(within(section()).getAllByRole('button')).toHaveLength(2)
    act(() => { vi.advanceTimersByTime(24 * 60 * 60 * 1000) })
    expect(runAdoVerb).not.toHaveBeenCalled()
  })
})

describe('in the lifecycle home', () => {
  const stage = (id: string, display: string, state: ProjectStage['stage_state'] = 'later'): ProjectStage => ({
    id, name: id, display, status: state, stage_state: state, artifact_count: 0, entered_at: null, completed_at: null, signed_off_by: null,
  })
  const STATUS: ProjectStatus = {
    project_name: 'demo', profile_id: 'p', current_phase: { id: '1', display: 'Phase 1' },
    stages: [stage('0', 'Phase 0: Discovery', 'signed_off'), stage('1', 'Phase 1: Requirements', 'current'), stage('build', 'Build Loop')],
  }

  function home(commandCenter: CommandCenter | null, extra: Partial<Parameters<typeof LifecycleHome>[0]> = {}) {
    // @ts-expect-error - partial test double
    window.studio = {
      getStageReadiness: vi.fn((_p: string, stageId?: string) => Promise.resolve(readinessWith({ stageId: stageId ?? '1', display: `Phase ${stageId ?? '1'}: Stage`, documents: [] }))),
      openDocument: vi.fn().mockReturnValue(new Promise(() => {})),
      onChatActivity: vi.fn((_cb: (activity: ChatActivity) => void) => () => {}),
      runAdoVerb,
    }
    render(
      <main>
        <StageReadinessProvider projectPath="/p" stageId="1">
          <LifecycleHome projectPath="/p" stageId="1" status={STATUS} commandCenter={commandCenter} actor="arjun" setOpening={vi.fn()} onSignedOff={vi.fn()} onOpenDocument={vi.fn()} onNavigate={vi.fn()} {...extra} />
        </StageReadinessProvider>
      </main>,
    )
  }

  it('mounts as a sibling section inside the Today section, beside the Azure Boards rows, with two data-write buttons of its own', async () => {
    home(withCc({ ado: adoBlock(PULLED.value), capabilities: ADO_CAPS }))
    await screen.findByRole('heading', { level: 2 })
    const today = screen.getByTestId('today')
    expect(section().parentElement).toBe(today)
    expect(Array.from(today.children).every((c) => c.tagName === 'SECTION')).toBe(true)
    expect(screen.getByTestId('ado-today').querySelectorAll('[data-write]')).toHaveLength(0)
    expect(section().querySelectorAll('[data-write]')).toHaveLength(2)
    expect(lineOf().textContent).toBe('Board as of 2026-10-12 09:02')
    expect(runAdoVerb).not.toHaveBeenCalled()
  })

  it('before the read lands it says `no data`, digit-free, with nothing spawned', async () => {
    home(null)
    await screen.findByRole('heading', { level: 2 })
    expect(lineOf().textContent).toBe(NO_DATA)
    expect(section().textContent ?? '').not.toMatch(/\d/)
    expect(runAdoVerb).not.toHaveBeenCalled()
  })

  it('Catch up from here pulls for THIS project and tells the host to re-read', async () => {
    runAdoVerb.mockResolvedValue(res('pull', 0, PULL_DONE))
    const onBoardPulled = vi.fn()
    home(withCc({ ado: adoBlock(NEVER_PULLED), capabilities: ADO_CAPS }), { onBoardPulled })
    await screen.findByRole('heading', { level: 2 })
    fireEvent.click(buttonNamed('Catch up'))
    await waitFor(() => expect(onBoardPulled).toHaveBeenCalledTimes(1))
    expect(runAdoVerb).toHaveBeenCalledTimes(1)
    expect(runAdoVerb).toHaveBeenCalledWith('/p', { verb: 'pull' })
  })
})
