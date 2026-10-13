import { useMemo, useState } from 'react'
import { collapse, describeDiff, diffLines, type DiffLine } from '../../shared/lineDiff'
import { Notice } from '../ui'

/** How two versions differ: one plain sentence, then only the lines that changed with a little
 * context, the identical stretches folded away, and inside a changed line only the words that
 * differ. Neither side is "removed" or "added" — both are somebody's version — so the two are
 * labelled Yours and Theirs rather than coloured as bad and good. */
export function ClashDiff({ mine, theirs }: { mine: string; theirs: string }) {
  const diff = useMemo(() => diffLines(mine, theirs), [mine, theirs])
  const hunks = useMemo(() => collapse(diff.lines, 2), [diff])

  return (
    <div>
      <p className="px-4 py-3 text-sm font-medium text-ink-1">{describeDiff(diff)}</p>
      {diff.tooLarge && (
        <Notice tone="warn" className="mx-4 mb-2">
          These are too different to line up, so each side&apos;s changed lines are shown whole.
        </Notice>
      )}
      {diff.changedLines > 0 && (
        <div className="border-t border-line-1">
          {hunks.map((h, i) =>
            h.type === 'lines'
              ? h.lines.map((line, k) => <Row key={`${i}-${k}`} line={line} />)
              : <Fold key={i} count={h.count} lines={h.lines} />,
          )}
        </div>
      )}
    </div>
  )
}

// "Yours" takes the accent, "Theirs" the warn hue — the same pairing the version cards above
// the diff use, so a glance at a row's colour says whose it is.
const TONE = {
  same: { row: '', label: '', mark: '' },
  mine: { row: 'bg-accent-50', label: 'text-accent-text', mark: 'bg-accent-200' },
  theirs: { row: 'bg-amber-50', label: 'text-status-warn-ink', mark: 'bg-amber-200' },
} as const

function Row({ line }: { line: DiffLine }) {
  const tone = TONE[line.kind]
  return (
    <div className={`flex gap-3 px-4 py-0.5 font-mono text-[12.5px] leading-relaxed text-ink-1 ${tone.row}`}>
      <span className={`w-12 shrink-0 select-none text-[10px] font-semibold uppercase tracking-wide ${tone.label}`}>
        {line.kind === 'mine' ? 'Yours' : line.kind === 'theirs' ? 'Theirs' : ''}
      </span>
      <span className="min-w-0 whitespace-pre-wrap break-words">
        {line.segments
          ? line.segments.map((s, i) =>
              s.changed
                ? <mark key={i} className={`rounded px-0.5 text-ink-1 ${tone.mark}`}>{s.text}</mark>
                : <span key={i}>{s.text}</span>,
            )
          : line.text || ' '}
      </span>
    </div>
  )
}

/** A stretch of identical lines, folded to one row that says how long it is. The lines are only
 * put on screen if asked for, so a long document does not print its unchanged middle. */
function Fold({ count, lines }: { count: number; lines: DiffLine[] }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border-y border-dashed border-line-1 bg-surface-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full px-4 py-1 text-left text-xs text-ink-3 hover:text-ink-1"
      >
        {`${open ? '▾' : '▸'} ${count} identical ${count === 1 ? 'line' : 'lines'}`}
      </button>
      {open && lines.map((line, i) => <Row key={i} line={line} />)}
    </div>
  )
}
