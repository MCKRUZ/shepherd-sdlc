# Code-host providers — GitHub (`gh`) or Azure DevOps (`az`), chosen by the repository

The plugin talks to the repository's code host for a handful of things: find a spec's pull
request, read its checks and the grader's verdict, open a draft PR at hand-off, read branch
protection, read pipeline runs, list the secrets the gates sign in with. Today every one of those
goes through the GitHub CLI. This layer adds Azure DevOps through the Azure CLI **without changing
a byte of GitHub behaviour**: same argv, same text, same tests, unmodified.

This is a **Tier-3 reference**: loaded on demand, read by nothing at runtime. The executable halves
are `scripts/code_host.py` (detection, CLI state, identity resolution, the documented contract) and
`scripts/ado_import.py` + `scripts/ado_map.py` (the Azure DevOps transport, fetchers and pure
normalisers). The master design is `docs/proposals/code-host-providers.md`; this file is the
shared contract the implementation waves read.

---

## Two axes, never merged

| Axis | Question | Source of truth | Values |
|---|---|---|---|
| **Code host** | Which CLI talks to the *repository* (PRs, reviewers, identity, branch policies) | `git remote get-url origin` + the overrides below | `github` / `azure-devops` / `none` |
| **CI platform** | Where the *pipelines* live (runs, secrets, pipeline dirs) | `.claude/harness-manifest.json` → `packs ∋ cicd/azure-devops` | `github` / `azure-devops` |

`code_host.detect_host()` owns the first; `code_host.installed_ci_platform()` owns the second (a
ten-line twin of `doctor.installed_platform()`, pinned by a test to agree with it on doctor's six
manifest cases — `doctor.py` itself is not imported). GitHub + Azure Pipelines is a legitimate
combination; a reader that sees the two disagree gets an informational note, never a failure.

## Host detection — override precedence

| # | Source | `source` tag | Works with no `.sdlc/`? | Notes |
|---|---|---|---|---|
| 1 | `--host github\|azure-devops\|none` on every host-touching script | `flag` | yes | one invocation |
| 2 | env `SHEPHERD_CODE_HOST`, then `SDLC_CODE_HOST` (the pre-2.0 name, still read) | `env` | yes | process tree; the new name wins when both are set and `detail` names whichever supplied the value; an unrecognised value is ignored and named in `detail` |
| 3 | `.sdlc/code-host.yaml` → `host:` | `file` | no | travels with the clone; written by `set_setting.py code-host` |
| 4 | `git remote get-url origin` → `parse_remote` | `remote` | yes | **the default path** |
| 5 | harness manifest, CI axis | `manifest` | no | **tie-breaker only** when there is no usable remote; never overrides a parsed remote |
| 6 | nothing matched | `default` | — | `host: none` |

`host == none` falls through to `gh` (`cli_for("none") == "gh"`): zero behaviour change for every
repository that exists today, and the gh error becomes the familiar `code_host_available: false`.
Studio labels it "unrecognised remote — tried gh".

### `.sdlc/code-host.yaml`

```yaml
host: azure-devops            # github | azure-devops | none   (required)
organization: contoso         # optional — only for a remote parse_remote cannot read
project: Claims               # optional
repository: claims-api        # optional
```

Validated like the other `.sdlc/*.yaml` singletons; never written into `state.yaml`
(`advance_phase.py` is protected). When all three optional fields are present they stand in for
the parsed remote so `ado_import._scope()` can still build `--org/--project/--repository`.

### Remote → host rule (`code_host.parse_remote`)

The shared fixture is `scripts/tests/fixtures/code_host/remote-urls.json`
(`[{url, host, org, project, repo, slug, org_url}]`), consumed by pytest **and** by Studio's
vitest port so the Python and TypeScript rules cannot drift. GHES, GitLab and ADO Server parse
as `none`; `.sdlc/code-host.yaml` is the escape hatch.

## The provider contract

No class hierarchy and no registry. The "interface" is a documented set of names, signatures
and return shapes — `code_host.PROVIDER_FUNCTIONS` — pinned by
`scripts/tests/test_provider_parity.py`: for every entry `ado_import` exposes the name with
exactly the signature of the GitHub-side function it mirrors (or the documented signature when
GitHub has no standalone function today).

