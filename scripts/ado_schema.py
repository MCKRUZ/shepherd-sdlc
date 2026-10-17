"""The IMPURE half of Boards discovery: read a client's process from Azure DevOps and keep it (B1-P4).

`ado_schema_map.py` turns az JSON into a plain-dict picture of the process (pure, tested on fixtures);
this module does the reads and owns the one file they are saved to, `.sdlc/ado/schema.json`.

  discover(repo_root, team)       serial GETs through `ado_transport.invoke_body`, mapped as they arrive
  load_schema / save_schema       the saved file: sorted JSON, indent 1, one trailing line feed
  schema_age_days(schema, today)  whole days since the read, or None when the date is unknown
  DISCOVER_AZ_CONTRACT            every argv prefix `discover` issues, for `test_boards_az_contract.py`

What `discover` reads, in order (each a `devops invoke` GET; the project is a route parameter, never
`--project`; every route comes from `boards_contract.WIT_ROUTES`, the one place a capture corrects):
  projects, workItemTypeCategories, workItemTypes, fields (project-wide), the team's backlog
  configuration, classificationNodes (areas and iterations, depth 3), the team's iterations,
  workItemRelationTypes — then, for each type a kind lands on, that type's fields with their allowed
  values (`workItemTypesField`, `$expand=allowedValues`). The type's states are taken from the
  workItemTypes answer, which carries every type's `states` exactly as `workItemTypeStates` answers them
  (B0 capture, 2026-10-14: equal for all seven types read), so they cost no call of their own.

The call count is bounded: eight fixed reads (six when no team is known), then exactly one
`workItemTypesField` read per landed type (`ado_schema_map.landed_types`) — at most one per kind the
mirror knows plus one, and on the captured process with the starter config four (Spec, Epic, Feature, Issue).

Three rules decide the parts that are not fixed:
  * The team is `--team`, else `team:` in `.sdlc/ado.yaml`, else the project's default team (the one
    Azure DevOps itself uses when none is named); with none of those the two team reads are skipped
    and the schema says so (`backlog: null`, `team: null`, `team_iterations: null`) instead of guessing.
  * A type's states and fields are read for every type a kind of the config lands on
    (`ado_schema_map.landed_types`: the spec's type first, then — in `KINDS` order — the type each configured
    kind, each `types.<kind>` pin and each `fields.<kind>` block resolves to, so Epic and Feature from their
    backlog categories as well as the pinned ones), resolved by `ado_schema_map.resolve_type` against what was
    already read. Without those facts a plan cannot tell a required field the process defaults (Priority 2 and
    ValueArea Business on the captured Epic) from one a create would leave empty, nor write a field such as an
    epic's Priority only where the type carries it. A pin the process lacks is skipped here (`validate` reports
    it), and a kind that rides as a tag lands nowhere. A type that was never read carries `states: null` /
    `fields: null` — unknown, not empty — and an Epic or Feature gets its states from the backlog
    configuration's own state mapping when its own were not read.
  * Nothing that names a person is saved. The project and team are reduced to their names, the only GUIDs
    are the classification nodes' `identifier`s (the join key for an iteration, not a person), and a
    picklist or default that holds an e-mail address or a GUID is withheld and noted. `save_schema` checks
    the whole document once more and refuses to write rather than write an identity.

A required call that fails raises `AdoImportError` worded `<area>/<resource>: <why>`, so the person reading
it knows which call to look at; the first failure stops the run (the reads are serial on purpose). The
module imports no subprocess: `az` is spawned only inside `ado_transport.run_az`.

Standalone or workflow: it reads and writes only under the repository root it is given (`--repo` or the
parent of `.sdlc/state.yaml`) and never reads `state.yaml` itself.
"""

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ado_schema_map as sm  # noqa: E402
import ado_sync_config as cfgmod  # noqa: E402
import ado_transport  # noqa: E402
from ado_map import AdoImportError  # noqa: E402
from boards_contract import CONFIG_FILE, EMAIL_RE, GUID_RE, SCHEMA_FILE, WIT_ROUTES  # noqa: E402

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Every `devops invoke` argv prefix `discover` issues, in the order it issues them (placeholders: P project,
# U organisation URL, T team, TY work item type). Checked against `az ... --help` by test_boards_az_contract.py
# and against the argv `discover` really emits by test_boards_sync_cli_b1.py. Read-only, `--detect false`, GA
# api-version, no `--project`.
DISCOVER_AZ_CONTRACT: tuple[list[str], ...] = (
    ["devops", "invoke", "--area", "core", "--resource", "projects", "--route-parameters", "projectId=P",
     "--http-method", "GET", "--api-version", "7.1", "--detect", "false", "--org", "U", "-o", "json"],
    ["devops", "invoke", "--area", "wit", "--resource", "workItemTypeCategories", "--route-parameters", "project=P",
     "--http-method", "GET", "--api-version", "7.1", "--detect", "false", "--org", "U", "-o", "json"],
    ["devops", "invoke", "--area", "wit", "--resource", "workItemTypes", "--route-parameters", "project=P",
     "--http-method", "GET", "--api-version", "7.1", "--detect", "false", "--org", "U", "-o", "json"],
    ["devops", "invoke", "--area", "wit", "--resource", "fields", "--route-parameters", "project=P",
     "--http-method", "GET", "--api-version", "7.1", "--detect", "false", "--org", "U", "-o", "json"],
    ["devops", "invoke", "--area", "work", "--resource", "backlogconfiguration", "--route-parameters", "project=P",
     "team=T", "--http-method", "GET", "--api-version", "7.1", "--detect", "false", "--org", "U", "-o", "json"],
    ["devops", "invoke", "--area", "wit", "--resource", "classificationNodes", "--route-parameters", "project=P",
     "--http-method", "GET", "--query-parameters", "$depth=3", "--api-version", "7.1", "--detect", "false",
     "--org", "U", "-o", "json"],
    ["devops", "invoke", "--area", "work", "--resource", "iterations", "--route-parameters", "project=P", "team=T",
     "--http-method", "GET", "--api-version", "7.1", "--detect", "false", "--org", "U", "-o", "json"],
    ["devops", "invoke", "--area", "wit", "--resource", "workItemRelationTypes", "--route-parameters", "project=P",
     "--http-method", "GET", "--api-version", "7.1", "--detect", "false", "--org", "U", "-o", "json"],
    ["devops", "invoke", "--area", "wit", "--resource", "workItemTypesField", "--route-parameters", "project=P",
     "type=TY", "--http-method", "GET", "--query-parameters", "$expand=allowedValues", "--api-version", "7.1",
     "--detect", "false", "--org", "U", "-o", "json"],
)

_NODE_LISTS = ("areas", "iterations")  # their entries' `identifier` is a GUID by design


# --- the clock (tests replace `now_utc`) ---------------------------------------------------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today() -> date:
    return now_utc().date()


# --- the saved file ----------------------------------------------------------------------------------------------

def load_schema(repo_root) -> dict | None:
    """The saved schema, or None when there is none. A file that exists but cannot be used (unreadable, not
    JSON, not an object, written by another schema version) is an `AdoImportError` that says how to replace it:
    a silent None would read as "never discovered"."""
    path = Path(repo_root) / SCHEMA_FILE
    fix = "run `ado_sync.py discover --refresh` to read it again"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise AdoImportError(f"{SCHEMA_FILE} could not be read ({type(exc).__name__}); {fix}") from None
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        raise AdoImportError(f"{SCHEMA_FILE} is not valid JSON; {fix}") from None
    if not isinstance(doc, dict) or doc.get("schema_version") != sm.SCHEMA_VERSION:
        raise AdoImportError(f"{SCHEMA_FILE} is not a schema this version reads (schema_version "
                             f"{sm.SCHEMA_VERSION} is expected); {fix}")
    return doc


def save_schema(repo_root, schema: dict) -> Path:
    """Write `.sdlc/ado/schema.json` (sorted keys, indent 1, one trailing line feed, via a temporary file and a
    rename so a crash never leaves half a file). Refuses, writing nothing, if the document would hold an e-mail
    address or a GUID anywhere but a classification node's `identifier`; the error names the place, not the value."""
    leaked = identity_paths(schema)
    if leaked:
        raise AdoImportError(f"refusing to write {SCHEMA_FILE}: it would hold an e-mail address or a GUID at "
                             f"{', '.join(leaked[:3])}" + (f" (and {len(leaked) - 3} more)" if len(leaked) > 3 else ""))
    path = Path(repo_root) / SCHEMA_FILE
    data = (json.dumps(schema, sort_keys=True, indent=1) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(path.name + ".tmp")
    try:
        scratch.write_bytes(data)
        os.replace(scratch, path)
    finally:
        scratch.unlink(missing_ok=True)
    return path


def schema_age_days(schema: dict, today) -> int | None:
    """Whole calendar days from the read to `today` (a date or a datetime), or None when the schema has no
    readable `discovered_at`. Not clamped: a read dated after `today` is a negative age, which says the clock moved."""
    stamp = schema.get("discovered_at") if isinstance(schema, dict) else None
    if not isinstance(stamp, str):
        return None
    try:
        read = datetime.fromisoformat(stamp).date()
    except ValueError:
        return None
    return (today.date() if isinstance(today, datetime) else today).toordinal() - read.toordinal()


def identity_paths(schema: dict) -> list[str]:
    """Where `schema` holds an e-mail address or a GUID, as dotted paths (a flagged key is shown as `<a key>`).
    A classification node's `identifier` is exempt: it joins an iteration to a team and names no one."""
    found: list[str] = []
    for key, value in schema.items():
        if key in _NODE_LISTS and isinstance(value, list):
            for i, node in enumerate(value):
                rest = {k: v for k, v in node.items() if k != "identifier"} if isinstance(node, dict) else node
                _scan(rest, f"{key}[{i}]", found)
        else:
            _scan(value, str(key), found)
    return found


def _is_identity(text: str) -> bool:
    return bool(EMAIL_RE.search(text) or GUID_RE.search(text))


def _scan(value, path: str, found: list[str]) -> None:
    if isinstance(value, str):
        if _is_identity(value):
            found.append(path)
    elif isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}.{key}" if not (isinstance(key, str) and _is_identity(key)) else f"{path}.<a key>"
            _scan(item, here, found)
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _scan(item, f"{path}[{i}]", found)


def _withhold_identities(schema: dict) -> list[str]:
    """Blank a field's picklist or default that holds an identity (None = unknown) and note why, in place.
    Returns the places it did so, as `Type.field.key`."""
    withheld = []
    for type_name, info in schema["types"].items():
        for ref, field in (info.get("fields") or {}).items():
            for key in ("allowed_values", "default"):
                if _holds_identity(field.get(key)):
                    field[key] = None
                    field.setdefault("_notes", []).append(f"{key} withheld: it held an e-mail address or a GUID")
                    withheld.append(f"{type_name}.{ref}.{key}")
    return withheld


def _holds_identity(value) -> bool:
    if isinstance(value, str):
        return _is_identity(value)
    if isinstance(value, (list, tuple)):
        return any(_holds_identity(v) for v in value)
    if isinstance(value, dict):
        return any(_holds_identity(v) for v in value.values())
    return False


# --- what to read ---------------------------------------------------------------------------------------------------

def discovery_config(repo_root) -> tuple[dict, str | None]:
    """The config `discover` reads its pins from, and a note when there was one it could not use. A missing
    config is normal (discover comes before `config init` for some people) and carries no note."""
    try:
        return cfgmod.load_config(repo_root), None
    except cfgmod.ConfigError as exc:
        if exc.kind == "missing":
            return {}, None
        return {}, f"{CONFIG_FILE} could not be used ({exc.kind}), so discovery ran without it; `config check` says why"


def types_to_read(schema: dict, cfg: dict) -> list[str]:
    """The work item types whose states and fields are read one by one, each once: every type a kind of the config
    lands on (`ado_schema_map.landed_types`: the spec's type first, then in `KINDS` order the type of each configured
    kind, each `types.<kind>` pin and each `fields.<kind>` block, and the BugCategory default when findings are
    mirrored). `schema` is what has been read so far (or a saved one); a kind that resolves to no type is left out."""
    return sm.landed_types(schema, cfg)


def is_reusable(schema: dict, cfg: dict, team: str | None, today) -> bool:
    """Whether a saved schema can stand in for a fresh read: it was read today, is for the team asked for (any
    team when none was), and already holds the states and fields of every type a kind of the config lands on (a
    schema saved before every landed type was read is read again)."""
    if schema_age_days(schema, today) != 0:
        return False
    cached = schema.get("team")
    cached_name = cached.get("name") if isinstance(cached, dict) else None
    if team and (not isinstance(cached_name, str) or cached_name.lower() != team.lower()):
        return False
    types = schema.get("types") if isinstance(schema.get("types"), dict) else {}
    for name in types_to_read(schema, cfg):
        info = types.get(name) or {}
        if info.get("states") is None or info.get("fields") is None:
            return False
    return True


def _pick_team(team: str | None, cfg: dict, project, notes: list[str]) -> str | None:
    for value in (team, cfg.get("team")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    default = project.get("defaultTeam") if isinstance(project, dict) else None
    name = default.get("name") if isinstance(default, dict) else None
    if isinstance(name, str) and name.strip():
        notes.append(f"no team was named (--team, or `team` in {CONFIG_FILE}); read the project's default team")
        return name.strip()
    notes.append("no team was named and the project reports no default team, so the team's backlog levels and "
                 "iterations were not read")
    return None


# --- discovery -------------------------------------------------------------------------------------------------------------

def _type_states(types_doc, type_name: str) -> list[dict]:
    """`ado_schema_map.map_type_states` of the `states` the workItemTypes answer carries for `type_name` — the list
    `workItemTypeStates` would answer (equal in the B0 capture), read with no call of its own. A shape it does not
    know is an `AdoImportError` worded `wit/workItemTypes type=<name>: <why>`, as a failed per-type read would be."""
    row = WIT_ROUTES["types"]
    label = f"{row['area']}/{row['resource']} type={type_name}"
    try:
        entry = next((t for t in sm._items(types_doc, "WorkItemType")
                      if isinstance(t, dict) and t.get("name") == type_name), None)
        if entry is None:
            raise AdoImportError(f"unexpected az shape: no WorkItemType named {type_name!r}")
        return sm.map_type_states(type_name, {"value": entry.get("states")})
    except AdoImportError as exc:
        raise AdoImportError(f"{label}: {exc}") from exc


def discover(repo_root, team: str | None = None, *, notes: list[str] | None = None, cfg: dict | None = None) -> dict:
    """Read the process and return the schema (`ado_schema_map.build_schema`'s document; saving is `save_schema`).

    `notes` collects the plain-language remarks the CLI prints (which team was used, what was withheld); `cfg`
    is an already-loaded config (default: read `.sdlc/ado.yaml`, ignoring one that cannot be used). Raises
    `AdoImportError` naming the call that failed, or that the origin is not an Azure DevOps remote."""
    notes = notes if notes is not None else []
    if cfg is None:
        cfg, note = discovery_config(repo_root)
        if note:
            notes.append(note)
    project = ado_transport.remote(repo_root).project
    commands: list[str] = []

    def read(name: str, mapper=None, *, query: dict | None = None, **params):
        row = WIT_ROUTES[name]
        label = f"{row['area']}/{row['resource']}" + (f" type={params['type']}" if "type" in params else "")
        route = {key: params[key] for key in row["route"]}
        try:
            doc = ado_transport.invoke_body(repo_root, row["area"], row["resource"], route, method=row["method"],
                                            query=query, api_version=row["api_version"])
            mapped = doc if mapper is None else mapper(doc)
        except AdoImportError as exc:
            raise AdoImportError(f"{label}: {exc}") from exc
        commands.append(label)
        return mapped

    project_doc = read("projects", projectId=project)
    team_name = _pick_team(team, cfg, project_doc, notes)
    categories = read("type_categories", sm.map_categories, project=project)
    types_doc, types = read("types", lambda doc: (doc, sm.map_types(doc)), project=project)
    fields = read("fields", sm.map_fields, project=project)
    backlog = read("backlog_config", sm.map_backlog_config, project=project, team=team_name) if team_name else None
    nodes = read("classification_nodes", sm.map_nodes, query={"$depth": "3"}, project=project)
    team_iterations = (read("team_iterations", sm.map_team_iterations, project=project, team=team_name)
                       if team_name else None)
    link_types = read("relation_types", sm.map_link_types, project=project)

    def assemble(states_by_type: dict, fields_by_type: dict) -> dict:
        return sm.build_schema(
            discovered_at=now_utc().strftime(TIMESTAMP_FORMAT), project=project_doc,
            team={"name": team_name} if team_name else None, categories=categories, types=types,
            states_by_type=states_by_type, fields_by_type=fields_by_type, fields=fields, backlog=backlog,
            nodes=nodes, team_iterations=team_iterations, link_types=link_types, commands=list(commands))

    states_by_type: dict = {}
    fields_by_type: dict = {}
    for name in types_to_read(assemble({}, {}), cfg):
        states_by_type[name] = _type_states(types_doc, name)
        fields_by_type[name] = read("type_fields", lambda doc, n=name: sm.map_type_fields(n, doc),
                                    query={"$expand": "allowedValues"}, project=project, type=name)
    schema = assemble(states_by_type, fields_by_type)
    withheld = _withhold_identities(schema)
    if withheld:
        notes.append(f"withheld {len(withheld)} field value(s) that held an e-mail address or a GUID "
                     f"(first: {withheld[0]})")
    return schema
