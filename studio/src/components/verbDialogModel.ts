// The words and shapes behind `VerbDialog` (togo-command-center.md §3.6), kept pure so a test
// reads them without a DOM: the title per intent, the exact line the plugin will be asked to run,
// the preconditions it will check (descriptive — the plugin remains the judge), and one
// `ResultView` per outcome, headed by the exit code alone ("Done" / "Not done" / "Refused by the
// plugin") with stdout and stderr verbatim. Nothing here spawns; nothing here decides.
import type { DecideDecisionResult, OpenDecisionResult, SpecTransitionResult, SprintVerbResult } from '../../shared/types'
import { EXIT_HEADING, exitHeading } from '../../shared/reasons'
import { describeArgv, SCRIPT } from '../../shared/sprintVerbArgv'
import { ACTOR_PLACEHOLDER, previewSprintVerb, type Intent } from '../palette/intents'

export type ResultTone = 'ok' | 'warn' | 'error'

export interface ResultView {
  heading: string
  tone: ResultTone
  /** The spawn that ran, as the console narrates it. */
  ran: string
  stdout: string
  stderr: string
}

export function dialogTitle(intent: Intent): string {
  switch (intent.kind) {
    case 'sprint': {
      const r = intent.request
      switch (r.verb) {
        case 'verdict': return `Record the ${r.lane} verdict on ${r.spec}`
        case 'handoff': return `Hand off ${r.spec}`
        case 'ack': return `Acknowledge the hand-off of ${r.spec}`
        case 'slate': return `Add ${r.specs.join(', ')} to ${r.sprint}`
        case 'unslate': return `Take ${r.spec} off the slate`
        case 'carry': return `Carry ${r.spec} to ${r.to}`
        case 'ready': return `Mark ${r.sprint} ready`
        case 'close': return `Close ${r.sprint}`
        case 'new': return `Create ${r.sprint}`
        case 'edit': return `Edit the goal of ${r.sprint}`
      }
      return 'Run a sprint verb'
    }
    case 'pull': return `Pull ${intent.spec}`
    case 'defer': return `Defer ${intent.spec}`
    case 'decide': return `Decide ${intent.id}`
    case 'decision': return 'Open a decision'
    case 'confirm-tier': return `Confirm the risk tier of ${intent.spec}`
    case 'close': return `Close ${intent.sprint}`
    case 'new-sprint': return 'New sprint'
  }
}

/** The line the dialog previews. For a sprint verb it is the golden argv; for the other scripts
 * the fixed spawn the inventory names. `--by` shows the actor's label; main fills the real one. */
export function previewLine(intent: Intent, actor: string | null): string {
  const by = actor ?? ACTOR_PLACEHOLDER
  switch (intent.kind) {
    case 'sprint': return previewSprintVerb(intent.request, actor)
    case 'pull':
      return intent.slated
        ? `Run: handoff.py --spec ${intent.path} --developer <picked in the hand-off>`
        : `Run: ${SCRIPT} slate --sprint ${intent.sprint ?? '<sprint>'} --spec ${intent.spec} --by ${by}`
    case 'defer': return `Run: spec_transition.py --spec ${intent.path} defer --reason ${JSON.stringify(intent.reason)}`
    case 'decide': return `Run: track_decisions.py decide --id ${intent.id} --by ${by} --resolution ${JSON.stringify(intent.resolution)} --json`
    case 'decision': return `Run: track_decisions.py open --decision ${JSON.stringify(intent.text)} --owner ${by} --json`
    case 'confirm-tier': return `Run: spec_transition.py --spec ${intent.path} --json confirm-tier --by ${by}`
    case 'close': return 'Opens Build › Closing — nothing runs until the close screen confirms'
    case 'new-sprint': return `Run: ${SCRIPT} new --sprint <id> --goal <goal> --start <date> --target <n> --by ${by}`
  }
}

/** What the plugin checks before it writes — its rules, in one line each, as the §5 table names
 * them. Never enforced here: the dialog shows them so a refusal is not a surprise. */
export function preconditions(intent: Intent): string[] {
  const human = 'a named human as --by (an AI-looking name is refused, exit 2)'
  switch (intent.kind) {
    case 'sprint':
      switch (intent.request.verb) {
        case 'verdict': return [human, 'the spec is slated in the sprint', 'n-a is a data-lane verdict only and needs a reason']
        case 'handoff': return [human, '--to names a person', 'the spec is slated in the sprint']
        case 'ack': return [human, 'a hand-off is open to you']
        case 'slate': return [human, 'the sprint is not closed', 'the spec is not already slated', 'target and mix — an override needs a reason']
        case 'unslate': return [human, 'the spec is slated', 'a reason is given']
        case 'carry': return [human, 'the spec is in a sprint and not merged', '--to exists, is open and is not the same sprint']
        case 'ready': return [human, 'every slated spec is DoR READY, status ready, with both reviews in — the gaps are listed otherwise']
        case 'close': return [human, 'every open spec is carried or dropped with a reason']
        case 'new': return [human, 'the sprint id is new', 'start, length and target are given']
        case 'edit': return [human, 'the sprint is not closed']
      }
      return [human]
    case 'pull': return intent.slated ? ['the spec passes the DoR', 'the developer is on the roster and is not the checker', 'the team is under its WIP limit'] : [human, 'the spec is not already slated']
    case 'defer': return ['a real reason — empty or a placeholder token is refused']
    case 'decide': return ['the decision id exists and is open']
    case 'decision': return ['an owner (you) and a 2-business-day clock are recorded']
    case 'confirm-tier': return [human, 'the spec has a risk tier']
    case 'close': return ['decided on the close screen, spec by spec']
    case 'new-sprint': return [human, 'the sprint id is new']
  }
}

const TONE: Record<number, ResultTone> = { 0: 'ok', 1: 'warn', 2: 'error' }

export function sprintResultView(result: SprintVerbResult): ResultView {
  const code = result.exitCode ?? 1
  return { heading: exitHeading(code), tone: TONE[code] ?? 'warn', ran: describeArgv(result.argv), stdout: result.stdout, stderr: result.stderr }
}

/** `spec_transition.py` never exits 2: a refusal is "Not done" with the plugin's own message. */
export function transitionResultView(ran: string, result: SpecTransitionResult): ResultView {
  if (result.ok) return { heading: EXIT_HEADING[0], tone: 'ok', ran, stdout: [result.message, result.note].filter(Boolean).join('\n'), stderr: '' }
  return { heading: EXIT_HEADING[1], tone: 'warn', ran, stdout: result.message ?? '', stderr: result.refusal?.message ?? '' }
}

export function decisionResultView(ran: string, result: OpenDecisionResult | DecideDecisionResult): ResultView {
  if (result.ok) {
    const lines = 'opened' in result ? [`${result.id} opened ${result.opened} · due ${result.due} · owner ${result.owner}`] : [`${result.id} ${result.status} · ${result.decided} · by ${result.by}`]
    return { heading: EXIT_HEADING[0], tone: 'ok', ran, stdout: lines.join('\n'), stderr: '' }
  }
  return { heading: EXIT_HEADING[1], tone: 'warn', ran, stdout: '', stderr: result.stderr }
}

/** The bridge method a verb needs is absent (an older Studio build): said plainly, as "Not done". */
export function bridgeMissingView(ran: string, method: string): ResultView {
  return { heading: EXIT_HEADING[1], tone: 'warn', ran, stdout: '', stderr: `window.studio.${method} is not in this build of Shepherd — nothing was run` }
}
