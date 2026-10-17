"""DS-P1 — `branch_scan.py`: read one file (or list one directory) as it stands on every local ref.

Why these tests are shaped the way they are: the module is thin git I/O whose two promises are
about what it must NOT do. It never fetches (an id allocation is a text edit; it must not reach the
network), and it never loses a ref silently (a ref it could not read is named, with a reason, so a
person is not told "no other branch uses DL-08" about a branch nobody looked at). Everything here runs
against real `git` repositories built under `tmp_path`, so a change to the actual plumbing cannot hide
behind a mock that quietly drifted from real git behaviour.
"""

import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import branch_scan as bs  # noqa: E402

LOG = ".sdlc/decision-log.md"


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8")
    return done.stdout.strip()


def commit(repo: Path, rel: str, text: str, message: str = "c") -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    commit(root, LOG, "master log\n", "master")
    return root


@pytest.fixture
def two_branches(repo) -> Path:
    """master has the log; `feature` changes it; `bare` never has it (a branch off an empty commit)."""
    git(repo, "checkout", "-q", "-b", "feature")
    commit(repo, LOG, "feature log\n", "feature")
    git(repo, "checkout", "-q", "master")
    git(repo, "checkout", "-q", "--orphan", "bare")
    git(repo, "rm", "-rfq", ".")
    commit(repo, "README.md", "nothing here\n", "bare")
    git(repo, "checkout", "-q", "master")
    return repo


# --- is_git_repo ---

def test_is_git_repo_true_for_a_repository(repo):
    assert bs.is_git_repo(repo) is True


def test_is_git_repo_false_for_a_plain_directory(tmp_path):
    assert bs.is_git_repo(tmp_path) is False


def test_is_git_repo_false_for_a_directory_that_does_not_exist(tmp_path):
    assert bs.is_git_repo(tmp_path / "nope") is False


