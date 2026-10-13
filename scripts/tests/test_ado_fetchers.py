"""Tests for ado_import.py's fetchers and writes — every az-touching function, driven by FakeAz
over the CAPTURED fixtures (ado_fixtures.DEFAULT_ANSWERS).

The second half of test_ado_import.py (split for file size): `FakeAz` stands in for
`ado_transport.az_json`, the ONE seam, and raises on any call it was not told about — that
AssertionError is the read-only pin. Expected ids and counts are derived from the fixture, so a
re-capture changes the data, not the assertions. No test here spawns a real az.
"""

import pytest

import ado_import as ai
import ado_map
import ado_transport
import code_host
from tests.ado_fixtures import (
    ADO_REMOTE, FakeAz, arg_after, captured_pr, command_of, load, project_pipelines, repo_pipelines, route_param,
)

ROSTER = "people:\n  - handle: '@priya-n'\n    name: Priya\n    team: core\n    roles: [checker]\n    email: person2@example.com\n  - handle: '@sam-k'\n    name: Sam\n    team: core\n    roles: [developer]\nteams:\n  - name: core\n    lead: '@priya-n'\n"
REMOTE = code_host.parse_remote(ADO_REMOTE)
ACTIVE = captured_pr("active")
BRANCH = ado_map.strip_ref(ACTIVE["sourceRefName"])  # every captured PR sits on it (anonymised); the newest is active
NEWEST = max(load("pr_list"), key=lambda p: p["pullRequestId"])
REPO = load("repos_show")
THREADS_PR = int(route_param("pr_threads", "pullRequestId"))        # the PR the default threads answer was captured for
GATE_PR = int(route_param("pr_threads_abandoned", "pullRequestId"))  # the PR carrying the gate comments (first capture)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    ai.clear_caches()
    for name in code_host.CODE_HOST_ENV_VARS:  # both SHEPHERD_CODE_HOST and the older SDLC_CODE_HOST
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(code_host, "origin_url", lambda root: ADO_REMOTE)
    yield
    ai.clear_caches()


@pytest.fixture
def az(monkeypatch):
    fake = FakeAz()
    monkeypatch.setattr(ado_transport, "az_json", fake)
    return fake


def _bound_here(show_answer, *definition_ids):
    """A `pipelines show` answer that binds the named definitions to the test repository (DERIVED —
    the capture has them on sibling repositories), so the project-wide fallback keeps them."""
    def answer(args):
        rec = show_answer(args)
        if int(arg_after(args, "--id") or 0) in definition_ids:
            rec = {**rec, "repository": {**(rec.get("repository") or {}), "id": REPO["id"], "name": REPO["name"]}}
        return rec
    return answer


