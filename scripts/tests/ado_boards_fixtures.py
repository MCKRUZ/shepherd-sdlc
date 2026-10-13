"""Shared harness for the Azure Boards mirror tests (`test_boards_*.py`), B1-P0.

The twin of `tests/ado_fixtures.py` for work items, with two differences: route keys carry the
HTTP method (`GET wit/workItemTypes`, `PATCH wit/workItems`), and the fake is read-only unless a
test says otherwise (`writes=True`).

Fixtures live under `scripts/tests/fixtures/code_host/azure_devops/wit/`:
  * the folder itself — hand-written stand-ins for an Agile inherited process
    (`_provenance: "hand-written (unverified)"`), always wrapped `{_provenance, _command, value}`;
    `value` is the JSON `az … -o json` would print (a `devops invoke` list is `{count, value[],
    continuation_token}`) and `_command` is the B0 call the file stands in for — never run.
  * `captured/` — the B0 capture (real `az` output, anonymised) under the SAME file names;
    `load_wit()` prefers it, so a capture replaces a hand-written file with no code change.
  * `synthetic/` — hand-written processes nobody will capture (Scrum, CMMI, Basic, two-level).

Every `test_boards_*.py` starts with `from tests.ado_boards_fixtures import boards_env, az  # noqa: F401`.
`boards_env` is autouse: it forbids a real `az` AT THE SEAM ONLY (`ado_transport.run_az` raises
`AssertionError("az spawned")`, `az_binary()` points at a path that does not exist) — it never
patches `subprocess.run`, which hook and reconcile tests own. `az` swaps a `FakeBoardsAz` in for
`run_az`, so a fake never sees the `--only-show-errors` that `run_az` appends.

Same-route fixtures (B2-P0) are told apart by a refined key: a route parameter (`GET wit/updates
id=4523`), a query parameter (`GET wit/comments continuationToken=*`) or the WIQL text (`boards
query sdlc-repo:`). The fake tries those first; a test that re-answers the bare key, and not a
refinement, gets its own answer for every call on that route.

Fold B3 (B3-P0) adds the write responses (`POST wit/workItems`, `PATCH wit/workItems`, `POST
wit/comments` — the method alone tells them from the reads, and only `writes=True` answers them),
two value refinements on a query parameter (`GET wit/comments order=desc` is the recovery re-list,
`GET core/connectionData connectOptions=0` the service-principal sign-in) and the stderr texts under
`wit/errors/*.txt`: verbatim `az` error output, the hand-written ones led by one
`# hand-written (unverified)` line that `load_wit_error()` drops; a capture under
`wit/captured/errors/` with the same name wins, as `load_wit()` lets a captured document win.

Fold B5 (B5-P0) adds one page of the reporting revisions feed (`GET wit/workItemRevisions` ->
`workitemrevisions`): every page call, a first one naming `startDateTime` or a later one naming
only `continuationToken`, gets that page unless a test answers `GET wit/workItemRevisions
continuationToken=*` itself (the existing any-value refinement), so a paging test builds its own
next page.
"""

import json
from pathlib import Path

import pytest

import ado_transport
import code_host
from ado_map import AdoImportError
from boards_contract import READ_POSTS, WRITE_METHODS
from tests.ado_fixtures import ADO_REMOTE, FIXTURES

WIT = FIXTURES / "wit"
WIT_CAPTURED = WIT / "captured"
WIT_SYNTHETIC = WIT / "synthetic"
HAND_WRITTEN = "hand-written (unverified)"
FORBIDDEN_AZ = "/nonexistent/az-forbidden"

# Native az verbs that change the board; a `devops invoke` write is recognised by its method.
_WRITE_VERBS = ("repos pr work-item add", "repos pr work-item remove", "boards work-item create",
                "boards work-item update", "boards work-item delete", "boards work-item relation add",
                "boards work-item relation remove", "boards iteration team add")


