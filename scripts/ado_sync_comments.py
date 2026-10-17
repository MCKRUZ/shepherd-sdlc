"""Comment drafting for the Azure Boards mirror: the eleven event templates and the plan rows they become (B3-P3).

A comment is speech, and it posts under a person's name. This module therefore only DRAFTS: it reads the
repository's own ledgers and hands back plan rows, and an `apply` that a named human confirmed is the only
thing that ever sends one. It writes no file, spawns nothing, makes no network call and never reads a path that
resolves outside `repo_root`. It is a library part, usable two ways like every part of the plugin:

  * Workflow mode — `ado_sync.py plan --state .sdlc/state.yaml` hands in the repository root, the parsed
    `.sdlc/ado.yaml`, the Boards ledger (`.sdlc/metrics/ado-sync-log.jsonl`) and the `ref -> work item id` map
    of what is linked, and gets back one row per comment worth drafting.
  * Standalone — point `repo_root` at any folder and pass `{}` for `cfg`, `[]` for the ledger and a `ref -> id`
    map of your own. Nothing needs `.sdlc/`; a source that is not there simply yields no rows.

What it reads (events in the order of `COMMENT_EVENTS`; an event switched off in `comments.events` makes no row at
all, and an empty config means the starter's defaults — handoff, spec_deferred, decision_resolved, sprint_carried):

  handoff, sprint_carried, sprint_dropped, verdict_recorded   `.sdlc/metrics/sprint-log.jsonl`
  spec_deferred                                               `specs/*.md` frontmatter (`status: deferred`)
  decision_resolved                                           `.sdlc/decision-log.md` rows that are decided
  finding_disposition                                         `.sdlc/metrics/findings-log.jsonl`, latest per finding
  gate_passed                                                 `.sdlc/state.yaml` phases with a recorded sign-off

`review_summary`, `pr_linked` and `spec_merged` have no ledger the repository keeps (nothing records a review's
round, a pull request's number or a merge's PR); the verb that knows the fact builds the row itself with
`event_row`, which renders and checks it exactly as the derived ones are. `ad_hoc_row` is a person's own
`comment --message`.

Rows. Every row is the same dict (`ROW_KEYS`); the model's `idem_key` is its identity, `text_sha` its fingerprint:

  status    `draft`    a comment that can be sent; `text` is exactly what the board will carry, less the trailer
                       (`apply` appends `with_trailer(text, plan_hash, trailer)` once the plan hash exists)
            `skipped`  not a comment yet: `reason` is one of `SKIP_REASONS` (the ref is not on the board, there is no
                       Lifecycle item for a gate, the ledger line lacks a value the template needs, ...)
            `refused`  the text must not be sent: `reason` is a `boards_contract.COMMENT_REFUSALS` member decided
                       while drafting (ai_actor, event_unknown, needs_disposition, email_in_text, max_chars, budget)
  `detail` is a fixed sentence — never the ledger's own words. A row refused `email_in_text` carries no text at all.

Noise and leak controls (design D40/D41/D46, kit K23). Default templates are fact plus link: they carry ids, sprint
numbers, `@handle`s and repository paths, never a reason, a resolution, a note, a finding's text or an intake
document. `comments.include_text: true` unlocks the `{reason}`/`{resolution}` variants only when `pii_reviewed_by`
names a person, clipped to 200 (deferral, decision) or 160 (carry, drop) characters and set on one line. A name
becomes a `@handle` only through the roster (`.sdlc/team.yaml`: a handle, an address or a name on it) or when it is
already written as one; an address is never printed. Every text is refused `email_in_text` if it would carry an
address or any `@domain.tld` form. A key already on a `commented` ledger line is never drafted again (the row is
simply absent; an ad hoc row says `already_posted`), and the per-item budget counts what this clone's ledger has
posted plus the rows drafted in the same call.

The board-visible trailer is `· sprd <12hex>` (kit K27), built only by `ado_sync_model.with_trailer`.
"""

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path

import yaml

import ado_sync_model as model
import boards_contract as bc
import findings_model as fm
import phase_model as pm
from ado_sync_model import idem_key, text_sha  # the sheet's `idem_key` and `text_sha` are the model's own
from check_spec import parse_frontmatter
from record_findings import scope_paths, target_under
from sprint_model import LANES, SPRINT_ID_RE, normalize_review
from track_decisions import parse_decisions

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
AGENT_STEMS: frozenset[str] = frozenset(p.stem for p in (PLUGIN_ROOT / "agents").glob("*.md"))
DEFAULT_MAX_CHARS = 4000     # comments.max_chars
DEFAULT_BUDGET = 50          # comments.per_item_budget
TEXT_LIMITS = {"spec_deferred": 200, "decision_resolved": 200, "sprint_carried": 160, "sprint_dropped": 160}
LENS = {"eng": "Engineering", "data": "Data"}   # sprint_model.LANES, as the board reads them
DISPOSITION_WORDS = {"FIXED": "fixed", "SPLIT": "split", "ACCEPTED_RISK": "accepted risk", "POSTPONED": "postponed"}
MENTION_NOTE = "mention {handle}: text only — will not notify (B5)"
BUDGET_NOT_CHECKED = "budget not checked: no ledger was given, so the comments already on the item are not known"


