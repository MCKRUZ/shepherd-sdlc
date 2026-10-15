"""Spec 0039, DS-P4 — data_spec.py: the CLI half of a data spec.

The model (data_spec_model.py) is pure text-in/text-out and has its own tests. What is pinned HERE is
what only a real process against a real directory can show, so every test drives the script as a
subprocess in a repository built under tmp_path (the parent specs are made by running new_spec.py):

  - the link          one call writes BOTH halves — the data spec's `serves:` and the parent's
                      `depends_on` / `data_review` — and the parent differs from before in exactly those
                      two lines, each still carrying its `# comment`
  - D4                a named human's `accepted` data verdict is kept, with a note, never overwritten
  - refusals          a data parent, a self-reference, a cycle, a conflicting `serves` exit 2; a missing or
                      ambiguous spec exits 1 — and a refusal writes NOTHING (every file hashed before/after)
  - honesty           `status` on a repo with no data spec is exactly {"has_data": false, "specs": []};
                      `check` says "not measured" (passed null) for a document that is not there
  - no side effects   `--help` touches nothing; `--repo` mode writes no ledger; `--state` mode appends one
                      four-key line; `status`/`check` never write
  - bytes             CRLF stays CRLF in a parent and in a target spec
"""

import ast
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
import check_spec as cs  # noqa: E402
import data_spec  # noqa: E402
import data_spec_model as dm  # noqa: E402
import sprint_model as sm  # noqa: E402

SCRIPT_PATH = SCRIPTS_DIR / "data_spec.py"


# --- helpers -----------------------------------------------------------------------------------

def run(script, args, cwd):
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script), *args],
        capture_output=True, text=True, encoding="utf-8", cwd=str(cwd),
    )


def data(repo, verb, *args, src=("--repo", ".")):
    """data_spec.py <verb> <src> <args> with cwd = the repo (so `--repo .` is the repo)."""
    return run("data_spec.py", [verb, *src, *args], repo)


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def snapshot(root: Path) -> dict:
    """{relative path: sha256} for every file under `root` — 'nothing was written' means this is equal."""
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def changed_lines(before: str, after: str):
    diff = list(difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0))
    removed = [ln[1:] for ln in diff if ln.startswith("-") and not ln.startswith("---")]
    added = [ln[1:] for ln in diff if ln.startswith("+") and not ln.startswith("+++")]
    return removed, added


def bare_lf(text: str) -> int:
    return sum(1 for i, c in enumerate(text) if c == "\n" and (i == 0 or text[i - 1] != "\r"))


def to_crlf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


def fm_of(path: Path) -> dict:
    return cs.parse_frontmatter(read(path))[0]


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


def build_spec(repo, name="duplicate claim 409", risk="MEDIUM") -> Path:
    """A real build spec, scaffolded by new_spec.py (so its comments and layout are the real ones)."""
    proc = run("new_spec.py", ["--repo", ".", "--name", name, "--risk", risk, "--json"], repo)
    assert proc.returncode == 0, proc.stderr
    return repo / json.loads(proc.stdout)["path"]


def set_key(path: Path, key: str, value: str) -> None:
    write(path, sm.set_frontmatter(read(path), key, value))


def add_state(repo) -> Path:
    state = repo / ".sdlc" / "state.yaml"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("project: {}\n", encoding="utf-8")
    return state


