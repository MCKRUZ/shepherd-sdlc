"""The Azure Boards watermark feed: every work item revision made since a point, read a page at a time (B5-P2, B5-P2b).

`ado_wit.py` asks about one item (its revisions, its comments); this module asks the board "what changed since I last
looked" in one stream, so `pull` need not re-read every mirrored item to learn which ones moved. It reads
`reporting/workItemRevisions` through `ado_transport.invoke_body` — the one seam that spawns `az` — at the location
`boards_contract.WIT_ROUTES["workitemrevisions"]` names (area, resource, route parameters, method, api-version; the
row the live capture corrects, so a corrected row is followed with no change here). It imports no subprocess and
holds no route string of its own.

  revisions_since(repo, watermark)   (revisions, next_watermark): every revision after the watermark, in the order the
                                     board sent them; the second value is the watermark to read from next time
  feed_page(repo, start_date_time=, continuation_token=)
                                     one call, naming exactly one of the two; both is a ValueError, so is neither
  load_watermark(repo) / save_watermark(repo, watermark)
                                     the one-line file `.sdlc/ado/local/watermark`; never saved reads as `None`

A watermark is one of two things, and the string SAYS which: `token:<opaque>` (the continuation token the board
returned, and what a read normally keeps) or `since:<whole UTC time>` (a start time `YYYY-MM-DDTHH:MM:SSZ`, a bound a
person or a caller picks for a first read). The kind is read from the prefix and never from the shape of the value: a
board's token is opaque, so one that begins `2026-10-13`, or is itself a whole UTC time, is still a token and is sent
as `continuationToken`; a `since:` value is sent as `startDateTime` and must be a whole UTC time. A string with
neither prefix is a ValueError (`save_watermark`, `revisions_since`) — or, in a file, `None` with a warning on stderr,
never a date guessed from it. `feed_page` itself takes the bare token or the bare time by parameter name; the prefix
belongs to the watermark, the string that gets stored. `None` is "never read": the first call then starts at
`FEED_START`, the beginning of the board's history — named, not omitted, so the first call always carries a
`startDateTime`. A token and a start time are never sent together (the API refuses the pair, and so does `feed_page`):
the first call names whichever the watermark is, and every later call names only the token the page before it
returned. `isLastBatch: true` ends the read and `token:<that page's token>` is the next watermark. A read that found
nothing newer and was sent no token keeps the watermark it started from, so `None` comes back as
`since:<FEED_START>`, never as nothing and never as 0.

This module stores NOTHING. The caller saves the returned watermark with `save_watermark` after it has used the
revisions, so a crash between the read and the use reads the same revisions again instead of losing them. An
unreadable watermark file — or one with no `token:` / `since:` prefix, as an earlier version wrote it — reads as `None`
for the same reason: read again, never skip. A file that is there but cannot be trusted says so on stderr (what is
wrong with it, never what it held), because reading from the beginning is not free; a file never saved says nothing.

What a revision looks like. `{"id", "rev", "fields": {reference name: value}}`, the fields as the board sent them
with two changes that keep people out of the repository's data. An identity (a field named `*By`, `AssignedTo` or
`AuthorizedAs`, or any object value) becomes `ado_discussion_map.redact_identity`'s `{handle, display_name, id}`, the
handle coming from `.sdlc/team.yaml` by e-mail address, read only when an identity turns up; an e-mail address or a
GUID inside any other text is replaced by `[email]` / `[guid]`. `System.History` (a comment's text) is dropped and
only `history_changed: true` is left. A value that is neither a scalar nor an identity is a shape this module does not
know and an `AdoImportError`. The result is in memory only: its display names and ids are the discussion cache's
kind of data, so a caller must not write them to a committed file or a ledger line.

Two honest limits. `MAX_FEED_PAGES` pages are read per call; if the board still had more, the result's `.truncated`
is True and its token is the one to resume from (the next call starts after the last page read). A page that says
there is more but whose token is missing, or is the one it was just asked for, is an `AdoImportError` — a loop, or a
silent cut, would be worse than a failed read.

Standalone or workflow: it takes a repository root (`--repo`, or the parent of `.sdlc/state.yaml`) only to read the
Azure DevOps remote and the roster from it, and never reads `state.yaml`.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ado_discussion_map  # noqa: E402
import ado_transport  # noqa: E402
import validate_team  # noqa: E402
import yaml  # noqa: E402
from ado_map import AdoImportError, _require  # noqa: E402
from boards_contract import EMAIL_RE, GUID_RE, LOCAL_DIR, PAGE_TOKEN_KEYS, WIT_ROUTES  # noqa: E402

TOKEN_PREFIX = "token:"               # a watermark's two kinds, named in the string itself (never inferred)
SINCE_PREFIX = "since:"
FEED_START = "1970-01-01T00:00:00Z"   # "from the beginning": what a watermark never read starts at
# What the feed is asked for on every call (the tokens carry no column list, so each call repeats it). The fields the
# mirror compares: who an item is, which revision, its type and state, when it changed and its tags. No identity,
# no free text — the B5-P0 fixture's first-page command names exactly these.
FEED_FIELDS = ("System.Id", "System.Rev", "System.WorkItemType", "System.State", "System.ChangedDate", "System.Tags")
MAX_FEED_PAGES = 100                  # per call; a feed page is a few hundred revisions
WATERMARK_FILE = f"{LOCAL_DIR}/watermark"
IDENTITY_FIELD_ENDS = ("By", "AssignedTo", "AuthorizedAs")  # the discussion map's own suffixes, pinned equal by a test

_START_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,7})?Z")
_TOKEN_RE = re.compile(r"[\x21-\x7e]{1,1024}")  # one printable ASCII word: it rides in one argv word as `k=<token>`


class RevisionList(list):
    """The revisions one read returned — a plain list, plus what a list cannot say.

    `truncated`: the read stopped at `MAX_FEED_PAGES` with the board still holding more."""

    truncated: bool = False


def _label() -> str:
    """`<area>/<resource>` of the contract row, for messages: an error names the call it came from."""
    row = WIT_ROUTES["workitemrevisions"]
    return f"{row['area']}/{row['resource']}"


# --- the watermark argument ----------------------------------------------------------------------------------------

def _classify(watermark) -> tuple[str, str]:
    """`("token", opaque)` for `token:<opaque>`, `("since", time)` for `since:<time>`: the kind is the prefix, read
    strictly (case-sensitive, at the very start, nothing guessed from the value after it), and the value is checked
    against what that kind allows — one word of printable text for a token, a whole UTC time for `since:`. A ValueError,
    before any call, for anything else, including a bare token or a bare time."""
    if not isinstance(watermark, str):
        raise ValueError(f"a watermark is `{TOKEN_PREFIX}<continuation token>` or `{SINCE_PREFIX}<UTC time>` as text, "
                         f"not {watermark!r}")
    if watermark.startswith(TOKEN_PREFIX):
        value = watermark[len(TOKEN_PREFIX):]
        if not _TOKEN_RE.fullmatch(value):
            raise ValueError(f"a `{TOKEN_PREFIX}` watermark carries one word of printable text with no space, "
                             f"1 to 1,024 characters")
        return "token", value
    if watermark.startswith(SINCE_PREFIX):
        value = watermark[len(SINCE_PREFIX):]
        if not _START_RE.fullmatch(value):
            raise ValueError(f"a `{SINCE_PREFIX}` watermark must be a whole ISO-8601 UTC time "
                             f"(2026-10-10T00:00:00Z), not {value!r}")
        return "since", value
    raise ValueError(f"a watermark names its kind: `{TOKEN_PREFIX}<continuation token>` or `{SINCE_PREFIX}<UTC time>`, "
                     f"not {watermark!r}")


def _watermark(kind: str, value: str) -> str:
    """The watermark string for a kind (`"token"` or `"since"`) and its bare value: the inverse of `_classify`."""
    return f"{TOKEN_PREFIX if kind == 'token' else SINCE_PREFIX}{value}"


# --- one page --------------------------------------------------------------------------------------------------------

def feed_page(repo_root, *, start_date_time: str | None = None, continuation_token: str | None = None) -> dict:
    """One `GET` of the feed, as the board sent it (parsed JSON, no shape checked here). Names `startDateTime` or
    `continuationToken`, never both and never neither: both is a ValueError (the API refuses the pair), and so is
    neither (an implicit "from the beginning" is `FEED_START`, named). Every call repeats `fields`."""
    if start_date_time is not None and continuation_token is not None:
        raise ValueError("start_date_time and continuation_token are mutually exclusive: the first page names a "
                         "start, every later page only the token the page before it returned")
    if start_date_time is None and continuation_token is None:
        raise ValueError("a feed page call names exactly one of start_date_time and continuation_token")
    if start_date_time is not None:
        if not (isinstance(start_date_time, str) and _START_RE.fullmatch(start_date_time)):
            raise ValueError(f"start_date_time must be a whole ISO-8601 UTC time, not {start_date_time!r}")
        query = {"startDateTime": start_date_time}
    else:
        if not (isinstance(continuation_token, str) and _TOKEN_RE.fullmatch(continuation_token)):
            raise ValueError(f"continuation_token must be the token a page returned (one word of printable text, "
                             f"no space, at most 1,024 characters), not {continuation_token!r}")
        query = {"continuationToken": continuation_token}
    query["fields"] = ",".join(FEED_FIELDS)
    row = WIT_ROUTES["workitemrevisions"]
    label = _label()
    params = {"project": ado_transport.remote(repo_root).project}
    for key in row["route"]:
        if key not in params:
            raise AdoImportError(f"{label}: route parameter {key!r} is not supplied "
                                 f"(boards_contract.WIT_ROUTES['workitemrevisions'])")
    try:
        return ado_transport.invoke_body(repo_root, row["area"], row["resource"],
                                         {key: params[key] for key in row["route"]}, method=row["method"],
                                         query=query, api_version=row["api_version"])
    except AdoImportError as exc:
        raise AdoImportError(f"{label}: {exc}") from exc


def _read_page(doc) -> tuple[list, bool, str | None]:
    """`(values, is_last_batch, continuation_token)` of one page, or an `AdoImportError` naming what was wrong. A blank
    token is no token."""
    values = _require(doc, "values", "feed page")
    if not isinstance(values, list):
        raise AdoImportError("unexpected az shape: feed page.values is not a list")
    last = _require(doc, "isLastBatch", "feed page")
    if not isinstance(last, bool):
        raise AdoImportError("unexpected az shape: feed page.isLastBatch is not true or false")
    # the body's `continuationToken`, else the `continuation_token` the az extension adds (its own spelling, B0 2026-10-15)
    token = next((doc[k] for k in PAGE_TOKEN_KEYS
                  if doc.get(k) is not None and not (isinstance(doc[k], str) and not doc[k].strip())), None)
    if isinstance(token, str) and not token.strip():
        token = None
    if token is not None and not (isinstance(token, str) and _TOKEN_RE.fullmatch(token)):
        raise AdoImportError("unexpected az shape: feed page.continuationToken is not a token "
                             "(one word of printable text)")
    return values, last, token


# --- one revision ----------------------------------------------------------------------------------------------------

def _roster_emails(root) -> dict[str, str]:
    """`{lower-case address: @handle}` from `<repo>/.sdlc/team.yaml`; `{}` for a missing or unreadable roster."""
    try:
        data = yaml.safe_load((Path(root) / ".sdlc" / "team.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return {}
    return validate_team.people_by_email(data if isinstance(data, dict) else {})


class _LazyRoster:
    """The roster, read the first time an identity needs it and never when none does."""

    def __init__(self, root):
        self.root = root
        self.emails: dict[str, str] | None = None

    def __call__(self) -> dict[str, str]:
        if self.emails is None:
            self.emails = _roster_emails(self.root)
        return self.emails


def _positive_in(value, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AdoImportError(f"unexpected az shape: {what} is not a positive integer ({value!r})")
    return value


def _plain(text: str) -> str:
    return GUID_RE.sub("[guid]", EMAIL_RE.sub("[email]", ado_discussion_map.strip_control(text)))


def _field(ref: str, value, roster):
    if isinstance(value, dict) or (isinstance(value, str) and ref.endswith(IDENTITY_FIELD_ENDS)):
        return ado_discussion_map.redact_identity(value, roster())
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _plain(value)
    raise AdoImportError(f"unexpected az shape: feed row field {ref} is a {type(value).__name__}, "
                         f"not a value or an identity")


def _row(raw, roster) -> dict:
    row = {"id": _positive_in(_require(raw, "id", "feed row"), "feed row.id"),
           "rev": _positive_in(_require(raw, "rev", "feed row"), "feed row.rev"), "fields": {}}
    fields = _require(raw, "fields", "feed row")
    if not isinstance(fields, dict):
        raise AdoImportError("unexpected az shape: feed row.fields is not an object")
    for ref, value in fields.items():
        if ref == "System.History":  # comment text: only the fact that it changed is kept
            row["history_changed"] = True
        else:
            row["fields"][str(ref)] = _field(str(ref), value, roster)
    return row


# --- the read --------------------------------------------------------------------------------------------------------

def revisions_since(repo_root, watermark: str | None) -> tuple[list[dict], str]:
    """`(revisions, next_watermark)`: every revision after `watermark`, in the order the board sent them, and the
    watermark to pass next time. `watermark` is None (never read: start at `FEED_START`), `since:<whole UTC time>`
    (sent as `startDateTime`) or `token:<opaque>` as an earlier read returned it (sent as `continuationToken`); the
    prefix decides, the value's shape never does, and anything else is a ValueError before a call. Pages are read until
    the board says `isLastBatch`; the returned watermark is `token:<that last page's token>`, or the one the read
    started from when the board sent no token. At most `MAX_FEED_PAGES` pages: past that the result's `.truncated` is
    True and the watermark is the last page's. Reads only — nothing is stored (see `save_watermark`)."""
    kind, value = ("since", FEED_START) if watermark is None else _classify(watermark)
    call = {"start_date_time": value} if kind == "since" else {"continuation_token": value}
    roster = _LazyRoster(repo_root)
    revisions = RevisionList()
    keep = _watermark(kind, value)
    for _ in range(MAX_FEED_PAGES):
        values, last, token = _read_page(feed_page(repo_root, **call))
        revisions.extend(_row(raw, roster) for raw in values)
        if token is not None:
            keep = _watermark("token", token)
        if last:
            return revisions, keep
        if token is None:
            raise AdoImportError(f"{_label()}: the board said there is more but sent no continuationToken, "
                                 f"so there is nothing to resume from")
        if token == call.get("continuation_token"):
            raise AdoImportError(f"{_label()}: paging did not advance (the board sent the continuationToken "
                                 f"{token!r} it was just asked for)")
        call = {"continuation_token": token}
    revisions.truncated = True
    return revisions, keep


