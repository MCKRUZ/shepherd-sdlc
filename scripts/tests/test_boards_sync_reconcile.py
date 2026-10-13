"""B4-P1a -- `ado_sync.py reconcile` and `pull --propose-specs`, and the one module that starts another script
(`ado_sync_reconcile.py`) (build kit sections 1 K9 and K10, 2 house rules 3, 4 and 9, 4 verb table, 5 card B4-P1a;
spec 0037; design section 8 and D10, D11, D32-D34).

What this pins, and why each line exists:
  * K10: every child the mirror starts is the list `[sys.executable, <scripts>/<script>.py, ...]` with the owning verb's
    OWN arguments -- `ready` and `defer` carry no `--by` (relaying one is argparse exit 2, read as "refused"), `risk`
    takes `[tier, --authorised-by, by]`, `assign` and `confirm-tier` end `--by`, `decide` is `--id --by --resolution`,
    `slate` and `unslate` are `--sprint --spec --by` (`unslate` adds the `--reason` the script requires). A test patches
    `subprocess.run` HERE ONLY and holds every argv as a LIST; no shell, no joined string;
  * `reconcile --take ado` is for a field the board owns that has an owning verb: `System.State` of a spec is exit 2 and
    spawns nothing; an in-flight spec's `AssignedTo` is `SDLC_OWNED_DRIFT`, reported with `spec_transition.py`'s own
    sentence (a test runs the real script and holds the sentence equal); a child's exit 1 is exit 1, never 2, and the
    row stays open (a `TAKE_*` without a recorded child exit 0 still counts as open);
  * `ack` needs an owner and `not-drift` a reason (exit 2), an AI `--by` is exit 2 with nothing spawned or written, and
    the machine's own words decide which take a class allows (`DELETED_IN_ADO` takes `ack`; `ORPHAN_IN_REPO` takes none);
  * the ledger keeps the verb and its arguments with every free-text value as `<text>`, a hash of that, and the child's
    exit -- never a comment's words, an address, a GUID or an absolute path;
  * `pull --propose-specs` writes ONE batch file under `.sdlc/ado/local/proposals/` of argv LISTS, never a shell string,
    and runs nothing; `pull` prints the plugin action of the design's section 8 table under each drift row;
  * the advisory first-seed note ignores an `applied` line that is not a create or an update (`link-pr` writes one) --
    that pin lives in `test_boards_sync_cli_b3.py`, beside the apply refusal it must agree with.

Nothing here spawns `az`: `boards_env` forbids it at the seam and the `az` fixture answers from the `wit/` fixtures. The
real-script tests start `spec_transition.py` on a temporary copy of the mini repository. The people are fictional.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import load_wit

import ast
import copy
import json
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

import ado_schema
import ado_sync
import ado_sync_model as model
import ado_sync_reconcile as rc
import boards_contract as bc

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
MINI = Path(__file__).resolve().parent / "fixtures" / "boards_repo"

NOW = datetime(2026, 10, 13, 9, 30, tzinfo=timezone.utc)
STAMP = "2026-10-13T09:30Z"
SPEC4, SPEC5 = "sdlc:spec:0004", "sdlc:spec:0005"
DECISION1 = "sdlc:decision:01"
SPEC4_FILE = "specs/0004-duplicate-claim-409.md"

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
BAD_NAMES = ["Claude", "claude-opus-4", "shepherd:feature-architect", "data-analyst"]


# --- helpers ---------------------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(ado_schema, "now_utc", lambda: NOW)


class Spawned:
    """A stand-in for `subprocess.run`, installed in THESE tests only: it records every call's argv as given and answers
    with the exit and text the test set."""

    def __init__(self):
        self.calls: list[dict] = []
        self.exit, self.stdout, self.stderr = 0, "done", ""

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": argv, "kwargs": kwargs})
        return subprocess.CompletedProcess(argv, self.exit, self.stdout, self.stderr)

    @property
    def argvs(self) -> list[list[str]]:
        return [c["argv"] for c in self.calls]


@pytest.fixture
def spawned(monkeypatch) -> Spawned:
    fake = Spawned()
    monkeypatch.setattr(subprocess, "run", fake)
    return fake


def run(capsys, *argv):
    code = ado_sync.main([str(a) for a in argv])
    return code, capsys.readouterr().out


def run_json(capsys, *argv):
    code, out = run(capsys, *argv, "--json")
    return code, json.loads(out)


@pytest.fixture
def repo(tmp_path, az, capsys) -> Path:
    """A copy of the mini repository with the starter config, the discovered schema and a roster that knows the
    fixtures' people; setup's own az calls are forgotten."""
    root = tmp_path / "repo"
    shutil.copytree(MINI, root)
    (root / ".sdlc" / "team.yaml").write_text(ROSTER, encoding="utf-8")
    assert ado_sync.main(["config", "init", "--repo", str(root)]) == 0
    assert ado_sync.main(["discover", "--repo", str(root)]) == 0
    set_config(root, fields={"spec": {"risk": {"field": "Custom.RiskTier",
                                               "values": {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}}}})
    capsys.readouterr()
    az.calls.clear()
    return root


def set_config(root: Path, **changes) -> None:
    path = root / bc.CONFIG_FILE
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg.update(changes)
    path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")


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


def linked(ref: str, wid: int, rev: int = 7, **extra) -> dict:
    return {"ts": "2026-10-12T08:00Z", "event": "linked", "ref": ref, "kind": ref.split(":")[1], "work_item": wid,
            "how": "linked", "rev_after": rev, "type": "User Story", "by": "@dev-one", **extra}


def drift_line(ref: str, field, cls: str, owner, wid: int, **extra) -> dict:
    return {"ts": "2026-10-12T10:00Z", "event": "drift_seen", "ref": ref, "kind": ref.split(":")[1], "work_item": wid,
            "field": field, "class": cls, "owner": owner, "rev": 3, "revised_at": "2026-10-12T09:00Z", **extra}


def observed() -> dict:
    return {"ts": "2026-10-12T11:00Z", "event": "observed", "ref": None, "items": 0}


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def set_spec_status(root: Path, ident: str, status: str) -> None:
    path = next((root / "specs").glob(f"{ident}-*.md"))
    text = path.read_text(encoding="utf-8")
    path.write_text(re.sub(r"(?m)^status: \S+", f"status: {status}", text, count=1), encoding="utf-8")


def pull_spec4(repo, capsys, rev: int = 1) -> dict:
    """Ledger spec 0004 as linked at an old revision and pull: the board moved State, IterationPath and AssignedTo."""
    seed(repo, linked(SPEC4, 4521, rev=rev))
    code, out = run_json(capsys, "pull", "--repo", repo)
    assert code == 0, out
    return out


def reconcile(capsys, repo, *argv, by="@dev-one"):
    return run(capsys, "reconcile", *argv, "--by", by, "--repo", repo)


def reconcile_json(capsys, repo, *argv, by="@dev-one"):
    return run_json(capsys, "reconcile", *argv, "--by", by, "--repo", repo)


def reconciled(root: Path) -> list[dict]:
    return [e for e in ledger(root) if e["event"] == "reconciled"]


def open_count(root: Path) -> int:
    return model.summarize(ledger(root), date(2026, 10, 13))["counts"]["open"]


def board_row(doc: dict, wid: int = 4521) -> dict:
    return next(r for r in doc["value"] if r and r["id"] == wid)


def item_row(wid: int, tags: str, title: str, type_name: str = "User Story", state: str = "Active", rev: int = 3,
             iteration: str | None = None) -> dict:
    """A board row shaped like the batch fixture's item 4521, as another item."""
    row = copy.deepcopy(board_row(load_wit("workitems_batch")))
    row["id"], row["rev"] = wid, rev
    row["fields"].update({"System.Id": wid, "System.Tags": tags, "System.WorkItemType": type_name,
                          "System.State": state, "System.Title": title})
    if iteration is not None:
        row["fields"]["System.IterationPath"] = iteration
    row.pop("relations", None)
    return row


