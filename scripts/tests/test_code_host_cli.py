"""Tests for code_host.py's CLI-state probes, identity resolution and command line (Wave 1).

The second half of test_code_host.py (split for file size). The probes take injected
`which`/`run` callables, so nothing here spawns gh or az; the command line runs with `--no-probe`.
"""

import json
import subprocess

import pytest

import code_host as ch

ADO = "https://dev.azure.com/contoso/Claims/_git/claims-api"
GH = "https://github.com/acme/widgets.git"


@pytest.fixture
def no_env(monkeypatch):
    monkeypatch.delenv(ch.ENV_VAR, raising=False)
    monkeypatch.delenv(ch.LEGACY_CODE_HOST_ENV, raising=False)


@pytest.fixture
def remote(monkeypatch):
    """Point origin_url at a chosen URL without a git repository."""
    def set_to(url):
        monkeypatch.setattr(ch, "origin_url", lambda root: url)
    return set_to


def _run_factory(outcomes: dict):
    """outcomes: leading argv words -> returncode."""
    def run(args, **kwargs):
        key = " ".join(args[:3])
        for prefix, rc in outcomes.items():
            if key.startswith(prefix):
                return subprocess.CompletedProcess(args, rc, "", "")
        raise AssertionError(f"unexpected probe: {args}")
    return run


class TestCliState:
    def test_az_not_installed(self):
        state, detail = ch.cli_state("azure-devops", which=lambda n: None, run=_run_factory({}))
        assert state == "not_installed" and "Azure CLI" in detail

    def test_az_extension_missing_names_the_fix(self):
        run = _run_factory({"az extension show": 1})
        state, detail = ch.cli_state("azure-devops", which=lambda n: "/usr/bin/az", run=run)
        assert state == "extension_missing" and "az extension add --name azure-devops" in detail

    def test_az_signed_out_names_the_fix(self):
        run = _run_factory({"az extension show": 0, "az account show": 1})
        state, detail = ch.cli_state("azure-devops", which=lambda n: "/usr/bin/az", run=run)
        assert state == "signed_out" and "az login" in detail

    def test_az_available_and_the_probes_carry_the_two_env_vars(self):
        seen = []

        def run(args, **kwargs):
            seen.append(kwargs["env"])
            return subprocess.CompletedProcess(args, 0, "", "")
        state, _ = ch.cli_state("azure-devops", which=lambda n: "/usr/bin/az", run=run)
        assert state == "available"
        assert all(env["AZURE_EXTENSION_USE_DYNAMIC_INSTALL"] == "no" and env["AZURE_CORE_COLLECT_TELEMETRY"] == "no"
                   for env in seen)

    def test_gh_states(self):
        assert ch.cli_state("github", which=lambda n: None, run=_run_factory({}))[0] == "not_installed"
        assert ch.cli_state("github", which=lambda n: "/usr/bin/gh", run=_run_factory({"gh auth status": 1}))[0] == "signed_out"
        assert ch.cli_state("none", which=lambda n: "/usr/bin/gh", run=_run_factory({"gh auth status": 0}))[0] == "available"

    def test_a_failing_probe_is_unknown_never_no(self):
        def boom(args, **kwargs):
            raise OSError("cannot spawn")
        state, detail = ch.cli_state("azure-devops", which=lambda n: "/usr/bin/az", run=boom)
        assert state == "unknown" and "probe" in detail


ROSTER = {"people": [{"handle": "@priya-n", "name": "Priya", "email": "Priya.N@Contoso.com"},
                     {"handle": "@sam-k", "name": "Sam"}]}


class TestResolvePerson:
    def test_github_login_on_the_roster(self):
        assert ch.resolve_person(ROSTER, {"login": "sam-k", "kind": "login"}) == "@sam-k"

    def test_github_login_not_on_the_roster_is_none_not_a_guess(self):
        assert ch.resolve_person(ROSTER, {"login": "someone", "kind": "login"}) is None

    def test_upn_matches_email_case_insensitively(self):
        assert ch.resolve_person(ROSTER, {"login": "priya.n@contoso.com", "kind": "upn"}) == "@priya-n"

    def test_upn_with_no_email_match_is_none_even_when_the_prefix_looks_familiar(self):
        assert ch.resolve_person(ROSTER, {"login": "sam-k@contoso.com", "kind": "upn"}) is None

    def test_kind_is_inferred_from_the_login_when_absent(self):
        assert ch.resolve_person(ROSTER, {"login": "priya.n@contoso.com"}) == "@priya-n"

    def test_garbage_in_is_none_not_a_crash(self):
        assert ch.resolve_person(None, {"login": "x"}) is None
        assert ch.resolve_person(ROSTER, None) is None
        assert ch.resolve_person({"people": "nope"}, {"login": "x"}) is None


class TestCli:
    def test_json_prints_one_document_with_the_host_block(self, tmp_path, no_env, remote, capsys):
        remote(ADO)
        assert ch.main(["--repo", str(tmp_path), "--json", "--no-probe"]) == 0
        doc = json.loads(capsys.readouterr().out)
        assert doc["host"] == {"name": "azure-devops", "source": "remote", "cli": "az", "cli_state": "unknown",
                               "detail": f"from origin {ADO}"}
        assert doc["remote"]["slug"] == "contoso/Claims/claims-api"
        assert doc["ci_platform"] == "github"

    def test_host_flag_and_state_mode(self, tmp_path, no_env, remote, capsys):
        remote(GH)
        (tmp_path / ".sdlc").mkdir()
        (tmp_path / ".sdlc" / "state.yaml").write_text("current_phase: '0'\n", encoding="utf-8")
        assert ch.main(["--state", str(tmp_path / ".sdlc" / "state.yaml"), "--host", "none", "--json", "--no-probe"]) == 0
        doc = json.loads(capsys.readouterr().out)
        assert (doc["host"]["name"], doc["host"]["source"], doc["host"]["cli"]) == ("none", "flag", "gh")

    def test_text_mode_exits_zero(self, tmp_path, no_env, remote, capsys):
        remote(None)
        assert ch.main(["--repo", str(tmp_path), "--no-probe"]) == 0
        out = capsys.readouterr().out
        assert "Code host: none (from default)" in out and "no origin remote" in out

    def test_a_bad_host_is_a_usage_error(self, tmp_path):
        with pytest.raises(SystemExit) as e:
            ch.main(["--repo", str(tmp_path), "--host", "bitbucket"])
        assert e.value.code == 2
