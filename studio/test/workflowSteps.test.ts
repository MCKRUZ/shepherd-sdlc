/** The pure function spec 0017 pins everything else to: given a stage's readiness, which step
 * is done, which is current, and which is locked.
 *
 * The line these tests hold is the one the spec names explicitly: the current step is the
 * FIRST not-ready document in the stage's own declared order, never "whichever was edited most
 * recently" — and this module has no notion of "recently" to fall back on even if it wanted to,
 * since a `StageDocument` carries no timestamp. That absence is itself part of the proof: the
 * "reopen after touching a later document" scenario is not something this function can get
 * wrong by accident, because the information that would let it is not there.
 *
 * The done-count parity test is the shared-source acceptance check made mechanical: the
 * Workflow tab and the Documents tab must report the same number of finished documents because
 * both trace back to `document.ready`, and this pins that tracing rather than trusting it.
 */

import { describe, expect, it } from 'vitest'
import { computeWorkflowSteps } from '../src/workflowSteps'
import type { StageDocument, StageReadiness } from '../shared/types'

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

function readiness(documents: StageDocument[], over: Partial<StageReadiness> = {}): StageReadiness {
  return {
    ok: true,
    stageId: '1',
    name: 'requirements',
    display: 'Phase 1: Requirements',
    isCurrent: true,
    documents,
    findings: [],
    judgement: [],
    signOff: { status: 'pending', signedOffBy: null, completedAt: null },
    ready: documents.every((d) => d.ready),
    ...over,
  }
}

describe('computeWorkflowSteps', () => {
  it('has exactly one step per required document, in the same order, plus a trailing Sign-off step', () => {
    const docs = [
      doc({ path: 'a.md', ready: true }),
      doc({ path: 'b.md', ready: false }),
      doc({ path: 'c.md', ready: false }),
    ]
    const steps = computeWorkflowSteps(readiness(docs))

    expect(steps).toHaveLength(4)
    expect(steps.slice(0, 3).map((s) => s.key)).toEqual(['a.md', 'b.md', 'c.md'])
    expect(steps[3]).toMatchObject({ kind: 'sign-off', key: 'sign-off' })
  })

  it('the first not-ready document is current; everything before it is done, everything not-ready after it is locked', () => {
    const docs = [
      doc({ path: 'a.md', ready: true }),
      doc({ path: 'b.md', ready: true }),
      doc({ path: 'c.md', ready: false }),
      doc({ path: 'd.md', ready: false }),
    ]
    const steps = computeWorkflowSteps(readiness(docs))

    expect(steps.map((s) => s.status)).toEqual(['done', 'done', 'current', 'locked', 'locked'])
  })

  it('reopening 3-of-5-ready shows the 4th (first not-ready) as current, even when the 5th was ready too', () => {
    // The exact scenario the acceptance check names: "the 5th was the one most recently
    // edited" — here read as "the 5th is also ready", the harder case, since a naive
    // implementation that picked the LAST ready document (or the last touched one) as the
    // boundary would misread this as everything through the 5th being settled.
    const docs = [
      doc({ path: '1.md', ready: true }),
      doc({ path: '2.md', ready: true }),
      doc({ path: '3.md', ready: true }),
      doc({ path: '4.md', ready: false }),
      doc({ path: '5.md', ready: true }),
    ]
    const steps = computeWorkflowSteps(readiness(docs))

    expect(steps.find((s) => s.key === '4.md')!.status).toBe('current')
    // A document that IS ready is reported done regardless of where it sits relative to the
    // current step — anything else would make this function disagree with the Documents tab,
    // which reads `document.ready` directly and has no idea what "locked" even means.
    expect(steps.find((s) => s.key === '5.md')!.status).toBe('done')
  })

  it('reopening 3-of-5-ready shows the 4th as current when the 5th is not ready either', () => {
    const docs = [
      doc({ path: '1.md', ready: true }),
      doc({ path: '2.md', ready: true }),
      doc({ path: '3.md', ready: true }),
      doc({ path: '4.md', ready: false }),
      doc({ path: '5.md', ready: false }),
    ]
    const steps = computeWorkflowSteps(readiness(docs))

    expect(steps.map((s) => s.status)).toEqual(['done', 'done', 'done', 'current', 'locked', 'locked'])
  })

  it('the Sign-off step is current once every document is ready', () => {
    const docs = [doc({ path: 'a.md', ready: true }), doc({ path: 'b.md', ready: true })]
    const steps = computeWorkflowSteps(readiness(docs))
    expect(steps.at(-1)).toMatchObject({ kind: 'sign-off', status: 'current' })
  })

  it('the Sign-off step is done once every document is ready AND the stage is already signed off', () => {
    // documentsTab.test.ts's own "signed off" fixture — status: 'signed_off' with a name and a
    // completedAt — is the same shape stage_readiness.py actually reports (readiness.ts reads
    // `raw.sign_off.status` straight through). Before this fix, computeWorkflowSteps never read
    // `readiness.signOff` at all, so this step could only ever be 'current' or 'locked' — never
    // 'done' — even though the Documents tab, reading the very same readiness object, already
    // shows "Signed off by Priya N." for this exact fixture.
    const docs = [doc({ path: 'a.md', ready: true }), doc({ path: 'b.md', ready: true })]
    const steps = computeWorkflowSteps(readiness(docs, {
      ready: true,
      signOff: { status: 'signed_off', signedOffBy: 'Priya N', completedAt: '2026-09-29T00:00:00.000Z' },
    }))
    expect(steps.at(-1)).toMatchObject({ kind: 'sign-off', status: 'done' })
  })

  it('the Sign-off step is locked while any document is not ready', () => {
    const docs = [doc({ path: 'a.md', ready: true }), doc({ path: 'b.md', ready: false })]
    const steps = computeWorkflowSteps(readiness(docs))
    expect(steps.at(-1)).toMatchObject({ kind: 'sign-off', status: 'locked' })
  })

  it('a stage with no required documents still has a current Sign-off step', () => {
    const steps = computeWorkflowSteps(readiness([]))
    expect(steps).toEqual([expect.objectContaining({ kind: 'sign-off', status: 'current' })])
  })

  it('reuses each document\'s own description rather than a second copy of the sentence', () => {
    const docs = [doc({ path: 'a.md', ready: true, description: 'What the fixture is for.' })]
    const steps = computeWorkflowSteps(readiness(docs))
    expect(steps[0].description).toBe('What the fixture is for.')
  })

  describe('done-count parity with the Documents tab (the shared-source acceptance check)', () => {
    const cases: Array<{ name: string; ready: boolean[] }> = [
      { name: 'none ready', ready: [false, false, false] },
      { name: 'all ready', ready: [true, true, true] },
      { name: 'a gap in the middle', ready: [true, false, true, true] },
      { name: 'the single not-ready case', ready: [true, true, false, true, true] },
    ]

    it.each(cases)('$name', ({ ready }) => {
      const docs = ready.map((r, i) => doc({ path: `${i}.md`, ready: r }))
      const steps = computeWorkflowSteps(readiness(docs))
      const stepsDone = steps.filter((s) => s.kind === 'document' && s.status === 'done').length
      const documentsReady = docs.filter((d) => d.ready).length
      expect(stepsDone).toBe(documentsReady)
    })
  })
})
