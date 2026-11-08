"""What test runners, compilers and linters really print, one table per tool, and how to read a run from it.

The shapes come from real output, kept in tests/fixtures/runner_outputs/ (gh, busted, lein and NUnit's console only from the tests that name them). A shape is
one line, anchored to how the tool prints it, so a word in a log line, a test name, a file name or a source snippet is not a verdict. To add a runner: run it for
real, add its output to the fixtures, add its lines here.

Kinds of line:
  COUNT  numbers the run printed; the named groups say what they count: p passed, f failed, e errors, s skipped, x failed as expected, t total
  FAIL   the run failed
  PASS   the run passed, and the line is the runner's own verdict
  ZERO   nothing was tested
  NOTE   not a verdict alone; _adjust may use it
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field

COUNT, FAIL, PASS, ZERO, NOTE = "count", "fail", "pass", "zero", "note"
# a pass or failure word from a script no table knows: only used when no runner printed a verdict
WEAK_FAIL, WEAK_PASS = "weak-fail", "weak-pass"


# ---------------------------------------------------------------- test runners
RUNNERS = {
    # `3 passed in 0.02s`, `=== 1 failed, 3 passed, 2 skipped in 0.05s ===`; a bare `27 passed` too, and pytest-sugar's one count per line
    "pytest": [
        (COUNT, r"^[= \t]*(?P<words>\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?|rerun|subtests? (?:passed|failed))(?:, \d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?|rerun|subtests? (?:passed|failed)))*)(?: in [\d.]+\s*m?s\b[^\n]*)?[= \t]*$"),
        (ZERO, r"^[= \t]*no tests ran\b[^\n]*$"),
        (ZERO, r"^collected 0 items\b[^\n]*$"),
        (FAIL, r"^!+ (?:stopping after \d+ failures?|Interrupted: [^\n]*error[^\n]*) !+$"),
        (FAIL, r"^Interrupted: \d+ errors? during collection\b"),
        (FAIL, r"^FAILED [\w./-]+\.py(?:::|\b)"),
        (FAIL, r"^ERROR [\w./-]+\.py\b"),
        (NOTE, r"^ERROR: (?:file or directory not found|usage:|not found:)"),
    ],
    # `  1 failed`, `  1 flaky`, `  2 skipped`, `  3 passed (1.6s)`, one count per line
    "playwright": [
        (COUNT, r"^[ \t]*(?P<words>\d+ (?:passed|failed|skipped|flaky|did not run|interrupted))(?: \([\d.]+\w*\))?[ \t]*$"),
        (ZERO, r"^Error: No tests found\b"),
        (COUNT, r"^[ \t]*\"expected\": (?P<p>\d+),$"),
        (COUNT, r"^[ \t]*\"unexpected\": (?P<f>\d+),$"),
        (COUNT, r"^[ \t]*\"skipped\": (?P<s>\d+),$"),
    ],
    # a report on stdout: `<testsuite tests="3" failures="0" errors="0" skipped="0" ...>`
    "junit": [
        (COUNT, r"^[ \t]*<testsuites?\b(?=[^>\n]*\btests=\"(?P<t>\d+)\")(?=[^>\n]*\bfailures=\"(?P<f>\d+)\")(?:(?=[^>\n]*\berrors=\"(?P<e>\d+)\"))?(?:(?=[^>\n]*\bskipped=\"(?P<s>\d+)\"))?"),
    ],
    # `Ran 3 tests in 0.001s` then `OK` or `FAILED (failures=1)`; also Django
    "unittest": [
        (COUNT, r"^Ran (?P<t>\d+) tests? in [^\n]*\n[-= \t]*\n?OK(?: \((?:expected failures=(?P<x>\d+)(?:, )?)?(?:skipped=(?P<s>\d+))?(?:, )?(?:expected failures=(?P<x2>\d+))?\))?[ \t]*$"),
        (ZERO, r"^NO TESTS RAN\b"),
        (ZERO, r"^Ran 0 tests\b"),
        (FAIL, r"^FAILED \((?:failures|errors)=[1-9][^\n]*\)$"),
    ],
    # `Tests:       1 failed, 5 passed, 6 total`
    "jest": [
        (COUNT, r"^Tests:[ \t]+(?P<words>(?:\d+ (?:failed|skipped|todo|passed)(?:, )?)*)(?:(?P<t>\d+) total)?[ \t]*$"),
        (COUNT, r"^Test Suites:[ \t]+(?P<f>[1-9]\d*) failed\b"),
        (NOTE, r"^Test Suites:[ \t]"),
        (ZERO, r"^No tests found, exiting with code \d"),
        (FAIL, r"^[ \t]*Test suite failed to run$"),
        (FAIL, r"^[ \t]*FAIL\s+\S+\.(?:[cm]?[jt]sx?|vue|svelte)\b"),
        (FAIL, r"^Jest: \"\w+\" coverage threshold for "),
    ],
    # ` Test Files  1 failed | 2 passed (3)`, `      Tests  3 passed | 1 skipped (4)`
    "vitest": [
        (COUNT, r"^[ \t]*Tests[ \t]+(?P<words>(?:\d+ (?:failed|skipped|todo|passed|expected fail)(?: \| )?)+)[ \t]*\(\d+\)[ \t]*$"),
        (COUNT, r"^[ \t]*Test Files[ \t]+(?P<f>[1-9]\d*) failed\b"),
        (NOTE, r"^[ \t]*Test Files[ \t]"),
        (ZERO, r"^[ \t]*No test files found, exiting with code \d"),
        (FAIL, r"^[ \t]*Vitest caught \d+ (?:unhandled )?errors? during the test run"),
        (FAIL, r"^[ \t]*Errors[ \t]+[1-9]\d* errors?\b"),
    ],
    # `  3 passing (5ms)`, `  1 failing`, `  2 pending`
    "mocha": [
        (COUNT, r"^[ \t]*(?P<p>\d+) passing\b[^\n]*$"),
        (COUNT, r"^[ \t]*(?P<f>\d+) failing[ \t]*$"),
        (COUNT, r"^[ \t]*(?P<s>\d+) pending[ \t]*$"),
        (ZERO, r"^(?:Error: )?No test files found\b"),
        (COUNT, r"^[ \t]*\"passes\": (?P<p>\d+),$"),
        (COUNT, r"^[ \t]*\"failures\": (?P<f>\d+),$"),
        (COUNT, r"^[ \t]*\"pending\": (?P<s>\d+),$"),
    ],
    # `  3 tests passed`, `  1 test failed`, `  1 known failure`, `  1 uncaught exception`
    "ava": [
        (COUNT, r"^[ \t]*(?P<p>\d+) tests? passed[ \t]*$"),
        (COUNT, r"^[ \t]*(?P<f>\d+) tests? failed[ \t]*$"),
        (COUNT, r"^[ \t]*(?P<s>\d+) tests? (?:skipped|todo)[ \t]*$"),
        (COUNT, r"^[ \t]*(?P<f>\d+) (?:uncaught exceptions?|unhandled rejections?)[ \t]*$"),
        (ZERO, r"^[ \t]*[✘✖] Couldn['’]t find any (?:matching tests|files to test)"),
        (FAIL, r"^[ \t]*[✘✖] [^\n]* exited with a non-zero exit code"),
        (FAIL, r"^[ \t]*[✘✖] No tests found in "),
    ],
    # `ℹ tests 3` `ℹ pass 3` `ℹ fail 0`, one count per line; TAP's `# pass 3`; the junit reporter's `<!-- pass 3 -->`
    "node": [
        (NOTE, r"^[✔✓] \S+\.[cm]?[jt]sx? \([\d.]+m?s\)$"),
        (COUNT, r"^(?:ℹ|#|<!--) (?:tests) (?P<t0>\d+)(?: -->)?[ \t]*$"),
        (COUNT, r"^[ \t]*(?:ℹ|#|<!--) pass[ \t]+(?P<p>\d+)(?: -->)?[ \t]*$"),
        (COUNT, r"^[ \t]*(?:ℹ|#|<!--) (?:fail|cancelled)[ \t]+(?P<f>\d+)(?: -->)?[ \t]*$"),
        (COUNT, r"^[ \t]*(?:ℹ|#|<!--) (?:skipped|skip|todo)[ \t]+(?P<s>\d+)(?: -->)?[ \t]*$"),
    ],
    "tap": [
        (COUNT, r"^#[ \t]*failed (?P<f>\d+) of \d+ tests?\b"),
        (FAIL, r"^[ \t]*not ok\b(?![^\n]*# (?:TODO|SKIP))"),
        (COUNT, r"^[ \t]*ok \d+\b(?P<note>[^\n]*# (?:SKIP|TODO))"),
        (ZERO, r"^1\.\.0\b"),
        (PASS, r"^[ \t]*ok \d+\b"),
    ],
    # `ok | 3 passed | 0 failed (1ms)`, `FAILED | 3 passed | 1 failed (2ms)`
    "deno": [
        (COUNT, r"^(?:ok|FAILED) \| (?P<p>\d+) passed(?: \(\d+ steps?\))? \| (?P<f>\d+) failed(?: \(\d+ steps?\))?(?: \| (?P<s>\d+) ignored)?(?: \| \d+ filtered out)?\b[^\n]*$"),
        (ZERO, r"^error: No test modules found\b"),
        (FAIL, r"^error: Test failed\b"),
        (FAIL, r"^error: Type checking failed\b"),
        (FAIL, r"^error: Module not found\b"),
        (FAIL, r"^error: The module's source code could not be parsed\b"),
    ],
    # ` 3 pass`, ` 0 fail`, ` 2 skip`, `Ran 3 tests across 1 file.`
    "bun": [
        (COUNT, r"^[ \t]*(?P<p>\d+) pass[ \t]*$"),
        (COUNT, r"^[ \t]*(?P<f>\d+) fail[ \t]*$"),
        (COUNT, r"^[ \t]*(?P<s>\d+) (?:skip|todo)[ \t]*$"),
        (COUNT, r"^[ \t]*(?P<e>\d+) errors?[ \t]*$"),
        (ZERO, r"^No tests found!"),
        (ZERO, r"^error: regex \"[^\n]*\" matched 0 tests\b"),
        (ZERO, r"^error: \d+ files? (?:were|was) filtered out"),
    ],
    # go test: `ok  \tpkg\t0.1s`, `FAIL\tpkg\t0.1s`, `--- FAIL: TestX`; the same in -json
    "go": [
        (ZERO, r"^ok\s+[^\s|]\S*[^\n]*\[no tests to run\]"),
        (ZERO, r"^\?\s+\S+\s+\[no test files\]"),
        (ZERO, r"^no packages to test\b"),
        (NOTE, r"^testing: warning: no tests to run$"),
        (PASS, r"^ok\s+[^\s|]\S*\s+(?:\(cached\)|[\d.]+\w*)(?:\s+coverage:[^\n]*)?[ \t]*$"),
        (FAIL, r"^--- FAIL: "),
        (FAIL, r"^[ \t]+--- FAIL: "),
        (FAIL, r"^FAIL$"),
        (FAIL, r"^FAIL\t\S+"),
        (FAIL, r"^panic: "),
        (NOTE, r"^--- SKIP: "),
        (NOTE, r"^--- PASS: "),
        (FAIL, r"^\{[^\n]{0,200}\"Action\":\"(?:fail|build-fail)\""),
        (ZERO, r"^\{[^\n]{0,120}\"Action\":\"output\",\"Package\":\"[^\"]*\",\"Output\":\"ok[^\"]*\[no tests to run\]"),
        (PASS, r"^\{[^\n]{0,120}\"Action\":\"output\",\"Package\":\"[^\"]*\",\"Output\":\"ok  \\t"),
        (ZERO, r"^\{[^\n]{0,120}\"Output\":\"\?   \\t[^\"]*\[no test files\]"),
        (NOTE, r"^\{[^\n]{0,80}\"Action\":\"skip\",\"Package\":\"[^\"]*\",\"Test\":\"[^\"/]*\""),
        (NOTE, r"^\{[^\n]{0,80}\"Action\":\"pass\",\"Package\":\"[^\"]*\",\"Test\":\"[^\"/]*\""),
    ],
    # `DONE 3 tests, 1 skipped, 1 failure in 0.1s`
    "gotestsum": [
        (COUNT, r"^DONE (?P<t>\d+) tests?(?:, (?P<s>\d+) skipped)?(?:, (?P<f>\d+) failures?)?(?:, (?P<e>\d+) errors?)? in "),
    ],
    # `test result: ok. 3 passed; 0 failed; 0 ignored; ...`; nextest's `Summary [0.01s] 3 tests run: 3 passed, 0 skipped`
    "cargo": [
        (COUNT, r"^test result: (?:ok|FAILED)\. (?P<p>\d+) passed; (?P<f>\d+) failed(?:; (?P<s>\d+) ignored)?\b"),
        (FAIL, r"^test result: FAILED\b"),
        (COUNT, r"^[ \t]*Summary \[[ \d.]+s\] (?P<t0>\d+) tests? run: (?P<p>\d+) passed(?: \(\d+ \w+\))?(?:, (?P<f>\d+) failed)?(?:, \d+ \w+)*?(?:, (?P<s>\d+) skipped)?\b"),
        (ZERO, r"^(?:error|warning): no tests to run\b"),
        (FAIL, r"^error\[E\d+\]: "),
        (FAIL, r"^error: test failed, to rerun pass\b"),
        (FAIL, r"^error: \d+ targets? failed:"),
        (FAIL, r"^error: test run failed\b"),
        (FAIL, r"^error: could not compile\b"),
        (FAIL, r"^error: file not found for module\b"),
        (FAIL, r"^(?:warning: )?build failed\b"),
    ],
    # `5 examples, 0 failures, 2 pending`; ExUnit before 1.20: `9 tests, 0 failures, 1 skipped`
    "rspec": [
        (COUNT, r"^(?P<t>\d+) examples?, (?P<f>\d+) failures?(?:, (?P<s>\d+) pending)?(?:, (?P<e>\d+) errors? occurred outside of examples)?\b"),
        (FAIL, r"^An error occurred (?:while loading|in an?|outside of)\b"),
        (FAIL, r"^Failed examples:$"),
        (FAIL, r"^rspec \S+:\d+ # "),
        (ZERO, r"^All examples were filtered out"),
    ],
    # `3 runs, 3 assertions, 0 failures, 0 errors, 0 skips`; Rails; test-unit's `3 tests, 3 assertions, ...`
    "minitest": [
        (COUNT, r"^(?P<t>\d+) (?:runs|tests), \d+ assertions?, (?P<f>\d+) failures?, (?P<e>\d+) errors?(?:, (?P<s>\d+) (?:skips|pendings))?\b"),
        (FAIL, r"^rake aborted!$"),
        (FAIL, r"^Command failed with status \(\d+\)"),
    ],
    # `OK (3 tests, 3 assertions)`, `FAILURES!` then `Tests: 4, Assertions: 4, Failures: 1.`, `OK, but there were issues!` then `Tests: 5, ... Skipped: 1.`
    "phpunit": [
        (COUNT, r"^OK \((?P<t>\d+) tests?, \d+ assertions?\)$"),
        (COUNT, r"^Tests: (?P<t>\d+), Assertions: \d+(?P<words>(?:, [A-Z][\w ]*: \d+)*)\.$"),
        (ZERO, r"^No tests executed!$"),
        (FAIL, r"^(?:FAILURES|ERRORS)!$"),
        (FAIL, r"^PHP (?:Parse|Fatal) error: "),
    ],
    # `  Tests:    1 failed, 3 passed (4 assertions)`
    "pest": [
        (COUNT, r"^[ \t]*Tests:[ \t]+(?P<words>(?:\d+ (?:failed|passed|skipped|todo|risky|warnings?|deprecated|incomplete)(?:, )?)+)[ \t]*\(\d+ assertions?\)[ \t]*$"),
        (ZERO, r"^[ \t]*(?:INFO[ \t]+)?No tests found\.?[ \t]*$"),
    ],
    # `Tests run: 3, Failures: 0, Errors: 0, Skipped: 0`, `BUILD FAILURE`
    "maven": [
        (COUNT, r"^Tests run: (?P<t>\d+), Failures: (?P<f>\d+), Errors: (?P<e>\d+)(?:, Skipped: (?P<s>\d+))?\b"),
        (FAIL, r"^BUILD FAILURE\b"),
        (FAIL, r"^\S[^\n]*? FAILURE \[[^\n]*\]$"),
        (FAIL, r"^COMPILATION ERROR\b"),
        (ZERO, r"^No tests to run\.$"),
        (ZERO, r"^Tests are skipped\.$"),
        (ZERO, r"^(?:Failed to execute goal [^\n]*)?No tests matching pattern\b"),
        (NOTE, r"^BUILD SUCCESS\b"),
        (NOTE, r"^--- surefire:\S+:test\b"),
    ],
    # `4 tests completed, 1 failed`, `BUILD FAILED in 8s`, `> Task :test NO-SOURCE`
    "gradle": [
        (COUNT, r"^(?P<t>\d+) tests? completed, (?P<f>\d+) failed(?:, (?P<s>\d+) skipped)?\b"),
        (FAIL, r"^BUILD FAILED\b"),
        (FAIL, r"^FAILURE: Build (?:failed|completed)\b"),
        (FAIL, r"^\S+ > \S+\(\)[^\n]* FAILED$"),
        (ZERO, r"^> Task (?:\S*:)?test NO-SOURCE$"),
        (ZERO, r"^(?:> )?No tests found for given includes\b"),
        (NOTE, r"^BUILD SUCCESSFUL\b"),
    ],
    # `[info] Passed: Total 3, Failed 0, Errors 0, Passed 3`, scalatest's `Tests: succeeded 3, failed 0, ...`
    "sbt": [
        (COUNT, r"^\[(?:info|error)\] (?:Passed|Failed): Total (?P<t>\d+), Failed (?P<f>\d+), Errors (?P<e>\d+), Passed (?P<p>\d+)(?:, Skipped (?P<s>\d+))?(?:, Ignored (?P<s2>\d+))?(?:, Canceled \d+)?(?:, Pending (?P<s3>\d+))?\b"),
        (COUNT, r"^\[info\] Tests: succeeded (?P<p>\d+), failed (?P<f>\d+), canceled \d+, ignored (?P<s>\d+), pending (?P<s2>\d+)"),
        (ZERO, r"^\[info\] No tests to run for "),
        (FAIL, r"^\[error\] Failed tests:"),
        (FAIL, r"^\[error\] \(\S[^\n]*\) "),
        (FAIL, r"^\[error\] Total time:"),
        (NOTE, r"^\[success\] Total time:"),
    ],
    # `Passed!  - Failed:     0, Passed:     3, Skipped:     0, Total:     3`; `Test summary: total: 4, failed: 1, succeeded: 3, skipped: 0`; NUnit's console
    "dotnet": [
        (COUNT, r"^(?:Passed!|Failed!|Skipped!)[ \t]+- Failed:[ \t]+(?P<f>\d+), Passed:[ \t]+(?P<p>\d+), Skipped:[ \t]+(?P<s>\d+)\b"),
        (COUNT, r"^Test summary: total: \d+, failed: (?P<f>\d+), succeeded: (?P<p>\d+), skipped: (?P<s>\d+)\b"),
        (COUNT, r"^Test Count: \d+, Passed: (?P<p>\d+), Failed: (?P<f>\d+), Warnings: \d+, Inconclusive: \d+, Skipped: (?P<s>\d+)\b"),
        (COUNT, r"^[ \t]+Passed: (?P<p>\d+)$"),
        (COUNT, r"^[ \t]+Failed: (?P<f>\d+)$"),
        (COUNT, r"^[ \t]+Skipped: (?P<s>\d+)$"),
        (FAIL, r"^Test Run Failed\.?$"),
        (NOTE, r"^Test Run Successful\.?$"),
        (ZERO, r"^No test is available in "),
        (ZERO, r"^No test matches the given testcase filter\b"),
        (FAIL, r"^\S[^\n]*: error [A-Z]+\d+: "),
        (FAIL, r"^Build FAILED\.$"),
        (FAIL, r"^Build failed with \d+ error"),
    ],
    # `Executed 3 tests, with 0 failures (0 unexpected) in ...`; Swift Testing's `✔ Test run with 3 tests passed after ...`
    "swift": [
        (COUNT, r"^[ \t]*Executed (?P<t>\d+) tests?, with (?:(?P<s>\d+) tests? skipped and )?(?P<fx>\d+) failures? \((?P<u>\d+) unexpected\)"),
        (FAIL, r"^Test Suite '[^'\n]*' failed at\b"),
        (FAIL, r"^Test Case '[^'\n]*' failed\b"),
        (COUNT, r"^[✔✓✘✗] Test run with (?P<p>\d+) tests?(?: in \d+ suites?)? passed\b"),   # `✘ ... passed ... with 1 known issue`: withKnownIssue is expected
        (FAIL, r"^[✘✗] Test run with \d+ tests?(?: in \d+ suites?)? failed\b"),
        (FAIL, r"^[✘✗] Test (?:\"[^\"\n]*\"|\S+) (?:failed\b|recorded an issue\b)"),
        (COUNT, r"^\[\d+/(?P<p>\d+)\] Testing \S+"),   # `swift test --parallel` prints no XCTest summary
        (NOTE, r"^[✘✗↷➜]? ?Test \S+ skipped\b"),
        (ZERO, r"^error: no tests found; create a target\b"),
        (FAIL, r"^error: fatalError$"),
        (FAIL, r"^\S+\.swift:\d+:\d+: error: "),
    ],
    # `00:00 +3: All tests passed!`, `00:00 +3 -1: Some tests failed.`, `00:00 +0 ~2: All tests skipped.`; the json reporter's last event
    "dart": [
        (COUNT, r"^\d+:\d+ \+(?P<p>\d+)(?: ~(?P<s>\d+))?(?: -(?P<f>\d+))?: (?:All tests passed!|Some tests failed\.|All tests skipped\.)"),
        (FAIL, r"^(?:\d+:\d+ \+\d+(?: ~\d+)? -\d+: )?Failed to load\b"),
        (FAIL, r"^Failing tests:$"),
        (FAIL, r"^\{\"testID\":\d+,\"result\":\"(?:failure|error)\""),
        (COUNT, r"^\{\"testID\":\d+,\"result\":\"success\",(?P<note>\"skipped\":true),\"hidden\":false"),
        (PASS, r"^\{\"testID\":\d+,\"result\":\"success\",\"skipped\":false,\"hidden\":false"),
        (ZERO, r"^No tests ran\.?$"),
        (ZERO, r"^No tests match (?:regular expression|the requested)\b"),
        (ZERO, r"^No tests were found\b"),
        (ZERO, r"^Test directory \"[^\"\n]*\" not found\b"),
        (FAIL, r"^\{\"success\":false\b"),
        (NOTE, r"^\{\"success\":true\b"),
        (COUNT, r"^\{\"group\":\{[^\n]*\"testCount\":(?P<t0>\d+)"),
        (COUNT, r"^🎉 (?P<p>\d+) tests? passed(?:, (?P<s>\d+) skipped)?\.?$"),
        (COUNT, r"^✅ (?P<p>\d+) tests? passed, (?P<f>\d+) failed\b"),
        (COUNT, r"^❌ (?P<p>\d+) tests? passed, (?P<f>\d+) failed\b"),
    ],
    # ExUnit 1.20: `Result: 3 passed`, `Result: 3/4 passed` then `Failed: 1 test`, `Result: 0 tests, 2 skipped`
    "exunit": [
        (COUNT, r"^Result: (?P<p>\d+)(?:/\d+)? passed(?:, (?P<s>\d+) skipped)?(?:, (?P<s2>\d+) excluded)?[ \t]*$"),
        (COUNT, r"^Result: (?P<t>0) tests(?:, (?P<s>\d+) skipped)?(?:, (?P<s2>\d+) excluded)?[ \t]*$"),
        (COUNT, r"^Failed: (?P<f>\d+) tests?[ \t]*$"),
        (COUNT, r"^(?P<t>\d+) tests?, (?P<f>\d+) failures?(?:, (?P<s>\d+) skipped)?(?:, (?P<s2>\d+) excluded)?\b"),
        (COUNT, r"^(?P<f>\d+) failures?[ \t]*$"),
        (ZERO, r"^There are no tests to run\b"),
        (ZERO, r"^The --only option was given to \"mix test\" but no test was executed\b"),
        (FAIL, r"^\*\* \(\w*Error\) "),
        (FAIL, r"^== Compilation error\b"),
    ],
    # `Ran 3 tests containing 3 assertions.` then `0 failures, 0 errors.`
    "clojure": [
        (COUNT, r"^Ran (?P<t>\d+) tests containing (?P<a>\d+) assertions\.[ \t]*\n(?P<f>\d+) failures, (?P<e>\d+) errors\.[ \t]*$"),
        (COUNT, r"^(?P<f>\d+) failures, (?P<e>\d+) errors\.[ \t]*$"),
        (FAIL, r"^(?:FAIL|ERROR) in \("),
        (FAIL, r"^(?:Syntax|Execution) error (?:compiling|reading source|\()"),
    ],
    # `100% tests passed, 0 tests failed out of 3`, `No tests were found!!!`
    "ctest": [
        (COUNT, r"^\d+% tests passed, (?P<f>\d+) tests? failed out of (?P<t>\d+)\b"),
        (ZERO, r"^No tests were found!!!"),
        (FAIL, r"^The following tests FAILED:"),
        (FAIL, r"^Errors while running CTest\b"),
        (FAIL, r"^[ \t]+\d+ - \S[^\n]* \((?:Failed|Timeout|SEGFAULT|Subprocess aborted|Not Run|ILLEGAL|BAD_COMMAND|Exception)\)$"),
        (NOTE, r"^[ \t]+\d+ - \S[^\n]* \((?:Skipped|Disabled)\)$"),
    ],
    # `[  PASSED  ] 3 tests.`, `[  FAILED  ] 1 test, listed below:`, `[  SKIPPED ] 2 tests, listed below:`
    "gtest": [
        (COUNT, r"^\[  PASSED  \] (?P<p>\d+) tests?\.[ \t]*$"),
        (COUNT, r"^\[  FAILED  \] (?P<f>\d+) tests?, listed below:"),
        (COUNT, r"^\[  SKIPPED \] (?P<s>\d+) tests?, listed below:"),
        (FAIL, r"^\[  FAILED  \] \S+"),
        (FAIL, r"^\d+ FAILED TESTS?\b"),
    ],
    # `All tests passed (3 assertions in 3 test cases)`, `test cases: 4 | 3 passed | 1 failed`, `test cases: 6 | 3 passed | 1 skipped | 2 failed as expected`
    "catch2": [
        (COUNT, r"^All tests passed \(\d+ assertions? in (?P<p>\d+) test cases?\)"),
        (COUNT, r"^test cases:[ \t]*\d+ \|[ \t]*(?P<words>[^\n]*)$"),
        (NOTE, r"^assertions:[ \t]"),
        (ZERO, r"^No tests ran\b"),
        (ZERO, r"^No test cases matched\b"),
        (COUNT, r"^Passed all (?P<p>\d+) test cases? with\b"),
        (COUNT, r"^Failed (?P<f>\d+) test cases?, failed\b"),
        (COUNT, r"^Passed (?P<p>\d+) test cases? with\b"),
    ],
    # `Tests Passed: 3, Failed: 0, Skipped: 0, Inconclusive: 0, NotRun: 0`, `Container failed: 1`
    "pester": [
        (COUNT, r"^Tests Passed: (?P<p>\d+), Failed: (?P<f>\d+), Skipped: (?P<s>\d+)(?:, Inconclusive: \d+)?(?:,? NotRun: (?P<s2>\d+))?"),
        (COUNT, r"^(?:Container|Block) failed: (?P<f>\d+)"),
        (ZERO, r"^(?:System\.Management\.Automation\.RuntimeException: )?No test files were found\b"),
        (FAIL, r"^\[-\] \S"),
    ],
    # `All tests successful.`, `Files=1, Tests=3`, `Result: PASS`, `Failed 1/3 subtests`
    "prove": [
        (FAIL, r"^Result: FAIL\b"),
        (ZERO, r"^Result: NOTESTS\b"),
        (COUNT, r"^Files=\d+, Tests=(?P<t>0)\b"),
        (COUNT, r"^Files=\d+, Tests=(?P<p>[1-9]\d*)\b"),
        (NOTE, r"^Result: PASS\b"),
        (NOTE, r"^All tests successful\.?$"),
    ],
    # `5 successes / 2 failures / 0 errors / 0 pending : 0.1 seconds`
    "busted": [
        (COUNT, r"^(?P<p>\d+) successes? / (?P<f>\d+) failures? / (?P<e>\d+) errors? / (?P<s>\d+) pending\b"),
    ],
    # the run table's last row: `✔  All specs passed!  133ms  3  3  -  -  -`, `✖  1 of 1 failed (100%)  309ms  4  3  1  -  -`
    "cypress": [
        (COUNT, r"^[ \t]*✔[ \t]+All specs passed![ \t]+\S+[ \t]+(?P<t0>\d+|-)[ \t]+(?P<p>\d+|-)[ \t]+(?P<f>\d+|-)[ \t]+(?P<s>\d+|-)[ \t]+(?P<s2>\d+|-)[ \t]*$"),
        (FAIL, r"^[ \t]*✖[ \t]+\d+ of \d+ failed\b"),
        (ZERO, r"^Can't run because no spec files were found\b"),
    ],
    # wrappers around a runner: their own verdict, never a count of tests
    "tox": [
        (FAIL, r"^[ \t]*\S+: FAIL code \d"),
        (FAIL, r"^[ \t]*evaluation failed :\("),
        (WEAK_PASS, r"^[ \t]*congratulations :\)"),
    ],
    "nox": [
        (FAIL, r"^nox > Session \S+ (?:failed|raised exception)\b"),
        (FAIL, r"^nox > \* \S+: failed\b"),
        (WEAK_PASS, r"^nox > Session \S+ was successful\b"),
    ],
    "make": [
        (ZERO, r"^(?:g?make)(?:\[\d+\])?: \*\*\* No (?:rule to make target|targets)\b"),
        (FAIL, r"^(?:g?make)(?:\[\d+\])?: \*\*\* "),
    ],
    "npm": [
        (ZERO, r"^npm (?:ERR!|error) Missing script\b"),
        (ZERO, r"^Error: no test specified$"),
        (FAIL, r"^npm (?:ERR!|error) (?:Lifecycle script|Test failed|code [1-9E])"),
        (FAIL, r"^(?:Error: )?ERR_PNPM_RECURSIVE\w*"),
        (FAIL, r"^\[?ELIFECYCLE\]?[ \t]+Test failed\b"),
        (ZERO, r"^No projects matched the filters\b"),
        (FAIL, r"^error Command failed\b"),
    ],
    "turbo": [
        (COUNT, r"^[ \t]*Tasks:[ \t]+(?P<ok>\d+) successful, (?P<all>\d+) total\b"),
        (FAIL, r"^[ \t]*Failed:[ \t]+\S+#\S+"),
    ],
    "nx": [
        (ZERO, r"^[ \t]*NX[ \t]+No tasks were run\b"),
        (FAIL, r"^[ \t]*NX[ \t]+Ran target \S+ for \d+ projects?\b[^\n]*\bfailed\b"),
        (FAIL, r"^[ \t]*NX[ \t]+Running target \S+ for \d+ projects? failed\b"),
        (FAIL, r"^[ \t]*[✖×][ \t]+\d+/\d+ failed\b"),
        (NOTE, r"^[ \t]*NX[ \t]+Successfully ran target\b"),
    ],
    "gh": [
        (FAIL, r"^\S[^\t\n]*\tfail\t"),
        (FAIL, r"^Some checks were not successful\b"),
        (COUNT, r"^(?P<f>\d+) (?:failing|failed), \d+ (?:successful|passing)\b"),
        (PASS, r"^All checks were successful\b"),
        (WEAK_PASS, r"^\S[^\t\n]*\tpass\t"),
    ],
    # a script's own words; these only speak when no runner above printed a verdict
    "script": [
        (WEAK_FAIL, r"^[ \t]*\[?(?:FAIL(?:ED|URE)?|ERROR)\]?(?::|[ \t]|$)"),
        (WEAK_FAIL, r"\b(?:FAIL(?:ED|URE)?)[ \t]*$"),
        (WEAK_FAIL, r"^[ \t]*Traceback \(most recent call last\)"),
        (WEAK_FAIL, r"^[ \t]*\w*(?:Assertion|Syntax|Reference|Type|Import|ModuleNotFound|Name|Runtime|Value)Error\b"),
        (WEAK_FAIL, r"^(?:Uncaught )?(?:Error|error|fatal|FATAL)(?:\[\w+\])?: "),
        (WEAK_FAIL, r"^[ \t]*(?:[✘✗✖❌]|\[[xX]\])[ \t]"),
        (WEAK_FAIL, r"\b[1-9]\d* (?:tests? )?failed[ \t.!]*$"),
        (WEAK_FAIL, r"^[ \t]*(?:Failures|Failed|Errors)[:=][ \t]*[1-9]"),
        (WEAK_PASS, r"(?i:^[ \t]*\[?(?:ok|pass(?:ed)?)\]?(?::|[ \t]|$))"),
        (WEAK_PASS, r"(?i:\b(?:ok|pass(?:ed)?)[ \t.!]*$)"),
        (WEAK_PASS, r"^[ \t]*[✓✔✅]"),
        (WEAK_PASS, r"\b(?:[Aa]ll |[1-9]\d* )(?:\w+ )?(?:tests?|checks?) (?:have )?passed\b"),
        (WEAK_PASS, r"\b[Tt]ests? passed\b"),
        (WEAK_PASS, r"全部通过"),
        (WEAK_PASS, r"\b[1-9]\d* passed\b"),
        (WEAK_PASS, r"\b[Ff]ail(?:ed|ures)?[: ]+0\b"),
        (WEAK_PASS, r"\b0 failed\b"),
        (WEAK_PASS, r"\bNo issues found\b"),
    ],
}

WRAPPERS = ("make", "npm")   # they report any command's failure, not only the test run's

# the words a count line uses, and what each one counts
_WORD = {"passed": "p", "passing": "p", "pass": "p", "xpassed": "p", "success": "p", "successes": "p", "expected fail": "x", "xfailed": "x", "failed as expected": "x", "known failure": "x", "known failures": "x",
         "failed": "f", "failing": "f", "fail": "f", "failure": "f", "failures": "f", "error": "f", "errors": "f", "subtest failed": "f", "subtests failed": "f", "subtest passed": "p", "subtests passed": "p", "interrupted": "f",
         "skipped": "s", "skip": "s", "skips": "s", "pending": "s", "ignored": "s", "todo": "s", "incomplete": "s", "deselected": "s", "excluded": "s", "did not run": "s", "flaky": "p"}


def _plain(pattern: str) -> str:
    """The pattern without its named groups, for joining with others."""
    return re.sub(r"\(\?P<\w+>", "(?:", pattern)


@functools.lru_cache(maxsize=None)
def tables():
    """(runner shapes, script shapes, one pattern any runner shape matches), compiled once and only when an output is read: the pre-command hook never needs them.
    Name, kind, compiled shape; the first shape to claim a line keeps it."""
    strong = [(name, kind, re.compile(rx, re.M)) for name, shapes in RUNNERS.items() for kind, rx in shapes if kind not in (WEAK_FAIL, WEAK_PASS)]
    weak = [(name, kind, re.compile(rx, re.M)) for name, shapes in RUNNERS.items() for kind, rx in shapes if kind in (WEAK_FAIL, WEAK_PASS)]
    anchored = [_plain(rx)[1:] for shapes in RUNNERS.values() for kind, rx in shapes if kind not in (WEAK_FAIL, WEAK_PASS)]   # every runner shape starts at `^`
    return strong, weak, re.compile("^(?:" + "|".join(anchored) + ")", re.M)


@functools.lru_cache(maxsize=None)
def check_shapes():
    return [(name, kind, re.compile(rx, re.M)) for name, shapes in CHECKERS.items() for kind, rx in shapes]


# ---------------------------------------------------------------- compilers and linters
# DIAG lines are real diagnostics. FOUND counts them when the group says more than 0. CLEAN is the tool saying it found nothing.
DIAG, FOUND, CLEAN = "diag", "found", "clean"
CHECKERS = {
    "typescript": [
        (DIAG, r"^\S[^\n]*\(\d+,\d+\): error TS\d+: "),
        (DIAG, r"^\S+:\d+:\d+ - error TS\d+: "),
        (DIAG, r"^Errors[ \t]+Files?$"),
    ],
    # tsc, ruff, mypy and biome all print this one
    "found": [(FOUND, r"^Found (?P<n>\d+) errors?\b")],
    # a tool that reports `0 error(s), 0 warning(s)` and `◇ Check passed`
    "summary": [(FOUND, r"^\W*(?P<n>\d+) errors?(?:\(s\))?[,.]?(?: \d+ warnings?(?:\(s\))?\b|[ \t]*$)"), (CLEAN, r"^\W*(?:Check|All checks?|Lint) passed\b"), (CLEAN, r"^\W*No issues found\b")],
    "mypy": [(DIAG, r"^\S+:\d+(?::\d+)?: error: "), (CLEAN, r"^Success: no issues found\b")],
    "pyright": [(FOUND, r"^[ \t]*(?P<n>\d+) errors?, \d+ warnings?, \d+ informations?\b"), (DIAG, r"^[ \t]*\S+:\d+:\d+ - error: "), (DIAG, r"^No source files found\b")],
    "eslint": [
        (FOUND, r"^✖ \d+ problems? \((?P<n>\d+) errors?, \d+ warnings?\)"),
        (DIAG, r"^[ \t]+\d+:\d+[ \t]+error[ \t]"),
        (DIAG, r"^ESLint found too many warnings\b"),
        (DIAG, r"\"errorCount\":[1-9]"),
    ],
    "ruff": [
        (DIAG, r"^\S+:\d+:\d+: [A-Z]+\d+ "),   # ruff and flake8; pylint's `I0021:` is an information message
        (DIAG, r"^invalid-syntax: "),
        (DIAG, r"^[A-Z]{1,4}\d{2,4} \S"),
        (DIAG, r"^Would reformat: "),
        (CLEAN, r"^All checks passed!"),
        (CLEAN, r"^\d+ files? already formatted\b"),
    ],
    "formatters": [
        (DIAG, r"^would reformat "),
        (DIAG, r"^\d+ files? would be reformatted\b"),
        (DIAG, r"^error: cannot format "),
        (DIAG, r"^\[warn\] Code style issues found\b"),
        (DIAG, r"^\[error\] "),
        (DIAG, r"^ERROR: \S[^\n]* Imports are incorrectly sorted\b"),
        (CLEAN, r"^All done!"),
        (CLEAN, r"^All matched files use Prettier code style!"),
    ],
    "pylint": [(DIAG, r"^\S+:\d+:\d+: [CRWEF]\d{4}: "), (FOUND, r"^Your code has been rated at (?P<rating>-?[\d.]+)/10\b")],
    "biome": [(DIAG, r"^[ \t]*[×✖] Some errors were emitted while\b"), (CLEAN, r"^Checked \d+ files? in \S+\. No fixes applied\.$")],
    "go": [(DIAG, r"^\S+\.go:\d+(?::\d+)?: "), (DIAG, r"^vet: "), (FOUND, r"^(?P<n>\d+) issues?[:.]$")],
    "rust": [(DIAG, r"^error(?:\[E\d+\])?: "), (CLEAN, r"^[ \t]*Finished `?\w+`?(?: profile)? ")],
    "dotnet": [(DIAG, r"^\S[^\n]*: error [A-Z]+\d+: "), (DIAG, r"^Build FAILED\.$"), (FOUND, r"^[ \t]*(?P<n>\d+) Error\(s\)$"), (CLEAN, r"^Build succeeded\.$")],
    "cc": [(DIAG, r"^\S+:\d+(?::\d+)?: (?:fatal )?error: "), (DIAG, r"^error: "), (CLEAN, r"^Build complete!")],
    "jvm": [(DIAG, r"^(?:\[ERROR\] )?BUILD FAILURE\b"), (DIAG, r"^BUILD FAILED\b"), (DIAG, r"^(?:\[ERROR\] )?COMPILATION ERROR\b"), (CLEAN, r"^(?:\[INFO\] )?BUILD SUCCESS")],
    "bundlers": [
        (DIAG, r"^error during build:"),
        (DIAG, r"^Build error occurred\b"),
        (DIAG, r"^Failed to compile\b"),
        (DIAG, r"^ERROR in "),
        (DIAG, r"^[ \t]+at (?:async )?\S[^\n]*[:(]\S+:\d+:\d+\)?$"),
        (CLEAN, r"^✓ built in\b"),
        (CLEAN, r"\bcompiled successfully\b"),
    ],
    "shell": [(DIAG, r"^(?:g?make)(?:\[\d+\])?: \*\*\* "), (DIAG, r"^npm (?:ERR!|error) "), (DIAG, r"^[ \t]*Traceback \(most recent call last\)"), (DIAG, r"^\w*Error: ")],
}

# ---------------------------------------------------------------- reading
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\^_]")   # colour, cursor control, hyperlinks
# what a wrapper puts before a runner's line: pnpm `packages/a test: `, turbo `web:test: `, Maven `[INFO] `, a CI log's timestamp, docker compose `api-1  | `
_PREFIX = re.compile(r"^(?:(?:[^\t\n]*\t[^\t\n]*\t)?\d{4}-\d\d-\d\dT[\d:.]+Z )?(?:\[(?:INFO|WARNING|ERROR)\] ?|[\w@./-]+ (?:test|check|lint|build)[:$] |[\w@./-]+:[a-zA-Z][\w-]*: |[\w.-]+[-_]\d+[ \t]+\| )?")
# a line none of the shapes could use is not worth a regex each
_WORTH_A_LOOK = re.compile(r"pass|fail|error|\bok\b|skip|success|✓|✔|✘|✗|✖|❌|✅|🎉|通过|traceback|\bno\b|notests|tests?\b|congratulations|\*\*\*|fatal|surefire|aborted|\bdone\b|pending|todo|flaky|did not run|interrupted|ignored|uncaught|unhandled|expected|deselected|excluded|examples?\b|\bruns\b|assertions?\b|\bfiles=|^1\.\.0\b|^Ran \d|exception|^\d+ issues?\b", re.I)
_CHECK_LOOK = re.compile(r"\d|error|pass|would|style|warn|×|✖|✓|compiled|built|succeeded|finished|all done|no issues|fatal|traceback|fail|vet:", re.I)
_LINE = 320   # a verdict is short; a long line (minified JSON, a progress bar) is cut, not scanned


def clean(text: str) -> str:
    """Without colour or cursor codes, and with a progress bar's carriage returns as line ends."""
    return ANSI.sub("", text or "").replace("\r\n", "\n").replace("\r", "\n")


