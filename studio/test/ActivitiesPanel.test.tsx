// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ActivitiesPanel } from '../src/components/ActivitiesPanel'
import type { ActivityCheckResult, StageActivity, StageReadiness, StartActivityResult } from '../shared/types'
import { activity, readinessWith } from './activityFixtures'

const DATA_FILES = [
  '.sdlc/artifacts/02-design/data/data-contract.md',
  '.sdlc/artifacts/02-design/data/data-readiness.md',
  '.sdlc/artifacts/02-design/data/lineage-audit.md',
]

function install(overrides: Record<string, unknown> = {}) {
  const studio = {
    startActivity: vi.fn(),
    runActivityCheck: vi.fn(),
    ...overrides,
  }
  // @ts-expect-error - test double, not the full StudioApi surface
  window.studio = studio
  return studio
}

afterEach(() => {
  // @ts-expect-error - cleaning up the test double
  delete window.studio
})

function draw(activities: StageActivity[], over: Partial<StageReadiness> = {}) {
  const onOpenDocument = vi.fn()
  const onRefresh = vi.fn().mockResolvedValue(undefined)
  const readiness = readinessWith({ capabilities: ['activities', 'rules-check', 'data-contract-summary'], activities, ...over })
  render(<ActivitiesPanel projectPath="/p" readiness={readiness} onOpenDocument={onOpenDocument} onRefresh={onRefresh} />)
  return { onOpenDocument, onRefresh }
}

const row = (id: string) => document.querySelector(`[data-activity-id="${id}"]`) as HTMLElement

describe('ActivitiesPanel: which rows are drawn', () => {
  it('draws create, talk and the two named checks in declared order, and never run or draft', () => {
    draw([
      activity({ id: 'talk', kind: 'talk', label: 'Talk' }),
      activity({ id: 'analysis', kind: 'run', label: 'Analysis' }),
      activity({ id: 'data-check', kind: 'check', label: 'Data check' }),
      activity({ id: 'some-draft', kind: 'draft', label: 'Some draft' }),
      activity({ id: 'data', kind: 'create', label: 'Data' }),
      activity({ id: 'rules-check', kind: 'check', label: 'Rules check' }),
    ])
    expect(screen.getByRole('heading', { name: 'Also in this stage' })).toBeTruthy()
    const ids = screen.getAllByTestId('activity-row').map((r) => r.getAttribute('data-activity-id'))
    expect(ids).toEqual(['talk', 'data-check', 'data', 'rules-check'])
  })

  it('draws nothing at all, not even the heading, for an older plugin with no activities key', () => {
    render(<ActivitiesPanel projectPath="/p" readiness={readinessWith({})} onOpenDocument={vi.fn()} />)
    expect(screen.queryByTestId('activities-panel')).toBeNull()
    expect(screen.queryByText('Also in this stage')).toBeNull()
  })

  it('draws nothing when every declared activity is a kind Studio has no control for', () => {
    draw([activity({ id: 'analysis', kind: 'run' }), activity({ id: 'some-draft', kind: 'draft' })])
    expect(screen.queryByText('Also in this stage')).toBeNull()
  })
})

describe("ActivitiesPanel: the plugin's status", () => {
  it('reads Done for done, with no control', () => {
    draw([activity({ id: 'data', kind: 'create', label: 'Data', status: 'done' })])
    expect(within(row('data')).getByText('Done')).toBeTruthy()
    expect(within(row('data')).queryByRole('button')).toBeNull()
  })

  it("shows a blocked activity's own reason, unchanged, and no enabled control", () => {
    const reason = 'Needs the requirements to be started first.'
    draw([activity({ id: 'rules-check', kind: 'check', status: 'blocked', reason })])
    expect(within(row('rules-check')).getByText(reason)).toBeTruthy()
    const buttons = within(row('rules-check')).queryAllByRole('button')
    expect(buttons.filter((b) => !b.hasAttribute('disabled'))).toHaveLength(0)
  })

  it('enables the control of an available activity', () => {
    draw([activity({ id: 'rules-check', kind: 'check' })])
    expect(within(row('rules-check')).getByRole('button', { name: 'Check rules' }).hasAttribute('disabled')).toBe(false)
  })

  it('shows a control disabled with a visible reason when the plugin lacks its capability', () => {
    draw([activity({ id: 'rules-check', kind: 'check' })], { capabilities: ['activities'] })
    const button = within(row('rules-check')).getByRole('button', { name: 'Check rules' })
    expect(button.hasAttribute('disabled')).toBe(true)
    expect(within(row('rules-check')).getByText('needs a newer plugin: lacks rules-check')).toBeTruthy()
  })
})

