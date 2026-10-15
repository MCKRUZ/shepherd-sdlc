// The spec card (togo-command-center.md §3.3; a lazy chunk, opened in place over the lanes). One
// read — `getSpecCard` — gives every block sourced: readiness (+ ladder), status, findings, the
// channel lint and the hand-off dry run; `openDocument` gives scope, `harness_context` and the
// `**Why this tier:**` notes. Zones: header · Intent · DoR · Checking ladder · Findings · Hand off.
// The title block Flips through `sharedElement` (#8) from the row that opened it and `Esc` / Back
// return focus to the opener via `stashBack` — M4's precedent, instant under test / reduced motion.
// The pinned wording lives in `TierChip` (raise free / lower refused in the plugin's words) and
// the foot's reason is `handoff.py`'s own sentence. One object, ONE screen: the Board's row and a
// lane card both open this card (plan §3.3); the old spec view's facts rail and dependency
// neighbourhood ride in the right column under a disclosure, so nothing the Board showed is lost.
//
// The Azure Boards zone (B5-P4, B6-P3): the chip stays a status in the facts row (no write control there). Beneath that
// row a Boards row holds `Pull now` (this spec's fields, `PullNow`), `Plan changes` (`PlanChanges`) and — once a pull
// has read drift for this spec — `Settle drift`; the Discussion block (comment composer inside, `Pull discussion`) sits
// below the facts rail. `Plan changes` runs ONE closed `plan` request for this spec on the person's click and never
// otherwise (K28; no effect here plans anything on open), says what the plugin found in one line, and hands the plan it
// printed to the chip, whose **Review plan** opens the apply dialog on exactly those rows; an apply that landed drops
// that plan. The card itself holds no request and no bridge call but its own two reads: every Boards spawn lives in
// `components/ado/`. A host that is not Azure DevOps draws none of it (the chip says why); steering mode draws the chip
// and the read-only discussion rows and nothing that writes.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { GitPullRequest } from 'lucide-react'
import type { ActorInfo, AdoVerbResult, BoardRow, DocumentSection, RosterPerson, SpecCard as SpecCardRead, SprintVerb } from '../../../shared/types'
import { hostFeatureReason, WORDING } from '../../../shared/codeHostModel'
import { samePerson } from '../../../shared/identity'
import { CAPABILITIES, NO_ACTOR, NO_DATA, NO_PR_YET, VAGUE_LINE_REWRITE } from '../../../shared/reasons'
import { slateToBoardRow } from '../../../shared/sprintModel'
import { BackLink, Button, Card, Chip, Disclosure, Eyebrow, Icon, Notice } from '../../ui'
import { backlogStore } from '../../stores/backlogStore'
import { MarkdownView } from '../MarkdownView'
import { SpecFactsRail } from '../SpecFactsRail'
import { SpecNeighbourhood } from '../SpecNeighbourhood'
import { useEnter } from '../../motion/useEnter'
import { useStudioGSAP } from '../../motion/useStudioGSAP'
import { motion } from '../../motion/motion'
import { contextFrom, sharedElement } from '../../motion/choreo'
import { stashBack } from '../../motion/choreo/sharedElement'
import { PersonRing } from '../brand/figures'
import { ringFor, riskTone } from '../planning/planningModel'
import { AdoChip } from '../ado/AdoChip'
import type { AdoPlanDoc } from '../ado/AdoApplyDialog'
import { PlanChanges } from '../ado/PlanChanges'
import { AdoReconcileDialog, readDriftItems, type AdoDriftItem } from '../ado/AdoReconcileDialog'
import { DiscussionBlock } from '../ado/DiscussionBlock'
import { PullNow, type PullKind } from '../ado/PullNow'
import { useConnection } from '../../stores/connectionStore'
import { ChannelDimensions } from './ChannelDimensions'
import { FindingsLedger } from './FindingsLedger'
import { HandoffFoot } from './HandoffFoot'
import { Ladder } from './Ladder'
import { TierChip } from './TierChip'
import { harnessContext, scopeSections, whyTierNotes } from './specDocument'

