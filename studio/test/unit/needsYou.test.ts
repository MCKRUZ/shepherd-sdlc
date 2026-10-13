/** `needsYou` (togo-command-center.md §2.3): exact handle match only; no identity → empty with the
 * reason; verdicts are never personal; overdue decisions first; confirm-tier only when the
 * plugin has the verb AND the row carries an empty `risk_confirmed_by`. */
import { describe, expect, it } from 'vitest'
import { needsYou, type NeedsYouInput } from '../../electron/main/commandCenter'
import { NO_ACTOR } from '../../shared/reasons'
import type { BoardRow, DecisionsView, SourcedBlock } from '../../shared/types'

const block = <T>(source: string, data: T | null): SourcedBlock<T> => ({ source, fetchedAt: 't', ok: data !== null, data, error: data === null ? 'no' : null })

const row = (over: Partial<BoardRow>): BoardRow => ({
  spec: '0001', name: 'a', path: 'specs/0001-a.md', title: '', status: 'in-flight', risk: 'HIGH', team: 'core', channel: '', owner: '@matt',
  developer: '@sam-k', checker: '@priya-n', branch: '', sprint: 'S08', nextOwner: '', engReview: '', dataReview: '', dependsOn: [], pullRequest: null, ...over,
})

const pr = (waitingOnHandle: string | null, waitingOn = 'waiting for a non-author approval; requested from @priya-n 2 days ago') =>
  ({ number: 12, url: 'u', state: 'OPEN', mergedAt: null, updatedAt: null, waitingOn, waitingOnHandle })

function input(over: Partial<NeedsYouInput> = {}): NeedsYouInput {
  return {
    actor: { name: '@priya-n', source: 'roster' },
    sprint: block('sprint.py status --json', {
      ok: true, sprint: null, slate: [], readiness: { ready: 0, total: 0, gaps: [] },
      verdictsPending: [{ spec: '0001', lane: 'eng', sinceBusinessDays: 3 }, { spec: '0002', lane: 'data', sinceBusinessDays: null }],
      handoffsOpen: [{ spec: '0003', to: '@Priya-N', sinceBusinessDays: 1 }, { spec: '0004', to: '@sam-k', sinceBusinessDays: 0 }],
      mix: {}, mixWarnings: [], wip: { inFlight: null, cap: null }, buildOrder: [], nextUp: null, dependencyGaps: [], decisions: null, carriedIn: [], hasData: true, note: null,
    }),
    board: block('spec_status.py --all --json + track_specs.py --json', {
      rows: [row({ spec: '0001', pullRequest: pr('priya-n') }), row({ spec: '0002', pullRequest: pr('@sam-k') }), row({ spec: '0005', owner: '@priya-n', risk: 'HIGH' }), row({ spec: '0006', owner: '@priya-n', risk: '' })],
      codeHostAvailable: true, error: null, teamLimits: null, warnings: [],
    }),
    decisions: block('track_decisions.py --json', {
      total: 3, open: 3, overdue: 1, clockBusinessDays: 2, logPath: 'p', exists: true, overdueDecisions: [],
      openDecisions: [
        { id: 'DL-01', decision: 'Pick auth', owner: '@priya-n', opened: '', due: '', status: 'open', businessDaysOpen: 1, clockDue: null, overdue: false },
        { id: 'DL-02', decision: 'Retention', owner: '@matt', opened: '', due: '', status: 'open', businessDaysOpen: 4, clockDue: null, overdue: true },
        { id: 'DL-03', decision: 'SMS vendor', owner: 'priya-n', opened: '', due: '', status: 'open', businessDaysOpen: 3, clockDue: null, overdue: true },
      ],
    }),
    capabilities: ['sprint-status'],
    unconfirmedTierSpecs: ['0005', '0006'],
    ...over,
  }
}

describe('needsYou', () => {
  it('no identity → empty with NO_ACTOR as the reason, nothing addressed to nobody', () => {
    expect(needsYou(input({ actor: null }))).toEqual({ items: [], reason: NO_ACTOR })
  })

  it('matches by exact handle (case and @ insensitive) — the hand-off to @Priya-N, the PR waiting on priya-n, two decisions', () => {
    const { items, reason } = needsYou(input())
    expect(reason).toBeNull()
    expect(items.map((i) => `${i.kind}:${i.spec ?? i.id}`)).toEqual(['decide:DL-03', 'decide:DL-01', 'ack:0003', 'review:0001'])
  })

  it('overdue decisions come first; the plugin\'s overdue flag is carried, not recomputed', () => {
    const decide = needsYou(input()).items.filter((i) => i.kind === 'decide')
    expect(decide[0]).toMatchObject({ id: 'DL-03', overdue: true }); expect(decide[1]).toMatchObject({ id: 'DL-01', overdue: false })
  })

  it('verdicts_pending never appear — a lane is not a person', () => {
    expect(needsYou(input()).items.some((i) => i.text.includes('eng') || i.text.includes('data'))).toBe(false)
    expect(needsYou(input()).items.map((i) => i.spec)).not.toContain('0002')
  })

  it('each item names its source and carries the plugin\'s words', () => {
    const { items } = needsYou(input())
    expect(items.find((i) => i.kind === 'ack')).toMatchObject({ source: 'sprint.py status --json', text: '@Priya-N', action: 'ack' })
    expect(items.find((i) => i.kind === 'review')).toMatchObject({ source: 'spec_status.py --all --json + track_specs.py --json', text: expect.stringContaining('non-author approval'), action: 'open PR' })
    expect(items.find((i) => i.kind === 'decide')).toMatchObject({ source: 'track_decisions.py --json' })
  })

  it('confirm-tier items appear only with the capability, only for my specs with a risk and an empty risk_confirmed_by', () => {
    expect(needsYou(input()).items.some((i) => i.kind === 'confirm-tier')).toBe(false)
    const withCap = needsYou(input({ capabilities: ['sprint-status', 'confirm-tier'] })).items.filter((i) => i.kind === 'confirm-tier')
    expect(withCap).toEqual([{ kind: 'confirm-tier', spec: '0005', action: 'confirm', source: 'spec_status.py --all --json + track_specs.py --json', text: 'HIGH' }])
    // A row that does not carry the key at all (older plugin) is not "unconfirmed".
    expect(needsYou(input({ capabilities: ['confirm-tier'], unconfirmedTierSpecs: [] })).items.some((i) => i.kind === 'confirm-tier')).toBe(false)
  })

  it('a block that failed contributes nothing and does not hide the others', () => {
    const { items } = needsYou(input({ decisions: block<DecisionsView>('track_decisions.py --json', null) }))
    expect(items.map((i) => i.kind)).toEqual(['ack', 'review'])
  })

  it('no per-person total exists on the result — it is a list', () => {
    const result = needsYou(input()) as unknown as Record<string, unknown>
    expect(Object.keys(result).sort()).toEqual(['items', 'reason'])
  })
})