def _digest(text: str) -> str:
    keep = []
    for line in text.split("\n"):
        line = _PREFIX.sub("", line[:_LINE], count=1)
        if _WORTH_A_LOOK.search(line):
            keep.append(line.rstrip())
    return "\n".join(keep)


def _int(value) -> int:
    return int(value) if value and value != "-" else 0


@dataclass
class Hit:
    runner: str
    kind: str
    line: str
    at: int = 0
    p: int = 0     # passed
    f: int = 0     # failed
    s: int = 0     # did not run: skipped, ignored, pending, excluded
    x: int = 0     # failed as expected
    t: int = -1    # total, when that is all the line says about passes
    ambiguous: bool = False
    shape: int = -1


def _count(name: str, m) -> Hit:
    g = m.groupdict()
    h = Hit(name, COUNT, m.group(0).split("\n")[-1].strip()[:160], m.start())
    h.p = _int(g.get("p"))
    h.f = _int(g.get("f")) + _int(g.get("e"))
    h.s = _int(g.get("s")) + _int(g.get("s2")) + _int(g.get("s3"))
    h.x = _int(g.get("x")) + _int(g.get("x2"))
    if g.get("words"):
        pairs = re.findall(r"(\d+) ([A-Za-z][a-z]*(?: [a-z]+)*)", g["words"]) + [(n, w) for w, n in re.findall(r"([A-Z][a-z]+): (\d+)", g["words"])]
        for n, w in pairs:
            slot = _WORD.get(w.lower())
            if slot:
                setattr(h, slot, getattr(h, slot) + int(n))
    if g.get("t"):
        h.t = int(g["t"])
    if g.get("t0") == "0":   # `ℹ tests 0`: says how many ran and nothing else
        h.t = 0
    if g.get("note"):      # TAP: `ok 3 - x # SKIP`
        h.s += 1
    if g.get("fx") is not None:   # XCTest: `with 1 failure (0 unexpected)`
        fx, u = int(g["fx"]), int(g["u"])
        h.f += u
        h.ambiguous = fx > 0 and u == 0
    if g.get("a") == "0":   # clojure.test: `Ran 1 tests containing 0 assertions`: it ran, and checked nothing
        h.t = 0
    if g.get("all") is not None:   # turbo: `Tasks: 2 successful, 3 total` counts tasks, not tests
        ok, total = int(g["ok"]), int(g["all"])
        h.f = max(total - ok, 0)
        h.kind = NOTE if h.f == 0 and total else COUNT
        h.t = 0 if not total else -1
    if h.t >= 0 and not h.p and not h.f:
        h.p = max(h.t - h.s - h.x, 0)
    return h


