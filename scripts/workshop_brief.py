"""Assemble the one-page workshop brief from a person's selections (the mechanical half of /sprd-brief).

/sprd-brief is a curated command: the discovery-analyst proposes contradictions and questions, a
person chooses what makes the page, and only then is the brief drafted. This script is that last
step. It FILLS `templates/phases/00-discovery/workshop-brief.md` with what it is handed and never
invents content: the prose claims for "What the documents say" are supplied by the caller (each
with its DOC-NNN), and every contradiction and question comes verbatim from the analyst's own
`contradiction-list.md` / `question-list.md`. It never calls a model.

Refusals exit 1 with a one-line `Error:` on stderr and write nothing: an unknown CON-NN / Q-NN,
more than 5 contradictions or 12 on-page questions (the one-page rule), a claim without a DOC-NNN
(the template's "no orphan facts" rule), a required input that was not supplied, a placeholder
that would be left unfilled, or an existing brief without --force. Usage errors exit 2.

A selected question routed `pre-workshop` is not placed on the page (those are emailed before the
workshop); it is reported under `questions.emailed_instead`. One routed `interview` is refused:
it is neither in the room nor emailed.

The template's HARD RULES comment addresses the person drafting. Its rules are enforced here (page
limits, DOC-NNN on every claim, questions-only lint) or by the command's curation gate, so the
comment is left out of the built brief. Every other template comment is kept, as in the shipped
filled example.

Standalone or Workflow:
  - Workflow:   --state .sdlc/state.yaml  (reads/writes <state.parent>/artifacts/00-discovery/)
  - Standalone: --repo <root> with no .sdlc/state.yaml, plus --contradictions-file /
                --questions-file / --registry-file (and optionally --output). DOC-NNN ids are then
                provisional and the build says so in `notes`.

Output is deterministic (no timestamps) and keeps the template's line-ending convention.
"""

import argparse
import json
import re
import sys
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "phases" / "00-discovery"
TEMPLATE_PATH = TEMPLATES / "workshop-brief.md"
QUESTION_TEMPLATE_PATH = TEMPLATES / "question-list.md"
DISCOVERY = Path("artifacts") / "00-discovery"

MAX_CONTRADICTIONS = 5
MAX_QUESTIONS = 12
DECISION_RANGE = (3, 5)
LOAD_BEARING_RANGE = (3, 5)
LOGISTICS_KEYS = ("client_name", "date_time_location", "duration", "attendees", "facilitator")

DOC_REF = re.compile(r"^DOC-\d{3,}\b")
PLACEHOLDER = re.compile(r"\$\{[^}]*\}")
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
FIELD = re.compile(r"^- \*\*(.+?):\*\*\s*(.*)$")
SOURCE_KEY = re.compile(r"^Source ([AB])\s*[—–-]+\s*(.+)$")
LIST_ITEM = re.compile(r"^(?:- |\d+\. )")
TRAILING_ID = re.compile(r"\s*\((?:Q|CON)-\d+\)\s*$")


class BriefError(Exception):
    """A refusal: reported as `Error: <message>` on stderr, exit 1, nothing written."""


# --- Parsing the analyst's documents ---

def read_text(path: Path, what: str) -> str:
    if not path.is_file():
        raise BriefError(f"{what} not found: {path}")
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return fh.read().replace("\r\n", "\n")


def fields_of(body: list[str]) -> dict[str, str]:
    out = {}
    for line in body:
        m = FIELD.match(line)
        if m:
            out[m.group(1).strip()] = COMMENT.sub("", m.group(2)).strip()
    return out


def parse_contradictions(text: str) -> list[dict]:
    entries, current = [], None
    for line in text.split("\n"):
        m = re.match(r"^### (CON-\d+):\s*(.*)$", line)
        if m:
            current = {"id": m.group(1), "title": m.group(2).strip(), "body": []}
            entries.append(current)
        elif line.startswith("#"):
            current = None
        elif current is not None:
            current["body"].append(line)
    for e in entries:
        f = fields_of(e.pop("body"))
        e["severity"] = f.get("Severity", "")
        e["question"] = f.get("The question for the room", "")
        e["sources"] = {}
        for key, value in f.items():
            sm = SOURCE_KEY.match(key)
            if sm:
                e["sources"][sm.group(1)] = (sm.group(2).strip(), value.strip().strip('"“”').strip())
    return entries


