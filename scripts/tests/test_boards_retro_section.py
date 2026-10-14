"""B5-P3 -- the Azure Boards section of `retro_report.py` (design D47 / open question 25; kit card B5-P3).

The mirror's own ledger (`.sdlc/metrics/ado-sync-log.jsonl`) is one more ledger the retro can read. The section answers the
retro question about it -- what keeps happening -- in three counts, each keyed by a work item, a reason or a class, never by
a person:

  * `directive_seen` -- how many board comments had a line that reads as an instruction, per work item, against how
    many comments were read at all (the tuning signal for the scan: lots flagged of few read = noisy);
  * `comment_refused` -- the reasons the mirror refused to draft a comment (`boards_contract.COMMENT_REFUSALS`), with how
    often and for how many items;
  * `drift_debt` -- the drift-disposition rollup: open rows, those past the two-business-day line, by class, and each
    disposition recorded against how many of them actually settled their row (a take without what it claims is debt).

It is ADDITIVE and it moves nothing that existed. `test_retro_report.py` (frozen) pins the exact key set of the JSON and
the number of `no data` lines of the text, so a repository with no Boards ledger must print exactly what it printed before:
the section is simply absent then (the way the sprint sections are), proven below against golden captures taken from the
unmodified script. When the ledger exists, every pre-existing key keeps its value and the text gains one block before the
closing rule. A count nobody measured reads `no data` / `null`, never 0.

Nothing here runs `az`; `boards_env` forbids it at the seam. The people are fictional.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401

import ast
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import ado_sync_model as model
import boards_contract as bc
import retro_report as rr
from findings_model import fingerprint

SCRIPTS = Path(__file__).resolve().parents[1]
LEDGER = bc.LEDGER
ACTORS = ("@dev-one", "@dev-two")
TODAY = date(2026, 10, 13)

# --- golden captures, taken from the UNMODIFIED retro_report.py -------------------------------------------------

GOLDEN_EMPTY_TEXT = """\
Retro Roll-up  (all history)
============================================================

Recurring findings (candidates for a permanent check):
  no data

Repeat-stale artifacts (artifact-log.jsonl):
  no data

Refresh funnel — divergence-heuristic tuning signal (artifact-log.jsonl):
  no data

Disposition debt rollup (honest counting):
  no data

============================================================
ADVISORY — read-only; patterns, not people; never blocks (exit 0).
Never tracked: velocity, story points, PR count, lines of code. No per-person ranking.
"""

GOLDEN_EMPTY_JSON = """\
{
  "has_data": {
    "recurring_findings": false,
    "repeat_stale": false,
    "refresh_funnel": false,
    "debt": false,
    "carry_over_recurrence": false,
    "bounce_causes": false
  },
  "recurring_findings": [],
  "repeat_stale": [],
  "refresh_funnel": {
    "by_spec": [],
    "by_stem": []
  },
  "debt": {
    "findings": 0,
    "artifact_staleness": 0,
    "refresh_open": 0,
    "total": 0
  },
  "carry_over_recurrence": [],
  "bounce_causes": [],
  "sprint_ledger_present": false,
  "window_days": null
}
"""

GOLDEN_LEGACY_TEXT = """\
Retro Roll-up  (all history)
============================================================

Recurring findings (candidates for a permanent check):
  • null-check @ auth.py:10
      seen 2 times across 2 rounds — candidate for a permanent check
      dispositions: OPEN=2

Repeat-stale artifacts (artifact-log.jsonl):
  no data

Refresh funnel — divergence-heuristic tuning signal (artifact-log.jsonl):
  no data

Disposition debt rollup (honest counting):
  findings debt        (findings-log.jsonl):  1
  artifact staleness   (artifact-log.jsonl):  0
  refresh open         (artifact-log.jsonl):  0
  total open debt:     1

Carry-over recurrence (sprint-log.jsonl — per spec, never per person):
  • spec 0004: carried out of 2 sprints (S07, S08) — RECURRING
      S07 → S08: blocked on DL-03
      S08 → S09: blocked on DL-03

