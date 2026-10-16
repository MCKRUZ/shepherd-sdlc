// @vitest-environment jsdom
/** The Azure Boards rows of the Today column (build kit §5 B4-P4, K18): a sibling
 * `<section data-testid="ado-today">` fed by `commandCenter.ado` (the plugin's `ado_sync.py status --json`) and
 * mounted in both Today renderers — `TodayColumn` and `LifecycleHome`. Two `role="listitem"` rows, each with one
 * action and NO `data-write`; a board that was never pulled reads "Not pulled yet" with no digit; a measured
 * zero is words, never a number the plugin did not give. `NeedsYouItem.kind` is not widened: the rows are not
 * needs-you items. The rows make no IPC call and never read the plugin's local cache. */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AdoSyncView } from '../shared/adoTypes'
import type { AdoVerbRequest } from '../shared/adoVerbArgv'
import type { AdoVerbResult, ChatActivity, CommandCenter, NeedsYouItem, ProjectStage, ProjectStatus, SourcedBlock, SprintVerbResult } from '../shared/types'
import { isReason, NOT_PULLED_YET } from '../shared/reasons'
import { TodayColumn } from '../src/components/today/TodayColumn'
import { AdoTodayRows, adoTodayRows, NOTHING_WAITING, UNMAPPED_NOT_COUNTED } from '../src/components/today/AdoTodayRows'
import { LifecycleHome } from '../src/components/LifecycleHome'
import { StageReadinessProvider } from '../src/components/StageReadinessContext'
import { resetChatTurnStore } from '../src/stores/chatTurnStore'
import { readinessWith } from './activityFixtures'
import { block, CC, EMPTY_CC, withCc } from './sprintHomeFixture'
import type { ConnectionInfo } from '../shared/types'
import { connectionStore, resetConnectionStore } from '../src/stores/connectionStore'

// Since B6 fix r4 the Today column mounts its Boards sections only where a board can exist (`BoardsToday`): the
// connection says Azure DevOps, or a status was read. These rows are about an Azure DevOps project whose board
// was never pulled, so the connection is set to one; `boardsToday.test.tsx` pins the other hosts.
const AZURE_CONNECTION: ConnectionInfo = {
  host: 'azure-devops', hostSource: 'remote', cli: { name: 'az', found: true, extension: true, signedIn: 'yes' }, lastPulledAt: null, branchProtected: null,
} as unknown as ConnectionInfo
beforeEach(() => { connectionStore.set(AZURE_CONNECTION) })
afterEach(() => { resetConnectionStore() })

const SOURCE = 'ado_sync.py status --json'
const GOLDEN = resolve(__dirname, '..', '..', 'scripts', 'tests', 'golden', 'ado_status_nodata.json')
/** The plugin's own never-pulled document, read from its golden (so a key it adds or renames turns this red). */
const NEVER_PULLED = JSON.parse(readFileSync(GOLDEN, 'utf-8')) as AdoSyncView

// Hand-written (unverified): a pulled board, in the shape `ado_sync_model.summarize` documents. 5 open rows by
// class, 4 refs among them, 1 conflict; `pending` stays null because no plan was ever written.
const MEASURED = {
  _provenance: 'hand-written (unverified)',
  _command: ['ado_sync.py', 'status', '--json'],
  value: {
    as_of: '2026-10-12T09:02:00Z',
    by_class: { ADO_OWNED_CHANGE: 1, CONFLICT: 1, UNMAPPED_IN_ADO: 3 },
    counts: { conflicts: 1, debt: 1, drifted: 4, linked: 5, open: 5, pending: null },
    debt: [{ ref: 'sdlc:spec:0004', field: 'System.State', class: 'SDLC_OWNED_DRIFT', seen: '2026-10-07', due: '2026-10-09' }],
    hook_line: 'no plan yet · 4 drifted · as of 2026-10-12T09:02Z', last_plan: null, ledger: '.sdlc/metrics/ado-sync-log.jsonl', notes: [], schema: 1,
  } satisfies AdoSyncView,
}
// Hand-written (unverified): a pull that found nothing — by_class is `{}` (a read that found none), not null.
// A pull classes only the ledgered items: `{}` holds no UNMAPPED_IN_ADO entry because that search never ran.
const CLEAN = {
  _provenance: 'hand-written (unverified)',
  _command: ['ado_sync.py', 'status', '--json'],
  value: { ...MEASURED.value, by_class: {}, counts: { conflicts: 0, debt: 0, drifted: 0, linked: 5, open: 0, pending: null }, debt: [], hook_line: 'no plan yet · 0 drifted · as of 2026-10-12T09:02Z' } satisfies AdoSyncView,
}
// Hand-written (unverified): the same clean pull, with the plugin's OWN zero for the unmapped search.
const CLEAN_SEARCHED = {
  _provenance: 'hand-written (unverified)',
  _command: ['ado_sync.py', 'status', '--json'],
  value: { ...CLEAN.value, by_class: { UNMAPPED_IN_ADO: 0 } } satisfies AdoSyncView,
}

