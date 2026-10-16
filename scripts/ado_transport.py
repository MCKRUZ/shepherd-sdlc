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
import re
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
        _check_remote_names(det.remote)
        _SCOPE[key] = det.remote
    return _SCOPE[key]


# On Windows `az` resolves to the `az.cmd` shim, so cmd.exe re-parses every argument; `list2cmdline` quotes only an
# argument that contains a space, so a space-free `project=R&D` would run `D` as a second command. The organisation,
# project and repository names come from `.sdlc/code-host.yaml` (committed, travels with the clone) or from `origin`,
# so they are checked ONCE here, before any `az` argv is built — every call site (`scope`, `invoke`, `invoke_body`,
# `rest_*`) goes through `remote()`. Security review of PR #5 (2026-10-16), MEDIUM.
_ORG_URL_OK = re.compile(r"^https://(dev\.azure\.com/[\w.-]+|[\w-]+\.visualstudio\.com)/?$")
_NAME_OK = re.compile(r"^[\w .()~@-]+$")          # letters/digits of any script, space, and the punctuation ADO allows


def _check_remote_names(r) -> None:
    """Refuse an organisation URL, project or repository name that cmd.exe would read as more than one argument
    (`& | < > ^ % ! "`, quotes, brackets, backslashes, control characters). The refusal names the field, never
    repeats the value."""
    if not isinstance(r.org_url, str) or not _ORG_URL_OK.match(r.org_url):
        raise AdoImportError(f"the Azure DevOps organisation URL in {code_host.CODE_HOST_FILE} (or origin) is not of the form "
                             "https://dev.azure.com/<org> or https://<org>.visualstudio.com; refusing to call az with it")
    for field, value in (("project", r.project), ("repository", r.repo)):
        if value is None and field == "repository":
            continue
        if not isinstance(value, str) or not value.strip() or not _NAME_OK.match(value) or value != value.strip():
            raise AdoImportError(f"the Azure DevOps {field} name in {code_host.CODE_HOST_FILE} (or origin) carries a character "
                                 "the shell could interpret (one of & | < > ^ % ! \" ' [ ] \\ or a control character); "
                                 "refusing to call az with it")


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


# ---------------------------------------------------------------------------------------------------
# B0 capture (2026-10-14): who the token belongs to (`connectionData`) is not an `az devops invoke`
# location — area `core` answers "--resource and --api-version combination is not correct", area
# `Location` "--area is not present in current organization". `az rest` reaches it, with an Entra token
# az mints for Azure DevOps' own resource id. `rest_get` is the ONE `az rest` this module sends: a GET, of
# a path in REST_READS only, under the parsed remote's organisation URL, at PREVIEW_API_VERSION (`7.1` is
# refused: "the requested version 7.1 of the resource is under preview"). Appended, as `invoke_body` was;
# everything above stays byte-for-byte as shipped.
ADO_RESOURCE_ID = "499b84ac-1321-427f-aa17-267ca6975798"  # == boards_contract.ADO_RESOURCE_ID (pinned by test)
REST_READS = frozenset({"_apis/connectionData"})          # == the paths of boards_contract.REST_ROUTES (pinned)
# What `az rest` says when it holds no Entra sign-in to mint the token from (a personal access token alone is
# such a sign-in): "Please run 'az login' to setup account." Re-worded so the identity reads as UNKNOWN — the
# CLI may well be signed in to Azure DevOps with that PAT, so `host_report.cli_state_from_error` must not read
# this as signed out. A "not materialized" refusal keeps its own words and hint (see `run_az`).
_NO_TOKEN_RE = re.compile(r"az login|setup account", re.IGNORECASE)
REST_NO_TOKEN = ("`az rest` could not mint an Entra token for Azure DevOps, so who is signed in could not be read "
                 "(connectionData); a personal access token alone cannot answer this read, and the identity is "
                 "unknown, not someone else's")


