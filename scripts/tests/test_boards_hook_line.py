"""The `[SHEPHERD-ADO]` session-start line, the `/sprd-ado` command file and their two doc rows (B2-P6).

The Azure Boards mirror keeps one line of status for the session-start hook: `plan` and `pull` write it as line 1
of `.sdlc/ado/local/hook-status.txt` (`ado_sync_model.hook_line`), and both hook twins echo it as

    [SHEPHERD-ADO] 3 rows pending · 1 drifted · as of 2026-10-12T09:02Z

Nothing else. The hook never runs `az`, `uv` or Python, never reads the board, never writes; a missing, empty or
unreadable file is silent, because a thrown error in the PowerShell twin would fall through
`pwsh ... || bash ...` and print the whole banner twice. This module runs the real bash twin against a tmp project
exactly the way Claude Code does (copying the `run_bash` / `run_pwsh` pattern of `test_session_start_hook.py`);
the PowerShell twin runs only when `pwsh` is on PATH, and its block is also checked statically.

It also pins `commands/sprd-ado.md` against the kit's verb table (kit section 4) WITHOUT waiting for the CLI that
implements the read verbs: every `ado_sync.py` invocation in the command's fenced blocks must use a verb and flags
that table lists, the verbs of the first two Folds must all be documented, a command that names a person (`link`,
`adopt`) must carry `--by`, and the command never calls `az` itself. `test_command_contracts.py` then proves the
same invocations against the live `--help` once the CLI verbs have merged.

The status file in every test is written with `hook_line()` (or, once, with the real `write_hook_status`), never
typed by hand, so a change to the golden form reds this module as well as the model's own test.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from ado_sync_config import write_hook_status
from ado_sync_model import hook_line

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / "hooks"
BASH_HOOK = HOOKS_DIR / "shepherd-session-start.sh"
PS1_HOOK = HOOKS_DIR / "shepherd-session-start.ps1"
HOOKS_JSON = HOOKS_DIR / "hooks.json"
COMMAND_DOC = REPO_ROOT / "commands" / "sprd-ado.md"
COMMANDS_REFERENCE = REPO_ROOT / "docs" / "commands.md"
HOOKS_REFERENCE = REPO_ROOT / "docs" / "hooks.md"
PWSH = shutil.which("pwsh")


def _bash() -> str | None:
    """The bash that can actually run the hook (see `test_session_start_hook._bash`).

    On Windows PATH's `bash` is System32's WSL shim, which exits 1 without running the script on a
    runner with no distro installed; Git Bash is what a real install executes hooks with.
    """
    if os.name != "nt":
        return shutil.which("bash")
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(var)
        if base and (Path(base) / "Git" / "bin" / "bash.exe").is_file():
            return str(Path(base) / "Git" / "bin" / "bash.exe")
    git = shutil.which("git")
    if git:
        cand = Path(git).parent.parent / "bin" / "bash.exe"
        if cand.is_file():
            return str(cand)
    found = shutil.which("bash")
    return None if found and "system32" in found.lower() else found


BASH = _bash()
needs_bash = pytest.mark.skipif(BASH is None, reason="shepherd-session-start.sh needs bash (Git Bash on Windows)")
needs_pwsh = pytest.mark.skipif(PWSH is None, reason="pwsh not on PATH; the PowerShell twin cannot be exercised here")

ADO_TAG = "[SHEPHERD-ADO]"
SPRINT_TAG = "[SHEPHERD-SPRINT]"
PHASE_TAG = "[SHEPHERD-PHASE]"
STATUS_REL = Path(".sdlc") / "ado" / "local" / "hook-status.txt"

PULLED = hook_line(3, 1, "2026-10-12T09:02Z")
NEVER_PULLED = hook_line(None, None, None)
SPRINT_RECORD = """---
sprint: "S07"
goal: "Ship the duplicate-claim rail"
start: "2026-09-28"
end: "2026-10-09"
state: ready
---
# Sprint S07
"""
SPRINT_LINE = '[SHEPHERD-SPRINT] S07 (ready) — "Ship the duplicate-claim rail" — 2026-09-28 → 2026-10-09'


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


def ado_lines(out: str) -> list[str]:
    return [line for line in lines(out) if line.startswith(ADO_TAG)]


def write_status(project: Path, content: str | bytes) -> Path:
    path = project / STATUS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return path


def set_phase(project: Path, phase_id: str, phase_name: str) -> None:
    state_path = project / ".sdlc" / "state.yaml"
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state["current_phase"] = phase_id
    state["phase_name"] = phase_name
    state_path.write_text(yaml.dump(state, default_flow_style=False), encoding="utf-8")


def tree(project: Path) -> dict[str, bytes]:
    """Every file under the project and its bytes: proof the hook created, changed and deleted nothing."""
    return {str(p.relative_to(project)): p.read_bytes() for p in sorted(project.rglob("*")) if p.is_file()}


@pytest.fixture
def project(state_yaml):
    """Repo root of the fixture project (state_yaml lives at <root>/.sdlc/state.yaml)."""
    return state_yaml.parent.parent


def test_the_golden_forms_the_hook_must_echo():
    # The status line is built by hook_line() everywhere below; pin the two forms here so a changed golden is
    # named in this module too, not only in the model's test.
    assert PULLED == "3 rows pending · 1 drifted · as of 2026-10-12T09:02Z"
    assert NEVER_PULLED == "no data (never pulled)"


# --------------------------------------------------------------------------- bash twin


@needs_bash
def test_no_status_file_prints_no_ado_line_and_creates_nothing(project):
    before = tree(project)

    proc = run_bash(project)

    assert proc.returncode == 0
    assert proc.stderr == ""
    assert lines(proc.stdout)[0].startswith("[SHEPHERD] Project: test-project")  # the hook actually ran
    assert ado_lines(proc.stdout) == []
    assert ADO_TAG not in proc.stdout
    assert tree(project) == before and not (project / ".sdlc" / "ado").exists()


@needs_bash
def test_status_file_prints_exactly_one_ado_line_with_its_first_line(project):
    write_status(project, PULLED + "\n")

    proc = run_bash(project)

    assert proc.returncode == 0
    assert proc.stderr == ""
    assert ado_lines(proc.stdout) == [f"{ADO_TAG} {PULLED}"]


@needs_bash
def test_a_never_pulled_status_is_echoed_as_words_not_as_a_zero(project):
    write_status(project, NEVER_PULLED + "\n")

    got = ado_lines(run_bash(project).stdout)

    assert got == [f"{ADO_TAG} no data (never pulled)"]


@needs_bash
def test_crlf_file_prints_the_identical_line(project):
    write_status(project, (PULLED + "\r\n").encode("utf-8"))
    crlf = run_bash(project)
    write_status(project, (PULLED + "\n").encode("utf-8"))
    lf = run_bash(project)

    assert ado_lines(crlf.stdout) == ado_lines(lf.stdout) == [f"{ADO_TAG} {PULLED}"]
    assert "\r" not in crlf.stdout  # the carriage return is stripped, not merely hidden by the test's normaliser
    assert crlf.stdout == lf.stdout


@needs_bash
def test_a_file_without_a_trailing_newline_still_prints(project):
    write_status(project, PULLED)

    assert ado_lines(run_bash(project).stdout) == [f"{ADO_TAG} {PULLED}"]


@needs_bash
def test_only_line_one_is_printed(project):
    write_status(project, f"{PULLED}\nsecond line, never shown\r\nthird\n")

    proc = run_bash(project)

    assert ado_lines(proc.stdout) == [f"{ADO_TAG} {PULLED}"]
    assert "second line" not in proc.stdout and "third" not in proc.stdout


@needs_bash
def test_the_status_line_written_by_the_real_writer_is_what_the_hook_prints(project):
    write_hook_status(project, PULLED)

    proc = run_bash(project)

    assert (project / STATUS_REL).read_bytes() == (PULLED + "\n").encode("utf-8")
    assert ado_lines(proc.stdout) == [f"{ADO_TAG} {PULLED}"]


@needs_bash
def test_ado_line_leaves_every_other_line_unchanged(project):
    baseline = run_bash(project)
    write_status(project, PULLED + "\n")

    proc = run_bash(project)

    assert baseline.returncode == proc.returncode == 0
    assert [line for line in lines(proc.stdout) if not line.startswith(ADO_TAG)] == lines(baseline.stdout)


@needs_bash
def test_ado_line_sits_directly_after_the_sprint_lines_and_before_the_context_tiers(project):
    set_phase(project, "build", "build")
    sprints = project / ".sdlc" / "sprints"
    sprints.mkdir()
    (sprints / "S07.md").write_text(SPRINT_RECORD, encoding="utf-8")
    (project / ".sdlc" / "constitution.md").write_text("Principles of the engagement.\n", encoding="utf-8")
    write_status(project, PULLED + "\n")

    out = lines(run_bash(project).stdout)

    at = out.index(f"{ADO_TAG} {PULLED}")
    assert out[at - 1] == SPRINT_LINE
    assert out[at + 1].startswith("[SHEPHERD-CONTEXT:FOUNDATION]")


@needs_bash
def test_without_a_sprint_the_ado_line_follows_the_phase_reminder(project):
    set_phase(project, "build", "build")
    write_status(project, PULLED + "\n")

    out = lines(run_bash(project).stdout)

    at = out.index(f"{ADO_TAG} {PULLED}")
    assert out[at - 1].startswith(PHASE_TAG)


@needs_bash
@pytest.mark.parametrize(
    "payload",
    [b"", b"\n", b"\r\n", b"\n" + PULLED.encode("utf-8") + b"\n"],
    ids=["empty", "newline-only", "crlf-only", "blank-first-line"],
)
def test_a_status_file_with_nothing_on_line_one_is_silent(project, payload):
    write_status(project, payload)

    proc = run_bash(project)

    assert proc.returncode == 0
    assert proc.stderr == ""
    assert lines(proc.stdout)[0].startswith("[SHEPHERD] Project: test-project")
    assert ado_lines(proc.stdout) == []


@needs_bash
def test_binary_garbage_never_throws_and_leaves_the_banner_alone(project):
    baseline = run_bash(project)
    write_status(project, b"\x00\x01 garbage \x80\xff\n")

    proc = run_bash(project)

    assert proc.returncode == 0
    assert proc.stderr == ""
    assert "Traceback" not in proc.stdout
    assert "\x00" not in proc.stdout  # a NUL is dropped, never forwarded (and bash 5 would warn about it)
    assert [line for line in lines(proc.stdout) if not line.startswith(ADO_TAG)] == lines(baseline.stdout)


@needs_bash
def test_a_directory_where_the_file_should_be_is_silent(project):
    (project / STATUS_REL).mkdir(parents=True)

    proc = run_bash(project)

    assert proc.returncode == 0
    assert proc.stderr == ""
    assert ado_lines(proc.stdout) == []


@needs_bash
def test_the_hook_is_read_only_for_the_status_file_and_everything_else(project):
    write_status(project, PULLED + "\n")
    before = tree(project)

    proc = run_bash(project)

    assert proc.returncode == 0
    assert tree(project) == before


@needs_bash
@pytest.mark.skipif(os.name == "nt", reason="PATH shims are POSIX; the source-level guards below cover Windows")
def test_the_hook_never_runs_az_uv_python_or_the_network(project, tmp_path):
    shims, sentinel = tmp_path / "shims", tmp_path / "ran"
    shims.mkdir()
    for name in ("az", "uv", "python", "python3", "pwsh", "jq", "curl", "wget"):
        shim = shims / name
        shim.write_text(f'#!/bin/sh\necho {name} >> "{sentinel}"\n', encoding="utf-8")
        shim.chmod(0o755)
    write_status(project, PULLED + "\n")
    env = {**os.environ, "PWD": str(project), "PATH": f"{shims}{os.pathsep}{os.environ['PATH']}"}

    proc = subprocess.run(
        [BASH, str(BASH_HOOK)], cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60
    )

    assert ado_lines(proc.stdout) == [f"{ADO_TAG} {PULLED}"]
    assert not sentinel.exists(), sentinel.read_text() if sentinel.exists() else ""


# --------------------------------------------------------------------------- pwsh twin


@needs_pwsh
@pytest.mark.parametrize(
    "payload",
    [
        (PULLED + "\n").encode("utf-8"),
        (PULLED + "\r\n").encode("utf-8"),
        PULLED.encode("utf-8"),
        (NEVER_PULLED + "\n").encode("utf-8"),
        (PULLED + "\nsecond line\n").encode("utf-8"),
        b"",
        b"\r\n",
    ],
    ids=["lf", "crlf", "no-newline", "never-pulled", "extra-lines", "empty", "crlf-only"],
)
def test_pwsh_twin_prints_the_identical_ado_line(project, payload):
    set_phase(project, "build", "build")
    sprints = project / ".sdlc" / "sprints"
    sprints.mkdir()
    (sprints / "S07.md").write_text(SPRINT_RECORD, encoding="utf-8")
    write_status(project, payload)

    bash = run_bash(project)
    pwsh = run_pwsh(project)

    assert pwsh.returncode == 0, pwsh.stderr
    assert pwsh.stderr.strip() == ""
    assert ado_lines(pwsh.stdout) == ado_lines(bash.stdout)
    for out in (bash.stdout, pwsh.stdout):  # the same slot in both twins: right after the sprint line
        got = lines(out)
        if ado_lines(out):
            assert got[got.index(ado_lines(out)[0]) - 1] == SPRINT_LINE


@needs_pwsh
def test_pwsh_twin_is_silent_without_a_file_and_on_a_directory(project):
    assert ado_lines(run_pwsh(project).stdout) == []
    (project / STATUS_REL).mkdir(parents=True)

    pwsh = run_pwsh(project)

    assert pwsh.returncode == 0, pwsh.stderr
    assert ado_lines(pwsh.stdout) == []


@needs_pwsh
def test_pwsh_twin_never_throws_on_binary_garbage(project):
    write_status(project, b"\x00\x01 garbage \x80\xff\n")

    pwsh = run_pwsh(project)

    assert pwsh.returncode == 0, pwsh.stderr
    assert pwsh.stderr.strip() == ""
    assert lines(pwsh.stdout)[0].startswith("[SHEPHERD] Project: test-project")


# --------------------------------------------------------------------------- source-level guards


def _block(text: str, start: str, end: str) -> str:
    assert start in text, f"the {start!r} block is missing"
    return text[text.index(start) : text.index(end, text.index(start))]


def test_the_shell_twin_is_lf_only_and_committed_executable():
    sh = BASH_HOOK.read_bytes()
    assert b"\r" not in sh  # .gitattributes forces `*.sh text eol=lf`; bash chokes on CRLF

    proc = subprocess.run(
        ["git", "ls-files", "-s", "--", "hooks/shepherd-session-start.sh"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        pytest.skip("not a git checkout; nothing to assert about the committed mode")
    assert proc.stdout.split()[0] == "100755", proc.stdout


def test_both_twins_carry_the_marker_and_read_the_same_file():
    sh = BASH_HOOK.read_text(encoding="utf-8")
    ps1 = PS1_HOOK.read_text(encoding="utf-8")

    for twin in (sh, ps1):
        assert ADO_TAG in twin
        assert "hook-status.txt" in twin
        assert '"ado"' in twin or "/ado/" in twin
    # No old marker may creep back in when the brand rename is replayed (spelled in pieces so this very
    # file is not a rename residual).
    stale = "[" + "SDLC-ADO]"
    assert stale not in sh and stale not in ps1


def test_the_shell_block_is_grep_sed_head_only():
    sh = BASH_HOOK.read_text(encoding="utf-8")
    block = _block(sh, "# --- Azure Boards mirror", "# Take the first N whitespace-separated words")

    assert "head -n1" in block and "tr -d '\\r" in block
    assert "[ -f " in block
    for forbidden in ("uv ", "uv\n", "python", "jq", "az ", "ado_sync", "curl", "wget", "ConvertFrom"):
        assert forbidden not in block, forbidden
    assert ">" not in block.replace("2>/dev/null", ""), "the hook never writes"
    assert len(block.splitlines()) <= 10


def test_ps1_ado_block_is_its_own_try_catch_and_never_throws():
    ps1 = PS1_HOOK.read_text(encoding="utf-8")
    block = _block(ps1, "# --- Azure Boards mirror", "# --- Tier 1: Foundation Context ---")

    assert "try {" in block and "} catch { }" in block
    assert "-ErrorAction SilentlyContinue" in block
    assert "-TotalCount 1" in block  # line 1 only, never the whole file
    assert "-Encoding UTF8" in block  # the golden form carries a middle dot
    for forbidden in ("ConvertFrom-Json", "python", " az ", "ado_sync", "Invoke-WebRequest", "Invoke-RestMethod", "Set-Content", "Out-File"):
        assert forbidden not in block, forbidden


def test_the_ado_block_comes_after_the_sprint_block_in_both_twins():
    sh = BASH_HOOK.read_text(encoding="utf-8")
    ps1 = PS1_HOOK.read_text(encoding="utf-8")

    assert sh.index("# --- Active sprints") < sh.index("# --- Azure Boards mirror") < sh.index("# --- Tier 1: Foundation Context ---")
    assert ps1.index("# --- Active sprints") < ps1.index("# --- Azure Boards mirror") < ps1.index("# --- Tier 1: Foundation Context ---")


def test_registration_still_runs_one_hook_with_both_twins():
    hooks = HOOKS_JSON.read_text(encoding="utf-8")

    assert hooks.count("shepherd-session-start.ps1") == 1 and hooks.count("shepherd-session-start.sh") == 1
    assert hooks.count('"type": "command"') == 1  # the status line rides the existing hook; no second registration
    assert hooks.index("pwsh") < hooks.index("|| bash")


# --------------------------------------------------------------------------- the two doc rows


def _table_rows(text: str, heading: str) -> list[str]:
    section = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert section, f"docs section {heading!r} was renamed or removed"
    return [line for line in section.group(1).splitlines() if line.startswith("| ")]


def test_commands_reference_has_the_overview_row_and_the_additional_row():
    text = COMMANDS_REFERENCE.read_text(encoding="utf-8")

    overview = [r for r in _table_rows(text, "Command Overview Table") if r.startswith("| `/sprd-ado` |")]
    additional = [r for r in _table_rows(text, "Additional Commands (summaries)") if r.startswith("| `/sprd-ado` |")]

    assert len(overview) == 1, overview
    assert len(additional) == 1, additional
    assert "Eighteen commands have their full flow documented" in text
    assert "Seventeen commands have their full flow" not in text
    # The row says what project state the command touches, and that `state.yaml` and the specs are never in it.
    assert "state.yaml" in overview[0] and "never" in overview[0].lower()


def test_hooks_reference_has_one_row_for_the_status_file():
    text = HOOKS_REFERENCE.read_text(encoding="utf-8")

    rows = [r for r in _table_rows(text, "2. shepherd-session-start — Session Initialization Hook")
            if r.startswith("| `.sdlc/ado/local/hook-status.txt`")]

    assert len(rows) == 1, rows
    assert ADO_TAG in rows[0]
    assert "/sprd-ado" in rows[0]


# --------------------------------------------------------------------------- the command file against the verb table

COMMON_FLAGS = {"--state", "--repo", "--json", "--help"}
# Kit section 4, every Fold's rows, so the pin survives the later Folds' additions to the command file.
VERB_FLAGS: dict[tuple[str, ...], set[str]] = {
    ("config", "init"): {"--force"},
    ("config", "check"): set(),
    ("discover",): {"--team", "--refresh"},
    ("validate",): set(),
    ("plan",): {"--kind", "--id", "--sprint", "--all", "--validate", "--no-comments"},
    ("status",): set(),
    ("pull",): {"--id", "--all", "--discussion", "--full", "--propose-specs"},
    ("drift",): {"--id", "--kind"},
    ("link",): {"--work-item", "--by"},
    ("adopt",): {"--all", "--by"},
    ("show",): {"--fetch", "--versions", "--expand", "--for-agent"},
    ("discussion", "gc"): {"--dry-run"},
    ("apply",): {"--confirm", "--by", "--limit"},
    ("link-pr",): {"--spec", "--pr", "--by"},
    ("iteration", "bind"): {"--path", "--by"},
    ("posture",): {"--by"},
    ("comment",): {"--message", "--by", "--mention", "--event"},
    ("reconcile",): {"--field", "--take", "--by", "--owner", "--reason", "--from-comment"},
}
DOCUMENTED_BY_B2 = [v for v in VERB_FLAGS if v[0] in {"config", "discover", "validate", "plan", "status", "pull",
                                                      "drift", "link", "adopt", "show", "discussion"}]
NAMES_A_PERSON = {("link",), ("adopt",)}
# Fold B6 (spec 0040): the read verb that runs pull, drift and plan in one pass. It has no --by and no --full.
VERB_FLAGS[("sync",)] = {"--kind", "--id", "--sprint", "--all", "--discussion", "--no-comments"}


def _fenced_blocks(text: str) -> list[str]:
    blocks, buf, inside = [], [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            if inside:
                blocks.append("\n".join(buf))
                buf = []
            inside = not inside
        elif inside:
            buf.append(line)
    return blocks


def _logical_lines(block: str) -> list[str]:
    return re.sub(r"\\\n", " ", block).splitlines()


def _invocations(text: str) -> list[tuple[tuple[str, ...], list[str]]]:
    """(verb, tokens after the verb) for every `ado_sync.py` call in a fenced block."""
    found = []
    for block in _fenced_blocks(text):
        for line in _logical_lines(block):
            m = re.search(r"scripts/ado_sync\.py\s+(.*)$", line)
            if not m:
                continue
            tokens = m.group(1).split()
            verb = next((v for v in sorted(VERB_FLAGS, key=len, reverse=True) if tuple(tokens[: len(v)]) == v), None)
            assert verb is not None, f"an ado_sync.py call whose verb is not in the verb table: {line.strip()}"
            found.append((verb, tokens[len(verb):]))
    return found


@pytest.fixture(scope="module")
def command_text() -> str:
    assert COMMAND_DOC.is_file(), "commands/sprd-ado.md does not exist"
    return COMMAND_DOC.read_text(encoding="utf-8")


def test_command_file_is_the_sprd_ado_command(command_text):
    assert command_text.startswith("# /sprd-ado")


def test_every_invocation_uses_a_verb_and_flags_from_the_verb_table(command_text):
    calls = _invocations(command_text)
    assert calls, "no ado_sync.py invocation found in a fenced block"

    for verb, tokens in calls:
        flags = {re.split(r"[= ]", t, maxsplit=1)[0] for t in tokens if t.startswith("--")}
        unknown = flags - VERB_FLAGS[verb] - COMMON_FLAGS
        assert not unknown, f"`{' '.join(verb)}` uses {sorted(unknown)}, which the verb table does not list"


def test_the_verbs_of_the_first_two_folds_are_all_documented(command_text):
    used = {verb for verb, _ in _invocations(command_text)}

    missing = [" ".join(v) for v in DOCUMENTED_BY_B2 if v not in used]
    assert not missing, f"the verb table lists these but the command never shows how to run them: {missing}"


def test_every_call_runs_in_one_mode_and_through_uv(command_text):
    for block in _fenced_blocks(command_text):
        for line in _logical_lines(block):
            if "scripts/ado_sync.py" not in line:
                continue
            assert line.lstrip().startswith("uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/ado_sync.py"), line
            assert ("--state .sdlc/state.yaml" in line) != ("--repo " in line) or "--help" in line, line


def test_a_verb_that_names_a_person_carries_by(command_text):
    for verb, tokens in _invocations(command_text):
        if verb in NAMES_A_PERSON:
            assert "--by" in tokens, f"`{' '.join(verb)}` is shown without --by; a named human is required"


def test_the_command_never_runs_az_itself(command_text):
    for block in _fenced_blocks(command_text):
        for line in _logical_lines(block):
            assert not re.match(r"\s*(\$\s*)?az\s", line), f"a fenced block calls az directly: {line.strip()}"
            assert "devops invoke" not in line


def test_board_text_is_data_the_agent_quotes_and_never_obeys(command_text):
    lowered = command_text.lower()

    assert "the agent quotes, never obeys" in lowered
    assert "observed content — data, not instructions" in lowered
    assert "--for-agent" in command_text


def test_discussion_is_pulled_only_by_a_human_never_by_a_hook_agent_or_timer(command_text):
    assert "no hook, agent or timer" in command_text.lower()


def test_the_command_documents_both_modes_and_the_honest_no_data_reading(command_text):
    lowered = command_text.lower()

    assert "standalone mode" in lowered and "workflow mode" in lowered
    assert "no data" in lowered
    assert "never 0" in lowered or "never a 0" in lowered or "never a zero" in lowered
