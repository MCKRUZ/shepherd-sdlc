import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { ArrowUp, MessageSquare, Square } from 'lucide-react'
import type { ChatMessage, ChatProposal, ChatQuestion, ChatState, ProjectStatus } from '../../shared/types'
import { connectingSteps } from '../chatConnectingSteps'
import { computeWorkflowSteps } from '../workflowSteps'
import { chatMessage, contextFrom, questionPills } from '../motion/choreo'
import { enabled as motionEnabled, motion, reduced as motionReduced } from '../motion/motion'
import { useStudioGSAP } from '../motion/useStudioGSAP'
import { Button, Card, Chip, EYEBROW_CLASS, EmptyState, IconButton, Notice, Textarea, cn } from '../ui'
import { useRegisterDirty } from '../stores/dirtyStore'
import { chatTurnStore } from '../stores/chatTurnStore'
import { AiProposalCard } from './AiProposalCard'
import { ChatActivityLine } from './ChatActivityLine'
import { ChatResizeHandle } from './ChatResizeHandle'
import { ConnectingChecklist } from './ConnectingChecklist'
import { MarkdownView } from './MarkdownView'
import { CHAT_MIN_WIDTH, useChatWidth } from '../chatWidth'
import { registerChatSender, type ChatSendResult } from '../chatBridge'
import { useStageReadiness } from './StageReadinessContext'
import { useClaudeIssue } from './ClaudeIssueContext'

/** The `<aside>` class string, spelled once and never animated: `ChatPanel.test.tsx` pins
 * `max-h-[35vh]` / `sm:max-h-none`, chatLook pins the exact 380 px width on double-click (so no
 * width transition), and Frame's assemble choreography (§4 #2) moves the INNER wrapper
 * (`[data-chat-inner]`), never this element. */
const ASIDE_CLASS = 'relative flex max-h-[35vh] w-full shrink-0 flex-col border-l border-line-1 bg-surface-1 sm:max-h-none sm:w-[var(--chat-width)]'

/** The collapsed aside (owner's v12 item 1): the same element, now a 40 px rail holding ONE
 * control that reopens it. The inner wrapper is `hidden`, never unmounted — the thread, its
 * draft and its width survive — and the shell still has exactly two asides. `sm:!w-10` beats
 * the inline `--chat-width` the aside still carries for the moment it reopens. */
const ASIDE_COLLAPSED_CLASS = 'relative flex max-h-[35vh] w-full shrink-0 flex-col border-l border-line-1 bg-surface-1 sm:max-h-none sm:!w-10'

/** Why Stop is greyed: there is no cancel verb for a chat turn yet, and a button that looked
 * live would promise one. Said in the person's words, not the backlog's (C5). */
const STOP_REASON = 'Stopping a reply is not available yet'

/** Present on every screen (spec 0008's own requirement) — spec 0016 wires the actual
 * conversation up, and spec 0018 scopes it to the stage's current document and makes the wait
 * before it is ready legible instead of looking identical to "ready and idle". A real, multi-turn
 * `claude` session drives a stage's documents: the assistant opens on a stage with a document not
 * yet started, structured questions render as real buttons alongside a message in the thread
 * (never gating the box below), and every proposed write is a card the person accepts, edits, or
 * discards — never a silent write. */
