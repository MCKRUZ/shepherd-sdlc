import { useEffect, useRef, useState } from 'react'
import type { SyncState } from '../../shared/types'
import { Chip, HoverCard, StatusDot, cn, type ChipTone, type DotStatus } from '../ui'
import { useStudioGSAP } from '../motion/useStudioGSAP'
import { motion } from '../motion/motion'
import { MOTION_DURATIONS, MOTION_EASES } from '../motion/contract'
import { contextFrom, syncChip } from '../motion/choreo'

function relativeTime(iso: string): string {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  return `${hours}h ago`
}

/** The words, tone and dot for each state, in one place so the chip and its hover card agree.
 * The texts are the ones sidebar.test pins ("4 sections need your input", "Sync error"). */
function describe(s: SyncState): { label: string; tone: ChipTone; dot: DotStatus; pulse: boolean; detail: string } {
  switch (s.kind) {
    case 'pulling':
      return { label: 'Pulling…', tone: 'neutral', dot: 'running', pulse: true, detail: 'Reading the repository for changes made elsewhere.' }
    case 'saving':
      return { label: 'Saving…', tone: 'neutral', dot: 'running', pulse: true, detail: 'Writing your changes to the repository.' }
    case 'clashes':
      return {
        label: `${s.count} section${s.count === 1 ? '' : 's'} need your input`,
        tone: 'warn', dot: 'warn', pulse: false,
        detail: 'The same section changed here and in the repository; the clash screen opens by itself.',
      }
    case 'waitingForApproval':
      return { label: `Waiting for ${s.approver}`, tone: 'warn', dot: 'warn', pulse: false, detail: `Approver: ${s.approver}. The stage's documents merge once they approve.` }
    case 'waitingForChecks':
      return { label: 'Waiting for checks', tone: 'neutral', dot: 'running', pulse: false, detail: 'The code host is still running its checks on the saved change.' }
    case 'localOnly':
      // Not a failure: every new project starts here. Calm tone, and the way out in the hover card.
      return {
        label: 'Saved on this computer only', tone: 'neutral', dot: 'ok', pulse: false,
        detail: "Not shared with a team yet. This project is not connected to a shared repository, so nothing syncs. To work with a team, connect one (git remote add origin <the repository's address>) and Shepherd will start syncing.",
      }
    case 'error':
      return { label: 'Sync error', tone: 'error', dot: 'error', pulse: false, detail: s.message }
    case 'idle':
    default:
      return {
        // A healthy state is quiet (G4-8): grey text with a green dot. Green fills are for
        // signed-off facts, and "synced" is not one.
        label: s.lastPulledAt ? `Synced ${relativeTime(s.lastPulledAt)}` : 'Not synced yet',
        tone: 'neutral', dot: 'ok', pulse: false,
        detail: s.lastPulledAt ? `Last pulled ${new Date(s.lastPulledAt).toLocaleString()}.` : 'Nothing has been pulled from the repository in this session.',
      }
  }
}

/** The sync indicator spec 0009 requires "on every screen". It lives in the sidebar's footer,
 * which is on every project screen. Re-renders on a tick so "2m ago" keeps advancing without
 * needing a new syncState push just to update the clock.
 *
 * It is a status, not a control: nothing here can be clicked, so it does not look as if it could
 * be. (The clash screen opens by itself when there is something to resolve.) The hover card
 * (§6.5) carries the detail the one-line label cannot — when it was last pulled, who it waits
 * on — and, like every hover card, holds nothing that writes. */
export function SyncChip({ syncState }: { syncState: SyncState }) {
  const [, forceTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => forceTick((n) => n + 1), 30_000)
    return () => clearInterval(id)
  }, [])

  const { label, tone, dot, pulse, detail } = describe(syncState)
  const rootRef = useRef<HTMLSpanElement>(null)
  const dotRef = useRef<HTMLSpanElement>(null)
  const labelRef = useRef<HTMLSpanElement>(null)

  // Choreography #23: a crossfade when the KIND changes (not on every 30 s tick), so the chip
  // does not blink while the clock advances.
  useStudioGSAP(() => {
    const root = rootRef.current
    if (!root) return
    const ctx = contextFrom(root, { enabled: motion.enabled(), reduced: motion.reduced() }, { durations: MOTION_DURATIONS, eases: MOTION_EASES })
    syncChip.play(ctx, { dot: dotRef.current, label: labelRef.current })
  }, { scope: rootRef, dependencies: [syncState.kind] })

  return (
    <HoverCard
      className="flex w-full"
      placement="top"
      trigger={
        <Chip
          ref={rootRef}
          tone={tone}
          size="sm"
          role="status"
          title={syncState.kind === 'error' ? syncState.message : undefined}
          // Grey text only on the quiet neutral state; warn and error keep the tone's own ink.
          className={cn('w-full justify-start rounded-[8px] px-2.5 py-1.5 text-xs', tone === 'neutral' && 'text-ink-3')}
        >
          <StatusDot ref={dotRef} status={dot} pulse={pulse} className="h-1.5 w-1.5" />
          <span ref={labelRef}>{label}</span>
        </Chip>
      }
      content={
        <span className="block max-w-[16rem] text-left">
          <span className="block font-medium">{label}</span>
          <span className="mt-0.5 block text-ink-3">{detail}</span>
        </span>
      }
    />
  )
}
