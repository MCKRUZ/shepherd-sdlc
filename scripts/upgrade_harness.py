#!/usr/bin/env python
"""Upgrade an installed delivery harness against a new plugin payload.

Three-way classification per file: the target's .claude/harness-manifest.json holds the
PRISTINE hash of what the last install composed (oldP), a fresh compose of the new payload
into a temp directory yields the new pristine (newP), and the file on disk is the current
state (cur). Comparing all three separates "the repo adapted this" from "upstream changed
this" — updates apply cleanly where the repo never touched the file, adaptations are kept,
and genuine two-sided divergence becomes a CONFLICT sibling (<file>.harness-new) for a human
to merge; the upgrade never overwrites local work.

Default is a DRY-RUN report; --apply performs the changes and refreshes the manifest.
--json prints the dry-run report as one JSON document instead; it never applies, so combining
it with --apply is refused (exit 2). Applying rewrites CI workflows and hooks a person must
review, which a machine-readable mode has no business doing.
Pass the SAME --profile the harness was installed with, or pack-composed files will look
retired. A target without a manifest is a LEGACY install: everything is classified as
untracked, and --apply adopts the pristine-matching files into a fresh manifest.

Exit codes: 0 on success (conflicts included — reporting them is the job), 2 on
InstallError-class problems (bad payload/profile/manifest), never a raw traceback.

Usage:
  uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/upgrade_harness.py \
    --payload ${CLAUDE_PLUGIN_ROOT}/harness --target . [--profile <profile.yaml>] [--apply]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
from harness_manifest import (  # noqa: E402
    MANIFEST_REL,
    build_manifest,
    file_digest,
    load_manifest,
    write_manifest,
)
from install_harness import InstallError, _install  # noqa: E402

# Classification names, in report order. See _classify for the decision table.
IDENTICAL = "IDENTICAL"
UPDATE = "UPDATE"
ADAPTED = "ADAPTED"
CONFLICT = "CONFLICT"
DELETED_LOCALLY = "DELETED-LOCALLY"
NEW = "NEW"
ADOPT = "ADOPT"
CONFLICT_UNTRACKED = "CONFLICT-UNTRACKED"
RETIRED = "RETIRED"
CLASS_ORDER = [IDENTICAL, UPDATE, ADAPTED, CONFLICT, DELETED_LOCALLY, NEW, ADOPT,
               CONFLICT_UNTRACKED, RETIRED]

CLASS_NOTES = {
    IDENTICAL: "current file matches the new pristine; --apply refreshes the manifest entry",
    UPDATE: "untouched locally, changed upstream; --apply replaces the file",
    ADAPTED: "adapted locally, unchanged upstream; kept as-is",
    CONFLICT: "changed on BOTH sides; --apply writes <file>.harness-new to merge by hand",
    DELETED_LOCALLY: "deleted in the repo; the deletion is respected (never reinstalled)",
    NEW: "new upstream file; --apply installs it",
    ADOPT: "untracked but matches the new pristine; --apply starts tracking it",
    CONFLICT_UNTRACKED: "untracked and diverged; --apply writes <file>.harness-new",
    RETIRED: "dropped upstream; --apply untracks it, deleting the file is the human's call",
}


def _classify(old: str | None, new: str | None, cur: str | None) -> str:
    """One file's classification from (manifest oldP, new pristine newP, current cur)."""
    if old is not None:
        if cur is None:
            return DELETED_LOCALLY
        if new is None:
            return RETIRED
        if cur == new:
            return IDENTICAL
        if cur == old:
            return UPDATE          # cur==old and cur!=new implies new!=old
        if new == old:
            return ADAPTED
        return CONFLICT
    if cur is None:
        return NEW
    if cur == new:
        return ADOPT
    return CONFLICT_UNTRACKED


