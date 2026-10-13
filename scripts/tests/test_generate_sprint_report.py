"""Tests for generate_sprint_report.py — the sprint planning / review page renderer.

The renderer is driven by the `sprint.build_view` JSON shape (proposal "Sprint Team Layer" §4).
These tests inject that view directly (`generate(..., view=...)`) or install a fake `sprint`
module, so they never depend on scripts/sprint.py being present or on its I/O.
"""

import json
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest

import generate_sprint_report as gsr

SCRIPT = Path(gsr.__file__).resolve()

SECTION_TITLES = (
    "Commitment", "Mix and capacity", "Build order and next up", "Dependencies",
    "Spec cards", "Open decisions", "Carried in",
)


# ── fixtures ────────────────────────────────────────────────────────────────────

SPEC_BODY = """\
---
spec: "{sid}"
name: "{name}"
status: {status}
type: feature
risk: {risk}
source: "{source}"
channel: "{channel}"
harness_context: "{hc}"
created: "2026-09-01"
sprint: "S07"
next_owner: ""
eng_review: "accepted"
data_review: "n-a"
depends_on: "{deps}"
---

# Spec {sid} — {name}

## Goal
Goal text for {sid}: the duplicate claim returns `409`.

## Why
Why text for {sid}: adjusters stop double-paying.

## Scope

### In scope
- `src/claims/**`

### Out of scope
- `src/auth/**`

## Acceptance Checks
- [ ] a duplicate submission returns `409`
- [ ] the body is `{{"error": "duplicate claim"}}`
- [ ] the first submission still returns `201`

## Risk Tier
**Tier:** {risk}
**Why this tier:** touches client money for {sid}.

## Delegation Plan
- **Scope (file patterns):** `src/claims/**`
- **Context (pattern to reuse):** `{hc}`
- **Permissions:** build, test, lint
- **Gated paths touched:** none

## Checking Plan
**Ladder depth:** {risk}
**Specifics:** grader + non-author Checker; security pass; named sign-off.

## Decision List
- DL-03 fail closed on a timeout — owner Dana
"""

SPRINT_RECORD = """\
---
sprint: "S07"
goal: "Adjusters never double-pay a claim"
start: "2026-09-21"
end: "2026-10-05"
state: {state}
target: 3
mix: "HIGH:1,MEDIUM:1,LOW:1"
board_ref: "ADO Iteration 6"
readied_by: "Priya"
closed_by: "{closed_by}"
created: "2026-09-18"
---
# Sprint S07

## Goal
Adjusters never double-pay a claim.

## Slate
<!-- Rendered by `sprint.py status` from spec frontmatter — never hand-edit. -->

## Close
{close_table}
"""

CLOSE_TABLE = """\
| spec | outcome | by | reason |
|------|---------|----|--------|
| 0001 | kept | Priya | merged 2026-10-02 |
| 0002 | carried → S08 | Priya | vendor sandbox unavailable until Oct 7 |
| 0003 | dropped | Priya | superseded by the new dedupe design |
"""

INDEX_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Acme — SDLC Project Index</title></head>
<body>
<div class="links-section">
  <h2>Quick Links</h2>
  <div class="links-grid">
    <a class="report-link" href="00-discovery-report.html">Phase 0: discovery</a>
    <a class="report-link" href="build-report.html">Build: build</a>
  </div>
