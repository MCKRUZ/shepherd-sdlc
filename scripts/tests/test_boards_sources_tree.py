"""The requirements tree's sources for the Boards mirror: outcomes, domains, requirements, epic links (B2-P3b).

`scripts/ado_sync_sources_tree.py` reads the first of the design's two trees (Outcome <-Related-> Domain -> FR)
out of `success-criteria.md` and `requirements.md`, and says how an epic joins it through the `FR Link` cell of
`epics.md`. Its mini repo is `fixtures/boards_repo_tree/` (generic names; the stray `FR-099` under no domain
heading is there on purpose, so `clean` strips it for the happy path and the raw fixture pins the refusal).

The rule these tests hold most firmly is the two-trees rule: an epic is never parented under an FR. A
single-domain epic parents under its Domain, a cross-domain epic has no parent and links each domain, an
epic with an empty `FR Link` says so. The module reads and never writes (every fixture's SHA-256 is
checked before and after), spawns nothing, and registers itself through `ado_sync_sources`' extend-only tables.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401

import ast
import hashlib
import importlib
import shutil
import sys
import types
from pathlib import Path

import pytest

import ado_sync_model as model
import ado_sync_sources as sources
import ado_sync_sources_tree as tree
import ado_wit_map as wm
import boards_contract as bc

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "boards_repo_tree"
SUCCESS = ".sdlc/artifacts/00-discovery/success-criteria.md"
REQUIREMENTS = ".sdlc/artifacts/01-requirements/requirements.md"
EPICS = ".sdlc/artifacts/01-requirements/epics.md"

# every FR in the mini repo, the domain heading it sits under and the priority it resolves to
FRS = {"FR-001": ("order-intake", "P0"), "FR-002": ("order-intake", "P0"), "FR-003": ("order-intake", "P1"),
       "FR-004": ("pricing-rules", "P0"), "FR-005": ("pricing-rules", "P1"),
       "FR-006": ("shipment-tracking", "P1"), "FR-007": ("shipment-tracking", "P2")}
CONFIG = {"tree": {"domain_outcomes": {"order-intake": ["1-turnaround-time"],
                                       "pricing-rules": ["1-turnaround-time", "2-margin-consistency"]}}}


def _digests(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _put(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


@pytest.fixture
def clean(tmp_path) -> Path:
    """The mini repo minus the deliberately stray FR-099: the happy-path tree."""
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    text = (root / REQUIREMENTS).read_bytes().decode("utf-8")
    start, end = text.index("<!-- fixture: FR-099"), text.index("### Order Intake")
    assert start < end, "the fixture's stray FR-099 moved: update this strip"
    _put(root, REQUIREMENTS, text[:start] + text[end:])
    return root


def _fr(n: int, priority: str = "P1") -> str:
    return (f"### FR-{n:03d}: Requirement {n}\n\n**Priority:** {priority}\n\n**Requirement:**\n"
            f"> The system SHALL do thing {n}.\n\n---\n\n")


def _doc(domains: dict[str, list[int]], *, summary: bool = True, outcome_col: dict[str, str] | None = None) -> str:
    """A small requirements.md: `domains` maps a domain name ('' = no heading) to its FR numbers."""
    out = "# Requirements\n\n"
    if summary:
        names = [d for d in domains if d]
        out += "## Summary Table\n\n| Domain | P0 | P1 | P2 | Total |" + (" Outcome |" if outcome_col else "")
        out += "\n|---|---|---|---|---|" + ("---|" if outcome_col else "") + "\n"
        for d in names:
            out += f"| {d} | 0 | 0 | 0 | 0 |" + (f" {outcome_col.get(d, '')} |" if outcome_col else "") + "\n"
        out += "\n"
    out += "## Functional Requirements\n\n"
    for d, numbers in domains.items():
        out += (f"### {d}\n\n" if d else "") + "".join(_fr(n) for n in numbers)
    return out


def _epics(links: dict[int, str]) -> str:
    rows = "".join(f"| EP-{n:03d} | Epic {n} | Persona | P0 | 3 | {cell} |\n" for n, cell in links.items())
    return ("# Epics\n\n## Epic Summary\n\n| Epic ID | Title | Persona | Priority | Estimate | FR Link |\n"
            "|---|---|---|---|---|---|\n" + rows)


def _repo(tmp_path: Path, *, name: str = "mini", requirements: str | None = None, epics: str | None = None,
          success: bool = False) -> Path:
    root = tmp_path / name
    root.mkdir()
    if requirements is not None:
        _put(root, REQUIREMENTS, requirements)
    if epics is not None:
        _put(root, EPICS, epics)
    if success:
        _put(root, SUCCESS, (FIXTURE / SUCCESS).read_bytes().decode("utf-8"))
    return root


# --- outcomes -----------------------------------------------------------------------------------------------

def test_one_outcome_per_dimension_heading():
    rows = tree.load_outcomes(FIXTURE)
    assert [r["id"] for r in rows] == ["1-turnaround-time", "2-margin-consistency", "3-adoption"]
    first = rows[0]
    assert first["ref"] == "sdlc:outcome:1-turnaround-time" and first["kind"] == "outcome"
    assert first["title"] == "Outcome 1 · Turnaround time" and first["tags"] == {first["ref"]}
    assert first["status"] is None and first["parent_ref"] is None and first["parent_note"] is None
    assert first["source_path"] == SUCCESS
    assert first["source_sha"] == hashlib.sha256((FIXTURE / SUCCESS).read_bytes()).hexdigest()
    assert bc.REF_RE.fullmatch(first["ref"])


def test_outcomes_have_no_related_refs_and_carry_the_threshold_rows():
    rows = tree.load_outcomes(FIXTURE)
    assert all(r["related_refs"] == [] for r in rows)  # the edge to a domain is declared on the domain
    assert rows[0]["fields"]["description_rows"] == [
        {"outcome": "Pass (exceeds expectations)", "threshold": "Median under 2 minutes",
         "measure": "Timestamp difference in the order log"},
        {"outcome": "Partial (acceptable, improvement required)", "threshold": "Median 2 to 5 minutes",
         "measure": "Timestamp difference in the order log"},
        {"outcome": "Fail (not acceptable for release)", "threshold": "Median over 5 minutes",
         "measure": "Timestamp difference in the order log"}]
    assert [len(r["fields"]["description_rows"]) for r in rows] == [3, 3, 3]
    assert rows[2]["fields"]["description_rows"][0]["threshold"] == "80% of desks active weekly"


def test_no_success_criteria_is_no_outcomes(tmp_path):
    assert tree.load_outcomes(_repo(tmp_path, requirements=_doc({"A": [1]}))) == []


def test_a_dimension_without_a_threshold_table_has_empty_rows(tmp_path):
    root = _repo(tmp_path)
    _put(root, SUCCESS, "# Success Criteria\n\n## Measurable Success Dimensions\n\n### Dimension 1: Speed\n\n"
                        "Prose only, no table yet.\n")
    (row,) = tree.load_outcomes(root)
    assert row["id"] == "1-speed" and row["fields"]["description_rows"] == []


def test_dimension_name_punctuation_is_slugged_and_a_nameless_one_is_just_its_number(tmp_path):
    root = _repo(tmp_path)
    _put(root, SUCCESS, "# S\n\n## Measurable Success Dimensions\n\n### Dimension 4: Cost & Speed (v2)\n\n"
                        "### Dimension 5\n\n")
    rows = tree.load_outcomes(root)
    assert [r["id"] for r in rows] == ["4-cost-speed-v2", "5"]
    assert [r["title"] for r in rows] == ["Outcome 4 · Cost & Speed (v2)", "Outcome 5"]
    assert all(bc.REF_RE.fullmatch(r["ref"]) for r in rows)


def test_two_dimensions_with_one_number_are_refused(tmp_path):
    root = _repo(tmp_path)
    _put(root, SUCCESS, "# S\n\n## Measurable Success Dimensions\n\n### Dimension 1: A\n\n### Dimension 1: B\n")
    with pytest.raises(ValueError, match="two dimensions numbered 1"):
        tree.load_outcomes(root)


def test_crlf_files_read_the_same_and_hash_the_same(tmp_path):
    """A CRLF checkout of the commit (Git for Windows' autocrlf default) is the same source: the same rows, the same
    fields and the same `source_sha`, or a ledger written on a Mac reads "the repo moved" on Windows. A lone CR is a
    real byte and still moves it."""
    root = _repo(tmp_path)
    lf = (FIXTURE / SUCCESS).read_bytes().decode("utf-8")
    assert "\r" not in lf, "the fixture must check out LF (.gitattributes `eol=lf`), or this compares CRLF with itself"
    _put(root, SUCCESS, lf.replace("\n", "\r\n"))
    rows = tree.load_outcomes(root)
    assert [r["id"] for r in rows] == [r["id"] for r in tree.load_outcomes(FIXTURE)]
    assert rows[0]["fields"] == tree.load_outcomes(FIXTURE)[0]["fields"]
    assert rows[0]["source_sha"] == tree.load_outcomes(FIXTURE)[0]["source_sha"]
    assert rows[0]["source_sha"] == hashlib.sha256(lf.encode()).hexdigest()
    _put(root, SUCCESS, lf.replace("\n", "\r", 1))
    assert tree.load_outcomes(root)[0]["source_sha"] != rows[0]["source_sha"]


# --- requirements -------------------------------------------------------------------------------------------

def test_every_fr_is_parented_by_the_domain_heading_above_it(clean):
    rows = tree.load_requirements(clean)
    assert [r["id"] for r in rows] == list(FRS)
    for row in rows:
        domain, _priority = FRS[row["id"]]
        assert row["parent_ref"] == f"sdlc:domain:{domain}" and row["fields"]["domain"] == domain
        assert row["parent_note"] is None and row["related_refs"] == []


def test_an_fr_row_is_a_projection(clean):
    row = tree.load_requirements(clean)[0]
    assert (row["ref"], row["kind"], row["id"]) == ("sdlc:fr:001", "requirement", "FR-001")
    assert row["title"] == "FR-001 · Reject duplicate orders" and row["tags"] == {"sdlc:fr:001"}
    assert row["status"] is None and row["source_path"] == REQUIREMENTS
    assert row["source_sha"] == hashlib.sha256((clean / REQUIREMENTS).read_bytes()).hexdigest()
    assert bc.REF_RE.fullmatch(row["ref"])


def test_priority_is_the_frs_own_line_then_its_traceability_row_then_none(clean, tmp_path):
    got = {r["id"]: r["fields"]["priority"] for r in tree.load_requirements(clean)}
    assert got == {fr: p for fr, (_d, p) in FRS.items()}
    # FR-001 "P0 (Must Have)" reads P0; FR-004's unfilled "P0 / P1 / P2" is not a priority, so the table answers;
    # FR-007 has no line at all, so the table answers P2
    root = _repo(tmp_path, requirements=_doc({"A": [1]}).replace("**Priority:** P1", "**Priority:** P0 / P1 / P2"))
    assert tree.load_requirements(root)[0]["fields"]["priority"] is None  # and no traceability table: unknown


def test_the_stray_fr_under_no_domain_heading_is_refused_naming_it():
    for call in (tree.load_requirements, tree.load_domains, tree.domain_of_fr):
        with pytest.raises(ValueError, match=r"FR-099 sits under no `### <Domain>` heading"):
            call(FIXTURE)


def test_domain_of_fr_maps_each_fr_to_its_domain(clean):
    assert tree.domain_of_fr(clean) == {fr: d for fr, (d, _p) in FRS.items()}


def test_a_flat_requirements_file_has_no_domains_and_no_parents(tmp_path):
    root = _repo(tmp_path, requirements=_doc({"": [1, 2]}, summary=False))
    rows = tree.load_requirements(root)
    assert [r["id"] for r in rows] == ["FR-001", "FR-002"]
    assert all(r["parent_ref"] is None and r["parent_note"].startswith("no parent") for r in rows)
    assert tree.load_domains(root) == [] and tree.domain_of_fr(root) == {}


def test_a_missing_requirements_file_is_empty_everywhere(tmp_path):
    root = _repo(tmp_path)
    assert (tree.load_requirements(root), tree.load_domains(root), tree.domain_of_fr(root)) == ([], [], {})


def test_an_fr_defined_twice_is_refused(tmp_path):
    root = _repo(tmp_path, requirements=_doc({"A": [1, 1]}))
    with pytest.raises(ValueError, match="FR-001 twice"):
        tree.load_requirements(root)


def test_a_heading_inside_a_code_fence_is_not_a_domain(tmp_path):
    text = _doc({"A": [1]}).replace("**Requirement:**", "```\n### Not A Domain\n```\n\n**Requirement:**")
    root = _repo(tmp_path, requirements=text)
    assert [r["parent_ref"] for r in tree.load_requirements(root)] == ["sdlc:domain:a"]


def test_a_wide_fr_number_keeps_its_digits_in_the_ref(tmp_path):
    root = _repo(tmp_path, requirements=_doc({"A": [1234]}))
    assert tree.load_requirements(root)[0]["ref"] == "sdlc:fr:1234"


# --- domains ------------------------------------------------------------------------------------------------

def test_three_domains_whose_fr_lists_match_their_headings(clean):
    rows = tree.load_domains(clean)  # the Summary Table's Total row is not a domain
    assert [(r["id"], r["title"]) for r in rows] == [("order-intake", "Order Intake"),
                                                      ("pricing-rules", "Pricing Rules"),
                                                      ("shipment-tracking", "Shipment Tracking")]
    assert [r["fields"]["fr_ids"] for r in rows] == [["FR-001", "FR-002", "FR-003"], ["FR-004", "FR-005"],
                                                     ["FR-006", "FR-007"]]
    first = rows[0]
    assert first["ref"] == "sdlc:domain:order-intake" and first["kind"] == "domain" and first["tags"] == {first["ref"]}
    assert first["status"] is None and first["source_path"] == REQUIREMENTS
    assert first["fields"]["description_rows"] == [{"fr": "FR-001", "priority": "P0"},
                                                   {"fr": "FR-002", "priority": "P0"},
                                                   {"fr": "FR-003", "priority": "P1"}]


def test_a_domain_with_no_outcome_declared_says_so(clean):
    for cfg in (None, {}, {"tree": {}}):
        rows = tree.load_domains(clean, cfg)
        assert all(r["related_refs"] == [] and r["parent_ref"] is None for r in rows)
        assert rows[0]["parent_note"].startswith("no outcome link")


def test_tree_domain_outcomes_fill_related_refs(clean):
    rows = {r["id"]: r for r in tree.load_domains(clean, CONFIG)}
    assert rows["order-intake"]["related_refs"] == ["sdlc:outcome:1-turnaround-time"]
    assert rows["pricing-rules"]["related_refs"] == ["sdlc:outcome:1-turnaround-time",
                                                     "sdlc:outcome:2-margin-consistency"]
    assert rows["order-intake"]["parent_note"] is None and rows["pricing-rules"]["parent_note"] is None
    assert rows["shipment-tracking"]["related_refs"] == []  # not in the config: said, not guessed
    assert rows["shipment-tracking"]["parent_note"].startswith("no outcome link")
    assert all(r["parent_ref"] is None for r in rows.values())


def test_a_domain_slug_absent_from_the_summary_table_is_refused(clean):
    cfg = {"tree": {"domain_outcomes": {"ghost-domain": ["1-turnaround-time"]}}}
    with pytest.raises(ValueError, match="ghost-domain"):
        tree.load_domains(clean, cfg)
    with pytest.raises(ValueError, match="ghost-domain"):
        tree.domain_outcomes(cfg, [{"domain": "Order Intake"}])


def test_an_outcome_id_success_criteria_does_not_define_is_refused(clean):
    cfg = {"tree": {"domain_outcomes": {"order-intake": ["9-nothing"]}}}
    with pytest.raises(ValueError, match="'9-nothing'.*does not define"):
        tree.load_domains(clean, cfg)


def test_an_outcome_column_in_the_summary_table_is_united_with_the_config(tmp_path):
    root = _repo(tmp_path, success=True, requirements=_doc(
        {"A": [1], "B": [2], "C": [3]}, outcome_col={"A": "2-margin-consistency", "B": "-", "C": "1-turnaround-time"}))
    cfg = {"tree": {"domain_outcomes": {"a": ["1-turnaround-time"]}}}
    rows = {r["id"]: r for r in tree.load_domains(root, cfg)}
    assert rows["a"]["related_refs"] == ["sdlc:outcome:1-turnaround-time", "sdlc:outcome:2-margin-consistency"]
    assert rows["b"]["related_refs"] == [] and rows["b"]["parent_note"].startswith("no outcome link")  # "-" is none
    assert rows["c"]["related_refs"] == ["sdlc:outcome:1-turnaround-time"]


def test_domain_outcomes_is_never_inferred_deduplicated_and_config_first():
    rows = [{"domain": "A", "outcome": "1-x, 2-y"}, {"domain": "B"}, {"domain": "C Domain", "outcome": "tbd"}]
    assert tree.domain_outcomes({"tree": {"domain_outcomes": {"a": ["2-y", "3-z"]}}}, rows) == {
        "a": ["2-y", "3-z", "1-x"]}
    assert tree.domain_outcomes(None, rows) == {"a": ["1-x", "2-y"]}
    assert tree.domain_outcomes({"tree": {"domain_outcomes": {"c-domain": "4-w"}}}, rows)["c-domain"] == ["4-w"]
    assert tree.domain_outcomes({}, [{"domain": "A"}]) == {}
    with pytest.raises(ValueError, match="list of outcome ids"):
        tree.domain_outcomes({"tree": {"domain_outcomes": {"a": [3]}}}, rows)
    with pytest.raises(ValueError, match="must map a domain slug"):
        tree.domain_outcomes({"tree": {"domain_outcomes": ["a"]}}, rows)


def test_outcome_edge_parent_makes_the_first_outcome_the_parent(clean):
    cfg = {"tree": {**CONFIG["tree"], "outcome_edge": "parent"}}
    rows = {r["id"]: r for r in tree.load_domains(clean, cfg)}
    assert rows["order-intake"]["parent_ref"] == "sdlc:outcome:1-turnaround-time"
    assert rows["order-intake"]["related_refs"] == []
    assert rows["pricing-rules"]["parent_ref"] == "sdlc:outcome:1-turnaround-time"
    assert rows["pricing-rules"]["related_refs"] == ["sdlc:outcome:2-margin-consistency"]
    assert rows["shipment-tracking"]["parent_ref"] is None
    with pytest.raises(ValueError, match="outcome_edge"):
        tree.load_domains(clean, {"tree": {"outcome_edge": "child"}})


def test_a_heading_with_no_summary_row_and_a_row_with_no_heading_are_refused(tmp_path):
    two = _doc({"A": [1], "B": [2]})
    no_row = _repo(tmp_path, requirements=two.replace("| B | 0 | 0 | 0 | 0 |\n", ""))
    with pytest.raises(ValueError, match="`### B` heading with no row in the Summary Table"):
        tree.load_domains(no_row)
    other = tmp_path / "other"
    other.mkdir()
    _put(other, REQUIREMENTS, two.replace("### B\n\n", ""))
    with pytest.raises(ValueError, match="lists the domain 'B' but has no `### B` heading"):
        tree.load_domains(other)


def test_a_domain_listed_twice_in_the_summary_table_is_refused(tmp_path):
    root = _repo(tmp_path, requirements=_doc({"A": [1]}).replace("| A | 0 | 0 | 0 | 0 |\n",
                                                                  "| A | 0 | 0 | 0 | 0 |\n| a | 0 | 0 | 0 | 0 |\n"))
    with pytest.raises(ValueError, match="twice"):
        tree.load_domains(root)


# --- the FR Link cell ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("FR-001..004, FR-009", ["FR-001", "FR-002", "FR-003", "FR-004", "FR-009"]),
    ("FR-001", ["FR-001"]),
    ("FR-003, FR-005", ["FR-003", "FR-005"]),
    ("FR-001..FR-003", ["FR-001", "FR-002", "FR-003"]),
    ("FR-001–003", ["FR-001", "FR-002", "FR-003"]),
    ("FR-001 — FR-002", ["FR-001", "FR-002"]),
    ("FR-001 to 003", ["FR-001", "FR-002", "FR-003"]),
    ("FR-001 - FR-002", ["FR-001", "FR-002"]),
    ("FR-9..11", ["FR-9", "FR-10", "FR-11"]),
    ("FR-002, FR-001..003, FR-002", ["FR-002", "FR-001", "FR-003"]),
    ("fr-007", ["FR-007"]),
    ("FR-001; FR-002 and FR-004", ["FR-001", "FR-002", "FR-004"]),
    ("", []), ("   ", []), ("—", []), ("TBD", []), ("n/a", []), ("[FR-NNN]", []), ("EP-002", []),
])
def test_parse_fr_link_goldens(text, expected):
    assert tree.parse_fr_link(text) == expected


def test_parse_fr_link_refuses_a_backwards_or_runaway_range_and_takes_none():
    for bad in ("FR-004..001", "FR-001..9999"):
        with pytest.raises(ValueError):
            tree.parse_fr_link(bad)
    assert tree.parse_fr_link(None) == []


# --- epic_links: the two-trees rule -------------------------------------------------------------------------

def test_a_single_domain_epic_parents_under_its_domain_and_relates_its_frs(clean):
    assert tree.epic_links(clean, {"id": "EP-001"}, {}) == (
        "sdlc:domain:order-intake", "fulfils FR-001..002", ["sdlc:fr:001", "sdlc:fr:002"])


def test_a_four_fr_epic_in_one_domain_reads_as_one_range(tmp_path):
    root = _repo(tmp_path, requirements=_doc({"Claims Intake": [1, 2, 3, 4, 9]}),
                 epics=_epics({1: "FR-001..004, FR-009", 2: "FR-001..002, FR-004"}))
    assert tree.epic_links(root, {"id": "EP-001"}, {}) == (
        "sdlc:domain:claims-intake", "fulfils FR-001..004, FR-009", [f"sdlc:fr:{n:03d}" for n in (1, 2, 3, 4, 9)])
    assert tree.epic_links(root, {"id": "EP-002"}, {})[1] == "fulfils FR-001..002, FR-004"


def test_a_cross_domain_epic_has_no_parent_and_relates_its_frs_and_both_domains(clean):
    assert tree.epic_links(clean, {"id": "EP-002"}, {}) == (
        None, "spans domains: order-intake, pricing-rules",
        ["sdlc:fr:003", "sdlc:fr:005", "sdlc:domain:order-intake", "sdlc:domain:pricing-rules"])


def test_an_empty_fr_link_is_a_stated_gap(clean):
    assert tree.epic_links(clean, {"id": "EP-003"}, {}) == (None, "no fulfils links: FR Link empty", [])


def test_an_fr_is_never_the_parent_of_an_epic_or_of_anything_else(clean):
    parents = [tree.epic_links(clean, {"id": f"EP-{n:03d}"}, {})[0] for n in (1, 2, 3)]
    parents += [r["parent_ref"] for r in tree.load_requirements(clean) + tree.load_domains(clean, CONFIG)
                + tree.load_outcomes(clean)]
    assert all(p is None or not p.startswith("sdlc:fr:") for p in parents)
    assert {p for p in parents if p} == {"sdlc:domain:order-intake", "sdlc:domain:pricing-rules",
                                         "sdlc:domain:shipment-tracking"}


def test_an_epic_is_found_by_its_ref_when_it_has_no_id(clean):
    assert tree.epic_links(clean, {"ref": "sdlc:epic:001"}, {})[1] == "fulfils FR-001..002"
    assert tree.epic_links(clean, {"id": "EP-1"}, {})[1] == "fulfils FR-001..002"
    for row in ({}, {"id": "FE-03"}, {"id": "FR-001"}, {"ref": "sdlc:feature:03"}):
        with pytest.raises(ValueError, match="no EP-NNN id"):
            tree.epic_links(clean, row, {})


def test_the_stray_fr_stops_an_epic_that_needs_the_requirements_tree():
    with pytest.raises(ValueError, match="FR-099"):
        tree.epic_links(FIXTURE, {"id": "EP-001"}, {})
    assert tree.epic_links(FIXTURE, {"id": "EP-003"}, {})[1] == "no fulfils links: FR Link empty"  # needs none


def test_an_epic_linking_an_fr_nobody_defined_is_refused_naming_both(tmp_path):
    root = _repo(tmp_path, requirements=_doc({"A": [1]}), epics=_epics({1: "FR-001, FR-042"}))
    with pytest.raises(ValueError, match="EP-001 links FR-042, which requirements.md does not define"):
        tree.epic_links(root, {"id": "EP-001"}, {})


def test_missing_artifacts_are_stated_never_guessed(tmp_path):
    reqs = _doc({"A": [1]})
    no_column = "# Epics\n\n| Epic ID | Title |\n|---|---|\n| EP-001 | x |\n"
    cases = [
        (_repo(tmp_path, name="a", requirements=reqs), "no fulfils links: epics.md not found"),
        (_repo(tmp_path, name="b", requirements=reqs, epics=no_column),
         "no fulfils links: epics.md has no FR Link column"),
        (_repo(tmp_path, name="c", requirements=reqs, epics=_epics({2: "FR-001"})),
         "no fulfils links: EP-001 has no row in the Epic Summary"),
        (_repo(tmp_path, name="d", epics=_epics({1: "FR-001"})), "no fulfils links: requirements.md not found"),
    ]
    for root, note in cases:
        assert tree.epic_links(root, {"id": "EP-001"}, {}) == (None, note, [])


def test_with_a_flat_requirements_file_an_epic_relates_its_frs_and_has_no_parent(tmp_path):
    root = _repo(tmp_path, requirements=_doc({"": [1, 2, 3]}, summary=False), epics=_epics({1: "FR-001..003"}))
    assert tree.epic_links(root, {"id": "EP-001"}, {}) == (
        None, "fulfils FR-001..003", ["sdlc:fr:001", "sdlc:fr:002", "sdlc:fr:003"])


# --- registration through ado_sync_sources' extend-only tables -----------------------------------------------

@pytest.fixture
def hooks(monkeypatch) -> types.ModuleType:
    """A stand-in `ado_sync_sources` with empty hook tables (B2-P3 owns the real one)."""
    stub = types.ModuleType("ado_sync_sources")
    stub.SOURCES, stub.PARENT_RESOLVERS = {}, {}
    monkeypatch.setitem(sys.modules, "ado_sync_sources", stub)
    return stub


def test_importing_the_module_registers_its_four_entries(hooks, monkeypatch):
    monkeypatch.delitem(sys.modules, "ado_sync_sources_tree")
    fresh = importlib.import_module("ado_sync_sources_tree")
    assert set(hooks.SOURCES) == {"outcome", "domain", "requirement"}
    assert set(hooks.PARENT_RESOLVERS) == {"epic"}
    assert hooks.SOURCES["domain"] is fresh._domains_source and hooks.PARENT_RESOLVERS["epic"] is fresh._epic_parent


def test_registration_is_extend_only_and_repeatable(hooks):
    spec_loader, feature_resolver = object(), object()
    hooks.SOURCES["spec"], hooks.PARENT_RESOLVERS["feature"] = spec_loader, feature_resolver
    assert tree._register(hooks) is True and tree._register(hooks) is True
    assert hooks.SOURCES["spec"] is spec_loader and hooks.PARENT_RESOLVERS["feature"] is feature_resolver
    assert set(hooks.SOURCES) == {"spec", "outcome", "domain", "requirement"}
    assert set(hooks.PARENT_RESOLVERS) == {"feature", "epic"}


def test_without_the_hook_tables_nothing_is_registered_and_nothing_fails(monkeypatch):
    assert tree._register(types.SimpleNamespace()) is False
    assert tree._register(types.SimpleNamespace(SOURCES={}, PARENT_RESOLVERS=None)) is False
    monkeypatch.setitem(sys.modules, "ado_sync_sources", None)  # an import of it now fails, as before B2-P3 exists
    assert tree._register() is False


def test_the_registered_loaders_answer_with_one_two_or_three_arguments(hooks, clean):
    tree._register(hooks)
    outcome, domain, requirement = (hooks.SOURCES[k] for k in ("outcome", "domain", "requirement"))
    assert [r["kind"] for r in outcome(clean)] == ["outcome"] * 3
    assert [r["kind"] for r in requirement(clean, {}, {})] == ["requirement"] * 7
    assert domain(clean, CONFIG)[0]["related_refs"] == ["sdlc:outcome:1-turnaround-time"]
    assert domain(clean)[0]["parent_note"].startswith("no outcome link")
    # the resolver answers epic_links whole: the fulfils links ride its third value into `related_refs` (K25)
    assert hooks.PARENT_RESOLVERS["epic"](clean, {"id": "EP-001"}) == (
        "sdlc:domain:order-intake", "fulfils FR-001..002", ["sdlc:fr:001", "sdlc:fr:002"])
    assert hooks.PARENT_RESOLVERS["epic"](clean, {"id": "EP-002"}) == (
        None, "spans domains: order-intake, pricing-rules",
        ["sdlc:fr:003", "sdlc:fr:005", "sdlc:domain:order-intake", "sdlc:domain:pricing-rules"])


# --- the tree as projections: titled by reference name, fulfils links carried (K25) ---------------------------

HYPERLINK = "https://dev.azure.com/org/Claims/_git/claims-api?path=/x.md&version=GCabc1234"
HISTORY = f"{bc.HISTORY_TOKEN} · created"


def _tree_rows(root: Path) -> list[dict]:
    return tree.load_outcomes(root) + tree.load_domains(root, CONFIG) + tree.load_requirements(root)


def test_every_tree_projection_carries_its_title_by_reference_name(clean):
    rows = _tree_rows(clean)
    assert {r["kind"] for r in rows} == {"outcome", "domain", "requirement"} and len(rows) == 13
    for row in rows:
        assert row["fields"]["System.Title"] == row["title"] and row["notes"] == [], row["ref"]


def test_a_tree_projections_neutral_keys_are_never_field_ops_and_it_can_be_created(clean):
    """`fields` keeps the repository's neutral keys (`description_rows`, `fr_ids`, `priority`, `domain`) beside
    `System.Title`; only the reference name is ever an op, so a plan lists no `/fields/fr_ids` and a create is
    buildable for every tree kind."""
    for row in _tree_rows(clean):
        assert [o["path"] for o in model.diff(row, None)] == ["/fields/System.Tags", "/fields/System.Title"], row["ref"]
        patch = wm.build_create_patch(row, {}, HYPERLINK, HISTORY, None)
        field_paths = [o["path"] for o in patch if o["path"].startswith("/fields/")]
        assert field_paths == ["/fields/System.Tags", "/fields/System.Title", "/fields/System.History"], row["ref"]
        assert next(o["value"] for o in patch if o["path"] == "/fields/System.Title") == row["title"]


def test_a_title_over_the_work_item_limit_is_cut_with_a_note(tmp_path):
    long_name = "x" * 300
    root = _repo(tmp_path, requirements=_doc({"A": [1]}).replace("Requirement 1", long_name))
    (row,) = tree.load_requirements(root)
    assert len(row["fields"]["System.Title"]) == 255 and row["fields"]["System.Title"].endswith("…")
    assert row["notes"] == ["title cut to 255 characters, the work item limit"]
    assert row["title"] == f"FR-001 · {long_name}"  # the projection's own title is the repository's, uncut


def test_projections_carry_each_epics_fulfils_links_as_related_refs(clean):
    """K25 through `ado_sync_sources.projections`: a single-domain epic parents under its Domain and is Related to
    its FRs; a cross-domain epic has no parent and is Related to its FRs and to each domain."""
    tree._register(sources)
    epics = {p["id"]: p for p in sources.projections(clean, {}, {}, ["epic"])}
    assert (epics["EP-001"]["parent_ref"], epics["EP-001"]["parent_note"], epics["EP-001"]["related_refs"]) == (
        "sdlc:domain:order-intake", "fulfils FR-001..002", ["sdlc:fr:001", "sdlc:fr:002"])
    assert (epics["EP-002"]["parent_ref"], epics["EP-002"]["parent_note"], epics["EP-002"]["related_refs"]) == (
        None, "spans domains: order-intake, pricing-rules",
        ["sdlc:fr:003", "sdlc:fr:005", "sdlc:domain:order-intake", "sdlc:domain:pricing-rules"])
    assert (epics["EP-003"]["parent_ref"], epics["EP-003"]["parent_note"], epics["EP-003"]["related_refs"]) == (
        None, "no fulfils links: FR Link empty", [])


def test_a_projected_epic_is_linked_from_the_fr_link_its_loader_read(clean):
    """The epic loader also finds a root-level epics.md; the resolver uses the FR Link that loader read
    (`source_row`) rather than a second lookup of its own that would say the file is missing."""
    (clean / EPICS).rename(clean / "epics.md")
    tree._register(sources)
    epics = {p["id"]: p for p in sources.projections(clean, {}, {}, ["epic"])}
    assert epics["EP-001"]["related_refs"] == ["sdlc:fr:001", "sdlc:fr:002"]
    assert tree.epic_links(clean, {"id": "EP-001"}, {})[1] == "no fulfils links: epics.md not found"  # a bare row
    assert tree.epic_links(clean, {"id": "EP-001", "source_row": {"FR Link": "FR-004..005"}}, {}) == (
        "sdlc:domain:pricing-rules", "fulfils FR-004..005", ["sdlc:fr:004", "sdlc:fr:005"])
    assert tree.epic_links(clean, {"id": "EP-001", "source_row": {"FR Link": ""}}, {}) == (
        None, "no fulfils links: FR Link empty", [])


# --- purity: reads only, spawns nothing, no identity ----------------------------------------------------------

def _run_everything(root: Path) -> None:
    for call in (tree.load_outcomes, tree.load_domains, tree.load_requirements, tree.domain_of_fr):
        try:
            call(root)
        except ValueError:
            pass  # the raw fixture's stray FR-099
    for n in (1, 2, 3):
        try:
            tree.epic_links(root, {"id": f"EP-{n:03d}"}, {})
        except ValueError:
            pass


def test_nothing_is_written(clean):
    for root in (FIXTURE, clean):
        before = _digests(root)
        _run_everything(root)
        tree.load_domains(clean, CONFIG)
        assert _digests(root) == before


def test_the_module_spawns_nothing_writes_nothing_and_imports_no_ado_module():
    source = Path(tree.__file__).read_text(encoding="utf-8")
    nodes = list(ast.walk(ast.parse(source)))
    imported = {a.name.split(".")[0] for n in nodes if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in nodes if isinstance(n, ast.ImportFrom) and n.module}
    assert not imported & {"subprocess", "shlex", "os", "shutil", "tempfile", "ado_transport"}
    assert not {m for m in imported if m.startswith("ado_")}
    assert not any(token in source for token in ("shell=True", ".write_text(", ".write_bytes(", "open(", "az_json"))


def test_the_exports_are_exactly_the_kits():
    assert sorted(tree.__all__) == sorted(["load_outcomes", "load_domains", "load_requirements", "domain_of_fr",
                                           "parse_fr_link", "epic_links", "domain_outcomes"])


def test_the_mini_repo_is_the_three_generic_artifacts_and_carries_no_identity():
    """Its own mini repo (`boards_repo_tree/**`, disjoint from B2-P3's `boards_repo/**`): the deliberately stray
    FR-099 would otherwise make every epic projection over the shared mini repo refuse."""
    for path in FIXTURE.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert not bc.EMAIL_RE.search(text) and not bc.GUID_RE.search(text), path.name
    assert sorted(p.relative_to(FIXTURE).as_posix() for p in FIXTURE.rglob("*") if p.is_file()) == [
        ".sdlc/artifacts/00-discovery/success-criteria.md", ".sdlc/artifacts/01-requirements/epics.md",
        ".sdlc/artifacts/01-requirements/requirements.md"]
