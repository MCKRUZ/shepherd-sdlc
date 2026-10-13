/** `sinceYesterday` (togo-command-center.md §2.3): ledger events verbatim plus PRs merged in the
 * window, each tagged by origin, newest first by the source's timestamp, undated rows last and
 * labelled. The window is a filter date main passes as `--since`, never a reported number. */
import { describe, expect, it } from 'vitest'
import { logEventText, sinceDateFor, sinceYesterday, STREAM_ROW_FIELDS } from '../../electron/main/commandCenter'
import type { Board, BoardRow, SourcedBlock, SprintLogView } from '../../shared/types'

const block = <T>(source: string, data: T | null): SourcedBlock<T> => ({ source, fetchedAt: 't', ok: data !== null, data, error: data === null ? 'no' : null })
const row = (spec: string, mergedAt: string | null): BoardRow => ({
  spec, name: 'a', path: `specs/${spec}-a.md`, title: '', status: 'merged', risk: 'LOW', team: '', channel: '', owner: '', developer: '', checker: '', branch: '',
  sprint: 'S08', nextOwner: '', engReview: '', dataReview: '', dependsOn: [],
  pullRequest: { number: Number(spec), url: 'u', state: 'MERGED', mergedAt, updatedAt: null, waitingOn: 'merged', waitingOnHandle: null },
})
const log = (events: SprintLogView['events']): SprintLogView => ({ events, count: events.length, since: '2026-10-05', path: 'p', exists: true, skipped: 0 })

describe('sinceDateFor', () => {
  it('counts business days back, skipping the weekend', () => {
    expect(sinceDateFor(1, new Date(2026, 9, 6))).toBe('2026-10-05')   // Tue → Mon
    expect(sinceDateFor(1, new Date(2026, 9, 5))).toBe('2026-10-02')   // Mon → Fri
    expect(sinceDateFor(3, new Date(2026, 9, 6))).toBe('2026-10-01')   // Tue → Thu last week
  })
})

describe('sinceYesterday', () => {
  const events = [
    // The plugin's ledger key is `ts` (sprint_model.make_event); a `timestamp` line is read too.
    { ts: '2026-10-05T09:00:00+00:00', event: 'slated', spec: '0007', sprint: 'S08', by: '@priya-n' },
    { event: 'ack', spec: '0003', by: '@sam-k' },
    { timestamp: '2026-10-06T08:30:00+00:00', event: 'verdict', spec: '0007', lane: 'eng', verdict: 'accepted', by: '@matt' },
  ]
  const board = { rows: [row('0001', '2026-10-05T17:00:00Z'), row('0002', '2026-09-20T10:00:00Z'), row('0003', null)], codeHostAvailable: true, error: null, teamLimits: null, warnings: [] }

  it('orders newest first by the source timestamp, undated last — labelled by the renderer\'s stamp, not a second word in the text', () => {
    const rows = sinceYesterday({ log: block('sprint.py log --since 2026-10-05 --json', log(events)), board: block('b', board), since: '2026-10-05' })
    expect(rows.map((r) => `${r.origin}:${r.event}:${r.spec}`)).toEqual(['log:verdict:0007', 'board:merged:0001', 'log:slated:0007', 'log:ack:0003'])
    // v13 fixer round: `at: null` IS the undated fact (TodayColumn's `stampText` says "undated"
    // on the id line); the text used to append the word too and the row said it twice.
    expect(rows[3].at).toBeNull(); expect(rows[3].text).toBe('')
  })

  /** v13 fixer round: a log row's text is the line's OTHER fields — never the event, spec and
   * `by` the row already shows on its id line and by-line ("handoff · 0003 · by Pod Lead" under
   * "0003 handoff" over "by Pod Lead" was one fact three times). */
  it('a log row\'s text is the ledger line\'s other fields, in the plugin\'s own words; none → empty', () => {
    const rows = sinceYesterday({ log: block('l', log(events)), board: block('b', board), since: '2026-10-05' })
    expect(rows.find((r) => r.event === 'verdict')!.text).toBe('lane eng · verdict accepted')
    expect(rows.find((r) => r.event === 'slated')!.text).toBe('')
    expect(rows.find((r) => r.event === 'ack')!.text).toBe('')
    // Never the spec id or the `by` name again (the id line and the by-line carry them).
    for (const r of rows.filter((x) => x.origin === 'log')) { expect(r.text).not.toContain(r.spec!); if (r.by) expect(r.text).not.toContain(r.by) }
    expect(logEventText({ ts: 't', event: 'handoff', spec: '0006', by: 'Pod Lead', to: '@sam-k', note: 'ready for checking' })).toBe('to @sam-k · note ready for checking')
    expect(logEventText({ event: 'carried', spec: '0001', to_sprint: 'S08', reason: 'blocked on DL-03', by: 'x' })).toBe('to_sprint S08 · reason blocked on DL-03')
    expect(logEventText({ event: 'x', spec: '1', extra: { a: 1 }, empty: '', nothing: null })).toBe('extra {"a":1}')
    expect([...STREAM_ROW_FIELDS].sort()).toEqual(['by', 'event', 'spec', 'sprint', 'timestamp', 'ts'])
  })

  it('keeps the ledger line verbatim in raw and keys a row by timestamp+event+spec', () => {
    const rows = sinceYesterday({ log: block('l', log(events)), board: block('b', board), since: '2026-10-05' })
    const verdict = rows.find((r) => r.event === 'verdict')!
    expect(verdict.raw).toEqual(events[2]); expect(verdict.key).toBe('2026-10-06T08:30:00+00:00+verdict+0007'); expect(verdict.by).toBe('@matt')
  })

  it('a PR merged before the window is not in the stream; a PR without mergedAt never is', () => {
    const rows = sinceYesterday({ log: block('l', log([])), board: block('b', board), since: '2026-10-05' })
    expect(rows.map((r) => r.spec)).toEqual(['0001']); expect(rows[0]).toMatchObject({ origin: 'board', text: 'PR #1 merged', at: '2026-10-05T17:00:00Z' })
  })

  it('a log block that failed (older plugin) leaves the board\'s merged rows alone', () => {
    const rows = sinceYesterday({ log: block<SprintLogView>('l', null), board: block('b', board), since: '2026-10-05' })
    expect(rows).toHaveLength(1); expect(rows[0].origin).toBe('board')
  })

  it('no aggregate: the result is rows, nothing counted', () => {
    expect(Array.isArray(sinceYesterday({ log: block('l', log(events)), board: block<Board & { warnings: string[] }>('b', null), since: '2026-10-05' }))).toBe(true)
  })
})
