"""The Azure Boards mirror's config file: load it, validate it, and start one (B1-P3).

`.sdlc/ado.yaml` says how a project's specs, epics, features and requirements map onto its Azure
DevOps process. `templates/ado/ado.yaml` is the starter every project begins from (the full key
set), `templates/ado/_schema.yaml` is the JSON Schema for its shape, and this module is the code
that reads the file and refuses an unsafe setting before anything is written to a board.

  load_config(repo_root)         the parsed file, or `ConfigError` (kind missing | invalid)
  validate_config(cfg, schema)   one row per finding; never raises, never touches a file
  init_config(repo_root)         copy the starter in and ignore the local cache folder
  write_hook_status(root, line)  the one-line status the session-start hook prints

`validate_config` returns `[{"level": ..., "message": ...}]`, each message a plain sentence naming
the key. The level is what the CLI maps to an exit code:

  refused       exit 2 — a setting that is unsafe or not known: an unknown key; a field that maps
                an activity metric (`sprint_model.is_forbidden_field`, anything under
                `Microsoft.VSTS.Scheduling.`) or that the discovered process refuses; free text or
                full descriptions switched on without a named `pii_reviewed_by`; directory lookups
                without a named `identity_scope_acknowledged_by`; a constant `fields.<kind>.<key>:
                {field, value}` aimed at a field the mirror builds itself or at an identity, holding an
                address or a GUID, or (with a schema) outside its field's allowed values; a value outside a closed set or a
                range (the shape file's `additionalProperties`, `enum`, `const`, `minimum`,
                `maximum` and `pattern` rows).
  unresolvable  exit 1 — only when a schema is given: a `types.<kind>` pin or a
                `states.<kind>.<status>.prefer` name the discovered process does not have.
  invalid       exit 1 — a key has the wrong type or a required key is missing (the shape file's
                `type` and `required` rows), or a constant also carries a `values` table. A missing or unparseable file is `load_config`'s
                `ConfigError`, not a row.

`schema` is the document `.sdlc/ado/schema.json` holds (the shape `ado_schema_map.build_schema`
returns): `types` (each with `states` and `fields`, either may be None when never read),
`categories`, `backlog.effort_field`, and an optional `refused_fields` list. It is read by key and
never imported from the schema map, so this module stays free of every `ado_*` module. A part the
schema does not carry is unknown, so its check is skipped rather than failed. With no schema the
schema-dependent checks are skipped and no `unresolvable` row can appear.

YAML 1.1 reads a bare `on`/`off` as a boolean; every on/off switch here accepts true/false and the
words "on"/"off". A bad type never also produces the enum or range row it would trigger.

Nothing here spawns a process or reads anything but the repository's `.sdlc/ado.yaml` and the
plugin's own two template files; no message echoes file content beyond the offending short value.
"""

import functools
from pathlib import Path

import jsonschema
import yaml

from boards_contract import CONFIG_FILE, EMAIL_RE, GUID_RE, HOOK_STATUS, LOCAL_DIR
from sprint_model import is_forbidden_field

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "ado"
STARTER_PATH = TEMPLATES_DIR / "ado.yaml"
SHAPE_PATH = TEMPLATES_DIR / "_schema.yaml"

_ERROR_KINDS = ("missing", "invalid", "refused")
_GITIGNORE = b"*\n"  # the local folder holds caches that must never be committed, the file itself included
_SCHEDULING_PREFIX = "microsoft.vsts.scheduling."
_METRICS = "an activity metric the standard never tracks (velocity, story points, PR count, lines of code)"
# A kind's default work item type comes from its process category (epic, feature, spec only).
_DEFAULT_CATEGORY = {"epic": "EpicCategory", "feature": "FeatureCategory", "spec": "RequirementCategory"}
# What a constant `{field, value}` may not set: the fields the mirror builds itself from the repository (a title, a
# state, the plugin tags, the description block, the History line), and the identity fields — a person reaches the
# board only through the roster (`validate_team.email_for`), never as a value typed into this file. Lower-cased.
_MIRROR_BUILT = frozenset({"system.title", "system.state", "system.tags", "system.description", "system.history",
                           "system.workitemtype", "system.id", "system.rev"})
