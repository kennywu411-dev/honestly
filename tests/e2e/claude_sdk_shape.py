"""stream-json input with content blocks (what SDK hosts send, e.g. text + image): does each prompt open a turn?"""
import glob, json, os, select, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from standin import Standin
CL = os.path.join(S, "clis/claude/node_modules/.bin/claude")
watch_keychain()
st = Standin()
box = sandbox("claude-sdk", "stream")
cfg = os.path.join(box["root"], "ccfg"); os.makedirs(cfg)
env = clean_env(box, ANTHROPIC_BASE_URL=st.url, ANTHROPIC_API_KEY="standin-dummy", CLAUDE_CONFIG_DIR=cfg, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", DISABLE_AUTOUPDATER="1", DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1")
subprocess.run([HONESTLY, "guard", "install"], env=env, cwd=box["proj"], capture_output=True)
wrap_hooks(os.path.join(cfg, "settings.json"), box, (("Stop", "stop"), ("PreToolUse", "pre")))
P = os.path.join(box["proj"], "app.py")
T = lambda s: [{"text": s}]
tool = lambda n, **k: [{"tool": n, "input": k}]
st.reset(main=[tool("Write", file_path=P, content="x = 1\n"), tool("Bash", command="pytest -q", description="run"), T("All 5 tests pass."),
               T("All tests pass.")], dump=os.path.join(box["root"], "requests.jsonl"))
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
msgs = [{"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "first: fix it"}]}, "parent_tool_use_id": None, "session_id": ""},
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "second: what does this picture show?"}, {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG}}]}, "parent_tool_use_id": None, "session_id": ""}]
p = subprocess.Popen(LOCKED + [CL, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose", "--model", "claude-sonnet-5", "--dangerously-skip-permissions"], env=env, cwd=box["proj"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
p.stdin.write(json.dumps(msgs[0]) + "\n"); p.stdin.flush()
sent = 1; end = time.time() + 60
while time.time() < end:
    r, _, _ = select.select([p.stdout], [], [], 1)
    if r:
        line = p.stdout.readline()
        if not line: break
        try: e = json.loads(line)
        except Exception: continue
        if e.get("type") == "result":
            print("result:", repr(e.get("result"))[:80])
            if sent < len(msgs):
                p.stdin.write(json.dumps(msgs[sent]) + "\n"); p.stdin.flush(); sent += 1
            else:
                p.stdin.close(); break
p.wait(timeout=30)
print("hooks:", [(h["label"], h["stdout"][:60]) for h in hooks_log(box)])
print("catches:", [(c["kind"], c.get("claim"), c.get("reason"), c.get("topic")) for c in catches(box)])
tr = glob.glob(os.path.join(cfg, "projects", "*", "*.jsonl"))[0]
copy_recordings("claude-sdk", "stream", [tr])
for l in open(tr):
    r = json.loads(l)
    if r.get("type") == "user":
        c = r["message"]["content"]
        print({k: r.get(k) for k in ("origin", "promptSource", "turnOrigin", "isMeta")}, type(c).__name__, [b.get("type") for b in c] if isinstance(c, list) else c[:40])
print(subprocess.run([sys.executable, os.path.join(HERE, "audit_file.py"), "claude", tr], capture_output=True, text=True).stdout[:1300])
