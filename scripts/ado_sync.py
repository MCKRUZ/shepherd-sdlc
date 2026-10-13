"""ado_sync.py -- The CLI of the Azure Boards mirror: set it up, read the client's process, check the fit (B1).

Azure DevOps Boards is a board the team already uses; this mirror projects the repository's specs, epics and
features onto it and reads board changes back. The skeleton below carries the verbs that never touch a work
item (the later Folds add `plan`, `pull`, `apply` and the rest to `VERBS`):

  config init [--force]   copy the starter `.sdlc/ado.yaml` in and ignore the local cache folder
  config check            the config's findings, one per line (against the saved schema when there is one)
  discover [--team T] [--refresh]
                          read the process with serial `devops invoke` GETs, save `.sdlc/ado/schema.json`
  validate                every configured kind resolves on the discovered process; the fit table and the
                          process additions an administrator would make for what does not fit as an item

What it reads
  - `.sdlc/ado.yaml` (the config) and `.sdlc/ado/schema.json` (what `discover` saved)
  - Azure DevOps through `ado_transport.invoke_body`, for `discover` only; `az` is never called twice for
    the same answer and never probed to explain a failure (the `host` block reads the failure it was given)
What it writes
  - `config init`: `.sdlc/ado.yaml` and `.sdlc/ado/local/.gitignore`; `discover`: `.sdlc/ado/schema.json`
  - Nothing else: never `state.yaml`, never a spec, never the board. `--help` and an import write nothing.

Exit codes (the kit's verb table)
  config init   0 written  | 1 the config exists and no --force
  config check  0 valid    | 1 missing, not YAML, wrong type, or a pin the process lacks | 2 refused (an unknown key,
                                an activity-metric field, free text without a named reviewer, a value out of range)
  discover      0 saved (or the schema read today is reused)
                | 1 any AdoImportError: az absent, a refused or failed call (the call is named), a remote that is
                  not Azure DevOps, a document the mapping does not recognise. The `host` block is printed.
  validate      0 resolvable | 1 gaps (no config or schema, an unresolvable pin, a kind with no type) |
                2 a forbidden field is mapped
  Refused (2) is a setting the mirror will not honour or a name that reads as an agent; Illegal (1) is a missing
  precondition. Both are copied from `sprint.py`, not imported.

Honesty: a team, backlog or state never read is `null` in the schema and "not discovered" in the output, never an
empty list or a zero; `--json` prints exactly one JSON document on stdout.

Standalone or Workflow (CLAUDE.md design rule):
  - Standalone: --repo <path>              (default: cwd) needs no `.sdlc/state.yaml`
  - Workflow:   --state .sdlc/state.yaml   repo root = the directory containing `.sdlc/`
`--help` for the script and for every verb does no filesystem work and exits 0 from any cwd.
"""

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ado_schema  # noqa: E402
import ado_schema_map as sm  # noqa: E402
import ado_sync_config as cfgmod  # noqa: E402
import host_report  # noqa: E402
from ado_map import AdoImportError  # noqa: E402
from boards_contract import CONFIG_FILE, DISCIPLINE_AGENTS, KINDS, SCHEMA_FILE  # noqa: E402
from findings_model import is_ai_actor  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
AGENT_PREFIX = "shepherd:"
# The kinds `validate` checks as work item types without a fit: the config must name the type.
PINNED_KINDS = ("spike", "decision", "finding", "question")
# The starter's `kinds` (templates/ado/ado.yaml); a config without the key means this set.
DEFAULT_KINDS = ("outcome", "domain", "requirement", "epic", "feature", "spec", "spike", "sprint", "decision")
RESULT_WORDS = {0: "resolvable", 1: "gaps", 2: "refused"}
# How a fit mode reads in the text table; `--json` keeps the mode itself. A tree kind whose backlog levels were
# never read is "not discovered" -- not known, never a 0 and never a gap.
MODE_WORDS = {sm.UNKNOWN: "not discovered"}
CHECK_WORDS = {0: "valid", 1: "gaps", 2: "refused"}

