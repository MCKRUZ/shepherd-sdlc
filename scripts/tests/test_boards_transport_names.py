"""Security review of PR #5 (2026-10-16), MEDIUM: on Windows `az` resolves to the `az.cmd` shim and cmd.exe
re-parses every argument, so an organisation, project or repository name carrying `&`, `|`, `%`, `!`, `^`, `<`, `>`
or a quote would reach cmd.exe as more than one argument (`project=R&D` runs `D`). The names come from `origin` or
from `.sdlc/code-host.yaml`, both of which a hostile repository controls, so `ado_transport.remote()` checks them
ONCE, before any `az` argv exists; every call site (`scope`, `invoke`, `invoke_body`, `rest_*`) goes through it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ado_transport  # noqa: E402
import code_host  # noqa: E402
from ado_map import AdoImportError  # noqa: E402
from code_host_remote import RemoteInfo  # noqa: E402


def _info(*, org: str = "contoso", project: str = "Claims", repo: str | None = "claims-api",
          org_url: str | None = None) -> RemoteInfo:
    org_url = org_url or f"https://dev.azure.com/{org}"
    return RemoteInfo("azure-devops", org, project, repo, f"{org}/{project}/{repo}", org_url,
                      f"{org_url}/{project}/_git/{repo}")


@pytest.mark.parametrize("project", ["Claims", "Expedition One", "R and D (EU)", "Ops-2026", "proj_7", "Café", "x@y"])
def test_a_project_name_azure_devops_allows_is_accepted(project):
    ado_transport._check_remote_names(_info(project=project))      # no exception


@pytest.mark.parametrize("project", ["x&calc", "R&D", "a|b", "%PATH%", "bang!", "a^b", "it's", 'say "hi"', "<x>",
                                     "p[1]", "back\\slash", "tab\tname", " lead", "trail ", ""])
def test_a_project_name_cmd_exe_could_split_is_refused(project):
    with pytest.raises(AdoImportError) as exc:
        ado_transport._check_remote_names(_info(project=project))
    message = str(exc.value)
    assert "project" in message and "refusing to call az" in message
    assert project == "" or project not in message                 # the refusal names the field, never the planted value


@pytest.mark.parametrize("repo", ["x&calc", "a|b", "%TEMP%"])
def test_a_repository_name_cmd_exe_could_split_is_refused(repo):
    with pytest.raises(AdoImportError) as exc:
        ado_transport._check_remote_names(_info(repo=repo))
    assert "repository" in str(exc.value)


def test_a_missing_repository_is_not_a_refusal():
    ado_transport._check_remote_names(_info(repo=None))


@pytest.mark.parametrize("org_url", ["https://dev.azure.com/contoso&x", "https://dev.azure.com/a b",
                                     "http://dev.azure.com/contoso", "https://evil.test/dev.azure.com/contoso",
                                     "https://dev.azure.com/%ORG%"])
def test_an_organisation_url_of_the_wrong_form_is_refused(org_url):
    with pytest.raises(AdoImportError) as exc:
        ado_transport._check_remote_names(_info(org_url=org_url))
    assert "organisation URL" in str(exc.value)


@pytest.mark.parametrize("org_url", ["https://dev.azure.com/contoso", "https://dev.azure.com/contoso/",
                                     "https://contoso.visualstudio.com", "https://my-org.visualstudio.com/"])
def test_both_organisation_url_forms_are_accepted(org_url):
    ado_transport._check_remote_names(_info(org_url=org_url))


def test_remote_refuses_a_hostile_origin_before_any_az_argv(tmp_path, monkeypatch, az):
    """End to end: the planted name arrives through `origin`, `remote()` refuses it, and nothing was spawned."""
    monkeypatch.setattr(code_host, "origin_url", lambda root: "https://dev.azure.com/contoso/x&calc/_git/claims-api")
    ado_transport._SCOPE.pop(str(tmp_path), None)
    with pytest.raises(AdoImportError) as exc:
        ado_transport.remote(tmp_path)
    assert "project" in str(exc.value) and "x&calc" not in str(exc.value)
    with pytest.raises(AdoImportError):
        ado_transport.scope(tmp_path)
    assert az.calls == []


def test_remote_still_resolves_a_clean_origin(tmp_path, az):
    ado_transport._SCOPE.pop(str(tmp_path), None)
    r = ado_transport.remote(tmp_path)                                # the harness's clean contoso remote
    assert r.project == "Claims" and ado_transport.scope(tmp_path)[:4] == ["--detect", "false", "--org", r.org_url]
    assert az.calls == []


def test_the_whitelists_are_the_module_s_own_constants():
    assert ado_transport._NAME_OK.pattern == r"^[\w .()~@-]+$"
    assert ado_transport._ORG_URL_OK.pattern == r"^https://(dev\.azure\.com/[\w.-]+|[\w-]+\.visualstudio\.com)/?$"


# --- the az rest URL through the az.cmd shim (security review of PR #5, LOW) --------------------------------------

def test_a_percent_pair_in_the_rest_url_is_refused_only_through_the_cmd_shim(monkeypatch):
    template = "{project}/_apis/wit/workitems/{id}"
    monkeypatch.setattr(ado_transport, "az_binary", lambda: r"C:\Program Files\Azure\CLI2\wbin\az.cmd")
    assert ado_transport._fill_rest_path(template, {"project": "A B", "id": 7}) == "A%20B/_apis/wit/workitems/7"
    with pytest.raises(AdoImportError) as exc:
        ado_transport._fill_rest_path(template, {"project": "A B C", "id": 7})       # A%20B%20C holds `%20B%`
    assert "az.cmd" in str(exc.value) and "A B C" not in str(exc.value)
    monkeypatch.setattr(ado_transport, "az_binary", lambda: r"C:\tools\az.exe")
    assert ado_transport._fill_rest_path(template, {"project": "A B C", "id": 7}) == "A%20B%20C/_apis/wit/workitems/7"
    monkeypatch.setattr(ado_transport, "az_binary", lambda: "/opt/homebrew/bin/az")
    assert ado_transport._fill_rest_path(template, {"project": "A B C", "id": 7}) == "A%20B%20C/_apis/wit/workitems/7"
