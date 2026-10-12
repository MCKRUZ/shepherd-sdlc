/** The Sprint view in the real window (proposal: studio-improvements, Batch 2).
 *
 * The promises here are the ones a function test cannot prove: that the Sprint entry sits beside
 * the Board in the sidebar and opens a screen that reads the sprint the plugin's own scripts made;
 * that a value the plugin reports as null reads "no data" on screen and never as a zero; that a
 * slate row opens the same spec view the board opens; and that the view offers no control that
 * changes the sprint — the only buttons write a page, and nothing runs until one is pressed.
 *
 * The fixture is built by the plugin's scripts, not by hand-written files: init_project.py,
 * new_spec.py three times, sprint.py new / slate / verdict — the same commands /sprd-sprint runs.
 */

import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test'
import { requirePlugin } from '../pluginRoot'

const root = resolve(import.meta.dirname, '..', '..')

// Located once, in one place, and LOUD when it cannot be found. See test/pluginRoot.ts.
const PLUGIN = requirePlugin(join(root, 'test'))

const PLUGIN_ROOT = PLUGIN.root
const SCRIPTS_DIR = PLUGIN.scriptsDir
const VENV_PYTHON = PLUGIN.python

let app: ElectronApplication
let page: Page
let workspace = ''
let specIds: string[] = []

function py(args: string[]): void {
  execFileSync(VENV_PYTHON, args, { cwd: SCRIPTS_DIR })
}

/** Build Loop's own screens sit beneath it in the sidebar, and only once Build Loop is where you
 * are — so reaching one is two clicks: the stage, then the screen. */
async function openBuildView(target: Page, view: string) {
  await target.getByRole('button', { name: /^Build Loop/ }).click()
  await target.getByRole('button', { name: view, exact: true }).click()
}

