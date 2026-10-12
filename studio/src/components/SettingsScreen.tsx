import { useCallback, useEffect, useRef, useState } from 'react'
import type { ConnectionInfo, ConnectionReport, ProjectSettings, Scorecard, ToolingReport } from '../../shared/types'
import { Button, Card, Chip, DefinitionList, Disclosure, Eyebrow, Field, Input, Notice, PageHeader, SkeletonRows } from '../ui'
import { useEnter } from '../motion/useEnter'
import { AppearanceSection } from './AppearanceSection'
import { GateAuthPanel } from './GateAuthPanel'
import { useListReveal } from './screenMotion'
import { ApprovalEditor, CodeHostOverride, LimitEditor, Section, codeHostItems, describeClaude, describePlugin } from './SettingsSections'
import { hostReasons } from '../hostReasons'
import { TypedActorForm } from './TypedActorForm'
import { connectionStore } from '../stores/connectionStore'
import { STICKY_HEADER_CLASS, useStuck } from './useStuck'

export { describeClaude, describePlugin } from './SettingsSections'

/** The plugin path on its own mono line (a path breaks only at its separators), then the
 * version and origin as prose — the same words `describePlugin` says, laid out to be read. */
function PluginDetail({ status }: { status: ToolingReport['pluginScripts'] }) {
  if (!status.found || !status.path) return <span>{describePlugin(status)}</span>
  const rest = describePlugin(status).slice(status.path.length).replace(/^\s*—\s*/, '')
  return (
    <span className="block">
      <span className="block font-mono text-xs text-ink-2 [overflow-wrap:anywhere]">{status.path}</span>
      <span className="block text-ink-3">{rest}</span>
    </span>
  )
}

/** A fixed rolling window for the alarm comparison below — this screen is about configuration,
 * not a report a person tunes the window on, so one steady figure beats an extra control. */
const ALARM_WINDOW_DAYS = 14

/** The project's settings (spec 0012) — read-only in this first cut, and honest about it.
 *
 * Every section names the FILE it is stored in, which spec 0012 asks for directly: a setting
 * whose home is invisible is one nobody can correct outside the app, and an app is not always
 * the right place to correct it from.
 *
 * Two distinctions this screen must never blur:
 *
 *   NOT CONFIGURED vs MISCONFIGURED. A project with no roster is ordinary. A project with a
 *   broken one needs fixing. Merging them sends a person to the wrong place.
 *
 *   A FIXED RULE vs A SETTING. The rules at the bottom cannot be changed here, and each says
 *   where it IS enforced. Listing an unenforced rule as a fact would tell someone they are
 *   protected by something that is not there — which is why this spec's own acceptance check
 *   was amended before this screen existed.
 */
