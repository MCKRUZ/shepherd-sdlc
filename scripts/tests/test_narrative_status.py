"""narrative_status.py — the read-only coverage check behind /sprd-enhance (spec 0022).

What these protect:
  * STALENESS COMES FROM GIT COMMIT TIME, NOT FILE TIME. A checkout resets mtimes, so the tests
    commit with controlled dates and then set mtimes the OPPOSITE way round to prove they are ignored.
  * NEVER A GUESS. Where git cannot answer (not a repo, untracked file) the answer is null.
  * ADVISORY AND DETERMINISTIC. Exit 0 on every data path, exit 2 only on a usage error, exactly one
    JSON document with --json, byte-identical output across runs.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "narrative_status.py"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed; staleness needs it")

OLD = "2026-01-01T10:00:00+00:00"
MID = "2026-02-01T10:00:00+00:00"
NEW = "2026-03-01T10:00:00+00:00"


def run(*args, cwd=None, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          encoding="utf-8", env=env or ENV, cwd=cwd)


def report(*args, **kw):
    proc = run(*args, "--json", **kw)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def git(repo, *args, when=None):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True)


def commit(repo, paths, when):
    git(repo, "add", "--", *[str(p) for p in paths])
    git(repo, "commit", "-m", "x", "--no-gpg-sign", when=when)


def write(path, text="# doc\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_project(tmp_path, phase="2", init_git=True):
    root = tmp_path / "proj"
    (root / ".sdlc" / "artifacts").mkdir(parents=True)
    (root / ".sdlc" / "state.yaml").write_text(f'current_phase: "{phase}"\n', encoding="utf-8")
    if init_git:
        git(root, "init", "-q")
        git(root, "config", "user.name", "T")
        git(root, "config", "user.email", "t@example.com")
    return root


def art(root, phase_dir, name):
    return root / ".sdlc" / "artifacts" / phase_dir / name


def by_name(result, phase="02-design"):
    block = next(p for p in result["phases"] if p["phase"] == phase)
    return {a["name"]: a for a in block["artifacts"]}


class TestListing:
    def test_artifact_without_a_companion_is_none_and_one_with_is_present(self, tmp_path):
        root = make_project(tmp_path, init_git=False)
        write(art(root, "02-design", "architecture.md"))
        write(art(root, "02-design", "api-design.md"))
        write(art(root, "02-design", "api-design.narrative.md"))
        result = report("--repo", str(root))
        found = by_name(result)
        assert found["architecture"]["status"] == "none"
        assert found["architecture"]["narrative"] is None
        assert found["api-design"]["status"] == "present"
        assert found["api-design"]["narrative"] == ".sdlc/artifacts/02-design/api-design.narrative.md"
        assert found["api-design"]["path"] == ".sdlc/artifacts/02-design/api-design.md"

    def test_a_narrative_is_never_listed_as_a_source(self, tmp_path):
        root = make_project(tmp_path, init_git=False)
        write(art(root, "02-design", "a.md"))
        write(art(root, "02-design", "a.narrative.md"))
        write(art(root, "02-design", "orphan.narrative.md"))
        assert list(by_name(report("--repo", str(root)))) == ["a"]

    def test_subfolders_and_non_markdown_files_are_ignored(self, tmp_path):
        root = make_project(tmp_path, init_git=False)
        write(art(root, "02-design", "a.md"))
        write(art(root, "02-design", "sections/s1.md"))
        write(art(root, "02-design", "diagram.png"), "x")
        assert list(by_name(report("--repo", str(root)))) == ["a"]

    def test_sorted_by_name_regardless_of_creation_order(self, tmp_path):
        root = make_project(tmp_path, init_git=False)
        for n in ("zeta.md", "alpha.md", "mid.md"):
            write(art(root, "02-design", n))
        assert list(by_name(report("--repo", str(root)))) == ["alpha", "mid", "zeta"]

    def test_coverage_counts_artifacts_with_a_companion(self, tmp_path):
        root = make_project(tmp_path, init_git=False)
        for n in ("a.md", "b.md", "c.md", "b.narrative.md"):
            write(art(root, "02-design", n))
        write(art(root, "02-design", "c.narrative.md"))
        result = report("--repo", str(root))
        assert result["coverage"] == {"with_narrative": 2, "total": 3}
        assert result["has_data"] is True


class TestPhaseSelection:
    def project_with_two_phases(self, tmp_path):
        root = make_project(tmp_path, phase="2", init_git=False)
        write(art(root, "01-requirements", "requirements.md"))
        write(art(root, "02-design", "architecture.md"))
        return root

    def test_defaults_to_the_current_phase_from_state(self, tmp_path):
        result = report("--repo", str(self.project_with_two_phases(tmp_path)))
        assert [p["phase"] for p in result["phases"]] == ["02-design"]

    def test_phase_flag_picks_another_phase(self, tmp_path):
        result = report("--repo", str(self.project_with_two_phases(tmp_path)), "--phase", "1")
        assert [p["phase"] for p in result["phases"]] == ["01-requirements"]
        assert result["coverage"]["total"] == 1

    def test_all_phases_covers_every_folder_that_exists_in_lifecycle_order(self, tmp_path):
        root = self.project_with_two_phases(tmp_path)
        result = report("--repo", str(root), "--all-phases")
        assert [p["phase"] for p in result["phases"]] == ["01-requirements", "02-design"]
        assert result["coverage"]["total"] == 2

    def test_phase_and_all_phases_together_is_a_usage_error(self, tmp_path):
        root = self.project_with_two_phases(tmp_path)
        assert run("--repo", str(root), "--phase", "1", "--all-phases").returncode == 2

    def test_phase_flag_needs_no_state_file(self, tmp_path):
        root = self.project_with_two_phases(tmp_path)
        (root / ".sdlc" / "state.yaml").unlink()
        assert report("--repo", str(root), "--phase", "2")["has_data"] is True

    def test_unknown_phase_reports_no_data_with_a_note(self, tmp_path):
        result = report("--repo", str(self.project_with_two_phases(tmp_path)), "--phase", "42")
        assert result["has_data"] is False
        assert result["phases"] == []
        assert "unknown phase" in result["notes"][0]


class TestMissingData:
    def test_no_sdlc_folder_is_no_data_and_exit_zero(self, tmp_path):
        proc = run("--repo", str(tmp_path), "--json")
        assert proc.returncode == 0
        result = json.loads(proc.stdout)
        assert result["has_data"] is False
        assert result["phases"] == []
        assert len(result["notes"]) == 1

    def test_no_state_file_is_no_data_and_exit_zero(self, tmp_path):
        root = make_project(tmp_path, init_git=False)
        (root / ".sdlc" / "state.yaml").unlink()
        write(art(root, "02-design", "a.md"))
        result = report("--repo", str(root))
        assert result["has_data"] is False
        assert "state file" in result["notes"][0]

    def test_phase_folder_that_does_not_exist_is_no_data(self, tmp_path):
        root = make_project(tmp_path, phase="3", init_git=False)
        result = report("--repo", str(root))
        assert result["has_data"] is False
        assert result["phases"] == []

    def test_empty_phase_folder_is_no_data_not_a_clean_bill(self, tmp_path):
        root = make_project(tmp_path, init_git=False)
        art(root, "02-design", "x").parent.mkdir(parents=True)
        result = report("--repo", str(root))
        assert result["has_data"] is False
        assert result["coverage"]["total"] == 0

    def test_text_mode_also_exits_zero_on_missing_input(self, tmp_path):
        proc = run("--repo", str(tmp_path))
        assert proc.returncode == 0
        assert "Narrative Coverage" in proc.stdout


class TestStateAndRepo:
    def test_state_and_repo_give_the_same_answer(self, tmp_path):
        root = make_project(tmp_path, init_git=False)
        write(art(root, "02-design", "a.md"))
        via_repo = report("--repo", str(root))
        via_state = report("--state", str(root / ".sdlc" / "state.yaml"))
        assert via_repo == via_state

    def test_both_flags_is_a_usage_error(self, tmp_path):
        root = make_project(tmp_path, init_git=False)
        assert run("--repo", str(root), "--state", str(root / ".sdlc" / "state.yaml")).returncode == 2

    def test_neither_flag_is_a_usage_error(self):
        assert run().returncode == 2


@needs_git
class TestStaleness:
    def test_source_committed_after_the_narrative_is_stale(self, tmp_path):
        root = make_project(tmp_path)
        src, nar = write(art(root, "02-design", "a.md")), write(art(root, "02-design", "a.narrative.md"))
        commit(root, [nar], OLD)
        commit(root, [src], NEW)
        assert by_name(report("--repo", str(root)))["a"]["stale"] is True

    def test_narrative_committed_after_the_source_is_fresh(self, tmp_path):
        root = make_project(tmp_path)
        src, nar = write(art(root, "02-design", "a.md")), write(art(root, "02-design", "a.narrative.md"))
        commit(root, [src], OLD)
        commit(root, [nar], NEW)
        assert by_name(report("--repo", str(root)))["a"]["stale"] is False

    def test_same_commit_is_not_stale(self, tmp_path):
        root = make_project(tmp_path)
        src, nar = write(art(root, "02-design", "a.md")), write(art(root, "02-design", "a.narrative.md"))
        commit(root, [src, nar], MID)
        assert by_name(report("--repo", str(root)))["a"]["stale"] is False

    def test_a_later_edit_to_the_source_makes_an_old_fresh_narrative_stale(self, tmp_path):
        root = make_project(tmp_path)
        src, nar = write(art(root, "02-design", "a.md")), write(art(root, "02-design", "a.narrative.md"))
        commit(root, [src, nar], OLD)
        src.write_text("# changed\n", encoding="utf-8")
        commit(root, [src], NEW)
        assert by_name(report("--repo", str(root)))["a"]["stale"] is True

    def test_file_modification_times_are_ignored(self, tmp_path):
        root = make_project(tmp_path)
        src, nar = write(art(root, "02-design", "a.md")), write(art(root, "02-design", "a.narrative.md"))
        commit(root, [src], OLD)
        commit(root, [nar], NEW)
        os.utime(nar, (1_000_000_000, 1_000_000_000))  # narrative looks ancient on disk
        os.utime(src, (2_000_000_000, 2_000_000_000))  # source looks brand new on disk
        assert by_name(report("--repo", str(root)))["a"]["stale"] is False

    def test_uncommitted_source_is_null(self, tmp_path):
        root = make_project(tmp_path)
        write(art(root, "02-design", "a.md"))
        nar = write(art(root, "02-design", "a.narrative.md"))
        commit(root, [nar], OLD)
        assert by_name(report("--repo", str(root)))["a"]["stale"] is None

    def test_uncommitted_narrative_is_null(self, tmp_path):
        root = make_project(tmp_path)
        src = write(art(root, "02-design", "a.md"))
        write(art(root, "02-design", "a.narrative.md"))
        commit(root, [src], OLD)
        assert by_name(report("--repo", str(root)))["a"]["stale"] is None

    def test_unknown_staleness_is_explained_in_notes(self, tmp_path):
        root = make_project(tmp_path)
        write(art(root, "02-design", "a.md"))
        write(art(root, "02-design", "a.narrative.md"))
        notes = report("--repo", str(root))["notes"]
        assert any("staleness unknown" in n for n in notes)

    def test_no_narrative_means_stale_is_null_not_false(self, tmp_path):
        root = make_project(tmp_path)
        src = write(art(root, "02-design", "a.md"))
        commit(root, [src], OLD)
        assert by_name(report("--repo", str(root)))["a"]["stale"] is None

    def test_not_a_git_repo_is_null(self, tmp_path):
        root = make_project(tmp_path, init_git=False)
        write(art(root, "02-design", "a.md"))
        write(art(root, "02-design", "a.narrative.md"))
        ceiling = {**ENV, "GIT_CEILING_DIRECTORIES": str(tmp_path)}  # never discover an enclosing repo
        result = report("--repo", str(root), env=ceiling)
        assert by_name(result)["a"]["stale"] is None

    def test_git_missing_from_path_is_null_not_an_error(self, tmp_path):
        root = make_project(tmp_path)
        src, nar = write(art(root, "02-design", "a.md")), write(art(root, "02-design", "a.narrative.md"))
        commit(root, [src, nar], OLD)
        bare = {**ENV, "PATH": str(Path(sys.executable).parent)}
        proc = run("--repo", str(root), "--json", env=bare)
        assert proc.returncode == 0
        assert by_name(json.loads(proc.stdout))["a"]["stale"] is None


class TestOutputContract:
    def project(self, tmp_path):
        root = make_project(tmp_path, init_git=False)
        write(art(root, "02-design", "a.md"))
        write(art(root, "02-design", "a.narrative.md"))
        write(art(root, "02-design", "b.md"))
        return root

    def test_json_mode_prints_exactly_one_document_and_nothing_else(self, tmp_path):
        proc = run("--repo", str(self.project(tmp_path)), "--json")
        assert proc.returncode == 0
        decoder = json.JSONDecoder()
        doc, end = decoder.raw_decode(proc.stdout)
        assert proc.stdout[end:].strip() == ""
        assert isinstance(doc, dict)

    def test_json_has_the_documented_shape(self, tmp_path):
        result = report("--repo", str(self.project(tmp_path)))
        assert set(result) == {"has_data", "notes", "phases", "coverage"}
        assert set(result["coverage"]) == {"with_narrative", "total"}
        assert set(result["phases"][0]) == {"phase", "artifacts"}
        assert set(result["phases"][0]["artifacts"][0]) == {"name", "path", "status", "narrative", "stale"}

    def test_output_is_byte_identical_across_runs(self, tmp_path):
        root = self.project(tmp_path)
        for flags in ([], ["--json"]):
            first = run("--repo", str(root), *flags)
            second = run("--repo", str(root), *flags)
            assert first.stdout == second.stdout

    def test_text_report_names_each_artifact_and_the_coverage(self, tmp_path):
        out = run("--repo", str(self.project(tmp_path))).stdout
        assert "a: narrative present" in out
        assert "b: no narrative" in out
        assert "Coverage: 1/2" in out

    def test_running_it_writes_nothing_to_the_project(self, tmp_path):
        root = self.project(tmp_path)
        before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
        run("--repo", str(root), "--all-phases", "--json")
        assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before
