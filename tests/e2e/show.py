"""Pretty-print one or more results/<group>/<scenario>.json files."""
import json, sys
for f in sys.argv[1:]:
    d = json.load(open(f))
    print("=====", d["name"], "expect", d["expect"], "pytest_ran", d["pytest_ran"])
    for r in d["runs"]:
        print(" RUN rc", r["rc"], "secs", r["secs"], "result", repr(r["result"])[:200])
        for s in r.get("shown_to_user") or []:
            print("   shown:", str(s)[:300])
    for q in d["requests"]:
        print(f'  req {q["kind"]:6} n={q["n"]} last={q["last"][-240:]!r}')
        print(f'      -> {json.dumps(q["reply"], ensure_ascii=False)[:180]}')
    for h in d["hooks"]:
        print(f'  hook {h["label"]} {h["ms"]}ms rc={h["rc"]} sha={h["stop_hook_active"]} lam={h["lam"][:60]!r} out={h["stdout"][:240]!r} err={h["stderr"][:120]!r}')
    if d["hooks"]:
        print("  fields", d["hooks"][-1]["fields"])
    print("  catches", [(c["kind"], c["claim"], c["reason"]) for c in d["catches"]])
    if d["hook_errors"]:
        print("  hook_errors", d["hook_errors"][-500:])
    print("  transcripts", d["transcripts"])
