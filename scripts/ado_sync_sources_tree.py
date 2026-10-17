"""The requirements tree's sources for the Boards mirror: outcomes, domains, requirements and epic links (B2-P3b).

Two trees are mirrored and joined by *fulfils* links (design D36, kit K25):

    requirements tree    Outcome <-Related-> Domain -> FR       what must be true
    delivery tree        Epic -> Feature -> Spec                how it gets built

This module reads the first tree out of the repository and says how an epic attaches to it. Everything
is declared in the artifacts and nothing is guessed: an outcome is a `### Dimension N:` of
`success-criteria.md`; a domain is a row of the `| Domain |` Summary Table of `requirements.md` and must
also be a `### <Domain>` heading; a requirement is a `### FR-NNN` and belongs to the domain heading above
it; an epic fulfils the FRs its Epic Summary `FR Link` cell lists. **An epic is never parented under an
FR** (an FR is smaller than an epic, and one epic can span two domains): a single-domain epic parents
under its Domain, a cross-domain epic has no parent and is `Related` to each domain, and every FR it
fulfils is a `Related` link.

  load_outcomes(repo_root)             one row per dimension, its threshold table in fields["description_rows"]
  load_domains(repo_root, cfg=None)    one row per Summary Table domain, its FR ids, its outcome links
  load_requirements(repo_root)         one row per FR, parent_ref = its domain's ref
  domain_of_fr(repo_root)              {"FR-001": "<domain slug>"}
  parse_fr_link(text)                  "FR-001..004, FR-009" -> the five ids
  epic_links(repo_root, row, cfg)      (parent_ref, note, related_refs) for one epic; registered whole as
                                       PARENT_RESOLVERS["epic"], so `projections` carries the fulfils links
  domain_outcomes(cfg, summary_rows)   {domain slug: [outcome id]} from tree.domain_outcomes + an `Outcome` column

A row is a Projection (the keys `ado_sync_sources.projections` documents): `ref`, `kind`, `id`, `title`,
`status`, `fields`, `tags`, `parent_ref`, `parent_note`, `related_refs`, `source_path`, `source_sha`.
`title` is the board title (`Outcome 1 · Turnaround time`, `Order Intake`, `FR-001 · Reject duplicates`);
`status` is always None because State is the board's (the mirror never writes it); `fields` carries the one
work item field every process has, `System.Title` (the board title, cut to 255 characters with a note), by
reference name like every projection, plus what the repository says under neutral keys (`description_rows`,
`fr_ids`, `priority`, `domain`) because which work item field those land on depends on the discovered process,
which a source never sees. A neutral key is never a field op: `ado_sync_model.diff` (and so both patch builders)
pushes reference names only. `notes` says what was left out (a cut title). `source_sha` is the SHA-256 of the
file as stored, CRLF read as LF. A ref is `sdlc:outcome:<n>-<slug>`, `sdlc:domain:<slug>` or `sdlc:fr:<digits>`, and
the row's tag is the ref itself.

A kind whose artifact does not exist yields no rows (the kinds are default-on only when their artifact is
there). An artifact that contradicts itself raises `ValueError` naming the offence — a domain heading with
no Summary Table row, a row with no heading, a stray FR under no domain heading, an epic linking an FR
nobody defined, a duplicate id — because pushing a half-understood tree to a board is worse than stopping.
The one tolerated shape is a *flat* `requirements.md` (the shipped template: `### FR-NNN` sections, no
Summary Table, no domain headings): its FRs simply have no parent and no domain item exists.

The module reads files and writes nothing; it spawns nothing and imports no `ado_*` module. On import it
registers its loaders with `ado_sync_sources` (`SOURCES["outcome"|"domain"|"requirement"]`,
`PARENT_RESOLVERS["epic"]`) — extend-only: it sets its own four keys and touches no other. If that module,
or either of its two tables, does not exist yet, nothing is registered and `_register()` may be called again.
"""

import functools
import hashlib
import importlib
import re
import sys
import unicodedata
from pathlib import Path

import yaml

import document_shape
from artifact_lineage import ID_RE

