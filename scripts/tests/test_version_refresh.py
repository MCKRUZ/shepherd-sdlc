"""Tests for the artifact versioning + refresh layer folded into audit_artifacts.

Covers the invariants the plan calls out: the hash-join (object filename === ledger 16-hex), the
canonical torn-write-safe mutate (post-image on disk after os.replace; kill-between-append-and-replace
reconciles), rollback's confirm hardening + refuse-to-uncaptured, cross-ledger-refcounted gc with
sign-off protection, and capture-is-best-effort (a store fault leaves record --scan byte-identical).
Every path asserts exit 0 (advisory). P4/P5 (refresh) extend this file.
"""

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

import artifact_model as am
import audit_artifacts as aa
import version_model as vm
from track_artifacts import compute_checksum

REQ = ".sdlc/artifacts/01-requirements/requirements.md"


def _write(p: Path, text: str) -> None:
    """Write fixture content with LF endings on every platform.

    The `newline` argument is load-bearing, not cosmetic: the store captures — and
    `version show` returns — the exact bytes on disk, so a plain text-mode write (which
    expands each newline to CRLF on Windows) makes a byte-exact assertion pass on Linux
    and fail on Windows. Every fixture write of artifact content goes through this helper
    so the corpus is byte-identical on both."""
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def run_cli(argv, capsys) -> tuple[int, str]:
    old = sys.argv
    sys.argv = ["audit_artifacts.py"] + argv
    try:
        with pytest.raises(SystemExit) as ei:
            aa.main()
        code = ei.value.code
    finally:
        sys.argv = old
    return code, capsys.readouterr().out


def _write_state(tmp_path: Path, *, signed: bool) -> None:
    """Minimal state.yaml so load_state is truthy; the requirements phase is signed or not."""
    import yaml
    pid = aa.phase_id_of(REQ)
    pdata = {"status": "completed", "sign_off": True} if signed else {"status": "in_progress"}
    sdlc = tmp_path / ".sdlc"
    sdlc.mkdir(parents=True, exist_ok=True)
    (sdlc / "state.yaml").write_text(yaml.safe_dump({"phases": {pid: pdata}}), encoding="utf-8")


def _two_versions(tmp_path: Path, capsys) -> str:
    """Author requirements.md, baseline-scan (v1), drift + rescan (v2). Blobs land via the capture
    seam. Returns the node key. No state.yaml (standalone --repo)."""
    req = tmp_path / REQ
    _write(req, "line one\nline two\n")
    run_cli(["record", "--scan", "--repo", str(tmp_path)], capsys)
    _write(req, "line one EDITED\nline two\nline three\n")
    run_cli(["record", "--scan", "--repo", str(tmp_path)], capsys)
    return REQ


def _diffhash(out: str) -> str | None:
    m = re.search(r"--reviewed (sha256:[0-9a-f]+)", out)
    return m.group(1) if m else None


# --- refresh corpus helpers (P4) --------------------------------------------------------------

EPICS = ".sdlc/artifacts/02-design/epics.md"


def _write_upstreams(tmp_path: Path, *, req_text: str | None = None) -> None:
    """A minimal pre-Build corpus: requirements.md (owns FR-001, an '8 hours' SLA) + epics.md."""
    _write(tmp_path / REQ, req_text or
           "# Requirements\n\n## FR-001 Duplicate claim\n"
           "Reject a duplicate within 8 hours; return HTTP 409.\n")
    _write(tmp_path / EPICS, "# Epics\n\n## EP-01 Claims\nCovers FR-001.\n")


def _spec_rel(sid: str = "0001") -> str:
    return f"specs/{sid}-thing.md"


def _write_spec(tmp_path: Path, *, sid: str = "0001", status: str = "merged",
                source: str = "FR-001", accept: str = "within 8 hours returns HTTP 409") -> str:
    """Author a spec tracing to `source`, with one acceptance check. Returns its repo-relative path."""
    text = (
        "---\n"
        f'spec: "{sid}"\n'
        f"name: thing {sid}\n"
        f"status: {status}\n"
        "risk: HIGH\n"
        f"source: {source}\n"
        'channel: "—"\n'
        "---\n"
        f"# Thing {sid}\n\n"
        "## Scope — in\nDo the thing.\n\n"
        "## Scope — out\nNothing.\n\n"
        "## Acceptance Checks\n"
        f"- {accept}\n"
    )
    _write(tmp_path / _spec_rel(sid), text)
    return _spec_rel(sid)


# --- refresh write-path helpers (P5) ----------------------------------------------------------

def _proposed(tmp_path: Path, spec_rel: str, stem: str) -> Path:
    """The .proposed path for a stem (via the module, so the dir-keying convention is never dup'd)."""
    return aa._proposed_path(tmp_path / ".sdlc", spec_rel, stem)


def _agent_edits(tmp_path: Path, spec_rel: str, stem: str, text: str) -> None:
    """Simulate the discipline agent editing ONLY the .proposed draft."""
    _write(_proposed(tmp_path, spec_rel, stem), text)


def _apply(tmp_path, spec_rel, stem, capsys, *, actor="kai", reviewed=None, ack=True, extra=None):
    argv = ["refresh", "apply", "--spec", spec_rel, stem, "--repo", str(tmp_path)]
    if actor:
        argv += ["--actor", actor]
    if reviewed:
        argv += ["--reviewed", reviewed]
    if ack:
        argv += ["--ack-signoff"]
    if extra:
        argv += extra
    return run_cli(argv, capsys)


def _confirm_apply(tmp_path, spec_rel, stem, capsys, *, actor="kai", ack=True):
    """Preview to harvest the diffhash, then apply for real. Returns (code, confirm_out)."""
    _, prev = _apply(tmp_path, spec_rel, stem, capsys, actor=None, reviewed=None, ack=False)
    dh = _diffhash(prev)
    return _apply(tmp_path, spec_rel, stem, capsys, actor=actor, reviewed=dh, ack=ack)


# --- hash-join invariant ----------------------------------------------------------------------

