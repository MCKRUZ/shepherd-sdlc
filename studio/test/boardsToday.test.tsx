// @vitest-environment jsdom
// BoardsToday — the Today column shows its Azure Boards sections only where a board can exist. Found by the fork's
// real-window overlap spec (cc/overlap.spec.ts, sprint-home at 1280×800): the fixture project is not on Azure
// DevOps, yet "Catch up with the board" and "Azure Boards" rendered and pushed the lane board below the viewport.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { AdoSyncView } from '../shared/adoTypes'
import type { ConnectionInfo, SourcedBlock } from '../shared/types'
import { BoardsToday, boardsPresent, statusMeasured } from '../src/components/ado/BoardsToday'
import { connectionStore, resetConnectionStore } from '../src/stores/connectionStore'

const runAdoVerb = vi.fn()
beforeEach(() => {
  ;(window as unknown as { studio: unknown }).studio = { runAdoVerb, getCommandCenter: vi.fn() }
  runAdoVerb.mockReset()
})
afterEach(() => { cleanup(); resetConnectionStore() })

const AZURE: ConnectionInfo = {
  host: 'azure-devops', hostSource: 'remote', cli: { name: 'az', found: true, extension: true, signedIn: 'yes' }, lastPulledAt: null, branchProtected: null,
} as unknown as ConnectionInfo
const GITHUB: ConnectionInfo = { ...AZURE, host: 'github', cli: { name: 'gh', found: true, extension: null, signedIn: 'yes' } } as unknown as ConnectionInfo
const NONE: ConnectionInfo = { ...AZURE, host: 'none', cli: { name: 'gh', found: false, extension: null, signedIn: 'unknown' } } as unknown as ConnectionInfo

const STATUS: AdoSyncView = {
  schema: 1, as_of: '2026-10-12T09:02Z', hook_line: '3 rows pending · 1 drifted · as of 2026-10-12T09:02Z',
  counts: { open: 3, pending: 3, drifted: 1, conflicts: 0, debt: 0, linked: 4 }, by_class: { SDLC_OWNED_DRIFT: 1 }, debt: [], last_plan: null, notes: [], ledger: '.sdlc/metrics/ado-sync-log.jsonl',
} as unknown as AdoSyncView
const okBlock: SourcedBlock<AdoSyncView> = { ok: true, data: STATUS, source: 'ado_sync.py status --json', readAt: '2026-10-12T09:03Z', error: null, cacheClass: 'local' } as unknown as SourcedBlock<AdoSyncView>
// The plugin's own never-pulled answer (scripts/tests/golden/ado_status_nodata.json): `ado_sync.py status --json` gives
// it to EVERY project, with or without `.sdlc/ado.yaml` — all nulls, "no data (never pulled)". The block is `ok`.
const NEVER_PULLED = JSON.parse(readFileSync(resolve(__dirname, '..', '..', 'scripts', 'tests', 'golden', 'ado_status_nodata.json'), 'utf8')) as AdoSyncView
const neverPulledBlock: SourcedBlock<AdoSyncView> = { ok: true, data: NEVER_PULLED, source: 'ado_sync.py status --json', readAt: '2026-10-12T09:03Z', error: null, cacheClass: 'local' } as unknown as SourcedBlock<AdoSyncView>
const badBlock: SourcedBlock<AdoSyncView> = { ok: false, data: null, source: 'ado_sync.py status --json', readAt: '2026-10-12T09:03Z', error: 'no .sdlc/ado.yaml', cacheClass: 'local' } as unknown as SourcedBlock<AdoSyncView>

describe('statusMeasured (pure)', () => {
  it('the never-pulled answer is not a measurement: every value null', () => {
    expect(NEVER_PULLED.as_of).toBeNull()
    expect(Object.values(NEVER_PULLED.counts).every((n) => n === null)).toBe(true)
    expect(statusMeasured(NEVER_PULLED)).toBe(false)
    expect(statusMeasured(null)).toBe(false)
    expect(statusMeasured(undefined)).toBe(false)
  })
  it('any one measured value is — a stamp, a count (a measured zero too), a class, a debt list or a plan', () => {
    expect(statusMeasured(STATUS)).toBe(true)
    expect(statusMeasured({ ...NEVER_PULLED, as_of: '2026-10-12T09:02Z' })).toBe(true)
    expect(statusMeasured({ ...NEVER_PULLED, counts: { ...NEVER_PULLED.counts, drifted: 0 } })).toBe(true)
    expect(statusMeasured({ ...NEVER_PULLED, by_class: {} })).toBe(true)
    expect(statusMeasured({ ...NEVER_PULLED, debt: [] })).toBe(true)
    expect(statusMeasured({ ...NEVER_PULLED, last_plan: { plan: 'p.json', ts: null, rows: 0 } })).toBe(true)
  })
})