export const BACK_LABEL = '← Back to the board'

export const FACTS_DISCLOSURE = 'Facts and neighbourhood'

/** The plugin capability (`scripts/capabilities.py`) whose verb `Plan changes` runs: a plugin without it disables the
 * button with `newerPlugin(cap)`. `PlanChanges` reads the same id from the closed table (`ADO_VERB_CAPABILITY.plan`). */
export const PLAN_CAPABILITY = 'ado-plan'

export interface SpecCardProps {
  projectPath: string
  row: BoardRow
  roster?: readonly RosterPerson[] | null
  capabilities?: string[]
  actor?: ActorInfo | null
  onBack: () => void
  onHandOff: () => void
  /** Opens another spec from this one (a dependency, a neighbour). Absent → the bodies say why not. */
  onOpenSpec?: (row: BoardRow) => void
  /** The host's VerbDialog for the facts rail's reserved sprint verbs; absent → the slots say why. */
  onVerb?: (verb: SprintVerb, row: BoardRow) => void
  /** Steering mode, for the Boards parts: the chip and the discussion rows, with nothing that writes or asks the board. */
  steering?: boolean
}

export function SpecCard({ projectPath, row, roster, capabilities, actor, onBack, onHandOff, onOpenSpec, onVerb, steering = false }: SpecCardProps) {
  const root = useRef<HTMLDivElement>(null)
  const title = useRef<HTMLDivElement>(null)
  useEnter(root, 'rise')
  useStudioGSAP(() => {
    const scope = root.current
    if (!scope) return
    sharedElement.play(contextFrom(scope, { enabled: motion.enabled(), reduced: motion.reduced() }, motion), { id: `spec:${row.spec}`, target: title.current })
  }, { scope: root, dependencies: [row.spec] })

  const back = useCallback(() => {
    stashBack(row.spec, motion.enabled() ? title.current : null)
    onBack()
  }, [row.spec, onBack])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      if ((e.target as HTMLElement | null)?.closest('[role="dialog"]')) return
      e.preventDefault(); back()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [back])

  const [card, setCard] = useState<SpecCardRead | null>(null)
  const [sections, setSections] = useState<DocumentSection[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reloads, setReloads] = useState(0)
  const reload = useCallback(() => setReloads((n) => n + 1), [])

  useEffect(() => {
    let live = true
    ;(async () => {
      try {
        const [c, doc] = await Promise.all([
          window.studio.getSpecCard(projectPath, row.path, row.developer || undefined),
          window.studio.openDocument(projectPath, row.path).catch(() => null),
        ])
        if (!live) return
        setCard(c); setSections(doc?.ok ? doc.sections : []); setError(null)
      } catch (err) {
        if (live) setError(err instanceof Error ? err.message : 'The spec card could not be read.')
      }
    })()
    return () => { live = false }
  }, [projectPath, row.path, row.developer, reloads])

  // ── Azure Boards ─────────────────────────────────────────────────────────────────────────────────
  const connection = useConnection()
  const boardsOff = connection ? hostFeatureReason(connection, 'workItems') === WORDING.boardsNotConfigured : false
  const itemRef = `sdlc:spec:${row.spec}`
  // The plan `Plan changes` drew up, kept with the spec and project it was drawn up for: it is only ever shown for them,
  // so another spec starts from nothing without an effect having to remember to clear it.
  const planKey = `${projectPath}|${row.spec}`
  const [drawn, setDrawn] = useState<{ key: string; doc: AdoPlanDoc } | null>(null)
  const planDoc = drawn !== null && drawn.key === planKey ? drawn.doc : null
  const [drift, setDrift] = useState<AdoDriftItem | null>(null)
  const [settling, setSettling] = useState(false)
  const [chipReads, setChipReads] = useState(0)
  const settledHere = useRef(false)
  // Another spec, another project: nothing is drawn from the last one.
  useEffect(() => { setDrift(null); setSettling(false) }, [row.spec, projectPath])

  // A pull of this spec's fields changed what the ledger says: the chip reads it again, and the drift it read is what
  // `Settle drift` opens.
  const pulledHere = (what: PullKind, result: AdoVerbResult) => {
    if (what !== 'fields') return
    setChipReads((n) => n + 1)
    setDrift(readDriftItems(result.json).find((i) => i.ref === itemRef) ?? null)
  }
  const closeSettle = () => {
    setSettling(false)
    if (settledHere.current) { settledHere.current = false; setDrift(null) }   // what settled is not offered again
  }

  const has = (cap: string) => capabilities === undefined || capabilities.includes(cap)
  const writeReason = actor === null ? NO_ACTOR : undefined
  const people = roster ?? []
  const me = actor?.name ?? null
  const scope = useMemo(() => scopeSections(sections ?? []), [sections])
  const harness = useMemo(() => harnessContext(sections ?? []), [sections])
  const why = useMemo(() => whyTierNotes(sections ?? []), [sections])
  const readiness = card?.readiness.data ?? null
  const ladder = card?.ladder.data ?? readiness?.ladder ?? null
  const pr = card?.status.data?.pull_request ?? null
  const blocking = useMemo(() => readiness?.blocking.map((f) => f.message) ?? [], [readiness])

  // Another spec, from the rows the Board or the sprint already fetched — never a second spawn.
  const rowFor = useCallback((id: string): BoardRow | null => {
    const fromBoard = backlogStore.rows.find((r) => r.spec === id)
    if (fromBoard) return fromBoard
    const fromSlate = backlogStore.slate.find((r) => r.id === id)
    return fromSlate ? slateToBoardRow(fromSlate) : null
  }, [])
  const openDependency = onOpenSpec ? (id: string) => { const target = rowFor(id); if (target) onOpenSpec(target) } : null
  const dependencyReason = (id: string) => (rowFor(id) ? null : 'Open the Board once to open this spec from here.')

  // The Board's own words for the three roles (SpecStatusView's facts rail), so a spec reads the
  // same from either screen.
  const person = (handle: string, label: string) => {
    if (!handle) return <span key={label} className="text-xs text-ink-3">{label} nobody</span>
    const ring = ringFor(people, handle)
    return <span key={label} className="inline-flex items-center gap-1 text-xs text-ink-2">{label} <PersonRing initials={ring.initials} name={ring.name} you={samePerson(handle, me)} /></span>
  }

  return (
    <div ref={root} data-testid="spec-card" data-spec={row.spec} className="relative mx-auto max-w-[1200px] rounded-[20px] bg-surface-1 p-6 shadow-3">
      <div ref={title} data-flip-id={`spec:${row.spec}`} className="min-w-0">
        <BackLink label={BACK_LABEL} onClick={back} className="mb-1" />
        <Eyebrow className="mb-1" data-testid="spec-eyebrow">Build · Spec <span className="font-mono tabular-nums">{row.spec}</span></Eyebrow>
        <h2 className="text-xl text-ink-1" data-page-heading tabIndex={-1}>
          <span className="font-mono text-base text-accent-text">{row.spec}</span> — {row.title || row.name}
        </h2>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs" data-testid="spec-facts">
        <Chip tone={riskTone(row.risk)} casing="identifier" dot>{row.risk || 'no tier'}</Chip>
        <Chip tone="neutral" casing="state" dot>{row.status || 'no status'}</Chip>
        {row.channel ? <Chip tone="mono" casing="identifier">{row.channel}</Chip> : null}
        {row.team ? <Chip tone="neutral">{row.team}</Chip> : null}
        {person(row.owner, 'Owns it')}{person(row.developer, 'Builds it')}{person(row.checker, 'Checks it')}
        <span className="font-mono text-ident text-ink-3">{row.path}</span>
        {pr ? (
          <a href={pr.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-mono text-ident text-accent-text hover:underline"><Icon icon={GitPullRequest} size={16} />#{pr.number}</a>
        ) : <span className="text-ink-3" data-testid="no-pr">{NO_PR_YET}</span>}
        <AdoChip
          key={`ado-${chipReads}`} projectPath={projectPath} specId={row.spec} capabilities={capabilities} actor={actor} steering={steering}
          plan={planDoc} onApplied={() => { setDrawn(null); setChipReads((n) => n + 1) }}
        />
        {row.engReview && <Chip tone="neutral" casing="state">eng {row.engReview}</Chip>}
        {row.dataReview && <Chip tone="neutral" casing="state">data {row.dataReview}</Chip>}
      </div>

      {/* The Boards row sits OUTSIDE the facts row: the chip's pin is "no write control at rest in spec-facts". */}
      {!steering && !boardsOff && (
        <div data-testid="spec-boards" className="mt-2 flex flex-wrap items-start gap-2 text-xs">
          <PullNow projectPath={projectPath} capabilities={capabilities ?? null} itemRef={itemRef} scope="fields" onPulled={pulledHere} />
          <PlanChanges key={planKey} projectPath={projectPath} capabilities={capabilities} kind="spec" id={row.spec} actor={actor} onPlanned={(doc) => setDrawn({ key: planKey, doc })} />
          {drift ? <Button size="sm" variant="secondary" onClick={() => setSettling(true)}>Settle drift</Button> : null}
        </div>
      )}
      {/* Mounted only while it is open: every opening starts from the drift the last pull read, with nothing chosen. */}
      {drift && settling && !steering && !boardsOff ? (
        <AdoReconcileDialog open projectPath={projectPath} item={drift} capabilities={capabilities} actor={actor} onClose={closeSettle} onSettled={() => { settledHere.current = true; setChipReads((n) => n + 1) }} />
      ) : null}

      {error && <Notice tone="error" className="mt-4">{error}</Notice>}
      {!card && !error && <p role="status" aria-busy="true" className="mt-4 text-sm text-ink-3">Reading the spec…</p>}

      {/* The body's `pb-16` = the sticky foot's height (64 px), so its last line clears the foot (v12 #3). */}
      {card && (
        <div className="mt-6 grid gap-6 pb-16 lg:grid-cols-[minmax(320px,1fr)_280px_minmax(300px,1fr)]" data-testid="spec-body">
          <section aria-label="Intent · Definition of Ready" className="space-y-4" data-testid="spec-intent">
            <TierChip projectPath={projectPath} specPath={row.path} risk={readiness?.risk ?? row.risk} whyNotes={why} canConfirm={has(CAPABILITIES.confirmTier)} writeReason={writeReason} onChanged={reload} />
            <Card>
              <Eyebrow as="h3">Definition of Ready</Eyebrow>
              {!readiness ? <p className="mt-1 text-xs text-ink-3">{card.readiness.error ?? NO_DATA}</p> : (
                <div className="mt-2 space-y-2 text-sm">
                  <Group title="Still needed" tone={readiness.blocking.length > 0 ? 'warn' : 'neutral'} items={blocking} empty="nothing blocking" />
                  <Group title="Worth a look" tone="neutral" items={readiness.advisory.map((f) => f.message)} empty="no advisories" extra={readiness.advisory.length > 0 ? <Button size="sm" disabled disabledReason={VAGUE_LINE_REWRITE}>Claude proposes a rewrite</Button> : null} />
                  <Group title="Passing" tone="neutral" items={readiness.passed.map((f) => f.message)} empty="none yet" collapsed />
                </div>
              )}
              <p className="mt-2 font-mono text-[10px] text-ink-3">{card.readiness.source}</p>
            </Card>
            <Card>
              <Eyebrow as="h3">Scope</Eyebrow>
              <Doc label="In" text={scope.scopeIn} />
              <Doc label="Out" text={scope.scopeOut} />
              <Doc label="harness_context" text={harness} />
            </Card>
            <ChannelDimensions channel={card.channel} />
          </section>
          <Ladder ladder={ladder} ladderError={card.ladder.error} status={card.status.data} roster={roster} hasLadderCapability={has(CAPABILITIES.readinessAll)} />
          <div className="space-y-4">
            <FindingsLedger findings={card.findings.data} error={card.findings.error} hasFindingsCapability={has(CAPABILITIES.findingsJson)} />
            {/* The old spec view's two zones, kept whole and folded: the frontmatter facts with the
                reserved sprint verbs, and where this spec sits among its dependencies. */}
            <Disclosure data-testid="spec-facts-disclosure" summary={<Eyebrow as="span">{FACTS_DISCLOSURE}</Eyebrow>} className="rounded-[10px] border border-line-1 bg-surface-1 p-3" summaryProps={{ className: 'text-ink-2' }}>
              <div className="mt-3 space-y-4 [&>section]:static">
                <SpecFactsRail
                  row={row}
                  pullRequest={pr ? { number: pr.number, url: pr.url } : null}
                  onOpenDependency={openDependency}
                  dependencyReason={dependencyReason}
                  capabilities={capabilities}
                  actor={actor}
                  onVerb={onVerb}
                />
                <SpecNeighbourhood row={row} onOpenSpec={onOpenSpec ?? null} rowFor={rowFor} />
              </div>
            </Disclosure>
            {!boardsOff && (
              <DiscussionBlock projectPath={projectPath} itemRef={itemRef} capabilities={capabilities ?? null} steering={steering} pull="discussion" />
            )}
          </div>
        </div>
      )}
      {card && (
        <HandoffFoot
          check={card.handoffCheck}
          hasCheckCapability={has(CAPABILITIES.handoffCheck)}
          blocking={blocking}
          readinessSource={card.readiness.source}
          status={row.status}
          onHandOff={onHandOff}
        />
      )}
    </div>
  )
}