class TestHashJoin:
    def test_object_filename_is_the_ledger_hash(self, tmp_path):
        data = b"# Requirements\nhello\n"
        vdir = tmp_path / ".sdlc" / "versions"
        h = aa.capture_bytes(vdir, data)
        assert h == aa.hash_bytes(data)
        rel = vm.object_relpath(h)
        blob = vdir / rel
        assert blob.is_file()
        assert blob.name == vm.hash_hex(h)          # filename IS the 16-hex — no second index

    def test_hash_bytes_equals_compute_checksum_of_same_bytes(self, tmp_path):
        data = b"identical bytes\nacross both hashing paths\n"
        f = tmp_path / "f.md"
        f.write_bytes(data)
        assert aa.hash_bytes(data) == compute_checksum(f)

    def test_capture_is_idempotent(self, tmp_path):
        vdir = tmp_path / ".sdlc" / "versions"
        data = b"same\n"
        h1 = aa.capture_bytes(vdir, data)
        h2 = aa.capture_bytes(vdir, data)           # write-if-absent — second call is a no-op
        assert h1 == h2
        assert len(list((vdir / "objects").rglob("*"))) >= 1


# --- version list / show (P2, regression) -----------------------------------------------------

class TestListShow:
    def test_list_shows_ordinals_and_capture_state(self, tmp_path, capsys):
        _two_versions(tmp_path, capsys)
        code, out = run_cli(["version", "list", "requirements.md", "--repo", str(tmp_path), "--json"], capsys)
        assert code == 0
        rows = json.loads(out)["versions"]
        assert [r["n"] for r in rows] == [1, 2]
        assert all(r["present"] for r in rows)      # both captured by the scan seam

    def test_show_retrieves_old_content_after_drift(self, tmp_path, capsys):
        _two_versions(tmp_path, capsys)             # disk is now v2
        code, out = run_cli(["version", "show", "requirements.md", "v1", "--repo", str(tmp_path)], capsys)
        assert code == 0
        assert out == "line one\nline two\n"        # the ORIGINAL, not what's on disk

    def test_baseline_synthesis_before_any_scan(self, tmp_path, capsys):
        _write(tmp_path / REQ, "never scanned\n")
        code, out = run_cli(["version", "list", "requirements.md", "--repo", str(tmp_path), "--json"], capsys)
        rows = json.loads(out)["versions"]
        assert len(rows) == 1 and rows[0]["event"] == "baseline"
        assert rows[0]["present"] is False          # nothing captured yet


# --- diff -------------------------------------------------------------------------------------

class TestDiff:
    def test_default_prev_to_latest(self, tmp_path, capsys):
        _two_versions(tmp_path, capsys)
        code, out = run_cli(["version", "diff", "requirements.md", "--repo", str(tmp_path)], capsys)
        assert code == 0
        assert "-line one" in out and "+line one EDITED" in out and "+line three" in out

    def test_single_version_nothing_to_compare(self, tmp_path, capsys):
        _write(tmp_path / REQ, "only one\n")
        run_cli(["record", "--scan", "--repo", str(tmp_path)], capsys)
        code, out = run_cli(["version", "diff", "requirements.md", "--repo", str(tmp_path)], capsys)
        assert code == 0 and "only one version" in out

    def test_missing_blob_degrades(self, tmp_path, capsys):
        _two_versions(tmp_path, capsys)
        # evict the v1 blob, then diff must degrade (not crash).
        rows = json.loads(run_cli(
            ["version", "list", "requirements.md", "--repo", str(tmp_path), "--json"], capsys)[1])["versions"]
        v1 = next(r for r in rows if r["n"] == 1)
        (tmp_path / ".sdlc" / "versions" / vm.object_relpath(v1["hash"])).unlink()
        code, out = run_cli(["version", "diff", "requirements.md", "v1", "v2", "--repo", str(tmp_path)], capsys)
        assert code == 0 and "content not captured" in out
        # multi-machine honesty: the message explains WHY (local & gitignored) and what to do.
        assert "local and gitignored" in out
        assert "record --scan" in out and "references/artifact-versioning.md" in out


# --- rollback: canonical mutate + confirm hardening -------------------------------------------

