"""Static command-prose contract lint (the STATIC half of the command-prose safety harness).

The plugin's 25+ commands/*.md files are prose instructions that embed real CLI
invocations. The scripts are unit-tested, but nothing catches a *doc* that names a
script, subcommand, flag, agent, or repo file that no longer exists — that
doc-to-script drift is the most common silent breakage (a renamed script, a
removed flag, a deleted agent). This module parses every fenced code block in
commands/*.md, extracts the plugin's `uv run ... scripts/<name>.py` invocations,
and checks each one against ground truth:

  1. the referenced scripts/<name>.py exists;
  2. every subcommand + `--flag` used appears in the script's own `--help`
     (captured live via subprocess, cached per (script, subcommand-tuple));
  3. backticked agent references resolve to an agents/<name>.md file;
  4. `references/<x>.md` / `templates/<...>` paths mentioned in the doc exist.

OUT OF SCOPE for v1: live "does the model actually follow the doc" evals. This
lint only checks that the invocations a doc names are *real* — not that the
surrounding prose reasons about them correctly.

Conservative by construction — the lint must not cry wolf. Anything it cannot
classify with confidence (an ambiguous positional-vs-subcommand token, a
placeholder like `<spec-path>`/`[<stem>]`, a short flag, a script whose `--help`
does not exit 0) is SKIPPED, never reported. Genuine-but-intentional references
(e.g. a harness-installed target-repo agent that is not a plugin agent) are
carried in the module-level ALLOWLIST with a comment.

Runtime: `--help` output is cached at module scope per (script, subcommand-tuple),
so the whole harness issues ~30 `uv run ... --help` subprocesses on a cold cache
and finishes well under 30s (measured ~5-8s locally; a single cached help call is
~0.1s).
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
COMMANDS_DIR = PLUGIN_ROOT / "commands"
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
AGENTS_DIR = PLUGIN_ROOT / "agents"


# ---------------------------------------------------------------------------
# ALLOWLIST — doc filename -> list of (substring, reason). A violation whose
# message contains an allowlisted substring for its doc is suppressed. Keep this
# empty unless a finding is genuinely intentional; every entry needs a reason.
# ---------------------------------------------------------------------------
ALLOWLIST: dict[str, list[tuple[str, str]]] = {
    # `ux-reviewer` is a code-review sub-agent the *harness installer* writes into
    # the target repo (composed from stack packs), not a plugin agents/*.md file —
    # so it correctly has no agents/ux-reviewer.md. Referenced only in setup prose.
    "sprd-setup.md": [
        ("references agent `ux-reviewer`", "harness-installed target-repo reviewer, not a plugin agent"),
    ],
}


# ---------------------------------------------------------------------------
# help capture (cached at module scope)
# ---------------------------------------------------------------------------
_HELP_CACHE: dict[tuple[str, tuple[str, ...]], tuple[int, str]] = {}


def get_help(script: str, chain: tuple[str, ...]) -> tuple[int, str]:
    """Return (returncode, combined stdout+stderr) of `script <chain...> --help`, cached."""
    key = (script, tuple(chain))
    if key in _HELP_CACHE:
        return _HELP_CACHE[key]
    cmd = [
        "uv", "run", "--project", str(SCRIPTS_DIR),
        str(SCRIPTS_DIR / f"{script}.py"),
        *chain, "--help",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        res = (r.returncode, (r.stdout or "") + "\n" + (r.stderr or ""))
    except Exception:  # noqa: BLE001 - a help subprocess failing must never crash the lint
        res = (1, "")
    _HELP_CACHE[key] = res
    return res


_CHOICE_GROUP_RE = re.compile(r"\{([a-z0-9_,-]+)\}")
_WORD_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def help_subcommands(script: str, chain: tuple[str, ...]) -> set[str]:
    """Lowercase subcommand choices argparse advertises at this help level (empty if leaf/failed)."""
    code, text = get_help(script, chain)
    if code != 0:
        return set()
    out: set[str] = set()
    for grp in _CHOICE_GROUP_RE.findall(text):
        for tok in grp.split(","):
            if _WORD_RE.match(tok):
                out.add(tok)
    return out


_FLAG_RE = re.compile(r"--[A-Za-z][A-Za-z0-9-]*")


def valid_flags(script: str, chain: tuple[str, ...]) -> set[str]:
    """Union of --flags from the top level down to `chain` (so parent/global flags count too)."""
    flags: set[str] = set()
    for i in range(len(chain) + 1):
        code, text = get_help(script, chain[:i])
        if code == 0:
            flags.update(_FLAG_RE.findall(text))
    return flags


# ---------------------------------------------------------------------------
# markdown / invocation extraction
# ---------------------------------------------------------------------------
_SCRIPT_RE = re.compile(r"scripts/([A-Za-z0-9_]+)\.py")


def iter_fenced_blocks(text: str):
    """Yield the inner text of every ``` fenced code block in a markdown document."""
    lines = text.splitlines()
    inside = False
    buf: list[str] = []
    for line in lines:
        if line.lstrip().startswith("```"):
            if inside:
                yield "\n".join(buf)
                buf = []
            inside = not inside
            continue
        if inside:
            buf.append(line)
    # an unterminated fence is ignored (defensive; docs are well-formed)


