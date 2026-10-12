// Azure DevOps through the Azure CLI (docs/proposals/code-host-providers.md §4.1), filling the
// same shapes GitHub does so sync.ts's isOursToMerge, the approval rung and the checks rung read
// an Azure DevOps pull request without knowing it is one. Every argv carries
// `--detect false --org --project [--repository]` from the PARSED REMOTE: az's own detection
// costs a `GET …/vsts/info` round-trip per call and needs auth.
//
// Two owner decisions live here. D-OWNER-8: Studio never completes an Azure DevOps pull request
// in v1 — `files: null` on every entry sends the poll down its existing fail-closed branch, and
// mergePullRequest refuses outright in case anything ever reaches it. D-OWNER-5 (typed actor)
// is the caller's: this host only says, honestly, when the CLI cannot name the person.

import { WORDING } from '../../../shared/codeHostModel'
import type { RemoteInfo } from '../../../shared/codeHostRemote'
import { AzError, azJson as defaultAzJson, MATERIALIZED_HINT } from '../az'
import { CodeHostUnavailable, type CodeHost, type CreatePullRequestOptions, type CreatePullRequestResult, type Identity, type Memo, type PrListEntry, type RepoView } from '../codeHostTypes'
import { mapChecks, mapPolicies, mapPr, stripRef } from './adoMap'

export { mapChecks, mapPolicies, mapPr, mapReviews, stripRef, AdoShapeError } from './adoMap'

export interface AzureDevOpsHostDeps {
  azJson?: <T>(args: string[], cwd: string) => Promise<T>
  memo?: Memo
  /** process.env by default — read for AZURE_DEVOPS_EXT_PAT, which is how "PAT only" is told
   * apart from "signed out" when `az account show` fails. */
  env?: Record<string, string | undefined>
}

const passThrough: Memo = (_key, fn) => fn()

/** `--description` takes one argument per line. argparse reads a bare `-x` (no space) as an
 * option and refuses the whole command, so such a line gets a leading space — the only edit
 * ever made to a person's text, and only when az would otherwise reject it. */
export function descriptionLines(body: string): string[] {
  return body.split('\n').map((line) => (line.startsWith('-') && !line.includes(' ') ? ` ${line}` : line))
}

/** The az argv per operation — exported so tests pin flags without spawning. */
export const ADO_ARGV = {
  scope: (r: RemoteInfo, withRepository = true): string[] => [
    '--detect', 'false', '--org', r.orgUrl ?? '', '--project', r.project ?? '',
    ...(withRepository ? ['--repository', r.repo] : []),
  ],
  whoAmI: (): string[] => ['account', 'show'],
  repoShow: (r: RemoteInfo): string[] => ['repos', 'show', ...ADO_ARGV.scope(r)],
  policyList: (r: RemoteInfo, repositoryId: string, branch: string): string[] => [
    'repos', 'policy', 'list', ...ADO_ARGV.scope(r, false), '--repository-id', repositoryId, '--branch', branch,
  ],
  prCreate: (r: RemoteInfo, o: CreatePullRequestOptions): string[] => [
    'repos', 'pr', 'create', ...ADO_ARGV.scope(r),
    '--source-branch', o.head, '--target-branch', o.base, '--title', o.title,
    '--description', ...descriptionLines(o.body),
    ...(o.reviewer ? ['--required-reviewers', o.reviewer] : []),
  ],
  prList: (r: RemoteInfo, head: string): string[] => [
    'repos', 'pr', 'list', ...ADO_ARGV.scope(r), '--source-branch', head, '--status', 'active', '--top', '5',
  ],
  prPolicyList: (r: RemoteInfo, number: number): string[] => ['repos', 'pr', 'policy', 'list', '--id', String(number), '--org', r.orgUrl ?? ''],
} as const

export const ADO_MERGE_REFUSAL = 'Shepherd does not complete Azure DevOps pull requests in this version — complete it in Azure DevOps once checks and approval are in.'

export class AzureDevOpsHost implements CodeHost {
  readonly kind = 'azure-devops' as const
  readonly cli = 'az' as const
  private readonly azJson: NonNullable<AzureDevOpsHostDeps['azJson']>
  private readonly memo: Memo
  private readonly env: Record<string, string | undefined>

  constructor(private readonly cwd: string, readonly remote: RemoteInfo, deps: AzureDevOpsHostDeps = {}) {
    this.azJson = deps.azJson ?? defaultAzJson
    this.memo = deps.memo ?? passThrough
    this.env = deps.env ?? process.env
  }

