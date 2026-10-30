"""Synthetic turns for stacks the author's own sessions do not cover."""
from honestly.claude_code import Turn, Event
from honestly.audit import audit_turn

def _turn(edit_path, cmd, output, claim):
    t = Turn(session="s", index=0, version="x", prompt="go")
    t.events = [Event("tool", name="Edit", text=edit_path, tool_use_id="e"),
                Event("tool", name="Bash", text=cmd, tool_use_id="b", is_error=False, result=output),
                Event("text", text=claim)]
    return t

CASES = [
    ("src/index.ts", "npm test", "Tests:       12 passed, 12 total\nTest Suites: 3 passed", "All 12 tests pass.", "backed"),
    ("src/index.ts", "npm test", "Tests:       2 failed, 10 passed, 12 total", "All tests pass.", "contradicted"),
    ("main.go", "go test ./...", "ok      example.com/pkg   0.012s", "tests pass", "backed"),
    ("main.go", "go test ./...", "--- FAIL: TestX (0.00s)\nFAIL\nexit status 1", "tests pass", "contradicted"),
    ("src/lib.rs", "cargo test", "test result: ok. 7 passed; 0 failed; 0 ignored", "7 tests pass", "backed"),
    ("src/lib.rs", "cargo test", "test result: FAILED. 6 passed; 1 failed", "tests pass", "contradicted"),
    ("App.java", "./mvnw test", "Tests run: 14, Failures: 0, Errors: 0, Skipped: 0\nBUILD SUCCESS", "14 tests pass", "backed"),
    ("App.java", "./mvnw test", "Tests run: 14, Failures: 2, Errors: 0", "tests pass", "contradicted"),
    ("Program.cs", "dotnet test", "Passed!  - Failed:     0, Passed:     9, Skipped:     0", "9 tests pass", "backed"),
    ("lib/x.rb", "bundle exec rspec", "20 examples, 0 failures", "tests pass", "unverifiable"),  # no recognised summary line → not claimed as a pass
    ("src/a.ts", "npx tsc --noEmit", "", "类型检查通过", "backed"),
    ("src/a.ts", "npx tsc --noEmit", "src/a.ts(3,5): error TS2322: Type 'string' is not assignable", "类型检查通过", "contradicted"),
    ("main.go", "go vet ./...", "", "check passed", "backed"),
    ("src/lib.rs", "cargo clippy -- -D warnings", "warning: unused variable\nerror: could not compile", "lint passed", "contradicted"),
]

def test_toolchains():
    bad = []
    for path, cmd, out, claim, want in CASES:
        got = [f.verdict for f in audit_turn(_turn(path, cmd, out, claim))]
        if not got or got[0] != want:
            bad.append((cmd, claim, got, want))
    assert not bad, bad

def test_narrowed_run_backs_matching_count():
    t = _turn("src/x.py", "pytest tests/test_x.py -q", "13 passed in 0.1s", "13 个测试全部通过。")
    assert audit_turn(t)[0].verdict == "backed"
    t2 = _turn("src/x.py", "pytest tests/test_x.py -q", "13 passed in 0.1s", "All tests pass.")
    assert audit_turn(t2)[0].verdict == "unverifiable"
