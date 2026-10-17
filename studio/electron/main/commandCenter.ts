// The command center's one read model (togo-command-center.md §2.3): a parallel fan-out over the
// plugin's read verbs, each answer wrapped in a `SourcedBlock` carrying the literal spawn it came
// from. Blocks are independent — one failing leaves the others `ok` — and `data: null` is "no
// data", never a zero. Two lists are DERIVED here and only here, by exact handle match
// (`shared/identity.samePerson`): `needsYou` and `sinceYesterday`. Neither carries a per-person
// total; `verdicts_pending` has a lane, not a person, and never appears in `needsYou`.
//
// Cache: one per project, keyed by block. Local blocks live until a write IPC, a completed pull
// or "Refresh this screen" invalidates them; the host block (`spec_status --all`, a code-host
// round trip) keeps a 60 s TTL and its own `fetchedAt`. No fs.watch, no background polling.

import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { runPluginScript } from './project'
import { rawStdout } from './commandRunner'
import { getBoardBlock } from './board'
import { getSprintList, getSprintLog, getSprintStatus, run, sourceArgs, type Read } from './sprint'
import { resolveActor } from './actor'
import { parseDocument, readDecisions, readFindings, readRoster, readScorecard } from './commandCenterReaders'
import { samePerson } from '../../shared/identity'
import { ADO_SYNC_COUNT_KEYS, ADO_SYNC_VIEW_KEYS, type AdoDebtRow, type AdoLastPlan, type AdoSyncCounts, type AdoSyncView } from '../../shared/adoTypes'
import { CAPABILITIES, NO_ACTOR, newerPlugin } from '../../shared/reasons'
import type {
  ActorInfo, Board, CommandCenter, DecisionsView, NeedsYouItem, SinceWindow, SourcedBlock, SprintLogView, SprintView,
  StreamRow,
} from '../../shared/types'

export const HOST_TTL_MS = 60_000
export const SOURCES = {
  sprint: 'sprint.py status --json', sprints: 'sprint.py list --json',
  board: 'spec_status.py --all --json + track_specs.py --json', decisions: 'track_decisions.py --json',
  findings: 'record_findings.py report --json', scorecard: 'scorecard.py report --json',
  roster: 'project_settings.py --json', log: (since: string) => `sprint.py log --since ${since} --json`,
  capabilities: 'generate_status.py --json',
  ado: 'ado_sync.py status --json',
} as const

type BoardBlockData = Board & { warnings: string[] }
interface ProjectCache {
  local: Map<string, SourcedBlock<unknown>>
  host: { block: SourcedBlock<BoardBlockData>; unconfirmedTierSpecs: string[]; at: number } | null
  /** One fan-out per (project, window) at a time: a prefetch on open and the renderer's first
   * read share the same spawns rather than doubling them. Keyed by `since`. */
  inflight: Map<string, Promise<CommandCenter>>
  /** The scripts dir of the last read, so a write can warm the cache without being handed one. */
  scriptsDir: string | null
  /** The cache's epoch: bumped by every invalidation. A block fetched under an older epoch is
   * handed to the caller that asked for it but never STORED — it describes the state before the
   * write that invalidated it (v13: a slow `status` started before a verdict landed after the
   * warm read's and overwrote the fresh block, so the next cache hit snapped the card back). */
  epoch: number
}
const caches = new Map<string, ProjectCache>()
const cacheFor = (p: string): ProjectCache =>
  caches.get(p) ?? caches.set(p, { local: new Map(), host: null, inflight: new Map(), scriptsDir: null, epoch: 0 }).get(p)!

/** Local blocks go on any write, any completed pull and any project switch; `'all'` (Refresh
 * this screen) drops the host block too. No project path clears every project. A read that is
 * still in flight is dropped as well: it was started against the state before the write, and a
 * caller arriving after the invalidation must never be handed it as fresh — nor may its blocks
 * land in the cache when its spawns settle later (`epoch`). */
export function invalidateCommandCenter(projectPath?: string, scope: 'local' | 'all' = 'local'): void {
  const targets = projectPath === undefined ? [...caches.values()] : [cacheFor(projectPath)]
  for (const c of targets) { c.local.clear(); c.inflight.clear(); c.epoch += 1; if (scope === 'all') c.host = null }
}

