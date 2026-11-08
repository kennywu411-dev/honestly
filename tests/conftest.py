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
