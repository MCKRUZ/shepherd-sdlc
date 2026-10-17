"""The sync Fold's pure contracts in the sync model (B6-P0): the stage names, the one `Next:` footer, the no-data document.

Fold B6 (spec 0040) adds a read verb, `ado_sync.py sync`, that runs the mirror's reads in one pass: the fields pull, the
drift read from that pull's own rows (never a second board read), the discussion pull only when `--discussion` is
given, then the plan. `scripts/ado_sync_model.py` grows append-only for it, and these pins hold three contracts the
CLI (B6-P1), the command prose (B6-P2) and the desktop app (B6-P3) are built against in parallel:

  * `SYNC_STAGES` — the four stage names, in the order `sync` runs them;
  * `apply_next_line(plan)` — the ONE golden form of the footer every verb that drafts a plan prints (`comment`,
    `plan`, `sync`): the 12-hex hash substituted, and anything that is not a 12-hex hash refused (ValueError);
  * `SYNC_NODATA` — the `sync --json` document when NOTHING could be read, saved as
    `scripts/tests/golden/ado_sync_unavailable.json`: every stage `unavailable`, every count `None`, no integer 0 and
    no `False` anywhere (house rule 2: a 0 appears only after a read that found none).

The module still imports only the standard library and the three plugin modules it imported before this Fold (an AST
test holds the set equal, not merely a subset), and calls no I/O. Nothing here reads a file except the module's own
source and the golden; nothing writes one.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401

import ast
import json
from pathlib import Path

import pytest

import ado_sync_model as sm
import boards_contract as bc

MODULE = Path(sm.__file__)
GOLDEN = Path(__file__).resolve().parent / "golden" / "ado_sync_unavailable.json"

# The model's import set as Folds B2-B5 left it; B6-P0 adds nothing to it.
IMPORTS_BEFORE_B6 = {"re", "hashlib", "json", "datetime", "typing", "boards_contract", "findings_model",
                     "track_decisions"}

# The card's literal: the `sync --json` document when nothing could be read.
SYNC_NODATA_LITERAL = {
    "ok": True, "unavailable": True, "reason": None, "verb": "sync", "as_of": None, "scope": None,
    "pull": {"unavailable": True, "reason": None},
    "drift": {"unavailable": True, "reason": None},
    "discussion": None,
    "plan": {"unavailable": True, "reason": None},
    "counts": None, "next": None, "hook_line": None, "drift_error": None,
}

PLAN = "0a1b2c3d4e5f"
GOLDEN_NEXT = "Next: `ado_sync.py apply --confirm 0a1b2c3d4e5f --by <you>` sends it, as whoever az is signed in as"


# --- purity -------------------------------------------------------------------------------------------------

def _imports() -> set[str]:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative imports"
            names.add((node.module or "").split(".")[0])
    return names


def test_the_model_import_set_is_unchanged_by_fold_b6():
    imported = _imports()
    assert imported == IMPORTS_BEFORE_B6, imported ^ IMPORTS_BEFORE_B6
    assert not {n for n in imported if n.startswith("ado_")}, "the model imports no ado_* module"


def test_the_grown_model_still_calls_no_io():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"open", "print", "input", "exec", "eval", "__import__"}, called
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"read_text", "write_text", "mkdir", "unlink", "now", "today", "utcnow", "sleep"}, attrs


# --- the stages ---------------------------------------------------------------------------------------------

def test_sync_stages_are_the_four_stages_in_the_order_sync_runs_them():
    assert sm.SYNC_STAGES == ("pull", "drift", "discussion", "plan")
    assert isinstance(sm.SYNC_STAGES, tuple)


def test_every_stage_but_discussion_is_a_key_of_the_nodata_document():
    """`discussion` is `None` (it runs only on an explicit `--discussion`); the other three each say unavailable."""
    for stage in sm.SYNC_STAGES:
        assert stage in sm.SYNC_NODATA, stage
    assert sm.SYNC_NODATA["discussion"] is None
    for stage in ("pull", "drift", "plan"):
        assert sm.SYNC_NODATA[stage] == {"unavailable": True, "reason": None}, stage


# --- the footer ---------------------------------------------------------------------------------------------

def test_apply_next_line_is_the_one_golden_form():
    assert sm.apply_next_line(PLAN) == GOLDEN_NEXT


def test_apply_next_line_substitutes_the_hash_and_nothing_else():
    other = "fedcba987654"
    assert sm.apply_next_line(other) == GOLDEN_NEXT.replace(PLAN, other)
    line = sm.apply_next_line(other)
    assert line.startswith("Next: `ado_sync.py apply --confirm ") and "\n" not in line
    assert line.count(other) == 1 and "--by <you>" in line


@pytest.mark.parametrize("bad", ["", "ZZZ", "0A1B2C3D4E5F", "0a1b2c3d4e5", "0a1b2c3d4e5f0", " 0a1b2c3d4e5f",
                                 "0a1b2c3d4e5f\n", "0a1b2c3d4e5g", "<hash>", None, 123456789012, b"0a1b2c3d4e5f"])
def test_apply_next_line_refuses_anything_that_is_not_a_12_hex_hash(bad):
    with pytest.raises(ValueError):
        sm.apply_next_line(bad)


def test_the_footer_hash_shape_is_the_contract_hash():
    assert bc.HASH_RE.fullmatch(PLAN)
    assert sm.apply_next_line(sm.plan_hash([{"ref": "sdlc:spec:0004"}])).startswith("Next: ")


# --- the no-data document -----------------------------------------------------------------------------------

def _scalars(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _scalars(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _scalars(v)
    else:
        yield value


def test_sync_nodata_is_the_card_literal():
    assert sm.SYNC_NODATA == SYNC_NODATA_LITERAL
    assert list(sm.SYNC_NODATA) == list(SYNC_NODATA_LITERAL), "the key order the card wrote"


def test_sync_nodata_has_no_integer_zero_and_no_false():
    scalars = list(_scalars(sm.SYNC_NODATA))
    assert not [v for v in scalars if isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0]
    assert False not in [v for v in scalars if isinstance(v, bool)]
    assert sm.SYNC_NODATA["counts"] is None and sm.SYNC_NODATA["next"] is None
    assert sm.SYNC_NODATA["hook_line"] is None and sm.SYNC_NODATA["as_of"] is None


def test_the_sync_nodata_literal_holds_no_0_in_the_source():
    """No `0` literal anywhere in the assignment, so a later edit cannot slip a fabricated zero in as a default."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    nodes = [n for n in ast.walk(tree)
             if isinstance(n, (ast.Assign, ast.AnnAssign))
             and any(isinstance(t, ast.Name) and t.id == "SYNC_NODATA"
                     for t in (n.targets if isinstance(n, ast.Assign) else [n.target]))]
    assert len(nodes) == 1, "SYNC_NODATA is assigned exactly once"
    assert isinstance(nodes[0].value, ast.Dict), "SYNC_NODATA is a dict literal"
    constants = [c.value for c in ast.walk(nodes[0].value) if isinstance(c, ast.Constant)]
    assert not [c for c in constants if c is False or (isinstance(c, (int, float)) and not isinstance(c, bool)
                                                         and c == 0)], constants


def test_sync_nodata_equals_the_golden_file_byte_for_byte():
    text = GOLDEN.read_text(encoding="utf-8")
    assert json.loads(text) == sm.SYNC_NODATA
    assert text == json.dumps(sm.SYNC_NODATA, sort_keys=True, indent=2) + "\n"
    assert ": 0" not in text and ":0" not in text and "false" not in text


def test_the_golden_carries_no_count_and_no_footer():
    doc = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert doc["verb"] == "sync" and doc["ok"] is True and doc["unavailable"] is True
    assert doc["counts"] is None and doc["next"] is None and doc["hook_line"] is None
