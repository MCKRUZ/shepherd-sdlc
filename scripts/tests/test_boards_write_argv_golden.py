"""B3-P2 -- the write argv golden (build kit gate G13): every argv `apply_plan` can send, recorded and pinned.

One scenario drives every write route there is -- a create with its parent link, an update guarded by `test /rev`, a
comment on the comments API, a comment on the History fallback, a comment recovered after a timeout, and the native
pull-request link -- and records every argv (and the request body that rode in its `--in-file`) that reached the
seam. Over ALL of them it asserts what must never be sent, then compares the recording with
`golden/az_write_argv.json`:

  * no `suppressNotifications`, `bypassRules` or `validateOnly` anywhere (argv or body), and none of `reactions`,
    `attachments`, `graph/` or `notification` in an argv: a work item notifies its followers exactly as a colleague's
    edit would (D23) and nothing is quiet, bypassed or dry-run;
  * no `PATCH`/`DELETE` on a route that holds `comments` (a comment is never edited or deleted), no `DELETE` or `PUT`
    at all, no `-preview.<digit>` (a revision crashes the az extension), only the two api-versions the seam allows;
  * every `devops invoke`, `boards` and `repos` argv carries `--detect false`, ends `-o json`, and never holds
    `--only-show-errors` (the seam adds that after the fake);
  * `az rest` is the identity read and, since the B0 write fixes (2026-10-15), the update — `az rest --method patch`
    of `<org>/<project>/_apis/wit/workitems/<id>?api-version=7.1`, the body from a file — and nothing else; no work item
    is PATCHed through `devops invoke` (the extension binds `…/workItems/${type}` for a PATCH and dies);
  * no file under `specs/` changes.

The plan hash is replaced by `<plan>` and the body file path by the seam's placeholder before comparing, so the golden
pins the argv shapes and the patches, not the planner's row contents. Regenerate with
`GOLDEN_REGEN=1 uv run --project scripts pytest scripts/tests/test_boards_write_argv_golden.py -q` and review the diff.
The checker's own detection is proven on bad argv below: a golden that cannot fail pins nothing.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import HAND_WRITTEN_PROCESS
from tests.ado_boards_fixtures import identity_rest_argv, is_identity_rest_read, route_key_boards
from tests.ado_boards_fixtures import body_file
from tests.test_boards_sync_apply import (SPEC4, _body, adhoc, apply, build_repo, clock, linked, load_cfg,  # noqa: F401
                                          make_board, plan_doc, seed, set_config, snapshot, with_rows)

import json
import os
import re
from pathlib import Path

import pytest

import ado_transport
import ado_wit
import ado_sync_comments as comments

# B0 (2026-10-14): these scenarios combine the item, history and write fixtures — hand-written for the hand-written
# Agile process, and not captured yet — with a process, so they read that same process even where a capture exists
# (tests/ado_boards_fixtures.py, `BOARDS_PROCESS`). The captured process is exercised in test_boards_captured_process.py.
BOARDS_PROCESS = HAND_WRITTEN_PROCESS

GOLDEN = Path(__file__).resolve().parent / "golden" / "az_write_argv.json"
REGEN = "GOLDEN_REGEN=1 uv run --project scripts pytest scripts/tests/test_boards_write_argv_golden.py -q"
ORG = "https://dev.azure.com/contoso"

NEVER_ANYWHERE = re.compile(r"suppressNotifications|bypassRules|validateOnly", re.IGNORECASE)
NEVER_IN_ARGV = re.compile(r"reactions|attachments|graph/|notification", re.IGNORECASE)
PREVIEW_REVISION = re.compile(r"-preview\.\d")
API_VERSIONS = ("7.1", "7.1-preview")


def violations(argv: list[str], body=None) -> list[str]:
    """Every rule `argv` (and the body it carried) breaks; `[]` for a clean one."""
    found = []
    text = " ".join(argv)
    if NEVER_ANYWHERE.search(text) or NEVER_ANYWHERE.search(json.dumps(body)):
        found.append("a notification-suppression, rule-bypass or validate-only flag")
    if NEVER_IN_ARGV.search(text):
        found.append("a reactions, attachments, graph or notification route")
    method = argv[argv.index("--http-method") + 1].upper() if "--http-method" in argv else "GET"
    if method in ("DELETE", "PUT"):
        found.append(f"an {method}")
    if method in ("PATCH", "DELETE") and "comments" in text.lower():
        found.append("a comment edit or delete")
    if PREVIEW_REVISION.search(text):
        found.append("a pinned preview revision")
    if argv[:2] == ["devops", "invoke"]:
        version = argv[argv.index("--api-version") + 1] if "--api-version" in argv else None
        if version not in API_VERSIONS:
            found.append("an api-version outside API_VERSION / PREVIEW_API_VERSION")
    if argv[:2] == ["devops", "invoke"] or argv[0] in ("boards", "repos"):
        detect = argv[argv.index("--detect") + 1] if "--detect" in argv else None
        if detect != "false":
            found.append("a missing --detect false")
    if argv[:2] == ["devops", "invoke"] and method == "PATCH" and "workItems" in argv:
        found.append("a work item PATCH through devops invoke (the extension binds `…/workItems/${type}` and dies)")
    # B0: `az rest` is the identity read; B0 write fixes (2026-10-15): and the update, and nothing else
    if argv[:1] == ["rest"] and not is_identity_rest_read(argv) and not is_update_rest_write(argv):
        found.append("an az rest other than the identity read or the update")
    if "--only-show-errors" in argv or argv[-2:] != ["-o", "json"]:
        found.append("an argv the seam would not have built")
    return found


UPDATE_ARGV = ["rest", "--method", "patch", "--resource", "499b84ac-1321-427f-aa17-267ca6975798", "--url",
               f"{ORG}/Claims/_apis/wit/workitems/4521?api-version=7.1", "--headers",
               "Content-Type=application/json-patch+json", "--body", "@/tmp/body.json", "-o", "json"]
UPDATE_URL = re.compile(r"^" + re.escape(ORG) + r"/[^/?#]+/_apis/wit/workitems/[1-9][0-9]*\?api-version=7\.1$")


def is_update_rest_write(argv: list[str]) -> bool:
    """B0 write fixes: exactly the update's `az rest` shape — a PATCH, Azure DevOps' resource id, a work item URL under
    ORG at the GA version, the JSON Patch media type, and the body from a file (`@<path>`)."""
    return (len(argv) == 13 and argv[:5] == ["rest", "--method", "patch", "--resource", ado_transport.ADO_RESOURCE_ID]
            and argv[5] == "--url" and bool(UPDATE_URL.fullmatch(argv[6]))
            and argv[7:9] == ["--headers", "Content-Type=application/json-patch+json"]
            and argv[9] == "--body" and argv[10].startswith("@") and len(argv[10]) > 1 and argv[11:] == ["-o", "json"])


def normalised(argv: list[str], body, plans: list[str]) -> dict:
    argv = [ado_transport.BODY_FILE_PLACEHOLDER if i and argv[i - 1] == "--in-file" else
            f"@{ado_transport.BODY_FILE_PLACEHOLDER}" if i and argv[i - 1] == "--body" and argv[0] == "rest" else w
            for i, w in enumerate(argv)]
    text = json.dumps({"argv": argv, "body": body}, ensure_ascii=False)
    for plan in plans:
        text = text.replace(plan, "<plan>")
    return json.loads(text)


@pytest.fixture
def scenario(tmp_path, monkeypatch, capsys):
    """Run every write route once; returns (steps: name -> recorded calls, the argv list, the repo, the specs before)."""
    board = make_board(monkeypatch)
    board.answers["repos pr work-item add"] = []                        # `link_pr` ignores the reply (B0 has not captured it)
    root = build_repo(tmp_path)
    capsys.readouterr()
    recording, calls, plans = [False], [], []

    def spy(args, cwd, timeout=60):
        if recording[0]:
            calls.append({"argv": list(args), "body": _body(args) if body_file(args) else None})
        return board(args, cwd, timeout)
    monkeypatch.setattr(ado_transport, "run_az", spy)
    specs_before = {k: v for k, v in snapshot(root).items() if k.startswith("specs/")}
    steps: dict[str, list[dict]] = {}

    def step(name: str, doc: dict | None, run=None):
        mark = len(calls)
        recording[0] = True
        try:
            if doc is not None:
                plans.append(doc["plan"])
                assert apply(root, doc)["exit"] == 0, name
            else:
                run()
        finally:
            recording[0] = False
        steps[name] = [normalised(c["argv"], c["body"], plans) for c in calls[mark:]]

    step("create an epic and its feature", plan_doc(root, capsys, "--kind", "epic", "--kind", "feature", "--id", "EP-001",
                                                     "--id", "FE-03"))
    seed(root, linked(SPEC4, 4521))
    doc = plan_doc(root, capsys, "--kind", "spec", "--id", "0004")
    rows = [*doc["rows"], adhoc(root, "a first fact"),
            comments.event_row("pr_linked", SPEC4, 4521, {"pr": 12}, {"ref": SPEC4, "pr": 12}, cfg=load_cfg(root))]
    step("update a spec and post two comments", with_rows(doc, rows))
    set_config(root, comments={**load_cfg(root)["comments"], "transport": "history"})
    step("post a comment through the History fallback",
         with_rows(doc, [comments.event_row("pr_linked", SPEC4, 4521, {"pr": 13}, {"ref": SPEC4, "pr": 13}, cfg=load_cfg(root))]))
    set_config(root, comments={**load_cfg(root)["comments"], "transport": "comments-api"})
    board.fail["workItemId=4521 --http-method POST"] = "`az devops invoke` timed out after 60s."
    step("recover a comment after a timeout", with_rows(doc, [adhoc(root, "probe from sdlc")]))
    del board.fail["workItemId=4521 --http-method POST"]
    step("link a pull request", None, run=lambda: ado_wit.link_pr(root, 12, 4521))
    return steps, calls, root, specs_before


def test_the_recorded_write_argv_match_the_golden(scenario):
    steps, calls, _root, _ = scenario
    assert calls, "nothing was recorded"
    bad = [(i, v) for i, c in enumerate(calls) for v in violations(c["argv"], c["body"])]
    assert bad == [], bad                                              # never bake a forbidden argv into the golden
    document = {"_provenance": "generated by test_boards_write_argv_golden.py (argv of this code, not captured from a "
                               "live board)", "_command": REGEN, "value": steps}
    if os.environ.get("GOLDEN_REGEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        pytest.skip(f"regenerated {GOLDEN.name} ({sum(len(v) for v in steps.values())} argv) -- review and commit it")
    assert GOLDEN.is_file(), f"missing golden {GOLDEN}; run {REGEN}"
    assert json.loads(GOLDEN.read_text(encoding="utf-8"))["value"] == steps, f"the write argv changed; if intended: {REGEN}"


def test_the_scenario_reaches_every_write_route(scenario):
    steps, calls, _root, _ = scenario
    keys = {route_key_boards(c["argv"]) for c in calls}
    assert {"GET core/connectionData", "POST wit/workitemsbatch", "POST wit/workItems", "PATCH wit/workItems",
            "POST wit/comments", "GET wit/comments", "repos pr work-item add"} <= keys
    assert [name for name, calls_ in steps.items() if not calls_] == []
    assert not any(c["argv"][0] == "devops" and "DELETE" in c["argv"] for c in calls)


def test_every_recorded_argv_is_clean(scenario):
    _steps, calls, _root, _ = scenario
    for c in calls:
        assert violations(c["argv"], c["body"]) == [], c["argv"]
        if is_identity_rest_read(c["argv"], ORG):  # B0: the identity read is `az rest` of <ORG>/_apis/connectionData
            continue
        if is_update_rest_write(c["argv"]):        # B0 write fixes: the update is `az rest` of <ORG>/<P>/…/workitems/<N>
            continue
        assert c["argv"][c["argv"].index("--detect") + 1] == "false" and c["argv"][c["argv"].index("--org") + 1] == ORG
    assert sum(1 for c in calls if is_identity_rest_read(c["argv"], ORG)) == 3   # once per step with a comment
    assert sum(1 for c in calls if is_update_rest_write(c["argv"])) == 2         # the spec update, the History entry
    assert sum(1 for c in calls if c["argv"][:1] == ["rest"]) == 5               # and no other `az rest`


def test_no_file_under_specs_changes_after_the_scenario(scenario):
    _steps, _calls, root, before = scenario
    after = {k: v for k, v in snapshot(root).items() if k.startswith("specs/")}
    assert before and after == before


@pytest.mark.parametrize("argv,body,expect", [
    (["devops", "invoke", "--http-method", "PATCH", "--api-version", "7.1", "--detect", "false", "-o", "json",
      "--query-parameters", "suppressNotifications=true"], None, "suppression"),
    (["devops", "invoke", "--http-method", "PATCH", "--api-version", "7.1", "--detect", "false", "-o", "json"],
     [{"op": "add", "path": "/bypassRules", "value": True}], "suppression"),
    (["devops", "invoke", "--http-method", "GET", "--api-version", "7.1", "--detect", "false", "-o", "json",
      "--query-parameters", "validateOnly=true"], None, "validate-only"),
    (["devops", "invoke", "--resource", "reactions", "--api-version", "7.1", "--detect", "false", "-o", "json"], None,
     "reactions"),
    (["devops", "invoke", "--resource", "attachments", "--api-version", "7.1", "--detect", "false", "-o", "json"], None,
     "attachments"),
    (["devops", "invoke", "--area", "graph", "--resource", "graph/users", "--api-version", "7.1", "--detect", "false",
      "-o", "json"], None, "graph"),
    (["devops", "invoke", "--resource", "notification/subscriptions", "--api-version", "7.1", "--detect", "false",
      "-o", "json"], None, "notification"),
    (["devops", "invoke", "--resource", "comments", "--http-method", "PATCH", "--api-version", "7.1-preview",
      "--detect", "false", "-o", "json"], None, "comment edit"),
    (["devops", "invoke", "--resource", "comments", "--http-method", "DELETE", "--api-version", "7.1-preview",
      "--detect", "false", "-o", "json"], None, "DELETE"),
    (["devops", "invoke", "--http-method", "GET", "--api-version", "7.1-preview.3", "--detect", "false", "-o", "json"],
     None, "preview revision"),
    (["devops", "invoke", "--http-method", "GET", "--api-version", "5.0", "--detect", "false", "-o", "json"], None,
     "api-version"),
    (["devops", "invoke", "--http-method", "GET", "--api-version", "7.1", "-o", "json"], None, "--detect false"),
    (["boards", "query", "--detect", "true", "-o", "json"], None, "--detect false"),
    (["repos", "pr", "work-item", "add", "--id", "1", "-o", "json"], None, "--detect false"),
    (["boards", "query", "--detect", "false", "-o", "json", "--only-show-errors"], None, "seam"),
    (["boards", "query", "--detect", "false"], None, "seam"),
    # B0: `az rest` is permitted for the identity read only — any other method, URL, version or resource fires
    ([*identity_rest_argv(ORG)[:2], "post", *identity_rest_argv(ORG)[3:]], None, "az rest other than"),
    ([w.replace("_apis/connectionData", "_apis/projects") for w in identity_rest_argv(ORG)], None, "az rest other than"),
    ([w.replace("7.1-preview", "7.1") for w in identity_rest_argv(ORG)], None, "az rest other than"),
    ([w.replace("contoso", "elsewhere") for w in identity_rest_argv(ORG)], None, "az rest other than"),
    (["rest", "--method", "get", "--url", f"{ORG}/_apis/connectionData?api-version=7.1-preview", "-o", "json"], None,
     "az rest other than"),
    # B0 write fixes (2026-10-15): a work item PATCH is the `az rest` update and nothing else — never `devops invoke`
    (["devops", "invoke", "--area", "wit", "--resource", "workItems", "--route-parameters", "project=Claims", "id=7",
      "--http-method", "PATCH", "--api-version", "7.1", "--detect", "false", "-o", "json"], None, "devops invoke"),
    ([w.replace("patch", "delete") if i == 2 else w for i, w in enumerate(UPDATE_ARGV)], None, "az rest other than"),
    ([w.replace(ORG, "https://dev.azure.com/elsewhere") for w in UPDATE_ARGV], None, "az rest other than"),
    ([w.replace("/workitems/4521", "/comments/4521") for w in UPDATE_ARGV], None, "az rest other than"),
    ([w.replace("api-version=7.1", "api-version=7.1-preview") for w in UPDATE_ARGV], None, "az rest other than"),
    ([w.replace("json-patch+json", "json") for w in UPDATE_ARGV], None, "az rest other than"),
    ([w.lstrip("@") if w.startswith("@") else w for w in UPDATE_ARGV], None, "az rest other than"),
    ([*UPDATE_ARGV[:-2], "--skip-authorization-header", "-o", "json"], None, "az rest other than"),
])
def test_the_checker_fires_on_each_forbidden_shape(argv, body, expect):
    found = violations(argv, body)
    assert any(expect.lower() in v.lower() for v in found), (argv, found)


def test_the_checker_accepts_the_argv_the_seam_builds():
    clean = ["devops", "invoke", "--area", "wit", "--resource", "comments", "--route-parameters", "project=Claims",
             "workItemId=4521", "--http-method", "POST", "--in-file", "<f>", "--media-type", "application/json",
             "--query-parameters", "format=markdown", "--api-version", "7.1-preview", "--detect", "false", "--org", ORG,
             "-o", "json"]
    assert violations(clean, {"text": "a fact"}) == []
    assert violations(["repos", "pr", "work-item", "add", "--id", "12", "--work-items", "4521", "--detect", "false",
                       "--org", ORG, "-o", "json"]) == []
    assert violations(identity_rest_argv(ORG)) == []   # B0: the identity read, `az rest` of <ORG>/_apis/connectionData
    assert violations(UPDATE_ARGV, [{"op": "test", "path": "/rev", "value": 7}]) == []   # B0 write fixes: the update
    assert UPDATE_ARGV == ado_transport.rest_write_argv(ORG, "{project}/_apis/wit/workitems/{id}",
                                                        {"project": "Claims", "id": 4521}, "/tmp/body.json")
