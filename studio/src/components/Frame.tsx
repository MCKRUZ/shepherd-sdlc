import { memo, type CSSProperties, type MutableRefObject, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CommandCenter, ConsoleEntry, ProjectStatus, SyncState } from '../../shared/types'
import type { Area, NavTarget } from '../../shared/nav'
import { homeFor } from '../../shared/nav'
import { slateToBoardRow } from '../../shared/sprintModel'
import { identityLabel } from '../../shared/identity'
import { LifecycleStrip, stripFactsFrom } from './LifecycleStrip'
import { OMNIBAR_PLACEHOLDER, TopBand } from './TopBand'
import { ChatPanel } from './ChatPanel'
import { Console, readStoredConsoleHeight } from './Console'
import { ShortcutsHelp } from './ShortcutsHelp'
import { readSurfaceDefault } from './AppearanceSection'
import { consoleToggle, frameAssemble } from '../motion/choreo'
import { motion } from '../motion/motion'
import { useStudioGSAP } from '../motion/useStudioGSAP'
import { choreoContext } from './entryScreenBits'
import { CHAT_DEFAULT_WIDTH, readStoredChatWidth } from '../chatWidth'
import { StageReadinessProvider, useStageReadiness } from './StageReadinessContext'
import { consoleStore, useConsoleEntries, useConsoleOpen } from '../stores/consoleStore'
import { useBacklogStore } from '../stores/backlogStore'
import { useConnection } from '../stores/connectionStore'
import { stageTabStore } from '../stores/stageTabStore'
import { CHAT_RAIL_WIDTH, chatStore, useChatCollapsed } from '../stores/chatStore'
import { SkipLink } from '../ui/VisuallyHidden'
import { cn } from '../ui/cn'
import { ToastRegion } from '../ui/ToastRegion'
import { toast } from '../ui/toastStore'
import { LiveAnnouncer } from '../a11y/LiveAnnouncer'
import { CommandPalette } from '../palette/CommandPalette'
import { intentEntries, type IntentContext, type IntentMatch } from '../palette/intents'
import { toggleSurfacePreference } from '../palette/paletteActions'
import { usePaletteIndex, usePreferenceActionHooks } from '../palette/usePaletteIndex'
import type { PaletteActionHooks, SettingsAnchor } from '../palette/types'
import { useShortcuts } from '../shortcuts/useShortcuts'
import { useSceneActions } from '../scenes/core/sceneActions'
import { joinSpineAssemble } from '../scenes/spine/spineCeremony'

/** What App knows and Frame does not: where a spec, a document or a Settings section opens, what
 * "back" means on the current screen, and which screen is showing. Every field is optional so a
 * test (frame.memo.test) can mount Frame without it; an absent hook means the palette row for it
 * is absent, never inert. App memoises the object. */
export interface FrameShellHooks {
  /** Open a spec by its repo-relative path (what the Board and the palette's "#" rows carry). */
  openSpec?: (relPath: string) => void
  /** Open a document, with the stage its readiness belongs to so the strip lights that stage. */
  openDocument?: (relPath: string, stageId: string | undefined) => void
  /** Go to Settings and scroll to a section once it has mounted. */
  openSettings?: (anchor: SettingsAnchor) => void
  /** The screen's own Back, when there is something behind it. */
  back?: () => void
  /** True while the lifecycle home (StageHome inside it) is the screen: enables the Spine toggle
   * and the readiness refresh. */
  stageHomeShowing?: boolean
  /** True while the Sprint view (with its constellation) is the screen. */
  sprintShowing?: boolean
  /** A screen's own P-class refresh, where App has one; never openProject or pull. */
  refreshScreen?: () => void
  /** The omnibar matched a verb (togo-command-center.md §3.6): App opens the VerbDialog. */
  openIntent?: (match: IntentMatch) => void
  /** The `…` menu's two project-switching rows. */
  newProject?: () => void
  openFolder?: () => void
}

