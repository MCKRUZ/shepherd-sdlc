/** The Azure Boards write path's spawn side (build kit §5 B4-P2; house rules 8 and 9): the renderer hands
 * main one closed `AdoVerbRequest`; main resolves the actor itself, builds the argv from the pure table
 * (`shared/adoVerbArgv.ts`) with the project source spliced after the verb, and spawns `ado_sync.py` ONCE.
 * The exit code is the truth (0 Done, 1 Not done, 2 Refused by the plugin); no actor, a bad request, a verb
 * the plugin lacks or a missing plugin refuse BEFORE any spawn with `exitCode: null`; every spawn, whatever
 * its exit, invalidates the command center's local blocks; nothing here can reach `az`, a shell, or a `--by`
 * the renderer chose. `registerAdoIpc` is the one handler that wires it. */
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../electron/main/project', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../electron/main/project')>()),
  runPluginScript: vi.fn(),
}))
vi.mock('../../electron/main/commandCenter', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../electron/main/commandCenter')>()),
  invalidateCommandCenter: vi.fn(),
  warmCommandCenter: vi.fn(() => null),
  getCapabilities: vi.fn(),
}))
vi.mock('../../electron/main/actor', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../electron/main/actor')>()),
  resolveActor: vi.fn(),
}))

import { adoVerbArgv, runAdoVerb } from '../../electron/main/adoWrites'
import { ADO_VERB_CHANNEL, registerAdoIpc } from '../../electron/main/adoIpc'
import { resolveActor } from '../../electron/main/actor'
import { runPluginScript } from '../../electron/main/project'
import { getCapabilities, invalidateCommandCenter, warmCommandCenter } from '../../electron/main/commandCenter'
import { ADO_VERB_CAPABILITY, ADO_VERBS, SCRIPT, type AdoVerbRequest } from '../../shared/adoVerbArgv'
import { PLUGIN_NOT_FOUND } from '../../shared/pluginId'
import { NO_ACTOR, newerPlugin } from '../../shared/reasons'
import type { ConsoleEntry } from '../../shared/types'

const run = vi.mocked(runPluginScript)
const PROJECT = '/work/proj'   // no .sdlc/state.yaml here on any machine → --repo
const SCRIPTS = '/plugin/scripts'
const ACTOR = { name: '@priya-n', source: 'roster' as const }
const REF = 'sdlc:spec:0001'
const HASH = 'a1b2c3d4e5f6'
const MAIN = resolve(__dirname, '..', '..', 'electron', 'main')
const entry = (exitCode: number, stdout = '', stderr = ''): ConsoleEntry => ({ id: 'x', command: 'py', args: [], cwd: '', startedAt: '', durationMs: 0, exitCode, stdout, stderr, ok: exitCode === 0 })

/** One request per verb, each with the argv the table prints for it (`--repo` spliced after the verb, `--json`
 * before the actor, `--by` last on a write and absent from a read). */
const EVERY_VERB: ReadonlyArray<{ req: AdoVerbRequest; argv: string[] }> = [
  { req: { verb: 'apply', confirm: HASH }, argv: ['apply', '--repo', PROJECT, '--confirm', HASH, '--json', '--by', '@priya-n'] },
  { req: { verb: 'reconcile', ref: REF, field: 'System.State', take: 'sdlc' }, argv: ['reconcile', '--repo', PROJECT, REF, '--field', 'System.State', '--take', 'sdlc', '--json', '--by', '@priya-n'] },
  { req: { verb: 'link', ref: REF, workItem: '4521' }, argv: ['link', '--repo', PROJECT, REF, '--work-item', '4521', '--json', '--by', '@priya-n'] },
  { req: { verb: 'pull' }, argv: ['pull', '--repo', PROJECT, '--json'] },
  { req: { verb: 'pullDiscussion', id: REF }, argv: ['pull', '--repo', PROJECT, '--discussion', '--id', REF, '--json'] },
  { req: { verb: 'show', ref: REF }, argv: ['show', '--repo', PROJECT, REF, '--json'] },
  { req: { verb: 'comment', ref: REF, message: 'Looks right.' }, argv: ['comment', '--repo', PROJECT, REF, '--message=Looks right.', '--json', '--by', '@priya-n'] },
  { req: { verb: 'plan', kind: 'spec', id: '0001' }, argv: ['plan', '--repo', PROJECT, '--kind', 'spec', '--id', '0001', '--json'] },
]

