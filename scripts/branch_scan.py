"""Read one file, or list one directory, as it stands on every local git ref.

Two branches cannot see each other's allocations: each one that opens "the next" decision (DL-07)
or "the next" spec (0034) picks the same number, and the collision only shows at merge time. The
commands that allocate those ids take `--all-branches` and use this module to look at every local
branch and remote-tracking ref first, so the new id is unused on all of them.

This is thin git I/O and nothing else. The judgement (which id is next) stays with the caller.

It NEVER fetches. An id allocation is a text edit; a tool that reached the network every time one
ran would be slow, would fail offline, and would be a surprising thing for a text edit to do. A ref
that has not been fetched is simply not seen, which is why the commands' help text tells people to
run `git fetch` themselves first. Only reads are issued here: `rev-parse`, `for-each-ref`, `show`,
`ls-tree`, `cat-file -e`, `config --get*` and `--version`, always as an argv list, never through a
shell.

Honesty rules, in the spirit of the rest of the scripts:
  - A ref that could not be read is named in `unread` with its reason. It is never dropped, and it is
    not counted in `refs_scanned`, so "checked on N branches" never covers a branch nobody looked at.
  - Not being inside a git repository is not an error: the result says `is_git: False` and carries
    nothing, and the caller carries on with what it has locally. That is the ONLY failure read as
    "not a repository": git missing, a `safe.directory` refusal or a timeout is "could not look", and
    the result then carries one `(all refs)` entry in `unread` saying why.
  - "This ref has no such path" is believed only once the ref's own tree has been proven readable. Git
    prints the same words for an absent path and for a tree it could not load (a `--filter=tree:0`
    clone's other branches), so on its own that message would count an unlooked-at branch as checked.
  - A partial clone read by a git too old to honour GIT_NO_LAZY_FETCH (before 2.45) would fetch the
    missing object from the network on a plain `git show`. Nothing is read in that case.
  - Paths are forward-slash and relative to the directory given (not to the git root), so a project
    that lives in a subdirectory of a larger repository is read at the right place.

Standalone or Workflow: the module has no `.sdlc/` dependency at all; it takes a directory and a
repo-relative path, which is what makes it usable in either mode.
"""

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

GIT_TIMEOUT_SECONDS = 60

# What git says when the path is simply not on that ref. Not an error: the ref just has no such file.
# (Pinned to English by LC_ALL=C below, so a translated git still matches.) These same words are also
# what git says when the ref's tree object cannot be read, so they are only believed after
# `_prove_tree_readable`.
_ABSENT_MARKERS = ("does not exist in", "exists on disk, but not in")

# The `unread` entry for "nothing could be read at all" (as opposed to one ref that could not be).
ALL_REFS = "(all refs)"

# GIT_NO_LAZY_FETCH is honoured from this git version on; older git lazily fetches a partial clone's
# missing objects over the network no matter what the environment says.
MIN_NO_LAZY_FETCH_VERSION = (2, 45)


class BranchScanError(Exception):
    """One git read failed. `stderr` is what git said, for a caller that wants to tell causes apart;
    `returncode` is git's exit status, None when git never produced one (a timeout, git missing)."""

    def __init__(self, message: str, stderr: str = "", returncode: int | None = None):
        super().__init__(message)
        self.stderr = stderr
        self.returncode = returncode


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
    # (git before 2.45 ignores it; `_partial_clone_blocker` keeps this module off those.)
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
        raise BranchScanError((err or out).strip() or f"git {' '.join(args)} failed", stderr=err,
                              returncode=result.returncode)
    return out, err


def is_git_repo(repo_root: Path) -> bool:
    """True inside a git work tree, False ONLY when git itself says this is not a repository.

    Anything else (git not installed, a `safe.directory` / dubious-ownership refusal, a timeout, a
    bare repository or `.git` directory) raises BranchScanError: "I could not tell" must never read
    as "there is nothing here". A directory that does not exist is not inside any repository.
    """
    if not Path(repo_root).is_dir():
        return False
    try:
        out, _ = _run_git(["rev-parse", "--is-inside-work-tree"], repo_root)
    except BranchScanError as e:
        if "not a git repository" in e.stderr:
            return False
        raise
    if out.strip() == "true":
        return True
    raise BranchScanError(f"{repo_root} is inside a git directory but not a git work tree "
                          f"(git rev-parse printed {out.strip()!r})")