/** The frame every screen shares once a project is open (togo-command-center.md §1): the shell
 * band — TopBand (mark · omnibar trigger · needs-you chip · sync · Console · Appearance · Settings
 * · `…`) over the LifecycleStrip (`nav[aria-label="Project"]`, the only navigation) — as the
 * FIRST `<aside>`, then `<main>` beside the chat (the second `<aside>`, 380 px), the console as
 * the bottom drawer. The a11y pins (two asides sidebar-then-chat, no `<input>` at rest, one `h1`,
 * one `aria-current`) hold verbatim: the band takes the sidebar's seat.
 *
 * Spec 0019: Frame is the common ancestor of both `StageHome` (rendered as its `children`) and
 * `ChatPanel` (its direct sibling), so it wraps them in `StageReadinessProvider`. `FrameBody` is
 * split out only because a value a `Context.Provider` holds can be read by a descendant, never by
 * the component that renders the provider itself.
 *
 * Observatory (§7 Frame row): the Wave 0 pieces mount here once — skip link, live region, toasts,
 * palette + shortcuts — and the heavy siblings get a `React.memo` boundary. Console entries never
 * travel through props: they live in `consoleStore` and only the Console panel subscribes.
 *
 * Steering mode (§3.5, visual §4 "steer-bg full-bleed; no chat, no console"): `steering` hides the
 * chat (the aside stays in the DOM), closes the console, takes the omnibar's verb group away, and
 * steps the shell back — the band becomes a presentation (mark · name · Leave), the strip and the
 * Build views are not drawn, and `<main>` drops its padding so the room is edge to edge. The
 * committee's view has zero write controls and nothing to navigate by but Esc. */
export function Frame({
  status, projectPath, consoleEntries, syncState, area, viewedStageId, actor, commandCenter = null, steering = false, onNavigate, shell, children,
}: {
  status: ProjectStatus
  projectPath: string
  /** Optional, for a test that mounts Frame with a fixed list; the app leaves it unset and the
   * Console reads `consoleStore`. */
  consoleEntries?: ConsoleEntry[]
  syncState: SyncState
  area: Area
  /** The stage whose documents were picked, or undefined for the project's current stage. */
  viewedStageId?: string
  /** Who is using Studio — spec 0016's chat needs this to attribute an accepted or discarded
   * proposal through the SAME draft ledger a structured-editor draft already uses. */
  actor: string
  /** The one read model (§2.3) App holds; null before it lands or on a plugin without it. */
  commandCenter?: CommandCenter | null
  steering?: boolean
  onNavigate: (target: NavTarget) => void
  shell?: FrameShellHooks
  children: ReactNode
}) {
  const currentStageId = status.stages.find((s) => s.stage_state === 'current')?.id
  // The ONE resolved stage every consumer below needs — the picked stage, or the project's own
  // current one, the same default stage_readiness.py itself uses when called with no --phase.
  const stageId = viewedStageId ?? currentStageId

  return (
    <StageReadinessProvider projectPath={projectPath} stageId={stageId}>
      <FrameBody
        status={status}
        projectPath={projectPath}
        consoleEntries={consoleEntries}
        syncState={syncState}
        area={area}
        viewedStageId={viewedStageId}
        stageId={stageId}
        currentStageId={currentStageId}
        actor={actor}
        commandCenter={commandCenter}
        steering={steering}
        onNavigate={onNavigate}
        shell={shell}
      >
        {children}
      </FrameBody>
    </StageReadinessProvider>
  )
}

/** Memo boundaries live here. `onNavigate` is a `useCallback` in App and `onToggleConsole` a
 * module function, so nothing happening in FrameBody reaches them. */
const MemoTopBand = memo(TopBand)
const MemoStrip = memo(LifecycleStrip)
const MemoChatPanel = memo(ChatPanel)

const EMPTY_SHELL: FrameShellHooks = {}

