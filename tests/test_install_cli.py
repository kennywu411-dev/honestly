"""Install, upgrade, uninstall and the CLI: what a new user meets in the first ten minutes."""
import json
import os
import stat
import subprocess
import sys

import pytest

from honestly import agents, hookline, hooks

posix_only = pytest.mark.skipif(os.name == "nt", reason="runs a POSIX shell")


def _script(path, body='#!/bin/sh\necho ran "$@"\n'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


# ---------------------------------------------------------------- the hook line
@posix_only
@pytest.mark.parametrize("folder", ["p(1)", "it's", 'q"t', "tick`t", "a&b", "semi;c", "d$x", "$(touch marker)", "a b", "我的 项目", "`touch marker`"])
def test_the_hook_line_runs_from_any_install_path(tmp_path, monkeypatch, folder):
    exe = _script(tmp_path / folder / "bin" / "honestly")
    monkeypatch.setattr(sys, "argv", [str(exe)])
    lines = [hooks._entries()["PreToolUse"]["hooks"][0]["command"],
             agents.entries("codex", hooks._exe())["PreToolUse"][0]["hooks"][0]["command"],
             agents.entries("cursor", hooks._exe())["beforeShellExecution"][0]["command"]]
    for line in lines:
        r = subprocess.run(["/bin/sh", "-c", line], capture_output=True, text=True, cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        assert "ran hook pre" in r.stdout
        assert hookline.parse_line(line).exe == str(exe)
    assert not (tmp_path / "marker").exists()   # a command in the install path never runs


OURS = ["/venv/bin/honestly hook stop  # honestly hook", "/venv/bin/honestly hook pre  # honestly hook", "honestly hook stop", "honestly hook pre  # honestly hook",
        '"/a b/honestly" hook stop  # honestly hook', "'/a b/honestly' hook pre  # honestly hook", "/venv/bin/sober hook stop  # sober hook", "sober hook pre  # sober hook",
        "/bin/honestly hook stop --agent codex  # honestly hook", "C:/x/honestly.exe hook pre  # honestly hook", '"C:/a b/honestly.exe" hook stop', "C:\\x\\honestly.exe hook stop",
        "'/py thon/python' -m honestly hook pre  # honestly hook", "/venv/bin/python -m honestly.cli hook stop", "/tmp/p(1)/bin/honestly hook pre  # honestly hook",
        "/tmp/it's/bin/honestly hook pre  # honestly hook", "'/tmp/it'\"'\"'s/bin/honestly' hook pre  # honestly hook", "/wrapper hook pre  # honestly hook"]
NOT_OURS = ["echo 'honestly hook ran' >> log", "/usr/local/bin/sober hook-runner --daily", "my-keep-this", "notify honestly hook", "honestly hook stop && rm -rf /", "honestly doctor",
            "honestly hook stop; curl evil", "sh -c 'honestly hook stop'", "/x/mytool hook stop", "grep 'sober hook' file  # honestly hook", "honestly hook pre | tee log", ""]


@pytest.mark.parametrize("line", OURS)
def test_every_form_we_ever_wrote_is_recognised(line):
    assert hooks._ours({"type": "command", "command": line})
    assert agents._is_ours({"type": "command", "command": line})


@pytest.mark.parametrize("line", NOT_OURS)
def test_a_command_that_only_mentions_the_words_is_not_ours(line):
    assert not hooks._ours({"type": "command", "command": line})
    assert not agents._is_ours({"type": "command", "command": line})


@pytest.mark.parametrize("hook", [{"command": None}, {"command": 5}, {"command": ["honestly", "hook", "stop"]}, {"type": "prompt", "prompt": "x"}, {}, "str", None, 5])
def test_an_odd_hook_shape_is_simply_not_ours(hook):
    assert not hookline.is_ours(hook)
    assert not hooks._ours(hook) if isinstance(hook, dict) else True


def test_the_exec_form_is_recognised_exactly():
    assert hookline.is_ours({"command": "C:/a b/honestly.exe", "args": ["hook", "pre"]})
    assert hookline.is_ours({"command": "C:/a b/honestly.exe", "args": ["hook", "stop", "--agent", "codex"]})
    assert hookline.is_ours({"command": "C:/a b/python.exe", "args": ["-m", "honestly", "hook", "stop"]})
    assert not hookline.is_ours({"command": "C:/a b/honestly.exe", "args": ["doctor"]})
    assert not hookline.is_ours({"command": "C:/a b/other.exe", "args": ["hook", "pre"]})


def test_a_long_odd_command_cannot_slow_the_match():
    import time
    t = time.time()
    assert not hookline.is_ours({"command": "'\"" * 5000 + " nothing"})
    assert time.time() - t < 1


# ---------------------------------------------------------------- which executable goes in the hook
def test_uvx_and_pipx_run_are_refused_because_their_folder_goes_away(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "settings_path", lambda: str(tmp_path / "settings.json"))
    for temp in ["/home/me/.cache/uv/archive-v0/AbC123/bin/honestly", "/x/uvc/archive-v0/dOij/bin/honestly", "/x/uv/environments-v2/abc/bin/honestly",
                 "/home/me/.local/pipx/.cache/84f983193965836/bin/honestly", r"C:\Users\me\AppData\Local\uv\cache\archive-v0\xyz\Scripts\honestly.exe"]:
        monkeypatch.setattr(sys, "argv", [temp])
        with pytest.raises(SystemExit) as e:
            hooks.guard("install")
        assert "temporary" in str(e.value) and "uv tool install honestly" in str(e.value)
        assert not (tmp_path / "settings.json").exists()
        assert "would write" in hooks.guard("install", dry_run=True)   # looking is still fine
    for lasting in ["/home/me/.local/bin/honestly", "/home/me/.local/share/uv/tools/honestly/bin/honestly", "/home/me/.local/pipx/venvs/honestly/bin/honestly", "/x/.venv/bin/honestly"]:
        assert not hooks._temporary_install(lasting)


def test_a_symlink_with_another_name_writes_the_real_program(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("symlinks")
    real = _script(tmp_path / "venv" / "bin" / "honestly")
    link = tmp_path / "hon"
    link.symlink_to(real)
    monkeypatch.setattr(sys, "argv", [str(link)])
    assert hooks._exe() == str(real.resolve())


def test_python_dash_m_writes_a_line_that_runs_the_module(tmp_path, monkeypatch):
    import honestly
    pkg = os.path.dirname(honestly.__file__)
    monkeypatch.setattr(hooks, "_importable_without_path", lambda python: True)
    monkeypatch.setattr(sys, "argv", [os.path.join(pkg, "__main__.py")])
    assert hooks._exe().endswith(" -m honestly") and sys.executable in hooks._exe()
    monkeypatch.setattr(sys, "argv", [os.path.join(pkg, "cli.py")])
    line = hooks._entries()["Stop"]["hooks"][0]["command"]
    assert " -m honestly hook stop" in line and hooks._ours({"command": line})


def test_python_dash_m_honestly_works():
    env = dict(os.environ, PYTHONPATH=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
    r = subprocess.run([sys.executable, "-m", "honestly", "--version"], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "honestly" in r.stdout


def test_no_command_on_path_refuses_instead_of_writing_a_dead_line(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "settings_path", lambda: str(tmp_path / "settings.json"))
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "hooks" / "run.py")])   # the plugin's own entry point
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(SystemExit) as e:
        hooks.guard("install")
    assert "pipx install honestly" in str(e.value) and "plugin" in str(e.value)
    assert not (tmp_path / "settings.json").exists()


# ---------------------------------------------------------------- Windows forms (string level, not run on Windows)
def test_windows_launcher_argv_gets_its_exe_back(monkeypatch):
    # pip's launcher does sys.argv[0] = re.sub(r'(-script\.pyw|\.exe)?$', '', sys.argv[0]), so the real file name is gone by the time we look
    monkeypatch.setattr(sys, "argv", [r"C:\Users\Jo\.venv\Scripts\honestly"])
    assert hooks._exe() == "C:/Users/Jo/.venv/Scripts/honestly.exe"


def test_windows_path_with_a_space_uses_the_exec_form_and_never_blocks(monkeypatch):
    monkeypatch.setattr(sys, "argv", [r"C:\Users\Jo Smith\Scripts\honestly.exe"])
    h = hooks._entries()["PreToolUse"]["hooks"][0]
    assert h["command"] == "C:/Users/Jo Smith/Scripts/honestly.exe" and h["args"] == ["hook", "pre"]
    assert h["onFailure"] == "continue" and hooks._ours(h)
    assert hooks._entries()["Stop"]["hooks"][0]["args"] == ["hook", "stop"]


def test_windows_path_without_a_space_stays_one_line_that_both_shells_read(monkeypatch):
    monkeypatch.setattr(sys, "argv", [r"C:\Users\Jo\Scripts\honestly.exe"])
    h = hooks._entries()["PreToolUse"]["hooks"][0]
    assert h["command"].startswith("C:/Users/Jo/Scripts/honestly.exe hook pre") and "args" not in h and h["onFailure"] == "continue"


def test_windows_unc_path_has_no_backslashes_left(monkeypatch):
    monkeypatch.setattr(sys, "argv", [r"\\srv\share\Scripts\honestly.exe"])
    assert hooks._exe() == "//srv/share/Scripts/honestly.exe"


def test_windows_agent_line_cannot_carry_a_shell_expansion(tmp_path, monkeypatch):
    monkeypatch.setattr(agents, "config_path", lambda agent: str(tmp_path / f"{agent}.json"))
    monkeypatch.setattr(sys, "argv", [r"C:\a $(x)\honestly.exe"])
    with pytest.raises(SystemExit):
        hooks.guard("install", agent="codex")


# ---------------------------------------------------------------- editing the user's settings file
ALL_AGENTS = ["claude-code", "codex", "cursor", "gemini"]
GROUPED_AGENTS = ["claude-code", "codex", "gemini"]
EVENT = {"claude-code": "Stop", "codex": "Stop", "gemini": "AfterAgent", "cursor": "stop"}


@pytest.fixture
def where(tmp_path, monkeypatch):
    """Point every assistant's settings file into tmp_path; returns agent -> path."""
    paths = {"claude-code": tmp_path / "claude" / "settings.json", "codex": tmp_path / "codex" / "hooks.json",
             "cursor": tmp_path / "cursor" / "hooks.json", "gemini": tmp_path / "gemini" / "settings.json"}
    monkeypatch.setattr(hooks, "settings_path", lambda: str(paths["claude-code"]))
    monkeypatch.setattr(agents, "config_path", lambda agent: str(paths[agent]))
    return paths


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))