def parse_git_version(text: str) -> tuple[int, int] | None:
    """`(major, minor)` from `git --version` output, or None when it has no recognisable version.

    "git version 2.43.0", "git version 2.46.0.windows.1" and "git version 2.54.0 (Apple Git-157)" all
    read; only the first two numeric components matter. Compared as integers, never as text ("2.9" is
    older than "2.45").
    """
    match = re.search(r"(\d+)\.(\d+)", text or "")
    return (int(match.group(1)), int(match.group(2))) if match else None


def _is_truthy(value: str) -> bool:
    return value.strip().lower() not in {"false", "no", "off", "0"}


def _is_partial_clone(repo_root: Path) -> bool:
    """True when git's own config marks this repository as a partial clone (missing objects it would
    normally fetch on demand): a promisor remote, or the partial-clone extension."""
    for args in (["config", "--get-regexp", r"^remote\..*\.promisor$"],
                 ["config", "--get", "extensions.partialclone"]):
        try:
            out, _ = _run_git(args, repo_root)
        except BranchScanError as e:
            if e.returncode == 1 and not e.stderr.strip():  # git config's own "no such key"
                continue
            raise
        for line in out.splitlines():
            if not line.strip():
                continue
            if args[1] == "--get":  # extensions.partialclone holds the promisor remote's name
                return True
            # `--get-regexp` prints "key value"; a bare key (no value) is git's spelling of true.
            value = line.partition(" ")[2]
            if not value.strip() or _is_truthy(value):
                return True
    return False


def _partial_clone_blocker(repo_root: Path) -> str | None:
    """Why nothing may be read from this repository, or None when reading is safe.

    A partial clone fetches a missing object from its remote when a read asks for one. Git 2.45 and
    later can be told not to (GIT_NO_LAZY_FETCH, set by `_run_git`); earlier versions cannot, so a
    partial clone on one of those is not read at all. Probed once per scan, and the version is only
    asked about when the repository is a partial clone.
    """
    if not _is_partial_clone(repo_root):
        return None
    out, _ = _run_git(["--version"], repo_root)
    version = parse_git_version(out)
    needed = ".".join(str(n) for n in MIN_NO_LAZY_FETCH_VERSION)
    if version is None:
        return (f"partial clone and the git version could not be read ({out.strip() or 'no output'}), so "
                f"it cannot be shown to be {needed} or newer, which cannot read it without a lazy "
                f"fetch; nothing was fetched — upgrade git or use a full clone")
    if version < MIN_NO_LAZY_FETCH_VERSION:
        return (f"partial clone and git {version[0]}.{version[1]} is older than {needed}, which cannot "
                f"read it without a lazy fetch; nothing was fetched — upgrade git or use a full clone")
    return None


def _preflight(repo_root: Path) -> tuple[bool, str | None]:
    """(is_git, reason nothing can be read). A reason means: report every ref as unread, read none."""
    try:
        if not is_git_repo(repo_root):
            return False, None
        return True, _partial_clone_blocker(repo_root)
    except BranchScanError as e:
        return True, str(e)


def list_refs(repo_root: Path) -> list[str]:
    """Every local branch and remote-tracking ref, sorted. A remote's `HEAD` is a symbolic ref, an
    alias for another ref in the same list, so it is left out rather than read twice; a real branch
    that merely ends in `/HEAD` (`rel/HEAD`) is not an alias and is kept. Tags are not branches."""
    out, _ = _run_git(["for-each-ref", "--format=%(refname)%00%(symref)", "refs/heads", "refs/remotes"],
                      repo_root)
    refs = []
    for line in out.splitlines():
        name, _, symref = line.partition("\0")
        if name.strip() and not symref.strip():
            refs.append(name.strip())
    return sorted(refs)


def _guard_ref(ref: str) -> None:
    # A refname never starts with a dash; one that does is an option wearing a ref's clothes.
    if not ref or ref.startswith("-"):
        raise BranchScanError(f"not a usable ref name: {ref!r}")


