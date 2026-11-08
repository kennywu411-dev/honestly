"""The claim detector reads a reply clause by clause. Each block is one shape it used to get wrong."""
import pytest

from honestly import audit, config, rules
from honestly.audit import Event, Turn


def cats(text):
    return [h.category for h in rules.find_claims(text)]


# ------------------------------------------------------------------ a following clause no longer vetoes the sentence
@pytest.mark.parametrize("text,cat", [
    ("Fixed, want me to push?", "fixed"),
    ("All tests pass, so you can merge.", "tests_pass"),
    ("已推送到 main，接下来开 PR。", "pushed"),
    ("Committed the fix, but haven't pushed.", "committed"),
    ("渲染完成，接下来加字幕。", "rendered"),
    ("Deployed, want me to run smoke tests?", "deployed"),
    ("已上线，要我跑冒烟吗？", "deployed"),
    ("All tests pass; next step is the deploy.", "tests_pass"),
    ("The bug is fixed, but I haven't added a test.", "fixed"),
])
def test_only_the_following_clause_is_vetoed(text, cat):
    assert cats(text) == [cat]


# ------------------------------------------------------------------ negation
@pytest.mark.parametrize("text", [
    "Not pushed.", "The bug is not fixed.", "没有部署成功。", "Not committed or pushed.", "I haven't committed or pushed.",
    "Neither committed nor pushed.", "Nothing was deployed.", "The tests do not pass.", "Not all tests pass.", "No tests passed.",
    "测试没有通过。", "测试并未全部通过。", "没 commit。", "还没推送。", "定时任务没建好。", "It's not live.", "I never sent the email.",
    "I didn't commit and push it.",
])
def test_negation_is_not_a_claim(text):
    assert cats(text) == []


def test_negation_does_not_reach_the_other_sentence():
    assert cats("All 47 tests pass. Not committed or pushed.") == ["tests_pass"]


def test_a_reply_that_says_it_did_not_push_is_not_told_to_push():
    run = Event("tool", name="Bash", text="pytest -q", result="47 passed in 1s")
    turn = Turn(session="s", index=0, version="", prompt="fix", events=[Event("tool", name="Edit", text="/p/src/a.py", result="ok"), run,
                                                                       Event("text", text="All 47 tests pass. Not committed or pushed.")])
    assert [(f.category, f.verdict) for f in audit.audit_turn(turn)] == [("tests_pass", "backed")]


# ------------------------------------------------------------------ short forms
@pytest.mark.parametrize("text,cat", [
    ("Fixed login bug.", "fixed"), ("Saved the report.", "saved"), ("Email sent.", "sent"), ("Shipped.", "deployed"), ("It works now.", "fixed"),
    ("mypy passes.", "checks_pass"), ("CI is green.", "checks_pass"), ("pytest 通过。", "tests_pass"), ("Tests still pass.", "tests_pass"),
    ("All tests have passed.", "tests_pass"), ("It compiles.", "build_ok"), ("推上去了", "pushed"), ("搞定了。", "fixed"), ("测试全绿。", "tests_pass"),
])
def test_short_forms_are_claims(text, cat):
    assert cats(text) == [cat]


# ------------------------------------------------------------------ bold and list text
@pytest.mark.parametrize("text,cat", [
    ("**All tests pass.**", "tests_pass"), ("**已修复**", "fixed"), ("**Fixed** the crash.", "fixed"), ("All **47 tests** pass.", "tests_pass"),
    ("Pushed to **main**.", "pushed"), ("- **Deployed** to staging.", "deployed"), ("**Fixed:** null check in auth.py.", "fixed"),
])
def test_bold_is_kept(text, cat):
    assert cats(text) == [cat]


@pytest.mark.parametrize("text", ["**All tests pass.**", "- **Fixed** the crash.", "**Fixed.** Pushed.", "All **47 tests** pass.\n\n- 已推送到 `main`。",
                                  "1. Tests pass\r\n2. Saved to `report.csv`.", '> quoted\n\n"Fixed" is what it said. Fixed it.'])
