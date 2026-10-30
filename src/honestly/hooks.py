"""Claude Code hooks: `honestly hook stop` and `honestly hook pre`, plus `honestly guard` install/uninstall.

Stop hook: if the reply the agent is about to send claims "tests pass / fixed / pushed ..." but
this turn's transcript shows no matching check after the last code edit, ask the agent to run it
(or say the work is unverified) before stopping. Fires once per turn (stop_hook_active guard).

PreToolUse hook (Bash): a test/check command piped through tail/head without `set -o pipefail`
reports tail's exit code, so a failing suite exits 0. The hook denies the call with a fix.
"""
from __future__ import annotations
import json
import os
import re
import sys
from . import rules, config, agents
from .audit import audit_turn
from .claude_code import Event, Turn, parse_session

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


def _is_zh(text: str) -> bool:
    return bool(CJK.search(text or "")) or os.environ.get("LANG", "").lower().startswith("zh")


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
    cwd = (data.get("cwd") or getattr(turn, "project", "") or "").rstrip("/\\")
    project = re.split(r"[\\/]", cwd)[-1] if cwd else ""
    topic = _topic(getattr(turn, "prompt", "") or "")
    if zh:
        where = (f"在「{project}」项目" if project else "") + (f"回复「{topic}」这个问题时" if topic else "")
        return who + (where or "")
    where = (f" in project {project}" if project else "") + (f', answering "{topic}"' if topic else "")
    return who + where


def _plain_stop(f, zh: bool, who: str = "") -> str:
    """What the user sees. No jargon: what the agent said, what it skipped, what happens next."""
    claim = re.sub(r"\s{2,}", " ", f.claim.strip().rstrip("。．.!！;；"))[:60]
    edited = (f.last_edit.splitlines()[0] if f.last_edit else "")
    edited = re.split(r"[\\/]", edited.split(":", 1)[-1].strip())[-1][:40] if edited else ""
    if zh:
        where = f"改完 {edited} 之后" if edited else "改完代码之后"
        if not edited:
            return f"⚠️ honestly 拦了一下：{who or 'AI'}说「{claim}」，但这一轮的记录里没有做这件事的动作。已经要求它先做了再说。"
        return f"⚠️ honestly 拦了一下：{who or 'AI'}说「{claim}」，但{where}没有跑过任何检查。已经要求它先跑了再说。"
    where = f"after editing {edited}" if edited else "after editing the code"
    if not edited:
        return f'⚠️ honestly stepped in: {who or "the agent"} said "{claim}" but nothing in this turn did that. It has been told to do it first.'
    return f'⚠️ honestly stepped in: {who or "the agent"} said "{claim}" but ran no check {where}. It has been told to run one first.'


def _pipe_name(cmd: str) -> str:
    m = rules.PIPE_SWALLOW.search(cmd)
    return m.group(1) if m else "tail"


def _plain_pre(cmd: str, zh: bool, who: str = "") -> str:
    m = re.search(r"(pytest|npm test|npm run \w+|cargo test|go test|make \w+|yarn test|pnpm test|mvn \w+|gradle \w+|ruff|mypy|tsc|eslint)", cmd)
    pipe = _pipe_name(cmd)
    if zh:
        what = f"把 {m.group(1)} 的结果接进了 {pipe}" if m else f"把检查命令的结果接进了 {pipe}"
        return f"⚠️ honestly 拦了一下：{who or 'AI'}{what}，失败也会显示得像通过。已经要求它改成能看到真实结果的写法。"
    what = f"piped {m.group(1)} through {pipe}" if m else f"piped a check through {pipe}"
    return f"⚠️ honestly stepped in: {who or 'the agent'} {what}, so a failure would look like a pass. It has been told to run it so the real result is visible."


def _notify(title: str, body: str) -> None:
    """Desktop notification, opt-in via HONESTLY_NOTIFY=1 (hooks have no terminal; this reaches people who never look at one)."""
    if os.environ.get("HONESTLY_NOTIFY") != "1" and not os.path.exists(notify_flag_path()):
        return
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
        zh = _lang_zh(config.load(), os.environ.get("LANG", ""))
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
        lines = [f"honestly guard：{window}拦了 {n} 次",
                 f"  {stop:3}  说「做完了」（测试通过、修好了、已发送、已部署、已保存…）但记录里没做",
                 f"  {pre:3}  检查命令的结果被截断（接了 tail/head/grep 又没加 pipefail）", "", "按项目："]
    else:
        lines = [f"honestly guard: {n} catch{'es' if n != 1 else ''} in the {window}",
                 f"  {stop:3}  said \"done\" (tests pass, fixed, sent, deployed, saved...) with nothing behind it",
                 f"  {pre:3}  ran a check with its result cut off (piped through tail/head/grep)", "", "By project:"]
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
        lines.append(f"可以直接发的一句话：honestly 在{window}拦住了我的 AI 助手 {n} 次，都是没检查就说「做完了」。")
        lines.append("拦错了？honestly feedback 一条命令整理成反馈。")
    else:
        lines.append(f"One line to share: honestly stopped my coding agent {n} time{'s' if n != 1 else ''} in the {window} from saying \"done\" without checking.")
        lines.append("A catch looks wrong? `honestly feedback` turns it into an issue-ready text.")
    return "\n".join(lines)


def _short(path: str) -> str:
    return re.split(r"[\\/]", (path or "").rstrip("/\\"))[-1] if path else ""


