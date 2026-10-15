"""B3-P4 -- the write verbs of the Azure Boards mirror's CLI (`ado_sync.py`): apply, link-pr, iteration bind, posture,
comment, and `plan --no-comments` (the B2 read verbs that append to the ledger keep their B2 exit codes on `DRIFT`).

What this pins, and why each line exists (build kit sections 1 K9, 2 house rules 3, 4 and 7, 4 verb table, 5 card
B3-P4; spec 0036; design D40-D43 and section 7):
  * every write verb refuses an AI or an agent as `--by` (exit 2) with ZERO az spawns and nothing written; `apply` and
    `link-pr` also refuse posture `plan-only` (exit 2, zero spawns); `posture` itself, `iteration bind` (a local config
    edit) and `comment` (a local plan file) work under `plan-only`, and `comment` says `apply not offered in this clone`;
  * `apply --confirm <12hex> --by <human> [--limit N]` hands the plan file to `ado_sync_apply.apply_plan` and reports
    its result: exit 0 all applied, 1 a row failed / stale hash / plan missing / `DRIFT`, 2 a whole-plan refusal
    (identity, forbidden field, first seed, a refused comment row) with nothing sent; a re-`plan` after an apply that
    landed lists no op;
  * `plan` now drafts the comment rows of the repository's own ledgers (a `skipped` row is shown, never planned);
    `--no-comments` drops them; the field-op counts and cost keys keep the B2 shape;
  * `comment <ref|#id> --message=<text>` writes a ONE-row plan file and nothing else (no az call), exit 0 even under
    `plan-only`; a message with `"`, a newline, `$(`, non-ASCII text or a leading `-` reaches the plan row, and then the
    board's request BODY, byte for byte, and never an az argv element;
  * a failed ledger append is `DRIFT: ...` and exit 1 on every write verb (house rule 7), and on `pull` and
    `discussion gc` as in B2; `plan` and `show --fetch` print the `DRIFT:` line and still exit 0 (kit K9 and the
    verb table: `plan`/`status`/`drift`/`show` exit 0 always -- house rule 4);
  * no ledger line, plan file or `--json` result carries an e-mail address or a GUID, and no az text reaches an
    `apply` or `link-pr` result (spec 0036's Checking Plan); every az argv carries `--detect false`; `--help` touches
    nothing.

Nothing here spawns `az`: `boards_env` forbids it at the seam and `board` stands a `FakeBoardsAz(writes=True)` in for
`run_az`. The people in the fixtures are fictional; the one address is on example.com.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import HAND_WRITTEN_PROCESS
from tests.ado_boards_fixtures import FakeBoardsAz, is_identity_rest_read, load_wit, load_wit_error, route_key_boards, route_params
from tests.ado_boards_fixtures import body_file

import copy
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

import ado_discussion_cache as cache
import ado_schema
import ado_sync
import ado_sync_model as model
import ado_transport
import boards_contract as bc
from ado_map import AdoImportError

# B0 (2026-10-14): these scenarios combine the item, history and write fixtures — hand-written for the hand-written
# Agile process, and not captured yet — with a process, so they read that same process even where a capture exists
# (tests/ado_boards_fixtures.py, `BOARDS_PROCESS`). The captured process is exercised in test_boards_captured_process.py.
BOARDS_PROCESS = HAND_WRITTEN_PROCESS

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ado_sync.py"
MINI = Path(__file__).resolve().parent / "fixtures" / "boards_repo"
GOLDEN_PLAN = Path(__file__).resolve().parent / "golden" / "ado_plan_spec_0004.txt"

NOW = datetime(2026, 10, 13, 9, 30, tzinfo=timezone.utc)
STAMP = "2026-10-13T09:30Z"
SPEC4, SPEC5, SPEC7 = "sdlc:spec:0004", "sdlc:spec:0005", "sdlc:spec:0007"
FEATURE3 = "sdlc:feature:03"
RISK_VALUES = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}
PROJECTION_TAGS = {"data-review:n-a", "eng-review:accepted", "risk:HIGH", "sdlc-repo:claims-api", SPEC4,
                   "sdlc:status:ready"}
KIM = "kim.lee" + "@corp.example.com"        # a hostile address, assembled so no address literal is committed (rule 10)
KIM_DOMAIN = "@kim." + "corp.example.com"    # the `@domain` form, which is refused too
AI_NAMES = ["Claude", "claude-opus-4", "shepherd:feature-architect", "data-analyst", "Shepherd:sdlc-orchestrator"]
# What a real az 401/403 prints: a storage-key GUID and a UPN-shaped `<guid>\<address>` (an all-zero GUID: not a real one).
FAKE_GUID = "00000000-0000-0000-0000-0000000000ff"
DENIED_AZ = f"ERROR: TF400813: The user '{FAKE_GUID}\\{KIM}' is not authorized to access this resource."
UNREADABLE_AZ = f"ERROR: the connection closed while {FAKE_GUID}\\{KIM} was waiting for an answer"

# The roster of the test copy: @dev-one signs in to az as the fixtures' person1 (`connection_data`).
ROSTER = """\
version: "1.0"
teams:
  - name: core
    lead: "@dev-one"
people:
  - handle: "@dev-one"
    name: "Person 1"
    email: "person1@example.com"
    team: core
    roles: [owner, developer, checker, lead]
    signs_off: ["1", "2", "build"]
  - handle: "@dev-two"
    name: "Person 2"
    email: "person2@example.com"
    team: core
    roles: [developer]
    signs_off: ["build"]
"""

# `--message=` goldens: what a person might type that a shell, an argparse or a JSON writer could mangle.
GOLDEN_MESSAGES = {
    "double_quote": 'He said "ship it" today',
    "newline": "first line\nsecond line",
    "command_substitution": "cost is $(rm -rf /tmp/x) and `id` and ${HOME}",
    "non_ascii": "Zażółć gęślą jaźń · 日本語 · ✓ · café",
    "leading_dash": "-rf is not a flag, --message is not either",
}


# --- helpers ---------------------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(ado_schema, "now_utc", lambda: NOW)


def _body(args):
    # `--in-file <path>`, or since the B0 write fixes an update's `az rest --body @<path>`
    return json.loads(Path(body_file(args)).read_text(encoding="utf-8"))


def board_row(doc: dict, wid: int = 4521) -> dict:
    return next(r for r in doc["value"] if r and r["id"] == wid)


def synced_batch(rev: int = 8):
    """The batch fixture with item 4521 changed to carry what spec 0004's projection pushes."""
    doc = copy.deepcopy(load_wit("workitems_batch"))
    row = board_row(doc)
    row["rev"] = rev
    row["fields"]["System.State"] = "Ready"
    row["fields"]["System.Tags"] = "; ".join(sorted(PROJECTION_TAGS))
    row["fields"]["Custom.RiskTier"] = "HIGH"
    return doc


def item_row(wid: int, tags: str, rev: int = 3) -> dict:
    row = copy.deepcopy(board_row(load_wit("workitems_batch")))
    row["id"], row["rev"] = wid, rev
    row["fields"]["System.Id"] = wid
    row["fields"]["System.Tags"] = tags
    row.pop("relations", None)
    return row


def put_batch(board, *rows: dict) -> None:
    board.answers["POST wit/workitemsbatch"] = {"count": len(rows), "value": list(rows)}


def tagged_none(args):
    return []


@pytest.fixture
def board(monkeypatch) -> FakeBoardsAz:
    """A fake that answers writes and records `(route key, argv, request body)` of each in `sent`; creates answer ids
    5001, 5002, ...; an update of #4521 answers the tested revision plus one and moves the board to the synced row (so a
    re-plan sees what an apply wrote); a PR link answers an empty list."""
    fake = FakeBoardsAz(writes=True, hand_written=BOARDS_PROCESS == HAND_WRITTEN_PROCESS)
    fake.sent = []
    fake.ids = itertools.count(5001)

    def record(args):
        fake.sent.append((route_key_boards(args), list(args), _body(args) if body_file(args) else None))

    def on_create(args):
        record(args)
        return {"id": next(fake.ids), "rev": 1}

    def on_update(args):
        record(args)
        rev = next(op["value"] for op in fake.sent[-1][2] if op["op"] == "test")
        wid = int(route_params(args)["id"])
        if wid == 4521:
            fake.answers["POST wit/workitemsbatch"] = synced_batch(rev + 1)
        return {"id": wid, "rev": rev + 1}

    def on_comment(args):
        record(args)
        return "comment_add_response"

    def on_link(args):
        fake.sent.append((route_key_boards(args), list(args), None))
        return []

    fake.answers.update({"POST wit/workItems": on_create, "PATCH wit/workItems": on_update,
                         "POST wit/comments": on_comment, "boards query": tagged_none,
                         "repos pr work-item add": on_link})
    monkeypatch.setattr(ado_transport, "run_az", fake)
    return fake


def run3(capsys, *argv):
    code = ado_sync.main([str(a) for a in argv])
    got = capsys.readouterr()
    return code, got.out, got.err


def run(capsys, *argv):
    code, out, _err = run3(capsys, *argv)
    return code, out


def run_json(capsys, *argv):
    code, out = run(capsys, *argv, "--json")
    return code, json.loads(out)


def set_config(root: Path, **changes) -> None:
    path = root / bc.CONFIG_FILE
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key, value in changes.items():
        cfg[key] = value
    path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")


def load_cfg(root: Path) -> dict:
    return yaml.safe_load((root / bc.CONFIG_FILE).read_text(encoding="utf-8"))


@pytest.fixture
def repo(tmp_path, board, capsys) -> Path:
    """A copy of the mini repository with the starter config (posture `assisted`, so apply is offered), the discovered
    schema and a roster that knows the fixtures' people. Setup's own az calls are forgotten."""
    root = tmp_path / "repo"
    shutil.copytree(MINI, root)
    (root / ".sdlc" / "team.yaml").write_text(ROSTER, encoding="utf-8")
    assert ado_sync.main(["config", "init", "--repo", str(root)]) == 0
    assert ado_sync.main(["discover", "--repo", str(root)]) == 0
    set_config(root, posture="assisted", fields={"spec": {"risk": {"field": "Custom.RiskTier", "values": RISK_VALUES}}})
    capsys.readouterr()
    board.calls.clear()
    return root


def ledger_path(root: Path) -> Path:
    return root / bc.LEDGER


def seed(root: Path, *events: dict) -> None:
    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def ledger(root: Path) -> list[dict]:
    path = ledger_path(root)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def events_of(root: Path, name: str) -> list[dict]:
    return [e for e in ledger(root) if e["event"] == name]


def linked(ref: str, wid: int, rev: int = 7, **extra) -> dict:
    return {"ts": "2026-10-12T08:00Z", "event": "linked", "ref": ref, "kind": ref.split(":")[1], "work_item": wid,
            "how": "linked", "rev_after": rev, "type": "User Story", "by": "@dev-one",
            "projection_hash": "0" * 12, **extra}


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def assert_no_identity(text: str) -> None:
    assert not bc.GUID_RE.search(text), "a GUID"
    assert not bc.EMAIL_RE.search(text), "an e-mail address"