def rest_argv(org_url: str, path: str, api_version: str = PREVIEW_API_VERSION) -> list[str]:
    """The `az rest` argv for one allow-listed GET (`-o json` included; `run_az` adds `--only-show-errors`)."""
    if path not in REST_READS:
        raise AdoImportError(f"`az rest` reads only {sorted(REST_READS)}; {path!r} is not one of them")
    version = check_api_version(api_version)
    if version not in (API_VERSION, PREVIEW_API_VERSION):
        raise AdoImportError(f"api-version {version!r} is neither {API_VERSION} nor {PREVIEW_API_VERSION}")
    return ["rest", "--method", "get", "--resource", ADO_RESOURCE_ID, "--url",
            f"{org_url.rstrip('/')}/{path}?api-version={version}", "-o", "json"]


def rest_get(repo_root, path: str, *, api_version: str = PREVIEW_API_VERSION, timeout: int = 60) -> dict | list:
    """`az rest --method get` of an allow-listed organisation-level path, returning the parsed JSON with no shape
    check (the caller `_require`s what it reads). Empty stdout is `[]`, as for every read. A failure is an
    AdoImportError; one saying az holds no Entra token is `REST_NO_TOKEN`, never az's own "run az login"."""
    argv = rest_argv(remote(repo_root).org_url, path, api_version)
    try:
        out = run_az(argv, repo_root, timeout=timeout)
    except AdoImportError as e:
        if "materialized" not in str(e) and _NO_TOKEN_RE.search(str(e)):
            raise AdoImportError(REST_NO_TOKEN) from None
        raise
    if not out.strip():
        return []
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise AdoImportError(f"`az rest --method get` of {path} returned unparseable JSON: {e}") from e


# ---------------------------------------------------------------------------------------------------
# B0 write fixes (2026-10-15, the first live `apply`): a work item UPDATE cannot go through `az devops invoke`.
# `workItems` has two locations, `{project}/_apis/wit/workItems/${type}` and `…/workItems/{id}`; for a PATCH the
# extension binds the first and dies inside itself (`ERROR: 'type'`, a KeyError; captured). `az rest --method patch`
# of the `{id}` URL works, with the same Entra token as `rest_get`. `rest_patch` is the ONE `az rest` write this
# module sends: a PATCH, of a path template in REST_WRITES only, filled from checked values, under the parsed
# remote's organisation URL, at API_VERSION, the JSON Patch in a 0600 temp file passed as `--body @<file>` exactly
# as `invoke_body` passes `--in-file` (and removed, and scrubbed from errors, the same way). Appended, as `rest_get`
# was; everything above stays byte-for-byte as shipped.
from urllib.parse import quote  # noqa: E402


def az_json_read(args: list[str], cwd) -> tuple[object, bool]:
    """`(parsed, printed_nothing)` of a read: `az_json`'s argv and parsing, plus whether stdout was empty. Empty
    stdout is `([], True)`, never a JSON error — `az boards query` prints nothing when no work item matches, and it
    printed nothing for the current-project macro too (B0, 2026-10-15), so a caller can say it read nothing."""
    out = run_az([*args, "-o", "json"], cwd)
    if not out.strip():
        return [], True
    try:
        return json.loads(out), False
    except json.JSONDecodeError as e:
        raise AdoImportError(f"`az {' '.join(args)}` returned unparseable JSON: {e}") from e


REST_WRITES =frozenset({"{project}/_apis/wit/workitems/{id}"})   # == the PATCH paths of boards_contract.REST_ROUTES
REST_PATCH_MEDIA_TYPE = "application/json-patch+json"
# A PATCH under a personal-access-token-only sign-in: az cannot mint the Entra token, so nothing was sent.
REST_NO_TOKEN_WRITE = ("`az rest` could not mint an Entra token for Azure DevOps, so the update was not sent: a work "
                       "item update goes through `az rest` (`az devops invoke` cannot PATCH a work item), which needs "
                       "an Entra sign-in (`az login`); a personal access token alone cannot send it")
_PLACEHOLDER_RE = re.compile(r"\{([a-z]+)\}")


