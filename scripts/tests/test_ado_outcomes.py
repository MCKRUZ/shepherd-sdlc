"""ado_outcomes — Azure DevOps history → scorecard events, on captured fixtures (code-host providers, Wave 5).

Nothing here spawns `az`: `ado_transport.az_json` (the one seam) is replaced by the FakeAz router, which
raises on any call it was not told about — that AssertionError is the read-only pin. Expected ids,
SHAs and dates are derived from the fixture, so a re-capture changes the data, not the assertions.
"""

from datetime import date, timedelta

import pytest

import ado_import
import ado_map
import ado_outcomes as ao
import ado_transport
import code_host
import github_import as gi
from ado_map import AdoImportError
from tests.ado_fixtures import ADO_REMOTE, FakeAz, load

MERGED = load("pr_show_completed")
SHA = MERGED["lastMergeCommit"]["commitId"]  # the merge commit of the captured completed PR
COMPLETED_IDS = sorted(p["pullRequestId"] for p in load("pr_list") if p["status"] == "completed")
RECORDS = load("deployment_records")["value"]
ENVIRONMENTS = load("environments")["value"]
# A window that contains every captured merge and deployment; one day past the last of them contains none.
_DATES = [p["closedDate"][:10] for p in load("pr_list") if p["status"] == "completed"] + [r["queueTime"][:10] for r in RECORDS]
SINCE = min(_DATES)
AFTER = (date.fromisoformat(max(_DATES)) + timedelta(days=1)).isoformat()


THREADS, COMMITS = "devops invoke git pullRequestThreads", "devops invoke git pullRequestCommits"


def answers(**over):
    """FakeAz answers on top of its defaults: the COMPLETED PR's threads and commits (the defaults
    are the active PR's), the captured merge SHA for every `runs show`, and an empty boards query."""
    base = {THREADS: load("pr_threads_completed"), COMMITS: load("pr_commits_completed"),
            "pipelines runs show": SHA, "boards query": []}
    base.update(over)
    return base


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    ao.clear_caches()
    ado_import.clear_caches()
    monkeypatch.delenv(code_host.ENV_VAR, raising=False)
    monkeypatch.delenv(code_host.LEGACY_CODE_HOST_ENV, raising=False)
    monkeypatch.setattr(code_host, "origin_url", lambda root: ADO_REMOTE)
    yield
    ao.clear_caches()
    ado_import.clear_caches()


@pytest.fixture
def az(monkeypatch):
    def install(**over):
        fake = FakeAz(answers(**over))
        monkeypatch.setattr(ado_transport, "az_json", fake)
        return fake
    return install


def thread(kind, when, **props):
    properties = {"CodeReviewThreadType": {"$type": "System.String", "$value": kind}}
    properties.update({k: {"$type": "System.String", "$value": v} for k, v in props.items()})
    return {"id": 1, "publishedDate": when, "isDeleted": False, "properties": properties,
            "identities": {"1": {"uniqueName": "reviewer@example.com"}}, "comments": []}


