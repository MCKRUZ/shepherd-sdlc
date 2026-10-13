// @vitest-environment jsdom
/** The Sprint view as a person meets it. The promises here are about honesty rather than
 * function: a value the plugin reports as null reads "no data" and never a zero; a project with no
 * sprint says so and where to start one; nothing on the screen totals work per person; and the
 * only writes are the two pages, each pressed for on purpose. */

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SprintBoard } from '../src/components/SprintBoard'
import type { SprintSlateRow, SprintStatusResult, SprintView } from '../shared/types'

const row = (over: Partial<SprintSlateRow> = {}): SprintSlateRow => ({
  id: '0007', name: 'duplicate-claim-409', risk: 'HIGH', type: 'feature', channel: '', status: 'ready', sprint: 'S07',
  nextOwner: '', engReview: 'accepted', dataReview: 'n-a', dependsOn: [], dor: 'READY', dorBlocking: [],
  path: '/p/specs/0007-duplicate-claim-409.md', relPath: 'specs/0007-duplicate-claim-409.md', ...over,
})

const VIEW: SprintView = {
  ok: true,
  sprint: {
    id: 'S07', goal: 'Adjusters file without a phone call', start: '2026-09-28', end: '2026-10-09', state: 'planning',
    target: 4, mix: 'HIGH:1,MEDIUM:2,LOW:1', boardRef: '', readiedBy: '', closedBy: '', created: '2026-09-25',
    path: '/p/.sdlc/sprints/S07.md', relPath: '.sdlc/sprints/S07.md', days: { total: 10, elapsed: 3, remaining: 7 },
  },
  slate: [
    row(),
    row({
      id: '0008', name: 'claim-export', risk: 'MEDIUM', status: 'draft', nextOwner: '@sam-k', engReview: '', dataReview: 'pending',
      dependsOn: ['0007'], dor: 'NOT READY', dorBlocking: ['## Scope Out: missing', 'acceptance check 3 is vague'],
      path: '/p/specs/0008-claim-export.md', relPath: 'specs/0008-claim-export.md',
    }),
  ],
  readiness: { ready: 1, total: 2, gaps: [{ spec: '0008', gaps: ['DoR NOT READY', 'status is draft'] }] },
  verdictsPending: [{ spec: '0008', lane: 'eng', sinceBusinessDays: null }, { spec: '0008', lane: 'data', sinceBusinessDays: 2 }],
  handoffsOpen: [{ spec: '0008', to: '@sam-k', sinceBusinessDays: null }],
  mix: { HIGH: { target: 1, actual: 1 }, MEDIUM: { target: 2, actual: 1 }, LOW: { target: 1, actual: 0 } },
  mixWarnings: ['LOW: 0 slated of 1 targeted'],
  wip: { inFlight: 0, cap: null },
  buildOrder: ['0007', '0008'],
  nextUp: '0007',
  dependencyGaps: [],
  decisions: null,
  carriedIn: [{ spec: '0007', fromSprint: 'S06', reason: 'blocked on the vendor API' }],
  hasData: true,
  note: null,
}

const NO_SPRINT: SprintView = {
  ...VIEW, sprint: null, slate: [], readiness: { ready: 0, total: 0, gaps: [] }, verdictsPending: [], handoffsOpen: [], mix: {},
  mixWarnings: [], buildOrder: [], nextUp: null, carriedIn: [], hasData: false, note: null,
}

function install(over: Record<string, unknown> = {}) {
  const studio = {
    getSprintStatus: vi.fn().mockResolvedValue(VIEW),
    renderSprintReport: vi.fn().mockResolvedValue({ ok: true, relOutput: '.sdlc/reports/sprint-S07-planning.html' }),
    openReport: vi.fn().mockResolvedValue({ ok: true }),
    ...over,
  }
  // @ts-expect-error - test double, not the full StudioApi surface
  window.studio = studio
  return studio
}

afterEach(() => {
  cleanup()
  // @ts-expect-error - cleaning up the test double
  delete window.studio
})