def join_continuations(block: str) -> list[str]:
    """Join backslash-newline continuations, return the block's logical lines."""
    joined = re.sub(r"\\\n", " ", block)
    return joined.splitlines()


def extract_invocations(block: str) -> list[tuple[str, str]]:
    """From a fenced block, return (script_name, argstring) for each plugin script invocation."""
    out: list[tuple[str, str]] = []
    for line in join_continuations(block):
        if "uv run" not in line or "scripts/" not in line:
            continue
        matches = list(_SCRIPT_RE.finditer(line))
        if not matches:
            continue
        # the `--project .../scripts` prefix has no `.py`; the real target is the
        # last scripts/<name>.py on the line. everything after it is the argstring.
        m = matches[-1]
        out.append((m.group(1), line[m.end():]))
    return out


# ---------------------------------------------------------------------------
# argstring tokenisation
# ---------------------------------------------------------------------------
def _unwrap(tok: str) -> str:
    """Strip wrapping quotes and brackets so `[--state`, `"<name>"`, `[<stem>]` classify cleanly."""
    prev = None
    t = tok.strip()
    while t and t != prev:
        prev = t
        if t and t[0] in "\"'([{":
            t = t[1:]
        if t and t[-1] in "\"')]}":
            t = t[:-1]
    return t


def _is_placeholder(core: str) -> bool:
    return core == "" or "<" in core or ">" in core or "{" in core or core == "..."


def analyse_invocation(script: str, argstring: str) -> tuple[tuple[str, ...], list[str], list[str]]:
    """Return (subcommand_chain, used_long_flags, skips) for one invocation.

    Subcommands are the leading positional tokens (before the first flag) that
    argparse actually advertises as choices, at most two deep. `skips` records
    anything intentionally not classified, for transparency only.
    """
    raw = argstring.split()
    tokens = [(_unwrap(t), t) for t in raw]

    # --- subcommand chain: only descend on tokens argparse lists as choices ---
    chain: list[str] = []
    skips: list[str] = []
    for core, _orig in tokens:
        if core.startswith("-"):
            break  # flags always follow the subcommand chain in these docs
        if _is_placeholder(core):
            break
        if not _WORD_RE.match(core):
            break
        if len(chain) >= 2:
            break
        choices = help_subcommands(script, tuple(chain))
        if core in choices and get_help(script, tuple(chain) + (core,))[0] == 0:
            chain.append(core)
            continue
        break  # a positional argument (e.g. FR-012), not a subcommand

    # --- used long flags ---
    used: list[str] = []
    for core, _orig in tokens:
        if not core.startswith("--"):
            continue
        name = core.split("=", 1)[0]
        if _FLAG_RE.fullmatch(name):
            if name not in used:
                used.append(name)
        else:
            skips.append(f"unclassifiable flag token {core!r}")
    return tuple(chain), used, skips


# ---------------------------------------------------------------------------
# cross-reference extraction (agents, repo files)
# ---------------------------------------------------------------------------
_AGENT_KEBAB = r"[a-z][a-z0-9]*(?:-[a-z0-9]+)+"
_AGENT_REF_RES = [
    re.compile(r"`(" + _AGENT_KEBAB + r")`\s+(?:sub-?)?agents?\b", re.IGNORECASE),
    re.compile(r"(?:sub-?)?agents?\s+`(" + _AGENT_KEBAB + r")`", re.IGNORECASE),
]
_FILE_REF_RE = re.compile(r"(?:references|templates)/[A-Za-z0-9._/-]+")


