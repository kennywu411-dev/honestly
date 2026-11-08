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


# ---------------------------------------------------------------- the plugin and the pip guard: exactly one acts
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = os.path.join(ROOT, "hooks", "run.py")
PIPED = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "pytest | head"}, "session_id": "s", "cwd": "/tmp"})


def _stop_event(tmp_path):
    t = tmp_path / "t.jsonl"
    rows = [{"type": "user", "message": {"role": "user", "content": "fix"}, "origin": {"kind": "human"}, "cwd": "/w", "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "assistant", "message": {"role": "assistant", "model": "m", "content": [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/w/src/a.py", "old_string": "a", "new_string": "b"}}]}, "cwd": "/w", "timestamp": "2026-01-01T00:00:01Z"},
            {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}, "cwd": "/w", "timestamp": "2026-01-01T00:00:02Z"},
            {"type": "assistant", "message": {"role": "assistant", "model": "m", "content": [{"type": "text", "text": "Fixed. All tests pass."}]}, "cwd": "/w", "timestamp": "2026-01-01T00:00:03Z"}]
    t.write_text("\n".join(map(json.dumps, rows)) + "\n")
    return json.dumps({"transcript_path": str(t), "cwd": "/w", "session_id": "s", "last_assistant_message": "Fixed. All tests pass."})


def _plugin_acts(tmp_path, which, settings=None):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    if settings is not None:
        (home / ".claude" / "settings.json").write_text(json.dumps(settings))
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), HONESTLY_NO_UPDATE_CHECK="1")
    r = subprocess.run([sys.executable, RUN, "hook", which], input=PIPED if which == "pre" else _stop_event(tmp_path), capture_output=True, text=True, encoding="utf-8", env=env)
    assert r.returncode == 0 and not r.stderr
    return bool(r.stdout.strip())


def _pip_settings(exe, events=("Stop", "PreToolUse")):
    which = {"Stop": "stop", "PreToolUse": "pre"}
    return {"hooks": {ev: [{"hooks": [{"type": "command", "command": f"{hookline.shell_word(str(exe))} hook {which[ev]}  # honestly hook"}]}] for ev in events}}


@posix_only
def test_a_working_pip_guard_means_the_plugin_steps_aside_for_both_events(tmp_path):
    exe = _script(tmp_path / "bin" / "honestly")
    assert not _plugin_acts(tmp_path, "stop", _pip_settings(exe))
    assert not _plugin_acts(tmp_path, "pre", _pip_settings(exe))


@posix_only
def test_the_plugin_covers_the_event_the_pip_guard_does_not_have(tmp_path):
    exe = _script(tmp_path / "bin" / "honestly")
    assert _plugin_acts(tmp_path, "stop", _pip_settings(exe, ["PreToolUse"]))
    assert not _plugin_acts(tmp_path, "pre", _pip_settings(exe, ["PreToolUse"]))
    assert _plugin_acts(tmp_path, "pre", _pip_settings(exe, ["Stop"]))
    assert not _plugin_acts(tmp_path, "stop", _pip_settings(exe, ["Stop"]))


@posix_only
@pytest.mark.parametrize("body", ["#!/gone/python3.12\nimport honestly\n", "#!/bin/sh\n'''exec' \"/gone/my python\" \"$0\" \"$@\"\n' '''\nimport honestly\n"])
def test_a_script_whose_python_went_away_does_not_count_as_working(tmp_path, body):
    exe = _script(tmp_path / "bin" / "honestly", body)
    assert _plugin_acts(tmp_path, "pre", _pip_settings(exe))
    assert _plugin_acts(tmp_path, "stop", _pip_settings(exe))


@posix_only
def test_a_file_that_is_not_executable_does_not_count_as_working(tmp_path):
    exe = tmp_path / "bin" / "honestly"
    exe.parent.mkdir()
    exe.write_text("x")
    exe.chmod(0o644)
    assert _plugin_acts(tmp_path, "pre", _pip_settings(exe))


@posix_only
def test_the_trampoline_pip_writes_for_a_long_path_counts_when_its_python_is_there(tmp_path):
    exe = _script(tmp_path / "bin" / "honestly", f"#!/bin/sh\n'''exec' \"{sys.executable}\" \"$0\" \"$@\"\n' '''\nimport honestly\n")
    assert not _plugin_acts(tmp_path, "pre", _pip_settings(exe))


@posix_only
def test_a_dead_or_foreign_line_leaves_the_plugin_in_charge(tmp_path):
    assert _plugin_acts(tmp_path, "pre", _pip_settings("/gone/honestly"))
    assert _plugin_acts(tmp_path, "pre", {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "echo 'honestly hook pre'"}]}]}})
    assert _plugin_acts(tmp_path, "pre")


def test_exec_form_entries_count_as_a_pip_guard(tmp_path):
    exe = _script(tmp_path / "bin" / "honestly") if os.name != "nt" else tmp_path
    settings = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": str(exe), "args": ["hook", "pre"]}]}]}}
    if os.name != "nt":
        assert not _plugin_acts(tmp_path, "pre", settings)


def test_windows_runnable_finds_the_launcher_behind_a_stripped_name(tmp_path, monkeypatch):
    # not run on Windows: pip's launcher strips .exe, so older entries name the file without it
    (tmp_path / "honestly.exe").write_text("x")
    monkeypatch.setattr(hookline.os, "name", "nt")
    assert hookline.runnable(str(tmp_path / "honestly"))
    assert not hookline.runnable(str(tmp_path / "other"))


def test_the_plugin_hook_can_never_block_a_command_when_it_fails():
    # docs: on Windows without Git Bash a failing shell-form PreToolUse hook blocks the call unless onFailure says otherwise
    with open(os.path.join(ROOT, "hooks", "hooks.json"), encoding="utf-8") as fh:
        plugin = json.load(fh)["hooks"]
    h = plugin["PreToolUse"][0]["hooks"][0]
    assert h["onFailure"] == "continue"


