"""Tests for sprint.py — the sprint team layer's I/O CLI (new, slate, unslate, status, handoff, ack,
verdict, ready, plan, close).

Covers: dual-mode (--repo bare repo / --state via conftest.state_yaml); exit codes per verb; key
insertion on three spec shapes leaves the body bytes identical and check_spec's verdict unchanged;
specs/spec-template.md is never listed or written; the slate proposal fills the mix; over-target is
refused unless --override --reason; the n-a verdict rules; handoff/ack; ready gaps -> exit 1 and
ready ok -> state ready + ledger + planning page; close needs a decision for every open spec, carries
rewrite sprint:, writes ## Close; forbidden --field keys exit 2; the JSON has no per-person
aggregation; .sdlc/state.yaml is byte-identical before/after every verb; --help exits 0 for the
script and every verb from a cwd with no .sdlc.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import check_spec
import sprint
import sprint_model as sm

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = PLUGIN_ROOT / "scripts" / "sprint.py"
HARNESS_TEMPLATE = PLUGIN_ROOT / "harness" / "spec-template.md"

# The shared contract's sprint template, verbatim — so these tests never depend on the templates agent.
SPRINT_TEMPLATE = (
    '---\n'
    'sprint: "SNN"\n'
    'goal: ""\n'
    'start: "YYYY-MM-DD"\n'
    'end: "YYYY-MM-DD"            # default: last business day of a 10-business-day window (start is day 1)\n'
    'state: planning              # planning | ready | closed\n'
    'target: 0                    # how many specs to slate (a count, never a size)\n'
    'mix: ""                      # by risk tier, e.g. "HIGH:1,MEDIUM:2,LOW:3"; counts sum <= target\n'
    'board_ref: ""                # manual mapping only, e.g. "ADO Iteration 6"; nothing reads it\n'
    'readied_by: ""\n'
    'closed_by: ""\n'
    'created: "YYYY-MM-DD"\n'
    '---\n'
    '# Sprint SNN\n'
    '\n'
    '## Goal\n'
    '\n'
    '## Slate\n'
    '<!-- Rendered by `sprint.py slate/unslate/ready/close` from spec frontmatter — never hand-edit; run /sprd-sprint status for the live view. -->\n'
    '\n'
    '## Close\n'
    '<!-- Written by `sprint.py close`: | spec | outcome (kept | carried → SNN | dropped) | by | reason | -->\n'
)

READY_BODY = """
# Spec {id} — {name}

## Goal
Answer a warranty lookup in one turn.

## Why
Customers wait.

## Scope

### In scope
- `src/warranty/*`

### Out of scope
- `src/billing/*`

## Acceptance Checks
- [ ] a lookup for serial `ABC123` returns 200 with `{{ "status": "active" }}`

## Risk Tier
**Tier:** {risk}
**Why this tier:** touches client data.

## Delegation Plan
- **Scope:** `src/warranty/*`

## Checking Plan
**Ladder depth:** {risk}
**Specifics:** security pass and named sign-off in the PR.

## Decision List
- none
"""


# --- helpers ------------------------------------------------------------------------------------

def plugin_shape_fm(spec_id, name, risk, status, extra=""):
    """The plugin template's frontmatter shape: status line with comment, channel, and — since
    the DoR started requiring a named accountable owner — an `owner` (upstream 1.6.x)."""
    return (
        '---\n'
        f'spec: "{spec_id}"\n'
        f'name: "{name}"\n'
        f'status: {status}            # draft | ready | in-flight | merged\n'
        'type: feature\n'
        f'risk: {risk}\n'
        'source: "REQ-1"\n'
        'channel: ""\n'
        'owner: "Priya"\n'
        'harness_context: "existing lookup pattern"\n'
        'created: "2026-09-01"\n'
        f'{extra}'
        '---\n'
    )


def harness_shape_fm(spec_id, name, risk, status):
    """The harness template's frontmatter shape: carries owner, no channel."""
    return (
        '---\n'
        f'spec: "{spec_id}"\n'
        f'name: "{name}"\n'
        f'status: {status}            # draft | ready | in-flight | merged\n'
        'type: feature\n'
        f'risk: {risk}\n'
        'owner: "Priya"\n'
        'source: "REQ-1"\n'
        'harness_context: "existing lookup pattern"\n'
        'created: "2026-09-01"\n'
        '---\n'
    )


def handwritten_fm(spec_id, name, risk):
    """A hand-written spec with no status line at all (but an owner, which the DoR requires)."""
    return f'---\nspec: "{spec_id}"\nname: "{name}"\nrisk: {risk}\nowner: "Priya"\nharness_context: "x"\n---\n'


def write_spec(repo: Path, spec_id, name, risk="MEDIUM", status="ready", fm=None, body=None, extra=""):
    specs = repo / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    fm = fm if fm is not None else plugin_shape_fm(spec_id, name, risk, status, extra)
    body = body if body is not None else READY_BODY.format(id=spec_id, name=name, risk=risk)
    path = specs / f"{spec_id}-{name}.md"
    path.write_bytes((fm + body).encode("utf-8"))
    return path


def make_backlog(repo: Path):
    """0007 HIGH ready, 0009 MEDIUM ready, 0011 LOW draft, 0013 LOW ready; plus the installed template."""
    (repo / "specs").mkdir(parents=True, exist_ok=True)
    (repo / "specs" / "spec-template.md").write_bytes(HARNESS_TEMPLATE.read_bytes())
    write_spec(repo, "0007", "warranty-lookup", "HIGH", "ready")
    write_spec(repo, "0009", "case-guardrail", "MEDIUM", "ready")
    write_spec(repo, "0011", "copy-polish", "LOW", "draft")
    write_spec(repo, "0013", "audit-fields", "LOW", "ready")
    return repo


def run(capsys, *argv) -> tuple[int, str]:
    """Run sprint.main in-process; return (exit code, stdout)."""
    try:
        code = sprint.main([str(a) for a in argv])
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    return code, capsys.readouterr().out


def ledger(repo: Path) -> list[dict]:
    path = repo / ".sdlc" / "metrics" / "sprint-log.jsonl"
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def fm_of(path: Path) -> dict:
    return check_spec.parse_frontmatter(path.read_bytes().decode("utf-8"))[0]


def verdict_of(path: Path) -> list[dict]:
    return check_spec.check_spec_text(path.read_bytes().decode("utf-8"))


def body_of(path: Path) -> bytes:
    text = path.read_bytes().decode("utf-8")
    end = text.find("\n---", 3)
    return text[end:].encode("utf-8")


def all_keys(obj, acc=None) -> set[str]:
    acc = set() if acc is None else acc
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(str(k))
            all_keys(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            all_keys(v, acc)
    return acc


# --- fixtures ------------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def sprint_template(tmp_path, monkeypatch):
    """Point the CLI at a copy of the contract template so the templates agent's timing is irrelevant."""
    tpl = tmp_path / "plugin-root" / "templates" / "phases" / "build" / "sprint.md"
    tpl.parent.mkdir(parents=True)
    tpl.write_text(SPRINT_TEMPLATE, encoding="utf-8")
    monkeypatch.setattr(sprint, "TEMPLATE_PATH", tpl)
    return tpl


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    return make_backlog(r)


@pytest.fixture
def sprint_repo(repo, capsys):
    """A repo with sprint S07 (target 3, mix HIGH:1,MEDIUM:1,LOW:1) created."""
    code, _ = run(capsys, "new", "--repo", repo, "--sprint", "S07", "--goal", "Warranty lookup answers in one turn",
                  "--start", "2026-09-28", "--target", "3", "--mix", "HIGH:1,MEDIUM:1,LOW:1", "--by", "Priya")
    assert code == 0
    return repo


@pytest.fixture
def slated_repo(sprint_repo, capsys):
    """S07 with 0007, 0009, 0011 slated."""
    code, _ = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S07", "--by", "Priya",
                  "--spec", "0007", "--spec", "0009", "--spec", "0011")
    assert code == 0
    return sprint_repo


@pytest.fixture
def render_calls(monkeypatch):
    """Stub the lazy page render so these tests do not depend on generate_sprint_report."""
    calls: list[dict] = []

    def fake(repo_root, sprint_id, kind, today, output=None, view=None):
        calls.append({"repo": Path(repo_root), "sprint": sprint_id, "kind": kind, "output": output, "view": view})
        return Path(repo_root) / ".sdlc" / "reports" / f"sprint-{sprint_id}-{kind}.html"

    monkeypatch.setattr(sprint, "_render_page", fake)
    return calls


def ready_up(repo: Path, capsys, specs=("0007", "0009", "0011")):
    """Drive the slate to the ready rule: status ready, eng accepted, data accepted."""
    for sid in specs:
        path = next((repo / "specs").glob(f"{sid}-*.md"))
        text = path.read_bytes().decode("utf-8").replace("status: draft", "status: ready")
        path.write_bytes(text.encode("utf-8"))
        assert run(capsys, "verdict", "--repo", repo, "--spec", sid, "--lane", "eng", "--verdict", "accepted", "--by", "Eng lead")[0] == 0
        assert run(capsys, "verdict", "--repo", repo, "--spec", sid, "--lane", "data", "--verdict", "accepted", "--by", "Data lead")[0] == 0


# --- --help ------------------------------------------------------------------------------------------

