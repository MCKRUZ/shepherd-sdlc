// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ActivitiesPanel } from '../src/components/ActivitiesPanel'
import type { StageActivity, StageReadiness } from '../shared/types'
import { activity, readinessWith } from './activityFixtures'

const ALL_CAPABILITIES = ['activities', 'phase-report-json', 'intake-modes', 'narrative-status', 'sprint-status']

const PANELS: Array<{ id: string; kind: StageActivity['kind']; testid: string; capability: string }> = [
  { id: 'phase-report', kind: 'run', testid: 'phase-report-panel', capability: 'phase-report-json' },
  { id: 'intake', kind: 'run', testid: 'intake-panel', capability: 'intake-modes' },
  { id: 'enhance', kind: 'draft', testid: 'narrative-panel', capability: 'narrative-status' },
  { id: 'review', kind: 'draft', testid: 'review-standing-panel', capability: 'activities' },
  { id: 'sprint', kind: 'run', testid: 'sprint-panel', capability: 'sprint-status' },
]

function install() {
  const studio = {
    getNarrativeCoverage: vi.fn().mockResolvedValue({ ok: true, hasData: false, notes: [], withNarrative: 0, total: 0, artifacts: [] }),
    getReviewStanding: vi.fn().mockResolvedValue({ ok: true, tracked: 0, openDebt: 0, fixedClaimMismatches: 0 }),
    getSprintStatus: vi.fn().mockResolvedValue({
      ok: true, sprint: null, slate: [], readiness: { ready: 0, total: 0, gaps: [] }, verdictsPending: [], handoffsOpen: [], mix: {},
      mixWarnings: [], wip: { inFlight: 0, cap: null }, buildOrder: [], nextUp: null, dependencyGaps: [], decisions: null, carriedIn: [],
      hasData: false, note: null,
    }),
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

function draw(activities: StageActivity[], over: Partial<StageReadiness> = {}) {
  install()
  const readiness = readinessWith({ capabilities: ALL_CAPABILITIES, activities, ...over })
  render(<ActivitiesPanel projectPath="/p" readiness={readiness} onOpenDocument={vi.fn()} />)
}

const row = (id: string) => document.querySelector(`[data-activity-id="${id}"]`) as HTMLElement

describe('ActivitiesPanel: the panel activities', () => {
  it('draws a row for each, in declared order, each with its own panel', () => {
    draw(PANELS.map((p) => activity({ id: p.id, kind: p.kind, label: p.id })))
    expect(screen.getAllByTestId('activity-row').map((r) => r.getAttribute('data-activity-id')))
      .toEqual(['phase-report', 'intake', 'enhance', 'review', 'sprint'])
    for (const p of PANELS) expect(within(row(p.id)).getByTestId(p.testid)).toBeTruthy()
  })

  it('shows the panel instead of the kind\'s generic control', () => {
    draw([activity({ id: 'intake', kind: 'create', label: 'Intake' })])
    expect(within(row('intake')).queryByRole('button', { name: 'Create' })).toBeNull()
    expect(within(row('intake')).getByTestId('intake-panel')).toBeTruthy()
  })

  it.each(PANELS)('shows $id\'s blocked reason verbatim and no panel', ({ id, kind, testid }) => {
    const reason = 'Needs the requirements to be started first.'
    draw([activity({ id, kind, status: 'blocked', reason })])
    expect(within(row(id)).getByText(reason)).toBeTruthy()
    expect(screen.queryByTestId(testid)).toBeNull()
  })

  it.each(PANELS)('keeps $id\'s panel for a done activity and labels it Done', ({ id, kind, testid }) => {
    draw([activity({ id, kind, status: 'done' })])
    expect(within(row(id)).getByText('Done')).toBeTruthy()
    expect(within(row(id)).getByTestId(testid)).toBeTruthy()
  })

  it.each(PANELS)('offers no $id panel when the plugin lacks $capability, and says why', ({ id, kind, testid, capability }) => {
    draw([activity({ id, kind })], { capabilities: ALL_CAPABILITIES.filter((c) => c !== capability) })
    expect(screen.queryByTestId(testid)).toBeNull()
    expect(within(row(id)).getByTestId('activity-disabled-reason').textContent).toBe(`needs a newer plugin: lacks ${capability}`)
  })

  it('routes the Build stage\'s sprint activity to the compact sprint panel, which reads the sprint once', async () => {
    const studio = install()
    const readiness = readinessWith({
      stageId: 'build', display: 'Phase Build: Build Loop', capabilities: ALL_CAPABILITIES,
      activities: [activity({ id: 'sprint', kind: 'run', label: 'Plan, ready and close the sprint', command: 'sprd-sprint' })],
    })
    render(<ActivitiesPanel projectPath="/p" readiness={readiness} onOpenDocument={vi.fn()} />)
    expect(within(row('sprint')).getByTestId('sprint-panel')).toBeTruthy()
    expect(await within(row('sprint')).findByTestId('sprint-empty')).toBeTruthy()
    expect(studio.getSprintStatus).toHaveBeenCalledWith('/p', undefined)
    // The panel is read-only; the row offers none of the generic controls.
    expect(within(row('sprint')).queryByRole('button', { name: 'Create' })).toBeNull()
    expect(within(row('sprint')).queryByRole('button', { name: 'Talk it through' })).toBeNull()
  })

  it('does not call the plugin for a blocked or unsupported read-only panel', () => {
    const studio = install()
    const readiness = readinessWith({
      capabilities: ['activities'],
      activities: [
        activity({ id: 'enhance', kind: 'draft' }), activity({ id: 'review', kind: 'draft', status: 'blocked', reason: 'Not yet.' }),
        activity({ id: 'sprint', kind: 'run' }),
      ],
    })
    render(<ActivitiesPanel projectPath="/p" readiness={readiness} onOpenDocument={vi.fn()} />)
    expect(studio.getNarrativeCoverage).not.toHaveBeenCalled()
    expect(studio.getReviewStanding).not.toHaveBeenCalled()
    expect(studio.getSprintStatus).not.toHaveBeenCalled()
  })
})
