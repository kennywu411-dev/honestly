import pytest
from honestly import hooks


@pytest.fixture(autouse=True)
def _isolated_catch_log(tmp_path, monkeypatch):
    """Hooks under test must never write into the developer's real ~/.honestly/catches.jsonl."""
    monkeypatch.setattr(hooks, "catches_path", lambda: str(tmp_path / "catches.jsonl"))
