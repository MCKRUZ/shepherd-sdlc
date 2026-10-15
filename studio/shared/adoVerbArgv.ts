// The closed argv table for the Azure Boards mirror (build kit §3 and §5 B4-P0; ado-boards-mirror.md §12 items 2,
// 7 and 8): the ONLY way a Studio request reaches `ado_sync.py`. Pure and golden-tested like `sprintVerbArgv.ts`
// (test/adoVerbArgv.test.ts) — main validates the request here, resolves the actor itself, and spawns exactly the
// list `buildAdoVerbArgv` returned (main adds the `--repo`/`--state` source after the verb, as `sprintWrites.ts`
// does); the renderer only ever hands over an `AdoVerbRequest`, a closed union. `SprintVerb` is never widened.
//
// The rules the table holds (house rules 8 and 9):
//   * `--by <actor>` is the LAST two elements of every write (`apply`, `reconcile`, `link`, `comment`) and absent
//     from every read (`pull`, `pullDiscussion`, `show`, `plan`); the value comes from main's actor, never the renderer.
//   * Free text is ONE element in `--flag=<text>` form — `--message=`, `--reason=`, `--owner=` — so a text with a
//     double quote, a newline, `$(`, non-ASCII or a leading `-` reaches argparse as one value and is never read
//     as a flag. A comment's message is sent byte for byte (not trimmed: the preview shows the exact text).
//   * Every argv is a list; nothing here, or in what spawns it, joins a command into a string or uses a shell.
//   * `--json` on every verb: Studio reads the plugin's JSON, never its prose (the composer's `apply --confirm`
//     hash comes from `comment --json`, and is checked against `HASH` here before it is sent).
// Validation is shape only — ids, hashes, the four takes, a required field present — never a judgement; the
// plugin stays the truth on everything else (AI `--by`, posture, identity, the stale hash, a non-A take).
//
// The union is the build kit's interface sheet (§3, the B4-P0 row): exactly these eight requests
// (test/adoVerbArgv.test.ts reads the sheet and holds `ADO_VERBS` to it). Fold B4 pinned seven; Fold B6 widened it by
// exactly one READ verb, `plan` (build kit K28, owner decision 2026-10-15), so the spec card can draw up a plan and
// hand it to the existing apply dialog — and no later Fold widens it without a kit amendment. `plan` carries no
// `--by` (it sends nothing to the board; `apply` is still the one write that does) and its scope is either a sprint
// (`--sprint SNN`) or one item (`--kind K --id ID`), never both and never neither: an unscoped plan of the whole
// repository is not something a click asks for. A verb the sheet does not list is not something Shepherd runs: a
// screen shows the plugin line for it instead, as the Today row's Propose spec does. B5-P4 only narrows `reconcile`
// to an sdlc ref (`SDLC_REF`): the CLI refuses a `#<work item>` there, so the table does too, before a spawn.
import { CAPABILITIES } from './reasons'

export type AdoVerbRequest =
  | { verb: 'apply'; confirm: string } | { verb: 'reconcile'; ref: string; field: string; take: 'ado' | 'sdlc' | 'ack' | 'not-drift'; owner?: string; reason?: string }
  | { verb: 'link'; ref: string; workItem: string } | { verb: 'pull'; id?: string } | { verb: 'pullDiscussion'; id?: string }
  | { verb: 'show'; ref: string } | { verb: 'comment'; ref: string; message: string }
  | { verb: 'plan'; kind?: string; id?: string; sprint?: string }

export type AdoVerb = AdoVerbRequest['verb']
export type AdoTake = Extract<AdoVerbRequest, { verb: 'reconcile' }>['take']
export type AdoArgvResult = { ok: true; argv: string[] } | { ok: false; errors: string[] }

