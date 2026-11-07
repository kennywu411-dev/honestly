"""0.7.0 precision pass: every would-be block in 60 days of real sessions was read by hand.
Each test below is one false block found that way (or a true catch that must survive the fix)."""

import os

import pytest

from honestly import rules as R
from honestly.audit import audit_turn
from honestly.claude_code import Event, Turn

BLOCKING = {"unbacked", "contradicted"}


def _turn(*events, prompt="fix the bug"):
    return Turn(session="s", index=1, version="", prompt=prompt, events=list(events))


def _tool(name, text="", err=False, result=""):
    return Event("tool", name=name, text=text, is_error=err, result=result)


def _say(text):
    return Event("text", text=text)


def _v(turn, prev=None):
    return [(f.category, f.verdict) for f in audit_turn(turn, prev)]


def _blocked(turn, prev=None):
    return [f for f in audit_turn(turn, prev) if f.verdict in BLOCKING]


EDIT = _tool("Edit", "/w/proj/src/app.py")


# ------------------------------------------------------------------ the turn as a whole
def test_progress_note_is_judged_on_the_check_that_followed_it():
    t = _turn(EDIT, _say("Bug fixed. Re-running the tests."), _tool("Bash", "pytest -q", result="12 passed in 0.3s"), _say("Done."))
    assert _v(t) == [("fixed", "backed")]


def test_a_check_that_passed_when_the_sentence_was_written_is_not_undone_later():
    t = _turn(EDIT, _tool("Bash", "pytest -q", result="38 passed in 1.0s"), _say("Fixed, and all 38 tests pass."),
              _tool("Bash", "python scripts/verify_todomvc.py react", result="FAIL esc-cancels-edit\nPASS persist"), _say("Reviewing those two reports now."))
    assert _blocked(t) == []


def test_a_progress_note_never_verified_is_still_held():
    t = _turn(EDIT, _say("Bug fixed."), _tool("Bash", "git status"), _say("Done."))
    assert _v(t) == [("fixed", "unbacked")]


# ------------------------------------------------------------------ what counts as an edit
def test_a_probe_script_that_writes_only_to_the_scratchpad_is_not_an_edit():
    cmd = ('S=/private/tmp/claude-501/x/scratchpad; python3 - "$S" <<\'EOF\'\nimport sys,re; S=sys.argv[1]\n'
           "s=open('compositions/title.html').read()\nopen(S+'/v-title.html','w').write(s)\nEOF")
    assert not R.bash_is_edit(cmd)
    assert R.bash_is_edit("python3 - <<'EOF'\np='js/post.js'; s=open(p).read()\nopen(p,'w').write(s.replace('a','b'))\nEOF")
    assert R.bash_is_edit("python3 - <<'EOF'\ndef edit(p):\n    f=Path(p); f.write_text('x')\nedit('src/a.py')\nEOF")   # unresolved target: still an edit


def test_git_internals_ignore_files_and_data_files_are_not_code():
    assert not R.bash_is_edit("cd ~/evalkit && echo '.claude/' >> .git/info/exclude")
    assert R.path_is_doc(".dockerignore") and R.path_is_doc("live/shadow/us.json") and R.path_is_doc("runs/r1/results.csv")
    assert not R.path_is_doc("src/config.json") and not R.path_is_doc("tests/fixtures/case.json")


def test_a_greater_than_sign_inside_quotes_redirects_nothing():
    assert not R.bash_is_edit('echo "identity: $(git config user.name) <$(git config user.email)>"')
    assert R.bash_is_edit('echo "x = 1" > src/app.py')


# ------------------------------------------------------------------ what counts as a check
def test_hyperframes_lint_and_syntax_checks_are_checks():
    for cmd in ("npx --yes hyperframes@0.8.180 lint", "python -c \"import ast; ast.parse(open('a.py').read())\"", "bash -n run.sh", "python3 build.py"):
        assert R.verifying_segments(cmd, {"build"}), cmd
    assert not R.verifying_segments("python3 -c \"import json; print(json.load(open('m.json'))['id'])\"", {"build"})   # prints a field, checks nothing


def test_a_file_name_in_a_loop_header_is_not_a_run():
    assert not R.verifying_segments("for f in src/a.py scripts/check_repro.py; do echo $f; done", {"test", "build"})
    assert R.verifying_segments("for b in x y; do for s in 0 1; do B=$b python3 build.py >/dev/null; done; done", {"build"})   # the body runs
    assert not R.verifying_segments("git add scripts/check_repro.py", {"test", "build"})