class TestFetchers:
    def test_find_pr_for_branch_takes_the_newest_and_reads_policies_only_when_active(self, tmp_path, az):
        assert NEWEST["status"] == "active" and all(p["sourceRefName"] == f"refs/heads/{BRANCH}" for p in load("pr_list"))
        pr = ai.find_pr_for_branch(tmp_path, BRANCH)
        assert pr["number"] == NEWEST["pullRequestId"] and pr["state"] == "OPEN"
        assert pr["statusCheckRollup"] == ai.map_checks(load("pr_policy_list"))  # captured: [] — no policy on the target branch
        assert az.count("repos", "pr", "policy", "list") == 1 and "_checks_unavailable" not in pr
        az.calls.clear()
        az.answers["repos pr list"] = lambda args: [load("pr_show_completed")] if BRANCH in args else []
        merged = ai.find_pr_for_branch(tmp_path, BRANCH)
        assert merged["state"] == "MERGED" and merged["statusCheckRollup"] == []
        assert az.count("repos", "pr", "policy", "list") == 0
        assert ai.find_pr_for_branch(tmp_path, "spec/9999-none") is None

    def test_an_active_pr_whose_target_has_policies_carries_them_as_checks(self, tmp_path, az):
        """The abandoned PR's evaluation records (first capture) stand in for a target branch WITH policies."""
        az.answers["repos pr policy list"] = load("pr_policy_list_abandoned")
        pr = ai.find_pr_for_branch(tmp_path, BRANCH)
        expected = sorted(c["name"] for c in ai.map_checks(load("pr_policy_list_abandoned")))
        assert expected and sorted(c["name"] for c in pr["statusCheckRollup"]) == expected and "_checks_unavailable" not in pr

    def test_an_active_pr_with_no_policies_has_no_checks_not_unknown_checks(self, tmp_path, az):
        az.answers["repos pr policy list"] = []
        pr = ai.find_pr_for_branch(tmp_path, BRANCH)
        assert pr["statusCheckRollup"] == [] and "_checks_unavailable" not in pr and pr["_notes"] == []

    def test_threads_are_fetched_once_for_bodies_and_events_and_the_repo_record_once(self, tmp_path, az):
        threads = load("pr_threads")
        text = sorted(((c["publishedDate"], c["content"]) for t in threads["value"] for c in t["comments"]
                       if c["commentType"] == "text"))
        assert ai.fetch_pr_comment_bodies(tmp_path, THREADS_PR) == [body for _, body in text]
        events = ai.fetch_pr_events(str(tmp_path), THREADS_PR)
        first = next(t for t in threads["value"] if ado_map.thread_property(t, "CodeReviewThreadType") == "ReviewersUpdate")
        assert events[0]["event"] == "review_requested" and events[0]["created_at"] == first["publishedDate"]
        invokes = [c for c in az.calls if c[:2] == ["devops", "invoke"]]
        assert len(invokes) == 1 and invokes[0][invokes[0].index("--api-version") + 1] == "7.1"
        route = invokes[0][invokes[0].index("--route-parameters") + 1:invokes[0].index("--api-version")]
        assert route == ["project=Claims", f"repositoryId={REPO['id']}", f"pullRequestId={THREADS_PR}"]
        ai.fetch_pr_comment_bodies(tmp_path, GATE_PR)
        assert az.count("repos", "show") == 1  # the repository GUID is read once per process

    def test_gate_comment_bodies_reach_the_caller_marker_first(self, tmp_path, az):
        az.answers["devops invoke git pullRequestThreads"] = load("pr_threads_abandoned")
        bodies = ai.fetch_pr_comment_bodies(tmp_path, GATE_PR)
        assert [b.split("\n", 1)[0] for b in bodies] == ["<!-- rails-gate:pipeline-7 -->", "<!-- rails-gate:pipeline-4 -->",
                                                         "<!-- rails-gate:pipeline-8 -->"]

    def test_fetch_all_keys_by_branch_and_marks_rows_past_the_checks_cap(self, tmp_path, az, monkeypatch):
        monkeypatch.setattr(ai, "ADO_CHECKS_MAX", 0)
        rows = ai.fetch_all_pull_requests(tmp_path)
        assert set(rows) == {BRANCH} and rows[BRANCH]["number"] == NEWEST["pullRequestId"]  # newest per branch wins
        assert rows[BRANCH]["_checks_unavailable"] is True
        listing = next(c for c in az.calls if c[:3] == ["repos", "pr", "list"])
        assert "--query" in listing and "--skip" in listing and az.count("repos", "pr", "policy", "list") == 0

    def test_fetch_all_reads_checks_for_active_rows_under_the_cap_and_never_for_merged_ones(self, tmp_path, az):
        completed = {**load("pr_show_completed"), "sourceRefName": "refs/heads/spec/0041-done"}
        az.answers["repos pr list"] = lambda args: [*load("pr_list"), completed]
        rows = ai.fetch_all_pull_requests(tmp_path)
        assert rows[BRANCH]["state"] == "OPEN" and "_checks_unavailable" not in rows[BRANCH]
        assert rows[BRANCH]["statusCheckRollup"] == ai.map_checks(load("pr_policy_list"))  # read for the active row …
        assert rows["spec/0041-done"]["state"] == "MERGED" and "_checks_unavailable" not in rows["spec/0041-done"]
        assert az.count("repos", "pr", "policy", "list") == 1  # … once, and never for the merged one

    def test_branch_policies_are_scoped_to_the_repository_and_default_branch(self, tmp_path, az):
        configs = load("policy_list")  # captured: [] on this repository's default branch
        rs = ai.fetch_branch_policies(str(tmp_path), "contoso/Claims/claims-api", None)
        assert rs["enforcement"] == ("active" if any(c.get("isEnabled") and c.get("isBlocking") for c in configs) else "disabled")
        call = next(c for c in az.calls if c[:3] == ["repos", "policy", "list"])
        assert call[call.index("--repository-id") + 1] == REPO["id"]
        assert call[call.index("--branch") + 1] == ado_map.strip_ref(REPO["defaultBranch"])  # repos show: defaultBranch

    def test_whoami_is_the_upn_with_its_tenant_and_a_pat_only_session_is_an_error(self, tmp_path, az):
        acct = load("account_show")
        who = ai.whoami(tmp_path)
        assert who["login"] == acct["user"]["name"] and who["kind"] == "upn" and who["tenant"] == acct["tenantId"]
        az.answers["account show"] = {}
        with pytest.raises(ai.AdoImportError, match="PAT only"):
            ai.whoami(tmp_path)

    def test_display_name_is_optional_and_silent_on_access_denied(self, tmp_path, az):
        az.fail["devops user show"] = "Access Denied: needs ReadExtended Users"  # captured outcome, both times
        assert ai.display_name(tmp_path, "person3@example.com") is None
        az.fail.clear()
        az.answers["devops user show"] = {"user": {"displayName": "Person 3", "principalName": "person3@example.com"}}
        assert ai.display_name(tmp_path, "person3@example.com") == "Person 3"

    def test_repo_view(self, tmp_path, az):
        view = ai.repo_view(tmp_path)
        assert view["nameWithOwner"] == "contoso/Claims/claims-api"
        assert view["defaultBranch"] == ado_map.strip_ref(REPO["defaultBranch"]) and view["defaultBranch"]
        assert view["id"] == REPO["id"] and view["viewerPermission"] is None and view["webUrl"] == REPO["webUrl"]

    def test_an_unexpected_call_is_pinned(self, tmp_path, az):
        with pytest.raises(AssertionError, match="unexpected az call"):
            ado_transport.az_json(["repos", "pr", "set-vote", "--id", "1"], tmp_path)