export function ChatPanel({
  status, projectPath, actor, stageId, hidden = false, collapsed = false, onExpand, onWidthChange,
}: {
  status: ProjectStatus | null
  projectPath: string | null
  actor: string
  /** The stage this chat is scoped to — the viewed stage, or the project's current one. Null
   * when no project is open, or the project has no stages yet. */
  stageId: string | null
  /** Frame's chat toggle. Adds `hidden` to the `<aside>` rather than unmounting it, so the
   * conversation, its draft and its width survive being tucked away; the shell still has
   * exactly two asides in the DOM either way. */
  hidden?: boolean
  /** Collapsed to its rail (chatStore, per area): the inner wrapper is hidden, the aside stays
   * 40 px wide with one control that calls `onExpand`. Steering uses `hidden`, not this. */
  collapsed?: boolean
  onExpand?: () => void
  /** Reports the applied width (px) whenever it changes, so the Frame root can carry
   * `--chat-width` for the screens beside this panel. The aside still sets its own variable. */
  onWidthChange?: (px: number) => void
}) {
  const [state, setState] = useState<ChatState | null>(null)
  // The one shared getStageReadiness read for this stage (spec 0019's StageReadinessProvider,
  // which Frame.tsx wraps this panel in) — not a fetch of its own. Used to label which document
  // this conversation is helping with (computeWorkflowSteps' own "current" rule) and to gate the
  // connecting checklist's "Reading" step; never written to.
  //
  // Finding #1 (PR #76 round 2): used directly, with NO loading-based nulling — the Provider
  // deliberately keeps the OLD stage's `readiness` on screen until the NEW stage's fetch resolves
  // (so a sidebar line doesn't flash empty), and StageHome/WorkflowTab already read it the same
  // way (`loading && !readiness`, which is false the whole time stale data is held). This panel
  // used to disagree: nulling `readiness` for the entire loading window reset the header's
  // document name and the "Reading" checklist step to a neutral/blank state while the document
  // panel right beside it kept showing the OLD stage's content — a visible contradiction until
  // the fetch settled. Showing the same stale-but-valid data here keeps every reader of this one
  // shared value telling the same story during a switch, exactly as the REST of the screen does.
  const { readiness, loading: readinessLoading, error: readinessError } = useStageReadiness()
  // The panel's width is the person's to set (dragged, or by keyboard on the handle). Applied
  // as a CSS variable so only the side-by-side layout uses it — below `sm` the panels stack and
  // the panel is full width regardless.
  const chatWidth = useChatWidth()
  const widthStyle = { '--chat-width': `${chatWidth.width}px` } as CSSProperties
  useEffect(() => { onWidthChange?.(chatWidth.width) }, [onWidthChange, chatWidth.width])
  const [busy, setBusy] = useState(false)
  // True once the chat flow (including the model's own first turn, when one was needed) has
  // actually finished for THIS stage — reset to false at the top of the mount effect below on
  // every stage switch. `initializing` (derived below, finding #6) reads this directly rather
  // than copying it into a second piece of state.
  const [chatSettled, setChatSettled] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const listRef = useRef<HTMLDivElement>(null)
  // What stage is actually on screen right now, readable from inside a handler's async
  // continuation — a plain closure variable would only ever hold the stage the handler was
  // CALLED for, which is exactly the bug this guards: switching stages while submit/answer/
  // resolveProposal is still awaiting its reply must not apply that stale reply's state to
  // whatever stage is on screen by the time it comes back, or send the next message to the
  // session the person already navigated away from believing they're on a different one.
  const currentStageId = useRef(stageId)
  useEffect(() => { currentStageId.current = stageId }, [stageId])
  // Bumped by the empty state's Retry after a failed start: the start effect below runs again
  // for the same stage, exactly as a stage switch would, with the error cleared first.
  const [startAttempt, setStartAttempt] = useState(0)

  useEffect(() => {
    if (!projectPath || !stageId) {
      setState(null)
      setBusy(false)
      setChatSettled(false)
      return
    }
    let cancelled = false
    setState(null)
    setError(null)
    // Reset synchronously on every stage switch, not just state/error — otherwise navigating
    // away from a stage while its auto-greet is still in flight (busy=true, awaiting
    // ensureChatStarted below) leaves the NEW stage's composer permanently disabled: that
    // in-flight call's own `if (cancelled) return` guard (below) correctly skips setBusy(false)
    // for the stage it was actually for, but nothing else was ever going to reset it back.
    setBusy(false)
    setChatSettled(false)

    // The readiness half of "ready" is now the shared read spec 0019's StageReadinessProvider
    // already owns (see `sharedReadiness`/`readinessLoading` above) — Frame.tsx wraps this panel
    // in it alongside StageHome, so this effect only drives the CHAT half. This used to also run
    // its own independent getStageReadiness() call in parallel (a 3rd/4th redundant read for the
    // same stage on one screen, alongside StageHome's and ensureChatStarted's own internal one) —
    // that duplication is exactly what spec 0019 removed; see StageReadinessContext.tsx.
    window.studio.getChatState(projectPath, stageId).then(async (loaded) => {
      if (cancelled) return
      setState(loaded)
      if (loaded.messages.length === 0) {
        setBusy(true)
        chatTurnStore.publish(projectPath, stageId, 'running')
        const result = await window.studio.ensureChatStarted(projectPath, stageId)
        if (cancelled) return // a stale reply for a stage the person already navigated away from
        setBusy(false)
        chatTurnStore.publish(projectPath, stageId, result.ok ? 'ended' : 'failed')
        if (!result.ok) setError(result.error ?? 'The assistant could not start.')
        setState(result.state)
      }
      if (!cancelled) setChatSettled(true)
    }).catch((err: unknown) => {
      // A real IPC round trip into the main process and can reject outright — the same
      // TOCTOU-class gap StageReadinessContext.tsx's own `refresh()` guards against. Surface it
      // through the same error banner an ordinary turn failure already renders, and still let
      // `chatSettled` flip so this half can't get stuck — the checklist's "Loading" step depends
      // on BOTH halves below, so a readiness-side failure (handled separately, in the context
      // itself) still correctly keeps that step from reading done.
      if (cancelled) return
      // CI's correctness-review (PR #76 round 3): this catch also fires when `ensureChatStarted`
      // rejects INSIDE the `.then` above, after `setBusy(true)` already ran for it — without
      // resetting it here too, `busy` stays stuck true forever for this stage: the composer
      // (bound to `disabled={busy}`) never re-enables, even once the error below is showing.
      setBusy(false)
      chatTurnStore.publish(projectPath, stageId, 'failed')
      setError(err instanceof Error ? err.message : 'The assistant could not start.')
      // Finding #4 (PR #76 round 2): without this, `state` stays null forever once this half
      // settles below — ChatMessageList's `state === null` check keeps rendering "Starting the
      // conversation…" permanently, right next to the error banner this sets, with no way to
      // tell the difference between "still starting" and "definitively failed". An empty-but-
      // non-null state (matching `emptyState()`'s shape used throughout this file's own tests)
      // lets ChatMessageList's OTHER empty-but-not-busy branch render instead, which reads the
      // `startError` prop below to show failure-specific text rather than its normal "already
      // started" copy.
      setState({ sessionId: null, messages: [] })
      setChatSettled(true)
    })

    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- actor changing mid-conversation should not re-greet
  }, [projectPath, stageId, startAttempt])

  // "Ready" only once BOTH halves have settled — the chat flow above (including the model's own
  // first turn, when one was needed) AND the shared readiness read — so the checklist can never
  // read as done before both of its underlying signals actually have. `chatSettled` is reset to
  // false at the top of the effect above on every stage switch, and `readinessLoading` already
  // reflects the CURRENT stage (StageReadinessProvider is keyed the same way), so this needs no
  // stage guard of its own — it can only read both true once both genuinely belong to the stage
  // on screen.
  //
  // Finding #6 (PR #76 round 2): a plain derived value, not a second piece of state copied in by
  // its own `useEffect`. The old `useState` + effect pair meant `initializing` only caught up to
  // `chatSettled`/`readinessLoading` ONE RENDER AFTER they actually changed — a stale extra frame
  // on every settle, the same self-referential-flag bug class `chatSettled` itself (see its own
  // comment above) was already written to avoid. Computing it directly here removes that lag
  // entirely: there is no render where `chatSettled`/`readinessLoading` have already flipped but
  // `initializing` has not yet caught up.
  const initializing = !chatSettled || readinessLoading

  // The Workflow tab's "Talk it through" asks this panel to send one turn through the SAME path a
  // typed message takes. The registered function is stable per chat-capable state and reads the
  // latest `sendText` through a ref, since that is defined below the early return.
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const sendTextRef = useRef<((text: string) => Promise<ChatSendResult>) | null>(null)
  const canChat = Boolean(projectPath && stageId)
  useEffect(() => {
    if (!canChat) return
    return registerChatSender((text) => sendTextRef.current?.(text) ?? Promise.resolve({ sent: false, reason: 'The chat is not open.' }))
  }, [canChat])

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight })
  }, [state?.messages.length])

  // An open proposal is a decision waiting on a person; Esc-as-back must not navigate past it (§6.2).
  // Rules of Hooks: this is the LAST hook and it sits ABOVE the placeholder return below. The
  // same fiber goes stageId → null (every stage signed off, or a corrupt `current_phase`) and
  // back without a remount (Frame renders `<MemoChatPanel>` with no key), so a hook called after
  // that return changed the hook count between renders and threw React #310 with no boundary
  // above App to catch it. With no messages the predicate is simply false.
  const hasPendingProposal = state?.messages.some((m) => m.proposals.some((p) => !p.outcome)) ?? false
  useRegisterDirty(() => hasPendingProposal)

  if (!projectPath || !stageId) {
    return <ChatPlaceholder status={status} style={widthStyle} hidden={hidden} collapsed={collapsed} onExpand={onExpand} />
  }

  // The current step's document, by the SAME rule the Workflow tab uses to pick it — null while
  // readiness has not answered yet, or when the current step is Sign-off (nothing to name).
  const currentDocumentTitle = readiness?.ok
    ? computeWorkflowSteps(readiness).find((s) => s.status === 'current' && s.kind === 'document')?.title ?? null
    : null
  // What the empty state says about where it is (S9): the stage's display name, from the shared
  // readiness read, or the project's current phase while that has not answered.
  const stageDisplay = readiness?.ok ? readiness.display : status?.current_phase.display ?? null

  const sendText = async (text: string): Promise<ChatSendResult> => {
    if (busy) return { sent: false, reason: 'The chat is busy with another message. Try again in a moment.' }
    const forStage = stageId
    setBusy(true)
    setError(null)
    chatTurnStore.publish(projectPath, stageId, 'running')
    const result = await window.studio.sendChatMessage(projectPath, stageId, text)
    chatTurnStore.publish(projectPath, forStage, result.ok ? 'ended' : 'failed')
    if (currentStageId.current !== forStage) return { sent: true } // the person moved on; this reply is now stale
    setBusy(false)
    // Always render the result, success or failure: on failure, `result.state` still carries
    // the message the person just sent (chat.ts persists it even when the turn itself fails) —
    // skipping this on failure was how that message used to vanish, shown nowhere at all
    // despite having been genuinely submitted.
    setState(result.state)
    if (!result.ok) setError(result.error ?? 'The assistant could not respond.')
    return { sent: true }
  }

  const submit = async () => {
    const text = draft.trim()
    if (!text || busy) return
    setDraft('')
    await sendText(text)
  }

  sendTextRef.current = async (text) => {
    if (initializing) return { sent: false, reason: 'The chat is still connecting. Try again in a moment.' }
    composerRef.current?.focus()
    composerRef.current?.scrollIntoView?.({ block: 'nearest' })
    return sendText(text)
  }

  const answer = async (questionId: string, option: string) => {
    const forStage = stageId
    setBusy(true)
    setError(null)
    chatTurnStore.publish(projectPath, stageId, 'running')
    const result = await window.studio.answerChatQuestion(projectPath, stageId, questionId, option)
    chatTurnStore.publish(projectPath, forStage, result.ok ? 'ended' : 'failed')
    if (currentStageId.current !== forStage) return
    setBusy(false)
    setState(result.state)
    if (!result.ok) setError(result.error ?? 'The assistant could not respond.')
  }

  const resolveProposal = async (proposalId: string, outcome: 'accepted' | 'edited' | 'discarded', finalValue: string) => {
    const forStage = stageId
    setBusy(true)
    setError(null)
    chatTurnStore.publish(projectPath, stageId, 'running')
    const result = await window.studio.resolveChatProposal(projectPath, stageId, proposalId, outcome, finalValue, actor || 'unknown')
    chatTurnStore.publish(projectPath, forStage, result.ok ? 'ended' : 'failed')
    if (currentStageId.current !== forStage) return
    setBusy(false)
    setState(result.state)
    if (!result.ok) setError(result.error ?? 'That could not be saved.')
  }

  return (
    // `max-h-[35vh] sm:max-h-none` — finding #5 (PR #76 round 2): the same mobile-stacking bug
    // class Sidebar.tsx was already fixed for in this PR (its own comment explains the mechanism:
    // below `sm`, Frame.tsx's row becomes a COLUMN, so an uncapped sibling's main axis sizes to
    // content and pushes everything after it off-screen). This `<aside>` is Frame.tsx's THIRD
    // stacked sibling and had no cap of its own. Deliberately smaller than Sidebar's 50vh, not
    // the same value: with two capped siblings now sharing one viewport, giving both 50vh could
    // sum to the full 100vh in the worst case (a tall stage list alongside a long conversation),
    // squeezing the main document panel — spec 0018's actual reason this screen stacks at all —
    // down to nothing. 35vh keeps the two capped siblings' combined worst case at 85vh, always
    // leaving the document panel real room, while still giving the conversation meaningfully
    // more than a token sliver.
    <aside style={widthStyle} data-chat-collapsed={collapsed ? '' : undefined} className={cn(collapsed ? ASIDE_COLLAPSED_CLASS : ASIDE_CLASS, hidden && 'hidden')}>
      {collapsed ? <ChatRail onExpand={onExpand} /> : (
        <ChatResizeHandle
          width={chatWidth.width}
          min={CHAT_MIN_WIDTH}
          max={chatWidth.max}
          onResize={chatWidth.setWidth}
          onCommit={chatWidth.commit}
          onReset={chatWidth.reset}
        />
      )}
      <div data-chat-inner="" className={cn('flex min-h-0 flex-1 flex-col', collapsed && 'hidden')}>
        <ChatHeader status={status} projectOpen currentDocumentTitle={currentDocumentTitle} />
        {initializing ? (
          <ConnectingChecklist steps={connectingSteps(state, readiness, chatSettled, status, currentDocumentTitle)} />
        ) : (
          <>
            <ChatMessageList listRef={listRef} state={state} busy={busy} projectPath={projectPath} stageId={stageId} startError={error} stageDisplay={stageDisplay} onAnswer={answer} onResolveProposal={resolveProposal} onRetryStart={() => setStartAttempt((n) => n + 1)} />
            {/* A chat-turn failure takes priority when both are set — it's the more recent, more
                actionable one; the shared readiness error is what proves this panel isn't silently
                stuck with no document scoping after that fetch failed outright (PR #76 finding #2,
                now owned by StageReadinessContext.tsx — see its own error field). Inline, never a
                toast (§6.6): the next turn is the retry.
                While the thread is still EMPTY the chat error is stated once, in the empty-state
                block above (a failed auto-start is a fact, not an alarm over an empty room), so the
                strip only carries it once there is a conversation for a failed turn to sit under.
                The readiness error is a different fact and keeps its line either way. */}
            {(((state?.messages.length ?? 0) > 0 && error) || readinessError) && (
              <Notice tone="error" className="rounded-none border-x-0 border-b-0">
                {((state?.messages.length ?? 0) > 0 && error) || readinessError}
              </Notice>
            )}
            <ChatComposer inputRef={composerRef} draft={draft} setDraft={setDraft} busy={busy} hasPendingProposal={hasPendingProposal} onSubmit={submit} />
          </>
        )}
      </div>
    </aside>
  )
}

