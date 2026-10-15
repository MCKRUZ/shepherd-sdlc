/** G18 — nothing reads the board on its own (build kit §7 and guardrails 26 and 28; owner decision 2026-10-15: no read
 * on project open, a staleness line and a button instead).
 *
 * Two halves. The RUNTIME half drives main's real `studio:openProject` handler (the one `index.ts` registers, with
 * `electron` and the model-free neighbours faked) and the command center's own read (`studio:getCommandCenter`, the
 * prefetch the open starts, the renderer's refresh) over a fake plugin, and holds every `ado_sync.py` spawn to exactly
 * `status <source> --json` — never `pull`, `plan`, `show`, `comment`, `apply`, `reconcile` or `link`, even when the
 * plugin declares every Boards capability, and not in a day of the open-project timer either. The SOURCE half holds the
 * renderer to the same line: every `runAdo(` / `runAdoVerb(` call site under `studio/src` lies under
 * `studio/src/components/ado/`, and no `useEffect` in the screens that mount the Boards controls names a Boards
 * request.
 *
 * Nothing here is live: `runCommand` is the only spawn seam faked, so the real `openProject`, `runPluginScript` and
 * `getCommandCenter` all run, and no `az`, `uv` or `git` is started. */
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, join, relative, resolve } from 'node:path'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'

const fake = vi.hoisted(() => {
  const handlers = new Map<string, (event: unknown, ...args: unknown[]) => unknown>()
  const state = { userData: '' }
  const window = () => ({
    webContents: { on() {}, setZoomFactor() {}, openDevTools() {}, setWindowOpenHandler() {}, send() {} },
    on() {}, loadURL() {}, loadFile() {}, isDestroyed: () => false, isMinimized: () => false, isFullScreen: () => false,
    getNormalBounds: () => ({ x: 0, y: 0, width: 1280, height: 800 }), getContentBounds: () => ({ x: 0, y: 0, width: 1280, height: 800 }),
  })
  const display = { workArea: { x: 0, y: 0, width: 1920, height: 1080 } }
  return {
    handlers,
    state,
    electron: {
      app: {
        requestSingleInstanceLock: () => true, getName: () => 'Shepherd', setAppUserModelId() {}, disableHardwareAcceleration() {},
        on() {}, whenReady: () => Promise.resolve(), getPath: () => state.userData, quit() {}, isPackaged: false,
      },
      BrowserWindow: Object.assign(function BrowserWindow() { return window() }, { getAllWindows: () => [] }),
      dialog: {},
      ipcMain: { handle: (channel: string, fn: (event: unknown, ...args: unknown[]) => unknown) => { handlers.set(channel, fn) }, on() {}, once() {} },
      screen: { getAllDisplays: () => [display], getPrimaryDisplay: () => display },
      shell: {},
    },
  }
})

vi.mock('electron', () => fake.electron)
vi.mock('../../electron/main/commandRunner', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../electron/main/commandRunner')>()),
  runCommand: vi.fn(),
}))
vi.mock('../../electron/main/tooling', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../electron/main/tooling')>()),
  detectAllTooling: vi.fn(async () => ({
    claude: { found: false }, uv: { found: false }, pluginScripts: { found: true, path: '/plugin/scripts' },
    git: { found: false }, gh: { found: false }, az: { found: false },
  })),
}))
vi.mock('../../electron/main/sync', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../electron/main/sync')>()),
  pull: vi.fn(async () => ({ ok: true })),
  pollAndMergeOpenPullRequest: vi.fn(async () => undefined),
}))

import { runCommand } from '../../electron/main/commandRunner'
import { pollAndMergeOpenPullRequest, pull } from '../../electron/main/sync'
import { getCommandCenter, invalidateCommandCenter, prefetchCommandCenter } from '../../electron/main/commandCenter'
import { ADO_VERBS } from '../../shared/adoVerbArgv'
import { CAPABILITIES } from '../../shared/reasons'
import type { ConsoleEntry } from '../../shared/types'

const run = vi.mocked(runCommand)
const SCRIPTS = '/plugin/scripts'
const STUDIO = resolve(__dirname, '..', '..')
const GOLDEN = resolve(STUDIO, '..', 'scripts', 'tests', 'golden', 'ado_status_nodata.json')
const NODATA = readFileSync(GOLDEN, 'utf-8')