describe('ActivitiesPanel: warnings', () => {
  it('shows one plain warning line under the heading while the rows still draw', () => {
    draw([activity({ id: 'data', kind: 'create', label: 'Data' })], { warnings: ['activities.yaml: stage "9" is unknown.'] })
    expect(screen.getByTestId('activities-warning').textContent).toBe('activities.yaml: stage "9" is unknown.')
    expect(screen.getByRole('heading', { name: 'Also in this stage' })).toBeTruthy()
    expect(screen.getAllByTestId('activity-row')).toHaveLength(1)
  })

  it('shows the warning even when the broken declaration left no rows', () => {
    draw([], { warnings: ['activities.yaml could not be read.'] })
    expect(screen.getByRole('heading', { name: 'Also in this stage' })).toBeTruthy()
    expect(screen.getByTestId('activities-warning')).toBeTruthy()
  })
})

describe('ActivitiesPanel: Create', () => {
  const createRow = () => activity({ id: 'data', kind: 'create', label: 'Data contract', creates: DATA_FILES })

  it('starts the activity, opens the first file, reports what it did, and refreshes readiness', async () => {
    const result: StartActivityResult = { ok: true, created: DATA_FILES, existing: [], opened: DATA_FILES[0] }
    const studio = install({ startActivity: vi.fn().mockResolvedValue(result) })
    const { onOpenDocument, onRefresh } = draw([createRow()])

    fireEvent.click(within(row('data')).getByRole('button', { name: 'Create' }))

    await waitFor(() => expect(onOpenDocument).toHaveBeenCalledWith(DATA_FILES[0]))
    expect(studio.startActivity).toHaveBeenCalledWith('/p', '1', 'data')
    expect(onRefresh).toHaveBeenCalledTimes(1)
    const line = screen.getByTestId('activity-result').textContent
    expect(line).toContain('Started 3 documents')
    expect(line).toContain('data-contract.md')
    expect(line).not.toContain('.sdlc/artifacts')
  })

  it('says plainly when one document already existed and was left as it was', async () => {
    install({
      startActivity: vi.fn().mockResolvedValue({
        ok: true, created: DATA_FILES.slice(1), existing: [DATA_FILES[0]], opened: DATA_FILES[1],
      } satisfies StartActivityResult),
    })
    draw([createRow()])
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))
    const line = await screen.findByTestId('activity-result')
    expect(line.textContent).toContain('Started 2 documents')
    expect(line.textContent).toContain('1 already existed and was left as it was')
    expect(line.textContent).toContain('data-contract.md')
  })

  it('shows one error line, and opens nothing, when starting fails', async () => {
    install({ startActivity: vi.fn().mockResolvedValue({ ok: false, created: [], existing: [], error: 'That path is outside the project.' }) })
    const { onOpenDocument, onRefresh } = draw([createRow()])
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))
    expect((await screen.findByRole('alert')).textContent).toBe('That path is outside the project.')
    expect(onOpenDocument).not.toHaveBeenCalled()
    expect(onRefresh).not.toHaveBeenCalled()
  })

  it('shows one error line when the call itself rejects', async () => {
    install({ startActivity: vi.fn().mockRejectedValue(new Error('IPC went away')) })
    draw([createRow()])
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))
    expect((await screen.findByRole('alert')).textContent).toBe('IPC went away')
  })
})

describe('ActivitiesPanel: Check rules', () => {
  const rules = (over: Record<string, unknown>): ActivityCheckResult =>
    ({ ok: true, check: 'rules-check', hasData: true, notes: [], findings: [], ...over }) as ActivityCheckResult

  async function runRules(result: ActivityCheckResult) {
    const studio = install({ runActivityCheck: vi.fn().mockResolvedValue(result) })
    draw([activity({ id: 'rules-check', kind: 'check' })])
    fireEvent.click(screen.getByRole('button', { name: 'Check rules' }))
    await screen.findByTestId('activity-result')
    return studio
  }

  it('runs the check for this project and activity', async () => {
    const studio = await runRules(rules({}))
    expect(studio.runActivityCheck).toHaveBeenCalledWith('/p', 'rules-check')
  })

  it("shows each finding's message with its subject", async () => {
    await runRules(rules({ findings: [
      { subject: 'BR-02', message: 'has no owner.' },
      { subject: 'BR-05', message: 'contradicts BR-01.' },
    ] }))
    const text = screen.getByTestId('activity-result').textContent
    expect(text).toContain('BR-02 has no owner.')
    expect(text).toContain('BR-05 contradicts BR-01.')
    expect(text).not.toContain('No problems found')
  })

  it('offers to open the business rules once the check had something to read, and not before', async () => {
    install({ runActivityCheck: vi.fn().mockResolvedValue(rules({})) })
    const { onOpenDocument } = draw([activity({ id: 'rules-check', kind: 'check' })])
    expect(screen.queryByRole('button', { name: 'Open business-rules.md' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Check rules' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Open business-rules.md' }))
    expect(onOpenDocument).toHaveBeenCalledWith('.sdlc/artifacts/01-requirements/business-rules.md')
  })

  it('offers no link when there was nothing to check', async () => {
    await runRules(rules({ hasData: false, notes: ['no rules yet.'] }))
    expect(screen.queryByRole('button', { name: 'Open business-rules.md' })).toBeNull()
  })

  it('reads "No problems found" for zero findings on a table that has rules', async () => {
    await runRules(rules({}))
    expect(screen.getByTestId('activity-result').textContent).toBe('No problems found')
  })

  it("reads \"Nothing to check yet\" with the plugin's note, never \"No problems found\", when there is no data", async () => {
    await runRules(rules({ hasData: false, notes: ['business-rules.md has no rules yet.'] }))
    const text = screen.getByTestId('activity-result').textContent ?? ''
    expect(text).toContain('Nothing to check yet')
    expect(text).toContain('business-rules.md has no rules yet.')
    expect(text).not.toContain('No problems found')
  })
})

