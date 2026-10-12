"""Bind a spec to its delivery channel — the mechanical half of /sprd-channel (spec 0021).

The command's steps 4 and 5 are a merge of two tables, and nothing in them needs a model:

  * set the spec's `channel:` and, when `harness_context` is empty, seed it from the channel
    descriptor's `harness_context_seed`;
  * append to the spec's existing `## Acceptance Checks` one line per channel dimension the spec
    does not yet cover, tagged `(channel: <dimension id>)` — the text coming from the feature's
    interaction spec (its "-> Acceptance check" cell for that dimension) when it has a real one,
    and from the descriptor's `example_check` otherwise.

The command's other steps stay with a person: confirming the overlay, and deciding whether the
channel's risk floor raises the tier. This script REPORTS the floor and never edits `risk:`; a
raise is `spec_transition.py risk`, after that confirmation.

It edits the `channel:` and `harness_context:` frontmatter lines and the Acceptance Checks
section, and no other byte of the spec. Run it twice and the second run changes nothing. A spec is
one channel: binding a different channel than the one already set is refused.

Standalone or Workflow (CLAUDE.md design rule):
  - Standalone: --spec specs/NNNN-name.md --channel <id> [--interaction-spec <path>]
  - Workflow:   --state .sdlc/state.yaml (or --repo <root>) — the interaction spec is then taken
                from .sdlc/artifacts/02-design/experience/channel-interaction-spec.md when present.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_channel as cc
import risk_model
import spec_transition as st
from check_spec import extract_section, list_items, parse_frontmatter

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INTERACTION_SPEC = Path(".sdlc") / "artifacts" / "02-design" / "experience" / "channel-interaction-spec.md"
# A line that is ONLY an empty checkbox (`- [ ]`) — the placeholder a scaffolded spec carries.
# It must end the line: `- [ ] A real check` is content, not a placeholder.
_BLANK_CHECKBOX_LINE_RE = re.compile(r"^[ \t]*[-*+][ \t]*\[[ xX]?\][ \t]*\r?(?:\n|\Z)", re.MULTILINE)


class BindError(Exception):
    """A clean refusal, reported as one line on stderr with exit 1; the spec is never touched."""


def _read_raw(path: Path) -> str:
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return f.read()
    except FileNotFoundError as e:
        raise BindError(f"spec not found: {path}") from e


def _replace_frontmatter_line(text: str, field: str, value: str) -> str:
    """Set one frontmatter field on its own line, keeping that line's ending and nothing else.

    Not `spec_transition.set_frontmatter_field`: its `.*$` pattern also consumes the `\\r` of a
    CRLF line, which would leave a bare LF in the middle of a Windows file."""
    end = text.find("\n---", 3)
    if end == -1:
        raise BindError("the spec's frontmatter block is never closed (no second `---` line), so it cannot be edited safely")
    block, rest = text[:end], text[end:]
    # Replace only the VALUE: the template annotates these lines (`channel: ""  # optional — ...`),
    # and that comment, the spacing before it and the line ending all stay.
    pattern = re.compile(
        rf"""^({re.escape(field)}:[ \t]*)(?:"(?:[^"\\]|\\.)*"|'[^']*'|[^#\r\n]*?)(?=[ \t]*(?:#[^\r\n]*)?\r?$)""",
        re.MULTILINE,
    )
    if pattern.search(block):
        block = pattern.sub(lambda m: m.group(1) + value, block, count=1)
    else:
        eol = "\r\n" if "\r\n" in block else "\n"
        # `rest` begins at the closing fence's "\n"; in a CRLF file the "\r" before it belongs to
        # the new line, or the appended field would end in a bare LF.
        block = block.rstrip("\r\n") + eol + f"{field}: {value}" + ("\r" if eol == "\r\n" else "")
    return block + rest


def _inject_checks(text: str, lines: list[str]) -> str:
    """Append `lines` to the Acceptance Checks section, dropping the blank `- [ ]` placeholder a
    freshly scaffolded spec carries. Everything outside that section is left as it was."""
    heading = re.search(r"^##[ \t]+Acceptance Checks[ \t]*\r?$", text, re.MULTILINE | re.IGNORECASE)
    if not heading:
        raise BindError("the spec has no ## Acceptance Checks section, so the channel's checks have nowhere to land")
    start = heading.end()
    following = re.search(r"^##[ \t]+", text[start:], re.MULTILINE)
    end = start + following.start() if following else len(text)

    eol = "\r\n" if "\r\n" in text else "\n"
    section = _BLANK_CHECKBOX_LINE_RE.sub("", text[start:end])
    body = section.rstrip()
    trailing = section[len(body):]
    return text[:start] + body + eol + eol.join(lines) + (trailing or eol) + text[end:]


def _line_for(dim: dict, interaction_row: dict | None) -> str:
    detail = (interaction_row or {}).get("check") or str(dim.get("example_check", "")).strip() or str(dim.get("intent", "")).strip()
    return f"- [ ] {detail}   (channel: {dim['id']})"


def _risk_report(descriptor: dict, current_risk: str | None) -> dict:
    floor = risk_model.normalize_tier(descriptor.get("risk_floor"))
    current = risk_model.normalize_tier(current_risk)
    # RISK_TIERS is declared most-risky-first, so a LOWER index is the riskier tier.
    raise_needed = bool(floor and current and risk_model.RISK_TIERS.index(floor) < risk_model.RISK_TIERS.index(current))
    return {"risk_floor": floor, "current_risk": current, "raise_needed": raise_needed}


