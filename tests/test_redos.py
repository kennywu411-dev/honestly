"""The rules run on whatever a command printed. Every pattern added for 0.7.2 has to stay linear on awkward output (CodeQL py/polynomial-redos)."""
import time

import pytest

from honestly import agents, audit, hooks, rules

PATTERNS = {
    "FAIL_COUNT": audit.FAIL_COUNT, "COUNTED_TESTS": audit.COUNTED_TESTS, "COMMITTED_RECAP": audit.COMMITTED_RECAP, "TEST_PATH": audit.TEST_PATH,
    "SELF_CHECK_OK": audit.SELF_CHECK_OK, "SELF_CHECK_BAD": audit.SELF_CHECK_BAD, "GIT_COMMIT_TITLE": audit.GIT_COMMIT_TITLE, "DRY_RUN_FLAG": audit.DRY_RUN_FLAG,
    "TEST_PASS": audit.TEST_PASS, "TEST_FAIL": audit.TEST_FAIL, "SUMMARY_LINE": audit.SUMMARY_LINE, "ZERO_TESTS": audit.ZERO_TESTS,
    "SHELL_OUTPUT": agents.SHELL_OUTPUT, "PS_WRITE": rules.PS_WRITE, "PS_WRITE_SOURCE": rules.PS_WRITE_SOURCE, "PIPE_SWALLOW": rules.PIPE_SWALLOW,
    "SELECT_CUTS_END": hooks.SELECT_CUTS_END, "SELECT_LAST": hooks.SELECT_LAST,
}
AWKWARD = [" ", "\n ", "\n", "\t", "9 tests, ", "fail ", ", ", "[  FAILED  ] ", "- ", "* ", "*", "| ", ".test", "Output: a\n", "with 1 failures ", "1 ", "# ", "#", " \n# ", "\n- * "]


@pytest.mark.parametrize("name", sorted(PATTERNS))
def test_a_pattern_stays_fast_on_awkward_output(name):
    rx = PATTERNS[name]
    for unit in AWKWARD:
        start = time.perf_counter()
        rx.search(unit * 2000)
        assert time.perf_counter() - start < 1.0, repr(unit)
