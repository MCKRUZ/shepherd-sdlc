"""The session-start hook twins: the `[SHEPHERD-SPRINT]` line and the retired section-plan block.

The first test of the hook itself. It runs the real scripts via subprocess with cwd = a tmp
project that holds `.sdlc/state.yaml` (+ `profile.yaml`) from conftest's `state_yaml` fixture,
exactly the way Claude Code invokes them. The bash twin always runs; the PowerShell twin runs
only when `pwsh` is on PATH (skipped otherwise) and must print identical `[SHEPHERD-SPRINT]` and
`[SHEPHERD-PHASE]` lines after `\\r\\n` normalisation — the two scripts share one output contract.

What the sprint layer asked of the hook (proposal §3 R5):

- `[SHEPHERD-SPRINT] S07 (ready) — "<goal>" — <start> → <end>` appears iff an active (not closed)
  sprint record exists under `.sdlc/sprints/`; prior lines are byte-identical either way;
- a malformed sprint file is silent — exit 0, no line, no stderr — because a thrown error in
  the pwsh twin would fall through `pwsh … || bash …` and double-print the banner;
- the Build reminder carries the refinement clause;
- the retired `[SHEPHERD] Session Handoff:` section-plan summary is gone even when a legacy
  `session-handoff.json` is still present.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

HOOKS_DIR = Path(__file__).resolve().parents[2] / "hooks"
BASH_HOOK = HOOKS_DIR / "shepherd-session-start.sh"
PS1_HOOK = HOOKS_DIR / "shepherd-session-start.ps1"
PWSH = shutil.which("pwsh")


def _bash() -> str | None:
    """The bash that can actually run the hook (mirrors test_review_gate_hook.py).

    On Windows, PATH's `bash` is System32's WSL shim, which on CI runners (no distro
    installed) prints "Windows Subsystem for Linux has no installed distributions" and
    exits 1 — it never runs the script at all. Git Bash is the bash a real Windows
    install executes hooks with, so resolve it explicitly and never fall back to the shim.
    """
    if os.name != "nt":
        return shutil.which("bash")
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(var)
        if base and (Path(base) / "Git" / "bin" / "bash.exe").is_file():
            return str(Path(base) / "Git" / "bin" / "bash.exe")
    git = shutil.which("git")
    if git:  # <git-root>/cmd/git.exe -> <git-root>/bin/bash.exe
        cand = Path(git).parent.parent / "bin" / "bash.exe"
        if cand.is_file():
            return str(cand)
    found = shutil.which("bash")
    return None if found and "system32" in found.lower() else found


BASH = _bash()
pytestmark = pytest.mark.skipif(
    BASH is None, reason="shepherd-session-start.sh needs bash (Git Bash on Windows)"
)

SPRINT_TAG = "[SHEPHERD-SPRINT]"
PHASE_TAG = "[SHEPHERD-PHASE]"
REFINE_CLAUSE = "Refinement for the next sprint runs alongside — /sprd-refine; the board is /sprd-sprint."
RETIRED_MARKERS = ("Session Handoff", "[SHEPHERD] Context:", "[SHEPHERD] Next action:", "active blocker")

# The templates/phases/build/sprint.md shape: quoted values, and unquoted `state:` with a trailing comment.
READY_SPRINT = """---
sprint: "S07"
goal: "Ship the duplicate-claim rail"
start: "2026-09-28"
end: "2026-10-09"            # default: start + 10 business days
state: ready              # planning | ready | closed
target: 6                    # how many specs to slate (a count, never a size)
mix: "HIGH:1,MEDIUM:2,LOW:3"
board_ref: "ADO Iteration 6"
readied_by: "Priya"
closed_by: ""
created: "2026-09-24"
---
# Sprint S07

## Goal
Ship the duplicate-claim rail.

## Slate
<!-- Rendered by `sprint.py status` from spec frontmatter — never hand-edit. -->

