import json, os, tempfile
from honestly import codex
from honestly.audit import audit_turns

def _write(lines):
    d = tempfile.mkdtemp(); p = os.path.join(d, "rollout-2026-10-27T00-00-00-abc.jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        for l in lines: fh.write(json.dumps(l, ensure_ascii=False) + "\n")
    return p

def test_codex_turns_tools_and_claims():
    lines = [
        {"type": "turn_context", "payload": {"model": "gpt-6-astra"}},
        {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage", "content": [{"type": "text", "text": "fix the bug"}]}}},
        {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "apply_patch", "call_id": "c1", "input": "*** Begin Patch\n*** Update File: src/app.py\n@@\n-a\n+b\n*** End Patch"}},
        {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1", "output": [{"type": "input_text", "text": "Done"}]}},
        {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "call_id": "c2", "input": "text(await tools.exec_command({cmd:\"pytest -q\", yield_time_ms: 1000}))"}},
        {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c2", "output": [{"type": "input_text", "text": "Script completed\nOutput:\n12 passed in 0.3s"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Fixed. All 12 tests pass."}]}},
    ]
    turns = codex.parse_session(_write(lines))
    assert len(turns) == 1 and turns[0].agent == "codex" and turns[0].model == "gpt-6-astra"
    names = [e.name for e in turns[0].events if e.kind == "tool"]
    assert names == ["Edit", "Bash"]
    assert turns[0].events[1].text == "pytest -q" and "12 passed" in turns[0].events[1].result
    f = [x for x in audit_turns(turns) if x.category == "tests_pass"]
    assert f and f[0].verdict == "backed"

def test_codex_unbacked_when_no_test_after_patch():
    lines = [
        {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage", "content": [{"type": "text", "text": "go"}]}}},
        {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "apply_patch", "call_id": "c1", "input": "*** Update File: src/app.py\n"}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "All tests pass now."}]}},
    ]
    f = audit_turns(codex.parse_session(_write(lines)))
    assert f and f[0].verdict == "unbacked"
