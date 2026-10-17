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
  connection_data(repo)                who the signed-in identity is (`authenticatedUser`), through `az rest`
  BOARDS_AZ_CONTRACT                   every argv prefix the reads issue, for `test_boards_az_contract.py`

How it asks. A `devops invoke` read goes through `ado_transport.invoke_body`, and its location (area,
resource, route-parameter names, method, api-version) comes from `boards_contract.WIT_ROUTES` — the one
place the live capture corrects, so a corrected row is followed with no change here. Two reads have a native
verb and use `ado_transport.az_json` with the scope `ado_transport.scope(with_repository=False)` supplies
(`--detect false --org --project`; a work item is not in a repository, and `az boards work-item show`
takes the organisation only). Every argv therefore carries `--detect false` and ends `-o json`; the seam
adds `--only-show-errors`; the only preview api-version is `PREVIEW_API_VERSION`, which the discussion
and identity routes use. The module imports no subprocess: `az` is spawned only inside the transport seam.

The one exception is the identity read. The B0 capture (2026-10-14) found that `connectionData` is not an
`az devops invoke` location at all, so it is `ado_transport.rest_get` of `boards_contract.REST_ROUTES` —
`az rest --method get --resource <Azure DevOps' resource id> --url <org>/_apis/connectionData?api-version=
7.1-preview -o json`, the only `az rest` read the plugin sends (no `--detect`: `az rest` has no such flag). It needs
an Entra sign-in: with a personal access token alone the read fails, the failure says the identity is
UNKNOWN (never "signed out", never a guess), and every write that needs it refuses as `identity_unknown`.
The one write of the same kind is `update` (and `add_history`, which is an update): the second capture (2026-10-15)
found that `az devops invoke` cannot PATCH a work item, so it is `ado_transport.rest_patch` (see `update`).

The tag queries scope by the project NAME, never the WIQL current-project macro: `az boards query` with
`[System.TeamProject] = @project` printed zero bytes (exit 0) on a board where items matched (B0, 2026-10-15),
while the literal project name, or no clause with `--project`, returned the rows. A query that prints nothing is
read as no rows (`QueryIds.printed_nothing`), never as a crash: empty stdout is not JSON.

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
from boards_contract import PAGE_TOKEN_KEYS, REF_RE, REST_ROUTES, WIT_ROUTES  # noqa: E402

BATCH_SIZE = 200          # ids per `workitemsbatch` POST: the REST limit
PAGE_SIZE = 200           # `$top` for the updates and comments reads
MAX_COMMENT_PAGES = 5     # 1,000 comments; `comments` says when it stopped here
MAX_UPDATE_PAGES = 50     # 10,000 revisions, the most Azure DevOps keeps for one item

_BODY_MEDIA_TYPE = "application/json"  # the batch read's request body (a JSON object, not a JSON Patch)

# Every argv prefix the reads issue, in the order of the list above (placeholders: P project, U organisation URL,
# Q a WIQL text, N a work item id, C a comment id, F the request body file, T a continuation token). Checked
# against `az ... --help` by test_boards_az_contract.py and against the argv the reads really emit by
# test_boards_wit_reads.py. Read-only, `--detect false`, no `--repository`, no preview revision — except the last,
# the identity read: `az rest` of the one allow-listed URL (U/_apis/connectionData), which has no `--detect` flag.
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
    ["rest", "--method", "get", "--resource", "499b84ac-1321-427f-aa17-267ca6975798", "--url",
     "U/_apis/connectionData?api-version=7.1-preview", "-o", "json"],
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
    `ref` is checked against `boards_contract.REF_RE` first: it is placed inside a WIQL string literal. The query names
    the remote's project as a literal (`ado_wit_map.wiql_ref_lookup`), never the current-project macro."""
    if not isinstance(ref, str) or not REF_RE.fullmatch(ref):
        raise ValueError(f"not a ref of the form sdlc:<kind>:<id>: {ref!r}")
    from ado_wit_map import wiql_ref_lookup  # pure; imported here as the write bodies import `classify_write_error`
    return query_ids(repo_root, wiql_ref_lookup(ref, _project(repo_root)))


class QueryIds(list):
    """The ids a `boards query` returned, in order — a plain list, plus whether `az` printed nothing at all.

    `printed_nothing`: the stdout was empty (zero bytes). `az boards query` prints nothing when no work item matches,
    and it also printed nothing for a query the board could not scope (the current-project macro, B0 2026-10-15), so
    an empty answer is read as no rows and a caller may say so; it is never parsed as JSON."""

    printed_nothing: bool = False