class TestRollback:
    def test_preview_writes_no_change_and_offers_diffhash(self, tmp_path, capsys):
        _two_versions(tmp_path, capsys)
        before = (tmp_path / REQ).read_text(encoding="utf-8")
        code, out = run_cli(["version", "rollback", "requirements.md", "v1", "--repo", str(tmp_path)], capsys)
        assert code == 0 and _diffhash(out)
        assert (tmp_path / REQ).read_text(encoding="utf-8") == before   # preview never writes

    def test_confirm_applies_and_is_append_only_restore(self, tmp_path, capsys):
        # Standalone --repo has no state.yaml, so sign-off can't be verified -> --ack-signoff required
        # (the plan's "degrade to a generic warning still requiring the flag").
        node = _two_versions(tmp_path, capsys)
        dh = _diffhash(run_cli(["version", "rollback", "requirements.md", "v1", "--repo", str(tmp_path)], capsys)[1])
        code, out = run_cli(["version", "rollback", "requirements.md", "v1", "--confirm", "--actor", "kai",
                             "--reviewed", dh, "--ack-signoff", "--repo", str(tmp_path)], capsys)
        assert code == 0 and "Rolled back" in out
        # disk is the original v1 content again
        assert (tmp_path / node).read_text(encoding="utf-8") == "line one\nline two\n"
        # append-only: a new v3 whose content is v1's -> rendered "restored from v1"
        rows = json.loads(run_cli(
            ["version", "list", "requirements.md", "--repo", str(tmp_path), "--json"], capsys)[1])["versions"]
        assert [r["n"] for r in rows] == [1, 2, 3]
        assert rows[2]["event"] == "revised" and rows[2]["restored_from"] == 1

    def test_mutate_leaves_post_image_hash_on_disk(self, tmp_path, capsys):
        """B1 forward direction: after os.replace, the ledger's latest hash == the file's hash."""
        node = _two_versions(tmp_path, capsys)
        dh = _diffhash(run_cli(["version", "rollback", "requirements.md", "v1", "--repo", str(tmp_path)], capsys)[1])
        run_cli(["version", "rollback", "requirements.md", "v1", "--confirm", "--actor", "kai",
                 "--reviewed", dh, "--ack-signoff", "--repo", str(tmp_path)], capsys)
        ledger = aa.load_ledger(tmp_path / ".sdlc" / "metrics" / "artifact-log.jsonl")
        latest = am.latest_change_per_artifact(ledger)[node]
        assert latest["hash"] == compute_checksum(tmp_path / node)

    def test_agent_actor_is_refused(self, tmp_path, capsys):
        _two_versions(tmp_path, capsys)
        dh = _diffhash(run_cli(["version", "rollback", "requirements.md", "v1", "--repo", str(tmp_path)], capsys)[1])
        code, out = run_cli(["version", "rollback", "requirements.md", "v1", "--confirm",
                             "--actor", "requirements-analyst", "--reviewed", dh, "--repo", str(tmp_path)], capsys)
        assert code == 0 and "discipline agent" in out and "One Rule" in out

    def test_confirm_without_reviewed_is_refused(self, tmp_path, capsys):
        _two_versions(tmp_path, capsys)
        code, out = run_cli(["version", "rollback", "requirements.md", "v1", "--confirm",
                             "--actor", "kai", "--repo", str(tmp_path)], capsys)
        assert code == 0 and "--reviewed" in out

    def test_stale_reviewed_is_refused(self, tmp_path, capsys):
        _two_versions(tmp_path, capsys)
        code, out = run_cli(["version", "rollback", "requirements.md", "v1", "--confirm", "--actor", "kai",
                             "--reviewed", "sha256:deadbeefdeadbeef", "--repo", str(tmp_path)], capsys)
        assert code == 0 and "does not match" in out

    def test_rollback_to_uncaptured_refuses(self, tmp_path, capsys):
        """Edge E2: a rollback target with no blob refuses — never os.replace from a missing object."""
        _two_versions(tmp_path, capsys)
        rows = json.loads(run_cli(
            ["version", "list", "requirements.md", "--repo", str(tmp_path), "--json"], capsys)[1])["versions"]
        v1 = next(r for r in rows if r["n"] == 1)
        (tmp_path / ".sdlc" / "versions" / vm.object_relpath(v1["hash"])).unlink()
        before = (tmp_path / REQ).read_text(encoding="utf-8")
        code, out = run_cli(["version", "rollback", "requirements.md", "v1", "--confirm", "--actor", "kai",
                             "--reviewed", "sha256:whatever", "--repo", str(tmp_path)], capsys)
        assert code == 0 and "content not captured" in out
        # the refuse message carries the multi-machine hint (why + remedy), not just the bare refusal.
        assert "local and gitignored" in out and "record --scan" in out
        assert (tmp_path / REQ).read_text(encoding="utf-8") == before   # nothing written

    def test_idempotent_rollback_to_current_is_noop(self, tmp_path, capsys):
        _two_versions(tmp_path, capsys)
        code, out = run_cli(["version", "rollback", "requirements.md", "latest", "--repo", str(tmp_path)], capsys)
        assert code == 0 and "already matches" in out

    def test_signed_off_needs_ack(self, tmp_path, capsys):
        node = _two_versions(tmp_path, capsys)
        _write_state(tmp_path, signed=True)         # requirements phase now signed off
        dh = _diffhash(run_cli(["version", "rollback", "requirements.md", "v1",
                                "--state", str(tmp_path / ".sdlc" / "state.yaml")], capsys)[1])
        # without --ack-signoff -> refuse
        code, out = run_cli(["version", "rollback", "requirements.md", "v1", "--confirm", "--actor", "kai",
                             "--reviewed", dh, "--state", str(tmp_path / ".sdlc" / "state.yaml")], capsys)
        assert code == 0 and "ack-signoff" in out
        assert (tmp_path / node).read_text(encoding="utf-8") != "line one\nline two\n"
        # with the flag -> applies
        code, out = run_cli(["version", "rollback", "requirements.md", "v1", "--confirm", "--actor", "kai",
                             "--reviewed", dh, "--ack-signoff",
                             "--state", str(tmp_path / ".sdlc" / "state.yaml")], capsys)
        assert code == 0 and "Rolled back" in out


# --- torn-write recovery ----------------------------------------------------------------------

class TestRecovery:
    def test_journal_completes_interrupted_replace(self, tmp_path):
        vdir = tmp_path / ".sdlc" / "versions"
        target = tmp_path / REQ
        _write(target, "OLD\n")
        newbytes = b"NEW COMMITTED CONTENT\n"
        h = aa.capture_bytes(vdir, newbytes)        # post-image object exists
        aa._write_pending(vdir, REQ, h)             # ledger appended, killed before os.replace
        aa.recover_pending(tmp_path, vdir)
        assert target.read_bytes() == newbytes      # replace redone
        assert not aa._pending_path(vdir).exists()  # journal cleared

    def test_no_journal_leaves_drift_untouched(self, tmp_path):
        """Ordinary un-scanned drift must NEVER be clobbered — recovery fires only on the journal."""
        vdir = tmp_path / ".sdlc" / "versions"
        target = tmp_path / REQ
        _write(target, "user's unsaved edit\n")
        aa.capture_bytes(vdir, b"some other content\n")   # a blob exists, but no journal
        aa.recover_pending(tmp_path, vdir)
        assert target.read_text(encoding="utf-8") == "user's unsaved edit\n"

    def test_recovery_survives_corrupt_journal(self, tmp_path):
        vdir = tmp_path / ".sdlc" / "versions"
        vdir.mkdir(parents=True, exist_ok=True)
        aa._pending_path(vdir).write_text("{not json", encoding="utf-8")
        aa.recover_pending(tmp_path, vdir)          # must not raise
        assert not aa._pending_path(vdir).exists()


# --- gc ---------------------------------------------------------------------------------------

class TestGc:
    def test_unknown_signoff_protects_everything(self, tmp_path, capsys):
        _two_versions(tmp_path, capsys)             # --repo, no state.yaml -> sign-off unknown
        code, out = run_cli(["version", "gc", "--keep", "1", "--repo", str(tmp_path)], capsys)
        assert code == 0 and "sign-off status unknown" in out and "nothing to prune" in out

    def test_evicts_non_retained_when_signoff_known(self, tmp_path, capsys):
        _two_versions(tmp_path, capsys)
        _write_state(tmp_path, signed=False)        # known + unsigned -> not protected
        state = str(tmp_path / ".sdlc" / "state.yaml")
        code, out = run_cli(["version", "gc", "--keep", "1", "--state", state], capsys)
        assert code == 0 and "1 object(s) prunable" in out
        # preview only — the object is still on disk
        assert list((tmp_path / ".sdlc" / "versions" / "objects").rglob("*sha256*")) or \
            any((tmp_path / ".sdlc" / "versions" / "objects").rglob("*"))
        code, out = run_cli(["version", "gc", "--keep", "1", "--apply", "--state", state], capsys)
        assert code == 0 and "pruned 1 object" in out

    def test_signed_off_artifact_is_protected(self, tmp_path, capsys):
        _two_versions(tmp_path, capsys)
        _write_state(tmp_path, signed=True)
        state = str(tmp_path / ".sdlc" / "state.yaml")
        code, out = run_cli(["version", "gc", "--keep", "1", "--apply", "--state", state], capsys)
        assert code == 0 and "nothing to prune" in out

    def test_shared_hash_retained_across_artifacts(self, tmp_path, capsys):
        """Dedup: a hash that is an old version of one artifact but the latest of another survives."""
        node = _two_versions(tmp_path, capsys)
        # roll back to v1 -> v3 shares v1's hash; that hash is now the LATEST, must never be evicted.
        dh = _diffhash(run_cli(["version", "rollback", "requirements.md", "v1", "--repo", str(tmp_path)], capsys)[1])
        run_cli(["version", "rollback", "requirements.md", "v1", "--confirm", "--actor", "kai",
                 "--reviewed", dh, "--ack-signoff", "--repo", str(tmp_path)], capsys)
        _write_state(tmp_path, signed=False)
        state = str(tmp_path / ".sdlc" / "state.yaml")
        run_cli(["version", "gc", "--keep", "1", "--apply", "--state", state], capsys)
        # v1's content is still retrievable because v3 (latest) shares its hash.
        code, out = run_cli(["version", "show", "requirements.md", "v1", "--state", state], capsys)
        assert code == 0 and out == "line one\nline two\n"


