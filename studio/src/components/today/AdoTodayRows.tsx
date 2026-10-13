// The Azure Boards rows of the Today column (build kit §5 B4-P4, K18): a sibling
// `<section data-testid="ado-today">` mounted in both Today renderers (`TodayColumn`, `LifecycleHome`), fed by
// `commandCenter.ado` — the plugin's own `ado_sync.py status --json`, read once with the other blocks. Two rows,
// each a `role="listitem"` with ONE action and no `data-write`:
//
//   * "Changed on the board" — how many items moved on the board since the last pull, and how many of those are
//     in conflict. `Show` opens the classes and the rows past their two-business-day clock, by ref and field —
//     never by person.
//   * "Not yet a spec" — how many board items sit under the mirror's paths with no spec here. `Propose spec`
//     shows the plugin line that writes a proposal for each; Shepherd does not run it (the closed Boards request
//     table has no such verb), so the row stays a read. The count is read ONLY from an `UNMAPPED_IN_ADO` entry the
//     plugin put in `by_class`: a pull classes the items already in the ledger, it never runs the search for board
//     items with no spec, so a `by_class` without that entry means "not counted" — never a zero.
//
// These are NOT needs-you items: `NeedsYouItem.kind` is never widened, and nothing here is counted into the
// chip in the top band. Honesty (house rule 2): a count the plugin never measured is `null` and reads
// "Not pulled yet" — three words, no digit; an integer 0 appears only after a read that found none, and is said
// in words ("nothing changed on the board since the last pull"), never as a bare number. The rows hold no IPC
// and never read the plugin's local files: everything they show is the one `AdoSyncView` document.
import { useState } from 'react'
import type { AdoSyncView } from '../../../shared/adoTypes'
import { plural } from '../../../shared/format'
import { NOT_PULLED_YET, UNDATED } from '../../../shared/reasons'
import type { CommandCenter, SourcedBlock } from '../../../shared/types'
import { Button, Eyebrow, cn } from '../../ui'

/** The reason both actions are withheld after a pull that found nothing to act on. */
export const NOTHING_WAITING = 'Nothing is waiting here'

/** The unmapped row when the plugin's document holds no `UNMAPPED_IN_ADO` count: the search never ran, so there is
 * no number to show (house rule 2: not measured is not zero). Digit-free. */
export const UNMAPPED_NOT_COUNTED = 'not counted — only the proposal line searches the board for these'

const SOURCE = 'ado_sync.py status --json'
const UNMAPPED_CLASS = 'UNMAPPED_IN_ADO'
const PROPOSE_COMMAND = 'ado_sync.py pull --propose-specs'

export type AdoTodayKey = 'drift' | 'unmapped'

export interface AdoTodayRow {
  key: AdoTodayKey
  label: string
  /** The row's sentence. Digit-free whenever `measured` is false. */
  text: string
  /** True only when the plugin measured this count (a pull happened); false reads as words, never a number. */
  measured: boolean
  action: 'Show' | 'Propose spec'
  /** Why the action is withheld, or null when it is offered. */
  reason: string | null
  /** The lines the action reveals; empty when there is nothing to reveal. A line starting `ado_sync.py` is a command. */
  detail: string[]
}

type AdoBlock = SourcedBlock<AdoSyncView> | null | undefined

function driftRow(view: AdoSyncView): AdoTodayRow {
  const base = { key: 'drift', label: 'Changed on the board', action: 'Show' } as const
  const drifted = view.counts.drifted
  if (drifted === null) return { ...base, text: NOT_PULLED_YET, measured: false, reason: NOT_PULLED_YET, detail: [] }
  if (drifted === 0) return { ...base, text: 'nothing changed on the board since the last pull', measured: true, reason: NOTHING_WAITING, detail: [] }
  const conflicts = view.counts.conflicts
  const detail = [
    ...Object.entries(view.by_class ?? {}).sort(([a], [b]) => a.localeCompare(b)).map(([cls, n]) => `${cls} · ${n}`),
    ...(view.debt ?? []).map((d) => [d.ref, d.field, d.class, `due ${d.due}`].filter((part): part is string => part !== null).join(' · ')),
  ]
  return {
    ...base,
    text: `${plural(drifted, 'item', 'items')} changed on the board${conflicts !== null && conflicts > 0 ? ` · ${conflicts} in conflict` : ''}`,
    measured: true, reason: null, detail,
  }
}

