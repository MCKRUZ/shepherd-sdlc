// What buildBrief refuses before it starts anything (spec 0032). The renderer is untrusted: it is not the
// authority on which ids exist or how many fit the page, and its text goes to a script. Two stages:
//   parseSelections        shape, id form, duplicates and text rules: needs no candidates, starts no process.
//   checkAgainstCandidates ids that exist, routes, the plugin's limits: needs the candidates just read.
// Each rule is never looser than workshop_brief.py's own (validate_logistics, validate_claims,
// validate_decisions, the one-page limits); a few are stricter on purpose, as the spec says.
// A refusal is one plain line. A value echoed in it is cut short and stripped of control characters.

import { inTheRoom, isEmailedBefore, isInterview, MAX_ATTENDEES, MAX_CLAIMS, MAX_LOGISTICS_TEXT } from '../../shared/briefLimits'
import { isRecord } from './briefRun'
import type { BriefAttendee, BriefClaim, BriefSelections, BriefCandidatesResult } from '../../shared/types'

type Ready = Extract<BriefCandidatesResult, { ok: true }>
type Checked<T> = { ok: true; value: T } | { ok: false; error: string }

const MAX_TEXT = 500
const MAX_LOGISTICS = MAX_LOGISTICS_TEXT
const ID_FORMS = {
  contradictions: { pattern: /^CON-\d+$/, noun: 'a contradiction id' },
  questions: { pattern: /^Q-\d+$/, noun: 'a question id' },
  loadBearing: { pattern: /^DOC-\d+$/, noun: 'a document id' },
} as const
// The plugin cites a claim's document as DOC-NNN with at least three digits.
const CLAIM_DOC = /^DOC-\d{3,}$/
const LINE_BREAK = /[\r\n\v\f\u0085\u2028\u2029]/
const NOT_A_SHAPE = 'The brief selections are not in a shape Shepherd can use.'

const refuse = (error: string): { ok: false; error: string } => ({ ok: false, error })
const show = (value: unknown): string => String(value).replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029]/g, ' ').slice(0, 40)
const hasExactKeys = (obj: Record<string, unknown>, keys: readonly string[]) =>
  Object.keys(obj).length === keys.length && keys.every((k) => Object.prototype.hasOwnProperty.call(obj, k))

/** Why `value` cannot be a field of at most `max` characters on one line, or null. */
function textIssue(value: string, max: number): string | null {
  if (value.trim() === '') return 'is empty'
  if (LINE_BREAK.test(value)) return 'must be on one line'
  return value.length > max ? `is longer than ${max} characters` : null
}

function idList(raw: unknown, kind: keyof typeof ID_FORMS): Checked<string[]> {
  if (!Array.isArray(raw)) return refuse(NOT_A_SHAPE)
  const { pattern, noun } = ID_FORMS[kind]
  const seen = new Set<string>()
  for (const id of raw) {
    if (typeof id !== 'string' || !pattern.test(id)) return refuse(`${show(id)} is not ${noun} Shepherd can use.`)
    if (seen.has(id)) return refuse(`${id} appears more than once.`)
    seen.add(id)
  }
  return { ok: true, value: [...raw] as string[] }
}

function decisionList(raw: unknown): Checked<string[]> {
  if (!Array.isArray(raw)) return refuse(NOT_A_SHAPE)
  for (const [i, d] of raw.entries()) {
    if (typeof d !== 'string') return refuse(`Decision ${i + 1} is not text.`)
    const issue = textIssue(d, MAX_TEXT)
    if (issue) return refuse(`Decision ${i + 1} ${issue}.`)
  }
  return { ok: true, value: [...raw] as string[] }
}

function claimList(raw: unknown): Checked<BriefClaim[]> {
  if (!Array.isArray(raw)) return refuse(NOT_A_SHAPE)
  if (raw.length > MAX_CLAIMS) return refuse(`The page takes up to ${MAX_CLAIMS} claims.`)
  const claims: BriefClaim[] = []
  for (const [i, c] of raw.entries()) {
    if (!isRecord(c) || !hasExactKeys(c, ['text', 'docRef']) || typeof c.text !== 'string' || typeof c.docRef !== 'string') {
      return refuse(NOT_A_SHAPE)
    }
    const issue = textIssue(c.text, MAX_TEXT)
    if (issue) return refuse(`Claim ${i + 1} ${issue}.`)
    if (!CLAIM_DOC.test(c.docRef)) return refuse(`Claim ${i + 1} needs a document from the registry.`)
    claims.push({ text: c.text, docRef: c.docRef })
  }
  return { ok: true, value: claims }
}

const LOGISTICS_FIELDS = [
  ['clientName', 'Client name'], ['dateTimeLocation', 'Date, time and place'], ['duration', 'Duration'], ['facilitator', 'Facilitator'],
] as const

function attendeeList(raw: unknown): Checked<BriefAttendee[]> {
  if (!Array.isArray(raw)) return refuse(NOT_A_SHAPE)
  if (raw.length === 0) return refuse('Add at least one attendee.')
  if (raw.length > MAX_ATTENDEES) return refuse(`The page takes up to ${MAX_ATTENDEES} attendees.`)
  const attendees: BriefAttendee[] = []
  for (const [i, a] of raw.entries()) {
    if (!isRecord(a) || !hasExactKeys(a, ['name', 'role']) || typeof a.name !== 'string' || typeof a.role !== 'string') return refuse(NOT_A_SHAPE)
    for (const field of ['name', 'role'] as const) {
      const issue = textIssue(a[field] as string, MAX_LOGISTICS)
      if (issue) return refuse(`Attendee ${i + 1}: the ${field} ${issue}.`)
    }
    attendees.push({ name: a.name, role: a.role })
  }
  return { ok: true, value: attendees }
}

