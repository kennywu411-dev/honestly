"""0.5.0: config knobs, doctor/feedback, subagent transcripts, background task output."""
import json, os
from honestly import config, rules, hooks, support
from honestly.claude_code import Event, Turn, parse_session
from honestly.audit import audit_turn


def _turn(*events, prompt="do it"):
    return Turn(session="s", index=1, version="", prompt=prompt, events=list(events))


def _tool(name, text="", err=False, result=""):
    return Event("tool", name=name, text=text, is_error=err, result=result)


def _cfg_home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "user_path", lambda: str(tmp_path / "config.json"))
    monkeypatch.setattr(config, "project_path", lambda cwd=None: str(tmp_path / "proj" / ".honestly.json"))
    yield_cfg = lambda: config.load()
    return yield_cfg


# ------------------------------------------------------------------ config
def test_ignore_phrase_and_disabled_category(tmp_path, monkeypatch):
    load = _cfg_home(tmp_path, monkeypatch)
    try:
        assert rules.find_claims("Fixed bed reactor results are fixed.")
        config.add_to("ignore", "fixed bed reactor")
        config.apply(load())
        assert not rules.find_claims("Fixed bed reactor results are fixed.")
        assert rules.find_claims("对比图已发给你了。")
        config.add_to("off", "sent"); config.apply(load())
        assert not rules.find_claims("对比图已发给你了。")
    finally:
        config.apply(config.DEFAULTS)


def test_custom_verify_command_counts_as_a_test(tmp_path, monkeypatch):
    load = _cfg_home(tmp_path, monkeypatch)
    try:
        t = _turn(_tool("Edit", "/x/a.py"), _tool("Bash", "make verify", result="all 12 checks passed"), Event("text", text="改好了，测试通过。"))
        assert [f.verdict for f in audit_turn(t) if f.category == "tests_pass"] == ["unbacked"]
        config.add_to("verify_commands", "make verify"); config.apply(load())
        assert [f.verdict for f in audit_turn(t) if f.category == "tests_pass"] == ["backed"]
        assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "make verify | tail -3"}, "cwd": str(tmp_path)}) is not None
    finally:
        config.apply(config.DEFAULTS)


def test_strictness_changes_what_guard_blocks(tmp_path, monkeypatch):
    load = _cfg_home(tmp_path, monkeypatch)
    monkeypatch.setattr(hooks, "_notify", lambda *a, **k: None)
    try:
        tp = tmp_path / "s.jsonl"
        rows = [{"type": "user", "message": {"content": "fix"}, "origin": {"kind": "human"}, "timestamp": "2026-01-01T00:00:00Z"},
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/x/a.py"}}]}, "timestamp": "2026-01-01T00:00:01Z"},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Fixed. All tests pass."}]}, "timestamp": "2026-01-01T00:00:02Z"}]
        tp.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        data = {"transcript_path": str(tp), "cwd": str(tmp_path / "proj"), "last_assistant_message": "Fixed. All tests pass."}
        assert hooks.stop_hook(dict(data))["decision"] == "block"
        config.set_value("strictness", "lenient")
        assert hooks.stop_hook(dict(data)) is None                       # unbacked is not blocked when lenient
        assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "pytest | tail"}, "cwd": str(tmp_path / "proj")}) is None
        config.set_value("strictness", "strict"); config.set_value("language", "en")
        out = hooks.stop_hook(dict(data))
        assert out["decision"] == "block" and "stepped in" in out["systemMessage"]   # language forced to English
        assert "strict" in config.show()
    finally:
        config.apply(config.DEFAULTS)


def test_project_config_merges_on_top_of_user_config(tmp_path, monkeypatch):
    _cfg_home(tmp_path, monkeypatch)
    config.add_to("ignore", "alpha"); config.add_to("ignore", "beta", project=True)
    cfg = config.load()
    assert cfg["ignore"] == ["alpha", "beta"]
    assert "not in ignore" in config.remove_from("ignore", "zzz")


# ---------------------------------------------------------- doctor / feedback
def test_doctor_self_test_blocks_and_report_lists_problems(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "settings_path", lambda: str(tmp_path / "settings.json"))
    results = support.self_test()
    assert [n for n, ok, _ in results if ok] == ["code", "non-code"]
    text = support.doctor()
    assert "self-test" in text and "blocked" in text
    assert "guard hooks not installed" in text and "honestly guard install" in text


