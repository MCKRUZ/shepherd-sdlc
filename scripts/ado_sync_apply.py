"""Apply a confirmed plan to the Azure Boards board: the one place Shepherd writes outside the repository (B3-P2).

`apply_plan(repo_root, plan, *, by, cfg, schema, limit, today)` sends the rows of a plan file (`.sdlc/ado/local/plans/
<hash>.json`, written by `ado_sync.py plan` and echoed back by a person as `apply --confirm <hash>`) and nothing
else. It writes to the board AS the person whose `az` login is active, so every guard here is mechanical, never a label:

  * Whole-plan refusals (the result's `refused_reason`, exit 2, NOTHING sent, in this order): an AI or agent `--by`
    (`ai_actor`), posture other than `assisted` (`posture`), a forbidden effort field in the plan (`forbidden_field`),
    a comment row refused while drafting or that no longer fits (`budget`, `max_chars`, `email_in_text`, ...), the
    first `--all` seed over `limits.first_seed` without a `--limit` in range (`first_seed`), and — read FIRST, before
    any other az call, whenever a comment row is to be sent — an executing identity that is not `--by`
    (`identity_mismatch`; `identity_unknown` for a service principal, an account off the roster, a `--by` that is not
    a roster @handle, or a `connectionData` read that failed). A plan with an update (or a History-transport comment)
    and no comment to post reads `connectionData` first too, but only to learn whether `az rest` can sign in: an
    update is an `az rest` PATCH (`az devops invoke` cannot PATCH a work item; B0 write fixes, 2026-10-15) and needs
    an Entra sign-in, so a failed read is `identity_unknown` (a personal access token alone), and a sign-in that is
    not `--by` is not refused for it. A plan that does not hash to its own id was edited after it was confirmed: that
    is a `ValueError`, as is a blank `--by` or one carrying an address.
  * Field ops, then comments. Creates run outcome -> domain -> requirement -> epic -> feature -> spec (parents before
    children whatever order the file lists them in) and the parent link rides in the child's own PATCH; a child whose
    parent was not created is reported (`deferred`, `parent_failed`), never created without it. An update is guarded by
    the revision the plan showed: a board that moved on, a repository that changed, or a PATCH the board rejects
    (`test /rev`) is a `conflict` row — skipped, ledgered, and the next op runs. `rule` and `not_found` continue
    (D16); `permission`, `throttled`, an unknown outcome and `DRIFT` stop the run (every later row is deferred
    `stopped`). A `rule` row names the patch field it was about when the board's answer says (`field`, and `reason`
    `unknown_identity` or `value_not_allowed`): an assignee the organisation does not know fails its own row only.
    Every create sets the config's `area_path` (`System.AreaPath`, create-time only). `--limit` and
    `limits.writes_per_run` count every write, comments included. A comment moves its item's `rev`, so an item this
    run commented on is re-read before anything here PATCHes it again.
  * A comment POST whose outcome is unknown (a timeout, an unreadable answer) is never retried: the item's newest 20
    comments are re-listed and the one carrying the row's `text_sha`, by the same identity, within 10 minutes is
    ledgered `commented{recovered: true}`; no match stops the run.
  * A ledger line follows each write (`applied`, `commented`, `conflict`, `refused`), built by
    `ado_sync_model.ledger_entry`. A failed append prints `DRIFT: ...` to stderr and the row is reported with class
    `drift` (the write landed, the record did not) and the run stops. A row done earlier under the same plan is
    skipped, so re-running a plan (or running its second chunk) never doubles an item or a comment.

Rows it reads. A `create` or `update` row is the one `ado_sync.py plan` writes: `ref`, `kind`, `type`,
`projection_hash`, `ops` (what the plan showed), `parent` ({ref, work_item, state}), `source_path`, and for an update
the `work_item` and `rev` the plan read. The repository's projection is rebuilt here and must still hash to the row's
`projection_hash`, so what is sent is what was shown. A `comment` row is the one `ado_sync_comments` drafts (`status`
draft, skipped or refused); only a draft is sent, its text with the `comments.trailer` mode's trailer appended, `plan`
being this plan's id. Any other row (link, held, unmapped, ...) sends nothing. The caller owns comparing `--confirm`
with `plan["plan"]`, and `plan["scope"]["all"]` is what makes a plan a first seed. A failed row also carries a fixed
`detail` sentence and, where it helps, a `reason` token (`rev_moved`, `source_changed`, `already_linked`, ...); a
result row never holds `az` text.

Never sent, and no code path builds them: an option that silences followers, skips the process's rules or only
validates, a delete, an edit of a comment, a reaction, an attachment, a follow, a Related link (only the parent edge
is written here), or a text field outside the sdlc markers. Nothing under `specs/` or outside `.sdlc/` is written.
Nothing spawns `az` here: every call goes through `ado_wit` and so through the one transport seam.

Both modes (CLAUDE.md design rule):
  * Workflow mode — `ado_sync.py apply --confirm <hash> --by <human> --state .sdlc/state.yaml` loads the plan file,
    `.sdlc/ado.yaml` and `.sdlc/ado/schema.json` and passes them in; the ledger is `.sdlc/metrics/ado-sync-log.jsonl`.
  * Standalone — a test or script passes any repository root, a plan document `{"plan": <12hex>, "rows": [...],
    "scope": {...}}`, a config and a schema as plain dicts. No `state.yaml` is read; a missing `.sdlc/` is created
    for the ledger.

`today` is a date, or an aware datetime that is then the clock for every ledger `ts` and for the recovery window; with
a plain date the clock is `ado_schema.now_utc()`, the seam every verb reads. The result is
`ado_sync_model.apply_result`: `{"applied", "failed", "deferred", "refused_reason", "exit"}`; a row carries ids and
fixed sentences only — never `az` text, an address or a GUID. Raises `ValueError` before anything is sent for a
malformed plan, `--by` or limit, and `AdoImportError` when the board cannot be read before the first write.
"""

