// The findings ledger (togo-command-center.md §3.3): "Findings touching this spec's scope paths",
// rows from `record_findings.py report --json --spec` `findings[]` with the plugin's own
// disposition words in the `ledger-*` tones, `off_books` outlined and said in words, "seen N times
// across reports" from `recurrence`, the unattributed count STATED — only while there is a row to
// attribute: beside an empty ledger a "0 attributed" is a zero standing in for no data (visual §8
// #6), so the empty state's sentence is the whole block. "Promote to a permanent check" is present
// and disabled (`reasons.PROMOTE_FINDING`). Nothing is counted here: `tracked`, `openDebt`,
// `attribution` are the plugin's numbers shown as given.
import type { FindingRow, FindingsView } from '../../../shared/types'
import { newerPlugin, NO_DATA, PROMOTE_FINDING } from '../../../shared/reasons'
import { Button, Eyebrow, cn } from '../../ui'
import { CcEmptyFigure } from '../brand/figures'

export const LEDGER_TITLE = "Findings touching this spec's scope paths"
export const OFF_BOOKS = 'off the books'
export const PROMOTE = 'Promote to a permanent check'

/** The plugin's five words (`findings_model`); anything else is drawn neutral, as written. */
const TONE: Record<string, string> = {
  OPEN: 'bg-ledger-open-bg text-ledger-open-ink',
  FIXED: 'bg-ledger-fixed-bg text-ledger-fixed-ink',
  SPLIT: 'bg-ledger-split-bg text-ledger-split-ink',
  ACCEPTED_RISK: 'bg-ledger-accepted-bg text-ledger-accepted-ink',
  POSTPONED: 'bg-ledger-postponed-bg text-ledger-postponed-ink',
}

export function seenLabel(rounds: number | undefined): string | null {
  if (rounds === undefined || rounds <= 1) return null
  return `seen ${rounds} times across reports`
}

export interface FindingsLedgerProps {
  findings: FindingsView | null
  error?: string | null
  hasFindingsCapability?: boolean
}

export function FindingsLedger({ findings, error = null, hasFindingsCapability = true }: FindingsLedgerProps) {
  const rows: FindingRow[] = findings?.findings ?? []
  return (
    <section aria-label={LEDGER_TITLE} data-testid="findings-ledger" className="space-y-3">
      <div className="flex items-baseline justify-between gap-2">
        <Eyebrow as="h3">{LEDGER_TITLE}</Eyebrow>
        {findings && rows.length > 0 && (
          <span className="text-xs text-ink-3" data-testid="findings-attribution">
            {findings.attribution
              ? `${findings.attribution.attributed} attributed · ${findings.attribution.unattributed} unattributed (${findings.attribution.method})`
              : `${findings.tracked} tracked project-wide · open debt ${findings.openDebt}`}
          </span>
        )}
      </div>
      {!findings ? (
        <p className="text-xs text-ink-3" data-testid="findings-empty">{!hasFindingsCapability ? newerPlugin('findings-json') : error ?? NO_DATA}</p>
      ) : rows.length === 0 ? (
        <div className="flex flex-col items-start gap-2 rounded-xl border border-dashed border-line-2 px-5 py-6">
          <CcEmptyFigure figure="no-findings" />
          <p className="text-[13px] leading-[18px] text-ink-2">{findings.tracked === 0 ? 'no findings recorded — the ledger is empty' : 'no finding targets a path under this spec\'s scope'}</p>
          {/* The inline code chips are taller than a 12 px line (the kit's `code` adds 2 px padding
              and a 1 px border around 13 px mono) and painted over the line above when the sentence
              wrapped (v13 spec-card shots at 1280 and 1680). Two guards, so neither alone has to
              hold: the line pitch is 24 px (`leading-6`) and the chips drop their vertical padding
              (`py-0`: ≈ 18 px tall, inside the pitch with room). The e2e probe
              (`overlap.spec` "spec-card caption") measures the chips against the text. */}
          <p className="text-xs leading-6 text-ink-3 [&_code]:py-0" data-testid="findings-caption">A <code className="font-mono text-ident">/sprd-review</code> report recorded with <code className="font-mono text-ident">record_findings.py record</code> would appear here.</p>
        </div>
      ) : (
        <ul className="divide-y divide-line-1" role="list">
          {rows.map((f) => {
            const rounds = findings.recurrence[f.fingerprint] ?? f.rounds
            const seen = seenLabel(rounds)
            return (
              <li key={f.fingerprint} className="flex min-h-11 items-start gap-3 py-2" data-finding={f.fingerprint} data-disposition={f.disposition} data-off-books={f.offBooks ? '' : undefined}>
                <span className={cn('mt-0.5 inline-flex h-[18px] shrink-0 items-center rounded-full px-1.5 text-[11px] font-medium', TONE[f.disposition] ?? 'bg-surface-2 text-ink-2', f.offBooks && 'ring-1 ring-ledger-offbooks')}>
                  {f.disposition}
                </span>
                <div className="min-w-0 flex-1 text-xs">
                  <p className="text-ink-1"><span className="font-mono text-ident text-ink-2">{f.id}</span> · {f.category} · {f.severity}</p>
                  <p className="text-ink-2">{f.detail}</p>
                  <p className="font-mono text-ident text-ink-3">{f.target}</p>
                  <p className="text-ink-3">
                    {f.offBooks && <span className="text-status-error-ink" data-testid="off-books">{OFF_BOOKS} · </span>}
                    {seen ? <span data-testid="seen">{seen}</span> : <span>seen once</span>}
                  </p>
                </div>
                <Button size="sm" disabled disabledReason={PROMOTE_FINDING}>{PROMOTE}</Button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
