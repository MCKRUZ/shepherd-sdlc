// @vitest-environment jsdom
/** The honest empty step panel (studio-upgrade-2 S4): the pinned sentence stays; the template
 * description and "How it gets created" are drawn from the plugin's own rows; the Start control
 * appears only for an `available` create activity that names this document; a blocked one shows
 * its reason and no button; "Up next" lists what follows. */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { documentNotFoundError } from '../shared/documentErrors'
import type { StageDocument, StageReadiness } from '../shared/types'
import { WorkflowTab, activitiesCreating } from '../src/components/WorkflowTab'
import { activity, readinessWith } from './activityFixtures'

const SENTENCE = 'Not started yet — this will appear here as soon as it is created.'

function doc(path: string, over: Partial<StageDocument> = {}): StageDocument {
  return { name: path.split('/').pop() ?? path, path, exists: false, folder: false, shaped: true, findingCount: 0, ready: false, ...over }
}

const BRIEF = '.sdlc/artifacts/00-discovery/workshop-brief.md'
const CREATE = activity({ id: 'brief-doc', kind: 'create', label: 'Workshop brief', command: 'sprd-brief', creates: [BRIEF] })

function readiness(over: Partial<StageReadiness> = {}): StageReadiness {
  return readinessWith({
    stageId: '0', name: 'discovery', display: 'Phase 0: Discovery', capabilities: ['activities'],
    documents: [doc(BRIEF, { description: 'The one-page brief for the workshop.' }), doc('next.md'), doc('later.md')],
    activities: [CREATE],
    ...over,
  })
}

function install() {
  const studio = {
    openDocument: vi.fn((_p: string, relPath: string) => Promise.resolve({ ok: false, path: relPath, shaped: false, warnings: [], sections: [], error: documentNotFoundError(relPath) })),
    startActivity: vi.fn().mockResolvedValue({ ok: true, created: [BRIEF], existing: [], opened: BRIEF }),
  }
  // @ts-expect-error - test double, not the full StudioApi surface
  window.studio = studio
  return studio
}

afterEach(() => {
  // @ts-expect-error - cleaning up the test double
  delete window.studio
})

function mount(r: StageReadiness) {
  const onOpenDocument = vi.fn()
  const onRefresh = vi.fn().mockResolvedValue(undefined)
  render(<WorkflowTab projectPath="/p" readiness={r} actor="Matt K" busyId={null} confirmError={null} onToggleSignOff={vi.fn()} onOpenDocument={onOpenDocument} onRefresh={onRefresh} />)
  return { onOpenDocument, onRefresh }
}

describe('the empty step panel', () => {
  it('keeps the sentence, adds the description, lists how it gets created, and offers Start only for an available match', async () => {
    const studio = install()
    const { onOpenDocument, onRefresh } = mount(readiness())
    const panel = await screen.findByTestId('empty-step-panel')
    expect(within(panel).getByText(SENTENCE)).toBeTruthy()
    expect(within(panel).getByText('The one-page brief for the workshop.')).toBeTruthy()
    const creator = within(panel).getByTestId('empty-step-creator')
    expect(creator.textContent).toContain('Workshop brief')
    expect(creator.textContent).toContain('/sprd-brief')
    expect(within(panel).getByText(/Ask in Chat/)).toBeTruthy()
    expect(within(panel).getByRole('heading', { name: 'Up next' })).toBeTruthy()
    expect(within(panel).getByText('next.md')).toBeTruthy()
    expect(within(panel).getByText('Sign-off')).toBeTruthy()

    fireEvent.click(within(panel).getByRole('button', { name: 'Start from template' }))
    await waitFor(() => expect(studio.startActivity).toHaveBeenCalledWith('/p', '0', 'brief-doc'))
    await waitFor(() => expect(onOpenDocument).toHaveBeenCalledWith(BRIEF))
    expect(onRefresh).toHaveBeenCalled()
  })

  it('a blocked activity shows the plugin\'s reason and no button', async () => {
    install()
    mount(readiness({ activities: [{ ...CREATE, status: 'blocked', reason: 'Run the intake first.' }] }))
    const panel = await screen.findByTestId('empty-step-panel')
    expect(within(panel).getByTestId('empty-step-reason').textContent).toContain('Run the intake first.')
    expect(within(panel).queryByRole('button', { name: 'Start from template' })).toBeNull()
  })

  it('no matching activity, or an older plugin — the sentence and no button', async () => {
    install()
    mount(readiness({ activities: undefined, capabilities: undefined }))
    const panel = await screen.findByTestId('empty-step-panel')
    expect(within(panel).getByText(SENTENCE)).toBeTruthy()
    expect(within(panel).queryByTestId('empty-step-creator')).toBeNull()
    expect(within(panel).queryByRole('button', { name: 'Start from template' })).toBeNull()
  })

  it('a done activity is listed as already run, with no button', async () => {
    install()
    mount(readiness({ activities: [{ ...CREATE, status: 'done' }] }))
    const panel = await screen.findByTestId('empty-step-panel')
    expect(within(panel).getByTestId('empty-step-creator').textContent).toContain('already run')
    expect(within(panel).queryByRole('button', { name: 'Start from template' })).toBeNull()
  })

  it('activitiesCreating matches the exact path, or the bare name only when the document path has no folder', () => {
    const r = readiness()
    expect(activitiesCreating(r, doc(BRIEF)).map((a) => a.activity.id)).toEqual(['brief-doc'])
    expect(activitiesCreating(r, doc('workshop-brief.md')).map((a) => a.activity.id)).toEqual(['brief-doc'])
    expect(activitiesCreating(r, doc('.sdlc/artifacts/01-requirements/workshop-brief.md'))).toEqual([])
    expect(activitiesCreating(r, doc('other.md'))).toEqual([])
  })
})
