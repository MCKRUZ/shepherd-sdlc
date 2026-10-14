// @vitest-environment jsdom
/** `Pull now` and the spec card's Boards zone (build kit §5 B5-P4; design §12 items 6 and 10).
 *
 * `PullNow` is two buttons — `Pull now` (the board's FIELDS, into the ledger) and `Pull discussion` (the board's
 * COMMENTS, into the local cache) — each a `data-write`, each one closed request through `runAdoVerb`, neither on a
 * timer, neither drawn in steering mode. It says what the plugin said under the exit code alone, and an exit 0 that
 * carries `unavailable` is NOT "Done": the plugin exits 0 on every path that is not a usage error, so an unreachable
 * board or a discussion switched off is read from the JSON.
 *
 * `DiscussionBlock` mounts it; `SpecCard` mounts the block below the facts rail (composer inside) and a Boards row
 * (`Pull now`, `Plan changes`) that is NOT inside the facts row — the chip's own pin ("no write control at rest in
 * `spec-facts`") still holds. `Plan changes` RUNS NOTHING: the closed `AdoVerbRequest` table is the build kit's
 * seven verbs and `plan` is not one of them (it writes a plan file and a ledger line), so the card shows the plugin
 * lines that plan this spec and send that plan — as the Today row's Propose spec does — and the chip is never
 * handed a plan from here. `window.studio` is a PARTIAL double.
 *
 * Every plugin document below is HAND-WRITTEN (unverified): its shape is read from `ado_sync.py` (`cmd_pull`,
 * `_pull_discussion`), not captured from a live board. */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AdoSyncView } from '../shared/adoTypes'
import type { AdoVerbRequest } from '../shared/adoVerbArgv'
import type { ActorInfo, AdoVerbResult, BoardRow, CommandCenter, ConnectionInfo, SourcedBlock, SpecCard as SpecCardRead } from '../shared/types'
import {
  BOARDS_UNREACHABLE, CAPABILITIES, EXIT_HEADING, newerPlugin, SCHEMA_NOT_DISCOVERED, WORK_ITEMS_NOT_SET_UP,
} from '../shared/reasons'
import { PullNow, PULL_RUNNING } from '../src/components/ado/PullNow'
import { DiscussionBlock } from '../src/components/ado/DiscussionBlock'
import { PLAN_CAPABILITY, PLAN_NOT_RUN, planLines, SpecCard } from '../src/components/SpecCard/SpecCard'
import { connectionStore, resetConnectionStore } from '../src/stores/connectionStore'

const REF = 'sdlc:spec:0008'
const ACTOR: ActorInfo = { name: '@sam-k', source: 'roster' }
const CAPS = ['ado-pull', 'ado-pull-discussion'] as const
const ALL_CAPS = [CAPABILITIES.adoStatus, 'ado-pull', 'ado-pull-discussion', 'ado-show', 'ado-comment', 'ado-apply', 'ado-plan', 'ado-reconcile'] as const

function res(verb: AdoVerbResult['verb'], exitCode: 0 | 1 | 2 | null, json: Record<string, unknown> | null, over: Partial<AdoVerbResult> = {}): AdoVerbResult {
  return { ok: exitCode === 0, exitCode, refused: exitCode === 2, stdout: '', stderr: '', argv: [], verb, json, ...over }
}

/** `pull --json` (hand-written, unverified): `cmd_pull`'s `out`. */
const PULLED = {
  ok: true, unavailable: false, reason: null, as_of: '2026-10-13T09:02:00Z', items: [], counts: {}, unmatched_ids: [], proposals: [],
  recorded: { observed: 3, drift_seen: 1 }, hook_line: '1 rows pending · 1 drifted · as of 2026-10-13T09:02Z', notes: [],
}
/** `pull --discussion --json` (hand-written, unverified): `_pull_discussion`'s document. */
const DISCUSSION_PULLED = {
  ok: true, discussion: 'pulled', as_of: '2026-10-13T09:02:00Z', skipped: 0, unmatched_ids: [], cost: 'cost: 1 item read',
  items: [{ ref: REF, work_item: 4521, comments: 2, new: 1, edited: 0, deleted: 0, truncated: false, unavailable: null }],
}
const SHOW = {
  ok: true, work_item: 4521, ref: REF, cached: true, as_of: '2026-10-12T09:02:00Z', unavailable: null, notes: [],
  rendered: [`Work item #4521 (${REF}) · discussion pulled 2026-10-12T09:02:00Z`, 'Comment 7 · @sam-k · 2026-10-11T12:00:00Z', '  | Looks right to me.'].join('\n'),
}

