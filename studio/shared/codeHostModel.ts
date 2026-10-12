/** The code-host vocabulary Studio's two processes share (code-host providers, Wave 6).
 *
 * Pure: no node imports, nothing spawned. The main process decides which CLI talks to the
 * repository (`detectHostFromInputs`, the same precedence as scripts/code_host.py) and the
 * renderer explains a disabled control (`hostFeatureReason`) from the `cli` block the main
 * process hands it — so the renderer never has to probe anything itself.
 *
 * `host: none` falls through to gh on purpose: zero behaviour change for every repository that
 * exists today, and the gh error becomes today's "unavailable" text.
 */

import { parseRemote, remoteHostName, type RemoteInfo } from './codeHostRemote'

export { parseRemote, type RemoteInfo } from './codeHostRemote'

export type HostName = 'github' | 'azure-devops' | 'none'
export type HostSource = 'flag' | 'env' | 'file' | 'remote' | 'manifest' | 'default'
export type CliName = 'gh' | 'az'
export const HOSTS: readonly HostName[] = ['github', 'azure-devops', 'none']
export const CODE_HOST_FILE = '.sdlc/code-host.yaml'
export const CODE_HOST_ENV = 'SHEPHERD_CODE_HOST'
/** The pre-2.0 name — already in shells and CI, so still read, after the new one (the same
 * two-name lookup as scripts/code_host.py's `code_host_env`). */
export const LEGACY_CODE_HOST_ENV = 'SDLC_CODE_HOST'

/** What the main process knows about the CLI a project's host needs. Honesty rules: `found`
 * is a fact from tooling detection; `extension` is null when it does not apply (gh) or was not
 * probed; `signedIn` is 'unknown' until a probe actually ran — never a guessed 'no'. */
export interface CliStatus {
  name: CliName | null
  found: boolean
  extension: boolean | null
  signedIn: 'yes' | 'no' | 'unknown'
  /** The §7.1 wording for whatever is wrong, when something is. */
  reason?: string
}

/** The slice of ConnectionInfo the reason helper reads — structural, so it works before
 * shared/types.ts grows the fields (Wave 6-B wires them). */
export interface HostConnection {
  host: HostName
  cli: CliStatus
}

export type HostFeature = 'board' | 'handoff' | 'pipelineEvidence' | 'gateCredential' | 'saveWhenProtected' | 'signedInAs'

export function cliFor(host: HostName): CliName {
  return host === 'azure-devops' ? 'az' : 'gh'
}

export function cliLabel(host: HostName): string {
  return host === 'azure-devops' ? 'Azure CLI (az) with the azure-devops extension' : 'GitHub CLI (gh)'
}

// ── §7.1 wording — one place, so the banner, the Settings row and a disabled control agree ──

export const WORDING = {
  noProject: 'Optional — needed when a project\'s repository is on GitHub / Azure DevOps. You can open a project without it.',
  azMissing: 'This project\'s repository is on Azure DevOps. The Azure CLI (az) wasn\'t found; the GitHub CLI isn\'t needed for this project.',
  azExtensionMissing: 'The Azure CLI (az) was found, but the azure-devops extension isn\'t: run `az extension add --name azure-devops`.',
  azSignedOut: 'Not signed in — run `az login`.',
  azPatOnly: 'Signed in with a PAT only; Azure DevOps cannot say who you are.',
  ghMissing: 'This project\'s repository is on GitHub. The GitHub CLI (gh) wasn\'t found; the Azure CLI isn\'t needed for this project.',
  ghSignedOut: 'Not signed in — run `gh auth login`.',
  hostNone: 'This folder\'s origin is not GitHub or Azure DevOps; pull-request features are off (gh was tried, as before).',
} as const

/** Why a CLI-backed feature is off right now, or null when nothing stands in its way. The
 * reason is computed from facts the main process established; 'unknown' (not probed) is NOT a
 * reason to disable anything — the real call is the honest answer in that case. */
export function hostFeatureReason(connection: HostConnection, feature: HostFeature): string | null {
  const { host, cli } = connection
  const cliName = cliLabelShort(host)
  if (host === 'none' && feature !== 'signedInAs') return WORDING.hostNone
  const problem = cliProblem(cli)
  if (!problem) return null
  if (feature === 'signedInAs') return `unavailable (${problem})`
  switch (feature) {
    case 'board': return `Live pull-request status needs the ${cliName}`
    case 'handoff': return `The hand-off completes locally; assigning on ${hostLabel(host)} needs ${cli.name ?? cliFor(host)}`
    case 'pipelineEvidence':
      return `This needs the ${cliLabel(host)} installed and signed in on this machine, and pipelines on the installed CI platform.`
    case 'gateCredential': return `Reading the gate credential needs the ${cliName}`
    case 'saveWhenProtected':
      return `A direct push was refused and ${cli.name ?? cliFor(host)} is not available to open a pull request — nothing was saved to the shared branch`
  }
}

/** The host's display name for a sentence. `none` (and an unknown host) reads as GitHub: that is
 * the CLI every host-touching script falls through to, so it is also the history being read. */
export function hostLabel(host: HostName | undefined): string {
  return host === 'azure-devops' ? 'Azure DevOps' : 'GitHub'
}

function cliLabelShort(host: HostName): string {
  return host === 'azure-devops' ? 'Azure CLI' : 'GitHub CLI'
}

