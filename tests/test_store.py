"""What honestly keeps on disk: private, scrubbed before it is written, bounded in size, and removable with one command."""
import builtins
import io
import json
import os
import stat
import sys

import pytest

from honestly import cache, cli, config, hooks, report, store, update
from honestly.audit import Finding

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes and symlinks")
TOKEN = "gh" + "p_" + "Ab1Cd2Ef3Gh4" * 3


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    d = h / ".honestly"
    monkeypatch.setattr(hooks, "catches_path", lambda: str(d / "catches.jsonl"))
    monkeypatch.setattr(hooks, "errors_path", lambda: str(d / "hook-errors.log"))
    monkeypatch.setattr(config, "trust_path", lambda: str(d / "trusted.json"))
    monkeypatch.setattr(config, "notices_path", lambda: str(d / "notices.json"))
    return d


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def _catch(**kw):
    turn = type("T", (), {"prompt": kw.pop("prompt", "fix it"), "agent": "claude-code", "model": "m", "session": "s", "index": 0, "project": ""})()
    hooks._record(kw.pop("kind", "stop"), {"cwd": kw.pop("cwd", "/work/p")}, turn, kw.pop("plain", "held"), **kw)


@posix_only
def test_the_folder_and_every_file_are_private(home, tmp_path):
    _catch(claim="All tests pass.")
    hooks._note("stop", "a note")
    hooks.set_notify(True)
    hooks._notify_due()
    cache.put(_a_session(tmp_path), "", [_finding()])
    assert mode(home) == 0o700
    for name in ("catches.jsonl", "hook-errors.log", "notify", "notify.last"):
        assert mode(home / name) == 0o600, name
    assert mode(home / "cache") == 0o700
    for name in os.listdir(home / "cache"):
        assert mode(home / "cache" / name) == 0o600


def _a_session(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text("{}\n")
    return str(p)


def _finding(**kw):
    base = dict(session="s", turn=0, version="", agent="a", model="m", ts="t", category="tests_pass", verdict="unbacked", reason="r", claim="c", last_edit="", tools_after_edit=[], context="")
    base.update(kw)
    return Finding(**base)


@posix_only
def test_an_install_from_before_is_tightened(home):
    home.mkdir(mode=0o755)
    (home / "catches.jsonl").write_text("{}\n")
    os.chmod(home / "catches.jsonl", 0o644)
    (home / "cache").mkdir()
    (home / "cache" / "x.json").write_text("[]")
    os.chmod(home / "cache" / "x.json", 0o644)
    store.tighten()
    assert mode(home) == 0o700 and mode(home / "catches.jsonl") == 0o600 and mode(home / "cache" / "x.json") == 0o600


@posix_only
def test_a_card_is_private_too(home):
    report._run = lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError())
    written = report.write_catches_card([], 7, str(home))
    assert mode(written[0]) == 0o600 and mode(home) == 0o700


@posix_only
def test_the_update_cache_is_private(home, monkeypatch):
    monkeypatch.setattr(update, "_fetch_latest", lambda timeout=2.0: "9.9.9")
    monkeypatch.delenv("HONESTLY_NO_UPDATE_CHECK", raising=False)
    update.latest_version(now=1.0)
    assert mode(home / "update-check.json") == 0o600


def test_catches_are_scrubbed_before_they_are_written(home):
    prompt = f"use {TOKEN} and tell alice@acme.example"
    _catch(prompt=prompt, cwd=os.path.join(os.environ["HOME"], "client-acme"), claim=f"Pushed with {TOKEN}.", reason=f"errored: {TOKEN}",
           plain=f'blocked: said "{TOKEN}"', command=f"X={TOKEN} pytest | head", tools=[f"Bash: curl -H 'Authorization: Bearer {TOKEN}' https://x"])
    raw = (home / "catches.jsonl").read_text(encoding="utf-8")
    assert TOKEN not in raw and "alice@acme.example" not in raw and os.environ["HOME"] not in raw
    row = json.loads(raw)
    assert row["project"] == "~/client-acme" and hooks._short(row["project"]) == "client-acme"
    assert row["claim"].startswith("Pushed with")


def test_the_report_still_works_from_scrubbed_rows(home):
    _catch(cwd=os.path.join(os.environ["HOME"], "client-acme"), claim="All tests pass.", plain="held")
    assert "client-acme" in hooks.catches_report(7, zh=False)


def test_the_error_log_is_scrubbed(home):
    hooks._note("stop", f"could not read {TOKEN}\x1b[2J")
    raw = (home / "hook-errors.log").read_text(encoding="utf-8")
    assert TOKEN not in raw and "\x1b" not in raw


def test_a_crash_is_logged_scrubbed(home, monkeypatch):
    def boom(*a, **k):
        raise ValueError(f"bad {TOKEN}")
    monkeypatch.setattr(hooks, "stop_hook", boom)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert hooks.run_hook("stop") == 0
    raw = (home / "hook-errors.log").read_text(encoding="utf-8")
    assert "ValueError" in raw and TOKEN not in raw