def decision_log(rows) -> str:
    lines = ["# Decision Log", "",
             "| id | decision | owner | opened | due (2 business days) | status |",
             "|----|----------|-------|--------|-----------------------|--------|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def readiness(gap_refs, *, other_section_ref="DL-99") -> str:
    rows = "\n".join(f"| gap {i} | what breaks | low | {ref} |" for i, ref in enumerate(gap_refs, 1))
    return ("# Data Readiness\n\n## Availability & quality\n\n"
            f"Nothing here counts as a gap ({other_section_ref}).\n\n"
            "## Gaps\n\nEach gap routes to the decision log.\n\n"
            "| Gap | Impact | Severity | Decision-log ref |\n|-----|--------|----------|------------------|\n"
            f"{rows}\n\n## PII & risk-tier impact\n\nnone\n")


DATA_DIR = ".sdlc/artifacts/02-design/data"


def finding(doc: dict, name: str) -> dict:
    return next(f for f in doc["findings"] if f["name"] == name)


# --- new: the happy path -----------------------------------------------------------------------

class TestNew:
    def test_creates_the_data_spec_and_fills_context(self, repo):
        parent = build_spec(repo)
        proc = data(repo, "new", "--serves", "0001", "--name", "claims profile", "--json")
        assert proc.returncode == 0, proc.stderr
        doc = json.loads(proc.stdout)
        assert doc["path"] == "specs/0002-claims-profile.md"
        out = repo / doc["path"]
        text = read(out)
        fm = cs.parse_frontmatter(text)[0]
        assert fm["type"] == "data" and fm["serves"] == "0001" and fm["spec"] == "0002"
        assert re.search(r'^serves: "0001"', text, re.MULTILINE)
        context = cs.extract_section(cs.parse_frontmatter(text)[1], "Context")
        assert context is not None
        serves_line = next(ln for ln in context.splitlines() if ln.startswith("**Serves:**"))
        assert f"specs/{parent.name}" in serves_line and "spec 0001" in serves_line
        assert re.search(r"taken \d{4}-\d{2}-\d{2}", context)
        assert "NNNN" not in context

    def test_parent_differs_in_exactly_two_lines_and_keeps_their_comments(self, repo):
        parent = build_spec(repo)
        before = read(parent)
        assert data(repo, "new", "--serves", "0001", "--name", "claims profile").returncode == 0
        removed, added = changed_lines(before, read(parent))
        assert len(removed) == 2 and len(added) == 2
        assert {ln.split(":")[0] for ln in removed} == {"depends_on", "data_review"}
        assert {ln.split(":")[0] for ln in added} == {"depends_on", "data_review"}
        for old in removed:
            key = old.split(":")[0]
            new = next(ln for ln in added if ln.startswith(key + ":"))
            assert "#" in new
            assert new.partition("#")[2] == old.partition("#")[2]
        fm = fm_of(parent)
        assert fm["depends_on"] == "0002" and fm["data_review"] == "pending"

    def test_json_key_set_is_exactly_the_documented_one(self, repo):
        build_spec(repo)
        doc = json.loads(data(repo, "new", "--serves", "0001", "--name", "claims profile", "--json").stdout)
        assert set(doc) == {"path", "id", "name", "risk", "serves", "parent_path", "parent",
                            "context_refs", "unresolved_refs"}
        assert set(doc["parent"]) == {"depends_on_before", "depends_on_after", "data_review_before",
                                      "data_review_after", "data_review_note"}
        assert set(doc["context_refs"]) == {"BR", "DL", "ADR", "DOC"}
        assert doc["id"] == "0002" and doc["name"] == "claims-profile" and doc["risk"] == "MEDIUM"
        assert doc["serves"] == "0001" and doc["parent_path"] == "specs/0001-duplicate-claim-409.md"
        assert doc["parent"]["depends_on_before"] == "" and doc["parent"]["depends_on_after"] == "0002"
        assert doc["parent"]["data_review_before"] == "" and doc["parent"]["data_review_after"] == "pending"
        assert doc["parent"]["data_review_note"] is None
        assert "refs_scanned" not in doc and "unread" not in doc

    def test_text_output_is_new_specs_lines_plus_the_serves_line(self, repo):
        build_spec(repo)
        proc = data(repo, "new", "--serves", "0001", "--name", "claims profile", "--risk", "high")
        assert proc.returncode == 0
        lines = proc.stdout.splitlines()
        assert len(lines) == 5
        assert lines[0].startswith("Spec created: ") and lines[0].endswith("0002-claims-profile.md")
        assert lines[1] == "  Risk tier: HIGH"
        assert lines[2] == "  Serves: spec 0001 (parent depends_on: 0002; data_review: pending)"
        assert lines[3] == "  Next: fill the body (Goal, Why, Scope, Acceptance Checks, plans), then validate:"
        assert lines[4].startswith("    uv run scripts/check_spec.py --spec ")
        assert fm_of(repo / "specs" / "0002-claims-profile.md")["risk"] == "HIGH"

    def test_an_accepted_data_verdict_is_kept_with_a_note(self, repo):
        parent = build_spec(repo)
        set_key(parent, "data_review", "accepted")
        doc = json.loads(data(repo, "new", "--serves", "0001", "--name", "claims profile", "--json").stdout)
        assert doc["parent"]["data_review_before"] == "accepted"
        assert doc["parent"]["data_review_after"] == "accepted"
        assert doc["parent"]["data_review_note"]
        fm = fm_of(parent)
        assert fm["data_review"] == "accepted" and fm["depends_on"] == "0002"

    def test_depends_on_is_appended_not_replaced(self, repo):
        parent = build_spec(repo)
        set_key(parent, "depends_on", "0009")
        doc = json.loads(data(repo, "new", "--serves", "0001", "--name", "claims profile", "--json").stdout)
        assert doc["parent"]["depends_on_before"] == "0009"
        assert doc["parent"]["depends_on_after"] == "0009,0002"
        assert fm_of(parent)["depends_on"] == "0009,0002"

    def test_context_carries_the_parents_checks_and_resolved_refs(self, repo):
        parent = build_spec(repo)
        text = read(parent)
        body = cs.parse_frontmatter(text)[1]
        assert cs.extract_section(body, "Acceptance Checks") is not None
        text = dm.replace_section_body(
            text, "Acceptance Checks",
            '- [ ] a duplicate submission returns 409 with body { "error": "duplicate claim" }')
        text = dm.replace_section_body(
            text, "Why", "Per BR-03, DL-07, ADR-004 and DOC-002 the claim must be unique.")
        write(parent, text)
        rules = repo / ".sdlc" / "artifacts" / "01-requirements" / "business-rules.md"
        rules.parent.mkdir(parents=True)
        rules.write_text("# Business rules\n\n| id | rule |\n|----|------|\n| BR-03 | one claim per id |\n",
                         encoding="utf-8")
        adr = repo / "docs" / "adr" / "ADR-004-keys.md"
        adr.parent.mkdir(parents=True)
        adr.write_text("# ADR-004: idempotency keys\n\nbody\n", encoding="utf-8")

        doc = json.loads(data(repo, "new", "--serves", "0001", "--name", "claims profile", "--json").stdout)
        assert doc["context_refs"] == {"BR": ["BR-03"], "DL": ["DL-07"], "ADR": ["ADR-004"], "DOC": ["DOC-002"]}
        assert doc["unresolved_refs"] == ["DL-07", "DOC-002"]
        context = cs.extract_section(cs.parse_frontmatter(read(repo / doc["path"]))[1], "Context")
        assert '- [ ] a duplicate submission returns 409 with body { "error": "duplicate claim" }' in context
        assert "- BR-03 — `.sdlc/artifacts/01-requirements/business-rules.md`" in context
        assert "- ADR-004 — `docs/adr/ADR-004-keys.md`" in context
        assert "- DL-07 — not found in this repository" in context
        assert "- DOC-002 — not found in this repository" in context

    def test_a_doc_resolves_to_its_summary_not_to_the_registry_row(self, repo):
        parent = build_spec(repo)
        write(parent, dm.replace_section_body(read(parent), "Why", "The vendor feed in DOC-004 is the source."))
        registry = repo / ".sdlc" / "artifacts" / "00-discovery" / "document-registry.md"
        registry.parent.mkdir(parents=True)
        registry.write_text("# Document Registry\n\n| ID | File | Priority |\n|----|------|----------|\n"
                            "| DOC-004 | vendor-feed.pdf | 1 |\n", encoding="utf-8")
        summary = repo / ".sdlc" / "context" / "intake" / "DOC-004-vendor-feed.md"
        summary.parent.mkdir(parents=True)
        summary.write_text("# DOC-004: vendor-feed.pdf\n\n## Document Overview\nThe feed.\n", encoding="utf-8")
        (summary.parent / "index.md").write_text("# Document Index\n\n- DOC-004 · vendor-feed.pdf · pdf — The feed.\n",
                                                 encoding="utf-8")

        doc = json.loads(data(repo, "new", "--serves", "0001", "--name", "claims profile", "--json").stdout)
        assert doc["unresolved_refs"] == []
        context = cs.extract_section(cs.parse_frontmatter(read(repo / doc["path"]))[1], "Context")
        assert "- DOC-004 — `.sdlc/context/intake/DOC-004-vendor-feed.md`" in context
        assert "document-registry.md" not in context

    def test_an_unrelated_existing_cycle_does_not_block_a_new_link(self, repo):
        build_spec(repo, "parent")
        b = build_spec(repo, "b")
        c = build_spec(repo, "c")
        set_key(b, "depends_on", "0003")
        set_key(c, "depends_on", "0002")
        proc = data(repo, "new", "--serves", "0001", "--name", "claims profile", "--json")
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)["id"] == "0004"

    def test_without_a_state_file_no_ledger_is_written(self, repo):
        build_spec(repo)
        assert data(repo, "new", "--serves", "0001", "--name", "claims profile").returncode == 0
        assert list(repo.rglob("spec-log.jsonl")) == []
        assert not (repo / ".sdlc").exists()

    def test_state_mode_appends_exactly_one_four_key_ledger_line(self, repo):
        build_spec(repo)
        state = add_state(repo)
        proc = data(repo, "new", "--serves", "0001", "--name", "claims profile", "--json",
                    src=("--state", str(state.relative_to(repo))))
        assert proc.returncode == 0, proc.stderr
        ledger = repo / ".sdlc" / "metrics" / "spec-log.jsonl"
        lines = ledger.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert set(event) == {"ts", "event", "spec", "serves"}
        assert event["event"] == "data_spec_linked" and event["spec"] == "0002" and event["serves"] == "0001"

    def test_a_failed_ledger_append_is_reported_as_drift(self, repo):
        build_spec(repo)
        state = add_state(repo)
        (repo / ".sdlc" / "metrics").write_text("not a directory", encoding="utf-8")
        proc = data(repo, "new", "--serves", "0001", "--name", "claims profile", "--json",
                    src=("--state", str(state.relative_to(repo))))
        assert proc.returncode == 1
        assert proc.stdout == ""
        assert proc.stderr.startswith("DRIFT:")
        assert (repo / "specs" / "0002-claims-profile.md").exists()  # the writes happened; the message says so


