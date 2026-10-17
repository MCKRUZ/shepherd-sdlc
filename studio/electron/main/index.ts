import { app, BrowserWindow, dialog, ipcMain, screen, shell } from 'electron'
import { MIN_HEIGHT, MIN_WIDTH, firstOpenBounds, fitSavedBounds, readSavedBounds, writeSavedBounds, zoomFor } from './windowBounds'

// A device scale forced for the production screenshot capture (`SHOT_SCALE=2` → the guide's
// images render at two device pixels per CSS pixel). Chromium reads this switch before the app
// is ready, so it is appended here, at load; macOS ignores the same switch on the command line.
if (process.env.TOGO_DEVICE_SCALE) app.commandLine.appendSwitch('force-device-scale-factor', process.env.TOGO_DEVICE_SCALE)
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import os from 'node:os'
import { detectAllTooling, type DetectAllToolingResult } from './tooling'
import { getConsoleLog, onConsoleEntry, rawStdout, killLiveChildren } from './commandRunner'
import { setGhBinary, setGitBinary } from './git'
import { setAzBinary } from './az'
import { invalidateCodeHost, resolveCodeHost } from './codeHost'
import { HOSTS } from '../../shared/codeHostModel'
import { PLUGIN_NOT_FOUND } from '../../shared/pluginId'
import { forgetTypedActor } from './typedActor'
import { initSettingsPath, loadSettings, recordRecentProject, saveSettings, type Settings } from './settings'
import { hasSdlcProject, listAvailableProfiles, openProject, previewSetup, runPluginScript, runSetup } from './project'
import { combineWithClaude } from './claudeAssist'
import { getConnectionInfo, getPendingClashes, noteCliDetection, onSyncState, pollAndMergeOpenPullRequest, pull, resolveClash, save, setTypedActor } from './sync'
import { addInstance, getDocumentChanges, nextNumber, openDocument, setField } from './documents'
import { confirmRestore, diffVersions, getVersionText, listVersions, previewRestore } from './history'
import { getStageReadiness, setJudgementConfirmation } from './readiness'
import { createProjectFolder } from './newProject'
import { gatherPipelineEvidence } from './pipelineEvidence'
import { registerActivityHandlers } from './activities'
import { registerActivityRunHandlers } from './activityRuns'
import { registerSprintHandlers } from './sprint'
import { registerBriefHandlers } from './briefForm'
import { signOffStage } from './signOff'
import { draftField, recordDraftOutcome } from './drafts'
import { registerDraftHandlers } from './draftDocuments'
import { registerBatchHandlers } from './draftBatch'
import {
  ipcAnswerChatQuestion, ipcEnsureChatStarted, ipcResolveChatProposal, ipcSendChatMessage,
  readChatState, type ChatContext,
} from './chat'
import { getCachedStageDisplay, setCachedStageDisplay } from './chatStageDisplay'
import {
  clearGateAuth, getConnectionReport, getFoundationSummary, getGateAuth, getGateInventory,
  getLastSeenCommit, setGateAuth,
  getProjectSettings, getScorecard, setLastSeenCommit, setRosterPerson, setStageApproval,
  setTeamLimit,
} from './settings'
import { runGitTolerant } from './git'
import {
  advanceAfterDeclaration, declareComplete, deferSpec, generateHandoffReport, getBoard,
  getDeclarationStatus,
  getSpecReadiness, getSpecStatus, transitionSpec,
} from './board'
import { checkHandOff, handOff } from './handoff'
import { getCommandCenter, invalidateCommandCenter, prefetchCommandCenter } from './commandCenter'
import { resolveActor } from './actor'
import { runSprintVerb } from './sprintWrites'
import { registerAdoIpc } from './adoIpc'
import { decideDecision, getDecisions, openDecision } from './decisions'
import { assignRoles, confirmTier, getReadinessAll, getSpecCard } from './specCard'
import { getSlateProposal } from './sprint'
import type { SinceWindow, SprintVerbRequest } from '../../shared/types'
import type { ChatActivity, ClashChoice, DraftOutcome } from '../../shared/types'

/** Two minutes, matching spec 0009's own acceptance check ("Studio pulls every 2 minutes
 * while open"). */
const PULL_INTERVAL_MS = 120_000

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// The built directory structure
//
// ├─┬ dist-electron
// │ ├─┬ main
// │ │ └── index.js    > Electron-Main
// │ └─┬ preload
// │   └── index.mjs   > Preload-Scripts
// ├─┬ dist
// │ └── index.html    > Electron-Renderer
//
process.env.APP_ROOT = path.join(__dirname, '../..')

export const MAIN_DIST = path.join(process.env.APP_ROOT, 'dist-electron')
export const RENDERER_DIST = path.join(process.env.APP_ROOT, 'dist')
export const VITE_DEV_SERVER_URL = process.env.VITE_DEV_SERVER_URL

process.env.VITE_PUBLIC = VITE_DEV_SERVER_URL
  ? path.join(process.env.APP_ROOT, 'public')
  : RENDERER_DIST

// Disable GPU Acceleration for Windows 7
if (process.platform === 'win32' && os.release().startsWith('6.1')) app.disableHardwareAcceleration()

// Set application name for Windows 10+ notifications
if (process.platform === 'win32') app.setAppUserModelId(app.getName())

if (!app.requestSingleInstanceLock()) {
  app.quit()
  process.exit(0)
}

let win: BrowserWindow | null = null