@pytest.mark.parametrize("skill", ["catches", "pr-note"])
def test_the_skills_work_where_only_python_exists(skill):
    with open(os.path.join(ROOT, "skills", skill, "SKILL.md"), encoding="utf-8") as fh:
        text = fh.read()
    assert 'Bash(python "${CLAUDE_PLUGIN_ROOT}/hooks/run.py"' in text and "Bash(python3 " in text


# ---------------------------------------------------------------- config files
@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """A temp home with the user config at home/.honestly/config.json, cwd at tmp_path/work."""
    home = tmp_path / "home"
    home.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(work)
    return home / ".honestly" / "config.json"


@pytest.mark.parametrize("edit", [lambda c: c.add_to("ignore", "newphrase"), lambda c: c.remove_from("ignore", "a"), lambda c: c.set_value("strictness", "strict"), lambda c: c.add_to("off", "fixed")])
@pytest.mark.parametrize("broken", ['{\n "strictness": "strict",\n "ignore": ["a", "b"],\n}\n', "[1]\n", b"\xff\xfe", "null"])
def test_a_config_it_cannot_read_is_never_overwritten(cfg, edit, broken):
    from honestly import config
    _write(cfg, broken)
    before = cfg.read_bytes()
    with pytest.raises(SystemExit) as e:
        edit(config)
    assert str(cfg) in str(e.value) and "nothing was changed" in str(e.value).lower()
    assert cfg.read_bytes() == before


def test_a_broken_config_is_reported_by_show(cfg):
    from honestly import config
    _write(cfg, '{"ignore": ["a"],}')
    assert str(cfg) in config.show() and "not valid JSON" in config.show()
    assert config.problems(None)


def test_editing_keeps_the_other_keys_and_a_list_written_as_one_string(cfg):
    from honestly import config
    _write(cfg, '{"ignore": "fixed bed", "strictness": "strict"}')
    config.add_to("ignore", "foo")
    d = json.loads(cfg.read_text())
    assert d == {"ignore": ["fixed bed", "foo"], "strictness": "strict"}
    _write(cfg, '{"ignore": "fixed bed"}')
    assert "already in" in config.add_to("ignore", "fixed bed")
    config.remove_from("ignore", "fixed bed")
    assert json.loads(cfg.read_text())["ignore"] == []


@pytest.mark.parametrize("shape", ['{"ignore": 5}', '{"verify_commands": null}', '{"off": {"a": 1}}', '{"ignore": [1, null, {"a": 1}]}'])
def test_editing_a_list_of_the_wrong_shape_does_not_crash(cfg, shape):
    from honestly import config
    for key in ("ignore", "verify_commands", "off"):
        _write(cfg, shape)
        assert "added" in config.add_to(key, "make check")
        assert "make check" in json.loads(cfg.read_text())[key]


@pytest.mark.parametrize("phrase", ["e", " ", "x "])
def test_a_one_letter_phrase_would_silence_everything_and_is_refused(cfg, phrase):
    from honestly import config
    with pytest.raises(SystemExit):
        config.add_to("ignore", phrase)
    with pytest.raises(SystemExit):
        config.add_to("verify_commands", phrase)
    assert not cfg.exists()


def test_one_letter_entries_already_in_a_file_are_not_applied(cfg):
    from honestly import config
    _write(cfg, '{"ignore": ["f", "i", "e", "foo"], "verify_commands": ["x", "make smoke"], "off": ["fixed"]}')
    loaded = config.load()
    assert loaded["ignore"] == ["foo"] and loaded["verify_commands"] == ["make smoke"] and loaded["off"] == ["fixed"]


@pytest.mark.parametrize("text", ['{"strictness": ["x"]}', '{"strictness": {}}', '{"language": {}}', '{"language": []}', '{"off": null, "ignore": null, "verify_commands": null}',
                                  '{"ignore": 5}', '{"verify_commands": [1, null, {"a": 1}]}', '{"strictness": 5, "language": 5}'])
def test_a_value_of_the_wrong_type_never_turns_the_guard_off(cfg, text):
    from honestly import config
    _write(cfg, text)
    loaded = config.load()
    assert loaded["strictness"] == "normal" and loaded["language"] == "auto"
    assert all(isinstance(x, str) and x != "None" for k in ("ignore", "verify_commands", "off") for x in loaded[k])
    assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "pytest | head -5"}, "cwd": "/tmp"})["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert config.show()


def _repo(tmp_path):
    root = tmp_path / "repo"
    (root / "src" / "deep").mkdir(parents=True)
    (root / ".git").mkdir()
    return root


def test_the_project_file_is_found_from_any_folder_of_the_repository(tmp_path):
    from honestly import config
    root = _repo(tmp_path)
    (root / ".honestly.json").write_text('{"strictness": "lenient"}')
    for cwd in (root, root / "src", root / "src" / "deep"):
        assert config.project_path(str(cwd)) == str(root / ".honestly.json")
        assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "pytest | head -5"}, "cwd": str(cwd)}) is None   # lenient applies everywhere


def test_the_nearest_project_file_wins_and_the_search_stops_at_the_repository(tmp_path):
    from honestly import config
    root = _repo(tmp_path)
    (root / "src" / ".honestly.json").write_text("{}")
    assert config.project_path(str(root / "src" / "deep")) == str(root / "src" / ".honestly.json")
    (tmp_path / ".honestly.json").write_text('{"strictness": "lenient"}')   # above the repository: not this project's
    (root / "src" / ".honestly.json").unlink()
    assert config.project_path(str(root / "src")) == str(root / ".honestly.json")


def test_outside_a_repository_only_the_folder_itself_counts(tmp_path):
    from honestly import config
    (tmp_path / ".honestly.json").write_text('{"strictness": "lenient"}')
    (tmp_path / "sub").mkdir()
    assert config.project_path(str(tmp_path / "sub")) == str(tmp_path / "sub" / ".honestly.json")


def test_a_project_setting_written_from_a_subfolder_goes_to_the_repository_root(tmp_path, monkeypatch):
    from honestly import config
    root = _repo(tmp_path)
    monkeypatch.chdir(root / "src")
    config.add_to("ignore", "fixed bed", project=True)
    assert json.loads((root / ".honestly.json").read_text())["ignore"] == ["fixed bed"]