class TestWrites:
    def _creates(self, az):
        az.answers["repos pr create"] = 77
        az.answers["repos pr update"] = {"status": "completed"}

    def test_create_draft_pr_names_the_developer_and_uses_the_checker_email(self, tmp_path, az):
        self._creates(az)
        (tmp_path / ".sdlc").mkdir()
        (tmp_path / ".sdlc" / "team.yaml").write_text(ROSTER, encoding="utf-8")
        url = ai.create_draft_pr(tmp_path, "spec/0007-x", "main", "0007", "x", "@sam-k", "@priya-n")
        assert url == f"{ADO_REMOTE}/pullrequest/77"
        call = next(c for c in az.calls if c[:3] == ["repos", "pr", "create"])
        assert call[call.index("--draft") + 1] == "true"
        assert call[call.index("--required-reviewers") + 1] == "person2@example.com"
        assert "Developer: @sam-k" in call and "--assignee" not in call
        assert call[call.index("--source-branch") + 1] == "spec/0007-x" and call[call.index("--target-branch") + 1] == "main"

    def test_a_checker_without_an_email_still_gets_a_pr_and_the_description_says_so(self, tmp_path, az):
        self._creates(az)
        ai.create_draft_pr(tmp_path, "spec/0007-x", "main", "0007", "x", "@sam-k", "@priya-n")
        call = next(c for c in az.calls if c[:3] == ["repos", "pr", "create"])
        assert "--required-reviewers" not in call
        assert any("no email in .sdlc/team.yaml" in a for a in call)

    def test_no_checker_means_no_reviewer_flag(self, tmp_path, az):
        self._creates(az)
        ai.create_draft_pr(tmp_path, "spec/0007-x", "main", "0007", "x", "@sam-k", "")
        call = next(c for c in az.calls if c[:3] == ["repos", "pr", "create"])
        assert "--required-reviewers" not in call and "Checker" not in " ".join(call)

    def test_complete_pr(self, tmp_path, az):
        self._creates(az)
        assert ai.complete_pr(tmp_path, 42) == f"{ADO_REMOTE}/pullrequest/42"
        call = next(c for c in az.calls if c[:3] == ["repos", "pr", "update"])
        assert call[call.index("--status") + 1] == "completed"