/** The one safe way to push a live update to the renderer. `win?.` alone only guards against
 * `win` being null — it does nothing for a `win` that still exists as a reference but was
 * already closed (destroyed). A background task (a chat turn, any streaming command) can finish
 * after the window closes, and calling `.webContents.send(...)` on a destroyed window throws an
 * uncaught 'Object has been destroyed' error that crashes the whole main process — proven by a
 * real Playwright run, which opens and closes windows fast enough to hit this reliably. */
function sendToWindow(channel: string, payload: unknown) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, payload)
}
const preload = path.join(__dirname, '../preload/index.mjs')
const indexHtml = path.join(RENDERER_DIST, 'index.html')

/** The plugin scripts directory currently in use — resolved once per session from
 * settings/detection, cached here so every IPC call doesn't re-detect. Cleared and
 * re-resolved if the person changes the override in settings. Resolving tooling also
 * primes git.ts with the real git/gh invocation strategy (see tooling.ts's Windows
 * .cmd-shim handling), so every later git/gh call in this session uses it too. */
let resolvedPluginScriptsDir: string | null = null

/** Runs detection with the person's overrides and primes every spawner with what it found —
 * git.ts and az.ts with how to invoke their binaries (a Windows .cmd shim changes every later
 * spawn), sync.ts with whether gh/az exist at all so resolving a project's code host does not
 * re-probe `--version`. One place, because three call sites each used to repeat half of it. */
async function detectTooling(): Promise<DetectAllToolingResult> {
  const settings = loadSettings()
  const report = await detectAllTooling({
    claudePath: settings.claudePathOverride,
    uvPath: settings.uvPathOverride,
    pluginScriptsPath: settings.pluginScriptsPathOverride,
    gitPath: settings.gitPathOverride,
    ghPath: settings.ghPathOverride,
    azPath: settings.azPathOverride,
  })
  if (report.gitResolved) setGitBinary(report.gitResolved)
  if (report.ghResolved) setGhBinary(report.ghResolved)
  if (report.azResolved) setAzBinary(report.azResolved)
  noteCliDetection({ gh: report.gh.found, az: report.az.found })
  return report
}

async function resolvePluginScriptsDir(): Promise<string | null> {
  if (resolvedPluginScriptsDir) return resolvedPluginScriptsDir
  const report = await detectTooling()
  if (report.pluginScripts.found && report.pluginScripts.path) {
    resolvedPluginScriptsDir = report.pluginScripts.path
  }
  return resolvedPluginScriptsDir
}

/** The project Studio currently has open — tracked here so the periodic pull timer (below)
 * knows what to sync. Spec 0008 never needed this (App.tsx discards the path after opening
 * on the renderer side); the main process tracks its own copy for the timer's sake. */
let openProjectPath: string | null = null
let pullTimer: NodeJS.Timeout | null = null

function startPullTimer() {
  if (pullTimer) return
  pullTimer = setInterval(async () => {
    if (!openProjectPath) return
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return
    await pull(openProjectPath, scriptsDir)
    await pollAndMergeOpenPullRequest(openProjectPath, scriptsDir)
  }, PULL_INTERVAL_MS)
}

