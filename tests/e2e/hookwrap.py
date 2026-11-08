#!/usr/bin/env python3
"""Records what a real assistant hands a hook and what the hook answers, then passes both through unchanged.
    hookwrap.py <logdir> <label> <command...>
Also copies the transcript as it was at that moment, because a transcript can lag behind the hook."""
import json, os, shutil, subprocess, sys, time
logdir, label = sys.argv[1], sys.argv[2]
cmd = sys.argv[3:]
data = sys.stdin.buffer.read()
os.makedirs(logdir, exist_ok=True)
t0 = time.time()
p = subprocess.run(cmd, input=data, capture_output=True)
ms = round((time.time() - t0) * 1000)
snap = ""
try:
    d = json.loads(data or b"{}")
    tp = d.get("transcript_path") or ""
    if tp and os.path.exists(tp) and os.path.getsize(tp) < 5_000_000:
        snap = os.path.join(logdir, f"transcript-at-{label}-{int(t0*1000)}.jsonl")
        shutil.copy(tp, snap)
except Exception:
    pass
rec = {"label": label, "t": t0, "ms": ms, "rc": p.returncode, "stdin": data.decode("utf-8", "replace"), "stdout": p.stdout.decode("utf-8", "replace"), "stderr": p.stderr.decode("utf-8", "replace"), "snapshot": snap}
with open(os.path.join(logdir, "hooks.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
sys.stdout.buffer.write(p.stdout); sys.stdout.flush()
sys.stderr.buffer.write(p.stderr); sys.stderr.flush()
sys.exit(p.returncode)
