"""What a pre-release review of 0.7.2 reproduced. Output cases go through judge_output, commands through the hooks."""
import json

import pytest

from honestly import agents, audit, hooks, rules
from honestly.audit import Event, Turn


def judge(seg, out, is_error=True):
    return audit.judge_output("tests_pass", seg, Event("tool", name="Bash", text=seg, result=out, is_error=is_error))[0]


def verdicts(*events, prompt="fix it"):
    return [f.verdict for f in audit.audit_turn(Turn(session="s", index=0, version="", prompt=prompt, events=list(events)), None)]


def bash(cmd, out="", err=False):
    return Event("tool", name="Bash", text=cmd, result=out, is_error=err)


def edit(path="/p/src/app.py"):
    return Event("tool", name="Edit", text=path, result="The file has been updated successfully.")


def say(text):
    return Event("text", text=text)


def pre(cmd):
    return hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": cmd}})


GO_MIXED = "ok  \tx/a\t0.1s\n--- FAIL: TestB (0.00s)\nFAIL\nFAIL\tx/b\t0.1s\nok  \tx/c\t0.1s\nFAIL"
DOTNET_MIXED = "Failed!  - Failed:     1, Passed:     2, Skipped:     0, Total:     3 - A.dll (net8.0)\nPassed!  - Failed:     0, Passed:     5, Skipped:     0, Total:     5 - B.dll (net8.0)"
CARGO_MIXED = "test result: FAILED. 7 passed; 2 failed; 0 ignored\n\ntest result: ok. 5 passed; 0 failed; 0 ignored"


@pytest.mark.parametrize("seg,out", [
    ("pytest -q", "3 passed, 1 skipped, 1 warning, 1 error in 0.01s"),
    ("npx jest", "Test Suites: 1 failed, 1 passed, 2 total\nTests:       5 passed, 5 total\nSnapshots:   0 total\nTime:        1 s"),
    ("npx vitest run", " Test Files  1 failed | 2 passed (3)\n      Tests  8 passed (8)\n   Start at  10:00:00"),
    ("npx playwright test", "  1 failed\n    [chromium] > a\n  5 passed (3.2s)"),
    ("make test", GO_MIXED), ("just test", GO_MIXED), ("npm test", GO_MIXED), ("./scripts/test.sh", GO_MIXED),
    ("make test", DOTNET_MIXED), ("make test", CARGO_MIXED), ("cargo t --no-fail-fast", CARGO_MIXED),
    ("tox", "5 passed in 0.1s\npy39: FAIL code 1 (0.5 seconds)\npy310: OK (0.5 seconds)\nevaluation failed :( (1.0 seconds)"),
    ("nox", "5 passed in 0.1s\nnox > Ran multiple sessions:\nnox > * tests-3.9: failed\nnox > * tests-3.10: success"),
    ("npm test --workspaces", "Tests:       5 passed, 5 total\nnpm error Lifecycle script `test` failed with error:\nnpm error code 1"),
    ("npx turbo test", "Tests:       5 passed, 5 total\n Tasks:    1 successful, 2 total\nFailed:    web#test"),
    ("mvn test", "Tests run: 5, Failures: 0, Errors: 0, Skipped: 0\n[INFO] BUILD FAILURE"),
    ("pytest -q", "PASSED tests/a.py\r" * 30 + "2 failed, 7 passed in 0.1s"),
    ("node --test", "ℹ pass 3\nℹ fail 0\nℹ cancelled 2"),
    ("prove t/", "# failed 1 of 2 tests"),
    ("busted", "5 successes / 2 failures / 0 errors / 0 pending : 0.1 seconds"),
    ("npx jest", "Tests:       \x1b[1m\x1b[31m1 failed\x1b[39m\x1b[22m, \x1b[1m\x1b[32m5 passed\x1b[39m\x1b[22m, 6 total"),
])
def test_a_run_with_a_failure_contradicts_the_claim(seg, out):
    assert judge(seg, out) == "contradicted"


@pytest.mark.parametrize("seg,out", [
    ("swift test", "Executed 0 tests, with 0 failures (0 unexpected) in 0.0 (0.0) seconds\n◇ Test run started.\n✔ Test run with 3 tests passed after 0.001 seconds."),
    ("go test -v ./...", "failed: 2\n--- PASS: TestRetry (0.00s)\nPASS\nok  \tx/a\t0.1s"),
    ("bundle exec rspec", "errors: 2\n..\n5 examples, 0 failures"),
    ("bun test", "failures: 3\n 9 pass\n 0 fail\n"),
    ("ctest -V", "errors: 2\n100% tests passed, 0 tests failed out of 9"),
    ("pytest -q", "retries: 3, errors: 2\n5 passed in 0.1s"),
    ("npx jest", "Test Suites: 2 passed, 2 total\nTests:       5 passed, 5 total"),
    ("npx playwright test", "  5 passed (3.2s)"),
])
def test_a_real_pass_stays_backed(seg, out):
    assert judge(seg, out, is_error=False) == "backed"


