"""Build big transcripts in each CLI's real record shape (cloned from real recordings of this harness): gen_transcripts.py <dir> <sizes MB...>
Two shapes: many ordinary turns, and one giant turn with no later prompt. The last turn edits, runs nothing, and claims."""
import json, os, sys
out, sizes = sys.argv[1], [int(x) for x in sys.argv[2:]]
os.makedirs(out, exist_ok=True)
PAD = "padding padding padding padding padding padding padding " * 40

def claude_turn(i, prompt=True, proj="/Users/x/proj"):
    ts = f"2026-11-08T12:{i % 60:02d}:{i % 59:02d}.000Z"
    base = {"isSidechain": False, "sessionId": "s", "cwd": proj, "version": "2.1.319", "entrypoint": "cli", "timestamp": ts}
    rows = []
    if prompt:
        rows.append(dict(base, type="user", uuid=f"u{i}", origin={"kind": "human"}, promptSource="typed", turnOrigin="human", message={"role": "user", "content": f"please do step {i}"}))
    rows.append(dict(base, type="attachment", uuid=f"a{i}", attachment={"type": "total_tokens_reminder", "text": PAD[:500]}))
    rows.append(dict(base, type="assistant", uuid=f"t{i}", message={"role": "assistant", "model": "claude-sonnet-5", "content": [{"type": "text", "text": f"Working on step {i}."}]}))
    rows.append(dict(base, type="assistant", uuid=f"b{i}", message={"role": "assistant", "model": "claude-sonnet-5", "content": [{"type": "tool_use", "id": f"toolu_{i}", "name": "Bash", "input": {"command": f"pytest -q tests/test_{i}.py", "description": "run"}}]}))
    rows.append(dict(base, type="user", uuid=f"r{i}", message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"toolu_{i}", "content": (PAD * 2) + "\n5 passed in 0.1s"}]}, toolUseResult={"stdout": PAD}))
    rows.append(dict(base, type="assistant", uuid=f"e{i}", message={"role": "assistant", "model": "claude-sonnet-5", "content": [{"type": "text", "text": f"Step {i} is done, 5 passed."}]}))
    return rows

def claude_tail(proj="/Users/x/proj"):
    ts = "2026-11-08T23:59:00.000Z"
    base = {"isSidechain": False, "sessionId": "s", "cwd": proj, "version": "2.1.319", "entrypoint": "cli", "timestamp": ts}
    return [dict(base, type="user", uuid="ul", origin={"kind": "human"}, promptSource="typed", turnOrigin="human", message={"role": "user", "content": "last step"}),
            dict(base, type="assistant", uuid="wl", message={"role": "assistant", "model": "claude-sonnet-5", "content": [{"type": "tool_use", "id": "toolu_w", "name": "Write", "input": {"file_path": proj + "/app.py", "content": "x = 1\n"}}]}),
            dict(base, type="user", uuid="rl", message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_w", "content": "ok"}]}),
            dict(base, type="assistant", uuid="cl", message={"role": "assistant", "model": "claude-sonnet-5", "content": [{"type": "text", "text": "All tests pass."}]})]

def codex_turn(i, prompt=True):
    ts = f"2026-11-08T12:{i % 60:02d}:{i % 59:02d}.000Z"
    rows = []
    if prompt:
        rows.append({"timestamp": ts, "type": "turn_context", "payload": {"cwd": "/Users/x/proj", "model": "gpt-5.5"}})
        rows.append({"timestamp": ts, "type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage", "content": [{"type": "text", "text": f"please do step {i}"}]}}})
    rows.append({"timestamp": ts, "type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "arguments": json.dumps({"cmd": f"pytest -q tests/test_{i}.py"}), "call_id": f"c{i}"}})
    rows.append({"timestamp": ts, "type": "response_item", "payload": {"type": "function_call_output", "call_id": f"c{i}", "output": "Chunk ID: x\nWall time: 0.1 seconds\nProcess exited with code 0\nOutput:\n" + PAD * 2 + "\n5 passed in 0.1s\n"}})
    rows.append({"timestamp": ts, "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": f"Step {i} is done, 5 passed."}]}})
    return rows

