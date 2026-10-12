// Mark A "Macron" — the SDLC Studio mark, inline (CSP: no remote assets, `img-src` never consulted).
// Geometry is copied from docs/brand/togo/mark-a-macron.svg on its 64-unit grid: a 30×7 bar
// (the macron) over a disc of radius 17.5.
//
// Two variants (brand §2, §8):
// - `flat` (default): both shapes `currentColor`, so a wrapper's `text-accent-600` colours it in
//   either theme — the brand keeps accent-600 the same value in dark (§5). This IS the mark.
// - `depth`: the sanctioned hero treatment. Bar and disc fill from ONE linear gradient in user
//   space — bar top-left (17, 9) → disc bottom-right (47, 56), so there is one light direction
//   across both shapes — whose stops are the theme-aware `--mark-depth-a` / `--mark-depth-b`
//   tokens (round 2, P0). Depth is two steps of the one accent and carries no meaning: never
//   below 48 px (`h-12`), never on a control, chip, status, data body or behind text. Its three
//   homes are the Welcome hero, the opening card and the app icon. Everything else stays flat.
//
// Minimums (brand): 24 px in-app (`h-6 w-6`), 48 px for a hero (`h-12 w-12`); 16 px only as the
// OS tile. Clear space is one bar height — 7/64 of the rendered size — on every side.
import { useId } from 'react'
import type { SVGProps } from 'react'
import type { TogoMarkVariant } from '../../ui/contract'

/** The exact shapes, exported so a test or a scene caption can assert the geometry without
 * rendering React. Do not round these: the lockup's optical balance depends on them. */
export const MARK_GEOMETRY = {
  viewBox: '0 0 64 64',
  bar: { x: 17, y: 9, width: 30, height: 7, rx: 3.5 },
  disc: { cx: 32, cy: 38.5, r: 17.5 },
} as const

/** The Depth gradient's vector in user space: the bar's top-left corner to the disc's
 * bottom-right tangent. One vector for both shapes is what makes it read as one lit object
 * rather than two tinted ones. */
export const DEPTH_GRADIENT = { x1: 17, y1: 9, x2: 47, y2: 56 } as const

/** Depth's minimum rendered size in CSS px (brand §4: "48 px+ · Depth allowed"). */
export const DEPTH_MIN_PX = 48

export interface TogoMarkProps extends Omit<SVGProps<SVGSVGElement>, 'viewBox' | 'children'> {
  /** `draw` renders the disc as a strokable outline (`pathLength=100`, dash offset 100 = hidden)
   * with `fill-opacity="0"`, and tags both shapes with `data-mark-bar` / `data-mark-disc` so a
   * choreography can draw the mark in once. The resting mark is the default and has no hooks:
   * motion is evidence, and a static mark has nothing to prove. */
  draw?: boolean
  /** `flat` (default) is the mark; `depth` is its hero treatment — see the file header. */
  variant?: TogoMarkVariant
}

/** The mark is always `aria-hidden`: the product's name is text beside it (a wordmark, an h1,
 * a visually-hidden prefix), never the picture. */
export function TogoMark({ draw = false, variant = 'flat', className, ...rest }: TogoMarkProps) {
  const { bar, disc } = MARK_GEOMETRY
  // `useId` gives two marks on one screen (hero + overlay) distinct gradient ids, and works
  // under renderToStaticMarkup — the overlay test renders that way.
  const id = useId()
  const gradientId = `togo-depth-${id.replace(/[^a-zA-Z0-9_-]/g, '')}`
  const paint = variant === 'depth' ? `url(#${gradientId})` : 'currentColor'
  return (
    <svg viewBox={MARK_GEOMETRY.viewBox} aria-hidden="true" focusable="false" className={className} {...rest}>
      {variant === 'depth' ? (
        <defs>
          <linearGradient id={gradientId} gradientUnits="userSpaceOnUse" {...DEPTH_GRADIENT}>
            <stop offset="0" style={{ stopColor: 'var(--mark-depth-a)' }} />
            <stop offset="1" style={{ stopColor: 'var(--mark-depth-b)' }} />
          </linearGradient>
        </defs>
      ) : null}
      <rect
        {...(draw ? { 'data-mark-bar': '' } : {})}
        x={bar.x}
        y={bar.y}
        width={bar.width}
        height={bar.height}
        rx={bar.rx}
        fill={paint}
        // The bar grows from its own centre, so the macron widens over the disc rather than
        // sliding in from the left.
        style={draw ? { transformOrigin: '32px 12.5px' } : undefined}
      />
      {draw ? (
        <circle
          data-mark-disc=""
          cx={disc.cx}
          cy={disc.cy}
          r={disc.r}
          fill={paint}
          fillOpacity="0"
          // With Depth the traced outline strokes with the same gradient, so the trace and the
          // fill that follows it are one object lit from one side.
          stroke={paint}
          strokeWidth="2.5"
          pathLength="100"
          strokeDasharray="100"
          strokeDashoffset="100"
        />
      ) : (
        <circle cx={disc.cx} cy={disc.cy} r={disc.r} fill={paint} />
      )}
    </svg>
  )
}
