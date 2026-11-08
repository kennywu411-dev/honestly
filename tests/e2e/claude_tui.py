"""Claude Code interactive (a real pty): what the person and the model see on a hold and a refusal; also records the interactive transcript shape."""
import glob, json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from standin import Standin
from tui import TUI
CL = os.path.join(S, "clis/claude/node_modules/.bin/claude")
watch_keychain()
st = Standin()
box = sandbox("claude-tui", "hold")
cfg = os.path.join(box["root"], "ccfg"); os.makedirs(cfg)
env = clean_env(box, ANTHROPIC_BASE_URL=st.url, ANTHROPIC_API_KEY="standin-dummy", CLAUDE_CONFIG_DIR=cfg, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", DISABLE_AUTOUPDATER="1", DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1", TERM="xterm-256color", COLORTERM="truecolor")
subprocess.run([HONESTLY, "guard", "install"], env=env, cwd=box["proj"], capture_output=True)
json.dump({"hasCompletedOnboarding": True, "lastOnboardingVersion": "2.1.319", "bypassPermissionsModeAccepted": True, "customApiKeyResponses": {"approved": ["standin-dummy"[-20:]], "rejected": []},
           "projects": {box["proj"]: {"hasTrustDialogAccepted": True, "hasCompletedProjectOnboarding": True, "projectOnboardingSeenCount": 5}}}, open(os.path.join(cfg, ".claude.json"), "w"))
P = os.path.join(box["proj"], "app.py")
T = lambda s: [{"text": s}]
def tool(n, **k): return [{"tool": n, "input": k}]
st.reset(main=[tool("Write", file_path=P, content="x = 1\n"), T("All tests pass."), T("Changed app.py, not verified."),
               tool("Bash", command="pytest | head -3", description="run"), T("That was refused."),
               tool("Write", file_path=P, content="x = 2\n"), T("所有测试都通过了。"), T("已修改，尚未验证。")], dump=os.path.join(box["root"], "requests.jsonl"))
t = TUI(LOCKED + [CL, "--model", "claude-sonnet-5", "--dangerously-skip-permissions"], env, box["proj"])
t.wait_for(r"(?i)(\? for shortcuts|bypass|welcome)", 25); t.pump(3)
def say(s, wait=8):
    t.send(s); t.pump(0.8); t.send("\r"); t.pump(wait)
    return t.text()
a = say("do the work"); print("--- after a held reply\n" + a[-2300:])
b = say("now run them"); print("--- after a refused command\n" + b[-1500:])
c = say("再改一次"); print("--- Chinese\n" + c[-1700:])
t.close()
print("catches:", [(x["kind"], x.get("claim")) for x in catches(box)], "errors:", hook_errors(box)[-400:], "auth:", dict(st.auth_seen), "keychain writes:", sum("add-generic" in x for x in keychain_calls(box)))
copy_recordings("claude-tui", "hold", glob.glob(os.path.join(cfg, "projects", "*", "*.jsonl")))
for x in st.log:
    print(x["kind"], x.get("n"), repr(x.get("since_assistant", "")[-120:]), "->", str(x.get("reply"))[:70])
for f in glob.glob(os.path.join(cfg, "projects", "*", "*.jsonl")):
    for l in open(f):
        r = json.loads(l)
        if r.get("type") == "user":
            c = r["message"]["content"]
            print({k: r.get(k) for k in ("origin", "promptSource", "turnOrigin", "isMeta", "entrypoint")}, type(c).__name__, (c[:50] if isinstance(c, str) else [b.get("type") for b in c]))
