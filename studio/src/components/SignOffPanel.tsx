import { useEffect, useRef, useState } from 'react'
import { Flip } from 'gsap/Flip'
import type { DisciplineSignoff, StageReadiness } from '../../shared/types'
import { Button, Card, Input, Notice, toast } from '../ui'
import { announce } from '../a11y/LiveAnnouncer'
import { MOTION_DURATIONS, MOTION_EASES } from '../motion/contract'
import { enabled as motionEnabled, reduced as motionReduced } from '../motion/motion'
import { ceremonyRegistry } from '../motion/ceremonyRegistry'
import { contextFrom, signOffCeremony } from '../motion/choreo'
import { playSpineCeremony } from '../scenes/spine/spineCeremony'
import { useClaudeIssue } from './ClaudeIssueContext'

interface Opening {
  projectName: string
  startedAt: number
  title?: string
  subtitle?: string
}

const ROW_INPUT = 'rounded-lg px-2 py-1 text-xs'

/** One optional Discipline / Section / Name row — the same triple `/sprd-next` offers to
 * capture. All-empty rows are dropped before the call, so leaving this untouched is exactly
 * "no sign-offs", byte-identical to not offering the feature at all. */
function DisciplineRow({
  value, onChange, onRemove,
}: {
  value: DisciplineSignoff
  onChange: (v: DisciplineSignoff) => void
  onRemove: () => void
}) {
  return (
    <div className="flex items-center gap-2">
      <Input
        size="sm"
        aria-label="Discipline"
        value={value.discipline}
        onChange={(e) => onChange({ ...value, discipline: e.target.value })}
        placeholder="Discipline (e.g. Design)"
        className={`w-32 ${ROW_INPUT}`}
      />
      <Input
        size="sm"
        aria-label="Section"
        value={value.section}
        onChange={(e) => onChange({ ...value, section: e.target.value })}
        placeholder="Section (e.g. interaction-specs)"
        className={`w-40 ${ROW_INPUT}`}
      />
      <Input
        size="sm"
        aria-label="Signed by"
        value={value.by}
        onChange={(e) => onChange({ ...value, by: e.target.value })}
        placeholder="Signed by"
        className={`w-32 ${ROW_INPUT}`}
      />
      <Button variant="ghost" size="sm" onClick={onRemove}>Remove</Button>
    </div>
  )
}

interface Success {
  fromPhase?: string
  toPhase?: string
  note?: string
  /** Who the sign-off was recorded under — the name the toast reads out. */
  signedBy: string
}

/** The card that replaces the form once the plugin advanced. The inline tick is the path the
 * ceremony (§4.2 #10 b) draws; it has no icon of its own to morph, so a plain stroke it is.
 *
 * Round 2 (M1): the SEAM — a 2 px accent line along the card's top edge that the ceremony draws
 * from the centre outward (the Macron's gesture, not its shape) — and the signer line, set in
 * the detail voice (`text-lg`, 650, −0.02 em) because the name is the record. A sign-off the
 * plugin recorded with NO name shows the hollow ring and says "no name recorded": an empty
 * signature line reads as signed, and this card exists to say who did. */
function SuccessCard({ success, cardRef, tickRef, seamRef }: {
  success: Success
  cardRef: (el: HTMLDivElement | null) => void
  tickRef: (el: SVGPathElement | null) => void
  seamRef: (el: HTMLSpanElement | null) => void
}) {
  const signer = success.signedBy.trim()
  return (
    <Card ref={cardRef} tone="ok" data-testid="sign-off-success" className="relative overflow-hidden">
      <span ref={seamRef} aria-hidden="true" data-seam="" className="pointer-events-none absolute inset-x-0 top-0 h-0.5 bg-accent-500" />
      <h3 className="flex items-center gap-2 text-sm font-medium text-ink-1">
        <svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" className="shrink-0 text-status-ok-fill">
          <path ref={tickRef} d="M3 8.5 6.5 12 13 4.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Signed off — moved from Phase {success.fromPhase} to Phase {success.toPhase}
      </h3>
      <p className="mt-2 flex items-center gap-2 text-lg font-[650] tracking-[-0.02em] text-ink-1" data-testid="sign-off-signer">
        {signer ? (
          <>Signed off by {signer}</>
        ) : (
          <>
            <span aria-hidden="true" className="inline-block h-[14px] w-[14px] shrink-0 rounded-full border-[1.5px] border-stage-signed-fill" />
            Completed · no name recorded
          </>
        )}
      </p>
      {success.note && <p className="mt-1 text-sm text-ink-2">{success.note}</p>}
    </Card>
  )
}

