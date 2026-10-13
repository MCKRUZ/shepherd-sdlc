// @vitest-environment jsdom
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { GuideTab } from '../src/components/GuideTab'
import type { StageGuide } from '../shared/types'
import { activity, readinessWith } from './activityFixtures'

function install(getStageGuide: (definition: string) => Promise<StageGuide>) {
  const studio = { getStageGuide: vi.fn(getStageGuide) }
  // @ts-expect-error - test double, not the full StudioApi surface
  window.studio = studio
  return studio
}

afterEach(() => {
  // @ts-expect-error - cleaning up the test double
  delete window.studio
})

const ACTIVITIES = [
  activity({ id: 'data', kind: 'create', label: 'Data contract', command: 'sprd-data' }),
  activity({ id: 'intake', kind: 'run', label: 'Read the documents', command: 'sprd-intake' }),
  activity({ id: 'brief', kind: 'draft', label: 'Brief', command: null }),
]

describe('GuideTab', () => {
  it('reads the stage definition and draws it as markdown', async () => {
    const studio = install(async () => ({ ok: true, markdown: '# Requirements\n\nWrite the **requirements**.' }))
    render(<GuideTab readiness={readinessWith({ definition: 'phases/01-requirements.md' })} />)
    expect(await screen.findByText('Requirements')).toBeTruthy()
    expect(screen.getByText('requirements').tagName).toBe('STRONG')
    expect(studio.getStageGuide).toHaveBeenCalledWith('phases/01-requirements.md')
  })

  it('lists every declared activity, including kinds the Workflow tab does not draw, with its command', async () => {
    install(async () => ({ ok: true, markdown: 'text' }))
    render(<GuideTab readiness={readinessWith({ definition: 'phases/x.md', activities: ACTIVITIES })} />)
    const items = await screen.findAllByTestId('guide-activity')
    expect(items.map((i) => i.getAttribute('data-activity-id'))).toEqual(['data', 'intake', 'brief'])
    expect(items[0].textContent).toBe('Data contract /sprd-data')
    expect(items[1].textContent).toBe('Read the documents /sprd-intake')
    expect(items[2].textContent).toBe('Brief')
  })

  it('says there is no guidance file, without asking the plugin, when there is no definition', () => {
    const studio = install(async () => ({ ok: true, markdown: 'never' }))
    render(<GuideTab readiness={readinessWith({ definition: null })} />)
    expect(screen.getByText('No guidance file for this stage')).toBeTruthy()
    expect(studio.getStageGuide).not.toHaveBeenCalled()
  })

  it('says the same when the definition key is absent (an older plugin)', () => {
    install(async () => ({ ok: true, markdown: 'never' }))
    render(<GuideTab readiness={readinessWith({})} />)
    expect(screen.getByText('No guidance file for this stage')).toBeTruthy()
  })

  it('says the same when the file cannot be read', async () => {
    install(async () => ({ ok: false, error: 'ENOENT' }))
    render(<GuideTab readiness={readinessWith({ definition: 'phases/gone.md' })} />)
    expect(await screen.findByText('No guidance file for this stage')).toBeTruthy()
    expect(screen.queryByText('ENOENT')).toBeNull()
  })

  it('says the same when the call itself rejects', async () => {
    install(() => Promise.reject(new Error('IPC went away')))
    render(<GuideTab readiness={readinessWith({ definition: 'phases/x.md' })} />)
    expect(await screen.findByText('No guidance file for this stage')).toBeTruthy()
  })

  it('never shows the previous stage text under the next stage when a slow reply lands late', async () => {
    let finishFirst: (g: StageGuide) => void = () => {}
    install((definition) => definition === 'phases/a.md'
      ? new Promise<StageGuide>((resolve) => { finishFirst = resolve })
      : Promise.resolve({ ok: true, markdown: 'Stage B text' }))
    const { rerender } = render(<GuideTab readiness={readinessWith({ definition: 'phases/a.md' })} />)
    rerender(<GuideTab readiness={readinessWith({ definition: 'phases/b.md' })} />)
    expect(await screen.findByText('Stage B text')).toBeTruthy()

    finishFirst({ ok: true, markdown: 'Stage A text' })
    await new Promise((r) => setTimeout(r, 0))
    expect(screen.queryByText('Stage A text')).toBeNull()
    expect(screen.getByText('Stage B text')).toBeTruthy()
  })

  it('shows loading, not the previous stage, while the next stage is still being read', async () => {
    install((definition) => definition === 'phases/a.md'
      ? Promise.resolve({ ok: true, markdown: 'Stage A text' })
      : new Promise<StageGuide>(() => {}))
    const { rerender } = render(<GuideTab readiness={readinessWith({ definition: 'phases/a.md' })} />)
    await screen.findByText('Stage A text')
    rerender(<GuideTab readiness={readinessWith({ definition: 'phases/b.md' })} />)
    await waitFor(() => expect(screen.queryByText('Stage A text')).toBeNull())
    expect(screen.getByText('Reading the guidance…')).toBeTruthy()
  })
})
