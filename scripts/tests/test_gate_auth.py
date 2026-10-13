"""Tests for gate_auth.py — how the review gates sign in to Claude.

This script handles a real credential, so the tests are mostly about what it must NEVER do.
The happy path is one call to the code host; the value is entirely in the refusals.

  THE CREDENTIAL NEVER TOUCHES DISK. Not a config file, not a cache, not a temporary file. The
  code host already stores it encrypted, and a second copy on a laptop is a second thing that
  can leak — from the machine more likely to be lost.

  IT NEVER APPEARS IN A COMMAND LINE. An argument is visible to anything that can list
  processes. It goes through standard input instead.

  IT IS NEVER ECHOED, not even back at the person who mistyped it. A refusal that quotes the
  value puts it in a terminal history and in any screenshot of the failure.

  A WRITE IS READ BACK. This credential's failure mode is silent and late: a gate that cannot
  sign in fails on somebody ELSE's pull request, long after the person who set it walked away.
"""

import json
import subprocess
from pathlib import Path

import pytest

import gate_auth as ga


class FakeGh:
    """Stands in for the code host, and records exactly how it was called.

    Records argv and stdin separately, which is the point: several tests assert the credential
    was in one and never the other.
    """

    def __init__(self, secrets=(), fail=None):
        self.secrets = list(secrets)
        self.fail = fail or {}
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, cmd, input=None, capture_output=True, text=True, check=False):
        self.calls.append((list(cmd), input))
        if cmd[:2] == ["git", "-C"]:
            return subprocess.CompletedProcess(cmd, 0, "https://github.com/acme/widgets.git\n", "")
        verb = cmd[2] if len(cmd) > 2 else ""
        if verb == "list":
            if "list" in self.fail:
                return subprocess.CompletedProcess(cmd, 1, "", self.fail["list"])
            payload = json.dumps([{"name": n} for n in self.secrets])
            return subprocess.CompletedProcess(cmd, 0, payload, "")
        if verb == "set":
            if "set" in self.fail:
                return subprocess.CompletedProcess(cmd, 1, "", self.fail["set"])
            if not self.fail.get("silent_set"):
                self.secrets.append(cmd[3])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if verb == "delete":
            if "delete" in self.fail:
                return subprocess.CompletedProcess(cmd, 1, "", self.fail["delete"])
            self.secrets = [s for s in self.secrets if s != cmd[3]]
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")


GOOD_KEY = "sk-ant-api03-" + "a" * 40
GOOD_TOKEN = "sk-ant-oat01-" + "b" * 40


@pytest.fixture
def gh(monkeypatch):
    fake = FakeGh()
    monkeypatch.setattr(ga.subprocess, "run", fake)
    return fake


