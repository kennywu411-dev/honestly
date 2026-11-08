"""Subagent work, read on every assistant, in the shapes the real CLIs wrote."""
import json
import os

import pytest

from real_fixture import load
from test_real_turns import held, stop


@pytest.mark.parametrize("name,claim", [("08b", "All tests pass"), ("08c", "All tests pass"), ("08l", "All tests pass")])
def test_claude_subagent_work_is_read(tmp_path, name, claim):
    p = load(tmp_path, "claude", name, claim)
    assert held(stop(p, claim + ".", background_tasks=[]))


@pytest.mark.parametrize("name", ["08a", "08j"])
def test_claude_a_subagents_passing_run_backs_the_claim(tmp_path, name):
    p = load(tmp_path, "claude", name, "All 5 tests pass")
    assert stop(p, "All 5 tests pass.") is None


def test_codex_a_subagents_passing_run_backs_the_claim(tmp_path):
    p = load(tmp_path, "codex", "08a", "All 5 tests pass")
    assert stop(p, "All 5 tests pass.", "codex") is None


def test_codex_a_subagents_edit_counts(tmp_path):
    p = load(tmp_path, "codex", "08c", "All tests pass")
    assert held(stop(p, "All tests pass.", "codex"))


def test_gemini_a_subagents_passing_run_backs_the_claim(tmp_path):
    p = load(tmp_path, "gemini", "08a", "All 5 tests pass")
    assert stop(p, "All 5 tests pass.", "gemini") is None


def test_gemini_a_subagents_edit_counts(tmp_path):
    p = load(tmp_path, "gemini", "08c", "All tests pass")
    assert held(stop(p, "All tests pass.", "gemini"))


def test_codex_a_subagent_whose_record_is_gone_stays_could_not_check(tmp_path):
    p = load(tmp_path, "codex", "08a", "All 5 tests pass")
    for f in os.listdir(os.path.dirname(p)):
        if os.path.join(os.path.dirname(p), f) != p:
            os.remove(os.path.join(os.path.dirname(p), f))
    assert stop(p, "All 5 tests pass.", "codex") is None


# ---------------------------------------------------------------- a background subagent still at work has reported nothing
def _with_other_worker(tmp_path, tasks_note=None):
    """The main agent reports on what it checked itself, while a background worker it started is still editing somewhere."""
    session = tmp_path / "session.jsonl"
    prompt = {"type": "user", "origin": {"kind": "human"}, "timestamp": "2026-11-08T12:00:00.000Z", "message": {"role": "user", "content": "do the work"}}
    def call(i, name, inp, out):
        ts = f"2026-11-08T12:00:{i:02d}.000Z"
        return [{"type": "assistant", "timestamp": ts, "message": {"role": "assistant", "model": "m", "content": [{"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}]}},
                {"type": "user", "timestamp": ts, "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": out}]}}]
    say = {"type": "assistant", "timestamp": "2026-11-08T12:00:50.000Z", "message": {"role": "assistant", "model": "m", "content": [{"type": "text", "text": "All 5 tests pass."}]}}
    rows = [prompt, *call(1, "Write", {"file_path": "/work/proj/a.py", "content": "x"}, "ok"), *call(2, "Agent", {"prompt": "other job"}, "Async agent launched successfully.\nagentId: w1 (internal ID)"),
            *call(3, "Bash", {"command": "pytest -q"}, "5 passed in 0.1s"), *(tasks_note or []), say]
    session.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    sub = tmp_path / "session" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-w1.meta.json").write_text(json.dumps({"toolUseId": "t2", "requestShape": "background"}), encoding="utf-8")
    (sub / "agent-w1.jsonl").write_text(json.dumps({"type": "assistant", "isSidechain": True, "timestamp": "2026-11-08T12:00:30.000Z", "message": {"role": "assistant", "model": "m", "content": [{"type": "tool_use", "id": "s1", "name": "Write", "input": {"file_path": "/work/proj/other.py", "content": "y"}}]}}) + "\n"
                                       + json.dumps({"type": "user", "isSidechain": True, "timestamp": "2026-11-08T12:00:30.000Z", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "s1", "content": "ok"}]}}) + "\n", encoding="utf-8")
    return str(session)


def test_a_worker_still_editing_does_not_make_a_finished_check_stale(tmp_path):
    p = _with_other_worker(tmp_path)
    assert stop(p, "All 5 tests pass.", background_tasks=[{"id": "w1", "type": "subagent", "status": "running"}]) is None


def test_a_worker_that_has_finished_does(tmp_path):
    p = _with_other_worker(tmp_path)
    assert held(stop(p, "All 5 tests pass.", background_tasks=[]))


def test_a_worker_that_reported_back_does(tmp_path):
    note = [{"type": "user", "origin": {"kind": "task-notification"}, "promptSource": "system", "turnOrigin": "task_notification", "timestamp": "2026-11-08T12:00:40.000Z",
             "message": {"role": "user", "content": "<task-notification>\n<task-id>w1</task-id>\n<tool-use-id>t2</tool-use-id>\n<status>completed</status>\n</task-notification>"}}]
    assert held(stop(_with_other_worker(tmp_path, note), "All 5 tests pass."))


def test_with_no_word_on_the_worker_its_edit_does_not_decide(tmp_path):
    assert stop(_with_other_worker(tmp_path), "All 5 tests pass.") is None
