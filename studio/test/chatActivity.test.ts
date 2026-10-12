import { describe, expect, it } from 'vitest'
import { describeLatestActivity } from '../electron/main/chatStreamParse'

// Same fixture shape as chatStreamParse.test.ts (captured from the real `claude
// --output-format stream-json` during spec 0016's spike) — only the fields the activity
// reader actually uses.
function assistantLine(content: unknown[], parentToolUseId: string | null = null): string {
  return JSON.stringify({
    type: 'assistant',
    message: { role: 'assistant', content },
    parent_tool_use_id: parentToolUseId,
    uuid: `uuid-${Math.random()}`,
    session_id: 'session-1',
  })
}

const toolUse = (name: string, input: Record<string, unknown> = {}) => ({ type: 'tool_use', id: 't1', name, input })
const stream = (...lines: string[]) => lines.join('\n') + '\n'

describe('describeLatestActivity — what the person sees instead of "Thinking…"', () => {
  it('is null before the model has produced anything we can describe', () => {
    expect(describeLatestActivity('')).toBeNull()
    expect(describeLatestActivity(stream(JSON.stringify({ type: 'system', subtype: 'init' })))).toBeNull()
  })

  it('names the file being read by its base name, not its full path', () => {
    const out = stream(assistantLine([toolUse('Read', { file_path: String.raw`C:\proj\.sdlc\artifacts\01-requirements\requirements.md` })]))
    expect(describeLatestActivity(out)).toBe('Reading requirements.md')
  })

  it('reads a forward-slash path the same way', () => {
    const out = stream(assistantLine([toolUse('Read', { file_path: '/proj/phases/01.md' })]))
    expect(describeLatestActivity(out)).toBe('Reading 01.md')
  })

  it.each(['Grep', 'Glob'])('describes %s as searching the project', (name) => {
    expect(describeLatestActivity(stream(assistantLine([toolUse(name, { pattern: 'x' })])))).toBe('Searching the project')
  })

  it('names the sub-agent being consulted, without the plugin prefix', () => {
    const out = stream(assistantLine([toolUse('Task', { subagent_type: 'shepherd:discovery-analyst', description: 'd', prompt: 'p' })]))
    expect(describeLatestActivity(out)).toBe('Asking the discovery-analyst sub-agent')
  })

  it('falls back to a generic sub-agent label when the type is missing', () => {
    expect(describeLatestActivity(stream(assistantLine([toolUse('Task', {})])))).toBe('Asking a sub-agent')
  })

  it('describes a proposed write by the document it targets', () => {
    const out = stream(assistantLine([toolUse('mcp__sdlc-studio-chat__ProposeWrite', { document: 'requirements.md', section: 's', field: 'f', value: 'v' })]))
    expect(describeLatestActivity(out)).toBe('Drafting a change to requirements.md')
  })

  it('describes a structured question as preparing a question', () => {
    const out = stream(assistantLine([toolUse('mcp__sdlc-studio-chat__AskStructuredQuestion', { question: 'q', options: ['a', 'b'] })]))
    expect(describeLatestActivity(out)).toBe('Preparing a question')
  })

  it('describes reply text as writing a reply', () => {
    expect(describeLatestActivity(stream(assistantLine([{ type: 'text', text: 'Here is my answer' }])))).toBe('Writing a reply')
  })

  it('reports a thinking block as "Thinking", so a stale earlier step does not linger while the model is reasoning', () => {
    const out = stream(
      assistantLine([toolUse('Read', { file_path: 'a.md' })]),
      assistantLine([{ type: 'thinking', thinking: '...' }]),
    )
    expect(describeLatestActivity(out)).toBe('Thinking')
  })

  it('uses a plain generic label for a tool it has no wording for, never the raw tool name', () => {
    const label = describeLatestActivity(stream(assistantLine([toolUse('SomeFutureTool')])))
    expect(label).toBe('Working')
  })

  it('reports the LATEST activity, not the first', () => {
    const out = stream(
      assistantLine([toolUse('Read', { file_path: 'a.md' })]),
      assistantLine([toolUse('Grep', { pattern: 'x' })]),
    )
    expect(describeLatestActivity(out)).toBe('Searching the project')
  })

  it('uses the last block of a multi-block message', () => {
    const out = stream(assistantLine([{ type: 'text', text: 'Let me look.' }, toolUse('Read', { file_path: 'a.md' })]))
    expect(describeLatestActivity(out)).toBe('Reading a.md')
  })

  it('ignores a trailing half-written line and falls back to the last complete one', () => {
    const partial = '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","na'
    const out = stream(assistantLine([toolUse('Read', { file_path: 'a.md' })])) + partial
    expect(describeLatestActivity(out)).toBe('Reading a.md')
  })

  it('skips non-assistant frames (tool_result echoes) after the last assistant message', () => {
    const out = stream(
      assistantLine([toolUse('Read', { file_path: 'a.md' })]),
      JSON.stringify({ type: 'user', message: { role: 'user', content: [{ type: 'tool_result', content: 'ok' }] } }),
    )
    expect(describeLatestActivity(out)).toBe('Reading a.md')
  })

  it('does not throw on a Read with no usable file_path', () => {
    expect(describeLatestActivity(stream(assistantLine([toolUse('Read', {})])))).toBe('Reading a file')
    expect(describeLatestActivity(stream(assistantLine([toolUse('Read', { file_path: 42 })])))).toBe('Reading a file')
  })
})
