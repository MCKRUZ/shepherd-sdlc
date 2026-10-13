export const meta = {
  name: 'boards-fold-runner',
  description: 'Build one Azure Boards Fold (B1–B5) from docs/proposals/ado-boards-mirror-build-kit.md: contracts first, DAG levels of packages in worktrees merged per level with an ownership check, the Fold gates and an adversarial critic in parallel, a capped fix loop',
  phases: [
    { title: 'Contracts', detail: 'the Fold\'s P0 on the Fold branch, sequential' },
    { title: 'Packages', detail: 'DAG levels; a worktree per package when a level has more than one' },
    { title: 'Merge', detail: 'merge refs/pkg/<id> into the Fold branch per level; ownership check against the cards' },
    { title: 'Verify', detail: 'the Fold gates in one agent (no fixing) and the critic, in parallel' },
    { title: 'Fix', detail: 'one agent per red round, capped at 3' },
  ],
}

// ---------------------------------------------------------------------------
// args (JSON, see the kit §8 for the per-Fold blocks):
//   fold          'B1'..'B5'
//   branch        the Fold branch, already checked out by the orchestrator (e.g. spec/0034-ado-boards-schema-and-config)
//   base          the sha the Fold branch was cut from = PR #106 head (or its merge commit) at run time
//   start         optional: the branch commit this Fold run starts from (ownership diffs anchor here; defaults to base)
//   spec          'specs/0034-....md'
//   version       '2.1.0'
//   kit           'docs/proposals/ado-boards-mirror-build-kit.md'
//   levels        [['B1-P0'], ['B1-P1','B1-P2','B1-P3'], ['B1-P4'], ['B1-P5']]   (level 0 = the one contracts package)
//   packages      { 'B1-P1': { owns: ['scripts/ado_transport.py', 'scripts/tests/test_boards_transport_body.py'], deps: ['B1-P0'], gatedOn?: 'mention_probe', card?: '<card text>' }, ... }
//   gates         [{ name, cmd, expect }]  — '$BASE' inside cmd is replaced by args.base
//   protectedList ['scripts/check_spec.py', ...]
//   present       ['comments', ...]  — stems of wit/captured/*.json that exist (gates gated packages)
//   rules, sheet  optional: the kit's §2 house rules and the §3 interface rows as text (otherwise agents read them from the kit by heading)
// ---------------------------------------------------------------------------

const A = args || {}
for (const k of ['fold', 'branch', 'base', 'spec', 'version', 'kit', 'levels', 'packages', 'gates', 'protectedList']) {
  if (A[k] === undefined) throw new Error(`args.${k} is required (see the build kit §8)`)
}
const PRESENT = A.present || []
const KIT = A.kit
const START = A.start || A.base   // the commit this Fold started from: ownership diffs anchor here, protected-core/test gates on A.base
// Optional per-stage model override, e.g. { contracts: 'opus', packages: 'sonnet', merge: 'sonnet', verify: 'sonnet', critic: 'opus', fix: 'opus' }.
// A stage left out inherits the session model. Recommended split: a stronger model for contracts, critic and fix; Sonnet for the pinned packages.
const M = A.models || {}
const withModel = (opts, m) => (m ? Object.assign({}, opts, { model: m }) : opts)
// Built by concatenation so this file never carries the legacy strings the rename-residual gate greps for.
const LEGACY = ['/sd' + 'lc-', '[SD' + 'LC', 'sdlc-sess' + 'ion-start', 'claude-code-sd' + 'lc']

