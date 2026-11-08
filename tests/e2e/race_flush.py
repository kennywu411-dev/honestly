"""Claude Code writes its transcript with a delay. How fast must a model answer for the stop hook to read a stale file?
The stand-in waits `delay` seconds before each reply. Each cell is out of RUNS real runs, unwrapped hooks, installed as a user would."""
import concurrent.futures as cf, json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from standin import Standin
CL = os.path.join(S, "clis/claude/node_modules/.bin/claude")
RUNS = int(os.environ.get("RUNS", "6"))
T = lambda s, d=0: [{"sleep": d}, {"text": s}]
def one(kind, delay, i, eager):
    box = sandbox("race", f"{kind}-{delay}-{i}-{eager}", FAKE_FAIL if kind == "failed-run" else FAKE_PASS)
    st = Standin(); st.latency = 0; cfg = os.path.join(box["root"], "ccfg"); os.makedirs(cfg)
    extra = {"CLAUDE_CODE_EAGER_FLUSH": "1"} if eager else {}
    env = clean_env(box, ANTHROPIC_BASE_URL=st.url, ANTHROPIC_API_KEY="standin-dummy", CLAUDE_CONFIG_DIR=cfg, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", DISABLE_AUTOUPDATER="1", DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1", **extra)
    subprocess.run([HONESTLY, "guard", "install"], env=env, cwd=box["proj"], capture_output=True)
    P = os.path.join(box["proj"], "app.py")
    W = [{"tool": "Write", "input": {"file_path": P, "content": "x = 1\n"}}]
    B = lambda c: [{"sleep": delay}, {"tool": "Bash", "input": {"command": c, "description": "run"}}]
    if kind == "failed-run":      # must hold
        main = [W, B("pytest -q"), T("All tests pass.", delay), T("One test fails.", delay)]
    elif kind == "tail-pass":     # must not hold
        main = [W, B("pytest | tail -3"), T("All 5 tests pass.", delay)]
    else:                         # honest retry: must hold once, with no "still says" notice
        main = [W, T("All tests pass.", delay), T("Changed app.py; not yet verified.", delay)]
    st.reset(main=main)
    r = subprocess.run(LOCKED + [CL, "-p", "do the work", "--model", "claude-sonnet-5", "--dangerously-skip-permissions", "--output-format", "stream-json", "--verbose"], env=env, cwd=box["proj"], capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    holds = sum(c["kind"] == "stop" for c in catches(box))
    notice = "not held a second time" in r.stdout
    ok = {"failed-run": holds == 1, "tail-pass": holds == 0, "honest-retry": holds == 1 and not notice}[kind]
    return kind, delay, eager, ok
if __name__ == "__main__":
    watch_keychain()
    delays = [float(x) for x in sys.argv[1:]] or [0, 0.2, 0.5, 1, 2, 3]
    jobs = [(k, d, i, e) for e in (False, True) for k in ("failed-run", "tail-pass", "honest-retry") for d in delays for i in range(RUNS)]
    res = {}
    with cf.ThreadPoolExecutor(int(os.environ.get("JOBS", "6"))) as ex:
        for k, d, e, ok in ex.map(lambda j: one(*j), jobs):
            res.setdefault((e, k), {}).setdefault(d, []).append(ok)
    print("correct runs out of", RUNS, "| model reply delay in seconds:", delays)
    for (e, k), row in res.items():
        print(("EAGER_FLUSH=1 " if e else "default       ") + f"{k:14}", " ".join(f"{d}s:{sum(v)}/{len(v)}" for d, v in row.items()), flush=True)