def put_batch(az, *rows: dict) -> None:
    az.answers["POST wit/workitemsbatch"] = {"count": len(rows), "value": list(rows)}


def tagged(untagged: list[int]):
    def answer(args):
        wiql = args[args.index("--wiql") + 1]
        return [{"id": i} for i in untagged] if "sdlc-repo:" in wiql else []
    return answer


def assert_no_identity(text: str) -> None:
    assert not bc.GUID_RE.search(text), "a GUID"
    assert not bc.EMAIL_RE.search(text), "an e-mail address"


# --- K10: the child argv table ---------------------------------------------------------------------------

CHILD_CASES = {
    "ready": ({}, []),
    "defer": ({"reason": "not needed"}, ["--reason", "not needed"]),
    "risk": ({"tier": "HIGH", "by": "@dev-one"}, ["HIGH", "--authorised-by", "@dev-one"]),
    "confirm-tier": ({"by": "@dev-one"}, ["--by", "@dev-one"]),
    "assign": ({"developer": "@dev-two", "by": "@dev-one"}, ["--developer", "@dev-two", "--by", "@dev-one"]),
    "decide": ({"id": "DL-01", "by": "@dev-one", "resolution": "ship the card first"},
               ["--id", "DL-01", "--by", "@dev-one", "--resolution", "ship the card first"]),
    "slate": ({"sprint": "S08", "spec": "0004", "by": "@dev-one"},
              ["--sprint", "S08", "--spec", "0004", "--by", "@dev-one"]),
    "unslate": ({"sprint": "S07", "spec": "0004", "by": "@dev-one", "reason": "left the slate"},
                ["--sprint", "S07", "--spec", "0004", "--by", "@dev-one", "--reason", "left the slate"]),
}
SPEC_TRANSITION_VERBS = ("ready", "defer", "risk", "confirm-tier", "assign")


def test_the_child_table_has_exactly_the_k10_verbs():
    assert set(rc.CHILD_ARGV) == set(CHILD_CASES) == set(rc.SCRIPT_OF)


@pytest.mark.parametrize("verb", sorted(CHILD_CASES))
def test_each_verb_builds_its_k10_argv(verb):
    args, expected = CHILD_CASES[verb]
    assert rc.CHILD_ARGV[verb](**args) == expected


@pytest.mark.parametrize("verb", sorted(CHILD_CASES))
def test_every_child_is_a_list_led_by_the_interpreter_and_the_owning_script(verb):
    args, tail = CHILD_CASES[verb]
    argv = rc.child_command(verb, spec_path="/r/specs/0004-x.md", **args)
    script = str(SCRIPTS / rc.SCRIPT_OF[verb])
    assert isinstance(argv, list) and all(isinstance(a, str) for a in argv)
    if verb in SPEC_TRANSITION_VERBS:
        assert argv == [sys.executable, script, "--spec", "/r/specs/0004-x.md", verb, *tail]
        assert rc.SCRIPT_OF[verb] == "spec_transition.py"
    else:
        assert argv == [sys.executable, script, verb, *tail]
    assert Path(script).is_file()


def test_ready_and_defer_carry_no_by_and_no_other_flag_they_do_not_take():
    assert "--by" not in rc.CHILD_ARGV["ready"]() and rc.CHILD_ARGV["ready"]() == []
    assert "--by" not in rc.CHILD_ARGV["defer"](reason="x") and rc.CHILD_ARGV["defer"](reason="x") == ["--reason", "x"]
    for verb in ("ready", "defer"):
        argv = rc.child_command(verb, spec_path="/r/s.md", **CHILD_CASES[verb][0])
        assert "--by" not in argv and "--authorised-by" not in argv


def test_a_spec_transition_without_the_spec_path_is_refused_and_an_unknown_verb_too():
    with pytest.raises(ValueError):
        rc.child_command("assign", developer="@a", by="@b")
    with pytest.raises(ValueError):
        rc.child_command("handoff", spec_path="/r/s.md")


def test_free_text_that_starts_with_a_dash_stays_one_flag_equals_element():
    assert rc.CHILD_ARGV["defer"](reason="-not a flag") == ["--reason=-not a flag"]
    assert rc.CHILD_ARGV["decide"](id="DL-01", by="@a", resolution='--x "quoted" $(id)\nline')[-1] == \
        '--resolution=--x "quoted" $(id)\nline'
    assert rc.CHILD_ARGV["unslate"](sprint="S1", spec="0004", by="@a", reason="-r")[-1] == "--reason=-r"


def test_a_risk_tier_that_could_read_as_a_flag_is_refused():
    for bad in ("--authorised-by", "-HIGH", "HIGH LOW", "", "H1"):
        with pytest.raises(ValueError):
            rc.CHILD_ARGV["risk"](tier=bad, by="@a")


def test_the_displayed_argv_never_carries_a_free_text_value_or_an_absolute_path():
    shown = rc.display_argv("decide", id="DL-01", by="@dev-one", resolution="the board's words")
    assert shown == ["track_decisions.py", "decide", "--id", "DL-01", "--by", "@dev-one", "--resolution", rc.TEXT]
    shown = rc.display_argv("assign", spec_rel=SPEC4_FILE, developer="@dev-two", by="@dev-one")
    assert shown == ["spec_transition.py", "--spec", SPEC4_FILE, "assign", "--developer", "@dev-two", "--by", "@dev-one"]
    assert rc.display_argv("unslate", sprint="S07", spec="0004", by="@a", reason="why")[-2:] == ["--reason", rc.TEXT]
    assert len(rc.argv_sha(shown)) == 12 and bc.HASH_RE.fullmatch(rc.argv_sha(shown))


def test_run_child_starts_a_list_without_a_shell_and_hands_back_the_exit(spawned, tmp_path):
    spawned.exit, spawned.stdout, spawned.stderr = 1, "Refused: no\x1b[31m", "warn"
    argv = [sys.executable, str(SCRIPTS / "spec_transition.py"), "--spec", "x.md", "ready"]
    result = rc.run_child(argv, tmp_path)
    (call,) = spawned.calls
    assert call["argv"] is argv and isinstance(call["argv"], list)
    assert not call["kwargs"].get("shell") and call["kwargs"]["cwd"] == str(tmp_path)
    assert call["kwargs"]["capture_output"] is True and call["kwargs"]["timeout"] == rc.CHILD_TIMEOUT
    assert result == {"exit": 1, "stdout": "Refused: no", "stderr": "warn"}       # the escape sequence is gone


