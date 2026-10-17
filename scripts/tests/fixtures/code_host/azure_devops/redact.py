"""Redact a captured `az … -o json` document before it becomes a fixture (pure; no I/O in `redact`).

Usage:  python redact.py --org contoso < captured.json > fixture.json

What is replaced, and with what — fixed fakes so a fixture is stable across captures:
  * GUIDs            → a GUID derived from the ORDER of first appearance (00000000-0000-0000-0000-000000000001, …),
                       so two fields that pointed at the same identity still point at the same fake.
  * UPNs / emails    → person1@example.com, person2@example.com, … (same stability rule).
  * the organisation → "contoso" wherever it appears in a URL or a slug (case-insensitive).
  * display names    → "Person N" matching the UPN's number when the record carries both.

Nothing else is touched: enum values, dates, booleans and shapes are the point of a fixture.
The caller still adds `"_provenance": "captured <date> <org anonymised>"` to the document.

A Boards (work item) capture names more than the organisation, so these options were appended for it
(B0, 2026-10-14). Each is off unless given, and without them the output is byte-for-byte what it was:
  * `--project NAME`  → "Claims" wherever it appears (case-insensitive, as the organisation), so the
                        project's default team, its process (`Agile_<project>`) and its URLs follow.
  * `--team NAME`     → "Claims Team" where a whole value, or one segment of a path or URL (split on
                        `\\`, `/`, `?`, `&`, `=`; percent-encoded or not), equals it — never inside other text.
  * `--rename OLD=NEW` (repeatable) → the same whole-value / segment rule for an area or iteration
                        node name (`--rename "Iteration 1=Sprint 1"`).
  * `--mask-free-text` → the value of every `description`, `helpText` and `xmlForm` key becomes
                        "[redacted: free text]" (the words a client typed into its own process).
  * `--indent N`      → the output's JSON indent (default 2, as before; the `wit/` fixtures use 1).
Usage:  python redact.py --org <org> --project <project> --team <team> --rename <a>=<b> --mask-free-text
"""

import argparse
import json
import re
import sys
from urllib.parse import quote, unquote

GUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# The policy TYPE GUIDs are vocabulary, not identity — they must survive redaction verbatim.
KEEP_GUIDS = {
    "0609b952-1397-4640-95ec-e00a01b2c241",  # build validation
    "cbdc66da-9728-4af8-aada-9a5a32e4a226",  # status check
    "fa4e907d-c16b-4a4c-9dfa-4906e5d171dd",  # approver count
    "fd2167ab-b0be-447a-8ec8-39368250530e",  # required reviewers
}


FAKE_PROJECT = "Claims"
FAKE_TEAM = "Claims Team"
REDACTED_TEXT = "[redacted: free text]"
FREE_TEXT_KEYS = frozenset({"description", "helpText", "xmlForm"})
_SEGMENT_SPLIT = re.compile(r"(\\|/|\?|&|=)")


def _rename_segments(s: str, names: dict[str, str]) -> str:
    """`s` with every whole segment (split on `\\ / ? & =`, raw or percent-decoded) found in `names` replaced; inside
    a URL the new name is percent-encoded, so a URL stays a URL."""
    parts = _SEGMENT_SPLIT.split(s)
    in_url = "://" in s
    for i, part in enumerate(parts):
        old = part if part in names else unquote(part) if "%" in part and unquote(part) in names else None
        if old is not None:
            parts[i] = quote(names[old], safe="") if in_url or part != old else names[old]
    return "".join(parts)


def redact(doc, org: str, fake_org: str = "contoso", *, project: str | None = None, team: str | None = None,
           renames: dict[str, str] | None = None, mask_free_text: bool = False):
    """Return a redacted deep copy of `doc` (any JSON value). The keyword options are the Boards pass (see above)."""
    guids: dict[str, str] = {}
    people: dict[str, str] = {}
    names = dict(renames or {})
    if team:
        names[team] = FAKE_TEAM

    def fake_guid(real: str) -> str:
        if real.lower() in KEEP_GUIDS:
            return real
        return guids.setdefault(real.lower(), f"00000000-0000-0000-0000-{len(guids) + 1:012d}")

    def fake_email(real: str) -> str:
        return people.setdefault(real.lower(), f"person{len(people) + 1}@example.com")

    def scrub(s: str) -> str:
        s = GUID_RE.sub(lambda m: fake_guid(m.group(0)), s)
        s = EMAIL_RE.sub(lambda m: fake_email(m.group(0)), s)
        if org:
            s = re.sub(re.escape(org), fake_org, s, flags=re.IGNORECASE)
        if project:
            s = re.sub(re.escape(project), FAKE_PROJECT, s, flags=re.IGNORECASE)
        if names:
            s = _rename_segments(s, names)
        return s

    def walk(v):
        if isinstance(v, dict):
            out = {k: (REDACTED_TEXT if mask_free_text and k in FREE_TEXT_KEYS and isinstance(x, str) and x
                       else walk(x)) for k, x in v.items()}
            if isinstance(out.get("uniqueName"), str) and "displayName" in out:
                n = re.match(r"person(\d+)@", out["uniqueName"])
                if n:
                    out["displayName"] = f"Person {n.group(1)}"
            return out
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, str):
            return scrub(v)
        return v

    return walk(doc)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Redact a captured az JSON document for use as a fixture")
    parser.add_argument("--org", required=True, help="The real organisation name to replace with 'contoso'")
    parser.add_argument("--project", help=f"The real project name to replace with {FAKE_PROJECT!r}")
    parser.add_argument("--team", help=f"The real team name to replace with {FAKE_TEAM!r} (whole values and segments)")
    parser.add_argument("--rename", action="append", default=[], metavar="OLD=NEW",
                        help="An area or iteration name to replace (whole values and segments); repeatable")
    parser.add_argument("--mask-free-text", action="store_true",
                        help=f"Replace every description / helpText / xmlForm value with {REDACTED_TEXT!r}")
    parser.add_argument("--indent", type=int, default=2, help="JSON indent of the output (default 2)")
    args = parser.parse_args(argv)
    renames = {}
    for pair in args.rename:
        old, sep, new = pair.partition("=")
        if not sep or not old or not new:
            parser.error(f"--rename wants OLD=NEW, got {pair!r}")
        renames[old] = new
    doc = json.load(sys.stdin)
    json.dump(redact(doc, args.org, project=args.project, team=args.team, renames=renames,
                     mask_free_text=args.mask_free_text), sys.stdout, indent=args.indent)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