class TestPureNormalisers:
    def test_completed_pr_maps_to_the_gh_pr_list_shape_with_normalised_times(self):
        pr = ao.pr_to_gh(MERGED)
        assert pr["number"] == MERGED["pullRequestId"] and pr["mergedAt"] == ao._iso(MERGED["closedDate"])
        assert pr["mergedAt"].endswith("Z") and "+" not in pr["mergedAt"] and "." not in pr["mergedAt"]  # second-precision UTC
        assert pr["mergeCommit"] == {"oid": SHA} and pr["reviews"] == [] and pr["labels"] == []  # labels: null (captured) → []
        author = MERGED["createdBy"]["uniqueName"].lower()
        assert pr["_author"] == author
        # Votes on the PR record carry no time: every non-author approval there is "undated" until a thread dates it.
        assert pr["_undated_approvals"] == sum(1 for r in MERGED["reviewers"]
                                               if (r.get("vote") or 0) >= ao.APPROVE_VOTE and r["uniqueName"].lower() != author)

    def test_an_active_pr_never_lends_its_trial_merge_commit(self):
        active = load("pr_show_active")
        assert active["lastMergeCommit"]  # pitfall P7: lastMergeCommit exists on active PRs
        assert ao.pr_to_gh(dict(active, closedDate="2026-10-05T17:00:00Z"))["mergeCommit"] is None

    def test_commits_take_the_rest_committer_date_shape(self):
        raw = load("pr_commits_completed")["value"]
        commits = ao.commits_to_gh(load("pr_commits_completed"))
        assert raw and [c["sha"] for c in commits] == [c["commitId"] for c in raw]
        assert commits[0]["commit"]["committer"]["date"] == ao._iso(raw[0]["committer"]["date"])

    def test_review_requests_come_from_thread_properties_not_prose(self):
        threads = load("pr_threads_completed")["value"]
        expected = sorted(ao._iso(t["publishedDate"]) for t in threads
                          if ado_map.thread_property(t, "CodeReviewThreadType") == "ReviewersUpdate"
                          and int(ado_map.thread_property(t, "CodeReviewReviewersUpdatedNumAdded") or 0) > 0)
        events = ao.review_requests_from_threads(threads)
        assert expected and events == [{"event": "review_requested", "created_at": when} for when in expected]
        joined = thread("ReviewersUpdate", "2026-10-05T10:00:00Z", CodeReviewReviewersUpdatedNumAdded="0")
        assert ao.review_requests_from_threads([joined]) == []  # a removal is not a request

    def test_votes_are_dated_by_their_thread_and_the_authors_own_is_skipped(self):
        votes = [thread("VoteUpdate", "2026-10-05T11:00:00Z", CodeReviewVoteResult="10", CodeReviewVotedByIdentity="1")]
        assert ao.votes_from_threads(votes, "someone-else@example.com") == [
            {"state": "APPROVED", "author": {"login": "reviewer@example.com"}, "submittedAt": "2026-10-05T11:00:00Z"}]
        assert ao.votes_from_threads(votes, "reviewer@example.com") == []
        reject = [thread("VoteUpdate", "2026-10-05T11:00:00Z", CodeReviewVoteResult="-10", CodeReviewVotedByIdentity="1")]
        assert ao.votes_from_threads(reject, "")[0]["state"] == "CHANGES_REQUESTED"

    def test_a_deployment_record_is_terminal_only_when_it_says_so(self):
        succeeded = next(r for r in RECORDS if r["result"] == "succeeded")
        failed = next(r for r in RECORDS if r["result"] == "failed")
        assert ao.statuses_from_record(succeeded) == [{"id": succeeded["id"], "state": "success",
                                                       "created_at": ao._iso(succeeded["finishTime"])}]
        assert ao.statuses_from_record(failed)[0]["state"] == "failure"
        assert ao.statuses_from_record(dict(succeeded, result=None, finishTime=None)) == []
        assert ao.statuses_from_record(dict(succeeded, result="canceled")) == []  # neither a success nor a failure

    def test_work_item_maps_to_the_gh_issue_shape_and_requires_its_keys(self):
        item = load("boards_query", hand_written=True)[0]  # the captured answer is empty; the row shape is unverified
        assert ao.work_item_to_gh(item) == {"number": 1001, "createdAt": "2026-09-23T08:00:00Z",
                                            "closedAt": "2026-09-23T12:00:00Z", "state": "Closed"}
        with pytest.raises(AdoImportError, match="unexpected az shape: missing WorkItem.fields"):
            ao.work_item_to_gh({"id": 1})

    def test_missing_required_keys_raise_rather_than_default(self):
        with pytest.raises(AdoImportError, match="missing GitPullRequest.closedDate"):
            ao.pr_to_gh({"pullRequestId": 1, "status": "completed"})
        with pytest.raises(AdoImportError, match="missing pullRequestCommits.value"):
            ao.commits_to_gh({"count": 0})

    def test_since_is_shape_checked_before_it_reaches_wiql(self):
        with pytest.raises(AdoImportError, match="YYYY-MM-DD"):
            ao.check_since("2026-09-01' OR 1=1 --")
        assert ao.check_since("2026-09-01") == "2026-09-01"

    def test_re_id_swaps_only_the_gh_prefix(self):
        assert ao.re_id({"gh_id": "gh-pr-merge:7"})["gh_id"] == "ado-pr-merge:7"
        assert ao.re_id({"gh_id": "gh-pr-review:7"})["gh_id"] == "ado-pr-review:7"
        assert ao.re_id({"gh_id": "gh-issue:7"})["gh_id"] == "ado-wi:7"