describe('ActivitiesPanel: Check personal data', () => {
  const data = (over: Record<string, unknown>): ActivityCheckResult => ({
    ok: true, check: 'data-check', hasData: true, notes: [], fieldCount: 0, piiCount: 0, piiFields: [], riskImplication: null, ...over,
  }) as ActivityCheckResult

  async function runData(result: ActivityCheckResult) {
    const studio = install({ runActivityCheck: vi.fn().mockResolvedValue(result) })
    draw([activity({ id: 'data-check', kind: 'check' })])
    fireEvent.click(screen.getByRole('button', { name: 'Check personal data' }))
    await screen.findByTestId('activity-result')
    return studio
  }

  it('shows the field count, the personal-data count with the names, and the risk sentence', async () => {
    await runData(data({
      fieldCount: 12, piiCount: 2, piiFields: ['email', 'date_of_birth'],
      riskImplication: 'Personal data raises this spec to HIGH risk.',
    }))
    const text = screen.getByTestId('activity-result').textContent
    expect(text).toContain('2 of 12 fields hold personal data')
    expect(text).toContain('email, date_of_birth')
    expect(text).toContain('Personal data raises this spec to HIGH risk.')
  })

  it('omits the risk sentence when the plugin returns none', async () => {
    await runData(data({ fieldCount: 4, piiCount: 0 }))
    expect(screen.getByTestId('activity-result').textContent).toBe('None of the 4 fields hold personal data.')
  })

  it('reads "Nothing to check yet", never "0 personal data fields", when has_data is false', async () => {
    await runData(data({ hasData: false, notes: ['data-contract.md has no fields yet.'] }))
    const text = screen.getByTestId('activity-result').textContent ?? ''
    expect(text).toContain('Nothing to check yet')
    expect(text).toContain('data-contract.md has no fields yet.')
    expect(text).not.toMatch(/\b0\b/)
    expect(text).not.toMatch(/personal data field/i)
  })
})

describe('ActivitiesPanel: a check that fails shows one error line and no count', () => {
  const failures: Array<[string, string]> = [
    ['the script is missing', 'rules_check.py was not found in the plugin.'],
    ['the script exits with code 1', 'The check stopped with an error: bad table.'],
    ['the script prints something that is not one JSON document', 'The check printed something Shepherd could not read.'],
  ]

  it.each(failures)('when %s', async (_name, error) => {
    install({ runActivityCheck: vi.fn().mockResolvedValue({ ok: false, error } satisfies ActivityCheckResult) })
    draw([activity({ id: 'rules-check', kind: 'check', label: 'Rules' })])
    fireEvent.click(screen.getByRole('button', { name: 'Check rules' }))
    await screen.findByRole('alert')

    const lines = within(row('rules-check')).getAllByRole('alert')
    expect(lines).toHaveLength(1)
    expect(lines[0].textContent).toBe(error)
    expect(row('rules-check').textContent).not.toMatch(/\d/)
    expect(screen.queryByTestId('activity-result')).toBeNull()
  })

  it('also when the call itself rejects', async () => {
    install({ runActivityCheck: vi.fn().mockRejectedValue(new Error('The check could not run.')) })
    draw([activity({ id: 'data-check', kind: 'check', label: 'Data' })])
    fireEvent.click(screen.getByRole('button', { name: 'Check personal data' }))
    expect((await screen.findByRole('alert')).textContent).toBe('The check could not run.')
  })
})