/** `status` is the authoritative signal here, checked FIRST (finding #2, PR #76 round 2):
 * once it has loaded, the real project/phase (or document) line always shows, regardless of
 * `projectOpen` — `stageId` can be `null` even with a project genuinely open and fully loaded
 * (Frame.tsx's `currentStageId` is `undefined` once every stage is signed off), and in that case
 * showing "open a project first" would be actively wrong, telling the reader to do something
 * they've already done.
 *
 * `status` can ALSO be null in two different situations, which is where `projectOpen` still
 * earns its keep: no project is open at all, versus a project (and stage) IS open but its status
 * has not finished loading yet. Those two get told apart only once `status` itself is absent.
 *
 * The heading itself stays the literal word "Chat" (spec 0016's own e2e test locates the panel
 * by it) — spec 0018's "scoped to the current document" shows up in the SUBTITLE instead, naming
 * the document this conversation is helping with once readiness has answered which one that is. */
function ChatHeader({
  status, projectOpen, currentDocumentTitle,
}: {
  status: ProjectStatus | null
  projectOpen: boolean
  currentDocumentTitle?: string | null
}) {
  // S9: the document's name is a Chip (identifier casing), so the header reads "Helping with:"
  // once and the filename sits as the one identifier it is, not as part of a sentence.
  const subtitle = !status
    ? (projectOpen ? 'Can see: loading…' : 'Can see: nothing yet — open a project first.')
    : currentDocumentTitle
      ? <>Helping with: <Chip casing="identifier" size="xs" className="ml-0.5 max-w-full" data-testid="chat-helping-with">{currentDocumentTitle}</Chip></>
      : `Can see: ${status.project_name}, ${status.current_phase.display}.`
  return (
    // 11 px vertical padding lands the header on the same 44 px line as the sidebar's project
    // row, so the two asides share one top edge.
    <div className="border-b border-line-1 px-4 py-[11px]">
      <h2 className="text-sm font-semibold text-ink-1">Chat</h2>
      <p className="mt-0.5 flex min-w-0 items-center truncate text-xs text-ink-3">{subtitle}</p>
    </div>
  )
}

