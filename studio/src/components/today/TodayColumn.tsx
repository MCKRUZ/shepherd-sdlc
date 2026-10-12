// The Today column (togo-command-center.md §3.1, visual §4 "Today 320 px"): `needsYou[]` first
// — one action each (Ack → `ack`, Open PR, Decide → `decideDecision`, Confirm → `confirmTier`),
// washed `today-act-bg`, `today-late-*` only on the plugin's `overdue:true` — then "Team is
// waiting on" (`verdicts_pending`, a lane and a wait, never a person), "since yesterday"
// (`sinceYesterday[]` with origin tags, the window a FILTER the person picks), "Claude's work" as
// one labelled line of Shepherd's own record, and a Standup notes button that is present, disabled,
// with its reason. The list main built is shown as it came: the chip in the TopBand is its length
// and nothing here re-counts it. A later row rises alone by its identity key, never a re-stagger.
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { Bell, Check, GitPullRequest, Hand, Scale } from 'lucide-react'
import type { CommandCenter, ConfirmTierResult, DecideDecisionResult, NeedsYouItem, SinceWindow, SprintVerbRequest, SprintVerbResult, StreamRow } from '../../../shared/types'
import { CAPABILITIES, exitHeading, LOOP_EVENTS_TOTALS_ONLY, NO_DATA, NOTHING_NEEDS_YOU, STANDUP_NOTES, STREAM_ARRIVES, UNDATED } from '../../../shared/reasons'
import { businessDays, groupVerdicts } from '../../../shared/sprintModel'
import { Button, Chip, cn, Disclosure, Eyebrow, Input, Segmented } from '../../ui'
import { TODAY_ROW_RISE } from '../../motion/presets'
import { enabled as motionEnabled, reduced as motionReduced } from '../../motion/motion'
import { engineFor } from '../../motion/useStudioGSAP'
import { CcEmptyFigure } from '../brand/figures'

export interface TodayColumnProps {
  cc: CommandCenter
  onRun: (request: SprintVerbRequest) => Promise<SprintVerbResult>
  onDecide: (id: string, resolution: string) => Promise<DecideDecisionResult>
  onConfirmTier: (specId: string) => Promise<ConfirmTierResult>
  onSince: (since: SinceWindow) => void
  /** Exit 0 anywhere → the host re-reads; nothing here moves on its own. */
  onActed: () => void
  /** Shepherd's own record of Claude's work this session, labelled as such; null → nothing drafted. */
  claudeLine: string | null
  /** Drawn as the STRIP above the lanes (the home under 1240 px): needs-you shows `STRIP_ROWS`
   * whole and folds the rest behind "N more"; the other groups keep their header and fold every
   * row behind "N rows". The rail (default) draws every row and scrolls. */
  strip?: boolean
  className?: string
}

const ICON: Record<NeedsYouItem['kind'], typeof Bell> = { ack: Hand, review: GitPullRequest, decide: Scale, 'confirm-tier': Check }
export const TEAM_WAITING_CAPTION = "a lane, not a person — the verdict is the team's"
const WINDOWS: { value: '1' | '3'; label: string }[] = [{ value: '1', label: '1 business day' }, { value: '3', label: '3 business days' }]

/** In the strip, needs-you shows this many rows whole; the rest fold. The OTHER groups keep their
 * header and fold every row (`shown` 0): at 1280×800 the strip has ≈ 108 px before the four
 * lanes' 240 px floor leaves the fold (372 top + 16 + 40 filter + 240 + 24), so a second whole
 * stream row (≈ 80 px each) cannot be afforded — needs-you is the group a person acts on. */
export const STRIP_ROWS = 2
/** The fold's summary — a count of rows on THIS screen, never a plugin number re-counted: "N
 * more" under rows that are shown, "N rows" when the group shows none. */
export const moreLabel = (hidden: number, shown = STRIP_ROWS): string => (shown > 0 ? `${hidden} more` : `${hidden} ${hidden === 1 ? 'row' : 'rows'}`)

/** A list's rows as the strip draws them: the first `shown` whole, the rest behind one
 * disclosure in a last `<li>` — so the list stays ONE list (every row is still a descendant of
 * the same `<ul>`, so a count of its rows is unchanged), nothing is cut mid-sentence and nothing
 * scrolls under a fade (v14 at 1280×800: the 120 px cap sliced "0005 data · today" and the fade
 * read as a cut). Off the strip the rows are returned as given. */
