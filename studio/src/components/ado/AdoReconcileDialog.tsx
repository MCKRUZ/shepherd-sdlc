// The Azure Boards reconcile dialog (build kit §5 B5-P4; ado-boards-mirror.md §12 item 6): the VerbDialog pattern for
// settling the drift `pull` recorded. A drift item is a list of fields the board changed; for each one a person says
// what to do with one `Segmented` — leave it open, take the board's value (through the verb that owns the field), keep
// the repository's, acknowledge it (an owner), or say it is not drift (a reason) — next to the field's own diff, drawn
// by the existing `ClashDiff` (Yours / Theirs). The preview IS the argv line each chosen field would run, built by the
// closed table (`buildAdoVerbArgv`; main adds `--repo`/`--state` after the verb), and ONE Confirm — the dialog's only
// `data-write` — runs one `reconcile` per chosen field, in order, as the signed-in person, and stops at the first the
// plugin did not settle (the rest are listed as not run: nothing is skipped silently, nothing is retried).
//
// The plugin is the judge. Shepherd offers every take on every field and shows the plugin's own proposal for the row
// (`pull --json` `proposals[]`); a take the field's class has no word for, a spec's State, an AI `--by`: the plugin
// refuses, and its words are shown under its exit code alone (0 "Done", 1 "Not done", 2 "Refused by the plugin"). What
// Shepherd checks is shape — an owner for `ack`, a reason for `not-drift`, an sdlc ref — through `validateAdoVerbRequest`.
//
// Rows come from the document `pull --json` printed (`readDriftItems`): per field `old`/`new` are the BOARD's value
// when the item was last sent and now. The plugin leaves both out for text, person and relation fields, so such a field
// is said to have no printed values — never drawn as an empty diff. A field the table cannot name (a whole-item row for
// an item gone from the board, `relations:parent`) is shown with the plugin's proposal and the sentence that says where
// to settle it; Shepherd offers no control it cannot honour.
//
// `--take ado` on a text field the board owns writes `<artifact>.proposed` beside the artifact and never the artifact
// itself: when a result's JSON carries `proposed`, the result names that path and says the artifact was not changed.
//
// Text is escaped (a React text node, never markup). Steering mode (`steering`) draws nothing at all.
import { useRef, useState } from 'react'
import type { ActorInfo, AdoVerbResult } from '../../../shared/types'
import {
  ADO_VERB_CAPABILITY, buildAdoVerbArgv, FIELD, SCRIPT, validateAdoVerbRequest, type AdoTake, type AdoVerbRequest,
} from '../../../shared/adoVerbArgv'
import { exitHeading, NO_ACTOR, newerPlugin } from '../../../shared/reasons'
import { Button, Chip, Dialog, Field, Input, Segmented, cn, type SegmentedOption } from '../../ui'
import { ClashDiff } from '../ClashDiff'
import { BRIDGE_MISSING } from './AdoApplyDialog'

export const RECONCILE_CONFIRM = 'Confirm — settle the chosen rows'
/** Why Confirm waits while every field is left open. */
export const CHOOSE_A_TAKE = 'Choose what to do about at least one field'
const NO_VALUES = 'The plugin does not print the value of a text, person or relation field — read the change on the board.'
const SETTLE_ELSEWHERE = 'Shepherd sends only a named field; settle this row with /sprd-ado reconcile.'

/** The classes a drift row is NOT (`ado_sync_model.NOT_DRIFT_CLASSES`: nothing to dispose of), and the two whole-item
 * classes `pull` records as a row with no field (`ado_sync._drift_events`). Pinned against the plugin's text. */
export const NOT_DRIFT_CLASSES: readonly string[] = ['IN_SYNC', 'COMMENT', 'NEVER_PUSHED']
export const WHOLE_ITEM_CLASSES: readonly string[] = ['DELETED_IN_ADO', 'ORPHAN_IN_REPO']

export interface AdoDriftProposal {
  /** The plugin's word for what a person does: `reconcile`, `by-hand` or `report`. */
  action: string
  /** Its sentence — never free text from the board. */
  text: string
}

