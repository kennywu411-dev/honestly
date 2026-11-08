import sys

import pytest
from honestly import config, hooks, report


@pytest.fixture(autouse=True)
def _isolated_catch_log(tmp_path, monkeypatch):
    """Hooks under test must never write into the developer's real ~/.honestly/catches.jsonl."""
    monkeypatch.setattr(hooks, "catches_path", lambda: str(tmp_path / "catches.jsonl"))
    monkeypatch.setattr(hooks, "errors_path", lambda: str(tmp_path / "hook-errors.log"))
    monkeypatch.setattr(config, "trust_path", lambda: str(tmp_path / "trusted.json"))
    monkeypatch.setattr(config, "notices_path", lambda: str(tmp_path / "notices.json"))


@pytest.fixture(autouse=True)
def _rule_tables_back_to_defaults():
    """A test that applies a config (an ignore phrase, a category switched off) must not change what the next test judges."""
    yield
    config.apply(config.DEFAULTS)


@pytest.fixture(autouse=True)
def _claude_folder_follows_home(monkeypatch):
    """Tests move HOME; a CLAUDE_CONFIG_DIR from the developer's shell would keep pointing at the real sessions."""
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)


@pytest.fixture(autouse=True)
def _running_as_the_installed_command(monkeypatch):
    """`guard install` writes the path of the running program; under pytest that is pytest, so stand in for the installed command."""
    monkeypatch.setattr(sys, "argv", ["/test/venv/bin/honestly"])


@pytest.fixture(autouse=True)
def _no_real_browser(monkeypatch):
    """A headless Chrome under a temporary HOME asks macOS for a keychain and shows the user a popup. No test may start one."""
    def nothing(cmd, **kw):
        raise FileNotFoundError(cmd[0])
    monkeypatch.setattr(report, "_run", nothing)


@pytest.fixture(autouse=True)
def _english_system(monkeypatch):
    """Messages follow the system language; pin it to English so results do not depend on the developer's machine."""
    for var in ("LC_ALL", "LC_MESSAGES"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setattr(hooks, "_SYSTEM_ZH", None)


MAX_TEST_ID = 4000


def pytest_collection_modifyitems(items):
    """pytest puts each test's id in an environment variable, and Windows refuses a value over 32767 characters: the test then errors, on every system
    but Windows it passes, and the report of it can cut the run's output short. So a parameter that big needs a name of its own, here too."""
    long = [item.nodeid[:80] for item in items if len(item.nodeid) > MAX_TEST_ID]
    if long:
        raise pytest.UsageError(f"test ids over {MAX_TEST_ID} characters break on Windows, give these a short id: {long}")
