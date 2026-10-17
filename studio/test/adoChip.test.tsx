// @vitest-environment jsdom
/** The Azure Boards chip on the spec card (build kit §5 B4-P3). It says what the plugin's `status --json`
 * says about the work-item mirror and nothing it did not measure: never pulled, never set up, unreadable
 * and "drift on this spec" are WORDS (no digit, no zero); steering mode draws it as a status with no
 * control that writes; and a plan to review opens the apply dialog (whose own Confirm is the write).
 * The chip never opens the mirror's files and never spawns `az`: it reads the command center's `ado` block,
 * or is handed one. `window.studio` is a PARTIAL double.
 *
 * `HOST_FEATURE` at the bottom pins the `'workItems'` case this package adds to `hostFeatureReason`. */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AdoSyncView } from '../shared/adoTypes'
import type { ActorInfo, BoardRow, CommandCenter, ConnectionInfo, SourcedBlock, SpecCard as SpecCardRead } from '../shared/types'
import { hostFeatureReason, WORDING } from '../shared/codeHostModel'
import { CAPABILITIES, FORBIDDEN_METRIC_WORDS, NO_DATA, NOT_PULLED_YET, WORK_ITEMS_NOT_SET_UP, newerPlugin } from '../shared/reasons'
import { AdoChip, adoChipView } from '../src/components/ado/AdoChip'
import { readAdoPlan } from '../src/components/ado/AdoApplyDialog'
import { SpecCard } from '../src/components/SpecCard/SpecCard'
import { connectionStore, resetConnectionStore } from '../src/stores/connectionStore'

const GOLDEN = resolve(__dirname, '..', '..', 'scripts', 'tests', 'golden', 'ado_status_nodata.json')
/** The plugin's own never-pulled `status --json` document — captured, not hand-written. */
const NEVER_PULLED = JSON.parse(readFileSync(GOLDEN, 'utf-8')) as AdoSyncView

const HASH = '1d0617c03373'
const ACTOR: ActorInfo = { name: '@sam-k', source: 'roster' }
const block = <T,>(data: T | null, error: string | null = null): SourcedBlock<T> => ({ source: 'ado_sync.py status --json', fetchedAt: 'now', ok: data !== null, data, error })

/** A pulled status, HAND-WRITTEN (unverified): the keys are `AdoSyncView`'s, the values are made up. */
const PULLED: AdoSyncView = {
  as_of: '2026-10-12T09:00:00Z', by_class: { SDLC_OWNED_DRIFT: 1 },
  counts: { conflicts: 0, debt: 1, drifted: 2, linked: 12, open: 3, pending: 1 },
  debt: [
    { ref: 'sdlc:spec:0008', field: 'System.State', class: 'SDLC_OWNED_DRIFT', seen: '2026-10-07', due: '2026-10-09' },
    { ref: 'sdlc:spec:0008', field: 'Custom.RiskTier', class: 'SDLC_OWNED_DRIFT', seen: '2026-10-07', due: '2026-10-09' },
    { ref: 'sdlc:spec:0011', field: null, class: 'CONFLICT', seen: '2026-10-07', due: '2026-10-09' },
  ],
  hook_line: 'ado: 12 linked · 1 pending · 2 drifted', last_plan: { plan: HASH, ts: '2026-10-12T09:00:00Z', rows: 3 }, ledger: '.sdlc/metrics/ado-sync-log.jsonl', notes: [], schema: 1,
}

const PLAN_JSON = {
  ok: true, unavailable: false, reason: null, plan: HASH, posture: 'assisted', executed_as: '@sam-k',
  rows: [{ ref: 'sdlc:spec:0008', kind: 'spec', id: '0008', action: 'update', reason: null, work_item: 4521, rev: 7, type: 'User Story', ops: [{ op: 'replace', path: '/fields/System.State', old: 'Active', new: 'Ready' }], notes: [] }],
}
const NOTHING_TO_SEND = { ok: true, unavailable: false, reason: null, plan: HASH, posture: 'assisted', executed_as: '@sam-k', rows: [{ ref: 'sdlc:spec:0008', kind: 'spec', id: '0008', action: 'held', reason: '#4522 is gone from the board', work_item: 4522, ops: [], notes: [] }] }

