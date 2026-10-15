/** The Azure Boards mirror's closed argv table (build kit §3 and §5 B4-P0; design §12): one golden argv per
 * verb, `--by <actor>` the last two elements of every write and absent from every read, a comment's message
 * as ONE `--message=<text>` element whatever it holds, a confirm that is not 12 hex refused before any spawn,
 * and `AdoSyncView` held to the keys of the plugin's own never-pulled `status --json` golden. Pure — nothing
 * is spawned; the two plugin files read here are read as text. */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { ADO_SYNC_COUNT_KEYS, ADO_SYNC_VIEW_KEYS, type AdoSyncView } from '../shared/adoTypes'
import {
  ADO_VERB_CAPABILITY, ADO_VERBS, BY_FLAG, BY_VERBS, buildAdoVerbArgv, HASH, REF, SCRIPT, SDLC_REF, TAKES,
  validateAdoVerbRequest, type AdoVerbRequest,
} from '../shared/adoVerbArgv'
import * as reasons from '../shared/reasons'

const ACTOR = '@MCKRUZ'
const PLUGIN = resolve(__dirname, '..', '..')
const GOLDEN = resolve(PLUGIN, 'scripts', 'tests', 'golden', 'ado_status_nodata.json')
const MODEL = resolve(PLUGIN, 'scripts', 'ado_sync_model.py')

function argv(req: AdoVerbRequest, actor = ACTOR): string[] {
  const r = buildAdoVerbArgv(req, actor)
  if (!r.ok) throw new Error(r.errors.join('; '))
  return r.argv
}

