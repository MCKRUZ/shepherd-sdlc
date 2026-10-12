/** Round 2 (C1/C2): the text tokens pass WCAG AA (4.5:1) on the surfaces they are used on, in
 * both themes. A SOURCE check: the hex values are parsed out of `tokens.css` / `dark.css`, one
 * level of `var(--color-*)` is resolved, and the ratio is computed here — so a retune of a token
 * that quietly drops a link or an eyebrow below AA fails this file, not a screenshot review.
 *
 * Measured ground (studio-upgrade-2 §1): dark `accent-700` as text was ≈ 2.5:1 and `ink-4`
 * eyebrows 2.45:1 — the two biggest correctness gaps in the v7 shots. Both pairs are pinned. */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const root = join(__dirname, '..', '..', 'src', 'theme')
const read = (rel: string) => readFileSync(join(root, rel), 'utf8')

/** `--color-x: value;` declarations inside the first block of `selector`. */
function declarations(css: string, selector: string): Map<string, string> {
  const start = css.indexOf(selector)
  if (start < 0) throw new Error(`${selector} not found`)
  const open = css.indexOf('{', start)
  const close = css.indexOf('}', open)
  const body = css.slice(open + 1, close)
  const out = new Map<string, string>()
  for (const m of body.matchAll(/(--[\w-]+):\s*([^;]+);/g)) out.set(m[1], m[2].trim())
  return out
}

