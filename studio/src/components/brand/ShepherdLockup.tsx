// The small lockup — mark beside wordmark — that keeps identity on the pre-project screens that
// are not the Welcome hero (New project, Set up, Tooling). It is window chrome: `text-ink-3` so it
// sits behind the content in weight, and never a heading, so the screen's own h1 stays the one
// heading assistive tech lands on. The Welcome hero composes its own lockup (mark + the h1 the
// split-title choreography targets), so this component is deliberately the 24 px size only.
import type { HTMLAttributes } from 'react'
import { cn } from '../../ui'
import { TogoMark } from './TogoMark'
import { TogoWordmark } from './TogoWordmark'

export interface TogoLockupProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {}

export function TogoLockup({ className, ...rest }: TogoLockupProps) {
  return (
    <div className={cn('flex items-center gap-2 text-ink-3', className)} {...rest}>
      {/* 24 px is the brand's in-app minimum; accent-600 keeps its value in both themes. */}
      <TogoMark className="h-6 w-6 shrink-0 text-accent-600" />
      <TogoWordmark className="text-xs" />
    </div>
  )
}
