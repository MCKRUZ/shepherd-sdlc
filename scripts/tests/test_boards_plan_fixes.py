"""B0 plan fixes -- the three defects a live `plan --all` against an inherited Agile process showed (2026-10-15).

The process (captured, anonymised under `wit/captured/`) has nothing above Epic in its portfolio, a custom `Spec`
requirement type, and an Epic and a Feature whose `Microsoft.VSTS.Common.ValueArea` is always required. The live plan
fitted the tree correctly and still emitted three defects; each is pinned here on the same repository shape (the
`boards_repo` mini repository with the `boards_repo_tree` artifacts laid over it -- the files the live run read):

  1. Tag mode was declared but never applied. Outcome, domain and requirement "ride as tags", yet an epic's tags held
     only its own ref. Now a parent or `Related` ref of a riding kind adds `domain:<slug>`, `fr:<id>`, and the
     `outcome:<id>` of each outcome a riding domain maps to; the plan says `rides as tag ...` instead of `not
     planned`; the three families are plugin-owned tags (`PLUGIN_TAG_PREFIXES`), so a board-side removal is drift.
  2. Per-type field facts were read only for pinned types, so Epic's Priority was never planned and every Epic and
     Feature create "would fail" for fields the process defaults. `discover` now reads every type a kind lands on
     (one `workItemTypesField` each), and the epic loader writes Priority and AcceptanceCriteria where the type
     carries them.
  3. No way to supply a required value no artifact carries. `fields.<kind>.<key>: {field, value}` is a constant:
     written verbatim at create, filled on update only while the board's field is empty, the board's afterwards,
     and checked by `config check` against the field's allowed values.

Nothing here spawns `az`: `boards_env` forbids it at the seam and the `az` fixture answers from the captured `wit/`
documents. Names and teams are fictional.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import FakeBoardsAz, route_key_boards, route_params
from tests.ado_boards_fixtures import body_file

import copy
import itertools
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

import ado_schema
import ado_schema_map as asm
import ado_sync
import ado_sync_apply as apply_mod
import ado_sync_config as cfgmod
import ado_sync_model as model
import ado_sync_sources as sources
import ado_sync_sources_tree as tree
import ado_transport
import ado_wit_map as wm
import boards_contract as bc

HERE = Path(__file__).resolve().parent
MINI = HERE / "fixtures" / "boards_repo"
TREE = HERE / "fixtures" / "boards_repo_tree"
REQUIREMENTS = ".sdlc/artifacts/01-requirements/requirements.md"
STARTER = HERE.parent.parent / "templates" / "ado" / "ado.yaml"
REFERENCE = HERE.parent.parent / "references" / "ado-boards.md"
NOW = datetime(2026, 10, 15, 9, 30, tzinfo=timezone.utc)

PRIORITY = "Microsoft.VSTS.Common.Priority"
VALUE_AREA = "Microsoft.VSTS.Common.ValueArea"
ACCEPTANCE = "Microsoft.VSTS.Common.AcceptanceCriteria"
DISCOVERY = ["GET core/projects", "GET wit/workItemTypeCategories", "GET wit/workItemTypes", "GET wit/fields",
             "GET work/backlogconfiguration", "GET wit/classificationNodes", "GET work/iterations",
             "GET wit/workItemRelationTypes"]

# The live project's config, with the two constants this process needs (DEFECT 3) and the outcome map the tree
# fixture's domains declare.
CONFIG = """\
version: 1
team: "Claims Team"
posture: plan-only
kinds: [outcome, domain, requirement, epic, feature, spec, spike, sprint, decision]
types:
  spec: Spec
  spike: Task
  decision: Issue
fields:
  spec:
    risk: { field: Custom.RiskTier, values: { HIGH: "High", MEDIUM: "Medium", LOW: "Low" } }
  epic:
    value_area: { field: Microsoft.VSTS.Common.ValueArea, value: "Business" }
  feature:
    value_area: { field: Microsoft.VSTS.Common.ValueArea, value: "Business" }