# --- new / target: refusals and errors ---------------------------------------------------------

class TestRefusals:
    def test_a_data_parent_is_refused_and_nothing_is_written(self, repo):
        build_spec(repo)
        assert data(repo, "new", "--serves", "0001", "--name", "claims profile").returncode == 0
        before = snapshot(repo)
        proc = data(repo, "new", "--serves", "0002", "--name", "second", "--json")
        assert proc.returncode == 2
        assert proc.stdout == "" and "data spec" in proc.stderr
        assert snapshot(repo) == before

    def test_target_onto_a_data_parent_is_refused(self, repo):
        build_spec(repo, "parent")
        assert data(repo, "new", "--serves", "0001", "--name", "claims profile").returncode == 0
        build_spec(repo, "third")
        before = snapshot(repo)
        proc = data(repo, "target", "--spec", "0003", "--serves", "0002")
        assert proc.returncode == 2
        assert snapshot(repo) == before

    def test_target_self_reference_is_refused(self, repo):
        build_spec(repo)
        before = snapshot(repo)
        proc = data(repo, "target", "--spec", "0001", "--serves", "0001", "--json")
        assert proc.returncode == 2
        assert proc.stdout == "" and proc.stderr
        assert snapshot(repo) == before

    @pytest.mark.parametrize("deps_of_target", ["0001", "0002"])
    def test_a_cycle_is_refused_and_both_files_are_unchanged(self, repo, deps_of_target):
        parent = build_spec(repo, "parent")
        middle = build_spec(repo, "middle")
        target = build_spec(repo, "target")
        if deps_of_target == "0001":      # 0003 -> 0001, and the link adds 0001 -> 0003
            set_key(target, "depends_on", "0001")
        else:                             # 0003 -> 0002 -> 0001, and the link adds 0001 -> 0003
            set_key(target, "depends_on", "0002")
            set_key(middle, "depends_on", "0001")
        before = snapshot(repo)
        proc = data(repo, "target", "--spec", "0003", "--serves", "0001", "--json")
        assert proc.returncode == 2
        assert proc.stdout == "" and "cycle" in proc.stderr.lower()
        assert snapshot(repo) == before
        assert "0003" not in fm_of(parent).get("depends_on", "")

    def test_a_cycle_is_still_found_when_an_unrelated_cycle_sits_in_specs(self, repo):
        # 0001 <-> 0002 is nobody's doing here, but it is what a back-edge DFS reports; the link
        # 0005 -> 0006 would close 0005 -> 0006 -> 0003 -> 0002 -> 0001 -> 0005
        specs = {n: build_spec(repo, f"s{n}") for n in range(1, 7)}
        set_key(specs[1], "depends_on", "0002,0005")
        set_key(specs[2], "depends_on", "0001")
        set_key(specs[3], "depends_on", "0002")
        set_key(specs[6], "depends_on", "0003")
        before = snapshot(repo)
        proc = data(repo, "target", "--spec", "0006", "--serves", "0005", "--json")
        assert proc.returncode == 2
        assert proc.stdout == "" and "dependency cycle" in proc.stderr
        assert "0005 -> 0006 -> 0003 -> 0002 -> 0001 -> 0005" in proc.stderr
        assert snapshot(repo) == before
        assert snapshot(repo / "specs") == {k.removeprefix("specs/"): v for k, v in before.items()
                                            if k.startswith("specs/")}
        assert "0006" not in fm_of(specs[5]).get("depends_on", "")

    def test_an_unrelated_cycle_alone_does_not_stop_target_from_linking(self, repo):
        specs = {n: build_spec(repo, f"s{n}") for n in range(1, 5)}
        set_key(specs[1], "depends_on", "0002")
        set_key(specs[2], "depends_on", "0001")
        proc = data(repo, "target", "--spec", "0004", "--serves", "0003", "--json")
        assert proc.returncode == 0, proc.stderr
        assert fm_of(specs[3])["depends_on"] == "0004"
        assert fm_of(specs[4])["type"] == "data" and fm_of(specs[4])["serves"] == "0003"
        assert fm_of(specs[1])["depends_on"] == "0002" and fm_of(specs[2])["depends_on"] == "0001"

    def test_the_plain_cycle_is_still_refused_and_names_the_loop(self, repo):
        build_spec(repo, "parent")
        build_spec(repo, "middle")
        target = build_spec(repo, "target")
        set_key(target, "depends_on", "0001")
        before = snapshot(repo)
        proc = data(repo, "target", "--spec", "0003", "--serves", "0001")
        assert proc.returncode == 2
        assert "0001 -> 0003 -> 0001" in proc.stderr
        assert snapshot(repo) == before

    @pytest.mark.parametrize("verb", ["new", "target"])
    @pytest.mark.parametrize("block", ['depends_on:\n  - "0003"', 'depends_on:   # was a list\n  - "0003"\n  - 0004'])
    def test_a_block_list_depends_on_is_refused_and_nothing_is_written(self, repo, verb, block):
        parent = build_spec(repo, "parent")
        build_spec(repo, "target")
        text = read(parent)
        line = next(ln for ln in text.splitlines() if ln.startswith("depends_on:"))
        write(parent, text.replace(line, block, 1))
        before = snapshot(repo)
        argv = (["new", "--serves", "0001", "--name", "claims profile"] if verb == "new"
                else ["target", "--spec", "0002", "--serves", "0001"])
        proc = data(repo, *argv, "--json")
        assert proc.returncode == 1
        assert proc.stdout == "" and "YAML list" in proc.stderr and "comma-separated" in proc.stderr
        assert snapshot(repo) == before

    def test_a_conflicting_existing_serves_is_refused(self, repo):
        build_spec(repo, "one")
        assert data(repo, "new", "--serves", "0001", "--name", "claims profile").returncode == 0
        build_spec(repo, "three")
        before = snapshot(repo)
        proc = data(repo, "target", "--spec", "0002", "--serves", "0003")
        assert proc.returncode == 2
        assert "0001" in proc.stderr
        assert snapshot(repo) == before

    def test_a_missing_parent_is_exit_1(self, repo):
        build_spec(repo)
        before = snapshot(repo)
        proc = data(repo, "new", "--serves", "0099", "--name", "claims profile", "--json")
        assert proc.returncode == 1
        assert proc.stdout == "" and "0099" in proc.stderr
        assert snapshot(repo) == before

    def test_target_with_a_missing_spec_or_parent_is_exit_1(self, repo):
        build_spec(repo)
        assert data(repo, "target", "--spec", "0099", "--serves", "0001").returncode == 1
        assert data(repo, "target", "--spec", "0001", "--serves", "0099").returncode == 1

    def test_two_files_with_one_id_are_exit_1_and_both_are_named(self, repo):
        parent = build_spec(repo, "a")
        (repo / "specs" / "0001-b.md").write_bytes(parent.read_bytes())
        before = snapshot(repo)
        proc = data(repo, "new", "--serves", "0001", "--name", "claims profile", "--json")
        assert proc.returncode == 1
        assert "0001-a.md" in proc.stderr and "0001-b.md" in proc.stderr
        assert proc.stdout == ""
        assert snapshot(repo) == before

    def test_a_parent_with_no_frontmatter_is_exit_1(self, repo):
        (repo / "specs").mkdir()
        (repo / "specs" / "0001-bare.md").write_text("# no frontmatter here\n", encoding="utf-8")
        before = snapshot(repo)
        proc = data(repo, "new", "--serves", "0001", "--name", "claims profile")
        assert proc.returncode == 1
        assert snapshot(repo) == before

    def test_a_bad_risk_and_an_empty_slug_are_exit_1_with_stdout_empty_under_json(self, repo):
        build_spec(repo)
        proc = data(repo, "new", "--serves", "0001", "--name", "x", "--risk", "URGENT", "--json")
        assert proc.returncode == 1 and proc.stdout == ""
        assert "Error: --risk must be one of HIGH, MEDIUM, LOW (got 'URGENT')" in proc.stderr
        proc = data(repo, "new", "--serves", "0001", "--name", "!!!", "--json")
        assert proc.returncode == 1 and proc.stdout == "" and "slug" in proc.stderr
        assert not (repo / "specs" / "0002-.md").exists()

    @pytest.mark.parametrize("bad", ["7", "abcd", "00001", ""])
    def test_a_malformed_spec_id_is_a_usage_error(self, repo, bad):
        build_spec(repo)
        proc = data(repo, "new", "--serves", bad, "--name", "claims profile", "--json")
        assert proc.returncode == 2 and proc.stdout == ""

    def test_a_missing_state_file_is_a_usage_error_for_every_verb(self, repo):
        for argv in (["new", "--serves", "0001", "--name", "x"],
                     ["target", "--spec", "0002", "--serves", "0001"],
                     ["status"], ["check", "--spec", "0001"]):
            proc = run("data_spec.py", [*argv, "--state", ".sdlc/state.yaml", "--json"], repo)
            assert proc.returncode == 2 and proc.stdout == "", argv

    def test_state_and_repo_together_are_a_usage_error(self, repo):
        add_state(repo)
        proc = run("data_spec.py", ["status", "--state", ".sdlc/state.yaml", "--repo", "."], repo)
        assert proc.returncode == 2


