// The Azure Boards chip on the spec card (build kit §5 B4-P3; ado-boards-mirror.md §12 item 1). It says what the
// plugin's `ado_sync.py status --json` says about the work-item mirror — through the command center's `ado` block,
// or a block its host hands in — and nothing the plugin did not measure:
//   * a project whose host is not Azure DevOps: "Work items are not set up for this project" (read nothing);
//   * a status that was not read, or a plugin without `ado-status-json`: "Work items · no data";
//   * a mirror that never pulled: "Work items · Not pulled yet";
//   * an open drift or conflict on THIS spec past its two business days (the status `debt` rows, by ref): drift,
//     named by field — never by person;
//   * otherwise the plugin's own one-line summary, as the PROJECT's: a spec absent from `debt` is not thereby "in
//     sync" (drift younger than two business days is not in `debt`), so the chip never says it is.
// Every no-data state is words with no digit; a count the plugin printed as null is never drawn as a zero.
//
// The chip is a status. A plan the host hands in (`plan`: what `plan --json` / `comment --json` printed) that has
// rows an apply would send offers "Review plan", which opens `AdoApplyDialog` — whose Confirm is the one write.
// Steering mode (`steering`) draws the status and nothing that writes or opens: zero `data-write`, zero buttons.
// The chip never opens the mirror's files, never spawns `az`, and re-reads the command center after an apply landed.
import { useEffect, useState } from 'react'
import type { AdoSyncView } from '../../../shared/adoTypes'
import type { ActorInfo, SourcedBlock } from '../../../shared/types'
import { hostFeatureReason, WORDING } from '../../../shared/codeHostModel'
import { CAPABILITIES, NO_DATA, NOT_PULLED_YET, newerPlugin, WORK_ITEMS_NOT_SET_UP } from '../../../shared/reasons'
import { Button, Chip, type ChipTone } from '../../ui'
import { useConnection } from '../../stores/connectionStore'
import { AdoApplyDialog, pendingRowCount, type AdoPlanDoc } from './AdoApplyDialog'

export const WORK_ITEMS = 'Work items'
export const REVIEW_PLAN = 'Review plan'

export type AdoChipState = 'not-set-up' | 'no-data' | 'not-pulled' | 'drift' | 'status'

export interface AdoChipView {
  state: AdoChipState
  tone: ChipTone
  /** The chip's whole visible text. */
  text: string
  /** The longer sentence: the chip's `title`. */
  detail: string
}

export interface AdoChipViewInput {
  /** The command center's `ado` block; null when it was not read (no bridge, no block, a failed read). */
  block: SourcedBlock<AdoSyncView> | null
  /** `hostFeatureReason(connection, 'workItems') === WORDING.boardsNotConfigured`: the host is not Azure DevOps. */
  notSetUp: boolean
  /** The spec id as `row.spec` spells it (`0008`); the mirror's ref is `sdlc:spec:<id>`. */
  specId: string
  /** Why the status was not even asked (a plugin without `ado-status-json`); shown when there is no data. */
  unreadReason?: string | null
}

/** What the chip says, from the status document alone. Pure. */
export function adoChipView({ block, notSetUp, specId, unreadReason = null }: AdoChipViewInput): AdoChipView {
  if (notSetUp) return { state: 'not-set-up', tone: 'neutral', text: WORK_ITEMS_NOT_SET_UP, detail: WORK_ITEMS_NOT_SET_UP }
  const data = block?.ok ? block.data : null
  if (!data) {
    return { state: 'no-data', tone: 'neutral', text: `${WORK_ITEMS} · ${NO_DATA}`, detail: unreadReason || block?.error || 'The mirror status was not read.' }
  }
  if (data.as_of === null) {
    return { state: 'not-pulled', tone: 'neutral', text: `${WORK_ITEMS} · ${NOT_PULLED_YET}`, detail: data.notes[0] ?? NOT_PULLED_YET }
  }
  const ref = `sdlc:spec:${specId}`
  const mine = (data.debt ?? []).filter((row) => row.ref === ref)
  if (mine.length > 0) {
    const fields = [...new Set(mine.map((row) => row.field).filter((f): f is string => f !== null))]
    const what = [...fields, ...(mine.some((row) => row.field === null) ? ['the whole item'] : [])].join(', ')
    const detail = mine.map((row) => `${row.class} since ${row.seen}, due ${row.due}${row.field ? ` (${row.field})` : ''}`).join('; ')
    return { state: 'drift', tone: 'warn', text: `${WORK_ITEMS} · drift on ${what}`, detail }
  }
  return { state: 'status', tone: 'neutral', text: `${WORK_ITEMS} · ${data.hook_line}`, detail: `Mirror status for this project, as of ${data.as_of}.` }
}

