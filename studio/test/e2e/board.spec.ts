/** The Build board in the real window (spec 0011).
 *
 * The check that matters most here is the last one. Spec 0011 asks for a board of 200 specs
 * across 4 teams to open in under two seconds, and its Checking Plan tells the reviewer to
 * confirm that was MEASURED, not assumed. The data half is already measured — 1.2 seconds,
 * one code-host request regardless of spec count — but rendering two hundred rows was, until
 * this file, an untested assumption. So the fixture builds two hundred real specs and the
 * test times the real window.
 *
 * Everything else here is the read-only promise: the status view offers no control that
 * changes anything, which cannot be proven by a function test — only by looking at what is
 * on screen.
 */

import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test'
import { requirePlugin } from '../pluginRoot'

const root = resolve(import.meta.dirname, '..', '..')
const TEAMS = ['core', 'claims', 'payments', 'platform']
const SPEC_COUNT = 200

// Located once, in one place, and LOUD when it cannot be found. A window run where 31 of 33
// tests skipped used to print "2 passed" and exit 0 — indistinguishable from a run that
// proved everything. See test/pluginRoot.ts.
const PLUGIN = requirePlugin(join(root, 'test'))

const PLUGIN_ROOT = PLUGIN.root
const SCRIPTS_DIR = PLUGIN.scriptsDir
const VENV_PYTHON = PLUGIN.python

let app: ElectronApplication
let page: Page
let workspace = ''

/** Two hundred real spec files across four teams, with a spread of risk, status and people —
 * a board that only works at twenty is a demo, which is the spec's own phrasing. */
function writeSpecs(project: string): void {
  const specs = join(project, 'specs')
  mkdirSync(specs, { recursive: true })
  for (let i = 1; i <= SPEC_COUNT; i++) {
    const id = String(i).padStart(4, '0')
    const status = ['draft', 'ready', 'in-flight', 'merged'][i % 4]
    writeFileSync(join(specs, `${id}-synthetic-${i}.md`), `---
spec: "${id}"
name: "synthetic-${i}"
status: ${status}
type: feature
risk: ${['LOW', 'MEDIUM', 'HIGH'][i % 3]}
owner: "${i % 5 === 0 ? '@matt' : '@priya-n'}"
developer: "${i % 3 === 0 ? '@matt' : '@sam-k'}"
checker: "${i % 7 === 0 ? '@matt' : '@priya-n'}"
team: "${TEAMS[i % 4]}"
created: "2026-09-24"
---

# Spec ${id} — Synthetic board row ${i}

## Goal
A row on the board.
`, 'utf-8')
  }
}

/** Build Loop's own screens sit beneath it in the sidebar, and only once Build Loop is where you
 * are — so reaching one is two clicks: the stage, then the screen. */
async function openBuildView(target: Page, view: string) {
  await target.getByRole('button', { name: /^Build Loop/ }).click()
  await target.getByRole('button', { name: view, exact: true }).click()
}

