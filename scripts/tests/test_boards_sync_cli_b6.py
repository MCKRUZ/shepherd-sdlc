from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import HAND_WRITTEN_PROCESS, route_key_boards

# B6-P1 -- the `sync` verb of the Azure Boards mirror's CLI (`ado_sync.py`), the one footer, and the capability.
#
# What this pins, and why each line exists (build kit sections 1 K9/K11/K28, 4, 9 guardrails 24-27; spec 0040):
#   * `sync` is a READ verb that runs four stages in `SYNC_STAGES` order: the fields pull, the drift read FROM THE
#     PULL'S OWN ROWS (the drift stage asks the board nothing: `az.calls` of `sync` are exactly `pull`'s then
#     `plan`'s, guardrail 24 and spec 0040's fourth acceptance check), the discussion pull ONLY on `--discussion` (and
#     it has no `--full`, `--by`, `--validate` or `--propose-specs`), then the plan;
#   * exit 0 on every path except a pull-stage ledger `DRIFT` (1); a stage that cannot read says so and the next
#     stage still runs; with nothing readable the document is `SYNC_NODATA` with only the `reason` strings filled;
#   * the hook line is written twice (the pull stage's, then the plan stage's), so line 1 is the plan stage's;
#   * `plan --json` gains `apply_offered` and `next`; the one footer `apply_next_line(plan)` ends the text of `plan`,
#     `comment` and `sync` wherever an apply is offered, and a plan-only clone prints none (the B2 golden stays
#     byte-equal);
#   * the two unavailable helpers: `_unavailable` says `"unavailable": true`; `_read_unavailable` keeps the legacy
#     verbs' sentence in `unavailable` (the desktop's DiscussionBlock reads a string there) and says `true` for `sync`.
#
# Nothing here spawns `az`: `boards_env` forbids it at the seam and the `az` fixture answers from the `wit/` fixtures.
# The people in the fixtures are fictional and no test writes a real one.

import argparse
import copy
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

import ado_schema
import ado_sync
import ado_sync_config as cfgmod
import ado_sync_model as model
import boards_contract as bc
import capabilities
from tests.ado_boards_fixtures import load_wit

BOARDS_PROCESS = HAND_WRITTEN_PROCESS    # the item fixtures were written for the hand-written Agile process

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ado_sync.py"
COMMAND_DOC = ROOT / "commands" / "sprd-ado.md"
MINI = Path(__file__).resolve().parent / "fixtures" / "boards_repo"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
GOLDEN_PLAN = GOLDEN_DIR / "ado_plan_spec_0004.txt"
GOLDEN_SYNC = GOLDEN_DIR / "ado_sync_spec_0004.txt"
GOLDEN_NODATA = GOLDEN_DIR / "ado_sync_unavailable.json"
NOT_INSTALLED = "The Azure CLI (`az`) is not installed or not on PATH."

NOW = datetime(2026, 10, 13, 9, 30, tzinfo=timezone.utc)
STAMP = "2026-10-13T09:30Z"
SPEC4 = "sdlc:spec:0004"
SPEC5 = "sdlc:spec:0005"
RISK_VALUES = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}
SYNC_FLAGS = {"--kind", "--id", "--sprint", "--all", "--discussion", "--no-comments"}
COMMON_FLAGS = {"--state", "--repo", "--json", "--help", "-h"}
FOOTER = "Next: `ado_sync.py apply --confirm {plan} --by <you>` sends it, as whoever az is signed in as"

