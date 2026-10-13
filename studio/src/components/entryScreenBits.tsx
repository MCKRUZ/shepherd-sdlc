// What the pre-project screens (Welcome, New project, Set up, Tooling, Clash) share: the centred
// full-window shell, the Ambient Field slot behind it, the small Shepherd lockup in the top-left,
// the theme toggle as window chrome in the top-right, and the one way a screen builds a
// choreography context from the motion module. Kept here so each screen imports a line, not a
// recipe — and so the "scene behind, content above" layering is decided once.
import type { HTMLAttributes, ReactNode, RefObject } from 'react'
import { SceneSlot } from '../scenes/core/SceneSlot'
import { MOTION_DURATIONS, MOTION_EASES, type ChoreoContext } from '../motion/contract'
import { contextFrom } from '../motion/choreo'
import { enabled, reduced } from '../motion/motion'
import { ThemeToggle, cn } from '../ui'
import { ShepherdLockup } from './brand/ShepherdLockup'

/** The Ambient Field has nothing to activate; the slot still wants the callback. */
const noop = () => {}

/** Renders nothing until Wave 3 registers the `ambient` scene; the wrapper is `aria-hidden` and
 * inert to the pointer either way, so content above it is never shadowed by a canvas. */
export function AmbientBackdrop({ canvasRef }: { canvasRef?: RefObject<HTMLDivElement | null> }) {
  return (
    <div ref={canvasRef} aria-hidden="true" data-ambient-field="" className="pointer-events-none absolute inset-0 overflow-hidden">
      <SceneSlot id="ambient" data={null} onActivate={noop} />
    </div>
  )
}

/** The theme toggle as a pill at the window's corner (G1-4). The pill says "chrome, not
 * content"; the Segmented inside loses its own grey well so there is one edge, not two. The
 * System / Light / Dark labels stay visible text — Settings › Appearance is tested by those
 * names and the two must read identically. */
export function CornerThemeToggle() {
  return (
    <div className="rounded-pill border border-line-1 bg-surface-1/80 p-0.5 backdrop-blur-sm">
      <ThemeToggle size="sm" className="[&_[role=group]]:bg-transparent [&_[role=group]]:p-0" />
    </div>
  )
}

/** Full-window centred stage on `surface-0`. `relative` so the backdrop can sit behind. `corner`
 * is window chrome (the theme toggle) pinned to the screen's top-right, outside the content
 * block, so it never floats beside whatever the block's vertical position happens to be. The
 * small lockup top-left is on by default; Welcome passes `brand={false}` because its hero already
 * carries the mark, and the mark appears once per screen (brand §5). */
export function EntryShell({
  children,
  className,
  rootRef,
  canvasRef,
  corner,
  brand = true,
  ...rest
}: {
  children: ReactNode
  className?: string
  rootRef?: RefObject<HTMLDivElement | null>
  canvasRef?: RefObject<HTMLDivElement | null>
  corner?: ReactNode
  brand?: boolean
} & Omit<HTMLAttributes<HTMLDivElement>, 'className' | 'children'>) {
  return (
    <div ref={rootRef} className={cn('relative flex h-screen items-center justify-center bg-surface-0 p-6', className)} {...rest}>
      <AmbientBackdrop canvasRef={canvasRef} />
      {brand ? <ShepherdLockup className="absolute left-6 top-5 z-10" /> : null}
      {/* 16 px from both edges — the same inset top and right, so the pill sits on the grid
          rather than 20 px in and 16 px down. */}
      {corner ? <div className="absolute right-4 top-4 z-10">{corner}</div> : null}
      <div className="relative w-full">{children}</div>
    </div>
  )
}

/** A catalogue row is a pure function of its context; this resolves the context the way the
 * hooks do (`motion.enabled()` at play time, the shared tokens) for a screen that calls
 * `play()` itself. */
export function choreoContext(scope: Element): ChoreoContext {
  return contextFrom(scope, { enabled: enabled(), reduced: reduced() }, { durations: MOTION_DURATIONS, eases: MOTION_EASES })
}
