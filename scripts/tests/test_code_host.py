"""Tests for code_host.py — which host, why, and which CLI (code-host providers, Wave 1).

Mirrors test_doctor.py::TestInstalledPlatform for the CI axis and adds the code-host axis: the
override precedence, the shared remote fixture, `none` falling through to gh, and the CLI-state
probes with injected `which`/`run` — nothing here spawns gh or az.
"""

import json
import subprocess

import pytest

import code_host as ch
import doctor  # imported ONLY here, to pin that the twin agrees with the original

FIXTURE = ch.Path(__file__).resolve().parent / "fixtures" / "code_host" / "remote-urls.json"
CASES = [c for c in json.loads(FIXTURE.read_text(encoding="utf-8")) if "url" in c]
ADO = "https://dev.azure.com/contoso/Claims/_git/claims-api"
GH = "https://github.com/acme/widgets.git"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["url"] or "<empty>")
def test_parse_remote_matches_the_shared_fixture(case):
    info = ch.parse_remote(case["url"])
    if case["host"] == "none":
        assert info is None
        return
    assert info is not None, case["url"]
    assert (info.host, info.org, info.project, info.repo, info.slug, info.org_url) == (
        case["host"], case["org"], case["project"], case["repo"], case["slug"], case["org_url"])


def test_parse_remote_web_urls():
    assert ch.parse_remote(GH).web_url == "https://github.com/acme/widgets"
    assert ch.parse_remote(ADO).web_url == ADO
    assert ch.parse_remote("https://contoso.visualstudio.com/Claims/_git/claims-api").web_url == \
        "https://contoso.visualstudio.com/Claims/_git/claims-api"


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


class TestDetectionPrecedence:
    def test_remote_is_the_default_path(self, tmp_path, no_env, remote):
        remote(ADO)
        det = ch.detect_host(tmp_path)
        assert (det.host, det.source) == ("azure-devops", "remote")
        assert det.remote.slug == "contoso/Claims/claims-api"
        assert ADO in det.detail

    def test_flag_beats_everything_and_keeps_the_parsed_remote(self, tmp_path, monkeypatch, remote):
        remote(ADO)
        monkeypatch.setenv(ch.ENV_VAR, "github")
        det = ch.detect_host(tmp_path, override="none")
        assert (det.host, det.source) == ("none", "flag")
        assert det.remote.host == "azure-devops"  # still reported, so a reader sees what was overridden

    def test_env_beats_file_and_remote(self, tmp_path, monkeypatch, remote):
        remote(GH)
        (tmp_path / ".sdlc").mkdir()
        (tmp_path / ".sdlc" / "code-host.yaml").write_text("host: none\n", encoding="utf-8")
        monkeypatch.setenv(ch.ENV_VAR, "azure-devops")
        assert ch.detect_host(tmp_path)[:2] == ("azure-devops", "env")

    def test_file_beats_remote(self, tmp_path, no_env, remote):
        remote(GH)
        (tmp_path / ".sdlc").mkdir()
        (tmp_path / ".sdlc" / "code-host.yaml").write_text("host: azure-devops\n", encoding="utf-8")
        det = ch.detect_host(tmp_path)
        assert (det.host, det.source) == ("azure-devops", "file")

    def test_file_can_supply_the_three_parts_for_an_unparseable_remote(self, tmp_path, no_env, remote):
        remote("https://tfs.corp.example/tfs/DefaultCollection/Claims/_git/claims-api")
        (tmp_path / ".sdlc").mkdir()
        (tmp_path / ".sdlc" / "code-host.yaml").write_text(
            "host: azure-devops\norganization: contoso\nproject: Claims\nrepository: claims-api\n", encoding="utf-8")
        det = ch.detect_host(tmp_path)
        assert det.source == "file"
        assert det.remote.org_url == "https://dev.azure.com/contoso"
        assert det.remote.slug == "contoso/Claims/claims-api"

    def test_a_malformed_file_is_ignored_and_named_never_applied(self, tmp_path, no_env, remote):
        remote(GH)
        (tmp_path / ".sdlc").mkdir()
        (tmp_path / ".sdlc" / "code-host.yaml").write_text("host: bitbucket\n", encoding="utf-8")
        det = ch.detect_host(tmp_path)
        assert (det.host, det.source) == ("github", "remote")
        assert "code-host.yaml" in det.detail

    def test_an_unrecognised_env_value_is_ignored_and_named(self, tmp_path, monkeypatch, remote):
        remote(GH)
        monkeypatch.setenv(ch.ENV_VAR, "gitlab")
        det = ch.detect_host(tmp_path)
        assert (det.host, det.source) == ("github", "remote")
        assert "gitlab" in det.detail and "ignored" in det.detail

    def test_manifest_breaks_the_tie_only_when_there_is_no_usable_remote(self, tmp_path, no_env, remote):
        remote(None)
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "harness-manifest.json").write_text(
            json.dumps({"packs": ["cicd/azure-devops"]}), encoding="utf-8")
        det = ch.detect_host(tmp_path)
        assert (det.host, det.source, det.remote) == ("azure-devops", "manifest", None)
        assert "no origin remote" in det.detail

    def test_manifest_never_overrides_a_parsed_remote(self, tmp_path, no_env, remote):
        remote(GH)
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "harness-manifest.json").write_text(
            json.dumps({"packs": ["cicd/azure-devops"]}), encoding="utf-8")
        assert ch.detect_host(tmp_path)[:2] == ("github", "remote")  # GitHub + Azure Pipelines is real

    def test_nothing_at_all_is_none_with_the_reason(self, tmp_path, no_env, remote):
        remote(None)
        det = ch.detect_host(tmp_path)
        assert (det.host, det.source) == ("none", "default")
        assert det.detail == "no origin remote"

    def test_an_unrecognised_remote_names_the_host(self, tmp_path, no_env, remote):
        remote("https://gitlab.com/acme/widgets.git")
        det = ch.detect_host(tmp_path)
        assert det.host == "none" and 'unrecognised host "gitlab.com"' in det.detail

    def test_an_invalid_override_is_a_value_error(self, tmp_path):
        with pytest.raises(ValueError):
            ch.detect_host(tmp_path, override="bitbucket")

    def test_origin_url_reads_a_real_git_remote(self, tmp_path, no_env):
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", ADO], check=True)
        assert ch.origin_url(tmp_path) == ADO
        assert ch.detect_host(tmp_path)[:2] == ("azure-devops", "remote")

    def test_no_git_repository_is_no_origin_not_a_crash(self, tmp_path):
        assert ch.origin_url(tmp_path) is None


