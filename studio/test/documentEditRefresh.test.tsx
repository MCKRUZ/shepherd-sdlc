// @vitest-environment jsdom
//
// CI's correctness-review gate (spec 0019, PR #77): shared stage readiness
// (StageReadinessContext.tsx) does not re-fetch when StageHome remounts after a document edit,
// so the stage home and the sidebar's doc-count line go stale. This is not a regression spec
// 0019 introduced — the identical gap already existed in `StageHome.tsx`'s own pre-0019
// `useCurrentStageDocs` effect (keyed only on `[projectPath, stageId]`, never re-fired on
// returning from editing a document) — but it is real, and it now lives in the shared context
// this spec owns, so it is closed here.
//
// This renders the REAL `Frame` → `StageReadinessProvider` → (`DocumentView` | `StageHome`)
// tree exactly as `App.tsx`'s `AppScreens` composes it (`openDoc` picks which of the two is
// Frame's `children`), saves a field through `DocumentView`'s own "Save field" button, clicks
// its real "← Back to the stage" button, and asserts the stage home's own documents fact (the
// summary strip's "N of M complete") reflects the NEW readiness — proving the fix fires at the
// real save/back flow's own moment, not merely that `refresh()` exists and works when called
// directly. (Recorded pin change, togo-command-center.md §8 #1: the sidebar and its doc-count
// line retired with the LifecycleStrip; the summary strip is where the same fact lives now.)

import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Frame } from '../src/components/Frame'
import { StageHome } from '../src/components/StageHome'
import { DocumentView } from '../src/components/DocumentView'
import type { ChatState, OpenDocumentResult, ProjectStatus, StageDocument, StageReadiness } from '../shared/types'

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

function readinessFor(documents: StageDocument[]): StageReadiness {
  return {
    ok: true,
    stageId: '1',
    name: 'stage-1',
    display: 'Phase 1: Stage 1',
    isCurrent: true,
    documents,
    findings: [],
    judgement: [],
    signOff: { status: 'pending', signedOffBy: null, completedAt: null },
    ready: documents.every((d) => d.ready),
  }
}

function openDocResult(summaryValue: string): OpenDocumentResult {
  return {
    ok: true,
    path: 'doc-1a.md',
    shaped: true,
    warnings: [],
    sections: [{
      kind: 'section',
      key: 'overview',
      heading: 'Overview',
      start: 0,
      end: 0,
      text: '',
      fields: {
        Summary: {
          label: 'Summary', value: summaryValue, start: 0, end: 0,
          type: 'text', required: false, anchor: 'labeled_value', empty: false,
        },
      },
    }],
  }
}

function emptyChatState(): ChatState {
  return { sessionId: 's', messages: [{ id: 'm1', role: 'assistant', text: 'hi', questions: [], proposals: [], at: '' }] }
}

function installStudioMock(opts: { getStageReadiness: ReturnType<typeof vi.fn>; setField: ReturnType<typeof vi.fn> }) {
  const studio = {
    getStageReadiness: opts.getStageReadiness,
    setJudgementConfirmation: vi.fn().mockResolvedValue({ ok: true }),
    getChatState: vi.fn().mockResolvedValue(emptyChatState()),
    ensureChatStarted: vi.fn().mockResolvedValue({ ok: true, state: emptyChatState() }),
    sendChatMessage: vi.fn().mockResolvedValue({ ok: true, state: emptyChatState() }),
    answerChatQuestion: vi.fn().mockResolvedValue({ ok: true, state: emptyChatState() }),
    resolveChatProposal: vi.fn().mockResolvedValue({ ok: true, state: emptyChatState() }),
    openDocument: vi.fn().mockResolvedValue(openDocResult('old value')),
    getDocumentChanges: vi.fn().mockResolvedValue([]),
    markDocumentSeen: vi.fn().mockResolvedValue(undefined),
    setField: opts.setField,
  }
  // @ts-expect-error - test double, not the full StudioApi surface
  window.studio = studio
  return studio
}

afterEach(() => {
  // @ts-expect-error - cleaning up the test double between tests
  delete window.studio
})

/** Mirrors `App.tsx`'s `AppScreens`: `openDoc` picks whether `Frame`'s `children` is
 * `DocumentView` or `StageHome`, both inside the same `Frame` (and so the same
 * `StageReadinessProvider`) exactly as the real app wires it. A plain test-local "Open doc"
 * button drives `openDoc` — StageHome's own document-list click path is exercised elsewhere;
 * what this test is proving is what happens AFTER a document is open and the person returns. */
function Harness() {
  const [openDoc, setOpenDoc] = useState<string | null>(null)
  return (
    <Frame
      status={status()}
      projectPath="/p"
      consoleEntries={[]}
      syncState={{ kind: 'idle', lastPulledAt: null }}
      area="documents"
      viewedStageId={undefined}
      actor="Matt K"
      onNavigate={() => {}}
    >
      {openDoc ? (
        <DocumentView
          key={openDoc}
          projectPath="/p"
          relPath={openDoc}
          actor="Matt K"
          onBack={() => setOpenDoc(null)}
          onShowHistory={() => {}}
        />
      ) : (
        <>
          <button type="button" onClick={() => setOpenDoc('doc-1a.md')}>Open doc</button>
          <StageHome
            projectPath="/p"
            stageId={undefined}
            actor="Matt K"
            setOpening={() => {}}
            onSignedOff={() => {}}
            onOpenDocument={() => {}}
          />
        </>
      )}
    </Frame>
  )
}

describe('shared stage readiness refreshes after a document edit (PR #77 correctness-review finding)', () => {
  it('shows the stage home and sidebar doc count AFTER editing and returning, not the stale pre-edit count', async () => {
    const getStageReadiness = vi.fn()
      // Before the edit: one of two documents ready.
      .mockResolvedValueOnce(readinessFor([doc('doc-1a.md', false), doc('doc-1b.md', true)]))
      // After the edit: both ready — what a refresh fired at the right moment must pick up.
      .mockResolvedValue(readinessFor([doc('doc-1a.md', true), doc('doc-1b.md', true)]))
    const setField = vi.fn().mockResolvedValue(openDocResult('new value'))
    installStudioMock({ getStageReadiness, setField })

    render(<Harness />)

    await waitFor(() => expect(screen.getByText('1 of 2 complete')).toBeTruthy())
    expect(getStageReadiness).toHaveBeenCalledTimes(1)

    const user = userEvent.setup()
    await act(async () => { await user.click(screen.getByText('Open doc')) })
    await waitFor(() => expect(screen.getByRole('heading', { name: 'doc-1a.md' })).toBeTruthy())

    // Enter edit mode and change the field.
    await act(async () => { await user.click(screen.getByText('Edit')) })
    const field = screen.getByDisplayValue('old value')
    await act(async () => { await user.clear(field); await user.type(field, 'new value') })

    // Save it through the real "Save field" button.
    await act(async () => { await user.click(screen.getByText('Save field')) })
    await waitFor(() => expect(setField).toHaveBeenCalledWith('/p', 'doc-1a.md', 'overview', 'Summary', 'new value'))

    // Navigate back through the real "← Back to the stage" button, exactly as a person would.
    await act(async () => { await user.click(screen.getByText('← Back to the stage')) })

    // The stage home / sidebar must now reflect the EDIT, not the pre-edit snapshot still held
    // by the shared context from before DocumentView was ever opened.
    await waitFor(() => expect(screen.getByText('2 of 2 complete')).toBeTruthy())
    expect(screen.queryByText('1 of 2 complete')).toBeNull()
    expect(getStageReadiness).toHaveBeenCalledTimes(2)
  })
})
