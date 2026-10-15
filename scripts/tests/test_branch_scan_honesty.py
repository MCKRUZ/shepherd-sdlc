"""Fix-A — `branch_scan.py` must never turn "I could not look" into "there is nothing there".

These are the four ways the first version of the scan reported a clean result it had not earned, each
found by running it rather than reading it, each pinned here against a real repository where one can
be built and by a recorded, scripted `git` where it cannot (a `safe.directory` refusal needs a second
user; a git older than 2.45 is not on this machine):

  1. a ref whose TREE cannot be read (a `--filter=tree:0` clone's other branches) was counted as
     "scanned, no such file", because git prints the same words for that and for an absent path
  2. `is_git_repo` answered False for every failure, so git missing or refusing the directory printed
     "(not a git repository)" with nothing in `unread`
  3. a real branch named `rel/HEAD` was dropped by a `/HEAD` suffix test, in neither list
  4. a partial clone read by a git older than 2.45 would fetch the missing object from the network

Every test that runs the module in-process records the git commands it issued (`GitSpy`), so "it
never fetches" is checked on every one of those paths, not just the happy one.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from golden_support import SCRIPTS_DIR  # noqa: E402

import branch_scan as bs  # noqa: E402

REAL_RUN = subprocess.run   # captured before any test patches `subprocess.run`
TD_SCRIPT = SCRIPTS_DIR / "track_decisions.py"
LOG = ".sdlc/decision-log.md"

HEADER = ("| id    | decision                | owner | opened     | due (2 business days) | status |\n"
          "|-------|-------------------------|-------|------------|-----------------------|--------|\n")


def _git_version() -> tuple[int, int] | None:
    try:
        return bs.parse_git_version(REAL_RUN(["git", "--version"], capture_output=True, text=True).stdout)
    except OSError:
        return None


# The real-clone tests need a git that honours GIT_NO_LAZY_FETCH, or the module (correctly) refuses to
# read a partial clone at all and there is nothing left to observe.
modern_git = pytest.mark.skipif(
    _git_version() is None or _git_version() < bs.MIN_NO_LAZY_FETCH_VERSION,
    reason=f"needs git {'.'.join(map(str, bs.MIN_NO_LAZY_FETCH_VERSION))} or newer")


# --- helpers ---

def log_text(*ids: int) -> str:
    rows = "".join(f"| DL-{n:02d} | Decision number {n} | Jane | 2026-07-07 | 2026-07-09 | open |\n"
                   for n in ids)
    return "# Decision Log\n\n" + HEADER + rows + "\n*Add one row per decision.*\n"


def git(repo: Path, *args: str) -> str:
    done = REAL_RUN(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8")
    return done.stdout.strip()


def commit(repo: Path, files: dict[str, str], message: str = "c") -> None:
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def run_td(args, cwd: Path, env=None):
    return REAL_RUN([sys.executable, str(TD_SCRIPT), *args], capture_output=True, text=True,
                    encoding="utf-8", cwd=str(cwd),
                    env=env or {**os.environ, "PYTHONIOENCODING": "utf-8"})


def open_args(*extra: str):
    return ["open", "--repo", ".", "--decision", "x", "--owner", "@priya-n", *extra]


def result(code: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, stdout.encode(), stderr.encode())


class GitSpy:
    """Stands in for `subprocess.run` inside branch_scan: records every command, runs the real git
    unless a rule answers first, and can fake `git --version` or make git vanish."""

    FORBIDDEN = {"fetch", "pull", "push", "clone", "ls-remote", "remote"}

    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch
        self.calls: list[list[str]] = []
        self.shells: list = []
        self.envs: list[dict] = []
        self.version: str | None = None          # fake `git --version` text, e.g. "2.43.0"
        self.missing = False                     # git is not on PATH
        self.rules: list = []                    # callables(argv) -> CompletedProcess | None
        self.started = False

    def start(self) -> "GitSpy":
        self._monkeypatch.setattr(bs.subprocess, "run", self)
        self.started = True
        return self

    def __call__(self, argv, *a, **k):
        argv = list(argv)
        self.calls.append(argv)
        self.shells.append(k.get("shell"))
        self.envs.append(k.get("env") or {})
        if self.missing:
            raise FileNotFoundError(2, "No such file or directory", "git")
        for rule in self.rules:
            fake = rule(argv)
            if fake is not None:
                return fake
        if self.version is not None and argv == ["git", "--version"]:
            return result(0, f"git version {self.version}\n")
        return REAL_RUN(argv, *a, **k)

    def commands(self) -> list[str]:
        """The git subcommand of each call, in order (`--version` for a version probe)."""
        return [argv[1] for argv in self.calls if len(argv) > 1]

    def assert_never_fetches(self) -> None:
        assert self.calls, "the spy saw nothing: the test proves nothing"
        for argv, shell, env in zip(self.calls, self.shells, self.envs):
            assert argv[0] == "git"
            assert not (self.FORBIDDEN & set(argv)), argv
            assert not shell, argv
            assert env.get("GIT_NO_LAZY_FETCH") == "1", argv


@pytest.fixture
def spy(monkeypatch):
    s = GitSpy(monkeypatch)
    yield s
    if s.started:
        s.assert_never_fetches()


@pytest.fixture
def repo(tmp_path) -> Path:
    """master holds DL-01..DL-03 and spec 0001; `feature` holds DL-07 and spec 0005; back on master."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    git(root, "config", "uploadpack.allowfilter", "true")
    commit(root, {LOG: log_text(1, 2, 3), "specs/0001-a.md": "a\n"}, "master")
    git(root, "checkout", "-q", "-b", "feature")
    commit(root, {LOG: log_text(1, 2, 3, 7), "specs/0005-x.md": "x\n"}, "feature")
    git(root, "checkout", "-q", "master")
    return root


