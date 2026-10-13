// The sprint home — the command center (togo-command-center.md §3.1; Area `sprint`, the default
// in Build). ONE read, `getCommandCenter`, every block sourced; the header, four lanes, the baton,
// the Today column, In the room, Refining and How it is going draw it as it came. Writes go
// through the closed argv table (`runSprintVerb`, `decideDecision`, `confirmTier`) with the actor
// main resolved; after any exit 0 the screen RE-READS and nothing moves until the refreshed read
// is in hand — then the verdict seal (#31) or the baton pass (#30) plays, and the lane Flip
// (`boardRegroup`) carries a card to its new lane. The slate constellation keeps its Graph surface
// behind `SceneShell`'s toggle with the old `SprintBoard` slate table as its Table twin. Motion
// reads `motion.familiarity(projectPath)`: the tier changes how a state is reached, never what.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Flip } from 'gsap/Flip'
import type { BoardRow, CommandCenter, ReadinessAll, SinceWindow, SprintVerbRequest, VerdictLane, VerdictValue } from '../../shared/types'
import { CAPABILITIES, NO_DATA } from '../../shared/reasons'
import { slateToBoardRow } from '../../shared/sprintModel'
import { PanelError } from './activityPanelBits'
import { cn, SkeletonRows } from '../ui'
import { motion } from '../motion/motion'
import { useEnter } from '../motion/useEnter'
import { focusPlanFor, useFocusReturn } from '../motion/focusReturn'
import { batonPass, boardRegroup, contextFrom, verdictSeal } from '../motion/choreo'
import { getScene } from '../scenes/core/sceneRegistry'
import { SceneSlot } from '../scenes/core/SceneSlot'
import { backlogStore } from '../stores/backlogStore'
import { useConnection } from '../stores/connectionStore'
import { hostReasons } from '../hostReasons'
import { constellationFromSprint } from './sprintSceneData'
import { SprintBoard } from './SprintBoard'
import { SprintHeader } from './SprintHeader'
import { InTheRoom } from './InTheRoom'
import { Refining } from './Refining'
import { LaneBoard } from './lanes/LaneBoard'
import { useCockpitChrome, useTodayBranch } from './lanes/useCockpitChrome'
import { VerdictDialog } from './lanes/VerdictDialog'
import type { LaneFilterMode, LaneRow } from './lanes/laneModel'
import { TodayColumn } from './today/TodayColumn'
import { GoingPanel } from './today/GoingPanel'

export interface SprintHomeProps {
  projectPath: string
  onOpenSpec: (row: BoardRow) => void
  /** `h` on a card / the omnibar's "hand NNNN to NAME": the host's hand-off dialog. */
  onHandOff?: (row: BoardRow) => void
  /** The "New sprint" primary with no sprint: the host's VerbDialog on the `new` verb. */
  onNewSprint: () => void
  /** Shepherd's own record of Claude's work this session (drafts, proposals), or null. */
  claudeLine?: string | null
  /** The spec the host just handed off with exit 0 — the baton plays once the refreshed read holds it. */
  handedOff?: string | null
  /** Bumped by the host after a write elsewhere landed exit 0 (the omnibar, "Refresh this screen"): re-read. */
  refreshKey?: number
  /** Coming back from the spec card: the control that opened it takes focus again once the read
   * lands (a lane card, or a Refining row's "refine in place →"). Accessibility, not decoration. */
  focusBack?: { spec: string; where: 'lane' | 'refining'; seq?: number } | null
}

/** The opener's selector, pure for the test. */
export function focusBackSelector(back: NonNullable<SprintHomeProps['focusBack']>): string {
  const id = CSS.escape(back.spec)
  return back.where === 'lane' ? `[data-lane-card][data-spec="${id}"]` : `[data-testid="refining-row"][data-spec="${id}"] [data-refine]`
}