class TestTheCredentialNeverTouchesDisk:
    def test_setting_one_writes_no_file_anywhere_under_the_repo(self, tmp_path, gh):
        # The assertion is on the FILESYSTEM, not on the code — an implementation that started
        # caching "for convenience" would pass a mock-based test and fail this one.
        before = {p for p in tmp_path.rglob("*")}
        ga.set_credential(tmp_path, "api-key", GOOD_KEY)
        assert {p for p in tmp_path.rglob("*")} == before

    def test_nor_anywhere_under_the_home_directory_it_was_given(self, tmp_path, gh, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("USERPROFILE", str(home))
        ga.set_credential(tmp_path, "subscription", GOOD_TOKEN)
        assert list(home.rglob("*")) == []


class TestItNeverAppearsInACommandLine:
    def test_the_credential_goes_through_stdin(self, tmp_path, gh):
        ga.set_credential(tmp_path, "api-key", GOOD_KEY)
        set_call = next(c for c in gh.calls if c[0][:3] == ["gh", "secret", "set"])
        assert set_call[1] == GOOD_KEY

    def test_and_appears_in_NO_argument_of_ANY_call(self, tmp_path, gh):
        # Every call, not just the one that sets it: a later read-back that echoed the value
        # into an argument would be just as visible to anything listing processes.
        ga.set_credential(tmp_path, "api-key", GOOD_KEY)
        for argv, _ in gh.calls:
            assert not any(GOOD_KEY in str(a) for a in argv), argv


class TestItIsNeverEchoed:
    # Distinctive on purpose. Short or common strings ("no") and text the help message
    # legitimately contains (the console URL) make this assertion pass or fail for reasons
    # that have nothing to do with echoing — the first version of this test failed on exactly
    # that and proved nothing either way.
    @pytest.mark.parametrize("mode,bad", [
        # Each is something the validator genuinely REJECTS — an earlier version used values
        # it happily accepts (it is loose on purpose), so the test proved nothing.
        ("api-key", "MYACTUALSECRET-zzzq7"),                      # no sk-ant- prefix
        ("subscription", "short-zzzq7"),                          # too short to be a token
        ("api-key", "https://example.invalid/?t=zzzq7"),          # a URL, not a credential
    ])
    def test_a_refusal_does_not_quote_what_was_typed(self, mode, bad):
        # Somebody who pastes the wrong thing should not find it in their shell history via
        # the error message — or in a screenshot of the failure.
        with pytest.raises(ga.GateAuthError) as e:
            ga.validate(mode, bad)
        assert "zzzq7" not in str(e.value)

    def test_a_refusal_says_what_shape_was_expected_instead(self):
        with pytest.raises(ga.GateAuthError) as e:
            ga.validate("api-key", "nonsense")
        assert "sk-ant-" in str(e.value)

    def test_status_reports_only_WHETHER_a_credential_exists(self, tmp_path, monkeypatch):
        fake = FakeGh(secrets=[ga.API_KEY_SECRET])
        monkeypatch.setattr(ga.subprocess, "run", fake)
        result = ga.status(tmp_path)
        assert result["configured"] == ["api-key"]
        assert GOOD_KEY not in json.dumps(result)


class TestAWriteIsReadBack:
    def test_a_set_the_code_host_silently_ignored_is_REFUSED(self, tmp_path, monkeypatch):
        # The failure this guards is silent and late: the command exits 0, nobody looks again,
        # and the gate fails weeks later on somebody else's pull request.
        fake = FakeGh(fail={"silent_set": True})
        monkeypatch.setattr(ga.subprocess, "run", fake)
        with pytest.raises(ga.GateAuthError) as e:
            ga.set_credential(tmp_path, "api-key", GOOD_KEY)
        assert e.value.kind == "not_confirmed"
        assert "admin" in str(e.value)

    def test_a_successful_set_is_confirmed_against_the_code_host(self, tmp_path, gh):
        result = ga.set_credential(tmp_path, "subscription", GOOD_TOKEN)
        assert result["ok"] and result["secret"] == ga.SUBSCRIPTION_SECRET
        assert ga.status(tmp_path)["configured"] == ["subscription"]


class TestWhatItRefusesBeforeSendingAnything:
    @pytest.mark.parametrize("empty", ["", "   ", "\n", None])
    def test_nothing_at_all(self, empty):
        with pytest.raises(ga.GateAuthError) as e:
            ga.validate("api-key", empty)
        assert e.value.kind == "empty"

    def test_a_whole_block_of_pasted_output(self):
        # The common mistake: copying the command AND its output together.
        with pytest.raises(ga.GateAuthError) as e:
            ga.validate("subscription", f"$ claude setup-token\n{GOOD_TOKEN}")
        assert e.value.kind == "multiline"

    def test_a_key_pasted_where_a_subscription_token_belongs_is_still_accepted(self):
        # Deliberately NOT refused. The two formats overlap today, and a validator that got
        # clever about telling them apart would start rejecting valid credentials the day
        # either format changes — a worse failure, because it blocks a correct setup.
        assert ga.validate("subscription", GOOD_KEY) == GOOD_KEY

    def test_surrounding_whitespace_is_forgiven(self, tmp_path, gh):
        # Pasting almost always brings a trailing newline. Refusing that would be pedantry.
        assert ga.validate("api-key", f"  {GOOD_KEY}\t") == GOOD_KEY

    def test_an_unknown_way_to_sign_in(self):
        with pytest.raises(ga.GateAuthError) as e:
            ga.validate("carrier-pigeon", GOOD_KEY)
        assert e.value.kind == "unknown_mode"

    def test_a_checkout_with_no_code_host_says_so_rather_than_failing_obscurely(
            self, tmp_path, monkeypatch):
        monkeypatch.setattr(ga.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
            a[0], 1, "", "fatal: No such remote 'origin'"))
        with pytest.raises(ga.GateAuthError) as e:
            ga.set_credential(tmp_path, "api-key", GOOD_KEY)
        assert e.value.kind == "no_remote"


