import { useEffect, useState, type ReactNode } from 'react'
import type { ApprovalStage, ConnectionInfo, SettingsSection, ToolStatus } from '../../shared/types'
import { claudeLacksMessage } from '../../shared/claudeContract'
import { CODE_HOST_ENV, CODE_HOST_FILE, HOSTS, LEGACY_CODE_HOST_ENV, cliFor, type HostName } from '../../shared/codeHostModel'
import { Card, Eyebrow, Input, Notice, Segmented, Select } from '../ui'
import type { DefinitionItem } from '../ui'
import { hostReasons, signedInSentence } from '../hostReasons'

const HOST_LABEL: Record<HostName, string> = { github: 'GitHub', 'azure-devops': 'Azure DevOps', none: 'none' }

/** How the host was decided, in the words of code-host-providers.md's precedence table. */
export function describeHostSource(connection: Pick<ConnectionInfo, 'hostSource'>): string {
  switch (connection.hostSource) {
    case 'flag': return 'from a --host flag'
    case 'env': return `from ${CODE_HOST_ENV} or ${LEGACY_CODE_HOST_ENV}`
    case 'file': return `from ${CODE_HOST_FILE}`
    case 'remote': return 'from origin'
    case 'manifest': return 'from the harness manifest'
    default: return 'nothing matched'
  }
}

/** The Repository rows that say which code host this is and what its CLI established
 * (code-host-providers.md §7 SettingsScreen row). Three rows, always: the host and how it was
 * decided; the CLI the host needs with the sign-in sentence or the §7.1 reason; and the OTHER
 * CLI, which "is not needed for this repository" — said outright, so nobody installs it. */
export function codeHostItems(connection: ConnectionInfo): DefinitionItem[] {
  const needed = connection.cli.name ?? cliFor(connection.host)
  const other = needed === 'az' ? 'gh' : 'az'
  const cliDetail = connection.host === 'none'
    ? hostReasons(connection).board ?? signedInSentence(connection)
    : signedInSentence(connection)
  return [
    { term: 'Code host', detail: `${HOST_LABEL[connection.host]} (${describeHostSource(connection)})`, key: 'code-host' },
    { term: 'CLI', detail: cliDetail, key: 'cli' },
    { term: `${other} CLI`, detail: 'not needed for this repository', key: 'other-cli' },
  ]
}

/** Pin the code host by hand (edit mode only). Writes `.sdlc/code-host.yaml` through the
 * plugin's own `set_setting.py code-host`; the file travels with the clone and is read ahead of
 * the origin remote. A refusal is the plugin's sentence, and the file was not touched. */
export function CodeHostOverride({
  value, busy, onSet,
}: {
  value: HostName
  busy: boolean
  onSet: (host: HostName) => void
}) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-3">
      <span className="text-xs text-ink-3">Pin the code host</span>
      <Segmented<HostName>
        size="sm"
        tone="neutral"
        label="Code host override"
        value={value}
        disabled={busy}
        disabledReason={busy ? 'A change is still being written.' : undefined}
        onChange={(host) => { if (host !== value) onSet(host) }}
        options={HOSTS.map((h) => ({ value: h, label: HOST_LABEL[h] }))}
      />
      <span className="text-xs text-ink-3">Written to {CODE_HOST_FILE}; overrides what the origin remote says.</span>
    </div>
  )
}

/** One settings section: a Card whose header names the FILE it is stored in — spec 0012 asks for
 * that directly, because a setting whose home is invisible is one nobody can correct outside the
 * app. `id` is the anchor the command palette's Settings group jumps to. */
