"""What real use of 0.8.1 turned up: documents written through a joined path, archives and Office files, a hold message
naming the wrong thing as still running, and a test summary printed after an echo label."""

import pytest

from honestly import hooks, rules
from honestly.audit import audit_turn, judge_output
from honestly.claude_code import Event, Turn


def _turn(*events, project="/w/proj"):
    return Turn(session="s", index=1, version="", prompt="do it", events=list(events), project=project)


def _bash(text, result="", running=False, task=""):
    return Event("tool", name="Bash", text=text, result=result, running=running, task=task)


def _say(text):
    return Event("text", text=text)


def _verdicts(turn, category):
    return [(f.verdict, f.reason) for f in audit_turn(turn) if f.category == category]


# ------------------------------------------------------------------ a path joined with `/`
DOC_WRITES = [
    "python3 - <<'EOF'\nimport pathlib\nR=pathlib.Path('.')\nlog=R/'docs/log.md'\nlog.write_text('a')\nEOF",
    "python3 - <<'EOF'\nfrom pathlib import Path\nR = Path('.')\nlog = R / 'docs' / 'log.md'\nlog.write_text('a')\nEOF",
    "python3 - <<'EOF'\nimport json, pathlib\nR=pathlib.Path('.')\np=R/'.agent/state.json'; s=json.load(open(p))\njson.dump(s,open(p,'w'))\nEOF",
    "python3 - <<'EOF'\nimport pathlib\na=pathlib.Path('.')/'AGENTS.md'; a.write_text('x')\nEOF",
    "python3 - <<'EOF'\nimport pathlib\nm=pathlib.Path.home()/'.claude/projects/p/memory/notes.md'\nm.write_text('x')\nEOF",
]


@pytest.mark.parametrize("cmd", DOC_WRITES)
def test_a_document_written_through_a_joined_path_is_no_code_edit(cmd):
    assert not rules.bash_is_edit(cmd)


@pytest.mark.parametrize("cmd", [
    "python3 - <<'EOF'\nimport pathlib\nR=pathlib.Path('.')\nf=R/'src/app.py'\nf.write_text('x')\nEOF",
    "python3 - <<'EOF'\nfrom pathlib import Path\nR = Path('.')\nf = R / 'src' / 'app.py'\nf.write_text('x')\nEOF",
    "python3 - <<'EOF'\nimport pathlib\nR=pathlib.Path('.')\nlog=R/'docs/log.md'\nlog.write_text('a')\n(R/'src/app.py').write_text('x')\nEOF",
])
def test_code_written_through_a_joined_path_is_still_an_edit(cmd):
    assert rules.bash_is_edit(cmd)


def test_a_push_followed_by_notes_written_through_a_joined_path_is_backed():
    """The real turn: the kernel was pushed, then the experiment log was updated, then the reply said it was pushed."""
    t = _turn(
        _bash("cd proj && python3 - <<'EOF'\nopen('notebooks/f/e066.ipynb','w').write('{}')\nEOF\nkaggle kernels push -p notebooks/f",
              "Kernel version 1 successfully pushed.  Please check progress at https://www.kaggle.com/code/me/x"),
        _bash("cd proj && python3 - <<'EOF'\nimport pathlib\nR=pathlib.Path('.')\nlog=R/'docs/log.md'\nlog.write_text(log.read_text()+'x')\nEOF", "ok"),
        _say("关掉 H22 的消融版（E066-f）已推送。"),
    )
    assert [v for v, _ in _verdicts(t, "pushed")] == ["backed"]


# ------------------------------------------------------------------ archives and Office files
@pytest.mark.parametrize("cmd", [
    "python3 -c \"import zipfile\nz=zipfile.ZipFile('/Users/me/Downloads/review.zip','w',zipfile.ZIP_DEFLATED)\nz.write('a.docx')\nz.close()\"",
    "python3 - <<'EOF'\nimport tarfile\nwith tarfile.open('out/site.tar.gz', 'w:gz') as t:\n    t.add('site')\nEOF",
    "python3 - <<'EOF'\nimport shutil\nshutil.make_archive('out/site', 'zip', 'site')\nEOF",
])
def test_writing_an_archive_is_no_code_edit(cmd):
    assert not rules.bash_is_edit(cmd)