test.describe('[studio-improvements B2] the Sprint view in the real window', () => {
  test.skip(!PLUGIN_ROOT || !existsSync(VENV_PYTHON), 'needs a plugin checkout beside this repo')
  test.describe.configure({ mode: 'serial' })

  test.beforeAll(async () => {
    test.setTimeout(240_000)
    workspace = mkdtempSync(join(tmpdir(), 'studio-e2e-sprint-'))
    const project = join(workspace, 'project')

    py([join(SCRIPTS_DIR, 'init_project.py'), '--profile', join(PLUGIN_ROOT!, 'profiles', 'microsoft-enterprise', 'profile.yaml'), '--target', project])
    for (const [name, risk] of [['duplicate claim 409', 'HIGH'], ['claim export', 'MEDIUM'], ['adjuster notes', 'LOW']]) {
      py([join(SCRIPTS_DIR, 'new_spec.py'), '--repo', project, '--name', name, '--risk', risk, '--owner', '@priya-n', '--team', 'claims'])
    }
    specIds = readdirSync(join(project, 'specs')).filter((f) => /^\d{4}-/.test(f)).map((f) => f.slice(0, 4)).sort()
    py([
      join(SCRIPTS_DIR, 'sprint.py'), 'new', '--repo', project, '--sprint', 'S07', '--goal', 'Adjusters file without a phone call',
      '--start', '2026-09-28', '--target', '3', '--mix', 'HIGH:1,MEDIUM:1,LOW:1', '--by', 'Priya N.',
    ])
    py([join(SCRIPTS_DIR, 'sprint.py'), 'slate', '--repo', project, '--sprint', 'S07', ...specIds.flatMap((id) => ['--spec', id]), '--by', 'Priya N.'])
    py([join(SCRIPTS_DIR, 'sprint.py'), 'verdict', '--repo', project, '--spec', specIds[0], '--lane', 'eng', '--verdict', 'accepted', '--by', 'Matt K.'])

    const userData = join(workspace, 'userData')
    mkdirSync(userData, { recursive: true })
    writeFileSync(join(userData, 'settings.json'), JSON.stringify({
      recentProjects: [{ path: project, name: 'sprint project', lastOpenedAt: new Date().toISOString() }],
      pluginScriptsPathOverride: SCRIPTS_DIR,
    }, null, 2))

    app = await electron.launch({
      args: ['.', '--no-sandbox', `--user-data-dir=${userData}`],
      cwd: root,
      env: { ...process.env, NODE_ENV: 'development' },
    })
    page = await app.firstWindow()
    await expect(page.getByText('Loading…')).toHaveCount(0, { timeout: 30_000 })
    await page.getByText('sprint project').click()
    // Recorded pin change (togo-command-center.md §1, §8): the lifecycle strip replaced the
    // sidebar and the Build station expands only on click, so "Documents" is no longer visible at
    // rest. The landing fact is the strip's `nav[aria-label=Project]` — a11y.spec's own wait.
    await expect(page.getByRole('navigation', { name: 'Project' })).toBeVisible({ timeout: 30_000 })
  })

  test.afterAll(async () => {
    test.setTimeout(120_000)
    // On the ubuntu runner this hook once ate the whole 120 s: a screenshot of a window that was
    // tearing down never returned. Each step gets its own ceiling so one slow step cannot strand
    // the rest (the screenshot is a convenience, not an assertion).
    await page?.screenshot({ path: 'test/screenshots/studio-improvements-sprint.png', timeout: 15_000 }).catch(() => {})
    const closed = await Promise.race([app?.close().then(() => true).catch(() => true), new Promise<boolean>((r) => setTimeout(() => r(false), 20_000))])
    if (!closed) { try { app?.process().kill('SIGKILL') } catch { /* already gone */ } }
    try {
      if (workspace) rmSync(workspace, { recursive: true, force: true })
    } catch {
      // A leftover temp directory is untidy, not a failure worth reddening a green run.
    }
  })

  // Recorded pin change (togo-command-center.md §1, §7 P0/P7): the Build view `sprint` is
  // relabelled "Home" (nav.ts BUILD_VIEWS — the loop is the work) and the screen is the sprint
  // home, `[data-testid=sprint-home]`, whose header keeps the `sprint-header/-state/-target/-wip`
  // ids. The sprint the scripts made is still what it opens.
  test('Home sits first under Build Loop and opens the sprint the scripts made', async () => {
    await openBuildView(page, 'Home')
    await expect(page.getByTestId('sprint-home')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('sprint-header')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('sprint-header')).toContainText('Sprint S07')
    await expect(page.getByTestId('sprint-header')).toContainText('Adjusters file without a phone call')
    await expect(page.getByTestId('sprint-state')).toHaveText('planning')
    await expect(page.getByTestId('sprint-target')).toHaveText('3 specs')
    // The Home entry is the lit one, not Board.
    await expect(page.getByRole('button', { name: 'Home', exact: true })).toHaveAttribute('aria-current', 'page')
  })

  test('the slate has the three slated specs, each NOT READY in the checker\'s words', async () => {
    const rows = page.getByTestId('sprint-slate-row')
    await expect(rows).toHaveCount(3)
    for (const id of specIds) await expect(page.locator(`[data-testid="sprint-slate-row"][data-spec="${id}"]`)).toBeVisible()
    // A fresh scaffold has placeholders; the DoR line comes from check_spec, not from Studio.
    // Counted inside the slate: the readiness card below repeats each spec's DoR line in the
    // plugin's own words ("0001: DoR: NOT READY (…)"), which is the same fact, not a fourth row.
    const slate = page.getByTestId('sprint-slate')
    await expect(slate.getByText('NOT READY')).toHaveCount(3)
    await slate.getByText('NOT READY').first().click()
    await expect(page.locator('details[open]')).toHaveCount(1)
  })

  test('a value the plugin reports as null reads "no data" or "not set", never a zero', async () => {
    // No cadence-plan.md states a WIP cap, and nothing is READY so nothing is next.
    await expect(page.getByTestId('sprint-wip')).toContainText('cap not set')
    await expect(page.getByTestId('sprint-decisions')).toContainText('no data — no decision-log')
    await expect(page.getByTestId('sprint-next-up')).toContainText('no slated spec is READY')
    await expect(page.getByTestId('sprint-readiness')).toContainText('0 of 3 ready')
  })

  test('the recorded verdict is on its row; the rest are pending and listed', async () => {
    const first = page.locator(`[data-testid="sprint-slate-row"][data-spec="${specIds[0]}"]`)
    await expect(first).toContainText('accepted')
    await expect(page.getByTestId('sprint-verdicts')).toContainText(`${specIds[1]} · eng`)
  })

  test('the slate twin offers no control that changes the sprint', async () => {
    // Recorded pin change (togo-command-center.md §6, §8 (2)): the sprint home has more controls
    // by design (the brief's screen 1); the three-button assertion is scoped to
    // `[data-testid=sprint-board]`, the slate's Table twin, where exactly these three remain.
    // No inputs anywhere in <main>, no textarea but the chat composer — unchanged.
    const buttons = await page.getByTestId('sprint-board').getByRole('button').allTextContents()
    const names = buttons.filter((b) => !specIds.includes(b.trim()))
    expect(names.sort()).toEqual(['Planning page', 'Refresh', 'Review page'])
    await expect(page.locator('main input')).toHaveCount(0)
    await expect(page.locator('main textarea:not([data-testid="chat-composer-input"])')).toHaveCount(0)
    await expect(page.getByText('Reports stay on this computer')).toBeVisible()
  })

  test('a slate row opens the same spec view the board opens, and Back returns to the sprint', async () => {
    await page.getByRole('button', { name: specIds[1], exact: true }).click()
    await expect(page.getByText(/Owns it/)).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText(`specs/${specIds[1]}-claim-export.md`)).toBeVisible()
    await page.getByRole('button', { name: '← Back to the board' }).click()
    await expect(page.getByTestId('sprint-header')).toBeVisible({ timeout: 30_000 })
  })

  test('Planning page writes the page inside .sdlc/reports and says where', async () => {
    await page.getByRole('button', { name: 'Planning page' }).click()
    await expect(page.getByTestId('sprint-page-result')).toContainText('.sdlc/reports/sprint-S07-planning.html', { timeout: 60_000 })
    expect(existsSync(join(workspace, 'project', '.sdlc', 'reports', 'sprint-S07-planning.html'))).toBe(true)
  })

  test('the Build › Workflow tab carries the same sprint as a compact panel', async () => {
    test.setTimeout(120_000)
    await openBuildView(page, 'Documents')
    await page.getByRole('button', { name: 'Workflow' }).click()
    // F11 (Observatory): the sprint activity's row offers "Open" and its panel renders in the
    // main slot's FocusedActivityHost, so the test opens the activity first and reads the panel
    // there — as runActivities / batchJobs / modelRunner / briefForm do. The panel's own testids
    // are unchanged; only where it lives moved.
    const row = page.locator('[data-testid="activity-row"][data-activity-id="sprint"]')
    // The row arrives with the stage's readiness, a beat after the tab switch — wait for it
    // before reading the button, or `count()` snapshots an empty list and Open is never pressed.
    await expect(row).toBeVisible({ timeout: 30_000 })
    const open = row.getByRole('button', { name: 'Open' })
    if (await open.count()) await open.click()
    const host = page.locator('[data-testid="focused-activity-host"][data-activity-id="sprint"]')
    await expect(host).toBeVisible({ timeout: 60_000 })
    const panel = host.getByTestId('sprint-panel')
    await expect(panel).toBeVisible({ timeout: 60_000 })
    await expect(panel.getByTestId('sprint-header')).toContainText('Sprint S07')
    await expect(panel.getByTestId('sprint-slate')).toHaveCount(0)
  })
})