/** Fire-and-forget: start the fan-out the moment a project opens so the sprint home's first read
 * is a cache hit (or joins the in-flight one). Errors are swallowed — the renderer's own read
 * reports them with the block's `error`. Returns the promise for a caller that wants to await it. */
export function prefetchCommandCenter(projectPath: string, scriptsDir: string, since: SinceWindow = 1): Promise<CommandCenter | null> {
  return getCommandCenter(projectPath, scriptsDir, since).catch(() => null)
}

/** After a write: re-run the fan-out the renderer is about to ask for, so "exit 0 → refreshed
 * read" is one spawn set, not two. A no-op for a project never read (no scripts dir known) — the
 * renderer's read then does the work itself. Never shows anything: the renderer still waits for
 * both the exit code and the refreshed read before a card moves (§2.4). */
export function warmCommandCenter(projectPath: string, since: SinceWindow = 1): Promise<CommandCenter | null> | null {
  const dir = caches.get(projectPath)?.scriptsDir
  return dir ? prefetchCommandCenter(projectPath, dir, since) : null
}

/** The document's stamp is its STALEST block, never the clock at the time of the call — a cache
 * hit must not read "as of now". Null when no block carries a stamp. */
export function oldestFetchedAt(blocks: readonly Pick<SourcedBlock<unknown>, 'fetchedAt'>[]): string | null {
  let oldest: string | null = null
  for (const b of blocks) if (b.fetchedAt && (oldest === null || b.fetchedAt < oldest)) oldest = b.fetchedAt
  return oldest
}

/** The spec ids the last board read listed — what `sprintWrites` checks a request against
 * without a spawn. Undefined when no board has been read yet (the plugin then refuses an unknown
 * spec itself, exit 1). */
export function cachedBoardSpecIds(projectPath: string): string[] | undefined {
  return caches.get(projectPath)?.host?.block.data?.rows.map((r) => r.spec)
}

const sourced = <T>(source: string, read: Read<T>): SourcedBlock<T> => ({
  source, fetchedAt: new Date().toISOString(), ok: read.ok, data: read.ok ? read.data : null, error: read.ok ? null : read.error,
})

async function local<T>(projectPath: string, key: string, source: string, fetch: () => Promise<Read<T>>): Promise<SourcedBlock<T>> {
  const cache = cacheFor(projectPath)
  const hit = cache.local.get(key)
  if (hit) return hit as SourcedBlock<T>
  const epoch = cache.epoch
  const block = sourced(source, await fetch().catch((e: unknown) => ({ ok: false as const, error: String((e as Error)?.message ?? e) })))
  // Stored only while the epoch it was fetched under is still current; a write in between makes
  // this block pre-write truth — returned to its caller, never cached.
  if (cache.epoch === epoch) cache.local.set(key, block)
  return block
}

/** One document from a read verb, or the plugin's message. The reader decides what counts. */
async function readOne<T>(scriptsDir: string, script: string, args: string[], read: (raw: unknown) => T | null): Promise<Read<T>> {
  const ran = await run(scriptsDir, script, args)
  const data = ran.raw ? read(ran.raw) : null
  return data !== null ? { ok: true, data } : { ok: false, error: ran.stderr.trim() || ran.stdout.trim() || `${script} gave no readable answer` }
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const isText = (v: unknown): v is string => typeof v === 'string'
const isCount = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v) && v >= 0

/** The `ado_sync.py status --json` document as `AdoSyncView`, or null when it is not that document: every key
 * the plugin documents (`adoTypes.ADO_SYNC_VIEW_KEYS`, and the counts' own) must be there with its type. A count
 * the plugin printed as `null` stays `null` — never read as 0 — and a document that is not the status document is
 * "no data", never a zeroed shape. Keys the plugin adds later are ignored, not carried. */