const PKG = {
  type: 'object',
  required: ['status', 'files', 'tests_run', 'failures', 'notes', 'sha'],
  properties: {
    status: { type: 'string', enum: ['done', 'blocked'] },
    files: { type: 'array', items: { type: 'object', required: ['path', 'action'], properties: { path: { type: 'string' }, action: { type: 'string', enum: ['created', 'edited'] } } } },
    tests_run: { type: 'array', items: { type: 'object', required: ['cmd', 'passed', 'failed', 'skipped'], properties: { cmd: { type: 'string' }, passed: { type: 'integer' }, failed: { type: 'integer' }, skipped: { type: 'integer' } } } },
    failures: { type: 'array', items: { type: 'string' } },
    notes: { type: 'array', items: { type: 'string' } },
    sha: { type: 'string' },
    blocked_on: { type: 'string' },
  },
}
const GATE = {
  type: 'object',
  required: ['green', 'results'],
  properties: {
    green: { type: 'boolean' },
    results: { type: 'array', items: { type: 'object', required: ['gate', 'passed', 'output_tail'], properties: { gate: { type: 'string' }, passed: { type: 'boolean' }, output_tail: { type: 'string' } } } },
  },
}
const CRIT = {
  type: 'object',
  required: ['verdict', 'findings'],
  properties: {
    verdict: { type: 'string', enum: ['pass', 'fail'] },
    findings: { type: 'array', items: { type: 'object', required: ['package', 'rule', 'file', 'detail', 'blocking'], properties: { package: { type: 'string' }, rule: { type: 'string' }, file: { type: 'string' }, detail: { type: 'string' }, blocking: { type: 'boolean' } } } },
  },
}

// glob → RegExp: '**' = any path, '*' = within one segment. Cards use only these two.
function rx(glob) {
  const esc = glob.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*\*/g, '\u0000').replace(/\*/g, '[^/]*').replace(/\u0000/g, '.*')
  return new RegExp('^' + esc + '$')
}
function owned(pkgIds) {
  const globs = []
  pkgIds.forEach(id => (A.packages[id].owns || []).forEach(g => globs.push(rx(g))))
  return path => globs.some(r => r.test(path))
}
function violations(pkgId, paths) { const ok = owned([pkgId]); return (paths || []).filter(p => !ok(p)) }

const RULES = A.rules ? `HOUSE RULES (each is checked mechanically after merge):\n${A.rules}` : `HOUSE RULES: read ${KIT}, the section headed "## 2. House rules", and obey every line; each is checked mechanically after merge.`
const SHEET = A.sheet ? `INTERFACE SHEET (pinned; a signature you did not define here is not yours to change):\n${A.sheet}` : `INTERFACE SHEET: read ${KIT}, the section headed "## 3. Interface sheet", and use ONLY the rows for the modules your card names. A signature you did not define is not yours to change.`
const COMMON = [
  `Fold ${A.fold} · branch ${A.branch} · base commit ${A.base} · spec ${A.spec} · version ${A.version}. Repository: the current checkout. Term rule: "Workflow tool" means this orchestration; "Workflow mode" means running a script with --state .sdlc/state.yaml.`,
  RULES, SHEET,
  `PROTECTED CORE (must stay byte-identical to ${A.base}; never open these for writing): ${A.protectedList.join(' ')}`,
].join('\n\n')

function cardText(id) {
  const p = A.packages[id]
  if (p && p.card) return p.card
  return `Read ${KIT}, the section headed "## 5. Package cards", and find the row/card for ${id}. That card is your whole scope. If the card cites a section of docs/proposals/ado-boards-mirror.md (for example '§6.2', 'the §8 drift matrix', 'the §8a templates', 'the §7 rows'), read ONLY that section of the design and treat it as part of your card; otherwise do not open the design document.`
}

function brief(id, isolated) {
  const p = A.packages[id]
  return [
    `You are building package ${id}. Your ONLY scope is this card:`, cardText(id), COMMON,
    `FILE OWNERSHIP: you may create or edit ONLY paths matching: ${(p.owns || []).join(', ')}. A card row marked (edit) may change an existing file; everything else you create. Needing any other file = stop and return status "blocked" with blocked_on=<path>. Never run \`az\`. Never run new_spec.py. Never edit a file under scripts/tests or studio/test that existed at ${A.base} unless your card marks it (edit).`,
    'PROCEDURE: (1) `git status --porcelain` must be empty before you start' + (isolated ? `, then \`git checkout -b pkg/${id} ${A.branch}\` (this worktree may have been cut from another ref — that command puts you on the Fold branch tip) and confirm \`git merge-base --is-ancestor ${A.base} HEAD\` succeeds` : '') + '. (2) Write the test file(s) your card names FIRST and run the card\'s acceptance command — it must fail. (3) Implement until it passes. (4) Run every "do-not" check on the card. (5) `git add` ONLY the paths you own; commit as "' + A.fold + ' ' + id + ': <card title>"; then `git update-ref refs/pkg/' + id + ' HEAD` and report sha = `git rev-parse HEAD`.',
    'Hand-written fixtures carry "_provenance": "hand-written (unverified)" and are always wrapped {"_provenance", "_command", "value"}. Report real test counts from the output (passed/failed/skipped per command); a test you did not run is not listed. files = exactly what you committed.',
  ].join('\n\n')
}