__all__ = ["load_outcomes", "load_domains", "load_requirements", "domain_of_fr", "parse_fr_link", "epic_links",
           "domain_outcomes"]

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SUCCESS_REL = ".sdlc/artifacts/00-discovery/success-criteria.md"
REQUIREMENTS_REL = ".sdlc/artifacts/01-requirements/requirements.md"
EPICS_REL = ".sdlc/artifacts/01-requirements/epics.md"
_SHAPES = {SUCCESS_REL: "templates/phases/00-discovery/success-criteria.shape.yaml",
           REQUIREMENTS_REL: "templates/phases/01-requirements/requirements.shape.yaml"}

_FR_HEADING_RE = re.compile(r"^FR-(\d+)\b[\s:.–—-]*(.*)$")
_H3_RE = re.compile(r"^### +(.*?)\s*$")
_DIMENSION_RE = re.compile(r"^Dimension\s+(\d+)[\s:.)–—-]*(.*)$")
_PRIORITY_LINE_RE = re.compile(r"^\*\*Priority:\*\*[ \t]*(.*)$", re.MULTILINE)
_PRIORITY_RE = re.compile(r"\bP([0-3])\b")
_FR_LINK_RE = re.compile(
    r"\bFR-(\d+)(?:\s*(?:\.\.\.?|…|–|—|-|\bto\b)\s*(?:FR-)?(\d+))?", re.IGNORECASE)
_RANGE_LIMIT = 500  # a typo such as FR-001..9999 must not become ten thousand links
_MAX_TITLE = 255     # the work item title limit (as `ado_sync_sources` cuts a spec's or an epic's title)
_TITLE = "System.Title"
_NONE_WORDS = frozenset({"", "-", "–", "—", "n/a", "na", "none", "tbd"})


# --- reading ----------------------------------------------------------------------------------------------

def _read(repo_root, rel: str) -> tuple[str, str] | None:
    """(text with LF newlines, sha256 of the stored bytes with CRLF read as LF), or None when the file is not there.
    A CRLF checkout of a commit (Git for Windows' autocrlf default) hashes as the LF one does, so a ledger written on
    one machine does not read as "the repo moved" on another; a BOM or a lone CR is a real byte and still moves it."""
    path = Path(repo_root) / rel
    if not path.is_file():
        return None
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError(f"{rel} is not UTF-8 text") from None
    return text.replace("\r\n", "\n"), hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


@functools.cache
def _shape(rel: str) -> dict:
    return yaml.safe_load((PLUGIN_ROOT / _SHAPES[rel]).read_text(encoding="utf-8"))


def _repeating_block(text: str, rel: str) -> dict | None:
    """The document's repeating section (its Dimensions, its Functional Requirements) as `read_document` finds it by
    heading — aliases and drifted wording included; None when the document has no such section."""
    doc = document_shape.read_document(text, _shape(rel))
    return next((b for b in doc["blocks"] if b["kind"] == "repeating_section"), None)


def _slug(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")


def _plain(cell: str) -> str:
    """A table cell or heading with its bold markers and wrapping backticks removed."""
    return cell.replace("**", "").strip().strip("`").strip()


def _norm(header: str) -> str:
    return re.sub(r"\s+", " ", _plain(header).lower().replace("’", "'"))


def _split_row(line: str) -> list[str]:
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    return [c.replace("\\|", "|").strip() for c in re.split(r"(?<!\\)\|", body)]


def _is_separator(line: str) -> bool:
    cells = _split_row(line)
    return bool(cells) and all(re.fullmatch(r":?-+:?", c) for c in cells)


def _tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """Every markdown table outside a code fence as (header cells, data rows)."""
    lines = text.split("\n")
    found, fenced, i = [], False, 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith(("```", "~~~")):
            fenced = not fenced
        elif (not fenced and stripped.startswith("|") and i + 1 < len(lines)
              and lines[i + 1].strip().startswith("|") and _is_separator(lines[i + 1])):
            rows, i = [], i + 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_split_row(lines[i]))
                i += 1
            found.append((_split_row(stripped), rows))
            continue
        i += 1
    return found


def _priority(text: str) -> str | None:
    """P0..P3 when `text` names exactly one; None for blank, unfilled ("P0 / P1 / P2") or anything else."""
    found = set(_PRIORITY_RE.findall(text or ""))
    return f"P{found.pop()}" if len(found) == 1 else None