_IDENTITY_FIELDS = frozenset({"system.assignedto", "system.createdby", "system.changedby", "system.authorizedas"})

# A shape violation of these kinds is `refused` (outside a closed set or range, or an unknown key);
# every other kind (a wrong type, a missing key) is `invalid`.
_REFUSING_VALIDATORS = frozenset({"additionalProperties", "enum", "const", "minimum", "maximum", "pattern"})
_TYPE_WORDS = {"string": "a string", "integer": "an integer", "number": "a number", "boolean": "true or false",
               "object": "a mapping", "array": "a list", "null": "null"}


class ConfigError(Exception):
    """A config file that cannot be used. `kind` is `missing` (no file), `invalid` (not YAML, not a
    mapping, or could not be read or written) or `refused`; the CLI maps them to exit 1, 1 and 2."""

    def __init__(self, message: str = "", *, kind: str = "invalid"):
        if kind not in _ERROR_KINDS:
            raise ValueError(f"unknown ConfigError kind {kind!r}; known: {', '.join(_ERROR_KINDS)}")
        super().__init__(message)
        self.kind = kind


# --- loading and starting a config ------------------------------------------------------------------

def load_config(repo_root) -> dict:
    """The parsed `.sdlc/ado.yaml`. Not validated: pass the result to `validate_config`. Raises
    `ConfigError(kind="missing")` when there is no file and `ConfigError(kind="invalid")` when it
    cannot be read, is not YAML, is empty or is not a mapping. A YAML error names the line and the
    parser's reason, never the text of the line."""
    path = Path(repo_root) / CONFIG_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"{path} does not exist; run `ado_sync.py config init` to create it.",
                          kind="missing") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path} could not be read ({type(exc).__name__}).", kind="invalid") from None
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark is not None else ""
        reason = getattr(exc, "problem", None) or "the YAML could not be parsed"
        raise ConfigError(f"{path} is not valid YAML{where}: {reason}.", kind="invalid") from None
    if doc is None:
        raise ConfigError(f"{path} is empty; it must be a mapping of keys to values.", kind="invalid")
    if not isinstance(doc, dict):
        raise ConfigError(f"{path} must be a mapping of keys to values, but it is {_describe(doc)}.", kind="invalid")
    return doc


def init_config(repo_root, *, force: bool = False) -> list[Path]:
    """Copy the starter to `.sdlc/ado.yaml` and write `.sdlc/ado/local/.gitignore` (exactly `*\\n`, so
    nothing under the local folder is ever committed). Returns the paths written, config first. A
    config that already exists raises `ConfigError(kind="invalid")` naming it, and nothing is written,
    unless `force` is true, which overwrites the config and the ignore file."""
    root = Path(repo_root)
    target = root / CONFIG_FILE
    if (target.exists() or target.is_symlink()) and not force:
        raise ConfigError(f"{target} already exists; keep it, or pass force to replace it with the starter.",
                          kind="invalid")
    gitignore = root / LOCAL_DIR / ".gitignore"
    try:
        starter = STARTER_PATH.read_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(starter)
        gitignore.parent.mkdir(parents=True, exist_ok=True)
        gitignore.write_bytes(_GITIGNORE)
    except OSError as exc:
        raise ConfigError(f"the starter config could not be written under {root} ({type(exc).__name__}).",
                          kind="invalid") from None
    return [target, gitignore]


def write_hook_status(repo_root, line: str) -> None:
    """Write `line` and a line feed to `.sdlc/ado/local/hook-status.txt`, creating the folders. The
    session-start hook prints its first line. A bare LF on every platform; UTF-8. An `OSError` is
    the caller's to handle."""
    path = Path(repo_root) / HOOK_STATUS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((line + "\n").encode("utf-8"))


