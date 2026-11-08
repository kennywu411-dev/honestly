"""Claude Code hooks: `honestly hook stop` and `honestly hook pre`, plus `honestly guard` install/uninstall.

Stop hook: if the reply the agent is about to send claims "tests pass / fixed / pushed ..." but
this turn's transcript shows no matching check after the last code edit, ask the agent to run it
(or say the work is unverified) before stopping. Fires once per turn (stop_hook_active guard).

PreToolUse hook (Bash): refuses a pipeline that keeps a test or build verdict from the agent (the summary cut off,
filtered out or discarded, or one suite's result scrolled away) and is not run with pipefail. The hook denies the call with a fix.
"""
from __future__ import annotations
import json
import os
import re
import sys
from . import rules, config, agents
from .audit import audit_turn
from .claude_code import Event, Turn

MARK = "honestly hook"
LEGACY_MARKS = ("sober hook",)   # entries written by the package's previous name
MARKS = (MARK,) + LEGACY_MARKS


def _ours(h: dict) -> bool:
    return any(m in h.get("command", "") for m in MARKS)


def _read_stdin():
    try:
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")   # Claude Code sends UTF-8; Windows would decode with the locale
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            _note("stdin", f"hook input is not a JSON object ({type(data).__name__}); nothing checked")
            return {}
        return data
    except Exception as e:
        _note("stdin", f"hook input is not JSON ({e.__class__.__name__}); nothing checked")
        return {}


CJK = re.compile(r"[\u4e00-\u9fff]")


_SYSTEM_ZH = None


def system_zh() -> bool:
    """Whether the user's system language is Chinese.

    POSIX order first (LC_ALL, then LC_MESSAGES, then LANG; a set value wins even when it is C or English). Apps started
    from the macOS Dock or the Windows Start menu often pass no locale variables to their hooks, so with none set the OS
    UI language is read: AppleLanguages on macOS, GetUserDefaultUILanguage on Windows. Any failure means English.
    """
    global _SYSTEM_ZH
    if _SYSTEM_ZH is not None:
        return _SYSTEM_ZH
    zh = False
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "")
        if val:
            zh = val.lower().startswith("zh")
            break
    else:
        try:
            if sys.platform == "darwin":
                import subprocess
                out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True, timeout=1).stdout
                first = re.search(r"[\"']?([A-Za-z]{2,3})[-_A-Za-z]*", out.replace("(", " "))
                zh = bool(first) and first.group(1).lower() == "zh"
            elif sys.platform == "win32":
                import ctypes
                zh = (ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF) == 0x04   # LANG_CHINESE
        except Exception:
            zh = False
    _SYSTEM_ZH = zh
    return zh


def _is_zh(text: str) -> bool:
    return bool(CJK.search(text or "")) or system_zh()


def _lang_zh(cfg: dict, *texts: str) -> bool:
    """Message language: the config's choice when it is fixed, otherwise whatever the conversation is in."""
    lang = cfg.get("language", "auto")
    if lang in ("zh", "en"):
        return lang == "zh"
    return any(_is_zh(t) for t in texts if t)


AGENT_NAMES = agents.NAMES


HARNESS_TAG = re.compile(r"<(system-reminder|task-notification|bash-input|bash-stdout|bash-stderr|local-command-stdout|local-command-stderr|command-name|command-message|command-args|ide_[\w-]+|side-sessions-event|ci-monitor-event)\b[^>]*>.*?(</\1>|$)", re.S)
BOILERPLATE = re.compile(r"^\s*(This session is being continued from a previous conversation|Caveat: The messages below)", re.I)


def _topic(prompt: str, limit: int = 30) -> str:
    """The user's own words, without the tags the harness wraps around system notes; empty when the turn was not started by the user."""
    full = re.sub(r"\s+", " ", HARNESS_TAG.sub(" ", prompt or "")).strip()
    if not full or BOILERPLATE.match(full):
        return ""
    return full[:limit] + ("…" if len(full) > limit else "")


def _who_where(data: dict, turn, zh: bool) -> str:
    """Name the assistant, its model, the project and the conversation, so the user knows exactly which chat this is about."""
    agent = AGENT_NAMES.get(getattr(turn, "agent", "") or "claude-code", "Claude Code")
    model = getattr(turn, "model", "") or ""
    who = f"{agent}（{model}）" if (zh and model) else (f"{agent} ({model})" if model else agent)
    project = _short(data.get("cwd") or getattr(turn, "project", "") or "")
    topic = _topic(getattr(turn, "prompt", "") or "")
    if zh:
        where = (f"在「{project}」项目" if project else "") + (f"回复「{topic}」这个问题时" if topic else "")
        return who + (where or "")
    where = (f" in project {project}" if project else "") + (f', answering "{topic}",' if topic else "")
    return who + where


def _edited_name(last_edit: str) -> str:
    """A short file name for the last edit; a shell command that changed files names its last file, or nothing."""
    first = (last_edit or "").splitlines()[0] if last_edit else ""
    kind, _, rest = first.partition(":")
    rest = rest.strip()
    if kind.strip().lower() == "bash":
        cmd = (last_edit or "").partition(":")[2].strip()
        written = [t.strip() for s in rules.segments(cmd) if rules.segment_is_edit(s, cmd) for t in rules.segment_targets(s, cmd) if t.strip()]
        if written:   # `cd proj/.claude && python3 - <<EOF ... open('launch.json', 'w')` wrote launch.json, not ".claude"
            return re.split(r"[\\/]", written[-1])[-1][:40]
        files = re.findall(r"[\w./\\-]+\.[A-Za-z0-9]{1,6}\b", QUOTED.sub(" ", rules.CD_DIR.sub(" ", rest)))   # a `cd` folder is not the file
        return re.split(r"[\\/]", files[-1])[-1][:40] if files else ""
    return re.split(r"[\\/]", rest)[-1][:40] if rest else ""


STOP_NOUN = {"tests_pass": ("test", "测试"), "checks_pass": ("check", "检查"), "build_ok": ("build", "构建"), "rendered": ("render", "渲染"),
             "pushed": ("push", "推送"), "committed": ("commit", "提交")}


