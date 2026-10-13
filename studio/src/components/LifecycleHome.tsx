// The lifecycle home (togo-command-center.md §3.4): the default outside the Build loop. A thin
// composition — today's `StageHome` (the Spine band with its Table twin, Workflow / Documents /
// Guide, `1`/`2`/`3`, every pin inside the body) with a Today column on the right carrying three
// groups: "needs you" (the command center's addressed list), "Claude is working the <stage>"
// (Shepherd's own record of chat activity for this stage — labelled as such, and never present-tense
// once the turn has ended or failed), and "Decisions this week" (`track_decisions.py --json`'s
// open rows with the plugin's clock; `today-late-*` only on its `overdue:true`). Leaning into the
// Build station adds a small "Go to the sprint home →" on the Needs-you row, never a banner.
//
// Honesty: every number is a plugin field or a list length; a block the plugin did not answer
// reads "no data" with the block's own source named beneath it in words a reader can read
// (`ink-3`, the script in `--text-ident` — never a word in `ink-4`); nothing is a per-person total.
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowRight } from 'lucide-react'
import type { CommandCenter, DecisionRow, NeedsYouItem, ProjectStatus } from '../../shared/types'
import { BUILD_STAGE_ID, type NavTarget } from '../../shared/nav'
import { NO_DATA, NOTHING_NEEDS_YOU } from '../../shared/reasons'
import { Button, Eyebrow, cn } from '../ui'
import { useChatTurn } from '../stores/chatTurnStore'
import { CcEmptyFigure } from './brand/figures'
import { StageHome } from './StageHome'

type StageHomeProps = Parameters<typeof StageHome>[0]

export interface LifecycleHomeProps extends StageHomeProps {
  status: ProjectStatus
  /** The one read model (§2.3), or null before it lands / on a plugin without it. */
  commandCenter: CommandCenter | null
  onNavigate: (target: NavTarget) => void
  /** One action per needs-you item, handed up as the item itself; the host maps it to a verb. */
  onNeedsYou?: (item: NeedsYouItem) => void
}

/** Provenance lines, in words: which scripts the block is drawn from and how it was addressed. */
export const NEEDS_YOU_SOURCE = { scripts: 'sprint.py status · spec_status.py --all · track_decisions.py', how: 'matched to your handle' }
export const WORKING_SOURCE = "Shepherd's own record of this session"

/** The Today column's height cap as the right column (≥ 1600 px): the window less the 169 px
 * above it (band 48 + strip 64 + main padding 24 + the strip's own hairline and labels, probe-
 * measured) and main's 24 px bottom padding, so the column ends on screen and scrolls inside. */
export const LIFECYCLE_TODAY_MAX_HEIGHT_CLASS = 'min-[1600px]:max-h-[calc(100dvh-193px)]'