def test_a_deleted_current_folder_does_not_stop_config(cfg, monkeypatch):
    from honestly import config
    def gone():
        raise FileNotFoundError(2, "No such file or directory")
    monkeypatch.setattr(os, "getcwd", gone)
    assert config.show() and config.load()["strictness"] == "normal"


@posix_only
def test_a_project_file_that_is_a_symlink_is_never_written_through(tmp_path, monkeypatch):
    from honestly import config
    victim = tmp_path / "zshrc"
    victim.write_text("export KEEP=1\n")
    work = tmp_path / "work"
    work.mkdir()
    (work / ".honestly.json").symlink_to(victim)
    monkeypatch.chdir(work)
    for edit in (lambda: config.add_to("ignore", "foo", project=True), lambda: config.set_value("strictness", "lenient", project=True), lambda: config.remove_from("ignore", "foo", project=True)):
        with pytest.raises(SystemExit) as e:
            edit()
        assert "symbolic link" in str(e.value)
    assert victim.read_text() == "export KEEP=1\n" and (work / ".honestly.json").is_symlink()


@posix_only
def test_a_new_project_file_has_ordinary_permissions(tmp_path, monkeypatch):
    from honestly import config
    monkeypatch.chdir(tmp_path)
    old = os.umask(0o022)
    try:
        config.add_to("ignore", "foo", project=True)
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / ".honestly.json").stat().st_mode) == 0o644


@pytest.mark.parametrize("edit", [lambda c: c.add_to("ignore", "foo"), lambda c: c.set_value("strictness", "strict")])
def test_a_config_folder_it_cannot_create_gives_one_clear_line(cfg, edit):
    from honestly import config
    cfg.parent.write_text("a file")
    with pytest.raises(SystemExit) as e:
        edit(config)
    assert "cannot write" in str(e.value)


# ---------------------------------------------------------------- doctor
def _doctor_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.setenv("HONESTLY_NO_UPDATE_CHECK", "1")
    monkeypatch.chdir(home)
    return home


def _doctor(zh=False):
    from honestly import support
    return support.doctor(zh=zh, with_problems=True)


def test_doctor_with_only_the_plugin_is_happy(tmp_path, monkeypatch):
    home = _doctor_home(tmp_path, monkeypatch)
    (home / ".claude" / "settings.json").write_text('{"enabledPlugins": {"honestly@honestly": true}}')
    text, problems = _doctor()
    assert not problems and "FAIL" not in text and "plugin" in text
    assert "plugin" in hooks.guard("status")
    assert "not installed" not in hooks.guard("status")


def test_a_disabled_plugin_does_not_count(tmp_path, monkeypatch):
    home = _doctor_home(tmp_path, monkeypatch)
    (home / ".claude" / "settings.json").write_text('{"enabledPlugins": {"honestly@honestly": false}}')
    _, problems = _doctor()
    assert problems


def test_doctor_with_only_another_assistant_is_happy(tmp_path, monkeypatch):
    home = _doctor_home(tmp_path, monkeypatch)
    exe = _script(tmp_path / "bin" / "honestly")
    monkeypatch.setattr(sys, "argv", [str(exe)])
    hooks.guard("install", agent="codex")
    text, problems = _doctor()
    assert not problems and "FAIL" not in text and "Codex" in text
    assert home


def test_doctor_with_nothing_installed_says_so(tmp_path, monkeypatch):
    _doctor_home(tmp_path, monkeypatch)
    text, problems = _doctor()
    assert "FAIL" in text and any("guard install" in p for p in problems)


@pytest.mark.parametrize("setup", [lambda c: c.set_value("strictness", "lenient"), lambda c: c.add_to("off", "tests_pass"), lambda c: c.add_to("off", "sent"), lambda c: c.add_to("ignore", "tests pass")])
def test_your_own_settings_do_not_fail_the_self_test(tmp_path, monkeypatch, setup):
    from honestly import config
    _doctor_home(tmp_path, monkeypatch)
    exe = _script(tmp_path / "bin" / "honestly")
    monkeypatch.setattr(sys, "argv", [str(exe)])
    hooks.guard("install")
    setup(config)
    text, problems = _doctor()
    assert not problems and "self-test (code)" in text and "NOT blocked" not in text
    assert config.load()   # the user's config is still in effect afterwards


def test_doctor_runs_the_line_of_every_assistant(tmp_path, monkeypatch):
    home = _doctor_home(tmp_path, monkeypatch)
    _write(home / ".codex" / "hooks.json", json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "/gone/honestly hook stop --agent codex  # honestly hook"}]}]}}))
    text, problems = _doctor()
    assert "/gone/honestly" in text and any("Codex" in p or "codex" in p for p in problems)


@posix_only
def test_doctor_reads_the_program_out_of_a_line_whatever_the_path(tmp_path, monkeypatch):
    _doctor_home(tmp_path, monkeypatch)
    exe = _script(tmp_path / "a hook b" / "honestly")
    monkeypatch.setattr(sys, "argv", [str(exe)])
    hooks.guard("install")
    text, problems = _doctor()
    assert not problems and f"hook command exists: {exe}" in text


def test_doctor_leaves_no_temporary_folder(tmp_path, monkeypatch):
    _doctor_home(tmp_path, monkeypatch)
    temp = tmp_path / "tmp"
    temp.mkdir()
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    from honestly import support
    assert support.self_test()
    assert not list(temp.iterdir())


@pytest.mark.parametrize("text", ["[]", "null"])
def test_doctor_reports_a_settings_file_that_is_not_an_object(tmp_path, monkeypatch, text):
    home = _doctor_home(tmp_path, monkeypatch)
    (home / ".claude" / "settings.json").write_text(text)
    out, problems = _doctor()
    assert "not a JSON object" in out and problems


def test_doctor_warns_about_a_config_it_is_ignoring(tmp_path, monkeypatch):
    home = _doctor_home(tmp_path, monkeypatch)
    _write(home / ".honestly" / "config.json", '{"a": 1,}')
    out, problems = _doctor()
    assert "not valid JSON" in out and problems


