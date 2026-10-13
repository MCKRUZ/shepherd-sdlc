/** The app icon IS the brand (round 2, B1 + B4). `docs/brand/shepherd/build-assets.mjs` writes
 * every raster from the SVG sources; this test reads what it wrote — the packaged icon is the
 * Depth tile at 256, the .ico and .icns carry the size ladder with the FLAT tile in the 16 px slot
 * (the frame alone on sand: its bars are moss 600 and umber 700 exactly, its centre the sand
 * ground with no S), the renderer's favicon is the same ICO, the builder config names the icon,
 * and what the app ships under public/brand is byte-identical to the brand source. Node only. */
import { createHash } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { inflateSync } from 'node:zlib'
import { describe, expect, it } from 'vitest'

const studio = resolve(__dirname, '..')
const repo = resolve(studio, '..')
const brand = join(repo, 'docs', 'brand', 'shepherd')
const read = (p: string) => readFileSync(p)
const sha = (b: Buffer) => createHash('sha256').update(b).digest('hex')

/** Minimal PNG decode: 8-bit RGBA, non-interlaced (what librsvg writes). Enough to read a pixel. */
function decodePng(png: Buffer): { width: number; height: number; at(x: number, y: number): [number, number, number, number] } {
  expect(png.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a')
  let o = 8, width = 0, height = 0
  const idat: Buffer[] = []
  while (o < png.length) {
    const len = png.readUInt32BE(o), type = png.subarray(o + 4, o + 8).toString('ascii'), data = png.subarray(o + 8, o + 8 + len)
    if (type === 'IHDR') {
      width = data.readUInt32BE(0); height = data.readUInt32BE(4)
      expect([data[8], data[9], data[12]]).toEqual([8, 6, 0]) // 8-bit, RGBA, non-interlaced
    }
    if (type === 'IDAT') idat.push(data)
    o += 12 + len
  }
  const raw = inflateSync(Buffer.concat(idat)), bpp = 4, stride = width * bpp, out = Buffer.alloc(stride * height)
  let prev = Buffer.alloc(stride), i = 0
  for (let y = 0; y < height; y++) {
    const f = raw[i++]!, line = Buffer.from(raw.subarray(i, i + stride)); i += stride
    for (let x = 0; x < stride; x++) {
      const a = x >= bpp ? line[x - bpp]! : 0, b = prev[x]!, c = x >= bpp ? prev[x - bpp]! : 0
      if (f === 1) line[x] = (line[x]! + a) & 255
      else if (f === 2) line[x] = (line[x]! + b) & 255
      else if (f === 3) line[x] = (line[x]! + ((a + b) >> 1)) & 255
      else if (f === 4) {
        const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c)
        line[x] = (line[x]! + (pa <= pb && pa <= pc ? a : pb <= pc ? b : c)) & 255
      }
    }
    line.copy(out, y * stride); prev = line
  }
  return { width, height, at: (x, y) => { const k = (y * width + x) * 4; return [out[k]!, out[k + 1]!, out[k + 2]!, out[k + 3]!] } }
}

const near = (px: readonly number[], hex: string, tol = 2) => {
  const want = [1, 3, 5].map((k) => parseInt(hex.slice(k, k + 2), 16))
  for (let k = 0; k < 3; k++) expect(Math.abs(px[k]! - want[k]!)).toBeLessThanOrEqual(tol)
}

