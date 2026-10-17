// The Azure Boards comment composer (build kit §5 B4-P4). A comment is speech, so it goes in two steps with a
// person's click between them: `comment` drafts a plan and prints its 12-hex hash and the exact row, the person
// reads that preview, and only Confirm sends `apply --confirm <hash>` — as whoever az is signed in as, which must
// be the person Shepherd records the write against. Nothing runs before Preview; nothing is sent before Confirm;
// this file never chains the two spawns itself (`adoWrites.ts` runs one verb per call).
//
// Every request is one of the closed `AdoVerbRequest`s: the renderer sends no argv, no flag and no name — main
// resolves the actor and appends `--by`. The message is sent byte for byte (the plugin shows what it will post).
// The plan's own text is shown escaped (a React text node — never markup), and every write control carries
// `data-write`. In steering mode the composer renders nothing at all: steering is read-only.
//
// Disabled means a reason, always: no signed-in person (`NO_ACTOR`), a plugin without the comment or apply
// capability (`newerPlugin`), a clone whose posture does not offer apply, and an az identity that is not the
// person ("Signed in to az as @x; Shepherd knows you as @y"). `executedAs` is the roster handle az resolved to
// (the plugin's `plan --json` prints it as `executed_as`; the closed table has no verb that prints it here, so a
// host that has it passes it in): `null`/absent is "not read yet", and the plugin's own whole-plan check at
// `apply` stays the truth — this gap only says it early.
import { useState } from 'react'
import type { AdoVerbResult } from '../../../shared/types'
import { ADO_VERB_CAPABILITY, HASH, validateAdoVerbRequest, type AdoVerbRequest } from '../../../shared/adoVerbArgv'
import { identityLabel, samePerson } from '../../../shared/identity'
import { exitHeading, NO_ACTOR, newerPlugin } from '../../../shared/reasons'
import { Button, Field, Notice, Textarea, cn } from '../../ui'
import { useConnection } from '../../stores/connectionStore'

export const WRITE_THE_COMMENT_FIRST = 'Write the comment first.'
export const BRIDGE_MISSING = 'This build of the desktop app has no runAdoVerb bridge.'

/** One closed request through the bridge, or null when this build has no `runAdoVerb` (an older app: said as a
 * sentence by the caller, never a crash). The request is validated by main against the same table. */
export async function runAdo(projectPath: string, request: AdoVerbRequest): Promise<AdoVerbResult | null> {
  const studio = window.studio as Partial<typeof window.studio> | undefined
  if (!studio || typeof studio.runAdoVerb !== 'function') return null
  return studio.runAdoVerb(projectPath, request)
}

/** Why Confirm is withheld when az and Shepherd disagree about who is writing, or null when they agree or when
 * either side is not known (the plugin decides at `apply`). `unknown` is the plugin's word for an identity it
 * could not match to the roster (a service principal, an account that is not on it). */
export function identityGap(executedAs: string | null | undefined, you: string | null | undefined): string | null {
  const az = executedAs?.trim()
  const known = you?.trim()
  if (!az || !known) return null
  if (az.toLowerCase() === 'unknown') return `Signed in to az as an identity that is not on the roster; Shepherd knows you as ${known}`
  return samePerson(az, known) ? null : `Signed in to az as ${az}; Shepherd knows you as ${known}`
}

interface Draft {
  plan: string
  text: string
  posture: string | null
  offered: boolean
  notes: string[]
}

interface Outcome {
  heading: string
  tone: 'ok' | 'error'
  stdout: string
  stderr: string
}

