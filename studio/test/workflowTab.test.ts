/** The Workflow tab (spec 0017): a step per required document, in the stage's declared order,
 * plus a Sign-off step, with the current step's real content shown beside the list.
 *
 * `LiveDocumentPanel`'s own fetch happens in a `useEffect`, which `renderToStaticMarkup` never
 * runs (server rendering has no effect phase) — so what these tests can and do pin is the
 * STRUCTURE: exactly one step per document plus Sign-off, in order; a locked or done step's row
 * carries nothing but its title, description and status — asserted as absence, never as
 * `disabled`; and the current step is the only place any content-loading attempt appears at
 * all. The live-refresh behaviour itself (the panel's text changing as the underlying file
 * changes, within one polling interval, with no reload) is proven end to end in
 * test/e2e/workflow.spec.ts, which is the only place effects actually run.
 */

import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { SignOffQuestion, StageDocument, StageReadiness } from '../shared/types'
import { WorkflowTab } from '../src/components/WorkflowTab'

function doc(overrides: Partial<StageDocument> & { path: string }): StageDocument {
  return {
    name: overrides.path.split('/').pop() ?? overrides.path,
    exists: true,
    folder: false,
    shaped: true,
    description: undefined,
    findingCount: 0,
    ready: true,
    ...overrides,
  }
}

const QUESTIONS: SignOffQuestion[] = [
  { id: 'q-1', text: 'Scope boundaries are unambiguous', hint: { status: 'looks_met', detail: '2 out of scope' }, confirmation: null },
  { id: 'q-2', text: 'Rollback rehearsed', hint: { status: 'judgement', detail: 'Needs your judgement.' }, confirmation: null },
]

function makeReadiness(documents: StageDocument[], over: Partial<StageReadiness> = {}): StageReadiness {
  return {
    ok: true,
    stageId: '1',
    name: 'requirements',
    display: 'Phase 1: Requirements',
    isCurrent: true,
    documents,
    findings: [],
    judgement: QUESTIONS,
    signOff: { status: 'pending', signedOffBy: null, completedAt: null },
    ready: documents.every((d) => d.ready),
    ...over,
  }
}

function render(readiness: StageReadiness) {
  return renderToStaticMarkup(h(WorkflowTab, {
    projectPath: '/tmp/project',
    readiness,
    actor: 'Matt K',
    busyId: null,
    confirmError: null,
    onToggleSignOff: () => {},
    onOpenDocument: () => {},
  }))
}

/** Pulls one step's own `<li>...</li>` fragment out of the full render, so an assertion about
 * what a SPECIFIC row does or does not contain cannot be satisfied by content that actually
 * lives in the shared panel next to the list. None of these rows nest another `<li>`, so a
 * non-greedy match to the next `</li>` is exact. */
function stepFragment(html: string, key: string): string {
  const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const m = html.match(new RegExp(`<li[^>]*data-step-key="${escaped}"[^>]*>([\\s\\S]*?)</li>`))
  if (!m) throw new Error(`no step row found for ${key}`)
  return m[1]
}