const BASE_CONNECTION: ConnectionInfo = {
  repo: 'acme/app', branch: 'main', localFolder: '/p', account: '@sam-k', accountSource: 'roster', rosterHandle: '@sam-k',
  host: 'azure-devops', hostSource: 'remote', cli: { name: 'az', found: true, extension: true, signedIn: 'yes' }, lastPulledAt: null, branchProtected: null,
}

let getCommandCenter: ReturnType<typeof vi.fn>
let runAdoVerb: ReturnType<typeof vi.fn>
const centerWith = (ado: SourcedBlock<AdoSyncView> | undefined) => ({ ...(ado ? { ado } : {}) }) as unknown as CommandCenter

beforeEach(() => {
  getCommandCenter = vi.fn().mockResolvedValue(centerWith(block(PULLED)))
  runAdoVerb = vi.fn().mockResolvedValue({ ok: true, exitCode: 0, refused: false, stdout: 'applied 1 row', stderr: '', argv: [], verb: 'apply', json: null })
  // @ts-expect-error - partial test double: only what the chip reaches
  window.studio = { getCommandCenter, runAdoVerb }
})
afterEach(async () => {
  cleanup()
  // Radix's FocusScope sends its unmount event from a setTimeout(0) scheduled during cleanup. Let that timer fire
  // while jsdom is still this file's environment: a file that ends right after closing a dialog otherwise reports an
  // unhandled "parameter 1 is not of type 'Event'" at teardown (Node's own CustomEvent by then). Same-delay timers
  // fire in the order they were set, so one macrotask after cleanup is enough.
  await new Promise((resolve) => setTimeout(resolve, 0))
  resetConnectionStore()
  // @ts-expect-error - cleaning up the test double
  delete window.studio
})

const chip = () => screen.getByTestId('ado-chip')
const stateOf = () => chip().getAttribute('data-state')

function mount(over: Partial<Parameters<typeof AdoChip>[0]> = {}) {
  const props = { projectPath: '/p', specId: '0008', capabilities: [CAPABILITIES.adoStatus, CAPABILITIES.adoApply], actor: ACTOR, ...over }
  render(<main><AdoChip {...props} /></main>)
  return props
}