const adoBlock = (data: AdoSyncView | null, error: string | null = null): SourcedBlock<AdoSyncView> => block(SOURCE, data, error)

afterEach(() => {
  cleanup()
  resetChatTurnStore()
  // @ts-expect-error - cleaning up the test double
  delete window.studio
})

let runAdoVerb: ReturnType<typeof vi.fn<(projectPath: string, request: AdoVerbRequest) => Promise<AdoVerbResult>>>
beforeEach(() => {
  runAdoVerb = vi.fn()
  // @ts-expect-error - partial test double: the rows must never reach for it
  window.studio = { runAdoVerb }
})

const ok: SprintVerbResult = { ok: true, exitCode: 0, refused: false, stdout: '', stderr: '', argv: [], verb: 'ack' }
function mountColumn(cc: CommandCenter, strip = false) {
  render(
    <TodayColumn cc={cc} strip={strip} onRun={vi.fn().mockResolvedValue(ok)} onDecide={vi.fn()} onConfirmTier={vi.fn()} onSince={vi.fn()} onActed={vi.fn()} claudeLine={null} />,
  )
  return screen.getByTestId('ado-today')
}

describe('adoTodayRows: what the plugin measured, in words', () => {
  it('the never-pulled golden is two digit-free "Not pulled yet" rows with their actions withheld for that reason', () => {
    const rows = adoTodayRows(adoBlock(NEVER_PULLED))
    expect(rows.map((r) => r.key)).toEqual(['drift', 'unmapped'])
    for (const row of rows) {
      expect(row.text).toBe(NOT_PULLED_YET)
      expect(row.measured).toBe(false)
      expect(row.reason).toBe(NOT_PULLED_YET)
      expect(row.detail).toEqual([])
    }
    expect(rows.map((r) => r.action)).toEqual(['Show', 'Propose spec'])
  })

  it('an absent block (the answer main builds by hand), a null block and an empty read are all "no data" — never a zeroed shape', () => {
    for (const none of [undefined, null, adoBlock(null)]) {
      const rows = adoTodayRows(none)
      expect(rows.map((r) => r.text)).toEqual([NOT_PULLED_YET, NOT_PULLED_YET])
      expect(rows.every((r) => !r.measured)).toBe(true)
    }
  })

  it('a pulled board reads its counts: items changed with the conflicts, and items with no spec here', () => {
    const [drift, unmapped] = adoTodayRows(adoBlock(MEASURED.value))
    expect(drift!.text).toBe('4 items changed on the board · 1 in conflict')
    expect(drift!.measured).toBe(true)
    expect(drift!.reason).toBeNull()
    expect(drift!.detail).toContain('ADO_OWNED_CHANGE · 1')
    expect(drift!.detail).toContain('CONFLICT · 1')
    expect(drift!.detail).toContain('sdlc:spec:0004 · System.State · SDLC_OWNED_DRIFT · due 2026-10-09')
    expect(unmapped!.text).toBe('3 items on the board with no spec here')
    expect(unmapped!.reason).toBeNull()
    expect(unmapped!.detail.join('\n')).toContain('ado_sync.py pull --propose-specs')
  })

  it('a count of one is singular; no conflict leaves the conflict clause off', () => {
    const one = { ...MEASURED.value, counts: { ...MEASURED.value.counts, drifted: 1, conflicts: 0 }, by_class: { UNMAPPED_IN_ADO: 1 } }
    const [drift, unmapped] = adoTodayRows(adoBlock(one))
    expect(drift!.text).toBe('1 item changed on the board')
    expect(unmapped!.text).toBe('1 item on the board with no spec here')
  })

  it('a read that found none says so in words, with no digit, and offers no action it could not take', () => {
    const rows = adoTodayRows(adoBlock(CLEAN_SEARCHED.value))
    expect(rows.map((r) => r.text)).toEqual(['nothing changed on the board since the last pull', 'no item on the board is without a spec here'])
    for (const row of rows) {
      expect(row.text).not.toMatch(/\d/)
      expect(row.measured).toBe(true)
      expect(row.reason).toBe(NOTHING_WAITING)
    }
  })

  it('a by_class with no UNMAPPED_IN_ADO entry is "not counted" — the search never ran, so it is never a zero', () => {
    const [drift, unmapped] = adoTodayRows(adoBlock(CLEAN.value))
    expect(drift!.text).toBe('nothing changed on the board since the last pull')
    expect(drift!.measured).toBe(true)
    expect(unmapped!.text).toBe(UNMAPPED_NOT_COUNTED)
    expect(unmapped!.text).not.toMatch(/\d/)
    expect(unmapped!.text).not.toContain('no item')
    expect(unmapped!.measured).toBe(false)
    expect(unmapped!.reason).toBeNull()
    expect(unmapped!.detail.join('\n')).toContain('ado_sync.py pull --propose-specs')
    const pulledNotSearched = { ...MEASURED.value, by_class: { ADO_OWNED_CHANGE: 1, CONFLICT: 1 } }
    expect(adoTodayRows(adoBlock(pulledNotSearched))[1]!.text).toBe(UNMAPPED_NOT_COUNTED)
    expect(adoTodayRows(adoBlock(pulledNotSearched))[1]!.measured).toBe(false)
  })

  it('a pull that measured drift but never classed it keeps the unmapped row as no data, not zero', () => {
    const [, unmapped] = adoTodayRows(adoBlock({ ...MEASURED.value, by_class: null }))
    expect(unmapped!.text).toBe(NOT_PULLED_YET)
    expect(unmapped!.measured).toBe(false)
  })

  it('a block the plugin could not answer shows the plugin\'s own sentence on both rows, as the reason for the action', () => {
    const rows = adoTodayRows(adoBlock(null, 'arrives with a newer plugin: lacks ado-status-json'))
    for (const row of rows) {
      expect(row.text).toBe('arrives with a newer plugin: lacks ado-status-json')
      expect(row.reason).toBe('arrives with a newer plugin: lacks ado-status-json')
      expect(row.measured).toBe(false)
    }
  })
})

