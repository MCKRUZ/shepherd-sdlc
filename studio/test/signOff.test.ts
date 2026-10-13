/** Signing off a phase, from Studio, without leaving the window.
 *
 * Until now the only thing in Studio that called the plugin's real phase-advance step was the
 * Build-declare-complete flow — every other phase (Discovery → Requirements, and on) still
 * needed `/sprd-next` in Claude Code. This is the general version: check the gates, confirm
 * every judgement question is ticked, write and validate a condensed "frozen layer" summary of
 * the phase, snapshot the artifact record, then advance — same order `/sprd-next` follows,
 * because it is the same plugin underneath and nothing here gets to disagree with it.
 *
 * Tested against a real git remote, same as `deferReachesTheRepo.test.ts` and
 * `syncMissingSectionArrival.test.ts`: a mock proves the calls were made, not that the result is
 * what the next person actually gets.
 */

import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterAll, describe, expect, it } from 'vitest'
import { initSettingsPath } from '../electron/main/settings'
import { checkStageGates, parseGateCheckOutput, setAsideLayer, signOffStage } from '../electron/main/signOff'
import { pull } from '../electron/main/sync'
import { requirePlugin } from './pluginRoot'

const PLUGIN = requirePlugin(__dirname)
const SCRIPTS_DIR = PLUGIN.scriptsDir
const VENV_PYTHON = PLUGIN.python

// The plugin's own recipe for a Phase 0 whose gates pass (scripts/tests/test_advance_signoff.py),
// reused rather than reinvented so this cannot drift from what the plugin actually requires.
const PHASE0: Record<string, string> = {
  'problem-statement.md':
    '# Problem Statement\n\nWe need a better claims process.\n\n## Scope\nIn scope: everything.\n',
  'constitution.md':
    '# Constitution\n\nCore principles and constraints for this project.\n',
  'success-criteria.md':
    '# Success Criteria\n\nThe project succeeds when all users can log in.\n',
  'constraints.md':
    '# Constraints\n\nMust use the existing infrastructure.\n',
  'phase1-handoff.md':
    '# Phase 1 Handoff\n\nReady for the requirements phase.\n',
}

// Real substance, close to what a real Phase 0 actually has — see the "real Claude call" test
// for why the placeholder PHASE0 above is not enough for it specifically.
const RICH_PHASE0: Record<string, string> = {
  'problem-statement.md': [
    '# Problem Statement',
    '',
    '## Executive Summary',
    'Claims adjusters currently re-key the same customer data into four disconnected systems',
    'for every claim, adding an average of 22 minutes of manual work and a 6% error rate from',
    'transcription mistakes. This costs the claims department roughly $1.8M a year in rework',
    'and delayed payouts, and is the single most common complaint in exit interviews for staff',
    'who leave the claims team within their first year.',
    '',
    '## Stakeholder Personas',
    '| Persona | Role | Primary Pain Point | Success Looks Like |',
    '|---------|------|--------------------|---------------------|',
    '| Dana | Claims Adjuster | Re-keys data 4 times per claim | One entry, auto-populated everywhere |',
    '| Priya | Claims Team Lead | Cannot see team-wide error rates | A live dashboard of transcription errors |',
    '| Sam | IT Operations | Four systems with no shared schema | One canonical customer record |',
    '',
    '## Problem Scope',
    'In scope: the intake-to-payout workflow for personal auto claims.',
    'Out of scope: commercial claims, and any change to the payout approval chain itself.',
    'Adjacent problems deferred: the separate fraud-review queue, which has its own backlog.',
  ].join('\n'),
  'constitution.md': [
    '# Constitution',
    '',
    '## Governing Principles',
    '1. No claim payout decision is ever automated — the system assists adjusters, it never',
    '   decides on their behalf.',
    '2. Every customer data field has exactly one system of record; every other system reads',
    '   it, none of them re-store their own copy.',
    '3. An adjuster can always see which system a field came from and when it was last updated.',
  ].join('\n'),
  'success-criteria.md': [
    '# Success Criteria',
    '',
    '## Measurable Success Dimensions',
    '### Dimension 1: Re-keying time',
    '**What we are measuring:** minutes an adjuster spends re-entering already-known data per claim.',
    '| Outcome | Threshold | How We will Measure |',
    '|---|---|---|',
    '| Pass | Under 5 minutes per claim | Timed observation on 30 claims |',
    '| Fail | Over 15 minutes per claim | Same |',
    '### Dimension 2: Transcription error rate',
    '**What we are measuring:** the rate of data entry errors caught in QA review.',
    '| Outcome | Threshold | How We will Measure |',
    '|---|---|---|',
    '| Pass | Under 1% | QA sampling of 200 claims a month |',
    '| Fail | Over 4% | Same |',
    '### Dimension 3: Adjuster-reported satisfaction',
    '**What we are measuring:** whether adjusters would recommend the new workflow.',
    '| Outcome | Threshold | How We will Measure |',
    '|---|---|---|',
    '| Pass | 80% positive | Quarterly survey |',
    '| Fail | Under 50% positive | Same |',
  ].join('\n'),
  'constraints.md': [
    '# Constraints',
    '',
    '## Fixed Limits',
    '- Budget: $650,000 for the first year, already approved by finance.',
    '- Timeline: a working pilot in one regional office within two quarters.',
    '- Technology: must integrate with the existing mainframe policy system without replacing it.',
    '- Policy: no customer PII may leave the company\'s own data center, including to any',
    '  third-party analytics tool.',
  ].join('\n'),
  'phase1-handoff.md': [
    '# Phase 1 Handoff',
    '',
    '## What Requirements Needs to Know',
    'The pilot region is the Midwest office, chosen because its claim volume is high enough to',
    'produce a statistically meaningful error-rate measurement within one quarter, and its team',
    'lead (Priya) has already agreed to weekly check-ins during the pilot.',
  ].join('\n'),
}

