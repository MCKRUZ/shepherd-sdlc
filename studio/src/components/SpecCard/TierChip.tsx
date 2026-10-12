// The risk tier on the spec card (togo-command-center.md §3.3, §5): the chip, Confirm
// (`confirmTier`; disabled with the capability reason without `confirm-tier`), and the EXISTING
// raise / lower controls with their pinned wording — a `Segmented` of LOW / MEDIUM / HIGH (the
// chosen tier carries `bg-slate-900`, `board.spec:215-229` — the inverse fill is that pin, so it
// stays; the control is marked `data-write`, since a click IS `spec_transition.py risk`), the
// authoriser field "Who authorised
// lowering this tier? Written into the spec." appearing ONLY after the plugin's own
// `lowering_needs_authorisation` refusal, the refusal shown in its words. The fixed sentence is
// `reasons.TIER_RULE`; `**Why this tier:**` notes are read from the document by the host.
import { useState } from 'react'
import type { ConfirmTierResult, SpecTransitionResult } from '../../../shared/types'
import { newerPlugin, TIER_RULE, WAITING_FOR_PLUGIN_ANSWER } from '../../../shared/reasons'
import { Button, Chip, Eyebrow, Field, Input, Notice, Segmented } from '../../ui'
import { riskTone } from '../planning/planningModel'

type Tier = 'LOW' | 'MEDIUM' | 'HIGH'
const TIERS: Tier[] = ['LOW', 'MEDIUM', 'HIGH']
export const AUTHORISER_LABEL = 'Who authorised lowering this tier? Written into the spec.'
export const CONFIRM_TIER = 'Confirm tier'

export interface TierChipProps {
  projectPath: string
  specPath: string
  risk: string
  /** `**Why this tier:**` notes from the document, verbatim. */
  whyNotes: string[]
  canConfirm: boolean
  /** Why writes are disabled (no actor); undefined = enabled. */
  writeReason?: string
  onChanged: () => void
}

export function TierChip({ projectPath, specPath, risk, whyNotes, canConfirm, writeReason, onChanged }: TierChipProps) {
  const [busy, setBusy] = useState(false)
  const [refusal, setRefusal] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [authorisedBy, setAuthorisedBy] = useState<string | null>(null)
  const current = TIERS.includes(risk as Tier) ? (risk as Tier) : ('' as Tier)

  const act = async (run: () => Promise<SpecTransitionResult>) => {
    setBusy(true); setRefusal(null); setMessage(null)
    const result = await run()
    setBusy(false)
    if (!result.ok) {
      setRefusal(result.refusal?.message ?? 'That change was refused.')
      if (result.refusal?.kind === 'lowering_needs_authorisation') setAuthorisedBy('')
      return
    }
    setAuthorisedBy(null)
    setMessage(result.message ?? null)
    onChanged()
  }
  const confirm = () => act(async () => {
    const r: ConfirmTierResult = await window.studio.confirmTier(projectPath, specPath)
    return { ...r, message: r.message ?? (r.changed === false ? 'already confirmed' : r.confirmedBy ? `confirmed by ${r.confirmedBy}` : 'confirmed') }
  })
  const busyReason = busy ? WAITING_FOR_PLUGIN_ANSWER : undefined

  return (
    <section aria-label="Risk tier" data-testid="tier-chip" className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Eyebrow as="h3">Risk tier</Eyebrow>
        <Chip tone={riskTone(risk)} casing="identifier" dot>{risk || 'no tier'}</Chip>
        <Button size="sm" data-write="" disabled={!canConfirm || Boolean(writeReason) || busy} disabledReason={!canConfirm ? newerPlugin('confirm-tier') : writeReason ?? busyReason} onClick={confirm}>
          {CONFIRM_TIER}
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Segmented<Tier>
          label="Risk tier"
          data-write=""
          tone="inverse"
          value={current}
          // The plugin's own rule, not a Shepherd one: raising a tier is free, and lowering asks for
          // the name through the refusal flow above (`authorisedBy`). A missing signed-in person
          // gates the verbs that carry --by (Confirm tier), never this control — the CI runner has
          // no identity and board.spec pins that a raise still takes effect there.
          disabled={busy}
          disabledReason={busyReason}
          options={TIERS.map((tier) => ({ value: tier, label: tier }))}
          onChange={(tier) => act(() => window.studio.setSpecRisk(projectPath, specPath, tier, authorisedBy?.trim() || undefined))}
        />
        <span className="text-xs text-ink-3">{TIER_RULE}</span>
      </div>
      {authorisedBy !== null && (
        <Field label={AUTHORISER_LABEL}>
          <Input value={authorisedBy} onChange={(e) => setAuthorisedBy(e.target.value)} className="border-status-warn-line" />
        </Field>
      )}
      {refusal && <Notice tone="warn"><p className="whitespace-pre-wrap">{refusal}</p></Notice>}
      {message && <p className="text-xs text-ink-2" data-testid="tier-message">{message}</p>}
      {whyNotes.length > 0 && (
        <div className="text-xs text-ink-2" data-testid="why-this-tier">
          <Eyebrow>Why this tier</Eyebrow>
          {whyNotes.map((n, i) => <p key={i} className="mt-0.5 whitespace-pre-wrap">{n}</p>)}
        </div>
      )}
    </section>
  )
}