@dataclass
class Run:
    """What one command's output says about the run."""
    hits: list = field(default_factory=list)
    state: str = ""     # fail | pass | skipped | zero | "" when nothing was recognised
    line: str = ""      # the line that decided it
    passed: int = 0
    ambiguous: bool = False   # XCTest's `with 1 failure (0 unexpected)`: an expected failure on macOS, a real one on Linux
    weak: bool = False        # decided by a script's words, not a runner's verdict


def _hits(digest: str, shapes: list) -> list:
    hits, claimed = [], set()
    for shape, (name, kind, rx) in enumerate(shapes):
        for m in rx.finditer(digest):
            if m.start() in claimed:
                continue
            claimed.add(m.start())
            hit = _count(name, m) if kind == COUNT else Hit(name, kind, m.group(0).strip()[:160], m.start())
            hit.shape = shape
            hits.append(hit)
    hits.sort(key=lambda h: h.at)
    return hits


def _scan(digest: str) -> list:
    """The runners' lines. One joined pattern finds them, so a long verbose run costs one pass and each shape only sees lines that are some runner's."""
    strong, _weak, any_runner = tables()
    kept = []
    for m in any_runner.finditer(digest):
        end = digest.find("\n", m.end())
        kept.append(digest[m.start():end if end >= 0 else len(digest)])
    return _hits("\n".join(kept), strong)


