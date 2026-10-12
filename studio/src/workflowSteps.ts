/** Turning stage readiness into a step-by-step sequence (spec 0017).
 *
 * One step per required document, in the stage's own declared order — `readiness.documents` is
 * already in that order (see electron/main/readiness.ts / scripts/stage_readiness.py's
 * `required_artifacts`) — plus a trailing Sign-off step.
 *
 * The rule spec 0017 fixes is the CURRENT step: the first not-ready document in that order,
 * never "whichever was edited most recently". This function only ever looks at order and each
 * document's own `ready` flag — there is no timestamp anywhere in a `StageDocument` for it to
 * consult even if it wanted to — so reopening a stage after touching a later document still
 * lands back where the sequence actually is. Once every document is ready, the Sign-off step
 * takes the current slot.
 *
 * This is the ONE place that decides done / current / locked. The Workflow tab and the
 * Documents tab both trace back to it — the Documents tab reads `document.ready` directly,
 * which is exactly what this derives "done" from — so the two can never disagree about how
 * many documents are done. That is spec 0017's shared-source acceptance check, made true by
 * construction rather than by convention.
 */

import type { ActivityStatus, StageActivity, StageDocument, StageReadiness } from '../shared/types'
import { capabilityFor, isDrawn } from '../shared/activityControls'

export type WorkflowStepStatus = 'done' | 'current' | 'locked'

export interface DocumentWorkflowStep {
  kind: 'document'
  /** The document's own path — stable, and already what the Documents tab keys its rows by. */
  key: string
  title: string
  description?: string
  status: WorkflowStepStatus
  document: StageDocument
}

export interface SignOffWorkflowStep {
  kind: 'sign-off'
  key: 'sign-off'
  title: string
  description?: string
  status: WorkflowStepStatus
}

export type WorkflowStep = DocumentWorkflowStep | SignOffWorkflowStep

export function computeWorkflowSteps(readiness: StageReadiness): WorkflowStep[] {
  const steps: WorkflowStep[] = []
  let foundCurrent = false

  for (const doc of readiness.documents) {
    let status: WorkflowStepStatus
    if (doc.ready) {
      status = 'done'
    } else if (!foundCurrent) {
      status = 'current'
      foundCurrent = true
    } else {
      status = 'locked'
    }
    steps.push({
      kind: 'document',
      key: doc.path,
      title: doc.name,
      // The exact same sentence the Documents tab already shows for this document — pulled
      // from the same field, not retyped, so there is nothing here that can drift out of sync
      // with it.
      description: doc.description,
      status,
      document: doc,
    })
  }

  steps.push({
    kind: 'sign-off',
    key: 'sign-off',
    title: 'Sign-off',
    description: 'Confirm the questions for whoever signs this stage off.',
    // Locked while any document still isn't ready. Otherwise done when the stage's own record
    // says it actually was signed off (readiness.signOff.status, the same field the Documents
    // tab already reads to show "Signed off by X.") — never just "every document is ready",
    // which is what makes the step CURRENT, not DONE: the stage can sit fully ready and
    // unsigned for a while, and that is a real, different state from having been signed off.
    status: foundCurrent ? 'locked' : readiness.signOff.status === 'signed_off' ? 'done' : 'current',
  })

  return steps
}

/** One optional activity to draw under the step list (spec 0024). */
export interface ActivityRow {
  activity: StageActivity
  status: ActivityStatus
  /** The plugin's own sentence, unchanged, when `blocked`. */
  reason: string | null
  /** Why the control is disabled even though the activity itself is not blocked: the installed
   * plugin lacks what the control needs. Null when the control can be used. */
  disabledReason: string | null
}

/** The activity rows to draw under the document steps, in the plugin's declared order.
 *
 * Empty when the plugin emitted no `activities` key at all (an older plugin): the tab is then
 * exactly what it was before spec 0024. Only activities Studio has a control for are drawn
 * (`isDrawn`); the rest are listed in the Guide tab instead. This never touches
 * `computeWorkflowSteps`: activities are optional and never gate a stage. */
export function computeActivityRows(readiness: StageReadiness): ActivityRow[] {
  if (readiness.activities === undefined) return []
  return readiness.activities
    .filter(isDrawn)
    .map((activity) => ({
      activity,
      status: activity.status,
      reason: activity.reason,
      disabledReason: missingCapabilityReason(activity, readiness.capabilities),
    }))
}

/** `capabilities` undefined means the plugin cannot say what it supports. The presence of the
 * `activities` key already proves it knows create and talk, but a check's script may be absent,
 * so only checks are treated as missing then. */
function missingCapabilityReason(activity: StageActivity, capabilities: string[] | undefined): string | null {
  const needed = capabilityFor(activity)
  if (needed === null) return null
  const missing = capabilities === undefined ? activity.kind === 'check' : !capabilities.includes(needed)
  return missing ? `needs a newer plugin: lacks ${needed}` : null
}

/** A plugin command as a person types it: the plugin declares `sprd-rules`, people read `/sprd-rules`. */
export function slashCommand(command: string): string {
  return command.startsWith('/') ? command : `/${command}`
}