describe('golden argv per verb', () => {
  const GOLDEN_ARGV: Array<[AdoVerbRequest, string[]]> = [
    [{ verb: 'apply', confirm: '0a1b2c3d4e5f' }, ['apply', '--confirm', '0a1b2c3d4e5f', '--json', '--by', ACTOR]],
    [{ verb: 'reconcile', ref: 'sdlc:spec:0004', field: 'System.AssignedTo', take: 'ado' },
      ['reconcile', 'sdlc:spec:0004', '--field', 'System.AssignedTo', '--take', 'ado', '--json', '--by', ACTOR]],
    [{ verb: 'reconcile', ref: 'sdlc:spec:0004', field: 'System.Title', take: 'sdlc' },
      ['reconcile', 'sdlc:spec:0004', '--field', 'System.Title', '--take', 'sdlc', '--json', '--by', ACTOR]],
    [{ verb: 'reconcile', ref: 'sdlc:spec:0004', field: 'System.State', take: 'ack', owner: '@MCKRUZ' },
      ['reconcile', 'sdlc:spec:0004', '--field', 'System.State', '--take', 'ack', '--owner=@MCKRUZ', '--json', '--by', ACTOR]],
    [{ verb: 'reconcile', ref: 'sdlc:decision:DL-03', field: 'System.IterationPath', take: 'not-drift', reason: '-the team re-planned "S09"' },
      ['reconcile', 'sdlc:decision:DL-03', '--field', 'System.IterationPath', '--take', 'not-drift', '--reason=-the team re-planned "S09"', '--json', '--by', ACTOR]],
    [{ verb: 'link', ref: 'sdlc:spec:0004', workItem: '#4521' }, ['link', 'sdlc:spec:0004', '--work-item', '#4521', '--json', '--by', ACTOR]],
    [{ verb: 'link', ref: 'sdlc:feature:FE-02', workItem: '4522' }, ['link', 'sdlc:feature:FE-02', '--work-item', '4522', '--json', '--by', ACTOR]],
    [{ verb: 'pull' }, ['pull', '--json']],
    [{ verb: 'pull', id: 'sdlc:spec:0004' }, ['pull', '--id', 'sdlc:spec:0004', '--json']],
    [{ verb: 'pullDiscussion' }, ['pull', '--discussion', '--json']],
    [{ verb: 'pullDiscussion', id: '#4521' }, ['pull', '--discussion', '--id', '#4521', '--json']],
    [{ verb: 'show', ref: 'sdlc:spec:0004' }, ['show', 'sdlc:spec:0004', '--json']],
    [{ verb: 'show', ref: '#4521' }, ['show', '#4521', '--json']],
    [{ verb: 'comment', ref: 'sdlc:spec:0004', message: 'Ready for review' },
      ['comment', 'sdlc:spec:0004', '--message=Ready for review', '--json', '--by', ACTOR]],
    [{ verb: 'plan', kind: 'spec', id: '0004' }, ['plan', '--kind', 'spec', '--id', '0004', '--json']],
    [{ verb: 'plan', sprint: 'S07' }, ['plan', '--sprint', 'S07', '--json']],
  ]

  it.each(GOLDEN_ARGV)('%j', (req, expected) => {
    expect(argv(req)).toEqual(expected)
  })

  it('covers every verb, in the order the table lists them', () => {
    const verbs = new Set(GOLDEN_ARGV.map(([req]) => req.verb))
    for (const v of ADO_VERBS) expect(verbs.has(v), v).toBe(true)
    expect([...ADO_VERBS]).toEqual(['apply', 'reconcile', 'link', 'pull', 'pullDiscussion', 'show', 'comment', 'plan'])
    expect([...BY_VERBS]).toEqual(['apply', 'reconcile', 'link', 'comment'])
    expect(SCRIPT).toBe('ado_sync.py')
    expect(BY_FLAG).toBe('--by')
  })

  it('--by <actor> is the last two elements of every write and absent from every read', () => {
    for (const [req] of GOLDEN_ARGV) {
      const a = argv(req)
      if (BY_VERBS.includes(req.verb)) {
        expect(a.slice(-2), req.verb).toEqual([BY_FLAG, ACTOR])
        expect(a.filter((x) => x === BY_FLAG), req.verb).toHaveLength(1)
      } else {
        expect(a, req.verb).not.toContain(BY_FLAG)
        expect(a.some((x) => x.startsWith('--by')), req.verb).toBe(false)
      }
      expect(a.filter((x) => x === '--json'), req.verb).toHaveLength(1)
    }
  })

  it('a read needs no actor; a write without one is refused before any spawn', () => {
    expect(argv({ verb: 'show', ref: '#4521' }, '')).toEqual(['show', '#4521', '--json'])
    expect(argv({ verb: 'pull' }, '   ')).toEqual(['pull', '--json'])
    for (const req of [
      { verb: 'apply', confirm: '0a1b2c3d4e5f' }, { verb: 'link', ref: 'sdlc:spec:0004', workItem: '4521' },
      { verb: 'comment', ref: 'sdlc:spec:0004', message: 'x' },
      { verb: 'reconcile', ref: 'sdlc:spec:0004', field: 'System.Title', take: 'sdlc' },
    ] as AdoVerbRequest[]) {
      expect(buildAdoVerbArgv(req, '  '), req.verb).toEqual({ ok: false, errors: ['no actor'] })
    }
  })

  it('the actor is trimmed and stays one element', () => {
    expect(argv({ verb: 'apply', confirm: '0a1b2c3d4e5f' }, '  @MCKRUZ  ').slice(-2)).toEqual(['--by', '@MCKRUZ'])
  })
})

describe('a comment message is ONE argv element, --message=<text>, byte for byte', () => {
  const MESSAGES: Array<[string, string]> = [
    ['a double quote', 'returns "409", not 200'],
    ['a newline', 'line one\nline two'],
    ['a command substitution', 'never run $(rm -rf ~) or `id`'],
    ['non-ASCII text', 'Prüfung bestanden — 確認済み ✓ ⚑'],
    ['a leading dash', '-1 is the rev we saw; --by @someone-else is text'],
    ['all five at once', '-"a"\n$(b) — ç'],
    ['surrounding blanks kept', '  indented\n'],
  ]

  it.each(MESSAGES)('%s', (_label, message) => {
    const a = argv({ verb: 'comment', ref: 'sdlc:spec:0004', message })
    expect(a).toEqual(['comment', 'sdlc:spec:0004', `--message=${message}`, '--json', '--by', ACTOR])
    expect(a.filter((x) => x.startsWith('--message'))).toEqual([`--message=${message}`])
    expect(a).not.toContain(message)
    expect(a).not.toContain('--message')
  })

  it('an empty or blank message, or one carrying a NUL, is refused', () => {
    expect(validateAdoVerbRequest({ verb: 'comment', ref: 'sdlc:spec:0004', message: '' })).toEqual(['message is required'])
    expect(validateAdoVerbRequest({ verb: 'comment', ref: 'sdlc:spec:0004', message: ' \n ' })).toEqual(['message is required'])
    expect(validateAdoVerbRequest({ verb: 'comment', ref: 'sdlc:spec:0004', message: 'a\0b' })).toEqual(['message contains a NUL character'])
  })
})

