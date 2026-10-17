// BoardsToday — the two Azure Boards sections of the Today column (the catch-up line with its buttons, and the
// Boards rows), mounted only where a board can exist. A project whose code host is not Azure DevOps, and whose
// mirror was never measured, gets NOTHING here: no eyebrow, no "not set up" line, no height. The spec card's own
// chip still says "work items are not set up" when a person looks at a spec, so nothing is silenced where a
// person acts; the Today column simply does not spend its height on a board that is not there (the 1280×800
// overlap rule puts Today above the lanes, uncapped).
//
// Shown when the connection says Azure DevOps, or when the command center holds a status in which the mirror
// MEASURED something (`as_of`, a count, a class, a debt row or a plan). A status document that merely READ is
// not evidence: `ado_sync.py status --json` answers for every project, with or without `.sdlc/ado.yaml`, and a
// never-pulled mirror's answer is all nulls ("no data (never pulled)") — so `ado.ok` alone put both sections on
// the e2e fixture, which is not on Azure DevOps. Steering stays the children's own concern. No read is started
// here (G18): both children spawn only on a click.
import type { AdoSyncView } from '../../../shared/adoTypes'
import type { CommandCenter, SourcedBlock } from '../../../shared/types'
import { hostFeatureReason, WORDING } from '../../../shared/codeHostModel'
import { useConnection } from '../../stores/connectionStore'
import { AdoTodayRows } from '../today/AdoTodayRows'
import { CatchUp } from './CatchUp'

export interface BoardsTodayProps {
  projectPath: string
  cc: Pick<CommandCenter, 'ado' | 'capabilities'> | null
  strip?: boolean
  steering?: boolean
  onPulled?: Parameters<typeof CatchUp>[0]['onPulled']
}

/** Whether the plugin's status document holds anything the mirror measured. All-null — the never-pulled answer
 * every project gets — is "no data", not a board. Pure. */
export function statusMeasured(view: AdoSyncView | null | undefined): boolean {
  if (!view) return false
  return view.as_of !== null || view.by_class !== null || view.debt !== null || view.last_plan !== null
    || Object.values(view.counts).some((n) => n !== null)
}

/** Whether the Today column should show its Boards sections at all. Pure, so a test can pin every case. */
export function boardsPresent(connection: { host: string } | null, ado: SourcedBlock<AdoSyncView> | null | undefined): boolean {
  if (ado?.ok && statusMeasured(ado.data)) return true
  if (!connection) return false
  return hostFeatureReason(connection as Parameters<typeof hostFeatureReason>[0], 'workItems') !== WORDING.boardsNotConfigured
}

export function BoardsToday({ projectPath, cc, strip = false, steering = false, onPulled }: BoardsTodayProps) {
  const connection = useConnection()
  if (!boardsPresent(connection, cc?.ado)) return null
  return (
    <>
      <CatchUp projectPath={projectPath} ado={cc?.ado} capabilities={cc?.capabilities} steering={steering} onPulled={onPulled} />
      <AdoTodayRows cc={cc} strip={strip} />
    </>
  )
}