class TestPipelines:
    def test_the_repository_filter_answers_nothing_so_definitions_come_from_the_project_wide_list(self, tmp_path, az):
        """Second capture: `pipelines list --repository R --repository-type tfsgit` returned [] for a
        repository that has pipelines project-wide, so the filter is not trusted. When it answers
        nothing, the project-wide list is read and each definition is kept only if its `show` binds
        it to this repository (GUID or name) — a sibling repository's pipeline is never ours."""
        assert load("pipelines_list") == [] and "--repository" in command_of("pipelines_list")
        bound, everything = repo_pipelines(), project_pipelines()
        sibling = [d for d in everything if d not in bound]
        assert bound and sibling and all("process" not in d and "repository" not in d for d in everything)
        for d in bound:
            assert ai.find_definition(str(tmp_path), f"{d['name']}.yml")["id"] == d["id"]
        for d in sibling:
            assert ai.find_definition(str(tmp_path), f"{d['name']}.yml") is None
        lists = [c for c in az.calls if c[:2] == ["pipelines", "list"]]
        assert [("--repository" in c) for c in lists] == [True, False]  # the filtered read, then the project-wide fallback, once
        assert az.count("pipelines", "show") == len(everything)  # one show per project-wide definition, cached
        assert az.count("repos", "show") == 1  # the repository GUID it matches on is read once

    def test_a_non_empty_repository_filter_is_trusted_and_the_project_wide_list_is_not_read(self, tmp_path, az):
        az.answers["pipelines list"] = lambda args: (repo_pipelines() if "--repository" in args
                                                     else pytest.fail("project-wide list read although the filter answered"))
        target = repo_pipelines()[0]
        assert ai.find_definition(str(tmp_path), f"{target['name']}.yml")["id"] == target["id"]
        assert az.count("pipelines", "list") == 1

    def test_runs_match_the_yaml_file_through_pipelines_show_then_the_name(self, tmp_path, az):
        """`pipelines list` has no `process` (captured); the YAML path is one `show` per definition, cached."""
        for d in repo_pipelines():
            runs = ai.fetch_runs(str(tmp_path), f"{d['name']}.yml", 10)
            call = [c for c in az.calls if c[:3] == ["pipelines", "runs", "list"]][-1]
            assert call[call.index("--pipeline-ids") + 1] == str(d["id"]) and call[call.index("--top") + 1] == "10"
            assert runs == ai.map_runs(load("runs_list"), REMOTE)  # captured: a definition with no runs answers [] — a real empty
        assert az.count("pipelines", "list") == 2 and az.count("pipelines", "show") == len(project_pipelines())  # cached across rails

    def test_the_captured_build_maps_through_fetch_runs(self, tmp_path, az):
        """The one captured Build (`runs show`) is served as its definition's history (derived). The capture
        has that definition on a sibling repository, so it is bound here to reach it through the fallback."""
        build = load("runs_show")
        az.answers["pipelines show"] = _bound_here(az.answers["pipelines show"], build["definition"]["id"])
        runs = ai.fetch_runs(str(tmp_path), f"{build['definition']['name']}.yml", 10)
        assert [r["databaseId"] for r in runs] == [build["id"]]
        assert runs[0]["conclusion"] == ado_map.RUN_RESULT[build["result"]]
        assert runs[0]["url"].endswith(f"/_build/results?buildId={build['id']}")

    def test_a_nested_yaml_is_not_mistaken_for_the_flat_gate_file(self, tmp_path, az):
        shown = load("pipelines_show")  # `backend/ci-cd.yml` — a sibling's in this capture, bound here (derived) for the PATH rule
        assert shown["process"]["yamlFilename"].replace("\\", "/").endswith("/backend/ci-cd.yml")
        az.answers["pipelines show"] = _bound_here(az.answers["pipelines show"], shown["id"])
        assert ai.find_definition(str(tmp_path), "backend/ci-cd.yml")["id"] == shown["id"]
        with pytest.raises(ai.AdoImportError, match="pipeline definition for `ci-cd.yml` not found in Azure Pipelines"):
            ai.fetch_runs(str(tmp_path), "ci-cd.yml", 10)  # backend/ci-cd.yml is another file

    def test_a_definition_named_like_the_stem_is_the_fallback(self, tmp_path, az):
        default = az.answers["pipelines show"]
        az.answers["pipelines show"] = lambda args: {**default(args), "process": {"type": 1}}  # no YAML anywhere (derived)
        target = repo_pipelines()[0]
        ai.fetch_runs(str(tmp_path), f"{target['name']}.yml", 10)
        call = next(c for c in az.calls if c[:3] == ["pipelines", "runs", "list"])
        assert call[call.index("--pipeline-ids") + 1] == str(target["id"])

    def test_no_definition_for_this_repository_is_said_only_after_the_fallback(self, tmp_path, az):
        bound = repo_pipelines()
        az.answers["pipelines list"] = lambda args: [] if "--repository" in args else [d for d in project_pipelines() if d not in bound]
        with pytest.raises(ai.AdoImportError) as e:
            ai.fetch_runs(str(tmp_path), "ci.yml", 10)
        assert "pipeline definition for `ci.yml` not found in Azure Pipelines" in str(e.value)  # what pipeline_proof renders as NO_DATA
        assert "no pipeline definition found for claims-api in project Claims" in str(e.value)
        assert [("--repository" in c) for c in az.calls if c[:2] == ["pipelines", "list"]] == [True, False]
        # With definitions bound to the repository, a missing FILE is just that — the repository is not blamed.
        ai.clear_caches()
        az.answers["pipelines list"] = lambda args: [] if "--repository" in args else project_pipelines()
        with pytest.raises(ai.AdoImportError) as e:
            ai.fetch_runs(str(tmp_path), "security.yml", 10)
        assert str(e.value) == "pipeline definition for `security.yml` not found in Azure Pipelines"

    def test_run_jobs(self, tmp_path, az):
        timeline = load("timeline")
        build_id = int(route_param("timeline", "buildId"))
        jobs = ai.run_jobs(str(tmp_path), build_id)["jobs"]
        assert jobs and jobs == [{"name": r["name"], "conclusion": ado_map.RUN_RESULT[r["result"]]}
                                 for r in timeline["records"] if r["type"] == "Job"]
        call = next(c for c in az.calls if c[:2] == ["devops", "invoke"])
        assert f"buildId={build_id}" in call

    def test_secret_names_reads_only_the_groups_the_pipelines_reference(self, tmp_path, az):
        folder = tmp_path / ".azuredevops" / "pipelines"
        folder.mkdir(parents=True)
        # The group the pipeline references and the variable names come FROM the fixture, so a
        # re-capture (or a re-scrub that renames groups and variables) cannot break this test.
        groups = load("variable_groups")
        referenced = groups[1]
        expected = sorted(load("variable_group_variables").keys())
        (folder / "grader.yml").write_text(f"variables:\n  - group: {referenced['name']}\n"
                                           "  - group: <<TOKEN>>\n", encoding="utf-8")
        names = ai.secret_names(tmp_path)
        assert sorted(names) == expected and len(names) == len(expected)
        variable_calls = [c for c in az.calls if c[:4] == ["pipelines", "variable-group", "variable", "list"]]
        assert [c[c.index("--group-id") + 1] for c in variable_calls] == [str(referenced["id"])]

    def test_no_referenced_group_falls_back_to_every_group(self, tmp_path, az):
        ai.secret_names(tmp_path)
        variable_calls = [c for c in az.calls if c[:4] == ["pipelines", "variable-group", "variable", "list"]]
        assert sorted(c[c.index("--group-id") + 1] for c in variable_calls) == ["267", "268"]


class TestListPullRequests:
    def test_every_pr_newest_first_without_the_branch_fold_or_any_checks_read(self, tmp_path, az):
        prs = ai.list_pull_requests(tmp_path, 100)
        assert [p["number"] for p in prs] == sorted((p["pullRequestId"] for p in load("pr_list")), reverse=True)
        merged = sum(1 for p in load("pr_list") if p["status"] == "completed")
        assert merged and sum(1 for p in prs if p["mergedAt"]) == merged and all(p["statusCheckRollup"] == [] for p in prs)
        assert az.count("repos", "pr", "policy", "list") == 0
        listing = next(c for c in az.calls if c[:3] == ["repos", "pr", "list"])
        assert listing[listing.index("--top") + 1] == "100"
