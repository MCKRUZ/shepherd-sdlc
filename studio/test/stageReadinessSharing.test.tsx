// @vitest-environment jsdom
//
// Spec 0019: Frame.tsx owns the ONE `getStageReadiness` fetch for the stage on screen and
// shares it with every descendant that needs it (StageHome as Frame's `children`, the chat
// panel as Frame's own sibling — see studio/src/App.tsx), instead of each one calling it
// independently. These tests render the REAL `Frame` (not a stand-in), with a real `StageHome`
// as its children exactly as `App.tsx` composes them, and a real `ChatPanel` (Frame's own
// direct child) — so a regression that reintroduces a second, parallel fetch anywhere in that
// tree fails here, not just in a unit test of one component in isolation.
//
// ChatPanel.tsx does not yet consume this shared value on this branch — spec 0018's own
// `readinessFlow` call hasn't rebased onto this work yet (see this spec's Decision List) — so
// these tests prove what IS true today: StageHome and the shell share exactly one fetch, and a
// refresh triggered from StageHome goes through the SAME shared `refresh()` rather than a
// second, StageHome-only re-fetch. Once ChatPanel adopts the context, the "exactly one call"
// assertions below continue to hold with no change to this file.
//
// Recorded pin change (togo-command-center.md §1, §8 #1): the sidebar — and with it its own
// "N of M documents complete" line and the second fetch it made for the TRUE current stage while a
// different stage was viewed — retired with the LifecycleStrip (lifecycleStrip.test.tsx). The
// strip reads `status.stages` and the command center, never stage readiness, so the shell now
// makes exactly ONE readiness fetch, for the viewed stage; the assertions that counted the
// sidebar's second call are re-recorded below to the one call that remains.

import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Frame } from '../src/components/Frame'
import { StageHome } from '../src/components/StageHome'
import type { ChatState, ProjectStatus, StageDocument, StageReadiness } from '../shared/types'

function stage(id: string, state: 'current' | 'signed_off' | 'later'): ProjectStatus['stages'][number] {
  return {
    id, name: id, display: `Phase ${id}`, status: state, stage_state: state,
    artifact_count: 0, entered_at: null, completed_at: null, signed_off_by: null,
  }
}

function status(): ProjectStatus {
  return {
    project_name: 'demo',
    profile_id: 'p',
    current_phase: { id: '1', display: 'Phase 1' },
    stages: [stage('0', 'signed_off'), stage('1', 'current'), stage('2', 'later')],
  }
}

function doc(path: string, ready: boolean): StageDocument {
  return { name: path, path, exists: true, folder: false, shaped: true, findingCount: 0, ready }
}

/** Every document ready, so `computeWorkflowSteps` lands the Workflow tab's current step on
 * Sign-off rather than a document — the document step would mount `LiveDocumentPanel`, which
 * polls `window.studio.openDocument` on its own timer, an unrelated fetch this test has no
 * reason to mock or assert about. */
function readinessFor(stageId: string, confirmed = false, documents: StageDocument[] = [doc(`doc-${stageId}.md`, true)]): StageReadiness {
  return {
    ok: true,
    stageId,
    name: `stage-${stageId}`,
    display: `Phase ${stageId}: Stage ${stageId}`,
    isCurrent: stageId === '1',
    documents,
    findings: [],
    judgement: [{
      id: 'q-1',
      text: 'Scope boundaries are unambiguous',
      hint: { status: 'judgement', detail: 'Needs your judgement.' },
      confirmation: confirmed ? { actor: 'Matt K', ts: '2026-10-01T00:00:00Z' } : null,
    }],
    signOff: { status: 'pending', signedOffBy: null, completedAt: null },
    ready: true,
  }
}

function emptyChatState(): ChatState {
  // One message already present so ChatPanel's auto-greet (`ensureChatStarted`) never fires —
  // that call is out of this spec's scope and this suite has no reason to mock or assert it.
  return { sessionId: 's', messages: [{ id: 'm1', role: 'assistant', text: 'hi', questions: [], proposals: [], at: '' }] }
}