def _titled(title: str, neutral: dict) -> tuple[dict, list[str]]:
    """`(fields, notes)`: `System.Title` (the board title, cut to the work item limit with a note) beside the
    repository's neutral keys, which no field op ever carries."""
    notes = []
    board = title
    if len(board) > _MAX_TITLE:
        notes.append(f"title cut to {_MAX_TITLE} characters, the work item limit")
        board = board[:_MAX_TITLE - 1] + "…"
    return {_TITLE: board, **neutral}, notes


# --- outcomes ---------------------------------------------------------------------------------------------

def load_outcomes(repo_root) -> list[dict]:
    """One row per `### Dimension N: <name>` of success-criteria.md, in document order.

    The dimension's `| Outcome | Threshold | How We'll Measure |` table rides `fields["description_rows"]` as
    `{"outcome", "threshold", "measure"}` rows (empty when the dimension has no such table). `related_refs` is
    always `[]`: the outcome-to-domain edge is declared on the Domain (`load_domains`). A missing file is `[]`;
    two dimensions with one number raise `ValueError`."""
    read = _read(repo_root, SUCCESS_REL)
    block = _repeating_block(read[0], SUCCESS_REL) if read else None
    if not block:
        return []
    text, sha = read
    rows, seen = [], {}
    for inst in block["instances"]:
        m = _DIMENSION_RE.match(_plain(inst["heading_text"]))
        number, name = int(m.group(1)), _plain(m.group(2))
        if number in seen:
            raise ValueError(f"success-criteria.md has two dimensions numbered {number}: "
                             f"{seen[number]!r} and {inst['heading_text']!r}")
        seen[number] = inst["heading_text"]
        ident = f"{number}-{_slug(name)}" if _slug(name) else str(number)
        ref = f"sdlc:outcome:{ident}"
        title = f"Outcome {number} · {name}" if name else f"Outcome {number}"
        fields, notes = _titled(title, {"description_rows": _threshold_rows(text[inst["start"]:inst["end"]])})
        rows.append({"ref": ref, "kind": "outcome", "id": ident, "title": title, "status": None,
                     "fields": fields, "tags": {ref}, "parent_ref": None, "parent_note": None, "related_refs": [],
                     "source_path": SUCCESS_REL, "source_sha": sha, "notes": notes})
    return rows


def _threshold_rows(body: str) -> list[dict]:
    for header, data in _tables(body):
        if [_norm(h) for h in header[:3]] == ["outcome", "threshold", "how we'll measure"]:
            return [{"outcome": _plain(r[0]), "threshold": _plain(r[1]) if len(r) > 1 else "",
                     "measure": _plain(r[2]) if len(r) > 2 else ""} for r in data if any(c.strip() for c in r)]
    return []


# --- requirements and domains -----------------------------------------------------------------------------

def _summary_rows(text: str) -> list[dict]:
    """The Summary Table's data rows keyed by lower-cased header ("domain", "p0", ..., "outcome"); the Total row and
    blank rows are not domains."""
    for header, data in _tables(text):
        if _norm(header[0]) != "domain":
            continue
        keys = [_norm(h) for h in header]
        rows = [{k: _plain(r[i]) if i < len(r) else "" for i, k in enumerate(keys)} for r in data]
        return [r for r in rows if r["domain"] and r["domain"].lower() not in ("total", "totals")]
    return []


def _traceability_priorities(text: str) -> dict[int, str | None]:
    """FR number -> priority from a traceability-style table (an `FR-NNN` first cell and a Priority column)."""
    found: dict[int, str | None] = {}
    for header, data in _tables(text):
        names = [_norm(h) for h in header]
        if "priority" not in names:
            continue
        col = names.index("priority")
        for r in data:
            m = _FR_HEADING_RE.match(_plain(r[0])) if r else None
            if m and col < len(r):
                found.setdefault(int(m.group(1)), _priority(r[col]))
    return found


