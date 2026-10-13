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
PLUGIN_TAG_PREFIXES: Final = ("sdlc:", "sdlc-repo:", "risk:", "channel:", "type:", "severity:", "eng-review:",
                              "data-review:", "carried-from:")

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


def _route(area: str, resource: str, route: tuple[str, ...], method: str = "GET", api_version: str = _GA) -> dict:
    return {"area": area, "resource": resource, "route": route, "method": method, "api_version": api_version,
            "verified": False}


# name -> {"area", "resource", "route": tuple[str, ...], "method", "api_version", "verified": bool}
WIT_ROUTES: Final[dict[str, dict]] = {
    # discovery (serial GETs; the project is a route parameter, never --project)
    "projects": _route("core", "projects", ("projectId",)),
    "type_categories": _route("wit", "workItemTypeCategories", ("project",)),
    "types": _route("wit", "workItemTypes", ("project",)),
    "type_states": _route("wit", "states", ("project", "type")),
    "type_fields": _route("wit", "fields", ("project", "type")),  # with --query-parameters $expand=allowedValues
    "fields": _route("wit", "fields", ("project",)),
    "backlog_config": _route("work", "backlogconfiguration", ("project", "team")),
    "classification_nodes": _route("wit", "classificationNodes", ("project",)),  # with $depth=3
    "team_iterations": _route("work", "iterations", ("project", "team")),
    "relation_types": _route("wit", "workItemRelationTypes", ("project",)),
    # items
    "workitem_create": _route("wit", "workItems", ("project", "type"), "POST"),  # type=$<Type>
    "workitem_update": _route("wit", "workItems", ("project", "id"), "PATCH"),
    "workitemsbatch": _route("wit", "workitemsbatch", ("project",), "POST"),  # a read (READ_POSTS)
    "updates": _route("wit", "updates", ("project", "id")),
    # discussion
    "comments": _route("wit", "comments", ("project", "workItemId"), api_version=_PREVIEW),
    "comment_versions": _route("wit", "commentsVersions", ("project", "workItemId", "commentId"), api_version=_PREVIEW),
    # identity
    "connection_data": _route("core", "connectionData", (), api_version=_PREVIEW),
    # reporting (B5-P0): {project}/_apis/wit/reporting/workItemRevisions, the watermark feed B5-P2 pages through
    "workitemrevisions": _route("wit", "workItemRevisions", ("project",)),
}
