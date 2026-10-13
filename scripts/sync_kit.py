#!/usr/bin/env python
"""Regenerate the plugin's harness/ payload from the canonical kit.

The canonical, authored source of the delivery harness is `delivery-standard/kit/`. The plugin
bundles a GENERATED copy under `harness/` so it is self-contained when installed. Run this at
release time (or after any kit change) to keep them in lockstep — do NOT hand-edit `harness/`.

The copy is not byte-for-byte. The kit is written for the upstream `claude-code-sdlc` plugin and
this fork ships as Shepherd, so a fixed RENAMES pass rewrites the brand strings — the slash-command
prefix (`/sdlc-<cmd>` → `/sprd-<cmd>`), the plugin id and the repo URL — in every text file IN
PLACE after the copy, as bytes, so the copied mode (incl. 100755 on the `.sh` hooks) survives and
nothing is decoded or re-encoded. The invariant `--check` enforces is therefore
`harness/ == rename(kit)`: the upstream kit stays untouched and the brand lives in one list here.
What the kit stores rather than shows — `.sdlc/` paths, gate ids, the JSON Schema `$id` under
`profile/` — is never touched; a file containing a NUL byte is copied verbatim.

Usage (from the plugin repo, with delivery-standard as a sibling):
  uv run --project scripts scripts/sync_kit.py
  uv run --project scripts scripts/sync_kit.py --kit ../delivery-standard/kit --check
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_KIT = PLUGIN_ROOT.parent / "delivery-standard" / "kit"
PAYLOAD = PLUGIN_ROOT / "harness"

# Brand strings the kit carries for the upstream plugin, rewritten for this fork. ORDERED: the
# URL and install forms must run before the bare id, or the bare rule would rewrite them first.
# Bytes patterns, so a file is never decoded. `\w` and `\b` are ASCII-only on bytes, which is
# what a slash command needs.
RENAMES: list[tuple[re.Pattern[bytes], bytes]] = [
    # The slash-command prefix only. The lookbehind excludes a path token (`.sdlc/`, `foo/sdlc`),
    # where the slash is preceded by a word character or a dot; `\b` keeps `/sdlc` from matching
    # inside a longer token.
    (re.compile(rb"(?<![\w./~])/sdlc\b"), b"/sprd"),
    (re.compile(rb"MCKRUZ/claude-code-sdlc"), b"MCKRUZ/shepherd-sdlc"),
    (re.compile(rb"claude-code-sdlc@mckruz"), b"shepherd@mckruz"),
    (re.compile(rb"claude-code-sdlc"), b"shepherd"),
]

# Kit-relative POSIX paths the rename pass never touches. The schema's `$id` is an identifier
# other tooling resolves, not a brand string — no pattern above matches it today, and the skip
# keeps that true whatever RENAMES grows into.
RENAME_SKIP = frozenset({"profile/rails-telemetry.schema.json"})


def _all_files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def rename(data: bytes) -> bytes:
    """Apply RENAMES to one file's bytes. Binary content (a NUL byte) is returned unchanged."""
    if b"\x00" in data:
        return data
    for pattern, replacement in RENAMES:
        data = pattern.sub(replacement, data)
    return data


def _expected(kit: Path, rel: str) -> bytes:
    """What harness/<rel> must contain: the kit file, renamed unless it is on the skip list."""
    data = (kit / rel).read_bytes()
    return data if rel in RENAME_SKIP else rename(data)


def check(kit: Path) -> int:
    if not kit.is_dir():
        print(f"ERROR: kit not found: {kit}", file=sys.stderr)
        return 2
    src, dst = _all_files(kit), _all_files(PAYLOAD) if PAYLOAD.exists() else set()
    missing, extra = sorted(src - dst), sorted(dst - src)
    changed = sorted(
        f for f in (src & dst)
        if (PAYLOAD / f).read_bytes() != _expected(kit, f)
    )
    if not (missing or extra or changed):
        print(f"IN SYNC: harness/ matches rename({kit}) ({len(src)} files).")
        return 0
    for f in missing:
        print(f"MISSING  {f}  (in kit, not in harness/)")
    for f in extra:
        print(f"STALE    {f}  (in harness/, not in kit)")
    for f in changed:
        print(f"CHANGED  {f}")
    print(f"\nOUT OF SYNC: run without --check to regenerate.")
    return 1


def sync(kit: Path) -> int:
    if not kit.is_dir():
        print(f"ERROR: kit not found: {kit}", file=sys.stderr)
        return 2
    if PAYLOAD.exists():
        shutil.rmtree(PAYLOAD)
    shutil.copytree(kit, PAYLOAD)
    renamed = 0
    for rel in sorted(_all_files(PAYLOAD)):
        if rel in RENAME_SKIP:
            continue
        path = PAYLOAD / rel
        before = path.read_bytes()
        after = rename(before)
        if after != before:
            path.write_bytes(after)  # in place, so the copied mode survives
            renamed += 1
    n = len(_all_files(PAYLOAD))
    print(f"Synced {n} files: {kit}  ->  {PAYLOAD}  ({renamed} renamed for Shepherd)")
    print("harness/ is GENERATED — do not hand-edit; edit delivery-standard/kit and re-run.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Sync the plugin harness payload from the kit.")
    ap.add_argument("--kit", type=Path, default=DEFAULT_KIT, help="path to delivery-standard/kit")
    ap.add_argument("--check", action="store_true", help="report drift without writing")
    args = ap.parse_args()
    kit = args.kit.resolve()
    return check(kit) if args.check else sync(kit)


if __name__ == "__main__":
    raise SystemExit(main())
