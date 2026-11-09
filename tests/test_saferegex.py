"""saferegex must agree with `re` where it answers at all, and must answer fast on what would make `re` hang."""
import re
import time

import pytest

from honestly import hooks, saferegex

def short(value):
    """A test's name: a pattern thousands of characters long is no name."""
    return value if len(value) < 60 else f"{value[:30]}...({len(value)} characters)"


def _work_seconds(fn):
    """A hang is work, so it is timed in CPU seconds: a runner waiting on its disk or for a core is no slower a check."""
    start = time.process_time()
    fn()
    return time.process_time() - start


LINES = ["=========== 1 failed, 2 passed, 1 warning in 0.12s ===========", "FAILED tests/test_a.py::test_x - assert 1 == 2", "Tests:       1 failed, 2 passed, 3 total", "test result: FAILED. 2 passed; 1 failed; 0 ignored",
         "FAIL\tgithub.com/acme/app/pkg\t0.012s", "--- FAIL: TestPrice (0.00s)", "error[E0308]: mismatched types", "make: *** [test] Error 1", "", "  1 failing", "ok  pkg 0.1s", "word boundary case", "a.b+c", "aaa"]
PATTERNS = ["passed", "failed|passed", "^FAILED", "FAIL$", "^$", "^(FAIL|ok)", "[0-9]+ (passed|failed)", "\\d+ failed", "=+ .* =+", "(a|b)+", "a*", "a+", "a?b", "colou?r", "a{2}", "a{2,}", "a{1,2}$", "(ab){2}", "\\bword\\b", "\\Bord", "[a-c]+", "[^a-z]+", "[[:digit:]]+".replace("[[:digit:]]", "[0-9]"), "\\s+", "\\S+", "\\w+", "\\W+", ".", ".*", ".+x", "a.b", "a\\.b", "a\\+c", "\\[test\\]", "\\*\\*\\*", "(?:FAIL|ok)\\s", "^.{3}$", "x|", "|x", "()", "(|a)b", "[]a]", "[a-]", "[-a]", "^\\s*1 fail", "error\\[E\\d+\\]", "FAILED \\(failures=\\d+\\)", "(?:a|aa)+$", "a*?b", "a+?a"]


@pytest.mark.parametrize("pattern", PATTERNS)
@pytest.mark.parametrize("icase", [False, True])
def test_it_agrees_with_re(pattern, icase):
    rx = re.compile(pattern, re.I if icase else 0)
    safe = saferegex.compile(pattern, icase)
    assert safe is not None, pattern
    for line in LINES:
        assert safe.search(line) == bool(rx.search(line)), (pattern, line)


@pytest.mark.parametrize("pattern", ["(a)\\1", "(?=a)b", "(?!a)b", "(?<=a)b", "(?i)a", "(?P<x>a)", "(((", ")", "[a", "a{1,100}", "*a", "+a", "\\", "x" * 500, "(" * 50 + "a" + ")" * 50, "(a{64}){64}"], ids=short)
def test_outside_the_subset_it_says_it_cannot_tell(pattern):
    assert saferegex.compile(pattern) is None


@pytest.mark.parametrize("pattern", ["(.*)*X", "(.+)+X", "(=+)+X", "([a-z ]+)+X", "(.*)(.*)(.*)(.*)(.*)X", "(\\w+\\s*)+X", "(a|aa)+X", "(a*)*X", "(.*){8}X", "x*" * 100 + "Q", "a|" * 150 + "Q"], ids=short)
def test_a_pattern_that_makes_re_hang_is_answered_at_once(pattern):
    start = time.perf_counter()
    safe = saferegex.compile(pattern)
    if safe is not None:
        for line in LINES:
            safe.search(line * 3)
    assert time.perf_counter() - start < 0.5


@pytest.mark.parametrize("cmd", ["pytest | grep -E '(.*)*X'", "pytest | grep -E '(.+)+X'", "pytest | grep -E '(=+)+X'", "pytest | grep -E '([a-z ]+)+X'", "pytest | grep -E '(.*)(.*)(.*)(.*)(.*)X'", "pytest | rg '(.*)*X'",
                                 "pytest | Select-String '(.+)+X'", 'pytest | findstr "(.*)*X"', "pytest | grep -E '" + "(" * 2000 + "'", "pytest | grep -E '" + "(a" * 2000 + ")" * 2000 + "'", "pytest | grep -E 'a{1,100000000}'", "pytest | grep '" + "x*" * 5000 + "Q'", "pytest | sed -n '/(.*)*X/p'", "pytest | awk '/(.+)+X/'"], ids=short)
def test_the_pipe_check_never_hangs_or_raises(cmd):
    assert _work_seconds(lambda: hooks.find_hidden_status(cmd)) < 0.5


CMD_THAT_WRITES_THE_LOG = "pytest | grep -E 'a{1,100000000}'"


def test_a_stall_writing_the_log_is_not_a_hang(monkeypatch):
    """A pattern it cannot judge writes a line to hook-errors.log. On a Windows runner that took 0.6 s and failed the test above, twice, on two such patterns."""
    monkeypatch.setattr(hooks, "_note", lambda *a: time.sleep(0.6))
    assert _work_seconds(lambda: hooks.find_hidden_status(CMD_THAT_WRITES_THE_LOG)) < 0.5


def test_a_check_that_spins_is_still_caught(monkeypatch):
    def spin(*a, **k):
        end = time.process_time() + 0.6   # by the same clock: on a busy machine 0.6 s on the wall may be much less work
        while time.process_time() < end:
            pass

    monkeypatch.setattr(hooks, "_unit_hidden", spin)
    assert _work_seconds(lambda: hooks.find_hidden_status(CMD_THAT_WRITES_THE_LOG)) >= 0.5


def test_the_verdict_samples_still_decide():
    keep = hooks._pattern_keeps_verdict
    assert keep("grep", {"E"}, ["passed|failed"]) == "select"
    assert keep("grep", set(), ["FAILED\\|ERROR"]) == "select"
    assert keep("grep", set(), ["FAILED|ERROR"]) == "filter"     # in a basic regex `|` is a plain character
    assert keep("grep", set(), ["[[:digit:]]\\+ passed"]) == "select"
    assert keep("grep", {"E"}, ["^(FAIL|ok)"]) == "select"
    assert keep("grep", set(), ["SKIP"]) == "filter"
    assert keep("grep", {"v"}, ["warning"]) == "filter"
    assert keep("grep", {"v"}, ["DEBUG"]) == "keep"
    assert keep("fgrep", set(), ["1 failed"]) == "select"
    assert keep("grep", {"x", "E"}, ["FAILED \\(failures=1\\)"]) == "select"
    assert keep("grep", {"q"}, ["x"]) == "silent"
    assert keep("grep", {"c"}, ["x"]) == "count"
    assert keep("grep", set(), None) == "keep"
    assert keep("grep", {"E"}, ["(a)\\1"]) == "keep"     # could not tell