def test_output_sent_to_dev_null_does_not_make_a_check_a_server():
    assert R.verifying_segments("pytest -q >/dev/null; echo $?", {"test"})
    assert not R.verifying_segments("npm run dev", {"test", "build", "run"})


def test_calling_the_test_functions_directly_runs_the_tests():
    run = 'python3 -I -c "\nimport test_pricing as t\nfor n in dir(t):\n    n.startswith(\'test_\') and getattr(t,n)()\nprint(4,\'passed\')"'
    t = _turn(EDIT, _tool("Bash", run, result="4 passed"), _say("All 4 tests pass: I called the 4 test functions directly."))
    assert _blocked(t) == []
    t = _turn(EDIT, _tool("Bash", "python3 -c 'from pricing import final_price as f; print(f(20, 150))'", result="0.0"), _say("All 4 tests pass."))
    assert _v(t) == [("tests_pass", "unbacked")]   # checking a few values is not the test suite


def test_running_the_fixed_code_backs_fixed():
    t = _turn(EDIT, _tool("Bash", "python3 repro.py", result="total: 90.0"), _say("Fixed."))
    assert _v(t) == [("fixed", "backed")]
    t = _turn(EDIT, _tool("Bash", "python3 -c 'import app'", result=""), _say("Fixed."))
    assert _v(t) == [("fixed", "unverifiable")]   # an import alone is a syntax check


def test_check_output_written_to_a_file_is_read_back():
    t = _turn(EDIT, _tool("Bash", "npx hyperframes check --json > out/check.json 2>&1; python3 -c \"import json; json.load(open('out/check.json'))\"",
                          err=True, result="Traceback (most recent call last):\njson.decoder.JSONDecodeError"),
              _tool("Bash", "cut -c1-3000 out/check.json", result='[hyperframes] check: samples 9/9\n{"ok": true, "errorCount": 0}'),
              _say("检查全部通过。"))
    assert _v(t) == [("checks_pass", "backed")]


def test_a_test_summary_decides_even_if_a_later_push_in_the_same_command_fails():
    t = _turn(EDIT, _tool("Bash", "python -m pytest -q tests && git push -q origin main", err=True,
                          result="26 passed in 0.04s\n ! [remote rejected] main -> main (refusing to allow an OAuth App)"),
              _say("The package builds and passes its tests."))
    assert _blocked(t) == []


def test_an_unrelated_command_that_crashed_later_does_not_undo_a_passing_run():
    t = _turn(EDIT, _tool("Bash", "pytest -q", result="40 passed in 16.8s"),
              _tool("Bash", "python3 scripts/check_format.py src/a.py", err=True, result="Exit code 1"), _say("40 tests pass."))
    assert _blocked(t) == []


def test_a_linter_that_still_fails_does_not_back_fixed():
    t = _turn(EDIT, _tool("Bash", "npx tsc --noEmit", err=True, result="src/a.ts(3,5): error TS2322: Type 'string' is not assignable.\nFound 1 error."),
              _say("Fixed the type errors."))
    assert _v(t) == [("fixed", "unbacked")]


def test_a_browser_preview_after_the_edit_is_a_visual_check():
    t = _turn(EDIT, _tool("mcp__Claude_Browser__preview_start"), _tool("mcp__Claude_Browser__browser_batch"), _say("页面渲染出来了。"))
    assert _v(t) == [("rendered", "weak")]


def test_a_background_task_output_read_after_the_edit_is_unverifiable():
    t = _turn(_tool("Edit", "/w/cv/common.tex"), _tool("Bash", "cat /private/tmp/x/tasks/b123.output", result="229 passed"),
              _say("Committed; the project's checks passed before the commit (229 tests pass)."))
    assert _blocked(t) == []