describe('adoChipView — what the status document lets the chip say', () => {
  const view = (over: Partial<Parameters<typeof adoChipView>[0]> = {}) => adoChipView({ block: block(PULLED), notSetUp: false, specId: '0001', ...over })

  it('a project whose host is not Azure DevOps has no work items: the sentence, nothing else', () => {
    const v = view({ block: null, notSetUp: true })
    expect(v.state).toBe('not-set-up')
    expect(v.text).toBe(WORK_ITEMS_NOT_SET_UP)
    expect(v.tone).toBe('neutral')
  })

  it('a status that was not read is "no data", with the plugin\'s own sentence kept as the detail — never a zeroed count', () => {
    expect(view({ block: null }).text).toBe(`Work items · ${NO_DATA}`)
    const plugin = view({ block: block<AdoSyncView>(null, 'ado_sync.py gave no readable answer') })
    expect(plugin.state).toBe('no-data')
    expect(plugin.text).toBe(`Work items · ${NO_DATA}`)
    expect(plugin.detail).toBe('ado_sync.py gave no readable answer')
    const older = view({ block: null, unreadReason: newerPlugin(CAPABILITIES.adoStatus) })
    expect(older.detail).toBe(newerPlugin(CAPABILITIES.adoStatus))
  })

  it('the plugin\'s never-pulled golden is "Not pulled yet" — words, not a 0 beside a label', () => {
    const v = view({ block: block(NEVER_PULLED) })
    expect(v.state).toBe('not-pulled')
    expect(v.text).toBe(`Work items · ${NOT_PULLED_YET}`)
    expect(v.detail).toContain('the mirror has never pulled')
  })

  it('every state with nothing measured is digit-free and free of the forbidden metric words', () => {
    const states = [
      view({ block: null, notSetUp: true }), view({ block: null }), view({ block: block<AdoSyncView>(null, 'unreadable') }),
      view({ block: null, unreadReason: newerPlugin(CAPABILITIES.adoStatus) }), view({ block: block(NEVER_PULLED) }),
    ]
    for (const v of states) {
      expect(v.text, v.state).not.toMatch(/\d/)
      expect(v.text, v.state).not.toMatch(FORBIDDEN_METRIC_WORDS)
    }
  })

  it('an open drift or conflict on THIS spec past its two business days is drift, by field — never by person', () => {
    const v = view({ specId: '0008' })
    expect(v.state).toBe('drift')
    expect(v.tone).toBe('warn')
    expect(v.text).toBe('Work items · drift on System.State, Custom.RiskTier')
    expect(v.detail).toContain('SDLC_OWNED_DRIFT')
    expect(v.detail).toContain('2026-10-09')
    expect(view({ specId: '0011' }).text).toBe('Work items · drift on the whole item')
  })

  it('otherwise it carries the plugin\'s own one-line summary, as the project\'s — it does not claim this spec is in sync', () => {
    const v = view({ specId: '0001' })
    expect(v.state).toBe('status')
    expect(v.tone).toBe('neutral')
    expect(v.text).toBe(`Work items · ${PULLED.hook_line}`)
    expect(v.detail).toContain('project')
    expect(v.detail).toContain(PULLED.as_of as string)
    expect(v.text).not.toMatch(/in sync/i)
  })

  it('a ref that only shares a prefix with this spec is not this spec (0008 is not 00081)', () => {
    const doc: AdoSyncView = { ...PULLED, debt: [{ ref: 'sdlc:spec:00081', field: 'System.State', class: 'SDLC_OWNED_DRIFT', seen: 'a', due: 'b' }] }
    expect(view({ block: block(doc), specId: '0008' }).state).toBe('status')
  })
})

