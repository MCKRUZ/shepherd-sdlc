"""The Azure Boards mirror's shared vocabulary: every enum, regex, path and REST location (B1-P0).

Pure data. It imports `re` and `typing` only, so any module — the pure maps, the impure seams,
the tests, the CLI — can import it without pulling in I/O. A later package that needs a new kind,
event or path adds it HERE rather than spelling a literal of its own, and a name is never renamed
once it has been written to a ledger.

`WIT_ROUTES` is the single point the B0 capture corrects: every `devops invoke` location (area,
resource, route-parameter names, method, api-version) was written from the REST reference and is
`verified: False` until a person runs the capture, reads `invoke_locations.json` and flips it.
`api_version` is the transport's `API_VERSION` ("7.1") or `PREVIEW_API_VERSION` ("7.1-preview")
and nothing else — a preview pinned to a revision number is refused at the seam.

The first capture (2026-10-14, `wit/captured/CAPTURE-NOTES.md` under the test fixtures) verified the
discovery rows and the reporting feed, and corrected three: the per-type states live at
`workItemTypeStates` (`--resource states` does not resolve), the per-type fields at `workItemTypesField`
(`--resource fields` with a `type` silently answers the project-wide list), and `connectionData` is not
an `az devops invoke` location at all — `REST_ROUTES` holds it, read with `az rest`.

The second capture (2026-10-15, the first live `apply`) reached the item rows: `workitem_create` binds
`{project}/_apis/wit/workItems/${type}` (so the type goes bare), and `workitemsbatch`, `updates` and `comments` (POST
and GET) answered in the forms below. `workitem_update` is verified as the location an update writes to, but NOT
through `az devops invoke`: `workItems` has two locations (`…/workItems/${type}` and `…/workItems/{id}`), the
extension binds the first for a PATCH and dies (`ERROR: 'type'`), so an update is `az rest --method patch` of
`REST_ROUTES["workitem_update"]`. `comment_versions` and the `connection_data` invoke row stay unverified.

`OWNERSHIP` says who is the source of truth for a work-item field once the item exists:
  * `S` — the repository (SDLC) owns it: the mirror writes it, and a board edit is drift.
  * `A` — Azure DevOps owns it: the mirror never overwrites it, a change is observed.
  * `C` — written once at create, then the board's (moving an item is the board's call).
A process-specific field (a custom risk-tier picklist, say) is named in `.sdlc/ado.yaml`, never here.

The regexes are anchored; match a whole value with `.fullmatch()` (`$` also matches before a
trailing newline). `EMAIL_RE` and `GUID_RE` are unanchored on purpose: they search free text for an
identity that must not be written.
"""

import re
from typing import Final

KINDS: Final = ("outcome", "domain", "epic", "feature", "spec", "spike", "sprint", "decision", "finding",
                "lifecycle", "requirement", "rule", "question", "measurement",
                "nfr")  # B5-P0: an NFR is a leaf under its Domain (opt-in), so TREE_ORDER does not name it
# apply's create order, so every link target exists before the item that points at it
TREE_ORDER: Final = ("outcome", "domain", "requirement", "epic", "feature", "spec")
FIT_MODES: Final = ("item", "area", "tag")
FULFILS_REL: Final = "System.LinkTypes.Related"  # epic -> FR links; outcome <-> domain too (tree.outcome_edge)
TRAILER_TOKEN: Final = "sprd"  # board-visible prose: the comment trailer `· sprd <12hex>`
HISTORY_TOKEN: Final = "sprd"  # board-visible prose: the create-time History line; tags stay "sdlc:"

DRIFT_CLASSES: Final = ("IN_SYNC", "ADO_OWNED_CHANGE", "SDLC_OWNED_DRIFT", "CONFLICT", "DELETED_IN_ADO",
                        "ORPHAN_IN_REPO", "RETYPED", "MOVED", "RELATION_DRIFT", "UNMAPPED_IN_ADO", "NEVER_PUSHED",
                        "COMMENT")
LEDGER_EVENTS: Final = ("discovered", "posture", "planned", "applied", "adopted", "linked", "conflict", "refused",
                        "observed", "drift_seen", "reconciled", "iteration_bound", "commented", "comment_refused",
                        "discussion_pulled", "comment_seen", "directive_seen", "discussion_gc")
COMMENT_REFUSALS: Final = ("ai_actor", "identity_mismatch", "identity_unknown", "budget", "max_chars",
                           "email_in_text", "event_unknown", "needs_disposition", "posture")