let runAdoVerb: ReturnType<typeof vi.fn<(projectPath: string, request: AdoVerbRequest) => Promise<AdoVerbResult>>>

beforeEach(() => {
  runAdoVerb = vi.fn()
  // @ts-expect-error - partial test double: only what these components reach
  window.studio = { runAdoVerb }
})
afterEach(async () => {
  vi.useRealTimers()
  cleanup()
  // Radix's FocusScope sends its unmount event from a setTimeout(0) scheduled during cleanup (see adoApplyDialog.test).
  await new Promise((resolve) => setTimeout(resolve, 0))
  resetConnectionStore()
  // @ts-expect-error - cleaning up the test double
  delete window.studio
})

/** A disabled kit Button carries its reason as hidden text inside itself, so a name is matched from its start. */
const buttonNamed = (name: string) => screen.getByRole('button', { name: new RegExp(`^${name}`) }) as HTMLButtonElement
const verbsCalled = () => runAdoVerb.mock.calls.map(([, request]) => request)

// ── PullNow itself ───────────────────────────────────────────────────────────────────────────────

describe('PullNow: two data-write buttons, neither on a timer', () => {
  it('draws Pull now (fields) and Pull discussion (cache), each a data-write, and runs nothing at rest', () => {
    vi.useFakeTimers()
    render(<PullNow projectPath="/p" itemRef={REF} capabilities={[...CAPS]} />)
    expect(buttonNamed('Pull now').hasAttribute('data-write')).toBe(true)
    expect(buttonNamed('Pull discussion').hasAttribute('data-write')).toBe(true)
    expect(document.querySelectorAll('[data-write]')).toHaveLength(2)
    // neither on a timer: a day passes and nothing was asked of the plugin
    act(() => { vi.advanceTimersByTime(24 * 60 * 60 * 1000) })
    expect(runAdoVerb).not.toHaveBeenCalled()
  })

  it('scope picks which of the two are drawn: both (the default), fields only, discussion only', () => {
    const { rerender } = render(<PullNow projectPath="/p" capabilities={[...CAPS]} />)
    expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(['Pull now', 'Pull discussion'])
    rerender(<PullNow projectPath="/p" capabilities={[...CAPS]} scope="fields" />)
    expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(['Pull now'])
    rerender(<PullNow projectPath="/p" capabilities={[...CAPS]} scope="discussion" />)
    expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(['Pull discussion'])
  })

  it('Pull now is one closed `pull` request, scoped to the item, once; Pull discussion is one `pullDiscussion`', async () => {
    runAdoVerb.mockResolvedValue(res('pull', 0, PULLED))
    render(<PullNow projectPath="/p" itemRef={REF} capabilities={[...CAPS]} />)
    fireEvent.click(buttonNamed('Pull now'))
    await screen.findByTestId('fields-pull-result')
    expect(runAdoVerb).toHaveBeenCalledTimes(1)
    expect(runAdoVerb).toHaveBeenCalledWith('/p', { verb: 'pull', id: REF })
    runAdoVerb.mockResolvedValue(res('pullDiscussion', 0, DISCUSSION_PULLED))
    fireEvent.click(buttonNamed('Pull discussion'))
    await screen.findByTestId('discussion-pull-result')
    expect(runAdoVerb).toHaveBeenCalledTimes(2)
    expect(runAdoVerb).toHaveBeenLastCalledWith('/p', { verb: 'pullDiscussion', id: REF })
  })

  it('with no item it asks for every ledgered item: the request has no id at all', async () => {
    runAdoVerb.mockResolvedValue(res('pull', 0, PULLED))
    render(<PullNow projectPath="/p" capabilities={[...CAPS]} />)
    fireEvent.click(buttonNamed('Pull now'))
    await screen.findByTestId('fields-pull-result')
    expect(verbsCalled()).toEqual([{ verb: 'pull' }])
    expect('id' in verbsCalled()[0]!).toBe(false)
  })

  it('an exit 0 says Done with the plugin\'s own as-of and counts, and tells the host what it read', async () => {
    runAdoVerb.mockResolvedValue(res('pull', 0, PULLED))
    const onPulled = vi.fn()
    render(<PullNow projectPath="/p" itemRef={REF} capabilities={[...CAPS]} onPulled={onPulled} />)
    fireEvent.click(buttonNamed('Pull now'))
    const said = await screen.findByTestId('fields-pull-result')
    expect(said.getAttribute('data-tone')).toBe('ok')
    expect(said.textContent).toContain(EXIT_HEADING[0])
    expect(said.textContent).toContain('2026-10-13 09:02')
    expect(said.textContent).toContain('3 items read')
    expect(said.textContent).toContain('1 drift row recorded')
    expect(onPulled).toHaveBeenCalledTimes(1)
    expect(onPulled.mock.calls[0]![0]).toBe('fields')
    expect(onPulled.mock.calls[0]![1].json).toEqual(PULLED)
  })

  it('a discussion pull says how many items it read and keeps an item the plugin could not cache, in the plugin\'s words', async () => {
    const doc = { ...DISCUSSION_PULLED, items: [...DISCUSSION_PULLED.items, { ref: 'sdlc:spec:0009', work_item: 4522, unavailable: 'not cached: OSError' }] }
    runAdoVerb.mockResolvedValue(res('pullDiscussion', 0, doc))
    const onPulled = vi.fn()
    render(<PullNow projectPath="/p" itemRef={REF} capabilities={[...CAPS]} scope="discussion" onPulled={onPulled} />)
    fireEvent.click(buttonNamed('Pull discussion'))
    const said = await screen.findByTestId('discussion-pull-result')
    expect(said.textContent).toContain('1 item read')   // the one it could not cache is not counted as read
    expect(said.textContent).toContain('sdlc:spec:0009')
    expect(said.textContent).toContain('not cached: OSError')
    expect(onPulled).toHaveBeenCalledWith('discussion', expect.objectContaining({ exitCode: 0 }))
  })

  it('exit 1 and exit 2 are said under their own headings with the plugin\'s stderr; the host is not told it pulled', async () => {
    const onPulled = vi.fn()
    runAdoVerb.mockResolvedValue(res('pull', 1, null, { stderr: 'DRIFT: the ledger cannot be appended to' }))
    render(<PullNow projectPath="/p" itemRef={REF} capabilities={[...CAPS]} onPulled={onPulled} />)
    fireEvent.click(buttonNamed('Pull now'))
    let said = await screen.findByTestId('fields-pull-result')
    expect(said.textContent).toContain(EXIT_HEADING[1])
    expect(said.textContent).toContain('DRIFT: the ledger cannot be appended to')
    expect(said.getAttribute('data-tone')).not.toBe('ok')
    runAdoVerb.mockResolvedValue(res('pull', 2, null, { stderr: 'Refused: not a person' }))
    fireEvent.click(buttonNamed('Pull now'))
    await waitFor(() => expect(screen.getByTestId('fields-pull-result').textContent).toContain(EXIT_HEADING[2]))
    said = screen.getByTestId('fields-pull-result')
    expect(said.textContent).toContain('Refused: not a person')
    expect(onPulled).not.toHaveBeenCalled()
  })

  it('an exit 0 that says unavailable is never Done: the board could not be reached, in Shepherd\'s digit-free words plus the plugin\'s reason', async () => {
    const onPulled = vi.fn()
    runAdoVerb.mockResolvedValue(res('pull', 0, { ok: true, unavailable: true, reason: 'az: not signed in', host: { name: 'azure-devops', cli: 'az', cli_state: 'signed-out' }, items: [] }))
    render(<PullNow projectPath="/p" itemRef={REF} capabilities={[...CAPS]} onPulled={onPulled} />)
    fireEvent.click(buttonNamed('Pull now'))
    const said = await screen.findByTestId('fields-pull-result')
    expect(said.textContent).toContain(BOARDS_UNREACHABLE)
    expect(said.textContent).toContain('az: not signed in')
    expect(said.textContent).not.toContain(EXIT_HEADING[0])
    expect(said.getAttribute('data-tone')).toBe('warn')
    expect(onPulled).not.toHaveBeenCalled()
    runAdoVerb.mockResolvedValue(res('pull', 0, { ok: true, unavailable: true, reason: 'not configured: no .sdlc/ado.yaml', items: [] }))
    fireEvent.click(buttonNamed('Pull now'))
    await waitFor(() => expect(screen.getByTestId('fields-pull-result').textContent).toContain(WORK_ITEMS_NOT_SET_UP))
    runAdoVerb.mockResolvedValue(res('pull', 0, { ok: true, unavailable: true, reason: 'no discovered schema: run `ado_sync.py discover` first', items: [] }))
    fireEvent.click(buttonNamed('Pull now'))
    await waitFor(() => expect(screen.getByTestId('fields-pull-result').textContent).toContain(SCHEMA_NOT_DISCOVERED))
  })

  it('a discussion the config switched off is the plugin\'s reason, not Done; no host refresh', async () => {
    const onPulled = vi.fn()
    runAdoVerb.mockResolvedValue(res('pullDiscussion', 0, { ok: true, discussion: 'disabled', reason: 'the board discussion is switched off', items: [], skipped: 0 }))
    render(<PullNow projectPath="/p" itemRef={REF} capabilities={[...CAPS]} onPulled={onPulled} />)
    fireEvent.click(buttonNamed('Pull discussion'))
    const said = await screen.findByTestId('discussion-pull-result')
    expect(said.textContent).toContain('the board discussion is switched off')
    expect(said.textContent).not.toContain(EXIT_HEADING[0])
    expect(onPulled).not.toHaveBeenCalled()
  })

  it('a bridge without runAdoVerb, and a request the table refuses, are sentences — nothing is spawned', async () => {
    // @ts-expect-error - the bridge of an older app
    window.studio = {}
    const { unmount } = render(<PullNow projectPath="/p" itemRef={REF} capabilities={[...CAPS]} />)
    fireEvent.click(buttonNamed('Pull now'))
    expect((await screen.findByTestId('fields-pull-result')).textContent).toContain(EXIT_HEADING[1])
    unmount()
    // @ts-expect-error - partial test double
    window.studio = { runAdoVerb }
    render(<PullNow projectPath="/p" itemRef="AB#4521" capabilities={[...CAPS]} />)
    fireEvent.click(buttonNamed('Pull now'))
    expect((await screen.findByTestId('fields-pull-result')).textContent).toContain('AB#4521')
    expect(runAdoVerb).not.toHaveBeenCalled()
  })

  it('one pull at a time: while one runs the other is disabled with its reason, and a second click is not a second spawn', async () => {
    let release: (value: AdoVerbResult) => void = () => {}
    runAdoVerb.mockImplementation(() => new Promise<AdoVerbResult>((resolve) => { release = resolve }))
    render(<PullNow projectPath="/p" itemRef={REF} capabilities={[...CAPS]} />)
    fireEvent.click(buttonNamed('Pull now'))
    fireEvent.click(document.querySelector('[data-pull="fields"]') as HTMLElement)
    const other = document.querySelector('[data-pull="discussion"]') as HTMLButtonElement
    expect(other.disabled).toBe(true)
    expect(other.getAttribute('title')).toBe(PULL_RUNNING)
    fireEvent.click(other)
    expect(runAdoVerb).toHaveBeenCalledTimes(1)
    await act(async () => { release(res('pull', 0, PULLED)) })
    await screen.findByTestId('fields-pull-result')
    expect((document.querySelector('[data-pull="discussion"]') as HTMLButtonElement).disabled).toBe(false)
  })

  it('a plugin without the capability disables that button with newerPlugin(cap); unknown capabilities leave it to the plugin', () => {
    const { rerender } = render(<PullNow projectPath="/p" capabilities={['ado-show']} />)
    expect(buttonNamed('Pull now').disabled).toBe(true)
    expect(buttonNamed('Pull now').getAttribute('title')).toBe(newerPlugin('ado-pull'))
    expect(buttonNamed('Pull discussion').getAttribute('title')).toBe(newerPlugin('ado-pull-discussion'))
    rerender(<PullNow projectPath="/p" capabilities={['ado-pull']} />)
    expect(buttonNamed('Pull now').disabled).toBe(false)
    expect(buttonNamed('Pull discussion').disabled).toBe(true)
    rerender(<PullNow projectPath="/p" capabilities={null} />)
    expect(buttonNamed('Pull now').disabled).toBe(false)
    expect(buttonNamed('Pull discussion').disabled).toBe(false)
  })

  it('steering mode draws nothing at all: no button, no data-write, nothing run', () => {
    const { container } = render(<PullNow projectPath="/p" itemRef={REF} capabilities={[...CAPS]} steering />)
    expect(container.innerHTML).toBe('')
    expect(runAdoVerb).not.toHaveBeenCalled()
  })
})