# Every agents/*.md stem, read once at import (a read, never a write). A `--by` that is one of these is an agent.
AGENT_STEMS: frozenset[str] = frozenset(p.stem for p in (PLUGIN_ROOT / "agents").glob("*.md"))


class Refused(Exception):
    """Exit 2: a setting the mirror will not honour, or a `--by` that reads as an AI or an agent."""


class Illegal(Exception):
    """Exit 1: an illegal operation or a missing precondition."""


# --- people, paths, the host -----------------------------------------------------------------------------------

def require_human(name: str | None, flag: str) -> str:
    """A named human for `--by`. A blank is `Illegal` (1). An AI or an agent is `Refused` (2): the name after a
    leading `shepherd:` (only that prefix) reads as an AI (`is_ai_actor`), is an `agents/*.md` stem, or is one of
    the discipline agents. Honestly labelled: this is a label check, not an identity check."""
    clean = str(name or "").strip()
    if not clean:
        raise Illegal(f"{flag} is required: name a person, not a role or a blank")
    stem = clean[len(AGENT_PREFIX):].strip() if clean.lower().startswith(AGENT_PREFIX) else clean
    lowered = stem.lower()
    if is_ai_actor(stem) or lowered in AGENT_STEMS or lowered in DISCIPLINE_AGENTS:
        raise Refused(f"Refused: {flag} '{clean}' reads as an AI or an agent, not a named human. The mirror records "
                      "who is accountable for a change to the board; an agent may not be that name. (This is "
                      "labelling, not enforcement: it cannot verify identity, only refuse the obvious.)")
    return clean


def resolve_repo_root(args) -> Path | None:
    """Repo root: the parent of `.sdlc/` from `--state` (None if the state file is missing), else `--repo`."""
    if getattr(args, "state", None):
        state_path = Path(args.state)
        if not state_path.is_file():
            return None
        return state_path.resolve().parent.parent
    return Path(getattr(args, "repo", None) or ".").resolve()


def host_block_for(repo_root, error: str | None) -> dict:
    """The `host` block, read from the error the call just raised (None = it answered). It never probes the CLI."""
    return host_report.host_block(host_report.detect(repo_root), error)


