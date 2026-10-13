"""/sprd-next must not ask for sign-off while a sign-off question is unconfirmed.

The confirmations are recorded by a script, but the rule that they matter lives in the command's
instructions to Claude — the protected advance script is deliberately untouched. So the
instructions are pinned here: if the step goes missing, the checkboxes stop meaning anything and
nothing else would notice.
"""

from pathlib import Path

COMMAND = (Path(__file__).resolve().parent.parent.parent / "commands" / "sprd-next.md").read_text(encoding="utf-8")


def test_the_command_reads_the_confirmation_status_before_asking_for_sign_off():
    assert "sign_off_confirmations.py" in COMMAND
    assert COMMAND.index("sign_off_confirmations.py") < COMMAND.index("HITL GATE")


def test_the_command_refuses_to_proceed_past_an_unconfirmed_question():
    lowered = COMMAND.lower()
    assert "unconfirmed" in lowered
    assert "do not ask" in lowered or "do not proceed" in lowered


def test_the_command_records_a_confirmation_only_when_the_human_gives_it():
    lowered = COMMAND.lower()
    assert "never confirm" in lowered or "never tick" in lowered
