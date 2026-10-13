import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { pluralWord } from '../../shared/format'
import type { ButtonProps } from '../ui'
import { Button, Notice, SkeletonBlock } from '../ui'

/** Pieces the four activity panels (spec 0026) share, so each reports a failure and guards against
 * a stale answer the same way. */

// The two legacy class strings stay exported for any importer still spelling a `<button>` by hand;
// new code in these panels renders `PanelButton` / `PanelSecondaryButton` (the §3 kit) instead, so
// the primary one keeps emitting the literal `bg-brand-600` the e2e specs locate by class.
export const PANEL_BUTTON =
  'rounded-lg bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-700 disabled:opacity-60'
export const PANEL_SECONDARY_BUTTON =
  'rounded-lg border border-line-1 px-3 py-1.5 text-xs font-medium text-ink-2 hover:border-line-2 disabled:opacity-60'

type PanelButtonProps = Omit<ButtonProps, 'variant' | 'size'>

/** The one action a panel runs (Export, Catalogue, Keep…). Small because it sits inside a list row. */
export function PanelButton(props: PanelButtonProps) {
  return <Button variant="primary" size="sm" {...props} />
}

/** Everything beside the main action (Cancel, Move up, Show preview, Strict check). */
export function PanelSecondaryButton(props: PanelButtonProps) {
  return <Button variant="secondary" size="sm" {...props} />
}

/** The word alone for a count — the shared rule (`shared/format.ts`, C6), kept under the name the
 * four panels already import. */
export function plural(count: number, one: string, many: string) {
  return pluralWord(count, one, many)
}

export function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback
}

/** The one line a failed call shows: no count, no partial result beside it. `role="alert"` and the
 * testid are what the panel tests read; the Notice only adds the icon and the error tone. */
export function PanelError({ message }: { message: string }) {
  return <Notice tone="error" role="alert" data-testid="panel-error" className="mt-2">{message}</Notice>
}

/** A kept loading sentence with skeleton bones beside it (§6.6): the text is what a test and a
 * reader find; the bones only say "something this shape is coming". The fixed line count never
 * implies how much will arrive. */
export function PanelLoading({ children, lines = 2 }: { children: string; lines?: number }) {
  return (
    <div aria-busy="true" className="space-y-1.5">
      <p role="status" className="text-xs text-ink-3">{children}</p>
      <SkeletonBlock lines={lines} />
    </div>
  )
}

/** State that belongs to one place (a project, or a project and stage). When `scope` changes the
 * state goes back to `initial`, and `isCurrent` turns a reply for the place the person already left
 * into a no-op — so an old stage's answer can never land on the one they are looking at.
 * `initial` must be a stable value (a module constant). */
export function useScopedState<T>(scope: string, initial: T): [T, Dispatch<SetStateAction<T>>, (forScope: string) => boolean] {
  const [value, setValue] = useState<T>(initial)
  const live = useRef<string | null>(null)
  useEffect(() => {
    live.current = scope
    setValue(initial)
    return () => { live.current = null }
  }, [scope, initial])
  return [value, setValue, (forScope) => live.current === forScope]
}

export type Loaded<T> = { kind: 'loading' } | { kind: 'failed'; message: string } | { kind: 'ready'; value: T }

/** Loads once when the panel appears and again when `scope` changes, for the read-only panels. A
 * reply for a scope the person already left is dropped. */
export function useLoaded<T extends { ok: boolean; error?: string }>(
  scope: string, load: () => Promise<T>, fallback: string,
): Loaded<T> {
  const [state, setState] = useState<Loaded<T>>({ kind: 'loading' })
  useEffect(() => {
    let cancelled = false
    setState({ kind: 'loading' })
    Promise.resolve().then(load).then(
      (value) => { if (!cancelled) setState(value.ok ? { kind: 'ready', value } : { kind: 'failed', message: value.error || fallback }) },
      (err) => { if (!cancelled) setState({ kind: 'failed', message: messageOf(err, fallback) }) },
    )
    return () => { cancelled = true }
    // `load` is rebuilt every render; the scope is what decides when to read again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope])
  return state
}