def _backups(path):
    return sorted(p for p in path.parent.iterdir() if ".bak-honestly-" in p.name)


def _no_temp_left(path):
    assert not [p for p in path.parent.iterdir() if p.name.startswith(".honestly-")]


ORIGINALS = [
    '{\n    "zeta": 1,\n    "exp": 1e3,\n    "esc": "caf\\u00e9",\n    "dup": 1, "dup": 2,\n    "arr": [1, 2],\n    "alpha": {"b": 1, "a": 2}\n}\n',
    '{"model":"x"}\n',
    '{"model":"x"}',
    '{"a": 1, "b": 2}\n',
    '{\r\n  "model": "x",\r\n  "hooks": {\r\n    "Other": [\r\n      {\r\n        "hooks": [ { "type": "command", "command": "mine" } ]\r\n      }\r\n    ]\r\n  }\r\n}\r\n',
    '﻿{\n\t"model": "x"\n}\n',
    '{\n  "hooks": {"Notification": [{"hooks": [{"type": "command", "command": "n"}]}], "Bar": []}\n}\n',
    '{\n  "hooks": {\n    "Other": [{"matcher":"x","hooks":[{"type":"command","command":"a"}]},\n              {"hooks":[{"type":"command","command":"b"}]}]\n  },\n  "z": null\n}\n',
    '{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mine"}]}], "AfterAgent": [{"hooks": [{"type": "command", "command": "mine"}]}]}, "z": [1, 2.50, true]}\n',
]


