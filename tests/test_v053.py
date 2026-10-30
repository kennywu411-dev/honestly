"""Regressions fixed in 0.5.3."""
import json
import os
import sys

import pytest

from honestly import rules as R, hooks, audit, support, update
from honestly.claude_code import Event


# ---------------------------------------------------------------- paths
def test_code_under_prompt_tmp_or_notes_dirs_is_still_code():
    for p in ["/Users/me/proj/src/prompts/builder.py", "/Users/me/proj/tmp/app.py", "/Users/me/tmp/src/app.py",
              "/Users/me/proj/lib/prompt_builder.ts", "/Users/me/proj/app/reports/views.py", "/Users/me/proj/src/notes/model.py",
              "/Users/me/proj/README_parser.py", "/Users/me/proj/src/environment.py"]:
        assert not R.path_is_doc(p), p
    for p in ["/Users/me/proj/PROMPT.md", "/Users/me/proj/prompts/system.txt", "/Users/me/proj/notes/plan.md", "/tmp/x/src/app.py",
              "/private/tmp/x/src/app.py", "/Users/me/proj/README.md", "/Users/me/proj/README", "/Users/me/proj/.env", "/Users/me/proj/.env.local",
              "/Users/me/proj/docs/guide.md", "/Users/me/proj/.cursor/rules/honestly.mdc"]:
        assert R.path_is_doc(p), p


def test_tmp_substring_in_a_project_path_does_not_disarm_bash_edits():
    assert R.bash_is_edit("sed -i '' 's/a/b/' /Users/me/proj/tmp/app.py")
    assert not R.bash_is_edit("sed -i '' 's/a/b/' /tmp/proj/app.py")
    assert not R.bash_is_edit("cat > /private/tmp/x/app.py <<'EOF'\nx=1\nEOF")


# ---------------------------------------------------------------- shell parsing
def test_apostrophe_in_a_comment_does_not_swallow_the_next_command():
    cmd = "sed -i '' 's/foo/bar/' src/app.py  # fix the user's name\npytest -q"
    segs = R.segments(cmd)
    assert any("pytest" in s.text and "sed -i" not in s.text for s in segs)
    assert R.bash_verifies(cmd, {"test"}, after_edit_only=True)
    out = hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "cd proj  # user's dir\npytest -q | tail -3"}})
    assert out is not None


def test_hash_inside_quotes_or_variables_is_kept():
    segs = R.segments('git commit -m "fix #12 and user\'s bug" && echo ${#arr} && pytest -q')
    assert len(segs) == 3 and "#12" in segs[0].text and "${#arr}" in segs[1].text


def test_patch_counts_as_an_edit_only_as_the_verb():
    for cmd in ['grep -rn "mock.patch" tests/', 'rg "patch(" src/', "grep -rn patch src/ | head", "git diff > fix.patch"]:
        assert not R.bash_is_edit(cmd), cmd
    assert R.bash_is_edit("patch -p1 < fix.patch")
    assert R.bash_is_edit("cat fix.patch | patch -p1")


# ---------------------------------------------------------------- claims
def test_ten_errors_and_transitive_passes_are_not_claims():
    assert R.find_claims("ruff still reports 10 errors remaining.") == []
    assert R.find_claims("This test passes a mock client into the handler.") == []
    assert R.find_claims("The helper test passes the config path through.") == []
    assert [h.category for h in R.find_claims("ruff reports 0 errors.")] == ["checks_pass"]
    assert [h.category for h in R.find_claims("All 12 tests pass now.")] == ["tests_pass"]
    assert [h.category for h in R.find_claims("Tests pass again after the fix.")] == ["tests_pass"]


def test_a_question_mark_ends_a_sentence():
    cats = [h.category for h in R.find_claims("What did I change? I fixed the parser and all tests pass.")]
    assert cats == ["tests_pass"] or cats == ["fixed"]
    assert R.find_claims("Do all tests pass?") == []
    assert R.find_claims("Make sure all tests pass before merging.") == []
    assert [h.category for h in R.find_claims("All tests pass, make sure to deploy afterwards.")] == ["tests_pass"]
    assert R.find_claims("Until the tests pass, keep the branch open.") == []


# ---------------------------------------------------------------- verification
def test_installing_a_test_tool_is_not_a_test_run():
    for cmd in ["pip install pytest", "pip list | grep pytest", "npm install jest", "uv pip install pytest", "pip3 show pytest"]:
        assert not R.bash_verifies(cmd, {"test"}), cmd
    assert R.bash_verifies("pip install -e . && pytest -q", {"test"})


