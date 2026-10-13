// The command center's figure geometry, stated ONCE (togo-command-center-visual.md §6). The React
// figures in this folder and the static twins under `public/brand/cc/*.svg` both draw these
// shapes; `test/ccBrandAssets.test.ts` holds the two in step by comparing every path datum here
// against the file. Literal numbers, never computed, so a re-render is byte-identical and a
// reviewer can diff a shape by eye.
//
// Vocabulary is the instrument's: four lane wells, a sprint-title bar (the gate's top bar), a
// Today column and the "you" ring, a sealed ledger page, the decision clock, the next-up slot.
// Two tones only — quiet and lit — both from the one accent ramp (§2: `accent-200`, `accent-500`).

/** A shape is one of three primitives; `tone` picks quiet / lit; `stroke` draws a hollow shape. */
export type FigureTone = 'quiet' | 'lit'
export type FigureShape =
  | { kind: 'rect'; x: number; y: number; w: number; h: number; rx: number; tone: FigureTone }
  | { kind: 'circle'; cx: number; cy: number; r: number; tone: FigureTone; stroke?: number; dash?: string }
  | { kind: 'path'; d: string; tone: FigureTone; stroke?: number }

export type CcEmptyFigureName = 'no-sprint' | 'nothing-needs-you' | 'no-findings' | 'no-decisions' | 'backlog-empty'

export const CC_EMPTY_FIGURE_NAMES: readonly CcEmptyFigureName[] = [
  'no-sprint', 'nothing-needs-you', 'no-findings', 'no-decisions', 'backlog-empty',
]

/** Every empty figure shares the kit's empty-state frame size (`emptyFigures.tsx`: 120×72). */
export const CC_FIGURE_VIEWBOX = { width: 120, height: 72 } as const

export const CC_EMPTY_FIGURES: Readonly<Record<CcEmptyFigureName, readonly FigureShape[]>> = {
  // "no sprint yet": four quiet lane wells and the lit sprint-title bar above them — the loop is
  // built, nothing is in it yet.
  'no-sprint': [
    { kind: 'rect', x: 8, y: 8, w: 48, h: 6, rx: 3, tone: 'lit' },
    { kind: 'rect', x: 8, y: 22, w: 20, h: 44, rx: 3, tone: 'quiet' },
    { kind: 'rect', x: 36, y: 22, w: 20, h: 44, rx: 3, tone: 'quiet' },
    { kind: 'rect', x: 64, y: 22, w: 20, h: 44, rx: 3, tone: 'quiet' },
    { kind: 'rect', x: 92, y: 22, w: 20, h: 44, rx: 3, tone: 'quiet' },
  ],
  // "nothing needs you": the "you" ring beside three quiet Today rows — nothing is lit towards it.
  'nothing-needs-you': [
    { kind: 'circle', cx: 20, cy: 36, r: 9, tone: 'lit', stroke: 2 },
    { kind: 'circle', cx: 20, cy: 36, r: 4, tone: 'lit' },
    { kind: 'rect', x: 40, y: 14, w: 72, h: 10, rx: 3, tone: 'quiet' },
    { kind: 'rect', x: 40, y: 31, w: 72, h: 10, rx: 3, tone: 'quiet' },
    { kind: 'rect', x: 40, y: 48, w: 72, h: 10, rx: 3, tone: 'quiet' },
  ],
  // "no findings": a quiet ledger page ruled with lit hairlines that hold no finding, sealed by
  // the lit seam at its top-centre (the verdict seal's gesture).
  'no-findings': [
    { kind: 'rect', x: 30, y: 8, w: 60, h: 56, rx: 4, tone: 'quiet' },
    { kind: 'rect', x: 48, y: 8, w: 24, h: 3, rx: 1.5, tone: 'lit' },
    { kind: 'path', d: 'M40 24 H80 M40 34 H72 M40 44 H76 M40 54 H66', tone: 'lit', stroke: 1 },
  ],
  // "no decisions open": the two-business-day clock at rest — a quiet ring with a lit centre.
  'no-decisions': [
    { kind: 'circle', cx: 60, cy: 36, r: 22, tone: 'quiet', stroke: 6 },
    { kind: 'circle', cx: 60, cy: 36, r: 5, tone: 'lit' },
    { kind: 'path', d: 'M60 20 V26 M76 36 H70', tone: 'lit', stroke: 2 },
  ],
  // "backlog empty": the Refining lane with its next-up slot drawn dashed — nothing to refine.
  'backlog-empty': [
    { kind: 'rect', x: 36, y: 10, w: 48, h: 52, rx: 4, tone: 'quiet' },
    { kind: 'circle', cx: 60, cy: 36, r: 8, tone: 'lit', stroke: 1.5, dash: '3 3' },
  ],
}