export function readAdoStatus(raw: unknown): AdoSyncView | null {
  if (!isObject(raw) || !ADO_SYNC_VIEW_KEYS.every((k) => k in raw)) return null
  const rawCounts = raw.counts
  if (!isObject(rawCounts) || !ADO_SYNC_COUNT_KEYS.every((k) => k in rawCounts)) return null
  const counts = {} as AdoSyncCounts
  for (const key of ADO_SYNC_COUNT_KEYS) {
    const v = rawCounts[key]
    if (v !== null && !isCount(v)) return null
    counts[key] = v
  }
  let byClass: Record<string, number> | null = null
  if (raw.by_class !== null) {
    if (!isObject(raw.by_class) || !Object.values(raw.by_class).every(isCount)) return null
    byClass = { ...(raw.by_class as Record<string, number>) }
  }
  let debt: AdoDebtRow[] | null = null
  if (raw.debt !== null) {
    if (!Array.isArray(raw.debt)) return null
    debt = []
    for (const row of raw.debt) {
      if (!isObject(row) || !isText(row.ref) || !(row.field === null || isText(row.field)) || !isText(row.class) || !isText(row.seen) || !isText(row.due)) return null
      debt.push({ ref: row.ref, field: row.field, class: row.class, seen: row.seen, due: row.due })
    }
  }
  let lastPlan: AdoLastPlan | null = null
  if (raw.last_plan !== null) {
    const p = raw.last_plan
    if (!isObject(p) || !isText(p.plan) || !(p.ts === null || isText(p.ts)) || !isCount(p.rows)) return null
    lastPlan = { plan: p.plan, ts: p.ts, rows: p.rows }
  }
  if (!(raw.as_of === null || isText(raw.as_of)) || !isText(raw.hook_line) || !isText(raw.ledger)) return null
  if (!Array.isArray(raw.notes) || !raw.notes.every(isText) || typeof raw.schema !== 'number' || !Number.isFinite(raw.schema)) return null
  return {
    as_of: raw.as_of, by_class: byClass, counts, debt, hook_line: raw.hook_line, last_plan: lastPlan, ledger: raw.ledger,
    notes: [...raw.notes], schema: raw.schema,
  }
}

/** `generate_status.py --json` capabilities — the plugin's own declaration (§2.6). A project
 * with no state file has none Studio can read, so every gated control stays disabled honestly. */
export async function getCapabilities(projectPath: string, scriptsDir: string): Promise<string[]> {
  const state = join(projectPath, '.sdlc', 'state.yaml')
  if (!existsSync(state)) return []
  const block = await local(projectPath, 'capabilities', SOURCES.capabilities, async () => {
    const entry = await runPluginScript(scriptsDir, 'generate_status.py', ['--state', state, '--json'])
    const doc = parseDocument(rawStdout(entry))
    const caps = doc && Array.isArray(doc.capabilities) ? doc.capabilities.filter((c): c is string => typeof c === 'string') : null
    return caps ? { ok: true, data: caps } : { ok: false, error: entry.stderr.trim() || 'generate_status.py gave no capabilities' }
  })
  return block.data ?? []
}

async function hostBlock(projectPath: string, scriptsDir: string, now: number) {
  const cache = cacheFor(projectPath)
  if (cache.host && now - cache.host.at < HOST_TTL_MS) return cache.host
  const epoch = cache.epoch
  const r = await getBoardBlock(projectPath, scriptsDir)
  const block = sourced<BoardBlockData>(SOURCES.board, r.ok ? { ok: true, data: { ...r.board, warnings: r.warnings } } : { ok: false, error: r.error ?? 'unreadable' })
  const entry = { block, unconfirmedTierSpecs: r.unconfirmedTierSpecs, at: now }
  // The same epoch rule as `local`: a `status --all` begun before a write never lands after it.
  if (cache.epoch === epoch) cache.host = entry
  return entry
}

/** The `--since` date for the window the person picked: N business days back from today, a
 * FILTER the plugin applies — never a number Studio reports. */
export function sinceDateFor(window: SinceWindow, now: Date = new Date()): string {
  const d = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()))
  for (let left = window; left > 0;) { d.setUTCDate(d.getUTCDate() - 1); if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) left-- }
  return d.toISOString().slice(0, 10)
}

// --- the two derived lists (exact handle match only) --------------------------------------------

export interface NeedsYouInput {
  actor: ActorInfo | null
  sprint: SourcedBlock<SprintView>
  board: SourcedBlock<BoardBlockData>
  decisions: SourcedBlock<DecisionsView>
  capabilities: readonly string[]
  /** Spec ids whose `spec_status --all` row carries `risk_confirmed_by` present AND empty. */
  unconfirmedTierSpecs?: readonly string[]
}