function logisticsOf(raw: unknown): Checked<BriefSelections['logistics']> {
  const keys = [...LOGISTICS_FIELDS.map(([key]) => key), 'attendees']
  if (!isRecord(raw) || !hasExactKeys(raw, keys)) return refuse(NOT_A_SHAPE)
  const text: Record<string, string> = {}
  for (const [key, label] of LOGISTICS_FIELDS) {
    const value = raw[key]
    if (typeof value !== 'string') return refuse(NOT_A_SHAPE)
    const issue = textIssue(value, MAX_LOGISTICS)
    if (issue) return refuse(`${label} ${issue}.`)
    text[key] = value
  }
  const attendees = attendeeList(raw.attendees)
  if (!attendees.ok) return attendees
  return {
    ok: true,
    value: { clientName: text.clientName, dateTimeLocation: text.dateTimeLocation, duration: text.duration, facilitator: text.facilitator, attendees: attendees.value },
  }
}

const SELECTION_KEYS = ['contradictions', 'questions', 'loadBearing', 'claims', 'decisions', 'logistics', 'replaceExisting'] as const

/** The selections rebuilt from what passed, or the one line to show. Nothing else the renderer sent survives. */
export function parseSelections(raw: unknown): Checked<BriefSelections> {
  if (!isRecord(raw) || !hasExactKeys(raw, SELECTION_KEYS) || typeof raw.replaceExisting !== 'boolean') return refuse(NOT_A_SHAPE)
  const contradictions = idList(raw.contradictions, 'contradictions')
  if (!contradictions.ok) return contradictions
  const questions = idList(raw.questions, 'questions')
  if (!questions.ok) return questions
  const loadBearing = idList(raw.loadBearing, 'loadBearing')
  if (!loadBearing.ok) return loadBearing
  const claims = claimList(raw.claims)
  if (!claims.ok) return claims
  const decisions = decisionList(raw.decisions)
  if (!decisions.ok) return decisions
  const logistics = logisticsOf(raw.logistics)
  if (!logistics.ok) return logistics
  return {
    ok: true,
    value: {
      contradictions: contradictions.value, questions: questions.value, loadBearing: loadBearing.value,
      claims: claims.value, decisions: decisions.value, logistics: logistics.value, replaceExisting: raw.replaceExisting,
    },
  }
}

// --- against the candidates ---------------------------------------------------------------------

/** `workshop` is the plugin's route for the room; an empty route is treated as the room too. */

function unknownIds(s: BriefSelections, c: Ready): string | null {
  const known = [
    { ids: s.contradictions, have: c.contradictions.map((x) => x.id), where: 'the contradiction list' },
    { ids: s.questions, have: c.questions.map((x) => x.id), where: 'the question list' },
    { ids: s.loadBearing, have: c.documents.map((x) => x.id), where: 'the document registry' },
  ]
  for (const { ids, have, where } of known) {
    const missing = ids.find((id) => !have.includes(id))
    if (missing) return `${missing} is not in ${where}.`
  }
  const documents = c.documents.map((d) => d.id)
  const orphan = s.claims.findIndex((claim) => !documents.includes(claim.docRef))
  return orphan === -1 ? null : `Claim ${orphan + 1} cites ${s.claims[orphan].docRef}, which is not in the document registry.`
}

function questionRoutes(s: BriefSelections, c: Ready): string | null {
  for (const id of s.questions) {
    const route = c.questions.find((q) => q.id === id)?.route ?? ''
    if (isEmailedBefore(route)) return `${id} is emailed before the workshop, not placed on the page.`
    if (isInterview(route)) return `${id} is neither in the room nor emailed.`
    if (!inTheRoom(route)) return `${id} has a route Shepherd does not recognise.`
  }
  return null
}

function counts(s: BriefSelections, c: Ready): string | null {
  const { limits } = c
  if (s.contradictions.length > limits.contradictions) return `${s.contradictions.length} contradictions selected; the one-page limit is ${limits.contradictions}.`
  if (s.questions.length > limits.questions) return `${s.questions.length} questions selected for the page; the one-page limit is ${limits.questions}.`
  const [lowDocs, highDocs] = limits.loadBearing
  if (s.loadBearing.length < lowDocs || s.loadBearing.length > highDocs) return `${s.loadBearing.length} load-bearing documents named; the page takes ${lowDocs} to ${highDocs}.`
  const [lowDec, highDec] = limits.decisions
  const total = c.standingDecisions + s.decisions.length
  if (total < lowDec || total > highDec) {
    return `With ${c.standingDecisions} standing decisions already on the page, add ${Math.max(lowDec - c.standingDecisions, 0)} to ${highDec - c.standingDecisions} more to land in the ${lowDec} to ${highDec} the page takes (you have ${s.decisions.length}).`
  }
  return null
}

/** The first reason the selections cannot be built against these candidates, or null. */
export function checkAgainstCandidates(s: BriefSelections, c: Ready): string | null {
  const reason = unknownIds(s, c) ?? questionRoutes(s, c) ?? counts(s, c)
  if (reason) return reason
  return c.existingBrief && !s.replaceExisting ? 'A brief already exists; confirm replacing it first.' : null
}

/** The `--questions` value: every ticked question plus every one routed pre-workshop (so the plugin
 * reports it as emailed instead), in the candidates' own order, each once. Empty when there are none. */
export function questionIdsForBuild(s: BriefSelections, c: Ready): string[] {
  return c.questions.filter((q) => s.questions.includes(q.id) || isEmailedBefore(q.route)).map((q) => q.id)
}
