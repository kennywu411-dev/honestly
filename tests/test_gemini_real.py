"""Gemini CLI's chat recording as version 0.67 really writes it, taken from a run of the real CLI."""
import json

import pytest

from honestly import agents, audit, hooks


def _call(name, args, output):
    call_id = f"{name}__{name}_1794131010392_0"
    return {"id": call_id, "name": name, "args": args, "status": "success", "timestamp": "2026-11-08T09:43:06.280Z",
            "result": [{"functionResponse": {"id": call_id, "name": name, "response": {"output": output}}}],
            "resultDisplay": output, "description": "", "displayName": name, "renderOutputAsMarkdown": False}


def _shell(output, code=0):
    tail = f"\nExit Code: {code}" if code else ""
    return f"<untrusted_context>\nOutput: {output}{tail}\nProcess Group PGID: 19953\n</untrusted_context>"


def _recording(tmp_path, *calls, reply="All 5 tests pass."):
    """One user prompt, then for each tool call: the empty model record, the same record with toolCalls, and the tool result as a `user` record."""
    rows = [{"sessionId": "47729bf4", "projectHash": "7a9e", "startTime": "2026-11-08T09:43:05.738Z", "lastUpdated": "2026-11-08T09:43:05.738Z", "kind": "main"},
            {"id": "ctx", "timestamp": "2026-11-08T09:43:05.738Z", "type": "user", "content": [{"text": "<session_context>\nThis is the Gemini CLI. We are setting up the context for our chat.\n</session_context>"}]},
            {"$set": {"lastUpdated": "2026-11-08T09:43:05.739Z"}},
            {"id": "prompt", "timestamp": "2026-11-08T09:43:06.261Z", "type": "user", "content": [{"text": "do the work"}]}]
    for i, call in enumerate(calls):
        base = {"id": f"m{i}", "timestamp": "2026-11-08T09:43:06.298Z", "type": "gemini", "content": "", "thoughts": [], "tokens": {"total": 2}, "model": "gemini-3.8-flash"}
        rows += [base, {"$set": {"lastUpdated": "x"}}, dict(base, toolCalls=[call]), {"$set": {"lastUpdated": "x"}},
                 {"id": f"r{i}", "timestamp": "2026-11-08T09:43:06.300Z", "type": "user", "content": call["result"]}, {"$set": {"lastUpdated": "x"}}]
    rows.append({"id": "last", "timestamp": "2026-11-08T09:43:06.400Z", "type": "gemini", "content": reply, "thoughts": [], "tokens": {"total": 2}, "model": "gemini-3.8-flash"})
    chats = tmp_path / "tmp" / "proj" / "chats"
    chats.mkdir(parents=True)
    (tmp_path / "tmp" / "proj" / ".project_root").write_text("/work/proj\n", encoding="utf-8")
    p = chats / "session-2026-11-08T09-43-47729bf4.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return str(p)


WRITE = _call("write_file", {"file_path": "app.py", "content": "x = 1\n"}, "Successfully created and wrote to new file: /work/proj/app.py.")


def test_one_prompt_is_one_turn(tmp_path):
    turns = agents.gemini_parse(_recording(tmp_path, WRITE, _call("run_shell_command", {"command": "pytest -q"}, _shell("5 passed in 0.1s"))))
    assert [t.prompt for t in turns] == ["do the work"]
    assert turns[0].project == "/work/proj" and turns[0].model == "gemini-3.8-flash"
    assert [(e.kind, e.name) for e in turns[0].events] == [("tool", "Edit"), ("tool", "Bash"), ("text", "")]


def test_a_tool_result_is_read_without_its_wrapper(tmp_path):
    turn = agents.gemini_parse(_recording(tmp_path, _call("run_shell_command", {"command": "pytest -q"}, _shell("1 failed, 4 passed in 0.1s", code=1))))[0]
    shell = turn.events[0]
    assert shell.result == "1 failed, 4 passed in 0.1s" and shell.is_error is True


