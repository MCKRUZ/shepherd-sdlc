/** `studio/public/brand/cc/*.svg` are the static twins of the command center's figures
 * (togo-command-center-visual.md §6), serialised by `ccStaticSvg.ts` from the one geometry the
 * React figures draw. This test is both the proof and the generator: with `CC_WRITE_ASSETS=1`
 * it writes the folder (the only sanctioned way to change it); without, it asserts every file
 * is byte-identical to what the serialiser produces now and that the folder has no strays.
 *
 * Colour discipline per file: an empty figure or the baton carries ONLY the two accent-ramp
 * hexes (#C7E0BC quiet, #4F8545 lit — moss 200 / 500); a lane glyph only moss 600 (#3F6B35);
 * NOTHING has a `<text>` — the lockup's word and eyebrow are outlined glyph paths (the wordmark
 * in Saira 600, the eyebrow in Inter 600) — and only the lockup has the one Depth gradient on
 * the brand's (4, 4) → (60, 60) vector over the two-tone mark. Node only; no renderer. */
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { CC_STATIC_HEX, ccStaticAssets } from '../src/components/brand/figures'
import {
  STEERING_EYEBROW_BASELINE, STEERING_EYEBROW_OUTLINE, STEERING_EYEBROW_PX, STEERING_TEXT_X, STEERING_WORDMARK_BASELINE, STEERING_WORDMARK_PX, WORDMARK_OUTLINE,
} from '../src/components/brand/figures/ccStaticSvg'

const folder = resolve(__dirname, '..', 'public', 'brand', 'cc')
const assets = ccStaticAssets()
const names = Object.keys(assets).sort()

if (process.env.CC_WRITE_ASSETS === '1') {
  mkdirSync(folder, { recursive: true })
  for (const [name, svg] of Object.entries(assets)) writeFileSync(join(folder, name), svg, 'utf8')
}