def test_run_child_never_invents_an_exit_for_a_child_that_did_not_run(monkeypatch, tmp_path):
    def timed_out(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 1)

    def missing(argv, **kwargs):
        raise FileNotFoundError("gone")
    monkeypatch.setattr(subprocess, "run", timed_out)
    assert rc.run_child(["x"], tmp_path)["exit"] is None
    monkeypatch.setattr(subprocess, "run", missing)
    result = rc.run_child(["x"], tmp_path)
    assert result["exit"] is None and "FileNotFoundError" in result["stderr"] and "gone" not in result["stderr"]


def test_run_child_really_runs_a_list_and_survives_an_argument_the_system_cannot_carry(tmp_path):
    done = rc.run_child([sys.executable, "-c", "import sys; print('hi'); print('err', file=sys.stderr); sys.exit(3)"],
                        tmp_path)
    assert done == {"exit": 3, "stdout": "hi", "stderr": "err"}
    result = rc.run_child([sys.executable, "-c", "pass", "a\x00b"], tmp_path)
    assert result["exit"] is None and "ValueError" in result["stderr"]


def test_the_assign_sentence_is_spec_transitions_own_and_reconcile_quotes_it(tmp_path):
    shutil.copytree(MINI, tmp_path / "r")
    root = tmp_path / "r"
    (root / ".sdlc" / "team.yaml").write_text(ROSTER, encoding="utf-8")
    spec = root / "specs" / "0005-claim-status-card.md"           # in-flight, developer @dev-two
    done = subprocess.run([sys.executable, str(SCRIPTS / "spec_transition.py"), "--spec", str(spec), "assign",
                           "--developer", "@dev-one", "--by", "@dev-one"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 1
    assert done.stdout.strip() == "Refused: " + rc.ASSIGN_HANDED_OFF.format(status="in-flight")


# --- static discipline (house rules 7 and 9, gates G7 and G8) ---------------------------------------------

def test_only_ado_transport_and_the_reconcile_module_import_subprocess():
    importers = sorted(p.name for p in SCRIPTS.glob("ado_*.py")
                       if re.search(r"^\s*(import|from)\s+subprocess\b", p.read_text(encoding="utf-8"), re.M))
    assert importers == ["ado_sync_reconcile.py", "ado_transport.py"]


def test_the_reconcile_module_has_no_shell_no_join_and_no_preview_revision():
    text = (SCRIPTS / "ado_sync_reconcile.py").read_text(encoding="utf-8")
    assert not re.search(r"shell\s*=\s*True|shlex\.join|\" \"\.join\((args|argv|cmd)", text)
    assert not re.search(r"-preview\.\d", text) and "shlex" not in text and "os.system" not in text
    tree = ast.parse(text)
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert "subprocess" in imported
    assert not imported & {"ado_transport", "ado_wit", "ado_sync"}       # it never reaches az, and never imports its caller
    assert not imported & {"sprint", "spec_transition", "handoff", "new_spec", "track_decisions"}   # it starts them


def test_ado_sync_may_import_the_reconcile_module_but_still_not_subprocess_or_the_protected_clis():
    tree = ast.parse((SCRIPTS / "ado_sync.py").read_text(encoding="utf-8"))
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert "ado_sync_reconcile" in names
    assert not names & {"subprocess", "sprint", "spec_transition", "handoff", "new_spec", "track_decisions"}


def test_reconcile_is_a_verb_with_the_kit_s_flags_and_pull_has_propose_specs():
    assert "reconcile" in ado_sync.VERBS and callable(ado_sync.VERBS["reconcile"])
    parser = ado_sync.build_parser()

    def node(*verb):
        found = parser
        for word in verb:
            found = next(a for a in found._actions if getattr(a, "choices", None)).choices[word]
        return found

    def flags(*verb):
        return {s for a in node(*verb)._actions for s in a.option_strings} - {"-h", "--help", "--state", "--repo", "--json"}
    assert flags("reconcile") == {"--field", "--take", "--by", "--owner", "--reason", "--from-comment"}
    assert {"--propose-specs"} <= flags("pull")
    take = next(a for a in node("reconcile")._actions if "--take" in a.option_strings)
    assert tuple(take.choices) == model.RECONCILE_TAKES == ("ado", "sdlc", "ack", "not-drift")


# --- the rows -------------------------------------------------------------------------------------------------

def test_drift_rows_open_count_is_what_the_summary_counts():
    rows = [
        observed(),
        linked(SPEC4, 4521), linked("sdlc:spec:0005", 4523), linked("sdlc:feature:03", 4410),
        drift_line(SPEC4, "System.State", "SDLC_OWNED_DRIFT", "S", 4521),
        drift_line(SPEC4, "System.AssignedTo", "ADO_OWNED_CHANGE", "A", 4521),
        drift_line(SPEC4, "System.IterationPath", "ADO_OWNED_CHANGE", "A", 4521),
        drift_line("sdlc:spec:0005", "System.State", "CONFLICT", "S", 4523),
        drift_line("sdlc:feature:03", None, "DELETED_IN_ADO", None, 4410),
        # settled honestly: an owner, a reason, a child exit of 0
        {"ts": "t", "event": "reconciled", "ref": SPEC4, "field": "System.AssignedTo", "disposition": "TAKE_ADO",
         "child_exit": 0},
        # mislabelled: still open
        {"ts": "t", "event": "reconciled", "ref": SPEC4, "field": "System.IterationPath",
         "disposition": "NOT_DRIFT"},
        {"ts": "t", "event": "reconciled", "ref": "sdlc:spec:0005", "field": "System.State", "disposition": "TAKE_SDLC",
         "child_exit": 1},
        {"ts": "t", "event": "reconciled", "ref": "sdlc:feature:03", "field": None, "disposition": "ACKNOWLEDGED",
         "owner": "@dev-one"},
    ]
    found = rc.drift_rows(rows)
    assert len(found) == 5
    assert sum(1 for r in found if r["open"]) == model.summarize(rows, date(2026, 10, 13))["counts"]["open"] == 3
    by = {(r["ref"], r["field"]): r["open"] for r in found}
    assert by[(SPEC4, "System.AssignedTo")] is False and by[("sdlc:feature:03", None)] is False
    assert by[(SPEC4, "System.IterationPath")] is True and by[("sdlc:spec:0005", "System.State")] is True


def test_an_apply_that_wrote_the_field_clears_the_row_as_the_summary_says():
    rows = [observed(), linked(SPEC4, 4521), drift_line(SPEC4, "System.State", "SDLC_OWNED_DRIFT", "S", 4521),
            {"ts": "t", "event": "applied", "ref": SPEC4, "action": "update", "work_item": 4521,
             "fields": ["System.State"]}]
    (row,) = rc.drift_rows(rows)
    assert row["open"] is False and model.summarize(rows, date(2026, 10, 13))["counts"]["open"] == 0


def test_a_row_that_is_not_recorded_or_already_settled_is_a_precondition():
    rows = rc.drift_rows([linked(SPEC4, 4521), drift_line(SPEC4, "System.State", "SDLC_OWNED_DRIFT", "S", 4521),
                          {"ts": "t", "event": "reconciled", "ref": SPEC4, "field": "System.State",
                           "disposition": "NOT_DRIFT", "reason": "known"}])
    with pytest.raises(rc.Precondition, match="already settled"):
        rc.pick_row(rows, SPEC4, "System.State")
    with pytest.raises(rc.Precondition, match="run `pull` first"):
        rc.pick_row(rows, SPEC4, "System.Title")


@pytest.mark.parametrize("cls", [c for c in bc.DRIFT_CLASSES if c not in model.NOT_DRIFT_CLASSES])
@pytest.mark.parametrize("take", model.RECONCILE_TAKES)
def test_a_take_is_the_machine_s_word_or_a_refusal_that_names_the_machine_s_words(cls, take):
    expected = model.disposition_for_take(cls, take)
    if expected is not None:
        assert rc.disposition_of(cls, take) == expected
        return
    with pytest.raises(rc.Rejected) as err:
        rc.disposition_of(cls, take)
    for word in model.dispositions_for(cls):
        assert word in str(err.value)


def test_ack_needs_an_owner_and_not_drift_a_reason():
    with pytest.raises(rc.Rejected, match="--owner"):
        rc.check_inputs("ack", None, "why")
    with pytest.raises(rc.Rejected, match="--reason"):
        rc.check_inputs("not-drift", "@dev-one", None)
    rc.check_inputs("ack", "@dev-one", None)
    rc.check_inputs("not-drift", None, "known")
    rc.check_inputs("ado", None, None)


def test_ado_route_follows_the_owner_of_the_field():
    assert rc.ado_route("spec", "System.AssignedTo", "A") == "assign"
    assert rc.ado_route("spec", "System.IterationPath", "A") == "iteration"
    assert rc.ado_route("decision", "System.State", "A") == "decide"
    for kind, field, owner, needle in [("spec", "System.State", "S", "handoff.py"),
                                       ("spec", "System.Title", "S", "repository owns"),
                                       ("requirement", "System.Title", "C", ".proposed"),
                                       ("spec", "relations:System.LinkTypes.Related", None, "report only"),
                                       ("finding", "System.State", "A", "no verb owns"),
                                       ("spec", "Microsoft.VSTS.Common.Priority", "A", "no verb owns"),
                                       ("spec", None, "A", "item itself")]:
        with pytest.raises(rc.Rejected, match=re.escape(needle)):
            rc.ado_route(kind, field, owner)


def test_take_sdlc_is_for_a_field_the_repository_owns():
    rc.check_sdlc("spec", "System.State", "S")
    for field, owner in [("System.AssignedTo", "A"), ("System.AreaPath", "C"), (None, None)]:
        with pytest.raises(rc.Rejected, match="never writes"):
            rc.check_sdlc("spec", field, owner)


# --- reconcile: refusals that spawn nothing and write nothing ---------------------------------------------------

def test_take_ado_on_a_specs_state_is_exit_2_and_spawns_and_writes_nothing(repo, az, spawned, capsys):
    pull_spec4(repo, capsys)
    before, calls = snapshot(repo), list(az.calls)
    code, out = reconcile(capsys, repo, SPEC4, "--field", "System.State", "--take", "ado")
    assert code == 2 and spawned.calls == [] and snapshot(repo) == before and az.calls == calls
    assert "handoff.py" in out and "System.State" in out
    code, doc = reconcile_json(capsys, repo, SPEC4, "--field", "System.State", "--take", "ado")
    assert code == 2 and doc["ok"] is False and doc["exit"] == 2


@pytest.mark.parametrize("name", BAD_NAMES)
def test_an_ai_by_is_exit_2_with_nothing_spawned_or_written(repo, az, spawned, capsys, name):
    pull_spec4(repo, capsys)
    before = snapshot(repo)
    code, out = reconcile(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "ado", by=name)
    assert code == 2 and spawned.calls == [] and snapshot(repo) == before
    assert reconcile(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "ack", "--owner", name)[0] == 2
    assert snapshot(repo) == before and spawned.calls == []


def test_a_blank_by_is_exit_1_not_a_refusal(repo, az, spawned, capsys):
    pull_spec4(repo, capsys)
    code, out = run(capsys, "reconcile", SPEC4, "--field", "System.AssignedTo", "--take", "ado", "--by", " ",
                    "--repo", repo)
    assert code == 1 and spawned.calls == []
    code, out = run(capsys, "reconcile", SPEC4, "--field", "System.AssignedTo", "--take", "ado", "--repo", repo)
    assert code == 1 and "--by is required" in out


def test_ack_without_an_owner_and_not_drift_without_a_reason_are_exit_2(repo, az, spawned, capsys):
    pull_spec4(repo, capsys)
    before = snapshot(repo)
    code, out = reconcile(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "ack")
    assert code == 2 and "--owner" in out
    code, out = reconcile(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "not-drift")
    assert code == 2 and "--reason" in out
    assert snapshot(repo) == before and spawned.calls == []


def test_a_missing_take_a_bad_ref_and_an_unrecorded_row_are_exit_1(repo, az, spawned, capsys):
    pull_spec4(repo, capsys)
    assert reconcile(capsys, repo, SPEC4, "--field", "System.State")[0] == 1                       # no --take
    assert reconcile(capsys, repo, "0004", "--field", "System.State", "--take", "ack", "--owner", "@dev-one")[0] == 1
    code, out = reconcile(capsys, repo, SPEC4, "--field", "System.Title", "--take", "ack", "--owner", "@dev-one")
    assert code == 1 and "run `pull` first" in out and "System.State" in out
    code, out = reconcile(capsys, repo, "sdlc:spec:0099", "--field", "System.State", "--take", "ack",
                          "--owner", "@dev-one")
    assert code == 1 and spawned.calls == []


def test_take_sdlc_on_a_field_the_board_owns_is_exit_2(repo, az, spawned, capsys):
    pull_spec4(repo, capsys)
    code, out = reconcile(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "sdlc")
    assert code == 2 and "never writes" in out and spawned.calls == []
    assert reconciled(repo) == []


def test_an_unreadable_ledger_stops_before_anything_is_spawned_exit_1(repo, az, spawned, capsys):
    pull_spec4(repo, capsys)
    with open(ledger_path(repo), "a", encoding="utf-8") as f:
        f.write("not json\n")
    code, out = reconcile(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "ado")
    assert code == 1 and "ledger" in out and spawned.calls == []


def test_a_ledger_that_cannot_be_appended_to_stops_before_the_child_starts(repo, az, spawned, capsys, monkeypatch):
    pull_spec4(repo, capsys)
    real = open

    def refuse(path, mode="r", *args, **kwargs):
        if str(path).endswith("ado-sync-log.jsonl") and "a" in mode:
            raise OSError("read-only file system")
        return real(path, mode, *args, **kwargs)
    monkeypatch.setattr("builtins.open", refuse)
    code, out = reconcile(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "ado")
    assert code == 1 and "DRIFT" in out and "nothing was started" in out and spawned.calls == []


def test_a_reason_that_holds_an_address_is_refused_before_anything_is_spawned(repo, az, spawned, capsys):
    pull_spec4(repo, capsys)
    hostile = "see kim.lee" + "@corp.example.com"
    code, out = reconcile(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "not-drift", "--reason", hostile)
    assert code == 1 and "ledger" in out and spawned.calls == [] and reconciled(repo) == []
    assert hostile not in "".join(json.dumps(e) for e in ledger(repo))


# --- reconcile --take ado: the owning verb, as a list -----------------------------------------------------------

def test_take_ado_on_a_ready_specs_assignee_spawns_assign_with_its_own_arguments(repo, az, spawned, capsys):
    pull_spec4(repo, capsys)
    spawned.stdout = "Assigned developer @dev-two."
    code, doc = reconcile_json(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "ado")
    assert code == 0 and doc["ok"] is True
    (call,) = spawned.calls
    spec = str(Path(repo).resolve() / SPEC4_FILE)
    assert call["argv"] == [sys.executable, str(SCRIPTS / "spec_transition.py"), "--spec", spec, "assign",
                            "--developer", "@dev-two", "--by", "@dev-one"]
    assert isinstance(call["argv"], list) and not call["kwargs"].get("shell")
    assert call["kwargs"]["cwd"] == str(Path(repo).resolve())
    (line,) = reconciled(repo)
    assert line["disposition"] == "TAKE_ADO" and line["child_exit"] == 0 and line["by"] == "@dev-one"
    assert line["ref"] == SPEC4 and line["field"] == "System.AssignedTo" and line["class"] == "ADO_OWNED_CHANGE"
    assert line["work_item"] == 4521 and line["kind"] == "spec"
    assert line["child_argv"] == ["spec_transition.py", "--spec", SPEC4_FILE, "assign", "--developer", "@dev-two",
                                  "--by", "@dev-one"]
    assert line["argv_sha"] == rc.argv_sha(line["child_argv"])
    assert doc["settled"] is True and doc["child"]["exit"] == 0 and "Assigned developer" in doc["child"]["stdout"]
    assert_no_identity(json.dumps(doc) + json.dumps(line))
    assert str(repo) not in json.dumps(line) and sys.executable not in json.dumps(line)


def test_take_ado_clears_the_row_only_because_the_child_exited_0(repo, az, spawned, capsys):
    pull_spec4(repo, capsys)
    before = open_count(repo)
    reconcile(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "ado")
    assert open_count(repo) == before - 1


@pytest.mark.parametrize("child_exit", [1, 2])
def test_a_child_that_fails_is_exit_1_never_2_and_the_row_stays_open(repo, az, spawned, capsys, child_exit):
    pull_spec4(repo, capsys)
    before = open_count(repo)
    spawned.exit, spawned.stdout, spawned.stderr = child_exit, "Refused: 'x' is not listed in the roster", "oops"
    code, out = reconcile(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "ado")
    assert code == 1 and "Refused: 'x' is not listed in the roster" in out and "exit " + str(child_exit) in out
    (line,) = reconciled(repo)
    assert line["disposition"] == "TAKE_ADO" and line["child_exit"] == child_exit
    assert open_count(repo) == before                                  # no recorded child exit 0: still open
    code, doc = reconcile_json(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "ado")
    assert code == 1 and doc["ok"] is False and doc["settled"] is False and doc["child"]["exit"] == child_exit
    assert doc["child"]["stderr"] == "oops"


def test_a_child_that_never_ran_is_exit_1_and_ledgers_no_made_up_exit(repo, az, monkeypatch, capsys):
    pull_spec4(repo, capsys)

    def missing(argv, **kwargs):
        raise FileNotFoundError("no interpreter")
    monkeypatch.setattr(subprocess, "run", missing)
    code, out = reconcile(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "ado")
    assert code == 1
    (line,) = reconciled(repo)
    assert line["child_exit"] is None and line["disposition"] == "TAKE_ADO"


def test_an_in_flight_specs_assignee_is_sdlc_owned_drift_reported_with_assigns_own_sentence(repo, az, spawned, capsys):
    set_spec_status(repo, "0004", "in-flight")
    out = pull_spec4(repo, capsys)
    (item,) = out["items"]
    assignee = next(f for f in item["fields"] if f["field"] == "System.AssignedTo")
    assert assignee["class"] == "SDLC_OWNED_DRIFT"
    proposal = next(p for p in out["proposals"] if p["field"] == "System.AssignedTo")
    assert proposal["action"] == "report" and proposal["text"] == rc.ASSIGN_HANDED_OFF.format(status="in-flight")
    code, text = reconcile(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "ado")
    assert code == 2 and rc.ASSIGN_HANDED_OFF.format(status="in-flight") in text
    assert spawned.calls == [] and reconciled(repo) == []


def test_an_assignee_who_is_not_on_the_roster_is_exit_1_and_asks_for_the_address_to_be_added(repo, az, spawned, capsys):
    pull_spec4(repo, capsys)
    (repo / ".sdlc" / "team.yaml").write_text(ROSTER.replace("person2@example.com", "somebody.else@example.com"),
                                              encoding="utf-8")
    code, out = reconcile(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "ado")
    assert code == 1 and "team.yaml" in out and spawned.calls == [] and reconciled(repo) == []


def test_take_ado_on_an_iteration_path_a_sprint_is_bound_to_spawns_slate(repo, az, spawned, capsys):
    set_config(repo, iterations={"S07": "Claims\\Sprint 6", "S08": "Claims\\Sprint 7"})
    pull_spec4(repo, capsys)
    code, doc = reconcile_json(capsys, repo, SPEC4, "--field", "System.IterationPath", "--take", "ado")
    assert code == 0, doc
    (call,) = spawned.calls
    assert call["argv"] == [sys.executable, str(SCRIPTS / "sprint.py"), "slate", "--sprint", "S08", "--spec", "0004",
                            "--by", "@dev-one"]
    assert call["kwargs"]["cwd"] == str(Path(repo).resolve())
    (line,) = reconciled(repo)
    assert line["child_argv"] == ["sprint.py", "slate", "--sprint", "S08", "--spec", "0004", "--by", "@dev-one"]
    assert line["disposition"] == "TAKE_ADO" and line["child_exit"] == 0


def test_an_iteration_path_no_sprint_is_bound_to_is_exit_1_and_names_iteration_bind(repo, az, spawned, capsys):
    set_config(repo, iterations={"S07": "Claims\\Sprint 6"})
    pull_spec4(repo, capsys)
    code, out = reconcile(capsys, repo, SPEC4, "--field", "System.IterationPath", "--take", "ado")
    assert code == 1 and "iteration bind" in out and spawned.calls == []


def test_a_board_move_out_of_every_sprint_is_an_unslate_that_needs_a_reason(repo, az, spawned, capsys):
    set_config(repo, iterations={"S07": "Claims\\Sprint 7"})
    batch = copy.deepcopy(load_wit("workitems_batch"))
    board_row(batch)["fields"]["System.IterationPath"] = "Claims"
    az.answers["POST wit/workitemsbatch"] = batch
    pull_spec4(repo, capsys)
    code, out = reconcile(capsys, repo, SPEC4, "--field", "System.IterationPath", "--take", "ado")
    assert code == 2 and "--reason" in out and spawned.calls == []
    code, doc = reconcile_json(capsys, repo, SPEC4, "--field", "System.IterationPath", "--take", "ado",
                               "--reason", "left the slate for good")
    assert code == 0, doc
    (call,) = spawned.calls
    assert call["argv"] == [sys.executable, str(SCRIPTS / "sprint.py"), "unslate", "--sprint", "S07", "--spec", "0004",
                            "--by", "@dev-one", "--reason", "left the slate for good"]
    (line,) = reconciled(repo)
    assert line["child_argv"][-2:] == ["--reason", rc.TEXT] and "left the slate" not in json.dumps(line["child_argv"])


def decision_repo(repo, az, *, state: str = "Closed") -> None:
    seed(repo, linked(DECISION1, 4600, rev=2, type="Issue"), observed(),
         drift_line(DECISION1, "System.State", "ADO_OWNED_CHANGE", "A", 4600))
    put_batch(az, item_row(4600, "sdlc:decision:01; sdlc-repo:claims-api", "DL-01 · Which channel ships first?",
                           type_name="Issue", state=state, rev=3))


def test_take_ado_on_a_closed_decision_spawns_decide_with_the_typed_resolution(repo, az, spawned, capsys):
    decision_repo(repo, az)
    code, doc = reconcile_json(capsys, repo, DECISION1, "--field", "System.State", "--take", "ado",
                               "--reason", "voice ships first")
    assert code == 0, doc
    (call,) = spawned.calls
    assert call["argv"] == [sys.executable, str(SCRIPTS / "track_decisions.py"), "decide", "--id", "DL-01", "--by",
                            "@dev-one", "--resolution", "voice ships first"]
    (line,) = reconciled(repo)
    assert line["child_argv"] == ["track_decisions.py", "decide", "--id", "DL-01", "--by", "@dev-one",
                                  "--resolution", rc.TEXT]
    assert "voice ships first" not in json.dumps(ledger(repo)[-1]["child_argv"])


def test_a_decision_is_never_closed_without_a_resolution_a_person_typed(repo, az, spawned, capsys):
    decision_repo(repo, az)
    code, out = reconcile(capsys, repo, DECISION1, "--field", "System.State", "--take", "ado")
    assert code == 2 and "never filled in" in out and spawned.calls == []


def test_a_decision_the_board_has_not_closed_is_exit_1(repo, az, spawned, capsys):
    decision_repo(repo, az, state="Active")
    code, out = reconcile(capsys, repo, DECISION1, "--field", "System.State", "--take", "ado", "--reason", "x")
    assert code == 1 and "not Completed" in out and spawned.calls == []


def cache_comment(repo, wid: int, **comment) -> None:
    import ado_discussion_cache as cache
    cache.save_cache(repo, {"work_item": wid, "work_item_id": wid, "as_of": STAMP,
                            "comments": [{"id": 7, "text": "Voice ships first, then chat.", "deleted": False,
                                          "flagged_lines": [], **comment}]})


def test_from_comment_takes_the_text_of_a_cached_comment_and_ledgers_only_its_id(repo, az, spawned, capsys):
    decision_repo(repo, az)
    cache_comment(repo, 4600)
    code, doc = reconcile_json(capsys, repo, DECISION1, "--field", "System.State", "--take", "ado",
                               "--from-comment", "7")
    assert code == 0, doc
    assert spawned.argvs[0][-2:] == ["--resolution", "Voice ships first, then chat."]
    line = reconciled(repo)[0]
    assert line["comment_id"] == 7 and "Voice ships first" not in json.dumps(line)
    assert "Voice ships first" not in json.dumps(doc)


@pytest.mark.parametrize("comment", [{"flagged_lines": [0]}, {"deleted": True}, {"text": "mail " + "a.b" + "@example.com"},
                                     {"text": "x" * 600}, {"text": "  "}])
def test_from_comment_refuses_a_comment_that_is_flagged_deleted_long_or_holds_an_address(repo, az, spawned, capsys,
                                                                                         comment):
    decision_repo(repo, az)
    cache_comment(repo, 4600, **comment)
    code, out = reconcile(capsys, repo, DECISION1, "--field", "System.State", "--take", "ado", "--from-comment", "7")
    assert code == 2 and spawned.calls == []


def test_from_comment_of_a_comment_that_is_not_cached_is_exit_2(repo, az, spawned, capsys):
    decision_repo(repo, az)
    code, out = reconcile(capsys, repo, DECISION1, "--field", "System.State", "--take", "ado", "--from-comment", "9")
    assert code == 2 and "discussion cache" in out and spawned.calls == []


def test_reconcile_runs_in_workflow_mode_from_the_state_file_too(repo, az, spawned, capsys):
    pull_spec4(repo, capsys)
    state = repo / ".sdlc" / "state.yaml"
    code, out = run(capsys, "reconcile", SPEC4, "--field", "System.AssignedTo", "--take", "ado", "--by", "@dev-one",
                    "--state", state)
    assert code == 0, out
    (call,) = spawned.calls
    assert call["argv"][2:4] == ["--spec", str(Path(repo).resolve() / SPEC4_FILE)]
    assert call["kwargs"]["cwd"] == str(Path(repo).resolve())
    assert reconciled(repo)[0]["disposition"] == "TAKE_ADO"
    code, out = run(capsys, "reconcile", SPEC4, "--take", "ack", "--owner", "@dev-one", "--by", "@dev-one",
                    "--state", repo / "nowhere" / "state.yaml")
    assert code == 1 and "state file not found" in out


# --- reconcile --take ack | not-drift | sdlc: no child -----------------------------------------------------------

def test_ack_with_an_owner_settles_the_row_and_spawns_nothing(repo, az, spawned, capsys):
    pull_spec4(repo, capsys)
    before = open_count(repo)
    code, doc = reconcile_json(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "ack",
                               "--owner", "@dev-two")
    assert code == 0 and spawned.calls == [] and doc["settled"] is True and doc["child"] is None
    (line,) = reconciled(repo)
    assert line["disposition"] == "ACKNOWLEDGED" and line["owner"] == "@dev-two" and "child_exit" not in line
    assert open_count(repo) == before - 1


def test_the_owner_is_ledgered_as_the_roster_handle_of_a_name_or_an_address(repo, az, spawned, capsys):
    pull_spec4(repo, capsys)
    reconcile(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "ack", "--owner", "Person 2")
    assert reconciled(repo)[0]["owner"] == "@dev-two"
    assert_no_identity(json.dumps(ledger(repo)))


def test_not_drift_with_a_reason_settles_the_row_and_ledgers_the_reason(repo, az, spawned, capsys):
    pull_spec4(repo, capsys)
    before = open_count(repo)
    code, doc = reconcile_json(capsys, repo, SPEC4, "--field", "System.IterationPath", "--take", "not-drift",
                               "--reason", "the team renamed the sprint")
    assert code == 0 and spawned.calls == []
    (line,) = reconciled(repo)
    assert line["disposition"] == "NOT_DRIFT" and line["reason"] == "the team renamed the sprint"
    assert open_count(repo) == before - 1


def test_take_sdlc_on_a_state_row_is_ledgered_but_stays_open_until_apply_lands_the_field(repo, az, spawned, capsys):
    pull_spec4(repo, capsys)
    before = open_count(repo)
    code, doc = reconcile_json(capsys, repo, SPEC4, "--field", "System.State", "--take", "sdlc")
    assert code == 0 and spawned.calls == []
    (line,) = reconciled(repo)
    assert line["disposition"] == "TAKE_SDLC" and "child_exit" not in line
    assert doc["settled"] is False and "apply" in doc["settled_why"] + " ".join(doc["notes"])
    assert open_count(repo) == before                       # honest: a TAKE_* with no recorded child exit 0 is open
    seed(repo, {"ts": "2026-10-13T10:00Z", "event": "applied", "ref": SPEC4, "action": "update", "work_item": 4521,
                "fields": ["System.State"]})
    assert open_count(repo) == before - 1


def test_a_row_that_was_settled_cannot_be_settled_twice(repo, az, spawned, capsys):
    pull_spec4(repo, capsys)
    args = (SPEC4, "--field", "System.AssignedTo", "--take", "ack", "--owner", "@dev-one")
    assert reconcile(capsys, repo, *args)[0] == 0
    code, out = reconcile(capsys, repo, *args)
    assert code == 1 and "already settled" in out and len(reconciled(repo)) == 1


# --- DELETED_IN_ADO and ORPHAN_IN_REPO ---------------------------------------------------------------------------

def pull_lost(repo, capsys):
    seed(repo, linked(SPEC4, 4999, rev=1), linked("sdlc:spec:0099", 4521, rev=7))
    code, out = run_json(capsys, "pull", "--repo", repo)
    assert code == 0
    return out


def test_a_deleted_item_takes_the_one_disposition_a_take_word_reaches(repo, az, spawned, capsys):
    out = pull_lost(repo, capsys)
    assert {i["ref"]: i["class"] for i in out["items"]} == {SPEC4: "DELETED_IN_ADO",
                                                            "sdlc:spec:0099": "ORPHAN_IN_REPO"}
    before = open_count(repo)
    for take in ("ado", "sdlc", "not-drift"):
        code, text = reconcile(capsys, repo, SPEC4, "--take", take, "--owner", "@dev-one", "--reason", "x")
        assert code == 2 and "DELETED_IN_ADO" in text and "RECREATE, UNLINK, ACKNOWLEDGED" in text
    assert reconciled(repo) == [] and open_count(repo) == before
    code, doc = reconcile_json(capsys, repo, SPEC4, "--take", "ack", "--owner", "@dev-two")
    assert code == 0 and doc["disposition"] == "ACKNOWLEDGED" and doc["field"] is None
    (line,) = reconciled(repo)
    assert line["ref"] == SPEC4 and line["field"] is None and line["class"] == "DELETED_IN_ADO"
    assert model.validate_disposition({"class": "DELETED_IN_ADO", **line})[0] is True
    assert open_count(repo) == before - 1 and spawned.calls == []


def test_a_deleted_item_with_a_field_named_that_it_does_not_have_is_exit_1(repo, az, spawned, capsys):
    pull_lost(repo, capsys)
    code, out = reconcile(capsys, repo, SPEC4, "--field", "System.State", "--take", "ack", "--owner", "@dev-one")
    assert code == 1 and "the item itself" in out


def test_an_orphan_takes_no_take_word_in_this_version_and_stays_open(repo, az, spawned, capsys):
    pull_lost(repo, capsys)
    before = open_count(repo)
    for take in model.RECONCILE_TAKES:
        code, text = reconcile(capsys, repo, "sdlc:spec:0099", "--take", take, "--owner", "@dev-one", "--reason", "x")
        assert code == 2 and "UNLINK" in text and "RELINK" in text
    assert reconciled(repo) == [] and open_count(repo) == before and spawned.calls == []


# --- what pull says about each drift row ------------------------------------------------------------------------

def test_pull_proposes_the_plugin_action_of_the_design_table_for_every_drift_row(repo, az, capsys):
    set_config(repo, iterations={"S07": "Claims\\Sprint 6", "S08": "Claims\\Sprint 7"})
    out = pull_spec4(repo, capsys)
    by = {p["field"]: p for p in out["proposals"]}
    assert by["System.AssignedTo"]["action"] == "reconcile"
    assert "assign --developer @dev-two" in by["System.AssignedTo"]["text"] and SPEC4 in by["System.AssignedTo"]["text"]
    assert by["System.IterationPath"]["action"] == "reconcile" and "slate --sprint S08" in by["System.IterationPath"]["text"]
    assert by["System.State"]["action"] == "report" and "handoff.py" in by["System.State"]["text"]
    assert all(p["class"] in bc.DRIFT_CLASSES and set(p) == {"ref", "kind", "field", "class", "action", "text"}
               for p in out["proposals"])
    assert_no_identity(json.dumps(out["proposals"]))


def test_pull_says_what_an_unbound_path_and_an_unknown_assignee_need_first(repo, az, capsys):
    set_config(repo, iterations={"S07": "Claims\\Sprint 6"})
    (repo / ".sdlc" / "team.yaml").write_text(ROSTER.replace("person2@example.com", "somebody.else@example.com"),
                                              encoding="utf-8")
    out = pull_spec4(repo, capsys)
    by = {p["field"]: p for p in out["proposals"]}
    assert by["System.IterationPath"]["action"] == "by-hand" and "iteration bind" in by["System.IterationPath"]["text"]
    assert by["System.AssignedTo"]["action"] == "by-hand" and "team.yaml" in by["System.AssignedTo"]["text"]


def test_pull_proposes_for_a_lost_row_and_prints_the_proposals_as_words(repo, az, capsys):
    out = pull_lost(repo, capsys)
    lost = {p["ref"]: p for p in out["proposals"]}
    assert lost[SPEC4]["field"] is None and "--take ack" in lost[SPEC4]["text"] and lost[SPEC4]["action"] == "reconcile"
    assert lost["sdlc:spec:0099"]["action"] == "report"
    code, text = run(capsys, "pull", "--repo", repo)
    assert code == 0 and "proposals:" in text and "--take ack" in text


def test_pull_proposals_change_no_az_call_and_no_ledger_line(repo, az, capsys):
    seed(repo, linked(SPEC4, 4521, rev=1))
    run_json(capsys, "pull", "--repo", repo)
    calls_with = len(az.calls)
    assert calls_with == 2 and az.count("devops", "invoke") == 2                 # one batch read, one updates read
    assert all("--detect" in c and c[c.index("--detect") + 1] == "false" for c in az.calls)


# --- pull --propose-specs ----------------------------------------------------------------------------------------

HOSTILE_TITLE = 'Fix "login"; $(rm -rf /) `id` -x'


def unmapped_board(az) -> None:
    az.answers["boards query"] = tagged([4530, 4531, 4532])
    put_batch(az,
              item_row(4530, "", "Reporting export for auditors"),
              item_row(4531, "", "0005 · claim status card", type_name="Bug"),
              item_row(4532, "", HOSTILE_TITLE))


def proposal_files(root: Path) -> list[Path]:
    folder = root / rc.PROPOSALS_DIR
    return sorted(p for p in folder.glob("*") if p.is_file()) if folder.is_dir() else []


def test_propose_specs_writes_one_batch_file_of_argv_lists_and_runs_nothing(repo, az, spawned, capsys):
    unmapped_board(az)
    local = repo / bc.LOCAL_DIR
    before = {p.relative_to(local).as_posix() for p in local.rglob("*") if p.is_file()}
    code, out = run_json(capsys, "pull", "--propose-specs", "--repo", repo)
    assert code == 0 and spawned.calls == []
    (path,) = proposal_files(repo)
    assert path.relative_to(repo).as_posix() == f"{rc.PROPOSALS_DIR}/specs-20261013T0930Z.json"
    assert out["propose_specs"] == {"path": path.relative_to(repo).as_posix(), "counts": {"new_spec": 2, "link": 1},
                                    "reason": None}
    after = {p.relative_to(local).as_posix() for p in local.rglob("*") if p.is_file()}
    assert after - before <= {"hook-status.txt", path.relative_to(local).as_posix()}
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["schema"] == 1 and doc["created"] == STAMP and doc["counts"] == {"new_spec": 2, "link": 1}
    by = {p["work_item"]: p for p in doc["proposals"]}
    assert by[4530]["action"] == "new_spec"
    assert by[4530]["new_spec"] == ["scripts/new_spec.py", "--name", "Reporting export for auditors", "--source",
                                    "ado:4530", "--owner", "@dev-two"]
    assert by[4530]["then"] == ["scripts/ado_sync.py", "link", "sdlc:spec:<NNNN>", "--work-item", "4530", "--by", "<you>"]
    assert by[4531]["action"] == "link" and by[4531]["new_spec"] is None
    assert by[4531]["then"] == ["scripts/ado_sync.py", "link", "sdlc:spec:0005", "--work-item", "4531", "--by", "<you>"]
    hostile = by[4532]["new_spec"]
    assert hostile[hostile.index("--name") + 1] == HOSTILE_TITLE            # one element, kept as data
    for p in doc["proposals"]:
        for key in ("new_spec", "then"):
            assert p[key] is None or (isinstance(p[key], list) and all(isinstance(a, str) for a in p[key]))
    assert_no_identity(path.read_text(encoding="utf-8"))
    assert all("--detect" in c and c[c.index("--detect") + 1] == "false" for c in az.calls)


def test_propose_specs_text_names_the_file_and_the_counts(repo, az, capsys):
    unmapped_board(az)
    code, text = run(capsys, "pull", "--propose-specs", "--repo", repo)
    assert code == 0 and "propose-specs" in text and "specs-20261013T0930Z.json" in text
    assert "2 new specs" in text and "1 link" in text


def test_the_batch_folder_is_the_ignored_local_one(repo, az, capsys):
    unmapped_board(az)
    run_json(capsys, "pull", "--propose-specs", "--repo", repo)
    assert (repo / bc.LOCAL_DIR / ".gitignore").read_text(encoding="utf-8") == "*\n"
    assert rc.PROPOSALS_DIR.startswith(bc.LOCAL_DIR + "/")


def test_propose_specs_with_nothing_untagged_writes_no_file_and_says_so(repo, az, capsys):
    az.answers["boards query"] = tagged([])
    code, out = run_json(capsys, "pull", "--propose-specs", "--repo", repo)
    assert code == 0 and proposal_files(repo) == []
    assert out["propose_specs"] == {"path": None, "counts": {"new_spec": 0, "link": 0}, "reason": None}
    code, text = run(capsys, "pull", "--propose-specs", "--repo", repo)
    assert "no untagged" in text


def test_propose_specs_with_no_path_to_search_under_says_not_searched_and_writes_nothing(repo, az, capsys):
    set_config(repo, area_path=None, iterations={})
    code, out = run_json(capsys, "pull", "--propose-specs", "--repo", repo)
    assert code == 0 and proposal_files(repo) == []
    assert out["propose_specs"]["path"] is None and "not searched" in out["propose_specs"]["reason"]


def test_propose_specs_when_the_search_fails_is_a_reason_not_a_failure(repo, az, capsys):
    az.fail["boards query"] = "ERROR: Could not resolve host dev.azure.com"
    code, out = run_json(capsys, "pull", "--propose-specs", "--repo", repo)
    assert code == 0 and proposal_files(repo) == [] and "not searched" in out["propose_specs"]["reason"]


def test_a_second_pull_in_the_same_minute_replaces_the_batch_it_does_not_add_one(repo, az, capsys):
    unmapped_board(az)
    run_json(capsys, "pull", "--propose-specs", "--repo", repo)
    run_json(capsys, "pull", "--propose-specs", "--repo", repo)
    assert len(proposal_files(repo)) == 1


def test_propose_specs_cannot_be_combined_with_the_discussion_pull(repo, az, capsys):
    code, out = run(capsys, "pull", "--propose-specs", "--discussion", "--repo", repo)
    assert code == 1 and "--propose-specs" in out and az.calls == [] and proposal_files(repo) == []


def test_a_pull_without_propose_specs_writes_no_batch_and_asks_no_extra_question(repo, az, capsys):
    seed(repo, linked(SPEC4, 4521, rev=7))
    run_json(capsys, "pull", "--repo", repo)
    assert proposal_files(repo) == [] and az.count("boards", "query") == 0
    code, out = run_json(capsys, "pull", "--repo", repo)
    assert "propose_specs" not in out or out["propose_specs"] is None


# --- the real child ------------------------------------------------------------------------------------------------

def test_take_ado_really_runs_assign_and_the_spec_and_the_summary_change(repo, az, capsys):
    pull_spec4(repo, capsys)
    before = open_count(repo)
    spec = repo / SPEC4_FILE
    assert 'developer: "@dev-one"' in spec.read_text(encoding="utf-8")
    code, doc = reconcile_json(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "ado")
    assert code == 0, doc
    assert 'developer: "@dev-two"' in spec.read_text(encoding="utf-8")
    assert doc["child"]["exit"] == 0 and "@dev-two" in doc["child"]["stdout"]
    assert open_count(repo) == before - 1


def test_a_real_refusal_by_the_owning_verb_is_exit_1_and_leaves_the_row_open(repo, az, capsys):
    pull_spec4(repo, capsys)
    spec = repo / SPEC4_FILE
    spec.write_text(re.sub(r'(?m)^checker: ""', 'checker: "@dev-two"', spec.read_text(encoding="utf-8")), encoding="utf-8")
    before, text = open_count(repo), spec.read_text(encoding="utf-8")
    code, out = reconcile(capsys, repo, SPEC4, "--field", "System.AssignedTo", "--take", "ado")
    assert code == 1 and "Refused" in out                       # the developer may not be the checker: spec_transition says so
    assert spec.read_text(encoding="utf-8") == text and open_count(repo) == before
    assert reconciled(repo)[0]["child_exit"] == 1


def test_a_real_decision_close_edits_the_log_through_track_decisions(repo, az, capsys):
    decision_repo(repo, az)
    code, doc = reconcile_json(capsys, repo, DECISION1, "--field", "System.State", "--take", "ado",
                               "--reason", "voice ships first")
    assert code == 0, doc
    log = (repo / ".sdlc" / "decision-log.md").read_text(encoding="utf-8")
    row = next(line for line in log.splitlines() if line.startswith("| DL-01"))
    assert "decided by @dev-one" in row and "voice ships first" in row and re.search(r"\|\s*decided\s*\|\s*$", row)