def wit_path(name: str, hand_written: bool = False) -> Path:
    """`captured/` first (unless `hand_written`), then the hand-written folder, then `synthetic/`.
    A name in none of them resolves to the hand-written folder, where loading it fails loudly."""
    captured = WIT_CAPTURED / f"{name}.json"
    if not hand_written and captured.is_file():
        return captured
    own = WIT / f"{name}.json"
    synthetic = WIT_SYNTHETIC / f"{name}.json"
    return synthetic if not own.is_file() and synthetic.is_file() else own


def wit_source_of(name: str) -> str:
    """`captured` | `hand-written` | `synthetic` — which kind of evidence `load_wit(name)` rests on."""
    parent = wit_path(name).parent
    if parent == WIT_CAPTURED:
        return "captured"
    return "synthetic" if parent == WIT_SYNTHETIC else "hand-written"


def load_wit(name: str, hand_written: bool = False):
    """The az document a fixture stands for (`doc["value"]`). A `value` of null is an empty
    stdout and comes back as `[]`, exactly as `ado_transport.az_json` would read it."""
    doc = json.loads(wit_path(name, hand_written).read_text(encoding="utf-8"))
    return [] if doc["value"] is None else doc["value"]


def _arg_after(args: list[str], flag: str) -> str | None:
    return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else None


def route_params(args: list[str]) -> dict[str, str]:
    """`k=v` words after `--route-parameters`, up to the next flag."""
    if "--route-parameters" not in args:
        return {}
    out = {}
    for word in args[args.index("--route-parameters") + 1:]:
        if word.startswith("--"):
            break
        if "=" in word:
            k, _, v = word.partition("=")
            out[k] = v
    return out


def query_params(args: list[str]) -> dict[str, str]:
    """`k=v` words after `--query-parameters`, up to the next flag (B2-P0)."""
    if "--query-parameters" not in args:
        return {}
    out = {}
    for word in args[args.index("--query-parameters") + 1:]:
        if word.startswith("--"):
            break
        k, _, v = word.partition("=")
        out[k] = v
    return out


# B2-P0: the parameters that tell same-route fixtures apart, most specific first.
REFINE_QUERY_PARAMS: tuple[str, ...] = ("continuationToken",)   # key `<route> continuationToken=*` (any value)
REFINE_ROUTE_PARAMS: tuple[str, ...] = ("id", "workItemId")       # key `<route> id=<value>`
WIQL_UNTAGGED_NEEDLE = "sdlc-repo:"                               # key `boards query sdlc-repo:`
# B3-P0: query parameters whose VALUE tells same-route fixtures apart (key `<route> order=desc`), tried after the
# any-value ones and before the route parameters: the recovery re-list of any item is one fixture.
REFINE_QUERY_VALUES: tuple[str, ...] = ("order", "connectOptions")


def refined_keys(key: str, args: list[str]) -> list[str]:
    """The refined route keys a call could match, most specific first (the bare key and `type=` come after)."""
    out = []
    if key == "boards query" and WIQL_UNTAGGED_NEEDLE in (_arg_after(args, "--wiql") or ""):
        out.append(f"{key} {WIQL_UNTAGGED_NEEDLE}")
    query = query_params(args)
    out += [f"{key} {name}=*" for name in REFINE_QUERY_PARAMS if name in query]
    out += [f"{key} {name}={query[name]}" for name in REFINE_QUERY_VALUES if name in query]  # B3-P0
    route = route_params(args)
    out += [f"{key} {name}={route[name]}" for name in REFINE_ROUTE_PARAMS if name in route]
    return out


def route_key_boards(args: list[str]) -> str:
    """`GET wit/workItemTypes` | `POST wit/wiql` | `PATCH wit/workItems` for `devops invoke`
    (method defaults to GET, as az's does); otherwise the leading non-flag words, e.g.
    `boards query`, `repos pr work-item add`, `account show`."""
    words = []
    for a in args:
        if a.startswith("-"):
            break
        words.append(a)
    if words[:2] == ["devops", "invoke"]:
        method = (_arg_after(args, "--http-method") or "GET").upper()
        return f"{method} {_arg_after(args, '--area')}/{_arg_after(args, '--resource')}"
    return " ".join(words)


