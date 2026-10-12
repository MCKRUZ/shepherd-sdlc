/** The CSS defines every token the types promise (studio-observatory.md §2, W0-A acceptance).
 *
 * Approach: a SOURCE check, not a Tailwind compile. Compiling index.css programmatically would
 * need Tailwind's Vite resolver for the `@import` chain and the fontsource packages, and would
 * run on every test — heavy for what is a spelling check. Instead each name in
 * `src/theme/tokens.d.ts` is expanded here through `satisfies Record<Union, 1>`, which the
 * typechecker refuses if a key is missing or extra, and the expanded name is then looked for in
 * the CSS text. The build itself is verified once by `vite build`, not here. */
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import type {
  AccentStep, AccentTextToken, DensityVar, DurationToken, EyebrowToken, InkToken, LineToken, MarkDepthVar,
  RadiusToken, ShadowToken, SpecToneToken, StageGroup, StaggerToken, StatusGroup, SurfaceToken, ThemeRevealVar,
  ToneSlot, TypeToken,
} from '../src/theme/tokens'
import { MOTION_DURATIONS, MOTION_STAGGERS } from '../src/motion/contract'

const root = join(__dirname, '..', 'src')
// The Windows runner checks out with CRLF on purpose (ci.yml); the multi-line expectations below
// are written with \n, so line endings are normalised here rather than in every assertion.
const read = (rel: string) => readFileSync(join(root, rel), 'utf8').replace(/\r\n/g, '\n')
/** Every file under `dir`, recursively — for the "exactly one carrier" pins below. */
const walk = (dir: string): string[] =>
  readdirSync(dir, { withFileTypes: true }).flatMap((d) => (d.isDirectory() ? walk(join(dir, d.name)) : [join(dir, d.name)]))
const index = read('index.css')
const tokens = read('theme/tokens.css')
const type = read('theme/type.css')
const dark = read('theme/dark.css')
const base = read('theme/base.css')

// `Record<Union, 1>` with `satisfies` is exhaustive both ways: a name the type has and this list
// lacks, or the reverse, fails `tsc -p tsconfig.test.json`.
const SURFACES = Object.keys({
  'surface-0': 1, 'surface-1': 1, 'surface-2': 1, 'surface-3': 1, 'surface-raised': 1,
  'surface-code': 1, 'surface-code-error': 1, scrim: 1,
} satisfies Record<SurfaceToken, 1>)
const INKS = Object.keys({ 'ink-1': 1, 'ink-2': 1, 'ink-3': 1, 'ink-4': 1, 'ink-inverse': 1 } satisfies Record<InkToken, 1>)
const EYEBROW = Object.keys({ eyebrow: 1 } satisfies Record<EyebrowToken, 1>)
const ACCENT_TEXT = Object.keys({ 'accent-text': 1, 'accent-text-hover': 1 } satisfies Record<AccentTextToken, 1>)
const MARK_DEPTH = Object.keys({ '--mark-depth-a': 1, '--mark-depth-b': 1 } satisfies Record<MarkDepthVar, 1>)
const THEME_REVEAL = Object.keys({ '--theme-reveal-x': 1, '--theme-reveal-y': 1 } satisfies Record<ThemeRevealVar, 1>)
const LINES = Object.keys({ 'line-1': 1, 'line-2': 1, 'line-3': 1 } satisfies Record<LineToken, 1>)
const STEPS = Object.keys({ 50: 1, 100: 1, 200: 1, 300: 1, 400: 1, 500: 1, 600: 1, 700: 1, 800: 1, 900: 1 } satisfies Record<AccentStep, 1>)
const STAGES = Object.keys({ 'stage-signed': 1, 'stage-current': 1, 'stage-later': 1 } satisfies Record<StageGroup, 1>)
const STATUSES = Object.keys({ 'status-ok': 1, 'status-warn': 1, 'status-error': 1, 'status-running': 1 } satisfies Record<StatusGroup, 1>)
const SLOTS = Object.keys({ fill: 1, bg: 1, ink: 1, line: 1 } satisfies Record<ToneSlot, 1>)
const SPECS = Object.keys({ 'spec-ready': 1, 'spec-inflight': 1, 'spec-merged': 1, 'spec-deferred': 1, 'spec-notready': 1 } satisfies Record<SpecToneToken, 1>)
const TYPES = Object.keys({ '2xs': 1, xs: 1, sm: 1, base: 1, md: 1, lg: 1, xl: 1, '2xl': 1, display: 1, code: 1 } satisfies Record<TypeToken, 1>)
const RADII = Object.keys({ 1: 1, 2: 1, 3: 1, 4: 1, pill: 1, lg: 1, xl: 1 } satisfies Record<RadiusToken, 1>)
const SHADOWS = Object.keys({ 1: 1, 2: 1, 3: 1 } satisfies Record<ShadowToken, 1>)
const DENSITY = Object.keys({ '--pad-card': 1, '--pad-row': 1, '--gap-list': 1 } satisfies Record<DensityVar, 1>)
const DURATIONS = Object.keys({ 'dur-1': 1, 'dur-2': 1, 'dur-3': 1, 'dur-4': 1, 'dur-5': 1 } satisfies Record<DurationToken, 1>)
const STAGGERS = Object.keys({ 'stagger-1': 1, 'stagger-2': 1 } satisfies Record<StaggerToken, 1>)

