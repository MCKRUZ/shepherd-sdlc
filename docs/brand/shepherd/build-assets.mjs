#!/usr/bin/env node
// Builds every Shepherd brand raster from the SVG sources in this folder, so the app icon can
// never drift from the brand.
//
//   node docs/brand/shepherd/build-assets.mjs
//
// Writes: docs/brand/shepherd/exports/<name>-<size>.png for every mark-*.svg, tile.svg and
// tile-depth.svg at 16–1024 px; studio/public/brand/ (byte copies of the shipped SVGs — the marks,
// the tiles, the wordmark and the lockup — the 512 tile, the .ico); studio/public/favicon.ico (the
// window and tab icon — the same ICO bytes, so determinism covers it too);
// studio/build/icon.{png,ico,icns}. The icon is the FLAT tile (the
// frame alone on sand) at 16 and 32 px — the S is unreadable there and a gradient is noise — and
// the DEPTH tile (the full mark with the one Depth overlay) from 64 px up; icon.png is
// tile-depth-256. The .ico and .icns are PNG-in-container, assembled here with no dependency
// (ICNS is written directly rather than through `iconutil`, so the result is identical on every
// platform and on every run). Deterministic: rsvg-convert (librsvg) writes no timestamp, so a
// re-run leaves `git status` clean. Needs `rsvg-convert` on PATH (Homebrew: librsvg).
import { spawnSync } from 'node:child_process'
import { copyFileSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, '..', '..', '..')
const exportsDir = join(here, 'exports')
const publicBrand = join(repoRoot, 'studio', 'public', 'brand')
const buildDir = join(repoRoot, 'studio', 'build')
const publicDir = join(repoRoot, 'studio', 'public')

export const SIZES = [16, 32, 64, 128, 256, 512, 1024]
/** Flat tile below this size, Depth tile from it (brand §4). */
export const DEPTH_FROM_PX = 64
/** The SVGs the desktop app ships, byte-identical to the sources here. The wordmark and the
 * lockup are copied, never rasterised: they are not square, and the app and the guides draw them
 * as vectors.
 *
 * wordmark.svg / wordmark-white.svg / lockup.svg are OUTLINED — real glyph paths, no `<text>` —
 * so they render where the font is not installed. They are not written by this script:
 * `outline-wordmark.py` beside it is the one command that produces them (and the
 * `WORDMARK_OUTLINE` / `STEERING_EYEBROW_OUTLINE` constants in
 * studio/src/components/brand/figures/ccStaticSvg.ts) from the bundled Saira and Inter variable
 * fonts — instanced at wght=600 with fontTools, shaped with HarfBuzz, emitted as path data — and
 * its default `--check` mode proves the shipped files and constants still match the fonts:
 *   uv run --with fonttools --with brotli --with uharfbuzz python3 docs/brand/shepherd/outline-wordmark.py
 * Re-outlining (`--write`) is a deliberate act (a font update), never a build step. */
export const SHIPPED_SVGS = [
  'mark-a-gate-s.svg', 'mark-a-gate-s-white.svg', 'mark-a-gate-s-depth.svg', 'tile.svg', 'tile-depth.svg',
  'wordmark.svg', 'wordmark-white.svg', 'lockup.svg',
]
/** ICO members: Windows reads 16/32 for lists and the taskbar, 48/256 for tiles and Explorer. */
export const ICO_SIZES = [16, 32, 48, 64, 128, 256]
/** ICNS members by size: OSType pairs for the 1× and 2× (retina) slots. */
const ICNS_TYPES = { 16: 'icp4', 32: 'icp5', 64: 'icp6', 128: 'ic07', 256: 'ic08', 512: 'ic09', 1024: 'ic10' }
const ICNS_RETINA = { 32: 'ic11', 64: 'ic12', 256: 'ic13', 512: 'ic14' }

function fail(message) {
  process.stderr.write(`build-assets: ${message}\n`)
  process.exit(1)
}

function rasterise(svgPath, size) {
  const r = spawnSync('rsvg-convert', ['-w', String(size), '-h', String(size), svgPath], { maxBuffer: 64 * 1024 * 1024 })
  if (r.error) fail(`could not run rsvg-convert (${r.error.message}); install librsvg (brew install librsvg / apt install librsvg2-bin) — the brand pipeline depends on it`)
  if (r.status !== 0) fail(`rsvg-convert failed on ${svgPath} @ ${size}:\n${r.stderr}`)
  return r.stdout
}

