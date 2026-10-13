"""Tests for connection_report.py — is this project wired up? (spec 0012)

The check that earns this file is the last one: which pipelines the playbook expects that a
project does not have. The others confirm what a person could work out in a minute; that one
answers something nobody can see by looking.

Two properties are asserted hard:

  THREE ANSWERS, NOT TWO. Every check can say "could not tell", and that is not a failure. A
  check reporting "no" when it means "I could not look" sends someone to fix something that
  was never broken.

  ONE SOURCE OF TRUTH. The expected set is read from the harness's own pipeline definitions.
  A hardcoded list here would drift the first time a pipeline is added — silently, which is
  the exact failure this report exists to catch, reproduced in the tool that catches it.
"""

import json

import pytest

import connection_report as cr


class TestExpectedSetComesFromTheHarness:
    def test_it_reads_the_harness_rather_than_a_list_in_this_file(self):
        expected = cr.expected_workflows()
        assert expected, "no expected pipelines found — the harness path is wrong"
        # Everything expected exists as a real file in the harness.
        for name in expected:
            assert (cr.HARNESS_WORKFLOWS / name).exists(), name

    def test_the_deliberate_exclusions_are_written_down_with_reasons(self):
        # Excluding a pipeline from "expected" is a judgement, so it is recorded rather than
        # buried in a filter — and each one says why.
        assert cr.NOT_UNIVERSALLY_EXPECTED
        for name, reason in cr.NOT_UNIVERSALLY_EXPECTED.items():
            assert reason.strip(), name
            assert name not in cr.expected_workflows()

    def test_a_deploy_pipeline_is_not_expected_of_every_project(self):
        assert "deploy-dev.yml" not in cr.expected_workflows()


class TestMissingChecks:
    def test_a_project_with_no_pipelines_is_told_exactly_which_are_missing(self, tmp_path):
        present, missing = cr.check_installed_checks(tmp_path)
        assert present["state"] == "no"
        assert missing["state"] == "yes"
        for name in cr.expected_workflows():
            assert name in missing["detail"], name

    def test_a_fully_wired_project_reports_nothing_missing(self, tmp_path):
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        for name in cr.expected_workflows():
            (wf / name).write_text("name: x\n", encoding="utf-8")
        present, missing = cr.check_installed_checks(tmp_path)
        assert present["state"] == "yes"
        assert missing["state"] == "no"

    def test_a_partly_wired_project_names_only_what_is_absent(self, tmp_path):
        expected = list(cr.expected_workflows())
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / expected[0]).write_text("name: x\n", encoding="utf-8")
        _, missing = cr.check_installed_checks(tmp_path)
        assert missing["state"] == "yes"
        assert expected[0] not in missing["detail"]
        assert expected[1] in missing["detail"]

    def test_an_extra_pipeline_a_project_added_is_not_a_problem(self, tmp_path):
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        for name in cr.expected_workflows():
            (wf / name).write_text("name: x\n", encoding="utf-8")
        (wf / "a-project-of-its-own.yml").write_text("name: x\n", encoding="utf-8")
        _, missing = cr.check_installed_checks(tmp_path)
        assert missing["state"] == "no"

    def test_it_compares_FILES_not_what_the_host_has_reported(self, tmp_path):
        # A pipeline that has never run reports no check on the code host, so asking the host
        # would call a correctly-installed but not-yet-triggered pipeline missing. This is a
        # file comparison on purpose, and needs no network at all.
        wf = tmp_path / ".github" / "workflows"
        wf.mkdir(parents=True)
        for name in cr.expected_workflows():
            (wf / name).write_text("name: x\n", encoding="utf-8")
        _, missing = cr.check_installed_checks(tmp_path)
        assert missing["state"] == "no"


class TestThreeAnswersNotTwo:
    def test_every_check_state_is_one_of_three(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cr, "_gh", lambda *a, **k: (False, "no code host here"))
        for check in cr.report(tmp_path)["checks"]:
            assert check["state"] in ("yes", "no", "unknown"), check

    def test_an_unreachable_host_is_UNKNOWN_where_it_cannot_tell(self, tmp_path, monkeypatch):
        # Not "no". "I could not look" and "the answer is no" send a person to two different
        # places, and only one of them is a problem with the project.
        monkeypatch.setattr(cr, "_gh", lambda *a, **k: (False, "gh unavailable"))
        states = {c["check"]: c["state"] for c in cr.report(tmp_path)["checks"]}
        assert states["can_open_prs"] == "unknown"
        assert states["branch_protected"] == "unknown"

    def test_every_check_carries_a_question_and_a_detail(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cr, "_gh", lambda *a, **k: (False, ""))
        for check in cr.report(tmp_path)["checks"]:
            assert check["question"].endswith("?"), check
            assert check["detail"].strip(), check