/** The collapsed rail's one control: reopens the chat. Its accessible name says what it does and
 * carries the key; `aria-expanded="false"` tells assistive tech the panel is there, folded. Not
 * a heading — the steering pin counts `heading[name=Chat]` and a rail is not a chat. */
export const CHAT_RAIL_LABEL = 'Open the chat'

function ChatRail({ onExpand }: { onExpand?: () => void }) {
  return (
    <div data-chat-rail="" className="flex flex-1 flex-col items-center gap-2 py-2">
      <IconButton
        label={CHAT_RAIL_LABEL}
        icon={MessageSquare}
        aria-expanded={false}
        aria-keyshortcuts="Meta+Backslash Control+Backslash"
        title={`${CHAT_RAIL_LABEL} (⌘\\)`}
        onClick={onExpand}
        disabled={!onExpand}
        disabledReason={onExpand ? undefined : 'the shell did not pass a chat toggle'}
      />
      <span aria-hidden="true" className="text-[11px] font-medium uppercase tracking-[0.08em] text-ink-3 [writing-mode:vertical-rl]">Chat</span>
    </div>
  )
}

function ChatPlaceholder({ status, style, hidden, collapsed, onExpand }: { status: ProjectStatus | null; style: CSSProperties; hidden: boolean; collapsed: boolean; onExpand?: () => void }) {
  return (
    // Same cap as the main panel's own `<aside>` above (finding #5) — this renders in the exact
    // same Frame.tsx sibling slot whenever no project/stage is open, so it is just as capable of
    // pushing the document panel off-screen at phone width if left uncapped. `relative` is
    // harmless here (no handle to position) and keeps the one class string.
    <aside style={style} data-chat-collapsed={collapsed ? '' : undefined} className={cn(collapsed ? ASIDE_COLLAPSED_CLASS : ASIDE_CLASS, hidden && 'hidden')}>
      {collapsed && <ChatRail onExpand={onExpand} />}
      <div data-chat-inner="" className={cn('flex min-h-0 flex-1 flex-col', collapsed && 'hidden')}>
        <ChatHeader status={status} projectOpen={false} />
        {/* The kit's one "nothing here, and why" frame (G4-9); the sentence is unchanged. */}
        <div className="flex flex-1 flex-col justify-end p-3">
          <EmptyState title="Open a stage to start a conversation." />
        </div>
      </div>
    </aside>
  )
}

