import { useState } from 'react'
import { inTheRoom, isEmailedBefore, isInterview } from '../../shared/briefLimits'
import type { BriefContradiction, BriefDocument, BriefQuestion } from '../../shared/types'
import { Card, Chip } from '../ui'
import { PanelSecondaryButton } from './activityPanelBits'
import { Reason, Section } from './briefBits'

interface PickProps<T> {
  items: T[]
  ticked: string[]
  limit: number
  onToggle: (id: string) => void
}

const CHECKBOX_ROW = 'flex items-start gap-2'

export function ContradictionsSection({ items, ticked, limit, onToggle }: PickProps<BriefContradiction>) {
  const count = items.filter((c) => ticked.includes(c.id)).length
  const full = count >= limit
  return (
    <Section title="Contradictions" counter={`${count} of ${limit}`} counterId="brief-contradictions-counter">
      {full && <Reason>{`The page holds ${limit} contradictions.`}</Reason>}
      <ul className="space-y-2">
        {items.map((item) => (
          <ContradictionRow
            key={item.id}
            item={item}
            checked={ticked.includes(item.id)}
            disabled={full && !ticked.includes(item.id)}
            onToggle={() => onToggle(item.id)}
          />
        ))}
      </ul>
    </Section>
  )
}

function ContradictionRow({
  item, checked, disabled, onToggle,
}: { item: BriefContradiction; checked: boolean; disabled: boolean; onToggle: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <Card as="li" padding="sm" data-testid="brief-contradiction" data-id={item.id} className="rounded-lg">
      <div className={CHECKBOX_ROW}>
        <input type="checkbox" aria-label={`Include ${item.id}`} checked={checked} disabled={disabled} onChange={onToggle} className="mt-0.5" />
        <div className="min-w-0 flex-1 space-y-1 text-xs text-ink-2">
          <p>
            <span className="font-medium text-ink-1">{item.id}</span> {item.title}{' '}
            <Chip tone="mono" className="uppercase">{item.severity}</Chip>
          </p>
          <p>{item.question}</p>
          <PanelSecondaryButton
            aria-expanded={open}
            aria-label={`${open ? 'Hide' : 'Show'} sources for ${item.id}`}
            onClick={() => setOpen(!open)}
          >
            {open ? 'Hide sources' : 'Show sources'}
          </PanelSecondaryButton>
          {open && <Sources item={item} />}
        </div>
      </div>
    </Card>
  )
}

function Sources({ item }: { item: BriefContradiction }) {
  return (
    <ul className="space-y-1">
      {item.sources.map((s) => (
        <li key={s.side} className="border-l-2 border-line-2 pl-2">
          <span className="font-medium text-ink-1">{s.document}</span>
          <q className="ml-1 italic">{s.quote}</q>
        </li>
      ))}
    </ul>
  )
}

/** The workshop agenda blocks in the order the candidates first mention them. */
function byBlock(questions: BriefQuestion[]): Array<[string, BriefQuestion[]]> {
  return questions.reduce<Array<[string, BriefQuestion[]]>>((groups, q) => {
    const at = groups.findIndex(([block]) => block === q.block)
    if (at === -1) return [...groups, [q.block, [q]]]
    return groups.map((g, i) => (i === at ? [g[0], [...g[1], q]] : g))
  }, [])
}

export function QuestionsSection({ items, ticked, limit, onToggle }: PickProps<BriefQuestion>) {
  const inRoom = items.filter((q) => !isEmailedBefore(q.route))
  const emailed = items.filter((q) => isEmailedBefore(q.route))
  const count = inRoom.filter((q) => inTheRoom(q.route) && ticked.includes(q.id)).length
  const full = count >= limit
  return (
    <Section title="Questions" counter={`${count} of ${limit}`} counterId="brief-questions-counter">
      {full && <Reason>{`The page holds ${limit} questions.`}</Reason>}
      {byBlock(inRoom).map(([block, questions]) => (
        <div key={block} data-testid="brief-question-block" data-block={block} className="space-y-1">
          <h5 className="text-xs font-medium text-ink-2">{block}</h5>
          <ul className="space-y-1">
            {questions.map((q) => (
              <QuestionRow key={q.id} q={q} checked={ticked.includes(q.id)} full={full} onToggle={() => onToggle(q.id)} />
            ))}
          </ul>
        </div>
      ))}
      {emailed.length > 0 && <EmailedQuestions items={emailed} />}
    </Section>
  )
}

function QuestionRow({ q, checked, full, onToggle }: { q: BriefQuestion; checked: boolean; full: boolean; onToggle: () => void }) {
  const unusable = !inTheRoom(q.route)
  const interview = isInterview(q.route)
  return (
    <li className={CHECKBOX_ROW}>
      <input
        type="checkbox"
        aria-label={`Include ${q.id}`}
        checked={!unusable && checked}
        disabled={unusable || (full && !checked)}
        onChange={onToggle}
        className="mt-0.5"
      />
      <span className="text-xs text-ink-2">
        <span className="font-medium text-ink-1">{q.id}</span> {q.question}
        {unusable && <span className="block text-ink-3">{interview ? 'Neither in the room nor emailed.' : 'Its route is not one Shepherd recognises.'}</span>}
      </span>
    </li>
  )
}

function EmailedQuestions({ items }: { items: BriefQuestion[] }) {
  return (
    <div data-testid="brief-emailed-questions" className="space-y-1">
      <h5 className="text-xs font-medium text-ink-2">Email these before the workshop</h5>
      <Reason>These are not placed on the page; the brief reports them as emailed instead.</Reason>
      <ul className="space-y-1">
        {items.map((q) => (
          <li key={q.id} className="text-xs text-ink-2">
            <span className="font-medium text-ink-1">{q.id}</span> {q.question}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function DocumentsSection({
  items, ticked, range, onToggle,
}: { items: BriefDocument[]; ticked: string[]; range: [number, number]; onToggle: (id: string) => void }) {
  const count = items.filter((d) => ticked.includes(d.id)).length
  const full = count >= range[1]
  return (
    <Section title="Load-bearing documents" counter={`${count} of ${range[0]} to ${range[1]}`} counterId="brief-documents-counter">
      {full && <Reason>{`The page names at most ${range[1]} load-bearing documents.`}</Reason>}
      <ul className="space-y-1">
        {items.map((d) => (
          <li key={d.id} className={CHECKBOX_ROW}>
            <input
              type="checkbox"
              aria-label={`Load-bearing ${d.id}`}
              checked={ticked.includes(d.id)}
              disabled={full && !ticked.includes(d.id)}
              onChange={() => onToggle(d.id)}
              className="mt-0.5"
            />
            <span className="text-xs text-ink-2">
              <span className="font-medium text-ink-1">{d.id}</span> {d.filename}
              {d.topics && <span className="text-ink-3"> ({d.topics})</span>}
            </span>
          </li>
        ))}
      </ul>
    </Section>
  )
}
