// Production-mode screenshots of the Observatory on a RICH fixture — NOT a spec. Unlike
// capture-observatory.mjs this builds with `npx vite build` (production: motion on, the Ambient
// field enabled, the Graph surface the default) and walks a Build-loop project with a real sprint,
// verdicts, an open hand-off, a decision clock owned by the signed-in person, a merged spec, a
// deferred spec with its reason, a not-ready backlog spec, a roster and a local bare origin (so
// the Sync chip is not an error). Run from studio/:
//
//   node test/screenshots/capture-observatory-v2.mjs            # builds first
//   SKIP_BUILD=1 node test/screenshots/capture-observatory-v2.mjs  # reuse dist/
//   SHOT_PREFIX=observatory-v11 node test/screenshots/capture-observatory-v2.mjs  # a new series
//   SHOT_SETTLE=1800 …                                                 # longer settle per shot (ms)
//   SHOT_SCALE=2 …                                                     # 2× device pixels (for the guide's images)
//
// Writes test/screenshots/<prefix>-<name>.png (prefix defaults to observatory-v2) and prints DPR +
// canvas size for sprint-graph. The v8 run (studio-upgrade-2 §4 P7) added five shots to the twelve
// (`welcome-dark`, `spec-view-dark`, `palette-dark`, `settings-dark`, `closing`). The v11 run
// (togo-command-center.md §7 P8) adds eight more and walks the command center: `sprint-home`,
// `sprint-home-dark`, `planning`, `spec-card`, `lifecycle-home`, `review`, `steering`, `omnibar`.
// Twenty-five files per run. The fixture's signed-in person is whoever `gh api user` says on this
// machine (added to the roster so the "you" ring and the needs-you chip have someone to address);
// without a login the decision is owned by a named human and nothing is addressed.
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { inflateSync } from 'node:zlib'
import { fileURLToPath } from 'node:url'
import { _electron as electron } from '@playwright/test'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..', '..')
const PLUGIN_ROOT = process.env.SDLC_PLUGIN_ROOT ?? resolve(root, '..')
const SCRIPTS_DIR = join(PLUGIN_ROOT, 'scripts')
const VENV_PYTHON = process.platform === 'win32'
  ? join(SCRIPTS_DIR, '.venv', 'Scripts', 'python.exe')
  : join(SCRIPTS_DIR, '.venv', 'bin', 'python')
const SETTLE = Number(process.env.SHOT_SETTLE ?? 1_200)
const PREFIX = process.env.SHOT_PREFIX ?? 'observatory-v2'
// Q5 cockpit QA (the owner's v12 critique, items 1, 6, 7). SHOT_WIDTHS="1280x800,1440x900,1680x1000"
// (default 1440x900): after the walk, each width revisits sprint-home, planning, spec-card and
// lifecycle-home in light and dark and writes <prefix>-<name>[-dark]@<w>.png (w = the width).
// SHOT_OVERLAP=1: after EVERY shot, measure the landmarks' boxes — band, strip, <main>, both asides,
// the lane board and each lane, Today, the sprint header, any dialog — and assert each sits inside
// the viewport (waived for <main>'s children while <main> is deliberately scrolled), that no two
// intersect unintentionally (containment is fine; lanes never touch each other or Today; the chat
// aside never overlaps <main>; a dialog may overlay) and that the ROOT never scrolls (only <main>
// does). Prints PROBE OVERLAP lines; a violation sets exit code 3. The same probe runs in
// Playwright: test/e2e/cc/overlap.spec.ts (`measureLandmarks` — the two bodies are kept in step by
// hand, since an .mjs cannot import a .ts).
const WIDTHS = (process.env.SHOT_WIDTHS ?? '1440x900').split(',').map((s) => s.trim()).filter(Boolean).map((s) => {
  const [w, h] = s.split('x').map(Number)
  if (!w || !h) throw new Error(`SHOT_WIDTHS: "${s}" is not <width>x<height>`)
  return { w, h }
})
const OVERLAP = process.env.SHOT_OVERLAP === '1'
const overlapViolations = []
// SHOT_PROBE=ghost (studio-upgrade-2 §4 P3 / C4-A2): instead of the walk, open Sprint on the GRAPH
// surface WITHOUT moving the pointer afterwards, capture the 25 px band above the Sprint header at
// 1.2 / 1.6 / 2.0 / 2.5 s and report the max per-channel deviation from `surface-0` per capture
// (ghost = any pixel row deviating > 8/255). GHOST_BISECT=<n> adds ONE style rule before the
// navigation so the cause can be named from evidence rather than guessed:
//   1 `[data-reveal]` transform:none / opacity:1   — kills the row stagger
//   2 the slate scroller overflow:visible          — the scroll box
//   3 the sticky header position:static            — sticky layer promotion
//   4 the band display:none                        — the band (a `::before` before the fix, a real
//                                                    `[data-stuck-band]` element after it)
//   5 TABLE surface (the prior said "known clean"; the probe showed the canvas was NOT necessary)
// Verdict and numbers: the header comment of `src/components/useStuck.ts`. The Sprint header is
// the `PageHeader` at the top of the screen since S7, found by its `h2[data-page-heading]`.
// GHOST_TARGET=board runs the same measurement on the Board's filter bar — a sticky header that
// sits MID-page (under the notice and the team chips), so the fix is shown to hold where the band
// has content above it, not only at the top of the screen where the Sprint header now lives.
const PROBE = process.env.SHOT_PROBE ?? null
const GHOST_TARGET = process.env.GHOST_TARGET === 'board' ? 'board' : 'sprint'
const GHOST_BISECT = Number(process.env.GHOST_BISECT ?? 0)
const GHOST_TIMES_MS = [1_200, 1_600, 2_000, 2_500]
const GHOST_THRESHOLD = 8
const GHOST_BISECT_CSS = {
  1: '[data-reveal]{transform:none!important;opacity:1!important}',
  2: '[aria-label="Sprint slate, scrolls sideways"]{overflow:visible!important}',
  3: 'main header[class*="sticky"],[data-testid="sprint-board"]>div:first-child{position:static!important}',
  4: '[data-stuck-band],[data-testid="sprint-board"]>div:first-child::before{display:none!important}',
}

if (!existsSync(VENV_PYTHON)) throw new Error(`no plugin venv at ${VENV_PYTHON} — run the plugin's pytest once to build it`)
if (!process.env.SKIP_BUILD) {
  execFileSync('npx', ['vite', 'build'], { cwd: root, stdio: 'inherit' }) // PRODUCTION mode on purpose
}
if (!existsSync(join(root, 'dist', 'index.html'))) throw new Error('no dist/ — the production build did not land')

