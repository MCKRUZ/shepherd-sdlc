# Capture notes — Azure Boards (work item) shapes as actually returned (2026-10-14)

The B0 capture of the build kit's §10 H1, steps 0–10 (read-only), against one real organisation.
Facts only: no client content is recorded here, and every file in this folder passed through the
redactor first.

| | |
|---|---|
| Date | 2026-10-14 |
| Tooling | Azure CLI 2.87.0, azure-devops extension 1.0.8, macOS |
| Sign-in | Entra: the person's own `az login` (`--allow-no-subscriptions`, the organisation's tenant). No personal access token was used, handed to the plugin or an assistant, or written to a file. |
| Scope | GETs only (steps 0–10 plus the team's field values). Nothing was written to the board. |
| Calls | every `devops invoke` ran `--org <org> --only-show-errors -o json --detect false --api-version 7.1`; the identity read ran as `az rest` (fact 3) |

## How the files were made

Each document is the `az … -o json` answer, wrapped `{"_provenance": "captured 2026-10-14 (org anonymised)",
"_command": [...], "value": ...}`. `_command` is the argv that ran, with the anonymised names;
`invoke_locations.json` also carries `_filter` (the wit/work/core subset of the listing).

Redaction: `redact.py --org <org> --project <project> --team <team> --rename <name>=<fake> … --mask-free-text`
(the project/team/rename/mask options were appended to `redact.py` for this capture; without them its output is
unchanged). What that does:

* organisation → `contoso`; project → `Claims` (so the process reads `Agile_Claims` and the default team
  `Claims Team`); the board's team → `Claims Team`; the other three area names → `Intake`, `Payments`, `Fraud`;
  every `Iteration N` → `Sprint N`. A name is replaced as a whole value or a whole path/URL segment, never inside
  other text.
* every `description`, `helpText` and `xmlForm` value → `[redacted: free text]` (what the client typed into its
  own process, and the form layouts).
* GUIDs and addresses as `redact.py` always does. GUIDs are numbered **per document**: a fake GUID is a stable
  anchor within one file only (a team iteration's `id` does not equal its classification node's `identifier`
  here, though it does in the organisation; the plugin joins iterations by path).
* `connection_data.json`: every identity field (`id`, `descriptor`, `subjectDescriptor`, `providerDisplayName`,
  `customDisplayName`, `properties.Account.$value`, `instanceId`, `deploymentId`) is set to the stand-ins of the
  hand-written `connection_data.json` (`person1@example.com`, `Person 1`, id `…0002`), so the hand-written comment
  fixtures' author ids still join with it.
* The project's default team and the board's team are two different teams in the organisation; both read
  `Claims Team` after redaction.

The one GUID that is not anonymised is `499b84ac-1321-427f-aa17-267ca6975798`, Azure DevOps' fixed Entra
resource id, and only in `connection_data.json`'s `_command`.

## The five facts, and what each changed in code

| # | Fact | In code |
|---|---|---|
| 1 | `az devops invoke --area wit --resource states --route-parameters project=P type=T` does not resolve: "--resource and --api-version combination is not correct". The per-type states live at resource `workItemTypeStates`, route `{project}/_apis/wit/workitemtypes/{type}/states`, released 7.1. `discover` died on exactly this call (`wit/states type=Spec`). The `workItemTypes` answer already carries every type's `states`, equal — same entries, same order — to the `workItemTypeStates` answer for all seven types read. | `boards_contract.WIT_ROUTES["type_states"]` → `workItemTypeStates`, verified. `ado_schema.discover` takes a type's states from the `workItemTypes` answer (`_type_states`) and spends no call on them; the schema is the same. |
| 2 | `--resource fields --route-parameters project=P type=T` ignores `type` and answers the project-wide list (212,625 bytes, the same bytes as the call without `type`). The per-type location is resource `workItemTypesField`, route `{project}/_apis/wit/workitemtypes/{type}/fields/{field}`, released 7.1; it honours `--query-parameters '$expand=allowedValues'` (System.State on `Spec`: 6 allowed values). An unrestricted field answers `allowedValues: []`. | `WIT_ROUTES["type_fields"]` → `workItemTypesField`, verified; `DISCOVER_AZ_CONTRACT`; `ado_sync._per_type_reads` reads the new command label (and still the old one from a schema saved before). `map_type_fields` already read `[]` as unrestricted. |
| 3 | `connectionData` is not reachable through `az devops invoke`: area `core` answers "--resource and --api-version combination is not correct", area `Location` "--area is not present in current organization" (although the full locations list does name a `Location`/`ConnectionData` location, `_apis/{resource}`, released 0.0). It is reachable as `az rest --method get --resource 499b84ac-1321-427f-aa17-267ca6975798 --url https://dev.azure.com/<org>/_apis/connectionData?api-version=7.1-preview -o json`; `api-version=7.1` is refused ("The requested version \"7.1\" of the resource is under preview"). The answer: `authenticatedUser` and `authorizedUser` `{id, descriptor, subjectDescriptor, providerDisplayName, customDisplayName, isActive, properties.Account.$value, resourceVersion, metaTypeId}`, `instanceId`, `deploymentId`, `deploymentType: hosted`, `locationServiceData`; unlike a `devops invoke` answer it has no `continuation_token`. | `ado_wit.connection_data` → `ado_transport.rest_get` of `boards_contract.REST_ROUTES["connection_data"]`. `rest_get` is the only `az rest` the plugin sends: a GET, of a path in `REST_READS` only, under the parsed remote's organisation URL, at `7.1-preview`. The `WIT_ROUTES["connection_data"]` row stays, never verified, as the name the read is known by. When `az rest` holds no Entra token (a personal access token alone) the failure is re-worded `REST_NO_TOKEN`, which `host_report` reads as `unknown` (never `signed_out`), and every plan with a comment refuses as `identity_unknown` (exit 2, nothing sent). `BOARDS_AZ_CONTRACT` and the three identity entries of `golden/az_write_argv.json` changed; every other argv in that golden is byte-identical. |
| 4 | Verified by the capture: `projects` (`_apis/projects/{projectId}`), `type_categories` (`workItemTypeCategories`), `types` (`workItemTypes`; each type carries `states`, `fields`, `fieldInstances`, `transitions`), `fields` (project-wide), `backlog_config` (`work/backlogconfiguration`, `{team}` in the route), `classification_nodes` (`$depth=3`), `team_iterations` (`work/teamsettings/iterations`, `{team}` in the route), `relation_types` (organisation level, `_apis/wit/workItemRelationTypes`: the `project` it is sent is not used), `workitemrevisions` (`{project}/_apis/wit/reporting/workItemRevisions`, released 7.1, from the locations list). Also confirmed from the locations list, not called: `comments` is preview only (released 0.0, min 5.1, max 7.2, so `7.1-preview` is right; `commentsVersions` likewise), `wiql` is `{project}/{team}/_apis/wit/wiql` (team optional), a `workItems` create binds `{project}/_apis/wit/workItems/${type}`, `updates` is `{project}/_apis/wit/workItems/{id}/updates/{updateNumber}`, `workItemsBatch` is `{project}/_apis/wit/workItemsBatch`, released 7.1. | Those nine rows plus the two corrected ones are `verified: True`; nothing else. `test_boards_contract.py` checks every `devops invoke` row against `invoke_locations.json` (a location exists, a GA row is released 7.1, a preview row is released 0.0 yet serves 7.1, every route parameter it sends is in the template). |
| 5 | The locations listing (`az devops invoke` with no `--area`/`--resource`) has 1005 locations in 97 areas; the wit/work/core subset is 106 (`invoke_locations.json`). For that call `az` printed a "Please wait…" line before the JSON on stdout. | Nothing: the plugin never issues the listing call; every read it does issue parsed cleanly in the same session. |

## Other facts about this process

* 17 work item types, including custom `Spec` and `RAID` types (reference names `Agile_<project>.Spec`,
  `.RAID`). User Story is `isDisabled: true` and in the Hidden category. The requirement category's default type
  is `Spec` (members Spec, User Story), while the team's requirement backlog (`Specs`) names User Story as its
  default type. `resolve_type` follows the category: the spec kind lands on `Spec`.
* `Spec` states: New (Proposed); In-Dev, In QA, Blocked (InProgress); Ready for Release (Resolved); Closed
  (Completed). On Epic, Feature and User Story the state named `Resolved` is in the **InProgress** category (the
  hand-written Agile fixture assumed Resolved), so a merged epic lands on Closed.
* `Spec` carries custom fields `Custom.RiskTier` (picklist High/Low/Medium), `Custom.Status` and
  `Custom.CheckingPlan` (picklists), `Custom.Scope`, `Custom.AcceptanceChecks`, `Custom.DelegationPlan`,
  `Custom.TouchesGatedPath` (boolean), `Custom.Owner`, `Custom.Goal`, `Custom.Why`, `Custom.Evaluations`,
  `Custom.Notesandopenquestions` — a Shepherd spec already modelled as a work item type. The starter config's risk
  mapping (High/Medium/Low) is this picklist's own spelling: `config check` refuses nothing.
* Per-type field counts: User Story 66, Issue 62, Epic 67, Feature 66, Spec 69; project-wide 106.
* Backlog: portfolio levels Epics (rank 4) and Features (3), nothing above Epic; requirement level Specs (2); task
  level Tasks (1) holding Task and Bug (`bugsBehavior: asTasks`); effort field `Microsoft.VSTS.Scheduling.StoryPoints`;
  `workItemTypeMappedStates` for six types.
* Areas are flat under the project root (four areas, one of them the board team's own). Eleven two-week
  iterations; the team has all eleven (6 past, 1 current, 4 future). `work/teamfieldvalues` names the team's own
  area, `includeChildren: false`.
* 21 relation types: 18 `workItemLink`, 3 `resourceLink`.
* Every `devops invoke` answer carries `continuation_token: null`; `-o json` sorts keys. Fields carry keys no
  mapper reads (`isPicklistSuggested`, `canSortBy`, `supportedOperations`, `picklistId`).

## The refusals, under `errors/`

| File | What | Source |
|---|---|---|
| `states_wrong_resource.txt` | `--resource states` with a `type` | the text the failed `discover` run recorded; the raw stderr file was overwritten by a later run |
| `connection_data_core.txt` | `--area core --resource connectionData` | the text the run reported; the raw stderr file was overwritten by a later run |
| `connection_data_location.txt` | `--area Location --resource connectionData` | verbatim stderr |
| `connection_data_rest_7.1.txt` | `az rest … ?api-version=7.1` | verbatim stderr |

## Still unverified

`uv run --project scripts pytest scripts/tests/test_wit_fixture_provenance.py -q -s` after this capture:

```
[boards] 17 work-item fixture(s) have NO capture and are hand-written: account_show, comment_add_response, comment_versions, comments, comments_hostile, comments_page2, comments_recent, connection_data_sp, updates, updates_after_comment, wiql_by_tag, wiql_untagged, workitem_create_response, workitem_show_relations, workitem_update_response, workitemrevisions, workitems_batch
[boards] 9 synthetic process fixture(s) (hand-written by design): basic_categories, basic_types, cmmi_categories, cmmi_types, scrum_categories, scrum_types, two_level_backlog_config, two_level_categories, two_level_types
```

`WIT_ROUTES` rows still `verified: False`: `workitem_create`, `workitem_update`, `workitemsbatch`, `updates`,
`comments`, `comment_versions` (listed in the locations, never called) and `connection_data` (not an invoke
location). The plan/apply/drift scenario tests read the hand-written process their hand-written item fixtures
belong to (`BOARDS_PROCESS` in `tests/ado_boards_fixtures.py`) until items are captured from one board.

## What the next capture session must still do (kit §10 H1, items 11–30)

1. **Items (11–16)**, on a populated scratch board with an item tagged `sdlc:spec:0004`: `wiql_by_tag` (`az boards
   query`), `workitem_show_relations` (an item with a pull request link and an attachment), `workitems_batch`
   (`POST wit/workItemsBatch`, `errorPolicy: omit`, one deleted id), `updates`.
2. **Write probes (17–24)** on a scratch item, every stderr verbatim under `errors/`: the create (which `workItems`
   location a POST binds — go/no-go #1 for `invoke_body`), the update guarded by `test /rev`, a stale rev
   (`stale_rev.txt`), a required-field violation (`rule_violation.txt`), a read-only account (`permission.txt`,
   needs the second account), a `-preview.N` api-version (`preview_rev.txt`), `az repos pr work-item add`.
3. **Discussion (25–30)**, the second account posting: comments and the body's continuation token (page 2), a
   comment POST (does the answer carry `rev`; `id` or `commentId`), an edit and a soft delete (`comment_versions`,
   `updates_after_comment`; whether either bumps the item's `rev`), a UI @mention and `#123` (which id the mention
   stores: storage key or `originId`), the hostile round-trip. Commit only through `redact.py` and `redact_wit.py`.
4. **The identity read without Entra**: the stderr of the `az rest` identity read under a personal-access-token-only
   sign-in (the plugin's reading of "Please run 'az login' to setup account." is hand-written), and a service
   principal's `connectionData` through `az rest` (`connection_data_sp.json` is hand-written, in the old `devops
   invoke` form).
5. **The runbook itself**: §10 H1 of the build kit still shows the old commands for steps 4, 5 and 10 (`--resource
   states`, `--resource fields` with a `type`, `--area core --resource connectionData`). The working forms are
   `--resource workItemTypeStates` (or none: `workItemTypes` carries the states), `--resource workItemTypesField
   … --query-parameters '$expand=allowedValues'`, and the `az rest` call of fact 3.
