"""What a stage still needs before it can be signed off — one read-only call (spec 0010).

Answering "is this stage ready?" previously took three or four separate calls and some text
parsing. This composes them into one JSON answer, for a UI that wants to show a person what is
missing and link each item to the field it refers to.

Two deliberate choices, both about not damaging the project while reading it:

  * **It never calls check_gates.py.** That script appends to `.sdlc/metrics/gate-log.jsonl` on
    every single invocation, with no flag to suppress it. A UI that polls readiness would
    silently inflate the project's own empirical-metrics record — the gate log would stop
    measuring gate runs and start measuring how often someone had a window open. So this reads
    the same registry conditions itself and leaves the log alone. check_gates.py remains the
    authority for actually passing a gate; this is the read-only view of the same question.

  * **Shapes are resolved by PATH, not by stamp.** check_document_completeness.scan_repo matches
    a document to its shape through the template stamp comment — but nothing in the pipeline
    (init_project.py, new_spec.py, the authoring agents) ever writes that stamp, so a
    stamp-based scan silently skips every document in a real project. `.sdlc/artifacts/<phase
    dir>/<name>.md` mirrors `templates/phases/<phase dir>/<name>.shape.yaml` exactly, which is
    the resolution that actually works today. The stamp is still tried as a fallback so this
    keeps working if stamping is ever wired up.

Exit code is always 0 — this reports, it never blocks. Dual --repo/--state, like its siblings.

Usage:
  stage_readiness.py [--phase 1] [--repo P | --state P] [--json]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import activities_model  # noqa: E402
import check_document_completeness as cdc  # noqa: E402
import document_shape as ds  # noqa: E402
import phase_model as pm  # noqa: E402
import sign_off_confirmations as soc  # noqa: E402
import yaml  # noqa: E402
from confirmation_hints import hint_for  # noqa: E402
from sign_off_confirmations import judgement_questions as judgement_conditions  # noqa: E402,F401

TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "templates"


def resolve_repo_root(args) -> Path:
    if getattr(args, "state", None):
        state_path = Path(args.state)
        if not state_path.exists():
            print(f"Error: State file not found: {state_path}")
            sys.exit(0)  # advisory — a missing state file is a report, not a crash
        return state_path.resolve().parent.parent
    return Path(args.repo).resolve()


def load_state(repo_root: Path) -> dict:
    state_path = repo_root / ".sdlc" / "state.yaml"
    if not state_path.exists():
        return {}
    try:
        return yaml.safe_load(state_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}


def find_shape_for_document(doc_relpath: str, doc_text: str) -> Path | None:
    """Path convention first, stamp second — see this module's docstring for why."""
    normalized = doc_relpath.replace("\\", "/")
    parts = normalized.split("/")
    if len(parts) >= 4 and parts[0] == ".sdlc" and parts[1] == "artifacts":
        candidate = TEMPLATES_ROOT / "phases" / parts[2] / (Path(parts[-1]).stem + ".shape.yaml")
        if candidate.exists():
            return candidate
    stamp = ds.read_stamp(doc_text)
    if stamp:
        return cdc.find_shape_for_template(TEMPLATES_ROOT, stamp[0])
    return None


def signoff_state(state: dict, phase_id: str) -> dict:
    """Read sign-off straight from state.yaml, which is where advance_phase.py actually writes
    it — `gate_results.signed_off_by` for the overall human sign-off and a `sign_offs` list for
    per-discipline ones. (audit_artifacts._signoff_note looks for `sign_off`/`signed_by`, keys
    nothing ever writes, so it can never report a name; don't route this through it.)"""
    phases = state.get("phases") or {}
    pdata = phases.get(phase_id) or {}
    if not isinstance(pdata, dict):
        pdata = {}
    gate_results = pdata.get("gate_results") or {}
    if not isinstance(gate_results, dict):
        gate_results = {}
    sign_offs = pdata.get("sign_offs") or []
    return {
        "status": pdata.get("status", "pending"),
        "completed_at": pdata.get("completed_at"),
        "signed_off_by": gate_results.get("signed_off_by"),
        "discipline_sign_offs": sign_offs if isinstance(sign_offs, list) else [],
    }