/** The §4 #13 arrival, played on the LAST bubble only when the count grew — a re-render of an
 * existing bubble (a question answered, a proposal resolved) is not an arrival. The sub-agent
 * dashed border settles from the accent to `line-2`; the colours are read from the theme's custom
 * properties here because a choreography never reads a CSS variable itself. */
function useMessageArrival(listRef: React.RefObject<HTMLDivElement | null>, count: number) {
  const previous = useRef<number | null>(null)
  useStudioGSAP(() => {
    const list = listRef.current
    const grew = previous.current !== null && count > previous.current
    previous.current = count
    if (!list || !grew) return
    const bubbles = list.querySelectorAll('[data-chat-bubble]')
    const bubble = bubbles[bubbles.length - 1]
    if (!bubble) return
    const vars = getComputedStyle(document.documentElement)
    const ctx = contextFrom(list, { enabled: motionEnabled(), reduced: motionReduced() }, motion)
    chatMessage.play(ctx, {
      bubble,
      subAgent: bubble.getAttribute('data-chat-bubble') === 'subagent',
      accentColor: vars.getPropertyValue('--color-accent-600').trim() || undefined,
      lineColor: vars.getPropertyValue('--color-line-2').trim() || undefined,
    })
  }, { scope: listRef, dependencies: [count] })
}

