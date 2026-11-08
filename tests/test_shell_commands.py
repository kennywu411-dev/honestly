"""What honestly must make of real shell lines: each group is one cause from the audit, in real commands, through the real functions and the real stop hook."""
import json
import os

import pytest

from honestly import hooks, rules, shell
from honestly.claude_code import Event
from shell_cases import GROUPS

EDIT = ("Edit", {"file_path": "/p/src/app.py"}, "ok")
PASS = ("Bash", {"command": "pytest -q"}, "27 passed in 1s")
OK = "27 passed in 1s"
T = {"test"}


def _rows(events):
    rows = [{"type": "user", "message": {"role": "user", "content": "do it"}, "origin": {"kind": "human"}}]
    for i, ev in enumerate(events):
        name, inp, out = ev[:3]
        rows.append({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}]}})
        rows.append({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": out, "is_error": ev[3] if len(ev) > 3 else False}]}})
    return rows


@pytest.fixture
def held(tmp_path):
    def run(events, reply="All tests pass."):
        p = tmp_path / "s.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in _rows(events)) + "\n", encoding="utf-8")
        out = hooks.stop_hook({"transcript_path": str(p), "last_assistant_message": reply, "stop_hook_active": False})
        return bool(out and out.get("decision") == "block")
    return run


def bash(cmd, out="ok", err=False):
    return ("Bash", {"command": cmd}, out, err)


def cases(*ids, without=()):
    return [c for g in ids for c in GROUPS[g] if c not in without]


def ids(values):
    return [repr(v)[:70] for v in values]


# ------------------------------------------------------------ an edit it must see
EDITS = cases("E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9", "E10", "E11", "E12")


@pytest.mark.parametrize("cmd", EDITS, ids=ids(EDITS))
def test_this_changes_code(cmd, held):
    assert rules.bash_is_edit(cmd)
    assert held([EDIT, PASS, bash(cmd)]), "a pass from before this edit must not back the claim"


# Formatters keep the code's meaning by contract, and `npm version` only bumps a number; `make fix` cannot be told from the text.
@pytest.mark.parametrize("cmd", GROUPS["E12f"], ids=ids(GROUPS["E12f"]))
def test_this_is_not_counted_as_an_edit(cmd):
    assert not rules.bash_is_edit(cmd)


# ------------------------------------------------------------ not an edit
LEFT_AS_EDITS = ["echo x > tmp/a.py", "echo x > .tmp/a.py", "echo x > build/a.js", "echo x > dist/a.js", "echo x > target/a.rs", "echo x > node_modules/a.js",
                 "echo x > .venv/a.py", "echo x > __pycache__/a.py", "jq . a.json > b.json"]
NOT_EDITS = cases("F2", "F3", "F4", "F5", "F6", without=LEFT_AS_EDITS)


@pytest.mark.parametrize("cmd", NOT_EDITS, ids=ids(NOT_EDITS))
def test_this_changes_no_code(cmd, held):
    assert not rules.bash_is_edit(cmd)
    assert not held([EDIT, PASS, bash(cmd)])


@pytest.mark.parametrize("cmd", LEFT_AS_EDITS, ids=ids(LEFT_AS_EDITS))
def test_a_write_into_a_build_or_tmp_folder_can_change_what_tests_run(cmd):
    assert rules.bash_is_edit(cmd)   # loosening this could pass a stale claim


@pytest.mark.parametrize("cmd", GROUPS["F1"], ids=ids(GROUPS["F1"]))
def test_a_run_piped_into_tee_is_a_run_not_an_edit(cmd, held):
    assert not rules.bash_is_edit(cmd)
    assert rules.verifying_segments(cmd, T) or rules.verifying_segments(cmd, {"test", "build"})
    assert not held([EDIT, bash(cmd, OK)])


# Each of these came from replaying real sessions: they were held by mistake on the first try at this parser.
@pytest.mark.parametrize("cmd", ["mv .github \"$S/workflows\"", "cp a.m4a research/ref-audio/", "cp $d/*.jpg renders/", "mv renders/a.png renders/old/", "printf '#!/bin/sh\\n' > .git/hooks/commit-msg", "echo x > .claude/hooks/run.py", "S=/tmp/x; cp $d/*.jpg $d/episode.json $S/$d",
                                 "T=$(mktemp -d); cd \"$T\" && echo x > a.py", "T=$(ls -d /tmp/e2e.* | head -1); cd \"$T\" && printf 'x' > src/app.py", "T=$(mktemp -d); echo x > $T/a.py",
                                 "python3 - <<'EOF'\nimport pathlib\ndef edit(path, a, b):\n    p = pathlib.Path(path); s = p.read_text()\n    p.write_text(s.replace(a, b))\nedit('docs/x.md', 'a', 'b')\nedit('notes/y.txt', 'a', 'b')\nEOF"], ids=lambda v: repr(v)[:70])
def test_no_code_was_changed_here(cmd):
    assert not rules.bash_is_edit(cmd)


def test_handing_a_helper_a_source_file_is_an_edit():
    assert rules.bash_is_edit("python3 - <<'EOF'\nimport pathlib\ndef edit(path, a, b):\n    p = pathlib.Path(path); s = p.read_text()\n    p.write_text(s.replace(a, b))\nedit('docs/x.md', 'a', 'b')\nedit('src/app.py', 'a', 'b')\nEOF")


def test_a_kaggle_push_is_a_push():
    for cmd in ["kaggle competitions submit x -k y -v 1 -f s.parquet", "kaggle kernels push -p d", "git push origin main", "git -C x push"]:
        assert rules.verifying_segments(cmd, {"push"}), cmd


def test_tee_into_a_source_file_is_still_an_edit():
    for cmd in ["echo 'x=1' | tee src/app.py", "cat new.py | tee src/app.py", "python gen.py | tee src/gen.py", "cat <<'EOF' | tee src/app.py\nx\nEOF"]:
        assert rules.bash_is_edit(cmd), cmd


# ------------------------------------------------------------ a check it must see
PRE_COMMIT_IS_NOT_A_TEST_RUN = ["pre-commit run --all-files"]
CHECKS = cases("C1", "C2", "C3", "C4", "C5", "C7", "C8", without=PRE_COMMIT_IS_NOT_A_TEST_RUN)


@pytest.mark.parametrize("cmd", CHECKS, ids=ids(CHECKS))
def test_this_ran_the_tests(cmd, held):
    assert rules.verifying_segments(cmd, T)
    assert not held([EDIT, bash(cmd, OK)])


@pytest.mark.parametrize("cmd", GROUPS["C6"], ids=ids(GROUPS["C6"]))
def test_this_ran_the_build(cmd, held):
    assert rules.verifying_segments(cmd, {"build"})
    assert not held([EDIT, bash(cmd, "Build complete, 0 errors")], "Build succeeded.")


@pytest.mark.parametrize("cmd", GROUPS["C9"], ids=ids(GROUPS["C9"]))
def test_edit_then_test_inside_one_command(cmd, held):
    assert not held([bash(cmd, OK)])


def test_a_package_managers_own_commands_are_what_they_run():
    for cmd in ["yarn jest", "yarn vitest run", "pnpm vitest run", "yarn playwright test", "yarn test", "yarn run test", "pnpm test", "npm test", "npm run test:unit", "npx vitest run", "bun test"]:
        assert rules.verifying_segments(cmd, T), cmd
    for cmd in ["yarn add jest", "yarn why jest", "pnpm add vitest", "npm run test:watch", "npm run dev", "yarn yarn yarn"]:
        assert not rules.verifying_segments(cmd, T), cmd


def test_a_lint_only_hook_run_does_not_back_tests_pass(held):
    assert not rules.verifying_segments("pre-commit run --all-files", T)
    assert held([EDIT, bash("pre-commit run --all-files", "All checks passed")])


# ------------------------------------------------------------ not a check
NAMED_LIKE_A_CHECK = [("python tools/pytest-report.py", "x"), ("python scripts/check_pytest_config.py", "x")]   # a script named so is taken at its word
FAKE = [t for t in GROUPS["X1"] + GROUPS["X2"] if tuple(t) not in NAMED_LIKE_A_CHECK]


@pytest.mark.parametrize("cmd,out", FAKE, ids=ids([t[0] for t in FAKE]))
def test_this_ran_no_tests(cmd, out, held):
    assert not rules.verifying_segments(cmd, T)
    assert held([EDIT, bash(cmd, out)])


NEVER_RUN = [c for c in GROUPS["X3"] if not c.startswith(("[ -f", "test -f"))]


@pytest.mark.parametrize("cmd", NEVER_RUN, ids=ids(NEVER_RUN))
def test_this_branch_never_runs(cmd, held):
    assert not rules.verifying_segments(cmd, T)
    assert held([EDIT, bash(cmd, "")])


@pytest.mark.parametrize("cmd,out", GROUPS["X4"], ids=ids([t[0] for t in GROUPS["X4"]]))
def test_this_is_no_lint_run(cmd, out, held):
    assert not rules.verifying_segments(cmd, {"test", "build"})
    assert held([EDIT, bash(cmd, out)], "Lint passes.")


@pytest.mark.parametrize("cmd,out", GROUPS["X5"], ids=ids([t[0] for t in GROUPS["X5"]]))
def test_this_does_not_exercise_the_fix(cmd, out, held):
    assert held([EDIT, bash(cmd, out)], "Fixed the crash.")


# Starting a server proves nothing about a fix, so these stay out on purpose.
STARTS_A_SERVER = ["npm start", "npm run dev", "yarn start"]
RUNS = [c for c in GROUPS["X5m"] if c not in STARTS_A_SERVER]


@pytest.mark.parametrize("cmd", RUNS, ids=ids(RUNS))
def test_this_runs_the_project_code(cmd):
    assert rules.verifying_segments(cmd, {"exercise"})


@pytest.mark.parametrize("cmd", STARTS_A_SERVER)
def test_starting_a_server_does_not_back_fixed(cmd):
    assert not rules.verifying_segments(cmd, {"exercise"})


@pytest.mark.parametrize("cmd,out", GROUPS["X6"], ids=ids([t[0] for t in GROUPS["X6"]]))
def test_a_dry_push_and_listing_tags_prove_nothing(cmd, out, held):
    assert held([EDIT, bash(cmd, out)], "Pushed to main." if "push" in cmd else "Committed.")


# ------------------------------------------------------------ the result is hidden
SILENT_RUNS = [t[0] for t in GROUPS["H1"] if ">/dev/null" in t[0]] + [c for c in GROUPS["H2"] + GROUPS["H2b"] if "out.log" not in c]


@pytest.mark.parametrize("cmd", SILENT_RUNS, ids=ids(SILENT_RUNS))
def test_output_and_status_both_gone(cmd, held):
    assert hooks.find_hidden_status(cmd), "refused"
    assert not rules.verifying_segments(cmd, T), "and no evidence"
    assert held([EDIT, bash(cmd, "ok")])


def test_a_silent_run_whose_status_still_shows_is_left_alone():
    for cmd in ["pytest -q > /dev/null", "pytest -q >/dev/null 2>&1; echo $?", "pytest -q >/dev/null 2>&1 && echo ok || echo bad", "pytest -q >/dev/null 2>&1 && echo ok",
                "pytest -q > /dev/null || exit 1", "pytest -q > /dev/null || echo FAILED", "set -e; pytest -q > /dev/null; echo done", "pytest -q > out.log 2>&1", "pytest -q || true", "pytest -q; true"]:
        assert not hooks.find_hidden_status(cmd), cmd
    assert rules.verifying_segments("pytest -q >/dev/null; echo $?", T)


HIDDEN = cases("H4", "H4s", "H5", "H6", "H6b", "H7", "H8", "H9", "H10")


@pytest.mark.parametrize("cmd", HIDDEN, ids=ids(HIDDEN))
def test_this_pipeline_hides_the_result(cmd):
    assert hooks.find_hidden_status(cmd)


@pytest.mark.parametrize("cmd", GROUPS["H4s"], ids=ids(GROUPS["H4s"]))
def test_the_stop_hook_does_not_accept_it_either(cmd, held):
    assert held([EDIT, bash(cmd, "")])


ALLOWED = cases("R1", "R2", "R3", "R4", "R5", "R6")


@pytest.mark.parametrize("cmd", ALLOWED, ids=ids(ALLOWED))
def test_this_pipeline_hides_nothing(cmd):
    assert not hooks.find_hidden_status(cmd)


STAY_ALLOWED = ["pytest | tail", "pytest | tail -5", "pytest | tee log", "pytest | cat", "pytest | grep -E 'passed|failed'", "pytest -k foo | head", "pytest tests/test_a.py | head",
                "pytest -rs | grep SKIP", "pytest 2>&1 | grep -A20 FAILURES | head -40", "pytest --version | head -1", "pytest --help | head", "pytest --collect-only | head",
                "cargo build | head", "go build ./... | head", "make | head", "ruff check . | head", "mypy . | head", "npm run build | tail", "set -o pipefail; pytest | head",
                "set -euo pipefail; pytest | head", "set -o errexit -o pipefail; pytest | head", "setopt pipefail; pytest | head", "bash -o pipefail -c 'pytest | head'",
                "bash -euo pipefail -c 'pytest | head'", "bash <<'EOF'\nset -euo pipefail\npytest | head\nEOF", "(set -o pipefail; pytest | head)", "pytest | head; echo ${PIPESTATUS[0]}",
                "pytest | wc -l; exit ${PIPESTATUS[0]}", 'git commit -m "pytest | head"', "echo 'pytest | head'", "grep 'pytest | head' docs.md", "cat > a.sh <<'EOF'\npytest | head\nEOF",
                "cat pytest.ini | head", "ls tests | head", "rg pytest . | head", "git grep pytest | head", "git log --grep pytest | head", "pip show pytest | head", "gh run view 1 | head"]
STAY_REFUSED = ["pytest | head", "pytest | head -5", "pytest|head", "pytest |& head -3", "pytest 2>&1 | head -3", "pytest | wc -l", "pytest | grep -c passed", "pytest | grep -q passed", "pytest | sort | head",
                "pytest | sed -n 1,5p", "pytest | sed 5q", "pytest | awk 'NR<=5'", "npm test | head -2", "go test ./... | wc -l", "cargo test | head", "python -m pytest | head", "uv run pytest | head -3",
                "docker compose exec web pytest | head -3", "make test | head -3", "x=$(pytest | head)", "echo \"$(pytest | wc -l)\"", "bash -c 'pytest | head -3'", "{ pytest; } | head -3", "(pytest) | head -3",
                "bash <<'EOF'\npytest | head -3\nEOF", "pytest |\nhead -3", "pytest \\\n | head -3", "for i in 1 2; do pytest | head -3; done", "if true; then pytest | wc -l; fi", "git commit -m \"$(pytest | head)\""]


@pytest.mark.parametrize("cmd", STAY_ALLOWED, ids=ids(STAY_ALLOWED))
def test_allowed_before_and_still_allowed(cmd):
    assert not hooks.find_hidden_status(cmd)


@pytest.mark.parametrize("cmd", STAY_REFUSED, ids=ids(STAY_REFUSED))
def test_refused_before_and_still_refused(cmd):
    assert hooks.find_hidden_status(cmd)


# ------------------------------------------------------------ where a command worked
ED = ("Edit", {"file_path": "/home/me/proj/src/app.py"}, "ok")


@pytest.mark.parametrize("cmd", GROUPS["D1"], ids=ids(GROUPS["D1"]))
def test_a_stray_path_does_not_move_the_check_to_another_project(cmd, held):
    assert held([bash(cmd, OK), ED], "All 27 tests pass.")


def _dir(cmd):
    return rules.event_dir(Event("tool", name="Bash", text=cmd))


@pytest.mark.parametrize("cmd,want", [("curl https://example.com/api", None), ("curl http://localhost:3000/health", None), ("cd /Users/me/My\\ Project && pytest", "/Users/me/My Project"),
                                      ("cd -P /a/b && pytest", "/a/b"), ("cd -- /a/b && pytest", "/a/b"), ("cd - && pytest", None), ("cd $(git rev-parse --show-toplevel) && pytest", None),
                                      ('cd "$(git rev-parse --show-toplevel)" && pytest', None), ("cd /a && cd /a/", "/a"), ("cd \\\n  /a/b && pytest", "/a/b"), ("git -C \\\n  /a/b status", "/a/b"),
                                      ("git commit -m 'a; cd /x'", None), ('echo "a; cd /x"', None), ("cat > scripts/deploy.sh <<'EOF'\ncd /srv/app\nEOF\npytest", None),
                                      ("cat > scripts/deploy.sh <<'EOF'\ncd /srv/app\nEOF\ncd /home/me/proj && pytest", "/home/me/proj"), ("cd /a/b && pytest", "/a/b"), ("P=/a/b; cd $P && pytest", "/a/b"),
                                      ("git -C '/a b' status", "/a b"), ("git -C /a status && git -C /b status", None), ("cd /a/b; cd /c; pytest", None), ("(cd /a/b && pytest)", "/a/b"), ("pytest /home/me/proj/tests", "/home/me/proj/tests")])
def test_event_dir(cmd, want):
    assert _dir(cmd) == want


def test_home_in_a_cd_is_expanded():
    assert _dir("cd $HOME/p && pytest") == os.path.join(os.path.expanduser("~"), "p")


# ------------------------------------------------------------ whitespace the shell ignores
SAME = ["sed -i 's/a/b/' src/app.py", "git apply fix.diff", "git checkout -- src/app.py", "git reset --hard", "git stash pop", "cat > src/app.py <<'EOF'\nx\nEOF", "echo x > src/app.py",
        "npm test", "go test ./...", "cargo test", "just test", "bun test", "make test", "python manage.py test", "npm run build", "cargo build", "docker build .", "go run .", "uv run python app.py",
        "pytest | head", "go test ./... | wc -l", "cd /a/b && pytest", "git -C /a/b status", "for f in a; do echo x > src/$f.py; done", "if ls; then echo pytest; fi", "for i in 1 2; do pytest | head; done"]


def _answers(cmd):
    return (rules.bash_is_edit(cmd), bool(rules.verifying_segments(cmd, {"test", "build"})), bool(rules.verifying_segments(cmd, {"exercise"})), bool(hooks.find_hidden_status(cmd)), _dir(cmd))


def _respaced(cmd):
    head, sep, rest = cmd.partition("\n")
    return [head.replace(" ", "  ") + sep + rest, head.replace(" ", "\t") + sep + rest, "   " + cmd, head + "   " + sep + rest, cmd + "\n", "\n" + cmd,
            head.replace(" ", " \\\n  ", 1) + sep + rest, head.replace("; ", ";\n") + sep + rest]


@pytest.mark.parametrize("cmd", SAME, ids=ids(SAME))
def test_whitespace_changes_nothing(cmd):
    want = _answers(cmd)
    for variant in _respaced(cmd):
        assert _answers(variant) == want, variant


# ------------------------------------------------------------ input that once made the hook give up and let the reply through
@pytest.mark.parametrize("cmd", GROUPS["Z1"] + GROUPS["Z1b"] + GROUPS["Z1c"], ids=ids(GROUPS["Z1"] + GROUPS["Z1b"] + GROUPS["Z1c"]))
def test_null_bytes_and_lone_surrogates_do_not_raise(cmd, held):
    rules.bash_is_edit(cmd)
    rules.verifying_segments(cmd, T)
    _dir(cmd)
    rules.edit_projects(Event("tool", name="Bash", text=cmd))
    hooks.find_hidden_status(cmd)
    if "pytest" not in cmd:
        assert held([EDIT, bash(cmd)])


def test_edit_paths_with_a_null_byte_do_not_raise():
    assert rules.event_dir(Event("tool", name="Edit", text="~\x00")) == "~\x00"
    assert rules.event_dir(Event("tool", name="Edit", text="~\ud800/a.py"))


@pytest.mark.parametrize("cmd", ["pytest | grep -E '" + "(" * 2000 + "'", "pytest | grep -E '" + "(a" * 2000 + ")" * 2000 + "'", "bash <<E0\n" * 800 + "pytest | head\n", "".join(f"bash <<E{i}\n" for i in range(800)) + "x\n" + "".join(f"E{i}\n" for i in reversed(range(800))), "(" * 5000, "$(" * 5000, "{ " * 5000, "if a; then " * 5000], ids=["grep open", "grep nested", "heredoc same", "heredoc nested", "parens", "subst", "groups", "ifs"])
def test_deep_nesting_does_not_raise(cmd):
    rules.bash_is_edit(cmd)
    rules.verifying_segments(cmd, T)
    hooks.find_hidden_status(cmd)
    _dir(cmd)


@pytest.mark.parametrize("value", [5, ["pytest"], None, {"a": 1}])
def test_a_command_that_is_not_text_does_not_raise(value):
    assert rules.bash_is_edit(value) is False
    assert rules.segments(value) == []
    assert rules.verifying_segments(value, T) == []
    assert hooks.find_hidden_status(value) is None


# ------------------------------------------------------------ paths on Windows: ntpath is the real thing on any system
@pytest.fixture
def windows(monkeypatch):
    import ntpath
    monkeypatch.setenv("USERPROFILE", "C:\\Users\\me")
    monkeypatch.setenv("USERNAME", "me")
    monkeypatch.setattr(os.path, "expanduser", ntpath.expanduser)
    monkeypatch.setattr(os, "sep", "\\")


@pytest.mark.parametrize("cmd,want", [("cd $HOME/p && pytest", "C:\\Users\\me\\p"), ("cd ~/p/q && pytest", "C:\\Users\\me\\p\\q"), ("git -C ~/p status", "C:\\Users\\me\\p"),
                                      ("cd C:\\a\\b && pytest", "C:\\a\\b"), ("cd C:\\a\\b && cd C:/a/b && pytest", "C:\\a\\b")])
def test_a_directory_has_one_kind_of_separator_on_windows(windows, cmd, want):
    assert _dir(cmd) == want


def test_a_relative_cd_keeps_the_separator_of_where_it_started():
    u = [x for x in shell.units("cd C:\\a && cd b/c && pytest") if x.text == "pytest"][0]
    assert u.cwd == "C:\\a\\b\\c"
    assert rules.seg_dir("cd C:\\a && cd b/c && pytest", "pytest") == "C:\\a\\b\\c"


def test_an_edit_in_the_home_folder_has_one_kind_of_separator_on_windows(windows):
    assert rules.event_dir(Event("tool", name="Edit", text="~/src/app.py")) == "C:\\Users\\me\\src\\app.py"


@pytest.mark.parametrize("path", ["~\x00", "~\x00/a.py", "~a\x00b", "~\ud800/a.py", "~\ud800"])
def test_what_cannot_be_a_path_is_left_as_written_on_every_system(windows, path):
    assert shell.expanduser(path) == path
    assert rules.event_dir(Event("tool", name="Edit", text=path)) == path


@pytest.mark.parametrize("path", ["C:\\Users\\me\\AppData\\Local\\Temp\\x\\a.py", "C:/Users/me/AppData/Local/Temp/x/a.py", "C:\\p\\scratchpad\\a.py", "D:\\a\\Temp\\claude\\b.py", "C:\\Temp\\a.py"])
def test_a_temp_folder_is_known_with_either_separator(path):
    assert rules.TEMP_PATH.search(path)
    assert rules.TMP_CWD.search("cd C:\\p\\scratchpad\\x") and rules.TMP_CWD.search("cd C:\\p\\scratchpad")
