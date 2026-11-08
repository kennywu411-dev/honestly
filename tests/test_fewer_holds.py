"""Holding a reply costs a turn, so by default only what is rarely wrong holds one. `strictness strict` brings the rest back."""
import json

import pytest

from honestly import audit, config, hooks
from honestly.audit import Event, Turn


def verdicts(*events):
    return [f.verdict for f in audit.audit_turn(Turn(session="s", index=0, version="", prompt="fix it", events=list(events)), None)]


def bash(cmd, out="", err=False):
    return Event("tool", name="Bash", text=cmd, result=out, is_error=err)


def edit(path="/p/src/app.py"):
    return Event("tool", name="Edit", text=path, result="The file has been updated successfully.")


def say(text):
    return Event("text", text=text)


PYTEST = bash("pytest -q", "27 passed in 14.09s")


# ---- what still holds a reply
def test_no_run_at_all_is_held():
    assert verdicts(edit(), say("All tests pass.")) == ["unbacked"]
    assert verdicts(edit(), say("Fixed the crash.")) == ["unbacked"]


def test_a_failed_run_is_held():
    assert verdicts(edit(), bash("pytest -q", "1 failed, 26 passed", True), say("All tests pass.")) == ["contradicted"]


def test_a_stale_pass_with_nothing_after_the_edit_is_held():
    assert verdicts(edit(), PYTEST, edit(), say("All tests pass.")) == ["unbacked"]


# ---- a stale pass that some later check followed
def test_a_lint_check_after_the_last_edit_is_not_held():
    assert verdicts(edit(), PYTEST, edit(), bash("ruff check .", "All checks passed!"), say("All tests pass.")) == ["weak"]


def test_a_lint_check_in_the_edit_command_is_not_held():
    cmd = "sed -i '' 's/a/b/' src/app.py && ruff check src && echo ok"
    assert verdicts(edit(), PYTEST, bash(cmd, "All checks passed!\nok"), say("All 27 tests pass.")) == ["weak"]


def test_a_failed_lint_check_does_not_help():
    assert verdicts(edit(), PYTEST, edit(), bash("ruff check .", "Found 2 errors.", True), say("All tests pass.")) == ["unbacked"]


def test_a_lint_check_without_any_earlier_pass_does_not_help():
    assert verdicts(edit(), bash("ruff check .", "All checks passed!"), say("All tests pass.")) == ["unbacked"]


def test_an_earlier_failed_run_does_not_help():
    failed = bash("pytest -q", "1 failed, 26 passed", True)
    assert verdicts(edit(), failed, edit(), bash("ruff check .", "All checks passed!"), say("All tests pass.")) == ["unbacked"]


# ---- "fixed" after a run that passed
def test_fixed_after_an_earlier_pass_is_not_held():
    assert verdicts(edit(), PYTEST, edit("/p/scripts/report.py"), say("已修复并加了回归测试。")) == ["weak"]


def test_fixed_after_an_earlier_failure_is_held():
    assert verdicts(edit(), bash("pytest -q", "1 failed, 26 passed", True), edit(), say("Fixed the crash.")) == ["unbacked"]


