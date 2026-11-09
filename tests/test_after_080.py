"""What real use of 0.8.0 turned up: a step for the reader held as a claim, a message sent mid-turn missing from what a catch quotes, and a home folder under /tmp read as scratch."""

import json

import pytest

from honestly import hooks, rules
from honestly.audit import audit_turn
from honestly.claims import find_claims
from honestly.claude_code import Event, Turn, _parse

BLOCKING = {"unbacked", "contradicted"}


def _categories(sentence):
    return [c.category for c in find_claims(sentence)]


# ------------------------------------------------------------------ a step for the reader that names a screen
@pytest.mark.parametrize("sentence", [
    "在左侧边栏打开定时任务（Scheduled），点开“【工作日 12:30】追问 + 投递，每天总量 100 条（先深圳）”。",   # the sentence 0.8.0 held in a real session
    "在左侧边栏打开定时任务（Scheduled）。",
    "打开定时任务（Scheduled）",
    "在左侧边栏打开 Scheduled。",
    "在 Settings 里打开 Scheduled。",
    "点开左侧的（Scheduled）页面。",
    "先打开定时任务（Scheduled）。",
    "然后在左侧边栏打开定时任务（Scheduled）。",
    "1. 打开定时任务（Scheduled）",
    "- 在左侧边栏打开 Scheduled。",
    "Click Scheduled in the sidebar.",
    "Open Scheduled in the sidebar.",
    "Please click Scheduled in the sidebar.",
    "Now tap Scheduled in the sidebar.",
])
def test_a_step_for_the_reader_is_no_claim(sentence):
    assert _categories(sentence) == []


@pytest.mark.parametrize("sentence, category", [
    ("定时任务已经建好了，每天 12:30 跑。", "scheduled"),
    ("我已经把定时任务设好了。", "scheduled"),
    ("Scheduled。", "scheduled"),
    ("已经 scheduled 了。", "scheduled"),
    ("The job is scheduled.", "scheduled"),
    ("定时任务 scheduled。", "scheduled"),
    ("任务已 scheduled。", "scheduled"),
    ("定时任务（Scheduled）已建好。", "scheduled"),
    ("每日备份任务（scheduled）。", "scheduled"),
    ("日报 Scheduled。", "scheduled"),
    ("已在左侧边栏把任务 Scheduled。", "scheduled"),
    # the wording of a step, with what says it was done
    ("我在左侧边栏打开定时任务（Scheduled）并设好了。", "scheduled"),
    ("打开页面确认已部署。", "deployed"),
    ("在左侧打开已部署（Deployed）。", "deployed"),
    ("打开页面（deployed）。", "deployed"),
    ("打开定时任务（Scheduled）并设好了。", "scheduled"),
    # a verb that is also a noun, right before the result word
    ("Deploy succeeded.", "deployed"),
    ("Test passed.", "tests_pass"),
])
def test_a_claim_with_the_same_words_is_still_a_claim(sentence, category):
    assert category in _categories(sentence)


@pytest.mark.parametrize("sentence", ["打开 CI 全部 passed。", "进入目录 pytest passed。", "打开页面全部 passed。"])
def test_a_result_after_a_step_word_is_still_a_claim(sentence):
    assert _categories(sentence) != []


# ------------------------------------------------------------------ a message sent while the assistant was working
def _row(kind, **more):
    return json.dumps({"type": kind, "isSidechain": False, "sessionId": "s", "timestamp": "2026-11-09T04:00:00Z", **more}, ensure_ascii=False)


def _user(text):
    return _row("user", promptSource="typed", message={"role": "user", "content": text})


def _says(text):
    return _row("assistant", message={"role": "assistant", "model": "m", "content": [{"type": "text", "text": text}]})


def _queued(prompt, kind="human", mode="prompt", **more):
    return _row("attachment", attachment={"type": "queued_command", "prompt": prompt, "commandMode": mode, "origin": {"kind": kind}, **more})


def _turns(tmp_path, *rows):
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return _parse(str(path))


def test_a_message_sent_mid_turn_is_what_a_catch_quotes(tmp_path):
    turns = _turns(tmp_path, _user("补齐 UIPilot"), _says("在做"), _queued("现在所有项目你帮我优化", humanTurn=True), _says("好了"))
    assert hooks._who_where({}, turns[-1], True).endswith("回复「现在所有项目你帮我优化」这个问题时")
    assert turns[-1].asked == "现在所有项目你帮我优化"


def test_the_last_of_several_messages_sent_mid_turn_is_quoted(tmp_path):
    turns = _turns(tmp_path, _user("第一句"), _queued("第二句", humanTurn=True), _queued("第三句", humanTurn=True), _says("好了"))
    assert turns[-1].asked == "第三句"


def test_a_message_sent_mid_turn_starts_no_turn_and_keeps_the_prompt(tmp_path):
    """The prompt and the turn's edges decide verdicts: what a person added while the work ran changes neither."""
    turns = _turns(tmp_path, _user("补齐 UIPilot"), _says("在做"), _queued("现在所有项目你帮我优化", humanTurn=True), _says("好了"))
    assert len(turns) == 1
    assert turns[0].prompt == "补齐 UIPilot"
    assert [e.kind for e in turns[0].events] == ["text", "text"]


@pytest.mark.parametrize("kind, mode, text", [
    ("task-notification", "task-notification", "<task-notification>done</task-notification>"),
    ("peer", "prompt", '<agent-message from="a">report</agent-message>'),
    (None, "prompt", "<system-reminder>Linked sessions now</system-reminder>"),
])
def test_what_no_person_sent_is_not_quoted(tmp_path, kind, mode, text):
    turns = _turns(tmp_path, _user("补齐 UIPilot"), _queued(text, kind=kind, mode=mode), _says("好了"))
    assert turns[-1].asked == "补齐 UIPilot"


