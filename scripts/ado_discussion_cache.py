"""The Azure Boards mirror's local discussion cache (B2-P4b): what `pull --discussion` read, kept on this machine.

A work item's comments live in `.sdlc/ado/local/discussion/<id>.json`; `me.json` beside the folder remembers who the
signed-in Azure DevOps user is (a roster `@handle` and an identity id, never an address). Both are local only:
`.sdlc/ado/local/` is ignored by git (`ado_sync_config.init_config` writes the ignore file), and this module writes the
same ignore file itself, before any comment text lands in the folder, if a clone never ran `config init`. It is the one
module that reads and writes those files, and it is a library part usable two ways like every part of the plugin:

  * Workflow mode — `ado_sync.py --state .sdlc/state.yaml …` hands in `repo_root` and the parsed `.sdlc/ado.yaml`.
  * Standalone — any caller passes a directory and plain dicts; nothing here needs `state.yaml` and nothing here
    reads the board or runs `az`.

The cache document is whatever the caller (the pure `ado_discussion_map`, via `pull --discussion`) built, plus two
keys this module owns: `schema` (stamped `1` on every save) and `work_item` (a positive integer the caller must set; it
names the file, and a cache found under another id is not trusted). An `as_of` ISO timestamp, when present, is what
`gc` ages the file by.

  * `save_cache` — sorted, indented JSON through a temporary file and a rename, so a crash never leaves half a file.
  * `load_cache` / `load_me` — the document, or `None` for one that is missing, unreadable, another schema or filed under
    another id. A cache is a convenience: an untrusted one is simply rewritten by the next pull, never an error.
  * `gc` — deletes a cache older than `discussion.retain_days` (default 90) and the cache of an item whose last ledger
    word is an UNLINK disposition, by the same rule `ado_sync_model.summarize` uses to stop counting it as linked.
    `dry_run=True` returns the list and deletes nothing. It returns what it removed (or would); the caller appends the
    `discussion_gc` ledger line, so a failed append is the caller's `DRIFT`, not a silent delete. A failed delete
    raises its `OSError`.

Nothing here writes the ledger, an identity, or anything outside `.sdlc/ado/local/`.
"""

import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Final

import boards_contract as bc

SCHEMA: Final = 1
DEFAULT_RETAIN_DAYS: Final = 90  # templates/ado/ado.yaml: discussion.retain_days

_CACHE_FILE: Final = re.compile(r"[1-9][0-9]*\.json")  # what cache_path writes; anything else is somebody else's
_GITIGNORE: Final = b"*\n"
_LINKING_EVENTS: Final = ("linked", "adopted", "applied")


def _is_id(value) -> bool:
    return type(value) is int and value >= 1


def _check_id(wid) -> int:
    if not _is_id(wid):
        raise ValueError(f"a work item id is a positive integer, not {wid!r}")
    return wid


def _day(text) -> date | None:
    """The calendar day of an ISO timestamp (a trailing Z allowed), or None when it does not read as one."""
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.strip().replace("Z", "+00:00")).date()
    except ValueError:
        return None


# --- reading and writing -------------------------------------------------------------------------------------------