def partial_clone(tmp_path: Path, src: Path, filter_spec: str) -> Path:
    """A real partial clone of `src`; skips the test when this git/server cannot make one. This is the
    TEST building its fixture over a local path — the module under test never fetches or clones."""
    dst = tmp_path / ("clone-" + filter_spec.replace(":", "-"))
    proc = REAL_RUN(["git", "-c", "uploadpack.allowfilter=true", "clone", "-q", f"--filter={filter_spec}",
                     "--no-local", src.as_uri(), str(dst)], capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"cannot make a --filter={filter_spec} clone here: {proc.stderr.strip()}")
    # The point of the fixture: the feature branch's tree really is not in the object store. Probed
    # with GIT_NO_LAZY_FETCH so the probe cannot fetch it either.
    probe = REAL_RUN(["git", "cat-file", "-e", "refs/remotes/origin/feature^{tree}"], cwd=dst,
                     capture_output=True, text=True, env={**os.environ, "GIT_NO_LAZY_FETCH": "1"})
    probe_subtree = REAL_RUN(["git", "ls-tree", "--name-only", "refs/remotes/origin/feature", "specs/"],
                             cwd=dst, capture_output=True, text=True,
                             env={**os.environ, "GIT_NO_LAZY_FETCH": "1"})
    if probe.returncode == 0 and probe_subtree.returncode == 0:
        pytest.skip(f"--filter={filter_spec} did not leave the feature tree unreadable on this git")
    return dst


# ===================================================================================================
# 1. a ref whose tree cannot be read is not "absent"
# ===================================================================================================

@modern_git
def test_a_treeless_clones_unloadable_branch_is_unread_not_scanned(tmp_path, repo):
    dst = partial_clone(tmp_path, repo, "tree:0")
    scan = bs.scan_file(dst, LOG)
    assert scan.is_git is True
    ref = "refs/remotes/origin/feature"
    assert [u["ref"] for u in scan.unread] == [ref]
    assert "tree could not be read" in scan.unread[0]["reason"]
    assert ref not in scan.refs_scanned                  # nobody looked at it, so it is not "checked"
    assert ref not in scan.texts
    assert "refs/heads/master" in scan.refs_scanned
    assert scan.texts["refs/heads/master"] == log_text(1, 2, 3)


@modern_git
def test_a_tree_1_clones_missing_subtree_is_unread_not_scanned(tmp_path, repo):
    """The root tree is there, the `.sdlc/` tree under it is not: proving only the root is readable
    would still call the log absent. The parent directory is proven too."""
    dst = partial_clone(tmp_path, repo, "tree:1")
    scan = bs.scan_file(dst, LOG)
    ref = "refs/remotes/origin/feature"
    assert [u["ref"] for u in scan.unread] == [ref]
    assert "tree could not be read" in scan.unread[0]["reason"]
    assert ref not in scan.refs_scanned
    assert "refs/heads/master" in scan.refs_scanned


@modern_git
def test_scan_dir_also_names_the_unloadable_branch(tmp_path, repo):
    dst = partial_clone(tmp_path, repo, "tree:0")
    is_git, refs, names, unread = bs.scan_dir(dst, "specs")
    assert is_git is True
    assert [u["ref"] for u in unread] == ["refs/remotes/origin/feature"]
    assert "refs/remotes/origin/feature" not in refs
    assert names["refs/heads/master"] == ["0001-a.md"]