def parse_questions(text: str) -> list[dict]:
    entries, current, block = [], None, ""
    for line in text.split("\n"):
        bm = re.match(r"^### Block:\s*(.+)$", line)
        qm = re.match(r"^#### (Q-\d+):\s*(.*)$", line)
        if bm:
            block, current = bm.group(1).strip(), None
        elif qm:
            current = {"id": qm.group(1), "question": qm.group(2).strip(), "block": block, "body": []}
            entries.append(current)
        elif line.startswith("#"):
            current = None
        elif current is not None:
            current["body"].append(line)
    for e in entries:
        e["route"] = fields_of(e.pop("body")).get("Route", "").lower()
    return entries


def parse_registry(text: str) -> list[dict]:
    """Rows of the Document Index table, found by header text (ID + Filename), not position."""
    lines, rows, columns = text.split("\n"), [], None
    for line in lines:
        if not line.strip().startswith("|"):
            if rows:
                break
            columns = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        lowered = [c.lower() for c in cells]
        if columns is None:
            if "id" in lowered and "filename" in lowered:
                columns = lowered
            continue
        if re.match(r"^:?-+:?$", cells[0]) or "${" in line:
            continue
        row = dict(zip(columns, cells))
        if re.match(r"^DOC-\d+$", row.get("id", "")):
            rows.append({"id": row["id"], "filename": row.get("filename", ""),
                         "topics": row.get("key topics", "")})
    return rows


def number_of(identifier: str, prefix: str) -> int | None:
    m = re.match(rf"^{prefix}-(\d+)$", identifier.strip().upper())
    return int(m.group(1)) if m else None


def lookup(selection: str, entries: list[dict], prefix: str, what: str) -> list[dict]:
    """The entries named by a comma-separated selection, in the source document's order."""
    by_number = {number_of(e["id"], prefix): e for e in entries}
    wanted = {}
    for raw in filter(None, (s.strip() for s in selection.split(","))):
        n = number_of(raw, prefix)
        if n is None or n not in by_number:
            raise BriefError(f"unknown {what} id: {raw}")
        wanted[n] = by_number[n]
    return [e for e in entries if number_of(e["id"], prefix) in wanted]


# --- Inputs supplied by the caller ---

def load_json_arg(value: str, flag: str):
    try:
        if value.lstrip().startswith(("[", "{")):
            return json.loads(value)
        with open(value, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        raise BriefError(f"{flag} is neither valid JSON nor a readable JSON file: {e}")


def one_line(value) -> str:
    return " ".join(str(value).split())


def validate_logistics(raw) -> dict:
    if not isinstance(raw, dict):
        raise BriefError("--logistics-json must be a JSON object")
    missing = [k for k in LOGISTICS_KEYS if not raw.get(k)]
    if missing:
        raise BriefError("--logistics-json is missing: " + ", ".join(missing))
    people = []
    for a in raw["attendees"] if isinstance(raw["attendees"], list) else []:
        name = one_line(a.get("name", "")) if isinstance(a, dict) else ""
        if not name:
            raise BriefError("--logistics-json: every attendee needs a name")
        role = one_line(a.get("role", ""))
        people.append(f"{name} ({role})" if role else name)
    if not people:
        raise BriefError("--logistics-json: attendees must be a non-empty list of {name, role}")
    return {"CLIENT_NAME": one_line(raw["client_name"]),
            "DATE_TIME_LOCATION": one_line(raw["date_time_location"]),
            "DURATION": one_line(raw["duration"]),
            "ATTENDEES_WITH_ROLES": ", ".join(people),
            "POD_LEAD_NAME": one_line(raw["facilitator"])}


def validate_claims(raw) -> list[str]:
    if not isinstance(raw, list):
        raise BriefError("--claims-json must be a JSON list")
    lines = []
    for i, c in enumerate(raw, 1):
        text = one_line(c.get("text", "")) if isinstance(c, dict) else ""
        ref = one_line(c.get("doc_ref", "")) if isinstance(c, dict) else ""
        if not text:
            raise BriefError(f"claim {i} has no text")
        if not DOC_REF.match(ref):
            raise BriefError(f"claim {i} has no DOC-NNN reference (every claim must cite its document)")
        lines.append(f"- {text} ({ref})")
    return lines


def validate_decisions(raw) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(d, str) and d.strip() for d in raw):
        raise BriefError("--decisions-json must be a JSON list of non-empty strings")
    return [one_line(d) for d in raw]


