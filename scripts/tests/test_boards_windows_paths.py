"""B5 fix -- what the Windows leg of CI found, pinned so a macOS or Linux run fails the same way it did.

Git for Windows checks text out CRLF by default (`core.autocrlf=true`), and a temp path there is `C:\\Users\\...`.
Neither is visible from a POSIX checkout, so each root cause gets a test here that reproduces it on any platform:

  * the Boards mini repositories (`fixtures/boards_repo*/`) are byte-exact test inputs -- the `.proposed` writer's
    tests splice spans into them and compare against LF text, and the plan golden pins a hash over what they hold --
    so `.gitattributes` must check them out LF everywhere (`eol=lf` wins over any `core.autocrlf`);
  * a CRLF checkout of the same commit is the same source: every projection, its `source_sha` and its
    `projection_hash` are what the LF checkout reads, or a ledger written on one machine says "the repo moved" on the
    other (the Windows leg printed `plan 0c81e0348031` for the golden's `plan 1d0617c03373`).

The temp-path scrub (`ado_transport.invoke_body`) is pinned beside its siblings in `test_boards_transport_body.py`,
and the CRLF golden plan beside the golden in `test_boards_sync_cli_b2.py`. Nothing here spawns `az` (`boards_env`
forbids it at the seam); the one process started is `git check-attr`, read-only.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401

import re
import shutil
import subprocess
from pathlib import Path

import pytest

import ado_sync  # noqa: F401  (imports and so registers every projection source: tree, findings, breadth)
import ado_sync_model as model
import ado_sync_sources as sources
import boards_contract as bc

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
MINI_REPOS = ("boards_repo", "boards_repo_p1", "boards_repo_tree")
TREE_REQUIREMENTS = ".sdlc/artifacts/01-requirements/requirements.md"


def mini_files() -> list[Path]:
    found = [p for name in MINI_REPOS for p in sorted((FIXTURES / name).rglob("*")) if p.is_file()]
    assert found, "the Boards mini repositories moved: update MINI_REPOS"
    return found


def to_crlf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


# --- the fixtures check out LF on every platform ---------------------------------------------------------------

def test_the_mini_repositories_hold_no_carriage_return():
    """What the Windows leg saw: every fixture CRLF, so `text.replace("\\n", "\\r\\n")` made `\\r\\r\\n`."""
    assert [p.relative_to(FIXTURES).as_posix() for p in mini_files() if b"\r" in p.read_bytes()] == []


def test_gitattributes_checks_every_mini_repository_file_out_lf():
    """The cause, not the symptom: an `eol=lf` attribute, which `core.autocrlf` cannot override."""
    rels = [p.relative_to(ROOT).as_posix() for p in mini_files()]
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout; the attribute cannot be asked about")
    proc = subprocess.run([git, "check-attr", "eol", "--", *rels], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    answers = dict(line.rsplit(": eol: ", 1) for line in proc.stdout.splitlines())
    assert {rel: answers.get(rel) for rel in rels} == {rel: "lf" for rel in rels}


# --- a CRLF checkout projects the same items --------------------------------------------------------------------

def copy_mini(src: Path, dst: Path, *, crlf: bool) -> Path:
    shutil.copytree(src, dst)
    if src.name == "boards_repo_tree":
        # the tree fixture's FR-099 sits under no domain heading on purpose (the loaders refuse it); cut, as the
        # tree tests' `clean` fixture does, so the requirement, domain and epic rows are compared too
        path = dst / TREE_REQUIREMENTS
        text = path.read_bytes().decode("utf-8")
        start, end = text.index("<!-- fixture: FR-099"), text.index("### Order Intake")
        assert start < end, "the fixture's stray FR-099 moved: update this strip"
        text = re.sub(r"(?m)^\| FR-099 .*\n", "", text[:start] + text[end:])
        path.write_bytes(text.encode("utf-8"))
    if crlf:
        for path in dst.rglob("*"):
            if path.is_file():
                path.write_bytes(to_crlf(path.read_bytes()))
    return dst


def projected(root: Path) -> dict[str, dict]:
    kinds = [k for k in bc.KINDS if k in sources.SOURCES]
    return {p["ref"]: {**p, "projection_hash": model.projection_hash(p)}
            for p in sources.projections(root, {}, {}, kinds)}


@pytest.mark.parametrize("name", MINI_REPOS)
def test_a_crlf_checkout_projects_every_item_exactly_as_the_lf_one_does(tmp_path, name):
    lf = copy_mini(FIXTURES / name, tmp_path / "lf", crlf=False)
    crlf = copy_mini(FIXTURES / name, tmp_path / "crlf", crlf=True)
    assert any(b"\r\n" in p.read_bytes() for p in crlf.rglob("*") if p.is_file())
    want, got = projected(lf), projected(crlf)
    assert want, f"{name} projected nothing: the comparison would prove nothing"
    assert list(got) == list(want)
    moved = {ref: sorted(k for k in want[ref] if want[ref][k] != got[ref][k]) for ref in want if got[ref] != want[ref]}
    assert moved == {}


def test_a_real_edit_still_moves_the_source_sha(tmp_path):
    """Unifying line endings is all the hash forgives: one changed word moves the spec, and only the spec."""
    root = copy_mini(FIXTURES / "boards_repo", tmp_path / "repo", crlf=True)
    before = projected(root)
    spec = next((root / "specs").glob("0004-*.md"))
    spec.write_bytes(spec.read_bytes().replace(b"409", b"410", 1))
    after = projected(root)
    assert {ref for ref in before if before[ref]["source_sha"] != after[ref]["source_sha"]} == {"sdlc:spec:0004"}
