"""B3-P2 -- `ado_sync_apply.apply_plan`: what happens when a named person sends a confirmed plan to the board.

What this pins, and why each line exists (build kit section 5 card B3-P2; spec 0036; design D16/D23/D41/D46 and
section 7; house rules 2, 3, 7, 9, 10, 11; guardrails 4, 5, 7):
  * the executing identity is read FIRST when a plan holds a comment to send: `connectionData` is az call 0, and an
    identity that is not `--by` (another person, a service principal, an account off the roster) refuses the WHOLE plan
    -- exit 2, `len(az.calls) == 1`, nothing written, not even the field ops;
  * every other whole-plan refusal costs no az call at all: an AI `--by`, posture `plan-only`, a forbidden (effort)
    field, a comment row refused while drafting, a first `--all` seed over `limits.first_seed` without a `--limit` in
    range; a plan whose rows do not hash to its id was edited and is a `ValueError`, not a refusal;
  * creates run outcome -> domain -> requirement -> epic -> feature -> spec whatever order the plan lists them in, the
    parent link rides in the child's own PATCH, and a child whose parent was not created is reported (`deferred`,
    `parent_failed`), never created without it;
  * an update is guarded by the revision the plan showed: a board that has moved on is skipped without a write, a PATCH
    the board rejects (`test /rev`) is a `conflict` row, and in both cases the next op runs; `permission`,
    `throttled` and an unknown outcome stop the run (every later row is deferred `stopped`), `rule` does not;
  * `--limit` and `limits.writes_per_run` count every write, comments included, and field ops go before comments;
  * a comment POST whose outcome is unknown is re-listed and matched by `text_sha` + author + the 10-minute window
    (`recovered: true`, never a second POST); a mismatch stops the run;
  * a ledger line is written after each write (`applied`, `commented`, `conflict`, `refused`); a failed append is
    `DRIFT` (class `drift`, run stopped, exit 1); a row done earlier under the same plan is skipped, so a repeat
    apply never doubles an item or a comment;
  * no file under `specs/` changes, nothing outside `.sdlc/` is written, and no e-mail address, GUID or `az` text
    reaches a ledger line or the result.

Nothing here spawns `az`: `boards_env` forbids it at the seam and `board` stands a `FakeBoardsAz(writes=True)` in for
`run_az`. The people in the fixtures are fictional; the one address is on example.com.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import HAND_WRITTEN_PROCESS
from tests.ado_boards_fixtures import FakeBoardsAz, is_identity_rest_read, load_wit, load_wit_error, route_key_boards, route_params
from tests.ado_boards_fixtures import body_file

import ast
import builtins
import copy
import itertools
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

import ado_discussion_cache as cache
import ado_schema
import ado_sync
import ado_sync_apply as apply_mod
import ado_sync_comments as comments
import ado_sync_model as model
import ado_transport
import boards_contract as bc
from ado_map import AdoImportError

# B0 (2026-10-14): these scenarios combine the item, history and write fixtures — hand-written for the hand-written
# Agile process, and not captured yet — with a process, so they read that same process even where a capture exists
# (tests/ado_boards_fixtures.py, `BOARDS_PROCESS`). The captured process is exercised in test_boards_captured_process.py.
BOARDS_PROCESS = HAND_WRITTEN_PROCESS

ROOT = Path(__file__).resolve().parents[2]
MINI = Path(__file__).resolve().parent / "fixtures" / "boards_repo"
NOW = datetime(2026, 10, 12, 9, 7, tzinfo=timezone.utc)   # two minutes after comment 504 of `comments_recent`
STAMP = "2026-10-12T09:07Z"
SPEC4, SPEC5 = "sdlc:spec:0004", "sdlc:spec:0005"
RISK_VALUES = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}
FRESH = "2026-10-12T09:00:00Z"

# The mini repo's roster with the sign-in address the `connection_data` fixture's person uses (person1).
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


# --- helpers ---------------------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(ado_schema, "now_utc", lambda: NOW)


def _body(args):
    # `--in-file <path>`, or since the B0 write fixes an update's `az rest --body @<path>`
    return json.loads(Path(body_file(args)).read_text(encoding="utf-8"))


def tagged_none(args):
    return []


def make_board(monkeypatch) -> FakeBoardsAz:
    """A fake that answers writes. `sent` records (route key, argv, request body) of every write that reached it, in
    order; creates answer ids 5001, 5002, ...; an update answers the item's id and the tested revision plus one."""
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
        return {"id": int(route_params(args)["id"]), "rev": rev + 1}

    def on_comment(args):
        record(args)
        return "comment_add_response"

    fake.answers.update({"POST wit/workItems": on_create, "PATCH wit/workItems": on_update,
                         "POST wit/comments": on_comment, "boards query": tagged_none})
    monkeypatch.setattr(ado_transport, "run_az", fake)
    return fake


@pytest.fixture
def board(monkeypatch) -> FakeBoardsAz:
    return make_board(monkeypatch)


def title_of(body) -> str:
    if not isinstance(body, list):
        return ""
    return str(next((op["value"] for op in body if op.get("path") == "/fields/System.Title"), ""))


def fail_with(board, key: str, text: str, when=None):
    """The write at `key` is rejected with `text` -- every one, or only those `when(argv, body)` picks out."""
    original = board.answers[key]

    def answer(args):
        body = _body(args)
        if when is not None and not when(args, body):
            return original(args)
        board.sent.append((route_key_boards(args), list(args), body))
        raise AdoImportError(text)
    board.answers[key] = answer


def on_item(wid: int):
    return lambda args, body: route_params(args).get("id") == str(wid)


def set_config(root: Path, **changes) -> None:
    path = root / bc.CONFIG_FILE
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key, value in changes.items():
        cfg[key] = value
    path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")


def build_repo(tmp_path: Path, **config) -> Path:
    """A copy of the mini repository with the starter config (posture assisted), the discovered schema and a roster
    that knows the fixtures' people. The caller forgets setup's own az calls."""
    root = tmp_path / "repo"
    shutil.copytree(MINI, root)
    (root / ".sdlc" / "team.yaml").write_text(ROSTER, encoding="utf-8")
    assert ado_sync.main(["config", "init", "--repo", str(root)]) == 0
    assert ado_sync.main(["discover", "--repo", str(root)]) == 0
    set_config(root, posture="assisted", fields={"spec": {"risk": {"field": "Custom.RiskTier", "values": RISK_VALUES}}},
               **config)
    return root


