"""B1-P1 — the body-carrying `az devops invoke` seam (`ado_transport.invoke_body`, `check_api_version`).

What this pins, and why each line exists (build kit §1 K2-K5, K21; guardrails 7, 8, 12):
  * the argv, byte for byte, for a GET, a read POST and a write PATCH — `--detect false` present,
    `-o json` the LAST TWO elements, and `--only-show-errors` ABSENT, because `run_az` appends it and
    a fake standing in for `run_az` never sees it (one test goes below the seam to prove the real
    argv ends `-o json --only-show-errors`);
  * no `-preview.<n>` api-version ever leaves the seam (`7.1-preview.1` crashes the az extension);
  * the request body travels in a private temp file that is removed on success AND on failure, and
    whose path is never printed — not even inside an error message `run_az` built from its argv;
  * the response is returned as parsed, never shape-checked (callers `_require`); an empty stdout is
    `[]` for a read and an error for a write;
  * the existing seam (`invoke`, `az_json`) is byte-for-byte what #106 shipped, so nothing above it
    changed under the two callers that still use it.

Nothing here spawns `az`: `boards_env` forbids it at the seam and every test swaps in a fake.
"""

import inspect
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import FORBIDDEN_AZ, FakeBoardsAz, load_wit

import ado_transport
import boards_contract
import code_host
from ado_map import AdoImportError

# The real `run_az`, captured at import: `boards_env` replaces the attribute for the length of each test.
_REAL_RUN_AZ = ado_transport.run_az
ORG = "https://dev.azure.com/contoso"  # what tests.ado_fixtures.ADO_REMOTE parses to
PATCH_BODY = [{"op": "test", "path": "/rev", "value": 3},
              {"op": "replace", "path": "/fields/System.Title", "value": "probe title"}]

# `inspect.getsource(ado_transport.invoke)` as shipped in #106 (325ac2b). Copied, never imported.
INVOKE_SOURCE = '''def invoke(repo_root, area: str, resource: str, route: dict, api_version: str = API_VERSION) -> dict:
    """`az devops invoke` for the REST resources that have no native verb (threads, commits,
    timeline, environments). `api_version` is PREVIEW_API_VERSION for the environments area only."""
    params = [f"{k}={v}" for k, v in route.items()]
    return az_json(["devops", "invoke", "--area", area, "--resource", resource, "--route-parameters", *params,
                    "--api-version", api_version, "--org", remote(repo_root).org_url], repo_root)
'''


# --- helpers ---------------------------------------------------------------------------------------

@pytest.fixture
def body_dir(tmp_path, monkeypatch) -> Path:
    """A private directory standing in for the system temp dir, so 'unlinked' is checkable."""
    d = tmp_path / "bodies"
    d.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(d))
    return d


@pytest.fixture
def writer(monkeypatch):
    """Install a `FakeBoardsAz` that allows writes (the `az` fixture's fake does not)."""
    def make(answers=None) -> FakeBoardsAz:
        fake = FakeBoardsAz(answers, writes=True)
        monkeypatch.setattr(ado_transport, "run_az", fake)
        return fake
    return make


def install(monkeypatch, fn) -> None:
    """Replace `run_az` with `fn(args)`; the real signature is `(args, cwd, timeout=60)`."""
    monkeypatch.setattr(ado_transport, "run_az", lambda args, cwd, timeout=60: fn(args))


def in_file_of(argv: list[str]) -> str:
    return argv[argv.index("--in-file") + 1]


class SeenBody:
    """A FakeBoardsAz answer that reads the `--in-file` while the call is 'in flight'."""

    def __init__(self, reply):
        self.reply, self.path, self.raw, self.mode, self.dir_listing = reply, None, None, None, None

    def __call__(self, args):
        self.path = in_file_of(args)
        self.raw = Path(self.path).read_bytes()
        self.mode = stat.S_IMODE(os.stat(self.path).st_mode)
        self.dir_listing = sorted(p.name for p in Path(self.path).parent.iterdir())
        return self.reply


def assert_seam_shape(argv: list[str]) -> None:
    """What every recorded argv carries, whatever the call."""
    assert argv[:2] == ["devops", "invoke"]
    assert argv[argv.index("--detect") + 1] == "false"
    assert argv[-2:] == ["-o", "json"]
    assert "--only-show-errors" not in argv  # run_az appends it; the fake never sees it
    assert "--project" not in argv and "--repository" not in argv  # the project is a route parameter
    assert argv[argv.index("--org") + 1] == ORG
    assert not any("-preview." in a for a in argv)


