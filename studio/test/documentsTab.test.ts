// @vitest-environment jsdom
/** The Documents tab as a BEHAVIOUR suite (studio-observatory.md §7 DocumentsTab row, decision D-B).
 *
 * Until Wave 3 this file compared `DocumentsTab` byte-for-byte against a reference copy of the
 * pre-0017 StageHome markup. That proof did its job (spec 0017's "byte-for-byte" check) and then
 * froze the component out of the kit and the dark theme. The Observatory replaces it with the
 * semantics a person — and the documents e2e — actually rely on, each pinned by name BEFORE the
 * component moved onto Card / Chip / Button / Eyebrow, so the migration is graded against
 * behaviour rather than against class strings. The one semantic the migration ADDS is `data-tone`
 * on the rows (a theme-independent hook for the status of each document).
 *
 * Built with `createElement` rather than JSX, like the rest of the `.test.ts` suite.
 */

import { createElement as h } from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ReadinessFinding, SignOffQuestion, StageDocument, StageReadiness } from '../shared/types'
import { DocumentsTab } from '../src/components/DocumentsTab'

// --- fixtures ----------------------------------------------------------------------------

const DOCS: StageDocument[] = [
  { name: 'requirements.md', path: 'requirements.md', exists: true, folder: false, shaped: true, description: 'What the system must do.', findingCount: 2, ready: false },
  { name: 'epics.md', path: 'epics.md', exists: false, folder: false, shaped: true, description: undefined, findingCount: 0, ready: false },
  { name: 'adrs', path: 'adrs', exists: true, folder: true, shaped: false, description: undefined, findingCount: 0, ready: true },
  { name: 'business-rules.md', path: 'business-rules.md', exists: true, folder: false, shaped: true, description: undefined, findingCount: 0, ready: true },
]

const FINDINGS: ReadinessFinding[] = [
  { path: 'requirements.md', section: 'FR-002', field: 'Dependencies', reason: 'absent or empty' },
  { path: 'requirements.md', section: 'FR-003', field: null, reason: 'section is empty' },
]

const QUESTIONS: SignOffQuestion[] = [
  { id: 'q-1', text: 'Scope boundaries are unambiguous', hint: { status: 'looks_met', detail: '2 out of scope' }, confirmation: null },
]

function makeReadiness(over: Partial<StageReadiness> = {}): StageReadiness {
  return {
    ok: true,
    stageId: '1',
    name: 'requirements',
    display: 'Phase 1: Requirements',
    isCurrent: true,
    documents: DOCS,
    findings: FINDINGS,
    judgement: QUESTIONS,
    signOff: { status: 'pending', signedOffBy: null, completedAt: null },
    ready: false,
    ...over,
  }
}

function mount(over: Partial<StageReadiness> = {}, actor = 'Matt K') {
  const onOpenDocument = vi.fn()
  const onToggle = vi.fn()
  render(h(DocumentsTab, {
    readiness: makeReadiness(over), actor, busyId: null, confirmError: null, onOpenDocument, onToggle,
  }))
  return { onOpenDocument, onToggle }
}

const ALL_READY = {
  documents: DOCS.map((d) => ({ ...d, exists: true, findingCount: 0, ready: true })),
  findings: [],
  ready: true,
  signOff: { status: 'signed_off' as const, signedOffBy: 'Priya N', completedAt: '2026-09-29T00:00:00.000Z' },
}

/** The document list is the first `<ul>` under the "Documents" heading; rows are its `<li>`s. */
function documentRows(): HTMLElement[] {
  const heading = screen.getByRole('heading', { name: 'Documents' })
  const list = heading.parentElement!.querySelector('ul')!
  return within(list).getAllByRole('listitem')
}

function rowFor(name: string): HTMLElement {
  return documentRows().find((li) => li.textContent?.startsWith(name))!
}

// --- the pins (§7 DocumentsTab row), in the order the row lists them ---------------------

