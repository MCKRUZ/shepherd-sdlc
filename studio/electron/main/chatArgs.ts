// The chat-turn driver (spec 0016) — the CLI launch-argument half. See chat.ts's own header
// for the full set of measurements this is built from; split out here (chat.ts was over this
// repo's 400-line file convention) so "what arguments does a chat turn launch with" is a
// self-contained, independently readable unit.

import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { claudeWorkingDirectory, CLAUDE_SHARED_SAFE_ARGS } from './claudeAssist'
import { ASK_QUESTION_TOOL as ASK_QUESTION, PROPOSE_WRITE_TOOL as PROPOSE_WRITE } from './chatMcpServer'
import { hostLabel, type HostName } from '../../shared/codeHostModel'
import { PLUGIN_ID } from '../../shared/pluginId'


// --- the fixed tool surface ---------------------------------------------------------------
// An explicit ALLOW-list, not a block-list (spec's own acceptance check: provable by
// asserting the launch arguments equal a fixed list, not by asserting three names are
// missing). Edit, Write and Bash never appear anywhere in this file. PROPOSE_WRITE/ASK_QUESTION
// are imported from chatMcpServer.ts — the single source of truth for this server's own name
// and tool names — rather than re-declared here, where a typo would silently create a tool
// name the server never actually serves.

/** The exact, complete tool list every chat session gets — nothing more, nothing less. A test
 * asserts buildChatArgs() output contains exactly this, comma-joined, as the value that
 * follows --tools (and again after --allowedTools, since denying prompts (--permission-mode
 * dontAsk) denies an MCP tool call outright without an explicit allow — measured live; Read/Grep/Glob/Task did
 * not need it, but granting it uniformly is simpler and strictly no wider than --tools already
 * allows). */
export const CHAT_TOOLS = ['Read', 'Grep', 'Glob', 'Task', PROPOSE_WRITE, ASK_QUESTION] as const

// --- locating the plugin's own name -------------------------------------------------------

/** The plugin's own declared name (`.claude-plugin/plugin.json`'s "name" field) — what a
 * Task-tool subagent_type must be prefixed with once --plugin-dir loads it. Never hardcoded:
 * a fork or rename of the plugin must keep working without a source change here. */
export function readPluginName(pluginRoot: string): string {
  const manifestPath = join(pluginRoot, '.claude-plugin', 'plugin.json')
  try {
    const parsed = JSON.parse(readFileSync(manifestPath, 'utf-8'))
    if (typeof parsed.name === 'string' && parsed.name) return parsed.name
  } catch { /* fall through to the fallback below */ }
  return PLUGIN_ID // this plugin's own known name, if the manifest is ever unreadable
}

// --- system prompt ---------------------------------------------------------------------
// Instructs the model WHERE to read this stage's real guidance and HOW to use its tools.
// Never restates phase content itself — that would be exactly the second, hand-authored copy
// the spec forbids. The model reads phases/NN-*.md and agents/*.md itself, at conversation
// time, through the real, granted file access.

