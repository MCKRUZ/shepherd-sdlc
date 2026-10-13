import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, History, Pencil } from 'lucide-react'
import type {
  DocumentChange, DocumentFocus, DocumentSection, OpenDocumentResult,
} from '../../shared/types'
import { matchesSection } from '../../shared/sections'
import { BackLink, Button, Notice, PageHeader, SkeletonBlock, toast } from '../ui'
import { useEnter } from '../motion/useEnter'
import { motion } from '../motion/motion'
import { contextFrom, findingFocus } from '../motion/choreo'
import { SHORTCUT_MAP } from '../shortcuts/shortcutMap'
import { useShortcuts } from '../shortcuts/useShortcuts'
import { DocumentOutline } from './DocumentOutline'
import { SectionCard } from './DocumentSections'
import { saveOpenFieldEditor } from './FieldEditor'
import { TemplateGapsNotice } from './TemplateGapsNotice'
import { useStageReadiness } from './StageReadinessContext'
import { STICKY_HEADER_CLASS, useStuck } from './useStuck'

/** Only this screen's rows of the §6.2 map. Frame's listener owns the shell scopes; handing
 * this hook the full map would make two listeners answer `/` or ⌘K. */
const DOCUMENT_BINDINGS = SHORTCUT_MAP.filter((b) => b.scope === 'documentView')

/** Reading and editing one document.
 *
 * The rule that shapes this whole component: NOTHING that changes content is rendered outside
 * edit mode. Not disabled — absent. A disabled button still tells the person "this is a thing
 * you could do here", and spec 0010's acceptance check is explicit that those controls do not
 * exist outside edit mode, "including the add button on a review panel". */