# --- target ------------------------------------------------------------------------------------

class TestTarget:
    def test_adds_context_once_and_is_idempotent(self, repo):
        parent = build_spec(repo, "parent")
        target = build_spec(repo, "target")
        proc = data(repo, "target", "--spec", "0002", "--serves", "0001", "--json")
        assert proc.returncode == 0, proc.stderr
        doc = json.loads(proc.stdout)
        assert set(doc) == {"path", "id", "serves", "changed", "parent", "context_refs", "unresolved_refs"}
        assert doc["path"] == "specs/0002-target.md" and doc["id"] == "0002" and doc["serves"] == "0001"
        assert doc["changed"] == {"type": True, "serves": True, "context_added": True}
        text = read(target)
        assert len(re.findall(r"^## Context\s*$", text, re.MULTILINE)) == 1
        fm = cs.parse_frontmatter(text)[0]
        assert fm["type"] == "data" and fm["serves"] == "0001"
        assert "**Serves:** spec 0001" in text
        assert fm_of(parent)["depends_on"] == "0002" and fm_of(parent)["data_review"] == "pending"

        after_first = snapshot(repo)
        proc = data(repo, "target", "--spec", "0002", "--serves", "0001", "--json")
        assert proc.returncode == 0
        again = json.loads(proc.stdout)
        assert again["changed"] == {"type": False, "serves": False, "context_added": False}
        assert again["parent"]["depends_on_before"] == again["parent"]["depends_on_after"] == "0002"
        assert snapshot(repo) == after_first

    def test_the_target_spec_gains_a_context_section_at_the_end_of_the_file(self, repo):
        build_spec(repo, "parent")
        target = build_spec(repo, "target")
        before = read(target)
        data(repo, "target", "--spec", "0002", "--serves", "0001")
        after = read(target)
        # the frontmatter edits aside, nothing already in the body moved: the section is appended
        assert after.endswith("\n") and "\n## Context\n" in after
        assert after.index("\n## Context\n") > after.index("\n## Decision List\n")
        assert len(after) > len(before)

    def test_an_existing_context_section_is_not_added_again(self, repo):
        build_spec(repo, "parent")
        assert data(repo, "new", "--serves", "0001", "--name", "claims profile").returncode == 0
        before = snapshot(repo)
        proc = data(repo, "target", "--spec", "0002", "--serves", "0001", "--json")
        assert proc.returncode == 0
        assert json.loads(proc.stdout)["changed"] == {"type": False, "serves": False, "context_added": False}
        assert snapshot(repo) == before

    def test_state_mode_ledgers_the_first_run_only(self, repo):
        build_spec(repo, "parent")
        build_spec(repo, "target")
        state = add_state(repo)
        src = ("--state", str(state.relative_to(repo)))
        assert data(repo, "target", "--spec", "0002", "--serves", "0001", src=src).returncode == 0
        assert data(repo, "target", "--spec", "0002", "--serves", "0001", src=src).returncode == 0
        lines = (repo / ".sdlc" / "metrics" / "spec-log.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1 and json.loads(lines[0])["event"] == "data_spec_linked"


# --- status ------------------------------------------------------------------------------------

class TestStatus:
    def test_no_data_spec_is_exactly_has_data_false(self, repo):
        build_spec(repo)
        before = snapshot(repo)
        proc = data(repo, "status", "--json")
        assert proc.returncode == 0
        assert json.loads(proc.stdout) == {"has_data": False, "specs": []}
        assert not re.search(r"\b0\b", proc.stdout)  # no count, no zero anywhere
        text = data(repo, "status")
        assert text.returncode == 0 and text.stdout.strip() == "No data specs."
        assert snapshot(repo) == before

    def test_a_repo_with_no_specs_directory_says_the_same(self, repo):
        proc = data(repo, "status", "--json")
        assert proc.returncode == 0
        assert json.loads(proc.stdout) == {"has_data": False, "specs": []}
        assert not (repo / "specs").exists()

    def test_after_new_the_row_shows_the_link_and_no_acceptance_due(self, repo):
        build_spec(repo)
        data(repo, "new", "--serves", "0001", "--name", "claims profile")
        before = snapshot(repo)
        doc = json.loads(data(repo, "status", "--json").stdout)
        assert doc["has_data"] is True and len(doc["specs"]) == 1
        row = doc["specs"][0]
        assert row == {"id": "0002", "serves": "0001", "status": "draft", "parent_found": True,
                       "parent_depends_on_has_me": True, "parent_data_review": "pending",
                       "acceptance_due": False}
        text = data(repo, "status").stdout.strip()
        assert text == ("0002 serves 0001 — status draft; in parent depends_on: yes; "
                        "parent data_review: pending; acceptance due: no")
        assert snapshot(repo) == before

    def test_a_merged_data_spec_whose_parent_is_not_accepted_is_acceptance_due(self, repo):
        build_spec(repo)
        data(repo, "new", "--serves", "0001", "--name", "claims profile")
        spec = repo / "specs" / "0002-claims-profile.md"
        write(spec, re.sub(r"^status: draft", "status: merged", read(spec), count=1, flags=re.MULTILINE))
        row = json.loads(data(repo, "status", "--json").stdout)["specs"][0]
        assert row["status"] == "merged" and row["acceptance_due"] is True
        assert data(repo, "status").stdout.strip().endswith("acceptance due: yes")

    def test_a_missing_parent_claims_nothing_about_it(self, repo):
        build_spec(repo)
        data(repo, "new", "--serves", "0001", "--name", "claims profile")
        (repo / "specs" / "0001-duplicate-claim-409.md").unlink()
        row = json.loads(data(repo, "status", "--json").stdout)["specs"][0]
        assert row["parent_found"] is False and row["parent_depends_on_has_me"] is None
        assert row["parent_data_review"] is None and row["acceptance_due"] is False
        assert "parent not found" in data(repo, "status").stdout

    def test_spec_filter_names_one_data_spec(self, repo):
        build_spec(repo, "parent")
        data(repo, "new", "--serves", "0001", "--name", "first")
        data(repo, "new", "--serves", "0001", "--name", "second")
        rows = json.loads(data(repo, "status", "--spec", "0003", "--json").stdout)["specs"]
        assert [r["id"] for r in rows] == ["0003"]
        every = json.loads(data(repo, "status", "--json").stdout)["specs"]
        assert [r["id"] for r in every] == ["0002", "0003"]

    def test_spec_filter_on_a_build_spec_is_not_a_data_spec(self, repo):
        build_spec(repo)
        proc = data(repo, "status", "--spec", "0001", "--json")
        assert proc.returncode == 0
        assert json.loads(proc.stdout) == {"has_data": False, "specs": []}


# --- check -------------------------------------------------------------------------------------

class TestCheck:
    def make_data_spec(self, repo, why=None):
        parent = build_spec(repo)
        if why:
            write(parent, dm.replace_section_body(read(parent), "Why", why))
        assert data(repo, "new", "--serves", "0001", "--name", "claims profile").returncode == 0
        return repo / "specs" / "0002-claims-profile.md"

    def test_absent_documents_are_not_measured_and_exit_0(self, repo):
        self.make_data_spec(repo)
        before = snapshot(repo)
        proc = data(repo, "check", "--spec", "0002", "--json")
        assert proc.returncode == 0
        doc = json.loads(proc.stdout)
        assert doc["spec"] == "0002"
        assert [f["name"] for f in doc["findings"]] == [
            "context-coverage", "readiness-gaps-owned", "handoff-present"]
        gaps = finding(doc, "readiness-gaps-owned")
        assert gaps["passed"] is None and "not measured" in gaps["detail"]
        assert gaps["detail"] == "not measured — data-readiness.md not present"
        hand = finding(doc, "handoff-present")
        assert hand["passed"] is None and hand["detail"] == "not measured — data-handoff.md not present"
        assert finding(doc, "context-coverage")["passed"] is True
        assert snapshot(repo) == before

    def test_text_form_has_one_line_per_finding(self, repo):
        self.make_data_spec(repo)
        proc = data(repo, "check", "--spec", "0002")
        assert proc.returncode == 0
        lines = proc.stdout.splitlines()
        assert len(lines) == 3
        assert lines[0].startswith("PASS") and "context-coverage" in lines[0]
        assert lines[1].startswith("n/a") and "readiness-gaps-owned" in lines[1]
        assert lines[2].startswith("n/a") and "handoff-present" in lines[2]

    def test_context_coverage_names_what_the_context_lost(self, repo):
        spec = self.make_data_spec(repo, why="Per BR-03 and DL-07 the claim must be unique.")
        assert finding(json.loads(data(repo, "check", "--spec", "0002", "--json").stdout),
                       "context-coverage")["passed"] is True
        text = read(spec)
        write(spec, text.replace("- BR-03 — not found in this repository\n", "- none\n"))
        result = finding(json.loads(data(repo, "check", "--spec", "0002", "--json").stdout), "context-coverage")
        assert result["passed"] is False and "BR-03" in result["detail"] and "DL-07" not in result["detail"]
        assert data(repo, "check", "--spec", "0002").stdout.splitlines()[0].startswith("FAIL")

    def test_context_coverage_is_null_when_the_parent_is_not_there(self, repo):
        self.make_data_spec(repo)
        (repo / "specs" / "0001-duplicate-claim-409.md").unlink()
        result = finding(json.loads(data(repo, "check", "--spec", "0002", "--json").stdout), "context-coverage")
        assert result["passed"] is None and "parent not found" in result["detail"]

    def test_gaps_with_an_owner_in_the_decision_log_pass(self, repo):
        self.make_data_spec(repo)
        docs = repo / DATA_DIR
        docs.mkdir(parents=True)
        (docs / "data-readiness.md").write_text(readiness(["DL-01"]), encoding="utf-8")
        (repo / ".sdlc" / "decision-log.md").write_text(
            decision_log([["DL-01", "Fail closed?", "@priya-n", "2026-10-01", "2026-10-05", "open"]]),
            encoding="utf-8")
        result = finding(json.loads(data(repo, "check", "--spec", "0002", "--json").stdout),
                         "readiness-gaps-owned")
        assert result["passed"] is True and "DL-01" in result["detail"]
        assert "DL-99" not in result["detail"]          # a DL outside the Gaps section is not a gap

    def test_unowned_and_missing_gaps_are_named(self, repo):
        self.make_data_spec(repo)
        docs = repo / DATA_DIR
        docs.mkdir(parents=True)
        (docs / "data-readiness.md").write_text(readiness(["DL-01", "DL-02", "DL-09"]), encoding="utf-8")
        (repo / ".sdlc" / "decision-log.md").write_text(decision_log([
            ["DL-01", "Fail closed?", "@priya-n", "2026-10-01", "2026-10-05", "open"],
            ["DL-02", "Which source wins?", "[name/role]", "2026-10-01", "2026-10-05", "open"],
        ]), encoding="utf-8")
        result = finding(json.loads(data(repo, "check", "--spec", "0002", "--json").stdout),
                         "readiness-gaps-owned")
        assert result["passed"] is False
        assert "DL-02" in result["detail"] and "DL-09" in result["detail"] and "DL-01" not in result["detail"]

    def test_a_read_readiness_file_that_names_no_decision_is_a_real_zero(self, repo):
        self.make_data_spec(repo)
        docs = repo / DATA_DIR
        docs.mkdir(parents=True)
        (docs / "data-readiness.md").write_text(readiness(["[DL-NN]"]), encoding="utf-8")
        result = finding(json.loads(data(repo, "check", "--spec", "0002", "--json").stdout),
                         "readiness-gaps-owned")
        assert result["passed"] is False and result["detail"] == "1 gap(s), 0 reference a DL-NN"

    def readiness_result(self, repo, text):
        self.make_data_spec(repo)
        docs = repo / DATA_DIR
        docs.mkdir(parents=True)
        (docs / "data-readiness.md").write_text(text, encoding="utf-8")
        return finding(json.loads(data(repo, "check", "--spec", "0002", "--json").stdout), "readiness-gaps-owned")

    def test_a_gaps_table_with_only_its_header_records_no_gap_and_passes(self, repo):
        result = self.readiness_result(repo, readiness([]))
        assert result["passed"] is True and result["detail"] == "no gaps recorded"

    def test_a_gaps_table_with_only_template_stand_ins_records_no_gap_and_passes(self, repo):
        stand_ins = ("| [e.g. field missing for X% of records] | [what breaks] | [low / med / high] | [DL-NN] |\n"
                     "| [...] | [...] | [...] | [...] |")
        text = readiness([]).replace("|-----|--------|----------|------------------|\n",
                                     "|-----|--------|----------|------------------|\n" + stand_ins + "\n")
        assert stand_ins in text
        result = self.readiness_result(repo, text)
        assert result["passed"] is True and result["detail"] == "no gaps recorded"

    def test_the_unfilled_data_readiness_template_records_no_gap(self, repo):
        template = Path(__file__).resolve().parents[2] / "templates" / "phases" / "02-design" / "data" / "data-readiness.md"
        result = self.readiness_result(repo, template.read_text(encoding="utf-8"))
        assert result["passed"] is True and result["detail"] == "no gaps recorded"

    def test_real_gaps_that_cite_no_decision_fail_with_their_count(self, repo):
        result = self.readiness_result(repo, readiness(["", "n/a"]))
        assert result["passed"] is False and result["detail"] == "2 gap(s), 0 reference a DL-NN"

    def test_a_real_gap_among_stand_ins_is_still_a_gap(self, repo):
        text = readiness([]).replace("|-----|--------|----------|------------------|\n",
                                     "|-----|--------|----------|------------------|\n"
                                     "| [...] | [...] | [...] | [...] |\n| phone is missing | cannot dedupe | low | |\n")
        result = self.readiness_result(repo, text)
        assert result["passed"] is False and result["detail"] == "1 gap(s), 0 reference a DL-NN"

    def test_a_missing_gaps_section_still_fails(self, repo):
        result = self.readiness_result(repo, "# Data Readiness\n\n## Availability & quality\n\nfine\n")
        assert result["passed"] is False and result["detail"] == "no ## Gaps section — 0 gaps reference a DL-NN"

    def test_a_decision_cited_in_prose_under_gaps_is_still_checked_against_the_log(self, repo):
        text = "# Data Readiness\n\n## Gaps\n\nOne gap, tracked as DL-07.\n\n## PII & risk-tier impact\n\nnone\n"
        result = self.readiness_result(repo, text)
        assert result["passed"] is False and "DL-07" in result["detail"]

    def test_standalone_repo_reads_the_documents_beside_the_repo_root(self, repo):
        self.make_data_spec(repo)
        (repo / "data-readiness.md").write_text(readiness(["DL-01"]), encoding="utf-8")
        (repo / "decision-log.md").write_text(
            decision_log([["DL-01", "Fail closed?", "@priya-n", "2026-10-01", "2026-10-05", "open"]]),
            encoding="utf-8")
        result = finding(json.loads(data(repo, "check", "--spec", "0002", "--json").stdout),
                         "readiness-gaps-owned")
        assert result["passed"] is True

    def test_state_mode_reads_the_workflow_data_directory(self, repo):
        self.make_data_spec(repo)
        state = add_state(repo)
        docs = repo / DATA_DIR
        docs.mkdir(parents=True)
        (docs / "data-handoff.md").write_text(
            "# Data Handoff\n\n## Smoke tests\n\nRun `pytest tests/smoke` — output: https://ci.example/run/42\n",
            encoding="utf-8")
        doc = json.loads(data(repo, "check", "--spec", "0002", "--json",
                              src=("--state", str(state.relative_to(repo)))).stdout)
        assert finding(doc, "handoff-present")["passed"] is True

    @pytest.mark.parametrize("smoke, expected", [
        ("Run `pytest tests/smoke`; output linked: [run 42](https://ci.example/run/42)", True),
        ("[The command that runs the smoke tests, and a link to the output]", False),
        ("Run <command>, output at https://ci.example/run/42", False),
        ("", False),
        ("- [x] smoke passed — [run 42](https://ci.example/run/42)", True),
        ("- [X] smoke passed\n- [ ] rerun after the backfill: [run 43](https://ci.example/run/43)", True),
        ("- [x] [the command that ran, and the output link]", False),
        ("- [ ] [fill in]", False),
    ])
    def test_handoff_present_reads_the_smoke_tests_section(self, repo, smoke, expected):
        self.make_data_spec(repo)
        docs = repo / DATA_DIR
        docs.mkdir(parents=True)
        (docs / "data-handoff.md").write_text(
            "# Data Handoff\n\n## What is live\n\n[a placeholder here is not in Smoke tests]\n\n"
            f"## Smoke tests\n\n<!-- guidance [with brackets] stays out of the count -->\n{smoke}\n\n"
            "## What is left\n\n- [ ] [later]\n", encoding="utf-8")
        result = finding(json.loads(data(repo, "check", "--spec", "0002", "--json").stdout), "handoff-present")
        assert result["passed"] is expected, result

    def test_an_unknown_spec_is_reported_not_crashed(self, repo):
        build_spec(repo)
        proc = data(repo, "check", "--spec", "0099", "--json")
        assert proc.returncode == 0
        doc = json.loads(proc.stdout)
        assert doc["spec"] == "0099"
        assert doc["findings"][0]["passed"] is False and "0099" in doc["findings"][0]["detail"]


# --- --all-branches ----------------------------------------------------------------------------

def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false",
         "-c", "core.autocrlf=false", *args],
        cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8")
    return done.stdout.strip()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
