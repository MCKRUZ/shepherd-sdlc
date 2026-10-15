"""The PURE half of Boards discovery: az JSON in, a plain-dict picture of a client's process out (B1-P2).

`ado_schema.py` (B1-P4) does the reads; everything here is a function of documents and imports no
I/O module, so the whole mapping is tested on fixtures. Two rules, the same as `ado_map.py`:

  * A key the mapping NEEDS raises `AdoImportError("unexpected az shape: missing <what>.<key>")`
    through `ado_map._require` instead of defaulting — a renamed field must fail loudly, because
    a default is how "nothing here" gets fabricated. `REQUIRED_KEYS` lists, per mapper, the keys
    read at the top of each item; the raise test iterates it.
  * An unknown enum value is KEPT and noted (`_notes`), never rewritten to a guess. And what a
    document does not say stays unknown (`None`), never `False` or `[]`.

The schema (`build_schema`) is what `.sdlc/ado/schema.json` holds. It carries no identity: the
project and team are reduced to their names, so the only GUIDs in it are the classification-node
`identifier`s. Paths are in the form work items carry (`Claims\\SDLC\\Intake`), not the REST form
(`\\Claims\\Area\\SDLC\\Intake`).

Config keys this module reads (all optional; a missing or wrong-typed one reads as "not set"):
  `types.<kind>`              pin a work item type for a kind ("types.decision: Issue")
  `states.<kind>.<status>`    the design's §6.2 shape (templates/ado/_schema.yaml): a state category
                              name, or `{category, prefer}`. `category` replaces the status rule's
                              category; `prefer` names a concrete state, honoured only when the type
                              has that state. `resolve_state` finds the kind of the type it is given
                              by inverting the `types` pins first, then the default types of the
                              categories in `STATE_KIND_CATEGORY` (and of the portfolio level a tree
                              kind is fitted to); a pin is more specific than a default.
  `tree.fit.<kind>`           pin outcome / domain / requirement to "item", "area" or "tag"
  `tree.domains`              the domain names, so `fit_levels` can match them to Area Path nodes
                              (the caller fills it from `requirements.md`; this module reads no file)

Level numbers count portfolio backlog levels ABOVE Epic, nearest first: level 1 is the first
level above Epic. A hidden level is not a level. Epic, Feature and Spec are always items on
their categories; only the requirements tree (outcome, domain, requirement) is fitted.
"""

import re

from ado_map import AdoImportError, _require
from boards_contract import CONFIG_FILE, DEFAULT_KINDS, KINDS, TREE_ORDER

SCHEMA_VERSION = 1
KNOWN_STATE_CATEGORIES = ("Proposed", "InProgress", "Resolved", "Completed", "Removed")
EPIC_CATEGORY = "Microsoft.EpicCategory"

# What each mapper reads at the top of every item (the document itself for the backlog
# configuration). The raise test deletes each in turn.
REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "map_categories": ("referenceName", "defaultWorkItemType", "workItemTypes"),
    "map_types": ("name", "referenceName", "states", "fieldInstances"),
    "map_type_states": ("name", "category"),
    "map_type_fields": ("referenceName", "alwaysRequired"),
    "map_fields": ("name", "referenceName", "type", "readOnly", "isIdentity", "isPicklist"),
    "map_backlog_config": ("portfolioBacklogs", "requirementBacklog", "taskBacklog"),
    "map_nodes": ("name", "id", "identifier", "structureType"),
    "map_team_iterations": ("name", "path"),
    "map_link_types": ("referenceName", "attributes"),
}

# A spec (or decision, finding ...) status -> the state categories that express it, tried in
# order: (category, which state of that category when there are several).
STATUS_RULES: dict[str, tuple[tuple[str, str], ...]] = {
    "draft": (("Proposed", "first"),),
    "open": (("Proposed", "first"),),
    "ready": (("Proposed", "last"),),
    "in-flight": (("InProgress", "first"),),
    "merged": (("Resolved", "first"), ("Completed", "first")),
    "decided": (("Completed", "first"),),
    "closed": (("Completed", "first"),),
    "deferred": (("Removed", "first"),),
}

# Kinds that never get a default type: the process must name one, and the nearest candidates
# present in it are listed so the person choosing is not guessing either.
CANDIDATES: dict[str, tuple[str, ...]] = {
    "spike": ("Spike", "Task"),
    "decision": ("Decision", "Issue", "Impediment"),
    "finding": ("Bug", "Issue"),
    "question": ("Issue", "Impediment"),
}
DEFAULT_CATEGORY = {"epic": "EpicCategory", "feature": "FeatureCategory", "spec": "RequirementCategory"}
# The category whose default type is a kind's type for reading its `states.<kind>.<status>` rule when no
# `types.<kind>` pin names one (resolve_state). spike and finding still get no type from `resolve_type`:
# a state rule written for them applies to their category's default type, nothing more.
STATE_KIND_CATEGORY = {"epic": "EpicCategory", "feature": "FeatureCategory", "spec": "RequirementCategory",
                       "spike": "TaskCategory", "finding": "BugCategory"}