def test_go_test_fail_lines_are_contradicted():
    out = "ok  \tpkg/a\t0.1s\n--- FAIL: TestX (0.00s)\nFAIL\nFAIL\tpkg/b\t0.2s\nFAIL\n"
    ev = Event("tool", name="Bash", text="go test ./...", result=out, is_error=True)
    verdict, _ = audit.judge_output("tests_pass", "go test ./...", ev)
    assert verdict == "contradicted"
    ok = Event("tool", name="Bash", text="go test ./...", result="ok  \tpkg/a\t0.1s\nok  \tpkg/b\t0.2s\n", is_error=False)
    assert audit.judge_output("tests_pass", "go test ./...", ok)[0] == "backed"


def test_a_run_that_collects_no_tests_does_not_back_a_pass_claim():
    outs = {
        "pytest -q tests/": "collected 0 items\n\nno tests ran in 0.01s\n",
        "python -m unittest": "\n----------------------------------------------------------------------\nRan 0 tests in 0.000s\n\nOK\n",
        "cargo test": "running 0 tests\n\ntest result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out\n",
        "go test ./...": "ok  \tpkg/a\t0.001s [no tests to run]\n",
        "npx jest": "No tests found, exiting with code 1\n",
        "npx mocha": "\n  0 passing (2ms)\n",
        "mvn test": "Tests run: 0, Failures: 0, Errors: 0, Skipped: 0\n",
    }
    for cmd, out in outs.items():
        ev = Event("tool", name="Bash", text=cmd, result=out, is_error=cmd == "npx jest")
        verdict, why = audit.judge_output("tests_pass", cmd, ev)
        assert verdict == "unbacked" and "no tests" in why, (cmd, verdict, why)
    # real runs are untouched, including a later run in the same command after an empty one
    ev = Event("tool", name="Bash", text="pytest -q", result="collected 12 items\n12 passed in 0.3s\n", is_error=False)
    assert audit.judge_output("tests_pass", "pytest -q", ev)[0] == "backed"
    ev = Event("tool", name="Bash", text="pytest -q a.py; pytest -q b.py", result="no tests ran in 0.01s\n3 passed in 0.1s\n", is_error=False)
    assert audit.judge_output("tests_pass", "pytest -q a.py; pytest -q b.py", ev)[0] == "backed"
    ev = Event("tool", name="Bash", text="npx mocha", result="  3 passing (20ms)\n  0 pending\n", is_error=False)
    assert audit.judge_output("tests_pass", "npx mocha", ev)[0] == "backed"


# ---------------------------------------------------------------- pre hook
def test_log_flags_do_not_disarm_the_pipe_check_and_listing_is_not_a_run():
    assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "pytest --log-cli-level=INFO tests/ 2>&1 | tail -20"}}) is not None
    assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "gh run view 123 --log | tail -20"}}) is None
    for cmd in ["pytest --collect-only -q | head -20", "pytest --version | head -1", "cargo test --help | head"]:
        assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": cmd}}) is None, cmd


def test_pre_message_names_the_actual_pipe():
    out = hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "cargo test 2>&1 | grep -c ok"}})
    assert out and "through grep" in out["systemMessage"] and "`| grep`" in json.dumps(out, ensure_ascii=False)


# ---------------------------------------------------------------- guard / settings
def test_guard_survives_odd_settings_shapes(tmp_path, monkeypatch):
    sp = tmp_path / "settings.json"
    monkeypatch.setattr(hooks, "settings_path", lambda: str(sp))
    for odd in ['{"hooks": null}', '{"hooks": {"Stop": "x"}}', '{"hooks": {"Stop": [{"hooks": "x"}]}}', '{"hooks": {"Stop": [1, {"hooks": [2]}]}}']:
        sp.write_text(odd, encoding="utf-8")
        assert "not installed" in hooks.guard("status")
        assert "installed →" in hooks.guard("install")
        assert "installed for Stop, PreToolUse" in hooks.guard("status")
    sp.write_text("[]", encoding="utf-8")
    assert "not a JSON object" in hooks.guard("status")
    with pytest.raises(SystemExit):
        hooks.guard("install")
    sp.write_text('{"hooks": [broken', encoding="utf-8")
    assert "cannot read" in hooks.guard("status")
    with pytest.raises(SystemExit):
        hooks.guard("install")
    assert sp.read_text(encoding="utf-8") == '{"hooks": [broken'   # never overwritten