beforeEach(() => {
  run.mockReset()
  vi.mocked(invalidateCommandCenter).mockClear()
  vi.mocked(warmCommandCenter).mockClear()
  vi.mocked(resolveActor).mockReset()
  vi.mocked(getCapabilities).mockReset()
})
afterEach(() => vi.useRealTimers())

describe('adoVerbArgv', () => {
  it('is the table\'s argv with the project source spliced after the verb', () => {
    for (const { req, argv } of EVERY_VERB) expect(adoVerbArgv(PROJECT, req, '@priya-n'), req.verb).toEqual({ ok: true, argv })
  })

  it('uses --state when the project has one, so the plugin reads the same project Studio has open', () => {
    const dir = mkdtempSync(join(tmpdir(), 'ado-w-'))
    try {
      mkdirSync(join(dir, '.sdlc')); writeFileSync(join(dir, '.sdlc', 'state.yaml'), 'current_phase: build\n')
      const r = adoVerbArgv(dir, { verb: 'show', ref: REF }, '@priya-n')
      expect(r).toEqual({ ok: true, argv: ['show', '--state', join(dir, '.sdlc', 'state.yaml'), REF, '--json'] })
    } finally { rmSync(dir, { recursive: true, force: true }) }
  })

  it('refuses a request the table refuses, with the table\'s reasons and no argv', () => {
    const r = adoVerbArgv(PROJECT, { verb: 'apply', confirm: 'ZZZ' }, '@priya-n')
    expect(r.ok).toBe(false)
    expect(!r.ok && r.errors.join(' ')).toMatch(/12-hex/)
  })

  it('keeps a message with a quote, a newline, $( , non-ASCII and a leading dash as ONE element, never a flag', () => {
    const message = '-rf "x"\n$(touch /tmp/p) café'
    const r = adoVerbArgv(PROJECT, { verb: 'comment', ref: REF, message }, '@priya-n')
    expect(r.ok && r.argv).toContain(`--message=${message}`)
    expect(r.ok && r.argv.filter((a) => a.includes('touch'))).toHaveLength(1)
    expect(r.ok && r.argv.slice(-2)).toEqual(['--by', '@priya-n'])
  })
})

