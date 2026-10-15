"""ado_sync.py -- The CLI of the Azure Boards mirror: set it up, read the client's process, plan, read and write the board.

Azure DevOps Boards is a board the team already uses; this mirror projects the repository's specs, epics and
features onto it and reads board changes back. Fold B1 shipped the verbs that never touch a work item; Fold B2
adds the READ verbs; Fold B3 adds the WRITE verbs; Fold B4 adds `reconcile`; Fold B6 adds `sync`, the catch-up that
runs the reads in one pass and sends nothing. The one place the mirror writes to the
board is `apply` (through `ado_sync_apply`, as the person whose `az` login is active) and `link-pr`; `iteration bind`,
`posture` and `comment` write only files in this repository; `reconcile` records a disposition and, for `--take ado`,
starts the verb that owns the field (through `ado_sync_reconcile`). A write verb needs a named human as `--by`, and
`apply` and `link-pr` also need posture `assisted`.

  config init [--force]   copy the starter `.sdlc/ado.yaml` in and ignore the local cache folder
  config check            the config's findings, one per line (against the saved schema when there is one)
  discover [--team T] [--refresh]
                          read the process with serial `devops invoke` GETs, save `.sdlc/ado/schema.json`
  validate                every configured kind resolves on the discovered process; the fit table and the
                          process additions an administrator would make for what does not fit as an item
  plan [--kind K] [--id ID] [--sprint SNN] [--all] [--validate] [--no-comments]
                          the dry run: what each item of the repository would do on the board (create, update,
                          link, or why it would not), the hash a person echoes to `apply`
  status                  what the ledger says, offline: linked, pending, drifted, as of when -- `no data`
                          where nothing was ever measured, never a zero
  pull [--id ID] [--all] [--discussion] [--full] [--propose-specs]
                          read the ledgered items back: record `observed` and `drift_seen`, write the session
                          hook's one line, and say under each drift row what a person may do about it;
                          `--discussion` caches each item's comments instead (`--full`, which forgets the comment
                          watermark, implies `--discussion`); `--propose-specs` also writes ONE batch file of
                          proposals (argument lists, nothing run) for the board items nobody has mapped
  drift [--id ID] [--kind K]
                          the same classification as `pull`, printed, and the board items nobody has linked
  sync [--kind K] [--id ID] [--sprint SNN] [--all] [--discussion] [--no-comments]
                          the catch-up in one read, four stages in order: `pull` (the fields), `drift` classified from
                          that pull's own rows (the board is not asked again — the untagged-items query is not
                          run, and the stage says so), the discussion pull ONLY on `--discussion` (there is no
                          `--full`), then `plan`;
                          ends with the same `Next:` line `plan` and `comment` print where an apply is offered
  link <ref> --work-item N --by H | adopt --all --by H
                          map a repository item to a work item that exists (the ledger's `linked`)
  show <ref|#id> [--fetch] [--versions] [--expand reactions] [--for-agent]
                          a work item's cached discussion, quoted; `--fetch` reads it from the board first
  discussion gc [--dry-run]
                          delete discussion caches past `discussion.retain_days` or for unlinked items
  apply --confirm <12hex> --by H [--limit N]
                          send the plan a person confirmed (the hash `plan` printed) to the board, as that person:
                          field ops first, then comments; every write is ledgered
  link-pr --spec NNNN --pr N --by H
                          link a pull request to the spec's work item (one `az repos pr work-item add`)
  iteration bind SNN --path P --by H
                          bind a sprint to an iteration path the discovered schema has (`.sdlc/ado.yaml` only)
  posture plan-only|assisted --by H
                          switch this clone's posture (`.sdlc/ado.yaml` only); `assisted` is what offers `apply`
  comment <ref|#id> --message=TEXT --by H [--mention @h ...] [--event NAME]
                          draft one comment as a one-row plan file; nothing is sent until `apply --confirm`
  reconcile <ref> --take ado|sdlc|ack|not-drift --by H [--field F] [--owner H] [--reason TEXT] [--from-comment ID]
                          settle one drift row `pull` recorded: `ado` starts the verb that owns the field (a spec's
                          assignee: `spec_transition.py assign`; its sprint: `sprint.py slate|unslate`; a decision's
                          close: `track_decisions.py decide`) and records its exit; `sdlc` keeps the repository's
                          value (the next `apply` puts it back); `ack` needs `--owner`, `not-drift` a `--reason`

What it reads
  - `.sdlc/ado.yaml` (the config), `.sdlc/ado/schema.json` (what `discover` saved), the repository's own specs,
    epics, features, sprints and decisions (through `ado_sync_sources`), `.sdlc/team.yaml`, and the ledger
  - Azure DevOps through `ado_wit` (and `ado_transport.invoke_body` for `discover`); `az` is never called twice
    for the same answer and never probed to explain a failure (the `host` block reads the failure it was given)
What it writes
  - `config init`: `.sdlc/ado.yaml` and `.sdlc/ado/local/.gitignore`; `discover`: `.sdlc/ado/schema.json`
  - `plan`: `.sdlc/ado/local/plans/<hash>.json`, ledger `planned`, `.sdlc/ado/local/hook-status.txt`
  - `sync`: what `pull` and `plan` write, once each (the hook line is written twice, the plan stage's is line 1;
    with `--discussion`, the discussion cache too) -- and nothing the board holds
  - `pull`: ledger `observed` and `drift_seen`, the hook line; `pull --discussion` and `show --fetch`: the local
    discussion cache (`.sdlc/ado/local/discussion/<id>.json`, `me.json`) and ledger `discussion_pulled`,
    `comment_seen`, `directive_seen` -- counts, ids and hashes only, never a comment's text, a name or an address
  - `pull --propose-specs`: one file under `.sdlc/ado/local/proposals/` (the ignored local folder); its `counts` are
    `null` when the search did not run, the items could not be read or the file was not written
  - `reconcile`: ledger `reconciled` (the disposition, the child's exit, the child's argument list with every free-text
    value as `<text>`); `--take ado` also runs the owning verb, which writes its own file (a spec's frontmatter, a
    sprint record, the decision log)
  - `link`, `adopt`: ledger `linked`; `discussion gc`: deletions under the local folder, ledger `discussion_gc`
  - `apply`: the board (work items it creates or updates, comments it posts), ledger `applied`, `commented`,
    `conflict`, `refused` (written by `ado_sync_apply`); `link-pr`: one relation on the board, ledger `applied`
    (`action: link_pr`, the item's baseline carried); `posture`: `.sdlc/ado.yaml`, ledger `posture`;
    `iteration bind`: `.sdlc/ado.yaml`, ledger `iteration_bound`; `comment`: one plan file, and ledger
    `comment_refused` when the text is refused -- never the board
  - Nothing else: never `state.yaml`, and no spec, sprint or decision except through the verb that owns it
    (`reconcile --take ado`). `--help` and an import write nothing.
  The ledger is `.sdlc/metrics/ado-sync-log.jsonl`, append-only, one `json.dumps(event)` per line; a failed
  append prints `DRIFT: ...` and exits 1. A `linked` (or, later, `applied`) line carries `work_item`, `rev_after`
  (the board's revision it was written against), `type` and `projection_hash`: `ado_sync_model.projection_hash` of
  the projection WITH the `sdlc-repo:<slug>` tag added, which is the document every verb here compares and plans.

Exit codes (the kit's verb table)
  config init   0 written  | 1 the config exists and no --force
  config check  0 valid    | 1 missing, not YAML, wrong type, or a pin the process lacks | 2 refused (an unknown key,
                                an activity-metric field, free text without a named reviewer, a value out of range)
  discover      0 saved (or the schema read today is reused)
                | 1 any AdoImportError: az absent, a refused or failed call (the call is named), a remote that is
                  not Azure DevOps, a document the mapping does not recognise. The `host` block is printed.
  validate      0 resolvable | 1 gaps (no config or schema, an unresolvable pin, a kind with no type) |
                2 a forbidden field is mapped
  plan, status, drift, show
                0 always -- a board that cannot be reached (or a missing config or schema) is `unavailable` with
                no rows, never a failure; so is a ledger that cannot be read or holds a line that is not a ledger
                line, and a plan file that cannot be written (`unavailable: <reason>`; in `--json`
                `"unavailable": "<reason>"`). A ledger append or hook line that fails after the read is printed
                (`DRIFT: ...`, `hook line: not written`) and the exit is still 0. 1 only for a usage error (a ref
                that is not ledgered and no `#id`, a target that is neither, a `--sprint` that is not a sprint
                id, `--fetch`/`--versions` on a remote that is not Azure DevOps); an unknown `--kind` is
                argparse's own usage error (2), the choices being `boards_contract.KINDS`
  sync          0 always -- a stage that cannot read is that stage's `unavailable` (the next still runs) and every stage
                `unavailable` still exits 0 | 1 `DRIFT` in the pull (or discussion) stage, recorded as `drift_error`
                with the later stages run; a `--sprint` that is not a sprint id is a usage error (1)
  pull          0 | 1 `DRIFT` (the ledger append failed) -- and nothing else: an unreadable ledger is `unavailable`
                (exit 0), and `--full` without `--discussion` implies it; a board item the search cannot read is a
                note, not a failure. 1 also for `--propose-specs` together with `--discussion` (a usage error)
  link, adopt   0 linked | 1 the item is not found, is already mapped, carries another mirror ref, or is ambiguous;
                the ledger cannot be read; `--by` names two people on the roster
                | 2 an AI or agent `--by`, an e-mail address that is on nobody's roster entry, or the `AB#` form
  discussion gc 0 | 1 `DRIFT`
  apply         0 every row applied (a row deferred by `--limit` or `limits.writes_per_run` is the person's choice)
                | 1 a row failed (a conflict, a rule, a stop), a stale hash (the plan file's rows no longer hash to
                  its id), a plan that is missing, a ledger that cannot be read or appended to (`DRIFT`), a board
                  that cannot be read before the first write, a `--confirm` that is not 12 hex
                | 2 an AI or agent `--by`, an address off the roster, posture `plan-only` (`apply not offered in this
                  clone`), or a whole-plan refusal with NOTHING sent: a forbidden effort field, a comment row
                  refused while drafting, the first `--all` seed over `limits.first_seed` without a `--limit` in
                  range, an `az` identity that is not `--by` (`identity_mismatch`, `identity_unknown`)
  link-pr       0 linked (or already linked in this clone's ledger) | 1 the spec is not ledgered, a bad id, `az`
                refused or failed (the class is said; an unknown outcome says the link may exist), `DRIFT` after the
                link landed | 2 an AI `--by`, an address off the roster, posture `plan-only`
  iteration bind
                0 bound (or already bound) | 1 not a sprint id, no discovered schema, a path the schema does not have,
                `DRIFT` | 2 an AI `--by` or an address off the roster
  posture       0 changed (or already that value) | 1 no config, `DRIFT` | 2 an AI `--by` or an address off the roster;
                it works under `plan-only`: it is how a clone leaves it
  comment       0 plan written (also under `plan-only`, where it prints `apply not offered in this clone`), or nothing
                to draft because the key was already posted | 1 not ledgered, a message that is empty, a mention
                that is not `@handle`, `DRIFT` | 2 an AI `--by`, or the text refused: `max_chars`, `email_in_text`,
                `event_unknown`, `budget`, `needs_disposition` (ledgered `comment_refused`)
  reconcile     0 settled, or recorded (`--take sdlc` stays open until `apply` lands the field) | 1 no drift row of that
                  ref and field, a row already settled, a board or schema that cannot answer, an assignee or iteration
                  path the mirror has no one for, a ledger that cannot be appended to (nothing was started), or the owning
                  verb failed (ITS exit 1 -- any nonzero exit, even argparse's 2 -- is 1 here, never 2); the failed child
                  is ledgered and the row stays open
                | 2 an AI `--by` or `--owner`, `--take ack` without `--owner`, `--take not-drift` without `--reason`, a
                  take the disposition machine has no word for (DELETED_IN_ADO takes `ack`; ORPHAN_IN_REPO takes none
                  in this version), `--take ado` on a field the board does not own or that no verb owns (a spec's
                  State is never taken), a developer change on an in-flight spec, `--take sdlc` on a field the board
                  owns, a resolution a person did not type (`--from-comment` alone is this refusal: it prints the
                  cached comment as a suggestion to type, never fills it in, and never copies it into a file)
  Refused (2) is a setting the mirror will not honour or a name that reads as an agent; Illegal (1) is a missing
  precondition, and Usage (an Illegal) the read verbs' only exit 1 besides `pull`'s DRIFT. Refused and Illegal are
  copied from `sprint.py`, not imported.
  `--by` is ledgered as a roster `@handle` when the typed text is, case-insensitively, one person's `handle`, `name`
  or `email` on `.sdlc/team.yaml`; a name that matches nobody is kept as typed (the `sprint.py` precedent).

Honesty: a team, backlog or state never read is `null` in the schema and "not discovered" in the output, never an
empty list or a zero; a count never measured is `null` / "no data" and a 0 appears only after a read that found
none; `--json` prints exactly one JSON document on stdout. The ledger, the plan file and every output of these
verbs carry no e-mail address, GUID or display name: an assignee is a roster `@handle`.

Standalone or Workflow (CLAUDE.md design rule):
  - Standalone: --repo <path>              (default: cwd) needs no `.sdlc/state.yaml`
  - Workflow:   --state .sdlc/state.yaml   repo root = the directory containing `.sdlc/`
`--help` for the script and for every verb does no filesystem work and exits 0 from any cwd.
"""

import argparse
import copy
import json
import os
import re
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ado_discussion_cache as cache  # noqa: E402
import ado_discussion_map as dm  # noqa: E402
import ado_schema  # noqa: E402
import ado_schema_map as sm  # noqa: E402
import ado_sync_apply as apply_mod  # noqa: E402
import ado_sync_comments as comments_mod  # noqa: E402
import ado_sync_config as cfgmod  # noqa: E402
import ado_sync_model as model  # noqa: E402
import ado_sync_reconcile as rc  # noqa: E402  (the one module that starts the owning verbs; this CLI never does)
import ado_sync_sources as sources  # noqa: E402
import ado_sync_sources_tree  # noqa: E402,F401  (registers outcome, domain, requirement and the epic parent)
import ado_sync_sources_df  # noqa: E402,F401  (registers finding: review findings as BugCategory items)
import ado_sync_sources_p1  # noqa: E402,F401  (registers the breadth sources: nfr, rule, question, lifecycle, measurement)
import ado_transport  # noqa: E402
import ado_wit  # noqa: E402
import ado_wit_map as wm  # noqa: E402
import boards_contract as bc  # noqa: E402
import host_report  # noqa: E402
import validate_team  # noqa: E402
from ado_map import AdoImportError  # noqa: E402
from boards_contract import CONFIG_FILE, KINDS, LEDGER, LOCAL_DIR, REF_RE, SCHEMA_FILE, TREE_ORDER  # noqa: E402
from check_spec import parse_frontmatter  # noqa: E402
from sprint_model import SPRINT_ID_RE  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
AGENT_PREFIX = model.AGENT_PREFIX  # "shepherd:", the only prefix `ai_by` strips
# The kinds `validate` checks as work item types without a fit: the config must name the type.
PINNED_KINDS = ("spike", "decision", "finding", "question")
# The starter's `kinds` (templates/ado/ado.yaml); a config without the key means this set.
DEFAULT_KINDS = bc.DEFAULT_KINDS
RESULT_WORDS = {0: "resolvable", 1: "gaps", 2: "refused"}
# How a fit mode reads in the text table; `--json` keeps the mode itself. A tree kind whose backlog levels were
# never read is "not discovered" -- not known, never a 0 and never a gap.
MODE_WORDS = {sm.UNKNOWN: "not discovered"}
CHECK_WORDS = {0: "valid", 1: "gaps", 2: "refused"}

# Every agents/*.md stem, read once at import (a read, never a write). A `--by` that is one of these is an agent.
AGENT_STEMS: frozenset[str] = frozenset(p.stem for p in (PLUGIN_ROOT / "agents").glob("*.md"))


class Refused(Exception):
    """Exit 2: a setting the mirror will not honour, or a `--by` that reads as an AI or an agent."""


class Illegal(Exception):
    """Exit 1: an illegal operation or a missing precondition."""


class Usage(Illegal):
    """Exit 1 on a read verb too: the command line asks for something that cannot be read as asked (a ref this clone
    never ledgered, a target that is neither a ref nor `#id`, a `--sprint` that is not a sprint id, `--fetch` on a
    remote that is not Azure DevOps). Any other `Illegal` on a read verb is answered `unavailable`, exit 0."""


class LedgerUnreadable(Illegal):
    """The ledger exists but cannot be read, or a line of it is not a ledger line. A read verb answers
    `unavailable: <reason>` and exits 0; a verb that would append to it stops with exit 1 (it does not add to a
    record it cannot read)."""


# The verbs that only read the board (`pull` also records what it read): house rule 4, they exit 0 on every path
# that is not a usage error; `pull` and `sync` (which runs it as its first stage) may exit 1, and only for `DRIFT`.
READ_VERBS = ("plan", "status", "pull", "drift", "show", "sync")
# What each read verb's `--json` carries when it is `unavailable`, beside `unavailable` and `reason`.
UNAVAILABLE_EXTRA: dict[str, dict] = {"plan": {"plan": None, "rows": [], "counts": None},
                                      "pull": {"items": [], "counts": None, "proposals": []},
                                      "drift": {"items": [], "counts": None}, "show": {}, "status": {},
                                      "sync": {"pull": None, "drift": None, "discussion": None, "plan": None,
                                               "counts": None, "next": None}}
# The read verbs whose `--json` says `"unavailable": true` when `main` answers for an escape from the verb (`sync`,
# which is shaped like `ado_sync_model.SYNC_NODATA`); the older ones keep the sentence in `unavailable`, which is
# what the desktop's DiscussionBlock reads from `show`.
BOOL_UNAVAILABLE_VERBS = ("sync",)


# --- people, paths, the host -----------------------------------------------------------------------------------

def require_human(name: str | None, flag: str) -> str:
    """A named human for `--by`. A blank is `Illegal` (1). An AI or an agent is `Refused` (2), decided by
    `ado_sync_model.ai_by` (K7): the name after a leading `shepherd:` (only that prefix) reads as an AI
    (`is_ai_actor`), is an `agents/*.md` stem, or is one of the discipline agents. Honestly labelled: this is a
    label check, not an identity check."""
    clean = str(name or "").strip()
    if not clean:
        raise Illegal(f"{flag} is required: name a person, not a role or a blank")
    if model.ai_by(clean, AGENT_STEMS):
        raise Refused(f"Refused: {flag} '{clean}' reads as an AI or an agent, not a named human. The mirror records "
                      "who is accountable for a change to the board; an agent may not be that name. (This is "
                      "labelling, not enforcement: it cannot verify identity, only refuse the obvious.)")
    return clean


EMAIL_SHAPED = re.compile(r"@.*\.")  # the loose shape `--by` refuses off the roster: an `@` with a `.` after it


def _roster_handles_for(roster: dict, typed: str) -> list[str]:
    """The roster handles whose `handle`, `name` or `email` is `typed`, case-insensitively: an exact match or none,
    never a guess (no prefix, no initials, no handle made up from a name)."""
    folded = typed.casefold()
    found = {h for h in validate_team.people_handles(roster) if h.strip().casefold() == folded}
    found |= {h for email, h in validate_team.people_by_email(roster).items() if email.casefold() == folded}
    people = roster.get("people") if isinstance(roster.get("people"), list) else []
    found |= {p["handle"] for p in people if isinstance(p, dict) and isinstance(p.get("handle"), str)
              and p["handle"].strip() and isinstance(p.get("name"), str) and p["name"].strip().casefold() == folded}
    return sorted({h.strip() for h in found})


def resolve_by(repo_root: Path, name: str | None, flag: str) -> str:
    """The `--by` a ledger line records (house rule 10): `require_human`'s name, as the roster `@handle` it names.
    One person on `.sdlc/team.yaml` whose `handle`, `name` or `email` is the typed text (case-insensitively) is
    that person's handle; two are `Illegal` (the mirror never picks one). Off the roster, an e-mail-shaped value
    (an `@` with a `.` after it) is `Refused` (exit 2: the ledger never keeps an address) and any other name is
    kept as typed, as `sprint.py` keeps it. Labelling, not identity: it refuses the obvious only."""
    clean = require_human(name, flag)
    handles = _roster_handles_for(_roster(repo_root), clean)
    if len(handles) > 1:
        raise Illegal(f"{flag} names {len(handles)} people on the roster ({', '.join(handles)}): give the handle")
    if handles:
        return require_human(handles[0], flag)
    if EMAIL_SHAPED.search(clean):
        raise Refused(f"Refused: {flag} reads as an e-mail address that is on nobody's roster entry: give a roster "
                      "handle or a name, not an address. (The ledger names a person by @handle and never keeps an "
                      "address.)")
    return clean


def resolve_repo_root(args) -> Path | None:
    """Repo root: the parent of `.sdlc/` from `--state` (None if the state file is missing), else `--repo`."""
    if getattr(args, "state", None):
        state_path = Path(args.state)
        if not state_path.is_file():
            return None
        return state_path.resolve().parent.parent
    return Path(getattr(args, "repo", None) or ".").resolve()


def host_block_for(repo_root, error: str | None) -> dict:
    """The `host` block, read from the error the call just raised (None = it answered). It never probes the CLI."""
    return host_report.host_block(host_report.detect(repo_root), error)