describe('AdoChip', () => {
  it('draws the state it is handed: never pulled reads in words, has no control and no digit', () => {
    mount({ ado: block(NEVER_PULLED), plan: null })
    expect(stateOf()).toBe('not-pulled')
    expect(chip().textContent).toBe(`Work items · ${NOT_PULLED_YET}`)
    expect(chip().textContent).not.toMatch(/\d/)
    expect(document.querySelectorAll('button')).toHaveLength(0)
    expect(getCommandCenter).not.toHaveBeenCalled()
  })

  it('with no block handed in it reads the command center once and draws its `ado` block', async () => {
    mount({ specId: '0008' })
    await waitFor(() => expect(stateOf()).toBe('drift'))
    expect(getCommandCenter).toHaveBeenCalledTimes(1)
    expect(getCommandCenter).toHaveBeenCalledWith('/p')
    expect(chip().textContent).toBe('Work items · drift on System.State, Custom.RiskTier')
  })

  it('draws nothing while the first read is out — no flash of "no data" for a block that is on its way', () => {
    getCommandCenter.mockReturnValue(new Promise(() => {}))
    mount()
    expect(screen.queryByTestId('ado-chip')).toBeNull()
  })

  it.each([
    ['a command center with no `ado` block (the no-plugin answer)', () => getCommandCenter.mockResolvedValue(centerWith(undefined))],
    ['a read that rejects', () => getCommandCenter.mockRejectedValue(new Error('no plugin'))],
    ['a block the plugin could not give', () => getCommandCenter.mockResolvedValue(centerWith(block<AdoSyncView>(null, 'ado_sync.py gave no readable answer')))],
  ])('%s is "no data", not a zero and not an error screen', async (_label, arrange) => {
    arrange()
    mount()
    await waitFor(() => expect(stateOf()).toBe('no-data'))
    expect(chip().textContent).toBe(`Work items · ${NO_DATA}`)
    expect(chip().textContent).not.toMatch(/\d/)
  })

  it('a bridge with no getCommandCenter (an older preload) is "no data" at once', async () => {
    // @ts-expect-error - a bridge without the command center
    window.studio = {}
    mount()
    await waitFor(() => expect(stateOf()).toBe('no-data'))
  })

  it('a plugin without ado-status-json is not asked: "no data", with the newer-plugin sentence as the detail', async () => {
    mount({ capabilities: ['sprint-status'] })
    await waitFor(() => expect(stateOf()).toBe('no-data'))
    expect(chip().getAttribute('title')).toBe(newerPlugin(CAPABILITIES.adoStatus))
    expect(getCommandCenter).not.toHaveBeenCalled()
  })

  it('capabilities not known yet leave the plugin to answer: the read happens', async () => {
    mount({ capabilities: undefined })
    await waitFor(() => expect(stateOf()).toBe('drift'))
    expect(getCommandCenter).toHaveBeenCalledTimes(1)
  })

  it('a project on GitHub (or on no host) says work items are not set up and reads nothing', () => {
    connectionStore.set({ ...BASE_CONNECTION, host: 'github', cli: { name: 'gh', found: true, extension: null, signedIn: 'yes' } })
    mount()
    expect(stateOf()).toBe('not-set-up')
    expect(chip().textContent).toBe(WORK_ITEMS_NOT_SET_UP)
    expect(getCommandCenter).not.toHaveBeenCalled()
  })

  it('an Azure DevOps project with no az still reads the mirror\'s status: the status is the plugin\'s ledger, not the board', async () => {
    connectionStore.set({ ...BASE_CONNECTION, cli: { name: 'az', found: false, extension: null, signedIn: 'unknown', reason: WORDING.azMissing } })
    mount({ specId: '0008' })
    await waitFor(() => expect(stateOf()).toBe('drift'))
  })

  describe('the plan to review', () => {
    it('is offered as "Review plan" only when the plan has rows an apply would send; it is a read, so not a write control', () => {
      mount({ ado: block(PULLED), plan: readAdoPlan(PLAN_JSON) })
      const open = screen.getByRole('button', { name: 'Review plan' })
      expect(open.hasAttribute('data-write')).toBe(false)
      expect((open as HTMLButtonElement).disabled).toBe(false)
    })

    it.each([
      ['no plan', null],
      ['a plan with nothing an apply would send', readAdoPlan(NOTHING_TO_SEND)],
      ['a plan that could not be drawn up', readAdoPlan({ ok: true, unavailable: true, reason: 'not configured', host: null, plan: null, rows: [] })],
    ])('offers nothing for %s', (_label, plan) => {
      mount({ ado: block(PULLED), plan })
      expect(screen.queryByRole('button', { name: 'Review plan' })).toBeNull()
    })

    it('opens the apply dialog on the plan\'s rows; its Confirm is the one write, and sends the hash through runAdoVerb', async () => {
      const onApplied = vi.fn()
      mount({ ado: block(PULLED), plan: readAdoPlan(PLAN_JSON), onApplied })
      expect(screen.queryByTestId('ado-apply-dialog')).toBeNull()
      fireEvent.click(screen.getByRole('button', { name: 'Review plan' }))
      const dialog = await screen.findByTestId('ado-apply-dialog')
      expect(dialog.querySelectorAll('[data-plan-row]')).toHaveLength(PLAN_JSON.rows.length)
      const confirm = screen.getByRole('button', { name: /^Confirm — apply to Azure Boards/ })
      expect(confirm.hasAttribute('data-write')).toBe(true)
      fireEvent.click(confirm)
      await waitFor(() => expect(runAdoVerb).toHaveBeenCalledWith('/p', { verb: 'apply', confirm: HASH }))
      await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1))
    })

    it('after an apply that landed, a chip that reads for itself reads again', async () => {
      mount({ plan: readAdoPlan(PLAN_JSON) })
      await waitFor(() => expect(stateOf()).toBe('drift'))
      expect(getCommandCenter).toHaveBeenCalledTimes(1)
      fireEvent.click(screen.getByRole('button', { name: 'Review plan' }))
      fireEvent.click(await screen.findByRole('button', { name: /^Confirm — apply to Azure Boards/ }))
      await waitFor(() => expect(getCommandCenter).toHaveBeenCalledTimes(2))
    })

    it('without ado-apply the dialog still reads, and its Confirm says which capability a newer plugin brings', async () => {
      mount({ ado: block(PULLED), plan: readAdoPlan(PLAN_JSON), capabilities: [CAPABILITIES.adoStatus] })
      fireEvent.click(screen.getByRole('button', { name: 'Review plan' }))
      const confirm = (await screen.findByRole('button', { name: /^Confirm — apply to Azure Boards/ })) as HTMLButtonElement
      expect(confirm.disabled).toBe(true)
      expect(confirm.getAttribute('title')).toBe(newerPlugin(CAPABILITIES.adoApply))
    })
  })

  describe('steering mode', () => {
    it('draws the status and nothing that writes: zero data-write, zero buttons — even with a plan that has rows to send', () => {
      mount({ ado: block(PULLED), plan: readAdoPlan(PLAN_JSON), steering: true, specId: '0008' })
      expect(chip().textContent).toBe('Work items · drift on System.State, Custom.RiskTier')
      expect(document.querySelectorAll('[data-write]')).toHaveLength(0)
      expect(document.querySelectorAll('button')).toHaveLength(0)
      expect(document.querySelectorAll('input, textarea')).toHaveLength(0)
      expect(screen.queryByTestId('ado-apply-dialog')).toBeNull()
    })

    it('the no-data states stay words in steering too', () => {
      mount({ ado: block(NEVER_PULLED), steering: true })
      expect(chip().textContent).toBe(`Work items · ${NOT_PULLED_YET}`)
      expect(document.querySelectorAll('[data-write]')).toHaveLength(0)
    })
  })
})

