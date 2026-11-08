"""How a run is read from what its runner printed. The verdict on a whole command, with its exit status and pipes, is in test_judge_output.py."""
import pytest

from honestly import verdicts


def state(text, **kw):
    return verdicts.read(verdicts.clean(text), **kw).state


@pytest.mark.parametrize("text,want", [
    ("=== 3 passed in 0.02s ===", "pass"),
    ("=== 1 failed, 3 passed in 0.05s ===", "fail"),
    ("=== 2 skipped in 0.02s ===", "skipped"),
    ("=== 3 deselected in 0.01s ===", "skipped"),
    ("no tests ran in 0.01s", "zero"),
    ("Ran 3 tests in 0.001s\n\nOK", "pass"),
    ("Ran 2 tests in 0.001s\n\nOK (skipped=2)", "skipped"),
    ("Ran 3 tests in 0.001s\n\nOK (skipped=1, expected failures=1)", "pass"),
    ("Ran 0 tests in 0.000s\n\nOK", "zero"),
    ("Tests:       3 skipped, 3 total", "skipped"),
    ("Tests:       0 total", "zero"),
    ("Test Suites: 1 failed, 1 passed, 2 total\nTests:       5 passed, 5 total", "fail"),
    ("      Tests  3 skipped (3)", "skipped"),
    ("  1 passing (9ms)\n  1 failing", "fail"),
    ("  0 passing (2ms)\n  2 pending", "skipped"),
    ("ℹ tests 0\nℹ pass 0\nℹ fail 0", "zero"),
    ("ok  \tm/a\t0.1s\n?   \tm/b\t[no test files]", "pass"),
    ("?   \tm/b\t[no test files]", "zero"),
    ("test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out\n\ntest result: ok. 0 passed; 0 failed; 0 ignored", "pass"),
    ("test result: ok. 0 passed; 0 failed; 2 ignored; 0 measured; 0 filtered out", "skipped"),
    ("     Summary [   0.01s] 4 tests run: 3 passed, 1 failed, 0 skipped", "fail"),
    ("OK, but there were issues!\nTests: 5, Assertions: 3, Skipped: 1, Incomplete: 1.", "pass"),
    ("Tests: 2, Assertions: 0, Skipped: 2.", "skipped"),
    ("Tests run: 2, Failures: 0, Errors: 0, Skipped: 2", "skipped"),
    ("test cases: 6 | 3 passed | 1 skipped | 2 failed as expected", "pass"),
    ("Result: 0 tests, 2 skipped", "skipped"),
    ("Result: 3/4 passed\nFailed: 1 test", "fail"),
    ("", ""),
    ("some output with no verdict at all", ""),
])
def test_the_state_of_a_run(text, want):
    assert state(text) == want


def test_a_script_word_only_speaks_when_no_runner_did():
    assert state("FAILED to reach upstream\n=== 3 passed in 0.02s ===") == "pass"
    assert verdicts.read("FAIL: unit\n").weak
    assert state("PASS: lint\nFAIL: unit") == "fail"
    assert state("all good: OK") == "pass"


def test_the_last_run_only_replaces_earlier_runs_when_asked():
    twice = "=== 1 failed in 0.1s ===\n=== 3 passed in 0.1s ==="
    assert state(twice) == "fail"
    assert state(twice, last_run_only=True) == "pass"
    jest = "Test Suites: 1 failed, 1 total\nTests:       1 failed, 1 total\nTest Suites: 1 passed, 1 total\nTests:       1 passed, 1 total"
    assert state(jest, last_run_only=True) == "pass"


def test_a_later_step_owns_what_a_wrapper_reports():
    out = "Tests:       5 passed, 5 total\nnpm error code 1\nmake: *** [deploy] Error 1"
    assert state(out) == "fail"
    assert state(out, later_steps=True) == "pass"


def test_every_runner_shape_starts_at_a_line_start():
    assert all(rx.pattern.startswith("^") for _name, _kind, rx in verdicts.tables()[0])


def test_colour_cursor_codes_and_links_are_not_text():
    assert verdicts.clean("\x1b]8;;http://x\x07link\x1b]8;;\x07 \x1b[?25l\x1b[2K\x1b[31m5 passed\x1b[39m") == "link 5 passed"
    assert verdicts.clean("a\r\nb\rc") == "a\nb\nc"


@pytest.mark.parametrize("text,problem", [
    ("Found 3 errors.", True),
    ("Found 0 errors", False),
    ("3 errors, 0 warnings, 0 informations", True),
    ("0 errors, 0 warnings, 0 informations", False),
    ("1 issues:", True),
    ("0 issues.", False),
    ("Your code has been rated at 0.00/10", True),
    ("Your code has been rated at 10.00/10", False),
    ("a.py:161:0: I0021: Useless suppression", False),
    ("./a.py:1:1: F401 'os' imported but unused", True),
])
def test_diagnostics_are_counted(text, problem):
    assert bool(verdicts.read_check(text).problem) == problem


@pytest.mark.parametrize("text,found", [
    ("Build error: missing header", True),
    ("fatal: could not read config", True),
    ("compiled src/error.tsx", False),
    ("dist/assets/error-BLru-uax.js  0.05 kB", False),
    ("warning: unused variable: `error`", False),
    ("2 |     let error = 1;", False),
    ("0 errors", False),
    ("finished without errors", False),
])
def test_the_word_error_for_a_tool_no_table_knows(text, found):
    assert bool(verdicts.error_word(text)) == found
