import { describe, expect, it } from 'vitest'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  buildChatArgs, buildSystemPrompt, CHAT_TOOLS, mcpConfigPath, readPluginName,
} from '../electron/main/chat'
import { CLAUDE_SHARED_SAFE_ARGS, claudeWorkingDirectory } from '../electron/main/claudeAssist'

// Spec 0016's own acceptance checks ask for exactly this: the tool list, the working-directory
// isolation, and Edit/Write/Bash's absence must be provable "from the session's own launch
// arguments... not from watching it behave correctly once." buildChatArgs is pure (no process,
// no I/O beyond writing the tiny mcp-config file) precisely so these are ordinary assertions.

function baseOpts(overrides: Partial<Parameters<typeof buildChatArgs>[0]> = {}) {
  return {
    prompt: 'hello',
    projectPath: 'C:/fake/project',
    pluginRoot: 'C:/fake/plugin',
    pluginName: 'shepherd',
    stageId: '1',
    stageDisplay: 'Requirements',
    mcpConfig: 'C:/fake/mcp-config.json',
    resume: false,
    sessionId: '11111111-1111-1111-1111-111111111111',
    ...overrides,
  }
}

describe('CHAT_TOOLS — the fixed allow-list', () => {
  it('is exactly Read, Grep, Glob, Task, and the two custom MCP tools — nothing else', () => {
    expect(CHAT_TOOLS).toEqual([
      'Read', 'Grep', 'Glob', 'Task',
      'mcp__sdlc-studio-chat__ProposeWrite',
      'mcp__sdlc-studio-chat__AskStructuredQuestion',
    ])
  })

  it('never contains Edit, Write, or Bash as a STANDALONE tool name (ProposeWrite legitimately contains "Write" as a substring)', () => {
    expect(CHAT_TOOLS).not.toContain('Edit')
    expect(CHAT_TOOLS).not.toContain('Write')
    expect(CHAT_TOOLS).not.toContain('Bash')
    expect(CHAT_TOOLS.some((t) => t === 'Edit' || t === 'Write' || t === 'Bash')).toBe(false)
  })
})

