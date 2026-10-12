// What the Sprint view says about the sprint `sprint.py status --json` reports — pure, shared by
// main and renderer so the process that reads the plugin and the screen that draws it agree.
//
// Two rules from the sprint layer are kept here on purpose. First, "no data" is never a zero: a
// verdict with no ledger line to age from, a WIP cap nobody stated, a sprint with nothing slated —
// each reads as the absence it is. Second, counts only: nothing here totals work per person. A
// slate row names its next owner because the plugin does; no helper sums rows by that name.

import type {
  BoardRow, SprintDecisions, SprintMixTier, SprintRecord, SprintSlateRow, SprintVerdictPending, SprintView,
} from './types'

/** The `capabilities` entry (generate_status.py --json) the view needs from the installed plugin. */
export const SPRINT_CAPABILITY = 'sprint-status'

/** A human-typed sprint id: S07, S12, S123 — the plugin's own rule (sprint_model.SPRINT_ID_RE). */
export const SPRINT_ID = /^S\d{2,}$/

export function isSprintId(value: unknown): value is string {
  return typeof value === 'string' && SPRINT_ID.test(value)
}

export const NO_DATA = 'no data'

/** "3 business days", "1 business day", "today" for a 0 the plugin DID report (a verdict asked for
 * this morning is not an absence, and "0 business days" reads like one), or "no data" when the
 * plugin could not age it at all. */
export function businessDays(n: number | null): string {
  if (n === null) return NO_DATA
  if (n === 0) return 'today'
  return `${n} business day${n === 1 ? '' : 's'}`
}

/** The line after the dates: how long is left, or who closed it. Null when there is nothing honest
 * to say (an open sprint whose window the plugin could not read). */
export function remainingLabel(sprint: SprintRecord): string | null {
  if (sprint.state === 'closed') return sprint.closedBy ? `closed by ${sprint.closedBy}` : 'closed'
  if (sprint.days.remaining === null) return null
  if (sprint.days.remaining === 0) return 'ends today'
  return `${businessDays(sprint.days.remaining)} remaining`
}

/** A spec's status is a STATE, so it wears a chip (G4-4), on the Board and the slate alike —
 * one map, here, so the two screens cannot disagree. `ready` is the same idea as the stage's
 * "now" and takes the current tone; in-flight is the accent; merged is the one signed fact;
 * draft and deferred are quiet. Studio never computes the status — the word is the plugin's.
 * The union is a subset of the kit's `ChipTone`, spelled here because `shared/` is also the
 * main process's and must not import the renderer's kit. */
export type SpecStatusTone = 'current' | 'accent' | 'ok' | 'neutral'

export function statusTone(status: string): SpecStatusTone {
  switch (status.trim().toLowerCase()) {
    case 'ready': return 'current'
    case 'in-flight': return 'accent'
    case 'merged': return 'ok'
    default: return 'neutral'
  }
}

/** Verdicts pending, grouped per spec in the plugin's order — a GROUPING only: the lanes and
 * their ages are the plugin's rows, nothing is counted or summed, and a spec appears once with
 * the lanes it is waiting on beneath it. */
export function groupVerdicts(pending: readonly SprintVerdictPending[]): Array<{ spec: string; lanes: SprintVerdictPending[] }> {
  const groups = new Map<string, SprintVerdictPending[]>()
  for (const v of pending) {
    const existing = groups.get(v.spec)
    if (existing) existing.push(v)
    else groups.set(v.spec, [v])
  }
  return [...groups.entries()].map(([spec, lanes]) => ({ spec, lanes }))
}

export type ChipTone = 'neutral' | 'good' | 'attention' | 'muted'

/** planning / ready / closed as a chip; anything else the plugin may say later is shown as it is.
 * Kept for the old Sprint board; the command-center screens use `sprintStateChip` below. */
export function stateChip(state: string): { label: string; tone: ChipTone } {
  switch (state) {
    case 'planning': return { label: 'planning', tone: 'attention' }
    case 'ready': return { label: 'ready', tone: 'good' }
    case 'closed': return { label: 'closed', tone: 'muted' }
    default: return { label: state || 'unknown', tone: 'neutral' }
  }
}

/** The sprint's state as ONE chip on every command-center screen (header, planning, close) —
 * the kit tone names, spelled here so `shared/` stays free of the renderer. A state is not a
 * measured wait or a host verdict, so it never wears amber or green (visual §8 #4): `planning`
 * is a neutral chip with a dot, `ready` is "now" (the current tone), `closed` is neutral and
 * muted; a word the plugin adds later is shown as it is, neutral. */
export type SprintStateTone = 'neutral' | 'current'

export function sprintStateChip(state: string): { label: string; tone: SprintStateTone; dot: boolean; muted: boolean } {
  switch (state) {
    case 'planning': return { label: 'planning', tone: 'neutral', dot: true, muted: false }
    case 'ready': return { label: 'ready', tone: 'current', dot: true, muted: false }
    case 'closed': return { label: 'closed', tone: 'neutral', dot: false, muted: true }
    default: return { label: state || 'unknown', tone: 'neutral', dot: false, muted: false }
  }
}

/** Risk chips keep the kit's tones everywhere a tier is drawn (visual §2): HIGH = error,
 * MEDIUM = warn, LOW = neutral; a tier the plugin wrote in another word is neutral too — never a
 * colour Studio chose. ONE table, so the Board, the lanes, planning and the spec card agree. */
