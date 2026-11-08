"""Windows: Claude Code's PowerShell tool, and the cmdlets agents pipe a run into. Each cmdlet is judged like the POSIX tool it stands for."""
import json, os, tempfile

import pytest

from honestly import audit, hooks, rules
from honestly.audit import Event


def pre(cmd, tool="Bash"):
    return hooks.pre_hook({"tool_name": tool, "tool_input": {"command": cmd}})


@pytest.mark.parametrize("cmd", [
    "pytest | Select-Object -First 5",
    "npm test 2>&1 | select -first 5",
    "pytest | Select-Object -f 5",                 # a parameter may be cut short
    "dotnet test | Select-Object -SkipLast 3",     # drops the end, where the result is
    "pytest | Select-Object -Index 0,1",
    "npm test --workspaces | Select-Object -Last 5",   # like `| tail`: an early failure in a multi-package run scrolls away
    "pytest | Select-String passed -Quiet",        # prints True or False
    "pytest | Measure-Object -Line",               # a count
    "pytest | Out-Null",
])
def test_a_cmdlet_that_hides_the_result_is_refused(cmd):
    assert pre(cmd) is not None, cmd


@pytest.mark.parametrize("cmd", [
    "pytest | Select-Object -Last 5",                 # like `| tail`: the summary is the last line
    "npm test | Select-String FAIL",                  # like `grep FAIL`: the failures are what is left
    "pytest | Select-String -Pattern 'passed','failed'",
    "pytest | Select-String 'passed|failed'",
    "pytest | Select-String -SimpleMatch FAILED",
    "pytest | findstr /C:\"FAILED\"",
    "pytest | Tee-Object log.txt",
    "pytest | Select-Object -Property Line",
    "Get-ChildItem | Select-Object -First 5",         # runs no test
    "Get-Content pytest.ini | Select-Object -First 5",
    "gc pytest.ini | select -first 5",
    "Select-String pytest log.txt | Select-Object -First 5",
    "Get-Process | Select-String pytest",
    "pytest | Select-Object -First 5; exit $LASTEXITCODE",   # like `${PIPESTATUS[0]}`: the real status is read
])
def test_a_cmdlet_that_leaves_the_result_is_allowed(cmd):
    assert pre(cmd) is None, cmd


def test_the_powershell_tool_goes_through_the_pre_hook():
    assert pre("pytest | Select-Object -First 5", tool="PowerShell") is not None
    assert pre("Get-ChildItem | Select-Object -First 5", tool="PowerShell") is None
    assert pre("pytest | head -5", tool="Read") is None


def test_the_hooks_match_the_powershell_tool():
    assert hooks._entries()["PreToolUse"]["matcher"] == "Bash|PowerShell"
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "hooks", "hooks.json"), encoding="utf-8") as fh:
        plugin = json.load(fh)
    assert plugin["hooks"]["PreToolUse"][0]["matcher"] == "Bash|PowerShell"


def test_the_refusal_suggests_the_powershell_way():
    msg = json.dumps(pre("pytest | Select-Object -First 5"), ensure_ascii=False)
    assert "Select-Object" in msg and "Select-Object -Last 40" in msg and "tail -n" not in msg
    assert "tail -n 40" in json.dumps(pre("pytest | head -5"), ensure_ascii=False)


def _transcript(*events):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "sess.jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": "fix it"}, "origin": {"kind": "human"}}) + "\n")
        for i, (name, inp, result) in enumerate(events):
            fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}]}}) + "\n")
            fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": result}]}}) + "\n")
    return p


def test_a_run_in_the_powershell_tool_backs_the_claim():
    p = _transcript(("Edit", {"file_path": "C:/p/src/app.py"}, "ok"), ("PowerShell", {"command": "pytest -q"}, "5 passed in 0.1s"))
    assert hooks.stop_hook({"transcript_path": p, "last_assistant_message": "All 5 tests pass.", "stop_hook_active": False}) is None


def test_a_failed_run_in_the_powershell_tool_holds_the_claim():
    p = _transcript(("Edit", {"file_path": "C:/p/src/app.py"}, "ok"), ("PowerShell", {"command": "pytest -q"}, "1 failed, 4 passed in 0.1s"))
    out = hooks.stop_hook({"transcript_path": p, "last_assistant_message": "All 5 tests pass.", "stop_hook_active": False})
    assert out and out["decision"] == "block"


@pytest.mark.parametrize("cmd", [
    'Set-Content src/app.py "x = 1"',
    'Set-Content -Path src/app.py -Value "x = 1"',
    'Add-Content src\\app.py "x = 1"',
    "(Get-Content src/app.py) -replace 'a','b' | Set-Content src/app.py",
    '"x = 1" | Out-File src/app.py',
])
def test_a_cmdlet_that_writes_code_is_an_edit(cmd):
    assert rules.bash_is_edit(cmd), cmd


@pytest.mark.parametrize("cmd", [
    'Set-Content notes.md "x"',
    "Set-Content -Path README.md -Value x",
    "pytest | Out-File log.txt",               # program output, like `pytest > log`
    "Get-Content src/app.py",
    "Set-Location src",
    "Get-Process | Out-File procs.txt",
])
def test_other_cmdlets_are_not_edits(cmd):
    assert not rules.bash_is_edit(cmd), cmd


def test_a_read_cmdlet_is_not_a_test_run():
    assert not rules.verifying_segments("Get-Content pytest.ini", {"test"})


def test_an_empty_filtered_run_could_not_be_checked():
    ev = Event("tool", name="Bash", text="pytest | Select-String foo", result="", is_error=False)
    assert audit.judge_output("tests_pass", "pytest | Select-String foo", ev)[0] == "unverifiable"


def test_pester_is_a_test_run():
    assert pre("Invoke-Pester | Select-Object -First 5") is not None
    assert rules.verifying_segments("Invoke-Pester ./tests", {"test"})


def _doctor_with(tmp_path, monkeypatch, matcher):
    from honestly import support
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    entries = hooks._entries()
    entries["PreToolUse"]["matcher"] = matcher
    (tmp_path / "settings.json").write_text(json.dumps({"hooks": {ev: [e] for ev, e in entries.items()}}), encoding="utf-8")
    return support.doctor(zh=False)


def test_doctor_names_an_install_that_misses_the_powershell_tool(tmp_path, monkeypatch):
    assert "PowerShell" in _doctor_with(tmp_path, monkeypatch, "Bash")
    assert "PowerShell" not in _doctor_with(tmp_path, monkeypatch, "Bash|PowerShell")


@pytest.mark.parametrize("cmd", [
    "npm test | Select-String foo",                # drops the summary
    "cargo test | sls -Pattern foo",
    "pytest | Select-String -NotMatch warning",    # like `grep -v warning`: drops "1 failed, 2 passed, 1 warning"
    "pytest | findstr foo",
    "pytest | findstr /V warning",
])
def test_a_filtering_cmdlet_is_read_like_grep(cmd):
    assert hooks.find_hidden_status(cmd) is None, cmd   # by default a filter looks for one thing
    assert hooks.find_hidden_status(cmd, strict=True) is not None, cmd