## Close
<!-- Written by `sprint.py close` -->
"""
READY_LINE = '[SHEPHERD-SPRINT] S07 (ready) — "Ship the duplicate-claim rail" — 2026-09-28 → 2026-10-09'

CLOSED_SPRINT = READY_SPRINT.replace('"S07"', '"S06"').replace("state: ready ", "state: closed").replace(
    'closed_by: ""', 'closed_by: "Priya"'
)

LEGACY_HANDOFF = """{
  "$schema": "session-handoff-v1",
  "session_number": 3,
  "sections": [{"id": "SECTION-001", "status": "complete"}, {"id": "SECTION-002", "status": "in_progress"}],
  "context_for_next_session": "wire the gateway next",
  "next_actions": [{"action": "Implement routes", "section": "SECTION-002"}],
  "blockers": [{"id": "B1", "resolved": false}]
}
"""


# --------------------------------------------------------------------------- helpers


def _run(cmd: list[str], project: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PWD": str(project)}
    return subprocess.run(
        cmd, cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
    )


def run_bash(project: Path) -> subprocess.CompletedProcess:
    return _run([BASH, str(BASH_HOOK)], project)


def run_pwsh(project: Path) -> subprocess.CompletedProcess:
    return _run([PWSH, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PS1_HOOK)], project)


def lines(out: str) -> list[str]:
    return out.replace("\r\n", "\n").rstrip("\n").split("\n") if out.strip() else []


def sprint_lines(out: str) -> list[str]:
    return [line for line in lines(out) if line.startswith(SPRINT_TAG)]


def phase_line(out: str) -> str:
    found = [line for line in lines(out) if line.startswith(PHASE_TAG)]
    assert len(found) == 1, found
    return found[0]


def set_phase(state_path: Path, phase_id: str, phase_name: str) -> None:
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state["current_phase"] = phase_id
    state["phase_name"] = phase_name
    state_path.write_text(yaml.dump(state, default_flow_style=False), encoding="utf-8")


@pytest.fixture
def project(state_yaml):
    """Repo root of the fixture project (state_yaml lives at <root>/.sdlc/state.yaml)."""
    return state_yaml.parent.parent


def write_sprint(project: Path, name: str, text: str | bytes) -> Path:
    sprints = project / ".sdlc" / "sprints"
    sprints.mkdir(parents=True, exist_ok=True)
    path = sprints / name
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8", newline="")
    return path


# --------------------------------------------------------------------------- bash twin


def test_no_sprints_dir_prints_no_sprint_line(project):
    proc = run_bash(project)

    assert proc.returncode == 0
    assert proc.stderr == ""
    assert lines(proc.stdout)[0].startswith("[SHEPHERD] Project: test-project")  # the hook actually ran
    assert sprint_lines(proc.stdout) == []
    assert not (project / ".sdlc" / "sprints").exists()  # the hook is read-only: it created nothing


def test_empty_sprints_dir_is_silent(project):
    (project / ".sdlc" / "sprints").mkdir()
    proc = run_bash(project)

    assert proc.returncode == 0
    assert proc.stderr == ""
    assert sprint_lines(proc.stdout) == []


def test_one_ready_one_closed_prints_exactly_one_line_and_leaves_prior_lines_unchanged(project):
    baseline = run_bash(project)
    assert baseline.returncode == 0

    write_sprint(project, "S06.md", CLOSED_SPRINT)
    write_sprint(project, "S07.md", READY_SPRINT)
    proc = run_bash(project)

    assert proc.returncode == 0
    assert proc.stderr == ""
    assert sprint_lines(proc.stdout) == [READY_LINE]
    others = [line for line in lines(proc.stdout) if not line.startswith(SPRINT_TAG)]
    assert others == lines(baseline.stdout)


def test_sprint_line_sits_directly_after_the_phase_reminder(project):
    # Anchor on the Build phase: conftest's yaml.dump single-quotes the '0' phase id, which the
    # hook's (deliberately unchanged) double-quote-only state regex does not unwrap, so Phase 0
    # prints no [SHEPHERD-PHASE] reminder in this fixture. `build` is written bare and always does.
    set_phase(project / ".sdlc" / "state.yaml", "build", "build")
    write_sprint(project, "S07.md", READY_SPRINT)
    out = lines(run_bash(project).stdout)

    idx = out.index(READY_LINE)
    assert out[idx - 1].startswith(PHASE_TAG)
    assert out[idx - 2].startswith("[SHEPHERD] Commands:")


def test_planning_sprints_show_too_in_filename_order_and_the_line_is_not_phase_gated(project):
    # Phase 0 — refinement for the next sprint runs in any phase where specs exist.
    assert yaml.safe_load((project / ".sdlc" / "state.yaml").read_text())["current_phase"] == "0"
    write_sprint(project, "S08.md", READY_SPRINT.replace('"S07"', '"S08"').replace("state: ready ", "state: planning"))
    write_sprint(project, "S07.md", READY_SPRINT)

    got = sprint_lines(run_bash(project).stdout)

    assert got == [READY_LINE, READY_LINE.replace("S07 (ready)", "S08 (planning)")]


def test_crlf_authored_record_and_unquoted_values_read_the_same(project):
    crlf = (
        "---\r\nsprint: S10\r\ngoal: \"CRLF authored\"\r\nstart: 2026-10-12   # typed\r\n"
        "end: 2026-10-23\r\nstate: planning\r\n---\r\n# Sprint S10\r\n"
    ).encode("utf-8")
    write_sprint(project, "S10.md", crlf)

    got = sprint_lines(run_bash(project).stdout)

    assert got == ['[SHEPHERD-SPRINT] S10 (planning) — "CRLF authored" — 2026-10-12 → 2026-10-23']


def test_missing_sprint_id_falls_back_to_the_filename(project):
    write_sprint(project, "S11.md", "---\ngoal: \"\"\nstart: \"\"\nend: \"\"\nstate: planning\n---\n")

    got = sprint_lines(run_bash(project).stdout)

    assert got == ['[SHEPHERD-SPRINT] S11 (planning) — "" —  → ']


@pytest.mark.parametrize(
    "name, payload",
    [
        ("garbage.md", b"not: yaml: at all\n\x00\x01 garbage \x80\xff\nstate:\n"),
        ("empty-state.md", "---\nsprint: \"S09\"\nstate:\n---\n"),
        ("no-frontmatter.md", "# Sprint S09\n\nJust prose, no keys at all.\n"),
        ("zero-bytes.md", b""),
    ],
)
def test_malformed_sprint_file_is_silent_and_exits_zero(project, name, payload):
    write_sprint(project, name, payload)
    write_sprint(project, "S07.md", READY_SPRINT)  # a good record alongside still prints exactly once

    proc = run_bash(project)

    assert proc.returncode == 0
    assert proc.stderr == ""
    assert "Traceback" not in proc.stdout
    assert sprint_lines(proc.stdout) == [READY_LINE]


def test_build_reminder_carries_the_refinement_clause(project):
    set_phase(project / ".sdlc" / "state.yaml", "build", "build")

    out = run_bash(project).stdout

    assert phase_line(out).endswith(REFINE_CLAUSE)
    assert phase_line(out).startswith("[SHEPHERD-PHASE] One spec at a time: Intent -> Delegate -> Discern.")


def test_other_phase_reminders_do_not_carry_the_clause(project):
    out = run_bash(project).stdout  # phase 0

    assert REFINE_CLAUSE not in out


def test_retired_session_handoff_block_is_gone_even_with_a_legacy_file(project):
    set_phase(project / ".sdlc" / "state.yaml", "build", "build")
    handoff = project / ".sdlc" / "artifacts" / "build" / "session-handoff.json"
    handoff.parent.mkdir(parents=True, exist_ok=True)
    handoff.write_text(LEGACY_HANDOFF, encoding="utf-8")

    proc = run_bash(project)

    assert proc.returncode == 0
    assert proc.stderr == ""
    for marker in RETIRED_MARKERS:
        assert marker not in proc.stdout, marker
    assert "malformed" not in proc.stdout


def test_malformed_legacy_handoff_file_no_longer_warns(project):
    set_phase(project / ".sdlc" / "state.yaml", "build", "build")
    handoff = project / ".sdlc" / "artifacts" / "build" / "session-handoff.json"
    handoff.parent.mkdir(parents=True, exist_ok=True)
    handoff.write_text("{ not json", encoding="utf-8")

    proc = run_bash(project)

    assert proc.returncode == 0
    assert "session-handoff.json" not in proc.stdout


# --------------------------------------------------------------------------- source-level guards


def test_hook_sources_are_lf_only_and_free_of_json_readers():
    sh = BASH_HOOK.read_bytes()
    ps1 = PS1_HOOK.read_bytes()

    # Only the shell script must be LF (.gitattributes forces `*.sh text eol=lf`; bash chokes on
    # CRLF). The .ps1 is left to the platform default and legitimately checks out CRLF on Windows.
    assert b"\r" not in sh
    for needle in (b"jq", b"python", b"session-handoff", b"Session Handoff", b"PYEOF"):
        assert needle not in sh, needle
    for needle in (b"ConvertFrom-Json", b"session-handoff", b"Session Handoff"):
        assert needle not in ps1, needle
    assert REFINE_CLAUSE.encode("utf-8") in sh
    assert REFINE_CLAUSE.encode("utf-8") in ps1
    assert b"[SHEPHERD-SPRINT]" in sh and b"[SHEPHERD-SPRINT]" in ps1
    # The closing context tags moved with their openers in the Shepherd rename, and no old
    # marker may creep back into either twin when `scripts/dev/rename_brand.py` is replayed.
    for closer in (b"[/SHEPHERD-CONTEXT:LAYER]", b"[/SHEPHERD-CONTEXT:INTAKE-INDEX]"):
        assert closer in sh and closer in ps1, closer
    for stale in (b"[SDLC", b"[/SDLC"):
        assert stale not in sh and stale not in ps1, stale


def test_ps1_sprint_block_never_throws():
    """A thrown error would fall through `pwsh … || bash …` and double-print the banner."""
    ps1 = PS1_HOOK.read_text(encoding="utf-8")
    block = ps1[ps1.index("# --- Active sprints") : ps1.index("# --- Tier 1: Foundation Context ---")]

    assert "try {" in block and "} catch { }" in block
    assert "-ErrorAction SilentlyContinue" in block


# --------------------------------------------------------------------------- pwsh twin


pwsh_only = pytest.mark.skipif(PWSH is None, reason="pwsh not on PATH; the PowerShell twin cannot be exercised here")


@pwsh_only
def test_pwsh_twin_prints_identical_sprint_and_phase_lines(project):
    set_phase(project / ".sdlc" / "state.yaml", "build", "build")
    write_sprint(project, "S06.md", CLOSED_SPRINT)
    write_sprint(project, "S07.md", READY_SPRINT)
    write_sprint(project, "S08.md", READY_SPRINT.replace('"S07"', '"S08"').replace("state: ready ", "state: planning"))

    bash = run_bash(project)
    pwsh = run_pwsh(project)

    assert pwsh.returncode == 0, pwsh.stderr
    assert sprint_lines(pwsh.stdout) == sprint_lines(bash.stdout) == [
        READY_LINE,
        READY_LINE.replace("S07 (ready)", "S08 (planning)"),
    ]
    assert phase_line(pwsh.stdout) == phase_line(bash.stdout)
    assert lines(pwsh.stdout)[0] == lines(bash.stdout)[0]


@pwsh_only
def test_pwsh_twin_is_silent_on_malformed_files_and_never_throws(project):
    write_sprint(project, "garbage.md", b"not: yaml: at all\n\x00\x01 garbage \x80\xff\nstate:\n")
    write_sprint(project, "empty-state.md", "---\nsprint: \"S09\"\nstate:\n---\n")
    write_sprint(project, "S07.md", READY_SPRINT)

    pwsh = run_pwsh(project)

    assert pwsh.returncode == 0, pwsh.stderr
    assert pwsh.stderr.strip() == ""
    assert sprint_lines(pwsh.stdout) == [READY_LINE]


@pwsh_only
def test_pwsh_twin_no_longer_prints_the_retired_handoff_summary(project):
    set_phase(project / ".sdlc" / "state.yaml", "build", "build")
    handoff = project / ".sdlc" / "artifacts" / "build" / "session-handoff.json"
    handoff.parent.mkdir(parents=True, exist_ok=True)
    handoff.write_text(LEGACY_HANDOFF, encoding="utf-8")

    pwsh = run_pwsh(project)

    assert pwsh.returncode == 0, pwsh.stderr
    for marker in RETIRED_MARKERS:
        assert marker not in pwsh.stdout, marker
