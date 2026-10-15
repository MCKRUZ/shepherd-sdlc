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

The B0 capture (2026-10-14) lands under `captured/` (see its CAPTURE-NOTES.md) and, through `load_wit()`,
becomes the default answer for every name it holds — with no change to this loader. It corrected three
locations, and the router follows: the per-type states are `GET wit/workItemTypeStates type=<T>` and the
per-type fields `GET wit/workItemTypesField type=<T>` (the old `wit/states` / `wit/fields type=` keys are gone,
so a regression to them is an "unexpected az call", as the real az refuses them), and the identity read is
`az rest` of `<org>/_apis/connectionData`, which `route_key_boards` names by the `boards_contract.REST_ROUTES` row it
reads: still `GET core/connectionData`, so every test that answers or counts that read keeps its key. The
capture also brought names no hand-written file stood in for — the Epic, Feature, `Spec` and `RAID` per-type
reads (this process has custom `Spec` and `RAID` types) — and two documents no read answers with
(`WIT_CAPTURED_REFERENCE`): the locations list and the team's field values, kept for the record.

The second capture (2026-10-15, the first live `apply`) replaced the item, write and comment answers
(`WIT_CAPTURED_ITEMS`) and two write errors, so a scenario that pins the hand-written ids (4521, ...) sets
`BOARDS_PROCESS = HAND_WRITTEN_PROCESS`. It also moved the update to `az rest --method patch` of
`<org>/<project>/_apis/wit/workitems/<id>`: `route_key_boards` names that `PATCH wit/workItems` (the
`REST_ROUTES["workitem_update"]` row's namesake), `route_params` reads its `project` and `id` from the URL, and
`body_file` finds the body behind either `--in-file <path>` or `--body @<path>`.
"""

import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

import pytest

import ado_transport
import code_host
from ado_map import AdoImportError
from boards_contract import READ_POSTS, REST_ROUTES, WIT_ROUTES, WRITE_METHODS
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


# B0 (2026-10-15): True while a test of a module that reads the hand-written ITEM fixtures runs (`BOARDS_ITEMS` or
# `BOARDS_PROCESS` set to HAND_WRITTEN_PROCESS; `boards_env` sets it per test). The second capture shadowed the item,
# write and comment answers (`WIT_CAPTURED_ITEMS`) that those modules' scenarios pin ids and texts of; for them
# `load_wit(name)` and every fake answer of such a name stay hand-written. The captures are read by name elsewhere.
_HAND_WRITTEN_ITEMS = [False]


def load_wit(name: str, hand_written: bool = False):
    """The az document a fixture stands for (`doc["value"]`). A `value` of null is an empty
    stdout and comes back as `[]`, exactly as `ado_transport.az_json` would read it. In a module that reads the
    hand-written item fixtures (`_HAND_WRITTEN_ITEMS`), a `WIT_CAPTURED_ITEMS` name is read hand-written."""
    hand_written = hand_written or (_HAND_WRITTEN_ITEMS[0] and name in WIT_CAPTURED_ITEMS)
    doc = json.loads(wit_path(name, hand_written).read_text(encoding="utf-8"))
    return [] if doc["value"] is None else doc["value"]


def load_captured(name: str):
    """B0 (2026-10-15): the CAPTURED document of `name` (`captured/<name>.json`'s `value`), whatever the module reads
    by default; a name nothing captured is a FileNotFoundError."""
    doc = json.loads((WIT_CAPTURED / f"{name}.json").read_text(encoding="utf-8"))
    return [] if doc["value"] is None else doc["value"]


def _arg_after(args: list[str], flag: str) -> str | None:
    return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else None


def _rest_template_re(template: str) -> re.Pattern:
    """B0 write fixes: a `boards_contract.REST_ROUTES` path template as a regex over an `az rest --url` path, each
    `{name}` a named group of one path segment (the URL's own spelling, percent-decoded by the caller)."""
    parts = re.split(r"\{([a-z]+)\}", template)
    pattern = "".join(re.escape(p) if i % 2 == 0 else f"(?P<{p}>[^/]+)" for i, p in enumerate(parts))
    return re.compile(rf"(?:^|/){pattern}$")


def rest_route(args: list[str]) -> tuple[str, dict[str, str]] | None:
    """B0 write fixes: `(REST_ROUTES name, the values its template's `{name}`s took)` for an `az rest` argv whose
    `--url` path matches one row's template, else None. The method is not matched: the route key carries the argv's
    own method, so a POST of the identity URL is still named (and refused as) a write of that row."""
    if args[:1] != ["rest"]:
        return None
    path = urlsplit(_arg_after(args, "--url") or "").path
    for name, row in REST_ROUTES.items():
        found = _rest_template_re(row["path"]).search(path)
        if found:
            return name, {k: unquote(v) for k, v in found.groupdict().items()}
    return None


def body_file(args: list[str]) -> str | None:
    """B0 write fixes: the request body file an argv carries — `--in-file <path>` (`devops invoke`) or `--body @<path>`
    (`az rest`) — or None."""
    if "--in-file" in args:
        return _arg_after(args, "--in-file")
    body = _arg_after(args, "--body") if args[:1] == ["rest"] else None
    return body[1:] if isinstance(body, str) and body.startswith("@") else None


def route_params(args: list[str]) -> dict[str, str]:
    """`k=v` words after `--route-parameters`, up to the next flag; for `az rest` of a REST_ROUTES template, the values
    its `{name}`s took in the `--url` (B0 write fixes: the update is `az rest`, its route is in its URL)."""
    found = rest_route(args)
    if found is not None:
        return found[1]
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
    """`k=v` words after `--query-parameters`, up to the next flag (B2-P0); for `az rest`, the query string of its
    `--url` (B0)."""
    if args[:1] == ["rest"]:
        return dict(parse_qsl(urlsplit(_arg_after(args, "--url") or "").query, keep_blank_values=True))
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
# B0 (plan fixes): the per-type fields read, and the answer it is derived from for a type no fixture was written for
TYPE_FIELDS_KEY = "GET wit/workItemTypesField"
TYPES_KEY = "GET wit/workItemTypes"


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
    if words == ["rest"]:
        return rest_route_key(args)
    return " ".join(words)


def rest_route_key(args: list[str]) -> str:
    """B0: an `az rest` call is named by the `boards_contract.REST_ROUTES` row whose method and path template its
    `--method` and `--url` match, as that row's `WIT_ROUTES` namesake (`GET core/connectionData`; since the B0 write
    fixes also `PATCH wit/workItems`, the update); any other is `<METHOD> rest <path>`, which no default answers."""
    method = (_arg_after(args, "--method") or "GET").upper()
    found = rest_route(args)
    if found is not None:
        name = found[0]
        return f"{method} {WIT_ROUTES[name]['area']}/{WIT_ROUTES[name]['resource']}"
    return f"{method} rest {urlsplit(_arg_after(args, '--url') or '').path}"


FIXTURE_ORG_URL = "https://dev.azure.com/contoso"  # what tests.ado_fixtures.ADO_REMOTE parses to


def identity_rest_argv(org_url: str = FIXTURE_ORG_URL) -> list[str]:
    """B0: the one `az rest` argv the plugin sends (the identity read), as the seam hands it to `run_az`."""
    row = REST_ROUTES["connection_data"]
    return ado_transport.rest_argv(org_url, row["path"], row["api_version"])


def is_identity_rest_read(args: list[str], org_url: str = FIXTURE_ORG_URL) -> bool:
    """True for exactly `identity_rest_argv()` and nothing else. A seam check lets that one argv through without
    `--detect false` (`az rest` has no such flag); any other `az rest` still fails the check it would have failed."""
    return list(args) == identity_rest_argv(org_url)


def is_write_key(key: str) -> bool:
    method, _, path = key.partition(" ")
    if method in WRITE_METHODS:
        area, _, resource = path.partition("/")
        return (area, resource) not in READ_POSTS
    return key in _WRITE_VERBS


# route key -> fixture name. A per-type route is refined by its `type=` route parameter
# (`GET wit/workItemTypeStates type=Bug`); the fake tries the refined key first, then the bare one.
DEFAULT_WIT_ANSWERS: dict[str, str] = {
    "GET core/projects": "projects",
    "GET wit/workItemTypeCategories": "type_categories",
    "GET wit/workItemTypes": "types",
    # B0 (2026-10-14): the corrected per-type locations (`wit/states` and `wit/fields type=` do not exist)
    "GET wit/workItemTypeStates type=User Story": "type_states_user_story",
    "GET wit/workItemTypeStates type=Bug": "type_states_bug",
    "GET wit/workItemTypeStates type=Issue": "type_states_issue",
    "GET wit/workItemTypeStates type=Epic": "type_states_epic",
    "GET wit/workItemTypeStates type=Feature": "type_states_feature",
    "GET wit/workItemTypeStates type=Spec": "type_states_spec",
    "GET wit/workItemTypeStates type=RAID": "type_states_raid",
    "GET wit/workItemTypesField type=User Story": "type_fields_user_story",
    "GET wit/workItemTypesField type=Issue": "type_fields_issue",
    "GET wit/workItemTypesField type=Epic": "type_fields_epic",
    "GET wit/workItemTypesField type=Feature": "type_fields_feature",
    "GET wit/workItemTypesField type=Spec": "type_fields_spec",
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
# B0: the names only the capture holds (no hand-written stand-in was ever written for them)
WIT_CAPTURED_ONLY: tuple[str, ...] = ("type_fields_epic", "type_fields_feature", "type_fields_spec", "type_states_epic",
                                      "type_states_feature", "type_states_raid", "type_states_spec")
# B0: captured documents no read answers with — the `devops invoke` locations list (its wit/work/core subset) and
# the team's area settings (`work/teamfieldvalues`, which the plugin does not read); and from the second capture
# (2026-10-15) a query for every item one repository tagged and a `Spec` create with a parent. Loaded by name, never
# routed.
WIT_CAPTURED_REFERENCE: tuple[str, ...] = ("invoke_locations", "team_field_values", "wiql_repo_tag",
                                           "workitem_create_response_spec")
# B0 (2026-10-15): the item, write and discussion names the second capture replaced (each has a hand-written twin)
WIT_CAPTURED_ITEMS: tuple[str, ...] = ("comment_add_response", "comments", "updates", "wiql_by_tag",
                                       "workitem_create_response", "workitem_show_relations",
                                       "workitem_update_response", "workitems_batch")


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
    even when answered. Every call is recorded first, refused or not.

    `hand_written=True` (B0) answers a fixture name from the hand-written file even where a capture exists
    (`load_wit(name, hand_written=True)`): the process the item fixtures were written for (see `BOARDS_PROCESS`).

    One read is answered without a fixture: a per-type fields read (`GET wit/workItemTypesField type=<T>`) for a type
    no file was written for in this provenance is derived from the same fake's workItemTypes answer
    (`_type_fields_from_types`), because `discover` reads every type a kind lands on and the hand-written and
    synthetic processes only ever had User Story and Issue written out. A type that answer does not name is still
    unexpected."""

    def __init__(self, answers: dict | None = None, fail: dict | None = None, *, writes: bool = False,
                 hand_written: bool = False):
        self.answers = dict(DEFAULT_WIT_ANSWERS)
        self.answers.update(answers or {})
        self.fail = dict(fail or {})
        self.writes = writes
        self.hand_written = hand_written
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
        if key == TYPE_FIELDS_KEY and wit_type is not None and (
                found is None or (isinstance(self.answers[found], str)
                                  and not wit_path(self.answers[found], self.hand_written).is_file())):
            return json.dumps(self._type_fields_from_types(wit_type))
        if found is None:
            raise AssertionError(f"unexpected az call: {key}")
        answer = self.answers[found]
        if callable(answer):
            answer = answer(args)
        if answer is None:
            return ""
        if isinstance(answer, str):
            answer = load_wit(answer, self.hand_written)
        return json.dumps(answer)

    def _type_fields_from_types(self, wit_type: str) -> dict:
        """B0 (plan fixes): the per-type fields answer of a type no fixture was written for, derived from the
        workItemTypes answer this fake gives for the same process: that type's `fieldInstances` (reference name,
        `alwaysRequired`, `defaultValue`), each with `allowedValues: []` (unrestricted, since that answer carries
        none). `discover` reads every type a kind lands on (Epic and Feature too), and the hand-written and synthetic
        processes never had those per-type documents written; a type the answer does not name is still
        `AssertionError("unexpected az call")`."""
        types = self.answers.get(TYPES_KEY)
        doc = load_wit(types, self.hand_written) if isinstance(types, str) else types
        entries = doc.get("value") if isinstance(doc, dict) else None
        entry = next((t for t in entries or [] if isinstance(t, dict) and t.get("name") == wit_type), None)
        if entry is None:
            raise AssertionError(f"unexpected az call: {TYPE_FIELDS_KEY} type={wit_type}")
        fields = [{**f, "allowedValues": [], "dependentFields": []} for f in entry.get("fieldInstances") or []]
        return {"count": len(fields), "value": fields, "continuation_token": None}

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
def boards_env(monkeypatch, request):
    ado_transport.clear_caches()
    for name in code_host.CODE_HOST_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(code_host, "origin_url", lambda root: ADO_REMOTE)
    monkeypatch.setattr(ado_transport, "az_binary", lambda: FORBIDDEN_AZ)
    monkeypatch.setattr(ado_transport, "run_az", _forbid)
    _HAND_WRITTEN_ITEMS[0] = uses_hand_written_items(request.module)
    yield
    _HAND_WRITTEN_ITEMS[0] = False
    ado_transport.clear_caches()


# B0: a test module that sets `BOARDS_PROCESS = HAND_WRITTEN_PROCESS` gets an `az` that reads the hand-written process
# even where a capture exists. The item, history, discussion and write fixtures are hand-written for that process (a
# User Story spec type, areas under `Claims\SDLC`, a picklist spelled HIGH/MEDIUM/LOW) and nothing captured them yet,
# so a scenario that combines items with a process keeps them consistent until a capture brings both from one board.
HAND_WRITTEN_PROCESS = "hand-written"


def uses_hand_written_process(module) -> bool:
    return getattr(module, "BOARDS_PROCESS", None) == HAND_WRITTEN_PROCESS


def uses_hand_written_items(module) -> bool:
    """B0 (2026-10-15): a module that sets `BOARDS_ITEMS = HAND_WRITTEN_PROCESS` (or the whole `BOARDS_PROCESS`) reads
    the hand-written item, write and comment fixtures, whose ids and texts its scenarios pin, not the capture."""
    return uses_hand_written_process(module) or getattr(module, "BOARDS_ITEMS", None) == HAND_WRITTEN_PROCESS


@pytest.fixture
def az(monkeypatch, request) -> FakeBoardsAz:
    fake = FakeBoardsAz(hand_written=uses_hand_written_process(request.module))
    monkeypatch.setattr(ado_transport, "run_az", fake)
    return fake


# --- Fold B3 (B3-P0): the stderr texts a failed write prints ------------------------------------------------------

WIT_ERRORS = WIT / "errors"
WIT_CAPTURED_ERRORS = WIT_CAPTURED / "errors"
# error text -> the `ado_wit_map.classify_write_error` class it must read as (and so apply's failure class)
WIT_ERROR_CLASSES: dict[str, str] = {"stale_rev": "conflict", "rule_violation": "rule", "permission": "permission",
                                     "throttled": "throttled"}
WIT_ERROR_NAMES: tuple[str, ...] = tuple(sorted(WIT_ERROR_CLASSES))
# B0: the refusals the capture met, under `captured/errors/` only (no hand-written twin): the old states location,
# `connectionData` through `devops invoke` (area core, area Location), and through `az rest` at `7.1`
WIT_CAPTURED_ERROR_NAMES: tuple[str, ...] = ("connection_data_core", "connection_data_location",
                                             "connection_data_rest_7.1", "states_wrong_resource")
# B0 write fixes (2026-10-15): what the first live apply and its probes met. Two replace a hand-written text of the
# same name (`stale_rev`, `rule_violation`: `load_wit_error` serves the capture); the rest have no twin.
WIT_CAPTURED_WRITE_ERROR_NAMES: tuple[str, ...] = ("create_dollar_type", "identity_unknown", "invoke_patch_keyerror",
                                                   "preview_rev", "rule_violation", "stale_rev")
# a captured write error -> the `classify_write_error` class it must read as (`invoke_patch_keyerror` and
# `preview_rev` are the extension failing inside itself, before any request: `unknown`)
WIT_CAPTURED_ERROR_CLASSES: dict[str, str] = {"stale_rev": "conflict", "rule_violation": "rule",
                                              "identity_unknown": "rule", "create_dollar_type": "not_found",
                                              "invoke_patch_keyerror": "unknown", "preview_rev": "unknown"}


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
