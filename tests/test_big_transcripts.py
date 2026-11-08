"""The hooks run under a time limit. A huge transcript must cost what its last turns cost, and nothing the turn did may be lost to save time."""
import json
import os
import time

import pytest

from honestly import agents, claude_code, codex, hooks

FILLER = "x" * 2000
SAY = "All tests pass."


def _user(text, ts="2026-01-01T00:00:00Z"):
    return {"type": "user", "message": {"role": "user", "content": text}, "origin": {"kind": "human"}, "cwd": "/work/p", "timestamp": ts}


def _tool(i, name="Bash", inp=None, out=FILLER, ts=None):
    ts = ts or f"2026-01-01T01:{i // 60 % 60:02d}:{i % 60:02d}Z"
    inp = inp if inp is not None else {"command": "ls"}
    return [{"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}]}, "cwd": "/work/p", "timestamp": ts},
            {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": out}]}, "cwd": "/work/p", "timestamp": ts}]


def _say(text=SAY):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}, "cwd": "/work/p", "timestamp": "2026-01-01T02:00:00Z"}


def _write(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return str(path)


def _one_prompt_rows(calls=5000):
    rows = [_user("fix the bug")] + _tool(0, "Edit", {"file_path": "/work/p/src/app.py"}, "ok")
    for i in range(1, calls):
        rows += _tool(i)
    return rows + [_say()]


def _hold(path, agent="claude-code"):
    return (hooks.stop_hook({"transcript_path": path, "cwd": "/work/p", "last_assistant_message": SAY, "stop_hook_active": False}, agent=agent) or {}).get("decision")


def test_an_edit_at_the_very_start_of_a_long_turn_still_counts(tmp_path):
    path = _write(tmp_path / "s.jsonl", _one_prompt_rows())
    assert os.path.getsize(path) > claude_code.TAIL_THRESHOLD
    assert _hold(path) == "block"


def test_a_long_turn_is_parsed_once(tmp_path, monkeypatch):
    path = _write(tmp_path / "s.jsonl", _one_prompt_rows())
    calls = []
    real = claude_code._parse
    monkeypatch.setattr(claude_code, "_parse", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    turns = claude_code.parse_session(path, tail=True)
    assert len(calls) == 1 and len(turns) == 1 and turns[0].prompt == "fix the bug"


def test_many_turns_cost_only_the_last_two(tmp_path, monkeypatch):
    rows = []
    for t in range(200):
        rows.append(_user(f"turn {t}", ts=f"2026-01-01T00:{t // 60:02d}:{t % 60:02d}Z"))
        for i in range(30):
            rows += _tool(t * 100 + i)
    path = _write(tmp_path / "s.jsonl", rows + [_say()])
    assert os.path.getsize(path) > claude_code.TAIL_THRESHOLD
    read = []
    real = claude_code._records
    monkeypatch.setattr(claude_code, "_records", lambda p, start=0: (read.append(start), real(p, start))[1])
    turns = claude_code.parse_session(path, tail=True)
    assert [t.prompt for t in turns] == ["turn 198", "turn 199"]
    assert read[0] > os.path.getsize(path) * 0.9


def test_a_tool_result_quoting_a_transcript_does_not_shorten_the_turn(tmp_path):
    quoted = json.dumps(_user("fake prompt")) + "\n"
    rows = [_user("real prompt")] + _tool(0, "Edit", {"file_path": "/work/p/src/app.py"}, "ok")
    for i in range(1, 5000):
        rows += _tool(i, out=quoted * 40)
    path = _write(tmp_path / "s.jsonl", rows + [_say()])
    turns = claude_code.parse_session(path, tail=True)
    assert [t.prompt for t in turns] == ["real prompt"]
    assert _hold(path) == "block"


def test_a_user_row_that_is_not_a_prompt_only_means_reading_further(tmp_path):
    rows = [_user("first"), _user("second")] + _tool(0, "Edit", {"file_path": "/work/p/src/app.py"}, "ok")
    for i in range(1, 5000):
        rows += _tool(i)
    rows.append({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "a note"}]}, "cwd": "/work/p", "timestamp": "2026-01-01T01:59:00Z"})
    rows.append({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "another"}]}, "cwd": "/work/p", "timestamp": "2026-01-01T01:59:30Z"})
    turns = claude_code.parse_session(_write(tmp_path / "s.jsonl", rows + [_say()]), tail=True)
    assert [t.prompt for t in turns] == ["first", "second"]


def _with_subagent(tmp_path, n):
    path = _write(tmp_path / "s.jsonl", [_user("fix", "2026-01-01T00:00:00Z")] + _tool(0, "Edit", {"file_path": "/work/p/a.py"}, "ok", ts="2026-01-01T00:00:01Z") + [_say()])
    sub = tmp_path / "s" / "subagents"
    sub.mkdir(parents=True)
    rows = [{"type": "assistant", "isSidechain": True, "message": {"content": [{"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": "ls"}}]}, "timestamp": "2026-01-01T00:00:03Z"} for i in range(n)]
    _write(sub / "agent-a.jsonl", rows)
    return path


def test_merging_a_big_subagent_takes_linear_time(tmp_path):
    path = _with_subagent(tmp_path, 16000)
    start = time.perf_counter()
    assert _hold(path) == "block"
    assert time.perf_counter() - start < 3.0


