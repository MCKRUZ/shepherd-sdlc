"""bind_channel.py — the mechanical half of /sprd-channel (spec 0021).

The command's steps 4 and 5 are a merge of two tables: set the spec's `channel:`, seed
`harness_context`, and append one acceptance-check line per channel dimension the spec does not
yet cover, taking each line from the feature's interaction spec when it has one and from the
channel descriptor's example otherwise. Nothing there needs a model, so it is a script.

What these protect, in order of how much it would hurt:
  1. NOTHING ELSE MOVES. It edits the `channel:` and `harness_context` lines and the Acceptance
     Checks section, and no other byte of a spec a person has written.
  2. IT CAN BE RUN AGAIN. A second run changes nothing; a different channel is refused.
  3. IT NEVER DECIDES RISK. It reports the channel's floor; raising the tier stays a person's act.
  4. THE SPEC STAYS READY. A spec that cleared the Definition of Ready still does.
"""

import difflib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import check_spec
from bind_channel import BindError, bind

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "bind_channel.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "specs"
SPEC = FIXTURES / "0042-voice-claim-intake.md"
INTERACTION = FIXTURES / "voice-interaction-spec.md"
CHANNELS = ROOT / "channels"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

VOICE = ["turn-taking", "barge-in", "intent-capture", "latency-budget", "readback-confirmation", "fallback-to-human"]


def make_spec(tmp_path, newline="\n", mutate=None):
    text = SPEC.read_text(encoding="utf-8")
    if mutate:
        text = mutate(text)
    path = tmp_path / "0042-voice-claim-intake.md"
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace("\n", newline))
    return path


def raw(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def run_cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, encoding="utf-8", env=ENV)


def frontmatter(text):
    return check_spec.parse_frontmatter(text)[0]


class TestBinding:
    def test_sets_the_channel_seeds_harness_context_and_appends_one_line_per_uncovered_dimension(self, tmp_path):
        path = make_spec(tmp_path)
        result = bind(path, "voice", CHANNELS)
        fm = frontmatter(raw(path))
        assert fm["channel"] == "voice"
        assert fm["harness_context"] == "voice turn pipeline"
        assert result["injected"] == VOICE
        accept = check_spec.extract_section(check_spec.parse_frontmatter(raw(path))[1], "Acceptance Checks")
        for dim in VOICE:
            assert f"(channel: {dim})" in accept

    def test_without_an_interaction_spec_each_line_is_the_descriptors_example_check(self, tmp_path):
        path = make_spec(tmp_path)
        bind(path, "voice", CHANNELS)
        assert "- [ ] When the caller begins speaking during TTS, output stops within 200 ms.   (channel: barge-in)" in raw(path)

    def test_with_an_interaction_spec_its_row_wins_and_a_placeholder_row_falls_back_to_the_example(self, tmp_path):
        path = make_spec(tmp_path)
        bind(path, "voice", CHANNELS, interaction_spec=INTERACTION)
        text = raw(path)
        assert "- [ ] When the caller speaks during a prompt, the prompt stops within 200 ms.   (channel: barge-in)" in text
        # latency-budget's interaction row is still template placeholders, so the descriptor's example is used
        assert "No response gap exceeds 1200 ms without a hold/filler cue; a gap over 3 s is a failure.   (channel: latency-budget)" in text

    def test_a_dimension_the_spec_already_covers_is_left_alone(self, tmp_path):
        path = make_spec(tmp_path, mutate=lambda t: t.replace(
            "- [ ] A caller who hangs up", "- [ ] The agent yields the turn after every prompt (channel: turn-taking)\n- [ ] A caller who hangs up", 1))
        result = bind(path, "voice", CHANNELS)
        assert "turn-taking" not in result["injected"] and result["already_covered"] == ["turn-taking"]
        assert raw(path).count("(channel: turn-taking)") == 1

    def test_an_existing_harness_context_is_not_overwritten(self, tmp_path):
        path = make_spec(tmp_path, mutate=lambda t: t.replace('harness_context: ""', 'harness_context: "the existing intake handler"', 1))
        result = bind(path, "voice", CHANNELS)
        assert frontmatter(raw(path))["harness_context"] == "the existing intake handler"
        assert result["harness_context_seeded"] is False

    def test_the_blank_checkbox_placeholder_a_new_spec_carries_is_replaced_not_left_beside_real_lines(self, tmp_path):
        path = make_spec(tmp_path, mutate=lambda t: t.replace(
            "- [ ] A completed intake call creates exactly one claim record and reads its 8-character reference back to the caller\n- [ ] A caller who hangs up before confirming creates no claim record\n", "- [ ]\n", 1))
        bind(path, "voice", CHANNELS)
        section = check_spec.extract_section(check_spec.parse_frontmatter(raw(path))[1], "Acceptance Checks")
        assert "- [ ]\n" not in section and "- [ ]\r\n" not in section


