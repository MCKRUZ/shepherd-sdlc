"""The document registry and the session-start index, built from the catalogue and the summaries.

`intake_documents.py --registry` calls `build()`. Step 6 of /sprd-intake is bookkeeping once the
catalogue and the summaries exist: which documents there are, how big, what each is about, and a
condensed index that fits a token budget. This does that and nothing else. Topic clusters and the
cross-reference map are judgment and are left exactly as the template (or a person) has them.

Rules that matter:
  * The catalogue is read, never written.
  * An existing registry is edited in place: only the two gathered sections and the `Generated:` line
    change; every other byte, including the file's line endings, is kept.
  * The index never loses a document id. It is trimmed in the command's own order (topic clusters,
    then one-line descriptions) and, if the ids alone are over budget, written in full and reported.
  * A missing summary reads as missing ("(not yet summarised)"), never as an empty row.
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "phases" / "00-discovery" / "document-registry.md"
REGISTRY_REL = Path("artifacts") / "00-discovery" / "document-registry.md"
INDEX_REL = Path("context") / "intake" / "index.md"
SUMMARY_HEADING = "## Document Corpus Summary"
INDEX_HEADING = "## Document Index"
CLUSTER_HEADING = "## Topic Clusters"
NOT_SUMMARISED = "(not yet summarised)"
KEY_TOPICS_CAP = 80
DESCRIPTION_CAPS = (120, 80, 40)
UNFILLED = "${"


# --- reading the summaries --------------------------------------------------------------------

def find_summary(folder: Path, doc_id: str) -> dict | None:
    """The summary written for `doc_id`, or None when there is none or it is still the template."""
    for path in sorted(folder.glob(f"{doc_id}-*.md")):
        text = path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
        if UNFILLED in text:
            return None
        return {"file": path.name, "scope": _scope(text), "overview": _first_sentence(_overview(text))}
    return None


def _field(text: str, label: str) -> str:
    match = re.search(rf"^\s*[-*]\s*\*\*{re.escape(label)}:\*\*\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _scope(text: str) -> str:
    return _field(text, "Scope")


def _overview(text: str) -> str:
    match = re.search(r"^## Document Overview\s*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return " ".join(match.group(1).split()) if match else ""


def _first_sentence(text: str) -> str:
    match = re.match(r"(.+?[.!?])(\s|$)", text)
    return match.group(1) if match else text


# --- the catalogue ----------------------------------------------------------------------------

def ordered_documents(catalog: dict) -> list[dict]:
    """Priority order first, then the rest by id."""
    docs = {d["doc_id"]: d for d in catalog.get("documents", [])}
    first = [docs[i] for i in catalog.get("priority_order", []) if i in docs]
    rest = sorted((d for i, d in docs.items() if i not in set(catalog.get("priority_order", []))), key=lambda d: d["doc_id"])
    return first + rest


def _filename(doc: dict) -> str:
    return doc.get("filename") or str(doc.get("source_path", "")).replace("\\", "/").rsplit("/", 1)[-1]


def type_breakdown(docs: list[dict]) -> str:
    counts: dict[str, int] = {}
    for doc in docs:
        counts[doc.get("type", "unknown")] = counts.get(doc.get("type", "unknown"), 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ", ".join(f"{name}: {n}" for name, n in ranked) or "none"


# --- the registry's two gathered sections -----------------------------------------------------

def corpus_section(catalog: dict, docs: list[dict]) -> list[str]:
    total = sum(int(d.get("estimated_tokens") or 0) for d in docs)
    return [
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Documents | {len(docs)} |",
        f"| Total Estimated Tokens | {total} |",
        f"| File Types | {type_breakdown(docs)} |",
        f"| Index Budget | {catalog.get('index_budget_tokens', 5000)} tokens |",
    ]


def index_section(docs: list[dict], skipped: set[str], summaries: dict[str, dict | None]) -> list[str]:
    rows = [
        "| ID | Filename | Type | Est. Tokens | Key Topics | Summary |",
        "|----|----------|------|-------------|------------|---------|",
    ]
    for doc in docs:
        doc_id, summary = doc["doc_id"], summaries.get(doc["doc_id"])
        if doc_id in skipped:
            topics = "(skipped)"
        else:
            topics = (summary["scope"][:KEY_TOPICS_CAP].rstrip() or "—") if summary else "—"
        link = f"[Summary](../../context/intake/{summary['file']})" if summary else NOT_SUMMARISED
        rows.append(f"| {doc_id} | {_filename(doc)} | {doc.get('type', '')} | {doc.get('estimated_tokens', '')} | {topics} | {link} |")
    return rows


def replace_section(lines: list[str], heading: str, body: list[str]) -> bool:
    """Replace what sits under `heading` (up to the next `## `) in `lines`; False if there is no such heading."""
    try:
        start = lines.index(heading)
    except ValueError:
        return False
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    lines[start + 1:end] = ["", *body, ""]
    return True


def _refresh_generated(lines: list[str], stamp: str) -> None:
    for i, line in enumerate(lines):
        if line.startswith("Generated:"):
            lines[i] = f"Generated: {stamp}"
            return


# --- topic clusters, as a person left them ----------------------------------------------------

def read_clusters(registry_lines: list[str]) -> list[tuple[str, str, str]]:
    """Filled rows of the registry's Topic Clusters table (name, documents, description)."""
    try:
        start = registry_lines.index(CLUSTER_HEADING)
    except ValueError:
        return []
    end = next((i for i in range(start + 1, len(registry_lines)) if registry_lines[i].startswith("## ")), len(registry_lines))
    rows = []
    for line in registry_lines[start + 1:end]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3 or cells[0] in ("Cluster", "") or set(cells[0]) <= set("-: ") or any(UNFILLED in c for c in cells):
            continue
        rows.append((cells[0], cells[1], cells[2]))
    return rows


