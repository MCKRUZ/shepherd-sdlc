// The Azure Boards mirror's read side, as Studio sees it (build kit §5 B4-P0; design §12 item 4). Shepherd never
// parses `.sdlc/ado.yaml`, `.sdlc/ado/schema.json` or anything under `.sdlc/ado/local/`: it runs
// `ado_sync.py status --json` and reads the one JSON document that verb prints. `AdoSyncView` is that document,
// key for key — `scripts/tests/golden/ado_status_nodata.json` is the never-pulled form, and
// `test/adoVerbArgv.test.ts` holds `ADO_SYNC_VIEW_KEYS` / `ADO_SYNC_COUNT_KEYS` equal to its keys, so a key the
// plugin adds or renames turns that test red rather than reading as `undefined` here.
//
// Honesty (house rule 2): a count that was never measured is `null` — "no data", two words — never 0. A 0 is
// only ever the plugin's own, after a read that found none. Studio renders `null` with `reasons.NO_DATA` or
// `reasons.NOT_PULLED_YET` and never substitutes a number.
//
// Pure types plus two key lists: no `node:*` import, no I/O — included by both the renderer and main.

/** `counts` — every value `null` until the ledger holds a read that measured it. */
export interface AdoSyncCounts {
  conflicts: number | null
  debt: number | null
  drifted: number | null
  linked: number | null
  open: number | null
  pending: number | null
}

/** `last_plan` — the latest `plan` the ledger recorded: its 12-hex hash, when, and how many rows. */
export interface AdoLastPlan {
  plan: string
  ts: string | null
  rows: number
}

/** One `debt` row: an open SDLC-owned drift or conflict older than two business days, by ref and field —
 * never by person. `field` is `null` for a whole-item row. */
export interface AdoDebtRow {
  ref: string
  field: string | null
  class: string
  seen: string
  due: string
}

/** The `ado_sync.py status --json` document (`ado_sync_model.summarize`; never pulled = `STATUS_NODATA`). */
export interface AdoSyncView {
  as_of: string | null
  by_class: Record<string, number> | null
  counts: AdoSyncCounts
  debt: AdoDebtRow[] | null
  hook_line: string
  last_plan: AdoLastPlan | null
  ledger: string
  notes: string[]
  schema: number
}

// `satisfies Record<keyof T, true>` makes tsc refuse a missing key AND an extra one, so these runtime lists
// cannot drift from the interfaces above; the golden test then holds the lists to the plugin's document.
const VIEW_KEYS = {
  as_of: true, by_class: true, counts: true, debt: true, hook_line: true, last_plan: true, ledger: true, notes: true,
  schema: true,
} as const satisfies Record<keyof AdoSyncView, true>

const COUNT_KEYS = {
  conflicts: true, debt: true, drifted: true, linked: true, open: true, pending: true,
} as const satisfies Record<keyof AdoSyncCounts, true>

/** Every key of `AdoSyncView`, in the plugin's `sort_keys` order. */
export const ADO_SYNC_VIEW_KEYS = Object.keys(VIEW_KEYS) as ReadonlyArray<keyof AdoSyncView>

/** Every key of `AdoSyncView['counts']`, sorted. */
export const ADO_SYNC_COUNT_KEYS = Object.keys(COUNT_KEYS) as ReadonlyArray<keyof AdoSyncCounts>