const board = () => screen.getByTestId('sprint-board')
const section = (id: string) => within(screen.getByTestId(id))

describe('SprintBoard: the sprint as the plugin reports it', () => {
  it('reads the active sprint once on mount and draws the header from the plugin\'s record', async () => {
    const studio = install()
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    expect(await screen.findByTestId('sprint-header')).toBeTruthy()
    expect(studio.getSprintStatus).toHaveBeenCalledTimes(1)
    expect(studio.getSprintStatus).toHaveBeenCalledWith('/p', undefined)
    const header = screen.getByTestId('sprint-header').textContent ?? ''
    expect(header).toContain('Sprint S07')
    expect(header).toContain('Adjusters file without a phone call')
    expect(screen.getByTestId('sprint-state').textContent).toBe('planning')
    expect(header).toContain('2026-09-28 → 2026-10-09')
    expect(screen.getByTestId('sprint-remaining').textContent).toBe('7 business days remaining')
    expect(screen.getByTestId('sprint-target').textContent).toBe('4 specs')
  })

  it('passes a named sprint through', async () => {
    const studio = install()
    render(<SprintBoard projectPath="/p" sprintId="S06" onOpenSpec={vi.fn()} />)
    await screen.findByTestId('sprint-header')
    expect(studio.getSprintStatus).toHaveBeenCalledWith('/p', 'S06')
  })

  it('shows the mix as actual/target chips, its warnings in amber, and the WIP cap as "not set"', async () => {
    install()
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    await screen.findByTestId('sprint-header')
    expect(screen.getAllByTestId('sprint-mix').map((c) => c.textContent)).toEqual(['HIGH 1/1', 'MEDIUM 1/2', 'LOW 0/1'])
    const warnings = screen.getByTestId('sprint-mix-warnings')
    expect(warnings.textContent).toContain('LOW: 0 slated of 1 targeted')
    expect(warnings.className).toContain('amber')
    expect(screen.getByTestId('sprint-wip').textContent).toBe('0 in flight · cap not set')
  })

  it('draws one slate row per spec with the lanes, the next owner and what it depends on', async () => {
    install()
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    await screen.findByTestId('sprint-slate')
    const rows = screen.getAllByTestId('sprint-slate-row')
    expect(rows.map((r) => r.getAttribute('data-spec'))).toEqual(['0007', '0008'])
    const second = within(rows[1])
    expect(second.getByText('claim-export')).toBeTruthy()
    expect(second.getByText('not recorded')).toBeTruthy()
    expect(second.getByText('pending')).toBeTruthy()
    expect(second.getByText('@sam-k')).toBeTruthy()
    expect(second.getByText('0007')).toBeTruthy()
    expect(within(rows[0]).getByText('READY')).toBeTruthy()
    expect(within(rows[0]).getByText('n/a')).toBeTruthy()
  })

  it('the slate sits in one labelled, keyboard-reachable scroll box, and the right-edge fade is only drawn when there is more to the right', async () => {
    install()
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    const slate = await screen.findByTestId('sprint-slate')
    // Ten columns in a ≈ 720 px column: the box scrolls sideways (observatory v4 critique,
    // sprint-table), so it is a region a keyboard user can focus and scroll, named for what it is.
    const scroller = within(slate).getByRole('region', { name: 'Sprint slate, scrolls sideways' })
    expect(scroller.getAttribute('tabindex')).toBe('0')
    expect(scroller.className).toContain('overflow-x-auto')
    expect(scroller.contains(within(slate).getByRole('table', { name: 'Sprint slate' }))).toBe(true)
    // Exactly one scroll box: the kit table's own wrapper is told not to clip.
    expect(scroller.className).toContain('[&>div]:overflow-visible')
    // jsdom has no layout, so nothing overflows: no fade is drawn — it is read from the box's own
    // scroll metrics, never assumed.
    expect(within(slate).queryByTestId('sprint-slate-fade')).toBeNull()
    // A box with more to the right (declared, since jsdom cannot lay one out) grows the fade.
    Object.defineProperty(scroller, 'scrollWidth', { value: 1200, configurable: true })
    Object.defineProperty(scroller, 'clientWidth', { value: 720, configurable: true })
    fireEvent.scroll(scroller)
    const fade = await within(slate).findByTestId('sprint-slate-fade')
    // The fade reads as one (observatory v9, measured in the production window): 64 px wide, held
    // opaque at the border before it dissolves, so a clipped word melts rather than being chopped.
    // Inline `background-image` on purpose (the v6 probe: the Tailwind gradient utilities painted
    // nothing in the production build); the colour is the surface token, so it holds in dark.
    expect(fade.className).toContain('w-16')
    expect(fade.className).toContain('pointer-events-none')
    expect(fade.style.backgroundImage).toContain('var(--color-surface-1) 30%')
    expect(fade.getAttribute('aria-hidden')).toBe('true')
    // Scrolled to the end: the fade goes.
    Object.defineProperty(scroller, 'scrollLeft', { value: 480, configurable: true })
    fireEvent.scroll(scroller)
    await waitFor(() => expect(within(slate).queryByTestId('sprint-slate-fade')).toBeNull())
  })

  it('the right-hand headers — the ones the box clips first — carry the full label as a title', async () => {
    install()
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    const slate = await screen.findByTestId('sprint-slate')
    // "NEXT OWNER" is the header cut at the right edge in the v9 shots; a title says what the cut
    // word is without scrolling. Each header is still a real `<th scope="col">`.
    for (const [name, title] of [['Next owner', 'Next owner'], ['Depends on', 'Depends on'], ['DoR', 'Definition of Ready']] as const) {
      const th = within(slate).getByRole('columnheader', { name })
      expect(th.getAttribute('scope')).toBe('col')
      expect(th.getAttribute('title') === title || th.querySelector(`[title="${title}"]`) !== null).toBe(true)
    }
  })

  it('a NOT READY row holds the checker\'s blocking lines behind a disclosure, in its words', async () => {
    install()
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    await screen.findByTestId('sprint-slate')
    const notReady = within(screen.getAllByTestId('sprint-slate-row')[1])
    expect(notReady.getByText('NOT READY').tagName).toBe('SUMMARY')
    expect(notReady.getByText('## Scope Out: missing')).toBeTruthy()
    expect(notReady.getByText('acceptance check 3 is vague')).toBeTruthy()
  })

  it('a row opens the spec view with the repo-relative path, through the same row shape the board uses', async () => {
    install()
    const onOpenSpec = vi.fn()
    render(<SprintBoard projectPath="/p" onOpenSpec={onOpenSpec} />)
    await screen.findByTestId('sprint-slate')
    fireEvent.click(within(screen.getAllByTestId('sprint-slate-row')[1]).getByRole('button', { name: '0008' }))
    expect(onOpenSpec).toHaveBeenCalledTimes(1)
    expect(onOpenSpec.mock.calls[0][0]).toMatchObject({ spec: '0008', path: 'specs/0008-claim-export.md', name: 'claim-export', status: 'draft', risk: 'MEDIUM' })
  })

  it('beside the slate, the readiness card does not repeat the plugin\'s "DoR: …" line the slate\'s NOT READY cell already carries; the compact panel keeps it', async () => {
    // The plugin's real line order (sprint_model.spec_gaps): the DoR verdict with its reasons
    // first, then status / eng / data. constellation.spec counts NOT READY once per slated spec.
    const real = { ...VIEW, readiness: { ready: 0, total: 1, gaps: [{ spec: '0008', gaps: ['DoR: NOT READY (Scope > In scope is empty)', 'status is draft, not ready', 'eng_review is not recorded, needs accepted'] }] } }
    install({ getSprintStatus: vi.fn().mockResolvedValue(real) })
    const { unmount } = render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    const card = await screen.findByTestId('sprint-readiness')
    expect(card.textContent).toContain('0008 — status is draft, not ready')
    expect(card.textContent).not.toContain('NOT READY')
    expect(card.querySelector('summary')?.textContent).toBe('1 more line')
    unmount()
    const second = render(<SprintBoard projectPath="/p" compact onOpenSpec={vi.fn()} />)
    const compact = await screen.findByTestId('sprint-readiness')
    expect(compact.textContent).toContain('0008 — DoR: NOT READY (Scope > In scope is empty)')
    second.unmount()
  })

  it('lists readiness gaps per spec, verdicts and handoffs with their age, the build order and next up', async () => {
    install()
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    await screen.findByTestId('sprint-readiness')
    expect(section('sprint-readiness').getByText('1 of 2 ready')).toBeTruthy()
    // S7: "id — first gap" on the line; the checker's remaining lines behind a disclosure that
    // is CLOSED by default (sprint.spec counts `details[open]` after opening one NOT READY).
    const readiness = screen.getByTestId('sprint-readiness')
    expect(readiness.textContent).toContain('0008 — DoR NOT READY')
    expect(readiness.textContent).toContain('status is draft')
    const more = readiness.querySelector('details') as HTMLDetailsElement
    expect(more).toBeTruthy()
    expect(more.open).toBe(false)
    expect(more.querySelector('summary')?.textContent).toBe('1 more line')
    // Verdicts pending grouped per spec: the id once, its lanes after it in the plugin's order.
    const verdicts = screen.getByTestId('sprint-verdicts').textContent ?? ''
    expect(verdicts).toContain('0008 · eng · no data · data · 2 business days')
    expect(verdicts.match(/0008/g)).toHaveLength(1)
    expect(screen.getByTestId('sprint-handoffs').textContent).toContain('0008 → @sam-k · no data')
    const next = screen.getByTestId('sprint-next-up').textContent ?? ''
    expect(next).toContain('0007 — READY, dependencies merged')
    expect(next).toContain('Build order: 0007 → 0008')
    expect(screen.getByTestId('sprint-dependency-gaps').textContent).toContain('none')
    expect(screen.getByTestId('sprint-decisions').textContent).toContain('no data — no decision-log')
    expect(screen.getByTestId('sprint-carried-in').textContent).toContain('0007 from S06: blocked on the vendor API')
  })

  it('a 0 the plugin DID report reads "today", never "0 business days"', async () => {
    install({ getSprintStatus: vi.fn().mockResolvedValue({ ...VIEW, verdictsPending: [{ spec: '0007', lane: 'data', sinceBusinessDays: 0 }], handoffsOpen: [{ spec: '0008', to: '@sam-k', sinceBusinessDays: 0 }] }) })
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    await screen.findByTestId('sprint-verdicts')
    expect(screen.getByTestId('sprint-verdicts').textContent).toContain('0007 · data · today')
    expect(screen.getByTestId('sprint-handoffs').textContent).toContain('0008 → @sam-k · today')
    expect(board().textContent).not.toMatch(/0 business days/)
  })

  it('a verdict age the plugin could not compute never reads as 0', async () => {
    install()
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    await screen.findByTestId('sprint-verdicts')
    expect(screen.getByTestId('sprint-verdicts').textContent).not.toMatch(/0 business days/)
    expect(screen.getByTestId('sprint-handoffs').textContent).not.toMatch(/0 business days/)
  })

  it('shows decisions due and overdue when the project keeps a decision log', async () => {
    install({ getSprintStatus: vi.fn().mockResolvedValue({ ...VIEW, decisions: { open: 2, overdue: [{ id: 'D-3', decision: 'Pick the queue', owner: '', due: '2026-10-01' }] } }) })
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    await screen.findByTestId('sprint-decisions')
    const text = screen.getByTestId('sprint-decisions').textContent ?? ''
    expect(text).toContain('2 open · 1 overdue')
    expect(text).toContain('D-3 — Pick the queue (owner: no owner, due 2026-10-01)')
  })

  it('a project with no sprint says so, points at /sprd-sprint new, and shows no count at all', async () => {
    install({ getSprintStatus: vi.fn().mockResolvedValue(NO_SPRINT) })
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    expect((await screen.findByTestId('sprint-empty')).textContent).toBe('No sprint — open one with /sprd-sprint new.')
    expect(screen.queryByTestId('sprint-header')).toBeNull()
    expect(screen.queryByTestId('sprint-readiness')).toBeNull()
    expect(screen.queryByTestId('sprint-pages')).toBeNull()
    expect(board().textContent).not.toMatch(/\b0 of 0\b/)
  })

  it('an unknown sprint id is the plugin\'s own note, not an error and not zeros', async () => {
    install({ getSprintStatus: vi.fn().mockResolvedValue({ ...NO_SPRINT, note: "'S99' names no sprint record — no data" }) })
    render(<SprintBoard projectPath="/p" sprintId="S99" onOpenSpec={vi.fn()} />)
    expect((await screen.findByTestId('sprint-empty')).textContent).toBe("'S99' names no sprint record — no data")
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('a sprint with nothing slated keeps its header and reads "no data" where the counts would be', async () => {
    install({ getSprintStatus: vi.fn().mockResolvedValue({ ...NO_SPRINT, sprint: VIEW.sprint, mix: { HIGH: { target: 1, actual: 0 } } }) })
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    await screen.findByTestId('sprint-header')
    expect(screen.getByTestId('sprint-empty').textContent).toBe('Nothing slated yet — propose a slate with /sprd-sprint slate.')
    expect(screen.queryByTestId('sprint-slate')).toBeNull()
    expect(screen.getByTestId('sprint-readiness').textContent).toContain('no data')
    expect(screen.getByTestId('sprint-readiness').textContent).not.toContain('0 of 0')
    expect(screen.getByTestId('sprint-verdicts').textContent).toContain('no data')
    expect(screen.getByTestId('sprint-handoffs').textContent).toContain('no data')
    expect(screen.getByTestId('sprint-next-up').textContent).toContain('no data')
  })

  it('a closed sprint says who closed it', async () => {
    install({ getSprintStatus: vi.fn().mockResolvedValue({ ...VIEW, sprint: { ...VIEW.sprint!, state: 'closed', closedBy: 'Priya N.' } }) })
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    await screen.findByTestId('sprint-header')
    expect(screen.getByTestId('sprint-state').textContent).toBe('closed')
    expect(screen.getByTestId('sprint-remaining').textContent).toBe('closed by Priya N.')
  })

  it('totals nothing per person: the next owner appears on its row and nowhere as a count', async () => {
    install()
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    await screen.findByTestId('sprint-slate')
    const text = board().textContent ?? ''
    expect(text).not.toMatch(/@sam-k[^\n]*\b\d+\s*(specs?|items?|points?)\b/)
    expect(text).not.toMatch(/velocity|story points|estimate/i)
  })

  it('Refresh reads the sprint again, from inside the sprint header card (the three-button pin)', async () => {
    const studio = install()
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    await screen.findByTestId('sprint-header')
    const refresh = screen.getByRole('button', { name: 'Refresh' })
    expect(screen.getByTestId('sprint-header').contains(refresh)).toBe(true)
    fireEvent.click(refresh)
    await waitFor(() => expect(studio.getSprintStatus).toHaveBeenCalledTimes(2))
    // The board itself draws no heading: SprintScreen's PageHeader is the one "Sprint" h2.
    expect(within(board()).queryByRole('heading', { name: 'Sprint' })).toBeNull()
  })
})

describe('SprintBoard: the two pages', () => {
  it('writes nothing on mount and says the pages stay on this computer', async () => {
    const studio = install()
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    await screen.findByTestId('sprint-pages')
    expect(studio.renderSprintReport).not.toHaveBeenCalled()
    expect(studio.openReport).not.toHaveBeenCalled()
    expect(screen.getByTestId('sprint-pages').textContent).toContain('Reports stay on this computer; they are not shared with the team.')
  })

  it('Planning page writes the planning page for THIS sprint, then opens what the plugin wrote', async () => {
    const studio = install()
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    await screen.findByTestId('sprint-pages')
    fireEvent.click(screen.getByRole('button', { name: 'Planning page' }))
    expect((await screen.findByTestId('sprint-page-result')).textContent).toBe('Planning page written: .sdlc/reports/sprint-S07-planning.html')
    expect(studio.renderSprintReport).toHaveBeenCalledWith('/p', 'S07', 'planning')
    expect(studio.openReport).toHaveBeenCalledWith('/p', '.sdlc/reports/sprint-S07-planning.html')
  })

  it('Review page asks for the review kind', async () => {
    const studio = install({ renderSprintReport: vi.fn().mockResolvedValue({ ok: true, relOutput: '.sdlc/reports/sprint-S07-review.html' }) })
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    await screen.findByTestId('sprint-pages')
    fireEvent.click(screen.getByRole('button', { name: 'Review page' }))
    expect((await screen.findByTestId('sprint-page-result')).textContent).toBe('Review page written: .sdlc/reports/sprint-S07-review.html')
    expect(studio.renderSprintReport).toHaveBeenCalledWith('/p', 'S07', 'review')
    expect(studio.openReport).toHaveBeenCalledWith('/p', '.sdlc/reports/sprint-S07-review.html')
  })

  it('a refused write is the plugin\'s one line, and nothing is opened', async () => {
    const studio = install({ renderSprintReport: vi.fn().mockResolvedValue({ ok: false, error: 'sprint S07 does not exist — run `new` first' }) })
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    await screen.findByTestId('sprint-pages')
    fireEvent.click(screen.getByRole('button', { name: 'Planning page' }))
    expect((await screen.findByRole('alert')).textContent).toBe('sprint S07 does not exist — run `new` first')
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(studio.openReport).not.toHaveBeenCalled()
    expect(screen.queryByTestId('sprint-page-result')).toBeNull()
  })

  it('a refused open keeps the written result and shows the refusal once', async () => {
    install({ openReport: vi.fn().mockResolvedValue({ ok: false, error: 'Shepherd only opens reports from this project’s .sdlc/reports folder.' }) })
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    await screen.findByTestId('sprint-pages')
    fireEvent.click(screen.getByRole('button', { name: 'Planning page' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Shepherd only opens reports from this project’s .sdlc/reports folder.')
    expect(screen.getByTestId('sprint-page-result')).toBeTruthy()
  })
})

describe('SprintBoard: failures and gating', () => {
  it.each<[string, () => Promise<SprintStatusResult>]>([
    ['the call rejects', () => Promise.reject(new Error('The sprint script is missing.'))],
    ['ok is false with a reason', () => Promise.resolve({ ok: false, error: 'state file not found: /p/.sdlc/state.yaml' })],
    ['ok is false with no reason', () => Promise.resolve({ ok: false, error: '' })],
  ])('is exactly one error line and no numbers when %s', async (_name, call) => {
    install({ getSprintStatus: vi.fn(call) })
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    await screen.findByRole('alert')
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.queryByTestId('sprint-header')).toBeNull()
    expect(board().textContent?.replace(/^Sprint.*?specs\./s, '')).not.toMatch(/\d/)
  })

  it('offers nothing and names the missing capability when the installed plugin lacks sprint-status', () => {
    const studio = install()
    render(<SprintBoard projectPath="/p" capabilities={['activities', 'phase-report-json']} onOpenSpec={vi.fn()} />)
    expect(screen.getByTestId('activity-disabled-reason').textContent).toBe('needs a newer plugin: lacks sprint-status')
    expect(studio.getSprintStatus).not.toHaveBeenCalled()
  })

  it('draws the view when the plugin lists sprint-status, or when nothing has said what it supports', async () => {
    install()
    const { unmount } = render(<SprintBoard projectPath="/p" capabilities={['activities', 'sprint-status']} onOpenSpec={vi.fn()} />)
    expect(await screen.findByTestId('sprint-header')).toBeTruthy()
    unmount()
    render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    expect(await screen.findByTestId('sprint-header')).toBeTruthy()
  })

  it('does not show one project\'s sprint after switching to another mid-read', async () => {
    let resolveFirst!: (v: SprintView) => void
    const studio = install({
      getSprintStatus: vi.fn()
        .mockReturnValueOnce(new Promise<SprintView>((r) => { resolveFirst = r }))
        .mockResolvedValueOnce(NO_SPRINT),
    })
    const { rerender } = render(<SprintBoard projectPath="/p" onOpenSpec={vi.fn()} />)
    rerender(<SprintBoard projectPath="/q" onOpenSpec={vi.fn()} />)
    await screen.findByTestId('sprint-empty')
    resolveFirst(VIEW)
    await waitFor(() => expect(studio.getSprintStatus).toHaveBeenCalledTimes(2))
    expect(screen.queryByTestId('sprint-header')).toBeNull()
  })
})

describe('SprintBoard: the compact panel', () => {
  it('is the same picture without the table or the full-view chrome, and never a second heading', async () => {
    install()
    render(<SprintBoard projectPath="/p" compact />)
    const panel = await screen.findByTestId('sprint-panel')
    expect(within(panel).getByTestId('sprint-header')).toBeTruthy()
    expect(within(panel).queryByTestId('sprint-slate')).toBeNull()
    expect(within(panel).queryByRole('heading', { name: 'Sprint' })).toBeNull()
    expect(within(panel).queryByRole('button', { name: 'Refresh' })).toBeNull()
    expect(within(panel).getByTestId('sprint-readiness').textContent).toContain('1 of 2 ready')
    expect(within(panel).getByTestId('sprint-next-up').textContent).toContain('0007')
    expect(within(panel).getByRole('button', { name: 'Planning page' })).toBeTruthy()
  })

  it('says "no sprint" in the panel too', async () => {
    install({ getSprintStatus: vi.fn().mockResolvedValue(NO_SPRINT) })
    render(<SprintBoard projectPath="/p" compact />)
    expect((await screen.findByTestId('sprint-empty')).textContent).toBe('No sprint — open one with /sprd-sprint new.')
  })
})

// --- the screen -------------------------------------------------------------------------------

vi.mock('../src/components/StageReadinessContext', () => ({
  useStageReadiness: () => ({ readiness: { capabilities: ['sprint-status'] }, loading: false, failure: null, refresh: () => {} }),
}))

describe('SprintScreen (S7): title first, then the figure, then the board', () => {
  it('renders the h2 "Sprint" exactly once with the area eyebrow and the lede, above the board', async () => {
    const { SprintScreen } = await import('../src/components/SprintBoard')
    install()
    render(<main><SprintScreen projectPath="/p" onOpenSpec={vi.fn()} /></main>)
    await screen.findByTestId('sprint-header')
    const headings = screen.getAllByRole('heading', { name: 'Sprint' })
    expect(headings).toHaveLength(1)
    expect(headings[0].tagName).toBe('H2')
    expect(headings[0].hasAttribute('data-page-heading')).toBe(true)
    const header = headings[0].closest('header')!
    // The sprint id reaches the eyebrow one render after the board's own card appears (the
    // board reports its view through `onView` in an effect), so the eyebrow is awaited, not read.
    await waitFor(() => expect(header.textContent).toContain('Build · Sprint S07'))
    expect(header.textContent).toContain('What the team committed to, as the plugin reads it from the specs.')
    // The header is the screen root's first child, the board after it.
    const root = document.querySelector('main')!.firstElementChild!
    expect(root.firstElementChild).toBe(header)
    expect(Array.from(root.children).indexOf(screen.getByTestId('sprint-board'))).toBeGreaterThan(0)
  })
})