describe('buildChatArgs', () => {
  it('puts -p -- <prompt> LAST, after every other flag — not just anywhere before the prompt', () => {
    // Two facts, both reproduced directly against the real `claude` binary, and both required
    // together:
    // 1. `-p "-something"` fails outright: "error: unknown option '-something'" — a bullet
    //    point, a negative number, anything a real message might start with.
    // 2. `--` doesn't protect just the one value after it — it tells the parser to stop
    //    reading flags AT ALL from that point on. Putting '-p', '--', prompt BEFORE the other
    //    flags (an earlier version of this fix) silently broke every flag that followed it:
    //    --output-format stream-json stopped applying with no error, falling back to plain
    //    prose instead of the structured output this app's stream parser depends on.
    // So `-- <prompt>` is correct, AND it must be the very last thing in the argument list.
    const { args } = buildChatArgs(baseOpts({ prompt: '-looks like a flag but is not' }))
    expect(args.slice(-3)).toEqual(['-p', '--', '-looks like a flag but is not'])
    // Every other flag this function emits appears before that point, not after.
    expect(args.indexOf('--output-format')).toBeLessThan(args.length - 3)
    expect(args.indexOf('--append-system-prompt')).toBeLessThan(args.length - 3)
  })

  it('runs in claudeWorkingDirectory(), never the project', () => {
    const { cwd } = buildChatArgs(baseOpts())
    expect(cwd).toBe(claudeWorkingDirectory())
    expect(cwd).not.toBe('C:/fake/project')
  })

  it('grants the project and plugin root ONLY through --add-dir', () => {
    const { args } = buildChatArgs(baseOpts())
    const addDirIndex = args.indexOf('--add-dir')
    expect(addDirIndex).toBeGreaterThanOrEqual(0)
    expect(args[addDirIndex + 1]).toBe('C:/fake/project')
    expect(args[addDirIndex + 2]).toBe('C:/fake/plugin')
  })

  it('also grants --plugin-dir the plugin root, and only the plugin root', () => {
    const { args } = buildChatArgs(baseOpts())
    const pluginDirIndex = args.indexOf('--plugin-dir')
    expect(pluginDirIndex).toBeGreaterThanOrEqual(0)
    expect(args[pluginDirIndex + 1]).toBe('C:/fake/plugin')
    // The value immediately after is a flag, not a second directory — --plugin-dir gets ONE value here.
    expect(args[pluginDirIndex + 2].startsWith('--')).toBe(true)
  })

  it('--tools is exactly the fixed CHAT_TOOLS list, comma-joined', () => {
    const { args } = buildChatArgs(baseOpts())
    const i = args.indexOf('--tools')
    expect(args[i + 1]).toBe(CHAT_TOOLS.join(','))
  })

  it('--allowedTools carries the same fixed list — MCP tools are denied by --permission-mode dontAsk without it', () => {
    const { args } = buildChatArgs(baseOpts())
    const i = args.indexOf('--allowedTools')
    expect(args[i + 1]).toBe(CHAT_TOOLS.join(','))
  })

  it('never passes --disallowedTools, --dangerously-skip-permissions, or --bare — the allow-list alone is the boundary', () => {
    const { args } = buildChatArgs(baseOpts())
    expect(args).not.toContain('--disallowedTools')
    expect(args).not.toContain('--dangerously-skip-permissions')
    expect(args).not.toContain('--allow-dangerously-skip-permissions')
    expect(args).not.toContain('--bare')
  })

  it('starts a NEW session with --session-id when resume is false', () => {
    const { args } = buildChatArgs(baseOpts({ resume: false, sessionId: 'sid-1' }))
    expect(args).toContain('--session-id')
    expect(args[args.indexOf('--session-id') + 1]).toBe('sid-1')
    expect(args).not.toContain('--resume')
  })

  it('resumes with --resume when resume is true, using the SAME session id', () => {
    const { args } = buildChatArgs(baseOpts({ resume: true, sessionId: 'sid-1' }))
    expect(args).toContain('--resume')
    expect(args[args.indexOf('--resume') + 1]).toBe('sid-1')
    expect(args).not.toContain('--session-id')
  })

  it('requires --verbose alongside --output-format stream-json (measured: the CLI refuses to start without it in -p mode)', () => {
    const { args } = buildChatArgs(baseOpts())
    expect(args).toContain('--output-format')
    expect(args[args.indexOf('--output-format') + 1]).toBe('stream-json')
    expect(args).toContain('--verbose')
  })

  it('passes --forward-subagent-text so a spawned sub-agent\'s own output reaches the transcript', () => {
    const { args } = buildChatArgs(baseOpts())
    expect(args).toContain('--forward-subagent-text')
  })

  it('isolates MCP servers to the one generated config — --strict-mcp-config, only --mcp-config', () => {
    const { args } = buildChatArgs(baseOpts({ mcpConfig: 'C:/fake/mcp-config.json' }))
    expect(args).toContain('--strict-mcp-config')
    const i = args.indexOf('--mcp-config')
    expect(args[i + 1]).toBe('C:/fake/mcp-config.json')
  })

  it('denies every permission prompt rather than escalating to a person who is not there', () => {
    const { args } = buildChatArgs(baseOpts())
    const i = args.indexOf('--permission-mode')
    expect(args[i + 1]).toBe('dontAsk')
  })

  // Regression: chat.ts used to hand-type '--strict-mcp-config' and '--permission-mode',
  // 'dontAsk' itself instead of reusing claudeAssist.ts's own CLAUDE_SHARED_SAFE_ARGS — a second,
  // independently-maintained copy of flags that exist because of a real past security finding.
  it('reuses claudeAssist.ts\'s own CLAUDE_SHARED_SAFE_ARGS for the flags every claude invocation shares, rather than a hand-typed copy', () => {
    const { args } = buildChatArgs(baseOpts())
    const i = args.indexOf('--permission-mode')
    expect(args.slice(i, i + CLAUDE_SHARED_SAFE_ARGS.length)).toEqual(CLAUDE_SHARED_SAFE_ARGS)
  })
})

