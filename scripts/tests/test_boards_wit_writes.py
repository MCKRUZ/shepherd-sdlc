"""B3-P1 — the work-item writes (`ado_wit`): create, update, comment, history, recovery re-list, PR link.

What this pins, and why each line exists (build kit §5 card B3-P1; house rules 2, 9, 10, 11; guardrails 2, 7, 8, 10):
  * `create` is `POST wit/workItems` (route `project=<P> type=<Type>`, bare since B0 2026-10-14), `update` is
    `PATCH wit/workItems` — since the B0 write fixes (2026-10-15) as `az rest --method patch` of
    `<org>/<P>/_apis/wit/workitems/<N>`, because `devops invoke` binds the `${type}` location for a PATCH and dies —
    both `application/json-patch+json` at `API_VERSION`, both answering `{id, rev}` and nothing else (the board's
    reply names people: it never rides out of this module);
  * an `update` patch always begins with `test /rev` (optimistic concurrency) — a patch that does not is refused
    before a call is made, and `add_history` is the same PATCH with `[test /rev, add /fields/System.History]`;
  * `add_comment` is `POST wit/comments` (route `project=<P> workItemId=<N>`), `--query-parameters format=markdown`,
    `application/json` `{"text": ...}`, at `PREVIEW_API_VERSION` — and the text rides in the request BODY only, never
    in an argv element; `list_recent_comments` is the recovery re-list `order=desc $top=20` (a read);
  * `link_pr` is the native `az repos pr work-item add --id <pr> --work-items <wid>` through `az_json`;
  * a failed write is an `AdoImportError` carrying `error_class` — what `ado_wit_map.classify_write_error` reads its
    stderr as (`conflict` for the stale `test /rev`, `rule`, `permission`, `throttled`, `not_found`, else `unknown`);
    an answer this module cannot read after the board said yes is `unknown` too (the write may have landed);
  * a fake with `writes=False` makes every write raise `AssertionError("unexpected az write")` — and nothing in this
    module swallows it — while the one read in the six (`list_recent_comments`) passes;
  * every recorded argv carries `--detect false`, ends `-o json`, never holds `--only-show-errors` (the seam adds it)
    or a `-preview.<digit>` string, and none of the flags a write must never send;
  * every location comes from `boards_contract.WIT_ROUTES`, the one B0 correction point.

Nothing here spawns `az`: `boards_env` forbids it at the seam; `az` and `wr` swap a `FakeBoardsAz` in for `run_az`.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import HAND_WRITTEN_PROCESS
from tests.ado_boards_fixtures import FakeBoardsAz, load_wit, load_wit_error, route_key_boards, route_params
from tests.ado_boards_fixtures import body_file

import inspect
import json
import re
from pathlib import Path

import pytest

import ado_sync_model
import ado_transport
import ado_wit
import ado_wit_map
import boards_contract
from ado_map import AdoImportError

# B0 (2026-10-15): the second capture shadowed the item, write and comment fixtures (`WIT_CAPTURED_ITEMS`); this module's
# scenarios pin the hand-written ones' ids and texts, so it reads those (`BOARDS_ITEMS`, tests/ado_boards_fixtures.py).
# The captured answers are exercised in test_boards_captured_items.py.
BOARDS_ITEMS = HAND_WRITTEN_PROCESS

ORG = "https://dev.azure.com/contoso"  # what tests.ado_fixtures.ADO_REMOTE parses to
PROJECT = "Claims"
PREVIEW = ado_transport.PREVIEW_API_VERSION
GA = ado_transport.API_VERSION

CREATE_PATCH = [{"op": "add", "path": "/fields/System.Title", "value": "t"},
                {"op": "add", "path": "/fields/System.Tags", "value": "sdlc:spec:0004"}]
UPDATE_PATCH = [{"op": "test", "path": "/rev", "value": 1},
                {"op": "replace", "path": "/fields/System.Title", "value": "probe title"}]
HOSTILE = '"quoted" \\ back\nnew line $(touch x) ✓ -- --flag `tick` é中'


# --- helpers ---------------------------------------------------------------------------------------------

@pytest.fixture
def wr(monkeypatch) -> FakeBoardsAz:
    """A fake that answers writes (`writes=True`) from the B3-P0 fixtures. `link_pr` has no fixture (B0 has not
    captured what `az repos pr work-item add` prints) and ignores the reply, so it is answered with an empty list."""
    fake = FakeBoardsAz({"repos pr work-item add": []}, writes=True)
    monkeypatch.setattr(ado_transport, "run_az", fake)
    return fake


def spy(seen: list, answer):
    """An answer that records the request body (read from the `--in-file`, or since the B0 write fixes the `az rest`
    `--body @<file>`, the seam wrote) and the argv, then answers `answer` (a fixture name or a document)."""
    def answer_with(args):
        path = Path(body_file(args))
        seen.append({"argv": args, "path": path, "body": json.loads(path.read_text(encoding="utf-8"))})
        return answer
    return answer_with


def arg_after(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def words_after(argv: list[str], flag: str) -> list[str]:
    out = []
    for word in argv[argv.index(flag) + 1:]:
        if word.startswith("--"):
            break
        out.append(word)
    return out


WRITE_CALLS = {
    "create": lambda repo: ado_wit.create(repo, "User Story", CREATE_PATCH),
    "update": lambda repo: ado_wit.update(repo, 4560, UPDATE_PATCH),
    "add_comment": lambda repo: ado_wit.add_comment(repo, 4521, "a fact · sprd 0123456789ab", "markdown"),
    "add_history": lambda repo: ado_wit.add_history(repo, 4560, 1, "<div>sprd · created</div>"),
    "link_pr": lambda repo: ado_wit.link_pr(repo, 12, 4521),
}
WRITE_NAMES = list(WRITE_CALLS)
# the needle in the joined argv that makes the fake raise, per write (`fail=` matches on it); an update is `az rest`
# since the B0 write fixes (2026-10-15: `devops invoke` cannot PATCH a work item)
FAIL_NEEDLE = {"create": "devops invoke", "update": "rest --method patch", "add_comment": "devops invoke",
               "add_history": "rest --method patch", "link_pr": "work-item add"}


def run_every_write(repo) -> None:
    for call in WRITE_CALLS.values():
        call(repo)
    ado_wit.list_recent_comments(repo, 4521)


# --- create ----------------------------------------------------------------------------------------------

def test_create_is_a_post_of_a_json_patch_to_wit_workitems_and_returns_id_and_rev(wr, tmp_path):
    seen: list = []
    wr.answers["POST wit/workItems"] = spy(seen, "workitem_create_response")
    out = ado_wit.create(tmp_path, "Task", CREATE_PATCH)
    assert out == {"id": 4560, "rev": 1}  # nothing else: the reply's CreatedBy/ChangedBy name people
    argv = seen[0]["argv"]
    # bare: the extension's template is `{project}/_apis/wit/workItems/${type}` (B0, 2026-10-14: `$Task` 404ed)
    assert argv[:argv.index("--in-file")] == ["devops", "invoke", "--area", "wit", "--resource", "workItems",
                                              "--route-parameters", f"project={PROJECT}", "type=Task",
                                              "--http-method", "POST"]
    assert argv[argv.index("--in-file") + 2:] == ["--media-type", "application/json-patch+json",
                                                  "--api-version", GA, "--detect", "false", "--org", ORG,
                                                  "-o", "json"]
    assert seen[0]["body"] == CREATE_PATCH
    assert wr.written() == [argv] and len(wr.calls) == 1


def test_create_keeps_a_type_name_with_spaces_as_one_route_parameter(wr, tmp_path):
    seen: list = []
    wr.answers["POST wit/workItems"] = spy(seen, "workitem_create_response")
    ado_wit.create(tmp_path, "Product Backlog Item", CREATE_PATCH)
    assert words_after(seen[0]["argv"], "--route-parameters") == [f"project={PROJECT}", "type=Product Backlog Item"]
    assert route_params(seen[0]["argv"])["type"] == "Product Backlog Item"


@pytest.mark.parametrize("type_name", ["", "   ", None, 7, "$Task", "a/b", "a\\b", "a?b", "a#b", "a%b", "a\nb", "a\x00b"])
def test_create_refuses_a_type_name_that_cannot_ride_in_a_route_before_calling(wr, tmp_path, type_name):
    with pytest.raises(ValueError):
        ado_wit.create(tmp_path, type_name, CREATE_PATCH)
    assert wr.calls == []


@pytest.mark.parametrize("patch", [[], None, {}, "x", [{"op": "add"}, "x"]])
def test_create_refuses_a_patch_that_is_not_a_list_of_operations_before_calling(wr, tmp_path, patch):
    with pytest.raises(ValueError):
        ado_wit.create(tmp_path, "Task", patch)
    assert wr.calls == []


@pytest.mark.parametrize("reply", [{"rev": 1}, {"id": 4560}, {"id": "4560", "rev": 1}, {"id": 4560, "rev": True},
                                   {"id": True, "rev": 1}, [], {"fields": {}}])
def test_create_reads_its_reply_only_through_require_and_a_bad_one_is_an_unknown_outcome(wr, tmp_path, reply):
    wr.answers["POST wit/workItems"] = reply
    with pytest.raises(AdoImportError, match="unexpected az shape") as info:
        ado_wit.create(tmp_path, "Task", CREATE_PATCH)
    assert info.value.error_class == "unknown"  # the board said yes: the item may exist


def test_create_with_an_empty_reply_is_an_unknown_outcome_not_a_success(wr, tmp_path):
    wr.answers["POST wit/workItems"] = None
    with pytest.raises(AdoImportError, match="empty response on write") as info:
        ado_wit.create(tmp_path, "Task", CREATE_PATCH)
    assert info.value.error_class == "unknown"


# --- update ----------------------------------------------------------------------------------------------

def test_update_is_a_patch_of_a_json_patch_that_begins_with_test_rev(wr, tmp_path):
    seen: list = []
    wr.answers["PATCH wit/workItems"] = spy(seen, "workitem_update_response")
    out = ado_wit.update(tmp_path, 4560, UPDATE_PATCH)
    assert out == {"id": 4560, "rev": 2}
    argv = seen[0]["argv"]
    # B0 write fixes (2026-10-15): `az rest`, not `devops invoke` (which binds `…/workItems/${type}` for a PATCH and
    # dies with `ERROR: 'type'`); no `--detect` (az rest has no such flag), the body as `--body @<file>`
    assert argv == ["rest", "--method", "patch", "--resource", boards_contract.ADO_RESOURCE_ID, "--url",
                    f"{ORG}/{PROJECT}/_apis/wit/workitems/4560?api-version={GA}",
                    "--headers", "Content-Type=application/json-patch+json", "--body", f"@{seen[0]['path']}",
                    "-o", "json"]
    assert seen[0]["body"] == UPDATE_PATCH
    assert seen[0]["body"][0] == {"op": "test", "path": "/rev", "value": 1}
    assert route_key_boards(argv) == "PATCH wit/workItems" and route_params(argv) == {"project": PROJECT, "id": "4560"}
    assert not any(a[:2] == ["devops", "invoke"] for a in wr.calls)


@pytest.mark.parametrize("patch", [
    [],
    [{"op": "replace", "path": "/fields/System.Title", "value": "t"}],                                  # no test op at all
    [{"op": "replace", "path": "/fields/System.Title", "value": "t"}, {"op": "test", "path": "/rev", "value": 1}],  # not first
    [{"op": "test", "path": "/fields/System.Title", "value": "t"}],                                     # a test, not of /rev
    [{"op": "replace", "path": "/rev", "value": 1}],                                                    # /rev, not a test
    [{"op": "test", "path": "/rev", "value": "1"}],                                                     # a revision is an integer
    [{"op": "test", "path": "/rev", "value": True}],
    [{"op": "test", "path": "/rev"}],
    [{"op": "test", "path": "/rev", "value": 0}],
    None, "x", [None],
])
def test_update_refuses_a_patch_that_does_not_begin_with_test_rev_before_calling(wr, tmp_path, patch):
    with pytest.raises(ValueError):
        ado_wit.update(tmp_path, 4560, patch)
    assert wr.calls == []


@pytest.mark.parametrize("wid", [0, -1, True, "4560", None, 4.0])
def test_update_refuses_an_id_that_is_not_a_positive_integer_before_calling(wr, tmp_path, wid):
    with pytest.raises(ValueError):
        ado_wit.update(tmp_path, wid, UPDATE_PATCH)
    assert wr.calls == []


def test_update_with_a_reply_for_another_item_is_an_unknown_outcome(wr, tmp_path):
    wr.answers["PATCH wit/workItems"] = {"id": 9999, "rev": 2}
    with pytest.raises(AdoImportError, match="unexpected az shape") as info:
        ado_wit.update(tmp_path, 4560, UPDATE_PATCH)
    assert info.value.error_class == "unknown"


@pytest.mark.parametrize("reply", [{"id": 4560}, {"rev": 2}, {"id": 4560, "rev": "2"}, {"id": "4560", "rev": 2}, []])
def test_update_reads_its_reply_only_through_require(wr, tmp_path, reply):
    wr.answers["PATCH wit/workItems"] = reply
    with pytest.raises(AdoImportError, match="unexpected az shape") as info:
        ado_wit.update(tmp_path, 4560, UPDATE_PATCH)
    assert info.value.error_class == "unknown"


# --- add_history -----------------------------------------------------------------------------------------

def test_add_history_is_the_patch_with_test_rev_then_add_system_history(wr, tmp_path):
    seen: list = []
    wr.answers["PATCH wit/workItems"] = spy(seen, "workitem_update_response")
    out = ado_wit.add_history(tmp_path, 4560, 1, "<div>sprd · created</div>")
    assert out == {"id": 4560, "rev": 2}
    assert seen[0]["body"] == [{"op": "test", "path": "/rev", "value": 1},
                               {"op": "add", "path": "/fields/System.History", "value": "<div>sprd · created</div>"}]
    assert route_key_boards(seen[0]["argv"]) == "PATCH wit/workItems"
    assert route_params(seen[0]["argv"]) == {"project": PROJECT, "id": "4560"}


@pytest.mark.parametrize("rev, html", [(0, "<p>x</p>"), (-3, "<p>x</p>"), (True, "<p>x</p>"), ("1", "<p>x</p>"),
                                       (None, "<p>x</p>"), (1, ""), (1, "   "), (1, None), (1, 7)])
def test_add_history_refuses_a_bad_revision_or_text_before_calling(wr, tmp_path, rev, html):
    with pytest.raises(ValueError):
        ado_wit.add_history(tmp_path, 4560, rev, html)
    assert wr.calls == []


def test_add_history_stale_revision_is_a_conflict(wr, tmp_path):
    wr.fail["rest --method patch"] = load_wit_error("stale_rev")   # captured 2026-10-15: `Precondition Failed … VS403351`
    with pytest.raises(AdoImportError) as info:
        ado_wit.add_history(tmp_path, 4560, 1, "<p>x</p>")
    assert info.value.error_class == "conflict"


# --- add_comment -----------------------------------------------------------------------------------------

def test_add_comment_is_a_post_to_wit_comments_at_the_preview_version(wr, tmp_path):
    seen: list = []
    wr.answers["POST wit/comments"] = spy(seen, "comment_add_response")
    out = ado_wit.add_comment(tmp_path, 4521, "probe from sdlc · sprd 000000000000", "markdown")
    assert out == {"comment_id": 504, "version": 1}
    argv = seen[0]["argv"]
    assert argv[:argv.index("--in-file")] == ["devops", "invoke", "--area", "wit", "--resource", "comments",
                                              "--route-parameters", f"project={PROJECT}", "workItemId=4521",
                                              "--http-method", "POST"]
    assert argv[argv.index("--in-file") + 2:] == ["--media-type", "application/json",
                                                  "--query-parameters", "format=markdown",
                                                  "--api-version", PREVIEW, "--detect", "false", "--org", ORG,
                                                  "-o", "json"]
    assert seen[0]["body"] == {"text": "probe from sdlc · sprd 000000000000"}


def test_add_comment_html_is_the_other_format_the_board_knows(wr, tmp_path):
    seen: list = []
    wr.answers["POST wit/comments"] = spy(seen, "comment_add_response")
    ado_wit.add_comment(tmp_path, 4521, "<p>x</p>", "html")
    assert words_after(seen[0]["argv"], "--query-parameters") == ["format=html"]


@pytest.mark.parametrize("fmt", ["", "md", "Markdown", "text", None, 1])
def test_add_comment_refuses_a_format_the_board_does_not_know_before_calling(wr, tmp_path, fmt):
    with pytest.raises(ValueError):
        ado_wit.add_comment(tmp_path, 4521, "x", fmt)
    assert wr.calls == []


@pytest.mark.parametrize("text", ["", "   \n", None, 7, ["x"]])
def test_add_comment_refuses_an_empty_or_non_text_comment_before_calling(wr, tmp_path, text):
    with pytest.raises(ValueError):
        ado_wit.add_comment(tmp_path, 4521, text, "markdown")
    assert wr.calls == []


@pytest.mark.parametrize("wid", [0, -1, True, "4521", None])
def test_add_comment_refuses_an_id_that_is_not_a_positive_integer_before_calling(wr, tmp_path, wid):
    with pytest.raises(ValueError):
        ado_wit.add_comment(tmp_path, wid, "x", "markdown")
    assert wr.calls == []


def test_add_comment_text_rides_in_the_request_body_never_in_an_argv_element(wr, tmp_path):
    seen: list = []
    wr.answers["POST wit/comments"] = spy(seen, "comment_add_response")
    ado_wit.add_comment(tmp_path, 4521, HOSTILE, "markdown")
    assert seen[0]["body"] == {"text": HOSTILE}  # the quotes, newline, `$(`, non-ASCII and `--flag` all arrive intact
    for word in seen[0]["argv"]:
        assert HOSTILE not in word and "$(touch" not in word and "touch x" not in word
    assert "--flag" not in seen[0]["argv"]  # the text's own `--flag` is body content, not an option


def test_add_comment_text_that_starts_with_a_dash_is_still_only_body(wr, tmp_path):
    seen: list = []
    wr.answers["POST wit/comments"] = spy(seen, "comment_add_response")
    ado_wit.add_comment(tmp_path, 4521, "--help me", "markdown")
    assert seen[0]["body"] == {"text": "--help me"} and "--help me" not in seen[0]["argv"]


@pytest.mark.parametrize("reply", [{"version": 1}, {"id": 504}, {"id": "504", "version": 1}, {"id": 504, "version": "1"},
                                   {"id": 504, "version": False}, []])
def test_add_comment_reads_its_reply_only_through_require_and_a_bad_one_is_unknown(wr, tmp_path, reply):
    wr.answers["POST wit/comments"] = reply
    with pytest.raises(AdoImportError, match="unexpected az shape") as info:
        ado_wit.add_comment(tmp_path, 4521, "x", "markdown")
    assert info.value.error_class == "unknown"  # the board said yes: the comment may be there (recover by re-list)


def test_add_comment_error_never_carries_the_comment_text(wr, tmp_path):
    wr.fail["devops invoke"] = load_wit_error("permission")
    with pytest.raises(AdoImportError) as info:
        ado_wit.add_comment(tmp_path, 4521, HOSTILE, "markdown")
    assert "touch x" not in str(info.value) and "new line" not in str(info.value)
    assert info.value.error_class == "permission"


# --- list_recent_comments --------------------------------------------------------------------------------

def test_list_recent_comments_is_the_newest_twenty_first(az, tmp_path):
    rows = ado_wit.list_recent_comments(tmp_path, 4521)
    assert [c["id"] for c in rows] == [504, 502, 501]  # as the board sent them: newest first, nothing dropped
    assert len(az.calls) == 1
    argv = az.calls[0]
    assert argv == ["devops", "invoke", "--area", "wit", "--resource", "comments", "--route-parameters",
                    f"project={PROJECT}", "workItemId=4521", "--http-method", "GET",
                    "--query-parameters", "order=desc", "$top=20", "--api-version", PREVIEW,
                    "--detect", "false", "--org", ORG, "-o", "json"]
    assert az.written() == []  # a read: a `writes=False` fake passes it


def test_list_recent_comments_asks_what_the_recovery_rule_reads(az, tmp_path):
    ado_wit.list_recent_comments(tmp_path, 4521)
    asked = dict(word.partition("=")[::2] for word in words_after(az.calls[0], "--query-parameters"))
    assert asked == ado_sync_model.RECENT_COMMENTS_QUERY


def test_list_recent_comments_returns_what_the_board_sent_unredacted(az, tmp_path):
    rows = ado_wit.list_recent_comments(tmp_path, 4521)
    sent = load_wit("comments_recent")["comments"][0]
    assert rows[0]["createdBy"]["id"] == sent["createdBy"]["id"]  # recovery needs the author's id
    assert rows[0]["text"] == sent["text"]


def test_list_recent_comments_of_an_item_with_none_is_an_empty_list(az, tmp_path):
    az.answers["GET wit/comments order=desc"] = {"count": 0, "totalCount": 0, "comments": []}
    assert ado_wit.list_recent_comments(tmp_path, 4521) == []


@pytest.mark.parametrize("reply", [{"count": 1}, {"comments": "x"}, {"value": []}, []])
def test_list_recent_comments_reads_its_reply_only_through_require(az, tmp_path, reply):
    az.answers["GET wit/comments order=desc"] = reply
    with pytest.raises(AdoImportError, match="unexpected az shape"):
        ado_wit.list_recent_comments(tmp_path, 4521)


@pytest.mark.parametrize("wid", [0, True, "4521", None])
def test_list_recent_comments_refuses_a_bad_id_before_calling(az, tmp_path, wid):
    with pytest.raises(ValueError):
        ado_wit.list_recent_comments(tmp_path, wid)
    assert az.calls == []


def test_list_recent_comments_failure_names_the_call(az, tmp_path):
    az.fail["devops invoke"] = "ERROR: boom"
    with pytest.raises(AdoImportError, match=r"wit/comments \(work item 4521\): ERROR: boom"):
        ado_wit.list_recent_comments(tmp_path, 4521)


# --- link_pr ---------------------------------------------------------------------------------------------

def test_link_pr_is_the_native_repos_pr_work_item_add(wr, tmp_path):
    assert ado_wit.link_pr(tmp_path, 12, 4521) is None
    assert wr.calls == [["repos", "pr", "work-item", "add", "--id", "12", "--work-items", "4521",
                         "--detect", "false", "--org", ORG, "-o", "json"]]
    assert route_key_boards(wr.calls[0]) == "repos pr work-item add"
    assert wr.written() == wr.calls


def test_link_pr_takes_the_pr_by_id_alone_not_by_project_or_repository(wr, tmp_path):
    # a PR id is organisation-wide, as `az repos pr update --id` already treats it: `--org`, not `--project`
    ado_wit.link_pr(tmp_path, 12, 4521)
    assert "--project" not in wr.calls[0] and "--repository" not in wr.calls[0]


@pytest.mark.parametrize("pr_id, wid", [(0, 4521), (4521, 0), (True, 4521), (12, True), ("12", 4521), (12, "4521"),
                                        (None, 4521), (12, None), (-1, 4521)])
def test_link_pr_refuses_an_id_that_is_not_a_positive_integer_before_calling(wr, tmp_path, pr_id, wid):
    with pytest.raises(ValueError):
        ado_wit.link_pr(tmp_path, pr_id, wid)
    assert wr.calls == []


def test_link_pr_failure_names_the_call_and_carries_the_class(wr, tmp_path):
    wr.fail["work-item add"] = load_wit_error("permission")
    with pytest.raises(AdoImportError, match=r"repos pr work-item add \(PR 12, work item 4521\)") as info:
        ado_wit.link_pr(tmp_path, 12, 4521)
    assert info.value.error_class == "permission"


# --- a failed write carries the class its stderr reads as ------------------------------------------------

@pytest.mark.parametrize("name", ["stale_rev", "rule_violation", "permission", "throttled"])
@pytest.mark.parametrize("write", WRITE_NAMES)
def test_a_failed_write_is_an_adoimporterror_carrying_the_class_of_its_stderr(wr, tmp_path, write, name):
    text = load_wit_error(name)
    wr.fail[FAIL_NEEDLE[write]] = text
    expected = {"stale_rev": "conflict", "rule_violation": "rule", "permission": "permission",
                "throttled": "throttled"}[name]
    assert ado_wit_map.classify_write_error(text) == expected  # the fixture and the classifier agree
    with pytest.raises(AdoImportError) as info:
        WRITE_CALLS[write](tmp_path)
    err = info.value
    assert err.error_class == expected and err.error_class in ado_wit_map.ERROR_CLASSES
    assert f"[{expected}]" in str(err) and text in str(err)  # a human still reads what the board said
    assert isinstance(err.__cause__, AdoImportError) and not hasattr(err.__cause__, "error_class")
    assert len(wr.calls) == 1  # one attempt: no retry on a write


def test_the_stale_revision_text_is_a_conflict_on_update(wr, tmp_path):
    wr.fail["rest --method patch"] = load_wit_error("stale_rev")
    with pytest.raises(AdoImportError, match=r"wit/workItems \(work item 4560\)") as info:
        ado_wit.update(tmp_path, 4560, UPDATE_PATCH)
    assert info.value.error_class == "conflict"


@pytest.mark.parametrize("write", WRITE_NAMES)
@pytest.mark.parametrize("message", [
    "`az devops invoke --area wit --resource workItems --route-parameters project=Claims id=7 --http-method PATCH "
    "--in-file <request body file> --media-type application/json-patch+json` timed out after 60s.",
    "ERROR: something nobody has seen before",
    "",
])
def test_a_failure_nothing_recognises_is_unknown_never_a_guess(wr, tmp_path, write, message):
    wr.fail[FAIL_NEEDLE[write]] = message
    with pytest.raises(AdoImportError) as info:
        WRITE_CALLS[write](tmp_path)
    assert info.value.error_class == "unknown"


def test_not_found_is_its_own_class(wr, tmp_path):
    wr.fail["rest --method patch"] = ("ERROR: TF401232: Work item 4560 does not exist, or you do not have permissions "
                                      "to read it.")
    with pytest.raises(AdoImportError) as info:
        ado_wit.update(tmp_path, 4560, UPDATE_PATCH)
    assert info.value.error_class == "not_found"


def test_the_error_is_a_plain_adoimporterror_so_existing_handlers_catch_it(wr, tmp_path):
    wr.fail["devops invoke"] = load_wit_error("throttled")
    with pytest.raises(AdoImportError) as info:
        ado_wit.create(tmp_path, "Task", CREATE_PATCH)
    assert type(info.value) is AdoImportError


def test_a_malformed_remote_is_refused_before_any_write_and_carries_no_class(wr, tmp_path, monkeypatch):
    import code_host
    monkeypatch.setattr(code_host, "origin_url", lambda root: "https://github.com/acme/widgets.git")
    ado_transport.clear_caches()
    with pytest.raises(AdoImportError, match="not an Azure DevOps remote") as info:
        ado_wit.create(tmp_path, "Task", CREATE_PATCH)
    assert not hasattr(info.value, "error_class") and wr.calls == []  # no write was attempted


# --- a read-only fake makes every write raise ------------------------------------------------------------

@pytest.mark.parametrize("write", WRITE_NAMES)
def test_with_writes_false_every_write_raises_and_is_not_swallowed(az, tmp_path, write):
    az.fail["devops invoke"] = "ERROR: would be classified"  # an AdoImportError must NOT be what comes out
    with pytest.raises(AssertionError, match="unexpected az write"):
        WRITE_CALLS[write](tmp_path)
    assert len(az.calls) == 1  # recorded, refused, and not retried
    assert az.written() == az.calls


@pytest.mark.parametrize("write", [w for w in WRITE_NAMES if w != "link_pr"])
def test_a_refused_write_leaves_no_request_body_file_behind(az, tmp_path, write):
    seen: list = []
    az.answers["POST wit/workItems"] = az.answers["PATCH wit/workItems"] = az.answers["POST wit/comments"] = (
        spy(seen, None))
    with pytest.raises(AssertionError, match="unexpected az write"):
        WRITE_CALLS[write](tmp_path)
    path = Path(body_file(az.calls[0]))   # `--in-file <path>`, or `az rest`'s `--body @<path>` for an update
    assert not path.exists()


@pytest.mark.parametrize("write", [w for w in WRITE_NAMES if w != "link_pr"])
def test_a_failed_write_leaves_no_request_body_file_behind(wr, tmp_path, write):
    wr.fail[FAIL_NEEDLE[write]] = load_wit_error("rule_violation")
    with pytest.raises(AdoImportError):
        WRITE_CALLS[write](tmp_path)
    assert not Path(body_file(wr.calls[0])).exists()


def test_a_successful_write_leaves_no_request_body_file_behind(wr, tmp_path):
    seen: list = []
    wr.answers["POST wit/workItems"] = spy(seen, "workitem_create_response")
    ado_wit.create(tmp_path, "Task", CREATE_PATCH)
    assert not seen[0]["path"].exists()


def test_the_only_read_among_the_six_passes_a_read_only_fake(az, tmp_path):
    ado_wit.list_recent_comments(tmp_path, 4521)
    assert az.written() == [] and az.count("devops", "invoke") == 1


# --- argv invariants over everything the six issue -------------------------------------------------------

FORBIDDEN_WORDS = ("suppressNotifications", "bypassRules", "validateOnly", "reactions", "attachments", "graph/",
                   "notification")


def _is_update_rest(argv: list[str]) -> bool:
    """B0 write fixes: the one `az rest` write, the update PATCH of `<ORG>/<project>/_apis/wit/workitems/<id>`."""
    return (argv[:4] == ["rest", "--method", "patch", "--resource"] and arg_after(argv, "--resource")
            == boards_contract.ADO_RESOURCE_ID and arg_after(argv, "--url").startswith(f"{ORG}/{PROJECT}/_apis/wit/"
                                                                                       "workitems/")
            and arg_after(argv, "--url").endswith(f"?api-version={GA}"))


def test_every_argv_the_six_emit_carries_detect_false_ends_json_and_never_a_preview_revision(wr, tmp_path):
    run_every_write(tmp_path)
    assert len(wr.calls) == 6
    for argv in wr.calls:
        assert argv[-2:] == ["-o", "json"]
        assert "--only-show-errors" not in argv  # `run_az` appends it; a fake standing in for it never sees it
        joined = " ".join(argv)
        assert not re.search(r"-preview\.\d", joined)
        assert not any(word in joined for word in FORBIDDEN_WORDS)
        assert "--repository" not in argv and "--project" not in argv  # the project is a route parameter, never a flag
        if argv[0] == "rest":   # `az rest` has no --detect and no --org: the URL names the organisation
            assert _is_update_rest(argv), argv
            continue
        assert argv[argv.index("--detect") + 1] == "false"
        assert arg_after(argv, "--org") == ORG
        if "--api-version" in argv:
            assert arg_after(argv, "--api-version") in (GA, PREVIEW)
    assert sum(1 for argv in wr.calls if argv[0] == "rest") == 2   # the update and the History entry


def test_no_write_patches_or_deletes_a_comment_and_none_deletes_anything(wr, tmp_path):
    run_every_write(tmp_path)
    for argv in wr.calls:
        if "--http-method" in argv:
            method = arg_after(argv, "--http-method")
            assert method in ("GET", "POST", "PATCH")
            assert not (arg_after(argv, "--resource") == "comments" and method in ("PATCH", "PUT", "DELETE"))
        if argv[0] == "rest":
            assert arg_after(argv, "--method") == "patch" and "comments" not in arg_after(argv, "--url").lower()
    assert not any("delete" in " ".join(argv).lower() for argv in wr.calls)
    # no write PATCHes a work item through `devops invoke`, which binds `…/workItems/${type}` and crashes (B0)
    assert not any(argv[:2] == ["devops", "invoke"] and "PATCH" in argv for argv in wr.calls)


def test_the_six_issue_exactly_these_route_keys(wr, tmp_path):
    run_every_write(tmp_path)
    assert [route_key_boards(c) for c in wr.calls] == ["POST wit/workItems", "PATCH wit/workItems", "POST wit/comments",
                                                       "PATCH wit/workItems", "repos pr work-item add",
                                                       "GET wit/comments"]


def test_the_write_argv_never_names_a_person_or_a_guid(wr, tmp_path):
    run_every_write(tmp_path)
    for argv in wr.calls:
        for i, word in enumerate(argv):
            if argv[0] == "rest" and i and argv[i - 1] == "--resource":
                assert word == boards_contract.ADO_RESOURCE_ID   # the fixed Entra resource id: vocabulary, not a person
                continue
            assert not boards_contract.EMAIL_RE.search(word) and not boards_contract.GUID_RE.search(word)


# --- the locations come from WIT_ROUTES ------------------------------------------------------------------

@pytest.mark.parametrize("row, call, key, reply", [
    ("workitem_create", lambda repo: ado_wit.create(repo, "Task", CREATE_PATCH), "POST wit/corrected",
     {"id": 4560, "rev": 1}),
    ("comments", lambda repo: ado_wit.add_comment(repo, 4521, "x", "markdown"), "POST wit/corrected",
     {"id": 504, "version": 1}),
    ("comments", lambda repo: ado_wit.list_recent_comments(repo, 4521), "GET wit/corrected order=desc",
     {"comments": []}),
], ids=["create", "add_comment", "list_recent_comments"])
def test_a_corrected_wit_routes_row_is_followed_with_no_change_here(wr, tmp_path, monkeypatch, row, call, key, reply):
    monkeypatch.setitem(boards_contract.WIT_ROUTES, row, {**boards_contract.WIT_ROUTES[row], "resource": "corrected"})
    wr.answers[key] = reply
    call(tmp_path)
    assert arg_after(wr.calls[0], "--resource") == "corrected"


@pytest.mark.parametrize("call", [lambda repo: ado_wit.update(repo, 4560, UPDATE_PATCH),
                                  lambda repo: ado_wit.add_history(repo, 4560, 1, "<p>x</p>")],
                         ids=["update", "add_history"])
def test_a_corrected_rest_routes_row_is_followed_once_the_transport_allows_it(wr, tmp_path, monkeypatch, call):
    """B0 write fixes: an update's location is `REST_ROUTES["workitem_update"]` (an `az rest` URL), not the invoke row's
    resource; a corrected path is followed with no change in `ado_wit`, and only once `ado_transport.REST_WRITES`
    allow-lists it too (the transport sends no `az rest` PATCH it does not know)."""
    corrected = "{project}/_apis/wit/corrected/{id}"
    monkeypatch.setitem(boards_contract.REST_ROUTES, "workitem_update",
                        {**boards_contract.REST_ROUTES["workitem_update"], "path": corrected})
    with pytest.raises(AdoImportError, match="writes only"):
        call(tmp_path)
    assert wr.calls == []   # refused before any file or az call
    monkeypatch.setattr(ado_transport, "REST_WRITES", frozenset({corrected}))
    wr.answers["PATCH wit/workItems"] = {"id": 4560, "rev": 2}   # the harness names the corrected row the same
    call(tmp_path)
    assert arg_after(wr.calls[0], "--url") == f"{ORG}/{PROJECT}/_apis/wit/corrected/4560?api-version={GA}"


def test_add_comment_posts_whatever_method_the_read_row_says(wr, tmp_path, monkeypatch):
    # the `comments` row is the READ location; a POST of a new comment is the same resource with the method changed
    assert boards_contract.WIT_ROUTES["comments"]["method"] == "GET"
    seen: list = []
    wr.answers["POST wit/comments"] = spy(seen, "comment_add_response")
    ado_wit.add_comment(tmp_path, 4521, "x", "markdown")
    assert arg_after(seen[0]["argv"], "--http-method") == "POST"


def test_create_and_update_use_the_methods_and_route_names_of_their_rows(wr, tmp_path):
    create_row = boards_contract.WIT_ROUTES["workitem_create"]
    update_row = boards_contract.WIT_ROUTES["workitem_update"]
    assert (create_row["method"], create_row["route"]) == ("POST", ("project", "type"))
    assert (update_row["method"], update_row["route"]) == ("PATCH", ("project", "id"))
    assert create_row["api_version"] == update_row["api_version"] == GA


# --- what the module is allowed to be --------------------------------------------------------------------

SOURCE = inspect.getsource(ado_wit)


def test_no_write_function_is_a_stub_any_more():
    assert "raise NotImplementedError" not in SOURCE
    for name in ("create", "update", "add_comment", "add_history", "list_recent_comments", "link_pr"):
        assert "NotImplementedError" not in inspect.getsource(getattr(ado_wit, name))


def test_the_six_keep_their_pinned_signatures():
    expect = {"create": ["repo_root", "type_name", "patch"], "update": ["repo_root", "wid", "patch"],
              "add_comment": ["repo_root", "wid", "text", "fmt"], "add_history": ["repo_root", "wid", "rev", "html"],
              "list_recent_comments": ["repo_root", "wid"], "link_pr": ["repo_root", "pr_id", "wid"]}
    for name, params in expect.items():
        assert list(inspect.signature(getattr(ado_wit, name)).parameters) == params


def test_the_writes_reach_az_only_through_the_seam_and_never_shell_out():
    assert "run_az" not in SOURCE
    assert not re.search(r"shell\s*=\s*True|shlex\.join", SOURCE)
    assert not re.search(r"-preview\.\d", SOURCE)


def test_the_write_bodies_name_no_flag_a_write_must_never_send():
    body = "".join(inspect.getsource(getattr(ado_wit, name))
                   for name in ("create", "update", "add_comment", "add_history", "list_recent_comments", "link_pr"))
    for word in FORBIDDEN_WORDS:
        assert word not in body
    assert "--only-show-errors" not in body


def test_the_writes_add_no_module_level_import():
    import ast
    top = {a.name.split(".")[0] for n in ast.parse(SOURCE).body if isinstance(n, ast.Import) for a in n.names}
    top |= {(n.module or "").split(".")[0] for n in ast.parse(SOURCE).body if isinstance(n, ast.ImportFrom)}
    assert top <= {"sys", "pathlib", "ado_transport", "ado_map", "boards_contract"}, top