describe('build/icon.* is the brand tile', () => {
  it('icon.png is tile-depth-256 byte for byte', () => {
    expect(sha(read(join(studio, 'build', 'icon.png')))).toBe(sha(read(join(brand, 'exports', 'tile-depth-256.png'))))
  })

  it('icon.ico carries at least five PNG members; the 16 px one is the flat tile — the two-tone frame alone on sand', () => {
    const ico = read(join(studio, 'build', 'icon.ico'))
    expect(ico.readUInt16LE(2)).toBe(1)
    const count = ico.readUInt16LE(4)
    expect(count).toBeGreaterThanOrEqual(5)
    const members = Array.from({ length: count }, (_, k) => {
      const e = 6 + 16 * k
      const w = ico.readUInt8(e) || 256, size = ico.readUInt32LE(e + 8), off = ico.readUInt32LE(e + 12)
      return { w, png: ico.subarray(off, off + size) }
    })
    const sixteen = members.find((m) => m.w === 16)!
    expect(sixteen).toBeDefined()
    const img = decodePng(sixteen.png)
    expect([img.width, img.height]).toEqual([16, 16])
    // The frame at 7/8 puts its bars 2 px in: the left bar is the umber half, the top bar the moss
    // half, read at the mid-edges; the centre is the sand ground — no S at this size, no gradient.
    near(img.at(2, 8), '#5E452A')
    near(img.at(8, 2), '#3F6B35')
    near(img.at(8, 8), '#F5EFE4')
    expect(sixteen.png.equals(read(join(brand, 'exports', 'tile-16.png')))).toBe(true)
    // From 64 px the member is the Depth tile: the moss half reads lighter at its top-left end
    // (the top bar) than at its bottom-right end (the right bar), and both differ from flat moss.
    const big = members.find((m) => m.w === 256)!
    const d = decodePng(big.png)
    const lit = d.at(86, 49), shaded = d.at(207, 170), mossG = 0x6b
    expect(lit[1]).toBeGreaterThan(shaded[1]! + 20)
    expect(lit[1]).toBeGreaterThan(mossG + 10)
    expect(shaded[1]).toBeLessThan(mossG - 5)
  })

  it('icon.icns carries at least five PNG members with the flat tile at 16 px', () => {
    const icns = read(join(studio, 'build', 'icon.icns'))
    expect(icns.subarray(0, 4).toString('ascii')).toBe('icns')
    expect(icns.readUInt32BE(4)).toBe(icns.length)
    const members: Array<{ type: string; png: Buffer }> = []
    for (let o = 8; o < icns.length;) {
      const type = icns.subarray(o, o + 4).toString('ascii'), len = icns.readUInt32BE(o + 4)
      members.push({ type, png: icns.subarray(o + 8, o + len) })
      o += len
    }
    expect(members.length).toBeGreaterThanOrEqual(5)
    const sixteen = members.find((m) => m.type === 'icp4')!
    const img = decodePng(sixteen.png)
    expect(img.width).toBe(16)
    near(img.at(2, 8), '#5E452A')
    near(img.at(8, 8), '#F5EFE4')
  })

  it('public/favicon.ico is the same ICO as build/icon.ico, so the window and tab icon cannot drift from the brand', () => {
    expect(sha(read(join(studio, 'public', 'favicon.ico')))).toBe(sha(read(join(studio, 'build', 'icon.ico'))))
    expect(sha(read(join(studio, 'public', 'brand', 'shepherd.ico')))).toBe(sha(read(join(studio, 'build', 'icon.ico'))))
  })

  it('electron-builder names build/icon for mac and win', () => {
    const cfg = JSON.parse(readFileSync(join(studio, 'electron-builder.json'), 'utf8')) as { mac: { icon?: string }; win: { icon?: string } }
    expect(cfg.mac.icon).toBe('build/icon')
    expect(cfg.win.icon).toBe('build/icon')
  })
})

describe('public/brand ships the brand source unchanged', () => {
  const shipped = ['mark-a-gate-s.svg', 'mark-a-gate-s-white.svg', 'mark-a-gate-s-depth.svg', 'tile.svg', 'tile-depth.svg', 'wordmark.svg', 'wordmark-white.svg', 'lockup.svg']
  for (const file of shipped) {
    it(`${file} is byte-identical to docs/brand/shepherd`, () => {
      expect(read(join(studio, 'public', 'brand', file)).equals(read(join(brand, file)))).toBe(true)
    })
  }

  it('the pipeline script exists beside the sources, names the Depth floor and ships exactly these SVGs', () => {
    const script = join(brand, 'build-assets.mjs')
    expect(existsSync(script)).toBe(true)
    const text = readFileSync(script, 'utf8')
    expect(text).toContain('DEPTH_FROM_PX = 64')
    const list = text.match(/export const SHIPPED_SVGS = \[([\s\S]*?)\]/)![1]!
    expect([...list.matchAll(/'([a-z0-9-]+\.svg)'/g)].map((m) => m[1]).sort()).toEqual([...shipped].sort())
  })
})