function FrameBody({
  status, projectPath, consoleEntries, syncState, area, viewedStageId, stageId, currentStageId, actor, commandCenter, steering, onNavigate, shell = EMPTY_SHELL, children,
}: {
  status: ProjectStatus
  projectPath: string
  consoleEntries?: ConsoleEntry[]
  syncState: SyncState
  area: Area
  viewedStageId?: string
  stageId: string | undefined
  currentStageId: string | undefined
  actor: string
  commandCenter: CommandCenter | null
  steering: boolean
  onNavigate: (target: NavTarget) => void
  shell?: FrameShellHooks
  children: ReactNode
}) {
  // Open/closed is store state so the palette's "Toggle console" and ⌘J flip the same flag the
  // band's button does; the dock below subscribes on its own.
  const consoleOpen = useConsoleOpen()
  // ⌘\, the band's Chat button and the `…` row fold the chat to its rail without unmounting it:
  // the aside keeps its place in DOM order (the a11y pins count two asides, band then chat) and
  // its composer keeps whatever was typed. The flag is PER AREA in `chatStore` (owner's v12
  // item 1): the sprint home and planning start folded so the lanes get the window; the choice
  // is remembered per machine. Steering hides the aside outright, as before.
  const chatCollapsed = useChatCollapsed(area)
  const toggleChat = useCallback(() => chatStore.toggle(area), [area])
  const expandChat = useCallback(() => chatStore.setCollapsed(area, false), [area])
  // Steering closes the console: the committee's screen has no drawer of command output.
  useEffect(() => { if (steering) consoleStore.setOpen(false) }, [steering])
  // The palette's open flag lives in ShellPalette so opening it re-renders that component alone;
  // the band's omnibar trigger reaches it through this ref, which ShellPalette fills on mount.
  const openPaletteRef = useRef<(() => void) | null>(null)
  const onOpenPalette = useCallback(() => openPaletteRef.current?.(), [])
  const openShortcutsRef = useRef<(() => void) | null>(null)
  const onOpenShortcuts = useCallback(() => openShortcutsRef.current?.(), [])

  const sprintFacts = useMemo(() => stripFactsFrom(commandCenter), [commandCenter])
  const needsYou = useMemo(() => (commandCenter ? { count: commandCenter.needsYou.length, reason: commandCenter.needsYouReason } : null), [commandCenter])
  // Guarded: a test fixture may omit `current_phase`; the real status always carries it.
  const home = homeFor(status.current_phase ? status : null, null, commandCenter?.capabilities ?? null)
  const { newProject, openFolder, back } = shell
  // Esc's own path out of steering (App's `back` returns to the screen it was entered from); a
  // test that mounts Frame without the hook leaves through the sprint home.
  const leaveSteering = useCallback(() => { if (back) back(); else onNavigate({ area: 'sprint' }) }, [back, onNavigate])
  const presentation = useMemo(() => (steering ? { onLeave: leaveSteering } : undefined), [steering, leaveSteering])
  const overflow = useMemo(() => ({
    toggleChat,
    openShortcuts: onOpenShortcuts,
    steering: () => onNavigate({ area: 'steering' }),
    newProject,
    openFolder,
  }), [toggleChat, onOpenShortcuts, onNavigate, newProject, openFolder])

  // The Frame root carries `--chat-width` / `--console-height` and `data-chat-hidden` (the
  // round-2 shell contract, read by screens that lay out beside the chat or above the console).
  // Both numbers live in the panels that own them; they REPORT here through stable callbacks and
  // the root's inline style is written imperatively, so a drag never re-renders FrameBody and
  // the memoised siblings keep their props. The refs make React's view of `style` match the DOM.
  const rootRef = useRef<HTMLDivElement>(null)
  const chatWidthRef = useRef<number>(readStoredChatWidth() ?? CHAT_DEFAULT_WIDTH)
  const consoleHeightRef = useRef<number>(consoleOpen ? readStoredConsoleHeight() : 0)
  // Folded, the aside is its 40 px rail, and that is the width the screens beside it (the toast
  // stack) must lay out against — the panel's own chosen width waits for the moment it reopens.
  const chatCollapsedRef = useRef(chatCollapsed)
  chatCollapsedRef.current = chatCollapsed
  const applyChatWidth = useCallback(() => {
    const px = chatCollapsedRef.current ? CHAT_RAIL_WIDTH : chatWidthRef.current
    rootRef.current?.style.setProperty('--chat-width', `${px}px`)
  }, [])
  const onChatWidth = useCallback((px: number) => {
    chatWidthRef.current = px
    applyChatWidth()
  }, [applyChatWidth])
  useEffect(() => { applyChatWidth() }, [chatCollapsed, applyChatWidth])
  const onConsoleHeight = useCallback((px: number) => {
    consoleHeightRef.current = px
    rootRef.current?.style.setProperty('--console-height', `${px}px`)
  }, [])
  const rootStyle = {
    '--chat-width': `${chatCollapsed ? CHAT_RAIL_WIDTH : chatWidthRef.current}px`,
    '--console-height': `${consoleHeightRef.current}px`,
  } as CSSProperties

  useFrameAssemble(rootRef, projectPath)
  usePrefetchCanvasHost(projectPath)

  return (
    <div ref={rootRef} data-frame-root="" data-chat-hidden={steering ? '' : undefined} data-chat-collapsed={chatCollapsed && !steering ? '' : undefined} data-steering={steering ? '' : undefined} style={rootStyle} className="flex h-screen flex-col bg-surface-0">
      <SkipLink />
      <LiveAnnouncer />
      {/* The shell band: the FIRST aside, holding the band and the strip (`nav[aria-label="Project"]`). */}
      <aside data-testid="shell-band" aria-label="Project shell" className={cn('shrink-0', steering ? 'bg-steer-bg' : 'bg-surface-0')}>
        <MemoTopBand
          status={status}
          syncState={syncState}
          area={area}
          consoleOpen={consoleOpen}
          onToggleConsole={consoleStore.toggle}
          onOpenPalette={onOpenPalette}
          onNavigate={onNavigate}
          needsYou={needsYou}
          home={home}
          currentStageId={currentStageId ?? null}
          overflow={overflow}
          presentation={presentation}
          chatOpen={!chatCollapsed}
          onToggleChat={toggleChat}
        />
        {/* The strip (and the Build views under it) is navigation; steering mode draws none. */}
        {!steering && <MemoStrip status={status} projectPath={projectPath} area={area} viewedStageId={viewedStageId} sprint={sprintFacts} onNavigate={onNavigate} />}
      </aside>
      {/* Column below sm, row at sm+ — spec 0018's document panel and chat need to stack at
          phone width. */}
      <div className="flex min-h-0 flex-1 flex-col sm:flex-row">
        {/* `id="main"` is the skip link's target; `tabIndex={-1}` takes programmatic focus without
            joining the tab order. Children render directly — no wrapper (§7 Frame row [MF]).
            Steering: no padding, so the room is full-bleed without negative margins. */}
        {/* <main> is the ONLY scroller, so it is also POSITIONED (`main#main { position: relative }`
            in theme/base.css, beside the root-never-scrolls rule) — the containing block of every
            absolutely positioned descendant. Unpositioned, an `absolute` box inside a screen resolves
            against the viewport, escapes main's clip and grows the document (v13's probe measured the
            root at 1440×1608 on the review and closing screens, scrolled 7.5 px — the whole shell
            offset, owner's item 6). The class list here is a pin (frame.memo.test), so the rule
            lives in the stylesheet. */}
        <main id="main" tabIndex={-1} className={cn('min-w-0 flex-1 overflow-auto', steering ? 'p-0' : 'p-6')}>{children}</main>
        <MemoChatPanel status={status} projectPath={projectPath} actor={actor} stageId={stageId ?? null} hidden={steering} collapsed={chatCollapsed} onExpand={expandChat} onWidthChange={onChatWidth} />
      </div>
      <ConsoleDock entries={consoleEntries} onHeightReport={onConsoleHeight} />
      <ToastRegion />
      <ShellPalette
        status={status}
        projectPath={projectPath}
        currentStageId={currentStageId}
        viewedStageId={stageId}
        area={area}
        commandCenter={commandCenter}
        steering={steering}
        onNavigate={onNavigate}
        toggleChat={toggleChat}
        shell={shell}
        openRef={openPaletteRef}
        openShortcutsRef={openShortcutsRef}
      />
    </div>
  )
}

