"""Change a project setting — validated first, written second (spec 0012).

Three settings, three files, three rules. Each verb writes only after the result would pass
the same validation the read side applies, so a settings screen cannot leave a project in a
state its own tooling rejects. The failure that prevents is specific: a roster saved with a
typo makes every later spec fail its owner check, and whoever broke it is three screens away
by the time anyone notices.

  person     Add or update someone in the roster (optionally their code-host `email`).
  limit      Set a team's work-in-progress limit.
  approval   Turn change-approval on or off for a stage.
  code-host  Pin which code host this repository is on (.sdlc/code-host.yaml).

NOTHING IS REGENERATED. Every write is a targeted edit that leaves the rest of the file
byte-for-byte alone, which matters more than it sounds: the first version of the roster write
parsed the file, changed the object and dumped it back. That was correct, passed validation,
and silently destroyed all nine comments its author had written. Losing what a person wrote is
the exact failure this whole product exists to prevent, so a settings screen must not be the
one place it happens. The same rule the document shape library follows for markdown applies
here.

Writes the file and nothing else: no commit, no branch, no push. Reaching the repository is
spec 0009's save, which is what makes a settings change an ordinary commit with a person and a
reason on it rather than a silent mutation.

Refusals happen BEFORE the file is touched, so a refused change leaves it exactly as it was.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import approval_settings as aps
import cadence_plan as cp
import validate_team as vt

HANDLE_RE = re.compile(r"^@[A-Za-z0-9][A-Za-z0-9-]*$")
FIELD_ORDER = ("name", "email", "team", "roles", "signs_off")

# The code hosts the plugin knows how to talk to. `none` is a real, deliberate answer — "do
# not treat this remote as either" — not the absence of one, which is why it is a value a
# person can write rather than the result of deleting the file. Mirrors code_host.py's set.
CODE_HOSTS = ("github", "azure-devops", "none")
CODE_HOST_FIELDS = ("host", "organization", "project", "repository")
CODE_HOST_HEADER = (
    "# Code host for this repository, pinned by hand — written by `set_setting.py code-host`.\n"
    "# Read ahead of the `origin` remote; a `--host` flag on a command or SHEPHERD_CODE_HOST in the\n"
    "# environment (or SDLC_CODE_HOST, the older name — still honoured) still wins. Delete this file\n"
    "# to go back to detecting the host from `origin`.\n")


class SettingError(Exception):
    def __init__(self, message: str, kind: str = "other"):
        super().__init__(message)
        self.kind = kind


def _roster_path(repo_root: Path) -> Path:
    return repo_root / ".sdlc" / "team.yaml"


def _load_roster(repo_root: Path) -> dict:
    path = _roster_path(repo_root)
    if not path.exists():
        raise SettingError(
            f"This project has no roster yet ({path.name}). Create one before adding people — "
            f"see templates/team/team.example.yaml.", "no_roster")
    try:
        return vt.load_yaml(path)
    except Exception as e:  # noqa: BLE001
        raise SettingError(f"The roster could not be read: {e}", "malformed") from e


def _check_roster_text(text: str) -> None:
    """Parse the PROPOSED text and validate the whole roster before it is written.

    The whole file, not just the changed row: a valid row can still break the roster — a team
    that no longer exists, a lead who was removed."""
    try:
        roster = vt.yaml.safe_load(text) if hasattr(vt, "yaml") else None
    except Exception as e:  # noqa: BLE001
        raise SettingError(f"That change would leave the roster unreadable: {e}", "would_be_invalid") from e
    if roster is None:
        import yaml as _yaml
        try:
            roster = _yaml.safe_load(text)
        except Exception as e:  # noqa: BLE001
            raise SettingError(f"That change would leave the roster unreadable: {e}",
                               "would_be_invalid") from e

    errors = vt.validate_team(roster, vt.load_yaml(vt.SCHEMA_PATH))
    if errors:
        raise SettingError(
            "That change would leave the roster invalid: " + "; ".join(errors), "would_be_invalid")


def _render_field(indent: str, key: str, value, eol: str) -> str:
    """Render one roster line, letting the serializer do the quoting.

    Hand-quoting with `"` was how a `--name` carrying line breaks wrote a second person into the
    file. The roster is re-validated after the edit, which catches MALFORMED output — but a
    smuggled person is perfectly well-formed, so validation passed and the command reported one
    change while the file gained two. Asking YAML to quote the value closes it at the source.
    """
    rendered = yaml.safe_dump(
        value, default_flow_style=True, allow_unicode=True, width=10 ** 6).strip()
    if rendered.endswith("..."):
        rendered = rendered[:-3].strip()
    return f"{indent}{key}: {rendered}{eol}"


def _person_span(lines: list[str], handle: str) -> tuple[int, int, str] | None:
    """(start, end, indent) of one person's entry, or None if they are not listed."""
    pattern = re.compile(r"^(\s*)-\s+handle:\s*[\"']?" + re.escape(handle) + r"[\"']?\s*$")
    for i, line in enumerate(lines):
        m = pattern.match(line.rstrip("\r\n"))
        if not m:
            continue
        indent = m.group(1)
        for j in range(i + 1, len(lines)):
            stripped = lines[j].rstrip("\r\n")
            if not stripped.strip():
                continue
            # The entry ends at the next sibling list item, or the next top-level key.
            if re.match(r"^" + re.escape(indent) + r"-\s", stripped):
                return (i, j, indent)
            if not stripped.startswith(indent + " "):
                return (i, j, indent)
        return (i, len(lines), indent)
    return None


