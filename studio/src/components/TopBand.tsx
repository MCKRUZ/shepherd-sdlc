// The top band (togo-command-center.md §1, visual §4 "Shell"): 48 px on `surface-0` with a
// `line-1` hairline — the Shepherd mark and the project name as ONE button that leans out to the
// lifecycle home, the omnibar trigger (a `<button>` styled as a field, never an `<input>` at
// rest — the palette overlay owns the input while open), the needs-you chip, the sync chip, and
// the project-wide controls: Console (⌘J, `aria-pressed`), Appearance (a disclosure holding the
// three preference toggles), Settings (⌘,, `aria-current` when showing) and the `…` menu. The
// band is the sidebar's header reborn, so it keeps the one `<h1>` and sits inside the shell's
// first `<aside>` with the strip (Frame.tsx) — the a11y pins that read Search / Appearance /
// Console from that aside hold verbatim.
//
// Honesty: the needs-you chip is the LENGTH of `CommandCenter.needsYou` — a list the main
// process addressed to this person by exact handle — never a count Studio made; with no actor
// it is disabled with `reasons.SIGN_IN_TO_SEE`; with nothing addressed it says so in words.
import { memo, useEffect, useRef, useState, type ReactNode } from 'react'
import { Bell, Command, MessageSquare, Settings, SunMoon, Terminal, type LucideIcon } from 'lucide-react'
import type { ProjectStatus, SyncState } from '../../shared/types'
import { targetForHome, type Area, type NavTarget } from '../../shared/nav'
import { NOTHING_NEEDS_YOU } from '../../shared/reasons'
import { DensityToggle, DisabledReason, Icon, Kbd, MotionToggle, ThemeToggle, Tooltip, VisuallyHidden, cn, disabledReasonProps } from '../ui'
import { ShepherdMark } from './brand/ShepherdMark'
import { PRODUCT_NAME } from './brand/ShepherdWordmark'
import { OverflowMenu, type OverflowActions } from './OverflowMenu'
import { SyncChip } from './SyncChip'

/** The omnibar trigger's words. The accessible name starts with "Search" (the a11y pin's
 * `/^Search/`); the visible text is the keycap and the invitation. */
export const OMNIBAR_PLACEHOLDER = 'a spec id, a verb, or a place'
export const OMNIBAR_LABEL = `Search — ${OMNIBAR_PLACEHOLDER}`

/** What the chip knows: the list's length and, when the list is empty for a reason other than
 * "nothing", that reason (`CommandCenter.needsYouReason`). Null = the read has not landed. */
export interface NeedsYouFacts {
  count: number
  reason: string | null
}

export interface TopBandProps {
  status: ProjectStatus
  syncState: SyncState
  area: Area
  consoleOpen: boolean
  onToggleConsole: () => void
  onOpenPalette: () => void
  onNavigate: (target: NavTarget) => void
  needsYou?: NeedsYouFacts | null
  /** Where the chip leans: the sprint home's Today column in Build, the lifecycle home otherwise. */
  home: 'sprint' | 'lifecycle'
  currentStageId: string | null
  overflow: OverflowActions
  /** The band's Chat toggle (owner's v12 item 1): `aria-pressed` while the aside is open, so the
   * collapsed-by-default sprint home has a visible way back to the chat beside ⌘\ and the `…`
   * row. Absent → no button (a test that mounts the band alone). */
  chatOpen?: boolean
  onToggleChat?: () => void
  /** Steering mode (togo-command-center.md §3.5, visual §4): the band steps back to a
   * presentation — the mark and the project name (still the one `<h1>`) and ONE "Leave steering
   * (Esc)" — no omnibar, no needs-you chip, no console or settings controls: the committee's
   * room has no write affordance and no navigation to draw the eye. `onLeave` is where Esc goes. */
  presentation?: { onLeave: () => void }
}

export const LEAVE_STEERING = 'Leave steering (Esc)'