function registerIpcHandlers() {
  ipcMain.handle('studio:detectTooling', () => detectTooling())

  ipcMain.handle('studio:getSettings', () => loadSettings())

  ipcMain.handle('studio:setToolOverride', (_event, kind: 'claude' | 'uv' | 'pluginScripts' | 'git' | 'gh' | 'az', overridePath: string) => {
    const settings = loadSettings()
    const key = {
      claude: 'claudePathOverride', uv: 'uvPathOverride', pluginScripts: 'pluginScriptsPathOverride',
      git: 'gitPathOverride', gh: 'ghPathOverride', az: 'azPathOverride',
    }[kind] as keyof Settings
    const updated: Settings = { ...settings, [key]: overridePath }
    saveSettings(updated)
    resolvedPluginScriptsDir = null // force re-resolve if any tool path changed
    // What was probed about a code-host CLI (extension, sign-in) was probed on the OLD path.
    invalidateCodeHost()
    return updated
  })

  ipcMain.handle('studio:pickFolder', async () => {
    if (!win) return null
    // createDirectory adds the "New Folder" button to the macOS dialog; Windows' folder dialog
    // already has one.
    const result = await dialog.showOpenDialog(win, { properties: ['openDirectory', 'createDirectory'] })
    return result.canceled ? null : result.filePaths[0]
  })

  ipcMain.handle('studio:createProject', (_event, parent: string, name: string) => createProjectFolder(parent, name))

  ipcMain.handle('studio:hasSdlcProject', (_event, projectPath: string) => hasSdlcProject(projectPath))

  ipcMain.handle('studio:openProject', async (_event, projectPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return { hasProject: false, error: PLUGIN_NOT_FOUND }
    // Spec 0009: pull immediately before a document opens — the closest existing entry
    // point in spec 0008's shell is opening the project itself; best-effort, since a
    // project with no remote configured yet (or offline) must still open.
    await pull(projectPath, scriptsDir).catch(() => undefined)
    const result = await openProject(scriptsDir, projectPath)
    if (result.hasProject && result.status) {
      recordRecentProject(projectPath, result.status.project_name)
      if (openProjectPath && openProjectPath !== projectPath) {
        // Leaving a project: what was probed about its code host, and any name typed for it,
        // belong to that project and must not be read as this one's.
        invalidateCodeHost(openProjectPath)
        forgetTypedActor(openProjectPath)
        invalidateCommandCenter(openProjectPath, 'all')
      }
      openProjectPath = projectPath
      startPullTimer()
      // Q4 (P3 seam): warm the command-center fan-out the moment the project opens, so the home's
      // first `getCommandCenter` is a cache hit (or joins the in-flight read) instead of eight
      // cold spawns after the shell paints. Best-effort and silent: the renderer's own read still
      // decides what shows, and a failure here only means that read does the work itself.
      void prefetchCommandCenter(projectPath, scriptsDir)
    }
    return result
  })

  ipcMain.handle('studio:listProfiles', async () => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? listAvailableProfiles(scriptsDir) : []
  })

  ipcMain.handle('studio:previewSetup', async (_event, projectPath: string, profileId: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return { error: PLUGIN_NOT_FOUND }
    return previewSetup(scriptsDir, projectPath, profileId)
  })

  ipcMain.handle('studio:runSetup', async (_event, projectPath: string, profileId: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return { ok: false, error: PLUGIN_NOT_FOUND }
    const result = await runSetup(scriptsDir, projectPath, profileId)
    if (result.ok) {
      recordRecentProject(projectPath, path.basename(projectPath))
    }
    return result
  })

  // The plugin is needed only for the roster half (handle for the signed-in identity); without
  // it the connection still reports, with the identity as the host gave it.
  ipcMain.handle('studio:getConnectionInfo', async (_event, projectPath: string) =>
    getConnectionInfo(projectPath, await resolvePluginScriptsDir()))

  // D-OWNER-5. Validation and the "only while the host cannot identify you" rule live in
  // sync.ts/typedActor.ts — main refuses, the renderer only asks. A refusal is a rejection.
  ipcMain.handle('studio:setTypedActor', async (_event, projectPath: string, name: string) =>
    setTypedActor(projectPath, await resolvePluginScriptsDir(), name))

  // The repository file IS the code-host override (code-host-providers.md §7): the plugin's own
  // `set_setting.py code-host` validates and writes `.sdlc/code-host.yaml`, so a person who
  // edits it by hand is held to exactly the same rules. The host is checked against the three
  // values HERE as well — the renderer is untrusted, and the argv is otherwise fixed. A refusal
  // rejects with the plugin's sentence; nothing was written in that case.
  ipcMain.handle('studio:setCodeHost', async (_event, projectPath: string, host: unknown) => {
    if (typeof host !== 'string' || !(HOSTS as readonly string[]).includes(host)) {
      throw new Error(`The code host must be one of ${HOSTS.join(', ')}.`)
    }
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) throw new Error(PLUGIN_NOT_FOUND)
    const entry = await runPluginScript(scriptsDir, 'set_setting.py', ['--repo', projectPath, '--json', 'code-host', '--host', host])
    let parsed: { ok?: unknown; refusal?: { message?: unknown } } = {}
    try { parsed = JSON.parse(rawStdout(entry)) } catch { parsed = {} }
    if (parsed.ok !== true) {
      const message = parsed.refusal?.message
      throw new Error(typeof message === 'string' && message ? message : entry.stderr.trim() || 'The code host was not changed.')
    }
    // What was probed about the OLD host (extension, sign-in, identity) is no longer this
    // project's; the refreshed info re-resolves from the file that was just written.
    invalidateCodeHost(projectPath)
    return getConnectionInfo(projectPath, scriptsDir)
  })

  ipcMain.handle('studio:pull', async (_event, projectPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return { ok: false, mergedFiles: [], clashes: [], arrivedChanges: [], entries: [], error: PLUGIN_NOT_FOUND }
    return pull(projectPath, scriptsDir)
  })

  ipcMain.handle(
    'studio:resolveClash',
    async (_event, projectPath: string, filePath: string, sectionKey: string, choice: ClashChoice, combinedText?: string) => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) return { ok: false, fileFullyResolved: false, error: PLUGIN_NOT_FOUND }
      return resolveClash(projectPath, scriptsDir, filePath, sectionKey, choice, combinedText)
    },
  )

  ipcMain.handle(
    'studio:save',
    async (
      _event, projectPath: string, changeNote: string,
      options?: { actor?: string; onlyPath?: string },
    ) => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) return { ok: false, entries: [], error: PLUGIN_NOT_FOUND }
      return save(projectPath, scriptsDir, changeNote, options ?? {})
    },
  )

  ipcMain.handle('studio:getPendingClashes', async (_event, projectPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? getPendingClashes(projectPath, scriptsDir) : []
  })

  ipcMain.handle('studio:combineWithClaude', async (_event, projectPath: string, localText: string, remoteText: string) => {
    const settings = loadSettings()
    return combineWithClaude(settings.claudePathOverride ?? 'claude', projectPath, localText, remoteText)
  })

  // --- Documents (spec 0010) ---

  ipcMain.handle('studio:getStageReadiness', async (_event, projectPath: string, stageId?: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) {
      return {
        ok: false, stageId: '', name: '', display: '', isCurrent: false, documents: [], findings: [],
        judgement: [], signOff: { status: 'unknown', signedOffBy: null, completedAt: null },
        ready: false, error: PLUGIN_NOT_FOUND,
      }
    }
    return getStageReadiness(projectPath, scriptsDir, stageId)
  })

  ipcMain.handle('studio:gatherPipelineEvidence', async (_event, projectPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) {
      return { ok: false, error: PLUGIN_NOT_FOUND, rails: [], proofsNeeded: [] }
    }
    // The host decides which CLI's history is read and whose protection sentence is said
    // (code-host-providers §6.2); resolveCodeHost is memoised, so this is a cache read.
    const { host } = await resolveCodeHost(projectPath)
    return gatherPipelineEvidence(projectPath, scriptsDir, host)
  })
  registerActivityHandlers(ipcMain, resolvePluginScriptsDir)
  registerActivityRunHandlers(ipcMain, resolvePluginScriptsDir)
  registerSprintHandlers(ipcMain, resolvePluginScriptsDir)
  registerAdoIpc(ipcMain, resolvePluginScriptsDir)
  registerBriefHandlers(ipcMain, resolvePluginScriptsDir)
  registerDraftHandlers(ipcMain, resolvePluginScriptsDir, sendToWindow, () => loadSettings().claudePathOverride)
  registerBatchHandlers(ipcMain, resolvePluginScriptsDir, sendToWindow, () => loadSettings().claudePathOverride)

  ipcMain.handle(
    'studio:setJudgementConfirmation',
    async (_event, projectPath: string, stageId: string, questionId: string, confirmed: boolean, actor: string) => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) return { ok: false, error: PLUGIN_NOT_FOUND }
      return setJudgementConfirmation(projectPath, scriptsDir, stageId, questionId, confirmed, actor)
    },
  )

  ipcMain.handle(
    'studio:signOffStage',
    async (
      _event, projectPath: string, stageId: string, signedBy: string,
      disciplineSignoffs: import('../../shared/types').DisciplineSignoff[],
    ) => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) {
        return { ok: false, stage: 'plugin' as const, error: PLUGIN_NOT_FOUND }
      }
      const claudePath = loadSettings().claudePathOverride ?? 'claude'
      return signOffStage(projectPath, scriptsDir, claudePath, stageId, signedBy, disciplineSignoffs)
    },
  )

  const noScripts = (relPath: string) => ({
    ok: false, path: relPath, shaped: false, warnings: [], sections: [],
    error: PLUGIN_NOT_FOUND,
  })

  // The ONE place Studio writes outside a project folder, and only to a location a person
  // pointed at in a save dialog. It takes the text it is given rather than fetching anything:
  // spec 0013 asks an export to contain exactly what was on screen, and re-fetching could
  // quietly produce a different document from the one somebody just read.
  ipcMain.handle('studio:exportDocument', async (_event, suggestedName: string, contents: string) => {
    if (!win) return { ok: false, error: 'No window to ask from.' }
    const result = await dialog.showSaveDialog(win, {
      defaultPath: suggestedName,
      filters: [{ name: 'Markdown', extensions: ['md'] }],
    })
    if (result.canceled || !result.filePath) return { ok: false, cancelled: true }
    try {
      writeFileSync(result.filePath, contents, 'utf-8')
      return { ok: true, path: result.filePath }
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : String(err) }
    }
  })

  ipcMain.handle('studio:getScorecard', async (_event, projectPath: string, windowDays: number) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return null
    return getScorecard(projectPath, scriptsDir, windowDays)
  })

  ipcMain.handle('studio:getFoundationSummary', async (_event, projectPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) {
      return {
        ok: false, stage: null, documents: [],
        error: PLUGIN_NOT_FOUND,
      }
    }
    return getFoundationSummary(projectPath, scriptsDir)
  })

  ipcMain.handle('studio:getGateAuth', async (_event, projectPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) {
      // Never "can sign in" when that could not be determined — reporting a gate as working
      // when it is unknown is the direction that gets somebody merged without a review.
      return { ok: false, repo: null, configured: [], gates_can_sign_in: false,
               detail: PLUGIN_NOT_FOUND }
    }
    return getGateAuth(projectPath, scriptsDir)
  })

  ipcMain.handle(
    'studio:setGateAuth',
    async (_event, projectPath: string, mode: 'subscription' | 'api-key', credential: string) => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) return noPluginSetting
      // The credential is handed straight to the plugin and kept nowhere here — not in
      // settings, not in a variable that outlives this call, not in the console log.
      return setGateAuth(projectPath, scriptsDir, mode, credential)
    },
  )

  ipcMain.handle(
    'studio:clearGateAuth',
    async (_event, projectPath: string, mode: 'subscription' | 'api-key') => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) return noPluginSetting
      return clearGateAuth(projectPath, scriptsDir, mode)
    },
  )

  ipcMain.handle('studio:getGateInventory', async (_event, projectPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) {
      return {
        ok: false, guide_source: null, gates: [], unexpected: [], bypass_ledgers: [],
        error: PLUGIN_NOT_FOUND,
      }
    }
    return getGateInventory(projectPath, scriptsDir)
  })

  ipcMain.handle('studio:getConnectionReport', async (_event, projectPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) {
      return {
        ok: false,
        not_universally_expected: {},
        checks: [{
          check: 'report',
          question: 'Is this project wired up?',
          state: 'unknown' as const,
          detail: PLUGIN_NOT_FOUND,
        }],
      }
    }
    return getConnectionReport(projectPath, scriptsDir)
  })

  ipcMain.handle('studio:getProjectSettings', async (_event, projectPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) {
      return { ok: false, fixed_rules: [],
               roster: { file: '.sdlc/team.yaml', present: false, teams: [], people: [],
                         errors: [PLUGIN_NOT_FOUND] },
               wip_limits: { file: '', present: false, errors: [], teams: [] },
               approval: { file: '.sdlc/approval-settings.yaml', present: false, errors: [], stages: [] } }
    }
    return getProjectSettings(projectPath, scriptsDir)
  })

  const noPluginSetting = {
    ok: false,
    refusal: { kind: 'other', message: PLUGIN_NOT_FOUND },
  }

  ipcMain.handle(
    'studio:setRosterPerson',
    async (
      _event, projectPath: string, handle: string,
      fields: { name?: string; team?: string; roles?: string[]; signsOff?: string[] },
    ) => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) return noPluginSetting
      invalidateCommandCenter(projectPath)
      return setRosterPerson(projectPath, scriptsDir, handle, fields)
    },
  )

  ipcMain.handle('studio:setTeamLimit', async (_event, projectPath: string, team: string, limit: number) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return noPluginSetting
    invalidateCommandCenter(projectPath)
    return setTeamLimit(projectPath, scriptsDir, team, limit)
  })

  ipcMain.handle(
    'studio:setStageApproval',
    async (_event, projectPath: string, stage: string, required: boolean, approver?: string) => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) return noPluginSetting
      return setStageApproval(projectPath, scriptsDir, stage, required, approver)
    },
  )

  ipcMain.handle(
    'studio:getDeclarationStatus',
    async (_event, projectPath: string, confirmedTeams: Record<string, string>) => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) {
        // can_declare stays false — a declaration permitted because a check could not run is
        // the false statement this whole flow exists to prevent.
        return {
          ok: false, can_declare: false,
          blockers: [{ kind: 'unreadable', count: 1,
                       message: PLUGIN_NOT_FOUND }],
          unfinished: [], deferred: [], teamless: [], teams_in_list: [],
          totals: { specs: 0, unfinished: 0, deferred: 0 },
        }
      }
      return getDeclarationStatus(projectPath, scriptsDir, confirmedTeams ?? {})
    },
  )

  ipcMain.handle(
    'studio:declareComplete',
    async (_event, projectPath: string, declaredBy: string, confirmedTeams: Record<string, string>) => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) return noPluginSetting
      return declareComplete(projectPath, scriptsDir, declaredBy, confirmedTeams ?? {})
    },
  )

  ipcMain.handle(
    'studio:deferSpec',
    async (_event, projectPath: string, specPath: string, reason: string, actor?: string) => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) return noPluginSetting
      invalidateCommandCenter(projectPath)
      return deferSpec(projectPath, scriptsDir, specPath, reason, actor)
    },
  )

  ipcMain.handle(
    'studio:advanceAfterDeclaration',
    async (_event, projectPath: string, declaredBy: string) => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) {
        return { ok: false, error: PLUGIN_NOT_FOUND }
      }
      return advanceAfterDeclaration(projectPath, scriptsDir, declaredBy)
    },
  )

  ipcMain.handle(
    'studio:generateHandoffReport',
    async (
      _event,
      projectPath: string,
      options?: { actor?: string; replaceExisting?: boolean },
    ) => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) {
        return { ok: false, error: PLUGIN_NOT_FOUND }
      }
      return generateHandoffReport(projectPath, scriptsDir, options ?? {})
    },
  )

  ipcMain.handle('studio:getBoard', async (_event, projectPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) {
      return { rows: [], codeHostAvailable: false, teamLimits: null,
               error: PLUGIN_NOT_FOUND }
    }
    return getBoard(projectPath, scriptsDir)
  })

  ipcMain.handle('studio:getSpecReadiness', async (_event, projectPath: string, specPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) {
      return { ok: false, error: PLUGIN_NOT_FOUND, ready: false,
               spec: '', risk: '', status: '', blocking: [], advisory: [], passed: [] }
    }
    return getSpecReadiness(projectPath, scriptsDir, specPath)
  })

  const noPlugin = { ok: false, refusal: { kind: 'other', message: PLUGIN_NOT_FOUND } }

  ipcMain.handle('studio:markSpecReady', async (_event, projectPath: string, specPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return noPlugin
    invalidateCommandCenter(projectPath)
    return transitionSpec(projectPath, scriptsDir, specPath, { kind: 'ready' })
  })

  ipcMain.handle(
    'studio:setSpecRisk',
    async (_event, projectPath: string, specPath: string, tier: string, authorisedBy?: string) => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) return noPlugin
      invalidateCommandCenter(projectPath)
      return transitionSpec(projectPath, scriptsDir, specPath, { kind: 'risk', tier, authorisedBy })
    },
  )

  ipcMain.handle('studio:getSpecStatus', async (_event, projectPath: string, specPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return { ok: false, error: PLUGIN_NOT_FOUND }
    return getSpecStatus(projectPath, scriptsDir, specPath)
  })

  ipcMain.handle(
    'studio:handOff',
    async (_event, projectPath: string, specPath: string, developer: string, overLimitReason?: string) => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) {
        return { ok: false, refusal: { kind: 'other' as const,
                 message: PLUGIN_NOT_FOUND } }
      }
      // A hand-off moves a spec to in-flight on the code host: the host block goes too.
      invalidateCommandCenter(projectPath, 'all')
      return handOff(projectPath, scriptsDir, specPath, developer, overLimitReason)
    },
  )

  // --- the command center (togo-command-center.md §2.2, §2.4) --------------------------------
  // Reads are P-class (never pull/sync); every write resolves the actor HERE and runs through
  // the closed argv table. `track_decisions.py --json` rejecting is passed through as an IPC
  // error rather than an all-zero view.

  const noPluginBlock = (source: string) => ({ source, fetchedAt: new Date().toISOString(), ok: false, data: null, error: PLUGIN_NOT_FOUND })

  ipcMain.handle('studio:getCommandCenter', async (_event, projectPath: string, since?: SinceWindow, refresh?: boolean) => {
    const scriptsDir = await resolvePluginScriptsDir()
    const window: SinceWindow = since === 3 ? 3 : 1
    if (!scriptsDir) {
      const b = noPluginBlock
      return {
        projectPath, fetchedAt: new Date().toISOString(), actor: null, capabilities: [],
        sprint: b('sprint.py status --json'), sprints: b('sprint.py list --json'), board: b('spec_status.py --all --json + track_specs.py --json'),
        decisions: b('track_decisions.py --json'), findings: b('record_findings.py report --json'), scorecard: b('scorecard.py report --json'),
        roster: b('project_settings.py --json'), log: b('sprint.py log --json'),
        needsYou: [], needsYouReason: PLUGIN_NOT_FOUND, sinceYesterday: [], since: window,
      }
    }
    return getCommandCenter(projectPath, scriptsDir, window, { refresh: refresh === true })
  })

  ipcMain.handle('studio:getSlateProposal', async (_event, projectPath: string, sprintId: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) throw new Error(PLUGIN_NOT_FOUND)
    const r = await getSlateProposal(projectPath, scriptsDir, sprintId)
    if (!r.ok) throw new Error(r.error)
    return r.data
  })

  ipcMain.handle('studio:getSpecCard', async (_event, projectPath: string, specPath: string, developer?: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) throw new Error(PLUGIN_NOT_FOUND)
    return getSpecCard(projectPath, scriptsDir, specPath, developer)
  })

  ipcMain.handle('studio:getReadinessAll', async (_event, projectPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return { ok: false, specs: [] }
    return getReadinessAll(projectPath, scriptsDir)
  })

  ipcMain.handle('studio:getDecisions', async (_event, projectPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) throw new Error(PLUGIN_NOT_FOUND)
    return getDecisions(projectPath, scriptsDir)
  })

  ipcMain.handle('studio:runSprintVerb', async (_event, projectPath: string, request: SprintVerbRequest) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) {
      return { ok: false, exitCode: null, refused: false, stdout: '', stderr: PLUGIN_NOT_FOUND, argv: [], verb: request?.verb ?? 'slate' }
    }
    const actor = await resolveActor(projectPath, scriptsDir)
    return runSprintVerb(projectPath, scriptsDir, request, actor)
  })

  ipcMain.handle('studio:openDecision', async (_event, projectPath: string, decision: string, owner?: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return { ok: false, stderr: PLUGIN_NOT_FOUND }
    return openDecision(projectPath, scriptsDir, decision, owner, await resolveActor(projectPath, scriptsDir))
  })

  ipcMain.handle('studio:decideDecision', async (_event, projectPath: string, id: string, resolution: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return { ok: false, stderr: PLUGIN_NOT_FOUND }
    return decideDecision(projectPath, scriptsDir, id, resolution, await resolveActor(projectPath, scriptsDir))
  })

  ipcMain.handle('studio:confirmTier', async (_event, projectPath: string, specPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return noPlugin
    return confirmTier(projectPath, scriptsDir, specPath, await resolveActor(projectPath, scriptsDir))
  })

  ipcMain.handle(
    'studio:assignRoles',
    async (_event, projectPath: string, specPath: string, roles: { developer?: string; checker?: string }) => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) return noPlugin
      return assignRoles(projectPath, scriptsDir, specPath, roles ?? {}, await resolveActor(projectPath, scriptsDir))
    },
  )

  ipcMain.handle('studio:checkHandOff', async (_event, projectPath: string, specPath: string, developer: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return noPlugin
    return checkHandOff(projectPath, scriptsDir, specPath, developer)
  })

  ipcMain.handle('studio:openDocument', async (_event, projectPath: string, relPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? openDocument(projectPath, scriptsDir, relPath) : noScripts(relPath)
  })

  ipcMain.handle('studio:getDocumentChanges', async (_event, projectPath: string, relPath: string) => {
    const branchEntry = await runGitTolerant(['branch', '--show-current'], projectPath)
    if (!branchEntry.ok) return []
    return getDocumentChanges(projectPath, relPath, getLastSeenCommit(projectPath, relPath), branchEntry.stdout.trim())
  })

  ipcMain.handle('studio:markDocumentSeen', async (_event, projectPath: string, relPath: string) => {
    const head = await runGitTolerant(['rev-parse', 'HEAD'], projectPath)
    if (head.ok) setLastSeenCommit(projectPath, relPath, head.stdout.trim())
  })

  ipcMain.handle(
    'studio:setField',
    async (_event, projectPath: string, relPath: string, sectionKey: string, label: string, value: string) => {
      const scriptsDir = await resolvePluginScriptsDir()
      return scriptsDir ? setField(projectPath, scriptsDir, relPath, sectionKey, label, value) : noScripts(relPath)
    },
  )

  ipcMain.handle('studio:nextNumber', async (_event, projectPath: string, relPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return { ok: false, error: PLUGIN_NOT_FOUND }
    return nextNumber(projectPath, scriptsDir, relPath)
  })

  ipcMain.handle('studio:addInstance', async (_event, projectPath: string, relPath: string, title: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? addInstance(projectPath, scriptsDir, relPath, title) : noScripts(relPath)
  })

  ipcMain.handle('studio:listVersions', async (_event, projectPath: string, relPath: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    return scriptsDir ? listVersions(projectPath, scriptsDir, relPath) : []
  })

  ipcMain.handle('studio:getVersionText', async (_event, projectPath: string, relPath: string, ref: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return { ok: false, error: PLUGIN_NOT_FOUND }
    return getVersionText(projectPath, scriptsDir, relPath, ref)
  })

  ipcMain.handle('studio:diffVersions', async (_event, projectPath: string, relPath: string, a: string, b: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return { ok: false, error: PLUGIN_NOT_FOUND }
    return diffVersions(projectPath, scriptsDir, relPath, a, b)
  })

  ipcMain.handle('studio:previewRestore', async (_event, projectPath: string, relPath: string, ref: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) {
      return { ok: false, diffHash: '', diff: '', needsSignOffAck: false, error: PLUGIN_NOT_FOUND }
    }
    return previewRestore(projectPath, scriptsDir, relPath, ref)
  })

  ipcMain.handle(
    'studio:confirmRestore',
    async (_event, projectPath: string, relPath: string, ref: string, actor: string, diffHash: string, ackSignOff: boolean) => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) return { ok: false, error: PLUGIN_NOT_FOUND }
      return confirmRestore(projectPath, scriptsDir, relPath, ref, actor, diffHash, ackSignOff)
    },
  )

  ipcMain.handle(
    'studio:draftField',
    async (_event, projectPath: string, relPath: string, sectionKey: string, label: string, guidance: string) => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) return { ok: false, error: PLUGIN_NOT_FOUND }
      const doc = await openDocument(projectPath, scriptsDir, relPath)
      const section = doc.sections.find((s) => s.key === sectionKey)
      const settings = loadSettings()
      return draftField(
        settings.claudePathOverride ?? 'claude',
        projectPath,
        relPath.split('/').pop() ?? relPath,
        section?.heading ?? sectionKey,
        label,
        guidance,
        section?.text ?? '',
      )
    },
  )

  ipcMain.handle(
    'studio:recordDraftOutcome',
    async (
      _event, projectPath: string, relPath: string, label: string, outcome: DraftOutcome,
      actor: string, charsOffered: number, charsKept: number, instance?: string,
    ) => {
      const scriptsDir = await resolvePluginScriptsDir()
      if (!scriptsDir) return
      await recordDraftOutcome(projectPath, scriptsDir, relPath, label, outcome, actor, charsOffered, charsKept, instance)
    },
  )

  // --- Chat authoring (spec 0016) ---
  // Every claude invocation streams through commandRunner's own onChunk hook, broadcast to
  // the SAME console channel every other command uses (spec 0008's transparency rule) — never
  // a side channel of its own (chat.ts's runChatTurn wires a no-op onChunk itself; there is no
  // second, index.ts-owned broadcast to keep in step with it).

  async function cachedStageDisplay(projectPath: string, scriptsDir: string, stageId: string): Promise<string> {
    const cached = getCachedStageDisplay(projectPath, stageId)
    if (cached !== undefined) return cached
    const readiness = await getStageReadiness(projectPath, scriptsDir, stageId)
    const display = readiness.display || stageId
    setCachedStageDisplay(projectPath, stageId, display)
    return display
  }

  async function chatContext(
    projectPath: string, stageId: string, precomputedDisplay?: string,
  ): Promise<ChatContext | null> {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return null
    const settings = loadSettings()
    const stageDisplay = precomputedDisplay !== undefined
      ? precomputedDisplay
      : await cachedStageDisplay(projectPath, scriptsDir, stageId)
    if (precomputedDisplay !== undefined) setCachedStageDisplay(projectPath, stageId, precomputedDisplay)
    return {
      projectPath,
      pluginScriptsDir: scriptsDir,
      stageId,
      stageDisplay,
      claudePath: settings.claudePathOverride ?? 'claude',
      execPath: process.execPath,
      host: (await resolveCodeHost(projectPath)).host,
      onActivity: (label) => sendToWindow('studio:chatActivity', { projectPath, stageId, label } satisfies ChatActivity),
    }
  }

  ipcMain.handle('studio:getChatState', (_event, projectPath: string, stageId: string) =>
    readChatState(projectPath, stageId))

  ipcMain.handle('studio:ensureChatStarted', async (_event, projectPath: string, stageId: string) => {
    const scriptsDir = await resolvePluginScriptsDir()
    if (!scriptsDir) return { ok: false, state: readChatState(projectPath, stageId), error: PLUGIN_NOT_FOUND }
    // The caller-side gate named in the spec ("a stage that has at least one document not yet
    // started") lives HERE, in the one place that decides it, rather than duplicated in the
    // renderer — ipcEnsureChatStarted's own contract is only "have we already greeted". This
    // readiness read also supplies chatContext's stageDisplay below, rather than making it
    // fetch readiness a second time for the same stage.
    const readiness = await getStageReadiness(projectPath, scriptsDir, stageId)
    const hasUnstarted = readiness.documents.some((d) => !d.exists)
    if (!hasUnstarted) return { ok: true, state: readChatState(projectPath, stageId) }
    const ctx = await chatContext(projectPath, stageId, readiness.display || stageId)
    if (!ctx) return { ok: false, state: readChatState(projectPath, stageId), error: PLUGIN_NOT_FOUND }
    return ipcEnsureChatStarted(ctx)
  })

  ipcMain.handle('studio:sendChatMessage', async (_event, projectPath: string, stageId: string, text: string) => {
    const ctx = await chatContext(projectPath, stageId)
    if (!ctx) return { ok: false, state: readChatState(projectPath, stageId), error: PLUGIN_NOT_FOUND }
    return ipcSendChatMessage(ctx, text)
  })

  ipcMain.handle(
    'studio:answerChatQuestion',
    async (_event, projectPath: string, stageId: string, questionId: string, optionLabel: string) => {
      const ctx = await chatContext(projectPath, stageId)
      if (!ctx) return { ok: false, state: readChatState(projectPath, stageId), error: PLUGIN_NOT_FOUND }
      return ipcAnswerChatQuestion(ctx, questionId, optionLabel)
    },
  )

  ipcMain.handle(
    'studio:resolveChatProposal',
    async (
      _event, projectPath: string, stageId: string, proposalId: string,
      outcome: DraftOutcome, finalValue: string, actor: string,
    ) => {
      const ctx = await chatContext(projectPath, stageId)
      if (!ctx) return { ok: false, state: readChatState(projectPath, stageId), error: PLUGIN_NOT_FOUND }
      return ipcResolveChatProposal(ctx, proposalId, outcome, finalValue, actor)
    },
  )

  let pulling = false
  onSyncState((state) => {
    // A pull that completed may have brought other people's spec, sprint and decision edits:
    // the command center's local blocks are stale the moment it lands. Saves are this machine's
    // own writes and already invalidated at their IPC; nothing here reads on a timer.
    if (state.kind === 'pulling') pulling = true
    else if (pulling && state.kind !== 'saving') {
      pulling = false
      if (openProjectPath) invalidateCommandCenter(openProjectPath)
    }
    sendToWindow('studio:syncState', state)
  })

  ipcMain.handle('studio:getConsoleLog', () => getConsoleLog())

  // Push new console entries to the renderer as they happen, so the console panel updates
  // live rather than only on the next getConsoleLog() poll.
  onConsoleEntry((entry) => {
    sendToWindow('studio:consoleEntry', entry)
  })
}

