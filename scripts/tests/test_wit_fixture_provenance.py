"""Every Boards (work item) fixture says where it came from (B1-P0).

The `wit/` documents under `scripts/tests/fixtures/code_host/azure_devops/` were written by hand
from the REST reference for an Agile inherited process — nobody has captured them from a real
organisation yet. The B0 capture session puts real, anonymised answers under `wit/captured/`
with the same file names, and `load_wit()` then prefers them with no code change. Until then the
one honest thing a test can do is keep that visible: fail on a fixture with no provenance or a
loose wrapper, and print — every run — the names that still resolve to a hand-written file, so the
day a capture lands is the day the list shrinks. The existing `test_fixture_provenance.py` is
non-recursive, so it never sees these.

The first capture landed on 2026-10-14 (B0, `wit/captured/CAPTURE-NOTES.md`): the discovery reads, the
per-type reads at their corrected locations, the identity read through `az rest`, and four refusals under
`captured/errors/`. The item, history, discussion and write fixtures are still hand-written.
"""

import json
import re

import pytest

import ado_transport
from boards_contract import ADO_RESOURCE_ID
from tests.ado_boards_fixtures import (HAND_WRITTEN, WIT, WIT_CAPTURED, WIT_CAPTURED_ONLY, WIT_CAPTURED_REFERENCE,
                                       WIT_FIXTURE_NAMES, WIT_SYNTHETIC, identity_rest_argv, wit_source_of)

CAPTURED_RE = re.compile(r"^captured \d{4}-\d{2}-\d{2} .+")
ANON_GUID_RE = re.compile(r"^00000000-0000-0000-0000-\d{12}$")
GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

HAND_WRITTEN_FILES = sorted(WIT.glob("*.json"))
CAPTURED_FILES = sorted(WIT_CAPTURED.glob("*.json"))
SYNTHETIC_FILES = sorted(WIT_SYNTHETIC.glob("*.json"))
ERROR_FILES = sorted((WIT / "errors").glob("*.json")) + sorted((WIT_CAPTURED / "errors").glob("*.json"))
ALL_FILES = HAND_WRITTEN_FILES + CAPTURED_FILES + SYNTHETIC_FILES + ERROR_FILES


