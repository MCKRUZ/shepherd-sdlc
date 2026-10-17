// The Boards nudge (build kit §5 B6-P3; owner decision 2026-10-15: nothing reads the board on its own). When a person
// changes something the board mirrors — a spec verb through the omnibar, a hand-off, a decision recorded from Today —
// the host says so ONCE, in a Notice: "Boards: <spec NNNN | sprint SNN | decision DL-NN> changed here — the board has
// not heard". Everything after that is a click, one control at a time:
//   1. **Plan board changes** — `PlanChanges`, one closed `plan` request for that item (or `{ verb: 'plan', sprint }`
//      for a sprint), and its one counts line;
//   2. **Review plan** — only when the plan has rows an apply would send (`pendingRowCount > 0`): it opens the apply
//      dialog on exactly the plan the plugin printed;
//   3. the dialog's Confirm — the one write, as whoever az is signed in as.
// It spawns NOTHING until clicked and never pulls: no fields, no discussion — this file holds no effect and no timer.
// After an apply that landed (exit 0) the plan is dropped (what was sent is not offered again, and the old counts line
// goes with it), the dialog stays up so the plugin's answer can be read, and closing it dismisses the nudge: the board
// has heard. An apply that did not land keeps the plan and the nudge.
//
// Drawn only while it can mean something: the host handed in the Boards block (`ado`, the command center's — an absent
// one means it was not read, so nothing is claimed), the project's host is Azure DevOps (a host not yet known is not
// "not Azure DevOps": the plugin decides at the click), and steering mode — which is read-only — is not showing.
//
// The module also holds the two small pure pieces the host needs to *use* it without importing a screen: which target an
// omnibar intent changed (`boardsTargetOf` — only what the host really knows; an id typed inside a dialog is never
// guessed), and `BoardsChanged`, the context through which a Today column that recorded a decision tells the host.
import { createContext, useContext, useState } from 'react'
import type { AdoSyncView } from '../../../shared/adoTypes'
import type { ActorInfo, SourcedBlock } from '../../../shared/types'
import { hostFeatureReason, WORDING } from '../../../shared/codeHostModel'
import type { Intent } from '../../palette/intents'
import { Button, Notice } from '../../ui'
import { useConnection } from '../../stores/connectionStore'
import { AdoApplyDialog, pendingRowCount, type AdoPlanDoc } from './AdoApplyDialog'
import { PlanChanges } from './PlanChanges'

/** What changed here: one item by kind and id (`spec` `0008`, `decision` `DL-03`), or a sprint. */
export type BoardsNudgeTarget = { kind: string; id: string } | { sprint: string }

/** `spec 0008`, `decision DL-03`, `sprint S07`: how the Notice names what changed. */
export function nudgeLabel(target: BoardsNudgeTarget): string {
  return 'sprint' in target ? `sprint ${target.sprint}` : `${target.kind} ${target.id}`
}

/** The target an omnibar intent changed once the plugin answered Done, or null when it wrote nothing the board mirrors
 * or the host does not know what it wrote (`new-sprint`: the id is typed in the dialog; `decision`: the plugin allocates
 * it). Pure; the sprint verbs that name a spec name that spec, the ones that name a sprint name the sprint. */
export function boardsTargetOf(intent: Intent): BoardsNudgeTarget | null {
  switch (intent.kind) {
    case 'sprint': {
      const request = intent.request
      switch (request.verb) {
        case 'unslate': case 'handoff': case 'ack': case 'verdict': case 'carry': return { kind: 'spec', id: request.spec }
        case 'slate': case 'ready': case 'close': case 'new': case 'edit': return { sprint: request.sprint }
      }
      return null
    }
    case 'pull': case 'defer': case 'confirm-tier': return { kind: 'spec', id: intent.spec }
    case 'decide': return { kind: 'decision', id: intent.id }
    case 'decision': case 'close': case 'new-sprint': return null
  }
}

/** How a Today column that recorded a decision tells the host, without the host being threaded through the sprint home:
 * absent (null) when no host provides it, so a column on its own tells nobody. */
export const BoardsChanged = createContext<((target: BoardsNudgeTarget) => void) | null>(null)
export const useBoardsChanged = () => useContext(BoardsChanged)

export interface BoardsNudgeProps {
  target: BoardsNudgeTarget
  projectPath: string
  /** The command center's `ado` block; null/undefined when it was not read — then nothing is drawn. */
  ado: SourcedBlock<AdoSyncView> | null | undefined
  /** `generate_status.py --json` capabilities; null/undefined while unknown (the plugin then decides). */
  capabilities: readonly string[] | null | undefined
  actor: ActorInfo | null | undefined
  /** Steering mode is read-only: nothing is drawn. */
  steering?: boolean
  onDismiss: () => void
}

export function BoardsNudge({ target, projectPath, ado, capabilities, actor, steering = false, onDismiss }: BoardsNudgeProps) {
  const connection = useConnection()
  const [plan, setPlan] = useState<AdoPlanDoc | null>(null)
  /** The plan the open dialog is showing: held apart from `plan`, so an apply that landed drops the plan (nothing left to
   * send) while the dialog stays up with the plugin's answer. */
  const [reviewing, setReviewing] = useState<AdoPlanDoc | null>(null)
  const [applied, setApplied] = useState(false)
  /** Bumped after an apply that landed: `PlanChanges` starts again from nothing, so its counts line is not the old plan's. */
  const [fresh, setFresh] = useState(0)

  const notSetUp = connection ? hostFeatureReason(connection, 'workItems') === WORDING.boardsNotConfigured : false
  if (steering || !ado || notSetUp) return null

  const reviewable = plan !== null && !plan.unavailable && pendingRowCount(plan) > 0
  const scope = 'sprint' in target ? { sprint: target.sprint } : { kind: target.kind, id: target.id }
  const closeReview = () => {
    setReviewing(null)
    if (applied) onDismiss()   // the board has now heard
  }

  return (
    <>
      <Notice
        tone="info"
        role="status"
        data-testid="boards-nudge"
        title={`Boards: ${nudgeLabel(target)} changed here — the board has not heard`}
        actions={<Button size="sm" variant="ghost" onClick={onDismiss}>Dismiss</Button>}
      >
        <div className="mt-1 flex flex-wrap items-start gap-2">
          <PlanChanges
            key={fresh}
            projectPath={projectPath}
            capabilities={capabilities}
            {...scope}
            label="Plan board changes"
            actor={actor}
            onPlanned={setPlan}
          />
          {reviewable ? <Button size="sm" onClick={() => { setApplied(false); setReviewing(plan) }}>Review plan</Button> : null}
        </div>
      </Notice>
      {reviewing ? (
        <AdoApplyDialog
          open
          projectPath={projectPath}
          plan={reviewing}
          capabilities={capabilities ?? undefined}
          actor={actor}
          onClose={closeReview}
          onApplied={() => { setApplied(true); setPlan(null); setFresh((n) => n + 1) }}
        />
      ) : null}
    </>
  )
}
