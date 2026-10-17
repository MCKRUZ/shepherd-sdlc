// Every sentence Studio shows for a control it disables itself (togo-command-center.md §2.7, §8
// honesty check 1). A disabled control's `aria-describedby` text is EITHER one of these OR a
// verbatim plugin message — `test/reasonsSweep.test.tsx` enforces exactly that, so this file is
// the complete list of Studio's own reasons. Nothing here is a judgement about the work: each
// line says which verb is missing, which capability a newer plugin brings, or what the plugin
// itself has no field for. "No data" wording lives here too so a zero is never typed by hand.

/** A plugin that lacks a capability disables the control honestly, naming the capability. */
export function newerPlugin(capability: string): string {
  return `arrives with a newer plugin: lacks ${capability}`
}

/** The ten capabilities the command center reads (§2.6), the three it already read, and the six of the
 * Azure Boards mirror (ado-boards-mirror.md §12: `ado_sync.py`'s status read, apply, reconcile, show,
 * discussion pull and comment). A missing one disables its control with `newerPlugin(cap)`;
 * `sprint-write` is what lets an older plugin disable the omnibar verbs. */
export const CAPABILITIES = {
  sprintStatus: 'sprint-status',
  sprintList: 'sprint-list',
  sprintLog: 'sprint-log',
  sprintCarry: 'sprint-carry',
  sprintEdit: 'sprint-edit',
  sprintWrite: 'sprint-write',
  confirmTier: 'confirm-tier',
  assignRoles: 'assign-roles',
  handoffCheck: 'handoff-check',
  findingsJson: 'findings-json',
  readinessAll: 'readiness-all',
  decisionOpen: 'decision-open',
  decisionDecide: 'decision-decide',
  adoStatus: 'ado-status-json',
  adoApply: 'ado-apply',
  adoReconcile: 'ado-reconcile',
  adoShow: 'ado-show',
  adoDiscussion: 'ado-pull-discussion',
  adoComment: 'ado-comment',
} as const

export type CapabilityName = (typeof CAPABILITIES)[keyof typeof CAPABILITIES]

// --- the actor ---------------------------------------------------------------------------------

export const NO_ACTOR = 'Sign in or type your name — the plugin records who is accountable'
export const SIGN_IN_TO_SEE = 'sign in or type your name to see what needs you'
export const NO_ROSTER = 'no roster — add people in Settings'
/** `v` on a card whose `developer` is me: a NOTE, never a disabled button (§5). */
export const OWN_BUILD_VERDICT = 'you built this — the verdict is someone else\'s'
/** The roster has no discipline role, so a data verdict is only "by <actor>". */
export const DATA_VERDICT_NO_DISCIPLINE = 'the roster has no discipline role — this records a data verdict by you, not as a data owner'

// --- present, disabled, with the reason — even on the newest plugin (§2.7) ------------------

export const SECURITY_SIGNER = 'No frontmatter field for a security signer — the HIGH sign-off is wording inside `## Checking Plan`; arrives with a newer plugin'
export const STANDUP_NOTES = 'arrives with a newer plugin: no read-only standup agent is registered in `agentRun`'
export const PROMOTE_FINDING = 'Promotion arrives with Phase C of the context-repair loop'
export const SPRINT_FIELDS_FIXED = 'set at `sprint new`; editing arrives with a newer plugin'
export const LOOP_EVENTS_TOTALS_ONLY = 'loop events: totals only — `scorecard.py` has no per-event view'
export const VAGUE_LINE_REWRITE = 'arrives with a newer plugin: `draftField` does not accept a spec path'
export const REASONED_SLATE = 'a reasoned proposal is a named agent run; this build shows the plugin\'s deterministic proposal'
export const TIER_CONFIRMATION_ARRIVES = 'tier confirmation arrives with a newer plugin'
export const SKIPPED_TIER_CONFIRMATION = 'skipped: tier confirmation arrives with a newer plugin'
export const STREAM_ARRIVES = `the stream arrives with a newer plugin: lacks ${CAPABILITIES.sprintLog}`
export const TWO_LEDGER_LINES = 'two ledger lines, not atomic'

// --- "no data" is two words, never a zero (§2.3, visual §1) ---------------------------------

export const NO_DATA = 'no data'
export const CAP_NOT_SET = 'cap not set'
export const DATES_UNREADABLE = 'dates unreadable — no bar'
export const NOTHING_NEEDS_YOU = 'nothing needs you'
export const NO_PR_YET = 'no PR yet'
export const NO_CHANNEL_BOUND = 'no channel bound'
export const GATED_PATH_NOT_DECLARED = 'gated path: not declared'
export const ORDER_NOT_GIVEN = 'order not given'
export const ORDER_ARRIVES_ON_COMMIT = 'order arrives when the slate is committed'
export const UNDATED = 'undated'
export const DEFERRED_REASON_RECORDED = 'deferred · reason recorded in the spec'
export const NO_NAME_RECORDED = 'no name recorded'
export const WINDOW_IS_A_LABEL = 'window is a label only'
export const NEXT_UP = 'next up · deps merged · pull →'
export const ONE_SPEC_ONE_BRANCH = 'one spec · one branch · one PR'
export const TIER_RULE = 'Raising a tier adds rungs for free; lowering is recorded against whoever decided'

