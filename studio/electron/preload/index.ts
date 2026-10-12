import { contextBridge, ipcRenderer } from 'electron'
import type { BatchState, ChatActivity, CommandCenterApi, ConsoleEntry, DraftProgressEvent, StudioApi, SyncState } from '../../shared/types'

// The ONLY surface the renderer gets. No generic ipcRenderer passthrough, no Node access,
// no arbitrary command execution — every call here maps to exactly one narrow main-process
// handler, and every one of those handlers goes through commandRunner's single choke point
// when it needs to run anything, so every command Studio runs is recorded to the console.
// Typed against the shared StudioApi interface, so a mismatch with what the renderer
// expects is a compile error here, not a runtime surprise.
const studio: StudioApi & CommandCenterApi = {
  detectTooling: () => ipcRenderer.invoke('studio:detectTooling'),
  getSettings: () => ipcRenderer.invoke('studio:getSettings'),
  setToolOverride: (kind, path) => ipcRenderer.invoke('studio:setToolOverride', kind, path),

  pickFolder: () => ipcRenderer.invoke('studio:pickFolder'),
  createProject: (parent, name) => ipcRenderer.invoke('studio:createProject', parent, name),
  hasSdlcProject: (projectPath) => ipcRenderer.invoke('studio:hasSdlcProject', projectPath),
  openProject: (projectPath) => ipcRenderer.invoke('studio:openProject', projectPath),

  listProfiles: () => ipcRenderer.invoke('studio:listProfiles'),
  previewSetup: (projectPath, profileId) => ipcRenderer.invoke('studio:previewSetup', projectPath, profileId),
  runSetup: (projectPath, profileId) => ipcRenderer.invoke('studio:runSetup', projectPath, profileId),

  getConnectionInfo: (projectPath) => ipcRenderer.invoke('studio:getConnectionInfo', projectPath),
  setTypedActor: (projectPath, name) => ipcRenderer.invoke('studio:setTypedActor', projectPath, name),
  setCodeHost: (projectPath, host) => ipcRenderer.invoke('studio:setCodeHost', projectPath, host),
  pull: (projectPath) => ipcRenderer.invoke('studio:pull', projectPath),
  resolveClash: (projectPath, filePath, sectionKey, choice, combinedText) =>
    ipcRenderer.invoke('studio:resolveClash', projectPath, filePath, sectionKey, choice, combinedText),
  save: (projectPath, changeNote, options) =>
    ipcRenderer.invoke('studio:save', projectPath, changeNote, options),
  onSyncState: (callback) => {
    const handler = (_event: Electron.IpcRendererEvent, state: SyncState) => callback(state)
    ipcRenderer.on('studio:syncState', handler)
    return () => ipcRenderer.off('studio:syncState', handler)
  },
  getPendingClashes: (projectPath) => ipcRenderer.invoke('studio:getPendingClashes', projectPath),
  combineWithClaude: (projectPath, localText, remoteText) =>
    ipcRenderer.invoke('studio:combineWithClaude', projectPath, localText, remoteText),

  getStageReadiness: (projectPath, stageId) => ipcRenderer.invoke('studio:getStageReadiness', projectPath, stageId),
  gatherPipelineEvidence: (projectPath) => ipcRenderer.invoke('studio:gatherPipelineEvidence', projectPath),
  startActivity: (projectPath, stageId, activityId) => ipcRenderer.invoke('studio:startActivity', projectPath, stageId, activityId),
  startDocument: (projectPath, relPath) => ipcRenderer.invoke('studio:startDocument', projectPath, relPath),
  runActivityCheck: (projectPath, activityId) => ipcRenderer.invoke('studio:runActivityCheck', projectPath, activityId),
  getStageGuide: (definition) => ipcRenderer.invoke('studio:getStageGuide', definition),
  exportPhaseReport: (projectPath, stageId, all) => ipcRenderer.invoke('studio:exportPhaseReport', projectPath, stageId, all),
  openReport: (projectPath, reportPath) => ipcRenderer.invoke('studio:openReport', projectPath, reportPath),
  runIntake: (projectPath, change) => ipcRenderer.invoke('studio:runIntake', projectPath, change),
  getNarrativeCoverage: (projectPath, stageId) => ipcRenderer.invoke('studio:getNarrativeCoverage', projectPath, stageId),
  getReviewStanding: (projectPath) => ipcRenderer.invoke('studio:getReviewStanding', projectPath),
  runStrictReviewCheck: (projectPath) => ipcRenderer.invoke('studio:runStrictReviewCheck', projectPath),
  getSprintStatus: (projectPath, sprintId) => ipcRenderer.invoke('studio:getSprintStatus', projectPath, sprintId),
  renderSprintReport: (projectPath, sprintId, kind) => ipcRenderer.invoke('studio:renderSprintReport', projectPath, sprintId, kind),
  startDraft: (projectPath, request) => ipcRenderer.invoke('studio:startDraft', projectPath, request),
  cancelDraft: () => ipcRenderer.invoke('studio:cancelDraft'),
  getDraftState: (projectPath) => ipcRenderer.invoke('studio:getDraftState', projectPath),
  keepDraft: (projectPath, jobId, actor) => ipcRenderer.invoke('studio:keepDraft', projectPath, jobId, actor),
  discardDraft: (projectPath, jobId, actor) => ipcRenderer.invoke('studio:discardDraft', projectPath, jobId, actor),
  onDraftProgress: (callback) => {
    const handler = (_event: Electron.IpcRendererEvent, progress: DraftProgressEvent) => callback(progress)
    ipcRenderer.on('studio:draftProgress', handler)
    return () => ipcRenderer.off('studio:draftProgress', handler)
  },
  previewBatch: (projectPath, kind) => ipcRenderer.invoke('studio:previewBatch', projectPath, kind),
  startBatch: (projectPath, kind) => ipcRenderer.invoke('studio:startBatch', projectPath, kind),
  cancelBatch: () => ipcRenderer.invoke('studio:cancelBatch'),
  getBatchState: (projectPath) => ipcRenderer.invoke('studio:getBatchState', projectPath),
  keepBatch: (projectPath, jobId, actor, candidateIds) => ipcRenderer.invoke('studio:keepBatch', projectPath, jobId, actor, candidateIds),
  discardBatch: (projectPath, jobId, actor, candidateIds) => ipcRenderer.invoke('studio:discardBatch', projectPath, jobId, actor, candidateIds),
  writeRegistry: (projectPath) => ipcRenderer.invoke('studio:writeRegistry', projectPath),
  getBriefCandidates: (projectPath) => ipcRenderer.invoke('studio:getBriefCandidates', projectPath),
  buildBrief: (projectPath, selections) => ipcRenderer.invoke('studio:buildBrief', projectPath, selections),
  onBatchState: (callback) => {
    const handler = (_event: Electron.IpcRendererEvent, update: { projectPath: string; state: BatchState }) => callback(update)
    ipcRenderer.on('studio:batchState', handler)
    return () => ipcRenderer.off('studio:batchState', handler)
  },
  setJudgementConfirmation: (projectPath, stageId, questionId, confirmed, actor) =>
    ipcRenderer.invoke('studio:setJudgementConfirmation', projectPath, stageId, questionId, confirmed, actor),
  signOffStage: (projectPath, stageId, signedBy, disciplineSignoffs) =>
    ipcRenderer.invoke('studio:signOffStage', projectPath, stageId, signedBy, disciplineSignoffs),
  openDocument: (projectPath, relPath) => ipcRenderer.invoke('studio:openDocument', projectPath, relPath),
  getDocumentChanges: (projectPath, relPath) => ipcRenderer.invoke('studio:getDocumentChanges', projectPath, relPath),
  markDocumentSeen: (projectPath, relPath) => ipcRenderer.invoke('studio:markDocumentSeen', projectPath, relPath),
  setField: (projectPath, relPath, sectionKey, label, value) =>
    ipcRenderer.invoke('studio:setField', projectPath, relPath, sectionKey, label, value),
  nextNumber: (projectPath, relPath) => ipcRenderer.invoke('studio:nextNumber', projectPath, relPath),
  addInstance: (projectPath, relPath, title) => ipcRenderer.invoke('studio:addInstance', projectPath, relPath, title),

  listVersions: (projectPath, relPath) => ipcRenderer.invoke('studio:listVersions', projectPath, relPath),
  getVersionText: (projectPath, relPath, ref) => ipcRenderer.invoke('studio:getVersionText', projectPath, relPath, ref),
  diffVersions: (projectPath, relPath, a, b) => ipcRenderer.invoke('studio:diffVersions', projectPath, relPath, a, b),
  previewRestore: (projectPath, relPath, ref) => ipcRenderer.invoke('studio:previewRestore', projectPath, relPath, ref),
  confirmRestore: (projectPath, relPath, ref, actor, diffHash, ackSignOff) =>
    ipcRenderer.invoke('studio:confirmRestore', projectPath, relPath, ref, actor, diffHash, ackSignOff),

  getBoard: (projectPath) => ipcRenderer.invoke('studio:getBoard', projectPath),
  getProjectSettings: (projectPath) => ipcRenderer.invoke('studio:getProjectSettings', projectPath),
  getConnectionReport: (projectPath) => ipcRenderer.invoke('studio:getConnectionReport', projectPath),
  getScorecard: (projectPath, windowDays) =>
    ipcRenderer.invoke('studio:getScorecard', projectPath, windowDays),
  getGateInventory: (projectPath) => ipcRenderer.invoke('studio:getGateInventory', projectPath),
  getGateAuth: (projectPath) => ipcRenderer.invoke('studio:getGateAuth', projectPath),
  setGateAuth: (projectPath, mode, credential) =>
    ipcRenderer.invoke('studio:setGateAuth', projectPath, mode, credential),
  clearGateAuth: (projectPath, mode) =>
    ipcRenderer.invoke('studio:clearGateAuth', projectPath, mode),
  getFoundationSummary: (projectPath) =>
    ipcRenderer.invoke('studio:getFoundationSummary', projectPath),
  getDeclarationStatus: (projectPath, confirmedTeams) =>
    ipcRenderer.invoke('studio:getDeclarationStatus', projectPath, confirmedTeams),
  declareComplete: (projectPath, declaredBy, confirmedTeams) =>
    ipcRenderer.invoke('studio:declareComplete', projectPath, declaredBy, confirmedTeams),
  advanceAfterDeclaration: (projectPath, declaredBy) =>
    ipcRenderer.invoke('studio:advanceAfterDeclaration', projectPath, declaredBy),
  deferSpec: (projectPath, specPath, reason, actor) =>
    ipcRenderer.invoke('studio:deferSpec', projectPath, specPath, reason, actor),
  generateHandoffReport: (projectPath, options) =>
    ipcRenderer.invoke('studio:generateHandoffReport', projectPath, options),
  exportDocument: (suggestedName, contents) =>
    ipcRenderer.invoke('studio:exportDocument', suggestedName, contents),
  setRosterPerson: (projectPath, handle, fields) =>
    ipcRenderer.invoke('studio:setRosterPerson', projectPath, handle, fields),
  setTeamLimit: (projectPath, team, limit) =>
    ipcRenderer.invoke('studio:setTeamLimit', projectPath, team, limit),
  setStageApproval: (projectPath, stage, required, approver) =>
    ipcRenderer.invoke('studio:setStageApproval', projectPath, stage, required, approver),
  getSpecReadiness: (projectPath, specPath) =>
    ipcRenderer.invoke('studio:getSpecReadiness', projectPath, specPath),
  markSpecReady: (projectPath, specPath) =>
    ipcRenderer.invoke('studio:markSpecReady', projectPath, specPath),
  setSpecRisk: (projectPath, specPath, tier, authorisedBy) =>
    ipcRenderer.invoke('studio:setSpecRisk', projectPath, specPath, tier, authorisedBy),
  getSpecStatus: (projectPath, specPath) =>
    ipcRenderer.invoke('studio:getSpecStatus', projectPath, specPath),
  handOff: (projectPath, specPath, developer, overLimitReason) =>
    ipcRenderer.invoke('studio:handOff', projectPath, specPath, developer, overLimitReason),

  draftField: (projectPath, relPath, sectionKey, label, guidance) =>
    ipcRenderer.invoke('studio:draftField', projectPath, relPath, sectionKey, label, guidance),
  recordDraftOutcome: (projectPath, relPath, label, outcome, actor, charsOffered, charsKept, instance) =>
    ipcRenderer.invoke('studio:recordDraftOutcome', projectPath, relPath, label, outcome, actor, charsOffered, charsKept, instance),

  getConsoleLog: () => ipcRenderer.invoke('studio:getConsoleLog'),
  onConsoleEntry: (callback) => {
    const handler = (_event: Electron.IpcRendererEvent, entry: ConsoleEntry) => callback(entry)
    ipcRenderer.on('studio:consoleEntry', handler)
    return () => ipcRenderer.off('studio:consoleEntry', handler)
  },

  getChatState: (projectPath, stageId) => ipcRenderer.invoke('studio:getChatState', projectPath, stageId),
  onChatActivity: (callback) => {
    const handler = (_event: Electron.IpcRendererEvent, activity: ChatActivity) => callback(activity)
    ipcRenderer.on('studio:chatActivity', handler)
    return () => ipcRenderer.off('studio:chatActivity', handler)
  },
  ensureChatStarted: (projectPath, stageId) =>
    ipcRenderer.invoke('studio:ensureChatStarted', projectPath, stageId),
  sendChatMessage: (projectPath, stageId, text) =>
    ipcRenderer.invoke('studio:sendChatMessage', projectPath, stageId, text),
  answerChatQuestion: (projectPath, stageId, questionId, optionLabel) =>
    ipcRenderer.invoke('studio:answerChatQuestion', projectPath, stageId, questionId, optionLabel),
  resolveChatProposal: (projectPath, stageId, proposalId, outcome, finalValue, actor) =>
    ipcRenderer.invoke('studio:resolveChatProposal', projectPath, stageId, proposalId, outcome, finalValue, actor),

  // The command center (togo-command-center.md §2.2, §2.4): five P-class reads, six writes that
  // each resolve the actor in main and run one fixed argv. Pass-through only.
  getCommandCenter: (projectPath, since, refresh) => ipcRenderer.invoke('studio:getCommandCenter', projectPath, since, refresh),
  getSlateProposal: (projectPath, sprintId) => ipcRenderer.invoke('studio:getSlateProposal', projectPath, sprintId),
  getSpecCard: (projectPath, specPath, developer) => ipcRenderer.invoke('studio:getSpecCard', projectPath, specPath, developer),
  getReadinessAll: (projectPath) => ipcRenderer.invoke('studio:getReadinessAll', projectPath),
  getDecisions: (projectPath) => ipcRenderer.invoke('studio:getDecisions', projectPath),
  runSprintVerb: (projectPath, request) => ipcRenderer.invoke('studio:runSprintVerb', projectPath, request),
  openDecision: (projectPath, decision, owner) => ipcRenderer.invoke('studio:openDecision', projectPath, decision, owner),
  decideDecision: (projectPath, id, resolution) => ipcRenderer.invoke('studio:decideDecision', projectPath, id, resolution),
  confirmTier: (projectPath, specPath) => ipcRenderer.invoke('studio:confirmTier', projectPath, specPath),
  assignRoles: (projectPath, specPath, roles) => ipcRenderer.invoke('studio:assignRoles', projectPath, specPath, roles),
  checkHandOff: (projectPath, specPath, developer) => ipcRenderer.invoke('studio:checkHandOff', projectPath, specPath, developer),
}

