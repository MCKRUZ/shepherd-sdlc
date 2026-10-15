// The two ways Shepherd reads the board back (build kit §5 B5-P4; ado-boards-mirror.md §12 items 6 and 10): `Pull now`
// reads the item's FIELDS into the ledger (`pull`), `Pull discussion` reads its COMMENTS into the local cache
// (`pull --discussion`). Each is one closed `AdoVerbRequest` through `runAdoVerb` — the renderer sends no argv, no flag
// and no name — and each is a `data-write`: both put a line in a ledger or a file on disk, so a person asks for them.
// Neither runs on a timer, on open, or after another verb; nothing here schedules anything.
//
// What it says is the plugin's, under the exit code alone. The plugin exits 0 on every path that is not a usage error,
// so an exit 0 is not yet "Done": a board that could not be reached (`unavailable`, with the plugin's reason) and a
// discussion switched off in the config (`discussion: "disabled"`) are read from the JSON and said in those words —
// Shepherd's own digit-free sentence for the first, the plugin's reason beneath it — and the host is told nothing was
// pulled. An item the plugin could not read or cache is listed by ref with its own reason, never dropped.
//
// `labels` renames a button for a host that puts the same two reads under its own words (the Today column's `Catch up`
// is the fields pull under another name); a kind it does not name keeps its default, and nothing else about the button
// changes — not the request, not the capability, not the `data-write`.
// Steering mode (`steering`) draws nothing: a committee screen does not ask the board for anything.
import { useState } from 'react'
import type { AdoVerbResult } from '../../../shared/types'
import { ADO_VERB_CAPABILITY, validateAdoVerbRequest, type AdoVerbRequest } from '../../../shared/adoVerbArgv'
import { EXIT_HEADING, exitHeading, NO_DATA, newerPlugin } from '../../../shared/reasons'
import { Button, cn } from '../../ui'
import { BRIDGE_MISSING, readAdoPlan, unavailableSentence } from './AdoApplyDialog'
import { runAdo } from './CommentComposer'

export type PullKind = 'fields' | 'discussion'
export type PullScope = 'both' | PullKind

/** Why the other button waits while one pull runs. */
export const PULL_RUNNING = 'A pull is already running'

const REQUEST: Record<PullKind, (id: string | undefined) => AdoVerbRequest> = {
  fields: (id) => (id === undefined ? { verb: 'pull' } : { verb: 'pull', id }),
  discussion: (id) => (id === undefined ? { verb: 'pullDiscussion' } : { verb: 'pullDiscussion', id }),
}

const LABEL: Record<PullKind, string> = { fields: 'Pull now', discussion: 'Pull discussion' }

export interface PullSaid {
  tone: 'ok' | 'warn' | 'error'
  /** The one line: the heading, then the plugin's own words. */
  line: string
  /** More of the plugin's words: an item it could not read, by ref. */
  notes: string[]
  /** True only when the board was read (so the host should re-read what it holds). */
  pulled: boolean
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const count = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : null)
const plural = (n: number, one: string): string => `${n} ${n === 1 ? one : `${one}s`}`

/** "2026-10-13 09:02" from the plugin's ISO stamp; null when there is none. */
function stampOf(at: unknown): string | null {
  if (typeof at !== 'string') return null
  const m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(at)
  return m ? `${m[1]} ${m[2]}` : at || null
}

const itemsOf = (json: Record<string, unknown>): Record<string, unknown>[] => (Array.isArray(json.items) ? json.items.filter(isObject) : [])