# --- Rendering ---

def contradiction_line(n: int, e: dict) -> str:
    for side in "AB":
        if side not in e["sources"] or not e["sources"][side][1]:
            raise BriefError(f"{e['id']} has no usable Source {side} in the contradiction list")
    if not e["question"]:
        raise BriefError(f"{e['id']} has no 'The question for the room' in the contradiction list")
    (ref_a, said_a), (ref_b, said_b) = e["sources"]["A"], e["sources"]["B"]
    said_b = one_line(said_b)
    stop = "" if said_b[-1] in ".!?" else "."
    return (f'{n}. {ref_a} says "{one_line(said_a)}"; {ref_b} says "{said_b}"{stop} '
            f"**{one_line(e['question'])}** ({e['id']})")


def block_order() -> list[str]:
    text = read_text(QUESTION_TEMPLATE_PATH, "question-list template")
    return [m.group(1).strip() for m in re.finditer(r"^### Block:\s*(.+)$", text, re.MULTILINE)]


def question_lines(on_page: list[dict]) -> list[str]:
    order = block_order()
    rank = {b: i for i, b in enumerate(order)}
    ordered = sorted(enumerate(on_page), key=lambda p: (rank.get(p[1]["block"], len(order)), p[0]))
    return [f"- **{q['block'] or 'Other'}:** {one_line(q['question'])} ({q['id']})" for _, q in ordered]


def split_sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    sections = [("", [])]
    for line in lines:
        if line.startswith("## "):
            sections.append((line, []))
        else:
            sections[-1][1].append(line)
    return sections


def leading_comment(body: list[str]) -> list[str]:
    """The section's guidance comment, which opens the body (possibly over several lines)."""
    start = next((i for i, l in enumerate(body) if l.strip()), None)
    if start is None or not body[start].lstrip().startswith("<!--"):
        return []
    end = next((i for i in range(start, len(body)) if "-->" in body[i]), start)
    return body[start:end + 1]


def generated_body(body: list[str], generated: list[str]) -> list[str]:
    out = [""] + leading_comment(body)
    if out[-1] != "":
        out.append("")
    return out + (generated + [""] if generated else [])


def pointer(body: list[str], text: str) -> list[str]:
    return generated_body(body, [text]) if not any(l.startswith("See `") for l in body) else body


def decision_body(body: list[str], supplied: list[str]) -> tuple[list[str], list[str]]:
    standing = [l for l in body if re.match(r"^\d+\. ", l) and "${" not in l]
    numbered = [f"{len(standing) + i}. {d}" for i, d in enumerate(supplied, 1)]
    return generated_body(body, standing + numbered), standing


def lint_brief(lines: list[str], standing: list[str]) -> list[dict]:
    """Advisory: list items under the two question-only sections that do not end in `?`."""
    findings, watching, in_comment = [], False, False
    for n, line in enumerate(lines, 1):
        if line.startswith("## "):
            watching = line[3:].strip() in ("What nobody has written down", "Decisions we need from the room")
            in_comment = False
            continue
        if "<!--" in line:
            in_comment = "-->" not in line
            continue
        if in_comment:
            in_comment = "-->" not in line
            continue
        if watching and LIST_ITEM.match(line) and line not in standing:
            if not TRAILING_ID.sub("", line).rstrip().endswith("?"):
                findings.append({"line": n, "message": f"does not end in a question mark: {line.strip()}"})
    return findings


