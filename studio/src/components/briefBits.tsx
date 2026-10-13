import type { ReactNode } from 'react'
import type { InputProps } from '../ui'
import { Input } from '../ui'

/** Small pieces every part of the workshop-brief form (spec 0032) is built from. */

// Kept for any importer still spelling an `<input>` by hand; the form itself renders `BriefInput`
// (the kit's Input). The focus style is the universal `:focus-visible` ring — this string no
// longer removes the outline (C5: a focus ring is never clipped or suppressed).
export const TEXT_INPUT =
  'w-full rounded-lg border border-line-1 px-2 py-1 text-xs text-ink-1 focus:border-brand-600'

/** The one-line text box the brief form uses everywhere (claims, decisions, logistics, attendees). */
export function BriefInput(props: Omit<InputProps, 'size'>) {
  return <Input size="sm" {...props} />
}

/** A titled block with its live counter, e.g. "2 of 5". */
export function Section({
  title, counter, counterId, children,
}: { title: string; counter?: string; counterId?: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <h4 className="text-xs font-semibold text-ink-1">{title}</h4>
        {counter !== undefined && <span data-testid={counterId} className="text-xs text-ink-2">{counter}</span>}
      </div>
      {children}
    </section>
  )
}

export function Reason({ children }: { children: ReactNode }) {
  return <p className="text-xs text-ink-3">{children}</p>
}

export function toggled(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id]
}

export function withoutIndex<T>(list: T[], index: number): T[] {
  return list.filter((_, i) => i !== index)
}