describe('refusals before any spawn — shape only, never a judgement', () => {
  it('apply with a confirm that is not the 12-hex plan hash returns errors', () => {
    const r = buildAdoVerbArgv({ verb: 'apply', confirm: 'ZZZ' }, ACTOR)
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.errors).toEqual(["confirm 'ZZZ' is not the plan's 12-hex hash"])
    for (const bad of ['ZZZ', '', '0A1B2C3D4E5F', '0a1b2c3d4e5', '0a1b2c3d4e5f0', ' 0a1b2c3d4e5f', '0a1b2c3d4e5f\n']) {
      expect(validateAdoVerbRequest({ verb: 'apply', confirm: bad }), JSON.stringify(bad)).toHaveLength(1)
    }
    expect(HASH.test('0a1b2c3d4e5f')).toBe(true)
  })

  it('REF is the kit pattern: an sdlc ref or a #<work item>, nothing else', () => {
    for (const ok of ['sdlc:spec:0004', 'sdlc:decision:DL-03', 'sdlc:feature:FE-02', '#4521']) expect(REF.test(ok), ok).toBe(true)
    for (const bad of ['AB#4521', '4521', 'sdlc:Spec:0004', 'sdlc:spec:', 'sdlc:spec:0004; rm -rf', '-x', '#', '#45 21', 'sdlc:spec:0004\n']) {
      expect(REF.test(bad), bad).toBe(false)
    }
    expect(validateAdoVerbRequest({ verb: 'show', ref: 'AB#4521' })).toEqual(["ref 'AB#4521' is not an sdlc:<kind>:<id> ref or a #<work item>"])
    expect(validateAdoVerbRequest({ verb: 'pull', id: '--all' })).toEqual(["id '--all' is not an sdlc:<kind>:<id> ref or a #<work item>"])
    expect(validateAdoVerbRequest({ verb: 'comment', ref: '-x', message: 'm' })).toHaveLength(1)
  })

  it('link pairs an sdlc ref with a work item number (4521 or #4521, never AB#4521)', () => {
    expect(validateAdoVerbRequest({ verb: 'link', ref: '#4521', workItem: '4521' })).toEqual(["ref '#4521' is not an sdlc:<kind>:<id> ref"])
    expect(validateAdoVerbRequest({ verb: 'link', ref: 'sdlc:spec:0004', workItem: 'AB#4521' })).toEqual(["work item 'AB#4521' is not a work item number (4521 or #4521)"])
    expect(validateAdoVerbRequest({ verb: 'link', ref: 'sdlc:spec:0004', workItem: '0' })).toHaveLength(1)
    expect(validateAdoVerbRequest({ verb: 'link', ref: 'sdlc:spec:0004', workItem: '#4521' })).toEqual([])
  })

  it('reconcile: a field reference name, one of the four takes, an owner for ack and a reason for not-drift', () => {
    const base = { verb: 'reconcile' as const, ref: 'sdlc:spec:0004', field: 'System.State' }
    expect(validateAdoVerbRequest({ ...base, take: 'ack' })).toEqual(['owner is required'])
    expect(validateAdoVerbRequest({ ...base, take: 'ack', owner: '  ' })).toEqual(['owner is required'])
    expect(validateAdoVerbRequest({ ...base, take: 'not-drift' })).toEqual(['reason is required'])
    expect(validateAdoVerbRequest({ ...base, take: 'mine' as never })).toEqual(["take 'mine' is not ado, sdlc, ack or not-drift"])
    expect(validateAdoVerbRequest({ ...base, field: '--take', take: 'ado' })).toEqual(["field '--take' is not a work item field reference name (System.State, Custom.RiskTier)"])
    expect(validateAdoVerbRequest({ ...base, field: 'State', take: 'ado' })).toHaveLength(1)
    expect(validateAdoVerbRequest({ ...base, take: 'sdlc', reason: 'a\0b' })).toEqual(['reason contains a NUL character'])
    expect(validateAdoVerbRequest({ ...base, take: 'ado' })).toEqual([])
    expect([...TAKES]).toEqual(['ado', 'sdlc', 'ack', 'not-drift'])
  })

  it('a blank optional owner or reason is left out, never sent as an empty flag', () => {
    const a = argv({ verb: 'reconcile', ref: 'sdlc:spec:0004', field: 'System.Title', take: 'sdlc', owner: ' ', reason: '' })
    expect(a).toEqual(['reconcile', 'sdlc:spec:0004', '--field', 'System.Title', '--take', 'sdlc', '--json', '--by', ACTOR])
  })

  it('a verb the table does not know, or no request at all, is refused and never throws', () => {
    expect(validateAdoVerbRequest({ verb: 'delete' } as unknown as AdoVerbRequest)).toEqual(["'delete' is not a Boards verb Shepherd runs"])
    expect(buildAdoVerbArgv({ verb: 'status' } as unknown as AdoVerbRequest, ACTOR)).toEqual({ ok: false, errors: ["'status' is not a Boards verb Shepherd runs"] })
    expect(validateAdoVerbRequest(null as unknown as AdoVerbRequest)).toEqual(['not a Boards request'])
    expect(validateAdoVerbRequest({ verb: 'apply', confirm: 123 } as unknown as AdoVerbRequest)).toEqual(["confirm '123' is not the plan's 12-hex hash"])
  })

  it('the take words are the plugin model\'s RECONCILE_TAKES, in its order', () => {
    const src = readFileSync(MODEL, 'utf-8')
    const m = /^RECONCILE_TAKES: Final = \(([^)]*)\)/m.exec(src)
    expect(m, 'RECONCILE_TAKES in scripts/ado_sync_model.py').not.toBeNull()
    const words = [...m![1]!.matchAll(/"([^"]+)"/g)].map((w) => w[1])
    expect(words).toEqual([...TAKES])
  })
})