def is_write_key(key: str) -> bool:
    method, _, path = key.partition(" ")
    if method in WRITE_METHODS:
        area, _, resource = path.partition("/")
        return (area, resource) not in READ_POSTS
    return key in _WRITE_VERBS


# route key -> fixture name. A per-type route is refined by its `type=` route parameter
# (`GET wit/states type=Bug`); the fake tries the refined key first, then the bare one.
DEFAULT_WIT_ANSWERS: dict[str, str] = {
    "GET core/projects": "projects",
    "GET wit/workItemTypeCategories": "type_categories",
    "GET wit/workItemTypes": "types",
    "GET wit/states type=User Story": "type_states_user_story",
    "GET wit/states type=Bug": "type_states_bug",
    "GET wit/states type=Issue": "type_states_issue",
    "GET wit/fields type=User Story": "type_fields_user_story",
    "GET wit/fields type=Issue": "type_fields_issue",
    "GET wit/fields": "fields",
    "GET work/backlogconfiguration": "backlog_config",
    "GET wit/classificationNodes": "classification_nodes",
    "GET work/iterations": "team_iterations",
    "GET wit/workItemRelationTypes": "relation_types",
    "GET core/connectionData": "connection_data",
    # Fold B2 (B2-P0): item, drift and discussion reads
    "POST wit/workitemsbatch": "workitems_batch",
    "GET wit/updates": "updates",
    "GET wit/updates id=4523": "updates_after_comment",
    "GET wit/comments": "comments",
    "GET wit/comments continuationToken=*": "comments_page2",
    "GET wit/comments workItemId=4524": "comments_hostile",
    "GET wit/commentsVersions": "comment_versions",
    "boards query": "wiql_by_tag",
    "boards query sdlc-repo:": "wiql_untagged",
    "boards work-item show": "workitem_show_relations",
    "account show": "account_show",
    # Fold B3 (B3-P0): the write responses (answered only by a `writes=True` fake), the re-list, the SP sign-in
    "POST wit/workItems": "workitem_create_response",
    "PATCH wit/workItems": "workitem_update_response",
    "POST wit/comments": "comment_add_response",
    "GET wit/comments order=desc": "comments_recent",
    "GET core/connectionData connectOptions=0": "connection_data_sp",
    # Fold B5 (B5-P0): one page of the reporting revisions feed (B5-P2's watermark pull)
    "GET wit/workItemRevisions": "workitemrevisions",
}
WIT_FIXTURE_NAMES: tuple[str, ...] = tuple(sorted(set(DEFAULT_WIT_ANSWERS.values())))


def route_name_of(fixture: str) -> str:
    """The `boards_contract.WIT_ROUTES` row a hand-written fixture answers (`type_states_bug` -> `type_states`)."""
    for stem in ("type_states", "type_fields"):
        if fixture.startswith(stem + "_"):
            return stem
    renamed = {"workitems_batch": "workitemsbatch", "updates_after_comment": "updates",
               "comment_versions": "comment_versions"}  # B2-P0
    renamed.update({"workitem_create_response": "workitem_create", "workitem_update_response": "workitem_update",
                    "comment_add_response": "comments", "connection_data_sp": "connection_data"})  # B3-P0
    if fixture in renamed:
        return renamed[fixture]
    if fixture.startswith("comments_"):
        return "comments"
    return fixture