ROSTER = """\
version: "1.0"
teams:
  - name: core
    lead: "@dev-one"
people:
  - handle: "@dev-one"
    name: "Person 1"
    email: "dev.one@example.com"
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


# --- helpers ---------------------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(ado_schema, "now_utc", lambda: NOW)


def run(capsys, *argv):
    code = ado_sync.main([str(a) for a in argv])
    return code, capsys.readouterr().out


def run_json(capsys, *argv):
    code, out = run(capsys, *argv, "--json")
    return code, json.loads(out)


def set_config(root: Path, **changes) -> None:
    path = root / bc.CONFIG_FILE
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg.update(changes)
    path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")


def build_repo(root: Path, capsys, az) -> Path:
    """A copy of the mini repository with the starter config (posture plan-only), the discovered schema and a
    roster that knows the fixtures' people. Setup's own az calls are forgotten."""
    shutil.copytree(MINI, root)
    (root / ".sdlc" / "team.yaml").write_text(ROSTER, encoding="utf-8")
    assert ado_sync.main(["config", "init", "--repo", str(root)]) == 0
    assert ado_sync.main(["discover", "--repo", str(root)]) == 0
    set_config(root, fields={"spec": {"risk": {"field": "Custom.RiskTier", "values": RISK_VALUES}}})
    capsys.readouterr()
    az.calls.clear()
    return root


@pytest.fixture
def repo(tmp_path, az, capsys) -> Path:
    return build_repo(tmp_path / "repo", capsys, az)


def linked(ref: str, wid: int, rev: int = 7) -> dict:
    """A linking line with no `by`: no handle, so the ledger scan below can ask for no `@` at all."""
    return {"ts": "2026-10-12T08:00Z", "event": "linked", "ref": ref, "kind": ref.split(":")[1], "work_item": wid,
            "how": "linked", "rev_after": rev, "type": "User Story"}


def seed(root: Path, *events: dict) -> None:
    path = root / bc.LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def ledger(root: Path) -> list[dict]:
    path = root / bc.LEDGER
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def tagged(untagged: list[int]):
    """A `boards query` answer: the ids the candidates query (the one that mentions `sdlc-repo:`) finds."""
    def answer(args):
        wiql = args[args.index("--wiql") + 1]
        return [{"id": i} for i in (untagged if "sdlc-repo:" in wiql else [])]
    return answer


def board_row(doc: dict, wid: int = 4521) -> dict:
    return next(r for r in doc["value"] if r and r["id"] == wid)


def synced_batch(rev: int = 8) -> dict:
    """The batch fixture with item 4521 changed to carry what spec 0004's projection pushes."""
    doc = copy.deepcopy(load_wit("workitems_batch"))
    row = board_row(doc)
    row["rev"] = rev
    row["fields"]["System.State"] = "Ready"
    row["fields"]["System.Tags"] = "; ".join(sorted({"data-review:n-a", "eng-review:accepted", "risk:HIGH",
                                                     "sdlc-repo:claims-api", SPEC4, "sdlc:status:ready"}))
    row["fields"]["Custom.RiskTier"] = "HIGH"
    return doc


def board_calls(az) -> list[list[str]]:
    """The recorded argvs, with the throwaway request-body path (a fresh temporary file per call) named `<body>`."""
    return [["<body>" if i and c[i - 1] == "--in-file" else a for i, a in enumerate(c)] for c in az.calls]


def zeros(node) -> list:
    """Every integer 0 in a document (a bool is not one): the honest counting rule says a document that measured
    nothing holds none."""
    found = []
    if isinstance(node, dict):
        for value in node.values():
            found += zeros(value)
    elif isinstance(node, list):
        for value in node:
            found += zeros(value)
    elif type(node) is int and node == 0:
        found.append(node)
    return found


def blank_reasons(doc: dict) -> dict:
    """`doc` with the `reason` strings of the top level and of the three stages cleared, as the golden holds them."""
    out = copy.deepcopy(doc)
    out["reason"] = None
    for stage in ("pull", "drift", "plan"):
        out[stage]["reason"] = None
    return out


def last_line(text: str) -> str:
    return text.rstrip("\n").splitlines()[-1]


# --- the contract the verb is built on ------------------------------------------------------------------

def test_sync_is_a_registered_read_verb_with_the_documented_unavailable_extras():
    assert "sync" in ado_sync.VERBS and ado_sync.VERBS["sync"] is ado_sync.cmd_sync
    assert "sync" in ado_sync.READ_VERBS
    assert ado_sync.UNAVAILABLE_EXTRA["sync"] == {"pull": None, "drift": None, "discussion": None, "plan": None,
                                                  "counts": None, "next": None}
    assert list(model.SYNC_STAGES) == ["pull", "drift", "discussion", "plan"]


def sync_parser():
    parser = ado_sync.build_parser()
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return action.choices["sync"]


def test_sync_has_exactly_the_documented_flags_and_none_of_the_forbidden_ones():
    flags = {s for a in sync_parser()._actions for s in a.option_strings if s.startswith("--")}
    assert flags == SYNC_FLAGS | (COMMON_FLAGS - {"-h"})
    for forbidden in ("--full", "--by", "--propose-specs", "--validate", "--confirm"):
        assert forbidden not in flags


@pytest.mark.parametrize("flag", ["--full", "--by=@dev-one", "--propose-specs", "--validate"])
def test_sync_refuses_a_flag_it_does_not_have_as_an_argparse_error(flag, capsys):
    with pytest.raises(SystemExit) as stop:
        ado_sync.main(["sync", flag, "--repo", "."])
    assert stop.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_sync_refuses_a_kind_the_library_does_not_have(capsys):
    with pytest.raises(SystemExit) as stop:
        ado_sync.main(["sync", "--kind", "bogus", "--repo", "."])
    assert stop.value.code == 2


