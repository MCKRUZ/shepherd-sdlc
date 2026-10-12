"""The mechanical "GitHub stays byte-identical" proof (code-host providers).

Each host-touching script is driven on gh-shaped fixtures with its existing seam patched to
RECORD the argv it hands to `gh` — `ss.gh_json`, `h.run_gh`, `cr._gh`, `github_import.run_gh`,
`ga.subprocess.run` — and the recording is compared with `fixtures/golden/gh-argv.json`, captured
from the scripts BEFORE the provider layer touched them (S1–S4, H1, C1–C4, G1–G3, P1–P7). The text
each script prints on the same fixtures is pinned beside it. A later wave that changes a gh
invocation, even by one flag, fails here.

Set GH_ARGV_GOLDEN_WRITE=1 to re-capture — only ever from scripts whose GitHub path is known good.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

import connection_report as cr
import gate_auth as ga
import github_import
import handoff as h
import pipeline_proof as pp
import spec_status as ss
from tests.golden_support import GOLDEN_DIR

GOLDEN = GOLDEN_DIR / "gh-argv.json"
WRITE = os.environ.get("GH_ARGV_GOLDEN_WRITE") == "1"

SPEC = ("---\nspec: \"0042\"\nname: \"duplicate-claim\"\nstatus: \"in-progress\"\nrisk: \"MEDIUM\"\n"
        "owner: \"@priya-n\"\nteam: \"claims\"\ndeveloper: \"@sam-k\"\nchecker: \"@priya-n\"\n---\n\n# Spec 0042 — Reject a duplicate claim\n")
GREEN = [{"name": "build-and-test", "status": "COMPLETED", "conclusion": "SUCCESS"},
         {"name": "grader", "status": "COMPLETED", "conclusion": "SUCCESS"}]
PR = {"number": 42, "url": "https://gh/pull/42", "state": "OPEN", "mergedAt": None, "updatedAt": "2026-09-21T10:00:00Z",
      "isDraft": False, "headRefName": "spec/0042-duplicate-claim", "statusCheckRollup": GREEN, "reviews": [],
      "reviewRequests": [{"login": "priya-n"}], "labels": []}
COMMENT = ("## Acceptance Check Verdicts\n\n| check | covered | reason |\n|---|---|---|\n"
           "| AC-1 | covered | |\n| AC-2 | not-covered | no test |\n")
NWO = "acme/app"
RULESET = {"id": 11, "name": "main-branch-protection", "target": "branch", "enforcement": "active",
           "created_at": "2026-09-25T12:00:00Z", "bypass_actors": [],
           "rules": [{"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "build-and-test"}]}}]}
GOOD_KEY = "sk-ant-api03-" + "a" * 40


def _spec_status(tmp_path, monkeypatch) -> tuple[list, dict[str, str]]:
    calls: list[list[str]] = []
    (tmp_path / "specs").mkdir()
    spec = tmp_path / "specs" / "0042-duplicate-claim.md"
    spec.write_text(SPEC, encoding="utf-8")

    def gh_json(args, cwd):
        calls.append(list(args))
        if args[:2] == ["pr", "list"]:
            return [PR]
        if args[:2] == ["pr", "view"]:
            return {"comments": [{"body": COMMENT}]}
        raise AssertionError(f"unexpected gh call: {args}")

    def run_gh(args, cwd):  # S3: fetch_pr_events goes through github_import.gh_json → run_gh
        calls.append(list(args))
        return "[]"
    monkeypatch.setattr(ss, "gh_json", gh_json)
    monkeypatch.setattr(github_import, "run_gh", run_gh)
    single = ss.report_status(tmp_path, spec)
    board = ss.report_all(tmp_path)
    return calls, {"spec_status-gh-single": ss.format_report(single), "spec_status-gh-all": ss.format_all_report(board)}


def _handoff(monkeypatch) -> list:
    calls: list[list[str]] = []

    def run_gh(args, cwd):
        calls.append(list(args))
        return "https://gh/pull/7\n"
    monkeypatch.setattr(h, "run_gh", run_gh)
    h.assign_on_host("repo", "spec/0007-x", "main", "0007", "x", "@sam-k", "@priya-n")
    h.assign_on_host("repo", "spec/0007-x", "main", "0007", "x", "@sam-k", "")
    return calls


def _connection_report(tmp_path, monkeypatch) -> tuple[list, dict[str, str]]:
    calls: list[list[str]] = []

    def _gh(args, cwd, timeout=20):
        calls.append(list(args))
        if args[:2] == ["api", "user"]:
            return True, "priya-n"
        if "nameWithOwner" in args:
            return True, NWO
        if "viewerPermission" in args:
            return True, "WRITE"
        return True, json.dumps([RULESET])
    monkeypatch.setattr(cr, "_gh", _gh)
    result = cr.report(tmp_path)
    return calls, {"connection_report-gh-ok": cr.format_report(result)}


def _gate_auth(tmp_path, monkeypatch) -> list:
    calls: list[list[str]] = []
    secrets: list[str] = []

    def run(cmd, input=None, capture_output=True, text=True, check=False):
        if cmd[:2] == ["git", "-C"]:
            return subprocess.CompletedProcess(cmd, 0, "https://github.com/acme/widgets.git\n", "")
        calls.append(list(cmd[1:]))  # argv after `gh`, like the other seams; the credential travels on stdin and is never recorded
        verb = cmd[2]
        if verb == "list":
            return subprocess.CompletedProcess(cmd, 0, json.dumps([{"name": n} for n in secrets]), "")
        if verb == "set":
            secrets.append(cmd[3])
        if verb == "delete":
            secrets.remove(cmd[3])
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(ga.subprocess, "run", run)
    ga.status(tmp_path)
    ga.set_credential(tmp_path, "api-key", GOOD_KEY)
    ga.clear_credential(tmp_path, "api-key")
    return calls


def _pipeline_proof(tmp_path, monkeypatch) -> list:
    calls: list[list[str]] = []
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    for name in ("ci.yml", "grader.yml", "security.yml", "deploy-dev.yml"):
        (wf / name).write_text("name: x\n", encoding="utf-8")
    (tmp_path / ".github" / "rulesets").mkdir()
    (tmp_path / ".github" / "rulesets" / "branch-protection.json").write_text(json.dumps(RULESET), encoding="utf-8")
    runs = {"ci.yml": [{"databaseId": 1, "conclusion": "failure", "status": "completed", "event": "pull_request",
                        "headBranch": "feat-a", "createdAt": "2026-09-26T10:00:00Z", "url": "https://gh/runs/1"}],
            "deploy-dev.yml": [{"databaseId": 4, "conclusion": "failure", "status": "completed", "event": "push",
                                "headBranch": "main", "createdAt": "2026-09-26T10:00:00Z", "url": "https://gh/runs/4"}]}
    prs = [{"number": 7, "headRefName": "feat-a", "state": "MERGED", "url": "https://gh/pull/7",
            "mergedAt": "2026-09-27T10:00:00Z", "reviewDecision": "APPROVED"}]

    def run_gh(args, cwd):
        calls.append(list(args))
        key = " ".join(args[:2])
        if key == "repo view":
            return json.dumps({"nameWithOwner": NWO})
        if key == "pr list":
            return json.dumps(prs)
        if key == "run list":
            return json.dumps(runs.get(args[args.index("--workflow") + 1], []))
        if key == f"api repos/{NWO}/rulesets":
            return json.dumps([{"id": 11, "name": "main-branch-protection", "enforcement": "active", "target": "branch"}])
        if key == f"api repos/{NWO}/rulesets/11":
            return json.dumps(RULESET)
        if key == "pr view":
            return json.dumps({"comments": [{"body": COMMENT}]})
        if key == "run view":
            return json.dumps({"jobs": [{"name": "rollback", "conclusion": "success"}]})
        raise AssertionError(f"unexpected gh call: {args}")
    monkeypatch.setattr(github_import, "run_gh", run_gh)
    assert pp.gather(tmp_path)["ok"]
    return calls


def capture_all(tmp_path: Path, monkeypatch) -> tuple[dict, dict]:
    """(argv by script, text by golden name). Argv lists are sorted: pipeline_proof fans out on a
    thread pool, so arrival order is not part of the contract — the SET of calls is."""
    texts: dict[str, str] = {}
    ss_calls, t = _spec_status(tmp_path / "ss", monkeypatch); texts.update(t)
    cr_calls, t = _connection_report(tmp_path / "cr", monkeypatch); texts.update(t)
    (tmp_path / "ss").mkdir(exist_ok=True)
    argv = {
        "spec_status": ss_calls,
        "handoff": _handoff(monkeypatch),
        "connection_report": cr_calls,
        "gate_auth": _gate_auth(tmp_path / "ga", monkeypatch),
        "pipeline_proof": _pipeline_proof(tmp_path / "pp", monkeypatch),
    }
    return {k: sorted(v, key=json.dumps) for k, v in argv.items()}, texts


@pytest.fixture
def captured(tmp_path, monkeypatch):
    for sub in ("ss", "cr", "ga", "pp"):
        (tmp_path / sub).mkdir()
    monkeypatch.delenv("SHEPHERD_CODE_HOST", raising=False)
    monkeypatch.delenv("SDLC_CODE_HOST", raising=False)
    return capture_all(tmp_path, monkeypatch)


def test_gh_argv_matches_the_golden(captured):
    argv, _ = captured
    if WRITE:
        GOLDEN.write_text(json.dumps(argv, indent=2) + "\n", encoding="utf-8")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for script, calls in golden.items():
        assert argv[script] == calls, f"{script}: gh argv moved\n got: {argv[script]}\n want: {calls}"
    assert set(argv) == set(golden)


@pytest.mark.parametrize("name", ["spec_status-gh-single", "spec_status-gh-all", "connection_report-gh-ok"])
def test_text_output_matches_the_golden(captured, name):
    _, texts = captured
    path = GOLDEN_DIR / f"{name}.txt"
    if WRITE:
        path.write_text(texts[name] + "\n", encoding="utf-8")
    assert texts[name] + "\n" == path.read_text(encoding="utf-8")


def test_the_golden_covers_every_documented_call_site():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    flat = {" ".join(c[:2]) for calls in golden.values() for c in calls}
    assert {"pr list", "pr view", "pr create", "api user", "repo view", "secret list", "secret set",
            "secret delete", "run list", "run view"} <= flat
    assert any(c[0] == "api" and "/issues/" in c[1] for c in golden["spec_status"])      # S3
    assert any(c[0] == "api" and c[1].endswith("/rulesets") for c in golden["pipeline_proof"])  # P5