class TestHelp:
    @pytest.mark.parametrize("verb", [None, *sprint.VERBS])
    def test_help_exits_zero_from_a_cwd_without_sdlc(self, verb, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        argv = ([verb] if verb else []) + ["--help"]
        code, out = run(capsys, *argv)
        assert code == 0
        assert "--help" in out or "usage" in out.lower()
        assert not (tmp_path / ".sdlc").exists()

    def test_script_help_subprocess(self, tmp_path):
        r = subprocess.run([sys.executable, str(SCRIPT), "--help"], cwd=tmp_path, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        for verb in sprint.VERBS:
            assert verb in r.stdout
        assert not (tmp_path / ".sdlc").exists()

    def test_every_write_verb_advertises_field_and_by(self, capsys):
        for verb in sprint.WRITE_VERBS:
            code, out = run(capsys, verb, "--help")
            assert code == 0
            assert "--field" in out, verb
            assert "--by" in out, verb


# --- new -------------------------------------------------------------------------------------------------

class TestNew:
    def test_creates_record_with_default_end(self, repo, capsys):
        code, out = run(capsys, "new", "--repo", repo, "--sprint", "S07", "--goal", "G", "--start", "2026-09-28",
                        "--target", "6", "--mix", "HIGH:1,MEDIUM:2,LOW:3", "--board-ref", "ADO Iteration 6", "--by", "Priya")
        assert code == 0
        rec = sprint.read_sprint(repo, "S07")
        assert rec["state"] == "planning"
        assert rec["target"] == 6
        assert rec["mix"] == "HIGH:1,MEDIUM:2,LOW:3"
        assert rec["start"] == "2026-09-28"
        assert rec["end"] == "2026-10-09"  # Mon + 10 business days, start counted as day 1 -> Fri (D2)
        assert rec["board_ref"] == "ADO Iteration 6"
        text = (repo / ".sdlc" / "sprints" / "S07.md").read_text(encoding="utf-8")
        assert "# Sprint S07" in text
        assert "## Goal\nG\n" in text
        assert "# planning | ready | closed" in text  # trailing comments kept
        assert [e["event"] for e in ledger(repo)] == ["sprint_new"]

    def test_explicit_end_and_days(self, repo, capsys):
        assert run(capsys, "new", "--repo", repo, "--sprint", "S07", "--goal", "G", "--start", "2026-09-28",
                   "--end", "2026-10-02", "--target", "2", "--by", "Priya")[0] == 0
        assert sprint.read_sprint(repo, "S07")["end"] == "2026-10-02"
        assert run(capsys, "new", "--repo", repo, "--sprint", "S08", "--goal", "G", "--start", "2026-09-28",
                   "--days", "5", "--target", "2", "--by", "Priya")[0] == 0
        assert sprint.read_sprint(repo, "S08")["end"] == "2026-10-02"  # Mon..Fri of the same week

    @pytest.mark.parametrize("argv, code", [
        (["--sprint", "sprint7", "--goal", "G", "--start", "2026-09-28", "--target", "3", "--by", "P"], 1),      # bad id
        (["--sprint", "S7", "--goal", "G", "--start", "2026-09-28", "--target", "3", "--by", "P"], 1),           # needs 2 digits
        (["--sprint", "S07", "--goal", "G", "--start", "2026-09-28", "--target", "3", "--mix", "HIGH:2,LOW:2", "--by", "P"], 1),  # sum > target
        (["--sprint", "S07", "--goal", "G", "--start", "2026-09-28", "--target", "3", "--mix", "EPIC:1", "--by", "P"], 1),        # unknown tier
        (["--sprint", "S07", "--goal", "G", "--start", "next monday", "--target", "3", "--by", "P"], 1),         # bad date
        (["--sprint", "S07", "--goal", "G", "--start", "2026-09-28", "--target", "0", "--by", "P"], 1),          # target < 1
        (["--sprint", "S07", "--goal", "G", "--start", "2026-09-28", "--end", "2026-09-20", "--target", "3", "--by", "P"], 1),  # end before start
        (["--sprint", "S07", "--goal", "G", "--start", "2026-09-28", "--target", "3", "--by", "claude"], 2),       # AI actor
        (["--sprint", "S07", "--goal", "G", "--start", "2026-09-28", "--target", "3", "--field", "velocity=9", "--by", "P"], 2),  # forbidden
        (["--sprint", "S07", "--goal", "Ship #1", "--start", "2026-09-28", "--target", "3", "--by", "P"], 2),    # '#' in a frontmatter value
        (["--sprint", "S07", "--goal", "G", "--start", "2026-09-28", "--target", "3"], 2),                        # --by is required (argparse usage error)
    ])
    def test_exit_codes(self, repo, capsys, argv, code):
        got, _ = run(capsys, "new", "--repo", repo, *argv)
        assert got == code
        assert not (repo / ".sdlc" / "sprints").exists() or not list((repo / ".sdlc" / "sprints").glob("*.md"))

    def test_one_sprint_per_id(self, sprint_repo, capsys):
        code, out = run(capsys, "new", "--repo", sprint_repo, "--sprint", "S07", "--goal", "again",
                        "--start", "2026-09-28", "--target", "3", "--by", "Priya")
        assert code == 1
        assert "already exists" in out

    def test_missing_template_is_exit_1(self, repo, capsys, monkeypatch, tmp_path):
        monkeypatch.setattr(sprint, "TEMPLATE_PATH", tmp_path / "nope.md")
        code, out = run(capsys, "new", "--repo", repo, "--sprint", "S07", "--goal", "G", "--start", "2026-09-28", "--target", "3", "--by", "Priya")
        assert code == 1
        assert "template" in out


# --- slate -----------------------------------------------------------------------------------------------

class TestSlateProposal:
    def test_proposal_fills_the_mix_in_id_order_and_writes_nothing(self, sprint_repo, capsys):
        before = {p.name: p.read_bytes() for p in (sprint_repo / "specs").iterdir()}
        code, out = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S07", "--json")
        assert code == 0
        prop = json.loads(out)
        # mix HIGH:1 MEDIUM:1 LOW:1 over {0007 HIGH, 0009 MEDIUM, 0011 LOW, 0013 LOW}: LOW bucket takes 0011 (lower id)
        assert [r["id"] for r in prop["proposal"]] == ["0007", "0009", "0011"]
        assert prop["candidates"] == 4
        assert prop["mix_warnings"] == []
        assert {p.name: p.read_bytes() for p in (sprint_repo / "specs").iterdir()} == before
        assert [e["event"] for e in ledger(sprint_repo)] == ["sprint_new"]

    def test_proposal_text_lists_confirm_command(self, sprint_repo, capsys):
        code, out = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S07")
        assert code == 0
        assert "--spec 0007 --spec 0009 --spec 0011" in out

    def test_proposal_fills_remaining_slots_only(self, sprint_repo, capsys):
        assert run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S07", "--by", "Priya", "--spec", "0007")[0] == 0
        code, out = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S07", "--json")
        prop = json.loads(out)
        assert prop["already_slated"] == ["0007"]
        assert [r["id"] for r in prop["proposal"]] == ["0009", "0011"]

    def test_proposal_excludes_merged_in_flight_and_slated(self, sprint_repo, capsys):
        write_spec(sprint_repo, "0015", "merged-one", "LOW", "merged")
        write_spec(sprint_repo, "0016", "flying", "LOW", "in-flight")
        write_spec(sprint_repo, "0017", "elsewhere", "LOW", "ready", extra='sprint: "S06"\n')
        code, out = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S07", "--json")
        ids = {r["id"] for r in json.loads(out)["proposal"]}
        assert not ids & {"0015", "0016", "0017"}

    def test_proposal_on_unknown_or_malformed_sprint_is_exit_0_no_data(self, sprint_repo, repo, capsys):
        """The proposal is a read; like `status` it never fails — an unknown id prints no data, exit 0."""
        before = {p.name: p.read_bytes() for p in (sprint_repo / "specs").iterdir()}
        code, out = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S99")
        assert code == 0 and "no data" in out and "S99" in out and "does not exist" in out
        code, out = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "bogus")
        assert code == 0 and "no data" in out and "not a sprint id" in out
        code, out = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S99", "--json")
        assert code == 0
        prop = json.loads(out)
        assert prop["proposal"] == [] and prop["has_data"] is False and prop["sprint"] == "S99"
        assert {p.name: p.read_bytes() for p in (sprint_repo / "specs").iterdir()} == before
        assert [e["event"] for e in ledger(sprint_repo)] == ["sprint_new"]
        # the confirm (write) form keeps its exit-1 precondition
        code, out = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S99", "--by", "Priya", "--spec", "0007")
        assert code == 1 and "does not exist" in out

    def test_proposal_with_no_sprint_at_all_is_exit_0(self, repo, capsys):
        code, out = run(capsys, "slate", "--repo", repo)
        assert code == 0 and "no data" in out and "run `new` first" in out

    def test_proposal_no_candidates_reads_no_data(self, tmp_path, capsys):
        repo = tmp_path / "empty"
        repo.mkdir()
        assert run(capsys, "new", "--repo", repo, "--sprint", "S07", "--goal", "G", "--start", "2026-09-28", "--target", "3", "--by", "Priya")[0] == 0
        code, out = run(capsys, "slate", "--repo", repo, "--sprint", "S07")
        assert code == 0
        assert "no data" in out


class TestSlateWrite:
    def test_writes_sprint_key_and_ledger(self, sprint_repo, capsys):
        code, out = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S07", "--by", "Priya",
                        "--spec", "0007", "--spec", "0009", "--spec", "0011")
        assert code == 0
        for sid in ("0007", "0009", "0011"):
            fm = fm_of(next((sprint_repo / "specs").glob(f"{sid}-*.md")))
            assert fm["sprint"] == "S07"
            for key in sm.SPEC_KEYS:
                assert key in fm
        events = [e for e in ledger(sprint_repo) if e["event"] == "slated"]
        assert [e["spec"] for e in events] == ["0007", "0009", "0011"]
        assert all(e["by"] == "Priya" and e["sprint"] == "S07" for e in events)
        assert "reason" not in events[0]
        record = (sprint_repo / ".sdlc" / "sprints" / "S07.md").read_text(encoding="utf-8")
        assert "| 0007 | warranty-lookup | HIGH |" in record  # ## Slate rendered into the record
        assert "never hand-edit" in record  # the comment under ## Slate survives

    def test_by_required_on_write(self, sprint_repo, capsys):
        code, out = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S07", "--spec", "0007")
        assert code == 1
        assert "--by" in out
        assert fm_of(sprint_repo / "specs" / "0007-warranty-lookup.md").get("sprint", "") == ""

    def test_unknown_spec_exit_1(self, sprint_repo, capsys):
        code, out = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S07", "--by", "Priya", "--spec", "0099")
        assert code == 1
        assert "unknown spec" in out

    def test_merged_spec_exit_1(self, sprint_repo, capsys):
        write_spec(sprint_repo, "0015", "done", "LOW", "merged")
        code, out = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S07", "--by", "Priya", "--spec", "0015")
        assert code == 1
        assert "merged" in out

    def test_spec_in_another_sprint_exit_1(self, sprint_repo, capsys):
        write_spec(sprint_repo, "0015", "elsewhere", "LOW", "ready", extra='sprint: "S06"\n')
        code, out = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S07", "--by", "Priya", "--spec", "0015")
        assert code == 1
        assert "S06" in out

    def test_over_target_refused_unless_override_with_reason(self, sprint_repo, capsys):
        base = ["slate", "--repo", sprint_repo, "--sprint", "S07", "--by", "Priya"]
        assert run(capsys, *base, "--spec", "0007", "--spec", "0009", "--spec", "0011")[0] == 0
        code, out = run(capsys, *base, "--spec", "0013")
        assert code == 1
        assert "more than the target" in out
        assert fm_of(sprint_repo / "specs" / "0013-audit-fields.md").get("sprint", "") == ""
        code, out = run(capsys, *base, "--spec", "0013", "--override")
        assert code == 1
        assert "--reason" in out
        code, out = run(capsys, *base, "--spec", "0013", "--override", "--reason", "capacity freed")
        assert code == 0
        assert "WARNING" in out and "over the target" in out
        assert fm_of(sprint_repo / "specs" / "0013-audit-fields.md")["sprint"] == "S07"
        slated = [e for e in ledger(sprint_repo) if e["event"] == "slated" and e["spec"] == "0013"]
        assert slated[0]["reason"] == "capacity freed"

    def test_mix_breach_warns_but_does_not_block(self, sprint_repo, capsys):
        code, out = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S07", "--by", "Priya",
                        "--spec", "0011", "--spec", "0013")  # two LOW against LOW:1
        assert code == 0
        assert "mix breach" in out

    def test_dependency_outside_slate_warns(self, sprint_repo, capsys):
        write_spec(sprint_repo, "0015", "needs-seven", "LOW", "ready", extra='depends_on: "0007"\n')
        code, out = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S07", "--by", "Priya", "--spec", "0015")
        assert code == 0
        assert "depends on 0007" in out and "outside the slate" in out

    def test_already_slated_is_a_noop(self, slated_repo, capsys):
        before = ledger(slated_repo)
        code, out = run(capsys, "slate", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya", "--spec", "0007")
        assert code == 0
        assert "Nothing to slate" in out
        assert ledger(slated_repo) == before

    def test_closed_sprint_cannot_be_slated(self, slated_repo, capsys, render_calls):
        ready_up(slated_repo, capsys)
        assert run(capsys, "ready", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya")[0] == 0
        assert run(capsys, "close", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya",
                   "--drop", "0007=a", "--drop", "0009=b", "--drop", "0011=c")[0] == 0
        code, out = run(capsys, "slate", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya", "--spec", "0013")
        assert code == 1
        assert "closed" in out

    def test_forbidden_field_exit_2_and_nothing_written(self, sprint_repo, capsys):
        code, out = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S07", "--by", "Priya",
                        "--spec", "0007", "--field", "story-points=3")
        assert code == 2
        assert "Refused" in out and "activity metric" in out
        assert fm_of(sprint_repo / "specs" / "0007-warranty-lookup.md").get("sprint", "") == ""

    def test_ai_actor_refused_exit_2(self, sprint_repo, capsys):
        code, out = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S07", "--by", "GPT bot", "--spec", "0007")
        assert code == 2
        assert "labelling, not enforcement" in out


# --- key insertion on three spec shapes ------------------------------------------------------------------

class TestKeyInsertion:
    @pytest.mark.parametrize("shape", ["plugin", "harness", "handwritten", "plugin-not-ready"])
    def test_body_bytes_and_verdict_unchanged(self, tmp_path, capsys, shape):
        repo = tmp_path / "shape-repo"
        repo.mkdir()
        (repo / "specs").mkdir()
        (repo / "specs" / "spec-template.md").write_bytes(HARNESS_TEMPLATE.read_bytes())
        if shape == "plugin":
            path = write_spec(repo, "0007", "alpha", "HIGH", "ready")
        elif shape == "harness":
            path = write_spec(repo, "0007", "alpha", "HIGH", fm=harness_shape_fm("0007", "alpha", "HIGH", "ready"))
        elif shape == "handwritten":
            path = write_spec(repo, "0007", "alpha", "HIGH", fm=handwritten_fm("0007", "alpha", "HIGH"))
        else:  # the plugin template's own body, placeholders and all -> NOT READY, and must stay exactly that
            tpl = (PLUGIN_ROOT / "templates" / "phases" / "build" / "spec.md").read_text(encoding="utf-8")
            fm, body = check_spec.parse_frontmatter(tpl)
            path = write_spec(repo, "0007", "alpha", "HIGH", fm=plugin_shape_fm("0007", "alpha", "HIGH", "draft"), body=body)
        before_body, before_verdict, before_fm = body_of(path), verdict_of(path), fm_of(path)
        assert run(capsys, "new", "--repo", repo, "--sprint", "S07", "--goal", "G", "--start", "2026-09-28", "--target", "1", "--by", "Priya")[0] == 0
        assert run(capsys, "slate", "--repo", repo, "--sprint", "S07", "--by", "Priya", "--spec", "0007")[0] == 0

        assert body_of(path) == before_body
        assert verdict_of(path) == before_verdict
        after = fm_of(path)
        assert after["sprint"] == "S07"
        for key in sm.SPEC_KEYS:
            assert key in after
        for key, val in before_fm.items():
            assert after[key] == val  # nothing pre-existing changed
        lines = path.read_bytes().decode("utf-8").split("\n")
        keys = [ln.split(":", 1)[0] for ln in lines[1:lines.index("---", 1)]]
        if "status" in keys:
            assert keys[keys.index("status") + 1:keys.index("status") + 6] == list(sm.SPEC_KEYS)
        else:
            assert keys[:5] == list(sm.SPEC_KEYS)  # right after the opening ---

    def test_template_never_listed_or_written(self, sprint_repo, capsys):
        tpl = sprint_repo / "specs" / "spec-template.md"
        before = tpl.read_bytes()
        assert tpl not in sprint.list_spec_files(sprint_repo)
        assert all("spec-template" not in r["path"] for r in sprint.load_specs(sprint_repo))
        assert run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S07", "--by", "Priya",
                   "--spec", "0007", "--spec", "0009", "--spec", "0011")[0] == 0
        assert run(capsys, "status", "--repo", sprint_repo, "--json")[0] == 0
        assert tpl.read_bytes() == before
        code, out = run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S07", "--by", "Priya", "--spec", "NNNN")
        assert code == 1  # the template's id is not a spec

    def test_status_is_never_written(self):
        with pytest.raises(ValueError):
            sm.set_frontmatter('---\nstatus: draft\n---\n', "status", "ready")


# --- unslate ------------------------------------------------------------------------------------------------

class TestUnslate:
    def test_clears_sprint_and_logs_reason(self, slated_repo, capsys):
        code, out = run(capsys, "unslate", "--repo", slated_repo, "--sprint", "S07", "--spec", "0011", "--by", "Priya", "--reason", "not this sprint")
        assert code == 0
        assert fm_of(slated_repo / "specs" / "0011-copy-polish.md")["sprint"] == ""
        ev = ledger(slated_repo)[-1]
        assert ev["event"] == "unslated" and ev["reason"] == "not this sprint" and ev["spec"] == "0011"
        assert "| 0011 |" not in (slated_repo / ".sdlc" / "sprints" / "S07.md").read_text(encoding="utf-8")

    def test_not_in_sprint_exit_1(self, slated_repo, capsys):
        code, out = run(capsys, "unslate", "--repo", slated_repo, "--sprint", "S07", "--spec", "0013", "--by", "Priya", "--reason", "x")
        assert code == 1
        assert "not in S07" in out

    def test_blank_reason_exit_1(self, slated_repo, capsys):
        assert run(capsys, "unslate", "--repo", slated_repo, "--sprint", "S07", "--spec", "0011", "--by", "Priya", "--reason", "  ")[0] == 1

    def test_forbidden_field_exit_2(self, slated_repo, capsys):
        assert run(capsys, "unslate", "--repo", slated_repo, "--sprint", "S07", "--spec", "0011", "--by", "Priya",
                   "--reason", "x", "--field", "estimate=3d")[0] == 2


# --- status / build_view ------------------------------------------------------------------------------------

class TestStatus:
    def test_no_sprint_reads_no_data_exit_0(self, repo, capsys):
        code, out = run(capsys, "status", "--repo", repo)
        assert code == 0
        assert "no data" in out
        code, out = run(capsys, "status", "--repo", repo, "--json")
        assert code == 0
        view = json.loads(out)
        assert view["sprint"] is None and view["slate"] == [] and view["has_data"] is False

    def test_bad_sprint_id_is_still_exit_0(self, repo, capsys):
        code, out = run(capsys, "status", "--repo", repo, "--sprint", "sprint-7")
        assert code == 0
        assert "no data" in out

    def test_text_sections(self, slated_repo, capsys):
        assert run(capsys, "handoff", "--repo", slated_repo, "--spec", "0011", "--to", "Spec owner", "--by", "Priya")[0] == 0
        code, out = run(capsys, "status", "--repo", slated_repo, "--sprint", "S07", "--today", "2026-10-02")
        assert code == 0
        for label in ("Slate", "Readiness", "Verdicts", "Handoffs", "Mix", "WIP", "Decisions", "Build order", "Next up"):
            assert label in out
        assert "ready when:" in out
        assert "standalone mode" in out
        assert "0011 → Spec owner" in out
        header = next(ln for ln in out.splitlines() if ln.strip().startswith("spec"))
        assert header.split() == ["spec", "name", "risk", "type", "status", "DoR", "eng", "data", "next", "owner"]
        assert "feature" in out  # the type column is rendered, as the command doc promises
        assert "HIGH 1/1 · MEDIUM 1/1 · LOW 1/1" in out
        assert "Build order 0007 → 0009 → 0011" in out
        assert "Next up     0007" in out
        assert "no decision-log" in out

    def test_json_matches_build_view_and_has_no_per_person_key(self, slated_repo, capsys):
        code, out = run(capsys, "status", "--repo", slated_repo, "--sprint", "S07", "--json", "--today", "2026-10-02")
        assert code == 0
        view = json.loads(out)
        direct = json.loads(json.dumps(sprint.build_view(slated_repo, "S07", today=sm.ts_to_date("2026-10-02")), default=str))
        assert view == direct
        expected_top = {"sprint", "slate", "readiness", "verdicts_pending", "handoffs_open", "mix", "mix_warnings",
                        "wip", "build_order", "next_up", "dependency_gaps", "decisions", "carried_in", "has_data"}
        assert set(view) == expected_top
        keys = all_keys(view)
        for bad in ("by_person", "per_person", "by_owner", "by_actor", "by_by", "by_author", "per_owner"):
            assert bad not in keys
        assert not any(k.startswith("per_") for k in keys)
        assert view["readiness"] == {"ready": 0, "total": 3, "gaps": view["readiness"]["gaps"]}
        assert len(view["readiness"]["gaps"]) == 3
        assert view["wip"] == {"in_flight": 0, "cap": None}
        assert view["sprint"]["days"] == {"total": 10, "elapsed": 4, "remaining": 6}

    def test_verdict_age_counts_business_days_from_slated_event(self, slated_repo, capsys):
        path = slated_repo / ".sdlc" / "metrics" / "sprint-log.jsonl"
        rewritten = []
        for e in ledger(slated_repo):
            if e["event"] == "slated":
                e["ts"] = "2026-09-28T09:00:00+00:00"  # a Monday
            rewritten.append(json.dumps(e))
        path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
        view = sprint.build_view(slated_repo, "S07", today=sm.ts_to_date("2026-10-02"))  # Friday
        pend = {(p["spec"], p["lane"]): p["since_business_days"] for p in view["verdicts_pending"]}
        assert pend[("0007", "eng")] == 4
        assert len(pend) == 6

    def test_no_slated_event_reads_none_not_zero(self, sprint_repo, capsys):
        write_spec(sprint_repo, "0015", "hand-slated", "LOW", "ready", extra='sprint: "S07"\n')  # slated by hand: no ledger line
        view = sprint.build_view(sprint_repo, "S07", today=sm.ts_to_date("2026-10-02"))
        assert all(p["since_business_days"] is None for p in view["verdicts_pending"])
        code, out = run(capsys, "status", "--repo", sprint_repo, "--sprint", "S07")
        assert "no data" in out

    def test_wip_cap_from_flag_and_cadence_plan(self, slated_repo, capsys):
        write_spec(slated_repo, "0015", "flying", "LOW", "in-flight")
        view = sprint.build_view(slated_repo, "S07", wip_cap=1)
        assert view["wip"] == {"in_flight": 1, "cap": 1}
        assert view["next_up"] is None  # at the cap
        plan = slated_repo / ".sdlc" / "artifacts" / "03-foundation" / "cadence-plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("- **WIP cap:** no Orchestrator runs more than **2** concurrent agent streams.\n", encoding="utf-8")
        view = sprint.build_view(slated_repo, "S07")
        assert view["wip"]["cap"] == 2
        plan.write_text("- **WIP cap:** no Orchestrator runs more than **[2]** concurrent agent streams.\n", encoding="utf-8")
        assert sprint.build_view(slated_repo, "S07")["wip"]["cap"] is None  # bracketed template value = unset

    def test_decisions_from_decision_log(self, slated_repo, capsys):
        (slated_repo / ".sdlc" / "decision-log.md").write_text(
            "| id | decision | owner | opened | due | status |\n|---|---|---|---|---|---|\n"
            "| DL-04 | fail open or closed | Product lead | 2026-09-22 | 2026-09-24 | open |\n"
            "| DL-05 | copy tone | Design | 2026-10-01 | 2026-10-03 | open |\n", encoding="utf-8")
        view = sprint.build_view(slated_repo, "S07", today=sm.ts_to_date("2026-10-02"))
        assert view["decisions"]["open"] == 2
        assert [d["id"] for d in view["decisions"]["overdue"]] == ["DL-04"]
        assert view["decisions"]["overdue"][0]["owner"] == "Product lead"
        code, out = run(capsys, "status", "--repo", slated_repo, "--sprint", "S07", "--today", "2026-10-02")
        assert "DL-04" in out and "overdue" in out

    def test_closed_sprint_status_shows_its_slate_and_no_remaining_days(self, slated_repo, capsys, render_calls):
        merge(slated_repo, "0007")
        assert run(capsys, "close", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya", "--carry-to", "S08",
                   "--carry", "0009=late", "--drop", "0011=deprioritised")[0] == 0
        # frontmatter alone would now name only 0007 (0009 moved to S08, 0011 cleared) — the ledger restores the slate
        view = sprint.build_view(slated_repo, "S07", today=sm.ts_to_date("2026-10-02"))
        assert [r["id"] for r in view["slate"]] == ["0007", "0009", "0011"]
        assert view["sprint"]["state"] == "closed" and view["has_data"] is True
        assert sm.outcomes(view["slate"]) == {"kept": ["0007"], "open": ["0009", "0011"]}
        code, out = run(capsys, "status", "--repo", slated_repo, "--sprint", "S07", "--today", "2026-10-02")
        assert code == 0
        assert "closed · 2026-09-28 → 2026-10-09" in out and "closed by Priya" in out
        assert "business days remaining" not in out
        assert "Propose a slate" not in out
        assert "0009" in out and "0011" in out

    def test_closed_sprint_with_no_ledger_reads_closed_hint(self, slated_repo, capsys, render_calls):
        for sid in ("0007", "0009", "0011"):
            merge(slated_repo, sid)
        assert run(capsys, "close", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya")[0] == 0
        # hand-clear every spec's sprint and remove the ledger: the closed view is honest about having nothing
        for path in (slated_repo / "specs").glob("0*.md"):
            path.write_bytes(path.read_bytes().replace(b'sprint: "S07"', b'sprint: ""'))
        (slated_repo / ".sdlc" / "metrics" / "sprint-log.jsonl").unlink()
        code, out = run(capsys, "status", "--repo", slated_repo, "--sprint", "S07")
        assert code == 0
        assert "no data — closed; see .sdlc/reports/sprint-S07-review.html" in out
        assert "sprint.py new" in out and "Propose a slate" not in out

    def test_defaults_to_active_sprint(self, slated_repo, capsys):
        code, out = run(capsys, "status", "--repo", slated_repo, "--json")
        assert json.loads(out)["sprint"]["id"] == "S07"

    def test_dependency_gap_and_build_order(self, sprint_repo, capsys):
        write_spec(sprint_repo, "0015", "needs-nine", "HIGH", "ready", extra='depends_on: "0009"\n')
        assert run(capsys, "slate", "--repo", sprint_repo, "--sprint", "S07", "--by", "Priya",
                   "--spec", "0009", "--spec", "0015", "--spec", "0011")[0] == 0
        view = sprint.build_view(sprint_repo, "S07")
        assert view["build_order"].index("0009") < view["build_order"].index("0015")
        assert view["dependency_gaps"] == []
        assert run(capsys, "unslate", "--repo", sprint_repo, "--sprint", "S07", "--spec", "0009", "--by", "Priya", "--reason", "x")[0] == 0
        view = sprint.build_view(sprint_repo, "S07")
        assert any("outside the slate" in g for g in view["dependency_gaps"])


# --- handoff / ack --------------------------------------------------------------------------------------------

class TestHandoffAck:
    def test_handoff_sets_next_owner_and_logs(self, slated_repo, capsys):
        code, out = run(capsys, "handoff", "--repo", slated_repo, "--spec", "0011", "--to", "Spec owner", "--by", "Priya", "--note", "scope-out empty")
        assert code == 0
        assert fm_of(slated_repo / "specs" / "0011-copy-polish.md")["next_owner"] == "Spec owner"
        ev = ledger(slated_repo)[-1]
        assert ev["event"] == "handoff" and ev["to"] == "Spec owner" and ev["by"] == "Priya" and ev["note"] == "scope-out empty"
        view = sprint.build_view(slated_repo, "S07")
        assert view["handoffs_open"][0]["spec"] == "0011" and view["handoffs_open"][0]["to"] == "Spec owner"
        assert view["handoffs_open"][0]["since_business_days"] == 0

    def test_ack_clears_and_warns_on_different_name(self, slated_repo, capsys):
        assert run(capsys, "handoff", "--repo", slated_repo, "--spec", "0011", "--to", "Spec owner", "--by", "Priya")[0] == 0
        code, out = run(capsys, "ack", "--repo", slated_repo, "--spec", "0011", "--by", "Someone else")
        assert code == 0
        assert "WARNING" in out and "Spec owner" in out
        assert fm_of(slated_repo / "specs" / "0011-copy-polish.md")["next_owner"] == ""
        assert ledger(slated_repo)[-1]["event"] == "ack"
        assert sprint.build_view(slated_repo, "S07")["handoffs_open"] == []

    def test_ack_by_the_owner_has_no_warning(self, slated_repo, capsys):
        assert run(capsys, "handoff", "--repo", slated_repo, "--spec", "0011", "--to", "Spec owner", "--by", "Priya")[0] == 0
        code, out = run(capsys, "ack", "--repo", slated_repo, "--spec", "0011", "--by", "spec owner")
        assert code == 0 and "WARNING" not in out

    def test_ack_without_handoff_exit_1(self, slated_repo, capsys):
        code, out = run(capsys, "ack", "--repo", slated_repo, "--spec", "0011", "--by", "Priya")
        assert code == 1
        assert "no open handoff" in out

    def test_handoff_unknown_spec_exit_1(self, slated_repo, capsys):
        assert run(capsys, "handoff", "--repo", slated_repo, "--spec", "0099", "--to", "X", "--by", "Priya")[0] == 1

    def test_handoff_to_ai_or_malformed_name_refused_exit_2(self, slated_repo, capsys):
        assert run(capsys, "handoff", "--repo", slated_repo, "--spec", "0011", "--to", "the agent", "--by", "Priya")[0] == 2
        code, out = run(capsys, "handoff", "--repo", slated_repo, "--spec", "0011", "--to", "Priya #2", "--by", "Priya")
        assert code == 2 and "Refused" in out
        assert fm_of(slated_repo / "specs" / "0011-copy-polish.md").get("next_owner", "") == ""

    def test_handoff_works_on_an_unslated_spec(self, repo, capsys):
        assert run(capsys, "handoff", "--repo", repo, "--spec", "0013", "--to", "Eng lead", "--by", "Priya")[0] == 0
        assert fm_of(repo / "specs" / "0013-audit-fields.md")["next_owner"] == "Eng lead"

    def test_forbidden_field_exit_2(self, slated_repo, capsys):
        assert run(capsys, "handoff", "--repo", slated_repo, "--spec", "0011", "--to", "X", "--by", "Priya", "--field", "hours=4")[0] == 2
        assert run(capsys, "ack", "--repo", slated_repo, "--spec", "0011", "--by", "Priya", "--field", "effort=L")[0] == 2


# --- verdict -----------------------------------------------------------------------------------------------------

class TestVerdict:
    def test_records_verdict_and_ledger(self, slated_repo, capsys):
        code, out = run(capsys, "verdict", "--repo", slated_repo, "--spec", "0007", "--lane", "eng", "--verdict", "accepted", "--by", "Eng lead")
        assert code == 0
        assert fm_of(slated_repo / "specs" / "0007-warranty-lookup.md")["eng_review"] == "accepted"
        ev = ledger(slated_repo)[-1]
        assert ev == {**ev, "event": "verdict", "spec": "0007", "lane": "eng", "verdict": "accepted", "by": "Eng lead"}
        assert "reason" not in ev

    def test_na_only_for_data_and_only_with_reason(self, slated_repo, capsys):
        base = ["verdict", "--repo", slated_repo, "--spec", "0007", "--by", "Data lead"]
        code, out = run(capsys, *base, "--lane", "eng", "--verdict", "n-a", "--reason", "x")
        assert code == 1 and "data lane only" in out
        code, out = run(capsys, *base, "--lane", "data", "--verdict", "n-a")
        assert code == 1 and "--reason" in out
        assert fm_of(slated_repo / "specs" / "0007-warranty-lookup.md").get("data_review", "") == ""
        code, out = run(capsys, *base, "--lane", "data", "--verdict", "n-a", "--reason", "no data impact")
        assert code == 0
        assert fm_of(slated_repo / "specs" / "0007-warranty-lookup.md")["data_review"] == "n-a"
        assert ledger(slated_repo)[-1]["reason"] == "no data impact"

    def test_returned_without_reason_warns_but_records(self, slated_repo, capsys):
        code, out = run(capsys, "verdict", "--repo", slated_repo, "--spec", "0007", "--lane", "eng", "--verdict", "returned", "--by", "Eng lead")
        assert code == 0 and "WARNING" in out
        assert fm_of(slated_repo / "specs" / "0007-warranty-lookup.md")["eng_review"] == "returned"

    def test_invalid_lane_or_verdict_is_a_usage_error(self, slated_repo, capsys):
        assert run(capsys, "verdict", "--repo", slated_repo, "--spec", "0007", "--lane", "ux", "--verdict", "accepted", "--by", "X")[0] == 2
        assert run(capsys, "verdict", "--repo", slated_repo, "--spec", "0007", "--lane", "eng", "--verdict", "maybe", "--by", "X")[0] == 2

    def test_ai_actor_and_forbidden_field(self, slated_repo, capsys):
        assert run(capsys, "verdict", "--repo", slated_repo, "--spec", "0007", "--lane", "eng", "--verdict", "accepted", "--by", "copilot")[0] == 2
        assert run(capsys, "verdict", "--repo", slated_repo, "--spec", "0007", "--lane", "eng", "--verdict", "accepted", "--by", "Eng lead", "--field", "capacity=3")[0] == 2

    def test_unknown_spec_exit_1(self, slated_repo, capsys):
        assert run(capsys, "verdict", "--repo", slated_repo, "--spec", "0099", "--lane", "eng", "--verdict", "accepted", "--by", "X")[0] == 1


# --- ready / plan -------------------------------------------------------------------------------------------------

class TestReady:
    def test_gaps_exit_1_and_nothing_changes(self, slated_repo, capsys, render_calls):
        before_record = (slated_repo / ".sdlc" / "sprints" / "S07.md").read_bytes()
        before_ledger = ledger(slated_repo)
        code, out = run(capsys, "ready", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya")
        assert code == 1
        assert "NOT ready" in out
        assert "0011: status is draft, not ready" in out
        assert "eng_review is not recorded" in out
        assert "ready when:" in out
        assert (slated_repo / ".sdlc" / "sprints" / "S07.md").read_bytes() == before_record
        assert ledger(slated_repo) == before_ledger
        assert render_calls == []

    def test_empty_slate_is_a_gap(self, sprint_repo, capsys, render_calls):
        code, out = run(capsys, "ready", "--repo", sprint_repo, "--sprint", "S07", "--by", "Priya")
        assert code == 1 and "slate is empty" in out

    def test_ok_sets_state_ledger_and_renders_planning_page(self, slated_repo, capsys, render_calls):
        ready_up(slated_repo, capsys)
        code, out = run(capsys, "ready", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya")
        assert code == 0
        rec = sprint.read_sprint(slated_repo, "S07")
        assert rec["state"] == "ready" and rec["readied_by"] == "Priya"
        text = (slated_repo / ".sdlc" / "sprints" / "S07.md").read_text(encoding="utf-8")
        assert "state: ready  # planning | ready | closed" in text  # value replaced, trailing comment kept
        ev = ledger(slated_repo)[-1]
        assert ev["event"] == "ready" and ev["sprint"] == "S07" and ev["by"] == "Priya"
        assert render_calls == [{"repo": slated_repo.resolve(), "sprint": "S07", "kind": "planning", "output": None, "view": None}]
        assert "Planning page written" in out

    def test_data_na_counts_as_ready(self, slated_repo, capsys, render_calls):
        ready_up(slated_repo, capsys, specs=("0007", "0009"))
        path = slated_repo / "specs" / "0011-copy-polish.md"
        path.write_bytes(path.read_bytes().replace(b"status: draft", b"status: ready"))
        assert run(capsys, "verdict", "--repo", slated_repo, "--spec", "0011", "--lane", "eng", "--verdict", "accepted", "--by", "Eng lead")[0] == 0
        assert run(capsys, "verdict", "--repo", slated_repo, "--spec", "0011", "--lane", "data", "--verdict", "n-a", "--by", "Data lead", "--reason", "copy only")[0] == 0
        assert run(capsys, "ready", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya")[0] == 0

    def test_render_failure_warns_but_exit_0(self, slated_repo, capsys, monkeypatch):
        ready_up(slated_repo, capsys)

        def boom(*_a, **_k):
            raise RuntimeError("renderer unavailable")

        monkeypatch.setattr(sprint, "_render_page", boom)
        code, out = run(capsys, "ready", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya")
        assert code == 0
        assert "WARNING" in out and "renderer unavailable" in out
        assert sprint.read_sprint(slated_repo, "S07")["state"] == "ready"

    def test_ready_is_forward_only(self, slated_repo, capsys, render_calls):
        ready_up(slated_repo, capsys)
        assert run(capsys, "ready", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya")[0] == 0
        code, out = run(capsys, "ready", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya")
        assert code == 1 and "forward only" in out

    def test_refusals(self, slated_repo, capsys, render_calls):
        ready_up(slated_repo, capsys)
        assert run(capsys, "ready", "--repo", slated_repo, "--sprint", "S07", "--by", "automated pipeline")[0] == 2
        assert run(capsys, "ready", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya", "--field", "velocity=12")[0] == 2
        assert sprint.read_sprint(slated_repo, "S07")["state"] == "planning"

    def test_no_sprint_exit_1(self, repo, capsys):
        code, out = run(capsys, "ready", "--repo", repo, "--by", "Priya")
        assert code == 1 and "run `new` first" in out

    def test_real_renderer_writes_planning_page(self, slated_repo, capsys):
        """One integration pass against the real generate_sprint_report (lazy import path)."""
        pytest.importorskip("generate_sprint_report")
        ready_up(slated_repo, capsys)
        code, out = run(capsys, "ready", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya")
        assert code == 0
        page = slated_repo / ".sdlc" / "reports" / "sprint-S07-planning.html"
        assert page.is_file()
        assert "Never tracked" in page.read_text(encoding="utf-8")


class TestPlan:
    def test_renders_on_demand(self, slated_repo, capsys, render_calls):
        code, out = run(capsys, "plan", "--repo", slated_repo, "--sprint", "S07", "--output", "out/draft.html")
        assert code == 0
        assert render_calls[0]["kind"] == "planning" and render_calls[0]["output"] == Path("out/draft.html")
        assert "Planning page written" in out

    def test_missing_sprint_exit_1(self, repo, capsys, render_calls):
        code, out = run(capsys, "plan", "--repo", repo, "--sprint", "S99")
        assert code == 1 and render_calls == []


# --- close ------------------------------------------------------------------------------------------------------------

def merge(repo: Path, spec_id: str):
    path = next((repo / "specs").glob(f"{spec_id}-*.md"))
    text = path.read_bytes().decode("utf-8")
    text = text.replace("status: ready", "status: merged").replace("status: draft", "status: merged")
    path.write_bytes(text.encode("utf-8"))


class TestClose:
    def test_undecided_open_specs_exit_1(self, slated_repo, capsys, render_calls):
        merge(slated_repo, "0007")
        code, out = run(capsys, "close", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya")
        assert code == 1
        assert "undecided: 0009, 0011" in out
        assert sprint.read_sprint(slated_repo, "S07")["state"] == "planning"
        assert render_calls == []

    def test_carry_needs_carry_to(self, slated_repo, capsys, render_calls):
        merge(slated_repo, "0007")
        code, out = run(capsys, "close", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya",
                        "--carry", "0009=late", "--drop", "0011=deprioritised")
        assert code == 1 and "--carry-to" in out

    @pytest.mark.parametrize("argv, needle", [
        (["--carry-to", "S08", "--carry", "0009=late", "--drop", "0009=no", "--drop", "0011=x"], "both --carry and --drop"),
        (["--carry-to", "S08", "--carry", "0009", "--drop", "0011=x"], "SPEC=REASON"),
        (["--carry-to", "S08", "--carry", "0009=", "--drop", "0011=x"], "SPEC=REASON"),
        (["--carry-to", "S07", "--carry", "0009=late", "--drop", "0011=x"], "this sprint"),
        (["--carry-to", "eight", "--carry", "0009=late", "--drop", "0011=x"], "not a sprint id"),
        (["--drop", "0007=x", "--drop", "0009=y", "--drop", "0011=z"], "kept"),          # 0007 is merged
        (["--drop", "0013=x", "--drop", "0009=y", "--drop", "0011=z"], "not slated"),    # 0013 not in S07
        (["--drop", "0099=x", "--drop", "0009=y", "--drop", "0011=z"], "unknown spec"),
    ])
    def test_illegal_decisions_exit_1(self, slated_repo, capsys, render_calls, argv, needle):
        merge(slated_repo, "0007")
        code, out = run(capsys, "close", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya", *argv)
        assert code == 1, out
        assert needle in out
        assert sprint.read_sprint(slated_repo, "S07")["state"] == "planning"

    def test_close_carries_drops_and_writes_close_table(self, slated_repo, capsys, render_calls):
        merge(slated_repo, "0007")
        code, out = run(capsys, "close", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya", "--carry-to", "S08",
                        "--carry", "0009=dependency landed late", "--drop", "0011=deprioritised")
        assert code == 0
        assert "1 kept · 1 carried → S08 · 1 dropped" in out
        assert "WARNING: sprint S08 has no record yet" in out
        assert fm_of(slated_repo / "specs" / "0007-warranty-lookup.md")["sprint"] == "S07"  # kept stays
        assert fm_of(slated_repo / "specs" / "0009-case-guardrail.md")["sprint"] == "S08"   # carried moves
        assert fm_of(slated_repo / "specs" / "0011-copy-polish.md")["sprint"] == ""         # dropped clears
        rec = sprint.read_sprint(slated_repo, "S07")
        assert rec["state"] == "closed" and rec["closed_by"] == "Priya"
        text = (slated_repo / ".sdlc" / "sprints" / "S07.md").read_text(encoding="utf-8")
        close = check_spec.extract_section(check_spec.parse_frontmatter(text)[1], "Close")
        assert "| 0007 | kept | Priya | merged |" in close
        assert "| 0009 | carried → S08 | Priya | dependency landed late |" in close
        assert "| 0011 | dropped | Priya | deprioritised |" in close
        assert "Written by `sprint.py close`" in close  # the comment survives
        events = [e["event"] for e in ledger(slated_repo)[-3:]]
        assert events == ["carried", "dropped", "closed"]
        carried = [e for e in ledger(slated_repo) if e["event"] == "carried"][0]
        assert carried == {**carried, "sprint": "S07", "spec": "0009", "to_sprint": "S08", "by": "Priya", "reason": "dependency landed late"}
        assert render_calls[-1]["kind"] == "review" and render_calls[-1]["sprint"] == "S07"

    def test_close_renders_the_review_from_the_slate_it_reviewed(self, slated_repo, capsys, render_calls):
        merge(slated_repo, "0007")
        assert run(capsys, "close", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya", "--carry-to", "S08",
                   "--carry", "0009=late", "--drop", "0011=deprioritised")[0] == 0
        view = render_calls[-1]["view"]
        assert view is not None, "close must hand the renderer the view it computed before its own writes"
        assert [r["id"] for r in view["slate"]] == ["0007", "0009", "0011"]
        assert view["sprint"]["state"] == "closed" and view["sprint"]["closed_by"] == "Priya"

    def test_real_review_page_lists_every_slated_spec_and_counts_honestly(self, slated_repo, capsys):
        """HIGH finding: 0 kept / 4 open must read as such — never 'no data' — after carries moved the frontmatter on."""
        assert run(capsys, "slate", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya", "--spec", "0013",
                   "--override", "--reason", "fourth spec for the review")[0] == 0
        code, out = run(capsys, "close", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya", "--carry-to", "S08",
                        "--carry", "0007=blocked on DL-03", "--carry", "0009=late",
                        "--drop", "0011=deprioritised", "--drop", "0013=superseded")
        assert code == 0, out
        page_path = slated_repo / ".sdlc" / "reports" / "sprint-S07-review.html"
        assert page_path.is_file() and "Review page written to" in out
        page = page_path.read_text(encoding="utf-8")
        assert "Kept (merged): 0 &middot; open at close: 4" in page
        commitment = page[page.index("<h2>Commitment</h2>"):page.index("<h2>Mix and capacity</h2>")]
        for sid in ("0007", "0009", "0011", "0013"):
            assert f"<code>{sid}</code>" in commitment, sid
        assert "no data" not in commitment.split("<h3>Verdicts pending</h3>")[0]
        order = page[page.index("<h2>Build order and next up</h2>"):page.index("<h2>Dependencies</h2>")]
        assert "<code>0007</code>" in order and "<code>0013</code>" in order
        cards = page[page.index("<h2>Spec cards</h2>"):page.index("<h2>Open decisions</h2>")]
        assert cards.count('<article class="card"') == 4
        assert "carried → S08" in page and "blocked on DL-03" in page and "superseded" in page
        assert "Closed by" in page and "Priya" in page
        # and `status` on the closed sprint tells the same story
        code, out = run(capsys, "status", "--repo", slated_repo, "--sprint", "S07")
        assert code == 0 and "0013" in out and "business days remaining" not in out

    def test_carried_in_shows_on_the_next_sprint(self, slated_repo, capsys, render_calls):
        merge(slated_repo, "0007")
        assert run(capsys, "new", "--repo", slated_repo, "--sprint", "S08", "--goal", "Next", "--start", "2026-10-12", "--target", "3", "--by", "Priya")[0] == 0
        code, out = run(capsys, "close", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya", "--carry-to", "S08",
                        "--carry", "0009=late", "--carry", "0011=late too")
        assert code == 0 and "no record yet" not in out
        view = sprint.build_view(slated_repo, "S08")
        assert [c["spec"] for c in view["carried_in"]] == ["0009", "0011"]
        assert view["carried_in"][0] == {"spec": "0009", "from_sprint": "S07", "reason": "late"}
        assert [r["id"] for r in view["slate"]] == ["0009", "0011"]
        assert sprint.active_sprint_id(slated_repo) == "S08"

    def test_all_kept_needs_no_decisions(self, slated_repo, capsys, render_calls):
        for sid in ("0007", "0009", "0011"):
            merge(slated_repo, sid)
        code, out = run(capsys, "close", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya")
        assert code == 0 and "3 kept · 0 carried · 0 dropped" in out
        assert sprint.build_view(slated_repo, "S07")["sprint"]["state"] == "closed"

    def test_close_twice_exit_1(self, slated_repo, capsys, render_calls):
        for sid in ("0007", "0009", "0011"):
            merge(slated_repo, sid)
        assert run(capsys, "close", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya")[0] == 0
        code, out = run(capsys, "close", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya")
        assert code == 1 and "already closed" in out

    def test_refusals(self, slated_repo, capsys, render_calls):
        for sid in ("0007", "0009", "0011"):
            merge(slated_repo, sid)
        assert run(capsys, "close", "--repo", slated_repo, "--sprint", "S07", "--by", "Claude")[0] == 2
        assert run(capsys, "close", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya", "--field", "loc=1200")[0] == 2
        assert run(capsys, "close", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya", "--field", "pr_count=4")[0] == 2
        assert sprint.read_sprint(slated_repo, "S07")["state"] == "planning"

    def test_render_failure_warns_but_exit_0(self, slated_repo, capsys, monkeypatch):
        for sid in ("0007", "0009", "0011"):
            merge(slated_repo, sid)
        monkeypatch.setattr(sprint, "_render_page", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
        code, out = run(capsys, "close", "--repo", slated_repo, "--sprint", "S07", "--by", "Priya")
        assert code == 0 and "WARNING" in out and "disk full" in out
        assert sprint.read_sprint(slated_repo, "S07")["state"] == "closed"


# --- forbidden fields across every write verb ------------------------------------------------------------------

class TestForbiddenFields:
    def test_every_forbidden_key_is_refused(self):
        for key in sm.FORBIDDEN_FIELDS:
            with pytest.raises(sprint.Refused):
                sprint.parse_extra_fields([f"{key}=1"])
        with pytest.raises(sprint.Refused):
            sprint.parse_extra_fields(["Story Points=3"])  # case / separator normalised
        assert sprint.parse_extra_fields(["board=ADO 6"]) == {"board": "ADO 6"}

    def test_malformed_field_exit_1(self, sprint_repo, capsys):
        code, out = run(capsys, "handoff", "--repo", sprint_repo, "--spec", "0007", "--to", "X", "--by", "Priya", "--field", "nokey")
        assert code == 1 and "key=value" in out

    def test_extra_field_lands_on_the_ledger_line(self, sprint_repo, capsys):
        assert run(capsys, "handoff", "--repo", sprint_repo, "--spec", "0007", "--to", "Eng lead", "--by", "Priya", "--field", "channel=voice")[0] == 0
        assert ledger(sprint_repo)[-1]["channel"] == "voice"


# --- ledger drift ------------------------------------------------------------------------------------------------

class TestDrift:
    def test_ledger_append_failure_prints_drift_exit_1(self, sprint_repo, capsys):
        lp = sprint_repo / ".sdlc" / "metrics" / "sprint-log.jsonl"
        lp.unlink()
        lp.mkdir()  # a directory where the ledger should be -> the append raises OSError
        code, out = run(capsys, "handoff", "--repo", sprint_repo, "--spec", "0007", "--to", "Eng lead", "--by", "Priya")
        assert code == 1
        assert "DRIFT" in out
        assert fm_of(sprint_repo / "specs" / "0007-warranty-lookup.md")["next_owner"] == "Eng lead"  # frontmatter went first


# --- dual mode: --state ----------------------------------------------------------------------------------------------

class TestWorkflowMode:
    def test_state_missing_exit_1(self, tmp_path, capsys):
        code, out = run(capsys, "status", "--state", tmp_path / ".sdlc" / "state.yaml")
        assert code == 1 and "state file not found" in out

    def test_state_and_repo_are_mutually_exclusive(self, tmp_path, capsys):
        assert run(capsys, "status", "--state", tmp_path / "s.yaml", "--repo", tmp_path)[0] == 2

    def test_full_lifecycle_never_touches_state_yaml(self, state_yaml, tmp_path, capsys, render_calls):
        repo = tmp_path  # conftest: state at <tmp_path>/.sdlc/state.yaml -> repo root is tmp_path
        make_backlog(repo)
        state_bytes = state_yaml.read_bytes()
        S = ["--state", state_yaml]

        def check(code_out):
            code, out = code_out
            assert state_yaml.read_bytes() == state_bytes
            return code, out

        assert check(run(capsys, "new", *S, "--sprint", "S07", "--goal", "G", "--start", "2026-09-28", "--target", "3", "--mix", "HIGH:1,MEDIUM:1,LOW:1", "--by", "Priya"))[0] == 0
        assert (repo / ".sdlc" / "sprints" / "S07.md").is_file()
        assert check(run(capsys, "slate", *S, "--sprint", "S07"))[0] == 0
        assert check(run(capsys, "slate", *S, "--sprint", "S07", "--by", "Priya", "--spec", "0007", "--spec", "0009", "--spec", "0011"))[0] == 0
        code, out = check(run(capsys, "status", *S, "--sprint", "S07"))
        assert code == 0 and "standalone mode" not in out
        assert check(run(capsys, "handoff", *S, "--spec", "0011", "--to", "Spec owner", "--by", "Priya"))[0] == 0
        assert check(run(capsys, "ack", *S, "--spec", "0011", "--by", "Spec owner"))[0] == 0
        assert check(run(capsys, "unslate", *S, "--sprint", "S07", "--spec", "0011", "--by", "Priya", "--reason", "not yet"))[0] == 0
        assert check(run(capsys, "slate", *S, "--sprint", "S07", "--by", "Priya", "--spec", "0011"))[0] == 0
        assert check(run(capsys, "ready", *S, "--sprint", "S07", "--by", "Priya"))[0] == 1
        for sid in ("0007", "0009", "0011"):
            path = next((repo / "specs").glob(f"{sid}-*.md"))
            path.write_bytes(path.read_bytes().replace(b"status: draft", b"status: ready"))
            assert check(run(capsys, "verdict", *S, "--spec", sid, "--lane", "eng", "--verdict", "accepted", "--by", "Eng lead"))[0] == 0
            assert check(run(capsys, "verdict", *S, "--spec", sid, "--lane", "data", "--verdict", "accepted", "--by", "Data lead"))[0] == 0
        assert check(run(capsys, "ready", *S, "--sprint", "S07", "--by", "Priya"))[0] == 0
        assert check(run(capsys, "plan", *S, "--sprint", "S07"))[0] == 0
        merge(repo, "0007")
        assert check(run(capsys, "close", *S, "--sprint", "S07", "--by", "Priya", "--carry-to", "S08", "--carry", "0009=late", "--drop", "0011=x"))[0] == 0
        code, out = check(run(capsys, "status", *S, "--sprint", "S07", "--json"))
        assert json.loads(out)["sprint"]["state"] == "closed"
        assert state_yaml.read_bytes() == state_bytes
        assert (repo / ".sdlc" / "metrics" / "sprint-log.jsonl").is_file()
        assert (repo / ".sdlc" / "specs").exists() is False  # specs live in the repo, not under .sdlc/

    def test_workflow_detected_by_state_yaml_not_bare_sdlc(self, repo, capsys):
        (repo / ".sdlc").mkdir(exist_ok=True)
        assert sprint.is_workflow(repo) is False
        (repo / ".sdlc" / "state.yaml").write_text("version: '1.0'\n", encoding="utf-8")
        assert sprint.is_workflow(repo) is True


# --- pure helpers --------------------------------------------------------------------------------------------------

class TestHelpers:
    def test_replace_section_keeps_comment_and_neighbours(self):
        out = sprint.replace_section(SPRINT_TEMPLATE, "Slate", "| a |\n|---|")
        assert "## Slate\n<!-- Rendered by `sprint.py slate/unslate/ready/close`" in out
        assert "| a |\n|---|\n\n## Close" in out
        assert out.endswith(SPRINT_TEMPLATE[SPRINT_TEMPLATE.index("## Close"):])
        again = sprint.replace_section(out, "Slate", "| b |\n|---|")
        assert "| a |" not in again and "| b |" in again
        assert again.count("## Slate") == 1

    def test_replace_section_appends_when_heading_absent(self):
        out = sprint.replace_section("---\nsprint: \"S07\"\n---\n# Sprint S07\n", "Close", "| x |")
        assert out.endswith("\n## Close\n| x |\n")

    def test_set_sprint_field_bare_vs_quoted_and_comment(self):
        text = sprint.set_sprint_field(SPRINT_TEMPLATE, "state", "ready")
        assert "state: ready  # planning | ready | closed" in text
        text = sprint.set_sprint_field(text, "readied_by", "Priya")
        assert 'readied_by: "Priya"' in text
        text = sprint.set_sprint_field(text, "target", "6")
        assert "target: 6  # how many specs" in text
        with pytest.raises(sprint.Refused):
            sprint.set_sprint_field(text, "goal", 'say "hi"')

    def test_render_slate_table_no_data_when_empty(self):
        assert sprint.render_slate_table([]) == "no data"

    def test_find_spec_by_id_padded_id_and_filename(self, repo):
        rows = sprint.load_specs(repo)
        assert sprint.find_spec(rows, "0007")["id"] == "0007"
        assert sprint.find_spec(rows, "7")["id"] == "0007"
        assert sprint.find_spec(rows, "0009-case-guardrail.md")["id"] == "0009"
        assert sprint.find_spec(rows, "NNNN") is None
        assert sprint.find_spec(rows, "") is None

    def test_spec_row_dor_and_blocking(self, repo):
        path = write_spec(repo, "0015", "half-done", "LOW", "draft", body="\n# Spec\n\n## Goal\nx\n")
        row = sprint.spec_row(path, path.read_bytes().decode("utf-8"))
        assert row["dor"] == "NOT READY"
        assert any("Missing required section" in m for m in row["dor_blocking"])
        ready = sprint.spec_row(repo / "specs" / "0007-warranty-lookup.md", (repo / "specs" / "0007-warranty-lookup.md").read_text())
        assert ready["dor"] == "READY" and ready["dor_blocking"] == []


# --- the Studio contract: rel_path, one JSON document, plan --json (studio-improvements F13) -------------

STATUS_TOP_KEYS = {"sprint", "slate", "readiness", "verdicts_pending", "handoffs_open", "mix", "mix_warnings",
                   "wip", "build_order", "next_up", "dependency_gaps", "decisions", "carried_in", "has_data"}


class TestStudioContract:
    def test_slate_rows_and_the_sprint_carry_rel_path_beside_the_absolute_path(self, slated_repo, capsys):
        code, out = run(capsys, "status", "--repo", slated_repo, "--sprint", "S07", "--json")
        assert code == 0
        view = json.loads(out)
        assert view["sprint"]["rel_path"] == ".sdlc/sprints/S07.md"
        assert Path(view["sprint"]["path"]).is_absolute()
        assert [r["rel_path"] for r in view["slate"]] == [
            "specs/0007-warranty-lookup.md", "specs/0009-case-guardrail.md", "specs/0011-copy-polish.md"]
        for r in view["slate"]:
            assert Path(r["path"]).is_absolute()
            assert "\\" not in r["rel_path"]  # POSIX, whatever the host separator

    def test_rel_path_is_relative_to_the_repo_root_the_state_file_names(self, slated_repo, capsys):
        (slated_repo / ".sdlc" / "state.yaml").write_text("project_name: x\n", encoding="utf-8")
        code, out = run(capsys, "status", "--state", slated_repo / ".sdlc" / "state.yaml", "--sprint", "S07", "--json")
        assert code == 0
        assert [r["rel_path"] for r in json.loads(out)["slate"]][0] == "specs/0007-warranty-lookup.md"

    def test_rel_path_helper_falls_back_outside_the_repo(self, tmp_path):
        assert sprint.rel_path(tmp_path / "repo", tmp_path / "elsewhere" / "specs" / "0001-x.md") == "specs/0001-x.md"
        assert sprint.rel_path(None, Path("specs") / "0001-x.md") == "specs/0001-x.md"

    def test_malformed_sprint_under_json_is_exactly_one_document_with_has_data_false_and_a_note(self, repo, capsys):
        code, out = run(capsys, "status", "--repo", repo, "--sprint", "sprint-7", "--json")
        assert code == 0
        view = json.loads(out)  # exactly one document — json.loads would refuse prose or two documents
        assert view == {
            "sprint": None, "slate": [], "readiness": {"ready": 0, "total": 0, "gaps": []},
            "verdicts_pending": [], "handoffs_open": [], "mix": {}, "mix_warnings": [],
            "wip": {"in_flight": 0, "cap": None}, "build_order": [], "next_up": None, "dependency_gaps": [],
            "decisions": None, "carried_in": [], "has_data": False, "note": view["note"],
        }
        assert "sprint-7" in view["note"] and "not a sprint id" in view["note"]

    def test_unknown_sprint_under_json_is_one_document_with_a_note_naming_it(self, slated_repo, capsys):
        code, out = run(capsys, "status", "--repo", slated_repo, "--sprint", "S99", "--json")
        assert code == 0
        view = json.loads(out)
        assert view["sprint"] is None and view["slate"] == [] and view["has_data"] is False
        assert "S99" in view["note"]
        assert set(view) == STATUS_TOP_KEYS | {"note"}

    def test_no_sprint_at_all_under_json_carries_a_note(self, repo, capsys):
        code, out = run(capsys, "status", "--repo", repo, "--json")
        assert code == 0
        view = json.loads(out)
        assert view["sprint"] is None and view["has_data"] is False
        assert "no sprint record" in view["note"]

    def test_a_real_view_has_no_note(self, slated_repo, capsys):
        code, out = run(capsys, "status", "--repo", slated_repo, "--sprint", "S07", "--json")
        assert set(json.loads(out)) == STATUS_TOP_KEYS

    def test_status_text_output_is_unchanged_by_the_json_work(self, repo, slated_repo, capsys):
        # The text paths are what people and the slash command read; --json must not touch them.
        code, out = run(capsys, "status", "--repo", repo, "--sprint", "sprint-7")
        assert code == 0
        assert out == "'sprint-7' is not a sprint id (expected S07, S12, ...) — no data\n"
        code, out = run(capsys, "status", "--repo", slated_repo, "--sprint", "S99")
        assert code == 0
        assert out.startswith("Sprint: no data — no sprint record under ")
        assert "note" not in out and "rel_path" not in out

    def test_plan_json_prints_ok_sprint_kind_output_rel_output(self, slated_repo, capsys, render_calls):
        code, out = run(capsys, "plan", "--repo", slated_repo, "--sprint", "S07", "--json")
        assert code == 0
        doc = json.loads(out)
        assert doc == {"ok": True, "sprint": "S07", "kind": "planning",
                       "output": str(slated_repo / ".sdlc" / "reports" / "sprint-S07-planning.html"),
                       "rel_output": ".sdlc/reports/sprint-S07-planning.html"}
        assert render_calls[0]["kind"] == "planning"

    def test_plan_json_on_a_missing_sprint_is_ok_false_with_the_same_exit_code(self, repo, capsys, render_calls):
        code, out = run(capsys, "plan", "--repo", repo, "--sprint", "S99", "--json")
        assert code == 1 and render_calls == []
        doc = json.loads(out)
        assert doc["ok"] is False and "S99" in doc["error"]
        assert set(doc) == {"ok", "error"}

    def test_plan_json_on_a_render_failure_is_ok_false_not_a_traceback(self, slated_repo, capsys, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("disk full")
        monkeypatch.setattr(sprint, "_render_page", boom)
        code, out = run(capsys, "plan", "--repo", slated_repo, "--sprint", "S07", "--json")
        assert code == 1
        doc = json.loads(out)
        assert doc["ok"] is False and "disk full" in doc["error"]
        # ...and without --json the exception still surfaces as before (nothing swallowed)
        with pytest.raises(RuntimeError):
            sprint.main(["plan", "--repo", str(slated_repo), "--sprint", "S07"])

    def test_plan_text_output_is_unchanged(self, slated_repo, repo, capsys, render_calls):
        code, out = run(capsys, "plan", "--repo", slated_repo, "--sprint", "S07")
        assert code == 0
        assert out == f"Planning page written to: {slated_repo / '.sdlc' / 'reports' / 'sprint-S07-planning.html'}\n"
        code, out = run(capsys, "plan", "--repo", repo, "--sprint", "S99")
        assert code == 1 and out.startswith("Error: ") and "S99" in out and "{" not in out

    def test_the_text_status_renders_the_same_with_rel_path_on_the_rows(self, slated_repo, capsys):
        # rel_path is an extra key on the dict; the text table lists fixed columns and must not grow one.
        code, out = run(capsys, "status", "--repo", slated_repo, "--sprint", "S07", "--today", "2026-10-02")
        assert code == 0
        header = next(ln for ln in out.splitlines() if ln.strip().startswith("spec"))
        assert header.split() == ["spec", "name", "risk", "type", "status", "DoR", "eng", "data", "next", "owner"]
        assert "rel_path" not in out


# --- list (read; togo-command-center §2.5 row 1) ---------------------------------------------------------------

LIST_TOP_KEYS = {"sprints", "active", "count"}
LIST_ROW_KEYS = {"id", "state", "goal", "start", "end", "ordinal"}


class TestList:
    def test_empty_dir_is_one_document_with_no_data(self, repo, capsys):
        code, out = run(capsys, "list", "--repo", repo, "--json")
        assert code == 0
        assert json.loads(out) == {"sprints": [], "active": None, "count": 0}
        code, out = run(capsys, "list", "--repo", repo)
        assert code == 0 and out.startswith("Sprints: no data — no sprint record under ")

    def test_three_sprints_one_closed_ordinals_and_active(self, sprint_repo, capsys, render_calls):
        for sid, start in (("S08", "2026-10-12"), ("S09", "2026-10-26")):
            assert run(capsys, "new", "--repo", sprint_repo, "--sprint", sid, "--goal", f"Goal {sid}", "--start", start,
                       "--target", "2", "--by", "Priya")[0] == 0
        assert run(capsys, "close", "--repo", sprint_repo, "--sprint", "S09", "--by", "Priya")[0] == 0  # empty slate closes clean
        code, out = run(capsys, "list", "--repo", sprint_repo, "--json")
        assert code == 0
        doc = json.loads(out)
        assert set(doc) == LIST_TOP_KEYS and doc["count"] == 3
        assert [s["id"] for s in doc["sprints"]] == ["S07", "S08", "S09"]
        assert [s["ordinal"] for s in doc["sprints"]] == [1, 2, 3]
        assert [s["state"] for s in doc["sprints"]] == ["planning", "planning", "closed"]
        assert doc["active"] == "S08"  # the highest NON-closed sprint, not the highest id
        assert doc["active"] == sprint.active_sprint_id(sprint_repo)
        for s in doc["sprints"]:
            assert set(s) == LIST_ROW_KEYS
        assert doc["sprints"][0] == {"id": "S07", "state": "planning", "goal": "Warranty lookup answers in one turn",
                                     "start": "2026-09-28", "end": "2026-10-09", "ordinal": 1}

    def test_malformed_record_reads_state_null_not_planning(self, sprint_repo, capsys):
        (sprint_repo / ".sdlc" / "sprints" / "S08.md").write_text("# Sprint S08\n\nno frontmatter at all\n", encoding="utf-8")
        (sprint_repo / ".sdlc" / "sprints" / "S09.md").write_text('---\nsprint: "S09"\nstate: done\n---\n', encoding="utf-8")
        code, out = run(capsys, "list", "--repo", sprint_repo, "--json")
        assert code == 0
        rows = {s["id"]: s for s in json.loads(out)["sprints"]}
        assert rows["S08"]["state"] is None and rows["S08"]["goal"] == "" and rows["S08"]["ordinal"] == 2
        assert rows["S09"]["state"] is None and rows["S09"]["ordinal"] == 3
        assert rows["S07"]["state"] == "planning"

    def test_text_mode_is_one_line_per_sprint(self, sprint_repo, capsys):
        assert run(capsys, "new", "--repo", sprint_repo, "--sprint", "S08", "--goal", "Next", "--start", "2026-10-12",
                   "--target", "2", "--by", "Priya")[0] == 0
        code, out = run(capsys, "list", "--repo", sprint_repo)
        assert code == 0
        lines = out.splitlines()
        assert lines[0].startswith("Sprints: 2 record(s) under ") and lines[0].endswith("· active S08")
        assert len(lines) == 3
        assert lines[1].split()[:3] == ["S07", "#1", "planning"] and "Warranty lookup answers in one turn" in lines[1]
        assert lines[2].split()[:3] == ["S08", "#2", "planning"] and "2026-10-12 → 2026-10-23" in lines[2]

    def test_list_only_matches_sprint_ids(self, sprint_repo, capsys):
        (sprint_repo / ".sdlc" / "sprints" / "notes.md").write_text("# notes\n", encoding="utf-8")
        code, out = run(capsys, "list", "--repo", sprint_repo, "--json")
        assert [s["id"] for s in json.loads(out)["sprints"]] == ["S07"]

    def test_status_json_is_unchanged_by_list(self, slated_repo, capsys):
        assert run(capsys, "list", "--repo", slated_repo, "--json")[0] == 0
        code, out = run(capsys, "status", "--repo", slated_repo, "--sprint", "S07", "--json")
        assert code == 0 and set(json.loads(out)) == STATUS_TOP_KEYS

    def test_help_advertises_the_capability_flags(self, capsys):
        code, out = run(capsys, "list", "--help")
        assert code == 0 and all(f in out for f in ("--repo", "--state", "--json"))
        assert "--by" not in out and "--field" not in out  # a read, never a write


# --- log (read; togo-command-center §2.5 row 2) ----------------------------------------------------------------

LOG_TOP_KEYS = {"events", "count", "since", "path", "exists", "skipped"}


def write_ledger_lines(repo: Path, lines: list[str]) -> Path:
    path = repo / ".sdlc" / "metrics" / "sprint-log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(ln + "\n" for ln in lines), encoding="utf-8")
    return path


class TestLog:
    def test_missing_ledger_reads_exists_false_never_an_error(self, repo, capsys):
        code, out = run(capsys, "log", "--repo", repo, "--json")
        assert code == 0
        doc = json.loads(out)
        assert doc == {"events": [], "count": 0, "since": None,
                       "path": str(repo / ".sdlc" / "metrics" / "sprint-log.jsonl"), "exists": False, "skipped": 0}
        code, out = run(capsys, "log", "--repo", repo)
        assert code == 0 and out.startswith("Sprint log: no data — no ledger at ")

    def test_lines_are_verbatim_and_no_aggregate_key_exists(self, slated_repo, capsys):
        code, out = run(capsys, "log", "--repo", slated_repo, "--json")
        assert code == 0
        doc = json.loads(out)
        assert set(doc) == LOG_TOP_KEYS
        assert doc["events"] == ledger(slated_repo)  # exactly the lines on disk, in file order, nothing reshaped
        assert doc["count"] == len(doc["events"]) == 4 and doc["exists"] is True and doc["skipped"] == 0
        assert [e["event"] for e in doc["events"]] == ["sprint_new", "slated", "slated", "slated"]
        assert not ({"velocity", "points", "per_person", "by_person", "totals"} & all_keys(doc))

    def test_since_is_inclusive_at_midnight_and_keeps_undated_lines(self, repo, capsys):
        write_ledger_lines(repo, [
            json.dumps({"ts": "2026-09-30T23:59:59+00:00", "event": "slated", "sprint": "S07", "spec": "0007", "by": "Priya"}),
            json.dumps({"ts": "2026-10-01T00:00:00+00:00", "event": "slated", "sprint": "S07", "spec": "0009", "by": "Priya"}),
            json.dumps({"ts": "2026-10-02T09:00:00+00:00", "event": "handoff", "spec": "0009", "to": "Sam", "by": "Priya"}),
            json.dumps({"event": "ack", "spec": "0009", "by": "Sam"}),  # undated: cannot be placed, so it is kept
        ])
        code, out = run(capsys, "log", "--repo", repo, "--since", "2026-10-01", "--json")
        assert code == 0
        doc = json.loads(out)
        assert doc["since"] == "2026-10-01" and doc["count"] == 3
        assert [e.get("spec") for e in doc["events"]] == ["0009", "0009", "0009"]
        assert doc["events"][-1] == {"event": "ack", "spec": "0009", "by": "Sam"}

    def test_sprint_filter_keeps_only_lines_naming_that_sprint(self, repo, capsys):
        write_ledger_lines(repo, [
            json.dumps({"ts": "2026-10-01T00:00:00+00:00", "event": "sprint_new", "sprint": "S07", "by": "Priya"}),
            json.dumps({"ts": "2026-10-01T00:00:01+00:00", "event": "sprint_new", "sprint": "S08", "by": "Priya"}),
            json.dumps({"ts": "2026-10-02T09:00:00+00:00", "event": "handoff", "spec": "0009", "to": "Sam", "by": "Priya"}),
        ])
        code, out = run(capsys, "log", "--repo", repo, "--sprint", "S08", "--json")
        doc = json.loads(out)
        assert code == 0 and doc["count"] == 1 and doc["events"][0]["sprint"] == "S08"
        code, out = run(capsys, "log", "--repo", repo, "--sprint", "S99", "--json")
        assert code == 0 and json.loads(out)["events"] == []

    def test_corrupt_lines_are_counted_in_skipped_not_dropped_silently(self, repo, capsys):
        write_ledger_lines(repo, [
            json.dumps({"ts": "2026-10-01T00:00:00+00:00", "event": "sprint_new", "sprint": "S07", "by": "Priya"}),
            "not json", "", "[1, 2]", "   ",
        ])
        code, out = run(capsys, "log", "--repo", repo, "--json")
        doc = json.loads(out)
        assert code == 0 and doc["count"] == 1 and doc["skipped"] == 2  # blank lines are neither
        code, out = run(capsys, "log", "--repo", repo)
        assert code == 0 and "1 event(s)" in out.splitlines()[0] and "2 unreadable line(s) skipped" in out.splitlines()[0]

    def test_read_ledger_behaviour_is_unchanged(self, repo):
        write_ledger_lines(repo, [json.dumps({"ts": "t", "event": "ready", "sprint": "S07"}), "garbage"])
        assert sprint.read_ledger(repo) == [{"ts": "t", "event": "ready", "sprint": "S07"}]
        assert sprint.read_ledger_lines(repo) == ([{"ts": "t", "event": "ready", "sprint": "S07"}], 1)

    def test_bad_since_is_exit_1_like_today(self, repo, capsys):
        code, out = run(capsys, "log", "--repo", repo, "--since", "yesterday")
        assert code == 1 and "--since must be an ISO date" in out

    def test_text_mode_one_line_per_event(self, slated_repo, capsys):
        code, out = run(capsys, "log", "--repo", slated_repo, "--sprint", "S07", "--since", "2020-01-01")
        assert code == 0
        lines = out.splitlines()
        assert lines[0].startswith("Sprint log: 4 event(s) since 2020-01-01 for S07 — ")
        assert len(lines) == 5
        assert lines[1].split()[1] == "sprint_new" and "sprint=S07" in lines[1] and "by=Priya" in lines[1]
        assert lines[2].split()[1] == "slated" and "spec=0007" in lines[2]

    def test_help_advertises_the_capability_flags(self, capsys):
        code, out = run(capsys, "log", "--help")
        assert code == 0 and all(f in out for f in ("--since", "--sprint", "--json"))
        assert "--by" not in out and "--field" not in out


# --- carry (write; togo-command-center §2.5 row 3) -------------------------------------------------------------

def slate_table_ids(record: Path) -> list[str]:
    section = check_spec.extract_section(record.read_text(encoding="utf-8"), "Slate") or ""
    return [ln.split("|")[1].strip() for ln in section.splitlines()
            if ln.startswith("| ") and not ln.startswith("| spec")]


class TestCarry:
    @pytest.fixture
    def two_sprints(self, slated_repo, capsys):
        """S07 slated with 0007/0009/0011; S08 open with target 2 and nothing slated."""
        assert run(capsys, "new", "--repo", slated_repo, "--sprint", "S08", "--goal", "Next", "--start", "2026-10-12",
                   "--target", "2", "--by", "Priya")[0] == 0
        return slated_repo

    def test_carry_rewrites_sprint_both_slate_tables_and_one_event(self, two_sprints, capsys):
        repo = two_sprints
        n_before = len(ledger(repo))
        code, out = run(capsys, "carry", "--repo", repo, "--spec", "0011", "--to", "S08", "--reason", "vendor sandbox slipped", "--by", "Priya")
        assert code == 0
        assert out.splitlines()[0] == "Carried 0011: S07 → S08 (by Priya): vendor sandbox slipped"
        assert fm_of(repo / "specs" / "0011-copy-polish.md")["sprint"] == "S08"
        assert slate_table_ids(repo / ".sdlc" / "sprints" / "S07.md") == ["0007", "0009"]
        assert slate_table_ids(repo / ".sdlc" / "sprints" / "S08.md") == ["0011"]
        events = ledger(repo)
        assert len(events) == n_before + 1
        e = events[-1]
        assert {k: v for k, v in e.items() if k != "ts"} == {
            "event": "carried", "sprint": "S07", "spec": "0011", "to_sprint": "S08", "by": "Priya",
            "reason": "vendor sandbox slipped"}

    def test_event_field_set_equals_the_close_paths(self, two_sprints, capsys, render_calls):
        repo = two_sprints
        assert run(capsys, "carry", "--repo", repo, "--spec", "0011", "--to", "S08", "--reason", "slipped", "--by", "Priya")[0] == 0
        mid_sprint = ledger(repo)[-1]
        merge(repo, "0007")
        assert run(capsys, "close", "--repo", repo, "--sprint", "S07", "--by", "Priya", "--carry-to", "S08", "--carry", "0009=late")[0] == 0
        at_close = next(e for e in reversed(ledger(repo)) if e["event"] == "carried" and e["spec"] == "0009")
        assert set(mid_sprint) == set(at_close)
        assert list(mid_sprint) == list(at_close)  # same key order too — one shape, two paths

    def test_status_on_the_receiving_sprint_lists_carried_in_with_the_reason(self, two_sprints, capsys):
        repo = two_sprints
        assert run(capsys, "carry", "--repo", repo, "--spec", "0011", "--to", "S08", "--reason", "slipped", "--by", "Priya")[0] == 0
        code, out = run(capsys, "status", "--repo", repo, "--sprint", "S08", "--json")
        view = json.loads(out)
        assert code == 0
        assert view["carried_in"] == [{"spec": "0011", "from_sprint": "S07", "reason": "slipped"}]
        assert [r["id"] for r in view["slate"]] == ["0011"]
        code, out = run(capsys, "status", "--repo", repo, "--sprint", "S07", "--json")
        assert [r["id"] for r in json.loads(out)["slate"]] == ["0007", "0009"]

    def test_spec_bytes_outside_the_sprint_key_are_untouched(self, two_sprints, capsys):
        repo = two_sprints
        path = repo / "specs" / "0011-copy-polish.md"
        before_body, before_verdict = body_of(path), verdict_of(path)
        assert run(capsys, "carry", "--repo", repo, "--spec", "0011", "--to", "S08", "--reason", "slipped", "--by", "Priya")[0] == 0
        assert body_of(path) == before_body and verdict_of(path) == before_verdict

    @pytest.mark.parametrize("argv, needle", [
        (["--spec", "0013", "--to", "S08", "--reason", "x"], "is not in a sprint"),
        (["--spec", "0007", "--to", "S07", "--reason", "x"], "carry forward, not in place"),
        (["--spec", "0007", "--to", "S09", "--reason", "x"], "sprint S09 does not exist"),
        (["--spec", "0007", "--to", "sprint-8", "--reason", "x"], "is not a sprint id"),
        (["--spec", "0007", "--to", "S08", "--reason", "   "], "--reason is required"),
        (["--spec", "0099", "--to", "S08", "--reason", "x"], "unknown spec"),
    ])
    def test_illegal_carries_exit_1_and_write_nothing(self, two_sprints, capsys, argv, needle):
        repo = two_sprints
        before = {p: p.read_bytes() for p in list((repo / "specs").iterdir()) + list((repo / ".sdlc" / "sprints").iterdir())}
        n = len(ledger(repo))
        code, out = run(capsys, "carry", "--repo", repo, *argv, "--by", "Priya")
        assert code == 1 and out.startswith("Error: ") and needle in out
        assert {p: p.read_bytes() for p in before} == before and len(ledger(repo)) == n

    def test_merged_spec_cannot_be_carried(self, two_sprints, capsys):
        merge(two_sprints, "0007")
        code, out = run(capsys, "carry", "--repo", two_sprints, "--spec", "0007", "--to", "S08", "--reason", "x", "--by", "Priya")
        assert code == 1 and "is merged" in out
        assert fm_of(two_sprints / "specs" / "0007-warranty-lookup.md")["sprint"] == "S07"

    def test_into_a_closed_sprint_is_exit_1(self, two_sprints, capsys, render_calls):
        assert run(capsys, "close", "--repo", two_sprints, "--sprint", "S08", "--by", "Priya")[0] == 0
        code, out = run(capsys, "carry", "--repo", two_sprints, "--spec", "0011", "--to", "S08", "--reason", "x", "--by", "Priya")
        assert code == 1 and "sprint S08 is closed" in out

    def test_out_of_a_closed_sprint_is_exit_1_its_slate_is_a_record(self, two_sprints, capsys, render_calls):
        repo = two_sprints
        merge(repo, "0007")
        assert run(capsys, "close", "--repo", repo, "--sprint", "S07", "--by", "Priya", "--carry-to", "S08",
                   "--carry", "0009=late", "--drop", "0011=x")[0] == 0
        path = repo / "specs" / "0013-audit-fields.md"  # a hand edit puts a spec back into the closed sprint
        path.write_bytes(sprint.set_spec_key(path.read_bytes().decode("utf-8"), "sprint", "S07").encode("utf-8"))
        code, out = run(capsys, "carry", "--repo", repo, "--spec", "0013", "--to", "S08", "--reason", "x", "--by", "Priya")
        assert code == 1 and "sprint S07 is closed" in out and "record" in out
        assert fm_of(path)["sprint"] == "S07"

    def test_ai_actor_and_forbidden_field_exit_2_nothing_written(self, two_sprints, capsys):
        repo = two_sprints
        n = len(ledger(repo))
        code, out = run(capsys, "carry", "--repo", repo, "--spec", "0011", "--to", "S08", "--reason", "x", "--by", "Claude")
        assert code == 2 and "reads as an AI" in out
        code, out = run(capsys, "carry", "--repo", repo, "--spec", "0011", "--to", "S08", "--reason", "x", "--by", "Priya", "--field", "points=3")
        assert code == 2 and "activity metric" in out
        assert fm_of(repo / "specs" / "0011-copy-polish.md")["sprint"] == "S07" and len(ledger(repo)) == n

    def test_over_target_warns_but_does_not_block(self, two_sprints, capsys):
        repo = two_sprints
        for sid in ("0007", "0009", "0011"):
            code, out = run(capsys, "carry", "--repo", repo, "--spec", sid, "--to", "S08", "--reason", "re-plan", "--by", "Priya")
            assert code == 0
        assert "WARNING: S08 now holds 3 specs, over its target of 2" in out
        assert slate_table_ids(repo / ".sdlc" / "sprints" / "S08.md") == ["0007", "0009", "0011"]
        assert slate_table_ids(repo / ".sdlc" / "sprints" / "S07.md") == []

    def test_ledger_append_failure_prints_drift_exit_1(self, two_sprints, capsys):
        repo = two_sprints
        lp = repo / ".sdlc" / "metrics" / "sprint-log.jsonl"
        lp.unlink()
        lp.mkdir()
        code, out = run(capsys, "carry", "--repo", repo, "--spec", "0011", "--to", "S08", "--reason", "x", "--by", "Priya")
        assert code == 1 and "DRIFT" in out
        assert fm_of(repo / "specs" / "0011-copy-polish.md")["sprint"] == "S08"  # frontmatter went first

    def test_help_advertises_the_capability_flags(self, capsys):
        code, out = run(capsys, "carry", "--help")
        assert code == 0 and all(f in out for f in ("--spec", "--to", "--reason", "--by", "--field"))


# --- edit (write; togo-command-center §2.5 row 4) --------------------------------------------------------------

class TestEdit:
    OLD = "Warranty lookup answers in one turn"
    NEW = "Warranty lookup answers in one turn, every time"

    def test_goal_replaced_in_frontmatter_and_section_all_else_byte_identical(self, sprint_repo, capsys):
        record = sprint_repo / ".sdlc" / "sprints" / "S07.md"
        before = record.read_bytes().decode("utf-8")
        assert before.count(self.OLD) == 2  # frontmatter goal: + the ## Goal section
        code, out = run(capsys, "edit", "--repo", sprint_repo, "--sprint", "S07", "--goal", self.NEW, "--by", "Priya")
        assert code == 0 and out == f"Sprint S07 goal set by Priya: {self.NEW}\n"
        after = record.read_bytes().decode("utf-8")
        assert after == before.replace(self.OLD, self.NEW)
        assert fm_of(record)["goal"] == self.NEW
        assert (check_spec.extract_section(after, "Goal") or "").strip() == self.NEW

    def test_status_json_and_log_json_reflect_the_edit(self, slated_repo, capsys):
        assert run(capsys, "edit", "--repo", slated_repo, "--sprint", "S07", "--goal", self.NEW, "--by", "Priya")[0] == 0
        code, out = run(capsys, "status", "--repo", slated_repo, "--sprint", "S07", "--json")
        assert code == 0 and json.loads(out)["sprint"]["goal"] == self.NEW
        code, out = run(capsys, "log", "--repo", slated_repo, "--json")
        last = json.loads(out)["events"][-1]
        assert {k: v for k, v in last.items() if k != "ts"} == {"event": "sprint_edited", "sprint": "S07", "field": "goal", "by": "Priya"}
        code, out = run(capsys, "status", "--repo", slated_repo, "--sprint", "S07")
        assert code == 0 and f'Sprint S07 — "{self.NEW}"' in out

    def test_unchanged_goal_writes_nothing(self, sprint_repo, capsys):
        record = sprint_repo / ".sdlc" / "sprints" / "S07.md"
        before, n = record.read_bytes(), len(ledger(sprint_repo))
        code, out = run(capsys, "edit", "--repo", sprint_repo, "--sprint", "S07", "--goal", f"  {self.OLD} ", "--by", "Priya")
        assert code == 0 and "unchanged" in out
        assert record.read_bytes() == before and len(ledger(sprint_repo)) == n

    def test_closed_sprint_is_exit_1(self, sprint_repo, capsys, render_calls):
        assert run(capsys, "close", "--repo", sprint_repo, "--sprint", "S07", "--by", "Priya")[0] == 0
        record = sprint_repo / ".sdlc" / "sprints" / "S07.md"
        before = record.read_bytes()
        code, out = run(capsys, "edit", "--repo", sprint_repo, "--sprint", "S07", "--goal", self.NEW, "--by", "Priya")
        assert code == 1 and "sprint S07 is closed" in out and record.read_bytes() == before

    @pytest.mark.parametrize("argv, needle", [
        (["--sprint", "S07", "--goal", "   "], "--goal must be a non-empty sentence"),
        (["--sprint", "S99", "--goal", "x"], "sprint S99 does not exist"),
        (["--sprint", "sprint-7", "--goal", "x"], "is not a sprint id"),
    ])
    def test_illegal_edits_exit_1(self, sprint_repo, capsys, argv, needle):
        n = len(ledger(sprint_repo))
        code, out = run(capsys, "edit", "--repo", sprint_repo, *argv, "--by", "Priya")
        assert code == 1 and out.startswith("Error: ") and needle in out and len(ledger(sprint_repo)) == n

    def test_ai_name_hash_in_goal_and_forbidden_field_exit_2(self, sprint_repo, capsys):
        record = sprint_repo / ".sdlc" / "sprints" / "S07.md"
        before, n = record.read_bytes(), len(ledger(sprint_repo))
        code, out = run(capsys, "edit", "--repo", sprint_repo, "--sprint", "S07", "--goal", self.NEW, "--by", "Claude")
        assert code == 2 and "reads as an AI" in out
        code, out = run(capsys, "edit", "--repo", sprint_repo, "--sprint", "S07", "--goal", "ship it # fast", "--by", "Priya")
        assert code == 2 and out.startswith("Refused:") and "'#'" in out
        code, out = run(capsys, "edit", "--repo", sprint_repo, "--sprint", "S07", "--goal", self.NEW, "--by", "Priya", "--field", "velocity=9")
        assert code == 2 and "activity metric" in out
        assert record.read_bytes() == before and len(ledger(sprint_repo)) == n

    def test_sprint_is_required(self, sprint_repo, capsys):
        assert run(capsys, "edit", "--repo", sprint_repo, "--goal", "x", "--by", "Priya")[0] == 2  # argparse usage error

    def test_help_advertises_the_capability_flags(self, capsys):
        code, out = run(capsys, "edit", "--help")
        assert code == 0 and all(f in out for f in ("--sprint", "--goal", "--by", "--field"))


class TestNewVerbsInWorkflowMode:
    def test_list_log_carry_edit_never_touch_state_yaml(self, state_yaml, tmp_path, capsys):
        repo = tmp_path
        make_backlog(repo)
        state_bytes = state_yaml.read_bytes()
        S = ["--state", state_yaml]
        assert run(capsys, "new", *S, "--sprint", "S07", "--goal", "G", "--start", "2026-09-28", "--target", "3", "--by", "Priya")[0] == 0
        assert run(capsys, "new", *S, "--sprint", "S08", "--goal", "H", "--start", "2026-10-12", "--target", "3", "--by", "Priya")[0] == 0
        assert run(capsys, "slate", *S, "--sprint", "S07", "--by", "Priya", "--spec", "0007")[0] == 0
        assert run(capsys, "edit", *S, "--sprint", "S07", "--goal", "G2", "--by", "Priya")[0] == 0
        assert run(capsys, "carry", *S, "--spec", "0007", "--to", "S08", "--reason", "r", "--by", "Priya")[0] == 0
        code, out = run(capsys, "list", *S, "--json")
        assert code == 0 and json.loads(out)["count"] == 2
        code, out = run(capsys, "log", *S, "--json")
        assert code == 0 and [e["event"] for e in json.loads(out)["events"]][-2:] == ["sprint_edited", "carried"]
        assert state_yaml.read_bytes() == state_bytes
