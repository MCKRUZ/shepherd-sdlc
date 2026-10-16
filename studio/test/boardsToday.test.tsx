// @vitest-environment jsdom
// BoardsToday — the Today column shows its Azure Boards sections only where a board can exist. Found by the fork's
// real-window overlap spec (cc/overlap.spec.ts, sprint-home at 1280×800): the fixture project is not on Azure
// DevOps, yet "Catch up with the board" and "Azure Boards" rendered and pushed the lane board below the viewport.
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { AdoSyncView } from '../shared/adoTypes'
import type { ConnectionInfo, SourcedBlock } from '../shared/types'
import { BoardsToday, boardsPresent } from '../src/components/ado/BoardsToday'
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
const badBlock: SourcedBlock<AdoSyncView> = { ok: false, data: null, source: 'ado_sync.py status --json', readAt: '2026-10-12T09:03Z', error: 'no .sdlc/ado.yaml', cacheClass: 'local' } as unknown as SourcedBlock<AdoSyncView>

describe('boardsPresent (pure)', () => {
  it('a read status block is enough on its own — it only ever comes from a project with .sdlc/ado.yaml', () => {
    expect(boardsPresent(null, okBlock)).toBe(true)
    expect(boardsPresent(GITHUB, okBlock)).toBe(true)
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
  it('a read status shows the sections even before the connection store is filled', () => {
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