function mergeBrief(level, landedBefore) {
  const union = owned(landedBefore.concat(level))
  return [
    COMMON,
    `You are the merge agent for level [${level.join(', ')}] of Fold ${A.fold}. You are on branch ${A.branch}; \`git status --porcelain\` must be empty.`,
    `For each id in this order run \`git merge --no-ff --no-edit refs/pkg/<id> -m "merge <id>"\`: ${level.join(', ')}.`,
    'A merge conflict means two cards touched one file — do NOT resolve it: `git merge --abort`, report gate "merge <id>" as passed=false with the conflicting paths in output_tail, and continue with the next id.',
    `After the merges run \`git diff --name-only ${START}\` (the commit this Fold started from — never the PR base) and report as gate "ownership" (passed=false if any path is listed) every path that matches NONE of these owned globs — the globs are authoritative, the kit's card prose is not: ${Object.keys(A.packages).flatMap(id => (A.packages[id] && A.packages[id].owns) || []).join(' ')}. '*' matches within one path segment, '**' matches any depth. List offending paths in output_tail.`,
    'green = every merge clean and the ownership gate passed. Do not fix anything.',
  ].join('\n\n')
}

function gateList() { return A.gates.map(g => `GATE ${g.name}\n  cmd: ${String(g.cmd).split('$BASE').join(A.base)}\n  expect: ${g.expect}`).join('\n\n') }

function verifyBrief() {
  return [
    COMMON,
    `Run each gate below in order from the repository root on branch ${A.branch}, exactly as written. Do NOT fix anything. A gate you could not run is passed=false with output_tail "not run: <why>". Record passed = (the outcome matches "expect") and the last 40 lines of output.`,
    gateList(), 'green = every gate passed.',
  ].join('\n\n')
}

function criticBrief() {
  return [
    COMMON,
    `Adversarially review \`git diff ${START}..HEAD\` on ${A.branch} against the package cards in ${KIT} ("## 5. Package cards", Fold ${A.fold}) and the house rules. Try to REFUTE a green verify. For every card check: (a) every path changed since ${START} matches at least one of these owned globs from args (the globs, not the card prose, are the authority; '*' = one segment, '**' = any depth): ${Object.keys(A.packages).flatMap(id => (A.packages[id] && A.packages[id].owns) || []).join(' ')}; (b) every exported signature matches the interface sheet (grep the def/export lines); (c) the card's do-not list holds; (d) no integer 0 stands for "no data"; (e) no email, UPN, GUID or display name is written to a committed file or JSONL line; (f) \`git diff --diff-filter=M --name-only ${A.base} -- scripts/tests studio/test\` lists only files a card marks (edit); (g) argv is always a list — grep for shell=True, shlex.join, '" ".join(' near args/argv/cmd; (h) every new az argv carries --detect false and no "-preview.<digit>" api-version; (i) the command doc names only verbs/flags in the kit's verb table; (j) a protected file is byte-identical to ${A.base}; (k) none of the legacy brand strings ${LEGACY.map(s => JSON.stringify(s)).join(', ')} was introduced outside .sdlc/ paths and sdlc:* tags.`,
    'blocking = a correctness or house-rule breach; style alone is non-blocking. verdict = fail if any finding is blocking.',
  ].join('\n\n')
}

function fixBrief(red, round) {
  return [
    COMMON,
    `Fix round ${round} on ${A.branch}. These are red:`,
    red.map(r => `GATE ${r.gate}\n${r.output_tail}`).join('\n\n'),
    `Fix inside the owning card's files only (cards: ${KIT} "## 5. Package cards"). Rules: never edit a protected file; never edit a pre-existing test to make it pass — if an existing test is red, the product code is wrong; never weaken a new test; never edit a gate. Commit as "${A.fold} fix r${round}: <gate names>". Return the structured result (status done, or blocked with blocked_on).`,
  ].join('\n\n')
}

