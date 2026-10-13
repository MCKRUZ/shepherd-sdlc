"""Tests for pipeline_proof.py — gathering which rails have fired, from GitHub's own history.

No live calls: `github_import.run_gh` is the one place `gh` is invoked (its own docstring says
tests monkeypatch it, never subprocess), so a router standing in for it exercises the whole
gather → classify → render → write path.

What these guard hardest:
  * READ-ONLY. This runs against a client's repository from a button in a desktop app; it must
    be impossible for it to open, close, merge, label or trigger anything. A test pins the exact
    set of `gh` calls it may make.
  * NEVER A FABRICATED ZERO. A rail whose history could not be read is NO_DATA, not "never fired";
    a ruleset that could not be read is "could not read", not "there is no ruleset".
  * NEVER CLOBBER A PERSON'S WORK. The forced-failure proofs a person records survive a re-run.
"""

import json

import pytest

import github_import
import pipeline_proof as pp
import pipeline_proof_model as m

NWO = "acme/app"


def run(rid, conclusion, branch="feat-a", event="pull_request", at="2026-09-26T10:00:00Z"):
    return {"databaseId": rid, "conclusion": conclusion, "status": "completed", "event": event,
            "headBranch": branch, "createdAt": at, "url": f"https://gh/runs/{rid}"}


PRS = [
    {"number": 7, "headRefName": "feat-a", "state": "MERGED", "url": "https://gh/pull/7",
     "mergedAt": "2026-09-27T10:00:00Z", "reviewDecision": "APPROVED"},
    {"number": 8, "headRefName": "feat-b", "state": "MERGED", "url": "https://gh/pull/8",
     "mergedAt": "2026-09-20T10:00:00Z", "reviewDecision": ""},
]

RUNS = {
    "ci.yml": [run(1, "failure", at="2026-09-26T10:00:00Z"), run(2, "success", at="2026-09-26T11:00:00Z")],
    "grader.yml": [run(3, "success")],
    "security.yml": [],
    "deploy-dev.yml": [run(4, "success", event="push", branch="main")],
}

GRADER_COMMENT = (
    "## Acceptance Check Verdicts\n\n| check | covered | reason |\n|---|---|---|\n"
    "| AC-1 | covered | |\n| AC-2 | not-covered | no test |\n"
)

LIVE_RULESET = {
    "id": 11, "name": "main-branch-protection", "target": "branch", "enforcement": "active",
    "created_at": "2026-09-25T12:00:00Z", "bypass_actors": [],
    "rules": [{"type": "required_status_checks",
               "parameters": {"required_status_checks": [{"context": "build-and-test"}, {"context": "grader"}]}}],
}
INSTALLED_RULESET = {"rules": [{"type": "required_status_checks", "parameters": {"required_status_checks": [
    {"context": "build-and-test"}, {"context": "grader"}, {"context": "security-review"}]}}]}


class FakeGh:
    """Stands in for github_import.run_gh and records every call it is asked to make."""

    def __init__(self, fail=None, runs=None, ruleset_error=None):
        self.calls: list[list[str]] = []
        self.fail = fail or {}
        self.runs = runs if runs is not None else RUNS
        self.ruleset_error = ruleset_error

    def __call__(self, args, cwd):
        self.calls.append(list(args))
        key = " ".join(args[:2])
        for needle, error in self.fail.items():
            if needle in " ".join(args):
                raise github_import.GitHubImportError(error)
        if key == "repo view":
            return json.dumps({"nameWithOwner": NWO})
        if key == "pr list":
            return json.dumps(PRS)
        if key == "run list":
            wf = args[args.index("--workflow") + 1]
            return json.dumps(self.runs.get(wf, []))
        if key == "api repos/acme/app/rulesets":
            if self.ruleset_error:
                raise github_import.GitHubImportError(self.ruleset_error)
            return json.dumps([{"id": 11, "name": "main-branch-protection", "enforcement": "active", "target": "branch"}])
        if key == "api repos/acme/app/rulesets/11":
            return json.dumps(LIVE_RULESET)
        if key == "pr view":
            return json.dumps({"comments": [{"body": GRADER_COMMENT}]})
        if key == "run view":
            return json.dumps({"jobs": [{"name": "deploy", "conclusion": "failure"}]})
        raise AssertionError(f"unexpected gh call: {args}")