class TestTheAnswersItGives:
    def test_no_credential_means_the_gates_cannot_sign_in(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ga.subprocess, "run", FakeGh())
        result = ga.status(tmp_path)
        assert result["gates_can_sign_in"] is False
        assert "fail closed" in ga.format_status(result)

    def test_not_signed_in_to_the_code_host_is_reported_as_that(self, tmp_path, monkeypatch):
        # Not as "no credential set". Those need completely different actions, and reporting
        # the wrong one sends somebody to reissue a key they already have.
        monkeypatch.setattr(ga.subprocess, "run",
                            FakeGh(fail={"list": "gh: You are not logged into any GitHub hosts"}))
        assert "gh auth login" in ga.status(tmp_path)["detail"]

    def test_both_set_is_not_an_error_but_says_which_one_signs_in(self, tmp_path, monkeypatch):
        # Worth saying plainly: somebody looking at a billed API key may believe it is the one
        # in use, and be surprised either way round.
        monkeypatch.setattr(ga.subprocess, "run",
                            FakeGh(secrets=[ga.API_KEY_SECRET, ga.SUBSCRIPTION_SECRET]))
        result = ga.status(tmp_path)
        assert sorted(result["configured"]) == ["api-key", "subscription"]
        assert "subscription token" in result["detail"]

    def test_the_metered_one_says_so_when_it_is_set(self, tmp_path, gh):
        # The cost is the actual decision between the two, so it is stated at the moment of
        # choosing rather than left in a document.
        assert "METERED" in ga.set_credential(tmp_path, "api-key", GOOD_KEY)["cost"]

    def test_the_subscription_one_says_it_costs_nothing_per_pull_request(self, tmp_path, gh):
        assert "no per-pull-request" in ga.set_credential(
            tmp_path, "subscription", GOOD_TOKEN)["cost"]


class TestClearing:
    def test_removing_the_last_one_warns_the_gates_will_fail_closed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ga.subprocess, "run", FakeGh(secrets=[ga.API_KEY_SECRET]))
        result = ga.clear_credential(tmp_path, "api-key")
        assert result["gates_can_sign_in"] is False
        assert "fail closed" in result["message"]

    def test_removing_one_of_two_says_the_gates_still_work(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ga.subprocess, "run",
                            FakeGh(secrets=[ga.API_KEY_SECRET, ga.SUBSCRIPTION_SECRET]))
        result = ga.clear_credential(tmp_path, "api-key")
        assert result["gates_can_sign_in"] is True


class TestTheSecretNamesMatchTheShippedPipelines:
    """The script and the pipelines are one decision. A rename in either alone is a gate that
    cannot sign in, discovered on somebody's pull request."""

    def _pipelines(self):
        root = Path(__file__).resolve().parents[2] / "harness"
        return list((root / "workflows").glob("*.yml")) + \
            list((root / "packs" / "cicd" / "github" / "workflows").glob("*.yml"))

    def test_every_gate_that_reads_a_key_also_accepts_a_subscription_token(self):
        for path in self._pipelines():
            text = path.read_text(encoding="utf-8")
            if "anthropic_api_key:" in text:
                assert "claude_code_oauth_token:" in text, (
                    f"{path.name} accepts only the metered credential")

    def test_the_subscription_secret_IS_read_by_every_gate_that_calls_the_action(self):
        """The credential a gate signs in with must be one this script can write.

        Asserted for the subscription secret only, and the reason is recorded rather than
        assumed: the configuration this was matched against (microsoft-agentic-harness, which
        runs these gates successfully today) passes the subscription token and the built-in
        workflow token, and NO api_key input at all.
        """
        for path in self._pipelines():
            text = path.read_text(encoding="utf-8")
            if "anthropics/claude-code-action" not in text:
                continue
            assert f"secrets.{ga.SUBSCRIPTION_SECRET}" in text, path.name

    def test_the_API_KEY_MODE_CURRENTLY_HAS_NO_CONSUMER_and_that_is_recorded(self):
        """A known gap, pinned so it cannot be forgotten rather than silently tolerated.

        `gate_auth.py set api-key` writes a secret that no shipped pipeline reads, because the
        working configuration does not pass an api_key input and matching it exactly was worth
        more than the reasoning that said an extra empty input would be harmless. Until a
        pipeline reads it, choosing that mode sets a credential nothing signs in with — which
        is precisely the silent no-op this whole harness exists to make impossible.

        When the api_key input is added back and PROVEN on a real pull request, delete this
        test and assert the consumer instead. Do not delete it to make the suite quiet.
        """
        joined = "\n".join(p.read_text(encoding="utf-8") for p in self._pipelines())
        assert f"secrets.{ga.API_KEY_SECRET}" not in joined, (
            "a pipeline now reads the API key — replace this test with one asserting that, "
            "and remove the warning from gate_auth.py")


