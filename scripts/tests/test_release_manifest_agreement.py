"""The version lives in three files, and a bump that misses one fails silently.

`RELEASING.md` step 3 already says to bump `.claude-plugin/plugin.json` **and**
`.claude-plugin/marketplace.json`, "they must match", and step 4 says to write the CHANGELOG
entry. Nothing enforced any of it, and the 1.1.0 release proved why that matters: the branch
bumped `plugin.json` and never touched `marketplace.json`, so when it was merged after the 1.0.1
stack, git **auto-merged** the marketplace file to 1.0.1. No conflict, no marker, no failing test —
a valid JSON file holding the wrong number.

The two versions are read by different consumers, which is what makes the mismatch expensive:

* `plugin.json` is what `scripts/harness_manifest.py` stamps into every installed repo's
  `.claude/harness-manifest.json`, so it is the version an engagement reports it runs and the one
  `/sprd-upgrade` compares against.
* `marketplace.json` is what Claude Code reads to decide whether an update exists.

When the marketplace lags, the release is published and no one is offered it. The installed repos
that do upgrade then report a version the marketplace says was never released.

This is the guard the release procedure was relying on a human to be.
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = REPO_ROOT / ".claude-plugin" / "marketplace.json"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def plugin_manifest() -> dict:
    return json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))


def marketplace_entry() -> dict:
    """This repo's own entry in the marketplace listing.

    The listing can carry several plugins; the one this repo releases is the entry whose `source`
    is the repo root. Matching on `source` rather than position means adding a second plugin to
    the listing cannot silently redirect this check at someone else's entry.
    """
    listing = json.loads(MARKETPLACE_JSON.read_text(encoding="utf-8"))
    own = [p for p in listing["plugins"] if p.get("source") == "."]
    assert len(own) == 1, (
        f"expected exactly one marketplace entry with source '.', found {len(own)} — "
        "this check no longer knows which entry describes this repo"
    )
    return own[0]


def released_versions_in_changelog() -> list[str]:
    """Release headings, newest first. `## Migration — ...` and friends are not releases."""
    return re.findall(r"^## (\d+\.\d+\.\d+)\b", CHANGELOG.read_text(encoding="utf-8"), re.M)


@pytest.mark.parametrize("path", [PLUGIN_JSON, MARKETPLACE_JSON, CHANGELOG])
def test_sources_exist(path: Path):
    """Guard the guard: a moved file must fail loudly, not make every check below vacuous."""
    assert path.exists(), f"{path.relative_to(REPO_ROOT)} is missing"


def test_both_manifests_ship_the_same_version():
    """RELEASING.md step 3: bump both, "they must match"."""
    plugin_version = plugin_manifest()["version"]
    marketplace_version = marketplace_entry()["version"]

    assert plugin_version == marketplace_version, (
        f"plugin.json says {plugin_version} and marketplace.json says {marketplace_version}. "
        "Installed repos record the plugin.json version; the marketplace offers the other one, so "
        "whichever is lower is a release nobody is told about. Bump both (RELEASING.md step 3)."
    )


def test_both_manifests_name_the_same_plugin():
    """A rename that lands in one file points the marketplace at a plugin that does not exist."""
    plugin_name = plugin_manifest()["name"]
    marketplace_name = marketplace_entry()["name"]

    assert plugin_name == marketplace_name, (
        f"plugin.json is named '{plugin_name}' but the marketplace lists '{marketplace_name}' — "
        "the marketplace would advertise a plugin under a name nothing installs as"
    )


def test_the_shipped_version_is_semver():
    version = plugin_manifest()["version"]
    assert SEMVER.match(version), (
        f"'{version}' is not MAJOR.MINOR.PATCH — `/sprd-upgrade` compares versions to decide "
        "whether an installed repo is behind, and cannot order a version it cannot parse"
    )


def test_the_changelog_documents_the_shipped_version():
    """RELEASING.md step 4. A version with no entry ships changes nobody can read about."""
    version = plugin_manifest()["version"]
    released = released_versions_in_changelog()
    assert released, "no `## X.Y.Z` headings parsed from CHANGELOG.md — the format changed"

    assert version in released, (
        f"the manifests ship {version} but CHANGELOG.md has no `## {version}` section "
        f"(newest documented: {released[0]}). Either the bump or the entry was forgotten."
    )


def test_the_shipped_version_is_the_newest_in_the_changelog():
    """Ordering catches the other half: an entry written for a version never bumped to.

    The 1.1.0 merge landed its section *above* 1.0.1 while the marketplace still said 1.0.1 — the
    changelog and the manifests disagreed about which release was current, and each looked
    internally consistent.
    """
    version = plugin_manifest()["version"]
    newest = released_versions_in_changelog()[0]

    assert version == newest, (
        f"CHANGELOG.md's newest release is {newest} but the manifests ship {version}. Newest-first "
        "is the convention, so this is either an unreleased entry or an un-entered release."
    )