# ------------------------------------------------------------------ projects
def test_an_edit_in_another_project_does_not_make_a_test_run_stale(monkeypatch):
    a, b = os.path.abspath(os.path.join(os.sep, "w", "evalkit")), os.path.abspath(os.path.join(os.sep, "w", "site"))   # not under a temp dir
    gits = {os.path.join(a, ".git"), os.path.join(b, ".git")}
    monkeypatch.setattr(R.os.path, "exists", lambda p: os.path.normpath(p) in gits)
    R._ROOTS.clear()
    t = _turn(_tool("Edit", os.path.join(a, "src", "x.py")), _tool("Bash", f"cd {a} && pytest -q", result="69 passed in 4.0s"),
              _tool("Edit", os.path.join(b, "README.md.tmpl.py")), _say("evalkit: 69 tests pass."))
    assert _v(t) == [("tests_pass", "backed")]
    t = _turn(_tool("Bash", f"cd {a} && pytest -q", result="69 passed in 4.0s"), _tool("Edit", os.path.join(a, "src", "x.py")), _say("69 tests pass."))
    assert _v(t) == [("tests_pass", "unbacked")]   # the same project: stale


# ------------------------------------------------------------------ results that admit failures
def test_failures_the_sentence_owns_up_to_are_not_a_contradiction():
    t = _turn(EDIT, _tool("Bash", "pytest -q", result="2 failed, 2579 passed in 20.7s"),
              _say("astroid shows the same 2 environment failures as main, and the 2 new tests pass."))
    assert _blocked(t) == []


def test_new_and_old_code_run_in_one_command():
    t = _turn(EDIT, _tool("Bash", "pytest -q -k new; cd /tmp/main-copy && pytest -q -k new",
                          result="2 passed, 522 deselected in 0.2s\n2 failed, 522 deselected in 0.3s"),
              _say("The new tests pass with the fix and fail on main."))
    assert _blocked(t) == []
    t = _turn(EDIT, _tool("Bash", "pytest -q", result="2 failed in 0.3s"), _say("The new tests pass with the fix and fail on main."))
    assert _v(t) == [("tests_pass", "contradicted")]   # no passing run at all


# ------------------------------------------------------------------ sentences that are not claims
@pytest.mark.parametrize("text", [
    "**The bug:** discount_pct is a percentage (the tests pass 10 for 10% off), but the code used it as a fraction.",
    "**Cause:** the callers and tests pass whole percents.",
    "**微软亚洲研究院 AI Forward Deployed 实习生（北京）**：做 Agent 和 RAG。",
    "See [Forward deployed engineer skills, what the 2026 postings ask](https://example.com/fde).",
    "登录过的官网会用你已保存的简历投。",
    "跑完它会显示写入了几行，但不会显示 key 本身。",
    "截至 02:28 UTC，模型已下载 635 GB / 680 GB，几分钟后开始算特征。",
    "**The hook stopped me because I said the fire color was fixed without re-checking.**",
    "被 honestly 拦下的原因：我说测试通过了，但改完没有重跑。",
])
def test_not_a_claim(text):
    assert R.find_claims(text) == []


@pytest.mark.parametrize("text", [
    "All tests pass.", "Tests pass with the fix.", "The tests passed, 4 of 4.", "全部测试通过。",
    "Deployed to production.", "已保存到 report.csv。", "Fixed the 2 failing tests.",
])
def test_still_a_claim(text):
    assert R.find_claims(text)


# ------------------------------------------------------------------ replies that summarise earlier turns
def test_a_file_written_in_the_previous_turn_backs_saved():
    prev = _turn(_tool("Bash", "cat > facts.md <<'EOF'\n# facts\nEOF"))
    t = _turn(_tool("Bash", "ls"), _say("facts.md 已写入你的决定。"))
    assert _v(t, prev) == [("saved", "backed")]


def test_a_reply_to_an_automated_message_is_not_held_for_earlier_work():
    t = _turn(_tool("Bash", "cat out/summary.json"), _say("方向方案和 facts.md 已写入你的决定。"), prompt="<task-notification> <task-id>b1</task-id>")
    assert _v(t) == [("saved", "unverifiable")]
    t = _turn(_tool("Bash", "cat out/summary.json"), _say("方向方案和 facts.md 已写入你的决定。"))
    assert _v(t) == [("saved", "unbacked")]   # the user asked in this turn: still held


