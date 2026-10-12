// @vitest-environment jsdom
/** The SDLC Studio mark has two variants and one geometry. `flat` is the mark: two `currentColor`
 * shapes and nothing else, so a wrapper's text colour is the only thing that paints it. `depth`
 * is its hero treatment: one linear gradient in user space, bar top-left to disc bottom-right,
 * referenced by both shapes — and by the traced outline when the mark draws in. Two marks on a
 * screen must not share a gradient id, or the second silently paints with the first's defs. */
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { DEPTH_GRADIENT, DEPTH_MIN_PX, MARK_GEOMETRY, TogoMark } from '../src/components/brand/TogoMark'

function parse(html: string): Document {
  return new DOMParser().parseFromString(`<div xmlns="http://www.w3.org/1999/xhtml">${html}</div>`, 'application/xhtml+xml')
}

describe('TogoMark — flat (the mark)', () => {
  it('emits two currentColor shapes, no <defs>, and is hidden from assistive tech', () => {
    const html = renderToStaticMarkup(createElement(TogoMark, { className: 'h-6 w-6' }))
    expect(html).not.toContain('<defs')
    expect(html).not.toContain('linearGradient')
    expect(html.match(/fill="currentColor"/g)?.length).toBe(2)
    expect(html).toContain('aria-hidden="true"')
    expect(html).toContain('viewBox="0 0 64 64"')
  })

  it('keeps the brand geometry unchanged', () => {
    expect(MARK_GEOMETRY).toEqual({
      viewBox: '0 0 64 64',
      bar: { x: 17, y: 9, width: 30, height: 7, rx: 3.5 },
      disc: { cx: 32, cy: 38.5, r: 17.5 },
    })
  })
})

describe('TogoMark — depth (the hero treatment)', () => {
  it('fills bar and disc from one userSpaceOnUse gradient on the 17/9 → 47/56 vector', () => {
    const html = renderToStaticMarkup(createElement(TogoMark, { variant: 'depth', className: 'h-12 w-12' }))
    const doc = parse(html)
    const gradients = doc.getElementsByTagName('linearGradient')
    expect(gradients.length).toBe(1)
    const g = gradients[0]!
    expect(g.getAttribute('gradientUnits')).toBe('userSpaceOnUse')
    expect(g.getAttribute('x1')).toBe('17')
    expect(g.getAttribute('y1')).toBe('9')
    expect(g.getAttribute('x2')).toBe('47')
    expect(g.getAttribute('y2')).toBe('56')
    expect(DEPTH_GRADIENT).toEqual({ x1: 17, y1: 9, x2: 47, y2: 56 })
    const ref = `url(#${g.getAttribute('id')})`
    expect(doc.getElementsByTagName('rect')[0]!.getAttribute('fill')).toBe(ref)
    expect(doc.getElementsByTagName('circle')[0]!.getAttribute('fill')).toBe(ref)
    expect(html).not.toContain('currentColor')
  })

  it('takes its two stops from the theme-aware P0 tokens, so dark mode gets its own pair', () => {
    const html = renderToStaticMarkup(createElement(TogoMark, { variant: 'depth' }))
    expect(html).toContain('stop-color:var(--mark-depth-a)')
    expect(html).toContain('stop-color:var(--mark-depth-b)')
    expect(html).not.toMatch(/#[0-9a-f]{6}/i)
  })

  it('gives two marks on one screen distinct gradient ids', () => {
    const html = renderToStaticMarkup(
      createElement('div', null, createElement(TogoMark, { variant: 'depth' }), createElement(TogoMark, { variant: 'depth' })),
    )
    const ids = [...html.matchAll(/<linearGradient id="([^"]+)"/g)].map((m) => m[1])
    expect(ids.length).toBe(2)
    expect(new Set(ids).size).toBe(2)
    for (const id of ids) expect(html).toContain(`url(#${id})`)
  })

  it('with draw keeps the data hooks and the hidden dash offset, and strokes the trace with the gradient', () => {
    const html = renderToStaticMarkup(createElement(TogoMark, { variant: 'depth', draw: true }))
    const doc = parse(html)
    const disc = doc.querySelector('[data-mark-disc]')!
    expect(disc).not.toBeNull()
    expect(doc.querySelector('[data-mark-bar]')).not.toBeNull()
    expect(disc.getAttribute('stroke-dashoffset')).toBe('100')
    expect(disc.getAttribute('fill-opacity')).toBe('0')
    const ref = `url(#${doc.getElementsByTagName('linearGradient')[0]!.getAttribute('id')})`
    expect(disc.getAttribute('stroke')).toBe(ref)
    expect(disc.getAttribute('fill')).toBe(ref)
  })

  it('names its floor: 48 px', () => {
    expect(DEPTH_MIN_PX).toBe(48)
  })
})
