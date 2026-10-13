// @vitest-environment jsdom
/** Row #30: plays only after exit 0 AND the refreshed read; POP 100 ms then the slide over dur-3
 * (420 ms in all) with the card rising from 0.1; `settled` keeps a crossfade only; reduced motion
 * crossfades ≤ 120 ms; disabled touches nothing; after progress(1) no transform remains. */
import { gsap } from 'gsap'
import { afterEach, describe, expect, it } from 'vitest'
import { MOTION_DURATIONS, MOTION_EASES } from '../src/motion/contract'
import { contextFrom } from '../src/motion/choreo'
import { batonPass, batonPassDue, slideOffset } from '../src/motion/choreo/batonPass'
import { BATON_PASS_TOTAL_S, BATON_POP_S } from '../src/motion/presets'

const tokens = { durations: MOTION_DURATIONS, eases: MOTION_EASES }
const ctx = (enabled = true, reduced = false) => contextFrom(document.body, { enabled, reduced }, tokens)
const make = (tag = 'div') => document.body.appendChild(document.createElement(tag))
const tweens = (tl: unknown) => (tl as gsap.core.Timeline).getChildren(false, true, false) as gsap.core.Tween[]
const on = (tl: unknown, el: Element) => tweens(tl).filter((t) => (t.targets() as unknown[]).includes(el))

afterEach(() => { gsap.globalTimeline.clear(); document.body.innerHTML = '' })

describe('batonPassDue', () => {
  it('is true only on ok AND refreshed', () => {
    expect(batonPassDue({ ok: true }, true)).toBe(true)
    expect(batonPassDue({ ok: true }, false)).toBe(false)
    expect(batonPassDue({ ok: false }, true)).toBe(false)
    expect(batonPassDue(null, true)).toBe(false)
  })
  it('slideOffset is zero without layout (jsdom) or without a slot', () => {
    expect(slideOffset(make(), make())).toEqual({ x: 0, y: 0 })
    expect(slideOffset(null, make())).toEqual({ x: 0, y: 0 })
  })
})

describe('batonPass', () => {
  it('full: pops the baton at 0 for 100 ms, slides it over dur-3 from 0.1, rises the card from 0.1; total 420 ms', () => {
    const baton = make('span'); const card = make(); const from = make(); const to = make()
    const tl = batonPass.play(ctx(), { baton, fromSlot: from, toSlot: to, card, tier: 'full' }) as gsap.core.Timeline
    tl.pause()
    const [pop, slide] = on(tl, baton)
    expect(pop.duration()).toBeCloseTo(BATON_POP_S)
    expect((pop.vars as { scale?: number }).scale).toBe(1)
    expect(slide.startTime()).toBeCloseTo(BATON_POP_S)
    expect(slide.duration()).toBeCloseTo(MOTION_DURATIONS['dur-3'])
    expect(on(tl, card)[0].startTime()).toBeCloseTo(BATON_POP_S)
    expect(tl.duration()).toBeCloseTo(BATON_PASS_TOTAL_S)
    tl.progress(1)
    expect((baton as HTMLElement).style.transform).toBe('')
    expect((card as HTMLElement).style.transform).toBe('')
  })

  it('quiet keeps the pop and the slide; settled keeps only a 120 ms crossfade', () => {
    const baton = make('span'); const card = make()
    const quiet = batonPass.play(ctx(), { baton, card, tier: 'quiet' }); quiet.pause()
    expect(on(quiet, baton)).toHaveLength(2)
    const settled = batonPass.play(ctx(), { baton, card, tier: 'settled' }); settled.pause()
    expect(on(settled, baton)).toHaveLength(1)
    expect(on(settled, baton)[0].duration()).toBeCloseTo(MOTION_DURATIONS['dur-1'])
    expect((on(settled, baton)[0].vars as { scale?: number }).scale).toBeUndefined()
  })

  it('reduced: a crossfade ≤ 120 ms, no transform', () => {
    const baton = make('span'); const card = make()
    const tl = batonPass.play(ctx(true, true), { baton, card, tier: 'full' }); tl.pause()
    for (const t of tweens(tl)) {
      expect(t.duration()).toBeLessThanOrEqual(0.12 + 1e-9)
      expect((t.vars as { scale?: number; x?: number }).scale).toBeUndefined()
      expect((t.vars as { x?: number }).x).toBeUndefined()
    }
  })

  it('disabled: a completed timeline and a byte-identical DOM', () => {
    const baton = make('span'); const card = make()
    const before = document.body.outerHTML
    const tl = batonPass.play(ctx(false, true), { baton, card, tier: 'full' })
    expect(tl.progress()).toBe(1)
    expect(document.body.outerHTML).toBe(before)
  })
})