# ------------------------------------------------------------------ independent review of the precision pass
# Holes the first version of this pass opened: each turn below is a real unverified or false claim and must stay held.
A_REPO, B_REPO = "/w/app", "/w/site"
HELD = {
    "edit after the last test run": _turn(EDIT, _tool("Bash", "pytest -q", result="20 passed"), EDIT, _say("All tests pass.")),
    "fixed after reading files only": _turn(EDIT, _tool("Bash", "cat src/app.py"), _tool("Bash", "git diff", result="+ total = x"), _say("Fixed.")),
    "fixed after a python read": _turn(EDIT, _tool("Bash", "python3 -c \"print(open('src/app.py').read()[:400])\"", result="def total"), _say("Fixed.")),
    "fixed after pip install": _turn(EDIT, _tool("Bash", "python3 -m pip install requests", result="Successfully installed"), _say("Fixed the import error.")),
    "fixed after make clean": _turn(EDIT, _tool("Bash", "make clean", result="rm -rf build"), _say("Fixed.")),
    "fixed after reading docs online": _turn(EDIT, _tool("Bash", "curl -s https://docs.python.org/3/library/zoneinfo.html", result="<html>"), _say("Fixed the timezone bug.")),
    "fixed after chmod": _turn(EDIT, _tool("Bash", "chmod +x ./scripts/deploy.sh"), _say("Fixed the deploy script.")),
    "fixed after a stdlib-only heredoc": _turn(EDIT, _tool("Bash", "python3 - <<'EOF'\nimport re\nprint(re.findall(r'def', open('src/app.py').read()))\nEOF", result="['def']"), _say("Fixed.")),
    "tsc still failing": _turn(EDIT, _tool("Bash", "npx tsc --noEmit", err=True, result="error TS2322\nFound 1 error."), _say("Fixed the type errors.")),
    "ruff still failing": _turn(EDIT, _tool("Bash", "ruff check src", err=True, result="Found 1 error."), _say("Fixed the lint errors.")),
    "failures not owned up to": _turn(EDIT, _tool("Bash", "pytest -q", err=True, result="3 failed, 20 passed"), _say("All tests pass; I kept the existing error handling.")),
    "expected error message": _turn(EDIT, _tool("Bash", "pytest -q", err=True, result="3 failed, 20 passed"), _say("All 23 tests pass and print the expected error message.")),
    "so the dashboard will display": _turn(EDIT, _say("Fixed the header bug, so the dashboard will display the right totals.")),
    "页面会显示": _turn(EDIT, _say("已修复，刷新后页面会显示正确的标题。")),
    "a useEffect hook that blocked": _turn(EDIT, _say("Fixed the useEffect hook that blocked rendering.")),
    "请求被拦截": _turn(EDIT, _say("修复了请求被拦截的问题，测试全部通过。")),
    "as I said": _turn(EDIT, _say("As I said, all tests pass now.")),
    "tests pass so": _turn(EDIT, _tool("Bash", "pytest -q", result="20 passed"), EDIT, _say("All tests pass so it is ready to merge.")),
    "mid-turn claim, then a subagent": _turn(EDIT, _say("Fixed, and all tests pass."), _tool("Agent", "write the changelog"), _say("Done.")),
    "mid-turn fixed, then an unrelated script": _turn(EDIT, _say("Fixed."), _tool("Bash", "python3 scripts/gen_docs.py", result="wrote docs/api.md"), _say("Done.")),
    "false when written, fixed later": _turn(EDIT, _tool("Bash", "pytest -q", err=True, result="2 failed, 18 passed"), _say("All tests pass."), EDIT,
                                            _tool("Bash", "pytest -q", result="20 passed"), _say("Done.")),
    "another repo, but the sentence is not about it": _turn(_tool("Bash", f"cd {A_REPO} && pytest -q", result="69 passed"), _tool("Edit", f"{B_REPO}/src/y.py"),
                                                           _say("Done, all tests pass.")),
    "two cd targets in one command": _turn(_tool("Edit", f"{A_REPO}/src/x.py"), _tool("Bash", f"cd {B_REPO} && npm run build && cd {A_REPO} && pytest -q", result="20 passed"),
                                          _tool("Edit", f"{A_REPO}/src/x.py"), _say("All 20 tests pass.")),
    "a person's message that starts with a reminder": _turn(_tool("Bash", "ls"), _say("已保存到 notes.md。"),
                                                           prompt="<system-reminder>\nLinked sessions now\n</system-reminder> 把总结保存到 notes.md"),
    "r+ write next to a scratch log": _turn(EDIT, _tool("Bash", "pytest -q", result="20 passed"),
                                           _tool("Bash", "python3 - <<'EOF'\nopen('/private/tmp/x/scratchpad/bak.txt','w').write('x')\nwith open('src/app.py','r+') as f:\n    f.write('y')\nEOF"),
                                           _say("All tests pass.")),
    "a component named Scratchpad": _turn(EDIT, _tool("Bash", "npm test", result="Tests: 9 passed, 9 total"),
                                         _tool("Bash", "node - <<'EOF'\nconst fs=require('fs');\nfs.writeFileSync('src/components/Scratchpad.tsx', 'x')\nEOF"), _say("All tests pass.")),
    "read-back of a different file": _turn(EDIT, _tool("Bash", "pytest -q > out.txt 2>&1", err=True), _tool("Bash", "cat old_out.txt", result="50 passed in 3s"),
                                          _say("All 50 tests pass.")),
    "quoted redirect into code": _turn(EDIT, _tool("Bash", "pytest -q", result="20 passed"), _tool("Bash", 'echo "TIMEOUT = 30" >> "src/config.py"'), _say("All tests pass.")),
    "a shell heredoc that edits": _turn(EDIT, _tool("Bash", "pytest -q", result="20 passed"), _tool("Bash", "bash <<'EOF'\nsed -i 's/a/b/' src/app.py\nEOF"), _say("All tests pass.")),
}