def agent_refs(text: str) -> set[str]:
    """Backticked kebab tokens sitting next to the word 'agent' — the conservative agent signal."""
    out: set[str] = set()
    for rx in _AGENT_REF_RES:
        for m in rx.finditer(text):
            out.add(m.group(1))
    return out


def file_refs(text: str) -> set[str]:
    """Concrete references/ and templates/ paths (placeholder-bearing paths are skipped)."""
    out: set[str] = set()
    for m in _FILE_REF_RE.finditer(text):
        nxt = text[m.end():m.end() + 1]
        if nxt in "<{*$":  # a placeholder immediately follows -> not a concrete path
            continue
        path = m.group(0).rstrip(".")
        if path in ("references", "templates"):
            continue
        out.add(path)
    return out


# ---------------------------------------------------------------------------
# the lint
# ---------------------------------------------------------------------------
def command_docs() -> list[Path]:
    return sorted(COMMANDS_DIR.glob("*.md"))


def _allowlisted(doc: str, message: str) -> bool:
    for sub, _reason in ALLOWLIST.get(doc, []):
        if sub in message:
            return True
    return False


def scan_doc(name: str, text: str, agent_set: set[str]) -> tuple[list[str], int]:
    """Raw (pre-allowlist) contract violations for one doc's text, + its invocation count.

    Factored out of collect_violations so the self-tests can drive the exact same
    detection path with planted defects: a silent no-op here fails those tests too.
    """
    raw: list[str] = []
    n_invocations = 0

    # 1-3: script existence + subcommand/flag contracts
    for block in iter_fenced_blocks(text):
        for script, argstring in extract_invocations(block):
            n_invocations += 1
            script_path = SCRIPTS_DIR / f"{script}.py"
            if not script_path.exists():
                raw.append(f"{name}: references scripts/{script}.py — no such script")
                continue
            chain, used, _skips = analyse_invocation(script, argstring)
            top_code, _ = get_help(script, ())
            if top_code != 0:
                continue  # can't introspect flags; skip rather than cry wolf
            allowed = valid_flags(script, chain)
            sub = (" " + " ".join(chain)) if chain else ""
            for flag in used:
                if flag not in allowed:
                    raw.append(
                        f"{name}: `{script}.py{sub}` uses {flag} — not in its --help"
                    )

    # 4a: agent cross-references
    for ref in sorted(agent_refs(text)):
        if ref not in agent_set:
            raw.append(f"{name}: references agent `{ref}` — no agents/{ref}.md")

    # 4b: repo file cross-references
    for ref in sorted(file_refs(text)):
        if not (PLUGIN_ROOT / ref).exists():
            raw.append(f"{name}: references {ref} — path does not exist")

    return raw, n_invocations


def collect_violations() -> tuple[list[str], list[str], int]:
    """Return (violations, suppressed, invocation_count) across every command doc."""
    agent_set = {p.stem for p in AGENTS_DIR.glob("*.md")}
    violations: list[str] = []
    suppressed: list[str] = []
    n_invocations = 0

    for doc in command_docs():
        name = doc.name
        text = doc.read_text(encoding="utf-8")
        raw, n = scan_doc(name, text, agent_set)
        n_invocations += n
        for msg in raw:
            (suppressed if _allowlisted(name, msg) else violations).append(msg)

    return violations, suppressed, n_invocations


# module-scope single pass (help cache makes the tests below share the work)
_VIOLATIONS, _SUPPRESSED, _N_INVOCATIONS = collect_violations()


def test_extraction_found_invocations():
    """Guard against a silently-broken parser: the docs really do embed script calls."""
    assert _N_INVOCATIONS >= 25, (
        f"only extracted {_N_INVOCATIONS} invocations — the parser is likely broken"
    )


def test_command_docs_reference_only_real_contracts():
    """Every script/subcommand/flag/agent/file a command doc names must actually exist."""
    assert not _VIOLATIONS, (
        "command-prose drift detected (doc references something that no longer exists):\n  "
        + "\n  ".join(_VIOLATIONS)
    )


# ---------------------------------------------------------------------------
# self-tests — prove the lint actually FIRES on planted defects. Without these,
# a silent degradation of collect_violations() to a no-op (a broken regex, a
# swallowed exception, an over-broad allowlist) would leave the two tests above
# passing vacuously and the drift they guard against undetected. Each case below
# feeds synthetic markdown / a fake agent name through the real detection path
# (scan_doc, the same one collect_violations uses) and asserts the defect surfaces.
# ---------------------------------------------------------------------------
_TEST_AGENTS = {"orchestrator", "requirements-analyst"}  # a couple of real stems