def test_doctor_reads_only_the_end_of_a_big_error_log(tmp_path, monkeypatch):
    home = _doctor_home(tmp_path, monkeypatch)
    log = tmp_path / "hook-errors.log"   # conftest points errors_path here
    with open(log, "w") as fh:
        fh.write("x" * 1000 + "\n")
        fh.write("2026-11-08T00:00:00 stop claude-code\nTraceback (most recent call last):\nValueError: y\n")
    out, _ = _doctor()
    assert "ValueError: y" in out
    assert home


def test_doctor_stream_encoding_is_read_before_it_is_changed():
    code = "import sys; from honestly import cli; sys.exit(cli.main(['doctor']))"
    env = dict(os.environ, PYTHONIOENCODING="ascii", PYTHONPATH=os.path.join(ROOT, "src"), HONESTLY_NO_UPDATE_CHECK="1")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, env=env)
    r.stdout.decode("ascii")   # the user asked for ascii and got it
    assert b"terminal encoding ascii" in r.stdout


# ---------------------------------------------------------------- the CLI: no traceback, honest exit codes
def _honestly(args, home, inp=b"", env=None, cwd=None):
    home.mkdir(parents=True, exist_ok=True)
    e = dict(os.environ, HOME=str(home), USERPROFILE=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), HONESTLY_NO_UPDATE_CHECK="1", PYTHONPATH=os.path.join(ROOT, "src"))
    e.update(env or {})
    return subprocess.run([sys.executable, "-m", "honestly", *args], input=inp, capture_output=True, env=e, cwd=cwd or str(home))


def _seed_session(home, n=3):
    p = home / ".claude" / "projects" / "-w" / "s.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(n):
        t = f"2026-11-0{1 + i % 7}T00:00:00Z"
        rows += [{"type": "user", "message": {"role": "user", "content": f"fix {i}"}, "origin": {"kind": "human"}, "cwd": "/w", "timestamp": t},
                 {"type": "assistant", "message": {"role": "assistant", "model": "m", "content": [{"type": "tool_use", "id": f"e{i}", "name": "Edit", "input": {"file_path": f"/w/src/a{i}.py", "old_string": "a", "new_string": "b"}}]}, "cwd": "/w", "timestamp": t},
                 {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"e{i}", "content": "ok"}]}, "cwd": "/w", "timestamp": t},
                 {"type": "assistant", "message": {"role": "assistant", "model": "m", "content": [{"type": "text", "text": f"Fixed bug {i}. All {i + 5} tests pass."}]}, "cwd": "/w", "timestamp": t}]
    p.write_text("\n".join(map(json.dumps, rows)) + "\n", encoding="utf-8")
    return p


CATCH = json.dumps({"ts": "2026-11-08T00:00:00+00:00", "kind": "stop", "agent": "claude-code", "model": "m", "project": "/p", "message": "m", "claim": "c", "reason": "r"})


@pytest.mark.parametrize("args,code", [
    (["audit", "--json", "/nonexistent/dir/x.jsonl"], 1), (["share", "--out", "/dev/null/x"], 1), (["catches", "--card", "--out", "/dev/null/x"], 1),
    (["sample", "/nonexistent.jsonl"], 1), (["sample", "/etc/hosts"], 1), (["sample", "/"], 1),
    (["audit", "--since", "9999999d"], 0), (["audit", "--since", "99999999999d"], 0),
    (["config", "strictness", "bogus"], 2), (["config", "strictness"], 2), (["config", "language", "xx"], 2), (["config", "off", "nonexistentcat"], 2),
    (["explain", "999"], 1), (["explain", "0"], 1), (["explain", "-1"], 1), (["feedback", "999"], 1), (["feedback", "-1"], 1), (["feedback", "0"], 1),
    (["catches", "--days", "0"], 2), (["catches", "--days", "-5"], 2), (["guard", "install", "on"], 2), (["guard", "status", "off"], 2),
])
def test_bad_input_gets_one_line_and_the_right_exit_code(tmp_path, args, code):
    home = tmp_path / "home"
    _seed_session(home)
    _write(home / ".honestly" / "catches.jsonl", CATCH + "\n")
    r = _honestly(args, home)
    assert r.returncode == code, r.stderr
    assert b"Traceback" not in r.stdout + r.stderr
    if code:
        assert r.stderr.strip()


def test_pr_note_with_a_path_or_a_number_it_cannot_use_gets_one_line(tmp_path):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    for args in (["pr-note", "--out", "/nonexistent/x/y.md"], ["pr-note", "--since", "99999999999d"]):
        r = _honestly(args, home, cwd=str(repo))
        assert r.returncode == 1 and b"Traceback" not in r.stderr and r.stderr.strip()


@posix_only
@pytest.mark.parametrize("args", [["doctor"], ["audit"], ["config"], ["ignore", "--list"], ["catches"], ["guard", "status"], []])
def test_a_deleted_current_folder_still_works_where_it_can(tmp_path, args):
    home = tmp_path / "home"
    gone = tmp_path / "gone"
    gone.mkdir()
    env = dict(os.environ, HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), HONESTLY_NO_UPDATE_CHECK="1", PYTHONPATH=os.path.join(ROOT, "src"))
    home.mkdir()
    r = subprocess.run(["/bin/sh", "-c", f"cd '{gone}' && rmdir '{gone}' && exec '{sys.executable}' -m honestly {' '.join(args)}"], capture_output=True, env=env)
    assert b"Traceback" not in r.stderr


@posix_only
@pytest.mark.parametrize("args", [["rule", "status"], ["pr-note"]])
def test_a_deleted_current_folder_is_explained_where_it_is_needed(tmp_path, args):
    home = tmp_path / "home"
    gone = tmp_path / "gone"
    gone.mkdir()
    env = dict(os.environ, HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), HONESTLY_NO_UPDATE_CHECK="1", PYTHONPATH=os.path.join(ROOT, "src"))
    home.mkdir()
    r = subprocess.run(["/bin/sh", "-c", f"cd '{gone}' && rmdir '{gone}' && exec '{sys.executable}' -m honestly {' '.join(args)}"], capture_output=True, env=env)
    assert r.returncode == 1 and b"Traceback" not in r.stderr and b"folder" in r.stderr


