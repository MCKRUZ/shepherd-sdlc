"""`sync_kit.py` regenerates harness/ as rename(kit), and `--check` holds that invariant.

The kit is written for the upstream `claude-code-sdlc` plugin; this fork ships as Shepherd.
Rather than fork the kit or hand-edit the generated copy (CI's sync-check would stay red for
ever), the script rewrites the brand strings in place after the copy. These tests pin the parts
that matter: the rename map and its order, the exec bit surviving the in-place write, `--check`
comparing against rename(kit) rather than the raw kit, and the schema `$id` left alone.

No real kit is checked out here (`../delivery-standard` is absent on most machines), so each
test builds a small kit in tmp_path and points PAYLOAD at a tmp harness. The two tests at the
end read the committed `harness/` instead — the local half of CI's sync-check.
"""

import os
import re
import stat
import sys
from pathlib import Path

import pytest

import sync_kit

REAL_PAYLOAD = sync_kit.PAYLOAD  # captured before any fixture monkeypatches it
SCHEMA_REL = "profile/rails-telemetry.schema.json"
SCHEMA_ID = b'"$id": "https://mckruz.dev/delivery-standard/rails-telemetry.schema.json"'
COMMAND = re.compile(rb"(?<![\w./~])/sdlc\b")

README = b"""# Kit
/plugin marketplace add MCKRUZ/claude-code-sdlc
/plugin install claude-code-sdlc@mckruz
Run `/sdlc-setup` then `/sdlc-doctor`; state lives in `.sdlc/state.yaml`.
The `claude-code-sdlc` plugin (`claude-code-sdlc/profiles/starter`); see foo/sdlc/bar.
Harvest: https://github.com/MCKRUZ/intent-driven-development/issues/5
"""
HOOK = b"#!/usr/bin/env bash\n# see /sdlc-doctor\nexit 0\n"
SCHEMA = b'{\n  ' + SCHEMA_ID + b',\n  "description": "see /sdlc-doctor and claude-code-sdlc"\n}\n'
BLOB = b"PNG\x00/sdlc-doctor claude-code-sdlc\x00"


@pytest.fixture
def kit(tmp_path, monkeypatch) -> Path:
    """A four-file kit covering every branch, with PAYLOAD pointed at a tmp harness."""
    kit = tmp_path / "kit"
    (kit / "hooks").mkdir(parents=True)
    (kit / "profile").mkdir()
    (kit / "README.md").write_bytes(README)
    hook = kit / "hooks" / "stop-gate.sh"
    hook.write_bytes(HOOK)
    hook.chmod(0o755)
    (kit / SCHEMA_REL).write_bytes(SCHEMA)
    (kit / "blob.bin").write_bytes(BLOB)
    monkeypatch.setattr(sync_kit, "PAYLOAD", tmp_path / "harness")
    return kit


class TestRenameMap:
    def test_slash_commands_become_sprd(self):
        assert sync_kit.rename(b"run /sdlc-doctor, then /sdlc") == b"run /sprd-doctor, then /sprd"

    def test_path_tokens_are_not_commands(self):
        # `.sdlc/` is the state directory and `foo/sdlc` a path — neither is a slash command.
        # A `~/sdlc` home path or a doubled slash is a path too (correctness review on PR #4).
        for text in (b".sdlc/state.yaml", b"foo/sdlc/bar", b"a/sdlcx", b"~/sdlc/x", b"//sdlc"):
            assert sync_kit.rename(text) == text

    def test_specific_forms_resolve_before_the_bare_id(self):
        assert sync_kit.rename(b"MCKRUZ/claude-code-sdlc") == b"MCKRUZ/shepherd-sdlc"
        assert sync_kit.rename(b"claude-code-sdlc@mckruz") == b"shepherd@mckruz"
        assert sync_kit.rename(b"the claude-code-sdlc plugin") == b"the shepherd plugin"

    def test_order_is_load_bearing(self):
        # Run the map backwards and the bare rule gets to the URL first — the wrong repo.
        data = b"MCKRUZ/claude-code-sdlc"
        for pattern, replacement in reversed(sync_kit.RENAMES):
            data = pattern.sub(replacement, data)
        assert data == b"MCKRUZ/shepherd"

    def test_binary_is_left_alone(self):
        assert sync_kit.rename(BLOB) == BLOB