export interface AdoDriftField {
  /** `null` for a row about the item itself (gone from the board, source gone from the repository). */
  field: string | null
  class: string
  owner: string | null
  rev: number | null
  /** The plugin printed this field's old and new value (it leaves them out for text, person and relation fields). */
  hasValues: boolean
  old: string
  new: string
  proposal: AdoDriftProposal | null
}

export interface AdoDriftItem {
  ref: string
  kind: string | null
  workItem: number | null
  class: string | null
  fields: AdoDriftField[]
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const textOrNull = (v: unknown): string | null => (typeof v === 'string' ? v : null)
const numberOrNull = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

/** A board value as the diff's text: a string as is, nothing as "(none)", anything else as JSON. */
function valueText(v: unknown): string {
  if (v === null || v === undefined) return '(none)'
  return typeof v === 'string' ? v : JSON.stringify(v)
}

/** The drift rows of the document `pull --json` (or `drift --json`) printed: every item with something to settle, in the
 * plugin's order, each field with the plugin's proposal for it. An item the plugin could not read, a field that is not
 * drift, and a document that is not a pull at all are left out — never an empty row. */
export function readDriftItems(raw: unknown): AdoDriftItem[] {
  if (!isObject(raw) || !Array.isArray(raw.items)) return []
  const proposals = Array.isArray(raw.proposals) ? raw.proposals.filter(isObject) : []
  const proposalFor = (ref: string, field: string | null): AdoDriftProposal | null => {
    const found = proposals.find((p) => p.ref === ref && (textOrNull(p.field) ?? null) === field)
    const text = found ? textOrNull(found.text) : null
    return found && text !== null ? { action: textOrNull(found.action) ?? 'report', text } : null
  }
  const out: AdoDriftItem[] = []
  for (const item of raw.items) {
    if (!isObject(item) || typeof item.ref !== 'string' || !item.ref) continue
    if (typeof item.unavailable === 'string' && item.unavailable !== '') continue
    const cls = textOrNull(item.class)
    const fields: AdoDriftField[] = (Array.isArray(item.fields) ? item.fields : []).filter(isObject)
      .filter((f) => typeof f.field === 'string' && typeof f.class === 'string' && !NOT_DRIFT_CLASSES.includes(f.class))
      .map((f) => ({
        field: f.field as string, class: f.class as string, owner: textOrNull(f.owner), rev: numberOrNull(f.rev), hasValues: 'new' in f,
        old: valueText(f.old), new: valueText(f.new), proposal: proposalFor(item.ref as string, f.field as string),
      }))
    if (cls !== null && WHOLE_ITEM_CLASSES.includes(cls)) {
      fields.push({ field: null, class: cls, owner: null, rev: numberOrNull(item.rev), hasValues: false, old: '', new: '', proposal: proposalFor(item.ref, null) })
    }
    if (fields.length > 0) out.push({ ref: item.ref, kind: textOrNull(item.kind), workItem: numberOrNull(item.work_item), class: cls, fields })
  }
  return out
}

type Choice = 'skip' | AdoTake
interface Pick {
  choice: Choice
  owner: string
  reason: string
}
const BLANK: Pick = { choice: 'skip', owner: '', reason: '' }

const OPTIONS: SegmentedOption<Choice>[] = [
  { value: 'skip', label: 'Leave open' },
  { value: 'ado', label: "Take the board's" },
  { value: 'sdlc', label: "Keep the repository's" },
  { value: 'ack', label: 'Acknowledge' },
  { value: 'not-drift', label: 'Not drift' },
]

/** The field the table can name: a work item field reference name (`FIELD`), never a whole-item row or a relation. */
const settleable = (f: AdoDriftField): f is AdoDriftField & { field: string } => f.field !== null && FIELD.test(f.field)

/** The line the dialog previews: the argv the closed table builds (main adds `--repo`/`--state` after the verb). */
function previewLine(argv: readonly string[]): string {
  return `Run: ${SCRIPT} ${argv.map((a) => (/\s/.test(a) ? JSON.stringify(a) : a)).join(' ')}`
}

/** What a result says about a `.proposed` draft, or null: the path the plugin printed (`proposed`, a string or an
 * object with `path`) and that the artifact itself was not changed; a `propose` child that exited 0 with no path key
 * says the same without naming it (the child's own words, shown beside, do). */
export function proposedSentence(json: Record<string, unknown> | null): string | null {
  if (!json) return null
  const given = json.proposed
  const path = typeof given === 'string' && given ? given : isObject(given) && typeof given.path === 'string' && given.path ? given.path : null
  const land = 'read the difference, then land it with /sprd-revise.'
  if (path) return `Wrote ${path} beside the artifact. ${path.replace(/\.proposed$/, '')} itself was not changed — ${land}`
  const child = isObject(json.child) ? json.child : null
  if (child && child.verb === 'propose' && child.exit === 0) return `A draft was written beside the artifact; the artifact itself was not changed — ${land}`
  return null
}

type RunRow =
  | { kind: 'ran'; field: string; result: AdoVerbResult | null }
  | { kind: 'not-run'; field: string }

const TONE_CLASS = {
  ok: 'border-status-ok-line bg-status-ok-bg text-status-ok-ink',
  warn: 'border-status-warn-line bg-status-warn-bg text-status-warn-ink',
  error: 'border-today-late-line bg-today-late-bg text-today-late-ink',
} as const

function ResultRow({ row }: { row: RunRow }) {
  if (row.kind === 'not-run') {
    return (
      <section data-testid="reconcile-result" data-field={row.field} data-exit-code="none" className="rounded-[10px] border border-line-1 bg-surface-1 px-3 py-2 text-xs text-ink-3">
        <span className="font-mono text-ink-2">{row.field}</span> — not run: the row before it was not settled.
      </section>
    )
  }
  const { result } = row
  const code = result ? result.exitCode : null
  const tone = code === 0 ? 'ok' : code === 2 ? 'error' : 'warn'
  const json = result?.json ?? null
  const child = json && isObject(json.child) ? json.child : null
  const childWords = child ? [child.stdout, child.stderr].filter((s): s is string => typeof s === 'string' && s.trim() !== '').join('\n').trim() : ''
  const settled = json && typeof json.settled_why === 'string' ? json.settled_why : null
  const notes = json && Array.isArray(json.notes) ? json.notes.filter((n): n is string => typeof n === 'string') : []
  const proposed = code === 0 ? proposedSentence(json) : null
  const said = result && (code !== 0 || !json) ? [result.stdout, result.stderr].filter((s) => s && s.trim()).join('\n').trim() : ''
  return (
    <section data-testid="reconcile-result" data-field={row.field} data-exit-code={code ?? 'none'} aria-live="polite" className={cn('space-y-1 rounded-[10px] border px-3 py-2', TONE_CLASS[tone])}>
      <h4 className="text-sm font-semibold">{exitHeading(code)} <span className="font-mono text-xs font-normal">{row.field}</span></h4>
      {result === null ? <p className="text-xs">{BRIDGE_MISSING}</p> : null}
      {result && result.argv.length > 0 ? <p className="font-mono text-[11px] opacity-80">{previewLine(result.argv)}</p> : null}
      {code === 0 && settled ? <p className="text-xs">settled: {settled}</p> : null}
      {proposed ? <p data-testid="reconcile-proposed" className="text-xs font-medium">{proposed}</p> : null}
      {code === 0 && childWords ? <pre className="whitespace-pre-wrap font-mono text-[11px]">{childWords}</pre> : null}
      {code === 0 ? notes.map((note, i) => <p key={i} className="text-xs">note: {note}</p>) : null}
      {said ? <pre className="whitespace-pre-wrap font-mono text-[11px]">{said}</pre> : null}
    </section>
  )
}

export interface AdoReconcileDialogProps {
  open: boolean
  projectPath: string
  /** One drift item from `readDriftItems`. */
  item: AdoDriftItem
  /** `generate_status.py --json` capabilities; undefined while unknown (the plugin then decides). */
  capabilities?: readonly string[]
  actor: ActorInfo | null | undefined
  /** Steering mode is read-only: nothing is drawn. */
  steering?: boolean
  onClose: () => void
  /** Called once, after a run in which at least one row settled (exit 0): the host re-reads what it holds. */
  onSettled?: () => void
}

export function AdoReconcileDialog({ open, projectPath, item, capabilities, actor, steering = false, onClose, onSettled }: AdoReconcileDialogProps) {
  const [picks, setPicks] = useState<Record<string, Pick>>({})
  const [ran, setRan] = useState<RunRow[]>([])
  const [busy, setBusy] = useState(false)
  const running = useRef(false)
  const confirmRef = useRef<HTMLButtonElement>(null)

  if (steering) return null

  const pickOf = (field: string): Pick => picks[field] ?? BLANK
  const update = (field: string, patch: Partial<Pick>) => setPicks((prev) => ({ ...prev, [field]: { ...(prev[field] ?? BLANK), ...patch } }))

  const chosen = item.fields.filter(settleable).filter((f) => pickOf(f.field).choice !== 'skip').map((f) => {
    const p = pickOf(f.field)
    const take = p.choice as AdoTake
    const owner = take === 'ack' && p.owner.trim() ? { owner: p.owner.trim() } : {}
    const reason = (take === 'ado' || take === 'sdlc' || take === 'not-drift') && p.reason.trim() ? { reason: p.reason.trim() } : {}
    const request: AdoVerbRequest = { verb: 'reconcile', ref: item.ref, field: f.field, take, ...owner, ...reason }
    return { field: f.field, request, problems: validateAdoVerbRequest(request) }
  })
  const firstProblem = chosen.find((c) => c.problems.length > 0)
  const capability = ADO_VERB_CAPABILITY.reconcile
  const lacks = capabilities !== undefined && !capabilities.includes(capability) ? newerPlugin(capability) : null
  const disabledReason = !actor ? NO_ACTOR
    : lacks ?? (chosen.length === 0 ? CHOOSE_A_TAKE : null) ?? (firstProblem ? `${firstProblem.field}: ${firstProblem.problems.join('; ')}` : null)
  const done = ran.length > 0
  // After Confirm the choices are frozen, with their reason: what the preview showed is what was sent.
  const frozen = busy ? 'Sending — wait for the plugin to answer' : done ? 'Sent — close this and pull again to settle more' : undefined

  const confirm = async () => {
    if (disabledReason || running.current || done) return
    running.current = true
    setBusy(true)
    const rows: RunRow[] = []
    let settledAny = false
    try {
      const studio = window.studio as Partial<typeof window.studio> | undefined
      for (let i = 0; i < chosen.length; i += 1) {
        const { field, request } = chosen[i]!
        let result: AdoVerbResult | null
        if (!studio || typeof studio.runAdoVerb !== 'function') {
          result = null
        } else {
          try {
            result = await studio.runAdoVerb(projectPath, request)
          } catch (err) {
            result = { ok: false, exitCode: null, refused: false, stdout: '', stderr: err instanceof Error ? err.message : 'The request did not reach the plugin.', argv: [], verb: 'reconcile', json: null }
          }
        }
        rows.push({ kind: 'ran', field, result })
        if (result && result.exitCode === 0) {
          settledAny = true
        } else {
          for (const rest of chosen.slice(i + 1)) rows.push({ kind: 'not-run', field: rest.field })
          break
        }
      }
      setRan(rows)
    } finally {
      running.current = false
      setBusy(false)
    }
    if (settledAny) onSettled?.()
  }

  const previews = chosen.map((c) => {
    const built = buildAdoVerbArgv(c.request, actor?.name ?? '(no actor)')
    return { field: c.field, line: built.ok ? previewLine(built.argv) : `${c.field}: ${built.errors.join('; ')}`, complete: built.ok }
  })

  return (
    <Dialog open={open} onClose={onClose} title={`Settle drift on ${item.ref}`} size="lg" initialFocus={confirmRef} data-testid="ado-reconcile-dialog" scrollBody
      description="Choose what to do about each field. Shepherd sends one reconcile per field you choose, as you; fields left open are not sent. The plugin refuses a take the row has no word for."
      footer={(
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>{done ? 'Close' : 'Cancel'}</Button>
          {!done && (
            <Button ref={confirmRef} variant="primary" data-write="" loading={busy} loadingLabel="Settling…" disabled={Boolean(disabledReason)} disabledReason={disabledReason ?? undefined} onClick={confirm}>
              {RECONCILE_CONFIRM}
            </Button>
          )}
        </div>
      )}
    >
      <div className="space-y-3 text-sm">
        <p className="text-xs text-ink-3" data-testid="reconcile-actor">
          Recorded against {actor ? <><span className="font-medium text-ink-1">{actor.name}</span> ({actor.source})</> : <span className="text-status-error-ink">{NO_ACTOR}</span>}.
        </p>
        <p className="text-xs text-ink-3">Yours is the board&apos;s value when this item was last sent; Theirs is what it holds now.</p>
        <ul className="space-y-3" aria-label="Drifted fields" data-testid="reconcile-fields">
          {item.fields.map((f, i) => {
            const pick = f.field !== null ? pickOf(f.field) : BLANK
            return (
              <li key={f.field ?? `item-${i}`} data-field={f.field ?? '(the item itself)'} className="rounded-[10px] border border-line-1 bg-surface-1">
                <div className="flex flex-wrap items-center gap-2 px-3 pt-2">
                  <span className="font-mono text-xs font-medium text-ink-1">{f.field ?? '(the item itself)'}</span>
                  <Chip tone="warn" casing="state" dot>{f.class}</Chip>
                </div>
                {f.proposal ? <p className="px-3 pt-1 text-xs text-ink-2 [overflow-wrap:anywhere]">{f.proposal.text}</p> : null}
                {f.field !== null && f.hasValues ? (
                  <div className="mt-2 border-t border-line-1"><ClashDiff mine={f.old} theirs={f.new} /></div>
                ) : null}
                {f.field !== null && !f.hasValues ? <p data-testid="reconcile-no-values" className="px-3 pt-1 text-xs text-ink-3">{NO_VALUES}</p> : null}
                {settleable(f) ? (
                  <div className="space-y-2 px-3 py-2">
                    <Segmented label={`Take for ${f.field}`} options={OPTIONS} value={pick.choice} onChange={(choice) => update(f.field, { choice })} size="sm" tone="accent" disabled={Boolean(frozen)} disabledReason={frozen} />
                    {pick.choice === 'ack' ? (
                      <Field label={`Owner for ${f.field}`} hint="A named person — an acknowledged row with no owner still counts as open.">
                        <Input value={pick.owner} onChange={(e) => update(f.field, { owner: e.target.value })} placeholder="@handle" disabled={Boolean(frozen)} disabledReason={frozen} />
                      </Field>
                    ) : null}
                    {pick.choice === 'not-drift' || pick.choice === 'ado' || pick.choice === 'sdlc' ? (
                      <Field label={pick.choice === 'not-drift' ? `Reason for ${f.field}` : `Reason for ${f.field} (optional)`}
                        hint={pick.choice === 'not-drift' ? 'Why this is not drift — a row with no reason still counts as open.' : 'Recorded with the choice; a decision’s resolution is typed here, never filled in.'}>
                        <Input value={pick.reason} onChange={(e) => update(f.field, { reason: e.target.value })} disabled={Boolean(frozen)} disabledReason={frozen} />
                      </Field>
                    ) : null}
                  </div>
                ) : <p className="px-3 py-2 text-xs text-ink-3">{SETTLE_ELSEWHERE}</p>}
              </li>
            )
          })}
        </ul>
        <div>
          <p className="text-xs font-medium text-ink-2">What will run</p>
          <ul data-testid="reconcile-preview" className="mt-1 space-y-1">
            {previews.map((p) => (
              <li key={p.field} data-preview-field={p.field} data-complete={p.complete ? '' : undefined} className="break-all font-mono text-[11px] text-ink-2">{p.line}</li>
            ))}
          </ul>
          {previews.length === 0 ? <p className="mt-1 text-xs text-ink-3">Nothing yet — every field is left open.</p> : null}
        </div>
        {ran.length > 0 ? (
          <div className="space-y-2" data-testid="reconcile-results">
            {ran.map((row, i) => <ResultRow key={i} row={row} />)}
          </div>
        ) : null}
      </div>
    </Dialog>
  )
}