@pytest.mark.parametrize("args", [["ignore", "x"], ["config", "strictness", "strict"], ["guard", "notify", "on"]])
@pytest.mark.parametrize("kind", ["file", pytest.param("read-only", marks=posix_only)])
def test_a_honestly_folder_it_cannot_use_gets_one_line(tmp_path, args, kind):
    home = tmp_path / "home"
    home.mkdir()
    d = home / ".honestly"
    if kind == "file":
        d.write_text("x")
    else:
        d.mkdir()
        d.chmod(0o555)
    r = _honestly(args, home)
    if kind != "file":
        d.chmod(0o755)
    assert r.returncode == 1 and b"Traceback" not in r.stderr and b"honestly" in r.stderr


def test_an_unexpected_error_is_one_line_and_the_traceback_is_on_request(tmp_path, monkeypatch, capsys):
    from honestly import cli
    monkeypatch.setattr(cli, "_dispatch", lambda args: 1 / 0)
    assert cli.main(["config"]) == 1
    err = capsys.readouterr().err
    assert "ZeroDivisionError" in err and "Traceback" not in err and "HONESTLY_DEBUG" in err
    monkeypatch.setenv("HONESTLY_DEBUG", "1")
    assert cli.main(["config"]) == 1
    assert "Traceback" in capsys.readouterr().err


def _closed_stdout(args, home, inp=b""):
    home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), HONESTLY_NO_UPDATE_CHECK="1", PYTHONPATH=os.path.join(ROOT, "src"))
    r, w = os.pipe()
    os.close(r)
    try:
        return subprocess.run([sys.executable, "-m", "honestly", *args], input=inp, stdout=w, stderr=subprocess.PIPE, env=env, cwd=str(home))
    finally:
        os.close(w)


@posix_only
@pytest.mark.parametrize("args", [["--help"], ["doctor", "--help"], ["guard", "status"], ["catches"], ["config"], []])
def test_a_reader_that_went_away_is_not_an_error_message(tmp_path, args):
    r = _closed_stdout(args, tmp_path / "home")
    assert r.stderr == b"" and r.returncode == 141


@posix_only
def test_writing_many_lines_into_head_prints_no_traceback(tmp_path):
    home = tmp_path / "home"
    _seed_session(home, 400)
    env = dict(os.environ, HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), HONESTLY_NO_UPDATE_CHECK="1", PYTHONPATH=os.path.join(ROOT, "src"))
    r = subprocess.run(["/bin/bash", "-c", f"'{sys.executable}' -m honestly audit --json /dev/stdout | head -1 >/dev/null; echo rc=${{PIPESTATUS[0]}}"], capture_output=True, env=env)
    assert b"Traceback" not in r.stderr and b"BrokenPipe" not in r.stderr


@posix_only
@pytest.mark.parametrize("which", ["pre", "stop"])
def test_a_hook_whose_stdout_is_gone_still_exits_zero_and_says_nothing(tmp_path, which):
    event = PIPED if which == "pre" else _stop_event(tmp_path)
    r = _closed_stdout(["hook", which], tmp_path / "home", event.encode())
    assert r.returncode == 0 and r.stderr == b""


@pytest.mark.skipif(not os.path.exists("/dev/full"), reason="no /dev/full here")
def test_a_full_disk_on_stdout_is_exit_zero_for_a_hook(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path), PYTHONPATH=os.path.join(ROOT, "src"))
    with open("/dev/full", "w") as full:
        r = subprocess.run([sys.executable, "-m", "honestly", "hook", "pre"], input=PIPED.encode(), stdout=full, stderr=subprocess.PIPE, env=env)
    assert r.returncode == 0 and r.stderr == b""


@pytest.mark.parametrize("args", [["hook"], ["hook", "x"], ["hook", "pre", "--new-flag"], ["hook", "pre", "--agent", "nope"], ["hook", "stop", "extra"], ["hook", "--agent"]])
def test_a_hook_line_with_arguments_it_does_not_know_never_blocks(tmp_path, args):
    # exit 2 from a hook means "block": a downgrade or a hand edit must not stop every command
    r = _honestly(args, tmp_path / "home", b"{}")
    assert r.returncode == 0 and r.stdout == b""


def test_the_marker_comment_as_plain_words_still_runs_the_hook(tmp_path):
    # cmd.exe has no `#` comments, so a hook line reaches the program with the marker as arguments
    r = _honestly(["hook", "pre", "--agent", "codex", "#", "honestly", "hook"], tmp_path / "home", PIPED.encode())
    assert r.returncode == 0 and b"deny" in r.stdout
    r = _honestly(["hook", "--help"], tmp_path / "home")
    assert r.returncode == 0 and b"usage" in r.stdout


def test_help_documents_the_exit_codes(tmp_path):
    out = _honestly(["--help"], tmp_path / "home").stdout.decode()
    assert "exit codes" in out.lower() and "141" in out


def test_categories_are_listed_and_match_the_rules(tmp_path):
    from honestly import config, rules
    assert set(config.CATEGORIES) == {name for name, _, _ in rules.CLAIM_PATTERNS}
    home = tmp_path / "home"
    assert b"tests_pass" in _honestly(["config"], home).stdout
    r = _honestly(["config", "off", "nope"], home)
    assert b"tests_pass" in r.stderr and not (home / ".honestly" / "config.json").exists()
    assert _honestly(["config", "off", "sent,checked"], home).returncode == 0


def test_guard_notify_respects_dry_run_and_shows_its_state(tmp_path):
    home = tmp_path / "home"
    r = _honestly(["guard", "notify", "on", "--dry-run"], home)
    assert r.returncode == 0 and not (home / ".honestly" / "notify").exists()
    assert b"off" in _honestly(["guard", "notify"], home).stdout and not (home / ".honestly" / "notify").exists()
    _honestly(["guard", "notify", "on"], home)
    assert (home / ".honestly" / "notify").exists() and b"on" in _honestly(["guard", "notify"], home).stdout


