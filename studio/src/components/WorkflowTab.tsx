import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { DocumentFocus, SignOffQuestion, StageActivity, StageDocument, StageReadiness } from '../../shared/types'
import {
  computeActivityRows, computeWorkflowSteps, slashCommand,
  type ActivityRow, type DocumentWorkflowStep, type WorkflowStep, type WorkflowStepStatus,
} from '../workflowSteps'
import { startDocumentPolling } from '../documentPoller'
import type { DocumentSnapshot } from '../documentSnapshot'
import { stageHomeKey } from '../stageHomeKey'
import { BackLink, Badge, Button, Card, EmptyState, Eyebrow, Notice } from '../ui'
import { ActivitiesPanel, ensureDocumentFromTemplate } from './ActivitiesPanel'
import { SectionCard } from './DocumentSections'
import { FocusedActivityContext, FocusedActivityHost, type FocusedActivity, type FocusedActivityBridge } from './FocusedActivityHost'
import { SignOffQuestions } from './SignOffQuestions'

/** How often the live panel re-reads the current step's document. Each poll is a real
 * subprocess round trip through `openDocument()`'s shape-library CLI, not a cheap read — spec
 * 0017's own Decision List calls this a deliberate cost/freshness tradeoff, not a default to
 * shrink later without noticing the cost. Paused while the window/tab is not visible — see
 * `documentPoller.ts`. */
const POLL_MS = 2000

/** A stage's home page, redrawn as a guided sequence (spec 0017): one step per required
 * document in the stage's own declared order, plus a trailing Sign-off step, with the current
 * step's real content shown live beside the list — steps above the file at phone width.
 *
 * Step status comes from `computeWorkflowSteps`, the same function the shared-source
 * acceptance check depends on, so this component makes no decision of its own about what is
 * done, current or locked — it only draws what that function already decided. Read-only by
 * construction: nothing here edits a document, that stays the structured editor and chat. */
export function WorkflowTab({
  projectPath,
  readiness,
  actor,
  busyId,
  confirmError,
  onToggleSignOff,
  onOpenDocument,
  onRefresh,
}: {
  projectPath: string
  readiness: StageReadiness
  /** Who a sign-off confirmation is recorded under; empty when nobody is signed in. */
  actor: string
  busyId: string | null
  confirmError: string | null
  onToggleSignOff: (question: SignOffQuestion, confirmed: boolean) => void
  /** Opens the same structured editor the Documents tab's rows open — the document panel's own
   * Edit control (spec 0018) reuses this exact callback, never a second write path. */
  onOpenDocument: (relPath: string, focus?: DocumentFocus) => void
  /** Re-reads the stage after an activity changed the project (starting documents). */
  onRefresh?: () => Promise<void>
}) {
  const steps = computeWorkflowSteps(readiness)
  const current = steps.find((s) => s.status === 'current') ?? null
  const stageKey = stageHomeKey(projectPath, readiness.stageId)

  // F11: the activity a person opened from "Also in this stage", shown in the main slot. Reset
  // when the stage or project changes — the same reset-on-switch rule the document panel and
  // StageHome's tab follow — because a Sprint board opened on Build is not an answer on Design.
  const [focused, setFocused] = useState<FocusedActivity | null>(null)
  useEffect(() => { setFocused(null) }, [stageKey])
  const bridge = useMemo<FocusedActivityBridge>(() => ({
    focusedId: focused?.activity.id ?? null,
    focus: (activity: StageActivity, panel: ReactNode) => setFocused({ activity, panel }),
    close: () => setFocused(null),
  }), [focused?.activity.id])

  return (
    <div className="flex flex-col gap-6 sm:flex-row">
      <div className="sm:w-72 sm:shrink-0">
        <ol className="space-y-2">
          {steps.map((step) => <StepRow key={step.key} step={step} />)}
        </ol>
        {/* Keyed on stage + project so one stage's result line never shows under another. The
            provider is how a panel row hands its panel to the main slot (see FocusedActivityHost);
            a row that ignores it renders inline exactly as it does today. */}
        <FocusedActivityContext.Provider value={bridge}>
          <ActivitiesPanel
            key={stageKey}
            projectPath={projectPath}
            readiness={readiness}
            actor={actor}
            onOpenDocument={onOpenDocument}
            onRefresh={onRefresh}
          />
        </FocusedActivityContext.Provider>
      </div>

      {/* The ONLY place any step's real content appears — never inside a step's own row. That is
          what makes a locked row's absence and a done row's absence both true by construction
          rather than by care: neither status ever reaches this branch. */}
      <div className="min-w-0 flex-1">
        {focused ? (
          <FocusedActivityHost activity={focused.activity} onClose={bridge.close}>
            {focused.panel}
          </FocusedActivityHost>
        ) : (
        <CurrentStepPanel
          projectPath={projectPath}
          current={current}
          steps={steps}
          readiness={readiness}
          actor={actor}
          busyId={busyId}
          confirmError={confirmError}
          onToggleSignOff={onToggleSignOff}
          onOpenDocument={onOpenDocument}
          onRefresh={onRefresh}
        />
        )}
      </div>
    </div>
  )
}

