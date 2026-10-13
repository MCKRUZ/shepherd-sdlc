import { useCallback, useEffect, useRef, useState } from 'react'
import { Download } from 'lucide-react'
import type { Scorecard } from '../../shared/types'
import { buildScorecardExport, hasNothingRecorded } from '../../shared/scorecardExport'
import { Button, Card, DefinitionList, EmptyState, Eyebrow, NoData, Notice, PageHeader, Segmented, SkeletonTile, StatTile, toast } from '../ui'
import { useCountUp } from '../motion/useCountUp'
import { useListReveal } from './screenMotion'

type WindowDays = '14' | '30' | '90'
const WINDOWS: { value: WindowDays; label: string }[] = [
  { value: '14', label: '14 days' }, { value: '30', label: '30 days' }, { value: '90', label: '90 days' },
]

const percent = (v: number) => `${Math.round(v * 100)}%`
/** ONE way to write hours on every screen (the home's panel, the close screen, steering, here):
 * one decimal and the unit joined, "5.3h" — never "20 h" here and "20.0h" there. */
export const formatHours = (v: number) => `${(Math.round(v * 10) / 10).toFixed(1)}h`
const hours = formatHours

/** One measure of the standard, as `scorecard.py report --json` reports it. `field` is the plugin's
 * own JSON key — every tile names it, so a number in a steering room is traceable to its source.
 * The table is shared by this screen, the sprint home's "How it is going" panel, the close screen's
 * Outcomes and steering mode (togo-command-center.md §3.1, §3.5): one list, so no screen can show a
 * measure another lacks or invent one the plugin does not report. */
export interface ScorecardMeasure {
  id: string
  label: string
  field: string
  value: number | null
  kind: 'percent' | 'hours' | 'count'
  produces: string
  /** The one measure the standard keeps apart (security-review wait) — its own line, always. */
  emphasis?: boolean
  /** What a RATE is a rate OF, from the plugin's own `totals` / `dora.deploy_count` — printed
   * under the number as "of N merged" so a measured 0 % is distinguishable from no data. Null
   * when the plugin reports no denominator (or a 0 — "of 0" would be a fabricated base). */
  denominator?: { n: number; noun: string; field: string } | null
}

/** "of 4 merged" — the plugin's own count under a rate, or null when it gave none. */
export function denominatorFor(n: number | null | undefined, noun: string, field: string): ScorecardMeasure['denominator'] {
  return typeof n === 'number' && Number.isFinite(n) && n > 0 ? { n, noun, field } : null
}

export function denominatorText(d: ScorecardMeasure['denominator']): string | null {
  return d ? `of ${d.n} ${d.noun}` : null
}

export function scorecardMeasures(card: Scorecard): ScorecardMeasure[] {
  const merged = denominatorFor(card.totals?.merges, 'merged', 'totals.merges')
  const deploys = denominatorFor(card.dora.deploy_count, 'deployments', 'dora.deploy_count')
  return [
    { id: 'accepted', label: 'Accepted as-is', field: 'accepted_as_is_rate', value: card.accepted_as_is_rate, kind: 'percent', produces: 'a merged spec recorded as accepted without rework', denominator: merged },
    { id: 'rework', label: 'Rework or revert', field: 'rework_revert_rate', value: card.rework_revert_rate, kind: 'percent', produces: 'a merged spec that was later reverted or reworked', denominator: merged },
    { id: 'bounce', label: 'Sent back', field: 'bounce_back_rate', value: card.bounce_back_rate, kind: 'percent', produces: 'a spec returned to its developer during checking', denominator: merged },
    { id: 'review-wait', label: 'Review wait (median)', field: 'review_wait_median_hours', value: card.review_wait_median_hours, kind: 'hours', produces: 'a review that has been requested and answered' },
    { id: 'security-wait', label: 'Security review wait (median)', field: 'security_review_wait_median_hours', value: card.security_review_wait_median_hours, kind: 'hours', produces: 'a security review that has been requested and answered', emphasis: true },
    { id: 'dora.deploys', label: 'Deployments', field: 'dora.deploy_count', value: card.dora.deploy_count, kind: 'count', produces: 'a recorded deployment' },
    { id: 'dora.lead', label: 'Lead time (median)', field: 'dora.lead_time_median_hours', value: card.dora.lead_time_median_hours, kind: 'hours', produces: 'a merged change that reached production' },
    { id: 'dora.cfr', label: 'Change failure rate', field: 'dora.change_fail_rate', value: card.dora.change_fail_rate, kind: 'percent', produces: 'a deployment that caused an incident', denominator: deploys },
    { id: 'dora.ttr', label: 'Time to recover (median)', field: 'dora.time_to_recover_median_hours', value: card.dora.time_to_recover_median_hours, kind: 'hours', produces: 'a closed incident' },
  ]
}