class TestFetchers:
    def test_merged_prs_keep_only_completed_rows_closed_on_or_after_since(self, az):
        fake = az()
        prs = ao.fetch_merged_prs("/r", SINCE)
        assert COMPLETED_IDS and sorted(p["number"] for p in prs) == COMPLETED_IDS
        assert ao.fetch_merged_prs("/r", AFTER) == []
        argv = fake.calls[0]
        assert argv[:3] == ["repos", "pr", "list"] and "--status" in argv and argv[argv.index("--status") + 1] == "completed"
        assert "--detect" in argv and argv[argv.index("--top") + 1] == "200"

    def test_threads_are_read_once_per_pr_and_serve_both_fetchers(self, az):
        fake = az()
        number = COMPLETED_IDS[-1]
        ao.fetch_pr_events("/r", number)
        ao.fetch_pr_reviews("/r", number, MERGED["createdBy"]["uniqueName"])
        thread_calls = [c for c in fake.calls if "pullRequestThreads" in c]
        assert len(thread_calls) == 1 and "7.1" in thread_calls[0]

    def test_environments_use_the_preview_api_version(self, az):
        fake = az()
        deps = ao.fetch_deployments("/r")
        # FakeAz serves the one captured record set for every environment.
        assert len(deps) == len(ENVIRONMENTS) * len(RECORDS) and {d["environment"] for d in deps} == {e["name"] for e in ENVIRONMENTS}
        for call in (c for c in fake.calls if "distributedtask" in c):
            assert call[call.index("--api-version") + 1] == "7.1-preview"  # `.1` crashes the extension
        succeeded = next(r for r in RECORDS if r["result"] == "succeeded")
        assert ao.fetch_deployment_statuses("/r", succeeded["id"])[0]["state"] == "success"
        with pytest.raises(AdoImportError, match="not read by fetch_deployments"):
            ao.fetch_deployment_statuses("/r", 999999)

    def test_build_sha_is_one_projected_runs_show_per_build_cached(self, az):
        fake = az()
        build_id = RECORDS[0]["owner"]["id"]
        assert ao.fetch_build_sha("/r", build_id) == SHA and ao.fetch_build_sha("/r", build_id) == SHA
        shows = [c for c in fake.calls if c[:3] == ["pipelines", "runs", "show"]]
        assert len(shows) == 1 and shows[0][shows[0].index("--query") + 1] == "sourceVersion"

    def test_an_empty_boards_query_is_no_incidents_not_an_error(self, az):
        az(**{"boards query": []})
        assert ao.fetch_incident_issues("/r", SINCE) == []
        az(**{"boards query": None})
        assert ao.fetch_incident_issues("/r", SINCE) == []
        az(**{"boards query": load("boards_query", hand_written=True)})
        assert ao.fetch_incident_issues("/r", SINCE)[0]["number"] == 1001