def _adjust(hits: list) -> list:
    """Where the verdict alone is not enough and a runner's other lines settle it."""
    by = lambda runner, needle: [h for h in hits if h.runner == runner and needle in h.line]
    # go test: `ok` says nothing about tests that only skipped. With -v or -json the lines are there to count; without them the output cannot tell.
    go_ok = [h for h in hits if h.runner == "go" and h.kind == PASS]
    if go_ok:
        skipped = by("go", "--- SKIP:") + by("go", '"Action":"skip"')
        passed = by("go", "--- PASS:") + by("go", '"Action":"pass"')
        if skipped and not passed:
            for h in go_ok:
                h.kind = NOTE
            hits.append(Hit("go", COUNT, skipped[-1].line, skipped[-1].at, s=len(skipped)))
        elif by("go", "testing: warning: no tests to run") and not passed:
            for h in go_ok:
                h.kind = ZERO
    # Swift Testing and CTest count a skipped test as passed; each prints one line per skipped test
    ran = [h for h in hits if h.runner == "swift" and h.p]
    skips = [h for h in hits if h.runner == "swift" and h.kind == NOTE and " skipped" in h.line]
    if ran and skips:
        ran[-1].p = max(ran[-1].p - len(skips), 0)
        ran[-1].s += len(skips)
    runs = [h for h in hits if h.runner == "ctest" and h.kind == COUNT]
    skips = [h for h in hits if h.runner == "ctest" and h.kind == NOTE]
    if runs and skips:
        runs[-1].s += len(skips)
        runs[-1].p = max(runs[-1].p - len(skips), 0)
    # sbt prints a count whenever it ran tests; `[success]` with none means it had none
    if by("sbt", "[success] Total time") and not [h for h in hits if h.runner == "sbt" and h.kind in (COUNT, FAIL, ZERO)]:
        hits.append(Hit("sbt", ZERO, "[success] with no test count", hits[-1].at))
    # Maven: surefire ran, the build is green, and it printed no count at all
    if by("maven", "--- surefire:") and by("maven", "BUILD SUCCESS") and not [h for h in hits if h.runner == "maven" and h.kind in (COUNT, FAIL, ZERO)]:
        hits.append(Hit("maven", ZERO, "surefire ran and printed no test count", hits[-1].at))
    # node --test counts a file with no test() in it, or with none matching the filter, as one passing test named after the file
    counted = [h for h in hits if h.runner == "node" and h.p]
    if counted and by("node", ".js (") and sum(h.p for h in counted) <= len(by("node", ".js (")) + len(by("node", ".ts (")):
        for h in counted:
            h.p = 0
    return hits