// ---------------------------------------------------------------------------
const done = {}
const landed = []
const skipped = []

// Level 0: contracts, sequential, on the Fold branch.
const p0 = A.levels[0][0]
const r0 = await agent(brief(p0, false), withModel({ label: p0, phase: 'Contracts', schema: PKG }, M.contracts))
if (!r0 || r0.status !== 'done') return { fold: A.fold, stopped: 'contracts', package: p0, result: r0 }
const v0 = violations(p0, (r0.files || []).map(f => f.path))
if (v0.length) return { fold: A.fold, stopped: 'contracts ownership', violations: v0, result: r0 }
done[p0] = r0; landed.push(p0)

// Later levels.
for (let i = 1; i < A.levels.length; i++) {
  const level = A.levels[i].filter(id => {
    const g = A.packages[id] && A.packages[id].gatedOn
    if (g && !PRESENT.includes(g)) { skipped.push(`${id} (needs captured ${g})`); return false }
    const deps = (A.packages[id] && A.packages[id].deps) || []
    const missing = deps.filter(d => !landed.includes(d))
    if (missing.length) { skipped.push(`${id} (dep not landed: ${missing.join(', ')})`); return false }
    return true
  })
  if (!level.length) continue
  const isolated = level.length > 1
  const results = await parallel(level.map(id => () => agent(brief(id, isolated), withModel({ label: id, phase: 'Packages', schema: PKG, isolation: isolated ? 'worktree' : undefined }, M.packages))))
  const okIds = []
  level.forEach((id, k) => {
    const r = results[k]
    done[id] = r
    const bad = r && r.status === 'done' ? violations(id, (r.files || []).map(f => f.path)) : []
    if (r && r.status === 'done' && !bad.length) okIds.push(id)
    else log(`${id}: ${!r ? 'agent died' : r.status === 'blocked' ? 'blocked on ' + (r.blocked_on || '?') : 'edited non-owned ' + bad.join(', ')}`)
  })
  if (!okIds.length) return { fold: A.fold, stopped: `level ${i}`, done, skipped }
  if (isolated) {
    const m = await agent(mergeBrief(okIds, landed.slice()), withModel({ label: `merge L${i}`, phase: 'Merge', schema: GATE }, M.merge))
    if (!m || !m.green) return { fold: A.fold, stopped: `merge L${i}`, merge: m, done, skipped }
  }
  okIds.forEach(id => landed.push(id))
  const notLanded = level.filter(id => !okIds.includes(id))
  if (notLanded.length) log(`not landed at level ${i}: ${notLanded.join(', ')} — dependents will be skipped`)
}
if (skipped.length) log(`skipped packages: ${skipped.join('; ')}`)

// Verify + critic in parallel, then a capped fix loop.
let round = 0, gate = null, crit = null, green = false
while (round < 3) {
  const [g, c] = await parallel([
    () => agent(verifyBrief(), withModel({ label: `verify r${round}`, phase: 'Verify', schema: GATE }, M.verify)),
    () => agent(criticBrief(), withModel({ label: `critic r${round}`, phase: 'Verify', schema: CRIT, effort: 'high' }, M.critic)),
  ])
  gate = g; crit = c
  const redGates = gate ? (gate.results || []).filter(r => !r.passed) : [{ gate: 'verify agent', passed: false, output_tail: 'the verify agent returned nothing' }]
  const blocking = crit ? (crit.findings || []).filter(f => f.blocking) : []
  green = !!(gate && gate.green) && !blocking.length
  if (green) break
  const red = redGates.concat(blocking.map(f => ({ gate: `critic ${f.package} ${f.rule}`, passed: false, output_tail: `${f.file}: ${f.detail}` })))
  log(`round ${round}: ${red.map(r => r.gate).join(', ')}`)
  await agent(fixBrief(red, round), withModel({ label: `fix r${round}`, phase: 'Fix', schema: PKG }, M.fix))
  round++
}

return { fold: A.fold, green, rounds: round, landed, skipped, verify: gate, critic: crit, packages: Object.fromEntries(Object.entries(done).map(([k, r]) => [k, r ? { status: r.status, sha: r.sha } : null])) }
