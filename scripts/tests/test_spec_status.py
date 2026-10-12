"""Tests for spec_status.py — a spec's status, read from its pull request (spec 0006).

The git plumbing for `status: merged` (finalize_merge / read_committed_status) is proven
against a real local git repo, no mocking, in test_spec_status_live.py. This file covers
the verdict-block parser, the waiting-on logic, and orchestration, with every `gh` call
monkeypatched.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import spec_status as ss
from github_import import GitHubImportError


def _hours_ago(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

GRADER_COMMENT = """\
# Grader verdict

Intent: rejects duplicate claims.

| Claim | Verdict | Evidence |
|---|---|---|
| duplicate returns 409 | ✅ met | src/x.py:10 |

Bottom line: LOOKS GOOD

## Acceptance Check Verdicts

| check | covered | reason |
|-------|---------|--------|
| A duplicate submission returns 409 with body `{ "error": "duplicate claim" }` | covered | src/x.py:10 asserts it |
| Two concurrent submissions of the same id persist exactly 1 row | not-covered | no concurrency test |
"""

CHECKS_ALL_GREEN = [
    {"name": "build-and-test", "status": "COMPLETED", "conclusion": "SUCCESS"},
    {"name": "grader", "status": "COMPLETED", "conclusion": "NEUTRAL"},
]

CHECKS_WITH_SECURITY = CHECKS_ALL_GREEN + [
    {"name": "security-review", "status": "COMPLETED", "conclusion": "SUCCESS"},
]


class TestParseVerdictBlock:
    def test_parses_the_block(self):
        verdicts = ss.parse_verdict_block(GRADER_COMMENT)
        assert len(verdicts) == 2
        assert verdicts[0]["covered"] is True
        assert verdicts[1]["covered"] is False
        assert "concurrency" in verdicts[1]["reason"]

    def test_missing_heading_is_none(self):
        assert ss.parse_verdict_block("just some prose, no block") is None

    def test_present_but_empty_block_is_empty_list_not_none(self):
        text = "## Acceptance Check Verdicts\n\nNothing here.\n"
        assert ss.parse_verdict_block(text) == []

    def test_stops_at_next_heading(self):
        text = GRADER_COMMENT + "\n## Something Else\n| a | b |\n|---|---|\n| x | y |\n"
        verdicts = ss.parse_verdict_block(text)
        assert len(verdicts) == 2  # the next heading's table isn't swallowed


class TestFindGraderVerdicts:
    def test_finds_block_in_comments(self, monkeypatch):
        monkeypatch.setattr(ss, "fetch_pr_comment_bodies", lambda repo, n: ["irrelevant", GRADER_COMMENT])
        verdicts, error = ss.find_grader_verdicts(".", 1)
        assert error is None
        assert len(verdicts) == 2

    def test_latest_comment_with_block_wins(self, monkeypatch):
        older = GRADER_COMMENT
        newer = older.replace("not-covered", "covered")
        monkeypatch.setattr(ss, "fetch_pr_comment_bodies", lambda repo, n: [older, newer])
        verdicts, _ = ss.find_grader_verdicts(".", 1)
        assert all(v["covered"] for v in verdicts)

    def test_no_block_anywhere_is_an_error_not_a_crash(self, monkeypatch):
        monkeypatch.setattr(ss, "fetch_pr_comment_bodies", lambda repo, n: ["no block here"])
        verdicts, error = ss.find_grader_verdicts(".", 1)
        assert verdicts is None
        assert "no grader verdict block" in error


class TestComputeWaitingOn:
    def _pr(self, **overrides):
        base = {
            "number": 1, "state": "OPEN", "isDraft": False,
            "statusCheckRollup": [], "reviews": [], "reviewRequests": [],
        }
        return {**base, **overrides}

    def test_merged(self):
        assert ss.compute_waiting_on(".", self._pr(state="MERGED"), None, None) == "merged"

    def test_closed_without_merging(self):
        assert ss.compute_waiting_on(".", self._pr(state="CLOSED"), None, None) == "closed without merging"

    def test_draft(self):
        assert "ready for review" in ss.compute_waiting_on(".", self._pr(isDraft=True), None, None)

    def test_pending_check(self):
        pr = self._pr(statusCheckRollup=[{"name": "build", "status": "IN_PROGRESS", "conclusion": None}])
        assert "build" in ss.compute_waiting_on(".", pr, None, None)

    def test_failing_check(self):
        pr = self._pr(statusCheckRollup=[{"name": "build", "status": "COMPLETED", "conclusion": "FAILURE"}])
        assert "build failed" in ss.compute_waiting_on(".", pr, None, None)

    def test_grader_has_not_run(self):
        pr = self._pr(statusCheckRollup=[{"name": "build", "status": "COMPLETED", "conclusion": "SUCCESS"}])
        assert "grader to run" in ss.compute_waiting_on(".", pr, None, None)

    def test_grader_ran_but_unreadable_verdict(self):
        pr = self._pr(statusCheckRollup=CHECKS_ALL_GREEN)
        assert "readable grader verdict" in ss.compute_waiting_on(".", pr, None, "no block found")

    def test_security_review_required_and_pending(self):
        pr = self._pr(statusCheckRollup=CHECKS_ALL_GREEN + [
            {"name": "security-review", "status": "COMPLETED", "conclusion": "FAILURE"},
        ])
        assert "security review" in ss.compute_waiting_on(".", pr, [], None)

    def test_ready_to_merge_when_approved(self):
        pr = self._pr(statusCheckRollup=CHECKS_WITH_SECURITY, reviews=[{"state": "APPROVED"}])
        assert ss.compute_waiting_on(".", pr, [], None) == "ready to merge"

    def test_waiting_on_named_reviewer_with_age(self, monkeypatch):
        pr = self._pr(
            statusCheckRollup=CHECKS_WITH_SECURITY,
            reviewRequests=[{"login": "priya-n"}],
        )
        monkeypatch.setattr(
            ss, "fetch_pr_events",
            lambda repo, n: [{"event": "review_requested", "created_at": "2020-01-01T00:00:00Z"}],
        )
        result = ss.compute_waiting_on(".", pr, [], None)
        assert "@priya-n" in result and "ago" in result

    def test_waiting_on_reviewer_no_events_omits_age(self, monkeypatch):
        pr = self._pr(statusCheckRollup=CHECKS_WITH_SECURITY, reviewRequests=[{"login": "priya-n"}])
        monkeypatch.setattr(ss, "fetch_pr_events", lambda repo, n: [])
        assert ss.compute_waiting_on(".", pr, [], None) == "waiting for a non-author approval; requested from @priya-n"

    def test_waiting_on_gh_failure_reading_events_is_tolerated(self, monkeypatch):
        pr = self._pr(statusCheckRollup=CHECKS_WITH_SECURITY, reviewRequests=[{"login": "priya-n"}])

        def boom(repo, n):
            raise GitHubImportError("rate limited")
        monkeypatch.setattr(ss, "fetch_pr_events", boom)
        result = ss.compute_waiting_on(".", pr, [], None)
        assert "@priya-n" in result  # degrades to no age, not a crash

    def test_no_reviewer_requested_yet(self):
        pr = self._pr(statusCheckRollup=CHECKS_WITH_SECURITY)
        assert ss.compute_waiting_on(".", pr, [], None) == "waiting for a non-author approval"


class TestSetStatusMerged:
    def test_sets_status_only(self):
        text = '---\nspec: "0007"\nstatus: ready\ndeveloper: "@sam-k"\n---\nbody\n'
        out = ss._set_status_merged(text)
        assert "status: merged" in out
        assert 'developer: "@sam-k"' in out  # untouched

    def test_no_frontmatter_raises(self):
        with pytest.raises(ss.SpecStatusError):
            ss._set_status_merged("no frontmatter here")


class TestReportStatus:
    def test_no_pr_found_reports_cleanly(self, tmp_path, monkeypatch):
        (tmp_path / "specs").mkdir()
        spec_path = tmp_path / "specs" / "0007-x.md"
        spec_path.write_text('---\nspec: "0007"\nname: "x"\nstatus: ready\n---\nbody\n', encoding="utf-8")
        monkeypatch.setattr(ss, "find_pr_for_branch", lambda repo, branch: None)
        result = ss.report_status(tmp_path, spec_path)
        assert result["pull_request"] is None
        assert result["code_host_available"] is True

    def test_no_code_host_access_reports_local_only(self, tmp_path, monkeypatch):
        (tmp_path / "specs").mkdir()
        spec_path = tmp_path / "specs" / "0007-x.md"
        spec_path.write_text('---\nspec: "0007"\nname: "x"\nstatus: in-flight\n---\nbody\n', encoding="utf-8")

        def boom(repo, branch):
            raise GitHubImportError("no network")
        monkeypatch.setattr(ss, "find_pr_for_branch", boom)
        result = ss.report_status(tmp_path, spec_path)
        assert result["code_host_available"] is False
        assert result["local_status"] == "in-flight"
        assert "no network" in result["error"]

    def test_missing_spec_raises(self, tmp_path):
        with pytest.raises(ss.SpecStatusError):
            ss.report_status(tmp_path, tmp_path / "specs" / "nope.md")

    def test_merged_pr_triggers_finalize_merge(self, tmp_path, monkeypatch):
        (tmp_path / "specs").mkdir()
        spec_path = tmp_path / "specs" / "0007-x.md"
        spec_path.write_text('---\nspec: "0007"\nname: "x"\nstatus: in-flight\n---\nbody\n', encoding="utf-8")
        pr = {
            "number": 1, "url": "https://x/pr/1", "state": "MERGED", "mergedAt": "t",
            "isDraft": False, "statusCheckRollup": [], "reviews": [], "reviewRequests": [],
        }
        monkeypatch.setattr(ss, "find_pr_for_branch", lambda repo, branch: pr)
        monkeypatch.setattr(ss, "resolve_base_branch", lambda repo: "main")
        calls = {}

        def fake_finalize(repo, base, path, spec_id):
            calls["called"] = True
            return True, None

        monkeypatch.setattr(ss, "finalize_merge", fake_finalize)
        result = ss.report_status(tmp_path, spec_path)
        assert calls.get("called") is True
        assert result["status_committed_merged"] is True

    def test_grader_not_yet_run_skips_verdict_lookup(self, tmp_path, monkeypatch):
        (tmp_path / "specs").mkdir()
        spec_path = tmp_path / "specs" / "0007-x.md"
        spec_path.write_text('---\nspec: "0007"\nname: "x"\nstatus: in-flight\n---\nbody\n', encoding="utf-8")
        pr = {
            "number": 1, "url": "u", "state": "OPEN", "mergedAt": None, "isDraft": False,
            "statusCheckRollup": [{"name": "build", "status": "COMPLETED", "conclusion": "SUCCESS"}],
            "reviews": [], "reviewRequests": [],
        }
        monkeypatch.setattr(ss, "find_pr_for_branch", lambda repo, branch: pr)

        def boom(*a, **k):
            raise AssertionError("must not fetch grader comments when the grader check hasn't run")
        monkeypatch.setattr(ss, "find_grader_verdicts", boom)
        result = ss.report_status(tmp_path, spec_path)
        assert result["pull_request"]["grader_ran"] is False


class TestFormatReport:
    def test_no_pr(self):
        out = ss.format_report({"spec": "0007", "branch": "spec/0007-x", "code_host_available": True, "pull_request": None})
        assert "No pull request found" in out

    def test_code_host_unavailable(self):
        out = ss.format_report({
            "spec": "0007", "branch": "spec/0007-x", "code_host_available": False,
            "local_status": "in-flight", "error": "no network",
        })
        assert "unavailable" in out
        assert "in-flight" in out

    def test_full_report(self):
        result = {
            "spec": "0007", "branch": "spec/0007-x", "code_host_available": True,
            "pull_request": {
                "number": 1, "url": "https://x/pr/1", "state": "OPEN",
                "checks": [{"name": "build", "status": "COMPLETED", "conclusion": "SUCCESS"}],
                "grader_ran": True, "verdicts": [{"check": "a", "covered": True, "reason": "r"}],
                "verdict_error": None, "security_review": {"conclusion": "SUCCESS"},
                "approvals": [{"by": "priya-n", "at": "t"}],
                "waiting_on": "ready to merge",
            },
            "status_committed_merged": False, "merge_commit_error": None,
        }
        out = ss.format_report(result)
        assert "1/1 acceptance checks covered" in out
        assert "priya-n" in out
        assert "ready to merge" in out


# ---------------------------------------------------------------------------
# The board's bulk mode (spec 0011) — every spec in ONE code-host request
# ---------------------------------------------------------------------------

SPEC_TEXT = """\
---
spec: "0042"
name: "duplicate-claim"
status: in-flight
type: feature
risk: HIGH
owner: "@MCKRUZ"
developer: "@sam-k"
checker: "@priya-n"
team: "claims"
channel: "ag-ui"
created: "2026-09-24"
---