const git = (args: string[], cwd: string) => execFileSync('git', args, { cwd, encoding: 'utf-8' }).trim()
const made: string[] = []

async function scenario(phase0Artifacts: Record<string, string> | null) {
  const ws = mkdtempSync(join(tmpdir(), 'studio-signoff-'))
  made.push(ws)
  initSettingsPath(join(ws, 'userData'))
  const origin = join(ws, 'origin.git')
  const project = join(ws, 'project')
  git(['init', '--bare', '--initial-branch=main', origin], ws)
  git(['clone', origin, project], ws)
  git(['config', 'user.email', 'me@example.com'], project)
  git(['config', 'user.name', 'Me'], project)
  execFileSync(VENV_PYTHON, [
    join(SCRIPTS_DIR, 'init_project.py'),
    '--profile', join(PLUGIN.root!, 'profiles', 'microsoft-enterprise', 'profile.yaml'),
    '--target', project,
  ], { cwd: SCRIPTS_DIR })

  if (phase0Artifacts) {
    const discovery = join(project, '.sdlc', 'artifacts', '00-discovery')
    mkdirSync(discovery, { recursive: true })
    for (const [name, content] of Object.entries(phase0Artifacts)) {
      writeFileSync(join(discovery, name), content)
    }
  }

  git(['add', '-A'], project)
  git(['commit', '-m', 'initial project'], project)
  git(['push', '-u', 'origin', 'main'], project)
  expect((await pull(project, SCRIPTS_DIR)).ok).toBe(true)
  return { ws, project, origin }
}

function phaseOf(root: string): string {
  const out = execFileSync(VENV_PYTHON, [
    join(SCRIPTS_DIR, 'generate_status.py'), '--state', join(root, '.sdlc', 'state.yaml'), '--json',
  ], { cwd: SCRIPTS_DIR, encoding: 'utf-8' })
  return JSON.parse(out).current_phase.id
}

function confirmAllJudgementQuestions(project: string, phase: string): void {
  const ids = JSON.parse(execFileSync(VENV_PYTHON, [
    join(SCRIPTS_DIR, 'sign_off_confirmations.py'), 'status', '--repo', project, '--phase', phase, '--json',
  ], { encoding: 'utf-8' })).items.map((i: { id: string }) => i.id)
  for (const id of ids) {
    execFileSync(VENV_PYTHON, [
      join(SCRIPTS_DIR, 'sign_off_confirmations.py'), 'confirm', '--repo', project,
      '--phase', phase, '--question-id', id, '--actor', 'Matt K',
    ])
  }
}

afterAll(() => {
  for (const ws of made) rmSync(ws, { recursive: true, force: true })
})