</div>
<div class="report-footer"><span>Shepherd — Project Index</span></div>
</body>
</html>
"""


def write_spec(repo: Path, sid: str, name: str, risk: str, *, status="ready", deps="", channel="chat",
               hc="claims-repository", source="FR-012") -> Path:
    path = repo / "specs" / f"{sid}-{name}.md"
    path.write_text(SPEC_BODY.format(sid=sid, name=name, risk=risk, status=status, deps=deps,
                                     channel=channel, hc=hc, source=source), encoding="utf-8")
    return path


def make_repo(tmp_path: Path, *, state="ready", closed_by="", close_table="", with_index=True,
              with_state=False) -> Path:
    repo = tmp_path / "proj"
    (repo / ".sdlc" / "sprints").mkdir(parents=True)
    (repo / ".sdlc" / "metrics").mkdir(parents=True)
    (repo / ".sdlc" / "reports").mkdir(parents=True)
    (repo / "specs").mkdir(parents=True)
    (repo / ".sdlc" / "sprints" / "S07.md").write_text(
        SPRINT_RECORD.format(state=state, closed_by=closed_by, close_table=close_table), encoding="utf-8")
    write_spec(repo, "0001", "duplicate-claim-409", "HIGH")
    write_spec(repo, "0002", "claim-search", "MEDIUM", deps="0001")
    write_spec(repo, "0003", "claim-copy-fix", "LOW", deps="0001,0002", status="draft")
    (repo / ".sdlc" / "decision-log.md").write_text(
        "# Decision log\n\n| id | decision | owner | opened | due | status |\n|---|---|---|---|---|---|\n"
        "| DL-03 | Fail closed on a timeout for 0001 | Dana | 2026-09-10 | 2026-09-12 | open |\n",
        encoding="utf-8")
    ledger = [
        {"ts": "2026-09-18T09:00:00+00:00", "event": "sprint_new", "sprint": "S07", "by": "Priya"},
        {"ts": "2026-09-18T09:05:00+00:00", "event": "slated", "sprint": "S07", "spec": "0001", "by": "Priya"},
        {"ts": "2026-09-18T09:05:01+00:00", "event": "slated", "sprint": "S07", "spec": "0002", "by": "Priya"},
        {"ts": "2026-09-18T09:05:02+00:00", "event": "slated", "sprint": "S07", "spec": "0003", "by": "Priya"},
        {"ts": "2026-09-21T08:30:00+00:00", "event": "ready", "sprint": "S07", "by": "Priya"},
        {"ts": "2026-09-05T08:30:00+00:00", "event": "carried", "sprint": "S06", "spec": "0002",
         "to_sprint": "S07", "by": "Priya", "reason": "vendor sandbox slipped"},
        {"ts": "2026-10-05T16:00:00+00:00", "event": "carried", "sprint": "S07", "spec": "0002",
         "to_sprint": "S08", "by": "Priya", "reason": "vendor sandbox unavailable until Oct 7"},
        {"ts": "2026-10-05T16:00:01+00:00", "event": "dropped", "sprint": "S07", "spec": "0003",
         "by": "Priya", "reason": "superseded by the new dedupe design"},
        {"ts": "2026-10-05T16:05:00+00:00", "event": "closed", "sprint": "S07", "by": "Priya"},
    ]
    (repo / ".sdlc" / "metrics" / "sprint-log.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in ledger) + "not json\n", encoding="utf-8")
    if with_index:
        (repo / ".sdlc" / "reports" / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    if with_state:
        (repo / ".sdlc" / "state.yaml").write_text("project_name: Acme Claims\ncurrent_phase: build\n", encoding="utf-8")
    return repo


def row(sid, name, risk, *, status="ready", deps=None, dor="READY", blocking=None, path="", eng="accepted",
        data="n-a", owner=""):
    return {
        "id": sid, "name": name, "risk": risk, "type": "feature", "channel": "chat", "status": status,
        "sprint": "S07", "next_owner": owner, "eng_review": eng, "data_review": data,
        "depends_on": deps or [], "dor": dor, "dor_blocking": blocking or [], "path": path,
    }


def full_view(repo: Path, *, state="ready") -> dict:
    specs = repo / "specs"
    slate = [
        row("0001", "duplicate-claim-409", "HIGH", path=str(specs / "0001-duplicate-claim-409.md")),
        row("0002", "claim-search", "MEDIUM", deps=["0001"], path=str(specs / "0002-claim-search.md")),
        row("0003", "claim-copy-fix", "LOW", status="draft", deps=["0001", "0002"], dor="NOT READY",
            blocking=["Scope > Out of scope is empty"], path="specs/0003-claim-copy-fix.md", owner="Marco"),
    ]
    return {
        "sprint": {"id": "S07", "goal": "Adjusters never double-pay a claim", "start": "2026-09-21",
                   "end": "2026-10-05", "state": state, "target": 3, "mix": "HIGH:1,MEDIUM:1,LOW:1",
                   "board_ref": "ADO Iteration 6", "readied_by": "Priya", "closed_by": "",
                   "path": str(repo / ".sdlc" / "sprints" / "S07.md"),
                   "days": {"total": 10, "elapsed": 4, "remaining": 6}},
        "slate": slate,
        "readiness": {"ready": 2, "total": 3,
                      "gaps": [{"spec": "0003", "gaps": ["DoR: NOT READY (Scope > Out of scope is empty)",
                                                         "status is draft, not ready"]}]},
        "verdicts_pending": [{"spec": "0003", "lane": "eng", "since_business_days": 3}],
        "handoffs_open": [{"spec": "0003", "to": "Marco", "since_business_days": None}],
        "mix": {"HIGH": {"target": 1, "actual": 1}, "MEDIUM": {"target": 1, "actual": 1}, "LOW": {"target": 1, "actual": 1}},
        "mix_warnings": ["slate has 3 specs, more than the target of 2"],
        "wip": {"in_flight": 1, "cap": 2},
        "build_order": ["0001", "0002", "0003"],
        "next_up": "0001",
        "dependency_gaps": ["0003: depends on 0009, which is not a known spec"],
        "decisions": {"open": 1, "overdue": [{"id": "DL-03", "decision": "Fail closed on a timeout for 0001",
                                             "owner": "Dana", "due": "2026-09-12"}]},
        "carried_in": [{"spec": "0002", "from_sprint": "S06", "reason": "vendor sandbox slipped"}],
        "has_data": True,
    }


def empty_view(repo: Path) -> dict:
    return {
        "sprint": {"id": "S07", "goal": "", "start": "", "end": "", "state": "planning", "target": None,
                   "mix": "", "board_ref": "", "readied_by": "", "closed_by": "",
                   "path": str(repo / ".sdlc" / "sprints" / "S07.md"),
                   "days": {"total": None, "elapsed": None, "remaining": None}},
        "slate": [], "readiness": {"ready": None, "total": None, "gaps": []},
        "verdicts_pending": [], "handoffs_open": [], "mix": {}, "mix_warnings": [],
        "wip": {"in_flight": None, "cap": None}, "build_order": [], "next_up": None,
        "dependency_gaps": [], "decisions": None, "carried_in": [], "has_data": False,
    }


def outside_markers(index_html: str) -> str:
    """The index with the sprints block cut out — what must stay byte-identical across reruns."""
    start = index_html.find(gsr.SPRINTS_START)
    end = index_html.find(gsr.SPRINTS_END)
    assert start != -1 and end != -1
    rest = index_html[end + len(gsr.SPRINTS_END):]
    if rest.startswith("\n"):  # the splice writes `block + "\n"` before </body>
        rest = rest[1:]
    return index_html[:start] + rest


# ── planning page ───────────────────────────────────────────────────────────────

class TestPlanningPage:
    def test_default_output_path_and_every_section(self, tmp_path):
        repo = make_repo(tmp_path)
        out = gsr.generate(repo, "S07", view=full_view(repo))
        assert out == repo / ".sdlc" / "reports" / "sprint-S07-planning.html"
        page = out.read_text(encoding="utf-8")
        for title in SECTION_TITLES:
            assert f"<h2>{title}</h2>" in page, title
        # header facts
        assert "Sprint S07" in page and "Planning" in page
        assert "Adjusters never double-pay a claim" in page
        assert "2026-09-21" in page and "2026-10-05" in page
        assert "ADO Iteration 6" in page
        assert "Priya on 2026-09-21" in page  # readied by / when, from the ledger's `ready` event
        assert "total 10" in page and "elapsed 4" in page and "remaining 6" in page

    def test_commitment_table_carries_verdicts_owner_and_gaps(self, tmp_path):
        repo = make_repo(tmp_path)
        page = gsr.generate(repo, "S07", view=full_view(repo)).read_text(encoding="utf-8")
        assert "2 of 3 slated specs ready" in page
        assert "Scope &gt; Out of scope is empty" in page
        assert "status is draft, not ready" in page
        assert "Marco" in page  # next owner and open handoff
        assert page.count(">accepted<") >= 3 and ">n-a<" in page
        # the pending verdict shows its age; the handoff with no timestamp reads "no data", never 0
        assert "<td>3</td>" in page
        m = re.search(r"Handoffs awaiting acknowledgement.*?</table>", page, re.DOTALL)
        assert m and "no data" in m.group(0)

    def test_mix_build_order_and_dependencies(self, tmp_path):
        repo = make_repo(tmp_path)
        page = gsr.generate(repo, "S07", view=full_view(repo)).read_text(encoding="utf-8")
        assert "HIGH:1,MEDIUM:1,LOW:1" in page
        assert "slate has 3 specs, more than the target of 2" in page
        assert "<td>WIP in flight</td><td>1</td>" in page and "<td>WIP cap</td><td>2</td>" in page
        assert "no target set" in page  # review-turnaround target absent (no cadence plan)
        # build order with arrows, next up and its why
        assert "<code>0001</code> &rarr; <code>0002</code> &rarr; <code>0003</code>" in page
        assert "Next up: <code>0001</code>" in page
        assert "under the WIP cap" in page
        assert "depends on <code>0001</code>" in page
        assert "unblocks 2" in page  # 0001 unblocks 0002 and 0003
        assert "0003: depends on 0009, which is not a known spec" in page

    def test_spec_cards_read_the_spec_bodies(self, tmp_path):
        repo = make_repo(tmp_path)
        page = gsr.generate(repo, "S07", view=full_view(repo)).read_text(encoding="utf-8")
        for sid in ("0001", "0002", "0003"):
            assert f'id="spec-{sid}"' in page
            assert f"Goal text for {sid}" in page
            assert f"Why text for {sid}" in page
            assert f"touches client money for {sid}" in page  # Risk Tier text
        assert "<td>Acceptance checks</td><td>3</td>" in page
        assert "claims-repository" in page  # harness_context
        assert "FR-012" in page  # source id
        assert "DL-03 fail closed on a timeout" in page  # Decision List item
        # a relative spec path resolves against the repo root
        assert "spec body not found" not in page

    def test_spec_card_without_body_reads_no_data(self, tmp_path):
        repo = make_repo(tmp_path)
        view = full_view(repo)
        view["slate"][0]["path"] = str(repo / "specs" / "missing.md")
        page = gsr.generate(repo, "S07", view=view).read_text(encoding="utf-8")
        assert "spec body not found" in page

    def test_open_decisions_and_carried_in(self, tmp_path):
        repo = make_repo(tmp_path)
        page = gsr.generate(repo, "S07", view=full_view(repo)).read_text(encoding="utf-8")
        assert "DL-03" in page and "Dana" in page and "2026-09-12" in page
        assert "Fail closed on a timeout for 0001" in page
        assert "vendor sandbox slipped" in page and "S06" in page

    def test_footer_guardrail_and_self_contained(self, tmp_path):
        repo = make_repo(tmp_path)
        page = gsr.generate(repo, "S07", view=full_view(repo)).read_text(encoding="utf-8")
        assert gsr.GUARDRAIL in page
        assert "Never tracked: velocity, story points, PR count, lines of code." in page
        assert "http://" not in page and "https://" not in page
        assert "<style>" in page and "<script" not in page
        assert page.startswith("<!DOCTYPE html>")

    def test_standalone_header_notes_missing_engagement_context(self, tmp_path):
        repo = make_repo(tmp_path)
        page = gsr.generate(repo, "S07", view=full_view(repo)).read_text(encoding="utf-8")
        assert "standalone mode" in page and "no state.yaml" in page
        assert "Project: proj" in page

    def test_workflow_header_uses_project_name(self, tmp_path):
        repo = make_repo(tmp_path, with_state=True)
        page = gsr.generate(repo, "S07", view=full_view(repo)).read_text(encoding="utf-8")
        assert "workflow mode" in page and "Acme Claims" in page

    def test_explicit_output_relative_to_repo(self, tmp_path):
        repo = make_repo(tmp_path)
        out = gsr.generate(repo, "S07", view=full_view(repo), output=Path("docs/sprint.html"))
        assert out == repo / "docs" / "sprint.html" and out.is_file()

    def test_cadence_plan_targets_feed_the_mix_section(self, tmp_path):
        repo = make_repo(tmp_path)
        plan = repo / ".sdlc" / "artifacts" / "03-foundation" / "cadence-plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text(
            "- **WIP cap:** no Orchestrator runs more than **2** concurrent agent streams.\n"
            "- **Review-wait tripwire:** halt new streams when median review wait exceeds **one working day**.\n"
            "- **Review-turnaround target:** **1 business day per lane**\n", encoding="utf-8")
        view = full_view(repo)
        view["wip"] = {"in_flight": 0, "cap": None}
        page = gsr.generate(repo, "S07", view=view).read_text(encoding="utf-8")
        assert "2 (cadence plan)" in page
        assert "1 business day per lane" in page
        assert "one working day" not in page  # the tripwire is not the turnaround target


# ── empty sections ──────────────────────────────────────────────────────────────

class TestEmptySections:
    def test_every_empty_section_reads_no_data_never_zero(self, tmp_path):
        repo = make_repo(tmp_path)
        page = gsr.generate(repo, "S07", view=empty_view(repo)).read_text(encoding="utf-8")
        for title in SECTION_TITLES:
            m = re.search(rf"<h2>{re.escape(title)}</h2>(.*?)</section>", page, re.DOTALL)
            assert m, title
            assert "no data" in m.group(1), title
        assert "nothing has been slated into this sprint yet" in page
        assert "total no data" in page and "remaining no data" in page
        assert "no decision-log found" in page
        assert "no cap set" in page and "no target set" in page
        assert "not yet readied" in page
        # no fabricated counts anywhere in the header facts
        header = re.search(r"<header.*?</header>", page, re.DOTALL).group(0)
        assert re.search(r"\b0\b", re.sub(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}", "", header)) is None


# ── review page ─────────────────────────────────────────────────────────────────

class TestReviewPage:
    def test_review_renders_outcomes_first(self, tmp_path):
        repo = make_repo(tmp_path, state="closed", closed_by="Priya", close_table=CLOSE_TABLE)
        view = full_view(repo, state="closed")
        view["slate"][0]["status"] = "merged"
        view["sprint"]["closed_by"] = "Priya"
        out = gsr.generate(repo, "S07", kind="review", view=view)
        assert out.name == "sprint-S07-review.html"
        page = out.read_text(encoding="utf-8")
        assert "Review" in page and "Outcomes: kept, carried, dropped" in page
        assert page.index("Outcomes: kept, carried, dropped") < page.index("<h2>Commitment</h2>")
        assert "Kept (merged): 1" in page and "open at close: 2" in page
        # the ## Close table from the sprint record
        assert "carried → S08" in page and "superseded by the new dedupe design" in page
        # the ledger's carried / dropped reasons, this sprint only
        assert "vendor sandbox unavailable until Oct 7" in page
        assert "carried &rarr; S08" in page and ">dropped<" in page
        # carry-over recurrence per spec (0002 carried out of S06 and S07)
        assert "<code>0002</code></td><td>2</td>" in page
        assert "Closed by" in page and "Priya on 2026-10-05" in page

    def test_review_with_nothing_closed_reads_no_data(self, tmp_path):
        repo = make_repo(tmp_path)
        (repo / ".sdlc" / "metrics" / "sprint-log.jsonl").unlink()
        page = gsr.generate(repo, "S07", kind="review", view=empty_view(repo)).read_text(encoding="utf-8")
        m = re.search(r"<h2>Outcomes: kept, carried, dropped</h2>(.*?)</section>", page, re.DOTALL)
        assert m and m.group(1).count("no data") >= 3
        assert "Kept (merged): no data" in page
        assert "not yet closed" in page

    def test_bad_kind_is_refused(self, tmp_path):
        repo = make_repo(tmp_path)
        with pytest.raises(ValueError):
            gsr.generate(repo, "S07", kind="retro", view=full_view(repo))


# ── index.html block ────────────────────────────────────────────────────────────

class TestIndexBlock:
    def test_inserted_once_before_body_close_and_existing_links_untouched(self, tmp_path):
        repo = make_repo(tmp_path)
        index = repo / ".sdlc" / "reports" / "index.html"
        before = index.read_text(encoding="utf-8")
        gsr.generate(repo, "S07", view=full_view(repo))
        after = index.read_text(encoding="utf-8")
        assert after.count(gsr.SPRINTS_START) == 1 and after.count(gsr.SPRINTS_END) == 1
        assert after.index(gsr.SPRINTS_END) < after.index("</body>")
        assert 'href="sprint-S07-planning.html"' in after
        assert 'href="00-discovery-report.html"' in after and 'href="build-report.html"' in after
        assert outside_markers(after) == before  # everything outside the block is byte-identical

    def test_rerun_replaces_the_block_and_lists_both_pages(self, tmp_path):
        repo = make_repo(tmp_path, close_table=CLOSE_TABLE)
        index = repo / ".sdlc" / "reports" / "index.html"
        gsr.generate(repo, "S07", view=full_view(repo))
        first = index.read_text(encoding="utf-8")
        gsr.generate(repo, "S07", view=full_view(repo))
        assert index.read_text(encoding="utf-8") == first  # idempotent
        gsr.generate(repo, "S07", kind="review", view=full_view(repo))
        third = index.read_text(encoding="utf-8")
        assert third.count(gsr.SPRINTS_START) == 1
        assert 'href="sprint-S07-planning.html"' in third and 'href="sprint-S07-review.html"' in third
        assert outside_markers(third) == outside_markers(first)

    def test_no_index_means_no_index_written(self, tmp_path):
        repo = make_repo(tmp_path, with_index=False)
        gsr.generate(repo, "S07", view=full_view(repo))
        assert not (repo / ".sdlc" / "reports" / "index.html").exists()

    def test_splice_without_body_close_appends(self):
        html = "<p>x</p>\n"
        out = gsr.splice_sprints_block(html, gsr.sprints_block([("S07", "planning", "sprint-S07-planning.html")]))
        assert out.startswith(html) and out.count(gsr.SPRINTS_START) == 1

    def test_sprint_pages_sorted_and_filtered(self, tmp_path):
        reports = tmp_path / "reports"
        reports.mkdir()
        for name in ("sprint-S08-review.html", "sprint-S07-planning.html", "build-report.html",
                     "sprint-S07-review.html", "sprint-x-planning.html"):
            (reports / name).write_text("", encoding="utf-8")
        assert gsr.sprint_pages(reports) == [
            ("S07", "planning", "sprint-S07-planning.html"),
            ("S07", "review", "sprint-S07-review.html"),
            ("S08", "review", "sprint-S08-review.html"),
        ]


# ── the view comes from sprint.build_view (lazily) ──────────────────────────────

class TestBuildViewWiring:
    def test_generate_calls_sprint_build_view_when_no_view_injected(self, tmp_path, monkeypatch):
        repo = make_repo(tmp_path)
        calls = []

        def fake_build_view(repo_root, sprint_id, today=None, wip_cap=None):
            calls.append((Path(repo_root), sprint_id, today))
            return full_view(repo)

        fake = types.ModuleType("sprint")
        fake.build_view = fake_build_view
        monkeypatch.setitem(sys.modules, "sprint", fake)
        out = gsr.generate(repo, "S07")
        assert calls == [(repo.resolve(), "S07", None)]
        assert out.is_file()

    def test_missing_sprint_record_is_reported_before_build_view(self, tmp_path, monkeypatch):
        repo = make_repo(tmp_path)
        (repo / ".sdlc" / "sprints" / "S07.md").unlink()
        fake = types.ModuleType("sprint")
        fake.build_view = lambda *a, **k: pytest.fail("build_view must not run for a missing sprint")
        monkeypatch.setitem(sys.modules, "sprint", fake)
        with pytest.raises(gsr.SprintNotFound):
            gsr.generate(repo, "S07")

    def test_view_without_sprint_is_not_found(self, tmp_path):
        repo = make_repo(tmp_path)
        with pytest.raises(gsr.SprintNotFound):
            gsr.generate(repo, "S07", view={"sprint": None, "slate": []})

    def test_bad_sprint_id_is_refused(self, tmp_path):
        repo = make_repo(tmp_path)
        with pytest.raises(ValueError):
            gsr.generate(repo, "sprint7", view=full_view(repo))


# ── helpers ─────────────────────────────────────────────────────────────────────

class TestHelpers:
    def test_latest_event_date_picks_the_newest_for_this_sprint(self):
        ledger = [
            {"ts": "2026-09-01T10:00:00+00:00", "event": "ready", "sprint": "S07"},
            {"ts": "2026-09-03T23:30:00Z", "event": "ready", "sprint": "S07"},
            {"ts": "2026-09-09T10:00:00+00:00", "event": "ready", "sprint": "S08"},
        ]
        assert gsr.latest_event_date(ledger, "ready", "S07") == "2026-09-03"
        assert gsr.latest_event_date(ledger, "closed", "S07") is None
        assert gsr.latest_event_date([], "ready", "S07") is None

    def test_read_ledger_skips_malformed_lines(self, tmp_path):
        repo = make_repo(tmp_path)
        entries = gsr.read_ledger(repo)
        assert len(entries) == 9 and all(isinstance(e, dict) for e in entries)
        assert gsr.read_ledger(tmp_path / "nowhere") == []

    def test_cadence_targets_template_brackets_are_unset(self, tmp_path):
        repo = make_repo(tmp_path)
        plan = repo / ".sdlc" / "artifacts" / "03-foundation" / "cadence-plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("- **WIP cap:** no more than **[2]** streams.\n"
                        "- **Review-turnaround target:** [not set]\n", encoding="utf-8")
        assert gsr.cadence_targets(repo) == {"wip_cap": None, "review_wait": None}
        assert gsr.cadence_targets(tmp_path / "nowhere") == {"wip_cap": None, "review_wait": None}

    def test_num_and_esc_are_honest(self):
        assert gsr._num(None) == "no data"
        assert gsr._num(0) == "0"
        assert gsr._esc("") == "&mdash;" and gsr._esc("<b>") == "&lt;b&gt;"

    def test_is_workflow_needs_state_yaml_not_a_bare_sdlc_dir(self, tmp_path):
        repo = make_repo(tmp_path)
        assert gsr.is_workflow(repo) is False
        (repo / ".sdlc" / "state.yaml").write_text("project_name: x\n", encoding="utf-8")
        assert gsr.is_workflow(repo) is True


# ── CLI ─────────────────────────────────────────────────────────────────────────

def run_cli(*args, cwd: Path):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True)


class TestCli:
    def test_help_exits_0_from_any_cwd(self, tmp_path):
        proc = run_cli("--help", cwd=tmp_path)
        assert proc.returncode == 0, proc.stderr
        for flag in ("--state", "--repo", "--sprint", "--kind", "--output"):
            assert flag in proc.stdout
        assert "planning" in proc.stdout and "review" in proc.stdout
        assert not list(tmp_path.iterdir())  # --help does no filesystem work

    def test_unknown_sprint_exits_1(self, tmp_path):
        repo = make_repo(tmp_path)
        proc = run_cli("--repo", str(repo), "--sprint", "S99", cwd=tmp_path)
        assert proc.returncode == 1
        assert "S99" in proc.stderr
        assert not (repo / ".sdlc" / "reports" / "sprint-S99-planning.html").exists()

    def test_bad_sprint_id_exits_1(self, tmp_path):
        repo = make_repo(tmp_path)
        proc = run_cli("--repo", str(repo), "--sprint", "seven", cwd=tmp_path)
        assert proc.returncode == 1 and "not a sprint id" in proc.stderr

    def test_missing_state_file_exits_1(self, tmp_path):
        proc = run_cli("--state", str(tmp_path / ".sdlc" / "state.yaml"), "--sprint", "S07", cwd=tmp_path)
        assert proc.returncode == 1 and "state file not found" in proc.stderr

    def test_state_and_repo_are_mutually_exclusive(self, tmp_path):
        proc = run_cli("--state", "x", "--repo", "y", "--sprint", "S07", cwd=tmp_path)
        assert proc.returncode == 2

    def test_resolve_repo_root_from_state_is_parent_of_sdlc(self, tmp_path):
        repo = make_repo(tmp_path, with_state=True)
        ns = types.SimpleNamespace(state=str(repo / ".sdlc" / "state.yaml"), repo=".")
        assert gsr.resolve_repo_root(ns) == repo.resolve()
        ns = types.SimpleNamespace(state=None, repo=str(repo))
        assert gsr.resolve_repo_root(ns) == repo.resolve()

    def test_cli_end_to_end_with_the_real_sprint_module(self, tmp_path):
        """Integration: only when scripts/sprint.py exists — the view then comes from the real build_view."""
        pytest.importorskip("sprint")
        repo = make_repo(tmp_path, with_state=True)
        proc = run_cli("--state", str(repo / ".sdlc" / "state.yaml"), "--sprint", "S07", cwd=tmp_path)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        out = repo / ".sdlc" / "reports" / "sprint-S07-planning.html"
        assert out.is_file() and "Sprint S07" in out.read_text(encoding="utf-8")
        assert "workflow mode" in proc.stdout


class TestCliJson:
    """`--json` prints one document on stdout; exit codes and the prose path are unchanged (studio-improvements F13)."""

    def test_success_prints_ok_sprint_kind_output_rel_output(self, tmp_path):
        pytest.importorskip("sprint")
        repo = make_repo(tmp_path, with_state=True)
        proc = run_cli("--state", str(repo / ".sdlc" / "state.yaml"), "--sprint", "S07", "--kind", "review", "--json",
                       cwd=tmp_path)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        doc = json.loads(proc.stdout)
        assert doc == {"ok": True, "sprint": "S07", "kind": "review",
                       "output": str((repo / ".sdlc" / "reports" / "sprint-S07-review.html").resolve()),
                       "rel_output": ".sdlc/reports/sprint-S07-review.html"}
        assert (repo / doc["rel_output"]).is_file()
        assert proc.stderr == ""

    def test_default_kind_is_planning_under_json_too(self, tmp_path):
        pytest.importorskip("sprint")
        repo = make_repo(tmp_path)
        proc = run_cli("--repo", str(repo), "--sprint", "S07", "--json", cwd=tmp_path)
        assert proc.returncode == 0, proc.stderr + proc.stdout
        doc = json.loads(proc.stdout)
        assert doc["kind"] == "planning" and doc["rel_output"] == ".sdlc/reports/sprint-S07-planning.html"

    def test_unknown_sprint_is_ok_false_on_stdout_with_the_same_exit_code(self, tmp_path):
        repo = make_repo(tmp_path)
        proc = run_cli("--repo", str(repo), "--sprint", "S99", "--json", cwd=tmp_path)
        assert proc.returncode == 1
        doc = json.loads(proc.stdout)
        assert doc["ok"] is False and "S99" in doc["error"] and set(doc) == {"ok", "error"}
        assert proc.stderr == ""
        assert not (repo / ".sdlc" / "reports" / "sprint-S99-planning.html").exists()

    def test_bad_sprint_id_and_missing_state_are_ok_false_documents(self, tmp_path):
        repo = make_repo(tmp_path)
        proc = run_cli("--repo", str(repo), "--sprint", "seven", "--json", cwd=tmp_path)
        assert proc.returncode == 1 and json.loads(proc.stdout)["ok"] is False
        assert "not a sprint id" in json.loads(proc.stdout)["error"]
        proc = run_cli("--state", str(tmp_path / ".sdlc" / "state.yaml"), "--sprint", "S07", "--json", cwd=tmp_path)
        assert proc.returncode == 1
        assert "state file not found" in json.loads(proc.stdout)["error"]

    def test_the_prose_path_is_byte_identical_without_json(self, tmp_path):
        pytest.importorskip("sprint")
        repo = make_repo(tmp_path, with_state=True)
        proc = run_cli("--state", str(repo / ".sdlc" / "state.yaml"), "--sprint", "S07", cwd=tmp_path)
        out = (repo / ".sdlc" / "reports" / "sprint-S07-planning.html").resolve()
        assert proc.returncode == 0
        assert proc.stdout == f"Sprint S07 planning page written to: {out} (workflow mode)\n"
        proc = run_cli("--repo", str(repo), "--sprint", "S99", cwd=tmp_path)
        assert proc.returncode == 1 and proc.stdout == "" and proc.stderr.startswith("Error: ") and "S99" in proc.stderr

    def test_rel_output_outside_the_repo_is_the_absolute_path(self, tmp_path):
        repo = make_repo(tmp_path)
        elsewhere = tmp_path / "elsewhere" / "page.html"
        assert gsr.rel_output(repo, elsewhere) == str(elsewhere)
        assert gsr.rel_output(repo, repo / ".sdlc" / "reports" / "x.html") == ".sdlc/reports/x.html"


# ── carry-over recurrence sees a mid-sprint `sprint.py carry` (togo-command-center §2.5 row 3) ──

class TestRecurrenceSeesMidSprintCarry:
    def test_review_counts_a_carry_made_without_closing(self, tmp_path):
        """`sprint.py carry` writes close's exact `carried` event, so the review page's per-spec
        recurrence counts it alongside the carries recorded at close — no second ledger, no reshaping."""
        sprint = pytest.importorskip("sprint")
        repo = make_repo(tmp_path)  # S07 open; 0002 in S07; the ledger already holds 0002 carried S06→S07 and S07→S08
        assert sprint.main(["new", "--repo", str(repo), "--sprint", "S09", "--goal", "Next", "--start", "2026-10-26",
                            "--target", "3", "--by", "Priya"]) == 0
        assert sprint.main(["carry", "--repo", str(repo), "--spec", "0002", "--to", "S09",
                            "--reason", "sandbox still down", "--by", "Priya"]) == 0
        carried = [e for e in gsr.read_ledger(repo) if e.get("event") == "carried" and e.get("spec") == "0002"]
        assert len(carried) == 3 and carried[-1]["sprint"] == "S07" and carried[-1]["to_sprint"] == "S09"
        assert set(carried[-1]) == set(carried[0])  # the close path's shape, byte for byte in its keys
        view = full_view(repo, state="closed")
        page = gsr.generate(repo, "S07", kind="review", view=view).read_text(encoding="utf-8")
        assert "<code>0002</code></td><td>3</td>" in page
        assert "sandbox still down" in page  # this sprint's carried/dropped ledger table lists it with its reason