def _rel(repo_root: Path, path: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


# --- output ----------------------------------------------------------------------------------------------------------

def _emit(args, payload: dict, text: str) -> None:
    """`--json` prints exactly one document; otherwise the text."""
    print(json.dumps(payload, indent=2) if args.json else text.rstrip("\n"))


def _error(args, message: str, code: int, **extra) -> int:
    if args.json:
        print(json.dumps({"ok": False, "error": message, "exit": code, **extra}, indent=2))
    else:
        print(message if code == 2 else f"Error: {message}")
    return code


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _host_line(host: dict) -> str:
    return f"Host: {host['name']} (source: {host['source']}); {host['cli']}: {host['cli_state']} - {host['detail']}"


def _name_of(obj) -> str | None:
    name = obj.get("name") if isinstance(obj, dict) else None
    return name if isinstance(name, str) and name else None


# --- config ----------------------------------------------------------------------------------------------------------

def cmd_config(args, repo_root: Path) -> int:
    return _config_init(args, repo_root) if args.config_verb == "init" else _config_check(args, repo_root)


def _config_init(args, repo_root: Path) -> int:
    target = repo_root / CONFIG_FILE
    if (target.exists() or target.is_symlink()) and not args.force:
        raise Illegal(f"{CONFIG_FILE} already exists; keep it, or pass --force to replace it with the starter")
    written = [_rel(repo_root, p) for p in cfgmod.init_config(repo_root, force=args.force)]
    text = "\n".join([*(f"Wrote {rel}" for rel in written),
                      "Edit the config, then run `ado_sync.py config check`; `ado_sync.py discover` reads the process "
                      "it will be checked against."])
    _emit(args, {"ok": True, "written": written}, text)
    return 0


def _schema_or_note(repo_root: Path) -> tuple[dict | None, str | None]:
    try:
        return ado_schema.load_schema(repo_root), None
    except AdoImportError as exc:
        return None, str(exc)


def _with_refusals(schema: dict | None) -> dict | None:
    """The schema as `validate_config` reads it: plus the fields the process says the mirror never writes."""
    return None if schema is None else {**schema, "refused_fields": sorted(sm.refused_fields(schema))}


def _counts(rows: list[dict]) -> dict:
    return {level: sum(1 for r in rows if r["level"] == level) for level in ("refused", "unresolvable", "invalid")}


def _exit_for(rows: list[dict], gaps: list[str]) -> int:
    if any(r["level"] == "refused" for r in rows):
        return 2
    return 1 if rows or gaps else 0


def _schema_line(schema: dict | None) -> str:
    if schema is None:
        return "Schema: not discovered yet (run `ado_sync.py discover`)"
    age = ado_schema.schema_age_days(schema, ado_schema.today())
    old = "age unknown" if age is None else f"{_plural(age, 'day')} old"
    return (f"Schema: read {schema.get('discovered_at') or 'at an unknown time'} ({old}), "
            f"team {_name_of(schema.get('team')) or 'not set'}")


def _schema_facts(schema: dict | None) -> dict | None:
    if schema is None:
        return None
    return {"discovered_at": schema.get("discovered_at"),
            "age_days": ado_schema.schema_age_days(schema, ado_schema.today()),
            "team": _name_of(schema.get("team"))}


def _finding_lines(rows: list[dict]) -> list[str]:
    return ["", "Config findings", *[f"  {r['level']}: {r['message']}" for r in rows]] if rows else []


def _config_check(args, repo_root: Path) -> int:
    cfg = cfgmod.load_config(repo_root)  # ConfigError -> main: missing / invalid exit 1
    schema, note = _schema_or_note(repo_root)
    rows = cfgmod.validate_config(cfg, _with_refusals(schema))
    code = _exit_for(rows, [])
    lines = [f"Config: {CONFIG_FILE}, {_plural(len(rows), 'finding')}",
             _schema_line(schema) if note is None else f"Schema: ignored ({note})",
             *_finding_lines(rows), "", f"Result: {CHECK_WORDS[code]} (exit {code})"]
    payload = {"ok": code == 0, "exit": code, "config": CONFIG_FILE, "schema": _schema_facts(schema), "rows": rows,
               "counts": _counts(rows)}
    if note is not None:
        payload["schema_note"] = note
    _emit(args, payload, "\n".join(lines))
    return code


# --- discover --------------------------------------------------------------------------------------------------------

def _clean(value) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _per_type_reads(schema: dict) -> list[str]:
    prefix = "wit/states type="
    return [c[len(prefix):] for c in schema.get("commands") or [] if isinstance(c, str) and c.startswith(prefix)]


def _discover_payload(schema: dict, *, reused: bool, host: dict | None, notes: list[str]) -> dict:
    backlog = schema.get("backlog")
    team_iterations = schema.get("team_iterations")
    return {"ok": True, "reused": reused, "path": SCHEMA_FILE, "discovered_at": schema.get("discovered_at"),
            "project": _name_of(schema.get("project")), "team": _name_of(schema.get("team")),
            "counts": {"types": len(schema.get("types") or {}), "fields": len(schema.get("fields") or {}),
                       "areas": len(schema.get("areas") or []), "iterations": len(schema.get("iterations") or []),
                       "team_iterations": len(team_iterations) if isinstance(team_iterations, list) else None,
                       "link_types": len(schema.get("link_types") or []),
                       "levels": len(backlog["levels"]) if isinstance(backlog, dict) else None},
            "per_type_reads": _per_type_reads(schema), "notes": notes, "host": host}


def _discover_text(payload: dict) -> str:
    c = payload["counts"]
    where = f"{payload['project'] or 'the project'} (team: {payload['team'] or 'not set'})"
    levels = "not read" if c["levels"] is None else str(c["levels"])
    team_iterations = "not read" if c["team_iterations"] is None else str(c["team_iterations"])
    reads = ", ".join(payload["per_type_reads"]) or "none"
    if payload["reused"]:
        head = (f"The saved schema for {where} was read today ({payload['discovered_at']}); nothing was read from "
                f"Azure DevOps. Pass --refresh to read it again.")
    else:
        head = f"Discovered the Azure DevOps process for {where} and saved {payload['path']}."
    lines = [head,
             f"  work item types {c['types']}, fields {c['fields']}, area paths {c['areas']}, iterations "
             f"{c['iterations']}, team iterations {team_iterations}, backlog levels {levels}",
             f"  states and fields read per type for: {reads}",
             *[f"Note: {n}" for n in payload["notes"]]]
    if payload["host"] is not None:
        lines.append(_host_line(payload["host"]))
    lines.append("Next: `ado_sync.py validate` checks the config against it.")
    return "\n".join(lines)


def _discover_failed(args, repo_root: Path, message: str, *, host_error: str | None) -> int:
    host = host_block_for(repo_root, host_error)
    if args.json:
        return _error(args, message, 1, host=host)
    code = _error(args, message, 1)
    print(_host_line(host))
    return code


def cmd_discover(args, repo_root: Path) -> int:
    cfg, cfg_note = ado_schema.discovery_config(repo_root)
    notes = [cfg_note] if cfg_note else []
    wanted = _clean(args.team) or _clean(cfg.get("team"))
    if not args.refresh:
        try:
            cached = ado_schema.load_schema(repo_root)
        except AdoImportError:
            cached = None  # a corrupt file is replaced by the read below
        if cached is not None and ado_schema.is_reusable(cached, cfg, wanted, ado_schema.today()):
            payload = _discover_payload(cached, reused=True, host=None, notes=notes)
            _emit(args, payload, _discover_text(payload))
            return 0
    try:
        schema = ado_schema.discover(repo_root, args.team, notes=notes, cfg=cfg)
    except AdoImportError as exc:
        return _discover_failed(args, repo_root, str(exc), host_error=str(exc))
    try:
        ado_schema.save_schema(repo_root, schema)
    except AdoImportError as exc:  # the identity guard: az answered, the file was refused
        return _discover_failed(args, repo_root, str(exc), host_error=None)
    except OSError as exc:
        return _discover_failed(args, repo_root, f"could not write {SCHEMA_FILE} ({type(exc).__name__})",
                                host_error=None)
    payload = _discover_payload(schema, reused=False, host=host_block_for(repo_root, None), notes=notes)
    _emit(args, payload, _discover_text(payload))
    return 0


# --- validate --------------------------------------------------------------------------------------------------------

def _configured_kinds(cfg: dict) -> tuple[str, ...]:
    if "kinds" not in cfg:
        return DEFAULT_KINDS
    raw = cfg["kinds"]
    return tuple(k for k in raw if isinstance(k, str) and k in KINDS) if isinstance(raw, (list, tuple)) else ()


def _fit_view(schema: dict, cfg: dict, kinds: tuple[str, ...]) -> tuple[dict, dict, list[str], list[str]]:
    """`(fit, resolved, gaps, recommendations)` for the configured kinds. A tree kind (outcome, domain,
    requirement) lands somewhere (an item, an Area Path or a tag) or, when the backlog levels were never read,
    is not known yet (`unknown`, printed "not discovered"); neither is a gap. Epic, feature and spec must
    resolve to a type, and so must a spike, decision, finding or question, which have no default."""
    fit = {k: v for k, v in sm.fit_levels(schema, cfg).items() if k in kinds}
    resolved = {}
    for kind in PINNED_KINDS:
        if kind in kinds:
            name, reason = sm.resolve_type(schema, kind, cfg)
            resolved[kind] = {"type": name, "reason": reason}
    gaps = [f"{k}: {v['reason']}" for k, v in fit.items() if k in ("epic", "feature", "spec") and v["type"] is None]
    gaps += [f"{k}: {v['reason']}" for k, v in resolved.items() if v["type"] is None]
    return fit, resolved, gaps, sm.recommendations(fit, schema)


def _fit_table(fit: dict, resolved: dict) -> list[str]:
    rows = [(k, MODE_WORDS.get(v["mode"], v["mode"]), v["type"] or "-", "-" if v["level"] is None else str(v["level"]),
             v["reason"]) for k, v in fit.items()]
    rows += [(k, "item" if v["type"] else "-", v["type"] or "-", "-", v["reason"]) for k, v in resolved.items()]
    header = ("kind", "mode", "type", "level", "why")
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(4)]
    return [("  " + "  ".join([*(cell.ljust(widths[i]) for i, cell in enumerate(row[:4])), row[4]])).rstrip()
            for row in [header, *rows]]


