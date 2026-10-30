"""Regression tests for the bugs an independent review found before launch (0.2.2)."""
import io, json, os, sys, tempfile
from honestly import rules as R, claude_code, codex, hooks
from honestly.audit import audit_turns, Finding
from honestly.report import text_report, stats


# ---------------------------------------------------------------- claim patterns on everyday prose
def _cats(sent):
    return [h.category for h in R.find_claims(sent)]


def test_pushed_committed_everyday_english_is_not_a_claim():
    for s in ["I pushed back on that design.", "The deadline was pushed back a week.", "The user pushed the button twice.",
              "The element gets pushed down by the margin.", "The data is pushed through the pipeline.",
              "The team is committed to the plan.", "This is committed to memory.", "The row is committed to the database in a transaction.",
              "This file hasn't been committed yet.", "Nothing was committed."]:
        assert not _cats(s), s


def test_pushed_committed_git_claims_still_count():
    assert _cats("Pushed to origin/main.") == ["pushed"]
    assert _cats("Pushed.") == ["pushed"]
    assert _cats("Committed the fix and pushed it.")[0] in ("committed", "pushed")
    assert _cats("Committed on main.") == ["committed"]
    assert _cats("已推送到远端。") == ["pushed"]
    assert _cats("Both notebooks are pushed (v3 and v1).") == ["pushed"]
    assert not _cats("Nothing is committed to git yet; tell me if you want a commit.")


def test_honest_partial_results_are_not_a_pass_claim():
    for s in ["Ran the suite: 12 passed, 1 failed (the fix is partial).", "3 tests passed and 2 failed.",
              "5 个测试通过，2 个失败。", "编译通过但运行报错。"]:
        assert not _cats(s), s


def test_fixed_somewhere_else_or_by_someone_else_is_not_a_claim():
    for s in ["The bug is fixed in version 2.0 upstream.", "The issue is fixed in Python 3.12.", "This was fixed upstream in v1.2.",
              "According to the docs, the error is fixed by setting the env var.", "上游已修复此问题。", "按照文档，这个问题已修复。",
              "之前已修复过类似问题。", "Set position: fixed; in CSS.", "Rename fixed.py to patched.py.", "The value is fixed at 3."]:
        assert not _cats(s), s


def test_pass_rate_and_other_time_or_place_are_not_claims():
    for s in ["用例通过率 80%。", "测试通过率下降了。", "All tests passed in the previous run, so no need to re-run.",
              "The build succeeded yesterday.", "Make sure all tests pass before merging.", "Ensure the build passes.",
              "Rendering is done on the client."]:
        assert not _cats(s), s


def test_markdown_structure_is_not_a_claim():
    assert not R.find_claims("### Fixed\n| committed | yes |\n## Tests pass")
    assert _cats("- Fixed the off-by-one.") == ["fixed"]          # list marker stripped, claim kept


def test_apostrophes_are_not_quotes():
    for s in ["I've fixed the user's issue.", "I've fixed the parser's handling of nested lists.", "I've pushed the branch to the team's remote.",
              "Now that's fixed, let's move on.", "I’ve fixed both; let’s ship it."]:
        assert _cats(s), s
    assert not R.find_claims('The bot replied "all tests pass" again.')      # real quotes still excluded
    assert not R.find_claims("The reviewer wrote 'tests pass' in the thread.")


def test_forward_looking_words_only_disqualify_before_the_claim():
    assert _cats("All 12 tests pass, even if the config file is missing.") == ["tests_pass"]
    assert _cats("Pushed to main; let me know if you want a tag.") == ["pushed"]
    assert _cats("测试全部通过，如果你需要我可以再加几个用例。")
    assert not _cats("If the tests pass, I'll push.")
    assert not _cats("如果测试通过就提交。")
    assert not _cats("I will push once the tests pass.")


# ---------------------------------------------------------------- Windows paths
def test_windows_paths_doc_and_temp_detection():
    for p in [r"C:\Users\a\.claude\settings.json", r"C:\Users\a\proj\docs\guide.html", r"C:\Users\a\proj\notes\plan.md",
              r"C:\Users\a\AppData\Local\Temp\claude-1\scratchpad\t.py", r"C:\Users\a\proj\scratchpad\x.py"]:
        assert R.path_is_doc(p), p
    assert not R.path_is_doc(r"C:\Users\a\proj\src\app.py")
    assert not R.path_is_doc(r"C:\Users\a\proj\notes\plan.py")   # code under a notes/ folder is still code
    assert not R.bash_is_edit(r"cat > C:\Users\a\AppData\Local\Temp\t.py <<'EOF'" + "\nx=1\nEOF")
    assert R.bash_is_edit(r"cat > C:\Users\a\proj\src\t.py <<'EOF'" + "\nx=1\nEOF")


