/** Spec 0024's window, driven for real: the activities list under the Workflow tab, and the Guide tab.
 *
 * The unit tests pin the rows, the controls and every result string against a mocked `window.studio`.
 * What they cannot prove is the whole route against the real plugin: that `stage_readiness.py`
 * really emits the activities, that Create really writes the three Design documents from their
 * templates through the real IPC, that the check really runs the real script, and that the Guide
 * tab really reads a file out of the plugin. That is what this file is for.
 *
 * Skipped when no plugin checkout is beside this repository, same convention as workflow.spec.ts.
 */

import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test'
import { requirePlugin } from '../pluginRoot'

const root = resolve(import.meta.dirname, '..', '..')
const PLUGIN = requirePlugin(join(root, 'test'))
const PLUGIN_ROOT = PLUGIN.root
const SCRIPTS_DIR = PLUGIN.scriptsDir
const VENV_PYTHON = PLUGIN.python

const DATA_DIR = '.sdlc/artifacts/02-design/data'
const DATA_FILES = ['data-contract.md', 'data-readiness.md', 'lineage-audit.md']

test.describe('[spec 0024] activities and the Guide tab, in the real window', () => {
  test.skip(!PLUGIN_ROOT || !existsSync(VENV_PYTHON), 'needs a plugin checkout beside this repo')
  test.describe.configure({ mode: 'serial' })

  let app: ElectronApplication
  let page: Page
  let workspace = ''
  let project = ''

  test.beforeAll(async () => {
    test.setTimeout(180_000)
    workspace = mkdtempSync(join(tmpdir(), 'studio-e2e-activities-'))
    project = join(workspace, 'project')

    execFileSync(VENV_PYTHON, [
      join(SCRIPTS_DIR, 'init_project.py'),
      '--profile', join(PLUGIN_ROOT!, 'profiles', 'microsoft-enterprise', 'profile.yaml'),
      '--target', project,
    ], { cwd: SCRIPTS_DIR })

    const statePath = join(project, '.sdlc', 'state.yaml')
    writeFileSync(
      statePath,
      readFileSync(statePath, 'utf-8')
        .replace(/^current_phase:.*$/m, 'current_phase: "2"')
        .replace(/^phase_name:.*$/m, 'phase_name: "design"'),
      'utf-8',
    )

    const userData = join(workspace, 'userData')
    mkdirSync(userData, { recursive: true })
    writeFileSync(join(userData, 'settings.json'), JSON.stringify({
      recentProjects: [{ path: project, name: 'activities e2e project', lastOpenedAt: new Date().toISOString() }],
      pluginScriptsPathOverride: SCRIPTS_DIR,
    }, null, 2))

    app = await electron.launch({
      args: ['.', '--no-sandbox', `--user-data-dir=${userData}`],
      cwd: root,
      env: { ...process.env, NODE_ENV: 'development' },
    })
    page = await app.firstWindow()
    await expect(page.getByText('Loading…')).toHaveCount(0, { timeout: 30_000 })
    await page.getByText('activities e2e project').click()
    await expect(page.getByRole('tab', { name: 'Workflow' })).toBeVisible({ timeout: 30_000 })
  })

  test.afterAll(async () => {
    test.setTimeout(120_000)
    await page?.screenshot({ path: 'test/screenshots/spec-0024-activities.png' }).catch(() => {})
    await app?.close().catch(() => {})
    try {
      if (workspace) rmSync(workspace, { recursive: true, force: true })
    } catch { /* a leftover temp directory is not a failed test */ }
  })

  const row = (id: string) => page.locator(`[data-testid="activity-row"][data-activity-id="${id}"]`)

  test('the plugin\'s own activities are listed under the steps: create, check and talk, never run or draft', async () => {
    await expect(page.getByTestId('activities-panel')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByRole('heading', { name: 'Also in this stage' })).toBeVisible()
    for (const id of ['data', 'data-check', 'experience', 'coach']) await expect(row(id)).toHaveCount(1)
    // Spec 0026 gave review, enhance and phase-report their panels, so Design draws all of its
    // declared activities now (spec 0024 held these three back until they had a control).
    for (const id of ['review', 'enhance', 'phase-report']) await expect(row(id)).toHaveCount(1)
  })

  test('the check that needs the data contract is blocked, with the plugin\'s reason, until it exists', async () => {
    await expect(row('data-check')).toHaveAttribute('data-activity-status', 'blocked')
    await expect(row('data-check').getByTestId('activity-disabled-reason').or(row('data-check'))).toContainText(/data-contract\.md/)
    await expect(row('data-check').getByRole('button', { name: 'Check personal data' })).toHaveCount(0)
  })

  test('Create starts all three data documents from their templates and opens the first one', async () => {
    for (const file of DATA_FILES) expect(existsSync(join(project, DATA_DIR, file))).toBe(false)
    await row('data').getByRole('button', { name: 'Create' }).click()
    // The window moves straight on to the first document, so the "Started 3 documents" line is
    // never on screen long enough to read — the evidence is the files and the open document.
    await expect(page.getByRole('heading', { name: 'data-contract.md', level: 2 })).toBeVisible({ timeout: 30_000 })
    for (const file of DATA_FILES) expect(existsSync(join(project, DATA_DIR, file))).toBe(true)
    await page.getByRole('button', { name: '← Back to the stage' }).click()
    await expect(page.getByRole('tab', { name: 'Workflow' })).toBeVisible()
  })

  test('the data activity then reads Done, and the check it was blocking becomes available', async () => {
    await expect(row('data')).toHaveAttribute('data-activity-status', 'done', { timeout: 30_000 })
    await expect(row('data-check')).toHaveAttribute('data-activity-status', 'available', { timeout: 30_000 })
  })

  test('a contract that is still the blank template says "Nothing to check yet", never "0 personal data fields"', async () => {
    await row('data-check').getByRole('button', { name: 'Check personal data' }).click()
    const result = row('data-check').getByTestId('activity-result')
    await expect(result).toBeVisible({ timeout: 60_000 })
    await expect(result).toContainText('Nothing to check yet')
    await expect(result).not.toContainText(/0 personal data/i)
  })

  test('a document edited by hand is left alone when the stage is reopened (never-overwrite itself is pinned in ensureDocumentNested.test.ts)', async () => {
    const before = DATA_FILES.map((f) => readFileSync(join(project, DATA_DIR, f), 'utf-8'))
    writeFileSync(join(project, DATA_DIR, DATA_FILES[0]), `${before[0]}\n<!-- edited by hand -->\n`)
    await page.getByRole('tab', { name: 'Documents' }).click()
    await page.getByRole('tab', { name: 'Workflow' }).click()
    const after = readFileSync(join(project, DATA_DIR, DATA_FILES[0]), 'utf-8')
    expect(after).toContain('<!-- edited by hand -->')
    expect(readFileSync(join(project, DATA_DIR, DATA_FILES[1]), 'utf-8')).toBe(before[1])
  })

  test('the Guide tab shows the stage\'s own guidance from the plugin and lists every activity, drawn or not', async () => {
    await page.getByRole('tab', { name: 'Guide' }).click()
    const guide = page.getByTestId('guide-tab')
    await expect(guide).toBeVisible({ timeout: 30_000 })
    await expect(guide).not.toContainText('No guidance file for this stage')
    // The activities Workflow does not draw are still named here, with their command.
    await expect(guide).toContainText('/sprd-review')
    await expect(guide).toContainText('/sprd-data')
  })

  test('changing back to Workflow lands on the steps again', async () => {
    await page.getByRole('tab', { name: 'Workflow' }).click()
    await expect(page.getByRole('tab', { name: 'Workflow' })).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByTestId('workflow-step').first()).toBeVisible()
  })
})
