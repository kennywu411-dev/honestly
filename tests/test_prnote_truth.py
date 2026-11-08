"""pr-note must never state something false: when it cannot know, it says so. Each case here once printed a false line."""
import json
import os
import subprocess

import pytest

from honestly import cli, prnote

TS = "2026-02-01T10:{:02d}:{:02d}Z"
OLD = 1700000000   # long before every transcript time below
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")


def git(root, *args, when=None):
    env = dict(ENV)
    if when:
        env.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    return subprocess.run(["git", *args], cwd=root, check=True, env=env, capture_output=True, text=True).stdout.strip()


def age(root):
    """Everything on disk predates the transcript, as it does when the agent's edits came before its test."""
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x != ".git"]
        for f in files:
            os.utime(os.path.join(d, f), (OLD, OLD))


def repo(tmp_path, name="app"):
    root = tmp_path / name
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "a.py").write_text("x = 1\n")
    (root / "README.md").write_text("hello\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init", when="2026-02-01T08:00:00Z")
    age(root)
    return os.path.realpath(root)


def session(claude_root, cwd, steps, name="s1", minute=0):
    d = os.path.join(str(claude_root), prnote._encoded(cwd))
    os.makedirs(d, exist_ok=True)
    n = [0]

    def ts():
        n[0] += 1
        return TS.format(minute, n[0])

    rows = [{"type": "user", "message": {"role": "user", "content": "work"}, "origin": {"kind": "human"}, "cwd": cwd, "timestamp": ts()}]
    for i, st in enumerate(steps):
        tid = f"{name}-{i}"
        if st[0] == "say":
            rows.append({"type": "assistant", "message": {"role": "assistant", "model": "m", "content": [{"type": "text", "text": st[1]}]}, "cwd": cwd, "timestamp": ts()})
            continue
        if st[0] == "edit":
            use, out, err = {"type": "tool_use", "id": tid, "name": "Edit", "input": {"file_path": st[1], "old_string": "a", "new_string": "b"}}, "ok", False
        else:
            use, out, err = {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": st[1]}}, st[2], (st[3] if len(st) > 3 else False)
        rows.append({"type": "assistant", "message": {"role": "assistant", "model": "m", "content": [use]}, "cwd": cwd, "timestamp": ts()})
        rows.append({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": out, "is_error": err}]}, "cwd": cwd, "timestamp": ts()})
    with open(os.path.join(d, name + ".jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def note(root, cr, **kw):
    kw.setdefault("since", "2026-02-01T09:00:00Z")
    return prnote.run(root, agents=("claude-code",), claude_root=str(cr), **kw)


def check_code(root, cr, *extra):
    here = os.getcwd()
    os.chdir(root)
    try:
        cli.main(["pr-note", "--agent", "claude-code", "--root", str(cr), "--check", *extra])
    except SystemExit as e:
        return e.code
    finally:
        os.chdir(here)
    return 0


EDIT = ("edit", "a.py")
PASS = ("bash", "pytest -q", "3 passed in 0.2s\n")
FAIL = ("bash", "pytest -q", "1 failed, 2 passed in 0.3s\n", True)


# ------------------------------------------------------------------ what counts as a passing test
@pytest.mark.parametrize("cmd,out", [("git commit -am 'Fix login, 12 passed'", "[feature abc123] Fix login, 12 passed\n 1 file changed\n"),
                                     ("git commit -am 'all 12 passed'", "[main 1a2b3c4] all 12 passed\n")])
def test_a_commit_message_echoed_back_is_not_a_hook_run(tmp_path, cmd, out):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, ("bash", cmd, out)])
    ev, block = note(root, cr)
    assert ev.status == "none" and "Tests ran after" not in block and "pre-commit hook" not in block


def test_a_lint_and_a_commit_message_is_only_a_lint(tmp_path):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, ("bash", "ruff check . && git commit -am 'Fix, all 12 passed'", "All checks passed!\n[feature abc123] Fix, all 12 passed\n")])
    ev, block = note(root, cr)
    assert ev.status == "no-test" and "Tests ran after" not in block and "12 passed" not in block.split("<sub>")[0].replace("all 12 passed", "")


def test_a_real_hook_run_still_counts(tmp_path):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, ("bash", "git commit -am x", "pre-commit: running\n12 passed in 1s\n[feature abc] x\n")])
    ev, block = note(root, cr)
    assert ev.status == "pass" and "`12 passed in 1s`" in block


@pytest.mark.parametrize("cmd,out", [("npm run build", "built in 3s\n"), ("ruff check .", "All checks passed!\n"), ("tsc --noEmit", "")])
def test_a_build_or_lint_is_not_called_a_test(tmp_path, cmd, out):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, ("bash", cmd, out)])
    ev, block = note(root, cr)
    assert ev.status == "no-test"
    assert "Tests ran after" not in block and "No test ran after the last code edit" in block
    assert f"`{cmd}`" in block   # the row still shows what did run