def test_the_cache_is_scrubbed_and_still_serves(home, tmp_path):
    session = _a_session(tmp_path)
    cache.put(session, "", [_finding(claim=f"used {TOKEN}", context=f"ctx {TOKEN}", tools_after_edit=[f"Bash: X={TOKEN} ls"], output=f"out {TOKEN}", last_edit=f"Edit: {TOKEN}")])
    names = os.listdir(home / "cache")
    assert len(names) == 1 and names[0].endswith(".json")
    assert TOKEN not in (home / "cache" / names[0]).read_text(encoding="utf-8")
    hit = cache.get(session, "")
    assert hit and hit[0].verdict == "unbacked"


def test_logs_rotate_and_old_catches_still_count(home, monkeypatch):
    monkeypatch.setattr(store, "MAX_LOG_BYTES", 600)
    for i in range(30):
        _catch(claim=f"All tests pass {i}.")
    assert (home / "catches.jsonl.1").exists()
    assert os.path.getsize(home / "catches.jsonl") <= 600 + 1000
    assert not (home / "catches.jsonl.2").exists()
    rows = hooks.load_catches()
    assert rows and rows[-1]["claim"] == "All tests pass 29."
    assert len(rows) >= 2


def test_the_error_log_rotates_too(home, monkeypatch):
    monkeypatch.setattr(store, "MAX_LOG_BYTES", 200)
    for i in range(30):
        hooks._note("stop", f"note {i}")
    assert (home / "hook-errors.log.1").exists()
    assert os.path.getsize(home / "hook-errors.log") <= 200 + 100


@posix_only
def test_a_planted_symlink_is_not_written_through(home, tmp_path):
    home.mkdir()
    victim = tmp_path / "victim"
    victim.write_text("KEEP\n")
    os.symlink(victim, home / "catches.jsonl")
    os.symlink(victim, home / "hook-errors.log")
    _catch(claim="All tests pass.")
    hooks._note("stop", "x")
    assert victim.read_text() == "KEEP\n"


@posix_only
def test_the_notify_stamp_does_not_truncate_through_a_symlink(home, tmp_path):
    home.mkdir()
    victim = tmp_path / "victim"
    victim.write_text("KEEP\n")
    os.symlink(victim, hooks.notify_flag_path() + ".last")
    hooks._notify_due()
    assert victim.read_text() == "KEEP\n"


@posix_only
def test_a_card_is_not_written_through_a_symlink(home, tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("KEEP\n")
    out = tmp_path / "out"
    out.mkdir()
    os.symlink(victim, out / "honestly-catches.svg")
    report._run = lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError())
    with pytest.raises(OSError):
        report.write_catches_card([], 7, str(out))
    assert victim.read_text() == "KEEP\n"


def _populate(home):
    (home / "cache").mkdir(parents=True)
    for name in ("catches.jsonl", "catches.jsonl.1", "hook-errors.log", "hook-errors.log.1", "update-check.json", "notices.json", "notify.last", "honestly-card.svg", "honestly-catches.png", "config.json", "trusted.json", "notify"):
        (home / name).write_text("{}\n")
    (home / "cache" / "x.json").write_text("[]")


def test_purge_removes_what_was_recorded_and_keeps_the_settings(home):
    _populate(home)
    removed = store.purge()
    assert sorted(os.listdir(home)) == ["config.json", "notify", "trusted.json"]
    assert str(home / "catches.jsonl") in removed


def test_purge_all_removes_everything(home):
    _populate(home)
    store.purge(everything=True)
    assert not home.exists()


def test_a_dry_run_removes_nothing(home):
    _populate(home)
    planned = store.purge(dry_run=True)
    assert str(home / "catches.jsonl") in planned and (home / "catches.jsonl").exists()


@posix_only
def test_purge_removes_a_link_and_not_what_it_points_at(home, tmp_path):
    home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.json").write_text("KEEP")
    os.symlink(outside, home / "cache")
    os.symlink(outside / "x.json", home / "catches.jsonl")
    store.purge()
    assert (outside / "x.json").read_text() == "KEEP"
    assert not os.path.lexists(home / "cache") and not os.path.lexists(home / "catches.jsonl")


class _Tty(io.StringIO):
    def isatty(self):
        return True


def test_the_command_needs_a_terminal_and_a_yes(home, monkeypatch, capsys):
    _populate(home)
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    with pytest.raises(SystemExit):
        cli.main(["purge"])
    assert (home / "catches.jsonl").exists()
    cli.main(["purge", "--dry-run"])
    assert "catches.jsonl" in capsys.readouterr().out and (home / "catches.jsonl").exists()
    monkeypatch.setattr(sys, "stdin", _Tty())
    monkeypatch.setattr(builtins, "input", lambda *a: "no")
    cli.main(["purge"])
    assert (home / "catches.jsonl").exists()
    monkeypatch.setattr(builtins, "input", lambda *a: "yes")
    cli.main(["purge"])
    assert not (home / "catches.jsonl").exists() and (home / "config.json").exists()


def test_writing_does_not_fail_when_the_folder_cannot_be_made(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(hooks, "catches_path", lambda: str(blocker / "catches.jsonl"))
    monkeypatch.setattr(hooks, "errors_path", lambda: str(blocker / "e.log"))
    _catch(claim="All tests pass.")
    hooks._note("stop", "x")
