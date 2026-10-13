"""The local discussion cache and its garbage collector (B2-P4b).

`pull --discussion` reads a work item's comments and keeps them in `.sdlc/ado/local/discussion/<id>.json`,
on this machine only (`.sdlc/ado/local/` is ignored by git; `me.json` beside it remembers who the signed-in
Azure DevOps user is). `ado_discussion_cache.py` is the one module that reads and writes those files:

  * `save_cache` stamps `schema: 1`, writes through a temporary file and a rename, and makes sure the folder is
    ignored by git before any comment text lands in it;
  * `load_cache` answers `None` for a cache it cannot trust (missing, unreadable, another schema, or filed under
    the wrong id) so a pull simply rewrites it;
  * `gc` deletes a cache older than `discussion.retain_days` and the cache of an item whose last ledger word is
    an UNLINK disposition — the same rule `ado_sync_model.summarize` uses to stop counting an item as linked.
    `dry_run=True` returns the list and deletes nothing.

Every document here is synthetic: no identity, no GUID, no comment text from anywhere real.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401

import ast
import json
import os
import re
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

import ado_discussion_cache as cache
import ado_sync_model as model
import boards_contract as bc

def _addr(user: str, domain: str = "corp.example") -> str:
    return user + "@" + domain  # built at run time: this file carries no address literal


TODAY = date(2026, 10, 13)
IDENT_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "discussion-cache-test"))  # an identity id, built at run time
CFG = {"discussion": {"retain_days": 90}}


def stamp(days_ago: int) -> str:
    return f"{(TODAY - timedelta(days=days_ago)).isoformat()}T09:02Z"


def doc(wid: int = 4521, as_of: str | None = None, **extra) -> dict:
    return {"work_item": wid, "as_of": as_of if as_of is not None else stamp(0),
            "comments": [{"id": 1, "text": "synthetic comment body"}], **extra}


def seed(root: Path, wid: int, days_ago: int) -> Path:
    return cache.save_cache(root, doc(wid, stamp(days_ago)))


def write_ledger(root: Path, entries: list[dict], raw_lines: list[str] | None = None) -> Path:
    path = root / bc.LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e) for e in entries] + list(raw_lines or [])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def link(ref: str, wid: int, event: str = "linked", ts: str = "2026-09-01T10:00Z") -> dict:
    return model.ledger_entry(ts, event, ref=ref, work_item=wid)


def unlink(ref: str, ts: str = "2026-10-01T10:00Z", **extra) -> dict:
    return model.ledger_entry(ts, "reconciled", ref=ref, disposition="UNLINK", **extra)


def names(paths) -> list[str]:
    return [p.name for p in paths]


# --- paths -------------------------------------------------------------------------------------------------------------

def test_cache_path_is_the_discussion_folder_and_the_id_and_creates_nothing(tmp_path):
    assert cache.cache_path(tmp_path, 4521) == tmp_path / ".sdlc" / "ado" / "local" / "discussion" / "4521.json"
    assert cache.cache_path(str(tmp_path), 7) == tmp_path / bc.DISCUSSION_DIR / "7.json"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("bad", [0, -1, True, False, "12", "../12", 1.5, None])
def test_cache_path_takes_a_positive_integer_id_only(tmp_path, bad):
    with pytest.raises(ValueError):
        cache.cache_path(tmp_path, bad)


# --- save_cache / load_cache -------------------------------------------------------------------------------------------

def test_save_cache_writes_schema_1_and_load_cache_reads_it_back(tmp_path):
    original = doc(4521, comments=[{"id": 501, "text": "synthetic body one"}, {"id": 502, "text": "two"}])
    snapshot = json.loads(json.dumps(original))
    path = cache.save_cache(tmp_path, original)
    assert path == cache.cache_path(tmp_path, 4521) and path.is_file()
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["schema"] == 1 and cache.SCHEMA == 1
    assert cache.load_cache(tmp_path, 4521) == {"schema": 1, **snapshot}
    assert original == snapshot, "save_cache must not mutate the document it was handed"


def test_save_cache_is_sorted_indented_and_ends_with_one_line_feed(tmp_path):
    path = cache.save_cache(tmp_path, doc(4521, zebra=1, apple=2))
    text = path.read_text(encoding="utf-8")
    assert text == json.dumps(json.loads(text), sort_keys=True, indent=1) + "\n"
    assert text.index('"apple"') < text.index('"zebra"') and not text.endswith("\n\n")


def test_save_cache_replaces_an_earlier_cache_and_leaves_no_temporary_file(tmp_path):
    cache.save_cache(tmp_path, doc(4521, comments=[]))
    cache.save_cache(tmp_path, doc(4521, comments=[{"id": 9}]))
    assert cache.load_cache(tmp_path, 4521)["comments"] == [{"id": 9}]
    assert sorted(p.name for p in (tmp_path / bc.DISCUSSION_DIR).iterdir()) == ["4521.json"]


def test_a_failed_rename_keeps_the_old_cache_and_removes_the_temporary_file(tmp_path):
    cache.save_cache(tmp_path, doc(4521, comments=[{"id": 1}]))

    def boom(src, dst):
        raise OSError("disk full")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            cache.save_cache(tmp_path, doc(4521, comments=[{"id": 2}]))
    assert cache.load_cache(tmp_path, 4521)["comments"] == [{"id": 1}]
    assert sorted(p.name for p in (tmp_path / bc.DISCUSSION_DIR).iterdir()) == ["4521.json"]


@pytest.mark.parametrize("bad", [
    {"as_of": "2026-10-12T09:02Z"},                       # no work_item
    {"work_item": "4521", "as_of": "x"},                  # not an integer
    {"work_item": True, "as_of": "x"},                    # a bool is not an id
    {"work_item": 0, "as_of": "x"},
    {"work_item": 4521, "schema": 2},                     # another version's document
    {"work_item": 4521, "schema": True},
    {"work_item": 4521, "bad": {1, 2}},                   # not JSON
    {"work_item": 4521, "bad": float("nan")},             # not valid JSON either
    ["work_item", 4521],                                  # not a mapping
])
def test_save_cache_refuses_a_document_it_cannot_key_or_write_and_writes_nothing(tmp_path, bad):
    with pytest.raises(ValueError):
        cache.save_cache(tmp_path, bad)
    assert not (tmp_path / ".sdlc").exists()


def test_save_cache_accepts_schema_1_when_the_caller_already_stamped_it(tmp_path):
    cache.save_cache(tmp_path, doc(4521, schema=1))
    assert cache.load_cache(tmp_path, 4521)["schema"] == 1


def test_save_cache_makes_the_local_folder_ignored_before_it_writes_and_never_clobbers_it(tmp_path):
    ignore = tmp_path / bc.LOCAL_DIR / ".gitignore"
    cache.save_cache(tmp_path, doc(4521))
    assert ignore.read_bytes() == b"*\n"
    ignore.write_bytes(b"*\n# a person's own note\n")
    cache.save_cache(tmp_path, doc(4522))
    assert ignore.read_bytes() == b"*\n# a person's own note\n"


def test_the_ignore_file_exists_before_the_first_comment_is_written(tmp_path, monkeypatch):
    seen: dict = {}
    real = os.replace

    def spy(src, dst):
        seen["ignored"] = (tmp_path / bc.LOCAL_DIR / ".gitignore").is_file()
        return real(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    cache.save_cache(tmp_path, doc(4521))
    assert seen == {"ignored": True}


def test_load_cache_is_none_when_there_is_nothing_to_trust(tmp_path):
    assert cache.load_cache(tmp_path, 4521) is None  # never pulled: absent, and nothing is created
    assert not (tmp_path / ".sdlc").exists()
    folder = tmp_path / bc.DISCUSSION_DIR
    folder.mkdir(parents=True)
    path = cache.cache_path(tmp_path, 4521)
    for content in (b"not json", b"[1, 2]", b"\xff\xfe\x00", b'{"work_item": 4521}',
                    b'{"schema": 2, "work_item": 4521}', b'{"schema": true, "work_item": 4521}',
                    b'{"schema": 1, "work_item": 9999}',   # a file copied under another id
                    b'{"schema": 1}'):
        path.write_bytes(content)
        assert cache.load_cache(tmp_path, 4521) is None, content
    path.unlink()
    path.mkdir()  # a folder named like a cache file is no cache either
    assert cache.load_cache(tmp_path, 4521) is None


# --- me.json -------------------------------------------------------------------------------------------------------------

def test_me_round_trips_a_handle_an_id_and_the_time_it_was_read(tmp_path):
    path = cache.save_me(tmp_path, "@MCKRUZ", IDENT_ID, "2026-10-13T08:00Z")
    assert path == tmp_path / bc.ME_FILE
    assert cache.load_me(tmp_path) == {"schema": 1, "handle": "@MCKRUZ", "id": IDENT_ID, "as_of": "2026-10-13T08:00Z"}
    assert (tmp_path / bc.LOCAL_DIR / ".gitignore").read_bytes() == b"*\n"


def test_me_keeps_unknown_as_none_never_as_an_empty_string(tmp_path):
    cache.save_me(tmp_path, None, None, "2026-10-13T08:00Z")
    me = cache.load_me(tmp_path)
    assert me["handle"] is None and me["id"] is None and me["as_of"] == "2026-10-13T08:00Z"


@pytest.mark.parametrize("handle, ident, as_of", [
    ("MCKRUZ", None, "2026-10-13T08:00Z"),            # a handle starts with @
    ("", None, "2026-10-13T08:00Z"),
    ("@" + _addr("a", "b.example"), None, "2026-10-13T08:00Z"),  # an address is not a handle
    ("@MCKRUZ ", None, "2026-10-13T08:00Z"),
    (None, _addr("kim"), "2026-10-13T08:00Z"),        # an id is not an address
    (None, "", "2026-10-13T08:00Z"),
    (None, None, ""),
    (None, None, "yesterday"),
    (None, None, None),
])
def test_me_refuses_an_unusable_handle_id_or_time_and_writes_nothing(tmp_path, handle, ident, as_of):
    with pytest.raises(ValueError):
        cache.save_me(tmp_path, handle, ident, as_of)
    assert not (tmp_path / ".sdlc").exists()


def test_load_me_is_none_when_absent_unreadable_or_another_schema(tmp_path):
    assert cache.load_me(tmp_path) is None
    path = tmp_path / bc.ME_FILE
    path.parent.mkdir(parents=True)
    for content in (b"nope", b"[]", b'{"handle": "@MCKRUZ"}', b'{"schema": 3, "handle": null}'):
        path.write_bytes(content)
        assert cache.load_me(tmp_path) is None, content


# --- gc: retention -----------------------------------------------------------------------------------------------------

def test_gc_deletes_a_cache_past_retain_days_and_keeps_the_rest(tmp_path):
    for wid, age in ((4501, 100), (4502, 91), (4503, 90), (4504, 10), (4505, 0), (4506, -1)):
        seed(tmp_path, wid, age)
    deleted = cache.gc(tmp_path, CFG, TODAY, dry_run=False)
    assert deleted == [cache.cache_path(tmp_path, 4501), cache.cache_path(tmp_path, 4502)]
    left = sorted(p.name for p in (tmp_path / bc.DISCUSSION_DIR).iterdir())
    assert left == ["4503.json", "4504.json", "4505.json", "4506.json"]


def test_gc_dry_run_returns_the_same_list_and_deletes_nothing(tmp_path):
    for wid, age in ((4501, 100), (4504, 10)):
        seed(tmp_path, wid, age)
    before = sorted(p.name for p in (tmp_path / bc.DISCUSSION_DIR).iterdir())
    planned = cache.gc(tmp_path, CFG, TODAY, dry_run=True)
    assert planned == [cache.cache_path(tmp_path, 4501)]
    assert sorted(p.name for p in (tmp_path / bc.DISCUSSION_DIR).iterdir()) == before
    assert cache.gc(tmp_path, CFG, TODAY, dry_run=False) == planned  # and the real run does what the preview said
    assert not cache.cache_path(tmp_path, 4501).exists()


def test_gc_sorts_by_item_number_not_by_name(tmp_path):
    for wid in (9, 10, 100, 11):
        seed(tmp_path, wid, 400)
    assert names(cache.gc(tmp_path, CFG, TODAY, dry_run=True)) == ["9.json", "10.json", "11.json", "100.json"]


def test_gc_retain_days_defaults_to_the_starter_value_when_the_key_is_absent(tmp_path):
    seed(tmp_path, 4501, 91)
    seed(tmp_path, 4502, 90)
    assert cache.DEFAULT_RETAIN_DAYS == 90
    for cfg in ({}, {"discussion": {}}, {"discussion": None}, {"discussion": {"enabled": True}}):
        assert names(cache.gc(tmp_path, cfg, TODAY, dry_run=True)) == ["4501.json"], cfg


def test_gc_retain_days_zero_keeps_only_today(tmp_path):
    seed(tmp_path, 4501, 1)
    seed(tmp_path, 4502, 0)
    assert names(cache.gc(tmp_path, {"discussion": {"retain_days": 0}}, TODAY, dry_run=True)) == ["4501.json"]


@pytest.mark.parametrize("cfg", [{"discussion": {"retain_days": -1}}, {"discussion": {"retain_days": "90"}},
                                 {"discussion": {"retain_days": True}}, {"discussion": {"retain_days": 1.5}},
                                 {"discussion": {"retain_days": None}}, {"discussion": "on"}, None, []])
def test_gc_refuses_a_retention_it_cannot_read_and_deletes_nothing(tmp_path, cfg):
    seed(tmp_path, 4501, 1000)
    with pytest.raises(ValueError):
        cache.gc(tmp_path, cfg, TODAY, dry_run=False)
    assert cache.cache_path(tmp_path, 4501).exists()


def test_gc_accepts_a_date_or_a_datetime_for_today_and_refuses_anything_else(tmp_path):
    seed(tmp_path, 4501, 91)
    assert names(cache.gc(tmp_path, CFG, TODAY, dry_run=True)) == ["4501.json"]
    assert names(cache.gc(tmp_path, CFG, datetime(2026, 10, 13, 23, 59), dry_run=True)) == ["4501.json"]
    for bad in ("2026-10-13", None, 20261013):
        with pytest.raises(TypeError):
            cache.gc(tmp_path, CFG, bad, dry_run=True)


def test_gc_ages_a_cache_by_its_file_time_when_the_document_has_no_readable_as_of(tmp_path):
    old = cache.save_cache(tmp_path, doc(4501, as_of="not a date"))
    fresh = cache.save_cache(tmp_path, doc(4502, as_of="also not a date"))
    bare = cache.cache_path(tmp_path, 4503)
    bare.write_text('{"schema": 1, "work_item": 4503}', encoding="utf-8")
    broken = cache.cache_path(tmp_path, 4504)
    broken.write_text("not json at all", encoding="utf-8")
    long_ago = datetime(2026, 10, 13, 12, 0) - timedelta(days=200)
    for path in (old, bare, broken):
        os.utime(path, (long_ago.timestamp(), long_ago.timestamp()))
    now = datetime(2026, 10, 13, 12, 0).timestamp()
    os.utime(fresh, (now, now))
    assert names(cache.gc(tmp_path, CFG, TODAY, dry_run=True)) == ["4501.json", "4503.json", "4504.json"]


# --- gc: unlinked items ----------------------------------------------------------------------------------------------------

def test_gc_deletes_the_cache_of_an_unlinked_item_even_when_it_is_fresh(tmp_path):
    seed(tmp_path, 4521, 0)
    seed(tmp_path, 4522, 0)
    write_ledger(tmp_path, [link("sdlc:spec:0004", 4521), link("sdlc:spec:0005", 4522),
                            unlink("sdlc:spec:0004")])
    assert cache.gc(tmp_path, CFG, TODAY, dry_run=False) == [cache.cache_path(tmp_path, 4521)]
    assert cache.cache_path(tmp_path, 4522).exists()


@pytest.mark.parametrize("event", ["linked", "adopted", "applied"])
def test_gc_knows_an_item_by_any_event_that_linked_it(tmp_path, event):
    seed(tmp_path, 4521, 0)
    write_ledger(tmp_path, [link("sdlc:spec:0004", 4521, event), unlink("sdlc:spec:0004")])
    assert names(cache.gc(tmp_path, CFG, TODAY, dry_run=True)) == ["4521.json"]


def test_gc_keeps_an_item_that_was_unlinked_and_then_linked_again(tmp_path):
    seed(tmp_path, 4521, 0)
    write_ledger(tmp_path, [link("sdlc:spec:0004", 4521), unlink("sdlc:spec:0004"),
                            link("sdlc:spec:0004", 4521, ts="2026-10-05T10:00Z")])
    assert cache.gc(tmp_path, CFG, TODAY, dry_run=True) == []


def test_gc_unlinks_the_old_item_when_a_ref_is_relinked_to_another(tmp_path):
    seed(tmp_path, 4521, 0)
    seed(tmp_path, 4530, 0)
    write_ledger(tmp_path, [link("sdlc:spec:0004", 4521), unlink("sdlc:spec:0004"),
                            link("sdlc:spec:0004", 4530, ts="2026-10-05T10:00Z")])
    assert names(cache.gc(tmp_path, CFG, TODAY, dry_run=True)) == ["4521.json"]


def test_gc_keeps_an_item_another_ref_still_points_at(tmp_path):
    seed(tmp_path, 4521, 0)
    write_ledger(tmp_path, [link("sdlc:spec:0004", 4521), link("sdlc:spec:0009", 4521), unlink("sdlc:spec:0004")])
    assert cache.gc(tmp_path, CFG, TODAY, dry_run=True) == []


def test_gc_ignores_a_field_scoped_reconcile_other_dispositions_and_an_unlink_of_nothing(tmp_path):
    for wid in (4521, 4522, 4523):
        seed(tmp_path, wid, 0)
    write_ledger(tmp_path, [
        link("sdlc:spec:0004", 4521), unlink("sdlc:spec:0004", field="System.State"),     # one field, not the item
        link("sdlc:spec:0005", 4522),
        model.ledger_entry("2026-10-01T10:00Z", "reconciled", ref="sdlc:spec:0005", disposition="RECREATE"),
        unlink("sdlc:spec:0099")])                                                        # never linked
    assert cache.gc(tmp_path, CFG, TODAY, dry_run=True) == []


@pytest.mark.parametrize("word", ["unlink", " UNLINK ", "Unlink"])
def test_gc_reads_the_unlink_disposition_the_way_status_does(tmp_path, word):
    seed(tmp_path, 4521, 0)
    write_ledger(tmp_path, [link("sdlc:spec:0004", 4521),
                            model.ledger_entry("2026-10-01T10:00Z", "reconciled", ref="sdlc:spec:0004",
                                               disposition=word)])
    assert names(cache.gc(tmp_path, CFG, TODAY, dry_run=True)) == ["4521.json"]


def test_gc_agrees_with_summarize_about_which_items_are_still_linked(tmp_path):
    ledger = [link("sdlc:spec:0004", 4521), link("sdlc:spec:0005", 4522), link("sdlc:spec:0006", 4523),
              unlink("sdlc:spec:0004"), unlink("sdlc:spec:0005"), link("sdlc:spec:0005", 4522, "adopted",
                                                                       ts="2026-10-05T10:00Z")]
    for wid in (4521, 4522, 4523):
        seed(tmp_path, wid, 0)
    write_ledger(tmp_path, ledger)
    still_linked = model.summarize(ledger, TODAY)["counts"]["linked"]
    kept = 3 - len(cache.gc(tmp_path, CFG, TODAY, dry_run=True))
    assert still_linked == kept == 2


def test_gc_tolerates_a_ledger_with_blank_garbled_and_foreign_lines(tmp_path):
    seed(tmp_path, 4521, 0)
    write_ledger(tmp_path, [link("sdlc:spec:0004", 4521), unlink("sdlc:spec:0004")],
                 raw_lines=["", "   ", "not json", "[1, 2, 3]", json.dumps({"event": "no-such-event"}),
                            json.dumps({"event": "linked", "ref": "sdlc:spec:0007", "work_item": "x"}),
                            json.dumps({"event": "linked", "ref": "sdlc:spec:0008", "work_item": True})])
    assert names(cache.gc(tmp_path, CFG, TODAY, dry_run=True)) == ["4521.json"]


# --- gc: what it leaves alone -----------------------------------------------------------------------------------------------

def test_gc_with_no_discussion_folder_and_no_ledger_is_an_empty_answer_and_creates_nothing(tmp_path):
    assert cache.gc(tmp_path, CFG, TODAY, dry_run=False) == []
    assert list(tmp_path.iterdir()) == []


def test_gc_touches_only_files_named_like_a_cache(tmp_path):
    seed(tmp_path, 4521, 400)
    folder = tmp_path / bc.DISCUSSION_DIR
    strangers = {"notes.txt", "abc.json", "007.json", "4521.json.tmp", "0.json"}
    for name in strangers:
        (folder / name).write_text("x", encoding="utf-8")
    (folder / "5.json").mkdir()                       # a folder named like a cache is not one
    me = cache.save_me(tmp_path, "@MCKRUZ", None, "2026-10-13T08:00Z")
    hook = tmp_path / bc.HOOK_STATUS
    hook.write_text("a line\n", encoding="utf-8")
    assert names(cache.gc(tmp_path, CFG, TODAY, dry_run=False)) == ["4521.json"]
    assert {p.name for p in folder.iterdir()} == strangers | {"5.json"}
    assert me.is_file() and hook.is_file()


@pytest.mark.skipif(sys.platform == "win32", reason="creating a symlink needs a privilege on Windows")
def test_gc_never_follows_or_removes_a_symlink(tmp_path):
    target = tmp_path / "elsewhere.json"
    target.write_text('{"schema": 1, "work_item": 9, "as_of": "2000-01-01"}', encoding="utf-8")
    folder = tmp_path / bc.DISCUSSION_DIR
    folder.mkdir(parents=True)
    (folder / "9.json").symlink_to(target)
    assert cache.gc(tmp_path, CFG, TODAY, dry_run=False) == []
    assert (folder / "9.json").is_symlink() and target.exists()


def test_gc_lets_a_failed_delete_surface_so_the_verb_can_say_drift(tmp_path, monkeypatch):
    seed(tmp_path, 4521, 400)

    def refuse(self, missing_ok=False):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "unlink", refuse)
    with pytest.raises(OSError):
        cache.gc(tmp_path, CFG, TODAY, dry_run=False)


def test_gc_does_not_fail_when_a_file_vanishes_between_the_listing_and_the_delete(tmp_path):
    seed(tmp_path, 4521, 400)
    seed(tmp_path, 4522, 400)
    real = Path.unlink
    gone = cache.cache_path(tmp_path, 4521)

    def racing(self, missing_ok=False):
        if self == gone:
            real(self)          # another process got there first
        return real(self, missing_ok=missing_ok)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "unlink", racing)
        assert names(cache.gc(tmp_path, CFG, TODAY, dry_run=False)) == ["4521.json", "4522.json"]
    assert list((tmp_path / bc.DISCUSSION_DIR).iterdir()) == []


# --- what the module writes --------------------------------------------------------------------------------------------------

def test_everything_the_module_writes_stays_under_the_ignored_local_folder(tmp_path):
    seed(tmp_path, 4521, 0)
    seed(tmp_path, 4522, 400)
    cache.save_me(tmp_path, "@MCKRUZ", IDENT_ID, "2026-10-13T08:00Z")
    cache.gc(tmp_path, CFG, TODAY, dry_run=False)
    files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert files == [".sdlc/ado/local/.gitignore", ".sdlc/ado/local/discussion/4521.json", ".sdlc/ado/local/me.json"]


def test_nothing_the_module_writes_goes_into_the_ledger(tmp_path):
    ledger = write_ledger(tmp_path, [link("sdlc:spec:0004", 4521)])
    before = ledger.read_bytes()
    seed(tmp_path, 4521, 400)
    cache.gc(tmp_path, CFG, TODAY, dry_run=False)
    assert ledger.read_bytes() == before  # the verb appends `discussion_gc`; the cache never does


# --- hygiene the gates also check ------------------------------------------------------------------------------------------

def test_the_cache_module_has_no_subprocess_no_shell_no_az_and_no_preview_revision():
    source = Path(cache.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s+subprocess\b", source, re.M)
    assert not re.search(r"shell=True|shlex\.join|os\.system", source)
    assert not re.search(r"-preview\.\d", source)
    tree = ast.parse(source)
    names_ = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names_ |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not names_ & {"subprocess", "ado_transport", "ado_wit", "ado_sync", "ado_sync_reconcile", "sprint",
                         "spec_transition"}, names_
