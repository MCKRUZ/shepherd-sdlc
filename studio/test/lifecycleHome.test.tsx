// @vitest-environment jsdom
/** The lifecycle home (togo-command-center.md §3.4): StageHome composed with a Today column —
 * needs-you (the addressed list, one action per item), Shepherd's own record of chat activity, and
 * the plugin's open decisions with `today-late-*` ONLY on its `overdue:true`. The screen root is
 * still `<main>`'s first child and holds the stage's h2; the column is a `<section>`, never a
 * third `<aside>`; a block the plugin did not answer reads "no data". */
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ChatActivity, CommandCenter, ProjectStage, ProjectStatus, SourcedBlock, StageDocument } from '../shared/types'
import { NO_DATA, NOTHING_NEEDS_YOU, SIGN_IN_TO_SEE } from '../shared/reasons'
import { LifecycleHome, NEEDS_YOU_SOURCE, WORKING_SOURCE, workingText, LIFECYCLE_TODAY_MAX_HEIGHT_CLASS } from '../src/components/LifecycleHome'
import { StageReadinessProvider } from '../src/components/StageReadinessContext'
import { chatTurnStore, resetChatTurnStore } from '../src/stores/chatTurnStore'
import { readinessWith } from './activityFixtures'

function stage(id: string, display: string, state: ProjectStage['stage_state'] = 'later'): ProjectStage {
  return { id, name: id, display, status: state, stage_state: state, artifact_count: 0, entered_at: null, completed_at: null, signed_off_by: null }
}
const STATUS: ProjectStatus = {
  project_name: 'demo', profile_id: 'p', current_phase: { id: '1', display: 'Phase 1' },
  stages: [stage('0', 'Phase 0: Discovery', 'signed_off'), stage('1', 'Phase 1: Requirements', 'current'), stage('build', 'Build Loop')],
}
const doc = (path: string, ready: boolean): StageDocument => ({ name: path, path, exists: true, folder: false, shaped: true, findingCount: 0, ready })

function block<T = never>(data: T | null, source: string, error: string | null = null): SourcedBlock<T> {
  return { source, fetchedAt: 'now', ok: data !== null, data, error }
}

function cc(over: Partial<CommandCenter> = {}): CommandCenter {
  return {
    projectPath: '/p', fetchedAt: 'now', actor: { name: '@arjun', source: 'roster' }, capabilities: ['sprint-status'],
    sprint: block<never>(null, 'sprint.py status --json'), sprints: block<never>(null, 'sprint.py list --json'), board: block<never>(null, 'spec_status.py --all --json'),
    decisions: block({
      total: 2, open: 2, overdue: 1, clockBusinessDays: 2, logPath: '.sdlc/decision-log.md', exists: true,
      openDecisions: [
        { id: 'DL-03', decision: 'Fail open or closed?', owner: '@arjun', opened: '2026-10-01', due: '2026-10-03', status: 'open', businessDaysOpen: 3, clockDue: '2026-10-03', overdue: true },
        { id: 'DL-04', decision: 'Keep the cache?', owner: '@sam-k', opened: '2026-10-06', due: '2026-10-08', status: 'open', businessDaysOpen: 0, clockDue: '2026-10-08', overdue: false },
      ],
      overdueDecisions: [],
    }, 'track_decisions.py --json'),
    findings: block<never>(null, 'record_findings.py report --json'), scorecard: block<never>(null, 'scorecard.py report --json'), roster: block<never>(null, 'project_settings.py --json'), log: block<never>(null, 'sprint.py log --json'),
    needsYou: [{ kind: 'ack', spec: '0006', action: 'ack', source: 'sprint.py status --json', text: '0006 handed to you by @sam-k' }],
    needsYouReason: null, sinceYesterday: [], since: 1, ...over,
  }
}

function install() {
  const studio = {
    getStageReadiness: vi.fn((_p: string, stageId?: string) => Promise.resolve(readinessWith({ stageId: stageId ?? '1', display: `Phase ${stageId ?? '1'}: Stage`, documents: [doc('a.md', true)] }))),
    openDocument: vi.fn().mockReturnValue(new Promise(() => {})),
    onChatActivity: vi.fn((_cb: (activity: ChatActivity) => void) => () => {}),
  }
  // @ts-expect-error - partial test double
  window.studio = studio
  return studio
}