export const TopBand = memo(function TopBand({
  status, syncState, area, consoleOpen, onToggleConsole, onOpenPalette, onNavigate, needsYou = null, home, currentStageId, overflow, presentation,
  chatOpen, onToggleChat,
}: TopBandProps) {
  const toLifecycle = () => onNavigate(targetForHome('lifecycle', currentStageId))
  if (presentation) {
    return (
      <div data-topband="" data-testid="top-band" data-presentation="" className="flex min-h-12 shrink-0 items-center justify-between gap-3 border-b border-line-1 bg-steer-bg px-4 py-1">
        <h1 className="min-w-0 shrink text-sm font-semibold leading-5 text-ink-1">
          <span className="flex max-w-[20rem] items-center gap-2.5 py-1 pl-1 pr-2">
            <ShepherdMark frameOnly className="h-6 w-6 shrink-0" />
            <VisuallyHidden>{`${PRODUCT_NAME} · `}</VisuallyHidden>
            <span className="truncate">{status.project_name}</span>
          </span>
        </h1>
        <button type="button" data-pressable="" onClick={presentation.onLeave} className="inline-flex h-8 items-center gap-2 rounded-lg px-3 text-sm text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink-1">
          {LEAVE_STEERING}
        </button>
      </div>
    )
  }
  return (
    <div data-topband="" data-testid="top-band" className="flex min-h-12 shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-line-1 bg-surface-0 px-4 py-1">
      <h1 className="min-w-0 shrink text-sm font-semibold leading-5 text-ink-1">
        <button
          type="button"
          data-pressable=""
          onClick={toLifecycle}
          title={status.profile_id}
          className="flex max-w-[16rem] items-center gap-2.5 rounded-lg py-1 pl-1 pr-2 text-left transition-colors hover:bg-surface-2"
        >
          <ShepherdMark frameOnly className="h-6 w-6 shrink-0" />
          <VisuallyHidden>{`${PRODUCT_NAME} · `}</VisuallyHidden>
          <span className="truncate">{status.project_name}</span>
        </button>
      </h1>

      <button
        type="button"
        data-omnibar-trigger=""
        data-testid="omnibar-trigger"
        aria-label={OMNIBAR_LABEL}
        aria-haspopup="dialog"
        onClick={onOpenPalette}
        // `clamp(320px, 36vw, 560px)` at desktop widths; below that it shrinks with the band so a
        // 400 px window never scrolls sideways (stepAuthoring.spec).
        className="flex h-8 min-w-[8rem] flex-1 items-center gap-2 rounded-lg border border-line-2 bg-surface-2 px-3 text-left text-sm text-ink-3 transition-colors hover:border-line-3 hover:text-ink-2 sm:w-[clamp(320px,36vw,560px)] sm:flex-none"
      >
        <Icon icon={Command} size={16} className="text-ink-4" />
        <Kbd keys={['Mod', 'K']} />
        {' '}<span aria-hidden="true" className="text-ink-4">·</span>{' '}
        <span className="truncate">{OMNIBAR_PLACEHOLDER}</span>
      </button>

      <div className="ml-auto flex items-center gap-1.5">
        <NeedsYouChip facts={needsYou} onClick={() => onNavigate(targetForHome(home, currentStageId))} />
        <div className="hidden max-w-[14rem] sm:block"><SyncChip syncState={syncState} /></div>
        <BandButton label="Console" icon={Terminal} kbd={['Mod', 'J']} pressed={consoleOpen} onClick={onToggleConsole} />
        {onToggleChat && <BandButton label="Chat" icon={MessageSquare} kbd={['Mod', '\\']} pressed={chatOpen === true} onClick={onToggleChat} />}
        <AppearanceButton />
        <BandButton label="Settings" icon={Settings} kbd={['Mod', ',']} current={area === 'settings'} onClick={() => onNavigate({ area: 'settings' })} />
        <OverflowMenu actions={overflow} />
      </div>
    </div>
  )
})

