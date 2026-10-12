"""How this repo's review gates sign in to Claude — set it, check it, remove it.

The correctness-review, security-review and grader gates run on the CODE HOST, not on anybody's
machine, so they cannot borrow a local Claude session. They need a credential of their own, and
this is the one supported way to put one there.

TWO WAYS TO SIGN IN, and the difference is money rather than capability:

  subscription   A token minted from your own Claude login (`claude setup-token`). The gates run
                 against your existing plan. No per-pull-request charge.
  api-key        An Anthropic API key. Metered — every pull request that touches source costs
                 real money at the model.

Both are offered because the choice is genuinely the operator's. A team that already pays for
Claude should not be told to start paying twice, and a team billing to a project cost code often
wants the API key precisely BECAUSE it is metered and attributable.

WHAT THIS DELIBERATELY DOES NOT DO — the whole reason it is one script rather than a README step:

  It never writes the credential to disk. Not to a config file, not to a cache, not to a
  temporary file. It reads it once from standard input, hands it to the code host, and lets it
  go. The code host already stores it encrypted; a second copy on a laptop is a second thing
  that can leak, and the laptop is the one more likely to be lost.

  It never prints it, and never puts it in a command line. A value passed as an argument is
  visible to anything that can list processes on the machine. This pipes it through standard
  input instead — which is also why `status` reports only WHETHER a credential exists, never
  any part of it.

  It refuses to guess. A token that does not look like what it claims to be is rejected before
  anything is sent, because a credential set wrong fails at the worst possible moment: on
  somebody else's pull request, as a gate that was supposed to be protecting them.

Standalone or Workflow (CLAUDE.md design rule):
  - Standalone: gate_auth.py --repo <path> status
  - Workflow:   gate_auth.py --state .sdlc/state.yaml status
Exit 0 on success; 1 when the credential could not be set or read. `status` always exits 0 —
"not configured" is an answer, not a failure.

CODE HOST (code-host providers). On GitHub everything above is as it always was — repository
secrets through `gh`, byte-identical. On Azure DevOps the pipelines take their secrets from
VARIABLE GROUPS (`- group: NAME` in .azuredevops/pipelines/*.yml), so `status` reads the variable
names in the groups the pipelines reference (`ado_import.secret_names`). `set` and `clear` are
NOT implemented for Azure DevOps (D-OWNER-6): they refuse with `kind: unsupported_host` and print
the exact `az pipelines variable-group variable …` command to run by hand — WITHOUT a value on
it, because az prompts for a secret's value on standard input when `--value` is omitted, which
is the same "never on a command line" rule this script keeps for `gh`. Chosen by the origin
remote; `--host` / `SHEPHERD_CODE_HOST` (the pre-2.0 `SDLC_CODE_HOST` is still read) /
`.sdlc/code-host.yaml` override it.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import code_host  # noqa: E402

# The secret names the shipped pipelines read. Changing either means changing the workflows in
# harness/workflows/ to match — they are one decision, not two.
SUBSCRIPTION_SECRET = "CLAUDE_CODE_OAUTH_TOKEN"
API_KEY_SECRET = "ANTHROPIC_API_KEY"

MODES = {
    "subscription": {
        "secret": SUBSCRIPTION_SECRET,
        "label": "your Claude subscription",
        "cost": "no per-pull-request charge — the gates run against your existing plan",
        "how": "Run `claude setup-token` on your own machine and paste the token it prints.",
    },
    "api-key": {
        "secret": API_KEY_SECRET,
        "label": "an Anthropic API key",
        "cost": "METERED — every pull request that touches source costs real money at the model",
        "how": "Create a key at https://console.anthropic.com/settings/keys and paste it.",
    },
}

# Deliberately loose. These reject a value that is obviously the WRONG KIND of thing — a
# pasted URL, an empty line, a whole JSON blob — and nothing more. A stricter pattern would
# start rejecting valid credentials the day either format changes, which is a worse failure
# than accepting one the code host will reject anyway: this one is silent and only shows up
# as a broken gate on somebody else's pull request.
API_KEY_RE = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{16,}$")
OAUTH_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-.]{20,}$")


class GateAuthError(Exception):
    def __init__(self, message: str, kind: str = "other"):
        super().__init__(message)
        self.kind = kind


def _gh(args: list[str], repo: str | None = None, stdin: str | None = None) -> subprocess.CompletedProcess:
    """One place the code host is called, so redaction and failure handling have one home."""
    cmd = ["gh", *args]
    if repo:
        cmd += ["--repo", repo]
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, check=False)


def remote_slug(repo_root: Path) -> str | None:
    """`owner/name` for this checkout's origin, or None when it has no code host.

    Read from git rather than taken as an argument: a credential set on the wrong repository is
    a credential leaked to whoever owns that one.
    """
    result = subprocess.run(
        ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
        capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    match = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    return match.group(1) if match else None


# ── code host (code-host providers) ─────────────────────────────────────────────────────────

def detect_host(repo_root: Path, override: str | None = None) -> code_host.Detection:
    """Which code host, with `code_host.detect_host`'s precedence (flag → env → .sdlc/code-host.yaml
    → origin remote → manifest tie-breaker → none) — but fed THIS module's own origin read.

    Why a twin and not the call: this module's tests, and the argv golden that proves the GitHub
    path unchanged, stand in for `subprocess.run` with a double that accepts exactly the arguments
    `_gh` and `remote_slug` pass. `code_host.origin_url` passes `encoding`/`timeout` too, which that
    double rejects — and rewriting those tests is what "no existing test file is modified" forbids.
    A test pins this against `code_host.detect_host` so the two cannot drift."""
    if override is not None:
        if override not in code_host.HOSTS:
            raise ValueError(f"--host must be one of {', '.join(code_host.HOSTS)} (got {override!r})")
        return code_host.Detection(override, "flag", code_host.parse_remote(_origin_url(repo_root)),
                                   f"--host {override}")
    env_name, env_value = code_host.code_host_env()
    url = _origin_url(repo_root)
    remote = code_host.parse_remote(url)
    notes: list[str] = []
    if env_value:
        if env_value in code_host.HOSTS:
            return code_host.Detection(env_value, "env", remote, f"{env_name}={env_value}")
        notes.append(f"{env_name}={env_value!r} ignored: not one of {', '.join(code_host.HOSTS)}")
    settings, file_error = code_host.read_code_host_file(repo_root)
    if settings:
        return code_host.Detection(settings["host"], "file", remote or code_host._remote_from_file(settings),
                                   f"{code_host.CODE_HOST_FILE} host: {settings['host']}")
    if file_error:
        notes.append(file_error)
    if remote is not None:
        return code_host.Detection(remote.host, "remote", remote, "; ".join([f"from origin {url}", *notes]))
    notes.insert(0, "unrecognised origin remote" if url else "no origin remote")
    if code_host.installed_ci_platform(repo_root) == "azure-devops":
        return code_host.Detection("azure-devops", "manifest", None,
                                   "; ".join([*notes, "harness manifest names cicd/azure-devops"]))
    return code_host.Detection("none", "default", None, "; ".join(notes))


def _origin_url(repo_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
        capture_output=True, text=True, check=False)
    return (result.stdout.strip() or None) if result.returncode == 0 else None


def host_json(detection: code_host.Detection) -> dict:
    """The top-level `host` block for --json. Azure DevOps is probed (local reads); GitHub is NOT —
    `gh auth status` is a call the GitHub path never made, and that path is pinned byte-identical —
    so there `cli_state: unknown` means exactly "not probed"."""
    return code_host.host_block(detection, probe=(detection.host == "azure-devops"))


def _ado_status(repo_root: Path, detection: code_host.Detection) -> dict:
    """`status` on Azure DevOps: the variable names in the groups the pipelines reference.

    Tri-state on purpose. `gates_can_sign_in` is True/False only when the groups were READ;
    when they could not be (no az, no extension, signed out, no parsable remote) it is None and
    `checked` is False — "could not look" is never reported as "nothing there", because the
    action that fixes each is different and the wrong one sends somebody to reissue a key
    they already have."""
    import ado_import
    slug = detection.remote.slug if detection.remote else None
    groups = sorted(ado_import.referenced_variable_groups(repo_root))
    try:
        names = set(ado_import.secret_names(repo_root))
    except ado_import.AdoImportError as e:
        return {"ok": True, "repo": slug, "configured": [], "gates_can_sign_in": None, "checked": False,
                "variable_groups": groups,
                "detail": f"Variable groups could not be read, so whether the gates can sign in is "
                          f"unknown: {e}"}
    configured = [m for m, spec in MODES.items() if spec["secret"] in names]
    if len(configured) == 2:
        detail = ("Both are set. The gates use the subscription token, so the API key is not "
                  "being charged — but it is also not what is signing in.")
    elif not groups:
        detail = ("No pipeline under .azuredevops/pipelines/ references a variable group yet, so "
                  "every variable group in the project was read.")
    else:
        detail = ""
    return {"ok": True, "repo": slug, "configured": configured, "gates_can_sign_in": bool(configured),
            "checked": True, "variable_groups": groups, "detail": detail}


def manual_command(repo_root: Path, detection: code_host.Detection, verb: str, secret: str) -> str:
    """The exact `az` command a person runs instead of `set`/`clear` on Azure DevOps. The VALUE is
    never on it: with `--value` omitted az prompts for a secret on standard input (verified from
    `az pipelines variable-group variable create --help`). The group id is a placeholder when the
    pipelines name a group by NAME only — az wants the id, and this refuses before any az call
    is made, so it does not look one up."""
    import ado_import
    groups = sorted(ado_import.referenced_variable_groups(repo_root))
    scope = []
    if detection.remote is not None and detection.remote.org_url:
        scope = ["--org", detection.remote.org_url, "--project", detection.remote.project or "<project>"]
    tail = ["--secret", "true"] if verb == "create" else ["--yes"]
    hint = f"  (group id: `az pipelines variable-group list` — the pipelines reference {', '.join(groups)})" \
        if groups else "  (group id: `az pipelines variable-group list`)"
    return " ".join(["az pipelines variable-group variable", verb, "--group-id <group-id>", "--name", secret,
                     *tail, *scope]) + "\n" + hint


def _refuse_on_ado(repo_root: Path, detection: code_host.Detection, verb: str, secret: str) -> None:
    raise GateAuthError(
        f"Setting or removing a variable-group secret on Azure DevOps is not done by this script "
        f"(the pipelines read {secret} from a variable group, not a repository secret). Run this "
        f"yourself — az will prompt for the value, so it never appears on a command line:\n"
        f"  {manual_command(repo_root, detection, verb, secret)}", "unsupported_host")


def status(repo_root: Path, host: str | None = None) -> dict:
    """Which credential, if any, this repository's gates will use. Never reports a value."""
    detection = detect_host(repo_root, host)
    if detection.host == "azure-devops":
        return _ado_status(repo_root, detection)
    slug = remote_slug(repo_root)
    if not slug:
        return {"ok": True, "repo": None, "configured": [], "gates_can_sign_in": False,
                "detail": "This checkout has no code host remote, so there is nowhere for the "
                          "gates to read a credential from."}

    result = _gh(["secret", "list", "--json", "name"], repo=slug)
    if result.returncode != 0:
        return {"ok": True, "repo": slug, "configured": [], "gates_can_sign_in": False,
                "detail": _gh_failure_detail(result)}

    try:
        names = {entry["name"] for entry in json.loads(result.stdout or "[]")}
    except (ValueError, KeyError, TypeError):
        names = set()

    configured = [m for m, spec in MODES.items() if spec["secret"] in names]
    return {
        "ok": True,
        "repo": slug,
        "configured": configured,
        "gates_can_sign_in": bool(configured),
        # Both set is not an error, but it IS worth saying: the pipelines prefer the
        # subscription token, so an API key sitting beside it is being billed for nothing —
        # or, worse, is the one somebody THINKS is in use.
        "detail": ("Both are set. The gates use the subscription token, so the API key is not "
                   "being charged — but it is also not what is signing in."
                   if len(configured) == 2 else ""),
    }


