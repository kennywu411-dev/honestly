"""0.6.3: desktop notifications are rate-limited."""
from honestly import hooks


def test_notifications_are_rate_limited(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "notify_flag_path", lambda: str(tmp_path / "notify"))
    assert hooks._notify_due() is True
    assert hooks._notify_due() is False
    assert hooks._notify_due() is False
    import os, time
    old = time.time() - hooks.NOTIFY_GAP - 1
    os.utime(str(tmp_path / "notify.last"), (old, old))
    assert hooks._notify_due() is True


def test_a_burst_of_catches_shows_one_notification(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(hooks, "notify_flag_path", lambda: str(tmp_path / "notify"))
    (tmp_path / "notify").write_text("")
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    for _ in range(20):
        hooks._notify("honestly", "piped pytest through tail")
    assert len(calls) == 1


def test_gh_argument_naming_a_test_tool_is_not_a_run():
    # `gh repo edit --add-topic pytest | tail` mentions pytest but runs no tests (found while tagging this repo)
    from honestly import hooks
    out = hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "gh repo edit --add-topic pytest --add-topic testing 2>&1 | tail -2"}, "cwd": "/tmp"})
    assert out is None
    out = hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "pytest -q | head -3"}, "cwd": "/tmp"})
    assert out is not None   # a real test run whose summary is cut off is still refused


def test_system_language_follows_posix_order_and_os_fallback(monkeypatch):
    from honestly import hooks
    def fresh(**env):
        for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
            monkeypatch.delenv(var, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setattr(hooks, "_SYSTEM_ZH", None)
        return hooks.system_zh()
    assert fresh(LANG="zh_CN.UTF-8") is True
    assert fresh(LANG="zh_CN.UTF-8", LC_ALL="en_US.UTF-8") is False   # LC_ALL wins
    assert fresh(LANG="en_US.UTF-8", LC_MESSAGES="zh_TW.UTF-8") is True
    assert fresh(LANG="C") is False
    import subprocess, sys as _sys
    monkeypatch.setattr(_sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: type("R", (), {"stdout": '(\n    "zh-Hans-CN",\n    "en-AU"\n)'})())
    assert fresh() is True   # no locale variables at all: the macOS UI language decides
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: type("R", (), {"stdout": '(\n    "en-AU",\n    "zh-Hans-CN"\n)'})())
    assert fresh() is False
