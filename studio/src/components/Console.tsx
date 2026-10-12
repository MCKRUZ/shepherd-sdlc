import { useCallback, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { formatTime } from '../../shared/format'
import type { ConsoleEntry } from '../../shared/types'
import { Chip, EmptyState, Segmented, StatusDot, type DotStatus } from '../ui'
import { consoleStore, useConsoleStore } from '../stores/consoleStore'
import { useStudioGSAP } from '../motion/useStudioGSAP'
import { motion } from '../motion/motion'
import { MOTION_DURATIONS, MOTION_EASES } from '../motion/contract'
import { CONSOLE_HEIGHT_PX, consoleRowExpand, contextFrom } from '../motion/choreo'

function commandBasename(path: string): string {
  return path.split(/[\\/]/).pop()?.toLowerCase().replace(/\.(exe|cmd|bat)$/, '') ?? path
}

type CliTool = 'git' | 'gh' | 'az'
const CLI_TOOLS: ReadonlySet<string> = new Set(['git', 'gh', 'az'])

/** Recognizes a git / gh / az invocation regardless of how it was actually launched — a
 * resolved absolute path, or (on Windows, for a .cmd-shimmed `gh` or `az.cmd`) routed through
 * cmd.exe /c, in which case the real tool name and subcommand sit one position further into
 * args. See tooling.ts's ResolvedBinary. Exported for `test/consoleAz.test.tsx`. */
export function gitOrGhSubcommand(entry: ConsoleEntry): { tool: CliTool; subArgs: string[] } | null {
  const base = commandBasename(entry.command)
  if (CLI_TOOLS.has(base)) return { tool: base as CliTool, subArgs: entry.args }
  if (base === 'cmd' && entry.args[0] === '/c') {
    const shimBase = commandBasename(entry.args[1] ?? '')
    if (CLI_TOOLS.has(shimBase)) return { tool: shimBase as CliTool, subArgs: entry.args.slice(2) }
  }
  return null
}

const GIT_PHRASES: Record<string, string> = {
  fetch: 'Checked for changes',
  show: 'Read a file from the repository',
  push: 'Saved changes to the repository',
  'read-tree': 'Prepared a commit',
  'hash-object': 'Prepared a commit',
  'update-index': 'Prepared a commit',
  'write-tree': 'Prepared a commit',
  'commit-tree': 'Prepared a commit',
  branch: 'Checked the current branch',
  'rev-parse': 'Looked up a commit',
  remote: 'Checked the repository connection',
  'ls-tree': 'Listed files in the repository',
  log: 'Checked recent history',
}

/** The az twin of the gh phrases. `az.ts` appends `--only-show-errors -o json`, so the verbs
 * are always at the front; `--status completed` is what turns a `repos pr update` into a merge. */
function azPlainPhrase(subArgs: string[]): string {
  const [group, noun, verb] = subArgs
  if (group === 'repos' && noun === 'pr') {
    if (verb === 'create') return 'Opened a pull request'
    if (verb === 'update') {
      const at = subArgs.indexOf('--status')
      return at >= 0 && subArgs[at + 1] === 'completed' ? 'Merged a pull request' : 'Updated a pull request'
    }
    if (verb === 'list' || verb === 'show') return 'Checked pull request status'
  }
  if (group === 'account' && noun === 'show') return 'Checked who is signed in'
  if (group === 'repos' && noun === 'policy' && verb === 'list') return 'Checked branch policies'
  return 'Talked to the code host'
}

export function toolPlainPhrase(tool: CliTool, subArgs: string[]): string {
  const sub = subArgs[0] ?? ''
  if (tool === 'git') return GIT_PHRASES[sub] ?? 'Talked to git'
  if (tool === 'az') return azPlainPhrase(subArgs)
  if (sub === 'pr' && subArgs[1] === 'create') return 'Opened a pull request'
  if (sub === 'pr' && subArgs[1] === 'merge') return 'Merged a pull request'
  if (sub === 'pr' && subArgs[1] === 'list') return 'Checked pull request status'
  if (sub === 'api') return 'Talked to the code host'
  return 'Talked to the code host'
}

/** One sentence describing what a command did — the console's "plain" view. Never hides a
 * command from either view; this is purely a friendlier summary of the SAME entry the
 * technical view shows in full. */
export function plainSummary(entry: ConsoleEntry): string {
  const seconds = (entry.durationMs / 1000).toFixed(1)
  const gitOrGh = gitOrGhSubcommand(entry)
  if (gitOrGh) {
    const phrase = toolPlainPhrase(gitOrGh.tool, gitOrGh.subArgs)
    if (entry.pending) return `${phrase} — still running…`
    return entry.ok ? `${phrase} — finished in ${seconds}s.` : `${phrase} — failed after ${seconds}s.`
  }
  const name = entry.command === 'uv' ? (entry.args[2]?.split(/[\\/]/).pop() ?? entry.command) : entry.command
  if (entry.pending) return `Running ${name}…`
  if (entry.ok) {
    return `Ran ${name} — finished in ${seconds}s.`
  }
  return `${name} failed after ${seconds}s.`
}

/** A pending entry is a command still running (an interim broadcast); its dot says so rather
 * than guessing ok or failed before the exit code exists. */
function dotFor(entry: ConsoleEntry): DotStatus {
  if (entry.pending) return 'running'
  return entry.ok ? 'ok' : 'error'
}

function choreoContext(scope: Element) {
  return contextFrom(scope, { enabled: motion.enabled(), reduced: motion.reduced() }, { durations: MOTION_DURATIONS, eases: MOTION_EASES })
}

function ConsoleRow({ entry, view }: { entry: ConsoleEntry; view: 'plain' | 'technical' }) {
  const [expanded, setExpanded] = useState(false)
  const detailRef = useRef<HTMLDivElement>(null)

  // Choreography #20 (row half): the detail block grows to its height and the first <pre> fades.
  useStudioGSAP(() => {
    const row = detailRef.current
    if (!row || !expanded) return
    consoleRowExpand.play(choreoContext(row), { row, pre: row.querySelector('pre') })
  }, { scope: detailRef, dependencies: [expanded] })

  return (
    // Telemetry density (G4-16): colour sits on the dot and the chip, never on the sentence.
    <div className="border-b border-line-1 py-1.5 text-xs">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-start justify-between gap-3 text-left"
      >
        <StatusDot status={dotFor(entry)} pulse={Boolean(entry.pending)} className="mt-1" />
        <div className="min-w-0 flex-1">
          {view === 'plain' ? (
            <p className="font-normal text-ink-1">{plainSummary(entry)}</p>
          ) : (
            <code className="block truncate font-mono text-code text-ink-2">
              {entry.command} {entry.args.join(' ')}
            </code>
          )}
          {/* C3: plain `text-2xs` (the token no longer tracks or bolds); words, so ink-3 (C2). */}
          <p className="mt-0.5 font-mono text-2xs text-ink-3">
            {formatTime(entry.startedAt)} · {entry.durationMs}ms · cwd: {entry.cwd}
          </p>
        </div>
        <Chip size="xs" tone={entry.pending ? 'neutral' : entry.ok ? 'ok' : 'error'} className="font-mono tabular-nums">
          {entry.pending ? 'RUNNING' : entry.ok ? 'OK' : `EXIT ${entry.exitCode ?? 'ERR'}`}
        </Chip>
      </button>
      {expanded && (
        <div ref={detailRef} className="mt-2 space-y-2 overflow-hidden">
          {view === 'technical' && (
            <p className="font-mono text-code text-ink-3">cwd: {entry.cwd}</p>
          )}
          {/* The two `<pre>` colour sets are kept literally (the dark-theme list names them);
              only the code type token, leading and corner radius are added. */}
          {entry.stdout && (
            <pre className="max-h-48 overflow-auto rounded-[8px] bg-surface-code p-2.5 font-mono text-code leading-4 text-white">
              {entry.stdout}
            </pre>
          )}
          {entry.stderr && (
            <pre className="max-h-48 overflow-auto rounded-[8px] bg-red-950 p-2.5 font-mono text-code leading-4 text-red-100">
              {entry.stderr}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

export const CONSOLE_HEIGHT_KEY = 'studio.consoleHeight'
export const CONSOLE_MIN_HEIGHT = 120
const KEY_STEP = 24

/** The remembered console height (`studio.consoleHeight`, §6.4), or the choreography's resting
 * height when nothing valid is stored. Frame reads this for the dock's first paint. */
export function readStoredConsoleHeight(): number {
  try {
    const raw = typeof localStorage === 'undefined' ? null : localStorage.getItem(CONSOLE_HEIGHT_KEY)
    const n = raw === null ? NaN : Number(raw)
    return Number.isFinite(n) && n >= CONSOLE_MIN_HEIGHT ? n : CONSOLE_HEIGHT_PX
  } catch {
    return CONSOLE_HEIGHT_PX
  }
}

export function consoleMaxHeight(): number {
  return typeof window === 'undefined' ? CONSOLE_HEIGHT_PX * 2 : Math.max(CONSOLE_MIN_HEIGHT, Math.floor(window.innerHeight * 0.6))
}

export function clampConsoleHeight(h: number): number {
  return Math.min(consoleMaxHeight(), Math.max(CONSOLE_MIN_HEIGHT, Math.round(h)))
}

/** The console's panel: a drag handle on its top edge, the Plain / Technical switch, and one row
 * per command. The height is a local preference (`studio.consoleHeight`, §6.4) but the element
 * that has it is Frame's dock around this panel, so Frame OWNS the height: it passes the current
 * value in and the separator here reports a new one through `onHeightChange` rather than reaching
 * for `parentElement.style`. Persisting is still this panel's job — it is the control that
 * changes the value — and happens on commit (pointer up, a key, a double-click), not per pixel. */
export function Console({ entries, height, onHeightChange }: {
  entries: ConsoleEntry[]
  /** The dock's current height in px; Frame's state. */
  height: number
  /** Called with a clamped height whenever the separator moves it. */
  onHeightChange: (height: number) => void
}) {
  const { mode: view } = useConsoleStore()
  const drag = useRef<{ startY: number; startH: number } | null>(null)

  const applyHeight = useCallback((h: number) => {
    const clamped = clampConsoleHeight(h)
    onHeightChange(clamped)
    return clamped
  }, [onHeightChange])

  const persist = useCallback((h: number) => {
    try { localStorage.setItem(CONSOLE_HEIGHT_KEY, String(h)) } catch { /* a preference, not data */ }
  }, [])

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    drag.current = { startY: e.clientY, startH: height }
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    // The handle is on the TOP edge: dragging up makes the panel taller.
    applyHeight(drag.current.startH + (drag.current.startY - e.clientY))
  }
  const onPointerUp = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    drag.current = null
    e.currentTarget.releasePointerCapture(e.pointerId)
    persist(height)
  }
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const delta = e.key === 'ArrowUp' ? KEY_STEP : e.key === 'ArrowDown' ? -KEY_STEP : e.key === 'Home' ? Infinity : e.key === 'End' ? -Infinity : null
    if (delta === null) return
    e.preventDefault()
    persist(applyHeight(delta === Infinity ? consoleMaxHeight() : delta === -Infinity ? CONSOLE_MIN_HEIGHT : height + delta))
  }

  return (
    <div className="flex h-full flex-col">
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize console"
        aria-valuemin={CONSOLE_MIN_HEIGHT}
        aria-valuemax={consoleMaxHeight()}
        aria-valuenow={height}
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={() => persist(applyHeight(CONSOLE_HEIGHT_PX))}
        onKeyDown={onKeyDown}
        className="group -mt-1 h-2 shrink-0 cursor-row-resize touch-none"
      >
        <span aria-hidden="true" className="mx-auto mt-0.5 block h-1 w-10 rounded-full bg-line-2 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
      </div>
      <div className="flex items-center justify-between border-b border-line-1 px-3 py-2">
        <h2 className="text-sm font-semibold text-ink-1">Console</h2>
        <Segmented<'plain' | 'technical'>
          label="Console view"
          tone="neutral"
          size="sm"
          value={view}
          onChange={consoleStore.setMode}
          options={[{ value: 'plain', label: 'Plain' }, { value: 'technical', label: 'Technical' }]}
        />
      </div>
      <div className="flex-1 overflow-auto px-3">
        {entries.length === 0 ? (
          // The kit's one "nothing here" frame (G4-9); the sentence is unchanged.
          <EmptyState title="Nothing has run yet." className="my-3" />
        ) : (
          entries.map((entry) => <ConsoleRow key={entry.id} entry={entry} view={view} />)
        )}
      </div>
    </div>
  )
}