const hexes = (svg: string) => Array.from(new Set(svg.match(/#[0-9A-Fa-f]{6}\b/g) ?? [])).sort()

describe('public/brand/cc is generated from the figure geometry', () => {
  it('ships exactly the twelve files the serialiser names, no strays', () => {
    expect(existsSync(folder)).toBe(true)
    expect(readdirSync(folder).filter((f) => f.endsWith('.svg')).sort()).toEqual(names)
    expect(names).toEqual([
      'baton.svg', 'empty-backlog-empty.svg', 'empty-no-decisions.svg', 'empty-no-findings.svg', 'empty-no-sprint.svg',
      'empty-nothing-needs-you.svg', 'lane-building.svg', 'lane-checking.svg', 'lane-merged.svg', 'lane-ready.svg',
      'room-ring.svg', 'steering-lockup-depth.svg',
    ])
  })

  it.each(names)('%s is byte-identical to the serialiser (run with CC_WRITE_ASSETS=1 to regenerate)', (name) => {
    expect(readFileSync(join(folder, name), 'utf8').replace(/\r\n/g, '\n')).toBe(assets[name])
  })

  it.each(names.filter((n) => n.startsWith('empty-') || n === 'baton.svg'))('%s uses the two accent tones and nothing else, with no text or gradient', (name) => {
    const svg = assets[name]!
    expect(hexes(svg)).toEqual([CC_STATIC_HEX.quiet, CC_STATIC_HEX.lit].sort())
    expect(svg).not.toMatch(/<text|<linearGradient|<filter|currentColor/)
    expect(svg).toContain('aria-hidden="true"')
    expect(svg).toMatch(/viewBox="0 0 (120 72|24 24)"/)
  })

  it.each(names.filter((n) => n.startsWith('lane-')))('%s is the mark colour only — shape is the cue', (name) => {
    const svg = assets[name]!
    expect(hexes(svg)).toEqual([CC_STATIC_HEX.glyph])
    expect(svg).not.toMatch(/<text|<linearGradient/)
    expect(svg).toContain('viewBox="0 0 18 18"')
  })

  it('room-ring.svg is the 20 px disc, a 2 px gap and a 2 px you-ring at light values', () => {
    const svg = assets['room-ring.svg']!
    expect(hexes(svg)).toEqual(['#3F6B35', '#EFEAE1', '#FFFFFF'])
    expect(svg).toContain('viewBox="0 0 28 28"')
    expect(svg).toContain('r="10"')
    expect(svg).toContain('stroke-width="2"')
  })

  it('steering-lockup-depth.svg carries the one Depth gradient on the brand vector over the two-tone mark, and the outlined wordmark and eyebrow', () => {
    const svg = assets['steering-lockup-depth.svg']!
    expect(svg.match(/<linearGradient/g)?.length).toBe(1)
    expect(svg).toContain('gradientUnits="userSpaceOnUse" x1="4" y1="4" x2="60" y2="60"')
    expect(svg).toContain('stop-color="#9DC58E"')
    expect(svg).toContain('stop-color="#192D17"')
    // The mark's own tones stay under the overlay, and the overlay is clipped to its silhouette.
    expect(svg.match(/fill="#3F6B35"/g)?.length).toBe(2)
    expect(svg.match(/fill="#5E452A"/g)?.length).toBe(2)
    expect(svg).toContain('clip-path="url(#mark)" opacity="0.3"')
    // No live text anywhere: the word and the eyebrow are outlined groups, each labelled, each
    // one translate-and-scale of its em-space outline (1000 units per em).
    expect(svg).not.toMatch(/<text|font-family|font-weight/)
    expect(svg).toContain(`<g data-wordmark="shepherd" aria-label="Shepherd" data-face="Saira Variable 600" fill="#1C1915" transform="translate(${STEERING_TEXT_X} ${STEERING_WORDMARK_BASELINE}) scale(${STEERING_WORDMARK_PX / 1000})">`)
    expect(svg).toContain(`<g data-eyebrow="steering" aria-label="Steering" data-face="Inter Variable 600" fill="#6B625A" transform="translate(${STEERING_TEXT_X} ${STEERING_EYEBROW_BASELINE}) scale(${STEERING_EYEBROW_PX / 1000})">`)
    expect(svg).toContain('scale(0.022)')
    expect(svg).toContain('scale(0.011)')
    expect([...svg.matchAll(/data-glyph="([A-Za-z])"/g)].map((m) => m[1]).join('')).toBe('shepherdSTEERING')
    expect(svg).toContain('role="img" aria-label="Shepherd — Steering"')
    // The mark is drawn at 48 px: the 64-unit grid scaled by 0.75.
    expect(svg).toContain('scale(0.75)')
  })

  it('the outlines are the brand\'s: Saira 600 lowercase at −0.01em for the word, Inter 600 caps at 0.08em for the eyebrow, in em space', () => {
    expect(WORDMARK_OUTLINE.text).toBe('shepherd')
    expect(WORDMARK_OUTLINE.face).toBe('Saira Variable')
    expect(WORDMARK_OUTLINE.weight).toBe(600)
    expect(WORDMARK_OUTLINE.trackingEm).toBe(-0.01)
    expect(WORDMARK_OUTLINE.glyphs.map((g) => g.char).join('')).toBe('shepherd')
    expect(STEERING_EYEBROW_OUTLINE.text).toBe('STEERING')
    expect(STEERING_EYEBROW_OUTLINE.face).toBe('Inter Variable')
    expect(STEERING_EYEBROW_OUTLINE.weight).toBe(600)
    expect(STEERING_EYEBROW_OUTLINE.trackingEm).toBe(0.08)
    expect(STEERING_EYEBROW_OUTLINE.glyphs.map((g) => g.char).join('')).toBe('STEERING')
    // Em space: baseline 0, the first outline's left edge at 0 (no coordinate left of it), the
    // word's ascenders reach Saira's 743 and the p drops 199; the eyebrow is caps on the baseline.
    for (const outline of [WORDMARK_OUTLINE, STEERING_EYEBROW_OUTLINE]) {
      const xs = outline.glyphs.flatMap((g) => [...g.d.matchAll(/[ML](-?\d+(?:\.\d+)?) /g)].map((m) => Number(m[1])))
      expect(Math.min(...xs)).toBeGreaterThanOrEqual(0)
      expect(Math.max(...xs)).toBeLessThanOrEqual(outline.right)
    }
    expect(WORDMARK_OUTLINE.top).toBe(-743)
    expect(WORDMARK_OUTLINE.bottom).toBe(199)
    expect(STEERING_EYEBROW_OUTLINE.top).toBeLessThan(-700)
    expect(STEERING_EYEBROW_OUTLINE.bottom).toBeLessThan(20)
    // The same outlines ship as docs/brand/shepherd/wordmark.svg (at 48 units; eight glyphs, same order).
    const wordmark = readFileSync(resolve(__dirname, '..', '..', 'docs', 'brand', 'shepherd', 'wordmark.svg'), 'utf8')
    expect([...wordmark.matchAll(/data-glyph="([a-z])"/g)].map((m) => m[1]).join('')).toBe(WORDMARK_OUTLINE.glyphs.map((g) => g.char).join(''))
  })

  it('every file says it is generated and from where', () => {
    for (const name of names) expect(assets[name], name).toContain('do not hand-edit')
  })
})