@modern_git
def test_open_all_branches_on_a_treeless_clone_names_the_branch_and_does_not_count_it(tmp_path, repo):
    dst = partial_clone(tmp_path, repo, "tree:0")
    proc = run_td(open_args("--json", "--all-branches"), dst)
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(proc.stdout)
    assert [u["ref"] for u in doc["unread"]] == ["refs/remotes/origin/feature"]
    assert "tree could not be read" in doc["unread"][0]["reason"]
    assert "refs/remotes/origin/feature" not in doc["refs_scanned"]
    assert doc["refs_scanned"] == ["refs/heads/master", "refs/remotes/origin/master"]
    assert doc["id"] == "DL-04"    # feature's DL-07 could not be seen, and the output says so


@modern_git
def test_the_text_form_excludes_the_unloadable_branch_from_its_count_and_warns_on_stderr(tmp_path, repo):
    dst = partial_clone(tmp_path, repo, "tree:0")
    proc = run_td(open_args("--all-branches"), dst)
    assert proc.returncode == 0, proc.stderr
    assert "  Ids checked on 2 branch(es)" in proc.stdout.splitlines()     # master + origin/master only
    assert "Warning:" in proc.stderr and "refs/remotes/origin/feature" in proc.stderr
    assert "refs/remotes/origin/feature" not in proc.stdout


def test_a_ref_whose_tree_git_cannot_load_is_unread_when_git_says_path_absent(repo, spy):
    """The same outcome without needing a partial clone: git's two answers for `feature` are scripted
    (the path-absent wording from `show`, `bad object` from `cat-file`), everything else is real."""
    def rule(argv):
        if argv[1:2] == ["show"] and argv[2].startswith("refs/heads/feature:"):
            return result(128, stderr="fatal: path '.sdlc/decision-log.md' exists on disk, but not in "
                                      "'refs/heads/feature'\n")
        if argv[1:3] == ["cat-file", "-e"] and argv[3].startswith("refs/heads/feature^"):
            return result(128, stderr="fatal: Not a valid object name refs/heads/feature^{tree}\n")
        return None

    spy.rules.append(rule)
    spy.start()
    scan = bs.scan_file(repo, LOG)
    assert [u["ref"] for u in scan.unread] == ["refs/heads/feature"]
    assert "tree could not be read" in scan.unread[0]["reason"]
    assert "Not a valid object name" in scan.unread[0]["reason"]    # git's own words are kept
    assert scan.refs_scanned == ["refs/heads/master"]
    assert scan.texts == {"refs/heads/master": log_text(1, 2, 3)}


def test_a_ref_whose_parent_directory_tree_is_missing_is_unread(repo, spy):
    """tree:1 style: the root tree reads, the tree under it does not."""
    def rule(argv):
        if argv[1:2] == ["show"] and argv[2].startswith("refs/heads/feature:"):
            return result(128, stderr="fatal: path '.sdlc/decision-log.md' does not exist in "
                                      "'refs/heads/feature'\n")
        if argv[1:2] == ["ls-tree"] and "-z" not in argv and argv[3] == "refs/heads/feature":
            return result(1, stderr="error: Could not read d18baca86174d9c405d6f710ce89bc81a46aa681\n")
        return None

    spy.rules.append(rule)
    spy.start()
    scan = bs.scan_file(repo, LOG)
    assert [u["ref"] for u in scan.unread] == ["refs/heads/feature"]
    assert "tree could not be read" in scan.unread[0]["reason"]
    assert "refs/heads/feature" not in scan.refs_scanned


def test_a_genuinely_absent_path_on_a_readable_ref_is_still_none(repo, spy):
    spy.start()
    assert bs.read_at(repo, "refs/heads/master", ".sdlc/never-existed.md") is None
    assert bs.read_at(repo, "refs/heads/master", "nothing-here.md") is None
    assert bs.list_dir_at(repo, "refs/heads/master", "no-such-dir") is None
    scan = bs.scan_file(repo, "specs/never-there.md")
    assert scan.unread == [] and scan.texts == {}
    assert scan.refs_scanned == ["refs/heads/feature", "refs/heads/master"]


def test_the_success_path_costs_no_extra_git_call(repo, spy):
    """The proof is only paid for by a path that is absent: reading an existing file is one `show`,
    listing an existing directory is one `ls-tree`."""
    spy.start()
    assert bs.read_at(repo, "refs/heads/master", LOG) == log_text(1, 2, 3)
    assert spy.commands() == ["show"]
    spy.calls.clear()
    assert bs.list_dir_at(repo, "refs/heads/master", "specs") == ["0001-a.md"]
    assert spy.commands() == ["ls-tree"]


