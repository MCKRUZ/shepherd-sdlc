import { describe, it, expect } from 'vitest'
import { redact } from '../electron/main/commandRunner'

// Spec 0009's first acceptance check: Studio "never prompts for, stores or displays a
// password or token." This is the one function that guarantees it for anything that ends
// up in the console, regardless of which git/gh command produced it.
describe('redact', () => {
  it('masks a credentialed HTTPS URL', () => {
    const out = redact('https://x-access-token:ghp_abcdefghijklmnopqrstuvwxyz123456@github.com/foo/bar.git')
    expect(out).toBe('https://***@github.com/foo/bar.git')
    expect(out).not.toContain('ghp_')
  })

  it('masks a bare GitHub personal access token in text', () => {
    const out = redact('remote: Invalid credentials for ghp_abcdefghijklmnopqrstuvwxyz123456')
    expect(out).toBe('remote: Invalid credentials for ***')
  })

  it('masks a fine-grained github_pat_ token', () => {
    const out = redact('token=github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz0123456789')
    expect(out).toBe('token=***')
  })

  it('masks every gh token prefix variant', () => {
    for (const prefix of ['ghp', 'gho', 'ghu', 'ghs', 'ghr']) {
      const token = `${prefix}_${'a'.repeat(36)}`
      expect(redact(`before ${token} after`)).toBe('before *** after')
    }
  })

  it('leaves ordinary text completely untouched', () => {
    const text = 'Merged pull request #42: Update requirements.md'
    expect(redact(text)).toBe(text)
  })

  it('leaves a plain https URL with no credentials untouched', () => {
    const text = 'https://github.com/MCKRUZ/shepherd-sdlc.git'
    expect(redact(text)).toBe(text)
  })

  it('masks multiple occurrences in the same string', () => {
    const token = `ghp_${'a'.repeat(36)}`
    const out = redact(`first ${token} second ${token}`)
    expect(out).toBe('first *** second ***')
  })

  it('does not false-positive on a short token-like word', () => {
    // Too short to be a real token (< 20 chars after the prefix) — must NOT be redacted,
    // or a real short identifier that happens to start with "ghp_" would be silently eaten.
    const text = 'ghp_short'
    expect(redact(text)).toBe(text)
  })
})

// Spec 0010's security pass: this function is a stated guarantee and had no adversarial test
// at all — every case above is a GitHub credential, and Studio spawns more than git and gh.
// The `claude` CLI runs through the same choke point and prints its own credential errors, a
// repository's remote can point at any host, and a person pasting a console excerpt into a
// bug report cannot tell which line carried a secret.
//
// Worth saying plainly: redaction is a backstop, not an eraser. A token that has already been
// shown must be rotated. These tests exist so the backstop is known to work, not so anyone
// relies on it to undo a leak.
describe('redact — credentials that are not GitHub tokens', () => {
  it('masks a GitLab token', () => {
    expect(redact(`fatal: auth failed glpat-${'a'.repeat(24)}`)).toBe('fatal: auth failed ***')
  })

  it('masks an Anthropic API key, which the claude CLI can echo', () => {
    expect(redact(`Invalid key: sk-ant-api03-${'a'.repeat(30)}`)).toBe('Invalid key: ***')
  })

  it('masks an AWS access key id', () => {
    expect(redact('AKIAIOSFODNN7EXAMPLE in the environment')).toBe('*** in the environment')
    expect(redact('ASIAIOSFODNN7EXAMPLE in the environment')).toBe('*** in the environment')
  })

  it('masks an Authorization header, keeping the scheme so the line still reads', () => {
    expect(redact('Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123'))
      .toBe('Authorization: Bearer ***')
    expect(redact('authorization: basic dXNlcjpwYXNzd29yZDEyMzQ1Njc4OTA='))
      .toBe('authorization: basic ***')
  })

  it('masks a JSON Web Token, which carries its claims in the clear', () => {
    const jwt = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk'
    expect(redact(`token: ${jwt}`)).toBe('token=***')
  })

  it('masks anything explicitly labelled as a secret, whatever its shape', () => {
    expect(redact('password=hunter2')).toBe('password=***')
    expect(redact('PASSWORD: "hunter2"')).toBe('PASSWORD=***')
    expect(redact('api_key = abc123xyz')).toBe('api_key=***')
    expect(redact('api-key: abc123xyz')).toBe('api-key=***')
    expect(redact('secret=s3cr3t')).toBe('secret=***')
    expect(redact('auth: abc123')).toBe('auth=***')
  })

  it('still leaves ordinary output alone', () => {
    for (const text of [
      'Merged pull request #42: Update requirements.md',
      'https://github.com/MCKRUZ/shepherd-sdlc.git',
      'To github.com:MCKRUZ/sdlc-studio.git\n   abc1234..def5678  main -> main',
      '3 files changed, 42 insertions(+), 7 deletions(-)',
      'FR-001: The system SHALL reject a duplicate claim_id',
    ]) {
      expect(redact(text)).toBe(text)
    }
  })

  it('does not eat a word that merely contains "token" as part of a sentence', () => {
    // No delimiter, so nothing is being assigned — this is prose, not a credential.
    const text = 'The token was rotated yesterday'
    expect(redact(text)).toBe(text)
  })
})
