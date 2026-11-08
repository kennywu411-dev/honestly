"""Older Codex CLIs against the same parser: does a second prompt open a turn, are tool calls and outputs read, does a hold fire?  codex_versions.py codex163 codex140"""
import collections, glob, json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from standin import Standin
from run_codex import config_toml
watch_keychain()
for label in sys.argv[1:]:
    CX = os.path.join(S, "clis", label, "node_modules/.bin/codex")
    ver = subprocess.run([CX, "--version"], capture_output=True, text=True).stdout.strip()
    st = Standin()
    box = sandbox("codex-versions", label)
    env = clean_env(box, STANDIN_API_KEY="standin-dummy", CODEX_HOME=os.path.join(box["home"], ".codex"))
    os.makedirs(env["CODEX_HOME"], exist_ok=True)
    open(os.path.join(env["CODEX_HOME"], "config.toml"), "w").write(config_toml(st, "[features]\ncodex_hooks = true\nhooks = true\n"))
    subprocess.run([HONESTLY, "guard", "install", "--agent", "codex"], env=env, cwd=box["proj"], capture_output=True)
    wrap_hooks(os.path.join(env["CODEX_HOME"], "hooks.json"), box, (("Stop", "stop"), ("PreToolUse", "pre")))
    P = lambda a, b: [{"custom": "apply_patch", "input": f"*** Begin Patch\n*** Update File: app.py\n@@\n-x = {a}\n+x = {b}\n*** End Patch\n"}]
    sh = lambda c: [{"tool": "exec_command", "input": {"cmd": c}}]
    T = lambda s: [{"text": s}]
    st.reset(main=[P(0, 1), sh("pytest -q"), T("Fixed."), sh("echo hi"), T("Said hi."), P(1, 2), T("All tests pass."), T("Not verified.")])
    tid = None; print("=====", label, ver)
    flag = ["--dangerously-bypass-hook-trust"] if "bypass-hook-trust" in subprocess.run([CX, "exec", "--help"], capture_output=True, text=True).stdout else []
    print("hook-trust flag:", bool(flag))
    for i, prompt in enumerate(["fix it", "say hi", "fix again"]):
        cmd = [CX, "exec"] + (["resume"] if tid else []) + ["--json", "--skip-git-repo-check"] + flag + ([tid] if tid else []) + [prompt]
        r = subprocess.run(LOCKED + cmd, env=env, cwd=box["proj"], capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL)
        for l in r.stdout.splitlines():
            try: e = json.loads(l)
            except Exception: continue
            if e.get("type") == "thread.started": tid = e["thread_id"]
        print("run", i, "rc", r.returncode, "left", len(st.main))
    print("hook runs:", [(h["label"], h["ms"], h["stdout"][:40]) for h in hooks_log(box)][-4:])
    print("catches:", [(c["kind"], c.get("claim"), c.get("reason")) for c in catches(box)], "errors:", hook_errors(box)[-300:])
    fs = sorted(glob.glob(env["CODEX_HOME"] + "/sessions/**/*.jsonl", recursive=True))
    copy_recordings("codex-versions", label, fs)
    for f in fs:
        c = collections.Counter()
        for l in open(f):
            r = json.loads(l); p = r.get("payload") or {}
            c[(r.get("type"), p.get("type"), (p.get("item") or {}).get("type") if isinstance(p.get("item"), dict) else None)] += 1
        print("user-prompt record kinds:", [k for k in c if "user" in str(k).lower()])
        print(subprocess.run([sys.executable, os.path.join(HERE, "audit_file.py"), "codex", f], capture_output=True, text=True).stdout[:1100])