/** Command center (togo-command-center-visual.md §2): exactly the tokens P0 adds — hex rows and
 * alias rows alike must be declared on :root, mapped to a utility, and restated in dark's first
 * block. Not a `TypeToken`/`ColorToken` union on purpose (tokens.d.ts is the kit's; these are the
 * command center's) — the list is the contract here. */
const CC_HEX_LIGHT: Record<string, string> = {
  lane: '#efeae1', 'lane-header': '#e9e3d9', 'lane-line': '#d9d1c4', 'card-lit': '#4f8545', baton: '#3f6b35', 'baton-bg': '#e3eddd',
  'baton-ink': '#3f6b35', 'you-ring': '#3f6b35', 'plan-says': '#f3f7f0', 'plan-says-line': '#c7e0bc', 'rung-pending': '#0369a1',
  'steer-bg': '#ffffff', 'steer-tile': '#f5efe4',
  // strip-lit is a hex row, not the `stage-signed-fill` alias: on the sand canvas the signed fill is 2.88:1,
  // under the 3:1 UI floor, so light takes the signed INK step (the `rung-pending` move) and dark the fill.
  'strip-lit': '#15803d',
}
const CC_HEX_DARK: Record<string, string> = {
  lane: '#1c1915', 'lane-header': '#25211c', 'lane-line': '#2e2923', 'card-lit': '#6fa55f', baton: '#6fa55f', 'baton-bg': '#243f20',
  'baton-ink': '#9dc58e', 'you-ring': '#9dc58e', 'plan-says': '#192d17', 'plan-says-line': '#2f5229', 'rung-pending': '#38bdf8',
  'steer-bg': '#0e0c0a', 'steer-tile': '#1c1915',
  'strip-lit': '#34d399',
}
const CC_ALIAS: Record<string, string> = {
  'strip-unlit': 'line-2', 'strip-viewing': 'stage-current-fill',
  'today-act-bg': 'stage-current-bg', 'today-act-ink': 'stage-current-ink', 'today-act-line': 'stage-current-line',
  'today-wait-bg': 'status-warn-bg', 'today-wait-ink': 'status-warn-ink', 'today-wait-line': 'status-warn-line',
  'today-late-bg': 'status-error-bg', 'today-late-ink': 'status-error-ink', 'today-late-line': 'status-error-line',
  'plan-backlog': 'lane', 'plan-slate': 'surface-1', 'rung-pass': 'status-ok-fill', 'rung-fail': 'status-error-fill',
  'rung-none': 'ink-4', 'rung-rail': 'line-2', 'ledger-open-bg': 'status-warn-bg', 'ledger-open-ink': 'status-warn-ink',
  'ledger-fixed-bg': 'status-ok-bg', 'ledger-fixed-ink': 'status-ok-ink', 'ledger-split-bg': 'stage-current-bg',
  'ledger-split-ink': 'stage-current-ink', 'ledger-accepted-bg': 'stage-signed-bg', 'ledger-accepted-ink': 'stage-signed-ink',
  'ledger-postponed-bg': 'stage-later-bg', 'ledger-postponed-ink': 'stage-later-ink', 'ledger-offbooks': 'status-error-fill',
  'steer-tile-line': 'line-1', 'steer-number-ink': 'ink-1', 'steer-label-ink': 'ink-2', 'steer-nodata-ink': 'ink-3',
}
const CC_TOKENS = [...Object.keys(CC_HEX_LIGHT), ...Object.keys(CC_ALIAS)]
const CC_TYPE: Record<string, [string, string, string, string]> = {
  'sprint-title': ['32px', '36px', '-0.02em', '650'],
  'lane-count': ['20px', '24px', '-0.01em', '600'],
  metric: ['26px', '30px', '-0.015em', '600'],
  ident: ['13px', '16px', '0.01em', '500'],
  'steer-number': ['56px', '60px', '-0.025em', '650'],
  'steer-label': ['24px', '32px', '0', '500'],
}

