// @vitest-environment jsdom
/** Settings › Appearance (studio-observatory.md §7 SettingsScreen row). The promises: the four
 * controls are button groups and never an `<input>`; pressing one flips the matching `<html
 * data-*>` attribute and persists the choice under the §2.1 key; the section sits OUTSIDE edit
 * mode, so the project's own editing controls stay absent while a theme is being picked; and the
 * Edit toggle says whether it is pressed. */

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConnectionInfo, ConnectionReport, GateAuthStatus, ProjectSettings, ToolingReport } from '../shared/types'
import { configureMotionForTests } from '../src/motion/motion'
import { SettingsScreen } from '../src/components/SettingsScreen'

const SETTINGS: ProjectSettings = {
  ok: true,
  roster: {
    file: '.sdlc/team.yaml', present: true, errors: [],
    teams: [{ name: 'core', lead: '@priya-n' }],
    people: [{ handle: '@priya-n', name: 'Priya N', team: 'core', roles: ['developer', 'checker'] }],
  },
  wip_limits: { file: '.sdlc/artifacts/03-foundation/cadence-plan.md', present: true, errors: [], teams: [{ team: 'core', wip_limit: 3, in_flight: 1, at_limit: false, over_limit: false }] },
  approval: { file: '.sdlc/approval-settings.yaml', present: false, errors: [], stages: [] },
  fixed_rules: [{ rule: 'Every spec passes the Definition of Ready before hand-off', enforced_by: 'scripts/check_spec.py' }],
}

const CONNECTION: ConnectionInfo = {
  repo: 'acme/claims', branch: 'main', localFolder: '/p', account: 'arjun', accountSource: 'host', rosterHandle: null,
  host: 'github', hostSource: 'remote', cli: { name: 'gh', found: true, extension: null, signedIn: 'yes' },
  lastPulledAt: null, branchProtected: null,
}
const REPORT: ConnectionReport = { ok: true, checks: [], not_universally_expected: {} }
const TOOL = { found: true, path: '/plugin/scripts', version: '2.0.0', pluginVersion: '1.6.2', source: 'sibling' as const }
const TOOLING: ToolingReport = { claude: TOOL, uv: TOOL, pluginScripts: TOOL, git: TOOL, gh: TOOL, az: TOOL }
const GATE_AUTH: GateAuthStatus = { ok: true, repo: 'acme/claims', configured: [], gates_can_sign_in: false, detail: '' }

function install() {
  const studio = {
    getProjectSettings: vi.fn().mockResolvedValue(SETTINGS),
    getConnectionInfo: vi.fn().mockResolvedValue(CONNECTION),
    getConnectionReport: vi.fn().mockResolvedValue(REPORT),
    getScorecard: vi.fn().mockResolvedValue(null),
    detectTooling: vi.fn().mockResolvedValue(TOOLING),
    getGateAuth: vi.fn().mockResolvedValue(GATE_AUTH),
  }
  // @ts-expect-error - test double, not the full StudioApi surface
  window.studio = studio
  return studio
}

const html = () => document.documentElement

beforeEach(() => {
  window.localStorage.clear()
  delete html().dataset.theme
  delete html().dataset.density
  delete html().dataset.motion
  configureMotionForTests(null)
})

afterEach(() => {
  cleanup()
  configureMotionForTests(null)
  // @ts-expect-error - cleaning up the test double
  delete window.studio
})

async function open() {
  install()
  render(<SettingsScreen projectPath="/p" actor="Arjun M" />)
  return within(await screen.findByRole('region', { name: 'Appearance' }))
}

describe('Settings › Build limits: amber stays amber (studio-observatory.md §2.3)', () => {
  it('over limit and a sounding review-wait alarm are warn ink — the same fact reads amber on the Board and the Graph, never refusal red here', async () => {
    const studio = install()
    studio.getProjectSettings.mockResolvedValue({
      ...SETTINGS,
      wip_limits: { ...SETTINGS.wip_limits, teams: [{ team: 'core', wip_limit: 3, in_flight: 4, at_limit: false, over_limit: true }] },
    })
    studio.getScorecard.mockResolvedValue({
      review_wait_median_hours: 52, security_review_wait_median_hours: 9,
      team_alarms: { core: { review_alarm_hours: 48, review_alarm_hours_default: false, review_over_alarm: true, security_alarm_hours: 24, security_alarm_hours_default: true, security_over_alarm: true } },
    })
    render(<SettingsScreen projectPath="/p" actor="Arjun M" />)
    const over = await screen.findByText('over limit')
    expect(over.className).toContain('text-status-warn-ink')
    const review = await screen.findByText(/review-wait alarm sounding \(52h\)/)
    expect(review.className).toContain('text-status-warn-ink')
    const security = screen.getByText(/security-review-wait alarm sounding \(9h\)/)
    expect(security.className).toContain('text-status-warn-ink')
    const limits = screen.getByRole('region', { name: 'Build limits' })
    expect(limits.innerHTML).not.toContain('status-error')
  })
})

