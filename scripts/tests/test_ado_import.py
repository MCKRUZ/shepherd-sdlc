"""Tests for ado_import.py — the az transport and the pure normalisers, on CAPTURED az output.

Mirrors test_github_import.py: the transport is tested through a monkeypatched subprocess.run,
the normalisers on fixture JSON. `load(name)` reads the captured file (real `az` output,
anonymised — CAPTURE-NOTES.md) whenever one exists; `load(name, hand_written=True)` reaches the
older hand-written document only for the shapes no real organisation exercised (a draft PR, an
unknown status, a `rejected` policy evaluation), and says so in the test name. Expected ids,
counts and timestamps are DERIVED from the fixture (`captured_pr`, `route_param`) so a re-capture
changes the data, not the assertions. No test here spawns a real az.
"""

import subprocess

import pytest

import ado_import as ai
import ado_transport
import code_host
import github_import
from tests.ado_fixtures import ADO_REMOTE, arg_after, captured_pr, captured_prs, command_of, load, route_param, source_of

REMOTE = code_host.parse_remote(ADO_REMOTE)
ACTIVE = captured_pr("active")                            # the newest active PR in the capture
TRIAL = captured_pr("active", mergeStatus="succeeded")    # an active PR carrying its trial merge (P7)
MERGED = captured_pr("completed")
ABANDONED = captured_pr("abandoned")                      # lives only in pr_show_abandoned (first capture)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    ai.clear_caches()
    for name in code_host.CODE_HOST_ENV_VARS:  # both SHEPHERD_CODE_HOST and the older SDLC_CODE_HOST
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(code_host, "origin_url", lambda root: ADO_REMOTE)
    yield
    ai.clear_caches()


