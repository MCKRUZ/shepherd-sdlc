#!/usr/bin/env python
"""Install the delivery harness (the kit) from the plugin's bundled payload into a target repo.

Called by /sprd-setup after .sdlc/ is initialized. Idempotent: existing files are left in place
and reported as SKIPPED unless --force is given. The payload is the plugin's `harness/` directory,
a generated copy of delivery-standard/kit (see scripts/sync_kit.py).

Two modes:
  * core-only (no --profile): copy the neutral kit — CLAUDE.md full of {{TOKENS}}, placeholder
    workflows. The base case a repo adapts by hand.
  * profile-aware (--profile <profile.yaml>): compose core + the stack pack + the CI/CD pack + any
    tools packs the profile selects. The packs' realized files OVERLAY the core placeholders (last
    wins), the .NET tooling permissions are MERGED into settings.json, pack MCP fragments are MERGED
    into the repo's .mcp.json (core ships context7 / sequential-thinking / playwright; the stack and
    CI/CD packs add their own, e.g. microsoft-learn, azure-devops), and the stack pack's standards
    are spliced into CLAUDE.md's "## Stack standards — {{STACK}}" section. Tools packs (the third axis,
    multi-select via a top-level `tools: [id, ...]`) integrate optional, often self-installing tools:
    they overlay only a small static surface (config + a SETUP guide) and the installer PRINTS their
    manual setup steps — it never runs them. Selection is driven entirely by the profile's own stack
    block (language -> stack pack, ci_cd.platform -> CI/CD pack) plus the `tools` list; the mapping
    lives in one place (the resolver tables below). The two axes degrade independently: a valid stack
    or platform with no pack built yet installs the neutral core for that axis and prints a WARNING
    (setup never fails just because a pack is missing), while an incompatible pair or a pack that is
    mapped but absent from the payload still fails closed (real breakage, not "not built yet").

  When BOTH a stack pack and a CI/CD pack compose, the seam between them is filled MECHANICALLY:
  the stack's ci-profile.yaml (toolchain + commands + coverage floor) is joined with the CI/CD
  pack's toolchain_map (its platform's setup action/task per toolchain id) into a <<CI_*>> token
  table, and every file the CI/CD pack overlays is substituted AS IT IS COPIED (see ci_tokens.py).
  A <<CI_*>> token surviving that substitution fails the install closed — a literal token is never
  written. When the stack axis DEGRADED (no stack pack) but a CI/CD pack composed, the tokens are
  deliberately LEFT in place and reported as a WARNING: the axes still degrade independently.

  This does NOT fill per-repo tokens ({{SOLUTION_OR_PROJECT}}, <<GATED_PATHS>>, <<EVAL_TEST_PROJECT>>,
  deploy wiring, reviewer models): those are genuinely repo-level Phase-3 adaptation, not something a
  profile knows, and they pass through substitution untouched. The profile drives which packs compose
  and what the seam resolves to, not repo-specific values.

Fail-closed: a FILE_MAP/DIR_MAP/EXTRA_FILES source missing from the payload, or a pack.yaml
overlay src missing from its pack, still logs a MISS line for EVERY missing item (the scan
completes; it never stops at the first), then the run exits 2 — a partial install never exits 0.
Files the maps deliberately leave unmapped are simply not installed; that is not a MISS.

Every successful run ends by writing .claude/harness-manifest.json in the target: the composed
PRISTINE state (sha256 of the final on-disk content) of every dest the run touched, plus the
plugin version, profile id, and composed pack ids. upgrade_harness.py reads it to three-way
classify local adaptation vs. upstream change. SKIPPED files are never recorded; on re-runs,
entries for untouched dests are preserved. See harness_manifest.py for the schema.

Usage:
  uv run --project ${CLAUDE_PLUGIN_ROOT}/scripts ${CLAUDE_PLUGIN_ROOT}/scripts/install_harness.py \
    --payload ${CLAUDE_PLUGIN_ROOT}/harness --target . [--profile <profile.yaml>] [--force]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

# Reuse the tested profile loader/validator rather than reinventing it.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
import ci_tokens  # noqa: E402
from harness_manifest import (  # noqa: E402
    MANIFEST_REL,
    build_manifest,
    file_digest,
    load_manifest,
    write_manifest,
)
from validate_profile import SCHEMA_PATH, load_yaml, validate_profile  # noqa: E402

# (source-relative-to-payload, dest-relative-to-repo). Directories end with "/".
# Mirrors kit/README.md "Install map (authoritative)".
FILE_MAP: list[tuple[str, str]] = [
    ("CLAUDE.md.template", "CLAUDE.md"),            # governance base; SDLC section appended by setup
    ("spec-template.md", "specs/spec-template.md"),
    ("spike-template.md", "spikes/spike-template.md"),  # bounded-discovery findings (Build loop §3a)
    # The closing-phase skeletons. Unlike specs and spikes these are SINGLE-INSTANCE documents —
    # one rollback procedure, one alert set, one playbook per repo — so they land at their final
    # name to be filled in, the way CLAUDE.md.template does, rather than as templates to copy.
    ("rollback-template.md", "ROLLBACK.md"),            # Phase 8: the written "roll back if X"
    ("alert-definitions-template.md", "ALERTS.md"),     # Phase 9: baselines, thresholds, who is woken
    ("incident-playbook-template.md", "INCIDENT-PLAYBOOK.md"),  # Phase 9: detect/diagnose/escalate
    ("settings.json", ".claude/settings.json"),
    ("mcp.json", ".mcp.json"),                      # team MCP servers; packs merge their fragments in
    ("HARNESS.md", "docs/harness.md"),              # the developer-facing tour of what's installed
    ("ONBOARDING.md", "ONBOARDING.md"),             # day-1 checklist; repo root, where a new dev looks
]
DIR_MAP: list[tuple[str, str]] = [
    ("hooks/", ".claude/hooks/"),
    ("agents/", ".claude/agents/"),
    ("skills/", ".claude/skills/"),
    ("workflows/", ".github/workflows/"),           # RAILS.md/README.md ride along; harmless
    ("profile/rubrics/", ".github/profile/rubrics/"),
    ("profile/rulesets/", ".github/rulesets/"),
    ("profile/scripts/", "scripts/rails/"),
    ("eval-datasets/", "eval-datasets/"),
    ("prompts/", "prompts/"),
    ("infra/", "infra/"),
]
# Single files that live at a repo path different from their payload dir.
EXTRA_FILES: list[tuple[str, str]] = [
    ("workflows/RAILS.md", ".github/RAILS.md"),
    ("profile/eval-bypasses.md", ".github/eval-bypasses.md"),
    ("profile/dependency-exceptions.md", ".github/dependency-exceptions.md"),   # dependency-gate ledger
    ("profile/rails-telemetry.schema.json", ".github/rails-telemetry.schema.json"),  # the report's shape
    ("profile/CODEOWNERS", ".github/CODEOWNERS"),
]
GITIGNORE_LINES = [".claude/.review-receipts/", ".claude/settings.local.json"]

# The core kit's governance assets are laid out GitHub-flavored by default (workflows under
# .github/workflows/, rubrics under .github/profile/rubrics/, a CODEOWNERS, a ruleset). For a
# non-GitHub CI/CD platform that layout is remapped by source-relative path:
#   * drop_dirs / drop_files — pure-GitHub MECHANISMS the platform's own CI/CD pack replaces, so
#     dropping them leaves no dead GitHub artifacts in the repo.
#   * redirect — neutral, platform-agnostic governance CONTENT that the platform's pipelines read
#     from a different home (e.g. the azure-devops pack's pipelines reference .azuredevops/rails/).
# Anything unlisted installs at its default, neutral path. github-actions and core-only installs
# (platform None) are ABSENT here on purpose: they fall through to the identity layout, so those
# installs stay byte-for-byte identical to before this seam existed (the additive guarantee).
_CORE_LAYOUT_BY_PLATFORM: dict[str, dict] = {
    "azure-devops": {
        # Each GitHub mechanism has an ADO analogue shipped by packs/cicd/azure-devops:
        #   workflows/            -> .azuredevops/pipelines/ (the pipeline YAMLs)
        #   profile/rulesets/     -> .azuredevops/rails/branch-policies.json
        #   profile/CODEOWNERS    -> required-reviewer branch policy (policies.json)
        #   apply-branch-protection.sh -> scripts/rails/configure-branch-policies.sh
        "drop_dirs": {"workflows/", "profile/rulesets/"},
        "drop_files": {"profile/CODEOWNERS", "profile/scripts/apply-branch-protection.sh"},
        # Neutral content the ADO pipelines read from the rails home (see the azure-devops pack's
        # `governance_rubrics` + the .azuredevops/rails/ path references in its pipeline YAMLs).
        # rails-telemetry.schema.json is deliberately NOT redirected: BOTH packs' telemetry
        # pipelines commit their report to .github/rails-telemetry.json ON PURPOSE — "one
        # collector reads a mixed GitHub/Azure fleet without caring which platform wrote a
        # file" (azure-pipelines/rails-telemetry.yml header). The operator-side fleet collector
        # is external to this repo, so its one-canonical-path contract cannot be updated from
        # here; the schema stays beside the report it describes. Moving either means moving
        # both AND the collector.
        "redirect": {
            "profile/rubrics/":                 ".azuredevops/rails/rubrics/",
            "profile/eval-bypasses.md":         ".azuredevops/rails/eval-bypasses.md",
            "profile/dependency-exceptions.md": ".azuredevops/rails/dependency-exceptions.md",
        },
    },
}

# Profile -> pack resolution. The profile's own stack block is the single source of truth; these
# tables are the ONE place profile vocabulary maps to pack ids. A language/platform with no entry
# fails closed (there is no pack for it yet) — never a silent core-only install.
STACK_PACK_BY_LANGUAGE = {
    "csharp": "dotnet",
    "typescript": "node-typescript",   # backend TS/Node; a TS *frontend* is the frontend axis
    "python": "python",
}
CICD_PACK_BY_PLATFORM = {
    "github-actions": "github",
    "azure-devops": "azure-devops",
}
# Frontend axis (packs/frontend/<id>): whenever the profile declares stack.frontend, the
# framework-agnostic 'generic' pack composes first, then a framework pack ON TOP (last wins).
# stack.frontend.framework is normalized (lowercased, separators collapsed, trailing version
# noise stripped — "React 18" / "react-18" / "react@18.2" all become "react") and looked up in
# FRONTEND_FRAMEWORK_ALIASES. An alias mapping to None is a framework we RECOGNIZE but have no
# web pack for (react-native is native, preact is not React) — it degrades to generic with a
# warning instead of ever fuzzy-matching a web pack. An unlisted framework degrades the same way.
FRONTEND_FRAMEWORK_ALIASES: dict[str, str | None] = {
    "react": "react",
    "reactjs": "react",
    "react.js": "react",
    "react-native": None,   # native UI, never the React WEB pack
    "preact": None,         # react-adjacent, but not React
    "angular": "angular",
    "angularjs": None,      # AngularJS 1.x is a different framework, not Angular 2+
}
FRONTEND_PACK_BY_FRAMEWORK = {
    "react": "react",
    "angular": "angular",
}

# The section heading in CLAUDE.md the stack pack replaces. Everything from this line to the next
# '## ' heading (or EOF) is swapped for the pack's realized standards — but only while the {{STACK}}
# marker survives (i.e. the section is still the untouched template; a repo's Phase-3 adaptation is
# never clobbered). Content around the section — e.g. the SDLC section setup appends — is preserved.
CLAUDE_STACK_HEADING = "## Stack standards"
CLAUDE_STACK_MARKER = "{{STACK}}"


class InstallError(Exception):
    """A fail-closed install problem (bad profile, unresolved/incompatible pack)."""


def _ensure_executable(dest: Path) -> None:
    """Give installed shell scripts the executable bit.

    copy2 preserves the source's mode, which sounds like enough and is not: every .sh in this
    repo and in delivery-standard is committed 0644, because git on Windows does not track the
    bit. Installed non-executable, the hooks and rails scripts die with 'Permission denied' —
    and since the gates are fail-closed, that surfaces as a blocked merge with a confusing
    reason, or as a checking ladder that is quietly not running at all.

    So the installer sets the bit rather than inheriting it. Deciding by suffix keeps it to the
    files that are actually executed; marking docs +x would be noise hiding the signal.
    """
    if dest.suffix != ".sh":
        return
    mode = dest.stat().st_mode
    dest.chmod(mode | 0o111)   # +x wherever the file is already readable


def _copy(src: Path, dest: Path, force: bool, written: set[Path], log: list[str],
          tokens: dict[str, str] | None = None) -> bool:
    """Copy src->dest, filling the <<CI_*>> seam tokens en route when a table is given. A dest
    written earlier THIS run (a core placeholder a pack overlays) is overwritten; a dest that
    pre-existed the run (a repo's own file) is preserved unless --force. Returns True iff the
    file was actually written (so the caller can audit only what it wrote)."""
    rel = str(dest)
    composed_this_run = dest in written
    existed = dest.exists()
    if existed and not force and not composed_this_run:
        log.append(f"SKIP    {rel}  (exists)")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)   # first, so mode bits survive where the source has them
    if tokens:
        _substitute_in_place(dest, tokens)
    _ensure_executable(dest)
    written.add(dest)
    if composed_this_run:
        log.append(f"OVERLAY {rel}")
    else:
        log.append(f"{'FORCE ' if existed else 'WRITE '}  {rel}")
    return True


def _substitute_in_place(dest: Path, tokens: dict[str, str]) -> None:
    """Rewrite a just-copied file with the seam tokens filled. Rewrites only on a real change, so
    a pack file with no tokens keeps copy2's byte-identical content and timestamp."""
    text = dest.read_text(encoding="utf-8")
    filled = ci_tokens.substitute(text, tokens)
    if filled != text:
        dest.write_text(filled, encoding="utf-8")


def _copy_core(payload: Path, target: Path, force: bool, written: set[Path], log: list[str],
               missing: list[str], platform: str | None = None) -> None:
    """Copy the core maps. A mapped source absent from the payload is logged AND collected in
    `missing` — the scan keeps going so every miss is reported, then the caller fails closed.

    `platform` (the profile's stack.ci_cd.platform) selects the on-disk layout via
    _CORE_LAYOUT_BY_PLATFORM: github-actions and core-only (None) use the identity layout, so those
    installs are byte-for-byte unchanged; a non-GitHub platform drops the pure-GitHub mechanisms and
    redirects neutral governance content to that platform's rails home."""
    layout = _CORE_LAYOUT_BY_PLATFORM.get(platform or "", {})
    drop_dirs = layout.get("drop_dirs", frozenset())
    drop_files = layout.get("drop_files", frozenset())
    redirect = layout.get("redirect", {})
    # RAILS.md reaches .github/RAILS.md via EXTRA_FILES, so the workflows/ dir scan must not ALSO
    # copy it; fold that long-standing skip in with any platform-dropped in-directory files.
    dir_skip = {"workflows/RAILS.md"} | set(drop_files)

    for src_rel, dest_rel in FILE_MAP + EXTRA_FILES:
        if src_rel in drop_files:
            log.append(f"OMIT    {src_rel}  (not used on {platform})")
            continue
        src = payload / src_rel
        if not src.is_file():
            log.append(f"MISS    {src_rel}  (not in payload)")
            missing.append(f"{src_rel} (not in payload)")
            continue
        _copy(src, target / redirect.get(src_rel, dest_rel), force, written, log)

    for src_rel, dest_rel in DIR_MAP:
        if src_rel in drop_dirs:
            log.append(f"OMIT    {src_rel}  (not used on {platform})")
            continue
        src_dir = payload / src_rel
        if not src_dir.is_dir():
            log.append(f"MISS    {src_rel}  (not in payload)")
            missing.append(f"{src_rel} (not in payload)")
            continue
        dest_rel = redirect.get(src_rel, dest_rel)
        for src in sorted(p for p in src_dir.rglob("*") if p.is_file()):
            key = src.relative_to(payload).as_posix()
            if key in dir_skip:
                continue
            dest = target / dest_rel / src.relative_to(src_dir)
            _copy(src, dest, force, written, log)


# ── Profile-aware composition ──────────────────────────────────────────────────

def _load_profile(profile_path: Path) -> dict:
    if not profile_path.is_file():
        raise InstallError(f"profile not found: {profile_path}")
    profile = load_yaml(profile_path)
    if not isinstance(profile, dict):
        raise InstallError(f"profile is not a YAML mapping: {profile_path}")
    schema = load_yaml(SCHEMA_PATH)
    errors = validate_profile(profile, schema)
    if errors:
        joined = "\n".join(f"  - {e}" for e in errors)
        raise InstallError(f"profile failed validation ({len(errors)} error(s)):\n{joined}")
    return profile


def _resolve_pack(axis: str, pack_id: str, payload: Path) -> tuple[Path, dict]:
    pack_dir = payload / "packs" / axis / pack_id
    manifest_path = pack_dir / "pack.yaml"
    if not manifest_path.is_file():
        raise InstallError(
            f"{axis} pack '{pack_id}' not found at {pack_dir} "
            f"(is the payload synced with packs/? run sync_kit.py)"
        )
    manifest = load_yaml(manifest_path)
    if not isinstance(manifest, dict) or "overlays" not in manifest:
        raise InstallError(f"{axis} pack '{pack_id}' manifest is missing an 'overlays' map")
    return pack_dir, manifest


def _resolve_packs(profile: dict, payload: Path):
    """Resolve the stack + CI/CD packs the profile selects. The two axes degrade INDEPENDENTLY: a
    valid-but-unmapped stack or platform (no pack built for it yet) yields None on that axis plus a
    warning — never a hard failure, so /sprd-setup can never break just because a pack doesn't exist.
    A pack that IS mapped but missing from the payload, or an incompatible pair, still fails closed:
    those are real breakage (a stale sync, a misconfigured profile), not "not built yet".

    Returns (stack_pack | None, cicd_pack | None, warnings) where each pack is a (dir, manifest) tuple.
    """
    stack = profile.get("stack", {}) or {}
    language = (stack.get("backend", {}) or {}).get("language")
    platform = (stack.get("ci_cd", {}) or {}).get("platform")
    warnings: list[str] = []

    stack_pack = None
    if language in STACK_PACK_BY_LANGUAGE:
        stack_pack = _resolve_pack("stacks", STACK_PACK_BY_LANGUAGE[language], payload)
    else:
        warnings.append(
            f"no stack pack for backend language {language!r}; installed neutral core, adapt the "
            f"stack standards in CLAUDE.md by hand (supported: {sorted(STACK_PACK_BY_LANGUAGE)})"
        )

    cicd_pack = None
    if platform in CICD_PACK_BY_PLATFORM:
        cicd_pack = _resolve_pack("cicd", CICD_PACK_BY_PLATFORM[platform], payload)
    else:
        warnings.append(
            f"no CI/CD pack for ci_cd.platform {platform!r}; no pipeline workflows installed, "
            f"wire CI by hand (supported: {sorted(CICD_PACK_BY_PLATFORM)})"
        )

    # Cross-check the pair only when both axes resolved — each manifest's own compatibility list.
    if stack_pack and cicd_pack:
        stack_id = STACK_PACK_BY_LANGUAGE[language]
        cicd_id = CICD_PACK_BY_PLATFORM[platform]
        allowed_cicd = stack_pack[1].get("requires_cicd_pack", [])
        allowed_stack = cicd_pack[1].get("requires_stack_pack", [])
        if allowed_cicd and cicd_id not in allowed_cicd:
            raise InstallError(
                f"stack pack '{stack_id}' does not support CI/CD pack '{cicd_id}' "
                f"(requires_cicd_pack: {allowed_cicd})"
            )
        if allowed_stack and stack_id not in allowed_stack:
            raise InstallError(
                f"CI/CD pack '{cicd_id}' does not support stack pack '{stack_id}' "
                f"(requires_stack_pack: {allowed_stack})"
            )
    return stack_pack, cicd_pack, warnings


def _normalize_framework(raw) -> str | None:
    """Normalize stack.frontend.framework for the alias lookup: lowercase, collapse runs of
    whitespace/underscores to hyphens, strip trailing version noise ("React 18" / "react-18" /
    "react@18.2" -> "react"). Alphabetic qualifiers survive ("react-native" stays itself)."""
    name = re.sub(r"[\s_]+", "-", str(raw).strip().lower())
    name = re.sub(r"[-.@]*v?\d[\d.]*$", "", name)
    return name.rstrip("-.@") or None


def _resolve_frontend(profile: dict, payload: Path):
    """Resolve the frontend axis. If the profile declares a frontend (stack.frontend present),
    the 'generic' pack (framework-agnostic UX reviewer) composes first; a framework pack —
    matched via FRONTEND_FRAMEWORK_ALIASES on the normalized framework name, never by prefix —
    composes on top and overlays what it specializes (last wins). A recognized-but-unsupported
    framework (alias -> None, e.g. react-native) or an unlisted one degrades to generic + a
    warning. A payload missing packs/frontend/generic fails closed (stale sync), like any
    mapped-but-absent pack. Returns (list, warnings) of (dir, manifest) tuples."""
    frontend = (profile.get("stack", {}) or {}).get("frontend")
    resolved: list[tuple[Path, dict]] = []
    warnings: list[str] = []
    if not isinstance(frontend, dict) or not frontend:
        return resolved, warnings
    resolved.append(_resolve_pack("frontend", "generic", payload))
    raw = frontend.get("framework")
    framework = _normalize_framework(raw) if raw else None
    canonical = FRONTEND_FRAMEWORK_ALIASES.get(framework) if framework else None
    if canonical in FRONTEND_PACK_BY_FRAMEWORK:
        resolved.append(_resolve_pack("frontend", FRONTEND_PACK_BY_FRAMEWORK[canonical], payload))
    elif framework in FRONTEND_FRAMEWORK_ALIASES:  # recognized, explicitly unsupported
        warnings.append(
            f"frontend framework {framework!r} is not supported by a frontend pack (no web pack "
            f"applies); installed the generic UX reviewer only"
        )
    elif framework:
        warnings.append(
            f"no frontend pack for framework {framework!r}; installed the generic UX reviewer "
            f"only (supported: {sorted(FRONTEND_PACK_BY_FRAMEWORK)})"
        )
    return resolved, warnings


def _resolve_tools(profile: dict, payload: Path):
    """Resolve the optional tools packs a profile opts into via a top-level `tools: [id, ...]` list.
    Tools are the third axis: they compose INDEPENDENTLY of stack/CI and are MULTI-SELECT, and the id
    IS the pack dir (packs/tools/<id>) — no derivation table. An id with no pack is a warn-and-skip
    (a typo or an un-built tool never fails setup). Returns (list, warnings) of (dir, manifest) tuples.
    """
    ids = profile.get("tools") or []
    resolved: list[tuple[Path, dict]] = []
    warnings: list[str] = []
    if not isinstance(ids, list):
        warnings.append(f"profile 'tools' must be a list of pack ids, got {type(ids).__name__}; skipped")
        return resolved, warnings
    for tid in ids:
        pack_dir = payload / "packs" / "tools" / str(tid)
        manifest_path = pack_dir / "pack.yaml"
        if not manifest_path.is_file():
            warnings.append(
                f"no tools pack {str(tid)!r} at {pack_dir}; skipped (typo, or not built/synced yet)"
            )
            continue
        manifest = load_yaml(manifest_path)
        if not isinstance(manifest, dict) or "overlays" not in manifest:
            warnings.append(f"tools pack {str(tid)!r} manifest missing an 'overlays' map; skipped")
            continue
        resolved.append((pack_dir, manifest))
    return resolved, warnings


def _merge_list(base: list, overlay: list) -> list:
    out = list(base)
    seen = {json.dumps(x, sort_keys=True) for x in base}
    for x in overlay:
        key = json.dumps(x, sort_keys=True)
        if key not in seen:
            out.append(x)
            seen.add(key)
    return out


def _strip_comments(value):
    """Recursively drop '//'-prefixed keys (JSON-comment convention) from dicts at any depth."""
    if isinstance(value, dict):
        return {k: _strip_comments(v) for k, v in value.items() if not str(k).startswith("//")}
    if isinstance(value, list):
        return [_strip_comments(x) for x in value]
    return value


def _deep_merge(base, overlay):
    """Recursively merge overlay into base: dicts merge key-wise, lists concat with de-dup, scalars
    take the overlay. Keys starting with '//' (JSON-comment convention) are dropped at every
    depth — including subtrees copied wholesale from only one side."""
    if isinstance(base, dict) and isinstance(overlay, dict):
        result = {k: _strip_comments(v) for k, v in base.items() if not str(k).startswith("//")}
        for k, v in overlay.items():
            if str(k).startswith("//"):
                continue
            result[k] = _deep_merge(result[k], v) if k in result else _strip_comments(v)
        return result
    if isinstance(base, list) and isinstance(overlay, list):
        return _merge_list(base, overlay)
    return _strip_comments(overlay)


def _merge_json(fragment: Path, dest: Path, log: list[str],
                touched: set[Path] | None = None) -> None:
    if not dest.exists():
        raise InstallError(f"cannot merge {fragment.name}: {dest} does not exist (core not copied?)")
    base = json.loads(dest.read_text(encoding="utf-8"))
    frag = json.loads(fragment.read_text(encoding="utf-8"))
    merged = _deep_merge(base, frag)
    dest.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    if touched is not None:  # a merged dest is touched even when the core copy SKIPped it
        touched.add(dest)
    log.append(f"MERGE   {dest}  (+{fragment.name})")


def _overlay_pack(pack_dir: Path, manifest: dict, target: Path, force: bool,
                  written: set[Path], log: list[str], missing: list[str],
                  touched: set[Path] | None = None,
                  tokens: dict[str, str] | None = None) -> list[Path]:
    """Overlay one pack's files. `tokens` fills the <<CI_*>> seam during the copy (CI/CD packs
    only). Returns the dests actually written, for the caller's post-write token audit."""
    copied: list[Path] = []
    for entry in manifest.get("overlays", []):
        src = pack_dir / entry["src"]
        dest = target / entry["dest"]
        if not src.is_file():
            log.append(f"MISS    {entry['src']}  (not in pack {pack_dir.name})")
            missing.append(f"{entry['src']} (not in pack {pack_dir.name})")
            continue
        if entry.get("merge"):
            _merge_json(src, dest, log, touched)
        elif _copy(src, dest, force, written, log, tokens):
            copied.append(dest)
    return copied


def _splice_claude_stack_section(stack_pack_dir: Path, manifest: dict, target: Path,
                                 force: bool, log: list[str],
                                 touched: set[Path] | None = None) -> None:
    """Replace CLAUDE.md's stack-standards section (heading to the next '## ' heading, or EOF)
    with the pack's realized one; everything before and after the section is preserved. Only
    fires while the {{STACK}} marker survives IN THE SECTION, so Phase-3 edits are safe."""
    claude = target / "CLAUDE.md"
    provides = manifest.get("provides", {}) or {}
    rel = provides.get("claude_standards")
    if not rel:
        return
    section_src = stack_pack_dir / rel
    if not claude.is_file() or not section_src.is_file():
        log.append("MISS    CLAUDE.md stack section  (CLAUDE.md or pack standards absent)")
        return

    text = claude.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    heading_idx = next((i for i, ln in enumerate(lines) if ln.startswith(CLAUDE_STACK_HEADING)), None)
    if heading_idx is None:
        log.append("MISS    CLAUDE.md stack section  (no '## Stack standards' heading)")
        return

    # The section ends at the next same-level heading (or EOF if it is the last section).
    end_idx = next((i for i in range(heading_idx + 1, len(lines)) if lines[i].startswith("## ")),
                   len(lines))
    already_adapted = CLAUDE_STACK_MARKER not in "".join(lines[heading_idx:end_idx])
    if already_adapted and not force:
        log.append("SKIP    CLAUDE.md stack section  (already adapted)")
        return

    # Strip a leading HTML-comment block from the pack section so the splice is clean.
    section = section_src.read_text(encoding="utf-8")
    marker = section_src.name
    if section.lstrip().startswith("<!--") and "-->" in section:
        section = section.split("-->", 1)[1].lstrip("\n")
    head = "".join(lines[:heading_idx]).rstrip("\n")
    tail = "".join(lines[end_idx:]).strip("\n")
    out = f"{head}\n\n{section.rstrip()}\n"
    if tail:
        out += f"\n{tail}\n"
    claude.write_text(out, encoding="utf-8")
    if touched is not None:  # a spliced dest is touched even when the core copy SKIPped it
        touched.add(claude)
    log.append(f"SPLICE  CLAUDE.md stack section  (<- {marker})")


def install(payload: Path, target: Path, force: bool, profile_path: Path | None = None) -> int:
    """Run the install. Every InstallError raised anywhere — bad profile, unresolved pack, failed
    merge, missing mapped source — lands here as a clean "ERROR: ..." + rc 2, never a traceback.
    The log so far (including every MISS line) is still printed on the error path."""
    log: list[str] = []
    try:
        return _install(payload, target, force, profile_path, log)
    except InstallError as exc:
        if log:
            print("\n".join(log))
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def _install(payload: Path, target: Path, force: bool, profile_path: Path | None,
             log: list[str], *, quiet: bool = False) -> int:
    if not payload.is_dir():
        raise InstallError(f"payload not found: {payload}")

    written: set[Path] = set()
    touched: set[Path] = set()
    missing: list[str] = []
    profile: dict | None = None
    stack_pack = cicd_pack = None
    frontend_packs: list[tuple[Path, dict]] = []
    tools_packs: list[tuple[Path, dict]] = []
    warnings: list[str] = []

    if profile_path is not None:
        profile = _load_profile(profile_path)
        stack_pack, cicd_pack, warnings = _resolve_packs(profile, payload)
        frontend_packs, fe_warnings = _resolve_frontend(profile, payload)
        tools_packs, tool_warnings = _resolve_tools(profile, payload)
        warnings = warnings + fe_warnings + tool_warnings

    # The core layout follows the CI/CD platform: a non-GitHub platform drops the GitHub mechanisms
    # and redirects neutral governance content (see _CORE_LAYOUT_BY_PLATFORM). None => identity.
    stack = (profile or {}).get("stack", {}) or {}
    platform = (stack.get("ci_cd", {}) or {}).get("platform")
    _copy_core(payload, target, force, written, log, missing, platform)
    _raise_if_missing(missing)  # after the FULL core scan, so every core miss is reported

    packs = _compose_packs(stack_pack, cicd_pack, frontend_packs, tools_packs,
                           target, force, written, touched, log, missing, warnings, profile)
    _ensure_gitignore(target, log)

    touched |= written  # copies; merge/splice dests were collected as they happened
    profile_id = (profile or {}).get("company", {}).get("profile_id")
    _write_manifest(payload, target, touched, profile_id, packs, log)
    if not quiet:
        _print_summary(log, warnings, tools_packs)
    return 0


def _compose_packs(stack_pack, cicd_pack, frontend_packs, tools_packs, target: Path,
                   force: bool, written: set[Path], touched: set[Path],
                   log: list[str], missing: list[str], warnings: list[str],
                   profile: dict | None) -> list[str]:
    """Overlay every resolved pack (stack -> CI/CD -> frontend -> tools; last wins) and return
    the composed pack ids as '<axis-dir>/<id>' for the manifest."""
    if not (stack_pack or cicd_pack or frontend_packs or tools_packs):
        return []
    parts = [f"stack pack '{p[0].name}'" for p in (stack_pack,) if p]
    parts += [f"CI/CD pack '{p[0].name}'" for p in (cicd_pack,) if p]
    parts += [f"frontend pack '{d.name}'" for d, _ in frontend_packs]
    parts += [f"tools pack '{d.name}'" for d, _ in tools_packs]
    log.append(f"\n-- composing {' + '.join(parts)} --")
    if stack_pack:
        _overlay_pack(stack_pack[0], stack_pack[1], target, force, written, log, missing, touched)
        _splice_claude_stack_section(stack_pack[0], stack_pack[1], target, force, log, touched)
    if cicd_pack:
        # The seam: fill the CI/CD pack's <<CI_*>> tokens from the stack's ci-profile as the files
        # are copied. No stack pack => no table => the tokens are left for Phase 3 (audited below).
        tokens = _ci_token_table(stack_pack, cicd_pack, profile) if stack_pack else None
        emitted = _overlay_pack(cicd_pack[0], cicd_pack[1], target, force, written, log, missing,
                                touched, tokens)
        _audit_ci_tokens(emitted, target, tokens, warnings)
    for fe_dir, fe_manifest in frontend_packs:
        _overlay_pack(fe_dir, fe_manifest, target, force, written, log, missing, touched)
    for tool_dir, tool_manifest in tools_packs:
        _overlay_pack(tool_dir, tool_manifest, target, force, written, log, missing, touched)
    _raise_if_missing(missing)  # after ALL packs are scanned, so every pack miss is reported

    packs = [f"stacks/{p[0].name}" for p in (stack_pack,) if p]
    packs += [f"cicd/{p[0].name}" for p in (cicd_pack,) if p]
    packs += [f"frontend/{d.name}" for d, _ in frontend_packs]
    packs += [f"tools/{d.name}" for d, _ in tools_packs]
    return packs


def _ci_token_table(stack_pack, cicd_pack, profile: dict) -> dict[str, str]:
    """Join the resolved stack pack's ci-profile.yaml with the resolved CI/CD pack's toolchain_map.
    The customer profile's quality.coverage_minimum overrides the stack pack's declared floor (the
    profile is the later, more specific layer). Every authoring fault (no declared profile, unmapped
    toolchain id, multi-line command, missing value) surfaces from ci_tokens as a ValueError; convert
    it to the fail-closed InstallError."""
    floor = (profile.get("quality") or {}).get("coverage_minimum")
    try:
        ci_profile = ci_tokens.load_ci_profile(stack_pack[0], stack_pack[1])
        return ci_tokens.build_token_table(ci_profile, cicd_pack[1], cicd_pack[0].name, floor)
    except ValueError as exc:
        raise InstallError(str(exc)) from exc


def _audit_ci_tokens(emitted: list[Path], target: Path, tokens: dict[str, str] | None,
                     warnings: list[str]) -> None:
    """Post-write scan of what the CI/CD pack actually wrote.

    With a token table, a surviving <<CI_*>> means the pack referenced a token the seam does not
    define — FAIL CLOSED rather than install a pipeline containing a literal token. Without one
    (the stack axis degraded), the same survivors are the EXPECTED Phase-3 hand-adaptation, so
    report them as a warning and let setup exit 0 — the axes degrade independently."""
    found = [(p, ci_tokens.residual_tokens(p.read_text(encoding="utf-8"))) for p in emitted]
    unfilled = [(p, toks) for p, toks in found if toks]
    if not unfilled:
        return
    items = "\n".join(f"  - {p.relative_to(target).as_posix()}: {', '.join(t)}"
                      for p, t in unfilled)
    if tokens is not None:
        raise InstallError(
            f"{len(unfilled)} emitted file(s) still contain unfilled <<CI_*>> seam token(s) "
            f"(fail-closed; the CI/CD pack references a token the stack's ci-profile does not "
            f"define):\n{items}"
        )
    warnings.append(
        f"no stack pack composed, so the CI/CD pack's <<CI_*>> seam tokens were LEFT UNFILLED in "
        f"{len(unfilled)} file(s) — fill them by hand (Phase 3) before the pipeline can run:\n"
        f"{items}"
    )


def _write_manifest(payload: Path, target: Path, touched: set[Path],
                    profile_id: str | None, packs: list[str], log: list[str]) -> None:
    """Record the composed pristine state: hash the FINAL on-disk content of every dest this
    run touched. On re-runs the existing manifest's entries for untouched dests are preserved
    (they still hold the pristine hash a later upgrade classifies against); touched entries
    are refreshed. The manifest write is part of the run — a failure fails the install."""
    try:
        existing = load_manifest(target)
    except ValueError as exc:
        raise InstallError(str(exc)) from exc
    files: dict[str, str] = dict(existing["files"]) if existing else {}
    for dest in touched:
        rel = dest.relative_to(target).as_posix()
        if rel == MANIFEST_REL:  # the manifest never lists itself
            continue
        files[rel] = file_digest(dest)
    try:
        write_manifest(target, build_manifest(payload, profile_id, packs, files))
    except OSError as exc:
        raise InstallError(f"failed to write {MANIFEST_REL}: {exc}") from exc
    log.append(f"MANIFEST {MANIFEST_REL} ({len(files)} files)")


def _raise_if_missing(missing: list[str]) -> None:
    """Fail closed on mapped-but-absent sources. Called only after a full scan so the error
    (and the MISS log lines) name every missing item, not just the first."""
    if not missing:
        return
    items = "\n".join(f"  - {m}" for m in missing)
    raise InstallError(f"{len(missing)} mapped source(s) missing (fail-closed):\n{items}")


def _print_summary(log: list[str], warnings: list[str], tools_packs: list[tuple[Path, dict]]) -> None:
    written_n = sum(1 for line in log if line.startswith(("WRITE", "FORCE", "OVERLAY", "SPLICE")))
    merged_n = sum(1 for line in log if line.startswith("MERGE"))
    skipped_n = sum(1 for line in log if line.startswith("SKIP"))
    print("\n".join(log))
    print(f"\nHarness install: {written_n} written, {merged_n} merged, {skipped_n} skipped "
          f"(use --force to overwrite).")
    _print_tool_setup(tools_packs)
    if warnings:
        print(f"\nWARNING: {len(warnings)} pack(s) not composed:", file=sys.stderr)
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)
    print("NEXT: review CLAUDE.md placeholders, then prove the rails "
          "(.github/RAILS.md shakedown drills) before trusting them.")