def _read(path: Path) -> dict | None:
    """The JSON object at `path` if it is a schema-1 document; None for anything else, including a missing file."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # a missing or unreadable file, bad UTF-8, bad JSON
        return None
    if not isinstance(doc, dict) or type(doc.get("schema")) is not int or doc["schema"] != SCHEMA:
        return None
    return doc


def _write(root: Path, path: Path, doc: dict) -> Path:
    try:
        data = (json.dumps(doc, sort_keys=True, indent=1, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as err:
        raise ValueError(f"the document must be JSON: {err}") from None
    ignore = root / bc.LOCAL_DIR / ".gitignore"
    ignore.parent.mkdir(parents=True, exist_ok=True)
    if not (ignore.exists() or ignore.is_symlink()):  # ignored before any comment text exists; never clobbered
        ignore.write_bytes(_GITIGNORE)
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        scratch.write_bytes(data)
        os.replace(scratch, path)
    finally:
        scratch.unlink(missing_ok=True)
    return path


def cache_path(repo_root, wid: int) -> Path:
    """`<repo>/.sdlc/ado/local/discussion/<wid>.json`. Creates nothing; `wid` must be a positive integer."""
    return Path(repo_root) / bc.DISCUSSION_DIR / f"{_check_id(wid)}.json"


def load_cache(repo_root, wid: int) -> dict | None:
    """The cache for work item `wid`, or None when there is none worth trusting."""
    doc = _read(cache_path(repo_root, wid))
    return doc if doc is not None and doc.get("work_item") == wid and type(doc["work_item"]) is int else None


def save_cache(repo_root, doc: dict) -> Path:
    """Write `doc` as the cache of work item `doc["work_item"]`, stamping `schema: 1`; returns the path. ValueError
    (and nothing written) for a document that is not a mapping, has no positive-integer `work_item`, carries another
    `schema`, or is not JSON. The `doc` passed in is not changed."""
    if not isinstance(doc, dict):
        raise ValueError("the cache document must be a mapping")
    wid = _check_id(doc.get("work_item"))
    schema = doc.get("schema", SCHEMA)
    if type(schema) is not int or schema != SCHEMA:
        raise ValueError(f"this module writes cache schema {SCHEMA}, not {schema!r}")
    root = Path(repo_root)
    return _write(root, cache_path(root, wid), {**doc, "schema": SCHEMA})


def load_me(repo_root) -> dict | None:
    """`{"schema", "handle", "id", "as_of"}` from `.sdlc/ado/local/me.json`, or None when it is absent or untrusted."""
    return _read(Path(repo_root) / bc.ME_FILE)


def save_me(repo_root, handle: str | None, ident_id: str | None, as_of: str) -> Path:
    """Remember who the signed-in user is: a roster `@handle` (None = not on the roster), the identity id (None =
    not read), and the ISO time it was read. Unknown stays None, never "". ValueError, writing nothing, for a handle
    that is not an `@handle`, an id that is blank or an address, or an `as_of` that is not an ISO timestamp."""
    if handle is not None and not (isinstance(handle, str) and bc.HANDLE_RE.fullmatch(handle)):
        raise ValueError("handle must be a roster @handle or None")
    if ident_id is not None and not (isinstance(ident_id, str) and ident_id.strip()
                                     and not bc.EMAIL_RE.search(ident_id)):
        raise ValueError("ident_id must be an identity id (not blank, not an e-mail address) or None")
    if _day(as_of) is None:
        raise ValueError("as_of must be an ISO timestamp, e.g. 2026-10-13T08:00Z")
    root = Path(repo_root)
    return _write(root, root / bc.ME_FILE, {"schema": SCHEMA, "handle": handle, "id": ident_id, "as_of": as_of})


# --- gc ------------------------------------------------------------------------------------------------------------------

def _retain_days(cfg) -> int:
    if not isinstance(cfg, dict):
        raise ValueError("cfg must be the parsed .sdlc/ado.yaml mapping")
    block = cfg.get("discussion")
    if block is None:
        return DEFAULT_RETAIN_DAYS
    if not isinstance(block, dict):
        raise ValueError("discussion must be a mapping")
    days = block.get("retain_days", DEFAULT_RETAIN_DAYS)
    if type(days) is not int or days < 0:
        raise ValueError(f"discussion.retain_days must be a non-negative integer, not {days!r}")
    return days


def _unlinked_items(root: Path) -> set[int]:
    """Work item ids whose last ledger word is UNLINK: the rule `ado_sync_model.summarize` uses for `linked`. A ref is
    linked by a `linked`/`adopted`/`applied` line with an integer `work_item`; a `reconciled` line with no `field` and
    the UNLINK disposition unlinks it; linking it again undoes that. An item a ref still points at (this one again,
    or another) is not unlinked."""
    try:
        text = (root / bc.LEDGER).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return set()
    linked: dict[str, int] = {}
    unlinked: set[int] = set()
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("event") not in bc.LEDGER_EVENTS:
            continue
        ref, event = entry.get("ref"), entry["event"]
        if not isinstance(ref, str) or not ref:
            continue
        if event in _LINKING_EVENTS and _is_id(entry.get("work_item")):
            linked[ref] = entry["work_item"]
        elif (event == "reconciled" and ref in linked and not entry.get("field")
              and str(entry.get("disposition")).strip().upper().replace("-", "_") == "UNLINK"):
            unlinked.add(linked.pop(ref))
    return unlinked - set(linked.values())


def _cached_on(path: Path) -> date:
    """The day this cache was read: its document's `as_of`, else the file's own modification day."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = None
    read = _day(doc.get("as_of")) if isinstance(doc, dict) else None
    return read if read is not None else date.fromtimestamp(path.stat().st_mtime)


def gc(repo_root, cfg: dict, today, *, dry_run: bool) -> list[Path]:
    """Delete every cache older than `discussion.retain_days` (a file read exactly that many days ago is kept) and
    every cache of an unlinked item; returns the paths, in item-number order, that were deleted (with `dry_run`, that
    would be). `today` is a date or a datetime. ValueError for a retention that is not a non-negative integer, TypeError
    for a `today` that is neither; in both cases nothing is deleted. Only files named `<n>.json` are touched, and a
    symlink or folder with such a name is left alone."""
    keep_days = _retain_days(cfg)
    if isinstance(today, datetime):
        today = today.date()
    if not isinstance(today, date):
        raise TypeError("today must be a date or a datetime")
    root = Path(repo_root)
    folder = root / bc.DISCUSSION_DIR
    if not folder.is_dir():
        return []
    unlinked = _unlinked_items(root)
    doomed: list[tuple[int, Path]] = []
    for entry in folder.iterdir():
        if not _CACHE_FILE.fullmatch(entry.name) or entry.is_symlink() or not entry.is_file():
            continue
        wid = int(entry.stem)
        try:
            expired = (today - _cached_on(entry)).days > keep_days
        except FileNotFoundError:  # removed since the listing: nothing left to do
            continue
        if wid in unlinked or expired:
            doomed.append((wid, entry))
    paths = [path for _, path in sorted(doomed)]
    if not dry_run:
        for path in paths:
            path.unlink(missing_ok=True)  # another process may have removed it first; any other failure surfaces
    return paths