def stop_hook(data: dict | None = None, agent: str = "claude-code") -> dict | None:
    data = agents.normalize(agent, "stop", data if data is not None else _read_stdin())
    if data.get("stop_hook_active"):
        return None
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
        elif os.path.getsize(path) == 0:
            _note("stop", f"transcript is empty, only the final message was checked: {path}")
    elif path:
        _note("stop", f"transcript_path does not exist, only the final message was checked: {path}")
    if turn is None:
        turn = Turn(session="live", index=0, version="", prompt="", agent=agent, model=str(data.get("model") or ""))
    if final and not any(e.kind == "text" and final[:80] in e.text for e in turn.events):
        turn.events.append(Event("text", text=final))
    bad = [f for f in audit_turn(turn, prev) if f.verdict in config.blocked_verdicts(cfg)]
    if not bad:
        return None
    zh = _lang_zh(cfg, bad[0].claim)
    plain = _plain_stop(bad[0], zh, _who_where(data, turn, zh))
    if len(bad) > 1:
        plain += f"（这条回复里还有 {len(bad) - 1} 句同样没有依据。）" if zh else f" ({len(bad) - 1} more sentence{'s' if len(bad) > 2 else ''} in this reply have the same problem.)"
    _record("stop", data, turn, plain, claim=bad[0].claim, reason=bad[0].reason, tools=bad[0].tools_after_edit)
    _notify("honestly", plain)
    # Claude Code shows `reason` to the user as "Stop hook feedback", so the plain sentence goes first and the
    # instruction to the agent is one short line in the same language.
    if zh:
        ask = ("给助手：现在就做那件事（跑测试 / 构建 / 渲染 / 推送 / 发送 / 保存 / 查证）并报告真实输出，做不了就把那句话改成「已修改，尚未验证」。"
               "回复第一行用加粗写明：被拦的原因和补跑的结果。")
    else:
        ask = ("To the agent: do it now (run the tests / build / render / push / send / save / look it up) and report the real output, or rewrite the sentence as "
               "unverified. Start your reply with one bold line: why you were stopped and what the check returned.")
    return agents.emit(agent, "stop", plain, ask)


TEST_LIKE = re.compile("|".join(p.pattern for k, p in rules.VERIFY.items() if k in ("test", "build")), re.I)
READ_ONLY = re.compile(r"(gh (run|pr) (view|list|watch|checks)|statusCheckRollup|^\s*(?:pip3? (?:list|show|freeze)|npm (?:ls|list)|uv pip (?:list|show))\b)", re.I)   # reading CI status/logs: the exit code does not carry the result


QUOTED = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'")
NOT_A_RUN = re.compile(r"(--collect-only|--co\b|--version|--help|(?:^|\s)-h\b|--list-tests|--list|--dry-run|--showconfig)")
RUNNER = re.compile(r"\s*(?:\w+=\S+\s+)*(?:\S*/)?(?:python3?|uv|poetry|hatch|pipenv|node|npx|bun|deno|go|bash|sh|zsh|make|ruby|bundle|php|dotnet|swift|cargo)\b")


def _runs_check(t: str) -> bool:
    """True when the segment executes a test/build tool, not when a tool or script name only appears as an argument (`sed -n 1,60p src/eval.py`)."""
    m = TEST_LIKE.search(t)
    if not m:
        return False
    hit = m.group(0)
    if "/" in hit or re.search(r"\.(py|go|ts|js|rb|sh)$", hit):
        return bool(RUNNER.match(t))
    return True


def pre_hook(data: dict | None = None, agent: str = "claude-code") -> dict | None:
    data = agents.normalize(agent, "pre", data if data is not None else _read_stdin())
    if data.get("tool_name") != "Bash":
        return None
    cfg = config.load(data.get("cwd") or None)
    config.apply(cfg)
    if cfg.get("strictness") == "lenient":
        return None
    cmd = (data.get("tool_input") or {}).get("command", "") or ""
    for seg in rules.segments(cmd):
        t = rules.COMMIT_MSG.sub("", seg.text)   # text quoted in a commit message is not a command
        if not re.match(r"\s*(?:\S*/)?(?:bash|sh|zsh|dash)\s+-l?c\b", t):
            t = QUOTED.sub(" ", t)   # `codex exec "run pytest | tail"`: a quoted test command is an argument, not a pipeline that runs here
        if seg.heredoc or not _runs_check(t) or READ_ONLY.search(t) or rules.NON_VERIFY_VERB.match(t) or re.match(r"\s*git (commit|push|tag|add)\b", t):
            continue   # `cat build.log | tail` mentions a test tool but runs none
        if NOT_A_RUN.search(t):
            continue   # listing tests or printing a version is not a run whose result could be hidden
        if rules.PIPE_SWALLOW.search(t) and "pipefail" not in cmd:
            zh = _lang_zh(cfg, cmd, os.environ.get("LANG", ""))
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
            plain = _plain_pre(t, zh, _who_where(data, turn or Turn(session="live", index=0, version="", prompt="", agent=agent, model=str(data.get("model") or "")), zh))
            _record("pre", data, turn, plain, command=t)
            _notify("honestly", plain)
            pipe = _pipe_name(t)
            fix = (f"给助手：把命令前面加上 `set -o pipefail;`，或者去掉 `| {pipe}` 直接读最后一行汇总。" if zh else
                   f"To the agent: prefix the command with `set -o pipefail;`, or drop the `| {pipe}` and read the summary line.")
            return agents.emit(agent, "pre", plain, fix)
    return None


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
    return os.path.expanduser("~/.claude/settings.json")


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
    if os.path.exists(path):
        import shutil, time
        shutil.copy(path, path + ".bak-honestly-" + time.strftime("%Y%m%d%H%M%S"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
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
