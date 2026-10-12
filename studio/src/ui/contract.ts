// Prop TYPES for the §3 component kit, primitives #1–#6 and #10–#16. No implementations: the kit package
// writes `src/ui/*.tsx` against these, and every later package types against the same file, so
// a prop name is agreed once. #7–#9 (form controls) live in `./contract-forms.ts` and #17–#31 in `./contract-data.ts`; both
// are re-exported here, so callers import from this file only.
//
// Rules the types encode (§3 header): every control takes `disabledReason`, which renders a
// `title` plus visually-hidden text — the existing `activity-disabled-reason` convention — so a
// disabled button always says why; `data-*` and `data-testid` pass through via the element rest
// props; icons are `aria-hidden` unless labelled.
import type { ComponentPropsWithoutRef, ElementType, ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'

export * from './contract-data'
export * from './contract-forms'

// --- shared pieces ---------------------------------------------------------------------------

/** Mixed into every control. The reason is rendered, never swallowed: a person reading a greyed
 * button must be told what would enable it. */
export interface Disableable {
  disabled?: boolean
  disabledReason?: string
}

export type ControlSize = 'sm' | 'md'

/** Rest props for a native element minus the keys a primitive owns itself. */
export type NativeProps<E extends ElementType, Owned extends PropertyKey = never> =
  Omit<ComponentPropsWithoutRef<E>, Owned>

// --- #1 Button ---------------------------------------------------------------------------------

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'link'

/** `type="button"` is emitted FIRST (pinned attribute order in `workflowTab.test.ts:218`).
 * `primary` always emits the literal class `bg-brand-600` (`board.spec.ts:127,148`). `loading`
 * sets `aria-busy` and swaps the label for `loadingLabel` (the existing "…" convention). */
export interface ButtonProps extends Disableable, NativeProps<'button', 'disabled' | 'type'> {
  variant?: ButtonVariant
  size?: ControlSize
  loading?: boolean
  loadingLabel?: string
  icon?: LucideIcon
  iconEnd?: LucideIcon
  /** Full-width. */
  block?: boolean
  type?: 'button' | 'submit' | 'reset'
}

// --- #2 IconButton -----------------------------------------------------------------------------

/** `label` is required because the icon is the only visible content; it becomes `aria-label`.
 * `pressed` maps to `aria-pressed` for toggles (sidebar collapse, Mark as seen). */
export interface IconButtonProps extends Disableable, NativeProps<'button', 'disabled' | 'type' | 'aria-label'> {
  label: string
  icon: LucideIcon
  size?: ControlSize
  pressed?: boolean
}

// --- #3 Card -----------------------------------------------------------------------------------

export type CardTone = 'default' | 'inset' | 'warn' | 'error' | 'ok' | 'info'
export type CardPadding = 'none' | 'sm' | 'md'

/** `data-flip-id` passes through for the Flip choreographies (§4 #8). */
export interface CardProps extends NativeProps<'div'> {
  tone?: CardTone
  padding?: CardPadding
  interactive?: boolean
  as?: 'div' | 'section' | 'article' | 'li'
  header?: ReactNode
  footer?: ReactNode
  'data-flip-id'?: string
}

// --- #4 Notice ---------------------------------------------------------------------------------

export type NoticeTone = 'warn' | 'error' | 'ok' | 'info'
export type NoticeRole = 'alert' | 'status' | 'none'

/** `warn` classes contain the word `amber` (`SprintBoard.test.tsx:104`). `error` defaults to
 * `role="alert"`, `warn` to `role="status"`. Testids (`plugin-behind`, `document-error`,
 * `activities-warning`, `template-gaps`) pass through the rest props. */
export interface NoticeProps extends NativeProps<'div', 'title' | 'role'> {
  tone: NoticeTone
  title?: ReactNode
  icon?: LucideIcon
  actions?: ReactNode
  role?: NoticeRole
}

// --- #5 NoData ---------------------------------------------------------------------------------

/** Renders the literal words "no data" in `ink-3` (a word is never `ink-4`) plus `what`: the
 * sentence saying what would produce data ("Merge a spec to start the accepted-as-is line").
 * Never a 0. */
export interface NoDataProps extends NativeProps<'span'> {
  what: string
}

// --- #6 Eyebrow --------------------------------------------------------------------------------

/** The label voice: the `--text-eyebrow` type token (11 / 600 / 0.08 em, caps — `EYEBROW_TYPE_CLASS`)
 * in `--color-eyebrow` (= `ink-3`). A bare `text-eyebrow` class is the colour utility only. */
export interface EyebrowProps extends NativeProps<'p'> {
  as?: 'p' | 'h3' | 'span'
}

// --- #10 Chip ----------------------------------------------------------------------------------

export type ChipTone = 'neutral' | 'accent' | 'ok' | 'warn' | 'error' | 'signed' | 'current' | 'later' | 'mono'
export type ChipSize = 'xs' | 'sm'

/** How the chip's text is cased — a typographic role, never a colour: `identifier` is mono,
 * verbatim (spec ids, branches, `HIGH`); `state` is the plugin's status word as written
 * (`in-flight`, `NOT READY`); `label` is a plain word in sentence case. Default `label`. */
export type ChipCasing = 'identifier' | 'state' | 'label'

/** Colour is never the only signal: `dot` or an icon rides beside the text. `as="button"` keeps
 * `rounded-full` (chatAuthoring `aside button.rounded-full` pin) and carries `data-pressable`. */
export interface ChipProps extends Disableable, NativeProps<'span', 'disabled'> {
  tone?: ChipTone
  size?: ChipSize
  casing?: ChipCasing
  dot?: boolean
  icon?: LucideIcon
  as?: 'span' | 'button'
  onClick?: () => void
}

// --- #11 Badge ---------------------------------------------------------------------------------

export type BadgeKind = 'complete' | 'current' | 'locked' | 'now' | 'ready' | 'notReady'

/** The text is always rendered; the kind only picks colour and icon. */
export interface BadgeProps extends NativeProps<'span'> {
  kind: BadgeKind
}

// --- #12 StatusDot -----------------------------------------------------------------------------

export type DotStatus = 'ok' | 'warn' | 'error' | 'running' | 'idle'

/** `aria-hidden`: a sibling renders the text. `pulse` is honoured only while motion is enabled. */
export interface StatusDotProps extends NativeProps<'span'> {
  status: DotStatus
  pulse?: boolean
}

// --- #13 Skeleton ------------------------------------------------------------------------------

/** Counts are FIXED by the caller and never imply how many rows will arrive. `aria-hidden`; the
 * parent carries `aria-busy="true"` and keeps its existing text ("Reading the sprint…"). */
export interface SkeletonLineProps extends NativeProps<'span'> { width?: string }
export interface SkeletonBlockProps extends NativeProps<'div'> { lines?: number }
export interface SkeletonRowsProps extends NativeProps<'div'> { rows?: number }
export interface SkeletonTileProps extends NativeProps<'div'> {}

// --- #14 EmptyState ----------------------------------------------------------------------------

/** The six B6 figures, drawn in the product's own vocabulary (`src/ui/emptyFigures.tsx`): a rail
 * with hollow stations, three hollow bodies and a dashed tether, a page of rows, two speech
 * hairlines, a prompt caret, two pages in register. Each ≤ 120×72, `line-2` hairlines, at most
 * one `accent-400` dot, `aria-hidden`, no `<text>`, no digit. The Scorecard gets none. */
export type EmptyStateFigure = 'rail' | 'constellation' | 'page' | 'conversation' | 'prompt' | 'aligned'

/** Existing sentences are passed verbatim as `title` / `body` (tests find them by text).
 * `figure` replaces `icon` when both are given. */
export interface EmptyStateProps extends NativeProps<'div', 'title'> {
  icon?: LucideIcon
  figure?: EmptyStateFigure
  title: ReactNode
  body?: ReactNode
  action?: ReactNode
}

// --- #15 StatTile ------------------------------------------------------------------------------

/** `value: null` renders `NoData`; a number count-ups only from a known `previous` number
 * (§4 #11 — never from 0). `id` keys the value memory. `hint` is the sentence explaining the
 * measure, required so a tile is never a bare number. */
export interface StatTileProps extends NativeProps<'div', 'id'> {
  id: string
  label: ReactNode
  value: number | null
  unit?: string
  hint: ReactNode
  previous?: number | null
  /** What would produce data, forwarded to NoData when `value` is null. */
  noDataWhat?: string
}

// --- #16 ProgressBar ---------------------------------------------------------------------------

/** `role="progressbar"` with `aria-valuetext` ("3 of 9 stages done"). Width tweens only between
 * two real values; `null` renders a hairline with no fill. */
export interface ProgressBarProps extends NativeProps<'div', 'role'> {
  value: number | null
  max: number
  label: string
  /** Overrides the default "`value` of `max` `label`" text. */
  valueText?: string
}

// --- #32 PageHeader (round 2, S1) -------------------------------------------------------------

/** One header for every screen: `Eyebrow` (the area, "BUILD · BOARD") · `h2 data-page-heading
 * tabIndex=-1` with the screen's heading text BYTE-IDENTICAL to today (heading pins) · `lede`
 * `max-w-[64ch] text-ink-3` · right-aligned `actions`. `sticky` emits `STICKY_HEADER_CLASS`
 * (imported by name from `components/useStuck.ts`) and calls `useStuck`: transparent at rest,
 * opaque `surface-0` only under `data-stuck`. Rendered INSIDE the screen root (never `<main>`'s
 * first child on its own), so `main.firstElementChild` pins hold. */
export interface PageHeaderProps extends NativeProps<'header', 'title'> {
  eyebrow?: ReactNode
  title: ReactNode
  lede?: ReactNode
  actions?: ReactNode
  sticky?: boolean
  /** Rest props for the `<h2>` (an `id` for `aria-labelledby`, a `data-flip-id`). */
  headingProps?: NativeProps<'h2', 'children'>
}

// --- #33 Disclosure (round 2, C8) -------------------------------------------------------------

/** `<details>` / `<summary>` kept as the tags (sprint.spec counts `details[open]`; the summary's
 * children text nodes are untouched so text pins hold). Hides `::marker`, draws a lucide
 * `ChevronRight` rotating 90° on `[open]`, mirrors `open` onto `aria-expanded`. */
export interface DisclosureProps extends NativeProps<'details', 'open' | 'onToggle' | 'children'> {
  summary: ReactNode
  children?: ReactNode
  /** Controlled open state; omit for the native uncontrolled `<details>`. */
  open?: boolean
  /** Uncontrolled initial state. */
  defaultOpen?: boolean
  onToggle?: (open: boolean) => void
  /** Rest props for the `<summary>` (a `data-testid`, a class). */
  summaryProps?: NativeProps<'summary', 'children'>
}

// --- brand: ShepherdMark variant (round 2, B2) ------------------------------------------------

/** `flat` is the two-tone gate-S mark as drawn — moss frame half and S lobe, umber frame half
 * and S lobe (the mark everywhere in the app; the frame alone below 48 px). `depth` lays ONE
 * `linearGradient` (`--mark-depth-a` → `--mark-depth-b`, userSpaceOnUse 4,4 → 60,60) over the
 * mark's own silhouette — hero and icon only, ≥ 48 px, never on a control, chip, status, data
 * body or behind text. `src/components/brand/ShepherdMark.tsx` adds `variant?: ShepherdMarkVariant`
 * to its own `ShepherdMarkProps`; this is the frozen name both the component and its tests use. */
export type ShepherdMarkVariant = 'flat' | 'depth'