contextBridge.exposeInMainWorld('studio', studio)

// --------- Preload scripts loading ---------
function domReady(condition: DocumentReadyState[] = ['complete', 'interactive']) {
  return new Promise(resolve => {
    if (condition.includes(document.readyState)) {
      resolve(true)
    } else {
      document.addEventListener('readystatechange', () => {
        if (condition.includes(document.readyState)) {
          resolve(true)
        }
      })
    }
  })
}

const safeDOM = {
  append(parent: HTMLElement, child: HTMLElement) {
    if (!Array.from(parent.children).find(e => e === child)) {
      return parent.appendChild(child)
    }
  },
  remove(parent: HTMLElement, child: HTMLElement) {
    if (Array.from(parent.children).find(e => e === child)) {
      return parent.removeChild(child)
    }
  },
}

/**
 * https://tobiasahlin.com/spinkit — the spin is SpinKit's; the square it turns is the brand's
 * flat tile (docs/brand/shepherd/tile.svg: the two-tone frame alone on sand, the same drawing the
 * OS shows at 16 and 32 px), inlined as a data URI because nothing is loaded before the renderer
 * paints. Sand (#F5EFE4) and bark (#14120F) are the brand's canvas values; `img-src data:` is
 * allowed by the renderer's CSP.
 */