def test_an_absent_path_is_proven_with_one_cat_file_and_one_ls_tree_for_its_directory(repo, spy):
    spy.start()
    assert bs.read_at(repo, "refs/heads/master", "nothing-here.md") is None       # at the project top
    assert spy.commands() == ["show", "cat-file", "ls-tree"]   # `ls-tree ./`: the project may be a sub-directory
    assert spy.calls[-1][-1] == "./"
    spy.calls.clear()
    assert bs.read_at(repo, "refs/heads/master", ".sdlc/never-existed.md") is None   # in a directory
    assert spy.commands() == ["show", "cat-file", "ls-tree"]
    spy.calls.clear()
    assert bs.list_dir_at(repo, "refs/heads/master", "no-such-dir") is None
    assert spy.commands() == ["ls-tree", "cat-file", "ls-tree"]   # the directory proof runs here too


# ===================================================================================================
# 2. "could not look" is not "not a repository"
# ===================================================================================================

def test_is_git_repo_still_says_false_for_a_directory_git_calls_not_a_repository(tmp_path, spy):
    spy.start()
    assert bs.is_git_repo(tmp_path) is False


def test_is_git_repo_raises_for_a_dubious_ownership_refusal(repo, spy):
    spy.rules.append(lambda argv: result(
        128, stderr="fatal: detected dubious ownership in repository at '/x'\n"
                    "To add an exception for this directory, call:\n") if argv[1] == "rev-parse" else None)
    spy.start()
    with pytest.raises(bs.BranchScanError, match="dubious ownership"):
        bs.is_git_repo(repo)


def test_is_git_repo_raises_for_a_timeout(repo, spy):
    def slow(argv):
        raise subprocess.TimeoutExpired(cmd="git", timeout=60)
    spy.rules.append(lambda argv: slow(argv) if argv[1] == "rev-parse" else None)
    spy.start()
    with pytest.raises(bs.BranchScanError, match="timed out"):
        bs.is_git_repo(repo)


def test_is_git_repo_raises_inside_a_bare_repository(tmp_path, spy):
    """`rev-parse --is-inside-work-tree` prints `false` there: not a work tree, but not "no repository"."""
    bare = tmp_path / "bare.git"
    bare.mkdir()
    git(bare, "init", "-q", "--bare")
    spy.start()
    with pytest.raises(bs.BranchScanError, match="not a git work tree"):
        bs.is_git_repo(bare)


def test_scan_file_reports_git_missing_as_all_refs_unread_not_as_not_a_repository(repo, spy):
    spy.missing = True
    spy.start()
    scan = bs.scan_file(repo, LOG)
    assert scan.is_git is True                                  # we cannot say it is NOT a repository
    assert scan.refs_scanned == [] and scan.texts == {}
    assert [u["ref"] for u in scan.unread] == ["(all refs)"]
    assert "could not run" in scan.unread[0]["reason"]


def test_scan_dir_reports_git_missing_the_same_way(repo, spy):
    spy.missing = True
    spy.start()
    is_git, refs, names, unread = bs.scan_dir(repo, "specs")
    assert (is_git, refs, names) == (True, [], {})
    assert [u["ref"] for u in unread] == ["(all refs)"]
    assert "could not run" in unread[0]["reason"]


def test_scan_file_reports_a_dubious_ownership_refusal_as_all_refs_unread(repo, spy):
    spy.rules.append(lambda argv: result(
        128, stderr="fatal: detected dubious ownership in repository at '/x'\n") if argv[1] == "rev-parse"
        else None)
    spy.start()
    scan = bs.scan_file(repo, LOG)
    assert scan.is_git is True and scan.refs_scanned == [] and scan.texts == {}
    assert scan.unread[0]["ref"] == "(all refs)" and "dubious ownership" in scan.unread[0]["reason"]
    assert "rev-parse" in spy.commands() and "show" not in spy.commands()    # nothing was read after it


def test_scan_dir_reports_a_dubious_ownership_refusal_as_all_refs_unread(repo, spy):
    spy.rules.append(lambda argv: result(
        128, stderr="fatal: detected dubious ownership in repository at '/x'\n") if argv[1] == "rev-parse"
        else None)
    spy.start()
    is_git, refs, names, unread = bs.scan_dir(repo, "specs")
    assert (is_git, refs, names) == (True, [], {})
    assert unread[0]["ref"] == "(all refs)" and "dubious ownership" in unread[0]["reason"]


def test_checked_summary_names_each_of_the_three_situations():
    assert bs.checked_summary(True, ["refs/heads/a", "refs/heads/b"], []) == "2 branch(es)"
    assert bs.checked_summary(True, [], []) == "0 branch(es)"            # looked, genuinely nothing
    assert bs.checked_summary(False, [], []) == "0 branches (not a git repository)"
    unread = [{"ref": "(all refs)", "reason": "git rev-parse\n failed:   nope"}]
    assert bs.checked_summary(True, [], unread) == "0 branches (could not read refs: git rev-parse failed: nope)"
    # one unreadable branch among readable ones does not change the count's wording
    assert bs.checked_summary(True, ["refs/heads/a"], [{"ref": "refs/heads/b", "reason": "x"}]) == "1 branch(es)"