import hashlib
import html
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Final

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ado_discussion_cache as cache  # noqa: E402
import ado_schema  # noqa: E402
import ado_schema_map as sm  # noqa: E402
import ado_sync_model as model  # noqa: E402
import ado_sync_sources as sources  # noqa: E402
import ado_sync_sources_tree  # noqa: E402,F401  (registers outcome, domain, requirement and the epic parent)
import ado_transport  # noqa: E402
import ado_wit  # noqa: E402
import ado_wit_map as wm  # noqa: E402
import boards_contract as bc  # noqa: E402
import validate_team  # noqa: E402
from ado_map import AdoImportError  # noqa: E402
from sprint_model import is_forbidden_field  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
AGENT_STEMS: Final[frozenset[str]] = frozenset(p.stem for p in (PLUGIN_ROOT / "agents").glob("*.md"))

DEFAULT_WRITES_PER_RUN: Final = 50   # limits.writes_per_run
DEFAULT_FIRST_SEED: Final = 20       # limits.first_seed
DEFAULT_BUDGET: Final = 50           # comments.per_item_budget
DEFAULT_MAX_CHARS: Final = 4000      # comments.max_chars
LEDGER_STAMP: Final = "%Y-%m-%dT%H:%MZ"
FIELDS_PREFIX: Final = "/fields/"
FIELD_ACTIONS: Final = ("create", "update")
LINKING_EVENTS: Final = ("linked", "adopted", "applied")
PARENT_STATES: Final = ("linked", "in this plan")   # a plan row's `parent.state` that names a work item to link under
_GIT_SHA: Final = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")

# What a failed row says, by class: fixed sentences, never the board's own words (they can name people).
DETAIL: Final[dict[str, str]] = {
    "conflict": "nothing was written for this row: the board, the ledger or the repository no longer matches what the "
                "plan showed (see reason), or the board refused the change as stale; plan again",
    "rule": "the board's process refused a value or a transition; fix the field or the process, then plan again",
    "permission": "the signed-in identity may not write here; the run stopped",
    "throttled": "the board is rate-limiting this identity; the run stopped, plan again later",
    "not_found": "the item, or what it points at, is no longer on the board; nothing was written for this row",
    "unknown": "the outcome is unknown (a timeout or an unreadable answer) and the run stopped; the write may have "
               "landed, so plan again before applying",
    "drift": "DRIFT: the write landed but the ledger append failed, so the record and the board now disagree; the run "
             "stopped, plan again once the ledger is writable",
}
# A `rule` failure that `ado_wit_map.describe_write_error` could tie to a field of the patch says which one (a reference
# name the patch carried, never the board's words). `{field}` is that name, or "a field" when none could be told.
RULE_DETAIL: Final[dict[str | None, str]] = {
    "unknown_identity": "the board does not know the identity given for {field} (the roster e-mail is not a user of "
                        "this organisation); fix people[].email in .sdlc/team.yaml or leave the item unassigned, then "
                        "plan again; the other rows went on",
    "value_not_allowed": "the board's process does not allow the value given for {field}; fix the mapping in "
                         ".sdlc/ado.yaml or the process, then plan again",
    None: "the board's process refused the value of {field} or a transition; fix the field or the process, then plan "
          "again",
}


def needs_rest_writes(rows: list[dict], cfg: dict) -> bool:
    """True when sending these plan rows would PATCH a work item through `az rest` — an update row, or a drafted comment
    under the History transport — which needs an Entra sign-in (a personal access token alone cannot mint the token;
    B0 write fixes, 2026-10-15). Creates and comments-API posts go through `az devops invoke` and need none."""
    block = cfg.get("comments") if isinstance(cfg, dict) and isinstance(cfg.get("comments"), dict) else {}
    history = block.get("transport") == "history"
    return any(isinstance(r, dict) and (r.get("action") == "update"
                                        or (history and r.get("action") == "comment" and r.get("status") == "draft"))
               for r in rows or [])


# --- the plan, the ledger, the clock ------------------------------------------------------------------------------

def _is_count(value) -> bool:
    return type(value) is int and value >= 1


