// One fixture for the sprint-home tests (P5): a `CommandCenter` document as `getCommandCenter`
// would return it, every block sourced, built from the SAME sprint and board rows the SprintBoard
// test uses so the two screens cannot drift. Helpers build variants (no sprint, no actor, no
// roster, no host) without copying the whole thing.
import type {
  Board, BoardRow, CommandCenter, DecisionsView, FindingsView, ProjectSettings, Scorecard, SourcedBlock, SprintListView,
  SprintLogView, SprintSlateRow, SprintView,
} from '../shared/types'

export const ME = '@arjun-m'

export const slateRow = (over: Partial<SprintSlateRow> = {}): SprintSlateRow => ({
  id: '0007', name: 'duplicate-claim-409', risk: 'HIGH', type: 'feature', channel: '', status: 'ready', sprint: 'S08',
  nextOwner: '', engReview: '', dataReview: '', dependsOn: [], dor: 'READY', dorBlocking: [],
  path: '/p/specs/0007-duplicate-claim-409.md', relPath: 'specs/0007-duplicate-claim-409.md', ...over,
})

export const boardRow = (over: Partial<BoardRow> = {}): BoardRow => ({
  spec: '0007', name: 'duplicate-claim-409', path: 'specs/0007-duplicate-claim-409.md', title: 'Duplicate claim 409', status: 'ready',
  risk: 'HIGH', team: 'core', channel: '', owner: ME, developer: '', checker: '', branch: '', sprint: 'S08', nextOwner: '',
  engReview: '', dataReview: '', dependsOn: [], pullRequest: null, ...over,
})

export const SLATE: SprintSlateRow[] = [
  slateRow(),
  slateRow({ id: '0008', name: 'claim-export', risk: 'MEDIUM', status: 'in-flight', nextOwner: '@sam-k', path: '/p/specs/0008-claim-export.md', relPath: 'specs/0008-claim-export.md' }),
  slateRow({ id: '0009', name: 'adjuster-notes', risk: 'LOW', status: 'in-flight', dependsOn: ['0007'], path: '/p/specs/0009-adjuster-notes.md', relPath: 'specs/0009-adjuster-notes.md' }),
  slateRow({ id: '0010', name: 'policy-lookup', risk: 'LOW', status: 'merged', engReview: 'accepted', dataReview: 'n-a', path: '/p/specs/0010-policy-lookup.md', relPath: 'specs/0010-policy-lookup.md' }),
  slateRow({ id: '0011', name: 'fraud-flags', risk: 'MEDIUM', status: 'ready', dor: 'NOT READY', dorBlocking: ['## Scope Out: missing'], path: '/p/specs/0011-fraud-flags.md', relPath: 'specs/0011-fraud-flags.md' }),
]

export const BOARD_ROWS: BoardRow[] = [
  boardRow(),
  boardRow({
    spec: '0008', name: 'claim-export', path: 'specs/0008-claim-export.md', status: 'in-flight', risk: 'MEDIUM', owner: '@priya-n', developer: ME, checker: '@sam-k',
    nextOwner: '@sam-k', branch: 'spec/0008-claim-export',
    pullRequest: { number: 42, url: 'https://example.test/pr/42', state: 'OPEN', mergedAt: null, updatedAt: '2026-10-05T10:00:00Z', waitingOn: 'waiting for CI: unit failed', waitingOnHandle: null },
  }),
  boardRow({
    spec: '0009', name: 'adjuster-notes', path: 'specs/0009-adjuster-notes.md', status: 'in-flight', risk: 'LOW', owner: '@priya-n', developer: '@sam-k', checker: ME, team: 'data',
    branch: 'spec/0009-adjuster-notes',
    pullRequest: { number: 43, url: 'https://example.test/pr/43', state: 'OPEN', mergedAt: null, updatedAt: null, waitingOn: 'waiting for a non-author approval; requested from @arjun-m 2 days ago', waitingOnHandle: ME, waitHours: 50, overAlarm: true },
  }),
  boardRow({ spec: '0010', name: 'policy-lookup', path: 'specs/0010-policy-lookup.md', status: 'merged', risk: 'LOW', owner: '@sam-k', developer: '@sam-k', checker: '@priya-n', pullRequest: { number: 40, url: 'https://example.test/pr/40', state: 'MERGED', mergedAt: '2026-10-05T16:00:00Z', updatedAt: null, waitingOn: 'merged', waitingOnHandle: null } }),
  boardRow({ spec: '0011', name: 'fraud-flags', path: 'specs/0011-fraud-flags.md', status: 'ready', risk: 'MEDIUM', owner: '@priya-n' }),
  // Unslated candidates and a deferral: Refining's rows.
  boardRow({ spec: '0012', name: 'batch-close', path: 'specs/0012-batch-close.md', status: 'draft', risk: 'LOW', owner: ME, sprint: '' }),
  boardRow({ spec: '0013', name: 'vendor-sync', path: 'specs/0013-vendor-sync.md', status: 'deferred', risk: 'MEDIUM', owner: '@sam-k', sprint: '' }),
]

