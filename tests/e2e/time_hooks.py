"""Time the real hook commands on big transcripts, with a fresh process each time, as an assistant runs them. The timeouts honestly installs: stop 30 s, pre 10 s."""
import glob, json, os, re, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import BOX, HONESTLY
d = sys.argv[1]
CAP = 90   # an assistant kills the stop hook at 30 s and the pre hook at 10 s; past this the exact figure no longer matters
home = os.path.join(BOX, "timing-home"); os.makedirs(home, exist_ok=True)
env = {"HOME": home, "PATH": "/usr/bin:/bin", "HONESTLY_NO_UPDATE_CHECK": "1", "LANG": "en_US.UTF-8"}
AGENT = {"claude": "claude-code", "codex": "codex", "gemini": "gemini"}
def timed(which, agent, payload, n=2):
    best, rss, out = 1e9, 0, ""
    for _ in range(n):
        t0 = time.time()
        p = subprocess.Popen(["/usr/bin/time", "-l", HONESTLY, "hook", which, "--agent", agent], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)
        try:
            o, e = p.communicate(json.dumps(payload), timeout=CAP)
        except subprocess.TimeoutExpired:
            subprocess.run(["pkill", "-P", str(p.pid)])
            p.kill(); p.communicate()
            return CAP, 0, f">{CAP}s"
        if p.returncode != 0:
            return time.time() - t0, 0, f"rc={p.returncode}"
        best = min(best, time.time() - t0); out = o
        m = re.search(r"(\d+)\s+maximum resident set size", e)
        if m: rss = max(rss, int(m.group(1)) // (1024 * 1024))
    return best, rss, ("held" if ('"decision"' in out) else "refused" if ("deny" in out) else "pass")
print(f"{'file':40} {'stop s':>7} {'MB RSS':>7} {'result':>7} | {'pre(hit) s':>10} {'MB RSS':>7} | {'pre(miss) s':>11}")
def key(f):
    m = re.search(r"session-(\w+)-(\d+)MB-(\w+)", f); return (m.group(1), int(m.group(2)), m.group(3))
for f in sorted(glob.glob(os.path.join(d, "session-*.jsonl")), key=key):
    a, mb, shape = key(f); agent = AGENT[a]
    base = {"session_id": "s", "transcript_path": f, "cwd": "/Users/x/proj", "hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": "All tests pass."}
    if a == "gemini":
        base = {"session_id": "s", "transcript_path": f, "cwd": "/Users/x/proj", "hook_event_name": "AfterAgent", "stop_hook_active": False, "prompt_response": "All tests pass."}
    s, rs, res = timed("stop", agent, base, 1 if mb >= 500 else 2)
    tool = {"claude": "Bash", "codex": "Bash", "gemini": "run_shell_command"}[a]
    ph, rp, rr = timed("pre", agent, {"session_id": "s", "transcript_path": f, "cwd": "/Users/x/proj", "tool_name": tool, "tool_input": {"command": "pytest | head -3"}}, 1 if mb >= 500 else 2)
    pm, _, _ = timed("pre", agent, {"session_id": "s", "transcript_path": f, "cwd": "/Users/x/proj", "tool_name": tool, "tool_input": {"command": "ls -la"}}, 2)
    flag = "  STOP OVER 30s" if s > 30 else ""
    flag += "  PRE OVER 10s" if ph > 10 else ""
    print(f"{os.path.basename(f)[8:-6]:40} {s:7.2f} {rs:7d} {res:>7} | {ph:10.2f} {rp:7d} | {pm:11.2f}{flag}", flush=True)