# ---- what the hook does with each verdict
def _stop(tmp_path, monkeypatch, reply, strictness="normal", events=()):
    monkeypatch.setattr(config, "load", lambda cwd=None: {**config.DEFAULTS, "strictness": strictness})
    rows = [{"type": "user", "message": {"role": "user", "content": "go"}, "origin": {"kind": "human"}}]
    for i, (name, inp, out) in enumerate(events):
        rows.append({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}]}})
        rows.append({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": out}]}})
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return hooks.stop_hook({"transcript_path": str(p), "last_assistant_message": reply, "stop_hook_active": False})


LOOKED = [("Bash", {"command": "ls"}, "a.txt")]   # a turn with no tools at all is never judged


@pytest.mark.parametrize("reply", ["The report is saved to report.csv.", "好，定时已设好：凌晨 1:00 开工。", "Email sent to the team.", "已上线。"])
def test_a_claim_about_something_other_than_code_does_not_hold_by_default(tmp_path, monkeypatch, reply):
    assert _stop(tmp_path, monkeypatch, reply, events=LOOKED) is None


def test_strict_holds_it(tmp_path, monkeypatch):
    out = _stop(tmp_path, monkeypatch, "The report is saved to report.csv.", "strict", events=LOOKED)
    assert out and out["decision"] == "block"


def test_a_code_claim_still_holds_by_default(tmp_path, monkeypatch):
    out = _stop(tmp_path, monkeypatch, "All tests pass.", events=[("Edit", {"file_path": "/p/src/app.py"}, "ok")])
    assert out and out["decision"] == "block"


def test_lenient_still_holds_a_failed_run(tmp_path, monkeypatch):
    run = ("Bash", {"command": "pytest -q"}, "1 failed, 4 passed in 0.1s")
    out = _stop(tmp_path, monkeypatch, "All tests pass.", "lenient", events=[("Edit", {"file_path": "/p/src/app.py"}, "ok"), run])
    assert out and out["decision"] == "block"


# ---- the pre hook
@pytest.mark.parametrize("cmd", [
    "uv run pytest -q -rs 2>&1 | grep SKIP",
    "pytest -q --durations=5 2>&1 | grep -E 's (call|setup)' | cut -c1-110",
    "npm test 2>&1 | grep -v warning",
    "npm test | Select-String foo",
    ".venv/bin/pytest tests/test_fixes.py -q -k spikes 2>&1 | grep -E 'zzz' | head -5",
    "python -m pytest -q tests/test_v062.py -x 2>&1 | grep -E 'zzz' | head -8",
    "pytest tests/test_a.py::test_x | head -5",
    "pytest -k spikes | head",
    "go test -run TestX ./... | head -5",
    "npx jest src/a.test.js | head -20",
])
def test_looking_for_one_thing_in_a_run_is_allowed(cmd):
    assert hooks.find_hidden_status(cmd) is None, cmd
    assert hooks.find_hidden_status(cmd, strict=True) is not None, cmd


@pytest.mark.parametrize("cmd", [
    "pytest | head", "pytest -q | head -5", "npm test | head -3", "cargo test 2>&1 | head", "go test ./... | head", "make test | head",
    "CI=1 pytest | head", "pytest | grep -c passed", "npm test | wc -l", "pytest | Out-Null", "pytest -q | Select-String passed -Quiet",
    "pytest | Select-Object -First 5", "npm test --workspaces | tail -5", "pytest -k foo | Out-Null",
])
def test_hiding_a_whole_runs_result_is_still_refused(cmd):
    assert hooks.find_hidden_status(cmd) is not None, cmd


# ---- recording
def test_a_call_with_no_session_is_not_recorded(tmp_path, monkeypatch):
    log = tmp_path / "c.jsonl"
    monkeypatch.setattr(hooks, "catches_path", lambda: str(log))
    assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "pytest | head"}}) is not None
    assert not log.exists()
    assert hooks.pre_hook({"tool_name": "Bash", "session_id": "abc", "tool_input": {"command": "pytest | head"}}) is not None
    assert log.exists()


# ---- #23: a failure word from another step
@pytest.mark.parametrize("out", [
    "https://github.com/x/y/releases/tag/v1\ndotnet failed : contradicted\npytest error  : contradicted",
    "Deployed. 1500 files, took 404 ms",
    "uploaded; 0 errors",
])
def test_a_word_elsewhere_in_the_output_does_not_contradict_a_deploy(out):
    assert verdicts(bash("gh release create v1 a.whl", out), say("已上线。")) == ["backed"]


@pytest.mark.parametrize("out", [
    "error: could not publish", "HTTP 422: Validation Failed", "deploy failed", "Error: unauthorized", "Permission denied",
    "fatal: repository not found", "failed to upload release asset",
])
def test_a_real_failed_deploy_is_still_contradicted(out):
    assert verdicts(bash("gh release create v1 a.whl", out), say("已上线。")) == ["contradicted"]