/** The baton (24×24, may POP): a lit body with two quiet grip bands. */
export const BATON_VIEWBOX = { width: 24, height: 24 } as const
export const BATON_SHAPES: readonly FigureShape[] = [
  { kind: 'rect', x: 3, y: 10, w: 18, h: 4, rx: 2, tone: 'lit' },
  { kind: 'rect', x: 7, y: 10, w: 2, h: 4, rx: 0, tone: 'quiet' },
  { kind: 'rect', x: 15, y: 10, w: 2, h: 4, rx: 0, tone: 'quiet' },
]

/** Lane-header glyphs (18×18, `currentColor`): the Spine's station vocabulary applied to the
 * loop — dashed = can be picked up, half = in progress, seamed = under verdict, filled = done. */
export type LaneGlyphName = 'ready' | 'building' | 'checking' | 'merged'
export const LANE_GLYPH_NAMES: readonly LaneGlyphName[] = ['ready', 'building', 'checking', 'merged']
export const LANE_GLYPH_VIEWBOX = { width: 18, height: 18 } as const

export interface GlyphPart { d: string; fill: boolean; stroke?: number; dash?: string }
export const LANE_GLYPHS: Readonly<Record<LaneGlyphName, readonly GlyphPart[]>> = {
  ready: [
    { d: 'M9 3 a6 6 0 1 1 0 12 a6 6 0 1 1 0 -12 Z', fill: false, stroke: 1.5, dash: '2.5 2.5' },
    { d: 'M9 7.5 a1.5 1.5 0 1 1 0 3 a1.5 1.5 0 1 1 0 -3 Z', fill: true },
  ],
  building: [
    { d: 'M9 3 a6 6 0 1 1 0 12 a6 6 0 1 1 0 -12 Z', fill: false, stroke: 1.5 },
    { d: 'M9 3 a6 6 0 0 0 0 12 Z', fill: true },
  ],
  checking: [
    { d: 'M9 3 a6 6 0 1 1 0 12 a6 6 0 1 1 0 -12 Z', fill: false, stroke: 1.5 },
    { d: 'M6 8 H12 a1 1 0 0 1 0 2 H6 a1 1 0 0 1 0 -2 Z', fill: true },
  ],
  merged: [
    { d: 'M9 3 a6 6 0 1 1 0 12 a6 6 0 1 1 0 -12 Z', fill: true },
  ],
}

/** The "In the room" ring (20 px): the initials disc, a 2 px gap, the 2 px `you-ring`. */
export const PERSON_RING_PX = 20
export const PERSON_RING_GAP_PX = 2
export const PERSON_RING_WIDTH_PX = 2

/** Light-theme hex for the static twins under `public/brand/cc/`: the moss ramp's 200 / 500 / 600
 * (docs/brand/shepherd/palette.json) — the values the `accent-200` / `accent-500` / `accent-600`
 * tokens resolve to in light, because a file cannot read a token. */
export const CC_STATIC_HEX = { quiet: '#C7E0BC', lit: '#4F8545', glyph: '#3F6B35' } as const
