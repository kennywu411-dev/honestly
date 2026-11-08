import pytest
from honestly import hooks


@pytest.fixture(autouse=True)
def _isolated_catch_log(tmp_path, monkeypatch):
    """Hooks under test must never write into the developer's real ~/.honestly/catches.jsonl."""
    monkeypatch.setattr(hooks, "catches_path", lambda: str(tmp_path / "catches.jsonl"))
    monkeypatch.setattr(hooks, "errors_path", lambda: str(tmp_path / "hook-errors.log"))


@pytest.fixture(autouse=True)
def _english_system(monkeypatch):
    """Messages follow the system language; pin it to English so results do not depend on the developer's machine."""
    for var in ("LC_ALL", "LC_MESSAGES"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setattr(hooks, "_SYSTEM_ZH", None)