def test_nothing_to_show_writes_no_card(tmp_path):
    home = tmp_path / "home"
    r = _honestly(["share"], home)
    assert r.returncode == 0 and b"nothing to" in r.stderr.lower() and not list((home / ".honestly").glob("*.svg"))
    r = _honestly(["catches", "--card"], home)
    assert r.returncode == 0 and not list((home / ".honestly").glob("*.svg"))


# ---------------------------------------------------------------- reading logs
def test_claude_config_dir_is_where_the_sessions_are(tmp_path):
    home = tmp_path / "home"
    alt = tmp_path / "alt"
    p = _seed_session(alt.parent / "x")   # build the session elsewhere and move it under the custom dir
    (alt / "projects" / "-w").mkdir(parents=True)
    os.replace(p, alt / "projects" / "-w" / "s.jsonl")
    env = {"CLAUDE_CONFIG_DIR": str(alt)}
    out = json.loads(_honestly(["audit", "--summary-json"], home, env=env).stdout)
    assert out["sessions"] == 1
    assert b"1 Claude Code session logs" in _honestly(["doctor"], home, env=env).stdout


def test_the_no_logs_message_names_the_folder_it_looked_in(tmp_path):
    alt = tmp_path / "alt"
    out = _honestly(["audit"], tmp_path / "home", env={"CLAUDE_CONFIG_DIR": str(alt)}).stdout.decode()
    assert str(alt) in out


def test_pr_note_finds_sessions_under_claude_config_dir(tmp_path, monkeypatch):
    from honestly import claude_code
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "alt"))
    assert claude_code.projects_root() == str(tmp_path / "alt" / "projects")
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert claude_code.projects_root() == os.path.join(str(tmp_path), ".claude", "projects")


def _make_dir(p):
    p.mkdir()


def _make_unreadable(p):
    p.write_text("{}\n")
    p.chmod(0)


def _make_dangling(p):
    p.symlink_to("/nonexistent/nothing")


@posix_only
@pytest.mark.parametrize("make", [_make_dir, _make_unreadable, _make_dangling])
def test_one_bad_session_log_does_not_stop_the_audit(tmp_path, make):
    home = tmp_path / "home"
    good = _seed_session(home)
    make(good.parent / "bad.jsonl")
    r = _honestly(["audit", "--summary-json"], home)
    assert r.returncode == 0 and b"Traceback" not in r.stderr
    assert json.loads(r.stdout)["sessions"] >= 1
    r = _honestly(["doctor"], home)
    assert b"Traceback" not in r.stderr


@posix_only
def test_an_unreadable_log_is_reported_not_hidden(tmp_path):
    home = tmp_path / "home"
    good = _seed_session(home)
    _make_unreadable(good.parent / "bad.jsonl")
    assert b"skipped" in _honestly(["audit"], home).stderr
    (good.parent / "bad.jsonl").chmod(0o644)


@posix_only
def test_a_dangling_subagent_file_costs_only_that_file(tmp_path):
    home = tmp_path / "home"
    good = _seed_session(home)
    (good.parent / "s" / "subagents").mkdir(parents=True)
    _make_dangling(good.parent / "s" / "subagents" / "agent-a.jsonl")
    r = _honestly(["audit", "--summary-json"], home)
    assert r.returncode == 0 and json.loads(r.stdout)["sessions"] == 1
    from honestly import claude_code
    assert claude_code.parse_session(str(good))   # the hook still reads the turn, not "could not be parsed"


def test_a_subagent_file_that_cannot_be_parsed_does_not_lose_the_parent(tmp_path, monkeypatch):
    from honestly import claude_code
    home = tmp_path / "home"
    good = _seed_session(home)
    sub = good.parent / "s" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-a.jsonl").write_text("{}\n")
    real = claude_code._parse
    def parse(path, *a, **k):
        if "agent-a" in str(path):
            raise PermissionError(13, "denied", str(path))
        return real(path, *a, **k)
    monkeypatch.setattr(claude_code, "_parse", parse)
    assert claude_code.parse_session(str(good))


DAMAGED = [(CATCH + "\n").encode() + b"\xff\xfe\n" + (CATCH + "\n").encode(),
           json.dumps({"ts": "2026-11-08T00:00:00+00:00", "project": 5, "kind": "stop"}) + "\n",
           json.dumps({"ts": "2026-11-08T00:00:00+00:00", "message": 5, "kind": 7}) + "\n",
           json.dumps({"ts": "2026-11-08T00:00:00+00:00", "agent": 5, "model": 7, "kind": "stop"}) + "\n",
           json.dumps({"ts": "2026-11-08T00:00:00+00:00", "tools": 5, "kind": "stop", "claim": 3, "command": 4, "reason": [], "version": 5}) + "\n",
           CATCH[:40], "[1, 2]\n5\n", ""]


@pytest.mark.parametrize("log", DAMAGED)
@pytest.mark.parametrize("args", [["catches"], ["catches", "--lang", "zh"], ["feedback"], ["feedback", "--issue"], ["doctor"], ["catches", "--days", "999999"], ["catches", "--days", "99999999999"]])
def test_a_damaged_catches_log_never_stops_the_report(tmp_path, log, args):
    home = tmp_path / "home"
    _write(home / ".honestly" / "catches.jsonl", log)
    r = _honestly(args, home)
    assert b"Traceback" not in r.stdout + r.stderr
    assert r.returncode in (0, 1) and r.stdout.strip()


@pytest.mark.parametrize("args", [["catches"], ["feedback"]])
@pytest.mark.parametrize("kind", ["dir", pytest.param("unreadable", marks=posix_only)])
def test_a_catches_log_it_cannot_open_is_one_line(tmp_path, args, kind):
    home = tmp_path / "home"
    log = home / ".honestly" / "catches.jsonl"
    if kind == "dir":
        log.mkdir(parents=True)
    else:
        _write(log, CATCH + "\n")
        log.chmod(0)
    r = _honestly(args, home)
    assert r.returncode == 1 and b"Traceback" not in r.stderr and b"catches.jsonl" in r.stderr
    d = _honestly(["doctor"], home)
    assert b"Traceback" not in d.stderr and b"catches.jsonl" in d.stdout


