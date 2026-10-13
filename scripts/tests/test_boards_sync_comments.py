"""Comment drafting for the Boards mirror (B3-P3): the eleven event templates, the rows `plan` derives from the
repository's own ledgers, and the rows a person's own `comment --message` makes.

`ado_sync_comments.py` only DRAFTS: it reads `.sdlc/metrics/sprint-log.jsonl`, `.sdlc/decision-log.md`,
`.sdlc/metrics/findings-log.jsonl`, `.sdlc/state.yaml`, `specs/` and the Boards ledger, and hands back plan rows. It
never spawns `az` and writes nothing; only an `apply` (B3-P2) sends. Every test here builds its repository in
`tmp_path` (generic handles, fictional text); the hostile one plants an address, a finding's detail, a note and an
intake document where a careless template would copy them. Addresses are assembled from parts (house rule 10).
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401

import ast
import copy
import hashlib
import json
import re
from pathlib import Path

import pytest
import yaml

import ado_sync_comments as acm
import ado_sync_model as sm
import boards_contract as bc

MODULE = Path(acm.__file__)
PLUGIN_ROOT = MODULE.parent.parent
STARTER = yaml.safe_load((PLUGIN_ROOT / "templates" / "ado" / "ado.yaml").read_text(encoding="utf-8"))
STEMS = frozenset(p.stem for p in (PLUGIN_ROOT / "agents").glob("*.md"))

KIM = "kim" + "@corp.com"                     # the card's hostile address, assembled
DEV_ONE_EMAIL = "dev.one" + "@example.com"    # the roster's one address
AT_CORP = "@" + "corp.com"                    # a bare `@domain` form: no local part, so not an address, still refused
AT_ORG = "@" + "example.org"
ZERO = "0" * 12
TS_HANDOFF = "2026-10-02T09:00:00+00:00"
TS_VERDICT = "2026-10-03T09:00:00+00:00"
HOSTILE_REASON = f"Acme Corp asked {KIM} to drop it, see DOC-007 salary table"
HOSTILE_NOTE = "NOTE-SECRET please call the client"
HOSTILE_DETAIL = f"DETAIL-SECRET {KIM} found raw SQL"
INTAKE_TEXT = "INTAKE-CLIENT-TEXT the client pays 4 million"

ROW_KEYS = {"action", "kind", "origin", "status", "reason", "detail", "event", "ref", "work_item", "target",
            "idem_key", "variant", "text", "format", "chars", "text_sha", "trailer", "mentions", "drafted_by",
            "budget", "notes"}
IDMAP = {"sdlc:spec:0004": 4004, "sdlc:spec:0005": 4005, "sdlc:spec:0007": 4007, "sdlc:spec:0009": 4009,
         "sdlc:decision:02": 4102, "sdlc:lifecycle:project": 4900}
ALL_ON = {"comments": {"events": {e: "on" for e in sm.COMMENT_EVENTS}}}


# --- a repository in tmp_path -----------------------------------------------------------------------------------

def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def jsonl(root: Path, rel: str, events: list) -> None:
    write(root, rel, "".join(json.dumps(e) + "\n" for e in events))


def spec_text(ident, name, status="in-flight", *, owner="@dev-one", developer="@dev-two", checker="@dev-one",
              reason="", extra="", scope=("scripts/claims.py",)) -> str:
    paths = "".join(f"- `{p}`\n" for p in scope)
    return (f'---\nspec: "{ident}"\nname: "{name}"\nstatus: {status}\ndeferred_reason: "{reason}"\n'
            f'owner: "{owner}"\ndeveloper: "{developer}"\nchecker: "{checker}"\n{extra}---\n\n'
            f"# Spec {ident}\n\n## Scope\n\n### In scope\n{paths}\n### Out of scope\n- nothing\n")


ROSTER = f"""version: "1.0"
teams:
  - name: core
    lead: "@dev-one"
people:
  - handle: "@dev-one"
    name: "Person One"
    email: "{DEV_ONE_EMAIL}"
  - handle: "@dev-two"
    name: "Person Two"
"""

DECISIONS = """# Decision Log

