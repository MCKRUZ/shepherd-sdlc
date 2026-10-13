/** The contract between Studio and the `claude` CLI (studio-improvements F1).
 *
 * Studio drives Claude Code with a fixed argv. One flag the installed CLI does not know is fatal
 * to every model call at once (`error: unknown option`), and it happened: `--permission-prompts`
 * exists in Claude Code 2.1.289 and not in 2.1.239, and the test fake accepted anything. Three
 * things are pinned here so it cannot recur silently:
 *
 *   1. every flag an argv builder emits is declared in REQUIRED_CLAUDE_FLAGS;
 *   2. parseHelpFlags reads a real `--help` (a fixture captured from 2.1.239) and declares
 *      nothing missing from it — the baseline this contract was built against;
 *   3. when `claude` is on this machine, its live `--help` declares nothing missing either.
 *      That is a process start, not a model call: zero cost, no STUDIO_SKIP_LIVE_MODEL gate.
 */

import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { buildAgentArgs } from '../electron/main/agentRun'
import { buildChatArgs } from '../electron/main/chat'
import { CLAUDE_SAFE_ARGS, CLAUDE_SHARED_SAFE_ARGS } from '../electron/main/claudeAssist'
import {
  CLAUDE_PERMISSION_MODE, claudeLacksMessage, missingClaudeFlags, parseHelpFlags, REQUIRED_CLAUDE_FLAGS,
} from '../shared/claudeContract'

const HELP_2_1_239 = readFileSync(join(__dirname, 'fixtures', 'claude-help-2.1.239.txt'), 'utf-8')

/** The flag tokens in an argv, up to the `--` separator (after it everything is the prompt). */
function flagsIn(args: readonly string[]): string[] {
  const out: string[] = []
  for (const a of args) {
    if (a === '--') break
    if (/^-{1,2}[A-Za-z][\w-]*$/.test(a)) out.push(a)
  }
  return out
}

describe('parseHelpFlags', () => {
  it('reads short and long forms, aliases, and placeholders — and not a flag merely mentioned in prose', () => {
    const synthetic = [
      'Usage: claude [options]',
      '',
      'Options:',
      '  -p, --print                           Print and exit',
      '  --allowedTools, --allowed-tools <tools...>',
      '      Comma or space-separated list (see --not-a-flag for the rest)',
      '  --permission-mode <mode>              Permission mode (choices: "dontAsk")',
      '  --verbose                             Override verbose mode',
      '',
    ].join('\n')
    const flags = parseHelpFlags(synthetic)
    for (const f of ['-p', '--print', '--allowedTools', '--allowed-tools', '--permission-mode', '--verbose']) {
      expect(flags.has(f), f).toBe(true)
    }
    expect(flags.has('--not-a-flag')).toBe(false)
    expect(flags.has('Comma')).toBe(false)
  })

  it('reads CRLF help text (the CLI on Windows) the same way', () => {
    expect(parseHelpFlags('Options:\r\n  --verbose    Verbose\r\n').has('--verbose')).toBe(true)
  })
})

describe('missingClaudeFlags', () => {
  it('declares nothing missing from Claude Code 2.1.239 — the baseline this contract was built against', () => {
    expect(missingClaudeFlags(HELP_2_1_239)).toEqual([])
  })

  it('names exactly the flag a help text lacks', () => {
    const without = HELP_2_1_239.split(/\r?\n/).filter((l) => !/^ {2}--permission-mode\b/.test(l)).join('\n')
    expect(missingClaudeFlags(without)).toEqual(['--permission-mode'])
  })

  it('reports EVERY flag missing for an empty help text — "could not read" must never read as "accepts all"', () => {
    expect(missingClaudeFlags('')).toEqual([...REQUIRED_CLAUDE_FLAGS])
  })

  it('phrases the one sentence Tooling and Settings show', () => {
    expect(claudeLacksMessage('2.1.100 (Claude Code)', ['--permission-mode', '--tools']))
      .toBe('Claude Code 2.1.100 lacks --permission-mode, --tools — update with `claude update`')
    expect(claudeLacksMessage(undefined, ['--tools'])).toMatch(/^Claude Code installed here lacks --tools/)
  })
})

describe('every argv builder stays inside the declared contract', () => {
  const chat = buildChatArgs({
    prompt: 'hello', projectPath: 'C:/fake/project', pluginRoot: 'C:/fake/plugin', pluginName: 'shepherd',
    stageId: '1', stageDisplay: 'Requirements', mcpConfig: 'C:/fake/mcp-config.json', resume: false,
    sessionId: '11111111-1111-1111-1111-111111111111',
  }).args
  const chatResumed = buildChatArgs({
    prompt: 'hello', projectPath: 'C:/fake/project', pluginRoot: 'C:/fake/plugin', pluginName: 'shepherd',
    stageId: '1', stageDisplay: 'Requirements', mcpConfig: 'C:/fake/mcp-config.json', resume: true,
    sessionId: '11111111-1111-1111-1111-111111111111',
  }).args
  const agent = buildAgentArgs({ kind: 'enhance', prompt: 'do', projectPath: 'C:/work/project', pluginRoot: 'C:/work/plugin' }).args
  const signOff = ['-p', ...CLAUDE_SAFE_ARGS] // signOff.ts / claudeAssist.ts / drafts.ts

  it.each([
    ['chat', chat], ['chat (resumed)', chatResumed], ['agent run', agent], ['sign-off / drafts / combine', signOff],
    ['shared safe args', CLAUDE_SHARED_SAFE_ARGS],
  ])('%s emits only declared flags', (_name, args) => {
    const undeclared = flagsIn(args).filter((f) => !REQUIRED_CLAUDE_FLAGS.includes(f))
    expect(undeclared).toEqual([])
  })

  it('every call runs under the one permission mode, and the old flag is gone', () => {
    for (const args of [chat, agent, signOff]) {
      const i = args.indexOf('--permission-mode')
      expect(i).toBeGreaterThan(-1)
      expect(args[i + 1]).toBe(CLAUDE_PERMISSION_MODE)
      expect(args).not.toContain('--permission-prompts')
    }
    expect(CLAUDE_PERMISSION_MODE).toBe('dontAsk')
  })

  it('REQUIRED_CLAUDE_FLAGS lists short forms first, then long forms in order, with no duplicates', () => {
    const shorts = REQUIRED_CLAUDE_FLAGS.filter((f) => !f.startsWith('--'))
    const longs = REQUIRED_CLAUDE_FLAGS.filter((f) => f.startsWith('--'))
    expect([...REQUIRED_CLAUDE_FLAGS]).toEqual([...shorts, ...longs])
    expect(longs).toEqual([...longs].sort((a, b) => a.localeCompare(b)))
    expect(new Set(REQUIRED_CLAUDE_FLAGS).size).toBe(REQUIRED_CLAUDE_FLAGS.length)
  })
})

function liveHelp(): string | null {
  try {
    // shell: true on Windows so a `claude.cmd` shim resolves; elsewhere the binary itself.
    return execFileSync('claude', ['--help'], { encoding: 'utf-8', timeout: 15_000, shell: process.platform === 'win32' })
  } catch {
    return null
  }
}
const LIVE_HELP = liveHelp()

describe.skipIf(LIVE_HELP === null)('the Claude Code installed on this machine', () => {
  it('declares every flag Studio emits — a process start, not a model call', () => {
    expect(missingClaudeFlags(LIVE_HELP!)).toEqual([])
  })
})