# --- the watermark file ----------------------------------------------------------------------------------------------

def _read_watermark(repo_root) -> tuple[str | None, str | None]:
    """`(watermark, problem)`: the saved watermark and None, or None and what is wrong with the file, or (None, None)
    when nothing was ever saved. The problem never carries the file's content."""
    try:
        text = (Path(repo_root) / WATERMARK_FILE).read_bytes().decode("ascii")
    except (FileNotFoundError, NotADirectoryError):
        return None, None
    except OSError:
        return None, "cannot be read"
    except UnicodeDecodeError:
        return None, "is not plain text"
    line = text.rstrip("\r\n")
    try:
        _classify(line)
    except ValueError:
        return None, f"does not hold one `{TOKEN_PREFIX}<token>` or `{SINCE_PREFIX}<UTC time>` line"
    return line, None


def load_watermark(repo_root) -> str | None:
    """The saved watermark (`token:<opaque>` or `since:<whole UTC time>`), or None when there is none worth trusting:
    never saved, empty, unreadable, more than one line, or with no valid prefix (an unprefixed value is never guessed
    into a date or a token). None reads from the beginning — the safe direction, never a skip — and is never 0. A file
    that is there but cannot be trusted is warned about on stderr, without its content; one never saved is not."""
    watermark, problem = _read_watermark(repo_root)
    if problem is not None:
        print(f"WARNING: {WATERMARK_FILE} {problem}; a watermark reads `{TOKEN_PREFIX}<token>` or "
              f"`{SINCE_PREFIX}<UTC time>`. Reading the feed from the beginning.", file=sys.stderr)
    return watermark


def save_watermark(repo_root, watermark: str) -> Path:
    """Write `watermark` (`token:<opaque>` or `since:<whole UTC time>`) as `.sdlc/ado/local/watermark`, one line,
    through a scratch file and a rename so a crash never leaves half of one; returns the path. A ValueError, writing
    nothing, for anything `revisions_since` would refuse — a bare token or a bare time included. The folder is made
    ignored by git first if no `.gitignore` is there (never overwritten if one is), as the discussion cache does."""
    _classify(watermark)
    path = Path(repo_root) / WATERMARK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    ignore = path.parent / ".gitignore"
    if not (ignore.exists() or ignore.is_symlink()):
        ignore.write_bytes(b"*\n")
    scratch = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        scratch.write_bytes(f"{watermark}\n".encode("ascii"))
        os.replace(scratch, path)
    finally:
        scratch.unlink(missing_ok=True)
    return path