def test_sync_help_leaves_an_empty_cwd_empty_in_process_and_in_a_subprocess(tmp_path, monkeypatch, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    with pytest.raises(SystemExit) as stop:
        ado_sync.main(["sync", "--help"])
    assert stop.value.code == 0
    assert "--discussion" in capsys.readouterr().out and list(empty.iterdir()) == []
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, str(SCRIPT), "sync", "--help"], cwd=empty, capture_output=True, text=True,
                          env=env, timeout=60)
    assert done.returncode == 0 and "--no-comments" in done.stdout and list(empty.iterdir()) == []


def test_the_capability_row_is_declared_and_lists_every_sync_flag():
    row = capabilities.CAPABILITIES["ado-sync"]
    assert row == {"script": "ado_sync.py", "argv": ["sync"],
                   "flags": ["--repo", "--state", "--json",                      # the common parent, like every sibling row
                             "--kind", "--id", "--sprint", "--all", "--discussion", "--no-comments"]}
    assert "ado-sync" in capabilities.list_capabilities()


# --- the happy path, on the mini repository ---------------------------------------------------------------

def sync_json(capsys, repo, *extra):
    code, doc = run_json(capsys, "sync", "--kind", "spec", "--id", "0004", "--repo", repo, *extra)
    assert code == 0, doc
    return doc