describe('reconcile takes an sdlc ref only — the CLI refuses #<id> there (B5-P4)', () => {
  const base = { verb: 'reconcile' as const, field: 'System.State', take: 'sdlc' as const }

  it("SDLC_REF is the plugin's boards_contract.REF_RE: sdlc:<kind>:<id>, never a #<work item>", () => {
    for (const ok of ['sdlc:spec:0004', 'sdlc:decision:DL-03', 'sdlc:feature:FE-02']) expect(SDLC_REF.test(ok), ok).toBe(true)
    for (const bad of ['#4521', 'AB#4521', '4521', 'sdlc:Spec:0004', 'sdlc:spec:', 'sdlc:spec:0004; rm', '-x', 'sdlc:spec:0004\n']) {
      expect(SDLC_REF.test(bad), bad).toBe(false)
    }
    // the plugin's own pattern, read as text so a change there turns this red
    const contract = readFileSync(resolve(PLUGIN, 'scripts', 'boards_contract.py'), 'utf-8')
    const m = /^REF_RE: Final = re\.compile\(r"([^"]+)"\)/m.exec(contract)
    expect(m, 'REF_RE in scripts/boards_contract.py').not.toBeNull()
    expect(SDLC_REF.source).toBe(m![1])
  })

  it('a #<work item> ref is refused for reconcile (it is still fine for show, pull and comment)', () => {
    expect(validateAdoVerbRequest({ ...base, ref: '#4521' })).toEqual(["ref '#4521' is not an sdlc:<kind>:<id> ref"])
    expect(buildAdoVerbArgv({ ...base, ref: '#4521' }, ACTOR)).toEqual({ ok: false, errors: ["ref '#4521' is not an sdlc:<kind>:<id> ref"] })
    expect(validateAdoVerbRequest({ ...base, ref: 'sdlc:spec:0004' })).toEqual([])
    expect(validateAdoVerbRequest({ verb: 'show', ref: '#4521' })).toEqual([])
    expect(validateAdoVerbRequest({ verb: 'pull', id: '#4521' })).toEqual([])
    expect(validateAdoVerbRequest({ verb: 'comment', ref: '#4521', message: 'm' })).toEqual([])
  })

  it('a non-text ref, or one that smuggles a flag, never builds an argv', () => {
    for (const bad of [undefined, null, 4521, '', '--take', 'sdlc:spec:0004 --take ado']) {
      expect(buildAdoVerbArgv({ ...base, ref: bad as never }, ACTOR).ok, String(bad)).toBe(false)
    }
  })
})

