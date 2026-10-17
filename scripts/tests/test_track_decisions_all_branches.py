"""DS-P1 — `track_decisions.py open --all-branches`.

Why these tests are shaped the way they are: two branches can each open "the next" decision and both
write DL-07; the flag exists so the new id is unused on every local ref. The properties that matter are
(1) the id really clears every branch's log, including remote-tracking refs and logs that only exist
there, (2) a branch whose log cannot be used is NAMED rather than silently ignored, and (3) without the
flag nothing a caller already depends on moves — same JSON keys, same text — because the verb's
goldens are pinned by earlier specs. Everything runs the real script against real git repositories.
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from golden_support import SCRIPTS_DIR  # noqa: E402

SCRIPT = SCRIPTS_DIR / "track_decisions.py"
TEMPLATE = SCRIPTS_DIR.parent / "templates" / "phases" / "01-requirements" / "decision-log.md"
LOG = ".sdlc/decision-log.md"
OPENED = "2026-10-02"  # a Friday: due is Tuesday 2026-10-06

HEADER = ("| id    | decision                | owner | opened     | due (2 business days) | status |\n"
          "|-------|-------------------------|-------|------------|-----------------------|--------|\n")


def log_text(*ids: int, prose: str = "# Decision Log\n\n") -> str:
    rows = "".join(f"| DL-{n:02d} | Decision number {n} | Jane | 2026-07-07 | 2026-07-09 | open |\n"
                   for n in ids)
    return prose + HEADER + rows + "\n*Add one row per decision.*\n"


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8")
    return done.stdout.strip()


def commit(repo: Path, text: str, message: str = "log", rel: str = LOG) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def run(args, cwd: Path):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          encoding="utf-8", cwd=str(cwd),
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def open_args(*extra: str, decision="x", owner="@priya-n"):
    return ["open", "--repo", ".", "--decision", decision, "--owner", owner, *extra]


def open_json(cwd: Path, *extra: str) -> dict:
    proc = run(open_args("--json", *extra), cwd)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.fixture
def repo(tmp_path) -> Path:
    """master holds DL-01..DL-03; `feature` holds DL-07; we are back on master."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    commit(root, log_text(1, 2, 3), "master log")
    git(root, "checkout", "-q", "-b", "feature")
    commit(root, log_text(1, 2, 3, 7), "feature log")
    git(root, "checkout", "-q", "master")
    return root


# --- the headline: the id is unused on every branch ---

def test_all_branches_picks_an_id_no_branch_has_used(repo):
    doc = open_json(repo, "--all-branches")
    assert doc["id"] == "DL-08"
    assert "refs/heads/feature" in doc["refs_scanned"]
    assert "refs/heads/master" in doc["refs_scanned"]
    assert doc["unread"] == []


def test_without_the_flag_the_id_is_the_local_one(repo):
    assert open_json(repo)["id"] == "DL-04"


def test_without_the_flag_the_json_keys_are_exactly_what_they_were(repo):
    doc = open_json(repo)
    assert set(doc) == {"id", "opened", "due", "owner", "path"}


def test_the_row_is_written_to_the_local_log_only(repo):
    open_json(repo, "--all-branches")
    local = (repo / LOG).read_text(encoding="utf-8")
    assert "| DL-08 |" in local
    assert "DL-07" not in local            # the other branch's row was only read, never copied
    assert git(repo, "show", f"refs/heads/feature:{LOG}") == log_text(1, 2, 3, 7).rstrip("\n")


def test_the_other_branches_highest_id_wins_even_when_it_is_far_ahead(repo):
    git(repo, "checkout", "-q", "feature")
    commit(repo, log_text(1, 2, 3, 41), "feature log")
    git(repo, "checkout", "-q", "master")
    assert open_json(repo, "--all-branches")["id"] == "DL-42"


def test_the_local_log_still_wins_when_it_is_the_highest(repo):
    (repo / LOG).write_bytes(log_text(1, 2, 3, 9).encode("utf-8"))   # uncommitted, ahead of feature
    assert open_json(repo, "--all-branches")["id"] == "DL-10"


def test_an_id_that_appears_only_in_prose_on_another_branch_still_counts(repo):
    git(repo, "checkout", "-q", "feature")
    commit(repo, log_text(1, 2, 3, prose="# Decision Log\n\nSee DL-19 in the workshop notes.\n\n"),
           "prose")
    git(repo, "checkout", "-q", "master")
    assert open_json(repo, "--all-branches")["id"] == "DL-20"