| `ado_import` name | Mirrors (GitHub, unchanged) | Signature | Returns |
|---|---|---|---|
| `whoami` | — (new; `gh api user --jq .login` inline in `connection_report`) | `(repo_root) -> dict` | `Identity` |
| `repo_view` | — (`gh repo view` inline) | `(repo_root) -> dict` | `RepoView` |
| `find_pr_for_branch` | `spec_status.find_pr_for_branch` | `(repo_root, branch_name: str) -> dict \| None` | `PullRequest` |
| `fetch_pr_comment_bodies` | `spec_status.fetch_pr_comment_bodies` | `(repo_root, pr_number: int) -> list[str]` | bodies, oldest → newest |
| `fetch_pr_events` | `github_import.fetch_pr_events` | `(repo_root: str, number: int) -> list[dict]` | gh issue-event shape (`review_requested`) or `[]` |
| `fetch_all_pull_requests` | `spec_status.fetch_all_pull_requests` | `(repo_root, limit: int = 1000) -> dict[str, dict]` | keyed by head branch |
| `fetch_pr_checks` | — (part of `statusCheckRollup`) | `(repo_root, pr_number: int) -> list[dict]` | `Check[]` |
| `fetch_branch_policies` | `pipeline_proof._read_ruleset` | `(cwd: str, nwo: str, installed_name: str \| None) -> dict \| None` | `Ruleset` |
| `create_draft_pr` (alias `assign_on_host`) | `handoff.assign_on_host` | `(repo_root, branch_name: str, base_branch: str, spec_id: str, spec_name: str, developer: str, checker: str) -> str` | web URL |
| `complete_pr` | — (Studio-only `gh pr merge`) | `(repo_root, pr_number: int) -> str` | web URL |
| `fetch_runs` | `pipeline_proof._fetch_runs` | `(cwd: str, workflow_file: str, limit: int) -> list[dict]` | `Run[]` |
| `run_jobs` | — (`gh run view --json jobs` inline) | `(cwd: str, run_id: int) -> dict` | `{jobs: Job[]}` |
| `secret_names` | — (`gh secret list` inline in `gate_auth.status`) | `(repo_root) -> list[str]` | variable names |

Each consuming script dispatches at its own call site (`_host_fn("find_pr_for_branch")` →
`ado_import.find_pr_for_branch` when `host == "azure-devops"`, else its own function). The
existing monkeypatch seams (`ss.gh_json`, `h.run_gh`, `cr._gh`, `github_import.run_gh`,
`ga.subprocess.run`) keep intercepting the GitHub path, which is why no existing test changes.

### Error type

`ado_import.AdoImportError` **is a subclass of** `github_import.GitHubImportError`, so every
existing `except GitHubImportError` (including the frozen `scorecard.py`) already catches an az
failure. `code_host.CodeHostError` is an alias of `GitHubImportError` for new code to read
naturally. A normaliser that meets an az document missing a key it needs raises
`AdoImportError("unexpected az shape: missing <what>")` — it never defaults, because a default
is how "nothing here" gets fabricated from a field rename.

### Normalised shapes (gh vocabulary, by design)

The gh JSON shapes **are** the normalised shapes, written down as TypedDicts in
`scripts/code_host_shapes.py` and re-exported by `code_host`: `Identity`, `PullRequest`, `Check`,
`Review`, `ReviewRequest`, `Run`, `Job`, `Ruleset`, `RepoView`. ADO is the single translator
(`ado_map.map_pr / map_checks / map_reviews / map_runs / map_jobs / map_policies / map_threads`).

ADO-specific honesty inside those shapes: `updatedAt = None` (no such field), `reviews[].submittedAt
= None`, `author.login` = the UPN, `handle` only when the roster resolves it, `_notes[]` for every
conservative mapping of an unknown enum, `_checks_unavailable: True` on bulk rows past the
checks cap, `files = None` when iterations were not fetched.

## Identity — one roster key, one optional host key

| Item | Rule |
|---|---|
| Roster key | `people[].handle` stays `^@[A-Za-z0-9-]+$` on both hosts; spec frontmatter and `check_spec.py` unchanged |
| Host key (optional) | `people[].email` — the sign-in identity on Azure DevOps (UPN or mail); unique, case-insensitive (Wave 2, `validate_team.py`) |
| Resolution | `code_host.resolve_person(roster, identity)`: GitHub → `@` + `login` if that handle is in the roster, else `None`; ADO → the handle whose `email` equals `identity.login` case-insensitively, else `None` |
| Never | a provider guesses a handle from a display name or a UPN prefix |

`create_draft_pr` on ADO: the developer is **named in the description** (ADO has no assignee); the
checker becomes `--required-reviewers <email>` when the roster has one, otherwise the PR is opened
without a reviewer and the description says so. The caller (`handoff`) decides whether that is an
`assignment_error`; the provider never fails the local half over it.

## CLI state (`code_host.cli_state(host)`)

| State | Meaning | Detail names the fix |
|---|---|---|
| `available` | CLI found, extension present (az), signed in | — |
| `not_installed` | `shutil.which` found nothing | "the Azure CLI is not installed" / "the GitHub CLI is not installed" |
| `extension_missing` | az found, `az extension show --name azure-devops` failed | "run `az extension add --name azure-devops`" |
| `signed_out` | `az account show` / `gh auth status` failed | "run `az login`" / "run `gh auth login`" |
| `unknown` | the probe itself failed or was skipped | never read as "no" |

Every host-touching `--json` carries a top-level `host` block `{name, source, cli, cli_state,
detail}` so a reader can see *why* a host was chosen. "Unavailable" rides that block; it is never a
fourth check state and never a false `no`.

## Studio contract (`ConnectionInfo` additions, Waves 6–7)