LEVEL_OF = {"requirement": 1, "domain": 2, "outcome": 3}  # portfolio levels above Epic, nearest first
TAG_FORM = {"requirement": "fr:<id>", "domain": "domain:<slug>", "outcome": "outcome:<slug>"}
_FIT_MODES = ("item", "area", "tag")
UNKNOWN = "unknown"  # the fit mode of a tree kind whose answer waits on backlog levels that were never read
# The backlog configuration was never read (no --team, no `team`, no default team): unknown, not "none".
_LEVELS_UNREAD = (f"backlog levels were not discovered — pass --team or set `team` in {CONFIG_FILE} so discover "
                  "can read them")
_SCHEDULING = "microsoft.vsts.scheduling."
_BUILTIN_SCHEDULING = ("StoryPoints", "OriginalEstimate", "RemainingWork", "CompletedWork", "Effort", "Size",
                       "DueDate", "TargetDate", "StartDate", "FinishDate")


# --- document helpers --------------------------------------------------------------------------

def _items(doc, what: str) -> list:
    """The list an az document stands for: `{count, value: [...]}` or the bare list."""
    value = doc.get("value") if isinstance(doc, dict) else doc
    if not isinstance(value, list):
        raise AdoImportError(f"unexpected az shape: missing {what}.value")
    return value


def _list(value, what: str) -> list:
    if not isinstance(value, list):
        raise AdoImportError(f"unexpected az shape: {what} is not a list")
    return value


def _dig(obj, *keys):
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


# --- the mappers ---------------------------------------------------------------------------------

def map_categories(doc) -> dict[str, dict]:
    """`{"RequirementCategory": {"default_type": "User Story", "types": ["User Story"]}}`; the key is
    the reference name without a leading `Microsoft.` (a custom level keeps its full reference name)."""
    out = {}
    for c in _items(doc, "WorkItemTypeCategory"):
        ref = _require(c, "referenceName", "WorkItemTypeCategory")
        default = _require(_require(c, "defaultWorkItemType", "WorkItemTypeCategory"), "name",
                           "WorkItemTypeCategory.defaultWorkItemType")
        members = _list(_require(c, "workItemTypes", "WorkItemTypeCategory"), "WorkItemTypeCategory.workItemTypes")
        out[ref[len("Microsoft."):] if ref.startswith("Microsoft.") else ref] = {
            "default_type": default,
            "types": [_require(t, "name", "WorkItemTypeCategory.workItemTypes") for t in members]}
    return out


def _transitions(raw, type_name: str) -> dict | None:
    if raw is None:
        return None
    what = f"WorkItemType({type_name}).transitions"
    if not isinstance(raw, dict):
        raise AdoImportError(f"unexpected az shape: {what} is not an object")
    return {frm: [_require(t, "to", what) for t in _list(targets, what)] for frm, targets in raw.items()}


def map_types(doc) -> dict[str, dict]:
    """`{name: {"reference_name", "disabled", "transitions", "required_fields"}}`. `transitions` is
    `{from_state: [to_state, ...]}` (the `""` key is creation) or None when the answer had none;
    `disabled` reads an absent `isDisabled` as enabled."""
    out = {}
    for t in _items(doc, "WorkItemType"):
        name = _require(t, "name", "WorkItemType")
        ref = _require(t, "referenceName", "WorkItemType")
        _list(_require(t, "states", "WorkItemType"), f"WorkItemType({name}).states")
        instances = _list(_require(t, "fieldInstances", "WorkItemType"), f"WorkItemType({name}).fieldInstances")
        out[name] = {
            "reference_name": ref,
            "disabled": bool(t.get("isDisabled", False)),
            "transitions": _transitions(t.get("transitions"), name),
            "required_fields": [_require(i, "referenceName", "WorkItemType.fieldInstances") for i in instances
                                if _require(i, "alwaysRequired", "WorkItemType.fieldInstances")]}
    return out


def map_type_states(type_name: str, doc) -> list[dict]:
    """`[{"name", "category", "order"}]`, `order` being the position in the answer. A category nobody
    has seen before is kept as given with a `_notes` entry."""
    what = f"WorkItemTypeState({type_name})"
    out = []
    for position, s in enumerate(_items(doc, what)):
        entry = {"name": _require(s, "name", what), "category": _require(s, "category", what), "order": position}
        if entry["category"] not in KNOWN_STATE_CATEGORIES:
            entry["_notes"] = [f"unknown stateCategory {entry['category']!r} kept as-is"]
        out.append(entry)
    return out


def map_type_fields(type_name: str, doc) -> dict[str, dict]:
    """`{ref: {"type", "read_only", "always_required", "default", "allowed_values"}}`. The per-type route
    carries neither `type` nor `readOnly`, so those are None here and `build_schema` fills them from the
    project-wide fields; an empty `allowedValues` means unrestricted and reads as None."""
    what = f"WorkItemTypeField({type_name})"
    out = {}
    for f in _items(doc, what):
        allowed = f.get("allowedValues")
        out[_require(f, "referenceName", what)] = {
            "type": f.get("type"), "read_only": f.get("readOnly"),
            "always_required": bool(_require(f, "alwaysRequired", what)), "default": f.get("defaultValue"),
            "allowed_values": list(allowed) if isinstance(allowed, list) and allowed else None}
    return out


