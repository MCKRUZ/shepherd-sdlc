"""The second-stage redactor for captured Boards discussion documents (B2-P4b).

`redact.py` swaps GUIDs, e-mail addresses and the organisation for stable fakes; it cannot see what a person
typed. `redact_wit.py` runs after it in the B0 capture pipeline (`redact.py --org <org> | redact_wit.py`) and
removes what is left: comment and history text, the target of an @mention, an on-behalf-of identity, and the
display name beside a unique name. It is also safe on its own, so it sweeps any e-mail address or GUID it
meets. The properties the capture session relies on:

  * deterministic and idempotent: the same document gives the same output, and redacting the output changes
    nothing, so a fixture can be re-run through the pipeline without churn;
  * shape-preserving: every key and list length survives, so a mapper written against the hand-written
    fixtures reads the captured ones with no code change;
  * pure: the input is never mutated and nothing is read or written but stdin and stdout.

No identity in this file is real. Raw-looking addresses, names and GUIDs are built at run time (never typed as
literals) so the file itself carries none.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401

import ast
import base64
import copy
import importlib.util
import io
import json
import re
import sys
import uuid
from pathlib import Path

import pytest

from tests.ado_boards_fixtures import wit_path
from tests.ado_fixtures import FIXTURES

MODULE_PATH = FIXTURES / "redact_wit.py"


def _load():
    spec = importlib.util.spec_from_file_location("redact_wit", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rw = _load()
redact_wit = rw.redact_wit


def _addr(user: str, domain: str = "corp.example") -> str:
    return user + "@" + domain


RAW_NAME = "Zed Testuser"
RAW_ADDR = _addr("zed.testuser")
RAW_GUID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "redact-wit-1"))
OTHER_GUID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "redact-wit-2"))
RAW_DESCRIPTOR = "aad." + base64.urlsafe_b64encode(RAW_GUID.encode()).decode().rstrip("=")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
GUID_RE = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")
ANON_GUID_RE = re.compile(r"^00000000-0000-0000-0000-\d{12}$")
AT_AT_RE = re.compile(r'@[^@\s"\\]*@')  # "@person1@example.com": a mention glued to an address

DISCUSSION_FIXTURES = ("comments", "comments_page2", "comment_versions", "comments_hostile", "updates",
                       "updates_after_comment", "workitem_show_relations", "workitems_batch", "connection_data")


def raw_identity() -> dict:
    avatar = f"https://dev.azure.com/example/_apis/GraphProfile/MemberAvatars/{RAW_DESCRIPTOR}"
    return {"displayName": RAW_NAME, "uniqueName": RAW_ADDR, "id": RAW_GUID, "descriptor": RAW_DESCRIPTOR,
            "url": f"https://dev.azure.com/example/_apis/Identities/{RAW_GUID}", "imageUrl": avatar,
            "_links": {"avatar": {"href": avatar}}}


def fixture_doc(name: str) -> dict:
    return json.loads(wit_path(name).read_text(encoding="utf-8"))


def walk_strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_strings(item)
    elif isinstance(value, str):
        yield value


def display_names(value) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        if isinstance(value.get("displayName"), str):
            found.add(value["displayName"])
        for item in value.values():
            found |= display_names(item)
    elif isinstance(value, list):
        for item in value:
            found |= display_names(item)
    return found


def shape(value):
    """Keys and list lengths, none of the values."""
    if isinstance(value, dict):
        return {k: shape(v) for k, v in value.items()}
    if isinstance(value, list):
        return [shape(v) for v in value]
    return None


# --- the three properties the capture session relies on ---------------------------------------------------------------

@pytest.mark.parametrize("name", DISCUSSION_FIXTURES)
def test_redact_wit_is_deterministic(name):
    doc = fixture_doc(name)
    first = redact_wit(doc)
    assert redact_wit(copy.deepcopy(doc)) == first
    assert json.dumps(redact_wit(doc)) == json.dumps(first)


@pytest.mark.parametrize("name", DISCUSSION_FIXTURES)
def test_redact_wit_is_idempotent(name):
    once = redact_wit(fixture_doc(name))
    assert redact_wit(once) == once


def test_redact_wit_is_idempotent_on_a_raw_capture_too():
    doc = {"comments": [{"id": 1, "text": "body", "createdBy": raw_identity(), "modifiedBy": raw_identity(),
                         "createdOnBehalfOf": {"displayName": "Bot Testuser", "id": OTHER_GUID},
                         "mentions": [{"targetId": RAW_GUID}, {"targetId": "descriptor-form"}],
                         "note": f"ping @{RAW_ADDR} about {OTHER_GUID}"}]}
    once = redact_wit(doc)
    assert redact_wit(once) == once
    assert json.dumps(redact_wit(redact_wit(once))) == json.dumps(once)


def test_redact_wit_never_mutates_its_input():
    doc = {"comments": [{"text": "body", "createdBy": raw_identity(), "mentions": [{"targetId": RAW_GUID}]}]}
    before = copy.deepcopy(doc)
    redact_wit(doc)
    assert doc == before


@pytest.mark.parametrize("name", DISCUSSION_FIXTURES)
def test_redact_wit_keeps_every_key_and_list_length(name):
    doc = fixture_doc(name)
    assert shape(redact_wit(doc)) == shape(doc)


# --- the card's pins over comments_hostile ------------------------------------------------------------------------------

def test_hostile_comments_come_out_with_no_at_at_address_and_no_input_display_name():
    doc = fixture_doc("comments_hostile")
    names = display_names(doc)
    assert names, "the fixture must carry display names for this test to mean anything"
    assert AT_AT_RE.search(json.dumps(doc)), "the fixture must carry an @address mention"
    dumped = json.dumps(redact_wit(doc), ensure_ascii=False)
    assert not AT_AT_RE.search(dumped)
    for name in names:
        assert name not in dumped, name
    assert "<script" not in dumped and "onerror" not in dumped and "\x1b" not in dumped and "\\u001b" not in dumped


def test_hostile_comments_keep_their_structure_and_their_anonymised_ids():
    doc = fixture_doc("comments_hostile")
    out = redact_wit(doc)
    first = out["value"]["comments"][0]
    assert first["id"] == 601 and first["format"] == "html" and first["isDeleted"] is False
    assert first["createdBy"]["id"] == doc["value"]["comments"][0]["createdBy"]["id"]  # already anonymised: kept
    assert first["mentions"][0]["targetId"] == doc["value"]["comments"][0]["mentions"][0]["targetId"]


# --- free text -------------------------------------------------------------------------------------------------------

def test_comment_text_rendered_text_and_a_version_ref_text_are_masked():
    doc = {"comments": [{"id": 1, "version": 2, "format": "html", "text": "<div>typed body</div>",
                         "renderedText": "<p>typed body</p>", "empty": "",
                         "commentVersionRef": {"commentId": 1, "version": 1, "text": "an older body"}}]}
    out = redact_wit(doc)["comments"][0]
    assert out["text"] == out["renderedText"] == out["commentVersionRef"]["text"] == rw.REDACTED_TEXT
    assert (out["id"], out["version"], out["format"], out["empty"]) == (1, 2, "html", "")
    assert out["commentVersionRef"]["commentId"] == 1 and out["commentVersionRef"]["version"] == 1


def test_history_values_are_masked_in_every_shape_it_arrives_in():
    doc = {"fields": {"System.History": {"oldValue": None, "newValue": "<div>a note</div>"}, "System.Title": "keep"},
           "item": {"System.History": "a plain note", "System.Id": 7},
           "ops": [{"op": "add", "path": "/fields/System.History", "value": "a patched note"},
                   {"op": "add", "path": "/fields/System.Title", "value": "kept title"}]}
    out = redact_wit(doc)
    assert out["fields"]["System.History"] == {"oldValue": None, "newValue": rw.REDACTED_TEXT}
    assert out["item"] == {"System.History": rw.REDACTED_TEXT, "System.Id": 7}
    assert out["ops"][0] == {"op": "add", "path": "/fields/System.History", "value": rw.REDACTED_TEXT}
    assert out["ops"][1]["value"] == "kept title" and out["fields"]["System.Title"] == "keep"


@pytest.mark.parametrize("name", DISCUSSION_FIXTURES)
def test_no_history_text_survives_in_any_discussion_fixture(name):
    def history(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "System.History":
                    yield item
                else:
                    yield from history(item)
        elif isinstance(value, list):
            for item in value:
                yield from history(item)

    for value in history(redact_wit(fixture_doc(name))):
        assert all(s in ("", rw.REDACTED_TEXT) for s in walk_strings(value)), value


# --- identities ------------------------------------------------------------------------------------------------------

def test_mention_targets_become_anonymised_guids_and_never_collide_with_existing_ones():
    existing = "00000000-0000-0000-0000-000000000001"
    doc = {"owner": {"id": existing},
           "comments": [{"mentions": [{"artifactType": "Person", "commentId": 1, "targetId": RAW_GUID},
                                      {"commentId": 1, "targetId": "descriptor-form-target"},
                                      {"commentId": 1, "targetId": existing},
                                      {"commentId": 1, "targetId": RAW_GUID.upper()}]}]}
    out = redact_wit(doc)
    targets = [m["targetId"] for m in out["comments"][0]["mentions"]]
    assert all(ANON_GUID_RE.match(t) for t in targets)
    assert targets[2] == existing  # an anonymised id is kept
    assert targets[0] == targets[3] and len({targets[0], targets[1], targets[2]}) == 3  # same raw id -> same fake
    assert existing not in (targets[0], targets[1])
    assert RAW_GUID not in json.dumps(out) and "descriptor-form-target" not in json.dumps(out)
    assert out["comments"][0]["mentions"][0]["artifactType"] == "Person"


def test_created_on_behalf_of_is_scrubbed_in_each_shape():
    doc = {"a": {"createdOnBehalfOf": "Bot Testuser"},
           "b": {"createdOnBehalfOf": {"displayName": "Bot Testuser", "id": OTHER_GUID, "isContainer": False}},
           "c": {"createdOnBehalfOf": raw_identity()},
           "d": {"createdOnBehalfOf": None}}
    out = redact_wit(doc)
    assert out["a"]["createdOnBehalfOf"] == rw.REDACTED_IDENTITY
    assert out["b"]["createdOnBehalfOf"]["displayName"] == rw.REDACTED_IDENTITY
    assert out["b"]["createdOnBehalfOf"]["isContainer"] is False
    assert ANON_GUID_RE.match(out["b"]["createdOnBehalfOf"]["id"])
    assert out["c"]["createdOnBehalfOf"]["uniqueName"].endswith("@example.com")
    assert out["c"]["createdOnBehalfOf"]["displayName"].startswith("Participant ")
    assert out["d"]["createdOnBehalfOf"] is None
    dumped = json.dumps(out)
    for leaked in ("Bot Testuser", RAW_NAME, RAW_ADDR, OTHER_GUID, RAW_GUID):
        assert leaked not in dumped


def test_a_display_name_beside_a_unique_name_becomes_a_numbered_label_per_person():
    other = _addr("alex.testuser")
    doc = [{"displayName": RAW_NAME, "uniqueName": RAW_ADDR},
           {"displayName": "Alex Testuser", "uniqueName": other},
           {"displayName": "Zed T.", "uniqueName": RAW_ADDR.upper()}]  # the same person, differently cased
    out = redact_wit(doc)
    assert [(i["uniqueName"], i["displayName"]) for i in out] == [
        ("person1@example.com", "Participant 1"), ("person2@example.com", "Participant 2"),
        ("person1@example.com", "Participant 1")]


def test_new_numbers_skip_the_ones_an_earlier_redaction_already_used():
    doc = [{"displayName": RAW_NAME, "uniqueName": RAW_ADDR},
           {"displayName": "Person 1", "uniqueName": "person1@example.com"}]
    out = redact_wit(doc)
    assert out[1] == {"displayName": "Participant 1", "uniqueName": "person1@example.com"}
    assert out[0] == {"displayName": "Participant 2", "uniqueName": "person2@example.com"}


def test_the_label_follows_the_number_of_the_address_redact_py_chose():
    out = redact_wit({"displayName": "Person 3", "uniqueName": "person3@example.com"})
    assert out == {"displayName": "Participant 3", "uniqueName": "person3@example.com"}


def test_descriptors_and_avatar_links_beside_a_unique_name_are_anonymised():
    out = redact_wit({"createdBy": raw_identity()})["createdBy"]
    assert out["descriptor"] == "aad.anonymised-1"
    assert out["imageUrl"].endswith("/MemberAvatars/aad.anonymised-1")
    assert out["_links"]["avatar"]["href"] == out["imageUrl"]
    assert ANON_GUID_RE.match(out["id"]) and out["url"].endswith("/_apis/Identities/" + out["id"])
    dumped = json.dumps(out)
    assert RAW_DESCRIPTOR not in dumped and RAW_DESCRIPTOR.removeprefix("aad.") not in dumped


# --- defence in depth: usable without redact.py ---------------------------------------------------------------------------

def test_a_raw_capture_loses_every_identity_even_without_redact_py():
    doc = {"count": 1, "comments": [{
        "id": 1, "text": f"hello {RAW_NAME} <{RAW_ADDR}>", "createdBy": raw_identity(), "modifiedBy": raw_identity(),
        "createdOnBehalfOf": {"displayName": "Bot Testuser", "id": OTHER_GUID},
        "mentions": [{"targetId": RAW_GUID, "commentId": 1}],
        "title": f"ping @{RAW_ADDR} today", "link": f"https://dev.azure.com/example/x/{OTHER_GUID}/y"}]}
    out = redact_wit(doc)
    dumped = json.dumps(out)
    for leaked in (RAW_ADDR, RAW_NAME, RAW_GUID, OTHER_GUID, "Bot Testuser", RAW_ADDR.upper()):
        assert leaked not in dumped
    comment = out["comments"][0]
    assert comment["createdBy"] == comment["modifiedBy"]
    assert comment["createdBy"]["uniqueName"] == "person1@example.com"
    assert comment["createdBy"]["displayName"] == "Participant 1"
    assert comment["mentions"][0]["targetId"] == comment["createdBy"]["id"]  # one raw id, one fake
    assert comment["title"] == "ping person1@example.com today" and not AT_AT_RE.search(dumped)
    assert comment["link"] == f"https://dev.azure.com/example/x/{comment['createdOnBehalfOf']['id']}/y"
    assert all(e.endswith("@example.com") for e in EMAIL_RE.findall(dumped))
    assert all(ANON_GUID_RE.match(g) for g in GUID_RE.findall(dumped))


@pytest.mark.parametrize("name", DISCUSSION_FIXTURES)
def test_every_discussion_fixture_stays_committable_after_redact_wit(name):
    """The provenance test's identity rules, applied to the redactor's output."""
    dumped = json.dumps(redact_wit(fixture_doc(name)))
    assert all(e.endswith("@example.com") for e in EMAIL_RE.findall(dumped))
    assert all(ANON_GUID_RE.match(g) for g in GUID_RE.findall(dumped))
    assert not re.search(r"-preview\.\d", dumped)


def test_an_already_clean_document_is_returned_equal():
    clean = {"_provenance": "hand-written (unverified)", "_command": ["az", "devops", "invoke", "--detect", "false"],
             "value": {"count": 0, "value": [], "who": {"displayName": "Participant 1",
                                                        "uniqueName": "person1@example.com",
                                                        "id": "00000000-0000-0000-0000-000000000001"}}}
    assert redact_wit(clean) == clean


# --- the command line --------------------------------------------------------------------------------------------------

def test_the_command_line_reads_stdin_and_writes_the_redacted_document(monkeypatch, capsys):
    doc = {"comments": [{"text": "body", "createdBy": raw_identity()}]}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(doc)))
    assert rw.main([]) == 0
    captured = capsys.readouterr()
    assert captured.out == json.dumps(redact_wit(doc), indent=2) + "\n" and captured.err == ""
    assert RAW_ADDR not in captured.out and RAW_NAME not in captured.out


def test_the_command_line_refuses_input_that_is_not_json(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert rw.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "not a JSON document" in captured.err


def test_help_touches_no_filesystem(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as stop:
        rw.main(["--help"])
    assert stop.value.code == 0 and list(tmp_path.iterdir()) == []
    assert "redact_wit" in capsys.readouterr().out


# --- hygiene the gates also check ---------------------------------------------------------------------------------------

def test_the_redactor_is_standalone_standard_library_only():
    """It runs as `python redact_wit.py` from anywhere, so it may import nothing of the plugin's."""
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert names <= {"argparse", "itertools", "json", "re", "sys"}, names