def test_report_project_name_from_windows_path():
    f = Finding(session="s", turn=1, version="", agent="claude-code", model="", ts="", category="fixed", verdict="backed", reason="",
                claim="", last_edit="", tools_after_edit=[], context="", verified_by="", output="", project=r"C:\Users\alice\Documents\my-proj")
    assert "my-proj" in stats([f])["by_project"]


def test_guard_entry_uses_windows_exe_path(monkeypatch):
    monkeypatch.setattr(sys, "argv", [r"C:\Users\a\venv\Scripts\honestly.exe"])
    cmd = hooks._entries()["Stop"]["hooks"][0]["command"]
    assert cmd.startswith("C:/Users/a/venv/Scripts/honestly.exe hook stop")   # forward slashes: the line is run by Git Bash, which eats backslashes
    monkeypatch.setattr(sys, "argv", [r"C:\Program Files\x\honestly.exe"])
    assert hooks._entries()["Stop"]["hooks"][0]["command"].startswith('"C:/Program Files/x/honestly.exe" hook stop')


# ---------------------------------------------------------------- hooks
def test_pre_hook_lets_read_only_pipelines_through():
    for cmd in ["cat build.log | tail -50", "grep -n pytest setup.cfg | head", "pip list | grep -i pytest | head", "find . -name '*_test.py' | head"]:
        assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": cmd}}) is None, cmd
    assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "pytest -q | tail -3"}}) is not None


def test_stdin_reader_tolerates_non_dict(monkeypatch, tmp_path):
    monkeypatch.setattr(hooks, "errors_path", lambda: str(tmp_path / "e.log"))
    monkeypatch.setattr(sys, "stdin", io.StringIO("[1, 2]"))
    assert hooks._read_stdin() == {}


# ---------------------------------------------------------------- parsers never crash on odd records
def _cc(lines):
    d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "p")); p = os.path.join(d, "p", "s.jsonl")
    with open(p, "w", encoding="utf-8") as fh:
        for l in lines:
            fh.write((l if isinstance(l, str) else json.dumps(l, ensure_ascii=False)) + "\n")
    return p


def test_claude_code_parser_survives_odd_records():
    lines = ["[]", "null", "123", "not json", "\ufeff{}",
             {"type": "user", "message": "hi", "timestamp": 1730000000},
             {"type": "user", "origin": "human", "message": {"content": "hello"}, "timestamp": None},
             {"type": "assistant", "message": {"content": [{"type": "text", "text": None}, "str", {"type": "tool_use", "name": None, "input": None, "id": None}]}},
             {"type": "assistant", "message": {"model": 5, "content": [{"type": "text", "text": "Fixed the bug."}]}}]
    turns = claude_code.parse_session(_cc(lines))
    fs = audit_turns(turns)
    assert all(isinstance(f.ts, str) for f in fs)
    assert all(not (f.verdict == "unbacked") for f in fs)      # an Edit with no path is not a code edit


def test_codex_cli_shell_command_and_exit_code():
    d = tempfile.mkdtemp(); p = os.path.join(d, "rollout-2026-10-28T00-00-00-x.jsonl")
    rows = ["[]", {"type": "turn_context", "payload": {"collaboration_mode": "plan", "state": {"collaboration_mode": "x"}, "cwd": None}},
            {"type": "event_msg", "payload": {"type": "item_completed", "item": "str"}},
            {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage", "content": [{"text": None}]}}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "apply_patch", "call_id": "c0", "arguments": "*** Begin Patch\n*** Update File: src/app.py\n+x\n*** End Patch"}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "shell_command", "call_id": "c1", "arguments": json.dumps({"command": "pytest -q"})}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": "1 failed, 4 passed\nProcess exited with code 1"}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "shell", "call_id": "c2", "arguments": "[1,2]"}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "shell", "call_id": "c3", "arguments": json.dumps({"command": ["bash", None, "-lc", "npm run build"]})}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c3", "output": json.dumps({"output": "", "metadata": {"exit_code": 1}})}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": None}, {"type": "output_text", "text": "Build passed. All tests pass."}]}}]
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write((r if isinstance(r, str) else json.dumps(r)) + "\n")
    turns = codex.parse_session(p)
    tools = [e for t in turns for e in t.events if e.kind == "tool"]
    assert any(e.name == "Bash" and e.text == "pytest -q" and e.is_error for e in tools)
    assert any(e.text == "bash -lc npm run build" and e.is_error for e in tools)
    fs = audit_turns(turns)
    assert fs and all(f.verdict != "backed" for f in fs)