const entry = (stdout: string, exitCode = 0, stderr = ''): ConsoleEntry => ({ id: 'x', command: 'py', args: [], cwd: '', startedAt: '', durationMs: 0, exitCode, stdout, stderr, ok: exitCode === 0 })

/** Every Boards capability the plugin declares, plus the sprint reads: the loudest plugin a project can have. */
const EVERY_CAPABILITY = [
  'sprint-status', 'sprint-list', 'sprint-log', CAPABILITIES.adoStatus, CAPABILITIES.adoApply, CAPABILITIES.adoReconcile, CAPABILITIES.adoShow,
  CAPABILITIES.adoComment, CAPABILITIES.adoDiscussion, 'ado-pull', 'ado-plan', 'ado-link',
]

let project = ''
let userData = ''
let statePath = ''

/** The plugin script a spawn names and the arguments after it, whichever interpreter form `runPluginScript` used
 * (`<venv python> <script> …` or `uv run --project <dir> <script> …`). */
function scriptSpawn(args: readonly string[]): { script: string; rest: string[] } | null {
  const at = args.findIndex((a) => /\.py$/.test(a))
  return at < 0 ? null : { script: basename(args[at]!), rest: args.slice(at + 1) }
}
const adoSpawns = () => run.mock.calls.map(([, args]) => scriptSpawn(args)).filter((s): s is { script: string; rest: string[] } => s !== null && s.script === 'ado_sync.py')
const STATUS_ARGS = () => ['status', '--state', statePath, '--json']

/** Answers each plugin script the way a plugin with every Boards capability would; anything else is a plain failure. */
function plugin() {
  run.mockReset()
  run.mockImplementation(async (_command, args) => {
    const spawn = scriptSpawn(args)
    switch (spawn?.script) {
      case 'generate_status.py':
        return entry(JSON.stringify({ project_name: 'demo', profile_id: 'p', current_phase: { id: 'build', display: 'Build' }, stages: [], capabilities: EVERY_CAPABILITY }))
      case 'ado_sync.py': return entry(NODATA)
      default: return entry('', 1, 'not answered by this fake')
    }
  })
}

/** Wait for `cond` with a REAL timer (only `setInterval` is faked below), so a read that is still settling is not a flake. */
async function until(cond: () => boolean, what: string): Promise<void> {
  for (let i = 0; i < 400; i++) {
    if (cond()) return
    await new Promise((r) => setTimeout(r, 5))
  }
  throw new Error(`timed out waiting for ${what}`)
}

beforeAll(async () => {
  userData = mkdtempSync(join(tmpdir(), 'no-open-ado-ud-'))
  project = mkdtempSync(join(tmpdir(), 'no-open-ado-'))
  mkdirSync(join(project, '.sdlc'))
  statePath = join(project, '.sdlc', 'state.yaml')
  writeFileSync(statePath, 'current_phase: build\n')
  fake.state.userData = userData
  plugin()
  // The open-project timer is an interval: faked from the start so a day of it can be run, and so it never outlives the file.
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  await import('../../electron/main/index')
  await until(() => fake.handlers.has('studio:openProject') && fake.handlers.has('studio:getCommandCenter'), 'main to register its handlers')
})
afterAll(() => {
  vi.useRealTimers()
  rmSync(project, { recursive: true, force: true })
  rmSync(userData, { recursive: true, force: true })
})

const handler = (channel: string) => fake.handlers.get(channel)!

