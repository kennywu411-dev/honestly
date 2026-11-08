"""A hold must not talk an agent into doing something hard to undo just to make a sentence true. The hold itself stays exactly as strict."""
import json

import pytest

from honestly import hooks

HARD = ["Deployed to production.", "I've emailed the customer the refund.", "Pushed to main.", "I've posted the update to the channel."]


def _hold(tmp_path, say, tools=(("Edit", {"file_path": "/work/p/src/app.py"}, "ok"),)):
    rows = [{"type": "user", "message": {"role": "user", "content": "look at this ticket"}, "origin": {"kind": "human"}, "cwd": "/work/p", "timestamp": "2026-01-01T00:00:00Z"}]
    for i, (name, inp, out) in enumerate(tools, 1):
        rows.append({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}]}, "cwd": "/work/p", "timestamp": f"2026-01-01T00:00:{i:02d}Z"})
        rows.append({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": out}]}, "cwd": "/work/p", "timestamp": f"2026-01-01T00:00:{i:02d}Z"})
    rows.append({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": say}]}, "cwd": "/work/p", "timestamp": "2026-01-01T00:01:00Z"})
    path = tmp_path / "s.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return hooks.stop_hook({"transcript_path": str(path), "cwd": "/work/p", "last_assistant_message": say, "stop_hook_active": False})


@pytest.mark.parametrize("say", HARD)
def test_it_still_holds_and_does_not_say_go_and_do_it(tmp_path, say):
    out = _hold(tmp_path, say)
    assert out and out["decision"] == "block"
    reason = out["reason"].lower()
    for bad in ("do it now", "run a push", "run a deploy", "do it first", "asked to run"):
        assert bad not in reason, reason
    assert "check" in reason and "not done" in reason and "ask the user" in reason


@pytest.mark.parametrize("say", ["Deployed to production.", "Pushed to main."])
def test_the_line_the_user_sees_says_the_same(tmp_path, say):
    assert "check, or to say it was not done" in _hold(tmp_path, say)["systemMessage"]


def test_a_failed_push_is_not_answered_with_try_again(tmp_path):
    out = _hold(tmp_path, "Pushed to main.", (("Edit", {"file_path": "/work/p/a.py"}, "ok"), ("Bash", {"command": "git push"}, "error: failed to push some refs")))
    assert out and out["decision"] == "block"
    assert "ask the user" in out["reason"].lower() and "fix it" not in out["systemMessage"]


def test_a_mixed_reply_gets_the_careful_instruction(tmp_path):
    out = _hold(tmp_path, "All tests pass. Pushed to main.")
    assert "ask the user" in out["reason"].lower() and "do it now" not in out["reason"].lower()
    assert "run tests" in out["reason"].lower()


def test_tests_and_builds_are_still_sent_off_to_run(tmp_path):
    for say in ("All tests pass.", "Build succeeded.", "Fixed the bug."):
        out = _hold(tmp_path, say)
        assert out and "do it now" in out["reason"].lower() and "run the tests" in out["reason"].lower()
        last = out["reason"].split("\n")[1].lower()
        assert " push " not in last and " send " not in last


def test_the_chinese_wording_too(tmp_path, monkeypatch):
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    monkeypatch.setattr(hooks, "_SYSTEM_ZH", None)
    out = _hold(tmp_path, "已部署到生产环境。")
    assert out and out["decision"] == "block"
    assert "立即执行" not in out["reason"] and "先问用户" in out["reason"] and "核实" in out["systemMessage"]
