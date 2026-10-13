/** The Sprint view's pure helpers: how the plugin's sprint document is worded on screen. The rule
 * under test throughout is the sprint layer's own — "no data" is never a zero, and nothing totals
 * work per person. */

import { describe, expect, it } from 'vitest'
import {
  businessDays, decisionsLabel, emptyMessage, isSprintId, laneBadge, mixChips, nextUpLabel, readinessLabel,
  remainingLabel, slateToBoardRow, SPRINT_CAPABILITY, stateChip, targetLabel, wipLabel, sprintStateChip, riskTone, dorChipTone,
} from '../shared/sprintModel'
import type { SprintRecord, SprintSlateRow, SprintView } from '../shared/types'

const sprint = (over: Partial<SprintRecord> = {}): SprintRecord => ({
  id: 'S07', goal: 'Claims adjusters file without a phone call', start: '2026-09-28', end: '2026-10-09', state: 'planning',
  target: 4, mix: 'HIGH:1,MEDIUM:2,LOW:1', boardRef: '', readiedBy: '', closedBy: '', created: '2026-09-25',
  path: '/p/.sdlc/sprints/S07.md', relPath: '.sdlc/sprints/S07.md', days: { total: 10, elapsed: 3, remaining: 7 }, ...over,
})

const row = (over: Partial<SprintSlateRow> = {}): SprintSlateRow => ({
  id: '0007', name: 'duplicate-claim-409', risk: 'HIGH', type: 'feature', channel: '', status: 'ready', sprint: 'S07',
  nextOwner: '', engReview: 'accepted', dataReview: 'n-a', dependsOn: [], dor: 'READY', dorBlocking: [],
  path: '/p/specs/0007-duplicate-claim-409.md', relPath: 'specs/0007-duplicate-claim-409.md', ...over,
})

const view = (over: Partial<SprintView> = {}): SprintView => ({
  ok: true, sprint: sprint(), slate: [row()], readiness: { ready: 1, total: 1, gaps: [] }, verdictsPending: [], handoffsOpen: [],
  mix: { HIGH: { target: 1, actual: 1 } }, mixWarnings: [], wip: { inFlight: 2, cap: 4 }, buildOrder: ['0007'], nextUp: '0007',
  dependencyGaps: [], decisions: null, carriedIn: [], hasData: true, note: null, ...over,
})

describe('sprint ids', () => {
  it('accepts the plugin\'s own shape and nothing else', () => {
    for (const ok of ['S07', 'S12', 'S123']) expect(isSprintId(ok)).toBe(true)
    for (const bad of ['S7', 's07', 'S07 --json', '../S07', '', 7, null, undefined]) expect(isSprintId(bad)).toBe(false)
  })

  it('names the capability the view needs', () => {
    expect(SPRINT_CAPABILITY).toBe('sprint-status')
  })
})

describe('no data is never a zero', () => {
  it('ages a verdict only when the plugin could', () => {
    expect(businessDays(null)).toBe('no data')
    // A 0 the plugin DID report is "today" — not an absence, and not a count that reads like one.
    expect(businessDays(0)).toBe('today')
    expect(businessDays(1)).toBe('1 business day')
    expect(businessDays(3)).toBe('3 business days')
  })

  it('WIP reads the cap as "not set" and the count as "no data" when unknown', () => {
    expect(wipLabel({ inFlight: 2, cap: 4 })).toBe('2 in flight · cap 4')
    expect(wipLabel({ inFlight: 2, cap: null })).toBe('2 in flight · cap not set')
    expect(wipLabel({ inFlight: null, cap: 4 })).toBe('no data')
  })

  it('readiness is "no data" for an empty slate, never "0 of 0 ready"', () => {
    expect(readinessLabel(view())).toBe('1 of 1 ready')
    expect(readinessLabel(view({ hasData: false, slate: [], readiness: { ready: 0, total: 0, gaps: [] } }))).toBe('no data')
  })

  it('a target the record does not state is "no data"', () => {
    expect(targetLabel(4)).toBe('4 specs')
    expect(targetLabel(1)).toBe('1 spec')
    expect(targetLabel(null)).toBe('no data')
  })

  it('a tier the mix did not name reads "no target", not 0', () => {
    expect(mixChips({ LOW: { target: null, actual: 2 }, HIGH: { target: 1, actual: 1 }, MEDIUM: { target: 2, actual: 0 } }).map((c) => c.label))
      .toEqual(['HIGH 1/1', 'MEDIUM 0/2', 'LOW 2/no target'])
    expect(mixChips({})).toEqual([])
  })

  it('decisions say "no decision-log" when there is none', () => {
    expect(decisionsLabel(null)).toBe('no data — no decision-log')
    expect(decisionsLabel({ open: 3, overdue: [] })).toBe('3 open')
    expect(decisionsLabel({ open: 3, overdue: [{ id: 'D-2', decision: 'x', owner: '', due: '' }] })).toBe('3 open · 1 overdue')
  })

  it('next up words its absence differently for an empty slate and a blocked one', () => {
    expect(nextUpLabel(view())).toBe('0007 — READY, dependencies merged, WIP 2 of 4')
    expect(nextUpLabel(view({ wip: { inFlight: 2, cap: null } }))).toBe('0007 — READY, dependencies merged')
    expect(nextUpLabel(view({ nextUp: null }))).toBe('no slated spec is READY with merged dependencies inside the WIP cap')
    expect(nextUpLabel(view({ nextUp: null, hasData: false, slate: [] }))).toBe('no data')
  })
})

