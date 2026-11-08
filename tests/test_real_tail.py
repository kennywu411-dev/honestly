"""A big transcript is read from its last prompts on. The answer has to be the same as reading all of it, in the shapes the real CLIs write."""
import json
import os

import pytest

from honestly import agents, claude_code
from real_fixture import cut, load
from test_real_turns import held, stop

FILLER = "padding " * 400


def _pad(path: str, cli: str, size: int = 9 * 1024 * 1024) -> None:
    """Put an earlier, finished turn of `size` bytes in front of what the CLI recorded."""
    with open(path, encoding="utf-8") as fh:
        rows = fh.read().splitlines(keepends=True)
    head, body = (rows[:1], rows[1:]) if cli == "gemini" else ([], rows)
    if cli == "claude":
        first = [{"type": "user", "origin": {"kind": "human"}, "timestamp": "2026-01-01T00:00:00Z", "message": {"role": "user", "content": "an earlier question"}}]
        one = {"type": "assistant", "timestamp": "2026-01-01T00:00:01Z", "message": {"role": "assistant", "model": "m", "content": [{"type": "text", "text": FILLER}]}}
    elif cli == "codex":
        first = [{"timestamp": "2026-01-01T00:00:00Z", "type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage", "content": [{"type": "text", "text": "an earlier question"}]}}}]
        one = {"timestamp": "2026-01-01T00:00:01Z", "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": FILLER}]}}
    else:
        first = [{"id": "early", "timestamp": "2026-01-01T00:00:00Z", "type": "user", "content": [{"text": "an earlier question"}]}]
        one = {"timestamp": "2026-01-01T00:00:01Z", "type": "gemini", "content": FILLER, "model": "m"}
    filler = []
    for i in range(size // len(FILLER)):
        filler.append(json.dumps(dict(one, id=f"f{i}"), ensure_ascii=False) + "\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(head + [json.dumps(r) + "\n" for r in first] + filler + body)


CASES = [
    ("claude", "12c", "All tests pass", "claude-code", "All tests pass.", True),
    ("claude", "12d", "All 5 tests pass", "claude-code", "All 5 tests pass.", False),
    ("claude", "07a", "not yet verified", "claude-code", "Changed app.py; not yet verified.", False),
    ("claude", "08b", "All tests pass", "claude-code", "All tests pass.", True),
    ("codex", "09e", "All 5 tests pass", "codex", "All 5 tests pass.", True),
    ("codex", "09f", "All 5 tests pass", "codex", "All 5 tests pass.", False),
    ("codex", "07a", "not yet verified", "codex", "Changed app.py; not yet verified.", False),
    ("codex", "08a", "All 5 tests pass", "codex", "All 5 tests pass.", False),
    ("gemini", "12e", "All tests pass", "gemini", "All tests pass.", True),
    ("gemini", "07g", "I changed app.py", "gemini", "All tests pass.\nI changed app.py; not verified.", False),
    ("gemini", "08a", "All 5 tests pass", "gemini", "All 5 tests pass.", False),
    ("gemini", "09b", "All 5 tests pass", "gemini", "All 5 tests pass.", True),
]


@pytest.mark.parametrize("cli,name,until,agent,reply,expected", CASES, ids=[f"{c[0]}-{c[1]}" for c in CASES])
def test_the_tail_decides_as_the_whole_file_does(tmp_path, cli, name, until, agent, reply, expected):
    p = load(tmp_path, cli, name, until)
    _pad(p, cli)
    assert os.path.getsize(p) > claude_code.TAIL_THRESHOLD
    assert held(stop(p, reply, agent)) is expected
    tail, whole = agents.parser_for(agent, tail=True)(p), agents.parser_for(agent)(p)
    assert tail[-1].prompt == whole[-1].prompt
    assert [e.text for e in tail[-1].events if e.kind == "tool"] == [e.text for e in whole[-1].events if e.kind == "tool"]
