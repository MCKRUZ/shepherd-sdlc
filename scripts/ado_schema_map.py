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
  `states.prefer.<status>`    a state name, or a list tried in order; `states.prefer.<Type>.<status>`
                              scopes it to one type. Honoured only when the type has that state.
  `tree.fit.<kind>`           pin outcome / domain / requirement to "item", "area" or "tag"
  `tree.domains`              the domain names, so `fit_levels` can match them to Area Path nodes
                              (the caller fills it from `requirements.md`; this module reads no file)

Level numbers count portfolio backlog levels ABOVE Epic, nearest first: level 1 is the first
level above Epic. A hidden level is not a level. Epic, Feature and Spec are always items on
their categories; only the requirements tree (outcome, domain, requirement) is fitted.
"""

import re

from ado_map import AdoImportError, _require
from boards_contract import KINDS, TREE_ORDER

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
LEVEL_OF = {"requirement": 1, "domain": 2, "outcome": 3}  # portfolio levels above Epic, nearest first
TAG_FORM = {"requirement": "fr:<id>", "domain": "domain:<slug>", "outcome": "outcome:<slug>"}
_FIT_MODES = ("item", "area", "tag")
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
    deterministic (`discovered_at` is passed in). A type's `states` and `fields` are None when they
    were never read — unknown, not empty. `project` and `team` keep their `name` only."""
    for label, mapping in (("states_by_type", states_by_type), ("fields_by_type", fields_by_type)):
        stray = sorted(set(mapping) - set(types))
        if stray:
            raise AdoImportError(f"unexpected az shape: {label} names type(s) the process does not have: " + ", ".join(stray))
    areas, iterations = nodes
    merged = {}
    for name, info in types.items():
        entry = dict(info)
        entry["states"] = list(states_by_type[name]) if name in states_by_type else None
        entry["fields"] = _merge_fields(fields_by_type[name], fields) if name in fields_by_type else None
        merged[name] = entry
    return {"schema_version": SCHEMA_VERSION, "discovered_at": discovered_at,
            "project": _name_only(project, "project"), "team": _name_only(team, "team"),
            "categories": dict(categories), "types": merged, "fields": dict(fields), "backlog": backlog,
            "areas": list(areas), "iterations": list(iterations), "team_iterations": list(team_iterations),
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


def _preferred(cfg: dict, type_name: str, status: str) -> list[str]:
    prefer = _dig(cfg, "states", "prefer")
    if not isinstance(prefer, dict):
        return []
    scoped = prefer.get(type_name)
    for source in (scoped if isinstance(scoped, dict) else {}, prefer):
        value = source.get(status)
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [v for v in value if isinstance(v, str)]
    return []


def resolve_state(schema: dict, type_name: str, status: str, cfg: dict) -> tuple[str | None, str]:
    """`(state_name, reason)` for a status on a type. `states.prefer` wins when the type has that state;
    otherwise the rule for the status picks from the state categories (`rule: last-proposed`). What the
    type cannot express is `(None, why)` — a spec that was merged on a type with no Resolved or
    Completed state is not given a state it does not have."""
    name, states, from_backlog = _states_of(schema, type_name)
    if name is None:
        return None, f"type {type_name!r} is not in the process"
    if not states:
        return None, f"no states were discovered for {name}"
    by_name = {s["name"].lower(): s["name"] for s in states}
    note = ""
    wanted = _preferred(cfg, name, status) or _preferred(cfg, type_name, status)
    if wanted:
        for candidate in wanted:
            if candidate.lower() in by_name:
                return by_name[candidate.lower()], f"prefer: {by_name[candidate.lower()]}"
        note = f"prefer {wanted[0]!r} is not a state of {name}; "
    chain = STATUS_RULES.get(status)
    if chain is None:
        return None, note + f"no state rule for status {status!r}"
    skipped = []
    for category, pick in chain:
        pool = [s for s in states if s["category"] == category]
        if pool:
            reason = f"rule: {pick}-{category.lower()}"
            if skipped:
                reason += f" ({name} has no {' or '.join(skipped)} state)"
            if from_backlog:
                reason += "; states from backlog mapping"
            return (pool[0] if pick == "first" else pool[-1])["name"], note + reason
        skipped.append(category)
    return None, note + f"{name} has no {' or '.join(skipped)} state"


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
        return [], "backlog levels were not discovered"
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
        unmet = f"tree.fit pins {kind} to item, but {reason}" if pin == "item" else reason
    if kind == "domain":
        return _fit_domain(schema, cfg, "tree.fit pins domain to area" if pin == "area" else unmet)
    return _entry("tag", None, None, f"{unmet}; {tags}")


def fit_levels(schema: dict, cfg: dict) -> dict[str, dict]:
    """How each kind of the two trees lands on this process, in `TREE_ORDER`:
    `{kind: {"mode": "item"|"area"|"tag", "type", "level", "reason"}}`, and for `domain` a `names` map
    (`{name: {"mode", "area_path"}}`, from `tree.domains`).

    Auto: requirement -> the first portfolio level above Epic, domain -> the second (else an Area Path
    node whose name matches, else a tag), outcome -> `types.outcome`, else the third level, else a tag.
    `tree.fit.<kind>` pins a mode, `types.<kind>` pins a type; a pin the process cannot meet falls back
    to a tag and says so. Epic, Feature and Spec are items on their categories (`type` None when the
    process has no such category — `recommendations` says so)."""
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


def recommendations(fit: dict, schema: dict) -> list[str]:
    """One sentence per kind that is not fitted as an item: the addition to the process an
    administrator would make and what the board gains. `[]` when every kind fits. The plugin never
    makes the addition."""
    have = len(_levels_above_epic(schema)[0])
    out = []
    for kind, entry in fit.items():
        if entry["mode"] == "item" and entry["type"] is not None:
            continue
        reason = entry["reason"]
        if kind in LEVEL_OF and " pins " in reason.split("; ")[0]:  # a pin the process cannot meet
            out.append(f"{kind}: not fitted as an item ({reason.split('; ')[0]}); fix the cause named there to "
                       "mirror it as a board item.")
        elif kind == "outcome":
            out.append("outcome: add a work item type for outcomes (for example Objective) and name it in "
                       "types.outcome, or a third portfolio backlog level above Epic, so each success dimension "
                       "is its own board item; until then outcomes ride as `outcome:<slug>` tags.")
        elif kind == "domain" and have < 2:
            names = entry.get("names") or {}
            need = ("add two portfolio backlog levels above Epic (the nearer one holds requirements, the next one "
                    "holds domains)" if have == 0 else
                    "add a second portfolio backlog level above Epic (the nearer one holds requirements)")
            until = (f"until then domains ride as Area Path nodes where one matches "
                     f"({sum(1 for v in names.values() if v['mode'] == 'area')} of {len(names)}) and as "
                     "`domain:<slug>` tags otherwise." if names else "until then domains ride as `domain:<slug>` tags.")
            out.append(f"domain: {need} so each domain is its own board item; {until}")
        elif kind == "requirement" and have < 1:
            out.append("requirement: add a portfolio backlog level above Epic so each FR is its own board item "
                       "that Epics link to; until then each FR rides as an `fr:<id>` tag.")
        else:
            out.append(f"{kind}: no work item type resolves ({reason}); name one in types.{kind} or add the "
                       "missing backlog level.")
    return out
