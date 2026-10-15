"""Read one file, or list one directory, as it stands on every local git ref.

Two branches cannot see each other's allocations: each one that opens "the next" decision (DL-07)
or "the next" spec (0034) picks the same number, and the collision only shows at merge time. The
commands that allocate those ids take `--all-branches` and use this module to look at every local
branch and remote-tracking ref first, so the new id is unused on all of them.

This is thin git I/O and nothing else. The judgement (which id is next) stays with the caller.

It NEVER fetches. An id allocation is a text edit; a tool that reached the network every time one
ran would be slow, would fail offline, and would be a surprising thing for a text edit to do. A ref
that has not been fetched is simply not seen, which is why the commands' help text tells people to
run `git fetch` themselves first. Only reads are issued here: `rev-parse`, `for-each-ref`, `show`
and `ls-tree`, always as an argv list, never through a shell.

Honesty rules, in the spirit of the rest of the scripts:
  - A ref that could not be read is named in `unread` with its reason. It is never dropped, and it is
    not counted in `refs_scanned`, so "checked on N branches" never covers a branch nobody looked at.
  - Not being inside a git repository is not an error: the result says `is_git: False` and carries
    nothing, and the caller carries on with what it has locally.
  - Paths are forward-slash and relative to the directory given (not to the git root), so a project
    that lives in a subdirectory of a larger repository is read at the right place.

Standalone or Workflow: the module has no `.sdlc/` dependency at all; it takes a directory and a
repo-relative path, which is what makes it usable in either mode.
"""

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

GIT_TIMEOUT_SECONDS = 60

# What git says when the path is simply not on that ref. Not an error: the ref just has no such file.
# (Pinned to English by LC_ALL=C below, so a translated git still matches.)
_ABSENT_MARKERS = ("does not exist in", "exists on disk, but not in")


class BranchScanError(Exception):
    """One git read failed. `stderr` is what git said, for a caller that wants to tell causes apart."""

    def __init__(self, message: str, stderr: str = ""):
        super().__init__(message)
        self.stderr = stderr


@dataclass
class ScanResult:
    is_git: bool
    refs_scanned: list[str] = field(default_factory=list)   # sorted refnames read successfully
    texts: dict[str, str] = field(default_factory=dict)     # ref -> file text, only where the path exists
    unread: list[dict] = field(default_factory=list)        # [{"ref": str, "reason": str}], sorted by ref


def _run_git(args: list[str], cwd) -> tuple[str, str]:
    """(stdout, stderr) of one git command; raises BranchScanError on a nonzero exit, a timeout, or
    git not being runnable at all. Output is decoded here rather than by `text=True`, which would
    translate CRLF to LF and hand back a file that is not the file on the ref."""
    # LC_ALL/LANGUAGE pin git's messages to English so the absent-path check below matches.
    # GIT_NO_LAZY_FETCH stops a partial clone from fetching a missing blob from its remote just
    # because a read asked for it: the object is then reported unreadable, which is the honest answer.
    env = {**os.environ, "LC_ALL": "C", "LANGUAGE": "C", "GIT_NO_LAZY_FETCH": "1"}
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=GIT_TIMEOUT_SECONDS,
                                env=env)
    except subprocess.TimeoutExpired as e:
        raise BranchScanError(f"git {' '.join(args)} timed out") from e
    except OSError as e:  # git not installed, or `cwd` is not a directory
        raise BranchScanError(f"git {' '.join(args)} could not run: {e}") from e
    out = result.stdout.decode("utf-8", errors="replace")
    err = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        raise BranchScanError((err or out).strip() or f"git {' '.join(args)} failed", stderr=err)
    return out, err


def is_git_repo(repo_root: Path) -> bool:
    """True only when `repo_root` is inside a git work tree; False on any failure, git missing included."""
    try:
        out, _ = _run_git(["rev-parse", "--is-inside-work-tree"], repo_root)
    except BranchScanError:
        return False
    return out.strip() == "true"