def _rel(repo_root: Path, path: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


# --- output ----------------------------------------------------------------------------------------------------------

def _emit(args, payload: dict, text: str) -> None:
    """`--json` prints exactly one document; otherwise the text."""
    print(json.dumps(payload, indent=2) if args.json else text.rstrip("\n"))


def _error(args, message: str, code: int, **extra) -> int:
    if args.json:
        print(json.dumps({"ok": False, "error": message, "exit": code, **extra}, indent=2))
    else:
        print(message if code == 2 else f"Error: {message}")
    return code


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _host_line(host: dict) -> str:
    return f"Host: {host['name']} (source: {host['source']}); {host['cli']}: {host['cli_state']} - {host['detail']}"


def _name_of(obj) -> str | None:
    name = obj.get("name") if isinstance(obj, dict) else None
    return name if isinstance(name, str) and name else None


# --- config ----------------------------------------------------------------------------------------------------------

def cmd_config(args, repo_root: Path) -> int:
    return _config_init(args, repo_root) if args.config_verb == "init" else _config_check(args, repo_root)


def _config_init(args, repo_root: Path) -> int:
    target = repo_root / CONFIG_FILE
    if (target.exists() or target.is_symlink()) and not args.force:
        raise Illegal(f"{CONFIG_FILE} already exists; keep it, or pass --force to replace it with the starter")
    written = [_rel(repo_root, p) for p in cfgmod.init_config(repo_root, force=args.force)]
    text = "\n".join([*(f"Wrote {rel}" for rel in written),
                      "Edit the config, then run `ado_sync.py config check`; `ado_sync.py discover` reads the process "
                      "it will be checked against."])
    _emit(args, {"ok": True, "written": written}, text)
    return 0


def _schema_or_note(repo_root: Path) -> tuple[dict | None, str | None]:
    try:
        return ado_schema.load_schema(repo_root), None
    except AdoImportError as exc:
        return None, str(exc)


def _with_refusals(schema: dict | None) -> dict | None:
    """The schema as `validate_config` reads it: plus the fields the process says the mirror never writes."""
    return None if schema is None else {**schema, "refused_fields": sorted(sm.refused_fields(schema))}


def _counts(rows: list[dict]) -> dict:
    return {level: sum(1 for r in rows if r["level"] == level) for level in ("refused", "unresolvable", "invalid")}


def _exit_for(rows: list[dict], gaps: list[str]) -> int:
    if any(r["level"] == "refused" for r in rows):
        return 2
    return 1 if rows or gaps else 0


def _schema_line(schema: dict | None) -> str:
    if schema is None:
        return "Schema: not discovered yet (run `ado_sync.py discover`)"
    age = ado_schema.schema_age_days(schema, ado_schema.today())
    old = "age unknown" if age is None else f"{_plural(age, 'day')} old"
    return (f"Schema: read {schema.get('discovered_at') or 'at an unknown time'} ({old}), "
            f"team {_name_of(schema.get('team')) or 'not set'}")


def _schema_facts(schema: dict | None) -> dict | None:
    if schema is None:
        return None
    return {"discovered_at": schema.get("discovered_at"),
            "age_days": ado_schema.schema_age_days(schema, ado_schema.today()),
            "team": _name_of(schema.get("team"))}


def _finding_lines(rows: list[dict]) -> list[str]:
    return ["", "Config findings", *[f"  {r['level']}: {r['message']}" for r in rows]] if rows else []


def _config_check(args, repo_root: Path) -> int:
    cfg = cfgmod.load_config(repo_root)  # ConfigError -> main: missing / invalid exit 1
    schema, note = _schema_or_note(repo_root)
    rows = cfgmod.validate_config(cfg, _with_refusals(schema))
    code = _exit_for(rows, [])
    lines = [f"Config: {CONFIG_FILE}, {_plural(len(rows), 'finding')}",
             _schema_line(schema) if note is None else f"Schema: ignored ({note})",
             *_finding_lines(rows), "", f"Result: {CHECK_WORDS[code]} (exit {code})"]
    payload = {"ok": code == 0, "exit": code, "config": CONFIG_FILE, "schema": _schema_facts(schema), "rows": rows,
               "counts": _counts(rows)}
    if note is not None:
        payload["schema_note"] = note
    _emit(args, payload, "\n".join(lines))
    return code


# --- discover --------------------------------------------------------------------------------------------------------

def _clean(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _per_type_reads(schema: dict) -> list[str]:
    """The types read one by one, in the order read: each per-type fields read (`wit/workItemTypesField type=<name>`
    since the B0 capture; a schema saved before it names `wit/states type=<name>`), each type once."""
    row = bc.WIT_ROUTES["type_fields"]
    prefixes = (f"{row['area']}/{row['resource']} type=", "wit/states type=")
    out: list[str] = []
    for c in schema.get("commands") or []:
        for prefix in prefixes:
            if isinstance(c, str) and c.startswith(prefix) and c[len(prefix):] not in out:
                out.append(c[len(prefix):])
    return out


def _discover_payload(schema: dict, *, reused: bool, host: dict | None, notes: list[str]) -> dict:
    backlog = schema.get("backlog")
    team_iterations = schema.get("team_iterations")
    return {"ok": True, "reused": reused, "path": SCHEMA_FILE, "discovered_at": schema.get("discovered_at"),
            "project": _name_of(schema.get("project")), "team": _name_of(schema.get("team")),
            "counts": {"types": len(schema.get("types") or {}), "fields": len(schema.get("fields") or {}),
                       "areas": len(schema.get("areas") or []), "iterations": len(schema.get("iterations") or []),
                       "team_iterations": len(team_iterations) if isinstance(team_iterations, list) else None,
                       "link_types": len(schema.get("link_types") or []),
                       "levels": len(backlog["levels"]) if isinstance(backlog, dict) else None},
            "per_type_reads": _per_type_reads(schema), "notes": notes, "host": host}


def _discover_text(payload: dict) -> str:
    c = payload["counts"]
    where = f"{payload['project'] or 'the project'} (team: {payload['team'] or 'not set'})"
    levels = "not read" if c["levels"] is None else str(c["levels"])
    team_iterations = "not read" if c["team_iterations"] is None else str(c["team_iterations"])
    reads = ", ".join(payload["per_type_reads"]) or "none"
    if payload["reused"]:
        head = (f"The saved schema for {where} was read today ({payload['discovered_at']}); nothing was read from "
                f"Azure DevOps. Pass --refresh to read it again.")
    else:
        head = f"Discovered the Azure DevOps process for {where} and saved {payload['path']}."
    lines = [head,
             f"  work item types {c['types']}, fields {c['fields']}, area paths {c['areas']}, iterations "
             f"{c['iterations']}, team iterations {team_iterations}, backlog levels {levels}",
             f"  states and fields read per type for: {reads}",
             *[f"Note: {n}" for n in payload["notes"]]]
    if payload["host"] is not None:
        lines.append(_host_line(payload["host"]))
    lines.append("Next: `ado_sync.py validate` checks the config against it.")
    return "\n".join(lines)


def _discover_failed(args, repo_root: Path, message: str, *, host_error: str | None) -> int:
    host = host_block_for(repo_root, host_error)
    if args.json:
        return _error(args, message, 1, host=host)
    code = _error(args, message, 1)
    print(_host_line(host))
    return code


def cmd_discover(args, repo_root: Path) -> int:
    cfg, cfg_note = ado_schema.discovery_config(repo_root)
    notes = [cfg_note] if cfg_note else []
    wanted = _clean(args.team) or _clean(cfg.get("team"))
    if not args.refresh:
        try:
            cached = ado_schema.load_schema(repo_root)
        except AdoImportError:
            cached = None  # a corrupt file is replaced by the read below
        if cached is not None and ado_schema.is_reusable(cached, cfg, wanted, ado_schema.today()):
            payload = _discover_payload(cached, reused=True, host=None, notes=notes)
            _emit(args, payload, _discover_text(payload))
            return 0
    try:
        schema = ado_schema.discover(repo_root, args.team, notes=notes, cfg=cfg)
    except AdoImportError as exc:
        return _discover_failed(args, repo_root, str(exc), host_error=str(exc))
    try:
        ado_schema.save_schema(repo_root, schema)
    except AdoImportError as exc:  # the identity guard: az answered, the file was refused
        return _discover_failed(args, repo_root, str(exc), host_error=None)
    except OSError as exc:
        return _discover_failed(args, repo_root, f"could not write {SCHEMA_FILE} ({type(exc).__name__})",
                                host_error=None)
    payload = _discover_payload(schema, reused=False, host=host_block_for(repo_root, None), notes=notes)
    _emit(args, payload, _discover_text(payload))
    return 0


# --- validate --------------------------------------------------------------------------------------------------------

def _configured_kinds(cfg: dict) -> tuple[str, ...]:
    return sm.configured_kinds(cfg)


def _fit_view(schema: dict, cfg: dict, kinds: tuple[str, ...]) -> tuple[dict, dict, list[str], list[str]]:
    """`(fit, resolved, gaps, recommendations)` for the configured kinds. A tree kind (outcome, domain,
    requirement) lands somewhere (an item, an Area Path or a tag) or, when the backlog levels were never read,
    is not known yet (`unknown`, printed "not discovered"); neither is a gap. Epic, feature and spec must
    resolve to a type, and so must a spike, decision, finding or question, which have no default."""
    fit = {k: v for k, v in sm.fit_levels(schema, cfg).items() if k in kinds}
    resolved = {}
    for kind in PINNED_KINDS:
        if kind in kinds:
            name, reason = sm.resolve_type(schema, kind, cfg)
            resolved[kind] = {"type": name, "reason": reason}
    gaps = [f"{k}: {v['reason']}" for k, v in fit.items() if k in ("epic", "feature", "spec") and v["type"] is None]
    gaps += [f"{k}: {v['reason']}" for k, v in resolved.items() if v["type"] is None]
    return fit, resolved, gaps, sm.recommendations(fit, schema)


def _fit_table(fit: dict, resolved: dict) -> list[str]:
    rows = [(k, MODE_WORDS.get(v["mode"], v["mode"]), v["type"] or "-", "-" if v["level"] is None else str(v["level"]),
             v["reason"]) for k, v in fit.items()]
    rows += [(k, "item" if v["type"] else "-", v["type"] or "-", "-", v["reason"]) for k, v in resolved.items()]
    header = ("kind", "mode", "type", "level", "why")
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(4)]
    return [("  " + "  ".join([*(cell.ljust(widths[i]) for i, cell in enumerate(row[:4])), row[4]])).rstrip()
            for row in [header, *rows]]


def cmd_validate(args, repo_root: Path) -> int:
    cfg = cfgmod.load_config(repo_root)       # ConfigError -> main
    schema = ado_schema.load_schema(repo_root)  # an unusable file -> AdoImportError -> main (exit 1)
    rows = cfgmod.validate_config(cfg, _with_refusals(schema))
    fit, resolved, recommendations = {}, {}, []
    if schema is None:
        gaps = ["no discovered schema: run `ado_sync.py discover` first, so there is a process to check the config against"]
    else:
        fit, resolved, gaps, recommendations = _fit_view(schema, cfg, _configured_kinds(cfg))
    code = _exit_for(rows, gaps)
    lines = ["Azure Boards mirror: validate", _schema_line(schema),
             f"Config: {CONFIG_FILE}, {_plural(len(rows), 'finding')}", *_finding_lines(rows)]
    if fit or resolved:
        lines += ["", "How each kind lands on this process", *_fit_table(fit, resolved)]
    if gaps:
        lines += ["", "Gaps", *[f"  - {g}" for g in gaps]]
    if recommendations:
        lines += ["", "Recommendations", *[f"  - {r}" for r in recommendations]]
    lines += ["", f"Result: {RESULT_WORDS[code]} (exit {code})"]
    payload = {"ok": code == 0, "exit": code, "schema": _schema_facts(schema), "rows": rows, "counts": _counts(rows),
               "fit": fit, "resolved": resolved, "gaps": gaps, "recommendations": recommendations}
    _emit(args, payload, "\n".join(lines))
    return code


# --- the ledger, the clock and the local files ---------------------------------------------------------------------

LINKING_EVENTS = ("linked", "adopted", "applied")
PLAN_SCHEMA = 1
LEDGER_STAMP = "%Y-%m-%dT%H:%MZ"  # minute precision, the form the hook line prints after "as of"


class LedgerDrift(Exception):
    """Exit 1: a ledger append failed, so the files and the ledger now disagree."""


def _now() -> datetime:
    return ado_schema.now_utc()


def _stamp(now: datetime | None = None) -> str:
    return (now or _now()).strftime(LEDGER_STAMP)


def _tidy(text, limit: int = 240) -> str:
    """One line of someone else's words (an `az` error): control characters gone, runs collapsed, cut."""
    clean = " ".join(dm.strip_control(str(text)).split())
    return clean if len(clean) <= limit else clean[:limit - 1] + "…"


def _event(ts: str, name: str, **fields) -> dict:
    """One ledger line through the model (it refuses an unknown event, an address and a GUID)."""
    try:
        return model.ledger_entry(ts, name, **fields)
    except ValueError as exc:
        raise Illegal(f"not written to the ledger: {exc}") from None


LEDGER_TEXT_KEYS = ("event", "ref", "field", "plan", "class", "kind")  # looked up and grouped by: a string or null


def _not_a_ledger_line(entry) -> str | None:
    """Why a parsed line is not a ledger line, or None when it is one."""
    if not isinstance(entry, dict):
        return "is not a JSON object"
    for key in LEDGER_TEXT_KEYS:
        if entry.get(key) is not None and not isinstance(entry[key], str):
            return f"has a {key!r} that is not a string"
    if entry.get("fields") is not None and not isinstance(entry["fields"], list):
        return "has a 'fields' that is not a list"
    return None


def read_ledger(repo_root) -> list[dict]:
    """The ledger's lines in append order; a missing file is `[]` and a blank line is skipped. A file that cannot be
    read, or a line that is not a ledger line (not a JSON object; an `event`, `ref`, `field`, `plan`, `class` or
    `kind` that is not a string or null; `fields` that is not a list), is `LedgerUnreadable` naming the line: the
    ledger is append-only, so a person repairs the line, and a line skipped in silence would undercount."""
    path = Path(repo_root) / LEDGER
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise LedgerUnreadable(f"{LEDGER} could not be read ({type(exc).__name__})") from None
    out = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except (ValueError, RecursionError):
            entry = None
        problem = _not_a_ledger_line(entry)
        if problem:
            raise LedgerUnreadable(f"{LEDGER} line {number} {problem}; the ledger is append-only, so repair or "
                                   "remove that line by hand (nothing was read from the ledger)")
        out.append(entry)
    return out


def _summary(ledger: list[dict]) -> dict:
    """`ado_sync_model.summarize` of the ledger as of today. A line the summary cannot read is `LedgerUnreadable`:
    `status` then says so instead of a traceback."""
    try:
        return model.summarize(ledger, ado_schema.today())
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        raise LedgerUnreadable(f"{LEDGER} holds a line the summary cannot read ({type(exc).__name__}: "
                               f"{_tidy(exc, 120)})") from None


def append_ledger(repo_root, events: list[dict]) -> None:
    """Append one `json.dumps(event)` line per event, opened with "a". An `OSError` is `LedgerDrift` (copied from
    `sprint.py`'s `commit`): the caller has already written whatever else the verb writes."""
    if not events:
        return
    path = Path(repo_root) / LEDGER
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")
    except OSError as exc:
        raise LedgerDrift(f"DRIFT: the ledger append failed ({LEDGER}): {exc}\n"
                          "       Anything else this verb wrote now disagrees with the ledger; "
                          "re-run it once the path is writable.") from None


def _is_id(value) -> bool:
    return type(value) is int and value >= 1


def _word(value) -> str:
    return str(value or "").strip().upper().replace("-", "_")


def linked_items(ledger: list[dict]) -> dict[str, dict]:
    """`ref` -> its last linking line (`linked`, `adopted` or `applied`, with an integer `work_item`). A ref whose
    last word is an UNLINK `reconciled` line is left out: the rule `ado_sync_model.summarize` counts `linked` by."""
    out: dict[str, dict] = {}
    for e in ledger:
        event, ref = e.get("event"), e.get("ref")
        if event not in model.LEDGER_EVENTS or not isinstance(ref, str) or not ref:
            continue
        if event in LINKING_EVENTS and _is_id(e.get("work_item")):
            out[ref] = e
        elif event == "reconciled" and ref in out and not e.get("field") and _word(e.get("disposition")) == "UNLINK":
            del out[ref]
    return out


REF_SEGMENT_KIND = {"fr": "requirement"}  # a requirement's ref is `sdlc:fr:<digits>` (ado_sync_sources_tree)


def _kind_of(ref: str) -> str | None:
    """The kind a `sdlc:<segment>:<id>` ref names: the segment, or the kind a differently spelled one stands for."""
    parts = ref.split(":")
    segment = parts[1] if len(parts) == 3 else ""
    return segment if segment in KINDS else REF_SEGMENT_KIND.get(segment)


def _link_row(ref: str, link: dict) -> dict:
    """A linking line as the `ledger_row` `classify_drift` reads: its kind comes from the ref when the line has none."""
    return {**link, "kind": link.get("kind") or _kind_of(ref)}


def _write_json(path: Path, doc: dict) -> None:
    """Sorted, indented JSON through a temporary file and a rename, so a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        scratch.write_text(json.dumps(doc, sort_keys=True, indent=1) + "\n", encoding="utf-8")
        os.replace(scratch, path)
    finally:
        scratch.unlink(missing_ok=True)


def _ensure_local_ignore(repo_root: Path) -> None:
    """`.sdlc/ado/local/` is ignored before anything lands in it (a clone that never ran `config init`)."""
    ignore = repo_root / LOCAL_DIR / ".gitignore"
    if not (ignore.exists() or ignore.is_symlink()):
        ignore.parent.mkdir(parents=True, exist_ok=True)
        ignore.write_bytes(b"*\n")


def _write_hook_line(repo_root: Path, ledger: list[dict]) -> tuple[str | None, str | None]:
    """Line 1 of `hook-status.txt` is the summary's `hook_line` (K11). `(line, problem)`: the file is a convenience
    for the session hook, so a summary that cannot be made or a file that cannot be written is a note, never the
    failure of a verb that has already written the ledger."""
    try:
        line = _summary(ledger)["hook_line"]
    except LedgerUnreadable as exc:
        return None, f"hook line: not written ({exc})"
    try:
        _ensure_local_ignore(repo_root)
        cfgmod.write_hook_status(repo_root, line)
    except OSError as exc:
        return line, f"hook line: not written to {bc.HOOK_STATUS} ({type(exc).__name__})"
    return line, None


# --- reading the repository's side and the board's -------------------------------------------------------------------

def _roster(repo_root: Path) -> dict:
    try:
        data = yaml.safe_load((repo_root / ".sdlc" / "team.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _emails(repo_root: Path) -> dict[str, str]:
    """`{lower-case address: @handle}`: the only way a board identity becomes a person here."""
    return validate_team.people_by_email(_roster(repo_root))


def _cfg_or_empty(repo_root: Path) -> dict:
    try:
        return cfgmod.load_config(repo_root)
    except cfgmod.ConfigError as exc:
        if exc.kind == "missing":
            return {}
        raise


def _load(repo_root: Path) -> tuple[dict, dict] | str:
    """`(cfg, schema)` or the sentence saying why there is nothing to read against: the read verbs go
    `unavailable` on these, they do not fail."""
    try:
        cfg = cfgmod.load_config(repo_root)
    except cfgmod.ConfigError as exc:
        if exc.kind == "missing":
            return f"not configured: {CONFIG_FILE} does not exist (run `ado_sync.py config init`)"
        return _tidy(exc)
    try:
        schema = ado_schema.load_schema(repo_root)
    except AdoImportError as exc:
        return _tidy(exc)
    if schema is None:
        return "no discovered schema: run `ado_sync.py discover` first, so there is a process to read against"
    return cfg, schema


def _scope_kinds(cfg: dict, wanted: list[str] | None) -> tuple[list[str], list[dict]]:
    """The kinds a verb covers (those asked for, else the configured ones) that have a source, and the rest
    named as skipped. An unknown kind never arrives: `--kind` is an argparse choice of `boards_contract.KINDS`."""
    asked = tuple(dict.fromkeys(wanted)) if wanted else _configured_kinds(cfg)
    have = [k for k in asked if k in sources.SOURCES]
    skipped = [{"kind": k, "reason": f"no source reads {k} yet (a later Fold adds it)"} for k in asked
               if k not in sources.SOURCES]
    return have, skipped


def _projections(repo_root: Path, cfg: dict, schema: dict, kinds: list[str]) -> list[dict]:
    """The repository's projections for `kinds`, each carrying the `sdlc-repo:<slug>` tag that says this
    repository owns the item. `AdoImportError` when the remote is not Azure DevOps; `ValueError` when an artifact
    contradicts itself."""
    slug = ado_transport.remote(repo_root).repo
    rows = sources.projections(repo_root, cfg, schema, kinds) if kinds else []
    for row in rows:
        row["tags"] = set(row["tags"]) | {f"{wm.REPO_TAG_PREFIX}{slug}"}
    return rows


def _read_items(repo_root: Path, ids: list[int], emails: dict[str, str]) -> tuple[dict[int, dict], list[int]]:
    """`(items by id, ids the board no longer has)` from one batch read per 200 ids. A row nobody asked for is
    ignored, never parsed."""
    wanted = list(dict.fromkeys(ids))
    if not wanted:
        return {}, []
    rows, _ = ado_wit.get_batch(repo_root, wanted)
    keep = set(wanted)
    items: dict[int, dict] = {}
    for raw in rows:
        if isinstance(raw, dict) and raw.get("id") in keep:
            item = wm.remote_item(raw, emails)
            items[item["id"]] = item
    return items, [i for i in wanted if i not in items]


FIND_CHUNK = 40  # refs per by-tag query: far under the length WIQL accepts


def _by_tag_wiql(refs: list[str], project: str | None = None) -> str:
    """One query for the work items tagged with any of `refs`, in `project` (the remote's project NAME, as a literal:
    `ado_wit_map.project_clause`). Never the current-project macro: `az boards query` answered a query using it with
    zero bytes on a board where items matched (B0, 2026-10-15). Every ref is checked against `REF_RE` first (it is
    `sdlc:` plus letters, digits and dashes, so it cannot end the string it sits in)."""
    for ref in refs:
        if not REF_RE.fullmatch(ref):
            raise ValueError(f"not a ref of the form sdlc:<kind>:<id>: {ref!r}")
    clauses = " OR ".join(f"[System.Tags] CONTAINS '{ref}'" for ref in refs)
    scope = wm.project_clause(project)
    return f"SELECT [System.Id] FROM WorkItems WHERE {f'{scope} AND ' if scope else ''}({clauses})"


def _query_tagged(repo_root: Path, refs: list[str]) -> list[int]:
    """The ids of the work items tagged with any of `refs`: one query per `FIND_CHUNK` refs, so a plan costs one query
    and one batch read however many items it covers, not one query each. No refs, no call."""
    ids: list[int] = []
    project = ado_transport.remote(repo_root).project if refs else None
    for start in range(0, len(refs), FIND_CHUNK):
        ids += ado_wit.query_ids(repo_root, _by_tag_wiql(refs[start:start + FIND_CHUNK], project))
    return list(dict.fromkeys(ids))


def _tag_map(items: dict[int, dict], refs: list[str]) -> dict[str, list[int]]:
    """`ref` -> the ids of the items whose tags name it exactly (a tag the query matched loosely is dropped here)."""
    found: dict[str, list[int]] = {ref: [] for ref in refs}
    for wid, item in sorted(items.items()):
        for tag in item["tags"]:
            if tag in found:
                found[tag].append(wid)
    return found


class _Outcome(NamedTuple):
    """What a read verb has to say, built and not yet printed: its `--json` document and its text. `sync` runs the
    read verbs' own code as its stages, so each says its answer as data and the caller decides how to print it."""
    doc: dict
    text: str


def _unavailable_outcome(repo_root: Path, verb: str, reason: str, *, host_error: str | None = None,
                         **extra) -> _Outcome:
    """A read that could not be made, as data: no rows, the reason in words (and the host block when `az` was the
    reason, read from the error it raised, never probed)."""
    host = host_block_for(repo_root, host_error) if host_error is not None else None
    lines = [f"Azure Boards mirror: {verb} - unavailable", f"  {reason}"]
    if host is not None:
        lines.append(_host_line(host))
    return _Outcome({"ok": True, "unavailable": True, "reason": reason, "host": host, **extra}, "\n".join(lines))


def _unavailable(args, repo_root: Path, verb: str, reason: str, *, host_error: str | None = None, **extra) -> int:
    """A read that could not be made: exit 0, no rows, the reason in words (and the host block when `az` was the
    reason, read from the error it raised, never probed)."""
    _emit(args, *_unavailable_outcome(repo_root, verb, reason, host_error=host_error, **extra))
    return 0


def _id_match(token: str, ref: str, ident: str | None = None, wid: int | None = None) -> bool:
    """Does an `--id` token name this item: its ref, its id as people write it, or (`#N`) its work item."""
    t = token.strip().lower()
    if t == ref.lower() or (ident is not None and t == str(ident).lower()):
        return True
    return wid is not None and bool(re.fullmatch(r"#[0-9]+", t)) and int(t[1:]) == wid


def _shown(value, emails: dict[str, str]):
    """A value for the screen or the plan file: an address becomes the roster handle (or a placeholder)."""
    if isinstance(value, str) and bc.EMAIL_RE.fullmatch(value.strip()):
        return emails.get(value.strip().lower()) or "(an identity that is not on the roster)"
    return value


# --- plan ------------------------------------------------------------------------------------------------------------

ACTION_ORDER = ("create", "update", "link", "ambiguous", "unmapped", "refused", "held")
PENDING_ACTIONS = ("create", "update")  # the rows `apply` would send; every other row needs a person first
PLACEHOLDER_HISTORY = f"{bc.HISTORY_TOKEN} · created"
NOT_WRITTEN_WORDS = ("effort fields", "read-only field")  # a ValueError that says "never written", not "fix it by hand"
SYSTEM_FILLED = "System."  # a required System.* field is the board's or the mirror's to fill, not a config gap
TAGS_PATH = "/fields/System.Tags"
DESCRIPTION_PATH = "/fields/System.Description"
FIELDS_PREFIX = "/fields/"


def _sprint_arg(text: str | None) -> str | None:
    if text is None:
        return None
    if not SPRINT_ID_RE.fullmatch(text.strip()):
        raise Usage(f"--sprint {text!r} is not a sprint id (S07, S12): the id of a file in .sdlc/sprints/")
    return text.strip()


def _in_sprint(repo_root: Path, proj: dict, sprint: str) -> bool:
    """The sprint's own item, or a spec whose frontmatter names the sprint."""
    if proj["ref"] == f"sdlc:sprint:{sprint}":
        return True
    if proj["kind"] != "spec":
        return False
    try:
        text = (repo_root / proj["source_path"]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return str(parse_frontmatter(text)[0].get("sprint") or "").strip() == sprint


def _select(repo_root: Path, projs: list[dict], ids: list[str], sprint: str | None) -> tuple[list[dict], list[str]]:
    """The projections an `--id`/`--sprint` selection names (both given: both must hold), and the `--id` tokens that
    named nothing."""
    chosen = []
    for p in projs:
        if ids and not any(_id_match(t, p["ref"], p["id"]) for t in ids):
            continue
        if sprint and not _in_sprint(repo_root, p, sprint):
            continue
        chosen.append(p)
    unmatched = [t for t in ids if not any(_id_match(t, p["ref"], p["id"]) for p in projs)]
    return chosen, unmatched


def _refusal(proj: dict, schema: dict) -> str | None:
    """The sentence for a projection that carries an effort field (the mirror never writes one), else None."""
    refused = {r.lower() for r in sm.refused_fields(schema)}
    for ref in proj["fields"]:
        if ref.lower() in refused or ref.lower().startswith("microsoft.vsts.scheduling."):
            return (f"{ref} is in the projection: effort fields (points, estimates, hours) are never written "
                    "(a forbidden metric; exit 2 at apply)")
    return None


def _split_tags(value) -> list[str]:
    return [t.strip() for t in str(value or "").split(";") if t.strip()]


def _tags_op(op: str, have: set, want: set) -> dict:
    kept = sum(1 for t in have if not t.startswith(bc.PLUGIN_TAG_PREFIXES))
    return {"op": op, "path": TAGS_PATH, "add": sorted(want - have), "remove": sorted(have - want), "kept": kept}


def _update_ops(patch: list[dict], remote: dict, projection: dict, emails: dict[str, str]) -> list[dict]:
    """The ops of `wm.build_update_patch` (less its `test /rev` guard) as the screen shows them: `old` from the model's
    diff, a tag change as an add/remove list, a description as the block it replaces."""
    by_path = {o["path"]: o for o in model.diff(projection, remote, model.ownership_for(projection.get("kind")))}
    ops = []
    for op in patch[1:]:
        path = op["path"]
        if path == TAGS_PATH:
            ops.append(_tags_op(op["op"], set(remote.get("tags") or ()), set(_split_tags(op["value"]))))
        elif path == DESCRIPTION_PATH:
            ops.append({"op": op["op"], "path": path, "old": "(the block between the sdlc markers)",
                        "new": "(the block from the repository)"})
        else:
            ops.append({"op": op["op"], "path": path, "old": _shown(by_path.get(path, {}).get("old"), emails),
                        "new": _shown(op["value"], emails)})
    return ops


def _create_ops(projection: dict, emails: dict[str, str]) -> list[dict]:
    """What a create sets: the model's `diff(projection, None)`, the tags as an add list, an identity as a handle."""
    ops = []
    for op in model.diff(projection, None):
        if op["path"] == TAGS_PATH:
            ops.append(_tags_op("add", set(), set(_split_tags(op["new"]))))
        else:
            ops.append({"op": "add", "path": op["path"], "old": None, "new": _shown(op["new"], emails)})
    return ops


def _required_notes(schema: dict, type_name: str, proj: dict) -> list[str]:
    """A field the type always requires that the create would leave empty: it would fail on the board. A field the
    projection sets -- from the repository or a `fields.<kind>` constant -- or the process defaults is not one. When the
    type's fields were never read, whether the process defaults it is not known, and the note says that instead of
    claiming the create would fail (`discover` reads every type a kind lands on)."""
    info = (schema.get("types") or {}).get(type_name) or {}
    read = isinstance(info.get("fields"), dict)
    notes = []
    for ref in info.get("required_fields") or []:
        if ref.startswith(SYSTEM_FILLED) or ref in proj["fields"]:
            continue
        if not read:
            notes.append(f"required field {ref}: {type_name}'s fields were not read, so whether the process gives it "
                         "a default is not known; `ado_sync.py discover --refresh` reads them")
            continue
        facts = sm.field_on_type(schema, type_name, ref)
        if facts is not None and facts.get("default") is not None:
            continue
        notes.append(f"required field {ref} has no value -> create would fail; add it under fields.{proj['kind']} "
                     "(a constant `{field, value}` when no artifact carries it) or give it a process default")
    return notes


def _validation(schema: dict, type_name: str, ops: list[dict], creating: bool) -> list[str]:
    """`plan --validate`: each op checked against the discovered process, locally (the board is not asked). A
    transition the type does not allow, a field the type does not carry, a value outside a picklist."""
    info = (schema.get("types") or {}).get(type_name) or {}
    read_fields = bool(info.get("fields"))
    found = []
    for op in ops:
        if not op["path"].startswith(FIELDS_PREFIX) or op["path"] == TAGS_PATH:
            continue
        ref = op["path"][len(FIELDS_PREFIX):]
        facts = sm.field_on_type(schema, type_name, ref)
        if facts is None:
            if read_fields:
                found.append(f"{ref} is not a field of {type_name} on this process")
            continue
        new = op.get("new")
        allowed = facts.get("allowed_values")
        # as text: an integer field's allowed values are answered "1", "2", ... (the captured Priority), its value 1
        if isinstance(allowed, list) and new is not None and str(new) not in {str(a) for a in allowed}:
            found.append(f"{ref}: {new!r} is not one of the allowed values ({', '.join(str(a) for a in allowed)})")
        if ref == "System.State" and isinstance(new, str):
            frm = "" if creating else str(op.get("old") or "")
            if sm.transition_allowed(schema, type_name, frm, new) is False:
                found.append(f"{type_name} does not allow {frm or 'creation'} -> {new}")
    return found


def _row(p: dict, action: str, type_name, *, reason=None, work_item=None, rev=None, ops=None, notes=None) -> dict:
    notes = list(notes or []) + list(p.get("notes") or [])
    return {"ref": p["ref"], "kind": p["kind"], "id": p["id"], "action": action, "reason": reason,
            "work_item": work_item, "rev": rev, "type": type_name, "ops": list(ops or []), "notes": notes,
            "parent": None, "related_refs": sorted(p.get("related_refs") or []),
            "source_path": p["source_path"], "source_sha": p["source_sha"], "projection_hash": model.projection_hash(p)}


def _row_type(p: dict, schema: dict, cfg: dict, typed: dict | None = None) -> tuple[str | None, str]:
    """`(type_name, reason)` a projection lands as: the type its source chose for this one row when the source names
    one -- the finding source sets `type_name` and `type_route` together (CRITICAL and HIGH on the process's
    `BugCategory` default type, the rest on `types.finding`, each validated against the discovered schema) -- else
    the kind's own resolution (`ado_schema_map.resolve_type`). `typed` is that resolution, cached per kind."""
    fields = p.get("fields") if isinstance(p.get("fields"), dict) else {}
    chosen, route = fields.get("type_name"), fields.get("type_route")
    if isinstance(chosen, str) and chosen and isinstance(route, str) and route:
        return chosen, f"chosen by the {p['kind']} source: {route}"
    if typed is not None and p["kind"] in typed:
        return typed[p["kind"]]
    return sm.resolve_type(schema, p["kind"], cfg)


def _unwritable(exc: ValueError) -> str:
    """`refused` for a field the mirror never writes, `held` for anything a person must fix by hand first."""
    return "refused" if any(w in str(exc) for w in NOT_WRITTEN_WORDS) else "held"


class _Board(NamedTuple):
    """What the ledger and the board said about the items a plan covers."""
    links: dict       # ref -> last linking line
    found: dict       # ref -> ids a by-tag query found (refs the ledger did not know)
    items: dict       # work item id -> remote_item
    missing: set      # ledgered ids the board no longer has
    emails: dict      # lower-case address -> @handle
    web_url: str      # the repository's web address: what a create's hyperlink is validated with
    area_path: str | None = None   # `wm.configured_area(cfg)`: every create sets it (B0 write fixes, 2026-10-15)


def _plan_row(p: dict, type_name, why: str, schema: dict, cfg_refusal: str | None, board: _Board) -> dict:
    """One projection against what the ledger and the board say. The model and the patch builders decide every
    op (`diff`, `build_update_patch`, `build_create_patch`), so what a plan shows is what an apply would send."""
    if cfg_refusal:
        return _row(p, "refused", type_name, reason=cfg_refusal)
    if type_name is None:
        return _row(p, "unmapped", None, reason=why)
    refusal = _refusal(p, schema)
    if refusal:
        return _row(p, "refused", type_name, reason=refusal)
    link = board.links.get(p["ref"])
    if link is not None:
        wid = link["work_item"]
        if wid in board.missing:
            return _row(p, "held", type_name, work_item=wid, reason=f"#{wid} is gone from the board (deleted, or not "
                        "visible to this az login); the mirror does not recreate it unasked")
        remote = board.items[wid]
        if remote["type"] != type_name:
            return _row(p, "held", type_name, work_item=wid, rev=remote["rev"],
                        reason=f"#{wid} is a {remote['type']} on the board but {p['kind']} maps to {type_name}")
        try:
            patch = wm.build_update_patch(remote, p)
        except ValueError as exc:
            return _row(p, _unwritable(exc), type_name, work_item=wid, rev=remote["rev"], reason=_tidy(exc))
        ops = _update_ops(patch, remote, p, board.emails) if wm.has_changes(patch) else []
        return _row(p, "update" if ops else "in_sync", type_name, work_item=wid, rev=remote["rev"], ops=ops)
    ids = board.found.get(p["ref"], [])
    if len(ids) > 1:
        return _row(p, "ambiguous", type_name, reason="tagged on " + ", ".join(f"#{i}" for i in ids)
                    + "; map the right one with `link <ref> --work-item N --by <you>`")
    if len(ids) == 1:
        kind_of_item = (board.items.get(ids[0]) or {}).get("type")
        return _row(p, "link", type_name, work_item=ids[0],
                    reason=f"#{ids[0]}{f' ({kind_of_item})' if kind_of_item else ''} is tagged {p['ref']} but is not in "
                    f"this clone's ledger; `ado_sync.py link {p['ref']} --work-item {ids[0]} --by <you>` maps it")
    try:
        wm.build_create_patch(p, schema, board.web_url, PLACEHOLDER_HISTORY, None,   # validated, then thrown away
                              area_path=board.area_path)
        shown = wm.with_create_fields(p, board.area_path)   # the area a create sets is shown, as it is sent
    except ValueError as exc:
        return _row(p, _unwritable(exc), type_name, reason=_tidy(exc))
    return _row(p, "create", type_name, ops=_create_ops(shown, board.emails),
                notes=_required_notes(schema, type_name, p))


def _kind_order(kind: str) -> int:
    return TREE_ORDER.index(kind) if kind in TREE_ORDER else len(TREE_ORDER) + KINDS.index(kind)


def _val(value) -> str:
    return "(none)" if value is None else str(value)


def _op_line(op: dict, width: int) -> str:
    label = op["path"][len(FIELDS_PREFIX):] if op["path"].startswith(FIELDS_PREFIX) else op["path"]
    if "add" in op:
        change = "  ".join([*(f"+ {t}" for t in op["add"]), *(f"- {t}" for t in op["remove"])]) or "(no change)"
        kept = f"   ({_plural(op['kept'], 'human tag')} kept)" if op["op"] != "add" else ""
        return f"  {label.ljust(width)}{change}{kept}"
    return f"  {label.ljust(width)}{_val(op['old'])} -> {_val(op['new'])}"


def _row_head(r: dict) -> str:
    head = f"{r['kind']} {r['id']}  {r['action']}"
    if r["action"] == "update":
        return f"{head}  #{r['work_item']} rev {r['rev']}"
    if r["action"] == "create":
        return f'{head}  type "{r["type"]}"'
    return f"{head}  {r['reason']}"


COMMENT_ACTION = "comment"  # the `action` of a comment row (`ado_sync_comments.ROW_KEYS`)


def _who(row: dict) -> str:
    """How a comment row names its item: `spec 0004` from the ref, else the `#id` it was addressed to."""
    ref = row.get("ref")
    parts = ref.split(":") if isinstance(ref, str) else []
    return f"{parts[1]} {parts[2]}" if len(parts) == 3 else str(row.get("target") or "work item")


def _comment_lines(row: dict, plan: str) -> list[str]:
    """A comment row as the plan shows it: its key, the exact text the board will carry (the trailer with this plan's
    hash included), every line quoted `  | ` so it can never be read as the plan's own words, and what is only text."""
    who = _who(row)
    if row["status"] == "refused":
        return [f"{who}  comment  refused  {row['reason']}: {row['detail']}  (an apply of this plan is refused whole)"]
    head = f"{who}  comment  #{row['work_item']}  event {row['event'] or 'ad hoc'}  (key {row['idem_key']})"
    facts = f"  format {row['format']} · {row['chars']} chars · trailer {row['trailer']}"
    text = model.with_trailer(row["text"], plan, row["trailer"])
    return [head, facts, *[f"  | {line}" for line in text.split("\n")], *[f"  {n}" for n in row["notes"]]]


def _comments_line(comments: dict, skipped: list[dict]) -> str | None:
    """The one line that counts what the drafter found (None when it found nothing or was told not to look)."""
    if not comments["planned"] or comments["unavailable"] or not (comments["draft"] or comments["skipped"]
                                                                  or comments["refused"]):
        return None
    why: dict[str, int] = {}
    for row in skipped:
        why[row["reason"]] = why.get(row["reason"], 0) + 1
    by_reason = f" ({', '.join(f'{k} {v}' for k, v in sorted(why.items()))})" if why else ""
    line = f"comments: {comments['draft']} to send, {comments['skipped']} skipped{by_reason}, {comments['refused']} refused"
    if comments["refused"]:
        line += "  (an apply of a plan holding a refused comment is refused whole; `plan --no-comments` splits them off)"
    return line


def _draft_comments(repo_root: Path, cfg: dict, ledger: list[dict], links: dict[str, dict],
                    selected: set[str] | None) -> tuple[list[dict], list[dict], str | None]:
    """`(rows, skipped, why not)`: the comment rows `ado_sync_comments` drafts from the repository's own ledgers.
    `rows` are the drafts (what an apply would send) and the refusals (an apply refuses a plan that holds one, so the
    person sees them first); `skipped` rows are listed and counted, never planned (they have nothing to send). `selected`
    is the refs the plan's selector named (None: no selector, every row). A drafter that cannot read the repository
    leaves the plan with no comments and says why: a plan never fails for them."""
    idmap = {ref: link["work_item"] for ref, link in links.items()}
    try:
        drafted = comments_mod.draft_event_rows(repo_root, cfg, ledger, idmap)
    except (ValueError, OSError, KeyError, TypeError, AttributeError, yaml.YAMLError) as exc:
        return [], [], f"comments not planned: {_tidy(exc, 160)}"
    if selected is not None:
        drafted = [r for r in drafted if r["ref"] in selected]
    return ([r for r in drafted if r["status"] != "skipped"], [r for r in drafted if r["status"] == "skipped"], None)


def _plan_text(out: dict, in_sync: int, fit_lines: list[str]) -> str:
    schema = out["schema"]
    age = schema["age_days"]
    old = "age unknown" if age is None else f"{_plural(age, 'day')} old"
    who = out["executed_as_word"]
    lines = [f"plan {out['plan']}  (schema {str(schema['discovered_at'])[:10]}, {old}; posture {out['posture']}; "
             f"az executed as {who})"]
    width = max([len(o["path"]) - len(FIELDS_PREFIX) for r in out["rows"] if r["action"] != COMMENT_ACTION
                 for o in r["ops"] if o["path"].startswith(FIELDS_PREFIX)] + [10]) + 2
    for r in out["rows"]:
        if r["action"] == COMMENT_ACTION:
            lines += _comment_lines(r, out["plan"])
            continue
        lines.append(_row_head(r))
        lines += [_op_line(o, width) for o in r["ops"]]
        parent = r["parent"]
        if parent is not None and r["action"] == "create":
            if parent["state"].startswith("rides as "):
                target = parent["state"]           # on the item's own tags, never a work item
            else:
                target = f"#{parent['work_item']}" if parent["work_item"] else f"no work item yet ({parent['state']})"
            lines.append(f"  parent {parent['ref']} -> {target}")
        lines += [f"  note: {n}" for n in r["notes"]]
        lines += [f"  validate: {v}" for v in r.get("validation", [])]
    if not out["rows"]:
        lines.append("nothing to push: no row is waiting on the board")
    if in_sync:
        lines.append(f"in sync: {_plural(in_sync, 'item')}")
    summary = _comments_line(out["comments"], out["comments_skipped"])
    if summary:
        lines.append(summary)
    for s in out["skipped"]:
        lines.append(f"skipped {s['kind']}: {s['reason']}")
    if out["unmatched_ids"]:
        lines.append("no item matches --id " + ", ".join(out["unmatched_ids"]))
    if fit_lines:
        lines += ["", "How each kind lands on this process", *fit_lines, ""]
    c = out["cost"]
    drafts = out["comments"]["draft"] or 0
    sending = f", {_plural(drafts, 'comment')}" if drafts else ""
    lines.append(f"cost: {_plural(c['writes'], 'write')}, {_plural(c['creates'], 'create')}, "
                 f"{_plural(c['links'], 'link')}{sending}  (az spawns on apply: {c['az_spawns']})")
    lines += [f"note: {n}" for n in out["notes"]]
    if out["validated"]:
        lines.append("validated locally against the discovered process; the board was not asked")
    lines.append(f"Plan file: {out['path']}")
    return "\n".join(lines)


def _plan_notes(cfg: dict, ledger: list[dict], scope_all: bool, counts: dict, comments: int = 0) -> list[str]:
    limits = cfg.get("limits") if isinstance(cfg.get("limits"), dict) else {}
    first_seed, per_run = limits.get("first_seed"), limits.get("writes_per_run")
    notes = []
    # a seed is the first only until an item was created or updated here: an `applied` line of another action (`link-pr`
    # writes one, and creates nothing) leaves the guard in place -- the rule `ado_sync_apply._first_seed_refusal` applies
    never_applied = not any(e.get("event") == "applied" and e.get("action") in apply_mod.FIELD_ACTIONS for e in ledger)
    if scope_all and never_applied and _is_id(first_seed) and counts["create"] > first_seed:
        notes.append(f"first seed: {_plural(counts['create'], 'create')} is over limits.first_seed ({first_seed}); "
                     "an apply of this plan will need --limit")
    pending = counts["create"] + counts["update"] + comments   # a comment is a write too (field ops go first)
    if _is_id(per_run) and pending > per_run:
        notes.append(f"{_plural(pending, 'row')} is over limits.writes_per_run ({per_run}); an apply stops at "
                     f"{per_run}, and the next plan covers the rest")
    return notes


def _edge_state(ref: str, fits: dict, links: dict, creating: set) -> str:
    """Where a parent or Related ref stands: `rides as tag domain:order-intake` when its tree kind rides as a tag on
    this process (it is on the item's own tags, never a work item), else `linked` (the ledger maps it), `in this plan`
    (a create of this plan), or `not planned`. `apply` links a parent only when it is `linked` or `in this plan`."""
    tag = sources.ride_tag(ref, fits)
    if tag is not None:
        return f"rides as tag {tag}"
    return "linked" if ref in links else "in this plan" if ref in creating else "not planned"


def _open_conflicts(ledger: list[dict]) -> dict[str, list[dict]]:
    """`ref` -> the CONFLICT and RETYPED rows a pull recorded that nothing has cleared: judged exactly as
    `ado_sync_model.summarize` judges them (a later `applied` naming the field, or a later `reconciled` that puts the
    row legitimately off the books). A plan notes them: its update would overwrite what the board changed."""
    latest: dict[tuple, tuple[int, dict]] = {}
    for i, e in enumerate(ledger):
        if e.get("event") == "drift_seen" and e.get("ref"):
            latest[(e["ref"], e.get("field"))] = (i, e)
    out: dict[str, list[dict]] = {}
    for (ref, field), (i, row) in latest.items():
        if row.get("class") not in ("CONFLICT", "RETYPED"):
            continue
        merged, cleared = dict(row), False
        for later in ledger[i + 1:]:
            if later.get("ref") != ref:
                continue
            if later.get("event") == "applied" and field in (later.get("fields") or []):
                cleared = True
            elif later.get("event") == "reconciled" and later.get("field") in (field, None):
                merged.update({k: v for k, v in later.items() if k not in ("ts", "event", "class")})
                cleared = cleared or not model.counts_as_open(merged)
        if not cleared and model.counts_as_open(merged):
            out.setdefault(ref, []).append(row)
    return out


def _apply_offer(posture: str, counts: dict, comments: dict, plan: str) -> tuple[bool, str | None]:
    """`(apply_offered, next)`: an apply is offered where the posture is `assisted`, and the one footer
    (`ado_sync_model.apply_next_line`) is named only when the plan holds something to send: a create, an update or a
    drafted comment. A plan-only clone is offered nothing and prints no footer; a plan with nothing to send names none."""
    offered = posture == "assisted"
    pending = counts["create"] + counts["update"] + (comments.get("draft") or 0)
    return offered, (model.apply_next_line(plan) if offered and pending > 0 else None)


def cmd_plan(args, repo_root: Path) -> int:
    doc, text, code = _plan_outcome(args, repo_root)
    if doc.get("next"):  # the footer is the LAST line, under a DRIFT line when there is one; an unavailable plan has none
        text = f"{text}\n{doc['next']}"
    _emit(args, doc, text)
    return code


def _plan_outcome(args, repo_root: Path) -> tuple[dict, str, int]:
    """`(document, text, exit)` of `plan`, built and not printed (`sync` runs it as its last stage). The text is
    empty under `--json`, where it is never read; it carries no footer: `cmd_plan` adds the one `next` names."""
    need = _load(repo_root)
    if isinstance(need, str):
        return (*_unavailable_outcome(repo_root, "plan", need, plan=None, rows=[], counts=None), 0)
    cfg, schema = need
    kinds, skipped = _scope_kinds(cfg, args.kind)
    sprint = _sprint_arg(args.sprint)
    ids = [t.strip() for t in args.id or [] if t.strip()]
    scope = {"kinds": list(args.kind or []), "ids": ids, "sprint": sprint,
             "all": bool(args.all or not (args.kind or ids or sprint))}
    fit, resolved, _gaps, _recommendations = _fit_view(schema, cfg, tuple(kinds))
    rides = [k for k, v in fit.items() if v["mode"] != "item"]  # a requirement or domain that rides as a tag or an area
    skipped += [{"kind": k, "reason": fit[k]["reason"]} for k in rides]
    refusals = [r["message"] for r in cfgmod.validate_config(cfg, _with_refusals(schema)) if r["level"] == "refused"]
    emails = _emails(repo_root)
    try:
        projs = _projections(repo_root, cfg, schema, [k for k in kinds if k not in rides])
        web_url = ado_transport.remote(repo_root).web_url
    except AdoImportError as exc:
        return (*_unavailable_outcome(repo_root, "plan", _tidy(exc), host_error=str(exc), plan=None, rows=[],
                                      counts=None), 0)
    except ValueError as exc:
        return (*_unavailable_outcome(repo_root, "plan", f"the repository's sources do not agree: {_tidy(exc)}",
                                      plan=None, rows=[], counts=None), 0)
    selected, unmatched = _select(repo_root, projs, ids, sprint)
    ledger = read_ledger(repo_root)
    links = linked_items(ledger)
    typed = {kind: sm.resolve_type(schema, kind, cfg) for kind in dict.fromkeys(p["kind"] for p in selected)}
    live = [p for p in selected
            if not refusals and _row_type(p, schema, cfg, typed)[0] is not None and _refusal(p, schema) is None]
    unledgered = [p["ref"] for p in live if p["ref"] not in links]
    ledgered_ids = [links[p["ref"]]["work_item"] for p in live if p["ref"] in links]
    try:  # one by-tag query for every ref the ledger does not know, then one batch read of everything it names
        items, missing = _read_items(repo_root, ledgered_ids + _query_tagged(repo_root, unledgered), emails)
    except AdoImportError as exc:
        return (*_unavailable_outcome(repo_root, "plan", _tidy(exc), host_error=str(exc), plan=None, rows=[],
                                      counts=None), 0)
    board = _Board(links, _tag_map(items, unledgered), items, set(missing) & set(ledgered_ids), emails, web_url,
                   wm.configured_area(cfg))
    pairs = [(p, _plan_row(p, *_row_type(p, schema, cfg, typed), schema, refusals[0] if refusals else None, board))
             for p in selected]
    in_sync = sum(1 for _, r in pairs if r["action"] == "in_sync")
    pairs = sorted(((p, r) for p, r in pairs if r["action"] != "in_sync"), key=lambda pr: _kind_order(pr[1]["kind"]))
    creating = {r["ref"] for _, r in pairs if r["action"] == "create"}
    conflicts = _open_conflicts(ledger)
    fits = sources.ride_fit(cfg, schema)   # the tree kinds that ride as tags: their refs are never a work item
    for p, r in pairs:
        if r["action"] == "update":
            r["notes"] += [f"open {c['class']} on {c.get('field') or 'the item'} since {c.get('ts')}: the board and the "
                           "repository both changed it, and this update would overwrite the board's value"
                           for c in conflicts.get(r["ref"], [])]
        parent = p.get("parent_ref")
        if parent:
            r["parent"] = {"ref": parent, "work_item": links[parent]["work_item"] if parent in links else None,
                           "state": _edge_state(parent, fits, links, creating)}
        elif p.get("parent_note"):
            r["notes"].append(p["parent_note"])
        if r["related_refs"]:  # a row with no Related edge has no key, so its plan hash is what it always was
            # a Related edge is only ever a tag today: apply sends no Related link, so an item-mode ref is "not planned"
            r["related"] = [{"ref": ref, "state": _edge_state(ref, fits, {}, set())} for ref in r["related_refs"]]
        if args.validate and r["action"] in PENDING_ACTIONS:
            r["validation"] = _validation(schema, r["type"], r["ops"], r["action"] == "create")
    narrowed = bool(args.kind or ids or sprint)  # a selector: a comment row is in scope only for the items it chose
    comment_rows, comment_skipped, comment_why = ([], [], None) if args.no_comments else _draft_comments(
        repo_root, cfg, ledger, links, {p["ref"] for p in selected} if narrowed else None)
    rows = [r for _, r in pairs] + comment_rows        # field ops first, then the comments (the order apply sends them in)
    counts = {a: sum(1 for r in rows if r["action"] == a) for a in ACTION_ORDER}   # field ops only: "comment" is not one
    counts["in_sync"] = in_sync
    drafts = sum(1 for r in comment_rows if r["status"] == "draft")
    cost = {"writes": counts["update"], "creates": counts["create"], "links": 0,
            "az_spawns": counts["update"] + counts["create"] + (1 + drafts if drafts else 0)}   # + connectionData, one POST each
    plan = model.plan_hash(rows)
    stamp = _stamp()
    posture = cfg.get("posture") if cfg.get("posture") in ("plan-only", "assisted") else "plan-only"
    path = f"{LOCAL_DIR}/plans/{plan}.json"
    # the lines are built first: one the model refuses stops the plan before the plan file is written
    events = [_event(stamp, "planned", plan=plan, ref=r["ref"], kind=r["kind"], action=r["action"],
                     work_item=r["work_item"]) for r in rows if r["action"] in PENDING_ACTIONS]   # never a comment row
    if not events:  # "a plan that found nothing" is a line with no ref, so `pending` reads 0, not no data
        events = [_event(stamp, "planned", plan=plan, ref=None)]
    try:
        _ensure_local_ignore(repo_root)
        _write_json(repo_root / path, {"schema": PLAN_SCHEMA, "plan": plan, "created": stamp, "scope": scope,
                                       "posture": posture, "rows": rows})
    except OSError as exc:  # -> main: `unavailable`, exit 0; nothing was ledgered
        raise Illegal(f"could not write the plan file {path} ({type(exc).__name__}); nothing was ledgered") from None
    drift = None
    if next((e.get("plan") for e in reversed(ledger) if e.get("event") == "planned"), None) != plan:
        try:
            append_ledger(repo_root, events)
            ledger = ledger + events
        except LedgerDrift as exc:  # printed, never a failure: plan exits 0 on every path that is not a usage error
            drift = str(exc)
    hook, hook_note = _write_hook_line(repo_root, ledger)
    me = cache.load_me(repo_root)
    executed_as = me.get("handle") if me else None
    word = executed_as or ("an identity that is not on the roster" if me else "not read yet")
    planned_comments = not args.no_comments and comment_why is None
    comments = {"planned": not args.no_comments,
                "draft": drafts if planned_comments else None,
                "skipped": len(comment_skipped) if planned_comments else None,
                "refused": sum(1 for r in comment_rows if r["status"] == "refused") if planned_comments else None,
                "unavailable": comment_why}
    offered, next_line = _apply_offer(posture, counts, comments, plan)
    out = {"ok": True, "unavailable": False, "reason": None, "plan": plan, "path": path, "scope": scope,
           "schema": _schema_facts(schema), "posture": posture, "executed_as": executed_as, "rows": rows,
           "counts": counts, "fit": fit, "skipped": skipped, "unmatched_ids": unmatched, "cost": cost,
           "notes": _plan_notes(cfg, ledger, scope["all"], counts, drafts)
           + ([comment_why] if comment_why else []) + ([hook_note] if hook_note else []),
           "validated": bool(args.validate), "comments": comments,
           "comments_skipped": [{k: r[k] for k in ("ref", "event", "reason", "detail")} for r in comment_skipped],
           "hook_line": hook, "drift": drift, "apply_offered": offered, "next": next_line}
    if args.json:
        return out, "", 0
    lines = _fit_table(fit, resolved) if fit or resolved else []
    text = _plan_text({**out, "executed_as_word": word}, in_sync, lines).rstrip("\n")
    return out, (text if drift is None else f"{text}\n{drift}"), 0  # `DRIFT: ...` leads its line, as in sprint.py


# --- status ----------------------------------------------------------------------------------------------------------

def _n(value) -> str:
    return "no data" if value is None else str(value)


def _status_text(doc: dict, configured: bool) -> str:
    c = doc["counts"]
    lines = ["Azure Boards mirror: status",
             f"config: {CONFIG_FILE}" if configured else "not configured (run `ado_sync.py config init`)",
             f"summary: {doc['hook_line']}",
             f"  linked    {_n(c['linked'])}",
             f"  pending   {_n(c['pending'])}",
             f"  drifted   {_n(c['drifted'])}",
             f"  conflicts {_n(c['conflicts'])}",
             f"  debt      {_n(c['debt'])}",
             f"as of: {doc['as_of'] or 'never pulled'}"]
    if doc["last_plan"] is not None:
        p = doc["last_plan"]
        lines.append(f"last plan: {p['plan']} at {p['ts']} ({_plural(p['rows'], 'row')})")
    if doc["by_class"]:
        lines.append("open drift: " + ", ".join(f"{k} {v}" for k, v in doc["by_class"].items()))
    for item in doc["debt"] or []:
        lines.append(f"  debt: {item['ref']} {item['field'] or '(whole item)'} {item['class']} seen {item['seen']}, "
                     f"due {item['due']}")
    lines += [f"note: {n}" for n in doc["notes"]]
    return "\n".join(lines)


def cmd_status(args, repo_root: Path) -> int:
    doc = _summary(read_ledger(repo_root))  # LedgerUnreadable -> main: `unavailable: <reason>`, exit 0
    if args.json:
        print(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False))  # the golden's form, byte for byte
    else:
        print(_status_text(doc, (repo_root / CONFIG_FILE).is_file()))
    return 0


# --- pull and drift --------------------------------------------------------------------------------------------------

def _ident(ref: str, proj: dict | None) -> str:
    return proj["id"] if proj else ref.split(":", 2)[2]


def _select_links(links: dict[str, dict], projs: dict[str, dict], ids: list[str],
                  kinds: list[str] | None) -> tuple[list[str], list[str]]:
    """The ledgered refs an `--id` (ref, id, or `#work item`) and `--kind` selection names, in ref order, and the ids
    that named none. `--kind` is an argparse choice of `boards_contract.KINDS`, so no unknown kind arrives here."""
    chosen = []
    for ref, link in sorted(links.items()):
        if kinds and _kind_of(ref) not in kinds:
            continue
        if ids and not any(_id_match(t, ref, _ident(ref, projs.get(ref)), link["work_item"]) for t in ids):
            continue
        chosen.append(ref)
    unmatched = [t for t in ids if not any(_id_match(t, ref, _ident(ref, projs.get(ref)), l["work_item"])
                                           for ref, l in links.items())]
    return chosen, unmatched


def _observe(repo_root: Path, links: dict, refs: list[str], projs: dict, emails: dict,
             remotes: dict | None = None) -> list[dict]:
    """Read the board for the ledgered `refs` (one batch read, then `wit/updates` only for an item whose revision moved
    past the ledger's `rev_after`) and classify each with `ado_sync_model.classify_drift`. An item that cannot be
    classified is a row with `unavailable` set, never a guessed class. An `AdoImportError` from the batch read
    propagates: nothing was read. A caller that passes `remotes` gets the items it read, by work item id, filled in
    (`pull` says what a person may do about a row from the item's current assignee and iteration; no second read)."""
    items, missing = _read_items(repo_root, [links[r]["work_item"] for r in refs], emails)
    if remotes is not None:
        remotes.update(items)
    gone = set(missing)
    results = []
    for ref in refs:
        link, proj = links[ref], projs.get(ref)
        wid = link["work_item"]
        remote = items.get(wid)
        row = {"ref": ref, "kind": _link_row(ref, link)["kind"], "work_item": wid, "rev": remote["rev"] if remote else None,
               "class": None, "fields": [], "attachments": [], "ignored": [], "unavailable": None}
        results.append(row)
        rev_after = link.get("rev_after")
        if wid not in gone and proj is not None and not _is_id(rev_after):
            row["unavailable"] = "the ledger line that linked it has no rev_after; link it again to set the baseline"
            continue
        updates = []
        if remote is not None and proj is not None and remote["rev"] > rev_after:
            try:
                updates = ado_wit.updates_since(repo_root, wid, rev_after)
            except AdoImportError as exc:
                row["unavailable"] = _tidy(exc)
                continue
        try:
            row.update(model.classify_drift(_link_row(ref, link), remote, proj, updates))
        except ValueError as exc:
            row["unavailable"] = _tidy(exc)
        # an attachment is listed by name and revision; its address carries a GUID the output has no use for
        row["attachments"] = [{"name": a.get("name"), "rev": a.get("rev")} for a in row["attachments"]]
    return results


def _drift_context(repo_root: Path, verb: str):
    """`(cfg, schema, projections by ref, links, emails, ledger)` or the `_Outcome` of an `unavailable` answer."""
    need = _load(repo_root)
    if isinstance(need, str):
        return _unavailable_outcome(repo_root, verb, need, items=[], counts=None)
    cfg, schema = need
    ledger = read_ledger(repo_root)
    links = linked_items(ledger)
    kinds = sorted({_link_row(ref, link)["kind"] for ref, link in links.items()} & set(sources.SOURCES))
    try:
        projs = {p["ref"]: p for p in _projections(repo_root, cfg, schema, kinds)}
    except AdoImportError as exc:
        return _unavailable_outcome(repo_root, verb, _tidy(exc), host_error=str(exc), items=[], counts=None)
    except ValueError as exc:
        return _unavailable_outcome(repo_root, verb, f"the repository's sources do not agree: {_tidy(exc)}",
                                    items=[], counts=None)
    return cfg, schema, projs, links, _emails(repo_root), ledger


def _unmapped(repo_root: Path, cfg: dict) -> tuple[list[int] | None, str | None]:
    """The work items under the mirror's area and iteration paths that this repository has not tagged
    (`UNMAPPED_IN_ADO`: candidates for `link` and `adopt`), as ids — with a note when `az boards query` printed nothing
    (read as none found) — or None and why they were not searched."""
    areas = [cfg["area_path"]] if isinstance(cfg.get("area_path"), str) and cfg["area_path"].strip() else []
    iterations = cfg.get("iterations") if isinstance(cfg.get("iterations"), dict) else {}
    paths = [v for v in iterations.values() if isinstance(v, str) and v.strip()]
    if not areas and not paths:
        return None, "not searched: no area_path or iterations in the config to look under"
    try:
        here = ado_transport.remote(repo_root)
        ids = ado_wit.query_ids(repo_root, wm.wiql_untagged(areas, paths, here.repo, here.project))
    except (AdoImportError, ValueError) as exc:
        return None, f"not searched: {_tidy(exc)}"
    # zero bytes is no rows, said in words (it is also what a query the board cannot scope prints, B0 2026-10-15)
    return ids, (ado_wit.QUERY_PRINTED_NOTHING if getattr(ids, "printed_nothing", False) else None)


def _class_counts(results: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in results:
        if r["class"]:
            counts[r["class"]] = counts.get(r["class"], 0) + 1
    return dict(sorted(counts.items()))


def _drift_lines(results: list[dict], projs: dict) -> list[str]:
    lines = []
    for r in results:
        head = f"{r['kind']} {_ident(r['ref'], projs.get(r['ref']))}  #{r['work_item']}"
        if r["unavailable"]:
            lines.append(f"{head}  unavailable: {r['unavailable']}")
            continue
        rev = f"  rev {r['rev']}" if r["rev"] is not None else ""
        lines.append(f"{head}{rev}  {r['class']}")
        for f in r["fields"]:
            change = f"  {_val(f['old'])} -> {_val(f['new'])}" if "new" in f else ""
            lines.append(f"  {f['field']}  {f['class']} (owner {f['owner'] or 'none'}) rev {f['rev']}{change}")
        for a in r["attachments"]:
            lines.append(f"  attachment added at rev {a['rev']} (listed, not drift)")
    return lines


def cmd_drift(args, repo_root: Path) -> int:
    ctx = _drift_context(repo_root, "drift")
    if isinstance(ctx, _Outcome):
        _emit(args, *ctx)
        return 0
    cfg, _schema, projs, links, emails, _ledger = ctx
    refs, unmatched = _select_links(links, projs, [t.strip() for t in args.id or []], args.kind)
    try:
        results = _observe(repo_root, links, refs, projs, emails)
    except AdoImportError as exc:
        return _unavailable(args, repo_root, "drift", _tidy(exc), host_error=str(exc), items=[], counts=None)
    unmapped, why = _unmapped(repo_root, cfg)
    notes = [why] if why else []
    out = {"ok": True, "unavailable": False, "reason": None, "items": results, "counts": _class_counts(results),
           "unmapped": unmapped, "unmatched_ids": unmatched, "notes": notes}
    lines = ["Azure Boards mirror: drift  (advisory; nothing was written)"]
    lines += _drift_lines(results, projs) or ["nothing is linked yet: no ledgered item to compare"]
    if unmapped:
        lines.append("untagged on the board: " + ", ".join(f"#{i}" for i in unmapped)
                     + "  (`link <ref> --work-item N --by <you>` maps one; `show #N` reads it)")
    elif unmapped is not None:
        lines.append("untagged on the board: none found under the mirror's paths")
    if unmatched:
        lines.append("no ledgered item matches --id " + ", ".join(unmatched))
    lines += [f"note: {n}" for n in notes]
    _emit(args, out, "\n".join(lines))
    return 0


def _drift_events(ts: str, results: list[dict], ledger: list[dict]) -> tuple[list[dict], int]:
    """`observed` per item and `drift_seen` per changed field, the latter only when the ledger's latest row for that
    (ref, field) is not already this class at this revision: a pull a day later keeps the first-seen time (the
    summary ages debt by it). A header `observed` with no ref says a pull ran when nothing is ledgered."""
    latest: dict[tuple, tuple] = {}
    for e in ledger:
        if e.get("event") == "drift_seen" and e.get("ref"):
            latest[(e["ref"], e.get("field"))] = (e.get("class"), e.get("rev"))
    events, seen = [], 0
    for r in results:
        if r["unavailable"]:
            continue
        events.append(_event(ts, "observed", ref=r["ref"], kind=r["kind"], work_item=r["work_item"], rev=r["rev"],
                             **{"class": r["class"]}))
        # a relation's targets are work item ids; one that points at a pull request or a link has no id and is left out
        rows = [{"field": f["field"], "class": f["class"], "owner": f["owner"], "rev": f["rev"],
                 "revised_at": f.get("revised_at"),
                 **({"added": [i for i in f["added"] if i is not None], "removed": [i for i in f["removed"] if i is not None]}
                    if "added" in f else {})}
                for f in r["fields"] if f["class"] not in model.NOT_DRIFT_CLASSES]
        if r["class"] in ("DELETED_IN_ADO", "ORPHAN_IN_REPO"):
            rows.append({"field": None, "class": r["class"], "owner": None, "rev": r["rev"], "revised_at": None})
        for row in rows:
            if latest.get((r["ref"], row["field"])) == (row["class"], row["rev"]):
                continue
            events.append(_event(ts, "drift_seen", ref=r["ref"], kind=r["kind"], work_item=r["work_item"], **row))
            seen += 1
    return events, seen


def _proposal_lines(props: list[dict]) -> list[str]:
    """What a person may do about each drift row, as words: `ado_sync_reconcile.proposals` is the design's section 8
    table, row by row. Nothing here runs anything."""
    if not props:
        return []
    return ["proposals:"] + [f"  {p['ref']}  {p['field'] or '(the item itself)'}  {p['action']}: {p['text']}"
                             for p in props]


def _propose_specs(repo_root: Path, cfg: dict, emails: dict[str, str], now: datetime) -> dict:
    """`pull --propose-specs`: the board items under the mirror's paths that this repository has not tagged (the
    `drift` search), as ONE batch file of argument lists under the ignored local folder. `{"path", "counts", "reason"}`:
    `path` None with a `reason` when the search could not run (not searched), the items could not be read, or the
    file could not be written; `path` None with no reason when the search found nothing. Honest counting (house
    rule 2): `counts` is None whenever nothing was measured or what was found was not written -- an integer 0 only
    after a search (or the read of what it found) that came back empty. A search or a read that fails is a reason,
    never a failure of the pull; nothing is run."""
    unmeasured = {"path": None, "counts": None, "reason": None}
    ids, why = _unmapped(repo_root, cfg)
    if ids is None:
        return {**unmeasured, "reason": why}
    if not ids:
        return {"path": None, "counts": {"new_spec": 0, "link": 0}, "reason": None}
    try:
        items, _missing = _read_items(repo_root, ids, emails)
    except AdoImportError as exc:
        return {**unmeasured, "reason": f"not read: {_tidy(exc)}"}
    rows = rc.spec_proposals(list(items.values()), rc.spec_ids(repo_root))
    if not rows:   # the read ran and the board returned none of them: a measured empty, not a guess
        return {"path": None, "counts": {"new_spec": 0, "link": 0},
                "reason": "the board did not return those items (deleted, or not visible to this az login)"}
    try:
        _ensure_local_ignore(repo_root)
        path = rc.write_batch(repo_root, now, rows, _write_json)
    except OSError as exc:
        return {**unmeasured, "reason": f"not written ({type(exc).__name__})"}
    return {"path": path, "counts": {"new_spec": sum(1 for r in rows if r["action"] == "new_spec"),
                                     "link": sum(1 for r in rows if r["action"] == "link")}, "reason": None}


def _propose_specs_line(found: dict) -> str:
    counts = found["counts"]
    if found["path"]:
        return (f"propose-specs: wrote {found['path']}  ({_plural(counts['new_spec'], 'new spec')}, "
                f"{_plural(counts['link'], 'link')}; argument lists for a person to run, nothing was run)")
    if found["reason"]:
        return f"propose-specs: nothing written - {found['reason']}"
    return "propose-specs: no untagged board items under the mirror's paths"


def cmd_pull(args, repo_root: Path) -> int:
    if args.propose_specs and (args.discussion or args.full):
        raise Usage("--propose-specs reads the board's fields and cannot be combined with --discussion or --full, which "
                    "read its comments: run them one after the other")
    if args.discussion or args.full:  # `--full` forgets the comment watermark, the only one there is: it implies it
        return _pull_discussion(args, repo_root)
    _emit(args, *_pull_fields(args, repo_root))
    return 0


def _pull_fields(args, repo_root: Path) -> _Outcome:
    """The fields pull as data (`sync` runs it as its first stage): the ledgered items read back, classified and
    recorded. `--kind` narrows it when the caller has one (`sync`; `pull` itself has none). A `LedgerDrift` from the
    append propagates: nothing was recorded, and nothing here has been printed."""
    ctx = _drift_context(repo_root, "pull")
    if isinstance(ctx, _Outcome):
        return ctx
    cfg, schema, projs, links, emails, ledger = ctx
    refs, unmatched = _select_links(links, projs, [t.strip() for t in args.id or []], getattr(args, "kind", None))
    remotes: dict[int, dict] = {}
    try:
        results = _observe(repo_root, links, refs, projs, emails, remotes)
    except AdoImportError as exc:
        return _unavailable_outcome(repo_root, "pull", _tidy(exc), host_error=str(exc), items=[], counts=None)
    now = _now()
    ts = _stamp(now)
    events, seen = _drift_events(ts, results, ledger)
    observed = sum(1 for e in events if e["event"] == "observed")
    if not results:
        events = [_event(ts, "observed", ref=None, items=0)]
    append_ledger(repo_root, events)  # LedgerDrift -> main: `DRIFT: ...`, exit 1 (pull's only exit 1)
    hook, hook_note = _write_hook_line(repo_root, ledger + events)
    notes = [hook_note] if hook_note else []
    props = rc.proposals(results, projs, remotes, cfg, schema)
    out = {"ok": True, "unavailable": False, "reason": None, "as_of": ts, "items": results,
           "counts": _class_counts(results), "unmatched_ids": unmatched, "proposals": props,
           "recorded": {"observed": observed, "drift_seen": seen}, "hook_line": hook, "notes": notes}
    lines = [f"Azure Boards mirror: pull  (as of {ts})"]
    lines += _drift_lines(results, projs) or ["nothing is linked yet: no ledgered item to read"]
    if unmatched:
        lines.append("no ledgered item matches --id " + ", ".join(unmatched))
    lines += _proposal_lines(props)
    lines += [f"recorded: {_plural(observed, 'observed line')}, {_plural(seen, 'drift_seen line')}",
              f"hook line: {hook if hook is not None else 'not written'}", *[f"note: {n}" for n in notes]]
    if args.propose_specs:
        out["propose_specs"] = _propose_specs(repo_root, cfg, emails, now)
        lines.append(_propose_specs_line(out["propose_specs"]))
    return _Outcome(out, "\n".join(lines))


# --- sync: the catch-up ---------------------------------------------------------------------------------------------
#
# One read verb that runs the reads a person otherwise runs one by one, in `ado_sync_model.SYNC_STAGES` order:
#   pull        the fields pull (`_pull_fields`), honouring --id and --kind
#   drift       the classification the pull just made, from its own rows: the drift stage reads nothing from the board
#               (guardrail 24: `sync`'s az calls are `pull`'s then `plan`'s). The board items nobody tagged are the
#               `drift` verb's own untagged query; `sync` leaves them unsearched (`None`) and says so in a note
#   discussion  the comments pull (`_discussion_outcome`), ONLY on `--discussion`; `sync` has no `--full`
#   plan        the dry run (`_plan_outcome`), honouring --kind, --id, --sprint, --all and --no-comments
# Each stage is the verb's own code over a copy of the arguments (`_stage_args`). A stage that cannot read says so as
# its own `{"unavailable": true, "reason": ...}` and the next stage still runs; the document is `SYNC_NODATA` with the
# reasons filled only when the pull AND the plan could not read. A ledger `DRIFT` in the pull (or the discussion) stage
# is recorded as `drift_error`, the later stages still run, and the exit is 1: the one exit `sync` has besides 0.

SYNC_HEADER = "Azure Boards mirror: sync  (as of {as_of}; reads the board, sends nothing)"
SYNC_SECTIONS = {"pull": "== pull ==", "drift": "== drift ==  (from the pull's rows; the board is not read again)",
                 "discussion": "== discussion ==", "plan": "== plan =="}
SYNC_UNTAGGED_NOTE = ("untagged board items not searched: sync reads the board only for the pull and the plan; "
                      "`drift` searches for them")
VERB_HEADER = "Azure Boards mirror: "  # the line a read verb's own text opens with; `sync` prints one header of its own
NOT_RECORDED = "its ledger lines were not written: the ledger append failed (the DRIFT sentence says why)"


class _Stage(NamedTuple):
    """One stage's answer: its document and text, and the `DRIFT` sentence when its ledger append failed."""
    doc: dict
    text: str
    drift: str | None = None


def _stage_args(args, **over) -> argparse.Namespace:
    """A copy of `args` with `over` set: a stage is the read verb's own code over the arguments that verb would have
    been given, so a flag `sync` does not have (`--full`, `--validate`, `--propose-specs`) is pinned off here."""
    return argparse.Namespace(**{**vars(args), **over})


def _down(reason: str, host: dict | None = None, drift: str | None = None) -> _Stage:
    """A stage that could not read. Its document is the one `SYNC_NODATA` holds (`unavailable` and `reason`); the
    host block, when `az` was the reason, rides in the text only."""
    lines = [f"unavailable: {reason}"]
    if host:
        lines.append(_host_line(host))
    return _Stage({"unavailable": True, "reason": reason}, "\n".join(lines), drift)


def _stage(run: Callable[..., tuple], args, repo_root: Path, *, headed: bool) -> _Stage:
    """Run one stage. A usage error is the person's to fix and propagates; a ledger `DRIFT`, a missing precondition or
    a board that cannot be read is that stage's `unavailable`, so the next stage still runs. `headed` drops the verb's
    own header line (`sync` prints its own); the plan's first line is its identity and stays."""
    try:
        doc, text = run(args, repo_root)[:2]
    except Usage:
        raise
    except LedgerDrift as exc:
        return _down(NOT_RECORDED, drift=str(exc))
    except (Illegal, cfgmod.ConfigError) as exc:
        return _down(_tidy(exc, 400))
    except AdoImportError as exc:
        return _down(_tidy(exc), host_block_for(repo_root, str(exc)))
    if doc.get("unavailable"):
        return _down(str(doc.get("reason")), doc.get("host"))
    if headed and text.startswith(VERB_HEADER) and "\n" in text:
        text = text.split("\n", 1)[1]
    return _Stage(doc, text)


def _drift_stage(pull: _Stage) -> _Stage:
    """The drift read from the pull's own rows: its class counts are the pull's, and this stage asks the board
    nothing -- no batch read and no query (guardrail 24). The untagged search (`_unmapped`) is a board read the
    `drift` verb makes and the `pull` verb does not, so here `unmapped` is `None` (not searched, never an empty list)
    and the note names the verb that searches."""
    if pull.doc.get("unavailable"):
        return _down(pull.doc["reason"])
    notes = [SYNC_UNTAGGED_NOTE]
    counts = pull.doc["counts"]
    lines = ["classes: " + (", ".join(f"{k} {v}" for k, v in counts.items()) if counts else "none read")]
    lines += [f"note: {n}" for n in notes]
    return _Stage({"ok": True, "unavailable": False, "reason": None, "counts": counts, "unmapped": None,
                   "notes": notes}, "\n".join(lines))


def _sync_counts(repo_root: Path, plan: dict) -> dict | None:
    """What the catch-up leaves to do: the plan's creates, updates and drafted comments, and how many items are
    drifted by the ledger's own count (the number the hook line prints). None for what was never measured: the whole
    block when the plan could not be drawn up, a comment count when comments were not planned, the drift count when
    nothing was ever pulled."""
    if plan.get("unavailable"):
        return None
    try:
        drifted = _summary(read_ledger(repo_root))["counts"]["drifted"]
    except LedgerUnreadable:
        drifted = None
    return {"create": plan["counts"]["create"], "update": plan["counts"]["update"],
            "comments": plan["comments"]["draft"], "drifted": drifted}


def _sync_document(repo_root: Path, scope: dict, pull: _Stage, drift: _Stage, discussion: _Stage | None,
                   plan: _Stage, drift_error: str | None) -> dict:
    """The `--json` document, keys in `SYNC_NODATA`'s order. When the pull AND the plan could not read it IS
    `SYNC_NODATA`, with the stages' reasons filled (and the discussion stage's document when `--discussion` asked)."""
    if pull.doc.get("unavailable") and plan.doc.get("unavailable"):
        doc = copy.deepcopy(model.SYNC_NODATA)
        doc["reason"] = pull.doc["reason"]
        for name, stage in (("pull", pull), ("drift", drift), ("plan", plan)):
            doc[name]["reason"] = stage.doc["reason"]
        doc["discussion"] = discussion.doc if discussion else None
        doc["drift_error"] = drift_error
        return doc
    return {"ok": True, "unavailable": False, "reason": None, "verb": "sync", "as_of": pull.doc.get("as_of"),
            "scope": scope, "pull": pull.doc, "drift": drift.doc, "discussion": discussion.doc if discussion else None,
            "plan": plan.doc, "counts": _sync_counts(repo_root, plan.doc), "next": plan.doc.get("next"),
            "hook_line": plan.doc.get("hook_line") or pull.doc.get("hook_line"), "drift_error": drift_error}


def _sync_text(doc: dict, stages: dict[str, _Stage | None], drift_error: str | None) -> str:
    """The header, one section per stage that ran, the hook line, the footer and (last) the `DRIFT` sentence."""
    lines = [SYNC_HEADER.format(as_of=_n(doc["as_of"]))]
    for name in model.SYNC_STAGES:
        stage = stages.get(name)
        if stage is not None:
            lines += [SYNC_SECTIONS[name], *([stage.text] if stage.text else [])]
    lines.append(f"hook line: {doc['hook_line'] if doc['hook_line'] is not None else 'not written'}")
    if doc["next"]:
        lines.append(doc["next"])
    if drift_error:
        lines.append(drift_error)  # `DRIFT: ...` leads its line and ends the text, as in `pull`
    return "\n".join(lines)


def cmd_sync(args, repo_root: Path) -> int:
    kinds, ids = list(args.kind or []), [t.strip() for t in args.id or [] if t.strip()]
    sprint = _sprint_arg(args.sprint)   # a sprint that is not a sprint id is a usage error, before anything is read
    scope = {"kinds": kinds, "ids": ids, "sprint": sprint, "all": bool(args.all or not (kinds or ids or sprint)),
             "discussion": bool(args.discussion)}
    pull = _stage(_pull_fields, _stage_args(args, propose_specs=False, discussion=False, full=False), repo_root,
                  headed=True)
    drift = _drift_stage(pull)
    discussion = _stage(_discussion_outcome, _stage_args(args, propose_specs=False, full=False), repo_root,
                        headed=True) if args.discussion else None
    plan = _stage(_plan_outcome, _stage_args(args, validate=False), repo_root, headed=False)
    drift_error = "\n".join(s.drift for s in (pull, discussion) if s is not None and s.drift) or None
    doc = _sync_document(repo_root, scope, pull, drift, discussion, plan, drift_error)
    stages = {"pull": pull, "drift": drift, "discussion": discussion, "plan": plan}
    _emit(args, doc, _sync_text(doc, stages, drift_error))
    return 1 if drift_error else 0


# --- link and adopt --------------------------------------------------------------------------------------------------

AB_FORM = re.compile(r"^ab#", re.IGNORECASE)


def _work_item_arg(text: str | None) -> int:
    """`4521` or `#4521`. The `AB#4521` form is Azure Boards' commit-message link syntax, not an id: refused (2)."""
    raw = str(text or "").strip()
    if not raw:
        raise Illegal("--work-item N is required: the number of the work item to map")
    if AB_FORM.match(raw):
        raise Refused(f"Refused: --work-item {raw!r} is the AB# commit-link form, not a work item id. Pass the "
                      "number (4521 or #4521); the mirror maps by id and never by a commit-message link.")
    found = re.fullmatch(r"#?([0-9]+)", raw)
    if not found or int(found.group(1)) < 1:
        raise Illegal(f"--work-item {raw!r} is not a work item id (a positive number, 4521 or #4521)")
    return int(found.group(1))


def _other_refs(item: dict, ref: str) -> list[str]:
    """The mirror refs an item's tags name besides `ref` (`sdlc:spec:0004`; a status tag is not a ref)."""
    return sorted(t for t in item["tags"] if REF_RE.fullmatch(t) and _kind_of(t) is not None and t != ref)


def _mapped_elsewhere(links: dict, ref: str, wid: int) -> str | None:
    return next((r for r, l in links.items() if l["work_item"] == wid and r != ref), None)


def _link_event(ts: str, p: dict, item: dict, how: str, by: str) -> dict:
    return _event(ts, "linked", ref=p["ref"], kind=p["kind"], work_item=item["id"], how=how, rev_after=item["rev"],
                  type=item["type"], projection_hash=model.projection_hash(p), by=by)


def cmd_link(args, repo_root: Path) -> int:
    by = resolve_by(repo_root, args.by, "--by")
    wid = _work_item_arg(args.work_item)
    ref = args.ref.strip()
    kind = _kind_of(ref) if REF_RE.fullmatch(ref) else None
    if kind is None:
        raise Illegal(f"{ref!r} is not an sdlc:<kind>:<id> ref (sdlc:spec:0004, sdlc:feature:03)")
    need = _load(repo_root)
    if isinstance(need, str):
        raise Illegal(need)
    cfg, schema = need
    if kind not in sources.SOURCES:
        raise Illegal(f"no source reads {kind} yet, so there is nothing in the repository to map {ref} to")
    try:
        proj = next((p for p in _projections(repo_root, cfg, schema, [kind]) if p["ref"] == ref), None)
    except ValueError as exc:
        raise Illegal(f"the repository's sources do not agree: {_tidy(exc)}") from None
    if proj is None:
        raise Illegal(f"{ref} is not in this repository: no {kind} reads as that id")
    links = linked_items(read_ledger(repo_root))
    if ref in links:
        raise Illegal(f"{ref} is already mapped to #{links[ref]['work_item']}; nothing was changed")
    if (other := _mapped_elsewhere(links, ref, wid)) is not None:
        raise Illegal(f"#{wid} is already mapped to {other}; nothing was changed")
    items, missing = _read_items(repo_root, [wid], _emails(repo_root))
    if wid in missing:
        raise Illegal(f"work item #{wid} was not found (deleted, or not visible to this az login)")
    item = items[wid]
    if others := _other_refs(item, ref):
        raise Illegal(f"#{wid} already carries another mirror ref ({', '.join(others)}); nothing was changed")
    notes = []
    type_name = _row_type(proj, schema, cfg)[0]
    if type_name is not None and item["type"] != type_name:
        notes.append(f"#{wid} is a {item['type']} but {kind} maps to {type_name}; a later pull will say so")
    append_ledger(repo_root, [_link_event(_stamp(), proj, item, "linked", by)])
    row = {"ref": ref, "work_item": wid, "how": "linked", "rev": item["rev"]}
    _emit(args, {"ok": True, "linked": [row], "notes": notes},
          "\n".join([f"Linked {ref} -> #{wid} (rev {item['rev']}) by {by}", *[f"note: {n}" for n in notes]]))
    return 0


def cmd_adopt(args, repo_root: Path) -> int:
    by = resolve_by(repo_root, args.by, "--by")
    if not args.all:
        raise Illegal("adopt needs --all: it maps every repository item the board already tags; use `link` for one")
    need = _load(repo_root)
    if isinstance(need, str):
        raise Illegal(need)
    cfg, schema = need
    kinds, skipped = _scope_kinds(cfg, None)
    fit, _resolved, _gaps, _recs = _fit_view(schema, cfg, tuple(kinds))
    rides = {k for k, v in fit.items() if v["mode"] != "item"}
    try:
        projs = _projections(repo_root, cfg, schema, [k for k in kinds if k not in rides])
    except ValueError as exc:
        raise Illegal(f"the repository's sources do not agree: {_tidy(exc)}") from None
    links = linked_items(read_ledger(repo_root))
    candidates = [p for p in projs if p["ref"] not in links and _row_type(p, schema, cfg)[0] is not None]
    refs = [p["ref"] for p in candidates]
    items, _missing = _read_items(repo_root, _query_tagged(repo_root, refs), _emails(repo_root))  # one query, one read
    found = _tag_map(items, refs)
    ts, taken = _stamp(), {l["work_item"]: r for r, l in links.items()}
    events, linked, refused, absent = [], [], [], []
    for p in candidates:
        ids, ref = found[p["ref"]], p["ref"]
        if not ids:
            absent.append(ref)
        elif len(ids) > 1:
            refused.append({"ref": ref, "reason": "ambiguous: tagged on " + ", ".join(f"#{i}" for i in ids)})
        elif ids[0] in taken:
            refused.append({"ref": ref, "reason": f"#{ids[0]} is already mapped to {taken[ids[0]]}"})
        elif others := _other_refs(items[ids[0]], ref):
            refused.append({"ref": ref, "reason": f"#{ids[0]} already carries another mirror ref ({', '.join(others)})"})
        else:
            events.append(_link_event(ts, p, items[ids[0]], "adopted", by))
            taken[ids[0]] = ref
            linked.append({"ref": ref, "work_item": ids[0], "how": "adopted", "rev": items[ids[0]]["rev"]})
    append_ledger(repo_root, events)
    code = 1 if refused else 0
    lines = [f"Adopted {_plural(len(linked), 'item')} by {by}"]
    lines += [f"  {r['ref']} -> #{r['work_item']} (rev {r['rev']})" for r in linked]
    lines += [f"  refused {r['ref']}: {r['reason']}" for r in refused]
    lines.append(f"not on the board: {_plural(len(absent), 'item')} (a plan would create them)")
    _emit(args, {"ok": code == 0, "linked": linked, "refused": refused, "not_on_board": absent, "skipped": skipped},
          "\n".join(lines))
    return code


# --- the discussion: show, pull --discussion, discussion gc ----------------------------------------------------------

DEFAULT_MAX_ITEMS = 50        # templates/ado/ado.yaml: discussion.max_items_per_pull
DEFAULT_MAX_COMMENTS = 300    # discussion.max_comments_per_item
DISCUSSION_OFF = "discussion disabled (D-OWNER-7)"


def _discussion_cfg(cfg: dict) -> dict:
    block = cfg.get("discussion")
    return block if isinstance(block, dict) else {}


def _limit(block: dict, key: str, default: int) -> int:
    value = block.get(key, default)
    return value if _is_id(value) else default


def _directive_scan_on(block: dict) -> bool:
    """`directive_scan: on` is YAML's True; `off` is False (or the word, when quoted)."""
    value = block.get("directive_scan", True)
    return not (value is False or str(value).strip().lower() == "off")


def _read_discussion(repo_root: Path, wid: int, ref: str | None, emails: dict, cached: dict | None, *, full: bool,
                     max_comments: int, ts: str) -> tuple[dict, dict]:
    """Read one item's comments and history from the board into a cache document (`ado_discussion_map` cleans every
    line and scrubs every identity), plus the model's `{new, edited, deleted, watermark}` against the cache's
    watermark (none with `full`). `AdoImportError` when the board could not be read: nothing is half-built."""
    raw = ado_wit.comments(repo_root, wid)
    mapped = [dm.map_comment(c, emails) for c in raw][-max_comments:]  # the newest are kept when an item has more
    diff = dm.diff_against_watermark(mapped, {} if full or not cached else cached.get("watermark") or {})
    old = [u for u in (cached or {}).get("updates") or [] if isinstance(u, dict) and _is_id(u.get("rev"))] \
        if cached and not full else []
    fresh = ado_wit.updates_since(repo_root, wid, max((u["rev"] for u in old), default=0))
    doc = {"work_item": wid, "work_item_id": wid, "ref": ref, "pulled_at": ts, "as_of": ts, "comments": mapped,
           "updates": old + dm.scrub_updates(fresh, emails), "watermark": diff["watermark"],
           "truncated": bool(getattr(raw, "truncated", False)), "total_count": getattr(raw, "total_count", None)}
    return doc, diff


def _me(repo_root: Path, emails: dict, ts: str, *, refresh: bool) -> dict | None:
    """Who the signed-in Azure DevOps user is: `me.json` (a roster handle or None, an identity id), read from
    `connectionData` once when it is missing. None when it cannot be learnt: "mentions me" is then unknown."""
    me = None if refresh else cache.load_me(repo_root)
    if me is not None:
        return me
    try:
        user = ado_wit.connection_data(repo_root)["authenticatedUser"]
        account = ((user.get("properties") or {}).get("Account") or {}).get("$value")
        who = dm.redact_identity({"uniqueName": account, "displayName": user.get("providerDisplayName"),
                                  "id": user.get("id")}, emails)
        cache.save_me(repo_root, who["handle"], who["id"], ts)
    except (AdoImportError, ValueError, TypeError, AttributeError):
        return None
    return cache.load_me(repo_root)


def _comment_events(ts: str, ref: str, wid: int, diff: dict, me: dict | None, scan: bool) -> list[dict]:
    """`comment_seen` for each new, edited or deleted comment and `directive_seen` for each that has a line reading
    as an instruction: ids, versions, hashes and line numbers only. No text, no name, no author handle."""
    events = []
    for change in ("new", "edited", "deleted"):
        for c in diff[change]:
            mine = None if not me or not me.get("id") else me["id"] in {m["id"] for m in c["mentions"]}
            events.append(_event(ts, "comment_seen", ref=ref, work_item=wid, comment=c["id"], version=c["version"],
                                 change=change, text_sha=c["text_sha"], mentions_me=mine))
            if scan and change != "deleted" and c["flagged_lines"]:
                events.append(_event(ts, "directive_seen", ref=ref, work_item=wid, comment=c["id"],
                                     lines=c["flagged_lines"]))
    return events


def _staleness(repo_root: Path, link: dict) -> tuple:
    """Items never pulled first, then the stalest: what a capped pull should spend its reads on."""
    doc = cache.load_cache(repo_root, link["work_item"])
    return (doc is not None, str(doc.get("pulled_at") or "") if doc else "")


def _pull_discussion(args, repo_root: Path) -> int:
    _emit(args, *_discussion_outcome(args, repo_root))
    return 0


def _discussion_outcome(args, repo_root: Path) -> _Outcome:
    """The discussion pull as data (`sync` runs it, on `--discussion` only, as its third stage). A `LedgerDrift` from
    the append propagates before anything is printed."""
    need = _load(repo_root)
    if isinstance(need, str):
        return _unavailable_outcome(repo_root, "pull --discussion", need, items=[])
    cfg, _schema = need
    block = _discussion_cfg(cfg)
    if block.get("enabled", True) is False:
        return _Outcome({"ok": True, "discussion": "disabled", "reason": DISCUSSION_OFF, "items": [], "skipped": 0},
                        f"{DISCUSSION_OFF}: set discussion.enabled: true in {CONFIG_FILE} to read the board's comments")
    links = linked_items(read_ledger(repo_root))
    ids = [t.strip() for t in args.id or [] if t.strip()]
    refs, unmatched = _select_links(links, {}, ids, None)
    refs.sort(key=lambda r: (_staleness(repo_root, links[r]), r))
    cap = _limit(block, "max_items_per_pull", DEFAULT_MAX_ITEMS)
    skipped, refs = max(0, len(refs) - cap), refs[:cap]
    emails, ts = _emails(repo_root), _stamp()
    me = _me(repo_root, emails, ts, refresh=args.full) if refs else None
    scan, events, rows, comments_read, calls = _directive_scan_on(block), [], [], 0, (1 if refs else 0)
    for ref in refs:
        wid = links[ref]["work_item"]
        row = {"ref": ref, "work_item": wid, "comments": None, "new": None, "edited": None, "deleted": None,
               "truncated": None, "unavailable": None}
        rows.append(row)
        calls += 2
        try:
            doc, diff = _read_discussion(repo_root, wid, ref, emails, cache.load_cache(repo_root, wid), full=args.full,
                                         max_comments=_limit(block, "max_comments_per_item", DEFAULT_MAX_COMMENTS),
                                         ts=ts)
        except AdoImportError as exc:
            row["unavailable"] = f"{wm.classify_write_error(str(exc))}: {_tidy(exc, 160)}"
            continue
        counts = {"comments": len(doc["comments"]), "new": len(diff["new"]), "edited": len(diff["edited"]),
                  "deleted": len(diff["deleted"]), "truncated": doc["truncated"]}
        try:  # the lines are built before the cache is saved: a refused line or an unwritable cache is a row, not a crash
            item_events = [*_comment_events(ts, ref, wid, diff, me, scan),
                           _event(ts, "discussion_pulled", ref=ref, work_item=wid, **counts)]
            cache.save_cache(repo_root, doc)
        except (Illegal, OSError, ValueError) as exc:
            row["unavailable"] = f"not cached: {_tidy(exc, 160)}"
            continue
        row.update(counts)
        comments_read += counts["comments"]
        events += item_events
    append_ledger(repo_root, events)  # LedgerDrift -> main: `DRIFT: ...`, exit 1 (pull's only exit 1)
    cost = (f"cost: {_plural(len(refs), 'item')} read, {_plural(comments_read, 'comment')} "
            f"(az calls: at least {calls})")
    lines = [f"Azure Boards mirror: pull --discussion  (as of {ts})"]
    for r in rows:
        head = f"  {r['ref']}  #{r['work_item']}"
        lines.append(f"{head}  unavailable: {r['unavailable']}" if r["unavailable"] else
                     f"{head}  {_plural(r['comments'], 'comment')} ({r['new']} new, {r['edited']} edited, "
                     f"{r['deleted']} deleted){'  truncated: the board holds more' if r['truncated'] else ''}")
    if not rows:
        lines.append("  nothing is linked yet: no ledgered item to read")
    if unmatched:
        lines.append("no ledgered item matches --id " + ", ".join(unmatched))
    if skipped:
        lines.append(f"skipped: {skipped}  (over discussion.max_items_per_pull {cap}; the stalest are read first)")
    lines.append(cost)
    return _Outcome({"ok": True, "discussion": "pulled", "as_of": ts, "items": rows, "skipped": skipped,
                     "unmatched_ids": unmatched, "cost": cost}, "\n".join(lines))


def _bound(item: dict, cfg: dict) -> bool:
    """Is the item under the mirror's area path or one of its bound iterations: the places a raw `#id` is cached."""
    area = cfg.get("area_path") if isinstance(cfg.get("area_path"), str) else None
    iterations = cfg.get("iterations") if isinstance(cfg.get("iterations"), dict) else {}
    under = lambda path, root: bool(root) and (path == root or path.startswith(root.rstrip("\\") + "\\"))  # noqa: E731
    return under(item["area"], area) or any(isinstance(v, str) and under(item["iteration"], v)
                                            for v in iterations.values())


def _version_blocks(repo_root: Path, wid: int, comments: list[dict], emails: dict, for_agent: bool) -> list[str]:
    """The edit history of every comment that has been edited, quoted the way a comment always is."""
    lines = []
    for c in comments:
        if not isinstance(c, dict) or not isinstance(c.get("version"), int) or c["version"] < 2:
            continue
        mapped = [dm.map_comment(v, emails) for v in ado_wit.comment_versions(repo_root, wid, c["id"])]
        shown = dm.render_show({"work_item_id": wid, "comments": mapped}, for_agent=for_agent).split("\n")
        body = shown[next(i for i, line in enumerate(shown) if line.startswith("Work item")) + 1:]
        lines += ["", f"Versions of comment {c['id']}", *body]
    return lines


def _cfg_or_note(repo_root: Path) -> tuple[dict, str | None]:
    """The config `show` reads, and why it was set aside: missing is `{}` with no note; one that does not load is
    `{}` and a note, never a failure (the cache can still be shown, with the default limits)."""
    try:
        return cfgmod.load_config(repo_root), None
    except cfgmod.ConfigError as exc:
        if exc.kind == "missing":
            return {}, None
        return {}, (f"config: ignored ({_tidy(exc, 160)}); the discussion limits are the defaults and a raw #id is "
                    "not cached")


def _keep_discussion(repo_root: Path, ts: str, ref: str, wid: int, doc: dict, diff: dict) -> tuple[bool, str | None]:
    """Save a fetched discussion and ledger its `discussion_pulled`. `(saved, problem)`: a line the model refuses or
    a cache that cannot be written leaves both unwritten; an append that fails after the save is the `DRIFT:`
    sentence. Either is printed; `show` still exits 0."""
    try:
        event = _event(ts, "discussion_pulled", ref=ref, work_item=wid, comments=len(doc["comments"]),
                       new=len(diff["new"]), edited=len(diff["edited"]), deleted=len(diff["deleted"]),
                       truncated=doc["truncated"])
        cache.save_cache(repo_root, doc)
    except (Illegal, OSError, ValueError) as exc:
        return False, f"not cached: {_tidy(exc, 160)}"
    try:
        append_ledger(repo_root, [event])
    except LedgerDrift as exc:
        return True, str(exc)
    return True, None


def cmd_show(args, repo_root: Path) -> int:
    target = args.target.strip()
    raw = re.fullmatch(r"#([0-9]+)", target)
    if raw is None and not REF_RE.fullmatch(target):
        raise Usage(f"{target!r} is neither an sdlc:<kind>:<id> ref nor a #<work item id>")
    links = linked_items(read_ledger(repo_root))  # LedgerUnreadable -> main: `unavailable: <reason>`, exit 0
    if raw is not None:
        wid = int(raw.group(1))
        ref = next((r for r, l in links.items() if l["work_item"] == wid), None) or f"#{wid}"
    elif target not in links:
        raise Usage(f"{target} is not ledgered in this clone, so it has no work item here: pass #<work item id>, "
                    "or `link` / `adopt` it first")
    else:
        ref, wid = target, links[target]["work_item"]
    live_wanted = args.fetch or args.versions
    if live_wanted:
        try:
            ado_transport.remote(repo_root)
        except AdoImportError as exc:
            raise Usage(f"`show --fetch` and `--versions` read Azure DevOps: {_tidy(exc)}") from None
    (cfg, cfg_note), emails, ts = _cfg_or_note(repo_root), _emails(repo_root), _stamp()
    cached = cache.load_cache(repo_root, wid)
    doc, unavailable, fetched, saved = cached, None, False, cached is not None
    outside, kept = False, None
    if args.fetch:
        try:
            items, missing = _read_items(repo_root, [wid], emails)
            if wid in missing:
                raise AdoImportError(f"work item #{wid} was not found (deleted, or not visible to this az login)")
            block = _discussion_cfg(cfg)
            fresh, _diff = _read_discussion(repo_root, wid, ref, emails, cached, full=False, ts=ts,
                                            max_comments=_limit(block, "max_comments_per_item", DEFAULT_MAX_COMMENTS))
        except AdoImportError as exc:
            unavailable = _tidy(exc)  # the cache, if there is one, is shown as it was
        else:
            fetched, doc = True, fresh
            if not ref.startswith("#") or _bound(items[wid], cfg):
                saved, kept = _keep_discussion(repo_root, ts, ref, wid, fresh, _diff)
            else:
                saved, outside = False, True  # a raw id outside the bound paths is a live print: nothing is kept
    stub = {"work_item_id": wid, "ref": ref}
    rendered = dm.render_show(doc if doc is not None else stub, for_agent=args.for_agent)
    comments = doc.get("comments") if isinstance(doc, dict) and isinstance(doc.get("comments"), list) else None
    extra = []
    if args.versions:
        try:
            listing = comments if comments is not None else [dm.map_comment(c, emails)
                                                              for c in ado_wit.comments(repo_root, wid)]
            extra += _version_blocks(repo_root, wid, listing, emails, args.for_agent)
        except AdoImportError as exc:
            unavailable = unavailable or _tidy(exc)
    notes = [cfg_note] if cfg_note else []
    if args.expand == "reactions":
        notes.append("reactions: not read in this version (no route is pinned for them)")
    if doc is None:
        notes.append(f"no discussion is cached: `ado_sync.py pull --discussion --id {ref}` reads it, "
                     f"or `show {ref} --fetch`")
    if outside:
        notes.append("cached: no (the item is outside the mirror's bound paths, so nothing was saved)")
    if kept:
        notes.append(kept)  # `not cached: ...`, or the `DRIFT: ...` sentence leading its own line
    if unavailable:
        notes.append(f"unavailable: {unavailable}")
    out = {"ok": True, "work_item": wid, "ref": ref, "cached": saved, "fetched": fetched,
           "as_of": doc.get("pulled_at") if isinstance(doc, dict) else None, "unavailable": unavailable,
           "for_agent": bool(args.for_agent), "comment_count": len(comments) if comments is not None else None,
           "rendered": "\n".join([rendered, *extra]), "notes": notes}
    _emit(args, out, "\n".join([rendered, *extra, *notes]))
    return 0


def cmd_discussion(args, repo_root: Path) -> int:
    cfg = _cfg_or_empty(repo_root)
    try:
        gone = cache.gc(repo_root, cfg, ado_schema.today(), dry_run=args.dry_run)
    except (ValueError, OSError) as exc:
        raise Illegal(f"discussion gc stopped: {_tidy(exc)}") from None
    removed = [p.relative_to(repo_root).as_posix() for p in gone]
    if gone and not args.dry_run:
        append_ledger(repo_root, [_event(_stamp(), "discussion_gc", removed=len(gone),
                                         work_items=[int(p.stem) for p in gone])])
    verb = "would delete" if args.dry_run else "deleted"
    lines = [f"discussion gc: {verb} {_plural(len(gone), 'cache file')}", *[f"  {r}" for r in removed]]
    _emit(args, {"ok": True, "dry_run": bool(args.dry_run), "removed": removed, "count": len(gone)}, "\n".join(lines))
    return 0

# --- the write verbs (B3): apply, link-pr, iteration bind, posture, comment ------------------------------------------
#
# A write verb needs a named human as `--by` (`resolve_by`: blank is 1, an AI, an agent or an address off the roster is
# 2, before anything is read or sent). `apply` and `link-pr` write to the board, so they also need posture `assisted`
# (2, zero `az` spawns). `posture`, `iteration bind` and `comment` write files in this repository only, so a clone in
# `plan-only` can still use them: `posture` is how it leaves that state, and a drafted comment waits in its plan file.
# A ledger line follows each write; an append that fails is `LedgerDrift`, which `main` answers `DRIFT: ...`, exit 1.

POSTURES = ("plan-only", "assisted")
PLANS_DIR = f"{LOCAL_DIR}/plans"
NOT_OFFERED = ("apply not offered in this clone: posture is plan-only (the default). A named human runs "
               "`ado_sync.py posture assisted --by <you>` to offer it")

# What a whole-plan refusal says, by `ado_sync_model.APPLY_REFUSALS` member: fixed sentences, never the board's words.
APPLY_REFUSAL_WORDS: dict[str, str] = {
    "ai_actor": "--by reads as an AI or an agent; only a named human applies a plan",
    "posture": NOT_OFFERED,
    "forbidden_field": "the plan carries an effort field (points, estimates or hours), which the mirror never writes",
    "first_seed": "this is the first --all seed and it creates more items than limits.first_seed allows; pass "
                  "--limit N (N within limits.first_seed) to apply it in chunks",
    "identity_mismatch": "az is signed in as someone other than --by, so a comment would post in that other person's "
                         "name; sign in as --by, or re-plan with --no-comments to apply the field ops",
    "identity_unknown": "who az is signed in as could not be matched to --by (a service principal, an account that is "
                        "not on the roster, a --by that is not a roster @handle, or an identity read that failed); "
                        "re-plan with --no-comments to apply the field ops",
    "budget": "a comment in the plan is over comments.per_item_budget for its item; re-plan with --no-comments to "
              "apply the field ops",
    "max_chars": "a comment in the plan is over comments.max_chars; re-plan with --no-comments to apply the field ops",
    "email_in_text": "a comment in the plan would carry an e-mail address (a comment names people by @handle only); "
                     "re-plan with --no-comments to apply the field ops",
    "event_unknown": "a comment in the plan names an event outside the closed set; re-plan with --no-comments to "
                     "apply the field ops",
    "needs_disposition": "a comment in the plan is for an item the board no longer has or has retyped; reconcile it "
                         "first, or re-plan with --no-comments to apply the field ops",
}
# Said after `identity_unknown` when the plan would PATCH a work item: the reason is the same, the remedy is not.
UPDATE_NEEDS_ENTRA = ("This plan updates work items, and an update is sent through `az rest` (az devops invoke cannot "
                      "PATCH a work item), which needs an Entra sign-in to the Azure CLI as --by: a personal access "
                      "token alone cannot send an update (creates and comments still go through az devops invoke).")


# Why the board could not be asked or did not answer, by a closed word: never `az`'s own words, which can carry a UPN, an
# e-mail address or a storage-key GUID (house rule 10; spec 0036's Checking Plan: no `az` text in an `apply` or
# `link-pr` result). `plan` prints the board's words when a person needs them.
BOARD_FAILURE_WORDS: dict[str, str] = {
    "not_installed": "the Azure CLI (az) is not installed or not on PATH",
    "extension_missing": "az has no azure-devops extension: run `az extension add --name azure-devops`",
    "signed_out": "az is not signed in: run `az login`",
    "permission": "the signed-in identity may not read or write these work items",
    "throttled": "the board is rate-limiting this identity; try again later",
    "not_found": "the board says the organisation, the project or an item does not exist",
    "unknown": "az could not be asked, failed, or answered something unreadable",
}
AZ_CLI_STATES = ("not_installed", "extension_missing", "signed_out")  # the `host_report` states that name a cause


def _board_failure(exc: AdoImportError) -> str:
    """`<fixed sentence> (<word>)` for an `AdoImportError` from the board: the `host_report` CLI state when it names
    one, else what `ado_wit_map.classify_write_error` reads; anything else is `unknown`. Nothing of the text is kept."""
    state = host_report.cli_state_from_error("az", str(exc))[0]
    word = state if state in AZ_CLI_STATES else wm.classify_write_error(str(exc))
    word = word if word in BOARD_FAILURE_WORDS else "unknown"
    return f"{BOARD_FAILURE_WORDS[word]} ({word})"


def _posture_of(cfg: dict) -> str:
    return cfg.get("posture") if cfg.get("posture") in POSTURES else "plan-only"


def _require_assisted(cfg: dict, verb: str) -> None:
    """Posture is read before any file, plan or `az`: a `plan-only` clone is refused the same whatever else is true."""
    if cfg.get("posture") != "assisted":
        raise Refused(f"Refused: {verb} sent nothing. {NOT_OFFERED}.")


def _write_text(path: Path, text: str) -> None:
    """UTF-8 text with a bare LF, through a temporary file and a rename (the form `_write_json` writes JSON in)."""
    scratch = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        scratch.write_bytes(text.encode("utf-8"))
        os.replace(scratch, path)
    finally:
        scratch.unlink(missing_ok=True)


def _write_plan_file(repo_root: Path, rows: list[dict], *, ids: list[str], posture: str, stamp: str) -> tuple[str, str]:
    """`(plan hash, repo-relative path)` of a plan file holding `rows`, in the one shape `plan` writes and `apply`
    reads. `Illegal` when it cannot be written: nothing was ledgered, so nothing disagrees."""
    plan = model.plan_hash(rows)
    path = f"{PLANS_DIR}/{plan}.json"
    doc = {"schema": PLAN_SCHEMA, "plan": plan, "created": stamp,
           "scope": {"kinds": [], "ids": ids, "sprint": None, "all": False}, "posture": posture, "rows": rows}
    try:
        _ensure_local_ignore(repo_root)
        _write_json(repo_root / path, doc)
    except OSError as exc:
        raise Illegal(f"could not write the plan file {path} ({type(exc).__name__}); nothing was ledgered") from None
    return plan, path


# --- apply -----------------------------------------------------------------------------------------------------------

def _confirm_arg(text) -> str:
    raw = str(text or "").strip()
    if not raw:
        raise Illegal("--confirm <12hex> is required: the hash `ado_sync.py plan` printed for the plan you read")
    if not bc.HASH_RE.fullmatch(raw):
        raise Illegal(f"--confirm {raw!r} is not a plan hash: 12 lower-case hex digits, as `plan` printed it")
    return raw


def _read_plan(repo_root: Path, confirm: str) -> dict:
    """The plan file `confirm` names, checked: it exists, is a plan, says it is `confirm`, and its rows still hash to
    `confirm`. A file edited after it was planned is a stale hash: what a person confirmed is not what is in it."""
    rel = f"{PLANS_DIR}/{confirm}.json"
    try:
        text = (repo_root / rel).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise Illegal(f"plan missing: {rel} does not exist in this clone; run `ado_sync.py plan`, read it, and "
                      "confirm the hash it prints") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise Illegal(f"the plan file {rel} could not be read ({type(exc).__name__}); nothing was sent") from None
    try:
        doc = json.loads(text)
    except (ValueError, RecursionError):
        doc = None
    rows = doc.get("rows") if isinstance(doc, dict) else None
    if not (isinstance(rows, list) and all(isinstance(r, dict) for r in rows)):
        raise Illegal(f"{rel} is not a plan file (no list of rows); run `ado_sync.py plan` again")
    if doc.get("plan") != confirm:
        raise Illegal(f"stale hash: {rel} holds plan {doc.get('plan')!r}, not {confirm}; run `ado_sync.py plan` again "
                      "and confirm the hash it prints")
    if model.plan_hash(rows) != confirm:
        raise Illegal(f"stale hash: the rows of {rel} no longer hash to {confirm} (the file was edited after it was "
                      "planned); run `ado_sync.py plan` again and confirm the new hash")
    return doc


def _what(row: dict) -> str:
    """The item a result row is about: its ref, else the `#id` a comment was addressed to."""
    return row["ref"] if row.get("ref") else f"#{row.get('work_item')}"


def _applied_line(a: dict) -> str:
    if a["action"] == "create":
        return f"create {_what(a)} -> #{a['work_item']} (rev {a['rev_after']})"
    if a["action"] == "update":
        return f"update {_what(a)} #{a['work_item']} (rev {a['rev_after']})"
    how = ", recovered after an unknown outcome" if a.get("recovered") else ""
    via = f"comment {a['comment_id']}" if a.get("comment_id") is not None else f"history, rev {a.get('rev_after')}"
    return f"comment {_what(a)} #{a['work_item']} ({via}{how})"


def _failed_line(f: dict) -> str:
    where = _what(f) + (f" #{f['work_item']}" if f.get("work_item") and f.get("ref") else "")
    why = f" ({f['reason']})" if f.get("reason") else ""
    return f"{f['action']} {where}  {f['class']}{why}" + ("" if f["class"] == "drift" else f": {f['detail']}")


def _apply_report(args, plan: str, by: str, result: dict, *, rest_writes: bool = False) -> int:
    code, reason = result["exit"], result["refused_reason"]
    applied, failed, deferred = result["applied"], result["failed"], result["deferred"]
    counts = {"applied": len(applied), "failed": len(failed), "deferred": len(deferred)}
    if reason is not None:  # nothing was sent: the whole plan is refused
        words = APPLY_REFUSAL_WORDS[reason]
        if reason == "identity_unknown" and rest_writes:
            words = f"{words}. {UPDATE_NEEDS_ENTRA}"
        return _error(args, f"Refused: apply sent nothing. {words} (reason: {reason})", 2,
                      plan=plan, by=by, refused_reason=reason, applied=[], failed=[], deferred=[], counts=counts,
                      drift=None)
    drift = next((f["detail"] for f in failed if f["class"] == "drift"), None)   # begins `DRIFT: `
    if code == 1:
        word = "some rows failed or the run stopped; plan again before applying what is left"
    elif not applied and not deferred:
        word = "nothing was sent: the plan holds no row `apply` sends (create, update or a drafted comment)"
    elif deferred:
        word = "applied what the limit allowed; the rest is deferred, apply the same plan again for it"
    else:
        word = "all applied"
    lines = [f"apply {plan}  by {by}"]
    if drift:
        lines.append(drift)  # `DRIFT: ...` leads its line, as in sprint.py
    lines.append(f"applied {len(applied)}")
    lines += [f"  {_applied_line(a)}" for a in applied]
    if failed:
        lines += [f"failed {len(failed)}", *[f"  {_failed_line(f)}" for f in failed]]
    if deferred:
        lines += [f"deferred {len(deferred)}", *[f"  {d['action']} {_what(d)}  {d['why']}" for d in deferred]]
    lines.append(f"Result: {word} (exit {code})")
    payload = {"ok": code == 0, "exit": code, "plan": plan, "by": by, "applied": applied, "failed": failed,
               "deferred": deferred, "refused_reason": None, "counts": counts, "drift": drift}
    _emit(args, payload, "\n".join(lines))
    return code


def cmd_apply(args, repo_root: Path) -> int:
    by = resolve_by(repo_root, args.by, "--by")
    confirm = _confirm_arg(args.confirm)
    cfg = cfgmod.load_config(repo_root)  # ConfigError -> main (1)
    _require_assisted(cfg, "apply")
    schema = ado_schema.load_schema(repo_root)  # an unusable file -> AdoImportError -> main (1)
    if schema is None:
        raise Illegal("no discovered schema: run `ado_sync.py discover` first, so there is a process to apply against")
    plan = _read_plan(repo_root, confirm)
    try:
        result = apply_mod.apply_plan(repo_root, plan, by=by, cfg=cfg, schema=schema, limit=args.limit,
                                      today=_now().date())
    except ValueError as exc:  # a malformed row, a ledger that cannot be read, a limit that is not a count: nothing sent
        raise Illegal(_tidy(exc, 300)) from None
    except AdoImportError as exc:  # a fixed sentence: the board's own words can name people (house rule 10)
        raise Illegal(f"the board could not be read before the first write, so nothing was sent: {_board_failure(exc)}; "
                      "`ado_sync.py plan` shows what the board answers") from None
    return _apply_report(args, confirm, by, result, rest_writes=apply_mod.needs_rest_writes(plan.get("rows"), cfg))


# --- link-pr ---------------------------------------------------------------------------------------------------------

def _spec_arg(text) -> str:
    raw = str(text or "").strip()
    if not re.fullmatch(r"[0-9]{1,6}", raw):
        raise Illegal(f"--spec {raw!r} is not a spec id (0004, or 4)")
    return raw.zfill(4)


def _pr_arg(text) -> int:
    found = re.fullmatch(r"!?([1-9][0-9]*)", str(text or "").strip())
    if found is None:
        raise Illegal(f"--pr {str(text or '').strip()!r} is not a pull request number (a positive number: 12, or !12)")
    return int(found.group(1))


def _link_failure(pr: int, wid: int, exc: AdoImportError) -> str:
    """What a failed link says: fixed sentences by `error_class`, never the board's own words (they can name people).
    No `error_class` means the error came before `az` was asked (`ado_wit.link_pr`: the remote could not be read)."""
    cls = getattr(exc, "error_class", None)
    if cls == "unknown":
        return (f"PR {pr} may or may not be linked to #{wid}: the outcome is unknown (a timeout or an answer that "
                "could not be read). Look at the pull request's work items before running this again; nothing was "
                "ledgered.")
    if cls in apply_mod.DETAIL:
        return f"PR {pr} was not linked to #{wid}: the board refused it ({cls}): {apply_mod.DETAIL[cls]}"
    return (f"PR {pr} was not linked to #{wid}: nothing was sent and az was not asked, because this clone's Azure "
            "DevOps remote could not be read; `ado_sync.py discover` prints the host this clone points at")


def _pr_linked_on(cfg: dict) -> bool:
    block = cfg.get("comments") if isinstance(cfg.get("comments"), dict) else {}
    events = block.get("events") if isinstance(block.get("events"), dict) else {}
    value = events.get("pr_linked")
    word = value.strip().lower() if isinstance(value, str) else None
    if value is True or word in ("on", "true"):
        return True
    if value is False or word in ("off", "false"):
        return False
    return comments_mod.EVENT_TEMPLATES["pr_linked"]["default"] == "on"


def _draft_pr_linked(repo_root: Path, cfg: dict, ledger: list[dict], ref: str, wid: int, pr: int,
                     stamp: str) -> tuple[dict | None, str | None]:
    """`(the comment plan, a note)` for the `pr_linked` event: nothing when the event is off (the default), else a
    one-row plan file holding `PR !N linked.` for a person to confirm. The row is drafted, never sent."""
    if not _pr_linked_on(cfg):
        return None, None
    try:
        row = comments_mod.event_row("pr_linked", ref, wid, {"pr": pr}, {"ref": ref, "pr": pr}, cfg=cfg, ledger=ledger)
    except ValueError as exc:  # includes `MissingValue`
        return None, f"pr_linked comment not drafted: {_tidy(exc, 160)}"
    if row["status"] != "draft":
        return None, f"pr_linked comment not drafted ({row['reason']}): {row['detail']}"
    try:
        plan, path = _write_plan_file(repo_root, [row], ids=[ref], posture=_posture_of(cfg), stamp=stamp)
    except Illegal as exc:
        return None, f"pr_linked comment not drafted: {exc}"
    return {"plan": plan, "path": path, "row": row}, None


def cmd_link_pr(args, repo_root: Path) -> int:
    by = resolve_by(repo_root, args.by, "--by")
    spec, pr = _spec_arg(args.spec), _pr_arg(args.pr)
    cfg = cfgmod.load_config(repo_root)  # ConfigError -> main (1)
    _require_assisted(cfg, "link-pr")
    ledger = read_ledger(repo_root)
    ref = f"sdlc:spec:{spec}"
    link = linked_items(ledger).get(ref)
    if link is None:
        raise Illegal(f"{ref} is not ledgered in this clone, so it has no work item here: `plan` and `apply` create "
                      "it, or `link` / `adopt` maps one that exists")
    wid = link["work_item"]
    done = any(e.get("event") == "applied" and e.get("action") == "link_pr" and e.get("ref") == ref
               and e.get("pr") == pr for e in ledger)
    if done:
        _emit(args, {"ok": True, "ref": ref, "work_item": wid, "pr": pr, "linked": False, "comment_plan": None,
                     "notes": []}, f"PR {pr} is already linked to #{wid} ({ref}) in this clone's ledger; nothing was sent")
        return 0
    # The line carries the item's baseline forward (`rev_after`, `type`, `projection_hash` of its last linking line), so
    # the ledger still says what was pushed and when; the link's own revision was not read.
    carried = {k: link[k] for k in ("rev_after", "type", "projection_hash") if link.get(k) is not None}
    stamp = _stamp()
    event = _event(stamp, "applied", ref=ref, kind="spec", work_item=wid, action="link_pr", pr=pr,
                   fields=["relations:ArtifactLink"], by=by, executed_as="unknown", **carried,
                   notes=["baseline carried: the revision the link made was not read"])
    try:
        ado_wit.link_pr(repo_root, pr, wid)
    except AdoImportError as exc:
        raise Illegal(_link_failure(pr, wid, exc)) from None
    append_ledger(repo_root, [event])  # LedgerDrift -> main: `DRIFT: ...`, exit 1 (the link is on the board, unrecorded)
    comment_plan, note = _draft_pr_linked(repo_root, cfg, ledger + [event], ref, wid, pr, stamp)
    notes = [f"a later `pull` may report the PR link as a relation change on #{wid}: the revision it made was not read"]
    notes += [note] if note else []
    lines = [f"Linked PR {pr} to #{wid} ({ref}) by {by}"]
    if comment_plan:
        lines.append(f"Drafted the pr_linked comment: plan {comment_plan['plan']} "
                     f"(`ado_sync.py apply --confirm {comment_plan['plan']} --by <you>` sends it)")
    lines += [f"note: {n}" for n in notes]
    _emit(args, {"ok": True, "ref": ref, "work_item": wid, "pr": pr, "linked": True,
                 "comment_plan": {k: comment_plan[k] for k in ("plan", "path")} if comment_plan else None,
                 "notes": notes}, "\n".join(lines))
    return 0


# --- posture and iteration bind: `.sdlc/ado.yaml`, edited in place ---------------------------------------------------

_POSTURE_LINE = re.compile(r"^posture:([ \t]*)([^\s#]+)(.*)$", re.MULTILINE)
_ITERATIONS_KEY = re.compile(r"^iterations:[ \t]*(#.*)?$")


def _with_posture(text: str, value: str) -> str:
    """The config text with its top-level `posture:` line set, its trailing comment kept in its column."""
    found = _POSTURE_LINE.search(text)
    if found is None:
        return text + ("" if not text or text.endswith("\n") else "\n") + f"posture: {value}\n"
    gap, old, rest = found.groups()
    if rest.lstrip(" ").startswith("#"):
        pad = max(1, len(rest) - len(rest.lstrip(" ")) + len(old) - len(value))
        rest = " " * pad + rest.lstrip(" ")
    return text[:found.start()] + f"posture:{gap}{value}{rest}" + text[found.end():]


def _quoted(text: str) -> str:
    """A YAML single-quoted scalar: the one form that needs no other escaping (a path carries backslashes)."""
    return "'" + text.replace("'", "''") + "'"


def _with_iteration(text: str, sprint: str, path: str) -> str | None:
    """The config text with `sprint: path` under a block-style top-level `iterations:`; a new block when the key is
    absent. None when the key is there in another style (the caller then rewrites the file from the parsed config)."""
    lines = text.split("\n")
    start = next((i for i, line in enumerate(lines) if _ITERATIONS_KEY.match(line)), None)
    entry = f"{sprint}: {_quoted(path)}"
    if start is None:
        if any(line.startswith("iterations:") for line in lines):
            return None
        return text + ("" if not text or text.endswith("\n") else "\n") + f"iterations:\n  {entry}\n"
    last, indent, end = start, None, start + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and line[0] in " \t":
            last, indent = end, indent or line[:len(line) - len(line.lstrip())]
        elif line.strip():
            break
        end += 1
    for i in range(start + 1, last + 1):
        found = re.match(rf"^(\s+){re.escape(sprint)}:[ \t]*", lines[i])
        if found:
            comment = re.search(r"[ \t]+#[^'\"]*$", lines[i])
            lines[i] = f"{found.group(1)}{entry}{comment.group(0) if comment else ''}"
            return "\n".join(lines)
    lines.insert(last + 1, f"{indent or '  '}{entry}")
    return "\n".join(lines)


def _save_config(repo_root: Path, new_cfg: dict, edited: str | None) -> str | None:
    """Write `.sdlc/ado.yaml`: the in-place edit when it parses back to exactly `new_cfg`, else the parsed config
    dumped (comments lost, and the note says so). `Illegal` when it cannot be written."""
    note = None
    try:
        parsed = yaml.safe_load(edited) if edited is not None else None
    except yaml.YAMLError:
        parsed = None
    if parsed != new_cfg:
        edited = yaml.safe_dump(new_cfg, sort_keys=False, allow_unicode=True)
        note = f"{CONFIG_FILE} was rewritten without its comments: its layout could not be edited in place"
    try:
        _write_text(repo_root / CONFIG_FILE, edited)
    except OSError as exc:
        raise Illegal(f"could not write {CONFIG_FILE} ({type(exc).__name__}); nothing was changed") from None
    return note


def _config_text(repo_root: Path) -> str:
    try:
        return (repo_root / CONFIG_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Illegal(f"{CONFIG_FILE} could not be read ({type(exc).__name__})") from None


def cmd_posture(args, repo_root: Path) -> int:
    by = resolve_by(repo_root, args.by, "--by")
    cfg = cfgmod.load_config(repo_root)  # ConfigError -> main (1): the posture is a key of the config
    value, previous = args.value, _posture_of(cfg)
    if cfg.get("posture") == value or (cfg.get("posture") is None and value == previous):
        _emit(args, {"ok": True, "posture": value, "previous": previous, "changed": False, "notes": []},
              f"Posture is already {value}; nothing was changed")
        return 0
    event = _event(_stamp(), "posture", posture=value, previous=previous, by=by)
    note = _save_config(repo_root, {**cfg, "posture": value}, _with_posture(_config_text(repo_root), value))
    append_ledger(repo_root, [event])  # LedgerDrift -> main: `DRIFT: ...` (the config moved, the record did not)
    notes = [note] if note else []
    if value == "assisted":
        notes.append("apply is now offered here: `ado_sync.py plan`, read it, then `ado_sync.py apply --confirm <hash> "
                     "--by <you>`; the board is written as whoever az is signed in as")
    _emit(args, {"ok": True, "posture": value, "previous": previous, "changed": True, "notes": notes},
          "\n".join([f"Posture: {previous} -> {value} by {by}", *[f"note: {n}" for n in notes]]))
    return 0


def _iteration_path(text) -> str:
    raw = str(text or "").strip()
    if not raw:
        raise Illegal("--path is required: the iteration path to bind, as the discovered schema spells it "
                      "(Claims\\Sprint 7)")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise Illegal("--path may not hold a control character")
    return raw[1:] if raw.startswith("\\") else raw  # the REST form `\Claims\Sprint 7` is the work-item form


def cmd_iteration(args, repo_root: Path) -> int:
    by = resolve_by(repo_root, args.by, "--by")
    sprint = str(args.sprint or "").strip()
    if not SPRINT_ID_RE.fullmatch(sprint):
        raise Illegal(f"{sprint!r} is not a sprint id (S07, S12): the id of a file in .sdlc/sprints/")
    path = _iteration_path(args.path)
    cfg = cfgmod.load_config(repo_root)  # ConfigError -> main (1)
    schema = ado_schema.load_schema(repo_root)  # an unusable file -> AdoImportError -> main (1)
    if schema is None:
        raise Illegal("no discovered schema: run `ado_sync.py discover` first, so there is an iteration tree to bind to")
    known = [i["path"] for i in schema.get("iterations") or [] if isinstance(i, dict) and isinstance(i.get("path"), str)]
    found = next((k for k in known if k == path), None) or next((k for k in known if k.casefold() == path.casefold()),
                                                                None)
    if found is None:
        shown = ", ".join(known[:6]) + (", ..." if len(known) > 6 else "")
        raise Illegal(f"{path!r} is not an iteration path in the discovered schema (known: {shown or 'none'}); "
                      "bind to one that exists, or `ado_sync.py discover --refresh` if it was just added")
    iterations = dict(cfg["iterations"]) if isinstance(cfg.get("iterations"), dict) else {}
    previous = iterations.get(sprint)
    notes = []
    team = schema.get("team_iterations")
    if isinstance(team, list) and found not in [t.get("path") for t in team if isinstance(t, dict)]:
        notes.append(f"{found} is in the project's iteration tree but not one of "
                     f"{_name_of(schema.get('team')) or 'the team'}'s iterations; add it to the team in Boards, or the "
                     "team's sprint board will not show it")
    elif team is None:
        notes.append("the team's iterations were not read (no team in the config), so this path was not checked "
                     "against them")
    if not (repo_root / ".sdlc" / "sprints" / f"{sprint}.md").is_file():
        notes.append(f"there is no .sdlc/sprints/{sprint}.md in this clone; the binding is recorded anyway")
    sharing = sorted(k for k, v in iterations.items() if v == found and k != sprint)
    if sharing:
        notes.append(f"{', '.join(sharing)} {'is' if len(sharing) == 1 else 'are'} also bound to {found}")
    if previous == found:
        _emit(args, {"ok": True, "sprint": sprint, "path": found, "previous": previous, "changed": False,
                     "notes": notes}, "\n".join([f"{sprint} is already bound to {found}; nothing was changed",
                                                 *[f"note: {n}" for n in notes]]))
        return 0
    event = _event(_stamp(), "iteration_bound", ref=f"sdlc:sprint:{sprint}", kind="sprint", sprint=sprint, path=found,
                   previous=previous, by=by)
    iterations[sprint] = found
    saved = _save_config(repo_root, {**cfg, "iterations": iterations},
                         _with_iteration(_config_text(repo_root), sprint, found))
    append_ledger(repo_root, [event])  # LedgerDrift -> main: `DRIFT: ...` (the config moved, the record did not)
    notes += [saved] if saved else []
    was = f" (was {previous})" if previous else ""
    _emit(args, {"ok": True, "sprint": sprint, "path": found, "previous": previous, "changed": True, "notes": notes},
          "\n".join([f"Bound {sprint} -> {found}{was} by {by}", *[f"note: {n}" for n in notes]]))
    return 0


# --- comment ---------------------------------------------------------------------------------------------------------

def cmd_comment(args, repo_root: Path) -> int:
    by = resolve_by(repo_root, args.by, "--by")
    target = str(args.target or "").strip()
    if args.message is None:
        raise Illegal("--message is required: the comment's text. Write it as --message=<text> so a text that starts "
                      "with a dash is not read as a flag")
    cfg = _cfg_or_empty(repo_root)
    ledger = read_ledger(repo_root)
    links = linked_items(ledger)
    raw = re.fullmatch(r"#([0-9]+)", target)
    if raw is not None:  # a raw id names the item's ref when the ledger knows it, so one key covers both spellings
        wid = int(raw.group(1))
        if wid < 1:
            raise Illegal(f"{target} is not a work item id (#4521)")
        ref = next((r for r, link in sorted(links.items()) if link["work_item"] == wid), None)
    elif REF_RE.fullmatch(target):
        if target not in links:
            raise Illegal(f"{target} is not ledgered in this clone, so it has no work item here: pass #<work item id>, "
                          "or `link` / `adopt` it first")
        ref, wid = target, links[target]["work_item"]
    else:
        raise Illegal(f"{target!r} is neither an sdlc:<kind>:<id> ref nor a #<work item id>")
    try:
        row = comments_mod.ad_hoc_row(ref or f"#{wid}", wid, args.message, by=by, mentions=args.mention or [], cfg=cfg,
                                      event=args.event, ledger=ledger)
    except ValueError as exc:  # an empty message, a mention that is not @handle: the request is illegal, not refused
        raise Illegal(_tidy(exc, 200)) from None
    stamp, posture = _stamp(), _posture_of(cfg)
    if row["status"] == "refused":  # exit 2 and the refusal is recorded; the refused text is in neither
        append_ledger(repo_root, [_event(stamp, "comment_refused", ref=row["ref"], work_item=wid, reason=row["reason"],
                                         idem_key=row["idem_key"], comment_event=row["event"], by=by)])
        shown = {k: v for k, v in row.items() if k != "text"}  # the refused words are not echoed back in the result
        return _error(args, f"Refused: the comment was not drafted ({row['reason']}): {row['detail']}", 2,
                      reason=row["reason"], row=shown)
    if row["status"] == "skipped":  # already posted: nothing to confirm
        _emit(args, {"ok": True, "plan": None, "path": None, "posture": posture, "apply_offered": False, "row": row,
                     "notes": []}, f"Nothing to draft: {row['detail']}")
        return 0
    plan, path = _write_plan_file(repo_root, [row], ids=[target], posture=posture, stamp=stamp)
    offered = posture == "assisted"
    closing = (model.apply_next_line(plan)
               if offered else f"{NOT_OFFERED}; the comment stays drafted in the plan file")
    _emit(args, {"ok": True, "plan": plan, "path": path, "posture": posture, "apply_offered": offered, "row": row,
                 "notes": row["notes"]},
          "\n".join([f"comment plan {plan}  (posture {posture})", *_comment_lines(row, plan), f"Plan file: {path}",
                     closing]))
    return 0


# --- CLI -------------------------------------------------------------------------------------------------------------

# --- reconcile -------------------------------------------------------------------------------------------------------

def _from_comment_arg(text) -> int | None:
    if text is None:
        return None
    raw = str(text).strip()
    if not re.fullmatch(r"[0-9]+", raw) or int(raw) < 1:
        raise Illegal(f"--from-comment {raw!r} is not a comment id (a positive number from the cached discussion)")
    return int(raw)


def _ledger_appendable(repo_root: Path) -> None:
    """Prove the ledger can take a line BEFORE the owning verb starts: an append that failed afterwards would leave
    that verb's edit with no record. Nothing is written to it."""
    path = Path(repo_root) / LEDGER
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8"):
            pass
    except OSError as exc:
        raise Illegal(f"DRIFT: the ledger cannot be appended to ({LEDGER}: {type(exc).__name__}); nothing was started, "
                      "so nothing changed. Make the path writable and run it again.") from None


def _plan_child(repo_root: Path, route: str, ref: str, kind: str, row: dict, by: str, reason: str | None,
                comment_id: int | None) -> dict:
    """The child `--take ado` starts, from the repository's projection and the board's CURRENT item (one batch read: the
    drift row names the field that moved, not what the board holds now)."""
    need = _load(repo_root)
    if isinstance(need, str):
        raise Illegal(need)
    cfg, schema = need
    if kind not in sources.SOURCES:
        raise Illegal(f"no source reads {kind} yet, so there is nothing in the repository to take the board's change into")
    try:
        proj = next((p for p in _projections(repo_root, cfg, schema, [kind]) if p["ref"] == ref), None)
    except ValueError as exc:
        raise Illegal(f"the repository's sources do not agree: {_tidy(exc)}") from None
    if proj is None:
        raise Illegal(f"{ref} is not in this repository: no {kind} reads as that id")
    wid = row["work_item"]
    if not _is_id(wid):
        raise Illegal("the drift row names no work item: pull again")
    items, missing = _read_items(repo_root, [wid], _emails(repo_root))   # AdoImportError: exit 1, nothing was started
    if wid in missing:
        raise Illegal(f"#{wid} is gone from the board (deleted, or not visible to this az login): pull again")
    # D52: the cached comment is only ever SHOWN as a suggestion; the resolution is the --reason a person typed
    comment = rc.cached_comment(cache.load_cache(repo_root, wid), comment_id) if comment_id is not None else None
    if route == "propose":   # D32: the board's words (or that comment's) become `<artifact>.proposed`; no child starts
        return {"verb": "propose", "argv": None, "shown": ["propose", row["field"]], "cwd": repo_root,
                "propose": {"proj": proj, "remote": items[wid], "field": row["field"], "comment": comment}}
    return rc.plan_child(route, repo_root=repo_root, ref=ref, proj=proj, remote=items[wid], cfg=cfg, schema=schema,
                         by=by, reason=reason, comment=comment, comment_id=comment_id)


def _settled_words(settled: bool, why: str, take: str, child: dict | None, exit_code) -> str:
    if settled:
        return "off the books"
    if take == "sdlc":
        return "still open until `apply` writes the field"
    if child is not None:
        return ("still open: the child did not run" if exit_code is None
                else f"still open: the child exited {exit_code}")
    return f"still open: {why}"


def _reconcile(args, repo_root: Path, *, by: str, ref: str, kind: str, owner: str | None, reason: str | None,
               comment_id: int | None) -> int:
    take = args.take
    ledger = read_ledger(repo_root)
    row = rc.pick_row(rc.drift_rows(ledger), ref, args.field)
    cls, field = row["class"], row["field"]
    disposition = rc.disposition_of(cls, take)
    rc.check_inputs(take, owner, reason)
    field_owner = row["owner"] or model.ownership_for(kind).get(field or "")
    notes: list[str] = []
    route = None
    if take == "sdlc":
        rc.check_sdlc(kind, field, field_owner)
        notes.append("the next `plan` carries the update that puts the repository's value back; `apply` lands it and "
                     "closes the row")
    elif take == "ado":
        route = "propose" if rc.is_text_proposal(field, field_owner) else rc.ado_route(kind, field, field_owner)
    if comment_id is not None and route not in ("decide", "propose"):
        raise rc.Rejected("Refused: --from-comment is for closing a decision (--take ado on its State) or proposing "
                          "a comment's words for a co-owned text field (--take ado on it); it is not used for "
                          "anything else.")
    child = _plan_child(repo_root, route, ref, kind, row, by, reason, comment_id) if route else None
    ts = _stamp()
    fields = {"ref": ref, "kind": kind, "work_item": row["work_item"], "field": field, "class": cls,
              "disposition": disposition, "by": by}
    if owner:
        fields["owner"] = owner
    fields.update(rc.ledger_reason(take, reason))   # `<text>` + reason_sha for ado/sdlc; the words for not-drift/ack
    if comment_id is not None:
        fields["comment_id"] = comment_id
    if child:
        fields["child_argv"] = child["shown"]
        fields["argv_sha"] = rc.argv_sha(child["shown"])
    if notes:
        fields["notes"] = notes
    _event(ts, "reconciled", **fields, **({"child_exit": 0} if child else {}))   # the model refuses an address, first
    _ledger_appendable(repo_root)
    if child and child["verb"] == "propose":   # Rejected / Precondition here: nothing written, nothing ledgered
        result = rc.propose(repo_root, **child["propose"])
        fields.update({"proposed": result["path"], "proposed_sha": result["proposed_sha"]})
    else:
        result = rc.run_child(child["argv"], child["cwd"]) if child else None
    if result is not None:
        fields["child_exit"] = result["exit"]
    append_ledger(repo_root, [_event(ts, "reconciled", **fields)])   # LedgerDrift -> main: `DRIFT: ...`, exit 1
    exit_code = result["exit"] if result is not None else None
    settled, why = model.validate_disposition({**fields, "class": cls})
    failed = result is not None and exit_code != 0
    label = field or "the item itself"
    state = _settled_words(settled, why, take, child, exit_code)
    out = {"ok": not failed, "ref": ref, "kind": kind, "field": field, "class": cls, "take": take,
           "disposition": disposition, "by": by, "owner": owner, "settled": settled, "settled_why": state,
           "child": None if result is None else {"verb": child["verb"], "argv": child["shown"], "exit": exit_code,
                                                 "stdout": result["stdout"], "stderr": result["stderr"]},
           "notes": notes}
    if "proposed" in fields:   # the `.proposed` the take wrote, as the ledger line names it (the desktop dialog reads it)
        out["proposed"] = fields.get("proposed")
        out["proposed_sha"] = fields.get("proposed_sha")
    if failed:
        out["exit"] = 1
    lines = [f"{'Not reconciled' if failed else 'Reconciled'} {ref} {label} ({cls}): {disposition} by {by}"]
    if result is not None:
        shown = json.dumps(child["shown"], ensure_ascii=False)
        lines.append(f"  child: {shown} -> exit {'none' if exit_code is None else exit_code}")
        lines += [f"  | {line}" for line in (result["stdout"] + "\n" + result["stderr"]).splitlines() if line.strip()]
    lines += [f"  settled: {state}"] + [f"  note: {n}" for n in notes]
    _emit(args, out, "\n".join(lines))
    return 1 if failed else 0


def cmd_reconcile(args, repo_root: Path) -> int:
    by = resolve_by(repo_root, args.by, "--by")
    if args.take is None:
        raise Illegal("--take is required: ado, sdlc, ack or not-drift")
    ref = args.ref.strip()
    kind = _kind_of(ref) if REF_RE.fullmatch(ref) else None
    if kind is None:
        raise Illegal(f"{ref!r} is not an sdlc:<kind>:<id> ref (sdlc:spec:0004, sdlc:decision:01)")
    owner = resolve_by(repo_root, args.owner, "--owner") if args.owner is not None else None
    reason = args.reason.strip() if isinstance(args.reason, str) and args.reason.strip() else None
    comment_id = _from_comment_arg(args.from_comment)
    try:
        return _reconcile(args, repo_root, by=by, ref=ref, kind=kind, owner=owner, reason=reason, comment_id=comment_id)
    except rc.Rejected as exc:
        raise Refused(str(exc)) from None
    except rc.Precondition as exc:
        raise Illegal(str(exc)) from None


BY_HELP = ("A named person, ledgered as the roster @handle when it is one person's handle, name or address on "
           ".sdlc/team.yaml (else as typed); an AI, an agent or an address off the roster is refused (exit 2)")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    src = common.add_mutually_exclusive_group()
    src.add_argument("--state", help="Path to .sdlc/state.yaml (workflow mode; repo root = parent of .sdlc/)")
    src.add_argument("--repo", default=".", help="Target repo root (standalone mode; default: cwd)")
    common.add_argument("--json", action="store_true", help="Print one JSON document instead of prose")

    parser = argparse.ArgumentParser(
        prog="ado_sync.py",
        description="Azure Boards mirror: configure it, discover the client's process, check that the config fits it, "
                    "plan against the board, read it back and, when a named person confirms a plan, write to it. "
                    "Reads and plans by default; only `apply` and `link-pr` write to the board, only as a named "
                    "human, and only when posture is assisted.")
    sub = parser.add_subparsers(dest="verb", required=True)

    p = sub.add_parser("config", help="Start or check .sdlc/ado.yaml")
    config_sub = p.add_subparsers(dest="config_verb", required=True)
    q = config_sub.add_parser("init", parents=[common], help="Copy the starter config in (exit 1 if one exists)")
    q.add_argument("--force", action="store_true", help="Replace an existing config with the starter")
    config_sub.add_parser("check", parents=[common],
                          help="Report anything unsafe, unknown or unresolvable in the config, one finding per line")

    p = sub.add_parser("discover", parents=[common],
                       help="Read the Azure DevOps process and save .sdlc/ado/schema.json")
    p.add_argument("--team", default=None, metavar="T",
                   help="The team whose backlog levels and iterations to read (default: team in the config, "
                        "else the project's default team)")
    p.add_argument("--refresh", action="store_true",
                   help="Read again even if a schema for this team was read today")

    sub.add_parser("validate", parents=[common],
                   help="Check every configured kind resolves on the discovered process; print the fit table")

    p = sub.add_parser("plan", parents=[common],
                       help="The dry run: what each repository item would do on the board, and the plan hash")
    p.add_argument("--kind", action="append", metavar="K", choices=KINDS,
                   help=f"Only this kind (repeat for several): one of {', '.join(KINDS)}")
    p.add_argument("--id", action="append", metavar="ID",
                   help="Only this item: its id (0004, FE-03) or ref (sdlc:spec:0004); repeat for several")
    p.add_argument("--sprint", default=None, metavar="SNN", help="Only this sprint and the specs it holds")
    p.add_argument("--all", action="store_true", help="Every configured kind (also what no selector means)")
    p.add_argument("--validate", action="store_true",
                   help="Also check each row against the discovered process (locally; the board is not asked)")
    p.add_argument("--no-comments", action="store_true",
                   help="Draft no comment rows: the plan holds field ops only (an apply of a plan with a refused "
                        "comment, or one whose az identity is not --by, is refused whole; this is how to split them)")

    sub.add_parser("status", parents=[common],
                   help="What the ledger says, offline: linked, pending, drifted, as of when (no data is no data)")

    p = sub.add_parser("pull", parents=[common],
                       help="Read the ledgered items back and record what changed on the board")
    p.add_argument("--id", action="append", metavar="ID", help="Only this item (id, ref or #work item); repeatable")
    p.add_argument("--all", action="store_true", help="Every ledgered item (the default)")
    p.add_argument("--discussion", action="store_true",
                   help="Cache each item's comments (locally; ledger counts only) instead of reading its fields")
    p.add_argument("--full", action="store_true",
                   help="Forget the comment watermark and read every comment again; implies --discussion")
    p.add_argument("--propose-specs", action="store_true",
                   help="Also write ONE batch file under .sdlc/ado/local/proposals/ of argument lists (new_spec, then "
                        "link) for the board items nobody has mapped; nothing is run (not with --discussion)")

    p = sub.add_parser("drift", parents=[common],
                       help="Classify each ledgered item against the board (advisory; writes nothing)")
    p.add_argument("--id", action="append", metavar="ID", help="Only this item (id, ref or #work item); repeatable")
    p.add_argument("--kind", action="append", metavar="K", choices=KINDS,
                   help=f"Only this kind; repeatable: one of {', '.join(KINDS)}")

    p = sub.add_parser("sync", parents=[common],
                       help="The catch-up in one read: pull, drift, plan (and the discussion, only on --discussion); "
                            "sends nothing")
    p.add_argument("--kind", action="append", metavar="K", choices=KINDS,
                   help=f"Only this kind (repeat for several): one of {', '.join(KINDS)}")
    p.add_argument("--id", action="append", metavar="ID",
                   help="Only this item: its id (0004, FE-03), ref (sdlc:spec:0004) or #work item; repeat for several")
    p.add_argument("--sprint", default=None, metavar="SNN",
                   help="Plan only this sprint and the specs it holds (the pull still reads every ledgered item)")
    p.add_argument("--all", action="store_true", help="Every configured kind (also what no selector means)")
    p.add_argument("--discussion", action="store_true",
                   help="Also read and cache each item's comments (locally; ledger counts only). Only when asked for: "
                        "no other flag implies it, and sync has no --full")
    p.add_argument("--no-comments", action="store_true",
                   help="Draft no comment rows in the plan: it holds field ops only (the same flag as `plan`)")

    p = sub.add_parser("link", parents=[common], help="Map one repository item to a work item that exists")
    p.add_argument("ref", help="The repository item: sdlc:<kind>:<id>, e.g. sdlc:spec:0004")
    p.add_argument("--work-item", default=None, metavar="N", help="The work item's number (4521 or #4521; not AB#4521)")
    p.add_argument("--by", default=None, metavar="HUMAN", help=BY_HELP)

    p = sub.add_parser("adopt", parents=[common],
                       help="Map every repository item the board already tags (the ledger's `linked`)")
    p.add_argument("--all", action="store_true", help="Required: adopt every ref the board tags exactly once")
    p.add_argument("--by", default=None, metavar="HUMAN", help=BY_HELP)

    p = sub.add_parser("show", parents=[common],
                       help="A work item's cached discussion, every comment line quoted `  | `")
    p.add_argument("target", help="sdlc:<kind>:<id> (ledgered) or #<work item id>")
    p.add_argument("--fetch", action="store_true", help="Read the item's discussion from the board first")
    p.add_argument("--versions", action="store_true", help="Also read the edit history of every edited comment")
    p.add_argument("--expand", choices=["reactions"], default=None,
                   help="Also read reactions (not available in this version; says so)")
    p.add_argument("--for-agent", action="store_true",
                   help="Fence the text as observed content and withhold lines that read as instructions")

    p = sub.add_parser("discussion", help="Housekeeping for the local discussion cache")
    discussion_sub = p.add_subparsers(dest="discussion_verb", required=True)
    q = discussion_sub.add_parser("gc", parents=[common],
                                  help="Delete caches past discussion.retain_days and those of unlinked items")
    q.add_argument("--dry-run", action="store_true", help="List what would be deleted; delete nothing")

    p = sub.add_parser("apply", parents=[common],
                       help="Send the plan a person confirmed to the board, as that person (posture assisted only)")
    p.add_argument("--confirm", default=None, metavar="HASH",
                   help="The 12-hex hash `plan` printed for the plan you read; a plan nobody confirmed is never sent")
    p.add_argument("--by", default=None, metavar="HUMAN", help=BY_HELP)
    p.add_argument("--limit", type=int, default=None, metavar="N",
                   help="Send at most N writes this run, comments counted (a first --all seed over "
                        "limits.first_seed needs it); apply the same plan again for the rest")

    p = sub.add_parser("link-pr", parents=[common],
                       help="Link a pull request to a spec's work item (posture assisted only)")
    p.add_argument("--spec", default=None, metavar="NNNN", help="The spec's id (0004, or 4); it must be ledgered here")
    p.add_argument("--pr", default=None, metavar="N", help="The pull request's number (12, or !12)")
    p.add_argument("--by", default=None, metavar="HUMAN", help=BY_HELP)

    p = sub.add_parser("iteration", help="Bind sprints to the board's iterations")
    iteration_sub = p.add_subparsers(dest="iteration_verb", required=True)
    q = iteration_sub.add_parser("bind", parents=[common],
                                 help="Bind a sprint to an iteration path the discovered schema has (edits "
                                      ".sdlc/ado.yaml; the board is not asked)")
    q.add_argument("sprint", metavar="SNN", help="The sprint id (S07)")
    q.add_argument("--path", default=None, metavar="P",
                   help="The iteration path as the discovered schema spells it (Claims\\Sprint 7)")
    q.add_argument("--by", default=None, metavar="HUMAN", help=BY_HELP)

    p = sub.add_parser("posture", parents=[common],
                       help="Switch this clone between plan-only and assisted (edits .sdlc/ado.yaml)")
    p.add_argument("value", choices=POSTURES, help="plan-only never writes to the board; assisted offers apply")
    p.add_argument("--by", default=None, metavar="HUMAN", help=BY_HELP)

    p = sub.add_parser("comment", parents=[common],
                       help="Draft one comment as a one-row plan file; nothing is sent until `apply --confirm`")
    p.add_argument("target", help="sdlc:<kind>:<id> (ledgered) or #<work item id>")
    p.add_argument("--message", default=None, metavar="TEXT",
                   help="The comment's text. Write --message=<text> (one argument) so a text that starts with a dash "
                        "is not read as a flag")
    p.add_argument("--by", default=None, metavar="HUMAN", help=BY_HELP)
    p.add_argument("--mention", action="append", metavar="@h",
                   help="A person to name, as @handle (repeatable); it is text only and will not notify")
    p.add_argument("--event", default=None, metavar="NAME",
                   help="Label the comment as one of the comment events (handoff, spec_deferred, ...); "
                        "a name outside that set is refused")

    p = sub.add_parser("reconcile", parents=[common],
                       help="Settle one drift row `pull` recorded: take the board's value through the verb that owns "
                            "it (ado), keep the repository's (sdlc), acknowledge it (ack) or say it is not drift")
    p.add_argument("ref", help="The repository item: sdlc:<kind>:<id>, e.g. sdlc:spec:0004")
    p.add_argument("--field", default=None, metavar="F",
                   help="The drifted field as `pull` printed it (System.AssignedTo); leave it out for a row about the "
                        "item itself (DELETED_IN_ADO, ORPHAN_IN_REPO)")
    p.add_argument("--take", default=None, choices=list(model.RECONCILE_TAKES),
                   help="ado: run the verb that owns the field (a spec's assignee or sprint, a decision's close; never "
                        "a spec's State) | sdlc: keep the repository's value, the next apply puts it back | ack: "
                        "someone knows (needs --owner) | not-drift: it is not drift (needs --reason)")
    p.add_argument("--by", default=None, metavar="HUMAN", help=BY_HELP)
    p.add_argument("--owner", default=None, metavar="HUMAN",
                   help="With --take ack: the named person who owns the row from here (an AI or an agent is refused)")
    p.add_argument("--reason", default=None, metavar="TEXT",
                   help="With --take not-drift: why it is not drift. With --take ado on a decision: what was decided "
                        "(typed by a person, never filled in). With --take ado when the board moved a spec out of "
                        "every sprint: why it leaves the slate")
    p.add_argument("--from-comment", default=None, metavar="ID",
                   help="With --take ado on a decision: show that cached comment (`pull --discussion` cached it) as a "
                        "suggested resolution for you to type or edit; it is never filled in, so the decision closes "
                        "only with the --reason you typed, and the ledger keeps the comment's id, never its words")
    return parser


VERBS: dict[str, Callable[[argparse.Namespace, Path], int]] = {
    "config": cmd_config, "discover": cmd_discover, "validate": cmd_validate, "plan": cmd_plan,
    "status": cmd_status, "pull": cmd_pull, "drift": cmd_drift, "link": cmd_link, "adopt": cmd_adopt,
    "show": cmd_show, "discussion": cmd_discussion, "apply": cmd_apply, "link-pr": cmd_link_pr,
    "iteration": cmd_iteration, "posture": cmd_posture, "comment": cmd_comment, "reconcile": cmd_reconcile,
    "sync": cmd_sync,
}


def _read_unavailable(args, verb: str, reason: str) -> int:
    """A read verb that could not answer for a reason that is not the board's (a ledger it cannot read, a file it
    could not write): `unavailable: <reason>` and exit 0 (house rule 4: reads exit 0 always)."""
    flag = True if verb in BOOL_UNAVAILABLE_VERBS else reason   # `sync` says true, the sentence is in `reason`
    payload = {"ok": True, "unavailable": flag, "reason": reason, **UNAVAILABLE_EXTRA.get(verb, {})}
    _emit(args, payload, f"Azure Boards mirror: {verb}\nunavailable: {reason}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = resolve_repo_root(args)
    if repo_root is None:
        return _error(args, f"state file not found: {args.state}", 1)
    reading = args.verb in READ_VERBS
    try:
        return VERBS[args.verb](args, repo_root)
    except Refused as exc:
        return _error(args, str(exc), 2)
    except Usage as exc:
        return _error(args, str(exc), 1)
    except Illegal as exc:  # LedgerUnreadable is one: on a read verb it is `unavailable`, never a failure
        return _read_unavailable(args, args.verb, str(exc)) if reading else _error(args, str(exc), 1)
    except cfgmod.ConfigError as exc:
        if reading:
            return _read_unavailable(args, args.verb, _tidy(exc))
        return _error(args, str(exc), 2 if exc.kind == "refused" else 1)
    except AdoImportError as exc:
        if reading:
            return _unavailable(args, repo_root, args.verb, _tidy(exc), host_error=str(exc),
                                **UNAVAILABLE_EXTRA.get(args.verb, {}))
        return _error(args, str(exc), 1)
    except LedgerDrift as exc:  # house rule 7 on every write verb, `pull` and `discussion gc`; the other reads exit 0
        code = 1 if args.verb not in READ_VERBS or args.verb in ("pull", "sync") else 0  # their DRIFT is the only exit 1
        if args.json:
            return _error(args, str(exc), code)
        print(exc)  # `DRIFT: ...` leads the line, as in sprint.py
        return code


if __name__ == "__main__":
    sys.exit(main())