/** A minimal, controllable stand-in for window.studio, in the same style ChatPanel.test.tsx
 * already uses: each test wires only the calls it needs. `getStageReadiness` is a `vi.fn` in
 * every test here, since every test's whole point is asserting how many times — and with what
 * arguments — it was actually called. */
function installStudioMock(getStageReadiness: ReturnType<typeof vi.fn>) {
  const studio = {
    getStageReadiness,
    setJudgementConfirmation: vi.fn().mockResolvedValue({ ok: true }),
    getChatState: vi.fn().mockResolvedValue(emptyChatState()),
    ensureChatStarted: vi.fn().mockResolvedValue({ ok: true, state: emptyChatState() }),
    sendChatMessage: vi.fn().mockResolvedValue({ ok: true, state: emptyChatState() }),
    answerChatQuestion: vi.fn().mockResolvedValue({ ok: true, state: emptyChatState() }),
    resolveChatProposal: vi.fn().mockResolvedValue({ ok: true, state: emptyChatState() }),
  }
  // @ts-expect-error - test double, not the full StudioApi surface
  window.studio = studio
  return studio
}

afterEach(() => {
  // @ts-expect-error - cleaning up the test double between tests
  delete window.studio
})

function renderFrame(viewedStageId: string | undefined) {
  return render(
    <Frame
      status={status()}
      projectPath="/p"
      consoleEntries={[]}
      syncState={{ kind: 'idle', lastPulledAt: null }}
      area="documents"
      viewedStageId={viewedStageId}
      actor="Matt K"
      onNavigate={() => {}}
    >
      <StageHome
        projectPath="/p"
        stageId={viewedStageId}
        actor="Matt K"
        setOpening={() => {}}
        onSignedOff={() => {}}
        onOpenDocument={() => {}}
      />
    </Frame>,
  )
}