OWNERSHIP: Final[dict[str, str]] = {
    "System.Title": "S",
    "System.Description": "S",
    "System.State": "S",
    "System.Tags": "S",  # the plugin-prefixed tags only (PLUGIN_TAG_PREFIXES); any other tag is left alone
    "Microsoft.VSTS.Common.AcceptanceCriteria": "S",
    "System.AssignedTo": "A",
    "System.IterationPath": "A",
    "Microsoft.VSTS.Common.Priority": "A",
    "Microsoft.VSTS.Common.StackRank": "A",
    "System.AreaPath": "C",
}
# A requirements-tree kind the process cannot hold as a work item rides on the items that point at it, as a tag of its
# own family (`ado_schema_map.TAG_FORM`): an epic under the `order-intake` domain carries `domain:order-intake`, one
# that fulfils FR-001 carries `fr:001`, and the outcomes that domain maps to ride as `outcome:<id>`. They are the
# repository's tags like every `sdlc:` one, so they close PLUGIN_TAG_PREFIXES: a board-side removal is drift.
RIDE_TAG_PREFIXES: Final[dict[str, str]] = {"outcome": "outcome:", "domain": "domain:", "requirement": "fr:"}
PLUGIN_TAG_PREFIXES: Final = ("sdlc:", "sdlc-repo:", "risk:", "channel:", "type:", "severity:", "eng-review:",
                              "data-review:", "carried-from:", *RIDE_TAG_PREFIXES.values())
# The kinds a config with no `kinds:` key mirrors: the starter's list (templates/ado/ado.yaml; a test keeps them equal).
DEFAULT_KINDS: Final = ("outcome", "domain", "requirement", "epic", "feature", "spec", "spike", "sprint", "decision")

# Where a page's continuation token rides, in the order it is read: the response body's own `continuationToken`, then
# the `continuation_token` key the azure-devops extension adds to every `devops invoke` answer (from the response
# header). The comments GET was captured answering only the second, as `null` on a last page (B0, 2026-10-15).
PAGE_TOKEN_KEYS: Final = ("continuationToken", "continuation_token")

WRITE_METHODS: Final = frozenset({"POST", "PATCH", "PUT", "DELETE"})
READ_POSTS: Final = frozenset({("wit", "wiql"), ("wit", "workitemsbatch")})  # POSTs that only read

HANDLE_RE: Final = re.compile(r"^@[A-Za-z0-9][A-Za-z0-9-]*$")
EMAIL_RE: Final = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
GUID_RE: Final = re.compile(r"\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b")
HASH_RE: Final = re.compile(r"^[0-9a-f]{12}$")
REF_RE: Final = re.compile(r"^sdlc:[a-z]+:[A-Za-z0-9-]+$")

CONFIG_FILE: Final = ".sdlc/ado.yaml"
SCHEMA_FILE: Final = ".sdlc/ado/schema.json"
LOCAL_DIR: Final = ".sdlc/ado/local"
HOOK_STATUS: Final = ".sdlc/ado/local/hook-status.txt"
LEDGER: Final = ".sdlc/metrics/ado-sync-log.jsonl"
DISCUSSION_DIR: Final = ".sdlc/ado/local/discussion"
ME_FILE: Final = ".sdlc/ado/local/me.json"

# A literal, not an import of audit_artifacts (a CLI); test_boards_contract.py keeps the two equal.
DISCIPLINE_AGENTS: Final = frozenset({"requirements-analyst", "feature-architect", "bizreq-analyst",
                                      "visual-designer", "conversation-designer", "data-analyst"})

_GA = "7.1"            # == ado_transport.API_VERSION (pinned by test)
_PREVIEW = "7.1-preview"  # == ado_transport.PREVIEW_API_VERSION (pinned by test)


def _route(area: str, resource: str, route: tuple[str, ...], method: str = "GET", api_version: str = _GA, *,
           verified: bool = False) -> dict:
    return {"area": area, "resource": resource, "route": route, "method": method, "api_version": api_version,
            "verified": verified}


_CAPTURED = True  # read in the B0 capture of 2026-10-14 (or listed, released, in its `invoke_locations.json`)