function resolveHex(vars: Map<string, string>, name: string, fallback?: Map<string, string>): string {
  let value = vars.get(name) ?? fallback?.get(name)
  for (let hops = 0; hops < 4 && value?.startsWith('var('); hops += 1) {
    const inner = value.slice(4, -1).trim()
    value = vars.get(inner) ?? fallback?.get(inner)
  }
  if (!value || !/^#[0-9a-f]{6}$/i.test(value)) throw new Error(`${name} did not resolve to a 6-digit hex (got ${value})`)
  return value
}

function luminance(hex: string): number {
  const channel = (i: number) => {
    const v = parseInt(hex.slice(i, i + 2), 16) / 255
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5)
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const light = declarations(read('tokens.css'), ':root')
const dark = declarations(read('dark.css'), '[data-theme="dark"]')

const AA = 4.5
/** WCAG non-text contrast floor for a UI edge, ring or disc. */
const UI = 3
const STATUSES = ['ok', 'warn', 'error', 'running'] as const

/** `[text token, surface token]` — every pair a word in that colour is drawn on. */
const PAIRS: ReadonlyArray<[string, string]> = [
  ['--color-accent-text', '--color-surface-0'],
  ['--color-accent-text', '--color-surface-1'],
  ['--color-accent-text', '--color-surface-raised'],
  ['--color-accent-text-hover', '--color-surface-0'],
  ['--color-eyebrow', '--color-surface-0'],
  ['--color-ink-3', '--color-surface-2'],
  ...STATUSES.map((s): [string, string] => [`--color-status-${s}-ink`, `--color-status-${s}-bg`]),
  // Command center text pairs (togo-command-center-visual.md §2, the measured table).
  ['--color-ink-1', '--color-lane'],
  ['--color-ink-2', '--color-lane'],
  ['--color-ink-3', '--color-lane'],
  ['--color-eyebrow', '--color-lane-header'],
  ['--color-ink-1', '--color-lane-header'],
  ['--color-accent-text', '--color-lane'],
  ['--color-baton-ink', '--color-baton-bg'],
  ['--color-today-act-ink', '--color-today-act-bg'],
  ['--color-today-wait-ink', '--color-today-wait-bg'],
  ['--color-today-late-ink', '--color-today-late-bg'],
  ['--color-ink-2', '--color-plan-says'],
  ['--color-ink-3', '--color-plan-says'],
  ['--color-accent-text', '--color-plan-says'],
  ['--color-ledger-open-ink', '--color-ledger-open-bg'],
  ['--color-ledger-fixed-ink', '--color-ledger-fixed-bg'],
  ['--color-ledger-split-ink', '--color-ledger-split-bg'],
  ['--color-ledger-accepted-ink', '--color-ledger-accepted-bg'],
  ['--color-ledger-postponed-ink', '--color-ledger-postponed-bg'],
  ['--color-ink-1', '--color-steer-bg'],
  ['--color-ink-2', '--color-steer-bg'],
  ['--color-steer-number-ink', '--color-steer-tile'],
  ['--color-steer-label-ink', '--color-steer-tile'],
  ['--color-steer-nodata-ink', '--color-steer-tile'],
]

/** `[edge token, surface token]` — a ring, disc or 1 px edge drawn on that surface (≥ 3:1). */
const UI_PAIRS: ReadonlyArray<[string, string]> = [
  ['--color-card-lit', '--color-surface-1'],
  ['--color-card-lit', '--color-lane'],
  ['--color-baton', '--color-lane'],
  ['--color-baton', '--color-surface-1'],
  ['--color-you-ring', '--color-surface-1'],
  ['--color-you-ring', '--color-lane'],
  ['--color-you-ring', '--color-surface-raised'],
  ['--color-strip-lit', '--color-surface-0'],
  ['--color-strip-viewing', '--color-surface-0'],
  ['--color-rung-pass', '--color-surface-1'],
  ['--color-rung-fail', '--color-surface-1'],
  ['--color-rung-pending', '--color-surface-1'],
]

describe.each([
  ['light', light, undefined],
  ['dark', dark, light],
] as const)('%s theme text contrast', (_name, vars, fallback) => {
  it.each(PAIRS)('%s on %s is at least 4.5:1', (text, surface) => {
    const ratio = contrast(resolveHex(vars, text, fallback), resolveHex(vars, surface, fallback))
    expect(ratio, `${text} on ${surface} = ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(AA)
  })
})

describe.each([
  ['light', light, undefined],
  ['dark', dark, light],
] as const)('%s theme UI contrast (command center)', (_name, vars, fallback) => {
  it.each(UI_PAIRS)('%s on %s is at least 3:1', (edge, surface) => {
    const ratio = contrast(resolveHex(vars, edge, fallback), resolveHex(vars, surface, fallback))
    expect(ratio, `${edge} on ${surface} = ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(UI)
  })
})

describe('the command center\'s written numbers reproduce (togo-command-center-visual.md §2)', () => {
  const measure = (vars: Map<string, string>, fg: string, bg: string, fallback?: Map<string, string>) =>
    contrast(resolveHex(vars, fg, fallback), resolveHex(vars, bg, fallback))
  // Shepherd palette (Furrow): sand / bark surfaces and ink, moss accent; the semantic hues are
  // unchanged, so the wait / late / fixed / pass / fail / pending rows keep their light figures.
  const WRITTEN: Array<[string, string, number, number]> = [
    ['--color-ink-1', '--color-lane', 14.61, 15.30],
    ['--color-ink-2', '--color-lane', 9.91, 11.56],
    ['--color-ink-3', '--color-lane', 4.98, 6.56],
    ['--color-eyebrow', '--color-lane-header', 4.67, 6.00],
    ['--color-ink-1', '--color-lane-header', 13.72, 13.98],
    ['--color-accent-text', '--color-lane', 5.21, 9.01],
    ['--color-card-lit', '--color-surface-1', 4.40, 6.02],
    ['--color-card-lit', '--color-lane', 3.67, 6.02],
    ['--color-baton', '--color-lane', 5.21, 6.02],
    ['--color-baton', '--color-surface-1', 6.24, 6.02],
    ['--color-baton-ink', '--color-baton-bg', 5.18, 5.98],
    ['--color-you-ring', '--color-surface-1', 6.24, 9.01],
    ['--color-you-ring', '--color-lane', 5.21, 9.01],
    ['--color-you-ring', '--color-surface-raised', 6.24, 7.42],
    ['--color-strip-lit', '--color-surface-0', 4.38, 9.73],
    ['--color-strip-viewing', '--color-surface-0', 5.45, 9.63],
    ['--color-today-act-ink', '--color-today-act-bg', 5.76, 5.98],
    ['--color-today-wait-ink', '--color-today-wait-bg', 4.84, 11.23],
    ['--color-today-late-ink', '--color-today-late-bg', 5.91, 9.32],
    ['--color-ink-2', '--color-plan-says', 10.95, 9.70],
    ['--color-ink-3', '--color-plan-says', 5.50, 5.51],
    ['--color-accent-text', '--color-plan-says', 5.76, 7.56],
    ['--color-rung-pass', '--color-surface-1', 3.30, 10.05],
    ['--color-rung-fail', '--color-surface-1', 4.83, 6.33],
    ['--color-rung-pending', '--color-surface-1', 5.93, 8.17],
    ['--color-ledger-postponed-ink', '--color-ledger-postponed-bg', 5.21, 6.56],
    ['--color-ledger-fixed-ink', '--color-ledger-fixed-bg', 4.79, 10.96],
    ['--color-ink-1', '--color-steer-bg', 17.51, 17.06],
    ['--color-ink-2', '--color-steer-bg', 11.87, 12.89],
    ['--color-ink-1', '--color-steer-tile', 15.30, 15.30],
    ['--color-ink-2', '--color-steer-tile', 10.37, 11.56],
    ['--color-ink-3', '--color-steer-tile', 5.21, 6.56],
  ]
  it.each(WRITTEN)('%s on %s = %s light / %s dark', (fg, bg, l, d) => {
    expect(measure(light, fg, bg)).toBeCloseTo(l, 1)
    expect(measure(dark, fg, bg, light)).toBeCloseTo(d, 1)
  })

  it('rung-none (ink-4) is decoration beside the words "no data": below the 3:1 UI floor in light and below AA in both themes', () => {
    expect(measure(light, '--color-rung-none', '--color-surface-1')).toBeLessThan(UI)
    // The document's 2.33:1 is ink-4 on surface-0 (the kit's pinned figure, below).
    expect(measure(dark, '--color-rung-none', '--color-surface-1', light)).toBeLessThan(AA)
  })

  it('strip-lit takes the signed INK step in light because the signed fill is 2.88:1 on the sand canvas', () => {
    expect(contrast(resolveHex(light, '--color-stage-signed-fill'), resolveHex(light, '--color-surface-0'))).toBeLessThan(UI)
    expect(resolveHex(light, '--color-strip-lit')).toBe(resolveHex(light, '--color-stage-signed-ink'))
    expect(resolveHex(dark, '--color-strip-lit')).toBe(resolveHex(dark, '--color-stage-signed-fill'))
  })

  it('light rung-pending takes the running INK step because the fill is 2.77:1 on white', () => {
    expect(contrast(resolveHex(light, '--color-status-running-fill'), '#ffffff')).toBeLessThan(UI)
    expect(resolveHex(light, '--color-rung-pending')).toBe(resolveHex(light, '--color-status-running-ink'))
    expect(resolveHex(dark, '--color-rung-pending')).toBe(resolveHex(dark, '--color-status-running-fill'))
  })
})

describe('the two measured gaps stay closed', () => {
  it('dark accent-text is the pale end of the inverted ramp, not accent-700 (which is ≈ 2.1:1)', () => {
    expect(contrast(resolveHex(dark, '--color-accent-700', light), resolveHex(dark, '--color-surface-0'))).toBeLessThan(AA)
    expect(resolveHex(dark, '--color-accent-text')).toBe('#9dc58e')
  })

  it('ink-4 is decoration in both themes — it fails AA on surface-0, which is why no word wears it', () => {
    expect(contrast(resolveHex(light, '--color-ink-4'), resolveHex(light, '--color-surface-0'))).toBeLessThan(AA)
    expect(contrast(resolveHex(dark, '--color-ink-4'), resolveHex(dark, '--color-surface-0'))).toBeLessThan(AA)
  })

  it('eyebrow resolves to ink-3 in both themes', () => {
    expect(resolveHex(light, '--color-eyebrow')).toBe(resolveHex(light, '--color-ink-3'))
    expect(resolveHex(dark, '--color-eyebrow', light)).toBe(resolveHex(dark, '--color-ink-3'))
  })
})