describe('Frame as the single owner of stage readiness (spec 0019)', () => {
  it('calls getStageReadiness exactly once for the stage, not once per consumer (StageHome + the sidebar doc-count line + the chat panel all mounted together)', async () => {
    const getStageReadiness = vi.fn().mockResolvedValue(readinessFor('1'))
    installStudioMock(getStageReadiness)

    renderFrame(undefined)

    await waitFor(() => expect(screen.getByText('Phase 1: Stage 1')).toBeTruthy())
    // The strip (the sidebar's successor) reads no readiness of its own: still ONE fetch.
    expect(screen.getByRole('navigation', { name: 'Project' })).toBeTruthy()

    expect(getStageReadiness).toHaveBeenCalledTimes(1)
    expect(getStageReadiness).toHaveBeenCalledWith('/p', '1')
  })

  it('confirming a judgement question refreshes through the ONE shared refresh — a single additional call, not one per consumer', async () => {
    const getStageReadiness = vi.fn()
      .mockResolvedValueOnce(readinessFor('1', false))
      .mockResolvedValueOnce(readinessFor('1', true))
    const studio = installStudioMock(getStageReadiness)

    renderFrame(undefined)
    await waitFor(() => expect(screen.getByText('Scope boundaries are unambiguous')).toBeTruthy())
    expect(getStageReadiness).toHaveBeenCalledTimes(1)

    const user = userEvent.setup()
    const confirmCheckbox = screen.getByRole('checkbox')
    await act(async () => { await user.click(confirmCheckbox) })

    await waitFor(() => expect(studio.setJudgementConfirmation).toHaveBeenCalledWith('/p', '1', 'q-1', true, 'Matt K'))
    // Exactly ONE more call — the shared refresh() — not a second, StageHome-only re-fetch
    // alongside it (which is exactly the regression a leftover "just in case" fetch would be).
    await waitFor(() => expect(getStageReadiness).toHaveBeenCalledTimes(2))
    expect(getStageReadiness).toHaveBeenNthCalledWith(2, '/p', '1')
  })

  it('switching the viewed stage re-fetches exactly once for the new stage, and the screen reflects the new stage only — never a stale mix of the old and new', async () => {
    const getStageReadiness = vi.fn().mockImplementation((_projectPath: string, stageId?: string) => (
      Promise.resolve(readinessFor(stageId ?? '1'))
    ))
    installStudioMock(getStageReadiness)

    const { rerender } = renderFrame('0')
    await waitFor(() => expect(screen.getByText('Phase 0: Stage 0')).toBeTruthy())
    // ONE call on first render: the viewed stage ('0', the shared fetch StageHome reads). The
    // sidebar's own current-stage line, which used to make a second call for '1', retired with
    // the sidebar (recorded pin change, header comment).
    await waitFor(() => expect(getStageReadiness).toHaveBeenCalledTimes(1))
    expect(getStageReadiness).toHaveBeenCalledWith('/p', '0')

    rerender(
      <Frame
        status={status()}
        projectPath="/p"
        consoleEntries={[]}
        syncState={{ kind: 'idle', lastPulledAt: null }}
        area="documents"
        viewedStageId="2"
        actor="Matt K"
        onNavigate={() => {}}
      >
        <StageHome
          projectPath="/p"
          stageId="2"
          actor="Matt K"
          setOpening={() => {}}
          onSignedOff={() => {}}
          onOpenDocument={() => {}}
        />
      </Frame>,
    )

    await waitFor(() => expect(screen.getByText('Phase 2: Stage 2')).toBeTruthy())
    expect(screen.queryByText('Phase 0: Stage 0')).toBeNull()
    // Exactly ONE more call, for the newly viewed stage ('2').
    expect(getStageReadiness).toHaveBeenCalledTimes(2)
    expect(getStageReadiness).toHaveBeenNthCalledWith(2, '/p', '2')
  })

  it('viewing a DIFFERENT stage never mislabels it as current: the screen shows the viewed stage\'s own documents and the strip lights the true current station', async () => {
    // Viewing stage '0' (signed off, 1 of 1 docs) while stage '1' is the project's actual
    // current stage (2 of 3 docs). The sidebar's own current-stage count line retired with the
    // sidebar (recorded pin change, header comment); what must still hold is that nothing on
    // screen shows stage 0's count as if it were the current stage's, and that the strip marks
    // the current station ('1') from `status.stages`, not from the viewed stage's readiness.
    const docsByStage: Record<string, StageDocument[]> = {
      '0': [doc('doc-0.md', true)],
      '1': [doc('doc-1a.md', true), doc('doc-1b.md', false), doc('doc-1c.md', true)],
    }
    const getStageReadiness = vi.fn().mockImplementation((_projectPath: string, stageId?: string) => (
      Promise.resolve(readinessFor(stageId ?? '1', false, docsByStage[stageId ?? '1']))
    ))
    installStudioMock(getStageReadiness)

    renderFrame('0')
    await waitFor(() => expect(screen.getByText('Phase 0: Stage 0')).toBeTruthy())

    // ONE fetch, for the viewed stage; nothing asks for stage 1's readiness on stage 0's behalf.
    expect(getStageReadiness).toHaveBeenCalledWith('/p', '0')
    expect(getStageReadiness).toHaveBeenCalledTimes(1)
    expect(getStageReadiness).not.toHaveBeenCalledWith('/p', '1')

    // Stage 0's count is never labelled as the current stage's, and no placeholder stands in.
    expect(screen.queryByText('2 of 3 documents complete')).toBeNull()
    expect(screen.queryByText('In progress')).toBeNull()
    const nav = screen.getByRole('navigation', { name: 'Project' })
    expect(nav.querySelector('[data-station="current"]')?.closest('li')?.getAttribute('data-stage-id')).toBe('1')
    expect(nav.querySelector('[data-viewing]')?.closest('li')?.getAttribute('data-stage-id')).toBe('0')
  })
})