# --- multi-machine honesty: the enriched missing-blob hint ------------------------------------

class TestMultiMachineHint:
    """Every degraded-content message explains the local/gitignored store honestly and says what to
    do — so a user on a second machine (fresh clone, CI, post-gc, store fault) doesn't read a bug."""

    def test_show_missing_blob_prints_hint(self, tmp_path, capsys):
        _write(tmp_path / REQ, "never scanned\n")           # baseline, nothing captured (present=False)
        code, out = run_cli(["version", "show", "requirements.md", "--repo", str(tmp_path)], capsys)
        assert code == 0 and "content not captured" in out
        assert "local and gitignored" in out
        assert "record --scan" in out and "references/artifact-versioning.md" in out

    def test_list_fresh_clone_prints_footer_hint(self, tmp_path, capsys):
        """Zero captured versions (the fresh-clone case) -> the hint is printed once as a footer."""
        _write(tmp_path / REQ, "never scanned\n")
        code, out = run_cli(["version", "list", "requirements.md", "--repo", str(tmp_path)], capsys)
        assert code == 0 and "[content not captured]" in out   # the per-row tag is still there
        assert "local and gitignored" in out and "record --scan" in out

    def test_list_all_captured_does_not_spam_hint(self, tmp_path, capsys):
        """No missing blobs -> no footer hint (don't cry wolf when every version is present)."""
        _two_versions(tmp_path, capsys)                        # both captured by the scan seam
        code, out = run_cli(["version", "list", "requirements.md", "--repo", str(tmp_path)], capsys)
        assert code == 0
        assert "content not captured" not in out               # nothing degraded -> no hint
        assert "record --scan" not in out

    def test_list_mixed_history_prints_one_line_pointer(self, tmp_path, capsys):
        """Some-but-not-all captured (single-blob gc / store fault) -> a one-line pointer, not the
        full two-line note — the tagged row still gets an explanation without footer spam."""
        _two_versions(tmp_path, capsys)
        rows = json.loads(run_cli(
            ["version", "list", "requirements.md", "--repo", str(tmp_path), "--json"], capsys)[1])["versions"]
        v1 = next(r for r in rows if r["n"] == 1)
        (tmp_path / ".sdlc" / "versions" / vm.object_relpath(v1["hash"])).unlink()   # evict v1 only
        code, out = run_cli(["version", "list", "requirements.md", "--repo", str(tmp_path)], capsys)
        assert code == 0 and "[content not captured]" in out
        assert "1 version(s) not captured on this machine" in out
        assert "references/artifact-versioning.md" in out
        assert "record --scan" not in out                      # the full note is NOT printed

    def test_gc_apply_points_at_recovery(self, tmp_path, capsys):
        """After a prune, gc says the pruned versions now degrade AND how to recover / go portable."""
        _two_versions(tmp_path, capsys)
        _write_state(tmp_path, signed=False)
        state = str(tmp_path / ".sdlc" / "state.yaml")
        code, out = run_cli(["version", "gc", "--keep", "1", "--apply", "--state", state], capsys)
        assert code == 0 and "pruned 1 object" in out
        assert "local and gitignored" in out and "references/artifact-versioning.md" in out


# --- capture best-effort ----------------------------------------------------------------------

class TestCaptureBestEffort:
    def test_store_fault_leaves_scan_byte_identical(self, tmp_path, capsys, monkeypatch):
        """An unwritable object store must not change record --scan's exit / stdout / ledger."""
        _write(tmp_path / REQ, "content\n")
        monkeypatch.setattr(aa, "capture_bytes", lambda *a, **k: None)   # store fully unwritable
        code, out = run_cli(["record", "--scan", "--repo", str(tmp_path)], capsys)
        assert code == 0 and "Baseline recorded" in out
        ledger = aa.load_ledger(tmp_path / ".sdlc" / "metrics" / "artifact-log.jsonl")
        assert any(e.get("artifact") == REQ and e.get("event") == "created" for e in ledger)
        assert not (tmp_path / ".sdlc" / "versions" / "objects").exists()   # no blobs, but ledger intact


# --- refresh detect: divergence-aware, review-first (P4) --------------------------------------