afterEach(() => {
  cleanup()
  resetChatTurnStore()
  // @ts-expect-error - cleaning up the test double
  delete window.studio
})

function home(commandCenter: CommandCenter | null, stageId = '1', onNeedsYou = vi.fn(), onNavigate = vi.fn()) {
  const utils = render(
    <main>
      <StageReadinessProvider projectPath="/p" stageId={stageId}>
        <LifecycleHome projectPath="/p" stageId={stageId} status={STATUS} commandCenter={commandCenter} actor="arjun" setOpening={vi.fn()} onSignedOff={vi.fn()} onOpenDocument={vi.fn()} onNavigate={onNavigate} onNeedsYou={onNeedsYou} />
      </StageReadinessProvider>
    </main>,
  )
  return { ...utils, onNeedsYou, onNavigate }
}

describe('LifecycleHome', () => {
  it('is the screen root under <main> with the stage heading inside; the Today column is a section, not an aside', async () => {
    install()
    const { container } = home(cc())
    await screen.findByRole('heading', { level: 2, name: 'Phase 1: Stage' })
    const main = container.querySelector('main')!
    expect(main.children).toHaveLength(1)
    expect(main.firstElementChild?.getAttribute('data-testid')).toBe('lifecycle-home')
    expect(main.firstElementChild?.querySelector('h2')).not.toBeNull()
    expect(container.querySelectorAll('aside')).toHaveLength(0)
    expect(screen.getByTestId('today').tagName).toBe('SECTION')
    // v13: as the ≥ 1600 px right column the section caps at the window and scrolls inside — the
    // overlap probe measured it 1030 px tall at 1680×1000, its decisions below the fold.
    expect(screen.getByTestId('today').className).toContain(LIFECYCLE_TODAY_MAX_HEIGHT_CLASS)
    expect(screen.getByTestId('today').className).toContain('min-[1600px]:overflow-y-auto')
  })

  it('needs-you lists the addressed items with one action each; the action hands the item up', async () => {
    install()
    const { onNeedsYou } = home(cc())
    await screen.findByRole('heading', { level: 2 })
    const items = document.querySelectorAll('[data-needs-you-item]')
    expect(items).toHaveLength(1)
    fireEvent.click(within(items[0] as HTMLElement).getByRole('button', { name: 'ack' }))
    expect(onNeedsYou).toHaveBeenCalledWith(expect.objectContaining({ kind: 'ack', spec: '0006' }))
  })

  it('an empty list says so in words, a reason says the reason, no read says no data — never a 0', async () => {
    install()
    home(cc({ needsYou: [] }))
    await screen.findByRole('heading', { level: 2 })
    expect(within(screen.getByTestId('today')).getByText(NOTHING_NEEDS_YOU)).toBeTruthy()
    cleanup()
    home(cc({ needsYou: [], needsYouReason: SIGN_IN_TO_SEE }))
    await screen.findByRole('heading', { level: 2 })
    expect(within(screen.getByTestId('today')).getByText(SIGN_IN_TO_SEE)).toBeTruthy()
    cleanup()
    home(null)
    await screen.findByRole('heading', { level: 2 })
    const column = screen.getByTestId('today')
    expect(within(column).getAllByText(NO_DATA).length).toBeGreaterThanOrEqual(2)
    expect(column.querySelectorAll('[data-stat]')).toHaveLength(0)
  })

  it('decisions carry the plugin\'s clock and tint late only on overdue:true; no log reads "no data — no decision-log"', async () => {
    install()
    home(cc())
    await screen.findByRole('heading', { level: 2 })
    const late = document.querySelector('[data-decision="DL-03"]')!
    const open = document.querySelector('[data-decision="DL-04"]')!
    expect(late.hasAttribute('data-overdue')).toBe(true)
    expect(late.className).toContain('today-late')
    expect(late.textContent).toContain('due 2026-10-03')
    expect(open.hasAttribute('data-overdue')).toBe(false)
    expect(open.className).not.toContain('today-late')
    cleanup()
    home(cc({ decisions: block({ total: 0, open: 0, overdue: 0, clockBusinessDays: 2, openDecisions: [], overdueDecisions: [], logPath: '', exists: false }, 'track_decisions.py --json') }))
    await screen.findByRole('heading', { level: 2 })
    expect(screen.getByText(`${NO_DATA} — no decision-log`)).toBeTruthy()
  })

  it('leaning into Build offers the sprint home; Shepherd\'s record says nothing ran until activity arrives', async () => {
    const studio = install()
    const { onNavigate } = home(cc(), 'build')
    await screen.findByRole('heading', { level: 2 })
    const go = screen.getByRole('button', { name: 'Go to the sprint home →' })
    fireEvent.click(go)
    expect(onNavigate).toHaveBeenCalledWith({ area: 'sprint' })
    // A small secondary on the Needs-you row, never a full-width primary slab.
    expect(go.className).not.toContain('bg-brand-600')
    expect(go.className).not.toContain('w-full')
    expect(go.closest('section[aria-label="Needs you"]')).not.toBeNull()
    expect(screen.getByText('nothing recorded this session')).toBeTruthy()
    expect(studio.onChatActivity).toHaveBeenCalled()
  })

  it('provenance is words in ink-3 with the scripts in the ident face — never a word in ink-4, never a renderer internal', async () => {
    install()
    home(cc())
    await screen.findByRole('heading', { level: 2 })
    const lines = Array.from(document.querySelectorAll<HTMLElement>('[data-provenance]'))
    expect(lines.length).toBeGreaterThanOrEqual(3)
    for (const line of lines) {
      expect(line.className).toContain('text-ink-3')
      expect(line.className).not.toContain('ink-4')
      expect(line.textContent).not.toMatch(/needsYou\[\]|onChatActivity|main:/)
    }
    expect(lines[0].textContent).toContain(NEEDS_YOU_SOURCE.scripts)
    expect(lines[0].textContent).toContain(NEEDS_YOU_SOURCE.how)
    expect(lines[1].textContent).toBe(WORKING_SOURCE)
    // The item's words are their own clamped row, never truncated to a sliver.
    const item = document.querySelector('[data-needs-you-item] [data-needs-you-text]') as HTMLElement
    expect(item.textContent).toBe('0006 handed to you by @sam-k')
    expect(item.className).toContain('line-clamp-2')
    const decision = document.querySelector('[data-decision="DL-03"] [data-decision-text]') as HTMLElement
    expect(decision.className).toContain('line-clamp-2')
  })

  it('"Claude is working" never asserts a present-tense label after the turn ended or failed — the ChatPanel\'s published phase wins', async () => {
    let emit: ((a: { projectPath: string; stageId: string; label: string }) => void) | null = null
    const studio = install()
    studio.onChatActivity.mockImplementation((cb: typeof emit) => { emit = cb; return () => {} })
    home(cc())
    await screen.findByRole('heading', { level: 2 })
    act(() => { emit!({ projectPath: '/p', stageId: '1', label: 'Writing a reply' }) })
    expect(document.querySelector('[data-working-line]')?.textContent).toContain('Writing a reply')
    act(() => { chatTurnStore.publish('/p', '1', 'failed', Date.now() + 1) })
    const line = document.querySelector('[data-working-line]') as HTMLElement
    expect(line.textContent).toContain('last activity')
    expect(line.textContent).toContain('turn failed')
    expect(line.textContent).not.toContain('Writing a reply')
    expect(line.getAttribute('data-turn')).toBe('failed')
    // Another stage's turn is not this stage's.
    act(() => { chatTurnStore.publish('/p', '2', 'running', Date.now() + 2) })
    expect((document.querySelector('[data-working-line]') as HTMLElement).textContent).toContain('turn failed')
    // The pure wording: a running turn with a label keeps the label; an ended turn after it does not.
    const at = new Date('2026-10-06T20:39:00Z')
    expect(workingText({ label: 'Writing a reply', at }, { phase: 'running', at: at.getTime() - 1 })).toEqual({ lead: 'Writing a reply', stamp: '20:39' })
    expect(workingText({ label: 'Writing a reply', at }, { phase: 'ended', at: at.getTime() + 1 })).toEqual({ lead: 'last activity', stamp: '20:39 · turn ended' })
    expect(workingText(null, null)).toBeNull()
  })
})