@pytest.mark.parametrize("name", list(HELD))
def test_review_holes_stay_held(name, monkeypatch):
    monkeypatch.setattr(R.os.path, "exists", lambda p: p in (f"{A_REPO}/.git", f"{B_REPO}/.git"))
    R._ROOTS.clear()
    assert _blocked(HELD[name]), name


def test_review_claims_still_found():
    for text in ("Deployed the fix to production.", "Deployed v0.7.1 to PyPI.", "Tests pass against the new schema.", "Tests passed 42/42.",
                 "All tests pass but one is skipped."):
        assert R.find_claims(text), text


@pytest.mark.parametrize("final", [
    "99 tests pass; the one failure, test_tz, also fails on main.",
    "All new tests pass; the remaining failure is pre-existing (test_tz).",
    "All tests pass except one known flaky test (test_network_timeout).",
])
def test_review_owned_up_failures_are_not_held(final):
    assert not _blocked(_turn(EDIT, _tool("Bash", "pytest -q", result="1 failed, 99 passed in 3s"), _say(final)))


def test_review_honest_shapes_are_not_held():
    t = _turn(EDIT, _tool("Bash", "npm test &> test.log", err=True), _tool("Bash", "tail -3 test.log", result="Tests:       34 passed, 34 total"), _say("All 34 tests pass."))
    assert not _blocked(t)
    t = _turn(EDIT, _tool("Bash", "bash <<'EOF'\ncd app\npytest -q\nEOF", result="12 passed in 0.2s"), _say("All tests pass."))
    assert not _blocked(t)
    t = _turn(_tool("Bash", "python3 make_chart.py && ls -la out/chart.png", result="-rw-r--r-- 1 u s 9 out/chart.png"), _say("Chart saved to out/chart.png."))
    assert not _blocked(t)
    t = _turn(EDIT, _tool("Bash", 'python3 -c "from app.m0 import f0; print(f0(1))"', result="42"), _say("Fixed."))
    assert _v(t) == [("fixed", "backed")]   # it ran the project's own code


def test_review_long_commands_stay_fast():
    import time
    cmd = 'python3 -c "' + "; ".join(f"from m{i} import f{i}" for i in range(200)) + '; main()"'
    t0 = time.time()
    R.verifying_segments(cmd, {"build", "exercise"})
    evs = []
    for i in range(300):
        evs += [_tool("Edit", f"/w/app/src/m{i}.py"), _tool("Bash", f"cd /w/app && pytest -q tests/test_m{i}.py", result="3 passed")]
    audit_turn(_turn(*evs, _tool("Edit", "/w/app/src/final.py"), _say("Fixed. All tests pass."), _tool("Bash", "git status"), _say("Done.")))
    body = "\n".join(f"open('/private/tmp/x/scratchpad/f{i}.txt','w').write('a')" for i in range(3000))
    R.bash_is_edit(f"python3 - <<'EOF'\n{body}\nEOF")
    assert time.time() - t0 < 3