/** The tile to use for an icon member of `size`: flat below DEPTH_FROM_PX, Depth from it. */
export function tileFor(size) {
  return size < DEPTH_FROM_PX ? 'tile' : 'tile-depth'
}

/** PNG-in-ICO: ICONDIR (6 bytes) + one ICONDIRENTRY (16 bytes) per member + the PNGs. */
export function buildIco(members) {
  const header = Buffer.alloc(6)
  header.writeUInt16LE(0, 0) // reserved
  header.writeUInt16LE(1, 2) // type: icon
  header.writeUInt16LE(members.length, 4)
  const entries = []
  let offset = 6 + 16 * members.length
  for (const { size, png } of members) {
    const e = Buffer.alloc(16)
    e.writeUInt8(size >= 256 ? 0 : size, 0) // 0 means 256
    e.writeUInt8(size >= 256 ? 0 : size, 1)
    e.writeUInt8(0, 2) // colours in palette
    e.writeUInt8(0, 3) // reserved
    e.writeUInt16LE(1, 4) // planes
    e.writeUInt16LE(32, 6) // bits per pixel
    e.writeUInt32LE(png.length, 8)
    e.writeUInt32LE(offset, 12)
    entries.push(e)
    offset += png.length
  }
  return Buffer.concat([header, ...entries, ...members.map((m) => m.png)])
}

/** PNG-in-ICNS: 'icns' + total length, then OSType + length + PNG per member. */
export function buildIcns(members) {
  const chunks = []
  for (const { type, png } of members) {
    const head = Buffer.alloc(8)
    head.write(type, 0, 'ascii')
    head.writeUInt32BE(8 + png.length, 4)
    chunks.push(head, png)
  }
  const body = Buffer.concat(chunks)
  const header = Buffer.alloc(8)
  header.write('icns', 0, 'ascii')
  header.writeUInt32BE(8 + body.length, 4)
  return Buffer.concat([header, body])
}

function main() {
  mkdirSync(exportsDir, { recursive: true })
  mkdirSync(publicBrand, { recursive: true })
  mkdirSync(buildDir, { recursive: true })

  const sources = readdirSync(here).filter((f) => f.endsWith('.svg') && (f.startsWith('mark-') || f.startsWith('tile')))
  const pngs = new Map() // `${name}-${size}` → Buffer
  for (const file of sources.sort()) {
    const name = file.replace(/\.svg$/, '')
    for (const size of SIZES) {
      const png = rasterise(join(here, file), size)
      pngs.set(`${name}-${size}`, png)
      writeFileSync(join(exportsDir, `${name}-${size}.png`), png)
    }
    process.stdout.write(`  ${file} → ${SIZES.length} sizes\n`)
  }

  const tile = (size) => pngs.get(`${tileFor(size)}-${size}`)
  const ico = buildIco(ICO_SIZES.map((size) => ({ size, png: size === 48 ? rasterise(join(here, `${tileFor(48)}.svg`), 48) : tile(size) })))
  const icnsMembers = []
  for (const [size, type] of Object.entries(ICNS_TYPES)) icnsMembers.push({ type, png: tile(Number(size)) })
  for (const [size, type] of Object.entries(ICNS_RETINA)) icnsMembers.push({ type, png: tile(Number(size)) })
  const icns = buildIcns(icnsMembers)

  writeFileSync(join(buildDir, 'icon.png'), tile(256))
  writeFileSync(join(buildDir, 'icon.ico'), ico)
  writeFileSync(join(buildDir, 'icon.icns'), icns)
  writeFileSync(join(exportsDir, 'shepherd.ico'), ico)
  // The renderer's favicon and the window icon (index.html, electron/main/index.ts) — one ICO, not a
  // hand-placed copy that could drift.
  writeFileSync(join(publicDir, 'favicon.ico'), ico)

  for (const file of SHIPPED_SVGS) copyFileSync(join(here, file), join(publicBrand, file))
  writeFileSync(join(publicBrand, 'shepherd-tile-512.png'), tile(512))
  writeFileSync(join(publicBrand, 'shepherd.ico'), ico)

  process.stdout.write(`wrote ${pngs.size} PNGs to exports/, ${SHIPPED_SVGS.length} SVGs (marks, tiles, wordmark, lockup) + tile + ico to studio/public/brand/, favicon.ico to studio/public/, icon.{png,ico,icns} to studio/build/\n`)
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main()