QUERY_PRINTED_NOTHING = ("`az boards query` printed nothing (zero bytes, read as no matching work item; an empty "
                         "stdout is not JSON)")


def query_ids(repo_root, wiql: str) -> list[int]:
    """`az boards query --wiql <wiql>`: the `id` of each work item it returns, in order (a `QueryIds`). An empty stdout
    (az prints nothing when no work item matches) is `[]` with `.printed_nothing` set. The caller owns the WIQL; build
    it with `ado_wit_map`."""
    if not isinstance(wiql, str) or not wiql.strip():
        raise ValueError("wiql must be a non-empty string")
    try:
        rows, nothing = ado_transport.az_json_read(["boards", "query",
                                                    *ado_transport.scope(repo_root, with_repository=False),
                                                    "--wiql", wiql], repo_root)
    except AdoImportError as exc:
        raise AdoImportError(f"boards query: {exc}") from exc
    if not isinstance(rows, list):
        raise AdoImportError("unexpected az shape: `az boards query` did not print a list of work items")
    out = QueryIds(_id_in(_require(row, "id", "boards query row"), "boards query row.id") for row in rows)
    out.printed_nothing = nothing
    return out


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
    `includeDeleted=true`; no `since` filter exists). The next page is asked for with the token the answer carries:
    the body's `continuationToken`, else the `continuation_token` key the extension adds itself (its spelling; the
    capture of 2026-10-15 answered only that one) — `boards_contract.PAGE_TOKEN_KEYS`. At most `MAX_COMMENT_PAGES`
    pages are read; if the board still had more, the result's `.truncated` is True. Text is returned exactly as sent."""
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
        token = next((doc[k] for k in PAGE_TOKEN_KEYS if doc.get(k) not in (None, "")), None)
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
    """The organisation's `connectionData`: `authenticatedUser` is the identity the token belongs to.

    Not a `devops invoke` read (B0 capture, 2026-10-14: no area resolves it): `ado_transport.rest_get` of
    `REST_ROUTES["connection_data"]`, an `az rest` GET at `7.1-preview` (`7.1` is refused as "under preview"). An
    error is worded `core/connectionData (az rest): <why>`; under a personal access token alone `<why>` is
    `ado_transport.REST_NO_TOKEN` — the identity is unknown, and nothing here guesses one."""
    row = REST_ROUTES["connection_data"]
    try:
        doc = ado_transport.rest_get(repo_root, row["path"], api_version=row["api_version"])
    except AdoImportError as exc:
        raise AdoImportError(f"core/connectionData (az rest): {exc}") from exc
    _require(doc, "authenticatedUser", "connectionData")
    return doc


# --- writes: B3 fills these six bodies, nothing else in this file ------------------------------------------

def create(repo_root, type_name: str, patch: list[dict]) -> dict:
    """`POST wit/workItems` of a JSON Patch: a new item of `type_name`. Returns `{"id", "rev"}` and nothing else — the
    board's reply names the people who created it, and that never leaves this module.

    The location is `WIT_ROUTES["workitem_create"]` (route `project=<P> type=<type_name>` — bare: the extension's
    template is `{project}/_apis/wit/workItems/${type}`, so a leading `$` reaches the board doubled and 404s; found by
    the 2026-10-14 B0 capture); the body goes
    `application/json-patch+json`. A failure is an `AdoImportError` carrying `error_class`: what
    `ado_wit_map.classify_write_error` reads its stderr as (`conflict`, `rule`, `permission`, `throttled`,
    `not_found`, else `unknown`). A reply this module cannot read is `unknown` too: the board said yes, so the item
    may exist. An error raised before `az` was called (no Azure DevOps remote) carries no `error_class`. Never retried."""
    if (not isinstance(type_name, str) or not type_name.strip() or type_name.startswith("$")
            or any(ch in "/\\?#%" or ord(ch) < 32 or ord(ch) == 127 for ch in type_name)):
        raise ValueError(f"type_name must be a work item type name (no leading $, slash or control character), "
                         f"got {type_name!r}")
    if not isinstance(patch, list) or not patch or not all(isinstance(op, dict) for op in patch):
        raise ValueError("patch must be a non-empty list of JSON Patch operations")
    row = WIT_ROUTES["workitem_create"]
    params = {"project": _project(repo_root), "type": type_name}   # bare: the location template already carries the `$`
    label = f"{row['area']}/{row['resource']} (create {type_name})"
    try:
        doc = ado_transport.invoke_body(repo_root, row["area"], row["resource"],
                                        {key: params[key] for key in row["route"]}, method=row["method"], body=patch,
                                        media_type="application/json-patch+json", api_version=row["api_version"])
    except AdoImportError as exc:
        from ado_wit_map import classify_write_error  # here, not at the top: Fold B3 changes only these six bodies
        error_class = classify_write_error(str(exc))
        failure = AdoImportError(f"{label}: write failed [{error_class}]: {exc}")
        failure.error_class = error_class
        raise failure from exc
    try:
        return {"id": _id_in(_require(doc, "id", "workItems create"), "workItems create.id"),
                "rev": _id_in(_require(doc, "rev", "workItems create"), "workItems create.rev")}
    except AdoImportError as exc:
        failure = AdoImportError(f"{label}: the reply was unreadable and the write may have landed [unknown]: {exc}")
        failure.error_class = "unknown"
        raise failure from exc


