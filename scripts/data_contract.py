"""Summarise a data contract's PII classification (the read-only check behind /sprd-data).

`summary` reads the Fields table of `data-contract.md` and reports how many fields it declares, which
of them are PII, and which have not been classified yet. PII is a risk-tier driver, so when at least
one field is PII the report quotes the line of `risk_model.TAXONOMY` that makes it one. The script
only counts what the document says: a person (or the data-analyst agent) classifies, this just adds
it up the same way every time.

Columns are found by their header text, case-insensitively, never by position, so a contract whose
columns are reordered or which carries extra columns gives the same answer.

Advisory: every path exits 0 except a usage error (exit 2). A missing document, or one with no
recognisable Fields table, reports `has_data: false` with a note and empty lists: a count of zero is
only ever reported alongside real data. Output is deterministic (no timestamps).

Standalone or Workflow:
  - Workflow:   --state .sdlc/state.yaml  (reads <state.parent>/artifacts/02-design/data/data-contract.md)
  - Workflow:   --repo <root>             (reads <root>/.sdlc/artifacts/02-design/data/data-contract.md)
  - Standalone: --doc <path>              (reads that file; needs no .sdlc/, and overrides the above)

Fixed behaviour worth knowing:
  - `yes` / `y` / `true` mean PII; `no` / `n` / `false` mean not. Any case, decoration such as
    **YES** or `YES` ignored.
  - `customer-linked` is the template's value for an INDIRECTLY identifying field (`YES` is directly
    identifying), and the template's own PII summary lists "the YES / customer-linked fields". Both
    count as PII here, so a contract is never reassured that it holds less personal data than it
    does; `indirect_fields` names the customer-linked subset so a reader can tell them apart.
  - A row still holding template placeholders ([field name], [...]) is not a field. A contract with
    nothing but placeholder rows has no data.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import risk_model

DEFAULT_RELATIVE = Path("artifacts") / "02-design" / "data" / "data-contract.md"

PII_YES = {"yes", "y", "true"}
PII_INDIRECT = {"customer-linked", "customer linked", "indirect"}
PII_NO = {"no", "n", "false"}
EMPTY_MARKS = {"", "-", "–", "—"}

PLACEHOLDER_SPAN_RE = re.compile(r"\[[^\]]*\]|<[^>]*>")
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
_FIELD_HEADER_RE = re.compile(r"^(field|field name|name|column)\b")
_PII_ONLY_HEADER_RE = re.compile(r"^pii\??$")
_PII_TAXONOMY_RE = re.compile(r"personal|client data|\bpii\b", re.IGNORECASE)


# --- Table parsing ---

def _split_row(line: str) -> list[str]:
    """Cells of a table row. `\\|` is a literal pipe inside a cell."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [c.strip().replace("\\|", "|") for c in _UNESCAPED_PIPE.split(line)]


def _is_separator(cells: list[str]) -> bool:
    joined = "".join(cells)
    return bool(joined) and set(joined) <= set("-:| ")


def parse_tables(text: str) -> list[list[list[str]]]:
    """Every pipe table in the text as a list of rows (header first, separator dropped)."""
    tables: list[list[list[str]]] = []
    block: list[str] = []
    for raw in text.splitlines() + [""]:
        if raw.lstrip().startswith("|"):
            block.append(raw)
            continue
        if len(block) >= 2:
            rows = [_split_row(b) for b in block]
            if _is_separator(rows[1]):
                tables.append([rows[0]] + rows[2:])
        block = []
    return tables


def is_placeholder_row(cells: list[str]) -> bool:
    """A template example row: more than half its non-empty cells are a [bracketed] or <angle> span."""
    filled = [c for c in cells if c]
    hits = sum(1 for c in filled if PLACEHOLDER_SPAN_RE.search(c))
    return bool(filled) and hits * 2 > len(filled)


def _header_key(cell: str) -> str:
    return re.sub(r"[`*_]", "", cell).strip().lower()


def find_fields_table(tables: list[list[list[str]]]) -> tuple[list[list[str]], int, int] | None:
    """(rows after the header, field-name column, PII column) of the first table that has both."""
    for table in tables:
        keys = [_header_key(c) for c in table[0]]
        name_idx = next((i for i, k in enumerate(keys) if _FIELD_HEADER_RE.match(k)), None)
        pii_idx = next((i for i, k in enumerate(keys) if _PII_ONLY_HEADER_RE.match(k)), None)
        if pii_idx is None:
            pii_idx = next((i for i, k in enumerate(keys) if "pii" in k), None)
        if name_idx is not None and pii_idx is not None and name_idx != pii_idx:
            return table[1:], name_idx, pii_idx
    return None


# --- Classification ---

def _clean(cell: str) -> str:
    return re.sub(r"[`*]", "", cell).strip()


def classify(cell: str) -> str:
    """'yes', 'indirect', 'no', 'empty', 'placeholder' or 'other' for one PII cell."""
    value = _clean(cell)
    if value.lower() in EMPTY_MARKS:
        return "empty"
    if PLACEHOLDER_SPAN_RE.search(value):
        return "placeholder"
    if value.lower() in PII_YES:
        return "yes"
    if value.lower() in PII_INDIRECT:
        return "indirect"
    if value.lower() in PII_NO:
        return "no"
    return "other"


