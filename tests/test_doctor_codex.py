"""`doctor` says plainly when Codex has not been told to run the hooks: Codex then skips them, and `codex exec` gives no warning."""
import json

import pytest

from honestly import agents, support


@pytest.fixture
def codex_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    agents.guard("codex", "install", "/opt/venv/bin/honestly")
    return home / ".codex"


def _trust(codex_home, stop=True, pre=True):
    hooks_json = str(codex_home / "hooks.json")
    state = ""
    if stop:
        state += f'[hooks.state."{hooks_json}:stop:0:0"]\ntrusted_hash = "sha256:{agents.codex_hook_hash(json.load(open(hooks_json))["hooks"]["Stop"][0], "stop")}"\n\n'
    if pre:
        state += f'[hooks.state."{hooks_json}:pre_tool_use:0:0"]\ntrusted_hash = "sha256:{agents.codex_hook_hash(json.load(open(hooks_json))["hooks"]["PreToolUse"][0], "pre_tool_use")}"\n\n'
    (codex_home / "config.toml").write_text('model = "x"\n\n[hooks.state]\n\n' + state, encoding="utf-8")


def test_not_reviewed_says_so_and_what_to_do(codex_home):
    text, problems = support.doctor(zh=False, with_problems=True)
    assert "NOT trusted" in text and "codex exec" in text
    assert any("Trust all" in p for p in problems)


def test_only_one_hook_trusted_is_not_trusted(codex_home):
    _trust(codex_home, pre=False)
    assert agents.codex_trust()[0] == "untrusted"


def test_reviewed_is_ok(codex_home):
    _trust(codex_home)
    text, problems = support.doctor(zh=False, with_problems=True)
    assert "NOT trusted" not in text and "trusted" in text
    assert not any("Trust all" in p for p in problems)


def test_changed_since_it_was_reviewed_says_so(codex_home):
    _trust(codex_home)
    agents.guard("codex", "install", "/another/venv/bin/honestly")
    assert agents.codex_trust()[0] == "changed"
    assert "changed" in support.doctor(zh=False)


def test_codex_home_moves_it(tmp_path, monkeypatch, codex_home):
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(other))
    assert agents.config_path("codex") == str(other / "hooks.json")
    agents.guard("codex", "install", "/opt/venv/bin/honestly")
    assert (other / "hooks.json").exists() and agents.codex_trust()[0] == "untrusted"


def test_a_codex_only_user_is_not_told_to_install_for_claude_code(codex_home):
    text, problems = support.doctor(zh=False, with_problems=True)
    assert "FAIL guard hooks not installed" not in text
    assert "run: honestly guard install" not in problems


def test_nobody_installed_is_still_a_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    text, problems = support.doctor(zh=False, with_problems=True)
    assert "guard hooks not installed" in text and "run: honestly guard install" in problems