export function Section({
  id, title, file, fileLabel = 'Stored in', section, children,
}: {
  id: string
  title: string
  file: string
  fileLabel?: string
  section?: SettingsSection
  children?: ReactNode
}) {
  return (
    <Card as="section" id={id} aria-labelledby={`${id}-title`} className="scroll-mt-28">
      {/* Section labels recede (the eyebrow voice) so the facts below lead; the file path keeps
          to the right in mono — words, so ink-3 — so a reader can always go and edit the real thing. */}
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <Eyebrow as="h3" id={`${id}-title`}>{title}</Eyebrow>
        {file && <span className="shrink-0 text-right font-mono text-xs text-ink-3">{fileLabel} {file}</span>}
      </div>

      {/* Not configured and misconfigured are different answers, shown differently. */}
      {section && !section.present && (
        <p className="mt-2 text-sm text-ink-3">
          This project has not set this up. Nothing is wrong — the file simply does not exist yet.
        </p>
      )}
      {section && section.errors.length > 0 && (
        <Notice tone="warn" title="This file exists but could not be read cleanly:" className="mt-2">
          <ul className="mt-1 space-y-0.5">
            {section.errors.map((e) => <li key={e}>{e}</li>)}
          </ul>
        </Notice>
      )}

      <div className="mt-3">{children}</div>
    </Card>
  )
}

/** One team's limit. Committed on blur or Enter rather than per keystroke — the plugin
 * validates and writes on every call, and doing that per character would write the file
 * four times to set a two-digit number. */
export function LimitEditor({ current, busy, onSet }: { current: number; busy: boolean; onSet: (value: number) => void }) {
  const [value, setValue] = useState(String(current))

  useEffect(() => { setValue(String(current)) }, [current])

  const commit = () => {
    const parsed = Number(value)
    // Refused by the plugin anyway; not sending it saves a pointless round trip and an
    // error message for something the person is probably mid-typing.
    if (!Number.isInteger(parsed) || parsed < 1 || parsed === current) {
      setValue(String(current))
      return
    }
    onSet(parsed)
  }

  return (
    <Input
      size="sm"
      value={value}
      disabled={busy}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === 'Enter') commit() }}
      className="w-16"
      aria-label="limit"
    />
  )
}

/** Approval for one stage. The approver list is the ROSTER — the plugin refuses anyone not on
 * it, since nothing could route an approval to them, so offering a free-text box here would
 * only invite a refusal. */
export function ApprovalEditor({
  stage, busy, people, onSet,
}: {
  stage: ApprovalStage
  busy: boolean
  people: string[]
  onSet: (required: boolean, approver?: string) => void
}) {
  const [approver, setApprover] = useState(stage.approver ?? '')

  return (
    <span className="flex items-center gap-2">
      <Select
        size="sm"
        value={stage.approval_required ? 'on' : 'off'}
        disabled={busy}
        onChange={(v) => onSet(v === 'on', approver || undefined)}
        options={[{ value: 'off', label: 'no approval needed' }, { value: 'on', label: 'needs approval' }]}
        aria-label={`approval for ${stage.stage}`}
      />
      {stage.approval_required && (
        <Select
          size="sm"
          value={approver}
          disabled={busy}
          onChange={(v) => { setApprover(v); onSet(true, v) }}
          options={[{ value: '', label: 'choose someone' }, ...people.map((h) => ({ value: h, label: h }))]}
          aria-label={`approver for ${stage.stage}`}
        />
      )}
    </span>
  )
}

/** The installed Claude Code, and whether it accepts every flag Studio emits. */
export function describeClaude(status: ToolStatus): string {
  if (!status.found) return status.error ?? 'not found'
  const missing = status.missingFlags ?? []
  if (missing.length > 0) return claudeLacksMessage(status.version, missing)
  return `${status.version ?? 'found'} — accepts every flag Shepherd uses`
}

/** Which plugin is driving this session, said plainly: the path alone does not say whether it is
 * the checkout beside Studio or an older marketplace copy (studio-improvements F2). */
export function describePlugin(status: ToolStatus): string {
  if (!status.found || !status.path) return status.error ?? 'not found'
  const origin = status.source === 'sibling' ? 'the checkout beside Shepherd'
    : status.source === 'cache' ? 'the plugin cache'
    : status.source === 'override' ? 'the path set in Shepherd'
    : 'origin not recorded'
  const version = status.pluginVersion ? `version ${status.pluginVersion}` : 'version not readable'
  return `${status.path} — ${version}, from ${origin}`
}