export type RiskTone = 'error' | 'warn' | 'neutral'

export function riskTone(risk: string): RiskTone {
  switch (risk.trim().toUpperCase()) {
    case 'HIGH': return 'error'
    case 'MEDIUM': return 'warn'
    default: return 'neutral'
  }
}

/** The Definition-of-Ready verdict as ONE chip tone (visual §8 #4): READY is "now" (`current`
 * with a dot — a passing check is the checker's verdict, never a host success, so never green);
 * NOT READY is the warn tone the checker's own MUST lines earn; anything else is neutral. */
export type DorTone = 'current' | 'warn' | 'neutral'

export function dorChipTone(dor: string | null | undefined): DorTone {
  if (dor === 'READY') return 'current'
  if (dor === 'NOT READY') return 'warn'
  return 'neutral'
}

export function targetLabel(target: number | null): string {
  return target === null ? NO_DATA : `${target} spec${target === 1 ? '' : 's'}`
}

export interface MixChip {
  tier: string
  actual: number
  target: number | null
  /** "HIGH 1/2", or "HIGH 1/no target" for a tier the mix did not name. */
  label: string
}

const TIER_ORDER = ['HIGH', 'MEDIUM', 'LOW']

/** The plugin's per-tier actual/target, in risk order. Empty when the plugin reported no mix. */
export function mixChips(mix: Record<string, SprintMixTier>): MixChip[] {
  const tiers = Object.keys(mix).sort((a, b) => {
    const ia = TIER_ORDER.indexOf(a), ib = TIER_ORDER.indexOf(b)
    return (ia === -1 ? TIER_ORDER.length : ia) - (ib === -1 ? TIER_ORDER.length : ib) || a.localeCompare(b)
  })
  return tiers.map((tier) => {
    const { actual, target } = mix[tier]
    return { tier, actual, target, label: `${tier} ${actual}/${target === null ? 'no target' : target}` }
  })
}

/** "2 in flight · cap 4", "2 in flight · cap not set", or "no data" when the count is unknown. */
export function wipLabel(wip: { inFlight: number | null; cap: number | null }): string {
  if (wip.inFlight === null) return NO_DATA
  return `${wip.inFlight} in flight · cap ${wip.cap === null ? 'not set' : wip.cap}`
}

/** "3 of 4 ready" — only when something is slated; an empty slate is "no data", not "0 of 0". */
export function readinessLabel(view: SprintView): string {
  if (!view.hasData) return NO_DATA
  return `${view.readiness.ready} of ${view.readiness.total} ready`
}

/** A review lane's value as a badge. An empty value is "not recorded" — the plugin treats it as
 * pending, and the badge says that rather than inventing a verdict. */
export function laneBadge(value: string): { label: string; tone: ChipTone } {
  switch (value) {
    case 'accepted': return { label: 'accepted', tone: 'good' }
    case 'returned': return { label: 'returned', tone: 'attention' }
    case 'n-a': return { label: 'n/a', tone: 'muted' }
    case 'pending': return { label: 'pending', tone: 'neutral' }
    case '': return { label: 'not recorded', tone: 'neutral' }
    default: return { label: value, tone: 'neutral' }
  }
}

/** Decisions due, from the plugin's decision-log summary: "no decision-log" when there is none. */
export function decisionsLabel(decisions: SprintDecisions | null): string {
  if (decisions === null) return `${NO_DATA} — no decision-log`
  const overdue = decisions.overdue.length
  return overdue === 0 ? `${decisions.open} open` : `${decisions.open} open · ${overdue} overdue`
}

/** The sentence under "Next up". The plugin decides which spec; this only words its absence. */
export function nextUpLabel(view: SprintView): string {
  if (view.nextUp) {
    const cap = view.wip.cap !== null && view.wip.inFlight !== null ? `, WIP ${view.wip.inFlight} of ${view.wip.cap}` : ''
    return `${view.nextUp} — READY, dependencies merged${cap}`
  }
  return view.hasData ? 'no slated spec is READY with merged dependencies inside the WIP cap' : NO_DATA
}

/** What to say instead of a slate when there is none to show. Null when there is a slate. */
export function emptyMessage(view: SprintView): string | null {
  if (view.sprint === null) return view.note ?? 'No sprint — open one with /sprd-sprint new.'
  if (view.slate.length > 0) return null
  if (view.sprint.state === 'closed') return `Closed; see .sdlc/reports/sprint-${view.sprint.id}-review.html. Start the next sprint with /sprd-sprint new.`
  return 'Nothing slated yet — propose a slate with /sprd-sprint slate.'
}

/** A slate row as the spec view takes it. The board's row carries the people and the live pull
 * request; a slate row carries neither, and the spec view reads what it needs from the spec file
 * by `path`, so an empty string here is "not known from this screen", not a claim. */
export function slateToBoardRow(row: SprintSlateRow): BoardRow {
  return {
    spec: row.id, name: row.name, path: row.relPath, title: '', status: row.status, risk: row.risk,
    team: '', channel: row.channel, owner: '', developer: '', checker: '', branch: '', pullRequest: null,
    sprint: row.sprint, nextOwner: row.nextOwner, engReview: row.engReview, dataReview: row.dataReview,
    dependsOn: row.dependsOn,
  }
}