def _doc(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _ids(path):
    return f"{path.parent.name}/{path.name}"


# Fold B1 (B1-P0): the discovery reads and `az account show`.
B1_NAMES = frozenset({"projects", "type_categories", "types", "type_states_user_story", "type_states_bug",
                      "type_states_issue", "type_fields_user_story", "type_fields_issue", "fields", "backlog_config",
                      "classification_nodes", "team_iterations", "relation_types", "connection_data", "account_show"})
# Fold B2 (B2-P0): the item, drift and discussion reads.
B2_NAMES = frozenset({"workitems_batch", "wiql_by_tag", "wiql_untagged", "updates", "workitem_show_relations",
                      "comments", "comments_page2", "comment_versions", "comments_hostile", "updates_after_comment"})
# Fold B3 (B3-P0): the write responses, the recent-comments re-list and the service-principal identity.
B3_NAMES = frozenset({"workitem_create_response", "workitem_update_response", "comment_add_response",
                      "comments_recent", "connection_data_sp"})
# Fold B5 (B5-P0): one page of the reporting revisions feed (B4 added no fixture).
B5_NAMES = frozenset({"workitemrevisions"})


# B0 (2026-10-14): the names only the capture holds, the captured documents no read answers with, and every file the
# capture landed (`captured/`): the B1 discovery reads it replaced, the per-type reads it added, and the identity read.
B0_ONLY_NAMES = frozenset(WIT_CAPTURED_ONLY)
B0_REFERENCE_NAMES = frozenset(WIT_CAPTURED_REFERENCE)
# B0 write fixes (2026-10-15): the second capture, the first live apply and its probes — the item, write and comment
# answers (each shadowing a hand-written twin) and two reference documents (a repository-tag query, a Spec create)
B0_ITEM_NAMES = frozenset({"wiql_by_tag", "workitem_show_relations", "workitems_batch", "updates",
                           "workitem_create_response", "workitem_update_response", "comment_add_response", "comments"})
B0_SECOND = B0_ITEM_NAMES | {"wiql_repo_tag", "workitem_create_response_spec"}
B0_CAPTURED = (B1_NAMES - {"account_show"}) | B0_ONLY_NAMES | B0_REFERENCE_NAMES | B0_ITEM_NAMES


def test_the_thirty_one_hand_written_fixtures_exist():
    assert sorted(p.stem for p in HAND_WRITTEN_FILES) == sorted(set(WIT_FIXTURE_NAMES) - B0_ONLY_NAMES)
    assert set(WIT_FIXTURE_NAMES) == B1_NAMES | B2_NAMES | B3_NAMES | B5_NAMES | B0_ONLY_NAMES
    assert not (B1_NAMES & B2_NAMES or B1_NAMES & B3_NAMES or B2_NAMES & B3_NAMES)
    assert not B5_NAMES & (B1_NAMES | B2_NAMES | B3_NAMES)
    assert not B0_ONLY_NAMES & (B1_NAMES | B2_NAMES | B3_NAMES | B5_NAMES)
    assert len(HAND_WRITTEN_FILES) == 31 and len(WIT_FIXTURE_NAMES) == 38


def test_the_b0_capture_landed_exactly_these_files():
    assert {p.stem for p in CAPTURED_FILES} == B0_CAPTURED and len(CAPTURED_FILES) == 23 + len(B0_SECOND) == 33
    assert B0_SECOND - B0_ITEM_NAMES <= B0_REFERENCE_NAMES
    assert not B0_REFERENCE_NAMES & set(WIT_FIXTURE_NAMES)  # loaded by name, never a router's default answer
    assert {n for n in WIT_FIXTURE_NAMES if wit_source_of(n) == "captured"} == B0_CAPTURED - B0_REFERENCE_NAMES
    dates = {p.stem: _doc(p)["_provenance"] for p in CAPTURED_FILES}
    assert all(CAPTURED_RE.match(prov) for prov in dates.values())
    assert {n for n, prov in dates.items() if "2026-10-15" in prov} == B0_SECOND
    assert all("2026-10-14" in prov for n, prov in dates.items() if n not in B0_SECOND)


ORG = "https://dev.azure.com/contoso"
UPDATE_URL = re.compile(re.escape(ORG) + r"/Claims/_apis/wit/workitems/\d+\?api-version=7\.1")


@pytest.mark.parametrize("path", CAPTURED_FILES, ids=_ids)
def test_a_captured_command_is_the_call_the_capture_ran(path):
    """Every captured `devops invoke` ran with `--detect false` against the anonymised organisation, the project as a
    route parameter, at the GA api-version — or `7.1-preview` for the comments resource, which has no released
    version; the identity read is the one `az rest` GET (B0). The second capture (2026-10-15) adds the native verbs
    (`boards query` with `--project`, `boards work-item show`) and the update, the one `az rest` PATCH."""
    command = _doc(path)["_command"]
    if command[1:3] == ["devops", "invoke"]:
        assert command[command.index("--org") + 1] == ORG, path.name
        assert command[command.index("--detect") + 1] == "false" and "--project" not in command, path.name
        if "--api-version" in command:  # the locations listing alone names no location, so no version either
            version = command[command.index("--api-version") + 1]
            preview = command[command.index("--resource") + 1] == "comments"
            assert version == (ado_transport.PREVIEW_API_VERSION if preview else ado_transport.API_VERSION), path.name
    elif command[1:3] == ["boards", "query"]:
        assert path.stem in B0_SECOND
        assert command[command.index("--org") + 1] == ORG and command[command.index("--detect") + 1] == "false"
        assert command[command.index("--project") + 1] == "Claims"
        wiql = command[command.index("--wiql") + 1]
        assert "@project" not in wiql and "[System.TeamProject] = 'Claims'" in wiql   # the macro answered zero bytes
    elif command[1:4] == ["boards", "work-item", "show"]:
        assert path.stem == "workitem_show_relations" and command[command.index("--expand") + 1] == "relations"
        assert command[command.index("--org") + 1] == ORG and command[command.index("--detect") + 1] == "false"
    elif command[1:4] == ["rest", "--method", "patch"]:
        assert path.stem == "workitem_update_response"
        assert command[command.index("--resource") + 1] == ADO_RESOURCE_ID
        assert UPDATE_URL.fullmatch(command[command.index("--url") + 1])
        assert command[command.index("--headers") + 1] == "Content-Type=application/json-patch+json"
        assert "--detect" not in command and "--org" not in command
    else:
        assert path.stem == "connection_data" and command == ["az", *identity_rest_argv()], path.name


@pytest.mark.parametrize("path", ALL_FILES, ids=_ids)
def test_every_fixture_is_wrapped_and_carries_a_recognised_provenance(path):
    doc = _doc(path)
    assert isinstance(doc, dict), f"{path.name}: wrap the az answer as {{_provenance, _command, value}}"
    assert {"_provenance", "_command", "value"} <= set(doc), f"{path.name}: {sorted(doc)}"
    prov = doc["_provenance"]
    assert prov == HAND_WRITTEN or CAPTURED_RE.match(prov), f"{path.name}: unrecognised _provenance {prov!r}"


@pytest.mark.parametrize("path", HAND_WRITTEN_FILES + SYNTHETIC_FILES, ids=_ids)
def test_hand_written_files_carry_exactly_the_wrapper(path):
    doc = _doc(path)
    assert set(doc) == {"_provenance", "_command", "value"}, f"{path.name}: {sorted(doc)}"
    assert doc["_provenance"] == HAND_WRITTEN


@pytest.mark.parametrize("path", CAPTURED_FILES, ids=_ids)
def test_captured_files_say_so_and_name_their_command(path):
    doc = _doc(path)
    assert CAPTURED_RE.match(doc["_provenance"]), path.name
    assert isinstance(doc["_command"], list) and doc["_command"][:1] == ["az"], path.name


@pytest.mark.parametrize("path", HAND_WRITTEN_FILES, ids=_ids)
def test_hand_written_commands_are_the_scoped_call_they_stand_in_for(path):
    """The `_command` of a hand-written file is the B0 call it stands in for (never run)."""
    command = _doc(path)["_command"]
    assert isinstance(command, list) and command[0] == "az", path.name
    if command[1:3] == ["devops", "invoke"]:
        assert command[command.index("--detect") + 1] == "false", path.name
        assert "--project" not in command, f"{path.name}: the project is a route parameter"
        api = command[command.index("--api-version") + 1]
        assert api in {ado_transport.API_VERSION, ado_transport.PREVIEW_API_VERSION}, path.name


@pytest.mark.parametrize("path", ALL_FILES, ids=_ids)
def test_no_fixture_carries_an_obvious_real_identity(path):
    text = path.read_text(encoding="utf-8")
    emails = set(EMAIL_RE.findall(text))
    assert all(e.endswith("@example.com") for e in emails), f"{path.name}: {emails}"
    # B0: the one GUID that is not anonymised is Azure DevOps' own resource id, and only in the `az rest` command
    command_guids = set(GUID_RE.findall(json.dumps(_doc(path).get("_command"))))
    assert command_guids <= {ADO_RESOURCE_ID}, f"{path.name}: {sorted(command_guids)}"
    guids = set(GUID_RE.findall(json.dumps(_doc(path)["value"])))
    assert all(ANON_GUID_RE.match(g) for g in guids), f"{path.name}: not anonymised: {sorted(guids)}"
    assert set(GUID_RE.findall(text)) - {ADO_RESOURCE_ID} <= guids, f"{path.name}: a GUID outside value and _command"
    assert not re.search(r"-preview\.\d", text), f"{path.name}: a revisioned preview api-version"


def test_hand_written_wit_fixtures_still_in_use_are_listed_not_hidden(capsys):
    """Information for a person, never a gate: what still rests on hand-written evidence."""
    still = [n for n in WIT_FIXTURE_NAMES if wit_source_of(n) == "hand-written"]
    synthetic = [p.stem for p in SYNTHETIC_FILES]
    with capsys.disabled():
        if still:
            print(f"\n[boards] {len(still)} work-item fixture(s) have NO capture and are hand-written: " + ", ".join(still))
        else:
            print("\n[boards] every work-item fixture name resolves to a captured file")
        if synthetic:
            print(f"[boards] {len(synthetic)} synthetic process fixture(s) (hand-written by design): " + ", ".join(synthetic))
    assert set(still) <= set(WIT_FIXTURE_NAMES)


# --- Fold B3 (B3-P0): the stderr texts under wit/errors/ (and, after B0, wit/captured/errors/) -------------------

from tests.ado_boards_fixtures import WIT_ERROR_NAMES  # noqa: E402

HAND_WRITTEN_ERRORS = sorted((WIT / "errors").glob("*.txt"))
CAPTURED_ERRORS = sorted((WIT_CAPTURED / "errors").glob("*.txt"))
CAPTURED_LINE_RE = re.compile(r"^# captured \d{4}-\d{2}-\d{2} .+")


def test_the_four_hand_written_error_texts_exist():
    assert sorted(p.stem for p in HAND_WRITTEN_ERRORS) == sorted(WIT_ERROR_NAMES)
    assert set(WIT_ERROR_NAMES) == {"stale_rev", "rule_violation", "permission", "throttled"}


def test_the_four_captured_error_texts_are_the_refusals_the_capture_met():
    """B0 (2026-10-14): none of the first four supersedes a hand-written write error (that capture sent no write); each
    says when it was captured on its first line, and two say the raw stderr file was overwritten and where the text came
    from. B0 write fixes (2026-10-15): the first live apply and its probes add six, two of which (`stale_rev`,
    `rule_violation`) now supersede their hand-written twins."""
    from tests.ado_boards_fixtures import WIT_CAPTURED_ERROR_NAMES, WIT_CAPTURED_WRITE_ERROR_NAMES
    assert sorted(p.stem for p in CAPTURED_ERRORS) == sorted({*WIT_CAPTURED_ERROR_NAMES, *WIT_CAPTURED_WRITE_ERROR_NAMES})
    assert not set(WIT_CAPTURED_ERROR_NAMES) & set(WIT_ERROR_NAMES)
    assert set(WIT_CAPTURED_WRITE_ERROR_NAMES) & set(WIT_ERROR_NAMES) == {"stale_rev", "rule_violation"}
    firsts = {p.stem: p.read_text(encoding="utf-8").splitlines()[0] for p in CAPTURED_ERRORS}
    assert all(CAPTURED_LINE_RE.match(line) for line in firsts.values())
    assert {n for n, line in firsts.items() if "2026-10-14" in line} == set(WIT_CAPTURED_ERROR_NAMES)
    assert {n for n, line in firsts.items() if "2026-10-15" in line} == set(WIT_CAPTURED_WRITE_ERROR_NAMES)
    assert {n for n, line in firsts.items() if "overwritten" in line} == {"states_wrong_resource", "connection_data_core"}


@pytest.mark.parametrize("path", HAND_WRITTEN_ERRORS, ids=_ids)
def test_a_hand_written_error_text_says_so_on_its_first_line(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# " + HAND_WRITTEN, path.name
    assert [ln for ln in lines[1:] if ln.strip()], f"{path.name}: no stderr after the provenance line"
    assert not any(ln.startswith("#") for ln in lines[1:]), path.name


@pytest.mark.parametrize("path", CAPTURED_ERRORS, ids=_ids)
def test_a_captured_error_text_is_verbatim_or_says_when_it_was_captured(path):
    first = path.read_text(encoding="utf-8").splitlines()[:1]
    assert not first or not first[0].startswith("#") or CAPTURED_LINE_RE.match(first[0]), path.name


@pytest.mark.parametrize("path", HAND_WRITTEN_ERRORS + CAPTURED_ERRORS, ids=_ids)
def test_no_error_text_carries_an_obvious_real_identity(path):
    text = path.read_text(encoding="utf-8")
    emails = set(EMAIL_RE.findall(text))
    assert all(e.endswith("@example.com") for e in emails), f"{path.name}: {emails}"
    guids = set(GUID_RE.findall(text))
    assert all(ANON_GUID_RE.match(g) for g in guids), f"{path.name}: not anonymised: {sorted(guids)}"
    assert not re.search(r"-preview\.\d", text), f"{path.name}: a revisioned preview api-version"