describe('DocumentsTab: the behaviour suite (studio-observatory.md §7, D-B)', () => {
  it('pin 1 — every document row carries a data-tone that says how it stands', () => {
    mount()
    expect(rowFor('requirements.md').dataset.tone).toBe('warn')
    expect(rowFor('epics.md').dataset.tone).toBe('neutral')
    expect(rowFor('adrs').dataset.tone).toBe('ok')
    expect(rowFor('business-rules.md').dataset.tone).toBe('ok')
  })

  it('pin 2 — a document with findings shows an amber "N to fill" chip', () => {
    mount()
    const chip = within(rowFor('requirements.md')).getByText('2 to fill')
    // Amber whichever palette spells it: the pre-kit literal or the kit's warn tone.
    expect(chip.className).toMatch(/amber|warn/)
  })

  it('pin 3 — a missing document reads "Not started" and a finished one reads "Complete"', () => {
    mount()
    expect(within(rowFor('epics.md')).getByText('Not started')).toBeTruthy()
    expect(within(rowFor('adrs')).getByText('Complete')).toBeTruthy()
    expect(within(rowFor('business-rules.md')).getByText('Complete')).toBeTruthy()
    // A folder is named as one, so nobody expects a single file to open.
    expect(within(rowFor('adrs')).getByText('folder')).toBeTruthy()
  })

  it('pin 4 — folder rows and non-existent rows are disabled; a real document is not', () => {
    mount()
    expect(within(rowFor('adrs')).getByRole('button')).toHaveProperty('disabled', true)
    expect(within(rowFor('epics.md')).getByRole('button')).toHaveProperty('disabled', true)
    const open = within(rowFor('requirements.md')).getByRole('button')
    expect(open).toHaveProperty('disabled', false)
    // The documents e2e locates this row by `button /^requirements\.md/` — the name leads.
    expect(screen.getByRole('button', { name: /^requirements\.md/ })).toBe(open)
  })

  it('pin 4b — opening a document row calls onOpenDocument with the path and no focus', () => {
    const { onOpenDocument } = mount()
    fireEvent.click(screen.getByRole('button', { name: /^requirements\.md/ }))
    expect(onOpenDocument).toHaveBeenCalledTimes(1)
    expect(onOpenDocument).toHaveBeenCalledWith('requirements.md')
  })

  it('pin 5 — a finding button names the field first, keeps focus, and opens the document at that field', () => {
    const { onOpenDocument } = mount()
    const finding = screen.getByRole('button', { name: /^Dependencies in FR-002 — requirements\.md/ })
    expect(within(finding).getByText('absent or empty')).toBeTruthy()
    finding.focus()
    fireEvent.click(finding)
    expect(document.activeElement).toBe(finding)
    expect(onOpenDocument).toHaveBeenCalledWith('requirements.md', { section: 'FR-002', field: 'Dependencies' })
    // A finding with no field names the section alone.
    fireEvent.click(screen.getByRole('button', { name: /^FR-003 — requirements\.md/ }))
    expect(onOpenDocument).toHaveBeenLastCalledWith('requirements.md', { section: 'FR-003', field: null })
  })

  it('pin 5b — "What is missing" appears only when there is something missing', () => {
    mount()
    expect(screen.getByRole('heading', { name: 'What is missing' })).toBeTruthy()
  })

  it('pin 5c — no findings, no "What is missing" section', () => {
    mount({ findings: [] })
    expect(screen.queryByRole('heading', { name: 'What is missing' })).toBeNull()
  })

  it('pin 6 — the sign-off questions render, each as a checkbox labelled with the question', () => {
    const { onToggle } = mount()
    const box = screen.getByRole('checkbox', { name: 'Scope boundaries are unambiguous' })
    fireEvent.click(box)
    expect(onToggle).toHaveBeenCalledWith(QUESTIONS[0], true)
  })

  it('pin 6b — no judgement questions, no checkboxes', () => {
    mount({ judgement: [] })
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
  })

  it('pin 7 — the readiness banner counts the documents still needing work', () => {
    mount()
    expect(screen.getByText('2 document(s) still need work before this stage can be signed off.')).toBeTruthy()
    expect(screen.queryByText(/Signed off by/)).toBeNull()
  })

  it('pin 7b — when every document is complete the banner says so and names who signed off', () => {
    mount(ALL_READY)
    expect(screen.getByText('Every required document is present and complete.')).toBeTruthy()
    expect(screen.getByText('Signed off by Priya N.')).toBeTruthy()
    expect(screen.queryByText(/to fill/)).toBeNull()
    for (const li of documentRows()) expect(li.dataset.tone).toBe('ok')
  })

  it('keeps "Documents" a heading — the documents e2e waits on it by role', () => {
    mount()
    expect(screen.getByRole('heading', { name: 'Documents' })).toBeTruthy()
    expect(screen.getByText('What the system must do.')).toBeTruthy()
  })
})