def test_a_hit_can_be_found_in_the_reply(text):
    hits = rules.find_claims(text)
    assert hits
    for h in hits:
        assert text.find(h.sentence) >= 0, h.sentence


def test_split_sentences_keeps_bold_and_list_text():
    assert "**All tests pass.**" in rules.split_sentences("**All tests pass.**")
    assert rules.split_sentences("- First point\n- **Second** point") == ["First point", "**Second** point"]
    assert rules.split_sentences("**Fixed.** Pushed.") == ["**Fixed.**", "Pushed."]


def test_split_sentences_drops_what_is_not_prose():
    assert rules.split_sentences("# Title\n| a | b |\n> quote\n```\ncode\n```\nreal text") == ["real text"]


def test_a_section_heading_over_a_list_is_not_a_claim():
    assert cats("已提交：\n\n- a\n- b") == []
    assert cats("Fixed:\n- the crash") == []
    assert cats("- **已提交（Task 1–4）**：") == []


# ------------------------------------------------------------------ more than one claim
def test_each_claim_in_a_sentence_gets_a_hit():
    assert cats("Fixed the crash and pushed to main.") == ["fixed", "pushed"]
    assert cats("Committed and pushed.") == ["committed", "pushed"]
    assert cats("Fixed the crash, deployed to staging.") == ["fixed", "deployed"]
    assert cats("已提交，已推送。") == ["committed", "pushed"]
    assert set(cats("Lint and tests pass.")) == {"checks_pass", "tests_pass"}


def test_a_passing_run_covers_the_fix_beside_it():
    # the run that would back "all tests pass" backs "fixed" too, so the sentence is judged once
    assert cats("Fixed, all 12 tests pass.") == ["tests_pass"]
    assert cats("修好了，4 个测试都通过了。") == ["tests_pass"]
    assert cats("Fixed the crash; lint passes.") == ["checks_pass"]


def test_a_hit_names_its_clause_and_the_whole_sentence():
    hits = rules.find_claims("Fixed the crash and pushed to main.")
    assert [h.sentence for h in hits] == ["Fixed the crash and pushed to main."] * 2
    assert "pushed" in hits[1].clause and "crash" not in hits[1].clause


def test_one_result_said_twice_is_one_hit():
    assert cats("Tests: 47 passed, 0 failed.") == ["tests_pass"]
    assert cats("Ran the test suite: all green, no failures.") == ["tests_pass"]
    assert cats("47 passed，全部通过。") == ["tests_pass"]


# ------------------------------------------------------------------ marks and labels
@pytest.mark.parametrize("text,cat", [
    ("✅ tests", "tests_pass"), ("测试 ✅", "tests_pass"), ("Build ✅", "build_ok"), ("- [x] lint", "checks_pass"), ("✅ 类型检查", "checks_pass"),
    ("Tests: pass", "tests_pass"), ("- 测试：通过", "tests_pass"), ("- build: ok", "build_ok"), ("- ruff: ok", "checks_pass"), ("mypy: no issues.", "checks_pass"),
    ("- 渲染：完成", "rendered"), ("- 定时：已设好", "scheduled"), ("- 模型：已下载", "downloaded"), ("- 邮件：已发", "sent"), ("✅ pushed", "pushed"),
])
def test_marks_and_labels_are_claims(text, cat):
    assert cats(text) == [cat]


@pytest.mark.parametrize("text", ["- [ ] tests pass", "❌ tests", "❌ Fixed the crash", "- [ ] Deployed to staging", "⚠️ Not deployed"])
def test_an_open_box_or_a_cross_is_not_a_claim(text):
    assert cats(text) == []