test.describe('[spec 0011] the Build board in the real window', () => {
  test.skip(!PLUGIN_ROOT || !existsSync(VENV_PYTHON), 'needs a plugin checkout beside this repo')
  test.describe.configure({ mode: 'serial' })

  test.beforeAll(async () => {
    test.setTimeout(240_000)
    workspace = mkdtempSync(join(tmpdir(), 'studio-e2e-board-'))
    const project = join(workspace, 'project')

    execFileSync(VENV_PYTHON, [
      join(SCRIPTS_DIR, 'init_project.py'),
      '--profile', join(PLUGIN_ROOT!, 'profiles', 'microsoft-enterprise', 'profile.yaml'),
      '--target', project,
    ], { cwd: SCRIPTS_DIR })
    writeSpecs(project)

    const userData = join(workspace, 'userData')
    mkdirSync(userData, { recursive: true })
    writeFileSync(join(userData, 'settings.json'), JSON.stringify({
      recentProjects: [{ path: project, name: 'board project', lastOpenedAt: new Date().toISOString() }],
      pluginScriptsPathOverride: SCRIPTS_DIR,
    }, null, 2))

    app = await electron.launch({
      args: ['.', '--no-sandbox', `--user-data-dir=${userData}`],
      cwd: root,
      env: { ...process.env, NODE_ENV: 'development' },
    })
    page = await app.firstWindow()
    await expect(page.getByText('Loading…')).toHaveCount(0, { timeout: 30_000 })
    await page.getByText('board project').click()
    // Recorded pin change (togo-command-center.md §1, §8): the strip replaced the sidebar and the
    // Build station expands only on click, so "Documents" is not visible at rest; the landing
    // fact is `nav[aria-label=Project]`, as a11y.spec waits. Every other pin here is unchanged.
    await expect(page.getByRole('navigation', { name: 'Project' })).toBeVisible({ timeout: 30_000 })
  })

  test.afterAll(async () => {
    // Closing Electron and deleting a 200-spec workspace together exceed the default 30s
    // hook budget on a cold filesystem — which failed the whole suite while every assertion
    // in it had passed. Each step is also guarded, so one slow step cannot strand the rest.
    test.setTimeout(120_000)
    await page?.screenshot({ path: 'test/screenshots/spec-0011-board.png' }).catch(() => {})
    await app?.close().catch(() => {})
    try {
      if (workspace) rmSync(workspace, { recursive: true, force: true })
    } catch {
      // A leftover temp directory is untidy, not a failure worth reddening a green run.
    }
  })

  test('opens on what needs the signed-in person', async () => {
    await page.getByRole('button', { name: /^Build Loop/ }).click()
    await expect(page.getByRole('button', { name: 'Needs me' })).toBeVisible({ timeout: 60_000 })
    // It is the SELECTED view on arrival, not merely one of the options.
    await expect(page.getByRole('button', { name: 'Needs me' })).toHaveAttribute('aria-pressed', 'true')
  })

  test(`shows all ${SPEC_COUNT} specs, and says so`, async () => {
    await page.getByRole('button', { name: 'Everything' }).click()
    await expect(page.getByText(`${SPEC_COUNT} specs`)).toBeVisible()
  })

  test('each team card shows its work in flight', async () => {
    for (const team of TEAMS) {
      await expect(page.getByText(team, { exact: true }).first()).toBeVisible()
    }
  })

  test('switching a role view does not re-read the repository', async () => {
    // The spec's own requirement, and the reason the board fetches once and filters in
    // memory. Measured as time, because that is the observable consequence: a view that
    // re-read would take as long as the first load did, every time.
    const started = Date.now()
    for (const view of ['I own', "I'm building", 'I check', 'Everything', 'Needs me']) {
      await page.getByRole('button', { name: view }).click()
      await expect(page.getByRole('button', { name: view })).toHaveAttribute('aria-pressed', 'true')
    }
    const elapsed = Date.now() - started
    expect(elapsed, `five role switches took ${elapsed}ms — that looks like re-reading`).toBeLessThan(2000)
  })

  test(`a board of ${SPEC_COUNT} specs across ${TEAMS.length} teams opens in under two seconds`, async () => {
    // The acceptance check the reviewer is told to confirm was measured rather than assumed.
    // Timed from clicking Refresh to the board reporting its count, so it covers the fetch
    // AND the render — the half that was previously an untested assumption.
    await page.getByRole('button', { name: 'Everything' }).click()
    const started = Date.now()
    await page.getByRole('button', { name: 'Refresh' }).click()
    await expect(page.getByText(`${SPEC_COUNT} specs`)).toBeVisible({ timeout: 10_000 })
    const elapsed = Date.now() - started
    console.log(`[measured] ${SPEC_COUNT} specs, ${TEAMS.length} teams: ${elapsed}ms`)
    expect(elapsed).toBeLessThan(2000)
  })

  test('search and filters narrow the list', async () => {
    await page.getByPlaceholder('Search').fill('synthetic board row 42')
    await expect(page.getByText('1 shown')).toBeVisible()
    await page.getByPlaceholder('Search').fill('')
  })

  test('the status view offers no control that changes anything', async () => {
    await page.getByRole('button', { name: 'Everything' }).click()
    // A merged spec — nothing about it should be actionable at all. Narrowed to exactly one
    // row first, then clicked by position: a row's accessible name includes its people, team
    // and risk as well as its title, so matching on the title alone never anchors cleanly.
    await page.getByPlaceholder('Search').fill('synthetic board row 43')
    await expect(page.getByText('1 shown')).toBeVisible()
    await page.locator('main li button').first().click()
    await expect(page.getByText(/Owns it/)).toBeVisible({ timeout: 30_000 })

    // Absence, not disabled — the same standard spec 0010's edit mode is held to. The chat
    // composer (spec 0016) is excluded: it's a persistent conversational input on every screen
    // by design, not a document-editing control — every change it can cause still goes through
    // a proposal card the person must accept, so it doesn't violate what this check protects.
    await expect(page.getByRole('button', { name: /^Hand off$/ })).toHaveCount(0)
    await expect(page.locator('textarea:not([data-testid="chat-composer-input"])')).toHaveCount(0)
    await expect(page.locator('input')).toHaveCount(0)
  })

  /** The risk-tier control (spec 0011's own acceptance check, and its Decision List): raising
   * is free, but lowering a tier is refused unless a name is given, and that name is what gets
   * written to the spec. This was built correctly but had never been driven through the real
   * window — "looks right by reading the code" is exactly the standard this project exists to
   * reject, so this proves it rather than trusting the earlier read. Spec 124 is a DRAFT at
   * MEDIUM (124 % 4 === 0, 124 % 3 === 1) — draft/ready specs are the only ones whose status
   * view renders the readiness panel at all. */
  test('raising a risk tier is free; lowering one is refused without a name, and recorded with one', async () => {
    // The previous test left the app on a spec's status view (it never navigates back) —
    // "Everything" belongs to the board list, not the status view.
    await page.getByRole('button', { name: '← Back to the board' }).click()
    await page.getByRole('button', { name: 'Everything' }).click()
    await page.getByPlaceholder('Search').fill('synthetic board row 124')
    await expect(page.getByText('1 shown')).toBeVisible()
    await page.locator('main li button').first().click()
    await expect(page.getByText(/Owns it/)).toBeVisible({ timeout: 30_000 })

    const highButton = page.getByRole('button', { name: 'HIGH', exact: true })
    const lowButton = page.getByRole('button', { name: 'LOW', exact: true })

    // Raising needs nothing — no name field appears, and it takes effect immediately.
    await highButton.click()
    await expect(page.getByLabel(/Who authorised lowering this tier/)).toHaveCount(0)
    await expect(highButton).toHaveAttribute('aria-pressed', 'true', { timeout: 10_000 })

    // Lowering (now from HIGH) without a name is refused, in the plugin's own words, and the
    // name field only appears BECAUSE of that specific refusal.
    await lowButton.click()
    const authorisedByInput = page.getByLabel(/Who authorised lowering this tier/)
    await expect(authorisedByInput).toBeVisible({ timeout: 10_000 })
    // The plugin's own refusal reason, not Studio's — the field only exists because of it.
    await expect(page.getByText(/needs a name/i)).toBeVisible()
    await expect(lowButton).not.toHaveAttribute('aria-pressed', 'true')

    // Naming someone lets it through, and the field disappears again once it has.
    await authorisedByInput.fill('Matt K')
    await lowButton.click()
    await expect(lowButton).toHaveAttribute('aria-pressed', 'true', { timeout: 10_000 })
    await expect(page.getByLabel(/Who authorised lowering this tier/)).toHaveCount(0)
  })


  /** The settings screen (spec 0012), in the real window.
   *
   * Its two load-bearing promises are both about honesty rather than function, so neither can
   * be proven by a function test: every section must name the FILE its setting lives in, and a
   * setting nobody has configured must read as "not set up" rather than as an error. The
   * project this suite builds has configured none of them, which makes it the right fixture for
   * the second one.
   */
  /** The two read-only explainer screens (spec 0013).
   *
   * Both promises here are about honesty rather than function, so neither can be proven by a
   * function test: a measure with nothing behind it must read "no data" and never zero, and
   * the activity measures this standard refuses must be STATED as refused rather than merely
   * absent. The fixture project has no recorded events at all, which makes it the right one
   * for the first.
   */
  test.describe('[spec 0013] the explainer screens', () => {
    test('what Build inherited is read from the documents, and names each location', async () => {
      await openBuildView(page, 'How it is going')
      await expect(page.getByRole('heading', { name: 'What Build inherited' })).toBeVisible({ timeout: 60_000 })
      // Read from the documents, which is the spec's own requirement — a list written into
      // the app would look right until a template changed.
      await expect(page.getByText(/Read from the documents themselves/)).toBeVisible()
    })

    test('a document Foundation did not produce is SHOWN, not quietly omitted', async () => {
      // This fixture has no Foundation documents at all. A shorter list would hide exactly
      // the thing worth noticing: Build opened without them.
      await expect(page.getByRole('heading', { name: 'Not delivered' })).toBeVisible()
      await expect(page.getByText(/risk-tier-map\.md/).first()).toBeVisible()
      await expect(page.getByText(/not written down anywhere/)).toBeVisible()
    })

    test('a measure with nothing behind it reads no data, never zero', async () => {
      // Its own tab now — this area opens on Foundation, and a test that passed only because
      // of a default is one that breaks when the default moves.
      await page.getByRole('button', { name: 'How Build is going' }).click()
      await expect(page.getByRole('heading', { name: 'How Build is going' })).toBeVisible({ timeout: 60_000 })

      // "Nobody has merged anything yet" and "everything merged was rejected" are opposite
      // situations, and a zero shows them identically.
      await expect(page.getByText('no data').first()).toBeVisible()
      await expect(page.getByText(/No data in the last 14 days/)).toBeVisible()
      await expect(page.getByText(/empty record, not a score of zero/)).toBeVisible()
    })

    test('a measure with no data says what would produce some', async () => {
      await expect(page.getByText(/Produced by a merged spec recorded as accepted/)).toBeVisible()
    })

    test('the security review wait is on its own line', async () => {
      // Folded into an average, a slow security review is one nobody acts on.
      await expect(page.getByText(/Security review wait/)).toBeVisible()
    })

    test('the refused activity measures are STATED as refused, not just absent', async () => {
      // An absence explains nothing. Saying why they are not measured is what changes a
      // conversation in a steering meeting.
      await expect(page.getByText(/Not measured here, on purpose/)).toBeVisible()
      await expect(page.getByText(/Velocity, story points, pull-request counts and lines of code/)).toBeVisible()
      await expect(page.getByText(/measure activity rather than outcome/)).toBeVisible()
    })

    test('the gates screen names which guide describes them', async () => {
      await page.getByRole('button', { name: 'Checks and gates' }).click()
      await expect(page.getByRole('heading', { name: 'Checks and gates' })).toBeVisible({ timeout: 30_000 })
      await expect(page.getByText(/Shepherd does not\s+describe the gates itself/)).toBeVisible()
    })

    test('a gate the playbook ships but this project lacks is not shown as protecting anything', async () => {
      await expect(
        page.getByText(/The playbook ships these; this project does not run them/),
      ).toBeVisible()
      await expect(page.getByText(/not protecting anything here/)).toBeVisible()
    })
  })

  /** Declaring Build finished (spec 0014).
   *
   * This fixture has 200 specs in mixed states and no team confirmations, so it is exactly the
   * situation where a declaration must be refused — and refused in a way somebody can act on.
   */
  test.describe('[spec 0014] declaring Build finished', () => {
    test('it says what is outstanding rather than only refusing', async () => {
      await openBuildView(page, 'Closing')
      await expect(page.getByRole('heading', { name: 'Declaring Build finished' }))
        .toBeVisible({ timeout: 60_000 })
      // A refusal a person cannot act on is a wall. This one names the count and the items.
      await expect(page.getByText(/neither merged nor deferred/)).toBeVisible()
      await expect(page.getByText(/have not confirmed their own list/)).toBeVisible()
    })

    test('the declare button stays visible while it would be refused', async () => {
      // A hidden button makes the rule invisible; a visible one that explains itself teaches
      // it. This half holds on any machine.
      await expect(page.getByRole('button', { name: /Declare Build complete/ })).toBeVisible()
    })

    test('and pressing it shows the plugin\'s own reasons', async () => {
      // Studio attributes a declaration to the signed-in code-host account and will not
      // attribute an irreversible act to nobody, so the control is disabled when it does not
      // know who you are. That is deliberate — but it means this assertion has an unstated
      // precondition, satisfied on a developer machine by accident and never in CI, where no
      // user account can be signed in (the runner's token is not a person).
      //
      // So it says so instead of pretending. A skip naming the cause is information; a test
      // that hangs for thirty seconds against a disabled button is not.
      const declare = page.getByRole('button', { name: /Declare Build complete/ })
      test.skip(
        !(await declare.isEnabled()),
        'No code-host account is signed in — `gh auth login` (GitHub) or `az login` (Azure DevOps). '
        + 'Studio has nobody to attribute a declaration to and correctly disables the control.',
      )
      await declare.click()
      await expect(page.getByText(/neither merged nor deferred/).first()).toBeVisible()
    })

    test('a suggested deferral reason is offered but never pre-filled', async () => {
      // Spec 0014 asks for exactly this: a default reason gets accepted unread, which turns a
      // record of WHY into a record of the tool's wording.
      await page.getByRole('button', { name: /^Defer$/ }).first().click()
      const box = page.getByRole('textbox').last()
      await expect(box).toHaveValue('')
      await expect(page.getByRole('button', { name: /Start from a suggestion/ })).toBeVisible()
    })
  })

  test.describe('[spec 0012] the settings screen', () => {
    test('every section names the file its setting is stored in', async () => {
      await page.getByRole('button', { name: 'Settings', exact: true }).click()
      await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible({ timeout: 60_000 })

      // Named, even when the file does not exist yet — that is the point: a person has to know
      // where to go to create it.
      await expect(page.getByText('.sdlc/team.yaml')).toBeVisible()
      await expect(page.getByText('.sdlc/approval-settings.yaml')).toBeVisible()
      await expect(page.getByText(/cadence-plan\.md/)).toBeVisible()
    })

    test('an unconfigured setting reads as not set up, never as an error', async () => {
      // "You have not set this up" and "you set it up wrong" send a person to two different
      // places. This fixture has configured nothing, so every section should say the former.
      await expect(page.getByText(/has not set this up/).first()).toBeVisible()
      await expect(page.getByText(/could not be read cleanly/)).toHaveCount(0)
    })

    test('the connection checks distinguish no from could-not-tell', async () => {
      // Three states, never two. The fixture has no git remote, so the host-dependent checks
      // genuinely cannot look — and reporting those as "no" would send a person to fix a
      // project that is not broken.
      await expect(page.getByText(/Signed in to the code host\?/)).toBeVisible()
      await expect(page.getByText(/Any check the playbook expects but is missing\?/)).toBeVisible()
      await expect(page.getByText(/could not tell/).first()).toBeVisible()
    })

    test('a pipeline that is not expected of every project says why', async () => {
      // An absence with a reason is information; an absence without one reads as a gap.
      await page.getByText(/Pipelines not expected of every project/).click()
      await expect(page.getByText(/only a project that deploys needs this/).first()).toBeVisible()
    })

    test('each fixed rule says where it is actually enforced', async () => {
      // A rule listed without that is a claim nobody can check — and spec 0012's own
      // acceptance check was amended because one of them was not enforced anywhere.
      await expect(page.getByText(/Nobody checks their own work/)).toBeVisible()
      await expect(page.getByText(/handoff\.py refuses a developer who is also/)).toBeVisible()
      await expect(page.getByText(/Lowering a risk tier is recorded against whoever decided it/)).toBeVisible()
      // The claim that was removed must not reappear.
      await expect(page.getByText(/only a team lead/i)).toHaveCount(0)
    })
  })
})

