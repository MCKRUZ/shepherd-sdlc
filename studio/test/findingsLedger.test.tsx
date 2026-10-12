// @vitest-environment jsdom
/** The findings ledger (togo-command-center.md §3.3): the plugin's disposition words, off-books
 * outlined and said, recurrence as "seen N times across reports", the unattributed count stated,
 * Promote present and disabled with its reason, and empty states that are sentences — never a 0. */
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { FindingsView } from '../shared/types'
import { newerPlugin, PROMOTE_FINDING } from '../shared/reasons'
import { FindingsLedger, OFF_BOOKS, seenLabel } from '../src/components/SpecCard/FindingsLedger'

const FINDINGS: FindingsView = {
  tracked: 3, openDebt: 1, fixedClaimMismatches: 0,
  findings: [
    { fingerprint: 'security:src/pay.ts', id: 'F-1', category: 'security', severity: 'HIGH', target: 'src/pay.ts', disposition: 'OPEN', detail: 'token logged', offBooks: false, firstSeen: '2026-09-01', lastSeen: '2026-10-01', rounds: 3 },
    { fingerprint: 'style:src/pay.ts', id: 'F-2', category: 'style', severity: 'LOW', target: 'src/pay.ts', disposition: 'SPLIT', detail: 'naming', offBooks: true, firstSeen: null, lastSeen: null, rounds: 1 },
    { fingerprint: 'tests:src/pay.ts', id: 'F-3', category: 'tests', severity: 'MEDIUM', target: 'src/pay.ts', disposition: 'FIXED', detail: 'added a test', offBooks: false, firstSeen: null, lastSeen: null, rounds: 1 },
  ],
  recurrence: { 'security:src/pay.ts': 3 },
  attribution: { method: 'scope-paths', attributed: 3, unattributed: 2 },
}

afterEach(cleanup)

describe('FindingsLedger', () => {
  it('rows wear the plugin\'s disposition word, off-books is outlined and said, recurrence reads "seen N times", the unattributed count is stated', () => {
    render(<FindingsLedger findings={FINDINGS} />)
    expect(screen.getByText("Findings touching this spec's scope paths")).toBeTruthy()
    const open = document.querySelector('[data-finding="security:src/pay.ts"]')!
    expect(open.getAttribute('data-disposition')).toBe('OPEN')
    expect(open.textContent).toContain('seen 3 times across reports')
    expect(open.querySelector('.bg-ledger-open-bg')).toBeTruthy()
    const split = document.querySelector('[data-finding="style:src/pay.ts"]')!
    expect(split.hasAttribute('data-off-books')).toBe(true)
    expect(split.textContent).toContain(OFF_BOOKS)
    expect(split.querySelector('.ring-ledger-offbooks')).toBeTruthy()
    expect(split.querySelector('.bg-ledger-split-bg')).toBeTruthy()
    expect(screen.getByTestId('findings-attribution').textContent).toBe('3 attributed · 2 unattributed (scope-paths)')
    const promote = screen.getAllByRole('button', { name: /^Promote to a permanent check/ }) as HTMLButtonElement[]
    expect(promote).toHaveLength(3)
    for (const b of promote) { expect(b.disabled).toBe(true); expect(b.getAttribute('title')).toBe(PROMOTE_FINDING) }
    expect(seenLabel(1)).toBeNull()
    expect(seenLabel(undefined)).toBeNull()
  })

  it('an empty ledger is the figure and a sentence alone — no "0 attributed" or "0 tracked" stands beside a declared absence; the words name their scripts as code', () => {
    render(<FindingsLedger findings={{ ...FINDINGS, findings: [], tracked: 0, attribution: undefined }} />)
    expect(document.querySelector('[data-cc-figure="no-findings"]')).toBeTruthy()
    expect(screen.getByText('no findings recorded — the ledger is empty')).toBeTruthy()
    expect(screen.queryByTestId('findings-attribution')).toBeNull()
    expect(document.querySelectorAll('[data-stat]')).toHaveLength(0)
    expect(document.body.textContent).not.toMatch(/\b0 (attributed|tracked|unattributed)/)
    expect(document.body.textContent).not.toContain('`')
    expect(Array.from(document.querySelectorAll('code')).map((c) => c.textContent)).toEqual(['/sprd-review', 'record_findings.py record'])
    // v13 fixer round: the chips painted over the line above when the caption wrapped (1280, 1680
    // shots). Two guards in the caption's classes: a 24 px pitch and chips with no vertical padding.
    const caption = screen.getByTestId('findings-caption')
    expect(caption.className).toContain('leading-6')
    expect(caption.className).toContain('[&_code]:py-0')
    cleanup()
    // Attribution with zero rows under the scope paths is the same absence: the sentence says so.
    render(<FindingsLedger findings={{ ...FINDINGS, findings: [], attribution: { method: 'scope-paths', attributed: 0, unattributed: 3 } }} />)
    expect(screen.getByText("no finding targets a path under this spec's scope")).toBeTruthy()
    expect(screen.queryByTestId('findings-attribution')).toBeNull()
  })

  it('project-wide counts are stated when rows exist without a --spec attribution', () => {
    render(<FindingsLedger findings={{ ...FINDINGS, attribution: undefined }} />)
    expect(screen.getByTestId('findings-attribution').textContent).toBe('3 tracked project-wide · open debt 1')
  })

  it('without findings-json the capability is named; a failed block shows its error', () => {
    render(<FindingsLedger findings={null} hasFindingsCapability={false} />)
    expect(screen.getByTestId('findings-empty').textContent).toBe(newerPlugin('findings-json'))
    cleanup()
    render(<FindingsLedger findings={null} error="record_findings.py: no ledger" />)
    expect(screen.getByTestId('findings-empty').textContent).toBe('record_findings.py: no ledger')
  })
})
