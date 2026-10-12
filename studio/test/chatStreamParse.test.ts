import { describe, expect, it } from 'vitest'
import { parseStreamJsonToMessages } from '../electron/main/chat'

// Fixture lines shaped exactly like `claude --output-format stream-json`'s real stdout,
// captured against the actual CLI during this spec's own spike work (2026-09-29) and
// simplified to the fields parseStreamJsonToMessages actually reads. Testing against a shape
// this close to reality is what makes this "the driver parses structurally" rather than a
// parser that only ever sees hand-invented fixtures.

function assistantLine(content: unknown[], opts: { parentToolUseId?: string; uuid?: string } = {}): string {
  return JSON.stringify({
    type: 'assistant',
    message: { role: 'assistant', content },
    parent_tool_use_id: opts.parentToolUseId ?? null,
    uuid: opts.uuid ?? `uuid-${Math.random()}`,
    session_id: 'session-1',
  })
}

describe('parseStreamJsonToMessages', () => {
  it('extracts a plain assistant text reply', () => {
    const lines = [assistantLine([{ type: 'text', text: 'Hello, let\'s start with the problem statement.' }], { uuid: 'm1' })]
    const messages = parseStreamJsonToMessages(lines)
    expect(messages).toHaveLength(1)
    expect(messages[0]).toMatchObject({ id: 'm1', role: 'assistant', text: 'Hello, let\'s start with the problem statement.' })
    expect(messages[0].questions).toEqual([])
    expect(messages[0].proposals).toEqual([])
  })

  it('ignores non-assistant frames (system, user/tool_result echoes) and malformed lines', () => {
    const lines = [
      JSON.stringify({ type: 'system', subtype: 'hook_started' }),
      JSON.stringify({ type: 'user', message: { role: 'user', content: [{ type: 'tool_result', content: 'ok' }] } }),
      'not json at all',
      '',
      '   ',
      assistantLine([{ type: 'text', text: 'The only real message.' }], { uuid: 'm1' }),
    ]
    expect(parseStreamJsonToMessages(lines)).toEqual([
      expect.objectContaining({ id: 'm1', text: 'The only real message.' }),
    ])
  })

  it('turns a bare Read/Grep tool_use with no text into nothing shown — it is mechanical bookkeeping, not chat content', () => {
    const lines = [assistantLine([{ type: 'tool_use', id: 't1', name: 'Read', input: { file_path: 'x.md' } }])]
    expect(parseStreamJsonToMessages(lines)).toEqual([])
  })

  // Acceptance check: "A proposed write is a real tool call the driver parses structurally...
  // a test feeds a reply with no such tool call and asserts no proposal card appears, rather
  // than a guessed one." Both directions, in the two tests below.
  it('extracts a ProposeWrite tool_use into a structured proposal', () => {
    const lines = [assistantLine([
      { type: 'text', text: 'Here is a first draft of the problem statement.' },
      {
        type: 'tool_use', id: 't1', name: 'mcp__sdlc-studio-chat__ProposeWrite',
        input: { document: '.sdlc/artifacts/00-discovery/problem-statement.md', section: 'Problem Statement', field: 'Summary', value: 'The team cannot see...' },
      },
    ], { uuid: 'm1' })]
    const messages = parseStreamJsonToMessages(lines)
    expect(messages).toHaveLength(1)
    expect(messages[0].proposals).toEqual([{
      id: 't1',
      document: '.sdlc/artifacts/00-discovery/problem-statement.md',
      section: 'Problem Statement',
      field: 'Summary',
      value: 'The team cannot see...',
    }])
  })

  it('a reply with NO ProposeWrite tool call produces NO proposals — never a guess from prose alone', () => {
    const lines = [assistantLine([
      { type: 'text', text: 'I will write "The team cannot see..." into the Summary field.' },
    ])]
    const messages = parseStreamJsonToMessages(lines)
    expect(messages).toHaveLength(1)
    expect(messages[0].proposals).toEqual([])
  })

  it('extracts an AskStructuredQuestion tool_use into a structured question with real options', () => {
    const lines = [assistantLine([{
      type: 'tool_use', id: 't1', name: 'mcp__sdlc-studio-chat__AskStructuredQuestion',
      input: { question: 'What type of system is this?', options: ['service', 'app', 'library', 'skill', 'cli'] },
    }], { uuid: 'm1' })]
    const messages = parseStreamJsonToMessages(lines)
    expect(messages[0].questions).toEqual([{
      id: 't1', question: 'What type of system is this?', options: ['service', 'app', 'library', 'skill', 'cli'],
    }])
  })

  it('a reply with NO AskStructuredQuestion tool call produces NO questions — plain prose never becomes clickable options', () => {
    const lines = [assistantLine([{ type: 'text', text: 'Is this a service, app, library, skill, or cli?' }])]
    const messages = parseStreamJsonToMessages(lines)
    expect(messages[0].questions).toEqual([])
  })

  // Regression test for a real bug: a turn that calls ProposeWrite (or AskStructuredQuestion)
  // more than once used to have every call but the last silently overwritten by a single
  // `proposal`/`question` variable — the MCP server had already acknowledged every call, but
  // only the last one ever reached the person as a card.
  it('preserves EVERY ProposeWrite call in a single reply, not just the last one', () => {
    const lines = [assistantLine([
      { type: 'text', text: 'Here are two fields.' },
      {
        type: 'tool_use', id: 't1', name: 'mcp__sdlc-studio-chat__ProposeWrite',
        input: { document: 'd.md', section: 'S1', field: 'F1', value: 'V1' },
      },
      {
        type: 'tool_use', id: 't2', name: 'mcp__sdlc-studio-chat__ProposeWrite',
        input: { document: 'd.md', section: 'S2', field: 'F2', value: 'V2' },
      },
    ], { uuid: 'm1' })]
    const messages = parseStreamJsonToMessages(lines)
    expect(messages).toHaveLength(1)
    expect(messages[0].proposals).toHaveLength(2)
    expect(messages[0].proposals.map((p) => p.id)).toEqual(['t1', 't2'])
    expect(messages[0].proposals[0]).toMatchObject({ field: 'F1', value: 'V1' })
    expect(messages[0].proposals[1]).toMatchObject({ field: 'F2', value: 'V2' })
  })

  it('preserves EVERY AskStructuredQuestion call in a single reply, not just the last one', () => {
    const lines = [assistantLine([
      {
        type: 'tool_use', id: 't1', name: 'mcp__sdlc-studio-chat__AskStructuredQuestion',
        input: { question: 'Q1?', options: ['A', 'B'] },
      },
      {
        type: 'tool_use', id: 't2', name: 'mcp__sdlc-studio-chat__AskStructuredQuestion',
        input: { question: 'Q2?', options: ['C', 'D'] },
      },
    ], { uuid: 'm1' })]
    const messages = parseStreamJsonToMessages(lines)
    expect(messages).toHaveLength(1)
    expect(messages[0].questions).toHaveLength(2)
    expect(messages[0].questions.map((q) => q.id)).toEqual(['t1', 't2'])
    expect(messages[0].questions[0]).toMatchObject({ question: 'Q1?' })
    expect(messages[0].questions[1]).toMatchObject({ question: 'Q2?' })
  })

  it('a proposal and a question in the SAME reply are both preserved, each addressable by its own id', () => {
    const lines = [assistantLine([
      {
        type: 'tool_use', id: 't1', name: 'mcp__sdlc-studio-chat__ProposeWrite',
        input: { document: 'd.md', section: 'S', field: 'F', value: 'V' },
      },
      {
        type: 'tool_use', id: 't2', name: 'mcp__sdlc-studio-chat__AskStructuredQuestion',
        input: { question: 'Q?', options: ['A', 'B'] },
      },
    ], { uuid: 'm1' })]
    const messages = parseStreamJsonToMessages(lines)
    expect(messages[0].proposals).toEqual([{ id: 't1', document: 'd.md', section: 'S', field: 'F', value: 'V' }])
    expect(messages[0].questions).toEqual([{ id: 't2', question: 'Q?', options: ['A', 'B'] }])
    // The proposal and question ids are distinct from the MESSAGE's own id.
    expect(messages[0].id).toBe('m1')
  })

  it('labels a forwarded sub-agent message with the agent it actually came from, correlated by parent_tool_use_id', () => {
    const lines = [
      // The orchestrator spawns discovery-analyst via Task.
      assistantLine([
        { type: 'text', text: 'Let me check the intake corpus for contradictions.' },
        { type: 'tool_use', id: 'task-1', name: 'Task', input: { subagent_type: 'shepherd:discovery-analyst', description: 'find contradictions', prompt: '...' } },
      ], { uuid: 'orchestrator-1' }),
      // The sub-agent's OWN forwarded text (--forward-subagent-text), not a paraphrase.
      assistantLine([{ type: 'text', text: 'Found 3 contradictions across the corpus.' }], { parentToolUseId: 'task-1', uuid: 'sub-1' }),
    ]
    const messages = parseStreamJsonToMessages(lines)
    expect(messages).toHaveLength(2)
    expect(messages[0]).toMatchObject({ id: 'orchestrator-1', role: 'assistant' })
    expect(messages[1]).toMatchObject({
      id: 'sub-1', role: 'subagent', subagentType: 'shepherd:discovery-analyst',
      text: 'Found 3 contradictions across the corpus.',
    })
  })

  it('labels a forwarded message "unknown" when its parent Task call was not seen in this batch of lines', () => {
    const lines = [assistantLine([{ type: 'text', text: 'orphaned forwarded text' }], { parentToolUseId: 'no-such-task', uuid: 'sub-1' })]
    const messages = parseStreamJsonToMessages(lines)
    expect(messages[0]).toMatchObject({ role: 'subagent', subagentType: 'unknown' })
  })
})