function unmappedRow(view: AdoSyncView): AdoTodayRow {
  const base = { key: 'unmapped', label: 'Not yet a spec', action: 'Propose spec' } as const
  if (view.by_class === null) return { ...base, text: NOT_PULLED_YET, measured: false, reason: NOT_PULLED_YET, detail: [] }
  const n = view.by_class[UNMAPPED_CLASS]
  // No entry: the plugin never searched for these, so it is not a count of zero. The action stays offered: it only
  // shows the line that does the search.
  if (typeof n !== 'number') {
    return {
      ...base, text: UNMAPPED_NOT_COUNTED, measured: false, reason: null,
      detail: ['Shepherd does not run this one: it searches the board for items that no spec here answers and writes a proposal file for each.', PROPOSE_COMMAND],
    }
  }
  if (n === 0) return { ...base, text: 'no item on the board is without a spec here', measured: true, reason: NOTHING_WAITING, detail: [] }
  return {
    ...base, text: `${plural(n, 'item', 'items')} on the board with no spec here`, measured: true, reason: null,
    detail: ['Shepherd does not run this one: it writes a proposal file for each item on the board that no spec here answers.', PROPOSE_COMMAND],
  }
}

/** The two rows from the command center's `ado` block: what the plugin measured, in words. A block that is
 * absent, null or empty is "Not pulled yet" on both rows; a block the plugin could not answer carries its own
 * sentence on both, and as the reason for the action. Pure: no IPC, no clock. */
export function adoTodayRows(block: AdoBlock): AdoTodayRow[] {
  const view = block?.data ?? null
  if (view !== null) return [driftRow(view), unmappedRow(view)]
  const said = block?.error?.trim() ? block.error.trim() : null
  const text = said ?? NOT_PULLED_YET
  return (['drift', 'unmapped'] as const).map((key) => ({
    key, label: key === 'drift' ? 'Changed on the board' : 'Not yet a spec', text, measured: false,
    action: key === 'drift' ? 'Show' : 'Propose spec', reason: text, detail: [],
  }))
}

/** "2026-10-12 09:02" from the plugin's ISO stamp, or the word "undated". */
function asOfText(at: string): string {
  const m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(at)
  return m ? `${m[1]} ${m[2]}` : at || UNDATED
}

export interface AdoTodayRowsProps {
  /** The one read model, or null before it lands; only its `ado` block is read. */
  cc: Pick<CommandCenter, 'ado'> | null
  /** Drawn in the strip above the lanes (the home under 1240 px): the rows sit side by side and wrap. */
  strip?: boolean
  className?: string
}

export function AdoTodayRows({ cc, strip = false, className }: AdoTodayRowsProps) {
  const block = cc?.ado
  const rows = adoTodayRows(block)
  const asOf = block?.data?.as_of ?? null
  const [open, setOpen] = useState<Record<AdoTodayKey, boolean>>({ drift: false, unmapped: false })
  return (
    <section aria-labelledby="ado-today-title" data-testid="ado-today" className={cn('space-y-2', className)}>
      <Eyebrow as="h3" id="ado-today-title">Azure Boards</Eyebrow>
      <ul role="list" className={cn('m-0 list-none p-0', strip ? 'flex flex-wrap gap-2' : 'space-y-1')}>
        {rows.map((row) => {
          const shown = open[row.key] && row.reason === null
          const detailId = `ado-today-${row.key}-detail`
          return (
            <li key={row.key} role="listitem" data-ado-row={row.key} title={block?.source ?? SOURCE} className={cn('min-h-[44px] rounded-[10px] border-l-2 border-line-2 bg-surface-1 px-3 py-2 text-xs text-ink-2', strip && 'min-w-[220px] flex-1')}>
              <div className="flex items-center gap-2">
                <span className="font-medium text-ink-1">{row.label}</span>
                <span className="ml-auto shrink-0">
                  <Button
                    size="sm" variant="secondary" aria-expanded={shown} aria-controls={shown ? detailId : undefined}
                    disabled={row.reason !== null} disabledReason={row.reason ?? undefined}
                    onClick={() => setOpen((prev) => ({ ...prev, [row.key]: !prev[row.key] }))}
                  >{row.action}</Button>
                </span>
              </div>
              <p className="mt-1 line-clamp-2 text-[13px] leading-[18px]" data-ado-text="" title={row.text}>{row.text}</p>
              {shown ? (
                <div id={detailId} data-ado-detail={row.key} className="mt-1 space-y-0.5 text-[11px] text-ink-3">
                  {row.detail.map((line) => (
                    <p key={line} className="m-0 [overflow-wrap:anywhere]">
                      {line.startsWith('ado_sync.py ') ? <code className="font-mono text-ident text-ink-2">{line}</code> : line}
                    </p>
                  ))}
                </div>
              ) : null}
            </li>
          )
        })}
      </ul>
      {asOf ? <p className="font-mono text-ident text-ink-3" data-testid="ado-as-of">as of {asOfText(asOf)}</p> : null}
    </section>
  )
}
