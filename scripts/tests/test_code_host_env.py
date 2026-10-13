"""Tests for the two-name code-host variable (Shepherd brand update, D5).

`SHEPHERD_CODE_HOST` is the name from 2.0 on; `SDLC_CODE_HOST` is the name already sitting in
people's shells and CI, so it is still read — after the new one. Three facts are pinned here and
nowhere else: the new name wins when both are set, the old name alone still works, and neither
set leaves detection exactly where it was. `detail` names whichever variable actually supplied
the value, so a reader is never told SHEPHERD_CODE_HOST chose a host that SDLC_CODE_HOST chose.
The gate_auth twin is checked under both names. Nothing here spawns gh or az.
"""

import pytest

import code_host as ch
import gate_auth as ga

GH = "https://github.com/acme/widgets.git"


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    for name in ch.CODE_HOST_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(ch, "origin_url", lambda root: GH)
    monkeypatch.setattr(ga, "_origin_url", lambda root: GH)


def test_the_two_names_and_the_order_they_are_read_in():
    assert ch.CODE_HOST_ENV == "SHEPHERD_CODE_HOST"
    assert ch.LEGACY_CODE_HOST_ENV == "SDLC_CODE_HOST"
    assert ch.CODE_HOST_ENV_VARS == (ch.CODE_HOST_ENV, ch.LEGACY_CODE_HOST_ENV)
    # The alias every existing caller and test imports labels the `env` source with the new name.
    assert ch.ENV_VAR == ch.CODE_HOST_ENV


class TestCodeHostEnv:
    def test_new_name_wins_over_old(self, monkeypatch):
        monkeypatch.setenv(ch.CODE_HOST_ENV, "azure-devops")
        monkeypatch.setenv(ch.LEGACY_CODE_HOST_ENV, "github")
        assert ch.code_host_env() == (ch.CODE_HOST_ENV, "azure-devops")

    def test_old_name_alone_is_still_read(self, monkeypatch):
        monkeypatch.setenv(ch.LEGACY_CODE_HOST_ENV, "azure-devops")
        assert ch.code_host_env() == (ch.LEGACY_CODE_HOST_ENV, "azure-devops")

    def test_neither_set_is_no_value_under_the_new_name(self):
        assert ch.code_host_env() == (ch.CODE_HOST_ENV, None)

    def test_an_empty_new_name_does_not_shadow_the_old_one(self, monkeypatch):
        monkeypatch.setenv(ch.CODE_HOST_ENV, "")
        monkeypatch.setenv(ch.LEGACY_CODE_HOST_ENV, "azure-devops")
        assert ch.code_host_env() == (ch.LEGACY_CODE_HOST_ENV, "azure-devops")

    def test_takes_an_injected_mapping(self):
        assert ch.code_host_env({"SDLC_CODE_HOST": "none"}) == ("SDLC_CODE_HOST", "none")
        assert ch.code_host_env({}) == (ch.CODE_HOST_ENV, None)


class TestDetectHost:
    def test_new_name_wins_and_detail_names_it(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ch.CODE_HOST_ENV, "azure-devops")
        monkeypatch.setenv(ch.LEGACY_CODE_HOST_ENV, "none")
        det = ch.detect_host(tmp_path)
        assert (det.host, det.source) == ("azure-devops", "env")
        assert det.detail == "SHEPHERD_CODE_HOST=azure-devops"

    def test_old_name_alone_still_overrides_and_detail_names_it(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ch.LEGACY_CODE_HOST_ENV, "azure-devops")
        det = ch.detect_host(tmp_path)
        assert (det.host, det.source) == ("azure-devops", "env")
        assert det.detail == "SDLC_CODE_HOST=azure-devops"

    def test_neither_set_falls_to_the_remote(self, tmp_path):
        det = ch.detect_host(tmp_path)
        assert (det.host, det.source) == ("github", "remote")
        assert "CODE_HOST" not in det.detail

    def test_an_unrecognised_new_value_is_ignored_not_rescued_by_the_old_one(self, tmp_path, monkeypatch):
        # "First set value" means exactly that: a bad SHEPHERD_CODE_HOST is named and skipped, and
        # detection moves on to the file and the remote — it does not quietly read the old name.
        monkeypatch.setenv(ch.CODE_HOST_ENV, "gitlab")
        monkeypatch.setenv(ch.LEGACY_CODE_HOST_ENV, "azure-devops")
        det = ch.detect_host(tmp_path)
        assert (det.host, det.source) == ("github", "remote")
        assert "SHEPHERD_CODE_HOST='gitlab' ignored" in det.detail

    @pytest.mark.parametrize("name", [ch.CODE_HOST_ENV, ch.LEGACY_CODE_HOST_ENV])
    def test_the_gate_auth_twin_agrees_under_either_name(self, tmp_path, monkeypatch, name):
        monkeypatch.setenv(name, "azure-devops")
        assert ga.detect_host(tmp_path) == ch.detect_host(tmp_path)
        assert ga.detect_host(tmp_path).detail == f"{name}=azure-devops"
