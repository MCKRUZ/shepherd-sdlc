"""Hand a ready spec to a developer in one step (spec 0005 — the Delegate beat's tool).

Today hand-off is four manual steps that each get skipped differently: the branch gets
named ad hoc, the spec's status goes stale, nobody is assigned, and the developer starts
without the spec in front of them. This makes it one step: branch, frontmatter, code-host
assignment, and (optionally) the Claude Code session itself.

Every refusal path (not ready, unknown developer, developer is also the checker, team at
its WIP limit, already in flight) runs BEFORE any git operation, so a refusal always leaves
the repository untouched — a half-done hand-off is worse than none. Git and GitHub are
deliberately separate: the branch/frontmatter/push happen over plain git, so a hand-off
still does its local half even with no code-host access; only the assignment step needs
the code host's CLI, and its failure is reported, not fatal.

Code host (code-host providers): the assignment step goes to `gh` on GitHub and to `az` on
Azure DevOps, chosen by the origin remote (`--host` / `SHEPHERD_CODE_HOST` (or the older
`SDLC_CODE_HOST`) / `.sdlc/code-host.yaml` ahead of it — `code_host.detect_host`). The GitHub
path is byte-identical to what it was. On
Azure DevOps there is no assignee on a pull request, so the developer is named in the
description; the checker is added as a required reviewer by roster EMAIL, and a checker with no
email is an `assignment_error` (the PR still opens — the local half is never failed over it).

Standalone or Workflow:
  - Standalone: --repo <path>
  - Workflow:   --state .sdlc/state.yaml
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cadence_plan as cp
import check_spec as cs
import code_host
import track_specs as ts
import validate_team as vt
from github_import import GitHubImportError, run_gh

BRANCH_PREFIX = "spec/"

# The no-self-check rule in ONE sentence, shared with `spec_transition.py assign` so a checker set
# ahead of the hand-off is refused in exactly the words the hand-off itself would use.
SELF_CHECK_MESSAGE = "'{developer}' is this spec's checker — a person cannot check their own build"


class HandoffError(Exception):
    """A refusal, or a local-git failure. Raised before any mutation, or the mutation
    itself failed outright — either way nothing was left half-done.

    `kind` is the same refusal as data, for a caller that must BEHAVE differently per
    refusal rather than just print it — a graphical caller offers a reason box for
    `team_at_limit` and a person-picker for `developer_is_checker`. Without it that
    caller has to pattern-match this class's English, which breaks the first time the
    wording is improved. The message stays the human-facing truth; the kind is a hint,
    and `other` is always a valid answer."""

    def __init__(self, message: str, kind: str = "other"):
        super().__init__(message)
        self.kind = kind


def run_git(args: list[str], cwd, env: dict | None = None, input_text: str | None = None) -> str:
    """`env` (e.g. GIT_INDEX_FILE) extends the current environment rather than replacing
    it, so PATH etc. still resolve. `input_text` feeds stdin, for `hash-object --stdin`."""
    full_env = {**os.environ, **env} if env else None
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60,
            env=full_env, input=input_text,
        )
    except subprocess.TimeoutExpired as e:
        raise HandoffError(f"git {' '.join(args)} timed out") from e
    if result.returncode != 0:
        raise HandoffError((result.stderr or result.stdout).strip() or f"git {' '.join(args)} failed")
    return result.stdout


def resolve_base_branch(repo_root) -> str:
    """origin's default branch, over plain git — no `gh`/API dependency, so this still
    works with no code-host access (only git+network to the remote is required)."""
    out = run_git(["ls-remote", "--symref", "origin", "HEAD"], cwd=repo_root)
    m = re.search(r"^ref:\s+refs/heads/(\S+)\s+HEAD", out, re.MULTILINE)
    if not m:
        raise HandoffError("Could not determine origin's default branch (git ls-remote --symref origin HEAD)")
    return m.group(1)


def branch_name_for(spec_id: str, spec_name: str) -> str:
    """The playbook's branch rule: spec/<id>-<name>, reusing the spec's own frontmatter
    id/name — the same pair that already names the spec file itself."""
    return f"{BRANCH_PREFIX}{spec_id}-{spec_name}"


def find_existing_handoff(repo_root, branch_name: str, spec_rel_path: str) -> str | None:
    """The developer already on file for this hand-off, or None if the branch doesn't
    exist yet. This — not the spec's status on the caller's own checkout — is the correct
    idempotency signal: the frontmatter change lands ONLY on the spec's own branch, so a
    checkout still sitting on main/master would see `status: ready` forever, long after a
    real hand-off happened. A branch existing on origin is the one fact everyone shares.
    """
    heads = run_git(["ls-remote", "--heads", "origin", branch_name], cwd=repo_root)
    if not heads.strip():
        return None
    # `--` so a branch name can never be read as a flag. It comes from the remote's own symref,
    # not from us, and `--upload-pack=` is the kind of thing that turns a name into an argument.
    run_git(["fetch", "origin", "--", branch_name], cwd=repo_root)
    content = run_git(["show", f"FETCH_HEAD:{spec_rel_path}"], cwd=repo_root)
    fm, _ = cs.parse_frontmatter(content)
    return fm.get("developer") or "(unset)"


def set_status_and_developer(text: str, developer: str) -> str:
    """Set frontmatter `status: in-flight` and `developer: "<handle>"`, touching only the
    frontmatter block (never a body line that happens to start with one of these words)."""
    if not text.startswith("---"):
        raise HandoffError("Spec has no frontmatter block")
    end = text.find("\n---", 3)
    if end == -1:
        raise HandoffError("Spec frontmatter block is not closed")

    # One field is one line. The frontmatter reader is line-based and last-key-wins, so a handle
    # carrying a line break would not be a long name — its second line would land as a separate
    # FIELD, silently rewriting whichever fields the template declares above `developer:`
    # (`risk` among them). Handles come from a roster that ships inside a repository, so this is
    # reachable by cloning one, and a risk tier quietly downgraded at hand-off time is the
    # checking ladder collapsing with nobody's name on it.
    if any(c in str(developer) for c in "\r\n"):
        raise HandoffError(
            "A developer handle cannot contain a line break — one field is one line, and a "
            "second line would be read as a different field entirely.")

    fm_block, rest = text[:end], text[end:]
    # `[^\r\n]*`, not `.*$`: `.` also matches the "\r" of a CRLF line and would leave a bare LF.
    fm_block = re.sub(r"^status:[^\r\n]*", "status: in-flight", fm_block, count=1, flags=re.MULTILINE)
    # Lambda replacements, not template strings: re.sub expands `\n`, `\1` and friends inside a
    # replacement template, so a literal backslash in a handle would become something else.
    fm_block = re.sub(r'^developer:[^\r\n]*', lambda _m: f'developer: "{developer}"', fm_block,
                      count=1, flags=re.MULTILINE)
    return fm_block + rest


def push_handoff_commit(repo_root, branch_name: str, base_branch: str,
                         spec_rel_path: str, new_text: str, commit_message: str) -> None:
    """Create the branch, write the frontmatter change, commit and push — via a throwaway
    git worktree, so the caller's own checkout (dirty or not, on any branch) is never
    touched. Cleaned up whether the push succeeds or fails."""
    run_git(["fetch", "origin", "--", base_branch], cwd=repo_root)
    with tempfile.TemporaryDirectory() as tmp:
        wt_path = Path(tmp) / "handoff-wt"
        run_git(["worktree", "add", "-b", branch_name, str(wt_path), f"origin/{base_branch}"], cwd=repo_root)
        try:
            (wt_path / spec_rel_path).write_text(new_text, encoding="utf-8")
            run_git(["add", spec_rel_path], cwd=wt_path)
            run_git(["commit", "-m", commit_message], cwd=wt_path)
            run_git(["push", "origin", branch_name], cwd=wt_path)
        finally:
            run_git(["worktree", "remove", "--force", str(wt_path)], cwd=repo_root)


def assign_on_host(repo_root, branch_name: str, base_branch: str, spec_id: str, spec_name: str,
                    developer: str, checker: str) -> str:
    """Open a draft PR for the branch and assign/request-review on it — GitHub has no
    concept of "assign"/"request review" without a PR to hang them on, and this repo's
    own convention is one spec = one branch = one PR, so opening it now (as a draft, since
    the build hasn't happened yet) is the natural place to hang both. Raises
    GitHubImportError on any `gh` failure — reused as-is; a `gh` failure here is exactly
    the same class of thing (no network, no auth, not a GitHub repo).
    """
    args = [
        "pr", "create", "--draft", "--base", base_branch, "--head", branch_name,
        "--title", f"Spec {spec_id}: {spec_name}",
        "--body", f"Hand-off for `specs/{spec_id}-{spec_name}.md`. Delegate beat — plan approval, then build.",
        "--assignee", developer.lstrip("@"),
    ]
    if checker:
        args += ["--reviewer", checker.lstrip("@")]
    return run_gh(args, cwd=str(repo_root)).strip()


# ── code host dispatch (code-host providers) ────────────────────────────────────────────────

def _host_fn(name: str, host: str):
    """The provider function for `name` on this host. Azure DevOps → `ado_import.<name>` (same
    name, same signature — `test_provider_parity.py` pins it); anything else → this module's own
    function, looked up by name AT CALL TIME so the existing `monkeypatch.setattr(h, …)` seams
    keep intercepting the GitHub path. `ado_import` is imported lazily: a GitHub checkout should
    not pay for, or be able to break on, the Azure modules."""
    if host == "azure-devops":
        import ado_import
        return getattr(ado_import, name)
    return globals()[name]


def host_json(detection) -> dict:
    """The top-level `host` block every host-touching --json carries. Azure DevOps is probed (local
    reads: the extension is present, an account is cached). GitHub is deliberately NOT probed —
    `gh auth status` would be a call the GitHub path never made before, and that path is pinned
    byte-identical — so there `cli_state: unknown` means exactly "not probed"."""
    return code_host.host_block(detection, probe=(detection.host == "azure-devops"))


def _is_email(value: str) -> bool:
    return "@" in value[1:]  # `@handle` has its only `@` first; `a@b` is a sign-in identity


def reviewer_gap(repo_root, checker: str) -> str | None:
    """Why the checker could NOT be added as a reviewer on Azure DevOps, or None when they can be.

    az names a reviewer by sign-in identity (UPN/mail); an `@handle` is a CLIError. The roster's
    optional `email` is the only honest bridge (never a guess from a display name), so a checker
    without one is reported as an assignment_error — the PR still opens, with the gap written
    into its description by the provider. Same lookup the provider does (`validate_team.email_for`),
    so the two cannot disagree."""
    if not checker or _is_email(checker):
        return None
    roster_path = Path(repo_root) / ".sdlc" / "team.yaml"
    try:
        roster = vt.load_yaml(roster_path) if roster_path.is_file() else None
    except Exception:  # a broken roster is validate_team's finding, not a reason to hide the gap
        roster = None
    if roster and vt.email_for(roster, checker):
        return None
    return (f"checker {checker} has no email in .sdlc/team.yaml; Azure DevOps needs one to add a "
            f"reviewer")


def open_command(repo_root, branch_name: str, spec_rel_path: str) -> list[str]:
    prompt = (
        f"Read {spec_rel_path} end to end, then build it to the Definition of Ready. "
        f"Start by presenting your plan — do not write anything until it is approved."
    )
    return ["claude", "--permission-mode", "plan", prompt]


def resolve_repo_root(args) -> Path:
    if args.state:
        state_path = Path(args.state)
        if not state_path.exists():
            print(f"Error: State file not found: {state_path}")
            sys.exit(1)
        return state_path.resolve().parent.parent
    return Path(args.repo).resolve()


def check_preconditions(repo_root: Path, spec_path: Path, developer: str,
                        over_limit_reason: str | None) -> dict:
    """Every refusal, in the order the hand-off applies them, and NOTHING else — no git write, no
    code-host call. Raises HandoffError for a refusal; returns the facts the mutation would use.

    One function, two callers: `handoff()` runs it and then mutates; `check_handoff()` runs it
    and stops. That is what makes a `--check` honest — it cannot say "would succeed" by a rule
    the live path does not apply, or refuse by one it does not, because there is only one list.

    `already_in_flight` is read from the spec's branch on origin (the one fact everyone shares),
    so it still needs `git ls-remote` — a read, never a write."""
    if not spec_path.exists():
        raise HandoffError(f"Spec not found: {spec_path}")
    text = spec_path.read_text(encoding="utf-8")
    fm, _ = cs.parse_frontmatter(text)
    if not fm:
        raise HandoffError("Spec has no parseable frontmatter")

    spec_id, spec_name = fm.get("spec", "????"), fm.get("name", "unnamed")
    branch_name = branch_name_for(spec_id, spec_name)
    spec_rel_path = str(spec_path.resolve().relative_to(repo_root)).replace("\\", "/")

    existing_developer = find_existing_handoff(repo_root, branch_name, spec_rel_path)
    if existing_developer is not None:
        return {"already_in_flight": True, "developer": existing_developer}

    roster_path = repo_root / ".sdlc" / "team.yaml"

    # --- Definition of Ready ---
    results = cs.check_spec_text(text, roster_path)
    must_fail = [r for r in results if not r["passed"] and r["severity"] == "MUST"]
    if must_fail:
        detail = "; ".join(r["message"] for r in must_fail)
        raise HandoffError(f"Spec is not ready ({len(must_fail)} blocking issue(s)): {detail}", "not_ready")

    # --- Developer / checker ---
    if roster_path.exists():
        roster = vt.load_yaml(roster_path)
        handles = vt.people_handles(roster)
        if developer not in handles:
            raise HandoffError(f"Developer '{developer}' is not listed in the roster ({roster_path})", "unknown_developer")

    checker = (fm.get("checker") or "").strip()
    if checker and checker == developer:
        raise HandoffError(SELF_CHECK_MESSAGE.format(developer=developer), "developer_is_checker")

    # --- Team WIP limit (spec 0003) ---
    team = (fm.get("team") or "").strip()
    limits, _cadence_errors = cp.load_limits(repo_root)
    in_flight_after = None
    if team in limits:
        specs = ts.scan_specs(repo_root / "specs")
        summary = ts.summarize(specs)
        in_flight_by_team = ts.team_in_flight_counts(summary["in_flight"])
        n = in_flight_by_team.get(team, 0)
        in_flight_after = n + 1
        limit = limits[team]["wip_limit"]
        if n + 1 > limit and not over_limit_reason:
            raise HandoffError(
                f"Team '{team}' is at its WIP limit: {n} in-flight, limit {limit} — this hand-off "
                f"would make {n + 1}. Use --over-limit \"<reason>\" to proceed anyway.",
                "team_at_limit",
            )

    return {
        "already_in_flight": False,
        "text": text,
        "spec_id": spec_id,
        "spec_name": spec_name,
        "branch": branch_name,
        "spec_rel_path": spec_rel_path,
        "developer": developer,
        "checker": checker or None,
        "team": team or None,
        # A count only where a cap exists to compare it to — "no cap set" is not "0 in flight".
        "in_flight_after": in_flight_after,
    }


def check_handoff(repo_root: Path, spec_path: Path, developer: str,
                  over_limit_reason: str | None) -> dict:
    """The dry run: what a hand-off WOULD do, or the refusal it would meet — the repository
    untouched either way. Stops before `resolve_base_branch`, so it never needs the default
    branch, never creates a worktree, never pushes. Raises HandoffError exactly as `handoff` would."""
    facts = check_preconditions(repo_root, spec_path, developer, over_limit_reason)
    if facts["already_in_flight"]:
        return {"ok": True, "already_in_flight": True, "developer": facts["developer"], "would": None}
    return {
        "ok": True,
        "already_in_flight": False,
        "would": {k: facts[k] for k in ("branch", "developer", "checker", "team", "in_flight_after")},
    }


def handoff(repo_root: Path, spec_path: Path, developer: str, over_limit_reason: str | None,
            host: str | None = None) -> dict:
    """Run every refusal check, then (if none fire) the git mutation. Returns a summary
    dict. Raises HandoffError for any refusal — the caller decides how to report it.

    `host` is the resolved code host (`github` / `azure-devops` / `none`); None detects it from
    the checkout. It decides only the assignment step — the refusals and the git half are the
    same on every host."""
    if host is None:
        host = code_host.detect_host(repo_root).host

    facts = check_preconditions(repo_root, spec_path, developer, over_limit_reason)
    if facts["already_in_flight"]:
        return {"already_in_flight": True, "developer": facts["developer"]}
    text, spec_id, spec_name = facts["text"], facts["spec_id"], facts["spec_name"]
    branch_name, spec_rel_path, checker = facts["branch"], facts["spec_rel_path"], facts["checker"] or ""

    # --- The mutation: branch, frontmatter, push ---
    base_branch = resolve_base_branch(repo_root)
    new_text = set_status_and_developer(text, developer)
    commit_message = f"chore: hand off spec {spec_id} to {developer}"
    if over_limit_reason:
        commit_message += f"\n\nOver WIP limit: {over_limit_reason}"
    push_handoff_commit(repo_root, branch_name, base_branch, spec_rel_path, new_text, commit_message)

    # --- Code-host assignment (best-effort — local half already succeeded above) ---
    # On Azure DevOps the checker is added by roster EMAIL; a checker with none is a gap the
    # provider cannot fill (D-OWNER-3). The PR still opens — "no reviewer" is a reportable
    # failure of the assignment step, not a reason to lose the local half that already landed.
    assignment_error = reviewer_gap(repo_root, checker) if host == "azure-devops" else None
    pr_url = None
    try:
        pr_url = _host_fn("assign_on_host", host)(
            repo_root, branch_name, base_branch, spec_id, spec_name, developer, checker)
    except GitHubImportError as e:  # AdoImportError is a subclass — one clause covers both CLIs
        assignment_error = str(e)

    return {
        "already_in_flight": False,
        "branch": branch_name,
        "developer": developer,
        "checker": checker or None,
        "pr_url": pr_url,
        "assignment_error": assignment_error,
        "spec_rel_path": spec_rel_path,
    }


def run_check(repo_root: Path, spec_path: Path, args, detection) -> int:
    """`--check`: print the dry run (JSON or text) and return the exit code — 0 for a hand-off
    that would go through, 1 for a refusal, with the same `kind`/`message` the live path gives."""
    import json
    try:
        result = check_handoff(repo_root, spec_path, args.developer, args.over_limit)
    except HandoffError as e:
        if args.json:
            print(json.dumps({"ok": False, "refusal": {"kind": e.kind, "message": str(e)},
                              "host": host_json(detection)}, indent=2))
        else:
            print(f"Refused: {e}")
        return 1
    if args.json:
        print(json.dumps({**result, "host": host_json(detection)}, indent=2))
        return 0
    if result["already_in_flight"]:
        print(f"Already in flight — developer: {result['developer']}. A hand-off would change nothing.")
        return 0
    would = result["would"]
    extras = [f"checker: {would['checker']}" if would["checker"] else "no checker set"]
    if would["team"]:
        extras.append(f"team {would['team']}" + (
            f", {would['in_flight_after']} in flight after" if would["in_flight_after"] is not None else ""))
    print(f"Would hand off: {would['branch']} -> {would['developer']} ({'; '.join(extras)})")
    print("  Nothing was changed. Run without --check to hand off.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Hand a ready spec to a developer")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--state", help="Path to .sdlc/state.yaml (workflow mode)")
    src.add_argument("--repo", default=".", help="Target repo root (standalone mode; default: cwd)")
    parser.add_argument("--spec", required=True, help="Path to specs/NNNN-name.md")
    parser.add_argument("--developer", required=True, help="Code-host handle, e.g. @sam-k")
    parser.add_argument("--over-limit", default=None, metavar="REASON",
                         help="Proceed even if the team is at its WIP limit; written into the commit")
    parser.add_argument("--open", action="store_true", help="Also start Claude Code on the branch")
    parser.add_argument("--check", action="store_true",
                        help="Dry run: apply every refusal and report what the hand-off WOULD do, "
                             "without a branch, a commit, a push or a code-host call")
    parser.add_argument("--json", action="store_true",
                        help="Emit the outcome (including a refusal and its kind) as JSON")
    parser.add_argument("--host", choices=code_host.HOSTS, default=None,
                        help="Code host for the assignment step (default: detected from origin; "
                             "`none` tries gh as before)")
    args = parser.parse_args()

    repo_root = resolve_repo_root(args)
    spec_path = Path(args.spec)
    detection = code_host.detect_host(repo_root, args.host)

    if args.check:
        sys.exit(run_check(repo_root, spec_path, args, detection))

    try:
        result = handoff(repo_root, spec_path, args.developer, args.over_limit, host=detection.host)
    except HandoffError as e:
        if args.json:
            import json
            print(json.dumps({"ok": False, "refusal": {"kind": e.kind, "message": str(e)},
                              "host": host_json(detection)}, indent=2))
        else:
            print(f"Refused: {e}")
        sys.exit(1)

    if args.json:
        import json
        print(json.dumps({"ok": True, **result, "host": host_json(detection)}, indent=2))
        return

    if result["already_in_flight"]:
        print(f"Already in flight — developer: {result['developer']}. Nothing changed.")
        return

    print(f"Handed off: {result['branch']} -> {result['developer']}")
    if result["pr_url"]:
        # "review requested" only when it was: on Azure DevOps the PR can open with the reviewer
        # missing (no roster email), and that gap is reported on the next line, not papered over.
        requested = result["checker"] and not result["assignment_error"]
        print(f"  PR: {result['pr_url']}" + (f" (review requested: {result['checker']})" if requested else ""))
    if result["assignment_error"]:
        print(f"  Local hand-off complete. Could not assign on the code host: {result['assignment_error']}")
        print("  Assign manually once code-host access is available.")
    if detection.host == "azure-devops":  # gh-path text (github AND the legacy `none`) stays byte-identical
        print(f"  Code host: {detection.host} (from {detection.source})")

    cmd = open_command(repo_root, result["branch"], result["spec_rel_path"])
    if args.open:
        run_git(["checkout", result["branch"]], cwd=repo_root)
        subprocess.run(cmd, cwd=repo_root)
    else:
        print(f"  Next: cd {repo_root} && git checkout {result['branch']} && " + " ".join(
            f'"{c}"' if " " in c else c for c in cmd
        ))


if __name__ == "__main__":
    main()
