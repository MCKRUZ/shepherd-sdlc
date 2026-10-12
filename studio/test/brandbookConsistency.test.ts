/** The brandbook and the guides must describe the assets that exist and the rules the code
 * enforces (round 2, B5). The brandbook names the Depth sources and the packaged icon, no longer
 * shows a gradient as a "don't", and says where Depth may live; both guides carry the rule; the
 * user-guide template references only shots the capture produces (or P7's listed v8 additions),
 * and every brand file it names is on disk. Node only. */
import { existsSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const studio = resolve(__dirname, '..')
const repo = resolve(studio, '..')
const brandDir = join(repo, 'docs', 'brand', 'shepherd')
const guideDir = join(repo, 'docs', 'guide')
const brandbook = readFileSync(join(brandDir, 'brandbook.html'), 'utf8')
const template = readFileSync(join(guideDir, 'shepherd-user-guide.template.html'), 'utf8')
const setupGuide = readFileSync(join(guideDir, 'shepherd-setup-guide.html'), 'utf8')
const capture = readFileSync(join(studio, 'test', 'screenshots', 'capture-observatory-v2.mjs'), 'utf8')

/** The six shots P7's v8 run adds (studio-upgrade-2 §4 P7). Listed here so the template may
 * reference them before the capture script (P7's file) gains them. */
const V8_ADDITIONS = ['welcome-dark', 'palette-dark', 'spec-view-dark', 'settings-dark', 'board-graph', 'closing']

/** The wordmark's eight glyph outlines as `lockup.svg` ships them (x from 80) — the guides and
 * the brandbook must carry these exact paths, never a retyped word. */
const lockup = readFileSync(join(brandDir, 'lockup.svg'), 'utf8')
const lockupGlyphs = lockup.match(/<path data-glyph="[a-z]" d="[^"]+"\/>/g)!
const wordmarkGlyphs = readFileSync(join(brandDir, 'wordmark.svg'), 'utf8').match(/<path data-glyph="[a-z]" d="[^"]+"\/>/g)!
/** Phrases the brandbook used while the wordmark face was still the owner's open pick. None may survive. */
const WORDMARK_PLACEHOLDERS = /stop 3|TBD|[Tt]o be chosen|wait for the wordmark face|follows? the wordmark face|wordmark face is chosen|No wordmark or lockup file ships/

describe('brandbook', () => {
  it('names the Depth sources, the packaged icon, and the three wordmark files', () => {
    for (const name of ['mark-a-gate-s-depth.svg', 'tile-depth.svg', 'studio/build/icon', 'build-assets.mjs', 'wordmark.svg', 'wordmark-white.svg', 'lockup.svg']) {
      expect(brandbook, name).toContain(name)
    }
  })

  it('settles the wordmark: Saira 600, lowercase, −0.01em, outlined — no placeholder left, no live-text wordmark', () => {
    expect(lockupGlyphs).toHaveLength(8)
    expect(brandbook).not.toMatch(WORDMARK_PLACEHOLDERS)
    expect(brandbook).not.toMatch(/<text[^>]*>Shepherd<\/text>/)
    expect(brandbook).toMatch(/<td>Wordmark<\/td><td><b>Saira Variable 600<\/b><\/td>/)
    expect(brandbook).toContain('One UI face, one display face.')
    expect(brandbook).toContain('<td>UI</td><td>Inter Variable</td>')
    expect(brandbook).toContain('<td>Code, ids, paths</td><td>JetBrains Mono Variable</td>')
    expect(brandbook).toMatch(/Lockup geometry/)
    expect(brandbook).toMatch(/from x 80, baseline y 46/)
    // The page states the outlines once (byte for byte from wordmark.svg) and draws every wordmark with <use>.
    expect(brandbook).toContain('<g id="wordmark" data-wordmark="shepherd" data-face="Saira Variable 600" data-tracking="-0.01em">')
    for (const path of wordmarkGlyphs) expect(brandbook).toContain(path)
    expect(brandbook).toContain('<use href="#wordmark" class="wordmark" x="80" fill="#1C1915"/>')
    expect(brandbook).toContain('header .lockup .wordmark{fill:var(--ink-1)}')
    expect(brandbook).not.toContain('header .lockup text{')
  })

  it('palette.json agrees: the typography block names the three faces and the outlined wordmark files', () => {
    const palette = JSON.parse(readFileSync(join(brandDir, 'palette.json'), 'utf8')) as { typography: Record<string, unknown> }
    expect(palette.typography.ui).toBe('Inter Variable (bundled)')
    expect(palette.typography.code).toBe('JetBrains Mono Variable (bundled)')
    expect(palette.typography.wordmark).toBe('Saira Variable 600, lowercase, tracking −0.01em (bundled)')
    expect(palette.typography.display).toMatch(/^Saira Variable 600/)
    expect(palette.typography.wordmark_files).toEqual(['wordmark.svg', 'wordmark-white.svg', 'lockup.svg'])
    expect(palette.typography.wordmark_outlined).toBe(true)
    expect(JSON.stringify(palette)).not.toContain('TBD')
  })

  it('no longer lists a gradient as a don\'t; Depth is the one sanctioned treatment', () => {
    expect(brandbook).not.toContain('aria-label="Don\'t: gradient"')
    expect(brandbook).not.toMatch(/No gradients<span>flat colour only/)
    expect(brandbook).toContain('aria-label="Do: Depth at hero size"')
    expect(brandbook).toMatch(/48 px\+? · Depth allowed|Depth allowed/)
    expect(brandbook).toContain('<h3>Mark A — Depth</h3>')
    expect(brandbook).toContain('<h3>Signature motion</h3>')
  })

  it('states the construction the component uses: one user-space gradient on the 4/4 → 60/60 vector over the two-tone mark', () => {
    expect(brandbook).toContain('gradientUnits="userSpaceOnUse" x1="4" y1="4" x2="60" y2="60"')
    expect(brandbook).toContain('#9DC58E')
    expect(brandbook).toContain('#192D17')
    expect(brandbook).toContain('#3F6B35')
    expect(brandbook).toContain('#5E452A')
  })

  it('the packaged-icon sentences agree with the pipeline\'s DEPTH_FROM_PX and ICO member list', () => {
    const pipeline = readFileSync(join(brandDir, 'build-assets.mjs'), 'utf8')
    const depthFrom = Number(pipeline.match(/export const DEPTH_FROM_PX = (\d+)/)![1])
    const icoSizes = pipeline.match(/export const ICO_SIZES = \[([\d,\s]+)\]/)![1]!.split(',').map((s) => Number(s.trim()))
    const flat = icoSizes.filter((s) => s < depthFrom)
    const depth = icoSizes.filter((s) => s >= depthFrom)
    expect(flat.length).toBeGreaterThan(0)
    expect(depth.length).toBeGreaterThan(0)
    const flatWords = flat.length === 1 ? `${flat[0]}` : `${flat.slice(0, -1).join(', ')} and ${flat[flat.length - 1]}`
    // "16, 32 and 48 flat, 64–256 Depth" — the ICO row, derived from the constants, not retyped.
    expect(brandbook).toContain(`${icoSizes.length === 6 ? 'six' : icoSizes.length} PNG members, ${flatWords} flat, ${depth[0]}–${depth[depth.length - 1]} Depth.`)
    // The ICNS row: every 1× / 2× slot below DEPTH_FROM_PX is flat; Depth starts at it.
    expect(brandbook).toContain(`Depth from ${depthFrom}.`)
    expect(brandbook).toMatch(new RegExp(`flat at ${[16, 32].filter((s) => s < depthFrom).join(' and ')}`))
  })

  it('every file the inventory names under docs/brand/shepherd exists', () => {
    const inventory = brandbook.slice(brandbook.indexOf('<h2 id="files">'))
    const names = new Set([...inventory.matchAll(/<code>((?:mark|tile|lockup|wordmark|palette|build-assets|brandbook)[a-z0-9-]*\.(?:svg|json|mjs|html))<\/code>/g)].map((m) => m[1]!))
    expect(names.size).toBeGreaterThan(8)
    for (const name of names) expect(existsSync(join(brandDir, name)), name).toBe(true)
  })
})

describe('guides', () => {
  it('both guides carry the outlined lockup — the wordmark\'s exact paths from lockup.svg — with no live text and no brand TODO left', () => {
    const built = readFileSync(join(guideDir, 'shepherd-user-guide.html'), 'utf8')
    for (const [name, text] of [['user guide template', template], ['setup guide', setupGuide], ['built user guide', built]] as const) {
      expect(text, name).not.toContain('TODO(brand')
      const header = text.match(/<svg class="lockup"[\s\S]*?<\/svg>/)![0]
      expect(header, name).not.toMatch(/<text/)
      expect(header, name).toContain('<g class="wordmark" fill="#1C1915" data-wordmark="shepherd" data-face="Saira Variable 600" data-tracking="-0.01em">')
      for (const path of lockupGlyphs) expect(header, name).toContain(path)
      // The fill follows the theme through the class, as the live text's did.
      expect(text, name).toContain('header .lockup .wordmark{fill:var(--ink-1)}')
      expect(text, name).not.toContain('header .lockup text{')
    }
  })

  it('both guides say where Depth may live', () => {
    for (const [name, text] of [['user guide', template], ['setup guide', setupGuide]] as const) {
      expect(text, name).toMatch(/Depth/)
      expect(text, name).toMatch(/Welcome hero/)
      expect(text, name).toMatch(/opening card|card that covers the window/)
      expect(text, name).toMatch(/app icon/)
      expect(text, name).toMatch(/never (appears )?on a control/)
    }
  })

  it('the user-guide template references exactly the shots the capture produces, plus the listed v8 additions', () => {
    const referenced = [...new Set([...template.matchAll(/\{\{shot:([a-z0-9-]+)\}\}/g)].map((m) => m[1]!))]
    const produced = new Set([...capture.matchAll(/shot\(page, '([a-z0-9-]+)'\)/g)].map((m) => m[1]!))
    expect(produced.size).toBeGreaterThanOrEqual(12)
    for (const name of referenced) {
      expect(produced.has(name) || V8_ADDITIONS.includes(name), `shot "${name}" is not produced by the capture`).toBe(true)
    }
    expect(referenced).toContain('welcome')
    expect(referenced).toContain('welcome-dark')
  })

  it('every command-center screen is captured in BOTH themes (visual §9 "dark and light shots both taken")', () => {
    const produced = new Set([...capture.matchAll(/shot\(page, '([a-z0-9-]+)'\)/g)].map((m) => m[1]!))
    // The light shot and its dark twin, per screen; steering is dark-first, so its twin is `-light`.
    const pairs: Array<[string, string]> = [
      ['sprint-home', 'sprint-home-dark'], ['sprint-graph', 'sprint-graph-dark'], ['sprint-table', 'sprint-table-dark'],
      ['planning', 'planning-dark'], ['spec-card', 'spec-card-dark'], ['stage-light', 'stage-dark'], ['lifecycle-home', 'lifecycle-home-dark'],
      ['board-list', 'board-list-dark'], ['board-graph', 'board-graph-dark'], ['palette', 'palette-dark'], ['settings', 'settings-dark'],
      ['spec-view', 'spec-view-dark'], ['review', 'review-dark'], ['closing', 'closing-dark'], ['steering-light', 'steering'], ['welcome', 'welcome-dark'],
    ]
    for (const [light, dark] of pairs) {
      expect(produced.has(light), `light shot "${light}" is not produced`).toBe(true)
      expect(produced.has(dark), `dark twin "${dark}" of "${light}" is not produced`).toBe(true)
    }
  })

  // Re-recorded (round 3, the integrator): this pinned v11 while the builder at 98e257a already
  // defaulted to v12 — the test was red at HEAD. The builder now defaults to the NEWEST series,
  // v13 (every v12 name has a v13 twin; the capture produced 59 shots), and the pin follows it.
  // Round 4 (the v14 verification pass): the builder moved to v14, the series the guide ships on.
  // Brand update (Shepherd, 2.0.0): the guide was re-captured as v30 against the renamed, re-skinned app.
  it('the guide builder defaults to the v30 shots (the Shepherd series)', () => {
    expect(readFileSync(join(guideDir, 'build-user-guide.mjs'), 'utf8')).toContain("'observatory-v30'")
  })
})
