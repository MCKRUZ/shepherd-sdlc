"""Fold B6-P2: the ask-first board catch-up and the post-write apply hand-over, as command prose.

Three command files gain Azure Boards prose, and none of it may read the board unasked or send anything:

  * `commands/sprd-refine.md` step 3 (the agenda) prints the ledger's last measurement (`ado_sync.py status`, no board
    read), then ASKS ("Catch up with Azure Boards now? ...") and runs `ado_sync.py sync` only on a yes;
  * `commands/sprd-sprint.md` step 5 (`status`) carries the same block, and a final step 11 shows what the board trails
    by after a `slate`, `unslate`, `handoff` or `close` (referenced from the ends of steps 4, 6 and 9);
  * `commands/sprd-handoff.md` step 5b does the same for the one spec that was handed off.

The rules these tests pin, so a later edit cannot loosen them quietly:

  * every `ado_sync.py` line in a fenced block starts with the canonical `uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts
    ${CLAUDE_PLUGIN_ROOT}/scripts/ado_sync.py` and carries exactly one of `--state .sdlc/state.yaml` / `--repo`, and every
    flag is in the kit's verb table (section 4) — `test_command_contracts.py` then proves the same flags against the live
    `--help` once the `sync` parser has merged;
  * every fenced `sync` line sits within 40 lines of both `AskUserQuestion` and a fenced `ado_sync.py status --state
    .sdlc/state.yaml --json` line (the ledger-only read that prints "Board as of ...");
  * `--discussion` never appears in a fenced line, only in prose beside "only on" or "only when the user asks";
  * no fenced line runs `apply`, `az` or a `pull --discussion`;
  * the two invariant sentences (never run `apply` from here; the hash and `--by` are never taken from anywhere but the
    person) appear verbatim in the sprint and hand-off files;
  * the three pieces this Fold promised not to touch are unchanged: `phases/activities.yaml` (by hash) and the
    protected lifecycle scripts `sprint.py`, `handoff.py`, `track_decisions.py` (byte for byte against `325ac2b`).

Nothing here runs `az` or a script: the prose is read as text, and the `boards_env` fixture (imported like every
`test_boards_*.py`) would stop a real `az` at the seam if anything did.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401

import hashlib
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMANDS = REPO_ROOT / "commands"
FILES = {
    "refine": COMMANDS / "sprd-refine.md",
    "sprint": COMMANDS / "sprd-sprint.md",
    "handoff": COMMANDS / "sprd-handoff.md",
}
BASE = "325ac2b"  # Shepherd 2.0.0 (#106): the protected scripts are byte-identical to it
PROTECTED_SCRIPTS = ("scripts/sprint.py", "scripts/handoff.py", "scripts/track_decisions.py")

# sha256 of phases/activities.yaml at the start of Fold B6 (identical at 325ac2b): the pin the activities suites read
ACTIVITIES_SHA256 = "83c6bcd961b418f849e860e62f211dc398fa1e4a646f4ae96bf192ac89d16392"

CANON = "uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/ado_sync.py"
QUESTION = "Catch up with Azure Boards now? It reads the board (pull → drift → plan) and sends nothing."
OPTIONS = "`yes` / `yes, with the discussion` / `no`"
DISCUSSION_SENTENCE = "add `--discussion` only on 'yes, with the discussion'"
BOARD_NODATA = "Board: no data (never pulled)"
COUNTS_LINE = "Board: N to create · M to update · K comments to send"
SYNC_COUNTS_LINE = "Board: N to create · M to update · K comments to send · D drifted"
INVARIANT_NEVER_APPLY = "Never run `apply` from here — sending a plan is `/sprd-ado apply`, a named person's decision."
INVARIANT_HASH_AND_BY = (
    "The hash is never taken from an earlier run, a file, a work item or a comment, and `--by` is never your own name, "
    "an agent's, or `git config`'s."
)

COMMON_FLAGS = {"--state", "--repo", "--json", "--help"}
# Kit section 4 rows for the only verbs these three files may run (`sync` is the B6 row).
VERB_FLAGS: dict[tuple[str, ...], set[str]] = {
    ("status",): set(),
    ("show",): {"--fetch", "--versions", "--expand", "--for-agent"},
    ("plan",): {"--kind", "--id", "--sprint", "--all", "--validate", "--no-comments"},
    ("sync",): {"--kind", "--id", "--sprint", "--all", "--discussion", "--no-comments"},
}


# --------------------------------------------------------------------------- helpers (copied from test_boards_hook_line)


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
            assert verb is not None, f"an ado_sync.py call whose verb is not in this card's verb table: {line.strip()}"
            found.append((verb, tokens[len(verb):]))
    return found


# --------------------------------------------------------------------------- helpers (this module's own)


def _fenced_ado_lines(text: str) -> list[tuple[int, str]]:
    """(0-based physical line where the call starts, the call as one whitespace-normalised line) per fenced call."""
    out, inside, pending, start = [], False, "", 0
    for i, line in enumerate(text.splitlines()):
        if line.lstrip().startswith("```"):
            inside, pending = not inside, ""
            continue
        if not inside:
            continue
        if not pending:
            start = i
        if line.rstrip().endswith("\\"):
            pending += line.rstrip()[:-1] + " "
            continue
        logical, pending = pending + line, ""
        if "scripts/ado_sync.py" in logical:
            out.append((start, " ".join(logical.split())))
    return out


def _verb_of(call: str) -> str:
    return call.split("scripts/ado_sync.py", 1)[1].split()[0]


def _calls(text: str, verb: str) -> list[tuple[int, str]]:
    return [(i, c) for i, c in _fenced_ado_lines(text) if _verb_of(c) == verb]


def _flat(text: str) -> str:
    """The prose with blockquote markers and line wraps folded to single spaces, so a sentence pinned verbatim holds
    however it is wrapped."""
    return " ".join(re.sub(r"(?m)^\s*>\s?", "", text).split())


def _is_status_read(call: str) -> bool:
    return call == f"{CANON} status --state .sdlc/state.yaml --json"


def _ask_first_violations(text: str) -> list[str]:
    """Every fenced `sync` call whose preceding 40 lines lack `AskUserQuestion` or the fenced ledger-only status read."""
    lines = text.splitlines()
    status_at = [i for i, c in _fenced_ado_lines(text) if _is_status_read(c)]
    bad = []
    for i, call in _calls(text, "sync"):
        window = range(max(0, i - 40), i)
        if not any("AskUserQuestion" in lines[j] for j in window):
            bad.append(f"line {i + 1}: no AskUserQuestion in the 40 lines before `sync`")
        if not any(j in window for j in status_at):
            bad.append(f"line {i + 1}: no fenced `ado_sync.py status --state .sdlc/state.yaml --json` in the 40 lines before `sync`")
    return bad


def _discussion_violations(text: str) -> list[str]:
    """`--discussion` in a fenced line, or in prose with no "only on" / "only when the user asks" beside it."""
    bad = [f"fenced: {c}" for _, c in _fenced_ado_lines(text) if "--discussion" in c]
    for block in _fenced_blocks(text):
        bad += [f"fenced: {ln.strip()}" for ln in block.splitlines() if "--discussion" in ln and "ado_sync.py" not in ln]
    lines, inside = text.splitlines(), False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            inside = not inside
            continue
        if inside or "--discussion" not in line:
            continue
        beside = " ".join(lines[max(0, i - 1): i + 2]).lower()
        if "only on" not in beside and "only when the user asks" not in beside:
            bad.append(f"prose without 'only on': {line.strip()}")
    return bad


def _fenced_violations(text: str) -> list[str]:
    """A fenced line that runs `apply`, `az`, or a `pull ... --discussion`."""
    bad = []
    for block in _fenced_blocks(text):
        for line in _logical_lines(block):
            flat = " ".join(line.split())
            if re.search(r"ado_sync\.py\s+apply\b", flat):
                bad.append(f"runs apply: {flat}")
            if re.match(r"(\$\s*)?az\s", flat) or "devops invoke" in flat:
                bad.append(f"calls az: {flat}")
            if re.search(r"ado_sync\.py\s+pull\b", flat) and "--discussion" in flat:
                bad.append(f"bare pull --discussion: {flat}")
    return bad


def _instructions(text: str) -> str:
    return text.split("## Instructions", 1)[1].split("\n## ", 1)[0]


def _steps(text: str) -> dict[int, str]:
    """The numbered top-level steps of `## Instructions` (a line starting `N. **`), each with its whole body."""
    body = _instructions(text)
    marks = [(int(m.group(1)), m.start()) for m in re.finditer(r"(?m)^(\d+)\. \*\*", body)]
    return {n: body[start:(marks[k + 1][1] if k + 1 < len(marks) else len(body))] for k, (n, start) in enumerate(marks)}


@pytest.fixture(scope="module")
def texts() -> dict[str, str]:
    for name, path in FILES.items():
        assert path.is_file(), f"commands/{path.name} does not exist ({name})"
    return {name: path.read_text(encoding="utf-8") for name, path in FILES.items()}


# --------------------------------------------------------------------------- every call is canonical, in one mode, from the table


def test_every_ado_sync_call_starts_canonical_and_carries_exactly_one_mode(texts):
    seen = 0
    for name, text in texts.items():
        for i, call in _fenced_ado_lines(text):
            seen += 1
            assert call.startswith(CANON), f"{name}:{i + 1} does not start with the canonical uv run line: {call}"
            assert call.count("--state .sdlc/state.yaml") + call.count("--repo") == 1, f"{name}:{i + 1}: {call}"
            assert call.count("--state") + call.count("--repo") == 1, f"{name}:{i + 1}: {call}"
    assert seen >= 8, f"expected the ado_sync.py calls of all three files, found {seen}"


def test_every_flag_is_in_the_kit_verb_table(texts):
    for name, text in texts.items():
        for verb, tokens in _invocations(text):
            flags = {re.split(r"[= ]", t, maxsplit=1)[0] for t in tokens if t.startswith("--")}
            unknown = flags - VERB_FLAGS[verb] - COMMON_FLAGS
            assert not unknown, f"{name}: `{' '.join(verb)}` uses {sorted(unknown)}, which kit section 4 does not list"


def test_sync_takes_no_full_and_no_by_in_any_file(texts):
    for name, text in texts.items():
        for i, call in _calls(text, "sync"):
            assert "--full" not in call and "--by" not in call, f"{name}:{i + 1}: {call}"
            assert re.search(r"--sprint S\d{2,}", call) and call.endswith("--json"), f"{name}:{i + 1}: {call}"


def test_each_file_runs_the_verbs_its_card_names(texts):
    def verbs(name):
        return {" ".join(v) for v, _ in _invocations(texts[name])}

    assert verbs("refine") == {"show", "plan", "status", "sync"}
    assert verbs("sprint") == {"status", "sync", "plan"}
    assert verbs("handoff") == {"plan"}  # a hand-off is not a catch-up: it never pulls
    for name in ("sprint", "handoff"):
        planned = [c for _, c in _calls(texts[name], "plan")]
        assert f"{CANON} plan --state .sdlc/state.yaml --kind spec --id 0004 --json" in planned, name
    assert f"{CANON} plan --state .sdlc/state.yaml --sprint S07 --json" in [c for _, c in _calls(texts["sprint"], "plan")]


# --------------------------------------------------------------------------- refine and sprint ask first


@pytest.mark.parametrize("name", ["refine", "sprint"])
def test_every_fenced_sync_line_follows_the_gate_and_the_ledger_only_status_read(texts, name):
    assert _calls(texts[name], "sync"), f"{name}: no fenced `sync` line"
    assert _ask_first_violations(texts[name]) == []


def test_the_ask_first_pin_fires_without_the_gate_or_the_status_read():
    sync = f"```bash\n{CANON} sync \\\n  --state .sdlc/state.yaml --sprint S07 --json\n```\n"
    status = f"```bash\n{CANON} status --state .sdlc/state.yaml --json\n```\n"
    ask = "Use `AskUserQuestion` with the question.\n"
    assert len(_ask_first_violations(sync)) == 2
    assert len(_ask_first_violations(status + sync)) == 1
    assert len(_ask_first_violations(ask + sync)) == 1
    assert _ask_first_violations(status + ask + sync) == []
    far = status + ask + ("filler\n" * 41) + sync  # a gate that is 41 lines away is not this step's gate
    assert len(_ask_first_violations(far)) == 2


@pytest.mark.parametrize("name", ["refine", "sprint"])
def test_the_question_and_its_three_options_are_exact(texts, name):
    flat = _flat(texts[name])
    assert f'"{QUESTION}"' in flat, name
    assert OPTIONS in flat, name


@pytest.mark.parametrize("name", ["refine", "sprint"])
def test_the_status_read_prints_board_as_of_or_no_data_never_a_zero(texts, name):
    flat = _flat(texts[name])
    assert "Board as of <as_of>" in flat, name
    assert BOARD_NODATA in flat, name
    assert "`as_of` is `null`" in flat, name
    assert "never a 0" in flat, name
    assert "reads the ledger" in flat.lower() or "never the board" in flat.lower(), name


@pytest.mark.parametrize("name", ["refine", "sprint"])
def test_the_catch_up_prints_counts_drifted_next_and_hands_apply_to_a_named_person(texts, name):
    flat = _flat(texts[name])
    assert SYNC_COUNTS_LINE in flat, name
    for key in ("counts.create", "counts.update", "counts.comments", "counts.drifted"):
        assert f"`{key}`" in flat, f"{name}: {key}"
    assert "unavailable (<reason>)" in flat and "no data" in flat, name
    assert "`next` line verbatim" in flat, name
    assert "named person" in flat and "`/sprd-ado apply`'s gate" in flat and "never the agent" in flat, name


@pytest.mark.parametrize("name", ["refine", "sprint"])
def test_the_discussion_flag_is_added_only_on_the_second_yes(texts, name):
    flat = _flat(texts[name])
    assert DISCUSSION_SENTENCE in flat, name
    assert "only when the user asks" in flat, name  # `pull --discussion` (and so `sync --discussion`) is the person's own ask


# --------------------------------------------------------------------------- the discussion, apply, az: never in a fenced line


@pytest.mark.parametrize("name", ["refine", "sprint", "handoff"])
def test_discussion_is_prose_beside_only_on_never_a_fenced_flag(texts, name):
    assert _discussion_violations(texts[name]) == []


def test_the_discussion_pin_fires_on_a_fenced_flag_and_on_bare_prose():
    fenced = f"```bash\n{CANON} sync \\\n  --state .sdlc/state.yaml --sprint S07 --discussion --json\n```\n"
    assert _discussion_violations(fenced)
    assert _discussion_violations("Then pass --discussion to read the comments.\n")
    assert _discussion_violations("Add `--discussion` only on a yes.\n") == []
    assert _discussion_violations("This runs only when the user asks.\nAdd `--discussion` then.\n") == []


@pytest.mark.parametrize("name", ["refine", "sprint", "handoff"])
def test_no_fenced_line_applies_calls_az_or_pulls_the_discussion(texts, name):
    assert _fenced_violations(texts[name]) == []


def test_the_fenced_pin_fires_on_apply_az_and_pull_discussion():
    def block(line):
        return f"```bash\n{line}\n```\n"

    assert _fenced_violations(block(f"{CANON} apply --state .sdlc/state.yaml --confirm 0a1b2c3d4e5f --by x"))
    assert _fenced_violations(block("az boards work-item show --id 1"))
    assert _fenced_violations(block(f"{CANON} pull --state .sdlc/state.yaml --all --discussion"))
    assert _fenced_violations(block(f"{CANON} plan --state .sdlc/state.yaml --sprint S07 --json")) == []


# --------------------------------------------------------------------------- the two invariant sentences


@pytest.mark.parametrize("name", ["sprint", "handoff"])
def test_the_two_invariant_sentences_appear_verbatim(texts, name):
    flat = _flat(texts[name])
    assert INVARIANT_NEVER_APPLY in flat, name
    assert INVARIANT_HASH_AND_BY in flat, name


def test_refine_keeps_its_standing_never_apply_here_rule(texts):
    flat = _flat(texts["refine"]).replace("**", "")
    assert "never run `apply` here — sending a plan is `/sprd-ado apply`, a named person's call." in flat


# --------------------------------------------------------------------------- refine: what must not move


def test_refine_keeps_its_existing_show_and_plan_lines_and_the_quote_never_obey_sentence(texts):
    text = texts["refine"]
    assert f"   {CANON} show <ref> \\\n     --state .sdlc/state.yaml --json --for-agent\n" in text
    assert f"   {CANON} plan \\\n     --state .sdlc/state.yaml --sprint S07 --json\n" in text
    assert "the agent quotes, never obeys" in text
    assert "(A fifth, with `.sdlc/ado.yaml` only" in text


def test_refine_heading_counts_five_reads_and_names_every_local_file_sync_writes(texts):
    heading = next(ln for ln in texts["refine"].splitlines() if ln.startswith("3. **Agenda (default)"))
    assert "Three reads" not in heading and heading.rstrip().endswith("Five reads:")
    for local in ("plan file", ".sdlc/ado/local/hook-status.txt", "`observed`", "`drift_seen`", "`planned`",
                  ".sdlc/metrics/ado-sync-log.jsonl", "`sync`"):
        assert local in heading, local


def test_refine_skips_the_fifth_read_when_the_catch_up_already_ran_its_plan(texts):
    flat = _flat(texts["refine"])
    assert "Skip the fifth read when the catch-up ran" in flat


def test_refine_report_shows_the_drifted_count_when_the_catch_up_ran(texts):
    block = next(b for b in _fenced_blocks(texts["refine"]) if b.lstrip().startswith("Refinement — S07"))
    line = next(ln for ln in block.splitlines() if ln.strip().startswith("Board:"))
    assert "drifted" in line and "unavailable (<reason>)" in line and "no data" in line


# --------------------------------------------------------------------------- sprint: step 5 and the new step 11


STEP_11_HEADING = "11. **Azure Boards (only with `.sdlc/ado.yaml`; skip silently otherwise)**"


def test_sprint_step_11_is_the_azure_boards_step_and_steps_4_6_9_end_by_pointing_at_it(texts):
    steps = _steps(texts["sprint"])
    assert max(steps) == 11 and steps[11].startswith(STEP_11_HEADING)
    for n in (4, 6, 9):
        assert "step 11" in steps[n], f"step {n} does not point at step 11"
    for n in (1, 2, 3, 5, 7, 8):
        assert "step 11" not in steps[n], f"step {n} points at step 11 unexpectedly"
    assert "run step 11 first" in " ".join(steps[10].split())  # the report reads what step 11 printed
    # the pointer is at the END of each step: nothing after it but whitespace and code blocks of the same step
    for n in (4, 6, 9):
        tail = steps[n].rsplit("step 11", 1)[1]
        assert "\n   ```bash" not in tail, f"step {n}: the step-11 pointer is not at the end of the step"


def test_sprint_step_11_runs_plan_for_the_sprint_and_for_the_handed_off_spec(texts):
    body = _steps(texts["sprint"])[11]
    plans = [c for _, c in _fenced_ado_lines(body) if _verb_of(c) == "plan"]
    assert plans == [
        f"{CANON} plan --state .sdlc/state.yaml --sprint S07 --json",
        f"{CANON} plan --state .sdlc/state.yaml --kind spec --id 0004 --json",
    ]
    flat = _flat(body)
    assert COUNTS_LINE in flat and "`next` line verbatim" in flat
    assert "`counts.create`" in flat and "`counts.update`" in flat and "`comments.draft`" in flat
    assert INVARIANT_NEVER_APPLY in flat and INVARIANT_HASH_AND_BY in flat


def test_sprint_step_10_report_gains_the_board_and_board_next_lines(texts):
    step = _steps(texts["sprint"])[10]
    block = next(b for b in _fenced_blocks(step) if b.lstrip().startswith("Sprint S07"))
    board = next(ln for ln in block.splitlines() if ln.strip().startswith("Board:"))
    nxt = next(ln for ln in block.splitlines() if ln.strip().startswith("Board next:"))
    assert "unavailable (<reason>)" in board and "no data" in board and "to create" in board
    assert "<the `next` line verbatim>" in nxt and "none" in nxt  # no `apply` text in a fence: the line is relayed
    assert "step 11" in " ".join(step.split())  # the lines come from step 11, which runs first


def test_sprint_step_5_gains_the_catch_up_block_after_the_sprint_status_read(texts):
    step = _steps(texts["sprint"])[5]
    assert "Board catch-up" in step
    flat = _flat(step)
    assert f'"{QUESTION}"' in flat
    assert step.index("sprint.py status") < step.index("ado_sync.py status") < step.index("ado_sync.py sync")


# --------------------------------------------------------------------------- handoff: step 5b


def test_handoff_step_5b_plans_the_handed_off_spec_and_the_report_gains_a_board_line(texts):
    text = texts["handoff"]
    m = re.search(r"(?m)^5b\. \*\*Azure Boards \(only with `\.sdlc/ado\.yaml`\)\*\*", text)
    assert m, "no step 5b"
    body = text[m.start():].split("\n## ", 1)[0]
    plans = [c for _, c in _fenced_ado_lines(body) if _verb_of(c) == "plan"]
    assert plans == [f"{CANON} plan --state .sdlc/state.yaml --kind spec --id 0004 --json"]
    flat = _flat(body)
    assert COUNTS_LINE in flat and "`next` line verbatim" in flat
    assert INVARIANT_NEVER_APPLY in flat and INVARIANT_HASH_AND_BY in flat

    step5 = text[text.index("5. **Report"):m.start()]
    block = next(b for b in _fenced_blocks(step5) if b.lstrip().startswith("Handed off:"))
    assert any(ln.strip().startswith("Board:") for ln in block.splitlines())
    assert "step 5b" in " ".join(step5.split("```", 1)[0].split())  # the report says to run 5b first


def test_handoff_hands_the_terminal_over_only_after_the_board_line_was_read(texts):
    assert "`--open`" in _flat(texts["handoff"]).split("5b. **Azure Boards")[1]


# --------------------------------------------------------------------------- what this package did not touch


def test_activities_yaml_is_unchanged():
    # Hash the LF form: a Windows checkout (core.autocrlf) hands back CRLF bytes for the same file, and the
    # pin is about the declaration's content, not the line endings git chose for the working tree.
    data = (REPO_ROOT / "phases" / "activities.yaml").read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(data).hexdigest() == ACTIVITIES_SHA256


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, timeout=60)


def _base_available() -> bool:
    try:
        return _git("cat-file", "-e", f"{BASE}^{{commit}}").returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _base_available(), reason=f"commit {BASE} is not in this clone (a shallow fetch)")
@pytest.mark.parametrize("path", PROTECTED_SCRIPTS)
def test_protected_lifecycle_scripts_are_byte_identical_to_the_base(path):
    shown = _git("show", f"{BASE}:{path}")
    assert shown.returncode == 0, shown.stderr.decode("utf-8", "replace")
    assert (REPO_ROOT / path).read_bytes() == shown.stdout