const failures = []
const py = (label, args) => {
  try { execFileSync(VENV_PYTHON, args, { cwd: SCRIPTS_DIR, stdio: 'pipe' }) }
  catch (e) { failures.push(`${label}: ${String(e.stderr ?? e.stdout ?? e.message).trim().split('\n').slice(-3).join(' | ')}`) }
}
const git = (args, cwd) => execFileSync('git', args, { cwd, stdio: 'pipe' })
const shot = async (page, name) => {
  await page.screenshot({ path: join(here, `${PREFIX}-${name}.png`) })
  if (OVERLAP) await probeOverlap(page, name)
}
const settle = async (page, ms = SETTLE) => page.waitForTimeout(ms)

/** Runs INSIDE the page. The twin of overlap.spec.ts's `measureLandmarks` — same body, kept in step by hand. */
function measureLandmarks() {
  const vw = window.innerWidth, vh = window.innerHeight, EPS = 1
  const boxes = []
  const add = (kind, el, name = kind) => {
    const r = el.getBoundingClientRect()
    if (r.width < 1 || r.height < 1 || getComputedStyle(el).visibility === 'hidden') return // hidden / collapsed: not on screen
    if (boxes.some((b) => b.el === el)) return // one element, one box: `today-rail` and `today` may resolve to the same section
    boxes.push({ name, kind, el, left: r.left, top: r.top, right: r.right, bottom: r.bottom })
  }
  const one = (kind, sel) => { const el = document.querySelector(sel); if (el) add(kind, el) }
  const all = (kind, sel, name) => document.querySelectorAll(sel).forEach((el, i) => add(kind, el, name(el, i)))
  one('top-band', '[data-testid="top-band"]')
  one('lifecycle-strip', '[data-testid="lifecycle-strip"]')
  one('shell-band', '[data-testid="shell-band"]')
  one('main', 'main#main')
  all('aside', 'aside', (el, i) => `aside[${i}]${el.getAttribute('data-testid') ? ` ${el.getAttribute('data-testid')}` : ''}`)
  one('lane-board', '[data-testid="lane-board"]')
  all('lane', '[data-testid^="lane-"][data-lane]:not([data-testid="lane-card"])', (el) => el.getAttribute('data-testid') ?? 'lane')
  one('today-rail', '[data-today-rail]')
  one('today', '[data-testid="today"]')
  one('sprint-header', '[data-testid="sprint-header"]')
  all('dialog', '[role="dialog"]', (_el, i) => `dialog[${i}]`)

  const fmt = (b) => `${b.name} [${Math.round(b.left)},${Math.round(b.top)} → ${Math.round(b.right)},${Math.round(b.bottom)}]`
  const violations = []
  const main = document.getElementById('main')
  const mainScrollTop = main?.scrollTop ?? 0
  for (const b of boxes) {
    const inScrolledMain = mainScrollTop > 0 && b.kind !== 'main' && b.kind !== 'aside' && b.kind !== 'shell-band' && b.kind !== 'top-band' && b.kind !== 'lifecycle-strip'
    if (inScrolledMain) continue
    if (b.left < -EPS || b.top < -EPS || b.right > vw + EPS || b.bottom > vh + EPS) violations.push(`outside the ${vw}×${vh} viewport: ${fmt(b)}`)
  }
  const contains = (a, b) => a.left <= b.left + EPS && a.top <= b.top + EPS && a.right >= b.right - EPS && a.bottom >= b.bottom - EPS
  const depth = (a, b) => Math.min(Math.min(a.right, b.right) - Math.max(a.left, b.left), Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top))
  const STRICT = new Set(['lane|lane', 'lane|today', 'lane|today-rail', 'aside|main'])
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const a = boxes[i], b = boxes[j]
      if (a.kind === 'dialog' || b.kind === 'dialog') continue
      const d = depth(a, b)
      if (d <= EPS) continue
      const key = [a.kind, b.kind].sort().join('|')
      if (STRICT.has(key)) { violations.push(`intersect ${Math.round(d)} px: ${fmt(a)} ∩ ${fmt(b)}`); continue }
      // A DOM descendant spilling past its ancestor's box is overflow, already reported by the viewport rule above.
      if (a.el.contains(b.el) || b.el.contains(a.el)) continue
      if (!contains(a, b) && !contains(b, a)) violations.push(`partial overlap ${Math.round(d)} px: ${fmt(a)} ∩ ${fmt(b)}`)
    }
  }
  const root = document.scrollingElement ?? document.documentElement
  if (root.scrollTop !== 0 || root.scrollLeft !== 0) violations.push(`the root is scrolled (top ${root.scrollTop}, left ${root.scrollLeft}) — only <main> may scroll`)
  if (root.scrollHeight > vh + EPS || root.scrollWidth > vw + EPS) {
    // Name what grows the document: elements reaching past the viewport with NO clipping or
    // scrolling ancestor below <html> (an ancestor that clips would have absorbed the overflow).
    // Only a SCROLLING ancestor absorbs overflow for this purpose: `overflow: hidden` on <body> or
    // #root does not stop an absolutely positioned portal child (containing block = the viewport)
    // from growing the document, and a zero-height box can still sit past the edge.
    const clips = (el) => /(auto|scroll)/.test(getComputedStyle(el).overflow)
    const culprits = []
    for (const el of Array.from(document.querySelectorAll('body *'))) {
      const r = el.getBoundingClientRect()
      if (r.bottom <= vh + EPS && r.right <= vw + EPS) continue
      let p = el.parentElement, clipped = false
      while (p && p !== document.documentElement) { if (clips(p)) { clipped = true; break } p = p.parentElement }
      if (clipped) continue
      const pos = getComputedStyle(el).position
      const cls = (el.getAttribute('class') ?? '').split(/\s+/).slice(0, 4).join(' ')
      culprits.push(`${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ''}${el.getAttribute('data-testid') ? `[${el.getAttribute('data-testid')}]` : ''}${cls ? ` .${cls}` : ''} ${pos} [${Math.round(r.left)},${Math.round(r.top)} → ${Math.round(r.right)},${Math.round(r.bottom)}] in ${el.parentElement?.tagName.toLowerCase()}${el.parentElement?.id ? `#${el.parentElement.id}` : ''}`)
      if (culprits.length >= 4) break
    }
    violations.push(`the root overflows its ${vw}×${vh} viewport (${root.scrollWidth}×${root.scrollHeight}) — the shell must never scroll${culprits.length ? `; unclipped past the edge: ${culprits.join(' · ')}` : ''}`)
  }
  const theme = document.documentElement.getAttribute('data-theme') ?? 'light'
  return { viewport: `${vw}x${vh}`, theme, mainScrollTop, landmarks: boxes.map(fmt), violations }
}