# --- validation --------------------------------------------------------------------------------------

def validate_config(cfg: dict, schema: dict | None) -> list[dict]:
    """Every finding in `cfg` as `{"level", "message"}` rows: shape first (by path), then the rules
    that cross keys, then, when `schema` is a mapping, the checks against the discovered process.
    A config that is not a mapping is one `invalid` row. Never raises on the data; mutates nothing."""
    if not isinstance(cfg, dict):
        return [_row("invalid", f"The config must be a mapping of keys to values, but it is {_describe(cfg)}.")]
    schema = schema if isinstance(schema, dict) else None
    rows = _shape_rows(cfg)
    rows.extend(_rule_rows(cfg, schema))
    if schema is not None:
        rows.extend(_unresolvable_rows(cfg, schema))
    return rows


def _row(level: str, message: str) -> dict:
    return {"level": level, "message": message}


@functools.lru_cache(maxsize=1)
def _validator() -> jsonschema.Draft202012Validator:
    try:
        shape = yaml.safe_load(SHAPE_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"the plugin's config schema {SHAPE_PATH} is missing or unreadable "
                          f"({type(exc).__name__}).", kind="invalid") from None
    return jsonschema.Draft202012Validator(shape)


def _shape_rows(cfg: dict) -> list[dict]:
    """The shape file's violations, grouped by path and in path order. A `type` error at a path hides
    the other errors there: `posture: 5` is the wrong type, and that is the one finding."""
    by_path: dict[tuple, list] = {}
    for err in _validator().iter_errors(cfg):
        by_path.setdefault(tuple(err.absolute_path), []).append(err)
    rows = []
    for path in sorted(by_path, key=lambda p: tuple(str(part) for part in p)):
        errors = by_path[path]
        typed = [e for e in errors if e.validator == "type"]
        for err in typed or sorted(errors, key=lambda e: e.validator):
            rows.extend(_shape_row(err))
    return rows


def _shape_row(err) -> list[dict]:
    name = _dotted(err.absolute_path)
    ours = f"`{name}`" if name else "The config"
    validator = err.validator
    if validator == "additionalProperties":
        known = err.schema.get("properties", {})
        extra = sorted((k for k in err.instance if k not in known), key=str)
        return [_row("refused", _unknown_key(name, key, known)) for key in extra]
    if validator == "enum":
        return [_row("refused", f"{ours} is {_show(err.instance)}; it must be {_choice(err.validator_value)}.")]
    if validator in ("const", "pattern"):
        wanted = err.schema.get("description") or f"{err.validator_value!r}"
        if validator == "pattern" and name:  # propertyNames: the instance is the offending key
            return [_row("refused", f"{ours} has the key {_show(err.instance)}; it must be {wanted}.")]
        return [_row("refused", f"{ours} is {_show(err.instance)}; it must be {wanted}.")]
    if validator in ("minimum", "maximum"):
        low, high = err.schema.get("minimum"), err.schema.get("maximum")
        bound = (f"between {low} and {high}" if low is not None and high is not None
                 else f"at least {low}" if low is not None else f"at most {high}")
        return [_row("refused", f"{ours} is {_show(err.instance)}; it must be {bound}.")]
    if validator == "type":
        return [_row("invalid", f"{ours} must be {_expected(err.validator_value)}, but it is "
                                f"{_describe(err.instance)}.")]
    if validator == "required":
        missing = [k for k in err.validator_value if k not in err.instance]
        return [_row("invalid", f"The required key `{_join(name, k)}` is missing.") for k in missing]
    return [_row("invalid", f"{ours} does not match the config schema ({validator}).")]


def _unknown_key(name: str, key, known: dict) -> str:
    allowed = ", ".join(sorted(map(str, known))) or "none"
    if not name:
        return f"Unknown top-level key `{key}`; the keys allowed there are {allowed}."
    if name == "comments.events":
        return f"Unknown comment event `{_join(name, key)}`; the events allowed are {allowed}."
    return f"Unknown key `{_join(name, key)}`; the keys allowed under `{name}` are {allowed}."