/** The chip: a list length in `--text-lane-count`, words when the list is empty, disabled with
 * the plugin-side reason when nobody is signed in. Never a zero (visual §8 #6). */
export function NeedsYouChip({ facts, onClick }: { facts: NeedsYouFacts | null; onClick: () => void }) {
  if (facts === null) return null
  if (facts.reason) {
    return (
      <button type="button" disabled data-needs-you="" data-testid="needs-you-chip" {...disabledReasonProps(facts.reason, true)} className={cn(CHIP_BASE, 'bg-surface-2 text-ink-3 opacity-60')}>
        <Icon icon={Bell} size={16} />
        <span>needs you</span>
        <DisabledReason reason={facts.reason} disabled />
      </button>
    )
  }
  if (facts.count === 0) {
    return (
      <button type="button" data-needs-you="" data-testid="needs-you-chip" onClick={onClick} className={cn(CHIP_BASE, 'bg-surface-2 text-ink-3 hover:text-ink-2')}>
        <Icon icon={Bell} size={16} />
        <span>{NOTHING_NEEDS_YOU}</span>
      </button>
    )
  }
  return (
    <button type="button" data-needs-you="" data-testid="needs-you-chip" onClick={onClick} className={cn(CHIP_BASE, 'border border-today-act-line bg-today-act-bg text-today-act-ink hover:brightness-95')}>
      <Icon icon={Bell} size={16} />
      <span>needs you</span>
      {' '}<span aria-hidden="true">·</span>{' '}
      <span data-stat="needs-you" className="text-(length:--text-lane-count) font-(--text-lane-count--font-weight) leading-6 tracking-(--text-lane-count--letter-spacing) tabular-nums">{facts.count}</span>
    </button>
  )
}

const CHIP_BASE = 'inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium whitespace-nowrap transition-colors'

/** A 32 × 32 band control: a glyph, a visually hidden label (so its text content IS its name —
 * the documents e2e reads the lit entry's text), a tooltip with the key, and the one aria state
 * the control has (pressed · expanded · current). */
function BandButton({ label, icon, kbd, pressed, expanded, controls, current, onClick, children }: {
  label: string
  icon: LucideIcon
  kbd?: string[]
  pressed?: boolean
  expanded?: boolean
  controls?: string
  current?: boolean
  onClick: () => void
  children?: ReactNode
}) {
  const lit = Boolean(pressed || expanded || current)
  return (
    <Tooltip label={label} kbd={kbd}>
      <button
        type="button"
        data-pressable=""
        aria-pressed={pressed}
        aria-expanded={expanded}
        aria-controls={controls}
        aria-current={current ? 'page' : undefined}
        onClick={onClick}
        className={cn(
          'inline-flex h-8 w-8 items-center justify-center rounded-lg text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink-1',
          lit && 'bg-surface-2 text-ink-1',
        )}
      >
        <Icon icon={icon} size={18} />
        <VisuallyHidden>{label}</VisuallyHidden>
        {children}
      </button>
    </Tooltip>
  )
}

/** Theme / density / animations in a disclosure under the button (the sidebar's footer popover,
 * moved up). Each toggle is a `Segmented` of buttons, so the shell still holds no `<input>`. */
function AppearanceButton() {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const panelId = 'topband-appearance'
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (!rootRef.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])
  return (
    <div ref={rootRef} className="relative" onKeyDown={(e) => { if (e.key === 'Escape' && open) { e.stopPropagation(); setOpen(false) } }}>
      <BandButton label="Appearance" icon={SunMoon} expanded={open} controls={panelId} onClick={() => setOpen((v) => !v)} />
      {open ? (
        <div id={panelId} className="absolute right-0 top-full z-30 mt-1 grid gap-2 rounded-[14px] bg-surface-raised p-3 shadow-3 ring-1 ring-line-1">
          <ThemeToggle />
          <DensityToggle />
          <MotionToggle note="On overrides the system's reduced-motion setting." />
        </div>
      ) : null}
    </div>
  )
}