def _plain_stop(f, zh: bool, who: str = "") -> str:
    """What the user sees. No jargon: what the agent said, what actually happened after its last edit, what happens next."""
    claim = re.sub(r"\s{2,}", " ", f.claim.strip().rstrip("。．.!！;；"))[:60]
    edited = _edited_name(f.last_edit)
    en_noun, zh_noun = STOP_NOUN.get(f.category, ("test or check", "测试或检查"))
    failed = f.verdict == "contradicted"
    errored = not failed and "errored" in (f.reason or "")
    image_only = f.verdict == "weak"
    if zh:
        who = who or "AI"
        if not f.last_edit:
            return f"⚠️ honestly 已拦截：{who}声称「{claim}」，但本轮记录中没有对应的操作。已要求其先完成操作再回复。"
        where = f"改完 {edited} 之后" if edited else "改完代码之后"
        if failed:
            return f"⚠️ honestly 已拦截：{who}声称「{claim}」，但{where}的{zh_noun}结果显示失败。已要求其修复，或如实报告失败。"
        if errored:
            return f"⚠️ honestly 已拦截：{who}声称「{claim}」，但{where}运行的{zh_noun}报错了。已要求其处理后重新运行。"
        if image_only:
            return f"⚠️ honestly 已拦截：{who}声称「{claim}」，但{where}只看了截图，没有运行{zh_noun}。已要求其先运行再回复。"
        if f.category == "tests_pass":
            return f"⚠️ honestly 已拦截：{who}声称「{claim}」，但{where}没有运行测试命令。已要求其先运行测试再回复。"
        return f"⚠️ honestly 已拦截：{who}声称「{claim}」，但{where}没有运行{zh_noun}。已要求其先运行再回复。"
    who = who or "the agent"
    if not f.last_edit:
        return f'⚠️ honestly blocked this reply: {who} said "{claim}" but no matching action ran in this turn. It has been asked to do it first.'
    where = f"after editing {edited}" if edited else "after editing the code"
    if failed:
        return f'⚠️ honestly blocked this reply: {who} said "{claim}" but the {en_noun} {where} reported a failure. It has been asked to fix it or report the failure.'
    if errored:
        return f'⚠️ honestly blocked this reply: {who} said "{claim}" but the {en_noun} it ran {where} errored. It has been asked to deal with that and run it again.'
    if image_only:
        return f'⚠️ honestly blocked this reply: {who} said "{claim}" but only looked at a screenshot {where}. It has been asked to run a {en_noun} first.'
    if f.category == "tests_pass":   # a snippet that calls test functions is not a test run
        return f'⚠️ honestly blocked this reply: {who} said "{claim}" but no test runner ran {where}. It has been asked to run the tests first.'
    article = "an" if en_noun[0] in "aeiou" else "a"
    return f'⚠️ honestly blocked this reply: {who} said "{claim}" but no {en_noun} ran {where}. It has been asked to run {article} {en_noun} first.'


def _pipe_name(cmd: str) -> str:
    stages = rules.pipe_stages(cmd)
    nxt = stages[1].strip().split() if len(stages) > 1 else []
    return os.path.basename(nxt[0].strip("\"'")) if nxt else "tail"


def _plain_pre(cmd: str, zh: bool, who: str = "", pipe: str = "", why: str = "head", kind: str = "test", tool: str = "") -> str:
    m = re.search(r"(pytest|npm test|npm run [\w:-]+|cargo test|cargo build|go test|go build|make(?: [A-Za-z][\w-]*)?|yarn test|pnpm test|mvn [\w-]+|gradle [\w-]+|tox|ruff|mypy|tsc|eslint)", cmd)
    pipe = pipe or _pipe_name(cmd)
    tool = (m.group(1) if m else tool).strip()
    test_like = kind in ("test", "multi")
    if zh:
        t = f" {tool} " if tool else "检查命令"
        res = "测试结果" if test_like else "结果"
        what = {"head": f"用 {pipe} 截掉了{t}输出的末尾，而{res}就打印在末尾",
                "silent": f"用 {pipe} 丢弃了{t}的输出，输出和退出码都看不到结果",
                "count": f"用 {pipe} 把{t}的输出变成了计数，看不到通过/失败的汇总",
                "filter": f"用 {pipe} 过滤了{t}的输出，通过/失败的汇总行会被滤掉",
                "tail": f"用 {pipe} 只保留了{t}输出的最后几行，前面的失败会看不到"}.get(why, f"用 {pipe} 截断了{t}的输出")
        return f"⚠️ honestly 已拦截该命令：{who or 'AI'}{what}。已要求其重新运行并显示真实结果。"
    t = tool or "a check"
    res = "test result" if test_like else "result"
    what = {"head": f"cut off the end of {t}'s output with {pipe}, where the {res} is printed",
            "silent": f"discarded {t}'s output with {pipe}, so neither the output nor the exit status shows the result",
            "count": f"reduced {t}'s output to a count with {pipe}, so the pass/fail summary is not shown",
            "filter": f"filtered {t}'s output with {pipe}, which drops the pass/fail summary",
            "tail": f"kept only the last lines of {t}'s output with {pipe}, so a failure earlier in the run would not show"}.get(why, f"cut {t}'s output with {pipe}")
    return f"⚠️ honestly blocked this command: {who or 'the agent'} {what}. It has been asked to rerun it so the real result is visible."


def _notify(title: str, body: str) -> None:
    """Desktop notification, opt-in via HONESTLY_NOTIFY=1 (hooks have no terminal; this reaches people who never look at one)."""
    if os.environ.get("HONESTLY_NOTIFY") != "1" and not os.path.exists(notify_flag_path()):
        return
    if not _notify_due():
        return   # a burst of catches (a loop, a replayed batch) shows one notification, not dozens
    import subprocess, sys as _sys
    body = re.sub(r"\s+", " ", body).strip()[:200]
    title = re.sub(r"[^\w .:-]", "", title)[:40] or "honestly"
    try:
        if _sys.platform == "darwin":
            def esc(s: str) -> str:   # AppleScript string literal: backslash and double quote are the only specials
                return s.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(["osascript", "-e", f'display notification "{esc(body)}" with title "{esc(title)}"'], timeout=5, capture_output=True)
        elif _sys.platform.startswith("linux"):
            subprocess.run(["notify-send", "--", title, body], timeout=5, capture_output=True)
        elif _sys.platform == "win32":
            # the text travels in environment variables: nothing from the reply is ever part of the script
            ps = ("[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');"
                  "$n=New-Object System.Windows.Forms.NotifyIcon;$n.Icon=[System.Drawing.SystemIcons]::Information;$n.Visible=$true;"
                  "$n.ShowBalloonTip(8000,$env:HONESTLY_NOTIFY_TITLE,$env:HONESTLY_NOTIFY_BODY,[System.Windows.Forms.ToolTipIcon]::Warning);Start-Sleep 8;$n.Dispose()")
            env = dict(os.environ, HONESTLY_NOTIFY_TITLE=title, HONESTLY_NOTIFY_BODY=body)
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=15, capture_output=True, env=env)
    except Exception:
        pass