def assert_clean_record(root: Path, *extra: str) -> None:
    for text in extra:
        assert_no_identity(text)
    for path in root.rglob("*.jsonl"):
        assert_no_identity(path.read_text(encoding="utf-8"))
    for path in (root / bc.LOCAL_DIR / "plans").glob("*.json") if (root / bc.LOCAL_DIR / "plans").is_dir() else []:
        assert_no_identity(path.read_text(encoding="utf-8"))


def assert_detect_false(board) -> None:
    for call in board.calls:
        if is_identity_rest_read(call):  # B0: the one `az rest` (the identity read) has no --detect flag
            continue
        if call[:3] == ["rest", "--method", "patch"]:   # B0 write fixes: nor has the update, `az rest` of its URL
            assert route_key_boards(call) == "PATCH wit/workItems" and "--detect" not in call, call
            assert call[call.index("--resource") + 1] == bc.ADO_RESOURCE_ID, call
            continue
        assert "--detect" in call and call[call.index("--detect") + 1] == "false", call


REAL_OPEN = open


def refuse_ledger_appends(monkeypatch) -> None:
    def refuse(path, mode="r", *args, **kwargs):
        if str(path).endswith("ado-sync-log.jsonl") and "a" in mode:
            raise OSError("read-only file system")
        return REAL_OPEN(path, mode, *args, **kwargs)
    monkeypatch.setattr("builtins.open", refuse)


def allow_ledger_appends(monkeypatch) -> None:
    """Undo `refuse_ledger_appends` only (`monkeypatch.undo()` would also undo the fake `az` and the clock)."""
    monkeypatch.setattr("builtins.open", REAL_OPEN)


def plan_doc(capsys, root: Path, *extra) -> dict:
    """What `ado_sync.py plan` printed (`--json`), with the plan file it wrote alongside as `file`."""
    code, out = run_json(capsys, "plan", *extra, "--repo", root)
    assert code == 0 and out["ok"], out
    out["file"] = json.loads((root / out["path"]).read_text(encoding="utf-8"))
    return out


def plan_spec4(capsys, root: Path, *extra) -> dict:
    return plan_doc(capsys, root, "--kind", "spec", "--id", "0004", *extra)


def apply_args(plan: str, *extra, by: str = "@dev-one") -> list:
    return ["apply", "--confirm", plan, "--by", by, *extra]


def writes(board, key: str) -> list[tuple]:
    return [s for s in board.sent if s[0] == key]


@pytest.fixture
def planned(repo, board, capsys) -> dict:
    """Spec 0004 is linked to #4521 (rev 7), behind the repository: one update row, planned (az calls forgotten)."""
    seed(repo, linked(SPEC4, 4521))
    out = plan_spec4(capsys, repo)
    assert [r["action"] for r in out["rows"]] == ["update"]
    board.calls.clear()
    return out


def carried_repo(repo, board, capsys) -> dict:
    """Spec 0005 is linked to #4522; the mini repo's sprint log carries it twice, so a plan holds 1 update + 2 comments."""
    seed(repo, linked(SPEC5, 4522, rev=3))
    put_batch(board, item_row(4522, "risk:LOW; sdlc:spec:0005; sdlc:status:draft"))
    out = plan_doc(capsys, repo, "--kind", "spec", "--id", "0005")
    board.calls.clear()
    return out


# --- the verb table, --help, and the guards every write verb shares --------------------------------------------

WRITE_VERBS = {
    "apply": lambda by: ["apply", "--confirm", "a" * 12, "--by", by],
    "link-pr": lambda by: ["link-pr", "--spec", "0004", "--pr", "12", "--by", by],
    "iteration-bind": lambda by: ["iteration", "bind", "S08", "--path", "Claims\\Sprint 7", "--by", by],
    "posture": lambda by: ["posture", "assisted", "--by", by],
    "comment": lambda by: ["comment", SPEC4, "--message=hello", "--by", by],
}


def test_the_write_verbs_are_in_the_parser_and_the_verb_table(repo):
    assert {"apply", "link-pr", "iteration", "posture", "comment"} <= set(ado_sync.VERBS)
    parser = ado_sync.build_parser()
    choices = next(a for a in parser._actions if getattr(a, "choices", None)).choices
    assert set(choices) == set(ado_sync.VERBS)
    assert all(callable(handler) for handler in ado_sync.VERBS.values())