def map_fields(doc) -> dict[str, dict]:
    """`{ref: {"name", "type", "is_identity", "is_picklist", "read_only", "custom"}}`; custom = not a
    `System.` / `Microsoft.` field."""
    out = {}
    for f in _items(doc, "WorkItemField"):
        ref = _require(f, "referenceName", "WorkItemField")
        out[ref] = {
            "name": _require(f, "name", "WorkItemField"), "type": _require(f, "type", "WorkItemField"),
            "is_identity": bool(_require(f, "isIdentity", "WorkItemField")),
            "is_picklist": bool(_require(f, "isPicklist", "WorkItemField")),
            "read_only": bool(_require(f, "readOnly", "WorkItemField")),
            "custom": not ref.startswith(("System.", "Microsoft."))}
    return out


def _level(raw, kind: str) -> dict:
    what = f"BacklogLevelConfiguration({kind})"
    rank = _require(raw, "rank", what)
    if isinstance(rank, bool) or not isinstance(rank, (int, float)):
        raise AdoImportError(f"unexpected az shape: {what}.rank is not a number")
    members = _list(_require(raw, "workItemTypes", what), f"{what}.workItemTypes")
    return {"id": _require(raw, "id", what), "name": _require(raw, "name", what), "rank": rank, "kind": kind,
            "types": [_require(t, "name", f"{what}.workItemTypes") for t in members],
            "default_type": _require(_require(raw, "defaultWorkItemType", what), "name", f"{what}.defaultWorkItemType"),
            "hidden": bool(raw.get("isHidden", False))}


def map_backlog_config(doc) -> dict:
    """`{"levels", "effort_field", "bugs_behavior", "mapped_states"}`. `levels` runs top down by rank
    (portfolio levels, then the requirement and task backlogs), each `{id, name, rank, kind, types,
    default_type, hidden}`; `mapped_states` is `{type: {state: category}}` from the backlog's own
    state mapping ({} when absent)."""
    what = "BacklogConfiguration"
    levels = [_level(raw, "portfolio") for raw in _list(_require(doc, "portfolioBacklogs", what), f"{what}.portfolioBacklogs")]
    levels.append(_level(_require(doc, "requirementBacklog", what), "requirement"))
    levels.append(_level(_require(doc, "taskBacklog", what), "task"))
    levels.sort(key=lambda lv: -lv["rank"])
    type_fields = _dig(doc, "backlogFields", "typeFields")
    mapped = {}
    for entry in doc.get("workItemTypeMappedStates") or []:
        mapped[_require(entry, "workItemTypeName", f"{what}.workItemTypeMappedStates")] = dict(
            _require(entry, "states", f"{what}.workItemTypeMappedStates"))
    return {"levels": levels, "mapped_states": mapped, "bugs_behavior": doc.get("bugsBehavior"),
            "effort_field": type_fields.get("Effort") if isinstance(type_fields, dict) else None}


def _walk(node: dict, parent: str | None, iteration: bool, out: list) -> None:
    what = "ClassificationNode"
    name = _require(node, "name", what)
    entry = {"path": name if parent is None else f"{parent}\\{name}", "id": _require(node, "id", what),
             "identifier": _require(node, "identifier", what)}
    attributes = node.get("attributes")
    if iteration and isinstance(attributes, dict):
        for key, field in (("start", "startDate"), ("finish", "finishDate")):
            if attributes.get(field):
                entry[key] = attributes[field]
    out.append(entry)
    for child in node.get("children") or []:
        _walk(child, entry["path"], iteration, out)


def map_nodes(doc) -> tuple[list[dict], list[dict]]:
    """`(areas, iterations)`, each `{"path", "id", "identifier", "start"?, "finish"?}` in document order
    with the project root first. The path is the work-item form: the REST `\\Project\\Area\\A` is built
    from the node names as `Project\\A`."""
    areas, iterations = [], []
    for root in _items(doc, "ClassificationNode"):
        structure = _require(root, "structureType", "ClassificationNode")
        if structure not in ("area", "iteration"):
            raise AdoImportError(f"unexpected az shape: unknown ClassificationNode.structureType {structure!r}")
        _walk(root, None, structure == "iteration", areas if structure == "area" else iterations)
    return areas, iterations


def map_team_iterations(doc) -> list[dict]:
    """`[{"name", "path", "start"?, "finish"?}]` — no id (the iteration node's `identifier` is the join
    key) and no `timeFrame` (it is relative to the day it was read)."""
    out = []
    for it in _items(doc, "TeamIteration"):
        entry = {"name": _require(it, "name", "TeamIteration"), "path": _require(it, "path", "TeamIteration")}
        attributes = it.get("attributes")
        if isinstance(attributes, dict):
            for key, field in (("start", "startDate"), ("finish", "finishDate")):
                if attributes.get(field):
                    entry[key] = attributes[field]
        out.append(entry)
    return out


def map_link_types(doc) -> list[str]:
    """Reference names of the enabled links between two work items (not hyperlinks or attachments)."""
    out = []
    for r in _items(doc, "WorkItemRelationType"):
        ref = _require(r, "referenceName", "WorkItemRelationType")
        attributes = _require(r, "attributes", "WorkItemRelationType")
        usage = _require(attributes, "usage", "WorkItemRelationType.attributes")
        if usage == "workItemLink" and _require(attributes, "enabled", "WorkItemRelationType.attributes"):
            out.append(ref)
    return out