def apply_person_edit(text: str, handle: str, fields: dict) -> str:
    """Add or update one person, editing the text and leaving everything else untouched."""
    lines = text.splitlines(keepends=True)
    eol = "\r\n" if text.find("\r\n") != -1 else "\n"
    span = _person_span(lines, handle)
    given = {k: v for k, v in fields.items() if v is not None}

    if span is not None:
        start, end, indent = span
        body_indent = indent + "  "
        rebuilt = [lines[start]]
        seen: set[str] = set()
        for line in lines[start + 1:end]:
            key_match = re.match(r"^\s*([A-Za-z_]+):", line.rstrip("\r\n"))
            key = key_match.group(1) if key_match else None
            if key in given:
                # Replaced in place, so the entry's own ordering and any comment lines around
                # it survive exactly as the author left them.
                rebuilt.append(_render_field(body_indent, key, given[key], eol))
                seen.add(key)
            else:
                rebuilt.append(line)
        # Fields this person did not have yet go after the ones they did.
        for key in FIELD_ORDER:
            if key in given and key not in seen:
                rebuilt.append(_render_field(body_indent, key, given[key], eol))
        return "".join(lines[:start] + rebuilt + lines[end:])

    # A new person: appended to the end of the people list, in the file's own indentation.
    people_at = next(
        (i for i, l in enumerate(lines) if re.match(r"^people:\s*$", l.rstrip("\r\n"))), None)
    if people_at is None:
        raise SettingError("The roster has no `people:` list to add to.", "malformed")

    item_indent = next(
        (re.match(r"^(\s*)-\s", l).group(1) for l in lines[people_at + 1:]
         if re.match(r"^\s*-\s", l)), "  ")
    insert_at = len(lines)
    for j in range(people_at + 1, len(lines)):
        stripped = lines[j].rstrip("\r\n")
        if stripped.strip() and not stripped.startswith((" ", "-")):
            insert_at = j
            break

    entry = [f'{item_indent}- handle: "{handle}"{eol}']
    for key in FIELD_ORDER:
        if key in given:
            entry.append(_render_field(item_indent + "  ", key, given[key], eol))
    # A blank line between entries, matching how the example roster separates people.
    if insert_at > 0 and lines[insert_at - 1].strip():
        entry.insert(0, eol)
    return "".join(lines[:insert_at] + entry + lines[insert_at:])


