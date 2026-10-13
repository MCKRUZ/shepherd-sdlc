// Shepherd's own record of a chat TURN's life (togo-command-center.md §3.4 "Claude is working the
// <stage>"): the ChatPanel owns `busy` and publishes here when a turn starts, ends or fails, so
// the lifecycle home's "Claude is working …" line can say so too — a present-tense label after
// the turn is over would assert work that is not happening. UI state only, keyed by project and
// stage like `onChatActivity`; it never reaches `window.studio`, never counts, never persists.
import { useSyncExternalStore } from 'react'

export type ChatTurnPhase = 'running' | 'ended' | 'failed'

export interface ChatTurnSnapshot {
  projectPath: string
  stageId: string
  phase: ChatTurnPhase
  /** When the phase was published (Shepherd's clock, labelled as its own record where shown). */
  at: number
}

type Listener = () => void

/** One entry per project + stage (turns for different stages can overlap, as `onChatActivity`
 * says), the map replaced on every publish so a subscriber sees a new reference. */
let snapshot: ReadonlyMap<string, ChatTurnSnapshot> = new Map()
const listeners = new Set<Listener>()

const keyOf = (projectPath: string, stageId: string) => `${projectPath}\u0000${stageId}`

function getSnapshot(): ReadonlyMap<string, ChatTurnSnapshot> {
  return snapshot
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function publish(projectPath: string, stageId: string, phase: ChatTurnPhase, at: number = Date.now()): void {
  const next = new Map(snapshot)
  next.set(keyOf(projectPath, stageId), { projectPath, stageId, phase, at })
  snapshot = next
  for (const listener of Array.from(listeners)) listener()
}

export const chatTurnStore = {
  getSnapshot,
  subscribe,
  publish,
  /** The phase last published for one project + stage, or null. */
  current(projectPath: string, stageId: string): ChatTurnSnapshot | null {
    return snapshot.get(keyOf(projectPath, stageId)) ?? null
  },
}

/** The latest turn phase for one project + stage, or null when none was published for it. */
export function useChatTurn(projectPath: string, stageId: string): ChatTurnSnapshot | null {
  const map = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
  return map.get(keyOf(projectPath, stageId)) ?? null
}

/** For tests: forget every turn. */
export function resetChatTurnStore(): void {
  snapshot = new Map()
  for (const listener of Array.from(listeners)) listener()
}
