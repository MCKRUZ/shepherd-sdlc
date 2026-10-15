"""B2-P2 — the work-item reads (`ado_wit`): items, history, discussion, identity.

What this pins, and why each line exists (build kit §5 card B2-P2; house rules 2, 9, 10, 11; guardrails 2, 7, 8, 10):
  * `get_batch` sends ONE `POST wit/workitemsbatch` per 200 ids, with `$expand=relations` and
    `errorPolicy=omit`, and reports the ids the board did not return as `missing` (a deleted item is
    news, never an error and never a silent drop);
  * `query_ids` / `find_by_ref` are `az boards query --wiql` with `scope(with_repository=False)` — so
    `--detect false` and NO `--repository` — and an empty stdout is `[]`;
  * `comments` pages on the response BODY's `continuationToken`, stops at five pages, says when it
    stopped early, and asks for `PREVIEW_API_VERSION`; `updates_since` filters `rev >` on the client;
  * every route comes from `boards_contract.WIT_ROUTES` (the one B0 correction point), every recorded
    argv carries `--detect false`, ends `-o json`, never holds `--only-show-errors` (the seam adds it)
    and never a `-preview.<digit>` string; a read-only fake (`writes=False`) passes every read;
  * a response is read only through `_require`; a shape it does not know is an `AdoImportError`;
  * since Fold B3 the six write functions have bodies (B3-P1's own tests pin their shapes): against a read-only
    fake (`writes=False`) the five that write raise its `AssertionError("unexpected az write: ...")` — nothing
    reaches the board — and go through against a writing one; `list_recent_comments` is the one read among the
    six, so a read-only fake passes it.

Nothing here spawns `az`: `boards_env` forbids it at the seam and `az` swaps a `FakeBoardsAz` in for `run_az`.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import HAND_WRITTEN_PROCESS
from tests.ado_boards_fixtures import FakeBoardsAz, identity_rest_argv, is_identity_rest_read, load_wit, route_key_boards, route_params

import ast
import inspect
import json
import re
from pathlib import Path

import pytest

import ado_transport
import ado_wit
import boards_contract
from ado_map import AdoImportError

# B0 (2026-10-15): the second capture shadowed the item, write and comment fixtures (`WIT_CAPTURED_ITEMS`); this module's
# scenarios pin the hand-written ones' ids and texts, so it reads those (`BOARDS_ITEMS`, tests/ado_boards_fixtures.py).
# The captured answers are exercised in test_boards_captured_items.py.
BOARDS_ITEMS = HAND_WRITTEN_PROCESS

ORG = "https://dev.azure.com/contoso"  # what tests.ado_fixtures.ADO_REMOTE parses to
PROJECT = "Claims"
PREVIEW = ado_transport.PREVIEW_API_VERSION


# --- helpers ---------------------------------------------------------------------------------------------

def batch_answer(seen: list, missing=frozenset()):
    """A `workitemsbatch` reply built from the request body: a row per id, a `null` for the ids in `missing`."""
    def answer(args):
        body = json.loads(Path(args[args.index("--in-file") + 1]).read_text(encoding="utf-8"))
        seen.append((args, body))
        value = [None if i in missing else {"id": i, "rev": 1, "fields": {"System.Id": i}} for i in body["ids"]]
        return {"count": len(value), "value": value}
    return answer


def pages_answer(pages: list[dict]):
    """Serve `pages` in order, then fail loudly if asked for another."""
    calls = iter(pages)

    def answer(args):
        try:
            return next(calls)
        except StopIteration:
            raise AssertionError("asked for a page that was never served") from None
    return answer


def comment_page(first: int, n: int, token: str | None, total: int = 99) -> dict:
    doc = {"totalCount": total, "count": n,
           "comments": [{"workItemId": 4521, "id": first + i, "version": 1, "text": "x", "format": "html"}
                        for i in range(n)]}
    if token is not None:
        doc["continuationToken"] = token
    return doc


def update_page(first_rev: int, n: int) -> dict:
    return {"count": n, "value": [{"id": first_rev + i, "workItemId": 4521, "rev": first_rev + i, "fields": {}}
                                  for i in range(n)]}


def query_of(argv: list[str]) -> list[str]:
    i = argv.index("--query-parameters") + 1
    out = []
    for word in argv[i:]:
        if word.startswith("--"):
            break
        out.append(word)
    return out


def run_every_read(repo) -> None:
    ado_wit.find_by_ref(repo, "sdlc:spec:0004")
    ado_wit.query_ids(repo, "SELECT [System.Id] FROM WorkItems")
    ado_wit.get_batch(repo, [4521, 4410])
    ado_wit.get_item(repo, 4521)
    ado_wit.updates_since(repo, 4521, 0)
    ado_wit.comments(repo, 4521)
    ado_wit.comment_versions(repo, 4521, 502)
    ado_wit.connection_data(repo)


# --- get_batch -------------------------------------------------------------------------------------------

def test_get_batch_of_250_ids_is_two_posts_of_200_and_50(az, tmp_path):
    seen: list = []
    az.answers["POST wit/workitemsbatch"] = batch_answer(seen)
    ids = list(range(1000, 1250))
    rows, missing = ado_wit.get_batch(tmp_path, ids)
    assert az.count("devops", "invoke") == 2
    assert [route_key_boards(c) for c in az.calls] == ["POST wit/workitemsbatch"] * 2
    assert [len(body["ids"]) for _, body in seen] == [200, 50]
    assert [i for _, body in seen for i in body["ids"]] == ids  # in order, none lost, none repeated
    assert [r["id"] for r in rows] == ids and missing == []


def test_get_batch_body_and_argv_are_pinned(az, tmp_path):
    seen: list = []
    az.answers["POST wit/workitemsbatch"] = batch_answer(seen)
    ado_wit.get_batch(tmp_path, [4521, 4410])
    argv, body = seen[0]
    assert body == {"ids": [4521, 4410], "$expand": "relations", "errorPolicy": "omit"}  # no `fields`: it cannot ride with $expand
    assert argv[:argv.index("--in-file")] == ["devops", "invoke", "--area", "wit", "--resource", "workitemsbatch",
                                              "--route-parameters", f"project={PROJECT}", "--http-method", "POST"]
    assert argv[argv.index("--in-file") + 2:] == ["--media-type", "application/json", "--api-version", "7.1",
                                                  "--detect", "false", "--org", ORG, "-o", "json"]


def test_get_batch_reports_the_ids_the_board_did_not_return_as_missing(az, tmp_path):
    seen: list = []
    az.answers["POST wit/workitemsbatch"] = batch_answer(seen, missing={4410, 4999})
    rows, missing = ado_wit.get_batch(tmp_path, [4521, 4410, 4999, 4530])
    assert [r["id"] for r in rows] == [4521, 4530]
    assert missing == [4410, 4999]


def test_get_batch_missing_is_measured_by_what_came_back_not_by_the_nulls(az, tmp_path):
    # a board that drops an id with no null in its place still has that id reported
    az.answers["POST wit/workitemsbatch"] = {"count": 1, "value": [{"id": 4521, "rev": 1, "fields": {}}]}
    rows, missing = ado_wit.get_batch(tmp_path, [4521, 4410])
    assert [r["id"] for r in rows] == [4521] and missing == [4410]


def test_get_batch_missing_spans_chunks(az, tmp_path):
    seen: list = []
    az.answers["POST wit/workitemsbatch"] = batch_answer(seen, missing={5, 205})
    rows, missing = ado_wit.get_batch(tmp_path, list(range(1, 251)))
    assert missing == [5, 205] and len(rows) == 248


def test_get_batch_on_the_default_fixture(az, tmp_path):
    rows, missing = ado_wit.get_batch(tmp_path, [4521, 4410, 4999])
    assert [r["id"] for r in rows] == [4521, 4410] and missing == [4999]
    assert rows[0]["rev"] == 7 and "relations" in rows[0]  # relations were requested, so they are passed through


def test_get_batch_of_nothing_asks_nothing(az, tmp_path):
    assert ado_wit.get_batch(tmp_path, []) == ([], [])
    assert az.calls == []


def test_get_batch_asks_for_each_id_once(az, tmp_path):
    seen: list = []
    az.answers["POST wit/workitemsbatch"] = batch_answer(seen)
    rows, missing = ado_wit.get_batch(tmp_path, [7, 7, 8, 7])
    assert seen[0][1]["ids"] == [7, 8] and [r["id"] for r in rows] == [7, 8] and missing == []


@pytest.mark.parametrize("bad", ["4521", 4521.0, True, 0, -3, None])
def test_get_batch_refuses_an_id_that_is_not_a_positive_integer(az, tmp_path, bad):
    with pytest.raises(ValueError):
        ado_wit.get_batch(tmp_path, [4521, bad])
    assert az.calls == []  # refused before anything was asked


@pytest.mark.parametrize("reply", [[], {"count": 0}, {"value": "x"}, {"count": 1, "value": [{"rev": 1}]},
                                   {"count": 1, "value": [{"id": "4521", "rev": 1}]}],
                         ids=["list", "no-value", "value-not-a-list", "row-without-id", "id-not-an-int"])
def test_get_batch_raises_on_a_shape_it_does_not_know(az, tmp_path, reply):
    az.answers["POST wit/workitemsbatch"] = reply
    with pytest.raises(AdoImportError):
        ado_wit.get_batch(tmp_path, [4521])


def test_get_batch_names_the_failed_call(az, tmp_path):
    az.fail["workitemsbatch"] = "TF401232: nope"
    with pytest.raises(AdoImportError, match=r"wit/workitemsbatch.*TF401232"):
        ado_wit.get_batch(tmp_path, [4521])


# --- query_ids / find_by_ref -----------------------------------------------------------------------------

WIQL = "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project"


def test_query_ids_argv_is_pinned_and_has_no_repository(az, tmp_path):
    assert ado_wit.query_ids(tmp_path, WIQL) == [4521]
    (argv,) = az.calls
    assert argv == ["boards", "query", "--detect", "false", "--org", ORG, "--project", PROJECT, "--wiql", WIQL,
                    "-o", "json"]
    assert "--repository" not in argv and "--only-show-errors" not in argv


def test_query_ids_takes_the_id_of_each_row_in_order(az, tmp_path):
    az.answers["boards query"] = [{"id": 30, "fields": {}}, {"id": 4, "rev": 2}, {"id": 4521}]
    assert ado_wit.query_ids(tmp_path, WIQL) == [30, 4, 4521]
    az.answers["boards query"] = load_wit("wiql_untagged")
    assert ado_wit.query_ids(tmp_path, WIQL) == [4530, 4531]


def test_query_ids_empty_stdout_is_an_empty_list_not_an_error(az, tmp_path):
    az.answers["boards query"] = None  # az prints nothing when no work item matches
    assert ado_wit.query_ids(tmp_path, WIQL) == []


@pytest.mark.parametrize("reply", [{"id": 1}, 3, [{"fields": {}}], [{"id": "7"}], [{"id": True}], [None]],
                         ids=["object", "number", "row-without-id", "id-not-an-int", "id-a-bool", "row-null"])
def test_query_ids_raises_on_a_shape_it_does_not_know(az, tmp_path, reply):
    az.answers["boards query"] = reply
    with pytest.raises(AdoImportError):
        ado_wit.query_ids(tmp_path, WIQL)


@pytest.mark.parametrize("wiql", ["", "   ", None, 7])
def test_query_ids_refuses_a_blank_query(az, tmp_path, wiql):
    with pytest.raises(ValueError):
        ado_wit.query_ids(tmp_path, wiql)
    assert az.calls == []


def test_find_by_ref_looks_the_tag_up_through_a_wiql(az, tmp_path):
    assert ado_wit.find_by_ref(tmp_path, "sdlc:spec:0004") == [4521]
    (argv,) = az.calls
    assert route_key_boards(argv) == "boards query"
    wiql = argv[argv.index("--wiql") + 1]
    # B0 (2026-10-15): the remote's project NAME as a literal; the `@project` macro made az print zero bytes
    assert wiql == ("SELECT [System.Id],[System.WorkItemType],[System.Title],[System.State],[System.Tags],"
                    "[System.AssignedTo] FROM WorkItems WHERE [System.TeamProject] = 'Claims' AND "
                    "[System.Tags] CONTAINS 'sdlc:spec:0004'")
    assert "@project" not in wiql
    assert "--repository" not in argv and argv[argv.index("--detect") + 1] == "false"


@pytest.mark.parametrize("ref", ["", "spec:0004", "sdlc:spec", "sdlc:spec:0004' OR [System.Id] > 0 OR '", "sdlc:Spec:0004",
                                 "sdlc:spec:00 04", "sdlc:spec:0004\n", None, 4])
def test_find_by_ref_refuses_a_ref_that_is_not_a_ref_before_it_asks(az, tmp_path, ref):
    with pytest.raises(ValueError):
        ado_wit.find_by_ref(tmp_path, ref)
    assert az.calls == []


def test_find_by_ref_with_no_match_is_an_empty_list(az, tmp_path):
    az.answers["boards query"] = None
    assert ado_wit.find_by_ref(tmp_path, "sdlc:spec:9999") == []


# --- get_item (the native single-item show) --------------------------------------------------------------

def test_get_item_is_the_native_show_with_relations(az, tmp_path):
    item = ado_wit.get_item(tmp_path, 4521)
    (argv,) = az.calls
    assert argv == ["boards", "work-item", "show", "--id", "4521", "--expand", "relations", "--detect", "false",
                    "--org", ORG, "-o", "json"]
    assert route_key_boards(argv) == "boards work-item show"
    assert item["id"] == 4521 and item["rev"] == 7 and item["relations"]


@pytest.mark.parametrize("reply", [None, [], 3, {"rev": 1, "fields": {}}], ids=["empty", "list", "number", "no-id"])
def test_get_item_raises_on_a_shape_it_does_not_know(az, tmp_path, reply):
    az.answers["boards work-item show"] = reply  # None is the empty stdout az_json reads as `[]`
    with pytest.raises(AdoImportError):
        ado_wit.get_item(tmp_path, 4521)


@pytest.mark.parametrize("bad", ["4521", 0, -1, True, None])
def test_get_item_refuses_an_id_that_is_not_a_positive_integer(az, tmp_path, bad):
    with pytest.raises(ValueError):
        ado_wit.get_item(tmp_path, bad)
    assert az.calls == []


# --- updates_since ---------------------------------------------------------------------------------------

def test_updates_since_keeps_only_revisions_after_rev(az, tmp_path):
    assert [u["rev"] for u in ado_wit.updates_since(tmp_path, 4521, 3)] == [4, 5]
    assert [u["rev"] for u in ado_wit.updates_since(tmp_path, 4521, 0)] == [1, 2, 3, 4, 5]
    assert ado_wit.updates_since(tmp_path, 4521, 5) == []  # nothing newer is an honest empty list
    assert ado_wit.updates_since(tmp_path, 4521, 9) == []


def test_updates_since_argv_is_pinned(az, tmp_path):
    ado_wit.updates_since(tmp_path, 4521, 3)
    (argv,) = az.calls
    assert argv == ["devops", "invoke", "--area", "wit", "--resource", "updates", "--route-parameters",
                    f"project={PROJECT}", "id=4521", "--http-method", "GET", "--query-parameters", "$top=200", "$skip=0",
                    "--api-version", "7.1", "--detect", "false", "--org", ORG, "-o", "json"]


def test_updates_since_pages_with_top_and_skip_and_filters_across_pages(az, tmp_path):
    az.answers["GET wit/updates"] = pages_answer([update_page(1, 200), update_page(201, 200), update_page(401, 17)])
    got = ado_wit.updates_since(tmp_path, 4521, 395)
    assert [u["rev"] for u in got] == list(range(396, 418))
    assert [query_of(c) for c in az.calls] == [["$top=200", "$skip=0"], ["$top=200", "$skip=200"],
                                               ["$top=200", "$skip=400"]]


def test_updates_since_an_exact_multiple_of_the_page_size_needs_one_empty_page(az, tmp_path):
    az.answers["GET wit/updates"] = pages_answer([update_page(1, 200), {"count": 0, "value": []}])
    assert len(ado_wit.updates_since(tmp_path, 4521, 0)) == 200
    assert len(az.calls) == 2


def test_updates_since_stops_with_an_error_when_the_board_ignores_skip(az, tmp_path):
    az.answers["GET wit/updates"] = lambda args: update_page(1, 200)  # the same full page every time
    with pytest.raises(AdoImportError, match="did not advance"):
        ado_wit.updates_since(tmp_path, 4521, 0)
    assert len(az.calls) == 2  # not fifty


def test_updates_since_refuses_to_return_a_history_it_could_not_finish(az, tmp_path, monkeypatch):
    monkeypatch.setattr(ado_wit, "MAX_UPDATE_PAGES", 3)
    served = iter(update_page(1 + 200 * i, 200) for i in range(10))
    az.answers["GET wit/updates"] = lambda args: next(served)
    with pytest.raises(AdoImportError, match="more than 3 pages"):
        ado_wit.updates_since(tmp_path, 4521, 0)  # the newest revisions are the last ones, so a cut is never silent
    assert len(az.calls) == 3


def test_updates_since_returns_revisions_in_ascending_order(az, tmp_path):
    az.answers["GET wit/updates"] = {"count": 3, "value": [{"rev": 9}, {"rev": 5}, {"rev": 7}]}
    assert [u["rev"] for u in ado_wit.updates_since(tmp_path, 4521, 4)] == [5, 7, 9]


@pytest.mark.parametrize("reply", [[], {"count": 1}, {"value": [{"id": 1}]}, {"value": [{"rev": "2"}]}, {"value": ["x"]}],
                         ids=["list", "no-value", "row-without-rev", "rev-not-an-int", "row-not-an-object"])
def test_updates_since_raises_on_a_shape_it_does_not_know(az, tmp_path, reply):
    az.answers["GET wit/updates"] = reply
    with pytest.raises(AdoImportError):
        ado_wit.updates_since(tmp_path, 4521, 0)


@pytest.mark.parametrize("wid, rev", [("4521", 0), (0, 0), (True, 0), (4521, -1), (4521, "3"), (4521, None), (4521, False)])
def test_updates_since_refuses_a_bad_id_or_rev(az, tmp_path, wid, rev):
    with pytest.raises(ValueError):
        ado_wit.updates_since(tmp_path, wid, rev)
    assert az.calls == []


# --- comments --------------------------------------------------------------------------------------------

COMMENTS_FIRST = ["devops", "invoke", "--area", "wit", "--resource", "comments", "--route-parameters",
                  f"project={PROJECT}", "workItemId=4521", "--http-method", "GET", "--query-parameters", "order=asc",
                  "$top=200", "includeDeleted=true", "--api-version", PREVIEW, "--detect", "false", "--org", ORG,
                  "-o", "json"]


def test_comments_reads_two_pages_on_the_body_token(az, tmp_path):
    got = ado_wit.comments(tmp_path, 4521)
    assert [c["id"] for c in got] == [501, 502, 503]
    assert isinstance(got, list) and got.truncated is False and got.total_count == 3
    first, second = az.calls
    assert first == COMMENTS_FIRST
    assert query_of(second) == ["order=asc", "$top=200", "includeDeleted=true", "continuationToken=dG9rZW4tcGFnZS0y"]
    assert second[:second.index("--query-parameters")] == first[:first.index("--query-parameters")]
    assert second[second.index("--api-version"):] == first[first.index("--api-version"):]


def test_comments_stops_at_five_pages_and_says_it_did(az, tmp_path):
    n = iter(range(100))
    az.answers["GET wit/comments"] = lambda args: comment_page(1000 * next(n), 200, f"tok-{next(n)}", total=2400)
    got = ado_wit.comments(tmp_path, 4521)  # only the bare key was re-answered, so the fake serves it for every page
    assert az.count("devops", "invoke") == 5
    assert len(got) == 5 * 200 and got.truncated is True and got.total_count == 2400
    tokens = [next((w.partition("=")[2] for w in query_of(c) if w.startswith("continuationToken=")), None)
              for c in az.calls]
    assert tokens[0] is None and all(tokens[1:])  # the first call has no token, each later one carries the last
    assert all(c[c.index("--api-version") + 1] == PREVIEW for c in az.calls)


def test_comments_that_end_on_the_fifth_page_are_not_truncated(az, tmp_path):
    pages = [comment_page(1, 200, "t1"), comment_page(201, 200, "t2"), comment_page(401, 200, "t3"),
             comment_page(601, 200, "t4"), comment_page(801, 7, None)]
    az.answers["GET wit/comments"] = pages_answer(pages)
    got = ado_wit.comments(tmp_path, 4521)
    assert len(got) == 807 and got.truncated is False and az.count("devops", "invoke") == 5


@pytest.mark.parametrize("token", [None, ""], ids=["absent", "empty"])
def test_comments_with_no_token_is_one_page(az, tmp_path, token):
    az.answers["GET wit/comments"] = comment_page(1, 3, token)
    got = ado_wit.comments(tmp_path, 4521)
    assert [c["id"] for c in got] == [1, 2, 3] and got.truncated is False and az.count("devops", "invoke") == 1


def test_comments_with_none_is_an_empty_list_with_a_known_count(az, tmp_path):
    az.answers["GET wit/comments"] = {"totalCount": 0, "count": 0, "comments": []}
    got = ado_wit.comments(tmp_path, 4521)
    assert got == [] and got.total_count == 0 and got.truncated is False


def test_comments_without_a_total_count_has_none_not_zero(az, tmp_path):
    az.answers["GET wit/comments"] = {"count": 1, "comments": [{"id": 1}]}
    assert ado_wit.comments(tmp_path, 4521).total_count is None


def test_comments_returns_hostile_text_untouched(az, tmp_path):
    # transport only: stripping, redacting and quoting belong to the discussion map, never here
    got = ado_wit.comments(tmp_path, 4524)
    assert got == load_wit("comments_hostile")["comments"]
    assert any("<script" in c["text"] for c in got)
    assert {route_params(c)["workItemId"] for c in az.calls} == {"4524"}


@pytest.mark.parametrize("reply", [[], {"totalCount": 1}, {"comments": "x"}, {"comments": [], "continuationToken": 7}],
                         ids=["list", "no-comments", "comments-not-a-list", "token-not-text"])
def test_comments_raises_on_a_shape_it_does_not_know(az, tmp_path, reply):
    az.answers["GET wit/comments"] = reply
    with pytest.raises(AdoImportError):
        ado_wit.comments(tmp_path, 4521)


@pytest.mark.parametrize("bad", ["4521", 0, -1, None, True])
def test_comments_refuse_an_id_that_is_not_a_positive_integer(az, tmp_path, bad):
    with pytest.raises(ValueError):
        ado_wit.comments(tmp_path, bad)
    assert az.calls == []


# --- comment_versions ------------------------------------------------------------------------------------

def test_comment_versions_argv_and_result(az, tmp_path):
    got = ado_wit.comment_versions(tmp_path, 4521, 502)
    assert [v["version"] for v in got] == [1, 2]
    (argv,) = az.calls
    assert argv == ["devops", "invoke", "--area", "wit", "--resource", "commentsVersions", "--route-parameters",
                    f"project={PROJECT}", "workItemId=4521", "commentId=502", "--http-method", "GET",
                    "--api-version", PREVIEW, "--detect", "false", "--org", ORG, "-o", "json"]


@pytest.mark.parametrize("reply", [[], {"count": 0}, {"value": "x"}], ids=["list", "no-value", "value-not-a-list"])
def test_comment_versions_raises_on_a_shape_it_does_not_know(az, tmp_path, reply):
    az.answers["GET wit/commentsVersions"] = reply
    with pytest.raises(AdoImportError):
        ado_wit.comment_versions(tmp_path, 4521, 502)


@pytest.mark.parametrize("wid, cid", [(0, 502), (4521, 0), (4521, "502"), (True, 502), (4521, None)])
def test_comment_versions_refuse_a_bad_id(az, tmp_path, wid, cid):
    with pytest.raises(ValueError):
        ado_wit.comment_versions(tmp_path, wid, cid)
    assert az.calls == []


# --- connection_data -------------------------------------------------------------------------------------

def test_connection_data_is_the_one_az_rest_read_on_the_preview_version(az, tmp_path):
    """B0 (2026-10-14): `connectionData` is no `devops invoke` location (area core: "--resource and --api-version
    combination is not correct"; area Location: "--area is not present in current organization"). It is `az rest` with
    Azure DevOps' resource id, at `7.1-preview` (`7.1` is refused as "under preview")."""
    doc = ado_wit.connection_data(tmp_path)
    assert doc == load_wit("connection_data") and doc["authenticatedUser"]["id"]
    (argv,) = az.calls
    assert argv == ["rest", "--method", "get", "--resource", "499b84ac-1321-427f-aa17-267ca6975798", "--url",
                    f"{ORG}/_apis/connectionData?api-version={PREVIEW}", "-o", "json"]
    assert argv == identity_rest_argv(ORG) and "--only-show-errors" not in argv   # the seam appends it
    assert route_key_boards(argv) == "GET core/connectionData" and az.written() == []


def test_the_captured_identity_read_names_its_own_az_rest_call():
    from tests.ado_boards_fixtures import wit_path, wit_source_of
    assert wit_source_of("connection_data") == "captured"
    command = json.loads(wit_path("connection_data").read_text(encoding="utf-8"))["_command"]
    assert command == ["az", *identity_rest_argv(ORG)]
    assert "continuation_token" not in load_wit("connection_data")   # `az rest` adds none; `devops invoke` would


@pytest.mark.parametrize("stderr", ["ERROR: Please run 'az login' to setup account.",
                                    "ERROR: Please run `az login` to setup account."])
def test_connection_data_under_a_pat_only_sign_in_is_unknown_never_signed_out_and_never_guessed(az, tmp_path, stderr):
    """`az rest` needs an Entra token; with a personal access token alone it cannot mint one (az's words are
    hand-written here: the capture signed in with Entra). The read fails, says the identity is unknown — so the host
    block reads `unknown`, not `signed_out` — and nothing stands in for the person."""
    import host_report
    az.fail["_apis/connectionData"] = stderr
    with pytest.raises(AdoImportError) as err:
        ado_wit.connection_data(tmp_path)
    text = str(err.value)
    assert text.startswith("core/connectionData (az rest): ") and ado_transport.REST_NO_TOKEN in text
    assert "az login" not in text and "@" not in text
    assert host_report.cli_state_from_error("az", text)[0] == "unknown"
    assert [route_key_boards(c) for c in az.calls] == ["GET core/connectionData"]   # asked once, never retried


def test_a_not_materialized_identity_keeps_its_own_words_and_hint(az, tmp_path):
    az.fail["_apis/connectionData"] = f"ERROR: Identity has not been materialized\n{ado_transport.MATERIALIZED_HINT}"
    with pytest.raises(AdoImportError, match="materialized") as err:
        ado_wit.connection_data(tmp_path)
    assert ado_transport.REST_NO_TOKEN not in str(err.value)


def test_az_rest_reads_only_the_allow_listed_path_at_an_allowed_version(az, tmp_path):
    for path in ("_apis/projects", "_apis/connectionData/../projects", "https://elsewhere/_apis/connectionData"):
        with pytest.raises(AdoImportError, match="reads only"):
            ado_transport.rest_get(tmp_path, path)
    for version in ("7.1-preview.1", "5.0"):
        with pytest.raises(AdoImportError):
            ado_transport.rest_get(tmp_path, "_apis/connectionData", api_version=version)
    assert az.calls == []                                    # refused before az was asked
    assert ado_transport.REST_READS == frozenset({"_apis/connectionData"})
    assert ado_transport.rest_argv("https://dev.azure.com/contoso/", "_apis/connectionData") == identity_rest_argv(ORG)
    assert "--method" in identity_rest_argv() and identity_rest_argv()[identity_rest_argv().index("--method") + 1] == "get"


def test_the_captured_refusals_are_what_the_rest_read_and_its_version_avoid():
    from tests.ado_boards_fixtures import load_wit_error
    assert load_wit_error("connection_data_core") == "ERROR: --resource and --api-version combination is not correct"
    assert load_wit_error("connection_data_location") == "ERROR: --area is not present in current organization"
    assert "-preview flag must be supplied" in load_wit_error("connection_data_rest_7.1")
    assert boards_contract.REST_ROUTES["connection_data"]["api_version"] == PREVIEW != ado_transport.API_VERSION


@pytest.mark.parametrize("reply", [[], {"authorizedUser": {}}, 3], ids=["list", "no-authenticated-user", "number"])
def test_connection_data_raises_on_a_shape_it_does_not_know(az, tmp_path, reply):
    az.answers["GET core/connectionData"] = reply
    with pytest.raises(AdoImportError):
        ado_wit.connection_data(tmp_path)


# --- the seam: every argv, every read, a read-only fake ---------------------------------------------------

def test_every_read_passes_a_read_only_fake(az, tmp_path):
    assert az.writes is False
    run_every_read(tmp_path)
    assert az.written() == []
    assert {route_key_boards(c) for c in az.calls} == {
        "boards query", "POST wit/workitemsbatch", "boards work-item show", "GET wit/updates", "GET wit/comments",
        "GET wit/commentsVersions", "GET core/connectionData"}


def test_every_recorded_argv_has_the_seam_shape(az, tmp_path):
    run_every_read(tmp_path)
    assert len(az.calls) >= 8
    assert [is_identity_rest_read(argv) for argv in az.calls].count(True) == 1   # B0: the identity read, once
    for argv in az.calls:
        assert argv[-2:] == ["-o", "json"] and "--only-show-errors" not in argv
        if is_identity_rest_read(argv):  # B0: the one `az rest` has no --detect or --org (its URL names the org)
            continue
        assert argv[argv.index("--detect") + 1] == "false", argv
        assert argv[argv.index("--org") + 1] == ORG
        assert "--repository" not in argv  # a work item is not in a repository
        assert not any(re.search(r"-preview\.\d", word) for word in argv)
        if argv[:2] == ["devops", "invoke"]:
            assert "--project" not in argv  # the project is a route parameter
            assert argv[argv.index("--api-version") + 1] in {ado_transport.API_VERSION, PREVIEW}


def test_the_reads_write_nothing_to_the_repository(az, tmp_path):
    run_every_read(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_corrected_route_is_followed_with_no_code_change(az, tmp_path, monkeypatch):
    """`WIT_ROUTES` is the single point the B0 capture corrects; the reads follow it."""
    monkeypatch.setitem(boards_contract.WIT_ROUTES, "updates",
                        {**boards_contract.WIT_ROUTES["updates"], "resource": "revisions"})
    monkeypatch.setitem(boards_contract.WIT_ROUTES, "comments",
                        {**boards_contract.WIT_ROUTES["comments"], "area": "wit2", "api_version": "7.1"})
    az.answers["GET wit/revisions"] = {"count": 1, "value": [{"rev": 8}]}
    az.answers["GET wit2/comments"] = {"totalCount": 0, "count": 0, "comments": []}
    assert ado_wit.updates_since(tmp_path, 4521, 7) == [{"rev": 8}]
    assert ado_wit.comments(tmp_path, 4521) == []
    assert [route_key_boards(c) for c in az.calls] == ["GET wit/revisions", "GET wit2/comments"]
    assert az.calls[1][az.calls[1].index("--api-version") + 1] == "7.1"


def test_a_route_that_needs_a_parameter_the_read_does_not_supply_is_an_error_not_a_guess(az, tmp_path, monkeypatch):
    monkeypatch.setitem(boards_contract.WIT_ROUTES, "updates",
                        {**boards_contract.WIT_ROUTES["updates"], "route": ("project", "id", "team")})
    with pytest.raises(AdoImportError, match="team"):
        ado_wit.updates_since(tmp_path, 4521, 0)
    assert az.calls == []


def test_a_failed_call_names_the_route_and_the_work_item(az, tmp_path):
    az.fail["resource comments"] = "TF401232: Work item 4521 does not exist"
    with pytest.raises(AdoImportError, match=r"wit/comments.*4521.*TF401232"):
        ado_wit.comments(tmp_path, 4521)


def test_a_failed_query_names_the_call(az, tmp_path):
    az.fail["boards query"] = "VS403403: not allowed"
    with pytest.raises(AdoImportError, match=r"boards query.*VS403403"):
        ado_wit.query_ids(tmp_path, WIQL)


# --- BOARDS_AZ_CONTRACT ----------------------------------------------------------------------------------

def shape(argv):
    """An argv with its run-specific values replaced by the contract's placeholders."""
    out, in_route, in_query = [], False, False
    for word in argv:
        if word == "--route-parameters":
            in_route, in_query = True, False
        elif word == "--query-parameters":
            in_route, in_query = False, True
        elif word.startswith("--"):
            in_route = in_query = False
        if in_route and "=" in word:
            word = word.partition("=")[0] + "="
        elif in_query and word.startswith("continuationToken="):
            word = "continuationToken=T"
        elif in_query and word.startswith("$skip="):
            word = "$skip=0"
        out.append(word)
    for flag, placeholder in (("--org", "U"), ("--project", "P"), ("--wiql", "Q"), ("--id", "N"), ("--in-file", "F")):
        if flag in out:
            out[out.index(flag) + 1] = placeholder
    if out[:1] == ["rest"]:  # B0: the identity read's organisation rides inside its --url
        out[out.index("--url") + 1] = out[out.index("--url") + 1].replace(ORG, "U", 1)
    return tuple(out)


def test_the_az_contract_matches_the_argv_the_reads_emit(az, tmp_path):
    run_every_read(tmp_path)
    emitted = {shape(c) for c in az.calls}
    contract = {shape(c) for c in ado_wit.BOARDS_AZ_CONTRACT}
    assert emitted == contract
    assert len(ado_wit.BOARDS_AZ_CONTRACT) == len(contract)  # no duplicate rows


def test_the_az_contract_is_read_only_and_never_pins_a_preview_revision():
    assert isinstance(ado_wit.BOARDS_AZ_CONTRACT, tuple) and ado_wit.BOARDS_AZ_CONTRACT
    for argv in ado_wit.BOARDS_AZ_CONTRACT:
        assert isinstance(argv, list) and all(isinstance(w, str) for w in argv)
        if argv[:1] == ["rest"]:  # B0: the one `az rest`, the identity read (it has no --detect flag)
            assert argv == identity_rest_argv("U") and argv is ado_wit.BOARDS_AZ_CONTRACT[-1], argv
            continue
        assert argv[argv.index("--detect") + 1] == "false", argv
        assert argv[-2:] == ["-o", "json"] and "--only-show-errors" not in argv
        assert "--repository" not in argv
        assert not any(re.search(r"-preview\.\d", word) for word in argv)
        if argv[:2] == ["devops", "invoke"]:
            assert argv[argv.index("--http-method") + 1] in {"GET", "POST"}
            if argv[argv.index("--http-method") + 1] == "POST":  # the one POST is the batch read
                assert argv[argv.index("--resource") + 1] == "workitemsbatch"
        else:
            assert argv[:2] in (["boards", "query"], ["boards", "work-item"])
            assert "create" not in argv and "update" not in argv


# --- the six write functions: B3 bodies, refused by a read-only fake ---------------------------------------

WRITES = [  # 4560 is the item the `workitem_update_response` fixture answers for
    ("create", ("User Story", [{"op": "add", "path": "/fields/System.Title", "value": "t"}])),
    ("update", (4560, [{"op": "test", "path": "/rev", "value": 7}])),
    ("add_comment", (4521, "text", "markdown")),
    ("add_history", (4560, 7, "<div>x</div>")),
    ("list_recent_comments", (4521,)),
    ("link_pr", (12, 4521)),
]
WRITING = [(n, a) for n, a in WRITES if n != "list_recent_comments"]  # the recovery re-list is a GET


@pytest.mark.parametrize("name, args", WRITING, ids=[n for n, _ in WRITING])
def test_a_write_function_is_refused_by_a_read_only_fake_and_goes_through_a_writing_one(monkeypatch, tmp_path,
                                                                                         name, args):
    refusing = FakeBoardsAz(writes=False)
    monkeypatch.setattr(ado_transport, "run_az", refusing)
    with pytest.raises(AssertionError, match="unexpected az write: "):
        getattr(ado_wit, name)(tmp_path, *args)
    assert len(refusing.calls) == 1 and refusing.written() == refusing.calls  # the one write, refused, not retried
    writing = FakeBoardsAz({"repos pr work-item add": []}, writes=True)  # B3-P1's tests pin what each one returns
    monkeypatch.setattr(ado_transport, "run_az", writing)
    getattr(ado_wit, name)(tmp_path, *args)
    assert len(writing.calls) == 1 and writing.written() == writing.calls  # the write went through


def test_list_recent_comments_is_the_one_read_among_the_six_and_a_read_only_fake_passes_it(az, tmp_path):
    assert not az.writes
    assert isinstance(ado_wit.list_recent_comments(tmp_path, 4521), list)
    assert len(az.calls) == 1 and az.written() == []


def test_the_write_stubs_keep_the_pinned_signatures():
    expect = {"create": ["repo_root", "type_name", "patch"], "update": ["repo_root", "wid", "patch"],
              "add_comment": ["repo_root", "wid", "text", "fmt"], "add_history": ["repo_root", "wid", "rev", "html"],
              "list_recent_comments": ["repo_root", "wid"], "link_pr": ["repo_root", "pr_id", "wid"]}
    for name, params in expect.items():
        assert list(inspect.signature(getattr(ado_wit, name)).parameters) == params
    reads = {"find_by_ref": ["repo_root", "ref"], "query_ids": ["repo_root", "wiql"], "get_batch": ["repo_root", "ids"],
             "updates_since": ["repo_root", "wid", "rev"], "comments": ["repo_root", "wid"],
             "comment_versions": ["repo_root", "wid", "comment_id"], "connection_data": ["repo_root"]}
    for name, params in reads.items():
        assert list(inspect.signature(getattr(ado_wit, name)).parameters) == params


# --- what the module is allowed to be ----------------------------------------------------------------------

SOURCE = inspect.getsource(ado_wit)


def test_the_module_imports_no_subprocess_and_reaches_az_only_through_the_seam():
    imported = set()
    for node in ast.walk(ast.parse(SOURCE)):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    # `ado_wit_map` (pure: `classify_write_error`) is imported by the B3 write bodies, inside the functions.
    assert imported <= {"sys", "pathlib", "ado_transport", "ado_map", "boards_contract", "ado_wit_map"}, imported
    assert "subprocess" not in imported
    assert "run_az" not in SOURCE  # only invoke_body and az_json, which own the spawn
    assert not re.search(r"shell\s*=\s*True|shlex\.join", SOURCE)


def test_the_module_never_names_a_preview_revision_or_a_write_only_flag():
    assert not re.search(r"-preview\.\d", SOURCE)
    for word in ("suppressNotifications", "bypassRules", "validateOnly"):
        assert word not in SOURCE


def test_the_interface_sheet_names_are_all_there():
    for name in ("BOARDS_AZ_CONTRACT", "find_by_ref", "query_ids", "get_batch", "updates_since", "comments",
                 "comment_versions", "connection_data", "create", "update", "add_comment", "add_history",
                 "list_recent_comments", "link_pr"):
        assert hasattr(ado_wit, name), name


# --- Fold B5 (B5-P2): the watermark feed is a read of the same kind, in its own module ----------------------------
# `ado_wit_feed` (its own tests: `test_boards_wit_feed.py`) pages `reporting/workItemRevisions`; it is not one of
# `ado_wit`'s reads and adds no row to `BOARDS_AZ_CONTRACT`, but it keeps the rules every read here keeps.

import ado_wit_feed  # noqa: E402

FEED_ROUTE_KEY = "GET wit/workItemRevisions"


def test_the_feed_read_keeps_the_seam_rules_every_read_here_keeps(az, tmp_path):
    ado_wit_feed.revisions_since(tmp_path, None)
    ado_wit_feed.revisions_since(tmp_path, "token:T1")
    assert az.writes is False and az.written() == []
    assert {route_key_boards(c) for c in az.calls} == {FEED_ROUTE_KEY} and len(az.calls) == 2
    for argv in az.calls:
        assert argv[argv.index("--detect") + 1] == "false", argv
        assert argv[argv.index("--org") + 1] == ORG
        assert argv[-2:] == ["-o", "json"] and "--only-show-errors" not in argv
        assert "--repository" not in argv and "--project" not in argv
        assert not any(re.search(r"-preview\.\d", word) for word in argv)
        assert argv[argv.index("--api-version") + 1] in {ado_transport.API_VERSION, PREVIEW}
        assert route_params(argv) == {"project": PROJECT}
    assert list(tmp_path.iterdir()) == []  # reading stores nothing; the caller saves the watermark


def test_the_feed_route_is_a_read_row_of_the_contract():
    row = boards_contract.WIT_ROUTES["workitemrevisions"]
    assert row["method"] == "GET" and row["method"] not in boards_contract.WRITE_METHODS
    assert (row["area"], row["resource"]) not in boards_contract.READ_POSTS


def test_the_feed_module_names_are_all_there():
    for name in ("revisions_since", "feed_page", "load_watermark", "save_watermark", "RevisionList", "FEED_START",
                 "FEED_FIELDS", "MAX_FEED_PAGES", "WATERMARK_FILE"):
        assert hasattr(ado_wit_feed, name), name