describe('WorkflowTab (spec 0017)', () => {
  it('renders exactly one step per required document, in order, plus one trailing Sign-off step', () => {
    const readiness = makeReadiness([
      doc({ path: 'requirements.md', ready: true }),
      doc({ path: 'epics.md', ready: false }),
      doc({ path: 'business-rules.md', ready: false }),
    ])
    const html = render(readiness)
    const keys = [...html.matchAll(/data-step-key="([^"]+)"/g)].map((m) => m[1])
    expect(keys).toEqual(['requirements.md', 'epics.md', 'business-rules.md', 'sign-off'])
  })

  it('a locked step\'s row has its title and description and nothing else — no button, no panel', () => {
    const readiness = makeReadiness([
      doc({ path: 'requirements.md', ready: false, description: 'What the system must do.' }),
      doc({ path: 'epics.md', ready: false, description: 'The bigger groupings.' }),
    ])
    const html = render(readiness)
    expect(html.match(/data-step-status="current"/g)).toHaveLength(1)
    // Two locked rows: epics.md AND the trailing Sign-off step, since not every document is
    // ready yet.
    expect(html.match(/data-step-status="locked"/g)).toHaveLength(2)

    const locked = stepFragment(html, 'epics.md')
    expect(locked).toContain('epics.md')
    expect(locked).toContain('The bigger groupings.')
    // Asserted as ABSENCE, not as `disabled` — a disabled control still says "this is a thing
    // you could do here", which is exactly the claim a locked step must not make.
    expect(locked).not.toContain('<button')
    expect(locked).not.toContain('<a ')
    expect(locked).not.toContain('data-testid="live-document-panel"')
    expect(locked).not.toContain('type="checkbox"')
  })

  it('a done step\'s row shows a completion state and never the document\'s full body text', () => {
    const readiness = makeReadiness([
      doc({ path: 'requirements.md', ready: true, description: 'What the system must do.' }),
      doc({ path: 'epics.md', ready: false }),
    ])
    const html = render(readiness)
    const done = stepFragment(html, 'requirements.md')
    expect(done).toContain('Complete')
    expect(done).toContain('requirements.md')
    expect(done).not.toContain('data-testid="live-document-panel"')
    expect(done).not.toContain('<button')
    expect(done).not.toContain('type="checkbox"')
  })

  it('only the current step ever triggers any content-loading attempt, and it is the only place content appears', () => {
    const readiness = makeReadiness([
      doc({ path: 'requirements.md', ready: true }),
      doc({ path: 'epics.md', ready: false }),
      doc({ path: 'business-rules.md', ready: false }),
    ])
    const html = render(readiness)

    // LiveDocumentPanel's effect never runs under renderToStaticMarkup, so its first-paint
    // state ("Opening…") is what a real mount shows before the first poll answers — and it
    // must appear exactly once, for the current step, never for a done or locked one.
    expect(html.match(/Opening…/g)).toHaveLength(1)
    expect(stepFragment(html, 'requirements.md')).not.toContain('Opening…')
    expect(stepFragment(html, 'business-rules.md')).not.toContain('Opening…')

    // And the loading attempt is not INSIDE any step row — it lives in the shared panel next
    // to the list, not duplicated into the row itself.
    for (const key of ['requirements.md', 'epics.md', 'business-rules.md', 'sign-off']) {
      expect(stepFragment(html, key)).not.toContain('Opening…')
    }
  })

  it('a folder current step is not opened as a document', () => {
    const readiness = makeReadiness([
      doc({ path: 'adrs', ready: false, folder: true, exists: true }),
    ])
    const html = render(readiness)
    expect(html).toContain('is a folder of documents')
    expect(html).not.toContain('Opening…')
  })

  it('the Sign-off step expands inline, with the same questions the Documents tab shows, once every document is ready', () => {
    const readiness = makeReadiness([doc({ path: 'requirements.md', ready: true })])
    const html = render(readiness)

    expect(stepFragment(html, 'sign-off')).not.toContain('type="checkbox"') // the row itself stays a row
    expect(html.match(/type="checkbox"/g)).toHaveLength(QUESTIONS.length) // but the panel shows them
    for (const q of QUESTIONS) expect(html).toContain(q.text)
    // Not a link to the Documents tab — there is no anchor or "Documents" tab reference inside
    // the panel area at all, it is the real component rendered in place.
    expect(html).not.toMatch(/href=/)
  })

  it('the Sign-off step stays locked, with no questions shown, while a document is not ready', () => {
    const readiness = makeReadiness([
      doc({ path: 'requirements.md', ready: false }),
    ])
    const html = render(readiness)
    // The row stays a plain title+description row (its description happens to use the word
    // "Confirm" — that's fine, it's still only a sentence, not a control) — what must be
    // absent is the QUESTIONS themselves and any way to answer one.
    expect(stepFragment(html, 'sign-off')).not.toContain(QUESTIONS[0].text)
    expect(html.match(/type="checkbox"/g)).toBeNull()
  })

  it('stacks the steps above the file panel at phone width and puts them side by side above it', () => {
    // A structural check that the responsive classes are actually present — the real
    // measurement (no horizontal scrollbar at 400px) is an e2e concern (test/e2e/workflow.spec.ts),
    // since only a real layout engine can prove a scrollbar does or does not appear.
    const html = render(makeReadiness([doc({ path: 'requirements.md', ready: false })]))
    expect(html).toMatch(/class="flex flex-col gap-6 sm:flex-row"/)
  })

  describe('the document panel header (spec 0018)', () => {
    it('shows Back to Workflow, Previous and Next, with Previous disabled on the first required document', () => {
      const readiness = makeReadiness([
        doc({ path: 'a.md', ready: false }),
        doc({ path: 'b.md', ready: false }),
        doc({ path: 'c.md', ready: false }),
      ])
      const html = render(readiness)
      expect(html).toContain('Back to Workflow')
      // Matched on `disabled=""` immediately after `type="button"` — React's own static-markup
      // spelling for a true boolean attribute — rather than a bare substring search for
      // "disabled", which Tailwind's own `disabled:opacity-40` class name would also match on
      // a button that is NOT disabled at all.
      expect(html).toMatch(/<button type="button" disabled=""[^>]*>Previous<\/button>/)
      expect(html).toMatch(/<button type="button"[^>]*>Next<\/button>/)
      expect(html).not.toMatch(/<button type="button" disabled=""[^>]*>Next<\/button>/)
    })

    it('disables Next, not Previous, when the current (and therefore first-viewed) document is the stage\'s last', () => {
      const readiness = makeReadiness([
        doc({ path: 'a.md', ready: true }),
        doc({ path: 'b.md', ready: true }),
        doc({ path: 'c.md', ready: false }),
      ])
      const html = render(readiness)
      expect(html).toMatch(/<button type="button" disabled=""[^>]*>Next<\/button>/)
      expect(html).not.toMatch(/<button type="button" disabled=""[^>]*>Previous<\/button>/)
    })

    it('the header does not force new horizontal overflow of its own at phone width (flex-wrap)', () => {
      const html = render(makeReadiness([doc({ path: 'a.md', ready: false }), doc({ path: 'b.md', ready: false })]))
      expect(html).toMatch(/class="flex flex-wrap items-center justify-between gap-2/)
    })
  })
})
