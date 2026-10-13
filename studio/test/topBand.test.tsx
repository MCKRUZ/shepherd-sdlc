// @vitest-environment jsdom
/** The top band (togo-command-center.md §1, §7 P4): the one `<h1>` (the project), the omnibar
 * trigger as a `<button>` whose name starts "Search" (never an `<input>` at rest), the needs-you
 * chip as a list LENGTH (words at zero, disabled with its reason without an actor, never a 0),
 * Console with `aria-pressed`, Appearance as a disclosure over the preference toggles, Settings
 * carrying `aria-current` on its screen with its name as text, and the `…` menu. */
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ProjectStatus } from '../shared/types'
import { NOTHING_NEEDS_YOU, SIGN_IN_TO_SEE } from '../shared/reasons'
import { TopBand, OMNIBAR_LABEL, type TopBandProps } from '../src/components/TopBand'
import { overflowRows } from '../src/components/OverflowMenu'

const STATUS: ProjectStatus = {
  project_name: 'acme-claims', profile_id: 'microsoft-enterprise', current_phase: { id: '3', display: 'Phase 3' },
  stages: [{ id: '3', name: 'foundation', display: 'Phase 3: Foundation', status: 'current', stage_state: 'current', artifact_count: 0, entered_at: null, completed_at: null, signed_off_by: null }],
}

function mount(over: Partial<TopBandProps> = {}) {
  const props: TopBandProps = {
    status: STATUS, syncState: { kind: 'idle', lastPulledAt: null }, area: 'documents', consoleOpen: false,
    onToggleConsole: vi.fn(), onOpenPalette: vi.fn(), onNavigate: vi.fn(), home: 'lifecycle', currentStageId: '3',
    overflow: { toggleChat: vi.fn(), openShortcuts: vi.fn(), steering: vi.fn(), newProject: vi.fn(), openFolder: vi.fn() },
    ...over,
  }
  const utils = render(<TopBand {...props} />)
  return { ...utils, props }
}

afterEach(cleanup)

describe('TopBand', () => {
  it('names the project in the one h1, with the product spoken before it; the button leans to the lifecycle home', () => {
    const { props } = mount()
    const h1 = screen.getByRole('heading', { level: 1 })
    expect(h1.textContent).toBe('Shepherd · acme-claims')
    fireEvent.click(within(h1).getByRole('button'))
    expect(props.onNavigate).toHaveBeenCalledWith({ area: 'documents', stageId: '3' })
    expect(document.querySelectorAll('input')).toHaveLength(0)
  })

  it('the omnibar trigger is a button named from "Search", carrying ⌘K and the invitation, and opens the palette', () => {
    const { props } = mount()
    const trigger = screen.getByRole('button', { name: /^Search/ })
    expect(trigger.getAttribute('aria-label')).toBe(OMNIBAR_LABEL)
    expect(trigger.textContent).toContain('a spec id, a verb, or a place')
    expect(trigger.querySelector('kbd')).not.toBeNull()
    fireEvent.click(trigger)
    expect(props.onOpenPalette).toHaveBeenCalledTimes(1)
  })

  it('Console carries aria-pressed; Settings carries aria-current on its screen and its name is its text', () => {
    const { props, unmount } = mount({ consoleOpen: true })
    const consoleButton = screen.getByRole('button', { name: 'Console' })
    expect(consoleButton.getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(consoleButton)
    expect(props.onToggleConsole).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('button', { name: 'Settings' }).hasAttribute('aria-current')).toBe(false)
    unmount()
    const onSettings = mount({ area: 'settings' })
    const settings = screen.getByRole('button', { name: 'Settings' })
    expect(settings.getAttribute('aria-current')).toBe('page')
    expect(settings.textContent).toBe('Settings')
    fireEvent.click(settings)
    expect(onSettings.props.onNavigate).toHaveBeenCalledWith({ area: 'settings' })
  })

  it('Appearance is a disclosure over the three preference toggles — buttons with aria-pressed, no input', () => {
    mount()
    const appearance = screen.getByRole('button', { name: 'Appearance' })
    expect(appearance.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(appearance)
    expect(appearance.getAttribute('aria-expanded')).toBe('true')
    const theme = screen.getByRole('group', { name: 'Theme' })
    expect(theme.querySelectorAll('button[aria-pressed="true"]')).toHaveLength(1)
    expect(document.querySelectorAll('input')).toHaveLength(0)
    fireEvent.keyDown(appearance, { key: 'Escape' })
    expect(appearance.getAttribute('aria-expanded')).toBe('false')
  })

  it('the needs-you chip: absent before the read, the length when addressed, words at zero, disabled with the reason without an actor', () => {
    const none = mount({ needsYou: null })
    expect(document.querySelector('[data-needs-you]')).toBeNull()
    none.unmount()
    const three = mount({ needsYou: { count: 3, reason: null }, home: 'sprint' })
    const chip = document.querySelector('[data-needs-you]') as HTMLButtonElement
    expect(chip.textContent).toContain('needs you')
    expect(chip.querySelector('[data-stat]')?.textContent).toBe('3')
    fireEvent.click(chip)
    expect(three.props.onNavigate).toHaveBeenCalledWith({ area: 'sprint' })
    three.unmount()
    mount({ needsYou: { count: 0, reason: null } })
    const zero = document.querySelector('[data-needs-you]') as HTMLButtonElement
    expect(zero.textContent).toContain(NOTHING_NEEDS_YOU)
    expect(zero.textContent).not.toMatch(/\d/)
    cleanup()
    mount({ needsYou: { count: 0, reason: SIGN_IN_TO_SEE } })
    const gated = document.querySelector('[data-needs-you]') as HTMLButtonElement
    expect(gated.disabled).toBe(true)
    expect(gated.getAttribute('title')).toBe(SIGN_IN_TO_SEE)
    expect(gated.querySelector('[data-disabled-reason]')?.textContent).toBe(SIGN_IN_TO_SEE)
  })

  it('the … menu lists the project-wide rows as menuitems, runs one, and closes on Escape', () => {
    const { props } = mount()
    const more = screen.getByRole('button', { name: 'More' })
    expect(more.getAttribute('aria-haspopup')).toBe('menu')
    expect(screen.queryByRole('menu')).toBeNull()
    fireEvent.click(more)
    const menu = screen.getByRole('menu')
    expect(within(menu).getAllByRole('menuitem')).toHaveLength(5)
    for (const name of [/^Chat/, /^Keyboard shortcuts/, /^Steering mode/, /^New project…/, /^Open folder…/]) expect(within(menu).getByRole('menuitem', { name })).toBeTruthy()
    fireEvent.click(within(screen.getByRole('menu')).getByRole('menuitem', { name: /Steering mode/ }))
    expect(props.overflow.steering).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('menu')).toBeNull()
    fireEvent.click(more)
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' })
    expect(screen.queryByRole('menu')).toBeNull()
    // Rows the host did not pass are absent, never inert.
    expect(overflowRows({ toggleChat: vi.fn() }).map((r) => r.id)).toEqual(['chat'])
  })
})