class TestACredentialNothingReads:
    """Setting a credential no gate consults is a silent no-op, so it is said out loud.

    The shipped gates pass only the subscription token, matching the configuration that
    demonstrably works. Choosing api-key today therefore sets a secret nothing signs in with —
    which would look exactly like success until a pull request proved otherwise.
    """

    def test_the_api_key_mode_warns_that_no_gate_reads_it(self, tmp_path, gh):
        result = ga.set_credential(tmp_path, "api-key", GOOD_KEY)
        assert result["ok"] is True          # it WAS set; the warning is about consumers
        assert "warning" in result
        assert ga.API_KEY_SECRET in result["warning"]

    def test_the_subscription_mode_does_not_warn(self, tmp_path, gh):
        # The control: a warning on the working path would be noise, and noise is how a real
        # warning stops being read.
        assert "warning" not in ga.set_credential(tmp_path, "subscription", GOOD_TOKEN)

    def test_an_unreadable_payload_never_invents_a_warning(self, monkeypatch):
        # Fail-safe in the quiet direction: this claims "nothing reads it" only when it could
        # actually look. Saying so without evidence would be the same sin in reverse.
        monkeypatch.setattr(ga.Path, "is_dir", lambda self: False)
        assert ga._any_pipeline_reads("ANYTHING") is True


# ---------------------------------------------------------------------------
# Azure DevOps (code-host providers, Wave 4) — additive; everything above is untouched
# ---------------------------------------------------------------------------

import io  # noqa: E402  (appended with the class below; the file above is byte-identical)
import sys  # noqa: E402

import ado_transport  # noqa: E402
import code_host  # noqa: E402
from tests.ado_fixtures import ADO_REMOTE, FakeAz  # noqa: E402

GROUP_VARIABLES = {  # the captured shape: a dict keyed by variable name → {isSecret, value}
    "5": {"CLAUDE_CODE_OAUTH_TOKEN": {"isSecret": True, "value": None}},
    "6": {"OTHER": {"isSecret": False, "value": "x"}},
}


def _variables_for(args):
    return GROUP_VARIABLES[args[args.index("--group-id") + 1]]