class TestNothingElseMoves:
    @pytest.mark.parametrize("newline", ["\n", "\r\n"])
    def test_only_the_channel_line_the_harness_context_line_and_the_acceptance_section_change(self, tmp_path, newline):
        path = make_spec(tmp_path, newline=newline)
        before = raw(path).splitlines()
        bind(path, "voice", CHANNELS)
        after = raw(path).splitlines()
        changed = [line for line in difflib.ndiff(before, after) if line[:1] in "+-"]
        allowed = ("channel:", "harness_context:", "- [ ]")
        for line in changed:
            assert line[2:].lstrip().startswith(allowed), f"unexpected change: {line!r}"

    def test_a_crlf_spec_stays_crlf_with_no_stray_lf(self, tmp_path):
        path = make_spec(tmp_path, newline="\r\n")
        bind(path, "voice", CHANNELS)
        data = path.read_bytes()
        assert data.count(b"\n") == data.count(b"\r\n")

    def test_a_spec_with_only_lf_stays_only_lf(self, tmp_path):
        path = make_spec(tmp_path)
        bind(path, "voice", CHANNELS)
        assert b"\r" not in path.read_bytes()

    def test_everything_after_the_acceptance_section_is_byte_identical(self, tmp_path):
        path = make_spec(tmp_path)
        original_tail = raw(path).split("## Risk Tier", 1)[1]
        bind(path, "voice", CHANNELS)
        assert raw(path).split("## Risk Tier", 1)[1] == original_tail


class TestRerunsAndConflicts:
    def test_a_second_run_with_the_same_arguments_changes_no_byte(self, tmp_path):
        path = make_spec(tmp_path)
        bind(path, "voice", CHANNELS)
        first = path.read_bytes()
        result = bind(path, "voice", CHANNELS)
        assert path.read_bytes() == first
        assert result["injected"] == [] and result["harness_context_seeded"] is False

    def test_a_different_channel_than_the_one_bound_is_refused_and_changes_nothing(self, tmp_path):
        path = make_spec(tmp_path)
        bind(path, "voice", CHANNELS)
        before = path.read_bytes()
        with pytest.raises(BindError, match="voice"):
            bind(path, "chat", CHANNELS)
        assert path.read_bytes() == before

    def test_binding_the_channel_the_spec_already_names_proceeds(self, tmp_path):
        path = make_spec(tmp_path, mutate=lambda t: t.replace('channel: ""', "channel: voice", 1))
        assert bind(path, "voice", CHANNELS)["injected"] == VOICE

    def test_the_channel_may_be_taken_from_the_spec_when_not_given(self, tmp_path):
        path = make_spec(tmp_path, mutate=lambda t: t.replace('channel: ""', "channel: voice", 1))
        assert bind(path, None, CHANNELS)["channel"] == "voice"


class TestRefusals:
    def _unchanged(self, path, match, **kw):
        before = path.read_bytes()
        with pytest.raises(BindError, match=match):
            bind(path, kw.pop("channel", "voice"), kw.pop("channels_dir", CHANNELS), **kw)
        assert path.read_bytes() == before

    def test_no_channel_given_and_none_bound(self, tmp_path):
        self._unchanged(make_spec(tmp_path), "no channel", channel=None)

    def test_a_channel_with_no_descriptor(self, tmp_path):
        self._unchanged(make_spec(tmp_path), "descriptor", channel="nonesuch")

    def test_a_spec_with_no_acceptance_checks_section(self, tmp_path):
        path = make_spec(tmp_path, mutate=lambda t: t.replace("## Acceptance Checks", "## Checks", 1))
        self._unchanged(path, "Acceptance Checks")

    def test_a_spec_that_does_not_exist(self, tmp_path):
        with pytest.raises(BindError, match="not found"):
            bind(tmp_path / "gone.md", "voice", CHANNELS)

    def test_a_spec_with_no_frontmatter(self, tmp_path):
        path = tmp_path / "s.md"
        path.write_text("# Just a heading\n\n## Acceptance Checks\n- [ ] x\n", encoding="utf-8")
        self._unchanged(path, "frontmatter")


class TestRisk:
    def test_reports_the_channels_floor_and_that_a_raise_is_needed_but_never_changes_the_tier(self, tmp_path):
        path = make_spec(tmp_path)
        result = bind(path, "voice", CHANNELS)
        assert (result["risk_floor"], result["current_risk"], result["raise_needed"]) == ("HIGH", "MEDIUM", True)
        assert frontmatter(raw(path))["risk"] == "MEDIUM"

    def test_no_raise_is_needed_when_the_spec_is_already_at_or_above_the_floor(self, tmp_path):
        path = make_spec(tmp_path, mutate=lambda t: t.replace("risk: MEDIUM", "risk: HIGH", 1).replace("**Tier:** MEDIUM", "**Tier:** HIGH").replace("**Ladder depth:** MEDIUM", "**Ladder depth:** HIGH"))
        assert bind(path, "voice", CHANNELS)["raise_needed"] is False


class TestSpecStaysReady:
    def test_every_blocking_check_that_passed_before_still_passes_after(self, tmp_path):
        path = make_spec(tmp_path)

        def blocking_failures(text):
            return [f["check"] for f in check_spec.check_spec_text(text) if f["severity"] == "MUST" and not f["passed"]]

        assert blocking_failures(raw(path)) == []
        bind(path, "voice", CHANNELS)
        assert blocking_failures(raw(path)) == []

    def test_binding_resolves_the_harness_context_advisory(self, tmp_path):
        path = make_spec(tmp_path)
        bind(path, "voice", CHANNELS)
        assert not [f for f in check_spec.check_spec_text(raw(path)) if "harness_context" in f["message"] and not f["passed"]]