describe('TopBand in steering mode (fixer round)', () => {
  it('the presentation variant keeps the one h1 and offers only "Leave steering (Esc)" — no omnibar, no needs-you chip, no console, no settings, no menu', () => {
    const onLeave = vi.fn()
    mount({ presentation: { onLeave }, needsYou: { count: 1, reason: null } })
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Shepherd · acme-claims')
    expect(document.querySelector('[data-topband][data-presentation]')).not.toBeNull()
    expect(screen.queryByRole('button', { name: /^Search/ })).toBeNull()
    expect(screen.queryByTestId('needs-you-chip')).toBeNull()
    for (const name of ['Console', 'Settings', 'Appearance', 'More']) expect(screen.queryByRole('button', { name })).toBeNull()
    expect(document.querySelectorAll('input')).toHaveLength(0)
    expect(document.querySelectorAll('button[data-write]')).toHaveLength(0)
    const leave = screen.getByRole('button', { name: 'Leave steering (Esc)' })
    expect(screen.getAllByRole('button')).toHaveLength(1)
    fireEvent.click(leave)
    expect(onLeave).toHaveBeenCalledTimes(1)
  })
})

describe('TopBand — the Chat toggle (owner\'s v12 item 1)', () => {
  it('is a band control with aria-pressed mirroring the aside, named by its text, and absent when the shell passes no toggle', () => {
    const onToggleChat = vi.fn()
    const open = mount({ chatOpen: true, onToggleChat })
    const chat = screen.getByRole('button', { name: 'Chat' })
    expect(chat.getAttribute('aria-pressed')).toBe('true')
    expect(chat.textContent).toBe('Chat')
    fireEvent.click(chat)
    expect(onToggleChat).toHaveBeenCalledTimes(1)
    open.unmount()
    mount({ chatOpen: false, onToggleChat })
    expect(screen.getByRole('button', { name: 'Chat' }).getAttribute('aria-pressed')).toBe('false')
    cleanup()
    mount()
    expect(screen.queryByRole('button', { name: 'Chat' })).toBeNull()
    expect(document.querySelectorAll('input')).toHaveLength(0)
  })
})