# --- the eleven templates (design §8a) ------------------------------------------------------------------------------
#
# `{name}` is filled from the row's values; `[ ... ]` is an optional clause that vanishes when any placeholder inside
# it has no value (a checker not named, a person with no roster handle). `@{who}` takes a handle WITHOUT its `@`.
# Where the design says the text variant is "same", `text` is the fact itself; `None` means it has no text variant.

def _row(default: str, fact: str, text: str | None, event: str) -> dict:
    return {"default": default, "fact": fact, "text": fact if text == "same" else text,
            "key": model.IDEM_KEY_RULES[event][0]}


EVENT_TEMPLATES: dict[str, dict] = {
    "handoff": _row("on", "Handed off to @{developer} for build on branch `{branch}`[; checker @{checker}].\n"
                          "Spec: {path}", "same", "handoff"),
    "spec_deferred": _row("on", "Deferred[ by @{by}] · reason in {path}#frontmatter",
                          "Deferred[ by @{by}]: {reason}.", "spec_deferred"),
    "decision_resolved": _row("on", "Decided[ by @{owner}]. Rationale: {log}#DL-{nn}",
                              "Decided[ by @{owner}]: {resolution}.", "decision_resolved"),
    "sprint_carried": _row("on", "Carried from {from_sprint} to {to_sprint}[ by @{by}] · reason in "
                                 ".sdlc/sprints/{to_sprint}.md",
                           "Carried from {from_sprint} to {to_sprint}[ by @{by}]: {reason}.", "sprint_carried"),
    "gate_passed": _row("off", "Phase {phase} gate passed · signed off[ by @{signer}] · {date}.[\nReport: {report}]",
                        "same", "gate_passed"),
    "verdict_recorded": _row("off", "{Lens} review: {verdict}[ by @{by}].", "same", "verdict_recorded"),
    "finding_disposition": _row("off", "Finding {fp} marked {disposition}[ by @{by}][ · split to {split_to}].",
                                None, "finding_disposition"),
    "sprint_dropped": _row("off", "Dropped from {sprint}[ by @{by}] · reason in .sdlc/sprints/{sprint}.md",
                           "Dropped from {sprint}[ by @{by}]: {reason}.", "sprint_dropped"),
    "review_summary": _row("off", "Review round {round}: {must} MUST, {should} SHOULD; summary in {report}.",
                           None, "review_summary"),
    "pr_linked": _row("off", "PR !{pr} linked.", None, "pr_linked"),
    "spec_merged": _row("off", "Merged via PR !{pr} on {date}.", None, "spec_merged"),
}

# Why a row is not a comment yet (never a `COMMENT_REFUSALS` member: a skip is not a refusal) -> the sentence.
SKIP_SENTENCES: dict[str, str] = {
    "not_on_board": "no work item is mapped to {ref} in this clone's ledger; link or adopt it first",
    "no_lifecycle_item": "no Lifecycle item is mapped, and a gate comment goes on that item only; link or adopt one",
    "spec_not_found": "{ref} has no spec file in specs/, so there is no branch or path to name",
    "missing_field": "{ref}: the ledger holds no {name} for this comment, so the template cannot be filled",
    "no_decided_date": "{ref}: the decision log records no decided date, so the comment has no key",
    "no_signoff_date": "the phase's sign-off records no completion date, so the comment has no key",
    "not_attributable": "the findings ledger has no spec id; the file is not in exactly one live spec's scope",
    "mislabelled_disposition": "the disposition lacks what it claims and still counts as debt, so no comment "
                               "says it was resolved",
    "unkeyable": "a field of the ledger line cannot be part of an idempotency key (a malformed value)",
    "already_posted": "this idempotency key is already on a commented ledger line; it is never posted twice",
}
SKIP_REASONS: tuple[str, ...] = tuple(SKIP_SENTENCES)

REFUSAL_SENTENCES: dict[str, str] = {
    "ai_actor": "--by reads as an AI or an agent; only a named human sends a comment",
    "event_unknown": "that is not one of the comment events (handoff, spec_deferred, ...)",
    "needs_disposition": "the board item is DELETED_IN_ADO or RETYPED; reconcile it before commenting on it",
    "email_in_text": "the text would carry an e-mail address; a comment names people by @handle only",
    "max_chars": "the text as posted is {chars} characters, over comments.max_chars ({limit})",
    "budget": "{used} of {limit} plugin comments are already on the item (comments.per_item_budget)",
}

ROW_KEYS: tuple[str, ...] = ("action", "kind", "origin", "status", "reason", "detail", "event", "ref", "work_item",
                             "target", "idem_key", "variant", "text", "format", "chars", "text_sha", "trailer",
                             "mentions", "drafted_by", "budget", "notes")

_TOKEN = re.compile(r"\[([^\[\]]*)\]|\{(\w+)\}")
_NAME = re.compile(r"\{(\w+)\}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]+")
_TYPED_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")
_DOMAIN_FORM = re.compile(r"@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_BARE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")
_SPEC_ID = re.compile(r"\d{1,6}")
_AGENT = re.compile(r"[a-z][a-z0-9-]{0,39}")
_DECIDED = re.compile(r"\s+[—–-]+\s+decided by\s+(?P<by>.+?)\s+on\s+(?P<date>\d{4}-\d{2}-\d{2})\s*:\s*(?P<what>.*)$",
                      re.DOTALL | re.IGNORECASE)