class TestNoneFallsThroughToGh:
    def test_cli_for(self):
        assert ch.cli_for("none") == "gh"
        assert ch.cli_for("github") == "gh"
        assert ch.cli_for("azure-devops") == "az"


class TestCiPlatformTwinAgreesWithDoctor:
    """doctor.installed_platform's six manifest cases, run through BOTH functions."""

    def _manifest(self, tmp_path, text):
        (tmp_path / ".claude").mkdir(exist_ok=True)
        (tmp_path / ".claude" / "harness-manifest.json").write_text(text, encoding="utf-8")

    @pytest.mark.parametrize("text", [
        json.dumps({"profile_id": "ado", "packs": ["stacks/dotnet", "cicd/azure-devops"], "files": {}}),
        json.dumps({"profile_id": "gh", "packs": ["stacks/dotnet", "cicd/github"], "files": {}}),
        "{not json",
        json.dumps({"profile_id": "core-only", "files": {}}),
        json.dumps({"profile_id": "x", "packs": 5, "files": {}}),
    ], ids=["ado-pack", "github-pack", "corrupt", "packless", "type-corrupt"])
    def test_with_a_manifest(self, tmp_path, text):
        self._manifest(tmp_path, text)
        assert ch.installed_ci_platform(tmp_path) == doctor.installed_platform(tmp_path)

    def test_no_manifest(self, tmp_path):
        assert ch.installed_ci_platform(tmp_path) == doctor.installed_platform(tmp_path) == "github"

    def test_the_ado_pack_flips_it(self, tmp_path):
        self._manifest(tmp_path, json.dumps({"packs": ["cicd/azure-devops"]}))
        assert ch.installed_ci_platform(tmp_path) == "azure-devops"