/** A project with no sprint record at all must say so and point at /sprd-sprint new — not show an
 * empty table, and not a "0 of 0". A separate app instance, because the fixture above has one. */
test.describe('[studio-improvements B2] a project with no sprint, in the real window', () => {
  test.skip(!PLUGIN_ROOT || !existsSync(VENV_PYTHON), 'needs a plugin checkout beside this repo')

  let bareApp: ElectronApplication
  let barePage: Page
  let bareWorkspace = ''

  test.beforeAll(async () => {
    test.setTimeout(120_000)
    bareWorkspace = mkdtempSync(join(tmpdir(), 'studio-e2e-nosprint-'))
    const project = join(bareWorkspace, 'project')
    py([join(SCRIPTS_DIR, 'init_project.py'), '--profile', join(PLUGIN_ROOT!, 'profiles', 'microsoft-enterprise', 'profile.yaml'), '--target', project])

    const userData = join(bareWorkspace, 'userData')
    mkdirSync(userData, { recursive: true })
    writeFileSync(join(userData, 'settings.json'), JSON.stringify({
      recentProjects: [{ path: project, name: 'no sprint project', lastOpenedAt: new Date().toISOString() }],
      pluginScriptsPathOverride: SCRIPTS_DIR,
    }, null, 2))

    bareApp = await electron.launch({
      args: ['.', '--no-sandbox', `--user-data-dir=${userData}`],
      cwd: root,
      env: { ...process.env, NODE_ENV: 'development' },
    })
    barePage = await bareApp.firstWindow()
    await expect(barePage.getByText('Loading…')).toHaveCount(0, { timeout: 30_000 })
    await barePage.getByText('no sprint project').click()
    // Same recorded change as above: the strip's navigation is the landing fact.
    await expect(barePage.getByRole('navigation', { name: 'Project' })).toBeVisible({ timeout: 30_000 })
  })

  test.afterAll(async () => {
    test.setTimeout(60_000)
    await bareApp?.close().catch(() => {})
    try {
      if (bareWorkspace) rmSync(bareWorkspace, { recursive: true, force: true })
    } catch {
      // A leftover temp directory is untidy, not a failure worth reddening a green run.
    }
  })

  test('says there is no sprint and where to start one; shows no table and no count', async () => {
    await openBuildView(barePage, 'Home')
    // The plugin's own note wins when it gives one ("no sprint record under … — create one with
    // `sprint.py new`"); Studio's sentence is the fallback. Either names where to start.
    await expect(barePage.getByTestId('sprint-empty')).toHaveText(/no sprint record|No sprint — open one with \/sprd-sprint new\./, { timeout: 60_000 })
    await expect(barePage.getByTestId('sprint-slate')).toHaveCount(0)
    await expect(barePage.getByTestId('sprint-header')).toHaveCount(0)
    await expect(barePage.getByText(/0 of 0/)).toHaveCount(0)
  })
})