def cmd_validate(args, repo_root: Path) -> int:
    cfg = cfgmod.load_config(repo_root)       # ConfigError -> main
    schema = ado_schema.load_schema(repo_root)  # an unusable file -> AdoImportError -> main (exit 1)
    rows = cfgmod.validate_config(cfg, _with_refusals(schema))
    fit, resolved, recommendations = {}, {}, []
    if schema is None:
        gaps = ["no discovered schema: run `ado_sync.py discover` first, so there is a process to check the config against"]
    else:
        fit, resolved, gaps, recommendations = _fit_view(schema, cfg, _configured_kinds(cfg))
    code = _exit_for(rows, gaps)
    lines = ["Azure Boards mirror: validate", _schema_line(schema),
             f"Config: {CONFIG_FILE}, {_plural(len(rows), 'finding')}", *_finding_lines(rows)]
    if fit or resolved:
        lines += ["", "How each kind lands on this process", *_fit_table(fit, resolved)]
    if gaps:
        lines += ["", "Gaps", *[f"  - {g}" for g in gaps]]
    if recommendations:
        lines += ["", "Recommendations", *[f"  - {r}" for r in recommendations]]
    lines += ["", f"Result: {RESULT_WORDS[code]} (exit {code})"]
    payload = {"ok": code == 0, "exit": code, "schema": _schema_facts(schema), "rows": rows, "counts": _counts(rows),
               "fit": fit, "resolved": resolved, "gaps": gaps, "recommendations": recommendations}
    _emit(args, payload, "\n".join(lines))
    return code