export interface AdoChipProps {
  projectPath: string
  /** The spec id as `row.spec` spells it (`0008`). */
  specId: string
  /** `generate_status.py --json` capabilities; undefined while unknown (the plugin then decides). */
  capabilities?: readonly string[]
  actor?: ActorInfo | null
  /** Steering mode: a presentation — the status, with nothing that writes or opens. */
  steering?: boolean
  /** The Boards block, when the host already holds the command center. Absent: the chip reads it itself. */
  ado?: SourcedBlock<AdoSyncView> | null
  /** A plan to review (the JSON of `plan` / `comment`, read by `readAdoPlan`). Absent: no "Review plan". */
  plan?: AdoPlanDoc | null
  /** Called after an apply that landed (exit 0), once the chip has asked for a fresh read. */
  onApplied?: () => void
}

export function AdoChip({ projectPath, specId, capabilities, actor, steering = false, ado, plan = null, onApplied }: AdoChipProps) {
  const connection = useConnection()
  const notSetUp = connection ? hostFeatureReason(connection, 'workItems') === WORDING.boardsNotConfigured : false
  const statusLacks = capabilities !== undefined && !capabilities.includes(CAPABILITIES.adoStatus) ? newerPlugin(CAPABILITIES.adoStatus) : null
  // Read the command center only when nothing was handed in and the read can mean something: the host is Azure
  // DevOps and the plugin declares the status verb.
  const selfRead = ado === undefined && !notSetUp && statusLacks === null
  const [read, setRead] = useState<{ done: boolean; block: SourcedBlock<AdoSyncView> | null }>({ done: false, block: null })
  const [reads, setReads] = useState(0)
  const [reviewing, setReviewing] = useState(false)

  useEffect(() => {
    if (!selfRead) return
    let live = true
    const studio = window.studio as Partial<typeof window.studio> | undefined
    if (!studio || typeof studio.getCommandCenter !== 'function') { setRead({ done: true, block: null }); return }
    studio.getCommandCenter(projectPath).then(
      (center) => { if (live) setRead({ done: true, block: center?.ado ?? null }) },
      () => { if (live) setRead({ done: true, block: null }) },
    )
    return () => { live = false }
  }, [selfRead, projectPath, reads])

  // The first read is out: draw nothing yet, so a block that is on its way never flashes as "no data".
  if (selfRead && !read.done) return null

  const view = adoChipView({ block: ado !== undefined ? ado : read.block, notSetUp, specId, unreadReason: statusLacks })
  const reviewable = !steering && !notSetUp && plan !== null && !plan.unavailable && pendingRowCount(plan) > 0

  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <Chip data-testid="ado-chip" data-state={view.state} tone={view.tone} dot title={view.detail}>{view.text}</Chip>
      {reviewable ? <Button size="sm" onClick={() => setReviewing(true)}>{REVIEW_PLAN}</Button> : null}
      {reviewable && plan ? (
        <AdoApplyDialog
          open={reviewing}
          projectPath={projectPath}
          plan={plan}
          capabilities={capabilities}
          actor={actor}
          onClose={() => setReviewing(false)}
          onApplied={() => { setReads((n) => n + 1); onApplied?.() }}
        />
      ) : null}
    </span>
  )
}