@pytest.fixture
def repo(tmp_path, board, capsys) -> Path:
    root = build_repo(tmp_path)
    capsys.readouterr()
    board.calls.clear()
    return root


def load_cfg(root: Path) -> dict:
    return yaml.safe_load((root / bc.CONFIG_FILE).read_text(encoding="utf-8"))


def load_schema(root: Path) -> dict:
    return json.loads((root / bc.SCHEMA_FILE).read_text(encoding="utf-8"))


def ledger(root: Path) -> list[dict]:
    path = root / bc.LEDGER
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def seed(root: Path, *events: dict) -> None:
    path = root / bc.LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def linked(ref: str, wid: int, rev: int = 7, **extra) -> dict:
    return {"ts": "2026-10-11T08:00Z", "event": "linked", "ref": ref, "kind": ref.split(":")[1], "work_item": wid,
            "how": "linked", "rev_after": rev, "type": "User Story", "by": "@dev-one", **extra}


def events_of(root: Path, name: str) -> list[dict]:
    return [e for e in ledger(root) if e["event"] == name]


def plan_doc(root: Path, capsys, *extra) -> dict:
    """The plan file `ado_sync.py plan` wrote: the document `apply_plan` is handed."""
    code = ado_sync.main(["plan", *extra, "--repo", str(root), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["ok"], out
    return json.loads((root / out["path"]).read_text(encoding="utf-8"))


def with_rows(doc: dict, rows: list[dict]) -> dict:
    return {**doc, "rows": rows, "plan": model.plan_hash(rows)}


def apply(root: Path, doc: dict, *, by: str = "@dev-one", limit=None, cfg=None, today=NOW) -> dict:
    return apply_mod.apply_plan(root, doc, by=by, cfg=load_cfg(root) if cfg is None else cfg, schema=load_schema(root),
                                limit=limit, today=today)


def put_batch(board, *rows: dict) -> None:
    board.answers["POST wit/workitemsbatch"] = {"count": len(rows), "value": list(rows)}


def board_row(wid: int = 4521) -> dict:
    return next(r for r in load_wit("workitems_batch")["value"] if r and r["id"] == wid)


def item_row(wid: int, tags: str, rev: int = 3) -> dict:
    row = copy.deepcopy(board_row())
    row["id"], row["rev"] = wid, rev
    row["fields"]["System.Id"] = wid
    row["fields"]["System.Tags"] = tags
    row.pop("relations", None)
    return row


@pytest.fixture
def two_updates(repo, board, capsys):
    """Specs 0004 and 0005 are linked to #4521 (rev 7) and #4522 (rev 3), both behind the repository: two update rows.
    The plan is made `--no-comments`: the mini repo's sprint log carries 0005 twice, so a default plan would also draft
    two `sprint_carried` comments, and these tests add the comment rows they need themselves."""
    seed(repo, linked(SPEC4, 4521, 7), linked(SPEC5, 4522, 3))
    put_batch(board, board_row(), item_row(4522, "risk:LOW; sdlc:spec:0005; sdlc:status:draft"))
    doc = plan_doc(repo, capsys, "--kind", "spec", "--id", "0004", "--id", "0005", "--no-comments")
    assert [r["action"] for r in doc["rows"]] == ["update", "update"]
    board.calls.clear()
    return doc


def adhoc(root: Path, message: str = "probe from sdlc", ref: str = SPEC4, wid: int = 4521, **kw) -> dict:
    row = comments.ad_hoc_row(ref, wid, message, by="@dev-one", mentions=[], cfg=load_cfg(root), **kw)
    assert row["status"] == "draft", row
    return row


def written(board) -> list[tuple]:
    return list(board.sent)


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def assert_no_identity(text: str) -> None:
    assert not bc.GUID_RE.search(text), "a GUID"
    assert not bc.EMAIL_RE.search(text), "an e-mail address"


def assert_clean_record(root: Path, result: dict) -> None:
    """Guardrail 4: nothing a ledger line or the result carries names a person."""
    assert_no_identity(json.dumps(result))
    for path in root.rglob("*.jsonl"):
        assert_no_identity(path.read_text(encoding="utf-8"))


def rev_of(body: list[dict]) -> int:
    return next(op["value"] for op in body if op["op"] == "test")


# --- creates: tree order, parents, failed parents ----------------------------------------------------------

def create_plan(root: Path, capsys) -> dict:
    doc = plan_doc(root, capsys, "--kind", "epic", "--kind", "feature", "--kind", "spec")
    assert [r["action"] for r in doc["rows"]] == ["create"] * 7
    return doc


def test_creates_run_in_tree_order_with_the_parent_in_the_childs_own_patch(repo, board, capsys):
    doc = create_plan(repo, capsys)
    doc = with_rows(doc, list(reversed(doc["rows"])))                     # the plan's own order is not trusted
    res = apply(repo, doc)
    assert (res["exit"], res["refused_reason"], res["failed"], res["deferred"]) == (0, None, [], [])
    assert set(res) == set(model.APPLY_RESULT_KEYS)
    creates = [a for a in res["applied"] if a["action"] == "create"]   # 0004 and 0005 also each have a move: an update
    assert [a["ref"].split(":")[1] for a in creates] == ["epic"] * 3 + ["feature"] + ["spec"] * 3
    ids = {a["ref"]: a["work_item"] for a in creates}
    posts = [s for s in written(board) if s[0] == "POST wit/workItems"]
    # bare type names: the extension's template is `{project}/_apis/wit/workItems/${type}`, so a leading `$` reached
    # the board as `$$Epic` and 404ed (B0 capture, 2026-10-14)
    assert [route_params(argv)["type"] for _, argv, _ in posts] == ["Epic"] * 3 + ["Feature"] + ["User Story"] * 3

    def parent(ref):
        body = posts[[a["ref"] for a in creates].index(ref)][2]
        links = [op["value"] for op in body if op["path"] == "/relations/-" and op["value"]["rel"] == model.PARENT_REL]
        return [int(link["url"].rsplit("/", 1)[1]) for link in links]
    assert parent("sdlc:feature:03") == [ids["sdlc:epic:001"]]
    assert parent(SPEC4) == parent(SPEC5) == [ids["sdlc:feature:03"]]
    assert parent("sdlc:spec:0007") == [] and parent("sdlc:epic:001") == []
    for _, _, body in posts:                                              # a create has nothing to test and says where it came from
        assert not any(op["op"] == "test" for op in body)
        assert any(op["path"] == "/relations/-" and op["value"]["rel"] == "Hyperlink" for op in body)
        (history,) = [op["value"] for op in body if op["path"] == "/fields/System.History"]
        assert history.startswith(f"{bc.HISTORY_TOKEN} · created · by @dev-one · executed as unknown · plan {doc['plan']} · ")


def test_a_create_links_its_source_file_at_the_head_commit_when_the_repository_has_one(repo, board, capsys):
    git = repo / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "refs" / "heads" / "main").write_text("a1b2c3d4e5f60718293a4b5c6d7e8f9012345678\n", encoding="utf-8")
    doc = plan_doc(repo, capsys, "--kind", "spec", "--id", "0007")
    assert apply(repo, doc)["exit"] == 0
    (body,) = [b for k, _, b in written(board) if k == "POST wit/workItems"]
    (link,) = [op["value"]["url"] for op in body if op["path"] == "/relations/-" and op["value"]["rel"] == "Hyperlink"]
    assert link == ("https://dev.azure.com/contoso/Claims/_git/claims-api?version=GCa1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
                    "&path=/specs/0007-reporting-export.md")


def test_a_child_of_a_failed_parent_is_reported_not_created(repo, board, capsys):
    doc = create_plan(repo, capsys)
    fail_with(board, "POST wit/workItems", load_wit_error("rule_violation"), lambda a, b: "EP-001" in title_of(b))
    res = apply(repo, doc)
    assert res["exit"] == 1 and res["refused_reason"] is None
    assert [(f["ref"], f["action"], f["work_item"], f["class"]) for f in res["failed"]] == \
        [("sdlc:epic:001", "create", None, "rule")]                      # a rule failure does not stop the run (D16)
    assert {d["ref"]: d["why"] for d in res["deferred"]} == {"sdlc:feature:03": "parent_failed", SPEC4: "parent_failed",
                                                              SPEC5: "parent_failed"}
    assert {a["ref"] for a in res["applied"]} == {"sdlc:epic:002", "sdlc:epic:003", "sdlc:spec:0007"}
    assert not any(title_of(b).startswith(("FE-03", "0004", "0005")) for _, _, b in written(board))   # never sent
    assert "sdlc:epic:001" not in [e["ref"] for e in events_of(repo, "applied")]


def test_every_create_is_one_ledger_line_the_status_verb_can_count(repo, board, capsys):
    doc = create_plan(repo, capsys)
    res = apply(repo, doc)
    lines = events_of(repo, "applied")
    assert [(e["ref"], e["work_item"]) for e in lines] == [(a["ref"], a["work_item"]) for a in res["applied"]]
    first = lines[0]
    assert (first["action"], first["kind"], first["rev_after"], first["by"], first["executed_as"], first["plan"]) == \
        ("create", "epic", 1, "@dev-one", "unknown", doc["plan"])
    assert first["projection_hash"] == next(r["projection_hash"] for r in doc["rows"] if r["ref"] == first["ref"])
    assert re.fullmatch(r"[0-9a-f]{12}", first["argv_sha"]) and first["type"] == "Epic" and "System.Title" in first["fields"]
    assert ado_sync.linked_items(ledger(repo))["sdlc:epic:001"]["work_item"] == lines[0]["work_item"]
    assert ado_sync.main(["status", "--repo", str(repo), "--json"]) == 0
    assert_clean_record(repo, res)


# --- updates: the guard, conflicts, stops ------------------------------------------------------------------

def test_an_update_tests_the_revision_the_plan_showed_and_ledgers_both_revisions(repo, board, two_updates):
    res = apply(repo, two_updates)
    assert (res["exit"], [a["work_item"] for a in res["applied"]], [a["rev_after"] for a in res["applied"]]) == \
        (0, [4521, 4522], [8, 4])
    patches = [(argv, body) for key, argv, body in written(board) if key == "PATCH wit/workItems"]
    assert [rev_of(body) for _, body in patches] == [7, 3] and all(body[0]["op"] == "test" for _, body in patches)
    assert [route_params(argv)["id"] for argv, _ in patches] == ["4521", "4522"]
    paths = {op["path"] for op in patches[0][1][1:]}
    assert paths == {"/fields/System.State", "/fields/System.Tags", "/fields/Custom.RiskTier"}
    line = events_of(repo, "applied")[0]
    assert (line["action"], line["rev_before"], line["rev_after"], line["plan"]) == ("update", 7, 8, two_updates["plan"])
    assert sorted(line["fields"]) == ["Custom.RiskTier", "System.State", "System.Tags"]
    # B0 write fixes (2026-10-15): az call 0 is the sign-in check of the update transport, then the one batch read, then
    # each PATCH as `az rest` (`devops invoke` binds `…/workItems/${type}` for a PATCH and dies)
    assert is_identity_rest_read(board.calls[0]) and route_key_boards(board.calls[1]) == "POST wit/workitemsbatch"
    assert board.count("devops", "invoke") == 1 and board.count("rest", "--method", "patch") == 2


def test_a_row_the_board_moved_since_the_plan_is_skipped_without_a_write_and_the_next_runs(repo, board, two_updates):
    moved = board_row()
    moved["rev"] = 9
    put_batch(board, moved, item_row(4522, "risk:LOW; sdlc:spec:0005; sdlc:status:draft"))
    res = apply(repo, two_updates)
    assert res["exit"] == 1
    assert [(f["ref"], f["class"]) for f in res["failed"]] == [(SPEC4, "conflict")]
    assert [a["work_item"] for a in res["applied"]] == [4522]
    assert [route_params(argv)["id"] for key, argv, _ in written(board) if key == "PATCH wit/workItems"] == ["4522"]
    (line,) = events_of(repo, "conflict")
    assert (line["ref"], line["work_item"], line["rev_before"], line["plan"]) == (SPEC4, 4521, 7, two_updates["plan"])


def test_a_patch_the_board_rejects_for_a_stale_rev_is_a_conflict_and_the_next_op_runs(repo, board, two_updates):
    fail_with(board, "PATCH wit/workItems", load_wit_error("stale_rev"), on_item(4521))
    res = apply(repo, two_updates)
    assert res["exit"] == 1 and res["deferred"] == []
    assert [(f["ref"], f["work_item"], f["class"]) for f in res["failed"]] == [(SPEC4, 4521, "conflict")]
    assert [a["ref"] for a in res["applied"]] == [SPEC5]
    assert [e["ref"] for e in events_of(repo, "conflict")] == [SPEC4]
    assert_clean_record(repo, res)                                        # the board's words never ride a result


@pytest.mark.parametrize("error", ["permission", "throttled", "unknown"])
def test_permission_throttled_and_an_unknown_outcome_stop_the_run(repo, board, two_updates, error):
    text = "`az devops invoke` timed out after 60s." if error == "unknown" else load_wit_error(error)
    fail_with(board, "PATCH wit/workItems", text)
    res = apply(repo, two_updates)
    assert res["exit"] == 1 and res["applied"] == []
    assert [(f["ref"], f["class"]) for f in res["failed"]] == [(SPEC4, error)]
    assert res["deferred"] == [{"ref": SPEC5, "action": "update", "why": "stopped"}]
    assert len([k for k, _, _ in written(board) if k == "PATCH wit/workItems"]) == 1


def test_a_rule_failure_is_reported_and_the_run_goes_on(repo, board, two_updates):
    fail_with(board, "PATCH wit/workItems", load_wit_error("rule_violation"), on_item(4521))
    res = apply(repo, two_updates)
    assert [(f["ref"], f["class"]) for f in res["failed"]] == [(SPEC4, "rule")] and [a["ref"] for a in res["applied"]] == [SPEC5]


def test_a_repository_that_changed_since_the_plan_is_a_conflict_not_a_different_write(repo, board, two_updates):
    spec = repo / "specs" / "0004-duplicate-claim-409.md"
    spec.write_text(spec.read_text(encoding="utf-8").replace("status: ready", "status: draft"), encoding="utf-8")
    res = apply(repo, two_updates)
    assert [(f["ref"], f["class"]) for f in res["failed"]] == [(SPEC4, "conflict")] and [a["ref"] for a in res["applied"]] == [SPEC5]


def test_an_update_for_an_item_the_board_no_longer_has_is_reported_not_found_and_sends_nothing(repo, board, two_updates):
    put_batch(board, board_row())                                          # #4522 has gone
    res = apply(repo, two_updates)
    assert [(f["ref"], f["work_item"], f["class"]) for f in res["failed"]] == [(SPEC5, 4522, "not_found")]
    assert [a["ref"] for a in res["applied"]] == [SPEC4] and res["exit"] == 1


def test_a_plain_date_for_today_reads_the_clock_the_other_verbs_read(repo, board, capsys):
    doc = plan_doc(repo, capsys, "--kind", "spec", "--id", "0007")
    assert apply(repo, doc, today=NOW.date())["exit"] == 0
    assert events_of(repo, "applied")[0]["ts"] == STAMP


# --- limits ------------------------------------------------------------------------------------------------

def test_limit_counts_writes_and_defers_the_rest(repo, board, capsys):
    doc = create_plan(repo, capsys)
    res = apply(repo, doc, limit=2)
    assert res["exit"] == 0 and len(res["applied"]) == 2 and len(written(board)) == 2
    assert {d["why"] for d in res["deferred"]} == {"limit"} and len(res["deferred"]) == 5


def test_writes_per_run_caps_the_run_and_the_smaller_of_the_two_names_the_reason(repo, board, capsys):
    doc = create_plan(repo, capsys)
    cfg = {**load_cfg(repo), "limits": {"writes_per_run": 3, "first_seed": 20}}
    res = apply(repo, doc, cfg=cfg)
    assert len(res["applied"]) == 3 and {d["why"] for d in res["deferred"]} == {"writes_per_run"}
    board.sent.clear()
    again = apply(repo, doc, cfg=cfg, limit=1)                            # the three done are skipped; limit 1 binds
    assert len(again["applied"]) == 1 and {d["why"] for d in again["deferred"]} == {"limit"}


def test_comments_count_toward_the_limit_and_field_ops_go_first(repo, board, two_updates):
    seed(repo, linked("sdlc:spec:0007", 4530))
    rows = [adhoc(repo, "first fact"), adhoc(repo, "second fact", ref="sdlc:spec:0007", wid=4530), *two_updates["rows"]]
    res = apply(repo, with_rows(two_updates, rows), limit=3)
    assert [a["action"] for a in res["applied"]] == ["update", "update", "comment"]   # comments come after every field op
    assert res["deferred"] == [{"ref": "sdlc:spec:0007", "action": "comment", "why": "limit"}]
    assert [k for k, _, _ in written(board)] == ["PATCH wit/workItems", "PATCH wit/workItems", "POST wit/comments"]


def test_the_first_all_seed_over_first_seed_needs_a_limit_in_range(repo, board, capsys):
    doc = plan_doc(repo, capsys, "--all")
    creates = sum(1 for r in doc["rows"] if r["action"] == "create")
    assert doc["scope"]["all"] and creates > 5
    cfg = {**load_cfg(repo), "limits": {"writes_per_run": 50, "first_seed": 5}}
    board.calls.clear()
    for limit in (None, 6):
        res = apply(repo, doc, cfg=cfg, limit=limit)
        assert (res["exit"], res["refused_reason"], res["applied"], res["failed"]) == (2, "first_seed", [], [])
    assert board.calls == []
    assert [e["reason"] for e in events_of(repo, "refused")] == ["first_seed", "first_seed"]
    ok = apply(repo, doc, cfg=cfg, limit=5)
    assert (ok["exit"], len(ok["applied"])) == (0, 5)
    later = apply(repo, doc, cfg=cfg)                                      # something has been applied: no longer a first seed
    assert later["refused_reason"] is None and later["exit"] == 0


def test_a_clone_that_only_linked_a_pr_is_still_on_its_first_seed(repo, board, capsys):
    seed(repo, linked(SPEC4, 4521, 7))
    board.answers["repos pr work-item add"] = []
    assert ado_sync.main(["link-pr", "--spec", "0004", "--pr", "12", "--by", "@dev-one", "--repo", str(repo)]) == 0
    capsys.readouterr()
    assert [(e["action"], e["ref"]) for e in events_of(repo, "applied")] == [("link_pr", SPEC4)]  # created nothing
    doc = plan_doc(repo, capsys, "--all")
    assert doc["scope"]["all"] and sum(1 for r in doc["rows"] if r["action"] == "create") > 5
    cfg = {**load_cfg(repo), "limits": {"writes_per_run": 50, "first_seed": 5}}
    board.calls.clear()
    res = apply(repo, doc, cfg=cfg)
    assert (res["exit"], res["refused_reason"], res["applied"], res["failed"]) == (2, "first_seed", [], [])
    assert board.calls == []


# --- refusals that cost no az call -------------------------------------------------------------------------

def test_an_ai_or_agent_by_is_refused_with_zero_spawns(repo, board, two_updates):
    doc = with_rows(two_updates, [*two_updates["rows"], adhoc(repo)])      # even with a comment to send: no identity read
    for name in ("Claude", "shepherd:feature-architect", "feature-architect", "claude-opus"):
        res = apply(repo, doc, by=name)
        assert (res["exit"], res["refused_reason"], res["applied"]) == (2, "ai_actor", [])
    assert board.calls == []
    assert all("by" not in e for e in events_of(repo, "refused"))         # the refusal does not record the AI's string


def test_posture_plan_only_is_refused_with_zero_spawns(repo, board, two_updates):
    for cfg in ({**load_cfg(repo), "posture": "plan-only"}, {**load_cfg(repo), "posture": None}, {}):
        res = apply(repo, two_updates, cfg=cfg)
        assert (res["exit"], res["refused_reason"]) == (2, "posture")
    assert board.calls == [] and written(board) == []


def test_a_forbidden_field_in_the_plan_refuses_the_whole_plan(repo, board, two_updates):
    effort = {"op": "replace", "path": "/fields/Microsoft.VSTS.Scheduling.StoryPoints", "old": 3, "new": 5}
    rows = copy.deepcopy(two_updates["rows"])
    rows[1]["ops"].append(effort)
    res = apply(repo, with_rows(two_updates, rows))
    assert (res["exit"], res["refused_reason"], res["applied"]) == (2, "forbidden_field", [])
    rows = copy.deepcopy(two_updates["rows"])
    rows[1]["ops"].append({"op": "add", "path": "/fields/Custom.Velocity", "old": None, "new": 9})
    assert apply(repo, with_rows(two_updates, rows))["refused_reason"] == "forbidden_field"
    rows = copy.deepcopy(two_updates["rows"])
    rows[0].update(action="refused", reason="effort fields are never written", ops=[])
    assert apply(repo, with_rows(two_updates, rows))["refused_reason"] == "forbidden_field"
    assert board.calls == []


def test_a_comment_row_refused_while_drafting_refuses_the_whole_plan(repo, board, two_updates):
    seed(repo, *[{"ts": STAMP, "event": "commented", "ref": SPEC4, "work_item": 4521, "idem_key": f"comment:{SPEC4}:{i:012x}"}
                 for i in range(50)])
    refused = comments.ad_hoc_row(SPEC4, 4521, "one too many", by="@dev-one", mentions=[], cfg=load_cfg(repo),
                                  ledger=ledger(repo))
    assert (refused["status"], refused["reason"]) == ("refused", "budget")
    res = apply(repo, with_rows(two_updates, [*two_updates["rows"], refused]))
    assert (res["exit"], res["refused_reason"], res["applied"]) == (2, "budget", [])
    assert board.calls == []                                               # not even the connectionData read: refused first


def test_a_plan_that_no_longer_hashes_to_its_id_is_an_error_not_a_send(repo, board, two_updates):
    edited = {**two_updates, "rows": two_updates["rows"][:1]}
    with pytest.raises(ValueError, match="hash"):
        apply(repo, edited)
    with pytest.raises(ValueError):
        apply(repo, {**two_updates, "plan": "not-a-hash"})
    for bad in ("", "  ", "kim@example.com", "00000000-0000-0000-0000-000000000002"):
        with pytest.raises(ValueError):
            apply(repo, two_updates, by=bad)
    with pytest.raises(ValueError):
        apply(repo, two_updates, limit=0)
    assert board.calls == []


@pytest.mark.parametrize("change", [
    {"projection_hash": None}, {"ref": "spec 0004"}, {"type": ""}, {"rev": None}, {"work_item": 0},
])
def test_a_malformed_row_is_an_error_before_anything_is_sent(repo, board, two_updates, change):
    rows = copy.deepcopy(two_updates["rows"])
    rows[0].update(change)
    with pytest.raises(ValueError):
        apply(repo, with_rows(two_updates, rows))
    assert board.calls == []


def test_a_malformed_comment_row_is_an_error_before_anything_is_sent(repo, board):
    row = adhoc(repo)
    for change in ({"text_sha": "0" * 12}, {"status": "maybe"}, {"trailer": "loud"}, {"work_item": None}, {"text": ""}):
        with pytest.raises(ValueError):
            apply(repo, with_rows({"schema": 1, "scope": {}}, [{**row, **change}]))
    assert board.calls == []


def test_a_ledger_line_that_is_not_a_ledger_line_stops_the_apply_before_it_sends(repo, board, two_updates):
    (repo / bc.LEDGER).parent.mkdir(parents=True, exist_ok=True)
    with open(repo / bc.LEDGER, "a", encoding="utf-8") as f:
        f.write("this is not json\n")
    with pytest.raises(ValueError, match="ledger"):
        apply(repo, two_updates)
    assert board.calls == []


def test_a_parent_is_always_moved_in_front_of_its_child():
    spec = {"ref": "sdlc:spec:0001", "kind": "spec", "action": "create", "parent": None}
    epic = {"ref": "sdlc:epic:001", "kind": "epic", "action": "create",
            "parent": {"ref": "sdlc:spec:0001", "state": "in this plan"}}      # a contrived edge against the kind order
    outcome = {"ref": "sdlc:outcome:one", "kind": "outcome", "action": "update"}
    assert [r["ref"] for r in apply_mod._in_tree_order([epic, spec, outcome])] == \
        ["sdlc:outcome:one", "sdlc:spec:0001", "sdlc:epic:001"]
    cycle = [{**epic, "parent": {"ref": "sdlc:spec:0001", "state": "in this plan"}},
             {**spec, "parent": {"ref": "sdlc:epic:001", "state": "in this plan"}}]
    assert len(apply_mod._in_tree_order(cycle)) == 2                           # a cycle in a plan file cannot hang the run


@pytest.mark.parametrize("layout", ["packed", "detached", "worktree", "garbage", "none"])
def test_the_head_commit_is_read_from_the_git_files_without_spawning_anything(tmp_path, layout):
    sha = "0123456789abcdef0123456789abcdef01234567"
    root = tmp_path / "checkout"
    root.mkdir()
    git = root / ".git"
    if layout == "packed":
        git.mkdir()
        (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (git / "packed-refs").write_text(f"# pack-refs\n{'f' * 40} refs/heads/other\n{sha} refs/heads/main\n", encoding="utf-8")
    elif layout == "detached":
        git.mkdir()
        (git / "HEAD").write_text(sha + "\n", encoding="utf-8")
    elif layout == "worktree":
        common, own = tmp_path / "common.git", tmp_path / "common.git" / "worktrees" / "w"
        (common / "refs" / "heads").mkdir(parents=True)
        own.mkdir(parents=True)
        (common / "refs" / "heads" / "feature").write_text(sha + "\n", encoding="utf-8")
        (own / "HEAD").write_text("ref: refs/heads/feature\n", encoding="utf-8")
        (own / "commondir").write_text("../..\n", encoding="utf-8")
        git.write_text(f"gitdir: {own}\n", encoding="utf-8")
    elif layout == "garbage":
        git.mkdir()
        (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (git / "refs" / "heads").mkdir(parents=True)
        (git / "refs" / "heads" / "main").write_text("not a sha\n", encoding="utf-8")
    assert apply_mod._head_commit(root) == (sha if layout in ("packed", "detached", "worktree") else None)


# --- identity first ----------------------------------------------------------------------------------------

def test_connection_data_is_call_zero_whenever_a_comment_row_exists_and_field_ops_go_first(repo, board, two_updates):
    rows = [adhoc(repo), *two_updates["rows"]]
    res = apply(repo, with_rows(two_updates, rows))
    assert res["exit"] == 0 and [a["action"] for a in res["applied"]] == ["update", "update", "comment"]
    assert route_key_boards(board.calls[0]) == "GET core/connectionData"
    assert [route_key_boards(c) for c in board.calls[1:]] == ["POST wit/workitemsbatch", "PATCH wit/workItems",
                                                              "PATCH wit/workItems", "POST wit/comments"]
    assert cache.load_me(repo)["handle"] == "@dev-one"                     # remembered for the recovery and for `plan`
    assert {e["executed_as"] for e in ledger(repo) if e["event"] in ("applied", "commented")} == {"@dev-one"}


@pytest.mark.parametrize("by,answer,reason", [
    ("@dev-two", None, "identity_mismatch"),                               # az is signed in as person1
    ("@dev-one", "connection_data_sp", "identity_unknown"),                # a service principal
    ("Kim Lee", None, "identity_unknown"),                                 # a --by the roster does not know
])
def test_an_identity_that_is_not_by_refuses_the_whole_plan_after_exactly_one_call(repo, board, two_updates, by, answer, reason):
    if answer:
        board.answers["GET core/connectionData"] = answer
    res = apply(repo, with_rows(two_updates, [*two_updates["rows"], adhoc(repo)]), by=by)
    assert (res["exit"], res["refused_reason"], res["applied"], res["failed"]) == (2, reason, [], [])
    assert len(board.calls) == 1 and route_key_boards(board.calls[0]) == "GET core/connectionData"
    assert written(board) == []                                            # not even the field ops: the whole plan, nothing sent
    assert [e["reason"] for e in events_of(repo, "refused")][-1] == reason


def test_a_pat_only_sign_in_cannot_say_who_is_signed_in_so_the_whole_plan_is_identity_unknown(repo, board, two_updates):
    """B0: the identity read is `az rest`, which needs an Entra token; with a personal access token alone it fails (az's
    words here are hand-written: the capture signed in with Entra). The plan is refused as `identity_unknown` after
    that one call — no field op sent, no identity remembered, and nobody's name stood in for the unknown one."""
    board.fail["_apis/connectionData"] = "ERROR: Please run 'az login' to setup account."
    res = apply(repo, with_rows(two_updates, [*two_updates["rows"], adhoc(repo)]))
    assert (res["exit"], res["refused_reason"], res["applied"], res["failed"]) == (2, "identity_unknown", [], [])
    assert len(board.calls) == 1 and is_identity_rest_read(board.calls[0]) and written(board) == []
    assert cache.load_me(repo) is None
    assert [e["reason"] for e in events_of(repo, "refused")][-1] == "identity_unknown"


def test_an_account_that_is_not_on_the_roster_is_identity_unknown(repo, board, two_updates):
    (repo / ".sdlc" / "team.yaml").write_text(ROSTER.replace("person1@example.com", "someone.else@example.com"),
                                              encoding="utf-8")
    res = apply(repo, with_rows(two_updates, [adhoc(repo)]))
    assert (res["exit"], res["refused_reason"]) == (2, "identity_unknown") and len(board.calls) == 1


def test_a_plan_with_only_field_ops_is_never_held_to_the_identity(repo, board, two_updates):
    # no comment, so no comment into anyone's name: `--by` need not be who az is signed in as. B0 write fixes
    # (2026-10-15): an update is an `az rest` PATCH, so the identity read is still made — as the check that `az rest`
    # can sign in at all (`test_an_update_under_a_pat_only_sign_in_...`) — and only that
    assert apply(repo, two_updates, by="@dev-two")["exit"] == 0
    assert [route_key_boards(c) for c in board.calls].count("GET core/connectionData") == 1
    assert is_identity_rest_read(board.calls[0]) and cache.load_me(repo) is None   # read, not saved: not a comment's


def test_a_plan_with_only_creates_never_reads_the_identity(repo, board, capsys):
    doc = plan_doc(repo, capsys, "--kind", "epic", "--id", "EP-001")
    assert {r["action"] for r in doc["rows"]} == {"create"}
    board.calls.clear()
    assert apply(repo, doc, by="@dev-two")["exit"] == 0     # a create is `devops invoke`: a token alone can send it
    assert not any(route_key_boards(c) == "GET core/connectionData" for c in board.calls)


def test_an_update_under_a_pat_only_sign_in_is_refused_whole_and_nothing_is_sent(repo, board, two_updates):
    """B0 write fixes: `az rest` cannot mint an Entra token from a personal access token, so no update can be sent. The
    whole plan is refused `identity_unknown` (exit 2) after one az call — the identity read — and nothing is written."""
    board.fail["_apis/connectionData"] = "ERROR: Please run 'az login' to setup account."
    res = apply(repo, two_updates)
    assert (res["exit"], res["refused_reason"], res["applied"], res["failed"]) == (2, "identity_unknown", [], [])
    assert len(board.calls) == 1 and is_identity_rest_read(board.calls[0]) and written(board) == []
    assert [e["reason"] for e in events_of(repo, "refused")] == ["identity_unknown"]


# --- comments ----------------------------------------------------------------------------------------------

def test_a_comment_posts_its_text_in_the_body_only_and_ledgers_what_the_board_answered(repo, board):
    seed(repo, linked(SPEC4, 4521))
    hostile = 'say "hi"\nnext line $(touch x) -- --flag `tick` é中'
    row = adhoc(repo, hostile)
    res = apply(repo, with_rows({"schema": 1, "scope": {}}, [row]))
    assert res["exit"] == 0
    (applied,) = res["applied"]
    assert applied == {"ref": SPEC4, "action": "comment", "work_item": 4521, "rev_after": None, "transport": "comments-api",
                       "comment_id": 504, "recovered": False}
    (key, argv, body), = written(board)
    assert key == "POST wit/comments" and body == {"text": row["text"]} and row["text"] == hostile.strip()
    assert not any("touch" in word or "hi" == word for word in argv)       # the text is never an argv word
    assert "format=markdown" in argv and argv[argv.index("--api-version") + 1] == "7.1-preview"
    (line,) = events_of(repo, "commented")
    assert (line["ref"], line["work_item"], line["comment_id"], line["version"], line["via"]) == (SPEC4, 4521, 504, 1, "comments-api")
    assert (line["text_sha"], line["idem_key"], line["trailer"], line["by"], line["executed_as"]) == \
        (row["text_sha"], row["idem_key"], "none", "@dev-one", "@dev-one")
    assert "recovered" not in line and "text" not in line and hostile not in json.dumps(line)
    assert_clean_record(repo, res)


def test_an_event_comment_carries_the_plan_hash_as_its_trailer_and_keeps_its_text_sha(repo, board):
    seed(repo, linked(SPEC4, 4521))
    row = comments.event_row("pr_linked", SPEC4, 4521, {"pr": 12}, {"ref": SPEC4, "pr": 12}, cfg=load_cfg(repo))
    assert row["status"] == "draft" and row["trailer"] == "hash"
    doc = with_rows({"schema": 1, "scope": {}}, [row])
    assert apply(repo, doc)["exit"] == 0
    (_, _, body), = written(board)
    assert body["text"] == f"PR !12 linked. · {bc.TRAILER_TOKEN} {doc['plan']}"
    assert model.text_sha(body["text"]) == row["text_sha"] == events_of(repo, "commented")[0]["text_sha"]


def test_the_history_transport_writes_one_tested_history_entry_at_the_revision_it_knows(repo, board, two_updates):
    set_config(repo, comments={**load_cfg(repo)["comments"], "transport": "history"})
    row = adhoc(repo, "a <b>fact</b> & more")
    res = apply(repo, with_rows(two_updates, [*two_updates["rows"], row]))
    assert res["exit"] == 0
    (spec_applied,) = [a for a in res["applied"] if a["action"] == "comment"]
    assert (spec_applied["transport"], spec_applied["rev_after"]) == ("history", 9) and "comment_id" not in spec_applied
    key, argv, body = written(board)[-1]
    assert key == "PATCH wit/workItems" and route_params(argv)["id"] == "4521"
    assert body[0] == {"op": "test", "path": "/rev", "value": 8}           # the update's own answer, not the stale 7
    assert body[1]["path"] == "/fields/System.History" and "&lt;b&gt;fact&lt;/b&gt; &amp; more" in body[1]["value"]
    assert events_of(repo, "commented")[0]["via"] == "history"


def test_a_comment_post_with_an_unknown_outcome_is_recovered_never_posted_twice(repo, board):
    seed(repo, linked(SPEC4, 4521))
    row = adhoc(repo, "probe from sdlc")                                   # comment 504 of `comments_recent` says the same
    board.fail["workItemId=4521 --http-method POST"] = "`az devops invoke` timed out after 60s."
    res = apply(repo, with_rows({"schema": 1, "scope": {}}, [row]))
    assert res["exit"] == 0 and res["failed"] == []
    (applied,) = res["applied"]
    assert (applied["comment_id"], applied["recovered"]) == (504, True)
    assert board.count("devops", "invoke") == 2 and len([c for c in board.calls if "POST" in c]) == 1   # the POST, the re-list
    assert board.count("rest") == 1 and is_identity_rest_read(board.calls[0])                         # call 0 (B0: az rest)
    assert [route_key_boards(c) for c in board.calls] == ["GET core/connectionData", "POST wit/comments", "GET wit/comments"]
    relist = board.calls[-1]
    assert "order=desc" in relist and "$top=20" in relist
    (line,) = events_of(repo, "commented")
    assert line["recovered"] is True and line["comment_id"] == 504 and line["text_sha"] == row["text_sha"]


def test_an_unknown_outcome_that_the_re_list_cannot_prove_stops_the_run(repo, board):
    seed(repo, linked(SPEC4, 4521), linked("sdlc:spec:0007", 4530))
    rows = [adhoc(repo, "a message nobody has posted"), adhoc(repo, "the next one", ref="sdlc:spec:0007", wid=4530)]
    board.fail["workItemId=4521 --http-method POST"] = "`az devops invoke` timed out after 60s."
    res = apply(repo, with_rows({"schema": 1, "scope": {}}, rows))
    assert res["exit"] == 1 and res["applied"] == []
    assert [(f["action"], f["class"], f["work_item"]) for f in res["failed"]] == [("comment", "unknown", 4521)]
    assert res["deferred"] == [{"ref": "sdlc:spec:0007", "action": "comment", "why": "stopped"}]
    assert len([c for c in board.calls if "POST" in c]) == 1 and events_of(repo, "commented") == []


def test_a_comment_already_on_the_board_is_never_posted_again(repo, board):
    seed(repo, linked(SPEC4, 4521))
    row = adhoc(repo)
    doc = with_rows({"schema": 1, "scope": {}}, [row])
    assert apply(repo, doc)["exit"] == 0 and len(written(board)) == 1
    again = apply(repo, doc)
    assert (again["exit"], again["applied"], again["failed"], again["deferred"]) == (0, [], [], [])
    assert len(written(board)) == 1 and len(events_of(repo, "commented")) == 1


def test_a_comment_whose_ref_is_no_longer_linked_to_that_item_is_not_sent(repo, board):
    row = adhoc(repo)                                                      # never linked in this ledger
    res = apply(repo, with_rows({"schema": 1, "scope": {}}, [row]))
    assert [(f["class"], f["work_item"]) for f in res["failed"]] == [("conflict", 4521)] and written(board) == []


def test_a_skipped_comment_row_sends_nothing_and_needs_no_identity(repo, board):
    skipped = comments.ad_hoc_row(SPEC4, 4521, "probe", by="@dev-one", mentions=[], cfg=load_cfg(repo))
    skipped.update(status="skipped", reason="not_on_board")
    res = apply(repo, with_rows({"schema": 1, "scope": {}}, [skipped]))
    assert (res["exit"], res["applied"]) == (0, []) and board.calls == []


# --- the ledger and the repository -------------------------------------------------------------------------

def test_a_failed_ledger_append_is_drift_and_stops_the_run(repo, board, capsys, monkeypatch):
    doc = create_plan(repo, capsys)
    real_open = builtins.open

    def no_append(file, mode="r", *args, **kwargs):
        if "a" in mode and str(file).endswith("ado-sync-log.jsonl"):
            raise OSError(28, "No space left on device")
        return real_open(file, mode, *args, **kwargs)
    monkeypatch.setattr(builtins, "open", no_append)
    res = apply(repo, doc)
    err = capsys.readouterr().err
    assert res["exit"] == 1 and res["applied"] == []
    assert [(f["ref"], f["class"]) for f in res["failed"]] == [("sdlc:epic:001", "drift")]
    assert res["failed"][0]["work_item"] == 5001                           # the write landed: say which item
    assert len(res["deferred"]) == 6 and {d["why"] for d in res["deferred"]} == {"stopped"}
    assert "DRIFT" in err and len(written(board)) == 1


def test_apply_changes_nothing_under_specs_and_writes_nothing_outside_the_sdlc_folder(repo, board, capsys):
    seed(repo, linked(SPEC4, 4521))
    specs = lambda: {k: v for k, v in snapshot(repo).items() if k.startswith("specs/")}   # noqa: E731
    doc = plan_doc(repo, capsys, "--kind", "spec", "--kind", "epic", "--kind", "feature")
    rows = [*doc["rows"], adhoc(repo)]
    before_all, before_specs = snapshot(repo), specs()
    res = apply(repo, with_rows(doc, rows))
    assert res["applied"] and specs() == before_specs and before_specs
    after = snapshot(repo)
    assert {k for k in after if after[k] != before_all.get(k)} <= {k for k in after if k.startswith(".sdlc/")}
    assert {k for k in before_all} <= set(after)


def test_a_repeated_apply_of_the_same_plan_does_not_double_anything(repo, board, capsys):
    doc = create_plan(repo, capsys)
    assert apply(repo, doc)["exit"] == 0
    sent = len(written(board))
    again = apply(repo, doc)
    assert (again["exit"], again["applied"], again["failed"], again["deferred"]) == (0, [], [], [])
    assert len(written(board)) == sent == 9      # seven creates, and the moves of 0004 and 0005 (not creation states)


def test_a_second_chunk_of_the_same_plan_finds_the_parents_the_first_chunk_made(repo, board, capsys):
    doc = create_plan(repo, capsys)
    first = apply(repo, doc, limit=4)                                      # three epics and the feature
    assert [a["ref"].split(":")[1] for a in first["applied"]] == ["epic"] * 3 + ["feature"]
    board.sent.clear()
    second = apply(repo, doc)
    assert [a["ref"] for a in second["applied"] if a["action"] == "create"] == [SPEC4, SPEC5, "sdlc:spec:0007"]
    assert second["exit"] == 0
    feature_id = next(a["work_item"] for a in first["applied"] if a["ref"] == "sdlc:feature:03")
    (body,) = [b for _, _, b in written(board) if title_of(b).startswith("0004")]
    (url,) = [op["value"]["url"] for op in body if op["path"] == "/relations/-" and op["value"]["rel"] == model.PARENT_REL]
    assert url.endswith(f"/workItems/{feature_id}")


def test_a_ref_the_ledger_already_links_under_another_plan_is_not_created_again(repo, board, capsys):
    doc = plan_doc(repo, capsys, "--kind", "spec", "--id", "0007")
    seed(repo, linked("sdlc:spec:0007", 4999))                             # someone linked it after the plan was made
    res = apply(repo, doc)
    assert [(f["ref"], f["class"], f["work_item"]) for f in res["failed"]] == [("sdlc:spec:0007", "conflict", None)]
    assert written(board) == [] and events_of(repo, "conflict")[0]["ref"] == "sdlc:spec:0007"


def test_every_recorded_argv_carries_detect_false_and_the_seam_adds_the_rest(repo, board, two_updates):
    res = apply(repo, with_rows(two_updates, [adhoc(repo), *two_updates["rows"]]))
    assert res["exit"] == 0 and board.calls
    for argv in board.calls:
        assert "--only-show-errors" not in argv and argv[-2:] == ["-o", "json"]
        assert not any(re.search(r"-preview\.\d", word) for word in argv)
        if is_identity_rest_read(argv):  # B0: the one `az rest` (the identity read) has no --detect flag
            continue
        if argv[:3] == ["rest", "--method", "patch"]:   # B0 write fixes: nor has the update, `az rest` of its URL
            assert route_key_boards(argv) == "PATCH wit/workItems" and "--detect" not in argv
            continue
        assert argv[argv.index("--detect") + 1] == "false"
    assert [is_identity_rest_read(argv) for argv in board.calls].count(True) == 1   # the comment row's identity read
    assert sum(1 for argv in board.calls if argv[:3] == ["rest", "--method", "patch"]) == 2   # the two updates
    assert_clean_record(repo, res)


# --- the module itself -------------------------------------------------------------------------------------

def test_the_module_spawns_nothing_and_names_none_of_the_flags_a_write_must_never_send():
    source = (ROOT / "scripts" / "ado_sync_apply.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)} | \
        {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert "subprocess" not in imported and "ado_sync" not in imported
    assert not re.search(r"shell\s*=\s*True|shlex\.join", source)
    assert not re.search(r"suppressNotifications|bypassRules|validateOnly|-preview\.\d", source)
    assert not re.search(r"\b(DELETE|PUT)\b", source)


def test_the_module_documents_standalone_and_workflow_use():
    doc = apply_mod.__doc__
    assert "Standalone" in doc and "Workflow" in doc and "apply_plan" in doc