def _rule_rows(cfg: dict, schema: dict | None) -> list[dict]:
    """The rules that cross keys, and the field mappings (the one check that also uses the schema)."""
    rows = []
    reviewed = _named(cfg.get("pii_reviewed_by"))
    comments = _mapping(cfg.get("comments"))
    if cfg.get("description_mode") == "full" and not reviewed:
        rows.append(_row("refused", "`description_mode` is `full`, which copies prose onto the board, so "
                                    "`pii_reviewed_by` must name the person who reviewed it for personal data."))
    if comments.get("include_text") is True and not reviewed:
        rows.append(_row("refused", "`comments.include_text` is true, which would post reason and resolution "
                                    "text, so `pii_reviewed_by` must name the person who reviewed it for "
                                    "personal data."))
    if comments.get("mention_lookup") == "identities" and not _named(comments.get("identity_scope_acknowledged_by")):
        rows.append(_row("refused", "`comments.mention_lookup` is `identities`, which looks people up in the "
                                    "directory, so `comments.identity_scope_acknowledged_by` must name the "
                                    "person who accepted that scope."))
    rows.extend(_field_rows(cfg, schema))
    return rows


def _field_rows(cfg: dict, schema: dict | None) -> list[dict]:
    """One refused row per `fields.<kind>.<key>` that maps an activity metric or a field the process
    refuses; otherwise, with a schema, one row per `values` entry its field does not allow."""
    rows = []
    refs, effort = _schema_refusals(schema) if schema is not None else (frozenset(), None)
    types = _types_of(schema) if schema is not None else None
    for kind, entries in _items(cfg.get("fields")):
        for key, rule in _items(entries):
            base = f"fields.{kind}.{key}"
            target = rule if isinstance(rule, str) else rule.get("field") if isinstance(rule, dict) else None
            target = target if isinstance(target, str) else None
            where = base if isinstance(rule, str) else f"{base}.field"
            if is_forbidden_field(key):
                rows.append(_row("refused", f"`{base}` is named for {_METRICS}; it is refused."))
            elif target is not None and target.lower().startswith(_SCHEDULING_PREFIX):
                rows.append(_row("refused", f"`{where}` targets `{target}`, a scheduling field (points, estimates, "
                                            "hours, dates) the mirror never writes; it is refused."))
            elif target is not None and (is_forbidden_field(target) or is_forbidden_field(target.rsplit(".", 1)[-1])):
                rows.append(_row("refused", f"`{where}` targets `{target}`, {_METRICS}; it is refused."))
            elif target is not None and effort is not None and target.lower() == effort:
                rows.append(_row("refused", f"`{where}` targets `{target}`, the effort field of the discovered "
                                            "backlog, which the mirror never writes; it is refused."))
            elif target is not None and target.lower() in refs:
                rows.append(_row("refused", f"`{where}` targets `{target}`, which the discovered process lists as "
                                            "a field the mirror never writes; it is refused."))
            elif isinstance(rule, dict) and "value" in rule:
                rows.extend(_constant_rows(cfg, schema, types, kind, base, target, rule))
            elif types is not None and target is not None and isinstance(rule, dict):
                rows.extend(_value_rows(cfg, schema, types, kind, base, target, rule.get("values")))
    return rows


