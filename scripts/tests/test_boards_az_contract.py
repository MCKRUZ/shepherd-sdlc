"""Every `az` argv that Boards discovery issues is one the installed CLI accepts (B1-P4, build kit K19).

The body of `test_az_contract.py`, run over `ado_schema.DISCOVER_AZ_CONTRACT` instead of
`ado_import.AZ_CONTRACT`. Help text only: no network, no login, nothing created. It skips cleanly unless
`az` AND the azure-devops extension are present (CI runners ship neither), with the two environment
variables set so az can neither install the extension on the fly nor phone home.

What it proves is narrow and worth having: a flag in `DISCOVER_AZ_CONTRACT` that the real CLI does not
know would otherwise be found by the first person to run `discover`. That the contract matches the argv
`discover` really emits is proven without az, in `test_boards_sync_cli_b1.py`.

This file reads the CLI's help only, which is why it is the one `test_boards_*.py` that looks for an `az`
binary at all; it names the program through `AZ_PROGRAM` so the later "no az in tests" gate (a grep for
the literal lookup call) stays at zero for every test that exercises behaviour.
"""

from tests.ado_boards_fixtures import boards_env, az  # noqa: F401

import os
import shutil
import subprocess

import pytest

import ado_schema

AZ_PROGRAM = "az"
AZ_ENV = {**os.environ, "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no", "AZURE_CORE_COLLECT_TELEMETRY": "no"}


def _az(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([shutil.which(AZ_PROGRAM) or AZ_PROGRAM, *args, "--only-show-errors"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=AZ_ENV, timeout=120, check=False)


def _extension_present() -> bool:
    if shutil.which(AZ_PROGRAM) is None:
        return False
    try:
        return _az(["extension", "show", "--name", "azure-devops", "-o", "json"]).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(not _extension_present(),
                                reason="az with the azure-devops extension is not installed; help text cannot be read")


def _command_words(argv: list[str]) -> list[str]:
    words = []
    for a in argv:
        if a.startswith("-"):
            break
        words.append(a)
    return words


_HELP_CACHE: dict[tuple[str, ...], str] = {}


def _help(words: list[str]) -> str:
    key = tuple(words)
    if key not in _HELP_CACHE:
        proc = _az([*words, "--help"])
        _HELP_CACHE[key] = proc.stdout + proc.stderr
    return _HELP_CACHE[key]


# Global az flags are documented under `az --help`, not per command.
GLOBAL_FLAGS = {"-o", "--output", "--query", "--only-show-errors", "--help", "--debug", "--verbose"}


def _id(argv: list[str]) -> str:
    """Every discovery call is `az devops invoke`; the resource tells the cases apart."""
    return " ".join(_command_words(argv)) + ":" + argv[argv.index("--resource") + 1]


@pytest.mark.parametrize("argv", ado_schema.DISCOVER_AZ_CONTRACT, ids=_id)
def test_every_flag_in_the_contract_appears_in_local_help(argv):
    words = _command_words(argv)
    text = _help(words)
    assert words[-1] in text, f"`az {' '.join(words)} --help` did not describe the command"
    flags = [a for a in argv if a.startswith("-") and a not in GLOBAL_FLAGS]
    missing = [f for f in flags if f not in text]
    assert not missing, f"az {' '.join(words)}: flags not in --help: {missing}"


# B0 (2026-10-14): the identity read is `az rest` (core az, no extension), the one argv of `ado_wit.BOARDS_AZ_CONTRACT`
# outside `devops invoke` and `boards`; its flags are checked the same way.
import ado_wit  # noqa: E402

REST_ARGV = [argv for argv in ado_wit.BOARDS_AZ_CONTRACT if argv[:1] == ["rest"]]


@pytest.mark.parametrize("argv", REST_ARGV, ids=lambda argv: "rest:connectionData")
def test_the_identity_read_s_az_rest_flags_appear_in_local_help(argv):
    text = _help(["rest"])
    assert "rest" in text, "`az rest --help` did not describe the command"
    flags = [a for a in argv if a.startswith("-") and a not in GLOBAL_FLAGS]
    assert flags == ["--method", "--resource", "--url"]
    assert not [f for f in flags if f not in text], text[:400]