def set_person(repo_root: Path, handle: str, name: str | None, team: str | None,
               roles: list[str] | None, signs_off: list[str] | None,
               email: str | None = None) -> dict:
    if not HANDLE_RE.match(handle or ""):
        raise SettingError(
            f"'{handle}' is not a code-host handle — expected something like @sam-k.", "bad_handle")
    # The same narrow check validate_team applies, done here so a refusal names the field and
    # leaves the file untouched. Whether it duplicates somebody else's is caught below, by
    # validating the whole proposed roster, since that needs every other entry.
    if email is not None and (
            not email.strip() or any(c in email for c in "\r\n") or "@" not in email):
        raise SettingError(
            f"'{email}' is not an email — expected one line containing '@', like sam@example.com.",
            "bad_email")

    roster = _load_roster(repo_root)
    known_teams = {t.get("name") for t in roster.get("teams") or []}
    if team and team not in known_teams:
        raise SettingError(
            f"'{team}' is not a team in this roster. Known teams: "
            f"{', '.join(sorted(n for n in known_teams if n)) or 'none'}.", "unknown_team")
    for role in roles or []:
        if role not in vt.ROLES:
            raise SettingError(
                f"'{role}' is not a role — expected one of {', '.join(vt.ROLES)}.", "unknown_role")
    # `signs_off` was the one list written through with no check at all, and it is the one that
    # matters most: approval_settings cross-checks a named approver against this roster, so an
    # unchecked value here mints somebody the sign-off machinery will subsequently treat as real.
    for stage in signs_off or []:
        if not isinstance(stage, str) or not stage.strip() or any(c in stage for c in "\r\n"):
            raise SettingError(
                f"'{stage}' is not a stage name — a stage is a single line of text.",
                "bad_stage")

    path = _roster_path(repo_root)
    original = path.read_text(encoding="utf-8")
    updating = any(p.get("handle") == handle for p in roster.get("people") or [])
    proposed = apply_person_edit(
        original, handle,
        {"name": name, "email": email.strip() if email else None, "team": team,
         "roles": roles, "signs_off": signs_off})

    _check_roster_text(proposed)

    # The roster is re-validated above, which catches output that is MALFORMED. It cannot catch
    # output that is well-formed and wrong — an extra person, written by a value that carried
    # its own YAML structure, validates perfectly. So the edit is checked against what it said
    # it would do: one named person, and nobody else. This holds whatever a value contains,
    # which is why it is here as well as the escaping, not instead of it.
    before = {p.get("handle") for p in roster.get("people") or []}
    after = vt.people_handles(yaml.safe_load(proposed) or {})
    smuggled = after - before - {handle}
    lost = before - after
    if smuggled or lost:
        raise SettingError(
            "That change would alter people you did not name — "
            + ", ".join(sorted(f"added {h}" for h in smuggled)
                        + sorted(f"removed {h}" for h in lost))
            + ". Nothing was written.", "would_be_invalid")

    path.write_text(proposed, encoding="utf-8")
    return {"ok": True, "changed": True, "file": ".sdlc/team.yaml",
            "message": f"{'Updated' if updating else 'Added'} {handle}.",
            "note": "This records that they may hold a role. It grants nobody access to the "
                    "repository — that stays with the code host."}


def replace_limit_row(text: str, team: str, limit: int) -> tuple[str, bool]:
    """Rewrite one row of the `## WIP Limits` table, leaving every other byte alone.

    A targeted row edit rather than regenerating the table: the cadence plan is a hand-written
    document with prose around that table, and regenerating it would reformat somebody's
    writing in order to change one number."""
    out, found = [], False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if not found and stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if cells and cells[0] == team and len(cells) >= 2:
                eol = line[len(line.rstrip("\r\n")):]
                cells[1] = str(limit)
                out.append("| " + " | ".join(cells) + " |" + eol)
                found = True
                continue
        out.append(line)
    return "".join(out), found


def set_limit(repo_root: Path, team: str, limit: int) -> dict:
    if limit < 1:
        raise SettingError(f"A work-in-progress limit must be at least 1, not {limit}.", "bad_limit")

    roster_path = _roster_path(repo_root)
    if roster_path.exists():
        known = {t.get("name") for t in (vt.load_yaml(roster_path).get("teams") or [])}
        if team not in known:
            raise SettingError(
                f"'{team}' is not a team in this project's roster. Known teams: "
                f"{', '.join(sorted(n for n in known if n)) or 'none'}.", "unknown_team")

    path = cp.resolve_cadence_plan_path(repo_root)
    if not path.exists():
        raise SettingError(
            f"This project has no cadence plan yet ({path.name}), which is where per-team "
            f"limits live. It is created in Foundation.", "no_cadence_plan")

    text = path.read_text(encoding="utf-8")
    proposed, found = replace_limit_row(text, team, limit)
    if not found:
        raise SettingError(
            f"The cadence plan has no `## WIP Limits` row for '{team}'. Add the row first — "
            f"this changes an existing limit, it does not invent the table.", "no_row")

    _, errors = cp.parse_limits_block(proposed)
    if errors:
        raise SettingError(
            "That change would leave the WIP Limits table unreadable: " + "; ".join(errors),
            "would_be_invalid")

    path.write_text(proposed, encoding="utf-8")
    return {"ok": True, "changed": True, "file": path.name,
            "message": f"{team}'s limit is now {limit}.",
            "note": "The cadence plan is a document, so this change appears in its history "
                    "like any other edit."}


