"""Scan and catalog external reference documents for SDLC intake."""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

# File type to glob pattern mapping
TYPE_GLOBS = {
    "pdf": "*.pdf",
    "markdown": "*.md",
    "text": "*.txt",
    "docx": "*.docx",
    "html": "*.html",
}

# Rough bytes-to-tokens ratio (English text average)
BYTES_PER_TOKEN = 4


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def compute_checksum(file_path: Path) -> str:
    """Compute SHA-256 hash of a file (first 16 hex chars)."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()[:16]}"


def estimate_tokens_from_text(text: str) -> int:
    """Estimate token count from word count (words * 1.3)."""
    return int(len(text.split()) * 1.3)


def estimate_tokens_from_bytes(size_bytes: int) -> int:
    """Rough token estimate from file size."""
    return size_bytes // BYTES_PER_TOKEN


def extract_text_length(file_path: Path, file_type: str) -> tuple[int, str]:
    """Extract text and estimate tokens. Returns (estimated_tokens, method)."""
    if file_type in ("markdown", "text"):
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
            return estimate_tokens_from_text(text), "word_count"
        except Exception:
            return estimate_tokens_from_bytes(file_path.stat().st_size), "byte_estimate"

    if file_type == "pdf":
        # Try pymupdf (fitz) if available
        try:
            import fitz  # type: ignore[import-untyped]

            doc = fitz.open(file_path)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            if text.strip():
                return estimate_tokens_from_text(text), "pdf_extracted"
        except ImportError:
            pass
        except Exception:
            pass
        # Fallback: byte-based estimate
        return estimate_tokens_from_bytes(file_path.stat().st_size), "byte_estimate"

    if file_type == "html":
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
            # Strip HTML tags for rough word count
            import re

            clean = re.sub(r"<[^>]+>", " ", text)
            return estimate_tokens_from_text(clean), "html_stripped"
        except Exception:
            return estimate_tokens_from_bytes(file_path.stat().st_size), "byte_estimate"

    # docx and others: byte-based estimate
    return estimate_tokens_from_bytes(file_path.stat().st_size), "byte_estimate"


def scan_intake_folder(
    intake_path: Path,
    types: list[str],
    max_documents: int,
) -> list[dict]:
    """Scan the intake folder for matching files."""
    files = []
    for file_type in types:
        glob_pattern = TYPE_GLOBS.get(file_type)
        if not glob_pattern:
            continue
        for fp in sorted(intake_path.rglob(glob_pattern)):
            if fp.is_file():
                files.append((fp, file_type))

    # Deduplicate by path (a .md file might match both markdown and text)
    seen = set()
    unique = []
    for fp, ft in files:
        if fp not in seen:
            seen.add(fp)
            unique.append((fp, ft))

    # Sort by name for stable DOC-NNN assignment
    unique.sort(key=lambda x: x[0].name.lower())

    # Apply max_documents cap
    if len(unique) > max_documents:
        print(
            f"Warning: Found {len(unique)} documents, capped at {max_documents}",
            file=sys.stderr,
        )
        unique = unique[:max_documents]

    return unique


def catalog_documents(
    intake_path: Path,
    files: list[tuple[Path, str]],
    config: dict,
    project_root: Path,
) -> dict:
    """Build the catalog.json structure."""
    documents = []
    total_tokens = 0

    for i, (fp, file_type) in enumerate(files, start=1):
        doc_id = f"DOC-{i:03d}"
        est_tokens, method = extract_text_length(fp, file_type)
        total_tokens += est_tokens

        documents.append({
            "doc_id": doc_id,
            "filename": fp.name,
            "type": file_type,
            "source_path": os.path.relpath(fp, project_root).replace("\\", "/"),
            "size_bytes": fp.stat().st_size,
            "estimated_tokens": est_tokens,
            "estimation_method": method,
            "checksum": compute_checksum(fp),
        })

    return {
        "intake_path": str(intake_path).replace("\\", "/"),
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "total_documents": len(documents),
        "total_estimated_tokens": total_tokens,
        "index_budget_tokens": config.get("index_budget_tokens", 5000),
        "summary_budget_tokens": config.get("summary_budget_tokens", 750),
        "documents": documents,
    }


LOCKED_MESSAGE = (
    "catalog is locked; DOC-NNN ids are stable — edit catalog.json by hand to unlock"
)


class Refusal(Exception):
    """A request the script declines to carry out (exit 1, nothing written)."""


def _id_list(value: str) -> list[str]:
    """argparse type: a comma-separated DOC-NNN list, with no empty elements."""
    ids = [part.strip() for part in value.split(",")]
    if not all(ids):
        raise argparse.ArgumentTypeError(f"empty id in list: {value!r}")
    return ids


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan and catalog external documents for SDLC intake"
    )
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--state", help="Path to .sdlc/state.yaml")
    where.add_argument("--repo", help="Project root containing .sdlc/ (dual mode)")
    parser.add_argument(
        "--docs",
        help="Catalog this folder instead of the profile's intake path. With no "
        "--state/--repo the catalog is provisional and nothing is written.",
    )
    parser.add_argument(
        "--rescan",
        action="store_true",
        help="Force re-cataloging even if catalog.json exists",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print the catalog as one JSON document"
    )
    parser.add_argument(
        "--skip", type=_id_list, metavar="DOC-NNN[,DOC-NNN]",
        help="Mark documents as skipped (additive, stored in catalog.json)",
    )
    parser.add_argument(
        "--priority", type=_id_list, metavar="DOC-NNN[,DOC-NNN]",
        help="Set the priority order, highest first (stored in catalog.json)",
    )
    parser.add_argument(
        "--lock", action="store_true",
        help="Freeze DOC-NNN ids: set locked=true in catalog.json",
    )
    parser.add_argument(
        "--registry", action="store_true",
        help="Write the document registry and the session-start index from the catalog and the "
        "summaries that exist (reads the catalog, never changes it)",
    )
    return parser


def parse_args() -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args()
    if not (args.state or args.repo or args.docs):
        parser.error("one of --state, --repo or --docs is required")
    if args.registry and (args.skip or args.priority or args.lock or args.rescan or args.docs):
        parser.error("--registry builds from the existing catalog; it cannot be combined with "
                     "--skip, --priority, --lock, --rescan or --docs")
    return args


def read_catalog(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_catalog(path: Path, catalog: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)


def fail(message: str, code: int = 1) -> None:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(code)


def catalog_json(catalog: dict, provisional: bool, message: str | None = None) -> dict:
    """Shape a catalog (or an empty result) as the --json document."""
    skipped = list(catalog.get("skipped", []))
    order = list(catalog.get("priority_order", []))
    documents = []
    for doc in catalog.get("documents", []):
        doc_id = doc["doc_id"]
        documents.append({
            "id": doc_id,
            "file": doc.get("source_path"),
            "type": doc.get("type"),
            "tokens": doc.get("estimated_tokens"),
            "estimation_method": doc.get("estimation_method"),
            "checksum": doc.get("checksum"),
            "skipped": doc_id in skipped,
            "priority": order.index(doc_id) + 1 if doc_id in order else None,
        })
    active = [d for d in documents if not d["skipped"]]
    payload = {
        "documents": documents,
        "locked": bool(catalog.get("locked")),
        "locked_at": catalog.get("locked_at"),
        "provisional": provisional,
        "skipped": skipped,
        "priority_order": order,
        "totals": {
            "documents": len(documents),
            "estimated_tokens": sum(d["tokens"] or 0 for d in documents),
            "skipped_documents": len(documents) - len(active),
            "active_documents": len(active),
            "active_estimated_tokens": sum(d["tokens"] or 0 for d in active),
            "index_budget_tokens": catalog.get("index_budget_tokens"),
            "summary_budget_tokens": catalog.get("summary_budget_tokens"),
        },
    }
    if message:
        payload["message"] = message
    return payload


def emit_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


def locate_project(args: argparse.Namespace) -> tuple[Path | None, Path | None]:
    """Return (sdlc_dir, project_root); (None, None) when running standalone."""
    if not (args.state or args.repo):
        return None, None
    if args.state:
        state_path = Path(args.state)
    else:
        state_path = Path(args.repo) / ".sdlc" / "state.yaml"
    if not state_path.exists():
        fail(f"State file not found: {state_path}")
    return state_path.parent, state_path.parent.parent


def check_change_rules(args, sdlc_dir, existing) -> None:
    """Refuse changes a standalone run cannot store or a locked catalog forbids."""
    wants_change = bool(args.skip or args.priority or args.lock)
    if sdlc_dir is None and wants_change:
        fail("--skip, --priority and --lock edit a project catalog; pass --repo or --state")
    if args.lock and existing is None:
        fail("no catalog to lock; run intake first")
    if existing and existing.get("locked") and (args.rescan or args.skip or args.priority):
        fail(LOCKED_MESSAGE)


def resolve_intake(args, sdlc_dir, project_root, provisional: bool) -> tuple[dict, Path]:
    """Find the documentation config and the folder to scan (may exit)."""
    profile = {}
    if sdlc_dir is not None:
        profile_path = sdlc_dir / "profile.yaml"
        if profile_path.exists():
            profile = load_yaml(profile_path) or {}
        elif not args.docs:
            fail(f"Profile not found: {profile_path}")
    doc_config = profile.get("documentation")
    if args.docs:
        intake_path = Path(args.docs)
        if not intake_path.is_dir():
            fail(f"Intake path not found: {intake_path}")
        return doc_config or {}, intake_path
    if not doc_config:
        message = "No 'documentation' section in profile. Nothing to intake."
        if args.json:
            emit_json(catalog_json({}, provisional, message))
        else:
            print(message)
        sys.exit(0)
    intake_path = project_root / doc_config["intake_path"]
    if not intake_path.exists():
        print(f"Error: Intake path not found: {intake_path}", file=sys.stderr)
        print(
            f"Create the folder and place reference documents in it, then re-run.",
            file=sys.stderr,
        )
        sys.exit(1)
    return doc_config, intake_path


def scan_catalog(doc_config, intake_path, project_root, args, provisional) -> dict:
    types = doc_config.get("types", ["pdf", "markdown", "text"])
    files = scan_intake_folder(intake_path, types, doc_config.get("max_documents", 50))
    if not files:
        message = f"No matching documents found in {intake_path}"
        if args.json:
            emit_json(catalog_json({}, provisional, message))
        else:
            print(message)
            print(f"  Scanned for types: {types}")
        sys.exit(2)
    # Source paths are relative to the project when the folder sits inside it,
    # otherwise to the folder itself (never a machine-specific absolute path).
    inside = project_root is not None and intake_path.resolve().is_relative_to(
        project_root.resolve()
    )
    return catalog_documents(
        intake_path, files, doc_config, project_root if inside else intake_path
    )


def carry_over_decisions(old: dict, new: dict) -> None:
    """Re-attach skip/priority to the rescanned catalog by source path (ids can shift)."""
    old_paths = {d["doc_id"]: d.get("source_path") for d in old.get("documents", [])}
    new_ids = {d["source_path"]: d["doc_id"] for d in new["documents"]}
    for key in ("skipped", "priority_order"):
        if key in old:
            carried = (new_ids.get(old_paths.get(i)) for i in old[key])
            new[key] = [i for i in carried if i]


def apply_decisions(catalog: dict, skip, priority) -> bool:
    """Store --skip/--priority in the in-memory catalog; True when anything changed."""
    known = {d["doc_id"] for d in catalog["documents"]}
    unknown = [i for i in (skip or []) + (priority or []) if i not in known]
    if unknown:
        raise Refusal(f"unknown document id(s): {', '.join(unknown)}")
    changed = False
    if skip:
        merged = sorted(set(catalog.get("skipped", [])) | set(skip))
        changed |= merged != catalog.get("skipped")
        catalog["skipped"] = merged
    if priority:
        ordered = list(dict.fromkeys(priority))
        changed |= ordered != catalog.get("priority_order")
        catalog["priority_order"] = ordered
    return changed


def apply_lock(catalog: dict) -> bool:
    if catalog.get("locked"):
        return False
    catalog["locked"] = True
    catalog["locked_at"] = datetime.now(timezone.utc).isoformat()
    return True


def print_existing(catalog: dict, catalog_path: Path) -> None:
    print(f"Catalog already exists: {catalog_path}")
    print("Use --rescan to force re-cataloging.")
    print(
        f"  {catalog['total_documents']} documents, "
        f"~{catalog['total_estimated_tokens']:,} estimated tokens"
    )
    if catalog.get("locked"):
        print("  [LOCKED] DOC-NNN IDs are frozen; --rescan, --skip and --priority are refused.")


def print_summary(catalog: dict, intake_path: Path) -> None:
    print(f"Document Intake Catalog — {catalog['total_documents']} documents")
    print("=" * 60)
    print(f"  Intake path: {intake_path}")
    print(f"  Total estimated tokens: ~{catalog['total_estimated_tokens']:,}")
    print(f"  Index budget: {catalog['index_budget_tokens']} tokens")
    print(f"  Summary budget: {catalog['summary_budget_tokens']} tokens/doc")
    print()

    for doc in catalog["documents"]:
        method_tag = f" [{doc['estimation_method']}]" if doc["estimation_method"] != "word_count" else ""
        print(
            f"  {doc['doc_id']}  {doc['filename']:<40} "
            f"{doc['type']:<10} ~{doc['estimated_tokens']:>8,} tokens{method_tag}"
        )

    print()


def print_changes(args, catalog: dict, lock_changed: bool) -> None:
    if args.skip:
        print(f"Skipped: {', '.join(catalog.get('skipped', []))}")
    if args.priority:
        print(f"Priority order: {', '.join(catalog.get('priority_order', []))}")
    if args.lock:
        print("Catalog locked." if lock_changed else "Catalog already locked.")


def registry_mode(args: argparse.Namespace, sdlc_dir: Path | None) -> None:
    """--registry: build the registry and index from the catalog on disk, then exit."""
    import intake_registry

    catalog_path = sdlc_dir / "context" / "intake" / "catalog.json" if sdlc_dir else None
    if catalog_path is None or not catalog_path.exists():
        fail("no catalog to build a registry from; run intake first")
    result = intake_registry.build(sdlc_dir, read_catalog(catalog_path), estimate_tokens_from_text)
    if args.json:
        emit_json(result)
    else:
        print(intake_registry.format_report(result))


def main() -> None:
    args = parse_args()
    sdlc_dir, project_root = locate_project(args)
    if args.registry:
        registry_mode(args, sdlc_dir)
        return
    provisional = sdlc_dir is None
    catalog_path = (
        sdlc_dir / "context" / "intake" / "catalog.json" if sdlc_dir else None
    )
    existing = (
        read_catalog(catalog_path) if catalog_path and catalog_path.exists() else None
    )
    check_change_rules(args, sdlc_dir, existing)

    wants_change = bool(args.skip or args.priority or args.lock)
    reuse = existing is not None and not args.rescan
    intake_path = None
    if not (reuse and wants_change):
        doc_config, intake_path = resolve_intake(args, sdlc_dir, project_root, provisional)

    if reuse and not wants_change:
        if args.json:
            emit_json(catalog_json(existing, provisional))
        else:
            print_existing(existing, catalog_path)
        sys.exit(0)

    scanned = not reuse
    if scanned:
        catalog = scan_catalog(doc_config, intake_path, project_root, args, provisional)
        if existing:
            carry_over_decisions(existing, catalog)
    else:
        catalog = existing

    try:
        changed = apply_decisions(catalog, args.skip, args.priority)
    except Refusal as refusal:
        fail(str(refusal))
    lock_changed = apply_lock(catalog) if args.lock else False

    if catalog_path and (scanned or changed or lock_changed):
        write_catalog(catalog_path, catalog)

    if args.json:
        emit_json(catalog_json(catalog, provisional))
        return
    if scanned:
        print_summary(catalog, intake_path)
        if catalog_path:
            print(f"Catalog written to: {catalog_path}")
            print("Next: Claude will generate per-document summaries during Phase 0 Step 0c.")
        else:
            print("Provisional catalog: nothing was written and the DOC-NNN ids are not stable.")
            print("Run /sprd-setup, then intake again, to get a project catalog.")
    print_changes(args, catalog, lock_changed)


if __name__ == "__main__":
    main()