class TestOnAzureDevOps:
    """Azure Pipelines read their secrets from VARIABLE GROUPS, not repository secrets, so on
    Azure DevOps `status` reads the variables in the groups the pipelines reference and
    `set`/`clear` refuse with the exact manual az command (the value never on it — az prompts).
    `gh` is never called on this path, and `az` is never called by a refusal."""

    @pytest.fixture
    def ado(self, tmp_path, monkeypatch):
        ado_transport.clear_caches()
        monkeypatch.delenv(code_host.ENV_VAR, raising=False)
        monkeypatch.delenv(code_host.LEGACY_CODE_HOST_ENV, raising=False)

        def git_only(cmd, input=None, capture_output=True, text=True, check=False):
            if cmd[:2] == ["git", "-C"]:
                return subprocess.CompletedProcess(cmd, 0, ADO_REMOTE + "\n", "")
            raise AssertionError(f"gh must not be called on Azure DevOps: {cmd}")
        monkeypatch.setattr(ga.subprocess, "run", git_only)
        monkeypatch.setattr(code_host, "origin_url", lambda root: ADO_REMOTE)  # ado_transport's read
        pipelines = tmp_path / ".azuredevops" / "pipelines"
        pipelines.mkdir(parents=True)
        (pipelines / "grader.yml").write_text("variables:\n  - group: claude-gates\n", encoding="utf-8")
        # Self-contained answers (not the shared fixture files): this test is about WHICH groups are
        # read, so the group list is stated here beside the assertion that depends on it.
        fake = FakeAz(answers={
            "pipelines variable-group list": [{"id": 5, "name": "claude-gates", "variables": {}},
                                              {"id": 6, "name": "unrelated", "variables": {}}],
            "pipelines variable-group variable list": _variables_for,
        })
        monkeypatch.setattr(ado_transport, "az_json", fake)
        yield fake
        ado_transport.clear_caches()

    def test_status_reads_only_the_variable_groups_the_pipelines_reference(self, tmp_path, ado):
        result = ga.status(tmp_path)
        assert result["repo"] == "contoso/Claims/claims-api"
        assert result["configured"] == ["subscription"]
        assert result["gates_can_sign_in"] is True and result["checked"] is True
        assert result["variable_groups"] == ["claude-gates"]
        listed = [c[c.index("--group-id") + 1] for c in ado.calls if "--group-id" in c]
        assert listed == ["5"]            # `unrelated` (id 6) is not this project's business

    def test_groups_that_cannot_be_listed_read_unknown_not_no(self, tmp_path, monkeypatch, ado):
        monkeypatch.setattr(ado_transport, "az_json",
                            FakeAz(fail={"variable-group list": "Please run 'az login' to setup account."}))
        result = ga.status(tmp_path)
        assert result["gates_can_sign_in"] is None and result["checked"] is False
        assert result["configured"] == []
        assert "az login" in result["detail"]
        text = ga.format_status(result)
        assert "NOT checked" in text and "fail closed" not in text

    def test_set_refuses_with_the_manual_command_and_sends_nothing(self, tmp_path, ado):
        before = {p for p in tmp_path.rglob("*")}
        with pytest.raises(ga.GateAuthError) as e:
            ga.set_credential(tmp_path, "subscription", GOOD_TOKEN)
        assert e.value.kind == "unsupported_host"
        msg = str(e.value)
        assert ("az pipelines variable-group variable create --group-id <group-id> "
                "--name CLAUDE_CODE_OAUTH_TOKEN --secret true "
                "--org https://dev.azure.com/contoso --project Claims") in msg
        assert "claude-gates" in msg                 # names the group the pipelines reference
        assert "--value" not in msg and GOOD_TOKEN not in msg
        assert ado.calls == []                       # a refusal makes no az call at all
        assert {p for p in tmp_path.rglob("*")} == before

    def test_set_still_validates_the_shape_first_so_a_bad_paste_is_a_bad_paste(self, tmp_path, ado):
        with pytest.raises(ga.GateAuthError) as e:
            ga.set_credential(tmp_path, "api-key", "nonsense-zzzq7")
        assert e.value.kind == "bad_shape" and "zzzq7" not in str(e.value)

    def test_clear_refuses_with_the_delete_command(self, tmp_path, ado):
        with pytest.raises(ga.GateAuthError) as e:
            ga.clear_credential(tmp_path, "api-key")
        assert e.value.kind == "unsupported_host"
        assert "az pipelines variable-group variable delete --group-id <group-id> --name ANTHROPIC_API_KEY --yes" in str(e.value)
        assert ado.calls == []

    def _main(self, monkeypatch, capsys, argv, stdin=""):
        monkeypatch.setattr(code_host, "cli_state", lambda host, **k: ("available", "probed by a stub"))
        monkeypatch.setattr(sys, "argv", ["gate_auth.py", *argv])
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        rc = ga.main()
        return rc, capsys.readouterr()

    def test_main_set_exits_1_with_kind_and_host_block_and_never_echoes(self, tmp_path, monkeypatch, capsys, ado):
        rc, out = self._main(monkeypatch, capsys, ["--repo", str(tmp_path), "--json", "set", "subscription"], GOOD_TOKEN)
        assert rc == 1
        doc = json.loads(out.out)
        assert doc["ok"] is False and doc["refusal"]["kind"] == "unsupported_host"
        assert "variable create" in doc["refusal"]["message"]
        assert doc["host"] == {"name": "azure-devops", "source": "remote", "cli": "az",
                               "cli_state": "available", "detail": f"from origin {ADO_REMOTE}"}
        assert GOOD_TOKEN not in out.out and GOOD_TOKEN not in out.err

    def test_main_set_text_mode_prints_the_command_on_stderr_and_exits_1(self, tmp_path, monkeypatch, capsys, ado):
        rc, out = self._main(monkeypatch, capsys, ["--repo", str(tmp_path), "set", "subscription"], GOOD_TOKEN)
        assert rc == 1
        assert "Refused:" in out.err and "az pipelines variable-group variable create" in out.err
        assert GOOD_TOKEN not in out.err

    def test_main_status_json_carries_the_host_block_and_exits_0(self, tmp_path, monkeypatch, capsys, ado):
        rc, out = self._main(monkeypatch, capsys, ["--repo", str(tmp_path), "--json", "status"])
        assert rc == 0
        doc = json.loads(out.out)
        assert doc["configured"] == ["subscription"] and doc["checked"] is True
        assert doc["host"]["name"] == "azure-devops" and doc["host"]["cli"] == "az"

    def test_main_status_text_names_the_code_host(self, tmp_path, monkeypatch, capsys, ado):
        rc, out = self._main(monkeypatch, capsys, ["--repo", str(tmp_path), "status"])
        assert rc == 0
        assert "Repository: contoso/Claims/claims-api" in out.out
        assert "Code host: azure-devops (from remote)" in out.out

    def test_host_flag_forces_azure_devops_on_an_unrecognised_remote(self, tmp_path, monkeypatch, capsys, ado):
        # Both origin reads (this module's and ado_transport's) see a remote nobody can parse:
        # the flag still picks the host, and with no org to read from the answer is "unknown".
        unknown = "https://git.example.invalid/x/y.git"
        monkeypatch.setattr(ga, "_origin_url", lambda root: unknown)
        monkeypatch.setattr(code_host, "origin_url", lambda root: unknown)
        ado_transport.clear_caches()
        rc, out = self._main(monkeypatch, capsys, ["--repo", str(tmp_path), "--host", "azure-devops", "--json", "status"])
        doc = json.loads(out.out)
        assert rc == 0 and doc["host"]["source"] == "flag"
        assert doc["gates_can_sign_in"] is None and doc["checked"] is False
        assert code_host.CODE_HOST_FILE in doc["detail"]       # names the escape hatch
        assert ado.calls == []                                 # nothing was asked of az without a scope

    def test_the_github_path_still_uses_gh_and_never_az(self, tmp_path, monkeypatch):
        monkeypatch.delenv(code_host.ENV_VAR, raising=False)
        monkeypatch.delenv(code_host.LEGACY_CODE_HOST_ENV, raising=False)
        monkeypatch.setattr(ga.subprocess, "run", FakeGh(secrets=[ga.API_KEY_SECRET]))
        fake = FakeAz()
        monkeypatch.setattr(ado_transport, "az_json", fake)
        result = ga.status(tmp_path)
        assert result["configured"] == ["api-key"] and result["gates_can_sign_in"] is True
        assert "checked" not in result and "host" not in result    # GitHub's output shape is unchanged
        assert fake.calls == []

    @pytest.mark.parametrize("url", [
        "https://github.com/acme/widgets.git",
        "git@github.com:acme/widgets.git",
        ADO_REMOTE,
        "git@ssh.dev.azure.com:v3/contoso/Claims/claims-api",
        None,
    ])
    def test_the_detection_twin_agrees_with_code_host(self, tmp_path, monkeypatch, url):
        monkeypatch.delenv(code_host.ENV_VAR, raising=False)
        monkeypatch.delenv(code_host.LEGACY_CODE_HOST_ENV, raising=False)
        monkeypatch.setattr(code_host, "origin_url", lambda root: url)
        monkeypatch.setattr(ga, "_origin_url", lambda root: url)
        assert ga.detect_host(tmp_path) == code_host.detect_host(tmp_path)

    def test_the_detection_twin_honours_the_env_and_file_overrides(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ga, "_origin_url", lambda root: "https://github.com/acme/widgets.git")
        monkeypatch.setenv(code_host.ENV_VAR, "azure-devops")
        assert ga.detect_host(tmp_path).source == "env"
        monkeypatch.delenv(code_host.ENV_VAR)
        (tmp_path / ".sdlc").mkdir()
        (tmp_path / ".sdlc" / "code-host.yaml").write_text("host: azure-devops\n", encoding="utf-8")
        det = ga.detect_host(tmp_path)
        assert det.source == "file" and det.host == "azure-devops"
        assert det.remote.host == "github"           # the parsed remote is kept for the record
