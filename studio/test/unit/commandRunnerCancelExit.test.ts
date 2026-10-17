/** A cancelled runCommand settles only once the child has actually exited.
 *
 * The Windows CI job failed `commandRunnerCancel.test.ts` with `EBUSY: resource busy or locked, rmdir`
 * on the folder the cancelled child had as its working directory: runCommand sent the kill and settled
 * at once, the kill is asynchronous (`taskkill` is a process of its own there), and Windows refuses to
 * remove a directory that a live process is standing in. Waiting for the child's own `exit` before
 * settling means no process outlives the promise. A Mac cannot hold a directory that way, so the race
 * is reproduced here with what it CAN show: a child that takes a moment to go after the stop. */

import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { CANCEL_EXIT_WAIT_MS, runCommand, wasCancelled } from '../../electron/main/commandRunner'

const alive = (pid: number): boolean => {
  try { process.kill(pid, 0); return true } catch { return false }
}

/** Starts a node child in a fresh folder that installs `onTerm` as its SIGTERM handler, records its
 * pid, then idles; resolves once the pid is on disk, so the handler is in place before any abort. */
async function startIdleChild(onTerm: string) {
  const dir = mkdtempSync(join(tmpdir(), 'studio-cancel-exit-'))
  const pidFile = join(dir, 'pid')
  const controller = new AbortController()
  const script = `process.on('SIGTERM', ${onTerm}); require('fs').writeFileSync(${JSON.stringify(pidFile)}, String(process.pid)); setInterval(() => {}, 1000)`
  const run = runCommand(process.execPath, ['-e', script], dir, { signal: controller.signal })
  for (let i = 0; i < 200; i++) {
    try { readFileSync(pidFile); break } catch { await new Promise((r) => setTimeout(r, 25)) }
  }
  const pid = Number(readFileSync(pidFile, 'utf-8'))
  return { dir, pid, controller, run }
}

async function cleanUp(dir: string, pid: number) {
  if (alive(pid)) { try { process.kill(pid, 'SIGKILL') } catch { /* already gone */ } }
  // Async rm on purpose: fs.rmSync's retries do not wait between attempts (5 retries took 2 ms on
  // Node 24 here; the Windows CI teardown's 20 at 100 ms gave up within its 291 ms test on Node 22).
  await rm(dir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 })
}

describe('runCommand cancel waits for the child to exit', () => {
  it('settles only after a child that lingers after the stop has gone, so its folder is free at once', async () => {
    // The child takes 600 ms to leave after SIGTERM. Windows' taskkill /F does not ask, so there the
    // wait is just the time the tree takes to die — the CI failure — and the assertions are the same.
    const { dir, pid, controller, run } = await startIdleChild('() => setTimeout(() => process.exit(0), 600)')
    try {
      controller.abort()
      const entry = await run

      expect(alive(pid), 'the child must be gone by the time the cancel settles').toBe(false)
      expect(wasCancelled(entry)).toBe(true)
      expect(entry.ok).toBe(false)
      expect(entry.exitCode).toBeNull()
      expect(entry.stderr).toContain('Cancelled')
      // No retries: nothing may still be standing in the folder the command ran in.
      expect(() => rmSync(dir, { recursive: true })).not.toThrow()
    } finally {
      await cleanUp(dir, pid)
    }
  })

  // Windows' taskkill /F cannot be ignored, so only a POSIX child can refuse the stop.
  it.skipIf(process.platform === 'win32')('still settles, and says so, when the child ignores the stop', async () => {
    const { dir, pid, controller, run } = await startIdleChild('() => {}')
    try {
      const started = Date.now()
      controller.abort()
      const entry = await run
      const waited = Date.now() - started

      expect(waited).toBeGreaterThanOrEqual(CANCEL_EXIT_WAIT_MS - 100)
      expect(waited).toBeLessThan(CANCEL_EXIT_WAIT_MS + 3000)
      expect(wasCancelled(entry)).toBe(true)
      expect(entry.exitCode).toBeNull()
      expect(entry.stderr).toContain('Cancelled')
      expect(entry.stderr).toContain('had not exited')
    } finally {
      await cleanUp(dir, pid)
    }
  })
})