def _gh_failure_detail(result: subprocess.CompletedProcess) -> str:
    err = (result.stderr or "").strip()
    if "not logged" in err.lower() or "authentication" in err.lower():
        return "Not signed in to the code host — run `gh auth login` first."
    if "not found" in err.lower() or "404" in err:
        return ("The repository was not found, or this account cannot see its settings. "
                "Setting a secret needs admin on the repository.")
    return err or "The code host did not say why."


def validate(mode: str, credential: str) -> str:
    """The credential, stripped — or a refusal naming what looks wrong. Never echoes the value."""
    if mode not in MODES:
        raise GateAuthError(f"'{mode}' is not a way to sign in — expected one of "
                            f"{', '.join(sorted(MODES))}.", "unknown_mode")

    credential = (credential or "").strip()
    if not credential:
        raise GateAuthError("Nothing was supplied to set.", "empty")
    if "\n" in credential or "\r" in credential:
        raise GateAuthError(
            "That looks like more than one line. Paste only the credential itself — a whole "
            "block of output usually means the surrounding text came with it.", "multiline")

    pattern = API_KEY_RE if mode == "api-key" else OAUTH_TOKEN_RE
    if not pattern.match(credential):
        # Says what SHAPE was expected, never what was received — echoing back a mistyped
        # secret is how it ends up in a terminal history or a screenshot.
        expected = ("an Anthropic API key, which begins `sk-ant-`"
                    if mode == "api-key"
                    else "a token from `claude setup-token`")
        raise GateAuthError(
            f"That does not look like {expected}. Nothing was sent. "
            f"{MODES[mode]['how']}", "bad_shape")
    return credential


