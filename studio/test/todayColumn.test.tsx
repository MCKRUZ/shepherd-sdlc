// @vitest-environment jsdom
/** The Today column shows main's lists as they came: needs-you first with one action each,
 * `today-late` only on the plugin's `overdue:true`, verdicts as a lane (never a person), the
 * stream with origin tags and "undated" last, the window as a filter, Standup notes present and
 * disabled with its reason. No IPC of its own — every action is a callback. */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TodayColumn, moreLabel, prUrlFor, stampText, streamSentence, STRIP_ROWS, TEAM_WAITING_CAPTION } from '../src/components/today/TodayColumn'
import { SIGN_IN_TO_SEE, STANDUP_NOTES, STREAM_ARRIVES, UNDATED } from '../shared/reasons'
import type { SprintVerbResult } from '../shared/types'
import { CC, EMPTY_CC, withCc } from './sprintHomeFixture'

afterEach(cleanup)

const ok: SprintVerbResult = { ok: true, exitCode: 0, refused: false, stdout: 'acknowledged', stderr: '', argv: [], verb: 'ack' }

function mount(cc = CC, over: Partial<Parameters<typeof TodayColumn>[0]> = {}) {
  const props = {
    cc,
    onRun: vi.fn().mockResolvedValue(ok),
    onDecide: vi.fn().mockResolvedValue({ ok: true, id: 'DL-01', status: 'decided', decided: '2026-10-06', by: '@arjun-m' }),
    onConfirmTier: vi.fn().mockResolvedValue({ ok: true, changed: true, message: 'confirmed' }),
    onSince: vi.fn(),
    onActed: vi.fn(),
    claudeLine: 'drafted 2 fields · 1 proposal waiting for a yes',
    ...over,
  }
  render(<TodayColumn {...props} />)
  return props
}

describe('needs you', () => {
  it('lists main\'s items in order, each with one action, the overdue one in today-late', () => {
    mount()
    const items = screen.getByTestId('needs-you-list').querySelectorAll('[data-needs-you-item]')
    expect(items).toHaveLength(3)
    expect(items[0].getAttribute('data-kind')).toBe('decide')
    expect(items[0].hasAttribute('data-late')).toBe(true)
    expect(items[0].className).toContain('today-late')
    expect(items[1].className).toContain('today-act')
    expect(within(items[1] as HTMLElement).getByRole('link', { name: 'Open PR' }).getAttribute('href')).toBe('https://example.test/pr/43')
    expect(within(items[2] as HTMLElement).getByRole('button', { name: 'Confirm' })).toBeTruthy()
    expect(items[0].getAttribute('title')).toBe('track_decisions.py --json')
    // The item's words are their own row, clamped to two lines — never truncated to a sliver.
    const text = items[0].querySelector('[data-needs-you-text]') as HTMLElement
    expect(text.textContent).toBe('Fail open or closed?')
    expect(text.className).toContain('line-clamp-2')
    expect(text.className).not.toContain('truncate')
  })

  it('Decide asks for a resolution, records through the callback and tells the host to re-read', async () => {
    const props = mount()
    const item = screen.getByTestId('needs-you-list').querySelector('[data-needs-you-item][data-kind="decide"]') as HTMLElement
    fireEvent.click(within(item).getByRole('button', { name: 'Decide' }))
    fireEvent.change(within(item).getByLabelText('Resolution for DL-01'), { target: { value: 'Fail closed' } })
    fireEvent.click(within(item).getByRole('button', { name: 'Record' }))
    await waitFor(() => expect(props.onDecide).toHaveBeenCalledWith('DL-01', 'Fail closed'))
    await waitFor(() => expect(props.onActed).toHaveBeenCalledTimes(1))
    expect(within(item).getByTestId('needs-you-outcome').textContent).toContain('decided')
  })

  it('Confirm runs confirmTier with the spec id', async () => {
    const props = mount()
    const item = screen.getByTestId('needs-you-list').querySelector('[data-needs-you-item][data-kind="confirm-tier"]') as HTMLElement
    fireEvent.click(within(item).getByRole('button', { name: 'Confirm' }))
    await waitFor(() => expect(props.onConfirmTier).toHaveBeenCalledWith('0012'))
  })

  it('no actor → the sign-in sentence; the chip would be 0 items but no digit is drawn', () => {
    mount(EMPTY_CC)
    expect(screen.getByTestId('needs-you-empty').textContent).toContain(SIGN_IN_TO_SEE)
    expect(screen.getByTestId('needs-you-empty').textContent ?? '').not.toMatch(/\d/)
  })

  it('prUrlFor is a lookup by exact spec id on the board block', () => {
    expect(prUrlFor(CC, '0009')).toBe('https://example.test/pr/43')
    expect(prUrlFor(CC, '0007')).toBeNull()
    expect(prUrlFor(CC, undefined)).toBeNull()
  })
})

