/** Spec 0029's analyse job against the REAL plugin scripts and a stand-in `claude`: one run of the
 * discovery-analyst, whose reply must be both documents between exact marker lines. A reply that is not
 * exactly that produces one failed result and no candidate. */

import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { cancelBatch, getBatchState, resetBatchStateForTests, startBatch } from '../electron/main/draftBatch'
import { activeBatch } from '../electron/main/draftBatchState'
import type { BatchState } from '../shared/types'
import { batchDeps, intakePath, makeIntakeProject, scriptedClaude, until, writeSummary, type ScriptEntry } from './batchHarness'
import { differences, snapshot } from './draftHarness'
import { requirePlugin } from './pluginRoot'

const PLUGIN = requirePlugin(__dirname)
const CONTRADICTIONS = '.sdlc/artifacts/00-discovery/contradiction-list.md'
const QUESTIONS = '.sdlc/artifacts/00-discovery/question-list.md'
const C = '=== FILE: contradiction-list.md ==='
const Q = '=== FILE: question-list.md ==='
const END = '=== END ==='
const REPLY = [C, '# Contradictions', '', 'DOC-001 and DOC-002 disagree.', Q, '# Questions', '', 'Q-01 Who owns it?', END].join('\n')

describe.skipIf(!PLUGIN.available)('the analyse job', () => {
  let project = ''
  beforeEach(() => {
    resetBatchStateForTests()
    project = makeIntakeProject(PLUGIN, { files: { 'a.md': '# a\n', 'b.md': '# b\n', 'c.md': '# c\n' } })
    writeSummary(project, 'DOC-001', 'a')
    writeSummary(project, 'DOC-002', 'b')
  })
  afterEach(() => {
    resetBatchStateForTests()
    rmSync(project, { recursive: true, force: true })
  })

  const state = (): BatchState => getBatchState(project)
  const finished = () => until(() => state().job !== null && state().job!.phase !== 'running' && !activeBatch(), 'the analysis to end')
  async function analyse(script: Record<string, ScriptEntry> = {}) {
    const claude = scriptedClaude(script)
    const deps = batchDeps(claude)
    const started = startBatch(project, PLUGIN.scriptsDir, 'analyse', deps)
    return { claude, deps, started }
  }
  const reply = (text: string): Record<string, ScriptEntry> => ({ analysis: { behaviour: 'text', text } })

  it('runs ONE discovery-analyst run with this exact argument list, and gives it paths, not text', async () => {
    const { claude, started } = await analyse()
    expect(started).toMatchObject({ ok: true, job: { kind: 'analyse', total: 1, done: 0, phase: 'running' } })
    await finished()

    expect(claude.started()).toEqual(['analysis'])
    const root = resolve(PLUGIN.scriptsDir, '..')
    const folder = join(project, '.sdlc', 'context', 'intake')
    expect(claude.log()[0].argv).toEqual([
      '--plugin-dir', root, '--add-dir', project, root,
      '--agent', 'shepherd:discovery-analyst',
      '--tools', 'Read,Grep,Glob', '--allowedTools', 'Read,Grep,Glob',
      '--permission-mode', 'dontAsk', '--strict-mcp-config',
      '--output-format', 'stream-json', '--verbose',
      '-p', '--',
      `Analyse the intake corpus of this project as your instructions describe, reading ${join(folder, 'index.md')}, ${join(folder, 'catalog.json')} and the summaries in ${folder}. `
      + 'You cannot save files in this session: do not try. '
      + 'Reply with ONLY the two documents, each introduced by an exact marker line, in this order and nothing else: '
      + 'a line === FILE: contradiction-list.md ===, the full markdown of contradiction-list.md, '
      + 'a line === FILE: question-list.md ===, the full markdown of question-list.md, and a final line === END ===.',
    ])
  })

  it('offers the two documents together, as candidates for the two analysis files', async () => {
    await analyse({ analysis: { cost: 0.31 } })
    await finished()

    expect(state().candidates).toEqual([
      {
        id: 'contradiction-list', target: CONTRADICTIONS, label: 'contradiction-list.md', status: 'ready',
        text: '# Contradiction list\n\nDOC-001 and DOC-002 disagree.', replacesExisting: false,
      },
      {
        id: 'question-list', target: QUESTIONS, label: 'question-list.md', status: 'ready',
        text: '# Question list\n\nQ-01 Who owns it?', replacesExisting: false,
      },
    ])
    expect(state().job).toMatchObject({ phase: 'finished', done: 1, total: 1, costUsd: 0.31 })
  })

  it('says a candidate replaces a file that is already there', async () => {
    mkdirSync(join(project, '.sdlc', 'artifacts', '00-discovery'), { recursive: true })
    writeFileSync(join(project, QUESTIONS), '# Written by hand\n')
    await analyse()
    await finished()
    expect(state().candidates.map((c) => [c.id, c.replacesExisting])).toEqual([['contradiction-list', false], ['question-list', true]])
  })

  describe('a reply that is not exactly both documents', () => {
    it.each([
      ['a missing contradiction marker', REPLY.replace(C, '')],
      ['a missing question marker', REPLY.replace(Q, '')],
      ['a missing end marker', REPLY.replace(END, '')],
      ['a duplicated marker', REPLY.replace(Q, `${Q}\n${Q}`)],
      ['an extra file', REPLY.replace(END, `=== FILE: notes.md ===\nmore\n${END}`)],
      ['the markers out of order', [Q, '# Q', C, '# C', END].join('\n')],
      ['a prose reply that saved the files itself', 'I wrote both files to .sdlc/artifacts/00-discovery/.'],
    ])('is one failed result and no candidate: %s', async (_name, text) => {
      await analyse(reply(text))
      await finished()
      expect(state().candidates).toEqual([{
        id: 'analysis', target: '', label: 'Analysis', status: 'failed', text: '',
        error: 'Claude did not return both documents in the expected form.', replacesExisting: false,
      }])
      expect(state().candidates.filter((c) => c.status === 'ready')).toEqual([])
      expect(state().job).toMatchObject({ phase: 'finished', done: 1 })
    })

    it('is a failed result with the run\'s own one line when the run itself fails', async () => {
      await analyse({ analysis: { behaviour: 'exit1' } })
      await finished()
      expect(state().candidates).toHaveLength(1)
      expect(state().candidates[0]).toMatchObject({ status: 'failed', label: 'Analysis', error: expect.stringMatching(/^Claude stopped with an error/) })
    })
  })

  it('refuses without two summarised documents, starting 0 processes', () => {
    rmSync(intakePath(project, 'DOC-002-b.md'))
    const claude = scriptedClaude()
    expect(startBatch(project, PLUGIN.scriptsDir, 'analyse', batchDeps(claude))).toEqual({ ok: false, error: 'Summarise at least two documents first' })
    expect(claude.log()).toEqual([])
  })

  it('is stopped by Cancel: the run is killed and there is nothing to keep', async () => {
    const { claude } = await analyse({ analysis: { behaviour: 'hang' } })
    await until(() => claude.started().length === 1, 'the run to start')
    cancelBatch()
    await finished()
    expect(state().job).toMatchObject({ phase: 'cancelled' })
    expect(state().candidates).toEqual([])
  })

  it.each([
    ['succeeds', {}],
    ['gives a reply that does not parse', reply('nothing useful')],
    ['fails', { analysis: { behaviour: 'exit1' as const } }],
  ])('writes nothing to the project when it %s', async (_name, script) => {
    const before = snapshot(project)
    await analyse(script)
    await finished()
    expect(differences(before, snapshot(project))).toEqual([])
  })
})
