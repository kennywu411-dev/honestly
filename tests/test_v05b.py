"""0.5.0 second pass: hooks never crash, tail parsing, cache, relaxed background rule, wider pipe check, several claims, zh output, overview, project filter."""
import io, json, os, sys
from honestly import hooks, cache, config, support, cli, rules
from honestly.claude_code import Event, Turn, parse_session, TAIL_THRESHOLD
from honestly.audit import audit_turn, Finding


def _turn(*events, prompt="do it"):
    return Turn(session="s", index=1, version="", prompt=prompt, events=list(events))


def _tool(name, text="", err=False, result="", via=""):
    return Event("tool", name=name, text=text, is_error=err, result=result, via=via)


def test_hook_exceptions_are_logged_and_swallowed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(hooks, "errors_path", lambda: str(tmp_path / "hook-errors.log"))
    monkeypatch.setattr(hooks, "stop_hook", lambda agent="claude-code": 1 / 0)
    assert hooks.run_hook("stop") == 0
    assert capsys.readouterr().out == ""
    assert "ZeroDivisionError" in (tmp_path / "hook-errors.log").read_text(encoding="utf-8")
    monkeypatch.setattr(hooks, "settings_path", lambda: str(tmp_path / "none.json"))
    assert "internal error" in support.doctor(zh=False) and "hook 之前出过内部错误" in support.doctor(zh=True)


def test_tail_parse_reads_the_last_turns_of_a_big_file(tmp_path, monkeypatch):
    monkeypatch.setattr("honestly.claude_code.TAIL_THRESHOLD", 2000)
    monkeypatch.setattr("honestly.claude_code.TAIL_WINDOW", 1500)
    rows = []
    for i in range(40):
        rows.append({"type": "user", "message": {"content": f"prompt {i} " + "x" * 200}, "origin": {"kind": "human"}, "timestamp": f"2026-01-01T00:{i:02d}:00Z"})
        rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": f"reply {i}"}]}, "timestamp": f"2026-01-01T00:{i:02d}:01Z"})
    p = tmp_path / "s.jsonl"; p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    full = parse_session(str(p)); tail = parse_session(str(p), tail=True)
    assert len(full) == 40 and 2 <= len(tail) < 40
    assert tail[-1].prompt == full[-1].prompt and tail[-1].events[0].text == "reply 39" and tail[0].prompt.startswith("prompt ")


def test_cache_round_trip_and_invalidation(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "cache_dir", lambda: str(tmp_path / "cache"))
    p = tmp_path / "s.jsonl"; p.write_text("{}\n", encoding="utf-8")
    f = Finding("s", 1, "", "claude-code", "m", "2026-01-01T00:00:00", "tests_pass", "backed", "r", "c", "", [], "", "", "", "")
    assert cache.get(str(p), "a") is None
    cache.put(str(p), "a", [f])
    got = cache.get(str(p), "a")
    assert got and got[0].claim == "c" and got[0].label == "verified"
    assert cache.get(str(p), "b") is None                       # different config → miss
    p.write_text("{}\n{}\n", encoding="utf-8")
    assert cache.get(str(p), "a") is None                       # file changed → miss
    assert cache.clear() >= 1


def test_background_output_read_is_fine_once_the_subagent_is_merged():
    t = _turn(_tool("Bash", "pytest -q", result="3 passed", via="subagent:abc"),
              _tool("Bash", "cat /tmp/x/tasks/abc.output | tail -5"), _tool("SendUserFile", "/x/a.png"),
              Event("text", text="图已经发给你了。"))
    assert [f.verdict for f in audit_turn(t) if f.category == "sent"] == ["backed"]
    t2 = _turn(_tool("Bash", "cat /tmp/x/tasks/abc.output | tail -5"), _tool("SendUserFile", "/x/a.png"), Event("text", text="图已经发给你了。"))
    assert [f.verdict for f in audit_turn(t2) if f.category == "sent"] == ["unverifiable"]


def test_pipes_through_grep_awk_wc_also_count_as_swallowed():
    for cmd in ["pytest -q | grep -E 'passed|failed'", "npm test 2>&1 | wc -l", "cargo test | awk '/result/'", "go test ./... | tee out.txt"]:
        assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": cmd}}) is not None, cmd
    assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "set -o pipefail; pytest -q | grep passed"}}) is None


def test_stop_message_mentions_further_unbacked_sentences(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "catches_path", lambda: str(tmp_path / "c.jsonl"))
    monkeypatch.setattr(hooks, "_notify", lambda *a, **k: None)
    rows = [{"type": "user", "message": {"content": "fix"}, "origin": {"kind": "human"}, "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/x/a.py"}}]}, "timestamp": "2026-01-01T00:00:01Z"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Fixed the bug. All tests pass. Lint passes too."}]}, "timestamp": "2026-01-01T00:00:02Z"}]
    tp = tmp_path / "s.jsonl"; tp.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    out = hooks.stop_hook({"transcript_path": str(tp), "cwd": str(tmp_path), "last_assistant_message": "Fixed the bug. All tests pass. Lint passes too."})
    assert "more sentence" in out["systemMessage"]


