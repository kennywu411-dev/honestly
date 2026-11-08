"""A hook that runs out of time must say so. Before this, the assistant's timeout killed it and the check silently did not happen."""
import io
import json
import os
import re
import signal
import sys
import threading
import time

import pytest

from honestly import hooks

needs_alarm = pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="no SIGALRM on this platform")


def _run(monkeypatch, capsys, which="stop", agent="claude-code", payload=None):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload or {})))
    start = time.perf_counter()
    assert hooks.run_hook(which, agent) == 0
    text = capsys.readouterr().out
    return (json.loads(text) if text.strip() else None), time.perf_counter() - start


def _stub(monkeypatch, fn, seconds=0.2):
    monkeypatch.setitem(hooks.HOOK_BUDGET, "stop", seconds)
    monkeypatch.setitem(hooks.HOOK_BUDGET, "pre", seconds)
    monkeypatch.setattr(hooks, "stop_hook", lambda data=None, agent="claude-code": fn())
    monkeypatch.setattr(hooks, "pre_hook", lambda data=None, agent="claude-code": fn())


@needs_alarm
@pytest.mark.parametrize("which,word", [("stop", "reply"), ("pre", "command")])
def test_a_catastrophic_regex_is_stopped_and_reported(tmp_path, monkeypatch, capsys, which, word):
    _stub(monkeypatch, lambda: re.search(r"(=+)+x", "=" * 40))
    out, took = _run(monkeypatch, capsys, which)
    assert took < 3.0
    assert "not checked" in out["systemMessage"] and word in out["systemMessage"]
    assert "decision" not in out and "hookSpecificOutput" not in out
    assert "budget" in (tmp_path / "hook-errors.log").read_text(encoding="utf-8")


@needs_alarm
def test_a_blocked_read_is_stopped_too(monkeypatch, capsys, tmp_path):
    fifo = tmp_path / "f"
    os.mkfifo(fifo)
    _stub(monkeypatch, lambda: open(fifo).read())
    out, took = _run(monkeypatch, capsys)
    assert took < 3.0 and "not checked" in out["systemMessage"]


@needs_alarm
def test_code_that_swallows_errors_cannot_swallow_the_deadline(monkeypatch, capsys):
    def stubborn():
        try:
            time.sleep(30)
        except Exception:
            return {"decision": "block"}
    _stub(monkeypatch, stubborn)
    out, took = _run(monkeypatch, capsys)
    assert took < 3.0 and "not checked" in out["systemMessage"] and "decision" not in out


@needs_alarm
def test_a_normal_run_prints_only_its_result_and_disarms(monkeypatch, capsys):
    _stub(monkeypatch, lambda: {"decision": "block", "reason": "r", "systemMessage": "s"}, seconds=5)
    out, _ = _run(monkeypatch, capsys)
    assert out == {"decision": "block", "reason": "r", "systemMessage": "s"}
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


@needs_alarm
def test_an_error_still_disarms(monkeypatch, capsys, tmp_path):
    _stub(monkeypatch, lambda: 1 / 0, seconds=5)
    out, _ = _run(monkeypatch, capsys)
    assert out is None and signal.getitimer(signal.ITIMER_REAL)[0] == 0
    assert "ZeroDivisionError" in (tmp_path / "hook-errors.log").read_text(encoding="utf-8")


@needs_alarm
def test_cursor_has_no_quiet_channel_so_only_the_log_records_it(monkeypatch, capsys, tmp_path):
    _stub(monkeypatch, lambda: time.sleep(30))
    out, _ = _run(monkeypatch, capsys, agent="cursor")
    assert out is None and "budget" in (tmp_path / "hook-errors.log").read_text(encoding="utf-8")


def test_without_alarm_the_watchdog_can_end_the_process(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(hooks, "_has_alarm", lambda: False)
    monkeypatch.setattr(hooks.faulthandler, "dump_traceback_later", lambda seconds, **kw: calls.append((seconds, kw.get("exit"))))
    monkeypatch.setattr(hooks.faulthandler, "cancel_dump_traceback_later", lambda: calls.append("cancelled"))
    disarm = hooks._arm_budget(7.0)
    disarm()
    assert calls == [(7.0, True), "cancelled"]


def test_outside_the_main_thread_nothing_is_armed(monkeypatch, capsys):
    results = []
    def worker():
        results.append(hooks._arm_budget(0.01)())
    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert results == [None]


def test_the_budgets_fit_inside_the_timeouts_the_hooks_are_installed_with():
    entries = hooks._entries()
    assert hooks.HOOK_BUDGET["stop"] < entries["Stop"]["hooks"][0]["timeout"]
    assert hooks.HOOK_BUDGET["pre"] < entries["PreToolUse"]["hooks"][0]["timeout"]
    plugin = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "hooks.json"), encoding="utf-8"))["hooks"]
    assert hooks.HOOK_BUDGET["stop"] < plugin["Stop"][0]["hooks"][0]["timeout"]
    assert hooks.HOOK_BUDGET["pre"] < plugin["PreToolUse"][0]["hooks"][0]["timeout"]