class TestSync:
    def test_rename_map_applied_on_copy(self, kit):
        assert sync_kit.sync(kit) == 0
        out = (sync_kit.PAYLOAD / "README.md").read_bytes()
        assert out == sync_kit.rename(README)
        assert b"/plugin marketplace add MCKRUZ/shepherd-sdlc" in out
        assert b"/plugin install shepherd@mckruz" in out
        assert b"`/sprd-setup` then `/sprd-doctor`" in out
        assert b"`shepherd/profiles/starter`" in out
        assert b"`.sdlc/state.yaml`" in out  # the state directory is the methodology, kept
        assert b"foo/sdlc/bar" in out  # a path token, kept
        assert b"MCKRUZ/intent-driven-development" in out  # the kit's own repo, not ours
        assert b"claude-code-sdlc" not in out
        assert not COMMAND.search(out)

    @pytest.mark.skipif(
        os.name == "nt",
        reason="no executable bit on Windows; git carries the mode (test_executable_bits.py)",
    )
    def test_hook_keeps_exec_bit_through_the_in_place_rewrite(self, kit):
        sync_kit.sync(kit)
        hook = sync_kit.PAYLOAD / "hooks" / "stop-gate.sh"
        assert b"/sprd-doctor" in hook.read_bytes()  # rewritten, not merely copied
        assert hook.stat().st_mode & stat.S_IXUSR

    def test_binary_copied_verbatim(self, kit):
        sync_kit.sync(kit)
        assert (sync_kit.PAYLOAD / "blob.bin").read_bytes() == BLOB

    def test_schema_id_untouched(self, kit):
        sync_kit.sync(kit)
        out = (sync_kit.PAYLOAD / SCHEMA_REL).read_bytes()
        assert out == SCHEMA  # the whole file: on the skip list, so even its prose is verbatim
        assert SCHEMA_ID in out

    def test_reports_how_many_files_were_renamed(self, kit, capsys):
        # README and the hook change; the schema is skipped and the blob is binary.
        sync_kit.sync(kit)
        out = capsys.readouterr().out
        assert "Synced 4 files" in out
        assert "(2 renamed for Shepherd)" in out

    def test_missing_kit_is_exit_2(self, kit):
        assert sync_kit.sync(kit / "nope") == 2


class TestCheck:
    def test_passes_against_renamed_kit(self, kit, capsys):
        sync_kit.sync(kit)
        capsys.readouterr()
        assert sync_kit.check(kit) == 0
        assert capsys.readouterr().out.startswith("IN SYNC")

    def test_fails_when_harness_is_the_raw_kit(self, kit, capsys):
        # A verbatim copy — what the pre-rename script produced — is drift now.
        sync_kit.sync(kit)
        (sync_kit.PAYLOAD / "README.md").write_bytes(README)
        capsys.readouterr()
        assert sync_kit.check(kit) == 1
        out = capsys.readouterr().out
        assert "CHANGED  README.md" in out
        assert "OUT OF SYNC" in out

    def test_skipped_file_is_still_compared(self, kit):
        # The skip list exempts the schema from the RENAME, not from the check.
        sync_kit.sync(kit)
        path = sync_kit.PAYLOAD / SCHEMA_REL
        path.write_bytes(path.read_bytes().replace(b"mckruz.dev", b"example.com"))
        assert sync_kit.check(kit) == 1

    def test_missing_and_stale_files(self, kit, capsys):
        sync_kit.sync(kit)
        (sync_kit.PAYLOAD / "blob.bin").unlink()
        (sync_kit.PAYLOAD / "extra.md").write_bytes(b"hand-edited\n")
        capsys.readouterr()
        assert sync_kit.check(kit) == 1
        out = capsys.readouterr().out
        assert "MISSING  blob.bin" in out
        assert "STALE    extra.md" in out

    def test_main_check_flag(self, kit, monkeypatch):
        sync_kit.sync(kit)
        monkeypatch.setattr(sys, "argv", ["sync_kit.py", "--kit", str(kit), "--check"])
        assert sync_kit.main() == 0

    def test_missing_kit_is_exit_2(self, kit):
        assert sync_kit.check(kit / "nope") == 2


class TestCommittedPayload:
    """The regenerated harness/ in this checkout, as CI's sync-check would see it."""

    def test_carries_no_upstream_brand_string(self):
        offenders = []
        for path in sorted(REAL_PAYLOAD.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(REAL_PAYLOAD).as_posix()
            data = path.read_bytes()
            if rel in sync_kit.RENAME_SKIP or b"\x00" in data:
                continue
            if COMMAND.search(data) or b"claude-code-sdlc" in data:
                offenders.append(rel)
        assert not offenders, (
            "harness/ still carries the upstream brand; it was copied without the rename pass. "
            "Re-run: uv run --project scripts scripts/sync_kit.py --kit <kit>\n  "
            + "\n  ".join(offenders)
        )

    def test_schema_id_is_the_upstream_identifier(self):
        assert SCHEMA_ID in (REAL_PAYLOAD / SCHEMA_REL).read_bytes()