# --- pins on what must not move --------------------------------------------------------------------

def test_the_legacy_seam_is_untouched():
    assert inspect.getsource(ado_transport.invoke) == INVOKE_SOURCE
    assert str(inspect.signature(ado_transport.az_json)) == "(args: list[str], cwd)"


def test_the_new_seam_is_appended_below_invoke():
    first = ado_transport.invoke.__code__.co_firstlineno
    assert ado_transport.check_api_version.__code__.co_firstlineno > first
    assert ado_transport.invoke_body.__code__.co_firstlineno > first


def test_the_pinned_signatures():
    p = inspect.Parameter
    params = inspect.signature(ado_transport.invoke_body).parameters.values()
    assert [(x.name, x.kind, x.default) for x in params] == [
        ("repo_root", p.POSITIONAL_OR_KEYWORD, p.empty),
        ("area", p.POSITIONAL_OR_KEYWORD, p.empty),
        ("resource", p.POSITIONAL_OR_KEYWORD, p.empty),
        ("route", p.POSITIONAL_OR_KEYWORD, p.empty),
        ("method", p.KEYWORD_ONLY, "GET"),
        ("body", p.KEYWORD_ONLY, None),
        ("media_type", p.KEYWORD_ONLY, "application/json-patch+json"),
        ("query", p.KEYWORD_ONLY, None),
        ("api_version", p.KEYWORD_ONLY, ado_transport.API_VERSION),
        ("timeout", p.KEYWORD_ONLY, 60),
    ]
    assert list(inspect.signature(ado_transport.check_api_version).parameters) == ["v"]


def test_the_write_methods_are_the_contracts():
    """invoke_body keeps its own literal (it imports nothing new); the contract is the authority."""
    assert ado_transport._WRITE_METHODS == boards_contract.WRITE_METHODS


# --- api-version -----------------------------------------------------------------------------------

@pytest.mark.parametrize("version", ["7.1-preview.4", "7.1-preview.1", "6.0-preview.2", "7.2-preview.10"])
def test_a_preview_revision_is_refused(version):
    with pytest.raises(AdoImportError, match="preview"):
        ado_transport.check_api_version(version)


@pytest.mark.parametrize("version", ["7.1-preview", "7.1", "7.0", "5.0"])
def test_ga_and_the_bare_preview_pass_through_unchanged(version):
    assert ado_transport.check_api_version(version) == version


def test_the_two_constants_both_pass():
    assert ado_transport.check_api_version(ado_transport.API_VERSION) == "7.1"
    assert ado_transport.check_api_version(ado_transport.PREVIEW_API_VERSION) == "7.1-preview"


def test_a_preview_revision_is_refused_before_any_az_call_or_temp_file(az, tmp_path, body_dir):
    with pytest.raises(AdoImportError, match="preview"):
        ado_transport.invoke_body(tmp_path, "wit", "comments", {"project": "Claims", "workItemId": "42"},
                                  method="POST", body={"text": "x"}, media_type="application/json",
                                  api_version="7.1-preview.4")
    assert az.calls == []
    assert list(body_dir.iterdir()) == []


def test_the_bare_preview_reaches_the_argv(az, tmp_path):
    ado_transport.invoke_body(tmp_path, "core", "connectionData", {}, api_version=ado_transport.PREVIEW_API_VERSION)
    argv = az.calls[0]
    assert argv[argv.index("--api-version") + 1] == "7.1-preview"


# --- argv goldens ----------------------------------------------------------------------------------

def test_get_argv_golden(az, tmp_path):
    out = ado_transport.invoke_body(tmp_path, "wit", "workItemTypes", {"project": "Claims"})
    assert az.calls == [["devops", "invoke", "--area", "wit", "--resource", "workItemTypes",
                         "--route-parameters", "project=Claims", "--http-method", "GET",
                         "--api-version", "7.1", "--detect", "false", "--org", ORG, "-o", "json"]]
    assert out == load_wit("types")  # parsed as printed, not reshaped
    assert_seam_shape(az.calls[0])


def test_get_with_route_and_query_golden(az, tmp_path):
    ado_transport.invoke_body(tmp_path, "wit", "fields", {"project": "Claims", "type": "User Story"},
                              query={"$expand": "allowedValues"})
    assert az.calls == [["devops", "invoke", "--area", "wit", "--resource", "fields",
                         "--route-parameters", "project=Claims", "type=User Story", "--http-method", "GET",
                         "--query-parameters", "$expand=allowedValues",
                         "--api-version", "7.1", "--detect", "false", "--org", ORG, "-o", "json"]]
    assert_seam_shape(az.calls[0])