def list_refs(repo_root: Path) -> list[str]:
    """Every local branch and remote-tracking ref, sorted. A remote's `HEAD` is an alias for another
    ref in the same list, so it is left out rather than read twice. Tags are not branches."""
    out, _ = _run_git(["for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes"], repo_root)
    refs = [line.strip() for line in out.splitlines() if line.strip()]
    return sorted(r for r in refs if not r.endswith("/HEAD"))


def _guard_ref(ref: str) -> None:
    # A refname never starts with a dash; one that does is an option wearing a ref's clothes.
    if not ref or ref.startswith("-"):
        raise BranchScanError(f"not a usable ref name: {ref!r}")


def read_at(repo_root: Path, ref: str, rel_path: str) -> str | None:
    """The text of `rel_path` as committed on `ref`, byte-for-byte; None when that ref has no such path.

    Any other failure (an unknown ref, a ref that is not a commit, git missing, a timeout) raises
    BranchScanError: "this branch has no such file" and "I could not look" must never look alike.
    """
    _guard_ref(ref)
    try:
        # `./` makes the path relative to `repo_root` rather than to the git root.
        out, _ = _run_git(["show", f"{ref}:./{rel_path}"], repo_root)
    except BranchScanError as e:
        if any(marker in e.stderr for marker in _ABSENT_MARKERS):
            return None
        raise
    return out


def list_dir_at(repo_root: Path, ref: str, rel_dir: str) -> list[str] | None:
    """Basenames of the entries directly inside `rel_dir` on `ref`; None when the directory is absent.

    A file with the directory's name is not a directory, and the trailing slash is what tells git so.
    """
    _guard_ref(ref)
    out, _ = _run_git(["ls-tree", "-z", "--name-only", ref, f"{rel_dir.rstrip('/')}/"], repo_root)
    names = [entry.rsplit("/", 1)[-1] for entry in out.split("\0") if entry]
    return names or None


def _list_refs_or_unread(repo_root: Path) -> tuple[list[str], list[dict]]:
    try:
        return list_refs(repo_root), []
    except BranchScanError as e:
        # Not "no refs": we could not list them, and a caller must be able to tell the difference.
        return [], [{"ref": "(all refs)", "reason": str(e)}]


def scan_file(repo_root: Path, rel_path: str) -> ScanResult:
    """`rel_path` on every local ref. Outside a git repository: ScanResult(False, [], {}, [])."""
    if not is_git_repo(repo_root):
        return ScanResult(False, [], {}, [])
    refs, unread = _list_refs_or_unread(repo_root)
    scanned: list[str] = []
    texts: dict[str, str] = {}
    for ref in refs:
        try:
            text = read_at(repo_root, ref, rel_path)
        except BranchScanError as e:
            unread.append({"ref": ref, "reason": str(e)})
            continue
        scanned.append(ref)
        if text is not None:
            texts[ref] = text
    unread.sort(key=lambda u: u["ref"])
    return ScanResult(True, scanned, texts, unread)


def scan_dir(repo_root: Path, rel_dir: str) -> tuple[bool, list[str], dict[str, list[str]], list[dict]]:
    """`rel_dir`'s entries on every local ref: (is_git, refs_scanned, ref -> names, unread).

    A ref that has no such directory is scanned and has no entry in the mapping.
    """
    if not is_git_repo(repo_root):
        return False, [], {}, []
    refs, unread = _list_refs_or_unread(repo_root)
    scanned: list[str] = []
    names: dict[str, list[str]] = {}
    for ref in refs:
        try:
            listing = list_dir_at(repo_root, ref, rel_dir)
        except BranchScanError as e:
            unread.append({"ref": ref, "reason": str(e)})
            continue
        scanned.append(ref)
        if listing is not None:
            names[ref] = listing
    unread.sort(key=lambda u: u["ref"])
    return True, scanned, names, unread
