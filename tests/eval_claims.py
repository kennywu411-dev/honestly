"""Score the claim detector on a labelled corpus. Not collected by pytest: run it by hand.

    PYTHONPATH=src python tests/eval_claims.py path/to/corpus.jsonl [--misses] [--wrong] [--json]

Each line of the corpus is {"text", "lang", "category", "is_claim", "form"}. A claim counts as caught when
`find_claims` returns any hit for it, and `in category` when one of the hits has the labelled category.
A non-claim is wrongly taken when `find_claims` returns any hit for it.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys

from honestly import rules


def score(rows):
    """One row per corpus line, with the categories the detector returned."""
    out = []
    for r in rows:
        cats = [h.category for h in rules.find_claims(r["text"])]
        out.append({**r, "hits": cats})
    return out


def _table(title, scored, key):
    groups = collections.defaultdict(list)
    for r in scored:
        groups[key(r)].append(r)
    print(f"\n{title}")
    print(f"  {'':<16}{'claims':>7}{'caught':>8}{'in cat':>8}{'others':>8}{'taken':>7}")
    for name in sorted(groups):
        claims = [r for r in groups[name] if r["is_claim"]]
        others = [r for r in groups[name] if not r["is_claim"]]
        caught = sum(bool(r["hits"]) for r in claims)
        in_cat = sum(r["category"] in r["hits"] for r in claims)
        taken = sum(bool(r["hits"]) for r in others)
        c = f"{100 * caught / len(claims):.1f}%" if claims else "-"
        k = f"{100 * in_cat / len(claims):.1f}%" if claims else "-"
        t = f"{100 * taken / len(others):.1f}%" if others else "-"
        print(f"  {name:<16}{len(claims):>7}{c:>8}{k:>8}{len(others):>8}{t:>7}")


def summary(scored):
    claims = [r for r in scored if r["is_claim"]]
    others = [r for r in scored if not r["is_claim"]]
    return {"claims": len(claims), "caught": sum(bool(r["hits"]) for r in claims), "in_category": sum(r["category"] in r["hits"] for r in claims),
            "non_claims": len(others), "taken": sum(bool(r["hits"]) for r in others)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("corpus")
    ap.add_argument("--misses", action="store_true", help="list the claims it missed")
    ap.add_argument("--wrong", action="store_true", help="list the non-claims it took as claims")
    ap.add_argument("--off-category", action="store_true", help="list the claims caught under another category")
    ap.add_argument("--json", action="store_true", help="print the summary as JSON and nothing else")
    args = ap.parse_args(argv)
    with open(args.corpus, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    scored = score(rows)
    s = summary(scored)
    if args.json:
        print(json.dumps(s))
        return 0
    print(f"claims caught      {s['caught']}/{s['claims']} = {100 * s['caught'] / max(s['claims'], 1):.1f}%")
    print(f"  in its category  {s['in_category']}/{s['claims']} = {100 * s['in_category'] / max(s['claims'], 1):.1f}%")
    print(f"non-claims taken   {s['taken']}/{s['non_claims']} = {100 * s['taken'] / max(s['non_claims'], 1):.1f}%")
    _table("by language", scored, lambda r: r.get("lang", "?"))
    _table("by category", scored, lambda r: r.get("category", "?"))
    _table("by form", scored, lambda r: r.get("form", "?"))
    if args.misses:
        print("\nmissed claims")
        for r in scored:
            if r["is_claim"] and not r["hits"]:
                print(f"  [{r['category']}/{r['form']}] {r['text']}")
    if args.wrong:
        print("\nnon-claims taken")
        for r in scored:
            if not r["is_claim"] and r["hits"]:
                print(f"  [{r['category']}/{r['form']}] {r['text']}  -> {r['hits']}")
    if args.off_category:
        print("\ncaught under another category")
        for r in scored:
            if r["is_claim"] and r["hits"] and r["category"] not in r["hits"]:
                print(f"  [{r['category']}/{r['form']}] {r['text']}  -> {r['hits']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
