"""The rules run on whatever a command printed. Every pattern added for 0.7.2 has to stay linear on awkward output (CodeQL py/polynomial-redos)."""
import time

import pytest

from honestly import audit, claims, hooks, rules

PATTERNS = {
    "FAIL_COUNT": audit.FAIL_COUNT, "COUNTED_TESTS": audit.COUNTED_TESTS, "COMMITTED_RECAP": audit.COMMITTED_RECAP,
    "SELF_CHECK_OK": audit.SELF_CHECK_OK, "SELF_CHECK_BAD": audit.SELF_CHECK_BAD, "GIT_COMMIT_TITLE": audit.GIT_COMMIT_TITLE, "DRY_RUN_FLAG": audit.DRY_RUN_FLAG, "DRY_RUN_CLAIM": audit.DRY_RUN_CLAIM, "SCRIPT_RUN": audit.SCRIPT_RUN,
    "TEST_PASS": audit.TEST_PASS, "TEST_FAIL": audit.TEST_FAIL, "SUMMARY_LINE": audit.SUMMARY_LINE, "ZERO_TESTS": audit.ZERO_TESTS,
    "PS_WRITE": rules.PS_WRITE, "PS_WRITE_SOURCE": rules.PS_WRITE_SOURCE, "PIPE_SWALLOW": rules.PIPE_SWALLOW,
    "SESSION_REPORT": audit.SESSION_REPORT, "SUITE_LINE": audit.SUITE_LINE, "SELECT_CUTS_END": hooks.SELECT_CUTS_END, "SELECT_LAST": hooks.SELECT_LAST,
}
AWKWARD = [" ", "\n ", "\n", "\t", "9 tests, ", "fail ", ", ", "[  FAILED  ] ", "- ", "* ", "*", "| ", ".test", "Output: a\n", "with 1 failures ", "1 ", "# ", "#", " \n# ", "\n- * "]
# what the claim detector reads is prose, so its awkward cases are prose too
AWKWARD_PROSE = AWKWARD + ["a", "test", "test ", "tests pass ", "the ", "not ", "`", "` ", '"', '" ', "'", "' ", "**", "[", "](", "(", "（", ".", ". ", "。", "? ", "/", "./", "_test", "a/", "a.", "1/", "测试", "测试 ", "已", "了", "的", "修好", "全部", "没", "看到", "把", "pushed ", "fixed ", "after ", "which ", "by ", "x" * 50 + " "]


@pytest.mark.parametrize("name", sorted(PATTERNS))
def test_a_pattern_stays_fast_on_awkward_output(name):
    rx = PATTERNS[name]
    for unit in AWKWARD:
        start = time.perf_counter()
        rx.search(unit * 2000)
        assert time.perf_counter() - start < 1.0, repr(unit)


# ---- the shell reader and the checks built on it: a command is whatever an assistant typed, so every entry point stays near linear on it, and stops at its limits
SHELL_UNITS = ["a ", "a|", "| ", "a;", ";", "; ", "&", "& ", "(", ")", "()", "$(", "$(a)", "$(a|b)", "${a}", "$a", "{", "}", "{ a; }", "{a;}|b;", '"', "'", '"a" ', "'a' ", '\\"', "\\'", "`", "`a`", "\\", "\\\n", "\n", " ", "\t", "<<", "<<<", "<<a", "<<a\na\n",
               '<<"a"', '"a"<<', ">", "> ", ">>", "> a.py;", "echo x > a.md;", "echo x > a.py;", "cd a;", "cd a && ", "#", " #", "A=1 ", "a=b;", "x=$(a);", "pytest ", "pytest|", "pytest | head;", "npm ", "pnpm ", "yarn ", "make ", "mvn ", "gradle ", "sbt ", "go test ", "bash ", "bash -c ", "python ", "python -a ",
               "uv run ", "docker run ", "time ", "env ", "set ", "set -o pipefail;", "sed -i ", "tee ", "cat > ", "git ", "git checkout ", "git -C a ", "open(", ".write(", "Path(a).write_text(", "for a in b; do ", "for a in b;do c;done;", "if a; then b; fi;", "while a; do b; done;", "f() { a; };", "测试 ", "\x00", "x"]
