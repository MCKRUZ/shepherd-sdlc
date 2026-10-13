/** `shared/reasons.ts` is the complete list of Studio's own disabled-control sentences
 * (togo-command-center.md §2.7, §8 honesty check 1) and the "no data" wording. */
import { describe, expect, it } from 'vitest'
import * as reasons from '../shared/reasons'

describe('reasons', () => {
  it('a missing capability disables honestly, naming the capability', () => {
    expect(reasons.newerPlugin('sprint-log')).toBe('arrives with a newer plugin: lacks sprint-log')
    expect(reasons.isReason(reasons.newerPlugin('confirm-tier'))).toBe(true)
    expect(reasons.isReason('sprint home arrives with a newer plugin: lacks sprint-status')).toBe(true)
  })

  it('names the ten command-center capabilities of §2.6, the three it already read and the six Azure Boards ones', () => {
    expect(Object.values(reasons.CAPABILITIES).sort()).toEqual([
      'ado-apply', 'ado-comment', 'ado-pull-discussion', 'ado-reconcile', 'ado-show', 'ado-status-json',
      'assign-roles', 'confirm-tier', 'decision-decide', 'decision-open', 'findings-json', 'handoff-check', 'readiness-all',
      'sprint-carry', 'sprint-edit', 'sprint-list', 'sprint-log', 'sprint-status', 'sprint-write',
    ])
  })

  it('every fixed sentence is a reason; a made-up one is not', () => {
    for (const s of reasons.REASON_SENTENCES) expect(reasons.isReason(s), s).toBe(true)
    expect(reasons.isReason('Not available')).toBe(false)
    expect(reasons.isReason(null)).toBe(false)
    expect(reasons.isReason('')).toBe(false)
    expect(reasons.isReason(reasons.createSprintFirst('S09'))).toBe(true)
    expect(reasons.createSprintFirst('S09')).toBe('create S09 first →')
  })

  it('the §2.7 sentences are present word for word', () => {
    expect(reasons.NO_ACTOR).toBe('Sign in or type your name — the plugin records who is accountable')
    expect(reasons.PROMOTE_FINDING).toBe('Promotion arrives with Phase C of the context-repair loop')
    expect(reasons.STANDUP_NOTES).toContain('no read-only standup agent is registered in `agentRun`')
    expect(reasons.SECURITY_SIGNER).toContain('No frontmatter field for a security signer')
    expect(reasons.STREAM_ARRIVES).toBe('the stream arrives with a newer plugin: lacks sprint-log')
    expect(reasons.OWN_BUILD_VERDICT).toBe('you built this — the verdict is someone else\'s')
  })

  it('"no data" is words; none of the no-data sentences contains a digit', () => {
    for (const s of [reasons.NO_DATA, reasons.CAP_NOT_SET, reasons.DATES_UNREADABLE, reasons.NOTHING_NEEDS_YOU, reasons.NO_PR_YET,
      reasons.NO_CHANNEL_BOUND, reasons.GATED_PATH_NOT_DECLARED, reasons.ORDER_NOT_GIVEN, reasons.UNDATED]) {
      expect(s).not.toMatch(/\d/)
    }
  })

  it('exit code → heading: 0 Done, 1 Not done, 2 Refused by the plugin, null Not done', () => {
    expect(reasons.exitHeading(0)).toBe('Done')
    expect(reasons.exitHeading(1)).toBe('Not done')
    expect(reasons.exitHeading(2)).toBe('Refused by the plugin')
    expect(reasons.exitHeading(null)).toBe('Not done')
    expect(reasons.exitHeading(137)).toBe('Not done')
  })

  it('the forbidden metric words regex catches the four phrases and nothing innocent', () => {
    for (const w of ['Velocity', 'story points', 'PR count', 'Lines of Code']) expect(reasons.FORBIDDEN_METRIC_WORDS.test(w)).toBe(true)
    expect(reasons.FORBIDDEN_METRIC_WORDS.test('accepted-as-is')).toBe(false)
    expect(reasons.FORBIDDEN_METRIC_WORDS.test('3 of 4')).toBe(false)
  })
})