def render(template: str, *, logistics: dict, load_bearing: list[dict], total_documents: int,
           claims: list[str], contradictions: list[str], questions: list[str],
           decisions: list[str], pointers: dict[str, str]) -> tuple[str, list[dict]]:
    eol = "\r\n" if template.count("\r\n") * 2 > template.count("\n") else "\n"
    text = template.replace("\r\n", "\n")
    text = re.sub(r"<!-- HARD RULES:.*?-->\n", "", text, flags=re.DOTALL)
    clause = "; ".join(f"{d['id']} ({d['filename']}{': ' + d['topics'] if d['topics'] else ''})" for d in load_bearing)
    tokens = {**logistics, "TOTAL_DOCUMENTS": str(total_documents),
              "TOP_3_5_DOCS_WITH_IDS_AND_ONE_CLAUSE_EACH": clause}
    text = re.sub(r"\$\{([A-Z_0-9]+)\}", lambda m: tokens.get(m.group(1), m.group(0)), text)

    fills = {"What the documents say": claims, "Where the documents disagree": contradictions,
             "What nobody has written down": questions}
    out, standing = [], []
    for heading, body in split_sections(text.split("\n")):
        name = heading[3:].strip()
        if name in fills:
            body = generated_body(body, fills[name])
        elif name == "Decisions we need from the room":
            body, standing = decision_body(body, decisions)
        elif name.startswith("Appendix") and name in pointers and pointers[name]:
            body = pointer(body, pointers[name])
        out += ([heading] if heading else []) + body
    while out and out[-1] == "":
        out.pop()
    out.append("")
    return eol.join(out), lint_brief(out, standing)


# --- Orchestration ---

def resolve_paths(args) -> dict:
    """Where each input lives and where the brief goes; `workflow` is true only with a real state.yaml."""
    if args.state:
        state = Path(args.state)
        if not state.is_file():
            raise BriefError(f"state file not found: {state}")
        sdlc, workflow = state.parent, True
    else:
        sdlc = Path(args.repo) / ".sdlc"
        workflow = (sdlc / "state.yaml").is_file()
    folder = sdlc / DISCOVERY
    paths = {key: Path(getattr(args, f"{key}_file") or folder / name) for key, name in
             (("contradictions", "contradiction-list.md"), ("questions", "question-list.md"),
              ("registry", "document-registry.md"))}
    explicit = [Path(getattr(args, f"{k}_file")) for k in ("registry", "questions", "contradictions")
                if getattr(args, f"{k}_file")]
    if args.output:
        paths["output"] = Path(args.output)
    elif explicit and not workflow:
        paths["output"] = explicit[0].parent / "workshop-brief.md"
    else:
        paths["output"] = folder / "workshop-brief.md"
    return {**paths, "workflow": workflow}


def select_questions(entries: list[dict], selection: str) -> tuple[list[dict], list[dict]]:
    """Split the chosen questions into those for the page and those to email instead."""
    on_page, emailed = [], []
    for q in lookup(selection, entries, "Q", "question"):
        route = q["route"]
        if route.startswith("pre"):
            emailed.append(q)
        elif route.startswith("interview"):
            raise BriefError(f"{q['id']} is routed to interview: it belongs neither on the page nor in an email")
        elif route and not route.startswith("workshop"):
            raise BriefError(f"{q['id']} has an unrecognised Route: {route}")
        else:
            on_page.append(q)
    return on_page, emailed


def appendix_pointers(contradictions, questions, registry) -> dict[str, str]:
    """A one-line pointer for each appendix whose source document was read (never inlined)."""
    where = "in the discovery artifacts folder"
    out = {"Appendix C: Document registry": f"See `document-registry.md` {where} ({len(registry)} documents)."}
    if questions is not None:
        workshop = sum(1 for q in questions if not q["route"] or q["route"].startswith("workshop"))
        out["Appendix A: Full question list"] = (
            f"See `question-list.md` {where} ({len(questions)} questions, {workshop} routed to the workshop).")
    if contradictions is not None:
        blocking = sum(1 for c in contradictions if c["severity"] == "blocks-outcome")
        out["Appendix B: Contradiction detail"] = (
            f"See `contradiction-list.md` {where} ({len(contradictions)} contradictions, {blocking} blocks-outcome).")
    return out


