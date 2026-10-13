// The steering-mode title lockup (togo-command-center-visual.md §1, §4): one of the command
// center's two Depth places. The mark at 48 px (`DEPTH_MIN_PX`, brand §4 "48 px+ · Depth
// allowed") in the hero treatment, the wordmark at 22 px, and the eyebrow "Steering" — the one
// word that tells a committee which screen they are looking at. Read-only chrome: it is never a
// heading (the screen's h1/h2 stays the one assistive tech lands on) and carries no control.
import type { HTMLAttributes } from 'react'
import { cn } from '../../../ui/cn'
import { EYEBROW_CLASS } from '../../../ui/Eyebrow'
import { DEPTH_MIN_PX, ShepherdMark } from '../ShepherdMark'
import { ShepherdWordmark } from '../ShepherdWordmark'

export const STEERING_LOCKUP_LABEL = 'Steering'
/** `h-12` = 48 px — exactly the Depth floor; the lockup never renders the mark smaller. */
export const STEERING_MARK_PX = DEPTH_MIN_PX

export interface SteeringLockupProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {}

export function SteeringLockup({ className, ...rest }: SteeringLockupProps) {
  return (
    <div className={cn('flex items-center gap-4', className)} data-steering-lockup="" {...rest}>
      <ShepherdMark variant="depth" className="h-12 w-12 shrink-0" />
      <div className="flex flex-col">
        <ShepherdWordmark className="text-xl text-ink-1" />
        <span className={EYEBROW_CLASS}>{STEERING_LOCKUP_LABEL}</span>
      </div>
    </div>
  )
}