const tones = (groups: string[]) => groups.flatMap((g) => SLOTS.map((s) => `${g}-${s}`))
const accent = STEPS.map((s) => `accent-${s}`)
const brand = STEPS.map((s) => `brand-${s}`)
/** Every ColorToken except `focus`, which is checked by name. */
const SEMANTIC = [...SURFACES, ...INKS, ...EYEBROW, ...LINES, 'focus', ...accent, ...ACCENT_TEXT, ...brand, ...tones(STAGES), ...tones(STATUSES), ...SPECS]
/** The tokens dark must restate. `brand-*` aliases `accent-*` so it follows for free. */
const DARK_OWNED = SEMANTIC.filter((n) => !n.startsWith('brand-'))

const count = (hay: string, needle: string) => hay.split(needle).length - 1
const declares = (css: string, prop: string) => new RegExp(`^\\s*${prop.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&')}:`, 'm').test(css)

describe('index.css', () => {
  it('keeps the Tailwind import first and imports the fonts and the four theme files', () => {
    expect(index.trimStart().startsWith('@import "tailwindcss";')).toBe(true)
    for (const dep of ['@fontsource-variable/inter/wght.css', '@fontsource-variable/jetbrains-mono/wght.css',
      '@fontsource-variable/saira/wght.css',
      './theme/tokens.css', './theme/type.css', './theme/dark.css', './theme/base.css']) {
      expect(index).toContain(`@import "${dep}";`)
    }
  })

  it('defines the attribute-driven dark variant', () => {
    expect(index).toContain('@custom-variant dark (&:where([data-theme="dark"], [data-theme="dark"] *));')
  })
})