describe('the rows in the Today column', () => {
  it('is a sibling <section data-testid="ado-today"> of the Today groups, not inside needs-you', () => {
    const section = mountColumn(withCc({ ado: adoBlock(MEASURED.value) }))
    expect(section.tagName).toBe('SECTION')
    const today = screen.getByTestId('today')
    expect(section.parentElement).toBe(today)
    expect(Array.from(today.children).every((c) => c.tagName === 'SECTION')).toBe(true)
    expect(screen.getByTestId('needs-you-list').contains(section)).toBe(false)
    expect(within(screen.getByTestId('needs-you-list')).queryByText(/on the board/)).toBeNull()
  })

  it('has two role="listitem" rows with one action each and zero data-write', () => {
    const section = mountColumn(withCc({ ado: adoBlock(MEASURED.value) }))
    const items = within(section).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    for (const item of items) {
      expect(item.getAttribute('role')).toBe('listitem')
      expect(item.querySelectorAll('button')).toHaveLength(1)
    }
    expect(items[0]!.getAttribute('data-ado-row')).toBe('drift')
    expect(items[1]!.getAttribute('data-ado-row')).toBe('unmapped')
    expect(within(items[0]!).getByRole('button', { name: 'Show' })).toBeTruthy()
    expect(within(items[1]!).getByRole('button', { name: 'Propose spec' })).toBeTruthy()
    expect(section.querySelectorAll('[data-write]')).toHaveLength(0)
    expect(section.querySelectorAll('input, textarea')).toHaveLength(0)
  })

  it('names its source and the as-of the plugin gave', () => {
    const section = mountColumn(withCc({ ado: adoBlock(MEASURED.value) }))
    expect(section.querySelector('[data-ado-row="drift"]')?.getAttribute('title')).toBe(SOURCE)
    expect(within(section).getByTestId('ado-as-of').textContent).toContain('2026-10-12 09:02')
  })

  it('"Not pulled yet" with no digit when the board was never pulled; the actions are disabled with that reason', () => {
    const section = mountColumn(withCc({ ado: adoBlock(NEVER_PULLED) }))
    expect(section.textContent ?? '').not.toMatch(/\d/)
    for (const row of section.querySelectorAll('[data-ado-row]')) {
      expect(row.querySelector('[data-ado-text]')?.textContent).toBe(NOT_PULLED_YET)
      const button = row.querySelector('button')!
      expect(button.disabled).toBe(true)
      expect(button.getAttribute('title')).toBe(NOT_PULLED_YET)
      expect(isReason(button.getAttribute('title'))).toBe(true)
    }
    expect(section.querySelectorAll('[data-write]')).toHaveLength(0)
    expect(within(section).queryByTestId('ado-as-of')).toBeNull()
  })

  it('no ado block at all (EMPTY_CC) is the same: two "Not pulled yet" rows, digit-free, every disabled control with a sanctioned reason', () => {
    const section = mountColumn(EMPTY_CC)
    expect(Array.from(section.querySelectorAll('[data-ado-text]')).map((n) => n.textContent)).toEqual([NOT_PULLED_YET, NOT_PULLED_YET])
    expect(section.textContent ?? '').not.toMatch(/\d/)
    for (const button of section.querySelectorAll('button')) {
      expect(isReason(button.getAttribute('title'))).toBe(true)
    }
  })

  it('Show reveals which changes are waiting — the classes and the rows past their clock, by ref and field, never a person', () => {
    const section = mountColumn(withCc({ ado: adoBlock(MEASURED.value) }))
    const show = within(section).getByRole('button', { name: 'Show' })
    expect(show.getAttribute('aria-expanded')).toBe('false')
    expect(section.querySelector('[data-ado-detail="drift"]')).toBeNull()
    fireEvent.click(show)
    const detail = section.querySelector('[data-ado-detail="drift"]')!
    expect(show.getAttribute('aria-expanded')).toBe('true')
    expect(detail.textContent).toContain('CONFLICT · 1')
    expect(detail.textContent).toContain('sdlc:spec:0004 · System.State · SDLC_OWNED_DRIFT · due 2026-10-09')
    expect(detail.textContent).not.toContain('@')
    fireEvent.click(show)
    expect(section.querySelector('[data-ado-detail="drift"]')).toBeNull()
  })

  it('Propose spec shows the line the plugin runs and says Shepherd does not run it — it is not a write from here', () => {
    const section = mountColumn(withCc({ ado: adoBlock(MEASURED.value) }))
    fireEvent.click(within(section).getByRole('button', { name: 'Propose spec' }))
    const detail = section.querySelector('[data-ado-detail="unmapped"]')!
    expect(detail.querySelector('code')?.textContent).toBe('ado_sync.py pull --propose-specs')
    expect(detail.textContent).toContain('Shepherd does not run this one')
    expect(section.querySelectorAll('[data-write]')).toHaveLength(0)
  })

  it('a measured zero disables both actions with "Nothing is waiting here"', () => {
    const section = mountColumn(withCc({ ado: adoBlock(CLEAN_SEARCHED.value) }))
    for (const button of section.querySelectorAll('button')) {
      expect(button.disabled).toBe(true)
      expect(button.getAttribute('title')).toBe(NOTHING_WAITING)
    }
  })

  it('a pull that never searched for unmapped items says "not counted" and still shows the line that searches', () => {
    const section = mountColumn(withCc({ ado: adoBlock(CLEAN.value) }))
    const row = section.querySelector('[data-ado-row="unmapped"]')!
    expect(row.querySelector('[data-ado-text]')?.textContent).toBe(UNMAPPED_NOT_COUNTED)
    expect(row.querySelector('[data-ado-text]')?.textContent ?? '').not.toMatch(/\d/)
    const propose = within(row as HTMLElement).getByRole('button', { name: 'Propose spec' })
    expect(propose.hasAttribute('disabled')).toBe(false)
    expect(propose.getAttribute('title')).not.toBe(NOTHING_WAITING)
    fireEvent.click(propose)
    expect(section.querySelector('[data-ado-detail="unmapped"] code')?.textContent).toBe('ado_sync.py pull --propose-specs')
    expect(section.querySelector('[data-ado-row="drift"] button')!.getAttribute('title')).toBe(NOTHING_WAITING)
    expect(section.querySelectorAll('[data-write]')).toHaveLength(0)
  })

  it('makes no IPC call of its own: opening and closing the rows never reaches the bridge', () => {
    const section = mountColumn(withCc({ ado: adoBlock(MEASURED.value) }))
    fireEvent.click(within(section).getByRole('button', { name: 'Show' }))
    fireEvent.click(within(section).getByRole('button', { name: 'Propose spec' }))
    expect(runAdoVerb).not.toHaveBeenCalled()
  })

  it('draws in the strip as well, still a sibling section with both rows', () => {
    const section = mountColumn(withCc({ ado: adoBlock(MEASURED.value) }), true)
    expect(section.parentElement).toBe(screen.getByTestId('today'))
    expect(within(section).getAllByRole('listitem')).toHaveLength(2)
  })

  it('leaves the needs-you list exactly as main built it: the rows are not needs-you items', () => {
    mountColumn(withCc({ ado: adoBlock(MEASURED.value) }))
    expect(screen.getByTestId('needs-you-list').querySelectorAll('[data-needs-you-item]')).toHaveLength(CC.needsYou.length)
    // Type-level pin (tsc over this file): widening `NeedsYouItem.kind` leaves a key out of this record.
    const kinds: Record<NeedsYouItem['kind'], true> = { ack: true, review: true, decide: true, 'confirm-tier': true }
    expect(Object.keys(kinds).sort()).toEqual(['ack', 'confirm-tier', 'decide', 'review'])
  })

  it('AdoTodayRows alone renders from a null command center without a throw', () => {
    render(<AdoTodayRows cc={null} />)
    expect(Array.from(screen.getByTestId('ado-today').querySelectorAll('[data-ado-text]')).map((n) => n.textContent)).toEqual([NOT_PULLED_YET, NOT_PULLED_YET])
  })
})