export function LifecycleHome({ commandCenter, onNeedsYou, ...stageHome }: LifecycleHomeProps) {
  const { status, stageId, onNavigate, projectPath } = stageHome
  const resolvedStage = stageId ?? status.stages.find((s) => s.stage_state === 'current')?.id ?? status.current_phase.id
  const stage = status.stages.find((s) => s.id === resolvedStage)
  return (
    // The Today column sits beside the stage home only when the window leaves the stage home its
    // own two-pane width (the Workflow tab's steps + live panel need ≈ 800 px beside the 380 px
    // chat); narrower, it is a band of three groups ABOVE the stage home — never a column the
    // stage home's panels slide under.
    <div data-testid="lifecycle-home" className="grid grid-cols-1 gap-6 min-[1600px]:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0 min-[1600px]:order-none">
        <StageHome {...stageHome} />
      </div>
      {/* A `<section>`, not an `<aside>`: the shell pins exactly two asides (the strip, the chat). */}
      {/* `min-[768px]:grid-cols-3`, not `md:` — v13's 1680×1000 shot showed three cramped sub-columns
          inside the 320 px rail: Tailwind orders a rem breakpoint and a px arbitrary variant by
          source, not by width, so `md:grid-cols-3` beat `min-[1600px]:grid-cols-1`. Two px variants
          sort by value and the wider one wins, as the layout intends.
          As the right column (≥ 1600) it caps at the window's height below its top (169 px of
          band + strip + main padding, measured by the overlap probe at 1680×1000, plus main's 24 px
          bottom padding) and scrolls inside — v13 measured the uncapped column at 1030 px, its
          "Decisions this week" below the fold. */}
      <section aria-label="Today" data-testid="today" className={cn('order-first grid gap-6 min-[768px]:grid-cols-3 min-[1600px]:order-none min-[1600px]:grid-cols-1 min-[1600px]:content-start min-[1600px]:pt-1 min-[1600px]:overflow-y-auto min-[1600px]:overscroll-contain min-[1600px]:pr-1', LIFECYCLE_TODAY_MAX_HEIGHT_CLASS)}>
        <Group
          label="Needs you"
          source={commandCenter ? <>{NEEDS_YOU_SOURCE.scripts} — {NEEDS_YOU_SOURCE.how}</> : null}
          action={resolvedStage === BUILD_STAGE_ID ? (
            <Button size="sm" variant="secondary" iconEnd={ArrowRight} onClick={() => onNavigate({ area: 'sprint' })}>Go to the sprint home →</Button>
          ) : null}
        >
          <NeedsYou cc={commandCenter} onAct={onNeedsYou} />
        </Group>
        <Group label={`Claude is working ${stage ? stage.display.replace(/^Phase [^:]+:\s*/, '') : 'this stage'}`} source={WORKING_SOURCE}>
          <WorkingLine projectPath={projectPath} stageId={resolvedStage} />
        </Group>
        <Group label="Decisions this week" source={commandCenter?.decisions.source ?? null}>
          <Decisions cc={commandCenter} />
        </Group>
      </section>
    </div>
  )
}

function Group({ label, source, action, children }: { label: string; source: ReactNode; action?: ReactNode; children: ReactNode }) {
  return (
    <section aria-label={label} className="space-y-2">
      <div className="flex min-h-7 items-center justify-between gap-3">
        <Eyebrow as="h3">{label}</Eyebrow>
        {action}
      </div>
      {children}
      {source ? <p className="font-mono text-ident text-ink-3" data-provenance="" aria-hidden="true">{source}</p> : null}
    </section>
  )
}

const ITEM = 'min-h-11 rounded-[10px] border-l-2 px-3 py-2 text-sm'

function NeedsYou({ cc, onAct }: { cc: CommandCenter | null; onAct?: (item: NeedsYouItem) => void }) {
  if (cc === null) return <p className="text-sm text-ink-3">{NO_DATA}</p>
  if (cc.needsYouReason) return <p className="text-sm text-ink-3">{cc.needsYouReason}</p>
  if (cc.needsYou.length === 0) {
    return (
      <div className="flex flex-col items-start gap-2 rounded-xl border border-dashed border-line-2 px-5 py-6">
        <CcEmptyFigure figure="nothing-needs-you" />
        <p className="text-sm text-ink-2">{NOTHING_NEEDS_YOU}</p>
      </div>
    )
  }
  return (
    <ul className="m-0 list-none space-y-2 p-0">
      {cc.needsYou.map((item, i) => (
        // Two rows (visual §4 "Today"): the id with the one action right-aligned, then the item's
        // own words clamped to two lines — never a sliver cut at a dozen characters.
        <li key={`${item.kind}-${item.spec ?? item.id ?? i}`} data-needs-you-item="" className={cn(ITEM, 'border-today-act-line bg-today-act-bg text-today-act-ink')}>
          <div className="flex items-center justify-between gap-3">
            <span className="font-mono text-ident tabular-nums">{item.spec ?? item.id ?? ''}</span>
            {onAct ? <Button size="sm" variant="secondary" onClick={() => onAct(item)}>{item.action}</Button> : null}
          </div>
          <p className="mt-1 line-clamp-2 text-[13px] leading-[18px]" data-needs-you-text="">{item.text}</p>
        </li>
      ))}
    </ul>
  )
}