describe('team is waiting on, since yesterday, Claude, standup', () => {
  it('verdicts pending are grouped per spec with a lane and the plugin\'s wait — never a person', () => {
    mount()
    const team = screen.getByTestId('team-waiting')
    expect(team.textContent).toContain('0009')
    expect(team.textContent).toContain('eng · 2 business days')
    expect(team.textContent).toContain('data · no data')
    expect(team.textContent).not.toContain('@')
  })

  it('the stream tags each row by origin, dates from the source, undated rows labelled; the window is a filter the person picks', () => {
    const props = mount()
    const rows = screen.getByTestId('stream').querySelectorAll('[data-stream-key]')
    expect(rows).toHaveLength(3)
    expect(rows[0].getAttribute('data-origin')).toBe('log')
    expect(rows[1].getAttribute('data-origin')).toBe('board')
    expect(rows[2].textContent).toContain(UNDATED)
    expect(stampText('2026-10-05T16:10:00Z')).toBe('2026-10-05 16:10')
    expect(stampText(null)).toBe(UNDATED)
    fireEvent.click(screen.getByRole('button', { name: '3 business days' }))
    expect(props.onSince).toHaveBeenCalledWith(3)
  })

  it('without sprint-log the stream says what arrives with a newer plugin', () => {
    mount(withCc({ capabilities: ['sprint-status', 'sprint-write'] }))
    expect(screen.getByTestId('stream-unavailable').textContent).toBe(STREAM_ARRIVES)
  })

  it('Claude\'s line is labelled as Shepherd\'s record; Standup notes is present, disabled, with its reason', () => {
    mount()
    expect(screen.getByTestId('claude-line').textContent).toContain('drafted 2 fields · 1 proposal waiting for a yes')
    expect(screen.getByTestId('claude-line').textContent).toContain("Shepherd's record")
    const standup = screen.getByRole('button', { name: /Standup notes/ })
    expect(standup.hasAttribute('disabled')).toBe(true)
    expect(standup.querySelector('[data-disabled-reason]')?.textContent).toBe(STANDUP_NOTES)
  })
})

describe('a row says each fact once (v13 fixer round)', () => {
  it('a log row whose text is empty shows the id line and the by-line only — no sentence paragraph; a row with other fields shows them', () => {
    const rows = [
      { origin: 'log' as const, key: 'k1', at: '2026-10-06T23:00:00Z', event: 'handoff', spec: '0003', by: 'Pod Lead', text: '', raw: {} },
      { origin: 'log' as const, key: 'k2', at: '2026-10-06T22:00:00Z', event: 'verdict', spec: '0005', by: 'Eng Lead', text: 'lane eng · verdict accepted', raw: {} },
    ]
    mount(withCc({ sinceYesterday: rows }))
    const items = Array.from(screen.getByTestId('stream').querySelectorAll('[data-stream-key]'))
    expect(items[0].querySelector('[data-stream-text]')).toBeNull()
    expect(items[0].querySelector('[data-stream-by]')?.textContent).toBe('by Pod Lead')
    // The event, the spec and `by` appear ONCE each in the row.
    const text = items[0].textContent ?? ''
    expect(text.split('handoff').length - 1).toBe(1)
    expect(text.split('0003').length - 1).toBe(1)
    expect(text.split('Pod Lead').length - 1).toBe(1)
    expect(items[1].querySelector('[data-stream-text]')?.textContent).toBe('lane eng · verdict accepted')
    expect(streamSentence({ text: '  ' })).toBeNull()
    expect(streamSentence({ text: 'PR #40 merged' })).toBe('PR #40 merged')
  })

  it('"a lane, not a person" is said once for the Team-is-waiting group, not under every row', () => {
    mount()
    const team = screen.getByTestId('team-waiting')
    expect(team.textContent).not.toContain(TEAM_WAITING_CAPTION)
    expect(screen.getByTestId('team-waiting-caption').textContent).toBe(TEAM_WAITING_CAPTION)
    expect(document.body.textContent!.split(TEAM_WAITING_CAPTION).length - 1).toBe(1)
  })
})

