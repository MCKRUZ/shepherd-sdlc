#!/usr/bin/env python3
"""Outline the Shepherd wordmark to SVG paths — the one command behind wordmark.svg,
wordmark-white.svg, lockup.svg and the WORDMARK_OUTLINE / STEERING_EYEBROW_OUTLINE constants in
studio/src/components/brand/figures/ccStaticSvg.ts.

Why outlines: the wordmark files must render where Saira is not installed, so they carry real
<path> glyph outlines and never a <text> element (brand §6; studio/test/brandAssets.test.ts pins
it). Re-outlining is a deliberate act — when the bundled font updates — never a build step:
build-assets.mjs copies these files into the app, it does not write them.

    uv run --with fonttools --with brotli --with uharfbuzz python3 docs/brand/shepherd/outline-wordmark.py
    uv run --with fonttools --with brotli --with uharfbuzz python3 docs/brand/shepherd/outline-wordmark.py --write

With no flag (or --check) it regenerates in memory, writes nothing, and compares, byte for byte,
with the three shipped SVGs beside this script and with the two `export const … as const` blocks
in ccStaticSvg.ts; exit 1 on any drift, naming it. --write replaces the three SVGs and prints the
two TypeScript blocks to paste over the constants in ccStaticSvg.ts (that file's prose comments
are written by hand and are kept). After --write: `node docs/brand/shepherd/build-assets.mjs`
copies the files into studio/public/brand/, and the steering lockup under public/brand/cc/ is
re-serialised from the constants (studio/test/ccBrandAssets.test.ts proves it current).

Recipe: the bundled variable fonts — @fontsource-variable/saira files/saira-latin-wght-normal.woff2
for the word, @fontsource-variable/inter files/inter-latin-wght-normal.woff2 for the steering
eyebrow — instanced at wght=600 with fontTools.varLib.instancer; "shepherd" (lowercase, tracking
−0.01em) and "STEERING" (tracking 0.08em) shaped with HarfBuzz (uharfbuzz, kern + liga on); each
glyph emitted with fontTools.pens.svgPathPen.SVGPathPen through a TransformPen that flips y and
scales the em. Two coordinate spaces: the 64-unit grid for the files (font size 48, baseline y 46,
the first outline's LEFT EDGE — not its pen origin — at x 0, or x 80 in the lockup; two decimals),
and em space for the TypeScript constants (1000 units per em, y down, baseline 0, left edge 0; one
decimal). The lockup's four mark paths are read from mark-a-gate-s.svg byte for byte, never redrawn.
"""
from __future__ import annotations

import argparse
import io
import math
import re
import sys
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
import uharfbuzz as hb

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
FONTS = REPO / "studio" / "node_modules" / "@fontsource-variable"
DEFAULT_SAIRA = FONTS / "saira" / "files" / "saira-latin-wght-normal.woff2"
DEFAULT_INTER = FONTS / "inter" / "files" / "inter-latin-wght-normal.woff2"
DEFAULT_MARK = HERE / "mark-a-gate-s.svg"
DEFAULT_TS = REPO / "studio" / "src" / "components" / "brand" / "figures" / "ccStaticSvg.ts"

WORD = "shepherd"
EYEBROW = "STEERING"
WEIGHT = 600
WORD_TRACKING = -10  # 1/1000 em per gap (−0.01em)
EYEBROW_TRACKING = 80  # 0.08em
SIZE, BASELINE = 48, 46  # font size and baseline on the 64-unit grid
LOCKUP_WORD_X = 80  # the word's left edge in lockup.svg: a 20-unit gap from the frame's right edge at 60
INK, WHITE = "#1C1915", "#FFFFFF"
SVG_FILES = ("wordmark.svg", "wordmark-white.svg", "lockup.svg")


def ntos_factory(decimals: int):
    """Number formatting shared by every coordinate: fixed decimals, trailing zeros dropped, no -0."""
    def ntos(value: float) -> str:
        s = f"{value:.{decimals}f}"
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return "0" if s in ("-0", "") else s
    return ntos


def load(path: Path, wght: int):
    font = TTFont(str(path))
    inst = instancer.instantiateVariableFont(font, {"wght": wght}, inplace=False)
    inst.flavor = None  # a plain TTF in memory: HarfBuzz reads it directly
    buf = io.BytesIO()
    inst.save(buf)
    return inst, hb.Font(hb.Face(buf.getvalue()))