/** The DORA four (the "Delivery" group) apart from the outcomes — one filter, so a screen that
 * groups the tiles agrees with this one about which measure is which. */
export const isDora = (m: Pick<ScorecardMeasure, 'id'>) => m.id.startsWith('dora.')

/** The number as READ for display — 72 for "72 %", 5.3 for "5.3 h" — plus its unit. Null stays null. */
/** The words for a count of zero recorded events — the plugin's own `0` (its text prints
 * "Deploys 0"), said as its escaped-bugs line says it, never a bare numeral that reads as a
 * measured zero (visual §8 #6). */
export const NONE_RECORDED = 'none recorded in this window'

export function shownValue(m: Pick<ScorecardMeasure, 'value' | 'kind'>): { shown: number | null; unit: string; words?: string } {
  const unit = m.kind === 'percent' ? '%' : m.kind === 'hours' ? 'h' : ''
  if (m.value === null) return { shown: null, unit }
  if (m.kind === 'count' && m.value === 0) return { shown: null, unit, words: NONE_RECORDED }
  return { shown: m.kind === 'percent' ? Math.round(m.value * 100) : m.kind === 'hours' ? Number(m.value.toFixed(1)) : m.value, unit }
}

/** The five outcome tiles as StatTiles — the sprint home's "How it is going" panel reuses this. */
export function ScorecardMeasures({ card }: { card: Scorecard }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {scorecardMeasures(card).filter((m) => !m.id.startsWith('dora.')).map((m) => <Measure key={m.id} measure={m} />)}
    </div>
  )
}

/** How Build is going (spec 0013). Every number is the plugin's; `null` is "no data" with what
 * would produce some — never a 0, which is a different and false claim. */