describe('Settings › Appearance', () => {
  it('flips data-theme from the Theme control and persists the choice', async () => {
    const appearance = await open()
    fireEvent.click(appearance.getByRole('button', { name: 'Dark' }))
    expect(html().dataset.theme).toBe('dark')
    expect(window.localStorage.getItem('studio.theme')).toBe('dark')
    fireEvent.click(appearance.getByRole('button', { name: 'Light' }))
    expect(html().dataset.theme).toBe('light')
    // System resolves to what the OS says — never the literal word.
    fireEvent.click(appearance.getByRole('button', { name: 'System' }))
    expect(['light', 'dark']).toContain(html().dataset.theme)
    expect(appearance.getByRole('button', { name: 'System' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('flips data-density from the Density control', async () => {
    const appearance = await open()
    fireEvent.click(appearance.getByRole('button', { name: 'Compact' }))
    expect(html().dataset.density).toBe('compact')
    expect(window.localStorage.getItem('studio.density')).toBe('compact')
    fireEvent.click(appearance.getByRole('button', { name: 'Comfortable' }))
    expect(html().dataset.density).toBe('comfortable')
  })

  it('flips data-motion from the Animations control and explains that On is an opt-in', async () => {
    const appearance = await open()
    // Outside MODE=test the preference decides; the seam lets the test see "on" land. Set after
    // the screen mounted so its enter choreography still ran on the stub, not real GSAP in jsdom.
    configureMotionForTests({ isTestMode: () => false })
    fireEvent.click(appearance.getByRole('button', { name: 'Off' }))
    expect(html().dataset.motion).toBe('off')
    expect(window.localStorage.getItem('studio.motion')).toBe('off')
    fireEvent.click(appearance.getByRole('button', { name: 'On' }))
    expect(html().dataset.motion).toBe('on')
    expect(appearance.getByText(/On is an opt-in that overrides it/)).toBeTruthy()
  })

  it('remembers the Visuals default under studio.sprint.surface', async () => {
    const appearance = await open()
    const visuals = appearance.getByRole('group', { name: 'Visuals default' })
    fireEvent.click(within(visuals).getByRole('button', { name: 'Graph' }))
    expect(window.localStorage.getItem('studio.sprint.surface')).toBe('graph')
    fireEvent.click(within(visuals).getByRole('button', { name: 'Table' }))
    expect(window.localStorage.getItem('studio.sprint.surface')).toBe('table')
  })

  it('is made of buttons: no <input> anywhere in the section', async () => {
    const appearance = await open()
    expect(appearance.queryAllByRole('textbox')).toHaveLength(0)
    for (const name of ['Theme', 'Density', 'Motion', 'Visuals default']) {
      const group = appearance.getByRole('group', { name })
      expect(group.querySelectorAll('button[aria-pressed="true"]')).toHaveLength(1)
    }
  })
})

describe('Settings: edit mode and the pinned facts', () => {
  it('keeps the project controls ABSENT until Edit is pressed, and Edit says so with aria-pressed', async () => {
    install()
    render(<SettingsScreen projectPath="/p" actor="Arjun M" />)
    await screen.findByRole('region', { name: 'Appearance' })
    const edit = screen.getByRole('button', { name: 'Edit' })
    expect(edit.getAttribute('aria-pressed')).toBe('false')
    expect(screen.queryByLabelText('limit')).toBeNull()
    fireEvent.click(edit)
    const done = screen.getByRole('button', { name: 'Done editing' })
    expect(done.getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByLabelText('limit')).toBeTruthy()
    fireEvent.click(done)
    expect(screen.queryByLabelText('limit')).toBeNull()
  })

  it('still states which Claude Code and which plugin this session runs', async () => {
    install()
    render(<SettingsScreen projectPath="/p" actor="Arjun M" />)
    const facts = await screen.findByTestId('tooling-facts')
    expect(facts.textContent).toContain('2.0.0 — accepts every flag Shepherd uses')
    expect(facts.textContent).toContain('version 1.6.2, from the checkout beside Shepherd')
  })
})