# --- the index --------------------------------------------------------------------------------

def _index_text(header: list[str], lines: list[str], clusters: list[tuple[str, str, str]]) -> str:
    out = [*header, "", *lines]
    if clusters:
        out += ["", "## Topic Clusters", *(f"- {name}: {docs} — {desc}" for name, docs, desc in clusters)]
    return "\n".join(out) + "\n"


def build_index(
    docs: list[dict], skipped: set[str], summaries: dict[str, dict | None],
    clusters: list[tuple[str, str, str]], catalog: dict, stamp: str, estimate: Callable[[str], int],
) -> dict:
    """The index text trimmed to the budget in the command's own order, and what was done to fit."""
    active = [d for d in docs if d["doc_id"] not in skipped]
    budget = int(catalog.get("index_budget_tokens", 5000))
    total = sum(int(d.get("estimated_tokens") or 0) for d in active)
    header = [
        "# Document Index", f"Generated: {stamp}",
        f"{len(active)} documents (~{total} estimated tokens). Full detail: .sdlc/{REGISTRY_REL.as_posix()}",
    ]

    def lines(cap: int | None) -> list[str]:
        out = []
        for doc in active:
            summary = summaries.get(doc["doc_id"])
            head = f"- {doc['doc_id']} · {_filename(doc)} · {doc.get('type', '')}"
            if cap == 0:
                out.append(head)
                continue
            text = summary["overview"] if summary else "no summary yet"
            if cap is not None and len(text) > cap:
                text = text[:cap].rstrip() + "..."
            out.append(f"{head} — {text}")
        return out

    trimmed: list[str] = []
    text = _index_text(header, lines(None), clusters)
    if estimate(text) > budget and clusters:
        trimmed.append("topic clusters dropped")
        text = _index_text(header, lines(None), [])
    for cap in (*DESCRIPTION_CAPS, 0):
        if estimate(text) <= budget:
            break
        trimmed.append("descriptions removed" if cap == 0 else f"descriptions shortened to {cap}")
        text = _index_text(header, lines(cap), [])
    tokens = estimate(text)
    return {"text": text, "tokens": tokens, "budget": budget, "within_budget": tokens <= budget, "trimmed": trimmed}


# --- the whole thing --------------------------------------------------------------------------

def _read_lines(path: Path) -> tuple[list[str], str]:
    raw = path.read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n").split("\n"), "\r\n" if "\r\n" in raw else "\n"


def _new_registry_lines(catalog: dict, stamp: str) -> list[str]:
    text = TEMPLATE.read_text(encoding="utf-8").replace("\r\n", "\n")
    for key, value in (("${TIMESTAMP}", stamp), ("${INTAKE_PATH}", str(catalog.get("intake_path", ""))),
                       ("${INDEX_BUDGET_TOKENS}", str(catalog.get("index_budget_tokens", 5000)))):
        text = text.replace(key, value)
    return text.split("\n")


def build(sdlc_dir: Path, catalog: dict, estimate: Callable[[str], int], now: datetime | None = None) -> dict:
    """Write the registry and the index under `sdlc_dir`; return the facts for the report."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    docs = ordered_documents(catalog)
    skipped = set(catalog.get("skipped", []))
    summaries = {d["doc_id"]: find_summary(sdlc_dir / "context" / "intake", d["doc_id"]) for d in docs}
    warnings: list[str] = []

    registry_path = sdlc_dir / REGISTRY_REL
    created = not registry_path.exists()
    lines, newline = (_new_registry_lines(catalog, stamp), "\n") if created else _read_lines(registry_path)
    for heading, body in ((SUMMARY_HEADING, corpus_section(catalog, docs)), (INDEX_HEADING, index_section(docs, skipped, summaries))):
        if not replace_section(lines, heading, body):
            warnings.append(f"the registry has no '{heading}' heading, so that section was left alone")
    _refresh_generated(lines, stamp)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_bytes(newline.join(lines).encode("utf-8"))

    index = build_index(docs, skipped, summaries, read_clusters(lines), catalog, stamp, estimate)
    index_path = sdlc_dir / INDEX_REL
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(index["text"].encode("utf-8"))

    active = [d["doc_id"] for d in docs if d["doc_id"] not in skipped]
    missing = [i for i in active if summaries.get(i) is None]
    return {
        "registry": f".sdlc/{REGISTRY_REL.as_posix()}",
        "index": f".sdlc/{INDEX_REL.as_posix()}",
        "documents": len(docs),
        "summarised": len(active) - len(missing),
        "missing_summaries": missing,
        "index_tokens": index["tokens"],
        "index_budget": index["budget"],
        "index_within_budget": index["within_budget"],
        "trimmed": index["trimmed"],
        "registry_created": created,
        "warnings": warnings,
    }


def format_report(result: dict) -> str:
    lines = [
        "Registry and index written",
        f"  Registry: {result['registry']}" + (" (created)" if result["registry_created"] else " (updated)"),
        f"  Index:    {result['index']} (~{result['index_tokens']} of {result['index_budget']} tokens)",
        f"  Documents: {result['documents']}, summarised: {result['summarised']}",
    ]
    if result["missing_summaries"]:
        lines.append(f"  Not yet summarised: {', '.join(result['missing_summaries'])}")
    if result["trimmed"]:
        lines.append(f"  Trimmed to fit: {'; '.join(result['trimmed'])}")
    if not result["index_within_budget"]:
        lines.append("  The index is over its budget even with ids alone; it was written in full.")
    lines += [f"  Warning: {w}" for w in result["warnings"]]
    return "\n".join(lines)
