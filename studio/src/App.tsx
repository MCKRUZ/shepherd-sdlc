import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { BoardRow, ClashChoice, CommandCenter, DocumentFocus, FileClash, ProjectStatus, RecentProject, Settings, SprintVerb, SyncState, ToolingReport } from '../shared/types'
import type { Area, NavTarget } from '../shared/nav'
import { BUILD_STAGE_ID, homeFor, targetForBuildView, targetForHome, targetForStage } from '../shared/nav'
import { slateToBoardRow } from '../shared/sprintModel'
import { effectOf, type IntentMatch } from './palette/intents'
import { consoleStore } from './stores/consoleStore'
import { dirtyStore } from './stores/dirtyStore'
import { backlogStore } from './stores/backlogStore'
import { stageTabStore } from './stores/stageTabStore'
import { connectionStore, useConnection } from './stores/connectionStore'
import { chatStore } from './stores/chatStore'
import { Notice, ToastRegion, dismiss, toast } from './ui'
import { motion } from './motion/motion'
import { ProjectKeyProvider } from './motion/projectKey'
import { valueMemory } from './motion/valueMemory'
import { useFocusOnNavigate } from './a11y/focusOnNavigate'
import { announce } from './a11y/LiveAnnouncer'
import { useShortcuts } from './shortcuts/useShortcuts'
import { escOwnedAbove } from './shortcuts/escOwners'
import { CommandPalette } from './palette/CommandPalette'
import { usePaletteIndex, usePreferenceActionHooks } from './palette/usePaletteIndex'
import type { SettingsAnchor } from './palette/types'
import { SceneSlot } from './scenes/core/SceneSlot'
import { AMBIENT_ENABLED } from './scenes/core/sceneDefaults'
import { ToolingIssues, REQUIRED_TOOLS } from './components/ToolingIssues'
import { CodeHostNotice } from './components/CodeHostNotice'
import { ClaudeIssueContext } from './components/ClaudeIssueContext'
import { claudeLacksMessage } from '../shared/claudeContract'
import { NewProjectScreen } from './components/NewProjectScreen'
import { WelcomeScreen } from './components/WelcomeScreen'
import { SetupFlow } from './components/SetupFlow'
import { Frame, type FrameShellHooks } from './components/Frame'
import { ShortcutsHelp } from './components/ShortcutsHelp'
import { LifecycleHome } from './components/LifecycleHome'
import { DocumentView } from './components/DocumentView'
import { BuildBoard } from './components/BuildBoard'
import { SprintHome } from './components/SprintHome'
import { SpecStatusView } from './components/SpecStatusView'
import { OpeningOverlay } from './components/OpeningOverlay'
import { BoardsChanged, BoardsNudge, boardsTargetOf, type BoardsNudgeTarget } from './components/ado/BoardsNudge'

// The rarely visited screens load on first use (studio-observatory.md §9): each is its own chunk,
// so the main chunk a cold start parses stays under its budget. Named exports → `default` shim.
const ClashScreen = lazy(() => import('./components/ClashScreen').then((m) => ({ default: m.ClashScreen })))
const HistoryPanel = lazy(() => import('./components/HistoryPanel').then((m) => ({ default: m.HistoryPanel })))
const HandoffDialog = lazy(() => import('./components/HandoffDialog').then((m) => ({ default: m.HandoffDialog })))
const SettingsScreen = lazy(() => import('./components/SettingsScreen').then((m) => ({ default: m.SettingsScreen })))
const ExplainViews = lazy(() => import('./components/ExplainViews').then((m) => ({ default: m.ExplainViews })))
const FeatureCompleteScreen = lazy(() => import('./components/FeatureCompleteScreen').then((m) => ({ default: m.FeatureCompleteScreen })))
// The omnibar's dialog (togo-command-center.md §3.6): opened by a matched verb, never at rest.
const VerbDialog = lazy(() => import('./components/VerbDialog').then((m) => ({ default: m.VerbDialog })))
// The command center's other screens (§3.2, §3.3, §3.5) — each its own chunk; the sprint home is
// the default in Build and stays in the main chunk.
const Planning = lazy(() => import('./components/planning/Planning').then((m) => ({ default: m.Planning })))
const SpecCard = lazy(() => import('./components/SpecCard/SpecCard').then((m) => ({ default: m.SpecCard })))
const SprintClose = lazy(() => import('./components/SprintClose').then((m) => ({ default: m.SprintClose })))
const SteeringMode = lazy(() => import('./components/SteeringMode').then((m) => ({ default: m.SteeringMode })))

/** The one read model (§2.3), when this build's bridge has it. The main process assembles it;
 * the renderer only asks. Null on a bridge without `getCommandCenter` (an older preload) or when
 * the read itself failed — then every element that reads it shows "no data", never a zero. */
async function readCommandCenter(projectPath: string, refresh = false): Promise<CommandCenter | null> {
  const studio = window.studio as Partial<typeof window.studio>
  if (typeof studio.getCommandCenter !== 'function') return null
  try {
    // `refresh` is "Refresh this screen": main drops its cache for the project and re-reads.
    return await studio.getCommandCenter(projectPath, undefined, refresh || undefined)
  } catch {
    return null
  }
}

/** What a lazy screen shows for the few ms its chunk takes: a bare paragraph, no wrapper — so
 * `main.firstElementChild` is still a screen-shaped root (workflow.spec:191) and nothing styled
 * flashes. Distinct from the app's "Loading…", which every e2e waits on. */
const OPENING = <p className="text-sm text-ink-4">Opening…</p>

type Screen =
  | { kind: 'loading' }
  | { kind: 'toolingIssues'; report: ToolingReport }
  | { kind: 'welcome' }
  | { kind: 'newProject' }
  | { kind: 'settingUp'; projectPath: string }
  | { kind: 'project'; status: ProjectStatus; projectPath: string }

/** A project being opened — or any other blocking, plugin-backed action, such as signing off a
 * phase — what to call it on screen, and when it started, for the clock. `title`/`subtitle` are
 * only needed for the non-opening case; omitted, the overlay uses its own opening-a-project text. */
interface Opening {
  projectName: string
  startedAt: number
  title?: string
  subtitle?: string
}

/** The last folder name of a path, for "Opening token-tracker…". */
function projectName(projectPath: string): string {
  return projectPath.split(/[\/]/).filter(Boolean).pop() ?? projectPath
}

// --- Esc's dirty guard (studio-observatory.md §6.2 Esc row [MF]) ---------------------------------
// The registry itself lives in `stores/dirtyStore.ts`; FieldEditor, HandoffDialog, ChatPanel and
// ClashScreen register there while they hold unsaved work, and `useShortcuts` below asks it.