/** What shows beside the step list: the current document step's live content, the sign-off
 * questions, a folder notice, or nothing. Pulled out of `WorkflowTab` itself so that function
 * stays a plain layout — this repo's "functions under 50 lines" convention (spec 0017's fix
 * pass, bug #10). */
function CurrentStepPanel({
  projectPath, current, steps, readiness, actor, busyId, confirmError, onToggleSignOff, onOpenDocument, onRefresh,
}: {
  projectPath: string
  current: WorkflowStep | null
  steps: WorkflowStep[]
  readiness: StageReadiness
  actor: string
  busyId: string | null
  confirmError: string | null
  onToggleSignOff: (question: SignOffQuestion, confirmed: boolean) => void
  onOpenDocument: (relPath: string, focus?: DocumentFocus) => void
  onRefresh?: () => Promise<void>
}) {
  if (current?.kind === 'document') {
    return (
      <DocumentStepPanel
        projectPath={projectPath}
        current={current}
        steps={steps}
        readiness={readiness}
        stageKey={stageHomeKey(projectPath, readiness.stageId)}
        onOpenDocument={onOpenDocument}
        onRefresh={onRefresh}
      />
    )
  }

  if (current?.kind === 'sign-off') {
    if (readiness.judgement.length === 0) {
      return <p className="text-sm text-ink-3">Nothing further needs confirming before this stage can be signed off.</p>
    }
    return (
      <SignOffQuestions
        questions={readiness.judgement}
        actor={actor}
        busyId={busyId}
        error={confirmError}
        onToggle={onToggleSignOff}
      />
    )
  }

  // The kit's one "nothing here" frame (G4-9); the sentence is the one tests find.
  return <EmptyState figure="page" title="Nothing is currently in progress on this stage." />
}

/** The current step, once it IS a document (spec 0018): a header (Back to Workflow / Previous /
 * Next / Edit) above the live content.
 *
 * `viewedKey` is deliberately separate from `current` — Previous/Next lets a person browse an
 * ADJACENT document in the stage's own declared order without that changing what the workflow
 * itself considers current (`computeWorkflowSteps`'s done/current/locked stays exactly as it
 * was). "Back to Workflow" snaps the view back to the real current step; so does the current
 * step itself moving on, or the stage changing underneath — the same reset-on-switch pattern
 * StageHome already uses for its own tab (`stageHomeKey`). The step LIST stays exactly as spec
 * 0017 left it: its rows are not a second way to navigate here, only Previous/Next in this
 * header is.
 *
 * The reset effect keys on `stageKey` (`stageHomeKey(projectPath, readiness.stageId)`) ALONGSIDE
 * `current.key`, not `current.key` alone (PR #76 review finding #6): `current.key` is just the
 * current document's own PATH, and two different stages' (or two different projects', browsing
 * the same profile's templates) current documents can share that exact string — when they do,
 * switching between them leaves `current.key` unchanged, so an effect keyed on it alone never
 * re-fires, and a document the person had browsed to in the OLD stage keeps showing even though
 * the workflow itself has moved on underneath. */