def test_the_cli_says_could_not_read_refs_when_git_is_not_on_path(tmp_path, repo):
    empty = tmp_path / "no-git-here"
    empty.mkdir()
    env = {**os.environ, "PATH": str(empty), "PYTHONIOENCODING": "utf-8"}
    text = run_td(open_args("--all-branches"), repo, env)
    assert text.returncode == 0, text.stderr
    lines = text.stdout.splitlines()
    line = next(ln for ln in lines if ln.startswith("  Ids checked on"))
    assert line.startswith("  Ids checked on 0 branches (could not read refs: ")
    assert "could not run" in line
    assert "not a git repository" not in text.stdout
    assert "Warning:" in text.stderr and "(all refs)" in text.stderr

    doc_proc = run_td(open_args("--json", "--all-branches"), repo, env)
    assert doc_proc.returncode == 0, doc_proc.stderr
    doc = json.loads(doc_proc.stdout)
    assert doc["refs_scanned"] == []
    assert [u["ref"] for u in doc["unread"]] == ["(all refs)"]
    assert "could not run" in doc["unread"][0]["reason"]
    assert doc["id"] == "DL-05"   # the local id: the text run above already wrote DL-04 to the log


@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in git is a POSIX shell script")
def test_the_cli_says_could_not_read_refs_for_a_dubious_ownership_refusal(tmp_path, repo):
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "git"
    shim.write_text("#!/bin/sh\nif [ \"$1\" = rev-parse ]; then\n"
                    "  echo \"fatal: detected dubious ownership in repository at '/x'\" >&2\n  exit 128\nfi\n"
                    "exit 1\n", encoding="utf-8")
    shim.chmod(0o755)
    env = {**os.environ, "PATH": str(shim_dir) + os.pathsep + os.environ["PATH"],
           "PYTHONIOENCODING": "utf-8"}
    proc = run_td(open_args("--all-branches"), repo, env)
    assert proc.returncode == 0, proc.stderr
    line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("  Ids checked on"))
    assert line.startswith("  Ids checked on 0 branches (could not read refs: ")
    assert "dubious ownership" in line
    assert "not a git repository" not in proc.stdout


def test_data_spec_new_says_the_same_thing_when_git_is_not_on_path(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    made = REAL_RUN([sys.executable, str(SCRIPTS_DIR / "new_spec.py"), "--repo", ".", "--name", "parent",
                     "--risk", "MEDIUM", "--json"], capture_output=True, text=True, encoding="utf-8",
                    cwd=str(root))
    assert made.returncode == 0, made.stderr
    empty = tmp_path / "no-git-here"
    empty.mkdir()
    env = {**os.environ, "PATH": str(empty), "PYTHONIOENCODING": "utf-8"}
    proc = REAL_RUN([sys.executable, str(SCRIPTS_DIR / "data_spec.py"), "new", "--repo", ".",
                     "--serves", "0001", "--name", "claims profile", "--all-branches"],
                    capture_output=True, text=True, encoding="utf-8", cwd=str(root), env=env)
    assert proc.returncode == 0, proc.stderr
    line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("  Ids checked on"))
    assert line.startswith("  Ids checked on 0 branches (could not read refs: ")
    assert "not a git repository" not in proc.stdout
    assert "Warning:" in proc.stderr

    jroot = tmp_path / "proj-json"
    jroot.mkdir()
    REAL_RUN([sys.executable, str(SCRIPTS_DIR / "new_spec.py"), "--repo", ".", "--name", "parent",
              "--risk", "MEDIUM", "--json"], capture_output=True, text=True, encoding="utf-8", cwd=str(jroot),
             check=True)
    jproc = REAL_RUN([sys.executable, str(SCRIPTS_DIR / "data_spec.py"), "new", "--repo", ".",
                      "--serves", "0001", "--name", "claims profile", "--all-branches", "--json"],
                     capture_output=True, text=True, encoding="utf-8", cwd=str(jroot), env=env)
    assert jproc.returncode == 0, jproc.stderr
    doc = json.loads(jproc.stdout)
    assert doc["id"] == "0002" and doc["refs_scanned"] == []
    assert [u["ref"] for u in doc["unread"]] == ["(all refs)"]


# ===================================================================================================
# 3. a branch that merely ends in /HEAD is a branch
# ===================================================================================================

