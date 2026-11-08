"""The plugin installed the way the README says, from a local copy of the marketplace (nothing fetched), then real runs."""
import glob, json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from standin import Standin
CL = os.path.join(S, "clis/claude/node_modules/.bin/claude")
watch_keychain()
st = Standin()
box = sandbox("claude-market", "m")
cfg = os.path.join(box["root"], "ccfg"); os.makedirs(cfg)
env = clean_env(box, ANTHROPIC_BASE_URL=st.url, ANTHROPIC_API_KEY="standin-dummy", CLAUDE_CONFIG_DIR=cfg, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", DISABLE_AUTOUPDATER="1", DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1")
def run(*a):
    r = subprocess.run(LOCKED + list(a), env=env, cwd=box["proj"], capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    print("$", " ".join(x if len(x) < 70 else "…" + x[-40:] for x in a), "->", r.returncode); print((r.stdout + r.stderr)[-400:])
run(CL, "plugin", "marketplace", "add", REPO)
run(CL, "plugin", "install", "honestly@honestly")
run(CL, "plugin", "list")
for f in glob.glob(cfg + "/plugins/cache/**/hooks/hooks.json", recursive=True): print("cache:", f[len(cfg):])
P = os.path.join(box["proj"], "app.py")
T = lambda s: [{"text": s}]
W = [{"tool": "Write", "input": {"file_path": P, "content": "x = 1\n"}}]
B = lambda c: [{"tool": "Bash", "input": {"command": c, "description": "run"}}]
def turn(steps, prompt="do the work", e=None):
    st.reset(main=steps); n0 = len(catches(box))
    r = subprocess.run(LOCKED + [CL, "-p", prompt, "--model", "claude-sonnet-5", "--dangerously-skip-permissions", "--output-format", "json"], env=e or env, cwd=box["proj"], capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    j = {}
    try: j = json.loads(r.stdout)
    except Exception: pass
    print(f"prompt {prompt!r}: result={j.get('result')!r} rc={r.returncode} new catches={[(c['kind'], c.get('claim')) for c in catches(box)[n0:]]} left={len(st.main)} errors={hook_errors(box)[-200:]!r}")
turn([W, T("All tests pass."), T("Not verified.")])
turn([W, B("pytest | head -3"), T("Stopped.")])
turn([W, B("pytest -q"), T("All 5 tests pass.")])
turn([W, T("所有测试都通过了。"), T("已修改，尚未验证。")], "修复这个问题")
print("--- no python on PATH: the Stop hook must say nothing is being checked")
noenv = dict(env); noenv["PATH"] = box["bin"]
st.reset(main=[W, T("All tests pass."), T("Not verified.")])
r = subprocess.run(LOCKED + [CL, "-p", "no python on PATH", "--model", "claude-sonnet-5", "--dangerously-skip-permissions", "--output-format", "stream-json", "--verbose"], env=noenv, cwd=box["proj"], capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
print("told the user:", "not checking this session" in r.stdout)
sp = os.path.join(cfg, "settings.json"); d = json.load(open(sp)) if os.path.exists(sp) else {}
d.setdefault("hooks", {})["Stop"] = [{"hooks": [{"type": "command", "command": "/nonexistent/honestly hook stop  # honestly hook"}]}]
json.dump(d, open(sp, "w"))
turn([W, T("All tests pass."), T("Not verified.")], "dangling guard entry")
print("auth:", dict(st.auth_seen))