def _assess_folder(art, full: Path, rel: str) -> dict:
    """A folder artifact (the registry writes `adrs/` with a trailing slash). It has no single
    document to read through a shape, so it is not shaped and nothing opens it as a file;
    what can honestly be said is whether it holds anything — the gate's own rule
    (check_gates.check_artifact_exists), so the two never disagree about a folder."""
    exists = full.is_dir()
    findings = []
    if exists and not any(full.iterdir()):
        findings.append({"section": art.name, "field": None, "reason": "folder is empty"})
    return {
        "name": art.name, "path": rel, "exists": exists, "folder": True, "shaped": False,
        "findings": findings, "ready": exists and not findings,
    }


def assess_artifacts(repo_root: Path, phase_def: dict, project_type: str | None) -> list[dict]:
    phase_dir_name = phase_def.get("slug") or ""
    phase_dir = repo_root / ".sdlc" / "artifacts" / phase_dir_name
    results = []

    for art in pm.required_artifacts(phase_def, project_type):
        full = art.base_dir(phase_dir, repo_root) / art.name
        rel = str(full.relative_to(repo_root)).replace("\\", "/") if full.is_relative_to(repo_root) else art.name

        # Decided from the registry entry as well as the disk, so a folder that has not been
        # created yet is still known to be a folder — and so a stray FILE where a folder is
        # expected reads as absent rather than being opened as the document it is not.
        if art.name.endswith("/") or full.is_dir():
            results.append(_assess_folder(art, full, rel))
            continue

        entry: dict = {"name": art.name, "path": rel, "exists": full.exists(), "folder": False, "findings": []}

        # Resolved from the PATH, so "what is this document for" is answerable before the
        # document exists — which is exactly when someone most needs to be told.
        text = full.read_text(encoding="utf-8", errors="replace") if full.exists() else ""
        shape_path = find_shape_for_document(rel, text)
        entry["shaped"] = shape_path is not None
        if shape_path is not None:
            shape = cdc.load_shape(shape_path)
            entry["description"] = shape.get("description")
            if full.exists():
                entry["findings"] = cdc.check_document(text, shape)

        entry["ready"] = entry["exists"] and not entry["findings"]
        results.append(entry)
    return results


def judgement_items(repo_root: Path, phase_id: str, state: dict) -> list[dict]:
    """Each sign-off question as a person answers it: an id to confirm against, what the software
    can say about it (a pre-check, never a verdict), and who has already confirmed it."""
    confirmed = soc.current_confirmations(repo_root, phase_id)
    return [
        {"id": qid, "text": text, "hint": hint_for(text, repo_root, state), "confirmation": confirmed.get(qid)}
        for qid, text in soc.questions(phase_id)
    ]


def assess(repo_root: Path, phase_id: str | None) -> dict:
    state = load_state(repo_root)
    current = pm.normalize_id(state.get("current_phase", 0)) if state else "0"
    target = pm.normalize_id(phase_id) if phase_id is not None else current

    phase_def = pm.get_phase(target) if target is not None else None
    if phase_def is None:
        return {"error": f"unknown phase {phase_id!r}", "stage": None}

    artifacts = assess_artifacts(repo_root, phase_def, (state.get("project_type") if state else None))
    blocking = [a for a in artifacts if not a["ready"]]
    stage_id = pm.normalize_id(phase_def["id"])
    judgement = judgement_items(repo_root, stage_id, state)

    activities, warnings = declared_activities(repo_root, stage_id)

    result = {
        "stage": {
            "id": pm.normalize_id(phase_def["id"]),
            "name": phase_def.get("name"),
            "display": phase_def.get("display"),
            "description": phase_def.get("description"),
            "is_current": pm.normalize_id(phase_def["id"]) == current,
        },
        "sign_off": signoff_state(state, pm.normalize_id(phase_def["id"])),
        "artifacts": artifacts,
        "judgement_conditions": judgement_conditions(phase_def),
        "judgement": judgement,
        "confirmed_count": sum(1 for i in judgement if i["confirmation"]),
        "blocking_count": len(blocking),
        "ready": not blocking,
        "activities": activities,
        "definition": phase_def.get("definition"),
    }
    if warnings:
        result["warnings"] = warnings
    return result


