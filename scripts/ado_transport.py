"""The one impure seam for Azure DevOps: how `az` is spawned (code-host providers, Wave 1).

The twin of `github_import.run_gh / gh_json`, with the same contract (UTF-8 forced, 60 s timeout,
one exception type) plus the az-specific rules, each of which is a pitfall met in practice
(docs/proposals/code-host-providers.md §4.3; fixtures/code_host/azure_devops/captured/CAPTURE-NOTES.md):
  * `AZURE_EXTENSION_USE_DYNAMIC_INSTALL=no` — a missing extension or a typo otherwise triggers an
    unprompted network install (observed: the extension upgraded itself mid-survey).
  * `AZURE_CORE_COLLECT_TELEMETRY=no` — no telemetry fork per call.
  * `--only-show-errors` always — preview/upgrade warnings land on stderr even on success.
  * `--detect false --org --project [--repository]` from the PARSED REMOTE — az's own detection
    costs a `GET …/vsts/info` round-trip per call and needs auth.
  * `--api-version` always on `devops invoke` — the default is 5.0, which predates Environments.
    Environments and deployment records need `7.1-preview` exactly: `7.1-preview.1` crashes the
    extension (`could not convert string to float: '7.1.1'`, captured 2026-10-05).
  * Empty stdout is `[]` — `az boards query` prints NOTHING when no work item matches (captured),
    and an empty list is the honest reading of "nothing matched", not an error.
  * The CLI's DEFAULT ACCOUNT decides the Azure DevOps token. An identity that has never opened
    the organisation in a browser gets HTTP 403 "Identity … has not been materialized"; the
    error is passed on with what to do about it, because the raw text does not say.

Tests monkeypatch `subprocess.run` (for the transport itself) or `az_json` (for everything above
it); nothing in the suite spawns a real `az`.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import code_host  # noqa: E402
from ado_map import AdoImportError  # noqa: E402

AZ_ENV = code_host.AZ_ENV
API_VERSION = "7.1"
PREVIEW_API_VERSION = "7.1-preview"  # environments / environmentdeploymentrecords ONLY (see above)
MATERIALIZED_HINT = ("the signed-in identity has never opened this organisation in a browser: sign in to it "
                     "interactively once with the account az is using (az's default account decides the "
                     "token; a guest in the organisation's tenant needs "
                     "`az login --allow-no-subscriptions --tenant <tenant id>`)")

# Per-process caches. The scope is parsed once per repo; the repository record serves every
# threads/commits route (it needs the repository GUID); threads serve two fetchers (bodies and
# events) for one PR; the pipelines list and each definition's `show` serve every rail.
# `clear_caches()` exists for tests.
_SCOPE: dict[str, code_host.RemoteInfo] = {}
_REPO: dict[str, dict] = {}
_THREADS: dict[tuple[str, int], dict] = {}
_PIPELINES: dict[str, list] = {}
_PIPELINE_SHOW: dict[tuple[str, int], dict] = {}


def clear_caches() -> None:
    _SCOPE.clear()
    _REPO.clear()
    _THREADS.clear()
    _PIPELINES.clear()
    _PIPELINE_SHOW.clear()


def az_binary() -> str:
    # shutil.which honours PATHEXT, so on Windows this resolves the `az.cmd` shim.
    return shutil.which("az") or "az"


def run_az(args: list[str], cwd, timeout: int = 60) -> str:
    """Shell out to `az`, returning stdout. Never raises anything but AdoImportError."""
    cmd = [az_binary(), *args, "--only-show-errors"]
    try:
        result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout, env={**os.environ, **AZ_ENV})
    except FileNotFoundError as e:
        raise AdoImportError("The Azure CLI (`az`) is not installed or not on PATH.") from e
    except subprocess.TimeoutExpired as e:
        raise AdoImportError(f"`az {' '.join(args)}` timed out after {timeout}s.") from e
    if result.returncode != 0:
        err = result.stderr.strip()
        if "azure-devops" in err and "extension" in err.lower():
            err = f"{err}\nrun `az extension add --name azure-devops`"
        elif "materialized" in err:
            err = f"{err}\n{MATERIALIZED_HINT}"
        raise AdoImportError(err or f"`az {' '.join(args)}` exited {result.returncode}.")
    return result.stdout


def az_json(args: list[str], cwd):
    out = run_az([*args, "-o", "json"], cwd)
    try:
        return json.loads(out) if out.strip() else []
    except json.JSONDecodeError as e:
        raise AdoImportError(f"`az {' '.join(args)}` returned unparseable JSON: {e}") from e


def remote(repo_root) -> code_host.RemoteInfo:
    """The parsed Azure DevOps remote for this checkout (honouring `.sdlc/code-host.yaml`), or an
    AdoImportError that says what to do — never a guess at an org."""
    key = str(repo_root)
    if key not in _SCOPE:
        det = code_host.detect_host(repo_root)
        if det.remote is None or det.remote.host != "azure-devops":
            raise AdoImportError(f"origin is not an Azure DevOps remote ({det.detail}); "
                                 f"set organization/project/repository in {code_host.CODE_HOST_FILE}")
        _SCOPE[key] = det.remote
    return _SCOPE[key]


def scope(repo_root, with_repository: bool = True) -> list[str]:
    r = remote(repo_root)
    args = ["--detect", "false", "--org", r.org_url, "--project", r.project]
    return [*args, "--repository", r.repo] if with_repository else args


def invoke(repo_root, area: str, resource: str, route: dict, api_version: str = API_VERSION) -> dict:
    """`az devops invoke` for the REST resources that have no native verb (threads, commits,
    timeline, environments). `api_version` is PREVIEW_API_VERSION for the environments area only."""
    params = [f"{k}={v}" for k, v in route.items()]
    return az_json(["devops", "invoke", "--area", area, "--resource", resource, "--route-parameters", *params,
                    "--api-version", api_version, "--org", remote(repo_root).org_url], repo_root)


# ---------------------------------------------------------------------------------------------------
# Azure Boards mirror (B1-P1): `devops invoke` WITH a request body. Appended below `invoke()`, which
# stays byte-for-byte as shipped, as do `az_json()` and `run_az()`: `invoke()` still serves the two
# code-host callers, `az_json` has no `timeout` (adding one would break every `FakeAz.__call__(args,
# cwd)` in the suite), and `--only-show-errors` is still appended INSIDE `run_az` — a fake standing in
# for `run_az` never sees it. `invoke_body` calls `run_az` directly so a test patches one seam.
# The imports sit here, not at the top of the file, so that the whole change is an append.
import re  # noqa: E402
import tempfile  # noqa: E402

_PREVIEW_REVISION_RE = re.compile(r"-preview\.\d")
_WRITE_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})  # == boards_contract.WRITE_METHODS (a test pins it)
BODY_FILE_PLACEHOLDER = "<request body file>"


def check_api_version(v: str) -> str:
    """`v` unchanged, or an AdoImportError for a preview pinned to a revision number. Only
    API_VERSION and PREVIEW_API_VERSION leave this module: a revision crashes the az extension."""
    if _PREVIEW_REVISION_RE.search(v):
        raise AdoImportError(f"api-version {v!r} pins a preview revision, which crashes the az extension; "
                             f"use API_VERSION ({API_VERSION}) or PREVIEW_API_VERSION ({PREVIEW_API_VERSION})")
    return v


def _unlink_quietly(path: str) -> None:
    # Best effort. Raising here would replace the error that matters (an HTTP 412, a timeout), and the
    # file is private (0600) in the temp directory.
    try:
        os.unlink(path)
    except OSError:
        pass


def _path_spellings(path: str) -> list[str]:
    """Every way an error message may spell `path`, longest first: as given; with forward slashes
    (a Windows path's `as_posix()`); and escaped as `repr()` and JSON quote it, which is how it
    reads when a whole argv list is put in a message. On Windows that doubles every backslash of
    `C:\\Users\\...`, so the path as given is not a substring of the message at all."""
    spellings = {path, path.replace("\\", "/"), repr(path)[1:-1], json.dumps(path)[1:-1]}
    return sorted((s for s in spellings if s), key=len, reverse=True)


def _scrub_path(text: str, path: str) -> str:
    for spelling in _path_spellings(path):
        text = text.replace(spelling, BODY_FILE_PLACEHOLDER)
    return text


def _write_body_file(payload: str) -> str:
    """The request body in a private temp file; returns its path, which is never printed. A file
    that was created is removed again if preparing it fails, and no OSError text (it names the path) escapes."""
    path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            path = f.name
            os.chmod(path, 0o600)  # before a byte of the body is written
            f.write(payload)
    except OSError as e:
        if path is not None:
            _unlink_quietly(path)
        raise AdoImportError(f"could not write the request body to a temporary file: "
                             f"{e.strerror or type(e).__name__}") from None
    return path


def invoke_body(repo_root, area: str, resource: str, route: dict, *, method: str = "GET", body: list | dict | None = None,
                media_type: str = "application/json-patch+json", query: dict | None = None,
                api_version: str = API_VERSION, timeout: int = 60) -> dict | list:
    """`az devops invoke` with an optional JSON request body (`--in-file`), returning the parsed JSON.

    Returned as parsed, with NO shape validation — a caller `_require`s what it reads, because a check
    here would break a `workitemsbatch` read that legitimately omits an id. Empty stdout is `[]` for a
    read and an AdoImportError for a write (a write that answered nothing is not known to have worked).
    `--detect false` is always emitted and the project is a route parameter, never `--project`.
    The body goes through a 0600 temp file that is removed on every path, and its path is scrubbed
    from any error `run_az` words from its own argv, in each spelling `_path_spellings` lists (a
    Windows path printed inside an argv list's repr has every backslash doubled). Raises only AdoImportError."""
    method = method.upper()
    version = check_api_version(api_version)  # before any file exists
    org_url = remote(repo_root).org_url
    payload = None
    if body is not None:  # `[]` and `{}` are bodies
        try:
            # ASCII-only (ensure_ascii): az reads --in-file in the locale encoding, so any non-ASCII
            # text would arrive as mojibake on a non-UTF-8 console. The JSON escapes decode identically.
            payload = json.dumps(body)
        except (TypeError, ValueError) as e:
            raise AdoImportError(f"the request body is not JSON-serialisable: {e}") from e
    body_path = _write_body_file(payload) if payload is not None else None
    try:
        argv = ["devops", "invoke", "--area", area, "--resource", resource,
                "--route-parameters", *[f"{k}={v}" for k, v in route.items()],
                "--http-method", method,
                *(["--in-file", body_path, "--media-type", media_type] if body_path is not None else []),
                *(["--query-parameters", *[f"{k}={v}" for k, v in query.items()]] if query else []),
                "--api-version", version, "--detect", "false", "--org", org_url, "-o", "json"]
        out = run_az(argv, repo_root, timeout=timeout)
    except AdoImportError as e:
        if body_path is not None and _scrub_path(str(e), body_path) != str(e):
            raise AdoImportError(_scrub_path(str(e), body_path)) from None
        raise
    finally:
        if body_path is not None:
            _unlink_quietly(body_path)
    if not out.strip():
        if method in _WRITE_METHODS:
            raise AdoImportError("empty response on write")
        return []
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise AdoImportError(f"`az devops invoke --area {area} --resource {resource}` returned "
                             f"unparseable JSON: {e}") from e