/** S9: the empty and the failed conversation, as one `EmptyState` at the TOP of the list region
 * (an empty room reads from its door, not its far wall). The sentence is unchanged; beneath it
 * the retry hint, then where this chat is — the stage · "read-only until you accept a proposal"
 * — as a quieter line. The document's name is NOT repeated here: the header's Chip is the one
 * place the filename appears. The hint comes BEFORE the facts line on purpose: chatAuthoring
 * matches `/already started\. Ask a question/` as one text run, and Playwright joins an element's
 * text without separators, so the title ends in a trailing space and the hint must follow it
 * directly. No `<li>` anywhere (chatLook counts exactly four in the aside). The failure message
 * sits in its own span so a test (and a reader) can find the host's words on their own. */
/** Does the host's own error already say that the assistant failed? The CLI's two default
 * sentences do; a raw message ("claude: not signed in") does not and gets the title before it. */
export function errorNamesTheFailure(error: string): boolean {
  return /^The assistant could not (start|respond)\b/.test(error.trim())
}

export const RETRY_START = 'Retry'

function ChatEmptyState({ startError, stageDisplay, onRetry }: {
  startError: string | null
  stageDisplay: string | null
  onRetry?: () => void
}) {
  const facts = [stageDisplay, 'read-only until you accept a proposal'].filter((f): f is string => Boolean(f))
  if (startError) {
    // A failed start is a quiet fact, not a hero: one small block in `ink-3` with the host's words
    // in their own span and the retry hint — the same sentences, no figure (fixer round, v11).
    // ONE failure sentence (v13): when the host's words already name the failure ("The assistant
    // could not respond.") they stand alone in `ink-2`; the fixed title precedes only a raw
    // message. The Retry button re-runs the start — the hint is still true, the button is quicker.
    const titled = !errorNamesTheFailure(startError)
    return (
      <div data-testid="chat-empty-state" className="px-1 py-2 text-xs leading-4 text-ink-3">
        <p>
          {titled && <><span className="font-medium text-ink-2">The assistant could not start.</span>{' '}</>}
          <span className={titled ? undefined : 'font-medium text-ink-2'} data-testid="chat-start-error">{startError}</span>
          {' '}Type a message to try again, or open a document to edit it directly.
        </p>
        <span className="mt-1.5 block" data-testid="chat-empty-facts">{facts.join(' · ')}</span>
        {onRetry && <Button size="sm" variant="secondary" className="mt-2" onClick={onRetry} data-testid="chat-retry-start">{RETRY_START}</Button>}
      </div>
    )
  }
  return (
    <EmptyState
      figure="conversation"
      data-testid="chat-empty-state"
      className="border-0 px-1 py-2"
      title={<>{startError ? 'The assistant could not start.' : "This stage's documents are already started."}{' '}</>}
      body={(
        <>
          {startError
            ? <><span>{startError}</span> Type a message to try again, or open a document to edit it directly.</>
            : 'Ask a question, or open a document to edit it directly.'}
          <span className="mt-1.5 block text-ink-3" data-testid="chat-empty-facts">{facts.join(' · ')}</span>
        </>
      )}
    />
  )
}