describe('tokens.css (light)', () => {
  it('declares every colour token on :root AND maps it to a utility in @theme inline reference', () => {
    expect(tokens).toContain('@theme inline reference {')
    for (const name of SEMANTIC) {
      expect(declares(tokens, `--color-${name}`), `--color-${name} declared`).toBe(true)
      // Once as the value on :root, once as the mapping — the mapping line is `--x: var(--x);`.
      expect(tokens, `--color-${name} mapped`).toContain(`--color-${name}: var(--color-${name});`)
      expect(count(tokens, `--color-${name}:`)).toBeGreaterThanOrEqual(2)
    }
  })

  it('defines the brand scrim once: surface-0 at .55 with a 2 px blur, aliased to the bg-scrim utility (P3)', () => {
    expect(tokens).toContain('--scrim: rgb(245 239 228 / 0.55);')
    expect(tokens).toContain('--scrim-filter: blur(2px) saturate(1);')
    expect(tokens).toMatch(/:root\s*\{[^}]*--color-scrim: var\(--scrim\);/)
    // Never a black wash: the light scrim is surface-0's rgb (sand), not the dark canvas's (bark-0).
    expect(tokens).not.toMatch(/--scrim: rgb\(20 18 15/)
  })

  it('completes the brand scale (200/300/800/900 were used with no CSS emitted)', () => {
    for (const step of [200, 300, 800, 900]) expect(declares(tokens, `--color-brand-${step}`)).toBe(true)
  })

  it('keeps the legacy aliases the var() usages and tests reference', () => {
    for (const legacy of ['stage-signed-off', 'stage-signed-off-bg', 'stage-current', 'stage-current-bg',
      'stage-later', 'stage-later-bg', 'command-ok', 'command-error', 'command-running']) {
      expect(declares(tokens, `--color-${legacy}`), legacy).toBe(true)
    }
    expect(tokens).toContain('--color-command-running: var(--color-status-running-fill);')
  })

  it('round 2: accent-as-text, the eyebrow voice and the Depth stops (C1, C2, B2)', () => {
    expect(tokens).toContain('--color-accent-text: #3f6b35;')
    expect(tokens).toContain('--color-accent-text-hover: #2f5229;')
    expect(tokens).toContain('--color-eyebrow: var(--color-ink-3);')
    // ink-3 is bark, tuned so a word in it passes AA on surface-2 (tokenContrast.test holds the ratio).
    expect(tokens).toContain('--color-ink-3: #6b625a;')
    expect(tokens).toMatch(/ink-4.*decoration only — placeholders, dividers, aria-hidden glyphs; never a\s+word/s)
    for (const v of MARK_DEPTH) expect(declares(tokens, v), v).toBe(true)
    expect(tokens).toContain('--mark-depth-a: #9dc58e;')
    expect(tokens).toContain('--mark-depth-b: #192d17;')
    // Depth is not a colour token: no `--color-mark-*`, so no utility can put it on a control.
    expect(tokens).not.toMatch(/--color-mark-depth/)
  })

  it('declares shadows, the ring, density vars, and motion vars that match the motion contract', () => {
    for (const s of SHADOWS) expect(declares(tokens, `--shadow-${s}`)).toBe(true)
    expect(tokens).toContain('--ring: 0 0 0 2px var(--color-surface-0), 0 0 0 4px var(--color-focus);')
    for (const d of DENSITY) expect(declares(tokens, d)).toBe(true)
    for (const d of DURATIONS) {
      const ms = Math.round(MOTION_DURATIONS[d as DurationToken] * 1000)
      expect(tokens, d).toContain(`--${d}: ${ms}ms;`)
    }
    for (const s of STAGGERS) {
      const ms = Math.round(MOTION_STAGGERS[s as StaggerToken] * 1000)
      expect(tokens, s).toContain(`--${s}: ${ms}ms;`)
    }
    expect(tokens).toMatch(/:root\s*\{[^}]*color-scheme: light;/)
  })
})

describe('command center tokens (togo-command-center-visual.md §2–§3)', () => {
  it('declares all 46 on :root — the 14 hex rows with the written light values, the 32 alias rows as var() of the token they name', () => {
    expect(CC_TOKENS).toHaveLength(46)
    for (const [name, hex] of Object.entries(CC_HEX_LIGHT)) expect(tokens, name).toContain(`--color-${name}: ${hex};`)
    for (const [name, target] of Object.entries(CC_ALIAS)) expect(tokens, name).toContain(`--color-${name}: var(--color-${target});`)
  })

  it('maps every one to a utility in @theme inline reference', () => {
    for (const name of CC_TOKENS) expect(tokens, `--color-${name} mapped`).toContain(`--color-${name}: var(--color-${name});`)
  })

  it('restates every one inside the FIRST dark block (tokenContrast.test reads only that block)', () => {
    const first = dark.slice(dark.indexOf('[data-theme="dark"] {'), dark.indexOf('}', dark.indexOf('[data-theme="dark"] {')))
    for (const [name, hex] of Object.entries(CC_HEX_DARK)) expect(first, name).toContain(`--color-${name}: ${hex};`)
    for (const [name, target] of Object.entries(CC_ALIAS)) expect(first, name).toContain(`--color-${name}: var(--color-${target});`)
  })

  it('none of the colour names shadows a type token, and the six type tokens carry the written size / line / tracking / weight', () => {
    for (const t of Object.keys(CC_TYPE)) {
      expect(CC_TOKENS, `--color-${t} would shadow text-${t}`).not.toContain(t)
      const [size, line, tracking, weight] = CC_TYPE[t]
      expect(type, t).toContain(`--text-${t}: ${size};`)
      expect(type, t).toContain(`--text-${t}--line-height: ${line};`)
      expect(type, t).toContain(`--text-${t}--letter-spacing: ${tracking};`)
      expect(type, t).toContain(`--text-${t}--font-weight: ${weight};`)
    }
  })

  it('adds no gradient, no shadow and no Depth colour token (visual §8)', () => {
    const added = tokens.slice(tokens.indexOf('/* Command center (togo-command-center-visual.md'), tokens.indexOf('/* Every semantic colour'))
    expect(added).not.toMatch(/gradient|--shadow-|--color-mark/)
  })
})

describe('type.css', () => {
  it('declares every type size and radius, with the Tailwind lg/xl remap and the fonts', () => {
    for (const t of TYPES) expect(declares(type, `--text-${t}`), t).toBe(true)
    for (const r of RADII) expect(declares(type, `--radius-${r}`), r).toBe(true)
    expect(type).toContain('--radius-lg: 10px;')
    expect(type).toContain('--radius-xl: 14px;')
    expect(type).toContain('--text-sm: 13px;')
    expect(type).toMatch(/--font-sans: "Inter Variable"/)
    expect(type).toMatch(/--font-mono: "JetBrains Mono Variable"/)
    expect(type).toMatch(/--font-display: "Saira Variable"/)
  })

  it('keeps the display face to the wordmark: one UI face, one display face for the wordmark only', () => {
    // The UI face is unchanged by the display face's arrival, and shares its fallback shape.
    expect(type).toMatch(/--font-sans: "Inter Variable", Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;/)
    expect(type).toMatch(/--font-display: "Saira Variable", Saira, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;/)
    // Inter's `cv11`/`ss01` alternates are Inter's; the display face does not inherit them.
    expect(type).toContain('--font-display--font-feature-settings: normal;')
    // No type token names a family: headings keep `--font-sans` through inheritance, so a size
    // token that started carrying `--font-display` would be the global change the brand forbids.
    expect(type).not.toMatch(/--text-[\w-]+--font-family/)
    expect(base).not.toContain('font-display')
    // `font-display` as a utility appears in exactly one component: the wordmark.
    const components = join(root, 'components')
    const carriers = walk(components).filter((f) => /\.tsx?$/.test(f) && /\bfont-display\b/.test(readFileSync(f, 'utf8')))
    expect(carriers.map((f) => f.replace(/\\/g, '/').split('/components/')[1])).toEqual(['brand/ShepherdWordmark.tsx'])
  })
})

describe('ShepherdWordmark', () => {
  const wordmark = read('components/brand/ShepherdWordmark.tsx')
  it('keeps the name capitalised in the DOM and lowercases only the glyphs, in the display face at 600, −0.01em', () => {
    // The DOM text (window title, h1 prefix, accessible name) is "Shepherd"; the lowercase
    // "shepherd" of the owner's references is `text-transform`, never a second spelling.
    expect(wordmark).toContain("export const PRODUCT_NAME = 'Shepherd'")
    expect(wordmark).not.toMatch(/=\s*['"`]shepherd['"`]|>\s*shepherd\s*</)
    expect(wordmark).toContain("export const WORDMARK_CLASS = 'font-display font-semibold lowercase tracking-[-0.01em]'")
    expect(wordmark).toContain('{PRODUCT_NAME}')
    // Live text, never a picture, never shouting (brand §6, §8).
    expect(wordmark).not.toMatch(/<svg|<img|uppercase/)
  })
})

describe('dark.css', () => {
  it('restates every owned colour token and the shadows under [data-theme="dark"] with color-scheme dark', () => {
    expect(dark).toMatch(/\[data-theme="dark"\]\s*\{\s*color-scheme: dark;/)
    for (const name of DARK_OWNED) expect(declares(dark, `--color-${name}`), name).toBe(true)
    for (const s of SHADOWS) expect(declares(dark, `--shadow-${s}`)).toBe(true)
  })

  it('round 2: dark accent-text is the pale ramp end, ink-4 is lifted, Depth never sinks into surface-0', () => {
    expect(dark).toContain('--color-accent-text: #9dc58e;')
    expect(dark).toContain('--color-accent-text-hover: #c7e0bc;')
    expect(dark).toContain('--color-eyebrow: var(--color-ink-3);')
    expect(dark).toContain('--color-ink-4: #6b625a;')
    for (const v of MARK_DEPTH) expect(declares(dark, v), v).toBe(true)
    expect(dark).toContain('--mark-depth-a: #9dc58e;')
    // The far stop is accent-600, not accent-900: #192d17 on #14120f would read as a hole.
    expect(dark).toContain('--mark-depth-b: #3f6b35;')
  })

  it('restates the scrim as surface-0 dark at .6 and keeps the bg-scrim alias (P3)', () => {
    expect(dark).toContain('--scrim: rgb(20 18 15 / 0.6);')
    expect(dark).toMatch(/\[data-theme="dark"\]\s*\{[^}]*--color-scrim: var\(--scrim\);/)
    // The blur is defined once, on :root — dark must not fork it.
    expect(declares(dark, '--scrim-filter')).toBe(false)
  })

  it('remaps the legacy palette steps the design enumerates, and leaves white alone', () => {
    for (const step of ['slate-50', 'slate-100', 'slate-200', 'slate-300', 'slate-400', 'slate-500', 'slate-600',
      'slate-700', 'slate-800', 'slate-900', 'amber-50', 'amber-100', 'amber-200', 'amber-300', 'amber-600',
      'amber-700', 'amber-800', 'amber-900', 'red-50', 'red-100', 'red-200', 'red-300', 'red-700', 'red-800',
      'red-900', 'green-100', 'green-500', 'green-800', 'emerald-50', 'emerald-700', 'sky-50', 'sky-200', 'sky-700']) {
      expect(declares(dark, `--color-${step}`), step).toBe(true)
    }
    for (const kept of ['--color-white', '--color-amber-500', '--color-red-500', '--color-red-950']) {
      expect(declares(dark, kept), `${kept} must not be remapped`).toBe(false)
    }
  })

  it('carries the ten unlayered exception selectors verbatim (the design\'s eight plus the two solid amber chips)', () => {
    const selectors = [
      '[data-theme=dark] .bg-white {',
      '[data-theme=dark] .bg-slate-900 {',
      '[data-theme=dark] .bg-slate-900.text-white {',
      '[data-theme=dark] .bg-slate-900\\/40 {',
      '[data-theme=dark] .bg-red-950 {',
      '[data-theme=dark] .bg-slate-50 {',
      '[data-theme=dark] .bg-slate-200\\/50 {',
      '[data-theme=dark] .border-dashed.border-slate-300 {',
      '[data-theme=dark] .bg-amber-600 {',
      '[data-theme=dark] .bg-amber-700 {',
    ]
    for (const sel of selectors) expect(dark, sel).toContain(sel)
    expect(dark.match(/^\[data-theme=dark\] /gm)?.length).toBe(10)
    expect(dark).toMatch(/\.bg-red-950 \{[^}]*color: #fecaca;/)
  })
})

describe('base.css', () => {
  it('has the focus ring, the theme-switch transition (no widths), density and motion-off rules', () => {
    expect(base).toMatch(/:focus-visible \{[^}]*box-shadow: var\(--ring\);/)
    const sw = base.match(/html\.theme-switching \* \{([^}]*)\}/)?.[1] ?? ''
    expect(sw).toContain('background-color 200ms')
    expect(sw).not.toMatch(/width/)
    const compact = base.match(/\[data-density="compact"\] \{([^}]*)\}/)?.[1] ?? ''
    for (const d of DENSITY) expect(compact, d).toContain(`${d}:`)
    expect(compact).toContain('--text-sm: 12.5px;')
    expect(base).toMatch(/\[data-motion="off"\] \*,\s*\[data-motion="off"\] \*::before,\s*\[data-motion="off"\] \*::after \{[^}]*transition-duration: 0ms !important;[^}]*animation-duration: 0ms !important;[^}]*animation-iteration-count: 1 !important;/)
    expect(base).toContain('@media (prefers-reduced-motion: reduce)')
    expect(base).not.toMatch(/#[0-9a-f]{3,8}\b/i)
  })

  it('round 2 (C4/A1): the two glows live on a fixed, inert #root::before, not on body', () => {
    const body = base.match(/\n {2}body \{([^}]*)\}/)?.[1] ?? ''
    expect(body).toContain('background: transparent;')
    expect(body).not.toMatch(/radial-gradient/)
    const glow = base.match(/#root::before \{([^}]*)\}/)?.[1] ?? ''
    expect(glow).toContain('position: fixed;')
    expect(glow).toContain('inset: 0;')
    expect(glow).toContain('pointer-events: none;')
    expect(glow).toContain('z-index: -1;')
    expect(glow.match(/radial-gradient/g)?.length).toBe(2)
    // `html` keeps the ground colour so the canvas is never bare.
    expect(base).toMatch(/\n {2}html \{[^}]*background: var\(--color-surface-0\);/)
    const darkGlow = base.match(/\[data-theme="dark"\] \{([^}]*)\}/)?.[1] ?? ''
    expect(darkGlow).toContain('--canvas-glow-1: rgb(79 133 69 / 0.09);')
    expect(darkGlow).toContain('--canvas-glow-2: rgb(63 107 53 / 0.05);')
  })

  it('round 2 (M8): universal press and focus-arrive, both zeroed by the motion-off rules', () => {
    expect(base).toMatch(/\[data-pressable\]:active:not\(:disabled\):not\(\[aria-disabled="true"\]\) \{[^}]*transform: scale\(0\.985\);[^}]*transition: transform 80ms var\(--ease-out\);/)
    expect(base).toMatch(/@keyframes ring-in \{[\s\S]*?to \{\s*box-shadow: var\(--ring\);/)
    // The static ring stays the resting value (forced colours; a11y `box-shadow !== 'none'`).
    expect(base).toMatch(/:focus-visible \{[^}]*box-shadow: var\(--ring\);/)
    // Fields keep their flush halo: the ring-in never runs on them.
    expect(base).toMatch(/:focus-visible:where\(:not\(input, textarea, select, \[role="combobox"\]\)\) \{\s*animation: ring-in var\(--dur-1\) var\(--ease-out\);/)
  })

  it('round 2 (M4, M10): the flip lift, the view-transition reveal and the suppressed cross-fade', () => {
    expect(base).toMatch(/\.is-flipping \{\s*position: relative;\s*z-index: 1;\s*\}/)
    expect(base).toContain('html.theme-switching[data-view-transition] * {\n  transition: none;\n}')
    expect(base).toMatch(/::view-transition-old\(root\),\s*::view-transition-new\(root\) \{[^}]*animation-duration: 420ms;[^}]*animation-timing-function: var\(--ease-expo-out\);/)
    expect(base).toMatch(/::view-transition-new\(root\) \{\s*animation-name: theme-reveal;/)
    for (const v of THEME_REVEAL) expect(base, v).toContain(`var(${v}, 50%)`)
    expect(base).toMatch(/html\[data-motion="off"\]::view-transition-new\(root\) \{\s*animation: none;/)
    // Widths still never animate anywhere in the theme switch.
    expect(base.match(/html\.theme-switching \* \{([^}]*)\}/)?.[1]).not.toMatch(/width/)
  })

  it('round 2: selection and mark take tokens — the brand wash, not the OS blue', () => {
    expect(base).toMatch(/::selection \{\s*background: var\(--color-accent-200\);\s*color: var\(--color-ink-1\);/)
    expect(base).toMatch(/\n {2}mark \{[^}]*background: var\(--color-status-warn-bg\);[^}]*color: var\(--color-status-warn-ink\);/)
  })
})