const TONE_CLASS: Record<Outcome['tone'], string> = {
  ok: 'border-status-ok-line bg-status-ok-bg text-status-ok-ink',
  error: 'border-today-late-line bg-today-late-bg text-today-late-ink',
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

/** The plan `comment --json` printed, as far as the composer needs it: a 12-hex hash, the row's own text, the
 * posture and whether apply is offered. Null when there is no hash — nothing is sent that the plugin did not name. */
function readDraft(json: Record<string, unknown> | null, typed: string): Draft | null {
  if (!json || typeof json.plan !== 'string' || !HASH.test(json.plan)) return null
  const row = isObject(json.row) ? json.row : null
  return {
    plan: json.plan,
    text: row && typeof row.text === 'string' ? row.text : typed,
    posture: typeof json.posture === 'string' ? json.posture : null,
    offered: json.apply_offered !== false,
    notes: Array.isArray(json.notes) ? json.notes.filter((n): n is string => typeof n === 'string') : [],
  }
}

function outcomeOf(result: AdoVerbResult | null): Outcome {
  if (!result) return { heading: exitHeading(null), tone: 'error', stdout: '', stderr: BRIDGE_MISSING }
  return { heading: exitHeading(result.exitCode), tone: result.exitCode === 0 ? 'ok' : 'error', stdout: result.stdout, stderr: result.stderr }
}

export interface CommentComposerProps {
  projectPath: string
  /** `sdlc:<kind>:<id>` or `#<work item>` — the item the comment is for. */
  itemRef: string
  /** `generate_status.py --json` capabilities; null while unknown (main still refuses a verb the plugin lacks). */
  capabilities: readonly string[] | null
  /** The roster handle az is signed in as, `"unknown"` for an identity off the roster, null/absent when not read. */
  executedAs?: string | null
  /** Steering mode is read-only: nothing is drawn. */
  steering?: boolean
  /** Called after the comment was sent (apply exited 0): the host re-reads. */
  onPosted?: () => void
}

export function CommentComposer({ projectPath, itemRef, capabilities, executedAs, steering = false, onPosted }: CommentComposerProps) {
  const connection = useConnection()
  const actor = identityLabel(connection?.account, connection?.rosterHandle)
  const you = connection?.rosterHandle?.trim() || actor
  const [message, setMessage] = useState('')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [busy, setBusy] = useState(false)

  if (steering) return null

  const lacks = (cap: string) => (capabilities !== null && !capabilities.includes(cap) ? newerPlugin(cap) : null)
  const gap = identityGap(executedAs, you)
  const previewReason = !actor ? NO_ACTOR
    : lacks(ADO_VERB_CAPABILITY.comment) ?? lacks(ADO_VERB_CAPABILITY.apply) ?? (message.trim() === '' ? WRITE_THE_COMMENT_FIRST : null)
  const notOffered = draft && !draft.offered ? `apply not offered in this clone: posture is ${draft.posture ?? 'not assisted'}` : null
  const confirmReason = !actor ? NO_ACTOR : lacks(ADO_VERB_CAPABILITY.apply) ?? gap ?? notOffered

  const doPreview = async () => {
    if (busy || previewReason) return
    const request: AdoVerbRequest = { verb: 'comment', ref: itemRef, message }
    const problems = validateAdoVerbRequest(request)
    if (problems.length > 0) { setOutcome({ heading: exitHeading(null), tone: 'error', stdout: '', stderr: problems.join('\n') }); return }
    setBusy(true)
    setOutcome(null)
    setDraft(null)
    try {
      const result = await runAdo(projectPath, request)
      const plan = result && result.exitCode === 0 ? readDraft(result.json, message) : null
      if (plan) setDraft(plan)
      else setOutcome(outcomeOf(result))
    } finally {
      setBusy(false)
    }
  }

  const doConfirm = async () => {
    if (busy || confirmReason || !draft) return
    setBusy(true)
    try {
      const result = await runAdo(projectPath, { verb: 'apply', confirm: draft.plan })
      setOutcome(outcomeOf(result))
      if (result && result.exitCode === 0) {
        setDraft(null)
        setMessage('')
        onPosted?.()
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-label="Comment on the board" data-testid="comment-composer" className="space-y-2">
      {draft ? (
        <div className="space-y-2">
          <pre data-testid="comment-preview" className="max-h-48 overflow-auto whitespace-pre-wrap rounded-[10px] border border-line-1 bg-surface-2 px-3 py-2 font-mono text-xs text-ink-1 [overflow-wrap:anywhere]">{draft.text}</pre>
          <p className="text-xs text-ink-2" data-testid="comment-actor">
            {actor ? <>Recorded against <span className="font-medium text-ink-1">{actor}</span></> : <span className="text-ink-3">{NO_ACTOR}</span>}
            {executedAs ? <span className="text-ink-3"> · sent as {executedAs}</span> : null}
          </p>
          <p className="font-mono text-ident text-ink-3" data-testid="comment-plan">plan {draft.plan}</p>
          {draft.notes.length > 0 ? <ul className="list-disc pl-5 text-xs text-ink-3">{draft.notes.map((note) => <li key={note}>{note}</li>)}</ul> : null}
          {gap ? <Notice tone="warn"><span data-testid="comment-identity-gap">{gap}</span></Notice> : null}
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" onClick={() => { setDraft(null); setOutcome(null) }}>Edit</Button>
            <Button size="sm" variant="primary" data-write="" loading={busy} loadingLabel="Sending…" disabled={Boolean(confirmReason)} disabledReason={confirmReason ?? undefined} onClick={doConfirm}>Confirm</Button>
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <Field label="Comment">
            <Textarea value={message} onChange={(e) => setMessage(e.target.value)} placeholder="what the board should read, as you" />
          </Field>
          <Button size="sm" variant="secondary" data-write="" loading={busy} loadingLabel="Drafting…" disabled={Boolean(previewReason)} disabledReason={previewReason ?? undefined} onClick={doPreview}>Preview comment</Button>
        </div>
      )}
      {outcome ? (
        <section data-testid="comment-result" data-tone={outcome.tone} aria-live="polite" className={cn('rounded-[10px] border px-3 py-2', TONE_CLASS[outcome.tone])}>
          <h3 className="text-sm font-semibold">{outcome.heading}</h3>
          {outcome.stdout ? <pre className="mt-1 whitespace-pre-wrap font-mono text-xs">{outcome.stdout}</pre> : null}
          {outcome.stderr ? <pre className="mt-1 whitespace-pre-wrap font-mono text-xs">{outcome.stderr}</pre> : null}
        </section>
      ) : null}
    </section>
  )
}