def test_the_redactor_has_no_subprocess_no_shell_and_no_preview_revision():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s+subprocess\b", source, re.M)
    assert not re.search(r"shell=True|shlex\.join|os\.system", source)
    assert not re.search(r"-preview\.\d", source)


# --- B0 (2026-10-14): redact.py's Boards options, the first stage of the work-item pipeline --------------------------

def _load_redact():
    spec = importlib.util.spec_from_file_location("redact", FIXTURES / "redact.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rd = _load_redact()
BOARD_DOC = {
    "name": "RealProj", "process": "Agile_RealProj", "team": {"name": "Squad"},
    "url": "https://dev.azure.com/RealOrg/RealProj/Squad/_apis/work/teamsettings",
    "nodes": [{"name": "Squad", "path": "\\RealProj\\Area\\Squad"},
              {"name": "Iteration 1", "path": "\\RealProj\\Iteration\\Iteration 1",
               "url": "https://dev.azure.com/RealOrg/x/_apis/wit/classificationNodes/Iterations/Iteration%201"},
              {"name": "Squadron", "path": "RealProj\\Squadron"}],
    "fields": [{"referenceName": "Custom.Squad", "description": "What the client typed", "helpText": "",
                "xmlForm": "<Form/>", "defaultValue": "Squad"}, {"description": None}],
}


def _boards(doc=BOARD_DOC, **extra):
    return rd.redact(doc, "RealOrg", project="RealProj", team="Squad", renames={"Iteration 1": "Sprint 1"}, **extra)


def test_without_the_boards_options_redact_is_what_it_was():
    plain = rd.redact(BOARD_DOC, "RealOrg")
    assert plain == rd.redact(BOARD_DOC, "RealOrg", project=None, team=None, renames=None, mask_free_text=False)
    assert plain["name"] == "RealProj" and plain["url"].startswith("https://dev.azure.com/contoso/RealProj/")


def test_the_project_is_replaced_wherever_it_appears_as_the_organisation_is():
    out = _boards()
    assert (out["name"], out["process"]) == ("Claims", "Agile_Claims")
    assert out["nodes"][0]["path"] == "\\Claims\\Area\\Claims Team"
    assert "RealProj" not in json.dumps(out) and "RealOrg" not in json.dumps(out)


def test_a_team_or_a_renamed_node_is_replaced_whole_never_inside_other_text():
    out = _boards()
    assert out["team"] == {"name": "Claims Team"} and out["nodes"][0]["name"] == "Claims Team"
    assert out["url"] == "https://dev.azure.com/contoso/Claims/Claims%20Team/_apis/work/teamsettings"  # a URL stays one
    assert out["nodes"][1]["name"] == "Sprint 1" and out["nodes"][1]["path"] == "\\Claims\\Iteration\\Sprint 1"
    assert out["nodes"][1]["url"].endswith("/Iterations/Sprint%201")                  # percent-encoded in, and out
    assert out["nodes"][2] == {"name": "Squadron", "path": "Claims\\Squadron"}          # not a whole segment
    assert out["fields"][0]["referenceName"] == "Custom.Squad" and out["fields"][0]["defaultValue"] == "Claims Team"


def test_mask_free_text_blanks_descriptions_help_and_forms_only():
    out = _boards(mask_free_text=True)
    first = out["fields"][0]
    assert first["description"] == first["xmlForm"] == rd.REDACTED_TEXT
    assert first["helpText"] == "" and out["fields"][1]["description"] is None        # nothing to hide is left as is
    assert _boards()["fields"][0]["description"] == "What the client typed"            # off unless asked


def test_the_redact_cli_takes_the_options_and_refuses_a_rename_without_an_equals(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(BOARD_DOC)))
    assert rd.main(["--org", "RealOrg", "--project", "RealProj", "--team", "Squad", "--rename", "Iteration 1=Sprint 1",
                    "--mask-free-text", "--indent", "1"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out) == _boards(mask_free_text=True) and out.startswith('{\n "name"')
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    with pytest.raises(SystemExit) as stop:
        rd.main(["--org", "RealOrg", "--rename", "no-equals-sign"])
    assert stop.value.code == 2
