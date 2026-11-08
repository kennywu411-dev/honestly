"""What a Codex user who only ran `honestly guard install` gets: doctor's word, exec with and without review, the TUI's review prompt, a hold on screen, and what re-install does to trust."""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from standin import Standin
from tui import TUI
from run_codex import config_toml, CX
watch_keychain()
st = Standin()
box = sandbox("codex", "trust")
env = clean_env(box, STANDIN_API_KEY="standin-dummy", CODEX_HOME=os.path.join(box["home"], ".codex"), TERM="xterm-256color", COLORTERM="truecolor")
os.makedirs(env["CODEX_HOME"], exist_ok=True)
cfgp = os.path.join(env["CODEX_HOME"], "config.toml")
open(cfgp, "w").write(config_toml(st, f'[projects."{box["proj"]}"]\ntrust_level = "trusted"\n'))
print(subprocess.run([HONESTLY, "guard", "install", "--agent", "codex"], env=env, cwd=box["proj"], capture_output=True, text=True).stdout)
print("--- guard status"); print(subprocess.run([HONESTLY, "guard", "status"], env=env, cwd=box["proj"], capture_output=True, text=True).stdout)
print("--- doctor"); d = subprocess.run([HONESTLY, "doctor"], env=env, cwd=box["proj"], capture_output=True, text=True); print("\n".join(l for l in d.stdout.splitlines() if "Codex" in l or "FAIL" in l or "problem" in l or "run:" in l or "all good" in l))
W = [{"custom": "apply_patch", "input": "*** Begin Patch\n*** Update File: app.py\n@@\n-x = 0\n+x = 1\n*** End Patch\n"}]
def exe(label):
    st.reset(main=[W, [{"text": "All tests pass."}], [{"text": "Not verified."}]])
    open(os.path.join(box["proj"], "app.py"), "w").write("x = 0\n")
    n0 = len(catches(box))
    r = subprocess.run(LOCKED + [CX, "exec", "--json", "--skip-git-repo-check", "do the work"], env=env, cwd=box["proj"], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    msgs = [json.loads(l).get("item", {}).get("message") for l in r.stdout.splitlines() if '"error"' in l]
    print(f"--- exec {label}: new catches {len(catches(box)) - n0}, script steps left {len(st.main)}, errors shown {msgs[:2]}")
exe("right after guard install, no review")
st.reset(main=[W, [{"text": "All tests pass."}], [{"text": "I changed app.py; not verified."}]], dump=os.path.join(box["root"], "requests.jsonl"))
open(os.path.join(box["proj"], "app.py"), "w").write("x = 0\n")
t = TUI(LOCKED + [CX, "--no-daemon"], env, box["proj"])
print("review prompt shown:", t.wait_for("Hooks need review", 20))
print("\n".join(l for l in t.text().splitlines() if l.strip() and "⣿" not in l)[:500])
t.send("2"); t.pump(0.5); t.send("\r"); t.pump(4)
if "Use existing model" in t.text():
    t.send("2"); t.pump(0.5); t.send("\r"); t.pump(3)
t.send("do the work"); t.pump(0.8); t.send("\r"); t.pump(10)
print("--- TUI after a hold and an honest retry\n" + "\n".join(l for l in t.text().splitlines() if l.strip() and "⣿" not in l)[:2200])
t.close()
exe("after Trust all, no bypass flag")
subprocess.run([HONESTLY, "guard", "install", "--agent", "codex"], env=env, cwd=box["proj"], capture_output=True, text=True)
exe("after re-running the same guard install")
alt = os.path.join(box["root"], "other-venv/bin"); os.makedirs(alt)
os.symlink(HONESTLY, os.path.join(alt, "honestly"))
print(subprocess.run([os.path.join(alt, "honestly"), "guard", "install", "--agent", "codex"], env=env, cwd=box["proj"], capture_output=True, text=True).stdout.strip())
exe("after guard install from another path (a new venv, an upgrade by another tool)")
d = subprocess.run([HONESTLY, "doctor"], env=env, cwd=box["proj"], capture_output=True, text=True).stdout
print("doctor now:", [l for l in d.splitlines() if "Codex" in l])
print("auth:", dict(st.auth_seen))