def test_an_empty_route_keeps_the_flag_as_pinned(az, tmp_path):
    """The pinned argv always emits `--route-parameters`; whether az wants it for a parameterless
    route is a B0 question (the capture passes an empty string), answered there, not guessed here."""
    ado_transport.invoke_body(tmp_path, "core", "connectionData", {})
    argv = az.calls[0]
    assert argv[argv.index("--route-parameters") + 1] == "--http-method"


def test_read_post_argv_golden(writer, tmp_path, body_dir):
    seen = SeenBody({"count": 0, "value": []})
    fake = writer({"POST wit/workitemsbatch": seen})
    body = {"ids": [1, 2], "$expand": "relations", "errorPolicy": "omit"}
    out = ado_transport.invoke_body(tmp_path, "wit", "workitemsbatch", {"project": "Claims"}, method="POST",
                                    body=body, media_type="application/json")
    assert fake.calls == [["devops", "invoke", "--area", "wit", "--resource", "workitemsbatch",
                           "--route-parameters", "project=Claims", "--http-method", "POST",
                           "--in-file", seen.path, "--media-type", "application/json",
                           "--api-version", "7.1", "--detect", "false", "--org", ORG, "-o", "json"]]
    assert out == {"count": 0, "value": []}
    assert json.loads(seen.raw) == body
    assert_seam_shape(fake.calls[0])


def test_create_post_argv_golden_keeps_the_dollar(writer, tmp_path, body_dir):
    seen = SeenBody({"id": 42, "rev": 1})
    fake = writer({"POST wit/workItems": seen})
    body = [{"op": "add", "path": "/fields/System.Title", "value": "probe title"}]
    ado_transport.invoke_body(tmp_path, "wit", "workItems", {"project": "Claims", "type": "$Task"},
                              method="POST", body=body)
    assert fake.calls == [["devops", "invoke", "--area", "wit", "--resource", "workItems",
                           "--route-parameters", "project=Claims", "type=$Task", "--http-method", "POST",
                           "--in-file", seen.path, "--media-type", "application/json-patch+json",
                           "--api-version", "7.1", "--detect", "false", "--org", ORG, "-o", "json"]]
    assert_seam_shape(fake.calls[0])


def test_patch_argv_golden(writer, tmp_path, body_dir):
    seen = SeenBody({"id": 42, "rev": 4})
    fake = writer({"PATCH wit/workItems": seen})
    out = ado_transport.invoke_body(tmp_path, "wit", "workItems", {"project": "Claims", "id": 42},
                                    method="PATCH", body=PATCH_BODY, query={"validateOnly": "true"})
    assert fake.calls == [["devops", "invoke", "--area", "wit", "--resource", "workItems",
                           "--route-parameters", "project=Claims", "id=42", "--http-method", "PATCH",
                           "--in-file", seen.path, "--media-type", "application/json-patch+json",
                           "--query-parameters", "validateOnly=true",
                           "--api-version", "7.1", "--detect", "false", "--org", ORG, "-o", "json"]]
    assert out == {"id": 42, "rev": 4}
    assert json.loads(seen.raw) == PATCH_BODY
    assert_seam_shape(fake.calls[0])


def test_a_lowercase_method_is_written_uppercase(writer, tmp_path, body_dir):
    fake = writer({"PATCH wit/workItems": {"id": 1}})
    ado_transport.invoke_body(tmp_path, "wit", "workItems", {"project": "Claims", "id": 1},
                              method="patch", body=PATCH_BODY)
    argv = fake.calls[0]
    assert argv[argv.index("--http-method") + 1] == "PATCH"