/** The console's dock: Frame owns the element whose height the preference and choreography #20
 * move, so it owns the height too. The stored `studio.consoleHeight` is the first paint's inline
 * height (the `h-64` class stays as the resting truth, pinned by frame.memo.test); the separator
 * inside Console reports a new height through a prop. Open plays the grow half on mount; close
 * keeps the dock mounted for the shrink half and unmounts when the timeline ends — synchronously
 * under the stub, so with motion off (every test) the dock is gone on the same tick. */
function ConsoleDock({ entries, onHeightReport }: { entries?: ConsoleEntry[]; onHeightReport?: (px: number) => void }) {
  const open = useConsoleOpen()
  const [rendered, setRendered] = useState(open)
  const [height, setHeight] = useState(readStoredConsoleHeight)
  const heightRef = useRef(height)
  heightRef.current = height
  const wrapper = useRef<HTMLDivElement>(null)

  useEffect(() => { if (open) setRendered(true) }, [open])
  useEffect(() => {
    onHeightReport?.(rendered ? height : 0)
  }, [onHeightReport, rendered, height])

  useStudioGSAP(() => {
    const el = wrapper.current
    if (!el || !rendered) return
    const tl = consoleToggle.play(choreoContext(el), { wrapper: el, direction: open ? 'open' : 'close' })
    tl.add(open ? () => { el.style.height = `${heightRef.current}px` } : () => setRendered(false))
  }, { scope: wrapper, dependencies: [open, rendered] })

  if (!rendered) return null
  return (
    <div ref={wrapper} className="h-64 shrink-0 border-t border-line-1 bg-white" style={{ height }}>
      <ConsolePanel entries={entries} height={height} onHeightChange={setHeight} />
    </div>
  )
}