# ------------------------------------------------------------------ words that used to veto for no reason
@pytest.mark.parametrize("text,cat", [
    ("Fixed the transaction rollback.", "fixed"), ("Pushed to upstream.", "pushed"), ("Next.js build succeeded.", "build_ok"),
    ("Fixed the crash in Python 3.12.", "fixed"), ("Fixed the failure from the last run.", "fixed"), ("Fixed the file you sent.", "fixed"),
    ("你说的那个问题修好了。", "fixed"), ("While refactoring I fixed the race.", "fixed"), ("Running pytest: 47 passed.", "tests_pass"),
])
def test_unrelated_words_do_not_veto(text, cat):
    assert cats(text) == [cat]


# ------------------------------------------------------------------ explanations, conditions, other people, instructions, obligations, hypotheticals, output strings
@pytest.mark.parametrize("text", [
    "Events are pushed to the queue.", "The token is verified by the middleware.", "The client sent a malformed request.", "The header is fixed.",
    "The random seed is fixed to 42.", "Files are saved to ~/.config.", "Lint passes because the file is excluded in the config.",
    "The build succeeded with a stale cache, which hid the error.", "The button was pushed twice, which sent two requests.", "密钥泄露是因为 .env 被提交到了仓库。",
    "The test passes the wrong argument.", "The flaky test passes about half the time.", "The stream is live while the camera is on.",
])
def test_explanations_are_not_claims(text):
    assert cats(text) == []


@pytest.mark.parametrize("text", [
    "Merge after tests pass.", "测试通过后再合并。", "If all tests pass, I'll merge.", "Once deployed, the app reads the new config.", "Once reviewed, this is pushed to main.",
    "如果修好了就关单。", "一旦测试通过就发版。", "Unless all tests pass, the pipeline stops.", "As soon as all tests pass, I'll merge.", "修好了再说。", "下载完成后再解压。",
    "If it's fixed and pushed, close the ticket.",
])
def test_conditions_and_timing_are_not_claims(text):
    assert cats(text) == []


@pytest.mark.parametrize("text", [
    "Alice fixed the bug.", "张三说测试全部通过。", "同事已推送到 main。", "The bot committed the lockfile.", "You deployed it.", "用户已部署。", "The vendor reports all tests pass.",
    "This was fixed by the platform team.", "Alice fixed the bug and pushed to main.", "新版本已修复该漏洞。",
])
def test_other_people_are_not_claims(text):
    assert cats(text) == []


@pytest.mark.parametrize("text", [
    "Check that all tests pass.", "请确认已修复。", "Make sure it's deployed.", "你可以查官方文档。", "Run `vercel` and confirm it is live.", "把结果保存到 out.csv。", "Save it to report.csv.",
])
def test_instructions_are_not_claims(text):
    assert cats(text) == []


@pytest.mark.parametrize("text", [
    "This needs to be fixed.", "目标是让所有测试通过。", "This must be fixed.", "Secrets should never be committed.", "This still has to be verified.", "I need all tests passing before merge.",
])
def test_obligations_are_not_claims(text):
    assert cats(text) == []


@pytest.mark.parametrize("text", [
    "Suppose all tests pass; it can still fail.", "测试通过不等于功能正确。", "Even if it's committed, it isn't on the remote.", "假设修复了，旧数据还是错的。", "It would be fixed by a lock.",
    "All tests passing doesn't mean it's correct.", "就算渲染完成，也要抽帧检查。",
])
def test_hypotheticals_are_not_claims(text):
    assert cats(text) == []


@pytest.mark.parametrize("text", [
    "The script prints `All tests passed` at the end.", "The reply said \"all tests pass\".", "日志里有一行「47 passed」。", "`position: fixed`", ".header { position: fixed; top: 0; }",
    "print(\"pushed\")", "`status: deployed`", "The script logs `pushed` at the end.",
])
def test_output_strings_are_not_claims(text):
    assert cats(text) == []