# name -> {"area", "resource", "route": tuple[str, ...], "method", "api_version", "verified": bool}
WIT_ROUTES: Final[dict[str, dict]] = {
    # discovery (serial GETs; the project is a route parameter, never --project)
    "projects": _route("core", "projects", ("projectId",), verified=_CAPTURED),  # _apis/projects/{projectId}
    "type_categories": _route("wit", "workItemTypeCategories", ("project",), verified=_CAPTURED),
    # each type also carries its `states`, `fields`, `fieldInstances` and `transitions` (captured)
    "types": _route("wit", "workItemTypes", ("project",), verified=_CAPTURED),
    # {project}/_apis/wit/workitemtypes/{type}/states; `--resource states` does not resolve (captured)
    "type_states": _route("wit", "workItemTypeStates", ("project", "type"), verified=_CAPTURED),
    # {project}/_apis/wit/workitemtypes/{type}/fields/{field}, with --query-parameters $expand=allowedValues;
    # `--resource fields` ignores a `type` and answers the project-wide list (captured)
    "type_fields": _route("wit", "workItemTypesField", ("project", "type"), verified=_CAPTURED),
    "fields": _route("wit", "fields", ("project",), verified=_CAPTURED),
    "backlog_config": _route("work", "backlogconfiguration", ("project", "team"), verified=_CAPTURED),
    "classification_nodes": _route("wit", "classificationNodes", ("project",), verified=_CAPTURED),  # with $depth=3
    "team_iterations": _route("work", "iterations", ("project", "team"), verified=_CAPTURED),  # work/teamsettings/
    # an organisation-level location (_apis/wit/workItemRelationTypes): the `project` it is sent is not used
    "relation_types": _route("wit", "workItemRelationTypes", ("project",), verified=_CAPTURED),
    # items
    "workitem_create": _route("wit", "workItems", ("project", "type"), "POST", verified=True),  # type=<Type>, bare: the template is `…/workItems/${type}` (B0 2026-10-14)
    # {project}/_apis/wit/workItems/{id}: SENT AS `az rest` (REST_ROUTES["workitem_update"]), never `devops invoke`,
    # which binds the `${type}` location for a PATCH and dies with `ERROR: 'type'` (B0 2026-10-15)
    "workitem_update": _route("wit", "workItems", ("project", "id"), "PATCH", verified=True),
    # a read (READ_POSTS); `errorPolicy: omit` answers a missing id as a `null` entry, counted in `count` (B0 2026-10-15)
    "workitemsbatch": _route("wit", "workitemsbatch", ("project",), "POST", verified=True),
    "updates": _route("wit", "updates", ("project", "id"), verified=True),
    # discussion: POST (format=markdown) and GET (order=asc) both reached (B0 2026-10-15); the extension adds its own
    # `continuation_token` key to the answer beside (or instead of) the body's `continuationToken`
    "comments": _route("wit", "comments", ("project", "workItemId"), api_version=_PREVIEW, verified=True),
    "comment_versions": _route("wit", "commentsVersions", ("project", "workItemId", "commentId"), api_version=_PREVIEW),
    # identity: NOT an `az devops invoke` location (captured: area `core` "--resource and --api-version combination
    # is not correct", area `Location` "--area is not present in current organization"). The row stays, never
    # verified, as the name the identity read is known by; `ado_wit.connection_data` reads REST_ROUTES below.
    "connection_data": _route("core", "connectionData", (), api_version=_PREVIEW),
    # reporting (B5-P0): {project}/_apis/wit/reporting/workItemRevisions, the watermark feed B5-P2 pages through
    "workitemrevisions": _route("wit", "workItemRevisions", ("project",), verified=_CAPTURED),
}

# The calls `az devops invoke` cannot make (B0 capture, 2026-10-14 and 2026-10-15). Each is `az rest --method <m>
# --resource ADO_RESOURCE_ID --url <organisation URL>/<path>?api-version=<api_version>`: az mints an Entra token for
# Azure DevOps itself, so a sign-in that holds only a personal access token cannot make the call. `ado_transport`
# keeps its own allow-lists of these paths (`REST_READS` for the GET, `REST_WRITES` for the PATCH; a test pins both
# to this table) and sends nothing else through `az rest`. A `{name}` in a path is filled by the transport from a
# checked value (the project percent-encoded, the id a positive integer), never from free text.
ADO_RESOURCE_ID: Final = "499b84ac-1321-427f-aa17-267ca6975798"  # Azure DevOps' fixed Entra resource id (vocabulary)
REST_ROUTES: Final[dict[str, dict]] = {
    # `7.1` is refused: "The requested version \"7.1\" of the resource is under preview" (captured)
    "connection_data": {"path": "_apis/connectionData", "method": "GET", "api_version": _PREVIEW, "verified": True},
    # an update: `--headers Content-Type=application/json-patch+json --body @<file>`. A stale `test /rev` answers
    # `Precondition Failed … VS403351`, a value outside a picklist `Bad Request … RuleValidationErrors` (captured)
    "workitem_update": {"path": "{project}/_apis/wit/workitems/{id}", "method": "PATCH", "api_version": _GA,
                        "verified": True},
}