# Spec 0042 — Reject a duplicate claim

## Goal
Something.
"""


def _write_spec(repo, text=SPEC_TEXT, name="0042-duplicate-claim.md"):
    specs = repo / "specs"
    specs.mkdir(exist_ok=True)
    (specs / name).write_text(text, encoding="utf-8")
    return specs / name


class TestSpecTitle:
    def test_strips_the_spec_number_prefix(self):
        assert ss._spec_title(SPEC_TEXT) == "Reject a duplicate claim"

    def test_no_heading_is_empty_not_an_error(self):
        assert ss._spec_title("no heading here") == ""


class TestFetchAllPullRequests:
    def test_keys_by_head_branch(self, monkeypatch):
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [
            {"number": 1, "headRefName": "spec/0001-a"},
            {"number": 2, "headRefName": "spec/0002-b"},
        ])
        by_branch = ss.fetch_all_pull_requests("/repo")
        assert set(by_branch) == {"spec/0001-a", "spec/0002-b"}

    def test_a_reused_branch_reports_its_CURRENT_pull_request(self, monkeypatch):
        # gh lists newest first, so the first occurrence is the live one. Taking the last
        # would report a closed predecessor as the branch's status.
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [
            {"number": 9, "headRefName": "spec/0001-a", "state": "OPEN"},
            {"number": 3, "headRefName": "spec/0001-a", "state": "CLOSED"},
        ])
        assert ss.fetch_all_pull_requests("/repo")["spec/0001-a"]["number"] == 9


class TestReportAll:
    def test_rows_come_from_the_spec_file_itself(self, tmp_path, monkeypatch):
        _write_spec(tmp_path)
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [])
        row = ss.report_all(tmp_path)["specs"][0]
        assert row["spec"] == "0042"
        assert row["title"] == "Reject a duplicate claim"
        assert row["risk"] == "HIGH"
        assert row["team"] == "claims"
        assert row["owner"] == "@MCKRUZ"
        assert row["developer"] == "@sam-k"
        assert row["checker"] == "@priya-n"
        assert row["branch"] == "spec/0042-duplicate-claim"
        assert row["pull_request"] is None

    def test_an_unreachable_code_host_still_returns_every_row(self, tmp_path, monkeypatch):
        # An empty board would read as "there is no work", which is a different claim from
        # "the live half is missing" — so the rows stay and the reason is stated.
        _write_spec(tmp_path)
        def boom(*a, **k):
            raise GitHubImportError("gh: not authenticated")
        monkeypatch.setattr(ss, "gh_json", boom)
        result = ss.report_all(tmp_path)
        assert result["code_host_available"] is False
        assert "not authenticated" in result["error"]
        assert len(result["specs"]) == 1
        assert result["specs"][0]["pull_request"] is None

    def test_matches_a_pull_request_by_the_shared_branch_rule(self, tmp_path, monkeypatch):
        _write_spec(tmp_path)
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [{
            "number": 7, "url": "https://x/7", "state": "OPEN",
            "headRefName": "spec/0042-duplicate-claim",
            "mergedAt": None, "updatedAt": "2026-09-20T10:00:00Z", "isDraft": False,
            "statusCheckRollup": CHECKS_ALL_GREEN, "reviews": [], "reviewRequests": [],
        }])
        pr = ss.report_all(tmp_path)["specs"][0]["pull_request"]
        assert pr["number"] == 7
        assert pr["updated_at"] == "2026-09-20T10:00:00Z"
        assert pr["waiting_on"] == "waiting for a non-author approval"

    def test_bulk_mode_NEVER_writes(self, tmp_path, monkeypatch):
        """A board refreshes on a timer. report_status() commits `status: merged` when it
        sees a merged pull request; doing that from a board would mean the act of LOOKING
        at the work changed the repository. Asserted, not assumed."""
        spec = _write_spec(tmp_path)
        before = spec.read_text(encoding="utf-8")
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [{
            "number": 7, "url": "https://x/7", "state": "MERGED",
            "headRefName": "spec/0042-duplicate-claim",
            "mergedAt": "2026-09-20T10:00:00Z", "updatedAt": "2026-09-20T10:00:00Z",
            "isDraft": False, "statusCheckRollup": CHECKS_ALL_GREEN,
            "reviews": [], "reviewRequests": [],
        }])
        # Any git call at all would be a bug here, so make one fatal.
        monkeypatch.setattr(ss, "run_git", lambda *a, **k: pytest.fail("bulk mode ran git"))

        result = ss.report_all(tmp_path)
        assert result["specs"][0]["pull_request"]["waiting_on"] == "merged"
        assert spec.read_text(encoding="utf-8") == before

    def test_a_spec_with_no_frontmatter_is_reported_not_skipped(self, tmp_path, monkeypatch):
        _write_spec(tmp_path, text="# Just a heading\n", name="0099-broken.md")
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [])
        rows = ss.report_all(tmp_path)["specs"]
        assert len(rows) == 1
        assert "frontmatter" in rows[0]["error"]

    def test_no_specs_directory_is_an_empty_board_not_a_crash(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [])
        assert ss.report_all(tmp_path)["specs"] == []

    def test_readme_is_not_a_spec(self, tmp_path, monkeypatch):
        _write_spec(tmp_path)
        (tmp_path / "specs" / "README.md").write_text("# specs\n", encoding="utf-8")
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [])
        assert len(ss.report_all(tmp_path)["specs"]) == 1


class TestReportAllWaitHours:
    """The real, numeric side of "waiting_on" (spec 0011/0012/0013's shared missing piece):
    how many hours old a pending review request actually is, and whether that is over the
    team's own alarm threshold from cadence-plan.md. This reuses the SAME fetch_pr_events call
    compute_waiting_on's sentence was already making — the point of these tests is proving
    that reuse actually happens, not just that the number comes out right."""

    def _open_pr_awaiting_review(self, **overrides):
        base = {
            "number": 7, "url": "https://x/7", "state": "OPEN",
            "headRefName": "spec/0042-duplicate-claim",
            "mergedAt": None, "updatedAt": "2026-09-20T10:00:00Z", "isDraft": False,
            "statusCheckRollup": CHECKS_WITH_SECURITY,
            "reviews": [], "reviewRequests": [{"login": "priya-n"}], "labels": [],
        }
        return {**base, **overrides}

    def test_over_alarm_when_the_real_wait_exceeds_the_teams_threshold(self, tmp_path, monkeypatch):
        _write_spec(tmp_path)  # team: "claims"
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [self._open_pr_awaiting_review()])
        monkeypatch.setattr(
            ss, "fetch_pr_events",
            lambda repo, n: [{"event": "review_requested", "created_at": _hours_ago(100)}],
        )
        monkeypatch.setattr(
            ss.cadence_plan, "load_limits",
            lambda repo: ({"claims": {"review_alarm_hours": 24, "security_alarm_hours": 48}}, []),
        )
        pr = ss.report_all(tmp_path)["specs"][0]["pull_request"]
        assert pr["wait_hours"] == pytest.approx(100, abs=0.1)
        assert pr["over_alarm"] is True
        # The sentence and the number must describe the same wait, not two different fetches.
        assert "@priya-n" in pr["waiting_on"] and "ago" in pr["waiting_on"]

    def test_under_alarm_when_the_wait_is_within_threshold(self, tmp_path, monkeypatch):
        _write_spec(tmp_path)
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [self._open_pr_awaiting_review()])
        monkeypatch.setattr(
            ss, "fetch_pr_events",
            lambda repo, n: [{"event": "review_requested", "created_at": _hours_ago(1)}],
        )
        monkeypatch.setattr(
            ss.cadence_plan, "load_limits",
            lambda repo: ({"claims": {"review_alarm_hours": 24, "security_alarm_hours": 48}}, []),
        )
        pr = ss.report_all(tmp_path)["specs"][0]["pull_request"]
        assert pr["over_alarm"] is False

    def test_a_high_risk_pr_is_compared_to_the_security_threshold_not_the_review_one(self, tmp_path, monkeypatch):
        _write_spec(tmp_path)
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [
            self._open_pr_awaiting_review(labels=[{"name": "risk:high"}])
        ])
        monkeypatch.setattr(
            ss, "fetch_pr_events",
            lambda repo, n: [{"event": "review_requested", "created_at": _hours_ago(30)}],
        )
        # 30h is over the review threshold but under the (higher) security one.
        monkeypatch.setattr(
            ss.cadence_plan, "load_limits",
            lambda repo: ({"claims": {"review_alarm_hours": 24, "security_alarm_hours": 48}}, []),
        )
        pr = ss.report_all(tmp_path)["specs"][0]["pull_request"]
        assert pr["over_alarm"] is False

    def test_falls_back_to_built_in_defaults_with_no_cadence_plan(self, tmp_path, monkeypatch):
        _write_spec(tmp_path)
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [self._open_pr_awaiting_review()])
        monkeypatch.setattr(
            ss, "fetch_pr_events",
            lambda repo, n: [{"event": "review_requested", "created_at": _hours_ago(30)}],
        )
        # A real project with no cadence-plan.md: load_limits' own documented behaviour.
        monkeypatch.setattr(ss.cadence_plan, "load_limits", lambda repo: ({}, []))
        pr = ss.report_all(tmp_path)["specs"][0]["pull_request"]
        assert ss.cadence_plan.DEFAULT_REVIEW_ALARM_HOURS == 24
        assert pr["over_alarm"] is True  # 30h > the built-in 24h default

    def test_no_pending_reviewer_never_fetches_events_at_all(self, tmp_path, monkeypatch):
        _write_spec(tmp_path)
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [
            self._open_pr_awaiting_review(reviewRequests=[])
        ])
        monkeypatch.setattr(ss, "fetch_pr_events", lambda repo, n: pytest.fail("fetched events with no pending reviewer"))
        pr = ss.report_all(tmp_path)["specs"][0]["pull_request"]
        assert "wait_hours" not in pr

    def test_one_fetch_serves_both_the_sentence_and_the_number(self, tmp_path, monkeypatch):
        """The bug this whole feature nearly introduced: computing the wait a second, separate
        way and paying for a second fetch_pr_events call per pending-review row."""
        _write_spec(tmp_path)
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [self._open_pr_awaiting_review()])
        calls = []

        def counting_fetch(repo, n):
            calls.append(n)
            return [{"event": "review_requested", "created_at": _hours_ago(10)}]
        monkeypatch.setattr(ss, "fetch_pr_events", counting_fetch)
        monkeypatch.setattr(
            ss.cadence_plan, "load_limits",
            lambda repo: ({"claims": {"review_alarm_hours": 24, "security_alarm_hours": 48}}, []),
        )
        pr = ss.report_all(tmp_path)["specs"][0]["pull_request"]
        assert calls == [7]  # exactly one call, for PR #7
        # 10 hours ago humanizes to "today" (_humanize_age works in whole days) — the point
        # here is that BOTH this sentence and wait_hours below came from the one call above.
        assert "wait_hours" in pr and "today" in pr["waiting_on"]


class TestWaitingOnHandle:
    """Structured, so a board never pattern-matches an English sentence to answer
    'is this waiting on me' for hundreds of rows."""

    def _pr(self, **over):
        base = {"state": "OPEN", "isDraft": False, "reviewRequests": []}
        return {**base, **over}

    def test_names_a_requested_reviewer(self):
        pr = self._pr(reviewRequests=[{"login": "priya-n"}])
        assert ss.waiting_on_handle(pr) == "@priya-n"

    def test_falls_back_to_a_team_name_when_there_is_no_login(self):
        pr = self._pr(reviewRequests=[{"name": "platform-reviewers"}])
        assert ss.waiting_on_handle(pr) == "@platform-reviewers"

    def test_nobody_in_particular_is_None_not_a_guess(self):
        # CI, the grader, an unclaimed review — real states, but none of them is a person.
        assert ss.waiting_on_handle(self._pr()) is None

    def test_a_draft_is_waiting_on_nobody(self):
        assert ss.waiting_on_handle(self._pr(isDraft=True, reviewRequests=[{"login": "x"}])) is None

    def test_a_closed_or_merged_pull_request_is_waiting_on_nobody(self):
        for state in ("MERGED", "CLOSED"):
            assert ss.waiting_on_handle(self._pr(state=state, reviewRequests=[{"login": "x"}])) is None

    def test_an_unidentifiable_reviewer_is_None_rather_than_the_word_someone(self):
        assert ss.waiting_on_handle(self._pr(reviewRequests=[{}])) is None


# ---------------------------------------------------------------------------
# Board rows carry the sprint-layer fields; only `NNNN-` files are rows (studio-improvements F4/F10)
# ---------------------------------------------------------------------------

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
HARNESS_TEMPLATE = PLUGIN_ROOT / "harness" / "spec-template.md"

SPEC_WITH_SPRINT_KEYS = SPEC_TEXT.replace(
    "status: in-flight\n",
    'status: in-flight\nsprint: "S07"\nnext_owner: "@sam-k"\neng_review: "@priya-n"\n'
    'data_review: "@dana"\ndepends_on: "0007, 0009"\n',
)


class TestReportAllSprintFields:
    def test_rows_carry_the_sprint_fields_from_the_frontmatter(self, tmp_path, monkeypatch):
        assert "sprint: " in SPEC_WITH_SPRINT_KEYS  # the fixture really has the keys
        _write_spec(tmp_path, text=SPEC_WITH_SPRINT_KEYS)
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [])
        row = ss.report_all(tmp_path)["specs"][0]
        assert row["sprint"] == "S07"
        assert row["next_owner"] == "@sam-k"
        assert row["eng_review"] == "@priya-n"
        assert row["data_review"] == "@dana"
        assert row["depends_on"] == ["0007", "0009"]

    def test_a_spec_without_the_keys_gets_empty_values_not_missing_keys(self, tmp_path, monkeypatch):
        # Additive: a repo that has never run a sprint still gets every key, so a board can
        # read row["sprint"] without a presence check — and "" is honest, where a missing key
        # would be read by some consumers as "unknown" and by others as a crash.
        _write_spec(tmp_path)
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [])
        row = ss.report_all(tmp_path)["specs"][0]
        assert row["sprint"] == ""
        assert row["next_owner"] == ""
        assert row["eng_review"] == ""
        assert row["data_review"] == ""
        assert row["depends_on"] == []

    def test_depends_on_uses_the_sprint_models_parser(self, tmp_path, monkeypatch):
        # One parser for the comma-separated field, so the board and sprint.py agree on what
        # "0007,0007 , 0009" means (deduped, trimmed, order kept).
        text = SPEC_TEXT.replace("status: in-flight\n", 'status: in-flight\ndepends_on: "0007,0007 , 0009"\n')
        assert "depends_on" in text  # the fixture really has the key
        _write_spec(tmp_path, text=text)
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [])
        assert ss.report_all(tmp_path)["specs"][0]["depends_on"] == ["0007", "0009"]

    def test_the_text_report_is_unchanged_by_the_new_keys(self, tmp_path, monkeypatch):
        # The new keys ride the JSON only; the text board a person reads is byte-identical
        # whether or not a spec carries them.
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [])
        _write_spec(tmp_path)
        plain = ss.format_all_report(ss.report_all(tmp_path))
        _write_spec(tmp_path, text=SPEC_WITH_SPRINT_KEYS)
        with_keys = ss.format_all_report(ss.report_all(tmp_path))
        assert plain == with_keys


class TestReportAllOnlyListsSpecFiles:
    """The harness installs specs/spec-template.md beside the real specs. It has frontmatter
    (spec: "NNNN"), so it used to parse as a phantom board row. Only files named like a spec —
    new_spec.SPEC_FILE_RE, `NNNN-` — are rows, the same rule track_specs and sprint.py apply."""

    def test_the_installed_spec_template_is_not_a_board_row(self, tmp_path, monkeypatch):
        _write_spec(tmp_path)
        (tmp_path / "specs" / "spec-template.md").write_bytes(HARNESS_TEMPLATE.read_bytes())
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [])
        rows = ss.report_all(tmp_path)["specs"]
        assert len(rows) == 1
        assert rows[0]["spec"] == "0042"
        assert not any("spec-template" in str(r.get("path", "")) for r in rows)

    def test_other_non_spec_markdown_is_not_a_row_either(self, tmp_path, monkeypatch):
        _write_spec(tmp_path)
        (tmp_path / "specs" / "notes.md").write_text("# scratch\n", encoding="utf-8")
        (tmp_path / "specs" / "readme.md").write_text("# lower-case readme\n", encoding="utf-8")
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [])
        assert len(ss.report_all(tmp_path)["specs"]) == 1

    def test_a_broken_file_that_IS_named_like_a_spec_still_gets_its_error_row(self, tmp_path, monkeypatch):
        # The filter narrows WHICH files are specs; it must not hide a real spec that is
        # unreadable. That row saying "no parseable frontmatter" is the point of the board.
        _write_spec(tmp_path, text="# Just a heading\n", name="0099-broken.md")
        (tmp_path / "specs" / "spec-template.md").write_bytes(HARNESS_TEMPLATE.read_bytes())
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [])
        rows = ss.report_all(tmp_path)["specs"]
        assert [r["path"] for r in rows] == ["0099-broken.md"]
        assert "frontmatter" in rows[0]["error"]


class TestOnAzureDevOps:
    """Additive (code-host providers, Wave 3): the same report over `ado_import`, driven by FakeAz
    on the CAPTURED fixtures. `gh` is never called and bulk mode never runs git; the classes above
    are untouched and the GitHub text is pinned by test_gh_argv_golden.py."""

    BRANCH = "spec/0042-duplicate-claim"

    @pytest.fixture(autouse=True)
    def _ado(self, monkeypatch):
        import ado_import
        import ado_transport
        import code_host
        from tests.ado_fixtures import ADO_REMOTE, FakeAz, load
        ado_import.clear_caches()
        monkeypatch.delenv(code_host.ENV_VAR, raising=False)
        monkeypatch.delenv(code_host.LEGACY_CODE_HOST_ENV, raising=False)
        monkeypatch.setattr(code_host, "origin_url", lambda root: ADO_REMOTE)
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: pytest.fail("gh was called on an Azure DevOps repository"))
        monkeypatch.setattr(ss, "run_git", lambda *a, **k: pytest.fail("bulk mode ran git"))
        self.az = FakeAz()
        # The captured PRs sit on the anonymised `branch-x` (the newest is active); here they are
        # re-labelled onto the spec's branch (handoff.branch_name_for) so the board can match them.
        # Derived, and said so.
        self.prs = [{**p, "sourceRefName": f"refs/heads/{self.BRANCH}"} for p in load("pr_list")]
        self.az.answers["repos pr list"] = lambda args: (
            self.prs if "--source-branch" not in args or args[args.index("--source-branch") + 1] == self.BRANCH else [])
        monkeypatch.setattr(ado_transport, "az_json", self.az)
        yield
        ado_import.clear_caches()

    def _roster(self, repo):
        (repo / ".sdlc").mkdir(exist_ok=True)
        (repo / ".sdlc" / "team.yaml").write_text(
            "people:\n  - handle: '@priya-n'\n    name: Priya\n    team: claims\n    roles: [checker]\n"
            "    email: person2@example.com\nteams:\n  - name: claims\n    lead: '@priya-n'\n", encoding="utf-8")

    def test_single_spec_is_read_through_az_and_carries_the_host_block(self, tmp_path):
        spec = _write_spec(tmp_path)
        import ado_import
        from tests.ado_fixtures import load
        result = ss.report_status(tmp_path, spec)
        pr = result["pull_request"]
        newest = max(self.prs, key=lambda p: p["pullRequestId"])  # the captured branch's newest PR is active
        assert newest["status"] == "active"
        assert result["code_host_available"] is True and pr["number"] == newest["pullRequestId"] and pr["state"] == "OPEN"
        # Captured: `pr policy list` on the active PR is [] — no policy on its target branch, so no checks (not "unknown").
        assert sorted(c["name"] for c in pr["checks"]) == sorted(c["name"] for c in ado_import.map_checks(load("pr_policy_list")))
        assert pr["waiting_on"] == "waiting for the grader to run"  # no check named `grader` among the policies
        assert pr["url"] == f"https://dev.azure.com/contoso/Claims/_git/claims-api/pullrequest/{newest['pullRequestId']}"
        assert result["host"] == {"name": "azure-devops", "source": "remote", "cli": "az", "cli_state": "available",
                                  "detail": "from origin https://dev.azure.com/contoso/Claims/_git/claims-api"}
        text = ss.format_report(result)
        assert text.splitlines()[-1] == "Code host: azure-devops (from origin)"
        assert any(c[:4] == ["repos", "pr", "policy", "list"] for c in self.az.calls)

    def test_approvals_carry_a_null_time_and_the_roster_handle(self, tmp_path):
        self._roster(tmp_path)
        approved = {**self.prs[0], "reviewers": [{**self.prs[0]["reviewers"][0], "vote": 10}]}  # person2 approves (derived)
        self.az.answers["repos pr list"] = lambda args: [approved]
        result = ss.report_status(tmp_path, _write_spec(tmp_path))
        assert result["pull_request"]["approvals"] == [{"by": "person2@example.com", "at": None, "handle": "@priya-n"}]
        text = ss.format_report(result)
        assert "  Approved by: @priya-n (person2@example.com) (time not recorded by Azure DevOps)" in text

    def test_board_rows_past_the_checks_cap_say_live_checks_not_read(self, tmp_path, monkeypatch):
        import ado_import
        monkeypatch.setattr(ado_import, "ADO_CHECKS_MAX", 0)
        self._roster(tmp_path)
        _write_spec(tmp_path)
        result = ss.report_all(tmp_path)
        assert result["code_host_available"] is True and result["host"]["name"] == "azure-devops"
        pr = result["specs"][0]["pull_request"]
        assert pr["waiting_on"] == "live checks not read for this row"
        assert pr["updated_at"] is None  # GitPullRequest has no last-moved field; "unknown", not creationDate
        assert pr["waiting_on_handle"] == "@priya-n"  # the roster handle, not the UPN
        # The review-request moment comes from the ReviewersUpdate thread (captured), so an age IS known here.
        assert "wait_hours" in pr and pr["wait_hours"] > 0 and isinstance(pr["over_alarm"], bool)
        assert not any(c[:4] == ["repos", "pr", "policy", "list"] for c in self.az.calls)
        text = ss.format_all_report(result)
        assert "live checks not read for this row" in text and text.splitlines()[-1] == "Code host: azure-devops (from origin)"

    def test_board_rows_under_the_cap_read_the_ladder(self, tmp_path):
        _write_spec(tmp_path)
        pr = ss.report_all(tmp_path)["specs"][0]["pull_request"]
        assert pr["waiting_on"] == "waiting for the grader to run"
        assert pr["waiting_on_handle"] == "@person2@example.com"  # no roster: the UPN is what is known

    def test_no_request_timestamp_means_the_keys_are_absent_not_zero(self, tmp_path):
        from tests.ado_fixtures import load
        self.az.answers["devops invoke git pullRequestThreads"] = load("pr_threads_active")  # RefUpdate only
        _write_spec(tmp_path)
        pr = ss.report_all(tmp_path)["specs"][0]["pull_request"]
        assert "wait_hours" not in pr and "over_alarm" not in pr
        assert ss.format_all_report(ss.report_all(tmp_path)).count("h]") == 0

    def test_an_az_failure_is_code_host_available_false_with_the_az_detail(self, tmp_path):
        self.az.fail["repos pr list"] = "ERROR: Please run 'az login' to setup account."
        result = ss.report_status(tmp_path, _write_spec(tmp_path))
        assert result["code_host_available"] is False and "az login" in result["error"]
        assert result["host"]["cli_state"] == "signed_out" and result["host"]["cli"] == "az"
        text = ss.format_report(result)
        assert "Code-host data unavailable" in text and text.splitlines()[-1] == "Code host: azure-devops (from origin)"
        board = ss.report_all(tmp_path)
        assert board["code_host_available"] is False and board["specs"][0]["pull_request"] is None
        assert board["host"]["cli_state"] == "signed_out"

    def test_no_pull_request_is_a_clean_answer(self, tmp_path):
        self.az.answers["repos pr list"] = lambda args: []
        result = ss.report_status(tmp_path, _write_spec(tmp_path))
        assert result["code_host_available"] is True and result["pull_request"] is None
        assert "No pull request found for this branch." in ss.format_report(result)

    def test_reviewer_handle_prefers_the_roster_handle(self):
        assert ss._reviewer_handle({"login": "person2@example.com", "handle": "@priya-n"}) == "priya-n"
        assert ss._reviewer_handle({"login": "person2@example.com", "handle": None}) == "person2@example.com"
        assert ss._reviewer_handle({"login": "priya-n"}) == "priya-n"  # gh entries: unchanged

    def test_host_flag_github_on_an_ado_remote_uses_gh(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [])
        _write_spec(tmp_path)
        result = ss.report_all(tmp_path, host="github")
        assert result["host"]["name"] == "github" and result["host"]["source"] == "flag"
        assert not self.az.calls and result["specs"][0]["pull_request"] is None
        assert "Code host:" not in ss.format_all_report(result)


# ---------------------------------------------------------------------------
# SDLC Studio command center (togo-command-center.md §2.5 row 10): the row carries `deferred_reason`
# ---------------------------------------------------------------------------

class TestReportAllDeferredReason:
    def test_a_deferred_spec_carries_its_reason_verbatim(self, tmp_path, monkeypatch):
        text = SPEC_TEXT.replace("status: in-flight\n",
                                 "status: deferred\ndeferred_reason: 'the upstream service slipped a quarter'\n")
        _write_spec(tmp_path, text=text)
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [])
        row = ss.report_all(tmp_path)["specs"][0]
        assert row["status"] == "deferred"
        assert row["deferred_reason"] == "the upstream service slipped a quarter"

    def test_a_spec_without_the_key_reads_empty_not_missing(self, tmp_path, monkeypatch):
        _write_spec(tmp_path)
        monkeypatch.setattr(ss, "gh_json", lambda *a, **k: [])
        row = ss.report_all(tmp_path)["specs"][0]
        assert row["deferred_reason"] == ""
        # Every key the row had before is still there, in the same order, with the new one before `branch`.
        keys = list(row)
        assert keys.index("deferred_reason") == keys.index("branch") - 1
        assert keys[:3] == ["spec", "name", "path"] and keys[-2:] == ["branch", "pull_request"]