Bounce causes (verdict: returned — by lane and reason, never by who returned it):
  eng:
    • needs a threat model (1 time; specs 0005)

============================================================
ADVISORY — read-only; patterns, not people; never blocks (exit 0).
Never tracked: velocity, story points, PR count, lines of code. No per-person ranking.
"""

GOLDEN_LEGACY_JSON = """\
{
  "has_data": {
    "recurring_findings": true,
    "repeat_stale": false,
    "refresh_funnel": false,
    "debt": true,
    "carry_over_recurrence": true,
    "bounce_causes": true
  },
  "recurring_findings": [
    {
      "category": "null-check",
      "target": "auth.py:10",
      "times": 2,
      "rounds": 2,
      "dispositions": {
        "OPEN": 2
      }
    }
  ],
  "repeat_stale": [],
  "refresh_funnel": {
    "by_spec": [],
    "by_stem": []
  },
  "debt": {
    "findings": 1,
    "artifact_staleness": 0,
    "refresh_open": 0,
    "total": 1
  },
  "carry_over_recurrence": [
    {
      "spec": "0004",
      "carried": 2,
      "sprints": [
        "S07",
        "S08"
      ],
      "carries": [
        {
          "from": "S07",
          "to": "S08",
          "reason": "blocked on DL-03"
        },
        {
          "from": "S08",
          "to": "S09",
          "reason": "blocked on DL-03"
        }
      ],
      "reasons": [
        "blocked on DL-03",
        "blocked on DL-03"
      ],
      "flagged": true
    }
  ],
  "bounce_causes": [
    {
      "lane": "eng",
      "reason": "needs a threat model",
      "times": 1,
      "specs": [
        "0005"
      ]
    }
  ],
  "sprint_ledger_present": true,
  "window_days": null
}
"""


# --- fixtures ---------------------------------------------------------------------------------------------------

def _finding(cat: str, target: str, ts: str, disp: str = "OPEN") -> dict:
    return {"timestamp": ts, "report": "review-report.md", "id": "F-1", "category": cat, "severity": "HIGH",
            "target": target, "disposition": disp, "fingerprint": fingerprint({"category": cat, "target": target}),
            "target_sha": None, "detail": "detail", "actor": "someone"}


def _jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write((row if isinstance(row, str) else json.dumps(row)) + "\n")


def legacy_repo(root: Path) -> Path:
    """The repository the goldens were captured on: a findings ledger and a sprint ledger, no Boards ledger."""
    metrics = root / ".sdlc" / "metrics"
    metrics.mkdir(parents=True, exist_ok=True)
    _jsonl(metrics / "findings-log.jsonl",
           [_finding("null-check", "auth.py:10", "2026-09-01T10:00:00+00:00"),
            _finding("null-check", "auth.py:10", "2026-09-03T10:00:00+00:00"),
            _finding("style", "ui.py:3", "2026-09-03T10:00:00+00:00", "FIXED")])
    _jsonl(metrics / "sprint-log.jsonl",
           [{"ts": "2026-09-05T10:00:00Z", "event": "carried", "sprint": "S07", "spec": "0004", "to_sprint": "S08",
             "reason": "blocked on DL-03", "by": "@someone"},
            {"ts": "2026-09-19T10:00:00Z", "event": "carried", "sprint": "S08", "spec": "0004", "to_sprint": "S09",
             "reason": "blocked on DL-03", "by": "@someone"},
            {"ts": "2026-09-06T10:00:00Z", "event": "verdict", "sprint": "S07", "spec": "0005", "lane": "eng",
             "verdict": "returned", "reason": "needs a threat model", "by": "@someone"}])
    return root


def empty_repo(root: Path) -> Path:
    (root / ".sdlc" / "metrics").mkdir(parents=True, exist_ok=True)
    return root


def ev(ts: str, event: str, **fields) -> dict:
    return {"ts": ts, "event": event, **fields}


def boards_events() -> list[dict]:
    """A small, fully fictional mirror ledger: two linked specs, one pull, drift on both, two dispositions, comments
    read on two work items with three flagged lines, three refused drafts."""
    return [
        ev("2026-10-01T09:00Z", "linked", ref="sdlc:spec:0004", kind="spec", work_item=4521, how="linked",
           rev_after=7, by=ACTORS[0]),
        ev("2026-10-01T09:00Z", "linked", ref="sdlc:spec:0005", kind="spec", work_item=4523, how="linked",
           rev_after=2, by=ACTORS[0]),
        ev("2026-10-12T11:00Z", "observed", ref=None, items=2),
        ev("2026-10-12T10:00Z", "drift_seen", ref="sdlc:spec:0004", kind="spec", work_item=4521,
           field="System.AssignedTo", **{"class": "ADO_OWNED_CHANGE"}, owner="A", rev=8, revised_at="2026-10-12T09:00Z"),
        ev("2026-10-12T10:00Z", "drift_seen", ref="sdlc:spec:0004", kind="spec", work_item=4521,
           field="System.IterationPath", **{"class": "ADO_OWNED_CHANGE"}, owner="A", rev=8, revised_at="2026-10-12T09:00Z"),
        ev("2026-10-01T10:00Z", "drift_seen", ref="sdlc:spec:0005", kind="spec", work_item=4523, field="System.State",
           **{"class": "SDLC_OWNED_DRIFT"}, owner="S", rev=3, revised_at="2026-10-01T09:30Z"),
        ev("2026-10-12T12:00Z", "reconciled", ref="sdlc:spec:0004", kind="spec", work_item=4521,
           field="System.AssignedTo", **{"class": "ADO_OWNED_CHANGE"}, disposition="ACKNOWLEDGED", by=ACTORS[0],
           owner=ACTORS[0]),
        ev("2026-10-12T12:05Z", "reconciled", ref="sdlc:spec:0004", kind="spec", work_item=4521,
           field="System.IterationPath", **{"class": "ADO_OWNED_CHANGE"}, disposition="TAKE_ADO", by=ACTORS[1],
           child_exit=1),
        ev("2026-10-12T11:10Z", "comment_seen", ref="sdlc:spec:0004", work_item=4521, comment=7, version=1,
           change="new", text_sha="a1b2c3d4e5f6", mentions_me=None),
        ev("2026-10-12T11:10Z", "comment_seen", ref="sdlc:spec:0004", work_item=4521, comment=8, version=1,
           change="new", text_sha="b2c3d4e5f6a1", mentions_me=None),
        ev("2026-10-12T11:10Z", "comment_seen", ref="sdlc:spec:0005", work_item=4523, comment=3, version=1,
           change="new", text_sha="c3d4e5f6a1b2", mentions_me=None),
        ev("2026-10-12T11:10Z", "directive_seen", ref="sdlc:spec:0004", work_item=4521, comment=7, lines=[1]),
        ev("2026-10-12T11:10Z", "directive_seen", ref="sdlc:spec:0004", work_item=4521, comment=8, lines=[0, 2]),
        ev("2026-10-12T12:30Z", "comment_seen", ref="sdlc:spec:0004", work_item=4521, comment=7, version=2,
           change="edited", text_sha="d4e5f6a1b2c3", mentions_me=None),
        ev("2026-10-12T12:30Z", "directive_seen", ref="sdlc:spec:0004", work_item=4521, comment=7, lines=[1]),
        ev("2026-10-12T13:00Z", "comment_refused", ref="sdlc:spec:0004", work_item=4521, reason="email_in_text",
           idem_key="deferred:sdlc:spec:0004:aaaa1111", comment_event="spec_deferred", by=ACTORS[0]),
        ev("2026-10-12T13:05Z", "comment_refused", ref="sdlc:spec:0004", work_item=4521, reason="email_in_text",
           idem_key="deferred:sdlc:spec:0004:bbbb2222", comment_event="spec_deferred", by=ACTORS[1]),
        ev("2026-10-12T13:10Z", "comment_refused", ref="sdlc:spec:0005", work_item=4523, reason="budget",
           idem_key="handoff:sdlc:spec:0005:2026-10-12T13:10Z", comment_event="handoff", by=ACTORS[0]),
    ]


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rr, "_today", lambda: TODAY)


def run_cli(argv: list[str], capsys) -> tuple[int, str]:
    old = sys.argv
    sys.argv = ["retro_report.py", *argv]
    try:
        with pytest.raises(SystemExit) as ei:
            rr.main()
        code = ei.value.code
    finally:
        sys.argv = old
    return code, capsys.readouterr().out


def run_json(argv: list[str], capsys) -> dict:
    code, out = run_cli([*argv, "--json"], capsys)
    assert code == 0
    return json.loads(out)


def script_output(root: Path, *extra: str) -> str:
    """What the script prints as a program: UTF-8 forced, as the golden captures were taken."""
    done = subprocess.run([sys.executable, str(SCRIPTS / "retro_report.py"), "--repo", str(root), *extra],
                          capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert done.returncode == 0, done.stderr
    return done.stdout


def with_ledger(root: Path, rows=None) -> Path:
    _jsonl(root / LEDGER, boards_events() if rows is None else rows)
    return root


# --- nothing that existed moves ---------------------------------------------------------------------------------

@pytest.mark.parametrize("name, build, text, doc", [("empty", empty_repo, GOLDEN_EMPTY_TEXT, GOLDEN_EMPTY_JSON),
                                                    ("legacy", legacy_repo, GOLDEN_LEGACY_TEXT, GOLDEN_LEGACY_JSON)])
def test_with_no_boards_ledger_both_outputs_are_byte_identical_to_the_unmodified_script(tmp_path, name, build, text, doc):
    build(tmp_path)
    assert not (tmp_path / LEDGER).exists()
    assert script_output(tmp_path) == text
    assert script_output(tmp_path, "--json") == doc
    assert "boards" not in json.loads(doc) and "Azure Boards" not in text


@pytest.mark.parametrize("rows", [[], ["", "not json", "[]", "42"],
                                  [{"ts": "2026-10-01T09:00Z", "event": "not-an-event"}, {"event": 7}, {"nothing": 1}]])
def test_a_ledger_with_no_event_the_mirror_wrote_is_the_same_as_no_ledger(tmp_path, rows):
    legacy_repo(tmp_path)
    _jsonl(tmp_path / LEDGER, rows)
    assert script_output(tmp_path) == GOLDEN_LEGACY_TEXT
    assert script_output(tmp_path, "--json") == GOLDEN_LEGACY_JSON


def test_the_frozen_pins_still_hold_with_no_ledger(tmp_path, capsys):
    """`test_retro_report.py` pins these on an empty repository; the section must not be the reason they break."""
    empty_repo(tmp_path)
    code, text = run_cli(["--repo", str(tmp_path)], capsys)
    assert code == 0 and text.count("no data") == 4
    data = run_json(["--repo", str(tmp_path)], capsys)
    assert set(data) == {"has_data", "recurring_findings", "repeat_stale", "refresh_funnel", "debt", "window_days",
                         "carry_over_recurrence", "bounce_causes", "sprint_ledger_present"}
    assert set(data["has_data"]) == {"recurring_findings", "repeat_stale", "refresh_funnel", "debt",
                                     "carry_over_recurrence", "bounce_causes"}


def test_with_a_ledger_every_existing_key_keeps_its_value_and_one_key_is_added(tmp_path, capsys):
    with_ledger(legacy_repo(tmp_path))
    data = run_json(["--repo", str(tmp_path)], capsys)
    before = json.loads(GOLDEN_LEGACY_JSON)
    assert set(data) - set(before) == {"boards"}
    assert {k: v for k, v in data.items() if k != "boards"} == before


def test_with_a_ledger_the_text_gains_one_block_before_the_closing_rule_and_loses_nothing(tmp_path):
    with_ledger(legacy_repo(tmp_path))
    text = script_output(tmp_path)
    head, tail = GOLDEN_LEGACY_TEXT.rsplit("=" * 60, 1)
    assert text.startswith(head) and text.endswith("=" * 60 + tail)
    block = text[len(head):-len("=" * 60 + tail)]
    assert block.startswith("Azure Boards mirror (") and block.count("Azure Boards mirror") == 1


# --- the section -------------------------------------------------------------------------------------------------

def boards(tmp_path, capsys, rows=None, *argv) -> dict:
    with_ledger(empty_repo(tmp_path), rows)
    return run_json(["--repo", str(tmp_path), *argv], capsys)["boards"]


def test_the_section_is_keyed_by_work_item_reason_and_class(tmp_path, capsys):
    b = boards(tmp_path, capsys)
    assert b["ledger"] == LEDGER
    assert b["has_data"] == {"directive_seen": True, "comment_refused": True, "drift_debt": True}
    assert b["directive_seen"] == {
        "comments_seen": 3, "flagged_comments": 2, "flagged_lines": 3,
        "by_work_item": [{"work_item": 4521, "ref": "sdlc:spec:0004", "comments": 2, "lines": 3, "events": 3}]}
    assert b["comment_refused"] == [{"reason": "email_in_text", "times": 2, "work_items": 1},
                                    {"reason": "budget", "times": 1, "work_items": 1}]
    drift = b["drift_debt"]
    assert (drift["as_of"], drift["open"], drift["drifted"], drift["conflicts"], drift["debt"]) == (
        "2026-10-12T11:00Z", 2, 2, 0, 1)
    assert drift["by_class"] == {"ADO_OWNED_CHANGE": 1, "SDLC_OWNED_DRIFT": 1}
    assert drift["debt_rows"] == [{"ref": "sdlc:spec:0005", "field": "System.State", "class": "SDLC_OWNED_DRIFT",
                                   "seen": "2026-10-01", "due": "2026-10-05"}]
    assert drift["dispositions"] == [{"disposition": "ACKNOWLEDGED", "recorded": 1, "settled": 1},
                                     {"disposition": "TAKE_ADO", "recorded": 1, "settled": 0}]


def test_the_drift_numbers_are_the_models_own(tmp_path, capsys):
    """One rule, not two: the rollup reads `ado_sync_model.summarize`, the number `status` prints."""
    b = boards(tmp_path, capsys)
    status = model.summarize(boards_events(), TODAY)
    for key in ("open", "drifted", "conflicts", "debt"):
        assert b["drift_debt"][key] == status["counts"][key]
    assert b["drift_debt"]["by_class"] == status["by_class"]


def test_a_flagged_comment_seen_again_after_an_edit_is_counted_once_but_its_events_are_kept(tmp_path, capsys):
    row = next(r for r in boards(tmp_path, capsys)["directive_seen"]["by_work_item"])
    assert row["comments"] == 2 and row["lines"] == 3 and row["events"] == 3      # comment 7 line 1 twice -> one line


def test_the_text_block_reads_per_item_per_reason_and_per_class(tmp_path):
    with_ledger(empty_repo(tmp_path))
    text = script_output(tmp_path)
    start = text.index("Azure Boards mirror")
    block = text[start:text.index("=" * 60, start)]
    assert "ado-sync-log.jsonl" in block and "never per person" in block
    assert "3 comments read; 2 had a line that reads as an instruction (3 lines)" in block
    assert "#4521 sdlc:spec:0004" in block and "2 comments, 3 lines" in block
    assert "email_in_text" in block and "2 times (1 work item)" in block and "budget" in block
    assert "open 2" in block and "past the 2-business-day line 1" in block and "conflicts 0" in block
    assert "ADO_OWNED_CHANGE 1" in block and "SDLC_OWNED_DRIFT 1" in block
    assert "ACKNOWLEDGED 1 (1 settled)" in block and "TAKE_ADO 1 (0 settled)" in block
    assert "as of 2026-10-12T11:00Z" in block


def walk(value):
    if isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from walk(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from walk(inner)


def test_no_actor_appears_in_the_section_as_a_key_a_value_or_a_word(tmp_path, capsys):
    b = boards(tmp_path, capsys)
    keys = set(walk(b))
    assert not keys & {"by", "executed_as", "revised_by", "owner", "actor", "person", "who", "handle"}
    assert "@dev" not in json.dumps(b)
    with_ledger(empty_repo(tmp_path / "again"))
    text = script_output(tmp_path / "again")
    assert not any(a in text for a in ACTORS) and "@dev" not in text


def test_no_ranking_flag_exists():
    help_text = rr.build_parser().format_help()
    assert not re.search(r"--(by|actor|person|rank|author|who)\b", help_text)


# --- no data is not zero -----------------------------------------------------------------------------------------

def test_a_ledger_that_never_read_a_comment_or_pulled_says_no_data_not_zero(tmp_path, capsys):
    rows = [ev("2026-10-01T09:00Z", "discovered", ref=None, team="core"),
            ev("2026-10-02T09:00Z", "planned", plan="3f9c1a07b2de", ref="sdlc:spec:0004", kind="spec", action="create")]
    b = boards(tmp_path, capsys, rows)
    assert b["has_data"] == {"directive_seen": False, "comment_refused": False, "drift_debt": False}
    assert b["directive_seen"] == {"comments_seen": None, "flagged_comments": None, "flagged_lines": None,
                                   "by_work_item": []}
    assert b["comment_refused"] == []
    drift = b["drift_debt"]
    assert all(drift[k] is None for k in ("as_of", "open", "drifted", "conflicts", "debt", "by_class", "debt_rows"))
    assert drift["dispositions"] == []
    with_ledger(empty_repo(tmp_path / "text"), rows)
    text = script_output(tmp_path / "text")
    block = text[text.index("Azure Boards mirror"):text.index("=" * 60, text.index("Azure Boards mirror"))]
    assert block.count("no data") == 3 and not re.search(r"\b0\b", block)


def test_comments_read_and_none_flagged_is_an_honest_zero(tmp_path, capsys):
    rows = [ev("2026-10-12T11:10Z", "comment_seen", ref="sdlc:spec:0004", work_item=4521, comment=7, version=1,
               change="new", text_sha="a1b2c3d4e5f6", mentions_me=None)]
    b = boards(tmp_path, capsys, rows)
    assert b["directive_seen"] == {"comments_seen": 1, "flagged_comments": 0, "flagged_lines": 0, "by_work_item": []}
    assert b["has_data"]["directive_seen"] is True


def test_directive_events_with_no_comment_seen_count_flags_but_not_a_denominator(tmp_path, capsys):
    rows = [ev("2026-10-12T11:10Z", "directive_seen", ref=None, work_item=4521, comment=7, lines=[3])]
    b = boards(tmp_path, capsys, rows)["directive_seen"]
    assert b["comments_seen"] is None and b["flagged_comments"] == 1 and b["flagged_lines"] == 1
    assert b["by_work_item"] == [{"work_item": 4521, "ref": None, "comments": 1, "lines": 1, "events": 1}]


def test_comments_posted_and_none_refused_is_an_honest_none(tmp_path, capsys):
    rows = [ev("2026-10-12T13:00Z", "commented", ref="sdlc:spec:0004", work_item=4521, idem_key="k", by=ACTORS[0])]
    b = boards(tmp_path, capsys, rows)
    assert b["comment_refused"] == [] and b["has_data"]["comment_refused"] is True
    with_ledger(empty_repo(tmp_path / "t"), rows)
    text = script_output(tmp_path / "t")
    assert "none recorded" in text[text.index("Refused comment drafts"):]


def test_a_pulled_ledger_with_no_open_drift_reads_zero_because_it_was_measured(tmp_path, capsys):
    rows = [ev("2026-10-12T11:00Z", "observed", ref=None, items=0)]
    drift = boards(tmp_path, capsys, rows)["drift_debt"]
    assert drift["as_of"] == "2026-10-12T11:00Z" and drift["open"] == 0 and drift["debt"] == 0 and drift["by_class"] == {}


def test_a_refusal_reason_outside_the_enum_is_bucketed_not_echoed(tmp_path, capsys):
    note = "kim.lee" + "@corp.example.com said no"
    rows = [ev("2026-10-12T13:00Z", "comment_refused", ref="sdlc:spec:0004", work_item=4521, reason="budget"),
            ev("2026-10-12T13:01Z", "comment_refused", ref="sdlc:spec:0004", work_item=4521, reason="free words here"),
            ev("2026-10-12T13:02Z", "comment_refused", ref="sdlc:spec:0004", work_item=4521, reason=note),
            ev("2026-10-12T13:03Z", "comment_refused", ref="sdlc:spec:0004", work_item=4521)]
    refused = boards(tmp_path, capsys, rows)["comment_refused"]
    assert {r["reason"]: r["times"] for r in refused} == {"budget": 1, "other": 3}
    assert "free words" not in json.dumps(refused) and "corp.example" not in json.dumps(refused)


def test_a_ref_that_is_not_an_sdlc_ref_is_never_shown(tmp_path, capsys):
    rows = [ev("2026-10-12T11:10Z", "directive_seen", ref="kim.lee-said-no", work_item=4521, comment=7, lines=[0]),
            ev("2026-10-12T11:11Z", "directive_seen", ref="sdlc:spec:0004", work_item=4521, comment=8, lines=[0])]
    (row,) = boards(tmp_path, capsys, rows)["directive_seen"]["by_work_item"]
    assert row["ref"] == "sdlc:spec:0004" and row["comments"] == 2
    only_bad = [ev("2026-10-12T11:10Z", "directive_seen", ref="kim.lee-said-no", work_item=9, comment=1, lines=[0])]
    (row,) = boards(tmp_path / "bad", capsys, only_bad)["directive_seen"]["by_work_item"]
    assert row["ref"] is None
    with_ledger(empty_repo(tmp_path / "text"), only_bad)
    assert "#9 (no ref)" in script_output(tmp_path / "text") and "kim.lee" not in script_output(tmp_path / "text")


def test_every_enum_reason_is_counted_under_its_own_name(tmp_path, capsys):
    rows = [ev("2026-10-12T13:00Z", "comment_refused", ref=None, work_item=4000 + i, reason=reason)
            for i, reason in enumerate(bc.COMMENT_REFUSALS)]
    refused = boards(tmp_path, capsys, rows)["comment_refused"]
    assert sorted(r["reason"] for r in refused) == sorted(bc.COMMENT_REFUSALS)
    assert all(r["times"] == 1 and r["work_items"] == 1 for r in refused)


# --- window, modes, faults ---------------------------------------------------------------------------------------

def stamp(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def test_the_window_applies_to_directive_and_refusal_counts_but_not_to_drift_debt(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(rr, "_today", lambda: datetime.now(timezone.utc).date())
    rows = [ev(stamp(400), "comment_seen", ref="sdlc:spec:0004", work_item=4521, comment=1, version=1, change="new"),
            ev(stamp(400), "directive_seen", ref="sdlc:spec:0004", work_item=4521, comment=1, lines=[0]),
            ev(stamp(400), "comment_refused", ref="sdlc:spec:0004", work_item=4521, reason="budget"),
            ev(stamp(2), "comment_seen", ref="sdlc:spec:0004", work_item=4521, comment=2, version=1, change="new"),
            ev(stamp(1), "comment_refused", ref="sdlc:spec:0004", work_item=4521, reason="max_chars"),
            ev(stamp(300), "observed", ref=None, items=1),
            ev(stamp(300), "drift_seen", ref="sdlc:spec:0005", kind="spec", work_item=4523, field="System.State",
               **{"class": "SDLC_OWNED_DRIFT"}, owner="S", rev=3)]
    whole = boards(tmp_path, capsys, rows)
    assert whole["directive_seen"]["flagged_comments"] == 1 and len(whole["comment_refused"]) == 2
    windowed = run_json(["--repo", str(tmp_path), "--window-days", "30"], capsys)["boards"]
    assert windowed["directive_seen"] == {"comments_seen": 1, "flagged_comments": 0, "flagged_lines": 0,
                                          "by_work_item": []}
    assert [r["reason"] for r in windowed["comment_refused"]] == ["max_chars"]
    assert windowed["drift_debt"]["open"] == 1 and windowed["drift_debt"]["debt"] == 1


def test_state_mode_reads_the_same_ledger_as_repo_mode(tmp_path, capsys):
    import yaml
    with_ledger(empty_repo(tmp_path))
    (tmp_path / ".sdlc" / "state.yaml").write_text(yaml.safe_dump({"phases": {}}), encoding="utf-8")
    via_repo = run_json(["--repo", str(tmp_path)], capsys)
    via_state = run_json(["--state", str(tmp_path / ".sdlc" / "state.yaml")], capsys)
    assert via_repo["boards"] == via_state["boards"]


def test_a_damaged_ledger_never_fails_and_never_invents_a_number(tmp_path, capsys):
    rows = ["{not json", json.dumps(ev("2026-10-12T11:00Z", "observed", ref=None, items=1)),
            json.dumps(ev("2026-10-12T11:10Z", "directive_seen", ref="sdlc:spec:0004", work_item="4521", comment=7,
                          lines="oops")),
            json.dumps(ev("2026-10-12T11:10Z", "directive_seen", ref="sdlc:spec:0004", work_item=True, comment=7,
                          lines=[1])),
            json.dumps(ev("2026-10-12T11:10Z", "directive_seen", ref="sdlc:spec:0004", work_item=4521, comment=7,
                          lines=[1, "x", -1, True])),
            json.dumps(ev("2026-10-12T11:10Z", "comment_refused", work_item=[1], reason=["budget"])),
            json.dumps(ev("2026-10-12T11:11Z", "drift_seen", ref="sdlc:spec:0004", field=None, work_item=1))]
    with_ledger(empty_repo(tmp_path), rows)
    code, out = run_cli(["--repo", str(tmp_path), "--json"], capsys)
    assert code == 0
    b = json.loads(out)["boards"]
    assert b["directive_seen"]["by_work_item"] == [{"work_item": 4521, "ref": "sdlc:spec:0004", "comments": 1,
                                                    "lines": 1, "events": 1}]
    assert b["drift_debt"]["by_class"] == {"other": 1}                  # a row with no class is bucketed, never a null key
    code, text = run_cli(["--repo", str(tmp_path)], capsys)
    assert code == 0 and "Azure Boards mirror" in text


def test_a_fault_in_the_section_is_reported_not_raised(tmp_path, capsys, monkeypatch):
    with_ledger(empty_repo(tmp_path))
    monkeypatch.setattr(model, "summarize", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    code, out = run_cli(["--repo", str(tmp_path), "--json"], capsys)
    assert code == 0
    b = json.loads(out)["boards"]
    assert b["has_data"]["drift_debt"] is False and b["drift_debt"]["open"] is None
    assert b["directive_seen"]["flagged_comments"] == 2          # the other blocks still read


# --- discipline --------------------------------------------------------------------------------------------------

def test_the_report_reads_the_pure_model_and_never_the_mirror_s_io_modules():
    tree = ast.parse((SCRIPTS / "retro_report.py").read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert {"ado_sync_model", "boards_contract"} <= imported
    assert not imported & {"subprocess", "ado_sync", "ado_transport", "ado_wit", "ado_sync_reconcile", "ado_schema",
                           "requests", "urllib", "socket"}


def test_the_section_writes_nothing(tmp_path):
    with_ledger(legacy_repo(tmp_path))
    before = {p: p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()}
    script_output(tmp_path)
    script_output(tmp_path, "--json")
    assert {p: p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()} == before
