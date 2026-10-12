/** Spec 0027's first acceptance check: what a model job may do is fixed in ONE argument list, and the
 * list is pinned by asserting it exactly, so every property (read-only tools, no MCP, isolated working
 * directory, fixed agent table) is provable without starting a process. */

import { describe, expect, it } from 'vitest'
import { AGENT_BY_KIND, AGENT_TOOLS, buildAgentArgs } from '../electron/main/agentRun'
import { CHAT_TOOLS } from '../electron/main/chatArgs'
import { claudeWorkingDirectory } from '../electron/main/claudeAssist'
import type { DraftKind } from '../shared/types'

const opts = (kind: DraftKind, prompt = 'do the thing') => ({
  kind, prompt, projectPath: 'C:/work/project', pluginRoot: 'C:/work/plugin',
})

describe('buildAgentArgs', () => {
  it('is exactly this list for an enhance job, with the prompt last', () => {
    expect(buildAgentArgs(opts('enhance')).args).toEqual([
      '--plugin-dir', 'C:/work/plugin',
      '--add-dir', 'C:/work/project', 'C:/work/plugin',
      '--agent', 'shepherd:narrative-enhancer',
      '--tools', 'Read,Grep,Glob',
      '--allowedTools', 'Read,Grep,Glob',
      '--permission-mode', 'dontAsk',
      '--strict-mcp-config',
      '--output-format', 'stream-json',
      '--verbose',
      '-p', '--', 'do the thing',
    ])
  })

  it('differs for a review job only in the agent', () => {
    const enhance = buildAgentArgs(opts('enhance')).args
    const review = buildAgentArgs(opts('review')).args
    expect(review.map((a) => a.replace('multi-reviewer', 'narrative-enhancer'))).toEqual(enhance)
    expect(review).toContain('shepherd:multi-reviewer')
  })

  it('keeps -p -- <prompt> last even when the prompt starts with a dash', () => {
    const { args } = buildAgentArgs(opts('enhance', '- looks like a flag'))
    expect(args.slice(-3)).toEqual(['-p', '--', '- looks like a flag'])
  })

  it.each(['enhance', 'review'] as const)('grants no tool that can write, run or reach out (%s)', (kind) => {
    const { args } = buildAgentArgs(opts(kind))
    const forbidden = [
      'Bash', 'Edit', 'Write', 'WebFetch', 'WebSearch', 'Task', 'NotebookEdit',
      '--mcp-config', '--dangerously-skip-permissions', '--dangerously-load-development-channels',
      '--disallowedTools', '--append-system-prompt', '--settings', '--resume', '--continue',
    ]
    for (const word of forbidden) {
      expect(args.some((a) => a.split(',').includes(word)), word).toBe(false)
    }
    // `--permission-mode` is allowed ONLY as dontAsk (studio-improvements F1 replaced
    // `--permission-prompts none` with it): any other mode would let a prompt through or skip
    // permissions outright, which is the finding this list exists to prevent.
    expect(args.filter((a) => a === '--permission-mode')).toHaveLength(1)
    expect(args[args.indexOf('--permission-mode') + 1]).toBe('dontAsk')
    // And the two tool lists are the same read-only list, nothing more.
    const listAfter = (flag: string) => args[args.indexOf(flag) + 1]
    expect(listAfter('--tools')).toBe(AGENT_TOOLS.join(','))
    expect(listAfter('--allowedTools')).toBe(AGENT_TOOLS.join(','))
    expect(args).toContain('--strict-mcp-config')
  })

  it("runs in Studio's empty directory, never in the project", () => {
    const built = buildAgentArgs(opts('enhance'))
    expect(built.cwd).toBe(claudeWorkingDirectory())
    expect(built.cwd).not.toBe('C:/work/project')
    expect(built.cwd).not.toBe('C:/work/plugin')
  })

  it("is narrower than the chat's tool surface, and a subset of it", () => {
    for (const tool of AGENT_TOOLS) expect(CHAT_TOOLS).toContain(tool)
    expect(AGENT_TOOLS.length).toBeLessThan(CHAT_TOOLS.length)
  })

  it('takes the agent from a fixed table, and refuses a kind that is not in it', () => {
    expect(AGENT_BY_KIND).toEqual({ enhance: 'narrative-enhancer', review: 'multi-reviewer' })
    expect(() => buildAgentArgs(opts('constructor' as DraftKind))).toThrow()
    expect(() => buildAgentArgs(opts('toString' as DraftKind))).toThrow()
    expect(() => buildAgentArgs(opts('narrative-enhancer' as DraftKind))).toThrow()
  })
})