/** Shepherd's own record: the last chat activity reported for this stage in this session, or the
 * plain fact that none was. Never "Thinking…" — nothing is assumed to be running — and never a
 * present-tense label once the ChatPanel has published the turn's end: then the line reads
 * "last activity · HH:MM · turn ended" (or "turn failed"). */
export function workingText(last: { label: string | null; at: Date } | null, turn: { phase: 'running' | 'ended' | 'failed'; at: number } | null): { lead: string; stamp: string } | null {
  if (!last && !turn) return null
  const stamp = (d: Date) => d.toISOString().slice(11, 16)
  if (turn && turn.phase !== 'running' && (!last || turn.at >= last.at.getTime())) {
    return { lead: 'last activity', stamp: `${stamp(last?.at ?? new Date(turn.at))} · turn ${turn.phase}` }
  }
  if (!last) return { lead: 'working', stamp: stamp(new Date(turn!.at)) }
  return { lead: last.label ?? 'working', stamp: stamp(last.at) }
}

function WorkingLine({ projectPath, stageId }: { projectPath: string; stageId: string }) {
  const [last, setLast] = useState<{ label: string | null; at: Date } | null>(null)
  const turn = useChatTurn(projectPath, stageId)
  const seen = useRef(false)
  useEffect(() => {
    seen.current = false
    setLast(null)
    const studio = window.studio as Partial<typeof window.studio>
    if (typeof studio.onChatActivity !== 'function') return
    return studio.onChatActivity((activity) => {
      if (activity.projectPath !== projectPath || activity.stageId !== stageId) return
      seen.current = true
      setLast({ label: activity.label, at: new Date() })
    })
  }, [projectPath, stageId])
  const text = workingText(last, turn)
  if (!text) return <p className="text-sm text-ink-3">nothing recorded this session</p>
  return <p className="text-sm text-ink-2" data-working-line="" data-turn={turn?.phase ?? undefined}>{text.lead} <span className="font-mono text-ident text-ink-3">· {text.stamp}</span></p>
}

function Decisions({ cc }: { cc: CommandCenter | null }) {
  const block = cc?.decisions ?? null
  if (!block || !block.ok || block.data === null) return <p className="text-sm text-ink-3">{NO_DATA}{block?.error ? ` — ${block.error}` : ''}</p>
  if (!block.data.exists) return <p className="text-sm text-ink-3">{NO_DATA} — no decision-log</p>
  if (block.data.openDecisions.length === 0) {
    return (
      <div className="flex flex-col items-start gap-2 rounded-xl border border-dashed border-line-2 px-5 py-6">
        <CcEmptyFigure figure="no-decisions" />
        <p className="text-sm text-ink-2">no open decisions</p>
      </div>
    )
  }
  return (
    <ul className="m-0 list-none space-y-2 p-0">
      {block.data.openDecisions.map((d) => <DecisionItem key={d.id} row={d} />)}
    </ul>
  )
}

function DecisionItem({ row }: { row: DecisionRow }) {
  return (
    <li data-decision={row.id} data-overdue={row.overdue ? '' : undefined} className={cn(ITEM, row.overdue ? 'border-today-late-line bg-today-late-bg text-today-late-ink' : 'border-line-2 text-ink-1')}>
      <p className="font-mono text-ident tabular-nums opacity-80">{row.id} · {row.owner} · due {row.clockDue ?? row.due}{row.overdue ? ' · overdue' : ''}</p>
      <p className="mt-1 line-clamp-2 text-[13px] leading-[18px]" data-decision-text="">{row.decision}</p>
    </li>
  )
}