def shape(inst, hb_font, text: str):
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(hb_font, buf, {"kern": True, "liga": True})
    names = inst.getGlyphOrder()
    return [(names[info.codepoint], pos.x_advance) for info, pos in zip(buf.glyph_infos, buf.glyph_positions)]


def outline(inst, hb_font, text: str, tracking: int, size: float, x0: float, baseline: float, decimals: int):
    """Per-glyph SVG path data plus the word's metrics. `size` is units per em in the output
    (1000 for em space, 48 for the 64-grid); `tracking` is 1/1000 em added per gap; `x0` is the
    output x of the first glyph's left edge (its left side bearing is subtracted, so the OUTLINE
    starts at x0, not the pen)."""
    upm = inst["head"].unitsPerEm
    k = size / upm
    glyph_set = inst.getGlyphSet()
    glyphs = shape(inst, hb_font, text)
    bounds = BoundsPen(glyph_set)
    glyph_set[glyphs[0][0]].draw(bounds)
    pen_x = -bounds.bounds[0]
    paths, right, top, bottom = [], None, None, None
    for index, (name, advance) in enumerate(glyphs):
        svg_pen = SVGPathPen(glyph_set, ntos=ntos_factory(decimals))
        glyph_set[name].draw(TransformPen(svg_pen, (k, 0, 0, -k, x0 + pen_x * k, baseline)))
        bounds = BoundsPen(glyph_set)
        glyph_set[name].draw(bounds)
        xmin, ymin, xmax, ymax = bounds.bounds
        r = x0 + (pen_x + xmax) * k
        right = r if right is None else max(right, r)
        t, b = baseline - ymax * k, baseline - ymin * k
        top = t if top is None else min(top, t)
        bottom = b if bottom is None else max(bottom, b)
        paths.append({"char": text[index], "d": svg_pen.getCommands()})
        pen_x += advance + tracking * upm / 1000
    return paths, {"right": right, "top": top, "bottom": bottom}


def word_group(paths, fill: str, indent: str = "  ") -> str:
    lines = [f'{indent}<g fill="{fill}" data-wordmark="shepherd" data-face="Saira Variable 600" data-tracking="-0.01em">']
    lines += [f'{indent}  <path data-glyph="{p["char"]}" d="{p["d"]}"/>' for p in paths]
    lines.append(f"{indent}</g>")
    return "\n".join(lines)


def ts_block(name: str, text: str, face: str, tracking_em: str, metrics) -> str:
    """One `export const … as const` block, in exactly the shape ccStaticSvg.ts carries."""
    n1 = ntos_factory(1)
    paths, m = metrics
    lines = [
        f"export const {name} = {{",
        f"  text: '{text}',",
        f"  face: '{face}',",
        f"  weight: {WEIGHT},",
        f"  trackingEm: {tracking_em},",
        "  /** Right edge of the last outline, in 1/1000 em from the first outline's left edge. */",
        f"  right: {n1(m['right'])},",
        "  /** Top of the tallest outline (negative: above the baseline) and bottom of the lowest, in 1/1000 em. */",
        f"  top: {n1(m['top'])},",
        f"  bottom: {n1(m['bottom'])},",
        "  glyphs: [",
    ]
    lines += [f"    {{ char: '{p['char']}', d: '{p['d']}' }}," for p in paths]
    lines += ["  ],", "} as const"]
    return "\n".join(lines)