# ---------------------------------------------------------------- rule
def _rule(*a, **k):
    from honestly import support
    return support.rule(*a, **k)


@pytest.mark.parametrize("original", ["# mine\r\nline2\r\n", "# mine\nline2\n", "﻿# mine\n"])
def test_rule_install_then_uninstall_gives_back_the_same_bytes(tmp_path, original):
    p = tmp_path / "CLAUDE.md"
    p.write_bytes(original.encode("utf-8"))
    _rule("install", cwd=str(tmp_path))
    data = p.read_bytes()
    assert b"honestly:start" in data
    if "\r\n" in original:
        assert b"\n" not in data.replace(b"\r\n", b"")   # one newline style in the file
    _rule("uninstall", cwd=str(tmp_path))
    assert p.read_bytes().decode("utf-8") == original


def test_rule_on_a_file_it_cannot_read_stops_with_one_line(tmp_path):
    p = tmp_path / "CLAUDE.md"
    p.write_bytes(b"# mine\xff\n")
    for action in ("status", "install", "uninstall"):
        with pytest.raises(SystemExit) as e:
            _rule(action, cwd=str(tmp_path))
        assert "UTF-8" in str(e.value) and str(p) in str(e.value)
    assert p.read_bytes() == b"# mine\xff\n"


def test_rule_when_the_file_is_a_folder_stops_with_one_line(tmp_path):
    (tmp_path / "CLAUDE.md").mkdir()
    for action in ("status", "install"):
        with pytest.raises(SystemExit) as e:
            _rule(action, cwd=str(tmp_path))
        assert "CLAUDE.md" in str(e.value)


@posix_only
def test_rule_on_a_read_only_file_or_folder_stops_with_one_line(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root ignores file modes")
    p = tmp_path / "CLAUDE.md"
    p.write_text("# mine\n")
    p.chmod(0o444)
    with pytest.raises(SystemExit) as e:
        _rule("install", cwd=str(tmp_path))
    assert "cannot write" in str(e.value) and p.read_text() == "# mine\n"
    p.chmod(0o644)
    d = tmp_path / "ro"
    d.mkdir()
    d.chmod(0o555)
    with pytest.raises(SystemExit) as e:
        _rule("install", agent="cursor", cwd=str(d))
    d.chmod(0o755)
    assert "cannot write" in str(e.value)


def test_rule_when_dot_cursor_is_a_file_stops_with_one_line(tmp_path):
    (tmp_path / ".cursor").write_text("x")
    with pytest.raises(SystemExit) as e:
        _rule("install", agent="cursor", cwd=str(tmp_path))
    assert "cannot write" in str(e.value)


@posix_only
def test_rule_does_not_write_through_a_link_out_of_the_project(tmp_path):
    victim = tmp_path / "zshrc"
    victim.write_text("export KEEP=1\n")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "CLAUDE.md").symlink_to(victim)
    with pytest.raises(SystemExit) as e:
        _rule("install", cwd=str(proj))
    assert "outside" in str(e.value) and victim.read_text() == "export KEEP=1\n"
    (proj / ".cursor").symlink_to(tmp_path)
    with pytest.raises(SystemExit):
        _rule("install", agent="cursor", cwd=str(proj))
    assert not (tmp_path / "rules").exists()