def test_feedback_redacts_and_links(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "catches_path", lambda: str(tmp_path / "c.jsonl"))
    assert "no catches" in support.feedback()
    hooks._record("stop", {"cwd": os.path.expanduser("~/secret/proj")}, None, "msg", claim="tests pass", reason="no check",
                  tools=["Bash: curl -H 'Authorization: abcdefghijklmnopqrstuvwxyz0123456789ABCDEF' me@example.com"])
    out = support.feedback(1, issue_url=True)
    assert "~/secret/proj" not in out and os.path.expanduser("~") not in out
    assert "<redacted>" in out and "<email>" in out and "issues/new?" in out
    assert "pick 1" in support.feedback(5)


# ------------------------------------------------------------- subagents
def _write(p, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_subagent_test_run_backs_the_parent_claim(tmp_path):
    main = tmp_path / "s.jsonl"
    _write(main, [
        {"type": "user", "message": {"content": "fix"}, "origin": {"kind": "human"}, "timestamp": "2026-01-01T00:00:00Z"},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "e1", "name": "Edit", "input": {"file_path": "/x/a.py"}}]}, "timestamp": "2026-01-01T00:00:01Z"},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "ag1", "name": "Agent", "input": {"prompt": "run the tests"}}]}, "timestamp": "2026-01-01T00:00:02Z"},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "ag1", "content": "done"}]}, "timestamp": "2026-01-01T00:00:09Z"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Fixed, all tests pass."}]}, "timestamp": "2026-01-01T00:00:10Z"}])
    sub = tmp_path / "s" / "subagents" / "agent-abc.jsonl"
    _write(sub, [
        {"type": "user", "isSidechain": True, "agentId": "abc", "message": {"content": "run the tests"}, "timestamp": "2026-01-01T00:00:03Z"},
        {"type": "assistant", "isSidechain": True, "agentId": "abc", "message": {"content": [{"type": "tool_use", "id": "s1", "name": "Bash", "input": {"command": "pytest -q"}}]}, "timestamp": "2026-01-01T00:00:04Z"},
        {"type": "user", "isSidechain": True, "agentId": "abc", "message": {"content": [{"type": "tool_result", "tool_use_id": "s1", "content": "5 passed in 0.2s"}]}, "timestamp": "2026-01-01T00:00:05Z"}])
    (tmp_path / "s" / "subagents" / "agent-abc.meta.json").write_text(json.dumps({"toolUseId": "ag1", "requestShape": "foreground"}))
    turns = parse_session(str(main))
    names = [e.name for e in turns[0].events if e.kind == "tool"]
    assert names == ["Edit", "Agent:read", "Bash"] and turns[0].events[2].via == "subagent:abc"
    f = [f for f in audit_turn(turns[0]) if f.category == "tests_pass"][0]
    assert f.verdict == "backed" and any("[subagent]" in t for t in f.tools_after_edit)
    # without the subagent file the Agent call stays opaque
    plain = parse_session(str(main), subagents=False)
    assert [f.verdict for f in audit_turn(plain[0]) if f.category == "tests_pass"] == ["unverifiable"]


def test_background_task_output_file_is_read_as_the_result(tmp_path):
    out = tmp_path / "tasks" / "b1.output"; out.parent.mkdir(); out.write_text("....\n4 passed in 0.1s\n")
    main = tmp_path / "s.jsonl"
    _write(main, [
        {"type": "user", "message": {"content": "fix"}, "origin": {"kind": "human"}, "timestamp": "2026-01-01T00:00:00Z"},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "e1", "name": "Edit", "input": {"file_path": "/x/a.py"}}]}, "timestamp": "2026-01-01T00:00:01Z"},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "pytest -q", "run_in_background": True}}]}, "timestamp": "2026-01-01T00:00:02Z"},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "b1", "content": f"Command running in background with ID: b1. Output is being written to: {out}"}]}, "timestamp": "2026-01-01T00:00:03Z"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "All 4 tests pass."}]}, "timestamp": "2026-01-01T00:00:10Z"}])
    turns = parse_session(str(main))
    assert "4 passed" in turns[0].events[1].result
    assert [f.verdict for f in audit_turn(turns[0]) if f.category == "tests_pass"] == ["backed"]


def test_user_as_subject_is_not_a_claim():
    for s in ["User sent a message instead of answering; I'll wait.", "你发来的截图我看了。", "The maintainers pushed a fix upstream."]:
        assert not rules.find_claims(s), s
