"""The IMPURE half of Boards work-item reads: ask Azure DevOps about items, their history and their discussion (B2-P2).

`ado_wit_map.py` turns what comes back into plain dicts (pure, tested on fixtures); this module only asks.
It is read-only in Fold B2 — the six write functions at the bottom raise `NotImplementedError("B3")` until
the write Fold fills their bodies — and it writes nothing to the repository: no file, no ledger, no cache.

  find_by_ref(repo, ref)               ids of the items tagged `sdlc:<kind>:<id>` (a WIQL by tag)
  query_ids(repo, wiql)                `az boards query --wiql`; the ids of whatever it returns
  get_batch(repo, ids)                 (rows, missing): `workitemsbatch`, 200 ids per POST, `errorPolicy=omit`
  get_item(repo, wid)                  one item with its relations, by the native `az boards work-item show`
  updates_since(repo, wid, rev)        the revisions newer than `rev`, oldest first
  comments(repo, wid)                  the discussion, oldest first, paged on the response body's token
  comment_versions(repo, wid, cid)     the edit history of one comment
  connection_data(repo)                who the signed-in identity is (`authenticatedUser`)
  BOARDS_AZ_CONTRACT                   every argv prefix the reads issue, for `test_boards_az_contract.py`

How it asks. A `devops invoke` read goes through `ado_transport.invoke_body`, and its location (area,
resource, route-parameter names, method, api-version) comes from `boards_contract.WIT_ROUTES` — the one
place the live capture corrects, so a corrected row is followed with no change here. Two reads have a native
verb and use `ado_transport.az_json` with the scope `ado_transport.scope(with_repository=False)` supplies
(`--detect false --org --project`; a work item is not in a repository, and `az boards work-item show`
takes the organisation only). Every argv therefore carries `--detect false` and ends `-o json`; the seam
adds `--only-show-errors`; the only preview api-version is `PREVIEW_API_VERSION`, which the discussion
and identity routes use. The module imports no subprocess: `az` is spawned only inside the transport seam.

What it returns. Rows as Azure DevOps sent them: a revision's `revisedBy`, a comment's `createdBy` and an
item's `AssignedTo` name people, and comment text is whatever its author typed. Nothing here redacts,
strips or quotes — that is the discussion map's job — so a caller must not write what it gets here to a
committed file or a ledger. A response is read only through `_require`: a shape this module does not know is
an `AdoImportError` naming it, never a default. An error from `az` is passed on worded `<area>/<resource>
(work item N): <why>`, so the person reading it knows which call to look at.

Two honest limits. `comments` stops after `MAX_COMMENT_PAGES` pages (1,000 comments) and its result says so
(`.truncated`, plus the board's own `.total_count` when it sent one); `updates_since` reads from the
first revision, pages by `$top`/`$skip`, and raises rather than return a history it could not finish,
because the newest revisions come last and a silent cut would drop exactly the ones it was asked for.

Standalone or workflow: it takes a repository root (`--repo`, or the parent of `.sdlc/state.yaml`) only to
read the Azure DevOps remote from it, and never reads `state.yaml`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ado_transport  # noqa: E402
from ado_map import AdoImportError, _require  # noqa: E402
from boards_contract import REF_RE, WIT_ROUTES  # noqa: E402

BATCH_SIZE = 200          # ids per `workitemsbatch` POST: the REST limit
PAGE_SIZE = 200           # `$top` for the updates and comments reads
MAX_COMMENT_PAGES = 5     # 1,000 comments; `comments` says when it stopped here
MAX_UPDATE_PAGES = 50     # 10,000 revisions, the most Azure DevOps keeps for one item

_BODY_MEDIA_TYPE = "application/json"  # the batch read's request body (a JSON object, not a JSON Patch)
_QUERY_COLUMNS = ("[System.Id],[System.WorkItemType],[System.Title],[System.State],[System.Tags],"
                  "[System.AssignedTo]")

# Every argv prefix the reads issue, in the order of the list above (placeholders: P project, U organisation URL,
# Q a WIQL text, N a work item id, C a comment id, F the request body file, T a continuation token). Checked
# against `az ... --help` by test_boards_az_contract.py and against the argv the reads really emit by
# test_boards_wit_reads.py. Read-only, `--detect false`, no `--repository`, no preview revision.
BOARDS_AZ_CONTRACT: tuple[list[str], ...] = (
    ["boards", "query", "--detect", "false", "--org", "U", "--project", "P", "--wiql", "Q", "-o", "json"],
    ["boards", "work-item", "show", "--id", "N", "--expand", "relations", "--detect", "false", "--org", "U",
     "-o", "json"],
    ["devops", "invoke", "--area", "wit", "--resource", "workitemsbatch", "--route-parameters", "project=P",
     "--http-method", "POST", "--in-file", "F", "--media-type", "application/json", "--api-version", "7.1",
     "--detect", "false", "--org", "U", "-o", "json"],
    ["devops", "invoke", "--area", "wit", "--resource", "updates", "--route-parameters", "project=P", "id=N",
     "--http-method", "GET", "--query-parameters", "$top=200", "$skip=0", "--api-version", "7.1",
     "--detect", "false", "--org", "U", "-o", "json"],
    ["devops", "invoke", "--area", "wit", "--resource", "comments", "--route-parameters", "project=P",
     "workItemId=N", "--http-method", "GET", "--query-parameters", "order=asc", "$top=200", "includeDeleted=true",
     "--api-version", "7.1-preview", "--detect", "false", "--org", "U", "-o", "json"],
    ["devops", "invoke", "--area", "wit", "--resource", "comments", "--route-parameters", "project=P",
     "workItemId=N", "--http-method", "GET", "--query-parameters", "order=asc", "$top=200", "includeDeleted=true",
     "continuationToken=T", "--api-version", "7.1-preview", "--detect", "false", "--org", "U", "-o", "json"],
    ["devops", "invoke", "--area", "wit", "--resource", "commentsVersions", "--route-parameters", "project=P",
     "workItemId=N", "commentId=C", "--http-method", "GET", "--api-version", "7.1-preview", "--detect", "false",
     "--org", "U", "-o", "json"],
    ["devops", "invoke", "--area", "core", "--resource", "connectionData", "--route-parameters",
     "--http-method", "GET", "--api-version", "7.1-preview", "--detect", "false", "--org", "U", "-o", "json"],
)


# --- the seam ----------------------------------------------------------------------------------------------

def _call(repo_root, name: str, *, query: dict | None = None, body: dict | None = None, **params):
    """One `devops invoke` of the `WIT_ROUTES[name]` location, `body` (a JSON object) sent when given. `params`
    fills the row's route parameters: a name the row asks for and the caller did not supply is an error, never
    a guess. An error from `az` is re-worded `<area>/<resource> (work item N): <why>`."""
    row = WIT_ROUTES[name]
    label = f"{row['area']}/{row['resource']}"
    item = params.get("workItemId", params.get("id"))
    if item is not None:
        label += f" (work item {item})"
    for key in row["route"]:
        if key not in params:
            raise AdoImportError(f"{label}: route parameter {key!r} is not supplied "
                                 f"(boards_contract.WIT_ROUTES[{name!r}])")
    route = {key: params[key] for key in row["route"]}
    extra = {"media_type": _BODY_MEDIA_TYPE} if body is not None else {}
    try:
        return ado_transport.invoke_body(repo_root, row["area"], row["resource"], route, method=row["method"],
                                         body=body, query=query, api_version=row["api_version"], **extra)
    except AdoImportError as exc:
        raise AdoImportError(f"{label}: {exc}") from exc


def _project(repo_root) -> str:
    return ado_transport.remote(repo_root).project


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _positive(value, what: str) -> int:
    """`value` when it is a positive integer. These go into a route (`workItemId=<n>`), so anything else —
    a string with a slash in it, a bool, zero — is refused before a call is made."""
    if not _is_int(value) or value < 1:
        raise ValueError(f"{what} must be a positive integer, got {value!r}")
    return value


def _id_in(value, what: str) -> int:
    """An id read FROM a response: an integer or an `AdoImportError`."""
    if not _is_int(value):
        raise AdoImportError(f"unexpected az shape: {what} is not an integer ({value!r})")
    return value


def _list_in(doc, key: str, what: str) -> list:
    value = _require(doc, key, what)
    if not isinstance(value, list):
        raise AdoImportError(f"unexpected az shape: {what}.{key} is not a list")
    return value


# --- finding items -----------------------------------------------------------------------------------------

def find_by_ref(repo_root, ref: str) -> list[int]:
    """The ids of the work items tagged with `ref` (`sdlc:<kind>:<id>`), in the board's order; `[]` when none is.
    `ref` is checked against `boards_contract.REF_RE` first: it is placed inside a WIQL string literal."""
    if not isinstance(ref, str) or not REF_RE.fullmatch(ref):
        raise ValueError(f"not a ref of the form sdlc:<kind>:<id>: {ref!r}")
    wiql = (f"SELECT {_QUERY_COLUMNS} FROM WorkItems WHERE [System.TeamProject] = @project "
            f"AND [System.Tags] CONTAINS '{ref}'")
    return query_ids(repo_root, wiql)


def query_ids(repo_root, wiql: str) -> list[int]:
    """`az boards query --wiql <wiql>`: the `id` of each work item it returns, in order. An empty stdout (az prints
    nothing when no work item matches) is `[]`. The caller owns the WIQL; build it with `ado_wit_map`."""
    if not isinstance(wiql, str) or not wiql.strip():
        raise ValueError("wiql must be a non-empty string")
    try:
        rows = ado_transport.az_json(["boards", "query", *ado_transport.scope(repo_root, with_repository=False),
                                      "--wiql", wiql], repo_root)
    except AdoImportError as exc:
        raise AdoImportError(f"boards query: {exc}") from exc
    if not isinstance(rows, list):
        raise AdoImportError("unexpected az shape: `az boards query` did not print a list of work items")
    return [_id_in(_require(row, "id", "boards query row"), "boards query row.id") for row in rows]


def get_batch(repo_root, ids: list[int]) -> tuple[list[dict], list[int]]:
    """`(rows, missing)` for `ids`: one `POST wit/workitemsbatch` per 200 ids with `$expand=relations` and
    `errorPolicy=omit`, so an id the board no longer has comes back as `null` instead of failing the batch.
    `missing` is every requested id no row came back for (asked once each, in the order given) — a deleted item
    is a fact to report, so it is neither dropped nor an error. No ids, no call."""
    wanted = list(dict.fromkeys(_positive(i, "a work item id") for i in ids))
    if not wanted:
        return [], []
    rows: list[dict] = []
    missing: list[int] = []
    project = _project(repo_root)
    for start in range(0, len(wanted), BATCH_SIZE):
        chunk = wanted[start:start + BATCH_SIZE]
        # no `fields`: the API refuses it beside `$expand`, and the mirror wants the whole item anyway
        doc = _call(repo_root, "workitemsbatch",
                    body={"ids": chunk, "$expand": "relations", "errorPolicy": "omit"}, project=project)
        got = [row for row in _list_in(doc, "value", "workitemsbatch") if row is not None]
        returned = {_id_in(_require(row, "id", "workitemsbatch row"), "workitemsbatch row.id") for row in got}
        rows.extend(got)
        missing.extend(i for i in chunk if i not in returned)
    return rows, missing


def get_item(repo_root, wid: int) -> dict:
    """One work item with its relations, by the native `az boards work-item show --id N --expand relations`
    (an organisation-wide id: the verb takes `--org`, not `--project`). An answer with no `id` is an error."""
    wid = _positive(wid, "a work item id")
    try:
        doc = ado_transport.az_json(["boards", "work-item", "show", "--id", str(wid), "--expand", "relations",
                                     "--detect", "false", "--org", ado_transport.remote(repo_root).org_url], repo_root)
    except AdoImportError as exc:
        raise AdoImportError(f"boards work-item show (work item {wid}): {exc}") from exc
    _id_in(_require(doc, "id", "boards work-item show"), "boards work-item show.id")
    return doc


# --- history -----------------------------------------------------------------------------------------------

def updates_since(repo_root, wid: int, rev: int) -> list[dict]:
    """The revisions of work item `wid` whose `rev` is greater than `rev`, oldest first; `[]` when there is none
    (`rev` 0 is the whole history). The filter is the client's: the list is read from the first revision in pages of
    200 (`$top`, `$skip`). A board that ignores `$skip`, or an item with more history than the platform keeps, is
    an `AdoImportError` — the newest revisions are last, so a silent cut would drop the ones asked for."""
    wid = _positive(wid, "a work item id")
    if not _is_int(rev) or rev < 0:
        raise ValueError(f"rev must be a non-negative integer, got {rev!r}")
    project = _project(repo_root)
    found: list[dict] = []
    seen: set[int] = set()
    skip = 0
    for _ in range(MAX_UPDATE_PAGES):
        doc = _call(repo_root, "updates", query={"$top": str(PAGE_SIZE), "$skip": str(skip)}, project=project, id=wid)
        page = _list_in(doc, "value", "updates")
        revs = [_id_in(_require(update, "rev", "updates row"), "updates row.rev") for update in page]
        if page and not set(revs) - seen:
            raise AdoImportError(f"wit/updates (work item {wid}): paging did not advance (the board sent revisions "
                                 f"it had already sent for $skip={skip})")
        seen.update(revs)
        found.extend(update for update, r in zip(page, revs) if r > rev)
        if len(page) < PAGE_SIZE:
            return sorted(found, key=lambda update: update["rev"])
        skip += len(page)
    raise AdoImportError(f"wit/updates (work item {wid}): more than {MAX_UPDATE_PAGES} pages of "
                         f"{PAGE_SIZE} revisions; stopped rather than return a history that is cut short")


# --- discussion --------------------------------------------------------------------------------------------

class CommentList(list):
    """The comments of one item, oldest first — a plain list, plus what a list cannot say.

    `truncated`: the read stopped at `MAX_COMMENT_PAGES` with the board still holding more.
    `total_count`: the board's own `totalCount` from the first page, or None when it sent none (never 0)."""

    truncated: bool = False
    total_count: int | None = None