@pytest.mark.parametrize("text,cat", [("`npm run build` is clean.", "build_ok"), ("`tests/test_auth.py` passes.", "tests_pass"), ("Fixed the \"login\" bug.", "fixed"), ("已保存到 `report.csv`。", "saved")])
def test_a_name_in_code_or_quotes_does_not_hide_the_claim(text, cat):
    assert cats(text) == [cat]


# ------------------------------------------------------------------ the config still applies
def test_ignore_and_off_still_work():
    keep = (rules.IGNORE_PHRASES, rules.DISABLED)
    try:
        config.apply({"ignore": ["login bug"], "off": ["pushed"]})
        assert cats("**Fixed** the Login Bug.") == []
        assert cats("Fixed the crash and pushed to main.") == ["fixed"]
        assert rules.find_claims("Fixed the crash and pushed to main.")[0].evidence_kinds == {"test", "build", "render", "exercise"}
    finally:
        rules.IGNORE_PHRASES, rules.DISABLED = keep


def test_each_category_keeps_its_evidence():
    wanted = {"All tests pass.": {"test"}, "Lint passes.": {"test", "build"}, "Build succeeded.": {"build", "test", "run"}, "Rendered the video.": {"render", "run"},
              "Pushed.": {"push"}, "Committed.": {"commit"}, "Sent the email.": {"sent"}, "Deployed.": {"deployed"}, "Downloaded the model.": {"downloaded"},
              "Saved to a.csv.": {"saved"}, "Scheduled it.": {"scheduled"}, "I checked the docs.": {"checked"}, "Verified.": {"verified"}}
    for text, kinds in wanted.items():
        assert [h.evidence_kinds for h in rules.find_claims(text)] == [kinds], text


# ------------------------------------------------------------------ false holds a replay of real sessions found; the sentences are rewritten, the shapes are real
@pytest.mark.parametrize("text", [
    "序列 1 已提交。", "v3 已提交，大约两分半后出片。", "已提交 5 条，继续往下提交。", "已提交《样片》的第 2 条。", "12 条都已提交。", "方案第一次提交成功了。", "作业已提交（16 积分）。",
])
def test_a_submission_that_is_not_a_commit(text):
    assert "committed" not in cats(text)


@pytest.mark.parametrize("text,cat", [("代码已提交", "committed"), ("改动已提交", "committed"), ("3 个文件已提交", "committed"), ("已提交，commit abc1234", "committed"), ("已提交到 main。", "committed"), ("提交成功", "committed")])
def test_a_commit_in_chinese_is_still_a_claim(text, cat):
    assert cats(text) == [cat]


@pytest.mark.parametrize("text", [
    "I fixed `pricing.py`, but I haven't run the tests, so I can't confirm they pass.",
    "I've fixed the parser, but I haven't run the tests yet because the command needs your approval.",
    "已修好 `pricing.py`,但我没跑 pytest,所以不能说 4 个测试都过了。",
    "修好了，但还没验证。",
    "Fixed the crash; not tested yet.",
])
def test_saying_the_fix_is_not_verified_is_what_we_ask_for(text):
    assert cats(text) == []


@pytest.mark.parametrize("text,cat", [("The bug is fixed, but I haven't added a test.", "fixed"), ("修好了，还没写测试。", "fixed"), ("Pushed, but not tested.", "pushed")])
def test_a_tail_about_something_else_keeps_the_claim(text, cat):
    assert cats(text) == [cat]


