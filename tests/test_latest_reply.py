"""A long turn has several replies now that a notification no longer starts a turn. A reply that already went out through a stop was judged then."""
import json

from honestly import hooks


def _user(text):
    return {"type": "user", "message": {"role": "user", "content": text}, "origin": {"kind": "human"}}


def _tool(name, inp, out="ok", tid="t"):
    return [{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}},
            {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": out}]}}]


def _say(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


NOTICE = {"type": "user", "message": {"role": "user", "content": "<task-notification>\n<task-id>x</task-id>\n<status>completed</status>\n</task-notification>"}, "origin": {"kind": "task-notification"}}
ASIDE = {"type": "user", "message": {"role": "user", "content": "<system-reminder>\nA background step finished.\n</system-reminder>"}, "isMeta": True}
STOPPED = {"type": "system", "subtype": "stop_hook_summary", "hookCount": 1}


def _held(tmp_path, rows, reply):
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    out = hooks.stop_hook({"transcript_path": str(p), "last_assistant_message": reply, "stop_hook_active": False})
    return bool(out and out.get("decision") == "block")


EDIT = _tool("Edit", {"file_path": "/p/src/app.py"})


def test_a_reply_that_already_stopped_is_not_judged_again(tmp_path):
    rows = [_user("go"), *EDIT, _say("All tests pass."), STOPPED, NOTICE, _say("Still waiting on the rest.")]
    assert not _held(tmp_path, rows, "Still waiting on the rest.")


def test_the_new_reply_is_still_judged(tmp_path):
    rows = [_user("go"), _say("Starting."), STOPPED, NOTICE, *EDIT, _say("All tests pass.")]
    assert _held(tmp_path, rows, "All tests pass.")


def test_work_before_the_stop_still_counts_against_the_new_reply(tmp_path):
    rows = [_user("go"), *EDIT, _say("Edited it."), STOPPED, ASIDE, _say("All tests pass.")]
    assert _held(tmp_path, rows, "All tests pass.")


def test_a_run_before_the_stop_still_backs_the_new_reply(tmp_path):
    run = _tool("Bash", {"command": "pytest -q"}, "5 passed in 0.1s", tid="r")
    rows = [_user("go"), *EDIT, *run, _say("Ran it."), STOPPED, ASIDE, _say("All 5 tests pass.")]
    assert not _held(tmp_path, rows, "All 5 tests pass.")


def test_a_progress_note_in_the_same_reply_is_still_judged(tmp_path):
    rows = [_user("go"), *EDIT, _say("All tests pass."), *_tool("Bash", {"command": "ls"}, "a", tid="l"), _say("Done looking.")]
    assert _held(tmp_path, rows, "Done looking.")


def test_a_notification_alone_does_not_excuse_what_came_before_it(tmp_path):
    rows = [_user("go"), *EDIT, _say("All tests pass."), NOTICE, _say("Noted.")]   # no stop between them: that text never went through this hook
    assert _held(tmp_path, rows, "Noted.")


def test_a_word_in_a_script_is_not_named_as_the_edited_file():
    assert hooks._edited_name("Bash: cat > t.py <<'EOF'\n@pytest.mark.skip\nEOF") in ("t.py", "")
    assert hooks._edited_name("Bash: python3 -c \"print(pytest.mark)\"") == ""
