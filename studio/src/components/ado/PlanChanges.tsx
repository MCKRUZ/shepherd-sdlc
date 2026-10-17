// `Plan changes` (build kit §5 B6-P3; K28; guardrails 26 and 28): ask the plugin what the board would need to hear about
// one item (a spec, a decision, a feature) or one sprint, and say what it found in ONE line — `N to create · M to
// update · K comments`. The request is the closed `plan` member of `AdoVerbRequest`, built and validated here and
// turned into argv by main from the pure table; the renderer sends no flag, no name and no `--by` (`plan` is a read
// that sends nothing to the board). The plan the plugin printed is read with `readAdoPlan` and handed to the host
// (`onPlanned`), whose apply dialog shows those very rows — this control never sends it anywhere itself.
//
// It is a `data-write`: `plan` writes a plan file and puts a `planned` line in the ledger, so a person asks for it.
// And a click is the ONLY trigger — no effect, no timer, nothing on mount, nothing after another verb — so a spec card
// that opens, a project that loads or a day that passes never asks the board for anything (guardrail 26).
//
// Honesty: a count the plugin did not print (`null`, absent, not a whole number) is `NO_DATA`, never a digit; a read
// that could not be made is one of Shepherd's own digit-free sentences with the plugin's reason beside it; an exit code
// is the truth (1 "Not done", 2 "Refused by the plugin"), and an exit 0 whose document is not a plan is "no data", not
// an empty plan. Steering mode draws nothing at all.
import { useState } from 'react'
import type { ActorInfo, AdoVerbResult } from '../../../shared/types'
import { ADO_VERB_CAPABILITY, validateAdoVerbRequest, type AdoVerbRequest } from '../../../shared/adoVerbArgv'
import { exitHeading, NO_ACTOR, NO_DATA, newerPlugin } from '../../../shared/reasons'
import { Button, cn } from '../../ui'
import { BRIDGE_MISSING, readAdoPlan, unavailableSentence, type AdoPlanDoc } from './AdoApplyDialog'
import { runAdo } from './CommentComposer'

export const PLAN_LABEL = 'Plan changes'

export interface PlanSaid {
  tone: 'ok' | 'warn' | 'error'
  /** The one line: the counts, or the sentence for what went wrong. */
  line: string
  /** The plan the plugin printed — also for one that could not be drawn up (`unavailable`, no rows); null when there was none to read. */
  doc: AdoPlanDoc | null
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
/** A count is a whole number, zero or more; anything else is not a count. */
const count = (v: unknown): number | null => (typeof v === 'number' && Number.isInteger(v) && v >= 0 ? v : null)

/** `N to create · M to update · K comments` from `plan --json`'s own `counts` (field rows only: "comment" is not one) and
 * `comments.draft`. A count that is missing, null or not a count reads `NO_DATA` in its place — never a digit. Pure. */
export function planCountsLine(json: Record<string, unknown>): string {
  const counts = isObject(json.counts) ? json.counts : {}
  const comments = isObject(json.comments) ? json.comments : {}
  const shown = (n: number | null) => (n === null ? NO_DATA : String(n))
  const drafted = count(comments.draft)
  return `${shown(count(counts.create))} to create · ${shown(count(counts.update))} to update · ${shown(drafted)} ${drafted === 1 ? 'comment' : 'comments'}`
}

/** What a plan's answer says, from the exit code and the one JSON document — pure, so a test reads it without a DOM. */
export function planSaid(result: AdoVerbResult | null): PlanSaid {
  if (!result) return { tone: 'error', line: `${exitHeading(null)} · ${BRIDGE_MISSING}`, doc: null }
  if (result.exitCode !== 0) {
    const said = result.stderr.trim()
    return { tone: result.exitCode === 2 ? 'error' : 'warn', line: `${exitHeading(result.exitCode)}${said ? ` · ${said}` : ''}`, doc: null }
  }
  const doc = readAdoPlan(result.json)
  if (!doc || !result.json) return { tone: 'warn', line: `${NO_DATA} · the plugin printed no plan`, doc: null }
  if (doc.unavailable) {
    const sentence = unavailableSentence(doc)
    return { tone: 'warn', line: doc.reason ? `${sentence} · ${doc.reason}` : sentence, doc }
  }
  return { tone: 'ok', line: planCountsLine(result.json), doc }
}

const TONE_CLASS: Record<PlanSaid['tone'], string> = {
  ok: 'text-ink-2',
  warn: 'text-status-warn-ink',
  error: 'text-status-error-ink',
}

export interface PlanChangesProps {
  projectPath: string
  /** `generate_status.py --json` capabilities; null/undefined while unknown (main still refuses a verb the plugin lacks). */
  capabilities: readonly string[] | null | undefined
  /** The item to plan: its kind and id (`spec`, `0008`). Absent when `sprint` is given. */
  kind?: string
  id?: string
  /** The sprint to plan (`S07`): every item on its slate. Absent when `kind` and `id` are given. */
  sprint?: string
  /** The button's words; `Plan changes` unless the host has its own. */
  label?: string
  /** Who is signed in: `null` is known-nobody (disabled with `NO_ACTOR`, as main refuses every verb without one); absent is "not read". */
  actor?: ActorInfo | null
  /** Steering mode is read-only: nothing is drawn. */
  steering?: boolean
  /** Called with the plan the plugin printed, once an exit 0 answered with a plan document. */
  onPlanned?: (plan: AdoPlanDoc) => void
  className?: string
}

export function PlanChanges({ projectPath, capabilities, kind, id, sprint, label = PLAN_LABEL, actor, steering = false, onPlanned, className }: PlanChangesProps) {
  const [busy, setBusy] = useState(false)
  const [said, setSaid] = useState<PlanSaid | null>(null)

  if (steering) return null

  const capability = ADO_VERB_CAPABILITY.plan
  const lacks = capabilities != null && !capabilities.includes(capability) ? newerPlugin(capability) : null
  const reason = lacks ?? (actor === null ? NO_ACTOR : null)

  const run = async () => {
    if (busy || reason) return
    const request: AdoVerbRequest = sprint !== undefined ? { verb: 'plan', sprint } : { verb: 'plan', kind, id }
    const problems = validateAdoVerbRequest(request)
    setBusy(true)
    setSaid(null)
    let view: PlanSaid
    try {
      if (problems.length > 0) view = { tone: 'warn', line: `${exitHeading(null)} · ${problems.join('; ')}`, doc: null }
      else view = planSaid(await runAdo(projectPath, request))
    } catch (err) {
      view = { tone: 'error', line: `${exitHeading(null)} · ${err instanceof Error ? err.message : 'The request did not reach the plugin.'}`, doc: null }
    } finally {
      setBusy(false)
    }
    setSaid(view)
    if (view.doc) onPlanned?.(view.doc)
  }

  return (
    <div data-testid="plan-changes" className={cn('flex min-w-0 flex-col gap-1', className)}>
      <div>
        <Button size="sm" variant="secondary" data-write="" data-plan="" loading={busy} loadingLabel="Planning…" disabled={Boolean(reason)} disabledReason={reason ?? undefined} onClick={() => { void run() }}>
          {label}
        </Button>
      </div>
      {said ? <p role="status" data-testid="plan-result" data-tone={said.tone} className={cn('m-0 text-xs [overflow-wrap:anywhere]', TONE_CLASS[said.tone])}>{said.line}</p> : null}
    </div>
  )
}