def test_a_build_only_fails_the_gate(tmp_path):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, ("bash", "npm run build", "built in 3s\n")])
    assert check_code(root, cr, "--since", "2026-02-01T09:00:00Z") == 1


@pytest.mark.parametrize("cmd,out", [("pytest | tail -3", "tests/a.py ..\nplugin output\n"), ("pytest -k x | head -3", "collected 3 items\n"), ("pytest | grep SKIP", "")])
def test_a_run_with_no_result_on_screen_is_not_called_failed(tmp_path, cmd, out):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, ("bash", cmd, out)])
    ev, block = note(root, cr)
    assert ev.status == "unclear" and "❌" not in block and "failed" not in block.split("<sub>")[0]
    assert "no pass/fail line" in block


def test_a_crash_is_still_called_failed(tmp_path):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, ("bash", "pytest -q", "Traceback (most recent call last):\nImportError\n", True)])
    ev, block = note(root, cr)
    assert ev.status == "fail" and "❌" in block


@pytest.mark.parametrize("cmd,out", [("pytest -k foo", "1 passed, 11 deselected\n"), ("pytest tests/test_a.py", "1 passed\n"), ("pytest tests/unit/small/ -q", "1 passed\n"), ("pytest --lf", "1 passed\n")])
def test_a_narrowed_pass_says_narrowed(tmp_path, cmd, out):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, ("bash", cmd, out)])
    ev, block = note(root, cr)
    assert ev.status == "narrowed"
    assert "Only a narrowed test run ran after the last code edit" in block and "no pass/fail line" not in block and "Tests ran after" not in block
    assert check_code(root, cr, "--since", "2026-02-01T09:00:00Z") == 1


@pytest.mark.parametrize("cmd", ["pytest", "pytest -q -x", "pytest tests/", "pytest -n 4 --tb=short", "python -m pytest tests", "go test ./...", "npm test", "cargo test", "pytest 2>&1"])
def test_a_whole_suite_is_not_narrowed(tmp_path, cmd):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, ("bash", cmd, "3 passed in 1s\n")])
    assert note(root, cr)[0].status == "pass"


@pytest.mark.parametrize("later", [("bash", "pytest tests/test_a.py -q", "3 passed\n"), ("bash", "pytest -q --lf", "1 passed\n"), ("bash", "pytest tests/d0/ -q", "1 passed\n"), ("bash", "npm test", "5 passed\n"), ("bash", "npm run build", "built\n")])
def test_a_failure_is_not_cleared_by_a_narrower_or_other_run(tmp_path, later):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, FAIL, later])
    ev, block = note(root, cr)
    assert ev.status == "fail", block
    assert "Tests ran after" not in block and "1 failed" in block
    assert check_code(root, cr, "--since", "2026-02-01T09:00:00Z") == 1


@pytest.mark.parametrize("first,later", [(FAIL, ("bash", "pytest -q", "3 passed\n")), (FAIL, ("bash", "python -m pytest", "3 passed\n")), (("bash", "pytest tests/test_a.py", "1 failed\n", True), ("bash", "pytest", "3 passed\n"))])
def test_a_failure_is_cleared_by_the_same_or_a_wider_run(tmp_path, first, later):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, first, later])
    assert note(root, cr)[0].status == "pass"


def test_a_narrowed_failure_is_cleared_by_the_same_narrowed_run_but_stays_narrowed(tmp_path):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, ("bash", "pytest tests/test_a.py", "1 failed\n", True), ("bash", "pytest tests/test_a.py", "1 passed\n")])
    assert note(root, cr)[0].status == "narrowed"


def test_a_narrow_run_after_a_whole_pass_keeps_the_pass(tmp_path):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, PASS, ("bash", "pytest -k one", "1 passed, 2 deselected\n")])
    assert note(root, cr)[0].status == "pass"


@pytest.mark.parametrize("cmd,out", [("gh pr checks", "All checks passed\n"), ("gh run view 12", "✓ main CI · 12\n")])
def test_reading_ci_is_not_a_test_run_here(tmp_path, cmd, out):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, ("bash", cmd, out)])
    ev, block = note(root, cr)
    assert ev.status == "unclear" and "Tests ran after" not in block


# ------------------------------------------------------------------ what happened on disk after the test
def test_committing_what_was_tested_is_not_a_change(tmp_path):
    root, cr = repo(tmp_path), tmp_path / "c"
    (tmp_path / "app" / "a.py").write_text("x = 2\n")
    age(root)
    session(cr, root, [EDIT, PASS])
    git(root, "commit", "-qam", "work", when="2026-02-01T10:30:00Z")
    ev, _ = note(root, cr)
    assert ev.status == "pass" and not ev.changed