def test_is_git_repo_raises_rather_than_answering_false_when_git_cannot_run(repo, monkeypatch):
    """"git is not installed" is not "this is not a repository": the first must be reported, not read
    as a clean empty result (test_branch_scan_honesty.py pins what the callers then say)."""
    def boom(*a, **k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(bs.subprocess, "run", boom)
    with pytest.raises(bs.BranchScanError, match="could not run"):
        bs.is_git_repo(repo)


# --- list_refs ---

def test_list_refs_returns_sorted_local_and_remote_tracking_refs(two_branches):
    git(two_branches, "update-ref", "refs/remotes/origin/master", "refs/heads/master")
    refs = bs.list_refs(two_branches)
    assert refs == ["refs/heads/bare", "refs/heads/feature", "refs/heads/master",
                    "refs/remotes/origin/master"]
    assert refs == sorted(refs)


def test_list_refs_omits_the_remote_head_alias(two_branches):
    """A symbolic ref is dropped because it IS an alias (its `%(symref)` is set), not because of its
    name; a real branch that happens to end in `/HEAD` is kept (test_branch_scan_honesty.py)."""
    git(two_branches, "update-ref", "refs/remotes/origin/master", "refs/heads/master")
    git(two_branches, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/master")
    # the alias really exists, so its absence below is the module's doing, not the fixture's
    assert "refs/remotes/origin/HEAD" in git(two_branches, "for-each-ref", "--format=%(refname)")
    refs = bs.list_refs(two_branches)
    assert "refs/remotes/origin/HEAD" not in refs
    assert "refs/remotes/origin/master" in refs
    assert refs == ["refs/heads/bare", "refs/heads/feature", "refs/heads/master",
                    "refs/remotes/origin/master"]


def test_list_refs_omits_tags(repo):
    git(repo, "tag", "v1")
    assert bs.list_refs(repo) == ["refs/heads/master"]


def test_list_refs_of_a_repository_with_no_commits_is_empty(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    assert bs.list_refs(root) == []


# --- read_at ---

def test_read_at_returns_the_text_on_that_ref(two_branches):
    assert bs.read_at(two_branches, "refs/heads/master", LOG) == "master log\n"
    assert bs.read_at(two_branches, "refs/heads/feature", LOG) == "feature log\n"


def test_read_at_returns_none_for_a_path_that_is_absent_on_that_ref(two_branches):
    assert bs.read_at(two_branches, "refs/heads/bare", LOG) is None
    assert bs.read_at(two_branches, "refs/heads/master", ".sdlc/never-existed.md") is None


def test_read_at_returns_none_for_a_path_that_exists_on_disk_but_not_on_the_ref(two_branches):
    # git's second wording: "exists on disk, but not in '<ref>'"
    (two_branches / "untracked.md").write_text("on disk only\n", encoding="utf-8")
    assert bs.read_at(two_branches, "refs/heads/master", "untracked.md") is None


def test_read_at_keeps_every_byte_crlf_included(repo):
    text = "| id |\r\n|----|\r\n| DL-01 |\r\n"
    commit(repo, LOG, text, "crlf")
    assert bs.read_at(repo, "refs/heads/master", LOG) == text


def test_read_at_keeps_non_ascii_text(repo):
    text = "decision — pick the “auth” provider\n"
    commit(repo, LOG, text, "unicode")
    assert bs.read_at(repo, "refs/heads/master", LOG) == text


def test_read_at_raises_for_a_ref_that_does_not_exist(repo):
    with pytest.raises(bs.BranchScanError):
        bs.read_at(repo, "refs/heads/no-such-branch", LOG)


def test_read_at_refuses_a_ref_that_could_pass_for_an_option(repo):
    with pytest.raises(bs.BranchScanError):
        bs.read_at(repo, "--output=/tmp/x", LOG)


def test_read_at_raises_rather_than_returning_none_when_git_cannot_run(repo, monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(bs.subprocess, "run", boom)
    with pytest.raises(bs.BranchScanError):
        bs.read_at(repo, "refs/heads/master", LOG)


def test_read_at_raises_on_a_timeout(repo, monkeypatch):
    def slow(*a, **k):
        raise subprocess.TimeoutExpired(cmd="git", timeout=60)
    monkeypatch.setattr(bs.subprocess, "run", slow)
    with pytest.raises(bs.BranchScanError, match="timed out"):
        bs.read_at(repo, "refs/heads/master", LOG)


def test_read_at_is_relative_to_the_given_directory_not_the_git_root(repo):
    """A project can sit in a subdirectory of a larger repository (a monorepo): the path the
    caller passes is relative to the project, so it must be read from there."""
    project = repo / "proj"
    commit(repo, "proj/.sdlc/decision-log.md", "project log\n", "proj")
    commit(repo, "rootonly.md", "lives at the git root\n", "root")
    assert bs.read_at(project, "refs/heads/master", ".sdlc/decision-log.md") == "project log\n"
    assert bs.read_at(project, "refs/heads/master", "rootonly.md") is None    # not in the project
    assert bs.read_at(repo, "refs/heads/master", "rootonly.md") == "lives at the git root\n"


# --- list_dir_at ---

def test_list_dir_at_returns_basenames(repo):
    commit(repo, "specs/0001-a.md", "a\n")
    commit(repo, "specs/0002-b.md", "b\n")
    commit(repo, "specs/nested/0003-c.md", "c\n")
    names = bs.list_dir_at(repo, "refs/heads/master", "specs")
    assert sorted(names) == ["0001-a.md", "0002-b.md", "nested"]
    assert all("/" not in n for n in names)


def test_list_dir_at_returns_none_when_the_directory_is_absent(two_branches):
    assert bs.list_dir_at(two_branches, "refs/heads/master", "specs") is None
    commit(two_branches, "specs/0001-a.md", "a\n")
    assert bs.list_dir_at(two_branches, "refs/heads/bare", "specs") is None


def test_list_dir_at_does_not_confuse_a_file_with_a_directory(repo):
    commit(repo, "specs", "a file named like the directory\n")
    assert bs.list_dir_at(repo, "refs/heads/master", "specs") is None


def test_list_dir_at_names_with_spaces_and_non_ascii_come_back_whole(repo):
    commit(repo, "specs/0001 a spec.md", "a\n")
    commit(repo, "specs/0002-café.md", "b\n")
    assert sorted(bs.list_dir_at(repo, "refs/heads/master", "specs")) == [
        "0001 a spec.md", "0002-café.md"]


def test_list_dir_at_is_relative_to_the_given_directory(repo):
    commit(repo, "proj/specs/0001-a.md", "a\n")
    assert bs.list_dir_at(repo / "proj", "refs/heads/master", "specs") == ["0001-a.md"]


def test_list_dir_at_raises_for_a_ref_that_does_not_exist(repo):
    with pytest.raises(bs.BranchScanError):
        bs.list_dir_at(repo, "refs/heads/no-such-branch", "specs")


# --- scan_file ---

def test_scan_file_reads_the_file_on_every_ref_that_has_it(two_branches):
    git(two_branches, "update-ref", "refs/remotes/origin/feature", "refs/heads/feature")
    result = bs.scan_file(two_branches, LOG)
    assert result.is_git is True
    assert result.refs_scanned == ["refs/heads/bare", "refs/heads/feature", "refs/heads/master",
                                   "refs/remotes/origin/feature"]
    assert result.texts == {
        "refs/heads/feature": "feature log\n",
        "refs/heads/master": "master log\n",
        "refs/remotes/origin/feature": "feature log\n",
    }                                         # `bare` was scanned and has no such file: no entry
    assert result.unread == []


def test_scan_file_reads_the_committed_ref_not_the_working_tree(repo):
    (repo / LOG).write_text("edited but never committed\n", encoding="utf-8")
    assert bs.scan_file(repo, LOG).texts == {"refs/heads/master": "master log\n"}


def test_scan_file_of_a_repository_with_no_commits(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    assert bs.scan_file(root, LOG) == bs.ScanResult(True, [], {}, [])


def test_scan_file_outside_a_git_repository(tmp_path):
    assert bs.scan_file(tmp_path, LOG) == bs.ScanResult(False, [], {}, [])


def test_scan_file_names_a_ref_it_could_not_read_and_keeps_going(two_branches, monkeypatch):
    real = bs.read_at

    def read_at(repo_root, ref, rel_path):
        if ref == "refs/heads/feature":
            raise bs.BranchScanError("git show refs/heads/feature failed: broken pack")
        return real(repo_root, ref, rel_path)

    monkeypatch.setattr(bs, "read_at", read_at)
    result = bs.scan_file(two_branches, LOG)
    assert result.unread == [{"ref": "refs/heads/feature",
                              "reason": "git show refs/heads/feature failed: broken pack"}]
    assert result.texts == {"refs/heads/master": "master log\n"}
    # a ref nobody could read was not "scanned"; it is named in `unread` and only there
    assert "refs/heads/feature" not in result.refs_scanned
    assert result.refs_scanned == ["refs/heads/bare", "refs/heads/master"]


def test_scan_file_names_a_ref_whose_object_is_damaged(two_branches):
    """A real unreadable ref, no monkeypatching: `feature`'s log blob is gone from the object store."""
    sha = git(two_branches, "rev-parse", f"refs/heads/feature:{LOG}")
    obj = two_branches / ".git" / "objects" / sha[:2] / sha[2:]
    obj.chmod(stat.S_IWRITE)             # git writes objects read-only; Windows refuses to unlink them otherwise
    obj.unlink()
    result = bs.scan_file(two_branches, LOG)
    assert [u["ref"] for u in result.unread] == ["refs/heads/feature"]
    assert result.unread[0]["reason"]
    assert result.texts == {"refs/heads/master": "master log\n"}
    assert "refs/heads/feature" not in result.refs_scanned


def test_scan_file_reports_a_failure_to_list_refs_instead_of_returning_a_clean_result(repo, monkeypatch):
    def boom(repo_root):
        raise bs.BranchScanError("for-each-ref failed: bad object")
    monkeypatch.setattr(bs, "list_refs", boom)
    result = bs.scan_file(repo, LOG)
    assert result.is_git is True
    assert result.refs_scanned == []
    assert result.texts == {}
    assert len(result.unread) == 1 and "for-each-ref failed" in result.unread[0]["reason"]


def test_scan_file_unread_is_sorted_by_ref(repo, monkeypatch):
    git(repo, "branch", "b-branch")
    git(repo, "branch", "a-branch")

    def read_at(repo_root, ref, rel_path):
        raise bs.BranchScanError("nope")

    monkeypatch.setattr(bs, "read_at", read_at)
    assert [u["ref"] for u in bs.scan_file(repo, LOG).unread] == [
        "refs/heads/a-branch", "refs/heads/b-branch", "refs/heads/master"]


# --- scan_dir ---

def test_scan_dir_lists_the_directory_on_every_ref_that_has_it(two_branches):
    git(two_branches, "checkout", "-q", "feature")
    commit(two_branches, "specs/0005-x.md", "x\n")
    git(two_branches, "checkout", "-q", "master")
    commit(two_branches, "specs/0001-a.md", "a\n")
    is_git, refs, names, unread = bs.scan_dir(two_branches, "specs")
    assert is_git is True
    assert refs == ["refs/heads/bare", "refs/heads/feature", "refs/heads/master"]
    assert names == {"refs/heads/feature": ["0005-x.md"], "refs/heads/master": ["0001-a.md"]}
    assert unread == []


def test_scan_dir_outside_a_git_repository(tmp_path):
    assert bs.scan_dir(tmp_path, "specs") == (False, [], {}, [])


def test_scan_dir_names_a_ref_it_could_not_read(repo, monkeypatch):
    commit(repo, "specs/0001-a.md", "a\n")
    git(repo, "branch", "other")
    real = bs.list_dir_at

    def list_dir_at(repo_root, ref, rel_dir):
        if ref == "refs/heads/other":
            raise bs.BranchScanError("cannot list")
        return real(repo_root, ref, rel_dir)

    monkeypatch.setattr(bs, "list_dir_at", list_dir_at)
    is_git, refs, names, unread = bs.scan_dir(repo, "specs")
    assert unread == [{"ref": "refs/heads/other", "reason": "cannot list"}]
    assert names == {"refs/heads/master": ["0001-a.md"]}
    assert refs == ["refs/heads/master"]


# --- never fetches ---

def test_no_command_the_module_runs_is_a_fetch(two_branches, monkeypatch):
    """Allocating an id is a text edit: it must not reach the network. Every git command the module
    issues, across every public function, is recorded and none may be a fetch (or anything that
    talks to a remote), and none may use a shell."""
    commit(two_branches, "specs/0001-a.md", "a\n")      # fixture work, before the recorder is on
    seen = []
    envs = []
    real = subprocess.run

    def recording(argv, *a, **k):
        seen.append((list(argv), k.get("shell")))
        envs.append(k.get("env") or {})
        return real(argv, *a, **k)

    monkeypatch.setattr(bs.subprocess, "run", recording)
    bs.is_git_repo(two_branches)
    bs.list_refs(two_branches)
    bs.read_at(two_branches, "refs/heads/master", LOG)
    bs.read_at(two_branches, "refs/heads/bare", LOG)
    bs.list_dir_at(two_branches, "refs/heads/master", "specs")
    bs.scan_file(two_branches, LOG)
    bs.scan_dir(two_branches, "specs")

    assert seen, "the recording wrapper saw nothing: the test proves nothing"
    forbidden = {"fetch", "pull", "push", "clone", "ls-remote", "remote"}
    for argv, shell in seen:
        assert argv[0] == "git"
        assert not (forbidden & set(argv)), argv
        assert not shell, argv
    # a partial clone must not fetch a missing blob from its remote just because a read asked for it
    assert all(env.get("GIT_NO_LAZY_FETCH") == "1" for env in envs)


def test_the_module_source_never_says_fetch_as_a_command():
    """Gate G9 in the build kit: `grep -c '"fetch"' scripts/branch_scan.py` must print 0."""
    source = Path(bs.__file__).read_text(encoding="utf-8")
    assert '"fetch"' not in source
    assert "shell=True" not in source


def test_the_module_does_not_import_handoff():
    """It copies run_git's pattern rather than importing a module that probes code hosts."""
    source = Path(bs.__file__).read_text(encoding="utf-8")
    assert "import handoff" not in source and "from handoff" not in source