class TestRunAz:
    def test_env_flags_binary_and_timeout(self, monkeypatch):
        seen = {}

        def fake_run(cmd, **kwargs):
            seen.update(cmd=cmd, **kwargs)
            return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")
        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(ado_transport.shutil, "which", lambda n: r"C:\Tools\az.cmd")
        assert ai.run_az(["repos", "pr", "list"], cwd="/repo") == "[]"
        assert seen["cmd"] == [r"C:\Tools\az.cmd", "repos", "pr", "list", "--only-show-errors"]
        assert seen["env"]["AZURE_EXTENSION_USE_DYNAMIC_INSTALL"] == "no"
        assert seen["env"]["AZURE_CORE_COLLECT_TELEMETRY"] == "no"
        assert seen["encoding"] == "utf-8" and seen["timeout"] == 60 and seen["cwd"] == "/repo"

    def test_az_missing_raises_clear_message(self, monkeypatch):
        def fake_run(*a, **k):
            raise FileNotFoundError()
        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(ai.AdoImportError, match="not installed"):
            ai.run_az(["account", "show"], cwd=".")

    def test_timeout_raises_clear_message(self, monkeypatch):
        def fake_run(*a, **k):
            raise subprocess.TimeoutExpired(cmd="az", timeout=60)
        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(ai.AdoImportError, match="timed out"):
            ai.run_az(["account", "show"], cwd=".")

    def test_nonzero_exit_raises_with_stderr_and_an_extension_hint(self, monkeypatch):
        def fake_run(cmd, **k):
            return subprocess.CompletedProcess(cmd, 1, "", "ERROR: 'repos' is misspelled or not recognized; azure-devops extension")
        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(ai.AdoImportError, match="az extension add --name azure-devops"):
            ai.run_az(["repos", "show"], cwd=".")

    def test_an_unmaterialized_identity_403_says_what_to_do(self, monkeypatch):
        """Captured: a tenant identity that never opened the org in a browser gets this 403, and az's
        DEFAULT account is what decided the token — the raw text says neither."""
        def fake_run(cmd, **k):
            return subprocess.CompletedProcess(cmd, 1, "", 'ERROR: HTTP 403 "Identity x has not been materialized, '
                                               'please use interactive login over the browser first."')
        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(ai.AdoImportError, match="default account decides the token") as e:
            ai.run_az(["repos", "show"], cwd=".")
        assert "--allow-no-subscriptions" in str(e.value) and "materialized" in str(e.value)

    def test_az_json_adds_output_json_and_parses(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(ado_transport, "run_az", lambda args, cwd, timeout=60: seen.setdefault("args", args) and '{"a": 1}')
        assert ai.az_json(["account", "show"], cwd=".") == {"a": 1}
        assert seen["args"][-2:] == ["-o", "json"]

    def test_az_json_empty_stdout_is_an_empty_list_and_garbage_raises(self, monkeypatch):
        """`az boards query` prints nothing when no work item matches (captured) — that is `[]`."""
        monkeypatch.setattr(ado_transport, "run_az", lambda args, cwd, timeout=60: "  ")
        assert ai.az_json(["boards", "query"], cwd=".") == []
        assert load("boards_query") == [] and source_of("boards_query") == "captured"
        monkeypatch.setattr(ado_transport, "run_az", lambda args, cwd, timeout=60: "not json")
        with pytest.raises(ai.AdoImportError, match="unparseable"):
            ai.az_json(["x"], cwd=".")

    def test_error_type_is_a_github_import_error(self):
        assert issubclass(ai.AdoImportError, github_import.GitHubImportError)

    def test_the_environments_area_uses_the_preview_version_only_there(self, monkeypatch):
        """`7.1-preview.1` crashes the extension (captured); `7.1` is right everywhere else."""
        seen = []
        monkeypatch.setattr(ado_transport, "az_json", lambda args, cwd: seen.append(args) or {})
        ado_transport.invoke("/r", "distributedtask", "environments", {"project": "P"}, api_version=ai.PREVIEW_API_VERSION)
        ado_transport.invoke("/r", "git", "pullRequestThreads", {"project": "P"})
        assert seen[0][seen[0].index("--api-version") + 1] == "7.1-preview"
        assert seen[1][seen[1].index("--api-version") + 1] == "7.1"


class TestScope:
    def test_scope_comes_from_the_parsed_remote_never_detect(self, tmp_path):
        assert ai._scope(tmp_path) == ["--detect", "false", "--org", "https://dev.azure.com/contoso",
                                       "--project", "Claims", "--repository", "claims-api"]
        assert "--repository" not in ai._scope(tmp_path, with_repository=False)

    def test_a_non_ado_remote_is_an_error_naming_the_escape_hatch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(code_host, "origin_url", lambda root: "https://github.com/acme/widgets.git")
        ai.clear_caches()
        with pytest.raises(ai.AdoImportError, match="code-host.yaml"):
            ai._scope(tmp_path)


class TestMapPrOnCapturedOutput:
    PRS = {p["pullRequestId"]: p for p in load("pr_list")}

    def test_the_fixture_is_captured_and_tells_the_story_the_router_relies_on(self):
        assert source_of("pr_list") == "captured" and self.PRS
        assert {p["status"] for p in self.PRS.values()} <= set(ai.ado_map.PR_STATE)  # no unknown status captured
        newest = max(self.PRS.values(), key=lambda p: p["pullRequestId"])
        assert newest["status"] == "active"  # FakeAz._pr_list's story: the newest PR on the captured branch is active
        assert {p["status"] for p in captured_prs().values()} == {"active", "completed", "abandoned"}
        assert all(p["isDraft"] is False for p in captured_prs().values())  # a draft is still hand-written only

    def test_states_and_merge_fields(self):
        active, merged, abandoned = (ai.map_pr(p, REMOTE) for p in (TRIAL, MERGED, ABANDONED))
        assert (active["state"], active["mergedAt"], active["mergeCommit"]) == ("OPEN", None, None)
        assert TRIAL["lastMergeCommit"]["commitId"]  # P7: the trial merge IS there on an active PR …
        assert MERGED["closedDate"] and merged["state"] == "MERGED" and merged["mergedAt"] == MERGED["closedDate"]
        assert merged["mergeCommit"] == {"oid": MERGED["lastMergeCommit"]["commitId"]}  # … and trusted only here
        assert abandoned["state"] == "CLOSED" and abandoned["mergeCommit"] is None and abandoned["mergedAt"] is None
        assert active["headRefName"] == ai.ado_map.strip_ref(TRIAL["sourceRefName"]) and not active["headRefName"].startswith("refs/")
        assert active["url"] == f"{ADO_REMOTE}/pullrequest/{TRIAL['pullRequestId']}"
        assert active["updatedAt"] is None and active["isDraft"] is False and active["files"] is None
        assert active["headRepositoryOwner"] == {"login": TRIAL["repository"]["id"]}

    def test_merge_status_conflicts_and_null_are_tolerated_and_never_lend_a_merge_commit(self):
        """Second capture: `mergeStatus` ∈ succeeded · conflicts · null. The `conflicts` row has no
        lastMergeCommit at all (nothing to trial-merge); the abandoned PR's is null."""
        assert {p.get("mergeStatus") for p in captured_prs().values()} <= {"succeeded", "conflicts", None}
        conflicts = captured_pr("active", mergeStatus="conflicts")
        assert conflicts["lastMergeCommit"] is None
        mapped = ai.map_pr(conflicts, REMOTE)
        assert mapped["state"] == "OPEN" and mapped["mergeCommit"] is None and mapped["_notes"] == []
        assert ABANDONED["mergeStatus"] is None and ai.map_pr(ABANDONED, REMOTE)["mergeCommit"] is None

    def test_labels_null_or_empty_are_an_empty_list_and_names_ride_through(self):
        """Captured: `labels` rides `pr list` by default — a populated list on the first capture, null on
        every PR of the second repository (no labels there). Null, `[]` and a list all map to a list."""
        for p in captured_prs().values():
            assert p.get("labels") is None or isinstance(p["labels"], list)
            assert ai.map_pr(p, REMOTE)["labels"] == [{"name": lb["name"]} for lb in p.get("labels") or []]
        assert any(p.get("labels") is None for p in captured_prs().values())  # the null form IS observed
        labelled = {**ACTIVE, "labels": [{"active": True, "id": "x", "name": "no-spec:chore", "url": "u"}]}  # the captured label keys
        assert ai.map_pr(labelled, REMOTE)["labels"] == [{"name": "no-spec:chore"}]

    def test_is_required_null_means_not_required(self):
        """Captured: `isRequired` is null when a reviewer is not required and true when required — never false."""
        values = {r.get("isRequired") for p in captured_prs().values() for r in p["reviewers"]}
        assert values == {None, True}
        pending = [r for r in ACTIVE["reviewers"] if (r.get("vote") or 0) == 0 and not r.get("isContainer")]
        assert pending  # the newest active PR is still waiting on someone
        reviews, requests, decision = ai.map_reviews(ACTIVE)
        assert reviews == [] and decision == "REVIEW_REQUIRED"
        assert [r["login"] for r in requests] == [r["uniqueName"] for r in pending]
        # Required reviewers are named first among the pending (derived: the completed PR's reviewers with their votes reset).
        waiting = [{**r, "vote": 0} for r in MERGED["reviewers"]]
        assert any(r["isRequired"] is True for r in waiting) and any(r["isRequired"] is None for r in waiting)
        _, requests, _ = ai.map_reviews({**MERGED, "reviewers": waiting})
        required = [r["uniqueName"] for r in waiting if r["isRequired"] is True]
        assert [r["login"] for r in requests][:len(required)] == required

    def test_votes(self):
        """Votes seen across the captures: 0, 10, -5, -10 (the second repository had only 0 and 10)."""
        assert {r.get("vote") for p in captured_prs().values() for r in p["reviewers"]} <= {0, 5, 10, -5, -10}
        author = MERGED["createdBy"]["uniqueName"].lower()
        approvers = [r["uniqueName"] for r in MERGED["reviewers"]
                     if (r.get("vote") or 0) >= ai.ado_map.APPROVE_VOTE and r["uniqueName"].lower() != author]
        reviews, requests, decision = ai.map_reviews(MERGED)
        assert approvers and [(r["state"], r["author"]["login"]) for r in reviews] == [("APPROVED", a) for a in approvers]
        assert decision == "APPROVED" and all(r["submittedAt"] is None for r in reviews)  # ADO stamps no time on a vote
        # A rejecting vote: none was captured in this repository, so one is derived from a captured reviewer.
        rejecting = {**ACTIVE, "reviewers": [{**ACTIVE["reviewers"][0], "vote": -5}]}
        reviews, requests, decision = ai.map_reviews(rejecting)
        assert [(r["state"], r["author"]["login"]) for r in reviews] == [("CHANGES_REQUESTED", ACTIVE["reviewers"][0]["uniqueName"])]
        assert requests == [] and decision == "CHANGES_REQUESTED"
        # The author's own approving vote is not a NON-author approval (derived: an approver becomes the author).
        reviews, _, _ = ai.map_reviews({**MERGED, "createdBy": {"uniqueName": approvers[0]}})
        assert approvers[0] not in [r["author"]["login"] for r in reviews] and len(reviews) == len(approvers) - 1

    def test_roster_resolves_a_handle_by_email_never_by_prefix(self):
        reviewer = ACTIVE["reviewers"][0]["uniqueName"]
        author = ACTIVE["createdBy"]["uniqueName"]
        roster = {"people": [{"handle": "@priya-n", "email": reviewer.upper()}, {"handle": "@" + author.split("@")[0]}]}
        pr = ai.map_pr(ACTIVE, None, None, roster)
        assert pr["reviewRequests"][0]["handle"] == "@priya-n"      # by email, case-insensitively
        assert pr["author"] == {"login": author, "handle": None}  # a handle that merely looks like the UPN's prefix is not a match

    def test_a_missing_required_key_raises_instead_of_defaulting(self):
        pr = dict(ACTIVE)
        del pr["sourceRefName"]
        with pytest.raises(ai.AdoImportError, match="unexpected az shape: missing GitPullRequest.sourceRefName"):
            ai.map_pr(pr)

    def test_hand_written_only_shapes_a_draft_and_an_unknown_status(self):
        """No captured PR was a draft or carried an unknown status; these rest on the hand-written file."""
        prs = {p["pullRequestId"]: p for p in load("pr_list", hand_written=True)}
        assert ai.map_pr(prs[39], REMOTE)["isDraft"] is True
        odd = ai.map_pr(prs[38], REMOTE)
        assert odd["state"] == "OPEN" and odd["_notes"] == ["pull request status 'notSet' is not a known value; read as OPEN"]


class TestMapChecksOnCapturedOutput:
    def test_an_active_prs_empty_policy_list_is_no_checks(self):
        """Captured in BOTH repositories: `pr policy list` on an active PR whose target branch has no
        policies answers `[]` — a legitimate empty, "no checks", never "unknown"."""
        assert source_of("pr_policy_list") == "captured" and load("pr_policy_list") == []
        assert arg_after(command_of("pr_policy_list"), "--id") == str(ACTIVE["pullRequestId"])  # asked about the active PR
        assert ai.map_checks(load("pr_policy_list")) == []

    def test_policy_evaluations_become_checks_and_reviewer_policies_do_not(self):
        """The abandoned PR's evaluations (first capture): build policies are checks, the approver-count policy is not."""
        records = load("pr_policy_list_abandoned")
        builds = [r for r in records if r["configuration"]["type"]["id"] in ai.ado_map.CHECK_POLICY_TYPES]
        others = [r for r in records if r["configuration"]["type"]["id"] not in ai.ado_map.CHECK_POLICY_TYPES]
        assert builds and others  # the fixture exercises both kinds
        checks = {c["name"]: c for c in ai.map_checks(records)}
        assert set(checks) == {r["configuration"]["settings"]["displayName"] for r in builds}
        for r in builds:
            c = checks[r["configuration"]["settings"]["displayName"]]
            assert (c["status"], c["conclusion"]) == ai.ado_map.POLICY_STATUS[r["status"]]  # every captured status is known
            assert c["blocking"] is r["configuration"]["isBlocking"]
        assert all(r["configuration"]["type"]["id"] in (ai.ado_map.MIN_REVIEWERS_POLICY_TYPE, ai.ado_map.REQUIRED_REVIEWERS_POLICY_TYPE)
                   for r in others)

    def test_an_empty_list_is_no_checks(self):
        assert ai.map_checks([]) == []

    def test_hand_written_only_statuses_rejected_queued_and_an_unknown_value(self):
        checks = {c["name"]: c for c in ai.map_checks(load("pr_policy_list", hand_written=True))}
        assert (checks["security-review"]["status"], checks["security-review"]["conclusion"]) == ("IN_PROGRESS", None)
        assert checks["correctness-review"]["conclusion"] == "FAILURE" and checks["eval-regression"]["blocking"] is False
        odd = checks["external-scan"]
        assert (odd["status"], odd["conclusion"]) == ("COMPLETED", None) and "mystery" in odd["_note"]

    def test_missing_type_raises(self):
        with pytest.raises(ai.AdoImportError, match="missing configuration.type"):
            ai.map_checks([{"status": "approved", "configuration": {"settings": {}}}])


class TestMapRunsJobsPoliciesOnCapturedOutput:
    def test_runs_build_their_web_url_because_a_build_record_has_no_links(self):
        """The captured Build (`runs show`) plus the captured `runs list` (empty: a definition with no
        runs) — neither carries `_links`, so the portal URL is built from the remote."""
        builds = [load("runs_show"), *load("runs_list")]
        assert all("_links" not in b for b in builds)
        runs = {r["databaseId"]: r for r in ai.map_runs(builds, REMOTE)}
        for b in builds:
            r = runs[b["id"]]
            assert b["result"] in ai.ado_map.RUN_RESULT and r["conclusion"] == ai.ado_map.RUN_RESULT[b["result"]]
            assert r["event"] == ai.ado_map.RUN_REASON.get(b["reason"], b["reason"])
            assert r["headBranch"] == ai.ado_map.strip_ref(b["sourceBranch"]) and r["createdAt"] == b["queueTime"]
            assert r["status"] == ("completed" if b["status"] == "completed" else "in_progress")
            assert r["url"] == f"https://dev.azure.com/contoso/Claims/_build/results?buildId={b['id']}"
        assert ai.map_runs(builds)[0]["url"] == builds[0]["url"]  # no remote: the REST url, not a fabricated page

    def test_an_in_flight_run_has_no_conclusion_and_is_never_a_failure(self):
        """Second capture: a run still going has `status: inProgress` and `result: null`. Derived here
        from the captured (completed) build, since the kept fixture is the finished one."""
        running = {**load("runs_show"), "status": "inProgress", "result": None, "finishTime": None}
        run = ai.map_runs([running], REMOTE)[0]
        assert run["status"] == "in_progress" and run["conclusion"] is None

    def test_jobs_are_the_timeline_records_of_type_job(self):
        timeline = load("timeline")
        assert {r["type"] for r in timeline["records"]} >= {"Job", "Stage", "Task"}
        assert {r["result"] for r in timeline["records"]} <= set(ai.ado_map.RUN_RESULT)  # succeeded · failed · skipped — all known
        job_records = [r for r in timeline["records"] if r["type"] == "Job"]
        assert job_records
        assert ai.map_jobs(timeline)["jobs"] == [{"name": r["name"], "conclusion": ai.ado_map.RUN_RESULT[r["result"]]} for r in job_records]

    def test_a_skipped_record_is_skipped_not_green_or_red(self):
        """Second capture: timeline `result` ∈ succeeded · failed · skipped (seen on a Stage). A skipped
        JOB is derived from that record; it must read neither success nor failure."""
        skipped = next(r for r in load("timeline")["records"] if r["result"] == "skipped")
        assert ai.map_jobs({"records": [{**skipped, "type": "Job"}]})["jobs"] == [{"name": skipped["name"], "conclusion": "skipped"}]

    def test_policies_are_a_ruleset_with_no_enforcement_date(self):
        """Captured (second repository): `repos policy list` scoped to the default branch is `[]` — no
        ruleset, read as "disabled", not "unknown". The populated case uses the PolicyConfiguration
        records inside the abandoned PR's evaluations (first capture)."""
        configs = load("policy_list")
        expected = "active" if any(c.get("isEnabled") and c.get("isBlocking") for c in configs) else "disabled"
        empty = ai.map_policies(configs)
        assert empty["enforcement"] == expected and empty["created_at"] is None
        configs = [r["configuration"] for r in load("pr_policy_list_abandoned")]
        rs = ai.map_policies(configs)
        assert rs["enforcement"] == "active" and rs["created_at"] is None
        contexts = [c["context"] for c in rs["rules"][0]["parameters"]["required_status_checks"]]
        assert contexts == [c["settings"]["displayName"] for c in configs
                            if c.get("isEnabled") and c["type"]["id"] in ai.ado_map.CHECK_POLICY_TYPES] and contexts
        assert ai.map_policies([{"isEnabled": True, "isBlocking": False, "type": {"id": "x"}}])["enforcement"] == "disabled"


class TestMapThreadsOnCapturedOutput:
    def test_review_requested_comes_from_the_typed_properties_not_the_prose(self):
        threads = load("pr_threads")
        bodies, events = ai.map_threads(threads)
        assert all(c["commentType"] == "system" for t in threads["value"] for c in t["comments"]) and bodies == []
        requested = [t for t in threads["value"] if ai.ado_map.thread_property(t, "CodeReviewThreadType") == "ReviewersUpdate"]
        assert requested  # at least one reviewer-added moment was captured
        assert events == [{
            "event": "review_requested", "created_at": t["publishedDate"],
            "requested_reviewer": {"login": t["identities"][str(ai.ado_map.thread_property(t, "CodeReviewReviewersUpdatedAddedIdentity"))]["uniqueName"]},
        } for t in requested]
        # Both wordings exist across the captures: "X joined as a reviewer" (self) and "X added Y as a
        # reviewer" (another person). Neither is read; the properties above are.
        for t in requested:
            text = t["comments"][0]["content"]
            assert "joined as a reviewer" in text or ("added" in text and "as a reviewer" in text)

    def test_a_thread_without_properties_yields_no_event_rather_than_a_guess(self):
        bodies, events = ai.map_threads(load("pr_threads", hand_written=True))
        assert events == []  # "Person 1 added Person 2 as a reviewer" is prose; prose is not read
        assert bodies[0] == "Looks fine to me." and "Acceptance Check Verdicts" in bodies[1] and len(bodies) == 2

    def test_gate_comments_are_text_comments_opening_with_the_rails_gate_marker(self):
        bodies, _ = ai.map_threads(load("pr_threads_abandoned"))
        assert [ai.ado_map.rails_gate_of(b) for b in bodies] == ["pipeline-7", "pipeline-4", "pipeline-8"]
        assert f"# Security review — PR #{route_param('pr_threads_abandoned', 'pullRequestId')}" in bodies[2]
        assert ai.ado_map.rails_gate_of("Looks fine to me.") is None

    def test_missing_value_raises(self):
        with pytest.raises(ai.AdoImportError, match="threads.value"):
            ai.map_threads({"count": 0})