@pytest.fixture
def repo(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    for name in ("ci.yml", "grader.yml", "security.yml", "deploy-dev.yml"):
        (wf / name).write_text("name: x\n")
    rulesets = tmp_path / ".github" / "rulesets"
    rulesets.mkdir()
    (rulesets / "branch-protection.json").write_text(json.dumps(INSTALLED_RULESET))
    (tmp_path / ".sdlc" / "artifacts" / "03-foundation").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def gh(monkeypatch):
    fake = FakeGh()
    monkeypatch.setattr(github_import, "run_gh", fake)
    return fake


def rail(result, file):
    return next(r for r in result["rails"] if r.get("file") == file)


class TestGather:
    def test_classifies_each_rail_from_its_own_history(self, repo, gh):
        result = pp.gather(repo)
        assert result["ok"] and result["repo"] == NWO
        assert rail(result, "ci.yml")["status"] == m.PROVEN
        assert rail(result, "grader.yml")["status"] == m.PROVEN  # the posted verdict named AC-2 uncovered
        assert rail(result, "security.yml")["status"] == m.NEVER_FIRED
        assert rail(result, "deploy-dev.yml")["status"] == m.RAN_UNPROVEN

    def test_a_local_hook_is_no_data_never_never_fired(self, repo, gh):
        stop = next(r for r in pp.gather(repo)["rails"] if r["rail"].lower().startswith("stop"))
        assert stop["status"] == m.NO_DATA
        assert stop["runs"] is None

    def test_a_rail_the_guide_expects_but_the_project_lacks_is_never_fired_and_says_it_is_not_installed(self, repo, gh):
        (repo / ".github" / "workflows" / "security.yml").unlink()
        sec = rail(pp.gather(repo), "security.yml")
        assert sec["status"] == m.NEVER_FIRED
        assert "not installed" in sec["reason"].lower()

    def test_a_pipeline_the_project_added_itself_is_inventoried_too(self, repo, gh):
        (repo / ".github" / "workflows" / "gates.yml").write_text("name: g\n")
        gh.runs = {**RUNS, "gates.yml": [run(9, "success")]}
        extra = rail(pp.gather(repo), "gates.yml")
        assert extra["described"] is False and extra["status"] == m.RAN_UNPROVEN

    def test_compares_the_live_ruleset_with_the_checked_in_one(self, repo, gh):
        rs = pp.gather(repo)["ruleset"]
        assert rs["enforcing"] and rs["missing_in_live"] == ["security-review"]

    def test_splits_merge_history_at_the_moment_the_ruleset_went_live(self, repo, gh):
        h = pp.gather(repo)["merge_history"]
        assert (h["pre_enforcement"], h["post_enforcement"]) == (1, 1)

    def test_lists_the_forced_failures_still_needed(self, repo, gh):
        needed = {n["rail"] for n in pp.gather(repo)["proofs_needed"]}
        assert any("security" in n for n in needed)
        assert not any(n == "ci" for n in needed)


class TestHonestFailure:
    def test_one_rail_that_cannot_be_read_is_no_data_while_the_others_still_report(self, repo, monkeypatch):
        fake = FakeGh(fail={"--workflow security.yml": "HTTP 502"})
        monkeypatch.setattr(github_import, "run_gh", fake)
        result = pp.gather(repo)
        assert rail(result, "security.yml")["status"] == m.NO_DATA
        assert "502" in rail(result, "security.yml")["reason"]
        assert rail(result, "ci.yml")["status"] == m.PROVEN

    def test_an_unreadable_ruleset_is_could_not_read_not_no_ruleset(self, repo, monkeypatch):
        monkeypatch.setattr(github_import, "run_gh", FakeGh(ruleset_error="HTTP 403"))
        rs = pp.gather(repo)["ruleset"]
        assert rs["live"] is None and "403" in rs["error"]
        assert rs["enforcing"] is None

    def test_gh_missing_entirely_is_a_clean_failure_that_writes_nothing(self, repo, monkeypatch):
        def broken(args, cwd):
            raise github_import.GitHubImportError("The `gh` CLI is not installed or not on PATH.")
        monkeypatch.setattr(github_import, "run_gh", broken)
        result = pp.gather(repo)
        assert result["ok"] is False and "gh" in result["error"]
        assert pp.write_document(repo, result) is None
        assert not (repo / pp.DOC_PATH).exists()


class TestReadOnly:
    """The property that matters most. Every call this makes to GitHub, enumerated."""

    ALLOWED = {("repo", "view"), ("pr", "list"), ("pr", "view"), ("run", "list"), ("run", "view")}
    WRITE_FLAGS = {"-X", "--method", "-f", "-F", "--field", "--raw-field", "--input"}

    def test_every_gh_call_is_a_read(self, repo, gh):
        pp.gather(repo)
        assert gh.calls, "expected the gatherer to call gh at all"
        for call in gh.calls:
            if call[0] == "api":
                assert not (self.WRITE_FLAGS & set(call)), f"api call with a write flag: {call}"
                assert call[1].startswith("repos/") and "/rulesets" in call[1], f"api call outside rulesets: {call}"
            else:
                assert (call[0], call[1]) in self.ALLOWED, f"not a read: {call}"


class TestDocument:
    def test_first_write_creates_the_document_with_every_section(self, repo, gh):
        result = pp.gather(repo)
        path = pp.write_document(repo, result)
        text = path.read_text(encoding="utf-8")
        for heading in ("Rail status", "Branch protection", "Merge history", "Proofs still needed", "Forced-failure proofs"):
            assert f"## {heading}" in text
        assert "PROVEN" in text and "NEVER-FIRED" in text and "NO DATA" in text
        assert f"**Repository:** {NWO}" in text

    def test_a_rerun_rewrites_the_gathered_sections_but_never_the_persons_proofs(self, repo, gh):
        path = pp.write_document(repo, pp.gather(repo))
        mine = "| ci | I planted a failing test | https://gh/pull/99 | 2026-09-28 |"
        text = path.read_text(encoding="utf-8")
        security_before = next(line for line in text.splitlines() if line.startswith("| security"))
        assert "NEVER-FIRED" in security_before                # the control: it really was never fired
        path.write_text(text.rstrip() + "\n" + mine + "\n", encoding="utf-8")

        gh.runs = {**RUNS, "security.yml": [run(20, "success")]}  # the world changed since last time
        pp.write_document(repo, pp.gather(repo))

        after = path.read_text(encoding="utf-8")
        assert mine in after                                   # the person's row survived
        security_row = next(line for line in after.splitlines() if line.startswith("| security"))
        assert "RAN-UNPROVEN" in security_row                  # the gathered half moved on
        for heading in (*pp.GENERATED_SECTIONS, pp.PERSONS_SECTION):
            assert after.count(f"## {heading}") == 1           # nothing duplicated

    def test_a_document_with_windows_line_endings_keeps_them(self, repo, gh):
        path = pp.write_document(repo, pp.gather(repo))
        crlf = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        path.write_bytes(crlf)
        pp.write_document(repo, pp.gather(repo))
        data = path.read_bytes()
        assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")

    def test_a_table_cell_never_breaks_the_table(self, repo, gh):
        gh.runs = {**RUNS}
        result = pp.gather(repo)
        result["rails"][0]["reason"] = "has a | pipe\nand a newline"
        text = pp.render_sections(result)["Rail status"]
        for line in text.splitlines():
            if line.startswith("| ci") or line.startswith("| " + result["rails"][0]["rail"]):
                assert line.count("|") == 5  # four cells, never split by the reason's own pipe


class TestCli:
    def test_json_output_for_the_app(self, repo, gh, capsys):
        rc = pp.main(["--repo", str(repo), "--json"])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0 and out["ok"] and out["rails"] and "wrote" not in out

    def test_write_flag_writes_and_reports_where(self, repo, gh, capsys):
        rc = pp.main(["--repo", str(repo), "--json", "--write"])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0 and out["wrote"] == pp.DOC_PATH
        assert (repo / pp.DOC_PATH).exists()

    def test_without_write_nothing_is_written(self, repo, gh):
        pp.main(["--repo", str(repo), "--json"])
        assert not (repo / pp.DOC_PATH).exists()

    def test_exits_zero_even_when_the_read_fails(self, repo, monkeypatch, capsys):
        def broken(args, cwd):
            raise github_import.GitHubImportError("no network")
        monkeypatch.setattr(github_import, "run_gh", broken)
        assert pp.main(["--repo", str(repo), "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["ok"] is False


class TestRenderMergeHistory:
    def _result(self, unapproved):
        return {"ok": True, "repo": NWO, "gathered_at": "x", "rails": [], "ruleset": {"live": True, "enforcing": True,
                "enforcement": "active", "required": [], "bypass_actors": [], "missing_in_live": [], "extra_in_live": [],
                "created_at": "2026-09-25T00:00:00Z"}, "proofs_needed": [], "notes": [],
                "merge_history": {"total_merged": 30, "enforced_since": "2026-09-25T00:00:00Z", "pre_enforcement": 5,
                                  "post_enforcement": 25, "unapproved_post_enforcement": unapproved}}

    def test_unapproved_merges_are_counted_and_only_the_most_recent_few_are_linked(self):
        unapproved = [{"label": f"PR #{n}", "url": f"https://gh/pull/{n}"} for n in range(1, 13)]
        text = pp.render_sections(self._result(unapproved))["Merge history"]
        assert "12 of them merged without an approval" in text
        assert "[PR #12]" in text and "[PR #8]" in text and "[PR #7]" not in text
        assert "+7 more" in text

    def test_no_unapproved_merge_says_so(self):
        assert "Every merge since was approved." in pp.render_sections(self._result([]))["Merge history"]


class TestOnAzureDevOps:
    """Additive (code-host providers, Wave 3): the gatherer on an Azure DevOps remote with the
    azure-devops CI pack installed, driven by FakeAz over the CAPTURED fixtures. `gh` is never
    called. The FakeAz router raising on an unknown call is the read-only pin for this path, the
    same device TestReadOnly uses for `gh`; the classes above are untouched.

    Second capture: `pipelines list --repository` answers [] although the project has pipelines,
    so the definitions come from the project-wide fallback (ado_fixtures.repo_pipelines: the
    derived definitions bound to this repository). Three of them are given the gate YAMLs here —
    security.yml has no definition on purpose — the one captured build is served as ci.yml's
    history (derived) and the other rails keep the captured empty run list."""

    READ_PREFIXES = {("repos", "show"), ("repos", "pr", "list"), ("repos", "pr", "policy", "list"),
                     ("repos", "policy", "list"), ("pipelines", "list"), ("pipelines", "show"),
                     ("pipelines", "runs", "list"), ("devops", "invoke")}

    @pytest.fixture
    def ado_repo(self, tmp_path, monkeypatch):
        import ado_import
        import ado_transport
        import code_host
        from tests.ado_fixtures import ADO_REMOTE, FakeAz, arg_after, load, repo_pipelines
        ado_import.clear_caches()
        monkeypatch.delenv(code_host.ENV_VAR, raising=False)
        monkeypatch.delenv(code_host.LEGACY_CODE_HOST_ENV, raising=False)
        monkeypatch.setattr(code_host, "origin_url", lambda root: ADO_REMOTE)
        monkeypatch.setattr(github_import, "run_gh", lambda *a, **k: pytest.fail("gh was called on an Azure DevOps repository"))
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "harness-manifest.json").write_text(json.dumps({"packs": ["cicd/azure-devops"]}), encoding="utf-8")
        pipelines = tmp_path / ".azuredevops" / "pipelines"
        pipelines.mkdir(parents=True)
        for name in ("ci.yml", "grader.yml", "security.yml", "deploy-dev.yml"):
            (pipelines / name).write_text("trigger: none\n", encoding="utf-8")
        rails = tmp_path / ".azuredevops" / "rails"
        rails.mkdir()
        (rails / "branch-policies.json").write_text(json.dumps({
            "branch": "master", "build_validation": [{"displayName": "pipeline-3", "isBlocking": True},
                                                      {"displayName": "build-and-test", "isBlocking": True}]}), encoding="utf-8")
        (tmp_path / ".sdlc" / "artifacts" / "03-foundation").mkdir(parents=True)
        bound = repo_pipelines()
        assert len(bound) >= 3, "the derived project-wide list must bind at least three definitions to the repository"
        self.yaml_by_id = {bound[0]["id"]: "ci.yml", bound[1]["id"]: "grader.yml", bound[2]["id"]: "deploy-dev.yml"}
        self.ci_id, self.build = bound[0]["id"], load("runs_show")
        defaults = FakeAz().answers

        def show(args):
            rec = defaults["pipelines show"](args)
            wanted = int(arg_after(args, "--id"))
            if wanted in self.yaml_by_id:
                rec = {**rec, "process": {"type": 2, "yamlFilename": f".azuredevops/pipelines/{self.yaml_by_id[wanted]}"}}
            return rec

        def runs(args):  # the captured build as ci.yml's history (derived); every other definition: the captured []
            return [self.build] if arg_after(args, "--pipeline-ids") == str(self.ci_id) else load("runs_list")

        self.az = FakeAz({"pipelines show": show, "pipelines runs list": runs})
        monkeypatch.setattr(ado_transport, "az_json", self.az)
        yield tmp_path
        ado_import.clear_caches()

    def test_rails_are_read_from_azure_pipelines_and_a_missing_definition_is_no_data(self, ado_repo):
        from tests.ado_fixtures import load
        result = pp.gather(ado_repo)
        assert result["ok"] and result["repo"] == "contoso/Claims/claims-api"
        assert result["host"]["name"] == "azure-devops" and result["ci_platform"] == "azure-devops"
        ci = rail(result, "ci.yml")
        assert ci["status"] in (m.RAN_UNPROVEN, m.PROVEN) and ci["runs"] == 1  # the one captured build, served as this rail's history
        assert all("_build/results?buildId=" in e["url"] for e in ci["evidence"])
        grader = rail(result, "grader.yml")
        assert load("runs_list") == [] and grader["status"] == m.NEVER_FIRED and grader["runs"] == 0  # a definition exists; its run list is [] (captured): a real zero
        security = rail(result, "security.yml")
        assert security["status"] == m.NO_DATA
        assert security["reason"] == "pipeline definition for `security.yml` not found in Azure Pipelines"
        assert security["runs"] is None  # never a fabricated zero
        lists = [c for c in self.az.calls if c[:2] == ["pipelines", "list"]]
        assert [("--repository" in c) for c in lists] == [True, False]  # the filtered read answered [] (captured); the project-wide fallback ran once

    def test_a_repository_with_no_pipeline_anywhere_is_no_data_naming_the_repository(self, ado_repo):
        self.az.answers["pipelines list"] = lambda args: []  # the filter AND the project-wide list: nothing bound to this repository
        result = pp.gather(ado_repo)
        for name in ("ci.yml", "grader.yml", "security.yml"):
            r = rail(result, name)
            assert r["status"] == m.NO_DATA and r["runs"] is None
            assert f"pipeline definition for `{name}` not found in Azure Pipelines" in r["reason"]
            assert "no pipeline definition found for claims-api in project Claims" in r["reason"]

    def test_a_rail_the_guide_expects_but_the_project_lacks_names_the_azure_dir(self, ado_repo):
        correctness = rail(pp.gather(ado_repo), "correctness.yml")
        assert correctness["status"] == m.NEVER_FIRED
        assert "is not installed in this project's .azuredevops/pipelines" in correctness["reason"]
        assert ".github/workflows" not in correctness["reason"]

    def test_branch_policies_are_the_ruleset_and_merges_are_not_split(self, ado_repo):
        import ado_map
        from tests.ado_fixtures import load
        configs = load("policy_list")  # captured: [] on this repository's default branch — no policy at all is common, and honest
        live_enforcing = any(c.get("isEnabled") and c.get("isBlocking") for c in configs)
        live_required = [c["settings"]["displayName"] for c in configs
                         if c.get("isEnabled") and c["type"]["id"] in ado_map.CHECK_POLICY_TYPES]
        result = pp.gather(ado_repo)
        rs = result["ruleset"]
        assert rs["live"] is True and rs["enforcing"] is live_enforcing and rs["created_at"] is None
        assert sorted(rs["required"]) == sorted(live_required)
        assert rs["missing_in_live"] == [n for n in ("pipeline-3", "build-and-test") if n not in live_required]  # expected by the checked-in policies, not enforced live
        assert result["merge_history"]["enforced_since"] is None  # ADO has no enforcement-start date
        assert result["merge_history"]["total_merged"] == sum(1 for p in load("pr_list") if p["status"] == "completed")
        protection = pp.render_sections(result)["Branch protection"]
        if live_enforcing:
            assert "**Enforcement:** active" in protection
        else:  # an empty policy list is a ruleset that enforces nothing — said as such, not as "could not read"
            assert "**Enforcement:** disabled" in protection and "not enforcing" in protection
            assert "Could not read" not in protection
        assert "Proofs still needed" in pp.render_sections(result)

    def test_every_az_call_is_a_read(self, ado_repo):
        pp.gather(ado_repo)
        assert self.az.calls, "expected the gatherer to call az at all"
        for call in self.az.calls:
            assert any(tuple(call[:len(p)]) == p for p in self.READ_PREFIXES), f"not a read: {call}"
            if call[:2] == ["devops", "invoke"]:
                assert "--http-method" not in call, f"invoke with a method: {call}"  # the default is GET

    def test_an_unreadable_policy_list_is_could_not_read_in_the_hosts_words(self, ado_repo):
        self.az.fail["repos policy list"] = "HTTP 403"
        result = pp.gather(ado_repo)
        assert result["ruleset"]["enforcing"] is None and result["ruleset"]["error"] == "HTTP 403"
        protection = pp.render_sections(result)["Branch protection"]
        assert protection.startswith("Could not read Azure DevOps's branch policies: HTTP 403")
        assert "not the same as there being no ruleset" in protection

    def test_an_az_failure_is_ok_false_with_the_host_block(self, ado_repo):
        self.az.fail["repos show"] = "ERROR: Please run 'az login' to setup account."
        result = pp.gather(ado_repo)
        assert result["ok"] is False and "az login" in result["error"]
        assert result["host"]["cli_state"] == "signed_out" and result["host"]["cli"] == "az"
        assert pp.write_document(ado_repo, result) is None

    def test_installed_policies_become_a_ruleset_and_a_github_export_passes_through(self):
        assert m.required_contexts(pp.installed_policies_as_ruleset(
            {"build_validation": [{"displayName": "grader"}, {"note": "no name"}]})) == ["grader"]
        assert pp.installed_policies_as_ruleset(INSTALLED_RULESET) is INSTALLED_RULESET

    def test_json_output_carries_the_host_block(self, ado_repo, capsys):
        assert pp.main(["--repo", str(ado_repo), "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] and out["host"]["name"] == "azure-devops" and out["ci_platform"] == "azure-devops"
