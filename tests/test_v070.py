"""0.7.0: findings from a pre-release review, each reproduced first and kept here as a regression test."""
import json

import pytest

from honestly import hooks, rules, config, prnote


# ------------------------------------------------------------------ pre-command check
BLOCK = [   # each one keeps the pass/fail verdict from the agent
    "pytest tests/ \\\n  -q | head -5",                 # backslash continuation
    "pytest -q | head -20",                             # the summary is printed last; head cuts it
    "pytest -rs | grep SKIP",                           # grep without the verdict words filters the summary out
    "pytest | grep -v warning",                         # "2 failed, 1 warning" contains the excluded word
    "pytest | wc -l",                                   # nothing of the output is left
    "npm test | grep -q PASS",
    "npm test --workspaces | tail -5",                  # each workspace prints its own result; an early failure scrolls away
    "npm test -ws 2>&1 | tail",
    "npm run build 2>&1 | head",                        # a build error is printed at the end
    "ruff check . | grep -q error",                     # a lint result is hidden only when nothing is shown
    "pytest | head # pipefail",                         # a comment is not pipefail
    "echo pipefail; pytest | head",                     # neither is the word
    "set +o pipefail; pytest | head",
    "pytest | head; set -o pipefail",                   # turned on after the pipe
    "python manage.py test | head",
    "bundle exec rails test | head",
    "php artisan test | head",
    "bun run test | head",
    "just test | head",
    "find . -name '*_test.py' | xargs pytest | head",
    "docker compose run app pytest | head",
    "time pytest | head",
    'bash -e -c "pytest | head"',
    "bash <<'EOF'\npytest | head\nEOF",                 # a heredoc fed to a shell runs
    "echo 'x<<y'; pytest | head",                       # `<<` inside quotes is not a heredoc
    "(pytest) | head",
    "pytest | tee log | head -3",                       # the last consumer decides what is visible
    "mvn -q clean test | head",
    "./gradlew clean test | head",
    "pnpm --filter web test | head",
    "yarn workspace web test | head",
    "node --test | head",
    "rg PIPESTATUS docs/; pytest | head",               # the word, not the variable
]
ALLOW = [
    "pytest -q | tail -3",                              # the summary line survives tail; the stop check reads it
    "python -m pytest -q 2>&1 | tail -15",
    "npm test 2>&1 | tail -25",
    'pytest | grep -E "passed|failed"',                 # the verdict words are kept
    "pytest | tee log",
    "npm test | cat",
    "ruff check . | head -20",                          # lint findings are printed first
    "tsc --noEmit | head -20",
    "npm run build | tail -15",
    "pdftotext cv.pdf - | grep Pages",                  # no pass/fail verdict at all
    "python scripts/check_final.py | sed -n 1,20p",     # a project script: the stop check reads its output
    "set -o pipefail; pytest | head",
    "set -euo pipefail\npytest -q | head -3",
    "set -o errexit -o pipefail; pytest | head",
    'bash -o pipefail -c "pytest | head"',
    "pytest 2>&1 | head; echo ${PIPESTATUS[0]}",
    "docker logs app | grep pytest | head",
    "journalctl -u ci | grep pytest | head",
    "history | grep pytest | head",
    "man pytest | head",
    "type pytest | head",
    "gh repo edit --add-topic pytest | head -2",
    'git commit -m "pytest | head"',
    "echo pytest | head",
    "make clean | head",
    "pytest --collect-only | head",
    "pytest > out.txt; head out.txt",
    "cat <<'EOF' > s.sh\npytest | head\nEOF",           # writing a script is not running it
    "/tmp/venv/bin/pip -q install pytest 2>&1 | head -1",
    "brew install ruff | tail",
    "go test ./... | tail -30",                         # Go prints FAIL again on the last line
    "cargo test 2>&1 | tail -20",                       # Cargo stops at the first failing binary and says so last
    "make test 2>&1 | tail -40",                        # make ends with "make: *** [test] Error 1"
    "go test ./... | grep -v '^ok'",                    # show only the failures
    "pytest | grep -v DeprecationWarning",
    "npx jest | grep -E 'Tests:'",
    "mvn test | grep 'Tests run:'",
    "cargo build 2>&1 | grep -E '^error' | head -30",   # the errors are what is left
    "tsc --noEmit | grep -c error",                     # a count of lint errors is the result
    "ruff check . | wc -l",
    "make run | head",
    "make -n test | head",
    "python make.py | head",
    "xcodebuild -list | head",
    "pytest --fixtures | head",
    "cargo test --no-run 2>&1 | head",
    "git show HEAD:tox.ini | head",
    "pgrep -f pytest | head",
    "npx mocha -r ts-node/register test/a.ts | tail",
    "pytest -n 4 | tail -3",
    "rg PIPESTATUS docs/ | head",
]