# --- CLI -------------------------------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    src = common.add_mutually_exclusive_group()
    src.add_argument("--state", help="Path to .sdlc/state.yaml (workflow mode; repo root = parent of .sdlc/)")
    src.add_argument("--repo", default=".", help="Target repo root (standalone mode; default: cwd)")
    common.add_argument("--json", action="store_true", help="Print one JSON document instead of prose")

    parser = argparse.ArgumentParser(
        prog="ado_sync.py",
        description="Azure Boards mirror: configure it, discover the client's process, check that the config fits it. "
                    "Reads and plans by default; nothing here writes to the board.")
    sub = parser.add_subparsers(dest="verb", required=True)

    p = sub.add_parser("config", help="Start or check .sdlc/ado.yaml")
    config_sub = p.add_subparsers(dest="config_verb", required=True)
    q = config_sub.add_parser("init", parents=[common], help="Copy the starter config in (exit 1 if one exists)")
    q.add_argument("--force", action="store_true", help="Replace an existing config with the starter")
    config_sub.add_parser("check", parents=[common],
                          help="Report anything unsafe, unknown or unresolvable in the config, one finding per line")

    p = sub.add_parser("discover", parents=[common],
                       help="Read the Azure DevOps process and save .sdlc/ado/schema.json")
    p.add_argument("--team", default=None, metavar="T",
                   help="The team whose backlog levels and iterations to read (default: team in the config, "
                        "else the project's default team)")
    p.add_argument("--refresh", action="store_true",
                   help="Read again even if a schema for this team was read today")

    sub.add_parser("validate", parents=[common],
                   help="Check every configured kind resolves on the discovered process; print the fit table")
    return parser


VERBS: dict[str, Callable[[argparse.Namespace, Path], int]] = {
    "config": cmd_config, "discover": cmd_discover, "validate": cmd_validate,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = resolve_repo_root(args)
    if repo_root is None:
        return _error(args, f"state file not found: {args.state}", 1)
    try:
        return VERBS[args.verb](args, repo_root)
    except Refused as exc:
        return _error(args, str(exc), 2)
    except Illegal as exc:
        return _error(args, str(exc), 1)
    except cfgmod.ConfigError as exc:
        return _error(args, str(exc), 2 if exc.kind == "refused" else 1)
    except AdoImportError as exc:
        return _error(args, str(exc), 1)


if __name__ == "__main__":
    sys.exit(main())