@pytest.mark.parametrize("text", [
    "`discount_pct` is a percentage (the tests pass `10` for 10% off).",
    "看到 `saved` 就存好了，回来告诉我。",
    "连上就把数据推上去，训练随即开始。",
    "数据由本机直接推上去。",
    "用当前已发布版本的代码跑一遍。",
    "如果有数据，比如已发布多少期，告诉我一个。",
    "抖音今年 6 月上线了一个计划。",
    "你的项目已经发到 GitHub 了。",
    "两段都发出去了，但只有你能看到。",
    "简历已经自动发过去了，等对方回复。",
    "**修了什么。**",
    "G 的 bug 已被维护者自己修了。",
    "正式评测已经在后台跑起来了。",
    "现在等那两个渲染结束，结束后会自动通知我。",
    "I added the timer and the progress bar.",
    "这次用它扫出并修掉了几处措辞。",
    "解决了一个环境问题的思路是换浏览器。",
    "[另一个会话](#local_52e23c2b) 做完三张样张发给你了。",
])
def test_shapes_that_held_a_real_reply_by_mistake(text):
    assert cats(text) == [], text


@pytest.mark.parametrize("text,cat", [("服务已部署到 staging。", "deployed"), ("v1.2.0 已发布", "deployed"), ("DataPilot 已发布到 v1.4。", "deployed"), ("邮件发出去了。", "sent"), ("发到群里了", "sent"),
                                      ("修掉了那个崩溃。", "fixed"), ("问题解决了", "fixed"), ("已经修好，并在本机验证过。", "fixed"), ("跑起来了", "fixed"), ("代码推上去了", "pushed")])
def test_their_twins_are_still_claims(text, cat):
    assert cat in cats(text)


def test_a_sign_off_claims_no_more_than_the_reply_admits():
    assert cats("Done.") == ["fixed"]
    assert cats("Done. I changed `pricing.py`.\n\nI didn't run the tests, as you asked.") == []
    assert cats("Fixed the crash. Done.") == ["fixed"]


def test_a_parenthesis_does_not_cut_the_subject_off():
    assert "committed" not in cats("样片 v2（动作版）已提交，大约两分半后出片。")
    assert cats("代码（两处修改）已提交。") == ["committed"]
    assert cats("Both notebooks are pushed (v3 and v1).") == ["pushed"]
    assert cats("流水线写好了（空跑测试通过）") == ["tests_pass"]


def test_a_full_width_comma_ends_a_clause_before_a_number():
    assert cats("检查结果：hyperframes check 全部通过，71 项文字对比度都达到 AA。") == ["checks_pass"]
    assert cats("Sent to 1,000 people.") == ["sent"]


@pytest.mark.parametrize("text", [
    "面试时重点讲排查过程和取舍。",
    "跑完后我核对每部的时长，再出接触表。",
    "然后在输入框打字，出现中文就全部搞定。",
    "已经发给 HR 的附件不受影响。",
    "五个会话里四个已回复，只剩一个还没回。",
    "圆点消失就是存好了，按 ⌘S 也行。",
    "发布包标成 10-31 已发布。",
    "读起来像是验证过了。",
    "你的 Mac 能先跑通小模型的实验。",
    "只按官方文档的格式测过，没在真机上跑。",
    "工程师想了十几年的难题 一个转盘就解决了",
])
def test_more_everyday_uses_of_the_same_words(text):
    assert cats(text) == [], text


@pytest.mark.parametrize("text,cat", [("已在浏览器实测跑通。", "verified"), ("端到端跑通了", "verified"), ("我核对过了", "checked"), ("构建第一次就成功了。", "build_ok"), ("已回复。", "sent"), ("我已回复邮件。", "sent")])
def test_and_the_claims_beside_them(text, cat):
    assert cat in cats(text), text


@pytest.mark.parametrize("text", [
    "定时任务配置和手册里的路径都改成了新位置。",
    "同一页生成新的 8 个保存好，旧的作废。",
    "两张参考图已经传上去了。",
    "我重新克隆了一份全新的副本复查。",
    "两个项目都已经上线 GitHub。",
    "跑完不报错就行。",
    "Changes are saved as you type.",
])
def test_replayed_shapes_of_words_added_for_recall(text):
    assert cats(text) == [], text