def _constant_rows(cfg, schema, types, kind, base, target, rule: dict) -> list[dict]:
    """A constant `{field, value}`: one value written verbatim to every item of the kind, so it may not also carry a
    `values` table, may not set a field the mirror builds itself or one that names a person (a person reaches the
    board only through the roster), may not be an address or a GUID, and — with a schema — must be one of the
    field's allowed values where the discovered type has a picklist."""
    value = rule.get("value")
    if target is None or isinstance(value, (dict, list)) or value is None:
        return []  # the shape rows already name a missing field or a value of the wrong type
    if "values" in rule:
        return [_row("invalid", f"`{base}` has both `value` (a constant) and `values` (a table from the source's "
                                "own value); give one of them.")]
    if target.lower() in _MIRROR_BUILT:
        return [_row("refused", f"`{base}.field` targets `{target}`, which the mirror builds itself from the "
                                "repository; a constant cannot set it.")]
    project_field = _mapping(_mapping(schema.get("fields")).get(target)) if schema is not None else {}
    if project_field.get("is_identity") is True or target.lower() in _IDENTITY_FIELDS:
        return [_row("refused", f"`{base}.field` targets `{target}`, an identity field; a person reaches the board "
                                "only through the roster, never as a constant.")]
    if isinstance(value, str) and (EMAIL_RE.search(value) or GUID_RE.search(value)):
        return [_row("refused", f"`{base}.value` holds an address or a GUID; a constant is board-visible on every "
                                "item and never names a person or an object.")]
    allowed = _allowed_values(cfg, schema, types, kind, target) if types is not None else None
    # compared as text: Azure DevOps answers an integer field's `allowedValues` as "1", "2", ... (captured Priority)
    if allowed is not None and str(value) not in {str(a) for a in allowed}:
        return [_row("refused", f"`{base}.value` is {_show(value)}, which is not an allowed value of `{target}`; "
                                f"the allowed values are {', '.join(map(str, allowed))}.")]
    return []


def _value_rows(cfg, schema, types, kind, base, target, values) -> list[dict]:
    if not isinstance(values, dict):
        return []
    allowed = _allowed_values(cfg, schema, types, kind, target)
    if allowed is None:
        return []
    shown = ", ".join(map(str, allowed))
    return [_row("refused", f"`{base}.values.{k}` maps to {v!r}, which is not an allowed value of `{target}`; "
                            f"the allowed values are {shown}.")
            for k, v in values.items() if isinstance(v, str) and v not in allowed]


def _unresolvable_rows(cfg: dict, schema: dict) -> list[dict]:
    """Pins the discovered process cannot honour: a type it lacks, a state its type lacks."""
    types = _types_of(schema)
    if types is None:
        return []
    rows = []
    usable = sorted(n for n, info in types.items() if not (isinstance(info, dict) and info.get("disabled")))
    for kind, pinned in _items(cfg.get("types")):
        if _named(pinned) and _find_type(types, pinned) is None:
            candidates = (f"candidates present in process: {', '.join(usable)}" if usable
                          else "the discovered process lists no work item types")
            rows.append(_row("unresolvable", f"`types.{kind}` pins {pinned!r}, but the process has no work item "
                                             f"type by that name; {candidates}."))
    for kind, statuses in _items(cfg.get("states")):
        for status, rule in _items(statuses):
            prefer = rule.get("prefer") if isinstance(rule, dict) else None
            if not _named(prefer):
                continue
            names = _candidate_types(cfg, schema, types, kind)
            pool = _state_names(types, names)
            if pool is not None and prefer.lower() not in {s.lower() for s in pool}:
                holder = f"the type {names[0]}" if len(names) == 1 else "any type in the process"
                rows.append(_row("unresolvable", f"`states.{kind}.{status}.prefer` names the state {prefer!r}, but "
                                                 f"{holder} has no state by that name; candidates present in "
                                                 f"process: {', '.join(pool) or 'none'}."))
    return rows


# --- reading the discovered schema (by key; nothing imported) ----------------------------------------

def _types_of(schema: dict) -> dict | None:
    types = schema.get("types")
    return types if isinstance(types, dict) else None


def _find_type(types: dict, name) -> str | None:
    """The process's own spelling of a type name, matched case-insensitively as Azure DevOps does."""
    if not isinstance(name, str):
        return None
    if name in types:
        return name
    lowered = {n.lower(): n for n in types if isinstance(n, str)}
    return lowered.get(name.lower())


