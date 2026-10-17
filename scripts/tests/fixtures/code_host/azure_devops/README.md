# Azure DevOps fixtures — what `az … -o json` returns, redacted

These documents are the inputs to `scripts/ado_map.py`'s pure normalisers and to the `FakeAz`
router in `scripts/tests/test_ado_import.py`. Every file carries a `_provenance` key:

| Value | Meaning |
|---|---|
| `"hand-written (unverified)"` | Written from the REST API reference and the extension's source, never seen from a real org. The field names may be wrong. |
| `"captured <YYYY-MM-DD> <org anonymised>"` | Captured from a real organisation with the commands below and passed through `redact.py`. |

`scripts/tests/test_fixture_provenance.py` fails on a missing key and **lists** the hand-written
files in its output, so an unverified shape stays visible until a capture replaces it. When a
capture lands, flip the matching **(unverified)** note in `docs/proposals/code-host-providers.md`.

## File convention

A fixture whose az output is a JSON **array** is wrapped as `{"_provenance": …, "_command": …,
"value": [...]}` (a bare array has nowhere to carry provenance); one whose output is an **object**
carries `_provenance` as an extra top-level key. `scripts/tests/ado_fixtures.py::load()` unwraps
both.

## Capture runbook (Wave 0 — a person with access to an Azure DevOps organisation)

Use a scratch config dir so your own defaults and PAT are not involved, and the two environment
variables so nothing installs itself or phones home:

```bash
export AZURE_CONFIG_DIR="$(mktemp -d)" AZURE_EXTENSION_USE_DYNAMIC_INSTALL=no AZURE_CORE_COLLECT_TELEMETRY=no
az login
az extension add --name azure-devops
ORG=https://dev.azure.com/<org>  P=<project>  R=<repo>  PR=<an active PR id>  MERGED=<a completed PR id>
S="--detect false --org $ORG --project $P"
```

| Fixture | Command (append `--only-show-errors -o json`) |
|---|---|
| `account_show.json` | `az account show --query "{user:user.name,tenant:tenantId}"` |
| `repos_show.json` | `az repos show $S --repository $R` |
| `pr_list.json` | `az repos pr list $S --repository $R --status all --top 5` — include one active, one completed, one abandoned and one draft PR |
| `pr_show.json` | `az repos pr show --id $PR --org $ORG` |
| `pr_policy_list.json` | `az repos pr policy list --id $PR --org $ORG` — on a PR with at least one build-validation policy in each of queued/running/approved/rejected if you can |
| `pr_reviewer_list.json` | `az repos pr reviewer list --id $PR --org $ORG` |
| `pr_threads.json` | `az devops invoke --area git --resource pullRequestThreads --route-parameters project=$P repositoryId=<repo GUID from repos_show> pullRequestId=$PR --api-version 7.1 --org $ORG` — on a PR the grader has commented on, and where a reviewer was added after creation |
| `policy_list.json` | `az repos policy list $S --repository-id <repo GUID> --branch main` |
| `pipelines_list.json` | `az pipelines list $S --repository $R --repository-type tfsgit` — confirm whether `process.yamlFilename` is present |
| `runs_list.json` | `az pipelines runs list $S --pipeline-ids <id> --top 10 --query-order QueueTimeDesc` |
| `timeline.json` | `az devops invoke --area build --resource timeline --route-parameters project=$P buildId=<a failed deploy run id> --api-version 7.1 --org $ORG` |
| `variable_groups.json` | `az pipelines variable-group list $S` |
| `variable_group_variables.json` | `az pipelines variable-group variable list $S --group-id <id>` |
| `environments.json` | `az devops invoke --area distributedtask --resource environments --route-parameters project=$P --api-version 7.1-preview.1 --org $ORG` (resource name unverified) |
| `deployment_records.json` | `az devops invoke --area distributedtask --resource environmentdeploymentrecords --route-parameters project=$P environmentId=<id> --api-version 7.1-preview.1 --org $ORG` (unverified) |
| `boards_query.json` | `az boards query $S --wiql "SELECT [System.Id],[System.CreatedDate],[Microsoft.VSTS.Common.ClosedDate],[System.State] FROM WorkItems WHERE [System.TeamProject] = @project AND [System.WorkItemType] = 'Bug' AND [System.Tags] CONTAINS 'incident'"` |

## Redaction rule

Pipe every capture through `redact.py` **before** it is saved anywhere, even locally:

```bash
az repos pr list $S --repository $R --status all --top 5 --only-show-errors -o json \
  | python scripts/tests/fixtures/code_host/azure_devops/redact.py --org <org> > pr_list.json
```

`redact.py` is pure and deterministic: GUIDs become `00000000-0000-0000-0000-00000000000N` in
order of first appearance (so two fields naming the same identity stay equal), UPNs and emails
become `personN@example.com`, display names follow, and the organisation name becomes `contoso`
wherever it appears. The policy TYPE GUIDs are vocabulary and are kept verbatim. Nothing else is
changed — enum values, dates, booleans and nesting are the whole point of a fixture. Then wrap
per the file convention above and set `_provenance` to `captured <date> <org anonymised>`.

Check the result by eye for anything the regexes could not know is personal (a PR title, a
comment body) before committing it.

A Boards (work item) capture names more than the organisation. For it, `redact.py` also takes
`--project <name>` (→ `Claims`), `--team <name>` (→ `Claims Team`), `--rename <old>=<new>` (an area
or iteration name, repeatable) and `--mask-free-text` (every `description`, `helpText` and `xmlForm`
becomes `[redacted: free text]`); without them its output is unchanged. Comment and history text
then goes through `redact_wit.py`. The Boards captures (2026-10-14: the process; 2026-10-15: the first
live apply, its items, writes and comments) and what each settled are in `wit/captured/CAPTURE-NOTES.md`.