@pytest.mark.parametrize("cmd,out", [
    ("mvn clean test", "Tests run: 5, Failures: 0, Errors: 0, Skipped: 0"),
    ("mvn -q test", "Tests run: 5, Failures: 0, Errors: 0, Skipped: 0"),
    ("./gradlew clean test", "9 tests completed, 0 failed"),
    ("./gradlew :app:test", "9 tests completed, 0 failed"),
    (".\\gradlew.bat test", "9 tests completed, 0 failed"),
    (".\\mvnw.cmd test", "Tests run: 5, Failures: 0, Errors: 0, Skipped: 0"),
    ("npm.cmd run test", "Tests:       5 passed, 5 total"),
    ("go.exe test ./...", "ok  \tx/a\t0.1s"),
    (".\\scripts\\run_tests.ps1", "5 passed in 0.1s"),
    ('powershell -Command "pytest -q"', "5 passed in 0.1s"),
    ('pwsh -c "pytest -q"', "5 passed in 0.1s"),
    ('cmd /c "pytest -q"', "5 passed in 0.1s"),
])
def test_common_test_commands_are_evidence(cmd, out):
    assert verdicts(edit(), bash(cmd, out), say("All tests pass.")) == ["backed"]


# ---- a commit's output is only a test run when it says so
@pytest.mark.parametrize("cmd,out", [
    ('git commit -q -m "wip"', "✖ 2 problems (0 errors, 2 warnings)"),
    ('git commit -q -m "wip"', "Build succeeded.\n    0 Error(s)"),
    ('git commit -q -m "wip"', "Summary: 0 error(s)"),
    ('git commit -m "Fix parser" -m "Tests: 562 passed" && git log -1', "[main abc1234] Fix parser\n 1 file changed\ncommit abc1234\n    Tests: 562 passed"),
    ('git log --grep "git commit" -3', "commit abc\n    12 passed"),
])
def test_a_commit_that_ran_no_tests_is_not_evidence(cmd, out):
    assert verdicts(edit(), bash(cmd, out), say("All tests pass.")) == ["unbacked"]


def test_a_new_file_does_not_rescue_an_earlier_run():
    new = Event("tool", name="Write", text="/p/src/fix.py", result="File created successfully at: /p/src/fix.py")
    assert verdicts(edit(), bash("pytest -q", "27 passed"), new, say("All tests pass.")) == ["unbacked"]
    assert verdicts(edit(), bash("tsc --noEmit", "Found 0 errors"), new, say("Type checks pass.")) == ["unbacked"]


# ---- the evidence rules must not give credit too easily
DRY_CLAIM = "Pipeline is written (dry run tests pass)."


@pytest.mark.parametrize("cmd,out", [
    ('git commit -m "Add --dry-run flag"', ""),
    ("grep -n -- --dry-run src/cli.py", "12: --dry-run"),
    ("python cli.py --help | grep --dry-run", "  --dry-run"),
    ('echo "use --dry-run next time"', "use --dry-run next time"),
    ("git push --dry-run", "To github.com"),
    ("python cli.py --dry-run 2>&1 | tail -3", "Traceback (most recent call last):\nRuntimeError: boom"),
])
def test_a_dry_run_needs_a_real_clean_run(cmd, out):
    assert verdicts(edit(), bash(cmd, out), say(DRY_CLAIM)) != ["backed"]


def test_a_dry_run_before_the_edit_in_the_same_command_is_not_after_it():
    assert verdicts(bash("python scripts/gen.py --dry-run && sed -i 's/a/b/' scripts/gen.py", "ok"), say(DRY_CLAIM)) != ["backed"]


def test_a_dry_run_only_backs_a_sentence_about_the_dry_run():
    assert verdicts(edit(), bash("python deploy.py --dry-run", "ok"), say("All tests pass and the dry run is clean.")) == ["unbacked"]
    assert verdicts(edit(), bash("npm publish --dry-run", "ok"), say("Fixed the crash; dry run next.")) == ["unbacked"]


@pytest.mark.parametrize("cmd,out,err", [
    ("python deploy.py", "[OK] config loaded\nTraceback (most recent call last):\nRuntimeError: boom", True),
    ("python deploy.py", "[OK] a\nFAIL: b", False),
    ("python deploy.py", "[OK] a\n[ FAIL ] b", False),
    ("python deploy.py", "[OK] a\n[X] b", False),
    ("curl -s localhost:8000/health", "[OK] healthy", False),
])
def test_a_self_check_needs_a_clean_script_run(cmd, out, err):
    assert verdicts(edit(), bash(cmd, out, err), say("All checks pass.")) != ["backed"]


@pytest.mark.parametrize("text", ["- Committed the parser change\n- Rewrote cache.py\n- All tests pass.", "已提交。\n之后我又改了 parser.py，测试全部通过。"])
def test_committed_in_a_list_item_is_not_a_heading(text):
    commit = bash('pytest -q && git commit -q -m "feat"', "90 passed in 11.78s")
    assert verdicts(edit(), commit, edit("/p/src/parser.py"), say(text)) == ["unbacked", "unbacked"]