def update(repo_root, wid: int, patch: list[dict]) -> dict:
    """`PATCH wit/workItems` of a JSON Patch on item `wid`. The patch MUST begin with `test /rev` (the revision the
    caller read), so a board that has moved on answers a refusal (`conflict`) instead of being overwritten; a patch
    that does not is a `ValueError` before any call. Returns `{"id", "rev"}` (the new revision) and nothing else.

    The location is `WIT_ROUTES["workitem_update"]` (`{project}/_apis/wit/workItems/{id}`), sent NOT through
    `az devops invoke` — for a PATCH the extension binds the other `workItems` location (`…/workItems/${type}`) and
    dies with `ERROR: 'type'` (B0, 2026-10-15) — but as `ado_transport.rest_patch` of `REST_ROUTES["workitem_update"]`:
    `az rest --method patch --resource <Azure DevOps' resource id> --url <org>/<project>/_apis/wit/workitems/<id>?
    api-version=7.1 --headers Content-Type=application/json-patch+json --body @<file> -o json`. That needs an Entra
    sign-in; under a personal access token alone the error is `ado_transport.REST_NO_TOKEN_WRITE` (nothing was sent).
    Errors as `create`: a failed write carries `error_class` (a stale `test /rev` answers `Precondition Failed …
    VS403351`, which reads `conflict`), an unreadable reply (or one for another item) is `unknown`. Never retried."""
    wid = _positive(wid, "a work item id")
    first = patch[0] if isinstance(patch, list) and patch else None
    if not (isinstance(first, dict) and first.get("op") == "test" and first.get("path") == "/rev"
            and _is_int(first.get("value")) and first["value"] >= 1):
        raise ValueError("an update patch must begin with {'op': 'test', 'path': '/rev', 'value': <the revision read>}")
    if not all(isinstance(op, dict) for op in patch):
        raise ValueError("patch must be a list of JSON Patch operations")
    row, rest = WIT_ROUTES["workitem_update"], REST_ROUTES["workitem_update"]
    params = {"project": _project(repo_root), "id": wid}
    label = f"{row['area']}/{row['resource']} (work item {wid})"
    try:
        doc = ado_transport.rest_patch(repo_root, rest["path"], {key: params[key] for key in row["route"]}, patch,
                                       api_version=rest["api_version"])
    except AdoImportError as exc:
        from ado_wit_map import classify_write_error  # here, not at the top: Fold B3 changes only these six bodies
        error_class = classify_write_error(str(exc))
        failure = AdoImportError(f"{label}: write failed [{error_class}]: {exc}")
        failure.error_class = error_class
        raise failure from exc
    try:
        answered = _id_in(_require(doc, "id", "workItems update"), "workItems update.id")
        if answered != wid:
            raise AdoImportError(f"unexpected az shape: workItems update answered for work item {answered}")
        return {"id": answered, "rev": _id_in(_require(doc, "rev", "workItems update"), "workItems update.rev")}
    except AdoImportError as exc:
        failure = AdoImportError(f"{label}: the reply was unreadable and the write may have landed [unknown]: {exc}")
        failure.error_class = "unknown"
        raise failure from exc