describe('since yesterday reads whole sentences (owner\'s v12 item 5)', () => {
  it('each row\'s text is its own line, clamped to two lines, never truncated to a sliver; the stamp sits on the id line', () => {
    mount()
    const rows = Array.from(screen.getByTestId('stream').querySelectorAll('[data-stream-key]'))
    expect(rows.length).toBeGreaterThan(0)
    for (const row of rows) {
      const text = row.querySelector('[data-stream-text]') as HTMLElement
      expect(text).not.toBeNull()
      expect(text.className).toContain('line-clamp-2')
      expect(text.className).not.toContain('truncate')
      expect(text.textContent?.length).toBeGreaterThan(0)
      expect(text.getAttribute('title')).toBe(text.textContent)
    }
    expect(screen.getByTestId('today').hasAttribute('data-today-rail')).toBe(true)
  })
})

/** v14 (sprint-home@1280 shot): as the strip above the lanes, Today was a 120 px scroller that
 * sliced "0005 data · today" mid-row behind a fade that read as a cut. The strip is now sized to
 * WHOLE rows: needs-you shows `STRIP_ROWS` in full and folds the rest behind one "N more"
 * disclosure — a last `<li>` of the same list, so every row is still in the list and a count of
 * them is unchanged — and the other groups keep their header and fold every row behind "N rows"
 * (at 1280×800 the strip has ≈ 108 px before the lanes' floor leaves the fold; a stream row is
 * ≈ 80). The rail (the default) draws every row and scrolls. */
describe('the strip folds each group to whole rows', () => {
  it('strip: two needs-you rows whole, the rest behind a closed "N more" in the same list; the other groups fold every row behind "N rows"; the rail folds nothing', () => {
    mount(CC, { strip: true })
    expect(STRIP_ROWS).toBe(2)
    expect(moreLabel(1)).toBe('1 more')
    expect(moreLabel(3, 0)).toBe('3 rows')
    expect(moreLabel(1, 0)).toBe('1 row')
    const list = screen.getByTestId('needs-you-list')
    // Every row is still in the list …
    expect(list.querySelectorAll('[data-needs-you-item]')).toHaveLength(3)
    // … but only two sit on its own line; the third is behind the fold, which is a <details>.
    expect(list.querySelectorAll(':scope > li[data-needs-you-item]')).toHaveLength(2)
    const more = screen.getByTestId('needs-you-more') as HTMLDetailsElement
    expect(more.tagName).toBe('DETAILS')
    expect(more.open).toBe(false)
    expect(more.parentElement?.tagName).toBe('LI')
    expect(more.parentElement?.parentElement).toBe(list)
    expect(more.querySelector('summary')?.textContent).toBe('1 more')
    expect(more.querySelectorAll('[data-needs-you-item]')).toHaveLength(1)
    expect(more.querySelector('[data-needs-you-item]')?.getAttribute('data-kind')).toBe('confirm-tier')
    // The stream keeps its header, window filter and caption, and folds EVERY row (three).
    const stream = screen.getByTestId('stream')
    expect(stream.querySelectorAll('[data-stream-key]')).toHaveLength(3)
    expect(stream.querySelectorAll(':scope > li[data-stream-key]')).toHaveLength(0)
    const streamMore = screen.getByTestId('stream-more') as HTMLDetailsElement
    expect(streamMore.open).toBe(false)
    expect(streamMore.querySelector('summary')?.textContent).toBe('3 rows')
    expect(streamMore.querySelectorAll('[data-stream-key]')).toHaveLength(3)
    expect(screen.getByRole('button', { name: '3 business days' })).toBeTruthy()
    // Team is waiting on: its one row folds too, under its caption.
    const team = screen.getByTestId('team-waiting')
    expect(team.querySelectorAll(':scope > li:not([data-fold])')).toHaveLength(0)
    expect(screen.getByTestId('team-waiting-more').querySelector('summary')?.textContent).toBe('1 row')
    expect(screen.getByTestId('team-waiting-caption')).toBeTruthy()
    // No height cap and no mask on the column: whole rows, never a slice.
    expect(screen.getByTestId('today').className).not.toMatch(/max-h-|mask-image|overflow-y-auto/)
    cleanup()
    mount()
    expect(screen.getByTestId('needs-you-list').querySelectorAll(':scope > li[data-needs-you-item]')).toHaveLength(3)
    expect(screen.getByTestId('stream').querySelectorAll(':scope > li[data-stream-key]')).toHaveLength(3)
    expect(document.querySelector('[data-fold]')).toBeNull()
  })
})
