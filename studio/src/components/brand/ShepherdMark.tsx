// Mark A "gate-S" — the Shepherd mark, inline (CSP: no remote assets, `img-src` never consulted).
// Geometry is copied byte-for-byte from docs/brand/shepherd/mark-a-gate-s.svg on its 64-unit grid
// (owner-locked, 2026-10-12): two chamfered frame halves — moss along the top and right with a
// tab, umber along the left and bottom — and a two-tone S (moss upper lobe, umber lower) 21.5
// units tall whose baseline sits on the tab's bottom edge (y 44.5). Never redraw or re-fit the
// paths here; the file is the law and `test/shepherdMark.test.tsx` reads it back.
//
// The mark is two-tone BY DESIGN. Moss 600 and umber 700 are fixed values in both themes (the
// dark ramp keeps 600/700 — brand §5), so nothing here is `currentColor` unless `monochrome`
// asks for it — the ink and white contexts, where a wrapper's text colour paints every path.
//
// Two variants (brand §2, §8):
// - `flat` (default): the four paths in their own tones. This IS the mark.
// - `depth`: the sanctioned hero treatment. ONE linear gradient in user space — the frame's
//   outer corners, top-left (4, 4) → bottom-right (60, 60), a vector perpendicular to both
//   chamfer seams so each half is lit the same way — laid over the mark's own silhouette at
//   30 %, its stops the theme-aware `--mark-depth-a` / `--mark-depth-b` tokens. The two tones
//   stay underneath: Depth lights the mark, it does not recolour it. Depth carries no meaning:
//   never below 48 px (`h-12`), never on a control, chip, status, data body or behind text. Its
//   homes are the Welcome hero, the opening card, the steering lockup and the app icon.
//
// Sizes (brand §4): the S is unreadable below 48 px, so anything smaller draws the frame ALONE
// (`frameOnly`) — the 16/32 px OS tile and the 24 px in-app row icon (`h-6 w-6`). The full mark
// starts at 48 px, which is also Depth's floor. Clear space is one bar thickness — 10.9/64 of
// the rendered size — on every side.
import { useId } from 'react'
import type { SVGProps } from 'react'
import type { ShepherdMarkVariant } from '../../ui/contract'

/** The exact paths, exported so a test or a scene caption can assert the geometry without
 * rendering React. Do not round or re-fit these: the S's seat on the tab depends on them. */
export const MARK_GEOMETRY = {
  viewBox: '0 0 64 64',
  frame: {
    /** Top + right bar with the tab the S sits on. */
    moss: 'M10.47 10.22 L16.7 4 L51.5 4 L60 12.5 L60 47.3 L56.52 50.77 L50.25 44.5 L42.7 44.5 L42.7 38.9 L49.1 38.9 L49.1 14.9 L15.15 14.9 Z',
    /** Left + bottom bar. */
    umber: 'M7.47 13.22 L14.9 20.65 L14.9 49.1 L48.85 49.1 L53.52 53.77 L47.3 60 L12.5 60 L4 51.5 L4 16.7 Z',
  },
  s: {
    /** The upper lobe. */
    moss: 'M21.03 27.33 A8.75 8.75 0 0 1 28.57 23.00 L36.53 23.00 A2.57 2.57 0 0 1 39.11 25.57 L39.11 28.47 A3.99 3.99 0 0 1 35.89 32.38 A34.59 34.59 0 0 0 27.04 30.09 A20.79 20.79 0 0 1 23.18 29.25 A3.57 3.57 0 0 1 21.03 27.33 Z',
    /** The lower lobe, drawn over the upper where they meet. */
    umber: 'M20.49 28.76 A6.34 6.34 0 0 0 24.22 32.45 A31.17 31.17 0 0 0 31.50 34.18 A16.51 16.51 0 0 1 36.65 35.64 A4.18 4.18 0 0 1 38.74 40.99 A5.54 5.54 0 0 1 33.58 44.50 L21.94 44.50 A1.75 1.75 0 0 1 20.20 42.75 L20.14 41.16 A3.08 3.08 0 0 1 20.67 39.39 A3.85 3.85 0 0 1 23.83 37.74 L25.64 37.74 A6.81 6.81 0 0 1 20.49 28.76 Z',
  },
} as const

export type MarkTone = 'moss' | 'umber'

/** The two tones, fixed in both themes (palette.json: moss 600 "acts", umber 700 "holds"). */
export const MARK_TONES: Readonly<Record<MarkTone, string>> = { moss: '#3F6B35', umber: '#5E452A' }

/** The Depth gradient's vector in user space: the frame's outer corners, top-left to
 * bottom-right. It runs perpendicular to both chamfer seams (x + y = 20.7 and 107.3), so the two
 * halves meet at the same stop and read as one lit object rather than two tinted ones. */
export const DEPTH_GRADIENT = { x1: 4, y1: 4, x2: 60, y2: 60 } as const