def required_inputs(args) -> tuple[dict, list[str], list[str]]:
    for flag, value in (("--logistics-json", args.logistics_json), ("--decisions-json", args.decisions_json),
                        ("--load-bearing", args.load_bearing)):
        if not value:
            raise BriefError(f"{flag} is required")
    claims = validate_claims(load_json_arg(args.claims_json, "--claims-json")) if args.claims_json else []
    return (validate_logistics(load_json_arg(args.logistics_json, "--logistics-json")),
            validate_decisions(load_json_arg(args.decisions_json, "--decisions-json")), claims)


def advisory_notes(args, load_bearing, claims, picked, on_page, standing_decisions, decisions) -> list[str]:
    notes = [] if args.workflow else [
        "DOC-NNN ids are provisional: there is no .sdlc/state.yaml, so they are not locked to an intake catalog."]
    for empty, message in ((claims, "No claims supplied: 'What the documents say' is left empty for the Pod Lead."),
                           (picked, "No contradictions selected: 'Where the documents disagree' is empty."),
                           (on_page, "No workshop questions on the page: 'What nobody has written down' is empty.")):
        if not empty:
            notes.append(message)
    for count, (low, high), what in ((len(load_bearing), LOAD_BEARING_RANGE, "load-bearing documents"),
                                     (standing_decisions + len(decisions), DECISION_RANGE, "decisions")):
        if not low <= count <= high:
            notes.append(f"{count} {what} on the page; the template asks for {low}-{high}.")
    return notes


def build(args) -> dict:
    paths = resolve_paths(args)
    args.workflow = paths["workflow"]
    logistics, decisions, claims = required_inputs(args)

    registry = parse_registry(read_text(paths["registry"], "document registry"))
    if not registry:
        raise BriefError(f"no Document Index table with DOC-NNN rows in {paths['registry']}")
    requested = [i for i in args.load_bearing.split(",") if i.strip()]
    by_number = {number_of(d["id"], "DOC"): d for d in lookup(args.load_bearing, registry, "DOC", "document")}
    load_bearing = [by_number[n] for n in dict.fromkeys(number_of(i, "DOC") for i in requested)]

    parsed = {}
    for key, parse, what, selection in (("contradictions", parse_contradictions, "contradiction list", args.contradictions),
                                        ("questions", parse_questions, "question list", args.questions)):
        if selection or paths[key].is_file():
            parsed[key] = parse(read_text(paths[key], what))
    picked = lookup(args.contradictions, parsed["contradictions"], "CON", "contradiction") if args.contradictions else []
    on_page, emailed = select_questions(parsed["questions"], args.questions) if args.questions else ([], [])
    if len(picked) > MAX_CONTRADICTIONS:
        raise BriefError(f"{len(picked)} contradictions selected; the one-page limit is {MAX_CONTRADICTIONS}")
    if len(on_page) > MAX_QUESTIONS:
        raise BriefError(f"{len(on_page)} questions selected for the page; the one-page limit is {MAX_QUESTIONS}")

    with open(TEMPLATE_PATH, encoding="utf-8", newline="") as fh:
        template = fh.read()
    text, lint = render(
        template, logistics=logistics, load_bearing=load_bearing, total_documents=len(registry), claims=claims,
        contradictions=[contradiction_line(n, c) for n, c in enumerate(picked, 1)],
        questions=question_lines(on_page), decisions=decisions,
        pointers=appendix_pointers(parsed.get("contradictions"), parsed.get("questions"), registry))
    left = sorted(set(PLACEHOLDER.findall(text)))
    if left:
        raise BriefError("the brief would keep unfilled placeholders: " + ", ".join(left))

    out = paths["output"]
    if out.exists() and not args.force:
        raise BriefError(f"{out} already exists; pass --force to overwrite it")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)

    def total(key):
        return len(parsed[key]) if key in parsed else None
    standing = sum(1 for l in template.split("\n") if re.match(r"^\d+\. ", l) and "${" not in l)
    ids = lambda entries: [e["id"] for e in entries]  # noqa: E731
    return {"path": str(out.resolve()),
            "contradictions": {"total": total("contradictions"), "on_page": len(picked), "ids": ids(picked)},
            "questions": {"total": total("questions"), "on_page": len(on_page), "ids": ids(on_page),
                          "emailed_instead": ids(emailed)},
            "claims": len(claims), "load_bearing": ids(load_bearing),
            "provisional_ids": not paths["workflow"], "lint": lint,
            "notes": advisory_notes(args, load_bearing, claims, picked, on_page, standing, decisions)}


