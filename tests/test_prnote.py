import json
import os
import subprocess

import pytest

from honestly import cli, prnote

TS = "2026-02-01T10:00:{:02d}Z"


def _repo(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "a.py").write_text("x = 1\n")
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True, env=env)
    return os.path.realpath(root)


def _session(claude_root, cwd, steps, name="s1"):
    """steps: ("edit", path) | ("bash", command, output, is_error) | ("say", text)"""
    d = os.path.join(claude_root, prnote._encoded(cwd))
    os.makedirs(d, exist_ok=True)
    rows = [{"type": "user", "message": {"role": "user", "content": "work"}, "origin": {"kind": "human"}, "cwd": cwd, "timestamp": TS.format(0)}]
    n = 1
    for i, st in enumerate(steps):
        tid = f"t{i}"
        if st[0] == "say":
            rows.append({"type": "assistant", "message": {"role": "assistant", "model": "m", "content": [{"type": "text", "text": st[1]}]}, "cwd": cwd, "timestamp": TS.format(n)}); n += 1
            continue
        if st[0] == "edit":
            use = {"type": "tool_use", "id": tid, "name": "Edit", "input": {"file_path": st[1], "old_string": "a", "new_string": "b"}}
            res = {"type": "tool_result", "tool_use_id": tid, "content": "ok"}
        else:
            use = {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": st[1]}}
            res = {"type": "tool_result", "tool_use_id": tid, "content": st[2], "is_error": st[3]}
        rows.append({"type": "assistant", "message": {"role": "assistant", "model": "m", "content": [use]}, "cwd": cwd, "timestamp": TS.format(n)}); n += 1
        rows.append({"type": "user", "message": {"role": "user", "content": [res]}, "cwd": cwd, "timestamp": TS.format(n)}); n += 1
    with open(os.path.join(d, name + ".jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _note(root, claude_root):
    return prnote.run(root, since="2026-02-01T09:00:00Z", agents=("claude-code",), claude_root=str(claude_root))


def test_tests_after_the_last_edit_are_reported_with_their_summary(tmp_path):
    root, cr = _repo(tmp_path), tmp_path / "claude"
    _session(str(cr), root, [("edit", "a.py"), ("bash", "pytest -q", "...\n3 passed in 0.2s\n", False), ("say", "All tests pass.")])
    ev, block = _note(root, cr)
    assert ev.status == "pass"
    assert "Tests ran after the last code edit and passed: `3 passed in 0.2s`" in block
    assert "| `pytest -q` | ✅ passed | `3 passed in 0.2s` |" in block
    assert "1 verified, 0 unverified" in block
    assert block.startswith(prnote.START) and block.rstrip().endswith(prnote.END)


def test_an_edit_after_the_last_test_run_is_called_out(tmp_path):
    root, cr = _repo(tmp_path), tmp_path / "claude"
    _session(str(cr), root, [("edit", "a.py"), ("bash", "pytest -q", "3 passed in 0.2s\n", False), ("edit", "b.py"), ("say", "Fixed, tests pass.")])
    ev, block = _note(root, cr)
    assert ev.status == "none"
    assert "No test or build ran after the last code edit" in block and "`b.py`" in block
    assert "1 earlier check run before the last edit is not counted" in block
    assert "Claims with nothing behind them" in block and "unverified" in block


def test_failures_and_empty_runs(tmp_path):
    root, cr = _repo(tmp_path), tmp_path / "claude"
    _session(str(cr), root, [("edit", "a.py"), ("bash", "pytest -q", "1 failed, 2 passed in 0.3s\n", True)])
    ev, block = _note(root, cr)
    assert ev.status == "fail" and "❌ failed" in block
    _session(str(cr), root, [("edit", "a.py"), ("bash", "go test ./...", "ok  \tpkg/a\t0.001s [no tests to run]\n", False)], name="s1")
    ev, block = _note(root, cr)
    assert ev.status == "unclear" and "no tests collected" in block


def test_a_session_opened_elsewhere_counts_only_where_it_names_the_repo(tmp_path, monkeypatch):
    from honestly import rules
    monkeypatch.setattr(rules, "path_is_doc", lambda p: p.endswith(".md"))   # pytest's tmp dir would count as scratch space
    root, cr = _repo(tmp_path), tmp_path / "claude"
    other = str(tmp_path / "elsewhere")
    os.makedirs(other)
    _session(str(cr), other, [("edit", os.path.join(root, "a.py")), ("bash", f"cd {root} && pytest -q", "5 passed in 1s\n", False),
                              ("edit", os.path.join(other, "unrelated.py")), ("bash", "pytest -q", "1 failed in 1s\n", True)])
    ev, block = _note(root, cr)
    assert ev.status == "pass" and ev.last_edit == "a.py"
    assert "unrelated" not in block and "1 failed" not in block


def test_unrelated_repositories_and_old_turns_are_ignored(tmp_path):
    root, cr = _repo(tmp_path), tmp_path / "claude"
    other = str(tmp_path / "other-repo")
    os.makedirs(other)
    _session(str(cr), other, [("edit", "x.py"), ("bash", "pytest -q", "9 passed\n", False)])
    ev, block = _note(root, cr)
    assert ev.sessions == 0 and ev.status == "no-edit" and "No code edit by an agent" in block
    ev, _ = prnote.run(root, since="2026-02-01T11:00:00Z", agents=("claude-code",), claude_root=str(cr))
    assert ev.sessions == 0


def test_secrets_and_home_paths_are_redacted(tmp_path):
    root, cr = _repo(tmp_path), tmp_path / "claude"
    home = os.path.expanduser("~")
    _session(str(cr), root, [("edit", "a.py"), ("bash", f"API_KEY=sk-live-abcdefghijklmnopqrstuvwxyz pytest -q {home}/x", "2 passed in 0.1s\n", False)])
    _, block = _note(root, cr)
    assert "sk-live" not in block and home not in block and "`pytest -q ~/x`" in block
    _session(str(cr), root, [("edit", "a.py"), ("bash", "pytest -q --token=ghp_abcdefghijklmnopqrstuvwxyz0123", "2 passed in 0.1s\n", False)])
    _, block = _note(root, cr)
    assert "ghp_" not in block and "<redacted>" in block


def test_splice_replaces_an_earlier_note_and_keeps_the_rest():
    a = prnote.START + "\nold\n" + prnote.END + "\n"
    b = prnote.START + "\nnew\n" + prnote.END + "\n"
    body = "## Summary\n\nFixes the parser.\n"
    once = prnote.splice(body, a)
    assert once.startswith(body.rstrip()) and once.endswith(a)
    twice = prnote.splice(once, b)
    assert "old" not in twice and twice.count(prnote.START) == 1 and "Fixes the parser." in twice
    assert prnote.splice(twice, b) == twice
    assert prnote.splice("", b) == b


def test_cli_check_exit_code(tmp_path, monkeypatch, capsys):
    root, cr = _repo(tmp_path), tmp_path / "claude"
    _session(str(cr), root, [("edit", "a.py"), ("say", "Done, tests pass.")])
    monkeypatch.chdir(root)
    with pytest.raises(SystemExit) as e:
        cli.main(["pr-note", "--since", "2026-02-01T09:00:00Z", "--agent", "claude-code", "--root", str(cr), "--check"])
    assert e.value.code == 1 and "No test or build ran" in capsys.readouterr().out
    _session(str(cr), root, [("edit", "a.py"), ("bash", "pytest", "4 passed\n", False)])
    cli.main(["pr-note", "--since", "2026-02-01T09:00:00Z", "--agent", "claude-code", "--root", str(cr), "--check"])
    assert "4 passed" in capsys.readouterr().out


def test_window_defaults_to_where_the_branch_left_its_base(tmp_path):
    root = _repo(tmp_path)
    cutoff, label = prnote.window_start(root, "", None)
    assert label == "since the last commit" and cutoff.startswith("20")
    assert prnote.window_start(root, "", "2h")[1] == "last 2h"
    with pytest.raises(SystemExit):
        prnote.window_start(root, "", "yesterday")


def test_not_a_git_repository(tmp_path):
    with pytest.raises(SystemExit):
        prnote.repo_root(str(tmp_path))


@pytest.mark.skipif(os.name == "nt", reason="fake gh is a shell script")
def test_gh_mode_puts_the_note_into_the_pr_once(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    store = tmp_path / "body.md"
    store.write_text("## Summary\n\nFixes the parser.\n")
    gh = tmp_path / "bin" / "gh"
    gh.parent.mkdir()
    gh.write_text(f"""#!/bin/sh
if [ "$2" = "view" ]; then
  python3 -c 'import json,sys; print(json.dumps({{"number": 7, "url": "https://example.com/pr/7", "body": open(sys.argv[1]).read()}}))' {store}
else
  cat > {store}
fi
""")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{gh.parent}{os.pathsep}{os.environ['PATH']}")
    block = prnote.START + "\nnote\n" + prnote.END + "\n"
    assert prnote.update_pr(root, block) == "honestly pr-note: updated https://example.com/pr/7"
    body = store.read_text()
    assert body.startswith("## Summary") and body.count(prnote.START) == 1
    assert "already has this note" in prnote.update_pr(root, block)


def test_real_world_shell_shapes(tmp_path, monkeypatch):
    import re
    from honestly import rules
    monkeypatch.setattr(rules, "path_is_doc", lambda p: p.endswith(".md"))
    monkeypatch.setattr(rules, "TMP_CWD", re.compile(r"(?!)"))   # pytest's tmp dir is /tmp on Linux: `cd /tmp/…` would mark the edit as scratch work
    root, cr = _repo(tmp_path), tmp_path / "claude"
    other = str(tmp_path / "tool")
    os.makedirs(other)
    elsewhere = str(tmp_path / "home")
    os.makedirs(elsewhere)
    _session(str(cr), elsewhere, [
        # an edit of a loop over two checkouts, one of them this repository
        ("bash", f"for d in {root} {other}; do cd $d && sed -i 's/a/b/' gate.py; done", "", False),
        # edit + lint + commit whose pre-commit hook runs the tests, in one command
        ("bash", f"cd {root} && sed -i 's/b/c/' gate.py && ruff check gate.py && GIT_AUTHOR_NAME=x git commit -qam fix",
         "All checks passed!\n[pre-commit] pytest\n12 passed in 1.0s\n", False),
        # work in another checkout whose command only later cds here must not count
        ("bash", f"cd {other} && sed -i 's/x/y/' tool.py && pytest -q; cd {root} && git status", "1 failed in 0.1s\n", True),
    ])
    ev, block = _note(root, cr)
    assert ev.last_edit == "gate.py" and ev.status == "pass"
    assert "| `git commit (its pre-commit hook ran the checks)` | ✅ passed | `12 passed in 1.0s` |" in block
    assert "tool.py" not in block and "1 failed" not in block and "GIT_AUTHOR" not in block


def test_a_loop_keyword_is_not_an_edited_file(tmp_path, monkeypatch):
    import re
    from honestly import rules
    monkeypatch.setattr(rules, "path_is_doc", lambda p: p.endswith(".md"))
    monkeypatch.setattr(rules, "TMP_CWD", re.compile(r"(?!)"))
    root, cr = _repo(tmp_path), tmp_path / "claude"
    _session(str(cr), root, [("bash", "for f in a b; do sed -i 's/a/b/' gate.py; done", "", False)])
    ev, _ = _note(root, cr)
    assert ev.last_edit == "gate.py"
