"""What a person chooses from when curating the workshop brief (`workshop_brief.py candidates`).

Read-only, and built from `workshop_brief.py`'s own parsers: the contradiction list, the question list and
the document registry that `build` selects from. A selection form shows exactly what `build` will accept,
so the two cannot disagree about what an entry is. Nothing is written, and the limits come from the
script's constants rather than being retyped anywhere.

`recommended` is the `/sprd-brief` curation step's own rule and nothing more: a contradiction whose severity
blocks the outcome or shapes the design is pre-ticked; the person changes it.

A missing or empty input is reported as `has_data: false` with a note saying what to run next. It is never an
error and never a zero count: a person opening the form before the analysis has run should be told what to do.
"""

import re

import workshop_brief as wb

RECOMMENDED_SEVERITIES = ("blocks-outcome", "shapes-design")

INPUTS = (
    # key, file name, parser, the entries it should hold, what to run when it is missing
    ("contradictions", "contradiction-list.md", wb.parse_contradictions, "CON-NN contradictions",
     "run the document analysis first"),
    ("questions", "question-list.md", wb.parse_questions, "Q-NN questions", "run the document analysis first"),
    ("registry", "document-registry.md", wb.parse_registry, "DOC-NNN documents",
     "run /sprd-intake --registry first"),
)


def _sources(entry: dict) -> list[dict]:
    return [{"side": side, "document": entry["sources"][side][0], "quote": entry["sources"][side][1]}
            for side in ("A", "B") if side in entry["sources"]]


def _contradiction(entry: dict) -> dict:
    return {"id": entry["id"], "title": entry["title"], "severity": entry["severity"],
            "question": entry["question"], "sources": _sources(entry),
            "recommended": entry["severity"] in RECOMMENDED_SEVERITIES}


def _question(entry: dict) -> dict:
    return {"id": entry["id"], "question": entry["question"], "block": entry["block"], "route": entry["route"]}


def _standing_decisions() -> int:
    """The numbered, placeholder-free decisions the template already carries (the build counts the same way)."""
    with open(wb.TEMPLATE_PATH, encoding="utf-8", newline="") as fh:
        template = fh.read().replace("\r\n", "\n")
    return sum(1 for line in template.split("\n") if re.match(r"^\d+\. ", line) and "${" not in line)


def report(args) -> dict:
    paths = wb.resolve_paths(args)
    parsed, notes = {}, []
    for key, name, parse, what, next_step in INPUTS:
        path = paths[key]
        if not path.is_file():
            parsed[key] = []
            notes.append(f"{name} not found: {next_step}.")
            continue
        parsed[key] = parse(wb.read_text(path, name))
        if not parsed[key]:
            notes.append(f"{name} holds no {what}.")
    return {
        "has_data": not notes,
        "notes": notes,
        "contradictions": [_contradiction(e) for e in parsed["contradictions"]],
        "questions": [_question(e) for e in parsed["questions"]],
        "documents": parsed["registry"],
        "limits": {"contradictions": wb.MAX_CONTRADICTIONS, "questions": wb.MAX_QUESTIONS,
                   "decisions": list(wb.DECISION_RANGE), "load_bearing": list(wb.LOAD_BEARING_RANGE)},
        "standing_decisions": _standing_decisions(),
        "existing_brief": paths["output"].is_file(),
        "provisional_ids": not paths["workflow"],
    }


def format_report(r: dict) -> str:
    limits = r["limits"]
    lines = ["Workshop brief: what to choose from", "=" * 40]
    lines += [f"No data: {note}" for note in r["notes"]]
    lines.append(f"Contradictions ({len(r['contradictions'])}; limit {limits['contradictions']} on the page):")
    for c in r["contradictions"]:
        lines.append(f"  {c['id']} [{c['severity'] or 'no severity'}]{' recommended' if c['recommended'] else ''}: {c['title']}")
    lines.append(f"Questions ({len(r['questions'])}; limit {limits['questions']} on the page):")
    for q in r["questions"]:
        lines.append(f"  {q['id']} [{q['block']} / {q['route']}]: {q['question']}")
    lines.append(f"Documents ({len(r['documents'])}); name {limits['load_bearing'][0]}-{limits['load_bearing'][1]} as load-bearing:")
    for d in r["documents"]:
        lines.append(f"  {d['id']}: {d['filename']}")
    lines.append(f"Decisions: {r['standing_decisions']} standing; the page takes {limits['decisions'][0]}-{limits['decisions'][1]} in all.")
    if r["existing_brief"]:
        lines.append("A brief already exists; building will ask before replacing it.")
    if r["provisional_ids"]:
        lines.append("Document ids are provisional: there is no project state file.")
    return "\n".join(lines)
