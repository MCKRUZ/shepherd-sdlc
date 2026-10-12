# Releasing the plugin

Releases only happen from a green `master` — CI (`.github/workflows/ci.yml`) runs the same
checks listed here, so a red anywhere means stop.

1. **Sync the payload** from the kit source of truth and verify:
   ```bash
   uv run --project scripts scripts/sync_kit.py --kit <delivery-standard>/kit
   uv run --project scripts scripts/sync_kit.py --kit <delivery-standard>/kit --check
   ```
   `harness/` is `rename(kit)` — `sync_kit.py` rewrites the kit's pre-2.0 `sdlc-*` command names, plugin id and
   repo URL in place (`RENAMES` in `scripts/sync_kit.py`); a brand change goes there, never into
   `harness/`.
2. **Run the suite** — everything, including the golden-repo compose test and the
   payload completeness tripwire:
   ```bash
   uv run --project scripts pytest scripts/tests -q
   ```
   If the kit legitimately changed the installed tree, regenerate the snapshot
   (`GOLDEN_REGEN=1 uv run --project scripts pytest scripts/tests/test_golden_repo.py -q`),
   review the diff, and commit it deliberately.
3. **Bump the version** in `.claude-plugin/plugin.json` AND `.claude-plugin/marketplace.json`
   (they must match). Semver: new capability = minor, fixes only = patch.
4. **Write the CHANGELOG entry** — `CHANGELOG.md`, newest first, factual and short.

   > Steps 3 and 4 are enforced by `scripts/tests/test_release_manifest_agreement.py`: the two
   > manifests must agree on version and name, the version must be semver, and it must be the
   > newest release heading in the CHANGELOG. This exists because 1.1.0 bumped `plugin.json`
   > alone — git then *auto-merged* `marketplace.json` to the previous version with no conflict
   > and no failing test, which would have published a release the marketplace never offered.

5. **Commit** (`feat:`/`fix:`/`chore:` as appropriate), **push**, and wait for CI green.
6. **Tag and push the tag**:
   ```bash
   git tag -a vX.Y.Z -m "X.Y.Z — <one-line summary>"
   git push origin vX.Y.Z
   ```
   Tags exist from `v0.4.0` onward; every release gets one — it is how an engagement can say
   which harness version it runs (see also `.claude/harness-manifest.json` in installed repos,
   which records the version at install time, and `/sprd-upgrade` to move repos forward).