`host: 'github'|'azure-devops'|'none'`, `hostSource`, `cli: { name: 'gh'|'az'|null, found,
extension: boolean|null, signedIn: 'yes'|'no'|'unknown', reason? }`, `accountSource:
'roster'|'host'|'typed'|null`, `rosterHandle: string|null`. `hostFeatureReason(connection,
feature)` returns one of: "Live pull-request status needs the Azure CLI", "The hand-off completes
locally; assigning on Azure DevOps needs az", "This project's repository is on Azure DevOps. The
Azure CLI (az) wasn't found; the GitHub CLI isn't needed for this project.", "…found, but the
azure-devops extension isn't: run `az extension add --name azure-devops`.", "Not signed in — run
`az login`.", "Signed in with a PAT only; Azure DevOps cannot say who you are.", "This folder's
origin is not GitHub or Azure DevOps; pull-request features are off (gh was tried, as before)."

## Scorecard import ids (Wave 5)

`gh_id` prefixes on Azure DevOps: `ado-pr-merge:<id>`, `ado-pr-review:<id>`,
`ado-deploy:<env>:<rec>`, `ado-wi:<id>` — they never collide with the `gh-*` ids, so a ledger can
hold both hosts' history.

## Transport rules for `az` (`ado_import.run_az` / `az_json`)

UTF-8 forced; 60 s timeout; `shutil.which("az")` (PATHEXT → `az.cmd`); env
`AZURE_EXTENSION_USE_DYNAMIC_INSTALL=no` + `AZURE_CORE_COLLECT_TELEMETRY=no` on every spawn;
always `--only-show-errors`; `az_json` adds `-o json`; empty stdout → `[]`; unparseable →
`AdoImportError`. Always `--detect false --org --project [--repository]` from the parsed remote
(never az's own `vsts/info` round-trip). `ado_import.AZ_CONTRACT` lists every argv prefix used;
`test_az_contract.py` checks each against local `--help` text and skips cleanly when the
extension is absent.

## Fixtures and provenance

`scripts/tests/fixtures/code_host/azure_devops/captured/*.json` is real `az` output captured
2026-10-05 from a live organisation and anonymised (`CAPTURE-NOTES.md` beside it lists every fact
it settled); each file is wrapped `{_provenance, _command, _secs, value}`. The folder above it
holds the older hand-written documents (`_provenance: "hand-written (unverified)"`), still the
only evidence for shapes no real organisation exercised (a draft PR, a `rejected` evaluation, a
grader comment carrying the verdict block). `tests/ado_fixtures.load(name)` prefers the captured
file and `load(name, hand_written=True)` reaches the other on purpose; `test_fixture_provenance.py`
fails on a missing key and **lists** what is still hand-written, so an unverified shape stays
visible until a capture lands. The capture runbook (exact commands, redaction rule) is that
folder's `README.md`; `redact.py` is the pure redactor.

What the capture changed in the contract (each a fact from the data): `reviewers[].isRequired` is
`null`, not `false`, when a reviewer is not required; `lastMergeCommit` sits on every ACTIVE PR as
the trial merge and is trusted only when `status == completed`; `labels` ride `pr list` by
default; `repos pr policy list` on an active PR with no policies answers `[]` — "no checks",
never "unknown"; threads carry a typed `properties` bag (`CodeReviewThreadType` ∈ `ReviewersUpdate`,
`VoteUpdate`, `StatusUpdate`, `RefUpdate`), so `fetch_pr_events` derives `review_requested` from the
`ReviewersUpdate` thread's `publishedDate` and never parses the system comment's prose (the wording
is "joined as a reviewer", not "added … as a reviewer"); the grader / security pipelines post a
**text** comment opening with `<!-- rails-gate:<pipeline> -->`; `pullRequestCommits` is a real
invoke resource; `az pipelines list` carries no `process`, so the YAML file comes from one
`az pipelines show --id N` per definition (cached); runs carry no `_links`, so the web URL is
`{org_url}/{project}/_build/results?buildId={id}`; environments and deployment records need
`--api-version 7.1-preview` exactly (`7.1-preview.1` crashes the extension); `az boards query`
prints nothing when no work item matches (→ `[]`); `az devops user show` may be Access Denied, so
the display-name lookup is optional and silent; and az's **default account decides the token** — the
`cli_state` detail names that rule and the HTTP 403 "identity … has not been materialized" case.

## Protected — byte-for-byte unchanged

`scripts/scorecard.py`, `generate_status.py`, `check_gates.py`, `check_spec.py`,
`advance_phase.py`, `phase_model.py`, `new_spec.py`, `harness/**`, `phases/phase-registry.yaml`,
`agents/section-evaluator.md`, `commands/sprd-coach.md`, `commands/sprd-spec.md`,
`templates/state-init.yaml`; `sprint.py` text and exit codes; `doctor.py`; `github_import.py`;
`pipeline_proof_model.py`. No existing test file is edited — new coverage is new files or new
additive classes. `scripts/tests/test_gh_argv_golden.py` is the mechanical proof: it records the
`gh` argv each script issues on gh-shaped fixtures and compares against a golden captured from
the pre-change scripts.