def set_approval(repo_root: Path, stage: str, required: bool, approver: str | None) -> dict:
    if required and not (approver or "").strip():
        raise SettingError(
            "Turning approval on needs a named approver — 'somebody must approve this' with "
            "nobody named is not a rule anyone can act on.", "approver_required")

    roster_path = _roster_path(repo_root)
    known = set(vt.people_handles(vt.load_yaml(roster_path))) if roster_path.exists() else None
    if required and known is not None and approver not in known:
        raise SettingError(
            f"'{approver}' is not in this project's roster, so nothing could route an approval "
            f"to them. Add them to the roster first.", "unknown_approver")

    path = repo_root / ".sdlc" / "approval-settings.yaml"
    existing = {}
    if path.exists():
        existing, errors = aps.parse_approval_settings(path.read_text(encoding="utf-8"), known)
        if errors:
            raise SettingError(
                "The existing approval settings could not be read, so this change is refused "
                "rather than written over them: " + "; ".join(errors), "malformed")

    import yaml
    existing[stage] = {"approval_required": required,
                       "approver": approver.strip() if required and approver else None}
    doc = {"stages": [{"stage": s, **v} for s, v in sorted(existing.items())]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")

    return {"ok": True, "changed": True, "file": ".sdlc/approval-settings.yaml",
            "message": f"Approval for '{stage}' is {'on' if required else 'off'}"
                       + (f", approved by {approver}." if required else "."),
            "note": "While a draft waits, everyone else keeps seeing the signed-off version."}


def _code_host_path(repo_root: Path) -> Path:
    return repo_root / ".sdlc" / "code-host.yaml"


def parse_code_host_text(text: str) -> tuple[dict, list[str]]:
    """(fields, errors) for a .sdlc/code-host.yaml. Validated like the other .sdlc singletons:
    every error names the key, and a reader treats any error as "no usable override" rather
    than guessing a host from a half-readable file — the remote is a safer answer than a typo."""
    errors: list[str] = []
    if not text.strip():
        return {}, errors
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as e:
        return {}, [f"invalid YAML: {e}"]
    if doc is None:
        return {}, errors
    if not isinstance(doc, dict):
        return {}, ["Root: expected a YAML mapping"]
    for key in doc:
        if key not in CODE_HOST_FIELDS:
            errors.append(f"{key}: unknown key (expected one of {', '.join(CODE_HOST_FIELDS)})")
    host = doc.get("host")
    if "host" not in doc:
        errors.append("host: missing")
    elif host not in CODE_HOSTS:
        errors.append(f"host: '{host}' is not a code host ({', '.join(CODE_HOSTS)})")
    for key in CODE_HOST_FIELDS[1:]:
        if key in doc:
            value = doc[key]
            if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n"):
                errors.append(f"{key}: must be one non-empty line of text")
    return ({k: v for k, v in doc.items() if k in CODE_HOST_FIELDS} if not errors else {}), errors


def apply_code_host_edit(text: str, fields: dict) -> str:
    """Set top-level keys in the file's text, replacing a key's line where it exists and
    appending the rest, so a comment somebody wrote above `host:` survives the change."""
    given = {k: v for k, v in fields.items() if v is not None}
    if not text.strip():
        return CODE_HOST_HEADER + "".join(
            _render_field("", k, given[k], "\n") for k in CODE_HOST_FIELDS if k in given)
    lines = text.splitlines(keepends=True)
    eol = "\r\n" if text.find("\r\n") != -1 else "\n"
    out, seen = [], set()
    for line in lines:
        m = re.match(r"^([A-Za-z_]+):", line)
        if m and m.group(1) in given:
            out.append(_render_field("", m.group(1), given[m.group(1)], eol))
            seen.add(m.group(1))
        else:
            out.append(line)
    if out and not out[-1].endswith(("\n", "\r")):
        out[-1] += eol
    out.extend(_render_field("", k, given[k], eol) for k in CODE_HOST_FIELDS
               if k in given and k not in seen)
    return "".join(out)


def set_code_host(repo_root: Path, host: str, organization: str | None = None,
                  project: str | None = None, repository: str | None = None) -> dict:
    """Pin the repository's code host. Overrides what `origin` says; never touches state.yaml."""
    if host not in CODE_HOSTS:
        raise SettingError(
            f"'{host}' is not a code host — expected one of {', '.join(CODE_HOSTS)}.", "bad_host")
    given = {"host": host, "organization": organization, "project": project,
             "repository": repository}
    for key, value in given.items():
        if value is not None and (not value.strip() or any(c in value for c in "\r\n")):
            raise SettingError(f"--{key} must be one non-empty line of text.", "bad_value")

    path = _code_host_path(repo_root)
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    existing, errors = parse_code_host_text(original)
    if errors:
        raise SettingError(
            f"The existing {path.name} could not be read, so this change is refused rather than "
            "written over it: " + "; ".join(errors), "malformed")

    proposed = apply_code_host_edit(original, given)
    parsed, errors = parse_code_host_text(proposed)
    if errors:
        raise SettingError(
            "That change would leave the code-host file invalid: " + "; ".join(errors),
            "would_be_invalid")
    # Same discipline as the roster: the result must contain exactly the keys that were there
    # plus the ones named, with the named ones holding the values given — a value carrying its
    # own YAML structure is serialized, so this is the backstop, not the only guard.
    expected = {**existing, **{k: v.strip() for k, v in given.items() if v is not None}}
    if parsed != expected:
        raise SettingError(
            "That change would write something other than what was asked. Nothing was written.",
            "would_be_invalid")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(proposed, encoding="utf-8")
    return {"ok": True, "changed": proposed != original, "file": ".sdlc/code-host.yaml",
            "message": f"This repository's code host is pinned to {host}.",
            "note": "Overrides what the `origin` remote says; a `--host` flag or SHEPHERD_CODE_HOST "
                    "(or the older SDLC_CODE_HOST, still honoured) still wins over this file. Delete it "
                    "to detect the host from the remote again."}


def resolve_repo_root(args) -> Path:
    if args.state:
        state = Path(args.state)
        if not state.exists():
            print(f"Error: State file not found: {state}", file=sys.stderr)
            sys.exit(1)
        return state.resolve().parent.parent
    return Path(args.repo).resolve()


def main():
    parser = argparse.ArgumentParser(description="Change a project setting — validated, then written")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--state", help="Path to .sdlc/state.yaml (workflow mode)")
    src.add_argument("--repo", default=".", help="Target repo root (standalone mode; default: cwd)")
    parser.add_argument("--json", action="store_true", help="Emit the outcome as JSON")
    sub = parser.add_subparsers(dest="action", required=True)

    person = sub.add_parser("person", help="Add or update someone in the roster")
    person.add_argument("handle", help="Code-host handle, e.g. @sam-k")
    person.add_argument("--name")
    person.add_argument("--email", default=None,
                        help="Sign-in identity on Azure DevOps (UPN or mail); optional, unique")
    person.add_argument("--team")
    person.add_argument("--roles", nargs="*", help=f"Any of {', '.join(vt.ROLES)}")
    person.add_argument("--signs-off", nargs="*", metavar="STAGE")

    limit = sub.add_parser("limit", help="Set a team's work-in-progress limit")
    limit.add_argument("team")
    limit.add_argument("limit", type=int)

    approval = sub.add_parser("approval", help="Turn change-approval on or off for a stage")
    approval.add_argument("stage")
    approval.add_argument("--on", dest="required", action="store_true")
    approval.add_argument("--off", dest="required", action="store_false")
    approval.add_argument("--approver", default=None)
    approval.set_defaults(required=True)

    code_host = sub.add_parser(
        "code-host", help="Pin which code host this repository is on (.sdlc/code-host.yaml)")
    code_host.add_argument("--host", required=True, choices=CODE_HOSTS,
                           help="github, azure-devops, or none (treat the remote as neither)")
    code_host.add_argument("--organization", default=None,
                           help="Azure DevOps organization, when the remote cannot be parsed")
    code_host.add_argument("--project", default=None,
                           help="Azure DevOps project, when the remote cannot be parsed")
    code_host.add_argument("--repository", default=None,
                           help="Repository name, when the remote cannot be parsed")

    args = parser.parse_args()
    repo_root = resolve_repo_root(args)

    try:
        if args.action == "person":
            result = set_person(repo_root, args.handle, args.name, args.team,
                               args.roles, args.signs_off, email=args.email)
        elif args.action == "limit":
            result = set_limit(repo_root, args.team, args.limit)
        elif args.action == "code-host":
            result = set_code_host(repo_root, args.host, args.organization, args.project,
                                   args.repository)
        else:
            result = set_approval(repo_root, args.stage, args.required, args.approver)
    except SettingError as e:
        if args.json:
            print(json.dumps({"ok": False, "refusal": {"kind": e.kind, "message": str(e)}}, indent=2))
        else:
            print(f"Refused: {e}")
        # An unknown host is a usage error (argparse already exits 2 for it on the command
        # line); every other refusal keeps the exit code the earlier verbs have always used.
        sys.exit(2 if e.kind == "bad_host" else 1)

    print(json.dumps(result, indent=2) if args.json else f"{result['message']}\n  {result['note']}")


if __name__ == "__main__":
    main()
