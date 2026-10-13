// @vitest-environment jsdom
/** The first screen: one heading, which is the product's name; the mark beside it is a picture
 * (aria-hidden) at hero size in the Depth treatment; no `<input>` anywhere in the shell; the
 * recent path is plain small type — a word in `ink-3`, no tracking, no semibold, no caps. */
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { gsap } from 'gsap'
import { WelcomeScreen } from '../src/components/WelcomeScreen'
import { resetFamiliarityCache } from '../src/scenes/ambient/familiarity'
import { welcomeOpen } from '../src/motion/choreo/welcomeOpen'
import { contextFrom } from '../src/motion/choreo'
import { MOTION_DURATIONS, MOTION_EASES } from '../src/motion/contract'

const noop = () => {}
const recent = [{ path: 'C:\\Work\\Claims Portal\\project', name: 'Claims Portal', lastOpenedAt: '2026-10-06T09:00:00Z' }]

function mount(projects = recent) {
  return render(<WelcomeScreen recentProjects={projects} onPickFolder={noop} onNewProject={noop} onOpenRecent={noop} />)
}

beforeEach(() => resetFamiliarityCache())
afterEach(() => resetFamiliarityCache())

describe('WelcomeScreen hero', () => {
  it('has exactly one h1, and it is the name', () => {
    mount()
    const headings = screen.getAllByRole('heading', { level: 1 })
    expect(headings.length).toBe(1)
    expect(headings[0]!.textContent).toBe('Shepherd')
    expect(headings[0]!.className).toContain('text-display')
  })

  it('shows the mark at 56 px in Depth, hidden from assistive tech', () => {
    const { container } = mount()
    const marks = container.querySelectorAll('svg[aria-hidden="true"] linearGradient')
    expect(marks.length).toBe(1)
    const svg = marks[0]!.closest('svg')!
    expect(svg.getAttribute('class')).toContain('h-14')
    expect(svg.getAttribute('class')).toContain('w-14')
    expect(svg.getAttribute('aria-hidden')).toBe('true')
    expect(svg.closest('[class*="gap-7"]')).not.toBeNull()
  })

  it('puts no <input> in the shell', () => {
    const { container } = mount()
    expect(container.querySelector('input')).toBeNull()
  })

  it('renders the recent path as plain small type: no caps, no tracking, a word in ink-3', () => {
    const { container } = mount()
    const path = container.querySelector('[dir="rtl"]')!
    expect(path).not.toBeNull()
    expect(path.textContent).toBe('…/Claims Portal/project')
    expect(path.className).toContain('text-2xs')
    expect(path.className).toContain('text-ink-3')
    expect(path.className).not.toMatch(/uppercase|tracking|font-semibold|text-ink-4/)
  })

  it('offers the rail figure on the empty recent list', () => {
    mount([])
    expect(screen.getByText('No recent projects')).toBeTruthy()
  })
})

describe('welcomeOpen honours familiarity', () => {
  const ctx = () => contextFrom(document.body, { enabled: true, reduced: false }, { durations: MOTION_DURATIONS, eases: MOTION_EASES })

  it('first opens: the canvas arrives over 600 ms; from the fourth open a plain 320 ms fade', () => {
    const canvas = document.createElement('div')
    // Motion on: `play` returns a real gsap timeline (the stub has no clock), so the cast is the fact.
    const full = welcomeOpen.play(ctx(), { canvas, familiarity: 'full' }) as gsap.core.Timeline
    const quiet = welcomeOpen.play(ctx(), { canvas, familiarity: 'quiet' }) as gsap.core.Timeline
    const settled = welcomeOpen.play(ctx(), { canvas, familiarity: 'settled' }) as gsap.core.Timeline
    expect(full.duration()).toBeCloseTo(0.6, 2)
    expect(quiet.duration()).toBeCloseTo(0.32, 2)
    expect(settled.duration()).toBeCloseTo(0.32, 2)
    for (const tl of [full, quiet, settled]) tl.kill()
  })

  it('with motion off every tier is the end state at once: the canvas is visible, nothing tweens', () => {
    const off = contextFrom(document.body, { enabled: false, reduced: false }, { durations: MOTION_DURATIONS, eases: MOTION_EASES })
    for (const familiarity of ['full', 'quiet', 'settled'] as const) {
      const canvas = document.createElement('div')
      document.body.appendChild(canvas)
      const tl = welcomeOpen.play(off, { canvas, familiarity })
      // The stub timeline has no clock: `duration` is not on its surface, by design.
      expect('duration' in tl).toBe(false)
      expect(canvas.style.opacity).toBe('1')
      canvas.remove()
    }
    vi.restoreAllMocks()
  })
})
