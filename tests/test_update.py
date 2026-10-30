"""The once-a-day "newer version" note: cached, quiet on failure, off by env var, never from the hooks."""
import json, os
from honestly import update


def _iso(tmp_path, monkeypatch, latest="9.9.9", fail=False):
    monkeypatch.setattr(update, "cache_path", lambda: str(tmp_path / "update-check.json"))
    calls = []
    def fetch(timeout=2.0):
        calls.append(1)
        if fail:
            raise OSError("offline")
        return latest
    monkeypatch.setattr(update, "_fetch_latest", fetch)
    monkeypatch.delenv("HONESTLY_NO_UPDATE_CHECK", raising=False)
    return calls


def test_note_when_newer_and_silent_when_current(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch, latest="0.5.0")
    assert "0.5.0" in update.update_note("0.4.2") and "pip install -U honestly" in update.update_note("0.4.2")
    assert "有新版 0.5.0" in update.update_note("0.4.2", zh=True)
    assert update.update_note("0.5.0") == ""
    assert update.update_note("0.10.0") == ""   # numeric, not string, comparison


def test_cache_is_used_for_a_day(tmp_path, monkeypatch):
    calls = _iso(tmp_path, monkeypatch, latest="0.5.0")
    update.update_note("0.4.2"); update.update_note("0.4.2")
    assert len(calls) == 1
    c = json.load(open(tmp_path / "update-check.json"))
    c["ts"] -= update.CACHE_TTL + 1
    json.dump(c, open(tmp_path / "update-check.json", "w"))
    update.update_note("0.4.2")
    assert len(calls) == 2


def test_offline_and_opt_out_are_silent(tmp_path, monkeypatch):
    _iso(tmp_path, monkeypatch, fail=True)
    assert update.update_note("0.1.0") == ""
    calls = _iso(tmp_path, monkeypatch, latest="0.5.0")
    monkeypatch.setenv("HONESTLY_NO_UPDATE_CHECK", "1")
    assert update.update_note("0.1.0") == "" and calls == []


def test_hooks_do_not_import_the_update_check():
    import honestly.hooks as h
    src = open(h.__file__, encoding="utf-8").read()
    assert "update_note" not in src and "urllib" not in src