export function foldRows(rows: ReactNode[], strip: boolean, testId: string, listClass = 'mt-1 space-y-1', shown = STRIP_ROWS): ReactNode[] {
  if (!strip || rows.length <= shown) return rows
  const rest = rows.slice(shown)
  return [
    ...rows.slice(0, shown),
    <li key="more" data-fold="" className="list-none">
      <Disclosure data-testid={testId} summary={<span className="text-xs text-ink-3">{moreLabel(rest.length, shown)}</span>}>
        <ul className={listClass}>{rest}</ul>
      </Disclosure>
    </li>,
  ]
}

/** The PR url for a needs-you row, looked up on the board by exact spec id. */
export function prUrlFor(cc: CommandCenter, spec: string | undefined): string | null {
  if (!spec) return null
  return cc.board.data?.rows.find((r) => r.spec === spec)?.pullRequest?.url ?? null
}

/** "2026-10-05 16:10" from the source's ISO stamp, or the word "undated". */
export function stampText(at: string | null): string {
  if (!at) return UNDATED
  const m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(at)
  return m ? `${m[1]} ${m[2]}` : at
}

/** The stream row's own sentence, or null when the row has none to add: main's `text` carries
 * the ledger line's OTHER fields ("lane eng · verdict accepted", "to @sam-k") or the board's
 * "PR #40 merged"; the id line already shows origin, spec, event and stamp, and the by-line shows
 * `by`, so a row never says one fact three times (v13: "0003 handoff / handoff · 0003 · by Pod
 * Lead / by Pod Lead"). */
export function streamSentence(r: Pick<StreamRow, 'text'>): string | null {
  const t = r.text.trim()
  return t.length > 0 ? t : null
}

export function TodayColumn({ cc, onRun, onDecide, onConfirmTier, onSince, onActed, claudeLine, strip = false, className }: TodayColumnProps) {
  const sprint = cc.sprint.data
  const verdictGroups = sprint ? groupVerdicts(sprint.verdictsPending) : []
  const hasLog = cc.capabilities.includes(CAPABILITIES.sprintLog)
  return (
    // Owner's v12 item 1: a 300 px right rail (or a strip above the lanes on a narrow main),
    // needs-you first; 16 px between groups so the four groups fit the rail's height.
    <section data-testid="today" aria-label="Today" data-today-rail="" className={cn('grid grid-cols-1 gap-4', className)}>
      <section aria-labelledby="needs-you-title" className="space-y-2">
        <div className="flex items-baseline justify-between">
          <Eyebrow as="h3" id="needs-you-title">Needs you</Eyebrow>
          <span className="text-xs text-ink-3" title="main · exact handle match over the sourced blocks">addressed to {cc.actor?.name ?? 'nobody'}</span>
        </div>
        {cc.needsYou.length === 0 ? (
          <div className="flex items-center gap-3 rounded-[10px] border border-dashed border-line-2 px-4 py-4" data-testid="needs-you-empty">
            <CcEmptyFigure figure="nothing-needs-you" className="h-12 w-20" />
            <p className="text-sm text-ink-2">{cc.needsYouReason ?? NOTHING_NEEDS_YOU}</p>
          </div>
        ) : (
          <ul className="space-y-2" data-testid="needs-you-list">
            {foldRows(cc.needsYou.map((item) => (
              <NeedsYouRow key={`${item.kind}:${item.spec ?? ''}:${item.id ?? ''}`} item={item} cc={cc} onRun={onRun} onDecide={onDecide} onConfirmTier={onConfirmTier} onActed={onActed} />
            )), strip, 'needs-you-more', 'mt-2 space-y-2')}
          </ul>
        )}
      </section>

      <section aria-labelledby="team-waiting-title" className="space-y-2">
        <Eyebrow as="h3" id="team-waiting-title">Team is waiting on</Eyebrow>
        {!sprint ? <p className="text-xs text-ink-3">{NO_DATA}</p> : verdictGroups.length === 0 ? <p className="text-xs text-ink-3">{sprint.hasData ? 'no verdict pending' : NO_DATA}</p> : (
          <>
            {/* Said ONCE for the group, not under every row (v13: two identical captions). */}
            <p className="text-[11px] text-ink-3" data-testid="team-waiting-caption">{TEAM_WAITING_CAPTION}</p>
            <ul className="space-y-1" title="sprint.py status --json · verdicts_pending" data-testid="team-waiting">
              {foldRows(verdictGroups.map((g) => (
                <li key={g.spec} className="flex min-h-[44px] flex-wrap items-center gap-x-2 rounded-[10px] border-l-2 border-line-2 bg-surface-1 px-3 py-2 text-xs">
                  <span className="font-mono text-ident tabular-nums text-ink-1">{g.spec}</span>
                  {g.lanes.map((v) => (
                    <span key={v.lane} className="font-mono text-ident text-ink-2">{v.lane} · {businessDays(v.sinceBusinessDays)}</span>
                  ))}
                </li>
              )), strip, 'team-waiting-more', 'mt-1 space-y-1', 0)}
            </ul>
          </>
        )}
      </section>

      <section aria-labelledby="since-title" className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Eyebrow as="h3" id="since-title">Since yesterday</Eyebrow>
          <Segmented<'1' | '3'> label="Window" tone="neutral" size="sm" options={WINDOWS} value={String(cc.since) as '1' | '3'} onChange={(v) => onSince(Number(v) as SinceWindow)} />
        </div>
        <Stream rows={cc.sinceYesterday} hasLog={hasLog} logError={cc.log.ok ? null : cc.log.error} strip={strip} />
        <p className="text-[11px] text-ink-3" title={LOOP_EVENTS_TOTALS_ONLY}>the window is a filter, not a number · {LOOP_EVENTS_TOTALS_ONLY}</p>
      </section>

      <section aria-labelledby="claude-title" className="space-y-2">
        <Eyebrow as="h3" id="claude-title">Claude's work</Eyebrow>
        <p className="text-xs text-ink-2" data-testid="claude-line" title="Shepherd's own record, not a plugin field">
          {claudeLine ?? 'nothing drafted this session'} <span className="text-ink-3">· Shepherd's record</span>
        </p>
        <Button size="sm" variant="secondary" icon={Bell} disabled disabledReason={STANDUP_NOTES}>Standup notes</Button>
      </section>
    </section>
  )
}