describe('the runtime half: main spawns the board only to read its status', () => {
  it('opening a project (the real studio:openProject) starts the command-center prefetch, and its one ado_sync.py spawn is `status <source> --json`', async () => {
    plugin()
    invalidateCommandCenter(project, 'all')
    const result = await handler('studio:openProject')({}, project) as { hasProject: boolean; status?: { project_name: string } }
    expect(result.hasProject).toBe(true)
    expect(result.status?.project_name).toBe('demo')
    // the open ran for real: it pulled the repository (faked) and read generate_status, and it warmed the read model
    expect(vi.mocked(pull)).toHaveBeenCalled()
    await until(() => adoSpawns().length > 0, 'the prefetch to read the Boards status')
    // let the whole fan-out settle (the renderer's own first read joins it), so a late spawn would be seen here
    await handler('studio:getCommandCenter')({}, project)
    const spawns = adoSpawns()
    expect(spawns.length).toBeGreaterThan(0)
    for (const spawn of spawns) expect(spawn.rest).toEqual(STATUS_ARGS())
    expect(new Set(spawns.map((s) => s.rest[0]))).toEqual(new Set(['status']))
  })

  it('no ado_sync.py verb is ever pull, plan, show, comment, apply, reconcile or link — whatever the plugin declares it can do', async () => {
    plugin()
    invalidateCommandCenter(project, 'all')
    await handler('studio:openProject')({}, project)
    await handler('studio:getCommandCenter')({}, project, 1, true)
    await handler('studio:getCommandCenter')({}, project, 3, true)
    const verbs = new Set(adoSpawns().map((s) => s.rest[0]))
    expect(verbs).toEqual(new Set(['status']))
    for (const verb of ADO_VERBS) expect(verbs.has(verb === 'pullDiscussion' ? 'pull' : verb), verb).toBe(false)
    // and not through the discussion flag either, which rides `pull`
    expect(adoSpawns().every((s) => !s.rest.includes('--discussion') && !s.rest.includes('--kind') && !s.rest.includes('--sprint'))).toBe(true)
  })

  it('the command center\'s own read and the prefetch it shares do the same, with and without a refresh', async () => {
    plugin()
    invalidateCommandCenter(project, 'all')
    await prefetchCommandCenter(project, SCRIPTS)
    await getCommandCenter(project, SCRIPTS, 1)
    await getCommandCenter(project, SCRIPTS, 1, { refresh: true })
    invalidateCommandCenter(project)
    await getCommandCenter(project, SCRIPTS, 3)
    expect(adoSpawns().length).toBeGreaterThan(0)
    for (const spawn of adoSpawns()) expect(spawn.rest).toEqual(STATUS_ARGS())
  })

  it('a day of the open-project timer (it pulls the repository, not the board) spawns no Boards verb', async () => {
    plugin()
    await handler('studio:openProject')({}, project)
    await handler('studio:getCommandCenter')({}, project)
    const before = adoSpawns().length
    vi.mocked(pull).mockClear()
    vi.mocked(pollAndMergeOpenPullRequest).mockClear()
    await vi.advanceTimersByTimeAsync(24 * 60 * 60 * 1000)
    // the timer did run (120 s, so hundreds of times) — and it is the repository it pulls
    expect(vi.mocked(pull).mock.calls.length).toBeGreaterThan(100)
    expect(adoSpawns().length).toBe(before)
    for (const spawn of adoSpawns()) expect(spawn.rest).toEqual(STATUS_ARGS())
  })
})

// ── the source half ──────────────────────────────────────────────────────────────────────────────

const SRC = join(STUDIO, 'src')
function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.tsx?$/.test(name)) out.push(full)
  }
  return out
}
/** Comments removed first: the files say in prose what they never do. */
const code = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, '').split(/\r?\n/).map((l) => l.replace(/(^|\s)\/\/.*$/, '')).join('\n')
const rel = (file: string) => relative(STUDIO, file).split('\\').join('/')

/** The argument text of every `name(` call in `source`, parentheses balanced and string contents skipped. */
function callBodies(source: string, name: string): string[] {
  const bodies: string[] = []
  const re = new RegExp(`\\b${name}\\(`, 'g')
  for (let m = re.exec(source); m; m = re.exec(source)) {
    let depth = 1
    let i = m.index + m[0].length
    const start = i
    let quote: string | null = null
    for (; i < source.length && depth > 0; i++) {
      const c = source[i]!
      if (quote) {
        if (c === '\\') i++
        else if (c === quote) quote = null
      } else if (c === '\'' || c === '"' || c === '`') quote = c
      else if (c === '(') depth++
      else if (c === ')') depth--
    }
    bodies.push(source.slice(start, i - 1))
  }
  return bodies
}

/** A Boards request object literal — `verb: 'plan'` and its seven siblings. The sprint verbs (`verb: 'handoff'`) are not these. */
const BOARDS_REQUEST = /verb:\s*'(apply|reconcile|link|pull|pullDiscussion|show|comment|plan)'/