def set_credential(repo_root: Path, mode: str, credential: str, host: str | None = None) -> dict:
    """Put the credential on the code host. It is never written anywhere on this machine."""
    credential = validate(mode, credential)

    detection = detect_host(repo_root, host)
    if detection.host == "azure-devops":
        _refuse_on_ado(repo_root, detection, "create", MODES[mode]["secret"])

    slug = remote_slug(repo_root)
    if not slug:
        raise GateAuthError(
            "This checkout has no code host remote, so there is nowhere to put a credential.",
            "no_remote")

    secret = MODES[mode]["secret"]
    # Through stdin, never as an argument: an argument is visible to anything that can list
    # processes, which on a shared or managed machine is a real audience.
    result = _gh(["secret", "set", secret], repo=slug, stdin=credential)
    if result.returncode != 0:
        raise GateAuthError(
            f"The credential was not set: {_gh_failure_detail(result)}", "not_set")

    # Read back rather than trusting the write. This is the one call whose failure is silent
    # and late — a gate that cannot sign in fails on somebody else's pull request, not here.
    after = status(repo_root)
    if mode not in after["configured"]:
        raise GateAuthError(
            f"The code host accepted the change but {secret} is not listed on the repository. "
            f"Check that this account has admin rights before relying on the gates.",
            "not_confirmed")

    result = {"ok": True, "repo": slug, "mode": mode, "secret": secret,
              "cost": MODES[mode]["cost"],
              "message": f"The review gates will sign in with {MODES[mode]['label']}."}

    # A credential nothing reads is the silent no-op this whole harness exists to prevent, so
    # it is said out loud at the moment of setting rather than discovered on a pull request.
    # The shipped gates currently pass only the subscription token, matching the configuration
    # that demonstrably works; until one reads the API key, choosing that mode sets a secret no
    # gate consults. Remove this when a pipeline reads it AND that has been proven on a real
    # pull request — not when it merely looks like it should.
    if mode == "api-key" and not _any_pipeline_reads(secret):
        result["warning"] = (
            f"No shipped gate currently reads {secret}, so this on its own will not let them "
            f"sign in. Use `set subscription` unless you have added the api_key input yourself.")
        result["message"] = f"{secret} is set — but see the warning."
    return result


