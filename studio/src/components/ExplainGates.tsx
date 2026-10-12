import { useCallback, useEffect, useRef, useState } from 'react'
import type { GateInventory } from '../../shared/types'
import { Card, DataTable, Eyebrow, Notice, PageHeader, SkeletonRows } from '../ui'
import { useListReveal } from './screenMotion'

type Gate = GateInventory['gates'][number]

/** Every check a change must pass (spec 0013). Described by the rails guide, never by Studio, so
 * this screen and the pipelines cannot disagree. */
export function GatesView({ projectPath }: { projectPath: string }) {
  const [inventory, setInventory] = useState<GateInventory | null>(null)
  const [loading, setLoading] = useState(true)
  const root = useRef<HTMLDivElement>(null)
  useListReveal(root, inventory?.ok ? projectPath : null)

  const load = useCallback(async () => {
    setLoading(true)
    setInventory(await window.studio.getGateInventory(projectPath))
    setLoading(false)
  }, [projectPath])

  useEffect(() => { load() }, [load])

  if (loading && !inventory) {
    return (
      <div aria-busy="true">
        <p role="status" className="text-sm text-ink-3">Reading the gates…</p>
        <SkeletonRows rows={3} className="mt-3" />
      </div>
    )
  }
  if (!inventory) return null

  if (!inventory.ok) {
    return (
      // Never "this project has no gates" — that is a much more alarming claim, and a
      // different one.
      <Notice tone="warn" title="The gates could not be described.">{inventory.error}</Notice>
    )
  }

  const installed = inventory.gates.filter((g) => g.state === 'installed')
  const missing = inventory.gates.filter((g) => g.state === 'missing')
  const local = inventory.gates.filter((g) => g.state === 'not_a_pipeline')

  return (
    <div ref={root} className="space-y-4">
      <div>
        {/* S1: the kit header; the heading text is byte-identical. */}
        <PageHeader
          eyebrow="Build · How it is going"
          title="Checks and gates"
          lede={(
            <>
              What every change has to pass. Described in{' '}
              <span className="font-mono text-xs">{inventory.guide_source}</span> — Shepherd does not
              describe the gates itself, so this screen and the pipelines cannot disagree.
            </>
          )}
        />
        {/* Said out loud rather than implied. This project supplies BOTH its gate list and the
            files that list names, so on its own the screen can only report what the project
            claims. Whether it was checked against the standard is the thing that makes the
            difference, and "nothing was compared" must not read like "nothing disagreed". */}
        <p className="mt-1 text-xs text-ink-3">
          {inventory.compared_with_playbook
            ? 'Checked against the playbook\'s own copy, and any disagreement is shown below.'
            : 'This is what the project says about itself; it has not been checked against the playbook.'}
        </p>
      </div>

      {(inventory.not_in_project_guide?.length ?? 0) > 0 && (
        <Notice tone="warn" title="The playbook expects these, and this project's guide does not list them">
          <p className="mt-1">
            Nothing above checked for them — a gate dropped from a project's own description
            stops being asked about, so its absence looks like agreement.
          </p>
          <ul className="mt-2 space-y-1">
            {inventory.not_in_project_guide!.map((d) => (
              <li key={d.gate} className="text-sm">
                <span className="font-medium">{d.gate}</span>
                <span className="ml-2 text-xs">{d.blocks}</span>
              </li>
            ))}
          </ul>
        </Notice>
      )}

      <GateList title="On every change here" gates={installed} tone="installed" />

      {missing.length > 0 && (
        <GateList
          title="The playbook ships these; this project does not run them"
          gates={missing}
          tone="missing"
          note="These are not protecting anything here. Listing them as gates would suggest otherwise."
        />
      )}

      {local.length > 0 && (
        <GateList
          title="Local gates"
          gates={local}
          tone="local"
          note="These run on a person's own machine rather than in the pipeline, so whether they are in place cannot be confirmed from the repository."
        />
      )}

      {inventory.unexpected.length > 0 && (
        <Card>
          <Eyebrow as="h3" className="mb-2">This project's own, not in the playbook</Eyebrow>
          <ul className="space-y-1">
            {inventory.unexpected.map((u) => (
              <li key={u.file} className="text-sm text-ink-1" data-reveal="">
                <span className="font-mono text-xs">{u.file}</span>
                <span className="ml-2 text-xs text-ink-3">{u.detail}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card>
        <Eyebrow as="h3" className="mb-2">Recorded ways past a gate</Eyebrow>
        <ul className="space-y-1">
          {inventory.bypass_ledgers.map((l) => (
            <li key={l.file} className="text-sm" data-reveal="">
              <span className="text-ink-1">{l.gate}</span>
              <span className="ml-2 text-xs text-ink-3">
                {l.present
                  ? <>recorded in <span className="font-mono">{l.file}</span></>
                  : 'no ledger in this project — there is no sanctioned way past it'}
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}

/** One group of gates as a table. The "differs" cell is shown in both documents' words and not
 * resolved: a project may legitimately have adapted a gate, and which copy is right is not this
 * screen's to decide. What it owes the reader is that the two do not say the same thing. */
function GateList({ title, gates, tone, note }: { title: string; gates: Gate[]; tone: 'installed' | 'missing' | 'local'; note?: string }) {
  return (
    <Card tone={tone === 'missing' ? 'warn' : 'default'}>
      <Eyebrow as="h3" className="mb-2">{title}</Eyebrow>
      <DataTable<Gate>
        label={title}
        rows={gates}
        rowKey={(g) => `${g.gate}-${g.file}`}
        rowProps={() => ({ 'data-reveal': '' } as React.ComponentPropsWithoutRef<'tr'>)}
        columns={[
          {
            id: 'gate', header: 'Gate',
            cell: (g) => (
              <>
                <span className="font-medium text-ink-1">{g.gate}</span>
                {g.optional && <span className="ml-2 text-xs text-ink-3">optional</span>}
              </>
            ),
          },
          { id: 'file', header: 'File', mono: true, cell: (g) => <span className="text-ink-3">{g.file}</span> },
          { id: 'runs', header: 'Runs on', cell: (g) => <span className="text-ink-2">Runs on {g.fires_on || 'unstated'} · {g.blocks || 'unstated'}</span> },
          {
            id: 'differs', header: 'Playbook',
            cell: (g) => (g.differs
              ? <span className="block rounded bg-status-warn-bg px-2 py-1 text-xs text-status-warn-ink">Differs from the playbook — {g.differs}</span>
              : <span className="text-ink-4">—</span>),
          },
        ]}
        empty="No gates in this group."
        dense
      />
      {note && <p className="mt-2 text-xs text-ink-3">{note}</p>}
    </Card>
  )
}