tree:
  fit: auto
  domain_outcomes:
    order-intake: [1-turnaround-time]
    pricing-rules: [1-turnaround-time, 2-margin-consistency]
"""
LANDED = ["Spec", "Epic", "Feature", "Task", "Issue"]  # the spec's type, then KINDS order: epic, feature, spike, decision


# --- helpers ---------------------------------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(ado_schema, "now_utc", lambda: NOW)


def run(capsys, *argv):
    code = ado_sync.main([str(a) for a in argv])
    return code, capsys.readouterr().out


def run_json(capsys, *argv):
    code, out = run(capsys, *argv, "--json")
    return code, json.loads(out)


def write_cfg(root: Path, text: str) -> None:
    path = root / bc.CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def rewrite(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))   # the bytes as given: no newline translation on any platform


def edit_cfg(root: Path, **changes) -> dict:
    cfg = yaml.safe_load((root / bc.CONFIG_FILE).read_text(encoding="utf-8"))
    cfg.update(changes)
    write_cfg(root, yaml.safe_dump(cfg, sort_keys=False))
    return cfg


def build(tmp_path: Path, config: str = CONFIG) -> Path:
    """The mini repository with the tree artifacts laid over it (the live run's files), minus the tree fixture's
    deliberately stray FR-099, with `config` as `.sdlc/ado.yaml`. Not discovered yet."""
    root = tmp_path / "repo"
    shutil.copytree(MINI, root)
    shutil.copytree(TREE / ".sdlc", root / ".sdlc", dirs_exist_ok=True)
    path = root / REQUIREMENTS
    text = path.read_bytes().decode("utf-8")
    start, end = text.index("<!-- fixture: FR-099"), text.index("### Order Intake")
    path.write_bytes((text[:start] + text[end:]).encode("utf-8"))
    write_cfg(root, config)
    return root


@pytest.fixture
def repo(tmp_path, az, capsys) -> Path:
    root = build(tmp_path)
    az.answers["boards query"] = []  # a board that holds no item yet
    assert ado_sync.main(["discover", "--repo", str(root)]) == 0
    capsys.readouterr()
    az.calls.clear()
    return root


def saved_schema(root: Path) -> dict:
    return json.loads((root / bc.SCHEMA_FILE).read_text(encoding="utf-8"))


def plan(capsys, root: Path, *extra) -> dict:
    code, out = run_json(capsys, "plan", "--repo", root, "--no-comments", *extra)
    assert code == 0 and out["ok"] and not out["unavailable"], out
    return out


def rows_by_ref(out: dict) -> dict:
    return {r["ref"]: r for r in out["rows"]}


def ops_of(row: dict) -> dict:
    return {op["path"][len("/fields/"):]: op for op in row["ops"]}


def tags_added(row: dict) -> set:
    return set(ops_of(row)["System.Tags"]["add"])


def ride(ref: str) -> str:
    """The `state` an edge to a riding ref reads in a plan row."""
    return f"rides as tag {sources.ride_tag(ref, {k: {'mode': 'tag'} for k in bc.RIDE_TAG_PREFIXES})}"


# --- the vocabulary: three tag families join the plugin-owned set ------------------------------------------------------

def test_the_plugin_tag_prefixes_are_the_old_nine_plus_the_three_tree_families():
    assert bc.PLUGIN_TAG_PREFIXES == ("sdlc:", "sdlc-repo:", "risk:", "channel:", "type:", "severity:", "eng-review:",
                                      "data-review:", "carried-from:", "outcome:", "domain:", "fr:")
    assert bc.RIDE_TAG_PREFIXES == {"outcome": "outcome:", "domain": "domain:", "requirement": "fr:"}


def test_each_ride_prefix_is_the_tag_form_the_fit_promises_for_its_kind():
    assert set(bc.RIDE_TAG_PREFIXES) == set(asm.LEVEL_OF) == set(asm.TAG_FORM)
    for kind, prefix in bc.RIDE_TAG_PREFIXES.items():
        assert asm.TAG_FORM[kind].startswith(prefix) and asm.TAG_FORM[kind][len(prefix):].startswith("<")


def test_the_default_kinds_live_in_the_contract_and_are_the_starters():
    assert ado_sync.DEFAULT_KINDS is bc.DEFAULT_KINDS
    assert list(bc.DEFAULT_KINDS) == yaml.safe_load(STARTER.read_text(encoding="utf-8"))["kinds"]
    assert asm.configured_kinds({}) == bc.DEFAULT_KINDS and asm.configured_kinds({"kinds": ["epic", "nope"]}) == ("epic",)
    assert asm.configured_kinds({"kinds": "epic"}) == ()


def test_a_ride_tag_is_one_the_patch_builder_may_write_and_a_persons_tag_survives_it():
    merged = wm.merge_tags("team-alpha; domain:old-name; fr:009", {"domain:order-intake", "fr:001", "sdlc:epic:001"})
    assert merged == "domain:order-intake; fr:001; sdlc:epic:001; team-alpha"  # the stale ride tags are withdrawn


# --- DEFECT 2: discover reads every type a kind lands on ---------------------------------------------------------------

def test_discover_reads_one_type_fields_call_per_landed_type_and_nothing_else(tmp_path, az, capsys):
    root = build(tmp_path)
    code, out = run_json(capsys, "discover", "--repo", root)
    assert code == 0 and out["ok"]
    keys = [route_key_boards(c) for c in az.calls]
    assert keys[:len(DISCOVERY)] == DISCOVERY and keys[len(DISCOVERY):] == ["GET wit/workItemTypesField"] * len(LANDED)
    assert [route_params(c)["type"] for c in az.calls[len(DISCOVERY):]] == LANDED
    assert len(az.calls) == len(DISCOVERY) + len(LANDED) and az.written() == []   # bounded: one read per landed type
    assert out["per_type_reads"] == LANDED
    saved = saved_schema(root)
    epic = saved["types"]["Epic"]["fields"]
    assert epic[PRIORITY]["allowed_values"] == ["1", "2", "3", "4"] and epic[PRIORITY]["default"] == "2"
    assert epic[VALUE_AREA]["allowed_values"] == ["Architectural", "Business"] and epic[VALUE_AREA]["default"] == "Business"
    assert saved["types"]["Feature"]["fields"][VALUE_AREA]["always_required"] is True
    assert saved["types"]["RAID"]["fields"] is None and saved["types"]["Bug"]["fields"] is None  # nothing lands there


def test_a_schema_saved_before_every_landed_type_was_read_is_read_again(repo):
    saved = saved_schema(repo)
    cfg = yaml.safe_load((repo / bc.CONFIG_FILE).read_text(encoding="utf-8"))
    assert ado_schema.is_reusable(saved, cfg, None, NOW.date())
    old = copy.deepcopy(saved)
    old["types"]["Epic"]["fields"] = None   # what the live run saved: only Spec and Issue were read
    assert not ado_schema.is_reusable(old, cfg, None, NOW.date())


def test_landed_types_follow_the_configured_kinds_the_pins_and_the_fit(repo):
    s = saved_schema(repo)
    assert asm.landed_types(s, {}) == ["Spec", "Epic", "Feature"]                 # the starter's kinds, no pin
    assert asm.landed_types(s, {"kinds": ["spec", "decision"], "types": {"decision": "Issue"}}) == ["Spec", "Issue"]
    assert asm.landed_types(s, {"kinds": ["spec"], "types": {"epic": "Epic"}}) == ["Spec", "Epic"]   # a pin lands
    assert asm.landed_types(s, {"kinds": ["spec", "finding"]}) == ["Spec", "Bug"]  # CRITICAL/HIGH land on BugCategory
    assert asm.landed_types(s, {"kinds": ["outcome", "domain", "requirement"]}) == ["Spec"]  # tags land nowhere
    assert ado_schema.types_to_read(s, yaml.safe_load(CONFIG)) == LANDED


def test_the_epic_priority_is_planned_from_the_epic_summary_where_the_type_carries_it(repo, capsys):
    rows = rows_by_ref(plan(capsys, repo, "--all"))
    assert {ref: ops_of(rows[ref])[PRIORITY]["new"] for ref in ("sdlc:epic:001", "sdlc:epic:002", "sdlc:epic:003")} == {
        "sdlc:epic:001": 1, "sdlc:epic:002": 1, "sdlc:epic:003": 2}   # P0, P0, P1 -> the board's 1 (most urgent) .. 4
    text = read(repo / tree.EPICS_REL)
    rewrite(repo / tree.EPICS_REL, text[:text.index("## P0 Epics")] + text[text.index("## Epic Summary"):])
    rows = rows_by_ref(plan(capsys, repo, "--kind", "epic"))
    assert ops_of(rows["sdlc:epic:003"])[PRIORITY]["new"] == 2      # the Summary column alone, no heading block


def test_an_epics_acceptance_criteria_land_in_the_field_the_type_carries(repo, capsys):
    rows = rows_by_ref(plan(capsys, repo, "--kind", "epic"))
    assert ops_of(rows["sdlc:epic:001"])[ACCEPTANCE]["new"] == (
        "Given a duplicate order, when it is submitted, then it is refused")
    anchor = "- [ ] **Given** a duplicate order, **when** it is submitted, **then** it is refused\n"
    rewrite(repo / tree.EPICS_REL, read(repo / tree.EPICS_REL).replace(anchor, anchor + (
        "- [ ] **Given** a [condition], **when** x\n"
        "- [x] Totals under 5 & over <3> match [the ledger](https://example.com/l)\n")))
    row = rows_by_ref(plan(capsys, repo, "--kind", "epic"))["sdlc:epic:001"]
    assert ops_of(row)[ACCEPTANCE]["new"] == (               # escaped, one per line; a link is content
        "Given a duplicate order, when it is submitted, then it is refused<br>"
        "Totals under 5 &amp; over &lt;3&gt; match [the ledger](https://example.com/l)")
    assert "1 acceptance criterion left out: still a template stand-in" in row["notes"]


def test_a_crlf_checkout_of_epics_plans_the_same_fields_and_the_same_projection(repo, capsys):
    before = {r["ref"]: (r["ops"], r["projection_hash"]) for r in plan(capsys, repo, "--kind", "epic")["rows"]}
    path = repo / tree.EPICS_REL
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))   # Git for Windows' autocrlf
    after = {r["ref"]: (r["ops"], r["projection_hash"]) for r in plan(capsys, repo, "--kind", "epic")["rows"]}
    assert after == before and ACCEPTANCE in {o["path"][len("/fields/"):] for o in after["sdlc:epic:001"][0]}


def test_no_create_would_fail_for_a_field_the_process_defaults_once_its_type_was_read(repo, capsys):
    out = plan(capsys, repo, "--all")
    notes = [n for r in out["rows"] for n in r["notes"]]
    assert not [n for n in notes if "create would fail" in n or "not known" in n], notes
    assert {r["type"] for r in out["rows"] if r["action"] == "create"} >= {"Epic", "Feature", "Spec", "Issue"}


def test_validate_compares_an_integer_fields_picklist_as_text(repo, capsys):
    out = plan(capsys, repo, "--kind", "epic", "--validate")
    assert out["validated"] and all(r.get("validation") == [] for r in out["rows"]), [r.get("validation") for r in out["rows"]]


def test_a_required_field_of_a_type_never_read_is_not_known_rather_than_a_failure(repo):
    schema = saved_schema(repo)
    proj = {"kind": "epic", "fields": {"System.Title": "EP-009 · x"}}
    unread = copy.deepcopy(schema)
    unread["types"]["Epic"]["fields"] = None
    notes = ado_sync._required_notes(unread, "Epic", proj)
    assert notes and all("not known" in n and "discover --refresh" in n and "would fail" not in n for n in notes)
    no_default = copy.deepcopy(schema)
    no_default["types"]["Epic"]["fields"][VALUE_AREA]["default"] = None
    (note,) = ado_sync._required_notes(no_default, "Epic", proj)
    assert note.startswith(f"required field {VALUE_AREA} has no value -> create would fail") and "constant" in note
    assert ado_sync._required_notes(no_default, "Epic", {**proj, "fields": {**proj["fields"], VALUE_AREA: "Business"}}) == []


# --- DEFECT 1: the tree kinds ride as tags -------------------------------------------------------------------------------

def test_a_single_domain_epic_carries_its_domain_its_frs_and_their_outcomes_as_tags(repo, capsys):
    out = plan(capsys, repo, "--all")
    assert {k: out["fit"][k]["mode"] for k in ("outcome", "domain", "requirement")} == dict.fromkeys(
        ("outcome", "domain", "requirement"), "tag")
    row = rows_by_ref(out)["sdlc:epic:001"]
    assert {"domain:order-intake", "fr:001", "fr:002", "outcome:1-turnaround-time", "sdlc:epic:001"} <= tags_added(row)
    assert row["parent"] == {"ref": "sdlc:domain:order-intake", "work_item": None,
                             "state": "rides as tag domain:order-intake"}
    assert row["related"] == [{"ref": "sdlc:fr:001", "state": "rides as tag fr:001"},
                              {"ref": "sdlc:fr:002", "state": "rides as tag fr:002"}]


def test_a_cross_domain_epic_carries_each_domain_and_every_outcome_they_map_to(repo, capsys):
    row = rows_by_ref(plan(capsys, repo, "--all"))["sdlc:epic:002"]
    assert row["parent"] is None and "spans domains: order-intake, pricing-rules" in row["notes"]
    assert {"domain:order-intake", "domain:pricing-rules", "fr:003", "fr:005", "outcome:1-turnaround-time",
            "outcome:2-margin-consistency"} <= tags_added(row)
    assert {e["ref"]: e["state"] for e in row["related"]} == {ref: ride(ref) for ref in (
        "sdlc:domain:order-intake", "sdlc:domain:pricing-rules", "sdlc:fr:003", "sdlc:fr:005")}


def test_an_epic_with_no_fulfils_link_rides_nothing_and_a_spec_has_no_related_key(repo, capsys):
    rows = rows_by_ref(plan(capsys, repo, "--all"))
    assert {t.split(":")[0] for t in tags_added(rows["sdlc:epic:003"])} == {"sdlc", "sdlc-repo"}
    assert "related" not in rows["sdlc:epic:003"] and "related" not in rows["sdlc:spec:0004"]
    assert rows["sdlc:feature:03"]["parent"]["state"] == "in this plan"   # an item-mode parent reads as before


def test_the_human_plan_prints_the_ride_tags_and_where_the_parent_went(repo, capsys):
    code, text = run(capsys, "plan", "--repo", repo, "--all", "--no-comments")
    assert code == 0
    block = text[text.index("epic EP-001  create"):text.index("epic EP-002  create")]
    assert "+ domain:order-intake" in block and "+ fr:001" in block and "+ outcome:1-turnaround-time" in block
    assert "  parent sdlc:domain:order-intake -> rides as tag domain:order-intake\n" in block
    assert "not planned" not in block and "create would fail" not in text


def test_only_mirrored_kinds_ride_and_an_unknown_fit_rides_nothing(repo):
    schema, cfg = saved_schema(repo), yaml.safe_load(CONFIG)
    epic = next(p for p in sources.projections(repo, {**cfg, "kinds": ["domain", "epic"]}, schema, ["epic"])
                if p["id"] == "EP-001")
    assert {t for t in epic["tags"] if t.startswith(("fr:", "outcome:", "domain:"))} == {"domain:order-intake"}
    unread = {**schema, "backlog": None}                                       # no team: the fit is not known
    epic = next(p for p in sources.projections(repo, cfg, unread, ["epic"]) if p["id"] == "EP-001")
    assert epic["tags"] == {"sdlc:epic:001"}
    pinned = {**cfg, "tree": {**cfg["tree"], "fit": {"domain": "tag", "requirement": "tag"}}}   # a tag pin needs no levels
    epic = next(p for p in sources.projections(repo, pinned, {}, ["epic"]) if p["id"] == "EP-001")
    assert epic["tags"] == {"sdlc:epic:001", "domain:order-intake", "fr:001", "fr:002"}  # outcome's fit: not known


def test_a_domain_to_outcome_map_that_contradicts_the_artifacts_adds_no_outcome_tag_and_says_why(repo):
    cfg = {**yaml.safe_load(CONFIG), "tree": {"domain_outcomes": {"claims-intake": ["1-turnaround-time"]}}}
    epic = next(p for p in sources.projections(repo, cfg, saved_schema(repo), ["epic"]) if p["id"] == "EP-001")
    assert {"domain:order-intake", "fr:001", "fr:002"} <= epic["tags"]
    assert not {t for t in epic["tags"] if t.startswith("outcome:")}
    assert any(n.startswith("no outcome tags for sdlc:domain:order-intake: tree.domain_outcomes names the domain "
                            "'claims-intake'") for n in epic["notes"])


def test_a_domain_fitted_to_an_area_path_still_rides_as_its_tag_and_says_area_mode_is_not_implemented(repo):
    schema = copy.deepcopy(saved_schema(repo))
    schema["areas"].append({**schema["areas"][1], "name": "Order Intake", "path": "Claims\\Order Intake"})
    cfg = {**yaml.safe_load(CONFIG), "tree": {"domains": ["Order Intake"]}}   # how `fit_levels` learns domain names
    assert asm.fit_levels(schema, cfg)["domain"]["mode"] == "area"
    epic = next(p for p in sources.projections(repo, cfg, schema, ["epic"]) if p["id"] == "EP-001")
    assert "domain:order-intake" in epic["tags"] and "System.AreaPath" not in epic["fields"]
    assert any("matches the Area Path Claims\\Order Intake, but setting System.AreaPath from the fit is not implemented"
               in n for n in epic["notes"])


def test_a_board_side_removal_of_a_ride_tag_is_drift_and_a_persons_tag_is_the_boards(repo):
    proj = next(p for p in sources.projections(repo, yaml.safe_load(CONFIG), saved_schema(repo), ["epic"])
                if p["id"] == "EP-001")
    have = sorted(proj["tags"] | {"team-alpha"})
    ledger_row = {"ref": proj["ref"], "kind": "epic", "work_item": 7001, "rev_after": 2,
                  "projection_hash": model.projection_hash(proj)}
    remote = {"id": 7001, "rev": 3, "type": "Epic", "tags": set(have) - {"domain:order-intake"}}

    def change(old, new):
        return [{"rev": 3, "fields": {"System.Tags": {"oldValue": "; ".join(old), "newValue": "; ".join(new)}}}]
    removed = model.classify_drift(ledger_row, remote, proj, change(have, [t for t in have if t != "domain:order-intake"]))
    assert removed["class"] == "SDLC_OWNED_DRIFT" and removed["fields"][0]["owner"] == "S"
    human = model.classify_drift(ledger_row, {**remote, "tags": set(have) - {"team-alpha"}}, proj,
                                 change(have, [t for t in have if t != "team-alpha"]))
    assert human["class"] == "ADO_OWNED_CHANGE" and human["fields"][0]["owner"] == "C"
    board = {**remote, "title": proj["fields"]["System.Title"],
             "fields": {ACCEPTANCE: proj["fields"][ACCEPTANCE], VALUE_AREA: "Business"}}
    (op,) = model.diff(proj, board, model.ownership_for("epic"))   # the next plan puts it back, nothing else
    assert op["path"] == "/fields/System.Tags" and "domain:order-intake" in op["new"]


# --- DEFECT 3: a constant field value -------------------------------------------------------------------------------------

def test_the_constants_are_planned_on_every_epic_and_feature_create(repo, capsys):
    out = plan(capsys, repo, "--all")
    creates = [r for r in out["rows"] if r["action"] == "create" and r["kind"] in ("epic", "feature")]
    assert len(creates) == 4 and all(ops_of(r)[VALUE_AREA]["new"] == "Business" for r in creates)
    assert not [r for r in out["rows"] if r["kind"] == "spec" and VALUE_AREA in ops_of(r)]   # only the kinds named


def test_config_check_accepts_a_constant_the_process_allows(repo, capsys):
    code, out = run_json(capsys, "config", "check", "--repo", repo)
    assert code == 0 and out["rows"] == [], out["rows"]


@pytest.mark.parametrize("rule, level, words", [
    ({"field": VALUE_AREA, "value": "Biz"}, "refused",
     f"`fields.epic.value_area.value` is 'Biz', which is not an allowed value of `{VALUE_AREA}`; the allowed values "
     "are Architectural, Business."),
    ({"field": VALUE_AREA, "value": "Business", "values": {"x": "Business"}}, "invalid", "has both `value`"),
    ({"field": "System.AssignedTo", "value": "Somebody"}, "refused", "an identity field"),
    ({"field": "System.Tags", "value": "x"}, "refused", "which the mirror builds itself"),
    ({"field": "Custom.Owner", "value": "dev.one@example.com"}, "refused", "holds an address or a GUID"),
    ({"field": "Microsoft.VSTS.Scheduling.Effort", "value": 3}, "refused", "a scheduling field"),
    ({"field": "Microsoft.VSTS.Scheduling.StoryPoints", "value": 3}, "refused", "a scheduling field"),
], ids=["outside-the-picklist", "value-and-values", "identity", "mirror-built", "an-address", "effort", "points"])
def test_config_check_refuses_an_unsafe_or_unknown_constant(repo, capsys, rule, level, words):
    edit_cfg(repo, fields={"epic": {"value_area": rule}})
    code, out = run_json(capsys, "config", "check", "--repo", repo)
    assert code == {"refused": 2, "invalid": 1}[level]
    assert [r["level"] for r in out["rows"]] == [level] and words in out["rows"][0]["message"], out["rows"]


def test_a_constant_named_for_an_activity_metric_is_refused_like_any_field_write():
    rows = cfgmod.validate_config({"version": 1, "fields": {"epic": {"points": {"field": "Custom.X", "value": 3}}}}, None)
    assert [r["level"] for r in rows] == ["refused"] and "activity metric" in rows[0]["message"]


def test_without_a_schema_the_allowed_values_are_not_checked_and_a_number_matches_a_text_picklist(repo):
    biz = {"version": 1, "fields": {"epic": {"value_area": {"field": VALUE_AREA, "value": "Biz"}}}}
    assert cfgmod.validate_config(biz, None) == []
    two = {"version": 1, "fields": {"epic": {"p": {"field": PRIORITY, "value": 2}}}}
    assert cfgmod.validate_config(two, saved_schema(repo)) == []   # "2" is in the captured ["1", "2", "3", "4"]


def test_a_constant_is_filled_on_update_only_while_the_board_field_is_empty_and_never_drifts(repo):
    proj = next(p for p in sources.projections(repo, yaml.safe_load(CONFIG), saved_schema(repo), ["feature"]))
    assert proj["fields"][VALUE_AREA] == "Business" and proj["constant_fields"] == [VALUE_AREA]
    remote = {"id": 7003, "rev": 4, "type": "Feature", "tags": set(proj["tags"]), "title": proj["fields"]["System.Title"],
              "fields": {"System.Title": proj["fields"]["System.Title"]}}
    (op,) = model.diff(proj, remote, model.ownership_for("feature"))
    assert (op["op"], op["path"], op["new"]) == ("add", f"/fields/{VALUE_AREA}", "Business")
    patch = wm.build_update_patch(remote, proj)
    assert patch[1:] == [{"op": "add", "path": f"/fields/{VALUE_AREA}", "value": "Business"}]
    held = {**remote, "fields": {**remote["fields"], VALUE_AREA: "Architectural"}}
    assert model.diff(proj, held, model.ownership_for("feature")) == []        # the board's choice stands
    ledger_row = {"ref": proj["ref"], "kind": "feature", "work_item": 7003, "rev_after": 4,
                  "projection_hash": model.projection_hash(proj)}
    moved = model.classify_drift(ledger_row, {**held, "rev": 5}, proj,
                                 [{"rev": 5, "fields": {VALUE_AREA: {"oldValue": "Business", "newValue": "Architectural"}}}])
    assert moved["class"] == "ADO_OWNED_CHANGE" and moved["fields"][0]["owner"] == "C"


def test_the_repositorys_own_value_wins_over_a_constant_for_the_same_field(repo):
    cfg = {**yaml.safe_load(CONFIG), "fields": {"epic": {"p": {"field": PRIORITY, "value": 4}}}}
    epic = next(p for p in sources.projections(repo, cfg, saved_schema(repo), ["epic"]) if p["id"] == "EP-001")
    assert epic["fields"][PRIORITY] == 1 and "constant_fields" not in epic
    assert f"fields.epic constant for {PRIORITY} not used: the source sets {PRIORITY} itself" in epic["notes"]


def test_a_projection_with_no_constant_has_no_constant_fields_key(repo):
    for proj in sources.projections(repo, {}, saved_schema(repo), ["epic", "feature", "spec"]):
        assert "constant_fields" not in proj


def test_the_starter_and_the_reference_document_the_constant_form():
    text = STARTER.read_text(encoding="utf-8")
    assert "#   value_area: { field: Microsoft.VSTS.Common.ValueArea, value: \"Business\" }" in text
    assert "value_area" not in json.dumps(yaml.safe_load(text))     # a commented example: the starter sets nothing
    doc = REFERENCE.read_text(encoding="utf-8")
    assert "value_area: { field: Microsoft.VSTS.Common.ValueArea, value: \"Business\" }" in doc
    assert "### When a tree kind rides as a tag" in doc and "Area mode is not implemented" in doc


# --- end to end: what the plan shows is what apply sends --------------------------------------------------------------------

def test_apply_sends_the_ride_tags_the_priority_and_the_constant_the_plan_showed(repo, monkeypatch, capsys):
    edit_cfg(repo, posture="assisted")
    out = plan(capsys, repo, "--kind", "epic", "--kind", "feature")
    doc = json.loads((repo / out["path"]).read_text(encoding="utf-8"))
    board = FakeBoardsAz(writes=True)
    sent, ids = [], itertools.count(5001)

    def on_create(args):
        sent.append((route_params(args)["type"], json.loads(read(Path(body_file(args))))))
        return {"id": next(ids), "rev": 1}
    board.answers.update({"POST wit/workItems": on_create, "boards query": []})
    monkeypatch.setattr(ado_transport, "run_az", board)
    cfg = yaml.safe_load((repo / bc.CONFIG_FILE).read_text(encoding="utf-8"))
    result = apply_mod.apply_plan(repo, doc, by="@dev-one", cfg=cfg, schema=saved_schema(repo), limit=None, today=NOW)
    assert result["exit"] == 0 and not result["failed"], result     # no `source_changed`: apply projects the same rows
    # bare type names: the extension's template is `…/workItems/${type}` (B0 2026-10-14: `$Epic` reached it as `$$Epic`)
    assert [t for t, _ in sent] == ["Epic", "Epic", "Epic", "Feature"]
    first = {op["path"]: op["value"] for op in sent[0][1] if op["path"].startswith("/fields/")}
    assert set(first["/fields/System.Tags"].split("; ")) >= {"domain:order-intake", "fr:001", "fr:002",
                                                            "outcome:1-turnaround-time", "sdlc:epic:001"}
    assert (first[f"/fields/{PRIORITY}"], first[f"/fields/{VALUE_AREA}"]) == (1, "Business")
    assert first[f"/fields/{ACCEPTANCE}"].startswith("Given a duplicate order")
    feature = {op["path"]: op["value"] for op in sent[3][1]}
    assert feature[f"/fields/{VALUE_AREA}"] == "Business"
    assert any(op["path"] == "/relations/-" and op["value"]["rel"] == model.PARENT_REL
               and op["value"]["url"].endswith("/workItems/5001") for op in sent[3][1])   # under EP-001, made first
    assert not any(op["path"] == "/relations/-" and op["value"]["rel"] == model.PARENT_REL for op in sent[0][1])