def format_report(r: dict) -> str:
    c, q = r["contradictions"], r["questions"]
    count = lambda n: "no data" if n is None else str(n)  # noqa: E731
    lines = ["Workshop Brief Drafted", "======================", f"Brief:           {r['path']}",
             f"Contradictions:  {count(c['total'])} total - {c['on_page']} on the page",
             f"Questions:       {count(q['total'])} total - {q['on_page']} on the page, "
             f"{len(q['emailed_instead'])} routed pre-workshop (email these now)"]
    if q["emailed_instead"]:
        lines.append("Email instead:   " + ", ".join(q["emailed_instead"]))
    lines += [f"Lint (line {f['line']}): {f['message']}" for f in r["lint"]]
    lines += [f"Note: {n}" for n in r["notes"]]
    lines.append("Next: Pod Lead edits, then sends to attendees. The brief is not sent by this command.")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Assemble the workshop brief from a person's selections")
    verbs = parser.add_subparsers(dest="verb", required=True, metavar="{build,candidates}")
    b = verbs.add_parser("build", help="Fill the workshop-brief template with the selections")
    src = b.add_mutually_exclusive_group(required=True)
    src.add_argument("--state", help="Path to .sdlc/state.yaml (workflow mode)")
    src.add_argument("--repo", help="Repo root (standalone when it has no .sdlc/state.yaml)")
    b.add_argument("--contradictions", help="Comma-separated CON-NN ids that make the page (max 5)")
    b.add_argument("--questions", help="Comma-separated Q-NN ids (max 12 on the page)")
    b.add_argument("--decisions-json", help="JSON list (or file) of engagement-specific decisions")
    b.add_argument("--logistics-json", help="JSON object (or file): client_name, date_time_location, "
                                            "duration, attendees [{name, role}], facilitator")
    b.add_argument("--claims-json", help="JSON list (or file) of {text, doc_ref}; doc_ref is a DOC-NNN")
    b.add_argument("--load-bearing", help="Comma-separated DOC-NNN ids of the load-bearing documents")
    b.add_argument("--contradictions-file", help="Override path to contradiction-list.md")
    b.add_argument("--questions-file", help="Override path to question-list.md")
    b.add_argument("--registry-file", help="Override path to document-registry.md")
    b.add_argument("--output", help="Where to write the brief (default: the discovery artifacts folder)")
    b.add_argument("--force", action="store_true", help="Overwrite an existing brief")
    b.add_argument("--json", action="store_true", help="Emit the result as one JSON document")
    c = verbs.add_parser("candidates", help="Report, read-only, what the brief can be built from (for a selection form)")
    csrc = c.add_mutually_exclusive_group(required=True)
    csrc.add_argument("--state", help="Path to .sdlc/state.yaml (workflow mode)")
    csrc.add_argument("--repo", help="Repo root (standalone when it has no .sdlc/state.yaml)")
    c.add_argument("--contradictions-file", help="Override path to contradiction-list.md")
    c.add_argument("--questions-file", help="Override path to question-list.md")
    c.add_argument("--registry-file", help="Override path to document-registry.md")
    c.add_argument("--json", action="store_true", help="Emit the result as one JSON document")
    c.set_defaults(output=None)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.verb == "candidates":
            # Run as a script this module is `__main__`; without this, brief_candidates' own
            # `import workshop_brief` loads a second copy whose BriefError is not the one caught below.
            sys.modules.setdefault("workshop_brief", sys.modules[__name__])
            import brief_candidates
            result = brief_candidates.report(args)
            print(json.dumps(result, indent=2) if args.json else brief_candidates.format_report(result))
            sys.exit(0)
        result = build(args)
    except BriefError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(result, indent=2) if args.json else format_report(result))
    sys.exit(0)


if __name__ == "__main__":
    main()
