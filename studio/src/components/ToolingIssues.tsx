import { useRef, useState } from 'react'
import { ExternalLink } from 'lucide-react'
import type { ToolingReport, ToolStatus } from '../../shared/types'
import { WORDING } from '../../shared/codeHostModel'
import { PLUGIN_DISPLAY_NAME } from '../../shared/pluginId'
import { BUTTON_BASE, BUTTON_SIZE, BUTTON_VARIANT, Button, Card, EYEBROW_CLASS, Field, Icon, Input, Notice, cn } from '../ui'
import { useStudioGSAP } from '../motion/useStudioGSAP'
import { listStagger } from '../motion/choreo'
import { EntryShell, choreoContext } from './entryScreenBits'

type ToolKey = 'claude' | 'uv' | 'pluginScripts' | 'git' | 'gh' | 'az'

/** The tools a project cannot open without. gh and az are deliberately NOT here (code-host
 * providers, D4): a project opens without either, and what a missing CLI costs is said per
 * feature from ConnectionInfo.cli, never by this screen. */
export const REQUIRED_TOOLS = ['claude', 'uv', 'pluginScripts', 'git'] as const
export const CODE_HOST_CLIS = ['gh', 'az'] as const

const INSTALL_LINKS: Record<ToolKey, string> = {
  claude: 'https://docs.claude.com/en/docs/claude-code',
  uv: 'https://docs.astral.sh/uv/getting-started/installation/',
  pluginScripts: 'https://docs.claude.com/en/docs/claude-code/plugins',
  git: 'https://git-scm.com/downloads',
  gh: 'https://cli.github.com/',
  az: 'https://aka.ms/azure-cli',
}

const LABELS: Record<ToolKey, string> = {
  claude: 'Claude Code',
  uv: 'uv (the script runner)',
  pluginScripts: `the ${PLUGIN_DISPLAY_NAME} plugin`,
  git: 'git',
  gh: 'the GitHub CLI (gh)',
  az: 'the Azure CLI (az)',
}

/** One missing tool: the probe's own error, the install page, and a way to point Shepherd at a
 * copy it did not find. "Use this" carries no `disabledReason` — the hidden reason text would
 * join the button's accessible name, and an e2e locates it by the exact name. */
function IssueRow({
  toolKey,
  status,
  onOverride,
}: {
  toolKey: ToolKey
  status: ToolStatus
  onOverride: (path: string) => void
}) {
  const [path, setPath] = useState('')
  const pathLabel = toolKey === 'pluginScripts' ? 'Path to the plugin\'s scripts/ folder' : 'Path to the binary'

  return (
    <Notice tone="warn" title={`${LABELS[toolKey]} wasn't found.`} data-reveal="" className="rounded-xl p-4">
      <p className="text-xs text-status-warn-ink">{status.error}</p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <a
          href={INSTALL_LINKS[toolKey]}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-700"
        >
          Install instructions
          <Icon icon={ExternalLink} size={14} />
        </a>
        <span className="pb-1.5 text-xs text-ink-3">or</span>
        <Field label={pathLabel} className="min-w-0 flex-1">
          <Input size="sm" mono value={path} onChange={(e) => setPath(e.target.value)} placeholder={pathLabel} />
        </Field>
        <Button size="sm" variant="secondary" disabled={!path.trim()} onClick={() => onOverride(path.trim())}>
          Use this
        </Button>
      </div>
    </Notice>
  )
}

/** One code-host CLI: found (where) or not found — and either way, nothing here blocks. The
 * copy is §7.1's "no project open" row, word for word from WORDING. */
function CliRow({
  toolKey,
  status,
  onOverride,
}: {
  toolKey: 'gh' | 'az'
  status: ToolStatus
  onOverride: (path: string) => void
}) {
  const [path, setPath] = useState('')
  return (
    <li data-reveal="" data-testid={`cli-${toolKey}`} className="rounded-xl border border-line-1 p-3 text-sm">
      <p className="text-ink-1">
        <span className="font-medium">{LABELS[toolKey]}</span>
        {status.found
          ? <span className="text-ink-3"> — found{status.path ? <> at <span className="font-mono text-xs">{status.path}</span></> : ''}</span>
          : <span className="text-ink-3"> — not found</span>}
      </p>
      {!status.found && (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <a href={INSTALL_LINKS[toolKey]} target="_blank" rel="noreferrer" className={cn(BUTTON_BASE, BUTTON_SIZE.sm, BUTTON_VARIANT.secondary)}>
            Install instructions
            <Icon icon={ExternalLink} size={14} />
          </a>
          <Field label="Path to the binary" className="min-w-0 flex-1">
            <Input size="sm" mono value={path} onChange={(e) => setPath(e.target.value)} placeholder="Path to the binary" />
          </Field>
          <Button size="sm" variant="secondary" disabled={!path.trim()} onClick={() => onOverride(path.trim())}>
            Use this
          </Button>
        </div>
      )}
    </li>
  )
}

/** Shown before any project when a REQUIRED tool is missing. Nothing is installed by Shepherd;
 * the person installs it or points at it. The code-host CLIs are listed too, as facts with
 * the same override inputs, but a project opens without them (code-host providers, D4). */
export function ToolingIssues({
  report,
  onOverride,
}: {
  report: ToolingReport
  onOverride: (kind: ToolKey, path: string) => void
}) {
  const issues = REQUIRED_TOOLS.filter((k) => !report[k].found)
  const listRef = useRef<HTMLDivElement | null>(null)

  useStudioGSAP(
    () => {
      const list = listRef.current
      if (!list) return
      listStagger.play(choreoContext(list), { items: Array.from(list.querySelectorAll('[data-reveal]')) })
    },
    // Once, at mount: the rows reveal when the screen appears, not again on every re-render
    // (each "Use this" override re-renders the parent with a new report).
    { scope: listRef, dependencies: [] },
  )

  return (
    <EntryShell>
      <Card className="mx-auto w-full max-w-lg space-y-3 rounded-4 p-6 shadow-2">
        <h1 className="text-lg text-ink-1">Before Shepherd can open a project</h1>
        <p className="text-sm text-ink-3">
          Shepherd needs these on this machine — nothing gets installed automatically.
        </p>
        <div ref={listRef} className="space-y-4">
          <section aria-labelledby="tooling-required-title" className="space-y-3">
            <h2 id="tooling-required-title" className={EYEBROW_CLASS}>Required</h2>
            {issues.map((k) => (
              <IssueRow key={k} toolKey={k} status={report[k]} onOverride={(path) => onOverride(k, path)} />
            ))}
          </section>
          <section aria-labelledby="tooling-cli-title" className="space-y-2">
            <h2 id="tooling-cli-title" className={EYEBROW_CLASS}>Code-host CLIs</h2>
            <p className="text-xs text-ink-3">{WORDING.noProject}</p>
            <ul className="space-y-2">
              {CODE_HOST_CLIS.map((k) => (
                <CliRow key={k} toolKey={k} status={report[k]} onOverride={(path) => onOverride(k, path)} />
              ))}
            </ul>
          </section>
        </div>
      </Card>
    </EntryShell>
  )
}