_DECISION_ID = re.compile(r"DL-(\d+)")
_SPLIT_TO = re.compile(r"(?:spec[ -]*)?(\d{4})", re.IGNORECASE)
_LIVE = ("draft", "ready", "in-flight")


class MissingValue(ValueError):
    """A required `{placeholder}` of a template has no value; `name` says which."""

    def __init__(self, name: str):
        super().__init__(f"no value for {{{name}}}")
        self.name = name


def _present(value) -> bool:
    return value is not None and str(value) != ""


def fill(template: str, values: dict) -> str:
    """The template with its placeholders filled, in ONE pass: a value is never scanned again, so a value that
    reads `{branch}` or `[; checker @x]` stays exactly that. An optional `[ ... ]` clause is dropped when any
    placeholder inside it has no value; a required placeholder with none raises `MissingValue`."""
    def clause(body: str) -> str:
        if any(not _present(values.get(n)) for n in _NAME.findall(body)):
            return ""
        return _NAME.sub(lambda m: str(values[m.group(1)]), body)

    def token(m) -> str:
        if m.group(1) is not None:
            return clause(m.group(1))
        name = m.group(2)
        if not _present(values.get(name)):
            raise MissingValue(name)
        return str(values[name])

    return _TOKEN.sub(token, template)


def _inline(text) -> str:
    """One line of someone's words: control and bidirectional characters become a space, runs collapse."""
    return " ".join(_CONTROL.sub(" ", str(text if text is not None else "")).split())


def _clip(text, limit: int) -> str:
    """`_inline`, less trailing full stops (a template ends its own sentence), cut to `limit` with an ellipsis."""
    clean = _inline(text).rstrip(" .")
    return clean if len(clean) <= limit else clean[:limit - 1] + "…"


def _render(event: str, values: dict, want_text: bool) -> tuple[str, str]:
    """`(text, "fact" | "text")`. The text variant is used only when asked for, when the event has one that differs
    from its fact, and when it can be filled; otherwise the fact is. `reason`/`resolution` are cut to the
    event's limit here, so a caller cannot hand an overlong or multi-line one through."""
    row = EVENT_TEMPLATES[event]
    if want_text and row["text"] is not None and row["text"] != row["fact"]:
        limit = TEXT_LIMITS.get(event, 200)
        cut = {k: (_clip(v, limit) if k in ("reason", "resolution") else v) for k, v in values.items()}
        try:
            return fill(row["text"], cut), "text"
        except MissingValue:
            pass
    return fill(row["fact"], values), "fact"


def render_event(event: str, values: dict, *, include_text: bool = False) -> str:
    """The comment for one event: the design's fact-plus-link line, or (include_text, an event that has one, every
    value present) its text variant. ValueError on an unknown event, `MissingValue` on a required value with none."""
    if event not in EVENT_TEMPLATES:
        raise ValueError(f"{event!r} is not one of the comment events")
    return _render(event, values, include_text)[0]


# --- settings, rows and refusals ------------------------------------------------------------------------------------

