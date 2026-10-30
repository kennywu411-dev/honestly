"""Codex / Cursor / Gemini CLI: transcript parsing, hook payloads in and out, installers."""
import json, os
from honestly import agents, hooks, config
from honestly.audit import audit_turn


def test_cursor_transcript_parses_tool_inputs_without_outputs(tmp_path):
    p = tmp_path / "c.jsonl"
    rows = [{"role": "user", "message": {"content": [{"type": "text", "text": "<user_query>fix the bug</user_query>"}]}},
            {"role": "assistant", "message": {"content": [{"type": "tool_use", "name": "edit_file", "input": {"target_file": "src/a.py", "code_edit": "x"}}]}},
            {"role": "assistant", "message": {"content": [{"type": "tool_use", "name": "run_terminal_cmd", "input": {"command": "pytest -q"}}]}},
            {"role": "assistant", "message": {"content": [{"type": "text", "text": "Fixed, tests pass."}]}}]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    turns = agents.cursor_parse(str(p))
    assert turns[0].prompt == "fix the bug" and turns[0].agent == "cursor"
    assert [(e.name, e.text) for e in turns[0].events if e.kind == "tool"] == [("Edit", "src/a.py"), ("Bash", "pytest -q")]
    v = [f.verdict for f in audit_turn(turns[0]) if f.category == "tests_pass"]
    assert v == ["unverifiable"]                      # a test ran but Cursor keeps no output: cannot be contradicted, never blocked
    rows2 = rows[:2] + rows[3:]
    p.write_text("\n".join(json.dumps(r) for r in rows2) + "\n")
    assert [f.verdict for f in audit_turn(agents.cursor_parse(str(p))[0]) if f.category == "tests_pass"] == ["unbacked"]


def test_gemini_transcript_jsonl_and_legacy_json(tmp_path):
    recs = [{"sessionId": "s", "projectHash": "h", "directories": ["/x/proj"], "startTime": "t"},
            {"id": "1", "timestamp": "2026-01-01T00:00:00Z", "type": "user", "content": [{"text": "fix it"}]},
            {"id": "2", "timestamp": "2026-01-01T00:00:01Z", "type": "gemini", "model": "gemini-3", "content": "Fixed. Tests pass.",
             "toolCalls": [{"name": "write_file", "args": {"file_path": "/x/proj/a.py"}, "result": "ok", "status": "success"},
                           {"name": "run_shell_command", "args": {"command": "pytest -q"}, "result": {"llmContent": "1 failed, 2 passed"}, "status": "success"}]},
            {"$patch": {"x": 1}}]
    p = tmp_path / "session-1.jsonl"; p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    turns = agents.gemini_parse(str(p))
    assert turns[0].agent == "gemini" and turns[0].model == "gemini-3" and turns[0].project == "/x/proj"
    tools = [e for e in turns[0].events if e.kind == "tool"]
    assert [(e.name, e.text) for e in tools] == [("Edit", "/x/proj/a.py"), ("Bash", "pytest -q")] and "1 failed" in tools[1].result
    assert [f.verdict for f in audit_turn(turns[0]) if f.category == "tests_pass"] == ["contradicted"]
    legacy = tmp_path / "session-2.json"; legacy.write_text(json.dumps({"messages": recs}))
    assert len(agents.gemini_parse(str(legacy))) == 1


def test_normalize_and_emit_per_agent():
    d = agents.normalize("cursor", "pre", {"command": "pytest | tail", "workspace_roots": ["/w"]})
    assert d["tool_name"] == "Bash" and d["tool_input"]["command"] == "pytest | tail" and d["cwd"] == "/w"
    assert agents.normalize("cursor", "stop", {"loop_count": 1})["stop_hook_active"] is True
    d = agents.normalize("codex", "pre", {"tool_name": "shell", "tool_input": {"command": ["pytest", "-q"]}})
    assert d["tool_input"]["command"] == "pytest -q"
    d = agents.normalize("gemini", "stop", {"prompt_response": [{"text": "done"}]})
    assert d["last_assistant_message"] == "done"
    assert set(agents.emit("cursor", "stop", "p", "i")) == {"followup_message"}
    assert agents.emit("cursor", "pre", "p", "i")["permission"] == "deny"
    assert agents.emit("gemini", "stop", "p", "i")["decision"] == "deny"
    assert agents.emit("codex", "stop", "p", "i")["decision"] == "block"
    assert agents.emit("codex", "pre", "p", "i")["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_pre_hook_denies_for_cursor_and_codex_payloads(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "catches_path", lambda: str(tmp_path / "c.jsonl"))
    monkeypatch.setattr(hooks, "_notify", lambda *a, **k: None)
    out = hooks.pre_hook({"command": "npm test | tail -3", "workspace_roots": [str(tmp_path)]}, agent="cursor")
    assert out["permission"] == "deny" and "Cursor" in out["user_message"]
    out = hooks.pre_hook({"tool_name": "exec_command", "tool_input": {"cmd": "cargo test 2>&1 | head"}, "cwd": str(tmp_path), "model": "gpt-5"}, agent="codex")
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny" and "Codex (gpt-5)" in out["systemMessage"]
    assert hooks.pre_hook({"command": "ls | head"}, agent="cursor") is None


def test_stop_hook_reads_a_gemini_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "catches_path", lambda: str(tmp_path / "c.jsonl"))
    monkeypatch.setattr(hooks, "_notify", lambda *a, **k: None)
    recs = [{"id": "1", "timestamp": "2026-01-01T00:00:00Z", "type": "user", "content": "fix it"},
            {"id": "2", "timestamp": "2026-01-01T00:00:01Z", "type": "gemini", "model": "gemini-3", "content": "Fixed. All tests pass.",
             "toolCalls": [{"name": "write_file", "args": {"file_path": "/x/a.py"}, "result": "ok", "status": "success"}]}]
    p = tmp_path / "session-1.jsonl"; p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    out = hooks.stop_hook({"transcript_path": str(p), "cwd": str(tmp_path), "prompt_response": "Fixed. All tests pass."}, agent="gemini")
    assert out["decision"] == "deny" and "Gemini CLI (gemini-3)" in out["systemMessage"]
    rows = [json.loads(l) for l in open(tmp_path / "c.jsonl", encoding="utf-8")]
    assert rows[0]["agent"] == "gemini"


def test_installers_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(agents, "config_path", lambda agent: str(tmp_path / f"{agent}.json"))
    (tmp_path / "cursor.json").write_text(json.dumps({"version": 1, "hooks": {"stop": [{"command": "other.sh"}]}}))
    for agent in ("codex", "cursor", "gemini"):
        assert "installed" in agents.guard(agent, "install", "/bin/honestly")
        assert set(agents.installed(agent)) == set(agents.entries(agent, "/bin/honestly"))
        assert "not installed" in agents.guard(agent, "uninstall", "/bin/honestly") or agents.installed(agent) == []
    cur = json.loads((tmp_path / "cursor.json").read_text())
    assert cur["hooks"]["stop"] == [{"command": "other.sh"}]           # someone else's hook survives install + uninstall
    assert "would write" in agents.guard("codex", "install", "/bin/honestly", dry_run=True)
    assert "not installed" in agents.guard("gemini", "status", "/bin/honestly")