def _fr_sections(text: str, block: dict) -> list[dict]:
    """The `###` sections of the Functional Requirements block in order: a domain heading (`{"domain": name}`) or an
    FR (`{"fr": digits, "name", "body"}`). A `###` line inside a code fence is not a heading."""
    sections, fenced = [], False
    for line in text[block["start"]:block["end"]].split("\n"):
        if line.strip().startswith(("```", "~~~")):
            fenced = not fenced
        heading = None if fenced else _H3_RE.match(line)
        if heading:
            title = _plain(heading.group(1))
            fr = _FR_HEADING_RE.match(title)
            sections.append({"fr": fr.group(1), "name": _plain(fr.group(2)), "body": []} if fr
                            else {"domain": title})
        elif sections and "fr" in sections[-1]:
            sections[-1]["body"].append(line)
    return sections


def _read_requirements(repo_root) -> dict | None:
    """requirements.md as `{"sha", "domains", "frs", "summary_rows"}`, or None when the file is absent. `domains` are in
    Summary Table order, each with its FR ids; an FR is `{"ref", "id", "number", "name", "domain", "priority"}`.
    Raises `ValueError` for the contradictions the module docstring lists."""
    read = _read(repo_root, REQUIREMENTS_REL)
    if read is None:
        return None
    text, sha = read
    block = _repeating_block(text, REQUIREMENTS_REL)
    sections = _fr_sections(text, block) if block else []
    summary = _summary_rows(text)
    traced = _traceability_priorities(text)

    table: dict[str, str] = {}  # domain slug -> name, from the Summary Table
    for row in summary:
        slug = _slug(row["domain"])
        if not slug or slug in table:
            raise ValueError(f"requirements.md Summary Table has the domain {row['domain']!r} twice or with no "
                             f"usable name")
        table[slug] = row["domain"]
    named: dict[str, str] = {}  # domain slug -> name, from the `### <Domain>` headings
    for s in sections:
        if "domain" in s:
            slug = _slug(s["domain"])
            if not slug or slug in named:
                raise ValueError(f"requirements.md has a `### {s['domain']}` heading that is empty or repeated")
            named[slug] = s["domain"]
    for slug, name in named.items():
        if slug not in table:
            raise ValueError(f"requirements.md has a `### {name}` heading with no row in the Summary Table")
    for slug, name in table.items():
        if slug not in named:
            raise ValueError(f"requirements.md Summary Table lists the domain {name!r} but has no `### {name}` heading")

    frs, current, seen = [], None, set()
    for s in sections:
        if "domain" in s:
            current = _slug(s["domain"])
            continue
        fr_id, number = f"FR-{s['fr']}", int(s["fr"])
        if number in seen:
            raise ValueError(f"requirements.md defines {fr_id} twice")
        seen.add(number)
        if table and current is None:
            raise ValueError(f"{fr_id} sits under no `### <Domain>` heading in requirements.md (the Summary Table "
                             f"declares domains, so every FR must be filed under one)")
        line = _PRIORITY_LINE_RE.search("\n".join(s["body"]))
        frs.append({"ref": f"sdlc:fr:{s['fr']}", "id": fr_id, "number": number, "name": s["name"],
                    "domain": current, "priority": (_priority(line.group(1)) if line else None) or traced.get(number)})
    domains = [{"slug": slug, "name": name, "fr_ids": [f["id"] for f in frs if f["domain"] == slug]}
               for slug, name in table.items()]
    return {"sha": sha, "domains": domains, "frs": frs, "summary_rows": summary}


def load_requirements(repo_root) -> list[dict]:
    """One row per `### FR-NNN`, in document order. `parent_ref` is `sdlc:domain:<slug>` of the `### <Domain>`
    heading above it (None for a flat requirements.md, with a `no parent` note); `fields["priority"]` is
    `P0`..`P3` from the FR's own `**Priority:**` line, else its traceability row, else None (an unfilled
    `P0 / P1 / P2` is not a priority); `fields["domain"]` is the domain slug. A missing file is `[]`; a stray
    FR, a duplicate FR or a heading/row mismatch raises `ValueError`."""
    tree = _read_requirements(repo_root)
    if tree is None:
        return []
    flat = not tree["domains"]
    rows = []
    for fr in tree["frs"]:
        title = f"{fr['id']} · {fr['name']}" if fr["name"] else fr["id"]
        fields, notes = _titled(title, {"priority": fr["priority"], "domain": fr["domain"]})
        rows.append({"ref": fr["ref"], "kind": "requirement", "id": fr["id"], "title": title, "status": None,
                     "fields": fields, "tags": {fr["ref"]},
                     "parent_ref": f"sdlc:domain:{fr['domain']}" if fr["domain"] else None,
                     "parent_note": "no parent: requirements.md has no domain headings" if flat else None,
                     "related_refs": [], "source_path": REQUIREMENTS_REL, "source_sha": tree["sha"], "notes": notes})
    return rows