def generate(saira_path: Path, inter_path: Path, mark_path: Path):
    """Everything this script produces: {filename: svg text} and {constant name: ts block}."""
    saira, saira_hb = load(saira_path, WEIGHT)
    inter, inter_hb = load(inter_path, WEIGHT)
    x_height = saira["OS/2"].sxHeight

    word48, m48 = outline(saira, saira_hb, WORD, WORD_TRACKING, SIZE, 0, BASELINE, 2)
    width = math.ceil(m48["right"])
    construction = (
        "Saira Variable at wght 600, lowercase, tracking −0.01em, outlined with fontTools (no live text: it renders where the font is not installed). "
        f"Font size {SIZE} on the 64-unit grid, baseline y {BASELINE}, the first outline's left edge at x 0; "
        f"x-height {x_height * SIZE / 1000:.1f}, ascenders to y {m48['top']:.2f}, the p's descender to y {m48['bottom']:.2f}. "
        "Regenerated by outlining the font with fontTools + HarfBuzz (recipe in build-assets.mjs), never edited by hand."
    )

    def wordmark_svg(fill: str, note: str) -> str:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 64" role="img" aria-label="Shepherd">\n'
            f"  <!-- The Shepherd wordmark{note}: {construction} -->\n"
            f"{word_group(word48, fill)}\n"
            "</svg>\n"
        )

    mark_paths = re.findall(r'<path fill="#[0-9A-F]{6}" d="[^"]+"/>', mark_path.read_text(encoding="utf8"))
    if len(mark_paths) != 4:
        sys.exit(f"outline-wordmark: expected the mark's four paths in {mark_path}, found {len(mark_paths)}")
    word_lockup, _ = outline(saira, saira_hb, WORD, WORD_TRACKING, SIZE, LOCKUP_WORD_X, BASELINE, 2)
    lockup = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 64" role="img" aria-label="Shepherd">\n'
        "  <!-- The Shepherd lockup: the two-tone gate-S mark on its own 64-unit canvas at x 0 (geometry byte-for-byte from mark-a-gate-s.svg), "
        f"the wordmark from x {LOCKUP_WORD_X} on the same baseline (y {BASELINE}) — a 20-unit gap from the frame's right edge at 60. "
        f"Wordmark: {construction} -->\n"
        + "".join(f"  {p}\n" for p in mark_paths)
        + word_group(word_lockup, INK)
        + "\n</svg>\n"
    )
    svgs = {
        "wordmark.svg": wordmark_svg(INK, " in ink (#1C1915)"),
        "wordmark-white.svg": wordmark_svg(WHITE, " in white, for moss, umber or bark grounds"),
        "lockup.svg": lockup,
    }
    blocks = {
        "WORDMARK_OUTLINE": ts_block("WORDMARK_OUTLINE", WORD, "Saira Variable", "-0.01", outline(saira, saira_hb, WORD, WORD_TRACKING, 1000, 0, 0, 1)),
        "STEERING_EYEBROW_OUTLINE": ts_block("STEERING_EYEBROW_OUTLINE", EYEBROW, "Inter Variable", "0.08", outline(inter, inter_hb, EYEBROW, EYEBROW_TRACKING, 1000, 0, 0, 1)),
    }
    return svgs, blocks


def shipped_block(ts_text: str, name: str) -> str | None:
    match = re.search(rf"^export const {name} = \{{\n.*?\n\}} as const$", ts_text, re.S | re.M)
    return match.group(0) if match else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="replace the three SVGs beside this script and print the TypeScript blocks")
    parser.add_argument("--check", action="store_true", help="compare with the shipped files and constants (the default)")
    parser.add_argument("--saira", type=Path, default=DEFAULT_SAIRA)
    parser.add_argument("--inter", type=Path, default=DEFAULT_INTER)
    parser.add_argument("--mark", type=Path, default=DEFAULT_MARK)
    parser.add_argument("--ts", type=Path, default=DEFAULT_TS, help="ccStaticSvg.ts, for the constants check")
    args = parser.parse_args()
    for path in (args.saira, args.inter, args.mark):
        if not path.is_file():
            return parser.error(f"not found: {path} (run `npm install` in studio/ for the fonts)")

    svgs, blocks = generate(args.saira, args.inter, args.mark)

    if args.write:
        for name, text in svgs.items():
            (HERE / name).write_text(text, encoding="utf8", newline="")
            print(f"wrote {HERE / name}")
        print("\n// Paste over the matching constants in", args.ts, "(keep its comments):\n")
        print("\n\n".join(blocks.values()))
        return 0

    drift = []
    for name, text in svgs.items():
        shipped = HERE / name
        if not shipped.is_file():
            drift.append(f"{shipped}: missing")
        elif shipped.read_bytes() != text.encode("utf8"):
            drift.append(f"{shipped}: differs from the regenerated outline")
    if args.ts.is_file():
        ts_text = args.ts.read_text(encoding="utf8")
        for name, block in blocks.items():
            current = shipped_block(ts_text, name)
            if current is None:
                drift.append(f"{args.ts}: no `export const {name} = {{ … }} as const` block")
            elif current != block:
                drift.append(f"{args.ts}: {name} differs from the regenerated outline")
    else:
        drift.append(f"{args.ts}: missing")
    if drift:
        print("outline-wordmark: DRIFT", file=sys.stderr)
        for line in drift:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"outline-wordmark: the {len(svgs)} shipped SVGs and the {len(blocks)} TypeScript constants match the fonts (no drift)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
