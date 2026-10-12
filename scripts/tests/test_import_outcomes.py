"""import_outcomes — the host-neutral `scorecard.py import` (code-host providers, Wave 5).

GitHub must go through `scorecard.import_events` literally (the protected path); Azure DevOps goes
through `ado_outcomes.collect_report`. Both are monkeypatched here, so nothing spawns gh or az, and
`code_host.cli_state` is pinned so the host block never probes a real CLI either.
"""

import json

import pytest

import code_host
import import_outcomes as io_
import scorecard
from ado_map import AdoImportError
from github_import import GitHubImportError
from tests.ado_fixtures import ADO_REMOTE

GH_REMOTE = "https://github.com/contoso/claims-api.git"
SINCE = "2026-09-01"

ADO_EVENTS = [
    {"type": "spec_merged", "gh_id": "ado-pr-merge:40334", "timestamp": "2026-10-05T17:23:23Z", "accepted_as_is": True},
    {"type": "spec_merged", "gh_id": "ado-pr-merge:40305", "timestamp": "2026-10-05T13:21:58Z", "accepted_as_is": None,
     "note": "approval time not recorded by Azure DevOps (no VoteUpdate thread); accepted-as-is unknown"},
    {"type": "review_wait", "gh_id": "ado-pr-review:40334", "timestamp": "2026-10-05T17:10:00Z", "security": False},
    {"type": "deploy", "gh_id": "ado-deploy:environment-1:18282", "timestamp": "2026-10-05T19:12:06Z",
     "env": "environment-1", "succeeded": True, "caused_failure": False},
]


@pytest.fixture(autouse=True)
def _quiet_cli(monkeypatch):
    monkeypatch.delenv(code_host.ENV_VAR, raising=False)
    monkeypatch.delenv(code_host.LEGACY_CODE_HOST_ENV, raising=False)
    monkeypatch.setattr(code_host, "cli_state", lambda host, **kw: ("available", "pinned by the test"))


@pytest.fixture
def on_github(monkeypatch):
    monkeypatch.setattr(code_host, "origin_url", lambda root: GH_REMOTE)


@pytest.fixture
def on_ado(monkeypatch):
    monkeypatch.setattr(code_host, "origin_url", lambda root: ADO_REMOTE)


def report(events=None, notes=None):
    return lambda root, since: {"events": list(ADO_EVENTS if events is None else events),
                                "notes": {"deploys": None, "incidents": None, **(notes or {})}}


def run(capsys, *argv):
    code = io_.main(list(argv))
    return code, capsys.readouterr().out


def ledger(repo):
    return scorecard.load_events(repo / ".sdlc" / "metrics" / "loop-events.jsonl")