def _print_tool_setup(tools_packs: list[tuple[Path, dict]]) -> None:
    """Surface each tools pack's manual setup steps. The installer never RUNS these — self-installing
    tools (e.g. GitNexus) register their own MCP server + generate their own footprint; we only point
    the operator at the commands the pack declares in its `setup` block."""
    with_setup = [(d, m) for d, m in tools_packs if m.get("setup")]
    if not with_setup:
        return
    print("\nMANUAL SETUP - tools packs install themselves; run these after the harness install:")
    for tool_dir, manifest in with_setup:
        setup = manifest["setup"]
        name = manifest.get("pack", {}).get("name", tool_dir.name)
        print(f"  {name}: {setup.get('summary', '')}")
        for cmd in setup.get("commands", []):
            print(f"      {cmd}")
        guide = manifest.get("provides", {}).get("setup_guide")
        if guide:
            print(f"      guide: .claude/tools/{tool_dir.name}/{guide}")


def _ensure_gitignore(target: Path, log: list[str]) -> None:
    gi = target / ".gitignore"
    existing = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    # Compare normalized (whitespace and trailing slash stripped) so a pre-existing entry
    # without the trailing slash doesn't get a near-duplicate appended.
    have = {ln.strip().rstrip("/") for ln in existing}
    missing = [ln for ln in GITIGNORE_LINES if ln.strip().rstrip("/") not in have]
    if not missing:
        return
    with gi.open("a", encoding="utf-8") as fh:
        if existing and existing[-1].strip():
            fh.write("\n")
        fh.write("# delivery harness\n" + "\n".join(missing) + "\n")
    log.append(f"WRITE   .gitignore  (+{len(missing)} lines)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Install the delivery harness into a repo.")
    ap.add_argument("--payload", required=True, type=Path, help="plugin harness/ directory")
    ap.add_argument("--target", default=Path("."), type=Path, help="target repo root")
    ap.add_argument("--profile", type=Path, default=None,
                    help="profile.yaml selecting the stack + CI/CD packs to compose (optional)")
    ap.add_argument("--force", action="store_true", help="overwrite existing files")
    args = ap.parse_args()
    profile = args.profile.resolve() if args.profile else None
    return install(args.payload.resolve(), args.target.resolve(), args.force, profile)


if __name__ == "__main__":
    raise SystemExit(main())