/** Spec 0013's own fixture (above) has no cadence-plan.md and no recorded events, which is
 * the right setup for proving "no data" — but the wrong one for proving the alarm banner
 * itself, which needs both to exist. A separate app instance, because the shared 200-spec
 * fixture above is deliberately event-less and must stay that way for those tests to mean
 * anything. */
test.describe('[spec 0013] review-wait alarms by team, in the real window', () => {
  test.skip(!PLUGIN_ROOT || !existsSync(VENV_PYTHON), 'needs a plugin checkout beside this repo')

  let alarmApp: ElectronApplication
  let alarmPage: Page
  let alarmWorkspace = ''

  test.beforeAll(async () => {
    test.setTimeout(120_000)
    alarmWorkspace = mkdtempSync(join(tmpdir(), 'studio-e2e-alarms-'))
    const project = join(alarmWorkspace, 'project')

    execFileSync(VENV_PYTHON, [
      join(SCRIPTS_DIR, 'init_project.py'),
      '--profile', join(PLUGIN_ROOT!, 'profiles', 'microsoft-enterprise', 'profile.yaml'),
      '--target', project,
    ], { cwd: SCRIPTS_DIR })

    mkdirSync(join(project, '.sdlc', 'artifacts', '03-foundation'), { recursive: true })
    writeFileSync(join(project, '.sdlc', 'artifacts', '03-foundation', 'cadence-plan.md'), `# Cadence Plan

## WIP Limits

| team | wip_limit | review_alarm_hours | security_alarm_hours |
|------|-----------|---------------------|-----------------------|
| claims | 3 | 12 | 24 |

## Hardening passes
- none
`, 'utf-8')

    // A real event, recorded the way a real project's history would populate it — not
    // hand-crafted JSONL that could drift from what record_event() actually writes.
    execFileSync(VENV_PYTHON, [
      join(SCRIPTS_DIR, 'scorecard.py'), 'record', '--repo', project,
      '--type', 'review_wait', '--field', 'wait_hours=30',
    ], { cwd: SCRIPTS_DIR })

    const userData = join(alarmWorkspace, 'userData')
    mkdirSync(userData, { recursive: true })
    writeFileSync(join(userData, 'settings.json'), JSON.stringify({
      recentProjects: [{ path: project, name: 'alarm project', lastOpenedAt: new Date().toISOString() }],
      pluginScriptsPathOverride: SCRIPTS_DIR,
    }, null, 2))

    alarmApp = await electron.launch({
      args: ['.', '--no-sandbox', `--user-data-dir=${userData}`],
      cwd: root,
      env: { ...process.env, NODE_ENV: 'development' },
    })
    alarmPage = await alarmApp.firstWindow()
    await expect(alarmPage.getByText('Loading…')).toHaveCount(0, { timeout: 30_000 })
    await alarmPage.getByText('alarm project').click()
    await expect(alarmPage.getByText('Documents').first()).toBeVisible({ timeout: 30_000 })
  })

  test.afterAll(async () => {
    test.setTimeout(60_000)
    await alarmPage?.screenshot({ path: 'test/screenshots/spec-0013-alarms.png' }).catch(() => {})
    await alarmApp?.close().catch(() => {})
    try {
      if (alarmWorkspace) rmSync(alarmWorkspace, { recursive: true, force: true })
    } catch {
      // A leftover temp directory is untidy, not a failure worth reddening a green run.
    }
  })

  test('a team over its review-wait alarm is named, with the real threshold', async () => {
    await openBuildView(alarmPage, 'How it is going')
    await alarmPage.getByRole('button', { name: 'How Build is going' }).click()
    await expect(alarmPage.getByRole('heading', { name: 'Review-wait alarms by team' }))
      .toBeVisible({ timeout: 60_000 })
    await expect(alarmPage.getByText('claims')).toBeVisible()
    // The real threshold from the fixture's cadence-plan.md, not a guessed or default one.
    await expect(alarmPage.getByText(/review vs 12h/)).toBeVisible()
    await expect(alarmPage.getByText(/OVER ALARM/)).toBeVisible()
  })

  test('the same alarm is named on the settings screen, next to the team it belongs to', async () => {
    // Spec 0012's check, closed with the same data this describe block already proved on the
    // scorecard screen — no second computation, just a second screen reading it.
    await alarmPage.getByRole('button', { name: 'Settings', exact: true }).click()
    await expect(alarmPage.getByText('claims')).toBeVisible({ timeout: 60_000 })
    await expect(alarmPage.getByText(/review-wait alarm sounding/)).toBeVisible()
    // This fixture recorded no security-wait event at all — the security alarm must stay
    // silent rather than borrow the review alarm's state (correctness review's own finding:
    // an earlier version collapsed both into one flag and one label).
    await expect(alarmPage.getByText(/security-review-wait alarm sounding/)).toHaveCount(0)
  })
})

