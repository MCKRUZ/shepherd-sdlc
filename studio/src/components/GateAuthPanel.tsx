import { useCallback, useEffect, useState } from 'react'
import type { ConnectionInfo, GateAuthStatus } from '../../shared/types'
import { cliLabel } from '../../shared/codeHostModel'
import { Button, Card, Eyebrow, Input, Notice } from '../ui'
import { hostReasons } from '../hostReasons'

/** How the review gates sign in to Claude.
 *
 * The correctness-review, security-review and grader gates run on the code host, not on
 * anybody's machine, so they cannot borrow the Claude session this application is using. They
 * need a credential of their own, and this is where a person provides one.
 *
 * TWO WAYS, and the difference is money rather than capability — which is why the cost is
 * stated at the moment of choosing rather than left in a document somewhere:
 *
 *   subscription  a token minted from your own Claude login. No per-pull-request charge.
 *   api key       metered. Every pull request that touches source costs real money.
 *
 * WHAT THIS SCREEN DOES NOT DO, deliberately:
 *
 *   It never shows a credential back, not even masked. There is nothing to show: the value is
 *   handed to the plugin, which hands it to the code host, and nobody keeps a copy. The screen
 *   can say WHETHER one is set, and that is the whole of what it knows.
 *
 *   It never remembers what was typed. The field is cleared the moment it is submitted, and
 *   its contents are never put in application state that outlives the call.
 *
 *   It enforces nothing. Every refusal — a malformed credential, a repository the account
 *   cannot administer, a write the code host silently ignored — comes back from the plugin, so
 *   a person who configures this by hand is held to exactly the same rules.
 */
export function GateAuthPanel({
  projectPath,
  connection = null,
}: {
  projectPath: string
  /** What the main process established about this project's code-host CLI. When the CLI is
   * unavailable the panel says so in the §7.1 words (hostReasons) and the credential cannot
   * be set — it would have nowhere to go. Absent → the panel behaves as before. */
  connection?: ConnectionInfo | null
}) {
  // One helper, never a hand-typed "needs gh": the reason text and the wording below are both
  // host-aware, so an Azure DevOps project reads "Azure CLI", not "GitHub".
  const cliReason = hostReasons(connection).gateCredential
  const hostCli = connection ? cliLabel(connection.host) : null
  const [status, setStatus] = useState<GateAuthStatus | null>(null)
  const [mode, setMode] = useState<'subscription' | 'api-key'>('subscription')
  const [credential, setCredential] = useState('')
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState<{ ok: boolean; message: string } | null>(null)

  const load = useCallback(async () => {
    setStatus(await window.studio.getGateAuth(projectPath))
  }, [projectPath])

  useEffect(() => { load() }, [load])

  const submit = async () => {
    setBusy(true)
    setOutcome(null)
    const result = await window.studio.setGateAuth(projectPath, mode, credential)
    // Cleared immediately, whatever happened. A credential left sitting in a form field
    // outlives the reason it was typed, and this one is never needed again.
    setCredential('')
    setBusy(false)
    setOutcome(result.ok
      ? { ok: true, message: `${result.message ?? 'Set.'} ${result.cost ?? ''}`.trim() }
      : { ok: false, message: result.refusal?.message ?? 'The credential was not set.' })
    await load()
  }

  const remove = async (which: 'subscription' | 'api-key') => {
    setBusy(true)
    const result = await window.studio.clearGateAuth(projectPath, which)
    setBusy(false)
    setOutcome(result.ok
      ? { ok: true, message: result.message ?? 'Removed.' }
      : { ok: false, message: result.refusal?.message ?? 'It was not removed.' })
    await load()
  }

  if (!status) return <p role="status" className="text-sm text-ink-4">Checking how the gates sign in…</p>

  return (
    <Card as="section" id="gate-approvals" aria-labelledby="gate-approvals-title" className="scroll-mt-20">
      <Eyebrow as="h3" id="gate-approvals-title" className="text-ink-2">How the review gates sign in</Eyebrow>
      <p className="mt-1 text-xs text-ink-3">
        The correctness, security and grader checks run on {status.repo ?? 'the code host'},
        not on this machine, so they need their own way to reach Claude.
        {hostCli ? ` Shepherd sets and reads the credential through the ${hostCli}.` : ''}
      </p>

      {cliReason && (
        <Notice tone="warn" className="mt-2" data-testid="gate-auth-host-reason">{cliReason}</Notice>
      )}

      {!status.gates_can_sign_in ? (
        <Notice tone="warn" className="mt-2">
          They cannot sign in yet. The correctness and security reviews fail closed on the pull
          requests they review — deliberately, so nothing merges looking reviewed when it was
          not. The grader stays quiet.
          {status.detail ? ` ${status.detail}` : ''}
        </Notice>
      ) : (
        <ul className="mt-2 space-y-1">
          {status.configured.map((which) => (
            <li key={which} className="flex items-center gap-2 text-sm text-ink-1">
              <span>{which === 'subscription' ? 'Your Claude subscription' : 'An Anthropic API key'}</span>
              <Button variant="link" size="sm" onClick={() => remove(which as 'subscription' | 'api-key')} disabled={busy}>
                remove
              </Button>
            </li>
          ))}
        </ul>
      )}
      {status.detail && status.gates_can_sign_in && <p className="mt-2 text-xs text-ink-3">{status.detail}</p>}

      <div className="mt-3 border-t border-line-1 pt-3">
        <div className="flex gap-4 text-sm">
          {(['subscription', 'api-key'] as const).map((option) => (
            <label key={option} className="flex items-center gap-1.5">
              <input type="radio" checked={mode === option} onChange={() => setMode(option)} />
              <span className="text-ink-1">{option === 'subscription' ? 'My Claude subscription' : 'An API key'}</span>
            </label>
          ))}
        </div>

        {/* The cost, said before the choice rather than after it. This is the only real
            difference between the two, so burying it would be burying the decision. */}
        <p className="mt-1.5 text-xs text-ink-3">
          {mode === 'subscription'
            ? 'No per-pull-request charge — the gates run against your existing plan. Run '
              + '`claude setup-token` on this machine and paste what it prints.'
            : 'Metered: every pull request that touches source costs real money at the model. '
              + 'Create a key in the Anthropic console and paste it.'}
        </p>

        <div className="mt-2 flex items-center gap-2">
          <Input
            // A password field, so it is not read over a shoulder or captured by a screen
            // recording. That is all it protects against — the real protection is that the
            // value is never stored, never logged and never sent back here.
            type="password"
            size="sm"
            mono
            value={credential}
            onChange={(e) => setCredential(e.target.value)}
            placeholder={mode === 'subscription' ? 'paste the token' : 'sk-ant-…'}
            autoComplete="off"
            spellCheck={false}
            aria-label={mode === 'subscription' ? 'Claude token' : 'Anthropic API key'}
            className="w-72"
          />
          <Button
            variant="primary"
            onClick={submit}
            disabled={busy || !credential.trim() || cliReason !== null}
            loading={busy}
            loadingLabel="Setting…"
            disabledReason={cliReason ?? (!credential.trim() ? 'Paste the credential first.' : undefined)}
          >
            Set it
          </Button>
        </div>

        <p className="mt-1.5 text-xs text-ink-4">
          It goes straight to {status.repo ?? 'the code host'}, which stores it encrypted.
          Nothing is written to this machine, and it is never shown again — to change it, set
          it again.
        </p>
      </div>

      {outcome && (
        <Notice tone={outcome.ok ? 'ok' : 'warn'} className="mt-3">{outcome.message}</Notice>
      )}
    </Card>
  )
}