export function needsYou(input: NeedsYouInput): { items: NeedsYouItem[]; reason: string | null } {
  const me = input.actor?.name
  if (!me) return { items: [], reason: NO_ACTOR }
  const items: NeedsYouItem[] = []
  for (const d of input.decisions.data?.openDecisions ?? []) {
    if (samePerson(d.owner, me)) items.push({ kind: 'decide', id: d.id, action: 'decide', source: input.decisions.source, text: d.decision, overdue: d.overdue })
  }
  items.sort((a, b) => Number(b.overdue === true) - Number(a.overdue === true))
  for (const h of input.sprint.data?.handoffsOpen ?? []) {
    if (samePerson(h.to, me)) items.push({ kind: 'ack', spec: h.spec, action: 'ack', source: input.sprint.source, text: h.to })
  }
  for (const row of input.board.data?.rows ?? []) {
    if (row.pullRequest && samePerson(row.pullRequest.waitingOnHandle, me)) {
      items.push({ kind: 'review', spec: row.spec, action: 'open PR', source: input.board.source, text: row.pullRequest.waitingOn })
    }
  }
  if (input.capabilities.includes(CAPABILITIES.confirmTier)) {
    for (const row of input.board.data?.rows ?? []) {
      if (row.risk && samePerson(row.owner, me) && input.unconfirmedTierSpecs?.includes(row.spec)) {
        items.push({ kind: 'confirm-tier', spec: row.spec, action: 'confirm', source: input.board.source, text: row.risk })
      }
    }
  }
  return { items, reason: null }
}

export interface SinceYesterdayInput { log: SourcedBlock<SprintLogView>; board: SourcedBlock<BoardBlockData>; since: string }

/** The ledger line's keys the stream row already carries as its own fields — the id line shows
 * origin · spec · event · stamp and the by-line `by`; `text` must not say them again (v13: every
 * log row read "0003 handoff / handoff · 0003 · by Pod Lead / by Pod Lead"). */
export const STREAM_ROW_FIELDS = new Set(['ts', 'timestamp', 'event', 'spec', 'sprint', 'by'])

/** A log row's sentence: the line's OTHER fields, each as `key value` in the plugin's own words
 * (`lane eng · verdict accepted`, `to @sam-k · note …`, `to_sprint S08 · reason …`), in the order
 * the line carries them; '' when the line has none (an `ack`, a `ready`). Nothing is reshaped:
 * a value is shown as written, a nested one as its JSON. */
export function logEventText(e: Record<string, unknown>): string {
  const parts: string[] = []
  for (const [key, value] of Object.entries(e)) {
    if (STREAM_ROW_FIELDS.has(key) || value === null || value === undefined || value === '') continue
    parts.push(`${key} ${typeof value === 'string' ? value : JSON.stringify(value)}`)
  }
  return parts.join(' · ')
}

/** Ledger events verbatim plus PRs merged in the window, newest first by the timestamp the source
 * gave; undated rows last — the row's `at` is null and the renderer's stamp reads "undated", so
 * `text` carries no second label. Decisions closed in the window are NOT here: the plugin's
 * `track_decisions.py --json` lists open rows only, and Studio does not read the log itself. */
export function sinceYesterday(input: SinceYesterdayInput): StreamRow[] {
  const rows: StreamRow[] = []
  const s = (v: unknown) => (typeof v === 'string' ? v : undefined)
  for (const e of input.log.data?.events ?? []) {
    // The ledger's own key is `ts` (sprint_model.make_event); `timestamp` is read for a line that carries it instead.
    const at = s(e.ts) ?? s(e.timestamp) ?? null, event = s(e.event) ?? 'event', spec = s(e.spec), by = s(e.by)
    rows.push({ origin: 'log', key: `${at ?? ''}+${event}+${spec ?? ''}`, at, event, spec, sprint: s(e.sprint), by, text: logEventText(e), raw: e })
  }
  for (const row of input.board.data?.rows ?? []) {
    const pr = row.pullRequest
    if (pr?.mergedAt && pr.mergedAt.slice(0, 10) >= input.since) {
      rows.push({ origin: 'board', key: `${pr.mergedAt}+merged+${row.spec}`, at: pr.mergedAt, event: 'merged', spec: row.spec, sprint: row.sprint || undefined, text: `PR #${pr.number} merged`, raw: { ...pr } })
    }
  }
  const dated = rows.filter((r) => r.at !== null).sort((a, b) => (a.at! < b.at! ? 1 : a.at! > b.at! ? -1 : 0))
  const undated = rows.filter((r) => r.at === null)
  return [...dated, ...undated]
}

// --- the document ---------------------------------------------------------------------------------