export function ScorecardView({ projectPath }: { projectPath: string }) {
  const [windowDays, setWindowDays] = useState<WindowDays>('14')
  const [card, setCard] = useState<Scorecard | null>(null)
  const [loading, setLoading] = useState(true)
  const [unreadable, setUnreadable] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  useListReveal(root, card ? `${projectPath}|${windowDays}` : null)

  const load = useCallback(async () => {
    setLoading(true)
    const result = await window.studio.getScorecard(projectPath, Number(windowDays))
    setCard(result)
    setUnreadable(result === null)
    setLoading(false)
  }, [projectPath, windowDays])

  useEffect(() => { load() }, [load])

  /** Has anything happened at all in this window? Used to say "no data yet" ONCE rather than
   * eleven times, which is the difference between a screen that informs and one that nags. */
  const nothingRecorded = card !== null && hasNothingRecorded(card)

  /** Built from the SAME object this screen rendered, never from a fresh fetch (spec 0013). */
  const exportScorecard = async () => {
    if (!card) return
    const contents = buildScorecardExport(card, {
      projectName: projectPath.split(/[\\/]/).filter(Boolean).pop() ?? 'this project',
      windowDays: Number(windowDays),
      now: new Date(),
    })
    const result = await window.studio.exportDocument(`how-build-is-going-${windowDays}d.md`, contents)
    if (result.ok) toast({ tone: 'ok', title: 'Export written', detail: result.path ?? 'saved' })
  }

  if (loading && !card) {
    return (
      <div aria-busy="true">
        <p role="status" className="text-sm text-ink-3">Reading the scorecard…</p>
        <div className="mt-3 grid grid-cols-2 gap-3"><SkeletonTile /><SkeletonTile /></div>
      </div>
    )
  }

  if (unreadable) {
    return (
      // Deliberately NOT an all-zero scorecard: a claim about the tool, not about the project.
      <Notice tone="warn" title="The scorecard could not be read.">
        This is not the same as "nothing has happened" — no numbers are being shown because
        none could be read, not because they are zero.
      </Notice>
    )
  }
  if (!card) return null
  const dora = scorecardMeasures(card).filter((m) => m.id.startsWith('dora.'))

  return (
    <div ref={root} className="space-y-4">
      <PageHeader
        eyebrow="Build · How it is going"
        title="How Build is going"
        lede="Every number here is computed by the plugin from recorded events. Shepherd does no arithmetic of its own."
        actions={(
          <>
            <Button size="sm" icon={Download} onClick={exportScorecard}>Export for a meeting</Button>
            <Segmented<WindowDays> label="Window" tone="inverse" size="sm" options={WINDOWS} value={windowDays} onChange={setWindowDays} />
          </>
        )}
      />

      {nothingRecorded && (
        <EmptyState
          title={`No data in the last ${windowDays} days.`}
          body="These measures come from merged specs, reverts, deployments and incidents. They start filling in as work goes through the loop — this is an empty record, not a score of zero."
        />
      )}

      <ScorecardMeasures card={card} />

      {/* The comparison itself is the plugin's (team_alarms), never computed here from the medians. */}
      {card.team_alarms && Object.keys(card.team_alarms).length > 0 && (
        <Card>
          <Eyebrow as="h3" className="mb-2">Review-wait alarms by team</Eyebrow>
          <div className="space-y-1 text-sm tabular-nums">
            {Object.entries(card.team_alarms).sort(([a], [b]) => a.localeCompare(b)).map(([team, a]) => (
              <div key={team} className="flex items-center gap-2" data-reveal="">
                <span className="w-24 shrink-0 font-medium text-ink-1">{team}</span>
                <span className={a.review_over_alarm ? 'font-semibold text-status-warn-ink' : 'text-ink-3'}>
                  review vs {a.review_alarm_hours}h{a.review_alarm_hours_default && ' (default)'}
                  {a.review_over_alarm === true && ' — OVER ALARM'}
                  {a.review_over_alarm === null && ' — no data'}
                </span>
                <span className={a.security_over_alarm ? 'font-semibold text-status-warn-ink' : 'text-ink-3'}>
                  security vs {a.security_alarm_hours}h{a.security_alarm_hours_default && ' (default)'}
                  {a.security_over_alarm === true && ' — OVER ALARM'}
                  {a.security_over_alarm === null && ' — no data'}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card>
        <Eyebrow as="h3" className="mb-2">Delivery</Eyebrow>
        <DefinitionList
          columns={2}
          items={dora.map((m) => ({ term: m.label, detail: <Counted id={m.id} value={m.value} format={m.kind === 'hours' ? hours : m.kind === 'percent' ? percent : String} produces={m.produces} /> }))}
        />
      </Card>

      <Card>
        <Eyebrow as="h3" className="mb-2">Bugs that got through</Eyebrow>
        {card.escaped_bugs.length === 0 ? (
          <p className="text-sm text-ink-3">None recorded in this window.</p>
        ) : (
          <ul className="space-y-2">
            {card.escaped_bugs.map((bug, i) => (
              <li key={i} className="text-sm" data-reveal="">
                <span className="text-ink-1">{String(bug.summary ?? 'a bug')}</span>
                <span className="mt-0.5 block text-xs text-ink-3">Should have been caught by: {String(bug.which_check ?? 'not recorded')}</span>
                {bug.proposed_fix ? <span className="block text-xs text-ink-3">Proposed: {String(bug.proposed_fix)}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Spec 0013 asks for this to be STATED, not merely absent (board.spec pins the sentence). */}
      <Card tone="inset">
        <Eyebrow as="h3" className="mb-2">Not measured here, on purpose</Eyebrow>
        <p className="text-sm text-ink-1">Velocity, story points, pull-request counts and lines of code.</p>
        <p className="mt-1 text-xs text-ink-3">
          They measure activity rather than outcome, and every one of them improves when work is
          split more finely — so a team can raise them without delivering anything more. The
          plugin refuses to record them at all, which is why they cannot appear here even by
          accident.
        </p>
      </Card>
    </div>
  )
}

/** A formatted number that tweens only between two REAL values (§4.2 #11); `null` is NoData. */
function Counted({ id, value, format, produces }: { id: string; value: number | null; format: (v: number) => string; produces: string }) {
  const counted = useCountUp(`scorecard.${id}`, value, { snap: 0.1, format })
  if (value === null) return <NoData what={`Produced by ${produces}.`} />
  return <span ref={counted.ref} className="text-sm font-semibold tabular-nums">{counted.text}</span>
}

/** One measure as a StatTile; the counter drives the tile's own `[data-value]` text node. */
function Measure({ measure }: { measure: ScorecardMeasure }) {
  const { shown, unit } = shownValue(measure)
  const counted = useCountUp(`scorecard.${measure.id}`, shown, { snap: measure.kind === 'percent' ? 1 : 0.1 })
  return (
    <StatTile
      id={`scorecard-${measure.id}`}
      ref={(el) => { counted.ref.current = el?.querySelector<HTMLElement>('[data-value]') ?? null }}
      label={measure.label}
      value={shown}
      unit={unit}
      hint={`Produced by ${measure.produces}.`}
      noDataWhat="Nothing of that kind has been recorded in this window."
      // The one measure the standard keeps apart gets its own row by POSITION, not a tint.
      className={measure.emphasis ? 'sm:col-span-2 lg:col-span-3' : undefined}
      data-reveal=""
    />
  )
}