/** The one subscriber to the console's entries. A test-supplied prop wins over the store so the
 * two jsdom tests that mount Frame with `consoleEntries={[]}` see exactly what they passed. */
function ConsolePanel({ entries, height, onHeightChange }: {
  entries?: ConsoleEntry[]
  height: number
  onHeightChange: (height: number) => void
}) {
  const stored = useConsoleEntries()
  return <Console entries={entries ?? (stored as ConsoleEntry[])} height={height} onHeightChange={onHeightChange} />
}

/** The clipboard is the renderer's own; a failure (no permission, no clipboard in a test) is a
 * toast saying so, never a silent nothing. */
function copyProjectPath(projectPath: string): void {
  const clipboard = typeof navigator !== 'undefined' ? navigator.clipboard : undefined
  if (!clipboard?.writeText) {
    toast({ tone: 'error', title: 'Could not reach the clipboard' })
    return
  }
  clipboard.writeText(projectPath)
    .then(() => toast({ tone: 'ok', title: 'Project path copied' }))
    .catch(() => toast({ tone: 'error', title: 'Could not copy the project path' }))
}

/** Palette + shortcuts help + the shell's shortcuts, isolated so opening either re-renders this
 * component and nothing above it. The index is built from what Frame already holds; nothing
 * here calls the bridge. The omnibar's verb row (`intents.ts`) reads the same held state — the
 * backlog rows, the command center's roster and sprints, the connection's identity — and hands a
 * match to App through `shell.openIntent`; nothing is spawned here. */
