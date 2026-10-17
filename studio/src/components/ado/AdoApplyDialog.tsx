// The Azure Boards apply dialog (build kit §5 B4-P3; ado-boards-mirror.md §12). A plan is a list of rows the
// plugin drew up (`ado_sync.py plan --json`, or a one-row `comment --json`); this dialog shows THOSE rows — the
// ops, notes and comment text the plugin printed, not a recomputation — then one Confirm that sends the plan's
// 12-hex hash back through the closed `runAdoVerb` table (`{ verb: 'apply', confirm: <hash> }`) and shows the
// plugin's answer under its exit code alone: 0 "Done", 1 "Not done", 2 "Refused by the plugin".
//
// The Confirm is the write (`data-write`). It is DISABLED with a reason, never hidden: nobody identified
// (`NO_ACTOR`), a plugin without `ado-apply` (`newerPlugin`), a plan that could not be drawn up (the plugin's own
// reason), a plan with no hash to confirm (the table's sentence). After any answer it is replaced by Close, so one
// plan is never sent twice by a double click; the plugin still refuses a stale hash and a mismatched az identity.
//
// Text is escaped: a comment's text is shown in a `<pre>` as characters, never as markup. The renderer never opens
// the mirror's own files; the plan arrives as the JSON a verb printed, handed in by whoever ran it.
import { useRef, useState } from 'react'
import type { ActorInfo, AdoVerbResult } from '../../../shared/types'
import { ADO_VERB_CAPABILITY, buildAdoVerbArgv, HASH, SCRIPT, type AdoVerbRequest } from '../../../shared/adoVerbArgv'
import {
  BOARDS_UNREACHABLE, exitHeading, NO_ACTOR, NO_DATA, newerPlugin, SCHEMA_NOT_DISCOVERED, WORK_ITEMS_NOT_SET_UP,
} from '../../../shared/reasons'
import { Button, Chip, Dialog, Notice, type ChipTone } from '../../ui'

export const APPLY_CONFIRM = 'Confirm — apply to Azure Boards'
export const BRIDGE_MISSING = 'This build of Shepherd has no Azure Boards bridge — update the app.'

/** One field op as `plan --json` prints it: a `replace`/`add` with the old and new value, or a tag change as
 * `add`/`remove` lists. Everything optional: a row the renderer cannot read is still shown, never dropped. */
export interface AdoPlanOp {
  op?: string | null
  path?: string | null
  old?: unknown
  new?: unknown
  add?: string[] | null
  remove?: string[] | null
  kept?: number | null
  /** A two-step create: the State the item is born in, where `new` is the State it is then moved to. The plugin
   * prints it as `(created Active, then moved)`, and apply sends two writes for the row. Absent otherwise. */
  via?: string | null
}

/** One plan row: a field row (`create` / `update` / `link` / `held` / …) or a comment row (`action: 'comment'`,
 * `status: draft | skipped | refused`, `text` exactly what the board will carry). */
export interface AdoPlanRow {
  ref: string | null
  target: string | null
  action: string
  status: string | null
  reason: string | null
  detail: string | null
  workItem: number | null
  rev: number | null
  type: string | null
  ops: AdoPlanOp[]
  notes: string[]
  text: string | null
}

