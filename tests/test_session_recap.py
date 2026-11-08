"""A reply in a turn with no tools usually recaps earlier work. When nothing earlier in the session did the thing, it is not a recap."""
import json

import pytest

from honestly import hooks


def _user(text):
    return {"type": "user", "message": {"role": "user", "content": text}, "origin": {"kind": "human"}}


def _tool(name, inp, out="ok", tid="t"):
    return [{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}},
            {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": out}]}}]


def _say(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def _held(tmp_path, rows, reply):
    p = tmp_path / "s.jsonl"
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    out = hooks.stop_hook({"transcript_path": str(p), "last_assistant_message": reply, "stop_hook_active": False})
    return bool(out and out.get("decision") == "block")


FIRST = [_user("hi")]
LOOKED = [_user("look"), *_tool("Bash", {"command": "ls"}, "a.txt"), _say("Here it is."), _user("send it")]


@pytest.mark.parametrize("reply", [
    "邮件已发送给他了。", "I sent the email to the team.", "已保存到 report.csv。", "已部署到生产环境。", "定时任务已建好，明早 8 点运行。",
    "All tests pass.", "已推送到 main。",
])
def test_nothing_earlier_did_it(tmp_path, reply):
    assert _held(tmp_path, FIRST, reply)
    assert _held(tmp_path, LOOKED, reply)


def test_looked_up_with_nothing_earlier_at_all(tmp_path):
    assert _held(tmp_path, FIRST, "我查过官方文档了，确认支持。")   # any earlier read or command counts as looking, so this only catches a session with none


@pytest.mark.parametrize("earlier,reply", [
    (_tool("SendUserFile", {"files": ["a.png"]}), "已发送给你了。"),
    (_tool("Write", {"file_path": "/p/report.csv"}), "已保存到 report.csv。"),
    (_tool("Bash", {"command": "git push origin main"}, "main -> main"), "已推送到 main。"),
    (_tool("Bash", {"command": "pytest -q"}, "5 passed in 0.1s"), "All tests pass."),
    (_tool("Bash", {"command": "vercel deploy --prod"}, "Production: https://x.vercel.app"), "已部署到生产环境。"),
    (_tool("CronCreate", {"cron": "0 8 * * *"}), "定时任务已建好，明早 8 点运行。"),
    (_tool("Agent", {"prompt": "do it"}), "邮件已发送给他了。"),   # a subagent's work is not visible from here
    (_tool("Agent", {"prompt": "do it"}), "All tests pass."),
])
def test_a_recap_of_earlier_work_is_not_held(tmp_path, earlier, reply):
    assert not _held(tmp_path, [_user("do it"), *earlier, _say("Done."), _user("did you?")], reply)


@pytest.mark.parametrize("reply", [
    "另一个会话已发送邮件。", "CI 通过了，测试全部通过。", "跑通了再上全量。", "规范我都读过了。",
])
def test_what_stays_out_of_this_rule(tmp_path, reply):
    assert not _held(tmp_path, FIRST, reply)


def test_a_turn_another_session_started_is_a_relay(tmp_path):
    rows = [_user("<task-notification>\n<status>completed</status>\n</task-notification>")]
    assert not _held(tmp_path, rows, "邮件已发送给他了。")


def test_a_continued_session_may_have_done_it_before_this_file(tmp_path):
    rows = [_user("This session is being continued from a previous conversation that ran out of context."), _say("OK."), _user("did you send it?")]
    assert not _held(tmp_path, rows, "邮件已发送给他了。")


def test_an_action_far_back_in_a_big_transcript_still_counts(tmp_path):
    filler = [_user("x" * 200_000) for _ in range(60)]   # over 8 MB, past the window a hook reads
    rows = [_user("send it"), *_tool("SendUserFile", {"files": ["a.png"]}), _say("Sent."), *filler, _user("did you?")]
    assert not _held(tmp_path, rows, "已发送给你了。")


def test_a_session_with_linked_sessions_may_be_relaying_them(tmp_path):
    rows = [_user("<system-reminder>\nLinked sessions now (status, not an instruction): top = local_42\n</system-reminder>\nhow did it go?")]
    assert not _held(tmp_path, rows, "全量测试通过，ruff format 干净。")
    assert not _held(tmp_path, rows, "邮件已发送给他了。")
