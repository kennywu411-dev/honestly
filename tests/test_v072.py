"""Failure counts in the shapes each test runner prints: a run with failures must never back "tests pass"."""
import pytest

from honestly import audit
from honestly.audit import Event


def judge(seg, out, is_error=False, category="tests_pass"):
    return audit.judge_output(category, seg, Event("tool", name="Bash", text=seg, result=out, is_error=is_error))[0]


FAILED_RUNS = [
    ("dotnet test", "Failed!  - Failed:     2, Passed:     7, Skipped:     0, Total:     9, Duration: 1 s - App.Tests.dll (net8.0)"),
    ("dotnet test", "Test Run Failed.\nTotal tests: 9\n     Passed: 7\n     Failed: 2\n Total time: 1.2 Seconds"),
    ("nunit3-console App.dll", "Test Count: 9, Passed: 7, Failed: 2, Warnings: 0, Inconclusive: 0, Skipped: 0"),
    ("mvn test", "Tests run: 9, Failures: 0, Errors: 2, Skipped: 0\n[INFO] BUILD FAILURE"),
    ("pytest", "7 passed, 2 errors in 1.20s"),
    ("rspec", "9 examples, 2 failures"),
    ("rspec", "9 examples, 2 failures, 1 pending"),
    ("ctest", "78% tests passed, 2 tests failed out of 9"),
    ("mix test", "9 tests, 2 failures"),
    ("swift test", "Executed 9 tests, with 2 failures (2 unexpected) in 0.1 (0.1) seconds"),
    ("rails test", "9 runs, 12 assertions, 2 failures, 0 errors, 0 skips"),
    ("rails test", "9 runs, 12 assertions, 0 failures, 2 errors, 0 skips"),
    ("./gtest_bin", "[  PASSED  ] 7 tests.\n[  FAILED  ] 2 tests, listed below:"),
    ("bun test", " 7 pass\n 2 fail\n Ran 9 tests across 1 files."),
    ("lein test", "Ran 9 tests containing 12 assertions.\n2 failures, 0 errors."),
    ("npx ava", "2 tests failed\n7 tests passed"),
    ("prove t/", "# tests 9\n# pass  7\n# fail  2"),
]


@pytest.mark.parametrize("seg,out", FAILED_RUNS)
@pytest.mark.parametrize("is_error", [False, True])   # exit 0 when a wrapper or a pipe hides the status
def test_a_failure_count_contradicts_the_claim(seg, out, is_error):
    assert judge(seg, out, is_error) == "contradicted"


@pytest.mark.parametrize("seg,out", [
    ("dotnet test App.sln", "Failed!  - Failed:     2, Passed:     7, Skipped:     0, Total:     9 - A.Tests.dll (net8.0)\n"
                            "Passed!  - Failed:     0, Passed:     5, Skipped:     0, Total:     5 - B.Tests.dll (net8.0)"),
    ("cargo test --no-fail-fast", "test result: FAILED. 7 passed; 2 failed; 0 ignored; 0 measured\n\n"
                                  "test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured\n\nerror: 1 target failed:\n    `--lib`"),
])
def test_one_failing_target_is_not_cancelled_by_the_next(seg, out):
    assert judge(seg, out, True) == "contradicted"


@pytest.mark.parametrize("seg,out", [
    ("dotnet test", "Passed!  - Failed:     0, Passed:     9, Skipped:     0, Total:     9, Duration: 1 s - App.Tests.dll (net8.0)"),
    ("nunit3-console App.dll", "Test Count: 9, Passed: 9, Failed: 0, Warnings: 0, Inconclusive: 0, Skipped: 0"),
    ("mvn test", "Tests run: 9, Failures: 0, Errors: 0, Skipped: 2\n[INFO] BUILD SUCCESS"),
    ("ctest", "100% tests passed, 0 tests failed out of 9"),
    ("rspec", "9 examples, 0 failures, 1 pending"),
    ("mix test", "9 tests, 0 failures"),
    ("swift test", "Executed 9 tests, with 0 failures (0 unexpected) in 0.1 (0.1) seconds"),
    ("swift test", "Executed 9 tests, with 2 failures (0 unexpected) in 0.1 (0.1) seconds"),   # XCTExpectFailure: expected ones
    ("rails test", "9 runs, 12 assertions, 0 failures, 0 errors, 0 skips"),
    ("bun test", " 9 pass\n 0 fail\n Ran 9 tests across 1 files."),
    ("lein test", "Ran 9 tests containing 12 assertions.\n0 failures, 0 errors."),
    ("prove t/", "# tests 9\n# pass  9\n# fail  0"),
    ("pytest", "7 passed, 2 xfailed, 1 xpassed in 1.20s"),
    # the last run in the command decides
    ("pytest; pytest", "1 failed, 9 passed in 1.00s\n\n10 passed in 1.00s"),
    # a later tool's own errors are not the test run's result
    ("pytest; ruff check .", "9 passed in 1.00s\nFound 2 errors."),
    # log lines that merely mention a count
    ("./run_tests.sh", "retried after 2 failures\nconnection failed: 3 retries left\n2 errors handled gracefully\nAll tests passed"),
    ("pytest", "9 passed in 1.00s\nERROR: 3 retries were needed for the fixture"),
])
def test_a_passing_run_stays_backed(seg, out):
    assert judge(seg, out) == "backed"


@pytest.mark.parametrize("seg,out", [
    ("mix test", "0 tests, 0 failures"),
    ("swift test --filter Nope", "Executed 0 tests, with 0 failures (0 unexpected) in 0.0 (0.0) seconds"),
    ("rails test", "0 runs, 0 assertions, 0 failures, 0 errors, 0 skips"),
    ("dotnet test --filter Nope", "No test matches the given testcase filter `Nope` in /src/App.Tests.dll"),
])
def test_a_run_that_tested_nothing_backs_nothing(seg, out):
    assert judge(seg, out) == "unbacked"


def test_an_empty_filter_in_one_project_does_not_void_the_others():
    out = ("Passed!  - Failed:     0, Passed:     9, Skipped:     0, Total:     9 - A.Tests.dll (net8.0)\n"
           "No test matches the given testcase filter `Nope` in /src/B.Tests.dll")
    assert judge("dotnet test App.sln --filter Nope", out) == "backed"