export function SettingsScreen({
  projectPath, actor, connection: initialConnection = null,
}: {
  projectPath: string
  actor: string
  /** What App already knows about the code host, so the Repository rows render on first paint;
   * this screen re-reads it on load and after a change either way. */
  connection?: ConnectionInfo | null
}) {
  const [settings, setSettings] = useState<ProjectSettings | null>(null)
  const [connection, setConnection] = useState<ConnectionInfo | null>(initialConnection)
  const [report, setReport] = useState<ConnectionReport | null>(null)
  /** For the review-wait alarm next to each team's limit below — the same figure spec 0013's
   * read-only scorecard shows, reused here rather than a second computation of "over alarm". */
  const [scorecard, setScorecard] = useState<Scorecard | null>(null)
  /** Which Claude Code and which plugin this session is actually driving (studio-improvements
   * F1/F2) — machine facts, not project settings, but this is where a person looks for them. */
  const [tooling, setTooling] = useState<ToolingReport | null>(null)
  const [loading, setLoading] = useState(true)
  /** Nothing on this screen changes anything until edit mode is on, and the controls are
   * ABSENT rather than disabled outside it — the same rule spec 0010's document editor
   * follows, for the same reason: a greyed-out control still advertises something you
   * cannot do. */
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [refusal, setRefusal] = useState<string | null>(null)
  /** What changed locally but has not reached the repository yet. Kept as the set of FILES
   * rather than a boolean, so the save can name exactly what it is committing. */
  const [unsaved, setUnsaved] = useState<string[]>([])
  const [reason, setReason] = useState('')

  const root = useRef<HTMLDivElement>(null)
  useEnter(root, 'rise', { key: projectPath })
  useListReveal(root, settings ? projectPath : null)
  // The edit bar is this screen's sticky header (G4-2): no always-on border or solid fill; the
  // hairline appears only once a section has scrolled under it.
  const headerRef = useRef<HTMLDivElement>(null)
  useStuck(headerRef)

  const load = useCallback(async () => {
    setLoading(true)
    const [s, c, r, sc, tl] = await Promise.all([
      window.studio.getProjectSettings(projectPath),
      window.studio.getConnectionInfo(projectPath),
      window.studio.getConnectionReport(projectPath),
      window.studio.getScorecard(projectPath, ALARM_WINDOW_DAYS),
      window.studio.detectTooling(),
    ])
    setSettings(s)
    setConnection(c)
    setReport(r)
    setScorecard(sc)
    setTooling(tl)
    setLoading(false)
  }, [projectPath])

  useEffect(() => { load() }, [load])

  /** Run one setting change, then re-read. The plugin validated before it wrote, so a refusal
   * means the file is untouched and there is nothing to undo. */
  const change = async (run: () => Promise<{ ok: boolean; file?: string; refusal?: { message: string } }>) => {
    setBusy(true)
    setRefusal(null)
    const result = await run()
    setBusy(false)
    if (!result.ok) {
      setRefusal(result.refusal?.message ?? 'That change was refused.')
      return
    }
    if (result.file) setUnsaved((prev) => (prev.includes(result.file!) ? prev : [...prev, result.file!]))
    await load()
  }

  /** Pin the code host. The main process validates and writes through `set_setting.py
   * code-host`, and answers with the refreshed connection — so the rows above update from what
   * was actually re-resolved, not from what was clicked. A rejection is the plugin's sentence. */
  const changeCodeHost = async (host: ConnectionInfo['host']) => {
    setBusy(true)
    setRefusal(null)
    try {
      const refreshed = await window.studio.setCodeHost(projectPath, host)
      setConnection(refreshed)
      connectionStore.set(refreshed)
      setUnsaved((prev) => (prev.includes('.sdlc/code-host.yaml') ? prev : [...prev, '.sdlc/code-host.yaml']))
    } catch (err) {
      setRefusal(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  /** Send the change to the repository as an ordinary commit, with who and why — spec 0012's
   * own requirement. Deliberately a separate act from making the change: writing and
   * committing in one step gives nobody the chance to look at what they did first. */
  const saveToRepository = async () => {
    setBusy(true)
    setRefusal(null)
    const result = await window.studio.save(projectPath, reason.trim(), { actor })
    setBusy(false)
    if (!result.ok) {
      setRefusal(result.error ?? 'Could not save this change.')
      return
    }
    setUnsaved([])
    setReason('')
  }

  if (loading && !settings) {
    return (
      <div ref={root} aria-busy="true">
        <p role="status" className="text-sm text-ink-3">Reading this project’s settings…</p>
        <SkeletonRows rows={3} className="mt-3" />
      </div>
    )
  }
  if (!settings) return null

  return (
    <div ref={root} className="space-y-5">
      {/* The edit bar stays in view while the sections scroll, inside the screen root so `<main>`
          keeps rendering the screen directly. */}
      <div ref={headerRef} className={STICKY_HEADER_CLASS}>
        {/* S1: the kit header — "Settings" byte-identical (the e2e finds it by name), the lede
            unchanged, the Edit toggle as the one action. The sticky block is this screen's. */}
        <PageHeader
          eyebrow="Project · Settings"
          title="Settings"
          lede="Every setting here is stored in the project itself, not in Shepherd — so it travels with the repository and changes like any other file."
          actions={(
            <Button
              size="sm"
              variant={editing ? 'secondary' : 'primary'}
              aria-pressed={editing}
              onClick={() => { setEditing((on) => !on); setRefusal(null) }}
            >
              {editing ? 'Done editing' : 'Edit'}
            </Button>
          )}
        />
      </div>

      {refusal && (
        // The plugin's own words — it knows why it refused, and it refused before writing, so
        // nothing needs undoing.
        <Notice tone="warn" className="text-sm"><p className="whitespace-pre-wrap">{refusal}</p></Notice>
      )}

      {unsaved.length > 0 && (
        <Card tone="info">
          <p className="text-sm font-medium text-ink-1">Changed here, not yet in the repository</p>
          <ul className="mt-1 space-y-0.5">
            {unsaved.map((f) => <li key={f} className="font-mono text-xs text-ink-2">{f}</li>)}
          </ul>
          <Field
            label="Why did this change?"
            className="mt-3"
            hint={!reason.trim()
              ? 'A reason is required — it becomes the commit message, which is how anyone later finds out why this is set the way it is.'
              : undefined}
          >
            <Input value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <Button
            variant="primary"
            className="mt-2"
            onClick={saveToRepository}
            disabled={busy || !reason.trim() || !actor.trim()}
            disabledReason={!actor.trim() ? 'A save needs a signed-in person to put on the commit.' : !reason.trim() ? 'Write the reason first.' : undefined}
          >
            Save to the repository
          </Button>
        </Card>
      )}

      <Section id="repository" title="Repository" file={connection?.localFolder ?? ''} fileLabel="This project lives at">
        <DefinitionList
          columns={2}
          className="text-sm"
          items={[
            { term: 'Repository', detail: connection?.repo || 'no remote configured' },
            { term: 'Branch', detail: connection?.branch || 'unknown' },
            // §7.1: "unavailable (az not installed)" when the CLI cannot say, from the one
            // reason helper — "not signed in" only when the CLI is there and said so.
            {
              term: 'Signed in as',
              detail: (
                <>
                  <span>{connection?.account || hostReasons(connection).signedInAs || 'not signed in'}</span>
                  {/* D-OWNER-5: a typed name is offered only when the host could not identify the person. */}
                  {connection && connection.accountSource === null && connection.cli.signedIn !== 'yes' && (
                    <TypedActorForm
                      projectPath={projectPath}
                      className="mt-2"
                      onIdentified={() => setConnection(connectionStore.getSnapshot())}
                    />
                  )}
                </>
              ),
            },
            {
              term: 'Default branch protected',
              detail: connection?.branchProtected === null || connection?.branchProtected === undefined
                ? 'could not tell'
                : connection.branchProtected ? 'yes' : 'no',
            },
            ...(connection ? codeHostItems(connection) : []),
          ]}
        />
        {editing && connection && (
          <CodeHostOverride value={connection.host} busy={busy} onSet={changeCodeHost} />
        )}
        <p className="mt-3 text-xs text-ink-3">
          Shepherd reads and writes the project's own documents and specs. It never writes your
          code — that stays read-only, and a save it makes is an ordinary commit with a person
          and a reason on it.
        </p>
        {/* Stated as best-effort because it is: the real gate is whether a push gets
            rejected, never this probe. Presenting a guess as a fact here would be the same
            mistake as listing an unenforced rule below. */}
        <p className="mt-1 text-xs text-ink-3">
          Whether the branch is protected is a best guess from the code host's settings. What
          actually decides is whether a direct push is refused.
        </p>
      </Section>

      {/* Outside edit mode on purpose, unlike everything else on this screen. The rest of
          these settings live in files this screen edits; a credential lives on the code host
          and is never written here, so there is nothing to stage, nothing to save, and no
          reason to make somebody turn on editing to fix a gate that is failing closed. */}
      <GateAuthPanel projectPath={projectPath} connection={connection} />

      {report && (
        <Section id="connection" title="Connection checks" file="" fileLabel="">
          <ul className="space-y-2">
            {report.checks.map((c) => (
              <li key={c.check} className="flex items-baseline gap-3 text-sm" data-reveal="">
                {/* Three states, never two. "Could not tell" is its own answer and reads
                    differently from "no", because they send a person to different places. The
                    same chip language as everywhere else: ok / warn / neutral, dot and word. */}
                <span className="w-24 shrink-0">
                  <Chip size="xs" dot tone={c.state === 'yes' ? 'ok' : c.state === 'no' ? 'warn' : 'neutral'}>
                    {c.state === 'yes' ? 'yes' : c.state === 'no' ? 'no' : 'could not tell'}
                  </Chip>
                </span>
                <span className="min-w-0">
                  <span className="block text-ink-1">{c.question}</span>
                  <span className="block text-xs text-ink-3">{c.detail}</span>
                </span>
              </li>
            ))}
          </ul>
          {/* C8: the kit's Disclosure — still <details>/<summary>, chevron instead of ::marker. */}
          {Object.keys(report.not_universally_expected).length > 0 && (
            <Disclosure
              className="mt-3"
              summary="Pipelines not expected of every project"
              summaryProps={{ className: 'cursor-pointer text-xs text-ink-3' }}
            >
              <ul className="mt-1 space-y-0.5">
                {Object.entries(report.not_universally_expected).map(([name, why]) => (
                  <li key={name} className="text-xs text-ink-3"><span className="font-mono">{name}</span> — {why}</li>
                ))}
              </ul>
            </Disclosure>
          )}
        </Section>
      )}

      <Section id="people" title="People and teams" file={settings.roster.file} section={settings.roster}>
        {settings.roster.present && settings.roster.people.length > 0 ? (
          // One row per person and nothing summed across them: a roster is who may hold a role,
          // never a per-person tally.
          <ul className="divide-y divide-line-1">
            {settings.roster.people.map((person) => (
              <li key={person.handle} className="py-2 text-sm" data-reveal="">
                <span className="font-medium text-ink-1">{person.name || person.handle}</span>
                <span className="ml-2 text-ink-3">{person.handle}</span>
                {person.team && <span className="ml-2 text-ink-3">{person.team}</span>}
                {settings.roster.teams.some((t) => t.lead === person.handle) && <Chip size="xs" className="ml-2">lead</Chip>}
                <span className="mt-0.5 block text-xs text-ink-3">
                  {person.roles?.length ? `May be: ${person.roles.join(', ')}` : 'No roles listed'}
                  {person.signs_off?.length ? ` · Signs off stages ${person.signs_off.join(', ')}` : ''}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
        <p className="mt-3 text-xs text-ink-3">
          Adding someone here records that they may hold a role. It grants nobody access —
          Shepherd never invites anyone or changes anyone's repository permissions.
        </p>
      </Section>

      <Section id="limits" title="Build limits" file={settings.wip_limits.file} section={settings.wip_limits}>
        {settings.wip_limits.teams.length > 0 && (
          <ul className="space-y-2">
            {settings.wip_limits.teams.map((t) => {
              const alarm = scorecard?.team_alarms?.[t.team]
              return (
                <li key={t.team} className="flex items-baseline justify-between gap-3 text-sm" data-reveal="">
                  <span className="text-ink-1">{t.team}</span>
                  {editing && (
                    <LimitEditor current={t.wip_limit} busy={busy} onSet={(value) => change(() => window.studio.setTeamLimit(projectPath, t.team, value))} />
                  )}
                  <span>
                    {/* The limit and what is actually in flight, always together. One without
                        the other invites the reader to supply the missing half from memory. */}
                    {/* §2.3 token table: a limit reached or passed is a warn-class fact (the
                        Board chip and the Graph ring say it in amber too); `status-error` is
                        reserved for hard errors, refusals and stderr. */}
                    <span className={t.over_limit || t.at_limit ? 'text-status-warn-ink' : 'text-ink-2'}>
                      {t.in_flight} in flight / {t.wip_limit}
                    </span>
                    {t.over_limit && <span className="ml-2 font-semibold text-status-warn-ink">over limit</span>}
                    {t.at_limit && !t.over_limit && <span className="ml-2 font-semibold text-status-warn-ink">at limit</span>}
                    {/* Spec 0012: "a team whose alarm is sounding is named on this screen". The
                        comparison itself is the plugin's (scorecard.py's build_team_alarms_payload)
                        — never recomputed here from the two medians. The two alarms are shown
                        SEPARATELY, each with its own figure — they come from disjoint event pools
                        (review_waits vs. sec_waits) and a team can be over one without the other. */}
                    {alarm?.review_over_alarm === true && (
                      <span className="ml-2 font-semibold text-status-warn-ink">
                        review-wait alarm sounding ({scorecard!.review_wait_median_hours?.toFixed(0)}h)
                      </span>
                    )}
                    {alarm?.security_over_alarm === true && (
                      <span className="ml-2 font-semibold text-status-warn-ink">
                        security-review-wait alarm sounding ({scorecard!.security_review_wait_median_hours?.toFixed(0)}h)
                      </span>
                    )}
                  </span>
                </li>
              )
            })}
          </ul>
        )}
      </Section>

      <Section id="approval" title="Change approval" file={settings.approval.file} section={settings.approval}>
        {settings.approval.stages.length > 0 ? (
          <ul className="space-y-1 text-sm">
            {settings.approval.stages.map((st) => (
              <li key={st.stage} className="flex items-baseline justify-between gap-3" data-reveal="">
                <span className="text-ink-1">{st.stage}</span>
                {editing ? (
                  <ApprovalEditor
                    stage={st}
                    busy={busy}
                    people={settings.roster.people.map((p) => p.handle)}
                    onSet={(required, approver) => change(() => window.studio.setStageApproval(projectPath, st.stage, required, approver))}
                  />
                ) : (
                  <span className="text-ink-2">{st.approval_required ? `needs ${st.approver || 'a named approver'}` : 'no approval needed'}</span>
                )}
              </li>
            ))}
          </ul>
        ) : null}
        <p className="mt-3 text-xs text-ink-3">
          Where approval is on, changing a signed-off document saves your work to its own branch
          and asks the named person to approve it. Everyone else keeps seeing the signed-off
          version until they do.
        </p>
      </Section>

      <Section id="tooling" title="Tooling on this machine" file="" fileLabel="">
        {/* Not a project setting — it does not travel with the repository — but the question
            "which plugin is Studio running, and can this Claude Code run what it asks" has no
            other home, and both have been answered wrongly in silence before (F1, F2). */}
        <DefinitionList
          columns={2}
          className="text-sm"
          data-testid="tooling-facts"
          items={[
            { term: 'Claude Code', detail: <span className="[overflow-wrap:anywhere]">{tooling ? describeClaude(tooling.claude) : 'checking…'}</span> },
            { term: 'Plugin scripts', detail: tooling ? <PluginDetail status={tooling.pluginScripts} /> : 'checking…' },
          ]}
        />
      </Section>

      <AppearanceSection />

      <Card as="section" id="fixed-rules" tone="inset" className="scroll-mt-28">
        <Eyebrow as="h3">Fixed here — change these in the playbook, not the project</Eyebrow>
        <ul className="mt-2 space-y-2">
          {settings.fixed_rules.map((r) => (
            <li key={r.rule} className="text-sm" data-reveal="">
              <span className="text-ink-1">{r.rule}</span>
              {/* Where it is ACTUALLY enforced. A rule listed without that is a claim nobody
                  can check. */}
              <span className="mt-0.5 block text-xs text-ink-3">{r.enforced_by}</span>
            </li>
          ))}
        </ul>
      </Card>

      <p className="text-xs text-ink-3">Notifications and project details are not built yet.</p>
    </div>
  )
}
