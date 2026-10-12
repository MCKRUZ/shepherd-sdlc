// @vitest-environment jsdom
/** The Shepherd mark has two variants and one geometry. `flat` is the mark: four filled paths in
 * the two brand tones — moss frame half and S lobe, umber frame half and S lobe — and nothing
 * else; `monochrome` is the ink/white mode where every path is `currentColor`. `depth` is its hero
 * treatment: ONE linear gradient in user space on the frame's corner-to-corner vector, laid over
 * the mark's own silhouette at the brand's opacity, with the two tones still underneath. The paths
 * are the owner-locked file's, byte for byte. Two marks on a screen must not share a gradient id,
 * or the second silently paints with the first's defs. */
import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import {
  DEPTH_GRADIENT, DEPTH_MIN_PX, DEPTH_OVERLAY_OPACITY, FRAME_ONLY_BELOW_PX, MARK_GEOMETRY, MARK_TONES, S_CENTRE, ShepherdMark,
} from '../src/components/brand/ShepherdMark'

const markSource = readFileSync(resolve(__dirname, '..', '..', 'docs', 'brand', 'shepherd', 'mark-a-gate-s.svg'), 'utf8')

function parse(html: string): Document {
  return new DOMParser().parseFromString(`<div xmlns="http://www.w3.org/1999/xhtml">${html}</div>`, 'application/xhtml+xml')
}

