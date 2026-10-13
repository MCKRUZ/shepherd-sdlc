// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ActivitiesPanel, buildTalkMessage } from '../src/components/ActivitiesPanel'
import { ChatPanel } from '../src/components/ChatPanel'
import { StageReadinessProvider } from '../src/components/StageReadinessContext'
import type { ChatState, ChatTurnResult } from '../shared/types'
import { activity, readinessWith } from './activityFixtures'

const TALK = activity({ id: 'rules-talk', kind: 'talk', label: 'Business rules', command: 'sprd-rules' })
const READINESS = readinessWith({ capabilities: ['activities'], activities: [TALK] })

function emptyState(): ChatState {
  return { sessionId: null, messages: [] }
}

function install() {
  const studio = {
    getChatState: vi.fn().mockResolvedValue({ sessionId: 's', messages: [{ id: 'm', role: 'assistant', text: 'hi', proposals: [], questions: [] }] }),
    onChatActivity: vi.fn().mockReturnValue(() => {}),
    getStageReadiness: vi.fn().mockResolvedValue(READINESS),
    ensureChatStarted: vi.fn().mockResolvedValue({ ok: true, state: emptyState() } satisfies ChatTurnResult),
    sendChatMessage: vi.fn().mockResolvedValue({ ok: true, state: emptyState() } satisfies ChatTurnResult),
  }
  // @ts-expect-error - test double, not the full StudioApi surface
  window.studio = studio
  return studio
}

afterEach(() => {
  // @ts-expect-error - cleaning up the test double
  delete window.studio
})

function renderBoth(withChat: boolean) {
  return render(
    <StageReadinessProvider projectPath="/p" stageId="1">
      <ActivitiesPanel projectPath="/p" readiness={READINESS} onOpenDocument={vi.fn()} />
      {withChat && <ChatPanel status={null} projectPath="/p" actor="matt" stageId="1" />}
    </StageReadinessProvider>,
  )
}

describe('Talk it through', () => {
  it('names the stage and the command and starts with the [Studio] marker', () => {
    expect(buildTalkMessage(TALK, 'Phase 1: Requirements')).toBe(
      '[Studio] The person has opened the "Business rules" step (/sprd-rules) in the Requirements stage and wants to talk it through. Help with this step now.',
    )
  })

  it('sends exactly one [Studio] turn through the chat send path per click', async () => {
    const studio = install()
    renderBoth(true)
    await waitFor(() => expect(screen.getByPlaceholderText('Type a message…')).toBeTruthy())
    const talk = screen.getByRole('button', { name: 'Talk it through' })
    await waitFor(() => expect(talk.hasAttribute('disabled')).toBe(false))

    fireEvent.click(talk)

    await waitFor(() => expect(studio.sendChatMessage).toHaveBeenCalledTimes(1))
    const [project, stage, text] = studio.sendChatMessage.mock.calls[0]
    expect([project, stage]).toEqual(['/p', '1'])
    expect(text.startsWith('[Studio] ')).toBe(true)
    expect(text).toContain('Requirements')
    expect(text).toContain('/sprd-rules')
    expect(studio.ensureChatStarted).not.toHaveBeenCalled()
  })

  it('focuses the chat input and leaves a typed draft alone', async () => {
    install()
    renderBoth(true)
    const input = (await screen.findByPlaceholderText('Type a message…')) as HTMLTextAreaElement
    fireEvent.change(input, { target: { value: 'half a thought' } })
    fireEvent.click(screen.getByRole('button', { name: 'Talk it through' }))
    await waitFor(() => expect(document.activeElement).toBe(input))
    expect(input.value).toBe('half a thought')
  })

  it('is disabled with a reason when no chat is open', () => {
    install()
    renderBoth(false)
    const talk = screen.getByRole('button', { name: 'Talk it through' })
    expect(talk.hasAttribute('disabled')).toBe(true)
    expect(screen.getByTestId('activity-disabled-reason').textContent).toBe('The chat is not open.')
  })

  it('says so, and sends nothing, while the chat is busy with another turn', async () => {
    let finish: (r: ChatTurnResult) => void = () => {}
    const studio = install()
    studio.sendChatMessage.mockImplementationOnce(() => new Promise<ChatTurnResult>((resolve) => { finish = resolve }))
    renderBoth(true)
    const input = await screen.findByPlaceholderText('Type a message…')
    fireEvent.change(input, { target: { value: 'typed turn' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(studio.sendChatMessage).toHaveBeenCalledTimes(1))

    fireEvent.click(screen.getByRole('button', { name: 'Talk it through' }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/busy/i)
    expect(studio.sendChatMessage).toHaveBeenCalledTimes(1)
    finish({ ok: true, state: emptyState() })
  })
})