def _is_count(value, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= maximum


def _named(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _comments(cfg) -> dict:
    block = cfg.get("comments") if isinstance(cfg, dict) else None
    return block if isinstance(block, dict) else {}


class _Settings:
    """What `.sdlc/ado.yaml` says about comments, each value falling back to the starter's default when it is absent
    or not what the schema allows (`config check` is where a bad value is reported, not here)."""

    def __init__(self, cfg):
        cfg = cfg if isinstance(cfg, dict) else {}
        block = _comments(cfg)
        self.fmt = block.get("format") if block.get("format") in ("markdown", "html") else "markdown"
        self.trailer = block.get("trailer") if block.get("trailer") in model.TRAILER_MODES else "hash"
        self.max_chars = block["max_chars"] if _is_count(block.get("max_chars"), 100000) else DEFAULT_MAX_CHARS
        self.budget = (block["per_item_budget"] if _is_count(block.get("per_item_budget"), 1000)
                       else DEFAULT_BUDGET)
        self.include_text = block.get("include_text") is True and _named(cfg.get("pii_reviewed_by"))
        events = block.get("events") if isinstance(block.get("events"), dict) else {}
        self._events = events

    def on(self, event: str) -> bool:
        value = self._events.get(event)
        word = value.strip().lower() if isinstance(value, str) else None
        if value is True or word in ("on", "true"):
            return True
        if value is False or word in ("off", "false"):
            return False
        return EVENT_TEMPLATES[event]["default"] == "on"


def _full(**kw) -> dict:
    row = {"action": "comment", "kind": "comment", "origin": "event", "status": "draft", "reason": None,
           "detail": None, "event": None, "ref": None, "work_item": None, "target": None, "idem_key": None,
           "variant": None, "text": None, "format": None, "chars": None, "text_sha": None, "trailer": None,
           "mentions": [], "drafted_by": None, "budget": None, "notes": []}
    row.update(kw)
    return {k: row[k] for k in ROW_KEYS}


def _skipped(origin: str, event, ref, wid, target, key, reason: str, **sentence_parts) -> dict:
    detail = SKIP_SENTENCES[reason].format(ref=ref or target or "the item", **sentence_parts)
    return _full(origin=origin, status="skipped", reason=reason, detail=detail, event=event, ref=ref, work_item=wid,
                 target=target if target is not None else ref, idem_key=key)


def _finish(st: _Settings, *, origin: str, event, ref, wid: int, target, key: str, text: str, variant,
            mentions: list, drafted_by, trailer: str, used, drift_class, by: str, notes: list,
            forced_email: bool = False) -> dict:
    """Decide the refusal (the model's rule, in the model's order) and build the row. `used` is the number of plugin
    comments already counted on the item, or None when no ledger was given (the budget is then not checked)."""
    reason = model.comment_refusal(text, by=by, agent_stems=AGENT_STEMS, event=event, max_chars=st.max_chars,
                                   trailer=trailer, budget_used=0 if used is None else used, budget=st.budget,
                                   drift_class=drift_class)
    # the model's address rule is an address; the design's is "any @domain form". It outranks only the checks after it.
    if reason in (None, "max_chars", "budget") and (forced_email or _DOMAIN_FORM.search(text)):
        reason = "email_in_text"
    posted = len(model.with_trailer(text, "0" * 12, trailer))
    shown = event if event in model.COMMENT_EVENTS else None
    base = dict(origin=origin, event=shown, ref=ref, work_item=wid, target=target if target is not None else ref,
                idem_key=key, variant=variant, format=st.fmt, trailer=trailer, mentions=list(mentions),
                drafted_by=drafted_by, notes=list(notes))
    if reason == "email_in_text":  # the text is dropped with the refusal: it is the one thing that must not travel
        return _full(**base, status="refused", reason=reason, detail=REFUSAL_SENTENCES[reason],
                     budget=_budget(st, used, None))
    kept = dict(base, text=text, chars=posted, text_sha=text_sha(text))
    if reason is not None:
        detail = REFUSAL_SENTENCES[reason].format(chars=posted, limit=st.max_chars if reason == "max_chars"
                                                  else st.budget, used=used)
        return _full(**kept, status="refused", reason=reason, detail=detail, budget=_budget(st, used, None))
    return _full(**kept, status="draft", budget=_budget(st, used, None if used is None else used + 1))


def _budget(st: _Settings, used, position) -> dict:
    return {"used": used, "of": st.budget, "position": position}


# --- who a name is ------------------------------------------------------------------------------------------------

class _Roster:
    """`.sdlc/team.yaml` as lookups. A name becomes a handle ONLY here (or by already being one)."""

    def __init__(self, text: str | None):
        self.handles: dict[str, str] = {}
        self.names: dict[str, str] = {}
        self.emails: dict[str, str] = {}
        try:
            data = yaml.safe_load(text) if text else None
        except yaml.YAMLError:
            data = None
        people = data.get("people") if isinstance(data, dict) else None
        for person in people if isinstance(people, list) else []:
            if not isinstance(person, dict):
                continue
            handle = person.get("handle")
            if not (isinstance(handle, str) and bc.HANDLE_RE.fullmatch(handle.strip())):
                continue
            handle = handle.strip()
            self.handles.setdefault(handle.casefold(), handle)
            if _named(person.get("name")):
                self.names.setdefault(" ".join(person["name"].split()).casefold(), handle)
            if _named(person.get("email")):
                self.emails.setdefault(person["email"].strip().lower(), handle)

    def handle(self, value) -> str | None:
        """The bare handle (no `@`) for what a ledger calls a person, or None. A handle is taken as written (the
        roster's spelling when it has one); a bare word, an address or a full name only through the roster."""
        if not isinstance(value, str):
            return None
        text = _inline(value)
        if not text:
            return None
        if bc.HANDLE_RE.fullmatch(text):
            return self.handles.get(text.casefold(), text)[1:]
        if "@" in text:
            found = self.emails.get(text.lower())
            return found[1:] if found else None
        if _BARE.fullmatch(text):
            found = self.handles.get("@" + text.casefold())
            return found[1:] if found else None
        found = self.names.get(" ".join(text.split()).casefold())
        return found[1:] if found else None


# --- the repository's ledgers ------------------------------------------------------------------------------------

def _is_id(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _latest_drift(ledger: list[dict]) -> dict[str, str]:
    """`ref -> the class` of its latest `observed` line: what a pull last said about the item."""
    out: dict[str, str] = {}
    for e in ledger:
        if e.get("event") == "observed" and isinstance(e.get("ref"), str) and isinstance(e.get("class"), str):
            out[e["ref"]] = e["class"]
    return out


class _Cand:
    """One thing a source found: the ref it is about, the template values, the key parts — or why it is skipped."""

    def __init__(self, ref, values=None, parts=None, skip=None, **sentence_parts):
        self.ref, self.values, self.parts = ref, values or {}, parts
        self.skip, self.sentence_parts = skip, sentence_parts


class _Drafter:
    def __init__(self, repo_root, cfg, ledger, idmap):
        self.root = Path(repo_root)
        self.st = _Settings(cfg)
        self.ledger = [e for e in ledger if isinstance(e, dict)] if isinstance(ledger, list) else []
        self.idmap = {r: w for r, w in (idmap.items() if isinstance(idmap, dict) else ())
                      if isinstance(r, str) and bc.REF_RE.fullmatch(r) and _is_id(w)}
        self.commented = model.commented_keys(self.ledger)
        self.drift = _latest_drift(self.ledger)
        self.seen: set[str] = set()
        self.pending: dict[int, int] = {}
        self._cache: dict = {}

    # -- reading, inside the repository only --
    def read(self, path: Path) -> str | None:
        try:
            if not path.is_file() or not path.resolve().is_relative_to(self.root.resolve()):
                return None
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def rel(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.root.resolve()).as_posix()

    def jsonl(self, rel: str) -> list[dict]:
        out = []
        for line in (self.read(self.root / rel) or "").splitlines():
            try:
                entry = json.loads(line) if line.strip() else None
            except ValueError:
                continue
            if isinstance(entry, dict):
                out.append(entry)
        return out

    def once(self, name: str, make):
        if name not in self._cache:
            self._cache[name] = make()
        return self._cache[name]

    @property
    def roster(self) -> _Roster:
        return self.once("roster", lambda: _Roster(self.read(self.root / ".sdlc" / "team.yaml")))

    def handle(self, value) -> str | None:
        return self.roster.handle(value)

    @property
    def sprint_log(self) -> list[dict]:
        return self.once("sprint_log", lambda: self.jsonl(".sdlc/metrics/sprint-log.jsonl"))

    @property
    def specs(self) -> dict[str, dict]:
        """spec id -> {status, checker, deferred_reason, deferred_by, path (repo-relative), stem, file}: one entry per
        `specs/*.md` inside the repository whose frontmatter `spec:` is all digits (the template's `NNNN` and the
        legacy `????` are not specs). The first file for an id wins."""
        def load():
            out: dict[str, dict] = {}
            for path in sorted((self.root / "specs").glob("*.md")):
                text = self.read(path)
                frontmatter = parse_frontmatter(text)[0] if text is not None else {}
                ident = str(frontmatter.get("spec", "")).strip()
                if not _SPEC_ID.fullmatch(ident) or ident in out:
                    continue
                out[ident] = {"id": ident, "file": path, "rel": self.rel(path), "stem": path.stem,
                              "status": (frontmatter.get("status") or "draft").strip().lower(),
                              "checker": frontmatter.get("checker") or "",
                              "deferred_reason": frontmatter.get("deferred_reason") or "",
                              "deferred_by": frontmatter.get("deferred_by") or ""}
            return out
        return self.once("specs", load)

    def lifecycle_ref(self) -> str | None:
        return min((r for r in self.idmap if r.split(":")[1] == "lifecycle"), default=None)

    # -- one candidate to one row --
    def make(self, event: str, cand: _Cand) -> dict | None:
        key = None
        if cand.parts is not None:
            try:
                key = idem_key(event, **cand.parts)
            except ValueError:
                return _skipped("event", event, cand.ref, None, None, None, "unkeyable")
            if key in self.commented or key in self.seen:
                return None  # on the board already (or listed already in this call): never drafted twice
            self.seen.add(key)
        wid = self.idmap.get(cand.ref) if cand.ref else None
        if cand.skip:
            return _skipped("event", event, cand.ref, wid, None, key, cand.skip, **cand.sentence_parts)
        if wid is None:
            return _skipped("event", event, cand.ref, None, None, key, "not_on_board")
        try:
            text, variant = _render(event, cand.values, self.st.include_text)
        except MissingValue as exc:
            return _skipped("event", event, cand.ref, wid, None, key, "missing_field", name=exc.name)
        used = model.budget_used(self.ledger, wid) + self.pending.get(wid, 0)
        row = _finish(self.st, origin="event", event=event, ref=cand.ref, wid=wid, target=None, key=key, text=text,
                      variant=variant, mentions=[], drafted_by=None, trailer=self.st.trailer, used=used,
                      drift_class=self.drift.get(cand.ref), by="", notes=[])
        if row["status"] == "draft":
            self.pending[wid] = self.pending.get(wid, 0) + 1
        return row


# --- the sources, one per derived event --------------------------------------------------------------------------

def _spec_ref(value) -> tuple[str | None, str | None]:
    ident = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    return (ident, f"sdlc:spec:{ident}") if _SPEC_ID.fullmatch(ident) else (None, None)


def _sprint(value) -> str | None:
    text = value.strip() if isinstance(value, str) else ""
    return text if SPRINT_ID_RE.fullmatch(text) else None


def _handoffs(d: _Drafter):
    for e in d.sprint_log:
        if e.get("event") != "handoff":
            continue
        ident, ref = _spec_ref(e.get("spec"))
        if ref is None:
            continue
        parts = {"ref": ref, "ts": e.get("ts")}
        spec = d.specs.get(ident)
        if spec is None:
            yield _Cand(ref, parts=parts, skip="spec_not_found")
            continue
        branch = _inline(f"spec/{spec['stem']}").replace("`", "'")   # handoff.py's rule: spec/<the file's own id-name>
        yield _Cand(ref, {"developer": d.handle(e.get("to")), "branch": branch,
                          "checker": d.handle(spec.get("checker")), "path": spec["rel"]}, parts)


def _deferrals(d: _Drafter):
    for ident, spec in sorted(d.specs.items()):
        reason = str(spec.get("deferred_reason") or "").strip()
        if spec.get("status") != "deferred" or not reason:
            continue
        yield _Cand(f"sdlc:spec:{ident}", {"by": d.handle(spec["deferred_by"]), "path": spec["rel"],
                                           "reason": reason},
                    {"ref": f"sdlc:spec:{ident}", "reason": reason})


def _decisions(d: _Drafter):
    log = next((p for p in (d.root / ".sdlc" / "decision-log.md", d.root / "decision-log.md")
                if d.read(p) is not None), None)
    if log is None:
        return
    for row in parse_decisions(log):
        m = _DECISION_ID.fullmatch((row.get("id") or "").strip().upper())
        if not m or (row.get("status") or "").strip().lower() not in ("decided", "resolved"):
            continue
        ref, ident = f"sdlc:decision:{m.group(1)}", f"DL-{m.group(1)}"
        found = _DECIDED.search(row.get("decision") or "")
        try:
            day = date.fromisoformat(found.group("date")).isoformat() if found else None
        except ValueError:
            day = None
        if day is None:
            yield _Cand(ref, skip="no_decided_date")
            continue
        decider = d.handle(found.group("by")) or d.handle(row.get("owner"))
        yield _Cand(ref, {"owner": decider, "log": d.rel(log), "nn": m.group(1), "resolution": found.group("what")},
                    {"decision": ident, "date": day})


def _carries(d: _Drafter):
    for e in d.sprint_log:
        if e.get("event") != "carried":
            continue
        _, ref = _spec_ref(e.get("spec"))
        src, dst = _sprint(e.get("sprint")), _sprint(e.get("to_sprint"))
        if ref is None or src is None or dst is None:
            continue
        yield _Cand(ref, {"from_sprint": src, "to_sprint": dst, "by": d.handle(e.get("by")),
                          "reason": e.get("reason")}, {"ref": ref, "from_sprint": src, "to_sprint": dst})


def _drops(d: _Drafter):
    for e in d.sprint_log:
        if e.get("event") != "dropped":
            continue
        _, ref = _spec_ref(e.get("spec"))
        sprint = _sprint(e.get("sprint"))
        if ref is None or sprint is None:
            continue
        yield _Cand(ref, {"sprint": sprint, "by": d.handle(e.get("by")), "reason": e.get("reason")},
                    {"ref": ref, "sprint": sprint})


def _verdicts(d: _Drafter):
    for e in d.sprint_log:
        if e.get("event") != "verdict":
            continue
        _, ref = _spec_ref(e.get("spec"))
        lane = e.get("lane").strip().lower() if isinstance(e.get("lane"), str) else None
        verdict = normalize_review(e.get("verdict")) if isinstance(e.get("verdict"), str) else None
        if ref is None or lane not in LANES or verdict is None:
            continue
        yield _Cand(ref, {"Lens": LENS[lane], "verdict": verdict, "by": d.handle(e.get("by"))},
                    {"ref": ref, "lens": lane, "verdict": verdict, "ts": e.get("ts")})


def _gate_day(value) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(value.strip()[:10]).isoformat() if isinstance(value, str) else None
    except ValueError:
        return None


def _gates(d: _Drafter):
    text = d.read(d.root / ".sdlc" / "state.yaml")
    try:
        state = yaml.safe_load(text) if text else None
    except yaml.YAMLError:
        return
    phases = state.get("phases") if isinstance(state, dict) else None
    if not isinstance(phases, dict):
        return
    def order(phase: str) -> tuple:
        known = pm.phase_order(phase)
        return (known if known is not None else 10 ** 6, phase)

    ordered = sorted(((str(k).strip(), v) for k, v in phases.items()), key=lambda kv: order(kv[0]))
    lifecycle = d.lifecycle_ref()
    for phase, data in ordered:
        results = data.get("gate_results") if isinstance(data, dict) else None
        signer = results.get("signed_off_by") if isinstance(results, dict) else None
        if not isinstance(data, dict) or data.get("status") != "completed" or not _named(signer):
            continue
        day = _gate_day(data.get("completed_at"))
        if day is None:
            yield _Cand(None, skip="no_signoff_date")
            continue
        parts = {"phase": phase, "signoff_date": day}
        if lifecycle is None:
            yield _Cand(None, parts=parts, skip="no_lifecycle_item")
            continue
        slug = pm.artifact_dirname(phase)
        report = f".sdlc/reports/{slug}-report.html" if slug else None
        if report is None or not (d.root / report).is_file() or d.read(d.root / report) is None:
            report = None
        yield _Cand(lifecycle, {"phase": phase, "signer": d.handle(signer), "date": day, "report": report}, parts)


def _split_ref(value) -> str | None:
    text = _inline(value) if isinstance(value, str) else ""
    if bc.REF_RE.fullmatch(text):
        return text
    found = _SPLIT_TO.fullmatch(text)
    return f"sdlc:spec:{found.group(1)}" if found else None


def _findings(d: _Drafter):
    latest: dict[str, dict] = {}
    for e in d.jsonl(".sdlc/metrics/findings-log.jsonl"):
        fingerprint = e.get("fingerprint") if _named(e.get("fingerprint")) else fm.fingerprint(e)
        latest[fingerprint] = e  # the finding's current disposition: the last line that names it
    scopes: dict[str, list[str]] = {}
    for fingerprint, e in latest.items():
        disposition = fm.normalize_disposition(e.get("disposition"))
        if disposition not in DISPOSITION_WORDS:
            continue  # OPEN is no one's decision; an unknown word is not one the ledger can vouch for
        if disposition in ("SPLIT", "ACCEPTED_RISK") and not fm.validate_disposition(e)[0]:
            yield _Cand(None, skip="mislabelled_disposition")
            continue
        fp = hashlib.sha256(str(fingerprint).encode("utf-8")).hexdigest()[:8]
        live = []
        for ident, spec in sorted(d.specs.items()):
            if spec.get("status") not in _LIVE:
                continue
            if ident not in scopes:
                scopes[ident] = scope_paths(d.read(spec["file"]) or "")
            if any(target_under(e.get("target"), p) for p in scopes[ident]):
                live.append(ident)
        parts = {"fp": fp, "disposition": DISPOSITION_WORDS[disposition].replace(" ", "-")}
        if len(live) != 1:
            yield _Cand(None, parts=parts, skip="not_attributable")
            continue
        who = {"ACCEPTED_RISK": e.get("approver"), "SPLIT": e.get("owner")}.get(disposition)
        split_to = _split_ref(e.get("split_to")) if disposition == "SPLIT" else None
        yield _Cand(f"sdlc:spec:{live[0]}", {"fp": fp, "disposition": DISPOSITION_WORDS[disposition],
                                             "by": d.handle(who), "split_to": split_to}, parts)


# source of each event the repository's ledgers can draft (the other three: see the module docstring)
SOURCES = {"handoff": _handoffs, "spec_deferred": _deferrals, "decision_resolved": _decisions,
           "sprint_carried": _carries, "gate_passed": _gates, "verdict_recorded": _verdicts,
           "finding_disposition": _findings, "sprint_dropped": _drops}
DERIVED_EVENTS: tuple[str, ...] = tuple(e for e in model.COMMENT_EVENTS if e in SOURCES)


def draft_event_rows(repo_root, cfg: dict, ledger: list[dict], idmap: dict[str, int]) -> list[dict]:
    """The comment rows `plan` derives from the repository's own ledgers (the module docstring lists the sources).

    `cfg` is the parsed `.sdlc/ado.yaml` (`{}` or None: the starter's defaults), `ledger` the Boards ledger's lines,
    `idmap` the `sdlc:<kind>:<id> -> work item id` of what is linked. One row per comment, in event order then
    ledger order: an event switched off makes none; a key already on a `commented` line is absent; a ref that is not
    on the board, or a line the template cannot be filled from, is a `skipped` row; a text that must not be sent is a
    `refused` row; the rest are `draft`. Every row passes `ado_sync_model.comment_refusal` while drafting, and no
    row carries a ledger's own words except through the gated text variants. Reads only inside `repo_root`; writes
    nothing."""
    d = _Drafter(repo_root, cfg, ledger, idmap)
    rows = []
    for event in DERIVED_EVENTS:
        if not d.st.on(event):
            continue
        for cand in SOURCES[event](d):
            row = d.make(event, cand)
            if row is not None:
                rows.append(row)
    return rows


def event_row(event: str, ref: str, wid: int, values: dict, key_parts: dict, *, cfg: dict,
              ledger: list[dict] | None = None) -> dict:
    """One event comment from facts the caller holds (`review_summary`, `pr_linked`, `spec_merged`, which no ledger
    records), rendered, keyed and checked exactly as a derived row is. `values` fill the template, `key_parts` are
    `ado_sync_model.idem_key`'s parts for the event. With a `ledger` the item's budget and drift are read from it and
    a key already on a `commented` line comes back `skipped` / `already_posted`; without one the budget is not
    checked. ValueError on an unknown event, a ref or work item that is not one, an unkeyable part, or `MissingValue`."""
    if event not in EVENT_TEMPLATES:
        raise ValueError(f"{event!r} is not one of the comment events")
    if not (isinstance(ref, str) and bc.REF_RE.fullmatch(ref)):
        raise ValueError(f"{ref!r} is not an sdlc:<kind>:<id> ref")
    if not _is_id(wid):
        raise ValueError(f"{wid!r} is not a work item id")
    st = _Settings(cfg)
    key = idem_key(event, **key_parts)
    lines = [e for e in ledger if isinstance(e, dict)] if ledger is not None else None
    if lines is not None and key in model.commented_keys(lines):
        return _skipped("event", event, ref, wid, None, key, "already_posted")
    text, variant = _render(event, values, st.include_text)
    return _finish(st, origin="event", event=event, ref=ref, wid=wid, target=None, key=key, text=text,
                   variant=variant, mentions=[], drafted_by=None, trailer=st.trailer,
                   used=None if lines is None else model.budget_used(lines, wid),
                   drift_class=None if lines is None else _latest_drift(lines).get(ref), by="", notes=[])


# --- an ad hoc comment --------------------------------------------------------------------------------------------

def _target(ref, wid) -> tuple[str | None, str]:
    if not (isinstance(ref, str) and model.TARGET_RE.fullmatch(ref)):
        raise ValueError(f"{ref!r} is not an sdlc:<kind>:<id> ref or a #<work item>")
    if not _is_id(wid):
        raise ValueError(f"{wid!r} is not a work item id")
    if ref.startswith("#"):
        if int(ref[1:]) != wid:
            raise ValueError(f"{ref} and work item {wid} name different items")
        return None, ref
    return ref, ref


def _mentions(values) -> tuple[list[str], bool]:
    """`(handles, an_address_was_named)`. A mention is `@handle` (plain text in v1, D44); any `@domain` or
    address form is not refused here but flagged, so the row is refused `email_in_text`; anything else is illegal."""
    out: list[str] = []
    address = False
    for value in values if isinstance(values, (list, tuple)) else []:
        if not isinstance(value, str):
            raise ValueError(f"--mention must look like @handle, not {value!r}")
        if bc.HANDLE_RE.fullmatch(value):
            if value not in out:
                out.append(value)
        elif bc.EMAIL_RE.search(value) or _DOMAIN_FORM.search(value) or value.count("@") > 1:
            address = True
        else:
            raise ValueError("--mention must look like @handle (letters, digits and hyphens)")
    return out, address


def _drafted_by(value) -> str | None:
    if value is None:
        return None
    stem = str(value).strip()
    if stem.lower().startswith(model.AGENT_PREFIX):
        stem = stem[len(model.AGENT_PREFIX):].strip()
    if not _AGENT.fullmatch(stem):
        raise ValueError("drafted_by is a bare agent stem or `claude` (lower-case letters, digits, hyphens)")
    return stem


def ad_hoc_row(ref: str, wid: int, message: str, *, by: str, mentions: list[str], cfg: dict, event: str | None = None,
               ledger: list[dict] | None = None, drift_class: str | None = None, drafted_by: str | None = None) -> dict:
    """The plan row for a person's own `comment <ref|#id> --message …`.

    `ref` is an `sdlc:<kind>:<id>` ref or `#<work item>` (which must be `wid`); `message` is taken as typed (line
    endings unified, outer space trimmed, control characters dropped); `by` is the named human (ValueError when
    blank — the verb exits 1; an AI or agent name is the refusal `ai_actor`); `mentions` are `@handle`s, appended
    to the text unless the message already names them and noted "text only — will not notify". Refusals, in the
    model's order: ai_actor, event_unknown (`event` outside `COMMENT_EVENTS`; None is plain), needs_disposition
    (`drift_class`, or the item's latest `observed` class in `ledger`), email_in_text (an address or any `@domain`
    form, in the message or a mention), max_chars, budget (needs `ledger`; without it the budget is not checked and
    the row says so). A key already on a `commented` line comes back `skipped` / `already_posted`. A message a human
    typed carries no trailer; one an agent proposed (`drafted_by`) takes `comments.trailer`.
    ValueError on an empty message, a bad ref, work item, mention or `drafted_by`."""
    target_ref, target = _target(ref, wid)
    if not isinstance(message, str):
        raise ValueError("the message must be text")
    typed = _TYPED_CONTROL.sub("", message.replace("\r\n", "\n").replace("\r", "\n")).strip()
    if not typed:
        raise ValueError("the message is empty")
    if not isinstance(by, str) or not by.strip():
        raise ValueError("--by is required: a named human")
    st = _Settings(cfg)
    handles, address = _mentions(mentions)
    agent = _drafted_by(drafted_by)
    named = [h for h in handles if re.search(r"(?<![A-Za-z0-9-])" + re.escape(h) + r"(?![A-Za-z0-9-])", typed)]
    missing = [h for h in handles if h not in named]
    text = typed + (" " + " ".join(missing) if missing else "")
    lines = [e for e in ledger if isinstance(e, dict)] if ledger is not None else None
    drift = drift_class
    if drift is None and lines is not None:  # the item's latest `observed` line, found by ref or, for a #id, by number
        same = (lambda e: e.get("ref") == target_ref) if target_ref is not None else (lambda e: e.get("work_item") == wid)
        drift = next((e.get("class") for e in reversed(lines) if e.get("event") == "observed" and same(e)), None)
    notes = [MENTION_NOTE.format(handle=h) for h in handles]
    used = None if lines is None else model.budget_used(lines, wid)
    if used is None:
        notes.append(BUDGET_NOT_CHECKED)
    key = idem_key(model.AD_HOC, ref=target, text=text)
    row = _finish(st, origin="ad_hoc", event=event, ref=target_ref, wid=wid, target=target, key=key, text=text,
                  variant=None, mentions=handles, drafted_by=agent, trailer=st.trailer if agent else "none",
                  used=used, drift_class=drift, by=by.strip(), notes=notes, forced_email=address)
    if row["status"] == "draft" and lines is not None and key in model.commented_keys(lines):
        return _skipped("ad_hoc", row["event"], target_ref, wid, target, key, "already_posted")
    return row
