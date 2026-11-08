"""Claude Code calls a hold a 'hook error'. The message says nothing is broken, on that host only, and an unkept transcript is said out loud."""
import pytest

from honestly import agents, hooks


@pytest.mark.parametrize("which", ["stop", "pre"])
def test_claude_code_says_a_hold_is_not_a_fault(which):
    out = agents.emit("claude-code", which, "⚠️ honestly blocked this reply: x", "To the agent: y")
    assert "hook error" in out["systemMessage"] and "Nothing is broken" in out["systemMessage"]


def test_claude_code_says_it_in_chinese_too():
    out = agents.emit("claude-code", "stop", "⚠️ honestly 已拦截：x", "给助手：y")
    assert "hook error" in out["systemMessage"] and "不是故障" in out["systemMessage"]


@pytest.mark.parametrize("agent,field", [("codex", "systemMessage"), ("gemini", "systemMessage")])
def test_other_hosts_get_no_note_about_a_label_they_do_not_use(agent, field):
    assert "hook error" not in agents.emit(agent, "stop", "⚠️ honestly blocked this reply: x", "y")[field]


def test_the_agent_is_not_told_about_labels():
    assert "hook error" not in agents.emit("claude-code", "stop", "⚠️ honestly blocked this reply: x", "y")["reason"]


def test_a_claim_with_no_transcript_to_check_is_said_out_loud(tmp_path):
    out = hooks.stop_hook({"transcript_path": str(tmp_path / "gone.jsonl"), "last_assistant_message": "All tests pass.", "stop_hook_active": False})
    assert out and "decision" not in out and "could not check" in out["systemMessage"]


def test_a_reply_with_no_claim_and_no_transcript_says_nothing(tmp_path):
    assert hooks.stop_hook({"transcript_path": str(tmp_path / "gone.jsonl"), "last_assistant_message": "Here is the plan.", "stop_hook_active": False}) is None