describe('parseGateCheckOutput — pure, no subprocess', () => {
  const PASS = [
    'Gate Check Results — Phase 0',
    '==================================================',
    '',
    '  [G1]',
    '    COMPLIANT      [MUST] problem-statement.md exists',
    '',
    '==================================================',
    'Summary: 5 compliant, 0 non-compliant, 0 review, 0 info — 5 total',
    'ALL GATES COMPLIANT — ready to advance',
  ].join('\n')

  const BLOCKED = [
    'Gate Check Results — Phase 0',
    '==================================================',
    '',
    '  [G1]',
    '    NON-COMPLIANT  [MUST] problem-statement.md is missing',
    '    COMPLIANT      [MUST] constitution.md exists',
    '  [G2]',
    '    NON-COMPLIANT  [SHOULD] success-criteria.md has a placeholder',
    '',
    '==================================================',
    'Summary: 1 compliant, 2 non-compliant, 0 review, 0 info — 3 total',
    'BLOCKED — 1 MUST gate(s) non-compliant. Fix before advancing.',
  ].join('\n')

  it('reads a clean pass as not blocked, with no failures', () => {
    const result = parseGateCheckOutput(PASS)
    expect(result.blocked).toBe(false)
    expect(result.mustFailures).toEqual([])
  })

  it('reads a MUST failure as blocked, naming only the MUST line', () => {
    const result = parseGateCheckOutput(BLOCKED)
    expect(result.blocked).toBe(true)
    expect(result.mustFailures).toEqual(['problem-statement.md is missing'])
  })

  it('keeps the full text for display, whichever way it goes', () => {
    expect(parseGateCheckOutput(BLOCKED).raw).toBe(BLOCKED)
  })

  it('reads a MUST failure on CRLF-terminated lines the same way — the real script prints CRLF on Windows', () => {
    // `.` does not match a line terminator, so a trailing \r left on a split-by-\n line
    // defeats `(.+)$` silently: found by exactly this — a freshly initialised project read as
    // "not blocked" because every real line from the Windows subprocess ends in \r\n.
    const result = parseGateCheckOutput(BLOCKED.replace(/\n/g, '\r\n'))
    expect(result.blocked).toBe(true)
    expect(result.mustFailures).toEqual(['problem-statement.md is missing'])
  })
})

describe('setAsideLayer — pure file moves, no subprocess (studio-improvements F6)', () => {
  const dir = () => { const d = mkdtempSync(join(tmpdir(), 'studio-layer-')); made.push(d); return d }

  it('does nothing when there is no layer yet, and restore is a no-op', () => {
    const layer = join(dir(), 'phase0-discovery.md')
    const aside = setAsideLayer(layer)
    expect(aside.supersededPath).toBeNull()
    expect(() => aside.restore()).not.toThrow()
    expect(existsSync(layer)).toBe(false)
  })

  it('keeps the previous layer under /sprd-next\'s own name, dated', () => {
    const layer = join(dir(), 'phase0-discovery.md')
    writeFileSync(layer, 'reviewed')
    const aside = setAsideLayer(layer, new Date('2026-10-05T12:00:00Z'))
    expect(aside.supersededPath).toBe(`${layer}.superseded-20261005`)
    expect(existsSync(layer)).toBe(false)
    expect(readFileSync(aside.supersededPath!, 'utf-8')).toBe('reviewed')
  })

  it('restore puts the previous layer back byte-for-byte and removes the failed draft', () => {
    const layer = join(dir(), 'phase0-discovery.md')
    writeFileSync(layer, 'reviewed\r\nlayer\r\n')
    const aside = setAsideLayer(layer)
    writeFileSync(layer, 'an invalid draft')
    aside.restore()
    expect(readFileSync(layer, 'utf-8')).toBe('reviewed\r\nlayer\r\n')
    expect(existsSync(aside.supersededPath!)).toBe(false)
  })

  it('a second sign-off on the same day does not overwrite the first one\'s history', () => {
    const layer = join(dir(), 'phase0-discovery.md')
    const day = new Date('2026-10-05T12:00:00Z')
    writeFileSync(layer, 'first')
    setAsideLayer(layer, day)
    writeFileSync(layer, 'second')
    const aside = setAsideLayer(layer, day)
    expect(aside.supersededPath).toBe(`${layer}.superseded-20261005-2`)
    expect(readFileSync(`${layer}.superseded-20261005`, 'utf-8')).toBe('first')
    expect(readFileSync(aside.supersededPath!, 'utf-8')).toBe('second')
  })
})

describe('signOffStage refuses Build before reading anything (studio-improvements F3)', () => {
  it('names Closing as where Build ends', async () => {
    const result = await signOffStage(join(tmpdir(), 'no-such-project'), join(tmpdir(), 'no-such-plugin'), 'claude', 'build', 'Matt K', [])
    if (result.ok) throw new Error('expected a refusal')
    expect(result.stage).toBe('build')
    expect(result.error).toMatch(/Closing/)
  })
})