def make_head_named_branches(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "rel/HEAD", "master")
    commit(repo, {LOG: log_text(1, 2, 3, 4), "specs/0002-x.md": "x\n"}, "rel/HEAD branch")
    git(repo, "checkout", "-q", "master")
    git(repo, "update-ref", "refs/remotes/origin/master", "refs/heads/master")
    git(repo, "update-ref", "refs/remotes/origin/rel/HEAD", "refs/heads/rel/HEAD")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/master")


def test_list_refs_keeps_branches_named_head_and_drops_only_the_symbolic_alias(repo):
    make_head_named_branches(repo)
    # the alias really exists, and so does the branch that only looks like one
    assert "refs/remotes/origin/HEAD" in git(repo, "for-each-ref", "--format=%(refname)")
    refs = bs.list_refs(repo)
    assert "refs/heads/rel/HEAD" in refs
    assert "refs/remotes/origin/rel/HEAD" in refs
    assert "refs/remotes/origin/HEAD" not in refs
    assert refs == sorted(refs)


def test_scan_file_and_scan_dir_read_a_branch_named_rel_head(repo, spy):
    make_head_named_branches(repo)
    spy.start()
    scan = bs.scan_file(repo, LOG)
    assert "refs/heads/rel/HEAD" in scan.refs_scanned
    assert scan.texts["refs/heads/rel/HEAD"] == log_text(1, 2, 3, 4)
    assert "refs/remotes/origin/HEAD" not in scan.refs_scanned
    assert scan.unread == []
    _, refs, names, unread = bs.scan_dir(repo, "specs")
    assert names["refs/heads/rel/HEAD"] == ["0001-a.md", "0002-x.md"]
    assert "refs/remotes/origin/HEAD" not in refs and unread == []


@pytest.fixture
def head_repo(tmp_path) -> Path:
    """No `feature` here: the ONLY branch holding DL-04 and spec 0002 is `rel/HEAD`, so an id is
    reissued exactly when that branch is skipped. A remote's symbolic `origin/HEAD` is there too."""
    root = tmp_path / "head-repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    commit(root, {LOG: log_text(1, 2, 3), "specs/0001-a.md": "a\n"}, "master")
    git(root, "checkout", "-q", "-b", "rel/HEAD")
    commit(root, {LOG: log_text(1, 2, 3, 4), "specs/0002-x.md": "x\n"}, "rel/HEAD holds DL-04 and 0002")
    git(root, "checkout", "-q", "master")
    git(root, "update-ref", "refs/remotes/origin/master", "refs/heads/master")
    git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/master")
    return root


def test_open_all_branches_does_not_reissue_an_id_held_on_a_branch_named_rel_head(head_repo):
    proc = run_td(open_args("--json", "--all-branches"), head_repo)
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["id"] == "DL-05"                      # rel/HEAD's DL-04 is the highest anywhere
    assert "refs/heads/rel/HEAD" in doc["refs_scanned"]
    assert "refs/remotes/origin/HEAD" not in doc["refs_scanned"]   # the alias is still left out
    assert doc["unread"] == []


def test_data_spec_new_does_not_reissue_a_spec_id_held_on_a_branch_named_rel_head(tmp_path):
    root = tmp_path / "spec-head"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    made = REAL_RUN([sys.executable, str(SCRIPTS_DIR / "new_spec.py"), "--repo", ".", "--name", "parent",
                     "--risk", "MEDIUM", "--json"], capture_output=True, text=True, encoding="utf-8",
                    cwd=str(root))
    assert made.returncode == 0, made.stderr
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "checkout", "-q", "-b", "rel/HEAD")
    commit(root, {"specs/0002-x.md": "---\nspec: \"0002\"\n---\n"}, "rel/HEAD holds spec 0002")
    git(root, "checkout", "-q", "-")
    proc = REAL_RUN([sys.executable, str(SCRIPTS_DIR / "data_spec.py"), "new", "--repo", ".",
                     "--serves", "0001", "--name", "claims profile", "--all-branches", "--json"],
                    capture_output=True, text=True, encoding="utf-8", cwd=str(root))
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["id"] == "0003"
    assert "refs/heads/rel/HEAD" in doc["refs_scanned"] and doc["unread"] == []


# ===================================================================================================
# 4. a partial clone on a git that would fetch for it is not read
# ===================================================================================================

@pytest.mark.parametrize("text, expected", [
    ("git version 2.43.0", (2, 43)),
    ("git version 2.46.0.windows.1", (2, 46)),
    ("git version 2.54.0 (Apple Git-157)", (2, 54)),
    ("git version 2.9.5", (2, 9)),
    ("git version 10.0.1\n", (10, 0)),
    ("git version 2.45", (2, 45)),
    ("", None),
    ("not git at all", None),
    ("git version 2", None),
])
def test_parse_git_version_reads_the_first_two_numbers(text, expected):
    assert bs.parse_git_version(text) == expected