// ── the SpecCard mount ───────────────────────────────────────────────────────────────────────────

const ROW: BoardRow = {
  spec: '0008', name: 'claim-export', path: 'specs/0008-claim-export.md', title: 'Claim export', status: 'draft',
  risk: 'MEDIUM', team: 'platform', channel: '', owner: '@sam-k', developer: '', checker: '@priya-n', branch: '',
  sprint: 'S07', nextOwner: '', engReview: '', dataReview: '', dependsOn: [], pullRequest: null,
}
const LADDER = { tier: 'MEDIUM', touchesGatedPath: null, rungs: ['CI (lint, unit) — blocks'] }
type PullRequest = NonNullable<SpecCardRead['status']['data']>['pull_request']
const PR: PullRequest = {
  number: 42, url: 'https://example.invalid/pr/42', state: 'OPEN', merged_at: null, checks: [], grader_ran: false, verdicts: [], verdict_error: null,
  security_review: null, approvals: [], waiting_on: 'waiting for CI',
} as unknown as PullRequest
const specCardRead = (pullRequest: PullRequest | null): SpecCardRead => ({
  spec: '0008', path: ROW.path,
  readiness: block({ ok: true, spec: '0008', risk: 'MEDIUM', status: 'draft', ready: true, blocking: [], advisory: [], passed: [], ladder: LADDER }),
  ladder: block(LADDER),
  status: block({ spec: '0008', branch: 'spec/0008-claim-export', code_host_available: true, pull_request: pullRequest }),
  findings: block({ tracked: 0, openDebt: 0, fixedClaimMismatches: 0, findings: [], recurrence: {}, attribution: { method: 'scope-paths', attributed: 0, unattributed: 0 } }),
  channel: null,
  handoffCheck: block({ ok: true }),
} as unknown as SpecCardRead)