def _fill_rest_path(template: str, route: dict) -> str:
    """`template` with every `{name}` filled from `route`: `project` percent-encoded whole (no `/` survives), `id` a
    positive integer. A name the template has and `route` does not, or one `route` has and the template does not,
    is an AdoImportError: a URL is never built from a guess."""
    names = _PLACEHOLDER_RE.findall(template)
    if set(names) != set(route):
        raise AdoImportError(f"`az rest` path {template!r} takes {sorted(names)}, not {sorted(route)}")

    def value(match) -> str:
        name, raw = match.group(1), route[match.group(1)]
        if name == "id":
            if type(raw) is not int or raw < 1:
                raise AdoImportError(f"`az rest` path {template!r}: id must be a positive integer, not {raw!r}")
            return str(raw)
        if not isinstance(raw, str) or not raw.strip() or any(ord(c) < 32 or ord(c) == 127 for c in raw):
            raise AdoImportError(f"`az rest` path {template!r}: {name} must be a name, not {raw!r}")
        encoded = quote(raw, safe="")
        # The URL is an argument of `az rest`; on Windows `az` is the `az.cmd` shim and cmd.exe would expand a
        # `%…%` pair inside it (`A%20B%20C` holds `%20B%`), so a value whose encoding carries two or more `%` is
        # refused there rather than sent mangled (security review of PR #5, LOW). An `az.exe`, or any other OS,
        # passes the URL through untouched.
        if encoded.count("%") >= 2 and az_binary().lower().endswith((".cmd", ".bat")):
            raise AdoImportError(f"`az rest` path {template!r}: the {name} name encodes to a URL with a `%…%` pair, which "
                                 "the az.cmd shim's cmd.exe would expand; on Windows use an `az.exe` on PATH, or a "
                                 "project name with at most one space or reserved character")
        return encoded
    return _PLACEHOLDER_RE.sub(value, template)


def rest_write_argv(org_url: str, path: str, route: dict, body_path: str, api_version: str = API_VERSION) -> list[str]:
    """The `az rest` argv for one allow-listed PATCH (`-o json` included; `run_az` adds `--only-show-errors`)."""
    if path not in REST_WRITES:
        raise AdoImportError(f"`az rest` writes only {sorted(REST_WRITES)}; {path!r} is not one of them")
    version = check_api_version(api_version)
    if version != API_VERSION:
        raise AdoImportError(f"api-version {version!r} is not {API_VERSION}: an update is a released call")
    return ["rest", "--method", "patch", "--resource", ADO_RESOURCE_ID, "--url",
            f"{org_url.rstrip('/')}/{_fill_rest_path(path, route)}?api-version={version}",
            "--headers", f"Content-Type={REST_PATCH_MEDIA_TYPE}", "--body", f"@{body_path}", "-o", "json"]


def rest_patch(repo_root, path: str, route: dict, body: list, *, api_version: str = API_VERSION,
               timeout: int = 60) -> dict | list:
    """`az rest --method patch` of an allow-listed path template, `route` filling it, `body` (a JSON Patch list) sent
    as `application/json-patch+json` from a private temp file, returning the parsed JSON with no shape check (the
    caller `_require`s what it reads). Empty stdout is an AdoImportError ("empty response on write"): a write that
    answered nothing is not known to have worked. One saying az holds no Entra token is `REST_NO_TOKEN_WRITE`. The
    body file is 0600, removed on every path, and its path is scrubbed from any error. Raises only AdoImportError."""
    if not isinstance(body, list):
        raise AdoImportError("an `az rest` PATCH body is a JSON Patch: a list of operations")
    try:
        payload = json.dumps(body)   # ASCII-only, as `invoke_body`: az reads the file in the locale encoding
    except (TypeError, ValueError) as e:
        raise AdoImportError(f"the request body is not JSON-serialisable: {e}") from e
    org_url = remote(repo_root).org_url
    rest_write_argv(org_url, path, route, BODY_FILE_PLACEHOLDER, api_version)   # refused before any file exists
    body_path = _write_body_file(payload)
    try:
        out = run_az(rest_write_argv(org_url, path, route, body_path, api_version), repo_root, timeout=timeout)
    except AdoImportError as e:
        text = _scrub_path(str(e), body_path)
        if "materialized" not in text and _NO_TOKEN_RE.search(text):
            raise AdoImportError(REST_NO_TOKEN_WRITE) from None
        if text != str(e):
            raise AdoImportError(text) from None
        raise
    finally:
        _unlink_quietly(body_path)
    if not out.strip():
        raise AdoImportError("empty response on write")
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise AdoImportError(f"`az rest --method patch` of {path} returned unparseable JSON: {e}") from e
