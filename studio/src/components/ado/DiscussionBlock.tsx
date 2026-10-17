// The Azure Boards discussion block (build kit §5 B4-P4). It shows what the plugin's `ado_sync.py show --json`
// printed for one item — and nothing it did not: a handle, a relative age, `edited ×N` / `deleted`, the
// comment's text, a `⚑` on a line the plugin flagged as reading like an instruction, and attachments as links.
// It reads the discussion through the closed `show` request and refreshes it with `PullNow` — `Pull now` (the
// item's fields) and `Pull discussion` (its comments), each a `data-write`, never on a timer; the renderer never
// opens the plugin's cache files itself.
//
// Comment text is untrusted board content. It reaches the screen only as React text nodes — never markup —
// and the plugin has already quoted every comment line (`  | `) so none can pass for the tool's own header; this
// parser keeps that boundary: only a quoted line is text, and only an unquoted `Comment …` line is a header.
// Attachments are links the person may open and that Shepherd never fetches: http(s) only, no media element,
// `rel="noreferrer noopener"`; an address that is not http(s) (or none) is a name, not a link.
//
// Steering mode (`steering`) is read-only: the rows show, the pull buttons and the composer do not exist.
import { useCallback, useEffect, useState } from 'react'
import { ADO_VERB_CAPABILITY, validateAdoVerbRequest, type AdoVerbRequest } from '../../../shared/adoVerbArgv'
import { formatRelative } from '../../../shared/format'
import { exitHeading, NOT_PULLED_YET, newerPlugin, UNDATED } from '../../../shared/reasons'
import type { AdoVerbResult } from '../../../shared/types'
import { Chip, Eyebrow } from '../../ui'
import { BRIDGE_MISSING, CommentComposer, runAdo } from './CommentComposer'
import { PullNow, type PullKind, type PullScope } from './PullNow'

/** The plugin's quote prefix, flag mark and flag suffix (`ado_discussion_map.QUOTE`, `FLAG_MARK`): the one
 * place a line of comment text is told from the tool's own words. */
const QUOTE = '  | '
const FLAG_MARK = '⚑'
const FLAG_SUFFIX = `   ${FLAG_MARK} reads as an instruction`
const FLAG_LABEL = 'reads as an instruction'
const NOT_PULLED_LINE = 'Discussion not pulled yet.'

export interface DiscussionLine {
  text: string
  /** The plugin read this line as an instruction: it is shown, with a marker, and never acted on. */
  flagged: boolean
}

export interface DiscussionComment {
  id: number | null
  /** A roster handle, else the plugin's own word for an author it could not map. */
  by: string | null
  created: string | null
  /** How many times it was edited: version 3 is edited twice. */
  edits: number
  deleted: boolean
  lines: DiscussionLine[]
}

export interface DiscussionView {
  /** False when the plugin said the discussion was never pulled for this item (not the same as "No comments"). */
  pulled: boolean
  asOf: string | null
  comments: DiscussionComment[]
  /** The plugin's own sentences about this read, verbatim. */
  notes: string[]
}

