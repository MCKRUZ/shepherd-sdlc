// The Azure Boards mirror's one IPC handler (build kit §5 B4-P2, decision K18: handlers live here, registered from
// `index.ts` with two lines, because that file is already past a thousand). `runAdoVerb` takes one closed
// `AdoVerbRequest` and runs the owning verb once; everything else about the Boards screens — the status block, the
// capabilities, the actor — is read through `getCommandCenter`, so there is no read channel here. The handler
// resolves the actor and the plugin's capabilities itself: the renderer sends no name, no flag and no argv, and
// `adoWrites.ts` refuses a request that does not fit the table before anything is spawned.

import type { IpcMain } from 'electron'
import { resolveActor } from './actor'
import { runAdoVerb } from './adoWrites'
import { getCapabilities } from './commandCenter'
import type { AdoVerbRequest } from '../../shared/adoVerbArgv'

/** The one channel; the preload invokes this exact name. */
export const ADO_VERB_CHANNEL = 'studio:runAdoVerb'

export function registerAdoIpc(ipcMain: IpcMain, resolvePluginScriptsDir: () => Promise<string | null>): void {
  ipcMain.handle(ADO_VERB_CHANNEL, async (_event, projectPath: string, request: AdoVerbRequest) => {
    const scriptsDir = await resolvePluginScriptsDir()
    // No plugin: refused before anyone is resolved (PLUGIN_NOT_FOUND, exitCode null).
    if (!scriptsDir) return runAdoVerb(projectPath, null, request, null)
    const actor = await resolveActor(projectPath, scriptsDir)
    const capabilities = await getCapabilities(projectPath, scriptsDir)
    return runAdoVerb(projectPath, scriptsDir, request, actor, capabilities)
  })
}