def test_the_timeout_is_forwarded_to_run_az(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(ado_transport, "run_az", lambda args, cwd, timeout=60: seen.append((cwd, timeout)) or "[]")
    ado_transport.invoke_body(tmp_path, "wit", "fields", {"project": "Claims"})
    ado_transport.invoke_body(tmp_path, "wit", "fields", {"project": "Claims"}, timeout=7)
    assert seen == [(tmp_path, 60), (tmp_path, 7)]


def test_nothing_is_invented_when_the_repo_is_not_an_azure_devops_remote(az, tmp_path, body_dir, monkeypatch):
    monkeypatch.setattr(code_host, "origin_url", lambda root: "https://github.com/o/r.git")
    with pytest.raises(AdoImportError, match="not an Azure DevOps remote"):
        ado_transport.invoke_body(tmp_path, "wit", "workItems", {"project": "Claims", "id": 1},
                                  method="PATCH", body=PATCH_BODY)
    assert az.calls == []
    assert list(body_dir.iterdir()) == []


# --- below the seam: the real argv -----------------------------------------------------------------

@pytest.mark.parametrize("kwargs, timeout", [({}, 60), ({"timeout": 7}, 7)])
def test_the_real_argv_ends_dash_o_json_only_show_errors(monkeypatch, tmp_path, kwargs, timeout):
    monkeypatch.setattr(ado_transport, "run_az", _REAL_RUN_AZ)
    spawned = []

    def fake_run(cmd, **kw):
        spawned.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, stdout='{"value": []}', stderr="")

    monkeypatch.setattr(ado_transport.subprocess, "run", fake_run)  # this test only; boards_env never does
    out = ado_transport.invoke_body(tmp_path, "wit", "workItemTypes", {"project": "Claims"}, **kwargs)
    (cmd, kw), = spawned
    assert out == {"value": []}
    assert cmd[0] == FORBIDDEN_AZ  # the binary came from az_binary(), which boards_env redirects
    assert cmd[-3:] == ["-o", "json", "--only-show-errors"]
    assert cmd[1:3] == ["devops", "invoke"]
    assert kw["timeout"] == timeout and kw["cwd"] == str(tmp_path)


@pytest.mark.parametrize("failure", [
    pytest.param(subprocess.TimeoutExpired(cmd="az", timeout=7), id="timeout"),
    pytest.param(subprocess.CompletedProcess([], 3, stdout="", stderr=""), id="exit-3-no-stderr"),
])
def test_the_body_path_is_scrubbed_from_the_errors_run_az_builds(monkeypatch, tmp_path, body_dir, capsys, failure):
    """`run_az` words a timeout and a silent non-zero exit with `az <its own argv>`, `--in-file` included."""
    monkeypatch.setattr(ado_transport, "run_az", _REAL_RUN_AZ)
    seen = {}

    def fake_run(cmd, **kw):
        seen["path"] = cmd[cmd.index("--in-file") + 1]
        assert Path(seen["path"]).is_file()
        if isinstance(failure, BaseException):
            raise failure
        return failure

    monkeypatch.setattr(ado_transport.subprocess, "run", fake_run)
    with pytest.raises(AdoImportError) as err:
        ado_transport.invoke_body(tmp_path, "wit", "workItems", {"project": "Claims", "id": 1},
                                  method="PATCH", body=PATCH_BODY, timeout=7)
    message = str(err.value)
    assert seen["path"] not in message
    assert "devops invoke" in message and ("timed out after 7s" in message or "exited 3" in message)
    assert err.value.__cause__ is None and err.value.__suppress_context__  # the traceback cannot leak it either
    assert list(body_dir.iterdir()) == []
    captured = capsys.readouterr()
    assert seen["path"] not in captured.out + captured.err


# --- the body file ---------------------------------------------------------------------------------

def test_the_body_file_is_private_ascii_json_in_the_temp_dir_and_removed_on_success(writer, tmp_path, body_dir, capsys):
    body = [{"op": "add", "path": "/fields/System.Title", "value": 'probe & "quote" ✓ $(x)\nline two é'}]
    seen = SeenBody({"id": 1})
    writer({"POST wit/workItems": seen})
    ado_transport.invoke_body(tmp_path, "wit", "workItems", {"project": "Claims", "type": "$Task"},
                              method="POST", body=body)
    assert Path(seen.path).parent == body_dir and seen.path.endswith(".json")
    assert seen.dir_listing == [Path(seen.path).name]  # exactly one file while the call ran
    seen.raw.decode("ascii")  # pure ASCII: az reads --in-file in the locale encoding
    assert json.loads(seen.raw) == body  # and it round-trips exactly
    if os.name == "posix":
        assert seen.mode == 0o600
    assert not Path(seen.path).exists() and list(body_dir.iterdir()) == []
    captured = capsys.readouterr()
    assert seen.path not in captured.out + captured.err