def bind(spec_path: Path, channel: str | None, channels_dir: Path, interaction_spec: Path | None = None) -> dict:
    spec_path = Path(spec_path)
    text = _read_raw(spec_path)
    if not text.startswith("---"):
        raise BindError("the spec has no frontmatter block")
    fm, body = parse_frontmatter(text)

    bound = (fm.get("channel") or "").strip()
    bound = None if bound.lower() in cc.NO_CHANNEL else bound
    if channel and bound and channel != bound:
        raise BindError(f"this spec is already bound to channel '{bound}'; a spec is one channel, so '{channel}' "
                        f"would mean decomposing into a separate spec per surface")
    channel = channel or bound
    if not channel:
        raise BindError("no channel: give --channel, or set `channel:` on the spec")

    descriptor, note = cc.load_channel_descriptor(channel, channels_dir)
    if descriptor is None:
        raise BindError(f"{note} (add channels/{channel}.yaml, or check the channel id)")

    notes: list[str] = []
    rows: list[dict] = []
    if interaction_spec and Path(interaction_spec).exists():
        itext = Path(interaction_spec).read_text(encoding="utf-8", errors="replace")
        doc_channel = cc.interaction_spec_channel(itext)
        if doc_channel and doc_channel != channel:
            notes.append(f"the interaction spec is for channel '{doc_channel}', not '{channel}', so it was not used")
        else:
            rows = cc.parse_interaction_rows(itext)

    checks = list_items(extract_section(body, "Acceptance Checks") or "")
    injected, already, new_lines = [], [], []
    for dim in descriptor.get("acceptance_dimensions") or []:
        if not isinstance(dim, dict) or not str(dim.get("id", "")).strip():
            continue
        dim = {**dim, "id": str(dim["id"]).strip()}
        if cc.dimension_covered(dim, checks):
            already.append(dim["id"])
            continue
        row = cc.find_interaction_row(dim["id"], rows)
        injected.append(dim["id"])
        new_lines.append(_line_for(dim, row if row and row["contract"] else None))

    new_text = text
    if new_lines:
        new_text = _inject_checks(new_text, new_lines)
    if bound != channel:
        new_text = _replace_frontmatter_line(new_text, "channel", st._yaml_scalar(channel))
    seed = str(descriptor.get("harness_context_seed", "")).strip()
    seeded = bool(seed) and not (fm.get("harness_context") or "").strip()
    if seeded:
        new_text = _replace_frontmatter_line(new_text, "harness_context", st._yaml_scalar(seed))

    if new_text != text:
        with open(spec_path, "w", encoding="utf-8", newline="") as f:
            f.write(new_text)
    return {
        "spec": spec_path.name, "channel": channel, "injected": injected, "already_covered": already,
        "harness_context_seeded": seeded, **_risk_report(descriptor, fm.get("risk")), "notes": notes,
    }


def format_report(result: dict, spec_path: Path) -> str:
    lines = [
        f"Channel Bound: {spec_path.name}  <- channel: {result['channel']}",
        "=" * 44,
        f"Injected:        {len(result['injected'])} acceptance check(s)"
        + (f" (dimensions: {', '.join(result['injected'])})" if result["injected"] else " — every dimension was already covered"),
        f"harness_context: {'seeded from the descriptor' if result['harness_context_seeded'] else 'already set'}",
    ]
    if result["risk_floor"]:
        verdict = (f"a raise to {result['risk_floor']} is needed (tier is {result['current_risk']}) — "
                   f"confirm it, then `spec_transition.py risk {result['risk_floor']}`"
                   if result["raise_needed"] else f"tier {result['current_risk']} already meets it")
        lines.append(f"Risk floor:      {result['risk_floor']} — {verdict}")
    lines += [f"Note:            {n}" for n in result["notes"]]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bind a spec to its delivery channel and inject the acceptance dimensions")
    parser.add_argument("--spec", required=True, help="Path to specs/NNNN-name.md")
    parser.add_argument("--channel", help="The channel to bind (otherwise the spec's own `channel:`)")
    parser.add_argument("--interaction-spec", dest="interaction_spec", help="channel-interaction-spec.md to take each line from")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--state", help="Path to .sdlc/state.yaml (workflow mode)")
    where.add_argument("--repo", help="Repo root (the interaction spec is found under .sdlc/)")
    parser.add_argument("--channels-dir", default=str(PLUGIN_ROOT / "channels"), help="Directory of channel descriptors")
    parser.add_argument("--json", action="store_true", help="Emit the result as one JSON document")
    args = parser.parse_args(argv)

    root = Path(args.state).resolve().parent.parent if args.state else (Path(args.repo) if args.repo else None)
    interaction = Path(args.interaction_spec) if args.interaction_spec else (
        root / DEFAULT_INTERACTION_SPEC if root and (root / DEFAULT_INTERACTION_SPEC).exists() else None)
    try:
        result = bind(Path(args.spec), args.channel, Path(args.channels_dir), interaction)
    except BindError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2) if args.json else format_report(result, Path(args.spec)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
