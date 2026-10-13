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
    "account show": "account_show",
}
WIT_FIXTURE_NAMES: tuple[str, ...] = tuple(sorted(set(DEFAULT_WIT_ANSWERS.values())))


def route_name_of(fixture: str) -> str:
    """The `boards_contract.WIT_ROUTES` row a hand-written fixture answers (`type_states_bug` -> `type_states`)."""
    for stem in ("type_states", "type_fields"):
        if fixture.startswith(stem + "_"):
            return stem
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