function DocumentStepPanel({
  projectPath, current, steps, readiness, stageKey, onOpenDocument, onRefresh,
}: {
  projectPath: string
  current: DocumentWorkflowStep
  steps: WorkflowStep[]
  readiness: StageReadiness
  stageKey: string
  onOpenDocument: (relPath: string, focus?: DocumentFocus) => void
  onRefresh?: () => Promise<void>
}) {
  const documentSteps = steps.filter((s): s is DocumentWorkflowStep => s.kind === 'document')
  const [viewedKey, setViewedKey] = useState(current.key)

  useEffect(() => { setViewedKey(current.key) }, [current.key, stageKey])

  const viewedIndex = documentSteps.findIndex((s) => s.key === viewedKey)
  const viewed = viewedIndex >= 0 ? documentSteps[viewedIndex] : current

  return (
    <div className="space-y-3">
      <DocumentPanelHeader
        title={viewed.title}
        onBack={() => setViewedKey(current.key)}
        onPrevious={() => setViewedKey(documentSteps[viewedIndex - 1].key)}
        onNext={() => setViewedKey(documentSteps[viewedIndex + 1].key)}
        previousDisabled={viewedIndex <= 0}
        nextDisabled={viewedIndex === -1 || viewedIndex >= documentSteps.length - 1}
        onEdit={() => onOpenDocument(viewed.document.path)}
        // Edit on a document that is not there only ever failed ("<path> does not exist"); the panel
        // below says it is not started and offers to start it.
        editDisabled={viewed.document.folder || !viewed.document.exists}
      />
      {viewed.document.folder ? (
        <p className="text-sm text-ink-3">
          {viewed.title} is a folder of documents — open it from the Documents tab.
        </p>
      ) : (
        <LiveDocumentPanel
          key={viewed.document.path}
          projectPath={projectPath}
          relPath={viewed.document.path}
          empty={(
            <EmptyStepPanel
              projectPath={projectPath}
              readiness={readiness}
              viewed={viewed}
              steps={steps}
              onOpenDocument={onOpenDocument}
              onRefresh={onRefresh}
            />
          )}
        />
      )}
    </div>
  )
}

/** Back to Workflow / Previous / Next / Edit — the document panel's own header (spec 0018's
 * acceptance check). `flex-wrap` is the same accommodation spec 0017's own responsive bar held
 * itself to: these controls do not force new horizontal overflow of their own at phone width. */
function DocumentPanelHeader({
  title, onBack, onPrevious, onNext, previousDisabled, nextDisabled, onEdit, editDisabled,
}: {
  title: string
  onBack: () => void
  onPrevious: () => void
  onNext: () => void
  previousDisabled: boolean
  nextDisabled: boolean
  onEdit: () => void
  editDisabled: boolean
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line-1 pb-3">
      <div className="min-w-0">
        <BackLink label="← Back to Workflow" onClick={onBack} className="font-medium" />
        <h3 className="mt-0.5 truncate text-sm font-semibold text-ink-1">{title}</h3>
      </div>
      {/* Kit Buttons: `type="button"` then `disabled=""` is the attribute order the static-markup
          test pins; the kit emits exactly that. No `disabledReason` here — the state is explained
          by position (first / last document), and hidden text inside the button would change the
          pinned `>Previous</button>` shape. */}
      <div className="flex shrink-0 flex-wrap gap-2">
        <Button size="sm" onClick={onPrevious} disabled={previousDisabled}>Previous</Button>
        <Button size="sm" onClick={onNext} disabled={nextDisabled}>Next</Button>
        <Button size="sm" variant="primary" onClick={onEdit} disabled={editDisabled}>Edit</Button>
      </div>
    </div>
  )
}

function StepRow({ step }: { step: WorkflowStep }) {
  return (
    <Card
      as="li"
      interactive
      data-testid="workflow-step"
      data-step-key={step.key}
      data-step-status={step.status}
      data-reveal=""
      // The current step wears the accent lightly (G4-14); the rest is ink.
      className={step.status === 'current' ? 'border-accent-400 bg-accent-50' : undefined}
    >
      <div className="flex items-baseline justify-between gap-3">
        {/* min-w-0 so this can actually shrink below its content's natural width at a narrow
            viewport, instead of forcing the row (and the page) wider — the same pattern
            DocumentsTab already uses for a document's name. Without it, a flex item's default
            min-width is its own content size, and "requirements.md" has nowhere to wrap. */}
        <span className="min-w-0 truncate text-sm font-medium text-ink-1">{step.title}</span>
        <StepBadge status={step.status} />
      </div>
      {step.description && <p className="mt-0.5 text-xs text-ink-3">{step.description}</p>}
    </Card>
  )
}

/** The text is the state; the Badge kind only colours it. A row never carries a control for
 * its state (asserted as absence by workflowTab.test.ts), so this stays a `<span>`. */
function StepBadge({ status }: { status: WorkflowStepStatus }) {
  if (status === 'done') return <Badge kind="complete" className="shrink-0">Complete</Badge>
  if (status === 'current') return <Badge kind="current" className="shrink-0">Current</Badge>
  return <Badge kind="locked" className="shrink-0">Locked</Badge>
}

/** The current step's real file, read through the exact same `openDocument()` the structured
 * editor uses, polled while this panel is mounted, the tab is visible, and this is the current
 * step. Leaving the tab (or the current step moving on) unmounts this panel and stops the
 * polling with it — see `documentPoller.ts` for the pause-while-hidden and
 * discard-stale-response guarantees. Read-only: nothing here writes, edits, or offers to. */