class TestAllBranches:
    def test_another_branchs_spec_id_is_not_reused(self, repo):
        git(repo, "init", "-q")
        build_spec(repo)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base")
        trunk = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        git(repo, "checkout", "-q", "-b", "other")
        (repo / "specs" / "0005-x.md").write_text('---\nspec: "0005"\n---\n', encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "other work")
        git(repo, "checkout", "-q", trunk)

        local = json.loads(data(repo, "new", "--serves", "0001", "--name", "local only", "--json").stdout)
        assert local["id"] == "0002" and "refs_scanned" not in local

        proc = data(repo, "new", "--serves", "0001", "--name", "claims profile", "--all-branches", "--json")
        assert proc.returncode == 0, proc.stderr
        doc = json.loads(proc.stdout)
        assert doc["id"] == "0006" and doc["path"] == "specs/0006-claims-profile.md"
        assert "refs/heads/other" in doc["refs_scanned"] and f"refs/heads/{trunk}" in doc["refs_scanned"]
        assert doc["unread"] == []
        assert (repo / doc["path"]).exists()

    def test_text_mode_says_how_many_branches_were_checked(self, repo):
        git(repo, "init", "-q")
        build_spec(repo)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base")
        proc = data(repo, "new", "--serves", "0001", "--name", "claims profile", "--all-branches")
        assert proc.returncode == 0
        assert "Ids checked on 1 branch(es)" in proc.stdout

    def test_outside_a_git_repository_it_proceeds_locally(self, repo):
        build_spec(repo)
        proc = data(repo, "new", "--serves", "0001", "--name", "claims profile", "--all-branches", "--json")
        assert proc.returncode == 0, proc.stderr
        doc = json.loads(proc.stdout)
        assert doc["id"] == "0002" and doc["refs_scanned"] == [] and doc["unread"] == []