@posix_only
def test_rule_follows_a_link_that_stays_inside_the_project(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# shared\n")
    (tmp_path / "CLAUDE.md").symlink_to("AGENTS.md")
    _rule("install", cwd=str(tmp_path))
    assert "honestly:start" in (tmp_path / "AGENTS.md").read_text() and (tmp_path / "CLAUDE.md").is_symlink()


# ---------------------------------------------------------------- the update note
def test_the_upgrade_command_matches_how_it_was_installed(tmp_path, monkeypatch):
    from honestly import update
    pipx = tmp_path / "pipx"
    pipx.mkdir()
    (pipx / "pipx_metadata.json").write_text("{}")
    uv = tmp_path / "uv"
    uv.mkdir()
    (uv / "uv-receipt.toml").write_text("")
    plain = tmp_path / "venv"
    plain.mkdir()
    assert update.upgrade_command(str(pipx), "/x/bin/honestly") == "pipx upgrade honestly"
    assert update.upgrade_command(str(uv), "/x/bin/honestly") == "uv tool upgrade honestly"
    assert update.upgrade_command(str(plain), "/x/bin/honestly") == "pip install -U honestly"
    assert update.upgrade_command(str(plain), "/plugins/honestly/hooks/run.py") == "claude plugin update honestly@honestly"
    monkeypatch.setattr(update.sys, "prefix", str(pipx))
    monkeypatch.setattr(update, "latest_version", lambda: "9.9.9")
    assert "pipx upgrade honestly" in update.update_note("0.1.0") and "pipx upgrade honestly" in update.update_note("0.1.0", zh=True)


def test_offline_is_only_tried_once_in_a_while(tmp_path, monkeypatch):
    from honestly import update
    monkeypatch.setattr(update, "cache_path", lambda: str(tmp_path / "u.json"))
    monkeypatch.delenv("HONESTLY_NO_UPDATE_CHECK", raising=False)
    calls = []
    def fetch(timeout=2.0):
        calls.append(1)
        raise OSError("offline")
    monkeypatch.setattr(update, "_fetch_latest", fetch)
    t = 1000000.0
    assert update.latest_version(now=t) == "" and update.latest_version(now=t + 60) == ""
    assert len(calls) == 1   # each `honestly catches` used to wait 2 s offline
    assert update.latest_version(now=t + update.RETRY_AFTER_FAILURE + 1) == "" and len(calls) == 2


def test_a_cache_timestamp_in_the_future_does_not_stop_checking_forever(tmp_path, monkeypatch):
    from honestly import update
    monkeypatch.setattr(update, "cache_path", lambda: str(tmp_path / "u.json"))
    monkeypatch.delenv("HONESTLY_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(update, "_fetch_latest", lambda timeout=2.0: "9.9.9")
    (tmp_path / "u.json").write_text(json.dumps({"ts": 9e12, "latest": "0.0.1"}))
    assert update.latest_version(now=1000.0) == "9.9.9"


# ---------------------------------------------------------------- what grows on disk
def _finding():
    from honestly.audit import Finding
    return Finding(session="s", turn=1, version="", agent="claude-code", model="", ts="", category="fixed", verdict="backed", reason="", claim="c", last_edit="", tools_after_edit=[], context="")


def test_a_session_keeps_one_cache_entry_however_often_it_changes(tmp_path, monkeypatch):
    from honestly import cache
    monkeypatch.setattr(cache, "cache_dir", lambda: str(tmp_path / "c"))
    s = tmp_path / "s.jsonl"
    other = tmp_path / "o.jsonl"
    other.write_text("{}\n")
    cache.put(str(other), "a", [_finding()])
    for i in range(20):
        s.write_text("x" * (i + 1))
        cache.put(str(s), "a", [_finding()])
        assert cache.get(str(s), "a")
    assert len(list((tmp_path / "c").iterdir())) == 2
    assert cache.get(str(other), "a")   # another session's entry is untouched


def test_entries_nothing_has_asked_for_in_months_go_away(tmp_path, monkeypatch):
    from honestly import cache
    monkeypatch.setattr(cache, "cache_dir", lambda: str(tmp_path / "c"))
    monkeypatch.setattr(cache, "_pruned", False)
    (tmp_path / "c").mkdir()
    old = tmp_path / "c" / "aaaa-bbbb.json"
    old.write_text("[]")
    os.utime(old, (1000, 1000))
    s = tmp_path / "s.jsonl"
    s.write_text("x")
    cache.put(str(s), "a", [_finding()])
    assert not old.exists() and cache.get(str(s), "a")


def test_a_background_task_file_that_changed_is_a_cache_miss(tmp_path, monkeypatch):
    from honestly import cache
    monkeypatch.setattr(cache, "cache_dir", lambda: str(tmp_path / "c"))
    s = tmp_path / "s.jsonl"
    s.write_text("x")
    task = tmp_path / "bg.output"
    task.write_text("1 failed\n")
    cache.put(str(s), "a", [_finding()], deps=[str(task)])
    assert cache.get(str(s), "a")
    task.write_text("3 passed, 0 failed\n")
    assert cache.get(str(s), "a") is None
    cache.put(str(s), "a", [_finding()], deps=[str(task)])
    task.unlink()   # task files are temporary; what was read while it existed still stands
    assert cache.get(str(s), "a")


def test_audit_notices_a_background_task_file_that_changed(tmp_path):
    home = tmp_path / "home"
    task = tmp_path / "bg.output"
    task.write_text("=== 1 failed, 2 passed in 0.1s ===\n")
    p = home / ".claude" / "projects" / "-w" / "s.jsonl"
    p.parent.mkdir(parents=True)
    t = "2026-11-01T00:00:00Z"
    rows = [{"type": "user", "message": {"role": "user", "content": "fix"}, "origin": {"kind": "human"}, "cwd": "/w", "timestamp": t},
            {"type": "assistant", "message": {"role": "assistant", "model": "m", "content": [{"type": "tool_use", "id": "e", "name": "Edit", "input": {"file_path": "/w/src/a.py", "old_string": "a", "new_string": "b"}}]}, "cwd": "/w", "timestamp": t},
            {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "e", "content": "ok"}]}, "cwd": "/w", "timestamp": t},
            {"type": "assistant", "message": {"role": "assistant", "model": "m", "content": [{"type": "tool_use", "id": "b", "name": "Bash", "input": {"command": "pytest -q"}}]}, "cwd": "/w", "timestamp": t},
            {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "b", "content": f"Output is being written to: {task}"}]}, "cwd": "/w", "timestamp": t},
            {"type": "assistant", "message": {"role": "assistant", "model": "m", "content": [{"type": "text", "text": "Fixed. All tests pass."}]}, "cwd": "/w", "timestamp": t}]
    p.write_text("\n".join(map(json.dumps, rows)) + "\n")
    before = json.loads(_honestly(["audit", "--summary-json"], home).stdout)
    task.write_text("=== 3 passed in 0.1s ===\n")
    cached = json.loads(_honestly(["audit", "--summary-json"], home).stdout)
    fresh = json.loads(_honestly(["audit", "--summary-json", "--no-cache"], home).stdout)
    assert cached == fresh and cached != before


def test_audit_clear_cache_empties_it(tmp_path):
    home = tmp_path / "home"
    _seed_session(home)
    _honestly(["audit", "--summary-json"], home)
    assert list((home / ".honestly" / "cache").iterdir())
    r = _honestly(["audit", "--clear-cache"], home)
    assert r.returncode == 0 and b"cache" in r.stdout and not list((home / ".honestly" / "cache").iterdir())


def test_the_cache_is_never_left_half_written(tmp_path, monkeypatch):
    from honestly import cache
    monkeypatch.setattr(cache, "cache_dir", lambda: str(tmp_path / "c"))
    s = tmp_path / "s.jsonl"
    s.write_text("x")
    def broken(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(cache.json, "dump", broken)
    cache.put(str(s), "a", [_finding()])
    assert not list((tmp_path / "c").iterdir())


def test_the_logs_stop_growing_and_keep_the_previous_part(tmp_path, monkeypatch):
    log = tmp_path / "catches.jsonl"   # conftest points catches_path here
    monkeypatch.setattr(hooks, "LOG_LIMIT", 1000)
    for _ in range(40):
        hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "pytest | head -5"}, "cwd": "/tmp", "session_id": "s"})
    assert log.stat().st_size < 3000 and (tmp_path / "catches.jsonl.1").exists()
    assert len(hooks.load_catches()) >= 1
    errors = tmp_path / "hook-errors.log"
    for _ in range(40):
        hooks._note("stdin", "x" * 100)
    assert errors.stat().st_size < 3000 and (tmp_path / "hook-errors.log.1").exists()