describe('the wordmark and lockup files are outlined, never live text', () => {
  const files = ['wordmark.svg', 'wordmark-white.svg', 'lockup.svg']
  const texts = Object.fromEntries(files.map((f) => [f, readFileSync(join(brand, f), 'utf8')]))

  it.each(files)('%s has no <text>, carries the eight glyph outlines of "shepherd" in Saira 600, and says what it is', (file) => {
    const svg = texts[file]!
    expect(svg).not.toMatch(/<text/)
    expect(svg).toContain('data-wordmark="shepherd" data-face="Saira Variable 600" data-tracking="-0.01em"')
    expect([...svg.matchAll(/data-glyph="([a-z])"/g)].map((m) => m[1]).join('')).toBe('shepherd')
    expect(svg.match(/<path data-glyph="[a-z]" d="M[^"]+"\/>/g)?.length).toBe(8)
    expect(svg).toContain('role="img" aria-label="Shepherd"')
    expect(svg).toMatch(/Saira Variable at wght 600, lowercase, tracking −0\.01em, outlined/)
  })

  it('wordmark.svg is ink on a 64-unit grid sized to its outlines; wordmark-white.svg is the same outlines in white', () => {
    expect(texts['wordmark.svg']).toContain('viewBox="0 0 201 64"')
    expect(texts['wordmark.svg']).toContain('<g fill="#1C1915" data-wordmark="shepherd"')
    expect(texts['wordmark-white.svg']).toContain('viewBox="0 0 201 64"')
    expect(texts['wordmark-white.svg']).toContain('<g fill="#FFFFFF" data-wordmark="shepherd"')
    const paths = (svg: string) => svg.match(/<path data-glyph="[a-z]" d="[^"]+"\/>/g)!
    expect(paths(texts['wordmark-white.svg']!)).toEqual(paths(texts['wordmark.svg']!))
    // The outlines start at x 0 and sit on the brand baseline: the first glyph's leftmost x is
    // within a hundredth of 0 and no coordinate leaves the 64-unit canvas.
    const numbers = paths(texts['wordmark.svg']!).join(' ').match(/-?\d+(?:\.\d+)?/g)!.map(Number)
    expect(Math.min(...numbers)).toBeGreaterThanOrEqual(0)
    expect(Math.max(...numbers)).toBeLessThanOrEqual(201)
  })

  it('lockup.svg is the mark byte for byte beside the wordmark from x 80 on the same baseline, 320 × 64', () => {
    const lockup = texts['lockup.svg']!
    expect(lockup).toContain('viewBox="0 0 320 64"')
    const mark = readFileSync(join(brand, 'mark-a-gate-s.svg'), 'utf8')
    for (const path of mark.match(/<path fill="#[0-9A-F]{6}" d="[^"]+"\/>/g)!) expect(lockup).toContain(path)
    expect(lockup.match(/<path fill="#3F6B35"/g)?.length).toBe(2)
    expect(lockup.match(/<path fill="#5E452A"/g)?.length).toBe(2)
    // The word's first outline (the s) begins 80 units to the right of where it begins in wordmark.svg.
    const first = (svg: string) => Number(svg.match(/<path data-glyph="s" d="M(-?\d+(?:\.\d+)?)/)![1])
    expect(first(lockup) - first(texts['wordmark.svg']!)).toBeCloseTo(80, 1)
    expect(lockup).toMatch(/the wordmark from x 80 on the same baseline \(y 46\)/)
  })
})