function ShellPalette({ status, projectPath, currentStageId, viewedStageId, area, commandCenter, steering, onNavigate, toggleChat, shell, openRef, openShortcutsRef }: {
  status: ProjectStatus
  projectPath: string
  currentStageId: string | undefined
  viewedStageId: string | undefined
  area: Area
  commandCenter: CommandCenter | null
  steering: boolean
  onNavigate: (target: NavTarget) => void
  toggleChat: () => void
  shell: FrameShellHooks
  openRef: MutableRefObject<(() => void) | null>
  openShortcutsRef: MutableRefObject<(() => void) | null>
}) {
  const [open, setOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const { readiness, refresh } = useStageReadiness()
  const backlog = useBacklogStore()
  const connection = useConnection()
  const prefs = usePreferenceActionHooks()
  const scene = useSceneActions()
  const openPalette = useCallback(() => { setHelpOpen(false); setOpen(true) }, [])
  const closePalette = useCallback(() => setOpen(false), [])
  const openShortcuts = useCallback(() => { setOpen(false); setHelpOpen(true) }, [])
  const closeShortcuts = useCallback(() => setHelpOpen(false), [])
  useEffect(() => {
    openRef.current = openPalette
    openShortcutsRef.current = openShortcuts
    return () => { openRef.current = null; openShortcutsRef.current = null }
  }, [openRef, openShortcutsRef, openPalette, openShortcuts])

  const { openSpec, openDocument, openSettings, back, stageHomeShowing, sprintShowing, refreshScreen, openIntent } = shell
  const readinessStageId = readiness?.ok ? readiness.stageId : undefined
  const actions = useMemo<PaletteActionHooks>(() => ({
    ...prefs.hooks,
    toggleConsole: consoleStore.toggle,
    toggleChat,
    toggleSpine: stageHomeShowing ? stageTabStore.toggleSpineCollapsed : undefined,
    toggleSurface: stageHomeShowing ? () => toggleSurfacePreference('spine') : sprintShowing ? () => toggleSurfacePreference('sprint') : undefined,
    refreshScreen: stageHomeShowing ? () => { void refresh() } : refreshScreen,
    fitGraph: scene?.fitGraph,
    focusNextUp: scene ? () => { scene.focusNextUp() } : undefined,
    copyProjectPath: () => copyProjectPath(projectPath),
    openShortcuts,
    steering: steering ? undefined : () => onNavigate({ area: 'steering' }),
    back,
  }), [prefs.hooks, toggleChat, stageHomeShowing, sprintShowing, refresh, refreshScreen, scene, projectPath, openShortcuts, steering, onNavigate, back])

  const host = useMemo(() => ({
    stages: status.stages,
    currentStageId: currentStageId ?? null,
    viewedStageId: viewedStageId ?? null,
    readiness,
    backlog,
    actions,
    recentIds: [],
    area,
    navigate: onNavigate,
    openSpec: openSpec ?? (() => onNavigate({ area: 'build' })),
    openDocument: openDocument
      ? (path: string) => openDocument(path, readinessStageId ?? viewedStageId)
      : () => onNavigate({ area: 'documents', stageId: viewedStageId }),
    openSettings: openSettings ?? (() => onNavigate({ area: 'settings' })),
  }), [status.stages, currentStageId, viewedStageId, readiness, readinessStageId, backlog, actions, area, onNavigate, openSpec, openDocument, openSettings])
  const { entries, recentIds, remember } = usePaletteIndex(host)

  // The omnibar's grammar context (§3.6): board rows (the slate converted the same way the Board
  // does), the roster, the sprint ids and capabilities the plugin reported, the identity label.
  const intents = useMemo(() => {
    if (steering || !openIntent) return undefined
    const seen = new Set(backlog.rows.map((r) => r.spec))
    const ctx: IntentContext = {
      rows: [...backlog.rows, ...backlog.slate.filter((s) => !seen.has(s.id)).map(slateToBoardRow)],
      roster: (commandCenter?.roster.data?.people ?? []).map((p) => ({ handle: p.handle, name: p.name })),
      activeSprint: commandCenter?.sprints.data?.active ?? commandCenter?.sprint.data?.sprint?.id ?? null,
      sprintIds: commandCenter?.sprints.data?.sprints.map((s) => s.id) ?? [],
      capabilities: commandCenter?.capabilities ?? null,
      actor: identityLabel(connection?.account, connection?.rosterHandle),
    }
    // `suggest` is the palette's own: a typo's nearest template fills the query and stays open.
    return (query: string, suggest: (phrase: string) => void) => intentEntries(query, ctx, openIntent, suggest)
  }, [steering, openIntent, backlog, commandCenter, connection])

  useShortcuts({
    handlers: {
      openPalette,
      openShortcuts,
      toggleConsole: consoleStore.toggle,
      toggleChat,
      cycleTheme: prefs.cycleTheme,
      toggleMotion: prefs.toggleMotion,
      toggleDensity: prefs.toggleDensity,
      openSettings: () => onNavigate({ area: 'settings' }),
      goStage: (stageId) => { if (status.stages.some((s) => s.id === stageId)) onNavigate({ area: 'documents', stageId }) },
    },
    scopes: ['project'],
    escLayers: [
      () => { if (!open) return false; setOpen(false); return true },
      () => { if (!helpOpen) return false; setHelpOpen(false); return true },
    ],
  })
  return (
    <>
      <CommandPalette open={open} onClose={closePalette} entries={entries} recentIds={recentIds} onRun={(e) => remember(e.id)} placeholder={OMNIBAR_PLACEHOLDER} intents={intents} />
      <ShortcutsHelp open={helpOpen} onClose={closeShortcuts} />
    </>
  )
}

/** M2 / M3: the shell opens as one thing. Played ONCE per `projectPath` from the Frame root the
 * moment it mounts, never again on a `refreshStatus` re-render. Only inner content is handed
 * over — the band, `<main>`'s first child and the chat's inner wrapper — never an `<aside>` or
 * `<main>` itself (§4 invariants). The strip's rail draw and station pops (row #32) and the
 * Spine's own draw join through `frameAssemble.join`. Under the stub nothing moves. */
function useFrameAssemble(rootRef: MutableRefObject<HTMLDivElement | null>, projectPath: string) {
  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    motion.recordOpen(projectPath)
    const tier = motion.familiarity(projectPath)
    const unjoin = frameAssemble.join((_ctx, tl) => { joinSpineAssemble(tl as unknown as gsap.core.Timeline) })
    const tl = frameAssemble.playOnce(projectPath, choreoContext(root), {
      sidebarHeader: root.querySelector('[data-topband]'),
      screenRoot: root.querySelector('main#main > :first-child'),
      chatInner: root.querySelector('[data-chat-inner]'),
      tier,
    })
    return () => {
      unjoin()
      tl?.kill()
      frameAssemble.forget(projectPath)
    }
  }, [rootRef, projectPath])
}