function LiveDocumentPanel({ projectPath, relPath, empty }: { projectPath: string; relPath: string; empty: ReactNode }) {
  const [snapshot, setSnapshot] = useState<DocumentSnapshot | null>(null)
  const lastJson = useRef<string>('')

  useEffect(() => {
    lastJson.current = ''
    setSnapshot(null)

    return startDocumentPolling({
      openDocument: window.studio.openDocument,
      projectPath,
      relPath,
      intervalMs: POLL_MS,
      setInterval: (cb, ms) => window.setInterval(cb, ms),
      clearInterval: (id) => window.clearInterval(id as number),
      isHidden: () => document.hidden,
      onVisibilityChange: (cb) => {
        document.addEventListener('visibilitychange', cb)
        return () => document.removeEventListener('visibilitychange', cb)
      },
      onSnapshot: (next) => {
        // Only replace what is on screen when the content actually changed. Every poll is
        // still a real call through the shape library — this only stops an unchanged answer
        // from flickering the panel or resetting a reader's scroll position.
        const json = JSON.stringify(next)
        if (json !== lastJson.current) {
          lastJson.current = json
          setSnapshot(next)
        }
      },
    })
  }, [projectPath, relPath])

  return <LiveDocumentPanelContent snapshot={snapshot} empty={empty} />
}

/** Renders one `DocumentSnapshot` — split out of `LiveDocumentPanel` so that function stays
 * about SCHEDULING (spec 0017's fix pass, bug #10) and this one stays about DISPLAY. `empty` is
 * what the waiting state shows (the `EmptyStepPanel`, which owns the pinned sentence). */
function LiveDocumentPanelContent({ snapshot, empty }: { snapshot: DocumentSnapshot | null; empty: ReactNode }) {
  if (!snapshot) return <p className="text-sm text-ink-3">Opening…</p>

  if (snapshot.kind === 'error') {
    return <Notice tone="error">{snapshot.message}</Notice>
  }
  if (snapshot.kind === 'waiting') return empty

  const { sections } = snapshot.doc
  return (
    <Card data-testid="live-document-panel" className="space-y-3 p-4" padding="none">
      {sections.length > 0 ? (
        // The SAME field-by-field rendering DocumentView uses (bug #9) — an unfilled field
        // reads "Empty", a field the shape declares but the document lacks reads "Not in this
        // document.", never raw placeholder text. Read-only: no `editing`, no `onSaveField`.
        sections.map((s) => <SectionCard key={s.key} section={s} />)
      ) : (
        <p className="text-sm text-ink-3">This document is still empty.</p>
      )}
    </Card>
  )
}

// --- the honest empty step (round 2, S4) --------------------------------------------------------

/** The `create` activities whose `creates` list names this document — exact path first; a bare
 * file name (a fixture, an older plugin) matches on the name alone. The activities are the
 * plugin's own rows for THIS stage, so the match never reaches another stage's document. */
export function activitiesCreating(readiness: StageReadiness, doc: StageDocument): ActivityRow[] {
  const bare = !doc.path.includes('/')
  const names = (p: string) => p.split('/').pop() ?? p
  return computeActivityRows(readiness).filter(({ activity }) =>
    activity.kind === 'create'
    && activity.creates.some((p) => p === doc.path || (bare && names(p) === doc.path)))
}

/** What a step that has no file yet says (S4): the pinned sentence, the template's own
 * description, how the document gets created (the plugin's `create` activities for it, by label
 * and slash command, and the chat), the ONE start control — only for an `available` activity
 * Studio can honour; a blocked one shows its reason and no button — and a quiet "Up next". */
