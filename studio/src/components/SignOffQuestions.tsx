import type { HintStatus, SignOffQuestion } from '../../shared/types'
import { Eyebrow, Notice } from '../ui'
import { useCountUp } from '../motion/useCountUp'

// C1: "Not yet" is the status-warn ink token (legible on both themes), not a raw amber.
const HINT: Record<HintStatus, { label: string; tone: string }> = {
  looks_met: { label: 'Looks done', tone: 'text-[var(--color-command-ok)]' },
  not_yet: { label: 'Not yet', tone: 'text-status-warn-ink' },
  judgement: { label: 'Needs your judgement', tone: 'text-ink-3' },
}

function formatWhen(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

/** "N of M confirmed". The count moves through `useCountUp` (§4.2 #11) — only between two real
 * values, keyed on THIS stage's questions so a different stage's count is never the "previous"
 * value a tween starts from. The rendered text is identical to the plain string. */
function ConfirmedCount({ confirmed, total, memoryKey }: { confirmed: number; total: number; memoryKey: string }) {
  const count = useCountUp(`sign-off-confirmed:${memoryKey}`, confirmed)
  return (
    <span className="text-xs text-ink-3">
      <span ref={count.ref}>{count.text}</span>{` of ${total} confirmed`}
    </span>
  )
}

/** The questions for whoever signs a stage off: a box for each, and beside it what Studio could
 * see. The box is ticked only by a named person — a hint that says "Looks done" leaves it empty,
 * because the hint is a pre-check and the person is the one who signs. */
export function SignOffQuestions({
  questions,
  actor,
  busyId,
  error,
  onToggle,
}: {
  questions: SignOffQuestion[]
  /** Who a confirmation is recorded under. Empty means there is no one to record it for. */
  actor: string
  busyId: string | null
  error: string | null
  onToggle: (question: SignOffQuestion, confirmed: boolean) => void
}) {
  const confirmed = questions.filter((q) => q.confirmation).length
  const tooOld = questions.some((q) => !q.id)

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <Eyebrow as="h3">Questions for whoever signs this off</Eyebrow>
        <ConfirmedCount confirmed={confirmed} total={questions.length} memoryKey={questions.map((q) => q.id || q.text).join('|')} />
      </div>
      <ul className="divide-y divide-line-1 overflow-hidden rounded-xl border border-line-1 bg-surface-1">
        {questions.map((q) => {
          const hint = HINT[q.hint.status]
          const canTick = Boolean(actor.trim()) && Boolean(q.id) && busyId !== q.id
          return (
            <li key={q.id || q.text} data-reveal="" className="flex items-start justify-between gap-6 px-4 py-3">
              <label className="flex min-w-0 flex-1 items-start gap-3 text-sm text-ink-1">
                {/* A native checkbox, not a kit control: the aria-label IS the question (pinned),
                    and the sign-off questions test reads `type="checkbox"` then `disabled` in
                    this attribute order. */}
                <input
                  type="checkbox"
                  aria-label={q.text}
                  checked={Boolean(q.confirmation)}
                  disabled={!canTick}
                  onChange={(e) => onToggle(q, e.target.checked)}
                  className="mt-0.5 h-4 w-4 shrink-0 rounded border-line-2"
                />
                <span className="min-w-0">
                  {q.text}
                  {q.confirmation && (
                    <span className="mt-0.5 block text-xs text-ink-3">
                      {`Confirmed by ${q.confirmation.actor} · ${formatWhen(q.confirmation.ts)}`}
                    </span>
                  )}
                </span>
              </label>
              <p className="w-2/5 shrink-0 text-xs leading-relaxed">
                <span className={`font-medium ${hint.tone}`}>{hint.label}</span>
                {q.hint.status !== 'judgement' && <span className="text-ink-3">{` — ${q.hint.detail}`}</span>}
              </p>
            </li>
          )
        })}
      </ul>
      <p className="mt-2 text-xs text-ink-3">
        The notes on the right are pre-checks: they show what Shepherd could see, and you still confirm.
      </p>
      {!actor.trim() && (
        <Notice tone="warn" className="mt-2">Shepherd records who confirmed, and you need to sign in before you can confirm.</Notice>
      )}
      {tooOld && (
        <Notice tone="warn" className="mt-2">This plugin is too old to keep confirmations. To tick these, update the plugin.</Notice>
      )}
      {error && <Notice tone="error" className="mt-2">{error}</Notice>}
    </div>
  )
}