/** One PROBE OVERLAP line per violation (or one "ok" line); a violation is exit code 3 at the end. */
async function probeOverlap(page, name) {
  const r = await page.evaluate(measureLandmarks)
  const head = `PROBE OVERLAP ${name} ${r.viewport} ${r.theme}${r.mainScrollTop > 0 ? ` (main scrolled ${Math.round(r.mainScrollTop)} px — viewport rule waived inside it)` : ''}`
  if (r.violations.length === 0) { console.log(`${head}: ok — ${r.landmarks.length} landmarks`); return }
  for (const v of r.violations) console.log(`${head}: ${v}`)
  overlapViolations.push(`${name} ${r.viewport} ${r.theme}: ${r.violations.length} violation(s)`)
  process.exitCode = 3
}

/** Replace one frontmatter line in place (`key: …` → `key: "value"`), everything else untouched. */
const setFm = (file, key, value) => {
  const text = readFileSync(file, 'utf-8')
  const re = new RegExp(`^${key}:.*$`, 'm')
  if (!re.test(text)) { failures.push(`frontmatter ${key} missing in ${file}`); return }
  writeFileSync(file, text.replace(re, `${key}: "${value}"`))
}

// --- fixture: bare origin + clone, six specs, a sprint with verdicts and a hand-off ------------
const workspace = mkdtempSync(join(tmpdir(), 'studio-shots-v2-'))
const origin = join(workspace, 'origin.git')
const project = join(workspace, 'project')
git(['init', '--bare', '--initial-branch=main', origin], workspace)
git(['clone', origin, project], workspace)
git(['config', 'user.email', 'studio-shots@example.com'], project)
git(['config', 'user.name', 'Studio Shots'], project)

const sprintPy = join(SCRIPTS_DIR, 'sprint.py')
py('init_project', [join(SCRIPTS_DIR, 'init_project.py'), '--profile', join(PLUGIN_ROOT, 'profiles', 'microsoft-enterprise', 'profile.yaml'), '--target', project])
// The project is IN the Build loop (homeFor → the sprint home); the same edit every Build e2e fixture makes.
const statePath = join(project, '.sdlc', 'state.yaml')
writeFileSync(statePath, readFileSync(statePath, 'utf-8').replace(/^current_phase:.*$/m, 'current_phase: "build"').replace(/^phase_name:.*$/m, 'phase_name: "Build"'))

const SPECS = [
  ['duplicate claim 409', 'HIGH'], ['claim export', 'MEDIUM'], ['adjuster notes', 'LOW'],
  ['fraud score feed', 'MEDIUM'], ['letters batch', 'LOW'], ['payments ledger', 'HIGH'], ['claims letters i18n', 'LOW'],
]
for (const [name, risk] of SPECS) {
  py(`new_spec ${name}`, [join(SCRIPTS_DIR, 'new_spec.py'), '--repo', project, '--name', name, '--risk', risk, '--owner', '@priya-n', '--team', 'claims'])
}
const specFiles = Object.fromEntries(readdirSync(join(project, 'specs')).filter((f) => /^\d{4}-/.test(f)).map((f) => [f.slice(0, 4), join(project, 'specs', f)]))
const ids = Object.keys(specFiles).sort()

/** The signed-in person on this machine, as the roster will know them. Null without a login. */
const me = (() => { try { return execFileSync('gh', ['api', 'user', '-q', '.login'], { stdio: 'pipe', encoding: 'utf-8' }).trim() || null } catch { return null } })()
const meHandle = me ? `@${me}` : null

/** A spec body that passes the Definition of Ready (the plugin test fixture's READY spec, with
 * this spec's id and name), so the Ready lane and "next up" have something true to show. */
const readyBody = (id, name, risk) => `
# Spec ${id} — ${name}

## Goal
A duplicate claim submission is rejected instead of double-processed.

## Why
Double-processed claims cause duplicate payouts and reconciliation work.

## Scope

### In scope
- \`src/Claims/ClaimsController.cs\`
- \`src/Claims/DuplicateGuard.cs\`

### Out of scope
- The payout pipeline under \`src/Payments/**\` — must not change.

## Acceptance Checks
- [ ] A duplicate submission returns 409 with body \`{ "error": "duplicate claim" }\`
- [ ] The first submission of an id returns 201 and persists one row
- [ ] Two concurrent submissions of the same id persist exactly 1 row

## Risk Tier
**Tier:** ${risk}
**Why this tier:** touches client claim data and the persistence path.

## Delegation Plan
- **Scope (file patterns):** \`src/Claims/**\`
- **Context (pattern to reuse):** the ClaimsController validation filter
- **Permissions:** build/test/lint auto; migrations confirm-required
- **Gated paths touched:** none

## Checking Plan
**Ladder depth:** ${risk}
**Specifics:** grader${risk === 'HIGH' ? ' + correctness + security pass + named sign-off in the PR' : risk === 'MEDIUM' ? ' + non-author Checker' : ' advisory + light human look'}.

## Decision List
- none
`
const makeReady = (id) => {
  const text = readFileSync(specFiles[id], 'utf-8')
  const end = text.indexOf('\n---', 4)
  const name = (text.match(/^name:\s*"?([^"\n]+)"?/m) ?? [])[1] ?? id
  const risk = (text.match(/^risk:\s*(\w+)/m) ?? [])[1] ?? 'LOW'
  writeFileSync(specFiles[id], text.slice(0, end + 4) + readyBody(id, name.trim(), risk))
  setFm(specFiles[id], 'harness_context', 'the ClaimsController validation filter')
}

// Roster: the plugin's example, plus @sam-k so the demo's developer resolves, plus the signed-in
// person so the needs-you chip and the "you" ring have someone to address.
const roster = readFileSync(join(PLUGIN_ROOT, 'templates', 'team', 'team.example.yaml'), 'utf-8')
  + '\n  - handle: "@sam-k"\n    name: "Sam Kowalski"\n    team: claims\n    roles: [developer, checker]\n    signs_off: ["build"]\n'
  + (meHandle ? `  - handle: "${meHandle}"\n    name: "${me}"\n    team: claims\n    roles: [owner, checker, lead]\n    signs_off: ["build"]\n` : '')
writeFileSync(join(project, '.sdlc', 'team.yaml'), roster)

