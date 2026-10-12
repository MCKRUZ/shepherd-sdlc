import { useCallback, useEffect, useRef, useState } from 'react'
import type { DocumentVersion, RestorePreview } from '../../shared/types'
import { Button, Card, DataTable, Dialog, Eyebrow, Notice, SkeletonRows, cn, toast } from '../ui'
import type { DataTableColumn } from '../ui'
import { useEnter } from '../motion/useEnter'

// The diff is code: the code type token (12/16, weight 450) on the code surface, 10 px corners.
const DIFF_CLASS = 'max-h-64 overflow-auto rounded-[10px] bg-surface-code p-3 font-mono text-code leading-4 text-white'

/** Versions of one document: who saved each and why, what changed between two, and restoring
 * one.
 *
 * Restoring is preview-then-confirm and this component never shortcuts it. The person is shown
 * the exact diff, and confirming sends back the hash of that diff — so a restore can only
 * apply the change that was actually reviewed. Restoring also ADDS a version rather than
 * removing any, which is why the button says "Restore as a new version": it is not an undo
 * that erases history, and the label should not imply it is. */
export function HistoryPanel({
  projectPath,
  relPath,
  actor,
  onClose,
  onRestored,
}: {
  projectPath: string
  relPath: string
  actor: string
  onClose: () => void
  onRestored: () => void
}) {
  const [versions, setVersions] = useState<DocumentVersion[] | null>(null)
  const [diff, setDiff] = useState<string | null>(null)
  const [preview, setPreview] = useState<(RestorePreview & { ref: string }) | null>(null)
  const [ackSignOff, setAckSignOff] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  useEnter(rootRef, 'rise')

  const fileName = relPath.split('/').pop()

  const load = useCallback(async () => {
    setVersions(await window.studio.listVersions(projectPath, relPath))
  }, [projectPath, relPath])

  useEffect(() => { load() }, [load])

  const showDiff = async (ref: string) => {
    setError(null)
    const result = await window.studio.diffVersions(projectPath, relPath, ref, 'latest')
    if (!result.ok) setError(result.error ?? 'Could not compare those versions.')
    else setDiff(result.diff ?? '')
  }

  const startRestore = async (ref: string) => {
    setError(null)
    setAckSignOff(false)
    const result = await window.studio.previewRestore(projectPath, relPath, ref)
    if (!result.ok) setError(result.error ?? 'Could not prepare that restore.')
    else setPreview({ ...result, ref })
  }

  // Stable: the Dialog re-runs its focus effect whenever `onClose` changes identity, and an
  // inline closure would re-run it on every keystroke in the acknowledgement.
  const cancelRestore = useCallback(() => setPreview(null), [])

  const confirm = async () => {
    if (!preview) return
    setBusy(true)
    const result = await window.studio.confirmRestore(
      projectPath, relPath, preview.ref, actor, preview.diffHash, ackSignOff,
    )
    setBusy(false)
    if (!result.ok) {
      setError(result.error ?? 'The restore was refused.')
      return
    }
    setPreview(null)
    toast({ tone: 'ok', title: 'Restored as a new version', detail: `${preview.ref} · ${fileName}` })
    await load()
    onRestored()
  }

  const columns: DataTableColumn<DocumentVersion>[] = [
    {
      id: 'version',
      header: 'Version',
      mono: true,
      width: '5rem',
      cell: (v) => (
        <>
          <span className="font-medium text-ink-1">v{v.n}</span>
          {v.restoredFrom !== undefined && <p className="mt-0.5 text-2xs text-ink-3">from v{v.restoredFrom}</p>}
        </>
      ),
    },
    { id: 'who', header: 'Who', cell: (v) => v.actor || 'unknown' },
    { id: 'when', header: 'When', mono: true, cell: (v) => (v.when ? v.when.slice(0, 10) : <span className="text-ink-4">—</span>) },
    {
      id: 'why',
      header: 'Why',
      cell: (v) => (
        <>
          {v.reason || <span className="text-ink-3">No reason recorded.</span>}
          {!v.present && (
            // A real state, not an error: the content store is local, so a version saved on
            // someone else's machine has metadata here but no bytes.
            <p className="mt-0.5 text-status-warn-ink">Content not available on this machine.</p>
          )}
        </>
      ),
    },
    {
      id: 'actions',
      header: <span className="sr-only">Actions</span>,
      align: 'end',
      cell: (v) => (
        <span className="inline-flex gap-1.5">
          <Button size="sm" disabled={!v.present} onClick={() => showDiff(`v${v.n}`)}>
            Compare
          </Button>
          <Button size="sm" disabled={!v.present} onClick={() => startRestore(`v${v.n}`)}>
            Restore
          </Button>
        </span>
      ),
    },
  ]

  const cannotConfirm = !actor.trim()
    ? 'Set your name in settings first — a restore is recorded against a person.'
    : preview?.needsSignOffAck && !ackSignOff
      ? 'Acknowledge the signed-off content first.'
      : undefined

  return (
    <div ref={rootRef} className="space-y-4">
      <div className="flex items-center justify-between">
        {/* Detail-screen rank (G4-1): the element stays an h3, the size is the detail title's. */}
        <h3 data-page-heading tabIndex={-1} className="text-lg text-ink-1">History — {fileName}</h3>
        <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
      </div>

      {error && <Notice tone="error">{error}</Notice>}

      {versions === null ? (
        <div aria-busy="true" className="space-y-2">
          <p role="status" className="text-sm text-ink-3">Loading…</p>
          <SkeletonRows rows={3} />
        </div>
      ) : (
        <DataTable
          label="Versions"
          columns={columns}
          rows={[...versions].reverse()}
          rowKey={(v) => `v${v.n}`}
          empty="No versions recorded yet — a version is written each time this document is saved."
        />
      )}

      {diff !== null && (
        <Card
          header={(
            <div className="flex items-center justify-between">
              <Eyebrow as="h3">What changed</Eyebrow>
              <Button variant="ghost" size="sm" onClick={() => setDiff(null)}>Hide</Button>
            </div>
          )}
        >
          <pre className={DIFF_CLASS}>{diff}</pre>
        </Card>
      )}

      <Dialog
        open={preview !== null}
        onClose={cancelRestore}
        title={`Restore ${preview?.ref ?? ''}?`}
        description="This adds a new version with the older content. Nothing is removed — the current version stays in the history."
        size="lg"
        footer={(
          <>
            <Button onClick={cancelRestore}>Cancel</Button>
            <Button variant="primary" onClick={confirm} loading={busy} disabled={cannotConfirm !== undefined} disabledReason={cannotConfirm}>
              Restore as a new version
            </Button>
          </>
        )}
      >
        {preview && (
          <>
            <pre className={cn(DIFF_CLASS, 'max-h-48')}>{preview.diff}</pre>
            {preview.needsSignOffAck && (
              <label className="mt-3 flex items-start gap-2 text-xs text-ink-1">
                <input type="checkbox" checked={ackSignOff} onChange={(e) => setAckSignOff(e.target.checked)} className="mt-0.5" />
                <span>This document is signed off. I understand I am changing signed-off content, and that this override is recorded.</span>
              </label>
            )}
            {!actor.trim() && (
              <p className="mt-3 text-xs text-status-warn-ink">Set your name in settings first — a restore is recorded against a person.</p>
            )}
          </>
        )}
      </Dialog>
    </div>
  )
}
