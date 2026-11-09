"""The action table reads a finished action in words nobody listed. These come from what real replies say and from what a reader takes for a claim."""
import pytest

from honestly import rules


def cats(text):
    return [h.category for h in rules.find_claims(text)]


@pytest.mark.parametrize("text,cat", [
    ("复盘和规范已补上。", "saved"), ("进度已经写进 docs/progress.md。", "saved"), ("README 和两份面试稿已同步更新。", "saved"), ("文档、状态文件和 AGENTS 都已更新。", "saved"), ("两条新规则补进了 CLAUDE.md。", "saved"),
    ("依赖都装好了。", "downloaded"), ("brew 装好了 ffmpeg。", "downloaded"), ("Docker 镜像 pull 下来了。", "downloaded"), ("Dependencies are all installed now.", "downloaded"), ("I installed ffmpeg via Homebrew.", "downloaded"),
    ("PR 开好了，#318。", "pushed"), ("分支已经合并进主干。", "pushed"), ("D3 已经合并进 main。", "pushed"), ("PR is up: #482.", "pushed"), ("Merged into main after the review came back approved.", "pushed"),
    ("已 deploy 到 Vercel，线上可访问。", "deployed"), ("预发环境更新好了。", "deployed"), ("v2.3.1 is out on npm.", "deployed"),
    ("封面图已经生成。", "rendered"), ("音频合成完毕。", "rendered"), ("I generated all six thumbnails.", "rendered"),
    ("改动都 commit 到 feature/login 分支了。", "committed"), ("我把这次重构拆成了三个提交。", "committed"), ("That's checked in locally now.", "committed"),
    ("备份任务已配置，每晚十二点执行。", "scheduled"), ("Added a launchd job that refreshes the cache hourly.", "scheduled"),
    ("已经回复客户了。", "sent"), ("通知已发给所有报名的人。", "sent"), ("Tweet's up with the launch video attached.", "sent"),
    ("我实际点了一遍，功能正常。", "verified"), ("校验和对上了。", "verified"), ("Tried it by hand in Chrome and Firefox.", "verified"),
    ("差异已经审过。", "checked"), ("查了 Sentry，昨晚没有新报错。", "checked"), ("I looked through the logs.", "checked"),
    ("持续集成已经变绿了。", "checks_pass"), ("流水线九个任务全过。", "checks_pass"), ("tsc 零报错。", "build_ok"), ("gradle assembleRelease 过了。", "build_ok"),
    ("单测 56/56 全过。", "tests_pass"), ("回归下来零失败。", "tests_pass"), ("Now at 41/41 in the auth module.", "tests_pass"), ("导出时乱码的毛病解决了。", "fixed"), ("The 500 on /checkout is fixed.", "fixed"),
])
def test_a_finished_action_is_read(text, cat):
    assert cat in cats(text), text


@pytest.mark.parametrize("text", [
    "镜头推到 37 个白格后停住。", "把问题推到最尖锐。", "一路推到戴放大镜的脸。", "路网明显开始合并了。", "在已有条目里合并了三处。",          # 推 and 合 mean other things
    "现在提交。", "记录 P23 并提交。", "然后提交，并请审阅者看整个分支。",                                                                 # a plan
    "重写好了，都按你说的标准来写。", "每个都写好了钩子和旅程。", "记下了。",                                                               # written into the chat, or noted
    "这些我们的规范里都已经写了。", "配置文件保存在 ~/.config/foo。", "日志写入 /var/log/app.log。", "数据都保存在本地。",                     # how things are
    "我把上面三项补进实施说明。", "把结果保存到 out.csv。", "写进问题日志；",                                                              # no mark of being finished
    "模拟面试过关才算做完。", "工具调用都已经封装好了。", "你同事已经把修复推上去了。", "你的脚本已经把视频渲染好了。", "另一个助手把文件写到了临时目录。", "评审人已经看过这段代码。",
    "邮件没发出去。", "这封邮件要是发出去，可能会被当成垃圾邮件。", "渲染完成后进度条才会消失。", "渲染完成后我会通知你。", "部署成功的话，旧实例会自动下线。", "空格也补好了，我就帮你发送。",
    "Files are downloaded to the cache.", "The service is deployed behind nginx.", "The job is scheduled with APScheduler.", "The result is saved in a variable.", "The header is fixed.", "The seed is fixed.", "The bug is fixed in version 2.0 upstream.",
    "Some of the frames might also be AI-generated video mixed in.", "Back in 2023 I deployed a similar service on Heroku.", "In a previous project I set up a nightly cron like this one.", "上次迁移时，我们把快照存到了磁带上。", "三年前这个仓库推到过另一个远端。",
])
def test_these_state_no_finished_action(text):
    assert [c for c in cats(text) if c != "fixed"] == [], text


def test_a_known_wording_is_never_loose():
    assert all(not h.loose for h in rules.find_claims("邮件已发送给他了。 All tests pass. 已推送到 main。"))


def test_a_new_wording_is_loose():
    assert all(h.loose for h in rules.find_claims("复盘和规范已补上。"))