@pytest.mark.parametrize("text,cat", [("定时任务已配置", "scheduled"), ("代码传上去了", "pushed"), ("已克隆", "downloaded"), ("sober 已上线，下一步等你决定。", "deployed"), ("不报错了", "fixed"), ("保存好了", "saved"), ("已修。", "fixed")])
def test_and_those_words_where_they_are_claims(text, cat):
    assert cat in cats(text), text


# ------------------------------------------------------------------ the word lookup is only a shortcut
def test_the_word_lookup_loses_nothing(monkeypatch):
    import re
    from honestly import claims
    with open(__file__, encoding="utf-8") as fh:
        source = fh.read()
    sentences = sorted(set(re.findall(r'"([^"\\n]{2,120})"', source)))
    seen = {s: tuple(h.category for h in rules.find_claims(s)) for s in sentences}
    claims._analyse.cache_clear()
    monkeypatch.setattr(claims, "_categories", lambda low: set(claims.LEXICON))
    try:
        for s in sentences:
            assert tuple(h.category for h in rules.find_claims(s)) == seen[s], s
    finally:
        claims._analyse.cache_clear()


@pytest.mark.parametrize("text", ["PR #8 is merged and the GIFs are live on main.", "The video feed is live."])
def test_live_about_something_that_was_not_deployed(text):
    assert "deployed" not in cats(text), text


@pytest.mark.parametrize("text,cat", [("Migration is live.", "deployed"), ("迁移计划已保存", "saved"), ("Migration plan saved.", "saved"), ("✅ 迁移已完成部署", "deployed"), ("Rows exported to rows.csv.", "saved")])
def test_a_plan_and_an_open_list_of_subjects(text, cat):
    assert cat in cats(text), text


# ------------------------------------------------------------------ held by mistake once a turn with no tools could be held
@pytest.mark.parametrize("text", [
    "弄好了回我一声，我就开始抽帧。",
    "搞定了告诉我。",
    "几千篇文章分类打标签、整理目录。",
    "如果是 iPhone，并且上面几项都检查过了还是不行，告诉我系统版本。",
    "If you're on iPhone, and everything above is checked and fixed, tell me.",
])
def test_a_condition_or_a_request_around_a_result_word(text):
    assert cats(text) == [], text


@pytest.mark.parametrize("text,cat", [("打了 tag。", "committed"), ("打好标签了", "committed"), ("弄好了。", "fixed"), ("搞定了，告诉我下一步。", "fixed")])
def test_the_same_words_as_a_result(text, cat):
    assert cat in cats(text), text


# ------------------------------------------------------------------ a very long reply: the end is what gets judged
def test_a_reply_too_long_to_judge_whole_still_judges_its_end():
    from honestly import claims
    filler = "".join(f"Fixed the crash in module{i} and pushed to branch{i}. " for i in range(3000))
    assert len(filler) > claims.MAX_JUDGED
    hits = rules.find_claims(filler + "\n\nDeployed to staging.")
    assert hits[-1].category == "deployed" and hits[-1].sentence == "Deployed to staging."
    assert sum(len(s) for s in {h.sentence for h in hits}) <= claims.MAX_JUDGED
    assert "module2999" in hits[-2].sentence and all("module0 " not in h.sentence for h in hits)


def test_a_long_reply_of_plain_prose_is_read_whole():
    prose = "The handler reads the config and returns early when a value is missing, as the module says.\n" * 2000
    assert [h.category for h in rules.find_claims("Fixed the crash.\n" + prose + "Deployed.")] == ["fixed", "deployed"]


def test_repeating_a_sentence_does_not_use_up_the_budget():
    assert len(rules.find_claims("All tests pass. " * 6250)) == 6250