def _any_pipeline_reads(secret: str) -> bool:
    """Does any shipped pipeline actually consult this secret? Best-effort and fail-safe: an
    unreadable payload reports True, so this never invents a warning it cannot substantiate."""
    workflows = Path(__file__).resolve().parent.parent / "harness" / "workflows"
    if not workflows.is_dir():
        return True
    try:
        return any(f"secrets.{secret}" in p.read_text(encoding="utf-8", errors="replace")
                   for p in workflows.glob("*.yml"))
    except OSError:
        return True


def clear_credential(repo_root: Path, mode: str, host: str | None = None) -> dict:
    if mode not in MODES:
        raise GateAuthError(f"'{mode}' is not a way to sign in.", "unknown_mode")
    detection = detect_host(repo_root, host)
    if detection.host == "azure-devops":
        _refuse_on_ado(repo_root, detection, "delete", MODES[mode]["secret"])
    slug = remote_slug(repo_root)
    if not slug:
        raise GateAuthError("This checkout has no code host remote.", "no_remote")

    secret = MODES[mode]["secret"]
    result = _gh(["secret", "delete", secret], repo=slug)
    if result.returncode != 0:
        raise GateAuthError(f"{secret} was not removed: {_gh_failure_detail(result)}", "not_set")

    remaining = status(repo_root)
    return {"ok": True, "repo": slug, "mode": mode, "secret": secret,
            "gates_can_sign_in": remaining["gates_can_sign_in"],
            "message": (f"{secret} removed. "
                        + ("Another credential is still set, so the gates can still sign in."
                           if remaining["gates_can_sign_in"]
                           else "The review gates can no longer sign in, and will fail closed "
                                "on the pull requests they review."))}