/** The cockpit ROW (v13 fixer round, owner's v12 item 1): from 1240 px of home width the home
 * grid's one row is `100dvh − --cockpit-chrome` (floor 280), so the four wells and the Today rail
 * — both grid items that stretch — end on ONE line, 24 px above the fold, and the band below
 * starts under it. Lanes and the rail each scroll inside. `--cockpit-chrome` is the grid's own
 * top plus `<main>`'s bottom padding (`cockpitLayout.ts`; measured live by `useCockpitChrome`). */
export const COCKPIT_ROW_CLASS = '@min-[1240px]:grid-rows-[max(280px,calc(100dvh-var(--cockpit-chrome,396px)))]'
/** The strip (under 1240 px): four groups in a row, sized to WHOLE rows — no height cap and no
 * scroller (v14 at 1280×800: a 120 px `max-h` sliced rows mid-sentence and its fade read as a
 * cut). Needs-you shows `TodayColumn`'s `STRIP_ROWS` whole and folds the rest behind "N more";
 * the other groups keep their header and fold every row (`strip` prop, from `useTodayBranch`);
 * `useCockpitChrome` measures the strip's real height into the wells' cap. */
export const TODAY_STRIP_CLASS = '@min-[700px]:grid-cols-2 @min-[1000px]:grid-cols-4'
/** The rail (from 1240 px): one column, the grid row's height, scrolling inside. */
export const TODAY_RAIL_CLASS = '@min-[1240px]:order-1 @min-[1240px]:grid-cols-1 @min-[1240px]:content-start @min-[1240px]:min-h-0 @min-[1240px]:overflow-y-auto @min-[1240px]:overscroll-contain @min-[1240px]:pr-1 @min-[1240px]:pb-2'
/** The RAIL scrolls inside a capped box, so its last 16 px fade: a clipped row reads as "more
 * below", never as a slice. Rail only — the strip has nothing to clip (v14). Plain CSS in a
 * class — nothing inline, nothing the CSP cares about. */
export const TODAY_SCROLL_MASK_CLASS = '@min-[1240px]:[mask-image:linear-gradient(to_bottom,#000_calc(100%-16px),transparent)]'

/** The board row the spec view takes: the board's row by exact id, else the slate row's shape. */
export function boardRowFor(row: LaneRow): BoardRow {
  return row.board ?? slateToBoardRow(row.slate)
}

