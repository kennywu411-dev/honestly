"""Does a CLI try to use the keychain under a temp HOME, with no login and only a dummy key? Nothing reaches the real keychain:
Claude Code's `security` calls hit a logger on PATH, Gemini CLI's native module is a logging stub."""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from standin import Standin
T = lambda s: [{"text": s}]
# Gemini, default storage settings
st = Standin(); box = sandbox("keychain", "gemini")
env = clean_env(box, GEMINI_API_KEY="standin-dummy", GOOGLE_GEMINI_BASE_URL=st.url, GEMINI_CLI_TRUST_WORKSPACE="true")
os.makedirs(os.path.join(box["home"], ".gemini"))
json.dump({"security": {"auth": {"selectedType": "gemini-api-key"}}}, open(os.path.join(box["home"], ".gemini/settings.json"), "w"))
st.reset(main=[T("hello")])
r = subprocess.run([os.path.join(S, "clis/gemini/node_modules/.bin/gemini"), "-p", "hi", "--yolo", "--output-format", "json"], env=env, cwd=box["proj"], capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL)
print("gemini default storage: rc", r.returncode, "keychain calls:", keychain_calls(box))
# Gemini, GEMINI_FORCE_FILE_STORAGE=true
st.reset(main=[T("hello")]); box = sandbox("keychain", "gemini-file")
env = clean_env(box, GEMINI_API_KEY="standin-dummy", GOOGLE_GEMINI_BASE_URL=st.url, GEMINI_CLI_TRUST_WORKSPACE="true", GEMINI_FORCE_FILE_STORAGE="true")
os.makedirs(os.path.join(box["home"], ".gemini"))
json.dump({"security": {"auth": {"selectedType": "gemini-api-key"}}}, open(os.path.join(box["home"], ".gemini/settings.json"), "w"))
r = subprocess.run([os.path.join(S, "clis/gemini/node_modules/.bin/gemini"), "-p", "hi", "--yolo", "--output-format", "json"], env=env, cwd=box["proj"], capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL)
print("gemini file storage: rc", r.returncode, "keychain calls:", keychain_calls(box))
# Claude Code
st.reset(main=[T("hello")]); box = sandbox("keychain", "claude")
cfg = os.path.join(box["root"], "ccfg"); os.makedirs(cfg)
env = clean_env(box, ANTHROPIC_BASE_URL=st.url, ANTHROPIC_API_KEY="standin-dummy", CLAUDE_CONFIG_DIR=cfg, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", DISABLE_AUTOUPDATER="1", DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1")
r = subprocess.run([os.path.join(S, "clis/claude/node_modules/.bin/claude"), "-p", "hi", "--model", "claude-sonnet-5", "--dangerously-skip-permissions"], env=env, cwd=box["proj"], capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL)
calls = keychain_calls(box)
print("claude -p: rc", r.returncode, "calls:", len(calls))
for c in sorted({" ".join(x.split()[1:3]) for x in calls}): print("   ", c)
print("writes:", [x for x in calls if "add-generic" in x or "delete-generic" in x][:5])
print("SecurityAgent up now:", security_agent_up())
