"""Which code host this repository is on, and which CLI talks to it (code-host providers, Wave 1).

Two axes, never merged: the CODE HOST (where the pull requests live — the `origin` remote, with
`--host` / `SHEPHERD_CODE_HOST` (the pre-2.0 `SDLC_CODE_HOST` is still read) / `.sdlc/code-host.yaml`
ahead of it) and the CI PLATFORM (where the pipelines live — the harness manifest, exactly as
`doctor.installed_platform()` reads it; a ten-line twin here so the diagnostic module is not
imported, and a test pins that they agree).

`host: none` deliberately falls through to `gh`: every repository that exists today keeps the
behaviour it has, and the gh error becomes the familiar `code_host_available: false`.

Standalone or Workflow:
  - Standalone: --repo <path>
  - Workflow:   --state .sdlc/state.yaml
Always exits 0 (a usage error is 2). `--json` prints exactly one document.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from code_host_remote import RemoteInfo, parse_remote  # noqa: E402,F401  (re-exported)
from code_host_shapes import (  # noqa: E402,F401  (re-exported)
    PROVIDER_FUNCTION_NAMES, PROVIDER_FUNCTIONS, Check, Identity, Job, PullRequest, RepoView,
    Review, ReviewRequest, Ruleset, Run,
)
from github_import import GitHubImportError  # noqa: E402

CodeHostError = GitHubImportError  # new code reads naturally; old `except` clauses keep working

HOSTS = ("github", "azure-devops", "none")
CLI_STATES = ("available", "not_installed", "extension_missing", "signed_out", "unknown")
CODE_HOST_ENV = "SHEPHERD_CODE_HOST"
LEGACY_CODE_HOST_ENV = "SDLC_CODE_HOST"  # the pre-2.0 name — still read, after the new one (code_host_env)
CODE_HOST_ENV_VARS = (CODE_HOST_ENV, LEGACY_CODE_HOST_ENV)
ENV_VAR = CODE_HOST_ENV  # the name the `env` source is labelled with; kept for the callers and tests that import it
CODE_HOST_FILE = ".sdlc/code-host.yaml"
AZ_ENV = {"AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no", "AZURE_CORE_COLLECT_TELEMETRY": "no"}


class Detection(NamedTuple):
    host: str                   # github | azure-devops | none
    source: str                 # flag | env | file | remote | manifest | default
    remote: RemoteInfo | None   # whatever could be parsed, even when the host came from an override
    detail: str                 # why — "from origin https://…", "no origin remote", …


# ── the CI axis (twin of doctor.installed_platform — kept in step by a test, not an import) ──

def installed_ci_platform(repo_root) -> str:
    """`azure-devops` only when the manifest names that CI/CD pack; a missing, corrupt, pack-less or
    type-corrupt manifest is `github` — the pre-pack behaviour (TypeError covers `"packs": 5`)."""
    manifest = Path(repo_root) / ".claude" / "harness-manifest.json"
    try:
        packs = json.loads(manifest.read_text(encoding="utf-8")).get("packs") or []
        return "azure-devops" if "cicd/azure-devops" in packs else "github"
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        return "github"


# ── the code-host axis ──────────────────────────────────────────────────────────────────────

def origin_url(repo_root) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(repo_root), "remote", "get-url", "origin"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def read_code_host_file(repo_root) -> tuple[dict | None, str | None]:
    """(settings, error). Absent → (None, None); malformed → an error string, never a silent default."""
    path = Path(repo_root) / CODE_HOST_FILE
    if not path.is_file():
        return None, None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        return None, f"{CODE_HOST_FILE} could not be read: {e}"
    if not isinstance(doc, dict):
        return None, f"{CODE_HOST_FILE}: expected a mapping with a `host:` key"
    host = doc.get("host")
    if host not in HOSTS:
        return None, f"{CODE_HOST_FILE}: host must be one of {', '.join(HOSTS)} (got {host!r})"
    for key in ("organization", "project", "repository"):
        if key in doc and doc[key] is not None and not isinstance(doc[key], str):
            return None, f"{CODE_HOST_FILE}: {key} must be a string"
    return doc, None


def _remote_from_file(settings: dict) -> RemoteInfo | None:
    """The three optional fields stand in for a remote parse_remote could not read."""
    org, project, repo = (settings.get(k) for k in ("organization", "project", "repository"))
    if settings.get("host") != "azure-devops" or not (org and project and repo):
        return None  # gh resolves its own repository from cwd; only az needs the three parts
    return RemoteInfo("azure-devops", org, project, repo, f"{org}/{project}/{repo}",
                      f"https://dev.azure.com/{org}", f"https://dev.azure.com/{org}/{project}/_git/{repo}")


def code_host_env(environ=None) -> tuple[str, str | None]:
    """(name, value) of the first code-host variable that holds a value: `SHEPHERD_CODE_HOST` wins,
    `SDLC_CODE_HOST` — the pre-2.0 name, already in shells and CI — is read when it does not. An
    empty value counts as unset, as it always did. Neither set → (CODE_HOST_ENV, None)."""
    environ = os.environ if environ is None else environ
    for name in CODE_HOST_ENV_VARS:
        value = environ.get(name)
        if value:
            return name, value
    return CODE_HOST_ENV, None


def detect_host(repo_root, override: str | None = None) -> Detection:
    """Precedence: flag → env → .sdlc/code-host.yaml → origin remote → manifest tie-breaker → none."""
    repo_root = Path(repo_root)
    notes: list[str] = []
    url = origin_url(repo_root)
    remote = parse_remote(url)

    if override is not None:
        if override not in HOSTS:
            raise ValueError(f"--host must be one of {', '.join(HOSTS)} (got {override!r})")
        return Detection(override, "flag", remote, f"--host {override}")

    env_name, env_value = code_host_env()
    if env_value:
        if env_value in HOSTS:
            return Detection(env_value, "env", remote, f"{env_name}={env_value}")
        notes.append(f"{env_name}={env_value!r} ignored: not one of {', '.join(HOSTS)}")

    settings, file_error = read_code_host_file(repo_root)
    if settings:
        return Detection(settings["host"], "file", remote or _remote_from_file(settings),
                         f"{CODE_HOST_FILE} host: {settings['host']}")
    if file_error:
        notes.append(file_error)

    if remote is not None:
        return Detection(remote.host, "remote", remote, "; ".join([f"from origin {url}", *notes]))

    host_name = (url.split("://", 1)[-1].split("/", 1)[0].split("@")[-1] if "://" in url else url.split(":", 1)[0]) if url else None
    notes.insert(0, f'unrecognised host "{host_name}"' if url else "no origin remote")

    # The manifest decides only when the remote could not: a fresh clone without `origin` on an
    # Azure Pipelines install is almost certainly an Azure DevOps repository. It never overrides
    # a remote that parsed — GitHub + Azure Pipelines is a real combination.
    if installed_ci_platform(repo_root) == "azure-devops":
        return Detection("azure-devops", "manifest", None,
                         "; ".join([*notes, "harness manifest names cicd/azure-devops"]))
    return Detection("none", "default", None, "; ".join(notes))


def cli_for(host: str) -> str:
    """`none` → gh on purpose (legacy default; see the module docstring)."""
    return "az" if host == "azure-devops" else "gh"


def _run_ok(run, args: list[str], env: dict | None) -> bool:
    return run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
               timeout=30, check=False, env=env).returncode == 0


def cli_state(host: str, *, which=shutil.which, run=subprocess.run) -> tuple[str, str]:
    """(state, detail). `az extension show` / `az account show` read cached config; `gh auth status`
    may validate its token. Tests inject `which`/`run`; the suite never runs these live."""
    cli = cli_for(host)
    try:
        if which(cli) is None:
            return "not_installed", ("the Azure CLI is not installed" if cli == "az"
                                     else "the GitHub CLI is not installed")
        if cli == "az":
            env = {**os.environ, **AZ_ENV}
            if not _run_ok(run, ["az", "extension", "show", "--name", "azure-devops", "-o", "json",
                                 "--only-show-errors"], env):
                return "extension_missing", "run `az extension add --name azure-devops`"
            if not _run_ok(run, ["az", "account", "show", "-o", "json", "--only-show-errors"], env):
                return "signed_out", "run `az login`"
            return "available", "az is installed, the azure-devops extension is present, and an account is signed in"
        if not _run_ok(run, ["gh", "auth", "status"], None):
            return "signed_out", "run `gh auth login`"
        return "available", "gh is installed and signed in"
    except (OSError, subprocess.TimeoutExpired) as e:
        return "unknown", f"the CLI probe itself failed: {e}"


# ── identity ────────────────────────────────────────────────────────────────────────────────

def resolve_person(roster: dict | None, identity: dict | None) -> str | None:
    """The roster handle for a host identity, or None. GitHub: `@login` when that handle is on the
    roster. Azure DevOps: the person whose `email` equals the UPN, case-insensitively. Never a
    guess from a display name or a UPN prefix — an unmapped person is reported as unmapped."""
    if not isinstance(roster, dict) or not isinstance(identity, dict):
        return None
    login = (identity.get("login") or "").strip()
    if not login:
        return None
    people = [p for p in (roster.get("people") or []) if isinstance(p, dict)]
    kind = identity.get("kind") or ("upn" if "@" in login else "login")
    if kind == "upn":
        for p in people:
            if isinstance(p.get("email"), str) and p["email"].strip().lower() == login.lower():
                return p.get("handle")
        return None
    handle = f"@{login.lstrip('@')}"
    return handle if any(p.get("handle") == handle for p in people) else None


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────

def host_block(detection: Detection, *, probe: bool = True) -> dict:
    """The top-level `host` block every host-touching --json carries."""
    state, detail = cli_state(detection.host) if probe else ("unknown", "CLI not probed (--no-probe)")
    return {"name": detection.host, "source": detection.source, "cli": cli_for(detection.host),
            "cli_state": state, "detail": detection.detail if state == "available" or not probe
            else f"{detection.detail}; {detail}"}


def resolve_repo_root(args) -> Path:
    if args.state:
        return Path(args.state).resolve().parent.parent
    return Path(args.repo).resolve()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Which code host is this repository on, and which CLI talks to it?")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--state", help="Path to .sdlc/state.yaml (workflow mode)")
    src.add_argument("--repo", default=".", help="Target repo root (standalone mode; default: cwd)")
    parser.add_argument("--host", choices=HOSTS, default=None, help="Override detection for this invocation")
    parser.add_argument("--json", action="store_true", help="Emit exactly one JSON document")
    parser.add_argument("--no-probe", action="store_true",
                        help="Do not run the local CLI probes (gh auth status / az account show); cli_state reads unknown")
    args = parser.parse_args(argv)

    root = resolve_repo_root(args)
    detection = detect_host(root, args.host)
    result = {
        "host": host_block(detection, probe=not args.no_probe),
        "remote": detection.remote._asdict() if detection.remote else None,
        "ci_platform": installed_ci_platform(root),
    }
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    h = result["host"]
    print(f"Code host: {h['name']} (from {h['source']}) — CLI: {h['cli']} [{h['cli_state']}]")
    print(f"  {h['detail']}")
    if result["remote"]:
        print(f"  Remote: {result['remote']['slug']}")
    print(f"  CI platform: {result['ci_platform']}"
          + ("" if result["ci_platform"] == h["name"] or h["name"] == "none"
             else f" (differs from the code host — a legitimate combination, e.g. GitHub + Azure Pipelines)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
