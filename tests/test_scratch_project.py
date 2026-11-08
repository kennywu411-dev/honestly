"""A project that happens to live under /tmp is a project. A scratch file somewhere else is still a scratch file."""
import json

import pytest

from honestly import hooks


def _hold(tmp_path, cwd, path=None, bash=None):
    tool = {"name": "Write", "input": {"file_path": path, "content": "x"}} if path else {"name": "Bash", "input": {"command": bash}}
    rows = [{"type": "user", "cwd": cwd, "origin": {"kind": "human"}, "promptSource": "typed", "message": {"role": "user", "content": "try it"}},
            {"type": "assistant", "cwd": cwd, "message": {"role": "assistant", "model": "m", "content": [{"type": "tool_use", "id": "t0", "name": "Bash", "input": {"command": "pytest -q"}}]}},   # passed, then the write: stale only if the write is an edit
            {"type": "user", "cwd": cwd, "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t0", "content": "5 passed in 0.1s"}]}},
            {"type": "assistant", "cwd": cwd, "message": {"role": "assistant", "model": "m", "content": [{"type": "tool_use", "id": "t1", **tool}]}},
            {"type": "user", "cwd": cwd, "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}]
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    out = hooks.stop_hook({"transcript_path": str(p), "cwd": cwd, "last_assistant_message": "All tests pass.", "stop_hook_active": False})
    return bool(out) and out.get("decision") == "block"


@pytest.mark.parametrize("cwd,path", [
    ("/tmp/demo", "/tmp/demo/app.py"),
    ("/private/tmp/demo", "/private/tmp/demo/src/app.py"),
    ("/private/tmp/demo", "/tmp/demo/app.py"),                 # macOS: the same folder under its other name
    ("/tmp/demo", "/private/tmp/demo/app.py"),
    ("/var/folders/ab/cd/T/tryit", "/var/folders/ab/cd/T/tryit/app.py"),
])
def test_an_edit_inside_a_project_under_a_temp_folder_counts(tmp_path, cwd, path):
    assert _hold(tmp_path, cwd, path)


@pytest.mark.parametrize("cwd,path", [
    ("/Users/me/proj", "/tmp/probe.py"),                       # a scratch script beside the real work
    ("/Users/me/proj", "/private/tmp/demo/app.py"),
    ("/tmp/demo", "/tmp/other/probe.py"),                      # outside the project it is in
    ("/tmp", "/tmp/probe.py"),                                 # the temp folder itself is not a project
    ("/private/tmp", "/private/tmp/probe.py"),
    ("/private/tmp/claude-501/-Users-me/abc/scratchpad", "/private/tmp/claude-501/-Users-me/abc/scratchpad/probe.py"),   # an agent's own scratch space
    ("/private/tmp/claude-501/-Users-me/abc", "/private/tmp/claude-501/-Users-me/abc/probe.py"),
    ("/tmp/demo", "/tmp/demo/README.md"),                      # notes stay notes
    ("/tmp/demo", "/tmp/demo/docs/guide.md"),
])
def test_a_scratch_file_is_still_not_a_code_edit(tmp_path, cwd, path):
    assert not _hold(tmp_path, cwd, path)


def test_a_shell_edit_inside_a_project_under_a_temp_folder_counts(tmp_path):
    assert _hold(tmp_path, "/tmp/demo", bash="sed -i '' 's/a/b/' /tmp/demo/app.py")
    assert _hold(tmp_path, "/private/tmp/demo", bash="cd /private/tmp/demo && echo 'x = 1' > app.py")


def test_a_shell_scratch_write_stays_scratch(tmp_path):
    assert not _hold(tmp_path, "/Users/me/proj", bash="echo 'x = 1' > /tmp/probe.py")
    assert not _hold(tmp_path, "/tmp/demo", bash="echo 'x = 1' > /tmp/other/probe.py")