def domain_of_fr(repo_root) -> dict[str, str]:
    """{"FR-001": "<domain slug>"} for every FR filed under a domain; {} when there is no requirements.md or it is
    flat. Raises like `load_requirements`."""
    tree = _read_requirements(repo_root)
    return {fr["id"]: fr["domain"] for fr in tree["frs"] if fr["domain"]} if tree else {}


def _outcome_ids(value, where: str) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[,;\s]+", value)
    if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{where} must be a list of outcome ids, such as [1-turnaround-time]")
    return [v.strip() for v in value if v.strip().lower() not in _NONE_WORDS]


def domain_outcomes(cfg: dict | None, summary_rows: list[dict]) -> dict[str, list[str]]:
    """{domain slug: [outcome id]} — `tree.domain_outcomes` from `.sdlc/ado.yaml` united with an optional `Outcome`
    column of the Summary Table (a row's `"outcome"` cell), config first, de-duplicated. A domain with no outcome
    has no key. Never inferred: a domain slug in the config that is not a Summary Table row raises `ValueError`."""
    declared = ((cfg or {}).get("tree") or {}).get("domain_outcomes") or {}
    if not isinstance(declared, dict):
        raise ValueError("tree.domain_outcomes must map a domain slug to a list of outcome ids")
    slugs = [_slug(r.get("domain", "")) for r in summary_rows]
    linked: dict[str, list[str]] = {}
    for key, value in declared.items():
        if key not in slugs:
            raise ValueError(f"tree.domain_outcomes names the domain {key!r}, which is not a row of the Summary "
                             f"Table in requirements.md (domains: {', '.join(slugs) or 'none'})")
        linked.setdefault(key, []).extend(_outcome_ids(value, f"tree.domain_outcomes.{key}"))
    for slug, row in zip(slugs, summary_rows):
        linked.setdefault(slug, []).extend(_outcome_ids(row.get("outcome", ""), f"the Outcome cell of {slug}"))
    return {slug: list(dict.fromkeys(ids)) for slug, ids in linked.items() if ids}


def load_domains(repo_root, cfg: dict | None = None) -> list[dict]:
    """One row per `| Domain |` Summary Table row, in table order. `fields["fr_ids"]` are the FRs under its
    `### <Domain>` heading and `fields["description_rows"]` their ids and priorities. Its outcome edge comes from
    `domain_outcomes(cfg, ...)` (`cfg` is the parsed `.sdlc/ado.yaml`; optional): `related_refs` lists the
    outcomes, or — with `tree.outcome_edge: parent` — the first becomes `parent_ref` and the rest stay related;
    a domain with none carries `parent_note` "no outcome link: ...". An outcome id that success-criteria.md
    does not define raises `ValueError`, as does a heading/row mismatch or a stray FR."""
    tree = _read_requirements(repo_root)
    if tree is None or not tree["domains"]:
        return []
    edge = ((cfg or {}).get("tree") or {}).get("outcome_edge", "related")
    if edge not in ("related", "parent"):
        raise ValueError(f"tree.outcome_edge must be related or parent, not {edge!r}")
    linked = domain_outcomes(cfg, tree["summary_rows"])
    known = {o["id"] for o in load_outcomes(repo_root)} if linked else set()
    priority = {fr["id"]: fr["priority"] for fr in tree["frs"]}
    rows = []
    for d in tree["domains"]:
        ids = linked.get(d["slug"], [])
        for outcome_id in ids:
            if outcome_id not in known:
                have = ", ".join(sorted(known)) or "none"
                raise ValueError(f"the domain {d['slug']!r} links the outcome {outcome_id!r}, which "
                                 f"success-criteria.md does not define (outcomes: {have})")
        refs = [f"sdlc:outcome:{i}" for i in ids]
        parent = refs[0] if refs and edge == "parent" else None
        ref = f"sdlc:domain:{d['slug']}"
        fields, notes = _titled(d["name"], {"fr_ids": list(d["fr_ids"]),
                                            "description_rows": [{"fr": i, "priority": priority[i]} for i in d["fr_ids"]]})
        rows.append({"ref": ref, "kind": "domain", "id": d["slug"], "title": d["name"], "status": None,
                     "fields": fields, "tags": {ref}, "parent_ref": parent,
                     "parent_note": None if refs else f"no outcome link: tree.domain_outcomes has no entry for "
                                                      f"{d['slug']}",
                     "related_refs": refs[1:] if parent else refs,
                     "source_path": REQUIREMENTS_REL, "source_sha": tree["sha"], "notes": notes})
    return rows


