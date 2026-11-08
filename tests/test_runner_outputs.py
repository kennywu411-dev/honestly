"""judge_output on what real test runners, compilers and linters printed. Each case is a run we made: <runner>/<case>.txt holds the bytes, <case>.json the command, exit code and verdict.

`expected` says what happened: backed if every test ran and passed, contradicted if something failed, unbacked if nothing was tested. `acceptable` is another verdict that is also right.
`safe` is the verdict we keep where the output cannot settle it, and `note` says why. tests/confusion.py prints the same table for any folder like this one.
"""
import json
import pathlib
import re

import pytest

from honestly import audit
from honestly.claude_code import Event

ROOT = pathlib.Path(__file__).parent / "fixtures" / "runner_outputs"
CASES = sorted(ROOT.rglob("*.json"))


def rows():
    out = []
    for meta in CASES:
        case = json.loads(meta.read_text(encoding="utf-8"))
        categories = case.get("category", "tests_pass")
        for category in [categories] if isinstance(categories, str) else categories:
            out.append(pytest.param(meta, case, category, id=f"{meta.parent.name}/{meta.stem}/{category}"))
    return out


@pytest.mark.parametrize("meta,case,category", rows())
def test_the_verdict_on_real_output(meta, case, category):
    out = meta.with_suffix(".txt").read_bytes().decode("utf-8", "replace")
    ev = Event("tool", name="Bash", text=case["command"], result=out, is_error=case["exit_code"] != 0)
    verdict, why = audit.judge_output(category, case["command"], ev)
    want = [case["safe"]] if "safe" in case else [case["expected"], *case.get("acceptable", [])]
    assert verdict in want, f"{case['command']!r} exit {case['exit_code']}: got {verdict} ({why})"


def test_the_fixture_is_real_small_and_impersonal():
    assert len(CASES) > 500
    total = 0
    for path in ROOT.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            total += len(data)
            assert not re.search(rb"/Users/|/private/tmp|C:\\Users|@gmail\.com", data), path
    assert total < 3_000_000