function ChatMessageList({
  listRef, state, busy, projectPath, stageId, startError, stageDisplay, onAnswer, onResolveProposal, onRetryStart,
}: {
  listRef: React.RefObject<HTMLDivElement | null>
  state: ChatState | null
  busy: boolean
  projectPath: string
  stageId: string
  /** Set when the chat flow has definitively failed to start (finding #4, PR #76 round 2) — swaps
   * the empty-session message below for one that admits the failure, rather than the "already
   * started" copy that branch normally shows for an ordinary, no-error empty session. */
  startError: string | null
  /** The stage's display name for the empty state's facts line (S9). */
  stageDisplay: string | null
  onAnswer: (questionId: string, option: string) => void
  onResolveProposal: (proposalId: string, outcome: 'accepted' | 'edited' | 'discarded', finalValue: string) => void
  /** Re-run the start after a failure (the empty state's Retry). */
  onRetryStart?: () => void
}) {
  useMessageArrival(listRef, state?.messages.length ?? 0)
  return (
    <div ref={listRef} className="flex-1 space-y-3 overflow-auto px-3 py-3">
      {state === null || (state.messages.length === 0 && busy) ? (
        <p className="text-xs text-ink-3">Starting the conversation…</p>
      ) : state.messages.length === 0 ? (
        <ChatEmptyState startError={startError} stageDisplay={stageDisplay} onRetry={onRetryStart} />
      ) : (
        state.messages.map((message) => (
          <MessageBubble key={message.id} message={message} busy={busy} onAnswer={onAnswer} onResolveProposal={onResolveProposal} />
        ))
      )}
      {busy && state !== null && state.messages.length > 0 && projectPath && stageId && (
        <ChatActivityLine projectPath={projectPath} stageId={stageId} />
      )}
    </div>
  )
}

/** Free text stays usable at all times once the conversation is ready (spec 0018) — a pending
 * structured question is answered by its own quick-reply chips, rendered inline in the thread
 * (see `QuestionPrompt`), never by gating this box. Typing something that is NOT an answer to
 * that question is just the next ordinary turn, exactly as spec 0016's chat already works. */
function ChatComposer({
  inputRef, draft, setDraft, busy, hasPendingProposal, onSubmit,
}: {
  inputRef: React.RefObject<HTMLTextAreaElement | null>
  draft: string
  setDraft: (value: string) => void
  busy: boolean
  hasPendingProposal: boolean
  onSubmit: () => void
}) {
  // A turn is a model call; when the installed Claude Code lacks a flag Studio emits, the box
  // says so where the person would type, instead of failing after Enter (F1).
  const claudeIssue = useClaudeIssue()
  // One line at rest, growing with the draft up to 160 px — then the field scrolls. Measured
  // from scrollHeight after a reset to `auto`, because a textarea never shrinks on its own.
  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [draft, inputRef])
  return (
    <div className="border-t border-line-1 p-3">
      {/* One field, one glyph (G4-7): the frame carries the focus ring (`focus-within`), so the
          textarea itself draws no border or shadow and the composer reads as a single control. */}
      <div className="flex items-end gap-1.5 rounded-[12px] border border-line-2 bg-surface-1 p-1.5 pl-3 transition-[border-color,box-shadow] duration-[120ms] focus-within:border-focus focus-within:shadow-[0_0_0_3px_color-mix(in_srgb,var(--color-focus)_22%,transparent)]">
        <Textarea
          ref={inputRef}
          data-testid="chat-composer-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSubmit() }
          }}
          disabled={busy || claudeIssue !== null}
          placeholder={claudeIssue ?? 'Type a message…'}
          rows={1}
          className="min-h-[24px] max-h-[160px] flex-1 resize-none border-0 bg-transparent px-0 py-1 shadow-none focus-visible:shadow-none"
        />
        {busy ? (
          <IconButton label="Stop" icon={Square} size="sm" disabled disabledReason={STOP_REASON} />
        ) : (
          <IconButton
            label="Send"
            icon={ArrowUp}
            size="sm"
            onClick={onSubmit}
            disabled={!draft.trim() || claudeIssue !== null}
            className="rounded-[8px] bg-brand-600 text-white hover:bg-brand-700 hover:text-white disabled:bg-surface-3 disabled:text-ink-4"
          />
        )}
      </div>
      {hasPendingProposal && (
        <p className="mt-1 text-xs text-ink-3">A proposal above is waiting on you.</p>
      )}
    </div>
  )
}

/** The three bubble class strings are literal on purpose: chatAuthoring finds a reply by
 * `.bg-slate-100, .border-dashed` and `ChatPanel.test.tsx` reads them too. Bubbles are `div`s,
 * not `li`s — chatLook counts exactly four `li` in the aside, all of them markdown. */