| id    | decision | owner | opened | due (2 business days) | status |
|-------|----------|-------|--------|-----------------------|--------|
| DL-01 | Which channel ships first? | @dev-one | 2026-10-05 | 2026-10-07 | open |
| DL-02 | How long are claim drafts kept? — decided by @dev-one on 2026-10-08: thirty days | @dev-two | 2026-10-05 | 2026-10-07 | decided |
"""


def make_repo(root: Path, *, hostile: bool = False) -> Path:
    """Every source the drafter reads, with one example of each of the eight derived events."""
    write(root, ".sdlc/team.yaml", ROSTER)
    stem = f"0004-duplicate-claim-{KIM}" if hostile else "0004-duplicate-claim-409"
    write(root, f"specs/{stem}.md", spec_text("0004", "duplicate claim 409"))
    write(root, "specs/0009-old-idea.md", spec_text(
        "0009", "old idea", "deferred", reason=HOSTILE_REASON if hostile else "the vendor API is not ready yet",
        scope=("scripts/other.py",)))
    note = HOSTILE_NOTE if hostile else "ok"
    why = HOSTILE_REASON if hostile else "waiting on design"
    jsonl(root, ".sdlc/metrics/sprint-log.jsonl", [
        {"ts": "2026-10-01T09:00:00+00:00", "event": "sprint_new", "sprint": "S07", "by": "@dev-one"},
        {"ts": TS_HANDOFF, "event": "handoff", "spec": "0004", "to": "@dev-two", "by": "@dev-one", "note": note},
        {"ts": TS_VERDICT, "event": "verdict", "spec": "0004", "lane": "eng", "verdict": "accepted",
         "by": "@dev-one", "reason": why},
        {"ts": "2026-10-04T09:00:00+00:00", "event": "carried", "sprint": "S06", "spec": "0005",
         "to_sprint": "S07", "by": "@dev-one", "reason": why},
        {"ts": "2026-10-05T09:00:00+00:00", "event": "dropped", "sprint": "S07", "spec": "0007",
         "by": "@dev-one", "reason": why},
    ])
    log = DECISIONS.replace("thirty days", HOSTILE_REASON if hostile else "thirty days")
    write(root, ".sdlc/decision-log.md", log)
    detail = HOSTILE_DETAIL if hostile else "raw SQL"
    jsonl(root, ".sdlc/metrics/findings-log.jsonl", [
        {"timestamp": "2026-10-09T10:00:00+00:00", "report": "review-report.md", "id": "F-1",
         "category": "sql-injection", "severity": "HIGH", "target": "scripts/claims.py:12", "disposition": "OPEN",
         "fingerprint": "sql-injection:scripts/claims.py", "target_sha": None, "detail": detail},
        {"timestamp": "2026-10-10T10:00:00+00:00", "report": "review-report.md", "id": "F-1",
         "category": "sql-injection", "severity": "HIGH", "target": "scripts/claims.py:12", "disposition": "FIXED",
         "fingerprint": "sql-injection:scripts/claims.py", "target_sha": None, "detail": detail},
    ])
    state = {"version": "1.0", "current_phase": "build", "phases": {
        "2": {"name": "design", "status": "completed", "completed_at": "2026-10-12T09:30:00Z",
              "gate_results": {"passed": 4, "failed": 0, "manual": 0, "signed_off_by": "@dev-one"}},
        "build": {"name": "build", "status": "active", "completed_at": None, "gate_results": {}}}}
    write(root, ".sdlc/state.yaml", yaml.safe_dump(state))
    write(root, ".sdlc/reports/02-design-report.html", "<html></html>")
    write(root, ".sdlc/intake/DOC-007.md", INTAKE_TEXT)
    return root


def draft(root, cfg=None, ledger=None, idmap=None):
    return acm.draft_event_rows(root, ALL_ON if cfg is None else cfg, [] if ledger is None else ledger,
                                IDMAP if idmap is None else idmap)


def by_event(rows) -> dict:
    out: dict = {}
    for r in rows:
        out.setdefault(r["event"], []).append(r)
    return out


def drafts(rows):
    return [r for r in rows if r["status"] == "draft"]


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        h.update(p.relative_to(root).as_posix().encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def commented(key: str, wid: int = 4004) -> dict:
    return {"ts": "2026-10-11T00:00:00Z", "event": "commented", "ref": "sdlc:spec:0004", "work_item": wid,
            "idem_key": key}


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "repo")


# --- the eleven templates ----------------------------------------------------------------------------------------

def test_event_templates_are_the_eleven_design_rows():
    assert tuple(acm.EVENT_TEMPLATES) == sm.COMMENT_EVENTS and len(acm.EVENT_TEMPLATES) == 11
    for event, row in acm.EVENT_TEMPLATES.items():
        assert set(row) == {"default", "fact", "text", "key"}, event
        assert row["default"] in ("on", "off") and isinstance(row["fact"], str) and row["fact"]
        assert row["text"] is None or (isinstance(row["text"], str) and row["text"])
        assert len(row["fact"].split("\n")) <= 2, f"{event}: a fact is at most two lines"


def test_template_defaults_are_the_shipped_starters_event_switches():
    shipped = {e: ("on" if v is True or v == "on" else "off") for e, v in STARTER["comments"]["events"].items()}
    assert {e: r["default"] for e, r in acm.EVENT_TEMPLATES.items()} == shipped
    assert {e for e, r in acm.EVENT_TEMPLATES.items() if r["default"] == "on"} == {
        "handoff", "spec_deferred", "decision_resolved", "sprint_carried"}


def test_template_keys_are_the_models_key_rules():
    assert {e: r["key"] for e, r in acm.EVENT_TEMPLATES.items()} == {
        e: sm.IDEM_KEY_RULES[e][0] for e in sm.COMMENT_EVENTS}


def test_gated_text_variants_exist_only_where_the_design_has_them():
    with_text = {e for e, r in acm.EVENT_TEMPLATES.items() if r["text"] is not None}
    assert with_text == {"handoff", "spec_deferred", "decision_resolved", "sprint_carried", "gate_passed",
                         "verdict_recorded", "sprint_dropped"}
    # the four that carry a person's words say so; the other three are "same" (the text variant is the fact)
    for event in ("spec_deferred", "decision_resolved", "sprint_carried", "sprint_dropped"):
        assert re.search(r"\{(reason|resolution)\}", acm.EVENT_TEMPLATES[event]["text"]), event
        assert not re.search(r"\{(reason|resolution)\}", acm.EVENT_TEMPLATES[event]["fact"]), event
    for event in ("handoff", "gate_passed", "verdict_recorded"):
        assert acm.EVENT_TEMPLATES[event]["text"] == acm.EVENT_TEMPLATES[event]["fact"], event


def test_no_default_fact_names_any_free_text_placeholder():
    free = {"reason", "resolution", "note", "detail", "summary", "title"}
    for event, row in acm.EVENT_TEMPLATES.items():
        names = set(re.findall(r"\{(\w+)\}", row["fact"]))
        assert not names & free, f"{event}: a default template carries {names & free}"


def test_every_template_renders_with_a_value_for_each_placeholder():
    for event, row in acm.EVENT_TEMPLATES.items():
        for variant in (row["fact"], row["text"]):
            if variant is None:
                continue
            values = {n: "x" for n in re.findall(r"\{(\w+)\}", variant)}
            assert acm.fill(variant, values) and "{" not in acm.fill(variant, values)


# Each row: (event, values for the placeholders, key parts, the fact as the design writes it, the gated text or None)
CASES = {
    "handoff": ({"developer": "dev-two", "branch": "spec/0004-duplicate-claim-409", "checker": "dev-one",
                 "path": "specs/0004-duplicate-claim-409.md"},
                {"ref": "sdlc:spec:0004", "ts": TS_HANDOFF},
                "Handed off to @dev-two for build on branch `spec/0004-duplicate-claim-409`; checker @dev-one.\n"
                "Spec: specs/0004-duplicate-claim-409.md", None),
    "spec_deferred": ({"by": "dev-one", "path": "specs/0009-old-idea.md", "reason": "the vendor API is not ready"},
                      {"ref": "sdlc:spec:0009", "reason": "the vendor API is not ready"},
                      "Deferred by @dev-one · reason in specs/0009-old-idea.md#frontmatter",
                      "Deferred by @dev-one: the vendor API is not ready."),
    "decision_resolved": ({"owner": "dev-one", "log": ".sdlc/decision-log.md", "nn": "02", "resolution": "thirty days"},
                          {"decision": "DL-02", "date": "2026-10-08"},
                          "Decided by @dev-one. Rationale: .sdlc/decision-log.md#DL-02",
                          "Decided by @dev-one: thirty days."),
    "sprint_carried": ({"from_sprint": "S06", "to_sprint": "S07", "by": "dev-one", "reason": "waiting on design"},
                       {"ref": "sdlc:spec:0005", "from_sprint": "S06", "to_sprint": "S07"},
                       "Carried from S06 to S07 by @dev-one · reason in .sdlc/sprints/S07.md",
                       "Carried from S06 to S07 by @dev-one: waiting on design."),
    "gate_passed": ({"phase": "2", "signer": "dev-one", "date": "2026-10-12",
                     "report": ".sdlc/reports/02-design-report.html"},
                    {"phase": "2", "signoff_date": "2026-10-12"},
                    "Phase 2 gate passed · signed off by @dev-one · 2026-10-12.\n"
                    "Report: .sdlc/reports/02-design-report.html", None),
    "verdict_recorded": ({"Lens": "Engineering", "verdict": "accepted", "by": "dev-one"},
                         {"ref": "sdlc:spec:0004", "lens": "eng", "verdict": "accepted", "ts": TS_VERDICT},
                         "Engineering review: accepted by @dev-one.", None),
    "finding_disposition": ({"fp": "3fa91c02", "disposition": "split", "by": "dev-two",
                             "split_to": "sdlc:spec:0007"},
                            {"fp": "3fa91c02", "disposition": "split"},
                            "Finding 3fa91c02 marked split by @dev-two · split to sdlc:spec:0007.", None),
    "sprint_dropped": ({"sprint": "S07", "by": "dev-one", "reason": "no longer needed"},
                       {"ref": "sdlc:spec:0007", "sprint": "S07"},
                       "Dropped from S07 by @dev-one · reason in .sdlc/sprints/S07.md",
                       "Dropped from S07 by @dev-one: no longer needed."),
    "review_summary": ({"round": "2", "must": "1", "should": "3",
                        "report": ".sdlc/artifacts/02-design/review-report.md"},
                       {"ref": "sdlc:lifecycle:project", "round": 2},
                       "Review round 2: 1 MUST, 3 SHOULD; summary in .sdlc/artifacts/02-design/review-report.md.",
                       None),
    "pr_linked": ({"pr": "12"}, {"ref": "sdlc:spec:0004", "pr": 12}, "PR !12 linked.", None),
    "spec_merged": ({"pr": "12", "date": "2026-10-12"}, {"ref": "sdlc:spec:0004"},
                    "Merged via PR !12 on 2026-10-12.", None),
}


def test_the_cases_cover_all_eleven_events():
    assert tuple(CASES) == sm.COMMENT_EVENTS


@pytest.mark.parametrize("event", sm.COMMENT_EVENTS)
def test_each_of_the_eleven_templates_renders_the_designs_fact(event):
    values, parts, fact, text = CASES[event]
    assert acm.render_event(event, values) == fact
    ref = parts.get("ref", "sdlc:spec:0004")
    row = acm.event_row(event, ref, 4004, values, parts, cfg=ALL_ON)
    assert row["status"] == "draft" and row["text"] == fact and row["variant"] == "fact"
    assert row["idem_key"] == sm.idem_key(event, **parts)
    assert row["event"] == event and row["origin"] == "event" and set(row) == ROW_KEYS


@pytest.mark.parametrize("event", sm.COMMENT_EVENTS)
def test_the_gated_text_variant_renders_only_when_asked(event):
    values, parts, fact, text = CASES[event]
    if text is None:
        assert acm.render_event(event, values, include_text=True) == fact
        return
    assert acm.render_event(event, values, include_text=True) == text
    assert acm.render_event(event, values, include_text=False) == fact


def test_an_optional_clause_vanishes_with_its_value_and_a_required_one_raises():
    values = {"developer": "dev-two", "branch": "spec/0004-x", "path": "specs/0004-x.md"}
    assert acm.render_event("handoff", values) == ("Handed off to @dev-two for build on branch `spec/0004-x`.\n"
                                                   "Spec: specs/0004-x.md")
    with pytest.raises(acm.MissingValue) as err:
        acm.render_event("handoff", {"branch": "b", "path": "p"})
    assert err.value.name == "developer"


def test_a_value_that_looks_like_a_placeholder_or_a_clause_is_never_expanded():
    values = {"developer": "{branch}", "branch": "[; checker @x]", "path": "{developer}"}
    out = acm.render_event("handoff", values)
    assert out == "Handed off to @{branch} for build on branch `[; checker @x]`.\nSpec: {developer}"


# --- the trailer token and the model's functions ------------------------------------------------------------------

def test_idem_key_and_text_sha_are_the_models():
    assert acm.idem_key is sm.idem_key and acm.text_sha is sm.text_sha
    assert acm.idem_key("handoff", ref="sdlc:spec:0004", ts="2026-10-12T08:14Z") == (
        "handoff:sdlc:spec:0004:2026-10-12T08:14Z")


@pytest.mark.parametrize("mode", sm.TRAILER_MODES)
def test_a_rows_text_sha_survives_every_trailer_mode_and_chars_counts_the_trailer(mode):
    cfg = {"comments": {"trailer": mode}}
    values, parts, fact, text = CASES["verdict_recorded"]
    row = acm.event_row("verdict_recorded", "sdlc:spec:0004", 4004, values, parts, cfg=cfg)
    assert row["trailer"] == mode and row["text"] == fact
    posted = sm.with_trailer(row["text"], "7b2e9d4c1a60", mode)
    assert sm.text_sha(posted) == row["text_sha"] == sm.text_sha(fact)
    assert row["chars"] == len(sm.with_trailer(fact, ZERO, mode))
    if mode != "none":
        assert posted.endswith(" · sprd 7b2e9d4c1a60") and "sdlc 7b2e" not in posted
    assert "· sdlc" not in posted


def test_the_default_trailer_is_hash_and_a_bad_one_falls_back_to_it():
    for cfg in ({}, {"comments": {}}, {"comments": {"trailer": "loud"}}, {"comments": {"trailer": None}}):
        values, parts, *_ = CASES["pr_linked"]
        assert acm.event_row("pr_linked", "sdlc:spec:0004", 4004, values, parts, cfg=cfg)["trailer"] == "hash"


# --- drafting from the repository's ledgers ----------------------------------------------------------------------------

def test_every_derived_event_drafts_one_row_with_the_models_key(repo):
    rows = draft(repo)
    assert all(set(r) == ROW_KEYS for r in rows)
    got = {r["event"]: r for r in rows if r["status"] == "draft"}
    deferred_key = sm.idem_key("spec_deferred", ref="sdlc:spec:0009", reason="the vendor API is not ready yet")
    fp8 = hashlib.sha256(b"sql-injection:scripts/claims.py").hexdigest()[:8]
    assert {e: r["idem_key"] for e, r in got.items()} == {
        "handoff": f"handoff:sdlc:spec:0004:{TS_HANDOFF}",
        "spec_deferred": deferred_key,
        "decision_resolved": "decision:DL-02:decided:2026-10-08",
        "sprint_carried": "carried:sdlc:spec:0005:S06:S07",
        "gate_passed": "gate:2:2026-10-12",
        "verdict_recorded": f"verdict:sdlc:spec:0004:eng:accepted:{TS_VERDICT}",
        "finding_disposition": f"finding:{fp8}:fixed",
        "sprint_dropped": "dropped:sdlc:spec:0007:S07"}
    assert {e: r["work_item"] for e, r in got.items()} == {
        "handoff": 4004, "spec_deferred": 4009, "decision_resolved": 4102, "sprint_carried": 4005,
        "gate_passed": 4900, "verdict_recorded": 4004, "finding_disposition": 4004, "sprint_dropped": 4007}
    assert {e: r["ref"] for e, r in got.items()}["gate_passed"] == "sdlc:lifecycle:project"
    assert all(r["origin"] == "event" and r["kind"] == "comment" and r["action"] == "comment" for r in got.values())
    assert all(r["reason"] is None and r["drafted_by"] is None and r["variant"] == "fact" for r in got.values())
    assert all(r["text_sha"] == sm.text_sha(r["text"]) and bc.HASH_RE.fullmatch(r["text_sha"]) for r in got.values())


def test_the_rows_read_like_the_design_over_a_real_repository(repo):
    got = {r["event"]: r["text"] for r in draft(repo) if r["status"] == "draft"}
    assert got["handoff"] == ("Handed off to @dev-two for build on branch `spec/0004-duplicate-claim-409`; "
                              "checker @dev-one.\nSpec: specs/0004-duplicate-claim-409.md")
    assert got["spec_deferred"] == "Deferred · reason in specs/0009-old-idea.md#frontmatter"
    assert got["decision_resolved"] == "Decided by @dev-one. Rationale: .sdlc/decision-log.md#DL-02"
    assert got["sprint_carried"] == "Carried from S06 to S07 by @dev-one · reason in .sdlc/sprints/S07.md"
    assert got["gate_passed"] == ("Phase 2 gate passed · signed off by @dev-one · 2026-10-12.\n"
                                  "Report: .sdlc/reports/02-design-report.html")
    assert got["verdict_recorded"] == "Engineering review: accepted by @dev-one."
    assert got["sprint_dropped"] == "Dropped from S07 by @dev-one · reason in .sdlc/sprints/S07.md"
    assert re.fullmatch(r"Finding [0-9a-f]{8} marked fixed\.", got["finding_disposition"])


def test_rows_come_in_event_order_and_the_same_inputs_give_the_same_rows(repo):
    first, second = draft(repo), draft(repo)
    assert first == second and json.loads(json.dumps(first)) == first
    order = [sm.COMMENT_EVENTS.index(r["event"]) for r in first]
    assert order == sorted(order)


def test_an_empty_config_drafts_only_the_default_on_events(repo):
    rows = draft(repo, cfg={})
    assert {r["event"] for r in rows} == {"handoff", "spec_deferred", "decision_resolved", "sprint_carried"}
    assert {r["event"] for r in draft(repo, cfg=None)} > {r["event"] for r in rows}


@pytest.mark.parametrize("on,off", [(True, False), ("on", "off")])
def test_the_event_switches_read_yaml_booleans_and_the_words(repo, on, off):
    events = {e: off for e in sm.COMMENT_EVENTS}
    events["verdict_recorded"] = on
    rows = draft(repo, cfg={"comments": {"events": events}})
    assert {r["event"] for r in rows} == {"verdict_recorded"}


def test_a_switched_off_event_makes_no_row_at_all(repo):
    cfg = copy.deepcopy(ALL_ON)
    cfg["comments"]["events"]["gate_passed"] = "off"
    assert "gate_passed" not in {r["event"] for r in draft(repo, cfg=cfg)}


def test_a_ref_the_board_does_not_have_is_a_skipped_row_naming_why(repo):
    rows = by_event(draft(repo, idmap={"sdlc:spec:0004": 4004}))
    carried = rows["sprint_carried"][0]
    assert carried["status"] == "skipped" and carried["reason"] == "not_on_board" and carried["work_item"] is None
    assert carried["text"] is None and carried["ref"] == "sdlc:spec:0005" and "sdlc:spec:0005" in carried["detail"]
    assert carried["reason"] in acm.SKIP_REASONS and carried["reason"] not in bc.COMMENT_REFUSALS
    assert rows["handoff"][0]["status"] == "draft"


def test_nothing_to_read_is_no_rows_not_a_crash(tmp_path):
    assert draft(tmp_path) == [] and draft(tmp_path, cfg={}, idmap={}) == []
    assert acm.draft_event_rows(tmp_path, None, [], {}) == []


def test_drafting_writes_nothing_and_spawns_nothing(repo, az):
    before = tree_hash(repo)
    draft(repo)
    draft(repo, cfg={})
    assert tree_hash(repo) == before and az.calls == []


def test_a_ledger_that_resolves_outside_the_repository_is_not_read(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    jsonl(outside, "log.jsonl", [{"ts": TS_HANDOFF, "event": "dropped", "sprint": "S07", "spec": "0007",
                                  "by": "@dev-one", "reason": "x"}])
    root = tmp_path / "repo"
    (root / ".sdlc/metrics").mkdir(parents=True)
    (root / ".sdlc/metrics/sprint-log.jsonl").symlink_to(outside / "log.jsonl")
    assert draft(root) == []


def test_a_spec_that_resolves_outside_the_repository_is_not_a_spec_and_a_template_is_none(tmp_path):
    outside = tmp_path / "outside"
    write(outside, "0004-x.md", spec_text("0004", "x"))
    root = tmp_path / "repo"
    jsonl(root, ".sdlc/metrics/sprint-log.jsonl", [{"ts": TS_HANDOFF, "event": "handoff", "spec": "0004",
                                                    "to": "@dev-two"},
                                                   {"ts": TS_VERDICT, "event": "handoff", "spec": "0006",
                                                    "to": "@dev-two"}])
    (root / "specs").mkdir()
    (root / "specs/0004-x.md").symlink_to(outside / "0004-x.md")
    write(root, "specs/spec-template.md", spec_text("NNNN", "template"))
    write(root, "specs/0006-legacy.md", spec_text("????", "legacy"))
    rows = draft(root, idmap={"sdlc:spec:0004": 4004, "sdlc:spec:0006": 4006})
    assert [(r["ref"], r["status"], r["reason"]) for r in rows] == [
        ("sdlc:spec:0004", "skipped", "spec_not_found"), ("sdlc:spec:0006", "skipped", "spec_not_found")]


# --- the handoff, deferral, carry, drop and verdict rows -------------------------------------------------------------------

def test_a_handoff_needs_the_spec_file_and_a_developer(repo):
    jsonl(repo, ".sdlc/metrics/sprint-log.jsonl", [
        {"ts": TS_HANDOFF, "event": "handoff", "spec": "0005", "to": "@dev-two", "by": "@dev-one"},
        {"ts": TS_HANDOFF.replace("09:00", "09:01"), "event": "handoff", "spec": "0004", "to": KIM, "by": "@dev-one"},
        {"ts": TS_HANDOFF.replace("09:00", "09:02"), "event": "handoff", "spec": "0004", "to": "Somebody Else",
         "by": "@dev-one"}])
    rows = by_event(draft(repo, idmap={"sdlc:spec:0004": 4004, "sdlc:spec:0005": 4005}))["handoff"]
    assert [(r["status"], r["reason"]) for r in rows] == [
        ("skipped", "spec_not_found"), ("skipped", "missing_field"), ("skipped", "missing_field")]
    assert all(KIM not in json.dumps(r) and "Somebody" not in json.dumps(r) for r in rows)


def test_a_handoff_without_a_checker_drops_the_clause(repo):
    write(repo, "specs/0004-duplicate-claim-409.md", spec_text("0004", "duplicate claim 409", checker=""))
    row = by_event(draft(repo))["handoff"][0]
    assert row["text"] == ("Handed off to @dev-two for build on branch `spec/0004-duplicate-claim-409`.\n"
                           "Spec: specs/0004-duplicate-claim-409.md")


def test_a_deferral_names_who_only_when_the_spec_says_so(repo):
    write(repo, "specs/0009-old-idea.md", spec_text("0009", "old idea", "deferred", reason="not ready yet, sorry",
                                                    extra='deferred_by: "@dev-two"\n'))
    row = by_event(draft(repo))["spec_deferred"][0]
    assert row["text"] == "Deferred by @dev-two · reason in specs/0009-old-idea.md#frontmatter"
    assert row["idem_key"] == sm.idem_key("spec_deferred", ref="sdlc:spec:0009", reason="not ready yet, sorry")


def test_a_deferred_spec_with_no_reason_and_a_live_spec_draft_nothing(repo):
    write(repo, "specs/0009-old-idea.md", spec_text("0009", "old idea", "deferred", reason=""))
    write(repo, "specs/0011-live.md", spec_text("0011", "live", "in-flight", reason="ignored"))
    assert "spec_deferred" not in {r["event"] for r in draft(repo, idmap={**IDMAP, "sdlc:spec:0011": 4011})}


def test_lanes_and_verdict_words_are_closed(repo):
    jsonl(repo, ".sdlc/metrics/sprint-log.jsonl", [
        {"ts": "2026-10-03T09:00:00+00:00", "event": "verdict", "spec": "0004", "lane": "data", "verdict": "n-a",
         "by": "@dev-two", "reason": "no data change"},
        {"ts": "2026-10-03T09:01:00+00:00", "event": "verdict", "spec": "0004", "lane": "security",
         "verdict": "accepted", "by": "@dev-two"},
        {"ts": "2026-10-03T09:02:00+00:00", "event": "verdict", "spec": "0004", "lane": "eng",
         "verdict": "maybe", "by": "@dev-two"}])
    rows = by_event(draft(repo))["verdict_recorded"]
    assert [r["text"] for r in rows] == ["Data review: n-a by @dev-two."]
    assert rows[0]["idem_key"] == "verdict:sdlc:spec:0004:data:n-a:2026-10-03T09:00:00+00:00"


def test_a_carried_and_a_dropped_event_need_real_sprint_ids(repo):
    jsonl(repo, ".sdlc/metrics/sprint-log.jsonl", [
        {"ts": "2026-10-04T09:00:00+00:00", "event": "carried", "sprint": "S06", "spec": "0005", "to_sprint": "next",
         "by": "@dev-one", "reason": "x"},
        {"ts": "2026-10-04T09:00:01+00:00", "event": "carried", "sprint": "S06", "spec": "0005", "to_sprint": "S07",
         "by": "@dev-one", "reason": "x"},
        {"ts": "2026-10-04T09:00:02+00:00", "event": "carried", "sprint": "S07", "spec": "0005", "to_sprint": "S08",
         "reason": "x"},
        {"ts": "2026-10-05T09:00:00+00:00", "event": "dropped", "sprint": "S0X", "spec": "0007", "by": "@dev-one"},
        "not an object", {"event": "dropped"}])
    rows = [r for r in draft(repo) if r["event"] in ("sprint_carried", "sprint_dropped")]
    assert [r["text"] for r in rows] == [
        "Carried from S06 to S07 by @dev-one · reason in .sdlc/sprints/S07.md",
        "Carried from S07 to S08 · reason in .sdlc/sprints/S08.md"]


def test_a_repeated_carry_between_the_same_sprints_is_one_row(repo):
    event = {"ts": "2026-10-04T09:00:00+00:00", "event": "carried", "sprint": "S06", "spec": "0005",
             "to_sprint": "S07", "by": "@dev-one", "reason": "x"}
    jsonl(repo, ".sdlc/metrics/sprint-log.jsonl", [event, {**event, "ts": "2026-10-04T10:00:00+00:00"}])
    assert len([r for r in draft(repo) if r["event"] == "sprint_carried"]) == 1


# --- decisions ----------------------------------------------------------------------------------------------------------

def test_a_decision_row_names_the_decider_then_the_owner_and_needs_a_date(repo):
    log = DECISIONS + ("| DL-03 | Which vendor? | @dev-two | 2026-10-05 | 2026-10-07 | decided |\n"
                       "| DL-04 | Cut scope? — decided by Somebody on 2026-10-09: yes | @dev-one | 2026-10-05 | "
                       "2026-10-07 | decided |\n"
                       "| DL-05 | Closed without a word | @dev-one | 2026-10-05 | 2026-10-07 | cancelled |\n")
    write(repo, ".sdlc/decision-log.md", log)
    idmap = {f"sdlc:decision:0{n}": 4100 + n for n in range(1, 6)}
    rows = {r["ref"]: r for r in by_event(draft(repo, idmap=idmap))["decision_resolved"]}
    assert set(rows) == {"sdlc:decision:02", "sdlc:decision:03", "sdlc:decision:04"}
    assert rows["sdlc:decision:02"]["text"] == "Decided by @dev-one. Rationale: .sdlc/decision-log.md#DL-02"
    assert (rows["sdlc:decision:03"]["status"], rows["sdlc:decision:03"]["reason"]) == ("skipped", "no_decided_date")
    assert rows["sdlc:decision:04"]["text"] == "Decided by @dev-one. Rationale: .sdlc/decision-log.md#DL-04"
    assert rows["sdlc:decision:04"]["idem_key"] == "decision:DL-04:decided:2026-10-09"


def test_the_real_mini_repository_drafts_its_carry_and_its_decision(tmp_path):
    here = Path(__file__).resolve().parent / "fixtures" / "boards_repo"
    before = tree_hash(here)
    rows = acm.draft_event_rows(here, {}, [], {"sdlc:spec:0005": 5, "sdlc:decision:02": 102})
    assert tree_hash(here) == before
    texts = {r["event"]: r["text"] for r in rows if r["status"] == "draft"}
    assert texts["decision_resolved"] == "Decided by @dev-one. Rationale: .sdlc/decision-log.md#DL-02"
    assert texts["sprint_carried"].startswith("Carried from S0")
    assert [r["idem_key"] for r in rows if r["event"] == "sprint_carried"] == [
        "carried:sdlc:spec:0005:S06:S07", "carried:sdlc:spec:0005:S05:S06"]


# --- gate sign-offs and the Lifecycle item -------------------------------------------------------------------------------

def test_gate_passed_on_with_no_lifecycle_item_is_a_skipped_row(repo):
    idmap = {k: v for k, v in IDMAP.items() if ":lifecycle:" not in k}
    rows = [r for r in draft(repo, idmap=idmap) if r["event"] == "gate_passed"]
    assert len(rows) == 1
    row = rows[0]
    assert (row["status"], row["reason"], row["work_item"], row["text"]) == ("skipped", "no_lifecycle_item", None, None)
    assert row["idem_key"] == "gate:2:2026-10-12"


def test_gate_passed_targets_only_the_lifecycle_item(repo):
    idmap = {**IDMAP, "sdlc:lifecycle:a-first": 4800}
    rows = [r for r in draft(repo, idmap=idmap) if r["event"] == "gate_passed"]
    assert [(r["ref"], r["work_item"]) for r in rows] == [("sdlc:lifecycle:a-first", 4800)]
    # a spec item is never the gate's target, however many there are
    assert all(not r["ref"].startswith("sdlc:spec:") for r in rows)


def test_a_gate_row_needs_a_completed_signed_off_phase_with_a_date(repo):
    state = {"phases": {
        "1": {"status": "completed", "completed_at": "2026-10-01T00:00:00Z", "gate_results": {"signed_off_by": ""}},
        "2": {"status": "completed", "completed_at": "2026-10-02T00:00:00Z", "gate_results": {"signed_off_by": "Kim"}},
        "3": {"status": "completed", "completed_at": None, "gate_results": {"signed_off_by": "@dev-one"}},
        "build": {"status": "active", "completed_at": "2026-10-04T00:00:00Z",
                  "gate_results": {"signed_off_by": "@dev-one"}},
        "7": {"status": "completed", "completed_at": "2026-10-05T00:00:00Z",
              "gate_results": {"signed_off_by": DEV_ONE_EMAIL}}}}
    write(repo, ".sdlc/state.yaml", yaml.safe_dump(state))
    rows = [r for r in draft(repo) if r["event"] == "gate_passed"]
    assert [(r["status"], r["reason"], r["idem_key"]) for r in rows] == [
        ("draft", None, "gate:2:2026-10-02"), ("skipped", "no_signoff_date", None),
        ("draft", None, "gate:7:2026-10-05")]
    # an unknown name is still a sign-off: only the clause naming a handle disappears
    assert rows[0]["text"].startswith("Phase 2 gate passed · signed off · 2026-10-02.")
    # an address resolves through the roster to its handle and is never printed
    assert rows[2]["text"] == "Phase 7 gate passed · signed off by @dev-one · 2026-10-05."
    assert not any(DEV_ONE_EMAIL in json.dumps(r) for r in rows)


def test_the_report_line_appears_only_when_the_report_exists(repo):
    (repo / ".sdlc/reports/02-design-report.html").unlink()
    row = [r for r in draft(repo) if r["event"] == "gate_passed"][0]
    assert row["text"] == "Phase 2 gate passed · signed off by @dev-one · 2026-10-12."


# --- findings ----------------------------------------------------------------------------------------------------------

def finding(fp, disposition, target="scripts/claims.py:3", stamp="2026-10-10T10:00:00+00:00", **extra):
    return {"timestamp": stamp, "report": "review-report.md", "id": "F-9", "category": "cat", "severity": "HIGH",
            "target": target, "disposition": disposition, "fingerprint": fp, "target_sha": None,
            "detail": HOSTILE_DETAIL, **extra}


def test_a_finding_comment_uses_the_latest_disposition_and_never_the_finding_text(repo):
    jsonl(repo, ".sdlc/metrics/findings-log.jsonl", [
        finding("a:scripts/claims.py", "OPEN"),
        finding("a:scripts/claims.py", "SPLIT", split_to="0007", owner="@dev-two"),
        finding("b:scripts/claims.py", "OPEN"),
        finding("c:scripts/claims.py", "ACCEPTED_RISK", approver="@dev-one", date="2026-10-11", reason="r",
                review_condition="rc")])
    rows = [r for r in draft(repo) if r["event"] == "finding_disposition"]
    texts = [r["text"] for r in rows]
    assert len(rows) == 2          # b is still OPEN: no one has decided anything about it
    assert re.fullmatch(r"Finding [0-9a-f]{8} marked split by @dev-two · split to sdlc:spec:0007\.", texts[0])
    assert re.fullmatch(r"Finding [0-9a-f]{8} marked accepted risk by @dev-one\.", texts[1])
    assert not any("DETAIL-SECRET" in json.dumps(r) or "cat" in r["text"] for r in rows)
    assert {r["idem_key"].split(":")[2] for r in rows} == {"split", "accepted-risk"}


def test_a_mislabelled_finding_disposition_is_a_skipped_row(repo):
    jsonl(repo, ".sdlc/metrics/findings-log.jsonl", [finding("a:scripts/claims.py", "SPLIT"),
                                                     finding("b:scripts/claims.py", "ACCEPTED_RISK", approver="Claude",
                                                             date="2026-10-11", reason="r", review_condition="rc")])
    rows = [r for r in draft(repo) if r["event"] == "finding_disposition"]
    assert [(r["status"], r["reason"], r["text"]) for r in rows] == [("skipped", "mislabelled_disposition", None)] * 2


def test_a_finding_needs_exactly_one_live_spec_that_owns_the_file(repo):
    jsonl(repo, ".sdlc/metrics/findings-log.jsonl", [finding("a:scripts/claims.py", "FIXED"),
                                                     finding("z:lib/none.py", "FIXED", target="lib/none.py")])
    rows = [r for r in draft(repo) if r["event"] == "finding_disposition"]
    assert [(r["status"], r["reason"]) for r in rows] == [("draft", None), ("skipped", "not_attributable")]
    write(repo, "specs/0010-twin.md", spec_text("0010", "twin", "ready"))          # a second live spec, same file
    write(repo, "specs/0003-done.md", spec_text("0003", "done", "merged"))         # a merged one never counts
    rows = [r for r in draft(repo, idmap={**IDMAP, "sdlc:spec:0010": 4010}) if r["event"] == "finding_disposition"]
    assert [(r["status"], r["reason"]) for r in rows] == [("skipped", "not_attributable")] * 2


# --- who a name is ---------------------------------------------------------------------------------------------------

def test_a_name_becomes_a_handle_only_through_the_roster(repo):
    who = [DEV_ONE_EMAIL, "Person Two", "dev-two", "stranger", KIM, "@new-person"]
    jsonl(repo, ".sdlc/metrics/sprint-log.jsonl", [
        {"ts": f"2026-10-05T09:00:0{i}+00:00", "event": "dropped", "sprint": f"S{7 + i:02d}", "spec": "0007", "by": by}
        for i, by in enumerate(who)])
    rows = [r for r in draft(repo) if r["event"] == "sprint_dropped"]
    assert [r["text"].split(" · ")[0] for r in rows] == [
        "Dropped from S07 by @dev-one", "Dropped from S08 by @dev-two", "Dropped from S09 by @dev-two",
        "Dropped from S10", "Dropped from S11", "Dropped from S12 by @new-person"]
    assert not any(KIM in json.dumps(r) or DEV_ONE_EMAIL in json.dumps(r) for r in rows)


def test_without_a_roster_only_a_well_formed_handle_is_named(tmp_path):
    root = tmp_path / "r"
    jsonl(root, ".sdlc/metrics/sprint-log.jsonl", [
        {"ts": "2026-10-05T09:00:00+00:00", "event": "dropped", "sprint": "S07", "spec": "0007", "by": "@kim"},
        {"ts": "2026-10-05T09:00:01+00:00", "event": "dropped", "sprint": "S08", "spec": "0007", "by": "kim"}])
    rows = draft(root)
    assert [r["text"].split(" · ")[0] for r in rows] == ["Dropped from S07 by @kim", "Dropped from S08"]


# --- one key, one comment -----------------------------------------------------------------------------------------------

def test_a_key_already_on_a_commented_line_is_never_drafted_again(repo):
    first = draft(repo)
    keys = [r["idem_key"] for r in first if r["status"] == "draft"]
    assert len(keys) == 8 and len(set(keys)) == 8
    ledger = [commented(k, r["work_item"]) for k, r in zip(keys, [r for r in first if r["status"] == "draft"])]
    assert draft(repo, ledger=ledger) == []
    # one key at a time: exactly that row goes, the rest stay
    for k in keys:
        again = draft(repo, ledger=[commented(k)])
        assert k not in {r["idem_key"] for r in again} and len(again) == 7
    # and a skipped row has no key on the board, so it is listed again
    assert len(draft(repo, idmap={})) == len(first)


def test_a_comment_refused_line_and_a_foreign_line_do_not_suppress_a_key(repo):
    key = [r["idem_key"] for r in draft(repo)][0]
    ledger = [{"ts": "2026-10-11T00:00:00Z", "event": "comment_refused", "ref": "sdlc:spec:0004", "idem_key": key},
              {"ts": "2026-10-11T00:00:00Z", "event": "planned", "idem_key": key}, "junk", {"event": "commented"}]
    assert key in {r["idem_key"] for r in draft(repo, ledger=ledger)}


def test_two_identical_ledger_lines_draft_one_row(repo):
    line = {"ts": TS_HANDOFF, "event": "handoff", "spec": "0004", "to": "@dev-two", "by": "@dev-one"}
    jsonl(repo, ".sdlc/metrics/sprint-log.jsonl", [line, dict(line)])
    assert len([r for r in draft(repo) if r["event"] == "handoff"]) == 1


# --- the budget ----------------------------------------------------------------------------------------------------------

def test_a_full_budget_is_a_refused_row_named_budget(repo):
    ledger = [commented(f"comment:sdlc:spec:0004:{i:012x}") for i in range(50)]
    row = by_event(draft(repo, ledger=ledger))["handoff"][0]
    assert (row["status"], row["reason"]) == ("refused", "budget") and row["reason"] in bc.COMMENT_REFUSALS
    assert row["budget"] == {"used": 50, "of": 50, "position": None}
    assert row["text"] is not None and row["idem_key"].startswith("handoff:")
    # another item on the board still has all its room
    assert by_event(draft(repo, ledger=ledger))["sprint_carried"][0]["status"] == "draft"


def test_the_last_free_comment_on_an_item_is_drafted_and_says_its_place(repo):
    ledger = [commented(f"comment:sdlc:spec:0004:{i:012x}") for i in range(49)]
    handoff = by_event(draft(repo, ledger=ledger))["handoff"][0]
    assert handoff["status"] == "draft" and handoff["budget"] == {"used": 49, "of": 50, "position": 50}
    verdict = by_event(draft(repo, ledger=ledger))["verdict_recorded"][0]   # the next row on item 4004
    assert (verdict["status"], verdict["reason"]) == ("refused", "budget")


def test_rows_drafted_in_the_same_call_spend_the_same_budget(repo):
    cfg = {"comments": {"events": {e: "on" for e in sm.COMMENT_EVENTS}, "per_item_budget": 1}}
    rows = [r for r in draft(repo, cfg=cfg) if r["work_item"] == 4004]      # handoff, verdict, finding on item 4004
    assert [(r["event"], r["status"], r["reason"]) for r in rows] == [
        ("handoff", "draft", None), ("verdict_recorded", "refused", "budget"), ("finding_disposition", "refused", "budget")]
    assert [r["budget"]["position"] for r in rows] == [1, None, None]


def test_a_bad_budget_or_limit_in_the_config_falls_back_to_the_default(repo):
    for bad in (0, -1, "many", True, None, 2.5):
        cfg = {"comments": {"events": ALL_ON["comments"]["events"], "per_item_budget": bad, "max_chars": bad}}
        assert by_event(draft(repo, cfg=cfg))["handoff"][0]["budget"]["of"] == 50


def test_max_chars_refuses_a_row_whose_posted_text_is_too_long(repo):
    cfg = {"comments": {"events": ALL_ON["comments"]["events"], "max_chars": 60}}
    row = by_event(draft(repo, cfg=cfg))["handoff"][0]
    assert (row["status"], row["reason"]) == ("refused", "max_chars") and row["reason"] in bc.COMMENT_REFUSALS
    assert row["chars"] > 60


def test_a_comment_on_a_deleted_or_retyped_item_needs_its_drift_disposed_first(repo):
    ledger = [{"ts": "2026-10-11T00:00:00Z", "event": "observed", "ref": "sdlc:spec:0004", "work_item": 4004,
               "class": "RETYPED"},
              {"ts": "2026-10-11T00:00:00Z", "event": "observed", "ref": "sdlc:spec:0007", "work_item": 4007,
               "class": "DELETED_IN_ADO"},
              {"ts": "2026-10-12T00:00:00Z", "event": "observed", "ref": "sdlc:spec:0007", "work_item": 4007,
               "class": "IN_SYNC"}]
    rows = by_event(draft(repo, ledger=ledger))
    assert (rows["handoff"][0]["status"], rows["handoff"][0]["reason"]) == ("refused", "needs_disposition")
    assert rows["sprint_dropped"][0]["status"] == "draft"        # the later observation is IN_SYNC: nothing to dispose


# --- the gated text variants --------------------------------------------------------------------------------------------

def cfg_text(reviewed="@dev-one", on=True):
    return {"pii_reviewed_by": reviewed, "comments": {"include_text": on, "events": ALL_ON["comments"]["events"]}}


def test_with_include_text_false_no_reason_text_appears_anywhere(repo):
    write(repo, "specs/0009-old-idea.md", spec_text("0009", "old idea", "deferred", reason="REASON-ONE not ready"))
    write(repo, ".sdlc/decision-log.md", DECISIONS.replace("thirty days", "RESOLUTION-TWO"))
    jsonl(repo, ".sdlc/metrics/sprint-log.jsonl", [
        {"ts": "2026-10-04T09:00:00+00:00", "event": "carried", "sprint": "S06", "spec": "0005", "to_sprint": "S07",
         "by": "@dev-one", "reason": "REASON-THREE"},
        {"ts": "2026-10-05T09:00:00+00:00", "event": "dropped", "sprint": "S07", "spec": "0007", "by": "@dev-one",
         "reason": "REASON-FOUR"}])
    for cfg in (ALL_ON, {"comments": {"include_text": False, "events": ALL_ON["comments"]["events"]}},
                cfg_text(reviewed=None), cfg_text(reviewed="  "), cfg_text(on="true")):
        blob = json.dumps(draft(repo, cfg=cfg))
        assert not re.search(r"REASON-|RESOLUTION-", blob), cfg
    assert all(r["variant"] == "fact" for r in draft(repo, cfg=cfg_text(reviewed=None)))


def test_include_text_with_a_named_reviewer_adds_the_clipped_text_variants(repo):
    write(repo, "specs/0009-old-idea.md", spec_text("0009", "old idea", "deferred", reason="REASON-ONE not ready."))
    write(repo, ".sdlc/decision-log.md", DECISIONS.replace("thirty days", "RESOLUTION-TWO"))
    long = "L" * 400
    jsonl(repo, ".sdlc/metrics/sprint-log.jsonl", [
        {"ts": "2026-10-04T09:00:00+00:00", "event": "carried", "sprint": "S06", "spec": "0005", "to_sprint": "S07",
         "by": "@dev-one", "reason": long},
        {"ts": "2026-10-05T09:00:00+00:00", "event": "dropped", "sprint": "S07", "spec": "0007", "by": "@dev-one",
         "reason": "REASON-FOUR\nsecond line\t\x1b[31mred"},
        {"ts": TS_VERDICT, "event": "verdict", "spec": "0004", "lane": "eng", "verdict": "accepted",
         "by": "@dev-one", "reason": "REASON-FIVE"}])
    rows = by_event(draft(repo, cfg=cfg_text()))
    assert rows["spec_deferred"][0]["text"] == "Deferred: REASON-ONE not ready."
    assert rows["spec_deferred"][0]["variant"] == "text"
    assert rows["decision_resolved"][0]["text"] == "Decided by @dev-one: RESOLUTION-TWO."
    carried = rows["sprint_carried"][0]["text"]
    assert carried == "Carried from S06 to S07 by @dev-one: " + "L" * 159 + "…."
    assert rows["sprint_dropped"][0]["text"] == "Dropped from S07 by @dev-one: REASON-FOUR second line [31mred."
    assert not re.search(r"[\x00-\x08\x0b-\x1f\x7f]", json.dumps(rows["sprint_dropped"][0], ensure_ascii=False))
    # an event with no text variant stays a fact
    assert [r["variant"] for r in rows["verdict_recorded"] + rows["finding_disposition"]] == ["fact", "fact"]
    assert "REASON-FIVE" not in json.dumps(rows)
    # the idempotency key is the same either way: the variant is a posting choice, not a different comment
    assert rows["sprint_carried"][0]["idem_key"] == by_event(draft(repo))["sprint_carried"][0]["idem_key"]


def test_a_decision_with_no_resolution_text_stays_a_fact_under_include_text(repo):
    write(repo, ".sdlc/decision-log.md", DECISIONS.replace(": thirty days", ":"))
    row = by_event(draft(repo, cfg=cfg_text()))["decision_resolved"][0]
    assert row["variant"] == "fact" and row["text"].startswith("Decided by @dev-one. Rationale:")


# --- the hostile repository -------------------------------------------------------------------------------------------

LEAKS = ("Acme", "DOC-007", "salary", "NOTE-SECRET", "DETAIL-SECRET", "INTAKE-CLIENT-TEXT", "found raw SQL",
         "sql-injection", "call the client")


@pytest.mark.parametrize("cfg", [ALL_ON, cfg_text(), cfg_text(reviewed=None), {}], ids=["fact", "text", "unreviewed", "empty"])
def test_a_hostile_ledger_leaks_no_email_finding_or_intake_text_into_any_row(tmp_path, cfg):
    root = make_repo(tmp_path / "hostile", hostile=True)
    before = tree_hash(root)
    rows = draft(root, cfg=cfg)
    assert tree_hash(root) == before and rows
    for row in rows:
        blob = json.dumps(row, ensure_ascii=False)
        assert not bc.EMAIL_RE.search(blob), row
        assert not bc.GUID_RE.search(blob)
        if cfg.get("comments", {}).get("include_text") is not True or not cfg.get("pii_reviewed_by"):
            assert not any(leak in blob for leak in LEAKS), (row["event"], blob)
        else:  # even with the gate open, only a reason or a resolution may appear: never a note, a finding or intake text
            assert not any(leak in blob for leak in ("NOTE-SECRET", "DETAIL-SECRET", "INTAKE-CLIENT-TEXT",
                                                     "found raw SQL", "sql-injection", "call the client")), blob
    for row in rows:
        if row["text"] is not None:
            assert not bc.EMAIL_RE.search(row["text"])


def test_a_hostile_spec_name_with_an_address_is_refused_and_its_text_is_dropped(tmp_path):
    root = make_repo(tmp_path / "hostile", hostile=True)
    row = by_event(draft(root))["handoff"][0]
    assert (row["status"], row["reason"]) == ("refused", "email_in_text") and row["reason"] in bc.COMMENT_REFUSALS
    assert row["text"] is None and row["chars"] is None and row["text_sha"] is None
    assert KIM not in json.dumps(row) and row["idem_key"].startswith("handoff:")


def test_an_address_inside_an_unlocked_reason_is_refused_not_posted(tmp_path):
    root = make_repo(tmp_path / "hostile", hostile=True)
    rows = by_event(draft(root, cfg=cfg_text()))
    for event in ("spec_deferred", "decision_resolved", "sprint_carried", "sprint_dropped"):
        row = rows[event][0]
        assert (row["status"], row["reason"], row["text"]) == ("refused", "email_in_text", None), event
    # the same rows with the gate shut are plain facts and post fine
    plain = by_event(draft(root, cfg=ALL_ON))
    assert all(plain[e][0]["status"] == "draft" for e in ("spec_deferred", "decision_resolved", "sprint_carried"))


def test_every_refusal_and_skip_a_drafter_gives_is_in_its_closed_set(tmp_path):
    root = make_repo(tmp_path / "hostile", hostile=True)
    ledger = [commented(f"comment:sdlc:spec:0004:{i:012x}") for i in range(50)]
    rows = draft(root, cfg=cfg_text(), ledger=ledger) + draft(root, idmap={}) + draft(root, cfg={"comments": {
        "events": ALL_ON["comments"]["events"], "max_chars": 10}})
    refusals = {r["reason"] for r in rows if r["status"] == "refused"}
    skips = {r["reason"] for r in rows if r["status"] == "skipped"}
    assert refusals and skips and refusals <= set(bc.COMMENT_REFUSALS) and skips <= set(acm.SKIP_REASONS)
    assert not set(acm.SKIP_REASONS) & set(bc.COMMENT_REFUSALS)
    assert all(r["reason"] is None for r in rows if r["status"] == "draft")
    # a refusal's or skip's detail is a fixed sentence: it never echoes the ledger's own words
    assert not any(any(leak in (r["detail"] or "") for leak in LEAKS) for r in rows)


def test_a_malformed_ledger_line_is_ignored_not_echoed(repo):
    write(repo, ".sdlc/metrics/sprint-log.jsonl",
          "{not json\n\n[1,2]\n" + json.dumps({"ts": "bad ts with spaces", "event": "handoff", "spec": "0004",
                                                "to": "@dev-two"}) + "\n"
          + json.dumps({"ts": TS_HANDOFF, "event": "handoff", "spec": "../../etc", "to": "@dev-two"}) + "\n")
    rows = draft(repo)
    handoffs = [r for r in rows if r["event"] == "handoff"]
    assert [(r["status"], r["reason"]) for r in handoffs] == [("skipped", "unkeyable")]
    assert "bad ts" not in json.dumps(rows) and "../../etc" not in json.dumps(rows)


# --- an ad hoc comment ----------------------------------------------------------------------------------------------------

def ad_hoc(message="Looks good to me", ref="sdlc:spec:0004", wid=4004, **kw):
    kw.setdefault("by", "@dev-one")
    kw.setdefault("mentions", [])
    kw.setdefault("cfg", {})
    return acm.ad_hoc_row(ref, wid, message, **kw)


def test_an_ad_hoc_row_carries_the_exact_text_its_key_and_its_budget_place():
    row = ad_hoc("Looks good to me", ledger=[commented("comment:sdlc:spec:0004:aaaaaaaaaaaa") for _ in range(3)])
    assert set(row) == ROW_KEYS
    assert (row["status"], row["origin"], row["event"], row["variant"]) == ("draft", "ad_hoc", None, None)
    assert row["text"] == "Looks good to me" and row["chars"] == len("Looks good to me")
    assert row["idem_key"] == sm.idem_key("ad_hoc", ref="sdlc:spec:0004", text="Looks good to me")
    assert row["text_sha"] == sm.text_sha("Looks good to me") and (row["ref"], row["work_item"]) == ("sdlc:spec:0004", 4004)
    assert row["target"] == "sdlc:spec:0004" and row["budget"] == {"used": 3, "of": 50, "position": 4}
    assert row["trailer"] == "none" and row["drafted_by"] is None and row["mentions"] == [] and row["format"] == "markdown"


def test_an_ad_hoc_comment_on_a_bare_work_item_has_no_ref():
    row = ad_hoc("hello", ref="#4521", wid=4521)
    assert (row["ref"], row["target"], row["work_item"]) == (None, "#4521", 4521)
    assert row["idem_key"] == sm.idem_key("ad_hoc", ref="#4521", text="hello")
    with pytest.raises(ValueError):
        ad_hoc("hello", ref="#4521", wid=4522)


def test_an_address_in_the_message_is_refused_email_in_text_and_the_text_is_dropped():
    row = ad_hoc(f"please ask {KIM} about it")
    assert (row["status"], row["reason"]) == ("refused", "email_in_text") and row["reason"] in bc.COMMENT_REFUSALS
    assert row["text"] is None and row["text_sha"] is None and KIM not in json.dumps(row)


@pytest.mark.parametrize("text", [f"ping {AT_CORP} now", f"see {AT_ORG}", f"write to {DEV_ONE_EMAIL}"])
def test_any_at_domain_form_is_email_in_text(text):
    assert ad_hoc(text)["reason"] == "email_in_text"


def test_an_at_handle_is_not_an_address():
    assert ad_hoc("thanks @dev-two")["status"] == "draft"


@pytest.mark.parametrize("by", ["Claude", "shepherd:feature-architect", "data-analyst", "an AI assistant", "Copilot"])
def test_an_ai_by_is_refused_ai_actor_with_zero_text_kept_out_of_the_row(by):
    row = ad_hoc(by=by)
    assert (row["status"], row["reason"]) == ("refused", "ai_actor") and row["reason"] in bc.COMMENT_REFUSALS
    assert sm.ai_by(by, acm.AGENT_STEMS)


def test_agent_stems_are_every_agent_file():
    assert acm.AGENT_STEMS == STEMS and "feature-architect" in acm.AGENT_STEMS


def test_an_empty_message_or_a_blank_by_is_an_illegal_request_not_a_refusal():
    for message in ("", "   \n"):
        with pytest.raises(ValueError):
            ad_hoc(message)
    with pytest.raises(ValueError):
        ad_hoc(by="  ")
    with pytest.raises(ValueError):
        ad_hoc(by=None)


def test_a_ref_or_work_item_that_is_not_one_is_an_illegal_request():
    for ref in ("spec 4", "sdlc:spec", "#0", "#abc", "", None):
        with pytest.raises(ValueError):
            ad_hoc(ref=ref)
    for wid in (0, -1, "4004", True, None):
        with pytest.raises(ValueError):
            ad_hoc(wid=wid)


def test_the_event_flag_is_a_closed_set():
    assert ad_hoc(event="handoff")["event"] == "handoff"
    row = ad_hoc(event="standup_note")
    assert (row["status"], row["reason"]) == ("refused", "event_unknown")
    assert ad_hoc(event="handoff")["idem_key"] == ad_hoc()["idem_key"]      # an ad hoc key is the text's, whatever it is called


def test_max_chars_and_the_budget_refuse_an_ad_hoc_row():
    cfg = {"comments": {"max_chars": 20, "trailer": "hash"}}
    assert ad_hoc("x" * 21, cfg=cfg)["reason"] == "max_chars" and ad_hoc("x" * 20, cfg=cfg)["status"] == "draft"
    full = [commented("comment:sdlc:spec:0004:aaaaaaaaaaaa") for _ in range(50)]
    assert ad_hoc(ledger=full)["reason"] == "budget"
    assert ad_hoc(ledger=full, cfg={"comments": {"per_item_budget": 51}})["status"] == "draft"
    elsewhere = [commented("comment:sdlc:spec:0004:aaaaaaaaaaaa", wid=1) for _ in range(50)]
    assert ad_hoc(ledger=elsewhere)["status"] == "draft"


def test_the_default_limits_are_the_starters_and_the_starters_are_what_the_defaults_say():
    block = STARTER["comments"]
    assert (acm.DEFAULT_MAX_CHARS, acm.DEFAULT_BUDGET) == (block["max_chars"], block["per_item_budget"]) == (4000, 50)
    assert ad_hoc("x" * 4000)["status"] == "draft" and ad_hoc("x" * 4001)["reason"] == "max_chars"
    # a trailed row counts its trailer: 4000 less the 20 characters of ` · sprd <12hex>`
    assert ad_hoc("x" * 3980, drafted_by="claude")["status"] == "draft"
    assert ad_hoc("x" * 3981, drafted_by="claude")["reason"] == "max_chars"


def test_without_a_ledger_the_budget_is_not_measured_and_says_so():
    row = ad_hoc()
    assert row["status"] == "draft" and row["budget"] == {"used": None, "of": 50, "position": None}
    assert any("budget not checked" in n for n in row["notes"])


def test_a_deleted_or_retyped_item_refuses_an_ad_hoc_comment_needs_disposition():
    for cls in ("DELETED_IN_ADO", "RETYPED"):
        row = ad_hoc(drift_class=cls)
        assert (row["status"], row["reason"]) == ("refused", "needs_disposition")
    seen = [{"ts": "2026-10-11T00:00:00Z", "event": "observed", "ref": "sdlc:spec:0004", "work_item": 4004,
             "class": "RETYPED"}]
    assert ad_hoc(ledger=seen)["reason"] == "needs_disposition"
    assert ad_hoc("hi", ref="#4004", wid=4004, ledger=seen)["reason"] == "needs_disposition"
    assert ad_hoc(drift_class="CONFLICT")["status"] == "draft"


def test_the_refusals_come_in_the_models_order():
    assert ad_hoc(f"{KIM}", by="Claude", event="nope", drift_class="RETYPED")["reason"] == "ai_actor"
    assert ad_hoc(f"{KIM}", event="nope", drift_class="RETYPED")["reason"] == "event_unknown"
    assert ad_hoc(f"{KIM}", drift_class="RETYPED")["reason"] == "needs_disposition"
    assert ad_hoc(f"{KIM}")["reason"] == "email_in_text"
    long = "x" * 5000 + f" {AT_CORP}"
    assert ad_hoc(long)["reason"] == "email_in_text"           # the domain form outranks length, as an address does


def test_a_mention_is_plain_text_that_says_it_will_not_notify():
    row = ad_hoc("can you look", mentions=["@priya-n", "@kim"], ledger=[])
    assert row["text"] == "can you look @priya-n @kim"
    assert row["mentions"] == ["@priya-n", "@kim"]
    assert row["notes"] == ["mention @priya-n: text only — will not notify (B5)",
                            "mention @kim: text only — will not notify (B5)"]
    already = ad_hoc("thanks @priya-n, and @kim", mentions=["@priya-n", "@kim", "@priya-n"], ledger=[])
    assert already["text"] == "thanks @priya-n, and @kim" and already["mentions"] == ["@priya-n", "@kim"]


def test_a_mention_that_is_an_address_is_refused_and_one_that_is_not_a_handle_is_illegal():
    assert ad_hoc(mentions=[KIM])["reason"] == "email_in_text"
    assert ad_hoc(mentions=[AT_CORP])["reason"] == "email_in_text"
    assert ad_hoc(mentions=["@" + KIM])["reason"] == "email_in_text"
    for bad in ("kim", "@", "@-kim", "@kim lee", "", None, 5):
        with pytest.raises(ValueError):
            ad_hoc(mentions=[bad])


def test_a_human_typed_row_has_no_trailer_and_an_ai_proposed_one_takes_the_configured_trailer():
    cfg = {"comments": {"trailer": "drafted"}}
    assert ad_hoc(cfg=cfg)["trailer"] == "none"
    proposed = ad_hoc(cfg=cfg, drafted_by="feature-architect")
    assert (proposed["trailer"], proposed["drafted_by"]) == ("drafted", "feature-architect")
    assert ad_hoc(cfg={}, drafted_by="shepherd:claude")["drafted_by"] == "claude"
    assert ad_hoc(cfg={}, drafted_by="claude")["trailer"] == "hash"
    assert proposed["chars"] == len(sm.with_trailer("Looks good to me", ZERO, "drafted"))
    for bad in ("Kim Lee", KIM, "", "a" * 80):
        with pytest.raises(ValueError):
            ad_hoc(drafted_by=bad)


def test_an_ad_hoc_key_already_on_the_board_is_a_skipped_row_not_a_second_post():
    key = sm.idem_key("ad_hoc", ref="sdlc:spec:0004", text="Looks good to me")
    row = ad_hoc(ledger=[commented(key)])
    assert (row["status"], row["reason"], row["text"]) == ("skipped", "already_posted", None)
    assert row["idem_key"] == key and row["reason"] in acm.SKIP_REASONS
    assert ad_hoc("a different message", ledger=[commented(key)])["status"] == "draft"


def test_an_ad_hoc_message_is_taken_as_typed_apart_from_line_endings_and_edges():
    row = ad_hoc("  line one\r\nline two  \n")
    assert row["text"] == "line one\nline two"
    assert row["text_sha"] == sm.text_sha("line one\nline two")
    assert row["chars"] == len("line one\nline two")


def test_a_typed_trailer_in_a_message_is_the_persons_text_and_stays_in_the_key():
    row = ad_hoc("see you · sprd 7b2e9d4c1a60")
    assert row["status"] == "draft" and row["text_sha"] == sm.text_sha("see you")
    assert row["idem_key"] == sm.idem_key("ad_hoc", ref="sdlc:spec:0004", text="see you · sprd 7b2e9d4c1a60")


def test_an_ad_hoc_row_never_spawns_or_writes(az):
    ad_hoc()
    ad_hoc(ledger=[])
    assert az.calls == []


# --- hygiene the gates also check -------------------------------------------------------------------------------------------

def test_the_module_has_no_subprocess_no_shell_join_no_preview_revision_and_no_board_sdlc_token():
    source = MODULE.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s+subprocess\b", source, re.M)
    assert not re.search(r"shell=True|shlex\.join|\" \"\.join\((args|argv|cmd)", source)
    assert not re.search(r"-preview\.\d", source)
    assert not re.search(r"shutil\.which\(.az.\)|[\"']az[\"']", source)
    assert "· sdlc" not in source and "claude-code-" + "sdlc:" not in source   # (assembled: the G5 grep reads this file)


def test_the_module_imports_only_what_a_repo_reader_needs():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            names.add((node.module or "").split(".")[0])
    forbidden = {"subprocess", "ado_transport", "ado_wit", "ado_sync", "ado_sync_apply", "ado_schema", "handoff",
                 "sprint", "spec_transition", "new_spec", "advance_phase", "check_gates", "code_host", "host_report",
                 "ado_map", "ado_import"}
    assert not names & forbidden, names & forbidden
    assert {"boards_contract", "ado_sync_model"} <= names


def test_the_module_opens_no_file_for_writing():
    source = MODULE.read_text(encoding="utf-8")
    assert not re.search(r"open\([^)]*[\"'][wax][+b]*[\"']|\.write_text\(|\.write_bytes\(|\.mkdir\(|\.unlink\(", source)