export interface DiscussionAttachment {
  name: string
  url: string | null
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const DATEISH = /^\d{4}-\d{2}-\d{2}/

/** `Comment 9 · v3 (edited) · @priya-n · 2026-10-12T12:00:00Z · modified 2026-10-13T11:00:00Z · deleted`: the
 * header the plugin builds in `_comment_lines`, read from the right so a display name with a dot in it cannot
 * shift a field. Cosmetic fields only — the text is never taken from a header. */
function readHeader(line: string): DiscussionComment | null {
  const m = /^Comment(?: (\d+))?(?: · (.*))?$/.exec(line)
  if (!m) return null
  const parts = m[2] ? m[2].split(' · ') : []
  let deleted = false
  if (parts[parts.length - 1] === 'deleted') { deleted = true; parts.pop() }
  if (/^modified \S+$/.test(parts[parts.length - 1] ?? '')) parts.pop()
  let edits = 0
  const version = /^v(\d+) \(edited\)$/.exec(parts[0] ?? '')
  if (version) { edits = Math.max(0, Number(version[1]) - 1); parts.shift() }
  let created: string | null = null
  if (parts.length >= 2 && DATEISH.test(parts[parts.length - 1]!)) created = parts.pop()!
  return { id: m[1] ? Number(m[1]) : null, by: parts.length > 0 ? parts.join(' · ') : null, created, edits, deleted, lines: [] }
}

function readLine(line: string): DiscussionLine {
  const body = line.startsWith(QUOTE) ? line.slice(QUOTE.length) : ''
  return body.endsWith(FLAG_SUFFIX) ? { text: body.slice(0, -FLAG_SUFFIX.length), flagged: true } : { text: body, flagged: false }
}

/** The one document `show --json` printed → what this block draws. Never throws: a document that is not that
 * one is "not pulled", never an empty discussion. */
export function parseDiscussion(doc: Record<string, unknown> | null): DiscussionView {
  const notes = isObject(doc) && Array.isArray(doc.notes) ? doc.notes.filter((n): n is string => typeof n === 'string') : []
  if (isObject(doc) && typeof doc.unavailable === 'string' && doc.unavailable) notes.push(`unavailable: ${doc.unavailable}`)
  const asOf = isObject(doc) && typeof doc.as_of === 'string' ? doc.as_of : null
  const rendered = isObject(doc) && typeof doc.rendered === 'string' ? doc.rendered : null
  if (rendered === null) return { pulled: false, asOf, comments: [], notes }
  const comments: DiscussionComment[] = []
  let pulled = true
  for (const line of rendered.split('\n')) {
    if (line === NOT_PULLED_LINE) { pulled = false; continue }
    if (line === 'Changes') break // the update history follows; it is not discussion
    if (line.startsWith(QUOTE) || line === QUOTE.trimEnd()) {
      const last = comments[comments.length - 1]
      if (last) last.lines.push(readLine(line))
      continue
    }
    const header = readHeader(line)
    if (header) comments.push(header)
  }
  return { pulled, asOf, comments, notes }
}

/** An address a person may be sent to: absolute http(s) only. Everything else — `javascript:`, `file:`, a
 * protocol-relative `//host`, nothing — is not a link. */
/** The host of an already-vetted href, for display beside the link's name; never throws (the href came from safeHref). */
export function hostOf(href: string): string {
  try {
    return new URL(href).host
  } catch {
    return ''
  }
}

export function safeHref(url: string | null | undefined): string | null {
  if (typeof url !== 'string') return null
  const text = url.trim()
  if (!/^https?:\/\/[^\s/]/i.test(text)) return null
  try {
    const parsed = new URL(text)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? text : null
  } catch {
    return null
  }
}

/** "2026-10-12 09:02" from the plugin's ISO stamp, or the word "undated". */
function stamp(at: string | null): string {
  if (!at) return UNDATED
  const m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(at)
  return m ? `${m[1]} ${m[2]}` : at
}

type Phase =
  | { phase: 'loading' }
  | { phase: 'ready'; view: DiscussionView }
  | { phase: 'unavailable'; message: string }

export interface DiscussionBlockProps {
  projectPath: string
  /** `sdlc:<kind>:<id>` or `#<work item>` — the item whose discussion this is. */
  itemRef: string
  /** `generate_status.py --json` capabilities; null while unknown. */
  capabilities: readonly string[] | null
  /** Steering mode: rows only — no pull buttons, no composer. */
  steering?: boolean
  /** Which pull buttons ride in the header: both (the default), or only `Pull discussion` when the host draws
   * `Pull now` itself (the spec card keeps it beside the chip). */
  pull?: PullScope
  /** Called after a pull that read the board, with what the plugin answered. */
  onPulled?: (what: PullKind, result: AdoVerbResult) => void
  /** Passed through to the composer: the roster handle az is signed in as, when the host knows it. */
  executedAs?: string | null
  /** Attachments the host knows for this item. Links, never fetched. */
  attachments?: readonly DiscussionAttachment[]
  /** Fixed in a test so "2 days ago" is deterministic. */
  now?: number | Date
}

export function DiscussionBlock({ projectPath, itemRef, capabilities, steering = false, pull = 'both', onPulled, executedAs, attachments = [], now }: DiscussionBlockProps) {
  const [state, setState] = useState<Phase>({ phase: 'loading' })
  const missing = (cap: string) => (capabilities !== null && !capabilities.includes(cap) ? newerPlugin(cap) : null)
  const showMissing = missing(ADO_VERB_CAPABILITY.show)

  const load = useCallback(async (alive: () => boolean = () => true) => {
    const request: AdoVerbRequest = { verb: 'show', ref: itemRef }
    const problems = validateAdoVerbRequest(request)
    if (problems.length > 0) { setState({ phase: 'unavailable', message: problems.join('\n') }); return }
    const result = await runAdo(projectPath, request)
    if (!alive()) return
    if (!result) setState({ phase: 'unavailable', message: BRIDGE_MISSING })
    else if (result.exitCode !== 0) setState({ phase: 'unavailable', message: result.stderr.trim() || exitHeading(result.exitCode) })
    else setState({ phase: 'ready', view: parseDiscussion(result.json) })
  }, [projectPath, itemRef])

  useEffect(() => {
    if (showMissing) { setState({ phase: 'unavailable', message: showMissing }); return }
    let live = true
    setState({ phase: 'loading' })
    void load(() => live)
    return () => { live = false }
  }, [load, showMissing])

  // The cache a Pull discussion just wrote is what `show` reads: read it again. A fields pull changes no comment.
  const pulled = (what: PullKind, result: AdoVerbResult) => {
    if (what === 'discussion') void load()
    onPulled?.(what, result)
  }

  const view = state.phase === 'ready' ? state.view : null
  const links = attachments.map((a) => ({ name: a.name, href: safeHref(a.url) }))

  return (
    <section aria-label="Board discussion" data-testid="discussion-block" className="space-y-2">
      <div className="flex min-h-7 items-start justify-between gap-3">
        <Eyebrow as="h3">Discussion</Eyebrow>
        <PullNow projectPath={projectPath} capabilities={capabilities} itemRef={itemRef} scope={pull} steering={steering} onPulled={pulled} className="items-end" />
      </div>
      {state.phase === 'loading' ? <p className="text-xs text-ink-3">Reading the discussion…</p> : null}
      {state.phase === 'unavailable' ? <p className="text-xs text-ink-3 [overflow-wrap:anywhere]" data-testid="discussion-unavailable">{state.message}</p> : null}
      {view && !view.pulled ? <p className="text-sm text-ink-3" data-testid="discussion-not-pulled">{NOT_PULLED_YET}</p> : null}
      {view && view.pulled && view.comments.length === 0 ? <p className="text-sm text-ink-3" data-testid="discussion-empty">No comments.</p> : null}
      {view && view.pulled && view.comments.length > 0 ? (
        <ul role="list" data-testid="discussion-list" className="m-0 list-none space-y-2 p-0">
          {view.comments.map((c, i) => (
            <li key={c.id ?? `n${i}`} role="listitem" data-comment-id={c.id ?? undefined} data-deleted={c.deleted ? '' : undefined} className="rounded-[10px] border-l-2 border-line-2 bg-surface-1 px-3 py-2 text-xs">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <span className="font-mono text-ident text-ink-1">{c.by ?? UNDATED}</span>
                <span className="text-ink-3" title={c.created ?? undefined}>{c.created ? formatRelative(c.created, now) : UNDATED}</span>
                {c.edits > 0 ? <Chip size="xs" tone="neutral" data-edited="">edited ×{c.edits}</Chip> : null}
                {c.deleted ? <Chip size="xs" tone="warn" data-deleted="">deleted</Chip> : null}
              </div>
              {c.lines.map((line, j) => (
                <p key={j} data-comment-line="" className="mt-0.5 whitespace-pre-wrap text-[13px] leading-[18px] text-ink-2 [overflow-wrap:anywhere]">
                  {line.flagged ? <span data-flag="" role="img" aria-label={FLAG_LABEL} title={FLAG_LABEL} className="mr-1 text-status-warn-ink">{FLAG_MARK}</span> : null}
                  {line.text}
                </p>
              ))}
            </li>
          ))}
        </ul>
      ) : null}
      {view?.asOf ? <p className="font-mono text-ident text-ink-3" data-testid="discussion-as-of">as of {stamp(view.asOf)}</p> : null}
      {view && view.notes.length > 0 ? <ul className="m-0 list-none space-y-0.5 p-0 text-[11px] text-ink-3">{view.notes.map((n) => <li key={n} className="[overflow-wrap:anywhere]">{n}</li>)}</ul> : null}
      {links.length > 0 ? (
        <div data-testid="discussion-attachments" className="space-y-0.5 text-xs">
          <p className="font-medium text-ink-2">Attachments</p>
          <ul role="list" className="m-0 list-none space-y-0.5 p-0">
            {links.map((a, i) => (
              <li key={i} role="listitem">
                {a.href ? (
                  <>
                    <a href={a.href} target="_blank" rel="noreferrer noopener" className="font-medium text-accent-text hover:underline">{a.name}</a>
                    {/* the link's host beside its name: a board comment's attachment is observed content, so the
                        person sees where a click goes before making it (security review of PR #5, LOW) */}
                    <span className="font-mono text-ident text-ink-3" data-testid="attachment-host"> · {hostOf(a.href)}</span>
                  </>
                ) : <span className="text-ink-3">{a.name}</span>}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {!steering ? <CommentComposer projectPath={projectPath} itemRef={itemRef} capabilities={capabilities} executedAs={executedAs} onPosted={() => { void load() }} /> : null}
    </section>
  )
}