@pytest.mark.parametrize("agent", GROUPED_AGENTS)
@pytest.mark.parametrize("original", ORIGINALS)
def test_install_then_uninstall_gives_back_the_same_bytes(where, agent, original):
    path = where[agent]
    _write(path, original)
    hooks.guard("install", agent=agent)
    after = path.read_bytes().decode("utf-8")
    assert hookline.MARK in after
    json.loads(after.lstrip("﻿"))
    hooks.guard("uninstall", agent=agent)
    assert path.read_bytes().decode("utf-8") == original
    _no_temp_left(path)


def test_only_the_hooks_change_when_installing(where):
    path = where["claude-code"]
    _write(path, ORIGINALS[0])
    hooks.guard("install")
    text = path.read_text(encoding="utf-8")
    for kept in ('"exp": 1e3', '"esc": "caf\\u00e9"', '"dup": 1, "dup": 2', '"arr": [1, 2]', '"alpha": {"b": 1, "a": 2}', '\n    "zeta": 1'):
        assert kept in text   # no reformatting, no re-encoding
    assert list(json.loads(text)) == ["zeta", "exp", "esc", "dup", "arr", "alpha", "hooks"]


def test_a_user_hook_in_an_event_we_use_keeps_its_exact_text(where):
    path = where["claude-code"]
    mine = '{"hooks":[{"type":"command","command":"mine"   }]}'
    _write(path, '{\n  "hooks": {\n    "Stop": [\n      ' + mine + '\n    ]\n  }\n}\n')
    hooks.guard("install")
    assert mine in path.read_text(encoding="utf-8")
    hooks.guard("uninstall")
    assert mine in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("agent", GROUPED_AGENTS)