class TestNeverRaises:
    def test_a_missing_code_host_is_an_answer_not_a_crash(self, tmp_path, monkeypatch):
        def boom(*a, **k):
            raise OSError("gh not installed")
        monkeypatch.setattr(cr.subprocess, "run", boom)
        result = cr.report(tmp_path)
        assert result["ok"] is True
        assert len(result["checks"]) == 6

    def test_unreadable_host_output_does_not_crash(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cr, "_gh", lambda *a, **k: (True, "not json"))
        assert cr.check_branch_protected(tmp_path)["state"] == "unknown"


class TestOnAzureDevOps:
    """Additive (code-host providers, Wave 3): the same six checks on an Azure DevOps remote, read
    through `ado_import` over FakeAz on the CAPTURED fixtures. `gh` is never called; the classes
    above are untouched and the GitHub text is pinned by test_gh_argv_golden.py."""

    @pytest.fixture(autouse=True)
    def _ado(self, monkeypatch):
        import ado_import
        import ado_transport
        import code_host
        from tests.ado_fixtures import ADO_REMOTE, FakeAz
        ado_import.clear_caches()
        monkeypatch.delenv(code_host.ENV_VAR, raising=False)
        monkeypatch.delenv(code_host.LEGACY_CODE_HOST_ENV, raising=False)
        monkeypatch.setattr(code_host, "origin_url", lambda root: ADO_REMOTE)
        monkeypatch.setattr(cr, "_gh", lambda *a, **k: pytest.fail("gh was called on an Azure DevOps repository"))
        self.az = FakeAz()
        monkeypatch.setattr(ado_transport, "az_json", self.az)
        yield
        ado_import.clear_caches()

    @staticmethod
    def _ado_manifest(tmp_path):
        (tmp_path / ".claude").mkdir(exist_ok=True)
        (tmp_path / ".claude" / "harness-manifest.json").write_text(
            json.dumps({"packs": ["cicd/azure-devops"]}), encoding="utf-8")

    def test_exactly_six_checks_with_the_host_block_beside_them(self, tmp_path):
        import ado_map
        from tests.ado_fixtures import load
        acct, repo, configs = load("account_show"), load("repos_show"), load("policy_list")
        result = cr.report(tmp_path)
        assert len(result["checks"]) == 6
        states = {c["check"]: c for c in result["checks"]}
        assert states["signed_in"]["state"] == "yes" and f"as {acct['user']['name']}" in states["signed_in"]["detail"]
        assert f"tenant {acct['tenantId']}" in states["signed_in"]["detail"]
        assert "default account decides the token" in states["signed_in"]["detail"]  # the tenant rule
        assert states["can_read"] == cr._check("can_read", "Can read this repository?", "yes", "contoso/Claims/claims-api")
        assert states["can_open_prs"]["state"] == "unknown" and "no cheap permission probe" in states["can_open_prs"]["detail"]
        enforcing = [c for c in configs if c.get("isEnabled") and c.get("isBlocking")]
        branch = ado_map.strip_ref(repo["defaultBranch"])
        if enforcing:
            assert states["branch_protected"]["state"] == "yes"
            assert states["branch_protected"]["detail"] == f"{len(enforcing)} enforcing polic{'y' if len(enforcing) == 1 else 'ies'} on `{branch}`"
        else:  # captured on the second repository: no policy on the default branch at all — "no" with the reason, never "unknown"
            assert states["branch_protected"]["state"] == "no"
            assert states["branch_protected"]["detail"].startswith(f"no enabled, blocking policy on `{branch}`")
        assert result["host"]["name"] == "azure-devops" and result["host"]["source"] == "remote"
        assert result["host"]["cli"] == "az" and result["host"]["cli_state"] == "available"
        assert all(c["state"] in ("yes", "no", "unknown") for c in result["checks"])

    def test_the_pipeline_checks_follow_the_ci_axis_not_the_code_host(self, tmp_path):
        # No manifest: the CI pack is GitHub's, so the two file checks read .github/workflows and the
        # report says the axes disagree — a legitimate combination, not a fault.
        result = cr.report(tmp_path)
        states = {c["check"]: c for c in result["checks"]}
        assert result["ci_platform"] == "github" and "a legitimate combination" in result["note"]
        assert ".github/workflows" in states["checks_installed"]["detail"]
        # The azure-devops pack: the same gate names, read from .azuredevops/pipelines.
        self._ado_manifest(tmp_path)
        pipelines = tmp_path / ".azuredevops" / "pipelines"
        pipelines.mkdir(parents=True)
        (pipelines / "ci.yml").write_text("trigger: none\n", encoding="utf-8")
        result = cr.report(tmp_path)
        states = {c["check"]: c for c in result["checks"]}
        assert result["ci_platform"] == "azure-devops" and result["note"] is None
        assert states["checks_installed"] == cr._check("checks_installed", "Which checks does this project have?", "yes", "ci.yml")
        expected = cr.expected_workflows("azure-devops")
        assert "ci.yml" in expected and "grader.yml" in expected and "deploy-dev.yml" not in expected
        assert states["checks_missing"]["state"] == "yes" and "grader.yml" in states["checks_missing"]["detail"]
        assert "ci.yml" not in states["checks_missing"]["detail"].split(", ")

    def test_an_empty_azure_pipelines_dir_names_that_dir_not_githubs(self, tmp_path):
        self._ado_manifest(tmp_path)
        present, _ = cr.check_installed_checks(tmp_path, "azure-devops")
        assert present["state"] == "no" and present["detail"] == "no pipeline definitions found in .azuredevops/pipelines"

    def test_signed_out_is_no_with_az_login_and_the_host_block_says_signed_out(self, tmp_path):
        self.az.fail["account show"] = "ERROR: Please run 'az login' to setup account."
        result = cr.report(tmp_path)
        states = {c["check"]: c for c in result["checks"]}
        assert states["signed_in"] == cr._check("signed_in", "Signed in to the code host?", "no", "az is not signed in — run `az login`")
        assert states["can_read"]["state"] == "yes"  # the repository read itself still answered
        assert result["host"]["cli_state"] == "signed_out" and "run `az login`" in result["host"]["detail"]

    def test_az_missing_is_no_for_sign_in_and_UNKNOWN_where_it_could_not_look(self, tmp_path):
        self.az.fail[""] = "The Azure CLI (`az`) is not installed or not on PATH."  # every call
        result = cr.report(tmp_path)
        states = {c["check"]: c for c in result["checks"]}
        assert states["signed_in"] == cr._check("signed_in", "Signed in to the code host?", "no", "the Azure CLI is not installed")
        assert states["can_read"]["state"] == "no"
        assert states["can_open_prs"]["state"] == "unknown"
        assert states["branch_protected"]["state"] == "unknown" and "could not be read" in states["branch_protected"]["detail"]
        assert result["host"]["cli_state"] == "not_installed"
        assert len(result["checks"]) == 6

    def test_no_blocking_policy_is_no_worded_as_what_actually_decides(self, tmp_path):
        from tests.ado_fixtures import load
        self.az.answers["repos policy list"] = [{**c, "isBlocking": False} for c in load("policy_list")]
        states = {c["check"]: c for c in cr.report(tmp_path)["checks"]}
        assert states["branch_protected"]["state"] == "no"
        assert "whether a direct push gets refused" in states["branch_protected"]["detail"]

    def test_the_text_footer_names_the_host_only_when_it_is_not_github(self, tmp_path, monkeypatch):
        text = cr.format_report(cr.report(tmp_path))
        assert text.splitlines()[-2:] == ["  Code host: azure-devops (from origin)",
                                          "  Note: " + cr.report(tmp_path)["note"]]
        import code_host
        monkeypatch.setattr(code_host, "origin_url", lambda root: "https://github.com/acme/app.git")
        monkeypatch.setattr(cr, "_gh", lambda *a, **k: (False, "gh unavailable"))
        github_text = cr.format_report(cr.report(tmp_path))
        assert "Code host:" not in github_text and "Note:" not in github_text

    def test_host_flag_overrides_the_remote(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cr, "_gh", lambda *a, **k: (False, "gh unavailable"))
        result = cr.report(tmp_path, host="github")
        assert result["host"] == {"name": "github", "source": "flag", "cli": "gh", "cli_state": "available",
                                  "detail": "--host github"} or result["host"]["source"] == "flag"
        assert not self.az.calls