class TestRefreshDetect:
    def test_surfaces_substantiated_upstream_with_discipline(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, accept="within 8 hours returns HTTP 409")   # faithful
        code, out = run_cli(["refresh", "detect", "--spec", spec, "--repo", str(tmp_path), "--json"], capsys)
        assert code == 0
        cands = json.loads(out)["candidates"]
        assert len(cands) == 1                              # only the substantiated FR-001 owner
        c = cands[0]
        assert c["target"] == REQ
        assert c["discipline"] == "requirements-analyst"    # DISCIPLINE_BY_STEM, emitted per candidate
        assert c["basis"] == "id-reference"
        assert c["confidence"] == "declared"
        assert c["drift"] is False                          # faithful spec -> trace-only

    def test_faithful_spec_is_review_only_without_draft(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, accept="within 8 hours returns HTTP 409")
        code, out = run_cli(["refresh", "detect", "--spec", spec, "--repo", str(tmp_path)], capsys)
        assert code == 0
        assert "trace-only" in out and "review only" in out
        assert "would draft" not in out                     # review-first default: no draft

    def test_drift_makes_candidate_draft_eligible(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, accept="within 4 hours returns HTTP 409")   # 4h != upstream 8h
        code, out = run_cli(["refresh", "detect", "--spec", spec, "--repo", str(tmp_path)], capsys)
        assert code == 0 and "DRIFT" in out and "would draft" in out
        code, out = run_cli(["refresh", "detect", "--spec", spec, "--repo", str(tmp_path), "--json"], capsys)
        assert json.loads(out)["candidates"][0]["drift"] is True

    def test_draft_flag_makes_faithful_eligible(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, accept="within 8 hours returns HTTP 409")
        code, out = run_cli(["refresh", "detect", "--spec", spec, "--draft", "--repo", str(tmp_path)], capsys)
        assert code == 0 and "would draft" in out           # --draft widens eligibility to declared

    def test_phantom_id_yields_no_candidate(self, tmp_path, capsys):
        """R2: a spec citing an id no upstream declares surfaces nothing — never a fabricated target."""
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, source="FR-999")       # FR-999 absent from requirements.md
        code, out = run_cli(["refresh", "detect", "--spec", spec, "--repo", str(tmp_path), "--json"], capsys)
        assert code == 0 and json.loads(out)["candidates"] == []
        _, out = run_cli(["refresh", "detect", "--spec", spec, "--repo", str(tmp_path)], capsys)
        assert "No traceable upstream" in out

    def test_no_source_yields_nudge(self, tmp_path, capsys):
        """R2: source: — (no id anywhere) -> zero candidates + the nudge, never a coarse fabrication."""
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, source="—")
        code, out = run_cli(["refresh", "detect", "--spec", spec, "--repo", str(tmp_path)], capsys)
        assert code == 0 and "No traceable upstream" in out

    def test_non_pre_build_upstream_filtered(self, tmp_path, capsys):
        """R1: an NFR reference maps to non-functional-requirements.md, NOT a PRE_BUILD stem -> filtered."""
        _write(tmp_path / ".sdlc/artifacts/01-requirements/non-functional-requirements.md",
               "# NFR\n\n## NFR-01 Latency\nUnder 200 ms.\n")
        spec = _write_spec(tmp_path, source="NFR-01")
        code, out = run_cli(["refresh", "detect", "--spec", spec, "--repo", str(tmp_path), "--json"], capsys)
        assert code == 0 and json.loads(out)["candidates"] == []

    def test_coarse_listed_but_never_draftable(self, tmp_path, capsys):
        """--include-coarse surfaces a phase-order guess, but it is never draft-eligible (even faithful)."""
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, source="—")            # no declared upstream -> coarse edges exist
        code, out = run_cli(["refresh", "detect", "--spec", spec, "--include-coarse",
                             "--draft", "--repo", str(tmp_path), "--json"], capsys)
        assert code == 0
        cands = json.loads(out)["candidates"]
        assert cands and all(c["confidence"] == "coarse" for c in cands)
        _, out = run_cli(["refresh", "detect", "--spec", spec, "--include-coarse", "--draft",
                          "--repo", str(tmp_path)], capsys)
        assert "never auto-drafted" in out and "would draft" not in out

    def test_already_fresher_is_suppressed(self, tmp_path, capsys):
        """An upstream changed AFTER the spec last did is suppressed as already-fresher (not a candidate)."""
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, accept="within 4 hours returns HTTP 409")
        run_cli(["record", "--scan", "--repo", str(tmp_path)], capsys)       # baseline: spec + req at ts0
        _write(tmp_path / REQ, "# Requirements\n\n## FR-001\nNow within 4 hours; HTTP 409.\n")
        run_cli(["record", "--scan", "--repo", str(tmp_path)], capsys)       # req now at ts1 > spec ts0
        code, out = run_cli(["refresh", "detect", "--spec", spec, "--repo", str(tmp_path), "--json"], capsys)
        assert code == 0
        cands = json.loads(out)["candidates"]
        assert len(cands) == 1 and cands[0]["already_fresher"] is True
        _, out = run_cli(["refresh", "detect", "--spec", spec, "--repo", str(tmp_path)], capsys)
        assert "already fresher" in out and "would draft" not in out

    def test_non_merged_spec_notes_status(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, status="ready", accept="within 4 hours returns HTTP 409")
        code, out = run_cli(["refresh", "detect", "--spec", spec, "--repo", str(tmp_path)], capsys)
        assert code == 0 and "not 'merged'" in out          # still runs (advisory), but flags the status

    def test_unresolvable_spec_exits_zero(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        code, out = run_cli(["refresh", "detect", "--spec", "specs/nope.md", "--repo", str(tmp_path)], capsys)
        assert code == 0 and "could not find spec" in out

    def test_detect_writes_nothing(self, tmp_path, capsys):
        """Detection is side-effect-free: no ledger, no object store, no refresh dir."""
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, accept="within 4 hours returns HTTP 409")
        run_cli(["refresh", "detect", "--spec", spec, "--draft", "--repo", str(tmp_path)], capsys)
        assert not (tmp_path / ".sdlc" / "metrics" / "artifact-log.jsonl").exists()
        assert not (tmp_path / ".sdlc" / "versions").exists()
        assert not (tmp_path / ".sdlc" / "refresh").exists()


# --- refresh scan: rollup across merged specs (P4) --------------------------------------------