def _plan_parts(plan) -> tuple[str, list[dict]]:
    """`(plan id, rows)` of a plan document, or a ValueError: the rows must hash to the id a person confirmed."""
    if not isinstance(plan, dict):
        raise ValueError("the plan must be the plan document: {'plan': <12hex>, 'rows': [...]}")
    plan_id, rows = plan.get("plan"), plan.get("rows")
    if not (isinstance(plan_id, str) and bc.HASH_RE.fullmatch(plan_id)):
        raise ValueError("the plan document has no 12-hex plan id")
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ValueError("the plan's rows must be a list of row documents")
    if model.plan_hash(rows) != plan_id:
        raise ValueError("the plan's rows do not hash to its id (hash mismatch): the file was edited after it was "
                         "planned; plan again and confirm the new hash")
    return plan_id, rows


def _by(by) -> str:
    clean = str(by or "").strip()
    if not clean:
        raise ValueError("--by is required: a named human")
    try:
        model.ledger_entry("2026-01-01T00:00Z", "refused", by=clean)   # what a ledger line would refuse, refused now
    except ValueError as exc:
        raise ValueError(f"--by cannot be recorded: {exc}") from None
    return clean


def _limit(limit) -> int | None:
    if limit is None:
        return None
    if not _is_count(limit):
        raise ValueError(f"--limit must be a positive integer, not {limit!r}")
    return limit


def _clock(today):
    if isinstance(today, datetime):
        if today.tzinfo is None:
            raise ValueError("today must be timezone-aware when it is a datetime")
        return lambda: today.astimezone(timezone.utc)
    if isinstance(today, date):
        return ado_schema.now_utc
    raise ValueError("today must be a date or an aware datetime")


def _read_ledger(root: Path) -> list[dict]:
    """The ledger's lines in append order. A line that is not a ledger line stops the apply before anything is sent:
    the idempotency checks (what is already posted or linked) cannot be made on a ledger that cannot be read."""
    try:
        text = (root / bc.LEDGER).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise ValueError(f"{bc.LEDGER} could not be read ({type(exc).__name__}); nothing was sent") from None
    out = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except (ValueError, RecursionError):
            entry = None
        if not isinstance(entry, dict) or any(entry.get(k) is not None and not isinstance(entry[k], str)
                                              for k in ("event", "ref", "plan")):
            raise ValueError(f"{bc.LEDGER} line {number} is not a ledger line; repair it by hand (nothing was sent)")
        out.append(entry)
    return out


def _append(root: Path, entry: dict) -> None:
    path = root / bc.LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _links(ledger: list[dict]) -> dict[str, dict]:
    """`ref` -> its last linking line (`linked`, `adopted`, `applied` with an integer `work_item`); an UNLINK
    `reconciled` line for the whole item takes it out (the rule `ado_sync.linked_items` and `summarize` count by)."""
    out: dict[str, dict] = {}
    for e in ledger:
        event, ref = e.get("event"), e.get("ref")
        if event not in model.LEDGER_EVENTS or not isinstance(ref, str) or not ref:
            continue
        if event in LINKING_EVENTS and _is_count(e.get("work_item")):
            out[ref] = e
        elif (event == "reconciled" and ref in out and not e.get("field")
              and str(e.get("disposition") or "").strip().upper().replace("-", "_") == "UNLINK"):
            del out[ref]
    return out