def format_status(result: dict) -> str:
    if not result["repo"]:
        return f"No code host remote.\n  {result['detail']}"
    lines = [f"Repository: {result['repo']}"]
    for mode, spec in MODES.items():
        mark = "set" if mode in result["configured"] else "—  "
        lines.append(f"  {mark:<4} {spec['secret']:<24} {spec['label']}")
    if result["gates_can_sign_in"] is None:
        # Azure DevOps only (GitHub never yields None, so its text is untouched): the groups
        # could not be read. Not "cannot sign in" — that would send somebody to reissue a key.
        lines.append("")
        lines.append("Whether the review gates can sign in was NOT checked.")
        lines.append(f"  {result['detail']}")
    elif not result["gates_can_sign_in"]:
        lines.append("")
        lines.append("The review gates cannot sign in. Correctness-review and security-review")
        lines.append("fail closed on the pull requests they review; the grader no-ops.")
        if result["detail"]:
            lines.append(f"  {result['detail']}")
    elif result["detail"]:
        lines.append("")
        lines.append(f"  {result['detail']}")
    return "\n".join(lines)


def resolve_repo_root(args) -> Path:
    if getattr(args, "state", None):
        return Path(args.state).resolve().parent.parent
    return Path(getattr(args, "repo", None) or ".").resolve()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="How this repo's review gates sign in to Claude (the credential is never "
                    "written to this machine)")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--state", help="Path to .sdlc/state.yaml (workflow mode)")
    src.add_argument("--repo", help="Repo root (standalone; default cwd)")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    parser.add_argument("--host", choices=code_host.HOSTS, default=None,
                        help="Code host (default: detected from origin). On azure-devops `status` reads "
                             "variable groups; `set`/`clear` print the manual az command instead")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Which credential the gates will use (never shows a value)")

    setter = sub.add_parser(
        "set", help="Set the credential, read from STANDARD INPUT so it never appears in a "
                    "command line or a shell history")
    setter.add_argument("mode", choices=sorted(MODES),
                        help="subscription = a token from `claude setup-token` (no per-PR cost); "
                             "api-key = an Anthropic API key (metered)")

    clearer = sub.add_parser("clear", help="Remove a credential from the repository")
    clearer.add_argument("mode", choices=sorted(MODES))

    args = parser.parse_args()
    repo_root = resolve_repo_root(args)
    detection = detect_host(repo_root, args.host)
    host = detection.host if args.host else None  # None → the functions detect for themselves, as before

    try:
        if args.command == "status":
            result = status(repo_root, host)
            if args.json:
                result["host"] = host_json(detection)
            print(json.dumps(result, indent=2) if args.json else format_status(result))
            if not args.json and detection.host == "azure-devops":
                print(f"\nCode host: azure-devops (from {detection.source})")
            return 0
        if args.command == "set":
            if sys.stdin.isatty():
                print(f"Paste {MODES[args.mode]['label']} and press Enter.\n"
                      f"  {MODES[args.mode]['how']}", file=sys.stderr)
            result = set_credential(repo_root, args.mode, sys.stdin.read(), host)
        else:
            result = clear_credential(repo_root, args.mode, host)
    except GateAuthError as e:
        if args.json:
            print(json.dumps({"ok": False, "refusal": {"kind": e.kind, "message": str(e)},
                              "host": host_json(detection)}))
        else:
            print(f"Refused: {e}", file=sys.stderr)
        return 1

    if args.json:
        result["host"] = host_json(detection)
    print(json.dumps(result, indent=2) if args.json else result["message"])
    if not args.json:
        if result.get("cost"):
            print(f"  Cost: {result['cost']}")
        if result.get("warning"):
            print(f"  WARNING: {result['warning']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