# --- bytes: line endings -----------------------------------------------------------------------

class TestLineEndings:
    def test_a_crlf_parent_stays_crlf_after_linking(self, repo):
        parent = build_spec(repo)
        crlf_text = to_crlf(read(parent))
        write(parent, crlf_text)
        proc = data(repo, "new", "--serves", "0001", "--name", "claims profile", "--json")
        assert proc.returncode == 0, proc.stderr
        after = read(parent)
        assert "\r\n" in after and bare_lf(after) == 0
        fm = cs.parse_frontmatter(after)[0]
        assert fm["depends_on"] == "0002" and fm["data_review"] == "pending"
        removed, added = changed_lines(crlf_text, after)
        assert len(removed) == 2 and len(added) == 2

    def test_a_crlf_target_spec_gains_a_crlf_context(self, repo):
        build_spec(repo, "parent")
        target = build_spec(repo, "target")
        write(target, to_crlf(read(target)))
        proc = data(repo, "target", "--spec", "0002", "--serves", "0001", "--json")
        assert proc.returncode == 0, proc.stderr
        after = read(target)
        assert bare_lf(after) == 0
        assert "\r\n## Context\r\n" in after
        assert len(re.findall(r"^## Context\s*$", after, re.MULTILINE)) == 1
        fm = cs.parse_frontmatter(after)[0]
        assert fm["type"] == "data" and fm["serves"] == "0001"


