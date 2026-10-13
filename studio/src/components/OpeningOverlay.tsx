import { useEffect, useRef, useState } from 'react'
import { formatElapsed } from '../../shared/elapsed'
import { ProgressRing } from '../ui'
import { useStudioGSAP } from '../motion/useStudioGSAP'
import { motion } from '../motion/motion'
import { MOTION_DURATIONS, MOTION_EASES } from '../motion/contract'
import { contextFrom, openingOverlay } from '../motion/choreo'
import { S_CENTRE, ShepherdMark } from './brand/ShepherdMark'

/** Shown while a project is being opened — or any other action that reads or writes through the
 * plugin and can take several seconds, where nothing on screen otherwise looks like it did
 * anything, so people click again. Title and subtitle default to the original opening-a-project
 * wording, so that call site is unchanged; a caller doing something else (signing off a phase)
 * passes its own.
 *
 * It covers the whole window and takes the keyboard as well as the pointer, so nothing behind it
 * can be operated until the action finishes or fails. It shows a running clock, because "still
 * working" is only believable if something visibly moves.
 *
 * Observatory (§4 #16, §6.3): only the root's OPACITY ever animates — its geometry is in place
 * from the first paint so documents.spec's `coversWindow` holds at any moment — and the card is
 * focused while it is up so assistive tech reads the dialog's label, with focus handed back to
 * whatever had it once the overlay goes. It renders in place, not through a portal, so
 * `renderToStaticMarkup` (openingOverlay.test.ts) still sees it.
 *
 * G1-5: the first thing the app does is draw its own mark once — a signature, not a spinner —
 * then rests. The 14 px ring beside the ticking clock stays the honest "still working" cue.
 * Round 2 (B2): the card mark is 48 px Depth — one of the gradient's three sanctioned homes. */
export function OpeningOverlay({
  projectName,
  startedAt,
  title,
  subtitle,
}: {
  projectName: string
  startedAt: number
  title?: string
  subtitle?: string
}) {
  const [now, setNow] = useState(() => Date.now())
  const rootRef = useRef<HTMLDivElement>(null)
  const cardRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(tick)
  }, [])

  // The pointer is blocked by the overlay itself; this blocks the keyboard, so Tab and Enter
  // cannot reach a control underneath. Focus moves INTO the card (tabIndex -1, so it never joins
  // the tab order) rather than merely being dropped, and goes back where it was on unmount — a
  // navigation that lands while the overlay is up finds its focus target only afterwards.
  useEffect(() => {
    const block = (e: KeyboardEvent) => {
      if (e.key === 'Tab' || e.key === 'Enter' || e.key === ' ') e.preventDefault()
    }
    window.addEventListener('keydown', block, true)
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    previous?.blur()
    cardRef.current?.focus({ preventScroll: true })
    return () => {
      window.removeEventListener('keydown', block, true)
      if (previous && previous.isConnected && document.contains(previous)) previous.focus({ preventScroll: true })
    }
  }, [])

  // Choreography #16: root fades in (150 ms), card settles (220 ms), then the mark draws in —
  // the two frame halves are traced as outlines, the frame fills as the trace hands over, then
  // the S settles into its seat on the tab — ≈ 0.76 s, under the 0.9 s ceremony cap. ONCE, at
  // mount. In MODE=test and with motion off the stub applies the end state at once: a filled,
  // static mark. The explicit `dependencies: []` is the intent spelled out: this component
  // re-renders every 250 ms for its clock, and nothing may replay.
  useStudioGSAP((g) => {
    const root = rootRef.current
    const card = cardRef.current
    if (!root) return
    const ctx = contextFrom(root, { enabled: motion.enabled(), reduced: motion.reduced() }, { durations: MOTION_DURATIONS, eases: MOTION_EASES })
    openingOverlay.play(ctx, { root, card })
    const frame = card?.querySelector('[data-mark-frame]')
    const s = card?.querySelector('[data-mark-s]')
    if (!frame || !s) return
    const halves = frame.querySelectorAll(':scope > path')
    const tl = g.timeline()
    // Trace: both halves at once, each in its own tone.
    tl.to(halves, { attr: { 'stroke-dashoffset': 0 }, duration: 0.42, ease: 'expo.out' }, 0.05)
    // Fill: the group's fill-opacity carries the tones and, in Depth, the overlay with them; the
    // stroke fades as the fill lands so the resting frame is never fatter than drawn.
    tl.to(frame, { attr: { 'fill-opacity': 1 }, duration: 0.16, ease: 'power2.out' }, 0.40)
    tl.to(halves, { attr: { 'stroke-opacity': 0 }, duration: 0.16, ease: 'power2.out' }, 0.40)
    // The S arrives last, scaling from its own centre (`svgOrigin` is in the mark's 64 units).
    tl.fromTo(s, { opacity: 0, scale: 0.85 }, { opacity: 1, scale: 1, svgOrigin: `${S_CENTRE.x} ${S_CENTRE.y}`, duration: 0.24, ease: 'expo.out' }, 0.52)
  }, { scope: rootRef, dependencies: [] })

  return (
    <div
      ref={rootRef}
      data-testid="opening-overlay"
      role="alertdialog"
      aria-modal="true"
      aria-busy="true"
      aria-label={title ?? `Opening ${projectName}`}
      className="fixed inset-0 z-50 flex cursor-progress items-center justify-center bg-scrim backdrop-blur-[1px]"
    >
      <div
        ref={cardRef}
        tabIndex={-1}
        className="w-[320px] rounded-[20px] border border-line-1 bg-surface-1 p-6 text-center shadow-3 outline-none"
      >
        {/* 48 px Depth (brand §4): the card is one of the mark's hero homes. The draw-in traces
            the frame halves in their own tones, fills them (Depth arriving with the fill), then
            seats the S. */}
        <ShepherdMark draw variant="depth" className="mx-auto h-12 w-12" />
        <p className="mt-4 text-sm font-medium text-ink-1">{title ?? `Opening ${projectName}…`}</p>
        <p className="mt-1 text-xs text-ink-3">{subtitle ?? 'Reading the project through the plugin.'}</p>
        {/* The ring's `animate-spin` keeps the "still working" signal while the mark rests;
            `value: null` is an indeterminate arc, never a fabricated 0%. */}
        <p className="mt-3 inline-flex items-center gap-2 font-mono text-lg tabular-nums text-ink-2">
          <ProgressRing value={null} size={14} label="Working" />
          <span>{formatElapsed(now - startedAt)}</span>
        </p>
      </div>
    </div>
  )
}
