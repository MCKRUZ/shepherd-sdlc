/** Spec 0029's registration: the seven invoke channels exist, index.ts gains one import and one call (it is
 * over its size cap), and a plugin that cannot be found is
 * an ok:false answer on every one that needs it. Reading the state and Cancel need no plugin. */

import { describe, expect, it } from 'vitest'
import { registerBatchHandlers } from '../electron/main/draftBatch'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

type Handler = (event: unknown, ...args: any[]) => unknown // eslint-disable-line @typescript-eslint/no-explicit-any

function fakeIpc() {
  const handlers = new Map<string, Handler>()
  return { handlers, ipcMain: { handle: (channel: string, fn: Handler) => { handlers.set(channel, fn) } } as never }
}

const CHANNELS = [
  'studio:previewBatch', 'studio:startBatch', 'studio:cancelBatch', 'studio:getBatchState',
  'studio:keepBatch', 'studio:discardBatch', 'studio:writeRegistry',
]

describe('batch registration', () => {
  it('registers the seven invoke channels', () => {
    const { handlers, ipcMain } = fakeIpc()
    registerBatchHandlers(ipcMain, async () => null, () => {}, () => undefined)
    expect([...handlers.keys()].sort()).toEqual([...CHANNELS].sort())
  })

  it('registers exactly the channels the preload invokes for batches, and pushes state on the preload channel', () => {
    const preload = readFileSync(join(__dirname, '..', 'electron', 'preload', 'index.ts'), 'utf-8')
    const invoked = [...preload.matchAll(/ipcRenderer\.invoke\('(studio:(?:previewBatch|startBatch|cancelBatch|getBatchState|keepBatch|discardBatch|writeRegistry))'/g)]
      .map((m) => m[1]).sort()
    expect(invoked).toEqual([...CHANNELS].sort())
    expect(preload).toContain("ipcRenderer.on('studio:batchState'")
  })

  it('is called from the main process entry point, once, beside the draft registration', () => {
    const entry = readFileSync(join(__dirname, '..', 'electron', 'main', 'index.ts'), 'utf-8')
    expect(entry.match(/registerBatchHandlers\(/g)).toHaveLength(1)
    expect(entry).toMatch(/import \{ registerBatchHandlers \} from '\.\/draftBatch'/)
  })

  it('answers ok:false "plugin scripts not found" when the plugin cannot be found, and never starts anything', async () => {
    const { handlers, ipcMain } = fakeIpc()
    registerBatchHandlers(ipcMain, async () => null, () => {}, () => undefined)
    const call = (channel: string, ...args: unknown[]) => handlers.get(channel)!({}, ...args)
    const NO_PLUGIN = 'Shepherd plugin scripts not found'

    expect(await call('studio:previewBatch', '/p', 'summarise')).toEqual({ ok: false, error: NO_PLUGIN })
    expect(await call('studio:startBatch', '/p', 'summarise')).toEqual({ ok: false, error: NO_PLUGIN })
    expect(await call('studio:keepBatch', '/p', 'j', 'Matt')).toEqual({ ok: false, error: NO_PLUGIN, kept: [], failed: [], warnings: [] })
    expect(await call('studio:discardBatch', '/p', 'j', 'Matt')).toEqual({ ok: false, error: NO_PLUGIN, warnings: [] })
    expect(await call('studio:writeRegistry', '/p')).toMatchObject({ ok: false, error: NO_PLUGIN, documents: 0, missingSummaries: [] })
  })

  it('still reads the state and cancels without the plugin: a running batch must stay stoppable', async () => {
    const { handlers, ipcMain } = fakeIpc()
    registerBatchHandlers(ipcMain, async () => null, () => {}, () => undefined)
    expect(await handlers.get('studio:cancelBatch')!({})).toEqual({ ok: true })
    expect(await handlers.get('studio:getBatchState')!({}, '/nowhere')).toEqual({ job: null, candidates: [] })
  })
})