class TestCli:
    def test_json_prints_one_document_with_the_reported_fields(self, tmp_path):
        path = make_spec(tmp_path)
        proc = run_cli("--spec", str(path), "--channel", "voice", "--json")
        assert proc.returncode == 0, proc.stderr
        doc = json.loads(proc.stdout)
        assert set(doc) >= {"spec", "channel", "injected", "already_covered", "harness_context_seeded", "risk_floor", "current_risk", "raise_needed"}
        assert doc["injected"] == VOICE

    def test_a_refusal_exits_one_with_one_line_on_stderr_and_no_traceback(self, tmp_path):
        path = make_spec(tmp_path)
        before = path.read_bytes()
        proc = run_cli("--spec", str(path), "--channel", "nonesuch")
        assert proc.returncode == 1 and proc.stderr.startswith("Error:") and "Traceback" not in proc.stderr
        assert path.read_bytes() == before

    def test_workflow_mode_finds_the_interaction_spec_in_its_default_place(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / ".sdlc" / "artifacts" / "02-design" / "experience").mkdir(parents=True)
        (repo / ".sdlc" / "state.yaml").write_text("project: demo\n", encoding="utf-8")
        (repo / ".sdlc" / "artifacts" / "02-design" / "experience" / "channel-interaction-spec.md").write_text(
            INTERACTION.read_text(encoding="utf-8"), encoding="utf-8")
        (repo / "specs").mkdir()
        spec = repo / "specs" / "0042-voice-claim-intake.md"
        spec.write_text(SPEC.read_text(encoding="utf-8"), encoding="utf-8")
        proc = run_cli("--spec", str(spec), "--channel", "voice", "--state", str(repo / ".sdlc" / "state.yaml"), "--json")
        assert proc.returncode == 0, proc.stderr
        assert "When the caller speaks during a prompt, the prompt stops within 200 ms." in spec.read_text(encoding="utf-8")

    def test_repo_mode_equals_state_mode(self, tmp_path):
        repo = tmp_path / "repo"
        (repo / ".sdlc" / "artifacts" / "02-design" / "experience").mkdir(parents=True)
        (repo / ".sdlc" / "artifacts" / "02-design" / "experience" / "channel-interaction-spec.md").write_text(
            INTERACTION.read_text(encoding="utf-8"), encoding="utf-8")
        (repo / "specs").mkdir()
        spec = repo / "specs" / "0042-voice-claim-intake.md"
        spec.write_text(SPEC.read_text(encoding="utf-8"), encoding="utf-8")
        assert run_cli("--spec", str(spec), "--channel", "voice", "--repo", str(repo)).returncode == 0
        assert "When the caller speaks during a prompt" in spec.read_text(encoding="utf-8")


class TestFrontmatterEdgeCases:
    """Closing the advisories from the correctness review of this PR."""

    def test_the_templates_inline_comment_survives_on_the_lines_that_are_rewritten(self, tmp_path):
        path = make_spec(tmp_path)
        bind(path, "voice", CHANNELS)
        text = raw(path)
        assert next(l for l in text.splitlines() if l.startswith("channel:")).endswith("# optional — delivery surface (see channels/); blank = channel-agnostic")
        assert next(l for l in text.splitlines() if l.startswith("harness_context:")).endswith("# the ONE existing pattern this change reuses (DoR requires this named)")

    def test_a_value_with_no_comment_after_it_is_still_replaced_cleanly(self, tmp_path):
        path = make_spec(tmp_path, mutate=lambda t: t.replace('channel: ""              # optional — delivery surface (see channels/); blank = channel-agnostic', 'channel: ""', 1))
        bind(path, "voice", CHANNELS)
        assert "channel: 'voice'\n" in raw(path)

    def test_a_spec_whose_frontmatter_is_never_closed_is_refused_and_left_alone(self, tmp_path):
        path = tmp_path / "broken.md"
        path.write_text('---\nspec: "0042"\nchannel: ""\n\n# no closing fence\n\n## Acceptance Checks\n- [ ] x\n', encoding="utf-8")
        before = path.read_bytes()
        with pytest.raises(BindError, match="frontmatter"):
            bind(path, "voice", CHANNELS)
        assert path.read_bytes() == before


def test_a_field_missing_from_a_crlf_specs_frontmatter_is_appended_with_a_crlf_line_ending(tmp_path):
    path = make_spec(tmp_path, newline="\r\n", mutate=lambda t: t.replace('harness_context: ""      # the ONE existing pattern this change reuses (DoR requires this named)\n', "", 1))
    assert "harness_context" not in frontmatter(raw(path))
    bind(path, "voice", CHANNELS)
    data = path.read_bytes()
    assert data.count(b"\n") == data.count(b"\r\n")
    assert frontmatter(raw(path))["harness_context"] == "voice turn pipeline"