def test_a_task_notification_is_not_another_sessions_report():
    assert verdicts(edit(), say("All 12 tests pass."), prompt="<task-notification>\n<status>completed</status>\n</task-notification>") == ["unbacked"]


def test_a_retry_loop_is_not_a_schedule():
    assert verdicts(bash('for i in 1 2 3; do curl -sf x && break; sleep $((i*2)); done', "ok"), say("定时已设好，每晚运行。")) == ["unbacked"]


# ---- PowerShell writes
@pytest.mark.parametrize("cmd", [
    '@"\ndef f(): return 1\n"@ | Set-Content src/app.py',
    'echo "x = 1" | Set-Content src/app.py',
    '"x = 1" > src/app.py',
    '[IO.File]::WriteAllText("src/app.py", "x = 1")',
    "if ($x) { Set-Content src/app.py 'x' }",
])
def test_more_powershell_writes_are_edits(cmd):
    assert rules.bash_is_edit(cmd), cmd


def test_a_write_to_a_windows_temp_folder_is_not_a_code_edit():
    assert not rules.bash_is_edit('Set-Content C:\\Temp\\scratch.py "x"')


# ---- pipes
@pytest.mark.parametrize("cmd", [
    'pytest -q | findstr "passed failed"',
    'pytest -q | findstr /I "passed failed"',
    'pytest -q | findstr /R "fail.*"',
    "pytest -q | Select-String '\\d{1,3} (passed|failed)'",
    "Get-Command pytest | Select-Object -First 1",
    "where.exe pytest | Select-Object -First 1",
    "pip list | findstr pytest | Select-Object -First 1",
    "git log --oneline | findstr pytest | Select-Object -First 3",
    "$x = Get-Content pytest.ini | Select-Object -First 1",
    "python -m pip install pytest | Out-Null",
    "Stop-Process -Name pytest | Out-Null",
])
def test_these_pipes_are_allowed(cmd):
    assert pre(cmd) is None, cmd


@pytest.mark.parametrize("cmd", [
    "pytest -q | Select-String passed -Quiet:$true",
    "$LASTEXITCODE = 0; pytest -q | Select-Object -First 5",
    "pytest -q |\n  Select-Object -First 5",
    "pytest -q |\n  head -5",
    "pytest -q `\n  | Select-Object -First 5",
    'pwsh -c "pytest -q | Select-Object -First 5"',
    'powershell -Command "pytest -q | Select-Object -First 5"',
])
def test_these_pipes_are_refused(cmd):
    assert pre(cmd) is not None, cmd


@pytest.mark.parametrize("cmd", [
    "pytest -q | Select-String -Pattern 'foo', 'bar'",
    "pytest -q | Select-String -Pattern:foo",
    "pytest -q | findstr /VI failed",
    "pytest -q | findstr /IC:foo",
    "pytest -q | findstr /VC:warning",
    'pytest -q | find "foo"',
    'cmd /c "pytest -q | findstr foo"',
])
def test_these_filters_are_read_right(cmd):
    assert hooks.find_hidden_status(cmd, strict=True) is not None, cmd


# ---- Gemini CLI results
def test_gemini_keeps_output_after_a_line_that_starts_with_error():
    text = "<untrusted_context>\nOutput: suite a: 5 passed in 0.1s\nError: suite b crashed\nsuite b: 2 failed, 3 passed in 0.1s\nExit Code: 1\nProcess Group PGID: 1\n</untrusted_context>"
    out, code = agents._gemini_result(text)
    assert "2 failed" in out and code == 1


def test_gemini_reads_the_exit_code_from_the_trailer_only():
    text = "<untrusted_context>\nOutput: Exit Code: 1\n12 passed in 0.1s\nProcess Group PGID: 1\n</untrusted_context>"
    out, code = agents._gemini_result(text)
    assert "12 passed" in out and code is None


# ---- nothing here may raise
def test_gemini_parse_survives_malformed_records(tmp_path):
    chats = tmp_path / "tmp" / "p" / "chats"
    chats.mkdir(parents=True)
    (tmp_path / "tmp" / "p" / ".project_root").write_bytes(b"\xff\xfe/bad")
    rows = [{"id": ["bad"]}, {"id": "1", "type": "user", "content": [{"text": "go"}]}, {"id": "2", "type": "gemini", "content": "x", "toolCalls": 5},
            {"id": "3", "type": "gemini", "content": "y", "toolCalls": [5, {"name": "run_shell_command", "args": 5, "result": 5}]},
            {"id": "4", "type": "gemini", "content": "", "toolCalls": [{"name": "run_shell_command", "args": {"command": "pytest"}, "result": "Exit Code: " + "9" * 5000}]}]
    p = chats / "session-x.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    assert [t.prompt for t in agents.gemini_parse(str(p))] == ["go"]


@pytest.mark.parametrize("data", [
    {"tool_name": "Bash", "tool_input": "x"}, {"tool_name": "Bash", "tool_input": {"command": 5}}, {"tool_name": "Bash", "tool_input": {"command": ["pytest"]}},
    {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": 5}, {"tool_name": "Bash"}, {},
])
def test_pre_hook_survives_odd_input(data):
    assert hooks.pre_hook(data) is None