@pytest.mark.parametrize("raised", [AdoImportError("HTTP 412 precondition failed"), RuntimeError("boom")])
def test_the_body_file_is_removed_when_run_az_raises(monkeypatch, tmp_path, body_dir, capsys, raised):
    seen = {}

    def boom(args):
        seen["path"] = in_file_of(args)
        seen["existed"] = os.path.exists(seen["path"])
        raise raised

    install(monkeypatch, boom)
    with pytest.raises(type(raised)) as err:
        ado_transport.invoke_body(tmp_path, "wit", "workItems", {"project": "Claims", "id": 1},
                                  method="PATCH", body=PATCH_BODY)
    assert err.value is raised  # a message without the path passes through untouched
    assert seen["existed"] and not os.path.exists(seen["path"])
    assert list(body_dir.iterdir()) == []
    captured = capsys.readouterr()
    assert seen["path"] not in captured.out + captured.err


def test_the_body_path_is_scrubbed_from_a_message_that_carries_it(monkeypatch, tmp_path, body_dir):
    def boom(args):
        raise AdoImportError(f"`az {args}` timed out after 60s.")

    install(monkeypatch, boom)
    with pytest.raises(AdoImportError) as err:
        ado_transport.invoke_body(tmp_path, "wit", "workItems", {"project": "Claims", "id": 1},
                                  method="PATCH", body=PATCH_BODY)
    assert str(body_dir) not in str(err.value)
    assert ado_transport.BODY_FILE_PLACEHOLDER in str(err.value) and "timed out after 60s" in str(err.value)


@pytest.fixture
def windows_body_dir(tmp_path, monkeypatch) -> Path:
    """A temp dir spelled the way the Windows runner's is -- backslashes and a non-ASCII user name -- so a message
    that quotes the body path quotes it differently from the path as given. On Windows the backslashes are the
    separators; elsewhere they are characters of one directory name, which POSIX allows."""
    parts = ("Users", "rünner", "AppData", "Local", "Temp")
    d = tmp_path.joinpath(*parts) if os.name == "nt" else tmp_path / "\\".join(("C:", *parts))
    d.mkdir(parents=True)
    assert "\\" in str(d)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(d))
    return d


@pytest.mark.parametrize("words", [
    pytest.param(lambda argv, path: f"`az {argv}` timed out after 60s.", id="argv-list-repr"),
    pytest.param(lambda argv, path: f"could not read {path}", id="as-given"),
    pytest.param(lambda argv, path: f"could not read {path.replace(chr(92), '/')}", id="as-posix"),
    pytest.param(lambda argv, path: f"bad request: {json.dumps({'file': path})}", id="json"),
])
def test_a_windows_body_path_is_scrubbed_in_every_spelling(monkeypatch, tmp_path, windows_body_dir, words):
    """The Windows leg: `run_az`'s argv list in a message spells `C:\\Users\\...` with every backslash doubled, so
    the path as given was not in it and nothing was scrubbed. Asserted on the directory's own words, not a pattern."""
    seen = {}

    def boom(args):
        seen["path"] = in_file_of(args)
        raise AdoImportError(words(args, seen["path"]))

    install(monkeypatch, boom)
    with pytest.raises(AdoImportError) as err:
        ado_transport.invoke_body(tmp_path, "wit", "workItems", {"project": "Claims", "id": 1},
                                  method="PATCH", body=PATCH_BODY)
    message = str(err.value)
    assert Path(seen["path"]).parent == windows_body_dir
    assert "rünner" not in message and "r\\u00fcnner" not in message and "AppData" not in message
    assert Path(seen["path"]).name not in message
    assert ado_transport.BODY_FILE_PLACEHOLDER in message
    assert err.value.__cause__ is None and err.value.__suppress_context__
    assert list(windows_body_dir.iterdir()) == []


@pytest.mark.parametrize("body", [[], {}], ids=["empty-list", "empty-dict"])
def test_an_empty_body_is_still_a_body(writer, tmp_path, body_dir, body):
    seen = SeenBody({"id": 1})
    writer({"PATCH wit/workItems": seen})
    ado_transport.invoke_body(tmp_path, "wit", "workItems", {"project": "Claims", "id": 1}, method="PATCH", body=body)
    assert seen.path is not None and json.loads(seen.raw) == body


def test_no_body_means_no_file_and_no_in_file_flags(az, tmp_path, body_dir):
    ado_transport.invoke_body(tmp_path, "wit", "workItemTypes", {"project": "Claims"})
    assert "--in-file" not in az.calls[0] and "--media-type" not in az.calls[0]
    assert list(body_dir.iterdir()) == []