def codex_tail():
    ts = "2026-11-08T23:59:00.000Z"
    return [{"timestamp": ts, "type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage", "content": [{"type": "text", "text": "last step"}]}}},
            {"timestamp": ts, "type": "response_item", "payload": {"type": "custom_tool_call", "name": "apply_patch", "input": "*** Begin Patch\n*** Update File: app.py\n@@\n-x = 0\n+x = 1\n*** End Patch\n", "call_id": "cw"}},
            {"timestamp": ts, "type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "cw", "output": "Exit code: 0\nOutput:\nSuccess."}},
            {"timestamp": ts, "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "All tests pass."}]}}]

def gemini_turn(i, prompt=True):
    ts = f"2026-11-08T12:{i % 60:02d}:{i % 59:02d}.000Z"
    rows = []
    if prompt:
        rows.append({"id": f"u{i}", "timestamp": ts, "type": "user", "content": [{"text": f"please do step {i}"}]})
        rows.append({"$set": {"lastUpdated": ts}})
    rows.append({"id": f"g{i}", "timestamp": ts, "type": "gemini", "content": "", "model": "gemini-3.8-flash"})
    rows.append({"id": f"g{i}", "timestamp": ts, "type": "gemini", "content": "", "model": "gemini-3.8-flash", "toolCalls": [{"id": f"tc{i}", "name": "run_shell_command", "args": {"command": f"pytest -q tests/test_{i}.py"}, "status": "success",
                 "result": [{"functionResponse": {"id": f"tc{i}", "name": "run_shell_command", "response": {"output": "<untrusted_context>\nOutput: " + PAD + "\n5 passed in 0.1s\nProcess Group PGID: 1\n</untrusted_context>"}}}]}]})
    rows.append({"id": f"f{i}", "timestamp": ts, "type": "user", "content": [{"functionResponse": {"id": f"tc{i}", "name": "run_shell_command", "response": {"output": PAD}}}]})
    rows.append({"id": f"e{i}", "timestamp": ts, "type": "gemini", "content": f"Step {i} is done, 5 passed.", "model": "gemini-3.8-flash"})
    return rows

def gemini_tail():
    ts = "2026-11-08T23:59:00.000Z"
    return [{"id": "ul", "timestamp": ts, "type": "user", "content": [{"text": "last step"}]},
            {"id": "wl", "timestamp": ts, "type": "gemini", "content": "", "model": "gemini-3.8-flash", "toolCalls": [{"id": "tw", "name": "write_file", "args": {"file_path": "app.py", "content": "x = 1\n"}, "status": "success", "result": [{"functionResponse": {"id": "tw", "name": "write_file", "response": {"output": "ok"}}}]}]},
            {"id": "cl", "timestamp": ts, "type": "gemini", "content": "All tests pass.", "model": "gemini-3.8-flash"}]

GEN = {"claude": (claude_turn, claude_tail, ".jsonl"), "codex": (codex_turn, codex_tail, ".jsonl"), "gemini": (gemini_turn, gemini_tail, ".jsonl")}
for agent, (turn, tail, ext) in GEN.items():
    for mb in sizes:
        for shape in ("turns", "giant"):
            name = os.path.join(out, f"session-{agent}-{mb}MB-{shape}{ext}")
            if os.path.exists(name):
                continue
            target = mb * 1024 * 1024
            with open(name, "w", encoding="utf-8") as fh:
                if agent == "gemini":
                    fh.write(json.dumps({"sessionId": "s", "projectHash": "h", "startTime": "t", "directories": ["/Users/x/proj"]}) + "\n")
                if agent == "codex":
                    fh.write(json.dumps({"timestamp": "2026-11-08T12:00:00Z", "type": "session_meta", "payload": {"cwd": "/Users/x/proj", "model": "gpt-5.5"}}) + "\n")
                written, i = 0, 0
                first = True
                while written < target:
                    rows = turn(i, prompt=(shape == "turns" or first))
                    first = False
                    s = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
                    fh.write(s); written += len(s); i += 1
                for r in tail() if shape == "turns" else [x for x in tail() if x.get("type") != "user" and not (x.get("payload") or {}).get("item")]:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(name, os.path.getsize(name) // 1024 // 1024, "MB", flush=True)