// The sprint: S07, six slated (slate BEFORE the statuses — the plugin refuses to slate a merged spec).
py('sprint new', [sprintPy, 'new', '--repo', project, '--sprint', 'S07', '--goal', 'Adjusters file without a phone call',
  '--start', '2026-09-28', '--target', '6', '--mix', 'HIGH:2,MEDIUM:2,LOW:2', '--by', 'Pod Lead'])
py('sprint slate', [sprintPy, 'slate', '--repo', project, '--sprint', 'S07', '--by', 'Pod Lead', ...ids.slice(0, 5).flatMap((id) => ['--spec', id])])
const demo = {
  '0001': { status: 'merged' },
  '0002': { status: 'ready', depends_on: '0001' },
  '0003': { status: 'in-flight', developer: '@sam-k', checker: meHandle ?? '@priya-n', depends_on: '0001' },
  '0004': { status: 'in-flight', developer: '@priya-n', checker: '@sam-k' },
  '0005': { status: 'ready', depends_on: '0002, 0004' },
  '0006': { status: 'draft', depends_on: '0005' },
}
for (const [id, fields] of Object.entries(demo)) {
  if (!specFiles[id]) { failures.push(`spec ${id} was not created`); continue }
  for (const [k, v] of Object.entries(fields)) setFm(specFiles[id], k, v)
}
for (const id of ['0002', '0005']) if (specFiles[id]) makeReady(id)
for (const id of ['0001', '0002', '0004']) {
  py(`verdict eng ${id}`, [sprintPy, 'verdict', '--repo', project, '--spec', id, '--lane', 'eng', '--verdict', 'accepted', '--by', 'Eng Lead'])
  py(`verdict data ${id}`, [sprintPy, 'verdict', '--repo', project, '--spec', id, '--lane', 'data', '--verdict', 'n-a', '--reason', 'no new data', '--by', 'Data Lead'])
}
py('verdict eng 0005', [sprintPy, 'verdict', '--repo', project, '--spec', '0005', '--lane', 'eng', '--verdict', 'accepted', '--by', 'Eng Lead'])
py('handoff 0003', [sprintPy, 'handoff', '--repo', project, '--spec', '0003', '--to', '@sam-k', '--by', 'Pod Lead', '--note', 'take the notes spec next'])
// A deferral with its reason, through the verb that records it.
if (specFiles['0007']) py('defer 0007', [join(SCRIPTS_DIR, 'spec_transition.py'), '--spec', specFiles['0007'], 'defer', '--reason', 'the letters vendor ships its locale pack next quarter'])
// Decision clocks: one overdue and owned by the signed-in person (needs you), one open for Priya.
const decisionsPy = join(SCRIPTS_DIR, 'track_decisions.py')
py('decision DL-01', [decisionsPy, '--repo', project, 'open', '--decision', 'Confirm risk tier for 0006 (proposed HIGH)', '--owner', meHandle ?? 'Pod Lead', '--opened', '2026-09-30'])
py('decision DL-02', [decisionsPy, '--repo', project, 'open', '--decision', 'Fail open or closed when the adjuster API is down?', '--owner', '@priya-n'])
// The scorecard: the standard's numbers come from recorded outcomes, never invented.
const scorecardPy = join(SCRIPTS_DIR, 'scorecard.py')
py('scorecard merged 1', [scorecardPy, 'record', '--repo', project, '--type', 'spec_merged', '--field', 'accepted_as_is=true', '--field', 'risk=HIGH'])
py('scorecard merged 2', [scorecardPy, 'record', '--repo', project, '--type', 'spec_merged', '--field', 'accepted_as_is=false', '--field', 'risk=LOW'])
py('scorecard wait', [scorecardPy, 'record', '--repo', project, '--type', 'review_wait', '--field', 'wait_hours=5.5'])
py('scorecard deploy', [scorecardPy, 'record', '--repo', project, '--type', 'deploy', '--field', 'env=prod', '--field', 'succeeded=true', '--field', 'lead_time_hours=20'])
try {
  git(['add', '-A'], project)
  git(['commit', '-q', '-m', 'observatory fixture'], project)
  git(['push', '-q', '-u', 'origin', 'main'], project)
} catch (e) { failures.push(`git commit/push: ${String(e.stderr ?? e.message).trim()}`) }

const userData = join(workspace, 'userData')
mkdirSync(userData, { recursive: true })
writeFileSync(join(userData, 'settings.json'), JSON.stringify({
  recentProjects: [{ path: project, name: 'observatory project', lastOpenedAt: new Date().toISOString() }],
  pluginScriptsPathOverride: SCRIPTS_DIR,
}, null, 2))

// --- the ghost probe ---------------------------------------------------------------------------
/** A minimal PNG reader for what Chromium's screenshots are: 8-bit RGB / RGBA, no interlace.
 * No dependency — the plan forbids adding one for a probe. */
function decodePng(buffer) {
  let pos = 8 // signature
  const idat = []
  let width = 0, height = 0, colorType = 6
  while (pos < buffer.length) {
    const length = buffer.readUInt32BE(pos)
    const type = buffer.toString('ascii', pos + 4, pos + 8)
    const data = buffer.subarray(pos + 8, pos + 8 + length)
    if (type === 'IHDR') {
      width = data.readUInt32BE(0); height = data.readUInt32BE(4)
      if (data[8] !== 8) throw new Error(`png: bit depth ${data[8]} unsupported`)
      colorType = data[9]
      if (data[12] !== 0) throw new Error('png: interlaced screenshots are not expected')
    } else if (type === 'IDAT') idat.push(data)
    pos += 12 + length
  }
  const bpp = colorType === 6 ? 4 : colorType === 2 ? 3 : (() => { throw new Error(`png: colour type ${colorType} unsupported`) })()
  const raw = inflateSync(Buffer.concat(idat))
  const stride = width * bpp
  const out = Buffer.alloc(height * stride)
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)]
    const src = y * (stride + 1) + 1
    const dst = y * stride
    for (let x = 0; x < stride; x++) {
      const a = x >= bpp ? out[dst + x - bpp] : 0
      const b = y > 0 ? out[dst - stride + x] : 0
      const c = x >= bpp && y > 0 ? out[dst - stride + x - bpp] : 0
      let v = raw[src + x]
      if (filter === 1) v += a
      else if (filter === 2) v += b
      else if (filter === 3) v += (a + b) >> 1
      else if (filter === 4) { const p = a + b - c; const pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c); v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c }
      out[dst + x] = v & 0xff
    }
  }
  return { width, height, bpp, data: out }
}

/** Per pixel row: the max |channel − surface-0 channel| over the row; the report is how many rows
 * exceed the threshold and the worst deviation seen, so a 1 px glyph strip cannot hide in a mean. */