def pii_taxonomy_clause() -> str:
    """The clause of the HIGH tier's `lands_here` that names personal or client data, verbatim.

    `risk_model.TAXONOMY` holds the tier's examples as one comma-separated string, so the PII line is
    the clause of that string that mentions it. If a future edit leaves no clause that does, the whole
    string is quoted rather than inventing one.
    """
    lands_here = risk_model.TAXONOMY["HIGH"]["lands_here"]
    for clause in (c.strip() for c in lands_here.split(",")):
        if _PII_TAXONOMY_RE.search(clause):
            return clause
    return lands_here


def summarise(text: str | None, missing_note: str) -> dict:
    result = {"has_data": False, "notes": [], "field_count": 0, "pii_fields": [], "indirect_fields": [],
              "pii_count": 0, "unclassified": [], "risk_implication": None, "advisory": True}
    if text is None:
        result["notes"].append(missing_note)
        return result

    found = find_fields_table(parse_tables(text))
    if found is None:
        result["notes"].append("no Fields table with a field-name column and a PII column found in the data contract")
        return result

    rows, name_idx, pii_idx = found
    fields = []
    for cells in rows:
        if not any(cells) or is_placeholder_row(cells):
            continue
        name = _clean(cells[name_idx]) if name_idx < len(cells) else ""
        pii = cells[pii_idx] if pii_idx < len(cells) else ""
        fields.append((name or f"(unnamed row {len(fields) + 1})", pii))
    if not fields:
        result["notes"].append("the Fields table holds only template placeholder rows: no fields declared yet")
        return result

    pii_fields, indirect_fields, unclassified, notes = [], [], [], []
    for name, pii in fields:
        kind = classify(pii)
        if kind in ("yes", "indirect"):
            pii_fields.append(name)
            if kind == "indirect":
                indirect_fields.append(name)
        elif kind in ("empty", "placeholder"):
            unclassified.append(name)
        elif kind == "other":
            unclassified.append(name)
            notes.append(f"field '{name}': PII value '{_clean(pii)}' is not yes or no, left unclassified for a person to decide")

    result.update(has_data=True, notes=notes, field_count=len(fields), pii_fields=pii_fields,
                  indirect_fields=indirect_fields, pii_count=len(pii_fields), unclassified=unclassified,
                  risk_implication=pii_taxonomy_clause() if pii_fields else None)
    return result


# --- Document location ---

def resolve_doc(args) -> Path:
    if args.doc:
        return Path(args.doc)
    if args.state:
        return Path(args.state).resolve().parent / DEFAULT_RELATIVE
    return Path(args.repo).resolve() / ".sdlc" / DEFAULT_RELATIVE


def read_document(path: Path) -> tuple[str | None, str]:
    """(text, note-if-missing). Unreadable counts as missing: the check is advisory."""
    if not path.is_file():
        return None, f"data contract not found at {path}"
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace"), ""
    except OSError as e:
        return None, f"data contract could not be read at {path}: {e.strerror or e}"


# --- Output ---

def format_report(result: dict, doc_path: Path) -> str:
    lines = ["Data Contract Summary", "=" * 44, f"Document: {doc_path}"]
    if not result["has_data"]:
        lines += [f"No data: {n}" for n in result["notes"]]
        lines.append("(advisory - nothing to summarise yet)")
        return "\n".join(lines)

    lines.append(f"Fields: {result['field_count']}")
    pii = ", ".join(result["pii_fields"]) or "none"
    lines.append(f"PII fields ({result['pii_count']}): {pii}")
    if result["indirect_fields"]:
        lines.append(f"  of which indirectly identifying (customer-linked): {', '.join(result['indirect_fields'])}")
    if result["unclassified"]:
        lines.append(f"Unclassified ({len(result['unclassified'])}): {', '.join(result['unclassified'])}")
    for note in result["notes"]:
        lines.append(f"Note: {note}")
    if result["risk_implication"]:
        lines.append(f'Risk: PII is a risk-tier driver. The HIGH tier lands "{result["risk_implication"]}".')
    lines.append("(advisory - a person confirms the PII classification)")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarise a data contract's PII classification (advisory, read-only)")
    verbs = parser.add_subparsers(dest="verb", required=True, metavar="{summary}")
    sm = verbs.add_parser("summary", help="Count the contract's fields and PII; quote the risk-tier line when any is PII")
    src = sm.add_mutually_exclusive_group()
    src.add_argument("--state", help="Path to .sdlc/state.yaml (workflow mode)")
    src.add_argument("--repo", help="Project root (standalone mode)")
    sm.add_argument("--doc", help="Path to data-contract.md (overrides the default location; needs no .sdlc/)")
    sm.add_argument("--json", action="store_true", help="Emit the result as one JSON document")
    return parser


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args()
    if not (args.state or args.repo or args.doc):
        parser.error("one of --state, --repo or --doc is required")

    doc_path = resolve_doc(args)
    text, missing_note = read_document(doc_path)
    result = summarise(text, missing_note)
    print(json.dumps(result, indent=2) if args.json else format_report(result, doc_path))
    sys.exit(0)


if __name__ == "__main__":
    main()