function MessageBubble({
  message, busy, onAnswer, onResolveProposal,
}: {
  message: ChatMessage
  busy: boolean
  onAnswer: (questionId: string, option: string) => void
  onResolveProposal: (proposalId: string, outcome: 'accepted' | 'edited' | 'discarded', finalValue: string) => void
}) {
  const isUser = message.role === 'user'
  const isSubagent = message.role === 'subagent'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        data-chat-bubble={isUser ? 'user' : isSubagent ? 'subagent' : 'assistant'}
        // The tight corner sits on the speaker's side (bottom-right for the person, bottom-left
        // for the assistant and sub-agents), so who spoke reads from the shape, not from colour.
        className={`max-w-[88%] rounded-[12px] px-3 py-2 text-sm leading-[1.45] ${
          isUser ? 'rounded-br-[4px] bg-brand-600 text-white' : isSubagent ? 'rounded-bl-[4px] border border-dashed border-line-2 bg-surface-0 text-ink-2' : 'rounded-bl-[4px] bg-slate-100 text-ink-1'
        }`}
      >
        {isSubagent && (
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-eyebrow">
            {message.subagentType ?? 'sub-agent'}
          </p>
        )}
        {/* The person's own words stay exactly as typed; the assistant's and sub-agents' replies are
            model output written in markdown, drawn through the same hardened renderer the
            documents use (raw HTML dropped, links never clickable, images never fetched). */}
        {message.text && (isUser
          ? <p className="whitespace-pre-wrap break-words">{message.text}</p>
          : <div className="break-words"><MarkdownView source={message.text} /></div>)}

        {/* A single reply may ask more than one structured question, or propose more than one
            write — each renders as its own card rather than only the last one reaching the
            person (see chatStreamParse.ts's own header for why that used to happen). */}
        {message.questions.map((question) => (
          <QuestionPrompt key={question.id} question={question} busy={busy} onAnswer={(option) => onAnswer(question.id, option)} />
        ))}

        {message.proposals.map((proposal) => (
          <ProposalCard
            key={proposal.id}
            proposal={proposal}
            busy={busy}
            onResolve={(outcome, finalValue) => onResolveProposal(proposal.id, outcome, finalValue)}
          />
        ))}
      </div>
    </div>
  )
}

/** Quick replies as `Chip as="button"` — the kit keeps `rounded-full`, which chatAuthoring locates
 * the options by (`aside button.rounded-full`). The pills slide in once, when the question first
 * renders (§4 #14); an answered question swaps to its "You picked" line with no motion. */
function QuestionPrompt({
  question, busy, onAnswer,
}: {
  question: ChatQuestion
  busy: boolean
  onAnswer: (option: string) => void
}) {
  const pillsRef = useRef<HTMLDivElement>(null)
  useStudioGSAP(() => {
    const row = pillsRef.current
    if (!row) return
    const ctx = contextFrom(row, { enabled: motionEnabled(), reduced: motionReduced() }, motion)
    questionPills.play(ctx, { pills: Array.from(row.children) })
  }, { scope: pillsRef, dependencies: [question.id] })
  return (
    <div className="mt-2 space-y-1">
      <p className="text-xs font-medium text-ink-3">{question.question}</p>
      {question.answeredWith ? (
        <p className="text-xs text-ink-3">You picked: <span className="font-semibold text-accent-text">{question.answeredWith}</span></p>
      ) : (
        <div ref={pillsRef} className="flex flex-wrap gap-1.5">
          {/* C1: the quick replies read in `accent-text` (legible on both themes) over the
              surface, not a hard `bg-white` that sat as a white patch on the dark theme. */}
          {question.options.map((option) => (
            <Chip
              key={option}
              as="button"
              tone="accent"
              size="sm"
              disabled={busy}
              onClick={() => onAnswer(option)}
              className="border border-brand-300 bg-surface-1 text-accent-text hover:bg-brand-50 hover:text-accent-text-hover"
            >
              {option}
            </Chip>
          ))}
        </div>
      )}
    </div>
  )
}

function ProposalCard({
  proposal, busy, onResolve,
}: {
  proposal: ChatProposal
  busy: boolean
  onResolve: (outcome: 'accepted' | 'edited' | 'discarded', finalValue: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(proposal.value)

  if (proposal.outcome) {
    const label = proposal.outcome === 'discarded' ? 'Discarded' : proposal.outcome === 'edited' ? 'Accepted (edited)' : 'Accepted'
    return (
      <Card padding="sm" className={`mt-2 rounded-lg ${proposal.outcome === 'discarded' ? 'opacity-60' : ''}`}>
        <p className={EYEBROW_CLASS}>
          {proposal.document} — {proposal.section} — {proposal.field}
        </p>
        <p className="mt-1 text-xs font-medium text-ink-2">{label}</p>
      </Card>
    )
  }

  return (
    <div className="mt-2">
      <AiProposalCard
        label={`Proposed write — ${proposal.document} — ${proposal.section} — ${proposal.field}`}
        busy={busy}
        onAccept={() => onResolve(editing && value.trim() !== proposal.value.trim() ? 'edited' : 'accepted', value)}
        onDiscard={() => onResolve('discarded', '')}
        middleActions={!editing ? (
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => setEditing(true)}>Edit</Button>
        ) : (
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => { setEditing(false); setValue(proposal.value) }}>
            Cancel edit
          </Button>
        )}
      >
        {editing ? (
          <Textarea
            mono
            size="sm"
            aria-label="Proposed text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={Math.min(10, Math.max(3, value.split('\n').length + 1))}
            className="mt-1"
          />
        ) : (
          <pre className="mt-1 whitespace-pre-wrap font-sans text-xs text-ink-1">{proposal.value}</pre>
        )}
      </AiProposalCard>
    </div>
  )
}
