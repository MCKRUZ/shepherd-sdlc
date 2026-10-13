/** A real failure hit on this machine: Studio auto-detected a months-old, marketplace-cached
 * copy of the plugin, whose generate_status.py predates --json — and the raw argparse dump
 * ("usage: generate_status.py [-h] --state STATE...\ngenerate_status.py: error: unrecognized
 * arguments: --json") was shown to the person as if it were "the error", with no explanation
 * of what actually went wrong or what to do about it. This is the fix: recognise argparse's
 * own failure shape and lead with a plain-language explanation, never hiding the raw detail
 * (spec 0008's own promise — the console's technical view is untouched either way).
 */

import { describe, expect, it } from 'vitest'
import { explainIfVersionMismatch } from '../electron/main/project'
import type { ConsoleEntry } from '../shared/types'

function entry(over: Partial<ConsoleEntry> = {}): ConsoleEntry {
  return {
    id: '1', command: 'python', args: [], cwd: '.', startedAt: '', durationMs: 0,
    exitCode: 2, ok: false, stdout: '', stderr: '',
    ...over,
  }
}

describe('explainIfVersionMismatch', () => {
  it('recognises the exact failure this session hit, and leads with plain language', () => {
    const real = entry({
      stderr: 'usage: generate_status.py [-h] --state STATE [--output OUTPUT]\n'
        + 'generate_status.py: error: unrecognized arguments: --json',
    })
    const result = explainIfVersionMismatch(real, 'generate_status.py')
    expect(result.stderr).toContain("doesn't match what Shepherd expects")
    expect(result.stderr).toContain('generate_status.py')
    // The raw detail is still there for the technical reader — never hidden, only introduced.
    expect(result.stderr).toContain('unrecognized arguments: --json')
  })

  it('also recognises a missing-required-argument mismatch', () => {
    const result = explainIfVersionMismatch(
      entry({ stderr: 'usage: foo.py [-h] --state STATE\nfoo.py: error: the following arguments are required: --state' }),
      'foo.py',
    )
    expect(result.stderr).toContain("doesn't match what Shepherd expects")
  })

  it('leaves an ordinary failure alone — this is not a catch-all for every script error', () => {
    const ordinary = entry({ stderr: 'FileNotFoundError: .sdlc/state.yaml does not exist' })
    const result = explainIfVersionMismatch(ordinary, 'generate_status.py')
    expect(result.stderr).toBe(ordinary.stderr)
  })

  it('leaves a successful entry untouched', () => {
    const ok = entry({ ok: true, exitCode: 0, stderr: '' })
    expect(explainIfVersionMismatch(ok, 'generate_status.py')).toBe(ok)
  })
})
