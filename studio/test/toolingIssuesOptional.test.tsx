// @vitest-environment jsdom
/** ToolingIssues after code-host providers (code-host-providers.md §7): two sections — Required
 * (the four tools a project cannot open without, wording unchanged) and Code-host CLIs (gh and az,
 * facts with override inputs, never blocking) — and the §7.1 "no project open" sentence from
 * WORDING, never hand-typed. */
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ToolingReport } from '../shared/types'
import { WORDING } from '../shared/codeHostModel'
import { configureMotionForTests } from '../src/motion/motion'
import { CODE_HOST_CLIS, REQUIRED_TOOLS, ToolingIssues } from '../src/components/ToolingIssues'

const FOUND = { found: true, path: '/usr/local/bin/x', version: '1.0.0' }
const MISSING = { found: false, error: 'not on PATH' }

const REPORT: ToolingReport = { claude: FOUND, uv: FOUND, pluginScripts: FOUND, git: MISSING, gh: MISSING, az: MISSING }

beforeEach(() => configureMotionForTests(null))
afterEach(() => { cleanup(); configureMotionForTests(null) })

describe('ToolingIssues: Required and Code-host CLIs are two sections', () => {
  it('names the two sections under the product heading', () => {
    render(<ToolingIssues report={REPORT} onOverride={vi.fn()} />)
    expect(screen.getByRole('heading', { level: 1, name: 'Before Shepherd can open a project' })).toBeTruthy()
    expect(screen.getByRole('heading', { level: 2, name: 'Required' })).toBeTruthy()
    expect(screen.getByRole('heading', { level: 2, name: 'Code-host CLIs' })).toBeTruthy()
  })

  it('only the required tools count as issues; gh and az are never among them', () => {
    expect([...REQUIRED_TOOLS]).toEqual(['claude', 'uv', 'pluginScripts', 'git'])
    expect([...CODE_HOST_CLIS]).toEqual(['gh', 'az'])
    render(<ToolingIssues report={REPORT} onOverride={vi.fn()} />)
    const required = screen.getByRole('heading', { level: 2, name: 'Required' }).closest('section')!
    // The required wording is the existing one; the code-host CLIs do not appear here.
    expect(within(required).getByText("git wasn't found.")).toBeTruthy()
    expect(within(required).queryByText(/Azure CLI|GitHub CLI/)).toBeNull()
  })

  it('the az row: label, not-found fact, aka.ms install link, and the §7.1 sentence from WORDING', () => {
    render(<ToolingIssues report={REPORT} onOverride={vi.fn()} />)
    expect(screen.getByText(WORDING.noProject)).toBeTruthy()
    const az = within(screen.getByTestId('cli-az'))
    expect(az.getByText('the Azure CLI (az)')).toBeTruthy()
    expect(az.getByText(/not found/)).toBeTruthy()
    expect(az.getByRole('link', { name: /Install instructions/ }).getAttribute('href')).toBe('https://aka.ms/azure-cli')
    const gh = within(screen.getByTestId('cli-gh'))
    expect(gh.getByText('the GitHub CLI (gh)')).toBeTruthy()
  })

  it('a found CLI reads as a fact with its path and offers no override', () => {
    render(<ToolingIssues report={{ ...REPORT, az: FOUND }} onOverride={vi.fn()} />)
    const az = within(screen.getByTestId('cli-az'))
    expect(az.getByText('/usr/local/bin/x')).toBeTruthy()
    expect(az.queryByRole('button', { name: 'Use this' })).toBeNull()
  })

  it('"Use this" on the az row calls onOverride with kind az (the typed path, trimmed)', () => {
    const onOverride = vi.fn()
    render(<ToolingIssues report={REPORT} onOverride={onOverride} />)
    const az = within(screen.getByTestId('cli-az'))
    const use = az.getByRole('button', { name: 'Use this' })
    expect((use as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(az.getByPlaceholderText('Path to the binary'), { target: { value: ' /opt/az ' } })
    fireEvent.click(use)
    expect(onOverride).toHaveBeenCalledWith('az', '/opt/az')
  })
})
