// @vitest-environment jsdom
/** F11 (studio-observatory §7 WorkflowTab row): an activity picked from "Also in this stage"
 * opens in the Workflow tab's MAIN slot, framed by `FocusedActivityHost`, while the left column
 * keeps only the step list and the activities list.
 *
 * ActivitiesPanel has no selection callback of its own yet (another package owns it), so the
 * hand-off is `FocusedActivityContext`: here a stand-in ActivitiesPanel reads it the way the
 * real one will, which pins the contract from this side — the host, the slot it fills, the way
 * back — without depending on that package's timing. The standalone cases need no context. */
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { StageActivity, StageDocument } from '../shared/types'
import { FocusedActivityHost, FOCUSED_ACTIVITY_BACK } from '../src/components/FocusedActivityHost'
import { WorkflowTab } from '../src/components/WorkflowTab'
import { activity, readinessWith } from './activityFixtures'

vi.mock('../src/components/ActivitiesPanel', async () => {
  const { useFocusedActivity } = await import('../src/components/FocusedActivityHost')
  const { activity: make } = await import('./activityFixtures')
  const sprint = make({ id: 'sprint', kind: 'run', label: 'Sprint', command: 'sprd-sprint' })
  function ActivitiesPanel() {
    const host = useFocusedActivity()
    return (
      <section data-testid="activities-panel">
        <h3>Also in this stage</h3>
        <button type="button" onClick={() => host?.focus(sprint, <div data-testid="sprint-panel">The sprint panel</div>)}>
          Open sprint
        </button>
        <span data-testid="focused-id">{host?.focusedId ?? 'none'}</span>
      </section>
    )
  }
  return { ActivitiesPanel }
})

const SPRINT: StageActivity = activity({ id: 'sprint', kind: 'run', label: 'Sprint', command: 'sprd-sprint' })

function doc(path: string, ready: boolean): StageDocument {
  return { name: path, path, exists: true, folder: false, shaped: true, findingCount: 0, ready } as StageDocument
}

afterEach(() => {
  cleanup()
  // @ts-expect-error - cleaning up the test double
  delete window.studio
})

describe('FocusedActivityHost on its own', () => {
  it('names the activity and its command, frames the panel, and offers the way back', () => {
    const onClose = vi.fn()
    render(
      <FocusedActivityHost activity={SPRINT} onClose={onClose}>
        <p>The panel body</p>
      </FocusedActivityHost>,
    )
    const host = screen.getByTestId('focused-activity-host')
    expect(host.getAttribute('data-activity-id')).toBe('sprint')
    expect(screen.getByRole('heading', { level: 3 }).textContent).toBe('Sprint /sprd-sprint')
    expect(within(host).getByText('The panel body')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: FOCUSED_ACTIVITY_BACK }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('moves focus to its heading so a keyboard user lands on what just opened', () => {
    render(<FocusedActivityHost activity={SPRINT} onClose={() => {}}>x</FocusedActivityHost>)
    expect(document.activeElement).toBe(screen.getByRole('heading', { level: 3 }))
  })

  it('leaves out the command when the plugin declared none', () => {
    render(<FocusedActivityHost activity={activity({ id: 'brief', label: 'Brief' })} onClose={() => {}}>x</FocusedActivityHost>)
    expect(screen.getByRole('heading', { level: 3 }).textContent).toBe('Brief')
  })
})

describe('WorkflowTab hosts the picked activity in the main slot', () => {
  function mount(stageId = '1') {
    // @ts-expect-error - test double, not the full StudioApi surface
    window.studio = { openDocument: vi.fn().mockReturnValue(new Promise(() => {})) }
    const readiness = readinessWith({
      stageId, display: `Phase ${stageId}`, documents: [doc('a.md', false), doc('b.md', false)], activities: [SPRINT],
    })
    return render(
      <WorkflowTab
        projectPath="/p" readiness={readiness} actor="matt" busyId={null} confirmError={null}
        onToggleSignOff={() => {}} onOpenDocument={() => {}}
      />,
    )
  }

  it('replaces the live document panel with the host, keeps the step list and the activities list on the left, and comes back', () => {
    const { container } = mount()
    expect(screen.getByText('Opening…')).toBeTruthy()
    expect(screen.getByTestId('focused-id').textContent).toBe('none')

    fireEvent.click(screen.getByRole('button', { name: 'Open sprint' }))

    const host = screen.getByTestId('focused-activity-host')
    expect(screen.getByTestId('sprint-panel')).toBeTruthy()
    expect(screen.queryByText('Opening…')).toBeNull()
    expect(screen.getByTestId('focused-id').textContent).toBe('sprint')

    // The host lives in the right (main) slot, never inside the `sm:w-72` column, which still
    // holds the <ol> of steps and the activities list — the layout string stays pinned.
    const root = container.firstElementChild as HTMLElement
    expect(root.className).toBe('flex flex-col gap-6 sm:flex-row')
    const left = root.firstElementChild as HTMLElement
    expect(left.className).toContain('sm:w-72')
    expect(left.contains(host)).toBe(false)
    expect(left.querySelector('ol')).toBeTruthy()
    expect(left.contains(screen.getByTestId('activities-panel'))).toBe(true)
    expect(screen.getAllByTestId('workflow-step')).toHaveLength(3)

    fireEvent.click(screen.getByRole('button', { name: FOCUSED_ACTIVITY_BACK }))
    expect(screen.queryByTestId('focused-activity-host')).toBeNull()
    expect(screen.getByText('Opening…')).toBeTruthy()
    expect(screen.getByTestId('focused-id').textContent).toBe('none')
  })

  it('drops the hosted activity when the stage changes underneath it', () => {
    const { rerender } = mount('1')
    fireEvent.click(screen.getByRole('button', { name: 'Open sprint' }))
    expect(screen.getByTestId('focused-activity-host')).toBeTruthy()

    const other = readinessWith({ stageId: '2', display: 'Phase 2', documents: [doc('c.md', false)], activities: [SPRINT] })
    rerender(
      <WorkflowTab
        projectPath="/p" readiness={other} actor="matt" busyId={null} confirmError={null}
        onToggleSignOff={() => {}} onOpenDocument={() => {}}
      />,
    )
    expect(screen.queryByTestId('focused-activity-host')).toBeNull()
    expect(screen.getByText('Opening…')).toBeTruthy()
  })
})
