"""Tests for doctor.py's `--json` mode (spec 0021) and the proof its text mode did not move.

Two promises are pinned here:

  * Without `--json`, the report is byte-identical to what the script printed before the flag
    existed. The golden files under `fixtures/golden/doctor-*.txt` were captured from the
    unmodified script. The doctor reports on the machine it runs on (which tools are installed,
    where) — so the goldens are taken with the machine pinned: tool lookup, the platform and the
    gh calls are replaced, and the fixture repo path is normalised.
  * With `--json`, stdout is exactly one JSON document, the exit code is the text mode's, and the
    `fix` of every non-passing check is the very line the text mode prints for it.
"""

import json
import subprocess
import sys
from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import doctor
from tests.golden_support import SCRIPTS_DIR, golden_path, normalise, read_golden

GH_SECRETS = json.dumps([{"name": "ANTHROPIC_API_KEY"}])
GH_RULESETS = json.dumps([{"name": "main", "enforcement": "active"}])
WORKFLOW = "jobs:\n  grade:\n    env:\n      KEY: ${{ secrets.ANTHROPIC_API_KEY }}\n"


# ── fixture repos ─────────────────────────────────────────────────────────────

def _installed(root: Path) -> Path:
    (root / ".claude" / "hooks").mkdir(parents=True)
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "CLAUDE.md").write_text("# rules\n", encoding="utf-8")
    (root / ".claude" / "harness-manifest.json").write_text(
        json.dumps({"profile_id": "test", "packs": ["cicd/github"], "files": {"CLAUDE.md": "x"}}),
        encoding="utf-8")
    (root / ".claude" / "settings.json").write_text(json.dumps({
        "hooks": {"Stop": [{"hooks": [{
            "type": "command", "command": "pwsh",
            "args": ["-File", "${CLAUDE_PROJECT_DIR}/.claude/hooks/stop-gate.ps1"],
        }]}]}}), encoding="utf-8")
    (root / ".github" / "workflows" / "grade.yml").write_text(WORKFLOW, encoding="utf-8")
    return root