describe("the table is the interface sheet's eight requests — B6 widened it by one read verb, plan (K28)", () => {
  const KIT = resolve(PLUGIN, 'docs', 'proposals', 'ado-boards-mirror-build-kit.md')

  /** The `verb:` names of the pinned union, read from the build kit's §3 B4-P0 block as text. */
  function sheetVerbs(): string[] {
    const kit = readFileSync(KIT, 'utf-8')
    const start = kit.indexOf('// studio/shared/adoVerbArgv.ts (B4-P0)')
    expect(start, 'the B4-P0 adoVerbArgv.ts block in the build kit §3').toBeGreaterThan(-1)
    const end = kit.indexOf('export const SCRIPT', start)
    expect(end, 'the end of the pinned AdoVerbRequest union').toBeGreaterThan(start)
    return [...kit.slice(start, end).matchAll(/verb: '(\w+)'/g)].map((m) => m[1]!)
  }

  it('ADO_VERBS and the capability map name exactly the verbs the sheet pins, in its order', () => {
    const pinned = sheetVerbs()
    expect(pinned).toHaveLength(8)
    expect([...ADO_VERBS]).toEqual(pinned)
    expect(Object.keys(ADO_VERB_CAPABILITY)).toEqual(pinned)
  })

  it('planSpec is still not in the table: refused before any spawn, like any verb the sheet does not list', () => {
    const req = { verb: 'planSpec', spec: '0004' }
    expect(validateAdoVerbRequest(req as unknown as AdoVerbRequest)).toEqual(["'planSpec' is not a Boards verb Shepherd runs"])
    expect(buildAdoVerbArgv(req as unknown as AdoVerbRequest, ACTOR)).toEqual({ ok: false, errors: ["'planSpec' is not a Boards verb Shepherd runs"] })
    expect(ADO_VERBS.filter((v) => /plan/i.test(v))).toEqual(['plan'])
  })

  it('plan without a whole scope is refused before any spawn: no scope, a sprint that is not SNN, a kind with no id', () => {
    for (const bad of [
      { verb: 'plan' }, { verb: 'plan', sprint: '7' }, { verb: 'plan', kind: 'spec' },
      { verb: 'plan', id: '0004' }, { verb: 'plan', sprint: 'S07', kind: 'spec', id: '0004' },
      { verb: 'plan', kind: 'spec', id: '--all' }, { verb: 'plan', kind: '--sprint', id: '0004' }, { verb: 'plan', kind: 'spec', id: '0004 --all' },
    ]) {
      const req = bad as unknown as AdoVerbRequest
      expect(validateAdoVerbRequest(req).length, JSON.stringify(bad)).toBeGreaterThan(0)
      const built = buildAdoVerbArgv(req, ACTOR)
      expect(built.ok, JSON.stringify(bad)).toBe(false)
      if (!built.ok) expect(built.errors).not.toContain("'plan' is not a Boards verb Shepherd runs")
    }
  })

  it('plan with a kind and an id is accepted as a READ: no --by, whoever the actor is', () => {
    const req: AdoVerbRequest = { verb: 'plan', kind: 'spec', id: '0004' }
    expect(validateAdoVerbRequest(req)).toEqual([])
    expect(buildAdoVerbArgv(req, ACTOR)).toEqual({ ok: true, argv: ['plan', '--kind', 'spec', '--id', '0004', '--json'] })
    expect(buildAdoVerbArgv(req, '')).toEqual({ ok: true, argv: ['plan', '--kind', 'spec', '--id', '0004', '--json'] })
    expect(argv(req)).not.toContain(BY_FLAG)
    expect(BY_VERBS).not.toContain('plan')
  })
})