def test_versions_compare_as_numbers_not_as_text():
    assert bs.parse_git_version("git version 2.9.5") < bs.MIN_NO_LAZY_FETCH_VERSION
    assert bs.parse_git_version("git version 2.100.0") > bs.MIN_NO_LAZY_FETCH_VERSION


NOTHING_READ = {"show", "cat-file", "ls-tree", "for-each-ref"}


def mark_partial(repo: Path) -> None:
    git(repo, "config", "remote.origin.promisor", "true")


def test_a_partial_clone_on_git_2_43_is_not_read_at_all(repo, spy):
    mark_partial(repo)
    spy.version = "2.43.0"
    spy.start()
    scan = bs.scan_file(repo, LOG)
    assert scan.is_git is True
    assert scan.refs_scanned == [] and scan.texts == {}
    assert [u["ref"] for u in scan.unread] == ["(all refs)"]
    reason = scan.unread[0]["reason"]
    assert "2.45" in reason and "2.43" in reason and "nothing was fetched" in reason
    assert not NOTHING_READ & set(spy.commands()), spy.commands()


def test_scan_dir_on_a_partial_clone_with_old_git_reads_nothing_either(repo, spy):
    mark_partial(repo)
    spy.version = "2.43.0"
    spy.start()
    is_git, refs, names, unread = bs.scan_dir(repo, "specs")
    assert (is_git, refs, names) == (True, [], {})
    assert [u["ref"] for u in unread] == ["(all refs)"] and "2.45" in unread[0]["reason"]
    assert not NOTHING_READ & set(spy.commands()), spy.commands()


@pytest.mark.parametrize("version", ["2.45.0", "2.46.0.windows.1", "2.54.0 (Apple Git-157)", "3.0.1"])
def test_the_same_partial_clone_on_git_2_45_or_newer_is_read(repo, spy, version):
    mark_partial(repo)
    spy.version = version
    spy.start()
    scan = bs.scan_file(repo, LOG)
    assert scan.unread == []
    assert scan.refs_scanned == ["refs/heads/feature", "refs/heads/master"]
    assert scan.texts["refs/heads/feature"] == log_text(1, 2, 3, 7)


@pytest.mark.parametrize("version", ["2.44.9", "2.9.5", "1.8.3"])
def test_older_gits_are_refused_by_number_not_by_text(repo, spy, version):
    mark_partial(repo)
    spy.version = version
    spy.start()
    scan = bs.scan_file(repo, LOG)
    assert scan.refs_scanned == [] and "2.45" in scan.unread[0]["reason"]


def test_the_partial_clone_extension_alone_counts_as_a_partial_clone(repo, spy):
    git(repo, "config", "extensions.partialclone", "origin")
    spy.version = "2.43.0"
    spy.start()
    scan = bs.scan_file(repo, LOG)
    assert scan.refs_scanned == [] and "2.45" in scan.unread[0]["reason"]
    assert not NOTHING_READ & set(spy.commands())


def test_a_full_clone_is_read_on_any_git_and_the_version_is_never_asked(repo, spy):
    spy.version = "2.43.0"
    spy.start()
    scan = bs.scan_file(repo, LOG)
    assert scan.unread == [] and scan.refs_scanned == ["refs/heads/feature", "refs/heads/master"]
    assert "--version" not in spy.commands()           # probed once, and only for a partial clone


def test_a_promisor_remote_set_to_false_is_not_a_partial_clone(repo, spy):
    git(repo, "config", "remote.origin.promisor", "false")
    spy.version = "2.43.0"
    spy.start()
    scan = bs.scan_file(repo, LOG)
    assert scan.unread == [] and "--version" not in spy.commands()


def test_the_partial_clone_probe_runs_once_per_scan(repo, spy):
    mark_partial(repo)
    spy.version = "2.54.0"
    spy.start()
    bs.scan_file(repo, LOG)
    assert spy.commands().count("--version") == 1
    assert spy.commands().count("config") == 1          # the promisor probe answered; no second query


def test_a_partial_clone_whose_git_version_cannot_be_read_is_not_read(repo, spy):
    mark_partial(repo)
    spy.version = "banana"
    spy.start()
    scan = bs.scan_file(repo, LOG)
    assert scan.refs_scanned == [] and scan.texts == {}
    assert scan.unread[0]["ref"] == "(all refs)" and "could not be read" in scan.unread[0]["reason"]
    assert not NOTHING_READ & set(spy.commands())