function EmptyStepPanel({
  projectPath, readiness, viewed, steps, onOpenDocument, onRefresh,
}: {
  projectPath: string
  readiness: StageReadiness
  viewed: DocumentWorkflowStep
  steps: WorkflowStep[]
  onOpenDocument: (relPath: string, focus?: DocumentFocus) => void
  onRefresh?: () => Promise<void>
}) {
  const creators = activitiesCreating(readiness, viewed.document)
  const startable = creators.find((r) => r.status === 'available' && r.disabledReason === null) ?? null
  const at = steps.findIndex((s) => s.key === viewed.key)
  const upNext = at >= 0 ? steps.slice(at + 1) : []
  return (
    <div className="space-y-4" data-testid="empty-step-panel">
      {/* The kit's "nothing here, and why" frame (G4-9); the sentence is the one workflow.spec finds. */}
      <EmptyState
        figure="page"
        title="Not started yet — this will appear here as soon as it is created."
        body={viewed.document.description}
        action={startable ? (
          <StartFromTemplate
            projectPath={projectPath}
            stageId={readiness.stageId}
            activity={startable.activity}
            onOpenDocument={onOpenDocument}
            onRefresh={onRefresh}
          />
        ) : creators.length === 0 && (
          // No `create` activity covers this document (most do not), so there was no way to start it
          // from here at all. Starting it from its own template is the same never-overwrite write.
          <StartThisDocument
            projectPath={projectPath}
            relPath={viewed.document.path}
            onOpenDocument={onOpenDocument}
            onRefresh={onRefresh}
          />
        )}
      />
      <section aria-labelledby={`how-created-${viewed.key}`}>
        <Eyebrow as="h3" id={`how-created-${viewed.key}`}>How it gets created</Eyebrow>
        <ul className="mt-1 space-y-1 text-xs text-ink-2">
          {creators.map(({ activity, status, reason, disabledReason }) => (
            <li key={activity.id} data-testid="empty-step-creator" data-activity-status={status}>
              <span className="text-ink-1">{activity.label}</span>
              {activity.command && <> · <code className="rounded bg-surface-2 px-1 py-0.5 text-code text-ink-2">{slashCommand(activity.command)}</code></>}
              {status === 'done' && <span className="text-ink-3"> — already run</span>}
              {/* The plugin's own sentence for a blocked row; the missing-capability reason for one
                  Studio cannot honour. Either way the reason is said and no button is drawn. */}
              {status === 'blocked' && reason && <span className="text-ink-3" data-testid="empty-step-reason"> — {reason}</span>}
              {status === 'available' && disabledReason && <span className="text-ink-3" data-testid="empty-step-reason"> — {disabledReason}</span>}
            </li>
          ))}
          <li>Ask in Chat — the assistant drafts it from this stage's documents, and you keep or discard the draft.</li>
        </ul>
      </section>
      {upNext.length > 0 && (
        <section aria-labelledby={`up-next-${viewed.key}`}>
          <Eyebrow as="h3" id={`up-next-${viewed.key}`}>Up next</Eyebrow>
          <ol className="mt-1 space-y-0.5 text-xs text-ink-3">
            {upNext.map((s) => <li key={s.key}>{s.title}</li>)}
          </ol>
        </section>
      )}
    </div>
  )
}

/** The one start control: the same `ensureDocumentFromTemplate` the "Also in this stage" list
 * runs, so there is still exactly one write path for starting a document. */
function StartFromTemplate({
  projectPath, stageId, activity, onOpenDocument, onRefresh,
}: {
  projectPath: string
  stageId: string
  activity: StageActivity
  onOpenDocument: (relPath: string, focus?: DocumentFocus) => void
  onRefresh?: () => Promise<void>
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const start = async () => {
    setBusy(true)
    setError(null)
    try {
      const result = await ensureDocumentFromTemplate({ projectPath, stageId, activityId: activity.id, onOpenDocument, onRefresh })
      if (!result.ok) setError(result.error ?? 'The document could not be started.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The document could not be started.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <Button variant="primary" size="sm" onClick={start} loading={busy} loadingLabel="Starting…" disabled={busy}>
        Start from template
      </Button>
      {error && <Notice tone="error" role="alert" className="mt-2">{error}</Notice>}
    </>
  )
}

/** Starts ONE document from the plugin's template when no `create` activity covers it. Creates the
 * file (never over an existing one), re-reads the stage, then opens it. A refusal is shown in words
 * and nothing opens; the button cannot be pressed twice while it works. */
function StartThisDocument({
  projectPath, relPath, onOpenDocument, onRefresh,
}: {
  projectPath: string
  relPath: string
  onOpenDocument: (relPath: string, focus?: DocumentFocus) => void
  onRefresh?: () => Promise<void>
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const start = async () => {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const result = await window.studio.startDocument(projectPath, relPath)
      if (!result.ok) {
        setError(result.error ?? 'This document could not be started.')
        return
      }
      await onRefresh?.()
      onOpenDocument(relPath)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'This document could not be started.')
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <Button variant="primary" size="sm" onClick={start} loading={busy} loadingLabel="Starting…" disabled={busy}>
        Start this document
      </Button>
      {error && <Notice tone="error" role="alert" className="mt-2">{error}</Notice>}
    </>
  )
}