# --- resolve_ref (the one I/O helper the sheet names) ------------------------------------------

class TestResolveRef:
    def test_roots_are_walked_in_order_and_only_definitions_count(self, repo):
        (repo / "docs").mkdir()
        (repo / "docs" / "a-notes.md").write_text("We rely on BR-03 here, but this only cites it.\n",
                                                   encoding="utf-8")
        (repo / "docs" / "b-rules.md").write_text("### BR-03 — one claim per id\n", encoding="utf-8")
        assert data_spec.resolve_ref(repo, "BR-03") == "docs/b-rules.md"
        art = repo / ".sdlc" / "artifacts" / "01-requirements"
        art.mkdir(parents=True)
        (art / "business-rules.md").write_text("| BR-03 | rule | source |\n", encoding="utf-8")
        assert data_spec.resolve_ref(repo, "BR-03") == ".sdlc/artifacts/01-requirements/business-rules.md"

    def test_a_ref_nobody_defines_is_none_and_a_longer_id_is_not_a_match(self, repo):
        (repo / "docs").mkdir()
        (repo / "docs" / "r.md").write_text("### BR-031 — a different rule\n", encoding="utf-8")
        assert data_spec.resolve_ref(repo, "BR-03") is None
        assert data_spec.resolve_ref(repo, "DL-01") is None

    def test_no_roots_at_all_is_none(self, repo):
        assert data_spec.resolve_ref(repo, "BR-03") is None

    def test_the_spec_being_written_is_skipped(self, repo):
        (repo / "specs").mkdir()
        own = repo / "specs" / "0002-x.md"
        own.write_text("| BR-03 | copied into its own Context |\n", encoding="utf-8")
        assert data_spec.resolve_ref(repo, "BR-03") == "specs/0002-x.md"
        assert data_spec.resolve_ref(repo, "BR-03", skip=own) is None


# --- the surface itself ------------------------------------------------------------------------

class TestSurface:
    def test_verbs(self):
        assert data_spec.VERBS == ("new", "target", "status", "check")

    @pytest.mark.parametrize("verb", data_spec.VERBS)
    def test_help_touches_nothing(self, verb, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        proc = run("data_spec.py", [verb, "--help"], empty)
        assert proc.returncode == 0 and "usage" in proc.stdout.lower()
        assert list(empty.iterdir()) == []

    def test_top_level_help_names_every_verb_and_touches_nothing(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        proc = run("data_spec.py", ["--help"], empty)
        assert proc.returncode == 0
        assert all(v in proc.stdout for v in data_spec.VERBS)
        assert list(empty.iterdir()) == []

    def test_no_verb_is_a_usage_error(self, tmp_path):
        proc = run("data_spec.py", [], tmp_path)
        assert proc.returncode == 2

    def test_module_never_imports_subprocess(self):
        tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        assert "subprocess" not in names
        assert "branch_scan" in names          # git reads go through the one module that owns them

    def test_module_never_fetches(self):
        assert '"fetch"' not in SCRIPT_PATH.read_text(encoding="utf-8")