def _candidate_types(cfg: dict, schema: dict, types: dict, kind: str) -> list[str]:
    """The type(s) a kind's checks run against: its pin (none, when the pin is not in the process, as
    that is reported on its own), else its category's default type, else every type there is."""
    pinned = _mapping(cfg.get("types")).get(kind)
    if _named(pinned):
        found = _find_type(types, pinned)
        return [found] if found else []
    category = _DEFAULT_CATEGORY.get(kind)
    if category is not None:
        entry = _mapping(_mapping(schema.get("categories")).get(category))
        found = _find_type(types, entry.get("default_type"))
        if found:
            return [found]
    return [n for n in types if isinstance(n, str)]


def _state_names(types: dict, names: list[str]) -> list[str] | None:
    """The state names of those types in order, or None when none of them had its states read."""
    pool, known = [], False
    for name in names:
        info = types.get(name)
        states = info.get("states") if isinstance(info, dict) else None
        if not isinstance(states, list):
            continue
        known = True
        for state in states:
            state_name = state.get("name") if isinstance(state, dict) else None
            if isinstance(state_name, str) and state_name not in pool:
                pool.append(state_name)
    return pool if known else None


def _allowed_values(cfg: dict, schema: dict, types: dict, kind: str, ref: str) -> list | None:
    """The picklist values of a field on the kind's type(s), or None when it has no picklist there (or
    its fields were never read). With several candidate types a value is allowed if any allows it."""
    allowed = None
    for name in _candidate_types(cfg, schema, types, kind):
        info = types.get(name)
        fields = info.get("fields") if isinstance(info, dict) else None
        if not isinstance(fields, dict):
            continue
        entry = fields.get(ref)
        if entry is None:
            entry = next((v for k, v in fields.items() if isinstance(k, str) and k.lower() == ref.lower()), None)
        values = entry.get("allowed_values") if isinstance(entry, dict) else None
        if isinstance(values, list) and values:
            allowed = (allowed or []) + [v for v in values if v not in (allowed or [])]
    return allowed


def _schema_refusals(schema: dict) -> tuple[frozenset, str | None]:
    """(lower-cased refused field refs the schema declares, the backlog's effort field lower-cased)."""
    declared = schema.get("refused_fields")
    refs = (frozenset(str(r).lower() for r in declared)
            if isinstance(declared, (list, tuple, set, frozenset)) else frozenset())
    effort = _mapping(schema.get("backlog")).get("effort_field")
    return refs, effort.lower() if isinstance(effort, str) and effort else None


# --- small helpers -----------------------------------------------------------------------------------

def _mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def _items(value):
    return list(value.items()) if isinstance(value, dict) else []


def _named(value) -> bool:
    """True for a string with something in it: a person is named."""
    return isinstance(value, str) and value.strip() != ""


def _join(name: str, key) -> str:
    return f"{name}.{key}" if name else str(key)


def _dotted(path) -> str:
    out = ""
    for part in path:
        if isinstance(part, int) and not isinstance(part, bool):
            out += f"[{part}]"
        else:
            out = f"{out}.{part}" if out else str(part)
    return out


def _describe(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true or false"
    if isinstance(value, int):
        return "an integer"
    if isinstance(value, float):
        return "a decimal number"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, dict):
        return "a mapping"
    if isinstance(value, (list, tuple)):
        return "a list"
    return type(value).__name__


def _expected(type_value) -> str:
    names = [type_value] if isinstance(type_value, str) else list(type_value)
    return " or ".join(_TYPE_WORDS.get(n, n) for n in names)


def _show(value) -> str:
    """A short, safe rendering of an offending value: containers by kind, text truncated."""
    if isinstance(value, (dict, list, tuple)):
        return _describe(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    text = repr(value)
    return text if len(text) <= 40 else text[:37] + "..."


def _choice(values) -> str:
    words = []
    for v in values:
        word = "on" if v is True else "off" if v is False else str(v)
        if word not in words:
            words.append(word)
    if len(words) <= 1:
        return "".join(words)
    if len(words) == 2:
        return f"{words[0]} or {words[1]}"
    return "one of " + ", ".join(words)