/** The short phrase for the Settings "Signed in as: unavailable (…)" row. */
function cliProblem(cli: CliStatus): string | null {
  if (!cli.found) return `${cli.name ?? 'the CLI'} not installed`
  if (cli.name === 'az' && cli.extension === false) return 'azure-devops extension missing'
  if (cli.signedIn === 'no') return cli.reason === WORDING.azPatOnly ? 'signed in with a PAT only' : 'not signed in'
  return null
}

// ── .sdlc/code-host.yaml — parsed by hand: four scalar keys, comments allowed, no YAML library in the renderer ──

export interface CodeHostFile {
  host: HostName
  organization?: string
  project?: string
  repository?: string
}

const FILE_KEYS = ['host', 'organization', 'project', 'repository'] as const

export function parseCodeHostYaml(text: string): { settings: CodeHostFile | null; error: string | null } {
  const doc: Record<string, string> = {}
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(/(^|\s)#.*$/, '').trim()
    if (!line) continue
    const m = /^([A-Za-z_]+)\s*:\s*(.*)$/.exec(line)
    if (!m) return { settings: null, error: `${CODE_HOST_FILE}: expected a mapping with a \`host:\` key` }
    const value = m[2]!.trim().replace(/^(['"])(.*)\1$/, '$2')
    if (value === '' || value === '~' || value === 'null') continue
    doc[m[1]!] = value
  }
  const host = doc.host
  if (!(HOSTS as readonly string[]).includes(host ?? '')) {
    return { settings: null, error: `${CODE_HOST_FILE}: host must be one of ${HOSTS.join(', ')} (got ${JSON.stringify(host ?? null)})` }
  }
  const settings: CodeHostFile = { host: host as HostName }
  for (const key of FILE_KEYS) if (key !== 'host' && doc[key]) settings[key] = doc[key]
  return { settings, error: null }
}

/** The three optional fields stand in for a remote parseRemote could not read — az needs them;
 * gh resolves its own repository from cwd. */
function remoteFromFile(settings: CodeHostFile): RemoteInfo | null {
  const { organization: org, project, repository: repo } = settings
  if (settings.host !== 'azure-devops' || !org || !project || !repo) return null
  return { host: 'azure-devops', org, project, repo, slug: `${org}/${project}/${repo}`, orgUrl: `https://dev.azure.com/${org}`, webUrl: `https://dev.azure.com/${org}/${project}/_git/${repo}` }
}

// ── detection precedence: env → file → remote → manifest tie-breaker → none (Python's order) ──

export interface DetectInputs {
  /** `SHEPHERD_CODE_HOST` (Studio has no `--host` flag; the env is what reaches a desktop app). */
  flagOrEnv?: string | null
  /** `SDLC_CODE_HOST`, the pre-2.0 name — read only when `flagOrEnv` holds no value. */
  legacyEnv?: string | null
  fileHost?: CodeHostFile | null
  /** The parse error for `.sdlc/code-host.yaml` when it exists but could not be read. */
  fileError?: string | null
  /** `git remote get-url origin`, or null when there is none / git failed. */
  remoteUrl: string | null
  /** `.claude/harness-manifest.json` `packs`; null when unreadable (reads as GitHub, as doctor does). */
  manifestPacks?: string[] | null
}

export interface Detection {
  host: HostName
  source: HostSource
  remote: RemoteInfo | null
  detail: string
}

export function detectHostFromInputs(inputs: DetectInputs): Detection {
  const url = inputs.remoteUrl?.trim() || null
  const remote = parseRemote(url)
  const notes: string[] = []

  // The first variable that holds a value wins — an empty one counts as unset, as it always
  // did — and the detail names whichever it was, so a person reads the variable they set.
  const env = inputs.flagOrEnv
    ? { name: CODE_HOST_ENV, value: inputs.flagOrEnv }
    : inputs.legacyEnv ? { name: LEGACY_CODE_HOST_ENV, value: inputs.legacyEnv } : null
  if (env) {
    if ((HOSTS as readonly string[]).includes(env.value)) return { host: env.value as HostName, source: 'env', remote, detail: `${env.name}=${env.value}` }
    notes.push(`${env.name}=${JSON.stringify(env.value)} ignored: not one of ${HOSTS.join(', ')}`)
  }

  if (inputs.fileHost) {
    const file = inputs.fileHost
    return { host: file.host, source: 'file', remote: remote ?? remoteFromFile(file), detail: `${CODE_HOST_FILE} host: ${file.host}` }
  }
  if (inputs.fileError) notes.push(inputs.fileError)

  if (remote) return { host: remote.host, source: 'remote', remote, detail: [`from origin ${url}`, ...notes].join('; ') }

  notes.unshift(url ? `unrecognised host "${remoteHostName(url)}"` : 'no origin remote')

  // The manifest decides only when the remote could not: a fresh clone without `origin` on an
  // Azure Pipelines install is almost certainly an Azure DevOps repository. It never overrides a
  // remote that parsed — GitHub + Azure Pipelines is a real combination.
  if (inputs.manifestPacks?.includes('cicd/azure-devops')) {
    return { host: 'azure-devops', source: 'manifest', remote: null, detail: [...notes, 'harness manifest names cicd/azure-devops'].join('; ') }
  }
  return { host: 'none', source: 'default', remote: null, detail: notes.join('; ') }
}