# --- the schema ----------------------------------------------------------------------------------

def _name_only(obj: dict | None, what: str) -> dict | None:
    return None if obj is None else {"name": _require(obj, "name", what)}


def _merge_fields(type_fields: dict, project_fields: dict) -> dict:
    merged = {}
    for ref, field in type_fields.items():
        entry = dict(field)
        known = project_fields.get(ref)
        if known is not None:
            for key in ("type", "read_only"):
                if entry[key] is None:
                    entry[key] = known[key]
        merged[ref] = entry
    return merged


def build_schema(*, discovered_at: str, project: dict | None, team: dict | None, categories, types,
                 states_by_type: dict, fields_by_type: dict, fields, backlog: dict | None, nodes,
                 team_iterations, link_types, commands: list[str]) -> dict:
    """Assemble the mapper outputs into the document `.sdlc/ado/schema.json` holds. Pure and
    deterministic (`discovered_at` is passed in). A type's `states` and `fields`, and `team_iterations`,
    are None when they were never read — unknown, not empty. `project` and `team` keep their `name` only."""
    for label, mapping in (("states_by_type", states_by_type), ("fields_by_type", fields_by_type)):
        stray = sorted(set(mapping) - set(types))
        if stray:
            raise AdoImportError(f"unexpected az shape: {label} names type(s) the process does not have: " + ", ".join(stray))
    areas, iterations = nodes
    team_iterations = None if team_iterations is None else list(team_iterations)  # None = never read
    merged = {}
    for name, info in types.items():
        entry = dict(info)
        entry["states"] = list(states_by_type[name]) if name in states_by_type else None
        entry["fields"] = _merge_fields(fields_by_type[name], fields) if name in fields_by_type else None
        merged[name] = entry
    return {"schema_version": SCHEMA_VERSION, "discovered_at": discovered_at,
            "project": _name_only(project, "project"), "team": _name_only(team, "team"),
            "categories": dict(categories), "types": merged, "fields": dict(fields), "backlog": backlog,
            "areas": list(areas), "iterations": list(iterations), "team_iterations": team_iterations,
            "link_types": list(link_types), "commands": list(commands)}


# --- questions about the schema ----------------------------------------------------------------------

def _type_info(schema: dict, type_name) -> tuple[str | None, dict | None]:
    """The canonical name and entry of a type, matched case-insensitively (Azure DevOps does)."""
    types = schema.get("types") or {}
    if type_name in types:
        return type_name, types[type_name]
    lowered = {n.lower(): n for n in types}
    name = lowered.get(str(type_name).lower())
    return (name, types[name]) if name else (None, None)


def _pin(cfg: dict, *keys) -> str | None:
    value = _dig(cfg, *keys)
    return value if isinstance(value, str) and value else None