export interface AdoPlanDoc {
  /** The 12-hex hash `apply --confirm` takes; null for a plan-only comment's draft and for an unavailable read. */
  plan: string | null
  rows: AdoPlanRow[]
  posture: string | null
  /** Who az will send as (a roster handle), null while az has not been read. */
  executedAs: string | null
  unavailable: boolean
  /** The plugin's sentence for an unavailable read. */
  reason: string | null
  /** An unavailable read that carries a `host` block: az was the reason. */
  hasHost: boolean
  applyOffered: boolean | null
  notes: string[]
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const text = (v: unknown): string | null => (typeof v === 'string' ? v : null)
const count = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const words = (v: unknown): string[] => (Array.isArray(v) ? v.filter((t): t is string => typeof t === 'string') : [])

function readOp(raw: unknown): AdoPlanOp | null {
  if (!isObject(raw)) return null
  return {
    op: text(raw.op), path: text(raw.path), old: raw.old ?? null, new: raw.new ?? null,
    add: Array.isArray(raw.add) ? words(raw.add) : null, remove: Array.isArray(raw.remove) ? words(raw.remove) : null, kept: count(raw.kept),
    via: text(raw.via),
  }
}

function readRow(raw: Record<string, unknown>): AdoPlanRow {
  return {
    ref: text(raw.ref), target: text(raw.target), action: text(raw.action) ?? 'unknown', status: text(raw.status), reason: text(raw.reason),
    detail: text(raw.detail), workItem: count(raw.work_item), rev: count(raw.rev), type: text(raw.type),
    ops: Array.isArray(raw.ops) ? raw.ops.map(readOp).filter((o): o is AdoPlanOp => o !== null) : [], notes: words(raw.notes), text: text(raw.text),
  }
}

/** The plan document as the plugin printed it, or null when the JSON is not one: no `plan` key, or a `plan` that
 * is not a 12-hex hash. `plan: null` is legitimate (a plan-only comment's draft; an unavailable read). A
 * `comment --json` document carries its one draft as `row`, not `rows`: read as a one-row plan. */
export function readAdoPlan(raw: unknown): AdoPlanDoc | null {
  if (!isObject(raw)) return null
  const unavailable = raw.unavailable === true
  if (!('plan' in raw) && !unavailable) return null
  const hash = text(raw.plan)
  if (raw.plan !== null && raw.plan !== undefined && (hash === null || !HASH.test(hash))) return null
  const rows = Array.isArray(raw.rows) ? raw.rows : isObject(raw.row) ? [raw.row] : []
  return {
    plan: hash, rows: rows.filter(isObject).map(readRow), posture: text(raw.posture), executedAs: text(raw.executed_as), unavailable,
    reason: text(raw.reason), hasHost: isObject(raw.host), applyOffered: typeof raw.apply_offered === 'boolean' ? raw.apply_offered : null,
    notes: words(raw.notes),
  }
}

/** Rows an `apply` would send: a create, an update, a drafted comment. A held, refused, unmapped, ambiguous or
 * skipped row needs a person first and is only listed. */
export function pendingRowCount(plan: AdoPlanDoc): number {
  return plan.rows.filter((r) => r.action === 'create' || r.action === 'update' || (r.action === 'comment' && r.status === 'draft')).length
}

/** The heading for a plan that could not be drawn up — one of Studio's own digit-free sentences, picked from what
 * the plugin said it could not do: az was the reason (a host block) → unreachable; "not configured" → not set up;
 * "no discovered schema" → not discovered. Anything else is "no data" with the plugin's reason kept beneath it:
 * the prose is matched only to pick a heading, never to decide anything. */
export function unavailableSentence(plan: AdoPlanDoc): string {
  if (plan.hasHost) return BOARDS_UNREACHABLE
  const reason = plan.reason ?? ''
  if (/^not configured\b/i.test(reason)) return WORK_ITEMS_NOT_SET_UP
  if (/^no discovered schema\b/i.test(reason)) return SCHEMA_NOT_DISCOVERED
  return NO_DATA
}

/** `spec 0004` from the ref, else the `#id` the row was addressed to, else "work item" (the plan's own `_who`). */
export function rowTitle(row: AdoPlanRow): string {
  const parts = row.ref ? row.ref.split(':') : []
  if (parts.length === 3) return `${parts[1]} ${parts[2]}`
  return row.target || 'work item'
}

const shown = (value: unknown): string => (value === null || value === undefined ? '(none)' : typeof value === 'string' ? value : JSON.stringify(value))

/** One op the way `ado_sync.py plan` prints it: `field  old → new`, a tag change as `+ tag  - tag`; a two-step
 * create's State op carries the plugin's own words after it, `(created Active, then moved)`, so the line does not
 * read as one write in the final State. */
export function opLine(op: AdoPlanOp): string {
  const path = op.path ?? ''
  const label = path.startsWith('/fields/') ? path.slice('/fields/'.length) : path
  if (op.add || op.remove) {
    const change = [...(op.add ?? []).map((t) => `+ ${t}`), ...(op.remove ?? []).map((t) => `- ${t}`)].join('  ')
    return `${label}  ${change || '(no change)'}`
  }
  const moved = op.via ? `  (created ${op.via}, then moved)` : ''
  return `${label}  ${shown(op.old)} → ${shown(op.new)}${moved}`
}

const rowLabel = (row: AdoPlanRow): string => (row.action === 'comment' && row.status ? `comment · ${row.status}` : row.action)

function rowTone(row: AdoPlanRow): ChipTone {
  const state = row.action === 'comment' ? row.status : row.action
  if (state === 'create' || state === 'update' || state === 'draft') return 'accent'
  if (state === 'refused') return 'error'
  if (state === 'link') return 'neutral'
  return 'warn'
}

/** The line the dialog previews: the argv the closed table builds (main adds `--repo`/`--state` after the verb). */
function previewLine(argv: readonly string[]): string {
  return `Run: ${SCRIPT} ${argv.map((a) => (/\s/.test(a) ? JSON.stringify(a) : a)).join(' ')}`
}

function PlanRow({ row }: { row: AdoPlanRow }) {
  return (
    <li data-plan-row="" data-action={row.action} data-ref={row.ref ?? undefined} className="rounded-[10px] border border-line-1 bg-surface-1 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs font-medium text-ink-1">{rowTitle(row)}</span>
        <Chip tone={rowTone(row)} casing="state" dot>{rowLabel(row)}</Chip>
        {row.workItem !== null ? <span className="font-mono text-xs text-ink-3">#{row.workItem}{row.rev !== null ? ` · rev ${row.rev}` : ''}</span> : null}
        {row.action === 'create' && row.type ? <span className="text-xs text-ink-3">type “{row.type}”</span> : null}
      </div>
      {row.reason ? <p className="mt-1 text-xs text-ink-2">{row.reason}{row.detail ? ` — ${row.detail}` : ''}</p> : null}
      {row.ops.length > 0 ? (
        <ul className="mt-1 space-y-0.5" aria-label="Changes">
          {row.ops.map((op, i) => <li key={i} data-plan-op="" className="whitespace-pre-wrap font-mono text-[11px] text-ink-1">{opLine(op)}</li>)}
        </ul>
      ) : null}
      {row.text !== null ? <pre data-plan-text="" className="mt-1 whitespace-pre-wrap rounded-[8px] bg-surface-2 px-2 py-1 font-mono text-[11px] text-ink-1">{row.text}</pre> : null}
      {row.notes.map((note, i) => <p key={i} className="mt-1 text-xs text-status-warn-ink">{note}</p>)}
    </li>
  )
}

export interface AdoApplyDialogProps {
  open: boolean
  projectPath: string
  plan: AdoPlanDoc
  /** `generate_status.py --json` capabilities; undefined while unknown (the plugin then decides). */
  capabilities?: readonly string[]
  actor: ActorInfo | null | undefined
  onClose: () => void
  /** Called once, after an exit 0: the host re-runs the reads it holds. */
  onApplied: () => void
}

type Outcome = { kind: 'ran'; result: AdoVerbResult } | { kind: 'bridge' }

export function AdoApplyDialog({ open, projectPath, plan, capabilities, actor, onClose, onApplied }: AdoApplyDialogProps) {
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [busy, setBusy] = useState(false)
  const confirmRef = useRef<HTMLButtonElement>(null)

  const request: AdoVerbRequest = { verb: 'apply', confirm: plan.plan ?? '' }
  const argv = buildAdoVerbArgv(request, actor?.name ?? '')
  const capability = ADO_VERB_CAPABILITY.apply
  const lacks = capabilities !== undefined && !capabilities.includes(capability) ? newerPlugin(capability) : null
  const disabledReason = !actor ? NO_ACTOR
    : lacks ?? (plan.unavailable ? (plan.reason ?? NO_DATA) : null) ?? (argv.ok ? null : argv.errors.join('; '))
  const pending = pendingRowCount(plan)

  const confirm = async () => {
    if (disabledReason || busy || outcome) return
    setBusy(true)
    try {
      const studio = window.studio as Partial<typeof window.studio> | undefined
      if (!studio || typeof studio.runAdoVerb !== 'function') { setOutcome({ kind: 'bridge' }); return }
      let result: AdoVerbResult
      try {
        result = await studio.runAdoVerb(projectPath, request)
      } catch (err) {
        result = { ok: false, exitCode: null, refused: false, stdout: '', stderr: err instanceof Error ? err.message : 'The request did not reach the plugin.', argv: [], verb: 'apply', json: null }
      }
      setOutcome({ kind: 'ran', result })
      if (result.exitCode === 0) onApplied()
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title="Apply this plan to Azure Boards" size="lg" initialFocus={confirmRef} data-testid="ado-apply-dialog"
      description="Shepherd sends exactly these rows, as you, once you confirm. The plugin refuses a plan that has changed since it was drawn up."
      footer={(
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>{outcome ? 'Close' : 'Cancel'}</Button>
          {!outcome && (
            <Button ref={confirmRef} variant="primary" data-write="" loading={busy} loadingLabel="Sending…" disabled={Boolean(disabledReason)} disabledReason={disabledReason ?? undefined} onClick={confirm}>
              {APPLY_CONFIRM}
            </Button>
          )}
        </div>
      )}
    >
      <div className="space-y-3 text-sm">
        <p className="font-mono text-[11px] text-ink-2" data-testid="ado-apply-argv">
          {previewLine(argv.ok ? argv.argv : ['apply', '--confirm', plan.plan ?? '(no plan)', '--json', '--by', actor?.name ?? '(no actor)'])}
        </p>
        <p className="text-xs text-ink-3" data-testid="ado-apply-actor">
          Recorded against {actor ? <><span className="font-medium text-ink-1">{actor.name}</span> ({actor.source})</> : <span className="text-status-error-ink">{NO_ACTOR}</span>}.
        </p>
        <p className="text-xs text-ink-3" data-testid="ado-apply-sender">
          {plan.executedAs
            ? <>Sent to the board as <span className="font-medium text-ink-1">{plan.executedAs}</span> — whoever az is signed in as.</>
            : 'Which identity az will send as has not been read yet.'}
          {plan.posture ? ` Posture: ${plan.posture}.` : ''}
        </p>
        {plan.unavailable ? (
          <Notice tone="warn" title={unavailableSentence(plan)} data-testid="ado-apply-unavailable">
            <p className="text-xs">{plan.reason ?? NO_DATA}</p>
          </Notice>
        ) : (
          <>
            <p className="text-xs text-ink-2" data-testid="ado-apply-count">
              {pending} {pending === 1 ? 'row' : 'rows'} of this plan would be sent; any other row needs a person first.
            </p>
            <ul className="space-y-2" aria-label="Plan rows" data-testid="ado-apply-rows">
              {plan.rows.map((row, i) => <PlanRow key={i} row={row} />)}
            </ul>
            {plan.notes.map((note, i) => <p key={i} className="text-xs text-ink-3">{note}</p>)}
          </>
        )}
        {outcome?.kind === 'bridge' ? (
          <Notice tone="error" title={exitHeading(null)} data-testid="ado-apply-result" data-exit-code="none">{BRIDGE_MISSING}</Notice>
        ) : null}
        {outcome?.kind === 'ran' ? <Answer result={outcome.result} /> : null}
      </div>
    </Dialog>
  )
}

/** The plugin's answer: the exit code alone picks the heading; stdout and stderr are shown verbatim. */
function Answer({ result }: { result: AdoVerbResult }) {
  const tone = result.exitCode === 0 ? 'ok' : result.exitCode === 2 ? 'error' : 'warn'
  const said = [result.stdout, result.stderr].filter((s) => s && s.trim()).join('\n').trim()
  return (
    <Notice tone={tone} title={exitHeading(result.exitCode)} data-testid="ado-apply-result" data-exit-code={result.exitCode ?? 'none'}>
      {result.argv.length > 0 ? <p className="font-mono text-[11px] text-ink-3">{previewLine(result.argv)}</p> : null}
      {said ? <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px] text-ink-1">{said}</pre> : <p className="mt-1 text-xs text-ink-3">The plugin printed nothing.</p>}
    </Notice>
  )
}