def test_help_on_every_write_verb_touches_nothing(tmp_path, monkeypatch, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    for argv in (["apply", "--help"], ["link-pr", "--help"], ["iteration", "--help"], ["iteration", "bind", "--help"],
                 ["posture", "--help"], ["comment", "--help"], ["plan", "--help"]):
        with pytest.raises(SystemExit) as stop:
            ado_sync.main(argv)
        assert stop.value.code == 0, argv
    capsys.readouterr()
    assert list(empty.iterdir()) == []


def test_the_script_runs_help_for_the_write_verbs_in_an_empty_cwd(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    for argv in (["apply"], ["link-pr"], ["iteration"], ["iteration", "bind"], ["posture"], ["comment"]):
        done = subprocess.run([sys.executable, str(SCRIPT), *argv, "--help"], cwd=empty, capture_output=True,
                              text=True, env=env, timeout=60)
        assert done.returncode == 0, (argv, done.stderr)
        assert "usage:" in done.stdout
    assert list(empty.iterdir()) == []


def test_the_flags_are_the_kit_s_verb_table():
    parser = ado_sync.build_parser()

    def flags(*verb):
        node = parser
        for word in verb:
            node = next(a for a in node._actions if getattr(a, "choices", None)).choices[word]
        return {s for a in node._actions for s in a.option_strings} - {"-h", "--help", "--state", "--repo", "--json"}
    assert flags("apply") == {"--confirm", "--by", "--limit"}
    assert flags("link-pr") == {"--spec", "--pr", "--by"}
    assert flags("iteration", "bind") == {"--path", "--by"}
    assert flags("posture") == {"--by"}
    assert flags("comment") == {"--message", "--by", "--mention", "--event"}
    assert {"--no-comments"} <= flags("plan")


@pytest.mark.parametrize("name", AI_NAMES)
@pytest.mark.parametrize("verb", sorted(WRITE_VERBS))
def test_every_write_verb_refuses_an_ai_or_an_agent_with_zero_spawns_and_writes_nothing(repo, board, capsys, verb, name):
    seed(repo, linked(SPEC4, 4521))
    before = snapshot(repo)
    code, out = run(capsys, *WRITE_VERBS[verb](name), "--repo", repo)
    assert code == 2 and "Refused" in out and "AI" in out, out
    assert board.calls == [] and snapshot(repo) == before
    code, doc = run_json(capsys, *WRITE_VERBS[verb](name), "--repo", repo)
    assert code == 2 and doc["ok"] is False and doc["exit"] == 2
    assert board.calls == [] and snapshot(repo) == before


def test_the_ai_refusal_comes_before_every_other_check_whatever_else_is_wrong_with_the_request(repo, board, capsys):
    """Exit 2 is about who is asking, so a request that is also malformed, missing its plan or off-posture is still 2."""
    set_config(repo, posture="plan-only")
    for argv in (["apply", "--by", "Claude"], ["apply", "--confirm", "nothex", "--by", "Claude"],
                 ["apply", "--confirm", "f" * 12, "--by", "Claude"], ["link-pr", "--spec", "abc", "--pr", "x", "--by", "Claude"],
                 ["link-pr", "--spec", "0004", "--pr", "12", "--by", "Claude"],
                 ["iteration", "bind", "banana", "--path", "", "--by", "Claude"], ["comment", "nonsense", "--by", "Claude"],
                 ["comment", SPEC4, "--message=", "--by", "Claude"]):
        code, out = run(capsys, *argv, "--repo", repo)
        assert code == 2 and "AI" in out, (argv, out)
    assert board.calls == []


@pytest.mark.parametrize("verb", sorted(WRITE_VERBS))
def test_every_write_verb_refuses_an_address_off_the_roster_as_by(repo, board, capsys, verb):
    before = snapshot(repo)
    code, out = run(capsys, *WRITE_VERBS[verb](KIM), "--repo", repo)
    assert code == 2 and "e-mail" in out and board.calls == [] and snapshot(repo) == before


def test_a_blank_or_missing_by_is_a_usage_error_exit_1_with_zero_spawns(repo, board, capsys):
    before = snapshot(repo)
    for argv in (["apply", "--confirm", "a" * 12], ["link-pr", "--spec", "0004", "--pr", "12"],
                 ["iteration", "bind", "S08", "--path", "Claims"], ["posture", "assisted"],
                 ["comment", SPEC4, "--message=hi"], ["posture", "assisted", "--by", "   "]):
        code, out = run(capsys, *argv, "--repo", repo)
        assert code == 1 and "--by" in out, argv
    assert board.calls == [] and snapshot(repo) == before


def test_by_is_ledgered_as_the_roster_handle_the_typed_name_matches(repo, capsys):
    code, _ = run(capsys, "posture", "plan-only", "--by", "Person 1", "--repo", repo)
    assert code == 0
    assert events_of(repo, "posture")[-1]["by"] == "@dev-one"
    code, out = run(capsys, "posture", "assisted", "--by", "Person 2", "--repo", repo)
    assert code == 0 and events_of(repo, "posture")[-1]["by"] == "@dev-two"


# --- posture -----------------------------------------------------------------------------------------------

def test_posture_switches_the_config_keeps_its_comments_and_ledgers_the_change(tmp_path, board, capsys):
    root = tmp_path / "repo"
    shutil.copytree(MINI, root)
    (root / ".sdlc" / "team.yaml").write_text(ROSTER, encoding="utf-8")
    assert ado_sync.main(["config", "init", "--repo", str(root)]) == 0
    capsys.readouterr()
    starter = (root / bc.CONFIG_FILE).read_text(encoding="utf-8")
    assert "posture: plan-only" in starter
    code, out = run(capsys, "posture", "assisted", "--by", "@dev-one", "--repo", root)
    assert code == 0 and "plan-only -> assisted" in out and "@dev-one" in out
    after = (root / bc.CONFIG_FILE).read_text(encoding="utf-8")
    assert yaml.safe_load(after) == {**yaml.safe_load(starter), "posture": "assisted"}
    assert after.count("\n") == starter.count("\n") and "# Azure Boards mirror" in after     # comments survive, one line moved
    assert re.search(r"^posture: assisted\s+# plan-only \| assisted", after, re.M)
    assert [l for l in after.splitlines() if not l.startswith("posture:")] == \
        [l for l in starter.splitlines() if not l.startswith("posture:")]
    assert events_of(root, "posture") == [{"ts": STAMP, "event": "posture", "posture": "assisted",
                                           "previous": "plan-only", "by": "@dev-one"}]
    assert board.calls == []
    code, out = run(capsys, "posture", "plan-only", "--by", "@dev-one", "--repo", root)
    assert code == 0 and yaml.safe_load((root / bc.CONFIG_FILE).read_text(encoding="utf-8"))["posture"] == "plan-only"
    assert [e["posture"] for e in events_of(root, "posture")] == ["assisted", "plan-only"]


def test_posture_to_the_value_it_already_has_changes_nothing_and_ledgers_nothing(repo, capsys):
    before = snapshot(repo)
    code, out = run(capsys, "posture", "assisted", "--by", "@dev-one", "--repo", repo)
    assert code == 0 and "already" in out and snapshot(repo) == before
    code, doc = run_json(capsys, "posture", "assisted", "--by", "@dev-one", "--repo", repo)
    assert code == 0 and doc["ok"] is True and doc["changed"] is False and doc["posture"] == "assisted"


def test_posture_works_from_plan_only_it_is_how_a_clone_switches(repo, board, capsys):
    set_config(repo, posture="plan-only")
    code, doc = run_json(capsys, "posture", "assisted", "--by", "@dev-one", "--repo", repo)
    assert code == 0 and doc["changed"] is True and doc["previous"] == "plan-only" and board.calls == []
    assert load_cfg(repo)["posture"] == "assisted"


def test_posture_adds_the_key_when_the_config_has_none(repo, capsys):
    cfg = load_cfg(repo)
    del cfg["posture"]
    (repo / bc.CONFIG_FILE).write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    code, doc = run_json(capsys, "posture", "assisted", "--by", "@dev-one", "--repo", repo)
    assert code == 0 and doc["previous"] == "plan-only" and load_cfg(repo)["posture"] == "assisted"
    assert {k: v for k, v in load_cfg(repo).items() if k != "posture"} == {k: v for k, v in cfg.items()}


def test_posture_without_a_config_is_exit_1_and_an_unknown_value_is_argparse_s_usage_error(tmp_path, capsys):
    code, out = run(capsys, "posture", "assisted", "--by", "@dev-one", "--repo", tmp_path)
    assert code == 1 and "ado.yaml" in out and not (tmp_path / ".sdlc").exists()
    with pytest.raises(SystemExit) as stop:
        ado_sync.main(["posture", "admin", "--by", "@dev-one", "--repo", str(tmp_path)])
    assert stop.value.code == 2 and "admin" in capsys.readouterr().err


def test_posture_in_workflow_mode_reads_the_config_beside_the_state_file(repo, capsys):
    code, doc = run_json(capsys, "posture", "plan-only", "--by", "@dev-one", "--state", repo / ".sdlc" / "state.yaml")
    assert code == 0 and load_cfg(repo)["posture"] == "plan-only"


def test_posture_a_failed_ledger_append_prints_drift_and_exits_1(repo, capsys, monkeypatch):
    refuse_ledger_appends(monkeypatch)
    code, out = run(capsys, "posture", "plan-only", "--by", "@dev-one", "--repo", repo)
    assert code == 1 and out.startswith("DRIFT:")
    allow_ledger_appends(monkeypatch)
    assert load_cfg(repo)["posture"] == "plan-only"               # the file moved, the record did not: said so
    assert events_of(repo, "posture") == []


# --- iteration bind ----------------------------------------------------------------------------------------

def bind(capsys, repo, snn="S08", path="Claims\\Sprint 7", *extra):
    return run(capsys, "iteration", "bind", snn, "--path", path, "--by", "@dev-one", *extra, "--repo", repo)


def test_iteration_bind_writes_the_binding_keeps_the_rest_of_the_config_and_ledgers_it(repo, board, capsys):
    before = (repo / bc.CONFIG_FILE).read_text(encoding="utf-8")
    code, out = bind(capsys, repo)
    assert code == 0 and "S08" in out and "Claims\\Sprint 7" in out
    cfg = load_cfg(repo)
    assert cfg["iterations"] == {"S07": "Claims\\Sprint 7", "S08": "Claims\\Sprint 7"}
    assert {k: v for k, v in cfg.items() if k != "iterations"} == \
        {k: v for k, v in yaml.safe_load(before).items() if k != "iterations"}
    after = (repo / bc.CONFIG_FILE).read_text(encoding="utf-8")
    assert after.count("\n") == before.count("\n") + 1 and "  S08: 'Claims\\Sprint 7'\n" in after   # one line added
    assert events_of(repo, "iteration_bound") == [{
        "ts": STAMP, "event": "iteration_bound", "ref": "sdlc:sprint:S08", "kind": "sprint", "sprint": "S08",
        "path": "Claims\\Sprint 7", "previous": None, "by": "@dev-one"}]
    assert board.calls == []                                       # a local config edit: the board is never asked
    assert ado_sync.main(["config", "check", "--repo", str(repo)]) != 2


def test_iteration_bind_keeps_the_starter_s_comments_and_works_under_plan_only(tmp_path, board, capsys):
    root = tmp_path / "repo"
    shutil.copytree(MINI, root)
    (root / ".sdlc" / "team.yaml").write_text(ROSTER, encoding="utf-8")
    assert ado_sync.main(["config", "init", "--repo", str(root)]) == 0
    assert ado_sync.main(["discover", "--repo", str(root)]) == 0
    capsys.readouterr()
    board.calls.clear()
    before = (root / bc.CONFIG_FILE).read_text(encoding="utf-8")
    assert load_cfg(root)["posture"] == "plan-only"                 # the starter: a local config edit is not a board write
    code, out = bind(capsys, root, "S08", "Claims\\Sprint 7")
    assert code == 0 and board.calls == []
    after = (root / bc.CONFIG_FILE).read_text(encoding="utf-8")
    assert [l for l in after.splitlines() if l != "  S08: 'Claims\\Sprint 7'"] == before.splitlines()   # one line, nothing else
    assert yaml.safe_load(after)["iterations"] == {"S07": "Claims\\Sprint 7", "S08": "Claims\\Sprint 7"}


def test_iteration_bind_in_a_flow_style_block_rewrites_the_config_and_says_the_comments_went(repo, board, capsys):
    path = repo / bc.CONFIG_FILE
    cfg = load_cfg(repo)
    text = "# a comment that will not survive a rewrite\n" + yaml.safe_dump({**cfg, "iterations": {}}, sort_keys=False)
    text = text.replace("iterations: {}", "iterations: {S07: 'Claims\\Sprint 7'}  # flow style")
    path.write_text(text, encoding="utf-8")
    code, doc = run_json(capsys, "iteration", "bind", "S08", "--path", "Claims\\Sprint 7", "--by", "@dev-one", "--repo", repo)
    assert code == 0 and any("without its comments" in n for n in doc["notes"])
    assert load_cfg(repo)["iterations"] == {"S07": "Claims\\Sprint 7", "S08": "Claims\\Sprint 7"}
    assert {k: v for k, v in load_cfg(repo).items() if k != "iterations"} == {k: v for k, v in cfg.items() if k != "iterations"}


def test_posture_keeps_a_quoted_value_s_comment_and_the_rest_of_the_file(repo, capsys):
    path = repo / bc.CONFIG_FILE
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"^posture: .*$", 'posture: "assisted"   # set by hand', text, flags=re.M)
    path.write_text(text, encoding="utf-8")
    code, out = run(capsys, "posture", "plan-only", "--by", "@dev-one", "--repo", repo)
    assert code == 0
    after = path.read_text(encoding="utf-8")
    assert "posture: plan-only" in after and "# set by hand" in after
    assert [l for l in after.splitlines() if not l.startswith("posture:")] == \
        [l for l in text.splitlines() if not l.startswith("posture:")]


def test_iteration_bind_to_a_path_not_in_the_schema_is_exit_1_and_changes_nothing(repo, board, capsys):
    before = snapshot(repo)
    code, out = bind(capsys, repo, "S08", "Claims\\Sprint 99")
    assert code == 1 and "Sprint 99" in out and "discovered" in out
    code, doc = run_json(capsys, "iteration", "bind", "S08", "--path", "Nowhere", "--by", "@dev-one", "--repo", repo)
    assert code == 1 and doc["ok"] is False
    assert snapshot(repo) == before and board.calls == []


def test_iteration_bind_takes_the_schema_s_spelling_of_a_path_that_differs_only_in_case(repo, capsys):
    code, out = bind(capsys, repo, "S08", "claims\\sprint 7")
    assert code == 0 and load_cfg(repo)["iterations"]["S08"] == "Claims\\Sprint 7"


def test_iteration_bind_rebinding_records_the_previous_path_and_the_same_path_is_a_no_op(repo, capsys):
    code, out = bind(capsys, repo, "S07", "Claims\\Sprint 7")
    assert code == 0 and "already" in out and events_of(repo, "iteration_bound") == []
    code, out = bind(capsys, repo, "S07", "Claims")
    assert code == 0 and load_cfg(repo)["iterations"]["S07"] == "Claims"
    assert events_of(repo, "iteration_bound")[-1]["previous"] == "Claims\\Sprint 7"


def test_iteration_bind_adds_the_block_when_the_config_has_none_and_notes_what_it_noticed(repo, capsys):
    cfg = load_cfg(repo)
    del cfg["iterations"]
    (repo / bc.CONFIG_FILE).write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    code, doc = run_json(capsys, "iteration", "bind", "S09", "--path", "Claims\\Sprint 7", "--by", "@dev-one",
                         "--repo", repo)
    assert code == 0 and load_cfg(repo)["iterations"] == {"S09": "Claims\\Sprint 7"}
    assert any("S09.md" in n for n in doc["notes"])                # no such sprint file in this clone: bound anyway, said so
    code, doc = run_json(capsys, "iteration", "bind", "S07", "--path", "Claims\\Sprint 7", "--by", "@dev-one",
                         "--repo", repo)
    assert any("S09" in n and "also bound" in n for n in doc["notes"])    # two sprints on one path is noted, not refused


def test_iteration_bind_a_sprint_id_that_is_not_one_and_a_missing_path_are_exit_1(repo, board, capsys):
    before = snapshot(repo)
    for argv in (["iteration", "bind", "banana", "--path", "Claims"], ["iteration", "bind", "S7", "--path", "Claims"],
                 ["iteration", "bind", "S08", "--path", "  "], ["iteration", "bind", "S08"]):
        code, out = run(capsys, *argv, "--by", "@dev-one", "--repo", repo)
        assert code == 1, argv
    assert snapshot(repo) == before and board.calls == []


def test_iteration_bind_without_a_discovered_schema_is_exit_1(repo, capsys):
    (repo / bc.SCHEMA_FILE).unlink()
    code, out = bind(capsys, repo)
    assert code == 1 and "discover" in out


def test_iteration_bind_a_failed_ledger_append_prints_drift_and_exits_1(repo, capsys, monkeypatch):
    refuse_ledger_appends(monkeypatch)
    code, out = bind(capsys, repo)
    assert code == 1 and out.startswith("DRIFT:")


def test_iteration_bind_notes_a_path_the_team_does_not_have(repo, capsys):
    code, doc = run_json(capsys, "iteration", "bind", "S08", "--path", "Claims", "--by", "@dev-one", "--repo", repo)
    assert code == 0 and any("team" in n for n in doc["notes"])    # in the iteration tree, not on the team's sprint board


# --- link-pr -----------------------------------------------------------------------------------------------

def link_pr(capsys, repo, *extra, by="@dev-one"):
    return run(capsys, "link-pr", "--spec", "0004", "--pr", "12", "--by", by, *extra, "--repo", repo)


def test_link_pr_is_one_native_az_write_and_a_ledger_line(repo, board, capsys):
    seed(repo, linked(SPEC4, 4521, rev=7, projection_hash="abc123abc123"))
    code, out = link_pr(capsys, repo)
    assert code == 0 and "PR 12" in out and "#4521" in out
    assert len(board.calls) == 1 and board.written() == board.calls
    (call,) = board.calls
    assert call[:4] == ["repos", "pr", "work-item", "add"]
    assert call[call.index("--id") + 1] == "12" and call[call.index("--work-items") + 1] == "4521"
    assert call[-2:] == ["-o", "json"] and "--org" in call     # `run_az` adds `--only-show-errors`; the fake never sees it
    assert_detect_false(board)
    assert "--project" not in call and "--repository" not in call
    (line,) = events_of(repo, "applied")
    assert (line["ref"], line["work_item"], line["action"], line["pr"], line["by"], line["executed_as"]) == \
        (SPEC4, 4521, "link_pr", 12, "@dev-one", "unknown")             # az's identity is not read for a PR link (D22)
    assert line["fields"] == ["relations:ArtifactLink"]
    # the item's baseline is carried, so a later pull still reads its revisions from rev 7 and compares what was pushed
    assert (line["rev_after"], line["projection_hash"], line["type"], line["kind"]) == (7, "abc123abc123", "User Story",
                                                                                      "spec")
    assert ado_sync.linked_items(ledger(repo))[SPEC4]["rev_after"] == 7
    assert_clean_record(repo, out)


def test_link_pr_under_plan_only_is_refused_with_zero_spawns(repo, board, capsys):
    seed(repo, linked(SPEC4, 4521))
    set_config(repo, posture="plan-only")
    before = snapshot(repo)
    code, out = link_pr(capsys, repo)
    assert code == 2 and "plan-only" in out and board.calls == [] and snapshot(repo) == before
    code, doc = run_json(capsys, "link-pr", "--spec", "4", "--pr", "12", "--by", "@dev-one", "--repo", repo)
    assert code == 2 and doc["ok"] is False and board.calls == []


def test_link_pr_for_a_spec_this_clone_never_ledgered_is_exit_1_with_zero_spawns(repo, board, capsys):
    code, out = link_pr(capsys, repo)
    assert code == 1 and SPEC4 in out and "link" in out and board.calls == []
    assert events_of(repo, "applied") == []


def test_link_pr_takes_the_spec_id_unpadded_and_refuses_what_is_not_an_id(repo, board, capsys):
    seed(repo, linked(SPEC4, 4521))
    code, doc = run_json(capsys, "link-pr", "--spec", "4", "--pr", "12", "--by", "@dev-one", "--repo", repo)
    assert code == 0 and doc["ref"] == SPEC4
    for spec, pr in (("abc", "12"), ("0004", "x"), ("0004", "0"), ("0004", "-3"), ("0004", "12; rm"), ("", "12"),
                     ("0004", "")):
        board.calls.clear()
        code, out = run(capsys, "link-pr", "--spec", spec, "--pr", pr, "--by", "@dev-one", "--repo", repo)
        assert code == 1 and board.calls == [], (spec, pr)


def test_link_pr_an_az_error_is_exit_1_with_nothing_ledgered_and_the_outcome_said(repo, board, capsys):
    seed(repo, linked(SPEC4, 4521))
    board.fail["work-item add"] = load_wit_error("permission")
    code, out = link_pr(capsys, repo)
    assert code == 1 and "was not linked" in out and "permission" in out and events_of(repo, "applied") == []
    assert load_wit_error("permission") not in out
    board.fail["work-item add"] = "operation timed out"
    code, out = link_pr(capsys, repo)
    assert code == 1 and "may or may not be linked" in out and events_of(repo, "applied") == []   # unknown: it may have landed


def test_link_pr_never_repeats_the_boards_words_so_it_names_no_one(repo, board, capsys):
    seed(repo, linked(SPEC4, 4521))
    for stderr, said in ((DENIED_AZ, "(permission)"), (UNREADABLE_AZ, "may or may not be linked")):
        board.fail["work-item add"] = stderr
        code, out = link_pr(capsys, repo)
        assert code == 1 and said in out and stderr not in out and "TF400813" not in out, stderr
        code, doc = run_json(capsys, "link-pr", "--spec", "0004", "--pr", "12", "--by", "@dev-one", "--repo", repo)
        assert code == 1 and doc["ok"] is False and said in doc["error"] and stderr not in json.dumps(doc), stderr
        assert_clean_record(repo, out, json.dumps(doc))
    assert events_of(repo, "applied") == []


def test_link_pr_a_remote_that_cannot_be_read_asks_no_az_and_does_not_echo_the_remote(repo, board, capsys, monkeypatch):
    seed(repo, linked(SPEC4, 4521))

    def not_azure(root):
        raise AdoImportError(f"origin is not an Azure DevOps remote (from origin https://{KIM}/{FAKE_GUID}.git)")
    monkeypatch.setattr(ado_transport, "remote", not_azure)
    code, out = link_pr(capsys, repo)
    assert code == 1 and "was not linked" in out and "az was not asked" in out and board.calls == []
    assert "origin is not" not in out and events_of(repo, "applied") == []
    assert_clean_record(repo, out)


def test_link_pr_twice_is_a_no_op_the_second_time(repo, board, capsys):
    seed(repo, linked(SPEC4, 4521))
    assert link_pr(capsys, repo)[0] == 0
    board.calls.clear()
    code, out = link_pr(capsys, repo)
    assert code == 0 and "already" in out and board.calls == [] and len(events_of(repo, "applied")) == 1


def test_link_pr_a_failed_ledger_append_prints_drift_and_exits_1_after_the_write_landed(repo, board, capsys, monkeypatch):
    seed(repo, linked(SPEC4, 4521))
    refuse_ledger_appends(monkeypatch)
    code, out = link_pr(capsys, repo)
    assert code == 1 and "DRIFT:" in out and len(board.written()) == 1


def test_link_pr_drafts_the_pr_linked_comment_only_when_that_event_is_on(repo, board, capsys):
    seed(repo, linked(SPEC4, 4521))
    code, doc = run_json(capsys, "link-pr", "--spec", "0004", "--pr", "12", "--by", "@dev-one", "--repo", repo)
    assert code == 0 and doc["comment_plan"] is None
    assert not (repo / bc.LOCAL_DIR / "plans").exists() or not list((repo / bc.LOCAL_DIR / "plans").glob("*.json"))
    set_config(repo, comments={**load_cfg(repo)["comments"], "events": {**load_cfg(repo)["comments"]["events"],
                                                                         "pr_linked": "on"}})
    code, doc = run_json(capsys, "link-pr", "--spec", "0004", "--pr", "13", "--by", "@dev-one", "--repo", repo)
    assert code == 0 and re.fullmatch(r"[0-9a-f]{12}", doc["comment_plan"]["plan"])
    plan = json.loads((repo / doc["comment_plan"]["path"]).read_text(encoding="utf-8"))
    (row,) = plan["rows"]
    assert row["event"] == "pr_linked" and row["status"] == "draft" and row["text"] == "PR !13 linked."
    assert row["idem_key"] == "pr:sdlc:spec:0004:13" and len(board.written()) == 2     # drafting sent nothing


# --- apply -------------------------------------------------------------------------------------------------

def test_apply_by_an_ai_is_refused_with_zero_spawns_even_with_a_real_plan(repo, board, planned, capsys):
    before = snapshot(repo)
    code, out = run(capsys, *apply_args(planned["plan"], by="Claude"), "--repo", repo)
    assert code == 2 and "Refused" in out and board.calls == [] and snapshot(repo) == before
    code, doc = run_json(capsys, *apply_args(planned["plan"], by="shepherd:sdlc-orchestrator"), "--repo", repo)
    assert code == 2 and doc["ok"] is False and doc["exit"] == 2 and board.calls == []


def test_apply_under_plan_only_is_refused_with_zero_spawns_and_names_the_way_out(repo, board, planned, capsys):
    set_config(repo, posture="plan-only")
    before = snapshot(repo)
    code, out = run(capsys, *apply_args(planned["plan"]), "--repo", repo)
    assert code == 2 and "plan-only" in out and "posture assisted" in out
    assert board.calls == [] and snapshot(repo) == before
    code, doc = run_json(capsys, *apply_args(planned["plan"]), "--repo", repo)
    assert code == 2 and doc["ok"] is False and board.calls == []
    code, out = run(capsys, *apply_args("f" * 12), "--repo", repo)      # the refusal does not depend on a plan being there
    assert code == 2 and board.calls == []


def test_apply_with_no_posture_in_the_config_is_plan_only(repo, board, planned, capsys):
    cfg = load_cfg(repo)
    del cfg["posture"]
    (repo / bc.CONFIG_FILE).write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    code, out = run(capsys, *apply_args(planned["plan"]), "--repo", repo)
    assert code == 2 and board.calls == []


def test_apply_a_missing_plan_a_bad_hash_and_no_confirm_are_exit_1_with_zero_spawns(repo, board, planned, capsys):
    for argv in (apply_args("f" * 12), apply_args("nothex000000"), apply_args("ABCDEF012345"),
                 apply_args(planned["plan"][:8]), ["apply", "--by", "@dev-one"]):
        code, out = run(capsys, *argv, "--repo", repo)
        assert code == 1, argv
        assert board.calls == [], argv
    code, out = run(capsys, *apply_args("f" * 12), "--repo", repo)
    assert "plan missing" in out and "plan" in out


def test_apply_a_plan_edited_after_it_was_made_is_a_stale_hash_exit_1_with_zero_spawns(repo, board, planned, capsys):
    path = repo / planned["path"]
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["rows"][0]["ops"][0]["new"] = "Closed"
    path.write_text(json.dumps(doc), encoding="utf-8")
    code, out = run(capsys, *apply_args(planned["plan"]), "--repo", repo)
    assert code == 1 and "stale hash" in out and board.calls == []
    path.write_text("{ not json", encoding="utf-8")
    code, out = run(capsys, *apply_args(planned["plan"]), "--repo", repo)
    assert code == 1 and board.calls == []
    doc["plan"] = "0" * 12                                           # a file that says it is another plan
    path.write_text(json.dumps(doc), encoding="utf-8")
    code, out = run(capsys, *apply_args(planned["plan"]), "--repo", repo)
    assert code == 1 and "stale hash" in out and board.calls == []


def test_apply_sends_the_plan_ledgers_it_and_a_re_plan_has_no_ops(repo, board, planned, capsys):
    code, out = run(capsys, *apply_args(planned["plan"]), "--repo", repo)
    assert code == 0, out
    assert "applied 1" in out and "update sdlc:spec:0004" in out and "#4521" in out and "rev 8" in out
    ((key, argv, body),) = board.sent
    assert key == "PATCH wit/workItems" and route_params(argv)["id"] == "4521"
    assert body[0] == {"op": "test", "path": "/rev", "value": 7}      # guarded by the revision the plan showed
    assert_detect_false(board)
    (line,) = events_of(repo, "applied")
    assert (line["ref"], line["action"], line["work_item"], line["rev_before"], line["rev_after"], line["plan"],
            line["by"]) == (SPEC4, "update", 4521, 7, 8, planned["plan"], "@dev-one")
    assert not events_of(repo, "refused") and not events_of(repo, "conflict")
    board.calls.clear()
    again = plan_spec4(capsys, repo)                                  # the board now carries what was written
    assert again["rows"] == [] and again["counts"]["update"] == 0 and again["counts"]["in_sync"] == 1
    assert again["cost"] == {"writes": 0, "creates": 0, "links": 0, "az_spawns": 0}
    assert board.written() == [] and len(board.sent) == 1             # the re-plan sent nothing and found nothing to send
    assert_clean_record(repo, out)


def test_apply_json_is_one_document_with_the_result_and_no_identity(repo, board, planned, capsys):
    code, out, err = run3(capsys, *apply_args(planned["plan"]), "--repo", repo, "--json")
    doc = json.loads(out)                                             # exactly one JSON document on stdout
    assert code == 0 and doc["ok"] is True and doc["exit"] == 0 and doc["plan"] == planned["plan"]
    assert doc["by"] == "@dev-one" and doc["refused_reason"] is None and doc["failed"] == [] and doc["deferred"] == []
    assert doc["applied"] == [{"ref": SPEC4, "action": "update", "work_item": 4521, "rev_after": 8}]
    assert doc["counts"] == {"applied": 1, "failed": 0, "deferred": 0}
    assert err == ""                                                   # nothing on stderr when nothing drifted
    assert_clean_record(repo, out)


def test_apply_a_board_that_moved_is_a_conflict_row_exit_1_and_nothing_is_written(repo, board, planned, capsys):
    put_batch(board, board_row(load_wit("workitems_batch")) | {"rev": 9})
    code, out = run(capsys, *apply_args(planned["plan"]), "--repo", repo)
    assert code == 1 and "failed 1" in out and "conflict" in out and "rev_moved" in out
    assert board.written() == [] and events_of(repo, "applied") == []
    (line,) = events_of(repo, "conflict")
    assert (line["ref"], line["work_item"], line["why"], line["rev_before"]) == (SPEC4, 4521, "rev_moved", 7)
    code, doc = run_json(capsys, *apply_args(planned["plan"]), "--repo", repo)
    assert code == 1 and doc["ok"] is False and doc["failed"][0]["class"] == "conflict"
    assert doc["failed"][0]["reason"] == "rev_moved"


def test_apply_a_permission_failure_stops_the_run_and_exits_1_without_the_boards_words(repo, board, planned, capsys):
    board.fail["rest --method patch"] = load_wit_error("permission")   # an update is `az rest` (B0 write fixes)
    code, out = run(capsys, *apply_args(planned["plan"]), "--repo", repo)
    assert code == 1 and "permission" in out and events_of(repo, "applied") == []
    assert load_wit_error("permission") not in out                    # a fixed sentence, never the board's own words
    code, doc = run_json(capsys, *apply_args(planned["plan"]), "--repo", repo)
    assert doc["failed"][0]["class"] == "permission" and "detail" in doc["failed"][0]
    assert load_wit_error("permission") not in json.dumps(doc)
    assert_no_identity(out)


def test_apply_limit_counts_every_write_and_defers_the_rest_without_failing(repo, board, capsys):
    az_calls = board.calls
    code, out = run_json(capsys, "plan", "--all", "--kind", "spec", "--repo", repo)
    assert code == 0 and out["counts"]["create"] == 3
    set_config(repo, limits={"writes_per_run": 50, "first_seed": 50})
    plan = plan_doc(capsys, repo, "--all", "--kind", "spec")
    az_calls.clear()
    code, doc = run_json(capsys, *apply_args(plan["plan"], "--limit", "1"), "--repo", repo)
    assert code == 0 and doc["counts"] == {"applied": 1, "failed": 0, "deferred": 2}
    assert {d["why"] for d in doc["deferred"]} == {"limit"} and len(writes(board, "POST wit/workItems")) == 1
    code, doc = run_json(capsys, *apply_args(plan["plan"], "--limit", "0"), "--repo", repo)
    assert code == 1 and doc["ok"] is False                           # a limit that is not a positive integer
    code, doc = run_json(capsys, *apply_args(plan["plan"]), "--repo", repo)      # the second chunk: the rest, never twice
    assert code == 0 and doc["counts"]["applied"] == 2 and len(writes(board, "POST wit/workItems")) == 3


def test_apply_the_first_seed_over_the_cap_is_refused_whole_until_a_limit_names_a_chunk(repo, board, capsys):
    set_config(repo, limits={"writes_per_run": 50, "first_seed": 1})
    plan = plan_doc(capsys, repo, "--all", "--kind", "spec")
    board.calls.clear()
    code, out = run(capsys, *apply_args(plan["plan"]), "--repo", repo)
    assert code == 2 and "first_seed" in out and "--limit" in out
    assert board.calls == [] and board.sent == []
    assert events_of(repo, "refused")[-1]["reason"] == "first_seed"
    code, doc = run_json(capsys, *apply_args(plan["plan"]), "--repo", repo)
    assert code == 2 and doc["refused_reason"] == "first_seed" and doc["applied"] == [] and doc["failed"] == []
    code, doc = run_json(capsys, *apply_args(plan["plan"], "--limit", "1"), "--repo", repo)
    assert code == 0 and doc["counts"]["applied"] == 1


def test_apply_a_forbidden_effort_field_in_the_plan_is_refused_whole(repo, board, capsys):
    set_config(repo, fields={"spec": {"effort": "Microsoft.VSTS.Scheduling.StoryPoints"}})
    plan = plan_spec4(capsys, repo)
    assert plan["rows"][0]["action"] == "refused"
    board.calls.clear()
    code, out = run(capsys, *apply_args(plan["plan"]), "--repo", repo)
    assert code == 2 and "effort" in out and board.calls == []


def test_apply_a_failed_ledger_append_prints_drift_and_exits_1_after_the_write_landed(repo, board, planned, capsys,
                                                                                    monkeypatch):
    refuse_ledger_appends(monkeypatch)
    code, out, err = run3(capsys, *apply_args(planned["plan"]), "--repo", repo)
    assert code == 1 and "DRIFT:" in out and len(board.written()) == 1
    allow_ledger_appends(monkeypatch)
    assert events_of(repo, "applied") == []                           # the write landed, the record did not
    code, doc = run_json(capsys, *apply_args(planned["plan"]), "--repo", repo)
    assert code == 1 and doc["failed"][0]["reason"] == "rev_moved"    # a second apply is stopped by the revision, not doubled
    assert len(board.written()) == 1


def test_apply_an_unreadable_ledger_stops_before_anything_is_sent_exit_1(repo, board, planned, capsys):
    with open(ledger_path(repo), "a", encoding="utf-8") as f:
        f.write("not json at all\n")
    code, out = run(capsys, *apply_args(planned["plan"]), "--repo", repo)
    assert code == 1 and "ledger" in out and board.calls == [] and board.sent == []


def test_apply_a_board_that_cannot_be_read_is_exit_1_with_nothing_written(repo, board, planned, capsys):
    board.fail["workitemsbatch"] = "ERROR: Could not resolve host dev.azure.com"
    code, out = run(capsys, *apply_args(planned["plan"]), "--repo", repo)
    assert code == 1 and board.written() == [] and events_of(repo, "applied") == []


@pytest.mark.parametrize("stderr, word", [
    (DENIED_AZ, "permission"),
    (f"ERROR: Please run 'az login' to setup account ({KIM}).", "signed_out"),
    ("The Azure CLI (`az`) is not installed or not on PATH.", "not_installed"),
    (UNREADABLE_AZ, "unknown"),
], ids=["denied", "signed_out", "not_installed", "unreadable"])
def test_apply_a_board_read_failing_before_the_first_write_says_why_in_fixed_words_never_az_s(repo, board, planned,
                                                                                            capsys, stderr, word):
    board.fail["workitemsbatch"] = stderr                            # the batch read in front of the first write
    code, out = run(capsys, *apply_args(planned["plan"]), "--repo", repo)
    assert code == 1 and "before the first write, so nothing was sent" in out and f"({word})" in out
    assert stderr not in out and "TF400813" not in out and "connection closed" not in out
    assert board.written() == [] and events_of(repo, "applied") == []
    code, doc = run_json(capsys, *apply_args(planned["plan"]), "--repo", repo)
    assert code == 1 and doc["ok"] is False and doc["exit"] == 1 and f"({word})" in doc["error"]
    assert stderr not in json.dumps(doc) and "TF400813" not in json.dumps(doc)
    assert_clean_record(repo, out, json.dumps(doc))                   # no address, no GUID: not in the result, not ledgered


def test_apply_in_workflow_mode_uses_the_state_file(repo, board, planned, capsys):
    code, doc = run_json(capsys, *apply_args(planned["plan"]), "--state", repo / ".sdlc" / "state.yaml")
    assert code == 0 and doc["counts"]["applied"] == 1
    code, out = run(capsys, *apply_args(planned["plan"]), "--state", repo / "nowhere" / ".sdlc" / "state.yaml")
    assert code == 1 and "state file not found" in out


def test_apply_without_a_discovered_schema_is_exit_1(repo, board, planned, capsys):
    (repo / bc.SCHEMA_FILE).unlink()
    code, out = run(capsys, *apply_args(planned["plan"]), "--repo", repo)
    assert code == 1 and "discover" in out and board.calls == []


def test_apply_changes_no_file_under_specs_and_nothing_outside_the_sdlc_folder(repo, board, planned, capsys):
    before = {k: v for k, v in snapshot(repo).items() if not k.startswith(".sdlc/")}
    assert run(capsys, *apply_args(planned["plan"]), "--repo", repo)[0] == 0
    assert {k: v for k, v in snapshot(repo).items() if not k.startswith(".sdlc/")} == before


# --- plan: the comment rows, and --no-comments ----------------------------------------------------------------

def test_plan_drafts_the_event_comments_of_the_ledgers_the_repository_keeps(repo, board, capsys):
    out = carried_repo(repo, board, capsys)
    actions = [(r["ref"], r["action"], r.get("status")) for r in out["rows"]]
    assert actions[0][1] == "update" and [a[1:] for a in actions[1:]] == [("comment", "draft"), ("comment", "draft")]
    keys = [r["idem_key"] for r in out["rows"] if r["action"] == "comment"]
    assert keys == ["carried:sdlc:spec:0005:S06:S07", "carried:sdlc:spec:0005:S05:S06"]
    assert out["file"]["rows"] == out["rows"] and model.plan_hash(out["rows"]) == out["plan"]
    assert out["counts"] == {"create": 0, "update": 1, "link": 0, "refused": 0, "unmapped": 0, "ambiguous": 0,
                             "held": 0, "in_sync": 0}                # the field-op counts keep their B2 shape
    assert out["comments"] == {"planned": True, "draft": 2, "skipped": 0, "refused": 0, "unavailable": None}
    assert out["cost"] == {"writes": 1, "creates": 0, "links": 0, "az_spawns": 4}    # connectionData 1, PATCH 1, POST 2
    assert out["posture"] == "assisted"
    assert [e["ref"] for e in events_of(repo, "planned")] == [SPEC5]  # only the field row is `pending`; a comment is not
    code, status = run_json(capsys, "status", "--repo", repo)
    assert status["counts"]["pending"] == 1


def test_plan_text_quotes_a_comment_and_prices_it(repo, board, capsys):
    carried_repo(repo, board, capsys)
    code, text = run(capsys, "plan", "--kind", "spec", "--id", "0005", "--repo", repo)
    assert code == 0
    assert "spec 0005  comment  #4522  event sprint_carried  (key carried:sdlc:spec:0005:S06:S07)" in text
    assert re.search(r"^  \| Carried from S06 to S07 by @dev-one · reason in \.sdlc/sprints/S07\.md · sprd [0-9a-f]{12}$",
                     text, re.M)
    assert "format markdown" in text and "trailer hash" in text
    assert re.search(r"cost: 1 write, 0 creates, 0 links, 2 comments  \(az spawns on apply: 4\)", text)
    assert "comments: 2 to send, 0 skipped, 0 refused" in text


def test_plan_no_comments_drops_them_and_changes_the_plan_hash(repo, board, capsys):
    with_comments = carried_repo(repo, board, capsys)
    without = plan_doc(capsys, repo, "--kind", "spec", "--id", "0005", "--no-comments")
    assert [r["action"] for r in without["rows"]] == ["update"]
    assert without["plan"] != with_comments["plan"]
    assert without["comments"] == {"planned": False, "draft": None, "skipped": None, "refused": None,
                                   "unavailable": None}
    assert without["cost"]["az_spawns"] == 1
    code, text = run(capsys, "plan", "--kind", "spec", "--id", "0005", "--no-comments", "--repo", repo)
    assert "comment" not in text.replace("--no-comments", "")


def test_plan_counts_a_skipped_comment_without_planning_it(repo, board, capsys):
    """An event on an item this clone never linked is a `skipped` row: counted for the person, absent from the plan
    (so it neither moves the hash nor blocks an apply)."""
    out = plan_doc(capsys, repo, "--kind", "spec", "--id", "0005")
    assert [r["action"] for r in out["rows"]] == ["create"]
    assert out["comments"] == {"planned": True, "draft": 0, "skipped": 2, "refused": 0, "unavailable": None}
    assert {s["reason"] for s in out["comments_skipped"]} == {"not_on_board"} and len(out["comments_skipped"]) == 2
    assert out["file"]["rows"] == out["rows"]
    code, text = run(capsys, "plan", "--kind", "spec", "--id", "0005", "--repo", repo)
    assert "comments: 0 to send, 2 skipped (not_on_board 2), 0 refused" in text
    assert "cost: 0 writes, 1 create, 0 links  (az spawns on apply: 1)" in text


def test_a_plan_with_no_comment_row_reads_as_it_did_before_comments_were_planned(repo, board, capsys):
    """The B2 golden (`ado_plan_spec_0004.txt`) stays byte-equal in its own test; here the same plan under
    `assisted` differs from it only in the hash, the posture word and — since Fold B6 (spec 0040, acceptance
    check 6) — the one `Next:` footer an offered apply adds as the last line: under `assisted` with a pending
    row the text ends with `ado_sync_model.apply_next_line(<hash>)`. Pin extended 2026-10-15 (the test postdates
    325ac2b); the plan-only golden itself gains no footer."""
    import ado_sync_model as model
    seed(repo, linked(SPEC4, 4521))
    code, text = run(capsys, "plan", "--kind", "spec", "--id", "0004", "--repo", repo)
    golden = GOLDEN_PLAN.read_text(encoding="utf-8")
    plan = re.match(r"plan ([0-9a-f]{12})", text).group(1)
    expected = golden.replace("plan 1d0617c03373", f"plan {plan}") \
        .replace("posture plan-only", "posture assisted").replace("1d0617c03373.json", f"{plan}.json")
    assert code == 0 and text == expected + model.apply_next_line(plan) + "\n"


def test_plan_a_comment_already_posted_is_never_drafted_again(repo, board, capsys):
    carried_repo(repo, board, capsys)
    seed(repo, {"ts": STAMP, "event": "commented", "ref": SPEC5, "work_item": 4522, "comment_id": 7, "version": 1,
                "idem_key": "carried:sdlc:spec:0005:S06:S07", "text_sha": "a" * 12, "plan": "b" * 12})
    out = plan_doc(capsys, repo, "--kind", "spec", "--id", "0005")
    assert [r["idem_key"] for r in out["rows"] if r["action"] == "comment"] == ["carried:sdlc:spec:0005:S05:S06"]


def test_plan_a_comment_over_the_budget_is_a_refused_row_and_apply_refuses_the_whole_plan(repo, board, capsys):
    set_config(repo, comments={**load_cfg(repo)["comments"], "per_item_budget": 1})
    seed(repo, {"ts": STAMP, "event": "commented", "ref": SPEC5, "work_item": 4522, "idem_key": "x:1",
                "comment_id": 1, "version": 1, "text_sha": "a" * 12, "plan": "b" * 12})
    out = carried_repo(repo, board, capsys)
    refused = [r for r in out["rows"] if r["action"] == "comment"]
    assert refused and {r["status"] for r in refused} == {"refused"} and {r["reason"] for r in refused} == {"budget"}
    assert out["comments"]["refused"] == 2 and out["comments"]["draft"] == 0
    code, text = run(capsys, *apply_args(out["plan"]), "--repo", repo)
    assert code == 2 and "budget" in text and board.calls == [] and "--no-comments" in text
    narrowed = plan_doc(capsys, repo, "--kind", "spec", "--id", "0005", "--no-comments")
    board.calls.clear()
    code, doc = run_json(capsys, *apply_args(narrowed["plan"]), "--repo", repo)
    assert code == 0 and doc["counts"]["applied"] == 1               # the field ops go once the comments are split off


def test_apply_a_plan_with_comments_reads_the_identity_first_and_posts_field_ops_before_comments(repo, board, capsys):
    out = carried_repo(repo, board, capsys)
    code, doc = run_json(capsys, *apply_args(out["plan"]), "--repo", repo)
    assert code == 0, doc
    assert route_key_boards(board.calls[0]) == "GET core/connectionData"          # az call 0
    assert [route_key_boards(c) for c in board.written()] == ["PATCH wit/workItems", "POST wit/comments",
                                                              "POST wit/comments"]
    assert [a["action"] for a in doc["applied"]] == ["update", "comment", "comment"]
    commented = events_of(repo, "commented")
    assert [e["idem_key"] for e in commented] == ["carried:sdlc:spec:0005:S06:S07", "carried:sdlc:spec:0005:S05:S06"]
    assert all(e["by"] == "@dev-one" and e["executed_as"] == "@dev-one" and e["plan"] == out["plan"]
               for e in commented)
    assert_detect_false(board)
    assert_clean_record(repo, json.dumps(doc))
    board.calls.clear()
    again = plan_doc(capsys, repo, "--kind", "spec", "--id", "0005")
    assert [r for r in again["rows"] if r["action"] == "comment"] == []           # keyed: never drafted again


def test_apply_a_comment_plan_by_someone_az_is_not_signed_in_as_is_refused_whole_after_one_call(repo, board, capsys):
    out = carried_repo(repo, board, capsys)
    code, text = run(capsys, *apply_args(out["plan"], by="@dev-two"), "--repo", repo)
    assert code == 2 and "identity_mismatch" in text and "--no-comments" in text
    assert len(board.calls) == 1 and route_key_boards(board.calls[0]) == "GET core/connectionData"
    assert board.sent == []                                          # not even the field op went
    board.calls.clear()
    board.answers["GET core/connectionData"] = "connection_data_sp"
    code, doc = run_json(capsys, *apply_args(out["plan"]), "--repo", repo)
    assert code == 2 and doc["refused_reason"] == "identity_unknown" and len(board.calls) == 1 and board.sent == []


def test_apply_under_a_pat_only_sign_in_is_identity_unknown_exit_2_and_never_a_crash(repo, board, capsys):
    """B0: the identity read is `az rest`, which a personal access token alone cannot answer (az's words below are
    hand-written; the capture signed in with Entra). The plan is refused whole after that one call, the reason is
    `identity_unknown` — not a crash, not "signed out", not a guessed person — and nothing is cached as `me`."""
    out = carried_repo(repo, board, capsys)
    board.calls.clear()
    board.fail["_apis/connectionData"] = "ERROR: Please run 'az login' to setup account."
    code, doc = run_json(capsys, *apply_args(out["plan"]), "--repo", repo)
    assert code == 2 and doc["refused_reason"] == "identity_unknown" and doc["applied"] == [] and board.sent == []
    assert len(board.calls) == 1 and is_identity_rest_read(board.calls[0])
    assert not (repo / bc.ME_FILE).exists()                       # nobody was remembered as `me`
    code, text = run(capsys, *apply_args(out["plan"]), "--repo", repo)
    assert code == 2 and "identity_unknown" in text and "az login" not in text and "Traceback" not in text


# --- comment -----------------------------------------------------------------------------------------------

def comment(capsys, repo, message="Ship it on Friday", target=SPEC4, *extra, by="@dev-one"):
    return run(capsys, "comment", target, f"--message={message}", "--by", by, *extra, "--repo", repo)


def plan_files(repo) -> list[Path]:
    folder = repo / bc.LOCAL_DIR / "plans"
    return sorted(folder.glob("*.json")) if folder.is_dir() else []


def test_comment_writes_a_one_row_plan_and_nothing_else_and_never_spawns_az(repo, board, capsys):
    seed(repo, linked(SPEC4, 4521))
    before = snapshot(repo)
    code, out = comment(capsys, repo)
    assert code == 0 and board.calls == []
    (path,) = plan_files(repo)
    plan = json.loads(path.read_text(encoding="utf-8"))
    (row,) = plan["rows"]
    assert (row["action"], row["status"], row["ref"], row["work_item"], row["origin"]) == ("comment", "draft", SPEC4,
                                                                                         4521, "ad_hoc")
    assert row["text"] == "Ship it on Friday" and row["trailer"] == "none" and row["format"] == "markdown"
    assert row["idem_key"] == model.idem_key(model.AD_HOC, ref=SPEC4, text="Ship it on Friday")
    assert model.plan_hash(plan["rows"]) == plan["plan"] == path.stem
    assert plan["scope"]["all"] is False and plan["posture"] == "assisted"
    assert path.stem in out and "  | Ship it on Friday" in out
    assert f"apply --confirm {path.stem} --by" in out and "apply not offered" not in out
    changed = {k for k, v in snapshot(repo).items() if before.get(k) != v}
    assert changed == {f".sdlc/ado/local/plans/{path.name}"}          # the plan file; no ledger line, no config, no spec
    assert_clean_record(repo, out)


def test_comment_under_plan_only_exits_0_and_says_apply_is_not_offered_in_this_clone(repo, board, capsys):
    seed(repo, linked(SPEC4, 4521))
    set_config(repo, posture="plan-only")
    code, out = comment(capsys, repo)
    assert code == 0 and "apply not offered in this clone" in out and board.calls == []
    assert "apply --confirm" not in out and len(plan_files(repo)) == 1
    code, doc = run_json(capsys, "comment", SPEC4, "--message=Ship it on Friday", "--by", "@dev-one", "--repo", repo)
    assert code == 0 and doc["apply_offered"] is False and doc["posture"] == "plan-only"
    code, out = run(capsys, *apply_args(doc["plan"]), "--repo", repo)
    assert code == 2 and board.calls == []                            # the comment is drafted; apply stays refused


def test_comment_by_a_raw_work_item_id_needs_no_ledger_entry_and_a_ledgered_one_takes_its_ref(repo, board, capsys):
    code, out = comment(capsys, repo, "On a board item nobody linked", "#4530")
    assert code == 0 and board.calls == []
    (row,) = json.loads(plan_files(repo)[0].read_text(encoding="utf-8"))["rows"]
    assert (row["ref"], row["work_item"], row["target"]) == (None, 4530, "#4530")
    seed(repo, linked(SPEC4, 4521))
    code, doc = run_json(capsys, "comment", "#4521", "--message=Same item, by number", "--by", "@dev-one", "--repo", repo)
    assert code == 0 and doc["row"]["ref"] == SPEC4 and doc["row"]["target"] == SPEC4     # one key whichever way it is named


def test_comment_on_a_ref_this_clone_never_ledgered_or_an_empty_message_is_exit_1(repo, board, capsys):
    code, out = comment(capsys, repo)
    assert code == 1 and SPEC4 in out and "ledger" in out
    seed(repo, linked(SPEC4, 4521))
    for message in ("", "   ", "\n\t "):
        code, out = comment(capsys, repo, message)
        assert code == 1 and "empty" in out, repr(message)
    code, out = run(capsys, "comment", SPEC4, "--by", "@dev-one", "--repo", repo)
    assert code == 1 and "--message" in out
    for target in ("nonsense", "#0", "sdlc:spec", "#abc"):
        code, out = comment(capsys, repo, "hi", target)
        assert code == 1, target
    assert plan_files(repo) == [] and board.calls == []


@pytest.mark.parametrize("message,reason", [
    ("x" * 5000, "max_chars"),
    (f"write to {KIM} about it", "email_in_text"),
    (f"ping {KIM_DOMAIN} please", "email_in_text"),
])
def test_comment_a_refused_text_is_exit_2_ledgered_and_has_no_plan(repo, board, capsys, message, reason):
    seed(repo, linked(SPEC4, 4521))
    code, out = comment(capsys, repo, message)
    assert code == 2 and reason in out and plan_files(repo) == [] and board.calls == []
    (line,) = events_of(repo, "comment_refused")
    assert (line["reason"], line["ref"], line["work_item"], line["by"]) == (reason, SPEC4, 4521, "@dev-one")
    assert line["reason"] in bc.COMMENT_REFUSALS
    assert_clean_record(repo, out)                                    # the refused address is in neither output nor record
    if reason == "email_in_text":
        assert "corp.example.com" not in out and "corp.example.com" not in ledger_path(repo).read_text(encoding="utf-8")
        assert KIM not in out and KIM not in json.dumps(ledger(repo))


def test_comment_an_unknown_event_the_budget_and_a_deleted_item_are_the_refusals_the_kit_names(repo, board, capsys):
    seed(repo, linked(SPEC4, 4521))
    code, out = comment(capsys, repo, "hi there", SPEC4, "--event", "all_hands")
    assert code == 2 and "event_unknown" in out
    code, out = comment(capsys, repo, "hi there", SPEC4, "--event", "handoff")
    assert code == 0                                                  # a closed-set event is a label, not a refusal
    (row,) = json.loads(plan_files(repo)[0].read_text(encoding="utf-8"))["rows"]
    assert row["event"] == "handoff"
    set_config(repo, comments={**load_cfg(repo)["comments"], "per_item_budget": 1})
    seed(repo, {"ts": STAMP, "event": "commented", "ref": SPEC4, "work_item": 4521, "idem_key": "x:1", "comment_id": 1,
                "version": 1, "text_sha": "a" * 12, "plan": "b" * 12})
    code, out = comment(capsys, repo, "one more")
    assert code == 2 and "budget" in out
    seed(repo, {"ts": STAMP, "event": "observed", "ref": SPEC4, "kind": "spec", "work_item": 4521, "rev": 7,
                "class": "DELETED_IN_ADO"})
    set_config(repo, comments={**load_cfg(repo)["comments"], "per_item_budget": 50})
    code, out = comment(capsys, repo, "to a deleted one")
    assert code == 2 and "needs_disposition" in out
    assert [e["reason"] for e in events_of(repo, "comment_refused")] == ["event_unknown", "budget", "needs_disposition"]


def test_comment_mentions_are_text_and_say_so_and_a_bad_mention_is_exit_1(repo, board, capsys):
    seed(repo, linked(SPEC4, 4521))
    code, doc = run_json(capsys, "comment", SPEC4, "--message=Please look", "--mention", "@dev-two", "--mention",
                         "@dev-two", "--mention", "@kim-l", "--by", "@dev-one", "--repo", repo)
    assert code == 0 and doc["row"]["mentions"] == ["@dev-two", "@kim-l"]
    assert doc["row"]["text"] == "Please look @dev-two @kim-l"
    assert any("@dev-two" in n and "will not notify" in n for n in doc["row"]["notes"])
    code, text = comment(capsys, repo, "Again", SPEC4, "--mention", "@dev-two")
    assert "mention @dev-two: text only" in text
    code, text = comment(capsys, repo, "Bad", SPEC4, "--mention", "dev-two")
    assert code == 1 and "@handle" in text


def test_comment_that_was_already_posted_is_nothing_to_draft_and_exit_0(repo, board, capsys):
    seed(repo, linked(SPEC4, 4521))
    key = model.idem_key(model.AD_HOC, ref=SPEC4, text="Ship it on Friday")
    seed(repo, {"ts": STAMP, "event": "commented", "ref": SPEC4, "work_item": 4521, "idem_key": key, "comment_id": 5,
                "version": 1, "text_sha": "a" * 12, "plan": "b" * 12})
    code, doc = run_json(capsys, "comment", SPEC4, "--message=Ship it on Friday", "--by", "@dev-one", "--repo", repo)
    assert code == 0 and doc["plan"] is None and doc["row"]["reason"] == "already_posted" and plan_files(repo) == []


def test_comment_a_failed_ledger_append_for_a_refusal_prints_drift_and_exits_1(repo, capsys, monkeypatch):
    seed(repo, linked(SPEC4, 4521))
    refuse_ledger_appends(monkeypatch)
    code, out = comment(capsys, repo, "x" * 5000)
    assert code == 1 and "DRIFT:" in out


def test_comment_a_plan_file_that_cannot_be_written_is_exit_1(repo, capsys, monkeypatch):
    seed(repo, linked(SPEC4, 4521))

    def refuse(path, doc):
        raise PermissionError("read-only")
    monkeypatch.setattr(ado_sync, "_write_json", refuse)
    code, out = comment(capsys, repo)
    assert code == 1 and "could not write the plan file" in out


def test_comment_in_workflow_mode_uses_the_state_file(repo, board, capsys):
    seed(repo, linked(SPEC4, 4521))
    code, out = run(capsys, "comment", SPEC4, "--message=hi", "--by", "@dev-one", "--state",
                    repo / ".sdlc" / "state.yaml")
    assert code == 0 and len(plan_files(repo)) == 1


def test_comment_then_apply_posts_it_as_the_person_and_ledgers_it(repo, board, capsys):
    seed(repo, linked(SPEC4, 4521))
    code, doc = run_json(capsys, "comment", SPEC4, "--message=Ship it on Friday", "--by", "@dev-one", "--repo", repo)
    board.calls.clear()
    code, applied = run_json(capsys, *apply_args(doc["plan"]), "--repo", repo)
    assert code == 0 and applied["applied"][0]["action"] == "comment" and applied["applied"][0]["comment_id"] == 504
    assert route_key_boards(board.calls[0]) == "GET core/connectionData"
    ((key, argv, body),) = board.sent
    assert key == "POST wit/comments" and body == {"text": "Ship it on Friday"}     # no trailer on a human's own words
    (line,) = events_of(repo, "commented")
    assert (line["by"], line["executed_as"], line["trailer"], line["via"], line["comment_id"]) == \
        ("@dev-one", "@dev-one", "none", "comments-api", 504)
    assert line["text_sha"] == doc["row"]["text_sha"] and line["idem_key"] == doc["row"]["idem_key"]
    assert "Ship it on Friday" not in ledger_path(repo).read_text(encoding="utf-8")   # the ledger keeps a hash, never the words
    code, doc = run_json(capsys, "comment", SPEC4, "--message=Ship it on Friday", "--by", "@dev-one", "--repo", repo)
    assert doc["plan"] is None                                        # now keyed: not drafted twice


@pytest.mark.parametrize("name", sorted(GOLDEN_MESSAGES))
def test_message_goldens_reach_the_plan_row_and_the_request_body_byte_for_byte(repo, board, capsys, name):
    message = GOLDEN_MESSAGES[name]
    seed(repo, linked(SPEC4, 4521))
    code, out = run(capsys, "comment", SPEC4, f"--message={message}", "--by", "@dev-one", "--repo", repo)
    assert code == 0, out
    (path,) = plan_files(repo)
    (row,) = json.loads(path.read_text(encoding="utf-8"))["rows"]
    assert row["text"] == message                                     # as typed: nothing quoted, split or evaluated
    assert "".join(f"  | {line}\n" for line in message.split("\n")) in out + "\n"
    assert model.text_sha(message) == row["text_sha"]
    board.calls.clear()
    code, doc = run_json(capsys, *apply_args(path.stem), "--repo", repo)
    assert code == 0, doc
    ((key, argv, body),) = board.sent
    assert key == "POST wit/comments" and body == {"text": message}   # the request BODY carries it, byte for byte
    assert not any(message in word or (len(message) > 8 and message[:8] in word) for call in board.calls for word in call)
    assert "--message" not in " ".join(w for call in board.calls for w in call)   # and no az argv element ever holds it
    assert_detect_false(board)


@pytest.mark.parametrize("name", sorted(GOLDEN_MESSAGES))
def test_message_goldens_survive_a_real_command_line_argv_list(repo, board, name):
    """The same messages through a real process: an argv LIST, no shell, `--message=<text>` as one element."""
    message = GOLDEN_MESSAGES[name]
    seed(repo, linked(SPEC4, 4521))
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run([sys.executable, str(SCRIPT), "comment", SPEC4, f"--message={message}", "--by", "@dev-one",
                           "--repo", str(repo)], capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
    assert done.returncode == 0, done.stderr
    (path,) = plan_files(repo)
    (row,) = json.loads(path.read_text(encoding="utf-8"))["rows"]
    assert row["text"] == message
    assert done.stdout.count(path.stem) >= 1


def test_a_message_with_a_control_character_is_cleaned_not_refused(repo, capsys):
    seed(repo, linked(SPEC4, 4521))
    code, doc = run_json(capsys, "comment", SPEC4, "--message=bell\x07 and \x1b[31mred\x1b[0m\r\nnext", "--by",
                         "@dev-one", "--repo", repo)
    assert code == 0 and "\x07" not in doc["row"]["text"] and "\x1b" not in doc["row"]["text"]
    assert "\r" not in doc["row"]["text"] and doc["row"]["text"].endswith("\nnext")


# --- DRIFT: exit 1 on every write verb, `pull` and `discussion gc`; `plan` and `show --fetch` print it, exit 0 ---------

def test_plan_a_failed_ledger_append_prints_drift_and_still_exits_0_with_the_plan_shown(repo, board, capsys, monkeypatch):
    seed(repo, linked(SPEC4, 4521))
    refuse_ledger_appends(monkeypatch)
    code, out = run(capsys, "plan", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 0 and out.startswith("plan ") and "\nDRIFT: " in out        # the plan is shown; DRIFT leads its line
    code, doc = run_json(capsys, "plan", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 0 and doc["ok"] is True and doc["drift"].startswith("DRIFT:") and re.fullmatch(r"[0-9a-f]{12}",
                                                                                                 doc["plan"])
    assert (repo / doc["path"]).is_file()                             # the plan file stays: apply can still read it
    allow_ledger_appends(monkeypatch)
    assert [e["event"] for e in ledger(repo)] == ["linked"]
    code, doc = run_json(capsys, "plan", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 0 and doc["drift"] is None and doc["ok"] is True


def test_plan_that_has_nothing_to_append_never_drifts(repo, board, capsys, monkeypatch):
    seed(repo, linked(SPEC4, 4521))
    first = plan_spec4(capsys, repo)
    refuse_ledger_appends(monkeypatch)
    code, doc = run_json(capsys, "plan", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 0 and doc["plan"] == first["plan"]                 # the same plan is not ledgered twice: no append, no DRIFT


def test_show_fetch_a_failed_ledger_append_prints_drift_and_still_exits_0_with_the_discussion_shown(repo, board, capsys,
                                                                                                   monkeypatch):
    seed(repo, linked(SPEC4, 4521))
    refuse_ledger_appends(monkeypatch)
    code, out = run(capsys, "show", SPEC4, "--fetch", "--repo", repo)
    assert code == 0 and "Work item #4521" in out and "\nDRIFT: " in out
    assert cache.load_cache(repo, 4521) is not None                   # saved; it is the ledger line that is missing
    code, doc = run_json(capsys, "show", SPEC4, "--fetch", "--repo", repo)
    assert code == 0 and doc["ok"] is True and any(n.startswith("DRIFT:") for n in doc["notes"])
    allow_ledger_appends(monkeypatch)
    assert [e["event"] for e in ledger(repo)] == ["linked"]


def test_show_fetch_a_cache_that_cannot_be_saved_is_still_a_note_exit_0(repo, board, capsys, monkeypatch):
    seed(repo, linked(SPEC4, 4521))

    def refuse(root, doc):
        raise OSError("read-only")
    monkeypatch.setattr(cache, "save_cache", refuse)
    code, out = run(capsys, "show", SPEC4, "--fetch", "--repo", repo)
    assert code == 0 and "not cached" in out and [e["event"] for e in ledger(repo)] == ["linked"]


def test_show_without_fetch_and_status_and_drift_never_append_so_never_drift(repo, board, capsys, monkeypatch):
    seed(repo, linked(SPEC4, 4521))
    refuse_ledger_appends(monkeypatch)
    for argv in (["show", SPEC4], ["status"], ["drift"]):
        code, out = run(capsys, *argv, "--repo", repo)
        assert code == 0 and "DRIFT:" not in out, argv


@pytest.mark.parametrize("verb", ["discussion", "pull"])
def test_the_b2_verbs_that_already_exited_1_on_drift_still_do(repo, board, capsys, monkeypatch, verb):
    seed(repo, linked(SPEC4, 4521))
    cache.save_cache(repo, {"work_item": 4521, "as_of": "2026-06-01T00:00Z", "comments": []})
    refuse_ledger_appends(monkeypatch)
    argv = ["discussion", "gc"] if verb == "discussion" else ["pull"]
    code, out = run(capsys, *argv, "--repo", repo)
    assert code == 1 and "DRIFT:" in out


# --- discipline --------------------------------------------------------------------------------------------

def test_the_write_path_has_no_shell_no_join_no_subprocess_and_none_of_the_options_that_skip_the_board_s_rules():
    text = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s+subprocess\b", text, re.MULTILINE)
    assert "shell=True" not in text and "shlex.join" not in text
    assert not re.search(r'" "\.join\((args|argv|cmd)', text)
    assert not re.search(r"-preview\.\d", text)
    for word in ("bypassRules", "suppressNotifications", "validateOnly"):       # the argv golden covers what az is sent
        assert word not in text, word


def test_every_apply_refusal_has_its_own_sentence():
    assert set(ado_sync.APPLY_REFUSAL_WORDS) == set(model.APPLY_REFUSALS)
    assert all(isinstance(s, str) and s for s in ado_sync.APPLY_REFUSAL_WORDS.values())


def test_every_az_argv_a_write_verb_builds_carries_detect_false_and_never_a_forbidden_word(repo, board, capsys):
    seed(repo, linked(SPEC4, 4521), linked(SPEC5, 4522, rev=3))
    put_batch(board, board_row(load_wit("workitems_batch")), item_row(4522, "risk:LOW; sdlc:spec:0005; sdlc:status:draft"))
    plan = plan_doc(capsys, repo, "--kind", "spec", "--id", "0004", "--id", "0005")
    assert run(capsys, *apply_args(plan["plan"]), "--repo", repo)[0] == 0
    assert run(capsys, "link-pr", "--spec", "0004", "--pr", "12", "--by", "@dev-one", "--repo", repo)[0] == 0
    assert board.calls and board.written()
    assert_detect_false(board)
    forbidden = ("suppressNotifications", "bypassRules", "validateOnly", "reactions", "attachments", "graph/",
                 "notification")
    for call in board.calls:
        assert not any(word in arg for arg in call for word in forbidden), call
        assert not any(re.search(r"-preview\.\d", arg) for arg in call), call
        assert "--only-show-errors" not in call and "--repository" not in call
    for key, argv, _body_ in board.sent:
        assert not (key.split(" ")[0] in ("PATCH", "DELETE") and "comments" in key)


# --- B4-P1a: the advisory first-seed note agrees with apply's refusal, and the B4 verb-table rows ----------------------

def _applied(action, **extra) -> dict:
    return {"ts": STAMP, "event": "applied", "ref": SPEC4, "action": action, "work_item": 4521, "rev_after": 8,
            "plan": "a" * 12, **extra}


def test_the_first_seed_note_ignores_an_applied_line_that_is_not_a_create_or_an_update():
    cfg, counts = {"limits": {"first_seed": 1, "writes_per_run": 50}}, {"create": 3, "update": 0}

    def first(ledger_) -> bool:
        return any("first seed" in n for n in ado_sync._plan_notes(cfg, ledger_, True, counts))
    assert first([]) and first([_applied("link_pr")])             # `link-pr` writes an `applied` line and creates nothing
    assert not first([_applied("create")]) and not first([_applied("update")])
    assert first([{k: v for k, v in _applied("create").items() if k != "action"}])   # no action: not a create or an update
    assert not any("first seed" in n for n in ado_sync._plan_notes(cfg, [], False, counts))   # not an --all: no note
    assert not any("first seed" in n for n in ado_sync._plan_notes(cfg, [], True, {"create": 1, "update": 0}))
    assert tuple(ado_sync.apply_mod.FIELD_ACTIONS) == ("create", "update")    # the one rule both sides read


def test_the_first_seed_note_and_the_apply_refusal_agree_after_a_link_pr_line(repo, board, capsys):
    set_config(repo, limits={"writes_per_run": 50, "first_seed": 1})
    seed(repo, _applied("link_pr"))
    plan = plan_doc(capsys, repo, "--all", "--kind", "spec")
    assert plan["counts"]["create"] > 1 and any("first seed" in n for n in plan["notes"])
    board.calls.clear()
    code, doc = run_json(capsys, *apply_args(plan["plan"]), "--repo", repo)
    assert code == 2 and doc["refused_reason"] == "first_seed" and board.written() == []


def test_the_b4_verb_table_rows_are_in_the_parser():
    parser = ado_sync.build_parser()

    def flags(*verb):
        node = parser
        for word in verb:
            node = next(a for a in node._actions if getattr(a, "choices", None)).choices[word]
        return {s for a in node._actions for s in a.option_strings} - {"-h", "--help", "--state", "--repo", "--json"}
    assert "reconcile" in ado_sync.VERBS and callable(ado_sync.VERBS["reconcile"])
    assert flags("reconcile") == {"--field", "--take", "--by", "--owner", "--reason", "--from-comment"}
    assert flags("pull") == {"--id", "--all", "--discussion", "--full", "--propose-specs"}
