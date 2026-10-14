"""B5-P2 — the watermark feed (`ado_wit_feed`): what changed on the board since a point, a page at a time.

What this pins, and why each line exists (build kit §5 Fold B5 card B5-P2; spec 0038 acceptance check 3; house rules
2, 9, 10, 11; guardrails 2, 7, 8, 10):
  * `revisions_since(repo, watermark)` reads `GET {project}/_apis/wit/reporting/workItemRevisions` through
    `ado_transport.invoke_body` and nothing else, at the location `boards_contract.WIT_ROUTES["workitemrevisions"]`
    names (never a literal route string): `--detect false`, `--api-version 7.1`, no `--repository`, no `--project`,
    no `--only-show-errors` (the seam adds it), no preview revision, and a read-only fake (`writes=False`) passes it;
  * `continuationToken` and `startDateTime` are mutually exclusive (a ValueError when both, and when neither, before
    any call): the first page names a start, every later page names only the token the page before it returned;
  * `isLastBatch: true` stops the paging, and the returned watermark is that last page's `continuationToken`; a page
    that says there is more but whose token does not move on is an error, never a loop; the page cap says it stopped
    (`.truncated`) and still returns a token the next read can resume from;
  * a watermark never read is `None`, never `0`, and an unreadable watermark file is `None` too (the safe direction:
    read again, never skip); `revisions_since` stores nothing, the caller saves the token with `save_watermark`;
  * every identity that comes back passes through `ado_discussion_map.redact_identity` (`{handle, display_name, id}`
    and nothing else); an e-mail or GUID inside any other text is replaced; `System.History` (comment text) is dropped;
  * a response is read only through `_require`: a shape the module does not know is an `AdoImportError` naming it.

Nothing here spawns `az`: `boards_env` forbids it at the seam and `az` swaps a `FakeBoardsAz` in for `run_az`.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import FakeBoardsAz, load_wit, query_params, route_key_boards, route_params, wit_path

import ast
import hashlib
import inspect
import json
import re

import pytest
import yaml

import ado_discussion_map
import ado_transport
import code_host
import ado_wit_feed as feed
import boards_contract
from ado_map import AdoImportError

ORG = "https://dev.azure.com/contoso"  # what tests.ado_fixtures.ADO_REMOTE parses to
PROJECT = "Claims"
FEED_KEY = "GET wit/workItemRevisions"
PAGED_KEY = f"{FEED_KEY} continuationToken=*"
FIXTURE = "workitemrevisions"
START = "2026-10-10T00:00:00Z"


# --- helpers ---------------------------------------------------------------------------------------------------

def revision(wid: int, rev: int, **fields) -> dict:
    return {"id": wid, "rev": rev, "fields": {"System.Id": wid, "System.Rev": rev, **fields}}


def page(values: list, token: str | None, last: bool) -> dict:
    doc = {"values": values, "nextLink": "https://dev.azure.com/contoso/_apis/wit/reporting/workItemRevisions",
           "isLastBatch": last}
    if token is not None:
        doc["continuationToken"] = token
    return doc


def pages_answer(pages: list[dict]):
    """Serve `pages` in order, then fail loudly if asked for another."""
    calls = iter(pages)

    def answer(args):
        try:
            return next(calls)
        except StopIteration:
            raise AssertionError("asked for a page that was never served") from None
    return answer


def chain(az, n: int, *, last: bool = True) -> None:
    """`n` pages, page `i` (1-based) carrying revision `(100 + i, 1)` and the token `T<i>`. Every page but the n-th says
    there is more; the n-th says it is the last unless `last` is False (then no page ever does)."""
    def doc(i: int) -> dict:
        return page([revision(100 + i, 1)], f"T{i}", last and i == n)
    az.answers[FEED_KEY] = doc(1)
    az.answers[PAGED_KEY] = lambda args: doc(int(query_params(args)["continuationToken"][1:]) + 1)


def query_of(argv: list[str]) -> dict[str, str]:
    return query_params(argv)


def fixture_values() -> list[dict]:
    return load_wit(FIXTURE)["values"]


# --- the module's surface ---------------------------------------------------------------------------------------

def test_the_interface_sheet_names_and_signatures():
    assert list(inspect.signature(feed.revisions_since).parameters) == ["repo_root", "watermark"]
    assert list(inspect.signature(feed.load_watermark).parameters) == ["repo_root"]
    assert list(inspect.signature(feed.save_watermark).parameters) == ["repo_root", "watermark"]
    params = inspect.signature(feed.feed_page).parameters
    assert list(params) == ["repo_root", "start_date_time", "continuation_token"]
    assert all(params[n].kind is inspect.Parameter.KEYWORD_ONLY and params[n].default is None
               for n in ("start_date_time", "continuation_token"))


def test_the_watermark_lives_under_the_local_folder():
    assert feed.WATERMARK_FILE == f"{boards_contract.LOCAL_DIR}/watermark" == ".sdlc/ado/local/watermark"


def test_the_requested_fields_are_the_ones_the_b5_p0_fixture_was_written_for():
    command = json.loads(wit_path(FIXTURE).read_text(encoding="utf-8"))["_command"]
    fields = next(w for w in command if w.startswith("fields="))[len("fields="):]
    assert ",".join(feed.FEED_FIELDS) == fields
    assert not {"System.AssignedTo", "System.ChangedBy", "System.CreatedBy", "System.History"} & set(feed.FEED_FIELDS)


# --- the first read ---------------------------------------------------------------------------------------------

def test_a_watermark_never_read_starts_at_the_beginning_with_a_start_date_and_no_token(az, tmp_path):
    rows, token = feed.revisions_since(tmp_path, None)
    assert len(az.calls) == 1 and route_key_boards(az.calls[0]) == FEED_KEY
    query = query_of(az.calls[0])
    assert query["startDateTime"] == feed.FEED_START and "continuationToken" not in query
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", feed.FEED_START)
    assert query["fields"] == ",".join(feed.FEED_FIELDS)
    assert route_params(az.calls[0]) == {"project": PROJECT}


def test_the_default_page_comes_back_whole_in_the_boards_order_and_its_token_is_the_next_watermark(az, tmp_path):
    rows, token = feed.revisions_since(tmp_path, START)
    doc = load_wit(FIXTURE)
    assert rows == [{"id": v["id"], "rev": v["rev"], "fields": v["fields"]} for v in doc["values"]]
    assert [(r["id"], r["rev"]) for r in rows] == [(4521, 7), (4530, 1), (4530, 2), (4523, 2), (4531, 1)]
    assert token == doc["continuationToken"] == "d2F0ZXJtYXJrLTQ3"
    assert len(az.calls) == 1, "isLastBatch is true: one call, however many tokens the page holds"
    assert rows.truncated is False


def test_a_start_date_watermark_names_that_date_on_the_first_call(az, tmp_path):
    feed.revisions_since(tmp_path, START)
    query = query_of(az.calls[0])
    assert query["startDateTime"] == START and "continuationToken" not in query


def test_a_token_watermark_resumes_with_the_token_and_no_start_date(az, tmp_path):
    az.answers[FEED_KEY] = page([revision(4540, 3)], "T9", True)
    rows, token = feed.revisions_since(tmp_path, "T8")
    assert len(az.calls) == 1
    query = query_of(az.calls[0])
    assert query["continuationToken"] == "T8" and "startDateTime" not in query
    assert query["fields"] == ",".join(feed.FEED_FIELDS)
    assert [(r["id"], r["rev"]) for r in rows] == [(4540, 3)] and token == "T9"


# --- paging -----------------------------------------------------------------------------------------------------

def test_a_later_page_names_only_the_token_the_page_before_returned(az, tmp_path):
    chain(az, 3)
    rows, token = feed.revisions_since(tmp_path, None)
    assert [route_key_boards(c) for c in az.calls] == [FEED_KEY] * 3
    queries = [query_of(c) for c in az.calls]
    assert "startDateTime" in queries[0] and "continuationToken" not in queries[0]
    assert [q.get("continuationToken") for q in queries[1:]] == ["T1", "T2"]
    assert all("startDateTime" not in q for q in queries[1:])
    assert all(q["fields"] == ",".join(feed.FEED_FIELDS) for q in queries)
    assert [r["id"] for r in rows] == [101, 102, 103], "the pages' revisions, in the order the board sent them"
    assert token == "T3"


def test_no_call_ever_carries_both_a_token_and_a_start_date(az, tmp_path):
    chain(az, 4)
    feed.revisions_since(tmp_path, START)
    feed.revisions_since(tmp_path, "T0")
    assert len(az.calls) == 8
    for call in az.calls:
        query = query_of(call)
        assert ("startDateTime" in query) != ("continuationToken" in query), query


def test_paging_stops_on_the_last_batch_and_the_watermark_is_that_pages_token(az, tmp_path):
    az.answers[FEED_KEY] = page([revision(1, 1)], "T1", False)
    az.answers[PAGED_KEY] = pages_answer([page([revision(2, 1)], "T2", False), page([revision(3, 1)], "T3", True)])
    rows, token = feed.revisions_since(tmp_path, None)
    assert len(az.calls) == 3 and token == "T3"
    save = feed.save_watermark(tmp_path, token)
    assert feed.load_watermark(tmp_path) == "T3" and save.read_text(encoding="utf-8").strip() == "T3"


def test_a_page_that_says_there_is_more_but_repeats_the_token_it_was_asked_for_is_an_error_not_a_loop(az, tmp_path):
    az.answers[FEED_KEY] = page([revision(1, 1)], "T1", False)
    az.answers[PAGED_KEY] = lambda args: page([revision(2, 1)], "T1", False)
    with pytest.raises(AdoImportError, match=r"did not advance.*T1"):
        feed.revisions_since(tmp_path, None)
    assert len(az.calls) == 2


def test_a_page_that_says_there_is_more_but_has_no_token_is_an_error(az, tmp_path):
    az.answers[FEED_KEY] = page([revision(1, 1)], None, False)
    with pytest.raises(AdoImportError, match="continuationToken"):
        feed.revisions_since(tmp_path, None)
    assert len(az.calls) == 1


def test_the_page_cap_stops_the_read_and_says_so_with_a_token_the_next_read_can_resume_from(az, tmp_path, monkeypatch):
    monkeypatch.setattr(feed, "MAX_FEED_PAGES", 3)
    chain(az, 5, last=False)
    rows, token = feed.revisions_since(tmp_path, None)
    assert len(az.calls) == 3 and rows.truncated is True
    assert token == "T3" and [r["id"] for r in rows] == [101, 102, 103]
    rows2, token2 = feed.revisions_since(tmp_path, token)  # the resume starts after the page the cap stopped at
    assert query_of(az.calls[3])["continuationToken"] == "T3" and rows2.truncated is True and token2 == "T6"


def test_a_last_batch_on_exactly_the_capped_page_is_not_truncated(az, tmp_path, monkeypatch):
    monkeypatch.setattr(feed, "MAX_FEED_PAGES", 3)
    chain(az, 3)
    rows, token = feed.revisions_since(tmp_path, None)
    assert len(az.calls) == 3 and rows.truncated is False and token == "T3"


def test_the_page_cap_default_is_a_hundred_pages():
    assert feed.MAX_FEED_PAGES == 100


# --- a read that found nothing newer ----------------------------------------------------------------------------

def test_nothing_newer_with_no_token_keeps_the_watermark_the_read_started_from(az, tmp_path):
    az.answers[FEED_KEY] = page([], None, True)
    assert feed.revisions_since(tmp_path, "T8") == ([], "T8")
    assert feed.revisions_since(tmp_path, START) == ([], START)
    assert feed.revisions_since(tmp_path, None) == ([], feed.FEED_START)


def test_nothing_newer_with_a_token_returns_that_token_and_an_empty_list_not_a_none(az, tmp_path):
    az.answers[FEED_KEY] = page([], "T8", True)
    rows, token = feed.revisions_since(tmp_path, "T8")
    assert rows == [] and rows is not None and token == "T8"


# --- exclusivity ------------------------------------------------------------------------------------------------

def test_a_page_call_with_both_a_start_date_and_a_token_is_a_value_error_before_any_call(az, tmp_path):
    with pytest.raises(ValueError, match="mutually exclusive"):
        feed.feed_page(tmp_path, start_date_time=START, continuation_token="T1")
    assert az.calls == []


def test_a_page_call_with_neither_is_a_value_error_before_any_call(az, tmp_path):
    with pytest.raises(ValueError, match="exactly one"):
        feed.feed_page(tmp_path)
    assert az.calls == []


def test_a_page_call_names_exactly_the_one_it_was_given(az, tmp_path):
    feed.feed_page(tmp_path, start_date_time=START)
    feed.feed_page(tmp_path, continuation_token="T1")
    assert [sorted(k for k in query_of(c) if k != "fields") for c in az.calls] == [["startDateTime"],
                                                                                    ["continuationToken"]]


# --- the watermark argument -------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["", " ", "a b", "T1\n", "\tT1", 0, 7, 1.5, True, b"T1", ["T1"], "x" * 2000],
                         ids=lambda v: repr(v)[:24])
def test_a_watermark_that_is_neither_none_a_start_date_nor_a_token_is_refused_before_any_call(az, tmp_path, bad):
    with pytest.raises(ValueError):
        feed.revisions_since(tmp_path, bad)
    assert az.calls == []


@pytest.mark.parametrize("bad", ["2026-10-10", "2026-10-10T00:00:00", "2026-10-10 00:00:00Z", "2026-10-10T00:00Z",
                                 "2026-10-10T00:00:00+02:00"])
def test_a_watermark_that_starts_like_a_date_must_be_a_whole_utc_time_not_guessed_into_a_token(az, tmp_path, bad):
    with pytest.raises(ValueError, match="ISO-8601 UTC"):
        feed.revisions_since(tmp_path, bad)
    assert az.calls == []


@pytest.mark.parametrize("good", ["2026-10-10T00:00:00Z", "2026-10-10T08:30:15.123Z"])
def test_a_whole_utc_time_is_a_start_date(az, tmp_path, good):
    feed.revisions_since(tmp_path, good)
    assert query_of(az.calls[0])["startDateTime"] == good


# --- identities and text ----------------------------------------------------------------------------------------

PAT = "Pat Example <pat@example.com>"
SAM = {"displayName": "Sam Example", "uniqueName": "sam@example.com", "id": "00000000-0000-0000-0000-000000000042",
       "imageUrl": "https://dev.azure.com/contoso/_apis/GraphProfile/MemberAvatars/x", "_links": {"avatar": {}}}


@pytest.fixture
def identity_fields(monkeypatch):
    monkeypatch.setattr(feed, "FEED_FIELDS", (*feed.FEED_FIELDS, "System.ChangedBy", "System.AssignedTo"))


def write_roster(root) -> dict:
    (root / ".sdlc").mkdir(exist_ok=True)
    (root / ".sdlc" / "team.yaml").write_text(
        yaml.safe_dump({"people": [{"handle": "@sam-k", "name": "Sam K", "email": "sam@example.com"}]}),
        encoding="utf-8")
    return {"sam@example.com": "@sam-k"}


def test_an_identity_is_whatever_redact_identity_makes_of_it_with_the_rosters_addresses(az, tmp_path, identity_fields):
    emails = write_roster(tmp_path)
    az.answers[FEED_KEY] = page([revision(4521, 8, **{"System.ChangedBy": PAT, "System.AssignedTo": SAM})], "T1", True)
    rows, _ = feed.revisions_since(tmp_path, START)
    fields = rows[0]["fields"]
    assert fields["System.ChangedBy"] == ado_discussion_map.redact_identity(PAT, emails)
    assert fields["System.AssignedTo"] == ado_discussion_map.redact_identity(SAM, emails)
    assert fields["System.ChangedBy"] == {"handle": None, "display_name": "Pat Example", "id": None}
    assert fields["System.AssignedTo"] == {"handle": "@sam-k", "display_name": "Sam Example",
                                           "id": "00000000-0000-0000-0000-000000000042"}


def test_every_identity_goes_through_the_discussion_maps_redact_identity(az, tmp_path, identity_fields, monkeypatch):
    seen = []
    monkeypatch.setattr(ado_discussion_map, "redact_identity",
                        lambda ident, emails: seen.append(ident) or {"handle": None, "display_name": None, "id": None})
    az.answers[FEED_KEY] = page([revision(4521, 8, **{"System.ChangedBy": PAT, "System.AssignedTo": SAM}),
                                 revision(4521, 9, **{"System.ChangedBy": PAT})], "T1", True)
    feed.revisions_since(tmp_path, START)
    assert seen == [PAT, SAM, PAT]


def test_no_address_and_no_link_leaves_the_module(az, tmp_path, identity_fields):
    write_roster(tmp_path)
    az.answers[FEED_KEY] = page([revision(4521, 8, **{"System.ChangedBy": PAT, "System.AssignedTo": SAM,
                                                      "System.Title": "Ask pat@example.com about 00000000-0000-0000-0000-000000000042"})],
                                "T1", True)
    rows, token = feed.revisions_since(tmp_path, START)
    text = json.dumps([rows, token])
    for needle in ("@example.com", "uniqueName", "imageUrl", "_links", "avatar", "MemberAvatars"):
        assert needle not in text, needle
    assert rows[0]["fields"]["System.Title"] == "Ask [email] about [guid]"


def test_an_identity_on_a_system_field_named_by_by_or_assigned_to_is_redacted_even_as_a_plain_string(az, tmp_path,
                                                                                                    monkeypatch):
    monkeypatch.setattr(feed, "FEED_FIELDS", (*feed.FEED_FIELDS, "System.AuthorizedAs", "Custom.ReviewedBy"))
    az.answers[FEED_KEY] = page([revision(1, 1, **{"System.AuthorizedAs": "Pat Example", "Custom.ReviewedBy": ""})],
                                "T1", True)
    rows, _ = feed.revisions_since(tmp_path, START)
    assert rows[0]["fields"]["System.AuthorizedAs"] == {"handle": None, "display_name": "Pat Example", "id": None}
    assert rows[0]["fields"]["Custom.ReviewedBy"] == {"handle": None, "display_name": None, "id": None}


def test_the_identity_suffixes_match_the_discussion_maps(az, tmp_path):
    assert feed.IDENTITY_FIELD_ENDS == ado_discussion_map._IDENTITY_FIELD_ENDS


def test_a_missing_roster_is_no_roster_not_a_failure(az, tmp_path, identity_fields):
    az.answers[FEED_KEY] = page([revision(1, 1, **{"System.AssignedTo": SAM})], "T1", True)
    rows, _ = feed.revisions_since(tmp_path, START)
    assert rows[0]["fields"]["System.AssignedTo"]["handle"] is None
    (tmp_path / ".sdlc").mkdir()
    (tmp_path / ".sdlc" / "team.yaml").write_text("people: [unclosed", encoding="utf-8")
    rows, _ = feed.revisions_since(tmp_path, START)
    assert rows[0]["fields"]["System.AssignedTo"]["handle"] is None


def test_the_roster_is_read_only_when_an_identity_needs_it(az, tmp_path, monkeypatch):
    read = []
    monkeypatch.setattr(feed, "_roster_emails", lambda root: read.append(root) or {})
    feed.revisions_since(tmp_path, START)  # the default fields carry no identity
    assert read == []


def test_system_history_is_dropped_and_only_the_fact_that_it_changed_remains(az, tmp_path, monkeypatch):
    monkeypatch.setattr(feed, "FEED_FIELDS", (*feed.FEED_FIELDS, "System.History"))
    az.answers[FEED_KEY] = page([revision(1, 2, **{"System.History": "<div>ping pat@example.com</div>"}),
                                 revision(1, 3)], "T1", True)
    rows, _ = feed.revisions_since(tmp_path, START)
    assert "System.History" not in rows[0]["fields"] and rows[0]["history_changed"] is True
    assert "history_changed" not in rows[1]
    assert "ping" not in json.dumps(rows)


def test_scalars_pass_through_untouched(az, tmp_path):
    az.answers[FEED_KEY] = page([revision(1, 1, **{"Custom.Flag": True, "Custom.Count": 3, "Custom.Ratio": 0.5,
                                                   "Custom.Empty": None})], "T1", True)
    rows, _ = feed.revisions_since(tmp_path, START)
    assert {k: rows[0]["fields"][k] for k in ("Custom.Flag", "Custom.Count", "Custom.Ratio", "Custom.Empty")} == {
        "Custom.Flag": True, "Custom.Count": 3, "Custom.Ratio": 0.5, "Custom.Empty": None}


def test_a_list_valued_field_is_a_shape_the_module_does_not_know(az, tmp_path):
    az.answers[FEED_KEY] = page([revision(1, 1, **{"Custom.Many": ["a", "b"]})], "T1", True)
    with pytest.raises(AdoImportError, match=r"unexpected az shape.*Custom\.Many"):
        feed.revisions_since(tmp_path, START)


# --- shapes the module does not know ----------------------------------------------------------------------------

@pytest.mark.parametrize("reply, needle", [
    ({"nextLink": "x", "continuationToken": "T", "isLastBatch": True}, "values"),
    ({"values": {}, "continuationToken": "T", "isLastBatch": True}, "values"),
    ({"values": [], "continuationToken": "T"}, "isLastBatch"),
    ({"values": [], "continuationToken": "T", "isLastBatch": "true"}, "isLastBatch"),
    ({"values": [], "continuationToken": 7, "isLastBatch": True}, "continuationToken"),
    ({"values": [], "continuationToken": "has space", "isLastBatch": True}, "continuationToken"),
    ([], "values"),
    (7, "values"),  # a bare number (a string would be read by the fake as a fixture name)
    ({"values": [{"rev": 1, "fields": {}}], "continuationToken": "T", "isLastBatch": True}, "id"),
    ({"values": [{"id": 1, "fields": {}}], "continuationToken": "T", "isLastBatch": True}, "rev"),
    ({"values": [{"id": 1, "rev": 1}], "continuationToken": "T", "isLastBatch": True}, "fields"),
    ({"values": [{"id": "1", "rev": 1, "fields": {}}], "continuationToken": "T", "isLastBatch": True}, "id"),
    ({"values": [{"id": True, "rev": 1, "fields": {}}], "continuationToken": "T", "isLastBatch": True}, "id"),
    ({"values": [{"id": 1, "rev": 0, "fields": {}}], "continuationToken": "T", "isLastBatch": True}, "rev"),
    ({"values": [{"id": 1, "rev": 1, "fields": []}], "continuationToken": "T", "isLastBatch": True}, "fields"),
    ({"values": ["row"], "continuationToken": "T", "isLastBatch": True}, "id"),
], ids=lambda v: str(v)[:32])
def test_a_page_in_a_shape_it_does_not_know_is_an_import_error_naming_it(az, tmp_path, reply, needle):
    az.answers[FEED_KEY] = reply
    with pytest.raises(AdoImportError, match=needle):
        feed.revisions_since(tmp_path, START)


def test_an_empty_stdout_is_not_a_page(az, tmp_path):
    az.answers[FEED_KEY] = None  # az prints nothing; invoke_body reads that as `[]`
    with pytest.raises(AdoImportError, match="unexpected az shape"):
        feed.revisions_since(tmp_path, START)


def test_a_failed_call_names_the_route(az, tmp_path):
    az.fail["resource workItemRevisions"] = "TF400813: The user is not authorized"
    with pytest.raises(AdoImportError, match=r"wit/workItemRevisions.*TF400813"):
        feed.revisions_since(tmp_path, START)


def test_a_failure_on_a_later_page_is_raised_and_the_earlier_pages_are_not_returned_as_a_whole_read(az, tmp_path):
    chain(az, 3)
    az.fail["continuationToken=T2"] = "VS403403: not allowed"
    with pytest.raises(AdoImportError, match="VS403403"):
        feed.revisions_since(tmp_path, None)


# --- the seam ---------------------------------------------------------------------------------------------------

def run_everything(root) -> None:
    feed.revisions_since(root, None)
    feed.revisions_since(root, START)
    feed.revisions_since(root, "T1")
    feed.feed_page(root, start_date_time=START)
    feed.feed_page(root, continuation_token="T1")


def test_every_read_passes_a_read_only_fake(az, tmp_path):
    assert az.writes is False
    run_everything(tmp_path)
    assert az.written() == []
    assert {route_key_boards(c) for c in az.calls} == {FEED_KEY}


def test_every_recorded_argv_has_the_seam_shape(az, tmp_path):
    chain(az, 3)
    run_everything(tmp_path)
    assert len(az.calls) >= 9
    for argv in az.calls:
        assert argv[:2] == ["devops", "invoke"]
        assert argv[argv.index("--detect") + 1] == "false", argv
        assert argv[argv.index("--org") + 1] == ORG
        assert argv[argv.index("--api-version") + 1] == "7.1" == ado_transport.API_VERSION
        assert argv[argv.index("--http-method") + 1] == "GET"
        assert (argv[argv.index("--area") + 1], argv[argv.index("--resource") + 1]) == ("wit", "workItemRevisions")
        assert argv[-2:] == ["-o", "json"] and "--only-show-errors" not in argv
        for banned in ("--repository", "--project", "--in-file", "--media-type"):
            assert banned not in argv, banned
        assert not any(re.search(r"-preview", word) for word in argv)
        assert route_params(argv) == {"project": PROJECT}


def test_the_project_and_organisation_come_from_the_remote(az, tmp_path, monkeypatch):
    monkeypatch.setattr(code_host, "origin_url", lambda root: "https://dev.azure.com/other/Billing/_git/ledger")
    ado_transport.clear_caches()
    feed.revisions_since(tmp_path, None)
    assert route_params(az.calls[0]) == {"project": "Billing"}
    assert az.calls[0][az.calls[0].index("--org") + 1] == "https://dev.azure.com/other"


def test_the_route_is_the_contract_row_and_the_row_says_the_plain_version():
    row = boards_contract.WIT_ROUTES["workitemrevisions"]
    assert row["api_version"] == ado_transport.API_VERSION and row["method"] == "GET" and row["route"] == ("project",)


def test_a_corrected_route_is_followed_with_no_code_change(az, tmp_path, monkeypatch):
    monkeypatch.setitem(boards_contract.WIT_ROUTES, "workitemrevisions",
                        {**boards_contract.WIT_ROUTES["workitemrevisions"], "resource": "revisionsFeed", "area": "wit2"})
    az.answers["GET wit2/revisionsFeed"] = page([revision(9, 1)], "T1", True)
    rows, token = feed.revisions_since(tmp_path, None)
    assert [route_key_boards(c) for c in az.calls] == ["GET wit2/revisionsFeed"]
    assert [r["id"] for r in rows] == [9] and token == "T1"


def test_a_route_that_needs_a_parameter_the_read_does_not_supply_is_an_error_not_a_guess(az, tmp_path, monkeypatch):
    monkeypatch.setitem(boards_contract.WIT_ROUTES, "workitemrevisions",
                        {**boards_contract.WIT_ROUTES["workitemrevisions"], "route": ("project", "team")})
    with pytest.raises(AdoImportError, match="team"):
        feed.revisions_since(tmp_path, None)
    assert az.calls == []


def test_a_preview_revision_never_reaches_az(az, tmp_path, monkeypatch):
    monkeypatch.setitem(boards_contract.WIT_ROUTES, "workitemrevisions",
                        {**boards_contract.WIT_ROUTES["workitemrevisions"], "api_version": "7.1-preview.4"})
    with pytest.raises(AdoImportError, match="preview"):
        feed.revisions_since(tmp_path, None)
    assert az.calls == []


def test_a_read_only_fake_that_refuses_writes_passes_the_whole_paging_loop(monkeypatch, tmp_path):
    fake = FakeBoardsAz({FEED_KEY: page([revision(1, 1)], "T1", False),
                         PAGED_KEY: pages_answer([page([revision(2, 1)], "T2", True)])}, writes=False)
    monkeypatch.setattr(ado_transport, "run_az", fake)
    rows, token = feed.revisions_since(tmp_path, None)
    assert [r["id"] for r in rows] == [1, 2] and token == "T2" and fake.written() == []


# --- the watermark file -----------------------------------------------------------------------------------------

def test_a_watermark_never_saved_is_none_not_zero(tmp_path):
    assert feed.load_watermark(tmp_path) is None
    assert feed.load_watermark(tmp_path / "does-not-exist") is None
    assert list(tmp_path.iterdir()) == [], "reading creates nothing"


def test_the_watermark_is_one_line_in_the_local_folder_and_round_trips(tmp_path):
    path = feed.save_watermark(tmp_path, "d2F0ZXJtYXJrLTQ3")
    assert path == tmp_path / ".sdlc" / "ado" / "local" / "watermark"
    assert path.read_bytes() == b"d2F0ZXJtYXJrLTQ3\n"
    assert feed.load_watermark(tmp_path) == "d2F0ZXJtYXJrLTQ3"
    feed.save_watermark(tmp_path, START)
    assert feed.load_watermark(tmp_path) == START and path.read_bytes() == f"{START}\n".encode()


def test_saving_makes_the_local_folder_ignored_by_git_and_never_clobbers_an_ignore_file(tmp_path):
    feed.save_watermark(tmp_path, "T1")
    ignore = tmp_path / ".sdlc" / "ado" / "local" / ".gitignore"
    assert ignore.read_bytes() == b"*\n"
    ignore.write_bytes(b"*\n!keep\n")
    feed.save_watermark(tmp_path, "T2")
    assert ignore.read_bytes() == b"*\n!keep\n"


def test_saving_leaves_no_scratch_file_behind(tmp_path):
    feed.save_watermark(tmp_path, "T1")
    feed.save_watermark(tmp_path, "T2")
    assert sorted(p.name for p in (tmp_path / ".sdlc" / "ado" / "local").iterdir()) == [".gitignore", "watermark"]


@pytest.mark.parametrize("bad", ["", " ", "a b", "T1\nT2", None, 0, 7, b"T1", "2026-10-10", "x" * 2000],
                         ids=lambda v: repr(v)[:24])
def test_a_watermark_that_cannot_be_read_back_is_refused_and_nothing_is_written(tmp_path, bad):
    with pytest.raises(ValueError):
        feed.save_watermark(tmp_path, bad)
    assert not (tmp_path / ".sdlc").exists()


@pytest.mark.parametrize("content", [b"", b"\n", b"   \n", b"T1\nT2\n", b"a b\n", b"\xff\xfe\x00bad", b"2026-10-10\n",
                                     b"x" * 2000])
def test_a_watermark_file_nobody_can_trust_reads_as_never_read_so_the_next_read_starts_again(tmp_path, content):
    path = tmp_path / ".sdlc" / "ado" / "local" / "watermark"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    assert feed.load_watermark(tmp_path) is None


def test_a_watermark_path_that_is_a_folder_reads_as_never_read(tmp_path):
    (tmp_path / ".sdlc" / "ado" / "local" / "watermark").mkdir(parents=True)
    assert feed.load_watermark(tmp_path) is None


def test_a_crlf_watermark_file_still_reads(tmp_path):
    path = tmp_path / ".sdlc" / "ado" / "local" / "watermark"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"T1\r\n")
    assert feed.load_watermark(tmp_path) == "T1"


def test_reading_the_feed_stores_nothing_the_caller_saves_the_token_after_it_has_used_the_rows(az, tmp_path):
    feed.revisions_since(tmp_path, None)
    feed.revisions_since(tmp_path, "T1")
    assert list(tmp_path.iterdir()) == []


def test_the_first_read_after_a_save_resumes_from_the_saved_token(az, tmp_path):
    az.answers[FEED_KEY] = page([revision(1, 1)], "T5", True)
    _, token = feed.revisions_since(tmp_path, feed.load_watermark(tmp_path))
    assert "startDateTime" in query_of(az.calls[0])
    feed.save_watermark(tmp_path, token)
    feed.revisions_since(tmp_path, feed.load_watermark(tmp_path))
    assert query_of(az.calls[1]).get("continuationToken") == "T5" and "startDateTime" not in query_of(az.calls[1])


# --- the fixture is read, never changed -------------------------------------------------------------------------

def test_the_feed_fixture_is_unchanged_by_the_run(az, tmp_path):
    path = wit_path(FIXTURE)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    run_everything(tmp_path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


# --- what the module is allowed to be ---------------------------------------------------------------------------

SOURCE = inspect.getsource(feed)
TREE = ast.parse(SOURCE)


def _docstring_nodes(tree) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                found.add(id(body[0].value))
    return found


def test_the_module_imports_no_subprocess_and_reaches_az_only_through_the_seam():
    imported = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"os", "re", "sys", "pathlib", "yaml", "ado_transport", "ado_map", "ado_discussion_map",
                        "boards_contract", "validate_team"}, imported
    assert "subprocess" not in imported
    assert "run_az" not in SOURCE and "az_json" not in SOURCE  # only invoke_body, which owns the spawn
    assert not re.search(r"shell\s*=\s*True|shlex\.join", SOURCE)


def test_the_module_never_names_a_preview_revision_or_a_write_only_flag():
    assert not re.search(r"-preview", SOURCE)
    for word in ("suppressNotifications", "bypassRules", "validateOnly", "--in-file", "POST", "PATCH"):
        assert word not in SOURCE, word


def test_the_route_is_never_a_literal_string_in_the_code():
    skip = _docstring_nodes(TREE)
    literals = [n.value for n in ast.walk(TREE) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in skip]
    for text in literals:
        assert "workItemRevisions" not in text and "_apis" not in text and "/reporting" not in text, text
    assert "workitemrevisions" in literals, "the one name it uses is the WIT_ROUTES row's key"
    assert "WIT_ROUTES" in SOURCE


def test_the_module_holds_no_address_and_no_guid():
    assert not boards_contract.EMAIL_RE.search(SOURCE) and not boards_contract.GUID_RE.search(SOURCE)