/** The exact defect correctness review found: a team can be over its SECURITY alarm with no
 * review-wait data at all (review_wait_median_hours is null, not zero). The describe block
 * above never exercises this — it only ever records a plain review-wait event — so this is a
 * separate fixture, not an extra assertion bolted onto that one. */
test.describe('[spec 0012] a team over only its security alarm, in the real window', () => {
  test.skip(!PLUGIN_ROOT || !existsSync(VENV_PYTHON), 'needs a plugin checkout beside this repo')

  let secApp: ElectronApplication
  let secPage: Page
  let secWorkspace = ''

  test.beforeAll(async () => {
    test.setTimeout(120_000)
    secWorkspace = mkdtempSync(join(tmpdir(), 'studio-e2e-secalarm-'))
    const project = join(secWorkspace, 'project')

    execFileSync(VENV_PYTHON, [
      join(SCRIPTS_DIR, 'init_project.py'),
      '--profile', join(PLUGIN_ROOT!, 'profiles', 'microsoft-enterprise', 'profile.yaml'),
      '--target', project,
    ], { cwd: SCRIPTS_DIR })

    mkdirSync(join(project, '.sdlc', 'artifacts', '03-foundation'), { recursive: true })
    writeFileSync(join(project, '.sdlc', 'artifacts', '03-foundation', 'cadence-plan.md'), `# Cadence Plan

## WIP Limits

| team | wip_limit | review_alarm_hours | security_alarm_hours |
|------|-----------|---------------------|-----------------------|
| platform | 2 | 24 | 24 |

## Hardening passes
- none
`, 'utf-8')

    // Only a SECURITY wait, never a plain one — review_wait_median_hours stays null (no data),
    // which is exactly the state the earlier, buggy label rendering mishandled.
    execFileSync(VENV_PYTHON, [
      join(SCRIPTS_DIR, 'scorecard.py'), 'record', '--repo', project,
      '--type', 'review_wait', '--field', 'wait_hours=100', '--field', 'security=true',
    ], { cwd: SCRIPTS_DIR })

    const userData = join(secWorkspace, 'userData')
    mkdirSync(userData, { recursive: true })
    writeFileSync(join(userData, 'settings.json'), JSON.stringify({
      recentProjects: [{ path: project, name: 'security alarm project', lastOpenedAt: new Date().toISOString() }],
      pluginScriptsPathOverride: SCRIPTS_DIR,
    }, null, 2))

    secApp = await electron.launch({
      args: ['.', '--no-sandbox', `--user-data-dir=${userData}`],
      cwd: root,
      env: { ...process.env, NODE_ENV: 'development' },
    })
    secPage = await secApp.firstWindow()
    await expect(secPage.getByText('Loading…')).toHaveCount(0, { timeout: 30_000 })
    await secPage.getByText('security alarm project').click()
    await expect(secPage.getByText('Documents').first()).toBeVisible({ timeout: 30_000 })
  })

  test.afterAll(async () => {
    test.setTimeout(60_000)
    await secApp?.close().catch(() => {})
    try {
      if (secWorkspace) rmSync(secWorkspace, { recursive: true, force: true })
    } catch {
      // A leftover temp directory is untidy, not a failure worth reddening a green run.
    }
  })

  test('names the security alarm with its own figure, and never borrows the review label', async () => {
    await secPage.getByRole('button', { name: 'Settings', exact: true }).click()
    await expect(secPage.getByText('platform')).toBeVisible({ timeout: 60_000 })
    await expect(secPage.getByText(/security-review-wait alarm sounding \(100h\)/)).toBeVisible()
    // The exact defect: with no review-wait data at all, the old code showed
    // "review-wait alarm sounding (h)" — a blank figure under the wrong label. Excludes the
    // security line itself, which legitimately contains "review-wait" as a substring.
    await expect(secPage.getByText(/(?<!security-)review-wait alarm sounding/)).toHaveCount(0)
  })
})