function NeedsYouRow({ item, cc, onRun, onDecide, onConfirmTier, onActed }: { item: NeedsYouItem; cc: CommandCenter } & Pick<TodayColumnProps, 'onRun' | 'onDecide' | 'onConfirmTier' | 'onActed'>) {
  const [busy, setBusy] = useState(false)
  const [resolution, setResolution] = useState('')
  const [deciding, setDeciding] = useState(false)
  const [outcome, setOutcome] = useState<string | null>(null)
  const Icon = ICON[item.kind]
  const late = item.overdue === true
  const run = async (fn: () => Promise<{ ok: boolean; text: string }>) => {
    if (busy) return
    setBusy(true)
    try {
      const res = await fn()
      setOutcome(res.text)
      if (res.ok) onActed()
    } finally { setBusy(false) }
  }
  const action = (() => {
    switch (item.kind) {
      case 'ack':
        return <Button size="sm" data-write="" loading={busy} onClick={() => run(async () => { const r = await onRun({ verb: 'ack', spec: item.spec! }); return { ok: r.ok, text: `${exitHeading(r.exitCode)}${r.stderr ? ` · ${r.stderr}` : ''}` } })}>Ack</Button>
      case 'review': {
        const url = prUrlFor(cc, item.spec)
        return url ? <a href={url} target="_blank" rel="noreferrer" className="text-xs font-medium text-accent-text hover:underline">Open PR</a> : <span className="text-xs text-ink-3">no PR url in the read</span>
      }
      case 'decide':
        return <Button size="sm" data-write="" onClick={() => setDeciding((d) => !d)}>Decide</Button>
      case 'confirm-tier':
        return <Button size="sm" data-write="" loading={busy} onClick={() => run(async () => { const r = await onConfirmTier(item.spec!); return { ok: r.ok, text: r.ok ? (r.message ?? 'confirmed') : (r.refusal?.message ?? 'Not done') } })}>Confirm</Button>
    }
  })()
  return (
    <li
      data-needs-you-item=""
      data-kind={item.kind}
      data-late={late ? '' : undefined}
      className={cn('min-h-[44px] rounded-[10px] border-l-2 px-3 py-2 text-xs', late ? 'border-today-late-line bg-today-late-bg text-today-late-ink' : 'border-today-act-line bg-today-act-bg text-today-act-ink')}
      title={item.source}
    >
      {/* Two rows: the id line with the chip and the ONE action right-aligned, then the item's
          own words — the row's content — clamped to two lines, never cut to a dozen characters. */}
      <div className="flex items-center gap-2">
        <Icon size={16} strokeWidth={1.75} aria-hidden="true" className="shrink-0" />
        <span className="font-mono text-ident tabular-nums">{item.spec ?? item.id}</span>
        {late && <Chip tone="error" size="xs">overdue</Chip>}
        <span className="ml-auto shrink-0">{action}</span>
      </div>
      <p className="mt-1 line-clamp-2 text-[13px] leading-[18px]" data-needs-you-text="">{item.text}</p>
      {deciding && item.kind === 'decide' && (
        <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (resolution.trim()) run(async () => { const r = await onDecide(item.id!, resolution.trim()); return { ok: r.ok, text: r.ok ? `decided · ${r.decided} by ${r.by}` : r.stderr } }) }}>
          <Input value={resolution} onChange={(e) => setResolution(e.target.value)} required placeholder="the resolution, in the log's own words" aria-label={`Resolution for ${item.id}`} />
          <Button size="sm" variant="primary" type="submit" data-write="" loading={busy}>Record</Button>
        </form>
      )}
      {outcome && <p className="mt-1 font-medium" data-testid="needs-you-outcome">{outcome}</p>}
    </li>
  )
}