export const SCRIPT = 'ado_sync.py'
/** The plan's handshake hash (`boards_contract.HASH_RE`): what `plan`/`comment --json` printed, echoed to `apply --confirm`. */
export const HASH = /^[0-9a-f]{12}$/
/** A repository ref (`boards_contract.REF_RE`) or a raw `#<work item>`. */
export const REF = /^(sdlc:[a-z]+:[A-Za-z0-9-]+|#\d+)$/
/** An sdlc ref and nothing else (`boards_contract.REF_RE`): what `reconcile` and `link` take — their CLIs refuse a
 * `#<work item>` there, so the table refuses it before a spawn. `REF` above is the wider `show`/`pull`/`comment` form. */
export const SDLC_REF = /^sdlc:[a-z]+:[A-Za-z0-9-]+$/
/** A work item field reference name (`ado_sync_model.REFERENCE_NAME_RE`): System.State, Custom.RiskTier. */
export const FIELD = /^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$/
/** `link --work-item`: `4521` or `#4521` — never `AB#4521`. */
export const WORK_ITEM = /^#?[1-9]\d*$/
/** `plan --sprint`: a sprint id (`sprint_model.SPRINT_ID_RE`), S07. */
export const SPRINT = /^S\d{2,}$/
/** `plan --kind`: a kind word, shape only — `ado_sync.py`'s argparse `choices` (the contract's KINDS) stays the truth. */
export const KIND = /^[a-z]+$/
/** `plan --id`: an item id (0004, FE-03), shape only; one that starts with `-` is refused too, so it is never a flag. */
export const ITEM_ID = /^[A-Za-z0-9-]+$/

/** The flag every write carries last; the value comes from main's actor, never from the renderer. */
export const BY_FLAG = '--by'
export const JSON_FLAG = '--json'

/** Every verb the table knows, in its order (Fold B6 appended `plan` last). */
export const ADO_VERBS: readonly AdoVerb[] = ['apply', 'reconcile', 'link', 'pull', 'pullDiscussion', 'show', 'comment', 'plan']
/** The writes: each carries `--by <actor>` last. The other four are reads and carry no `--by`. */
export const BY_VERBS: readonly AdoVerb[] = ['apply', 'reconcile', 'link', 'comment']
/** `reconcile --take` (the build kit's verb table; `ado_sync_model.RECONCILE_TAKES`, in its order). */
export const TAKES: readonly AdoTake[] = ['ado', 'sdlc', 'ack', 'not-drift']

/** The plugin capability (`scripts/capabilities.py`) each verb needs; a plugin without it disables the control
 * with `newerPlugin(cap)`. The six Boards ids Studio gates on are spelled once, in `reasons.CAPABILITIES`. */
export const ADO_VERB_CAPABILITY: Readonly<Record<AdoVerbRequest['verb'], string>> = {
  apply: CAPABILITIES.adoApply,
  reconcile: CAPABILITIES.adoReconcile,
  link: 'ado-link',
  pull: 'ado-pull',
  pullDiscussion: CAPABILITIES.adoDiscussion,
  show: CAPABILITIES.adoShow,
  comment: CAPABILITIES.adoComment,
  plan: 'ado-plan',
}

function isText(value: unknown): value is string {
  return typeof value === 'string'
}

/** Present and non-blank, after the caller's decision to send it. */
function given(value: unknown): value is string {
  return isText(value) && value.trim() !== ''
}

/** The shape the plugin will accept, checked BEFORE any spawn. Returns the reasons it refuses; never throws. */
export function validateAdoVerbRequest(req: AdoVerbRequest): string[] {
  if (!req || typeof req !== 'object') return ['not a Boards request']
  const errors: string[] = []
  const ref = (value: unknown, label = 'ref') => {
    if (!isText(value) || !REF.test(value)) errors.push(`${label} '${String(value)}' is not an sdlc:<kind>:<id> ref or a #<work item>`)
  }
  const required = (value: unknown, label: string) => {
    if (!given(value)) errors.push(`${label} is required`)
    else if (value.includes('\0')) errors.push(`${label} contains a NUL character`)
  }
  const optional = (value: unknown, label: string) => {
    if (value === undefined || value === null) return
    if (!isText(value)) errors.push(`${label} is not text`)
    else if (value.includes('\0')) errors.push(`${label} contains a NUL character`)
  }
  switch (req.verb) {
    case 'apply':
      if (!isText(req.confirm) || !HASH.test(req.confirm)) errors.push(`confirm '${String(req.confirm)}' is not the plan's 12-hex hash`)
      break
    case 'reconcile':
      if (!isText(req.ref) || !SDLC_REF.test(req.ref)) errors.push(`ref '${String(req.ref)}' is not an sdlc:<kind>:<id> ref`)
      if (!isText(req.field) || !FIELD.test(req.field)) {
        errors.push(`field '${String(req.field)}' is not a work item field reference name (System.State, Custom.RiskTier)`)
      }
      if (!TAKES.includes(req.take)) errors.push(`take '${String(req.take)}' is not ado, sdlc, ack or not-drift`)
      // The plugin's honest counting, mirrored so the dialog shows the field: ACKNOWLEDGED needs an owner,
      // NOT_DRIFT a reason (ado_sync_model.DISPOSITION_NEEDS).
      if (req.take === 'ack') required(req.owner, 'owner')
      else optional(req.owner, 'owner')
      if (req.take === 'not-drift') required(req.reason, 'reason')
      else optional(req.reason, 'reason')
      break
    case 'link':
      if (!isText(req.ref) || !REF.test(req.ref) || !req.ref.startsWith('sdlc:')) errors.push(`ref '${String(req.ref)}' is not an sdlc:<kind>:<id> ref`)
      if (!isText(req.workItem) || !WORK_ITEM.test(req.workItem)) {
        errors.push(`work item '${String(req.workItem)}' is not a work item number (4521 or #4521)`)
      }
      break
    case 'pull':
    case 'pullDiscussion':
      if (req.id !== undefined) ref(req.id, 'id')
      break
    case 'show':
      ref(req.ref)
      break
    case 'comment':
      ref(req.ref)
      required(req.message, 'message')
      break
    case 'plan': {
      // A sprint, or one item named by its kind AND id — never both, never neither. Shape only.
      const item = req.kind !== undefined || req.id !== undefined
      if (req.sprint !== undefined) {
        if (!isText(req.sprint) || !SPRINT.test(req.sprint)) errors.push(`sprint '${String(req.sprint)}' is not a sprint id (S07)`)
        if (item) errors.push('a plan names a sprint, or a kind and an id, never both')
      } else if (!item) {
        errors.push('a plan needs a kind and an id, or a sprint')
      } else {
        if (req.kind === undefined) errors.push('kind is required with an id')
        else if (!isText(req.kind) || !KIND.test(req.kind)) errors.push(`kind '${String(req.kind)}' is not a kind (spec, feature, epic)`)
        if (req.id === undefined) errors.push('id is required with a kind')
        else if (!isText(req.id) || !ITEM_ID.test(req.id) || req.id.startsWith('-')) errors.push(`id '${String(req.id)}' is not an item id (0004, FE-03)`)
      }
      break
    }
    default:
      errors.push(`'${String((req as { verb?: unknown }).verb)}' is not a Boards verb Shepherd runs`)
  }
  return errors
}

/** The argv after the interpreter and the script path: `[verb, …positional and flags, '--json']`, then
 * `'--by', actor` on a write. Deterministic order per verb, so the console line, the dialog's preview and the
 * golden test read the same words. Refuses (never throws) on a bad request, or a write with no actor. */
export function buildAdoVerbArgv(req: AdoVerbRequest, actor: string): { ok: true; argv: string[] } | { ok: false; errors: string[] } {
  const errors = validateAdoVerbRequest(req)
  const writes = errors.length === 0 && BY_VERBS.includes(req.verb)
  if (writes && !given(actor)) errors.push('no actor')
  if (errors.length > 0) return { ok: false, errors }
  const argv: string[] = []
  switch (req.verb) {
    case 'apply': argv.push('apply', '--confirm', req.confirm); break
    case 'reconcile':
      argv.push('reconcile', req.ref, '--field', req.field, '--take', req.take)
      if (given(req.owner)) argv.push(`--owner=${req.owner.trim()}`)
      if (given(req.reason)) argv.push(`--reason=${req.reason.trim()}`)
      break
    case 'link': argv.push('link', req.ref, '--work-item', req.workItem); break
    case 'pull':
      argv.push('pull')
      if (req.id !== undefined) argv.push('--id', req.id)
      break
    case 'pullDiscussion':
      argv.push('pull', '--discussion')
      if (req.id !== undefined) argv.push('--id', req.id)
      break
    case 'show': argv.push('show', req.ref); break
    case 'comment': argv.push('comment', req.ref, `--message=${req.message}`); break
    case 'plan':
      if (req.sprint !== undefined) argv.push('plan', '--sprint', req.sprint)
      else argv.push('plan', '--kind', req.kind!, '--id', req.id!)
      break
  }
  argv.push(JSON_FLAG)
  if (writes) argv.push(BY_FLAG, actor.trim())
  return { ok: true, argv }
}
