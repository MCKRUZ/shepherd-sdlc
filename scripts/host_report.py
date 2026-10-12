"""The top-level `host` block every host-touching `--json` carries (code-host providers, Wave 3).

`{name, source, cli, cli_state, detail}` — so a reader can see WHY a host was chosen and whether
its CLI answered. Two rules from the honesty table (docs/proposals/code-host-providers.md §8):

  * `cli_state` here is read from the OUTCOME of the call the script just made, never from a
    separate probe: a script that already asked the host does not spawn `gh auth status` or
    `az account show` a second time to say so (and the test suite, which never runs either CLI,
    would have no way to intercept it). The call went through → `available`; it failed → the
    failure text says which of not_installed / extension_missing / signed_out it was, else
    `unknown` — never a false "no".
  * "Unavailable" rides THIS block. It is never a fourth check state in connection_report and
    never `code_host_available: true` with an empty board in spec_status.

`describe_source` is the phrase the text footers use ("Code host: azure-devops (from origin)").
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import code_host  # noqa: E402

SOURCE_PHRASE = {
    "flag": "from --host", "env": f"from {code_host.CODE_HOST_ENV} or {code_host.LEGACY_CODE_HOST_ENV}", "file": f"from {code_host.CODE_HOST_FILE}",
    "remote": "from origin", "manifest": "from the harness manifest", "default": "by default",
}


def detect(repo_root, override: str | None = None) -> code_host.Detection:
    """`code_host.detect_host`, but a failure INSIDE detection (an unusable git, an odd subprocess
    environment) degrades to `none` — the legacy gh path every repository had before this layer —
    with the failure named in `detail`, instead of taking a read-only report down with it. An
    invalid `--host` is still the caller's error and is raised as before."""
    try:
        return code_host.detect_host(repo_root, override)
    except ValueError:
        raise
    except Exception as e:  # noqa: BLE001 — a diagnostic must never be the thing that crashes
        return code_host.Detection("none", "default", None, f"host detection failed: {type(e).__name__}: {e}")


def describe_source(source: str) -> str:
    return SOURCE_PHRASE.get(source, f"from {source}")


def cli_state_from_error(cli: str, error: str | None) -> tuple[str, str]:
    """(cli_state, detail) read from what the CLI said when it was asked."""
    if error is None:
        return "available", f"{cli} answered"
    low = error.lower()
    if "not installed" in low or "not on path" in low:
        return "not_installed", ("the Azure CLI is not installed" if cli == "az" else "the GitHub CLI is not installed")
    if cli == "az" and "extension" in low and "azure-devops" in low:
        return "extension_missing", "run `az extension add --name azure-devops`"
    if "az login" in low or "gh auth login" in low or "not logged in" in low or "pat only" in low:
        return "signed_out", ("run `az login`" if cli == "az" else "run `gh auth login`")
    return "unknown", f"{cli} failed: {error.splitlines()[0] if error else 'no detail'}"


def host_block(detection: code_host.Detection, error: str | None = None) -> dict:
    cli = code_host.cli_for(detection.host)
    state, state_detail = cli_state_from_error(cli, error)
    detail = detection.detail if state == "available" else f"{detection.detail}; {state_detail}"
    return {"name": detection.host, "source": detection.source, "cli": cli, "cli_state": state, "detail": detail}


def footer(detection: code_host.Detection) -> str | None:
    """The text footer line, or None for GitHub AND for `none` — `none` is the legacy gh fall-through
    (code_host.cli_for), so printing it would change today's text for every repository without a
    recognised remote. Only a host that is actually different from GitHub gets a line."""
    if detection.host in ("github", "none"):
        return None
    return f"Code host: {detection.host} ({describe_source(detection.source)})"