def test_an_exit_code_of_zero_is_not_an_error(tmp_path):
    turn = agents.gemini_parse(_recording(tmp_path, _call("run_shell_command", {"command": "pytest -q"}, _shell("ok  \texample.com/a\t0.1s"))))[0]
    assert turn.events[0].result == "ok  \texample.com/a\t0.1s" and turn.events[0].is_error is False


def test_a_record_written_twice_counts_once(tmp_path):
    p = _recording(tmp_path, WRITE, reply="Done.")
    with open(p, "a", encoding="utf-8") as fh:   # the same id again, as the CLI does when it updates a record
        fh.write(json.dumps({"id": "last", "timestamp": "x", "type": "gemini", "content": "Done.", "model": "gemini-3.8-flash"}) + "\n")
    assert [e.text for e in agents.gemini_parse(p)[0].events if e.kind == "text"] == ["Done."]


def _stop(path, reply="All 5 tests pass.", active=False):
    return hooks.stop_hook({"session_id": "47729bf4", "transcript_path": path, "cwd": "/work/proj", "hook_event_name": "AfterAgent",
                            "prompt": "do the work", "prompt_response": reply, "stop_hook_active": active}, agent="gemini")


def test_an_edit_and_no_run_is_held(tmp_path):
    out = _stop(_recording(tmp_path, WRITE, reply="All tests pass."), reply="All tests pass.")
    assert out and out["decision"] == "deny"


def test_a_failed_run_is_held(tmp_path):
    out = _stop(_recording(tmp_path, WRITE, _call("run_shell_command", {"command": "pytest -q"}, _shell("1 failed, 4 passed in 0.1s", code=1))))
    assert out and out["decision"] == "deny"


def test_a_real_run_lets_the_reply_through(tmp_path):
    assert _stop(_recording(tmp_path, WRITE, _call("run_shell_command", {"command": "pytest -q"}, _shell("5 passed in 0.1s")))) is None


@pytest.mark.parametrize("res,want", [
    ("plain text", "plain text"),
    ([{"text": "a part"}], "a part"),
    ({"llmContent": "older shape"}, "older shape"),
    (_shell("5 passed"), "5 passed"),
    ("Command: pytest\nDirectory: (root)\nOutput: 5 passed\nError: (none)\nExit Code: 0\nSignal: (none)", "5 passed"),
])
def test_other_result_shapes_still_read(res, want):
    assert agents._gemini_result(res)[0] == want


def _after_hold(tmp_path, retry):
    """A held reply, the CLI sending our message back as a `user` record, and the model's new reply. On this second call `prompt_response` holds both replies."""
    p = _recording(tmp_path, WRITE, reply="All tests pass.")
    hold = "⚠️ honestly 已拦截：Gemini CLI 声称「All tests pass」，但改完 app.py 之后没有运行测试命令。\n给助手：请立即执行对应操作。"
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "hold", "timestamp": "x", "type": "user", "content": [{"text": hold}]}) + "\n")
        fh.write(json.dumps({"id": "again", "timestamp": "x", "type": "gemini", "content": retry, "model": "gemini-3.8-flash"}) + "\n")
    return _stop(p, reply="All tests pass.\n" + retry, active=True)


def test_an_honest_retry_is_let_through(tmp_path):
    assert _after_hold(tmp_path, "I have not run the tests.") is None


def test_the_same_claim_again_is_named_but_not_held_twice(tmp_path):
    out = _after_hold(tmp_path, "All tests pass.")
    assert out and "decision" not in out and "All tests pass" in out["systemMessage"]


def test_the_audit_still_counts_the_reply_that_was_held(tmp_path):
    p = _recording(tmp_path, WRITE, reply="All tests pass.")
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "hold", "timestamp": "x", "type": "user", "content": [{"text": "⚠️ honestly blocked this.\nTo the agent: run it."}]}) + "\n")
        fh.write(json.dumps({"id": "again", "timestamp": "x", "type": "gemini", "content": "I have not run the tests.", "model": "gemini-3.8-flash"}) + "\n")
    turns = agents.gemini_parse(p)
    assert [f.verdict for f in audit.audit_turn(turns[0], None)] == ["unbacked"]