class FakeBoardsAz:
    """Stands in for `ado_transport.run_az`; returns the stdout az would print.

    `answers` maps a route key to: a fixture name (str, read with `load_wit`), a document
    (json-dumped), `None` (an empty stdout), or a callable `args -> any of those`. `fail` maps a
    needle in the joined argv to an `AdoImportError` message. Anything not answered is
    `AssertionError("unexpected az call: <key>")`; with `writes=False` a write — a WRITE_METHODS
    invoke outside READ_POSTS, or a native write verb — is `AssertionError("unexpected az write: <key>")`
    even when answered. Every call is recorded first, refused or not."""

    def __init__(self, answers: dict | None = None, fail: dict | None = None, *, writes: bool = False):
        self.answers = dict(DEFAULT_WIT_ANSWERS)
        self.answers.update(answers or {})
        self.fail = dict(fail or {})
        self.writes = writes
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], cwd, timeout: int = 60) -> str:
        args = list(args)
        self.calls.append(args)
        key = route_key_boards(args)
        if not self.writes and is_write_key(key):
            raise AssertionError(f"unexpected az write: {key}")
        joined = " ".join(args)
        for needle, message in self.fail.items():
            if needle in joined:
                raise AdoImportError(message)
        wit_type = route_params(args).get("type")
        candidates = [f"{key} type={wit_type}", key] if wit_type is not None else [key]
        candidates = [*self._refinements(key, args), *candidates]
        found = next((k for k in candidates if k in self.answers), None)
        if found is None:
            raise AssertionError(f"unexpected az call: {key}")
        answer = self.answers[found]
        if callable(answer):
            answer = answer(args)
        if answer is None:
            return ""
        if isinstance(answer, str):
            answer = load_wit(answer)
        return json.dumps(answer)

    def _refinements(self, key: str, args: list[str]) -> list[str]:
        """B2-P0: the refined keys answered for this call. When the bare key no longer carries its default
        answer (the test re-answered it), a refinement still carrying ITS default is skipped."""
        found = [k for k in refined_keys(key, args) if k in self.answers]
        if self.answers.get(key) != DEFAULT_WIT_ANSWERS.get(key):
            found = [k for k in found if self.answers[k] != DEFAULT_WIT_ANSWERS.get(k)]
        return found

    def count(self, *leading: str) -> int:
        return sum(1 for c in self.calls if c[:len(leading)] == list(leading))

    def written(self) -> list[list[str]]:
        return [c for c in self.calls if is_write_key(route_key_boards(c))]


def _forbid(*args, **kwargs):
    raise AssertionError("az spawned")


@pytest.fixture(autouse=True)
def boards_env(monkeypatch):
    ado_transport.clear_caches()
    for name in code_host.CODE_HOST_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(code_host, "origin_url", lambda root: ADO_REMOTE)
    monkeypatch.setattr(ado_transport, "az_binary", lambda: FORBIDDEN_AZ)
    monkeypatch.setattr(ado_transport, "run_az", _forbid)
    yield
    ado_transport.clear_caches()


@pytest.fixture
def az(monkeypatch) -> FakeBoardsAz:
    fake = FakeBoardsAz()
    monkeypatch.setattr(ado_transport, "run_az", fake)
    return fake


# --- Fold B3 (B3-P0): the stderr texts a failed write prints ------------------------------------------------------

WIT_ERRORS = WIT / "errors"
WIT_CAPTURED_ERRORS = WIT_CAPTURED / "errors"
# error text -> the `ado_wit_map.classify_write_error` class it must read as (and so apply's failure class)
WIT_ERROR_CLASSES: dict[str, str] = {"stale_rev": "conflict", "rule_violation": "rule", "permission": "permission",
                                     "throttled": "throttled"}
WIT_ERROR_NAMES: tuple[str, ...] = tuple(sorted(WIT_ERROR_CLASSES))


def wit_error_path(name: str, hand_written: bool = False) -> Path:
    """`captured/errors/<name>.txt` first (unless `hand_written`), then the hand-written `errors/<name>.txt`."""
    captured = WIT_CAPTURED_ERRORS / f"{name}.txt"
    if not hand_written and captured.is_file():
        return captured
    return WIT_ERRORS / f"{name}.txt"


def load_wit_error(name: str, hand_written: bool = False) -> str:
    """The stderr text as `ado_transport.run_az` would raise it (stripped): a leading `# hand-written …` or
    `# captured …` provenance line is dropped, nothing else is."""
    lines = wit_error_path(name, hand_written).read_text(encoding="utf-8").splitlines()
    if lines and (lines[0] == "# " + HAND_WRITTEN or lines[0].startswith("# captured ")):
        lines = lines[1:]
    return "\n".join(lines).strip()