def test_report_all_unverifiable_is_not_called_no_claims():
    f = Finding(session="s", turn=1, version="", agent="claude-code", model="", ts="", category="tests_pass", verdict="unverifiable", reason="x",
                claim="", last_edit="", tools_after_edit=[], context="", verified_by="", output="", project="")
    out = text_report([f] * 5, 3, 0)
    assert "none could be decided" in out and "no checkable" not in out.lower()


def test_pre_hook_ignores_commands_quoted_in_a_commit_message():
    cmd = 'git commit -m "guard: pip list | grep pytest | head is read-only; 52 tests pass" && git push'
    assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": cmd}}) is None


def test_explaining_a_message_is_not_a_claim():
    assert not R.find_claims("意思是：你说修好了、测试全过，但改完 login.py 之后一条测试命令都没跑。")
    assert not R.find_claims("That means it said the bug was fixed and all tests passed without running anything.")
    assert not R.find_claims("The reviewer said the tests pass on their machine.")


def test_script_writing_only_tempfile_paths_is_not_an_edit():
    cmd = "python3 - <<'EOF'\nimport tempfile, os\nd = tempfile.mkdtemp(); p = os.path.join(d, 's.jsonl')\nopen(p, 'w').write('x')\nEOF"
    assert not R.bash_is_edit(cmd)


def test_hook_blocks_carry_a_plain_language_message_for_the_user():
    d = tempfile.mkdtemp(); p = os.path.join(d, "s.jsonl")
    rows = [{"type": "user", "uuid": "u1", "timestamp": "2026-10-28T10:00:00Z", "message": {"role": "user", "content": "fix it"}},
            {"type": "assistant", "uuid": "a1", "timestamp": "2026-10-28T10:00:05Z", "message": {"role": "assistant", "model": "m",
             "content": [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/x/src/auth/login.py"}}]}},
            {"type": "assistant", "uuid": "a2", "timestamp": "2026-10-28T10:00:09Z", "message": {"role": "assistant", "model": "m",
             "content": [{"type": "text", "text": "登录接口的 bug 已修复，12 个测试全部通过。"}]}}]
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    out = hooks.stop_hook({"transcript_path": p, "cwd": "/Users/me/Documents/shop-api", "last_assistant_message": "登录接口的 bug 已修复，12 个测试全部通过。", "stop_hook_active": False})
    assert out["decision"] == "block"
    assert out["systemMessage"].startswith("⚠️ honestly 拦了一下：Claude Code（m）在「shop-api」项目回复「fix it」这个问题时说「登录接口的 bug 已修复") and "login.py" in out["systemMessage"]
    assert out["reason"].startswith("⚠️ honestly 拦了一下") and "给助手" in out["reason"]   # user line first, then one line for the agent
    pre = hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "pytest -q | tail -3"}, "transcript_path": p, "cwd": "/Users/me/Documents/shop-api"})
    assert pre["systemMessage"].startswith('⚠️ honestly stepped in: Claude Code (m) in project shop-api, answering "fix it" piped pytest through tail')


def test_catches_are_recorded_and_summarised(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "catches_path", lambda: str(tmp_path / "catches.jsonl"))
    assert "no catches" in hooks.catches_report(7)
    pre = hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "pytest -q | tail -3"}, "cwd": "/Users/me/shop-api"})
    assert pre is not None
    rows = hooks.load_catches(7)
    assert len(rows) == 1 and rows[0]["kind"] == "pre" and rows[0]["project"] == "/Users/me/shop-api"
    rep = hooks.catches_report(7)
    assert "1 catch in the last 7 days" in rep and "shop-api" in rep and "One line to share" in rep


def test_guard_replaces_legacy_sober_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "settings_path", lambda: str(tmp_path / "settings.json"))
    (tmp_path / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "/old/sober hook stop  # sober hook"}]}]}}))
    assert "installed for Stop" in hooks.guard("status")
    hooks.guard("install")
    cfg = json.loads((tmp_path / "settings.json").read_text())
    cmds = [h["command"] for g in cfg["hooks"]["Stop"] for h in g["hooks"]]
    assert len(cmds) == 1 and "honestly hook" in cmds[0] and "sober hook" not in cmds[0]


def test_guard_entry_path_is_absolute(monkeypatch):
    monkeypatch.setattr(sys, "argv", [".venv/bin/honestly"])
    cmd = hooks._entries()["Stop"]["hooks"][0]["command"]
    assert os.path.isabs(cmd.split(" hook stop")[0])


def test_notify_switch_is_a_marker_file(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "notify_flag_path", lambda: str(tmp_path / "notify"))
    assert "on" in hooks.set_notify(True) and (tmp_path / "notify").exists()
    assert "off" in hooks.set_notify(False) and not (tmp_path / "notify").exists()
