// @vitest-environment jsdom
/** The command center's figure set (togo-command-center-visual.md §6): five empty figures, the
 * baton, four lane glyphs, the steering lockup and the person ring. Each figure is `aria-hidden`,
 * ≤ 120×72, has no `<text>` and no digit, paints ONLY in the two accent tones, and renders
 * byte-identical markup twice. The lane glyphs are `currentColor` only (shape, not colour). The
 * person ring never emits a digit and only the signed-in person wears the you-ring. */
import { render } from '@testing-library/react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import {
  BATON_MAX_PX, BatonGlyph, CC_EMPTY_FIGURE_NAMES, CcEmptyFigure, LANE_GLYPH_NAMES, LaneGlyph, PersonRing, ringInitials,
  STEERING_LOCKUP_LABEL, STEERING_MARK_PX, SteeringLockup, YOU_RING_SHADOW,
} from '../src/components/brand/figures'
import { DEPTH_MIN_PX } from '../src/components/brand/ShepherdMark'

const TONE_CLASSES = ['fill-accent-200', 'fill-accent-500', 'fill-none stroke-accent-200', 'fill-none stroke-accent-500']

describe('CcEmptyFigure', () => {
  it('has exactly the five names the visual direction lists, in order', () => {
    expect([...CC_EMPTY_FIGURE_NAMES]).toEqual(['no-sprint', 'nothing-needs-you', 'no-findings', 'no-decisions', 'backlog-empty'])
  })

  it.each(CC_EMPTY_FIGURE_NAMES)('%s is aria-hidden, 120×72, has no <text> or digit, and paints only in the two accent tones', (figure) => {
    const { container } = render(<CcEmptyFigure figure={figure} />)
    const svg = container.querySelector('svg')!
    expect(svg.getAttribute('aria-hidden')).toBe('true')
    expect(svg.getAttribute('focusable')).toBe('false')
    expect(svg.getAttribute('data-cc-figure')).toBe(figure)
    expect(svg.getAttribute('viewBox')).toBe('0 0 120 72')
    expect(Number(svg.getAttribute('width'))).toBeLessThanOrEqual(120)
    expect(Number(svg.getAttribute('height'))).toBeLessThanOrEqual(72)
    expect(svg.querySelector('text')).toBeNull()
    expect(svg.querySelector('defs, linearGradient, filter')).toBeNull()
    expect(svg.textContent ?? '').not.toMatch(/\d/)
    const shapes = Array.from(svg.querySelectorAll('path, circle, rect'))
    expect(shapes.length).toBeGreaterThan(0)
    for (const shape of shapes) {
      expect(TONE_CLASSES, `${figure}: ${shape.outerHTML}`).toContain(shape.getAttribute('class'))
      expect(shape.getAttribute('fill')).toBeNull() // no hex, no currentColor — the token class paints
      expect(shape.getAttribute('stroke')).toBeNull()
    }
    // Two-tone means BOTH tones appear: a figure of one tone would read as a silhouette.
    const classes = shapes.map((s) => s.getAttribute('class') ?? '')
    expect(classes.some((c) => c.includes('accent-200'))).toBe(true)
    expect(classes.some((c) => c.includes('accent-500'))).toBe(true)
  })

  it('renders byte-identical markup on re-render', () => {
    for (const figure of CC_EMPTY_FIGURE_NAMES) {
      expect(renderToStaticMarkup(<CcEmptyFigure figure={figure} />)).toBe(renderToStaticMarkup(<CcEmptyFigure figure={figure} />))
    }
  })
})

describe('BatonGlyph', () => {
  it('is a 24 px two-tone glyph (the POP ceiling), aria-hidden, carrying data-baton', () => {
    expect(BATON_MAX_PX).toBe(24)
    const { container } = render(<BatonGlyph />)
    const svg = container.querySelector('svg')!
    expect(svg.getAttribute('width')).toBe('24')
    expect(svg.getAttribute('aria-hidden')).toBe('true')
    expect(svg.hasAttribute('data-baton')).toBe(true)
    const classes = Array.from(svg.querySelectorAll('rect')).map((r) => r.getAttribute('class'))
    expect(classes).toEqual(['fill-accent-500', 'fill-accent-200', 'fill-accent-200'])
    expect(svg.querySelector('text')).toBeNull()
  })

  it('never renders above 24 px', () => {
    for (const size of [16, 18, 20, 24] as const) {
      const html = renderToStaticMarkup(<BatonGlyph size={size} />)
      expect(html).toContain(`width="${size}"`)
      expect(size).toBeLessThanOrEqual(BATON_MAX_PX)
    }
  })
})