describe('boardsPresent (pure)', () => {
  it('a status in which the mirror measured something is enough on its own, whatever the host', () => {
    expect(boardsPresent(null, okBlock)).toBe(true)
    expect(boardsPresent(GITHUB, okBlock)).toBe(true)
    expect(boardsPresent(NONE, okBlock)).toBe(true)
  })
  it('a status that merely read — the never-pulled answer every project gets — is not evidence of a board', () => {
    expect(boardsPresent(null, neverPulledBlock)).toBe(false)
    expect(boardsPresent(GITHUB, neverPulledBlock)).toBe(false)
    expect(boardsPresent(NONE, neverPulledBlock)).toBe(false)
    // …but an Azure DevOps project whose board was never pulled still shows its sections (it can pull).
    expect(boardsPresent(AZURE, neverPulledBlock)).toBe(true)
  })
  it('without a read block, the connection decides: Azure DevOps yes, GitHub / none / unread no', () => {
    expect(boardsPresent(AZURE, undefined)).toBe(true)
    expect(boardsPresent(AZURE, badBlock)).toBe(true)
    expect(boardsPresent(GITHUB, undefined)).toBe(false)
    expect(boardsPresent(GITHUB, badBlock)).toBe(false)
    expect(boardsPresent(NONE, undefined)).toBe(false)
    expect(boardsPresent(null, undefined)).toBe(false)
    expect(boardsPresent(null, badBlock)).toBe(false)
  })
})

describe('BoardsToday', () => {
  it('renders nothing for a project that is not on Azure DevOps — no eyebrow, no line, no height, no spawn', () => {
    connectionStore.set(GITHUB)
    const { container } = render(<BoardsToday projectPath="/p" cc={{ ado: undefined, capabilities: [] }} />)
    expect(container.innerHTML).toBe('')
    expect(screen.queryByTestId('ado-catch-up')).toBeNull()
    expect(screen.queryByTestId('ado-today')).toBeNull()
    expect(runAdoVerb).not.toHaveBeenCalled()
  })
  it('renders nothing for a non-Azure project whose status read is the ok, all-null never-pulled answer (the e2e fixture)', () => {
    for (const connection of [NONE, GITHUB, null]) {
      resetConnectionStore()
      if (connection) connectionStore.set(connection)
      const { container, unmount } = render(<BoardsToday projectPath="/p" cc={{ ado: neverPulledBlock, capabilities: ['ado-pull', 'ado-status-json'] }} />)
      expect(container.innerHTML).toBe('')
      unmount()
    }
    expect(runAdoVerb).not.toHaveBeenCalled()
  })
  it('renders the sections for an Azure DevOps project whose board was never pulled', () => {
    connectionStore.set(AZURE)
    render(<BoardsToday projectPath="/p" cc={{ ado: neverPulledBlock, capabilities: [] }} />)
    expect(screen.getByTestId('ado-catch-up')).toBeTruthy()
    expect(screen.getByTestId('ado-today')).toBeTruthy()
    expect(runAdoVerb).not.toHaveBeenCalled()
  })
  it('renders nothing before the connection is known when no status was ever read', () => {
    resetConnectionStore()
    const { container } = render(<BoardsToday projectPath="/p" cc={null} />)
    expect(container.innerHTML).toBe('')
  })
  it('renders both sections for an Azure DevOps project, in order, and spawns nothing on mount', () => {
    connectionStore.set(AZURE)
    render(<BoardsToday projectPath="/p" cc={{ ado: okBlock, capabilities: ['ado-pull', 'ado-pull-discussion', 'ado-status-json'] }} />)
    const catchUp = screen.getByTestId('ado-catch-up')
    const rows = screen.getByTestId('ado-today')
    expect(catchUp.compareDocumentPosition(rows) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(runAdoVerb).not.toHaveBeenCalled()
  })
  it('a measured status shows the sections even before the connection store is filled', () => {
    resetConnectionStore()
    render(<BoardsToday projectPath="/p" cc={{ ado: okBlock, capabilities: [] }} />)
    expect(screen.getByTestId('ado-today')).toBeTruthy()
  })
  it('steering reaches the children: the catch-up section hides its buttons and the rows stay read-only', () => {
    connectionStore.set(AZURE)
    render(<BoardsToday projectPath="/p" cc={{ ado: okBlock, capabilities: [] }} steering />)
    expect(screen.queryByTestId('ado-catch-up')).toBeNull()
    expect(screen.getByTestId('ado-today').querySelectorAll('[data-write]')).toHaveLength(0)
  })
})