@pytest.mark.parametrize("cmd", BLOCK)
def test_pipeline_that_hides_a_test_result_is_refused(cmd):
    assert hooks.find_hidden_status(cmd) is not None, cmd


@pytest.mark.parametrize("cmd", ALLOW)
def test_pipeline_that_keeps_the_result_or_runs_no_test_is_allowed(cmd):
    assert hooks.find_hidden_status(cmd) is None, cmd


def test_message_says_how_the_result_was_lost():
    out = hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "pytest -q | head -20"}, "cwd": "/tmp"})
    text = json.dumps(out, ensure_ascii=False)
    assert "cut off the end of pytest's output with head" in text and "`| head`" in text
    out = hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "npm test --workspaces | tail -5"}, "cwd": "/tmp"})
    assert "earlier in the run would not show" in json.dumps(out, ensure_ascii=False)
    out = hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "pytest | tee log | head -3"}, "cwd": "/tmp"})
    assert "`| head`" in json.dumps(out, ensure_ascii=False)   # the pipe that hides the result, not the first one


# ------------------------------------------------------------------ stop check
def _stop(tmp_path, events, final):
    recs = [{"type": "user", "message": {"role": "user", "content": "fix the bug"}, "cwd": "/w/proj"}]
    for i, e in enumerate(events):
        tid = f"t{i}"
        if e[0] == "edit":
            recs.append({"type": "assistant", "message": {"model": "m", "content": [{"type": "tool_use", "id": tid, "name": "Edit", "input": {"file_path": e[1]}}]}})
            recs.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}})
        else:
            recs.append({"type": "assistant", "message": {"model": "m", "content": [{"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": e[1]}}]}})
            recs.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": e[2], "is_error": e[3]}]}})
    recs.append({"type": "assistant", "message": {"model": "m", "content": [{"type": "text", "text": final}]}})
    p = tmp_path / f"s{len(list(tmp_path.iterdir()))}.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return hooks.stop_hook({"transcript_path": str(p), "last_assistant_message": final, "cwd": "/w/proj"})


EDIT = ("edit", "/w/proj/src/app.py")


@pytest.mark.parametrize("is_error", [True, False])
def test_failure_summary_beyond_3000_characters_is_still_read(tmp_path, is_error):
    out = "\n".join(f"tests/test_a.py::test_{i} PASSED" for i in range(120)) + "\ntests/test_a.py::test_x FAILED\n=== 1 failed, 120 passed in 2s ==="
    assert len(out) > 3000
    assert _stop(tmp_path, [EDIT, ("bash", "pytest -v", out, is_error)], "All tests pass.") is not None


def test_long_cargo_output_with_failure_at_the_end(tmp_path):
    out = "running 4 tests\ntest a ... ok\n" * 200 + "test result: FAILED. 3 passed; 1 failed"
    assert _stop(tmp_path, [EDIT, ("bash", "cargo test", out, False)], "All tests pass.") is not None


def test_clip_keeps_the_end():
    from honestly.claude_code import clip_output
    text = "x" * 10000 + "LAST LINE"
    assert clip_output(text).endswith("LAST LINE") and len(clip_output(text)) < 3200


@pytest.mark.parametrize("output", ["==== 12 deselected in 0.02s ====", "======= 0 passed in 0.01s ======"])
def test_a_run_that_tested_nothing_backs_nothing(tmp_path, output):
    assert _stop(tmp_path, [EDIT, ("bash", "pytest -q -k zzz", output, False)], "All tests pass.") is not None


def test_errored_run_without_a_summary_backs_nothing(tmp_path):
    out = "ImportError while loading conftest '/w/proj/conftest.py'.\ntests PASSED marker in a log line"
    assert _stop(tmp_path, [EDIT, ("bash", "pytest -q", out, True)], "All tests pass.") is not None


def test_listing_tests_is_not_a_run(tmp_path):
    assert _stop(tmp_path, [EDIT, ("bash", "pytest --collect-only -q", "5 tests collected", False)], "All tests pass.") is not None


@pytest.mark.parametrize("final", ["Test suite passes.", "The tests are green."])
def test_more_ways_of_saying_it(tmp_path, final):
    assert _stop(tmp_path, [EDIT], final) is not None


def test_an_explicitly_earlier_result_is_not_a_claim(tmp_path):
    assert _stop(tmp_path, [EDIT], "Earlier tests passed, and I edited app.py.") is None