export interface GetCommandCenterOptions { refresh?: boolean; now?: Date; actor?: ActorInfo | null }

/** One in-flight fan-out per (project, window): a second caller joins the first rather than
 * spawning again; a `refresh` drops cache AND in-flight and starts over. The entry is removed when
 * the read settles, so a later call after an invalidation is a fresh read. */
export function getCommandCenter(
  projectPath: string, scriptsDir: string, since: SinceWindow = 1, opts: GetCommandCenterOptions = {},
): Promise<CommandCenter> {
  if (opts.refresh) invalidateCommandCenter(projectPath, 'all')
  const cache = cacheFor(projectPath)
  cache.scriptsDir = scriptsDir
  const key = String(since)
  const joined = cache.inflight.get(key)
  if (joined) return joined
  const read = readCommandCenter(projectPath, scriptsDir, since, opts).finally(() => {
    if (cache.inflight.get(key) === read) cache.inflight.delete(key)
  })
  cache.inflight.set(key, read)
  return read
}

async function readCommandCenter(
  projectPath: string, scriptsDir: string, since: SinceWindow, opts: GetCommandCenterOptions,
): Promise<CommandCenter> {
  const now = opts.now ?? new Date()
  const sinceDate = sinceDateFor(since, now)
  const capabilities = await getCapabilities(projectPath, scriptsDir)
  const gated = <T>(cap: string, source: string, fetch: () => Promise<Read<T>>) =>
    capabilities.includes(cap) ? fetch() : Promise.resolve<Read<T>>({ ok: false, error: newerPlugin(cap) })
  const [actor, sprint, sprints, host, decisions, findings, scorecard, roster, log, ado] = await Promise.all([
    opts.actor !== undefined ? opts.actor : resolveActor(projectPath, scriptsDir),
    local(projectPath, 'sprint', SOURCES.sprint, async () => {
      const r = await getSprintStatus(projectPath, scriptsDir)
      return r.ok ? { ok: true, data: r } : { ok: false, error: r.error }
    }),
    local(projectPath, 'sprints', SOURCES.sprints, () => gated(CAPABILITIES.sprintList, SOURCES.sprints, () => getSprintList(projectPath, scriptsDir))),
    hostBlock(projectPath, scriptsDir, now.getTime()),
    local(projectPath, 'decisions', SOURCES.decisions, () => readOne(scriptsDir, 'track_decisions.py', [...sourceArgs(projectPath), '--json'], readDecisions)),
    local(projectPath, 'findings', SOURCES.findings, () => readOne(scriptsDir, 'record_findings.py', ['report', ...sourceArgs(projectPath), '--json'], readFindings)),
    local(projectPath, 'scorecard', SOURCES.scorecard, () => readOne(scriptsDir, 'scorecard.py', ['report', ...sourceArgs(projectPath), '--json'], readScorecard)),
    local(projectPath, 'roster', SOURCES.roster, () => readOne(scriptsDir, 'project_settings.py', ['--repo', projectPath, '--json'], readRoster)),
    local(projectPath, `log:${sinceDate}`, SOURCES.log(sinceDate), () => gated(CAPABILITIES.sprintLog, SOURCES.log(sinceDate), () => getSprintLog(projectPath, scriptsDir, sinceDate))),
    // The Azure Boards mirror's read side: the plugin's own `status --json`, never `az`, never `.sdlc/ado/**` read here.
    local(projectPath, 'ado', SOURCES.ado, () => gated(CAPABILITIES.adoStatus, SOURCES.ado, () => readOne(scriptsDir, 'ado_sync.py', ['status', ...sourceArgs(projectPath), '--json'], readAdoStatus))),
  ])
  const board = host.block
  const needs = needsYou({ actor, sprint, board, decisions, capabilities, unconfirmedTierSpecs: host.unconfirmedTierSpecs })
  // The stamp is the stalest block's, so a cache hit never reads "as of now" (freshness is a fact).
  const fetchedAt = oldestFetchedAt([sprint, sprints, board, decisions, findings, scorecard, roster, log, ado]) ?? now.toISOString()
  return {
    projectPath, fetchedAt, actor, capabilities, sprint, sprints, board, decisions, findings, scorecard, roster, log, ado,
    needsYou: needs.items, needsYouReason: needs.reason, sinceYesterday: sinceYesterday({ log, board, since: sinceDate }), since,
  }
}