/** I8 (host half): warm the scene chunk while the window is idle, so the first Graph surface
 * does not pay the import on click. Only when it is likely to be wanted — not in a test build,
 * not when the Spine band is collapsed, and only when the stored default surface is `graph`. */
function usePrefetchCanvasHost(projectPath: string) {
  useEffect(() => {
    if (import.meta.env.MODE === 'test') return
    if (stageTabStore.spineCollapsed || readSurfaceDefault() !== 'graph') return
    const w = window as Window & {
      requestIdleCallback?: (cb: () => void) => number
      cancelIdleCallback?: (id: number) => void
    }
    let cancelled = false
    const run = () => {
      if (cancelled) return
      void import('../scenes/core/lazyCanvas').then((m) => {
        if (cancelled) return
        ;(m as { prefetchCanvasHost?: () => unknown }).prefetchCanvasHost?.()
      }).catch(() => { /* the chunk arrives on first use instead */ })
    }
    const idle = typeof w.requestIdleCallback === 'function' ? w.requestIdleCallback(run) : null
    const timer = idle === null ? setTimeout(run, 400) : null
    return () => {
      cancelled = true
      if (idle !== null && typeof w.cancelIdleCallback === 'function') w.cancelIdleCallback(idle)
      if (timer !== null) clearTimeout(timer)
    }
  }, [projectPath])
}