def test_passing_run_still_backs_the_claim(tmp_path):
    out = "\n".join(f"tests/test_a.py::test_{i} PASSED" for i in range(120)) + "\n=== 120 passed in 2s ==="
    assert _stop(tmp_path, [EDIT, ("bash", "pytest -v", out, False)], "All tests pass.") is None


# ------------------------------------------------------------------ install safety
def test_settings_path_follows_claude_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "alt"))
    assert hooks.settings_path() == str(tmp_path / "alt" / "settings.json")
    from honestly import agents
    assert agents.config_path("claude-code") == str(tmp_path / "alt" / "settings.json")


def test_settings_write_is_atomic_and_backups_never_overwrite(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{"model": "x"}')
    config.write_json_atomic(str(p), {"model": "x", "hooks": {}})
    config.write_json_atomic(str(p), {"model": "x"})
    baks = sorted(f.name for f in tmp_path.iterdir() if ".bak-honestly-" in f.name)
    assert len(baks) == 2   # same second, two backups, the original kept
    assert json.loads((tmp_path / baks[0]).read_text()) == {"model": "x"}
    assert json.loads(p.read_text()) == {"model": "x"}
    assert not [f for f in tmp_path.iterdir() if f.name.startswith(".honestly-")]   # no temp file left behind


def test_settings_write_goes_through_a_symlinked_dotfile(tmp_path):
    real = tmp_path / "dotfiles" / "settings.json"
    real.parent.mkdir()
    real.write_text("{}")
    link = tmp_path / "settings.json"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    config.write_json_atomic(str(link), {"a": 1}, backup=False)
    assert link.is_symlink() and json.loads(real.read_text()) == {"a": 1}


def test_pr_note_without_gh_explains_instead_of_a_traceback(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(SystemExit) as e:
        prnote.update_pr(str(tmp_path), "block")
    assert "GitHub CLI" in str(e.value)


def test_doctor_lists_a_project_that_relaxes_the_rules(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".honestly.json").write_text('{"strictness": "lenient", "ignore": ["pass"]}')
    from honestly import support
    report = support.doctor(zh=False)
    assert "relaxes the rules" in report and "strictness: lenient" in report


def test_earlier_only_excuses_an_explicitly_earlier_result():
    assert rules.NOT_A_CLAIM.search("Tests passed earlier.")
    assert not rules.NOT_A_CLAIM.search("The bug I mentioned earlier is fixed now.")   # a real claim about now


def test_clip_keeps_a_summary_printed_in_the_middle():
    from honestly.claude_code import clip_output
    text = "." * 2000 + "\n39 passed in 1.00s\n" + "lint line\n" * 600
    assert "39 passed in 1.00s" in clip_output(text)


def test_a_lint_tool_count_after_the_tests_is_not_the_test_summary(tmp_path):
    out = "....\n39 passed in 1.00s\nE501 Line too long\nFound 4 errors."
    assert _stop(tmp_path, [EDIT, ("bash", "set -o pipefail; uv run pytest -q 2>&1; ruff check", out, True)], "39 tests pass.") is None


def test_a_refused_command_never_pops_a_desktop_notification(monkeypatch):
    calls = []
    monkeypatch.setattr(hooks, "_notify", lambda *a, **k: calls.append(a))
    assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "pytest -q | head -3"}, "cwd": "/tmp"}) is not None
    assert calls == []
    assert hooks.NOTIFY_GAP >= 300


def test_stop_message_says_what_actually_happened(tmp_path):
    out = _stop(tmp_path, [EDIT, ("bash", "python3 -c 'from app import f; print(f(1))'", "1", False)], "All 4 tests pass.")
    assert "no test runner ran after editing app.py" in out["systemMessage"]   # a quick snippet is not the test suite
    out = _stop(tmp_path, [EDIT, ("bash", "pytest -q", "1 failed, 3 passed in 0.1s", True)], "All 4 tests pass.")
    assert "reported a failure" in out["systemMessage"]                 # a failing run is not "no check"
    out = _stop(tmp_path, [EDIT, ("bash", "npm run build", "Error: Cannot find module", True)], "The build succeeds.")
    assert "build" in out["systemMessage"] and "no test ran" not in out["systemMessage"]


def test_tests_that_fail_on_main_are_proof_not_a_failure(tmp_path):
    # found on a real session: the agent ran the new tests with the fix, then on main to show they catch the bug
    runs = [EDIT, ("bash", "pytest -q tests/test_new.py", "3 passed in 0.1s", False),
            ("bash", "cd /tmp/main-copy && pytest -q tests/test_new.py", "3 failed in 0.1s", True)]
    assert _stop(tmp_path, runs, "The new tests pass with the fix and fail on main.") is None
    assert _stop(tmp_path, runs[:1] + runs[2:], "The new tests pass with the fix and fail on main.") is not None   # no passing run at all
    assert _stop(tmp_path, [EDIT], "修复前 7 个新测试失败，修复后全部通过。") is not None   # still a claim that needs a run