  /** An AzError that means "this CLI cannot do it here" becomes the §7.1 reason; anything
   * else (a real failure of a real call) is passed on as it was. */
  private unavailable(err: unknown): unknown {
    if (!(err instanceof AzError)) return err
    switch (err.failure) {
      case 'not_installed': return new CodeHostUnavailable(WORDING.azMissing, 'not_installed')
      case 'extension_missing': return new CodeHostUnavailable(WORDING.azExtensionMissing, 'extension_missing')
      case 'signed_out': {
        const patOnly = Boolean(this.env.AZURE_DEVOPS_EXT_PAT || this.env.AZURE_DEVOPS_EXT_AUTH_TOKEN)
        const wording = patOnly ? WORDING.azPatOnly : WORDING.azSignedOut
        return new CodeHostUnavailable(wording, patOnly ? 'pat_only' : 'signed_out', `If you are signed in and Azure DevOps still refuses: ${MATERIALIZED_HINT}.`)
      }
      default: return err
    }
  }

  private async az<T>(args: string[]): Promise<T> {
    try {
      return await this.azJson<T>(args, this.cwd)
    } catch (err) {
      throw this.unavailable(err)
    }
  }

  whoAmI(): Promise<Identity> {
    return this.memo('whoAmI', async () => {
      const account = await this.az<{ user?: { name?: string; type?: string }; tenantId?: string }>(ADO_ARGV.whoAmI())
      const login = account?.user?.name?.trim() ?? ''
      // `az account show` with no account prints nothing useful; an empty name is the PAT-only
      // / signed-out case the honesty table wants named, not an Identity with a blank login.
      if (!login) throw this.unavailable(new AzError('az account show named no user', 'signed_out', { id: '', command: 'az', args: ADO_ARGV.whoAmI(), cwd: this.cwd, startedAt: '', durationMs: 0, exitCode: 1, stdout: '', stderr: '', ok: false }))
      return { login, kind: 'upn', tenant: account.tenantId ?? null }
    })
  }

  repoView(): Promise<RepoView> {
    return this.memo('repoView', async () => {
      const repo = await this.az<{ id?: string; name?: string; defaultBranch?: string | null; webUrl?: string; isFork?: boolean | null }>(ADO_ARGV.repoShow(this.remote))
      const id = typeof repo.id === 'string' ? repo.id : null
      return {
        id, name: repo.name ?? null, ownerLogin: null,
        defaultBranch: repo.defaultBranch ? stripRef(repo.defaultBranch) : null,
        webUrl: repo.webUrl ?? null, isFork: typeof repo.isFork === 'boolean' ? repo.isFork : null,
        headOwnerKey: id, // what `pr list` rows carry as repository.id — the fork check's comparand
      }
    })
  }

  async isBranchProtected(defaultBranch: string): Promise<boolean | null> {
    const view = await this.repoView()
    if (!view.id) return null // no GUID, no scoped policy list — "couldn't read", not "no"
    const configs = await this.az<unknown[]>(ADO_ARGV.policyList(this.remote, view.id, defaultBranch))
    return mapPolicies(configs).enforcing
  }

  async createPullRequest(opts: CreatePullRequestOptions): Promise<CreatePullRequestResult> {
    const created = await this.az<{ pullRequestId?: number }>(ADO_ARGV.prCreate(this.remote, opts))
    const id = created?.pullRequestId
    if (typeof id !== 'number') throw new Error('az repos pr create returned no pullRequestId')
    return { url: `${this.remote.webUrl}/pullrequest/${id}`, note: ADO_MERGE_REFUSAL }
  }

  async listOpenPullRequests(head: string): Promise<PrListEntry[]> {
    const prs = await this.az<Array<Record<string, unknown>>>(ADO_ARGV.prList(this.remote, head))
    const out: PrListEntry[] = []
    for (const pr of Array.isArray(prs) ? prs : []) {
      // One policy read per open PR — a failure here propagates rather than reading as "no checks".
      const records = await this.az<unknown[]>(ADO_ARGV.prPolicyList(this.remote, Number(pr.pullRequestId)))
      // `files: null` is the v1 fail-closed signal (sync.ts reads `pr.files ?? []`); PrListEntry's
      // type still says `files?: Array` — widening it to `| null` is sync.ts's one-line change
      // in Wave 6-B, so the cast is confined to this boundary rather than touching sync.ts here.
      out.push(mapPr(pr, this.remote.webUrl, mapChecks(records)) as unknown as PrListEntry)
    }
    return out
  }

  async mergePullRequest(_number: number): Promise<string> {
    throw new CodeHostUnavailable(ADO_MERGE_REFUSAL, 'fail_closed')
  }
}