def test_a_config_that_git_cannot_read_is_reported_not_treated_as_not_partial(repo, spy):
    spy.rules.append(lambda argv: result(128, stderr="fatal: bad config line 3 in file .git/config\n")
                     if argv[1] == "config" else None)
    spy.start()
    scan = bs.scan_file(repo, LOG)
    assert scan.refs_scanned == [] and scan.texts == {}
    assert scan.unread[0]["ref"] == "(all refs)" and "bad config line" in scan.unread[0]["reason"]


@modern_git
def test_a_real_partial_clone_is_read_on_a_git_that_can_be_told_not_to_fetch(tmp_path, repo, spy):
    dst = partial_clone(tmp_path, repo, "tree:0")
    spy.start()
    scan = bs.scan_file(dst, LOG)
    assert [u["ref"] for u in scan.unread] == ["refs/remotes/origin/feature"]   # unloadable, not blocked
    assert "refs/heads/master" in scan.refs_scanned
    assert "--version" in spy.commands()
    assert "fetch" not in spy.commands()


# ===================================================================================================
# the module still never fetches
# ===================================================================================================

def test_no_command_issued_on_any_path_above_is_a_fetch(repo, spy):
    """One run across every public entry point and every refusal path: nothing may fetch, pull,
    clone or talk to a remote, no call may use a shell, and every call carries GIT_NO_LAZY_FETCH."""
    make_head_named_branches(repo)
    spy.start()
    bs.is_git_repo(repo)
    bs.list_refs(repo)
    bs.read_at(repo, "refs/heads/master", LOG)
    bs.read_at(repo, "refs/heads/master", "absent/never.md")
    bs.list_dir_at(repo, "refs/heads/master", "specs")
    bs.list_dir_at(repo, "refs/heads/master", "absent")
    bs.scan_file(repo, LOG)
    bs.scan_dir(repo, "specs")
    mark_partial(repo)
    for version in ("2.43.0", "2.54.0"):
        spy.version = version
        bs.scan_file(repo, LOG)
        bs.scan_dir(repo, "specs")
    spy.missing = True
    bs.scan_file(repo, LOG)
    bs.scan_dir(repo, "specs")
    spy.assert_never_fetches()


def test_the_module_source_still_has_no_fetch_command_or_shell():
    source = Path(bs.__file__).read_text(encoding="utf-8")
    assert source.count('"fetch"') == 0
    assert "shell=True" not in source


# ===================================================================================================
# 5. a project in a SUB-DIRECTORY of a larger repository, on a tree:1 clone (review round 2)
# ===================================================================================================

@modern_git
def test_a_sub_project_root_level_log_on_a_tree_1_clone_is_unread_not_absent(tmp_path):
    """The project lives at proj/ inside a larger repo and keeps its log at proj/decision-log.md (the
    resolve_write_target fallback). A `--filter=tree:1` clone has the git-root tree but not proj/'s,
    so git says the log 'exists on disk, but not in' the other branch — proving only the root tree
    would still call it absent and count the branch. The project directory itself is proven too."""
    src = tmp_path / "mono"
    src.mkdir()
    git(src, "init", "-q", "-b", "master")
    git(src, "config", "uploadpack.allowfilter", "true")
    commit(src, {"README.md": "top\n", "proj/decision-log.md": log_text(1, 2)}, "master")
    git(src, "checkout", "-q", "-b", "other")
    commit(src, {"proj/decision-log.md": log_text(1, 2, 5)}, "other")
    git(src, "checkout", "-q", "master")
    dst = tmp_path / "clone-tree-1"
    proc = REAL_RUN(["git", "clone", "-q", "--filter=tree:1", "--no-local", src.as_uri(), str(dst)],
                    capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"cannot make a --filter=tree:1 clone here: {proc.stderr.strip()}")
    probe = REAL_RUN(["git", "ls-tree", "--name-only", "refs/remotes/origin/other", "proj/"], cwd=dst,
                     capture_output=True, text=True, env={**os.environ, "GIT_NO_LAZY_FETCH": "1"})
    if probe.returncode == 0:
        pytest.skip("--filter=tree:1 did not leave proj/'s tree unreadable on this git")
    scan = bs.scan_file(dst / "proj", "decision-log.md")
    assert "refs/remotes/origin/other" in [u["ref"] for u in scan.unread]
    assert "refs/remotes/origin/other" not in scan.refs_scanned
    assert "refs/heads/master" in scan.refs_scanned
    # and the CLI does not reissue DL-05 as if that branch had been read
    proc = run_td(open_args("--all-branches", "--json"), dst / "proj")
    doc = json.loads(proc.stdout)
    assert "refs/remotes/origin/other" in [u["ref"] for u in doc["unread"]]
    assert doc["refs_scanned"] == [r for r in doc["refs_scanned"] if r != "refs/remotes/origin/other"]
