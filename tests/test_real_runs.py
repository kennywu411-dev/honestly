"""A long or background run, read wherever its result arrives, in the shapes the real CLIs wrote."""
import json
import os

import pytest

from real_fixture import load
from test_real_turns import EDIT, _call, _prompt, _say, _session, held, stop


def test_codex_a_failure_polled_later_is_held(tmp_path):
    p = load(tmp_path, "codex", "09e", "All 5 tests pass")
    assert held(stop(p, "All 5 tests pass.", "codex"))


def test_codex_a_pass_polled_later_goes_through(tmp_path):
    p = load(tmp_path, "codex", "09f", "All 5 tests pass")
    assert stop(p, "All 5 tests pass.", "codex") is None


def test_codex_a_claim_while_the_run_is_going_is_held(tmp_path):
    p = load(tmp_path, "codex", "09c", "All 5 tests pass")
    out = stop(p, "All 5 tests pass.", "codex")
    assert held(out) and "still running" in out["reason"]


def test_gemini_a_failure_read_later_is_held(tmp_path):
    p = load(tmp_path, "gemini", "09b", "All 5 tests pass")
    assert held(stop(p, "All 5 tests pass.", "gemini"))


def test_gemini_a_pass_read_later_goes_through(tmp_path):
    p = load(tmp_path, "gemini", "09a", "All 5 tests pass")
    assert stop(p, "All 5 tests pass.", "gemini") is None


def test_gemini_a_claim_while_the_run_is_going_is_held(tmp_path):
    p = load(tmp_path, "gemini", "09c", "All 5 tests pass")
    out = stop(p, "All 5 tests pass.", "gemini")
    assert held(out) and "still running" in out["reason"]


def _bg_id(p):
    return open(p, encoding="utf-8").read().split("background with ID: ")[1].split(".")[0]


def test_claude_a_claim_while_the_background_run_is_going_is_held(tmp_path):
    p = load(tmp_path, "claude", "09d", "All 5 tests pass")
    out = stop(p, "All 5 tests pass.", background_tasks=[{"id": _bg_id(p), "type": "shell", "status": "running", "description": "run", "command": "sleep 8; pytest -q"}])
    assert held(out) and "still running" in out["reason"]


def test_claude_a_background_run_that_ended_with_no_output_is_not_called_running(tmp_path):
    p = load(tmp_path, "claude", "09d", "All 5 tests pass")
    assert stop(p, "All 5 tests pass.", background_tasks=[]) is None


def test_claude_an_older_host_without_the_field_is_judged_as_before(tmp_path):
    p = load(tmp_path, "claude", "09d", "All 5 tests pass")
    assert stop(p, "All 5 tests pass.") is None


def test_claude_a_finished_check_stands_while_another_task_runs(tmp_path):
    p = _session(tmp_path, _prompt("do the work"), *EDIT, *_call(2, "Bash", {"command": "pytest -q"}, "5 passed in 0.1s"),
                 *_call(3, "Agent", {"prompt": "look around", "subagent_type": "general-purpose"}, "Async agent launched successfully.\nagentId: a1 (internal ID)"), _say("All 5 tests pass."))
    assert stop(p, "All 5 tests pass.", background_tasks=[{"id": "a1", "type": "subagent", "status": "running", "description": "look"}]) is None


def test_claude_a_claim_with_a_subagent_still_running_and_nothing_else_is_held(tmp_path):
    p = _session(tmp_path, _prompt("do the work"), *EDIT,
                 *_call(3, "Agent", {"prompt": "run the tests", "subagent_type": "general-purpose"}, "Async agent launched successfully.\nagentId: a1 (internal ID)"), _say("All 5 tests pass."))
    out = stop(p, "All 5 tests pass.", background_tasks=[{"id": "a1", "type": "subagent", "status": "running", "description": "run the tests"}])
    assert held(out) and "still running" in out["reason"]


def test_claude_a_background_crash_with_no_summary_is_held(tmp_path):
    p = load(tmp_path, "claude", "09j", "All tests pass")
    task = _bg_id(p)
    with open(os.path.join(str(tmp_path), "scratch", "tasks", f"{task}.output"), "w", encoding="utf-8") as fh:
        fh.write("INTERNALERROR> collection crashed\n\n[exited with code 3]\n")
    assert held(stop(p, "All tests pass."))


def _codex_run(tmp_path, output):
    rows = [{"timestamp": "2026-11-09T00:00:00Z", "type": "session_meta", "payload": {"cwd": "/work/proj", "model": "m"}},
            {"timestamp": "2026-11-09T00:00:01Z", "type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage", "content": [{"type": "text", "text": "do it"}]}}},
            {"timestamp": "2026-11-09T00:00:02Z", "type": "response_item", "payload": {"type": "custom_tool_call", "name": "apply_patch", "input": "*** Begin Patch\n*** Update File: app.py\n@@\n-x\n+y\n*** End Patch\n", "call_id": "c0"}},
            {"timestamp": "2026-11-09T00:00:02Z", "type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c0", "output": "Exit code: 0\nOutput:\nSuccess."}},
            {"timestamp": "2026-11-09T00:00:03Z", "type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "arguments": "{\"cmd\": \"pytest -q\"}", "call_id": "c1"}},
            {"timestamp": "2026-11-09T00:00:03Z", "type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": output}},
            {"timestamp": "2026-11-09T00:00:04Z", "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "All 5 tests pass."}]}}]
    p = tmp_path / "rollout-x.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return str(p)


@pytest.mark.parametrize("line", ["warning: No such file or directory: conftest_extra.py", "Traceback (most recent call last): handled and logged by test_retry"])
def test_codex_a_clean_exit_is_a_clean_exit_whatever_the_log_says(tmp_path, line):
    out = f"Chunk ID: a\nWall time: 0.9 seconds\nProcess exited with code 0\nOriginal token count: 18\nOutput:\n{line}\n5 passed in 0.1s\n"
    assert stop(_codex_run(tmp_path, out), "All 5 tests pass.", "codex") is None


def test_codex_an_exit_code_is_read_when_the_log_says_nothing(tmp_path):
    out = "Chunk ID: a\nWall time: 0.9 seconds\nProcess exited with code 3\nOriginal token count: 4\nOutput:\nINTERNALERROR> crashed\n"
    assert held(stop(_codex_run(tmp_path, out), "All 5 tests pass.", "codex"))