def _classify_all(old_files: dict[str, str], new_files: dict[str, str],
                  target: Path) -> dict[str, list[str]]:
    """Classify the union of manifest + new-pristine paths, grouped by classification."""
    groups: dict[str, list[str]] = {name: [] for name in CLASS_ORDER}
    for rel in sorted(set(old_files) | set(new_files)):
        if rel == MANIFEST_REL:  # the manifest never classifies itself
            continue
        cur_path = target / rel
        cur = file_digest(cur_path) if cur_path.is_file() else None
        groups[_classify(old_files.get(rel), new_files.get(rel), cur)].append(rel)
    return groups


def _compose_pristine(payload: Path, profile_path: Path | None, tmp: Path) -> dict:
    """Compose the new pristine tree into tmp (the installer's own compose, force semantics,
    silent) and return the manifest it wrote — the new-pristine hash map plus provenance."""
    _install(payload, tmp, force=True, profile_path=profile_path, log=[], quiet=True)
    pristine = load_manifest(tmp)
    if pristine is None:
        raise InstallError("pristine compose produced no manifest (installer bug)")
    return pristine


def _install_pristine(tmp: Path, target: Path, rel: str, suffix: str = "") -> None:
    dest = target / (rel + suffix)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tmp / rel, dest)


def _apply_changes(groups: dict[str, list[str]], tmp: Path, target: Path,
                   old_files: dict[str, str],
                   new_files: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Perform each classification's file effect and return (updated files map, change lines).
    CONFLICT/CONFLICT-UNTRACKED never touch the current file or its manifest entry — the
    .harness-new sibling carries the new pristine content until a human merges it."""
    files = dict(old_files)
    changes: list[str] = []
    for rel in groups[IDENTICAL]:
        files[rel] = new_files[rel]
    for rel in groups[ADOPT]:
        files[rel] = new_files[rel]
        changes.append(f"ADOPT    {rel}  (now tracked)")
    for rel in groups[UPDATE]:
        _install_pristine(tmp, target, rel)
        files[rel] = new_files[rel]
        changes.append(f"UPDATE   {rel}")
    for rel in groups[NEW]:
        _install_pristine(tmp, target, rel)
        files[rel] = new_files[rel]
        changes.append(f"NEW      {rel}")
    for rel in groups[CONFLICT] + groups[CONFLICT_UNTRACKED]:
        _install_pristine(tmp, target, rel, suffix=".harness-new")
        changes.append(f"CONFLICT {rel}  -> wrote {rel}.harness-new")
    for rel in groups[RETIRED]:
        files.pop(rel, None)
        changes.append(f"RETIRED  {rel}  (untracked; file left in place)")
    return files, changes


def _print_report(groups: dict[str, list[str]], target: Path, legacy: bool, apply: bool,
                  new_version: str, old_version: str | None) -> None:
    mode = "APPLY" if apply else "DRY RUN (no changes made; re-run with --apply)"
    versions = f"payload plugin version: {new_version}"
    if old_version:
        versions += f"  (installed: {old_version})"
    print(f"Harness upgrade: {mode}\ntarget: {target}\n{versions}")
    if legacy:
        print("\n" + "!" * 74)
        print("! LEGACY INSTALL: no .claude/harness-manifest.json in the target; adopting.")
        print("! Every path is classified as untracked; files matching the new pristine are")
        print("! ADOPTed, and --apply writes a fresh manifest from the ADOPT/NEW outcomes.")
        print("!" * 74)
    for name in CLASS_ORDER:
        rels = groups[name]
        if not rels:
            continue
        print(f"\n{name} ({len(rels)}) - {CLASS_NOTES[name]}")
        for rel in rels:
            print(f"  {rel}")
    counts = ", ".join(f"{len(groups[n])} {n}" for n in CLASS_ORDER if groups[n])
    print(f"\nTotals: {sum(len(v) for v in groups.values())} path(s): {counts}")
    _print_next_actions(groups)


def _print_next_actions(groups: dict[str, list[str]]) -> None:
    print("\nNEXT ACTIONS:")
    print("  - Merge each <file>.harness-new into its file by hand, then DELETE the "
          ".harness-new sibling.")
    print("  - CLAUDE.md carries the SDLC section /sprd-setup appended, so it typically "
          "reports ADAPTED or")
    print("    CONFLICT: merge its stack-standards section deliberately; never wholesale-"
          "replace the file.")
    if groups[RETIRED]:
        print("  - RETIRED files stay on disk; delete them yourself once nothing references "
              "them.")


def _print_json(groups: dict[str, list[str]], legacy: bool, new_version: str,
                old_version: str | None) -> None:
    """The dry-run report as data, in the script's own classification labels and order.
    `counts` lists only the labels that occur, as the text report's Totals line does."""
    print(json.dumps({
        "mode": "dry-run",
        "legacy": legacy,
        "payload_version": new_version,
        "installed_version": old_version,
        "files": [{"path": rel, "classification": name, "detail": CLASS_NOTES[name]}
                  for name in CLASS_ORDER for rel in groups[name]],
        "counts": {name: len(groups[name]) for name in CLASS_ORDER if groups[name]},
    }, indent=2))


def upgrade(payload: Path, target: Path, profile_path: Path | None = None,
            apply: bool = False, as_json: bool = False) -> int:
    """Run the upgrade. Every InstallError-class problem lands as a clean 'ERROR: ...' + rc 2.
    With as_json the same problem is also the one document on stdout, as {"error": ...}."""
    try:
        return _upgrade(payload, target, profile_path, apply, as_json)
    except InstallError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if as_json:
            print(json.dumps({"error": str(exc)}, indent=2))
        return 2


def _upgrade(payload: Path, target: Path, profile_path: Path | None, apply: bool,
             as_json: bool = False) -> int:
    if not target.is_dir():
        raise InstallError(f"target not found: {target}")
    try:
        manifest = load_manifest(target)
    except ValueError as exc:
        raise InstallError(str(exc)) from exc
    legacy = manifest is None
    old_files: dict[str, str] = manifest["files"] if manifest else {}

    with tempfile.TemporaryDirectory(prefix="harness-pristine-") as td:
        tmp = Path(td)
        pristine = _compose_pristine(payload, profile_path, tmp)
        groups = _classify_all(old_files, pristine["files"], target)
        changes: list[str] = []
        if apply:
            files, changes = _apply_changes(groups, tmp, target, old_files, pristine["files"])
            write_manifest(target, build_manifest(payload, pristine["profile_id"],
                                                  pristine["packs"], files))

    old_version = manifest.get("plugin_version") if manifest else None
    if as_json:
        _print_json(groups, legacy, pristine["plugin_version"], old_version)
        return 0
    _print_report(groups, target, legacy, apply, pristine["plugin_version"], old_version)
    if apply:
        print("\nAPPLIED:")
        for line in changes or ["  (manifest refreshed; no file changes)"]:
            print(line if line.startswith("  ") else f"  {line}")
        print(f"  MANIFEST {MANIFEST_REL} refreshed")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Upgrade an installed harness against a new payload.")
    ap.add_argument("--payload", required=True, type=Path, help="plugin harness/ directory")
    ap.add_argument("--target", default=Path("."), type=Path, help="target repo root")
    ap.add_argument("--profile", type=Path, default=None,
                    help="the SAME profile.yaml the harness was installed with (optional)")
    ap.add_argument("--apply", action="store_true",
                    help="perform the changes (default: dry-run report only)")
    ap.add_argument("--json", action="store_true",
                    help="print the dry-run report as one JSON document (never combined with "
                         "--apply)")
    args = ap.parse_args()
    if args.json and args.apply:
        ap.error("--json is dry-run only and cannot be combined with --apply")
    profile = args.profile.resolve() if args.profile else None
    return upgrade(args.payload.resolve(), args.target.resolve(), profile, args.apply, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