def test_subagent_calls_land_where_their_time_says(tmp_path):
    main = [_user("fix", "2026-01-01T00:00:00Z")] + _tool(0, "Bash", {"command": "first"}, "ok", ts="2026-01-01T00:00:10Z") + _tool(1, "Bash", {"command": "second"}, "ok", ts="2026-01-01T00:00:30Z")
    main += [_user("next", "2026-01-01T00:01:00Z")] + _tool(2, "Bash", {"command": "third"}, "ok", ts="2026-01-01T00:01:10Z")
    path = _write(tmp_path / "s.jsonl", main)
    sub = tmp_path / "s" / "subagents"
    sub.mkdir(parents=True)
    def call(i, ts):
        return {"type": "assistant", "isSidechain": True, "message": {"content": [{"type": "tool_use", "id": f"x{i}", "name": "Bash", "input": {"command": f"sub{i}"}}]}, "timestamp": ts}
    _write(sub / "agent-a.jsonl", [call(1, "2026-01-01T00:00:20Z"), call(2, "2026-01-01T00:00:40Z"), call(3, "2026-01-01T00:01:05Z"), call(0, "2025-12-31T23:00:00Z")])
    turns = claude_code.parse_session(path)
    assert [e.text for e in turns[0].events] == ["first", "sub1", "second", "sub2"]
    assert [e.text for e in turns[1].events] == ["sub3", "third"]


def _codex_rows(turns, calls, first_edit=True):
    rows = [{"type": "session_meta", "payload": {"cwd": "/work/p", "model": "gpt-x"}}]
    n = 0
    for t in range(turns):
        rows.append({"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage", "content": [{"text": f"turn {t}"}]}}})
        if t == turns - 1 and first_edit:
            rows.append({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "apply_patch", "call_id": "p", "input": "*** Update File: src/a.py"}})
        for _ in range(calls):
            n += 1
            rows.append({"type": "response_item", "payload": {"type": "function_call", "name": "shell", "call_id": f"c{n}", "arguments": json.dumps({"command": "ls"})}})
            rows.append({"type": "response_item", "payload": {"type": "function_call_output", "call_id": f"c{n}", "output": FILLER}})
    rows.append({"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"text": SAY}]}})
    return rows


def test_codex_reads_only_its_last_turns(tmp_path):
    path = _write(tmp_path / "r.jsonl", _codex_rows(100, 60))
    assert os.path.getsize(path) > claude_code.TAIL_THRESHOLD
    turns = agents.parser_for("codex", tail=True)(path)
    assert [t.prompt for t in turns] == ["turn 98", "turn 99"]
    assert turns[-1].project == "/work/p" and turns[-1].model == "gpt-x"
    assert _hold(path, "codex") == "block"


def test_codex_keeps_a_whole_long_turn(tmp_path):
    path = _write(tmp_path / "r.jsonl", _codex_rows(1, 5000))
    assert [t.prompt for t in agents.parser_for("codex", tail=True)(path)] == ["turn 0"]
    assert _hold(path, "codex") == "block"


def _gemini_rows(turns, calls):
    rows = []
    n = 0
    for t in range(turns):
        rows.append({"type": "user", "id": f"u{t}", "content": f"turn {t}"})
        for _ in range(calls):
            n += 1
            rows.append({"type": "gemini", "id": f"g{n}", "model": "g", "content": "", "toolCalls": [{"name": "run_shell_command", "args": {"command": "ls"}, "result": FILLER, "status": "success"}]})
    return rows


def test_gemini_reads_only_its_last_turns(tmp_path):
    (tmp_path / "chats").mkdir()
    path = _write(tmp_path / "chats" / "session-1.jsonl", _gemini_rows(100, 60))
    assert [t.prompt for t in agents.parser_for("gemini", tail=True)(path)] == ["turn 98", "turn 99"]


def test_cursor_reads_only_its_last_turns(tmp_path):
    rows = []
    for t in range(100):
        rows.append({"role": "user", "message": {"content": f"turn {t}"}})
        rows += [{"role": "assistant", "message": {"content": [{"type": "text", "text": FILLER}]}} for _ in range(60)]
    path = _write(tmp_path / "t.jsonl", rows)
    assert [t.prompt for t in agents.parser_for("cursor", tail=True)(path)] == ["turn 98", "turn 99"]


def test_a_small_file_is_read_whole(tmp_path):
    path = _write(tmp_path / "r.jsonl", _codex_rows(3, 1))
    assert [t.prompt for t in agents.parser_for("codex", tail=True)(path)] == ["turn 0", "turn 1", "turn 2"]


@pytest.mark.parametrize("agent,rows", [("claude-code", _one_prompt_rows), ("codex", lambda: _codex_rows(1, 5000))])
def test_refusing_a_command_reads_only_a_small_tail(tmp_path, monkeypatch, agent, rows):
    path = _write(tmp_path / "s.jsonl", rows())
    asked = []
    real = agents.parser_for
    monkeypatch.setattr(agents, "parser_for", lambda a, tail=False, light=False: (asked.append(light), real(a, tail, light))[1])
    assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "pytest | head"}, "cwd": "/work/p", "transcript_path": path}, agent=agent)
    assert asked == [True]
    start = time.perf_counter()
    real(agent, light=True)(path)
    assert time.perf_counter() - start < 0.5


def test_codex_module_still_parses_from_the_start_by_default(tmp_path):
    path = _write(tmp_path / "r.jsonl", _codex_rows(2, 1))
    assert len(codex.parse_session(path)) == 2