function bandDeviation(img, surface) {
  const rows = []
  for (let y = 0; y < img.height; y++) {
    let worst = 0
    for (let x = 0; x < img.width; x++) {
      const i = (y * img.width + x) * img.bpp
      for (let ch = 0; ch < 3; ch++) worst = Math.max(worst, Math.abs(img.data[i + ch] - surface[ch]))
    }
    rows.push(worst)
  }
  const ghostRows = rows.map((v, i) => [i, v]).filter(([, v]) => v > GHOST_THRESHOLD)
  return { rows: img.height, worst: Math.max(...rows), ghostRows: ghostRows.length, ghostRowIndexes: ghostRows.map(([i]) => i), perRow: rows }
}

class ProbeDone extends Error {}

const hexToRgb = (hex) => { const h = hex.replace('#', ''); return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) }

/** The protocol in the file comment. Returns the report lines; writes nothing but the console. */
async function ghostProbe(page) {
  const lines = [`GHOST PROBE bisect=${GHOST_BISECT || 'none'} dpr=${await page.evaluate(() => window.devicePixelRatio)}`]
  if (GHOST_BISECT_CSS[GHOST_BISECT]) await page.addStyleTag({ content: GHOST_BISECT_CSS[GHOST_BISECT] })
  const surfaceHex = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--color-surface-0').trim())
  const surface = hexToRgb(surfaceHex)
  lines.push(`surface-0 ${surfaceHex} → ${surface.join(',')}`)
  await page.getByRole('button', { name: /^Build Loop/ }).click()
  const t0 = Date.now()
  // v11: the sprint target is the sprint HOME (`Home` under Build Loop); its header is the band's anchor.
  await page.getByRole('button', { name: GHOST_TARGET === 'board' ? 'Board' : 'Home', exact: true }).click()
  if (GHOST_TARGET === 'board') await page.getByRole('button', { name: 'Everything' }).waitFor({ timeout: 60_000 })
  else await page.getByTestId('sprint-header').waitFor({ timeout: 60_000 })
  const tHeader = Date.now() - t0
  const figure = page.getByTestId('constellation-sprint')
  let surfaceNote = GHOST_TARGET === 'board' ? 'board list (no figure)' : 'graph (default)'
  if (GHOST_TARGET === 'board') {
    // The list surface: rows stagger in under the sticky filter bar exactly as the slate did.
  } else if (GHOST_BISECT === 5) {
    await figure.getByRole('button', { name: 'Table', exact: true }).click()
    surfaceNote = 'TABLE (bisect 5)'
  } else {
    // The slate constellation sits below the lanes on the sprint home; the probe measures the band
    // above the header, so the figure is only noted, never scrolled to (the pointer stays put).
    surfaceNote = (await figure.count()) ? `graph figure present (${await figure.getAttribute('data-surface')})` : 'no figure'
  }
  const tSurface = Date.now() - t0
  lines.push(`header at ${tHeader} ms, surface ${surfaceNote} at ${tSurface} ms; pointer left where the last click put it`)
  for (const at of GHOST_TIMES_MS) {
    const wait = t0 + at - Date.now()
    if (wait > 0) await page.waitForTimeout(wait)
    const band = await page.evaluate(() => {
      const filterRow = document.querySelector('[data-filter-row]')
      // v11: the sprint home's header (`SprintHeader`, test id `sprint-header`) sits under <main>'s
      // 24 px padding, so the 25 px band above it is all ground.
      const header = filterRow ? filterRow.parentElement : document.querySelector('[data-testid="sprint-header"]')
      const main = document.getElementById('main')
      if (!header || !main) return null
      const r = header.getBoundingClientRect(); const m = main.getBoundingClientRect()
      // The Sprint header sits under <main>'s 24 px padding, so the 25 px band is all ground. The
      // Board's filter bar sits 24 px (`space-y-6`) under the team chips: the 25th row up is the
      // chips' own bottom edge, real content — so that target measures the 24 px gap exactly.
      const wanted = filterRow ? 24 : 25
      // The band never reaches above <main>'s own top edge: the row there is the strip's hairline
      // (`border-b border-line-1`, by design), not ground — measuring it would report the shell.
      const y = Math.max(Math.round(m.top) + 1, Math.round(r.top) - wanted)
      const height = Math.round(r.top) - y
      return { x: Math.round(m.left), y, width: Math.round(m.width), height, stuck: header.hasAttribute('data-stuck'), surface: document.querySelector('[data-testid="constellation-sprint"]')?.getAttribute('data-surface') ?? 'list' }
    })
    const atMs = Date.now() - t0
    if (!band) { lines.push(`t=${atMs} ms: no header found`); continue }
    const png = await page.screenshot({ type: 'png', clip: { x: band.x, y: band.y, width: band.width, height: band.height } })
    const dev = bandDeviation(decodePng(png), surface)
    lines.push(`t=${atMs} ms target=${GHOST_TARGET} surface=${band.surface} stuck=${band.stuck} band y=${band.y}..${band.y + band.height} rows=${dev.rows}: ghost rows=${dev.ghostRows} worst=${dev.worst}/255${dev.ghostRows ? ` at device rows [${dev.ghostRowIndexes.join(',')}] per-row max [${dev.perRow.join(' ')}]` : ''}`)
    if (dev.ghostRows) writeFileSync(join(here, `${PREFIX}-ghost-probe-${GHOST_BISECT || 0}-${at}.png`), png)
  }
  return lines
}