export function SprintHome({ projectPath, onOpenSpec, onHandOff, onNewSprint, claudeLine = null, handedOff = null, refreshKey = 0, focusBack = null }: SprintHomeProps) {
  const [cc, setCc] = useState<CommandCenter | null>(null)
  const [readiness, setReadiness] = useState<ReadinessAll | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [since, setSince] = useState<SinceWindow>(1)
  const [filter, setFilter] = useState<LaneFilterMode>('all')
  const [verdictRow, setVerdictRow] = useState<LaneRow | null>(null)
  const [reads, setReads] = useState(0)
  const pendingSeal = useRef<{ spec: string; lane: VerdictLane; verdict: VerdictValue } | null>(null)
  const pendingBaton = useRef<string | null>(null)
  const flipState = useRef<Flip.FlipState | null>(null)
  const root = useRef<HTMLDivElement>(null)
  const lanesRef = useRef<HTMLDivElement>(null)
  const gridRef = useRef<HTMLDivElement>(null)
  useEnter(root, 'rise', { key: projectPath })
  const tier = motion.familiarity(projectPath)
  const connection = useConnection()
  const hasSprint = Boolean(cc?.sprint.data?.sprint)
  useCockpitChrome(root, gridRef, hasSprint)
  // Which branch Today is drawn in — the strip folds its groups to whole rows (v14).
  const todayIs = useTodayBranch(root, cc !== null)
  // After a verb's exit 0 the control that changed takes focus — once the refreshed read (a new
  // `cc`) has landed, never before (plan §10; `motion/focusReturn`). Keyed on the document
  // itself: `fetchedAt` is the STALEST block's stamp and can survive a write (the host block's TTL).
  const focus = useFocusReturn(root, cc)

  // Re-read: capture the cards' positions first so the lane Flip has a "before".
  const reload = useCallback(() => {
    const el = lanesRef.current
    if (el && motion.enabled()) flipState.current = Flip.getState(el.querySelectorAll('[data-flip-id^="spec:"]'))
    setReads((n) => n + 1)
  }, [])

  useEffect(() => {
    let cancelled = false
    setError(null)
    window.studio.getCommandCenter(projectPath, since).then(
      async (doc) => {
        if (cancelled) return
        setCc(doc)
        if (doc.sprint.data) backlogStore.setSlate(projectPath, doc.sprint.data.slate)
        if (doc.board.data) backlogStore.setRows(projectPath, doc.board.data.rows)
        if (doc.capabilities.includes(CAPABILITIES.readinessAll)) {
          try { const all = await window.studio.getReadinessAll(projectPath); if (!cancelled) setReadiness(all) } catch { if (!cancelled) setReadiness(null) }
        }
      },
      (err: unknown) => { if (!cancelled) setError(err instanceof Error ? err.message : 'The command center could not be read.') },
    )
    return () => { cancelled = true }
  }, [projectPath, since, reads, refreshKey])

  // Back from the spec card: focus returns to the opener once the rows exist — once per return.
  const focusedBack = useRef<string | null>(null)
  useEffect(() => {
    if (!cc || !focusBack) return
    const key = `${focusBack.where}:${focusBack.spec}:${focusBack.seq ?? 0}`
    if (focusedBack.current === key) return
    const el = root.current?.querySelector<HTMLElement>(focusBackSelector(focusBack))
    if (!el) return
    focusedBack.current = key
    el.focus({ preventScroll: false })
  }, [cc, focusBack])

  // After a refreshed read: the lane Flip, then the seal or the baton — in that order, once.
  useEffect(() => {
    if (!cc) return
    const lanes = lanesRef.current
    const ctx = (scope: Element) => contextFrom(scope, { enabled: motion.enabled(), reduced: motion.reduced() }, motion)
    if (lanes && flipState.current) {
      boardRegroup.play(ctx(lanes), { state: flipState.current, container: lanes })
      flipState.current = null
    }
    const seal = pendingSeal.current
    if (seal && lanes) {
      pendingSeal.current = null
      const card = lanes.querySelector(`[data-lane-card][data-spec="${CSS.escape(seal.spec)}"]`)
      if (card) {
        const chip = card.querySelector(`[data-review-chip="${seal.lane}"]`)
        verdictSeal.play(ctx(card), { card, seam: card.querySelector('[data-seam]'), chipIn: chip, verdict: seal.verdict, tier })
      }
    }
    const spec = pendingBaton.current ?? handedOff
    if (spec && lanes && cc.sprint.data?.handoffsOpen.some((h) => h.spec === spec)) {
      pendingBaton.current = null
      const slot = lanes.querySelector(`[data-baton-slot][data-spec="${CSS.escape(spec)}"]`)
      const card = lanes.querySelector(`[data-lane-card][data-spec="${CSS.escape(spec)}"]`)
      if (slot) batonPass.play(ctx(lanes), { baton: slot.querySelector('[data-baton]'), fromSlot: card, toSlot: slot, card, tier })
    }
  }, [cc, handedOff, tier])

  const runVerb = useCallback(async (request: SprintVerbRequest) => {
    const result = await window.studio.runSprintVerb(projectPath, request)
    if (result.ok) { focus.schedule(focusPlanFor(request)); reload() }
    return result
  }, [projectPath, reload, focus])
  const decide = useCallback(async (id: string, resolution: string) => {
    const result = await window.studio.decideDecision(projectPath, id, resolution)
    if (result.ok) reload()
    return result
  }, [projectPath, reload])
  const confirmTier = useCallback(async (specPath: string) => {
    const result = await window.studio.confirmTier(projectPath, specPath)
    if (result.ok) reload()
    return result
  }, [projectPath, reload])
  const specPathFor = useCallback((id: string) => cc?.board.data?.rows.find((r) => r.spec === id)?.path ?? id, [cc])

  const view = cc?.sprint.data ?? null
  const scene = useMemo(() => (view && view.sprint ? constellationFromSprint(view) : null), [view])
  const sceneRegistered = getScene('constellation-sprint') !== undefined
  const openLane = useCallback((row: LaneRow) => onOpenSpec(boardRowFor(row)), [onOpenSpec])
  const openBoardRow = useCallback((id: string) => {
    const row = cc?.board.data?.rows.find((r) => r.spec === id) ?? (view ? view.slate.find((r) => r.id === id) : undefined)
    if (row) onOpenSpec('spec' in row ? row : slateToBoardRow(row))
  }, [cc, view, onOpenSpec])

  if (error) return <div ref={root} data-testid="sprint-home" className="p-6"><PanelError message={error} /></div>
  if (!cc) {
    return (
      <div ref={root} data-testid="sprint-home" aria-busy="true" className="space-y-4">
        <p role="status" className="text-sm text-ink-3">Reading the command center…</p>
        <SkeletonRows rows={4} />
      </div>
    )
  }

  const hostReason = cc.board.data?.codeHostAvailable === false ? (hostReasons(connection).board ?? cc.board.data.error ?? 'the code host could not be read') : cc.board.ok ? null : (cc.board.error ?? NO_DATA)
  const boardRows = cc.board.data?.rows ?? null
  const people = cc.roster.data?.people ?? null
  const twin = <SprintBoard projectPath={projectPath} view={view} twin onOpenSpec={onOpenSpec} onRefresh={reload} />

  return (
    // The cockpit (owner's v12 item 1; `lanes/cockpitLayout.ts` holds the arithmetic): header,
    // In the room as one row, then the home grid. `@container`: measured on THIS screen, not the
    // window — the chat is a 40 px rail here by default (chatStore), so a 1440 window leaves 1352
    // and a 1280 window 1192. From 1240 px (4 × 220 + 3 × 12 + 24 + 300) Today is a 300 px RIGHT
    // RAIL beside four full lanes and the grid's one row IS the cockpit: `100dvh − --cockpit-chrome`
    // tall (`COCKPIT_ROW_CLASS`), so wells and rail fill it and end together 24 px above the fold
    // (v13 fixer round: the wells had stopped at their content height, leaving a void and the
    // band's eyebrows sliced on the fold). Under 1240 Today is a capped strip ABOVE the lanes, the
    // lanes take the whole width (four across from 916 px of their own, two by two below) and cap
    // their height at `100dvh − --cockpit-chrome`, scrolling inside. Refining, How it is going and
    // the slate sit below the fold, 48 px on, where `<main>` scrolls to them.
    <div
      ref={root}
      data-testid="sprint-home"
      data-tier={tier}
      data-fetched-at={cc.fetchedAt}
      className="@container flex flex-col gap-6"
    >
      {view ? <SprintHeader view={view} actor={cc.actor} capabilities={cc.capabilities} onNewSprint={onNewSprint} />
        : <PanelError message={cc.sprint.error ?? 'The sprint could not be read.'} />}
      <InTheRoom people={people} view={view} board={boardRows} me={cc.actor?.name ?? null} />
      {/* `--cockpit-chrome` lives HERE, on a child of the `@container` root, not on the root: a
          container query measures the nearest ANCESTOR container, so the same variant on the root
          itself never matched (v13 probe). The classes carry the first-paint defaults
          (`COCKPIT_CHROME_PX` for the rail, `COCKPIT_CHROME_WITH_STRIP_PX` under it, where the
          strip, its gap and the filter row join the chrome); `useCockpitChrome` writes the measured
          value inline once the grid is laid out. Under the rail threshold the grid's gap tightens
          to 16 (`STRIP_GAP_PX`). The row height applies only while there is a sprint — the
          no-sprint list is a short well, not a cockpit. */}
      <div
        ref={gridRef}
        className={cn(
          'grid grid-cols-1 gap-6 [--cockpit-chrome:396px] @max-[1239px]:gap-4 @max-[1239px]:[--cockpit-chrome:572px] @min-[1240px]:grid-cols-[minmax(0,1fr)_300px]',
          hasSprint && COCKPIT_ROW_CLASS,
        )}
        data-home-grid=""
      >
        {/* Today first in DOM — needs-you is the first thing to act on — and `order-1` from 1240 px
            so auto-placement seats the lanes in the 1fr column and Today in the rail. As a strip
            (under 1240) its four groups sit in a row, each cut to WHOLE rows — `STRIP_ROWS` shown,
            the rest behind "N more" — never to a height (v14: the 120 px cap sliced text). As the
            RAIL it is a grid item of the cockpit row — `min-h-0` so it may be shorter than its
            content — and scrolls inside, so the cockpit (four lanes AND the rail) fits the first
            screen; v13's probe measured the uncapped rail at 1467 px. */}
        <TodayColumn cc={cc} onRun={runVerb} onDecide={decide} onConfirmTier={(id) => confirmTier(specPathFor(id))} onSince={setSince} onActed={reload} claudeLine={claudeLine}
          strip={todayIs === 'strip'} className={cn(TODAY_STRIP_CLASS, TODAY_RAIL_CLASS, TODAY_SCROLL_MASK_CLASS)} />
        {view && view.sprint ? (
          // In the rail branch the wrapper is a flex column of the row's height, so the lane board
          // can hand its wells the height left under the filter row (`LaneBoard`: `flex-1 min-h-0`).
          <div ref={lanesRef} className="min-w-0 @min-[1240px]:flex @min-[1240px]:min-h-0 @min-[1240px]:flex-col">
            <LaneBoard
              view={view} board={boardRows} hostReason={hostReason} actor={cc.actor} capabilities={cc.capabilities} roster={people}
              filter={filter} onFilter={setFilter} onOpen={openLane} onHandOff={onHandOff ? (row) => onHandOff(boardRowFor(row)) : undefined}
              onVerdict={setVerdictRow} onRun={runVerb} onAcked={(spec) => { pendingBaton.current = spec }} tier={tier} revealKey={`${projectPath}|${cc.fetchedAt}`}
              className="@min-[1240px]:min-h-0 @min-[1240px]:flex-1"
            />
          </div>
        ) : (
          // No sprint: the lanes are replaced by the Board rows (the backlog as the plugin lists it).
          <div ref={lanesRef} data-testid="no-sprint-rows" className="rounded-[14px] bg-lane p-3 text-xs text-ink-2">
            {boardRows && boardRows.length > 0 ? (
              <ul className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
                {boardRows.map((r) => (
                  <li key={r.spec}><button type="button" className="font-mono text-ident tabular-nums hover:underline" onClick={() => onOpenSpec(r)}>{r.spec}</button> <span className="text-ink-1">{r.name}</span> <span className="text-ink-3">· {r.status}</span></li>
                ))}
              </ul>
            ) : <p className="text-ink-3">{hostReason ?? 'no spec on the board'}</p>}
          </div>
        )}
      </div>
      {/* Below the fold: 48 px on (the column gap plus this margin), Refining for S(n+1) beside
          How it is going, then the slate's Graph surface with its Table twin. */}
      <div className="mt-6 grid grid-cols-1 gap-6 @min-[960px]:grid-cols-2" data-home-below="">
        <Refining rows={boardRows} readiness={readiness} roster={people} actor={cc.actor} capabilities={cc.capabilities} afterSprint={view?.sprint?.id ?? null} onOpen={onOpenSpec} onConfirmTier={(row) => confirmTier(row.path)} />
        <GoingPanel block={cc.scorecard} />
      </div>
      {view && view.sprint && (
        <section aria-label="Slate" className="space-y-3">
          {scene && sceneRegistered
            ? <SceneSlot id="constellation-sprint" data={scene} onActivate={openBoardRow} table={twin} />
            : twin}
        </section>
      )}
      {verdictRow && (
        <VerdictDialog row={verdictRow} actor={cc.actor} capabilities={cc.capabilities} projectPath={projectPath} boardSpecIds={view?.slate.map((r) => r.id)}
          onClose={() => setVerdictRow(null)} onRun={runVerb} onRecorded={(spec, lane, verdict) => { pendingSeal.current = { spec, lane, verdict } }} />
      )}
    </div>
  )
}
