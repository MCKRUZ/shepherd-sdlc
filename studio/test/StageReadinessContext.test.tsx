// @vitest-environment jsdom
//
// StageReadinessProvider's `refresh()` has no ordering guarantee against the
// `window.studio.getStageReadiness` subprocess calls it makes — two independent calls can
// resolve in either order. Without a stale-response guard, switching from stage A to stage B
// before A's call resolves — and having A's reply arrive AFTER B's — would let
// `setReadiness(resultForA)` silently overwrite the correct `resultForB`, for every consumer
// that reads this context (sidebar, StageHome, eventually ChatPanel). This is the same class of
// bug ChatPanel.tsx guards against today ("a stale reply for a stage the person already
// navigated away from") and the `useCurrentStageDocs` hook spec 0019 removed guarded with its
// own `cancelled` flag.

import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StageReadinessProvider, useStageReadiness } from '../src/components/StageReadinessContext'
import type { StageReadiness } from '../shared/types'

function readinessStub(stageId: string): StageReadiness {
  return {
    ok: true,
    stageId,
    name: `stage-${stageId}`,
    display: `Phase ${stageId}`,
    isCurrent: false,
    documents: [],
    findings: [],
    judgement: [],
    signOff: { status: 'pending', signedOffBy: null, completedAt: null },
    ready: true,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => { resolve = res })
  return { promise, resolve }
}

function Consumer() {
  const { readiness, loading } = useStageReadiness()
  return <div data-testid="readiness">{loading && !readiness ? 'loading' : (readiness?.stageId ?? 'none')}</div>
}

afterEach(() => {
  // @ts-expect-error - cleaning up the test double between tests
  delete window.studio
})

describe('StageReadinessProvider.refresh() stale-response guard', () => {
  it('the LATER-requested stage\'s data wins even when its reply resolves BEFORE the earlier stage\'s', async () => {
    const forA = deferred<StageReadiness>()
    const forB = deferred<StageReadiness>()
    const getStageReadiness = vi.fn()
      .mockImplementationOnce(() => forA.promise)
      .mockImplementationOnce(() => forB.promise)
    // @ts-expect-error - test double, not the full StudioApi surface
    window.studio = { getStageReadiness }

    const { rerender } = render(
      <StageReadinessProvider projectPath="/p" stageId="A"><Consumer /></StageReadinessProvider>,
    )
    await waitFor(() => expect(getStageReadiness).toHaveBeenCalledTimes(1))

    // Navigate to stage B before A's fetch has resolved at all.
    rerender(
      <StageReadinessProvider projectPath="/p" stageId="B"><Consumer /></StageReadinessProvider>,
    )
    await waitFor(() => expect(getStageReadiness).toHaveBeenCalledTimes(2))

    // B's reply arrives FIRST ...
    forB.resolve(readinessStub('B'))
    await waitFor(() => expect(screen.getByTestId('readiness').textContent).toBe('B'))

    // ... then A's stale reply arrives SECOND. It must never overwrite B's correct data.
    forA.resolve(readinessStub('A'))
    await new Promise((r) => setTimeout(r, 0))
    expect(screen.getByTestId('readiness').textContent).toBe('B')
  })
})