describe.skipIf(!PLUGIN.available)('checkStageGates, against the real plugin', () => {
  it('fails CLOSED when the script cannot run at all — a missing state file is not a clean pass', async () => {
    const nowhere = mkdtempSync(join(tmpdir(), 'studio-nostate-'))
    made.push(nowhere)
    const result = await checkStageGates(nowhere, SCRIPTS_DIR, '0')
    expect(result.blocked).toBe(true)
    expect(result.mustFailures).toHaveLength(1)
    expect(result.mustFailures[0]).toMatch(/did not complete/)
    expect(result.mustFailures[0]).toMatch(/State file not found/)
  }, 60_000)

  it('blocks a freshly initialised project, naming a missing artifact', async () => {
    const s = await scenario(null)
    const result = await checkStageGates(s.project, SCRIPTS_DIR, '0')
    expect(result.blocked).toBe(true)
    expect(result.mustFailures.length).toBeGreaterThan(0)
  }, 60_000)

  it('passes once Phase 0 has its five artifacts', async () => {
    const s = await scenario(PHASE0)
    const result = await checkStageGates(s.project, SCRIPTS_DIR, '0')
    expect(result.blocked, result.raw).toBe(false)
  }, 60_000)
})

describe.skipIf(!PLUGIN.available)('signOffStage, against the real plugin', () => {
  it('is refused without a name', async () => {
    const s = await scenario(PHASE0)
    const result = await signOffStage(s.project, SCRIPTS_DIR, 'claude', '0', '   ', [])
    if (result.ok) throw new Error('expected a refusal')
    expect(result.stage).toBe('name')
  }, 60_000)

  it('is refused when a judgement question has not been confirmed, and names one', async () => {
    const s = await scenario(PHASE0)
    const result = await signOffStage(s.project, SCRIPTS_DIR, 'claude', '0', 'Matt K', [])
    if (result.ok) throw new Error('expected a refusal')
    expect(result.stage).toBe('confirmations')
    expect(result.error).toMatch(/confirm/i)
  }, 60_000)

  it('is refused with the plugin\'s own blocker text when a MUST gate fails', async () => {
    // Confirmations must be out of the way first, or this could fail on either check and
    // prove nothing specific — the gate failure has to be the ONLY thing left standing.
    const s = await scenario(null)
    confirmAllJudgementQuestions(s.project, '0')
    const result = await signOffStage(s.project, SCRIPTS_DIR, 'claude', '0', 'Matt K', [])
    if (result.ok) throw new Error('expected a refusal')
    expect(result.stage).toBe('gates')
    expect(result.error).toMatch(/NON-COMPLIANT|MUST|missing/i)
    expect(phaseOf(s.project)).toBe('0')
  }, 60_000)

  it('is refused for a stage that is not the project\'s current one', async () => {
    const s = await scenario(PHASE0)
    const result = await signOffStage(s.project, SCRIPTS_DIR, 'claude', '1', 'Matt K', [])
    if (result.ok) throw new Error('expected a refusal')
    expect(result.stage).toBe('not-current')
  }, 60_000)

  describe.skipIf(process.env.STUDIO_SKIP_LIVE_MODEL === '1')('with a real Claude call', () => {
    it('drafts a valid frozen layer, advances the phase, and the layer reaches the remote', async () => {
      // Real substance, not the placeholder one-liners above: the frozen layer's own minimum
      // (1000 tokens) is a floor an honest condensation of near-empty toy documents cannot
      // reach without inventing content, which the prompt explicitly forbids ("every value
      // must trace to a source artifact"). This is close to what a real Phase 0 actually has.
      const s = await scenario(RICH_PHASE0)
      confirmAllJudgementQuestions(s.project, '0')

      const result = await signOffStage(s.project, SCRIPTS_DIR, 'claude', '0', 'Matt K', [
        { discipline: 'Design', section: 'interaction-specs', by: 'Priya N' },
      ])
      expect(result.ok, JSON.stringify(result)).toBe(true)
      if (!result.ok) return
      expect(result.fromPhase).toBe('0')
      expect(result.toPhase).not.toBe('0')
      expect(phaseOf(s.project)).toBe(result.toPhase)

      const layerPath = join(s.project, '.sdlc', 'context', 'layers', 'phase0-discovery.md')
      expect(existsSync(layerPath), 'the frozen layer was not written locally').toBe(true)
      const layer = readFileSync(layerPath, 'utf-8')
      expect(layer).toContain('## Decision')
      expect(layer).toContain('## Key Outcomes')
      expect(layer).toContain('## Artifact Summary')
      expect(layer).not.toMatch(/\$\{[A-Z_]+\}/)

      git(['fetch', 'origin'], s.project)
      const remoteLayer = git(['show', 'origin/main:.sdlc/context/layers/phase0-discovery.md'], s.project)
      expect(remoteLayer).toBe(layer.replace(/\r\n/g, '\n').trimEnd())

      const state = git(['show', 'origin/main:.sdlc/state.yaml'], s.project)
      expect(state).toContain('signed_off_by: Matt K')
      expect(state).toContain('Priya N')
    }, 180_000)
  })
})