NOTIFY_GAP = 300   # seconds between two desktop notifications; only a held reply notifies, never a refused command


def _notify_due() -> bool:
    """True at most once per NOTIFY_GAP seconds; the stamp file's mtime is the last notification."""
    import time
    stamp = notify_flag_path() + ".last"
    try:
        if time.time() - os.path.getmtime(stamp) < NOTIFY_GAP:
            return False
    except OSError:
        pass
    try:
        os.makedirs(os.path.dirname(stamp), exist_ok=True)
        with open(stamp, "w", encoding="utf-8"):
            pass
    except OSError:
        pass
    return True


def notify_flag_path() -> str:
    return os.path.join(os.path.expanduser("~/.honestly"), "notify")


def set_notify(on: bool) -> str:
    """`honestly guard notify on|off`: a marker file, so it works on every platform without touching the environment."""
    path = notify_flag_path()
    if on:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").close()
        return "honestly guard: desktop notifications on (each catch also pops up as a system notification)"
    if os.path.exists(path):
        os.remove(path)
    return "honestly guard: desktop notifications off"


def catches_path() -> str:
    return os.path.join(os.path.expanduser("~/.honestly"), "catches.jsonl")


def local_time(ts: str) -> str:
    """A catch's UTC timestamp as local wall-clock time, for people reading the report."""
    import datetime
    try:
        d = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return d.astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)[:16]


def _note(which: str, msg: str) -> None:
    """One line in hook-errors.log for input the hook let through without looking at (so `doctor` can show why nothing was caught)."""
    import datetime
    try:
        os.makedirs(os.path.dirname(errors_path()), exist_ok=True)
        with open(errors_path(), "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} {which}: {msg}\n")
    except Exception:
        pass