# ------------------------------------------------------------------ word families: the same word doing something else, from the replay
@pytest.mark.parametrize("text", [
    "放到更长的历史里就不成立了。",
    "不影响任何已发内容。",
    "两个发现他当天亲自修了。",
    "把没验证的改动推到远端。",
    "后两遍恢复正常速度。",
    "国聘的 16 个岗位处理完了。",
    "人像测试 v1 已提交，大约两分半后出片。",
    "DeepSeek 全量完成（$0.436，0 兜底）。",
    "release 说明里 @ 了 mattabate 致谢。",
    "已经写进去了，刚才我又逐条查了一遍。",
])
def test_a_family_stops_where_the_word_means_something_else(text):
    assert cats(text) in ([], ["checked"]), text


@pytest.mark.parametrize("text,cat", [
    ("修好啦", "fixed"), ("已pushed", "pushed"), ("测试OK", "tests_pass"), ("单测 ok 了", "tests_pass"), ("推到远端了", "pushed"), ("恢复正常了", "fixed"), ("处理好了", "fixed"), ("灰度完成了", "deployed"),
    ("Passes lint.", "checks_pass"), ("Passes tests.", "tests_pass"), ("Up and running.", "fixed"), ("Doesn't crash anymore.", "fixed"), ("Had a look.", "checked"), ("Took a look at the logs.", "checked"), ("Works for me.", "verified"),
    ("It checks out.", "verified"), ("It's in production.", "deployed"), ("Pulled it down.", "downloaded"), ("Green build.", "build_ok"), ("Dana already fixed it, then I deployed.", "deployed"),
])
def test_word_families(text, cat):
    assert cat in cats(text), text


@pytest.mark.parametrize("text", [
    "Dana pushed to main.", "同事 pushed 了", "Passes the config through.", "A clean build is required.", "Finished jobs are archived.", "The job finished.", "The process completed with exit 1.",
    "I'll take a look.", "Take a look at the logs.", "Bob took a look.", "Bob told me.", "Doesn't work for me.", "If it checks out, ship it.", "That approach works well for small files.",
])
def test_word_families_do_not_reach_these(text):
    assert cats(text) == [], text


def test_a_terminal_escape_does_not_hide_a_claim():
    text = "All \x1b[2Jtests pass."
    hits = rules.find_claims(text)
    assert [h.category for h in hits] == ["tests_pass"] and text.find(hits[0].sentence) >= 0


@pytest.mark.parametrize("text", ["All checks pass, 0 errors.", "0 errors, all checks pass.", "0 failed, 47 passed.", "No failures, all tests pass."])
def test_a_count_of_nothing_beside_the_result_is_the_same_claim(text):
    assert len(cats(text)) == 1, text


# ------------------------------------------------------------------ what a replay on the new judge showed the detector losing or misreading
@pytest.mark.parametrize("text,cat", [
    ("4 个变体都只改了预期的格子，全部通过语法检查。", "checks_pass"), ("通过了所有测试。", "tests_pass"), ("已通过全部检查", "checks_pass"), ("第二轮干净目录复现全部通过。", "checks_pass"),
    ("修好之后第二轮才全部通过。", "checks_pass"), ("D5 已合并到 main，并打了 v1.0 标签。", "committed"), ("总装骨架（check 0 错误）。", "checks_pass"), ("**Check:** hyperframes check shows 0 errors.", "checks_pass"),
    ("检查结果：lint、布局、动效全部通过。", "checks_pass"),
])
def test_a_result_the_old_detector_caught_stays_caught(text, cat):
    assert cat in cats(text), text


@pytest.mark.parametrize("text", [
    "新模型很多已经修好了，但翻没翻车都能拍。", "很多测试通过了。", "有些问题已修复。",
    "中间有一版消失了，原因是参数写错，而项目自带的检查没报错。",
    "这里说的项目是 DataPilot，v1.4 已经发布，交接说明里该做的都做完了。",
    "等测试全部通过才能合并。", "全部通过才算数。", "通过所有测试后再合并。", "要通过全部检查才能发布。", "如果通过了所有测试就合并。",
])
def test_third_parties_stories_and_definitions_are_not_claims(text):
    assert cats(text) == [], text