// ── DiscussionBlock mounts it ────────────────────────────────────────────────────────────────────

describe('DiscussionBlock carries PullNow', () => {
  function answer(others: Partial<Record<AdoVerbResult['verb'], AdoVerbResult>> = {}) {
    runAdoVerb.mockImplementation(async (_p, request) => (request.verb === 'show' ? res('show', 0, SHOW) : others[request.verb] ?? res(request.verb, 0, PULLED)))
  }
  type BlockProps = Parameters<typeof DiscussionBlock>[0]
  const mountBlock = (over: Partial<BlockProps> = {}) => render(<DiscussionBlock projectPath="/p" itemRef={REF} capabilities={[...ALL_CAPS]} {...over} />)

  it('has both buttons by default; Pull now runs `pull` for the item and does not re-read the discussion', async () => {
    answer()
    mountBlock()
    await screen.findByTestId('discussion-list')
    expect(buttonNamed('Pull now').hasAttribute('data-write')).toBe(true)
    expect(buttonNamed('Pull discussion').hasAttribute('data-write')).toBe(true)
    fireEvent.click(buttonNamed('Pull now'))
    await screen.findByTestId('fields-pull-result')
    expect(verbsCalled()).toEqual([{ verb: 'show', ref: REF }, { verb: 'pull', id: REF }])
  })

  it('Pull discussion still re-reads the discussion afterwards (the cache it just wrote)', async () => {
    answer({ pullDiscussion: res('pullDiscussion', 0, DISCUSSION_PULLED) })
    mountBlock()
    await screen.findByTestId('discussion-list')
    fireEvent.click(buttonNamed('Pull discussion'))
    await waitFor(() => expect(verbsCalled()).toEqual([{ verb: 'show', ref: REF }, { verb: 'pullDiscussion', id: REF }, { verb: 'show', ref: REF }]))
  })

  it('pull="discussion" leaves only Pull discussion (the spec card keeps Pull now beside the chip)', async () => {
    answer()
    mountBlock({ pull: 'discussion' })
    await screen.findByTestId('discussion-list')
    expect(screen.queryByRole('button', { name: /^Pull now/ })).toBeNull()
    expect(buttonNamed('Pull discussion')).toBeTruthy()
  })

  it('onPulled hears about each pull; steering shows the rows and no pull control at all', async () => {
    answer()
    const onPulled = vi.fn()
    const { unmount } = mountBlock({ onPulled })
    await screen.findByTestId('discussion-list')
    fireEvent.click(buttonNamed('Pull now'))
    await waitFor(() => expect(onPulled).toHaveBeenCalledWith('fields', expect.objectContaining({ verb: 'pull' })))
    unmount()
    runAdoVerb.mockClear()
    const steered = mountBlock({ steering: true })
    await screen.findByTestId('discussion-list')
    expect(steered.container.querySelectorAll('[data-write], button')).toHaveLength(0)
    expect(screen.queryByTestId('pull-now')).toBeNull()
  })
})

