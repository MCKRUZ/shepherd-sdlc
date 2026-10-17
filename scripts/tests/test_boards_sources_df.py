"""The findings source for the Boards mirror: review findings as Bug (or Issue) items (B4-P1b).

`scripts/ado_sync_sources_df.py` reads `.sdlc/metrics/findings-log.jsonl` through `record_findings.load_ledger`
and `findings_model`, and registers `SOURCES["finding"]` with `ado_sync_sources` when it is imported. Each test
builds a ledger in `tmp_path` with the real writer (`record_findings.build_entry`), so what the source reads is
what `/sprd-review` records.

The rules held most firmly: a CRITICAL or HIGH finding is a `BugCategory` item and every other one is the
configured `types.finding`; the title is `[<category>] <fingerprint>`; the State comes from the disposition and
a mislabelled SPLIT or ACCEPTED_RISK still counts as open; a SPLIT is `Related` to the spec it names; and no
word a reviewer wrote (detail, reason, review condition, owner, approver) reaches any field, tag or note.

`ado_sync_sources_df` is never imported at module level here: importing it registers a source in the real
`ado_sync_sources.SOURCES`, which `ado_sync.py` itself now does (it imports the module, so `plan --kind finding`
plans findings: `test_plan_with_the_cli_finding_is_a_sourced_kind` below). The `df` fixture imports it afresh
against a stand-in hook table and leaves `sys.modules` as it found it, so a test's registration never lands in the
real table.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import HAND_WRITTEN_PROCESS

import ast
import hashlib
import importlib
import json
import os
import re
import sys
import types
from pathlib import Path

import pytest

import ado_sync_model as model
import ado_sync_sources as src
import ado_wit_map as wm
import boards_contract as bc
import record_findings as rf

# B0 (2026-10-14): these scenarios combine the item, history and write fixtures — hand-written for the hand-written
# Agile process, and not captured yet — with a process, so they read that same process even where a capture exists
# (tests/ado_boards_fixtures.py, `BOARDS_PROCESS`). The captured process is exercised in test_boards_captured_process.py.
BOARDS_PROCESS = HAND_WRITTEN_PROCESS

SCRIPTS = Path(src.__file__).resolve().parent
MODULE = SCRIPTS / "ado_sync_sources_df.py"
LEDGER = ".sdlc/metrics/findings-log.jsonl"
PINNED = {"ref", "kind", "id", "title", "status", "fields", "tags", "parent_ref", "parent_note", "related_refs",
          "source_path", "source_sha"}
TARGET = "specs/0004-duplicate-claim-409.md"
FP = f"auth-gap:{TARGET}"
TS = "2026-10-01T09:00:00+00:00"
HYPERLINK = "https://dev.azure.com/org/Claims/_git/claims-api?path=/x.md&version=GCabc1234"
HISTORY = f"{bc.HISTORY_TOKEN} · created"


def _states(*pairs):
    return [{"name": n, "category": c, "order": i} for i, (n, c) in enumerate(pairs)]


BUG_STATES = _states(("New", "Proposed"), ("Active", "InProgress"), ("Resolved", "Resolved"), ("Closed", "Completed"))
ISSUE_STATES = _states(("To Do", "Proposed"), ("Doing", "InProgress"), ("Done", "Completed"))
# Agile: a Bug with no Removed state. Scrum: a Bug that has one. Basic: no BugCategory at all, only an Issue.
AGILE = {"types": {"Bug": {"states": BUG_STATES}, "Issue": {"states": ISSUE_STATES}},
         "categories": {"BugCategory": {"default_type": "Bug", "types": ["Bug"]}}}
SCRUM = {"types": {"Bug": {"states": _states(("New", "Proposed"), ("Approved", "Proposed"), ("Committed", "InProgress"),
                                              ("Done", "Completed"), ("Removed", "Removed"))},
                   "Issue": {"states": ISSUE_STATES}},
         "categories": {"BugCategory": {"default_type": "Bug", "types": ["Bug"]}}}
BASIC = {"types": {"Issue": {"states": ISSUE_STATES}}, "categories": {}}
CFG = {"types": {"finding": "Issue"}}


# --- a repository in tmp_path, a ledger written by the real writer --------------------------------------------------

def finding(**kw) -> dict:
    """A parsed `## Gate Results` row: the keys `record_findings.parse_findings_block` hands `build_entry`."""
    row = {"id": "F1", "category": "auth-gap", "severity": "HIGH", "target": f"{TARGET}:12", "disposition": "OPEN",
           "detail": "the handler trusts the caller"}
    row.update(kw)
    return row


def record(root: Path, *findings, stamp: str = TS, report: str = "review-report.md") -> None:
    path = root / LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        for item in findings:
            handle.write(json.dumps(rf.build_entry(item, report, root, stamp)) + "\n")


def tree_sha(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def short(fingerprint: str) -> str:
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:8]


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


@pytest.fixture
def hooks() -> types.ModuleType:
    """A stand-in `ado_sync_sources` hook table: the module registers into this, never into the real one."""
    stub = types.ModuleType("ado_sync_sources")
    stub.SOURCES, stub.PARENT_RESOLVERS = {}, {}
    return stub


@pytest.fixture
def snapshot() -> dict:
    return dict(src.SOURCES)


@pytest.fixture
def df(monkeypatch, hooks):
    """`ado_sync_sources_df` imported afresh: its import-time registration lands in `hooks`, and `sys.modules` is
    restored at teardown so a cached copy never hides the registration from the next importer."""
    monkeypatch.setitem(sys.modules, "ado_sync_sources_df", None)  # recorded: undone at teardown
    del sys.modules["ado_sync_sources_df"]
    with monkeypatch.context() as inner:
        inner.setitem(sys.modules, "ado_sync_sources", hooks)
        return importlib.import_module("ado_sync_sources_df")


@pytest.fixture
def project(monkeypatch, df):
    """`projections` over the real `ado_sync_sources`, with the finding loader set for this test only."""
    monkeypatch.setitem(src.SOURCES, "finding", df.load_findings)

    def run(root, cfg=CFG, schema=AGILE, kinds=("finding",)):
        return src.projections(root, cfg, schema, list(kinds))
    return run


def one(project, root, **kw) -> dict:
    (row,) = project(root, **kw)
    return row


# --- registration through ado_sync_sources' extend-only table -------------------------------------------------------

def test_importing_the_module_registers_the_finding_source_and_nothing_else(hooks, df):
    assert set(hooks.SOURCES) == {"finding"} and hooks.SOURCES["finding"] is df.load_findings
    assert hooks.PARENT_RESOLVERS == {}, "a finding has no parent: no resolver is registered"


def test_registration_is_extend_only_and_repeatable(hooks, df):
    spec_loader, resolver = object(), object()
    hooks.SOURCES["spec"], hooks.PARENT_RESOLVERS["feature"] = spec_loader, resolver
    assert df._register(hooks) is True and df._register(hooks) is True
    assert hooks.SOURCES["spec"] is spec_loader and hooks.PARENT_RESOLVERS["feature"] is resolver
    assert set(hooks.SOURCES) == {"spec", "finding"} and set(hooks.PARENT_RESOLVERS) == {"feature"}


def test_without_the_hook_table_nothing_is_registered_and_nothing_fails(df, monkeypatch):
    assert df._register(types.SimpleNamespace()) is False
    assert df._register(types.SimpleNamespace(SOURCES=None)) is False
    monkeypatch.setitem(sys.modules, "ado_sync_sources", None)  # an import of it now fails
    assert df._register() is False


def test_the_test_import_leaves_the_real_hook_table_and_sys_modules_as_they_were(snapshot, df):
    assert src.SOURCES == snapshot, "importing the module in a test must not register a source in the real table"
    assert sys.modules["ado_sync_sources"] is src


def test_the_loader_answers_through_projections_and_standalone_with_the_repository_alone(monkeypatch, df, repo):
    record(repo, finding())
    monkeypatch.setitem(src.SOURCES, "finding", df.load_findings)
    assert [p["kind"] for p in src.projections(repo, CFG, AGILE, ["finding"])] == ["finding"]
    assert [p["kind"] for p in df.load_findings(repo)] == ["finding"], "cfg and schema are optional standalone"


# --- reading the ledger ---------------------------------------------------------------------------------------------

def test_no_ledger_or_an_empty_one_yields_no_rows_and_a_directory_is_not_a_ledger(project, repo):
    assert project(repo) == []
    (repo / LEDGER).parent.mkdir(parents=True)
    (repo / LEDGER).write_text("", encoding="utf-8")
    assert project(repo) == []
    (repo / LEDGER).unlink()
    (repo / LEDGER).mkdir()
    assert project(repo) == []


def test_a_malformed_line_and_a_line_that_is_not_an_object_are_skipped(project, repo):
    record(repo, finding())
    with open(repo / LEDGER, "a", encoding="utf-8") as handle:
        handle.write("{not json\n42\n[1, 2]\n\n")
    assert [p["id"] for p in project(repo)] == [short(FP)]


def test_a_ledger_that_resolves_outside_the_repository_is_refused(project, repo, tmp_path):
    outside = tmp_path / "outside.jsonl"
    outside.write_text(json.dumps(rf.build_entry(finding(), "r.md", repo, TS)) + "\n", encoding="utf-8")
    (repo / LEDGER).parent.mkdir(parents=True)
    try:
        os.symlink(outside, repo / LEDGER)
    except (OSError, NotImplementedError):
        pytest.skip("this platform cannot create a symlink")
    with pytest.raises(ValueError, match="outside the repository"):
        project(repo)


def test_a_read_writes_nothing_and_leaves_the_repository_byte_identical(project, repo):
    record(repo, finding(), finding(category="race", severity="LOW", target="a.md:3"))
    before = tree_sha(repo)
    project(repo)
    project(repo, cfg={}, schema={})
    assert tree_sha(repo) == before, "a read changed, added or removed a file"


def test_one_projection_per_fingerprint_and_the_latest_round_decides(project, repo):
    record(repo, finding(), finding(category="race", severity="LOW", target="a.md:3"), stamp="2026-10-01T09:00:00+00:00")
    record(repo, finding(disposition="FIXED"), stamp="2026-10-02T09:00:00+00:00")
    rows = {p["id"]: p for p in project(repo)}
    assert set(rows) == {short(FP), short("race:a.md")}
    assert rows[short(FP)]["status"] == "fixed" and rows[short(FP)]["fields"]["System.State"] == "Closed"
    assert rows[short("race:a.md")]["status"] == "open"


# --- the projection: identity, title, tags, parent, source ----------------------------------------------------------

def test_a_high_open_finding_is_a_bug_with_the_pinned_projection_keys(project, repo):
    record(repo, finding())
    row = one(project, repo)
    assert PINNED <= set(row) and "source_row" not in row
    fp = short(FP)
    assert row["ref"] == f"sdlc:finding:{fp}" and row["kind"] == "finding" and row["id"] == fp
    assert bc.REF_RE.fullmatch(row["ref"]) and bc.HASH_RE.fullmatch(row["source_sha"])
    assert row["title"] == f"[auth-gap] {FP}" and row["status"] == "open"
    assert row["fields"] == {"System.Title": f"[auth-gap] {FP}", "System.State": "New", "type_route": "BugCategory",
                             "type_name": "Bug"}
    assert row["tags"] == {row["ref"], "severity:HIGH"} and isinstance(row["tags"], set)
    assert row["parent_ref"] is None and row["parent_note"] is None and row["related_refs"] == []
    assert row["source_path"] == LEDGER and row["notes"] == []


def test_the_tag_names_the_finding_the_way_its_disposition_comment_does(repo):
    """B3's `finding_disposition` comment says `Finding <8 hex>`: the sha-256 of the ledger fingerprint. The item's
    tag carries the same eight characters, so a person reading the board can match the comment to the item."""
    import ado_sync_comments as comments
    (repo / "specs").mkdir()
    (repo / "specs" / "0004-duplicate-claim-409.md").write_text(
        '---\nspec: "0004"\nname: "duplicate claim 409"\nstatus: in-flight\nowner: "@dev-one"\n---\n\n# Spec 0004\n\n'
        "## Scope\n\n### In scope\n- `specs/0004-duplicate-claim-409.md`\n\n### Out of scope\n- nothing\n",
        encoding="utf-8")
    record(repo, finding(disposition="FIXED"))
    rows = comments.draft_event_rows(repo, {"comments": {"events": {"finding_disposition": "on"}}}, [],
                                     {"sdlc:spec:0004": 4004})
    (drafted,) = [r for r in rows if r["event"] == "finding_disposition"]
    assert re.fullmatch(r"Finding ([0-9a-f]{8}) marked fixed\.", drafted["text"]), drafted
    assert drafted["text"] == f"Finding {short(FP)} marked fixed."


def test_a_blank_category_reads_uncategorized_and_a_line_with_no_fingerprint_is_given_one(project, repo):
    (repo / LEDGER).parent.mkdir(parents=True)
    line = {"timestamp": TS, "report": "r.md", "id": "F1", "category": "Auth Gap", "severity": "HIGH",
            "target": "a.md:1", "disposition": "OPEN", "detail": "x"}
    blank = {**line, "category": "  ", "target": ""}
    (repo / LEDGER).write_text(json.dumps(line) + "\n" + json.dumps(blank) + "\n", encoding="utf-8")
    titles = {p["fields"]["System.Title"] for p in project(repo)}
    assert titles == {"[Auth Gap] auth-gap:a.md", "[uncategorized] uncategorized"}


def test_a_title_over_the_work_item_limit_is_cut_with_a_note_and_the_projections_own_title_is_not(project, repo):
    category = "x" * 300
    record(repo, finding(category=category))
    row = one(project, repo)
    assert len(row["fields"]["System.Title"]) == 255 and row["fields"]["System.Title"].endswith("…")
    assert "title cut to 255 characters, the work item limit" in row["notes"]
    assert row["title"].startswith(f"[{category}] ")


def test_a_control_character_in_a_category_becomes_a_space(project, repo):
    record(repo, finding(category="auth\x1b[31m\ngap"))
    row = one(project, repo)
    assert "\x1b" not in row["title"] and "\n" not in row["title"] and row["title"].startswith("[auth [31m gap] ")


def test_two_fingerprints_that_share_a_short_form_are_refused_naming_both(df, repo, monkeypatch):
    record(repo, finding(), finding(category="race", target="a.md:3"))
    monkeypatch.setattr(df, "short_fingerprint", lambda fingerprint: "00000000")
    with pytest.raises(ValueError, match=r"auth-gap:specs/0004.*race:a\.md|race:a\.md.*auth-gap:specs/0004"):
        df.load_findings(repo)


# --- severity: BugCategory for CRITICAL/HIGH, types.finding for the rest --------------------------------------------

@pytest.mark.parametrize("severity, route, type_name, state", [
    ("CRITICAL", "BugCategory", "Bug", "New"),
    ("HIGH", "BugCategory", "Bug", "New"),
    ("high", "BugCategory", "Bug", "New"),
    ("MEDIUM", "types.finding", "Issue", "To Do"),
    ("LOW", "types.finding", "Issue", "To Do"),
])
def test_critical_and_high_are_bugcategory_and_the_rest_are_the_configured_type(project, repo, severity, route,
                                                                                type_name, state):
    record(repo, finding(severity=severity))
    row = one(project, repo)
    assert (row["fields"]["type_route"], row["fields"]["type_name"], row["fields"]["System.State"]) == (
        route, type_name, state)
    assert row["tags"] == {row["ref"], f"severity:{severity.upper()}"}


def test_the_bugcategory_default_type_is_whatever_the_process_calls_it(project, repo):
    schema = {"types": {"Defect": {"states": BUG_STATES}, "Issue": {"states": ISSUE_STATES}},
              "categories": {"BugCategory": {"default_type": "Defect", "types": ["Defect"]}}}
    record(repo, finding())
    assert one(project, repo, schema=schema)["fields"]["type_name"] == "Defect"


def test_an_unknown_severity_is_mirrored_as_the_configured_type_with_no_severity_tag_and_a_note(project, repo):
    record(repo, finding(severity="SEVERE-ISH"))
    row = one(project, repo)
    assert row["tags"] == {row["ref"]} and row["fields"]["type_route"] == "types.finding"
    assert any("severity" in n and "CRITICAL" in n for n in row["notes"]) and "SEVERE-ISH" not in json.dumps(row, default=sorted)


def test_a_process_with_no_bugcategory_falls_back_to_the_pin_and_says_so(project, repo):
    record(repo, finding())
    row = one(project, repo, schema=BASIC)
    assert (row["fields"]["type_route"], row["fields"]["type_name"], row["fields"]["System.State"]) == (
        "types.finding", "Issue", "To Do")
    assert any("BugCategory" in n for n in row["notes"])


def test_with_no_type_to_use_no_type_and_no_state_are_invented_and_the_notes_say_why(project, repo):
    record(repo, finding(), finding(category="race", severity="LOW", target="a.md:3"))
    for schema in (BASIC, AGILE):
        rows = {p["fields"]["System.Title"]: p for p in project(repo, cfg={}, schema=schema)}
        medium = rows["[race] race:a.md"]
        assert set(medium["fields"]) == {"System.Title"}, "no types.finding pin: no type, so no state"
        assert any(n.startswith("type not set: types.finding not set") for n in medium["notes"]), medium["notes"]
    standalone = project(repo, cfg={}, schema={})
    assert all(set(p["fields"]) == {"System.Title"} for p in standalone)
    assert all(p["notes"] for p in standalone), "each row says why it has no type"


def test_a_disabled_bugcategory_default_type_falls_back_to_the_pin(project, repo):
    schema = {**AGILE, "types": {**AGILE["types"], "Bug": {"states": BUG_STATES, "disabled": True}}}
    record(repo, finding())
    row = one(project, repo, schema=schema)
    assert row["fields"]["type_name"] == "Issue" and any("BugCategory" in n for n in row["notes"])


# --- State from the disposition -------------------------------------------------------------------------------------

def _state_of(project, repo, schema=AGILE, severity="HIGH", **kw):
    (repo / LEDGER).unlink(missing_ok=True)
    record(repo, finding(severity=severity, **kw))
    return one(project, repo, schema=schema)


@pytest.mark.parametrize("extra, status, state", [
    ({"disposition": "OPEN"}, "open", "New"),
    ({"disposition": "POSTPONED"}, "postponed", "New"),  # deferred without a home: still debt, so still open
    ({"disposition": "FIXED"}, "fixed", "Closed"),
    ({"disposition": "ACCEPTED_RISK", "approver": "Jane Doe", "date": "2026-10-02", "reason": "r",
      "review_condition": "rc"}, "accepted-risk", "Closed"),
])
def test_the_state_follows_the_disposition(project, repo, extra, status, state):
    row = _state_of(project, repo, **extra)
    assert (row["status"], row["fields"]["System.State"]) == (status, state) and row["notes"] == []


def test_a_split_is_deferred_where_the_process_has_a_removed_state_and_says_so_where_it_has_none(project, repo):
    split = {"disposition": "SPLIT", "split_to": "0042", "owner": "Jane"}
    assert _state_of(project, repo, schema=SCRUM, **split)["fields"]["System.State"] == "Removed"
    row = _state_of(project, repo, schema=AGILE, **split)
    assert "System.State" not in row["fields"] and row["status"] == "split"
    assert any(n.startswith("state not set:") and "Removed" in n for n in row["notes"]), row["notes"]


def test_a_state_rule_in_the_config_is_applied_to_the_findings_type(project, repo):
    two_done = {"types": {"Issue": {"states": _states(("To Do", "Proposed"), ("Done", "Completed"),
                                                      ("Closed", "Completed"))}}, "categories": {}}
    record(repo, finding(severity="MEDIUM", disposition="FIXED"))
    assert one(project, repo, schema=two_done)["fields"]["System.State"] == "Done"   # the rule's first Completed state
    prefer_closed = {**CFG, "states": {"finding": {"closed": {"category": "Completed", "prefer": "Closed"}}}}
    assert one(project, repo, cfg=prefer_closed, schema=two_done)["fields"]["System.State"] == "Closed"
    other_kind = {**CFG, "states": {"spec": {"closed": {"category": "Completed", "prefer": "Closed"}}}}
    assert one(project, repo, cfg=other_kind, schema=two_done)["fields"]["System.State"] == "Done"


@pytest.mark.parametrize("extra, reason", [
    ({"disposition": "SPLIT"}, "SPLIT missing required field(s): split_to, owner"),
    ({"disposition": "SPLIT", "split_to": "0042"}, "SPLIT missing required field(s): owner"),
    ({"disposition": "ACCEPTED_RISK", "approver": "Jane Doe"}, "ACCEPTED_RISK missing required field(s)"),
    ({"disposition": "ACCEPTED_RISK", "approver": "Claude", "date": "2026-10-02", "reason": "r",
      "review_condition": "rc"}, "ACCEPTED_RISK approver must be a human, not an AI"),
])
def test_a_mislabelled_disposition_still_counts_as_open(project, repo, extra, reason):
    row = _state_of(project, repo, **extra)
    assert row["fields"]["System.State"] == "New", "a SPLIT or ACCEPTED_RISK that lacks its evidence is still debt"
    assert any(n.startswith(reason) and n.endswith("it still counts as debt, so the item is mirrored as open")
               for n in row["notes"]), row["notes"]


def test_an_unknown_disposition_gets_no_status_and_no_state_and_is_not_echoed(project, repo):
    row = _state_of(project, repo, disposition="WONTFIX-FOR-NOW")
    assert row["status"] is None and "System.State" not in row["fields"]
    assert any("disposition" in n and "OPEN" in n for n in row["notes"])
    assert "WONTFIX" not in json.dumps(row, default=sorted)


# --- SPLIT -> Related to the spec item ------------------------------------------------------------------------------

@pytest.mark.parametrize("split_to", ["0042", "spec 0042", "SPEC-0042", " 0042 ", "sdlc:spec:0042"])
def test_a_split_is_related_to_the_spec_it_names(project, repo, split_to):
    row = _state_of(project, repo, schema=SCRUM, disposition="SPLIT", split_to=split_to, owner="Jane")
    assert row["related_refs"] == ["sdlc:spec:0042"] and row["parent_ref"] is None and row["notes"] == []


def test_a_split_to_something_that_is_not_a_spec_has_no_link_and_a_note_without_the_value(project, repo):
    for split_to in ("JIRA-1234", "sdlc:decision:01", "the other team"):
        row = _state_of(project, repo, schema=SCRUM, disposition="SPLIT", split_to=split_to, owner="Jane")
        assert row["related_refs"] == [] and row["fields"]["System.State"] == "Removed"
        assert any("split_to" in n and "spec" in n for n in row["notes"]) and split_to not in json.dumps(row, default=sorted)


def test_only_a_split_is_related_whatever_else_the_line_carries(project, repo):
    for disposition in ("OPEN", "FIXED", "POSTPONED"):
        assert _state_of(project, repo, disposition=disposition, split_to="0042")["related_refs"] == []


def test_a_split_that_names_a_spec_but_no_owner_is_related_and_still_open(project, repo):
    row = _state_of(project, repo, disposition="SPLIT", split_to="0042")
    assert row["related_refs"] == ["sdlc:spec:0042"] and row["fields"]["System.State"] == "New"


# --- never finding text ---------------------------------------------------------------------------------------------

SECRETS = ("DETAIL-SECRET", "REASON-SECRET", "CONDITION-SECRET", "OWNER-SECRET", "APPROVER-SECRET")
ADDRESS = "kim" + "@corp.com"


def test_no_word_a_reviewer_wrote_reaches_a_field_a_tag_or_a_note(project, repo):
    record(repo,
           finding(detail=f"DETAIL-SECRET {ADDRESS} raw SQL in the handler"),
           finding(category="race", target="a.md:3", disposition="SPLIT", split_to="0042", owner=f"OWNER-SECRET {ADDRESS}",
                   detail="DETAIL-SECRET again"),
           finding(category="leak", target="b.md:3", disposition="ACCEPTED_RISK", approver=f"APPROVER-SECRET {ADDRESS}",
                   date="2026-10-02", reason="REASON-SECRET", review_condition="CONDITION-SECRET"),
           finding(category="stale", target="c.md:3", disposition="SPLIT", owner="OWNER-SECRET", reason="REASON-SECRET"))
    rows = project(repo, cfg={**CFG, "fields": {"finding": {"detail": "System.Description", "reason": {
        "field": "Custom.Why"}}}})
    assert len(rows) == 4
    blob = json.dumps(rows, default=sorted)
    assert not [s for s in (*SECRETS, ADDRESS, "@corp") if s in blob], blob
    for row in rows:
        assert set(row["fields"]) <= {"System.Title", "System.State", "type_route", "type_name"}, row["fields"]


def test_a_configured_field_for_a_finding_is_not_applied_and_the_row_says_so(project, repo):
    record(repo, finding())
    cfg = {**CFG, "fields": {"finding": {"severity": "Microsoft.VSTS.Common.Severity"}}}
    row = one(project, repo, cfg=cfg)
    assert "Microsoft.VSTS.Common.Severity" not in row["fields"]
    assert any(n.startswith("fields.finding is not applied") for n in row["notes"]), row["notes"]
    assert one(project, repo)["notes"] == [], "no note without a fields.finding entry"


def test_a_findings_diff_is_the_title_the_state_and_the_plugin_tags_only_and_it_can_be_created(project, repo):
    record(repo, finding())
    row = one(project, repo)
    assert [o["path"] for o in model.diff(row, None)] == ["/fields/System.State", "/fields/System.Tags",
                                                          "/fields/System.Title"]
    patch = wm.build_create_patch(row, AGILE, HYPERLINK, HISTORY, None)
    assert [o["path"] for o in patch if o["path"].startswith("/fields/")] == [
        "/fields/System.State", "/fields/System.Tags", "/fields/System.Title", "/fields/System.History"]
    assert next(o["value"] for o in patch if o["path"] == "/fields/System.Tags") == f"{row['ref']}; severity:HIGH"
    assert next(o["value"] for o in patch if o["path"] == "/fields/System.Title") == row["title"]


def test_the_board_owns_a_findings_state_after_create_and_the_repository_owns_its_title_and_tags(project, repo):
    record(repo, finding())
    row = one(project, repo)
    remote = {"title": row["fields"]["System.Title"], "state": "Active", "tags": set(row["tags"])}
    own = model.ownership_for("finding")
    assert model.diff(row, remote, own) == [], "a State the board moved is the board's: no op"
    record(repo, finding(severity="CRITICAL"), stamp="2026-10-02T09:00:00+00:00")
    moved = one(project, repo)
    assert [o["path"] for o in model.diff(moved, remote, own)] == ["/fields/System.Tags"]


# --- source_sha: the finding's own facts, so a new round that changes nothing moves nothing -------------------------

def test_source_sha_moves_with_what_is_mirrored_and_with_nothing_else(project, repo):
    record(repo, finding(), finding(category="race", target="a.md:3", severity="LOW"))
    before = {p["ref"]: p["source_sha"] for p in project(repo)}
    assert len(set(before.values())) == 2 and all(bc.HASH_RE.fullmatch(s) for s in before.values())
    # the same review re-recorded a week later, its detail reworded and its line number moved: nothing mirrored changed
    record(repo, finding(detail="a different sentence", target=f"{TARGET}:99"),
           finding(category="race", target="a.md:7", severity="LOW"), stamp="2026-10-08T09:00:00+00:00", report="again.md")
    assert {p["ref"]: p["source_sha"] for p in project(repo)} == before
    # the disposition changes: only that finding's sha moves
    record(repo, finding(disposition="FIXED"), stamp="2026-10-09T09:00:00+00:00")
    after = {p["ref"]: p["source_sha"] for p in project(repo)}
    moved = {ref for ref in before if before[ref] != after[ref]}
    assert moved == {f"sdlc:finding:{short(FP)}"}


def test_a_split_gaining_its_owner_moves_the_sha_because_it_changes_the_state(project, repo):
    record(repo, finding(disposition="SPLIT", split_to="0042"))
    first = one(project, repo, schema=SCRUM)
    record(repo, finding(disposition="SPLIT", split_to="0042", owner="Jane"), stamp="2026-10-09T09:00:00+00:00")
    second = one(project, repo, schema=SCRUM)
    assert first["fields"]["System.State"] == "New" and second["fields"]["System.State"] == "Removed"
    assert first["source_sha"] != second["source_sha"]


# --- through the CLI: `ado_sync.py` imports the source (spec 0037) -------------------------------------------------

MINI = Path(__file__).resolve().parent / "fixtures" / "boards_repo"


def _cli_repo(tmp_path: Path, capsys, **types_pin) -> Path:
    import shutil

    import yaml

    import ado_sync
    root = tmp_path / "repo"
    shutil.copytree(MINI, root)
    assert ado_sync.main(["config", "init", "--repo", str(root)]) == 0
    assert ado_sync.main(["discover", "--repo", str(root)]) == 0
    path = root / bc.CONFIG_FILE
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["fields"] = {"spec": {"risk": {"field": "Custom.RiskTier",
                                       "values": {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW"}}}}
    if types_pin:
        cfg["types"] = {**(cfg.get("types") or {}), **types_pin}
    path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    capsys.readouterr()
    return root


def _plan_findings(root: Path, capsys) -> dict:
    import ado_sync
    code = ado_sync.main(["plan", "--kind", "finding", "--repo", str(root), "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert code == 0, doc
    return doc


def test_plan_with_the_cli_finding_is_a_sourced_kind(tmp_path, az, capsys):
    """`ado_sync.py` imports the source, so `plan --kind finding` plans review findings as work items: a HIGH finding
    on the process's BugCategory default type, titled `[<category>] <fingerprint>`, with no reviewer's words."""
    import ado_sync  # noqa: F401  (the CLI's own import is what registers the kind)
    loader = src.SOURCES.get("finding")
    assert loader is not None and (loader.__module__, loader.__name__) == ("ado_sync_sources_df", "load_findings")
    root = _cli_repo(tmp_path, capsys)
    bug = json.loads((root / bc.SCHEMA_FILE).read_text(encoding="utf-8"))["categories"]["BugCategory"]["default_type"]
    record(root, finding(), finding(id="F2", category="style", severity="LOW", target="scripts/x.py:3"))
    doc = _plan_findings(root, capsys)
    assert not any(s["kind"] == "finding" for s in doc["skipped"])
    rows = {r["ref"]: r for r in doc["rows"] if r["kind"] == "finding"}
    high = rows[f"sdlc:finding:{short(FP)}"]
    assert high["action"] == "create" and high["type"] == bug
    title = next(o["new"] for o in high["ops"] if o["path"] == "/fields/System.Title")
    assert title == f"[auth-gap] {FP}"
    low = rows[f"sdlc:finding:{short('style:scripts/x.py')}"]
    assert low["action"] == "unmapped" and low["type"] is None and "types.finding" in low["reason"]  # never guessed
    assert "trusts the caller" not in json.dumps(doc)


def test_plan_with_the_cli_lands_the_other_findings_on_the_pinned_finding_type(tmp_path, az, capsys):
    root = _cli_repo(tmp_path, capsys, finding="Issue")
    bug = json.loads((root / bc.SCHEMA_FILE).read_text(encoding="utf-8"))["categories"]["BugCategory"]["default_type"]
    record(root, finding(), finding(id="F2", category="style", severity="LOW", target="scripts/x.py:3"))
    rows = {r["ref"]: r for r in _plan_findings(root, capsys)["rows"] if r["kind"] == "finding"}
    assert rows[f"sdlc:finding:{short(FP)}"]["type"] == bug                 # HIGH stays a Bug despite the pin
    assert rows[f"sdlc:finding:{short('style:scripts/x.py')}"]["type"] == "Issue"
    assert {r["action"] for r in rows.values()} == {"create"}


# --- the module itself ----------------------------------------------------------------------------------------------

ALLOWED_IMPORTS = {"hashlib", "importlib", "json", "re", "sys", "pathlib", "boards_contract", "findings_model",
                   "ado_schema_map", "record_findings"}


def _imports(tree: ast.AST) -> set[str]:
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    return imported | {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}


def test_the_module_is_read_only_spawns_nothing_and_imports_only_what_it_needs():
    text = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    assert _imports(tree) <= ALLOWED_IMPORTS, _imports(tree) - ALLOWED_IMPORTS
    assert not _imports(tree) & {"subprocess", "ado_transport", "ado_sync_sources", "socket", "urllib", "requests",
                                 "shutil", "os", "yaml"}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "rename", "touch", "chmod",
                        "symlink_to", "write"}, attrs
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"open", "print", "input", "exec", "eval", "__import__"}, called
    assert not re.search(r"shell=True|shlex\.join", text)


def test_the_module_reads_no_identity_and_names_no_preview_api_version():
    text = MODULE.read_text(encoding="utf-8")
    assert "EMAIL_RE" not in text and '"email"' not in text and "'email'" not in text
    assert not re.search(r"-preview\.\d", text)


def test_the_module_never_reads_the_text_fields_of_a_ledger_line():
    """The only ledger keys the module may name are the ones that become a title, a tag, a state or a link."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    keys = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not keys & {"detail", "reason", "review_condition", "approver", "date", "target_sha", "report"}, keys