def _last_run(hits: list) -> list:
    """The same tests ran more than once in one command: what came before the last summary's previous twin is history."""
    last = next((h for h in reversed(hits) if h.kind == COUNT and (h.p or h.f or h.t >= 0)), None)
    if last is None:
        return hits
    earlier = [h for h in hits if h.shape == last.shape and h.at < last.at]
    return [h for h in hits if h.at > earlier[-1].at] if earlier else hits


def read(text: str, last_run_only: bool = False, later_steps: bool = False) -> Run:
    """Read a run from cleaned output. A failure anywhere in one run is a failure: a later target, workspace or package passing does not cancel it.
    `last_run_only`: the command ran the same tests again, so the earlier summary is history.
    `later_steps`: other commands ran after the tests, so `make: ***` and `npm error` may be theirs: `npm test && npm run deploy`."""
    digest = _digest(text)
    hits = _adjust(_scan(digest))
    if later_steps:
        hits = [h for h in hits if h.runner not in WRAPPERS]
    run = decide(_last_run(hits) if last_run_only else hits)
    if run.state:
        return run
    return decide(hits + _hits(digest, tables()[1]))   # no runner said anything: a script's own words are all there is


def decide(hits: list) -> Run:
    run = Run(hits=hits)
    strong = [h for h in hits if h.kind not in (WEAK_FAIL, WEAK_PASS, NOTE)]
    bad = next((h for h in strong if h.kind == FAIL or h.f > 0), None)
    if bad:
        run.state, run.line = "fail", bad.line
        return run
    run.passed = sum(h.p for h in strong)
    counts = [h for h in strong if h.kind == COUNT]
    good = next((h for h in reversed(strong) if h.p > 0 or h.kind == PASS), None)
    if good:
        run.state, run.line = "pass", good.line
        run.ambiguous = any(h.ambiguous for h in counts)
        return run
    if any(h.ambiguous for h in counts):
        run.state, run.line, run.ambiguous = "pass", next(h.line for h in counts if h.ambiguous), True
        return run
    skipped = next((h for h in reversed(counts) if h.s > 0 or h.x > 0), None)
    if skipped:
        run.state, run.line = "skipped", skipped.line
        return run
    zero = next((h for h in reversed(strong) if h.kind == ZERO or (h.kind == COUNT and h.t == 0)), None)
    if zero:
        run.state, run.line = "zero", zero.line
        return run
    if counts:   # `ℹ tests 0`, `0 passing`: numbers, and none of them a test that ran
        run.state, run.line = "zero", counts[-1].line
        return run
    weak_bad = next((h for h in hits if h.kind == WEAK_FAIL), None)
    if weak_bad:
        run.state, run.line, run.weak = "fail", weak_bad.line, True
        return run
    weak_good = next((h for h in reversed(hits) if h.kind == WEAK_PASS), None)
    if weak_good:
        run.state, run.line, run.weak = "pass", weak_good.line, True
        return run
    return run