/** The stream, each row tagged by origin; a row that arrives after the first paint rises alone. */
function Stream({ rows, hasLog, logError, strip }: { rows: StreamRow[]; hasLog: boolean; logError: string | null; strip: boolean }) {
  const seen = useRef<Set<string> | null>(null)
  const list = useRef<HTMLUListElement>(null)
  useLayoutEffect(() => {
    const el = list.current
    if (!el) return
    if (seen.current === null) { seen.current = new Set(rows.map((r) => r.key)); return }
    const fresh = rows.filter((r) => !seen.current!.has(r.key))
    for (const r of fresh) seen.current.add(r.key)
    if (fresh.length === 0) return
    const on = motionEnabled()
    const g = engineFor(on)
    for (const r of fresh) {
      const node = el.querySelector(`[data-stream-key="${CSS.escape(r.key)}"]`)
      if (!node) continue
      const from = on && !motionReduced() ? TODAY_ROW_RISE.from : { opacity: 0 }
      g.fromTo(node, from, { ...TODAY_ROW_RISE.to, duration: on && motionReduced() ? 0.12 : (TODAY_ROW_RISE.to.duration as number) })
    }
  }, [rows])
  if (!hasLog) return <p className="text-xs text-ink-3" data-testid="stream-unavailable">{STREAM_ARRIVES}</p>
  if (logError) return <p className="text-xs text-ink-3" data-testid="stream-unavailable">{logError}</p>
  if (rows.length === 0) return <p className="text-xs text-ink-3">nothing in the window</p>
  return (
    <ul ref={list} className="space-y-1" data-testid="stream">
      {foldRows(rows.map((r) => {
        const sentence = streamSentence(r)
        return (
          // Owner's v12 item 5: the row's sentence WHOLE, on its own line, two lines allowed —
          // never "handoff ha…". The id line carries the origin tag, the spec, the event and the
          // stamp; the sentence is the line's OTHER fields (`streamSentence`), the by-line `by`.
          <li key={r.key} data-stream-key={r.key} data-origin={r.origin} className="min-h-[44px] rounded-[10px] border-l-2 border-line-2 bg-surface-1 px-3 py-2 text-xs text-ink-2">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <Chip tone="neutral" size="xs" title="which read this row came from">{r.origin}</Chip>
              <span className="font-mono text-ident tabular-nums text-ink-1">{r.spec ?? r.id ?? ''}</span>
              <span className="font-medium text-ink-1">{r.event}</span>
              <span className="ml-auto font-mono text-ident text-ink-3">{stampText(r.at)}</span>
            </div>
            {sentence && <p className="mt-0.5 line-clamp-2 text-[13px] leading-[18px] text-ink-2" data-stream-text="" title={sentence}>{sentence}</p>}
            {r.by && <p className="text-ink-3" data-stream-by="">by {r.by}</p>}
          </li>
        )
      }), strip, 'stream-more', 'mt-1 space-y-1', 0)}
    </ul>
  )
}
