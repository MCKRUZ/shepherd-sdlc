// `Catch up` (build kit §5 B6-P3; owner decision 2026-10-15): the Today column's answer to "has the board moved while I
// was away", without reading the board on its own. Opening a project asks the board nothing; instead this section says
// how old the mirror is, in the same four states the spec card's chip derives (`adoChipView`):
//   * `Board as of <stamp>` — the plugin's own `as_of`;
//   * `Not pulled yet` — the mirror has never pulled;
//   * `Work items are not set up for this project` — the host is not Azure DevOps (and then no button: there is no
//     board to ask);
//   * `no data` — the status was not read, or the plugin could not answer it.
// Every no-data state is words with no digit.
//
// Beneath the line sit the two reads, as `PullNow`'s own buttons: **Catch up** is the board's FIELDS (the closed `pull`
// request, for every ledgered item) and **Pull discussion** is its COMMENTS — a second, separate click that is never
// implied by the first. Each is a `data-write`; neither runs on mount, on a timer, or after another verb, and this file
// holds no effect and no timer of its own, so a day that passes spawns nothing.
//
// The host hands in what the command center already read (`ado`, `capabilities`) and re-reads when `onPulled` says a
// pull landed; nothing here opens the mirror's files. Steering mode (`steering`) draws nothing.
import type { AdoSyncView } from '../../../shared/adoTypes'
import type { SourcedBlock } from '../../../shared/types'
import { hostFeatureReason, WORDING } from '../../../shared/codeHostModel'
import { NO_DATA, NOT_PULLED_YET, UNDATED, WORK_ITEMS_NOT_SET_UP } from '../../../shared/reasons'
import { Eyebrow } from '../../ui'
import { useConnection } from '../../stores/connectionStore'
import { adoChipView, type AdoChipState } from './AdoChip'
import { PullNow } from './PullNow'

/** What the section's own button is called: the fields pull, under the words a person coming back to work reaches for. */
export const CATCH_UP_LABEL = 'Catch up'

export interface CatchUpLine {
  state: AdoChipState
  /** The whole visible line. Digit-free in every state but `Board as of <stamp>`. */
  text: string
}

/** "2026-10-12 09:02" from the plugin's ISO stamp; the stamp as written when it is not one; the word "undated" for none. */
function stampOf(at: string | null): string {
  if (!at) return UNDATED
  const m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(at)
  return m ? `${m[1]} ${m[2]}` : at
}

/** How old the mirror is, from the status block alone: `adoChipView`'s own states, said for the project (a spec's drift
 * is the chip's business, never this line's — no spec is named, so none can match). Pure. */
export function catchUpLine({ block, notSetUp }: { block: SourcedBlock<AdoSyncView> | null; notSetUp: boolean }): CatchUpLine {
  const { state } = adoChipView({ block, notSetUp, specId: '' })
  switch (state) {
    case 'not-set-up': return { state, text: WORK_ITEMS_NOT_SET_UP }
    case 'no-data': return { state, text: NO_DATA }
    case 'not-pulled': return { state, text: NOT_PULLED_YET }
    default: return { state, text: `Board as of ${stampOf(block?.data?.as_of ?? null)}` }
  }
}

export interface CatchUpProps {
  projectPath: string
  /** The command center's `ado` block; null/undefined when it was not read (no plugin, an older command center). */
  ado: SourcedBlock<AdoSyncView> | null | undefined
  /** `generate_status.py --json` capabilities; null/undefined while unknown (main still refuses a verb the plugin lacks). */
  capabilities: readonly string[] | null | undefined
  /** Steering mode is read-only: nothing is drawn. */
  steering?: boolean
  /** Called after a pull that READ the board, with which pull and the plugin's answer: the host re-reads what it holds. */
  onPulled?: Parameters<typeof PullNow>[0]['onPulled']
}

export function CatchUp({ projectPath, ado, capabilities, steering = false, onPulled }: CatchUpProps) {
  const connection = useConnection()
  if (steering) return null

  const notSetUp = connection ? hostFeatureReason(connection, 'workItems') === WORDING.boardsNotConfigured : false
  const line = catchUpLine({ block: ado ?? null, notSetUp })
  return (
    <section aria-labelledby="ado-catch-up-title" data-testid="ado-catch-up" className="space-y-2">
      <Eyebrow as="h3" id="ado-catch-up-title">Catch up with the board</Eyebrow>
      <p data-testid="catch-up-line" data-state={line.state} className="m-0 text-xs text-ink-2" title={ado?.error ?? undefined}>{line.text}</p>
      {notSetUp ? null : (
        <PullNow projectPath={projectPath} capabilities={capabilities ?? null} scope="both" labels={{ fields: CATCH_UP_LABEL }} onPulled={onPulled} />
      )}
    </section>
  )
}