class TestRefreshScan:
    def test_counts_merged_and_drift(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        _write_spec(tmp_path, sid="0001", accept="within 4 hours returns HTTP 409")   # merged + drift
        _write_spec(tmp_path, sid="0002", status="ready", accept="within 4 hours")    # not merged
        code, out = run_cli(["refresh", "scan", "--repo", str(tmp_path), "--json"], capsys)
        assert code == 0
        data = json.loads(out)
        assert data["merged_specs"] == 1                    # only the merged spec is scanned
        assert data["drifted_total"] == 1

    def test_no_merged_specs(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        _write_spec(tmp_path, status="ready")
        code, out = run_cli(["refresh", "scan", "--repo", str(tmp_path)], capsys)
        assert code == 0 and "no merged specs" in out

    def test_scan_writes_nothing(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        _write_spec(tmp_path, accept="within 4 hours returns HTTP 409")
        run_cli(["refresh", "scan", "--repo", str(tmp_path)], capsys)
        assert not (tmp_path / ".sdlc" / "metrics" / "artifact-log.jsonl").exists()
        assert not (tmp_path / ".sdlc" / "versions").exists()


# --- refresh draft: seed .proposed + candidates.json (P5) -------------------------------------

class TestRefreshDraft:
    def test_drafts_drifted_candidate(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, accept="within 4 hours returns HTTP 409")   # drifts
        code, out = run_cli(["refresh", "draft", "--spec", spec, "--repo", str(tmp_path)], capsys)
        assert code == 0 and "Staged 1 draft" in out
        pp = _proposed(tmp_path, spec, "requirements")
        assert pp.is_file()
        assert pp.read_text() == (tmp_path / REQ).read_text()   # seeded with the CURRENT upstream

    def test_candidates_json_pins_hash_and_discipline(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, accept="within 4 hours returns HTTP 409")
        run_cli(["refresh", "draft", "--spec", spec, "--repo", str(tmp_path)], capsys)
        data = json.loads(aa._candidates_path(tmp_path / ".sdlc", spec).read_text())
        rec = data["candidates"][0]
        assert rec["stem"] == "requirements"
        assert rec["discipline"] == "requirements-analyst"
        assert rec["upstream_hash"] == aa.hash_bytes((tmp_path / REQ).read_bytes())  # pinned to bytes copied

    def test_review_first_no_draft_without_flag(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, accept="within 8 hours returns HTTP 409")   # faithful, no drift
        code, out = run_cli(["refresh", "draft", "--spec", spec, "--repo", str(tmp_path)], capsys)
        assert code == 0 and "no drift detected" in out and "Pass --draft" in out
        assert not _proposed(tmp_path, spec, "requirements").exists()

    def test_draft_flag_drafts_faithful(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, accept="within 8 hours returns HTTP 409")
        code, out = run_cli(["refresh", "draft", "--spec", spec, "--draft", "--repo", str(tmp_path)], capsys)
        assert code == 0 and "Staged 1 draft" in out
        assert _proposed(tmp_path, spec, "requirements").is_file()

    def test_redraft_overwrites_and_warns(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, accept="within 4 hours returns HTTP 409")
        run_cli(["refresh", "draft", "--spec", spec, "--repo", str(tmp_path)], capsys)
        _agent_edits(tmp_path, spec, "requirements", "stale edit\n")
        code, out = run_cli(["refresh", "draft", "--spec", spec, "--repo", str(tmp_path)], capsys)
        assert code == 0 and "re-drafting" in out and "overwritten" in out
        # the re-draft re-seeds from the current upstream, discarding the stale edit
        assert _proposed(tmp_path, spec, "requirements").read_text() == (tmp_path / REQ).read_text()

    def test_no_candidate_nudges(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, source="—")
        code, out = run_cli(["refresh", "draft", "--spec", spec, "--repo", str(tmp_path)], capsys)
        assert code == 0 and "no draftable upstream" in out


# --- refresh apply: named-human confirm, guards, canonical mutate (P5) ------------------------

class TestRefreshApply:
    def _drift_and_draft(self, tmp_path, capsys, *, sid="0001"):
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, sid=sid, accept="within 4 hours returns HTTP 409")
        run_cli(["record", "--scan", "--repo", str(tmp_path)], capsys)    # baseline v1
        run_cli(["refresh", "draft", "--spec", spec, "--repo", str(tmp_path)], capsys)
        _agent_edits(tmp_path, spec, "requirements",
                     "# Requirements\n\n## FR-001 Duplicate claim\n"
                     "Reject a duplicate within 4 hours; return HTTP 409.\n")
        return spec

    def test_preview_does_not_touch_the_real_file(self, tmp_path, capsys):
        spec = self._drift_and_draft(tmp_path, capsys)
        before = (tmp_path / REQ).read_text()
        code, out = _apply(tmp_path, spec, "requirements", capsys, actor=None, reviewed=None, ack=False)
        assert code == 0 and "preview only" in out and _diffhash(out)
        assert (tmp_path / REQ).read_text() == before          # untouched

    def test_agent_actor_rejected(self, tmp_path, capsys):
        spec = self._drift_and_draft(tmp_path, capsys)
        _, prev = _apply(tmp_path, spec, "requirements", capsys, actor=None, ack=False)
        code, out = _apply(tmp_path, spec, "requirements", capsys,
                           actor="requirements-analyst", reviewed=_diffhash(prev))
        assert code == 0 and "discipline agent" in out and "One Rule" in out
        assert "4 hours" not in (tmp_path / REQ).read_text()   # nothing written

    def test_wrong_reviewed_rejected(self, tmp_path, capsys):
        spec = self._drift_and_draft(tmp_path, capsys)
        code, out = _apply(tmp_path, spec, "requirements", capsys, reviewed="sha256:deadbeef")
        assert code == 0 and "does not match" in out
        assert "4 hours" not in (tmp_path / REQ).read_text()

    def test_confirm_applies_and_records_refreshed_with_source_spec(self, tmp_path, capsys):
        spec = self._drift_and_draft(tmp_path, capsys)
        code, out = _confirm_apply(tmp_path, spec, "requirements", capsys)
        assert code == 0 and "Refreshed" in out
        assert "within 4 hours" in (tmp_path / REQ).read_text()   # the real artifact moved
        ledger = aa.load_ledger(tmp_path / ".sdlc" / "metrics" / "artifact-log.jsonl")
        refreshed = [e for e in ledger if e.get("event") == "refreshed"]
        assert len(refreshed) == 1
        assert refreshed[0]["source_spec"] == "0001"              # additive rider, per-spec attribution
        assert refreshed[0]["artifact"] == REQ

    def test_apply_is_rollback_able(self, tmp_path, capsys):
        """The safety net: a refresh lands as an append-only version, restorable to the pre-image."""
        spec = self._drift_and_draft(tmp_path, capsys)
        _confirm_apply(tmp_path, spec, "requirements", capsys)
        versions = aa._versions_of(tmp_path, tmp_path / ".sdlc" / "metrics",
                                   tmp_path / ".sdlc" / "versions", REQ)
        assert [v["event"] for v in versions] == ["created", "refreshed"]
        _, prev = run_cli(["version", "rollback", REQ, "prev", "--repo", str(tmp_path)], capsys)
        run_cli(["version", "rollback", REQ, "prev", "--confirm", "--actor", "kai",
                 "--reviewed", _diffhash(prev), "--ack-signoff", "--repo", str(tmp_path)], capsys)
        assert "within 8 hours" in (tmp_path / REQ).read_text()   # restored the pre-refresh content

    def test_cleans_up_draft_on_apply(self, tmp_path, capsys):
        spec = self._drift_and_draft(tmp_path, capsys)
        _confirm_apply(tmp_path, spec, "requirements", capsys)
        assert not _proposed(tmp_path, spec, "requirements").exists()
        assert not aa._candidates_path(tmp_path / ".sdlc", spec).exists()

    def test_staleness_guard_when_upstream_moves(self, tmp_path, capsys):
        spec = self._drift_and_draft(tmp_path, capsys)
        _write(tmp_path / REQ, "# Requirements\n\n## FR-001\nmoved on disk after draft\n")
        _, prev = _apply(tmp_path, spec, "requirements", capsys, actor=None, ack=False)
        code, out = _apply(tmp_path, spec, "requirements", capsys, reviewed="sha256:whatever")
        assert code == 0 and "moved since the draft" in out

    def test_identical_draft_is_noop(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, accept="within 8 hours returns HTTP 409")
        run_cli(["refresh", "draft", "--spec", spec, "--draft", "--repo", str(tmp_path)], capsys)
        # agent left the .proposed untouched (identical to the upstream)
        code, out = _apply(tmp_path, spec, "requirements", capsys, actor=None, ack=False)
        assert code == 0 and "identical" in out and "no edit" in out

    def test_missing_draft_errors(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, accept="within 4 hours returns HTTP 409")
        code, out = _apply(tmp_path, spec, "requirements", capsys)
        assert code == 0 and "no draft for stem" in out

    def test_signoff_gate_blocks_without_ack(self, tmp_path, capsys):
        spec = self._drift_and_draft(tmp_path, capsys)
        _write_state(tmp_path, signed=True)                       # requirements phase signed off
        code, out = _apply(tmp_path, spec, "requirements", capsys, ack=False,
                           reviewed=None, actor="kai")
        # no --reviewed yet -> preview; harvest hash then confirm without --ack-signoff
        _, prev = _apply(tmp_path, spec, "requirements", capsys, actor=None, ack=False)
        code, out = _apply(tmp_path, spec, "requirements", capsys, reviewed=_diffhash(prev), ack=False)
        assert code == 0 and "signed-off" in out and "--ack-signoff" in out
        assert "within 4 hours" not in (tmp_path / REQ).read_text()


# --- refresh reject: NOT_AFFECTED on the reverse edge (P5) ------------------------------------

class TestRefreshReject:
    def _spec_citing_br(self, tmp_path):
        _write_upstreams(tmp_path)
        _write(tmp_path / ".sdlc/artifacts/01-requirements/business-rules.md",
               "# Business Rules\n\n## BR-01 Retention\nKeep logs 90 days.\n")
        return _write_spec(tmp_path, accept="within 4 hours; relates to BR-01")

    def test_reject_with_reason_is_off_books(self, tmp_path, capsys):
        spec = self._spec_citing_br(tmp_path)
        code, out = run_cli(["refresh", "reject", "--spec", spec, "business-rules",
                             "--reason", "retention unaffected", "--owner", "jane",
                             "--repo", str(tmp_path)], capsys)
        assert code == 0 and "NOT_AFFECTED" in out and "off the books" in out

    def test_reject_without_reason_still_counts(self, tmp_path, capsys):
        spec = self._spec_citing_br(tmp_path)
        code, out = run_cli(["refresh", "reject", "--spec", spec, "business-rules",
                             "--repo", str(tmp_path)], capsys)
        assert code == 0 and "STILL COUNTS" in out and "--reason" in out

    def test_reject_non_candidate_refused(self, tmp_path, capsys):
        _write_upstreams(tmp_path)                                # spec cites only FR-001
        spec = _write_spec(tmp_path, accept="within 4 hours returns HTTP 409")
        code, out = run_cli(["refresh", "reject", "--spec", spec, "business-rules",
                             "--reason", "x", "--repo", str(tmp_path)], capsys)
        assert code == 0 and "no candidate upstream" in out

    def test_reject_edge_invisible_to_forward_report(self, tmp_path, capsys):
        """R4: the reject records (downstream=upstream-artifact, upstream=spec) — a reverse edge the
        forward lineage graph has no counterpart for, so compute_staleness never renders it."""
        spec = self._spec_citing_br(tmp_path)
        run_cli(["refresh", "reject", "--spec", spec, "business-rules",
                 "--reason", "x", "--repo", str(tmp_path)], capsys)
        code, out = run_cli(["report", "--repo", str(tmp_path), "--json"], capsys)
        data = json.loads(out)
        assert code == 0 and data["stale"] == 0 and data["open"] == 0


# --- refresh status: honest per-spec disposition counting (P5) --------------------------------

class TestRefreshStatus:
    def test_open_when_nothing_done(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, accept="within 4 hours returns HTTP 409")
        code, out = run_cli(["refresh", "status", "--spec", spec, "--repo", str(tmp_path), "--json"], capsys)
        assert code == 0
        counts = json.loads(out)["counts"]
        assert counts["open"] == 1 and counts["refreshed"] == 0

    def test_refreshed_attributed_via_source_spec(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, accept="within 4 hours returns HTTP 409")
        run_cli(["record", "--scan", "--repo", str(tmp_path)], capsys)
        run_cli(["refresh", "draft", "--spec", spec, "--repo", str(tmp_path)], capsys)
        _agent_edits(tmp_path, spec, "requirements",
                     "# Requirements\n\n## FR-001\nwithin 4 hours; HTTP 409.\n")
        _confirm_apply(tmp_path, spec, "requirements", capsys)
        code, out = run_cli(["refresh", "status", "--spec", spec, "--repo", str(tmp_path), "--json"], capsys)
        counts = json.loads(out)["counts"]
        assert code == 0 and counts["refreshed"] == 1 and counts["open"] == 0

    def test_not_affected_without_reason_counts_in_status(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        _write(tmp_path / ".sdlc/artifacts/01-requirements/business-rules.md",
               "# Business Rules\n\n## BR-01\nKeep logs 90 days.\n")
        spec = _write_spec(tmp_path, accept="within 4 hours; relates to BR-01")
        run_cli(["refresh", "reject", "--spec", spec, "business-rules", "--repo", str(tmp_path)], capsys)
        code, out = run_cli(["refresh", "status", "--spec", spec, "--repo", str(tmp_path), "--json"], capsys)
        rows = {r["target"].split("/")[-1]: r for r in json.loads(out)["rows"]}
        assert rows["business-rules.md"]["disposition"] == "NOT_AFFECTED"
        assert rows["business-rules.md"]["off_books"] is False    # no reason -> still counts

    def test_rollup_across_merged_specs(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        _write_spec(tmp_path, sid="0001", accept="within 4 hours returns HTTP 409")
        _write_spec(tmp_path, sid="0002", status="ready", accept="within 4 hours")
        code, out = run_cli(["refresh", "status", "--repo", str(tmp_path), "--json"], capsys)
        data = json.loads(out)
        assert code == 0 and data["merged_specs"] == 1

    def test_no_data(self, tmp_path, capsys):
        _write_upstreams(tmp_path)
        code, out = run_cli(["refresh", "status", "--repo", str(tmp_path)], capsys)
        assert code == 0 and "no merged specs" in out


# --- exit-0 across every version path ---------------------------------------------------------

class TestExitZero:
    @pytest.mark.parametrize("argv", [
        ["version", "list", "requirements.md"],
        ["version", "show", "requirements.md", "v9"],
        ["version", "diff", "requirements.md"],
        ["version", "rollback", "requirements.md", "v9"],
        ["version", "rollback", "requirements.md", "prev", "--confirm", "--actor", "kai"],
        ["version", "gc"],
        ["version", "gc", "--apply"],
        ["refresh", "detect", "--spec", "specs/missing.md"],
        ["refresh", "scan"],
        ["refresh", "draft", "--spec", "specs/missing.md"],
        ["refresh", "apply", "--spec", "specs/missing.md", "requirements"],
        ["refresh", "reject", "--spec", "specs/missing.md", "requirements"],
        ["refresh", "status", "--spec", "specs/missing.md"],
        ["refresh", "status"],
    ])
    def test_never_nonzero(self, tmp_path, capsys, argv):
        _write(tmp_path / REQ, "content\n")
        code, _ = run_cli(argv + ["--repo", str(tmp_path)], capsys)
        assert code == 0


# --- P7: additive-contract / byte-identical invariants ----------------------------------------

class TestInvariants:
    """The plan's non-negotiables, asserted mechanically: artifact_model unchanged (the source_spec
    rider is caller-added), /sprd-audit output byte-identical with/without a version store, the layer
    writes no state.yaml, the ledger stays its own JSONL with no gate_results rows, and the store +
    refresh drafts are gitignored."""

    def test_change_entry_carries_no_source_spec_rider(self):
        """artifact_model.py stays byte-for-byte unchanged: `source_spec` is a key the refresh caller
        rides onto the returned dict, never a field of change_entry itself."""
        e = am.change_entry(ts="2026-01-01T00:00:00+00:00", artifact=REQ, event="refreshed")
        assert "source_spec" not in e

    def test_report_json_byte_identical_without_version_store(self, tmp_path, capsys):
        """`report` (the /sprd-audit-artifacts engine) must never read the object store — deleting the
        whole store leaves its JSON byte-for-byte identical (the store is derived, non-authoritative)."""
        _two_versions(tmp_path, capsys)                                  # ledger + a populated store
        _, with_store = run_cli(["report", "--repo", str(tmp_path), "--json"], capsys)
        store = tmp_path / ".sdlc" / "versions"
        assert any(store.rglob("*"))                                     # the scan captured blobs
        shutil.rmtree(store)
        _, without_store = run_cli(["report", "--repo", str(tmp_path), "--json"], capsys)
        assert with_store == without_store and with_store.strip()

    def test_impact_json_byte_identical_without_version_store(self, tmp_path, capsys):
        _two_versions(tmp_path, capsys)
        _, with_store = run_cli(["impact", "requirements.md", "--repo", str(tmp_path), "--json"], capsys)
        shutil.rmtree(tmp_path / ".sdlc" / "versions")
        _, without_store = run_cli(["impact", "requirements.md", "--repo", str(tmp_path), "--json"], capsys)
        assert with_store == without_store and with_store.strip()

    def test_version_and_refresh_never_write_state_yaml(self, tmp_path, capsys):
        """B3: a refresh apply and a version rollback both mutate the artifact + ledger + store —
        never state.yaml. (Refuse paths leave it untouched too, so this holds regardless of guards.)"""
        _write_upstreams(tmp_path)
        spec = _write_spec(tmp_path, accept="within 4 hours returns HTTP 409")
        _write_state(tmp_path, signed=False)                             # known + unsigned -> no ack gate
        state = str(tmp_path / ".sdlc" / "state.yaml")
        run_cli(["record", "--scan", "--state", state], capsys)          # v1 baseline
        before = (tmp_path / ".sdlc" / "state.yaml").read_bytes()

        # (a) draft + named-human apply (mutates requirements.md up to the spec's reality)
        run_cli(["refresh", "draft", "--spec", spec, "--state", state], capsys)
        _agent_edits(tmp_path, spec, "requirements",
                     "# Requirements\n\n## FR-001 Duplicate claim\n"
                     "Reject a duplicate within 4 hours; return HTTP 409.\n")
        _, prev = run_cli(["refresh", "apply", "--spec", spec, "requirements", "--state", state], capsys)
        run_cli(["refresh", "apply", "--spec", spec, "requirements", "--actor", "kai",
                 "--reviewed", _diffhash(prev), "--state", state], capsys)
        # (b) roll it back (append-only revert of the same file)
        _, prev2 = run_cli(["version", "rollback", "requirements.md", "prev", "--state", state], capsys)
        run_cli(["version", "rollback", "requirements.md", "prev", "--confirm", "--actor", "kai",
                 "--reviewed", _diffhash(prev2), "--state", state], capsys)

        assert (tmp_path / ".sdlc" / "state.yaml").read_bytes() == before

    def test_ledger_stays_its_own_jsonl_with_no_gate_results_rows(self, tmp_path, capsys):
        """The change-ledger is the only *.jsonl the layer writes, and no entry carries a gate_results
        key — so /sprd-audit's gate history can never absorb a phantom row from this layer."""
        _two_versions(tmp_path, capsys)
        dh = _diffhash(run_cli(
            ["version", "rollback", "requirements.md", "v1", "--repo", str(tmp_path)], capsys)[1])
        run_cli(["version", "rollback", "requirements.md", "v1", "--confirm", "--actor", "kai",
                 "--reviewed", dh, "--ack-signoff", "--repo", str(tmp_path)], capsys)
        metrics = tmp_path / ".sdlc" / "metrics"
        assert sorted(p.name for p in metrics.glob("*.jsonl")) == ["artifact-log.jsonl"]
        for line in (metrics / "artifact-log.jsonl").read_text(encoding="utf-8").splitlines():
            assert "gate_results" not in json.loads(line)

    def test_gitignore_ignores_the_store_and_refresh_drafts(self):
        """The locked .gitignore default: object store + transient refresh drafts are local-only."""
        gi = (Path(__file__).resolve().parents[2] / ".gitignore").read_text(encoding="utf-8")
        for needed in (".sdlc/versions/objects/",
                       ".sdlc/refresh/**/*.proposed",
                       ".sdlc/refresh/**/candidates.json",
                       ".sdlc/refresh/_rollback/"):
            assert needed in gi