def _roster_emails(root: Path) -> dict[str, str]:
    try:
        data = yaml.safe_load((root / ".sdlc" / "team.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return {}
    return validate_team.people_by_email(data if isinstance(data, dict) else {})


def _head_commit(root: Path) -> str | None:
    """The checked-out commit, read from the `.git` files (no process is spawned), or None. Follows a worktree's
    `gitdir:` pointer and its `commondir`, a symbolic HEAD, a loose ref and `packed-refs`."""
    try:
        git = root / ".git"
        if git.is_file():
            text = git.read_text(encoding="utf-8").strip()
            if not text.startswith("gitdir:"):
                return None
            git = (root / text[len("gitdir:"):].strip()).resolve()
        homes = [git]
        if (git / "commondir").is_file():
            homes.append((git / (git / "commondir").read_text(encoding="utf-8").strip()).resolve())
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head if _GIT_SHA.fullmatch(head) else None
        ref = head[len("ref:"):].strip()
        for home in homes:
            loose = home / ref
            if loose.is_file():
                sha = loose.read_text(encoding="utf-8").strip()
                return sha if _GIT_SHA.fullmatch(sha) else None
            packed = home / "packed-refs"
            if packed.is_file():
                for line in packed.read_text(encoding="utf-8").splitlines():
                    sha, _, name = line.partition(" ")
                    if name.strip() == ref and _GIT_SHA.fullmatch(sha):
                        return sha
    except (OSError, UnicodeDecodeError):
        return None
    return None


def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]


def _field_refs(patch: list[dict]) -> list[str]:
    paths = (str(op.get("path", "")) for op in patch)
    return sorted({path[len(FIELDS_PREFIX):] for path in paths if path.startswith(FIELDS_PREFIX)})


def _history_html(text: str) -> str:
    """A comment as the History field's HTML: escaped, one `<br>` per line."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "<div>" + "<br>".join(html.escape(line) for line in lines) + "</div>"


# --- reading the plan -----------------------------------------------------------------------------------------------

def _check_field_row(row: dict) -> None:
    ref = row.get("ref")
    if not (isinstance(ref, str) and bc.REF_RE.fullmatch(ref)):
        raise ValueError(f"a {row['action']} row has no sdlc:<kind>:<id> ref ({ref!r})")
    for key in ("kind", "type"):
        if not (isinstance(row.get(key), str) and row[key].strip()):
            raise ValueError(f"{ref}: a {row['action']} row needs a {key}")
    if not (isinstance(row.get("projection_hash"), str) and bc.HASH_RE.fullmatch(row["projection_hash"])):
        raise ValueError(f"{ref}: the row has no projection_hash")
    if row["action"] == "update" and not (_is_count(row.get("work_item")) and _is_count(row.get("rev"))):
        raise ValueError(f"{ref}: an update row needs the work item and the revision the plan showed")


def _check_comment_row(row: dict) -> None:
    status = row.get("status")
    if status not in ("draft", "skipped", "refused"):
        raise ValueError(f"a comment row has status {status!r}, not draft, skipped or refused")
    if status == "refused":
        if row.get("reason") not in bc.COMMENT_REFUSALS:
            raise ValueError(f"a refused comment row has reason {row.get('reason')!r}, not a COMMENT_REFUSALS member")
        return
    if status == "skipped":
        return
    ref, wid, text = row.get("ref"), row.get("work_item"), row.get("text")
    if ref is not None and not (isinstance(ref, str) and bc.REF_RE.fullmatch(ref)):
        raise ValueError(f"a comment row's ref {ref!r} is not an sdlc:<kind>:<id> ref")
    if not _is_count(wid):
        raise ValueError("a comment row needs the work item it goes on")
    if not (isinstance(text, str) and text.strip()):
        raise ValueError("a comment row needs its text")
    if row.get("format") not in ("markdown", "html") or row.get("trailer") not in model.TRAILER_MODES:
        raise ValueError("a comment row needs a format (markdown or html) and a trailer mode")
    for key in ("idem_key", "text_sha"):
        if not (isinstance(row.get(key), str) and row[key]):
            raise ValueError(f"a comment row needs its {key}")
    if not bc.HASH_RE.fullmatch(row["text_sha"]) or model.text_sha(text) != row["text_sha"]:
        raise ValueError("a comment row's text_sha does not match its text")


def _kind_rank(kind: str) -> int:
    if kind in bc.TREE_ORDER:
        return bc.TREE_ORDER.index(kind)
    return len(bc.TREE_ORDER) + (bc.KINDS.index(kind) if kind in bc.KINDS else len(bc.KINDS))


def _in_tree_order(rows: list[dict]) -> list[dict]:
    """Field rows by `TREE_ORDER` (stable within a kind), with any row's in-plan parent moved in front of it."""
    base = sorted(rows, key=lambda r: _kind_rank(r["kind"]))
    creating = {r["ref"]: r for r in base if r["action"] == "create"}
    out: list[dict] = []
    seen: set[str] = set()

    def visit(row: dict) -> None:
        if row["ref"] in seen:
            return
        seen.add(row["ref"])
        parent = row.get("parent")
        if row["action"] == "create" and isinstance(parent, dict) and parent.get("state") == "in this plan":
            first = creating.get(parent.get("ref"))
            if first is not None:
                visit(first)
        out.append(row)

    for row in base:
        visit(row)
    return out


def _forbidden(rows: list[dict], schema: dict) -> bool:
    """A plan that carries an effort field is refused whole: the plan marks such a row `refused`, and any op on a
    `Microsoft.VSTS.Scheduling.*` field, a field the process names as effort, or an activity metric is the same."""
    refused = {ref.lower() for ref in sm.refused_fields(schema)}
    prefixes = tuple(p.lower() for p in model.FORBIDDEN_FIELD_PREFIXES)
    for row in rows:
        if row.get("action") == "refused":
            return True
        if row.get("action") not in FIELD_ACTIONS:
            continue
        for op in row.get("ops") or []:
            path = op.get("path") if isinstance(op, dict) else None
            if isinstance(path, str) and path.startswith(FIELDS_PREFIX):
                ref = path[len(FIELDS_PREFIX):]
                low = ref.lower()
                if low in refused or low.startswith(prefixes) or is_forbidden_field(ref.rsplit(".", 1)[-1]):
                    return True
    return False


def _setting(block, key: str, default: int) -> int:
    value = block.get(key) if isinstance(block, dict) else None
    return value if _is_count(value) else default


def _first_seed_refusal(plan: dict, rows: list[dict], ledger: list[dict], cfg: dict, limit: int | None) -> str | None:
    """A seed is no longer the first once an item was created or updated here: an `applied` line of another action
    (`link-pr`'s `link_pr`, which creates nothing) leaves the `limits.first_seed` guard in place."""
    scope = plan.get("scope")
    if not (isinstance(scope, dict) and scope.get("all") is True) or any(
            e.get("event") == "applied" and e.get("action") in FIELD_ACTIONS for e in ledger):
        return None
    seed = _setting(cfg.get("limits"), "first_seed", DEFAULT_FIRST_SEED)
    creates = sum(1 for r in rows if r.get("action") == "create")
    return "first_seed" if creates > seed and (limit is None or limit > seed) else None


# --- the run --------------------------------------------------------------------------------------------------------

class _Run:
    """One apply: what has been sent, what the ledger says, and what the board said back."""

    def __init__(self, root: Path, plan_id: str, by: str, cfg: dict, schema: dict, now, ledger: list[dict]):
        self.root, self.plan, self.by, self.cfg, self.schema, self.now = root, plan_id, by, cfg, schema, now
        self.ledger = ledger
        self.links = _links(ledger)
        self.commented = set(model.commented_keys(ledger))
        self.emails = _roster_emails(root)
        self.executed_as, self.me_id = "unknown", None
        self.applied: list[dict] = []
        self.failed: list[dict] = []
        self.deferred: list[dict] = []
        self.writes, self.stopped, self.drift_said = 0, False, False
        self.cap, self.cap_why = 0, "writes_per_run"
        self.created: dict[str, int] = {}   # ref -> the work item this run created
        self.revs: dict[int, int] = {}      # work item -> the revision this run knows it is at
        # work items this run posted a comment on through the comments API: a comment bumps the item's `rev` and its
        # answer does not say to what (B0, 2026-10-15: rev 2 -> 3), so a later PATCH here re-reads the rev first
        self.rev_stale: set[int] = set()
        self.items: dict[int, dict] = {}
        self.projs: dict[str, dict] = {}
        self.remote_info = None
        self.commit = None
        block = cfg.get("comments")
        self.comments = block if isinstance(block, dict) else {}
        self.transport = self.comments.get("transport") if self.comments.get("transport") in model.COMMENT_TRANSPORTS \
            else "comments-api"

    # -- the ledger
    def _stamp(self) -> str:
        return self.now().strftime(LEDGER_STAMP)

    def _line(self, event: str, fields: dict) -> Exception | None:
        try:
            entry = model.ledger_entry(self._stamp(), event, **fields)
            _append(self.root, entry)
        except (OSError, ValueError) as exc:
            return exc
        self.ledger.append(entry)
        return None

    def record(self, event: str, **fields) -> bool:
        """Append one line after something landed. A failed append is DRIFT: said once, and the run stops."""
        failure = self._line(event, {**fields, "by": self.by, "executed_as": self.executed_as, "plan": self.plan})
        if failure is None:
            return True
        if not self.drift_said:
            self.drift_said = True
            reason = failure.strerror if isinstance(failure, OSError) and failure.strerror else type(failure).__name__
            print(f"DRIFT: the ledger append failed ({bc.LEDGER}: {reason}); what was just sent to the board is not "
                  "recorded here. Stopping; plan again once the ledger is writable.", file=sys.stderr)
        self.stopped = True
        return False

    def refuse(self, reason: str) -> dict:
        """The whole plan is refused and nothing was sent. The refusal is recorded if it can be; that never fails it."""
        fields = {"plan": self.plan, "reason": reason}
        if reason != "ai_actor":
            fields["by"] = self.by
        self._line("refused", fields)
        return model.apply_result(refused_reason=reason)

    # -- rows
    def _ref_fields(self, row: dict, action: str, **extra) -> dict:
        out = {"ref": row.get("ref"), "action": action, **extra}
        if row.get("ref") is None:
            out["work_item"] = row.get("work_item")
        return out

    def fail(self, row: dict, action: str, cls: str, *, wid=None, reason: str | None = None,
             field: str | None = None) -> None:
        detail = DETAIL[cls]
        if cls == "rule" and (reason or field):   # say which field, in fixed words (B0 write fixes, 2026-10-15)
            detail = RULE_DETAIL.get(reason, RULE_DETAIL[None]).format(field=field or "a field")
        out = {"ref": row.get("ref"), "action": action, "work_item": wid, "class": cls, "detail": detail}
        if reason:
            out["reason"] = reason
        if field:
            out["field"] = field
        self.failed.append(out)

    def defer(self, row: dict, action: str, why: str) -> None:
        self.deferred.append(self._ref_fields(row, action, why=why))

    def conflict(self, row: dict, action: str, wid, why: str, **extra) -> None:
        self.record("conflict", ref=row.get("ref"), kind=row.get("kind"), work_item=wid, rev_before=row.get("rev"),
                    why=why, **extra)
        self.fail(row, action, "conflict", wid=wid, reason=why)

    def write_failed(self, row: dict, action: str, wid, exc: AdoImportError, patch: list[dict] | None = None) -> None:
        cls = getattr(exc, "error_class", None)
        cls = cls if cls in model.WRITE_ERROR_CLASSES else "unknown"
        if cls == "conflict":
            return self.conflict(row, action, wid, "write_conflict")
        said = wm.describe_write_error(str(exc), _field_refs(patch)) if cls == "rule" and patch else {}
        self.fail(row, action, cls, wid=wid, reason=said.get("reason"), field=said.get("field"))
        if cls in model.STOP_CLASSES or cls in model.RECOVER_CLASSES:
            self.stopped = True

    def gate(self, row: dict, action: str) -> bool:
        """True when the row may be sent: the run has not stopped and the write cap has room."""
        if self.stopped:
            self.defer(row, action, "stopped")
            return False
        if self.writes >= self.cap:
            self.defer(row, action, self.cap_why)
            return False
        return True

    # -- before the first write
    def read_identity(self, *, bind: bool = True) -> str | None:
        """Who `az` is signed in as, read before any other az call. The refusal reason, or None when it is `--by`.

        `bind=False` is the read a plan with updates (or History comments) but no comment to post makes: an update is
        an `az rest` PATCH, which needs the same Entra token this `az rest` read needs, so a read that fails refuses the
        plan as `identity_unknown` (under a personal access token alone nothing could be updated); a read that works is
        not held to `--by` (an update writes no words in anybody's name), and changes nothing (B0 write fixes)."""
        try:
            me = model.executing_identity(ado_wit.connection_data(self.root), self.emails)
        except (AdoImportError, ValueError):
            return "identity_unknown"
        if not bind:
            return None
        try:
            cache.save_me(self.root, me["handle"], me["id"], self._stamp())
        except (OSError, ValueError):
            pass
        self.me_id = me["id"]
        by_handle = self.by if bc.HANDLE_RE.fullmatch(self.by) else None
        reason = "identity_unknown" if me["service_principal"] else model.identity_refusal(by_handle, me["handle"])
        if reason is None:
            self.executed_as = me["handle"]
        return reason

    def comment_refusal(self, rows: list[dict], drafts: list[dict]) -> str | None:
        for row in rows:
            if row.get("action") == "comment" and row.get("status") == "refused":
                return row["reason"]
        used: dict[int, int] = {}
        budget = _setting(self.comments, "per_item_budget", DEFAULT_BUDGET)
        for row in drafts:
            if row["idem_key"] in self.commented:
                continue
            wid = row["work_item"]
            count = used.get(wid, model.budget_used(self.ledger, wid))
            reason = model.comment_refusal(row["text"], by=self.by, agent_stems=AGENT_STEMS, event=row.get("event"),
                                           max_chars=_setting(self.comments, "max_chars", DEFAULT_MAX_CHARS),
                                           trailer=row["trailer"], budget_used=count, budget=budget)
            if reason:
                return reason
            used[wid] = count + 1
        return None

    def prepare(self, field_rows: list[dict], drafts: list[dict]) -> None:
        """Everything the writes need that is a read: the repository's current projections, the board's current
        revisions (one batch per 200 ids) and the commit the hyperlinks name. Nothing has been written yet."""
        if field_rows:
            self.remote_info = ado_transport.remote(self.root)
            kinds = [k for k in dict.fromkeys(r["kind"] for r in field_rows) if k in sources.SOURCES]
            for proj in sources.projections(self.root, self.cfg, self.schema, kinds) if kinds else []:
                proj["tags"] = set(proj["tags"]) | {f"{wm.REPO_TAG_PREFIX}{self.remote_info.repo}"}
                self.projs[proj["ref"]] = proj
            if any(r["action"] == "create" for r in field_rows):
                self.commit = _head_commit(self.root)
        wanted = [r["work_item"] for r in field_rows if r["action"] == "update"]
        if self.transport == "history":
            wanted += [r["work_item"] for r in drafts]
        wanted = list(dict.fromkeys(wanted))
        if wanted:
            rows, _missing = ado_wit.get_batch(self.root, wanted)
            for raw in rows:
                if isinstance(raw, dict) and raw.get("id") in wanted:
                    item = wm.remote_item(raw, self.emails)
                    self.items[item["id"]] = item
                    self.revs[item["id"]] = item["rev"]

    # -- the writes
    def done_under_this_plan(self, ref: str) -> bool:
        link = self.links.get(ref)
        return bool(link and link.get("event") == "applied" and link.get("plan") == self.plan)

    def hyperlink(self, row: dict) -> str:
        if self.commit:
            try:
                return wm.file_hyperlink(self.remote_info, row.get("source_path"), self.commit)
            except ValueError:
                pass
        return self.remote_info.web_url

    def parent_url(self, row: dict) -> tuple[str | None, bool]:
        """`(the parent's work item URL | None, ok)`; not ok when the parent should exist and does not."""
        parent = row.get("parent")
        if not isinstance(parent, dict) or parent.get("state") not in PARENT_STATES:
            return None, True
        ref = parent.get("ref")
        wid = self.created.get(ref) or (self.links.get(ref) or {}).get("work_item")
        if not _is_count(wid):
            return None, False
        return wm.work_item_url(self.remote_info, wid), True

    def create(self, row: dict) -> None:
        ref = row["ref"]
        if ref in self.links:
            if not self.done_under_this_plan(ref):
                self.conflict(row, "create", None, "already_linked")
            return
        if not self.gate(row, "create"):
            return
        proj = self.projs.get(ref)
        if proj is None or model.projection_hash(proj) != row["projection_hash"]:
            return self.conflict(row, "create", None, "source_changed")
        parent_url, parent_ok = self.parent_url(row)
        if not parent_ok:
            return self.defer(row, "create", "parent_failed")
        history = (f"{bc.HISTORY_TOKEN} · created · by {self.by} · executed as {self.executed_as} · "
                   f"plan {self.plan} · {row.get('source_path')}")
        try:
            patch = wm.build_create_patch(proj, self.schema, self.hyperlink(row), history, parent_url,
                                          area_path=wm.configured_area(self.cfg))
        except ValueError:
            return self.conflict(row, "create", None, "unbuildable")
        self.writes += 1
        try:
            out = ado_wit.create(self.root, row["type"], patch)
        except AdoImportError as exc:
            return self.write_failed(row, "create", None, exc, patch)
        except ValueError:                       # refused before any call was made
            self.writes -= 1
            return self.conflict(row, "create", None, "unbuildable")
        wid, rev = out["id"], out["rev"]
        self.created[ref] = wid
        self.revs[wid] = rev
        if not self.record("applied", ref=ref, kind=row["kind"], action="create", work_item=wid, rev_before=None,
                           rev_after=rev, fields=_field_refs(patch), type=row["type"],
                           projection_hash=row["projection_hash"], argv_sha=_sha(patch)):
            return self.fail(row, "create", "drift", wid=wid)
        self.links[ref] = self.ledger[-1]
        self.applied.append({"ref": ref, "action": "create", "work_item": wid, "rev_after": rev})

    def update(self, row: dict) -> None:
        ref, wid = row["ref"], row["work_item"]
        if self.done_under_this_plan(ref) or not self.gate(row, "update"):
            return
        if wid in self.rev_stale and not self.reread_rev(wid):   # field ops run first, so only a defensive re-read
            return self.conflict(row, "update", wid, "rev_unread")
        remote = self.items.get(wid)
        if remote is None:
            return self.fail(row, "update", "not_found", wid=wid, reason="gone")
        proj = self.projs.get(ref)
        if proj is None or model.projection_hash(proj) != row["projection_hash"]:
            return self.conflict(row, "update", wid, "source_changed")
        if remote["type"] != row["type"]:
            return self.conflict(row, "update", wid, "type_changed")
        if remote["rev"] != row["rev"]:
            return self.conflict(row, "update", wid, "rev_moved", rev_now=remote["rev"])
        try:
            patch = wm.build_update_patch(remote, proj)
        except ValueError:
            return self.conflict(row, "update", wid, "unbuildable")
        if not wm.has_changes(patch):
            return self.conflict(row, "update", wid, "nothing_to_change")
        if {op["path"] for op in patch[1:]} != {o.get("path") for o in row.get("ops") or [] if isinstance(o, dict)}:
            return self.conflict(row, "update", wid, "ops_changed")      # what would go is not what the plan showed
        self.writes += 1
        try:
            out = ado_wit.update(self.root, wid, patch)
        except AdoImportError as exc:
            return self.write_failed(row, "update", wid, exc, patch)
        except ValueError:
            self.writes -= 1
            return self.conflict(row, "update", wid, "unbuildable")
        rev_after = out["rev"]
        self.revs[wid] = rev_after
        if not self.record("applied", ref=ref, kind=row["kind"], action="update", work_item=wid,
                           rev_before=remote["rev"], rev_after=rev_after, fields=_field_refs(patch), type=row["type"],
                           projection_hash=row["projection_hash"], argv_sha=_sha(patch)):
            return self.fail(row, "update", "drift", wid=wid)
        self.links[ref] = self.ledger[-1]
        self.applied.append({"ref": ref, "action": "update", "work_item": wid, "rev_after": rev_after})

    def reread_rev(self, wid: int) -> bool:
        """Re-read the revision of an item this run commented on (a comment moves `rev`, and the comments API does not
        answer the new one), so a PATCH after it tests the revision the board is really at. True when it was read."""
        try:
            rows, _missing = ado_wit.get_batch(self.root, [wid])
        except AdoImportError:
            return False
        for raw in rows:
            if isinstance(raw, dict) and raw.get("id") == wid and _is_count(raw.get("rev")):
                self.revs[wid] = raw["rev"]
                if wid in self.items:
                    self.items[wid] = wm.remote_item(raw, self.emails)
                self.rev_stale.discard(wid)
                return True
        return False

    def recover(self, row: dict, wid: int, sent_at: str) -> dict | None:
        """The comment an unknown-outcome POST already created, found by `text_sha` + author + window, else None."""
        try:
            return model.recovered_comment(row["text_sha"], ado_wit.list_recent_comments(self.root, wid), self.me_id,
                                           sent_at)
        except (AdoImportError, ValueError):
            return None

    def comment(self, row: dict) -> None:
        key, wid, ref = row["idem_key"], row["work_item"], row.get("ref")
        if key in self.commented or not self.gate(row, "comment"):
            return
        if ref is not None and (self.links.get(ref) or {}).get("work_item") != wid:
            return self.conflict(row, "comment", wid, "unlinked")
        text = model.with_trailer(row["text"], self.plan, row["trailer"])
        sent_at = self.now().isoformat()
        found, comment_id, version, rev_after = None, None, None, None
        self.writes += 1
        try:
            if self.transport == "history":
                if wid in self.rev_stale and not self.reread_rev(wid):
                    self.writes -= 1
                    return self.conflict(row, "comment", wid, "rev_unread")
                if wid not in self.revs:
                    self.writes -= 1
                    return self.fail(row, "comment", "not_found", wid=wid, reason="gone")
                rev_after = ado_wit.add_history(self.root, wid, self.revs[wid], _history_html(text))["rev"]
                self.revs[wid] = rev_after
            else:
                out = ado_wit.add_comment(self.root, wid, text, row["format"])
                comment_id, version = out["comment_id"], out["version"]
                self.rev_stale.add(wid)                      # a comment bumps the item's rev (B0, 2026-10-15)
        except AdoImportError as exc:
            if getattr(exc, "error_class", None) not in model.RECOVER_CLASSES or self.transport == "history":
                return self.write_failed(row, "comment", wid, exc)
            found = self.recover(row, wid, sent_at)          # an unknown outcome: re-list, never post again
            if found is None:
                self.rev_stale.add(wid)                      # it may have landed, and moved the rev with it
                return self.write_failed(row, "comment", wid, exc)
            self.rev_stale.add(wid)
            comment_id, version = found["comment_id"], found["version"]
        except ValueError:
            self.writes -= 1
            return self.conflict(row, "comment", wid, "unbuildable")
        extra = {"recovered": True} if found else {}
        if rev_after is not None:
            extra["rev_after"] = rev_after
        if not self.record("commented", ref=ref, work_item=wid, comment_id=comment_id, version=version,
                           format=row["format"], via=self.transport, text_sha=row["text_sha"], chars=len(text),
                           comment_event=row.get("event"), idem_key=key, drafted_by=row.get("drafted_by"),
                           trailer=row["trailer"], mentions=list(row.get("mentions") or []),
                           argv_sha=_sha({"text": text}), **extra):
            return self.fail(row, "comment", "drift", wid=wid)
        self.commented.add(key)
        applied = {"ref": ref, "action": "comment", "work_item": wid, "rev_after": rev_after,
                   "transport": self.transport, "recovered": bool(found)}
        if comment_id is not None:
            applied["comment_id"] = comment_id
        self.applied.append(applied)


def apply_plan(repo_root, plan: dict, *, by: str, cfg: dict, schema: dict, limit: int | None, today) -> dict:
    """Send `plan` (a plan document, see the module docstring) as the person `by`: `{"applied", "failed", "deferred",
    "refused_reason", "exit"}` from `ado_sync_model.apply_result` — exit 0 all applied (a row deferred by `limit` or
    `writes_per_run` is the person's choice), 1 any row failed or `DRIFT`, 2 the whole plan refused with nothing sent.

    `cfg` is the parsed `.sdlc/ado.yaml` (posture, limits, comments), `schema` the discovered process, `limit` the
    verb's `--limit N` or None, `today` a date or an aware datetime (the clock). ValueError before anything is sent
    for a plan that does not hash to its id, a malformed row, a blank `--by` or one that cannot be recorded, or a
    `limit` that is not a positive integer; `AdoImportError` when the board cannot be read before the first write."""
    root = Path(repo_root)
    plan_id, rows = _plan_parts(plan)
    by = _by(by)
    limit = _limit(limit)
    if not isinstance(cfg, dict) or not isinstance(schema, dict):
        raise ValueError("cfg and schema must be the parsed .sdlc/ado.yaml and the discovered schema")
    for row in rows:
        if row.get("action") in FIELD_ACTIONS:
            _check_field_row(row)
        elif row.get("action") == "comment":
            _check_comment_row(row)
    run = _Run(root, plan_id, by, cfg, schema, _clock(today), _read_ledger(root))
    field_rows = _in_tree_order([r for r in rows if r.get("action") in FIELD_ACTIONS])
    drafts = [r for r in rows if r.get("action") == "comment" and r.get("status") == "draft"]
    reason = ("ai_actor" if model.ai_by(by, AGENT_STEMS) else
              "posture" if cfg.get("posture") != "assisted" else
              "forbidden_field" if _forbidden(rows, schema) else
              run.comment_refusal(rows, drafts) or _first_seed_refusal(plan, rows, run.ledger, cfg, limit))
    if reason is None and drafts:
        reason = run.read_identity()                       # az call 0, before any other read or write
    elif reason is None and needs_rest_writes(rows, cfg):
        reason = run.read_identity(bind=False)             # az call 0: can `az rest` (the update transport) sign in
    if reason is not None:
        return run.refuse(reason)
    run.prepare(field_rows, drafts)
    per_run = _setting(cfg.get("limits"), "writes_per_run", DEFAULT_WRITES_PER_RUN)
    run.cap, run.cap_why = min([(per_run, "writes_per_run"), *([(limit, "limit")] if limit is not None else [])])
    for row in field_rows:
        (run.create if row["action"] == "create" else run.update)(row)
    for row in drafts:                                       # field ops first, then the comments
        run.comment(row)
    return model.apply_result(applied=run.applied, failed=run.failed, deferred=run.deferred)