def _prove_tree_readable(repo_root: Path, ref: str, parent_dir: str = "") -> None:
    """Raise BranchScanError unless `ref`'s tree can be read, down to `parent_dir` when one is given.

    Git's "no such path" message is also what it prints when it could not load a tree on the way
    (a `--filter=tree:0` clone's other branches have no root tree; `--filter=tree:1` leaves the root
    and drops the directories under it). So a path is only called absent once the trees leading to it
    are proven readable: `cat-file -e` for the root, then an `ls-tree` of the path's own directory —
    `./` when the path sits at the project's top, since the project may itself live in a subdirectory
    of the git repository (`--filter=tree:1` keeps the root tree and drops exactly those) — which
    fails when any tree on the way is missing and prints nothing when the directory is simply not
    there. Only reached on the path-absent branch; a successful read costs no extra call.
    """
    try:
        _run_git(["cat-file", "-e", f"{ref}^{{tree}}"], repo_root)
        _run_git(["ls-tree", "--name-only", ref, f"{parent_dir}/" if parent_dir else "./"], repo_root)
    except BranchScanError as e:
        detail = e.stderr.strip() or str(e)
        raise BranchScanError(f"ref {ref}: its tree could not be read ({detail})", stderr=e.stderr,
                              returncode=e.returncode) from e


def read_at(repo_root: Path, ref: str, rel_path: str) -> str | None:
    """The text of `rel_path` as committed on `ref`, byte-for-byte; None when that ref has no such path.

    Any other failure (an unknown ref, a ref that is not a commit, git missing, a timeout, a ref whose
    tree cannot be read) raises BranchScanError: "this branch has no such file" and "I could not
    look" must never look alike.
    """
    _guard_ref(ref)
    try:
        # `./` makes the path relative to `repo_root` rather than to the git root.
        out, _ = _run_git(["show", f"{ref}:./{rel_path}"], repo_root)
    except BranchScanError as e:
        if any(marker in e.stderr for marker in _ABSENT_MARKERS):
            _prove_tree_readable(repo_root, ref, rel_path.rpartition("/")[0])
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
    if not names:
        # `ls-tree` walked the trees down to `rel_dir` without error, so they are readable; the root
        # check is belt and braces for a git that answers an unloadable tree with an empty listing.
        _prove_tree_readable(repo_root, ref)
        return None
    return names


def _list_refs_or_unread(repo_root: Path) -> tuple[list[str], list[dict]]:
    try:
        return list_refs(repo_root), []
    except BranchScanError as e:
        # Not "no refs": we could not list them, and a caller must be able to tell the difference.
        return [], [{"ref": ALL_REFS, "reason": str(e)}]


def scan_file(repo_root: Path, rel_path: str) -> ScanResult:
    """`rel_path` on every local ref. Outside a git repository: ScanResult(False, [], {}, []).

    When nothing can be read at all (git cannot run, git refuses the directory, a partial clone on a
    git that would fetch for it) the result is `is_git=True` with no refs scanned and one `(all refs)`
    entry in `unread`, never a clean empty result.
    """
    is_git, blocked = _preflight(repo_root)
    if not is_git:
        return ScanResult(False, [], {}, [])
    if blocked:
        return ScanResult(True, [], {}, [{"ref": ALL_REFS, "reason": blocked}])
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

    A ref that has no such directory is scanned and has no entry in the mapping. Nothing readable at
    all is reported as in `scan_file`: `(True, [], {}, [{"ref": "(all refs)", ...}])`.
    """
    is_git, blocked = _preflight(repo_root)
    if not is_git:
        return False, [], {}, []
    if blocked:
        return True, [], {}, [{"ref": ALL_REFS, "reason": blocked}]
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


def checked_summary(is_git: bool, refs_scanned: list[str], unread: list[dict]) -> str:
    """What follows "Ids checked on " in a command's text output, so every caller says the same thing.

    `3 branch(es)`; `0 branches (not a git repository)`; or, when nothing could be read at all,
    `0 branches (could not read refs: <why>)` — never a bare `0 branch(es)` that reads as "looked,
    found nothing". A per-ref failure stays in `unread` (and in the caller's warning) and does not
    change this line: the count is exactly the refs that were read.
    """
    if not is_git:
        return "0 branches (not a git repository)"
    reasons = [u["reason"] for u in unread if u["ref"] == ALL_REFS]
    if not refs_scanned and reasons:
        return f"0 branches (could not read refs: {' '.join(reasons[0].split())})"
    return f"{len(refs_scanned)} branch(es)"
