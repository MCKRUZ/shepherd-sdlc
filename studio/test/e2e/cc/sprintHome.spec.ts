/** The sprint home in the real window (togo-command-center.md §3.1, §7 P7).
 *
 * The promises a component test cannot make: that a Build-loop project LANDS on the sprint
 * home (`homeFor`, chosen once per open); that the lane keys are real keyboard events in the
 * real window (`j j ↵` opens the third card, `h` the hand-off dialog pre-filled); that the
 * baton's text is the plugin's `handoffs_open` row and the needs-you chip is the length of the
 * list main addressed to the signed-in person; and that a verdict the plugin REFUSES (exit 2)
 * reads "Refused by the plugin" with the plugin's own stderr — forced through the test hook
 * `STUDIO_TEST_FORCE_BY=Claude`, because `typedActor.ts` rightly refuses to let a person sign
 * in under an AI-looking name.
 *
 * The lanes are a partition of `status` (sprint.py never writes `status`; the fixture sets it
 * the way board.spec does): 0001 in-flight with both verdicts accepted → Building; 0002
 * in-flight with verdicts pending → Checking; 0003 merged → Merged. Ready stays empty: nothing
 * scaffolded passes the DoR, and that is the plugin's call, not the fixture's. */

import { existsSync } from 'node:fs'
import { expect, test, type ElectronApplication, type Page } from '@playwright/test'
import {
  enterBuildLoop, handoffTo, HANDOFF_TO, newProject, newSprint, openOverdueDecision, PLUGIN_ROOT, setFrontmatter,
  slate, sprintStatus, VENV_PYTHON, verdict, writeRoster, type Fixture,
} from './fixture'
import { ASSUMED, closeApp, ensureActor, launch, openProject, refreshScreen, SEL, seedSettings, sprintHomeVisible, TEXT } from './shell'

interface StatusView { handoffs_open: { spec: string; to: string; since_business_days: number | null }[] }

function buildLoopFixture(prefix: string): Fixture {
  const fx = newProject(prefix)
  enterBuildLoop(fx.project)
  writeRoster(fx.project)
  const [a, b, c] = fx.specIds
  newSprint(fx.project)
  // Slate first: `sprint.py slate` refuses a merged spec ("slating delivered work is not a
  // commitment"), so the statuses that make the lanes are set after the commitment, as they
  // would be in life.
  slate(fx.project, fx.specIds)
  setFrontmatter(fx.specPath[a], 'status', 'in-flight')
  setFrontmatter(fx.specPath[b], 'status', 'in-flight')
  setFrontmatter(fx.specPath[c], 'status', 'merged')
  verdict(fx.project, a, 'eng', 'accepted')
  verdict(fx.project, a, 'data', 'accepted')
  handoffTo(fx.project, b, HANDOFF_TO)
  return fx
}