/** Signs off the current stage and advances the phase — the window's own version of
 * `/sprd-next`. Shown only when there is something to offer: the stage is the project's
 * current one, every required document is complete, and every judgement question is already
 * confirmed (`SignOffQuestions`' own job, above this). Everything this does — checking the
 * gates, drafting and validating the frozen-layer summary, snapshotting the artifact record,
 * advancing — is the plugin's; a refusal is shown in the plugin's own words, naming which step
 * it stopped at, never a guess dressed up as an explanation.
 *
 * The ceremony (§4.2 #10) is gated on BOTH facts being real: `signOffStage` said ok AND the
 * caller's `onSignedOff` refresh (App's `refreshStatus`) has resolved, so the sidebar it will
 * animate already shows the new state. The toast and the live announcement are made whether or
 * not motion is on — they are the record, the timeline is the flourish. */
export function SignOffPanel({
  projectPath,
  readiness,
  actor,
  setOpening,
  onSignedOff,
}: {
  projectPath: string
  readiness: StageReadiness
  actor: string
  setOpening: (opening: Opening | null) => void
  /** App's `refreshStatus`; awaited so the ceremony only starts once the new status is on screen. */
  onSignedOff: () => void | Promise<void>
}) {
  const [signedBy, setSignedBy] = useState(actor)
  const [rows, setRows] = useState<DisciplineSignoff[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<Success | null>(null)
  const [ceremonyDue, setCeremonyDue] = useState(false)
  const root = useRef<HTMLDivElement | null>(null)
  const successCard = useRef<HTMLDivElement | null>(null)
  const tickPath = useRef<SVGPathElement | null>(null)
  const seam = useRef<HTMLSpanElement | null>(null)
  // What the Sidebar showed BEFORE the refresh: the Now badge's position (for the Flip) and the
  // bar's fraction. Captured in the handler, between the plugin's `ok` and `onSignedOff`, because
  // after the refresh the Sidebar has already drawn the new state.
  const before = useRef<{ nowState: Flip.FlipState | null; fraction: number | null }>({ nowState: null, fraction: null })
  // The registry hold taken for the ceremony: released when the timeline ends (or is killed) —
  // and on unmount, because the hold is taken BEFORE `await onSignedOff()`: a person who leaves
  // this screen while the refresh is still pending would otherwise leave the Sidebar's progress
  // row applying end states (never tweening) for the rest of the session.
  const release = useRef<(() => void) | null>(null)
  useEffect(() => () => { release.current?.(); release.current = null }, [])
  // Drafting the phase summary is a model call; an installed Claude Code that lacks a flag Studio
  // emits would fail it after the gates passed. Disabled with the reason instead (F1).
  const claudeIssue = useClaudeIssue()

  // Plays once the success card is in the DOM and the refresh has landed — one timeline (M1):
  // this card's tick, rise and seam, then the Sidebar's nodes resolved through `ceremonyRegistry`
  // at this moment (so they are the elements the refreshed render drew), then the Spine at the
  // "spine" label. The Sidebar's own progress row saw the registry held and applied its end
  // state, so the bar is this timeline's to tween from the fraction captured before the refresh.
  useEffect(() => {
    if (!ceremonyDue || !success || !root.current) return
    setCeremonyDue(false)
    const ctx = contextFrom(root.current, { enabled: motionEnabled(), reduced: motionReduced() }, { durations: MOTION_DURATIONS, eases: MOTION_EASES })
    // `onSpine` fires at the timeline's "spine" label: the mounted Spine scene (if any — table
    // surface or no WebGL means none) advances its lit rail to the stage just signed. A no-op when
    // nothing is listening; the refreshed status moves the rail on the next render regardless.
    const signedStageId = readiness.stageId
    const nodes = ceremonyRegistry.resolve()
    const bar = nodes.bar
    const toFraction = bar instanceof HTMLElement && bar.parentElement
      ? Number(bar.parentElement.getAttribute('aria-valuenow')) / Math.max(1, Number(bar.parentElement.getAttribute('aria-valuemax')))
      : undefined
    const tl = signOffCeremony.play(ctx, {
      successCard: successCard.current,
      tickPath: tickPath.current,
      seam: seam.current,
      signedNode: nodes.signedNode,
      connector: nodes.connector,
      nextRing: nodes.nextRing,
      nowBadge: nodes.nowBadge,
      nowState: before.current.nowState,
      bar,
      fromFraction: before.current.fraction,
      toFraction: Number.isFinite(toFraction) ? toFraction : undefined,
      onSpine: () => { playSpineCeremony(signedStageId) },
    })
    const done = () => { release.current?.(); release.current = null }
    void tl.then(done)
    return () => { tl.kill(); done() }
  }, [ceremonyDue, success, readiness.stageId])

  if (success) {
    return (
      <div ref={root}>
        <SuccessCard
          success={success}
          cardRef={(el) => { successCard.current = el }}
          tickRef={(el) => { tickPath.current = el }}
          seamRef={(el) => { seam.current = el }}
        />
      </div>
    )
  }

  const signOff = async () => {
    setBusy(true)
    setError(null)
    // Whether the ceremony effect was scheduled: if not (a refusal, or a throw after the hold
    // was taken), the hold is released here so the Sidebar is never left frozen.
    let scheduled = false
    setOpening({
      projectName: readiness.display,
      startedAt: Date.now(),
      title: `Signing off ${readiness.display}…`,
      subtitle: 'Checking gates, drafting the phase summary, and advancing.',
    })
    try {
      const result = await window.studio.signOffStage(projectPath, readiness.stageId, signedBy, rows)
      if (!result.ok) {
        setError(result.error)
        return
      }
      setSuccess({ fromPhase: result.fromPhase, toPhase: result.toPhase, note: result.note, signedBy })
      // The ceremony owns the Sidebar's bar, node and Now badge from here until it ends: the hold
      // makes the Sidebar's own progress row apply its end state on the refresh instead of
      // tweening, and the Sidebar's BEFORE picture is captured now, while it is still drawn.
      release.current?.()
      release.current = ceremonyRegistry.hold()
      const nodes = ceremonyRegistry.resolve()
      before.current = {
        nowState: nodes.nowBadge && motionEnabled() && !motionReduced() ? Flip.getState(nodes.nowBadge) : null,
        fraction: nodes.bar instanceof HTMLElement && nodes.bar.parentElement
          ? Number(nodes.bar.parentElement.getAttribute('aria-valuenow')) / Math.max(1, Number(nodes.bar.parentElement.getAttribute('aria-valuemax')))
          : null,
      }
      // Both facts, in order: the plugin advanced, then the refreshed status is on screen.
      await onSignedOff()
      const line = `Phase ${result.fromPhase ?? readiness.stageId} signed off · by ${signedBy.trim()}`
      toast({ tone: 'ok', title: line })
      announce(line)
      setCeremonyDue(true)
      scheduled = true
    } finally {
      if (!scheduled) { release.current?.(); release.current = null }
      setOpening(null)
      setBusy(false)
    }
  }

  return (
    <Card ref={root}>
      <h3 className="text-sm font-medium text-ink-1">Sign off {readiness.display}</h3>
      <p className="mt-1 text-sm text-ink-2">
        Checks the gates, drafts and validates a summary of this phase, and advances — the same
        thing <code className="rounded bg-surface-2 px-1 text-xs">/sprd-next</code> does.
      </p>

      <label className="mt-3 block text-xs font-medium text-ink-2">
        Signed by
        <Input
          value={signedBy}
          onChange={(e) => setSignedBy(e.target.value)}
          className="mt-1 block w-56"
        />
      </label>

      <div className="mt-3">
        <p className="text-xs font-medium text-ink-2">Discipline sign-offs (optional)</p>
        <div className="mt-1 space-y-1">
          {rows.map((row, i) => (
            <DisciplineRow
              key={i}
              value={row}
              onChange={(v) => setRows(rows.map((r, j) => (j === i ? v : r)))}
              onRemove={() => setRows(rows.filter((_, j) => j !== i))}
            />
          ))}
        </div>
        <Button
          variant="link"
          size="sm"
          className="mt-1 text-xs font-medium text-ink-3"
          onClick={() => setRows([...rows, { discipline: '', section: '', by: '' }])}
        >
          + Add a discipline sign-off
        </Button>
      </div>

      {error && (
        <Notice tone="warn" className="mt-3">
          {/* The plugin's own wording, whole — a person fixing a gate needs to know which one. */}
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs text-amber-900">{error}</pre>
        </Notice>
      )}

      {claudeIssue && <p className="mt-3 text-xs text-amber-800">{claudeIssue}</p>}

      {/* No `disabledReason` on this button: the empty-name reason is the field right above it,
          and hidden text inside the button would change the pinned `>Sign off…</button>` shape. */}
      <Button
        variant="primary"
        className="mt-3"
        onClick={signOff}
        disabled={busy || !signedBy.trim() || claudeIssue !== null}
      >
        {busy ? 'Signing off…' : error ? 'Try again' : `Sign off and advance`}
      </Button>
    </Card>
  )
}