def add_comment(repo_root, wid: int, text: str, fmt: str) -> dict:
    """`POST wit/comments` of `{"text": text}` on item `wid`, `format=<fmt>` (`markdown` or `html`), at
    `PREVIEW_API_VERSION`: the discussion's own endpoint. The text rides in the request body only — never in an argv
    element, so no quote, newline or `$(` in it can reach a shell — and never in an error message. Returns
    `{"comment_id", "version"}` and nothing else.

    The location is the `comments` row of `WIT_ROUTES` (the read location of the same resource; the method here is
    POST). Errors as `create`: a failed write carries `error_class`; an unreadable reply is `unknown`, and the caller
    recovers by re-listing (`list_recent_comments`), never by posting again. Never retried."""
    wid = _positive(wid, "a work item id")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("a comment's text must be non-empty text")
    if fmt not in ("markdown", "html"):
        raise ValueError(f"fmt must be 'markdown' or 'html', got {fmt!r}")
    row = WIT_ROUTES["comments"]
    params = {"project": _project(repo_root), "workItemId": wid}
    label = f"{row['area']}/{row['resource']} (work item {wid})"
    try:
        doc = ado_transport.invoke_body(repo_root, row["area"], row["resource"],
                                        {key: params[key] for key in row["route"]}, method="POST",
                                        body={"text": text}, media_type="application/json", query={"format": fmt},
                                        api_version=row["api_version"])
    except AdoImportError as exc:
        from ado_wit_map import classify_write_error  # here, not at the top: Fold B3 changes only these six bodies
        error_class = classify_write_error(str(exc))
        failure = AdoImportError(f"{label}: write failed [{error_class}]: {exc}")
        failure.error_class = error_class
        raise failure from exc
    try:
        return {"comment_id": _id_in(_require(doc, "id", "comments add"), "comments add.id"),
                "version": _id_in(_require(doc, "version", "comments add"), "comments add.version")}
    except AdoImportError as exc:
        failure = AdoImportError(f"{label}: the reply was unreadable and the write may have landed [unknown]: {exc}")
        failure.error_class = "unknown"
        raise failure from exc


def add_history(repo_root, wid: int, rev: int, html: str) -> dict:
    """The fallback for a comment: `update` with `[test /rev, add /fields/System.History]` — one History entry on item
    `wid`, written only if the item is still at revision `rev`. Returns what `update` returns (`{"id", "rev"}`);
    every refusal, error and `error_class` is `update`'s."""
    rev = _positive(rev, "a revision")
    if not isinstance(html, str) or not html.strip():
        raise ValueError("a history entry must be non-empty text")
    return update(repo_root, wid, [{"op": "test", "path": "/rev", "value": rev},
                                   {"op": "add", "path": "/fields/System.History", "value": html}])


def list_recent_comments(repo_root, wid: int) -> list[dict]:
    """The newest 20 comments on item `wid`, newest first (`order=desc`, `$top=20`), as the board sent them: a READ,
    asked after a comment POST whose outcome is unknown, so the caller can look for the text it sent (by its
    `text_sha`) instead of posting twice. Authors and text are returned unredacted — the recovery rule needs the
    author's id — so nothing here may be written to a file."""
    wid = _positive(wid, "a work item id")
    doc = _call(repo_root, "comments", query={"order": "desc", "$top": "20"}, project=_project(repo_root),
                workItemId=wid)
    return _list_in(doc, "comments", "comments")


def link_pr(repo_root, pr_id: int, wid: int) -> None:
    """`az repos pr work-item add --id <pr_id> --work-items <wid>` through `az_json`: link pull request `pr_id` to
    work item `wid`. A native verb, not a `devops invoke`. A pull request id is organisation-wide (as for
    `az repos pr update --id`), so the argv carries `--detect false --org <url>` and not `--project`/`--repository`.
    Errors as `create`: a failure carries `error_class`. Never retried."""
    pr_id = _positive(pr_id, "a pull request id")
    wid = _positive(wid, "a work item id")
    org_url = ado_transport.remote(repo_root).org_url
    label = f"repos pr work-item add (PR {pr_id}, work item {wid})"
    try:
        ado_transport.az_json(["repos", "pr", "work-item", "add", "--id", str(pr_id), "--work-items", str(wid),
                               "--detect", "false", "--org", org_url], repo_root)
    except AdoImportError as exc:
        from ado_wit_map import classify_write_error  # here, not at the top: Fold B3 changes only these six bodies
        error_class = classify_write_error(str(exc))
        failure = AdoImportError(f"{label}: write failed [{error_class}]: {exc}")
        failure.error_class = error_class
        raise failure from exc