/** `<ref>: <reason>` for each item the plugin could not read or cache — its words, verbatim. */
function itemNotes(json: Record<string, unknown>): string[] {
  return itemsOf(json)
    .filter((i) => typeof i.unavailable === 'string' && i.unavailable !== '')
    .map((i) => `${typeof i.ref === 'string' ? i.ref : typeof i.work_item === 'number' ? `#${i.work_item}` : 'an item'}: ${String(i.unavailable)}`)
}

/** What a pull's answer says, from the exit code and the one JSON document — pure, so a test reads it without a DOM. */
export function pullSaid(kind: PullKind, result: AdoVerbResult | null): PullSaid {
  if (!result) return { tone: 'error', line: `${exitHeading(null)} · ${BRIDGE_MISSING}`, notes: [], pulled: false }
  if (result.exitCode !== 0) {
    const said = result.stderr.trim()
    return { tone: result.exitCode === 2 ? 'error' : 'warn', line: `${exitHeading(result.exitCode)}${said ? ` · ${said}` : ''}`, notes: [], pulled: false }
  }
  const json = result.json
  const reason = json && typeof json.reason === 'string' ? json.reason : ''
  if (json && json.unavailable === true) {
    const doc = readAdoPlan({ plan: null, unavailable: true, reason: json.reason, host: json.host ?? null })
    const sentence = doc ? unavailableSentence(doc) : NO_DATA
    return { tone: 'warn', line: reason ? `${sentence} · ${reason}` : sentence, notes: [], pulled: false }
  }
  if (kind === 'discussion' && json && json.discussion === 'disabled') {
    return { tone: 'warn', line: reason || NO_DATA, notes: [], pulled: false }
  }
  const recorded = json && isObject(json.recorded) ? json.recorded : null
  const observed = recorded ? count(recorded.observed) : null
  const drifted = recorded ? count(recorded.drift_seen) : null
  const read = json ? itemsOf(json).filter((i) => !(typeof i.unavailable === 'string' && i.unavailable !== '')).length : null
  const summary = kind === 'fields'
    ? (observed !== null ? [`${plural(observed, 'item')} read`, ...(drifted !== null ? [`${plural(drifted, 'drift row')} recorded`] : [])].join(', ') : null)
    : (read !== null && json && Array.isArray(json.items) ? `${plural(read, 'item')} read` : null)
  const stamp = stampOf(json?.as_of)
  const line = [EXIT_HEADING[0], stamp ? `as of ${stamp}` : null, summary].filter((part): part is string => Boolean(part)).join(' · ')
  return { tone: 'ok', line, notes: json ? itemNotes(json) : [], pulled: true }
}

const TONE_CLASS: Record<PullSaid['tone'], string> = {
  ok: 'text-status-ok-ink',
  warn: 'text-status-warn-ink',
  error: 'text-status-error-ink',
}

export interface PullNowProps {
  projectPath: string
  /** `generate_status.py --json` capabilities; null while unknown (main still refuses a verb the plugin lacks). */
  capabilities: readonly string[] | null
  /** `sdlc:<kind>:<id>` or `#<work item>`: pull only this item. Absent: every ledgered item. */
  itemRef?: string
  /** Which buttons: both (the default), the fields one, or the discussion one. */
  scope?: PullScope
  /** A button's words when the host has its own for it; a kind left out keeps `Pull now` / `Pull discussion`. */
  labels?: Partial<Record<PullKind, string>>
  /** Steering mode is read-only: nothing is drawn. */
  steering?: boolean
  /** Called after a pull that READ the board (exit 0, not unavailable, not switched off), with the plugin's answer. */
  onPulled?: (what: PullKind, result: AdoVerbResult) => void
  className?: string
}

export function PullNow({ projectPath, capabilities, itemRef, scope = 'both', labels, steering = false, onPulled, className }: PullNowProps) {
  const [busy, setBusy] = useState<PullKind | null>(null)
  const [said, setSaid] = useState<Partial<Record<PullKind, PullSaid>>>({})

  if (steering) return null

  const kinds: PullKind[] = scope === 'both' ? ['fields', 'discussion'] : [scope]
  const lacks = (cap: string) => (capabilities !== null && !capabilities.includes(cap) ? newerPlugin(cap) : null)
  const capability: Record<PullKind, string> = { fields: ADO_VERB_CAPABILITY.pull, discussion: ADO_VERB_CAPABILITY.pullDiscussion }

  const run = async (kind: PullKind) => {
    if (busy) return
    const request = REQUEST[kind](itemRef)
    const problems = validateAdoVerbRequest(request)
    setBusy(kind)
    setSaid((prev) => ({ ...prev, [kind]: undefined }))
    let view: PullSaid
    let result: AdoVerbResult | null = null
    try {
      if (problems.length > 0) {
        view = { tone: 'warn', line: `${exitHeading(null)} · ${problems.join('; ')}`, notes: [], pulled: false }
      } else {
        result = await runAdo(projectPath, request)
        view = pullSaid(kind, result)
      }
    } catch (err) {
      view = { tone: 'error', line: `${exitHeading(null)} · ${err instanceof Error ? err.message : 'The request did not reach the plugin.'}`, notes: [], pulled: false }
    } finally {
      setBusy(null)
    }
    setSaid((prev) => ({ ...prev, [kind]: view }))
    if (result && view.pulled) onPulled?.(kind, result)
  }

  return (
    <div data-testid="pull-now" className={cn('flex min-w-0 flex-col gap-1', className)}>
      <div className="flex flex-wrap items-center gap-1.5">
        {kinds.map((kind) => {
          const reason = lacks(capability[kind]) ?? (busy !== null && busy !== kind ? PULL_RUNNING : null)
          return (
            <Button key={kind} size="sm" variant="secondary" data-write="" data-pull={kind} loading={busy === kind} loadingLabel="Pulling…"
              disabled={Boolean(reason)} disabledReason={reason ?? undefined} onClick={() => { void run(kind) }}>
              {labels?.[kind] ?? LABEL[kind]}
            </Button>
          )
        })}
      </div>
      {(['fields', 'discussion'] as const).map((kind) => {
        const view = said[kind]
        if (!view) return null
        return (
          <div key={kind} role="status" data-testid={`${kind}-pull-result`} data-tone={view.tone} className={cn('space-y-0.5 text-xs [overflow-wrap:anywhere]', TONE_CLASS[view.tone])}>
            <p>{view.line}</p>
            {view.notes.map((note, i) => <p key={i} className="text-ink-3">{note}</p>)}
          </div>
        )
      })}
    </div>
  )
}
