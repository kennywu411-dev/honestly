"""Sessions the real CLIs recorded. A turn is what the person asked for, however many notifications, compactions or retries it took."""
import json
import os

import pytest

from honestly import agents, audit, claude_code, codex, hooks
from real_fixture import cut, load


def stop(path, reply, agent="claude-code", **extra):
    data = {"session_id": "s", "transcript_path": path, "cwd": "/work/proj", "stop_hook_active": False, **extra}
    if agent == "gemini":
        data["prompt_response"] = reply
    else:
        data["last_assistant_message"] = reply
    return hooks.stop_hook(data, agent=agent)


def held(out):
    return bool(out) and out.get("decision") in ("block", "deny")


# ---------------------------------------------------------------- Claude Code: what opens a turn
def test_a_background_failure_notified_later_is_held(tmp_path):
    p = load(tmp_path, "claude", "09f", "All 5 tests pass", tasks={"bvbrhoe58": "1 failed, 4 passed in 0.1s\n\n[exited with code 1]\n"})
    assert held(stop(p, "All 5 tests pass."))


def test_a_background_pass_notified_later_goes_through(tmp_path):
    p = load(tmp_path, "claude", "09e", "All 5 tests pass")
    task = json.dumps(open(p, encoding="utf-8").read()).split("written to: ")[1].split(".output")[0].rsplit("/", 1)[-1]
    with open(os.path.join(str(tmp_path), "scratch", "tasks", f"{task}.output"), "w", encoding="utf-8") as fh:
        fh.write("5 passed in 0.1s\n\n[exited with code 0]\n")
    assert stop(p, "All 5 tests pass.") is None


def test_a_failed_run_before_auto_compaction_is_still_held(tmp_path):
    p = load(tmp_path, "claude", "12c", "All tests pass")
    assert held(stop(p, "All tests pass."))


def test_a_passed_run_before_auto_compaction_still_backs_the_claim(tmp_path):
    p = load(tmp_path, "claude", "12d", "All 5 tests pass")
    assert stop(p, "All 5 tests pass.") is None


def test_a_prompt_with_content_blocks_opens_a_turn():
    p = os.path.join(os.path.dirname(__file__), "fixtures", "real", "claude", "sdk.jsonl")
    turns = claude_code.parse_session(p, subagents=False)
    assert [t.prompt[:6] for t in turns if t.prompt and not t.prompt.startswith("Stop hook")][:2] == ["first:", "second"]


def _session(tmp_path, *rows):
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return str(p)


def _prompt(text):
    return {"type": "user", "origin": {"kind": "human"}, "promptSource": "typed", "turnOrigin": "human", "timestamp": "2026-11-08T12:00:00.000Z", "message": {"role": "user", "content": text}}


