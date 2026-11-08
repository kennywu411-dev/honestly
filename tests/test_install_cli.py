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