def comments(repo_root, wid: int) -> list[dict]:
    """Every comment on work item `wid`, deleted ones included, oldest first (`order=asc`, `$top=200`,
    `includeDeleted=true`; no `since` filter exists). The next page is asked for with the `continuationToken` in
    the response BODY — `devops invoke` does not surface response headers. At most `MAX_COMMENT_PAGES` pages are
    read; if the board still had more, the result's `.truncated` is True. Text is returned exactly as sent."""
    wid = _positive(wid, "a work item id")
    project = _project(repo_root)
    out = CommentList()
    token = None
    for page_no in range(MAX_COMMENT_PAGES):
        query = {"order": "asc", "$top": str(PAGE_SIZE), "includeDeleted": "true"}
        if token:
            query["continuationToken"] = token
        doc = _call(repo_root, "comments", query=query, project=project, workItemId=wid)
        out.extend(_list_in(doc, "comments", "comments"))
        if page_no == 0 and _is_int(doc.get("totalCount")):
            out.total_count = doc["totalCount"]
        token = doc.get("continuationToken")
        if token is not None and not isinstance(token, str):
            raise AdoImportError("unexpected az shape: comments.continuationToken is not text")
        if not token:
            return out
    out.truncated = True
    return out


def comment_versions(repo_root, wid: int, comment_id: int) -> list[dict]:
    """Every saved version of one comment (its edit history), as the board sent them."""
    wid = _positive(wid, "a work item id")
    comment_id = _positive(comment_id, "a comment id")
    doc = _call(repo_root, "comment_versions", project=_project(repo_root), workItemId=wid, commentId=comment_id)
    return _list_in(doc, "value", "commentsVersions")


# --- identity ----------------------------------------------------------------------------------------------

def connection_data(repo_root) -> dict:
    """The organisation's `connectionData`: `authenticatedUser` is the identity the token belongs to. The route has
    no parameters; whether az wants an empty `--route-parameters` word for it is a B0 capture question."""
    doc = _call(repo_root, "connection_data")
    _require(doc, "authenticatedUser", "connectionData")
    return doc


# --- writes: B3 fills these six bodies, nothing else in this file ------------------------------------------

def create(repo_root, type_name: str, patch: list[dict]) -> dict:
    raise NotImplementedError("B3")


def update(repo_root, wid: int, patch: list[dict]) -> dict:
    raise NotImplementedError("B3")


def add_comment(repo_root, wid: int, text: str, fmt: str) -> dict:
    raise NotImplementedError("B3")


def add_history(repo_root, wid: int, rev: int, html: str) -> dict:
    raise NotImplementedError("B3")


def list_recent_comments(repo_root, wid: int) -> list[dict]:
    raise NotImplementedError("B3")


def link_pr(repo_root, pr_id: int, wid: int) -> None:
    raise NotImplementedError("B3")