def build_case(case: str, root: Path) -> tuple[Path, dict]:
    """Return (repo, options) for a named situation. Options: offline, pwsh, posix."""
    repo = root / "repo"
    repo.mkdir(parents=True)
    if case == "no-harness-offline":
        return repo, {"offline": True}
    _installed(repo)
    if case == "installed-failure-offline":
        # No stop-gate.ps1 on disk, pwsh not found, and a token the installer left unfilled.
        (repo / ".github" / "workflows" / "ci.yml").write_text(
            "paths: <<GATED_PATHS>>\n", encoding="utf-8")
        return repo, {"offline": True, "pwsh": False}
    (repo / ".claude" / "hooks" / "stop-gate.ps1").write_text("# hook\n", encoding="utf-8")
    if case == "installed-warn-online":
        return repo, {"offline": False}
    if case == "all-passed-online":
        (repo / ".claude" / "hooks" / "gate.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (repo / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"context7": {}}}), encoding="utf-8")
        return repo, {"offline": False, "posix": True}
    raise KeyError(case)


CASES = ["no-harness-offline", "installed-failure-offline", "installed-warn-online",
         "all-passed-online"]


@contextmanager
def pinned_machine(options: dict):
    """The doctor reads the machine; pin it so a report is the same everywhere."""
    def which(tool):
        return None if tool == "pwsh" and options.get("pwsh") is False else f"/fake/bin/{tool}"

    def run(cmd, timeout=30, cwd=None):
        return (0, GH_SECRETS) if cmd[:3] == ["gh", "secret", "list"] else (0, GH_RULESETS)

    os_stub = (SimpleNamespace(name="posix", access=lambda p, m: True, X_OK=1)
               if options.get("posix") else SimpleNamespace(name="nt"))
    with patch.object(doctor, "shutil", SimpleNamespace(which=which)), \
            patch.object(doctor, "os", os_stub), patch.object(doctor, "_run", run):
        yield


def run_text(case: str, root: Path) -> str:
    """The text report plus exit code, in the golden-file format, for one situation."""
    repo, options = build_case(case, root)
    out = StringIO()
    with pinned_machine(options), redirect_stdout(out):
        rc = doctor.run(repo, offline=options["offline"])
    return f"exit: {rc}\n--- stdout ---\n{normalise(out.getvalue(), repo)}"


def run_json(case: str, root: Path) -> tuple[int, str]:
    repo, options = build_case(case, root)
    out = StringIO()
    with pinned_machine(options), redirect_stdout(out):
        rc = doctor.run(repo, offline=options["offline"], as_json=True)
    return rc, out.getvalue()


# ── the text mode did not move ────────────────────────────────────────────────

@pytest.mark.parametrize("case", CASES)
def test_text_mode_is_byte_identical_to_the_golden_capture(case, tmp_path):
    assert golden_path(f"doctor-{case}").exists()
    assert run_text(case, tmp_path) == read_golden(f"doctor-{case}")


# ── the JSON mode ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("case", CASES)
def test_json_is_exactly_one_document_with_the_text_modes_exit_code(case, tmp_path):
    text_rc = int(run_text(case, tmp_path / "a").split("\n", 1)[0].removeprefix("exit: "))
    rc, stdout = run_json(case, tmp_path / "b")
    doc = json.loads(stdout)
    assert stdout == json.dumps(doc, indent=2) + "\n"
    assert rc == text_rc
    assert doc["ok"] == (rc == 0)


@pytest.mark.parametrize("case", CASES)
def test_json_checks_carry_the_text_modes_fix_lines(case, tmp_path):
    """`fix` is the line the text mode prints — and null where it prints none."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    text = run_text(case, tmp_path / "a")
    _, stdout = run_json(case, tmp_path / "b")
    doc = json.loads(stdout)
    for check in doc["checks"]:
        assert set(check) == {"name", "status", "detail", "fix"}
        assert check["status"] in {"PASS", "FAIL", "WARN"}
        if check["fix"] is None:
            continue
        assert check["status"] != "PASS"
        assert f"fix: {check['fix']}" in text
    printed_fixes = text.count("fix: ")
    assert printed_fixes == sum(1 for c in doc["checks"] if c["fix"] is not None)


@pytest.mark.parametrize("case", CASES)
def test_json_summary_counts_match_the_checks(case, tmp_path):
    _, stdout = run_json(case, tmp_path)
    doc = json.loads(stdout)
    for status in ("PASS", "FAIL", "WARN"):
        assert doc["summary"][status.lower()] == sum(
            1 for c in doc["checks"] if c["status"] == status)


def test_no_harness_reports_installed_false_and_points_at_setup(tmp_path):
    rc, stdout = run_json("no-harness-offline", tmp_path)
    doc = json.loads(stdout)
    assert rc == 1 and doc["ok"] is False
    assert doc["harness_installed"] is False
    assert "/sprd-setup" in doc["message"]


def test_installed_harness_has_no_message(tmp_path):
    rc, stdout = run_json("all-passed-online", tmp_path)
    doc = json.loads(stdout)
    assert rc == 0 and doc["ok"] is True
    assert doc["harness_installed"] is True and doc["message"] is None
    assert doc["summary"]["fail"] == 0 and doc["summary"]["warn"] == 0


def test_a_failure_in_the_checks_makes_ok_false_and_exit_one(tmp_path):
    rc, stdout = run_json("installed-failure-offline", tmp_path)
    doc = json.loads(stdout)
    assert rc == 1 and doc["ok"] is False
    assert doc["summary"]["fail"] >= 1
    failing = [c for c in doc["checks"] if c["status"] == "FAIL"]
    assert any("pwsh" in c["name"] for c in failing)


def test_offline_drops_the_network_checks_and_says_so(tmp_path):
    _, offline = run_json("installed-failure-offline", tmp_path / "x")
    names = " | ".join(c["name"] for c in json.loads(offline)["checks"])
    assert "secret" not in names and "ruleset" not in names
    assert json.loads(offline)["skipped"] == ["Repo secrets", "Branch protection"]

    _, online = run_json("installed-warn-online", tmp_path / "y")
    online_doc = json.loads(online)
    names = " | ".join(c["name"] for c in online_doc["checks"])
    assert "secret ANTHROPIC_API_KEY set" in names and "active ruleset" in names
    assert online_doc["skipped"] == []


# ── the real script, as a subprocess ──────────────────────────────────────────

def _subprocess(repo: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "doctor.py"), "--repo", str(repo), *flags],
        capture_output=True, text=True, encoding="utf-8")


def test_subprocess_json_on_a_bare_repo_is_one_document_and_exit_one(tmp_path):
    proc = _subprocess(tmp_path, "--offline", "--json")
    doc = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert doc["harness_installed"] is False
    assert "/sprd-setup" in doc["message"]
    assert proc.stderr == ""


def test_subprocess_exit_code_is_the_same_with_and_without_json(tmp_path):
    plain = _subprocess(tmp_path, "--offline")
    flagged = _subprocess(tmp_path, "--offline", "--json")
    assert plain.returncode == flagged.returncode == 1
    assert plain.stdout.startswith("/sprd-doctor")