@pytest.mark.parametrize("path", ["report.docx", "out/model.xlsx", "deck.pptx", "/Users/me/Downloads/a.zip", "dist/site.tar.gz", "backup.tgz"])
def test_archives_and_office_files_are_not_code(path):
    assert rules.path_is_doc(path)


def test_a_python_write_to_source_next_to_an_archive_is_still_an_edit():
    cmd = "python3 - <<'EOF'\nimport zipfile\nzipfile.ZipFile('out/a.zip','w').write('a.txt')\nopen('src/app.py','w').write('x')\nEOF"
    assert rules.bash_is_edit(cmd)


# ------------------------------------------------------------------ what was still running
EDIT = Event("tool", name="Edit", text="/w/proj/src/app.py")


def test_a_background_command_that_is_not_a_check_is_not_reported_as_one_still_running():
    t = _turn(EDIT, _bash("python replay.py > out.log 2>&1", running=True, task="b1"), _say("All tests pass."))
    (verdict, reason), = _verdicts(t, "tests_pass")
    assert verdict == "unbacked"
    assert "still running" not in reason and "background command" in reason
    f = [x for x in audit_turn(t) if x.category == "tests_pass"][0]
    zh, en = hooks._plain_stop(f, True), hooks._plain_stop(f, False)
    assert "还在运行" not in zh and "没有运行测试命令" in zh
    assert "still running" not in en


def test_a_check_still_running_is_still_reported_as_running():
    t = _turn(EDIT, _bash("pytest -q", running=True, task="b2"), _say("All tests pass."))
    (verdict, reason), = _verdicts(t, "tests_pass")
    assert verdict == "unbacked" and "still running" in reason
    f = [x for x in audit_turn(t) if x.category == "tests_pass"][0]
    assert "还在运行" in hooks._plain_stop(f, True)


def test_a_subagent_still_running_is_named_as_a_subagent():
    t = _turn(EDIT, Event("tool", name="Agent", text="run the suite", running=True, task="a1"), _say("All tests pass."))
    (verdict, reason), = _verdicts(t, "tests_pass")
    assert verdict == "unbacked" and "subagent" in reason
    f = [x for x in audit_turn(t) if x.category == "tests_pass"][0]
    assert "子代理" in hooks._plain_stop(f, True)


# ------------------------------------------------------------------ a test summary printed after an echo label
def _judge(cmd, out, claim="194 tests pass"):
    return judge_output("tests_pass", cmd, Event("tool", name="Bash", text=cmd, result=out), claim)[0]


@pytest.mark.parametrize("cmd", [
    'echo "full suite: $(uv run --with pytest pytest -q 2>&1 | tail -1 | cut -c1-80)"',
    "echo \"pytest: $(.venv/bin/python -m pytest -q -p no:cacheprovider 2>&1 | tail -1)\"",
])
def test_a_summary_after_an_echo_label_is_read(cmd):
    label = cmd.split(":")[0].split('"')[1]
    assert _judge(cmd, f"{label}: 194 passed, 2 warnings in 9.28s") == "backed"
    assert _judge(cmd, f"{label}: 1 failed, 193 passed in 9.28s") == "contradicted"


def test_a_failure_behind_a_printf_label_is_read_as_a_failure():
    """0.8.1 read `pytest: 1 failed, 193 passed` from a printf as a pass: the failure count was no longer at the start of its line."""
    cmd = 'printf "pytest: %s\\n" "$(pytest -q 2>&1 | tail -1)"'
    assert _judge(cmd, "pytest: 1 failed, 193 passed in 9.28s") == "contradicted"
    assert _judge(cmd, "pytest: 194 passed in 9.28s") == "backed"
    assert _judge(cmd, "pytest: 6 errors in 4.59s") in ("contradicted", "unbacked")


@pytest.mark.parametrize("cmd, out", [
    ('echo "full suite: 194 passed"', "full suite: 194 passed"),
    ('echo "full suite: $(echo 194 passed)"', "full suite: 194 passed"),
    ('pytest -q > /dev/null; echo "full suite: 194 passed"', "full suite: 194 passed"),
])
def test_a_summary_the_command_wrote_itself_is_still_not_a_run(cmd, out):
    assert _judge(cmd, out) != "backed"