@pytest.mark.parametrize("action", ["install", "uninstall"])
def test_a_user_hook_sharing_a_group_with_ours_stays(where, agent, action):
    path = where[agent]
    ev = EVENT[agent]
    _write(path, json.dumps({"hooks": {ev: [{"matcher": "x", "hooks": [{"type": "command", "command": "my-keep-this"},
                                                                       {"type": "command", "command": "/old/honestly hook stop  # honestly hook"}]}]}}, indent=2))
    hooks.guard(action, agent=agent)
    cfg = json.loads(path.read_text(encoding="utf-8"))
    group = next(g for g in cfg["hooks"][ev] if any(h["command"] == "my-keep-this" for h in g["hooks"]))
    assert group["matcher"] == "x" and [h["command"] for h in group["hooks"]] == ["my-keep-this"]
    assert sum("/old/honestly" in h["command"] for g in cfg["hooks"][ev] for h in g["hooks"]) == 0


@pytest.mark.parametrize("agent", ALL_AGENTS)
def test_uninstall_leaves_what_only_mentions_the_words_and_shapes_it_does_not_know(where, agent):
    path = where[agent]
    theirs = "echo 'honestly hook ran' >> log"
    hook = {"type": "command", "command": theirs}
    group = hook if agent == "cursor" else {"hooks": [hook]}
    original = json.dumps({"hooks": {"Foo": {"a": 1}, "Bar": [], "Baz": "s", "Qux": [group, 1, "x", None], EVENT[agent]: [group]}, "z": 1}, indent=2) + "\n"
    _write(path, original)
    message = hooks.guard("uninstall", agent=agent)
    assert "not installed" in message and "nothing to remove" in message
    assert path.read_text(encoding="utf-8") == original and not _backups(path)


@pytest.mark.parametrize("agent", GROUPED_AGENTS)
def test_install_keeps_entries_it_cannot_read_in_a_list(where, agent):
    path = where[agent]
    ev = EVENT[agent]
    _write(path, json.dumps({"hooks": {ev: [1, "x", None, {"hooks": "s"}, {"hooks": [2]}]}}))
    hooks.guard("install", agent=agent)
    assert json.loads(path.read_text(encoding="utf-8"))["hooks"][ev][:5] == [1, "x", None, {"hooks": "s"}, {"hooks": [2]}]


@pytest.mark.parametrize("agent", ALL_AGENTS)
@pytest.mark.parametrize("bad", ['{"hooks": [1, 2]}', '{"hooks": "x"}', '{"hooks": {"EVENT": "x"}}', '{"hooks": {"EVENT": {"a": 1}}}'])
def test_install_refuses_a_shape_it_would_have_to_overwrite(where, agent, bad):
    path = where[agent]
    text = bad.replace("EVENT", EVENT[agent])
    _write(path, text)
    with pytest.raises(SystemExit) as e:
        hooks.guard("install", agent=agent)
    assert e.value.code not in (0, None) and str(path) in str(e.value)
    assert path.read_text(encoding="utf-8") == text and not _backups(path)


