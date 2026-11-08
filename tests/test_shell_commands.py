"""What honestly must make of real shell lines: each group is one cause from the audit, in real commands, through the real functions and the real stop hook."""
import json
import os

import pytest

from honestly import hooks, rules
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


