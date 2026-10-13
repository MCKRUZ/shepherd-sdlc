/** The chat panel's look and width, in the real window.
 *
 * The unit tests prove the pieces (the markdown renderer is hardened, the width is clamped and
 * remembered); this proves what a person actually sees: a reply written in markdown is drawn as
 * formatted text rather than raw asterisks, and dragging the panel's left edge really widens it.
 *
 * The conversation is seeded into Studio's saved chat state, so no model call is needed.
 * Skipped when no plugin checkout is beside this repository (same as chatAuthoring.spec.ts).
 */

import { execFileSync } from 'node:child_process'
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test'
import { requirePlugin } from '../pluginRoot'
import { closeApp } from './cc/shell'

const root = resolve(import.meta.dirname, '..', '..')
const PLUGIN = requirePlugin(join(root, 'test'))
const PLUGIN_ROOT = PLUGIN.root
const SCRIPTS_DIR = PLUGIN.scriptsDir
const VENV_PYTHON = PLUGIN.python

const REPLY = [
  "I've re-verified this against Microsoft's page, so it's the spec's recorded finding.",
  '',
  "- **It's cheaper.** About $11.68/month against about $16.06.",
  '- **No application code changes.** The rate limiter runs one script against one key.',
  '',
  '**What changes.**',
  '- The host and port change (`*.redis.azure.net`, port 10000).',
  '- Key-based access is disabled, so it is Entra-only.',
  '',
  '**The risk.** The rate limiter is deliberately fail-open.',
].join('\n')

/** The shared close: app.quit() with a grace period, then the process ended by pid and its death
 * waited for, so Playwright's worker teardown never inherits a live app (see cc/shell.ts). */
async function closeQuickly(app: ElectronApplication | undefined): Promise<void> {
  await closeApp(app, undefined, 'chat-look')
}

test.describe('[chat look and width] a markdown reply, and a panel the person can widen', () => {
  test.skip(!PLUGIN_ROOT || !existsSync(VENV_PYTHON), 'needs a plugin checkout beside this repo')
  test.describe.configure({ mode: 'serial' })

  let workspace = ''
  let app: ElectronApplication
  let page: Page

  test.beforeAll(async () => {
    test.setTimeout(180_000)
    workspace = mkdtempSync(join(tmpdir(), 'studio-e2e-chat-look-'))
    const project = join(workspace, 'project')
    execFileSync(VENV_PYTHON, [
      join(SCRIPTS_DIR, 'init_project.py'),
      '--profile', join(PLUGIN_ROOT!, 'profiles', 'microsoft-enterprise', 'profile.yaml'),
      '--target', project,
    ], { cwd: SCRIPTS_DIR })
    // A stage whose documents all exist, so opening it makes no model call of its own.
    mkdirSync(join(project, '.sdlc', 'artifacts', '01-requirements'), { recursive: true })
    for (const name of ['requirements', 'non-functional-requirements', 'epics', 'phase2-handoff']) {
      cpSync(
        join(SCRIPTS_DIR, 'tests', 'fixtures', 'documents', `${name}.md`),
        join(project, '.sdlc', 'artifacts', '01-requirements', `${name}.md`),
      )
    }
    const statePath = join(project, '.sdlc', 'state.yaml')
    writeFileSync(
      statePath,
      readFileSync(statePath, 'utf-8')
        .replace(/^current_phase:.*$/m, 'current_phase: "1"')
        .replace(/^phase_name:.*$/m, 'phase_name: "requirements"'),
      'utf-8',
    )

    const userData = join(workspace, 'userData')
    mkdirSync(userData, { recursive: true })
    const at = new Date().toISOString()
    writeFileSync(join(userData, 'settings.json'), JSON.stringify({
      recentProjects: [{ path: project, name: 'chat look project', lastOpenedAt: at }],
      pluginScriptsPathOverride: SCRIPTS_DIR,
      chatState: {
        [`${project}\u0000${'1'}`]: {
          sessionId: 'seeded',
          messages: [
            { id: 'u1', role: 'user', text: 'What does the Redis change cost us?', questions: [], proposals: [], at },
            { id: 'a1', role: 'assistant', text: REPLY, questions: [], proposals: [], at },
          ],
        },
      },
    }, null, 2))

    app = await electron.launch({
      args: ['.', '--no-sandbox', `--user-data-dir=${userData}`],
      cwd: root,
      env: { ...process.env, NODE_ENV: 'development' },
    })
    page = await app.firstWindow()
    await expect(page.getByText('Loading…')).toHaveCount(0, { timeout: 30_000 })
  })

  test.afterAll(async () => {
    test.setTimeout(30_000)
    await page?.screenshot({ path: 'test/screenshots/chat-look-and-width.png' }).catch(() => {})
    await closeQuickly(app)
    try { if (workspace) rmSync(workspace, { recursive: true, force: true }) } catch { /* not a failed test */ }
  })

  test('the reply is drawn as formatted text, not raw markdown', async () => {
    await page.getByText('chat look project').click()
    await expect(page.getByRole('heading', { name: 'Chat' })).toBeVisible({ timeout: 30_000 })
    const chat = page.locator('aside').filter({ has: page.getByRole('heading', { name: 'Chat' }) })
    await expect(chat.getByText("It's cheaper.")).toBeVisible({ timeout: 15_000 })
    expect(await chat.locator('strong').count()).toBeGreaterThanOrEqual(3)
    expect(await chat.locator('li').count()).toBe(4)
    expect(await chat.innerText()).not.toContain('**')
  })

  test('dragging the left edge widens the panel, and it stays within the window', async () => {
    const chat = page.locator('aside').filter({ has: page.getByRole('heading', { name: 'Chat' }) })
    const before = (await chat.boundingBox())!.width
    const handle = chat.getByRole('separator', { name: 'Resize chat' })
    const box = (await handle.boundingBox())!
    const y = box.y + box.height / 2
    await page.mouse.move(box.x + box.width / 2, y)
    await page.mouse.down()
    await page.mouse.move(box.x - 150, y, { steps: 8 })
    await page.mouse.up()
    const after = (await chat.boundingBox())!.width
    expect(after).toBeGreaterThan(before + 100)

    // Dragged far past any sane size: held at 60% of the window, so the document keeps its room.
    await page.mouse.move(box.x - 150, y)
    await page.mouse.down()
    await page.mouse.move(5, y, { steps: 8 })
    await page.mouse.up()
    const windowWidth = (await page.evaluate(() => window.innerWidth))
    const capped = (await chat.boundingBox())!.width
    expect(capped).toBeLessThanOrEqual(windowWidth * 0.6 + 1)
    expect(capped).toBeGreaterThan(after)
  })

  test('double-clicking the edge returns to the default width', async () => {
    const chat = page.locator('aside').filter({ has: page.getByRole('heading', { name: 'Chat' }) })
    await chat.getByRole('separator', { name: 'Resize chat' }).dblclick()
    expect(Math.round((await chat.boundingBox())!.width)).toBe(380)
  })
})
