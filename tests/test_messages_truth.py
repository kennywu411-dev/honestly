"""Each message must fit the situation and be followable: what it says happened happened, and what it asks for would help."""
import json
import os

import pytest

from honestly import cli, config, hooks


def session(tmp_path, events, reply, prompt="fix the login bug", cwd="/work/docpilot"):
    rows = [{"type": "user", "message": {"role": "user", "content": prompt}, "origin": {"kind": "human"}, "cwd": cwd, "timestamp": "2026-11-08T10:00:00.000Z"}]
    for i, e in enumerate(events):
        name, inp, res = e[0], e[1], e[2]
        err = e[3] if len(e) > 3 else False
        rows.append({"type": "assistant", "message": {"role": "assistant", "model": "m", "content": [{"type": "tool_use", "id": f"t{i}", "name": name, "input": inp if isinstance(inp, dict) else {"command": inp}}]}, "cwd": cwd, "timestamp": f"2026-11-08T10:00:{i + 1:02d}.000Z"})
        rows.append({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": res, "is_error": err}]}, "cwd": cwd, "timestamp": f"2026-11-08T10:00:{i + 1:02d}.500Z"})
    rows.append({"type": "assistant", "message": {"role": "assistant", "model": "m", "content": [{"type": "text", "text": reply}]}, "cwd": cwd, "timestamp": "2026-11-08T10:01:00.000Z"})
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return str(p)


def stop(tmp_path, events, reply, active=False, cwd="/work/docpilot", **kw):
    return hooks.stop_hook({"transcript_path": session(tmp_path, events, reply, cwd=cwd, **kw), "cwd": cwd, "last_assistant_message": reply, "stop_hook_active": active, "session_id": "x"})


def said(tmp_path, events, reply, **kw):
    return stop(tmp_path, events, reply, **kw)["systemMessage"]


EDIT = ("Edit", {"file_path": "/work/docpilot/login.py"}, "ok")
FAIL = ("Bash", "pytest -q", "2 failed, 10 passed in 1s", True)
LS = ("Bash", "ls", "a")


def pre_fix(cmd):
    o = hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": "/work/docpilot", "session_id": "x"})
    return o["systemMessage"], o["hookSpecificOutput"]["permissionDecisionReason"].split("\n")[1]


# ------------------------------------------------------------------ what it says happened
@pytest.mark.parametrize("run", [("Bash", "pytest -q | grep SKIP", ""), ("Bash", "pytest", "no tests ran in 0.1s")])
def test_it_does_not_say_no_runner_ran_when_one_did(tmp_path, run):
    assert "no test runner ran" not in said(tmp_path, [EDIT, run], "All tests pass.")


def test_a_filtered_run_is_named_as_filtered(tmp_path):
    m = said(tmp_path, [EDIT, ("Bash", "pytest -q | grep SKIP", "")], "All tests pass.")
    assert "result" in m and "pipe" in m
    z = said(tmp_path, [EDIT, ("Bash", "pytest -q | grep SKIP", "")], "测试全部通过。", prompt="修一下")
    assert "管道" in z and "没有运行测试命令" not in z


def test_an_empty_run_is_named_as_empty(tmp_path):
    assert "collected no tests" in said(tmp_path, [EDIT, ("Bash", "pytest", "no tests ran in 0.1s")], "All tests pass.")
    assert "没有收集到" in said(tmp_path, [EDIT, ("Bash", "pytest", "no tests ran in 0.1s")], "测试全部通过。", prompt="修一下")


def test_no_run_at_all_still_says_so(tmp_path):
    assert "no test runner ran after editing login.py" in said(tmp_path, [EDIT], "All tests pass.")


def test_a_second_pass_on_a_failed_run_says_it_failed(tmp_path):
    m = stop(tmp_path, [EDIT, FAIL], "All tests pass.", active=True)["systemMessage"]
    assert "nothing after the last edit" not in m and "failed" in m


def test_a_second_pass_about_an_email_does_not_mention_edits(tmp_path):
    m = stop(tmp_path, [LS], "I've emailed them.", active=True)["systemMessage"]
    assert "edit" not in m and "this turn" in m
    z = stop(tmp_path, [LS], "邮件已发送。", active=True, prompt="发邮件")["systemMessage"]
    assert "改动" not in z and "这一轮" in z


def test_a_second_pass_after_no_run_keeps_its_wording(tmp_path):
    assert "nothing after the last edit" in stop(tmp_path, [EDIT], "All tests pass.", active=True)["systemMessage"]


@pytest.mark.parametrize("reply,want", [("Committed.", "no commit was made after editing login.py. It has been asked to commit first."),
                                        ("Render complete.", "no render ran after editing login.py. It has been asked to render first."),
                                        ("Build succeeded.", "no build ran after editing login.py. It has been asked to run the build first.")])
def test_the_verb_fits_the_action(tmp_path, reply, want):
    assert want in said(tmp_path, [EDIT], reply)


def test_the_chinese_verb_fits_the_action(tmp_path):
    m = said(tmp_path, [EDIT], "打了 tag。", prompt="修")
    assert "没有提交" in m and "没有运行提交" not in m


def test_a_shell_variable_is_not_shown_as_the_file():
    assert "$" not in hooks._edited_name("Bash: sed -i 's/a/b/' $F")


def test_a_long_claim_is_cut_visibly(tmp_path):
    m = said(tmp_path, [EDIT], "Fixed the login bug and the logout bug and the session bug and the cookie bug.")
    assert "…\"" in m


@pytest.mark.parametrize("cwd,want,bad", [("/work/docpilot/src", "docpilot/src", "in project src,"), ("/work/docpilot/.claude", "project docpilot", ".claude")])
def test_the_project_is_named_well(tmp_path, cwd, want, bad):
    m = said(tmp_path, [EDIT], "All tests pass.", cwd=cwd)
    assert want in m and bad not in m


def test_the_home_folder_is_not_a_project(tmp_path):
    m = said(tmp_path, [EDIT], "All tests pass.", cwd=os.path.expanduser("~"))
    assert "in project" not in m


# ------------------------------------------------------------------ what it asks for must help
def test_a_refusal_about_tail_does_not_suggest_tail(tmp_path):
    _, fix = pre_fix("npm test --workspaces | tail")
    assert "tail -n" not in fix and "> " in fix


def test_a_refusal_about_select_last_does_not_suggest_it(tmp_path):
    _, fix = pre_fix("npm test --workspaces | Select-Object -Last 5")
    assert "Select-Object -Last 40" not in fix


def test_a_refusal_about_head_suggests_the_end(tmp_path):
    _, fix = pre_fix("pytest | head")
    assert "tail -n 40" in fix


def test_the_chinese_refusal_about_tail_does_not_suggest_tail(tmp_path, monkeypatch):
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    monkeypatch.setattr(hooks, "_SYSTEM_ZH", None)
    _, fix = pre_fix("npm test --workspaces | tail")
    assert "tail -n" not in fix


@pytest.mark.parametrize("cmd,tool,bad", [("npx jest --config make.config.js | head", "jest", "make's"), ("npx vitest run --dir tox-tests | head", "vitest", "tox's"),
                                          ("python -m unittest discover -s tsc_tests | head", "unittest", "tsc's"), ("python -m unittest | head", "unittest", "python -m"),
                                          ("pytest tests/ruff_rules | wc -l", "pytest", "ruff's")])
def test_a_refusal_names_the_tool_that_ran(cmd, tool, bad):
    m, _ = pre_fix(cmd)
    assert f"{tool}'s output" in m and bad not in m


@pytest.mark.parametrize("cmd,tool", [("npm run build | head", "npm run build"), ("cargo test | head", "cargo test"), ("./gradlew test | head", "gradlew test"), ("make test | wc -l", "make test"), ("uv run pytest | head", "pytest")])
def test_a_refusal_keeps_a_useful_name(cmd, tool):
    assert f"{tool}'s output" in pre_fix(cmd)[0]


def test_the_ask_fits_a_claim_about_code(tmp_path):
    ask = stop(tmp_path, [EDIT], "All tests pass.")["reason"].split("\n")[1]
    assert "changed, not yet verified" in ask and "send" not in ask


def test_the_chinese_ask_fits_a_claim_about_code(tmp_path):
    ask = stop(tmp_path, [EDIT], "测试全部通过。", prompt="修")["reason"].split("\n")[1]
    assert "已修改，尚未验证" in ask


def test_the_notify_message_says_what_notifies():
    m = hooks.set_notify(True)
    hooks.set_notify(False)
    assert "each catch" not in m and "at most one every 5 minutes" in m


def test_the_rule_text_does_not_advise_what_earns_a_hold():
    from honestly.support import RULE_TEXT, RULE_TEXT_ZH
    assert "pipefail" not in RULE_TEXT and "pipefail" not in RULE_TEXT_ZH
    assert "tail -n 40" in RULE_TEXT and "tail -n 40" in RULE_TEXT_ZH


def test_the_overview_only_offers_what_runs(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    cli.main([])
    out = capsys.readouterr().out
    assert "explain N, share" not in out and "two live self-tests" in out and "honestly explain N" in out


# ------------------------------------------------------------------ language: the conversation decides
LANGS = [("修一下登录接口的 bug", "All tests pass.", "en_US.UTF-8", True),   # a Chinese person with an English sentence in the reply
         ("fix the login bug", "Fixed 登录.py, all tests pass.", "en_US.UTF-8", False),   # a Chinese file name is not a Chinese conversation
         ("fix the login bug", "All tests pass.", "zh_CN.UTF-8", False),   # an English conversation on a Chinese system
         ("修一下", "All tests pass.", "zh_CN.UTF-8", True)]


@pytest.mark.parametrize("prompt,reply,lang,zh", LANGS)
def test_the_hold_follows_the_conversation(tmp_path, monkeypatch, prompt, reply, lang, zh):
    monkeypatch.setenv("LANG", lang)
    monkeypatch.setattr(hooks, "_SYSTEM_ZH", None)
    assert ("已拦截" in said(tmp_path, [EDIT], reply, prompt=prompt)) is zh


def test_a_reply_alone_decides_when_the_prompt_says_nothing(tmp_path):
    assert "已拦截" in said(tmp_path, [EDIT], "测试全部通过。", prompt="ok")


def test_a_comment_in_a_command_does_not_change_the_language(tmp_path):
    p = session(tmp_path, [EDIT], "x")
    o = hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": "pytest | head # 跑测试"}, "cwd": "/w", "transcript_path": p, "session_id": "s"})
    assert "blocked this command" in o["systemMessage"]


@pytest.mark.parametrize("fixed,reply,zh", [("en", "测试全部通过。", False), ("zh", "All tests pass.", True)])
def test_a_fixed_language_wins(tmp_path, monkeypatch, fixed, reply, zh):
    monkeypatch.setattr(config, "load", lambda cwd=None: dict(config.DEFAULTS, language=fixed))
    assert ("已拦截" in said(tmp_path, [EDIT], reply)) is zh


def test_a_report_with_no_conversation_follows_the_system(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    monkeypatch.setattr(hooks, "_SYSTEM_ZH", None)
    assert "拦截记录" in hooks.catches_report(7)
    from honestly.support import doctor
    assert "终端编码" in doctor()


# ------------------------------------------------------------------ config
def test_the_categories_can_be_found(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    out = config.show(str(tmp_path))
    for cat in ("tests_pass", "sent", "scheduled", "verified"):
        assert cat in out
    assert "unbacked" not in out and "unverified" in out


def exit_code(argv):
    try:
        return cli.main(argv) or 0
    except SystemExit as e:
        return e.code


def test_off_refuses_what_is_not_a_category(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert exit_code(["config", "off", "tests"]) == 2 and "tests_pass" in capsys.readouterr().err
    assert config.load(str(tmp_path))["off"] == []


@pytest.mark.parametrize("argv", [["config", "strictness", "bogus"], ["config", "language", "fr"], ["config", "strictness"], ["config", "off"], ["config", "verify"]])
def test_a_bad_setting_exits_2(tmp_path, monkeypatch, argv):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert exit_code(argv) == 2


def broken(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    os.makedirs(tmp_path / ".honestly")
    p = tmp_path / ".honestly" / "config.json"
    p.write_text('{ "strictness": "strict", ', encoding="utf-8")
    return p


def test_a_broken_settings_file_is_reported(tmp_path, monkeypatch):
    broken(tmp_path, monkeypatch)
    assert "not valid JSON" in config.show(str(tmp_path))
    from honestly.support import doctor
    assert "not valid JSON" in doctor(zh=False)


def test_a_broken_settings_file_is_not_overwritten(tmp_path, monkeypatch, capsys):
    p = broken(tmp_path, monkeypatch)
    before = p.read_text(encoding="utf-8")
    for argv in (["config", "language", "zh"], ["config", "off", "sent"], ["ignore", "x"]):
        assert exit_code(argv) != 0
    assert p.read_text(encoding="utf-8") == before


def test_the_project_file_is_found_from_a_subfolder(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / "src" / "deep").mkdir(parents=True)
    (root / ".honestly.json").write_text('{"off": ["tests_pass"]}', encoding="utf-8")
    assert config.load(str(root / "src" / "deep"))["off"] == []   # it relaxes, so it needs its owner's trust first
    assert stop(tmp_path, [EDIT], "All tests pass.", cwd=str(root / "src"))
    config.trust(str(root))
    assert config.load(str(root / "src" / "deep"))["off"] == ["tests_pass"]
    assert stop(tmp_path, [EDIT], "All tests pass.", cwd=str(root / "src")) is None


def test_a_file_above_the_repository_is_not_this_project(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    (tmp_path / ".honestly.json").write_text('{"off": ["tests_pass"]}', encoding="utf-8")
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    assert config.load(str(root))["off"] == []
    plain = tmp_path / "plain" / "sub"
    plain.mkdir(parents=True)
    assert config.load(str(plain))["off"] == []


def test_project_writes_go_to_the_repository_root(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / "src").mkdir()
    config.set_value("strictness", "strict", project=True, cwd=str(root / "src"))
    assert (root / ".honestly.json").exists() and not (root / "src" / ".honestly.json").exists()


def test_doctor_does_not_send_a_codex_user_to_the_claude_install(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HONESTLY_NO_UPDATE_CHECK", "1")
    hooks.guard("install", agent="codex")
    from honestly.support import doctor
    text, problems = doctor(zh=False, with_problems=True)
    assert "guard hooks not installed" not in text and "not use Claude Code" in text
    assert not any("run: honestly guard install" in p and "--agent" not in p for p in problems)   # the Claude Code install is not what it needs


def test_doctor_knows_the_plugin(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HONESTLY_NO_UPDATE_CHECK", "1")
    os.makedirs(tmp_path / ".claude")
    (tmp_path / ".claude" / "settings.json").write_text('{"enabledPlugins": {"honestly@honestly": true}}', encoding="utf-8")
    from honestly.support import doctor
    text, problems = doctor(zh=False, with_problems=True)
    assert not problems and "plugin" in text


def test_doctor_with_nothing_installed_still_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HONESTLY_NO_UPDATE_CHECK", "1")
    from honestly.support import doctor
    _, problems = doctor(zh=False, with_problems=True)
    assert problems


def test_doctor_reads_the_real_encoding(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HONESTLY_NO_UPDATE_CHECK", "1")
    monkeypatch.setenv("PYTHONIOENCODING", "latin-1")
    from honestly.support import doctor
    assert "warn terminal encoding latin-1" in doctor(zh=False)