test.describe('[command center P7] the sprint home in the real window', () => {
  test.skip(!PLUGIN_ROOT || !existsSync(VENV_PYTHON), 'needs a plugin checkout beside this repo')
  test.describe.configure({ mode: 'serial' })

  let app: ElectronApplication
  let page: Page
  let fx: Fixture
  let actor = ''
  let thirdCard = ''

  test.beforeAll(async () => {
    test.setTimeout(240_000)
    fx = buildLoopFixture('cc-sprint-home')
    seedSettings(fx.userData, fx.project, 'sprint home project')
    ;({ app, page } = await launch(fx.userData))
    await openProject(page, 'sprint home project')
    // The decision is opened AFTER the actor is known: its owner must be the signed-in person
    // by exact match, whoever the host (or the typed-name form) says that is.
    actor = await ensureActor(page, fx.project)
    openOverdueDecision(fx.project, actor, `Confirm risk tier for ${fx.specIds[0]} (proposed HIGH)`)
    await refreshScreen(page)
  })

  test.afterAll(async () => {
    test.setTimeout(120_000)
    await closeApp(app, page, 'cc-sprint-home')
  })

  test('a Build-loop project lands on the sprint home, not on a document list', async () => {
    await sprintHomeVisible(page)
    await expect(page.locator(SEL.sprintHeader)).toContainText('S07')
    await expect(page.locator(SEL.sprintHeader)).toContainText('Adjusters file without a phone call')
    // Home is the lit Build view (nav.ts BUILD_VIEWS: `sprint` relabelled Home).
    await expect(page.locator('[aria-current="page"]')).toHaveCount(1)
    await expect(page.locator(`main ${SEL.laneScope}`)).toBeVisible()
    await expect(page.locator(ASSUMED.laneCard)).toHaveCount(3)
  })

  test('the lanes are a partition of the plugin\'s status: one card each in Building, Checking, Merged', async () => {
    const [a, b, c] = fx.specIds
    for (const [id, lane] of [[a, 'building'], [b, 'checking'], [c, 'merged']] as const) {
      const card = page.locator(`${ASSUMED.laneCard}[data-spec="${id}"]`)
      await expect(card).toHaveCount(1)
      await expect(card).toHaveAttribute('data-lane', lane)
    }
    // No Approve control anywhere — the code host's non-author approval is the only one (§5).
    await expect(page.locator('main').getByRole('button', { name: /^Approve$/ })).toHaveCount(0)
  })

  test('the baton on the Building→Checking edge reads the plugin\'s handoffs_open row', async () => {
    const view = sprintStatus<StatusView>(fx.project)
    expect(view.handoffs_open).toHaveLength(1)
    const [row] = view.handoffs_open
    const baton = page.locator(ASSUMED.baton)
    await expect(baton).toBeVisible()
    await expect(baton).toContainText(`${row.spec} → ${row.to}`)
  })

  test('the needs-you chip is the length of the list addressed to me: one overdue decision', async () => {
    // The hand-off went to Sam K, not to me; the verdicts have a lane, not a person; the one
    // item addressed to me is DL-01 — so the chip is exactly one, not a count of everything.
    const chip = page.locator(ASSUMED.needsYouChip)
    await expect(chip).toContainText(/needs you · 1\b/)
    const today = page.locator(ASSUMED.today)
    await expect(today).toContainText('DL-01')
    await expect(today.getByRole('button', { name: /^Decide/ })).toHaveCount(1)
    // The hand-off is the team's, under "Team is waiting on" — never "yours".
    await expect(today).not.toContainText(`${fx.specIds[1]} → ${actor}`)
  })

  test('j j ↵ opens the third card in place; Esc returns to the lanes', async () => {
    const cards = page.locator(ASSUMED.laneCard)
    thirdCard = (await cards.nth(2).getAttribute('data-spec')) ?? ''
    expect(thirdCard).toMatch(/^\d{4}$/)
    await page.locator(SEL.laneScope).focus()
    await page.keyboard.press('j')
    await page.keyboard.press('j')
    await page.keyboard.press('Enter')
    const card = page.locator(ASSUMED.specCard)
    await expect(card).toBeVisible({ timeout: 30_000 })
    await expect(card).toHaveAttribute('data-spec', thirdCard)
    await page.keyboard.press('Escape')
    await expect(card).toHaveCount(0)
    await expect(page.locator(SEL.laneScope)).toBeVisible()
  })

  test('h on a focused card opens the hand-off dialog pre-filled with that spec', async () => {
    await page.locator(SEL.laneScope).focus()
    await page.keyboard.press('j')
    const focused = await page.evaluate(() => (document.activeElement as HTMLElement | null)?.closest('[data-spec]')?.getAttribute('data-spec') ?? '')
    expect(focused).toMatch(/^\d{4}$/)
    await page.keyboard.press('h')
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible({ timeout: 10_000 })
    await expect(dialog).toContainText(focused)
    await expect(dialog).toContainText(/hand/i)
    // Nothing ran: a dialog is a proposal; only Confirm (`data-write`) runs the verb.
    await expect(dialog.locator(SEL.writeControl)).toHaveCount(1)
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
  })

  test('no number on the home is Shepherd\'s own: no digit inside a person chip, no bare 0 in a stat', async () => {
    const chips = await page.locator(SEL.personChip).allTextContents()
    for (const text of chips) expect(text).not.toMatch(/\d/)
    const stats = await page.locator(SEL.stat).allTextContents()
    for (const text of stats) expect(text).not.toMatch(/\b0\b/)
    await expect(page.locator(SEL.sprintHeader)).toContainText('cap not set')
  })
})

/** The plugin's refusal, verbatim. `actor.ts` reads `STUDIO_TEST_FORCE_BY` outside production
 * and passes that name as `--by`; sprint.py's `require_human` answers exit 2. A separate app,
 * because the hook is process-wide. */
test.describe('[command center P7] a verdict the plugin refuses reads as the plugin\'s refusal', () => {
  test.skip(!PLUGIN_ROOT || !existsSync(VENV_PYTHON), 'needs a plugin checkout beside this repo')

  let app: ElectronApplication
  let page: Page
  let fx: Fixture

  test.beforeAll(async () => {
    test.setTimeout(240_000)
    fx = buildLoopFixture('cc-refused')
    seedSettings(fx.userData, fx.project, 'refused project')
    ;({ app, page } = await launch(fx.userData, { STUDIO_TEST_FORCE_BY: 'Claude' }))
    await openProject(page, 'refused project')
    await sprintHomeVisible(page)
  })

  test.afterAll(async () => {
    test.setTimeout(120_000)
    await closeApp(app, page, 'cc-refused-verdict')
  })

  test('exit 2 renders "Refused by the plugin" with sprint.py\'s own stderr, and no spec changed', async () => {
    const checking = page.locator(`${ASSUMED.laneCard}[data-lane="checking"]`).first()
    await checking.focus()
    await page.keyboard.press('v')
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible({ timeout: 10_000 })
    await dialog.getByText('accepted', { exact: true }).click()
    await dialog.locator(SEL.writeControl).click()
    const result = page.locator(ASSUMED.verbResult)
    await expect(result).toBeVisible({ timeout: 60_000 })
    await expect(result).toContainText(TEXT.refused)
    await expect(result).toContainText("Refused: --by 'Claude' reads as an AI/automation, not a named human.")
    await expect(result).not.toContainText(TEXT.done)
    // The frontmatter is untouched: the refusal happened before any write.
    const view = sprintStatus<{ slate: { id: string; eng_review: string }[] }>(fx.project)
    const row = view.slate.find((r) => r.id === fx.specIds[1])
    expect(row?.eng_review).toBe('')
  })
})