def test_guard_install_is_idempotent_without_new_backups(tmp_path, monkeypatch):
    sp = tmp_path / "settings.json"
    monkeypatch.setattr(hooks, "settings_path", lambda: str(sp))
    assert "not installed, nothing to remove" in hooks.guard("uninstall")
    assert not sp.exists()
    assert "installed →" in hooks.guard("install")
    n = len(list(tmp_path.iterdir()))
    assert "already installed" in hooks.guard("install")
    assert len(list(tmp_path.iterdir())) == n   # no second backup
    assert "uninstalled →" in hooks.guard("uninstall")
    assert "hooks" not in json.loads(sp.read_text(encoding="utf-8"))


def test_windows_exe_path_is_written_with_forward_slashes(monkeypatch):
    monkeypatch.setattr(sys, "argv", [r"C:\Users\dev\.venv\Scripts\honestly.exe"])
    assert hooks._exe() == "C:/Users/dev/.venv/Scripts/honestly.exe"
    monkeypatch.setattr(sys, "argv", ["/home/me/.venv/bin/honestly"])
    assert hooks._exe() == "/home/me/.venv/bin/honestly"


# ---------------------------------------------------------------- notifications
def test_notification_text_never_becomes_code(monkeypatch):
    calls = []
    import subprocess
    monkeypatch.setenv("HONESTLY_NOTIFY", "1")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)))
    body = ",1);iex 'calc';# all tests pass \"quoted\" \\ back"
    monkeypatch.setattr(sys, "platform", "win32")
    hooks._notify("honestly", body)
    cmd, kw = calls[-1]
    assert "iex" not in " ".join(cmd) and kw["env"]["HONESTLY_NOTIFY_BODY"] == body
    monkeypatch.setattr(sys, "platform", "darwin")
    hooks._notify("honestly", body)
    cmd, _ = calls[-1]
    assert cmd[0] == "osascript" and '\\"quoted\\"' in cmd[2] and "\\\\ back" in cmd[2]
    monkeypatch.setattr(sys, "platform", "linux")
    hooks._notify("honestly", body)
    assert calls[-1][0][:2] == ["notify-send", "--"]


# ---------------------------------------------------------------- misc
def test_update_check_env_var_is_respected_everywhere(monkeypatch, tmp_path):
    monkeypatch.setenv("HONESTLY_NO_UPDATE_CHECK", "1")
    monkeypatch.setattr(update, "cache_path", lambda: str(tmp_path / "u.json"))
    monkeypatch.setattr(update, "_fetch_latest", lambda timeout=2.0: (_ for _ in ()).throw(AssertionError("network used")))
    assert update.latest_version() == ""
    assert update.update_note("0.0.1") == ""


def test_redaction_catches_common_secrets():
    s = support._redact("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY mysql -p'hunter2' curl -u admin:S3cret!pw https://user:pw@host/x "
                        "Authorization: Bearer abc.def token=short api_key: \"sk-12345\" --password=x1 pytest -q")
    for leak in ["wJalrXUtnFEMI", "hunter2", "S3cret", "user:pw@", "abc.def", "short", "sk-12345", "x1 "]:
        assert leak not in s, (leak, s)
    assert "pytest -q" in s


def test_local_time_is_wall_clock():
    out = hooks.local_time("2026-10-30T04:33:21+00:00")
    assert len(out) == 16 and out[4] == "-"
    assert hooks.local_time("garbage") == "garbage"


def test_rule_install_rejects_a_missing_dir(tmp_path):
    with pytest.raises(SystemExit):
        support.rule("install", "claude-code", str(tmp_path / "nope"))
    assert not (tmp_path / "nope").exists()
    assert "not present" in support.rule("uninstall", "claude-code", str(tmp_path))


def test_cli_version_and_config_usage(capsys):
    from honestly.cli import main
    from honestly import __version__
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0 and __version__ in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        main(["config", "verify"])
    assert e.value.code != 0
    with pytest.raises(SystemExit) as e:
        main(["config", "off"])
    assert e.value.code != 0


def test_background_output_file_is_read_from_the_tail(tmp_path):
    from honestly.claude_code import _tool_result_text
    big = tmp_path / "t.output"
    big.write_bytes(b"x" * 100_000 + b"\n12 passed in 1.0s\n")   # bytes: no newline translation on Windows
    text = _tool_result_text({"content": f"Output is being written to: {big}"})
    assert text.rstrip().endswith("12 passed in 1.0s") and len(text) <= 3000


def test_fail_open_input_leaves_a_note(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "errors_path", lambda: str(tmp_path / "hook-errors.log"))
    assert hooks.stop_hook({"transcript_path": str(tmp_path / "missing.jsonl"), "last_assistant_message": "hello"}) is None
    assert "does not exist" in (tmp_path / "hook-errors.log").read_text(encoding="utf-8")
