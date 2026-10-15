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
   `updates_after_comment`; whether either bumps the item's `rev`), a UI mention and `#123` (which id the mention
   stores: storage key or `originId`), the hostile round-trip. Commit only through `redact.py` and `redact_wit.py`.
4. **The identity read without Entra**: the stderr of the `az rest` identity read under a personal-access-token-only
   sign-in (the plugin's reading of "Please run 'az login' to setup account." is hand-written), and a service
   principal's `connectionData` through `az rest` (`connection_data_sp.json` is hand-written, in the old `devops
   invoke` form).
5. **The runbook itself**: §10 H1 of the build kit still shows the old commands for steps 4, 5 and 10 (`--resource
   states`, `--resource fields` with a `type`, `--area core --resource connectionData`). The working forms are
   `--resource workItemTypeStates` (or none: `workItemTypes` carries the states), `--resource workItemTypesField
   … --query-parameters '$expand=allowedValues'`, and the `az rest` call of fact 3.

---

# Second capture — the first live `apply` and its probes (2026-10-15)

| | |
|---|---|
| Date | 2026-10-15 |
| Tooling | Azure CLI 2.87.0, azure-devops extension 1.0.8, macOS |
| Sign-in | Entra, the person's own `az login` in the organisation's tenant. No personal access token was used. |
| Scope | the mirror's own `apply` of a confirmed plan (3 Epics and 1 Feature created), then kit §10 H1 steps 11–26 on those items and on one scratch Task: reads, an update and its refusals, a create probe, two comment calls. Every write was sent as that person, after the plan hash was confirmed by name. |

## How the files were made

As the first capture, wrapped `{"_provenance": "captured 2026-10-15 (org anonymised)", "_command": [...], "value":
...}`, with `_body` where the call sent one (the request body, anonymised the same way) and `_note` where `_command`
is reconstructed. Redaction: `redact.py --org <org> --project <project> --team <team> --rename … --mask-free-text`
with the first capture's names, then `redact_wit.py` over every `value` (History text, comment text, the identity
blocks beside a `uniqueName`), then by hand:

* work item ids, comment ids, link ids and `System.PersonId` are renumbered **per file**, by kind, in order of first
  appearance (`1`, `2`, …), in `_command` and `_body` too; the deliberately missing id of the batch read
  (`999999999`) is kept. A fake id is an anchor within one file only.
* the display name inside `revisedBy.name` (`<name> <address>`) becomes `Participant 1`; the account id inside an
  identity URL (`…/A<GUID>/_apis/Identities/…`, which the GUID pattern cannot see) and the 32-hex Kanban extension id
  in a `WEF_<id>_Kanban.Column` key are anonymised; the identity service's regional host becomes
  `app.vssps.visualstudio.com`.
* `errors/identity_unknown.txt`: az printed the unknown address masked (the first and last character of each part
  kept); it was a fixture's example.com address and is written as the stand-in `person1@example.com`.
  `errors/invoke_patch_keyerror.txt` keeps the first three lines; the traceback below them names the capturing
  machine's paths.

The one GUID not anonymised is still Azure DevOps' fixed resource id, in the `az rest` `_command` only.

## The files

| File | What | Notes |
|---|---|---|
| `wiql_by_tag.json` | `az boards query` by one tag, the literal project form | `_note`: the run kept the answer, not the exact WIQL; the select list is the fields the answer carries (`System.Id`, `System.State`) |
| `wiql_repo_tag.json` | the same query for `sdlc-repo:<repo>`: the four items the apply created | reference only (no route answers with it); `_note` as above |
| `workitem_show_relations.json` | `az boards work-item show --expand relations` of the Feature | a `System.LinkTypes.Hierarchy-Reverse` parent and the source-file `Hyperlink`; created before the area fix, so `System.AreaPath` is the project root |
| `workitems_batch.json` | `POST wit/workitemsbatch`, two ids and a missing one, `errorPolicy: omit` | `count: 3`, the third entry `null` |
| `updates.json` | `GET wit/updates` of an Epic | two updates, both `rev: 1` — the second has no `fields`, only `relations.added` (the child linked from its own side) |
| `workitem_create_response.json` | the create probe (`type=Task`, bare) | the title `sdlc probe & "quote" ✓` round-trips; the probe set the team's area, and that is where it landed |
| `workitem_create_response_spec.json` | a hand-built `Spec` create: Custom.RiskTier, State, the sprint's IterationPath, a parent | reference only; `Custom.CheckingPlan` and `Custom.TouchesGatedPath` came back filled by the process's defaults |
| `workitem_update_response.json` | the update through `az rest --method patch` | `test /rev 1` → `rev: 2`; unlike every `devops invoke` answer it has no `continuation_token` key |
| `comment_add_response.json` | `POST wit/comments`, `format=markdown`, at `7.1-preview` | `id`, `version: 1`, `format`, `text`, `renderedText` (HTML), `createdBy`, `workItemId`, and the extension's `continuation_token: null` |
| `comments.json` | `GET wit/comments`, `order=asc $top=2 includeDeleted=true` | `{comments, count, totalCount, continuation_token}`; each comment has `mentions`; **no `isDeleted` key** on a live comment; `renderedText` came back empty on the GET |
| `errors/stale_rev.txt` | the same `test /rev 1` PATCH sent again through `az rest` | `Precondition Failed(… VS403351 … TestPatchOperationFailedException …)` |
| `errors/rule_violation.txt` | an `az rest` PATCH of `System.State` to a value the type does not have | `Bad Request(… RuleValidationErrors … is not in the list of supported values … RuleValidationException …)` |
| `errors/identity_unknown.txt` | a create carrying `System.AssignedTo` for an address the organisation does not know | `The identity value '…' for field 'Assigned To' is an unknown identity.` |
| `errors/invoke_patch_keyerror.txt` | `devops invoke --resource workItems --http-method PATCH` | `ERROR: 'type'`: the extension failing inside itself |
| `errors/create_dollar_type.txt` | the create POST with `type=$Task` | `…/workItems/$$Task was not found …` (404) |
| `errors/preview_rev.txt` | `devops invoke` with `7.1-preview` pinned to revision 4 | `could not convert string to float: '7.1.4'`, as the design predicted |

Not landed: the zero-byte answers of the two by-tag queries in the current-project macro form (an empty file holds
nothing to redact; fact 3 below records them).

## The facts, and what each changed in code

| # | Fact | In code |
|---|---|---|
| 1 | `az devops invoke --area wit --resource workItems --route-parameters project=P id=N --http-method PATCH` dies inside the extension with `ERROR: 'type'` (a KeyError): `workItems` has two locations, `{project}/_apis/wit/workItems/${type}` and `…/workItems/{id}`, and it binds the first. `az rest --method patch --resource 499b84ac-… --url https://dev.azure.com/<org>/<project>/_apis/wit/workitems/<id>?api-version=7.1 --headers Content-Type=application/json-patch+json --body` plus the at-sign and the body file works: a stale `test /rev` answers `Precondition Failed … VS403351`, a picklist violation `Bad Request … RuleValidationErrors`. | `ado_transport.rest_patch` / `rest_write_argv` (allow-list `REST_WRITES`, the GA version, a percent-encoded project, a positive id, the body in a 0600 temp file, scrubbed and removed); `ado_wit.update` sends through it; `boards_contract.REST_ROUTES["workitem_update"]`; `classify_write_error` reads the two texts as `conflict` and `rule`. A personal access token alone cannot mint the token: `REST_NO_TOKEN_WRITE`, and `apply` refuses a plan that would PATCH as `identity_unknown` (exit 2, nothing sent) after reading `connectionData` first. The write golden: the two PATCH argv changed. |
| 2 | A create whose `System.AssignedTo` is an address the organisation does not know is refused `… is an unknown identity.`; the classifier read it `unknown`, a stop class, so the five rows after it were deferred as stopped. | `classify_write_error` reads it (and `RuleValidationErrors`) as `rule`: that row fails, the run goes on. `describe_write_error` names the patch field it was about (`System.AssignedTo`, `reason: unknown_identity`; `System.State`, `value_not_allowed`), and the failed row carries `field`, `reason` and a fixed sentence — never the board's words. The schema holds no identity by design, so the plan cannot warn ahead of the board. |
| 3 | `az boards query --project P --wiql "… WHERE [System.TeamProject] = ` + the current-project macro + ` AND [System.Tags] CONTAINS 'x'"` exits 0 and prints **zero bytes** although items match; the same query with the literal project name, or with the clause dropped (`--project` alone), returns the rows. | Every tag query (`ado_wit.find_by_ref`, `ado_wit_map.wiql_ref_lookup` / `wiql_untagged`, `ado_sync._by_tag_wiql`) names the remote's project as a whitelisted, quote-doubled literal (`ado_wit_map.project_clause`). Zero bytes stays no rows (`ado_transport.az_json_read`, `ado_wit.QueryIds.printed_nothing`) and `drift` says so in a note. The scorecard import's incident query (`ado_outcomes_map.INCIDENT_WIQL`) still uses the macro: not part of this fix. |
| 4 | `area_path` was never written: the four created items landed at the project root, outside the team's board filter (moved by hand afterwards). | `ado_wit_map.with_create_fields` / `build_create_patch(area_path=)` add `System.AreaPath` to every create when the config names an area; `plan` shows the op. An update never sends it; a board-side move stays `C` (`ADO_OWNED_CHANGE`). The write golden: the two creates gained the op. |
| 5 | Comments through `devops invoke` work in the plugin's form, POST and GET. The page token rides as `continuation_token` (the extension's spelling), not only as the body's `continuationToken`. A live comment carries no `isDeleted` key. | `boards_contract.PAGE_TOKEN_KEYS` (body first, then the extension's key) in `ado_wit.comments`, `ado_discussion_map.map_comment_list` and `ado_wit_feed`; `map_comment` reads an absent `isDeleted` as not deleted (requiring it made every real comment unreadable). |
| 6 | Posting a comment bumps the item's `rev` (2 → 3, `System.CommentCount` 1); the comment's answer does not carry the new `rev`. | `apply` marks an item it commented on and re-reads its `rev` before it PATCHes it again in the same run (`_Run.reread_rev`); a plan read before someone's comment is stale after it (`rev_moved`: plan again). |
| 7 | A child created with a `Hierarchy-Reverse` parent adds a revision to the PARENT's history that has no `fields`, only `relations.added`, and keeps the parent's `rev` (both updates read `rev: 1`). | Nothing yet: `classify_drift` skips a revision at or below the ledgered `rev_after`, so a relation-only change that does not move `rev` is not seen as drift. Recorded for a later package. |
| 8 | `workitemsbatch` with `errorPolicy: omit` answers a missing id as a `null` entry, counted in `count`. A create with `type=$Task` reaches the board as `$$Task` (404). A preview api-version pinned to a revision fails inside the extension. | Already handled: `get_batch` reports the id as missing; `create` sends the bare type (`acc04e6`); `check_api_version` refuses a revision before any call. |

Verified by this capture (`boards_contract.WIT_ROUTES`): `workitemsbatch`, `updates`, `comments` (POST and GET) and
`workitem_update` (the location; sent as `az rest`), with `REST_ROUTES["workitem_update"]`. Still `verified: False`:
`comment_versions` (not called) and the `connection_data` invoke row (no invoke location).

## Still not captured

`uv run --project scripts pytest scripts/tests/test_wit_fixture_provenance.py -q -s` after this capture:

```
[boards] 9 work-item fixture(s) have NO capture and are hand-written: account_show, comment_versions, comments_hostile, comments_page2, comments_recent, connection_data_sp, updates_after_comment, wiql_untagged, workitemrevisions
```

The next session: a second page of comments (does the body carry `continuationToken` when there is more), an edit
and a soft delete (`comment_versions`, `updates_after_comment`), the recovery re-list (`order=desc`), a read-only
account's refusal (`permission.txt`), a throttle, `az repos pr work-item add`, a service principal's
`connectionData`, the `az rest` refusal under a personal-access-token-only sign-in (the plugin's reading of
"Please run 'az login' to setup account." is still hand-written), the untagged query (`NOT … CONTAINS
'sdlc-repo:…'` under the area and iteration paths), and a page of the reporting revisions feed.