describe('the source half: every Boards spawn in the renderer lies under components/ado/', () => {
  const files = walk(SRC)

  it('every runAdo( / runAdoVerb( call site under studio/src is a file under studio/src/components/ado/', () => {
    const sites = files.filter((f) => /\brunAdo(Verb)?\(/.test(code(readFileSync(f, 'utf-8')))).map(rel)
    // not vacuous: the controls that exist today are found
    for (const known of ['PullNow', 'PlanChanges', 'CommentComposer', 'AdoApplyDialog', 'AdoReconcileDialog', 'DiscussionBlock']) {
      expect(sites, known).toContain(`src/components/ado/${known}.tsx`)
    }
    expect(sites.filter((f) => !f.startsWith('src/components/ado/'))).toEqual([])
  })

  it('the screens that mount the controls — and the shell — never name a Boards request themselves', () => {
    for (const file of ['src/App.tsx', 'src/components/SpecCard/SpecCard.tsx', 'src/components/today/TodayColumn.tsx', 'src/components/LifecycleHome.tsx']) {
      const body = code(readFileSync(join(STUDIO, file), 'utf-8'))
      expect(body, file).not.toMatch(/\brunAdo(Verb)?\(/)
      expect(body, file).not.toMatch(BOARDS_REQUEST)
      expect(body, file).not.toMatch(/window\.studio\.runAdoVerb|studio\.runAdoVerb/)
    }
  })

  it('no useEffect or useLayoutEffect in those screens, or in the Boards controls, names a Boards request or its component', () => {
    const targets = [
      'src/App.tsx', 'src/components/SpecCard/SpecCard.tsx', 'src/components/today/TodayColumn.tsx', 'src/components/LifecycleHome.tsx',
      'src/components/ado/PlanChanges.tsx', 'src/components/ado/CatchUp.tsx', 'src/components/ado/BoardsNudge.tsx', 'src/components/ado/PullNow.tsx',
    ]
    const named = new RegExp(`\\b(runAdo|runAdoVerb|PlanChanges|CatchUp|BoardsNudge|PullNow)\\b|${BOARDS_REQUEST.source}|['"\`](plan|pull)['"\`]`)
    for (const file of targets) {
      const body = code(readFileSync(join(STUDIO, file), 'utf-8'))
      for (const hook of ['useEffect', 'useLayoutEffect']) {
        for (const effect of callBodies(body, hook)) expect(effect, `${file} ${hook}`).not.toMatch(named)
      }
    }
    // the scanner is not blind: it finds the effects that DO exist
    expect(callBodies(code(readFileSync(join(STUDIO, 'src/App.tsx'), 'utf-8')), 'useEffect').length).toBeGreaterThan(2)
    expect(callBodies('useEffect(() => { a(b) }, [c])', 'useEffect')).toEqual(['() => { a(b) }, [c]'])
    expect(callBodies('useEffect(() => { go(\'plan)\') }, [])', 'useEffect')[0]).toMatch(/plan/)
  })

  it('the open path and the status refresh hold no Boards verb: the project opens without reading the board', () => {
    const app = code(readFileSync(join(STUDIO, 'src/App.tsx'), 'utf-8'))
    const open = app.slice(app.indexOf('const openPath = useCallback'), app.indexOf('const handlePickFolder'))
    const refresh = app.slice(app.indexOf('const refreshStatus = useCallback'), app.indexOf('const refreshCommandCenter = useCallback'))
    expect(open.length).toBeGreaterThan(200)
    expect(refresh.length).toBeGreaterThan(100)
    for (const region of [open, refresh]) expect(region).not.toMatch(/runAdo|AdoVerb|BoardsNudge|PlanChanges|CatchUp|setBoardsNudge/)
    // main's open handler names no Boards script either
    const main = code(readFileSync(join(STUDIO, 'electron/main/index.ts'), 'utf-8'))
    const handlerAt = main.indexOf('ipcMain.handle(\'studio:openProject\'')
    const handlerBody = main.slice(handlerAt, main.indexOf('ipcMain.handle(\'studio:listProfiles\''))
    expect(handlerBody.length).toBeGreaterThan(200)
    expect(handlerBody).not.toMatch(/ado_sync|runAdoVerb|AdoVerb|\bado\b/i)
  })
})