def test_sync_runs_the_stages_and_its_plan_is_the_plain_plan(repo, az, capsys):
    seed(repo, linked(SPEC4, 4521))
    doc = sync_json(capsys, repo)
    assert doc["ok"] is True and doc["unavailable"] is False and doc["reason"] is None and doc["verb"] == "sync"
    assert doc["scope"] == {"kinds": ["spec"], "ids": ["0004"], "sprint": None, "all": False, "discussion": False}
    assert doc["as_of"] == STAMP == doc["pull"]["as_of"]
    assert doc["pull"]["recorded"]["observed"] == 1 and doc["pull"]["unavailable"] is False
    assert doc["drift"]["counts"] == doc["pull"]["counts"] == {"IN_SYNC": 1}
    assert doc["discussion"] is None and doc["drift_error"] is None
    code, plain = run_json(capsys, "plan", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 0
    assert doc["plan"]["rows"] == plain["rows"] and doc["plan"]["plan"] == plain["plan"]
    assert re.fullmatch(r"[0-9a-f]{12}", doc["plan"]["plan"])
    assert set(doc) == set(model.SYNC_NODATA)           # the keys of the pinned document, on every path
    assert az.written() == []


def test_sync_drift_comes_from_the_pull_rows_and_asks_the_board_nothing(repo, az, capsys):
    """The drift stage classifies the pull's own rows and makes no board read of its own: not the batch read, and not
    `drift`'s untagged query either. Untagged items on the board stay `drift`'s question; here they are `None`
    (never searched) with a note saying so, never an empty list."""
    seed(repo, linked(SPEC4, 4521, rev=1))                # the board moved from rev 1 to 7: a real drift to classify
    az.answers["boards query"] = tagged([4530, 4531])     # untagged items exist; sync must not go looking for them
    doc = sync_json(capsys, repo)
    assert doc["pull"]["counts"] == {"SDLC_OWNED_DRIFT": 1} == doc["drift"]["counts"]
    assert doc["drift"]["unmapped"] is None
    assert doc["drift"]["notes"] == [ado_sync.SYNC_UNTAGGED_NOTE]
    assert "not searched" in ado_sync.SYNC_UNTAGGED_NOTE and "`drift`" in ado_sync.SYNC_UNTAGGED_NOTE
    assert az.count("boards", "query") == 0
    assert doc["counts"]["drifted"] == 1
    code, text = run(capsys, "sync", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 0 and "#4530" not in text and "untagged on the board:" not in text
    assert f"note: {ado_sync.SYNC_UNTAGGED_NOTE}" in text


def test_sync_drift_says_not_searched_when_the_config_has_no_path_to_look_under(repo, az, capsys):
    seed(repo, linked(SPEC4, 4521))
    set_config(repo, area_path=None, iterations={})
    doc = sync_json(capsys, repo)
    assert doc["drift"]["unmapped"] is None and doc["drift"]["notes"] == [ado_sync.SYNC_UNTAGGED_NOTE]
    assert az.count("boards", "query") == 0


def test_the_board_is_read_once_for_the_fields_az_calls_of_sync_are_pull_then_plan(tmp_path, az, capsys):
    """Guardrail 24 and spec 0040's fourth acceptance check: the `az.calls` recorded by `sync` equal those recorded by
    `pull` then `plan` over the same fixtures, so the drift stage adds 0 board reads -- no batch read and no query.
    Three fresh copies so each verb meets the same state; the untagged query has an answer, so a stray one would
    have been made and recorded, not silently refused."""
    calls = {}
    for name, argv in (("pull", ["pull", "--id", "0004"]), ("plan", ["plan", "--kind", "spec", "--id", "0004"]),
                       ("sync", ["sync", "--kind", "spec", "--id", "0004"])):
        root = build_repo(tmp_path / name, capsys, az)
        seed(root, linked(SPEC4, 4521))
        az.answers["boards query"] = tagged([4530, 4531])
        code, _ = run(capsys, *argv, "--repo", root)
        assert code == 0
        calls[name] = board_calls(az)
        az.calls.clear()
    assert calls["sync"] == calls["pull"] + calls["plan"]
    assert [c for c in calls["sync"] if c[:2] == ["boards", "query"]] == []
    batch = [c for c in calls["sync"] if route_key_boards(c) == "POST wit/workitemsbatch"]
    assert len(batch) == 2                                 # one for the pull, one for the plan: none for the drift


def test_discussion_is_read_only_on_discussion_and_adds_exactly_the_discussion_pull_calls(tmp_path, az, capsys):
    stage_calls = {}
    for name, argv in (("pull", ["pull", "--id", "0004"]), ("plan", ["plan", "--kind", "spec", "--id", "0004"])):
        root = build_repo(tmp_path / f"alone-{name}", capsys, az)
        seed(root, linked(SPEC4, 4521))
        code, _ = run(capsys, *argv, "--repo", root)
        assert code == 0
        stage_calls[name] = board_calls(az)
        az.calls.clear()

    plain_root = build_repo(tmp_path / "plain", capsys, az)
    seed(plain_root, linked(SPEC4, 4521))
    code, doc = run_json(capsys, "sync", "--kind", "spec", "--id", "0004", "--repo", plain_root)
    assert code == 0 and doc["discussion"] is None
    plain_calls = board_calls(az)
    assert not [c for c in plain_calls if "wit/comments" in route_key_boards(c)]       # a bare sync never reads comments
    assert plain_calls == stage_calls["pull"] + stage_calls["plan"]
    az.calls.clear()

    only_root = build_repo(tmp_path / "only", capsys, az)
    seed(only_root, linked(SPEC4, 4521))
    code, _ = run(capsys, "pull", "--id", "0004", "--discussion", "--repo", only_root)
    assert code == 0
    discussion_calls = board_calls(az)
    assert [c for c in discussion_calls if "wit/comments" in route_key_boards(c)]
    az.calls.clear()

    full_root = build_repo(tmp_path / "full", capsys, az)
    seed(full_root, linked(SPEC4, 4521))
    code, doc = run_json(capsys, "sync", "--kind", "spec", "--id", "0004", "--discussion", "--repo", full_root)
    assert code == 0 and isinstance(doc["discussion"], dict) and doc["discussion"]["discussion"] == "pulled"
    assert doc["scope"]["discussion"] is True
    with_calls = board_calls(az)
    # the pull stage, then the discussion pull, then the plan; the drift stage between them asks the board nothing
    assert with_calls == stage_calls["pull"] + discussion_calls + stage_calls["plan"]
    assert az.written() == []


def test_the_stages_appear_in_the_documented_order_in_the_text(repo, az, capsys):
    seed(repo, linked(SPEC4, 4521))
    code, text = run(capsys, "sync", "--kind", "spec", "--id", "0004", "--discussion", "--repo", repo)
    assert code == 0
    marks = [text.index(m) for m in ("== pull ==", "== drift ==", "== discussion ==", "== plan ==")]
    assert marks == sorted(marks)
    assert text.splitlines()[0] == (f"Azure Boards mirror: sync  (as of {STAMP}; reads the board, sends nothing)")
    assert "== drift ==  (from the pull's rows; the board is not read again)" in text
    assert ado_sync.SYNC_SECTIONS["drift"] == "== drift ==  (from the pull's rows; the board is not read again)"
    code, text = run(capsys, "sync", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert "== discussion ==" not in text


def test_sync_scope_relays_every_selector_and_no_comments_reaches_the_plan(repo, az, capsys):
    seed(repo, linked(SPEC4, 4521))
    code, doc = run_json(capsys, "sync", "--kind", "spec", "--kind", "feature", "--id", "0004", "--id", "FE-03",
                         "--no-comments", "--repo", repo)
    assert code == 0 and doc["scope"] == {"kinds": ["spec", "feature"], "ids": ["0004", "FE-03"], "sprint": None,
                                          "all": False, "discussion": False}
    assert doc["plan"]["comments"]["planned"] is False and doc["plan"]["scope"]["ids"] == ["0004", "FE-03"]
    code, doc = run_json(capsys, "sync", "--all", "--repo", repo)
    assert doc["scope"]["all"] is True and doc["plan"]["scope"]["all"] is True
    code, doc = run_json(capsys, "sync", "--sprint", "S07", "--repo", repo)
    assert doc["scope"]["sprint"] == "S07" and doc["plan"]["scope"]["sprint"] == "S07"


def test_a_sprint_that_is_not_a_sprint_id_is_a_usage_error_before_anything_is_read(repo, az, capsys):
    before = snapshot(repo)
    code, out = run(capsys, "sync", "--sprint", "7", "--repo", repo)
    assert code == 1 and "not a sprint id" in out
    assert az.calls == [] and snapshot(repo) == before


def test_sync_in_workflow_mode_uses_the_state_file(repo, az, capsys):
    seed(repo, linked(SPEC4, 4521))
    code, doc = run_json(capsys, "sync", "--kind", "spec", "--id", "0004", "--state", repo / ".sdlc" / "state.yaml")
    assert code == 0 and doc["pull"]["recorded"]["observed"] == 1


def test_the_hook_line_is_written_twice_and_line_one_is_the_plan_stages(repo, az, capsys, monkeypatch):
    seed(repo, linked(SPEC4, 4521))
    written = []
    real = cfgmod.write_hook_status
    monkeypatch.setattr(cfgmod, "write_hook_status", lambda root, line: (written.append(line), real(root, line))[1])
    doc = sync_json(capsys, repo)
    assert len(written) == 2 and written[0] == doc["pull"]["hook_line"] and written[1] == doc["plan"]["hook_line"]
    assert written[0] != written[1]                        # the plan stage knows the pending row; the pull stage did not
    first = (repo / bc.HOOK_STATUS).read_text(encoding="utf-8").splitlines()[0]
    assert first == doc["plan"]["hook_line"] == doc["hook_line"] == f"1 row pending · 0 drifted · as of {STAMP}"
    assert doc["counts"] == {"create": 0, "update": 1, "comments": 0, "drifted": 0}


def test_every_ledger_line_and_plan_file_is_free_of_addresses_guids_and_handles(tmp_path, az, capsys):
    root = build_repo(tmp_path / "scan", capsys, az)
    seed(root, linked(SPEC4, 4521, rev=1))
    az.answers["boards query"] = tagged([4530])
    for argv in (["sync", "--kind", "spec", "--id", "0004"], ["sync", "--kind", "spec", "--id", "0004", "--discussion"]):
        code, _ = run(capsys, *argv, "--repo", root)
        assert code == 0, argv
    written = [p for p in root.rglob("*.jsonl") if not (MINI / p.relative_to(root)).is_file()]   # not the fixture's own
    plans = list((root / ".sdlc" / "ado" / "local" / "plans").glob("*.json"))
    assert root / bc.LEDGER in written and plans
    for path in [*written, *plans]:                       # spec 0004 has no assignee: no handle, no address, no GUID
        text = path.read_text(encoding="utf-8")
        assert "@" not in text and not bc.GUID_RE.search(text), path
    code, _ = run(capsys, "sync", "--all", "--discussion", "--repo", root)    # every kind: a plan may name a roster handle
    assert code == 0
    for path in [*root.rglob("*.jsonl"), *(root / ".sdlc" / "ado" / "local" / "plans").glob("*.json")]:
        text = path.read_text(encoding="utf-8")
        assert not bc.EMAIL_RE.search(text) and not bc.GUID_RE.search(text), path
    assert all(e["event"] in bc.LEDGER_EVENTS for e in ledger(root))


# --- a stage that cannot read, and nothing readable -------------------------------------------------------

def test_with_no_config_every_stage_is_unavailable_and_the_document_is_the_pinned_one(tmp_path, az, capsys):
    before = snapshot(tmp_path)
    code, doc = run_json(capsys, "sync", "--repo", tmp_path)
    assert code == 0
    assert blank_reasons(doc) == model.SYNC_NODATA == json.loads(GOLDEN_NODATA.read_text(encoding="utf-8"))
    for key in (None, "pull", "drift", "plan"):
        reason = doc["reason"] if key is None else doc[key]["reason"]
        assert isinstance(reason, str) and "config init" in reason
    assert doc["unavailable"] is True and doc["counts"] is None and doc["next"] is None and zeros(doc) == []
    assert snapshot(tmp_path) == before and az.calls == []
    code, text = run(capsys, "sync", "--repo", tmp_path)
    assert code == 0 and text.count("unavailable:") == 3 and "== plan ==" in text and "config init" in text


def test_with_no_discovered_schema_it_says_so_and_exits_0(tmp_path, az, capsys):
    assert ado_sync.main(["config", "init", "--repo", str(tmp_path)]) == 0
    capsys.readouterr()
    code, doc = run_json(capsys, "sync", "--repo", tmp_path)
    assert code == 0 and blank_reasons(doc) == model.SYNC_NODATA and "discover" in doc["plan"]["reason"]


def test_when_az_cannot_be_reached_every_stage_is_unavailable_exit_0_and_nothing_is_written(repo, az, capsys):
    seed(repo, linked(SPEC4, 4521, rev=1))
    az.fail["workitemsbatch"] = NOT_INSTALLED
    before = snapshot(repo)
    code, doc = run_json(capsys, "sync", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 0 and blank_reasons(doc) == model.SYNC_NODATA and zeros(doc) == []
    assert "not installed" in doc["pull"]["reason"] and "not installed" in doc["plan"]["reason"]
    assert snapshot(repo) == before and az.count("boards", "query") == 0       # the drift stage never queries the board
    code, text = run(capsys, "sync", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 0 and "not_installed" in text and "== plan ==" in text


def test_with_discussion_requested_and_nothing_readable_the_discussion_stage_says_so(tmp_path, az, capsys):
    code, doc = run_json(capsys, "sync", "--discussion", "--repo", tmp_path)
    assert code == 0 and doc["unavailable"] is True
    assert doc["discussion"] == {"unavailable": True, "reason": doc["pull"]["reason"]}


def test_a_corrupt_ledger_is_unavailable_for_every_stage_exit_0_and_nothing_is_read_or_written(repo, az, capsys):
    seed(repo, linked(SPEC4, 4521))
    with open(repo / bc.LEDGER, "a", encoding="utf-8") as f:
        f.write("this is not json\n")
    before = snapshot(repo)
    code, doc = run_json(capsys, "sync", "--repo", repo)
    assert code == 0 and doc["unavailable"] is True and "line 2 is not a JSON object" in doc["pull"]["reason"]
    assert snapshot(repo) == before and az.calls == []


def test_a_plan_file_that_cannot_be_written_leaves_only_the_plan_stage_unavailable(repo, az, capsys, monkeypatch):
    seed(repo, linked(SPEC4, 4521))

    def refuse(path, doc):
        raise PermissionError("read-only")
    monkeypatch.setattr(ado_sync, "_write_json", refuse)
    code, doc = run_json(capsys, "sync", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 0 and doc["unavailable"] is False and doc["pull"]["unavailable"] is False
    assert doc["plan"]["unavailable"] is True and doc["plan"]["reason"].startswith("could not write the plan file")
    assert doc["counts"] is None and doc["next"] is None and doc["hook_line"] == doc["pull"]["hook_line"]
    code, text = run(capsys, "sync", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 0 and "unavailable: could not write the plan file" in text


# --- a ledger append that fails in the pull stage ---------------------------------------------------------

def refuse_first_append(monkeypatch):
    real = ado_sync.append_ledger
    seen = []

    def append(root, events):
        seen.append(events)
        if len(seen) == 1:
            raise ado_sync.LedgerDrift("DRIFT: the ledger append failed (.sdlc/metrics/ado-sync-log.jsonl): disk\n"
                                       "       Anything else this verb wrote now disagrees with the ledger; "
                                       "re-run it once the path is writable.")
        return real(root, events)
    monkeypatch.setattr(ado_sync, "append_ledger", append)
    return seen


def test_a_pull_stage_ledger_drift_is_recorded_the_later_stages_run_and_the_exit_is_1(repo, az, capsys, monkeypatch):
    seed(repo, linked(SPEC4, 4521))
    seen = refuse_first_append(monkeypatch)
    code, doc = run_json(capsys, "sync", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 1 and doc["drift_error"].startswith("DRIFT:") and len(seen) >= 2
    assert doc["plan"]["unavailable"] is False and re.fullmatch(r"[0-9a-f]{12}", doc["plan"]["plan"])
    assert doc["pull"]["unavailable"] is True and doc["drift"]["unavailable"] is True and doc["unavailable"] is False
    assert doc["hook_line"] == doc["plan"]["hook_line"]


def test_a_pull_stage_ledger_drift_ends_the_text_with_the_drift_sentence(repo, az, capsys, monkeypatch):
    seed(repo, linked(SPEC4, 4521))
    refuse_first_append(monkeypatch)
    code, text = run(capsys, "sync", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 1 and "== plan ==" in text and "\nDRIFT: " in text
    assert text.rstrip("\n").splitlines()[-2].startswith("DRIFT:") and "re-run it once the path is writable" in last_line(text)


@pytest.mark.parametrize("verb,code", [("sync", 1), ("pull", 1), ("status", 0), ("plan", 0), ("drift", 0), ("show", 0),
                                       ("apply", 1), ("discussion", 1)])
def test_main_answers_a_ledger_drift_with_the_exit_the_verb_table_gives(verb, code, monkeypatch, capsys, tmp_path):
    def boom(args, root):
        raise ado_sync.LedgerDrift("DRIFT: x")
    monkeypatch.setitem(ado_sync.VERBS, verb, boom)
    argv = {"show": ["show", "#1"], "discussion": ["discussion", "gc"]}.get(verb, [verb])
    assert ado_sync.main([*argv, "--repo", str(tmp_path)]) == code
    assert capsys.readouterr().out.startswith("DRIFT:")


# --- the two unavailable helpers --------------------------------------------------------------------------

def test_unavailable_says_true_and_keeps_the_sentence_in_reason(tmp_path, capsys):
    code = ado_sync._unavailable(argparse.Namespace(json=True), tmp_path, "pull", "no board", items=[], counts=None)
    doc = json.loads(capsys.readouterr().out)
    assert code == 0 and doc["unavailable"] is True and doc["reason"] == "no board" and doc["items"] == []


def test_read_unavailable_says_true_for_sync_and_keeps_the_sentence_in_reason(capsys):
    code = ado_sync._read_unavailable(argparse.Namespace(json=True), "sync", "the ledger cannot be read")
    doc = json.loads(capsys.readouterr().out)
    assert code == 0 and doc["unavailable"] is True and doc["reason"] == "the ledger cannot be read" and doc["ok"] is True
    assert {k: doc[k] for k in ado_sync.UNAVAILABLE_EXTRA["sync"]} == ado_sync.UNAVAILABLE_EXTRA["sync"]


@pytest.mark.parametrize("verb", ["plan", "status", "pull", "drift", "show"])
def test_read_unavailable_keeps_the_legacy_shape_for_the_older_read_verbs(verb, capsys):
    ado_sync._read_unavailable(argparse.Namespace(json=True), verb, "the ledger cannot be read")
    doc = json.loads(capsys.readouterr().out)
    assert doc["unavailable"] == doc["reason"] == "the ledger cannot be read"     # a sentence: DiscussionBlock reads it


def test_main_answers_an_illegal_that_escapes_sync_with_the_unavailable_document(monkeypatch, capsys, tmp_path):
    def boom(args, root):
        raise ado_sync.Illegal("something the stages did not catch")
    monkeypatch.setitem(ado_sync.VERBS, "sync", boom)
    code, doc = run_json(capsys, "sync", "--repo", tmp_path)
    assert code == 0 and doc["unavailable"] is True and doc["reason"] == "something the stages did not catch"
    assert doc["pull"] is None and doc["plan"] is None and doc["counts"] is None and doc["next"] is None


# --- the one footer ---------------------------------------------------------------------------------------

def plan_text_and_doc(capsys, repo):
    code, text = run(capsys, "plan", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 0
    code, doc = run_json(capsys, "plan", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 0
    return text, doc


def test_plan_only_prints_no_footer_and_the_b2_golden_stays_byte_equal(repo, az, capsys):
    seed(repo, linked(SPEC4, 4521))
    text, doc = plan_text_and_doc(capsys, repo)
    assert text == GOLDEN_PLAN.read_text(encoding="utf-8") and "Next:" not in text
    assert doc["posture"] == "plan-only" and doc["apply_offered"] is False and doc["next"] is None


def test_assisted_with_pending_rows_offers_the_apply_and_the_text_ends_with_the_footer(repo, az, capsys):
    set_config(repo, posture="assisted")
    seed(repo, linked(SPEC4, 4521))
    text, doc = plan_text_and_doc(capsys, repo)
    expected = model.apply_next_line(doc["plan"])
    assert doc["apply_offered"] is True and doc["next"] == expected == FOOTER.format(plan=doc["plan"])
    assert doc["counts"]["update"] == 1 and last_line(text) == expected and text.count("Next:") == 1
    # nothing else moved: the text above the footer is the golden's, with the hash and the posture word
    plan = doc["plan"]
    golden = GOLDEN_PLAN.read_text(encoding="utf-8").replace("plan 1d0617c03373", f"plan {plan}") \
        .replace("posture plan-only", "posture assisted").replace("1d0617c03373.json", f"{plan}.json")
    assert text == golden + expected + "\n"


def test_assisted_with_nothing_pending_offers_nothing_and_prints_no_footer(repo, az, capsys):
    set_config(repo, posture="assisted")
    az.answers["POST wit/workitemsbatch"] = synced_batch()
    seed(repo, linked(SPEC4, 4521, rev=8))
    text, doc = plan_text_and_doc(capsys, repo)
    assert doc["rows"] == [] and doc["apply_offered"] is True and doc["next"] is None
    assert "Next:" not in text and "nothing to push" in text


@pytest.mark.parametrize("posture,create,update,draft,offered,line", [
    ("assisted", 1, 0, None, True, True), ("assisted", 0, 1, 0, True, True), ("assisted", 0, 0, 2, True, True),
    ("assisted", 0, 0, 0, True, False), ("assisted", 0, 0, None, True, False),
    ("plan-only", 1, 1, 3, False, False)])
def test_the_footer_rule_is_posture_assisted_and_something_to_send(posture, create, update, draft, offered, line):
    plan = "0a1b2c3d4e5f"
    counts = {"create": create, "update": update}
    got = ado_sync._apply_offer(posture, counts, {"draft": draft}, plan)
    assert got == (offered, model.apply_next_line(plan) if line else None)


def test_comment_text_is_byte_identical_to_what_it_always_printed(repo, az, capsys):
    set_config(repo, posture="assisted")
    seed(repo, linked(SPEC4, 4521))
    code, text = run(capsys, "comment", SPEC4, "--message=hello", "--by", "@dev-one", "--repo", repo)
    assert code == 0
    code, doc = run_json(capsys, "comment", SPEC4, "--message=hello", "--by", "@dev-one", "--repo", repo)
    plan, path = doc["plan"], doc["path"]
    legacy_footer = f"Next: `ado_sync.py apply --confirm {plan} --by <you>` sends it, as whoever az is signed in as"
    assert last_line(text) == legacy_footer == model.apply_next_line(plan)
    head = text.splitlines()
    assert head[0] == f"comment plan {plan}  (posture assisted)" and head[-2] == f"Plan file: {path}"
    set_config(repo, posture="plan-only")
    code, text = run(capsys, "comment", SPEC4, "--message=hello", "--by", "@dev-one", "--repo", repo)
    assert "Next:" not in text and last_line(text).startswith("apply not offered in this clone")


def test_sync_text_ends_with_the_footer_when_an_apply_is_offered_and_its_json_carries_the_same_line(repo, az, capsys):
    set_config(repo, posture="assisted")
    seed(repo, linked(SPEC4, 4521))
    code, text = run(capsys, "sync", "--kind", "spec", "--id", "0004", "--repo", repo)
    code2, doc = run_json(capsys, "sync", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == code2 == 0
    expected = model.apply_next_line(doc["plan"]["plan"])
    assert doc["next"] == doc["plan"]["next"] == expected and last_line(text) == expected and text.count("Next:") == 1
    assert text.index("hook line: ") < text.index(expected)
    assert doc["counts"] == {"create": 0, "update": 1, "comments": 0, "drifted": 0}


def test_sync_prints_no_footer_on_a_plan_only_clone(repo, az, capsys):
    seed(repo, linked(SPEC4, 4521))
    code, text = run(capsys, "sync", "--kind", "spec", "--id", "0004", "--repo", repo)
    code2, doc = run_json(capsys, "sync", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert doc["next"] is None and doc["plan"]["next"] is None and "Next:" not in text
    assert last_line(text).startswith("hook line: ")


def test_the_text_form_is_the_golden_byte_for_byte(repo, az, capsys):
    seed(repo, linked(SPEC4, 4521))
    az.answers["boards query"] = tagged([4530, 4531])     # untagged items exist; the golden holds none of them
    code, text = run(capsys, "sync", "--kind", "spec", "--id", "0004", "--repo", repo)
    assert code == 0 and text == GOLDEN_SYNC.read_text(encoding="utf-8")
    assert az.count("boards", "query") == 0 and "#4530" not in text
    plan_golden = GOLDEN_PLAN.read_text(encoding="utf-8").rstrip("\n")
    assert plan_golden in text                      # the plan section is the plan's own text, verbatim
    assert not bc.EMAIL_RE.search(text) and not bc.GUID_RE.search(text)


# --- the command file -------------------------------------------------------------------------------------

def test_the_command_documents_sync_with_one_fenced_invocation_and_the_pinned_phrases():
    text = COMMAND_DOC.read_text(encoding="utf-8")
    calls = re.findall(r"scripts/ado_sync\.py sync\b[^\n]*", text)
    fenced = [c for c in calls if c.startswith("scripts/ado_sync.py sync --state .sdlc/state.yaml")]
    assert fenced == ["scripts/ado_sync.py sync --state .sdlc/state.yaml --sprint S07 --json"]
    assert "no hook, agent or timer" in text.lower() and "**sync — the catch-up**" in text
    assert "only when the user asks for it in this conversation" in text
    assert "reads the board and sends nothing" in text.lower()