export function buildSystemPrompt(opts: {
  projectPath: string
  pluginRoot: string
  pluginName: string
  stageId: string
  stageDisplay: string
  host?: HostName
}): string {
  return [
    'You are the SDLC assistant inside Shepherd\'s chat panel, authoring this project\'s '
      + 'documents through a live conversation. You have no Edit, Write or Bash tool — you '
      + 'cannot and must not write to any file yourself, on this machine or any other, by any '
      + 'means. Never claim a write happened; only ProposeWrite reaches the person, and only '
      + 'they decide whether it is ever saved.',
    '',
    `Project root (real, read-only access granted): ${opts.projectPath}`,
    `Plugin root (real, read-only access granted): ${opts.pluginRoot}`,
    `Current stage: ${opts.stageId} — ${opts.stageDisplay}`,
    '',
    'Before asking anything, locate and fully read this stage\'s own phase guidance file — '
      + `glob for it under ${opts.pluginRoot}/phases/ (its name starts with the stage id above, `
      + 'e.g. "0-*.md" or "01-*.md" — check both patterns) — and read the project\'s own current '
      + `state (${opts.projectPath}/.sdlc/state.yaml and this stage's artifact folder) to see `
      + 'what is already written. Follow that phase file\'s own step order exactly. If the '
      + 'person free-types something the interview has not reached yet, acknowledge it briefly '
      + 'and redirect back to the current step — do not reorder or skip ahead on your own '
      + 'judgement.',
    '',
    'When the phase guidance calls for one of the plugin\'s own discipline sub-agents (for '
      + 'example discovery-analyst), spawn it with the Task tool using '
      + `subagent_type "${opts.pluginName}:<agent-name>" — the bare name will be rejected. `
      + 'Relay its own findings; never paraphrase them as if they were your own.',
    '',
    'To propose writing a field of a document, call the ProposeWrite tool with the document\'s '
      + 'repo-relative path, the section, the field label, and the proposed text. This does '
      + 'NOT write anything — it only shows the person a proposal card. The field label must be '
      + 'copied EXACTLY, character for character, from that document\'s own shape file (glob for '
      + `it under ${opts.pluginRoot}/templates/phases/**/*.shape.yaml — each field is declared `
      + 'as "- label: <exact text>"). Do not paraphrase, retitle, reword, or guess a label: the '
      + 'write is matched against that exact key with no fuzzy correction, so a label that does '
      + 'not match character-for-character fails to save with no useful signal why. If you '
      + 'cannot find the field\'s exact declared label, read the shape file again rather than '
      + 'inventing one.',
    '',
    `You cannot run commands, so you cannot read ${hostLabel(opts.host)} yourself. When the person needs evidence `
      + 'about this repository\'s delivery pipeline (which CI rails have fired, whether branch '
      + 'protection is enforcing, which pull requests merged), tell them to use the "Gather '
      + `pipeline evidence" button on the Foundation stage, which reads ${hostLabel(opts.host)} and writes `
      + '.sdlc/artifacts/03-foundation/pipeline-proof.md — then read that file and help them with '
      + 'it. Do not write them a prompt to paste into another session; they should never have to '
      + 'leave this app for it.',
    '',
    'A user message that begins "[Studio]" names the document and step the person has just '
      + 'opened in the app: treat it as the current step, and as the brief for the discipline '
      + 'sub-agent that owns it, instead of redirecting them back to the interview.',
    '',
    'A single reply may call ProposeWrite or AskStructuredQuestion more than once if you have '
      + 'more than one proposal or question ready — each call produces its own separate card, '
      + 'and none of them overwrite each other.',
    '',
    'To ask a structured, multiple-choice question, call the AskStructuredQuestion tool, then '
      + 'END YOUR TURN immediately — say nothing else after calling it. Never ask a '
      + 'multiple-choice question as plain prose the person has to type an answer to.',
  ].join('\n')
}

// --- building the CLI arguments ------------------------------------------------------------

export interface ChatArgsOptions {
  prompt: string
  projectPath: string
  pluginRoot: string
  pluginName: string
  stageId: string
  stageDisplay: string
  mcpConfig: string
  /** Present to --resume this session; absent (with sessionId still required) to start a new
   * one with --session-id. */
  resume: boolean
  sessionId: string
  /** The project's code host (ConnectionInfo.host), for the sentence about the pipeline-evidence
   * button. Absent reads as GitHub — today's wording. */
  host?: HostName
}

/** Pure: no I/O, no process spawn — every acceptance check about "the session's own launch
 * arguments" (the tool list, the working-directory isolation, Edit/Write/Bash's absence) is
 * provable by calling this and asserting on its output, without spawning a real process. */
export function buildChatArgs(opts: ChatArgsOptions): { command: string; args: string[]; cwd: string } {
  const toolList = CHAT_TOOLS.join(',')
  const args = [
    '--add-dir', opts.projectPath, opts.pluginRoot,
    '--plugin-dir', opts.pluginRoot,
    '--tools', toolList,
    '--allowedTools', toolList,
    '--mcp-config', opts.mcpConfig,
    // The flags every `claude` invocation in this app shares (claudeAssist.ts) — chat.ts pins
    // its tool surface with the explicit --tools/--allowedTools allow-list above rather than
    // claudeAssist's --disallowedTools deny-list, so only the truly shared part is reused here.
    ...CLAUDE_SHARED_SAFE_ARGS,
    '--output-format', 'stream-json',
    '--input-format', 'text',
    '--verbose',
    '--forward-subagent-text',
    opts.resume ? '--resume' : '--session-id', opts.sessionId,
    '--append-system-prompt', buildSystemPrompt(opts),
    // `-p -- <prompt>` MUST be last. `--` is not scoped to just the one value after it — it
    // tells the CLI's parser to stop reading flags AT ALL from that point on, so every flag
    // after it would be read as a positional word instead (reproduced: with any flag after
    // `--`, --output-format stream-json silently stopped applying and the CLI fell back to
    // plain conversational output, no error, no warning). `--` in front of the prompt is still
    // needed — a message starting with "-" is otherwise read as an unknown flag (also
    // reproduced) — it's the ORDER that was wrong, not the idea.
    '-p', '--', opts.prompt,
  ]
  return { command: 'claude', args, cwd: claudeWorkingDirectory() }
}