describe('ShepherdMark — flat (the mark)', () => {
  it('emits four paths in the two brand tones, no <defs>, and is hidden from assistive tech', () => {
    const html = renderToStaticMarkup(createElement(ShepherdMark, { className: 'h-12 w-12' }))
    expect(html).not.toContain('<defs')
    expect(html).not.toContain('linearGradient')
    expect(html).not.toContain('currentColor')
    expect(html.match(/<path /g)?.length).toBe(4)
    expect(html.match(/fill="#3F6B35"/g)?.length).toBe(2)
    expect(html.match(/fill="#5E452A"/g)?.length).toBe(2)
    expect(html).toContain('aria-hidden="true"')
    expect(html).toContain('viewBox="0 0 64 64"')
  })

  it('keeps the brand geometry unchanged: every path is the owner-locked file\'s, byte for byte', () => {
    expect(MARK_GEOMETRY.viewBox).toBe('0 0 64 64')
    for (const d of [MARK_GEOMETRY.frame.moss, MARK_GEOMETRY.frame.umber, MARK_GEOMETRY.s.moss, MARK_GEOMETRY.s.umber]) {
      expect(markSource, d.slice(0, 24)).toContain(`d="${d}"`)
    }
    // The file pairs each path with its tone; the component must pair them the same way.
    expect(markSource).toContain(`<path fill="${MARK_TONES.moss}" d="${MARK_GEOMETRY.frame.moss}"/>`)
    expect(markSource).toContain(`<path fill="${MARK_TONES.umber}" d="${MARK_GEOMETRY.frame.umber}"/>`)
    expect(markSource).toContain(`<path fill="${MARK_TONES.moss}" d="${MARK_GEOMETRY.s.moss}"/>`)
    expect(markSource).toContain(`<path fill="${MARK_TONES.umber}" d="${MARK_GEOMETRY.s.umber}"/>`)
    expect(MARK_TONES).toEqual({ moss: '#3F6B35', umber: '#5E452A' })
  })

  it('monochrome paints every path currentColor, so a wrapper\'s text colour is the only thing that paints it', () => {
    const html = renderToStaticMarkup(createElement(ShepherdMark, { monochrome: true }))
    expect(html.match(/fill="currentColor"/g)?.length).toBe(4)
    expect(html).not.toMatch(/#[0-9a-f]{6}/i)
  })

  it('frameOnly draws the two frame halves and no S — the rule below 48 px', () => {
    const html = renderToStaticMarkup(createElement(ShepherdMark, { frameOnly: true, className: 'h-6 w-6' }))
    expect(html.match(/<path /g)?.length).toBe(2)
    expect(html).toContain(MARK_GEOMETRY.frame.moss)
    expect(html).not.toContain(MARK_GEOMETRY.s.moss)
    expect(FRAME_ONLY_BELOW_PX).toBe(48)
  })
})

describe('ShepherdMark — depth (the hero treatment)', () => {
  it('lays one userSpaceOnUse gradient on the 4/4 → 60/60 vector over both the frame and the S, keeping the tones underneath', () => {
    const html = renderToStaticMarkup(createElement(ShepherdMark, { variant: 'depth', className: 'h-12 w-12' }))
    const doc = parse(html)
    const gradients = doc.getElementsByTagName('linearGradient')
    expect(gradients.length).toBe(1)
    const g = gradients[0]!
    expect(g.getAttribute('gradientUnits')).toBe('userSpaceOnUse')
    expect(g.getAttribute('x1')).toBe('4')
    expect(g.getAttribute('y1')).toBe('4')
    expect(g.getAttribute('x2')).toBe('60')
    expect(g.getAttribute('y2')).toBe('60')
    expect(DEPTH_GRADIENT).toEqual({ x1: 4, y1: 4, x2: 60, y2: 60 })
    const ref = `url(#${g.getAttribute('id')})`
    // Two overlay groups (frame, S), each the gradient at the brand opacity, composited as one
    // layer so the S lobes' overlap is not lit twice.
    const overlays = Array.from(doc.getElementsByTagName('g')).filter((el) => el.getAttribute('fill') === ref)
    expect(overlays.length).toBe(2)
    for (const overlay of overlays) {
      expect(overlay.getAttribute('opacity')).toBe(String(DEPTH_OVERLAY_OPACITY))
      expect(overlay.getElementsByTagName('path').length).toBe(2)
    }
    // The tones are still there: Depth lights the mark, it does not recolour it.
    expect(html.match(/fill="#3F6B35"/g)?.length).toBe(2)
    expect(html.match(/fill="#5E452A"/g)?.length).toBe(2)
    expect(html).not.toContain('currentColor')
    expect(DEPTH_OVERLAY_OPACITY).toBe(0.3)
  })

  it('takes its two stops from the theme-aware P0 tokens, so dark mode gets its own pair', () => {
    const html = renderToStaticMarkup(createElement(ShepherdMark, { variant: 'depth' }))
    expect(html).toContain('stop-color:var(--mark-depth-a)')
    expect(html).toContain('stop-color:var(--mark-depth-b)')
    // No hex inside the gradient: the only literal colours are the mark's own two tones.
    const defs = html.slice(html.indexOf('<defs'), html.indexOf('</defs>'))
    expect(defs).not.toMatch(/#[0-9a-f]{6}/i)
    expect(new Set(html.match(/#[0-9A-F]{6}/g))).toEqual(new Set(['#3F6B35', '#5E452A']))
  })

  it('gives two marks on one screen distinct gradient ids', () => {
    const html = renderToStaticMarkup(
      createElement('div', null, createElement(ShepherdMark, { variant: 'depth' }), createElement(ShepherdMark, { variant: 'depth' })),
    )
    const ids = [...html.matchAll(/<linearGradient id="([^"]+)"/g)].map((m) => m[1])
    expect(ids.length).toBe(2)
    expect(new Set(ids).size).toBe(2)
    for (const id of ids) expect(html).toContain(`url(#${id})`)
  })

  it('with draw keeps the data hooks, the hidden fill and dash offset, and strokes each half in its own tone', () => {
    const html = renderToStaticMarkup(createElement(ShepherdMark, { variant: 'depth', draw: true }))
    const doc = parse(html)
    const frame = doc.querySelector('[data-mark-frame]')!
    const s = doc.querySelector('[data-mark-s]')!
    expect(frame).not.toBeNull()
    expect(s).not.toBeNull()
    expect(frame.getAttribute('fill-opacity')).toBe('0')
    expect(s.getAttribute('opacity')).toBe('0')
    const halves = Array.from(frame.children).filter((el) => el.tagName === 'path')
    expect(halves.length).toBe(2)
    for (const half of halves) {
      expect(half.getAttribute('stroke-dashoffset')).toBe('100')
      expect(half.getAttribute('stroke-dasharray')).toBe('100')
      expect(half.getAttribute('pathLength')).toBe('100')
      expect(half.getAttribute('stroke')).toBe(half.getAttribute('fill'))
    }
    expect(halves.map((h) => h.getAttribute('stroke'))).toEqual([MARK_TONES.moss, MARK_TONES.umber])
    // The S is seated at its own centre, where the draw-in scales it from.
    expect(S_CENTRE).toEqual({ x: 29.6, y: 33.75 })
  })

  it('without draw carries no hooks: a static mark has nothing to prove', () => {
    const html = renderToStaticMarkup(createElement(ShepherdMark, { variant: 'depth' }))
    expect(html).not.toContain('data-mark-')
    expect(html).not.toContain('stroke-dashoffset')
  })

  it('names its floor: 48 px', () => {
    expect(DEPTH_MIN_PX).toBe(48)
  })
})
