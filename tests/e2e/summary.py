"""Scenario-by-CLI matrix from results/*/*.json. `summary.py` prints Markdown; exit code 1 when any scored scenario failed.
What each cell says: PASS/FAIL against the scenario's `expect`, then what happened (H holds, W second-pass notices, R refusals)."""
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import S, score
groups = sys.argv[1:] or ["claude-guard", "claude-plugin", "codex", "gemini"]
rows, cols = {}, []
auth_other = keychain_writes = 0
for g in groups:
    cols.append(g)
    for f in sorted(glob.glob(os.path.join(S, "results", g, "*.json"))):
        d = json.load(open(f))
        if "expect" not in d: continue
        holds, warns, denies, reached, verdict = score(d)
        auth_other += (d.get("auth_seen") or {}).get("OTHER", 0)
        keychain_writes += sum("add-generic" in x or "delete-generic" in x or "setPassword" in x for x in d.get("keychain_calls") or [])
        rows.setdefault(d["name"], {})[g] = (verdict, f"H{holds}" + (f" W{warns}" if warns else "") + (f" R{denies}" if denies else ""), d["expect"])
print("| scenario | expect | " + " | ".join(cols) + " |")
print("|---|---|" + "---|" * len(cols))
failed = 0
for name in sorted(rows):
    cells = []
    exp = next(iter(rows[name].values()))[2]
    for g in cols:
        c = rows[name].get(g)
        cells.append("" if not c else f"{c[0]} {c[1]}")
        failed += bool(c and c[0] == "FAIL")
    print(f"| {name} | {exp} | " + " | ".join(cells) + " |")
print(f"\nscored FAIL cells: {failed}; requests with a non-dummy credential: {auth_other}; keychain writes attempted: {keychain_writes}")
sys.exit(1 if failed else 0)