describe('LaneGlyph', () => {
  it('has the four lane names in loop order', () => {
    expect([...LANE_GLYPH_NAMES]).toEqual(['ready', 'building', 'checking', 'merged'])
  })

  it.each(LANE_GLYPH_NAMES)('%s is currentColor only — shape is the cue, never a hue', (lane) => {
    const { container } = render(<LaneGlyph lane={lane} />)
    const svg = container.querySelector('svg')!
    expect(svg.getAttribute('aria-hidden')).toBe('true')
    expect(svg.getAttribute('data-lane-glyph')).toBe(lane)
    expect(svg.getAttribute('width')).toBe('18')
    const parts = Array.from(svg.querySelectorAll('path'))
    expect(parts.length).toBeGreaterThan(0)
    for (const part of parts) {
      const paints = [part.getAttribute('fill'), part.getAttribute('stroke')].filter((p) => p && p !== 'none')
      expect(paints.length).toBeGreaterThan(0)
      for (const paint of paints) expect(paint).toBe('currentColor')
      expect(part.getAttribute('class')).toBeNull()
    }
  })

  it('draws four distinct shapes', () => {
    const markups = LANE_GLYPH_NAMES.map((lane) => renderToStaticMarkup(<LaneGlyph lane={lane} />))
    expect(new Set(markups).size).toBe(4)
  })
})

describe('SteeringLockup', () => {
  it('is the Depth mark at exactly the 48 px floor beside the wordmark and the eyebrow "Steering", never a heading', () => {
    expect(STEERING_MARK_PX).toBe(DEPTH_MIN_PX)
    expect(STEERING_MARK_PX).toBe(48)
    const { container } = render(<SteeringLockup />)
    const root = container.querySelector('[data-steering-lockup]')!
    expect(root).toBeTruthy()
    expect(root.innerHTML).toContain('linearGradient')
    expect(root.querySelector('svg')?.getAttribute('class')).toContain('h-12 w-12')
    expect(root.textContent).toContain('Shepherd')
    expect(root.textContent).toContain(STEERING_LOCKUP_LABEL)
    expect(root.querySelector('h1, h2, h3, button, a, input')).toBeNull()
  })
})

describe('PersonRing', () => {
  it('shows at most two letters, never a digit, and names the person for assistive tech', () => {
    expect(ringInitials('Sam K')).toBe('SA')
    expect(ringInitials('@priya-n')).toBe('PR')
    expect(ringInitials('p2')).toBe('P')
    expect(ringInitials('42')).toBe('')
    const { container } = render(<PersonRing initials="S4" name="@sam-k" />)
    const ring = container.querySelector('[data-person]')!
    expect(ring.getAttribute('role')).toBe('img')
    expect(ring.getAttribute('aria-label')).toBe('@sam-k')
    expect(ring.textContent ?? '').not.toMatch(/\d/)
    expect(ring.textContent).toBe('S')
    expect((ring as HTMLElement).style.width).toBe('20px')
    expect(ring.hasAttribute('data-you')).toBe(false)
    expect((ring as HTMLElement).style.boxShadow).toBe('')
  })

  it('only the signed-in person wears the you-ring: a surface gap then the you-ring token with the accent as fallback', () => {
    const { container } = render(<PersonRing initials="AM" name="Arjun M" you />)
    const ring = container.querySelector('[data-person]') as HTMLElement
    expect(ring.hasAttribute('data-you')).toBe(true)
    expect(ring.getAttribute('aria-label')).toBe('Arjun M (you)')
    expect(YOU_RING_SHADOW).toBe('0 0 0 2px var(--color-surface-1), 0 0 0 4px var(--color-you-ring, var(--color-accent-600))')
    expect(ring.style.boxShadow).toBe(YOU_RING_SHADOW)
  })

  it('lit draws the card-lit edge; dim fades to .55 without hiding the name', () => {
    const { container } = render(<><PersonRing initials="PN" name="Priya N" lit /><PersonRing initials="SK" name="Sam K" dim /></>)
    const [lit, dim] = Array.from(container.querySelectorAll('[data-person]')) as HTMLElement[]
    expect(lit.hasAttribute('data-lit')).toBe(true)
    expect(lit.style.boxShadow).toContain('--color-card-lit')
    expect(dim.className).toContain('opacity-55')
    expect(dim.getAttribute('aria-label')).toBe('Sam K')
  })
})