def test_more_sentences_note_agrees_in_number(tmp_path):
    out = _stop(tmp_path, [EDIT], "Fixed the bug. All tests pass.")
    assert "1 more sentence in this reply has the same problem" in out["systemMessage"]


@pytest.mark.parametrize("out", ["?   \tacme/cmd\t[no test files]\nok  \tacme/pkg\t0.012s\n", "test result: ok. 12 passed; 0 failed\n   Doc-tests app\nrunning 0 tests\ntest result: ok. 0 passed; 0 failed\n"])
def test_go_and_rust_runs_with_an_empty_package_still_back_a_pass(tmp_path, out):
    cmd = "go test ./..." if "acme" in out else "cargo test"
    assert _stop(tmp_path, [EDIT, ("bash", cmd, out, False)], "All tests pass.") is None


def test_earlier_does_not_hide_a_claim_about_now():
    assert not rules.NOT_A_CLAIM.search("The flaky test passed earlier; I fixed the race and all tests pass now.")
    assert not rules.NOT_A_CLAIM.search("Fixed the regression from the previous commit; all tests pass.")


def _stop_after_block(tmp_path, first, then, final, active=True):
    """A held reply, Claude Code's "Stop hook feedback" message, then the agent's answer."""
    recs = [{"type": "user", "message": {"role": "user", "content": "fix the bug"}, "cwd": "/w/proj"}]
    def tools(events, base):
        out = []
        for i, e in enumerate(events):
            tid = f"t{base}{i}"
            if e[0] == "edit":
                out.append({"type": "assistant", "message": {"model": "m", "content": [{"type": "tool_use", "id": tid, "name": "Edit", "input": {"file_path": e[1]}}]}})
                out.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}})
            else:
                out.append({"type": "assistant", "message": {"model": "m", "content": [{"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": e[1]}}]}})
                out.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": e[2], "is_error": e[3]}]}})
        return out
    recs += tools(first, "a")
    recs.append({"type": "assistant", "message": {"model": "m", "content": [{"type": "text", "text": "Fixed, all 4 tests pass."}]}})
    recs.append({"type": "user", "message": {"role": "user", "content": "Stop hook feedback: ⚠️ honestly blocked this reply: ..."}})
    recs += tools(then, "b")
    recs.append({"type": "assistant", "message": {"model": "m", "content": [{"type": "text", "text": final}]}})
    p = tmp_path / "after.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return hooks.stop_hook({"transcript_path": str(p), "last_assistant_message": final, "cwd": "/w/proj", "stop_hook_active": active})


def test_answer_to_a_block_without_a_test_run_gets_a_warning_not_a_second_block(tmp_path):
    out = _stop_after_block(tmp_path, [EDIT], [("bash", "python3 -c 'import test_app; test_app.test_a()'", "PASS", False)], "Re-checked: all 4 tests pass.")
    assert out is not None and "decision" not in out and "still says" in out["systemMessage"]


def test_answer_to_a_block_with_a_real_test_run_passes_quietly(tmp_path):
    out = _stop_after_block(tmp_path, [EDIT], [("bash", "pytest -q", "4 passed in 0.01s", False)], "I ran pytest: 4 passed. All 4 tests pass.")
    assert out is None


def test_edited_name_is_a_file_or_nothing():
    assert hooks._edited_name("Edit: /w/proj/src/app.py") == "app.py"
    assert hooks._edited_name("Bash: sed -i 's/a/b/' src/app.py") == "app.py"
    assert hooks._edited_name("Bash: git stash && pytest -q; git stash pop") == ""


@pytest.mark.parametrize("honest", [
    "已修改 pricing.py,但我**没有运行测试**,所以不能说 4 个测试都通过了。",   # blocked by mistake while recording the demo
    "我没有跑测试，无法确认 4 个测试都通过。",
    "I changed pricing.py but didn't run the tests, so I can't say all 4 pass.",
    "The fix is in place; I cannot confirm the tests pass without running them.",
])
def test_an_honest_not_verified_is_not_a_claim(tmp_path, honest):
    assert _stop(tmp_path, [EDIT], honest) is None


@pytest.mark.parametrize("claim", [
    "我之前没跑测试，现在跑了，4 个测试都通过了。",
    "I didn't run the tests at first, so I ran them now and all 4 tests pass.",
])
def test_not_running_then_running_is_still_a_claim(tmp_path, claim):
    assert _stop(tmp_path, [EDIT], claim) is not None