SHELL_FUNCS = {"segments": rules.segments, "bash_is_edit": rules.bash_is_edit, "verifying_segments": lambda c: rules.verifying_segments(c, {"test", "build", "exercise", "run", "render", "push", "commit"}),
               "verifying_after_edit": lambda c: rules.verifying_segments(c, {"test"}, after_edit_only=True), "find_hidden_status": hooks.find_hidden_status, "_stage_kind": hooks._stage_kind, "_consumer": hooks._consumer,
               "exercises_code": lambda c: rules.exercises_code(c, rules.Segment(c)), "event_dir": lambda c: rules.event_dir(rules_event(c))}


def rules_event(c):
    from honestly.claude_code import Event
    return Event("tool", name="Bash", text=c)


@pytest.mark.parametrize("name", sorted(SHELL_FUNCS))
def test_a_100_kb_command_of_any_shape_cannot_outrun_a_hook(name):
    fn = SHELL_FUNCS[name]
    for unit in SHELL_UNITS:
        cmd = (unit * (100_000 // len(unit) + 1))[:100_000]
        start = time.process_time()
        fn(cmd)
        spent = time.process_time() - start
        # The limits in shell.py hold whatever the shape; the pre-command hook has 10 s. The slowest shape takes about 0.5 s
        # on a laptop and 2.6 s on the macOS Python 3.9 runner, so 5 s leaves room for a slow runner and still stops a blow-up.
        assert spent < 5.0, (name, unit, spent)


@pytest.mark.parametrize("cmd", ["cat > src/big.py <<'EOF'\n" + "x = open('a').read().replace('b', 'c')  # it's\n" * 2000 + "EOF", "python3 - <<'EOF'\n" + "print('a')\n" * 8000 + "EOF", "git commit -m \"" + "line of text. " * 7000 + "\"", "pytest -q " + "tests/test_module.py " * 4800, "bash <<'EOF'\n" + "echo line\n" * 9000 + "EOF"], ids=["source file in a heredoc", "python script in a heredoc", "long commit message", "many file arguments", "shell heredoc"])
def test_a_large_real_command_stays_quick(cmd):
    from honestly import shell
    for fn in (rules.bash_is_edit, lambda c: rules.verifying_segments(c, {"test", "build", "exercise"}), hooks.find_hidden_status):
        shell.parse.cache_clear()
        shell.units.cache_clear()
        start = time.process_time()
        fn(cmd)
        assert time.process_time() - start < 0.5


@pytest.mark.parametrize("unit", ["a|", "a;", "$(a)", "(", "$("])
def test_past_the_limits_it_says_it_could_not_check(unit, tmp_path, monkeypatch):
    from honestly import shell
    monkeypatch.setattr(hooks, "errors_path", lambda: str(tmp_path / "hook-errors.log"))
    cmd = unit * (shell.MAX_PIPELINES + shell.MAX_DEPTH + 10)
    assert rules.too_big(cmd)
    hooks.find_hidden_status(cmd)
    assert "too long to read" in (tmp_path / "hook-errors.log").read_text()


def test_an_oversized_command_after_an_edit_is_not_read_as_a_verdict(tmp_path):
    from honestly.audit import audit_turn
    from honestly.claude_code import Turn, Event
    big = "echo x;" * 5000 + "pytest -q"
    t = Turn(session="s", index=0, version="", prompt="", agent="claude-code", model="")
    t.events = [Event("tool", name="Edit", text="/p/src/app.py"), Event("tool", name="Bash", text=big, result=""), Event("text", text="All tests pass.")]
    assert [f.verdict for f in audit_turn(t)] == ["unverifiable"]


REGEX_PATTERNS = {"NOT_A_RUN": rules.NOT_A_RUN, "NON_VERIFY_VERB": rules.NON_VERIFY_VERB, "PIPEFAIL_ON": rules.PIPEFAIL_ON, "WRITE_MARK": rules.WRITE_MARK, "PRE_TEST": hooks.PRE_TEST, "PRE_BUILD": hooks.PRE_BUILD, "PRE_LINT": hooks.PRE_LINT, "PRE_COMPILE": hooks.PRE_COMPILE, "PRE_MULTI": hooks.PRE_MULTI, "NOT_A_CHECK": hooks.NOT_A_CHECK}
REGEX_ANCHORED = {"VERIFY_TEST": rules.VERIFY["test"], "VERIFY_BUILD": rules.VERIFY["build"], "VERIFY_RUN": rules.VERIFY["run"], "MORE_TEST": rules._MORE_TEST, "PRE_TEST": hooks.PRE_TEST, "PRE_BUILD": hooks.PRE_BUILD, "PRE_LINT": hooks.PRE_LINT}


@pytest.mark.parametrize("name", sorted(REGEX_ANCHORED))
def test_a_pattern_used_at_the_head_of_a_command_is_fast(name):
    rx = REGEX_ANCHORED[name]
    for unit in ["pytest ", "npm ", "pnpm ", "mvn ", "gradle ", "sbt ", "make ", "python ", "python -a ", "a ", " ", "-a ", "./", "a/"]:
        line = (unit * 1000)[:4000]   # rules.command_line cuts a command to 4000 characters
        start = time.process_time()
        rx.match(line)
        assert time.process_time() - start < 0.1, repr(unit)


@pytest.mark.parametrize("name", sorted(claims.PATTERNS))
def test_a_claim_pattern_stays_fast_on_awkward_prose(name):
    rx = claims.PATTERNS[name]
    for unit in AWKWARD_PROSE:
        text = (unit * 4000)[:8000]
        start = time.perf_counter()
        rx.search(text)
        assert time.perf_counter() - start < 1.0, repr(unit)


@pytest.mark.parametrize("unit", AWKWARD_PROSE)
def test_the_whole_detector_stays_fast_on_awkward_prose(unit):
    claims._analyse.cache_clear()
    text = (unit * 100000)[:100000]
    start = time.perf_counter()
    rules.find_claims(text)
    assert time.perf_counter() - start < 1.0, repr(unit)


PROSE = ("The handler reads the config file and returns early when the value is missing. We keep a small cache of the parsed result so the second call is cheap; "
         "the test for that lives next to the module. 这个函数读取配置文件，缺少字段时提前返回。对应的测试在模块旁边。\n\n")


@pytest.mark.parametrize("name,text", [
    ("prose", (PROSE * 400)[:100000]),
    ("one line of prose", (PROSE.replace("\n", " ") * 400)[:100000]),
    ("the same claim again and again", ("All tests pass. " * 6250)[:100000]),
], ids=["prose", "one-line", "repeated"])
def test_a_100_kb_reply_takes_under_50_ms(name, text):
    best = 9.9
    for _ in range(5):   # the best of five: a busy machine is not the detector's fault
        claims._analyse.cache_clear()
        start = time.process_time()
        rules.find_claims(text)
        best = min(best, time.process_time() - start)
    assert best < 0.05, f"{name}: {best * 1000:.0f} ms"


def test_a_100_kb_reply_of_different_claims_does_not_blow_up():
    # catches a blow-up, not a slow runner: this takes about 30 ms here and 55 to 78 ms on CI
    text = "".join(f"Fixed the crash in module{i} and pushed to branch{i}, all {i} tests pass. " for i in range(1600))[:100000]
    best = 9.9
    for _ in range(5):
        claims._analyse.cache_clear()
        start = time.process_time()
        rules.find_claims(text)
        best = min(best, time.process_time() - start)
    assert best < 0.5, f"{best * 1000:.0f} ms"