// ── the spec card ────────────────────────────────────────────────────────────────────────────────

const ROW: BoardRow = {
  spec: '0008', name: 'claim-export', path: 'specs/0008-claim-export.md', title: 'Claim export', status: 'draft',
  risk: 'MEDIUM', team: 'platform', channel: '', owner: '@sam-k', developer: '', checker: '@priya-n', branch: '',
  sprint: 'S07', nextOwner: '', engReview: '', dataReview: '', dependsOn: [], pullRequest: null,
}
const LADDER = { tier: 'MEDIUM', touchesGatedPath: null, rungs: ['CI (lint, unit) — blocks'] }
const block = <T,>(data: T | null, error: string | null = null): SourcedBlock<T> => ({ source: 'ado_sync.py status --json', fetchedAt: 'now', ok: data !== null, data, error })
const specCardRead = (): SpecCardRead => ({
  spec: '0008', path: ROW.path,
  readiness: block({ ok: true, spec: '0008', risk: 'MEDIUM', status: 'draft', ready: true, blocking: [], advisory: [], passed: [], ladder: LADDER }),
  ladder: block(LADDER),
  status: block({ spec: '0008', branch: 'spec/0008-claim-export', code_host_available: true, pull_request: null }),
  findings: block({ tracked: 0, openDebt: 0, fixedClaimMismatches: 0, findings: [], recurrence: {}, attribution: { method: 'scope-paths', attributed: 0, unattributed: 0 } }),
  channel: null,
  handoffCheck: block({ ok: true }),
} as unknown as SpecCardRead)

