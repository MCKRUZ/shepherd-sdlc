// The small lockup — mark beside wordmark — that keeps identity on the pre-project screens that
// are not the Welcome hero (New project, Set up, Tooling). It is window chrome: `text-ink-3` so it
// sits behind the content in weight, and never a heading, so the screen's own h1 stays the one
// heading assistive tech lands on. The Welcome hero composes its own lockup (mark + the h1 the
// split-title choreography targets), so this component is deliberately the 24 px size only.
import type { HTMLAttributes } from 'react'
import { cn } from '../../ui'
import { ShepherdMark } from './ShepherdMark'
import { ShepherdWordmark } from './ShepherdWordmark'

export interface ShepherdLockupProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {}

export function ShepherdLockup({ className, ...rest }: ShepherdLockupProps) {
  return (
    <div className={cn('flex items-center gap-2 text-ink-3', className)} {...rest}>
      {/* 24 px is below the S's 48 px floor, so the frame alone (brand §4); its two tones keep
          their values in both themes, so no text colour is needed. */}
      <ShepherdMark frameOnly className="h-6 w-6 shrink-0" />
      <ShepherdWordmark className="text-xs" />
    </div>
  )
}
