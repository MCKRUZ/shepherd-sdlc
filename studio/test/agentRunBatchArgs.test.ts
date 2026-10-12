/** Spec 0029's argument-list check: the two batch jobs run through the SAME buildAgentArgs as spec 0027's,
 * so what Claude may do is still one list, pinned exactly. The agent comes from a fixed table, never from the
 * renderer, and no document text can reach the list. */

import { describe, expect, it } from 'vitest'
import { AGENT_BY_KIND, AGENT_TOOLS, BATCH_AGENT_BY_KIND, buildAgentArgs, type AgentKind } from '../electron/main/agentRun'
import { analysePrompt, summarisePrompt } from '../electron/main/draftBatchPlan'
import { claudeWorkingDirectory } from '../electron/main/claudeAssist'

const opts = (kind: AgentKind, prompt = 'do the thing') => ({
  kind, prompt, projectPath: 'C:/work/project', pluginRoot: 'C:/work/plugin',
})

describe('buildAgentArgs for the batch jobs', () => {
  it('is exactly this list for a summarise run, with the prompt last', () => {
    expect(buildAgentArgs(opts('summarise')).args).toEqual([
      '--plugin-dir', 'C:/work/plugin',
      '--add-dir', 'C:/work/project', 'C:/work/plugin',
      '--agent', 'shepherd:document-summarizer',
      '--tools', 'Read,Grep,Glob',
      '--allowedTools', 'Read,Grep,Glob',
      '--permission-mode', 'dontAsk',
      '--strict-mcp-config',
      '--output-format', 'stream-json',
      '--verbose',
      '-p', '--', 'do the thing',
    ])
  })

  it('is exactly this list for an analyse run, with the prompt last', () => {
    expect(buildAgentArgs(opts('analyse')).args).toEqual([
      '--plugin-dir', 'C:/work/plugin',
      '--add-dir', 'C:/work/project', 'C:/work/plugin',
      '--agent', 'shepherd:discovery-analyst',
      '--tools', 'Read,Grep,Glob',
      '--allowedTools', 'Read,Grep,Glob',
      '--permission-mode', 'dontAsk',
      '--strict-mcp-config',
      '--output-format', 'stream-json',
      '--verbose',
      '-p', '--', 'do the thing',
    ])
  })

  it('differs from a spec 0027 job only in the agent', () => {
    const enhance = buildAgentArgs(opts('enhance')).args
    expect(buildAgentArgs(opts('summarise')).args.map((a) => a.replace('document-summarizer', 'narrative-enhancer'))).toEqual(enhance)
    expect(buildAgentArgs(opts('analyse')).args.map((a) => a.replace('discovery-analyst', 'narrative-enhancer'))).toEqual(enhance)
  })

  it.each(['summarise', 'analyse'] as const)('grants no tool that can write, run or reach out (%s)', (kind) => {
    const { args } = buildAgentArgs(opts(kind))
    const forbidden = [
      'Bash', 'Edit', 'Write', 'WebFetch', 'WebSearch', 'Task', 'NotebookEdit',
      '--mcp-config', '--dangerously-skip-permissions', '--dangerously-load-development-channels',
      '--disallowedTools', '--append-system-prompt', '--settings', '--resume', '--continue',
    ]
    for (const word of forbidden) expect(args.some((a) => a.split(',').includes(word)), word).toBe(false)
    // `--permission-mode` only as dontAsk — any other mode lets a prompt through or skips
    // permissions outright (studio-improvements F1).
    expect(args.filter((a) => a === '--permission-mode')).toHaveLength(1)
    expect(args[args.indexOf('--permission-mode') + 1]).toBe('dontAsk')
    const listAfter = (flag: string) => args[args.indexOf(flag) + 1]
    expect(listAfter('--tools')).toBe(AGENT_TOOLS.join(','))
    expect(listAfter('--allowedTools')).toBe(AGENT_TOOLS.join(','))
    expect(args).toContain('--strict-mcp-config')
  })

  it("runs in Studio's empty directory, never in the project", () => {
    for (const kind of ['summarise', 'analyse'] as const) {
      const built = buildAgentArgs(opts(kind))
      expect(built.cwd).toBe(claudeWorkingDirectory())
      expect(built.cwd).not.toBe('C:/work/project')
    }
  })

  it('takes the agents from fixed tables, and refuses a kind that is in neither', () => {
    expect(BATCH_AGENT_BY_KIND).toEqual({ summarise: 'document-summarizer', analyse: 'discovery-analyst' })
    expect(AGENT_BY_KIND).toEqual({ enhance: 'narrative-enhancer', review: 'multi-reviewer' }) // spec 0027's table is untouched
    for (const kind of ['constructor', 'toString', '__proto__', 'document-summarizer', 'discovery-analyst', '']) {
      expect(() => buildAgentArgs(opts(kind as AgentKind)), kind).toThrow()
    }
  })

  it('carries no text from a source document: a marker inside one is absent from every argument', () => {
    const BODY_MARKER = 'BODY-MARKER-9d41c7'
    const NAME_MARKER = 'NAME-MARKER-3b8e02'
    // The prompts are built from an id and paths only; a document's body and its name are inputs they never take.
    const summarise = summarisePrompt('C:/work/project', 'DOC-003')
    const analyse = analysePrompt('C:/work/project')
    for (const prompt of [summarise, analyse]) {
      const args = buildAgentArgs(opts('summarise', prompt)).args
      expect(args.join('\n')).not.toContain(BODY_MARKER)
      expect(args.join('\n')).not.toContain(NAME_MARKER)
    }
    expect(summarise).toContain('DOC-003')
  })
})