// --- the walk ----------------------------------------------------------------------------------
// SHOT_SCALE=2 renders at two device pixels per CSS pixel (main appends Chromium's
// force-device-scale-factor switch from TOGO_DEVICE_SCALE before the app is ready — the same
// switch on the command line is ignored on macOS) — the guide's screenshots come out crisp when
// downsampled; the probes read CSS-pixel geometry and stay unaffected, but the ghost probe's
// band crop is in device pixels, so run the probes at the default scale of 1.
const SCALE = Number(process.env.SHOT_SCALE ?? 1)
const app = await electron.launch({
  args: ['.', '--no-sandbox', `--user-data-dir=${userData}`],
  cwd: root,
  env: { ...process.env, NODE_ENV: 'development', TOGO_AUTO_ZOOM: process.env.TOGO_AUTO_ZOOM ?? '0', ...(SCALE !== 1 ? { TOGO_DEVICE_SCALE: String(SCALE) } : {}) },
})
const notes = []
const consoleLines = []
const GPU_ERROR = /GLSL|shader|useProgram|WebGL|THREE\.WebGL|program not valid|CONTEXT_LOST/i
try {
  const page = await app.firstWindow()
  // SHOT_WINDOW=1 resizes the real BrowserWindow (so main's width-driven rendering scale and the
  // remembered bounds are exercised); the default emulates the viewport, which leaves the window
  // alone and is what the layout probes want.
  const setView = async (width, height) => {
    if (process.env.SHOT_WINDOW === '1') {
      await app.evaluate(({ BrowserWindow }, size) => { const w = BrowserWindow.getAllWindows()[0]; w.setContentSize(size.width, size.height); }, { width, height })
      await page.waitForTimeout(400)
      const zoom = await app.evaluate(({ BrowserWindow }) => { const w = BrowserWindow.getAllWindows()[0]; return { zoom: w.webContents.getZoomFactor(), content: w.getContentBounds() } })
      notes.push(`window ${zoom.content.width}x${zoom.content.height} · zoom ${zoom.zoom}`)
      return
    }
    await page.setViewportSize({ width, height })
  }
  // GPU-side smoke test: a shader that fails to compile reports itself only on the renderer's
  // console (three logs the GLSL error, then `useProgram: program not valid` every frame) and the
  // scene silently draws nothing — the ground grid did exactly that for a reserved word. Every
  // console error/warning the walk sees is collected; GPU ones fail the run below.
  page.on('console', (msg) => {
    const type = msg.type()
    if (type === 'error' || type === 'warning') consoleLines.push(`[${type}] ${msg.text().split('\n')[0].slice(0, 220)}`)
  })
  page.on('pageerror', (err) => consoleLines.push(`[pageerror] ${String(err.message ?? err).split('\n')[0].slice(0, 220)}`))
  await setView(1440, 900)
  await page.getByRole('heading', { level: 1, name: 'Shepherd' }).waitFor({ timeout: 30_000 })
  await settle(page)
  await shot(page, 'welcome')
  // v8: the Welcome in the dark theme. The corner pill is the kit's ThemeToggle (group "Theme"),
  // the same control the sidebar's Appearance popover holds; back to Light so the walk's light
  // twins are the explicit preference, not whatever the OS says.
  const welcomeTheme = page.getByRole('group', { name: 'Theme' })
  await welcomeTheme.getByRole('button', { name: 'Dark' }).click()
  await page.mouse.move(720, 620)
  await settle(page)
  await shot(page, 'welcome-dark')
  await welcomeTheme.getByRole('button', { name: 'Light' }).click()
  await page.waitForTimeout(400)

  await page.getByText('observatory project').click()
  await page.getByRole('navigation', { name: 'Project' }).waitFor({ timeout: 60_000 })
  // The shell band is the first <aside> (TopBand + LifecycleStrip): Appearance, Settings, More.
  const sidebar = page.locator('aside').first()
  const nav = page.getByRole('navigation', { name: 'Project' })

  if (PROBE === 'ghost') {
    // The probe is the whole run: no walk, no shots, the pointer untouched after the last click.
    for (const line of await ghostProbe(page)) console.log(line)
    throw new ProbeDone()
  }

  /** Click a SceneShell's Graph button if the table is showing, then wait for its canvas. */
  const ensureGraph = async (figure) => {
    const graph = figure.getByRole('button', { name: 'Graph', exact: true })
    if (await graph.count() && (await graph.getAttribute('aria-pressed')) !== 'true') await graph.click()
    await figure.locator('canvas').first().waitFor({ timeout: 30_000 }).catch(() => notes.push('no canvas appeared'))
  }
  const setTheme = async (label) => {
    await sidebar.getByRole('button', { name: 'Appearance' }).click()
    await sidebar.getByRole('group', { name: 'Theme' }).getByRole('button', { name: label }).click()
    await sidebar.getByRole('button', { name: 'Appearance' }).click()
    await page.mouse.move(720, 450) // the popover closes under the pointer; park it over <main>
    await page.waitForTimeout(400)
  }
  const openBuild = async (view) => {
    const build = nav.getByRole('button', { name: /^Build Loop/ })
    if ((await build.getAttribute('aria-expanded')) !== 'true') await build.click()
    await nav.getByRole('button', { name: view, exact: true }).click()
  }
  const scrollTop = async () => { await page.evaluate(() => document.getElementById('main')?.scrollTo({ top: 0 })); await page.waitForTimeout(300) }

  // --- the sprint home: a Build-loop project lands here (homeFor) -------------------------------
  const home = page.getByTestId('sprint-home')
  await home.waitFor({ timeout: 60_000 })
  await page.getByTestId('lane-card').first().waitFor({ timeout: 60_000 }).catch(() => notes.push('sprint-home: no lane card'))
  await page.waitForTimeout(2_500) // the command-center read lands; lanes, Today, the room and Refining fill
  await page.mouse.move(720, 870)
  await settle(page, 1_800)
  await shot(page, 'sprint-home')
  notes.push(`needs-you chip: ${(await page.getByTestId('needs-you-chip').textContent().catch(() => null)) ?? 'absent'}`)
  await setTheme('Dark')
  await settle(page, 1_200)
  await shot(page, 'sprint-home-dark')
  await setTheme('Light')

  // The slate constellation keeps its Graph surface below the lanes; its Table twin is the slate.
  const slate = page.locator('section[aria-label="Slate"]')
  await slate.scrollIntoViewIfNeeded()
  const figure = page.getByTestId('constellation-sprint')
  await ensureGraph(figure)
  await settle(page, 1_800)
  await shot(page, 'sprint-graph')
  await setTheme('Dark')
  await settle(page, 1_200)
  await shot(page, 'sprint-graph-dark')
  await setTheme('Light')
  await settle(page, 600)
  notes.push(`devicePixelRatio: ${await page.evaluate(() => window.devicePixelRatio)}`)
  notes.push(`sprint-graph canvas: ${await page.evaluate(() => {
    const c = document.querySelector('[data-testid="constellation-sprint"] canvas')
    if (!c) return 'none'
    const r = c.getBoundingClientRect()
    return `css ${Math.round(r.width)}x${Math.round(r.height)}, buffer ${c.width}x${c.height}`
  })}`)
  const plate = figure.locator('[data-plate-id="0005"] button')
  if (await plate.count()) await plate.hover({ force: true })
  else notes.push('no plate for 0005')
  await settle(page)
  await shot(page, 'sprint-graph-hover')
  await page.mouse.move(720, 60)
  await figure.getByRole('button', { name: 'Table', exact: true }).click()
  await settle(page)
  await shot(page, 'sprint-table')
  await setTheme('Dark')
  await settle(page, 1_200)
  await shot(page, 'sprint-table-dark')
  await setTheme('Light')
  await settle(page, 600)
  await figure.getByRole('button', { name: 'Graph', exact: true }).click().catch(() => {})
  await scrollTop()

  // --- planning -------------------------------------------------------------------------------
  await openBuild('Planning')
  await page.getByTestId('planning-backlog').waitFor({ timeout: 60_000 })
  await page.waitForTimeout(2_000)
  await settle(page)
  await shot(page, 'planning')
  await setTheme('Dark')
  await settle(page, 1_200)
  await shot(page, 'planning-dark')
  await setTheme('Light')
  await settle(page, 600)

  // --- the spec card, opened in place from Refining -------------------------------------------
  await openBuild('Home')
  await home.waitFor({ timeout: 60_000 })
  const refining = page.getByTestId('refining')
  await refining.locator('[data-testid="refining-row"]').first().waitFor({ timeout: 60_000 }).catch(() => notes.push('no refining row'))
  await refining.scrollIntoViewIfNeeded()
  const refine = refining.locator('[data-refine]').first()
  if (await refine.count()) {
    await refine.click()
    await page.getByTestId('spec-card').waitFor({ timeout: 60_000 })
    await page.waitForTimeout(2_000)
    await settle(page)
    await shot(page, 'spec-card')
    await setTheme('Dark')
    await settle(page, 1_200)
    await shot(page, 'spec-card-dark')
    await setTheme('Light')
    await settle(page, 600)
    await page.keyboard.press('Escape')
    await home.waitFor({ timeout: 60_000 })
  } else notes.push('spec-card: no "refine in place →" to click')
  await scrollTop()

  // --- the lifecycle home: lean into a station ------------------------------------------------
  await nav.getByRole('button', { name: /^Phase 0/ }).click()
  await page.getByTestId('lifecycle-home').waitFor({ timeout: 60_000 })
  await page.waitForTimeout(2_500) // readiness poll lands; StageHome shows rows, not its skeleton
  const spine = page.getByTestId('spine-band')
  // The band's collapsed state persists (localStorage) and an earlier step may have left it
  // folded — v14's stage-dark-hover shot found no figure to hover. `StageHome` marks the folded
  // band with `data-collapsed` and names the chevron "Expand the lifecycle view"; open it first
  // and let the height row settle before any stage shot.
  if ((await spine.getAttribute('data-collapsed')) !== null) {
    await spine.getByRole('button', { name: 'Expand the lifecycle view' }).click()
    await settle(page, 800)
    notes.push('stage: the Lifecycle band was collapsed; expanded it before the stage shots')
  }
  await ensureGraph(spine)
  await settle(page)
  await shot(page, 'stage-light')
  await setTheme('Dark')
  await settle(page)
  await shot(page, 'stage-dark')
  await nav.getByRole('button', { name: /^Phase 2/ }).hover()
  await settle(page)
  await shot(page, 'stage-dark-hover')
  await page.mouse.move(720, 450)
  await setTheme('Light')
  // Build's lifecycle home (the `Documents` view): the Spine, Build's documents, the Today band and
  // "Go to the sprint home →". (The station itself opens the Board, as it always has.)
  await openBuild('Documents')
  await page.getByRole('button', { name: 'Go to the sprint home →' }).waitFor({ timeout: 60_000 }).catch(() => notes.push('lifecycle-home: no "Go to the sprint home" button'))
  await page.waitForTimeout(1_500)
  await settle(page)
  await shot(page, 'lifecycle-home')
  await setTheme('Dark')
  await settle(page, 1_200)
  await shot(page, 'lifecycle-home-dark')
  await setTheme('Light')
  await settle(page, 600)

  // --- the Board ---------------------------------------------------------------------------------
  await openBuild('Board')
  await page.getByRole('button', { name: 'Everything' }).waitFor({ timeout: 60_000 })
  await page.getByRole('button', { name: 'Everything' }).click()
  await settle(page)
  await shot(page, 'board-list')
  await setTheme('Dark')
  await settle(page, 1_200)
  await shot(page, 'board-list-dark')
  await setTheme('Light')
  await settle(page, 600)
  await page.getByRole('group', { name: 'Board surface' }).getByRole('button', { name: 'Graph', exact: true }).click()
  await page.locator('canvas').first().waitFor({ timeout: 30_000 }).catch(() => notes.push('board: no canvas'))
  await settle(page, 1_800)
  await shot(page, 'board-graph')
  await setTheme('Dark')
  await settle(page, 1_200)
  await shot(page, 'board-graph-dark')
  await setTheme('Light')
  await settle(page, 600)
  await page.getByRole('group', { name: 'Board surface' }).getByRole('button', { name: 'List', exact: true }).click()

  // --- the palette and the omnibar -------------------------------------------------------------
  await page.keyboard.press('Meta+K')
  await page.getByTestId('command-palette').waitFor({ timeout: 10_000 })
  await page.keyboard.type('sprint')
  await settle(page, 600)
  await shot(page, 'palette')
  await page.keyboard.press('Escape')
  await page.keyboard.press('Meta+K')
  await page.getByTestId('command-palette').waitFor({ timeout: 10_000 })
  await page.keyboard.type('verdict 0003 accepted')
  await settle(page, 600)
  await shot(page, 'omnibar')
  await page.keyboard.press('Escape')

  // --- Settings, the spec view, the dark twins -------------------------------------------------
  await sidebar.getByRole('button', { name: 'Settings' }).click()
  const appearance = page.locator('#appearance')
  await appearance.waitFor({ timeout: 60_000 })
  await appearance.scrollIntoViewIfNeeded()
  await settle(page)
  await shot(page, 'settings')

  await openBuild('Board')
  await page.getByRole('button', { name: 'Everything' }).waitFor({ timeout: 60_000 })
  await page.getByRole('button', { name: 'Everything' }).click()
  await page.getByRole('button', { name: /^0001\b/ }).first().click()
  await page.waitForTimeout(2_000)
  await settle(page)
  await shot(page, 'spec-view')
  await setTheme('Dark')
  await settle(page)
  await shot(page, 'spec-view-dark')
  await page.getByRole('button', { name: '← Back to the board' }).click()
  await page.getByRole('button', { name: 'Everything' }).waitFor({ timeout: 60_000 })
  await page.keyboard.press('Meta+K')
  await page.getByTestId('command-palette').waitFor({ timeout: 10_000 })
  await page.keyboard.type('sprint')
  await settle(page, 600)
  await shot(page, 'palette-dark')
  await page.keyboard.press('Escape')
  await sidebar.getByRole('button', { name: 'Settings' }).click()
  await appearance.waitFor({ timeout: 60_000 })
  await appearance.scrollIntoViewIfNeeded()
  await settle(page)
  await shot(page, 'settings-dark')
  await setTheme('Light')

  // --- review / close, above the unchanged "Declaring Build finished" --------------------------
  await openBuild('Closing')
  await page.getByTestId('sprint-close').waitFor({ timeout: 60_000 })
  await page.getByTestId('close-outcomes').waitFor({ timeout: 60_000 }).catch(() => notes.push('review: no outcomes section'))
  await page.waitForTimeout(1_500)
  await settle(page)
  await shot(page, 'review')
  await setTheme('Dark')
  await settle(page, 1_200)
  await shot(page, 'review-dark')
  await setTheme('Light')
  await settle(page, 600)
  const declaring = page.getByRole('heading', { name: 'Declaring Build finished' })
  await declaring.waitFor({ timeout: 60_000 })
  await declaring.scrollIntoViewIfNeeded()
  await ensureGraph(page.locator('main#main'))
  await settle(page, 1_800)
  await shot(page, 'closing')
  await setTheme('Dark')
  await settle(page, 1_200)
  await shot(page, 'closing-dark')
  await setTheme('Light')
  await settle(page, 600)

  // --- steering mode (the committee's room): the light room first, then the dark one ------------
  // The band is a presentation in steering (mark · name · Leave), so the theme is set BEFORE
  // entering and the room is left (Esc) before switching.
  await sidebar.getByRole('button', { name: 'More' }).click()
  await page.getByRole('menuitem', { name: 'Steering mode' }).or(page.getByRole('button', { name: 'Steering mode' })).first().click()
  await page.getByTestId('steering-mode').waitFor({ timeout: 60_000 })
  await page.getByTestId('steering-tiles').waitFor({ timeout: 60_000 }).catch(() => notes.push('steering: no tiles'))
  await page.waitForTimeout(1_500)
  await settle(page)
  await shot(page, 'steering-light')
  await page.keyboard.press('Escape')
  await page.getByTestId('steering-mode').waitFor({ state: 'detached', timeout: 10_000 }).catch(() => {})
  await setTheme('Dark')
  await sidebar.getByRole('button', { name: 'More' }).click()
  await page.getByRole('menuitem', { name: 'Steering mode' }).or(page.getByRole('button', { name: 'Steering mode' })).first().click()
  await page.getByTestId('steering-mode').waitFor({ timeout: 60_000 })
  await page.getByTestId('steering-tiles').waitFor({ timeout: 60_000 }).catch(() => notes.push('steering: no tiles'))
  await page.waitForTimeout(1_500)
  await settle(page)
  await shot(page, 'steering')
  await page.keyboard.press('Escape')
  await page.getByTestId('steering-mode').waitFor({ state: 'detached', timeout: 10_000 }).catch(() => {})
  await setTheme('Light')

  // --- Q5: the cockpit at each SHOT_WIDTHS size, light and dark ----------------------------------
  // The four screens the owner judges the cockpit by, each at rest (<main> scrolled to the top) so
  // the overlap probe's viewport rule applies in full. Files: <prefix>-<name>[-dark]@<w>.png.
  for (const { w, h } of WIDTHS) {
    await setView(w, h)
    await page.waitForTimeout(400)
    for (const theme of ['Light', 'Dark']) {
      await setTheme(theme)
      const suffix = `${theme === 'Dark' ? '-dark' : ''}@${w}`
      await openBuild('Home')
      await home.waitFor({ timeout: 60_000 })
      await page.waitForTimeout(1_500)
      await scrollTop()
      await settle(page)
      await shot(page, `sprint-home${suffix}`)
      await openBuild('Planning')
      await page.getByTestId('planning-backlog').waitFor({ timeout: 60_000 })
      await page.waitForTimeout(1_200)
      await scrollTop()
      await settle(page)
      await shot(page, `planning${suffix}`)
      await openBuild('Home')
      await home.waitFor({ timeout: 60_000 })
      // The command-center read fills Refining after the home mounts: wait for a row, as the walk does.
      await refining.locator('[data-testid="refining-row"]').first().waitFor({ timeout: 60_000 }).catch(() => {})
      const refineAt = refining.locator('[data-refine]').first()
      if (await refineAt.count()) {
        await refineAt.scrollIntoViewIfNeeded()
        await refineAt.click()
        await page.getByTestId('spec-card').waitFor({ timeout: 60_000 })
        await page.waitForTimeout(1_200)
        await scrollTop()
        await settle(page)
        await shot(page, `spec-card${suffix}`)
        await page.keyboard.press('Escape')
        await home.waitFor({ timeout: 60_000 })
      } else notes.push(`spec-card${suffix}: no "refine in place →" to click`)
      await openBuild('Documents')
      await page.getByRole('button', { name: 'Go to the sprint home →' }).waitFor({ timeout: 60_000 }).catch(() => notes.push(`lifecycle-home${suffix}: no "Go to the sprint home" button`))
      await page.waitForTimeout(1_200)
      await scrollTop()
      await settle(page)
      await shot(page, `lifecycle-home${suffix}`)
    }
    await setTheme('Light')
  }
} catch (e) {
  if (!(e instanceof ProbeDone)) throw e
} finally {
  await app.close().catch(() => {})
  try { rmSync(workspace, { recursive: true, force: true }) } catch { /* untidy, not fatal */ }
}
for (const n of notes) console.log(n)
if (failures.length) { console.log('fixture commands that failed:'); for (const f of failures) console.log(`  - ${f}`) }
else console.log('fixture: every command succeeded')
console.log(`wrote ${readdirSync(here).filter((f) => f.startsWith(`${PREFIX}-`)).length} ${PREFIX}-*.png to ${here}`)
const gpu = consoleLines.filter((l) => GPU_ERROR.test(l))
console.log(`renderer console: ${consoleLines.length} error/warning line(s), ${gpu.length} GPU-related`)
for (const l of consoleLines.slice(0, 12)) console.log(`  ${l}`)
if (gpu.length) { console.log('GPU errors are a failed capture: a scene drew less than it claims.'); if (!process.exitCode) process.exitCode = 2 }
if (OVERLAP) {
  if (overlapViolations.length) { console.log(`overlap probe: ${overlapViolations.length} shot(s) with a violation (exit 3):`); for (const v of overlapViolations) console.log(`  - ${v}`) }
  else console.log('overlap probe: every shot clean — no landmark outside the viewport, no unintended intersection, the root never scrolled')
}