def _fence(*lines: str) -> str:
    """Wrap lines in a ``` code fence so iter_fenced_blocks picks them up."""
    return "```\n" + "\n".join(lines) + "\n```"


def test_selftest_unknown_flag_is_reported():
    """A real script called with a flag absent from its --help must be flagged."""
    text = _fence("uv run --project scripts scripts/audit_artifacts.py report --no-such-flag")
    raw, n = scan_doc("synthetic.md", text, _TEST_AGENTS)
    assert n == 1
    assert any("--no-such-flag" in m for m in raw), raw


def test_selftest_real_flag_is_not_reported():
    """The flag path must not over-report: a genuine --json/--repo stays clean.

    This also proves --help introspection is live — if get_help silently returned
    empty, every real flag would (wrongly) be reported and this would fail.
    """
    text = _fence("uv run --project scripts scripts/audit_artifacts.py report --json --repo /tmp/x")
    raw, n = scan_doc("synthetic.md", text, _TEST_AGENTS)
    assert n == 1
    assert raw == [], raw


def test_selftest_nonexistent_script_is_reported():
    """An invocation of scripts/<name>.py with no such file must be flagged."""
    text = _fence("uv run --project scripts scripts/does_not_exist.py report --json")
    raw, _n = scan_doc("synthetic.md", text, _TEST_AGENTS)
    assert any("does_not_exist.py" in m and "no such script" in m for m in raw), raw


def test_selftest_unknown_agent_ref_is_reported():
    """A backticked kebab name next to 'agent' with no agents/<name>.md must be flagged."""
    text = "run the `made-up-agent` agent to do the thing"
    raw, _n = scan_doc("synthetic.md", text, _TEST_AGENTS)
    assert any("made-up-agent" in m for m in raw), raw


def test_selftest_known_agent_ref_is_not_reported():
    """A real agent name must not be flagged (guards against over-reporting)."""
    text = "run the `requirements-analyst` agent to do the thing"
    raw, _n = scan_doc("synthetic.md", text, _TEST_AGENTS)
    assert raw == [], raw


def test_selftest_nonexistent_file_ref_is_reported():
    """A concrete references/ path that does not exist must be flagged."""
    text = "see references/does-not-exist.md for details"
    raw, _n = scan_doc("synthetic.md", text, _TEST_AGENTS)
    assert any("references/does-not-exist.md" in m for m in raw), raw


def test_selftest_two_level_subcommand_vs_positional():
    """analyse_invocation must descend a 2-level subcommand but stop at a positional."""
    chain2, _used2, _ = analyse_invocation(
        "audit_artifacts", " version list requirements.md --repo /tmp/x"
    )
    assert chain2 == ("version", "list")  # both are argparse choices
    chain1, used1, _ = analyse_invocation("audit_artifacts", " impact FR-012 --repo /tmp/x")
    assert chain1 == ("impact",)  # FR-012 is a positional, not a subcommand
    assert "--repo" in used1


def test_selftest_allowlist_suppresses_only_matching_message():
    """_allowlisted must suppress exactly its substring, for its doc only — nothing broader."""
    doc = "sprd-setup.md"
    assert _allowlisted(
        doc, "sprd-setup.md: references agent `ux-reviewer` — no agents/ux-reviewer.md"
    )
    # a different agent under the same doc is NOT suppressed
    assert not _allowlisted(
        doc, "sprd-setup.md: references agent `other-agent` — no agents/other-agent.md"
    )
    # the same substring under a different doc is NOT suppressed
    assert not _allowlisted("other.md", "references agent `ux-reviewer`")


def test_selftest_clean_input_yields_no_violations():
    """A fully valid invocation produces zero violations (baseline for the above)."""
    text = _fence("uv run --project scripts scripts/audit_artifacts.py report --json")
    raw, n = scan_doc("synthetic.md", text, _TEST_AGENTS)
    assert n == 1
    assert raw == [], raw


if __name__ == "__main__":  # manual run: python test_command_contracts.py
    print(f"invocations parsed: {_N_INVOCATIONS}")
    print(f"help subprocesses:  {len(_HELP_CACHE)}")
    if _SUPPRESSED:
        print("suppressed (allowlisted):")
        for s in _SUPPRESSED:
            print("  " + s)
    if _VIOLATIONS:
        print("VIOLATIONS:")
        for v in _VIOLATIONS:
            print("  " + v)
        sys.exit(1)
    print("clean")