def test_remote_tracking_refs_are_read_too(repo):
    """A log that lives only on a remote-tracking ref (the branch was never checked out here)."""
    git(repo, "update-ref", "refs/remotes/origin/sprint-9", "refs/heads/feature")
    git(repo, "branch", "-q", "-D", "feature")
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/sprint-9")
    doc = open_json(repo, "--all-branches")
    assert doc["id"] == "DL-08"
    assert "refs/remotes/origin/sprint-9" in doc["refs_scanned"]
    assert "refs/remotes/origin/HEAD" not in doc["refs_scanned"]   # a symbolic alias, not a branch


def test_a_branch_without_a_log_is_scanned_and_is_not_a_problem(repo):
    git(repo, "checkout", "-q", "--orphan", "docs-only")
    git(repo, "rm", "-rfq", ".")
    commit(repo, "just docs\n", "docs", rel="README.md")
    git(repo, "checkout", "-q", "master")
    doc = open_json(repo, "--all-branches")
    assert doc["id"] == "DL-08"
    assert "refs/heads/docs-only" in doc["refs_scanned"]
    assert doc["unread"] == []


def test_a_branch_holding_only_the_shipped_template_does_not_move_the_id(repo):
    """The template's own prose cites DL-01 as an example; a fresh log on another branch is not use."""
    git(repo, "checkout", "-q", "-b", "fresh", "master")
    commit(repo, TEMPLATE.read_text(encoding="utf-8"), "fresh template")
    git(repo, "checkout", "-q", "master")
    git(repo, "branch", "-q", "-D", "feature")
    assert open_json(repo, "--all-branches")["id"] == "DL-04"


# --- a ref that cannot be used is named, never dropped ---

def test_a_branch_whose_log_has_no_table_is_named_in_unread_and_the_verb_still_succeeds(repo):
    git(repo, "checkout", "-q", "-b", "broken", "master")
    commit(repo, "# Decision Log\n\nWe forgot the table.\n", "no table")
    git(repo, "checkout", "-q", "master")
    proc = run(open_args("--json", "--all-branches"), repo)
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["id"] == "DL-08"                              # the readable branch still counted
    assert [u["ref"] for u in doc["unread"]] == ["refs/heads/broken"]
    assert "no decision table" in doc["unread"][0]["reason"]
    assert "refs/heads/broken" not in doc["refs_scanned"]    # not checked, so not claimed as checked
    assert "refs/heads/feature" in doc["refs_scanned"]


def test_a_branch_with_an_unrecognised_table_header_is_named_in_unread(repo):
    git(repo, "checkout", "-q", "-b", "odd", "master")
    commit(repo, "# Log\n\n| id | thing |\n|----|-------|\n| DL-30 | x |\n", "odd header")
    git(repo, "checkout", "-q", "master")
    doc = open_json(repo, "--all-branches")
    assert [u["ref"] for u in doc["unread"]] == ["refs/heads/odd"]
    assert "not recognised" in doc["unread"][0]["reason"]
    assert doc["id"] == "DL-08"


def test_the_text_output_warns_on_stderr_about_an_unreadable_branch(repo):
    git(repo, "checkout", "-q", "-b", "broken", "master")
    commit(repo, "no table here\n", "no table")
    git(repo, "checkout", "-q", "master")
    proc = run(open_args("--all-branches"), repo)
    assert proc.returncode == 0
    assert "refs/heads/broken" in proc.stderr
    assert "refs/heads/broken" not in proc.stdout


def test_a_ref_git_cannot_read_is_named_in_unread(repo):
    """Not monkeypatched: `feature`'s log blob is gone from the object store."""
    sha = git(repo, "rev-parse", f"refs/heads/feature:{LOG}")
    obj = repo / ".git" / "objects" / sha[:2] / sha[2:]
    obj.chmod(stat.S_IWRITE)             # git writes objects read-only; Windows refuses to unlink them otherwise
    obj.unlink()
    doc = open_json(repo, "--all-branches")
    assert [u["ref"] for u in doc["unread"]] == ["refs/heads/feature"]
    assert doc["unread"][0]["reason"]
    assert doc["id"] == "DL-04"           # that branch's DL-07 cannot be seen, and the output says so
    assert "refs/heads/feature" not in doc["refs_scanned"]


# --- not a git repository ---

def test_outside_a_git_repository_the_flag_still_opens_dl_01_from_the_template(tmp_path):
    doc = open_json(tmp_path, "--all-branches")
    assert doc["id"] == "DL-01"
    assert doc["refs_scanned"] == []
    assert doc["unread"] == []
    assert (tmp_path / LOG).exists()                         # created from the template, as ever
    assert "| DL-01 |" in (tmp_path / LOG).read_text(encoding="utf-8")