export const SPRINT: SprintView = {
  ok: true,
  sprint: {
    id: 'S08', goal: 'Adjusters file without a phone call', start: '2026-09-28', end: '2026-10-09', state: 'ready',
    target: 4, mix: 'HIGH:1,MEDIUM:2,LOW:1', boardRef: '', readiedBy: '@priya-n', closedBy: '', created: '2026-09-25',
    path: '/p/.sdlc/sprints/S08.md', relPath: '.sdlc/sprints/S08.md', days: { total: 10, elapsed: 4, remaining: 6 },
  },
  slate: SLATE,
  readiness: { ready: 1, total: 5, gaps: [{ spec: '0011', gaps: ['DoR: NOT READY (## Scope Out: missing)'] }] },
  verdictsPending: [{ spec: '0009', lane: 'eng', sinceBusinessDays: 2 }, { spec: '0009', lane: 'data', sinceBusinessDays: null }],
  handoffsOpen: [{ spec: '0008', to: '@sam-k', sinceBusinessDays: 2 }],
  mix: { HIGH: { target: 1, actual: 1 }, MEDIUM: { target: 2, actual: 2 }, LOW: { target: 1, actual: 2 } },
  mixWarnings: ['LOW: 2 slated of 1 targeted'],
  wip: { inFlight: 2, cap: 4 },
  buildOrder: ['0007', '0008', '0009'],
  nextUp: '0007',
  dependencyGaps: [],
  decisions: { open: 1, overdue: [{ id: 'DL-01', decision: 'Fail open or closed?', owner: ME, due: '2026-10-02' }] },
  carriedIn: [],
  hasData: true,
  note: null,
}

export const NO_SPRINT: SprintView = {
  ...SPRINT, sprint: null, slate: [], readiness: { ready: 0, total: 0, gaps: [] }, verdictsPending: [], handoffsOpen: [], mix: {},
  mixWarnings: [], wip: { inFlight: null, cap: null }, buildOrder: [], nextUp: null, decisions: null, carriedIn: [], hasData: false,
  note: 'No sprint — open one with /sprd-sprint new.',
}

export const ROSTER: ProjectSettings['roster'] = {
  file: '.sdlc/team.yaml', present: true, errors: [],
  teams: [{ name: 'core', lead: '@priya-n' }, { name: 'data', lead: '@sam-k' }],
  people: [
    { handle: '@priya-n', name: 'Priya N', team: 'core', roles: ['owner', 'checker'] },
    { handle: ME, name: 'Arjun M', team: 'core', roles: ['developer', 'checker'] },
    { handle: '@sam-k', name: 'Sam K', team: 'data', roles: ['developer'] },
  ],
}

export const DECISIONS: DecisionsView = {
  total: 2, open: 1, overdue: 1, clockBusinessDays: 2, logPath: '.sdlc/decision-log.md', exists: true,
  openDecisions: [{ id: 'DL-01', decision: 'Fail open or closed?', owner: ME, opened: '2026-09-30', due: '2026-10-02', status: 'open', businessDaysOpen: 4, clockDue: '2026-10-02', overdue: true }],
  overdueDecisions: [{ id: 'DL-01', decision: 'Fail open or closed?', owner: ME, opened: '2026-09-30', due: '2026-10-02', status: 'open', businessDaysOpen: 4, clockDue: '2026-10-02', overdue: true }],
}

export const SCORECARD: Scorecard = {
  accepted_as_is_rate: 0.75, review_wait_median_hours: 18.5, security_review_wait_median_hours: null, rework_revert_rate: null,
  bounce_back_rate: 0.1, escaped_bugs: [{ which_check: 'grader', spec: '0004' }],
  dora: { deploy_count: 3, lead_time_median_hours: 40, change_fail_rate: null, time_to_recover_median_hours: null },
  totals: { merges: 4, reverts: 0, bounces: 1 },
}