/** Fallback for a screen that has not registered yet: a text control inside `<main>` that has
 * focus AND text in it is being edited by definition. Narrow on purpose — the chat composer is
 * in an `<aside>`, and a search box empties the moment its filter is cleared. */
function focusedMainFieldHasText(): boolean {
  if (typeof document === 'undefined') return false
  const el = document.activeElement
  if (!(el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement)) return false
  if (!el.closest('main')) return false
  return el.value.trim().length > 0
}

/** Anything open ABOVE the screen owns Esc: the palette and `Dialog`s (portalled to `#overlays`),
 * the `…` menu, a hover card, the OpeningOverlay. Each already closes itself on Esc, so this layer
 * only has to recognise them and step aside — it reports "something is being edited" so
 * `handleEscape` does nothing and the event reaches their own listeners untouched. The selector
 * lives in `shortcuts/escOwners.ts` (one list, tested against the kit's own overlays). */

/** Frame's `useShortcuts` (the palette's) and this one share `window`, and a two-key sequence
 * only works when ONE listener sees both keys: the first to read `g` claims it with
 * `preventDefault`, and the other then ignores the whole chord. Frame has no handlers for the
 * `g` sequences, `[` `]` or back, so App must be the one that reads them — and it mounts AFTER
 * Frame's child effect. Listening in the capture phase puts it first regardless of mount order.
 * Keys App has no handler for fall through to Frame unchanged (no `preventDefault`). */
const CAPTURE_TARGET: Pick<Window, 'addEventListener' | 'removeEventListener'> | null =
  typeof window === 'undefined'
    ? null
    : {
        addEventListener: ((type: string, listener: EventListenerOrEventListenerObject) =>
          window.addEventListener(type, listener, true)) as Window['addEventListener'],
        removeEventListener: ((type: string, listener: EventListenerOrEventListenerObject) =>
          window.removeEventListener(type, listener, true)) as Window['removeEventListener'],
      }

/** The chat composer is the one element outside `<main>` a shortcut focuses. ChatPanel is
 * Frame's; reaching it by its pinned testid keeps App off its props. */
function focusChatComposer(): void {
  document.querySelector<HTMLElement>('[data-testid="chat-composer-input"]')?.focus()
}

/** What the live region says after a navigation (§6.3): the screen's own name, never a count. */
function navigationAnnouncement(args: {
  area: Area
  stages: ProjectStatus['stages']
  stageId: string | undefined
  openDoc: string | null
  showHistory: boolean
  openSpec: BoardRow | null
  handingOff: boolean
}): string {
  const { area, stages, stageId, openDoc, showHistory, openSpec, handingOff } = args
  if (area === 'documents') {
    if (openDoc) {
      const name = openDoc.split(/[\/]/).filter(Boolean).pop() ?? openDoc
      return showHistory ? `History of ${name}` : name
    }
    return stages.find((s) => s.id === stageId)?.display ?? 'Stage'
  }
  if (area === 'build' || area === 'sprint' || area === 'planning') {
    if (openSpec && handingOff) return `Hand off spec ${openSpec.spec}`
    if (openSpec) return `Spec ${openSpec.spec}`
    return area === 'build' ? 'Board' : area === 'planning' ? 'Planning' : 'Sprint home'
  }
  if (area === 'explain') return 'How it is going'
  if (area === 'steering') return 'Steering mode'
  if (area === 'closing') return 'Closing'
  return 'Settings'
}

/** Scroll a Settings section into view once it exists. The Settings chunk is lazy and its sections
 * render after the settings read lands, so the element is not there when the palette row runs;
 * poll briefly rather than guess a delay. The first attempt waits past `useFocusOnNavigate`'s
 * heading focus (260 ms with motion on), which would otherwise scroll back to the top after this
 * had scrolled down. Returns a cancel for a navigation that supersedes the jump. */
function scrollToAnchorWhenMounted(anchor: string): () => void {
  const FIRST_MS = 300
  const EVERY_MS = 100
  const GIVE_UP_MS = 4000
  let cancelled = false
  const startedAt = Date.now()
  const attempt = () => {
    if (cancelled) return
    const el = document.getElementById(anchor)
    if (el) {
      el.scrollIntoView({ block: 'start' })
      // The section's own heading takes focus so a screen reader lands where the eye did.
      const heading = document.getElementById(`${anchor}-title`) ?? el
      if (!heading.hasAttribute('tabindex')) heading.tabIndex = -1
      heading.focus({ preventScroll: true })
      return
    }
    if (Date.now() - startedAt < GIVE_UP_MS) setTimeout(attempt, EVERY_MS)
  }
  const timer = setTimeout(attempt, FIRST_MS)
  return () => { cancelled = true; clearTimeout(timer) }
}

/** The palette, the shortcuts help and the global shortcuts for the screens before a project is
 * open. The index has no stages, so only the actions group exists: preferences, the help, and —
 * on the Welcome screen — New project… / Open folder…, which are the two things that screen does. */