# --- epics ------------------------------------------------------------------------------------------------

def parse_fr_link(text: str) -> list[str]:
    """The FR ids a `FR Link` cell names, in order, de-duplicated: ranges (`FR-001..004`, `FR-001..FR-004`, an en or
    em dash, `to`) expand with the first id's zero padding, lists split on anything else. Words that are not FR ids
    (`TBD`, `n/a`, a dash) name none. A range that runs backwards or past 500 raises `ValueError`."""
    ids: list[str] = []
    for m in _FR_LINK_RE.finditer(text or ""):
        start_digits, end_digits = m.group(1), m.group(2)
        first = int(start_digits)
        last = int(end_digits) if end_digits is not None else first
        if last < first:
            raise ValueError(f"FR Link range {m.group(0).strip()!r} runs backwards")
        if last - first >= _RANGE_LIMIT:
            raise ValueError(f"FR Link range {m.group(0).strip()!r} spans more than {_RANGE_LIMIT} requirements")
        ids.extend(f"FR-{n:0{len(start_digits)}d}" for n in range(first, last + 1))
    return list(dict.fromkeys(ids))


def _ep_number(text: str) -> int | None:
    """The number of the first `EP-NNN` in `text`, or of an `sdlc:epic:NNN` ref; None for neither."""
    for m in ID_RE.finditer(text):
        if m.group(1) == "EP":
            return int(re.search(r"\d+", m.group(0)).group(0))
    m = re.fullmatch(r"sdlc:epic:(\d+)", text.strip())
    return int(m.group(1)) if m else None


def _epic_fr_links(text: str) -> dict[int, str] | None:
    """EP number -> the raw `FR Link` cell, from the first table with an FR Link column; None without one."""
    for header, data in _tables(text):
        col = next((i for i, h in enumerate(header) if _norm(h) in ("fr link", "fr links")), None)
        if col is None:
            continue
        links: dict[int, str] = {}
        for row in data:
            number = _ep_number(row[0]) if row else None
            if number is not None:
                links.setdefault(number, row[col] if col < len(row) else "")
        return links
    return None


def _compress(frs: list[dict]) -> str:
    """`FR-001, FR-002, FR-003, FR-009` -> `FR-001..003, FR-009` (runs of consecutive numbers in link order)."""
    runs: list[list[dict]] = []
    for fr in frs:
        if runs and fr["number"] == runs[-1][-1]["number"] + 1:
            runs[-1].append(fr)
        else:
            runs.append([fr])
    return ", ".join(r[0]["id"] if len(r) == 1 else f"{r[0]['id']}..{r[-1]['id'][3:]}" for r in runs)


