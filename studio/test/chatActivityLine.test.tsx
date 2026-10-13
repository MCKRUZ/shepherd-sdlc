// @vitest-environment jsdom
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { ChatActivityLine, SILENT_HINT_AFTER_SECONDS, activityText, silenceHint } from '../src/components/ChatActivityLine'
import type { ChatActivity } from '../shared/types'

describe('activityText / silenceHint — the wording', () => {
  it('falls back to "Thinking…" with the clock before any step has arrived', () => {
    expect(activityText(null, 0)).toBe('Thinking… 0s')
    expect(activityText(null, 9)).toBe('Thinking… 9s')
  })

  it('shows the step with the clock once one has arrived', () => {
    expect(activityText('Reading requirements.md', 14)).toBe('Reading requirements.md… 14s')
  })

  it('stays quiet until the silence is long enough to matter, then says so', () => {
    expect(silenceHint(SILENT_HINT_AFTER_SECONDS - 1)).toBeNull()
    expect(silenceHint(SILENT_HINT_AFTER_SECONDS)).toMatch(/No new step for 20s/)
  })
})

describe('ChatActivityLine', () => {
  let emit: (activity: ChatActivity) => void
  let unsubscribe: Mock<() => void>

  beforeEach(() => {
    vi.useFakeTimers()
    unsubscribe = vi.fn<() => void>()
    // @ts-expect-error - test double, not the full StudioApi surface
    window.studio = {
      onChatActivity: vi.fn((cb: (a: ChatActivity) => void) => { emit = cb; return unsubscribe }),
    }
  })

  afterEach(() => {
    vi.useRealTimers()
    // @ts-expect-error - cleaning up the test double
    delete window.studio
  })

  it('starts as "Thinking… 0s" and counts up each second, so a slow turn is visibly alive', () => {
    render(<ChatActivityLine projectPath="/p" stageId="0" />)
    expect(screen.getByTestId('chat-activity').textContent).toBe('Thinking… 0s')
    act(() => { vi.advanceTimersByTime(5000) })
    expect(screen.getByTestId('chat-activity').textContent).toBe('Thinking… 5s')
  })

  it('swaps in the step the main process reports for THIS project and stage', () => {
    render(<ChatActivityLine projectPath="/p" stageId="0" />)
    act(() => { vi.advanceTimersByTime(3000) })
    act(() => emit({ projectPath: '/p', stageId: '0', label: 'Reading requirements.md' }))
    expect(screen.getByTestId('chat-activity').textContent).toBe('Reading requirements.md… 3s')
  })

  it('ignores a step from a different stage or project — another stage\'s turn is not this one\'s activity', () => {
    render(<ChatActivityLine projectPath="/p" stageId="0" />)
    act(() => emit({ projectPath: '/p', stageId: '1', label: 'Searching the project' }))
    act(() => emit({ projectPath: '/other', stageId: '0', label: 'Searching the project' }))
    expect(screen.getByTestId('chat-activity').textContent).toBe('Thinking… 0s')
  })

  it('says the assistant is probably writing a long reply after a long gap with no new step, and clears it on the next step', () => {
    render(<ChatActivityLine projectPath="/p" stageId="0" />)
    act(() => emit({ projectPath: '/p', stageId: '0', label: 'Reading a.md' }))
    act(() => { vi.advanceTimersByTime((SILENT_HINT_AFTER_SECONDS + 1) * 1000) })
    expect(screen.getByTestId('chat-activity').textContent).toMatch(/Reading a\.md….*No new step for 21s.*long reply/)
    act(() => emit({ projectPath: '/p', stageId: '0', label: 'Writing a reply' }))
    expect(screen.getByTestId('chat-activity').textContent).not.toMatch(/No new step/)
  })

  it('unsubscribes and stops its timer when the turn ends (unmount)', () => {
    const { unmount } = render(<ChatActivityLine projectPath="/p" stageId="0" />)
    unmount()
    expect(unsubscribe).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
  })
})