export function DocumentView({
  projectPath,
  relPath,
  actor,
  focus,
  onBack,
  onShowHistory,
  onOpenDocument,
}: {
  projectPath: string
  relPath: string
  actor: string
  /** Set when the reader arrived from a readiness item rather than the document list: the
   * section and field that item was about, so they land on it instead of hunting for it. */
  focus?: DocumentFocus
  onBack: () => void
  onShowHistory: () => void
  /** Alt+↑ / Alt+↓ step through the stage's openable documents in declared order. Optional
   * because only the host can change which document is open; without it the keys do nothing. */
  onOpenDocument?: (relPath: string) => void
}) {
  // StageHome (and the sidebar's doc-count line, and the Workflow tab) all read the ONE shared
  // fetch Frame.tsx's StageReadinessProvider owns (spec 0019) — keyed on [projectPath, stageId],
  // never on anything that happens while a document is open. DocumentView is rendered as that
  // same Provider's descendant (Frame's `children`, exactly like StageHome — see App.tsx), so it
  // can read this context directly and refresh it itself. Without this, saving a field here
  // leaves the shared readiness holding whatever it read before this document was ever opened:
  // the pre-existing gap `StageHome.tsx`'s own pre-0019 `useCurrentStageDocs` had too, now
  // closed here since it lives in the shared context this spec introduced.
  const { refresh: refreshReadiness, readiness } = useStageReadiness()

  /** The section the reader was sent to (a readiness item) or picked (the outline rail),
   * resolved once the document is open. Held as the section KEY rather than the plugin's
   * reported name, because that is what the rendered cards are addressed by. `fromFinding`
   * decides whether the card says "You were sent here…" — an outline click sent nobody. */
  const [focused, setFocused] = useState<{ key: string; fromFinding: boolean } | null>(null)
  const focusedKey = focused?.key ?? null
  /** Bumped on every outline click so picking the SAME section again still scrolls and pulses. */
  const [pick, setPick] = useState(0)
  const [doc, setDoc] = useState<OpenDocumentResult | null>(null)
  const [changes, setChanges] = useState<DocumentChange[]>([])
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [nextId, setNextId] = useState<string | null>(null)
  // Working out the next number means asking the plugin, in another process. Until that
  // answers, the control must not claim to know — see the comment on the button itself.
  const [numbering, setNumbering] = useState(false)
  const [busy, setBusy] = useState(false)

  // The screen root is rendered from the first paint (loading state included) so the enter
  // choreography has an element to move and `main.firstElementChild` is this screen throughout.
  const rootRef = useRef<HTMLDivElement>(null)
  useEnter(rootRef, 'rise')
  // The title block is this screen's sticky header (G4-2): flush at rest, a hairline once the
  // sections have scrolled under it.
  const headerRef = useRef<HTMLDivElement>(null)
  useStuck(headerRef)

  const fileName = relPath.split('/').pop()

  const load = useCallback(async () => {
    const opened = await window.studio.openDocument(projectPath, relPath)
    setDoc(opened)
    if (!opened.ok) setError(opened.error ?? 'Could not open this document.')
  }, [projectPath, relPath])

  useEffect(() => { load() }, [load])

  // Resolve the readiness item's section to a rendered card, once there is a document to look
  // in. Matched with the SAME rule the main process used to attach the finding to a field
  // (shared/sections.ts) — two different rules here would send the reader to the wrong place
  // and look like a broken link rather than a disagreement.
  useEffect(() => {
    if (!focus || !doc?.ok) { setFocused(null); return }
    const hit = doc.sections.find((s) => matchesSection(s.key, s.heading, focus.section))
    setFocused(hit ? { key: hit.key, fromFinding: true } : null)
  }, [focus, doc])

  // Scrolled after the card exists, not when the focus arrives — the element is not in the
  // document until the section it belongs to has rendered. Then the ring pulses (§4 #21) so the
  // eye lands where the scroll did; the classes themselves never change. The outline rail (S5)
  // reaches the same effect through `focused` + `pick`, so a finding and a click share one ring.
  useEffect(() => {
    const root = rootRef.current
    if (!focusedKey || !root) return
    const escaped = typeof CSS !== 'undefined' && typeof CSS.escape === 'function' ? CSS.escape(focusedKey) : focusedKey.replace(/"/g, '\\"')
    const card = root.querySelector(`[data-section-key="${escaped}"]`)
    if (!card) return
    // jsdom has no scrollIntoView; a component test that opens from a finding must still render.
    if (typeof card.scrollIntoView === 'function') card.scrollIntoView({ block: 'center' })
    const timeline = findingFocus.play(
      contextFrom(root, { enabled: motion.enabled(), reduced: motion.reduced() }, motion),
      { card },
    )
    return () => { timeline.kill() }
  }, [focusedKey, pick])

  const pickSection = useCallback((key: string) => {
    setFocused({ key, fromFinding: false })
    setPick((n) => n + 1)
  }, [])

  // Listing what changed never marks it seen — that is a separate, explicit act, so merely
  // opening a document can't quietly erase the "here's what moved" signal.
  useEffect(() => {
    window.studio.getDocumentChanges(projectPath, relPath).then(setChanges)
  }, [projectPath, relPath])

  // Alt+↑/↓ walk the stage's documents as the Workflow tab lists them — only the ones that can
  // be opened as one document (a folder step or a not-yet-created file has nothing to show).
  const stepDocument = useCallback((delta: 1 | -1) => {
    if (!onOpenDocument) return
    const openable = (readiness?.documents ?? []).filter((d) => d.exists && !d.folder)
    const at = openable.findIndex((d) => d.path === relPath)
    if (at < 0) return
    const next = openable[at + delta]
    if (next) onOpenDocument(next.path)
  }, [onOpenDocument, readiness, relPath])

  useShortcuts({
    handlers: { stepDocument, saveField: () => { saveOpenFieldEditor() } },
    scopes: ['documentView'],
    bindings: DOCUMENT_BINDINGS,
  })

  const enterEditMode = useCallback(async () => {
    setEditing(true)

    // Most documents have no numbered sections at all — 22 of the 27 shapes — so there is no
    // next number to work out and asking for one is both pointless and actively misleading:
    // the plugin correctly answers "no numbered sections here", and reporting that as a
    // failure puts an error banner on an ordinary, healthy document. Ask only where an
    // answer is meaningful.
    if (!(doc?.sections ?? []).some((s) => s.kind === 'repeating_instance')) {
      setNextId(null)
      return
    }

    setNumbering(true)
    const next = await window.studio.nextNumber(projectPath, relPath)
    setNumbering(false)
    setNextId(next.ok ? next.id ?? null : null)
    // Here a failure IS a failure: this document has numbered sections, so not being able to
    // name the next one means something went wrong. It used to be discarded, and the only
    // visible trace was the add control quietly reading "Add another" — a silent degradation
    // wearing the costume of a design choice.
    if (!next.ok) setError(next.error ?? 'Could not work out the next number for this document.')
  }, [projectPath, relPath, doc])

  const saveField = useCallback(async (section: DocumentSection, label: string, value: string) => {
    setBusy(true)
    setError(null)
    const result = await window.studio.setField(projectPath, relPath, section.key, label, value)
    if (!result.ok) setError(result.error ?? 'Could not save that change.')
    else {
      setDoc(result)
      // The toast names the field, not the value — the card already shows what was written.
      toast({ tone: 'ok', title: 'Field saved', detail: `${label} · ${fileName}` })
    }
    setBusy(false)
  }, [projectPath, relPath, fileName])

  const addRequirement = useCallback(async () => {
    setBusy(true)
    setError(null)
    const result = await window.studio.addInstance(projectPath, relPath, '')
    if (!result.ok) setError(result.error ?? 'Could not add that.')
    else {
      setDoc(result)
      setNumbering(true)
      const next = await window.studio.nextNumber(projectPath, relPath)
      setNumbering(false)
      setNextId(next.ok ? next.id ?? null : null)
      if (!next.ok) setError(next.error ?? 'Could not work out the next number for this document.')
    }
    setBusy(false)
  }, [projectPath, relPath])

  if (!doc) {
    return (
      <div ref={rootRef} className="space-y-4" aria-busy="true">
        <p role="status" className="text-sm text-ink-3">Opening…</p>
        <SkeletonBlock lines={3} />
      </div>
    )
  }

  const hasRepeating = doc.sections.some((s) => s.kind === 'repeating_instance')

  return (
    <div ref={rootRef} className="space-y-6">
      {/* Inside the screen root, not around it: `<main>` is the scroll container and the e2e
          measures `main.firstElementChild`. */}
      <div ref={headerRef} className={STICKY_HEADER_CLASS}>
        <BackLink
          label="← Back to the stage"
          className="mb-1"
          onClick={() => {
            // Fire-and-forget, not awaited: the person already asked to leave, so navigation
            // happens immediately. The refresh updates the shared context in the background —
            // StageHome only blanks its screen on `loading` while it has no `readiness` yet
            // (see StageHome.tsx), which is never true here since reaching this screen at all
            // required a readiness fetch to have already completed. It just silently swaps in
            // the current data once the fetch resolves, with no flash the person would notice.
            void refreshReadiness()
            onBack()
          }}
        />
        {/* S1: the kit header — the stage this document belongs to as the eyebrow, the file name
            as the heading (byte-identical), the shape's description as the lede, the two controls
            as actions. The sticky block above is this screen's, so `sticky` is not passed. */}
        <PageHeader
          eyebrow={readiness?.ok ? readiness.display : undefined}
          title={fileName}
          lede={doc.description || undefined}
          actions={(
            <>
              <Button size="sm" icon={History} onClick={onShowHistory}>History</Button>
              {editing ? (
                // A toggle in its pressed state, not a brand-painted control: the kit's secondary
                // look plus `aria-pressed` says "editing is on" without borrowing the primary colour.
                <Button size="sm" variant="secondary" aria-pressed icon={Check} onClick={() => setEditing(false)}>
                  Done editing
                </Button>
              ) : (
                <Button
                  size="sm"
                  variant="primary"
                  icon={Pencil}
                  onClick={enterEditMode}
                  disabled={!doc.shaped}
                  disabledReason="This document has no shape, so its fields cannot be edited here."
                >
                  Edit
                </Button>
              )}
            </>
          )}
        />
        {/* Spec 0010: every field shows where the document lives, without leaving the page. A
            path is words, so ink-3 (C2: ink-4 is decoration only). */}
        <p className="mt-1 font-mono text-xs text-ink-3">{relPath}</p>
      </div>

      {changes.length > 0 && (
        <Notice
          tone="info"
          title="Changed since you last looked"
          actions={(
            <Button
              variant="ghost"
              size="sm"
              onClick={async () => {
                await window.studio.markDocumentSeen(projectPath, relPath)
                setChanges([])
              }}
            >
              Mark as seen
            </Button>
          )}
        >
          <ul className="mt-1 space-y-1">
            {changes.slice(0, 8).map((c, i) => (
              <li key={`${c.when}-${i}`}>
                <span className="font-medium">{c.author}</span>
                <span className="text-ink-3"> · {c.when} · </span>
                {c.reason}
              </li>
            ))}
          </ul>
        </Notice>
      )}

      {doc.pluginBehind && (
        // Not an error and not blocking: an older plugin still reads and saves every document
        // correctly. It just cannot offer everything this Studio can, and a person seeing a
        // section as plain text has no way to know that an update would change it.
        <Notice tone="warn" data-testid="plugin-behind" title="Your installed Shepherd plugin is older than this version of the app.">
          Everything still opens and saves correctly, but some parts of this document may show as
          plain text instead of editable fields. To update, run <code className="font-mono">claude plugin update</code>{' '}
          in a terminal, then reopen the document.
        </Notice>
      )}

      {doc.shaped && <TemplateGapsNotice warnings={doc.warnings} />}

      {!doc.shaped && doc.warnings.length > 0 && (
        <Notice tone="warn" title="This document is shown as plain text.">
          <ul className="space-y-0.5">
            {doc.warnings.map((w) => <li key={w}>{w}</li>)}
          </ul>
          <p className="mt-2">Nothing is hidden — everything in the file is below, exactly as written.</p>
        </Notice>
      )}

      {error && (
        // The test hook is here because asserting "no error is shown" by matching the wording
        // proves nothing: a test that looks for the wrong sentence passes whether or not the
        // banner is there. That happened — a regression test for the false-alarm defect below
        // passed with the defect still in place, because the real message was different.
        <Notice tone="error" data-testid="document-error">{error}</Notice>
      )}

      {/* S5: the sections, with the outline rail beside them from xl up (220 px, sticky under the
          header). Below xl the rail is not drawn — the sections already read top to bottom. */}
      <div className="xl:flex xl:items-start xl:gap-6">
        <div className="min-w-0 flex-1 space-y-6">
          <div className="space-y-3">
            {doc.sections.map((section) => (
              <SectionCard
                key={section.key}
                section={section}
                editing={editing}
                busy={busy}
                projectPath={projectPath}
                relPath={relPath}
                actor={actor}
                highlighted={section.key === focusedKey}
                highlightField={section.key === focusedKey && focused?.fromFinding ? focus?.field ?? null : null}
                highlightNote={focused?.fromFinding ? undefined : null}
                onSaveField={saveField}
              />
            ))}
          </div>

          {/* The add control exists ONLY in edit mode, and shows the number it will use before
              anything is created — spec 0010's acceptance check asks for exactly that.
              THREE states, never two. "Add another" once meant both "this document has no
              numbered sections" and "the number has not come back yet", because working it out
              is a call into another process. A slow answer then looked exactly like no answer —
              which is how a passing feature came to be reported as an unbuilt one. */}
          {editing && hasRepeating && (
            <Button
              block
              onClick={addRequirement}
              disabled={busy || numbering}
              className="rounded-xl border-dashed py-3 text-sm font-medium text-ink-2 hover:border-accent-500 hover:text-accent-text-hover"
            >
              {numbering ? 'Working out the next number…' : nextId ? `Add ${nextId}` : 'Add another'}
            </Button>
          )}
        </div>
        <DocumentOutline
          sections={doc.sections}
          findings={readiness?.ok ? readiness.findings : []}
          relPath={relPath}
          activeKey={focusedKey}
          onSelect={pickSection}
          className="hidden xl:sticky xl:top-24 xl:block"
        />
      </div>
    </div>
  )
}