describe('each verb names the capability that gates it', () => {
  it('maps to the plugin capability ids, the six Boards ones through CAPABILITIES', () => {
    expect(ADO_VERB_CAPABILITY).toEqual({
      apply: 'ado-apply', reconcile: 'ado-reconcile', link: 'ado-link', pull: 'ado-pull', pullDiscussion: 'ado-pull-discussion',
      show: 'ado-show', comment: 'ado-comment', plan: 'ado-plan',
    })
    expect(ADO_VERB_CAPABILITY.apply).toBe(reasons.CAPABILITIES.adoApply)
    expect(ADO_VERB_CAPABILITY.reconcile).toBe(reasons.CAPABILITIES.adoReconcile)
    expect(ADO_VERB_CAPABILITY.show).toBe(reasons.CAPABILITIES.adoShow)
    expect(ADO_VERB_CAPABILITY.pullDiscussion).toBe(reasons.CAPABILITIES.adoDiscussion)
    expect(ADO_VERB_CAPABILITY.comment).toBe(reasons.CAPABILITIES.adoComment)
    expect(Object.keys(ADO_VERB_CAPABILITY).sort()).toEqual([...ADO_VERBS].sort())
  })

  it('CAPABILITIES names the six Boards ids', () => {
    expect(reasons.CAPABILITIES.adoStatus).toBe('ado-status-json')
    expect(reasons.CAPABILITIES.adoApply).toBe('ado-apply')
    expect(reasons.CAPABILITIES.adoReconcile).toBe('ado-reconcile')
    expect(reasons.CAPABILITIES.adoShow).toBe('ado-show')
    expect(reasons.CAPABILITIES.adoDiscussion).toBe('ado-pull-discussion')
    expect(reasons.CAPABILITIES.adoComment).toBe('ado-comment')
    expect(reasons.isReason(reasons.newerPlugin(reasons.CAPABILITIES.adoStatus))).toBe(true)
  })
})

describe('the Boards no-data sentences', () => {
  const SENTENCES: Array<[string, string]> = [
    [reasons.WORK_ITEMS_NOT_SET_UP, 'Work items are not set up for this project'],
    [reasons.SCHEMA_NOT_DISCOVERED, 'Schema not discovered yet'],
    [reasons.NOT_PULLED_YET, 'Not pulled yet'],
    [reasons.BOARDS_UNREACHABLE, 'Could not reach Azure Boards'],
  ]

  it.each(SENTENCES)('%s — word for word, digit-free, a reason', (sentence, words) => {
    expect(sentence).toBe(words)
    expect(sentence).not.toMatch(/\d/)
    expect(reasons.REASON_SENTENCES).toContain(sentence)
    expect(reasons.isReason(sentence)).toBe(true)
  })
})

describe('AdoSyncView mirrors the plugin\'s never-pulled status --json golden', () => {
  const golden = JSON.parse(readFileSync(GOLDEN, 'utf-8')) as Record<string, unknown>

  it('has exactly the golden\'s keys', () => {
    expect(Object.keys(golden).sort()).toEqual([...ADO_SYNC_VIEW_KEYS].sort())
    expect(ADO_SYNC_VIEW_KEYS).toHaveLength(9)
  })

  it('and exactly its count keys', () => {
    expect(Object.keys(golden.counts as Record<string, unknown>).sort()).toEqual([...ADO_SYNC_COUNT_KEYS].sort())
  })

  it('reads as the type: every count unmeasured (null), never 0', () => {
    const view = golden as unknown as AdoSyncView
    expect(view.as_of).toBeNull()
    expect(view.hook_line).toBe('no data (never pulled)')
    for (const k of ADO_SYNC_COUNT_KEYS) expect(view.counts[k], k).toBeNull()
    expect(JSON.stringify(view)).not.toMatch(/:\s*0\b/)
  })
})
