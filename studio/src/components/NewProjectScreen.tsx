import { useRef, useState } from 'react'
import { Button, Card, Field, Input, Notice } from '../ui'
import { useEnter } from '../motion/useEnter'
import { EntryShell } from './entryScreenBits'

const REMEMBERED_PARENT = 'studio.newProjectParent'

function readRememberedParent(): string | null {
  try { return localStorage.getItem(REMEMBERED_PARENT) } catch { return null }
}

function rememberParent(parent: string): void {
  try { localStorage.setItem(REMEMBERED_PARENT, parent) } catch { /* a convenience, never a failure */ }
}

/** Where the new folder will land, written the way this person's operating system writes paths. */
function joinForDisplay(parent: string, name: string): string {
  const separator = parent.includes('\\') ? '\\' : '/'
  return parent.endsWith(separator) ? `${parent}${name}` : `${parent}${separator}${name}`
}

/** Start a project from nothing: a name, and where it should live. Shepherd makes the folder and
 * starts version tracking in it, then the person continues into the same setup wizard an
 * existing folder goes through — they never leave the app to make a folder first. */
export function NewProjectScreen({
  onCancel,
  onCreated,
}: {
  onCancel: () => void
  onCreated: (projectPath: string) => void
}) {
  const [name, setName] = useState('')
  const [parent, setParent] = useState<string | null>(readRememberedParent)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cardRef = useRef<HTMLDivElement | null>(null)
  // The card settles like a dialog panel (§4 #15) — this screen is the one place a dialog's job
  // is done by a whole screen.
  useEnter(cardRef, 'rise')

  const trimmed = name.trim()
  const ready = trimmed !== '' && parent !== null && !busy

  const chooseLocation = async () => {
    const chosen = await window.studio.pickFolder()
    if (!chosen) return
    setParent(chosen)
    rememberParent(chosen)
    setError(null)
  }

  const create = async () => {
    if (!ready || parent === null) return
    setBusy(true)
    setError(null)
    try {
      const result = await window.studio.createProject(parent, trimmed)
      if (result.ok && result.path) {
        onCreated(result.path)
        return
      }
      setError(result.error ?? 'The project could not be created.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The project could not be created.')
    }
    setBusy(false)
  }

  return (
    <EntryShell>
      <div className="mx-auto w-full max-w-md space-y-5">
        {/* Left-aligned like the other pre-project headings; `text-lg` carries 18/24/600/−0.01em
            from the type scale, so no weight class here. */}
        <div>
          <h1 className="text-lg text-ink-1">New project</h1>
          <p className="mt-1 text-sm text-ink-3">
            Shepherd will make the folder and set it up for you. You'll choose the lifecycle profile on the next step.
          </p>
        </div>

        <Card ref={cardRef} className="space-y-4 rounded-4 p-6 shadow-2">
          {/* The error is one Notice below, not also Field's own `error` slot: two `role="alert"`s
              for one failure would be announced twice. */}
          <Field label="Project name" id="new-project-name">
            <Input
              type="text"
              autoFocus
              value={name}
              disabled={busy}
              invalid={error !== null}
              onChange={(e) => { setName(e.target.value); setError(null) }}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void create() } }}
              placeholder="e.g. Claims Portal"
            />
          </Field>

          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-ink-2">Location</span>
            <div className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate rounded-lg bg-surface-2 px-3 py-1.5 font-mono text-sm text-ink-2" title={parent ?? undefined}>
                {parent ?? 'No location chosen yet'}
              </span>
              <Button variant="secondary" disabled={busy} onClick={chooseLocation} className="shrink-0">
                Choose location…
              </Button>
            </div>
          </div>

          {parent !== null && trimmed !== '' && (
            <p className="text-xs text-ink-3">
              Will create: <span data-testid="new-project-target" className="break-all font-mono font-medium text-ink-1">{joinForDisplay(parent, trimmed)}</span>
            </p>
          )}
        </Card>

        {error && (
          <Notice tone="error" role="alert">
            {error}
          </Notice>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="secondary" disabled={busy} onClick={onCancel} className="px-4 text-sm">
            Cancel
          </Button>
          <Button variant="primary" disabled={!ready} loading={busy} loadingLabel="Creating…" onClick={create} className="px-4 text-sm">
            Create project
          </Button>
        </div>
      </div>
    </EntryShell>
  )
}
