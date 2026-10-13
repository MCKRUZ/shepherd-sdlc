"""Every Boards (work item) fixture says where it came from (B1-P0).

The `wit/` documents under `scripts/tests/fixtures/code_host/azure_devops/` were written by hand
from the REST reference for an Agile inherited process — nobody has captured them from a real
organisation yet. The B0 capture session puts real, anonymised answers under `wit/captured/`
with the same file names, and `load_wit()` then prefers them with no code change. Until then the
one honest thing a test can do is keep that visible: fail on a fixture with no provenance or a
loose wrapper, and print — every run — the names that still resolve to a hand-written file, so the
day a capture lands is the day the list shrinks. The existing `test_fixture_provenance.py` is
non-recursive, so it never sees these.
"""

import json
import re

import pytest

import ado_transport
from tests.ado_boards_fixtures import (HAND_WRITTEN, WIT, WIT_CAPTURED, WIT_FIXTURE_NAMES, WIT_SYNTHETIC,
                                       wit_source_of)

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


def test_the_fifteen_hand_written_fixtures_exist():
    assert sorted(p.stem for p in HAND_WRITTEN_FILES) == sorted(WIT_FIXTURE_NAMES)
    assert len(WIT_FIXTURE_NAMES) == 15


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
    guids = set(GUID_RE.findall(text))
    assert all(ANON_GUID_RE.match(g) for g in guids), f"{path.name}: not anonymised: {sorted(guids)}"
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