def epic_links(repo_root, epic_row: dict, cfg: dict | None = None) -> tuple[str | None, str | None, list[str]]:
    """(parent_ref, note, related_refs) for one epic, from its `FR Link` cell in epics.md's Epic Summary.

    * every linked FR in one domain: (`sdlc:domain:<slug>`, "fulfils FR-001..004", [the FR refs])
    * FRs in several domains: (None, "spans domains: a, b", [the FR refs] + [the domain refs])
    * `FR Link` empty: (None, "no fulfils links: FR Link empty", [])
    * "no fulfils links: <why>", nothing linked, when epics.md, its FR Link column, the epic's row or
      requirements.md is missing; a flat requirements.md gives (None, "fulfils ...", [the FR refs]).

    An FR is never the parent. An FR the epic links but requirements.md does not define raises `ValueError`.
    `epic_row` names its epic by `id` (EP-001) or `ref` (sdlc:epic:001). A row `ado_sync_sources.projections` hands
    over carries `source_row` — what its epic loader read, from whichever epics.md it found — and its `FR Link`
    is used as read (the Epic Summary cell, else the epic's `**Linked requirement:**` line); a bare row re-reads
    the Epic Summary of `.sdlc/artifacts/01-requirements/epics.md`. `cfg` is accepted so every resolver takes
    the same arguments; the links are declared in the artifacts, so none of it is read."""
    number = next((n for n in (_ep_number(str(epic_row.get(k) or "")) for k in ("id", "ref")) if n is not None), None)
    if number is None:
        raise ValueError(f"epic row carries no EP-NNN id (id={epic_row.get('id')!r}, ref={epic_row.get('ref')!r})")
    epic_id = f"EP-{number:03d}"
    source_row = epic_row.get("source_row")
    if isinstance(source_row, dict) and "FR Link" in source_row:
        cell = str(source_row.get("FR Link") or "")
    else:
        epics = _read(repo_root, EPICS_REL)
        if epics is None:
            return None, "no fulfils links: epics.md not found", []
        links = _epic_fr_links(epics[0])
        if links is None:
            return None, "no fulfils links: epics.md has no FR Link column", []
        if number not in links:
            return None, f"no fulfils links: {epic_id} has no row in the Epic Summary", []
        cell = links[number]
    wanted = parse_fr_link(cell)
    if not wanted:
        return None, "no fulfils links: FR Link empty", []
    tree = _read_requirements(repo_root)
    if tree is None:
        return None, "no fulfils links: requirements.md not found", []
    by_number = {fr["number"]: fr for fr in tree["frs"]}
    missing = [i for i in wanted if int(i[3:]) not in by_number]
    if missing:
        raise ValueError(f"{epic_id} links {', '.join(missing)}, which requirements.md does not define")
    frs = [by_number[int(i[3:])] for i in wanted]
    refs = [fr["ref"] for fr in frs]
    used = {fr["domain"] for fr in frs if fr["domain"]}
    if len(used) > 1:
        slugs = [d["slug"] for d in tree["domains"] if d["slug"] in used]
        return None, f"spans domains: {', '.join(slugs)}", refs + [f"sdlc:domain:{s}" for s in slugs]
    return (f"sdlc:domain:{used.pop()}" if used else None), f"fulfils {_compress(frs)}", refs


# --- registration -----------------------------------------------------------------------------------------

def _outcomes_source(repo_root, cfg=None, schema=None) -> list[dict]:
    return load_outcomes(repo_root)


def _domains_source(repo_root, cfg=None, schema=None) -> list[dict]:
    return load_domains(repo_root, cfg)


def _requirements_source(repo_root, cfg=None, schema=None) -> list[dict]:
    return load_requirements(repo_root)


def _epic_parent(repo_root, epic_row: dict) -> tuple[str | None, str | None, list[str]]:
    """`PARENT_RESOLVERS["epic"]`: `epic_links` whole — (parent_ref, note, related_refs). `projections` writes the
    first two into `parent_ref`/`parent_note` and appends the fulfils links to `related_refs` (kit K25: an epic is
    Related to every FR in its FR Link, and a cross-domain epic to each domain)."""
    return epic_links(repo_root, epic_row, None)


def _register(hooks=None) -> bool:
    """Add this module's four entries to `ado_sync_sources`' extend-only tables; True when they were added.

    `hooks` is the module (or any object with `SOURCES` and `PARENT_RESOLVERS` dicts); by default it is looked up in
    `sys.modules` and imported lazily. A module that does not exist yet, or lacks either table, registers nothing
    and returns False — a real import error inside it is not swallowed. Only this module's own keys are set."""
    if hooks is None:
        hooks = sys.modules.get("ado_sync_sources")
        if hooks is None:
            try:
                hooks = importlib.import_module("ado_sync_sources")
            except ModuleNotFoundError as exc:
                if exc.name != "ado_sync_sources":
                    raise
                return False
    sources, resolvers = getattr(hooks, "SOURCES", None), getattr(hooks, "PARENT_RESOLVERS", None)
    if not isinstance(sources, dict) or not isinstance(resolvers, dict):
        return False
    sources["outcome"] = _outcomes_source
    sources["domain"] = _domains_source
    sources["requirement"] = _requirements_source
    resolvers["epic"] = _epic_parent
    return True


_register()