def test_outside_a_git_repository_the_text_line_says_so(tmp_path):
    proc = run(open_args("--all-branches"), tmp_path)
    assert proc.returncode == 0
    assert "  Ids checked on 0 branches (not a git repository)" in proc.stdout.splitlines()


# --- the text output ---

def test_the_text_output_gains_exactly_one_line_with_the_flag(tmp_path):
    """Two identical repositories, one run with the flag and one without: the flagged stdout is the
    plain stdout plus the one branch line, byte for byte. This is what keeps the flagged path's copy
    of the verb's text from drifting away from the original."""
    outputs = {}
    for name in ("plain", "flagged"):
        root = tmp_path / name
        root.mkdir()
        git(root, "init", "-q", "-b", "master")
        commit(root, log_text(1, 2, 3), "master log")
        extra = ("--all-branches",) if name == "flagged" else ()
        outputs[name] = run(open_args("--opened", OPENED, *extra), root)
    assert outputs["plain"].returncode == outputs["flagged"].returncode == 0
    assert outputs["plain"].stdout == ("Decision opened: DL-04  [@priya-n]\n"
                                       "  Due 2026-10-06 (2 business days after 2026-10-02)\n")
    assert outputs["flagged"].stdout == outputs["plain"].stdout + "  Ids checked on 1 branch(es)\n"
    assert outputs["flagged"].stderr == outputs["plain"].stderr == ""


def test_the_text_line_counts_branches_actually_read(repo):
    git(repo, "branch", "third")
    proc = run(open_args("--all-branches"), repo)
    assert "  Ids checked on 3 branch(es)" in proc.stdout.splitlines()


def test_without_the_flag_stdout_has_no_branch_line(repo):
    proc = run(open_args(), repo)
    assert "Ids checked" not in proc.stdout
    assert proc.stderr == ""


# --- the same flag in the other mode, and the rest of the verb ---

def test_state_mode_scans_from_the_repo_root(repo):
    (repo / ".sdlc" / "state.yaml").write_text("x: 1\n", encoding="utf-8")
    proc = run(["open", "--state", ".sdlc/state.yaml", "--decision", "x", "--owner", "@priya-n",
                "--json", "--all-branches"], repo)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["id"] == "DL-08"


def test_a_log_in_a_subdirectory_project_is_found_on_other_branches(tmp_path):
    """The repository root is not the project root: paths are read relative to the project."""
    root = tmp_path / "mono"
    project = root / "proj"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    commit(root, log_text(1, 2), "master log", rel="proj/.sdlc/decision-log.md")
    git(root, "checkout", "-q", "-b", "feature")
    commit(root, log_text(1, 2, 5), "feature log", rel="proj/.sdlc/decision-log.md")
    git(root, "checkout", "-q", "master")
    assert open_json(project, "--all-branches")["id"] == "DL-06"


def test_a_root_level_decision_log_is_scanned_at_its_own_path(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    commit(root, log_text(1), "master log", rel="decision-log.md")
    git(root, "checkout", "-q", "-b", "feature")
    commit(root, log_text(1, 6), "feature log", rel="decision-log.md")
    git(root, "checkout", "-q", "master")
    doc = open_json(root, "--all-branches")
    assert doc["id"] == "DL-07"
    assert doc["path"] == "decision-log.md"


def test_a_refusal_with_the_flag_still_exits_1_and_leaves_the_log_alone(repo):
    proc = run(["open", "--repo", ".", "--decision", "  ", "--owner", "@priya-n", "--all-branches"], repo)
    assert proc.returncode == 1
    assert "must not be empty" in proc.stderr
    assert (repo / LOG).read_text(encoding="utf-8") == log_text(1, 2, 3)


def test_decide_is_unaffected_by_the_new_flag_existing(repo):
    proc = run(["decide", "--repo", ".", "--id", "DL-01", "--by", "@priya-n",
                "--resolution", "Fail closed", "--json"], repo)
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(proc.stdout)
    assert set(doc) == {"id", "status", "decided", "by", "path"}


def test_help_names_the_flag_says_to_fetch_first_and_touches_no_filesystem(tmp_path):
    proc = run(["open", "--help"], tmp_path)
    assert proc.returncode == 0
    assert "--all-branches" in proc.stdout
    assert "git fetch" in " ".join(proc.stdout.split())
    assert list(tmp_path.iterdir()) == []