def test_a_body_that_is_not_json_is_refused_without_a_file(az, tmp_path, body_dir):
    with pytest.raises(AdoImportError, match="not JSON-serialisable"):
        ado_transport.invoke_body(tmp_path, "wit", "workItems", {"project": "Claims", "id": 1},
                                  method="PATCH", body=[{"value": object()}])
    assert az.calls == [] and list(body_dir.iterdir()) == []


def test_a_body_file_that_is_already_gone_is_not_an_error(writer, tmp_path, body_dir):
    def vanish(args):
        os.unlink(in_file_of(args))
        return {"id": 1}

    writer({"PATCH wit/workItems": vanish})
    out = ado_transport.invoke_body(tmp_path, "wit", "workItems", {"project": "Claims", "id": 1},
                                    method="PATCH", body=PATCH_BODY)
    assert out == {"id": 1}


def test_a_full_disk_is_an_ado_error_that_does_not_name_the_path(az, tmp_path, body_dir, monkeypatch):
    def full(*args, **kwargs):
        raise OSError(28, "No space left on device", str(body_dir / "tmpabc123.json"))

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", full)
    with pytest.raises(AdoImportError, match="No space left on device") as err:
        ado_transport.invoke_body(tmp_path, "wit", "workItems", {"project": "Claims", "id": 1},
                                  method="PATCH", body=PATCH_BODY)
    assert "tmpabc123" not in str(err.value)
    assert az.calls == []


def test_a_chmod_failure_removes_the_file_it_had_created(az, tmp_path, body_dir, monkeypatch):
    def refuse(path, mode):
        raise PermissionError(1, "Operation not permitted", path)

    monkeypatch.setattr(ado_transport.os, "chmod", refuse)
    with pytest.raises(AdoImportError, match="Operation not permitted") as err:
        ado_transport.invoke_body(tmp_path, "wit", "workItems", {"project": "Claims", "id": 1},
                                  method="PATCH", body=PATCH_BODY)
    assert str(body_dir) not in str(err.value)
    assert az.calls == [] and list(body_dir.iterdir()) == []


# --- the response ----------------------------------------------------------------------------------

@pytest.mark.parametrize("reply", [[], {}, {"count": 0, "value": []}, [{"id": 1}], {"id": 7, "rev": 2, "odd": None}])
def test_the_response_is_returned_as_parsed_with_no_shape_check(writer, tmp_path, reply):
    writer({"GET wit/updates": reply})
    assert ado_transport.invoke_body(tmp_path, "wit", "updates", {"project": "Claims", "id": 1}) == reply


@pytest.mark.parametrize("stdout", ["", "  \n"], ids=["empty", "whitespace"])
def test_an_empty_stdout_is_an_empty_list_for_a_get(monkeypatch, tmp_path, stdout):
    install(monkeypatch, lambda args: stdout)  # the raw seam: a FakeBoardsAz reads a str answer as a fixture name
    assert ado_transport.invoke_body(tmp_path, "wit", "updates", {"project": "Claims", "id": 1}) == []


@pytest.mark.parametrize("method", sorted(boards_contract.WRITE_METHODS))
def test_an_empty_stdout_on_a_write_is_an_error(writer, tmp_path, body_dir, method):
    fake = writer()
    fake.answers[f"{method} wit/workItems"] = None
    body = None if method == "DELETE" else PATCH_BODY
    with pytest.raises(AdoImportError) as err:
        ado_transport.invoke_body(tmp_path, "wit", "workItems", {"project": "Claims", "id": 1},
                                  method=method, body=body)
    assert str(err.value) == "empty response on write"
    assert list(body_dir.iterdir()) == []


def test_a_lowercase_write_method_is_still_a_write_for_an_empty_stdout(writer, tmp_path, body_dir):
    writer().answers["PATCH wit/workItems"] = None
    with pytest.raises(AdoImportError, match="empty response on write"):
        ado_transport.invoke_body(tmp_path, "wit", "workItems", {"project": "Claims", "id": 1},
                                  method="patch", body=PATCH_BODY)


def test_unparseable_json_is_an_ado_error_without_the_path_or_the_text(monkeypatch, tmp_path, body_dir):
    install(monkeypatch, lambda args: "{not json: a private comment")
    with pytest.raises(AdoImportError, match="unparseable JSON") as err:
        ado_transport.invoke_body(tmp_path, "wit", "workItems", {"project": "Claims", "id": 1},
                                  method="PATCH", body=PATCH_BODY)
    assert str(body_dir) not in str(err.value) and "private comment" not in str(err.value)
    assert list(body_dir.iterdir()) == []