describe('the same rows in the lifecycle home', () => {
  const stage = (id: string, display: string, state: ProjectStage['stage_state'] = 'later'): ProjectStage => ({
    id, name: id, display, status: state, stage_state: state, artifact_count: 0, entered_at: null, completed_at: null, signed_off_by: null,
  })
  const STATUS: ProjectStatus = {
    project_name: 'demo', profile_id: 'p', current_phase: { id: '1', display: 'Phase 1' },
    stages: [stage('0', 'Phase 0: Discovery', 'signed_off'), stage('1', 'Phase 1: Requirements', 'current'), stage('build', 'Build Loop')],
  }

  function home(commandCenter: CommandCenter | null) {
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
          <LifecycleHome projectPath="/p" stageId="1" status={STATUS} commandCenter={commandCenter} actor="arjun" setOpening={vi.fn()} onSignedOff={vi.fn()} onOpenDocument={vi.fn()} onNavigate={vi.fn()} />
        </StageReadinessProvider>
      </main>,
    )
  }

  it('mounts as a sibling section inside the Today section, beside needs-you, Claude and decisions', async () => {
    home(withCc({ ado: adoBlock(MEASURED.value) }))
    await screen.findByRole('heading', { level: 2 })
    const today = screen.getByTestId('today')
    const section = within(today).getByTestId('ado-today')
    expect(section.tagName).toBe('SECTION')
    expect(section.parentElement).toBe(today)
    expect(Array.from(today.children).every((c) => c.tagName === 'SECTION')).toBe(true)
    expect(within(section).getAllByRole('listitem')).toHaveLength(2)
    expect(section.querySelectorAll('[data-write]')).toHaveLength(0)
    expect(document.querySelectorAll('aside')).toHaveLength(0)
  })

  it('before the read lands it says "Not pulled yet", digit-free', async () => {
    home(null)
    await screen.findByRole('heading', { level: 2 })
    const section = screen.getByTestId('ado-today')
    expect(Array.from(section.querySelectorAll('[data-ado-text]')).map((n) => n.textContent)).toEqual([NOT_PULLED_YET, NOT_PULLED_YET])
    expect(section.textContent ?? '').not.toMatch(/\d/)
  })
})