@pytest.mark.parametrize("agent", ALL_AGENTS)
@pytest.mark.parametrize("bad", ['// comment\n{"a": 1}\n', '{"a": 1,}\n', "{not json", "[1, 2]\n", "null\n", '"x"\n', b'{"a": "\xff"}\n'])
@pytest.mark.parametrize("action", ["install", "uninstall"])
def test_a_file_it_cannot_read_stops_with_an_error_and_is_left_alone(where, agent, bad, action):
    path = where[agent]
    _write(path, bad)
    before = path.read_bytes()
    with pytest.raises(SystemExit) as e:
        hooks.guard(action, agent=agent)
    assert e.value.code not in (0, None)   # a string: Python prints it and exits 1
    assert path.read_bytes() == before and not _backups(path)
    status = hooks.guard("status", agent=agent)
    assert "cannot read" in status or "not a JSON object" in status


@pytest.mark.parametrize("agent", ALL_AGENTS)
@pytest.mark.parametrize("empty", ["", "  \n", '{"hooks": null}'])
def test_an_empty_file_and_null_hooks_are_room_to_write(where, agent, empty):
    path = where[agent]
    _write(path, empty)
    hooks.guard("install", agent=agent)
    assert EVENT[agent] in json.loads(path.read_text(encoding="utf-8"))["hooks"]


@pytest.mark.parametrize("agent", ALL_AGENTS)
def test_installing_again_changes_nothing_and_makes_no_backup(where, agent):
    path = where[agent]
    _write(path, '{"keep": 1}\n')
    hooks.guard("install", agent=agent)
    first = path.read_bytes()
    n = len(_backups(path))
    for _ in range(2):
        assert "already installed" in hooks.guard("install", agent=agent)
    assert path.read_bytes() == first and len(_backups(path)) == n