def declared_activities(repo_root: Path, stage_id: str) -> tuple[list[dict], list[str]]:
    """The stage's activities, or none plus a warning when the declaration cannot be used.

    A broken `phases/activities.yaml` must not take the readiness report down with it: the
    documents and sign-off are still true, so only the activity list is withheld."""
    try:
        data = activities_model.load()
        problems = activities_model.validate(data)
        if problems:
            return [], [f"activities declaration is invalid: {problems[0]}"]
        return activities_model.evaluate(repo_root, stage_id, data), []
    except activities_model.ActivitiesError as e:
        return [], [f"activities declaration unavailable: {e}"]
    except Exception as e:  # noqa: BLE001 — a fault in the declaration must not take the report down
        return [], [f"activities declaration could not be evaluated: {type(e).__name__}: {e}"]


def format_report(result: dict) -> str:
    if result.get("error"):
        return f"Error: {result['error']}"

    stage = result["stage"]
    lines = [f"Readiness — {stage['display']}", "=" * 50, ""]
    if stage.get("description"):
        lines += [f"  {stage['description']}", ""]

    lines.append("  Documents")
    indent = " " * 4
    detail_indent = " " * 4 + " " * 12
    for a in result["artifacts"]:
        if not a["exists"]:
            lines.append(f"{indent}{'MISSING':<11} {a['name']} — not created yet")
            if a.get("description"):
                lines.append(f"{detail_indent}{a['description']}")
            continue
        if a["findings"]:
            lines.append(f"{indent}{'INCOMPLETE':<11} {a['name']} — {len(a['findings'])} field(s) to fill")
            for f in a["findings"]:
                where = f["section"] if f.get("field") is None else f"{f['section']} > {f['field']}"
                lines.append(f"{detail_indent}{where}: {f['reason']}")
        else:
            lines.append(f"{indent}{'READY':<11} {a['name']}")
        if not a.get("shaped"):
            lines.append(f"{detail_indent}(no shape — only its presence could be checked)")

    judgement = result["judgement"]
    if judgement:
        lines += ["", "  Questions for whoever signs this off (a person confirms each; hints only pre-check)"]
        for item in judgement:
            c = item["confirmation"]
            lines.append(f"    {'[x]' if c else '[ ]'} {item['text']}")
            lines.append(f"          {item['hint']['detail']}")
            if c:
                lines.append(f"          Confirmed by {c['actor']} at {c['ts']}")

    so = result["sign_off"]
    lines += ["", f"  Sign-off: {so['status']}" + (f" by {so['signed_off_by']}" if so.get("signed_off_by") else "")]
    lines += ["", "=" * 50]
    lines.append(
        "READY — every required document is present and complete."
        if result["ready"]
        else f"NOT READY — {result['blocking_count']} document(s) still need work."
    )
    lines.append("ADVISORY — this reports; /sprd-gate and /sprd-next decide (exit 0).")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="What a stage still needs before sign-off (read-only, never blocks)"
    )
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--state", help="Path to .sdlc/state.yaml (workflow mode)")
    src.add_argument("--repo", default=".", help="Target repo root (standalone mode; default: cwd)")
    parser.add_argument("--phase", help="Phase id (default: the project's current phase)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = assess(resolve_repo_root(args), args.phase)
    print(json.dumps(result, indent=2) if args.json else format_report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