def _record(kind: str, data: dict, turn, plain: str, claim: str = "", reason: str = "", command: str = "", tools=None) -> None:
    """Append one line per catch so `honestly catches` can show what guard did this week. Local file, never sent anywhere."""
    import datetime
    row = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "kind": kind,
           "agent": getattr(turn, "agent", "") or "claude-code", "model": getattr(turn, "model", "") or "",
           "project": (data.get("cwd") or getattr(turn, "project", "") or ""), "topic": _topic(getattr(turn, "prompt", "") or "", 80),
           "claim": claim[:200], "reason": reason[:200], "command": command[:200], "message": plain,
           "tools": [str(t)[:160] for t in (tools or [])][-8:], "version": __import__("honestly").__version__,
           "session": getattr(turn, "session", "") or "", "turn": getattr(turn, "index", 0)}
    try:
        os.makedirs(os.path.dirname(catches_path()), exist_ok=True)
        with open(catches_path(), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


def load_catches(since_days: int | None = None) -> list[dict]:
    import datetime
    rows = []
    if not os.path.exists(catches_path()):
        return rows
    cutoff = None
    if since_days:
        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=since_days)).isoformat(timespec="seconds")
    with open(catches_path(), encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if isinstance(r, dict) and (not cutoff or str(r.get("ts", "")) >= cutoff):
                rows.append(r)
    return rows


def catches_report(since_days: int = 7, zh: bool | None = None) -> str:
    """Plain summary of what guard stopped, for people who never read the terminal while it happened."""
    from collections import Counter
    if zh is None:
        zh = _lang_zh(config.load(), "")
    rows = load_catches(since_days)
    window = f"最近 {since_days} 天" if zh else f"last {since_days} days"
    if not rows:
        if zh:
            return (f"honestly guard：{window}没有拦截记录。\n"
                    "  要么助手每次都做了检查，要么 guard 没装上（honestly guard status 查看，honestly doctor 体检）。")
        return (f"honestly guard: no catches in the {window}.\n"
                "  Either the agent ran its checks every time, or guard is not installed (honestly guard status, honestly doctor).")
    stop = sum(1 for r in rows if r.get("kind") == "stop")
    pre = len(rows) - stop
    by_project = Counter(_short(r.get("project", "")) for r in rows)
    by_model = Counter((AGENT_NAMES.get(r.get("agent", ""), r.get("agent", "")) + " " + r.get("model", "")).strip() for r in rows)
    n = len(rows)
    if zh:
        lines = [f"honestly guard：{window}已拦截 {n} 次",
                 f"  {stop:3}  说「做完了」（测试通过、修好了、已发送、已部署、已保存…）但记录里没做",
                 f"  {pre:3}  检查命令的结果被管道截断或过滤", "", "按项目："]
    else:
        lines = [f"honestly guard: {n} catch{'es' if n != 1 else ''} in the {window}",
                 f"  {stop:3}  said \"done\" (tests pass, fixed, sent, deployed, saved...) with nothing behind it",
                 f"  {pre:3}  ran a check with its result cut off or filtered by a pipe", "", "By project:"]
    for k, c in by_project.most_common(8):
        lines.append(f"  {c:3}  {k or ('（未知）' if zh else '(unknown)')}")
    lines.append("按助手：" if zh else "By assistant:")
    for k, c in by_model.most_common(5):
        lines.append(f"  {c:3}  {k or ('（未知）' if zh else '(unknown)')}")
    lines += ["", "最近三次：" if zh else "Most recent:"]
    for r in rows[-3:]:
        lines.append(f"  {local_time(r.get('ts', ''))}  {r.get('message', '')[:160]}")
    lines.append("")
    if zh:
        lines.append(f"可以直接分享的一句话：honestly 在{window}拦截了 AI 助手 {n} 次未经检查就报告「已完成」的回复。")
        lines.append("认为是误判？运行 honestly feedback 生成反馈。")
    else:
        lines.append(f"One line to share: honestly blocked my coding agent {n} time{'s' if n != 1 else ''} in the {window} from saying \"done\" without checking.")
        lines.append("A catch looks wrong? `honestly feedback` turns it into an issue-ready text.")
    return "\n".join(lines)


def _short(path: str) -> str:
    """The project's folder name; a tool's config folder the shell happened to be in (.claude, .vscode, .git) is not a project."""
    parts = [p for p in re.split(r"[\\/]", path or "") if p]
    home = [p for p in re.split(r"[\\/]", os.path.expanduser("~")) if p]
    while len(parts) > 1 and parts[-1].startswith(".") and parts[:-1] != home:   # ~/.claude itself is the user's global config
        parts.pop()
    return parts[-1] if parts else ""


def stop_hook(data: dict | None = None, agent: str = "claude-code") -> dict | None:
    data = agents.normalize(agent, "stop", data if data is not None else _read_stdin())
    second_pass = bool(data.get("stop_hook_active"))   # the agent is answering a block: warn, never block twice
    cfg = config.load(data.get("cwd") or None)
    config.apply(cfg)
    final = data.get("last_assistant_message") or ""
    path = data.get("transcript_path") or ""
    turn = None
    prev = None
    if path and os.path.exists(path):
        try:
            turns = agents.parser_for(agent, tail=True)(path)
        except Exception as e:
            _note("stop", f"transcript could not be parsed, only the final message was checked: {path} ({e.__class__.__name__}: {e})")
            turns = []
        if turns:
            turn = turns[-1]
            prev = turns[-2] if len(turns) > 1 else None
            if prev is not None and (turn.prompt or "").lstrip().startswith(("Stop hook feedback", "⚠️ honestly")):
                # Claude Code and Gemini CLI feed the block back as a new message; the work it answers is the turn before it
                import dataclasses
                turn = dataclasses.replace(prev, events=[e for e in prev.events if e.kind != "text"] + list(turn.events))   # judge only the new reply, with the earlier edits as context
                prev = turns[-3] if len(turns) > 2 else None
        elif os.path.getsize(path) == 0:
            _note("stop", f"transcript is empty, only the final message was checked: {path}")
    elif path:
        _note("stop", f"transcript_path does not exist, only the final message was checked: {path}")
    if turn is None:
        turn = Turn(session="live", index=0, version="", prompt="", agent=agent, model=str(data.get("model") or ""))
    if agent == "gemini" and second_pass and any(e.kind == "text" for e in turn.events):
        final = ""   # on a retry Gemini CLI's prompt_response repeats the held reply; the recording has the new one alone
    if final and not any(e.kind == "text" and final[:80] in e.text for e in turn.events):
        turn.events.append(Event("text", text=final))
    bad = [f for f in audit_turn(turn, prev) if f.verdict in config.blocked_verdicts(cfg)]
    if not bad:
        return None
    zh = _lang_zh(cfg, bad[0].claim)
    if second_pass:
        claim = re.sub(r"\s{2,}", " ", bad[0].claim.strip().rstrip("。．.!！;；"))[:60]
        note = (f"⚠️ honestly 提醒：这条回复仍然声称「{claim}」，但最后一次改动之后仍没有可核实的依据。为避免反复拦截，这次没有再拦，请把它当作未经验证。" if zh else
                f'⚠️ honestly: this reply still says "{claim}" with nothing after the last edit to back it. It was not held a second time; treat it as unverified.')
        return agents.warn(agent, note)
    plain = _plain_stop(bad[0], zh, _who_where(data, turn, zh))
    if len(bad) > 1:
        plain += f"（这条回复里还有 {len(bad) - 1} 句同样没有依据。）" if zh else f" ({len(bad) - 1} more sentence{'s' if len(bad) > 2 else ''} in this reply {'have' if len(bad) > 2 else 'has'} the same problem.)"
    _record("stop", data, turn, plain, claim=bad[0].claim, reason=bad[0].reason, tools=bad[0].tools_after_edit)
    _notify("honestly", plain)
    # Claude Code shows `reason` to the user as "Stop hook feedback", so the plain sentence goes first and the
    # instruction to the agent is one short line in the same language.
    if zh:
        ask = ("给助手：请立即执行对应操作（运行测试 / 构建 / 渲染 / 推送 / 发送 / 保存 / 查证）并报告真实输出；无法执行时，把该句改为「已修改，尚未验证」。"
               "回复第一行用加粗写明：被拦截的原因和补跑结果。")
    else:
        ask = ("To the agent: do it now (run the tests / build / render / push / send / save / look it up) and report the real output, or rewrite the sentence as "
               "unverified. Start your reply with one bold line: why you were stopped and what the check returned.")
    return agents.emit(agent, "stop", plain, ask)


TEST_LIKE = re.compile("|".join(p.pattern for k, p in rules.VERIFY.items() if k in ("test", "build")), re.I)
READ_ONLY = re.compile(r"(gh (run|pr) (view|list|watch|checks)|statusCheckRollup|^\s*(?:pip3? (?:list|show|freeze)|npm (?:ls|list)|uv pip (?:list|show))\b)", re.I)   # reading CI status/logs: the exit code does not carry the result


QUOTED = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'")
NOT_A_RUN = rules.NOT_A_RUN
GROUP_PIPE = re.compile(r"\{(?P<body>[^{}]*)\}(?:\s*\d?>(?:&[\d-])?)*\s*\|&?\s*(?P<pipe>[^;&|]+)")   # a `{ ...; }` group piped into another command; a target fd only follows `&`, so `9>9>...` has one parse and cannot backtrack exponentially
ENV_ASSIGN = re.compile(r"^(?:\s*\w+=\S*\s+)+")   # leading `VAR=value ` assignments; a quoted value is already blanked by QUOTED
RUNNER = re.compile(r"\s*(?:\w+=\S+\s+)*(?:\S*/)?(?:python3?|uv|poetry|hatch|pipenv|node|npx|bun|deno|go|bash|sh|zsh|make|ruby|bundle|php|dotnet|swift|cargo)\b")
SHELL_INLINE = re.compile(r"\s*(?:\S*/)?(?:bash|sh|zsh|dash)\s+(?:-\S+\s+)*?-[a-z]*c\b")   # `bash -c "..."`, `bash -e -lc "..."`: the quoted text runs
SHELL_HEREDOC = re.compile(r"^\s*(?:\S*/)?(?:bash|sh|zsh|dash)\b[^<\n]*<<")                 # `bash <<'EOF'`: the heredoc body runs
STAGE_PREFIX = re.compile(r"^\s*(?:(?:\w+=\S*|time|nice|nohup|xargs(?:\s+-\S+)*|timeout\s+\S+|env)\s+)+")   # wrappers in front of the command that runs


def _runs_check(t: str) -> bool:
    """True when the segment executes a test/build tool, not when a tool or script name only appears as an argument (`sed -n 1,60p src/eval.py`)."""
    m = TEST_LIKE.search(t)
    if not m:
        return False
    hit = m.group(0)
    if "/" in hit or re.search(r"\.(py|go|ts|js|rb|sh)$", hit):
        return bool(RUNNER.match(t))
    return True


# The pre-command check only looks at tools that print a pass/fail verdict, and only refuses a pipe that keeps that verdict
# from the agent: cutting the end of the output, discarding it, filtering out the summary, or (for runners that print one
# result per package or suite) keeping only the last lines. `pytest | tail` keeps the summary line, so it is left alone;
# the stop check still reads that line before the agent may say the tests pass.
_PM_TEST = r"(?:npm|pnpm|yarn|bun)\b[^|;&]*?\s(?:run\s+)?test\b(?![-.\w/])"   # npm test, pnpm --filter web test, yarn workspace web test
_MAKE = r"(?<![\w./-])make(?![\w.-])"
PRE_TEST = re.compile(r"(\bpytest\b|\bpy\.test\b|-m pytest|-m unittest|\bnpm t\b|\bcargo t\b|\bbazel test\b|\bgotestsum\b|\bsbt\b[^|;&]*\btest\b|\bdart test\b|\btox\b|\bnox\b|hatch (?:run )?test|pdm (?:run )?test|" + _PM_TEST + r"|deno test|\bjest\b|\bvitest\b|\bmocha\b|playwright test|cypress run"
                      r"|node\s+(?:-\S+\s+)*--test\b|\bgo test\b|cargo (?:test|nextest)|mvnw?\b[^|;&]*\s(?:test|verify)\b|gradlew?\b[^|;&]*\s(?:test|check)\b|dotnet test|swift test|xcodebuild test|flutter test|mix test"
                      r"|\brspec\b|rake test|\bphpunit\b|\bpest\b|\bctest\b|" + _MAKE + r"(?:\s+-[-\w=]+)*\s+(?:test|check)\b|manage\.py test|rails test|artisan test|\bjust test\b)", re.I)
# Runners that keep going after a failing package and do not repeat it at the end. Go, Cargo and make print the
# failure again last (`FAIL`, `error: test failed`, `make: *** ... Error`), so `| tail` keeps it and is not refused.
PRE_MULTI = re.compile(r"(?:npm|yarn)\b[^|;&]*\s(?:--workspaces\b|-ws\b)|\s--no-bail\b|yarn workspaces foreach", re.I)
PRE_BUILD = re.compile(r"((?:npm|pnpm|yarn)\b[^|;&]*?\s(?:run\s+)?build\b(?![-.\w/])|vite build|next build|mvnw?\b[^|;&]*\s(?:compile|package)\b|gradlew?\b[^|;&]*\s(?:build|assemble)\b"
                       r"|dotnet build|xcodebuild\b(?![^|;&]*\s-(?:list|showsdks|showBuildSettings|showdestinations|version|help|usage)\b)|docker build"
                       r")", re.I)
# Compilers print each error as it happens, so the start of the output shows them: `| head` keeps the result, like a linter.
PRE_COMPILE = re.compile(r"(cargo (?:build|check)\b|\bgo build\b|swift build|" + _MAKE + r"(?!(?:\s+-[-\w=]+)*\s+(?:-n\b|--dry-run|--just-print|clean|distclean|install|uninstall|help|fmt|format|run|dev|serve|start|watch|docs?|migrate|deploy|publish|up|down|logs|shell|lint|typecheck|test|check)\b))", re.I)
PRE_LINT = re.compile(r"(\bruff\b|\bmypy\b|\bpyright\b|\beslint\b|\bflake8\b|\bpylint\b|black --check|isort --check|\bbiome\b|prettier --check|\brubocop\b|\bphpstan\b|\bpsalm\b|\bshellcheck\b|golangci-lint|staticcheck|\btsc\b"
                      r"|\bgo vet\b|cargo clippy\b|" + _MAKE + r"(?:\s+-[-\w=]+)*\s+(?:lint|typecheck)\b|(?:npm|pnpm|yarn)\b[^|;&]*?\s(?:run\s+)?(?:lint|typecheck|type-check)\b)", re.I)
PRE_EXTRA = None   # the user's `verify_commands`, set by config.apply
NOT_A_CHECK = re.compile(r"^\s*(?:brew|cargo install|go install|gem install|uvx|pipx run|pgrep|pkill|git (?:show|blame|grep|cat-file|ls-files|log|diff))\b")
SEVERITY = {"keep": 0, "select": 0, "tail": 1, "filter": 2, "count": 3, "head": 4, "silent": 5}   # "select": a filter that keeps the failure lines
# Lines a test, build or lint run prints when something failed; a grep that keeps one of these keeps the verdict.
VERDICT_SAMPLES = [
    "=========== 1 failed, 2 passed in 0.12s ===========",
    "=========== 1 failed, 2 passed, 1 warning in 0.12s ===========",
    "FAILED tests/test_a.py::test_x - assert 1 == 2",
    "Tests:       1 failed, 2 passed, 3 total",
    " Test Files  1 failed | 2 passed (3)",
    "      Tests  1 failed | 2 passed (3)",
    "3 examples, 1 failure",
    "Tests run: 3, Failures: 1, Errors: 0, Skipped: 0",
    "[ERROR] Tests run: 3, Failures: 1, Errors: 0, Skipped: 0",
    "test result: FAILED. 2 passed; 1 failed; 0 ignored",
    "FAIL\tgithub.com/acme/app/pkg\t0.012s",
    "--- FAIL: TestPrice (0.00s)",
    "error: test failed, to rerun pass `--lib`",
    "  1 failing",
    "FAILED (failures=1)",
    "Tests: 3, Assertions: 3, Failures: 1.",
    "# fail 1",
    "BUILD FAILED",
    "make: *** [test] Error 1",
    "error[E0308]: mismatched types",
    "src/app.ts(3,7): error TS2322: Type 'string' is not assignable to type 'number'.",
    "Found 3 errors.",
    "Failed!  - Failed:     1, Passed:     3, Skipped:     0, Total:     4, Duration: 12 ms",
    "Total tests: 4",
    "     Failed: 1",
    "=================================== FAILURES ===================================",
]
GREP_NAMES = {"grep", "egrep", "fgrep", "rg", "ag", "ack"}


def _stage_kind(stage: str):
    """What a pipeline stage runs: "test", "multi" (a runner that does not repeat an early failure at the end), "build", "lint", or None."""
    bare = STAGE_PREFIX.sub("", ENV_ASSIGN.sub("", stage))
    word = re.sub(r"^(\s*)\S*/(?=[^\s/]+(?:\s|$))", r"\1", bare)   # `/path/.venv/bin/pip install pytest` is pip
    if READ_ONLY.search(word) or rules.NON_VERIFY_VERB.match(word) or NOT_A_CHECK.match(word) or re.match(r"\s*git (commit|push|tag|add)\b", word):
        return None   # `grep pytest log`, `gh repo edit --add-topic pytest`, `git show HEAD:tox.ini`, `brew install ruff`
    if NOT_A_RUN.search(bare):
        return None   # `pytest --collect-only`, `--version`, `cargo test --no-run`: nothing can fail
    if PRE_TEST.search(bare) or (PRE_EXTRA is not None and PRE_EXTRA.search(bare)):
        return "multi" if PRE_MULTI.search(bare) else "test"
    if PRE_LINT.search(bare) or PRE_COMPILE.search(bare):
        return "lint"
    if PRE_BUILD.search(bare):
        return "build"
    return None


def _grep_parts(stage: str):
    """(name, flags, patterns) of a grep-like command; patterns is None when they cannot be known (`-f file`)."""
    import shlex
    try:
        toks = shlex.split(STAGE_PREFIX.sub("", stage), posix=True)
    except ValueError:
        toks = STAGE_PREFIX.sub("", stage).split()
    if not toks:
        return "", set(), None
    name = os.path.basename(toks[0])
    flags, pats, i = set(), [], 1
    long_flags = {"--count": "c", "--quiet": "q", "--silent": "q", "--files-with-matches": "l", "--files-without-match": "L",
                  "--invert-match": "v", "--ignore-case": "i", "--fixed-strings": "F", "--extended-regexp": "E", "--only-matching": "o",
                  "--word-regexp": "w", "--line-regexp": "x", "--perl-regexp": "E"}
    while i < len(toks):
        t = toks[i]
        if t == "--":
            if not pats and i + 1 < len(toks):
                pats.append(toks[i + 1])
            break
        if t.startswith("--"):
            key = t.split("=", 1)[0]
            if key == "--regexp":
                pats.append(t.split("=", 1)[1] if "=" in t else (toks[i + 1] if i + 1 < len(toks) else ""))
                i += 1 if "=" in t else 2
                continue
            if key == "--file":
                return name, flags, None
            if key in long_flags:
                flags.add(long_flags[key])
            i += 1
            continue
        if t.startswith("-") and len(t) > 1 and not pats:
            j = 1
            while j < len(t):
                c = t[j]
                if c in "ABCmefg":   # options that take a value
                    val = t[j + 1:] or (toks[i + 1] if i + 1 < len(toks) else "")
                    if not t[j + 1:]:
                        i += 1
                    if c == "e":
                        pats.append(val)
                    if c == "f":
                        return name, flags, None
                    break
                flags.add(c)
                j += 1
            i += 1
            continue
        if not pats:
            pats.append(t)
        i += 1
    return name, flags, pats


def _py_regex(pattern: str, flags: set, name: str) -> str:
    if "F" in flags or name == "fgrep":
        return re.escape(pattern)
    out = pattern.replace("[[:digit:]]", r"\d").replace("[[:space:]]", r"\s").replace("[[:alpha:]]", "[A-Za-z]") \
                 .replace("[[:upper:]]", "[A-Z]").replace("[[:lower:]]", "[a-z]").replace("[[:alnum:]]", "[A-Za-z0-9]")
    if "E" in flags or name in ("egrep", "rg", "ag", "ack"):
        return out
    res, k = [], 0   # basic regex: `\|` `\(` `\+` are operators, bare `|` `(` `+` are literal characters
    while k < len(out):
        ch = out[k]
        if ch == "\\" and k + 1 < len(out) and out[k + 1] in "|()+?{}":
            res.append(out[k + 1]); k += 2; continue
        res.append("\\" + ch if ch in "|()+?{}" else ch)
        k += 1
    return "".join(res)


def _grep_keeps_verdict(stage: str):
    """For a grep stage: "silent", "count", "filter" or "keep", judged by running its pattern over typical failure lines."""
    name, flags, pats = _grep_parts(stage)
    if flags & {"q", "l", "L"}:
        return "silent"
    if "c" in flags:
        return "count"
    if not pats:
        return "keep"   # patterns we cannot see: give it the benefit of the doubt
    try:
        rx = re.compile("|".join(_py_regex(p, flags, name) for p in pats), re.I if "i" in flags else 0)
    except re.error:
        return "keep"
    if "x" in flags:
        hit = any(rx.fullmatch(line.strip()) for line in VERDICT_SAMPLES)
    else:
        hit = any(rx.search(line) for line in VERDICT_SAMPLES)
    if "v" in flags:
        return "filter" if hit else "keep"   # `grep -v warning` drops "1 failed, 2 passed, 1 warning"
    return "select" if hit else "filter"


def _consumer(stage: str) -> str:
    """How a command after the pipe treats the output it receives."""
    s = STAGE_PREFIX.sub("", stage.strip().lstrip("{( ")).strip()   # `| { head -5; }` is still head
    parts = s.split()
    name = os.path.basename(parts[0].strip("\"'")) if parts else ""
    rest = s[len(parts[0]):] if parts else ""
    if name == "awk" and re.search(r"\bNR\s*(?:<=?|==)\s*\d+", rest):
        return "head"   # `awk 'NR<=10'`
    if name in ("jq", "awk") and re.search(r"fail|error|FAIL", rest):
        return "select"   # `jq 'select(.Action=="fail")'`
    if name == "head":
        return "head"
    if name == "sed":
        if "$" in rest:
            return "keep"   # `sed -n '/FAILURES/,$p'` prints through to the end
        return "head" if re.search(r"(?:^|\s)-n\b|\b\d+q\b", rest) else "keep"
    if name == "wc":
        return "count"
    if name in GREP_NAMES:
        return _grep_keeps_verdict(s)
    if name == "tail":
        return "tail"
    return "keep"   # tee, cat, sort, less, tr, jq, ...: the output still shows the result


def _hides(kind: str, chain: list) -> bool:
    """chain: consumer kinds in pipeline order after the verdict-printing stage."""
    worst = max(chain, key=SEVERITY.get)
    if worst == "head" and "select" in chain[: chain.index("head")]:
        return False   # `pytest | grep -A20 FAILURES | head`, `cargo build | grep '^error' | head`: the failures are what is left
    if kind in ("test", "multi"):
        return worst in ("silent", "head", "count", "filter") or (worst == "tail" and kind == "multi")
    if kind == "build":
        return worst in ("silent", "head")
    return kind == "lint" and worst == "silent"


def _expand_groups(cmd: str) -> str:
    """Rewrite `{ a; b; } | tail` as `a | tail ; b | tail`, looking only outside quotes (a release note may quote such a group)."""
    unquoted = QUOTED.sub(lambda m: " " * len(m.group(0)), cmd)
    for m in reversed(list(GROUP_PIPE.finditer(unquoted))):
        body, pipe = cmd[m.start("body"):m.end("body")], cmd[m.start("pipe"):m.end("pipe")]
        cmd = cmd[:m.start()] + " ; ".join(f"{g.text} | {pipe}" for g in rules.segments(body)) + cmd[m.end():]
    return cmd


def find_hidden_status(cmd: str):
    """The first pipeline that keeps a test or build result from the agent, as (segment, next command, why), or None.

    Not refused: a pipe that leaves the verdict visible (`pytest | tail`, `| tee log`, `grep -E "passed|failed"`), a pipeline
    that turns on pipefail before the pipe (`set -o pipefail`, `set -euo pipefail`, `bash -o pipefail -c`, zsh `setopt pipefail`)
    or reads each stage's status (`${PIPESTATUS[0]}`), and any tool that prints no verdict.
    """
    if re.search(r"\$\{?(?:PIPESTATUS|pipestatus)\b", rules._strip_comments(cmd)):
        return None
    for body in re.findall(r"\$\(([^()]*)\)", cmd):   # `result=$(pytest -q | head -5)`
        hit = find_hidden_status(body)
        if hit:
            return hit
    pf = False
    for seg in rules.segments(_expand_groups(cmd)):
        if seg.heredoc:
            head, _, rest = seg.text.partition("\n")
            if SHELL_HEREDOC.match(head) and not pf and not rules.PIPEFAIL_ON.search(head):
                hit = find_hidden_status(rest.rsplit("\n", 1)[0] if "\n" in rest else "")
                if hit:
                    return hit
            continue
        raw = rules.COMMIT_MSG.sub(lambda m: " " * len(m.group(0)), seg.text)   # text quoted in a commit message is not a command
        blank = raw if SHELL_INLINE.match(raw) else QUOTED.sub(lambda m: " " * len(m.group(0)), raw)   # quoted text is an argument
        cuts = [0] + [x for m in re.finditer(r"(?<!\|)\|&?(?!\|)", blank) for x in (m.start(), m.end())] + [len(raw)]
        stages = [(blank[cuts[i]:cuts[i + 1]], raw[cuts[i]:cuts[i + 1]]) for i in range(0, len(cuts) - 1, 2)]
        if len(stages) > 1 and not pf:
            for i, (st, _) in enumerate(stages[:-1]):
                if rules.PIPEFAIL_ON.search("|".join(x for x, _ in stages[:i + 1])):
                    break   # `bash -o pipefail -c "pytest | tail"`
                kind = _stage_kind(st)
                if not kind:
                    continue
                cons = [(_consumer(r), r) for _, r in stages[i + 1:]]
                chain = [c for c, _ in cons]
                if _hides(kind, chain):
                    how, culprit = max(cons, key=lambda c: SEVERITY[c[0]])
                    words = STAGE_PREFIX.sub("", culprit).strip().split()
                    pipe = os.path.basename(words[0].strip("\"'")) if words else "tail"
                    tool = " ".join(STAGE_PREFIX.sub("", ENV_ASSIGN.sub("", st)).split()[:2])
                    return raw.strip(), pipe or "tail", how, kind, tool
                break   # the first verdict-printing stage decides; later stages only consume its output
        if rules.PIPEFAIL_OFF.search(blank):
            pf = False
        elif rules.PIPEFAIL_ON.search(blank):
            pf = True
    return None


def pre_hook(data: dict | None = None, agent: str = "claude-code") -> dict | None:
    data = agents.normalize(agent, "pre", data if data is not None else _read_stdin())
    if data.get("tool_name") != "Bash":
        return None
    cfg = config.load(data.get("cwd") or None)
    config.apply(cfg)
    if cfg.get("strictness") == "lenient":
        return None
    cmd = (data.get("tool_input") or {}).get("command", "") or ""
    hit = find_hidden_status(cmd)
    if not hit:
        return None
    t, pipe, why, kind, tool = hit
    zh = _lang_zh(cfg, cmd)
    turn = None
    tp = data.get("transcript_path") or ""
    if tp and os.path.exists(tp):
        try:
            turns = agents.parser_for(agent, tail=True)(tp)
            turn = turns[-1] if turns else None
        except Exception:
            turn = None
    if turn is not None and not zh and cfg.get("language", "auto") == "auto":
        zh = _is_zh(turn.prompt)
    plain = _plain_pre(t, zh, _who_where(data, turn or Turn(session="live", index=0, version="", prompt="", agent=agent, model=str(data.get("model") or "")), zh), pipe=pipe, why=why, kind=kind, tool=tool)
    _record("pre", data, turn, plain, command=t)
    fix = (f"给助手：请重新运行并让输出末尾可见（去掉 `| {pipe}`，或改用 `| tail -n 40`），然后引用最后的汇总行。" if zh else
           f"To the agent: rerun it so the end of the output is visible (drop `| {pipe}`, or use `| tail -n 40`), then quote the final summary line.")
    return agents.emit(agent, "pre", plain, fix)


def errors_path() -> str:
    return os.path.join(os.path.expanduser("~/.honestly"), "hook-errors.log")


def run_hook(which: str, agent: str = "claude-code") -> int:
    """Entry point for the installed hooks. A bug in honestly must never block or slow the assistant: any exception is
    written to ~/.honestly/hook-errors.log (shown by `honestly doctor`) and the hook exits 0 with no output."""
    try:
        out = stop_hook(agent=agent) if which == "stop" else pre_hook(agent=agent)
    except Exception:
        import traceback, datetime
        try:
            os.makedirs(os.path.dirname(errors_path()), exist_ok=True)
            with open(errors_path(), "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} {which} {agent}\n{traceback.format_exc()}\n")
        except Exception:
            pass
        return 0
    if out:
        print(json.dumps(out, ensure_ascii=False))
    return 0


# ----------------------------------------------------------- guard install
def settings_path() -> str:
    """Claude Code's user settings; CLAUDE_CONFIG_DIR moves them, and Claude Code then reads hooks from there."""
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(base, "settings.json")


def _exe() -> str:
    """The honestly executable as the hooks should call it: absolute, quoted when the path has a space."""
    argv0 = sys.argv[0] if sys.argv else ""
    import ntpath, posixpath
    is_ours = os.path.splitext(re.split(r"[\\/]", argv0)[-1])[0] == "honestly"
    if is_ours and not (ntpath.isabs(argv0) or posixpath.isabs(argv0)):
        argv0 = os.path.abspath(argv0)   # hooks run from any cwd, so a relative .venv/bin/honestly would break
    exe = argv0 if is_ours else "honestly"   # Scripts\honestly.exe on Windows
    if WIN_PATH.match(exe):
        exe = exe.replace("\\", "/")   # the hook line is run by a POSIX shell (Git Bash on Windows), which would eat the backslashes
    if " " in exe:
        exe = f'"{exe}"'
    return exe


WIN_PATH = re.compile(r"^[A-Za-z]:\\")


def _entries():
    exe = _exe()
    return {
        "Stop": {"matcher": "", "hooks": [{"type": "command", "command": f"{exe} hook stop  # {MARK}", "timeout": 30}]},
        "PreToolUse": {"matcher": "Bash", "hooks": [{"type": "command", "command": f"{exe} hook pre  # {MARK}", "timeout": 10}]},
    }


def guard(action: str, dry_run: bool = False, agent: str = "claude-code") -> str:
    if agent == "all":
        return "\n".join(guard(action, dry_run, a) for a in agents.SUPPORTED)
    if agent != "claude-code":
        return agents.guard(agent, action, _exe(), dry_run)
    path = settings_path()
    try:
        cfg = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    except Exception as e:
        return _fail(action, f"honestly guard: cannot read {path}: {e}  (the file was left untouched)")
    if not isinstance(cfg, dict):
        return _fail(action, f"honestly guard: {path} is not a JSON object (the file was left untouched)")
    hooks = cfg.get("hooks") if isinstance(cfg.get("hooks"), dict) else {}
    installed = {ev: any(_ours(h) for g in groups_of(hooks, ev) for h in hooks_of(g)) for ev in hooks}
    if action == "status":
        on = [ev for ev, v in installed.items() if v]
        return f"honestly guard (Claude Code): {'installed for ' + ', '.join(on) if on else 'not installed'} ({path})"
    before = json.dumps(cfg, sort_keys=True)
    cfg["hooks"] = hooks
    if action == "install":
        for ev, entry in _entries().items():
            groups = [g for g in groups_of(hooks, ev) if not any(_ours(h) for h in hooks_of(g))]   # replace older entries (path or name may have changed)
            groups.append(entry)
            hooks[ev] = groups
    elif action == "uninstall":
        for ev in list(hooks):
            kept = [g for g in groups_of(hooks, ev) if not any(_ours(h) for h in hooks_of(g))]
            if kept:
                hooks[ev] = kept
            else:
                del hooks[ev]
    if not hooks:
        cfg.pop("hooks", None)
    if dry_run:
        return (f"honestly guard would write the following `hooks` section into {path} (a timestamped backup of the file is made first; "
                f"`honestly guard uninstall` removes exactly these entries):\n" + json.dumps({"hooks": hooks}, ensure_ascii=False, indent=2))
    if json.dumps(cfg, sort_keys=True) == before:
        return (f"honestly guard: already installed, nothing changed ({path})" if action == "install"
                else f"honestly guard: not installed, nothing to remove ({path})")
    config.write_json_atomic(path, cfg)
    return f"honestly guard: {action}ed → {path}"


def _fail(action: str, msg: str) -> str:
    """`status` reports a broken settings file; `install` / `uninstall` exit non-zero on it so scripts notice."""
    if action == "status":
        return msg
    raise SystemExit(msg)


def groups_of(hooks: dict, ev: str) -> list:
    gs = hooks.get(ev)
    return [g for g in gs if isinstance(g, dict)] if isinstance(gs, list) else []


def hooks_of(group: dict) -> list:
    hs = group.get("hooks")
    return [h for h in hs if isinstance(h, dict)] if isinstance(hs, list) else []