async function createWindow() {
  // Size: what the person left last time if it still lands on a connected display, else a first
  // open that fits the display's work area (up to 1680×1050, never under 1180×720, centred).
  // A fixed 1280×800 was small on a desktop display and cramped the command center's lanes.
  const userData = app.getPath('userData')
  const areas = screen.getAllDisplays().map((d) => d.workArea)
  const bounds = fitSavedBounds(readSavedBounds(userData), areas) ?? firstOpenBounds(screen.getPrimaryDisplay().workArea)
  win = new BrowserWindow({
    title: 'Shepherd',
    ...bounds,
    minWidth: MIN_WIDTH,
    minHeight: MIN_HEIGHT,
    icon: path.join(process.env.VITE_PUBLIC!, 'favicon.ico'), // set unconditionally above, before createWindow() can run
    webPreferences: {
      preload,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  // Remember the size and place (debounced) so the next open restores them.
  let saveTimer: NodeJS.Timeout | null = null
  const remember = () => {
    if (!win || win.isMinimized() || win.isFullScreen()) return
    const b = win.getNormalBounds()
    writeSavedBounds(userData, b)
  }
  const scheduleRemember = () => { if (saveTimer) clearTimeout(saveTimer); saveTimer = setTimeout(remember, 400) }
  // Rendering scale follows the window width (windowBounds.zoomFor): the layout is drawn for
  // ~1440 px and reads small on a wide display. Off under the tests and the capture, which set
  // their own viewports and read CSS-pixel geometry.
  const autoZoom = process.env.TOGO_AUTO_ZOOM !== '0'
  const applyZoom = () => { if (win && autoZoom) win.webContents.setZoomFactor(zoomFor(win.getContentBounds().width)) }
  win.webContents.on('did-finish-load', applyZoom)
  win.on('resize', applyZoom)
  win.on('resize', scheduleRemember)
  win.on('move', scheduleRemember)
  win.on('close', () => { if (saveTimer) clearTimeout(saveTimer); remember() })

  if (VITE_DEV_SERVER_URL) { // #298
    win.loadURL(VITE_DEV_SERVER_URL)
    // Open devTool if the app is not packaged
    win.webContents.openDevTools()
  } else {
    win.loadFile(indexHtml)
  }

  // Make all links open with the browser, not with the application
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https:')) shell.openExternal(url)
    return { action: 'deny' }
  })

  // The window may only ever show Studio's own page. Without this, anything that could make
  // the page navigate elsewhere would hand a remote site the whole `window.studio` API —
  // every file read and write, and every call that starts a process. The window-open handler
  // above already covers new windows; this covers the top-level frame itself, which it does
  // not. (Spec 0010's security pass.)
  const isOurOwnPage = (url: string) =>
    (VITE_DEV_SERVER_URL !== undefined && url.startsWith(VITE_DEV_SERVER_URL)) || url.startsWith('file://')

  win.webContents.on('will-navigate', (event, url) => {
    if (!isOurOwnPage(url)) event.preventDefault()
  })
  win.webContents.on('will-redirect', (event, url) => {
    if (!isOurOwnPage(url)) event.preventDefault()
  })
}

// An embedded browser frame would be another way to reach a remote origin inside the app, and
// Studio has no use for one. Refused for every web contents, not just the main window.
app.on('web-contents-created', (_event, contents) => {
  contents.on('will-attach-webview', (event) => event.preventDefault())
})

app.whenReady().then(() => {
  initSettingsPath(app.getPath('userData'))
  registerIpcHandlers()
  createWindow()
})

// Quitting must not wait on a plugin script or a model run that outlived the window: end every
// child this process started (the e2e worker teardown once timed out on exactly that).
app.on('before-quit', () => { killLiveChildren() })

app.on('window-all-closed', () => {
  win = null
  if (process.platform !== 'darwin') app.quit()
})

app.on('second-instance', () => {
  if (win) {
    // Focus on the main window if the user tried to open another
    if (win.isMinimized()) win.restore()
    win.focus()
  }
})

app.on('activate', () => {
  const allWindows = BrowserWindow.getAllWindows()
  if (allWindows.length) {
    allWindows[0].focus()
  } else {
    createWindow()
  }
})