class TestCollect:
    def test_every_id_carries_an_ado_prefix_and_none_a_gh_one(self, az):
        az(**{"boards query": load("boards_query", hand_written=True)})
        events = ao.collect_events("/r", SINCE)
        ids = [e["gh_id"] for e in events]
        assert ids and all(i.startswith("ado-") for i in ids) and not any(i.startswith("gh-") for i in ids)
        assert f"ado-pr-merge:{COMPLETED_IDS[-1]}" in ids
        assert f"ado-deploy:{ENVIRONMENTS[0]['name']}:{RECORDS[0]['id']}" in ids and "ado-wi:1001" in ids
        assert len(ids) == len(set(ids))

    def test_the_gh_mappers_are_what_produce_the_events(self, az, monkeypatch):
        az()
        seen = []
        real = gi.map_merge_event
        monkeypatch.setattr(ao.gi, "map_merge_event", lambda pr, commits: seen.append(pr["number"]) or real(pr, commits))
        ao.collect_events("/r", SINCE)
        assert sorted(seen) == COMPLETED_IDS

    def test_review_wait_without_a_request_moment_omits_wait_hours(self, az):
        vote_only = {"value": [thread("VoteUpdate", "2026-10-05T17:10:00Z", CodeReviewVoteResult="10", CodeReviewVotedByIdentity="1")]}
        az(**{THREADS: vote_only})
        waits = [e for e in ao.collect_events("/r", SINCE) if e["type"] == "review_wait"]
        assert waits and all("wait_hours" not in w for w in waits)  # the key is absent, never None
        assert waits[0]["timestamp"] == "2026-10-05T17:10:00Z" and waits[0]["gh_id"].startswith("ado-pr-review:")

    def test_review_wait_with_a_request_moment_is_measured(self, az):
        both = {"value": [thread("ReviewersUpdate", "2026-10-05T15:10:00Z", CodeReviewReviewersUpdatedNumAdded="1"),
                          thread("VoteUpdate", "2026-10-05T17:10:00Z", CodeReviewVoteResult="10", CodeReviewVotedByIdentity="1")]}
        az(**{THREADS: both})
        wait = next(e for e in ao.collect_events("/r", SINCE) if e["type"] == "review_wait")
        assert wait["wait_hours"] == 2.0 and wait["security"] is False

    def test_an_undatable_approval_leaves_accepted_as_is_unknown_not_true(self, az):
        prs = load("pr_list")
        for pr in prs:
            pr["reviewers"] = [{"uniqueName": "other@example.com", "vote": 10, "isRequired": None, "isContainer": None}]
        az(**{"repos pr list": prs, THREADS: {"value": []}})
        merges = [e for e in ao.collect_events("/r", SINCE) if e["type"] == "spec_merged"]
        assert merges and all(m["accepted_as_is"] is None and "approval time not recorded" in m["note"] for m in merges)

    def test_a_deploy_read_failure_is_a_note_and_no_deploy_events_never_zeros(self, az):
        fake = az()
        fake.fail = {"environments": "TF400813: the environments resource is not available to this identity"}
        report = ao.collect_report("/r", SINCE)
        assert "environments resource" in report["notes"]["deploys"]
        assert not any(e["type"] == "deploy" for e in report["events"])
        assert any(e["type"] == "spec_merged" for e in report["events"])

    def test_an_incident_read_failure_is_a_note(self, az):
        fake = az()
        fake.fail = {"boards query": "VS402337: boards are disabled for this project"}
        assert "VS402337" in ao.collect_report("/r", SINCE)["notes"]["incidents"]

    def test_a_pull_request_read_failure_is_fatal(self, az):
        fake = az()
        fake.fail = {"repos pr list": "az login required"}
        with pytest.raises(AdoImportError, match="az login required"):
            ao.collect_events("/r", SINCE)

    def test_lead_time_is_computed_only_when_the_deployed_sha_matches_a_merge(self, az):
        az()
        deploys = [e for e in ao.collect_events("/r", SINCE) if e["type"] == "deploy"]
        assert deploys and all("lead_time_hours" in d for d in deploys if d["succeeded"])  # every `runs show` answers the captured merge SHA
        ao.clear_caches()  # the SHA cache is per process; a new answer needs a fresh one
        az(**{"pipelines runs show": "0000000000000000000000000000000000000000"})
        deploys = [e for e in ao.collect_events("/r", SINCE) if e["type"] == "deploy"]
        assert deploys and not any("lead_time_hours" in d for d in deploys)