def clean_pass(text: str) -> bool:
    """A summary in the output says tests passed and none failed in it: one command may also hold a failing run on the old code."""
    return any((h.p > 0 and h.f == 0) or h.kind == PASS for h in _scan(_digest(clean(text))) if h.kind not in (WEAK_FAIL, WEAK_PASS))


def summary_line(text: str) -> str:
    """The line a person would read as this run's result."""
    return read(clean(text)).line


def has_summary(text: str) -> bool:
    """A runner's own verdict or count is in this output: a commit hook that printed one ran the tests."""
    run = read(clean(text))
    return bool(run.state) and not run.weak


@dataclass
class Check:
    """What a compiler's or linter's output says."""
    problem: str = ""   # a real diagnostic, or a count above 0
    clean: str = ""     # the tool said it found nothing


def read_check(text: str) -> Check:
    digest = "\n".join(line for line in (_PREFIX.sub("", line[:_LINE], count=1).rstrip() for line in text.split("\n")) if _CHECK_LOOK.search(line))
    found, claimed = Check(), set()
    for _name, kind, rx in check_shapes():
        for m in rx.finditer(digest):
            if m.start() in claimed:
                continue
            claimed.add(m.start())
            line = m.group(0).strip()[:160]
            if kind == DIAG:
                found.problem = found.problem or line
            elif kind == CLEAN:
                found.clean = found.clean or line
            else:
                g = m.groupdict()
                bad = float(g["rating"]) < 10 if g.get("rating") else int(g["n"]) > 0
                if bad:
                    found.problem = found.problem or line
                else:
                    found.clean = found.clean or line
    return found