def resolve_type(schema: dict, kind: str, cfg: dict) -> tuple[str | None, str]:
    """`(type_name, reason)`: the pin `types.<kind>` if set, else the default type of the kind's category
    (epic, feature, spec), else the fit (outcome, domain, requirement). A kind with no default is
    `(None, "types.<kind> not set; candidates present in process: ...")` — never a guess."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    pinned = _pin(cfg, "types", kind)
    if pinned is not None:
        name, info = _type_info(schema, pinned)
        if name is None:
            return None, f"types.{kind} pins {pinned!r} but the process has no such type"
        if info.get("disabled"):
            return None, f"types.{kind} pins {name!r} but it is disabled in this process"
        return name, f"types.{kind} pinned: {name}"
    if kind in LEVEL_OF:
        fitted = fit_levels(schema, cfg)[kind]
        if fitted["mode"] == "item":
            return fitted["type"], fitted["reason"]
        if fitted["mode"] == UNKNOWN:
            return None, f"it is not known whether {kind} is an item on this process: {fitted['reason']}"
        return None, f"{kind} is fitted as {fitted['mode']}, not an item: {fitted['reason']}"
    if kind in DEFAULT_CATEGORY:
        category = DEFAULT_CATEGORY[kind]
        entry = (schema.get("categories") or {}).get(category)
        if entry is None:
            return None, f"types.{kind} not set; the process has no {category}"
        name, info = _type_info(schema, entry["default_type"])
        if name is not None and info.get("disabled"):
            return None, f"default type of {category} ({name}) is disabled in this process"
        return entry["default_type"], f"default type of {category}"
    present = [_type_info(schema, c)[0] for c in CANDIDATES.get(kind, ()) if _type_info(schema, c)[0]]
    if present:
        return None, f"types.{kind} not set; candidates present in process: {', '.join(present)}"
    return None, f"types.{kind} not set; no candidate types present in process"


def configured_kinds(cfg: dict) -> tuple[str, ...]:
    """The kinds a config mirrors: its `kinds:` list (the known kinds, in its order), else `DEFAULT_KINDS` (the
    starter's list) when the key is absent. A `kinds:` that is not a list mirrors nothing."""
    if not isinstance(cfg, dict) or "kinds" not in cfg:
        return DEFAULT_KINDS
    raw = cfg["kinds"]
    return tuple(k for k in raw if isinstance(k, str) and k in KINDS) if isinstance(raw, (list, tuple)) else ()


def landed_types(schema: dict, cfg: dict) -> list[str]:
    """Every work item type a kind of this config lands on, each once, in the order `discover` reads them: the
    spec's type first (every plan needs it), then in `KINDS` order the type of each configured kind, of each
    `types.<kind>` pin and of each `fields.<kind>` block (`resolve_type`, so a tree kind fitted as an item counts
    and one that rides as a tag or an area does not), and the `BugCategory` default type when findings are mirrored
    (the finding source lands CRITICAL and HIGH there). A kind that resolves to no type lands nowhere and adds
    nothing, so the list is never longer than the kinds there are plus one: one per-type read each."""
    cfg = cfg if isinstance(cfg, dict) else {}
    wanted = {"spec", *configured_kinds(cfg)}
    for section in ("types", "fields"):
        block = cfg.get(section)
        if isinstance(block, dict):
            wanted.update(k for k in block if isinstance(k, str) and k in KINDS)
    names: list[str] = []
    for kind in ("spec", *(k for k in KINDS if k != "spec")):
        if kind in wanted:
            name, _ = resolve_type(schema, kind, cfg)
            if name is not None and name not in names:
                names.append(name)
    if "finding" in wanted:
        entry = (schema.get("categories") or {}).get("BugCategory")
        name, info = _type_info(schema, entry.get("default_type")) if isinstance(entry, dict) else (None, None)
        if name is not None and not info.get("disabled") and name not in names:
            names.append(name)
    return names


def _states_of(schema: dict, type_name: str) -> tuple[str | None, list[dict] | None, bool]:
    """`(canonical name, states in order, came from the backlog mapping)`."""
    name, info = _type_info(schema, type_name)
    if name is None:
        return None, None, False
    if info.get("states"):
        return name, sorted(info["states"], key=lambda s: s["order"]), False
    mapped = _dig(schema, "backlog", "mapped_states", name)
    if mapped:
        return name, [{"name": n, "category": c, "order": i} for i, (n, c) in enumerate(mapped.items())], True
    return name, None, False


def _state_rule(rule) -> tuple[str | None, str | None]:
    """`(category, prefer)` from one `states.<kind>.<status>` value: a category name, or
    `{category, prefer}`. A part that is missing, blank or wrong-typed reads as not set."""
    if isinstance(rule, dict):
        rule_category, prefer = rule.get("category"), rule.get("prefer")
    else:
        rule_category, prefer = rule, None
    return (rule_category if isinstance(rule_category, str) and rule_category else None,
            prefer if isinstance(prefer, str) and prefer else None)


def _fold(value) -> str | None:
    """A state or category name for a case-insensitive match (an unknown category is kept as given, maybe null)."""
    return value.lower() if isinstance(value, str) else None


def _kinds_on_type(schema: dict, name: str, cfg: dict) -> tuple[list[str], list[str]]:
    """`(pinned, defaulted)`, each in `KINDS` order: the kinds whose `types.<kind>` pin names the type
    `name`, and the kinds with no pin whose type it is by default — the default type of their category
    (`STATE_KIND_CATEGORY`) or, for a tree kind, of the portfolio level `fit_levels` fits it to."""
    pinned, defaulted, fit = [], [], None
    categories = schema.get("categories") or {}
    for kind in KINDS:
        pin = _pin(cfg, "types", kind)
        if pin is not None:
            if _type_info(schema, pin)[0] == name:
                pinned.append(kind)
        elif kind in STATE_KIND_CATEGORY:
            default = _dig(categories, STATE_KIND_CATEGORY[kind], "default_type")
            if isinstance(default, str) and _type_info(schema, default)[0] == name:
                defaulted.append(kind)
        elif kind in LEVEL_OF:
            fit = fit if fit is not None else fit_levels(schema, cfg)
            if fit[kind]["mode"] == "item" and fit[kind]["type"] == name:
                defaulted.append(kind)
    return pinned, defaulted


def _rule_for(schema: dict, name: str, status: str,
              cfg: dict) -> tuple[str | None, tuple[str | None, str | None], str, str | None]:
    """`(source, (category, prefer), aside, conflict)` for the type `name`: the `states.<kind>.<status>`
    rule of its kind (`source` None when that kind has no rule), a sentence noting kinds passed over
    (`aside`, "" when none), and `conflict`, the reason to refuse when equally specific kinds disagree."""
    pinned, defaulted = _kinds_on_type(schema, name, cfg)
    tier, passed = (pinned, defaulted) if pinned else (defaulted, [])
    states = _dig(cfg, "states")
    states = states if isinstance(states, dict) else {}

    def rules(kinds):
        found = [(kind, _state_rule(_dig(states, kind, status))) for kind in kinds]
        return [(kind, rule) for kind, rule in found if rule != (None, None)]

    ruled = rules(tier)
    aside = ""
    if passed:
        skipped = rules(passed)
        aside = (f"{name} is pinned by {' and '.join(f'types.{k}' for k in pinned)} and is also the default type "
                 f"for {', '.join(passed)}; the pin is more specific")
        if skipped:
            aside += f", so {' and '.join(f'states.{k}.{status}' for k, _ in skipped)} is not applied"
    if len({tuple(_fold(part) for part in rule) for _, rule in ruled}) > 1:
        keys = " and ".join(f"states.{kind}.{status}" for kind, _ in ruled)
        return None, (None, None), aside, (f"{keys} apply to {name} and disagree; pass a config whose `states` "
                                           "holds only the kind being resolved")
    if not ruled:
        return None, (None, None), aside, None
    return f"states.{ruled[0][0]}.{status}", ruled[0][1], aside, None


def resolve_state(schema: dict, type_name: str, status: str, cfg: dict) -> tuple[str | None, str]:
    """`(state_name, reason)` for a status on a type.

    The config rule is `states.<kind>.<status>` (design §6.2): a category name, or `{category, prefer}`.
    The kind is the one whose `types.<kind>` pin names this type; with no pin naming it, the kind whose
    category's default type it is (`STATE_KIND_CATEGORY`: RequirementCategory -> spec, EpicCategory -> epic,
    FeatureCategory -> feature, TaskCategory -> spike, BugCategory -> finding) or whose fitted portfolio
    level's type it is (requirement, domain, outcome). A pin is more specific than a default; the reason
    says so when both name the type. `prefer` wins when the type has that state (matched
    case-insensitively); otherwise the rule's `category` (or, with no rule, the status rule's own,
    `rule: last-proposed`) picks the state, and the reason says the preferred state was not found.
    Equally specific kinds on one type whose rules disagree are `(None, why)`, never a guess: a caller
    that knows the kind passes `cfg` with `states` narrowed to that kind (still the §6.2 shape). What the
    type cannot express is `(None, why)` too — a spec that was merged on a type with no Resolved or
    Completed state is not given a state it does not have."""
    name, states, from_backlog = _states_of(schema, type_name)
    if name is None:
        return None, f"type {type_name!r} is not in the process"
    if not states:
        return None, f"no states were discovered for {name}"
    source, (category, prefer), aside, conflict = _rule_for(schema, name, status, cfg)
    tail = f"; {aside}" if aside else ""
    if conflict is not None:
        return None, conflict + tail
    note = ""
    if prefer is not None:
        hit = next((s for s in states if _fold(s["name"]) == prefer.lower()), None)
        if hit is not None:
            reason = f"prefer: {hit['name']} ({source})"
            if category is not None and _fold(hit["category"]) != category.lower():
                reason += f"; {hit['name']} is {hit['category']}, not {category}"
            return hit["name"], reason + tail
        note = f"prefer {prefer!r} was not found among the states of {name}; "
    default = STATUS_RULES.get(status)
    if category is not None:
        pick = next((p for c, p in default or () if c.lower() == category.lower()), "first")
        chain, label = ((category, pick),), source
    elif default is None:
        return None, note + f"no state rule for status {status!r}" + tail
    else:
        chain, label = default, "rule"
    skipped = []
    for wanted, pick in chain:
        pool = [s for s in states if _fold(s["category"]) == wanted.lower()]
        if pool:
            reason = f"{label}: {pick}-{wanted.lower()}"
            if skipped:
                reason += f" ({name} has no {' or '.join(skipped)} state)"
            if from_backlog:
                reason += "; states from backlog mapping"
            return (pool[0] if pick == "first" else pool[-1])["name"], note + reason + tail
        skipped.append(wanted)
    missing = f"{name} has no {' or '.join(skipped)} state"
    return None, note + (f"{missing} ({source})" if category is not None else missing) + tail


def field_on_type(schema: dict, type_name: str, ref: str) -> dict | None:
    """The field's facts on that type, or None when the type or its fields were never read or the type
    does not carry the field (matched case-insensitively)."""
    _, info = _type_info(schema, type_name)
    fields = info.get("fields") if info else None
    if not fields:
        return None
    if ref in fields:
        return dict(fields[ref])
    lowered = {k.lower(): k for k in fields}
    return dict(fields[lowered[ref.lower()]]) if ref.lower() in lowered else None


def transition_allowed(schema: dict, type_name: str, frm: str, to: str) -> bool | None:
    """Whether the process lets `frm` go to `to` (`""` is creation); None when the type's transitions
    were not read or `frm` is not a state it lists. A no-op (`frm == to`) is allowed."""
    _, info = _type_info(schema, type_name)
    transitions = info.get("transitions") if info else None
    if transitions is None:
        return None
    if frm and frm.lower() == to.lower():
        return True
    lowered = {k.lower(): v for k, v in transitions.items()}
    targets = lowered.get(frm.lower())
    return None if targets is None else to.lower() in {t.lower() for t in targets}


def refused_fields(schema: dict) -> frozenset[str]:
    """Fields the mirror never writes: every `Microsoft.VSTS.Scheduling.*` field (points, estimates,
    hours, dates) the process has, the well-known ones whether or not the process lists them, and the
    backlog's own effort field (a custom process may call it something else)."""
    refused = {f"Microsoft.VSTS.Scheduling.{n}" for n in _BUILTIN_SCHEDULING}
    refs = list(schema.get("fields") or {})
    for info in (schema.get("types") or {}).values():
        refs.extend(info.get("fields") or {})
    refused.update(r for r in refs if r.lower().startswith(_SCHEDULING))
    effort = _dig(schema, "backlog", "effort_field")
    if effort:
        refused.add(effort)
    return frozenset(refused)


# --- fitting the requirements tree to the process ------------------------------------------------------

def _levels_above_epic(schema: dict) -> tuple[list[dict], str | None]:
    """The visible portfolio levels above Epic's, nearest first, and why none can be known."""
    backlog = schema.get("backlog")
    if not backlog:
        return [], _LEVELS_UNREAD
    portfolio = [lv for lv in backlog["levels"] if lv["kind"] == "portfolio" and not lv["hidden"]]  # top down
    index = next((i for i, lv in enumerate(portfolio) if lv["id"] == EPIC_CATEGORY), None)
    if index is None:
        index = next((i for i, lv in enumerate(portfolio) if any(t.lower() == "epic" for t in lv["types"])), None)
    if index is None:
        return [], "no Epic portfolio level found in the backlog configuration"
    return list(reversed(portfolio[:index])), None


def _entry(mode: str, type_name: str | None, level: int | None, reason: str, names: dict | None = None) -> dict:
    entry = {"mode": mode, "type": type_name, "level": level, "reason": reason}
    if names is not None:
        entry["names"] = names
    return entry


def _item_for(schema: dict, cfg: dict, kind: str, above: list[dict], why: str | None) -> tuple:
    """`(type, level, reason)` for fitting `kind` as an item, or `(None, None, why not)`."""
    pinned = _pin(cfg, "types", kind)
    if pinned is not None:
        name, info = _type_info(schema, pinned)
        if name is None:
            return None, None, f"types.{kind} pins {pinned!r} but the process has no such type"
        if info.get("disabled"):
            return None, None, f"types.{kind} pins {name!r} but it is disabled in this process"
        level = next((i + 1 for i, lv in enumerate(above) if name.lower() in (t.lower() for t in lv["types"])), None)
        return name, level, f"types.{kind} pinned: {name}"
    number = LEVEL_OF[kind]
    if len(above) < number:
        if why:
            return None, None, why
        return None, None, (f"types.outcome not set and no portfolio level {number} above Epic" if kind == "outcome"
                            else f"no portfolio level {number} above Epic")
    level = above[number - 1]
    name, info = _type_info(schema, level["default_type"])
    if name is None or info.get("disabled"):
        return None, None, f"portfolio level {number} above Epic ({level['name']}) has no usable default type"
    return name, number, f"portfolio level {number} above Epic ({level['name']})"


def _domain_names(schema: dict, cfg: dict, *, areas_ok: bool) -> dict[str, dict]:
    """Each domain name -> `{"mode": "area"|"tag", "area_path"}`: an area when a node below the project
    root has the same slug."""
    index = {}
    for node in schema.get("areas") or []:
        if "\\" in node["path"]:
            index.setdefault(_slug(node["path"].rsplit("\\", 1)[1]), node["path"])
    domains = _dig(cfg, "tree", "domains")
    out = {}
    for name in domains if isinstance(domains, list) else []:
        path = index.get(_slug(name)) if areas_ok and isinstance(name, str) else None
        out[name] = {"mode": "area" if path else "tag", "area_path": path}
    return out


def _fit_domain(schema: dict, cfg: dict, prefix: str) -> dict:
    names = _domain_names(schema, cfg, areas_ok=True)
    matched = sum(1 for v in names.values() if v["mode"] == "area")
    if not names:
        return _entry("tag", None, None, f"{prefix}; no domain names given (tree.domains), so domains ride as "
                      f"`{TAG_FORM['domain']}` tags", names)
    if not matched:
        return _entry("tag", None, None, f"{prefix}; 0 of {len(names)} domain names match an Area Path node, so "
                      f"domains ride as `{TAG_FORM['domain']}` tags", names)
    return _entry("area", None, None, f"{prefix}; {matched} of {len(names)} domain names match an Area Path node "
                  f"(the rest ride as `{TAG_FORM['domain']}` tags)", names)


def _unknown(schema: dict, cfg: dict, kind: str, reason: str) -> dict:
    """A tree kind whose fit waits on backlog levels that were never read: not known, never a fallback."""
    names = None
    if kind == "domain":
        names = {n: {"mode": UNKNOWN, "area_path": None} for n in _domain_names(schema, cfg, areas_ok=False)}
    return _entry(UNKNOWN, None, None, reason, names)


def _fit_tree_kind(schema: dict, cfg: dict, kind: str, above: list[dict], why: str | None, pin: str | None) -> dict:
    tags = f"rides as `{TAG_FORM[kind]}` tags"
    names = {} if kind == "domain" else None
    if pin == "tag":
        if kind == "domain":
            names = _domain_names(schema, cfg, areas_ok=False)
        return _entry("tag", None, None, f"tree.fit pins {kind} to tag", names)
    if pin == "area" and kind != "domain":
        return _entry("tag", None, None, f"tree.fit pins {kind} to area, which applies to domain only; fitted as a tag")
    unmet = None
    if pin != "area":
        name, level, reason = _item_for(schema, cfg, kind, above, why)
        if name is not None:
            if kind == "domain":
                names = {n: {"mode": "item", "area_path": None} for n in _domain_names(schema, cfg, areas_ok=False)}
            return _entry("item", name, level, reason, names)
        if reason == _LEVELS_UNREAD:  # the levels that decide it were never read (a types pin never lands here)
            unknown = f"tree.fit pins {kind} to item, but {reason}" if pin == "item" else reason
            return _unknown(schema, cfg, kind, unknown)
        unmet = f"tree.fit pins {kind} to item, but {reason}" if pin == "item" else reason
    if kind == "domain":
        return _fit_domain(schema, cfg, "tree.fit pins domain to area" if pin == "area" else unmet)
    return _entry("tag", None, None, f"{unmet}; {tags}")


def fit_levels(schema: dict, cfg: dict) -> dict[str, dict]:
    """How each kind of the two trees lands on this process, in `TREE_ORDER`:
    `{kind: {"mode": "item"|"area"|"tag"|"unknown", "type", "level", "reason"}}`, and for `domain` a
    `names` map (`{name: {"mode", "area_path"}}`, from `tree.domains`).

    Auto: requirement -> the first portfolio level above Epic, domain -> the second (else an Area Path
    node whose name matches, else a tag), outcome -> `types.outcome`, else the third level, else a tag.
    `tree.fit.<kind>` pins a mode, `types.<kind>` pins a type; a pin the process cannot meet falls back
    to a tag and says so. When the backlog configuration was never read (`schema["backlog"]` None: no
    --team, no `team`, no default team) a tree kind whose answer waits on those levels is `"unknown"`,
    never a fallback: a level count that was not taken is not a 0. A `types` pin, a `tree.fit` tag pin
    and a `tree.fit` area pin need no levels and are answered as usual. Epic, Feature and Spec are items
    on their categories (`type` None when the process has no such category — `recommendations` says so)."""
    above, why = _levels_above_epic(schema)
    modes = _dig(cfg, "tree", "fit")
    pins = {k: v for k, v in modes.items() if v in _FIT_MODES} if isinstance(modes, dict) else {}
    fit = {}
    for kind in TREE_ORDER:
        if kind in LEVEL_OF:
            fit[kind] = _fit_tree_kind(schema, cfg, kind, above, why, pins.get(kind))
        else:
            name, reason = resolve_type(schema, kind, cfg)
            fit[kind] = _entry("item", name, None, reason)
    return fit


def _domain_until(entry: dict) -> str:
    names = entry.get("names") or {}
    if not names:
        return "domains ride as `domain:<slug>` tags"
    matched = sum(1 for v in names.values() if v["mode"] == "area")
    return (f"domains ride as Area Path nodes where one matches ({matched} of {len(names)}) and as "
            "`domain:<slug>` tags otherwise")


def _levels_unread(kinds: list[str]) -> str:
    """The one sentence for the tree kinds whose fit waits on backlog levels that were never read: no
    count of levels (none was taken) and so no addition, only how to have discover read them."""
    which = "this kind" if len(kinds) == 1 else "these kinds"
    return (f"{', '.join(kinds)}: {_LEVELS_UNREAD}; until then it is not known whether this process has "
            f"portfolio backlog levels above Epic to hold {which} as board items, so no process addition is "
            "recommended.")


def recommendations(fit: dict, schema: dict) -> list[str]:
    """One sentence per kind that is not fitted as an item: the addition to the process an
    administrator would make and what the board gains. `[]` when every kind fits. The plugin never
    makes the addition. When the backlog levels were never read (no team), the tree kinds that wait on
    them (`"unknown"` in the fit) share exactly one sentence saying so and naming `--team` and `team`
    — a level count that was never taken is not a 0 to recommend numbered additions from."""
    above, why = _levels_above_epic(schema)
    have, unread = len(above), why == _LEVELS_UNREAD
    out, waiting, at = [], [], None
    for kind, entry in fit.items():
        if entry["mode"] == "item" and entry["type"] is not None:
            continue
        reason = entry["reason"]
        pinned = " pins " in reason.split("; ")[0]  # a pin the process cannot meet (it needs no levels)
        if entry["mode"] == UNKNOWN or (kind in LEVEL_OF and unread and not pinned):
            at = len(out) if at is None else at
            waiting.append(kind)
        elif kind in LEVEL_OF and pinned:
            out.append(f"{kind}: not fitted as an item ({reason.split('; ')[0]}); fix the cause named there to "
                       "mirror it as a board item.")
        elif kind == "outcome":
            out.append("outcome: add a work item type for outcomes (for example Objective) and name it in "
                       "types.outcome, or a third portfolio backlog level above Epic, so each success dimension "
                       "is its own board item; until then outcomes ride as `outcome:<slug>` tags.")
        elif kind == "domain" and have < 2:
            need = ("add two portfolio backlog levels above Epic (the nearer one holds requirements, the next one "
                    "holds domains)" if have == 0 else
                    "add a second portfolio backlog level above Epic (the nearer one holds requirements)")
            out.append(f"domain: {need} so each domain is its own board item; until then {_domain_until(entry)}.")
        elif kind == "requirement" and have < 1:
            out.append("requirement: add a portfolio backlog level above Epic so each FR is its own board item "
                       "that Epics link to; until then each FR rides as an `fr:<id>` tag.")
        else:
            out.append(f"{kind}: no work item type resolves ({reason}); name one in types.{kind} or add the "
                       "missing backlog level.")
    if waiting:
        out.insert(at, _levels_unread(waiting))
    return out
