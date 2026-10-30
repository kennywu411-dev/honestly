import json, os, tempfile
from honestly import hooks

def _transcript(records):
    d = tempfile.mkdtemp(); p = os.path.join(d, "sess.jsonl")
    with open(p, "w") as fh:
        for r in records: fh.write(json.dumps(r) + "\n")
    return p

def test_stop_hook_blocks_stale_claim():
    p = _transcript([
        {"type": "user", "message": {"role": "user", "content": "fix it"}, "origin": {"kind": "human"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/p/src/app.py"}}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
    ])
    out = hooks.stop_hook({"transcript_path": p, "last_assistant_message": "Fixed the bug, all tests pass.", "stop_hook_active": False})
    assert out and out["decision"] == "block" and "tests pass" in out["reason"].lower()

def test_stop_hook_allows_verified_claim():
    p = _transcript([
        {"type": "user", "message": {"role": "user", "content": "fix it"}, "origin": {"kind": "human"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/p/src/app.py"}}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "pytest -q"}}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t2", "content": "5 passed in 0.1s"}]}},
    ])
    assert hooks.stop_hook({"transcript_path": p, "last_assistant_message": "All 5 tests pass.", "stop_hook_active": False}) is None

def test_stop_hook_fires_once():
    assert hooks.stop_hook({"transcript_path": "/nonexistent", "last_assistant_message": "tests pass", "stop_hook_active": True}) is None

def test_pre_hook_denies_piped_test():
    out = hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "npm test 2>&1 | tail -5"}})
    assert out and out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "set -o pipefail; npm test 2>&1 | tail -5"}}) is None
    assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "ls | tail -5"}}) is None

def test_guard_dry_run_adds_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "settings_path", lambda: str(tmp_path / "settings.json"))
    raw = hooks.guard("install", dry_run=True)
    assert raw.startswith("honestly guard would write")
    out = json.loads(raw[raw.index("{"):])
    assert "Stop" in out["hooks"] and "PreToolUse" in out["hooks"]
    assert not (tmp_path / "settings.json").exists()

def test_pre_hook_ignores_ci_log_reads():
    assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "gh run view 123 --log-failed | head -20"}}) is None