// The Azure Boards mirror's four no-data states (ado-boards-mirror.md §12 item 1), each digit-free: a board
// that was never configured, discovered, pulled or reachable says so in words, never as a 0.
export const WORK_ITEMS_NOT_SET_UP = 'Work items are not set up for this project'
export const SCHEMA_NOT_DISCOVERED = 'Schema not discovered yet'
export const NOT_PULLED_YET = 'Not pulled yet'
export const BOARDS_UNREACHABLE = 'Could not reach Azure Boards'

/** The hand-off dialog's Confirm while `--to` names nobody yet (the `h` key on a card). */
export const PICK_RECIPIENT = 'pick a person on the roster — --to needs a roster handle'

/** A typed recipient the roster does not know: a visible gap, never a guess (§3.6). */
export function notOnRoster(name: string): string {
  return `“${name}” is not on the roster — pick the person`
}

/** "create S09 first →" — the Carry-to picker when the target sprint does not exist yet. */
export function createSprintFirst(sprintId: string): string {
  return `create ${sprintId} first →`
}

// --- the result headings, by exit code (§2.4) -----------------------------------------------

export const EXIT_HEADING = { 0: 'Done', 1: 'Not done', 2: 'Refused by the plugin' } as const

export function exitHeading(exitCode: number | null): string {
  if (exitCode === 0) return EXIT_HEADING[0]
  if (exitCode === 2) return EXIT_HEADING[2]
  return EXIT_HEADING[1]
}

// --- the forbidden words (§5, §8 honesty check 2) ------------------------------------------

/** Activity metrics never appear on a screen. The sweep greps the DOM for these; this regex is the
 * one sanctioned place the words are spelled in `studio/src`. */
export const FORBIDDEN_METRIC_WORDS = /velocity|story points|PR count|lines of code/i

// --- the sweep's list ------------------------------------------------------------------------

/** Every fixed sentence above. `isReason(text)` is what `reasonsSweep.test.tsx` asks of each
 * disabled control's description when it is not a plugin message from the fixture. */
/** A write control while its own verb is still running: the plugin has not answered yet. */
export const WAITING_FOR_PLUGIN_ANSWER = 'Waiting for the plugin to answer.'
/** `HandoffDialog`: the two gaps the form itself can see before `handoff.py` is asked. */
export const NAME_DEVELOPER_FIRST = 'Name the developer first.'
export const REASON_REQUIRED_PAST_LIMIT = 'A reason is required to go past a limit.'

export const REASON_SENTENCES: readonly string[] = [
  WAITING_FOR_PLUGIN_ANSWER, NAME_DEVELOPER_FIRST, REASON_REQUIRED_PAST_LIMIT,
  NO_ACTOR, SIGN_IN_TO_SEE, NO_ROSTER, OWN_BUILD_VERDICT, DATA_VERDICT_NO_DISCIPLINE,
  SECURITY_SIGNER, STANDUP_NOTES, PROMOTE_FINDING, SPRINT_FIELDS_FIXED, LOOP_EVENTS_TOTALS_ONLY,
  VAGUE_LINE_REWRITE, REASONED_SLATE, TIER_CONFIRMATION_ARRIVES, SKIPPED_TIER_CONFIRMATION, STREAM_ARRIVES,
  TWO_LEDGER_LINES, NO_DATA, CAP_NOT_SET, DATES_UNREADABLE, NOTHING_NEEDS_YOU, NO_PR_YET, NO_CHANNEL_BOUND,
  GATED_PATH_NOT_DECLARED, ORDER_NOT_GIVEN, ORDER_ARRIVES_ON_COMMIT, UNDATED, DEFERRED_REASON_RECORDED,
  NO_NAME_RECORDED, WINDOW_IS_A_LABEL, NEXT_UP, ONE_SPEC_ONE_BRANCH, TIER_RULE, PICK_RECIPIENT,
  WORK_ITEMS_NOT_SET_UP, SCHEMA_NOT_DISCOVERED, NOT_PULLED_YET, BOARDS_UNREACHABLE,
]

/** True for a fixed sentence, a `newerPlugin(cap)` line or a `createSprintFirst(id)` line. */
export function isReason(text: string | null | undefined): boolean {
  if (!text) return false
  const t = text.trim()
  return REASON_SENTENCES.includes(t) || /^(sprint home )?arrives with a newer plugin: lacks [a-z-]+$/.test(t) || /^create S\d{2,} first →$/.test(t) || /^“.+” is not on the roster — pick the person$/.test(t)
}