def _call(i, name, inp, out, is_error=False):
    ts = f"2026-11-08T12:00:{i:02d}.000Z"
    return [{"type": "assistant", "timestamp": ts, "message": {"role": "assistant", "model": "m", "content": [{"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}]}},
            {"type": "user", "timestamp": ts, "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": out, "is_error": is_error}]}}]


def _say(text, ts="2026-11-08T12:01:00.000Z"):
    return {"type": "assistant", "timestamp": ts, "message": {"role": "assistant", "model": "m", "content": [{"type": "text", "text": text}]}}


PEER = {"type": "user", "isMeta": True, "origin": {"kind": "peer"}, "promptSource": "system", "turnOrigin": "peer", "timestamp": "2026-11-08T12:00:40.000Z",
        "message": {"role": "user", "content": "Another Claude session sent a message:\nAll 57 tests pass on the branch (57 passed)."}}
CHILD = {"type": "user", "origin": {"kind": "task-notification"}, "promptSource": "system", "turnOrigin": "task_notification", "timestamp": "2026-11-08T12:00:40.000Z",
         "message": {"role": "user", "content": "<task-notification>\n<task-id>s1</task-id>\n<status>completed</status>\n<summary>The session you started finished a turn</summary>\n<result>57 passed</result>\n</task-notification>"}}
EDIT = _call(1, "Write", {"file_path": "/work/proj/app.py", "content": "x"}, "ok")


@pytest.mark.parametrize("report", [PEER, CHILD], ids=["peer", "child session"])
def test_a_reply_to_another_sessions_report_is_not_judged_on_this_sessions_edits(tmp_path, report):
    p = _session(tmp_path, _prompt("do the work"), *EDIT, _say("Edited, waiting for the other session."), report, _say("The other session reports all 57 tests pass."))
    assert stop(p, "The other session reports all 57 tests pass.") is None


@pytest.mark.parametrize("report", [PEER, CHILD], ids=["peer", "child session"])
def test_an_edit_after_another_sessions_report_is_judged(tmp_path, report):
    edit = _call(50, "Write", {"file_path": "/work/proj/b.py", "content": "y"}, "ok")
    p = _session(tmp_path, _prompt("do the work"), report, *edit, _say("All tests pass."))
    assert held(stop(p, "All tests pass."))


def test_a_nonprompt_record_keeps_the_prompt_the_person_wrote(tmp_path):
    note = {"type": "user", "origin": {"kind": "task-notification"}, "promptSource": "system", "turnOrigin": "task_notification", "timestamp": "2026-11-08T12:00:40.000Z",
            "message": {"role": "user", "content": "<task-notification>\n<task-id>b1</task-id>\n<tool-use-id>t1</tool-use-id>\n<status>completed</status>\n</task-notification>"}}
    meta = {"type": "user", "isMeta": True, "timestamp": "2026-11-08T12:00:41.000Z", "message": {"role": "user", "content": "<system-reminder>\n<tools-used-before-summary>Write</tools-used-before-summary>\n</system-reminder>"}}
    compact = {"type": "user", "isCompactSummary": True, "isVisibleInTranscriptOnly": True, "turnOrigin": "human", "timestamp": "2026-11-08T12:00:42.000Z",
               "message": {"role": "user", "content": "This session is being continued from a previous conversation that ran out of context."}}
    typed = {"type": "user", "timestamp": "2026-11-08T12:00:43.000Z", "message": {"role": "user", "content": "<local-command-stdout>done</local-command-stdout>"}}
    p = _session(tmp_path, _prompt("fix the login bug"), *EDIT, note, meta, compact, typed, _say("All tests pass."))
    turns = claude_code.parse_session(p, subagents=False)
    assert [t.prompt for t in turns] == ["fix the login bug"]
    assert [e.name for e in turns[0].events if e.kind == "tool"] == ["Write"]


def test_a_skills_text_does_not_excuse_a_claim(tmp_path):
    skill = {"type": "user", "isMeta": True, "timestamp": "2026-11-08T12:00:02.000Z", "message": {"role": "user", "content": [{"type": "text", "text": "Base directory for this skill: /x"}]}}
    look = _call(3, "Read", {"file_path": "/work/proj/a.py"}, "x")
    p = _session(tmp_path, _prompt("mail the maintainer"), skill, *look, _say("I sent the email to the maintainer."))
    assert held(stop(p, "I sent the email to the maintainer."))


def test_a_scheduled_prompt_is_a_new_request(tmp_path):
    scheduled = {"type": "user", "origin": {"kind": "task-notification"}, "promptSource": "system", "turnOrigin": "scheduled", "timestamp": "2026-11-08T12:00:40.000Z", "message": {"role": "user", "content": "Check the nightly build."}}
    p = _session(tmp_path, _prompt("fix the bug"), *EDIT, _say("Edited."), scheduled, _say("Nothing to report."))
    assert [t.prompt for t in claude_code.parse_session(p, subagents=False)] == ["fix the bug", "Check the nightly build."]


def test_an_old_transcript_with_plain_strings_still_opens_turns(tmp_path):
    rows = [{"type": "user", "timestamp": "2026-01-01T00:00:00Z", "message": {"role": "user", "content": "first"}}, _say("ok"),
            {"type": "user", "timestamp": "2026-01-01T00:01:00Z", "message": {"role": "user", "content": "second"}}, _say("ok")]
    assert [t.prompt for t in claude_code.parse_session(_session(tmp_path, *rows), subagents=False)] == ["first", "second"]


def test_a_compaction_still_says_the_earlier_work_is_not_all_here(tmp_path):
    compact = {"type": "user", "isCompactSummary": True, "turnOrigin": "human", "timestamp": "2026-11-08T12:00:42.000Z", "message": {"role": "user", "content": "This session is being continued from a previous conversation."}}
    p = _session(tmp_path, _prompt("go on"), compact, _say("I sent the email to the maintainer."))
    findings = audit.audit_turns(claude_code.parse_session(p, subagents=False))
    assert [f.verdict for f in findings] != ["unbacked"]


def test_tail_reading_finds_the_real_prompt_past_notifications(tmp_path):
    notes = [{"type": "user", "origin": {"kind": "task-notification"}, "promptSource": "system", "turnOrigin": "task_notification", "timestamp": "2026-11-08T12:00:40.000Z",
              "message": {"role": "user", "content": f"<task-notification>\n<task-id>b{i}</task-id>\n<tool-use-id>t1</tool-use-id>\n</task-notification>"}} for i in range(6)]
    big = {"type": "assistant", "timestamp": "2026-11-08T12:00:30.000Z", "message": {"role": "assistant", "model": "m", "content": [{"type": "text", "text": "x" * (3 * 1024 * 1024)}]}}
    p = _session(tmp_path, _prompt("earlier"), _say("ok"), _prompt("fix it"), *EDIT, big, big, big, *notes, _say("All tests pass."))
    assert os.path.getsize(p) > claude_code.TAIL_THRESHOLD
    a, b = claude_code.parse_session(p, tail=True), claude_code.parse_session(p)
    assert a[-1].prompt == b[-1].prompt == "fix it"
    assert held(stop(p, "All tests pass."))


# ---------------------------------------------------------------- Gemini CLI: compression stays in the turn
def test_gemini_a_failed_run_before_compression_is_held(tmp_path):
    p = load(tmp_path, "gemini", "12e", "All tests pass")
    assert held(stop(p, "All tests pass.", "gemini"))


def test_gemini_compression_does_not_add_a_turn(tmp_path):
    p = load(tmp_path, "gemini", "12e", "All tests pass")
    assert [t.prompt[:7] for t in agents.gemini_parse(p)] == ["first q", "second ", "now fix"]


def test_gemini_a_loop_warning_stays_in_the_turn(tmp_path):
    p = tmp_path / "chats" / "session-x.jsonl"
    p.parent.mkdir()
    rows = [{"id": "h", "sessionId": "abc", "projectHash": "x", "kind": "main"},
            {"id": "u", "type": "user", "timestamp": "2026-11-08T12:00:00Z", "content": [{"text": "fix it"}]},
            {"id": "g", "type": "gemini", "timestamp": "2026-11-08T12:00:01Z", "content": "", "model": "m", "toolCalls": [{"id": "c", "name": "write_file", "args": {"file_path": "app.py", "content": "x"}, "status": "success", "result": []}]},
            {"id": "l", "type": "user", "timestamp": "2026-11-08T12:00:02Z", "content": [{"text": "System: Potential loop detected. Details: Repeated tool call"}]},
            {"id": "e", "type": "gemini", "timestamp": "2026-11-08T12:00:03Z", "content": "All tests pass.", "model": "m"}]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert [t.prompt for t in agents.gemini_parse(str(p))] == ["fix it"]
    assert held(stop(str(p), "All tests pass.", "gemini"))


# ---------------------------------------------------------------- one prompt, one hold
def test_gemini_second_claim_after_a_tool_call_is_noted_not_held(tmp_path):
    p = load(tmp_path, "gemini", "07f")
    cut(p, "try 1")
    out = stop(p, "All tests pass, try 0.\nAll tests pass, try 1.", "gemini")
    assert not held(out) and "not held a second time" in out["systemMessage"]


def test_gemini_many_claims_still_one_hold(tmp_path):
    p = load(tmp_path, "gemini", "07f")
    cut(p, "try 5")
    assert not held(stop(p, "All tests pass, try 5.", "gemini"))


def test_gemini_an_honest_retry_after_a_tool_call_is_left_alone(tmp_path):
    p = load(tmp_path, "gemini", "07g", "I changed app.py")
    assert stop(p, "All tests pass.\nI changed app.py; not verified.", "gemini") is None


def test_gemini_the_first_claim_is_held(tmp_path):
    p = load(tmp_path, "gemini", "07f", "try 0")
    assert held(stop(p, "All tests pass, try 0.", "gemini"))


def test_claude_a_later_claim_in_the_same_prompt_is_noted_not_held_even_when_the_host_reset_the_flag(tmp_path):
    p = load(tmp_path, "claude", "07b")
    out = stop(p, "All tests pass.")
    assert not held(out) and "not held a second time" in out["systemMessage"]


def test_a_new_prompt_can_be_held_again(tmp_path):
    p = load(tmp_path, "claude", "07a")
    edit = _call(60, "Write", {"file_path": "/work/proj/c.py", "content": "z"}, "ok")
    with open(p, "a", encoding="utf-8") as fh:
        for r in [_prompt("next thing"), *edit, _say("All tests pass.")]:
            fh.write(json.dumps(r) + "\n")
    assert held(stop(p, "All tests pass."))


# ---------------------------------------------------------------- Codex: the hook's prompt is not a new request, and not part of the reply
def test_codex_an_honest_retry_gets_no_notice(tmp_path):
    p = load(tmp_path, "codex", "07a", "not yet verified")
    assert stop(p, "Changed app.py; not yet verified.", "codex", stop_hook_active=True) is None


def test_codex_a_repeated_claim_gets_the_notice(tmp_path):
    p = load(tmp_path, "codex", "01", "All tests pass")
    with open(p, encoding="utf-8") as fh:
        first = fh.read()
    held_first = stop(p, "All tests pass.", "codex")
    assert held(held_first)
    cut_rows = [json.loads(x) for x in first.splitlines()]
    last = cut_rows[-1]
    hook = {"timestamp": last["timestamp"], "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": '<hook_prompt hook_run_id="stop:1:x">⚠️ honestly blocked this reply</hook_prompt>'}]}}
    again = {"timestamp": last["timestamp"], "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "All tests pass."}]}}
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(hook) + "\n" + json.dumps(again) + "\n")
    out = stop(p, "All tests pass.", "codex", stop_hook_active=True)
    assert not held(out) and "not held a second time" in out["systemMessage"]