function useLoading() {
  const className = `loaders-css__square-spin`
  const tile = 'data:image/svg+xml,%3Csvg%20xmlns=%22http://www.w3.org/2000/svg%22%20viewBox=%220%200%2064%2064%22%3E%3Crect%20width=%2264%22%20height=%2264%22%20rx=%2214%22%20fill=%22%23F5EFE4%22/%3E%3Cg%20transform=%22translate(4%204)%20scale(0.875)%22%3E%3Cpath%20fill=%22%233F6B35%22%20d=%22M10.47%2010.22%20L16.7%204%20L51.5%204%20L60%2012.5%20L60%2047.3%20L56.52%2050.77%20L50.25%2044.5%20L42.7%2044.5%20L42.7%2038.9%20L49.1%2038.9%20L49.1%2014.9%20L15.15%2014.9%20Z%22/%3E%3Cpath%20fill=%22%235E452A%22%20d=%22M7.47%2013.22%20L14.9%2020.65%20L14.9%2049.1%20L48.85%2049.1%20L53.52%2053.77%20L47.3%2060%20L12.5%2060%20L4%2051.5%20L4%2016.7%20Z%22/%3E%3C/g%3E%3C/svg%3E'
  const styleContent = `
@keyframes square-spin {
  25% { transform: perspective(100px) rotateX(180deg) rotateY(0); }
  50% { transform: perspective(100px) rotateX(180deg) rotateY(180deg); }
  75% { transform: perspective(100px) rotateX(0) rotateY(180deg); }
  100% { transform: perspective(100px) rotateX(0) rotateY(0); }
}
.${className} > div {
  animation-fill-mode: both;
  width: 50px;
  height: 50px;
  border-radius: 11px;
  background: #F5EFE4 url("${tile}") center / contain no-repeat;
  animation: square-spin 3s 0s cubic-bezier(0.09, 0.57, 0.49, 0.9) infinite;
}
.app-loading-wrap {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #14120F;
  z-index: 9;
}
    `
  const oStyle = document.createElement('style')
  const oDiv = document.createElement('div')

  oStyle.id = 'app-loading-style'
  oStyle.innerHTML = styleContent
  oDiv.className = 'app-loading-wrap'
  oDiv.innerHTML = `<div class="${className}"><div></div></div>`

  return {
    appendLoading() {
      safeDOM.append(document.head, oStyle)
      safeDOM.append(document.body, oDiv)
    },
    removeLoading() {
      safeDOM.remove(document.head, oStyle)
      safeDOM.remove(document.body, oDiv)
    },
  }
}

// ----------------------------------------------------------------------

const { appendLoading, removeLoading } = useLoading()
domReady().then(appendLoading)

window.onmessage = (ev) => {
  ev.data.payload === 'removeLoading' && removeLoading()
}

setTimeout(removeLoading, 4999)