const STATUS: AdoSyncView = {
  as_of: '2026-10-12T09:00:00Z', by_class: {}, counts: { conflicts: 0, debt: 0, drifted: 0, linked: 12, open: 0, pending: 1 }, debt: [],
  hook_line: 'ado: 12 linked · 1 pending', last_plan: null, ledger: '.sdlc/metrics/ado-sync-log.jsonl', notes: [], schema: 1,
}

const AZURE: ConnectionInfo = {
  repo: 'acme/app', branch: 'main', localFolder: '/p', account: '@sam-k', accountSource: 'roster', rosterHandle: '@sam-k',
  host: 'azure-devops', hostSource: 'remote', cli: { name: 'az', found: true, extension: true, signedIn: 'yes' }, lastPulledAt: null, branchProtected: null,
}

describe('SpecCard: the Boards zone', () => {
  let getCommandCenter: ReturnType<typeof vi.fn>

  beforeEach(() => {
    getCommandCenter = vi.fn().mockResolvedValue({ ado: block(STATUS) } as unknown as CommandCenter)
    runAdoVerb.mockImplementation(async (_p, request) => {
      if (request.verb === 'show') return res('show', 0, SHOW)
      if (request.verb === 'pull') return res('pull', 0, PULLED)
      return res(request.verb, 0, {})
    })
    // @ts-expect-error - partial test double: only what the card, the chip and the block reach
    window.studio = { getSpecCard: vi.fn().mockResolvedValue(specCardRead()), openDocument: vi.fn().mockResolvedValue({ ok: true, path: ROW.path, shaped: true, warnings: [], sections: [] }), getCommandCenter, runAdoVerb }
    connectionStore.set(AZURE)
  })

  async function mountCard(over: Partial<Parameters<typeof SpecCard>[0]> = {}) {
    render(<main><SpecCard projectPath="/p" row={ROW} actor={ACTOR} capabilities={[...ALL_CAPS]} onBack={vi.fn()} onHandOff={vi.fn()} {...over} /></main>)
    await screen.findByTestId('spec-ladder')
  }
  const follows = (before: Element, after: Element) => Boolean(before.compareDocumentPosition(after) & Node.DOCUMENT_POSITION_FOLLOWING)
  const chip = () => screen.getByTestId('ado-chip')

  it('mounts the Discussion block below the facts rail, composer inside, reading the spec\'s own ref', async () => {
    await mountCard()
    const discussion = await screen.findByTestId('discussion-block')
    await screen.findByTestId('discussion-list')
    expect(follows(screen.getByTestId('spec-facts-disclosure'), discussion)).toBe(true)
    expect(within(discussion).getByTestId('comment-composer')).toBeTruthy()
    expect(verbsCalled()).toContainEqual({ verb: 'show', ref: REF })
    // the block carries Pull discussion; Pull now lives beside the chip, so each button is on the card once
    expect(screen.getAllByRole('button', { name: /^Pull discussion/ })).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: /^Pull now/ })).toHaveLength(1)
  })

  it('keeps the chip\'s pin: no write control inside the facts row; Pull now and Plan changes sit in a Boards row of their own', async () => {
    await mountCard()
    await waitFor(() => expect(chip()).toBeTruthy())
    expect(screen.getByTestId('spec-facts').querySelectorAll('[data-write]')).toHaveLength(0)
    const boards = screen.getByTestId('spec-boards')
    expect(screen.getByTestId('spec-facts').contains(boards)).toBe(false)
    expect(follows(screen.getByTestId('spec-facts'), boards)).toBe(true)
    expect(within(boards).getByRole('button', { name: /^Pull now/ }).hasAttribute('data-write')).toBe(true)
    // Plan changes runs nothing (it shows the plugin lines), so it is not a write control either
    expect(within(boards).getByRole('button', { name: /^Plan changes/ }).hasAttribute('data-write')).toBe(false)
  })

  it('opening the card never plans or pulls: only the discussion is read, and no timer changes that', async () => {
    await mountCard()
    await screen.findByTestId('discussion-list')
    expect(new Set(verbsCalled().map((r) => r.verb))).toEqual(new Set(['show']))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(new Set(verbsCalled().map((r) => r.verb))).toEqual(new Set(['show']))
  })

  it('Plan changes shows this spec\'s plugin lines and runs nothing: no request, no Review plan, nothing ledgered', async () => {
    await mountCard()
    await waitFor(() => expect(chip().getAttribute('data-state')).toBe('status'))
    await screen.findByTestId('discussion-list')
    const before = runAdoVerb.mock.calls.length
    expect(screen.queryByRole('button', { name: /^Review plan/ })).toBeNull()
    const button = within(screen.getByTestId('spec-boards')).getByRole('button', { name: /^Plan changes/ })
    expect(button.getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByTestId('plan-lines')).toBeNull()
    fireEvent.click(button)
    const shown = screen.getByTestId('plan-lines')
    expect(button.getAttribute('aria-expanded')).toBe('true')
    expect(shown.textContent).toContain(PLAN_NOT_RUN)
    expect([...shown.querySelectorAll('code')].map((c) => c.textContent)).toEqual(planLines('0008'))
    expect(planLines('0008')).toEqual(['ado_sync.py plan --kind spec --id 0008', 'ado_sync.py apply --confirm <hash> --by <your handle>'])
    await new Promise((resolve) => setTimeout(resolve, 20))
    // nothing was asked of the plugin by the click: the only requests are the discussion read the card made on open
    expect(runAdoVerb.mock.calls.length).toBe(before)
    expect(new Set(verbsCalled().map((r) => r.verb))).toEqual(new Set(['show']))
    expect(verbsCalled().some((r) => /plan/i.test(String(r.verb)))).toBe(false)
    expect(screen.queryByRole('button', { name: /^Review plan/ })).toBeNull()
    fireEvent.click(button)
    expect(screen.queryByTestId('plan-lines')).toBeNull()
    expect(button.getAttribute('aria-expanded')).toBe('false')
  })

  it('the lines it shows are the plugin\'s own: plan --kind spec --id, apply --confirm --by, and ado-plan a declared capability', () => {
    const PLUGIN = resolve(__dirname, '..', '..')
    const cli = readFileSync(resolve(PLUGIN, 'scripts', 'ado_sync.py'), 'utf-8')
    expect(cli).toMatch(/sub\.add_parser\("plan"/)
    expect(cli).toMatch(/p\.add_argument\("--kind", action="append"/)
    expect(cli).toMatch(/p\.add_argument\("--id", action="append", metavar="ID",\s+help="Only this item: its id \(0004/)
    expect(cli).toMatch(/sub\.add_parser\("apply"[\s\S]{0,400}p\.add_argument\("--confirm"[\s\S]{0,300}p\.add_argument\("--by"/)
    const contract = readFileSync(resolve(PLUGIN, 'scripts', 'boards_contract.py'), 'utf-8')
    expect(contract).toMatch(/^KINDS[^=]*= \([^)]*"spec"/m)
    const caps = readFileSync(resolve(PLUGIN, 'scripts', 'capabilities.py'), 'utf-8')
    expect(caps).toMatch(new RegExp(`"${PLAN_CAPABILITY}": \\{"script": "ado_sync\\.py", "argv": \\["plan"\\]`))
  })

  it('Pull now pulls this spec only and re-reads the chip; the chip is never handed a plan from the card', async () => {
    await mountCard()
    await waitFor(() => expect(chip().getAttribute('data-state')).toBe('status'))
    fireEvent.click(screen.getByRole('button', { name: /^Plan changes/ }))
    expect(getCommandCenter).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: /^Pull now/ }))
    await screen.findByTestId('fields-pull-result')
    expect(verbsCalled()).toContainEqual({ verb: 'pull', id: REF })
    await waitFor(() => expect(getCommandCenter).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole('button', { name: /^Review plan/ })).toBeNull()
    expect(new Set(verbsCalled().map((r) => r.verb))).toEqual(new Set(['show', 'pull']))
  })

  it('every disabled Boards control carries a reason: no actor, and a plugin without the capability', async () => {
    await mountCard({ actor: null, capabilities: [CAPABILITIES.adoStatus, 'ado-show'] })
    await screen.findByTestId('discussion-block')
    const boards = screen.getByTestId('spec-boards')
    // Plan changes' reason is the verb the plugin lacks, never the missing person: showing a line runs nothing
    const plan = within(boards).getByRole('button', { name: /^Plan changes/ }) as HTMLButtonElement
    expect(plan.disabled).toBe(true)
    expect(plan.getAttribute('title')).toBe(newerPlugin('ado-plan'))
    const pull = within(boards).getByRole('button', { name: /^Pull now/ }) as HTMLButtonElement
    expect(pull.getAttribute('title')).toBe(newerPlugin('ado-pull'))
    cleanup()
    await mountCard({ actor: null })
    const open = within(screen.getByTestId('spec-boards')).getByRole('button', { name: /^Plan changes/ }) as HTMLButtonElement
    expect(open.disabled).toBe(false)
    fireEvent.click(open)
    expect([...screen.getByTestId('plan-lines').querySelectorAll('code')].map((c) => c.textContent)).toEqual(planLines('0008'))
    expect(verbsCalled().some((r) => /plan/i.test(String(r.verb)))).toBe(false)
    cleanup()
    await mountCard({ capabilities: [CAPABILITIES.adoStatus, 'ado-show'] })
    const lacking = within(screen.getByTestId('spec-boards')).getByRole('button', { name: /^Plan changes/ }) as HTMLButtonElement
    expect(lacking.disabled).toBe(true)
    expect(lacking.getAttribute('title')).toBe(newerPlugin('ado-plan'))
    expect(PLAN_CAPABILITY).toBe('ado-plan')
    fireEvent.click(lacking)
    expect(screen.queryByTestId('plan-lines')).toBeNull()   // a line the plugin cannot run is never shown
    const sweep = [...screen.getByTestId('spec-boards').querySelectorAll<HTMLElement>('button[disabled]'), ...screen.getByTestId('discussion-block').querySelectorAll<HTMLElement>('button[disabled], textarea[disabled]')]
    expect(sweep.length).toBeGreaterThan(0)
    for (const el of sweep) expect((el.getAttribute('title') ?? '').trim(), el.textContent ?? '').not.toBe('')
  })

  it('steering mode: the Boards row is gone and nothing in the chip row or the Discussion block writes', async () => {
    await mountCard({ steering: true })
    await screen.findByTestId('discussion-list')
    expect(screen.queryByTestId('spec-boards')).toBeNull()
    expect(screen.queryByTestId('comment-composer')).toBeNull()
    expect(screen.queryByTestId('pull-now')).toBeNull()
    expect(screen.getByTestId('spec-facts').querySelectorAll('[data-write]')).toHaveLength(0)
    expect(screen.getByTestId('discussion-block').querySelectorAll('[data-write], button, input, textarea')).toHaveLength(0)
    expect(screen.queryByRole('button', { name: /^Plan changes/ })).toBeNull()
    expect(new Set(verbsCalled().map((r) => r.verb))).toEqual(new Set(['show']))
  })

  it('a project whose host is not Azure DevOps gets the chip\'s own sentence and no Boards zone, no spawn', async () => {
    connectionStore.set({ ...AZURE, host: 'github', cli: { name: 'gh', found: true, extension: null, signedIn: 'yes' } })
    await mountCard()
    await waitFor(() => expect(chip().textContent).toBe(WORK_ITEMS_NOT_SET_UP))
    expect(screen.queryByTestId('spec-boards')).toBeNull()
    expect(screen.queryByTestId('discussion-block')).toBeNull()
    expect(runAdoVerb).not.toHaveBeenCalled()
  })
})

// ── what PullNow may not do ──────────────────────────────────────────────────────────────────────

describe('PullNow and the Boards row hold no timer and add no channel', () => {
  const root = resolve(__dirname, '..')
  const code = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, '').split(/\r?\n/).map((l) => l.replace(/(^|\s)\/\/.*$/, '')).join('\n')

  it('PullNow never schedules anything: no interval, no timeout, no frame callback — a click is the only trigger', () => {
    const body = code(readFileSync(resolve(root, 'src', 'components', 'ado', 'PullNow.tsx'), 'utf-8'))
    expect(body).not.toMatch(/setInterval|setTimeout|requestAnimationFrame|useEffect/)
    expect(body.match(/data-write/g)).toHaveLength(1)   // one Button, drawn once per kind: the two buttons are one element
    expect(body).not.toMatch(/window\.studio|child_process|['"`]az['"`]/)
  })

  it('the spec card itself reaches the plugin for no Boards verb (its Boards components do, through runAdoVerb), and the preload still exposes one Ado channel', () => {
    const card = code(readFileSync(resolve(root, 'src', 'components', 'SpecCard', 'SpecCard.tsx'), 'utf-8'))
    const studioCalls = [...new Set([...card.matchAll(/studio\.(\w+)/g)].map((m) => m[1]))].sort()
    expect(studioCalls).toEqual(['getSpecCard', 'openDocument'])
    expect(card).not.toMatch(/verb: '/)
    expect(card).not.toMatch(/planSpec/)
    const preload = readFileSync(resolve(root, 'electron', 'preload', 'index.ts'), 'utf-8')
    expect(preload.match(/studio:\w*Ado\w*/g)).toEqual(['studio:runAdoVerb'])
  })
})