def test_a_message_sent_mid_turn_with_an_image_is_quoted_by_its_text(tmp_path):
    parts = [{"type": "text", "text": "看这张图"}, {"type": "image", "source": {"data": "x"}}]
    turns = _turns(tmp_path, _user("第一句"), _queued(parts, humanTurn=True), _says("好了"))
    assert turns[-1].asked == "看这张图"


def test_a_turn_with_no_message_mid_way_quotes_its_prompt():
    assert Turn(session="s", index=0, version="", prompt="第一句").asked == "第一句"


def test_the_catch_log_records_the_message_sent_mid_turn(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    turns = _turns(tmp_path, _user("补齐 UIPilot"), _queued("现在所有项目你帮我优化", humanTurn=True), _says("好了"))
    rows = []
    monkeypatch.setattr(hooks.store, "append_line", lambda path, line: rows.append(line))
    hooks._record("stop", {}, turns[-1], "held", claim="好了")
    assert "现在所有项目你帮我优化" in rows[-1]
    assert "补齐 UIPilot" not in rows[-1]


# ------------------------------------------------------------------ a home folder under a temp directory
def _home(monkeypatch, path):
    monkeypatch.setenv("HOME", path)
    monkeypatch.setenv("USERPROFILE", path)


SHELL_EDITS_IN_HOME = [
    "cd /tmp && cd ~/proj && echo x > src/app.py",
    "cd ~/proj && echo x > src/app.py",
    "echo x > ~/proj/src/app.py",
    "cp new.py ~/proj/src/app.py",
    "python3 - <<'EOF'\nimport os\nopen(os.path.expanduser('~/proj/src/app.py'), 'w').write('x')\nEOF",
    "python3 - <<'EOF'\nopen('~/proj/src/app.py', 'w').write('x')\nEOF",
]


@pytest.mark.parametrize("home", ["/tmp/home", "/tmp", "/private/tmp/home", "/var/tmp/agent"])
@pytest.mark.parametrize("cmd", SHELL_EDITS_IN_HOME)
def test_a_shell_edit_in_the_home_folder_counts_wherever_home_is(monkeypatch, home, cmd):
    _home(monkeypatch, home)
    assert rules.bash_is_edit(cmd)


@pytest.mark.parametrize("cmd", SHELL_EDITS_IN_HOME)
def test_the_same_edits_count_with_an_ordinary_home(monkeypatch, cmd):
    _home(monkeypatch, "/home/me")
    assert rules.bash_is_edit(cmd)


@pytest.mark.parametrize("home", ["/tmp/home", "/tmp", "/home/me"])
@pytest.mark.parametrize("cmd", ["echo x > /tmp/probe.py", "cd /tmp/x && echo y > a.py", "echo x > ~/scratchpad/a.py", "echo x > ~/proj/docs/notes.md"])
def test_scratch_and_notes_stay_what_they_are(monkeypatch, home, cmd):
    _home(monkeypatch, home)
    assert not rules.bash_is_edit(cmd)


def _audit(*events, project="/w/other"):
    return audit_turn(Turn(session="s", index=1, version="", prompt="fix it", events=list(events), project=project))


def _tool(name, text, result=""):
    return Event("tool", name=name, text=text, result=result)


CLAIM = Event("text", text="All tests pass.")


@pytest.mark.parametrize("project", ["/w/other", "/tmp/home/proj", "/tmp/home"])
@pytest.mark.parametrize("edit", [
    ("Edit", "/tmp/home/proj/src/app.py"),
    ("Write", "/private/tmp/home/proj/src/app.py"),
    ("Bash", "echo x > /tmp/home/proj/src/app.py"),
    ("Bash", "cd /tmp/home/proj && echo x > src/app.py"),
    ("Bash", "cd ~/proj && echo x > src/app.py"),
])
def test_a_false_test_claim_after_an_edit_in_the_home_folder_is_held(monkeypatch, project, edit):
    _home(monkeypatch, "/tmp/home")
    flags = _audit(_tool(*edit), CLAIM, project=project)
    assert [f.verdict for f in flags if f.category == "tests_pass"] == ["unbacked"]


@pytest.mark.parametrize("edit", ["cd ~/proj && echo x > src/app.py", "echo x > ~/proj/src/app.py", "echo x > /tmp/home/proj/src/app.py"])
def test_a_run_from_before_an_edit_in_the_home_folder_backs_nothing(monkeypatch, edit):
    """The lie 0.8.0 let through: tests, then an edit it read as scratch, then "All tests pass" on the strength of the old run."""
    _home(monkeypatch, "/tmp/home")
    flags = _audit(_tool("Bash", "pytest -q", "3 passed in 0.1s"), _tool("Bash", edit), CLAIM)
    assert [f.verdict for f in flags if f.category == "tests_pass"] == ["unbacked"]


@pytest.mark.parametrize("run", ["cd ~/proj && pytest -q", "cd /tmp/home/proj && pytest -q", "pytest -q"])
def test_a_real_run_after_that_edit_backs_the_claim(monkeypatch, run):
    _home(monkeypatch, "/tmp/home")
    flags = _audit(_tool("Bash", "cd ~/proj && echo x > src/app.py"), _tool("Bash", run, "3 passed in 0.1s"), CLAIM, project="/tmp/home/proj")
    assert not [f for f in flags if f.verdict in BLOCKING]


def test_an_edit_in_a_temp_folder_outside_home_stays_scratch(monkeypatch):
    _home(monkeypatch, "/tmp/home")
    flags = _audit(_tool("Edit", "/tmp/probe/app.py"), CLAIM)
    assert not [f for f in flags if f.verdict in BLOCKING]