/** How much of the Depth gradient lies over the mark. Judged on the rendered icon: at 0.55 the
 * umber half read as olive and the two tones merged; at 0.3 both tones survive and the mark
 * still reads lit from the top-left. The brand SVGs carry the same figure. */
export const DEPTH_OVERLAY_OPACITY = 0.3

/** Depth's minimum rendered size in CSS px (brand §4: "48 px+ · Depth allowed"). */
export const DEPTH_MIN_PX = 48

/** Below this rendered size the S is unreadable and the frame is drawn alone (brand §4). */
export const FRAME_ONLY_BELOW_PX = 48

/** The S's bounding-box centre on the 64 grid — where the draw-in scales it from. */
export const S_CENTRE = { x: 29.6, y: 33.75 } as const

export interface ShepherdMarkProps extends Omit<SVGProps<SVGSVGElement>, 'viewBox' | 'children'> {
  /** `draw` prepares the mark for the opening card's draw-in: the frame group starts with
   * `fill-opacity="0"` and each half is a strokable outline (`pathLength=100`, dash offset 100 =
   * hidden) tagged `data-mark-frame`; the S group starts at `opacity="0"` tagged `data-mark-s`.
   * The resting mark is the default and has no hooks: motion is evidence, and a static mark has
   * nothing to prove. */
  draw?: boolean
  /** `flat` (default) is the mark; `depth` is its hero treatment — see the file header. */
  variant?: ShepherdMarkVariant
  /** Every path in `currentColor` — the ink and white contexts (a document header on bark, a
   * mark on a moss ground). The default is the two-tone mark. */
  monochrome?: boolean
  /** The frame without the S — the brand's rule below `FRAME_ONLY_BELOW_PX` (48 px). */
  frameOnly?: boolean
}

/** The gradient-filled twin of a set of paths, composited as ONE layer so the lobes' overlap is
 * not lit twice. Inherits the group's `fill-opacity`, so under `draw` it arrives with the fill. */
function DepthOverlay({ paths, paint }: { paths: readonly string[]; paint: string }) {
  return (
    <g fill={paint} opacity={DEPTH_OVERLAY_OPACITY}>
      {paths.map((d) => (
        <path key={d} d={d} />
      ))}
    </g>
  )
}

/** The mark is always `aria-hidden`: the product's name is text beside it (a wordmark, an h1,
 * a visually-hidden prefix), never the picture. */
export function ShepherdMark({ draw = false, variant = 'flat', monochrome = false, frameOnly = false, className, ...rest }: ShepherdMarkProps) {
  const { frame, s } = MARK_GEOMETRY
  // `useId` gives two marks on one screen (hero + overlay) distinct gradient ids, and works
  // under renderToStaticMarkup — the overlay test renders that way.
  const id = useId()
  const gradientId = `shepherd-depth-${id.replace(/[^a-zA-Z0-9_-]/g, '')}`
  const depth = variant === 'depth'
  const tone = (t: MarkTone) => (monochrome ? 'currentColor' : MARK_TONES[t])
  const overlay = depth ? `url(#${gradientId})` : null
  // The trace strokes each half in its own tone; `stroke-opacity` is independent of the group's
  // `fill-opacity`, so the outline shows while the fill is still hidden. The choreography fades
  // the stroke out as the fill lands, so the resting frame is never 2.5 units fatter.
  const trace = (stroke: string) =>
    draw ? { stroke, strokeWidth: 2.5, strokeLinejoin: 'miter' as const, pathLength: 100, strokeDasharray: 100, strokeDashoffset: 100 } : {}
  return (
    <svg viewBox={MARK_GEOMETRY.viewBox} aria-hidden="true" focusable="false" className={className} {...rest}>
      {depth ? (
        <defs>
          <linearGradient id={gradientId} gradientUnits="userSpaceOnUse" {...DEPTH_GRADIENT}>
            <stop offset="0" style={{ stopColor: 'var(--mark-depth-a)' }} />
            <stop offset="1" style={{ stopColor: 'var(--mark-depth-b)' }} />
          </linearGradient>
        </defs>
      ) : null}
      <g {...(draw ? { 'data-mark-frame': '', fillOpacity: 0 } : {})}>
        <path d={frame.moss} fill={tone('moss')} {...trace(tone('moss'))} />
        <path d={frame.umber} fill={tone('umber')} {...trace(tone('umber'))} />
        {overlay ? <DepthOverlay paths={[frame.moss, frame.umber]} paint={overlay} /> : null}
      </g>
      {frameOnly ? null : (
        <g {...(draw ? { 'data-mark-s': '', opacity: 0 } : {})}>
          <path d={s.moss} fill={tone('moss')} />
          <path d={s.umber} fill={tone('umber')} />
          {overlay ? <DepthOverlay paths={[s.moss, s.umber]} paint={overlay} /> : null}
        </g>
      )}
    </svg>
  )
}
