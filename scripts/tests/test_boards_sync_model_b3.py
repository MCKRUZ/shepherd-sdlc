"""The write Fold's pure contracts in the sync model (B3-P0): apply results, idempotency keys, comment refusals, text_sha.

`scripts/ado_sync_model.py` grows append-only for Fold B3 (spec 0036, HIGH: it writes to an external system as a
person). `apply_plan` (B3-P2) reports through `apply_result`; the comment drafter (B3-P3) keys every row with
`idem_key`, refuses with `comment_refusal` and fingerprints with `text_sha`; `apply` refuses a plan whose comments
would post under another name with `identity_refusal`; and the design §7 recovery on an unknown outcome is
`recovered_comment`. They are pinned here against the hand-written B3 fixtures (`comment_add_response`,
`comments_recent`, `connection_data`, `connection_data_sp`, `errors/*.txt`) and against the B2 contract, whose
signatures do not move. The e-mail addresses the cases need are assembled from parts (house rule 10).
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401
from tests.ado_boards_fixtures import HAND_WRITTEN_PROCESS

import ast
import copy
import hashlib
import inspect
import json
from pathlib import Path

import pytest
import yaml

import ado_sync_model as sm
import ado_wit_map as wm
import boards_contract as bc
from tests import ado_boards_fixtures as abf

# B0 (2026-10-15): the second capture shadowed the item, write and comment fixtures (`WIT_CAPTURED_ITEMS`); this module's
# scenarios pin the hand-written ones' ids and texts, so it reads those (`BOARDS_ITEMS`, tests/ado_boards_fixtures.py).
# The captured answers are exercised in test_boards_captured_items.py.
BOARDS_ITEMS = HAND_WRITTEN_PROCESS

MODULE = Path(sm.__file__)
PLUGIN_ROOT = MODULE.parent.parent
STEMS = frozenset(p.stem for p in (PLUGIN_ROOT / "agents").glob("*.md"))
ALLOWED_IMPORTS = {"re", "hashlib", "json", "datetime", "typing", "boards_contract", "findings_model",
                   "artifact_model", "track_decisions"}
TEMPLATE = PLUGIN_ROOT / "templates" / "ado" / "ado.yaml"
SHAPE = PLUGIN_ROOT / "templates" / "ado" / "_schema.yaml"

KIM_EMAIL = "kim" + "@corp.com"                  # the card's value, assembled (house rule 10)
PERSON_1_EMAIL = "person1" + "@example.com"      # connection_data.json's account
TS = "2026-10-12T09:02:00Z"
PLAN = "7b2e9d4c1a60"
OTHER_PLAN = "3f9a1c2b7d04"
REF = "sdlc:spec:0004"
BODY = ("Handed off to @priya-n for build on branch `spec/0004-duplicate-claim-409`; checker @jordan-b.\n"
        "Spec: specs/0004-duplicate-claim-409.md")


# --- purity and the B2 contract ----------------------------------------------------------------------------

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


def test_the_grown_model_still_imports_only_the_allowlist():
    imported = _imports()
    assert imported <= ALLOWED_IMPORTS, imported - ALLOWED_IMPORTS
    assert not {n for n in imported if n.startswith("ado_")}


def test_the_grown_model_still_calls_no_io():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & {"open", "print", "input", "exec", "eval", "__import__"}, called
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"read_text", "write_text", "mkdir", "unlink", "now", "today", "utcnow", "sleep"}, attrs


B2_SIGNATURES = [
    ("ai_by", ("name", "agent_stems")), ("plan_hash", ("rows",)), ("projection_hash", ("projection",)),
    ("diff", ("projection", "remote", "ownership")), ("classify_drift", ("ledger_row", "remote", "projection", "updates")),
    ("validate_disposition", ("row",)), ("counts_as_open", ("row",)), ("ledger_entry", ("ts", "event", "fields")),
    ("ledger_id", ("work_item", "rev")), ("hook_line", ("pending", "drifted", "as_of")), ("summarize", ("ledger", "today")),
    ("ownership_for", ("kind",)),
]


@pytest.mark.parametrize("name, params", B2_SIGNATURES, ids=[n for n, _ in B2_SIGNATURES])
def test_the_b2_signatures_did_not_move(name, params):
    assert tuple(inspect.signature(getattr(sm, name)).parameters) == params


def test_the_b2_vocabulary_is_still_the_contract_s():
    assert sm.LEDGER_EVENTS is bc.LEDGER_EVENTS and sm.DRIFT_CLASSES is bc.DRIFT_CLASSES
    assert sm.STATUS_NODATA["counts"] == dict.fromkeys(sm.COUNT_KEYS)


# --- comment events and idempotency keys ---------------------------------------------------------------------

def _yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_comment_events_are_the_closed_set_the_config_ships():
    assert len(sm.COMMENT_EVENTS) == 11 and len(set(sm.COMMENT_EVENTS)) == 11
    assert sm.COMMENT_EVENTS == tuple(_yaml(TEMPLATE)["comments"]["events"])
    shape = _yaml(SHAPE)["properties"]["comments"]["properties"]
    assert sm.COMMENT_EVENTS == tuple(shape["events"]["properties"])


def test_every_event_has_exactly_one_key_rule_and_ad_hoc_is_the_twelfth():
    assert set(sm.IDEM_KEY_RULES) == set(sm.COMMENT_EVENTS) | {sm.AD_HOC}
    assert sm.AD_HOC not in sm.COMMENT_EVENTS
    prefixes = [template.split(":", 1)[0] for template, _ in sm.IDEM_KEY_RULES.values()]
    assert len(prefixes) == len(set(prefixes)) == 12  # no two events can share a key


def _sha8(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


KEYS = [
    ("handoff", {"ref": REF, "ts": "2026-10-12T08:14Z"}, "handoff:sdlc:spec:0004:2026-10-12T08:14Z"),
    ("spec_deferred", {"ref": "sdlc:spec:0006", "reason": "blocked on the carrier"},
     "deferred:sdlc:spec:0006:" + _sha8("blocked on the carrier")),
    ("decision_resolved", {"decision": "DL-07", "date": "2026-10-12"}, "decision:DL-07:decided:2026-10-12"),
    ("sprint_carried", {"ref": REF, "from_sprint": "S06", "to_sprint": "S07"}, "carried:sdlc:spec:0004:S06:S07"),
    ("gate_passed", {"phase": "2", "signoff_date": "2026-10-12"}, "gate:2:2026-10-12"),
    ("verdict_recorded", {"ref": REF, "lens": "engineering", "verdict": "accepted", "ts": "2026-10-12T10:00Z"},
     "verdict:sdlc:spec:0004:engineering:accepted:2026-10-12T10:00Z"),
    ("finding_disposition", {"fp": "a1b2c3d4e5f6", "disposition": "FIXED"}, "finding:a1b2c3d4e5f6:FIXED"),
    ("sprint_dropped", {"ref": REF, "sprint": "S07"}, "dropped:sdlc:spec:0004:S07"),
    ("review_summary", {"ref": REF, "round": 2}, "review:sdlc:spec:0004:2"),
    ("pr_linked", {"ref": REF, "pr": 118}, "pr:sdlc:spec:0004:118"),
    ("spec_merged", {"ref": REF}, "merged:sdlc:spec:0004"),
]


@pytest.mark.parametrize("event, parts, key", KEYS, ids=[k[0] for k in KEYS])
def test_idem_key_is_the_design_form(event, parts, key):
    assert sm.idem_key(event, **parts) == key
    sm.ledger_entry(TS, "commented", idem_key=key)  # a key always fits on a ledger line


def test_the_table_covers_every_event():
    assert {k[0] for k in KEYS} == set(sm.COMMENT_EVENTS)


def test_an_ad_hoc_key_hashes_the_message_and_may_target_a_raw_work_item():
    text = "Can we pair on the 409 body tomorrow?"
    assert sm.idem_key(sm.AD_HOC, ref="#4521", text=text) == f"comment:#4521:{sm.text_sha(text)}"
    assert sm.idem_key(sm.AD_HOC, ref=REF, text=text) == f"comment:{REF}:{sm.text_sha(text)}"
    assert "pair" not in sm.idem_key(sm.AD_HOC, ref=REF, text=text)
    with pytest.raises(ValueError):
        sm.idem_key("handoff", ref="#4521", ts="2026-10-12T08:14Z")  # a template event names a ref


def test_a_deferral_key_never_carries_the_reason_text():
    key = sm.idem_key("spec_deferred", ref=REF, reason="vendor contract with Kim Lee lapsed")
    assert "Kim" not in key and "vendor" not in key and len(key.rsplit(":", 1)[1]) == 8
    assert key == sm.idem_key("spec_deferred", ref=REF, reason="  vendor contract with Kim Lee lapsed  ")


BAD_KEYS = [
    ("an unknown event", "standup", {"ref": REF}),
    ("a missing part", "handoff", {"ref": REF}),
    ("an extra part", "spec_merged", {"ref": REF, "ts": "2026-10-12T08:14Z"}),
    ("a ref that is not one", "spec_merged", {"ref": "spec 0004"}),
    ("a raw id for a template event", "spec_merged", {"ref": "#4521"}),
    ("a space in a token", "handoff", {"ref": REF, "ts": "2026-10-12 08:14Z"}),
    ("a newline in a token", "sprint_dropped", {"ref": REF, "sprint": "S07\nS08"}),
    ("an e-mail in a token", "verdict_recorded", {"ref": REF, "lens": KIM_EMAIL, "verdict": "accepted", "ts": "t1"}),
    ("a GUID in a token", "finding_disposition", {"fp": "00000000-0000-0000-0000-000000000003", "disposition": "FIXED"}),
    ("a zero round", "review_summary", {"ref": REF, "round": 0}),
    ("a boolean round", "review_summary", {"ref": REF, "round": True}),
    ("a pr that is not a number", "pr_linked", {"ref": REF, "pr": "12a"}),
    ("a decision without DL-", "decision_resolved", {"decision": "07", "date": "2026-10-12"}),
    ("a date in another form", "decision_resolved", {"decision": "DL-07", "date": "12/10/2026"}),
    ("an empty reason", "spec_deferred", {"ref": REF, "reason": "   "}),
    ("an empty ad hoc message", sm.AD_HOC, {"ref": REF, "text": ""}),
    ("a number where a token belongs", "sprint_dropped", {"ref": REF, "sprint": 7}),
]


@pytest.mark.parametrize("label, event, parts", BAD_KEYS, ids=[b[0] for b in BAD_KEYS])
def test_idem_key_refuses_what_its_rule_does_not_name(label, event, parts):
    with pytest.raises(ValueError):
        sm.idem_key(event, **parts)


def test_pr_and_round_accept_a_digit_string_as_their_number():
    assert sm.idem_key("pr_linked", ref=REF, pr="118") == sm.idem_key("pr_linked", ref=REF, pr=118)


LEDGER = [
    {"ts": TS, "event": "planned", "plan": PLAN, "ref": REF},
    {"ts": TS, "event": "commented", "ref": REF, "work_item": 4521, "idem_key": "handoff:sdlc:spec:0004:t1"},
    {"ts": TS, "event": "commented", "ref": REF, "work_item": 4521, "idem_key": "pr:sdlc:spec:0004:118",
     "recovered": True},
    {"ts": TS, "event": "comment_refused", "ref": REF, "work_item": 4521, "idem_key": "merged:sdlc:spec:0004",
     "reason": "budget"},
    {"ts": TS, "event": "commented", "ref": "sdlc:decision:07", "work_item": 4533, "idem_key": "decision:DL-07:decided:d"},
    "not a line",
]


def test_commented_keys_are_the_posted_ones_and_a_refusal_is_not_posted():
    assert sm.commented_keys(LEDGER) == frozenset({"handoff:sdlc:spec:0004:t1", "pr:sdlc:spec:0004:118",
                                                   "decision:DL-07:decided:d"})
    assert sm.commented_keys([]) == frozenset()


def test_budget_used_counts_the_plugin_comments_on_one_item():
    assert sm.budget_used(LEDGER, 4521) == 2
    assert sm.budget_used(LEDGER, 4533) == 1
    used = sm.budget_used([], 4521)
    assert used == 0 and isinstance(used, int) and not isinstance(used, bool)  # a read that found none


# --- text_sha and the trailer --------------------------------------------------------------------------------

def test_text_sha_is_the_first_12_hex_of_sha256_over_the_body():
    assert sm.text_sha("abc") == hashlib.sha256(b"abc").hexdigest()[:12]
    assert bc.HASH_RE.fullmatch(sm.text_sha(BODY))


@pytest.mark.parametrize("mode", ["none", "hash", "drafted"])
@pytest.mark.parametrize("plan", [PLAN, OTHER_PLAN])
def test_text_sha_is_the_same_with_any_trailer_any_plan_and_any_line_ending(mode, plan):
    posted = sm.with_trailer(BODY, plan, mode)
    assert sm.text_sha(posted) == sm.text_sha(BODY)
    assert sm.text_sha(posted.replace("\n", "\r\n")) == sm.text_sha(BODY)
    assert sm.text_sha("\n  " + posted + "  \n") == sm.text_sha(BODY)


def test_text_sha_moves_with_the_body():
    assert sm.text_sha(BODY) != sm.text_sha(BODY.replace("@jordan-b", "@kim"))
    assert sm.text_sha("a\nb") != sm.text_sha("a b")


@pytest.mark.parametrize("bad", [None, 7, b"abc", ["abc"]])
def test_text_sha_refuses_what_is_not_text(bad):
    with pytest.raises(ValueError):
        sm.text_sha(bad)


def test_the_trailer_forms():
    assert sm.with_trailer(BODY, PLAN, "hash") == BODY + " · sprd 7b2e9d4c1a60"
    assert sm.with_trailer(BODY, PLAN, "hash").endswith(f"· {bc.TRAILER_TOKEN} {PLAN}")
    assert sm.with_trailer(BODY, PLAN, "drafted") == BODY + " · drafted with Shepherd · sprd 7b2e9d4c1a60"
    assert sm.with_trailer(BODY + "\n\n", None, "none") == BODY
    assert sm.with_trailer(BODY, PLAN, "hash").splitlines()[-1] == "Spec: specs/0004-duplicate-claim-409.md · sprd " + PLAN


def test_trailer_modes_and_transports_are_the_config_enums():
    shape = _yaml(SHAPE)["properties"]["comments"]["properties"]
    assert sm.TRAILER_MODES == tuple(shape["trailer"]["enum"])
    assert sm.COMMENT_TRANSPORTS == tuple(shape["transport"]["enum"])
    assert _yaml(TEMPLATE)["comments"]["trailer"] in sm.TRAILER_MODES


@pytest.mark.parametrize("plan, mode", [("7B2E9D4C1A60", "hash"), ("7b2e9d4c1a6", "hash"), (None, "drafted"),
                                        (PLAN, "loud"), (PLAN, None)])
def test_with_trailer_refuses_a_bad_hash_or_mode(plan, mode):
    with pytest.raises(ValueError):
        sm.with_trailer(BODY, plan, mode)


def test_strip_trailer_gives_back_the_body_and_the_plan():
    assert sm.strip_trailer(sm.with_trailer(BODY, PLAN, "hash")) == (BODY, PLAN)
    assert sm.strip_trailer(sm.with_trailer(BODY, OTHER_PLAN, "drafted")) == (BODY, OTHER_PLAN)
    assert sm.strip_trailer(BODY) == (BODY, None)
    assert sm.strip_trailer("Middle · sprd 7b2e9d4c1a60 then more") == ("Middle · sprd 7b2e9d4c1a60 then more", None)


def test_the_hand_written_post_carries_the_runbook_trailer():
    posted = abf.load_wit("comment_add_response")
    body, plan = sm.strip_trailer(posted["text"])
    assert plan == "000000000000" and body == "probe from sdlc"


# --- comment refusals ----------------------------------------------------------------------------------------

BASE = {"by": "Kim Lee", "event": "handoff", "max_chars": 4000, "trailer": "hash", "budget_used": 3, "budget": 50,
        "drift_class": None}
REFUSALS = [
    ("a person, in budget", {}, None),
    ("Claude", {"by": "Claude"}, "ai_actor"),
    ("a namespaced agent", {"by": "shepherd:feature-architect"}, "ai_actor"),
    ("a discipline agent", {"by": "data-analyst"}, "ai_actor"),
    ("an event outside the closed set", {"event": "standup"}, "event_unknown"),
    ("an ad hoc comment", {"event": None}, None),
    ("a deleted item", {"drift_class": "DELETED_IN_ADO"}, "needs_disposition"),
    ("a retyped item", {"drift_class": "RETYPED"}, "needs_disposition"),
    ("a conflict is not a disposition gate", {"drift_class": "CONFLICT"}, None),
    ("an address in the text", {"text": BODY + " cc " + KIM_EMAIL}, "email_in_text"),
    ("over max_chars once trailed", {"max_chars": len(BODY) + 5}, "max_chars"),
    ("exactly max_chars untrailed", {"max_chars": len(BODY), "trailer": "none"}, None),
    ("budget 50/50", {"budget_used": 50}, "budget"),
    ("budget 49/50", {"budget_used": 49}, None),
    ("an AI wins over every other reason", {"by": "Claude", "text": KIM_EMAIL, "budget_used": 50,
                                            "event": "standup"}, "ai_actor"),
    ("an address wins over the length and the budget", {"text": KIM_EMAIL, "max_chars": 3, "budget_used": 50},
     "email_in_text"),
]


@pytest.mark.parametrize("label, over, expected", REFUSALS, ids=[r[0] for r in REFUSALS])
def test_comment_refusal(label, over, expected):
    kwargs = {**BASE, **over}
    text = kwargs.pop("text", BODY)
    got = sm.comment_refusal(text, agent_stems=STEMS, **kwargs)
    assert got == expected
    assert got is None or got in bc.COMMENT_REFUSALS


def test_a_handle_is_not_an_address():
    assert sm.comment_refusal("Handed off to @priya-n; checker @MCKRUZ.", agent_stems=STEMS, **BASE) is None


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_an_empty_message_is_illegal_not_a_refusal(text):
    with pytest.raises(ValueError):
        sm.comment_refusal(text, agent_stems=STEMS, **BASE)


@pytest.mark.parametrize("over", [{"budget_used": None}, {"budget_used": True}, {"budget_used": -1}, {"budget": 0},
                                  {"max_chars": 0}, {"trailer": "loud"}])
def test_comment_refusal_needs_counted_inputs(over):
    with pytest.raises(ValueError):
        sm.comment_refusal(BODY, agent_stems=STEMS, **{**BASE, **over})


def test_every_comment_refusal_member_has_exactly_one_rule():
    drafting, at_apply = set(sm.COMMENT_DRAFT_REFUSALS), set(sm.COMMENT_APPLY_REFUSALS)
    assert not drafting & at_apply
    assert drafting | at_apply == set(bc.COMMENT_REFUSALS)
    assert at_apply == {"identity_mismatch", "identity_unknown", "posture"}


# --- the executing identity ----------------------------------------------------------------------------------

ROSTER = {PERSON_1_EMAIL: "@kim"}
PERSON_1_ID = "00000000-0000-0000-0000-000000000002"


def test_the_signed_in_person_resolves_through_the_roster():
    who = sm.executing_identity(abf.load_wit("connection_data"), ROSTER)
    assert who == {"handle": "@kim", "id": PERSON_1_ID, "service_principal": False}
    assert "@example.com" not in json.dumps(who) and "Person 1" not in json.dumps(who)


def test_a_service_principal_has_no_handle_and_reads_as_unknown():
    who = sm.executing_identity(abf.load_wit("connection_data_sp"), ROSTER)
    assert who["handle"] is None and who["service_principal"] is True
    assert sm.identity_refusal("@kim", who["handle"]) == "identity_unknown"


def test_an_account_outside_the_roster_has_no_handle():
    who = sm.executing_identity(abf.load_wit("connection_data"), {})
    assert who == {"handle": None, "id": PERSON_1_ID, "service_principal": False}


@pytest.mark.parametrize("doc", [{}, {"authenticatedUser": None}, {"authenticatedUser": "Person 1"}, [], None])
def test_executing_identity_needs_an_authenticated_user(doc):
    with pytest.raises(ValueError):
        sm.executing_identity(doc, ROSTER)


@pytest.mark.parametrize("by, me, expected", [
    ("@kim", "@kim", None), ("@KIM", "@kim", None), ("@MCKRUZ", "@mckruz", None),
    ("@kim", "@priya-n", "identity_mismatch"), ("@kim", None, "identity_unknown"), (None, "@kim", "identity_unknown"),
    ("Kim Lee", "@kim", "identity_unknown"), ("@kim", "unknown", "identity_unknown"),
])
def test_identity_refusal(by, me, expected):
    got = sm.identity_refusal(by, me)
    assert got == expected and (got is None or got in bc.COMMENT_REFUSALS)


# --- apply results -------------------------------------------------------------------------------------------

CREATED = {"ref": REF, "action": "create", "work_item": 4560, "rev_after": 1}
UPDATED = {"ref": "sdlc:feature:03", "action": "update", "work_item": 4410, "rev_after": 4, "fields": ["System.State"]}
COMMENTED = {"ref": REF, "action": "comment", "work_item": 4521, "rev_after": None, "comment_id": 504,
             "transport": "comments-api", "recovered": False}
CONFLICT = {"ref": "sdlc:spec:0005", "action": "update", "work_item": 4522, "class": "conflict"}
DEFERRED = {"ref": "sdlc:spec:0007", "action": "create", "why": "limit"}


def test_apply_result_has_exactly_the_interface_sheet_keys():
    out = sm.apply_result()
    assert tuple(out) == sm.APPLY_RESULT_KEYS == ("applied", "failed", "deferred", "refused_reason", "exit")
    assert out == {"applied": [], "failed": [], "deferred": [], "refused_reason": None, "exit": 0}


@pytest.mark.parametrize("kwargs, code", [
    ({"applied": [CREATED, UPDATED, COMMENTED]}, 0),
    ({"applied": [CREATED], "deferred": [DEFERRED]}, 0),  # --limit is the person's choice, not a failure
    ({"applied": [CREATED], "failed": [CONFLICT]}, 1),
    ({"failed": [{**CONFLICT, "class": "permission"}], "deferred": [{**DEFERRED, "why": "stopped"}]}, 1),
    ({"refused_reason": "ai_actor"}, 2),
    ({"refused_reason": "identity_mismatch", "deferred": [DEFERRED]}, 2),
    ({"refused_reason": "first_seed"}, 2),
])
def test_apply_exit_codes(kwargs, code):
    assert sm.apply_result(**kwargs)["exit"] == code


def test_a_refused_plan_sent_nothing():
    with pytest.raises(ValueError):
        sm.apply_result(applied=[CREATED], refused_reason="posture")
    with pytest.raises(ValueError):
        sm.apply_result(failed=[CONFLICT], refused_reason="identity_unknown")


BAD_ROWS = [
    ("applied", {**CREATED, "action": "delete"}),
    ("applied", {**CREATED, "work_item": "4560"}),
    ("applied", {**CREATED, "work_item": True}),
    ("applied", {**CREATED, "work_item": None}),
    ("applied", {**CREATED, "rev_after": 0}),
    ("applied", {**CREATED, "ref": "spec 0004"}),
    ("applied", {**CREATED, "ref": None}),            # only a comment may target a raw work item
    ("applied", {**COMMENTED, "comment_id": None}),   # the comments API answers with an id
    ("applied", {**COMMENTED, "transport": "email"}),
    ("applied", {**COMMENTED, "recovered": "yes"}),
    ("applied", {**CREATED, "recovered": True}),      # only a comment is ever recovered
    ("applied", {**CREATED, "note": "by " + KIM_EMAIL}),
    ("applied", {**CREATED, "note": "identity 00000000-0000-0000-0000-000000000002"}),
    ("failed", {**CONFLICT, "class": "boom"}),
    ("failed", {**CONFLICT, "work_item": "4522"}),
    ("deferred", {**DEFERRED, "why": "tired"}),
    ("deferred", "sdlc:spec:0007"),
]


@pytest.mark.parametrize("part, row", BAD_ROWS, ids=[f"{p}-{i}" for i, (p, _) in enumerate(BAD_ROWS)])
def test_apply_result_refuses_a_row_outside_its_shape(part, row):
    with pytest.raises(ValueError):
        sm.apply_result(**{part: [row]})


@pytest.mark.parametrize("reason", ["nope", "", "budget exceeded", 2])
def test_apply_result_refuses_a_reason_outside_the_vocabulary(reason):
    with pytest.raises(ValueError):
        sm.apply_result(refused_reason=reason)


def test_a_raw_work_item_comment_and_the_history_transport_are_shapes_too():
    raw = {**COMMENTED, "ref": None}
    history = {**COMMENTED, "transport": "history", "comment_id": None, "rev_after": 10}
    recovered = {**COMMENTED, "recovered": True}
    failed_create = {"ref": "sdlc:spec:0005", "action": "create", "work_item": None, "class": "rule"}
    child = {"ref": "sdlc:spec:0006", "action": "create", "why": "parent_failed"}
    out = sm.apply_result(applied=[raw, history, recovered], failed=[failed_create], deferred=[child])
    assert out["exit"] == 1 and len(out["applied"]) == 3


def test_apply_result_copies_its_rows():
    rows = [copy.deepcopy(UPDATED)]
    out = sm.apply_result(applied=rows)
    rows[0]["fields"].append("System.Title")
    assert out["applied"][0]["fields"] == ["System.State"]


def test_the_vocabularies():
    assert sm.WRITE_ERROR_CLASSES == wm.ERROR_CLASSES
    assert set(sm.WRITE_ERROR_CLASSES) < set(sm.FAILURE_CLASSES)
    assert set(sm.FAILURE_CLASSES) - set(sm.WRITE_ERROR_CLASSES) == {"created_by_mismatch", "drift"}
    assert set(sm.STOP_CLASSES) == {"permission", "throttled", "drift"} and set(sm.STOP_CLASSES) < set(sm.FAILURE_CLASSES)
    assert sm.RECOVER_CLASSES == ("unknown",)
    assert sm.APPLY_REFUSALS == (*bc.COMMENT_REFUSALS, "forbidden_field", "first_seed")
    assert sm.DEFER_REASONS == ("limit", "writes_per_run", "stopped", "parent_failed")
    assert sm.APPLY_ACTIONS == ("create", "update", "comment")


@pytest.mark.parametrize("name, cls", sorted(abf.WIT_ERROR_CLASSES.items()))
def test_each_hand_written_error_reads_as_its_failure_class(name, cls):
    got = wm.classify_write_error(abf.load_wit_error(name))
    assert got == cls and got in sm.FAILURE_CLASSES
    assert (got in sm.STOP_CLASSES) == (cls in {"permission", "throttled"})
    assert got not in sm.RECOVER_CLASSES  # the board said no: nothing was committed, nothing to recover


def test_a_timed_out_post_is_the_unknown_outcome_that_is_recovered():
    timed_out = "`az devops invoke --area wit --resource comments` timed out after 60s."
    assert wm.classify_write_error(timed_out) in sm.RECOVER_CLASSES


def test_raw_stderr_never_rides_in_a_result():
    detail = abf.load_wit_error("permission")  # it names the identity the board refused
    with pytest.raises(ValueError):
        sm.apply_result(failed=[{**CONFLICT, "class": "permission", "detail": detail}])


# --- recovery on an unknown outcome (design §7) --------------------------------------------------------------

POSTED = abf.load_wit("comment_add_response", hand_written=True)   # read at import: `BOARDS_ITEMS` is per test
RECENT = abf.load_wit("comments_recent")["comments"]
ME = abf.load_wit("connection_data")["authenticatedUser"]["id"]
SENT = "2026-10-12T09:04:30Z"


def test_recovery_finds_the_comment_an_unknown_outcome_already_created():
    got = sm.recovered_comment(sm.text_sha(POSTED["text"]), RECENT, ME, SENT)
    assert got == {"comment_id": POSTED["id"], "version": POSTED["version"], "recovered": True}


def test_recovery_reads_the_plan_row_s_body_sha_not_the_trailed_text():
    body, _ = sm.strip_trailer(POSTED["text"])
    assert sm.recovered_comment(sm.text_sha(body), RECENT, ME, SENT)["comment_id"] == POSTED["id"]


@pytest.mark.parametrize("label, sha, me, sent", [
    ("another author", None, "00000000-0000-0000-0000-000000000003", SENT),
    ("an unknown me", None, None, SENT),
    ("sent 11 minutes earlier", None, ME, "2026-10-12T08:54:00Z"),
    ("other text", "0123456789ab", ME, SENT),
])
def test_recovery_finds_nothing_it_cannot_prove(label, sha, me, sent):
    assert sm.recovered_comment(sha or sm.text_sha(POSTED["text"]), RECENT, me, sent) is None


def test_recovery_window_is_ten_minutes_either_side():
    assert sm.RECOVERY_WINDOW_MINUTES == 10
    created = POSTED["createdDate"]
    assert created == "2026-10-12T09:05:00Z"
    assert sm.recovered_comment(sm.text_sha(POSTED["text"]), RECENT, ME, "2026-10-12T08:55:00Z") is not None
    assert sm.recovered_comment(sm.text_sha(POSTED["text"]), RECENT, ME, "2026-10-12T09:15:00Z") is not None
    assert sm.recovered_comment(sm.text_sha(POSTED["text"]), RECENT, ME, "2026-10-12T09:15:01Z") is None


def test_a_deleted_or_unreadable_comment_never_matches():
    sha = sm.text_sha(POSTED["text"])
    deleted = [{**c, "isDeleted": True} for c in RECENT]
    assert sm.recovered_comment(sha, deleted, ME, SENT) is None
    undated = [{**c, "createdDate": "yesterday"} for c in RECENT]
    assert sm.recovered_comment(sha, undated, ME, SENT) is None
    assert sm.recovered_comment(sha, ["junk", None, {"id": "x"}], ME, SENT) is None


def test_recovery_accepts_the_comment_id_spelling():
    renamed = [{("commentId" if k == "id" else k): v for k, v in c.items()} for c in RECENT]
    assert sm.recovered_comment(sm.text_sha(POSTED["text"]), renamed, ME, SENT)["comment_id"] == POSTED["id"]


@pytest.mark.parametrize("sha, sent", [("XYZ", SENT), (sm.text_sha("x"), "yesterday")])
def test_recovery_refuses_a_bad_sha_or_send_time(sha, sent):
    with pytest.raises(ValueError):
        sm.recovered_comment(sha, RECENT, ME, sent)


def test_the_re_list_query_is_the_one_the_recent_fixture_stands_for():
    assert sm.RECENT_COMMENTS_QUERY == {"order": "desc", "$top": "20"}
    command = json.loads(abf.wit_path("comments_recent").read_text(encoding="utf-8"))["_command"]
    assert abf.query_params(command) == sm.RECENT_COMMENTS_QUERY
