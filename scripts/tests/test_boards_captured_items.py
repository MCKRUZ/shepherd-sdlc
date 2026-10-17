"""B0 write fixes — the second capture (2026-10-15, the first live `apply`), read through the code that consumes it.

The capture landed under `wit/captured/` (CAPTURE-NOTES.md says how, and what each file settled): the item, write and
comment answers that shadow their hand-written twins (`WIT_CAPTURED_ITEMS`), a repository-tag query and a `Spec` create
(`WIT_CAPTURED_REFERENCE`), and six error texts. The scenario modules keep reading the hand-written fixtures their ids
are pinned to (`BOARDS_ITEMS`); this module reads the captures, so each shape the board really sent is exercised by the
function that reads it:

  * the transport: an update is `az rest --method patch` of `<org>/<project>/_apis/wit/workitems/<id>`, its JSON Patch
    in a 0600 temp file passed `--body @<file>`, removed on every path and scrubbed from every error; nothing but the
    `REST_WRITES` template, the GA api-version and a positive id reach that URL; a personal-access-token-only sign-in is
    `REST_NO_TOKEN_WRITE`, never az's own "run az login"; `az devops invoke` PATCH of a work item is never built;
  * the error texts read as their classes: a stale `test /rev` (`Precondition Failed … VS403351`) is `conflict`, a value
    outside a picklist (`RuleValidationErrors`) and an unknown identity are `rule` — the row fails, the run goes on — and
    `describe_write_error` names the patch field each one is about, never with the board's words;
  * `az boards query` printing zero bytes is no rows, with `printed_nothing` set, never a JSON error;
  * the comments page token rides as `continuation_token` (the extension's spelling) as well as `continuationToken`;
  * each captured item answer reads through its mapper: a batch with a `null` for the missing id, a Feature with its
    parent, an Epic's history with a relation-only revision that kept its `rev`, the create and update replies.

Nothing here spawns `az`: `boards_env` forbids it at the seam.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import (WIT_CAPTURED, WIT_CAPTURED_ERROR_CLASSES, WIT_CAPTURED_ITEMS,
                                       WIT_CAPTURED_REFERENCE, WIT_CAPTURED_WRITE_ERROR_NAMES, FakeBoardsAz, body_file,
                                       load_captured, load_wit, load_wit_error, route_key_boards, route_params)

import json
import os
import re
import stat
from pathlib import Path

import pytest

import ado_discussion_map as dm
import ado_transport
import ado_wit
import ado_wit_feed
import ado_wit_map as wm
import boards_contract as bc
from ado_map import AdoImportError

ORG = "https://dev.azure.com/contoso"
PROJECT = "Claims"
UPDATE = bc.REST_ROUTES["workitem_update"]["path"]
PATCH = [{"op": "test", "path": "/rev", "value": 1}, {"op": "replace", "path": "/fields/System.Title", "value": "t"}]


def _doc(name: str) -> dict:
    return json.loads((WIT_CAPTURED / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def writer(monkeypatch) -> FakeBoardsAz:
    """A fake that answers writes from the captures (this module reads them: it sets no `BOARDS_ITEMS`)."""
    fake = FakeBoardsAz(writes=True)
    monkeypatch.setattr(ado_transport, "run_az", fake)
    return fake


# --- the capture is what this module reads --------------------------------------------------------------------

def test_this_module_reads_the_captured_items_not_their_hand_written_twins():
    for name in WIT_CAPTURED_ITEMS:
        assert load_wit(name) == load_captured(name) != load_wit(name, hand_written=True), name
    assert {"wiql_repo_tag", "workitem_create_response_spec"} <= set(WIT_CAPTURED_REFERENCE)


@pytest.mark.parametrize("name", sorted(WIT_CAPTURED_ITEMS))
def test_each_captured_item_command_routes_to_its_captured_answer(name, tmp_path):
    command = _doc(name)["_command"]
    argv = [w for w in command[1:] if w != "--only-show-errors"]
    if argv[0] == "rest":   # the captured update ran with its body file; the placeholder stands in for the path
        argv[argv.index("--body") + 1] = "@/tmp/body.json"
    out = FakeBoardsAz(writes=True)(argv if argv[-2:] == ["-o", "json"] else [*argv, "-o", "json"], tmp_path)
    assert json.loads(out) == load_wit(name)


# --- Defect A: an update is `az rest`, never `devops invoke` ------------------------------------------------

def test_the_invoke_patch_crash_is_why_the_update_is_az_rest():
    """`devops invoke --resource workItems --http-method PATCH` dies in the extension (`ERROR: 'type'`): it binds the
    `…/workItems/${type}` location. The text classifies as nothing known (`unknown`), which is why it was a stop."""
    text = load_wit_error("invoke_patch_keyerror")
    assert "ERROR: 'type'" in text and wm.classify_write_error(text) == "unknown"
    assert bc.WIT_ROUTES["workitem_update"]["verified"] and bc.REST_ROUTES["workitem_update"]["verified"]


def test_update_sends_exactly_the_rest_patch_and_returns_id_and_rev(writer, tmp_path):
    seen = []

    def answer(args):
        path = Path(body_file(args))
        seen.append((list(args), path, json.loads(path.read_text(encoding="utf-8")), stat.S_IMODE(os.stat(path).st_mode)))
        return "workitem_update_response"
    writer.answers["PATCH wit/workItems"] = answer
    captured = load_captured("workitem_update_response")
    out = ado_wit.update(tmp_path, captured["id"], [{"op": "test", "path": "/rev", "value": 1}, PATCH[1]])
    assert out == {"id": captured["id"], "rev": captured["rev"]} == {"id": 1, "rev": 2}   # rev 1 -> 2 (captured)
    ((argv, path, body, mode),) = seen
    assert argv == ["rest", "--method", "patch", "--resource", bc.ADO_RESOURCE_ID, "--url",
                    f"{ORG}/{PROJECT}/_apis/wit/workitems/1?api-version=7.1", "--headers",
                    "Content-Type=application/json-patch+json", "--body", f"@{path}", "-o", "json"]
    assert body[0] == {"op": "test", "path": "/rev", "value": 1} and not path.exists()
    if os.name != "nt":
        assert mode == 0o600
    assert route_key_boards(argv) == "PATCH wit/workItems" and route_params(argv) == {"project": PROJECT, "id": "1"}


def test_the_captured_update_reply_is_az_rest_shaped():
    reply = load_captured("workitem_update_response")
    assert "continuation_token" not in reply                       # `az rest` adds none; every `devops invoke` does
    assert {"id", "rev", "fields"} <= set(reply) and reply["fields"]["System.Title"] == "sdlc probe 2"
    command = _doc("workitem_update_response")["_command"]
    assert command[:4] == ["az", "rest", "--method", "patch"] and "--detect" not in command


@pytest.mark.parametrize("route, why", [
    ({"project": PROJECT, "id": 0}, "positive integer"), ({"project": PROJECT, "id": "7"}, "positive integer"),
    ({"project": PROJECT, "id": True}, "positive integer"), ({"project": "", "id": 7}, "a name"),
    ({"project": "a\nb", "id": 7}, "a name"), ({"project": PROJECT}, "takes"), ({"id": 7}, "takes"),
    ({"project": PROJECT, "id": 7, "x": 1}, "takes"),
])
def test_the_rest_url_is_built_only_from_checked_values(writer, tmp_path, route, why):
    with pytest.raises(AdoImportError, match=why):
        ado_transport.rest_patch(tmp_path, UPDATE, route, PATCH)
    assert writer.calls == []


def test_a_project_name_is_percent_encoded_whole_in_the_rest_url():
    argv = ado_transport.rest_write_argv(ORG, UPDATE, {"project": "Claims Ops/../x", "id": 9}, "/tmp/b.json")
    assert argv[argv.index("--url") + 1] == f"{ORG}/Claims%20Ops%2F..%2Fx/_apis/wit/workitems/9?api-version=7.1"


@pytest.mark.parametrize("path, version, why", [
    ("_apis/connectionData", "7.1", "writes only"), ("{project}/_apis/wit/comments/{id}", "7.1", "writes only"),
    (UPDATE, "7.1-preview", "is not 7.1"), (UPDATE, "7.1-preview.3", "preview revision"), (UPDATE, "5.0", "is not 7.1"),
])
def test_only_the_allow_listed_patch_at_the_ga_version_is_sent(writer, tmp_path, path, version, why):
    with pytest.raises(AdoImportError, match=why):
        ado_transport.rest_patch(tmp_path, path, {"project": PROJECT, "id": 1}, PATCH, api_version=version)
    assert writer.calls == []


def test_a_pat_only_sign_in_is_said_in_the_plugins_words_and_nothing_was_sent(writer, tmp_path):
    writer.fail["rest --method patch"] = "ERROR: Please run 'az login' to setup account."
    with pytest.raises(AdoImportError) as info:
        ado_wit.update(tmp_path, 4560, PATCH)
    text = str(info.value)
    assert ado_transport.REST_NO_TOKEN_WRITE in text and "az login" not in text.replace("`az login`", "")
    assert info.value.error_class == "permission"          # nothing was sent, and no later update could be: a stop
    assert "Entra" in ado_transport.REST_NO_TOKEN_WRITE and "personal access token" in ado_transport.REST_NO_TOKEN_WRITE


def test_a_failed_patch_never_names_its_body_file_and_removes_it(writer, tmp_path):
    def fail(args):
        path = body_file(args)
        raise AdoImportError(f"`az {' '.join(args)}` exited 1 reading {path}")
    writer.answers["PATCH wit/workItems"] = fail
    with pytest.raises(AdoImportError) as info:
        ado_wit.update(tmp_path, 4560, PATCH)
    path = body_file(writer.calls[0])
    assert path not in str(info.value) and ado_transport.BODY_FILE_PLACEHOLDER in str(info.value)
    assert not Path(path).exists()


def test_an_empty_patch_reply_is_an_unknown_outcome(writer, tmp_path):
    writer.answers["PATCH wit/workItems"] = None
    with pytest.raises(AdoImportError, match="empty response on write") as info:
        ado_wit.update(tmp_path, 4560, PATCH)
    assert info.value.error_class == "unknown"


def test_no_scripts_module_builds_a_work_item_patch_through_devops_invoke():
    scripts = Path(ado_wit.__file__).resolve().parent
    source = (scripts / "ado_wit.py").read_text(encoding="utf-8")
    body = source[source.index("def update("):source.index("def add_comment(")]
    assert "rest_patch" in body and "invoke_body" not in body
    for path in scripts.glob("ado_*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"invoke_body\([^)]*method\s*=\s*['\"]PATCH", text), path.name


# --- the captured error texts, by class ------------------------------------------------------------------------

@pytest.mark.parametrize("name", WIT_CAPTURED_WRITE_ERROR_NAMES)
def test_each_captured_error_text_reads_as_its_class(name):
    assert wm.classify_write_error(load_wit_error(name)) == WIT_CAPTURED_ERROR_CLASSES[name]


def test_the_stale_rev_and_rule_texts_say_what_the_board_said():
    stale, rule = load_wit_error("stale_rev"), load_wit_error("rule_violation")
    assert stale.startswith("ERROR: Precondition Failed(") and "VS403351" in stale and "TestPatchOperationFailedException" in stale
    assert rule.startswith("ERROR: Bad Request(") and "RuleValidationErrors" in rule
    assert "is an unknown identity" in load_wit_error("identity_unknown")
    assert "$$Task" in load_wit_error("create_dollar_type") and "7.1.4" in load_wit_error("preview_rev")


@pytest.mark.parametrize("name, fields, expect", [
    ("identity_unknown", ["System.Title", "System.AssignedTo", "System.Tags"],
     {"reason": "unknown_identity", "field": "System.AssignedTo"}),
    ("identity_unknown", ["System.Title"], {"reason": "unknown_identity", "field": None}),          # never guessed
    ("rule_violation", ["System.State", "System.Title"], {"reason": "value_not_allowed", "field": "System.State"}),
    ("rule_violation", ["System.Title"], {"reason": "value_not_allowed", "field": None}),
    ("stale_rev", ["System.Title"], {"reason": None, "field": None}),                              # not a rule
    ("create_dollar_type", ["System.Title"], {"reason": None, "field": None}),
])
def test_describe_write_error_names_only_a_field_the_patch_carried(name, fields, expect):
    assert wm.describe_write_error(load_wit_error(name), fields) == expect


def test_describe_write_error_matches_a_display_name_to_exactly_one_field():
    text = "ERROR: TF401320: Rule Error for field 'Risk Tier'. Error code: InvalidListValue."
    assert wm.describe_write_error(text, ["Custom.RiskTier", "System.Title"])["field"] == "Custom.RiskTier"
    assert wm.describe_write_error(text, ["Custom.RiskTier", "Other.RiskTier"])["field"] is None   # two: no guess
    assert wm.describe_write_error("not text", None) == {"reason": None, "field": None}
    assert set(wm.RULE_REASONS) == {"unknown_identity", "value_not_allowed"}


# --- Defect C: zero bytes from `az boards query` is no rows -----------------------------------------------------

def test_a_query_that_prints_nothing_is_no_rows_and_says_so(az, tmp_path):
    az.answers["boards query"] = None   # zero bytes, exit 0: what the macro (and an empty match) printed
    ids = ado_wit.query_ids(tmp_path, "SELECT [System.Id] FROM WorkItems")
    assert ids == [] and ids.printed_nothing is True
    az.answers["boards query"] = []
    ids = ado_wit.query_ids(tmp_path, "SELECT [System.Id] FROM WorkItems")
    assert ids == [] and ids.printed_nothing is False   # an empty list printed is a list, not nothing
    assert "zero bytes" in ado_wit.QUERY_PRINTED_NOTHING


def test_the_captured_by_tag_answers_read_as_ids(az, tmp_path):
    az.answers["boards query"] = "wiql_repo_tag"
    assert ado_wit.query_ids(tmp_path, "SELECT [System.Id] FROM WorkItems") == [1, 2, 3, 4]
    az.answers["boards query"] = "wiql_by_tag"                           # the default: the captured by-tag answer
    assert ado_wit.find_by_ref(tmp_path, "sdlc:epic:001") == [1]
    wiql = az.calls[-1][az.calls[-1].index("--wiql") + 1]
    assert "@project" not in wiql and "[System.TeamProject] = 'Claims'" in wiql
    for name in ("wiql_by_tag", "wiql_repo_tag"):
        sent = _doc(name)["_command"]
        assert "@project" not in sent[sent.index("--wiql") + 1] and sent[sent.index("--project") + 1] == PROJECT
        for row in load_captured(name):                                  # `fields` holds what the select list named
            assert row["fields"]["System.Id"] == row["id"] and set(row["fields"]) <= {"System.Id", "System.State"}


def test_the_ado_transport_read_helper_parses_or_says_nothing(monkeypatch, tmp_path):
    answers = iter(["", "  \n", '[{"id": 3}]', "not json"])
    monkeypatch.setattr(ado_transport, "run_az", lambda args, cwd, timeout=60: next(answers))
    assert ado_transport.az_json_read(["boards", "query"], tmp_path) == ([], True)
    assert ado_transport.az_json_read(["boards", "query"], tmp_path) == ([], True)
    assert ado_transport.az_json_read(["boards", "query"], tmp_path) == ([{"id": 3}], False)
    with pytest.raises(AdoImportError, match="unparseable JSON"):
        ado_transport.az_json_read(["boards", "query"], tmp_path)


# --- comments: the extension's token spelling ------------------------------------------------------------------

def test_the_captured_comments_page_is_a_last_page_in_the_extensions_spelling():
    page = load_captured("comments")
    assert page["continuation_token"] is None and "continuationToken" not in page
    assert page["count"] == page["totalCount"] == len(page["comments"]) == 1
    assert {"mentions", "createdBy", "format", "version", "workItemId"} <= set(page["comments"][0])
    assert "isDeleted" not in page["comments"][0]                         # a live comment: the false flag is left out
    comments, token = dm.map_comment_list(page, {})
    assert token is None and len(comments) == 1 and comments[0]["deleted"] is False
    assert comments[0]["id"] == 1 and comments[0]["version"] == 1 and comments[0]["format"] == "markdown"


def test_comments_page_on_the_snake_case_token(az, tmp_path):
    first = {"comments": [{"id": 1}], "count": 1, "totalCount": 2, "continuation_token": "abc"}
    second = {"comments": [{"id": 2}], "count": 1, "continuation_token": None}
    az.answers["GET wit/comments"] = first
    az.answers["GET wit/comments continuationToken=*"] = second
    got = ado_wit.comments(tmp_path, 4521)
    assert [c["id"] for c in got] == [1, 2] and got.total_count == 2 and not got.truncated
    asked = [route_params(c) for c in az.calls]
    assert len(az.calls) == 2 and "continuationToken=abc" in az.calls[1]
    assert asked[0]["workItemId"] == "4521"


def test_the_body_token_wins_over_the_extensions_key():
    doc = {"comments": [], "continuationToken": "body", "continuation_token": "header"}
    assert dm.map_comment_list(doc, {})[1] == "body"
    assert dm.map_comment_list({"comments": [], "continuation_token": "header"}, {})[1] == "header"
    assert dm.map_comment_list({"comments": [], "continuationToken": "", "continuation_token": None}, {})[1] is None


def test_the_feed_reads_either_spelling(az, tmp_path):
    page = {"values": [], "isLastBatch": True, "continuation_token": "T9"}
    assert ado_wit_feed._read_page(page) == ([], True, "T9")
    assert ado_wit_feed._read_page({**page, "continuationToken": "T1"}) == ([], True, "T1")
    assert ado_wit_feed._read_page({"values": [], "isLastBatch": True, "continuation_token": None}) == ([], True, None)


def test_the_captured_comment_post_reads_as_its_id_and_version(writer, tmp_path):
    posted = load_captured("comment_add_response")
    out = ado_wit.add_comment(tmp_path, 1, "probe from sdlc · sprd 000000000000", "markdown")
    assert out == {"comment_id": posted["id"], "version": posted["version"]} == {"comment_id": 1, "version": 1}
    assert posted["format"] == "markdown" and posted["workItemId"] == 1 and "continuation_token" in posted


# --- the item answers through their mappers ----------------------------------------------------------------------

def test_the_captured_batch_omits_the_missing_id_as_null_and_get_batch_reports_it(az, tmp_path):
    doc = load_captured("workitems_batch")
    assert doc["count"] == 3 and doc["value"][2] is None                  # errorPolicy=omit: counted, and null
    assert _doc("workitems_batch")["_body"] == {"ids": [1, 2, 999999999], "$expand": "relations", "errorPolicy": "omit"}
    rows, missing = ado_wit.get_batch(tmp_path, [1, 2, 999999999])
    assert [r["id"] for r in rows] == [1, 2] and missing == [999999999]
    items = [wm.remote_item(r, {"person1@example.com": "@dev-one"}) for r in rows]
    assert [(i["type"], i["area"], i["rev"]) for i in items] == [("Epic", PROJECT, 1), ("Feature", PROJECT, 1)]
    feature = items[1]
    assert {"rel": "System.LinkTypes.Hierarchy-Reverse", "target": 1, "name": "Parent"} in feature["relations"]
    assert "System.History" not in feature["fields"] and "System.CreatedBy" not in feature["fields"]


def test_the_captured_feature_shows_its_parent_and_hyperlink(az, tmp_path):
    item = ado_wit.get_item(tmp_path, 1)
    assert item == load_captured("workitem_show_relations")
    mapped = wm.remote_item(item)
    rels = {r["rel"]: r for r in mapped["relations"]}
    assert rels["System.LinkTypes.Hierarchy-Reverse"]["target"] == item["fields"]["System.Parent"] == 2
    assert rels["Hyperlink"]["url"].startswith(f"{ORG}/{PROJECT}/_git/")
    assert mapped["area"] == PROJECT    # created before the fix: at the project root, not the team's area (Defect D)


def test_the_captured_history_has_a_relation_only_revision_that_kept_its_rev(az, tmp_path):
    """A child linked from its own side adds a revision to the parent's history with no `fields` and the SAME `rev`:
    the parent's revision number did not move (captured)."""
    updates = load_captured("updates")["value"]
    assert [(u["id"], u["rev"]) for u in updates] == [(1, 1), (2, 1)]
    assert "fields" not in updates[1] and updates[1]["relations"]["added"][0]["rel"] == "System.LinkTypes.Hierarchy-Forward"
    got = ado_wit.updates_since(tmp_path, 1, 0)
    assert [u["id"] for u in got] == [1, 2]


def test_the_captured_creates_read_as_id_and_rev(writer, tmp_path):
    task = load_captured("workitem_create_response")
    assert ado_wit.create(tmp_path, "Task", [{"op": "add", "path": "/fields/System.Title", "value": "t"}]) == \
        {"id": task["id"], "rev": task["rev"]}
    assert task["fields"]["System.Title"] == 'sdlc probe & "quote" ✓'      # quotes, ampersand and non-ASCII intact
    assert task["fields"]["System.AreaPath"] == "Claims\\Claims Team"     # the probe set the area: it landed there
    spec = load_captured("workitem_create_response_spec")
    assert spec["fields"]["System.WorkItemType"] == "Spec" and spec["fields"]["Custom.RiskTier"] == "High"
    assert spec["fields"]["System.IterationPath"] == "Claims\\Sprint 7" and spec["rev"] == 1
    (parent,) = spec["relations"]
    assert parent["rel"] == "System.LinkTypes.Hierarchy-Reverse" and parent["url"].endswith("/_apis/wit/workItems/1")
    command = _doc("workitem_create_response_spec")["_command"]
    assert "type=Spec" in command and not any(w.startswith("type=$") for w in command)
