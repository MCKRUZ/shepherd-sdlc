// The window's rendering scale follows its width in the real app (electron/main/windowBounds.ts);
// the specs set their own viewports and read CSS-pixel geometry, so it is off here (inherited by
// every Electron the specs launch through process.env).
process.env.TOGO_AUTO_ZOOM = '0'
import { chmodSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { delimiter, join } from 'node:path'
import { defineConfig } from '@playwright/test'

// Nothing a spec does may start the machine's own browser. On Linux, Electron opens a report page
// or a link by running `xdg-open` from PATH (shell.openPath / openExternal, electron
// shell/common/platform_util_linux.cc), and on the ubuntu runner that started a real browser which
// inherited the app's stdout/stderr and outlived it. Playwright waits for those pipes to close
// before it counts the app as closed, so the app a spec had closed (the sprint close screen's
// review page; the Sprint view's Planning page) held the worker for its full teardown budget and
// failed the job as "1 error was not a part of any test" with every test green. A stand-in
// `xdg-open` first on PATH — inherited the same way as TOGO_AUTO_ZOOM above — says what it was
// asked to open (on the app's stderr, so it shows in the `pw:browser` log) and opens nothing. The
// specs assert the page is written and where; handing it to a browser is the operating system's
// job and was never what they checked. macOS and Windows open files through the system's own API,
// not a program on PATH, so this is Linux-only. The marker keeps a worker, which loads this
// config again with the runner's environment, from adding a second one.
if (process.platform === 'linux' && !process.env.STUDIO_E2E_XDG_OPEN_STUB) {
  const bin = mkdtempSync(join(tmpdir(), 'studio-e2e-bin-'))
  const stub = join(bin, 'xdg-open')
  writeFileSync(stub, '#!/bin/sh\necho "[e2e] xdg-open stand-in; nothing opened: $*" >&2\nexit 0\n')
  chmodSync(stub, 0o755)
  process.env.PATH = `${bin}${delimiter}${process.env.PATH ?? ''}`
  process.env.STUDIO_E2E_XDG_OPEN_STUB = stub
  process.once('exit', () => rmSync(bin, { recursive: true, force: true }))
}

export default defineConfig({
  testDir: './test/e2e',
  fullyParallel: false,
  workers: 1,
  // The test timeout is also the worker-teardown budget. On the ubuntu runner, closing the last
  // Electron app of a run took longer than Playwright's 30 s default after every test had
  // passed (the specs set their own longer timeouts per test; this covers the teardown).
  timeout: 120_000,
  reporter: 'list',
  use: {
    trace: 'on-first-retry',
  },
})
