"""Re-measure judge_output on a folder of real runner outputs: `python tests/confusion.py DIR [--list kind ...] [--runner name ...]`.

DIR holds <runner>/<case>.txt (the bytes a command printed) and <case>.json (command, exit_code, expected, optional acceptable, category).
Prints how many verdicts agree and, for the rest, which way they are wrong:

  false_pass     should hold, did not: backed or unverifiable when the run failed or tested nothing
  false_hold     every test passed, and it held anyway
  label          holds either way, with the wrong word: contradicted for unbacked, or the reverse
  lost_evidence  every test passed, not held, not counted as evidence: unverifiable
"""
import argparse
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from honestly import audit  # noqa: E402
from honestly.claude_code import Event  # noqa: E402

HOLDS = ("contradicted", "unbacked")


def kind(expected: str, got: str, acceptable) -> str:
    if expected == got:
        return "ok"
    if got in acceptable:
        return "acceptable"
    if expected in HOLDS and got in ("backed", "unverifiable"):
        return "false_pass"
    if expected == "backed" and got in HOLDS:
        return "false_hold"
    if expected in HOLDS and got in HOLDS:
        return "label"
    return "lost_evidence"


def judge_all(root: pathlib.Path):
    """One row per file and claim: a linter's output is judged as both a build claim and a checks claim."""
    for meta in sorted(root.rglob("*.json")):
        case = json.loads(meta.read_text(encoding="utf-8"))
        out = meta.with_suffix(".txt").read_bytes().decode("utf-8", "replace")
        ev = Event("tool", name="Bash", text=case["command"], result=out, is_error=case["exit_code"] != 0)
        categories = case.get("category", "tests_pass")
        for category in [categories] if isinstance(categories, str) else categories:
            verdict, why = audit.judge_output(category, case["command"], ev)
            yield {"path": str(meta.relative_to(root).with_suffix("")), "category": category, "command": case["command"], "exit_code": case["exit_code"], "expected": case["expected"], "verdict": verdict, "why": why,
                   "kind": kind(case["expected"], verdict, case.get("acceptable", [])), "runner": case.get("runner", meta.parent.name), "note": case.get("note", "")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", type=pathlib.Path)
    ap.add_argument("--list", nargs="*", default=[], help="print the rows of these kinds")
    ap.add_argument("--runner", nargs="*", default=[], help="limit the listing to these runners")
    args = ap.parse_args(argv)
    rows = list(judge_all(args.dir))
    counts = collections.Counter(r["kind"] for r in rows)
    print(f"files={sum(1 for _ in args.dir.rglob('*.txt'))} verdicts={len(rows)} runners={len({r['runner'] for r in rows})}")
    for k in ("ok", "acceptable", "false_pass", "false_hold", "label", "lost_evidence"):
        print(f"{k:14} {counts[k]}")
    for r in rows:
        if r["kind"] in args.list and (not args.runner or r["runner"] in args.runner):
            tag = "" if r["category"] == "tests_pass" else f" [{r['category']}]"
            print(f"{r['kind']:13} {r['path']}{tag}: expected {r['expected']}, got {r['verdict']}, exit {r['exit_code']} :: {r['command'][:60]} :: {r['why'][:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