# the word `error`, outside a file name, a quoted identifier, a warning or a zero count. A tool no table knows still gets caught this way.
_NOT_A_DIAGNOSTIC = re.compile(r"`[^`\n]*`|'[^'\n]*'|\"[^\"\n]*\"|\S*[/\\.][\w/\\.-]*|\b[\w-]*-[\w.-]*\b|\b0 errors?\b|\bno errors?\b|\berrors?[:=] ?0\b|\bwithout errors?\b", re.I)
_ERROR_WORD = re.compile(r"\b(?:error|fatal)\b|Traceback", re.I)
_SOURCE_LINE = re.compile(r"^[ \t]*\d*[ \t]*\|")   # a compiler quoting the source
_WARNING_LINE = re.compile(r"^[ \t]*(?:warn(?:ing)?\b|\[warn(?:ing)?\])", re.I)


def error_word(text: str) -> str:
    """The first line that uses `error` as a word about this run, for a tool no table knows."""
    for line in text.split("\n"):
        if len(line) > _LINE or _WARNING_LINE.match(line) or _SOURCE_LINE.match(line) or not _ERROR_WORD.search(line):
            continue
        if _ERROR_WORD.search(_NOT_A_DIAGNOSTIC.sub(" ", line)):
            return line.strip()[:160]
    return ""


def union(*kinds) -> re.Pattern:
    """Every shape of these kinds as one pattern, for the code that only asks whether a line of that sort is there."""
    return re.compile("|".join(_plain(rx) for shapes in RUNNERS.values() for kind, rx in shapes if kind in kinds), re.M)