describe('the Boards renderers keep the truth rule', () => {
  const FILES = [
    'src/components/ado/DiscussionBlock.tsx',
    'src/components/ado/CommentComposer.tsx',
    'src/components/today/AdoTodayRows.tsx',
  ].map((rel) => ({ rel, source: readFileSync(resolve(__dirname, '..', rel), 'utf-8') }))

  /** Comments are removed first: the files say in prose what they never read. */
  const code = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, '').split(/\r?\n/).map((l) => l.replace(/(^|\s)\/\/.*$/, '')).join('\n')

  it('never names the plugin\'s local cache or the mirror\'s files — the renderer reads the plugin\'s JSON only', () => {
    for (const { rel, source } of FILES) {
      expect(code(source), rel).not.toMatch(/ado\/local|\.sdlc\/ado|ado\.yaml|schema\.json|me\.json/)
    }
  })

  it('never builds HTML from text, never fetches, never opens a window of its own', () => {
    for (const { rel, source } of FILES) {
      expect(code(source), rel).not.toMatch(/dangerouslySetInnerHTML|innerHTML|\bfetch\(|XMLHttpRequest|window\.open|eval\(/)
    }
  })

  it('AdoTodayRows is a pure view: no window.studio at all', () => {
    expect(code(FILES[2]!.source)).not.toContain('window.studio')
  })

  it('the only bridge call the Boards components make is the closed runAdoVerb', () => {
    for (const { rel, source } of FILES.slice(0, 2)) {
      const calls = [...code(source).matchAll(/studio\.(\w+)/g)].map((m) => m[1])
      expect(new Set(calls), rel).toEqual(new Set(calls.filter((c) => c === 'runAdoVerb')))
    }
  })
})
