"""Fixes from the 2026-10-29 self-check: a read-only sed on eval.py was denied, harness tags leaked into the topic,
a CI-status read hid the real pytest result, and inline code vanished from claim text."""
from honestly import hooks, rules as R
from honestly.claude_code import Event, Turn
from honestly.audit import audit_turn


def _turn(*events, prompt="do it"):
    return Turn(session="s", index=1, version="", prompt=prompt, events=list(events))


def _tool(name, text="", err=False, result=""):
    return Event("tool", name=name, text=text, is_error=err, result=result)


def test_pre_hook_ignores_test_script_names_used_as_arguments():
    for cmd in ["sed -n 1,60p src/eval.py | grep -n -i -A20 'LABELS' | head -40", "awk '/def/' tests/test_x.py | head", "diff a_test.go b_test.go | head"]:
        assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": cmd}}) is None, cmd
    assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "python src/eval.py 2>&1 | tail -3"}}) is not None
    assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "pytest -q | tail -3"}}) is not None


def test_topic_drops_harness_tags_and_boilerplate():
    assert hooks._topic("<system-reminder> Linked sessions now (s…) </system-reminder>") == ""
    assert hooks._topic("<task-notification> <task-id>b1</task-id> done </task-notification>") == ""
    assert hooks._topic("This session is being continued from a previous conversation that ran out of context.") == ""
    assert hooks._topic("<system-reminder>x</system-reminder> 把图发我") == "把图发我"
    assert hooks._topic("a" * 40) == "a" * 30 + "…"


def test_pre_message_without_a_recognised_tool_reads_cleanly():
    zh = hooks._plain_pre("python src/eval.py | tail -3", True, "Claude Code")
    en = hooks._plain_pre("python src/eval.py | tail -3", False, "Claude Code")
    assert "把检查命令的结果截断了" in zh and "  " not in zh
    assert "piped a check through tail/head" in en and "  " not in en
    assert "把 pytest 的结果截断了" in hooks._plain_pre("pytest | tail", True, "")


def test_ci_status_read_after_real_test_run_does_not_hide_the_result():
    t = _turn(_tool("Edit", "/x/a.py"),
              _tool("Bash", "python -m pytest -q", result="3 passed in 0.1s"),
              _tool("Bash", "gh run view 1 --json status,conclusion", result="completed/success"),
              Event("text", text="改好了，3 个测试通过。"))
    f = [f for f in audit_turn(t) if f.category == "tests_pass"][0]
    assert f.verdict == "backed", (f.verdict, f.reason)
    t = _turn(_tool("Edit", "/x/a.py"),
              _tool("Bash", "python -m pytest -q", result="1 failed, 2 passed"),
              _tool("Bash", "gh run view 1 --json status,conclusion", result="completed/success"),
              Event("text", text="改好了，测试通过。"))
    f = [f for f in audit_turn(t) if f.category == "tests_pass"][0]
    assert f.verdict == "contradicted", (f.verdict, f.reason)


def test_inline_code_stays_in_the_claim_text():
    hits = R.find_claims("结果已保存到 `report.csv`。")
    assert hits and "report.csv" in hits[0].sentence
    t = _turn(_tool("Write", "/x/report.csv"), Event("text", text="结果已保存到 `report.csv`。"))
    assert [f.verdict for f in audit_turn(t) if f.category == "saved"] == ["backed"]