class TestOnGitHub:
    def test_delegates_to_the_protected_import_events_literally(self, tmp_path, on_github, monkeypatch, capsys):
        seen = []
        monkeypatch.setattr(scorecard, "import_events", lambda root, path, since: seen.append((root, path, since))
                            or {"spec_merged": 1, "review_wait": 1})
        code, out = run(capsys, "--repo", str(tmp_path), "--since", SINCE)
        assert code == 0 and out == "Imported 2 event(s): 1 review_wait, 1 spec_merged\n"
        assert seen == [(tmp_path.resolve(), tmp_path.resolve() / ".sdlc" / "metrics" / "loop-events.jsonl", SINCE)]

    def test_no_data_reads_exactly_as_scorecard_import_does(self, tmp_path, on_github, monkeypatch, capsys):
        monkeypatch.setattr(scorecard, "import_events", lambda *a: {})
        assert run(capsys, "--repo", str(tmp_path), "--since", SINCE) == (0, "Imported: no data\n")

    def test_a_gh_failure_is_error_exit_1_and_writes_nothing(self, tmp_path, on_github, monkeypatch, capsys):
        def boom(*a):
            raise GitHubImportError("gh: not logged in")
        monkeypatch.setattr(scorecard, "import_events", boom)
        code, out = run(capsys, "--repo", str(tmp_path), "--since", SINCE)
        assert (code, out) == (1, "Error: gh: not logged in\n") and not (tmp_path / ".sdlc").exists()

    def test_host_none_still_tries_gh_the_legacy_default(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(code_host, "origin_url", lambda root: None)
        monkeypatch.setattr(scorecard, "import_events", lambda *a: {"deploy": 3})
        code, out = run(capsys, "--repo", str(tmp_path), "--since", SINCE, "--json")
        doc = json.loads(out)
        assert code == 0 and doc["host"]["name"] == "none" and doc["imported"] == {"deploy": 3}


class TestOnAzureDevOps:
    def test_writes_collected_events_and_reports_counts_and_notes(self, tmp_path, on_ado, monkeypatch, capsys):
        monkeypatch.setattr("ado_outcomes.collect_report", report())
        code, out = run(capsys, "--repo", str(tmp_path), "--since", SINCE)
        assert code == 0
        assert out.splitlines() == [
            "Imported 4 event(s): 1 deploy, 1 review_wait, 2 spec_merged",
            "review_wait: 1 event(s) carry no wait time (Azure DevOps records no request timestamp)",
            "spec_merged: 1 event(s) have no approval time (no vote thread dates the approval; accepted-as-is left unknown)",
        ]
        written = ledger(tmp_path)
        assert [e["gh_id"] for e in written] == [e["gh_id"] for e in ADO_EVENTS]
        assert "wait_hours" not in next(e for e in written if e["type"] == "review_wait")  # absent, never null

    def test_rerunning_the_window_dedups_on_gh_id(self, tmp_path, on_ado, monkeypatch, capsys):
        monkeypatch.setattr("ado_outcomes.collect_report", report())
        run(capsys, "--repo", str(tmp_path), "--since", SINCE)
        assert run(capsys, "--repo", str(tmp_path), "--since", SINCE) == (0, "Imported: no data\n")
        assert len(ledger(tmp_path)) == len(ADO_EVENTS)

    def test_ado_ids_never_collide_with_github_ids_for_the_same_number(self, tmp_path, on_ado, monkeypatch, capsys):
        path = tmp_path / ".sdlc" / "metrics" / "loop-events.jsonl"
        scorecard.append_events(path, [{"type": "spec_merged", "gh_id": "gh-pr-merge:40334", "timestamp": "2026-10-01T00:00:00Z"}])
        monkeypatch.setattr("ado_outcomes.collect_report", report([ADO_EVENTS[0]]))
        code, out = run(capsys, "--repo", str(tmp_path), "--since", SINCE)
        assert code == 0 and out.startswith("Imported 1 event(s)")
        assert sorted(e["gh_id"] for e in ledger(tmp_path)) == ["ado-pr-merge:40334", "gh-pr-merge:40334"]

    def test_unsupported_categories_print_a_note_rather_than_zeros(self, tmp_path, on_ado, monkeypatch, capsys):
        monkeypatch.setattr("ado_outcomes.collect_report",
                            report([ADO_EVENTS[0]], {"deploys": "environments API refused (HTTP 403)", "incidents": "boards disabled"}))
        code, out = run(capsys, "--repo", str(tmp_path), "--since", SINCE)
        assert code == 0
        assert "deploys: not imported (environments API refused (HTTP 403))" in out
        assert "incidents: not imported (boards disabled)" in out
        assert not any(e["type"] in ("deploy", "incident") for e in ledger(tmp_path))

    def test_an_az_failure_is_error_exit_1_with_no_partial_write(self, tmp_path, on_ado, monkeypatch, capsys):
        path = tmp_path / ".sdlc" / "metrics" / "loop-events.jsonl"
        hand = {"type": "escaped_bug", "timestamp": "2026-09-30T00:00:00Z", "which_check": "grader"}
        scorecard.append_events(path, [hand])
        before = path.read_bytes()

        def boom(root, since):
            raise AdoImportError("The Azure CLI (`az`) is not installed or not on PATH.")
        monkeypatch.setattr("ado_outcomes.collect_report", boom)
        code, out = run(capsys, "--repo", str(tmp_path), "--since", SINCE)
        assert (code, out) == (1, "Error: The Azure CLI (`az`) is not installed or not on PATH.\n")
        assert path.read_bytes() == before

    def test_json_is_exactly_one_document_carrying_the_host_block(self, tmp_path, on_ado, monkeypatch, capsys):
        monkeypatch.setattr("ado_outcomes.collect_report", report())
        code, out = run(capsys, "--repo", str(tmp_path), "--since", SINCE, "--json")
        doc = json.loads(out)  # a second document or a stray line would fail to parse
        assert code == 0
        assert doc["host"] == {"name": "azure-devops", "source": "remote", "cli": "az", "cli_state": "available",
                               "detail": doc["host"]["detail"]}
        assert doc["imported"] == {"deploy": 1, "review_wait": 1, "spec_merged": 2} and doc["total"] == 4
        assert doc["error"] is None and len(doc["notes"]) == 2

    def test_json_error_is_also_one_document_exit_1(self, tmp_path, on_ado, monkeypatch, capsys):
        def boom(root, since):
            raise AdoImportError("run `az login`")
        monkeypatch.setattr("ado_outcomes.collect_report", boom)
        code, out = run(capsys, "--repo", str(tmp_path), "--since", SINCE, "--json")
        doc = json.loads(out)
        assert code == 1 and doc["error"] == "run `az login`" and doc["imported"] is None and doc["host"]["name"] == "azure-devops"

    def test_host_flag_overrides_a_github_remote(self, tmp_path, on_github, monkeypatch, capsys):
        monkeypatch.setattr("ado_outcomes.collect_report", report([ADO_EVENTS[0]]))
        monkeypatch.setattr(scorecard, "import_events", lambda *a: pytest.fail("the GitHub path must not run"))
        code, out = run(capsys, "--repo", str(tmp_path), "--since", SINCE, "--host", "azure-devops", "--json")
        doc = json.loads(out)
        assert code == 0 and doc["host"]["source"] == "flag" and doc["total"] == 1

    def test_state_mode_writes_beside_the_state_file(self, tmp_path, on_ado, monkeypatch, capsys):
        state = tmp_path / "proj" / ".sdlc" / "state.yaml"
        state.parent.mkdir(parents=True)
        state.write_text('current_phase: "build"\n', encoding="utf-8")
        monkeypatch.setattr("ado_outcomes.collect_report", report([ADO_EVENTS[0]]))
        code, _ = run(capsys, "--state", str(state), "--since", SINCE)
        assert code == 0 and (state.parent / "metrics" / "loop-events.jsonl").is_file()


class TestArguments:
    def test_since_must_be_a_date(self, tmp_path, on_ado, capsys):
        code, out = run(capsys, "--repo", str(tmp_path), "--since", "last week")
        assert code == 1 and out.startswith("Error: --since must be YYYY-MM-DD")

    def test_a_missing_state_file_is_an_error_not_a_traceback(self, tmp_path, on_ado, capsys):
        code, out = run(capsys, "--state", str(tmp_path / "nope.yaml"), "--since", SINCE, "--json")
        assert code == 1 and json.loads(out)["error"].startswith("State file not found")

    def test_help_documents_every_flag(self, capsys):
        with pytest.raises(SystemExit):
            io_.main(["--help"])
        text = capsys.readouterr().out
        assert all(flag in text for flag in ("--since", "--repo", "--state", "--host", "--json"))
