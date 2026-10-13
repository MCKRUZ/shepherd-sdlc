/** The visual direction (`docs/proposals/togo-command-center-visual.md`) is a contract other
 * packages build to, so its mechanical claims are checked here: it stays under its line cap;
 * every lucide icon it names exists in the installed `lucide-react`; every `--text-*` token it
 * adds has no `--color-*` namesake (Tailwind resolves `text-<name>` as a colour first, which
 * would silently drop the typography — the `Eyebrow.tsx` lesson); every colour token it names
 * is either new to the CSS or an alias of a token the CSS already declares; every hex it quotes
 * for a new token is a 6-digit value; and the contrast numbers it records are reproduced here
 * by the same formula `tokenContrast.test.ts` uses, so the document cannot drift from the math. */
import { existsSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

/** WCAG 2.x relative luminance and contrast — the same formula as `ui/tokenContrast.test.ts`
 * (restated rather than imported: importing a test file would register its suites here too). */
function luminance(hex: string): number {
  const channel = (i: number) => {
    const v = parseInt(hex.slice(i, i + 2), 16) / 255
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5)
}
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const studio = resolve(__dirname, '..')
const doc = readFileSync(join(studio, '..', 'docs', 'proposals', 'togo-command-center-visual.md'), 'utf8').replace(/\r\n/g, '\n')
const tokensCss = readFileSync(join(studio, 'src', 'theme', 'tokens.css'), 'utf8')
const typeCss = readFileSync(join(studio, 'src', 'theme', 'type.css'), 'utf8')
const lines = doc.split('\n')

/** The §2 table rows: `| \`name\` | light | dark | …`. Names with ` / ` list sibling slots. */
function tokenRows(): Array<{ names: string[]; light: string; dark: string }> {
  const start = lines.findIndex((l) => l.startsWith('## 2.'))
  const end = lines.findIndex((l, i) => i > start && l.startsWith('**Contrast'))
  const rows: Array<{ names: string[]; light: string; dark: string }> = []
  for (const line of lines.slice(start, end)) {
    const m = line.match(/^\| `([^`]+)`((?: \/ `[^`]+`)*) \| ([^|]+) \| ([^|]+) \|/)
    if (!m) continue
    const base = m[1]!
    const slots = Array.from(m[2]!.matchAll(/`([^`]+)`/g)).map((s) => s[1]!)
    rows.push({ names: slots.length ? [base, ...slots.map((s) => base.replace(/-bg$/, '') + s)] : [base], light: m[3]!.trim(), dark: m[4]!.trim() })
  }
  return rows
}

describe('togo-command-center-visual.md', () => {
  it('stays within its 320-line cap and has the nine numbered sections', () => {
    expect(lines.length).toBeLessThanOrEqual(320)
    for (const n of [1, 2, 3, 4, 5, 6, 7, 8, 9]) expect(doc).toMatch(new RegExp(`^## ${n}\\. `, 'm'))
  })

  it('names only lucide icons that exist in the installed lucide-react', () => {
    const start = lines.findIndex((l) => l.startsWith('## 5.'))
    const end = lines.findIndex((l, i) => i > start && l.startsWith('## '))
    const icons = new Set(lines.slice(start, end).join('\n').match(/`[a-z][a-z0-9-]*`/g)?.map((s) => s.slice(1, -1)) ?? [])
    icons.delete('aria-hidden'); icons.delete('label'); icons.delete('rung-'); icons.delete('rung-*')
    expect(icons.size).toBeGreaterThanOrEqual(20)
    for (const icon of icons) {
      expect(existsSync(join(studio, 'node_modules', 'lucide-react', 'dist', 'esm', 'icons', `${icon}.mjs`)), icon).toBe(true)
    }
  })

  it('adds type tokens that collide with no colour token, in the CSS or in this document', () => {
    const typeTokens = Array.from(doc.matchAll(/`--text-([a-z-]+)`/g)).map((m) => m[1]!)
    const added = ['sprint-title', 'lane-count', 'metric', 'ident', 'steer-number', 'steer-label']
    for (const t of added) expect(typeTokens, t).toContain(t)
    const colourNames = new Set([
      ...Array.from(tokensCss.matchAll(/--color-([a-z0-9-]+):/g)).map((m) => m[1]!),
      ...tokenRows().flatMap((r) => r.names),
    ])
    for (const t of added) {
      expect(colourNames.has(t), `--color-${t} would shadow text-${t}`).toBe(false)
      expect(typeCss, `--text-${t} was P0's to add (type.css)`).toContain(`--text-${t}:`)
    }
  })

  it('every new colour token is declared by P0, as a 6-digit hex per theme or an alias of a token tokens.css declares', () => {
    const rows = tokenRows()
    expect(rows.length).toBeGreaterThanOrEqual(30)
    const declared = new Set(Array.from(tokensCss.matchAll(/--color-([a-z0-9-]+):/g)).map((m) => m[1]!))
    const added = new Set(rows.flatMap((r) => r.names))
    expect(added.size, 'no token is listed twice').toBe(rows.flatMap((r) => r.names).length)
    // P0 has added the rows to tokens.css; `preexisting` is what the CSS declared before them.
    const preexisting = new Set([...declared].filter((n) => !added.has(n)))
    for (const row of rows) {
      for (const name of row.names) expect(declared.has(name), `${name} is P0's to add — declared in tokens.css`).toBe(true)
      const alias = row.light.match(/^alias `([a-z0-9-]+)(?:\/[^`]*)?`$/)
      if (alias) {
        const target = alias[1]!
        expect(preexisting.has(target) || added.has(target), `${row.names[0]} aliases ${target}, which neither tokens.css nor this document declares`).toBe(true)
        expect(row.dark).toBe('alias')
      } else {
        expect(row.light, row.names[0]).toMatch(/^`#[0-9a-f]{6}`/)
        expect(row.dark, row.names[0]).toMatch(/^`#[0-9a-f]{6}`/)
      }
    }
  })

  it('the recorded contrast numbers reproduce by the WCAG formula (text ≥ 4.5, UI ≥ 3)', () => {
    // [fg, bg, light ratio, dark ratio] — the rows of the §2 contrast table that carry hexes.
    // Shepherd palette (Furrow) — the same rows, re-measured: ink-1 / ink-3 / accent-text on lane,
    // eyebrow on lane-header, card-lit on surface-1, baton-ink on baton-bg, you-ring on lane, strip-lit
    // on surface-0 (the signed INK step in light), today-act, ink-3 on plan-says, rung-pending on
    // surface-1, ledger-postponed, ink-1 on steer-bg, ink-3 on steer-tile.
    const pinned: Array<[string, string, string, string, number, number, number]> = [
      ['#1c1915', '#efeae1', '#f5efe4', '#1c1915', 14.61, 15.30, 4.5],
      ['#6b625a', '#efeae1', '#a69d94', '#1c1915', 4.98, 6.56, 4.5],
      ['#6b625a', '#e9e3d9', '#a69d94', '#25211c', 4.67, 6.00, 4.5],
      ['#3f6b35', '#efeae1', '#9dc58e', '#1c1915', 5.21, 9.01, 4.5],
      ['#4f8545', '#ffffff', '#6fa55f', '#1c1915', 4.40, 6.02, 3],
      ['#3f6b35', '#e3eddd', '#9dc58e', '#243f20', 5.18, 5.98, 4.5],
      ['#3f6b35', '#efeae1', '#9dc58e', '#1c1915', 5.21, 9.01, 3],
      ['#15803d', '#f5efe4', '#34d399', '#14120f', 4.38, 9.73, 3],
      ['#3f6b35', '#f3f7f0', '#9dc58e', '#243f20', 5.76, 5.98, 4.5],
      ['#6b625a', '#f3f7f0', '#a69d94', '#192d17', 5.50, 5.51, 4.5],
      ['#0369a1', '#ffffff', '#38bdf8', '#1c1915', 5.93, 8.17, 3],
      ['#6b625a', '#f5efe4', '#a69d94', '#1c1915', 5.21, 6.56, 4.5],
      ['#1c1915', '#ffffff', '#f5efe4', '#0e0c0a', 17.51, 17.06, 4.5],
      ['#6b625a', '#f5efe4', '#a69d94', '#1c1915', 5.21, 6.56, 4.5],
    ]
    for (const [lf, lb, df, db, light, dark, floor] of pinned) {
      const l = contrast(lf, lb), d = contrast(df, db)
      expect(l, `${lf} on ${lb}`).toBeCloseTo(light, 1)
      expect(d, `${df} on ${db}`).toBeCloseTo(dark, 1)
      expect(l).toBeGreaterThanOrEqual(floor)
      expect(d).toBeGreaterThanOrEqual(floor)
      expect(doc).toContain(light.toFixed(2))
      expect(doc).toContain(dark.toFixed(2))
    }
    // The one documented sub-3:1 pair that justified `rung-pending` taking the ink step in light.
    expect(contrast('#0ea5e9', '#ffffff')).toBeLessThan(3)
    expect(doc).toContain('2.77')
  })

  it('names Depth at exactly two places, forbids every other gradient, and keeps the forbidden metrics out', () => {
    expect(doc).toContain('exactly two places')
    expect(doc).toMatch(/No gradient anywhere except Depth/)
    expect(doc).toMatch(/no velocity, points, PR count, LOC or hours anywhere/i)
    expect(doc).toContain('"no data"')
  })
})