def test_a_dirty_tree_after_the_test_is_called_out(tmp_path):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, PASS])
    (tmp_path / "app" / "a.py").write_text("broken\n")
    ev, block = note(root, cr)
    assert ev.status == "stale" and ev.changed == ["a.py"]
    assert "Tests ran after" not in block and "Code changed after the last test" in block and "`a.py`" in block
    assert check_code(root, cr, "--since", "2026-02-01T09:00:00Z") == 1


def test_a_later_commit_of_new_code_is_called_out(tmp_path):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, PASS])
    (tmp_path / "app" / "other.py").write_text("y = 1\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "by hand", when="2026-02-01T11:00:00Z")
    ev, block = note(root, cr)
    assert ev.status == "stale" and ev.changed == ["other.py"]


@pytest.mark.parametrize("change", ["rm", "git rm", "git mv", "mv", "untracked", "committed rm", "committed mv"])
def test_every_way_code_can_change_is_called_out(tmp_path, change):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, PASS])
    app = tmp_path / "app"
    if change == "rm":
        (app / "a.py").unlink()
    elif change == "git rm":
        git(root, "rm", "-q", "a.py")
    elif change == "git mv":
        git(root, "mv", "a.py", "b.py")
    elif change == "mv":
        (app / "a.py").rename(app / "b.py")
    elif change == "untracked":
        (app / "new.py").write_text("z = 1\n")
    elif change == "committed rm":
        git(root, "rm", "-q", "a.py")
        git(root, "commit", "-qm", "rm", when="2026-02-01T11:00:00Z")
    else:
        git(root, "mv", "a.py", "b.py")
        git(root, "commit", "-qm", "mv", when="2026-02-01T11:00:00Z")
    ev, block = note(root, cr)
    assert ev.status == "stale", block
    assert "Tests ran after" not in block


def test_a_formatter_or_pull_is_seen_by_what_it_wrote(tmp_path):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, PASS, ("bash", "black .", "reformatted a.py\n")])
    (tmp_path / "app" / "a.py").write_text("x = 1  # reformatted\n")
    assert note(root, cr)[0].status == "stale"
    root2, cr2 = repo(tmp_path, "unchanged"), tmp_path / "c2"
    session(cr2, root2, [EDIT, PASS, ("bash", "black .", "All done! 1 file left unchanged.\n")])
    assert note(root2, cr2)[0].status == "pass"   # it changed nothing


def test_docs_and_ignored_files_do_not_count(tmp_path):
    root, cr = repo(tmp_path), tmp_path / "c"
    app = tmp_path / "app"
    (app / ".gitignore").write_text("build/\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "ignore", when="2026-02-01T08:30:00Z")
    age(root)
    session(cr, root, [EDIT, PASS])
    (app / "README.md").write_text("more\n")
    (app / "build").mkdir()
    (app / "build" / "out.py").write_text("generated\n")
    (app / "notes.txt").write_text("x\n")
    assert note(root, cr)[0].status == "pass"


def test_a_failure_stays_a_failure_when_code_also_changed(tmp_path):
    root, cr = repo(tmp_path), tmp_path / "c"
    session(cr, root, [EDIT, FAIL])
    (tmp_path / "app" / "a.py").write_text("y\n")
    assert note(root, cr)[0].status == "fail"


def test_evidence_from_another_branch_is_not_reported_as_this_ones(tmp_path):
    root, cr = repo(tmp_path), tmp_path / "c"
    git(root, "checkout", "-qb", "feature-a")
    session(cr, root, [("edit", "only_on_a.py"), PASS])
    (tmp_path / "app" / "only_on_a.py").write_text("x\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "a", when="2026-02-01T10:30:00Z")
    git(root, "checkout", "-q", "main")
    git(root, "checkout", "-qb", "feature-b")
    ev, block = note(root, cr)
    assert ev.status == "elsewhere", block
    assert "Tests ran after" not in block and "`only_on_a.py`" in block and "not in this working tree" in block
    assert check_code(root, cr, "--since", "2026-02-01T09:00:00Z") == 1


def test_switching_branch_rewrites_what_differs_and_is_called_out(tmp_path):
    root, cr = repo(tmp_path), tmp_path / "c"
    git(root, "checkout", "-qb", "feature-a")
    (tmp_path / "app" / "a.py").write_text("x = 22\n")   # a new size: git trusts an unchanged time and size
    age(root)
    session(cr, root, [EDIT, PASS])
    git(root, "commit", "-qam", "a", when="2026-02-01T10:30:00Z")
    git(root, "checkout", "-q", "main")
    assert note(root, cr)[0].status == "stale"
