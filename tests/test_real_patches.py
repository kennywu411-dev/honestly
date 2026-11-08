"""Codex hands a whole patch over as text. It is an edit, whatever it says."""
import pytest

from honestly import codex, hooks
from real_fixture import load
from test_real_turns import held, stop


@pytest.mark.parametrize("body", ["+Do not run pytest | head -3 because it hides the result.", "+pytest | head -3"])
def test_codex_a_patch_that_mentions_a_pipe_is_not_refused(body):
    patch = f"*** Begin Patch\n*** Add File: docs/howto.md\n{body}\n*** End Patch\n"
    assert hooks.pre_hook({"tool_name": "apply_patch", "tool_input": {"command": patch}, "session_id": "s"}, agent="codex") is None


def test_codex_a_piped_test_is_still_refused():
    out = hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "pytest | head -3"}, "session_id": "s"}, agent="codex")
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_codex_a_patch_body_with_a_cmd_key_is_an_edit(tmp_path):
    p = load(tmp_path, "codex", "15g", "All tests pass")
    tools = [e for t in codex.parse_session(p) for e in t.events if e.kind == "tool"]
    assert [(e.name, e.text) for e in tools] == [("Edit", "runner.js")]
    assert held(stop(p, "All tests pass.", "codex"))


def test_codex_a_wrapped_shell_call_is_still_a_command():
    tool, text = codex._command_from_call("js_exec", {"input": 'await exec({cmd: "pytest -q"})'})
    assert (tool, text) == ("Bash", "pytest -q")


def test_codex_old_rollouts_open_a_turn_at_each_prompt(tmp_path):
    p = load(tmp_path, "codex", "v140")
    assert [t.prompt for t in codex.parse_session(p) if t.prompt] == ["fix it", "say hi", "fix again"]
