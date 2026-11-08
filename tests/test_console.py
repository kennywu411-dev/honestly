"""What the hooks print has to reach the assistant whatever the console or pipe can encode: a crash while printing loses the hold."""
import json
import os
import subprocess
import sys

import pytest

RUN = "from honestly import hooks; import sys; sys.exit(hooks.run_hook(%r))"


def _hook(which, data, tmp_path, encoding):
    env = dict(os.environ, PYTHONIOENCODING=encoding, PYTHONUTF8="0", HOME=str(tmp_path), USERPROFILE=str(tmp_path), PYTHONPATH=os.pathsep.join(p for p in sys.path if p))
    r = subprocess.run([sys.executable, "-c", RUN % which], input=json.dumps(data), capture_output=True, text=True, encoding="ascii", errors="replace", env=env, timeout=60)
    assert r.returncode == 0, r.stderr[-300:]
    assert "UnicodeEncodeError" not in r.stderr
    return json.loads(r.stdout)


def _transcript(tmp_path):
    rows = [{"type": "user", "message": {"role": "user", "content": "\u4fee\u4e00\u4e0b"}, "origin": {"kind": "human"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t0", "name": "Edit", "input": {"file_path": "/p/src/app.py"}}]}},
            {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t0", "content": "ok"}]}}]
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return str(p)


@pytest.mark.parametrize("encoding", ["cp1252", "ascii", "utf-8"])
@pytest.mark.parametrize("cmd", ["pytest | head", "pytest \ud800 | head", "pytest \x00 | head", "pytest \u6d4b\u8bd5 | head"], ids=["plain", "lone surrogate", "null byte", "chinese"])
def test_a_refused_command_is_refused_on_any_console(cmd, encoding, tmp_path):
    out = _hook("pre", {"tool_name": "Bash", "tool_input": {"command": cmd}, "session_id": "s"}, tmp_path, encoding)
    assert "deny" in json.dumps(out)


@pytest.mark.parametrize("encoding", ["cp1252", "ascii", "utf-8"])
@pytest.mark.parametrize("reply", ["All tests pass.", "\u6d4b\u8bd5\u5168\u90e8\u901a\u8fc7\u3002", "All tests pass \ud800."], ids=["english", "chinese", "lone surrogate"])
def test_a_held_reply_is_held_on_any_console(reply, encoding, tmp_path):
    out = _hook("stop", {"transcript_path": _transcript(tmp_path), "last_assistant_message": reply, "stop_hook_active": False, "session_id": "s"}, tmp_path, encoding)
    assert out.get("decision") == "block"
