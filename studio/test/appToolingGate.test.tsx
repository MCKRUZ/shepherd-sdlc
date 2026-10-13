// @vitest-environment jsdom
/** App's tooling gate after code-host providers (D4, code-host-providers.md §7 App.tsx row): a
 * missing gh or az never routes to the tooling-issues screen — a project opens without either —
 * while a missing REQUIRED tool (claude, uv, plugin scripts, git) still does. */
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ToolingReport } from '../shared/types'
import { configureMotionForTests } from '../src/motion/motion'
import App from '../src/App'

const FOUND = { found: true, path: '/usr/local/bin/x', version: '1.0.0' }
const MISSING = { found: false, error: 'not on PATH' }
const ALL_FOUND: ToolingReport = { claude: FOUND, uv: FOUND, pluginScripts: FOUND, git: FOUND, gh: FOUND, az: FOUND }

function install(report: ToolingReport) {
  const studio = {
    detectTooling: vi.fn().mockResolvedValue(report),
    getSettings: vi.fn().mockResolvedValue({ recentProjects: [] }),
    getConsoleLog: vi.fn().mockResolvedValue([]),
    onConsoleEntry: vi.fn().mockReturnValue(() => {}),
    onSyncState: vi.fn().mockReturnValue(() => {}),
  }
  // @ts-expect-error - test double, not the full StudioApi surface
  window.studio = studio
  return studio
}

beforeEach(() => configureMotionForTests(null))
afterEach(() => {
  cleanup()
  configureMotionForTests(null)
  // @ts-expect-error - cleaning up the test double
  delete window.studio
})

const TOOLING_HEADING = 'Before Shepherd can open a project'

describe('App tooling gate: gh and az never block', () => {
  it('gh AND az both missing → the Welcome screen, not the tooling-issues screen', async () => {
    const studio = install({ ...ALL_FOUND, gh: MISSING, az: MISSING })
    render(<App />)
    await waitFor(() => expect(screen.queryByText('Loading…')).toBeNull())
    expect(screen.queryByRole('heading', { name: TOOLING_HEADING })).toBeNull()
    // The welcome path is the one that reads the recent projects; the gate path never does.
    await waitFor(() => expect(studio.getSettings).toHaveBeenCalled())
  })

  it('a required tool missing (git) → the tooling-issues screen, with both sections', async () => {
    const studio = install({ ...ALL_FOUND, git: MISSING })
    render(<App />)
    expect(await screen.findByRole('heading', { name: TOOLING_HEADING })).toBeTruthy()
    expect(screen.getByRole('heading', { level: 2, name: 'Required' })).toBeTruthy()
    expect(screen.getByRole('heading', { level: 2, name: 'Code-host CLIs' })).toBeTruthy()
    expect(screen.getByText("git wasn't found.")).toBeTruthy()
    expect(studio.getSettings).not.toHaveBeenCalled()
  })
})