describe('SpecCard mounts the chip beside the PR chip', () => {
  async function renderCard(pullRequest: PullRequest | null) {
    // @ts-expect-error - partial test double: only what the card and the chip reach
    window.studio = { getSpecCard: vi.fn().mockResolvedValue(specCardRead(pullRequest)), openDocument: vi.fn().mockResolvedValue({ ok: true, path: ROW.path, shaped: true, warnings: [], sections: [] }), getCommandCenter, runAdoVerb }
    render(<main><SpecCard projectPath="/p" row={ROW} actor={ACTOR} capabilities={[CAPABILITIES.adoStatus]} onBack={vi.fn()} onHandOff={vi.fn()} /></main>)
    await screen.findByTestId('spec-ladder')
    await waitFor(() => expect(screen.queryByTestId('ado-chip')).not.toBeNull())
  }
  const follows = (before: Element, after: Element) => Boolean(before.compareDocumentPosition(after) & Node.DOCUMENT_POSITION_FOLLOWING)

  it('sits in the facts row right after "no PR yet", and carries this spec\'s id', async () => {
    await renderCard(null)
    const facts = screen.getByTestId('spec-facts')
    expect(facts.contains(chip())).toBe(true)
    expect(follows(screen.getByTestId('no-pr'), chip())).toBe(true)
    await waitFor(() => expect(stateOf()).toBe('drift'))
  })

  it('sits right after the pull request link when there is one', async () => {
    await renderCard(PR)
    const link = within(screen.getByTestId('spec-facts')).getByRole('link', { name: /#42/ })
    expect(follows(link, chip())).toBe(true)
  })

  it('adds no input and no write control at rest — the card\'s own "no <input>" pin still holds', async () => {
    await renderCard(null)
    expect(document.querySelectorAll('input')).toHaveLength(0)
    expect(screen.getByTestId('spec-facts').querySelectorAll('[data-write]')).toHaveLength(0)
  })
})

// ── HOST_FEATURE: the 'workItems' case ───────────────────────────────────────────────────────────

describe('hostFeatureReason(…, "workItems") — HOST_FEATURE', () => {
  const gh = { host: 'github' as const, cli: { name: 'gh' as const, found: true, extension: null, signedIn: 'yes' as const } }
  const none = { host: 'none' as const, cli: { name: 'gh' as const, found: true, extension: null, signedIn: 'yes' as const } }
  const az = (cli: Partial<typeof BASE_CONNECTION.cli>) => ({ host: 'azure-devops' as const, cli: { ...BASE_CONNECTION.cli, ...cli } })

  it('WORDING.boardsNotConfigured is the reasons.ts sentence, digit-free', () => {
    expect(WORDING.boardsNotConfigured).toBe(WORK_ITEMS_NOT_SET_UP)
    expect(WORDING.boardsNotConfigured).not.toMatch(/\d/)
  })

  it('a project that is not on Azure DevOps has no work items, whatever its CLI says — and on no host it is not the pull-request sentence', () => {
    expect(hostFeatureReason(gh, 'workItems')).toBe(WORDING.boardsNotConfigured)
    expect(hostFeatureReason(none, 'workItems')).toBe(WORDING.boardsNotConfigured)
    expect(hostFeatureReason(none, 'workItems')).not.toBe(WORDING.hostNone)
    expect(hostFeatureReason({ ...gh, cli: { ...gh.cli, found: false } }, 'workItems')).toBe(WORDING.boardsNotConfigured)
  })

  it('an Azure DevOps project with az in place has nothing in the way; one without it names the Azure CLI', () => {
    expect(hostFeatureReason(az({}), 'workItems')).toBeNull()
    expect(hostFeatureReason(az({ signedIn: 'unknown' }), 'workItems')).toBeNull()
    expect(hostFeatureReason(az({ found: false }), 'workItems')).toContain('Azure CLI')
    expect(hostFeatureReason(az({ extension: false }), 'workItems')).toContain('Azure CLI')
    expect(hostFeatureReason(az({ signedIn: 'no' }), 'workItems')).toContain('Azure CLI')
  })

  it('leaves every earlier feature\'s sentence where it was', () => {
    expect(hostFeatureReason(az({ found: false }), 'board')).toBe('Live pull-request status needs the Azure CLI')
    expect(hostFeatureReason(none, 'board')).toBe(WORDING.hostNone)
    expect(hostFeatureReason(gh, 'board')).toBeNull()
  })
})
