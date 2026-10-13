"""Which artifacts have a narrative companion, and is it stale — the read-only half of /sprd-enhance.

/sprd-enhance spawns the narrative-enhancer for every artifact in a phase that has no
`<name>.narrative.md` beside it. Working out *which* those are, and whether an existing narrative
has been left behind by an edit to its source, is bookkeeping. This does it the same way every time
so a button can show it and the model is spent only on the prose.

For each `.md` file directly inside `.sdlc/artifacts/<phase dir>/` (not `*.narrative.md`, not
subfolders) it reports:
  status   `none` (no `<name>.narrative.md` beside it) or `present`
  stale    for a `present` narrative: true if the source was last COMMITTED after the narrative,
           false if not, null when git cannot say (no git, not a repository, or either file
           untracked). Never a guess.

Staleness is by git commit time, never file modification time: a checkout resets mtimes, so they
would call every narrative stale or fresh at random; commit time is the same on every machine.

Advisory: ALWAYS exits 0, except a usage error (exit 2). No `.sdlc/artifacts`, no state file, or no
artifacts reports `has_data: false` with a note, never a fabricated zero. Output is deterministic
(sorted by file name; no timestamps).

Standalone or Workflow:
  - Workflow:   --state .sdlc/state.yaml   (current phase from the state; artifacts beside it)
  - Standalone: --repo <root>              (reads <root>/.sdlc/state.yaml and <root>/.sdlc/artifacts)
  With --phase or --all-phases the state file is not needed at all.

Usage:
  narrative_status.py (--state S | --repo R) [--phase N | --all-phases] [--json]
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase_model as pm  # noqa: E402
import yaml  # noqa: E402

NARRATIVE_SUFFIX = ".narrative.md"
GIT_TIMEOUT_SECONDS = 20


def commit_time(project_root: Path, path: Path) -> int | None:
    """Unix time of the last commit touching `path`, or None when git cannot say."""
    rel = os.path.relpath(path, project_root).replace(os.sep, "/")
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", rel],
            cwd=project_root, capture_output=True, text=True,
            timeout=GIT_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    out = proc.stdout.strip()
    if proc.returncode != 0 or not out.isdigit():
        return None
    return int(out)


def is_stale(project_root: Path, source: Path, narrative: Path) -> bool | None:
    source_time = commit_time(project_root, source)
    narrative_time = commit_time(project_root, narrative)
    if source_time is None or narrative_time is None:
        return None
    return source_time > narrative_time


def rel_posix(project_root: Path, path: Path) -> str:
    return os.path.relpath(path, project_root).replace(os.sep, "/")


def scan_phase_folder(project_root: Path, folder: Path) -> list[dict]:
    """The technical artifacts directly inside `folder`, sorted by file name."""
    sources = sorted(
        (p for p in folder.iterdir()
         if p.is_file() and p.name.endswith(".md") and not p.name.endswith(NARRATIVE_SUFFIX)),
        key=lambda p: p.name)
    artifacts = []
    for source in sources:
        stem = source.name[: -len(".md")]
        narrative = folder / f"{stem}{NARRATIVE_SUFFIX}"
        if narrative.is_file():
            artifacts.append({
                "name": stem,
                "path": rel_posix(project_root, source),
                "status": "present",
                "narrative": rel_posix(project_root, narrative),
                "stale": is_stale(project_root, source, narrative),
            })
        else:
            artifacts.append({
                "name": stem,
                "path": rel_posix(project_root, source),
                "status": "none",
                "narrative": None,
                "stale": None,
            })
    return artifacts


def read_current_phase(state_path: Path) -> tuple[str | None, str | None]:
    """(current phase id, problem) from a state file; exactly one of the two is None."""
    if not state_path.is_file():
        return None, f"no state file at {state_path.as_posix()}"
    try:
        state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return None, f"state file {state_path.as_posix()} could not be read"
    phase = pm.normalize_id(state.get("current_phase")) if isinstance(state, dict) else None
    if not phase:
        return None, f"state file {state_path.as_posix()} records no current_phase"
    return phase, None


def empty_result(note: str) -> dict:
    return {"has_data": False, "notes": [note], "phases": [],
            "coverage": {"with_narrative": 0, "total": 0}}


def select_slugs(args, state_path: Path, artifacts_dir: Path) -> tuple[list[str], str | None]:
    """The phase folder names to scan, or a note explaining why there are none."""
    if args.all_phases:
        slugs = [p["slug"] for p in pm.all_phases() if (artifacts_dir / p["slug"]).is_dir()]
        return slugs, None if slugs else f"no phase folders under {artifacts_dir.as_posix()}"
    if args.phase is not None:
        phase = pm.normalize_id(args.phase)
    else:
        phase, problem = read_current_phase(state_path)
        if problem:
            return [], problem
    slug = pm.artifact_dirname(phase)
    if slug is None:
        return [], f"unknown phase '{phase}'"
    if not (artifacts_dir / slug).is_dir():
        return [], f"no artifact folder for phase '{phase}' ({slug})"
    return [slug], None


def build_result(args) -> dict:
    if args.state:
        state_path = Path(args.state).resolve()
        sdlc_dir = state_path.parent
    else:
        sdlc_dir = Path(args.repo).resolve() / ".sdlc"
        state_path = sdlc_dir / "state.yaml"
    project_root = sdlc_dir.parent
    artifacts_dir = sdlc_dir / "artifacts"

    if not artifacts_dir.is_dir():
        return empty_result(f"no artifacts folder at {artifacts_dir.as_posix()}")

    slugs, problem = select_slugs(args, state_path, artifacts_dir)
    if problem:
        return empty_result(problem)

    phases = [{"phase": slug, "artifacts": scan_phase_folder(project_root, artifacts_dir / slug)}
              for slug in slugs]
    artifacts = [a for ph in phases for a in ph["artifacts"]]
    present = [a for a in artifacts if a["status"] == "present"]
    notes = []
    if not artifacts:
        notes.append("no artifacts found in the selected phase folder(s)")
    unknown = [a["narrative"] for a in present if a["stale"] is None]
    if unknown:
        notes.append(f"staleness unknown for {len(unknown)} narrative(s): git history is unavailable "
                     "or the source or narrative is not committed")
    return {
        "has_data": bool(artifacts),
        "notes": notes,
        "phases": phases,
        "coverage": {"with_narrative": len(present), "total": len(artifacts)},
    }


def format_report(result: dict) -> str:
    lines = ["Narrative Coverage", "=" * 44]
    if not result["has_data"]:
        lines.extend(result["notes"] or ["no data"])
        return "\n".join(lines)
    for phase in result["phases"]:
        lines.append(f"{phase['phase']}")
        for a in phase["artifacts"]:
            if a["status"] == "none":
                state = "no narrative"
            else:
                stale = {True: "STALE", False: "up to date", None: "staleness unknown"}[a["stale"]]
                state = f"narrative present ({stale})"
            lines.append(f"  {a['name']}: {state}")
    cov = result["coverage"]
    lines.append("")
    lines.append(f"Coverage: {cov['with_narrative']}/{cov['total']} artifacts have narrative companions")
    for note in result["notes"]:
        lines.append(f"Note: {note}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report which artifacts have a narrative companion and whether it is stale.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--state", help="Path to .sdlc/state.yaml")
    source.add_argument("--repo", help="Project root containing .sdlc/")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--phase", help="Phase id to report (default: the current phase)")
    scope.add_argument("--all-phases", action="store_true", help="Every phase folder that exists")
    parser.add_argument("--json", action="store_true", help="Print exactly one JSON document")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    result = build_result(args)
    print(json.dumps(result, indent=2) if args.json else format_report(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