/** One DoR group: the eyebrow voice for the title (`--text-eyebrow` + `ink-3`, never a coloured
 * cut of its own), the count as a chip that carries the only tone — warn while MUST lines block,
 * neutral otherwise: a passing DoR line is the checker's verdict, not a host success, so never
 * green (visual §8 #4). A named region around the disclosure, so "Still needed" is reachable as a
 * landmark (the e2e reads it by role) while the group still folds. */
function Group({ title, tone, items, empty, extra, collapsed = false }: { title: string; tone: 'warn' | 'neutral'; items: string[]; empty: string; extra?: React.ReactNode; collapsed?: boolean }) {
  return (
    <section aria-label={title} data-group={title}>
      <details open={!collapsed || undefined}>
        <summary className="flex cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden [&::marker]:hidden">
          <Eyebrow as="span">{title}</Eyebrow>
          <Chip tone={tone} size="xs" data-group-count="">{items.length}</Chip>
        </summary>
        {items.length === 0 ? <p className="mt-1 text-xs text-ink-3">{empty}</p> : <ul className="mt-1 space-y-1">{items.map((m, i) => <li key={i} className="text-ink-1">• {m}</li>)}</ul>}
        {extra ? <div className="mt-2">{extra}</div> : null}
      </details>
    </section>
  )
}

/** `null`: the document has no such section; `''`: the section is there with nothing in it (the
 * template's comment stripped) — two different facts, each said in `ink-3` words, never a blank. */
export const SECTION_EMPTY = `${NO_DATA} — the section is empty`
export const SECTION_ABSENT = 'not in the document'

function Doc({ label, text }: { label: string; text: string | null }) {
  return (
    <div className="mt-2" data-doc={label}>
      <p className="text-xs font-medium text-ink-2">{label}</p>
      {text ? (
        // The document's own markdown, TYPESET (v14 at 1680: a `<pre>` drew "### In scope" and a
        // lone "-" as literal text) — through the same `MarkdownView` the Documents tab reads
        // with, which drops raw HTML, so a template comment can never surface here either.
        <div className="mt-0.5" data-doc-body=""><MarkdownView source={text} /></div>
      ) : <p className="mt-0.5 text-xs text-ink-3" data-doc-empty={text === null ? 'absent' : 'empty'}>{text === null ? SECTION_ABSENT : SECTION_EMPTY}</p>}
    </div>
  )
}

export default SpecCard
