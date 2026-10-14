"""ado_sync_reconcile.py -- Settle what `pull` found on the board: the disposition driver, the one place the Azure Boards
mirror starts another script, and the batch proposal for board items nobody mapped (B4-P1a).

`ado_sync.py pull` records drift rows in the ledger (`drift_seen`); `ado_sync.py reconcile <ref> --field F --take
ado|sdlc|ack|not-drift --by <human>` settles one of them through the design's section 8 disposition machine
(`ado_sync_model.DISPOSITION_MACHINE`). This module is what both verbs lean on. It decides; `ado_sync.py` reads the
repository and the board and appends the ledger line.

  * `drift_rows(ledger)` / `pick_row` -- the open drift rows, judged exactly as `ado_sync_model.summarize` judges them.
  * `disposition_of(cls, take)` -- the machine's word for a take on a row of that class, or a refusal that names the
    words the machine does allow (never a guess; `ado_sync_model.disposition_for_take`).
  * `ado_route` / `check_sdlc` -- which takes a field's OWNER allows (D10, D11). `--take ado` is permitted only for a
    field the board owns (`A`) that has an owning verb: a spec's `AssignedTo` while it is draft or ready
    (`spec_transition.py assign`), a spec's `IterationPath` (`sprint.py slate|unslate`), a decision's close
    (`track_decisions.py decide`). A spec's State is never taken. `--take sdlc` pushes the repository's value back, so
    it is for a field the repository owns (`S`) and nothing else.
  * `CHILD_ARGV` / `child_command` / `run_child` -- the K10 per-verb child argv table and the spawn. EVERY child is the
    list `[sys.executable, <scripts>/<script>.py, ...]` run without a shell; `ready` and `defer` take no `--by`
    (relaying one is argparse exit 2, which would read as a refusal); a child's nonzero exit is the verb's exit 1,
    never 2. This is the only module besides `ado_transport` that imports `subprocess`.
  * `proposals(...)` -- what `pull` prints under each drift row: the plugin action of the section 8 table, as words.
  * `spec_proposals` / `write_batch` -- `pull --propose-specs`: ONE batch file under `.sdlc/ado/local/proposals/`
    holding, for each untagged board item, the argv LIST of `new_spec.py` (or of `link`) a person may run. Argv lists
    in JSON, never a shell string; nothing is run.
  * `propose` (and the parts it runs: `text_target`, `is_text_proposal`, `proposal_text`, `locate_field`,
    `spliced_value`, `write_proposed`) -- the D32 `.proposed` writer (B5-P3). `--take ado` on a board edit to a C-class text field (a requirement's Description
    or AcceptanceCriteria, an epic's AcceptanceCriteria) lands the board's words -- or, with `--from-comment <id>`, the
    cached comment's -- as `<artifact>.proposed`, beside the artifact, by splicing them into the document's own field
    span through `document_shape.write_document`. The artifact itself is never written: the proposal differs from it
    only inside that one span, keeps its line endings, and a person lands it through `/sprd-revise`. A proposal nobody
    has landed is never overwritten, a source path that leaves the repository or a symlinked proposal is refused, text
    holding an address or an id is refused (a proposal sits in the working tree), and a line that reads as an
    instruction is counted and shown, never refused (D47). A kind or field with no place in a shaped document (a
    title, an S field, a table) is refused naming the ones that have one; nothing is guessed.
  * `ledger_reason` / `reason_sha` -- what a `reconciled` line may keep of a `--reason` (house rule 10, below).

Honesty. A take that did not settle the row says so: a `TAKE_*` without a recorded child exit 0 still counts as open
(`ado_sync_model.validate_disposition`), so `--take ado` whose child failed leaves the row open and `--take sdlc`
leaves it open until `apply` lands the field. What is ledgered is the verb and its arguments, with every free-text
value (a reason, a resolution) replaced by `<text>`, the child's exit and a hash of that argv -- never a comment's
words, an address or an absolute path. The one exception is a `--reason` the machine REQUIRES: `--take not-drift` and
`--take ack` keep the typed words on the committed line (a NOT_DRIFT row with no reason, an ACKNOWLEDGED one with no
owner, still counts as open). For `--take ado` and `--take sdlc` the line carries `reason: "<text>"` and `reason_sha`
(the first 12 hex of the sha256 of the words) instead, because a resolution or an unslate reason may be a board
comment's own words (`ledger_reason`); an address or an id in a reason is refused for every take.

Other people's comments (design D52). A cached board comment is never copied into a repository artifact and never
filled in as a verb's argument. `--from-comment <id>` only PRINTS that comment, behind the `  | ` gutter and the `⚑`
marker, as a suggested resolution for the person to type or edit; the decision is closed only with the `--reason`
they typed, and the ledger keeps the comment's id, never its words.

Both modes (CLAUDE.md design rule):
  * Workflow mode -- `ado_sync.py reconcile ... --state .sdlc/state.yaml` hands in the repository root, the parsed
    `.sdlc/ado.yaml`, the discovered schema, the spec's projection and the board's current item.
  * Standalone -- every function takes plain dicts and lists; `child_command` and `run_child` need only a path. Nothing
    here needs `.sdlc/state.yaml`, and nothing here runs `az` or writes the ledger.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Final

import yaml

import ado_discussion_map as dm
import ado_sync_model as model
import boards_contract as bc
from check_spec import parse_frontmatter
from document_shape import read_document, write_document

SCRIPTS: Final = Path(__file__).resolve().parent
TAKES: Final = model.RECONCILE_TAKES
CHILD_TIMEOUT: Final = 120          # seconds a spawned verb may take; a verb that edits one file takes well under one
TEXT: Final = "<text>"              # what the ledger keeps of a free-text argument
PROPOSALS_DIR: Final = f"{bc.LOCAL_DIR}/proposals"
MAX_RESOLUTION: Final = 500         # characters a typed resolution may hold in one decision-log row
HANDED_OFF: Final = model.SPEC_HANDED_OFF
LOCAL_STAMP: Final = "%Y%m%dT%H%MZ"


class Rejected(Exception):
    """The mirror refuses this take (`ado_sync.Refused`, exit 2): the field's owner does not allow it, a name is
    missing, or the machine has no such word for the row."""


class Precondition(Exception):
    """A missing precondition (`ado_sync.Illegal`, exit 1): no such drift row, nothing to read it against."""


# --- the K10 child argv table ------------------------------------------------------------------------------------

def _opt(flag: str, value) -> list[str]:
    """`[flag, value]`, or the one-element `flag=value` when the value starts with a dash (argparse would read a
    separate `-x` as the next flag, not as this one's value)."""
    text = str(value)
    return [f"{flag}={text}"] if text.startswith("-") else [flag, text]


def _tier(tier) -> str:
    """The positional `risk` takes: letters only, so it can never be read as a flag."""
    text = str(tier)
    if not re.fullmatch(r"[A-Za-z]+", text):
        raise ValueError(f"a risk tier is a word (HIGH, MEDIUM, LOW), not {text!r}")
    return text


# verb -> builder(**args) -> the argv AFTER the verb word. Keyed by the owning verb's own name; `SCRIPT_OF` says which
# script owns it. `ready` and `defer` have no `--by` (`spec_transition.py` does not take one there). `unslate` also
# needs the reason `sprint.py` requires of it; the K10 row names `slate` and `unslate` together, but `unslate --reason`
# is required by the script, so without it every unslate would end in argparse exit 2.
CHILD_ARGV: Final[dict[str, Callable[..., list[str]]]] = {
    "ready": lambda: [],
    "defer": lambda reason: _opt("--reason", reason),
    "risk": lambda tier, by: [_tier(tier), *_opt("--authorised-by", by)],
    "confirm-tier": lambda by: _opt("--by", by),
    "assign": lambda developer, by: [*_opt("--developer", developer), *_opt("--by", by)],
    "decide": lambda id, by, resolution: [*_opt("--id", id), *_opt("--by", by), *_opt("--resolution", resolution)],
    "slate": lambda sprint, spec, by: [*_opt("--sprint", sprint), *_opt("--spec", spec), *_opt("--by", by)],
    "unslate": lambda sprint, spec, by, reason: [*_opt("--sprint", sprint), *_opt("--spec", spec), *_opt("--by", by),
                                                 *_opt("--reason", reason)],
}
SCRIPT_OF: Final[dict[str, str]] = {
    "ready": "spec_transition.py", "defer": "spec_transition.py", "risk": "spec_transition.py",
    "confirm-tier": "spec_transition.py", "assign": "spec_transition.py", "decide": "track_decisions.py",
    "slate": "sprint.py", "unslate": "sprint.py",
}
FREE_TEXT: Final = frozenset({"reason", "resolution"})   # argument names whose values are someone's words


def child_command(verb: str, *, spec_path=None, **args) -> list[str]:
    """The argv to run, as a list: `[sys.executable, <scripts>/spec_transition.py, "--spec", path, <verb>, *argv]` for a
    spec transition (`spec_path` is required), `[sys.executable, <scripts>/<script>.py, <verb>, *argv]` for `sprint.py`
    and `track_decisions.py` (they work on the repository they are run in: see `run_child`'s `cwd`)."""
    if verb not in CHILD_ARGV:
        raise ValueError(f"no child verb {verb!r}; the table is {', '.join(CHILD_ARGV)}")
    script = str(SCRIPTS / SCRIPT_OF[verb])
    tail = CHILD_ARGV[verb](**args)
    if SCRIPT_OF[verb] == "spec_transition.py":
        if spec_path is None:
            raise ValueError(f"{verb} is a spec transition: it needs the spec's path")
        return [sys.executable, script, "--spec", str(spec_path), verb, *tail]
    return [sys.executable, script, verb, *tail]


def display_argv(verb: str, *, spec_rel: str | None = None, **args) -> list[str]:
    """What the ledger and the screen keep of a child: the script's file name, the spec's repository-relative path,
    and the arguments with every free-text value replaced by `<text>` (a resolution may be a comment's words)."""
    safe = {k: (TEXT if k in FREE_TEXT else v) for k, v in args.items()}
    tail = CHILD_ARGV[verb](**safe)
    head = [SCRIPT_OF[verb]]
    if SCRIPT_OF[verb] == "spec_transition.py":
        head += ["--spec", spec_rel or "<spec>"]
    return [*head, verb, *tail]


def argv_sha(shown: list[str]) -> str:
    return hashlib.sha256(json.dumps(shown, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def run_child(argv: list[str], cwd) -> dict:
    """Run one child to its end: `{"exit": int | None, "stdout", "stderr"}`. No shell. `exit` is None when it could not
    be started or ran out of time (never a made-up code); its text is a fixed sentence then. The child's own words are
    returned for the screen, control characters removed."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        done = subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=CHILD_TIMEOUT, env=env, stdin=subprocess.DEVNULL, check=False)
    except subprocess.TimeoutExpired:
        return {"exit": None, "stdout": "", "stderr": f"timed out after {CHILD_TIMEOUT} seconds"}
    except (OSError, ValueError) as exc:   # ValueError: an argument the operating system cannot carry (a NUL)
        return {"exit": None, "stdout": "", "stderr": f"could not be started ({type(exc).__name__})"}
    return {"exit": done.returncode, "stdout": dm.strip_control(done.stdout or "").strip("\n"),
            "stderr": dm.strip_control(done.stderr or "").strip("\n")}


# --- the rows -----------------------------------------------------------------------------------------------------

def drift_rows(ledger: list[dict]) -> list[dict]:
    """Every drift row the ledger holds: the latest `drift_seen` per (ref, field), merged with the `reconciled` lines
    after it and cleared by a later `applied` naming the field -- the rule `ado_sync_model.summarize` counts `open`
    by (a test holds the two equal). Each is `{"ref", "field", "class", "owner", "kind", "work_item", "row", "merged",
    "open"}`; `merged` is what `validate_disposition` judged."""
    events = [e for e in ledger if isinstance(e, dict) and e.get("event") in model.LEDGER_EVENTS]
    latest: dict[tuple, tuple[int, dict]] = {}
    for i, e in enumerate(events):
        if e["event"] == "drift_seen" and e.get("ref"):
            latest[(e["ref"], e.get("field"))] = (i, dict(e))
    out = []
    for (ref, field), (i, row) in latest.items():
        merged, cleared = dict(row), False
        for e in events[i + 1:]:
            if e.get("ref") != ref:
                continue
            if e["event"] == "applied" and field in (e.get("fields") or []):
                cleared = True
            elif e["event"] == "reconciled" and e.get("field") in (field, None):
                merged.update({k: v for k, v in e.items() if k not in ("ts", "event", "class")})
                if not model.counts_as_open(merged):
                    cleared = True
        out.append({"ref": ref, "field": field, "class": row.get("class"), "owner": row.get("owner"),
                    "kind": row.get("kind"), "work_item": row.get("work_item"), "row": row, "merged": merged,
                    "open": not cleared and model.counts_as_open(merged)})
    return out


def pick_row(rows: list[dict], ref: str, field: str | None) -> dict:
    """The open drift row of `ref` named by `field` (None: the row of the item itself, as `DELETED_IN_ADO` and
    `ORPHAN_IN_REPO` are). `Precondition` when there is none, saying which rows the ref does have."""
    mine = [r for r in rows if r["ref"] == ref]
    wanted = field.strip() if isinstance(field, str) and field.strip() else None
    found = next((r for r in mine if r["field"] == wanted), None)
    label = f"{ref} {wanted}" if wanted else f"{ref} (the item itself)"
    if found is None:
        have = [r["field"] or "(the item itself)" for r in mine if r["open"]]
        hint = f" Open rows of {ref}: {', '.join(have)}." if have else ""
        raise Precondition(f"no drift is recorded for {label}: run `pull` first (and name the field with --field).{hint}")
    if not found["open"]:
        _, why = model.validate_disposition(found["merged"])
        raise Precondition(f"{label} is already settled ({why}); nothing was changed")
    return found


def disposition_of(cls: str, take: str) -> str:
    """The disposition `--take` records on a row of class `cls`, or `Rejected` naming the machine's own words for that
    class. No take word reaches RECREATE, UNLINK or RELINK (the four take words are ado, sdlc, ack and not-drift), so
    those two classes say so in plain words instead of guessing."""
    disp = model.disposition_for_take(cls, take)
    if disp is not None:
        return disp
    allowed = model.dispositions_for(cls)
    words = ", ".join(allowed) if allowed else "none"
    tail = ""
    if cls == "DELETED_IN_ADO":
        tail = (" The only disposition a take word reaches there is ACKNOWLEDGED: `--take ack --owner <you>` records "
                "that someone knows it is gone. RECREATE and UNLINK have no take word in this version.")
    elif cls == "ORPHAN_IN_REPO":
        tail = (" No take word reaches UNLINK or RELINK in this version, so the row stays open and `status` keeps "
                "counting it.")
    raise Rejected(f"Refused: --take {take} is not a way to settle a {cls} row (the machine allows: {words}).{tail}")


def check_inputs(take: str, owner: str | None, reason: str | None) -> None:
    """What each take needs a person to say (all refusals, exit 2): ACKNOWLEDGED an owner, NOT_DRIFT a reason."""
    if take == "ack" and not owner:
        raise Rejected("Refused: --take ack needs --owner <a named person>: an acknowledged row with no owner still "
                       "counts as open.")
    if take == "not-drift" and not reason:
        raise Rejected("Refused: --take not-drift needs --reason <why this is not drift>: a row with no reason still "
                       "counts as open.")


# --- who owns the field -------------------------------------------------------------------------------------------

# spec_transition.py's own refusal for a developer change on a handed-off spec (`assign`, :377-380); a test runs the
# real script and holds this equal to what it prints.
ASSIGN_HANDED_OFF: Final = ("This spec is {status} — its branch names who is building it, and this file cannot change "
                            "that. A new developer is a new hand-off.")
OWNING_RULE: Final[dict[tuple[str, str], str]] = {
    ("spec", "System.State"): ("a spec's status is written only by its own verbs (`spec_transition.py ready|defer`, "
                               "and `in-flight` only by `handoff.py`, which creates the branch and a draft pull "
                               "request -- a board move must never do that)"),
}


def _rule_for(kind: str, field: str) -> str:
    if (kind, field) in OWNING_RULE:
        return OWNING_RULE[(kind, field)]
    if field == "System.Tags":
        return "the `sdlc:*` tags are the mirror's, put back on the next push"
    return f"the repository owns {field} on a {kind} and the next `apply` pushes it back"


def ado_route(kind: str, field: str | None, owner: str | None) -> str:
    """Which owning verb `--take ado` relays to for this field -- `assign`, `iteration` or `decide` -- or `Rejected`.
    Refused for every field the board does not own (D11): an `S` field names the owning rule, a `C` field says only
    co-owned text is taken (as a `.proposed` draft: `ado_sync.py` asks `is_text_proposal` first and routes that text
    to `propose`, so a `C` field reaching here is not text), and a field with no owning verb says so."""
    if field is None:
        raise Rejected("Refused: --take ado is for a field the board owns; this row is about the item itself.")
    if owner == "S":
        raise Rejected(f"Refused: --take ado never takes {field} on a {kind}: {_rule_for(kind, field)}. A board edit "
                       f"is drift the repository puts back; `--take sdlc` records that choice, `--take ack` that "
                       "someone knows.")
    if owner == "C":
        raise Rejected(f"Refused: {field} on a {kind} is the board's once the item exists, and it is not text a "
                       "document holds: only co-owned text (a requirement's Description or AcceptanceCriteria, an "
                       "epic's AcceptanceCriteria) is taken, as a `.proposed` draft beside its artifact that a person "
                       "lands through /sprd-revise. Record that a person read it with `--take ack --owner <you>`.")
    if owner != "A":
        raise Rejected(f"Refused: {field} has no owning verb to take it through (relation drift is report only); "
                       "`--take ack --owner <you>` records that someone knows.")
    if kind == "spec" and field == "System.AssignedTo":
        return "assign"
    if kind == "spec" and field == "System.IterationPath":
        return "iteration"
    if kind == "decision" and field == "System.State":
        return "decide"
    raise Rejected(f"Refused: no verb owns {field} on a {kind}, so there is nothing to take it through. "
                   "`--take ack --owner <you>` records that someone knows.")


def check_sdlc(kind: str, field: str | None, owner: str | None) -> None:
    """`--take sdlc` pushes the repository's value back at the next `apply`: only for a field the repository owns."""
    if field is None or owner != "S":
        what = "the item itself" if field is None else field
        raise Rejected(f"Refused: --take sdlc pushes the repository's value back to the board, and the mirror never "
                       f"writes {what} on a {kind} after it exists (the board owns it). `--take ack --owner <you>` "
                       "records that someone knows.")


# --- the child to run ---------------------------------------------------------------------------------------------

def state_category(schema: dict | None, type_name: str | None, state: str | None) -> str | None:
    """The category (`Completed`, `InProgress`, ...) the discovered process gives `state` on `type_name`, or None when
    the schema holds no states for the type (never read) or does not know the state."""
    types = (schema or {}).get("types") if isinstance((schema or {}).get("types"), dict) else {}
    info = next((v for k, v in types.items() if str(k).lower() == str(type_name).lower()), None)
    states = info.get("states") if isinstance(info, dict) else None
    for s in states or []:
        if isinstance(s, dict) and str(s.get("name", "")).lower() == str(state).lower():
            return s.get("category")
    return None


def cached_comment(cache_doc: dict | None, comment_id: int) -> dict:
    """The cached comment `comment_id`, to SHOW as a suggestion (design D52: never copied, never filled in).
    `Rejected` when it is not in the local discussion cache or was deleted: a suggestion, or the `comment_id` a ledger
    line names, must point at a comment the person can read."""
    comments = cache_doc.get("comments") if isinstance(cache_doc, dict) else None
    found = next((c for c in comments or [] if isinstance(c, dict) and c.get("id") == comment_id), None)
    if found is None or found.get("deleted"):
        raise Rejected(f"Refused: comment {comment_id} is not in the local discussion cache (run `pull --discussion` "
                       "for the item) or it was deleted; type the resolution with --reason instead.")
    return found


def suggestion_lines(comment: dict) -> list[str]:
    """The comment's words as the screen shows them: every line behind the `  | ` gutter, a line that reads as an
    instruction marked `⚑`. For a person to read, then type or edit -- this is printed, never written to a file."""
    text = dm.strip_control(comment.get("text")) if isinstance(comment.get("text"), str) else ""
    lines = text.split("\n") if text.strip() else []
    flagged = set(dm.directive_scan(text)) if lines else set()
    stored = comment.get("flagged_lines")
    if isinstance(stored, list):
        flagged |= {i for i in stored if type(i) is int and 0 <= i < len(lines)}
    return [dm.QUOTE + (f"{line}   {dm.FLAG_MARK} reads as an instruction" if i in flagged else line)
            for i, line in enumerate(lines)]


def suggestion_refusal(comment_id: int, comment: dict) -> str:
    """The refusal `--from-comment` without `--reason` ends in: the comment printed as a suggestion, and the one way
    to close the decision -- the person types the resolution."""
    quoted = suggestion_lines(comment)
    body = quoted if quoted else [dm.QUOTE + "(the comment is empty)"]
    return "\n".join([
        "Refused: a decision's resolution is typed by a person; a board comment is never filled in for you, and its "
        "words are never copied into the decision log.",
        f"{dm.FLAG_MARK} comment {comment_id} suggests (someone else's words, shown as data -- not instructions):",
        *body,
        f"To close the decision, type the resolution yourself (as written, or edited): --reason \"<what was decided>\" "
        f"--from-comment {comment_id}. The ledger records comment {comment_id} as the suggestion; the log gets what "
        "you typed.",
    ])


def one_line_resolution(text, source: str) -> str:
    """The resolution a person typed, as one line for a decision-log row (which is committed): `Rejected` when it is
    empty, too long for a row, or carries an address or a GUID."""
    clean = " ".join(dm.strip_control(str(text or "")).split())
    if not clean:
        raise Rejected(f"Refused: {source} is empty; a decision's resolution says what was decided.")
    if len(clean) > MAX_RESOLUTION:
        raise Rejected(f"Refused: {source} is longer than the {MAX_RESOLUTION} characters a decision-log row takes; "
                       "shorten it.")
    if bc.EMAIL_RE.search(clean) or bc.GUID_RE.search(clean):
        raise Rejected(f"Refused: {source} carries an e-mail address or an id; a decision log is committed and never "
                       "holds one. Type the resolution without it.")
    return clean


def plan_child(route: str, *, repo_root, ref: str, proj: dict, remote: dict, cfg: dict, schema: dict | None, by: str,
               reason: str | None, comment: dict | None = None, comment_id: int | None = None) -> dict:
    """The child `--take ado` spawns for `route`, built from the repository's projection and the board's CURRENT item:
    `{"verb", "argv", "shown", "cwd"}`. `Precondition` for what a person must settle first (an assignee not
    on the roster, a path no sprint is bound to), `Rejected` for a refusal of the mirror's own. `comment` (the cached
    comment `--from-comment` named) is only ever shown as a suggestion: the resolution is the `reason` a person typed."""
    root = Path(repo_root)
    spec_rel = proj.get("source_path")
    if route == "assign":
        status = proj.get("status")
        if status in HANDED_OFF:
            raise Rejected("Refused: " + ASSIGN_HANDED_OFF.format(status=status))
        handle = remote.get("assigned_to_handle")
        if not handle:
            raise Precondition("the board's assignee is not a person on the roster (or the item is unassigned): add "
                               "their address to .sdlc/team.yaml, then pull again; `assign` never guesses a handle")
        args = {"developer": handle, "by": by}
        verb = "assign"
    elif route == "iteration":
        verb, args = _iteration_verb(root, proj, remote, cfg, by, reason)
    elif route == "decide":
        category = state_category(schema, remote.get("type"), remote.get("state"))
        if category is None:
            raise Precondition("the discovered schema holds no states for this item's type, so whether the board "
                               "closed it is not known: run `discover --refresh` first")
        if category != "Completed":
            raise Precondition(f"the board's state is in the {category} category, not Completed: there is nothing "
                               "to close, so no decision is recorded")
        if not reason:
            if comment is not None:
                raise Rejected(suggestion_refusal(comment_id, comment))
            raise Rejected("Refused: closing a decision needs its resolution, typed by a person: --reason <what was "
                           "decided> (--from-comment <id> shows a cached comment as a suggestion to type). It is never "
                           "filled in for you.")
        verb, args = "decide", {"id": proj["id"], "by": by, "resolution": one_line_resolution(reason, "--reason")}
    else:  # a route nobody registered: never reached through `ado_route`
        raise ValueError(f"unknown route {route!r}")
    argv = child_command(verb, spec_path=(root / spec_rel) if spec_rel else None, **args)
    return {"verb": verb, "argv": argv, "shown": display_argv(verb, spec_rel=spec_rel, **args), "cwd": root}


def _iteration_verb(root: Path, proj: dict, remote: dict, cfg: dict, by: str, reason: str | None) -> tuple[str, dict]:
    """`slate` when the board's iteration path is a sprint's, `unslate` when it is the project's own root (no sprint)
    and the spec holds one; else the sentence saying what to bind first."""
    path = remote.get("iteration")
    bound = cfg.get("iterations") if isinstance(cfg.get("iterations"), dict) else {}
    by_path = {p: s for s, p in bound.items() if isinstance(p, str)}
    sprint_now = _spec_sprint(root, proj)
    spec_id = proj["id"]
    if path in by_path:
        if by_path[path] == sprint_now:
            raise Precondition(f"{path} is already {by_path[path]}, the sprint spec {spec_id} holds: pull again, the "
                               "board and the repository agree")
        return "slate", {"sprint": by_path[path], "spec": spec_id, "by": by}
    if isinstance(path, str) and "\\" not in path and sprint_now:
        if not reason:
            raise Rejected(f"Refused: the board moved spec {spec_id} out of every sprint; taking that is an unslate, "
                           "and `unslate` records why: --reason <why it leaves the slate>.")
        return "unslate", {"sprint": sprint_now, "spec": spec_id, "by": by, "reason": reason}
    raise Precondition(f"the board's iteration path is bound to no sprint: run `ado_sync.py iteration bind <SNN> --path "
                       f"<that path> --by <you>` first, then take it")


def _spec_sprint(root: Path, proj: dict) -> str:
    """The `sprint:` a spec's frontmatter holds (blank when none), read from its own file."""
    rel = proj.get("source_path")
    try:
        fm = parse_frontmatter((root / rel).read_text(encoding="utf-8"))[0] if rel else {}
    except (OSError, UnicodeDecodeError):
        return ""
    return str((fm or {}).get("sprint") or "").strip()


# --- what pull says about each drift row --------------------------------------------------------------------------

def _bound_sprint(cfg: dict, path) -> str | None:
    bound = cfg.get("iterations") if isinstance(cfg.get("iterations"), dict) else {}
    return next((s for s, p in bound.items() if p == path), None)


def _propose_field(ref: str, kind: str, f: dict, proj: dict | None, remote: dict | None, cfg: dict,
                   schema: dict | None) -> tuple[str, str]:
    """`(action, text)` for one drift field of one item: the plugin action of the design's section 8 table."""
    field, cls, owner = f.get("field"), f.get("class"), f.get("owner")
    take = f"`reconcile {ref} --field {field} --take ado --by <you>`"
    if field == "System.AssignedTo" and kind == "spec":
        status = (proj or {}).get("status")
        if status in HANDED_OFF:
            return "report", ASSIGN_HANDED_OFF.format(status=status)
        handle = (remote or {}).get("assigned_to_handle")
        if handle:
            return "reconcile", f"{take} runs `spec_transition.py assign --developer {handle}`"
        return "by-hand", ("the new assignee is not on the roster: add their address to .sdlc/team.yaml, then pull "
                           "again")
    if field == "System.IterationPath" and kind == "spec":
        path = (remote or {}).get("iteration")
        sprint = _bound_sprint(cfg, path)
        if sprint:
            return "reconcile", f"{take} runs `sprint.py slate --sprint {sprint}`"
        return "by-hand", "the board's iteration path is bound to no sprint: run `iteration bind <SNN> --path <path>` first"
    if field == "System.State" and kind == "spec":
        category = state_category(schema, (remote or {}).get("type"), (remote or {}).get("state"))
        end = ("; to end the spec, `spec_transition.py --spec <path> defer --reason <why>`, then pull again"
               if category == "Removed" else "")
        return "report", f"never taken: {_rule_for('spec', 'System.State')}{end}"
    if field == "System.State" and kind == "decision":
        category = state_category(schema, (remote or {}).get("type"), (remote or {}).get("state"))
        if category == "Completed":
            return "reconcile", (f"`reconcile {ref} --field {field} --take ado --reason <what was decided> --by <you>` "
                                 "runs `track_decisions.py decide`; the resolution is typed by a person, never "
                                 "filled in (--from-comment <id> shows a cached comment as a suggestion to type)")
        return "report", "the board has not closed it: nothing to decide yet"
    if field == "System.State" and kind == "finding":
        return "report", ("record the disposition in the review report's `## Gate Results`; `record_findings.py "
                          "report --strict` still checks the target changed")
    if field in ("System.Title", "System.Description", "Microsoft.VSTS.Common.AcceptanceCriteria"):
        if owner == "C" and text_target(kind, field) is not None:
            return "reconcile", (f"{take} writes the board's words as `<artifact>.proposed` beside the artifact (never "
                                 "the artifact itself); a person lands it through /sprd-revise (--from-comment <id> "
                                 "proposes a cached comment's words instead)")
        if owner == "C":
            return "report", ("the board's text is the board's and has no place in a document this version writes: "
                              "read it with `show`, then `--take ack --owner <you>`")
        return "report", "the repository's text is re-pushed on the next apply; `--take sdlc` records that choice"
    if field == "System.Tags":
        return "report", "an `sdlc:*` tag was removed: it is added back on the next push"
    if field == "relations:parent":
        return "by-hand", ("change the FE-NN in the spec's `source:` (no verb writes it, so a person does) or the "
                           "brief header's epic; the mirror never moves it back")
    if str(field).startswith("relations:"):
        return "report", "report only"
    if field == "System.AreaPath":
        return "report", "the ledger learns the path; report only"
    if field == "System.WorkItemType":
        return "report", "retyped on the board: the mirror cannot change a type; it needs a disposition"
    if cls == "ADO_OWNED_CHANGE":
        return "report", f"the board owns {field}; `--take ack --owner <you>` records that someone knows"
    return "report", "report only"


def proposals(results: list[dict], projs: dict[str, dict], remotes: dict[int, dict], cfg: dict,
              schema: dict | None) -> list[dict]:
    """One proposal per drift row `pull` read: `{"ref", "kind", "field", "class", "action", "text"}` with `action` one of
    `reconcile` (a take settles it through the owning verb), `by-hand` (a person does something first) and `report`.
    A lost row (`DELETED_IN_ADO`, `ORPHAN_IN_REPO`) is proposed too. Free text from the board is never in `text`."""
    out = []
    for r in results:
        if r.get("unavailable") or not r.get("class"):
            continue
        ref, kind, cls = r["ref"], r.get("kind") or "", r["class"]
        if cls == "DELETED_IN_ADO":
            out.append({"ref": ref, "kind": kind, "field": None, "class": cls, "action": "reconcile",
                        "text": (f"gone from the board (deleted, or not visible to this az login); the mirror does "
                                 f"not recreate it unasked. `reconcile {ref} --take ack --owner <you> --by <you>` "
                                 "records that someone knows")})
            continue
        if cls == "ORPHAN_IN_REPO":
            out.append({"ref": ref, "kind": kind, "field": None, "class": cls, "action": "report",
                        "text": ("its source is gone from the repository (deleted or renumbered); the board item is "
                                 "left alone. UNLINK or RELINK has no take word in this version")})
            continue
        proj, remote = projs.get(ref), remotes.get(r["work_item"])
        for f in r.get("fields") or []:
            if f.get("class") in model.NOT_DRIFT_CLASSES:
                continue
            action, text = _propose_field(ref, kind, f, proj, remote, cfg, schema)
            out.append({"ref": ref, "kind": kind, "field": f.get("field"), "class": f.get("class"),
                        "action": action, "text": text})
    return out


# --- pull --propose-specs -----------------------------------------------------------------------------------------

_SPEC_FILE = re.compile(r"^(\d+)-.+\.md$")
_TITLED = re.compile(r"^(\d{4,}) · (.+)$")
TITLE_LIMIT: Final = 200


def spec_ids(repo_root) -> set[str]:
    """The ids of the specs the repository already has, read from the file names under `specs/`."""
    folder = Path(repo_root) / "specs"
    return {m.group(1) for p in (sorted(folder.glob("*.md")) if folder.is_dir() else [])
            if (m := _SPEC_FILE.match(p.name))}


def _clean_title(text) -> str:
    clean = " ".join(dm.strip_control(str(text or "")).split())
    return clean if len(clean) <= TITLE_LIMIT else clean[:TITLE_LIMIT - 1] + "…"


def spec_proposals(items: list[dict], have: set[str]) -> list[dict]:
    """One proposal per untagged board item (`ado_wit_map.remote_item` documents): a title already of the form
    `NNNN · <name>` for a spec the repository has is a `link`; anything else is a `new_spec` named from the title. Each
    carries an argv LIST (the script's repository-relative path first) a person may run -- nothing here runs
    anything, and nothing is a shell string. The `link` that follows a `new_spec` names the new spec's id as
    `<NNNN>`: it does not exist until `new_spec.py` allocates it."""
    out = []
    for item in sorted(items, key=lambda i: i["id"]):
        title = _clean_title(item.get("title"))
        m = _TITLED.match(title)
        wid, owner = item["id"], item.get("assigned_to_handle")
        base = {"work_item": wid, "type": item.get("type"), "state": item.get("state"), "title": title,
                "owner": owner}
        if m and m.group(1) in have:
            out.append({**base, "action": "link", "new_spec": None,
                        "then": ["scripts/ado_sync.py", "link", f"sdlc:spec:{m.group(1)}", "--work-item", str(wid),
                                 "--by", "<you>"]})
            continue
        name = m.group(2) if m else title
        new_spec = ["scripts/new_spec.py", "--name", name, "--source", f"ado:{wid}"]
        if owner:
            new_spec += ["--owner", owner]
        out.append({**base, "action": "new_spec", "new_spec": new_spec,
                    "then": ["scripts/ado_sync.py", "link", "sdlc:spec:<NNNN>", "--work-item", str(wid),
                             "--by", "<you>"]})
    return out


def batch_path(stamp_dt) -> str:
    """The repository-relative path of one batch file: `.sdlc/ado/local/proposals/specs-<UTC minute>.json`."""
    return f"{PROPOSALS_DIR}/specs-{stamp_dt.strftime(LOCAL_STAMP)}.json"


def write_batch(repo_root, stamp_dt, proposals_: list[dict], write: Callable[[Path, dict], None]) -> str:
    """Write ONE batch proposal file and return its repository-relative path. `write(path, doc)` is the caller's atomic
    JSON writer. The folder is the ignored local one (`.sdlc/ado/local/`), where a board title may sit."""
    rel = batch_path(stamp_dt)
    doc = {"schema": 1, "created": stamp_dt.strftime("%Y-%m-%dT%H:%MZ"), "from": "ado_sync.py pull --propose-specs",
           "note": ("Proposals for work items on the board that this repository has not tagged. Every command is an "
                    "argument list for a person (or a named agent they direct) to run; nothing was run. A title is "
                    "the board's text, kept as data."),
           "counts": {"new_spec": sum(1 for p in proposals_ if p["action"] == "new_spec"),
                      "link": sum(1 for p in proposals_ if p["action"] == "link")},
           "proposals": proposals_}
    write(Path(repo_root) / rel, doc)
    return rel


# --- D32: the board's text, back as a proposal (B5-P3) ------------------------------------------------------------
#
# Call order for `--take ado` on a C-class text field: `is_text_proposal` (which route), then `propose`, which runs
# `text_target` (is there a place for it), `proposal_text` (the words) and `write_proposed` (the file). Nothing here
# reads the board, runs a process or writes the ledger: the caller hands in the board's current item (or a cached comment) and takes the result's `exit`,
# `stdout` and `stderr` the way it takes a child's. A proposal written is a take that carries what it claims (the
# board's words are on disk beside the artifact, the artifact is untouched, a person lands it): `exit` is 0.

PROPOSED_SUFFIX: Final = ".proposed"
MAX_PROPOSED_CHARS: Final = 8000      # characters of board text one field proposal may hold
DESCRIPTION: Final = "System.Description"
ACCEPTANCE: Final = "Microsoft.VSTS.Common.AcceptanceCriteria"
TEXT_FIELDS: Final = ("System.Title", DESCRIPTION, ACCEPTANCE)
# (kind, board field) -> the label of the shaped field that holds the same words. Only what a shape can place: a block
# found by its id (`### FR-001`), a labelled line inside it. A title is the repository's (S) except on a decision, whose
# row is a table cell; an NFR, rule or question is a table row: none of those is mapped, so each is refused by name.
TEXT_TARGETS: Final[dict[tuple[str, str], str]] = {
    ("requirement", DESCRIPTION): "Requirement",
    ("requirement", ACCEPTANCE): "Acceptance criteria",
    ("epic", ACCEPTANCE): "Acceptance criteria",
}
SHAPES_ROOT: Final = SCRIPTS.parent / "templates" / "phases"


def text_target(kind: str | None, field: str | None) -> str | None:
    """The label of the field in the artifact's shape that carries this board field of this kind, or None."""
    return TEXT_TARGETS.get((kind, field))


def is_text_proposal(field: str | None, owner: str | None) -> bool:
    """True for a C-class text field: the route `--take ado` takes through a `.proposed` draft, not a child verb."""
    return owner == "C" and field in TEXT_FIELDS


def _no_place(kind, field) -> str:
    return (f"Refused: the board's {field} on a {kind} has no place in a document this version can write. It writes a "
            "requirement's Description and AcceptanceCriteria and an epic's AcceptanceCriteria (a labelled line of the "
            "block `requirements.md` or `epics.md` keeps for it); read the board's text with `show`, then record that a "
            "person read it: `--take ack --owner <you>`.")


def _outside_the_markers(html: str) -> str:
    """The Description with the mirror's own block (between the `sdlc` markers) taken out: what is left is a person's."""
    begin, end = html.find(model.MARKER_BEGIN), html.find(model.MARKER_END)
    if begin < 0 and end < 0:
        return html
    if begin < 0 or end < begin + len(model.MARKER_BEGIN):
        raise Precondition("the board's Description has an sdlc marker without its pair, so the mirror's block cannot be "
                           "told from a person's own text: fix the markers on the board, then take it again")
    return html[:begin] + "<br>" + html[end + len(model.MARKER_END):]


def proposal_text(remote: dict | None, field: str, *, comment: dict | None = None) -> dict:
    """The words to propose: `{"text", "source": "board" | "comment", "flagged_lines": [int]}`.

    From the board's CURRENT item (`remote["fields"][field]`, rich text read as plain text; the Description without the
    mirror's own block) or, when `--from-comment` named one, the cached `comment`'s text -- control characters removed
    either way, every line end `\\n`. `Precondition` when there are no words of a person's to take, `Rejected` for text
    longer than a field takes or holding an e-mail address or an id (a proposal sits in the working tree, where a
    committed file never holds one). A line that reads as an instruction is NOT refused: it is listed in
    `flagged_lines` (0-based, relative to `text`) for the caller to show with the `⚑` marker (design D47)."""
    stored: list = []
    if comment is not None:
        said = comment if isinstance(comment, dict) else {}
        if said.get("deleted"):
            raise Rejected("Refused: that comment was deleted on the board; there are no words left to propose.")
        clean = dm.strip_control(said["text"]) if isinstance(said.get("text"), str) else ""
        source = "comment"
        stored = said["flagged_lines"] if isinstance(said.get("flagged_lines"), list) else []
    else:
        fields = remote.get("fields") if isinstance(remote, dict) else None
        if not isinstance(fields, dict):
            raise Precondition("the board's item was not read, so there is no text to take: pull again")
        html = fields.get(field)
        html = html if isinstance(html, str) else ""
        clean = dm.html_to_text(_outside_the_markers(html) if field == DESCRIPTION else html)
        source = "board"
    flagged = set(dm.directive_scan(clean)) | {i for i in stored if type(i) is int and 0 <= i <= clean.count("\n")}
    shift = clean[:len(clean) - len(clean.lstrip())].count("\n")           # blank lines trimmed off the front
    text = "\n".join(line.rstrip() for line in clean.strip().split("\n")) if clean.strip() else ""
    if not text:
        where = "the comment" if comment is not None else f"{field} on the board"
        raise Precondition(f"{where} holds no text of a person's: nothing to propose")
    if len(text) > MAX_PROPOSED_CHARS:
        raise Rejected(f"Refused: the text is longer than the {MAX_PROPOSED_CHARS} characters one field proposal takes; "
                       "shorten it on the board or edit the document by hand through /sprd-revise.")
    if bc.EMAIL_RE.search(text) or bc.GUID_RE.search(text):
        raise Rejected("Refused: the text carries an e-mail address or an id; a proposal sits in the working tree and is "
                       "never given one. Edit the document by hand through /sprd-revise.")
    last = text.count("\n")
    return {"text": text, "source": source,
            "flagged_lines": sorted(i - shift for i in flagged if shift <= i and i - shift <= last)}


def shape_for(artifact_rel: str) -> dict:
    """The shape of the artifact at `artifact_rel`: `templates/phases/<its phase folder>/<name>.shape.yaml`, else the one
    shape of that name anywhere under `templates/phases/` (a standalone repository keeps its documents anywhere).
    `Precondition` when there is none or it cannot be read."""
    stem, phase = Path(artifact_rel).stem, Path(artifact_rel).parent.name
    path = SHAPES_ROOT / phase / f"{stem}.shape.yaml" if phase else None
    if path is None or not path.is_file():
        found = sorted(SHAPES_ROOT.glob(f"*/{stem}.shape.yaml"))
        if len(found) != 1:
            raise Precondition(f"{artifact_rel} has no shape the writer can read (templates/phases/*/{stem}.shape.yaml): "
                               "text is placed only in a document whose fields a shape names")
        path = found[0]
    try:
        shape = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        raise Precondition(f"the shape of {artifact_rel} could not be read") from None
    if not isinstance(shape, dict):
        raise Precondition(f"the shape of {artifact_rel} is not a mapping")
    return shape


def locate_field(text: str, shape: dict, ident: str, label: str) -> dict:
    """The exact span of field `label` inside the block `ident` (`FR-001`) of the document `text`:
    `{"start", "end", "anchor", "type", "value", "heading", "label", "instance"}`, offsets into `text` as
    `document_shape.read_document` reads them. `Precondition` when the document does not read as its shape, holds the id
    nowhere or twice, or the block lacks the labelled line; `Rejected` for a table (prose is never spliced into one)."""
    doc = read_document(text, shape)
    if not doc.get("matched"):
        raise Precondition("the document does not read as its shape (" + "; ".join(doc.get("warnings") or
                           ["no section was recognised"]) + "): nothing is placed in a document that has drifted from it")
    hits, repeating = [], []
    for block in doc["blocks"]:
        if block.get("kind") != "repeating_section":
            continue
        repeating.append(block.get("heading"))
        hits += [(block, inst) for inst in block["instances"]
                 if re.match(re.escape(ident) + r"(?![A-Za-z0-9])", inst["heading_text"])]
    if not hits:
        where = ", ".join(f"'{h}'" for h in repeating) or "no section"
        raise Precondition(f"{ident} is not a block the document's shape reads as fields (only {where} hold blocks of "
                           "fields; everything else is free text): edit it by hand through /sprd-revise")
    if len(hits) > 1:
        raise Precondition(f"{ident} is found more than once in the document, so which block is meant is not guessed: "
                           "an id is used once")
    block, inst = hits[0]
    found = inst["fields"].get(label)
    if found is None:
        raise Precondition(f"{ident} has no `**{label}:**` line in the document: add the line, then take it again")
    if found["type"] == "table":
        raise Rejected(f"Refused: {label} of {ident} is a table, and prose is never spliced into one.")
    return {"start": found["start"], "end": found["end"], "anchor": found["anchor"], "type": found["type"],
            "value": found["value"], "heading": block["heading"], "label": label, "instance": inst["heading_text"]}


def _document_eol(text: str) -> str:
    return "\r\n" if text.count("\r\n") * 2 > text.count("\n") else "\n"


def _carry_style(original: str, lines: list[str], field_type: str) -> list[str]:
    """The words, in the field's own list or quote style: a checklist gets its `- [ ]` boxes, a field written as a
    blockquote keeps its `>`; anything else is taken as it is."""
    if field_type == "checklist":
        out = []
        for line in lines:
            if not line.strip() or re.match(r"[-*+] \[[ xX]\] ", line):
                out.append(line)
            elif re.match(r"[-*+] ", line):
                out.append("- [ ] " + line[2:])
            else:
                out.append("- [ ] " + line)
        return out
    kept = [ln for ln in original.replace("\r\n", "\n").split("\n") if ln.strip()]
    if kept and all(ln.startswith(">") for ln in kept):
        return [line if line.startswith(">") else ("> " + line if line.strip() else ">") for line in lines]
    return lines


# A thematic break (`---`, `***`, `___`, spaced or longer): the rule that closes one block before the next. A field's
# span runs to the next label or heading, so the LAST field of a block covers that rule too; it is the document's.
_BREAK_LINE: Final = re.compile(r" {0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})")


def _words_end(original: str) -> int:
    """Where a block field's own words end inside its span: before the trailing white space and any separator lines
    after them (kept, byte for byte, as the span's tail). 0 when the span holds nothing but white space and rules."""
    end = len(original.rstrip())
    while end:
        start = original.rfind("\n", 0, end) + 1
        if not _BREAK_LINE.fullmatch(original[start:end]):
            return end
        end = len(original[:start].rstrip())
    return 0


def spliced_value(text: str, span: dict, board_text: str) -> str:
    """What replaces the bytes `span` covers: the board's words in the field's own style, with the span's own trailing
    white space (the blank line before the next label) and any block separator after the words (`---`) kept, every new
    line end the document's own (CRLF stays CRLF). An inline field takes one line. `span` is `locate_field`'s answer
    (or any dict with `start`, `end`, `anchor`, `type`)."""
    start, end = span["start"], span["end"]
    original = text[start:end]
    eol = "\r\n" if "\r\n" in original else ("\n" if "\n" in original else _document_eol(text))
    lines = [ln.rstrip() for ln in board_text.replace("\r\n", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    inline = span.get("anchor") == "inline"
    body = " ".join(" ".join(lines).split()) if inline else eol.join(_carry_style(original, lines, span.get("type") or ""))
    if original.strip():
        lead = original[:len(original) - len(original.lstrip())]
        cut = len(original.rstrip()) if inline else _words_end(original)
        trail = original[cut:] if cut else eol * 2 + original[len(lead):]   # only a `---`: the words go before it
    else:
        lead, trail = "", (original if "\n" in original else "")
    if not inline and "\n" not in trail:
        trail += eol if end >= len(text) else eol * 2           # the next label stays on its own line
    return lead + body + trail


def _read_text(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as fh:      # newline="": CRLF is never translated
        return fh.read()


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def write_proposed(repo_root, *, proj: dict, field: str, text: str, flagged_lines=None) -> dict:
    """Write `<artifact>.proposed` beside the artifact of `proj` (`kind`, `id`, `source_path`) for the board `field`.

    The proposal is the artifact's text with ONE span replaced through `document_shape.write_document`; the artifact is
    never written. Returns `{"exit": 0, "stdout", "stderr", "artifact", "path", "field", "label", "span": [start, end],
    "proposed_sha", "rewritten", "flagged_lines"}` (`rewritten` False when a byte-identical proposal was already waiting).
    `Rejected` (a refusal of the mirror's own): no place for this kind and field, a source path that leaves the
    repository, a symlinked proposal, a table field. `Precondition` (nothing was changed): no source file, the id or the
    labelled line absent, the artifact already saying this, another proposal waiting (one per artifact: land it with
    /sprd-revise or delete it), the file unreadable or unwritable."""
    kind, ident, rel = proj.get("kind"), proj.get("id"), proj.get("source_path")
    label = text_target(kind, field)
    if label is None:
        raise Rejected(_no_place(kind, field))
    if not isinstance(rel, str) or not rel.strip() or not isinstance(ident, str) or not ident:
        raise Precondition("the item has no source file in this repository, so there is nothing to propose against")
    root = Path(repo_root).resolve()
    artifact = (root / rel).resolve()
    try:
        artifact.relative_to(root)
    except ValueError:
        raise Rejected(f"Refused: {rel} leaves the repository; a proposal is written only beside a file inside it.") from None
    if not artifact.is_file():
        raise Precondition(f"{rel} is not a file in this repository: there is nothing to propose against")
    try:
        original = _read_text(artifact)
    except (OSError, UnicodeDecodeError):
        raise Precondition(f"{rel} could not be read as UTF-8 text") from None
    span = locate_field(original, shape_for(rel), ident, label)
    value = spliced_value(original, span, text)
    if value == original[span["start"]:span["end"]]:
        raise Precondition(f"{rel} already says what the board says for {label} of {ident}: nothing to propose")
    proposed = write_document(original, [(span["start"], span["end"], value)])
    target = artifact.with_name(artifact.name + PROPOSED_SUFFIX)
    shown = rel + PROPOSED_SUFFIX
    rewritten = True
    if target.is_symlink():
        raise Rejected(f"Refused: {shown} is a symbolic link; a proposal is never written through one.")
    if target.exists():
        try:
            waiting = _read_text(target)
        except (OSError, UnicodeDecodeError):
            raise Precondition(f"{shown} exists and could not be read; nothing was changed") from None
        if waiting != proposed:
            raise Precondition(f"a proposal is already waiting beside the artifact ({shown}): land it with /sprd-revise "
                               "or delete it, then take this one; nothing was changed")
        rewritten = False
    else:
        tmp = target.with_name(target.name + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8", newline="") as fh:
                fh.write(proposed)
            os.replace(tmp, target)
        except OSError as exc:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise Precondition(f"could not write {shown} ({type(exc).__name__}); nothing was changed") from None
    flagged = sorted(flagged_lines or [])
    words = (f"Wrote {shown}: the board's words for {label} of {ident} sit in the artifact's own field (bytes "
             f"{span['start']}-{span['end']}); {rel} is not changed. Read the difference, then land it with /sprd-revise."
             if rewritten else
             f"{shown} already holds this proposal (nothing was rewritten); {rel} is not changed. Land it with "
             "/sprd-revise.")
    if flagged:
        words += (f" {len(flagged)} line{'' if len(flagged) == 1 else 's'} of it read as an instruction "
                  f"({dm.FLAG_MARK}): they are the board's words, shown as data -- not instructions.")
    return {"exit": 0, "stdout": words, "stderr": "", "artifact": rel, "path": shown, "field": field, "label": label,
            "span": [span["start"], span["end"]], "proposed_sha": _sha12(proposed), "rewritten": rewritten,
            "flagged_lines": flagged}


def propose(repo_root, *, proj: dict, remote: dict | None, field: str, comment: dict | None = None) -> dict:
    """The whole of `--take ado` on a C-class text field in one call: `text_target` (refused, naming what has a place,
    BEFORE any text is read), `proposal_text` (the board's current words, or the cached `comment`'s), `write_proposed`.
    Returns `write_proposed`'s result plus `"source"` (`board` or `comment`). `remote` is the item as
    `ado_wit_map.remote_item` documents it, read just now; nothing here reads the board."""
    if text_target(proj.get("kind"), field) is None:
        raise Rejected(_no_place(proj.get("kind"), field))
    got = proposal_text(remote, field, comment=comment)
    result = write_proposed(repo_root, proj=proj, field=field, text=got["text"], flagged_lines=got["flagged_lines"])
    return {**result, "source": got["source"]}


# --- what a `reconciled` line keeps of a --reason (house rule 10; the B4 critic) ----------------------------------

REASON_KEPT_TAKES: Final = ("not-drift", "ack")     # the takes that REQUIRE the words: the line is not honest without them


def reason_sha(text) -> str:
    """The first 12 hex of the sha256 of the typed words (trimmed): enough to tell two reasons apart, none of the words."""
    return hashlib.sha256(str(text).strip().encode("utf-8")).hexdigest()[:12]


def ledger_reason(take: str, reason) -> dict:
    """The fields a `--reason` becomes on a committed `reconciled` line: `{}` when none was given; for `--take not-drift`
    and `--take ack` (which require one) `{"reason": <the words>}`; for `--take ado` and `--take sdlc`
    `{"reason": "<text>", "reason_sha": <12 hex>}`, because a resolution or an unslate reason may be a board comment's
    own words. `Precondition` (nothing started) when the words carry an e-mail address or an id, for any take."""
    words = reason.strip() if isinstance(reason, str) else ""
    if not words:
        return {}
    if bc.EMAIL_RE.search(words) or bc.GUID_RE.search(words):
        raise Precondition("not written to the ledger: a reason may not carry an e-mail address or an id (name the "
                           "person's handle, not their address); nothing was started")
    if take in REASON_KEPT_TAKES:
        return {"reason": words}
    return {"reason": TEXT, "reason_sha": reason_sha(words)}