describe('runAdoVerb', () => {
  it('exit 0 is Done: ok, not refused, stdout verbatim, the argv that ran, the plugin\'s JSON beside it', async () => {
    run.mockResolvedValue(entry(0, JSON.stringify({ ok: true, plan: HASH, apply_offered: true })))
    const r = await runAdoVerb(PROJECT, SCRIPTS, { verb: 'comment', ref: REF, message: 'hi' }, ACTOR)
    expect(r).toEqual({
      ok: true, exitCode: 0, refused: false, stdout: JSON.stringify({ ok: true, plan: HASH, apply_offered: true }), stderr: '',
      verb: 'comment', json: { ok: true, plan: HASH, apply_offered: true },
      argv: ['comment', '--repo', PROJECT, REF, '--message=hi', '--json', '--by', '@priya-n'],
    })
    expect(run).toHaveBeenCalledTimes(1)
    expect(run).toHaveBeenCalledWith(SCRIPTS, 'ado_sync.py', r.argv)
    expect(invalidateCommandCenter).toHaveBeenCalledWith(PROJECT)
  })

  it('exit 0 warms the read the renderer is about to make; a non-zero exit does not', async () => {
    run.mockResolvedValue(entry(0, '{}'))
    await runAdoVerb(PROJECT, SCRIPTS, { verb: 'pull' }, ACTOR)
    expect(warmCommandCenter).toHaveBeenCalledWith(PROJECT)
    vi.mocked(warmCommandCenter).mockClear()
    run.mockResolvedValue(entry(1, '', 'Error: nothing to pull'))
    await runAdoVerb(PROJECT, SCRIPTS, { verb: 'pull' }, ACTOR)
    expect(warmCommandCenter).not.toHaveBeenCalled()
  })

  it('exit 1 is Not done, stderr verbatim, not refused', async () => {
    run.mockResolvedValue(entry(1, '', 'Error: stale plan hash\n'))
    const r = await runAdoVerb(PROJECT, SCRIPTS, { verb: 'apply', confirm: HASH }, ACTOR)
    expect(r).toMatchObject({ ok: false, exitCode: 1, refused: false, stderr: 'Error: stale plan hash\n', json: null })
    expect(invalidateCommandCenter).toHaveBeenCalledWith(PROJECT)
  })

  it('exit 2 is Refused by the plugin', async () => {
    run.mockResolvedValue(entry(2, '', "Refused: --by 'Claude' reads as an AI/automation"))
    const r = await runAdoVerb(PROJECT, SCRIPTS, { verb: 'link', ref: REF, workItem: '4521' }, { name: 'Claude', source: 'typed' })
    expect(r).toMatchObject({ ok: false, exitCode: 2, refused: true, stderr: expect.stringContaining('Refused') })
    expect(invalidateCommandCenter).toHaveBeenCalled()
  })

  it('a plugin JSON refusal on stdout is still handed over as `json`; prose is not', async () => {
    run.mockResolvedValue(entry(2, JSON.stringify({ ok: false, refused: 'posture plan-only' })))
    expect((await runAdoVerb(PROJECT, SCRIPTS, { verb: 'apply', confirm: HASH }, ACTOR)).json).toEqual({ ok: false, refused: 'posture plan-only' })
    run.mockResolvedValue(entry(0, 'Linked sdlc:spec:0001 to #4521'))
    expect((await runAdoVerb(PROJECT, SCRIPTS, { verb: 'link', ref: REF, workItem: '4521' }, ACTOR)).json).toBeNull()
    run.mockResolvedValue(entry(0, '[1,2]'))
    expect((await runAdoVerb(PROJECT, SCRIPTS, { verb: 'pull' }, ACTOR)).json).toBeNull()
  })

  it('reconcile refuses a #<work item> ref here too — before any spawn (B5-P4)', async () => {
    const r = await runAdoVerb(PROJECT, SCRIPTS, { verb: 'reconcile', ref: '#4521', field: 'System.State', take: 'sdlc' }, ACTOR)
    expect(r.exitCode).toBeNull(); expect(r.stderr).toBe("ref '#4521' is not an sdlc:<kind>:<id> ref")
    expect(run).not.toHaveBeenCalled(); expect(invalidateCommandCenter).not.toHaveBeenCalled()
  })

  it('a plan request (planSpec) is not one of the eight: refused before any spawn, nothing invalidated (B5-P4)', async () => {
    const r = await runAdoVerb(PROJECT, SCRIPTS, { verb: 'planSpec', spec: '0001' } as unknown as AdoVerbRequest, ACTOR)
    expect(r).toEqual({ ok: false, exitCode: null, refused: false, stdout: '', stderr: 'That is not a Boards verb Shepherd runs.', argv: [], verb: 'show', json: null })
    expect(run).not.toHaveBeenCalled(); expect(invalidateCommandCenter).not.toHaveBeenCalled()
    expect(ADO_VERBS).toHaveLength(8)
  })

  it('plan with no scope is the one read B6 added, refused by the table before any spawn, nothing invalidated (B6-P0)', async () => {
    const r = await runAdoVerb(PROJECT, SCRIPTS, { verb: 'plan' } as unknown as AdoVerbRequest, ACTOR)
    expect(r).toMatchObject({ ok: false, exitCode: null, refused: false, stdout: '', argv: [], verb: 'plan', json: null })
    expect(r.stderr).not.toBe('That is not a Boards verb Shepherd runs.'); expect(r.stderr).not.toBe('')
    expect(run).not.toHaveBeenCalled(); expect(invalidateCommandCenter).not.toHaveBeenCalled()
  })

  it('runs ado_sync.py once per verb, whichever of the eight it is, and never az', async () => {
    run.mockResolvedValue(entry(0, '{}'))
    for (const { req, argv } of EVERY_VERB) {
      run.mockClear()
      const r = await runAdoVerb(PROJECT, SCRIPTS, req, ACTOR)
      expect(r.argv, req.verb).toEqual(argv)
      expect(run, req.verb).toHaveBeenCalledTimes(1)
      expect(run.mock.calls[0]![1], req.verb).toBe(SCRIPT)
      expect(run.mock.calls[0]![1]).toBe('ado_sync.py')
      expect(run.mock.calls[0]![2].includes('az'), req.verb).toBe(false)
    }
    expect(EVERY_VERB.map((v) => v.req.verb).sort()).toEqual([...ADO_VERBS].sort())
  })

  it('the composer is two verbs, two spawns: comment drafts the plan, apply sends the hash the plan printed', async () => {
    run.mockResolvedValueOnce(entry(0, JSON.stringify({ ok: true, plan: HASH, apply_offered: true })))
    const drafted = await runAdoVerb(PROJECT, SCRIPTS, { verb: 'comment', ref: REF, message: 'On it.' }, ACTOR)
    expect(run).toHaveBeenCalledTimes(1)
    const plan = String(drafted.json?.plan)
    run.mockResolvedValueOnce(entry(0, JSON.stringify({ ok: true, applied: 1 })))
    const sent = await runAdoVerb(PROJECT, SCRIPTS, { verb: 'apply', confirm: plan }, ACTOR)
    expect(run).toHaveBeenCalledTimes(2)
    expect(run.mock.calls.map((c) => c[2][0])).toEqual(['comment', 'apply'])
    expect(sent.argv).toEqual(['apply', '--repo', PROJECT, '--confirm', HASH, '--json', '--by', '@priya-n'])
    expect(invalidateCommandCenter).toHaveBeenCalledTimes(2)
  })

  it('no actor refuses before spawning with NO_ACTOR and exitCode null (Shepherd did not ask)', async () => {
    for (const { req } of EVERY_VERB) {
      const r = await runAdoVerb(PROJECT, SCRIPTS, req, null)
      expect(r, req.verb).toEqual({ ok: false, exitCode: null, refused: false, stdout: '', stderr: NO_ACTOR, argv: [], verb: req.verb, json: null })
    }
    expect(run).not.toHaveBeenCalled(); expect(invalidateCommandCenter).not.toHaveBeenCalled()
  })

  it('a bad request never reaches a spawn; the mirrored rule is the stderr', async () => {
    const hash = await runAdoVerb(PROJECT, SCRIPTS, { verb: 'apply', confirm: 'ZZZ' }, ACTOR)
    expect(hash.exitCode).toBeNull(); expect(hash.stderr).toMatch(/12-hex/)
    const ack = await runAdoVerb(PROJECT, SCRIPTS, { verb: 'reconcile', ref: REF, field: 'System.State', take: 'ack' }, ACTOR)
    expect(ack.exitCode).toBeNull(); expect(ack.stderr).toBe('owner is required')
    const ref = await runAdoVerb(PROJECT, SCRIPTS, { verb: 'show', ref: 'AB#4521' }, ACTOR)
    expect(ref.exitCode).toBeNull(); expect(ref.stderr).toMatch(/not an sdlc:<kind>:<id> ref or a #<work item>/)
    expect(run).not.toHaveBeenCalled(); expect(invalidateCommandCenter).not.toHaveBeenCalled()
  })

  it('something that is not a Boards verb is refused, never spawned, with a sentence that says Shepherd', async () => {
    for (const bad of [{ verb: 'planSpec' }, { verb: 'config' }, { verb: 'status' }, {}, null, undefined, 'apply'] as unknown[]) {
      const r = await runAdoVerb(PROJECT, SCRIPTS, bad as AdoVerbRequest, ACTOR)
      expect(r.ok).toBe(false); expect(r.exitCode).toBeNull(); expect(r.refused).toBe(false)
      expect(r.stderr).toBe('That is not a Boards verb Shepherd runs.')
    }
    expect(run).not.toHaveBeenCalled()
  })

  it('a verb the plugin lacks is refused with newerPlugin(cap) when capabilities are known', async () => {
    const apply: AdoVerbRequest = { verb: 'apply', confirm: HASH }
    const r = await runAdoVerb(PROJECT, SCRIPTS, apply, ACTOR, ['ado-status-json', 'ado-comment'])
    expect(r).toMatchObject({ ok: false, exitCode: null, stderr: newerPlugin(ADO_VERB_CAPABILITY.apply) })
    expect(newerPlugin('ado-apply')).toBe(r.stderr); expect(run).not.toHaveBeenCalled()
    run.mockResolvedValue(entry(0, '{}'))
    expect((await runAdoVerb(PROJECT, SCRIPTS, apply, ACTOR, ['ado-apply'])).ok).toBe(true)
    // Capabilities the caller does not know (a unit test, a project with no state file) are not a refusal.
    expect((await runAdoVerb(PROJECT, SCRIPTS, apply, ACTOR)).ok).toBe(true)
  })

  it('every verb is gated on the capability the table names for it', async () => {
    for (const { req } of EVERY_VERB) {
      const r = await runAdoVerb(PROJECT, SCRIPTS, req, ACTOR, [])
      expect(r.stderr, req.verb).toBe(newerPlugin(ADO_VERB_CAPABILITY[req.verb])); expect(r.exitCode).toBeNull()
    }
    expect(run).not.toHaveBeenCalled()
  })

  it('no plugin scripts folder refuses with PLUGIN_NOT_FOUND (which names Shepherd) before anything else', async () => {
    const r = await runAdoVerb(PROJECT, null, { verb: 'pull' }, ACTOR)
    expect(r).toEqual({ ok: false, exitCode: null, refused: false, stdout: '', stderr: PLUGIN_NOT_FOUND, argv: [], verb: 'pull', json: null })
    expect(PLUGIN_NOT_FOUND).toContain('Shepherd'); expect(run).not.toHaveBeenCalled()
  })

  it('a spawn that throws is the plugin not answering: the local blocks are still invalidated', async () => {
    run.mockRejectedValue(new Error('spawn uv ENOENT'))
    await expect(runAdoVerb(PROJECT, SCRIPTS, { verb: 'pull' }, ACTOR)).rejects.toThrow('spawn uv ENOENT')
    expect(invalidateCommandCenter).toHaveBeenCalledWith(PROJECT)
  })
})

describe('registerAdoIpc', () => {
  type Handler = (event: unknown, projectPath: string, request: AdoVerbRequest) => Promise<unknown>
  function register(scriptsDir: string | null) {
    const handlers = new Map<string, Handler>()
    const ipcMain = { handle: vi.fn((channel: string, h: Handler) => { handlers.set(channel, h) }) }
    registerAdoIpc(ipcMain as never, async () => scriptsDir)
    return { handlers, ipcMain }
  }

  it('registers exactly one channel, the write path, and no read channel (reads ride getCommandCenter)', () => {
    const { handlers, ipcMain } = register(SCRIPTS)
    expect(ADO_VERB_CHANNEL).toBe('studio:runAdoVerb')
    expect(ipcMain.handle).toHaveBeenCalledTimes(1)
    expect([...handlers.keys()]).toEqual(['studio:runAdoVerb'])
  })

  it('resolves the actor and the capabilities in main, then runs one spawn', async () => {
    vi.mocked(resolveActor).mockResolvedValue(ACTOR)
    vi.mocked(getCapabilities).mockResolvedValue(['ado-comment'])
    run.mockResolvedValue(entry(0, '{}'))
    const { handlers } = register(SCRIPTS)
    const r = await handlers.get(ADO_VERB_CHANNEL)!({}, PROJECT, { verb: 'comment', ref: REF, message: 'hi' })
    expect(resolveActor).toHaveBeenCalledWith(PROJECT, SCRIPTS)
    expect(getCapabilities).toHaveBeenCalledWith(PROJECT, SCRIPTS)
    expect(run).toHaveBeenCalledTimes(1)
    expect(r).toMatchObject({ ok: true, exitCode: 0, verb: 'comment' })
  })

  it('--by is always the main-resolved actor: a `by` or `actor` the renderer adds is never read', async () => {
    vi.mocked(resolveActor).mockResolvedValue(ACTOR)
    vi.mocked(getCapabilities).mockResolvedValue(['ado-comment'])
    run.mockResolvedValue(entry(0, '{}'))
    const { handlers } = register(SCRIPTS)
    const sneaky = { verb: 'comment', ref: REF, message: 'hi', by: '@someone-else', actor: '@someone-else', argv: ['--by', '@someone-else'] } as unknown as AdoVerbRequest
    await handlers.get(ADO_VERB_CHANNEL)!({}, PROJECT, sneaky)
    const argv = run.mock.calls[0]![2]
    expect(argv.slice(-2)).toEqual(['--by', '@priya-n'])
    expect(argv.join(' ')).not.toContain('@someone-else')
  })

  it('with no identified person nothing is spawned and the answer is NO_ACTOR', async () => {
    vi.mocked(resolveActor).mockResolvedValue(null)
    vi.mocked(getCapabilities).mockResolvedValue(['ado-apply'])
    const { handlers } = register(SCRIPTS)
    const r = await handlers.get(ADO_VERB_CHANNEL)!({}, PROJECT, { verb: 'apply', confirm: HASH })
    expect(r).toMatchObject({ ok: false, exitCode: null, stderr: NO_ACTOR }); expect(run).not.toHaveBeenCalled()
  })

  it('a plugin without the capability is refused with newerPlugin(cap), nothing spawned', async () => {
    vi.mocked(resolveActor).mockResolvedValue(ACTOR)
    vi.mocked(getCapabilities).mockResolvedValue(['ado-status-json'])
    const { handlers } = register(SCRIPTS)
    const r = await handlers.get(ADO_VERB_CHANNEL)!({}, PROJECT, { verb: 'apply', confirm: HASH })
    expect(r).toMatchObject({ ok: false, exitCode: null, stderr: newerPlugin('ado-apply') }); expect(run).not.toHaveBeenCalled()
  })

  it('no plugin scripts folder answers PLUGIN_NOT_FOUND without resolving anyone', async () => {
    const { handlers } = register(null)
    const r = await handlers.get(ADO_VERB_CHANNEL)!({}, PROJECT, { verb: 'pull' })
    expect(r).toMatchObject({ ok: false, exitCode: null, stderr: PLUGIN_NOT_FOUND })
    expect(resolveActor).not.toHaveBeenCalled(); expect(run).not.toHaveBeenCalled()
  })
})

describe('the files that wire it', () => {
  const read = (...p: string[]) => readFileSync(join(MAIN, ...p), 'utf-8')
  /** Code without its comments, so a comment that says what the file avoids does not trip a check on code. */
  const code = (src: string) => src.replace(/\/\*[\s\S]*?\*\//g, '').split(/\r?\n/).map((l) => l.replace(/(^|\s)\/\/.*$/, '')).join('\n')

  it('adoWrites.ts takes PLUGIN_NOT_FOUND from shared/pluginId and says Shepherd, never the old product name', () => {
    const src = read('adoWrites.ts')
    expect(src).toMatch(/import \{[^}]*\bPLUGIN_NOT_FOUND\b[^}]*\} from '\.\.\/\.\.\/shared\/pluginId'/)
    expect(code(src)).not.toMatch(/claude-code-sdlc|SDLC Studio|sdlc-studio/i)
    expect(code(src)).toContain('Shepherd')
  })

  it('neither file can spawn a shell or reach az: the only spawn is runPluginScript', () => {
    for (const file of ['adoWrites.ts', 'adoIpc.ts']) {
      const src = code(read(file))
      expect(src, file).not.toMatch(/child_process|\bspawn\(|\bexec\(|execFile|shell\s*:/)
      expect(src, file).not.toMatch(/['"`]az['"`]/)
      expect(src, file).not.toMatch(/\.join\(\s*' '\s*\)/)
    }
  })

  it('index.ts takes exactly two lines for this: the import and the call', () => {
    const lines = read('index.ts').split(/\r?\n/).filter((l) => l.includes('registerAdoIpc'))
    expect(lines).toHaveLength(2)
    expect(lines.some((l) => /^import \{ registerAdoIpc \} from '\.\/adoIpc'/.test(l))).toBe(true)
    expect(lines.some((l) => /^\s*registerAdoIpc\(ipcMain, resolvePluginScriptsDir\)/.test(l))).toBe(true)
  })

  it('the preload exposes runAdoVerb as a pass-through on the channel main registers', () => {
    const preload = readFileSync(resolve(MAIN, '..', 'preload', 'index.ts'), 'utf-8')
    expect(preload).toContain(`runAdoVerb: (projectPath, request) => ipcRenderer.invoke('${ADO_VERB_CHANNEL}', projectPath, request)`)
    expect(preload.match(/studio:\w*Ado\w*/g)).toEqual([ADO_VERB_CHANNEL])
  })
})