def test_an_upgrade_replaces_our_entry_where_it_is(where):
    path = where["claude-code"]
    old = {"matcher": "", "hooks": [{"type": "command", "command": "/old/sober hook stop  # sober hook", "timeout": 30}]}
    mine = {"hooks": [{"type": "command", "command": "mine"}]}
    _write(path, json.dumps({"hooks": {"Stop": [old, mine], "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "sober hook pre  # sober hook"}]}]}}, indent=2))
    hooks.guard("install")
    cfg = json.loads(path.read_text(encoding="utf-8"))["hooks"]
    assert [g["hooks"][0]["command"] for g in cfg["Stop"]] == [hooks._entries()["Stop"]["hooks"][0]["command"], "mine"]
    assert cfg["PreToolUse"][0]["matcher"] == "Bash|PowerShell" and len(cfg["PreToolUse"]) == 1


@pytest.mark.parametrize("agent", ALL_AGENTS)
def test_uninstall_with_nothing_installed_creates_nothing(where, agent):
    assert "nothing to remove" in hooks.guard("uninstall", agent=agent)
    assert not where[agent].exists() and not where[agent].parent.exists()


@pytest.mark.parametrize("agent", ALL_AGENTS)
def test_a_file_that_only_held_our_hooks_goes_away_on_uninstall(where, agent):
    path = where[agent]
    hooks.guard("install", agent=agent)
    assert "uninstalled" in hooks.guard("uninstall", agent=agent)
    assert not path.exists() and not _backups(path)


@posix_only
def test_a_symlinked_settings_file_stays_a_symlink_after_uninstall(where, tmp_path):
    real = tmp_path / "dotfiles" / "s.json"
    _write(real, "{}\n")
    path = where["claude-code"]
    path.parent.mkdir()
    path.symlink_to(real)
    hooks.guard("install")
    assert path.is_symlink() and "hooks" in json.loads(real.read_text())
    hooks.guard("uninstall")
    assert path.is_symlink() and json.loads(real.read_text()) == {}


def test_backups_are_byte_exact_and_do_not_pile_up(where):
    path = where["claude-code"]
    original = '{ "first":   "version" }\n'
    _write(path, original)
    hooks.guard("install")
    assert _backups(path)[0].read_text() == original
    for _ in range(12):
        hooks.guard("uninstall")
        hooks.guard("install")
    baks = _backups(path)
    assert len(baks) <= 5
    assert baks[0].read_text() == original   # the one from before honestly was ever there is kept


def test_dry_run_writes_nothing_for_every_agent(where):
    for agent in ALL_AGENTS:
        _write(where[agent], '{"keep": 1}\n')
        out = hooks.guard("install", agent=agent, dry_run=True)
        assert "would write" in out and json.loads(out[out.index("{"):])["hooks"]
        assert where[agent].read_text() == '{"keep": 1}\n' and not _backups(where[agent])


def test_install_all_reports_every_agent_and_fails_when_one_failed(where):
    _write(where["gemini"], "// comment\n{}\n")
    with pytest.raises(SystemExit) as e:
        hooks.guard("install", agent="all")
    assert "cannot read" in str(e.value) and "Claude Code" not in str(e.value) or "installed" in str(e.value)
    assert where["codex"].exists() and where["claude-code"].exists() and where["cursor"].exists()


# ---------------------------------------------------------------- when writing fails
@posix_only
def test_a_read_only_file_is_refused_not_replaced(where):
    if os.geteuid() == 0:
        pytest.skip("root ignores file modes")
    path = where["claude-code"]
    _write(path, '{"model": "x"}\n')
    path.chmod(0o444)
    with pytest.raises(SystemExit) as e:
        hooks.guard("install")
    assert "read-only" in str(e.value) and str(path) in str(e.value)
    assert path.read_text() == '{"model": "x"}\n' and not _backups(path)


@posix_only
@pytest.mark.parametrize("agent", ALL_AGENTS)
def test_a_read_only_folder_gives_one_clear_line(where, agent):
    if os.geteuid() == 0:
        pytest.skip("root ignores file modes")
    path = where[agent]
    _write(path, '{"model": "x"}\n')
    path.parent.chmod(0o555)
    try:
        with pytest.raises(SystemExit) as e:
            hooks.guard("install", agent=agent)
    finally:
        path.parent.chmod(0o755)
    assert "cannot write" in str(e.value) and path.read_text() == '{"model": "x"}\n' and not _backups(path)


def test_a_file_where_the_folder_should_be_gives_one_clear_line(where):
    _write(where["claude-code"].parent.with_name("x"), "")
    where["claude-code"].parent.write_text("a file")
    with pytest.raises(SystemExit) as e:
        hooks.guard("install")
    assert "cannot write" in str(e.value)


def test_a_failed_write_leaves_the_file_and_no_empty_backup(where, monkeypatch):
    from honestly import config
    path = where["claude-code"]
    _write(path, '{"model": "x"}\n')
    def full(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(config.os, "replace", full)
    with pytest.raises(SystemExit) as e:
        hooks.guard("install")
    assert "No space left" in str(e.value)
    assert path.read_text() == '{"model": "x"}\n' and not _backups(path)
    _no_temp_left(path)


def test_another_program_writing_the_file_is_not_overwritten(where, monkeypatch):
    from honestly import config
    path = where["claude-code"]
    _write(path, '{"n": 0}\n')
    real = config.write_text_atomic
    calls = []
    def race(*a, **k):
        if not calls:
            calls.append(1)
            path.write_text('{"n": 1}\n')   # after honestly read the file, before its copy is moved in
        return real(*a, **k)
    monkeypatch.setattr(config, "write_text_atomic", race)
    hooks.guard("install")
    cfg = json.loads(path.read_text())
    assert cfg["n"] == 1 and "hooks" in cfg


# ---------------------------------------------------------------- status and the overview never crash
@pytest.mark.parametrize("agent", ALL_AGENTS)
@pytest.mark.parametrize("text", ["[]", "null", '"x"', "{}", '{"hooks": 5}', '{"hooks": {"Stop": 5}}', '{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": null}]}]}}',
                                  '{"hooks": {"stop": [{"command": 5}], "AfterAgent": [{"hooks": [{"command": ["x"]}]}]}}'])
def test_status_and_overview_survive_any_shape(where, agent, text, capsys):
    from honestly import cli
    _write(where[agent], text)
    assert hooks.guard("status", agent="all")
    assert isinstance(agents.installed("codex"), list)
    cli.main([])
    assert "honestly" in capsys.readouterr().out


def test_status_says_when_the_command_behind_the_entry_is_gone(where):
    _write(where["claude-code"], json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/gone/honestly hook stop  # honestly hook"}]}]}}))
    status = hooks.guard("status")
    assert "installed for Stop" in status and "/gone/honestly" in status and "guard install" in status