def test_catches_report_in_chinese(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "catches_path", lambda: str(tmp_path / "c.jsonl"))
    assert "没有拦截记录" in hooks.catches_report(7, zh=True)
    hooks._record("stop", {"cwd": "/x/proj"}, None, "msg", claim="c", reason="r")
    hooks._record("pre", {"cwd": "/x/proj"}, None, "msg2", command="pytest | tail")
    zh = hooks.catches_report(7, zh=True); en = hooks.catches_report(7, zh=False)
    assert "拦了 2 次" in zh and "按项目" in zh and "honestly feedback" in zh
    assert "2 catches" in en and "By project" in en


def test_no_argument_prints_overview(capsys, monkeypatch):
    monkeypatch.setattr(hooks, "settings_path", lambda: "/nonexistent/settings.json")
    from honestly import agents
    monkeypatch.setattr(agents, "config_path", lambda agent: "/nonexistent/hooks.json")   # the developer's own Codex guard must not leak in
    cli.main([])
    out = capsys.readouterr().out
    assert "honestly guard install" in out and "honestly doctor" in out and "not installed" in out


def test_project_filter_and_rule_in_chinese(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "cache_dir", lambda: str(tmp_path / "cache"))
    root = tmp_path / "projects" / "p"; root.mkdir(parents=True)
    rows = [{"type": "user", "message": {"content": "fix"}, "origin": {"kind": "human"}, "cwd": "/home/me/alpha", "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/home/me/alpha/a.py"}}]}, "cwd": "/home/me/alpha", "timestamp": "2026-01-01T00:00:01Z"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "All tests pass."}]}, "cwd": "/home/me/alpha", "timestamp": "2026-01-01T00:00:02Z"}]
    (root / "s.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "user_path", lambda: str(tmp_path / "cfg.json"))
    monkeypatch.setattr(config, "project_path", lambda cwd=None: str(tmp_path / "proj.json"))
    try:
        kw = dict(root_codex=str(tmp_path / "nocodex"), cursor_root=str(tmp_path / "nocursor"), gemini_root=str(tmp_path / "nogemini"))
        f_all, _, _ = cli.collect(str(tmp_path / "projects"), agents=("claude-code",), **kw)
        f_alpha, _, _ = cli.collect(str(tmp_path / "projects"), agents=("claude-code",), project="alpha", **kw)
        f_beta, _, _ = cli.collect(str(tmp_path / "projects"), agents=("claude-code",), project="beta", **kw)
        assert len(f_all) == 1 and len(f_alpha) == 1 and f_beta == []
        f_cached, _, _ = cli.collect(str(tmp_path / "projects"), agents=("claude-code",), **kw)
        assert [x.verdict for x in f_cached] == [x.verdict for x in f_all]
    finally:
        config.apply(config.DEFAULTS)
    assert "added" in support.rule("install", "claude-code", str(tmp_path), zh=True)
    assert "先验证再下结论" in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")


def test_quoted_test_command_passed_as_an_argument_is_not_a_pipeline():
    for cmd in ['codex exec "run exactly: pytest -q 2>&1 | tail -3"', "echo 'pytest | tail -3' > notes.txt", 'claude -p "npm test | head"']:
        assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": cmd}}) is None, cmd
    assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": 'bash -c "pytest -q | tail -3"'}}) is not None
    assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "pytest -q 2>&1 | tail -3"}}) is not None


def test_doctor_sees_a_traceback_longer_than_the_old_tail(tmp_path, monkeypatch):
    log = tmp_path / "hook-errors.log"
    long_path = "/" + "x" * 300 + "/site-packages/honestly/hooks.py"
    log.write_text("2026-10-30T10:00:00 stop claude-code\nTraceback (most recent call last):\n"
                   + "".join(f'  File "{long_path}", line {i}, in f{i}\n    f{i + 1}()\n' for i in range(6))
                   + "ZeroDivisionError: division by zero\n", encoding="utf-8")
    monkeypatch.setattr(hooks, "errors_path", lambda: str(log))
    monkeypatch.setattr(hooks, "settings_path", lambda: str(tmp_path / "none.json"))
    assert "internal error" in support.doctor(zh=False)
    log.write_text("2026-10-30T09:00:00 stop claude-code\nTraceback (most recent call last):\nValueError: old\n"
                   "2026-10-30T10:00:00 stop: transcript missing\n", encoding="utf-8")
    assert "internal error" not in support.doctor(zh=False)