function PreProjectShell({ newProject, openFolder }: { newProject?: () => void; openFolder?: () => void }) {
  const [open, setOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const prefs = usePreferenceActionHooks()
  const openPalette = useCallback(() => { setHelpOpen(false); setOpen(true) }, [])
  const closePalette = useCallback(() => setOpen(false), [])
  const openShortcuts = useCallback(() => { setOpen(false); setHelpOpen(true) }, [])
  const closeShortcuts = useCallback(() => setHelpOpen(false), [])
  const host = useMemo(() => ({
    stages: [],
    currentStageId: null,
    viewedStageId: null,
    readiness: null,
    backlog: { rows: [], slate: [] },
    actions: { ...prefs.hooks, openShortcuts, newProject, openFolder },
    recentIds: [],
    area: null,
    navigate: () => {},
    openSpec: () => {},
    openDocument: () => {},
    openSettings: () => {},
  }), [prefs.hooks, openShortcuts, newProject, openFolder])
  const { entries, recentIds, remember } = usePaletteIndex(host)
  useShortcuts({
    handlers: { openPalette, openShortcuts, cycleTheme: prefs.cycleTheme, toggleMotion: prefs.toggleMotion, toggleDensity: prefs.toggleDensity },
    escLayers: [
      () => { if (!open) return false; setOpen(false); return true },
      () => { if (!helpOpen) return false; setHelpOpen(false); return true },
    ],
  })
  return (
    <>
      <CommandPalette open={open} onClose={closePalette} entries={entries} recentIds={recentIds} onRun={(e) => remember(e.id)} />
      <ShortcutsHelp open={helpOpen} onClose={closeShortcuts} />
    </>
  )
}

/** Toasts need a region to land in; Frame mounts one for a project, this does for the screens
 * before one. A fragment, not a wrapper div, so each screen stays the root it was. The palette
 * and help are portalled dialogs, mounted only while open, so the screen stays the root too. */
function PreProject({ children, newProject, openFolder }: { children: React.ReactNode; newProject?: () => void; openFolder?: () => void }) {
  return (
    <>
      {children}
      <ToastRegion />
      <PreProjectShell newProject={newProject} openFolder={openFolder} />
    </>
  )
}

function AppScreens({ setOpening }: { setOpening: (opening: Opening | null) => void }) {
  const [screen, setScreen] = useState<Screen>({ kind: 'loading' })
  const [recentProjects, setRecentProjects] = useState<RecentProject[]>([])
  const [syncState, setSyncState] = useState<SyncState>({ kind: 'idle', lastPulledAt: null })
  const [pendingClashes, setPendingClashes] = useState<FileClash[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  /** Which stage's home the reader is looking at, from clicking the stage list — undefined
   * defers to the project's current stage, the same default the readiness script itself uses
   * when called with no --phase. */
  const [viewedStageId, setViewedStageId] = useState<string | undefined>(undefined)
  /** Which document is open within the project screen, or null for the stage home. */
  const [openDoc, setOpenDoc] = useState<string | null>(null)
  /** Which field the reader asked to be taken to, when they arrived from a readiness item
   * rather than from the document list. Undefined for an ordinary open. */
  const [openDocFocus, setOpenDocFocus] = useState<DocumentFocus | undefined>(undefined)
  const [showHistory, setShowHistory] = useState(false)
  /** Who is using Studio, for attributing saves, restores and drafts. Taken from the
   * signed-in code-host account, which is the same identity the team roster and approvals
   * already use — rather than inventing a separate Studio-only name to keep in step. */
  const [actor, setActor] = useState('')
  /** Which area of the project is showing. Documents is where spec 0010 lives; Build is
   * spec 0011's board; Sprint is the sprint the team runs on it. Kept here rather than in a
   * router, because there are so few areas. */
  const [area, setArea] = useState<Area>('documents')
  /** The spec whose status is open, and separately whether its hand-off is showing — a
   * hand-off is a decision taken FROM a spec, not a different place in the app. */
  const [openSpec, setOpenSpec] = useState<BoardRow | null>(null)
  const [handingOff, setHandingOff] = useState(false)
  /** The command center's read model (togo-command-center.md §2.3): read once per project open
   * and again after every exit 0 — never on a timer. The shell's chip and the strip's Build
   * station read it; the sprint home runs its own read of the same cached document. */
  const [commandCenter, setCommandCenter] = useState<CommandCenter | null>(null)
  /** The omnibar verb awaiting Confirm (§3.6); the dialog is mounted only while one is. */
  const [verbIntent, setVerbIntent] = useState<IntentMatch | null>(null)
  /** Every match the host builds itself carries the plugin's own `effect` sentence (intents.ts):
   * what the verb WRITES on Done, from the verbs' code — the dialog previews it before Confirm. */
  const withEffect = (m: Omit<IntentMatch, 'effect'>): IntentMatch => ({ ...m, effect: effectOf(m.intent) })
  /** Bumped after every exit 0 this component learns of (the omnibar's dialog, a needs-you action,
   * "Refresh this screen") — AFTER the command center has been re-read, so the screens' own
   * re-reads find the refreshed document. Nothing on screen moves before that (§2.4). */
  const [refreshKey, setRefreshKey] = useState(0)
  /** The spec this person just handed off with exit 0: the sprint home plays the baton once the
   * refreshed read holds it (§4 #30). */
  const [handedOff, setHandedOff] = useState<string | null>(null)
  /** What this person just changed that the board mirrors (a spec verb, a hand-off, a decision): one nudge, drawn at the
   * top of the screen until it is dismissed or the plan it led to was applied. Setting it asks the board NOTHING — every
   * read is a click inside the nudge — and it is forgotten with the project it was set for. */
  const [boardsNudge, setBoardsNudge] = useState<BoardsNudgeTarget | null>(null)
  const nudgeProject = screen.kind === 'project' ? screen.projectPath : null
  useEffect(() => { setBoardsNudge(null) }, [nudgeProject])
  /** The control that opened the spec card (a lane card, a Refining row), so Back / Esc hand focus
   * back to it when the home returns (§3.3). */
  const [specOpener, setSpecOpener] = useState<{ spec: string; where: 'lane' | 'refining'; seq: number } | null>(null)
  const openSeq = useRef(0)
  /** Where steering mode was entered from: `Esc` leaves, back to that screen (§3.5). */
  const steeringFrom = useRef<Area>('sprint')
  // The spec card opens at the top of <main>, wherever the home was scrolled to.
  useEffect(() => {
    if (openSpec && (area === 'sprint' || area === 'planning')) document.getElementById('main')?.scrollTo({ top: 0 })
  }, [openSpec, area])
  const areaRef = useRef<Area>('documents')
  /** A Settings section the palette asked for; scrolled to once Settings has mounted it. */
  const [pendingAnchor, setPendingAnchor] = useState<SettingsAnchor | null>(null)
  /** The last tooling report, kept for one derived fact: whether the installed Claude Code
   * accepts every flag Studio emits (studio-improvements F1). A missing tool blocks opening a
   * project (below); a missing FLAG does not — the project is still readable — it disables the
   * model controls with the reason, through ClaudeIssueContext. */
  const [tooling, setTooling] = useState<ToolingReport | null>(null)
  const claudeIssue = useMemo(() => {
    const missing = tooling?.claude.missingFlags ?? []
    return missing.length > 0 ? claudeLacksMessage(tooling?.claude.version, missing) : null
  }, [tooling])

  /** What the main process established about the open project's code host and its CLI
   * (code-host providers, Wave 7). Read once a project opens; the renderer never probes. The
   * banner below and the Settings rows read it; a missing CLI never blocks opening (D4). Read
   * from the store, not a second useState, so a typed sign-in made in Settings reaches the banner. */
  const connection = useConnection()
  /** Projects whose code-host banner was dismissed this session — per project, so switching to
   * one with a different problem shows that one's sentence. */
  const [dismissedHostNotice, setDismissedHostNotice] = useState<ReadonlySet<string>>(() => new Set())

  const refreshTooling = useCallback(async () => {
    const report = await window.studio.detectTooling()
    setTooling(report)
    // gh and az never block opening a project (code-host providers, D4): what a missing
    // code-host CLI costs is said per feature from ConnectionInfo.cli once a project is open.
    const allFound = REQUIRED_TOOLS.every((k) => report[k].found)
    if (!allFound) {
      setScreen({ kind: 'toolingIssues', report })
      return false
    }
    return true
  }, [])

  const loadRecent = useCallback(async () => {
    const settings: Settings = await window.studio.getSettings()
    setRecentProjects(settings.recentProjects)
  }, [])

  useEffect(() => {
    // The entries live in `consoleStore`, not in this component's state: an entry arriving here
    // used to re-render the whole shell (Sidebar, the open screen, ChatPanel) roughly every 2s on
    // the Workflow tab. Now only the Console panel subscribes. The store keeps the same cap the
    // main process's own log has (see consoleLog.ts) and replaces a streaming command's interim
    // row by id. This component still owns the one IPC subscription.
    window.studio.getConsoleLog().then(consoleStore.replaceAll)
    return window.studio.onConsoleEntry((entry) => consoleStore.append(entry))
  }, [])

  useEffect(() => window.studio.onSyncState(setSyncState), [])

  // Pulling (including on the background timer, whose result the renderer never otherwise
  // sees) can surface clashes at any time — fetch the current list whenever the sync
  // indicator reports some are pending, so the clash screen has real data to show.
  const clashCount = syncState.kind === 'clashes' ? syncState.count : null
  const openProjectPath = screen.kind === 'project' ? screen.projectPath : null
  useEffect(() => {
    if (openProjectPath === null || clashCount === null) return
    window.studio.getPendingClashes(openProjectPath).then(setPendingClashes)
  }, [clashCount, openProjectPath])

  useEffect(() => {
    refreshTooling().then((ok) => {
      if (ok) {
        loadRecent().then(() => setScreen({ kind: 'welcome' }))
      }
    })
  }, [refreshTooling, loadRecent])

  const openPath = useCallback(async (projectPath: string) => {
    setError(null)
    // Opening reads the project through the plugin and can take seconds. The overlay goes up
    // before the first await and comes down in `finally`, so it can neither be missed nor
    // strand the window behind it if the open throws.
    setOpening({ projectName: projectName(projectPath), startedAt: Date.now() })
    try {
      const result = await window.studio.openProject(projectPath)
      if (!result.hasProject) {
        valueMemory.clear()
        setScreen({ kind: 'settingUp', projectPath })
        return
      }
      if (result.status) {
        // A different project is a different set of facts: no counter may tween from the number
        // the last project showed (§4 #11). Belt and braces with the per-project id scoping in
        // `useCountUp` — this clears the memory, that keeps the ids apart even if it did not.
        valueMemory.clear()
        // The home is chosen ONCE per open (togo-command-center.md §1): the sprint home iff the
        // project is in Build AND the plugin declares `sprint-status`; the lifecycle home
        // otherwise. The capabilities come from the command-center read, awaited here so the
        // choice is made on facts, not on a guess that a later read would overturn.
        const cc = await readCommandCenter(projectPath)
        const currentStageId = result.status.stages.find((s) => s.stage_state === 'current')?.id ?? result.status.current_phase?.id ?? null
        const home = homeFor(result.status, cc?.sprint.data ? { hasData: cc.sprint.data.hasData } : null, cc?.capabilities ?? null)
        const landing = targetForHome(home, currentStageId)
        setCommandCenter(cc)
        setScreen({ kind: 'project', status: result.status, projectPath })
        setOpenDoc(null)
        setOpenSpec(null)
        setHandingOff(false)
        setVerbIntent(null)
        setArea(landing.area)
        // The lifecycle home opens on the project's current stage — the same default as before.
        setViewedStageId(undefined)
        connectionStore.clear()
        window.studio.getConnectionInfo(projectPath).then((info) => {
          setActor(info.account ?? '')
          // Screens that read the host (BuildBoard, HandoffDialog, PipelineEvidencePanel…) take it
          // from the store rather than props, so one publish here reaches all of them.
          connectionStore.set(info)
        })
        loadRecent()
      } else {
        setError(result.error ?? "Could not read this project's status.")
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setOpening(null)
    }
  }, [loadRecent, setOpening])

  const handlePickFolder = useCallback(async () => {
    const folder = await window.studio.pickFolder()
    if (folder) await openPath(folder)
  }, [openPath])

  // Stable so the pre-project palette's host (memoised on it) is not rebuilt every render.
  const startNewProject = useCallback(() => { setError(null); setScreen({ kind: 'newProject' }) }, [])

  // After a phase sign-off the sidebar's stage list is stale — current_phase moved, but the
  // status this screen holds was read before that happened. Re-reads it in place, without
  // resetting the open document or view the way a fresh openPath would.
  const refreshStatus = useCallback(async () => {
    if (screen.kind !== 'project') return
    const result = await window.studio.openProject(screen.projectPath)
    if (result.hasProject && result.status) {
      setScreen({ kind: 'project', status: result.status, projectPath: screen.projectPath })
    }
  }, [screen])

  /** After an exit 0 (§2.4): re-run the P-class reads this component holds — the command center
   * and the status — never before. Nothing on screen moves until both have landed. `refresh` is
   * the explicit "Refresh this screen": main drops its cache first. The screens re-read on
   * `refreshKey`, bumped only once the document is in hand. */
  const refreshCommandCenter = useCallback(async (refresh = false) => {
    if (screen.kind !== 'project') return
    setCommandCenter(await readCommandCenter(screen.projectPath, refresh))
    setRefreshKey((k) => k + 1)
  }, [screen])

  const handleOverride = useCallback(
    async (kind: 'claude' | 'uv' | 'pluginScripts' | 'git' | 'gh' | 'az', path: string) => {
      await window.studio.setToolOverride(kind, path)
      await refreshTooling().then((ok) => {
        if (ok) { connectionStore.clear(); loadRecent().then(() => setScreen({ kind: 'welcome' })) }
      })
    },
    [refreshTooling, loadRecent],
  )

  // Stable across renders so the memoised Sidebar (see Frame.tsx) is not re-rendered by a new
  // function identity every time something unrelated in this component changes. Everything it
  // touches is a state setter, which React already keeps stable.
  const handleNavigate = useCallback((target: NavTarget) => {
    // Steering remembers the screen it was entered from, so `Esc` returns there (§3.5).
    if (target.area === 'steering' && areaRef.current !== 'steering') steeringFrom.current = areaRef.current
    setArea(target.area)
    if (target.area === 'documents') {
      setOpenDoc(null)
      setShowHistory(false)
      setViewedStageId(target.stageId)
    }
    if (target.area === 'build' || target.area === 'sprint' || target.area === 'planning') {
      // Choosing Board, Home or Planning again returns to the list, not to whichever spec was open.
      setOpenSpec(null)
      setSpecOpener(null)
      setHandingOff(false)
    }
  }, [])

  /** A spec opened from the sprint home or planning (§3.3): remembers the opener so focus can
   * return to it — a lane card, or a Refining row's "refine in place →" — and opens the card. */
  const openSpecFromHome = useCallback((row: BoardRow) => {
    const el = typeof document !== 'undefined' ? (document.activeElement as HTMLElement | null) : null
    const where = el?.closest('[data-lane-card]') ? 'lane' : el?.closest('[data-testid="refining-row"]') ? 'refining' : null
    openSeq.current += 1
    setSpecOpener(where ? { spec: row.spec, where, seq: openSeq.current } : null)
    setHandingOff(false)
    setOpenSpec(row)
  }, [])

  /** `h` on a lane card, the facts rail's slot, the omnibar's "hand NNNN to NAME": the sprint
   * layer's hand-off (`sprint.py handoff`, the baton), through the dialog — the recipient is
   * picked from the roster there; no free text reaches `--to`. */
  const openSprintVerb = useCallback((verb: SprintVerb, row: BoardRow) => {
    if (verb === 'handoff') {
      // The row's own `checker` (spec frontmatter, set by `spec_transition.py assign`) is the
      // recipient the dialog opens with — a plugin field, so the preview reads `--to @sam-k`
      // rather than `<to?>` (cockpit.spec `h`). A row with no checker opens with the picker.
      const checker = row.checker?.trim() || ''
      setVerbIntent(withEffect({
        intent: { kind: 'sprint', request: { verb: 'handoff', spec: row.spec, to: checker }, ...(checker ? { recipient: { handle: checker } } : {}) },
        title: `Hand off ${row.spec}`,
        subtitle: 'sprint.py handoff — the baton passes to a person on the roster; the plugin checks they are a person and the spec is in the sprint',
      }))
    } else if (verb === 'ack') {
      setVerbIntent(withEffect({ intent: { kind: 'sprint', request: { verb: 'ack', spec: row.spec } }, title: `Acknowledge the hand-off of ${row.spec}`, subtitle: 'sprint.py ack — recorded against you'}))
    } else if (verb === 'unslate') {
      setVerbIntent(withEffect({ intent: { kind: 'sprint', request: { verb: 'unslate', spec: row.spec, reason: '' } }, title: `Take ${row.spec} off the slate`, subtitle: 'sprint.py unslate — the reason goes in the ledger line'}))
    }
  }, [])

  /** The `new` sprint dialog; `suggestedId` ("S09" after "S08") pre-fills the id field only. */
  const openNewSprint = useCallback((suggestedId?: string) => {
    setVerbIntent(withEffect({ intent: { kind: 'new-sprint', sprint: suggestedId }, title: 'New sprint', subtitle: 'sprint.py new — id, goal, start, length and target, recorded against you'}))
  }, [])

  /** "pull NNNN" on a slated, READY spec (and a needs-you hand-off row): the existing hand-off
   * flow for that spec, from the rows the Board or the sprint already fetched. */
  const openHandOffFor = useCallback((specId: string) => {
    const row = backlogStore.rows.find((r) => r.spec === specId)
      ?? (() => { const s = backlogStore.slate.find((r) => r.id === specId); return s ? slateToBoardRow(s) : undefined })()
    if (!row) { handleNavigate({ area: 'build' }); return }
    setArea((a) => (a === 'sprint' ? a : 'build'))
    setOpenSpec(row)
    setHandingOff(true)
  }, [handleNavigate])

  // --- palette landings: the row opens the item, not just its area --------------------------------

  /** A spec by path, from what the Board or the Sprint already fetched (`backlogStore`); a path
   * neither holds lands on the Board, which re-reads and will list it. */
  const openSpecByPath = useCallback((relPath: string) => {
    const row = backlogStore.rows.find((r) => r.path === relPath)
      ?? (() => { const s = backlogStore.slate.find((r) => r.relPath === relPath); return s ? slateToBoardRow(s) : undefined })()
    if (!row) { handleNavigate({ area: 'build' }); return }
    // A spec opened while the Sprint shows keeps Sprint behind it, as its own rows do.
    setArea((a) => (a === 'sprint' ? a : 'build'))
    setHandingOff(false)
    setOpenSpec(row)
  }, [handleNavigate])

  const openDocumentAt = useCallback((relPath: string, stageId: string | undefined) => {
    setArea('documents')
    setViewedStageId(stageId)
    setShowHistory(false)
    setOpenDocFocus(undefined)
    setOpenDoc(relPath)
  }, [])

  const openSettingsAt = useCallback((anchor: SettingsAnchor) => {
    handleNavigate({ area: 'settings' })
    setPendingAnchor(anchor)
  }, [handleNavigate])

  useEffect(() => {
    if (pendingAnchor === null || area !== 'settings') return
    const cancel = scrollToAnchorWhenMounted(pendingAnchor)
    // Cleared once scheduled so the same row picked twice scrolls twice.
    setPendingAnchor(null)
    return cancel
  }, [pendingAnchor, area])

  // --- shell wiring: shortcuts, Esc back, focus, announcement -------------------------------------

  const inProject = screen.kind === 'project'
  areaRef.current = area
  const stages = inProject ? screen.status.stages : null
  const currentStageId = stages?.find((s) => s.stage_state === 'current')?.id
  // Which screen is actually in <main>: the digit shortcuts and the Spine rows exist only on the
  // stage home, the Sprint surface toggle only on the Sprint list.
  const stageHomeShowing = inProject && area === 'documents' && openDoc === null && !(pendingClashes && pendingClashes.length > 0)
  const sprintShowing = inProject && area === 'sprint' && openSpec === null
  // The stage the keyboard is "at": the viewed one on Documents, Build for its four views, the
  // project's current one on Settings (which lights no stage). `[` / `]` step from here.
  const keyboardStageId = area === 'documents' || area === 'settings' ? (viewedStageId ?? currentStageId) : BUILD_STAGE_ID

  // Esc's last layer: the same `onBack` / `onClose` the screens' own Back buttons call, in the
  // order the screens stack (hand-off over spec; history over document). Undefined when the
  // list or stage home is showing — there is nothing behind it to go back to.
  const back = useMemo<(() => void) | undefined>(() => {
    if (!inProject) return undefined
    if (area === 'build' || area === 'sprint' || area === 'planning') {
      if (handingOff) return () => setHandingOff(false)
      if (openSpec) return () => setOpenSpec(null)
      return undefined
    }
    // Steering mode: Esc leaves (§3.5), back to the screen it was entered from.
    if (area === 'steering') return () => setArea(steeringFrom.current)
    if (area === 'documents' && openDoc) {
      return showHistory ? () => setShowHistory(false) : () => setOpenDoc(null)
    }
    return undefined
  }, [inProject, area, handingOff, openSpec, openDoc, showHistory])

  const openIntent = useCallback((match: IntentMatch) => setVerbIntent(match), [])
  // "Refresh this screen" (the palette): the one explicit re-read — main drops its cache, then
  // every screen re-reads. On the stage home Frame routes the row to the readiness refresh instead.
  const refreshScreen = useCallback(() => { void refreshCommandCenter(true) }, [refreshCommandCenter])
  const shell = useMemo<FrameShellHooks>(() => ({
    openSpec: openSpecByPath,
    openDocument: openDocumentAt,
    openSettings: openSettingsAt,
    back,
    stageHomeShowing,
    sprintShowing,
    refreshScreen,
    openIntent,
    newProject: startNewProject,
    openFolder: handlePickFolder,
  }), [openSpecByPath, openDocumentAt, openSettingsAt, back, stageHomeShowing, sprintShowing, refreshScreen, openIntent, startNewProject, handlePickFolder])

  useShortcuts({
    handlers: {
      stageTab: (tab) => stageTabStore.request(tab),
      goBuildView: (view) => handleNavigate(targetForBuildView(view)),
      // `g l` the lifecycle home (`g s`, the sprint home, arrives as the `sprint` build view).
      goHome: (home) => handleNavigate(targetForHome(home, currentStageId ?? null)),
      steering: () => handleNavigate({ area: 'steering' }),
      goStage: (stageId) => { if (stages?.some((s) => s.id === stageId)) handleNavigate(targetForStage(stageId)) },
      stepStage: (delta) => {
        if (!stages || keyboardStageId === undefined) return
        const index = stages.findIndex((s) => s.id === keyboardStageId)
        const next = index >= 0 ? stages[index + delta] : undefined
        // The ends are ends: no wrap from Close back to Phase 0.
        if (next) handleNavigate(targetForStage(next.id))
      },
      // ⌘⇧C on a screen whose chat is folded (the sprint home and planning start that way,
      // chatStore) unfolds it first and focuses the composer once the aside has re-rendered —
      // folded, the composer is `display:none` and refuses focus, so the shortcut would do nothing.
      focusChat: () => {
        if (chatStore.isCollapsed(area)) {
          chatStore.setCollapsed(area, false)
          requestAnimationFrame(focusChatComposer)
        } else {
          focusChatComposer()
        }
      },
    },
    scopes: stageHomeShowing ? ['project', 'stageHome'] : ['project'],
    onBack: back,
    isDirty: () => escOwnedAbove() || dirtyStore.anyDirty() || focusedMainFieldHasText(),
    enabled: inProject,
    target: CAPTURE_TARGET,
  })

  // One string that changes exactly when the screen does (not when it re-renders): what §6.3
  // moves focus on and what the live region announces. Null before a project is open, so the
  // welcome screen keeps whatever focus it had.
  const navKey = inProject
    ? [area, viewedStageId ?? '', openDoc ?? '', showHistory, openSpec?.spec ?? '', handingOff].join('|')
    : null
  // Focus waits for the screen's enter choreography (§4 #3, 240 ms) so it lands on a heading
  // that has finished arriving; with motion off (every test) it moves at once.
  useFocusOnNavigate(navKey, { delayMs: motion.enabled() ? 260 : 0 })
  useEffect(() => {
    if (navKey === null || !stages) return
    announce(navigationAnnouncement({ area, stages, stageId: keyboardStageId, openDoc, showHistory, openSpec, handingOff }))
    // `navKey` is the one dependency on purpose: the announcement is about a navigation, and the
    // other values are the parts it is made of.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navKey])

  // Before a project is open there is no `<main>` to hold a banner, so an error is a toast —
  // sticky, because "could not open" must outlive six seconds. One toast per distinct message
  // (a screen change while the same error stands must not repeat it), dismissed the moment the
  // error clears so a stale failure never follows the reader into the project they then opened.
  const errorToast = useRef<{ text: string; id: string } | null>(null)
  useEffect(() => {
    if (error === null) {
      if (errorToast.current) dismiss(errorToast.current.id)
      errorToast.current = null
      return
    }
    if (inProject || errorToast.current?.text === error) return
    if (errorToast.current) dismiss(errorToast.current.id)
    errorToast.current = { text: error, id: toast({ tone: 'error', title: error, sticky: true }) }
  }, [error, inProject])

  if (screen.kind === 'loading') {
    return (
      <div className="relative flex h-screen flex-col items-center justify-center gap-4 bg-surface-0">
        {/* Pure decoration, so test builds never mount it; the text is what every e2e waits for. */}
        {AMBIENT_ENABLED && <SceneSlot id="ambient" data={null} onActivate={() => {}} />}
        {/* The first paint already carries the mark; the opening overlay (G1-5) then draws it.
            Static here — motion is evidence, and nothing has happened yet. Inline SVG (CSP). */}
        <svg viewBox="0 0 64 64" aria-hidden="true" className="relative h-10 w-10 text-accent-600">
          <rect x="17" y="9" width="30" height="7" rx="3.5" fill="currentColor" />
          <circle cx="32" cy="38.5" r="17.5" fill="currentColor" />
        </svg>
        <span className="relative text-sm text-ink-3">Loading…</span>
      </div>
    )
  }

  if (screen.kind === 'toolingIssues') {
    return <ToolingIssues report={screen.report} onOverride={handleOverride} />
  }

  if (screen.kind === 'newProject') {
    return (
      <PreProject>
        <NewProjectScreen
          onCancel={() => { connectionStore.clear(); setScreen({ kind: 'welcome' }) }}
          // The new folder has no .sdlc yet, so opening it lands in the same setup wizard an
          // existing folder without one goes through — one path, not a second one for new projects.
          onCreated={(projectPath) => { void openPath(projectPath) }}
        />
      </PreProject>
    )
  }

  if (screen.kind === 'settingUp') {
    return (
      <PreProject>
        <SetupFlow
          projectPath={screen.projectPath}
          onCancel={() => { connectionStore.clear(); setScreen({ kind: 'welcome' }) }}
          onConfirm={async (profileId) => {
            const result = await window.studio.runSetup(screen.projectPath, profileId)
            if (!result.ok) {
              setError(result.error ?? 'Setting up the project failed.')
              return
            }
            await openPath(screen.projectPath)
          }}
        />
      </PreProject>
    )
  }

  if (screen.kind === 'project') {
    if (pendingClashes && pendingClashes.length > 0) {
      const { projectPath } = screen
      return (
        <ProjectKeyProvider value={projectPath}>
        <Suspense fallback={OPENING}>
        <ClashScreen
          clashes={pendingClashes}
          onResolve={async (filePath, sectionKey, choice: ClashChoice, combinedText) => {
            const result = await window.studio.resolveClash(projectPath, filePath, sectionKey, choice, combinedText)
            if (!result.ok) {
              setError(result.error ?? 'Could not resolve this clash.')
              return
            }
            const remaining = await window.studio.getPendingClashes(projectPath)
            setPendingClashes(remaining)
          }}
          onCombine={async (localText, remoteText) => {
            const result = await window.studio.combineWithClaude(projectPath, localText, remoteText)
            if ('error' in result) throw new Error(result.error)
            return result.combined
          }}
          onDone={() => setPendingClashes(null)}
        />
        </Suspense>
        </ProjectKeyProvider>
      )
    }
    const { projectPath, status } = screen
    return (
      <ProjectKeyProvider value={projectPath}>
      <ClaudeIssueContext.Provider value={claudeIssue}>
      <BoardsChanged.Provider value={setBoardsNudge}>
      <Frame
        status={status}
        projectPath={projectPath}
        syncState={syncState}
        area={area}
        viewedStageId={viewedStageId}
        actor={actor}
        commandCenter={commandCenter}
        steering={area === 'steering'}
        onNavigate={handleNavigate}
        shell={shell}
      >
        {/* The omnibar's dialog (§3.6): mounted only while a verb awaits Confirm; portalled, so
            `<main>`'s first child stays the screen. After an exit 0 the reads this component holds
            are re-run — never before. */}
        {verbIntent && (
          <Suspense fallback={null}>
            <VerbDialog
              projectPath={projectPath}
              match={verbIntent}
              roster={(commandCenter?.roster.data?.people ?? []).map((p) => ({ handle: p.handle, name: p.name ?? p.handle, team: p.team }))}
              capabilities={commandCenter?.capabilities ?? null}
              onClose={() => setVerbIntent(null)}
              onDone={() => {
                // The baton plays for THIS person's hand-off only, once the refreshed read holds it.
                if (verbIntent.intent.kind === 'sprint' && verbIntent.intent.request.verb === 'handoff') setHandedOff(verbIntent.intent.request.spec)
                const changed = boardsTargetOf(verbIntent.intent)
                if (changed) setBoardsNudge(changed)   // a verb that names nothing leaves the standing nudge alone
                void refreshCommandCenter(); void refreshStatus()
              }}
              onHandOff={openHandOffFor}
              onNavigate={handleNavigate}
            />
          </Suspense>
        )}
        {/* Inline, never also a toast (§6.6): a hard error stays where the reader can re-read it.
            Rendered only while one stands, so the screen root is still `<main>`'s first child. */}
        {error && (
          <Notice tone="error" role="alert" className="mb-4">
            {error}
          </Notice>
        )}
        {/* The Boards nudge (B6-P3): what changed here that the board has not heard, said once, with every read a click
            inside it. Rendered only while one stands (and the Boards block was read), so the screen root is still
            `<main>`'s first child otherwise. */}
        {boardsNudge && (
          <BoardsNudge
            target={boardsNudge}
            projectPath={projectPath}
            ado={commandCenter?.ado}
            capabilities={commandCenter?.capabilities}
            actor={commandCenter?.actor ?? null}
            steering={area === 'steering'}
            onDismiss={() => setBoardsNudge(null)}
          />
        )}
        {/* Non-blocking (D4): the project is open; this says what its code-host CLI cannot do
            right now, in the §7.1 sentence. Same placement rule as the error above — rendered
            only while there is something to say and not yet dismissed. The Board and a spec
            page carry their own host notice, so the banner steps aside there: one sentence per screen. */}
        {!dismissedHostNotice.has(projectPath) && area !== 'build' && area !== 'steering' && !openSpec && (
          <CodeHostNotice
            connection={connection}
            onDismiss={() => setDismissedHostNotice((prev) => new Set(prev).add(projectPath))}
          />
        )}
        {area === 'closing' ? (
          // Closing (§3.5): the sprint's close screen above the unchanged FeatureCompleteScreen
          // while a sprint is active (the command center's own read says so); the declaration
          // screen alone otherwise.
          <Suspense fallback={OPENING}>
            {commandCenter?.sprint.data?.sprint ? (
              <SprintClose projectPath={projectPath} refreshKey={refreshKey} onNewSprint={openNewSprint}>
                <FeatureCompleteScreen
                  projectPath={projectPath}
                  actor={actor}
                  status={status}
                  onNavigate={handleNavigate}
                  buildStage={status.stages.find((s) => s.id === 'build') ?? null}
                  embedded
                />
              </SprintClose>
            ) : (
              <FeatureCompleteScreen
                projectPath={projectPath}
                actor={actor}
                status={status}
                onNavigate={handleNavigate}
                buildStage={status.stages.find((s) => s.id === 'build') ?? null}
              />
            )}
          </Suspense>
        ) : area === 'steering' ? (
          // Steering mode (§3.5): the read-only view of "How it is going" for a committee. The
          // Frame hides the chat and the console and withdraws the omnibar's verbs; the screen
          // has no write control of its own; `Esc` returns to the screen it was entered from.
          <Suspense fallback={OPENING}>
            <SteeringMode projectPath={projectPath} sprintId={commandCenter?.sprint.data?.sprint?.id ?? null} onExit={() => setArea(steeringFrom.current)} />
          </Suspense>
        ) : area === 'explain' ? (
          <Suspense fallback={OPENING}><ExplainViews projectPath={projectPath} /></Suspense>
        ) : area === 'settings' ? (
          <Suspense fallback={OPENING}><SettingsScreen projectPath={projectPath} actor={actor} connection={connection} /></Suspense>
        ) : area === 'build' || area === 'sprint' || area === 'planning' ? (
          // A spec opened from the sprint's slate is the same spec view the board opens, and
          // Back returns to wherever it was opened from.
          handingOff && openSpec ? (
            <Suspense fallback={OPENING}>
              <HandoffDialog
                projectPath={projectPath}
                row={openSpec}
                onClose={() => setHandingOff(false)}
                onHandedOff={() => {
                  // Back to the board, and forget the spec — its row is now stale, and the
                  // board re-reads on mount rather than showing what used to be true.
                  setBoardsNudge({ kind: 'spec', id: openSpec.spec })
                  setHandingOff(false)
                  setOpenSpec(null)
                }}
              />
            </Suspense>
          ) : openSpec && area === 'build' ? (
            // One object, one screen (§3.3): the Board's row opens the same spec card the lanes
            // open, with the old view's facts rail and neighbourhood folded into it. The legacy
            // SpecStatusView remains only for a plugin whose command-center read never landed.
            commandCenter ? (
              <Suspense fallback={OPENING}>
                <SpecCard
                  key={openSpec.spec}
                  projectPath={projectPath}
                  row={openSpec}
                  roster={commandCenter.roster.data?.people ?? null}
                  capabilities={commandCenter.capabilities}
                  actor={commandCenter.actor}
                  onBack={() => setOpenSpec(null)}
                  onHandOff={() => setHandingOff(true)}
                  onVerb={openSprintVerb}
                  // I7: a neighbour opens in this same card (the key remounts it); Back still
                  // returns to the Board.
                  onOpenSpec={(next) => {
                    setHandingOff(false)
                    setOpenSpec(next)
                  }}
                />
              </Suspense>
            ) : (
              <SpecStatusView
                key={openSpec.spec}
                projectPath={projectPath}
                row={openSpec}
                capabilities={undefined}
                actor={null}
                onVerb={openSprintVerb}
                onBack={() => setOpenSpec(null)}
                onHandOff={() => setHandingOff(true)}
                onOpenSpec={(next) => {
                  setHandingOff(false)
                  setOpenSpec(next)
                }}
              />
            )
          ) : area === 'sprint' || area === 'planning' ? (
            // The sprint home (§3.1) or planning (§3.2), with the spec card (§3.3) opened IN PLACE
            // over it: the home stays mounted beneath — out of flow, invisible and inert while the
            // card shows — so Back / Esc return to the very DOM that opened it and the opener takes
            // focus again at once, with no re-read. `h` and the slate's slots open the dialog; every
            // write re-reads before anything moves.
            <div className="relative">
              <div className={openSpec ? 'invisible absolute inset-x-0 top-0 h-0 overflow-hidden' : undefined} inert={openSpec ? true : undefined} aria-hidden={openSpec ? true : undefined}>
                {area === 'planning' ? (
                  <Suspense fallback={OPENING}>
                    <Planning projectPath={projectPath} onOpenSpec={openSpecFromHome} onNewSprint={() => openNewSprint()} onIntent={openIntent} refreshKey={refreshKey} />
                  </Suspense>
                ) : (
                  <SprintHome
                    projectPath={projectPath}
                    onOpenSpec={openSpecFromHome}
                    onHandOff={(row) => openSprintVerb('handoff', row)}
                    onNewSprint={() => openNewSprint()}
                    handedOff={handedOff}
                    refreshKey={refreshKey}
                    focusBack={openSpec ? null : specOpener}
                  />
                )}
              </div>
              {openSpec && (
                <Suspense fallback={OPENING}>
                  <SpecCard
                    key={openSpec.spec}
                    projectPath={projectPath}
                    row={openSpec}
                    roster={commandCenter?.roster.data?.people ?? null}
                    capabilities={commandCenter?.capabilities}
                    actor={commandCenter?.actor ?? null}
                    onBack={() => setOpenSpec(null)}
                    onHandOff={() => setHandingOff(true)}
                    onVerb={openSprintVerb}
                    onOpenSpec={(next) => { setHandingOff(false); setOpenSpec(next) }}
                  />
                </Suspense>
              )}
            </div>
          ) : (
            <BuildBoard
              projectPath={projectPath}
              account={actor || null}
              onOpenSpec={(row) => {
                setHandingOff(false)
                setOpenSpec(row)
              }}
            />
          )
        ) : openDoc && showHistory ? (
          <Suspense fallback={OPENING}>
            <HistoryPanel
              projectPath={projectPath}
              relPath={openDoc}
              actor={actor}
              onClose={() => setShowHistory(false)}
              // A restore rewrites the file, so the open document is stale — close back to the
              // document, which re-reads it, rather than showing content that no longer matches.
              onRestored={() => setShowHistory(false)}
            />
          </Suspense>
        ) : openDoc ? (
          <DocumentView
            key={openDoc}
            projectPath={projectPath}
            relPath={openDoc}
            actor={actor}
            focus={openDocFocus}
            onBack={() => setOpenDoc(null)}
            onShowHistory={() => setShowHistory(true)}
            onOpenDocument={(next) => openDocumentAt(next, viewedStageId)}
          />
        ) : (
          // The lifecycle home (§3.4): StageHome with the Today column beside it.
          <LifecycleHome
            projectPath={projectPath}
            stageId={viewedStageId}
            status={status}
            commandCenter={commandCenter}
            onNavigate={handleNavigate}
            actor={actor}
            setOpening={setOpening}
            onSignedOff={() => { void refreshStatus(); void refreshCommandCenter() }}
            onBoardPulled={() => { void refreshCommandCenter() }}
            onGoToClosing={() => setArea('closing')}
            onOpenDocument={(relPath, focus) => {
              setShowHistory(false)
              setOpenDocFocus(focus)
              setOpenDoc(relPath)
            }}
            onNeedsYou={(item) => {
              // One action per item (§2.3): the verb the item names, through the dialog.
              if (item.kind === 'ack' && item.spec) setVerbIntent(withEffect({ intent: { kind: 'sprint', request: { verb: 'ack', spec: item.spec } }, title: `ack ${item.spec}`, subtitle: item.text}))
              else if (item.kind === 'confirm-tier' && item.spec) {
                const row = backlogStore.rows.find((r) => r.spec === item.spec)
                if (row) setVerbIntent(withEffect({ intent: { kind: 'confirm-tier', spec: row.spec, path: row.path }, title: `confirm tier ${row.spec}`, subtitle: item.text}))
                else handleNavigate({ area: 'sprint' })
              } else if (item.kind === 'review' && item.spec) openSpecByPath(backlogStore.rows.find((r) => r.spec === item.spec)?.path ?? '')
              else handleNavigate({ area: 'sprint' })
            }}
          />
        )}
      </Frame>
      </BoardsChanged.Provider>
      </ClaudeIssueContext.Provider>
      </ProjectKeyProvider>
    )
  }

  return (
    <PreProject newProject={startNewProject} openFolder={handlePickFolder}>
      <WelcomeScreen
        recentProjects={recentProjects}
        onPickFolder={handlePickFolder}
        onNewProject={startNewProject}
        onOpenRecent={openPath}
      />
    </PreProject>
  )
}

/** Holds the "a project is opening" state above every screen, so the overlay covers whichever
 * screen is showing — welcome, set-up, or a project being reopened. */
function App() {
  const [opening, setOpening] = useState<Opening | null>(null)
  return (
    <>
      <AppScreens setOpening={setOpening} />
      {opening && (
        <OpeningOverlay
          projectName={opening.projectName}
          startedAt={opening.startedAt}
          title={opening.title}
          subtitle={opening.subtitle}
        />
      )}
    </>
  )
}

export default App