describe('the header', () => {
  it('says how long is left, or who closed it, or nothing it cannot know', () => {
    expect(remainingLabel(sprint())).toBe('7 business days remaining')
    expect(remainingLabel(sprint({ days: { total: 10, elapsed: 9, remaining: 1 } }))).toBe('1 business day remaining')
    expect(remainingLabel(sprint({ days: { total: null, elapsed: null, remaining: null } }))).toBeNull()
    expect(remainingLabel(sprint({ state: 'closed', closedBy: 'Priya N.' }))).toBe('closed by Priya N.')
    expect(remainingLabel(sprint({ state: 'closed' }))).toBe('closed')
  })

  it('shows the three states as chips and anything else as it is', () => {
    expect(stateChip('planning')).toEqual({ label: 'planning', tone: 'attention' })
    expect(stateChip('ready')).toEqual({ label: 'ready', tone: 'good' })
    expect(stateChip('closed')).toEqual({ label: 'closed', tone: 'muted' })
    expect(stateChip('paused')).toEqual({ label: 'paused', tone: 'neutral' })
    expect(stateChip('')).toEqual({ label: 'unknown', tone: 'neutral' })
  })
})

describe('lane badges', () => {
  it('shows the plugin\'s verdict and calls an empty one "not recorded" rather than inventing one', () => {
    expect(laneBadge('accepted')).toEqual({ label: 'accepted', tone: 'good' })
    expect(laneBadge('returned')).toEqual({ label: 'returned', tone: 'attention' })
    expect(laneBadge('n-a')).toEqual({ label: 'n/a', tone: 'muted' })
    expect(laneBadge('pending')).toEqual({ label: 'pending', tone: 'neutral' })
    expect(laneBadge('')).toEqual({ label: 'not recorded', tone: 'neutral' })
  })
})

describe('what to say instead of a slate', () => {
  it('no sprint at all points at /sprd-sprint new, in the plugin\'s words when it gave any', () => {
    expect(emptyMessage(view({ sprint: null, slate: [], hasData: false }))).toBe('No sprint — open one with /sprd-sprint new.')
    expect(emptyMessage(view({ sprint: null, slate: [], hasData: false, note: "'S7' is not a sprint id" }))).toBe("'S7' is not a sprint id")
  })

  it('an open sprint with nothing slated points at /sprd-sprint slate; a closed one at its review page', () => {
    expect(emptyMessage(view({ slate: [], hasData: false }))).toBe('Nothing slated yet — propose a slate with /sprd-sprint slate.')
    expect(emptyMessage(view({ slate: [], hasData: false, sprint: sprint({ state: 'closed' }) })))
      .toBe('Closed; see .sdlc/reports/sprint-S07-review.html. Start the next sprint with /sprd-sprint new.')
  })

  it('says nothing when there is a slate', () => {
    expect(emptyMessage(view())).toBeNull()
  })
})

describe('opening a slate row in the spec view', () => {
  it('uses the repo-relative path and claims nothing about people the slate does not carry', () => {
    const r = slateToBoardRow(row({ nextOwner: '@sam-k' }))
    expect(r.path).toBe('specs/0007-duplicate-claim-409.md')
    expect(r.spec).toBe('0007')
    expect(r.name).toBe('duplicate-claim-409')
    expect(r.status).toBe('ready')
    expect(r.risk).toBe('HIGH')
    expect(r.owner).toBe('')
    expect(r.developer).toBe('')
    expect(r.checker).toBe('')
    expect(r.pullRequest).toBeNull()
    // The sprint fields the slate DOES carry travel with the row, so the board's own "waiting
    // on me" and sprint chip answer the same from either screen.
    expect(r.sprint).toBe('S07')
    expect(r.nextOwner).toBe('@sam-k')
    expect(r.engReview).toBe('accepted')
    expect(r.dataReview).toBe('n-a')
    expect(r.dependsOn).toEqual([])
  })
})

describe('counts only', () => {
  it('exports no helper that totals work by person', async () => {
    const mod = await import('../shared/sprintModel')
    const names = Object.keys(mod)
    expect(names.filter((n) => /perPerson|byOwner|byPerson|velocity|points|estimate/i.test(n))).toEqual([])
  })
})

describe('the command center\'s one chip per fact (fixer round)', () => {
  it('sprintStateChip: planning is neutral with a dot, ready is "now", closed is neutral and muted — never amber, never green', () => {
    expect(sprintStateChip('planning')).toEqual({ label: 'planning', tone: 'neutral', dot: true, muted: false })
    expect(sprintStateChip('ready')).toEqual({ label: 'ready', tone: 'current', dot: true, muted: false })
    expect(sprintStateChip('closed')).toEqual({ label: 'closed', tone: 'neutral', dot: false, muted: true })
    expect(sprintStateChip('paused')).toEqual({ label: 'paused', tone: 'neutral', dot: false, muted: false })
    expect(sprintStateChip('')).toEqual({ label: 'unknown', tone: 'neutral', dot: false, muted: false })
  })

  it('riskTone is the one risk map: HIGH error, MEDIUM warn, anything else neutral', () => {
    expect(riskTone('HIGH')).toBe('error')
    expect(riskTone(' medium ')).toBe('warn')
    expect(riskTone('LOW')).toBe('neutral')
    expect(riskTone('')).toBe('neutral')
  })

  it('dorChipTone: READY is the current tone (a verdict, not a host success), NOT READY warn, else neutral', () => {
    expect(dorChipTone('READY')).toBe('current')
    expect(dorChipTone('NOT READY')).toBe('warn')
    expect(dorChipTone(null)).toBe('neutral')
    expect(dorChipTone('unknown')).toBe('neutral')
  })
})