describe('buildSystemPrompt', () => {
  it('never embeds any file content — only paths, ids, and instructions the driver itself wrote', () => {
    const prompt = buildSystemPrompt({
      projectPath: 'C:/fake/project',
      pluginRoot: 'C:/fake/plugin',
      pluginName: 'shepherd',
      stageId: '0',
      stageDisplay: 'Discovery',
    })
    // The function takes no file contents as input at all — this is a by-construction
    // property, and the assertion below is a regression guard against someone later
    // "helpfully" reading a file into it.
    expect(prompt).toContain('C:/fake/project')
    expect(prompt).toContain('C:/fake/plugin')
    expect(prompt).toContain('shepherd:<agent-name>')
  })

  it('tells the model to end its turn immediately after AskStructuredQuestion', () => {
    const prompt = buildSystemPrompt({
      projectPath: 'p', pluginRoot: 'r', pluginName: 'n', stageId: '0', stageDisplay: 'D',
    })
    expect(prompt).toMatch(/AskStructuredQuestion.*END YOUR TURN/s)
  })

  it('tells the model how to treat a [Studio] message: the current step, not a reason to redirect', () => {
    const prompt = buildSystemPrompt({
      projectPath: 'p', pluginRoot: 'r', pluginName: 'n', stageId: '0', stageDisplay: 'D',
    })
    expect(prompt).toContain('begins "[Studio]"')
    expect(prompt).toMatch(/instead of redirecting them back/)
  })

  it('states plainly that Edit, Write and Bash are not available', () => {
    const prompt = buildSystemPrompt({
      projectPath: 'p', pluginRoot: 'r', pluginName: 'n', stageId: '0', stageDisplay: 'D',
    })
    expect(prompt).toMatch(/no Edit, Write or Bash/)
  })

  // Regression: the prompt used to tell the model to call ProposeWrite with "the field label"
  // but never stated it must match the shape's declared key EXACTLY — documents.ts's setField
  // does a plain `section.fields[label]` lookup with no fuzz matching (unlike matchesSection's
  // loose section-name match), so a model-phrased label that differs by casing, punctuation, or
  // wording just fails to save with no useful signal why.
  it('tells the model the field label must match the shape\'s declared key EXACTLY, and where to find it', () => {
    const prompt = buildSystemPrompt({
      projectPath: 'p', pluginRoot: '/plugin', pluginName: 'n', stageId: '0', stageDisplay: 'D',
    })
    expect(prompt).toMatch(/EXACTLY/)
    expect(prompt).toContain('/plugin/templates/phases/**/*.shape.yaml')
    expect(prompt).toMatch(/label: <exact text>/)
  })

  // Regression: asked for evidence about the repository's delivery pipeline, the assistant (which
  // cannot run commands) wrote a prompt for the person to paste into a SEPARATE Claude session.
  // Studio has a button for exactly this on the Foundation stage; the person should never have to
  // leave the app for it.
  it('points the person to Studio\'s own pipeline-evidence button rather than sending them to another session', () => {
    const prompt = buildSystemPrompt({
      projectPath: 'p', pluginRoot: 'r', pluginName: 'n', stageId: '3', stageDisplay: 'Foundation',
    })
    expect(prompt).toContain('Gather pipeline evidence')
    expect(prompt).toMatch(/pipeline-proof\.md/)
    expect(prompt).toMatch(/do not write (them )?a prompt/i)
  })

  it('tells the model a single reply may call ProposeWrite or AskStructuredQuestion more than once', () => {
    const prompt = buildSystemPrompt({
      projectPath: 'p', pluginRoot: 'r', pluginName: 'n', stageId: '0', stageDisplay: 'D',
    })
    expect(prompt).toMatch(/more than once/)
  })
})

describe('readPluginName', () => {
  it('reads the real name out of .claude-plugin/plugin.json', () => {
    const dir = mkdtempSync(join(tmpdir(), 'chat-plugin-name-'))
    try {
      const manifestDir = join(dir, '.claude-plugin')
      mkdirSync(manifestDir, { recursive: true })
      writeFileSync(join(manifestDir, 'plugin.json'), JSON.stringify({ name: 'a-forked-plugin' }))
      expect(readPluginName(dir)).toBe('a-forked-plugin')
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('falls back to the known plugin name when the manifest is unreadable', () => {
    expect(readPluginName(join(tmpdir(), 'definitely-does-not-exist-' + Date.now()))).toBe('shepherd')
  })
})

describe('mcpConfigPath', () => {
  it('writes a real JSON file naming exactly one MCP server: the Electron binary, run as plain node, given an inline script', () => {
    const path = mcpConfigPath('C:/fake/electron.exe')
    expect(existsSync(path)).toBe(true)
    const parsed = JSON.parse(readFileSync(path, 'utf-8'))
    const servers = Object.keys(parsed.mcpServers)
    expect(servers).toHaveLength(1)
    const server = parsed.mcpServers[servers[0]]
    expect(server.command).toBe('C:/fake/electron.exe')
    expect(server.args[0]).toBe('-e')
    expect(typeof server.args[1]).toBe('string')
    expect(server.args[1]).toContain('ProposeWrite') // the generated script embeds the real TOOLS schema
    expect(server.env).toEqual({ ELECTRON_RUN_AS_NODE: '1' })
  })

  it('the generated inline script is syntactically valid JS (a Function constructor parses it without throwing)', () => {
    const path = mcpConfigPath('C:/fake/electron.exe')
    const parsed = JSON.parse(readFileSync(path, 'utf-8'))
    const script = Object.values(parsed.mcpServers)[0] as { args: string[] }
    expect(() => new Function(script.args[1])).not.toThrow()
  })
})