export const LOG: SprintLogView = {
  events: [
    { timestamp: '2026-10-05T16:10:00Z', event: 'verdict', spec: '0010', sprint: 'S08', by: '@priya-n', lane: 'eng', verdict: 'accepted' },
    { timestamp: '2026-10-05T09:00:00Z', event: 'handoff', spec: '0008', sprint: 'S08', by: ME, to: '@sam-k' },
  ],
  count: 2, since: '2026-10-05', path: '.sdlc/metrics/sprint-log.jsonl', exists: true, skipped: 0,
}

const FINDINGS: FindingsView = { tracked: 0, openDebt: 0, fixedClaimMismatches: 0, findings: [], recurrence: {} }
const SPRINTS: SprintListView = { sprints: [{ id: 'S07', state: 'closed', goal: '', start: '', end: '', ordinal: 7 }, { id: 'S08', state: 'ready', goal: 'Adjusters file without a phone call', start: '2026-09-28', end: '2026-10-09', ordinal: 8 }], active: 'S08', count: 2 }

export function block<T>(source: string, data: T | null, error: string | null = null): SourcedBlock<T> {
  return { source, fetchedAt: '2026-10-06T10:42:00Z', ok: data !== null, data, error }
}

export const CC: CommandCenter = {
  projectPath: '/p',
  fetchedAt: '2026-10-06T10:42:00Z',
  actor: { name: ME, source: 'roster' },
  capabilities: ['sprint-status', 'sprint-write', 'sprint-list', 'sprint-log', 'confirm-tier', 'readiness-all', 'decision-open', 'decision-decide', 'code-host'],
  sprint: block('sprint.py status --json', SPRINT),
  sprints: block('sprint.py list --json', SPRINTS),
  board: block<Board & { warnings: string[] }>('spec_status.py --all --json', { rows: BOARD_ROWS, codeHostAvailable: true, error: null, teamLimits: null, warnings: [] }),
  decisions: block('track_decisions.py --json', DECISIONS),
  findings: block('record_findings.py report --json', FINDINGS),
  scorecard: block('scorecard.py report --json', SCORECARD),
  roster: block('project_settings.py --json', ROSTER),
  log: block('sprint.py log --since 2026-10-05 --json', LOG),
  needsYou: [
    { kind: 'decide', id: 'DL-01', action: 'decide', source: 'track_decisions.py --json', text: 'Fail open or closed?', overdue: true },
    { kind: 'review', spec: '0009', action: 'open PR', source: 'spec_status.py --all --json', text: 'waiting for a non-author approval; requested from @arjun-m 2 days ago' },
    { kind: 'confirm-tier', spec: '0012', action: 'confirm', source: 'spec_status.py --all --json', text: 'LOW proposed' },
  ],
  needsYouReason: null,
  sinceYesterday: [
    { origin: 'log', key: '2026-10-05T16:10:00Z+verdict+0010', at: '2026-10-05T16:10:00Z', event: 'verdict', spec: '0010', by: '@priya-n', text: 'eng accepted', raw: {} },
    { origin: 'board', key: '2026-10-05T16:00:00Z+merged+0010', at: '2026-10-05T16:00:00Z', event: 'merged', spec: '0010', text: 'PR #40 merged', raw: {} },
    { origin: 'log', key: 'undated+ack+0003', at: null, event: 'ack', spec: '0003', text: 'acknowledged', raw: {} },
  ],
  since: 1,
}

/** The empty fixture of §8's honesty checks: no sprint, no roster, no host, no decision-log, no
 * actor, no capabilities beyond the home itself. */
export const EMPTY_CC: CommandCenter = {
  ...CC,
  actor: null,
  capabilities: ['sprint-status'],
  sprint: block('sprint.py status --json', NO_SPRINT),
  sprints: block('sprint.py list --json', { sprints: [], active: null, count: 0 }),
  board: block<Board & { warnings: string[] }>('spec_status.py --all --json', { rows: [], codeHostAvailable: false, error: 'gh not found', teamLimits: null, warnings: [] }),
  decisions: block('track_decisions.py --json', null, 'no decision-log'),
  findings: block('record_findings.py report --json', null, 'no ledger'),
  scorecard: block('scorecard.py report --json', null, 'no events'),
  roster: block('project_settings.py --json', null, 'no roster'),
  log: block('sprint.py log --json', null, 'lacks sprint-log'),
  needsYou: [],
  needsYouReason: 'sign in or type your name to see what needs you',
  sinceYesterday: [],
}

export function withCc(over: Partial<CommandCenter>): CommandCenter {
  return { ...CC, ...over }
}
