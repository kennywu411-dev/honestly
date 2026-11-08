"""`honestly doctor` (is the install working?) and `honestly feedback` (turn a wrong catch into an issue-ready text)."""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
import tempfile
import urllib.parse

from . import __version__, config, guardfile, hookline, hooks
from .programs import program
from .redact import redact
from .claude_code import iter_sessions, parse_session, projects_root

REPO = "https://github.com/kennywu411-dev/honestly"


# ------------------------------------------------------------------- doctor
def _our_entries(settings: dict, flat: bool = False) -> list:
    """The hook entries guard installed, one per distinct program."""
    seen, out = set(), []
    for h in guardfile.commands(settings, flat):
        exe = hookline.parse_entry(h).exe
        if exe not in seen:
            seen.add(exe)
            out.append(h)
    return out


_STOP_WORD = re.compile(r"(\shook\s+)stop(?=(?:\s+--agent\s+\S+)?(?:\s+#.*)?\s*$)")


def _hook_runs(hook: dict) -> tuple:
    """Run the installed entry the way the assistant will, with an empty event: (ran, detail). A shell-form line goes through `sh -c`
    (Git Bash on Windows provides it), an exec-form entry starts directly."""
    import subprocess
    if isinstance(hook.get("args"), list):
        argv = [hook["command"]] + ["pre" if a == "stop" else a for a in hook["args"]]
    else:
        sh = None
        for name in ("sh", "bash"):
            try:
                sh = shutil.which(program(name))
            except FileNotFoundError:
                continue
            if sh:
                break
        if not sh:
            return (None, "no sh/bash found to try the hook line")
        argv = [sh, "-c", _STOP_WORD.sub(r"\1pre", hook["command"], count=1)]
    try:
        r = subprocess.run(argv, input=b"{}", capture_output=True, timeout=20)
    except Exception as e:
        return (False, f"{e.__class__.__name__}: {e}")
    err = r.stderr.decode("utf-8", "ignore").strip().splitlines()
    return (r.returncode == 0, err[-1] if err and r.returncode != 0 else "")


def _shown(hook: dict) -> str:
    return hook["command"].split("  #")[0] + (" " + " ".join(hook["args"]) if isinstance(hook.get("args"), list) else "")


def _fake_session(d: str, rows: list) -> str:
    tp = os.path.join(d, f"s{len(os.listdir(d))}.jsonl")
    with open(tp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return tp


def self_test() -> list:
    """Feed guard two fake turns and see whether it blocks: a code claim ('All tests pass.' right after an edit, no test
    run) and a non-code claim ('I've sent you the file.' with no send tool). Returns [(name, blocked, message)].
    It tests the program, not the user's choices, so the default settings apply: a lenient config is not a broken install."""
    with tempfile.TemporaryDirectory(prefix="honestly-doctor-") as d:
        return _self_test_in(d)


def _self_test_in(d: str) -> list:
    ts = "2026-01-01T00:00:0{}Z"
    code = _fake_session(d, [
        {"type": "user", "message": {"role": "user", "content": "fix the bug"}, "origin": {"kind": "human"}, "cwd": d, "timestamp": ts.format(0)},
        {"type": "assistant", "message": {"role": "assistant", "model": "doctor", "content": [
            {"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/honestly-selftest/src/app.py", "old_string": "a", "new_string": "b"}}]}, "cwd": d, "timestamp": ts.format(1)},   # not under a temp dir: edits there never count
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}, "cwd": d, "timestamp": ts.format(2)},
        {"type": "assistant", "message": {"role": "assistant", "model": "doctor", "content": [{"type": "text", "text": "Fixed. All tests pass."}]}, "cwd": d, "timestamp": ts.format(3)},
    ])
    noncode = _fake_session(d, [
        {"type": "user", "message": {"role": "user", "content": "send me the report"}, "origin": {"kind": "human"}, "cwd": d, "timestamp": ts.format(0)},
        {"type": "assistant", "message": {"role": "assistant", "model": "doctor", "content": [
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls reports/"}}]}, "cwd": d, "timestamp": ts.format(1)},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "report.pdf"}]}, "cwd": d, "timestamp": ts.format(2)},
        {"type": "assistant", "message": {"role": "assistant", "model": "doctor", "content": [{"type": "text", "text": "I've sent you the report."}]}, "cwd": d, "timestamp": ts.format(3)},
    ])
    saved = (hooks.catches_path, hooks._notify, config.load)
    hooks.catches_path = lambda: os.path.join(d, "catches.jsonl")   # never pollute the real log
    hooks._notify = lambda *a, **k: None
    config.load = lambda cwd=None: dict(config.DEFAULTS)
    results = []
    try:
        for name, tp, last in (("code", code, "Fixed. All tests pass."), ("non-code", noncode, "I've sent you the report.")):
            try:
                out = hooks.stop_hook({"transcript_path": tp, "cwd": d, "last_assistant_message": last, "stop_hook_active": False})
            except Exception as e:
                out = {"error": str(e)}
            results.append((name, bool(out and out.get("decision") == "block"), (out or {}).get("systemMessage", "") or str(out)))
    finally:
        hooks.catches_path, hooks._notify, config.load = saved
        config.apply(config.load())
    return results


def _check_hook_entries(entries: list, lines: list, problems: list, L, agent: str, marks: tuple) -> None:
    """Can each hook entry's program start, and does the first line really run?"""
    ok, bad = marks
    install = "honestly guard install" + (f" --agent {agent}" if agent else "")
    for h in entries:
        exe = hookline.parse_entry(h).exe
        if hookline.runnable(exe):
            lines.append(f"{ok}" + L(f"hook command exists: {exe}", f"hook 命令存在：{exe}"))
        else:
            lines.append(f"{bad}" + L(f"hook command cannot start: {exe}", f"hook 命令启动不了：{exe}"))
            problems.append(L(f"{agent or 'Claude Code'}: the hook points to {exe}, which cannot start; run: {install}", f"{agent or 'Claude Code'}：hook 指向的 {exe} 启动不了；运行：{install}"))
    for h in entries[:1]:
        ran, detail = _hook_runs(h)
        if ran is None:
            continue
        lines.append(f"{ok if ran else bad}" + L(f"hook line runs through the shell: {_shown(h)}", f"hook 命令行能在 shell 里跑：{_shown(h)}") + (f"  ({detail})" if detail else ""))
        if not ran:
            problems.append(L(f"the hook line fails when a shell runs it (the assistant would skip the guard silently); run `{install}` again and send this output with `honestly feedback --issue`",
                              f"hook 命令行在 shell 里跑不起来（助手会静默跳过 guard）；重新 {install}，并用 honestly feedback --issue 发来这段输出"))


def doctor(zh: bool | None = None, with_problems: bool = False):
    """The report as text; with_problems=True returns (text, problems) so the CLI can exit non-zero."""
    if zh is None:
        zh = hooks._lang_zh(config.load(), "")
    L = lambda en, cn: cn if zh else en
    ok, warn, bad = "  ok   ", "  warn ", "  FAIL "
    lines = [f"honestly {__version__} doctor"]
    problems = []
    py = ".".join(map(str, sys.version_info[:3]))
    lines.append(f"{ok if sys.version_info >= (3, 9) else bad}Python {py} · {platform.system()} {platform.release()}")
    if sys.version_info < (3, 9):
        problems.append(L("Python 3.9 or newer is required", "需要 Python 3.9 或更新"))
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    lines.append(f"{ok if 'utf' in enc else warn}" + L(f"terminal encoding {enc or 'unknown'}", f"终端编码 {enc or '未知'}")
                 + ("" if "utf" in enc else L("  (not UTF-8: honestly re-encodes its own output, other tools may show garbled text)", "  （不是 UTF-8：honestly 自己的输出会转码，其他工具可能乱码）")))
    pp = config.project_path(None)
    relaxed = config.project_relaxes(None)
    if relaxed and config.is_trusted(pp):
        lines.append(f"{warn}" + L(f"this project's {pp} relaxes the rules, and you trusted it: {', '.join(relaxed)}", f"本项目的 {pp} 放宽了规则，你已信任它：{'、'.join(relaxed)}"))
    elif relaxed:
        lines.append(f"{warn}" + L(f"this project's {pp} relaxes the rules ({', '.join(relaxed)}); ignored until you run honestly trust",
                                   f"本项目的 {pp} 想放宽规则（{'、'.join(relaxed)}），已忽略；运行 honestly trust 才会生效"))
    for p in config.problems():
        lines.append(f"{warn}{p}")
        problems.append(L(f"fix or delete it: {p}", f"修复或删除它：{p}"))
    sp = hooks.settings_path()
    settings = {}
    if os.path.exists(sp):
        try:
            with open(sp, encoding="utf-8") as fh:
                settings = json.load(fh)
            if isinstance(settings, dict):
                lines.append(f"{ok}" + L(f"Claude Code settings readable: {sp}", f"Claude Code 设置文件可读：{sp}"))
            else:
                settings = {}
                lines.append(f"{bad}" + L(f"settings file is not a JSON object: {sp}", f"设置文件不是 JSON 对象：{sp}"))
                problems.append(L(f"fix the JSON in {sp} (a backup may exist next to it)", f"修复 {sp} 里的 JSON（旁边可能有备份）"))
        except Exception as e:
            lines.append(f"{bad}" + L(f"settings file is not valid JSON: {sp} ({e})", f"设置文件不是合法 JSON：{sp}（{e}）"))
            problems.append(L(f"fix the JSON in {sp} (a backup may exist next to it)", f"修复 {sp} 里的 JSON（旁边可能有备份）"))
    else:
        lines.append(f"{warn}" + L(f"no Claude Code settings file at {sp}", f"没有 Claude Code 设置文件：{sp}"))
    from . import agents as _ag
    _hk = settings.get("hooks") if isinstance(settings.get("hooks"), dict) else {}
    installed = set(guardfile.hook_events(settings))
    other_agents = [a for a in ("codex", "cursor", "gemini") if _ag.installed(a)]
    if {"Stop", "PreToolUse"} <= installed:
        lines.append(f"{ok}" + L("guard hooks installed (Stop, PreToolUse)", "guard 的两个 hook 已装（Stop、PreToolUse）"))
        if not any("PowerShell" in str(g.get("matcher") or "") for g in hooks.groups_of(_hk, "PreToolUse") if any(hooks._ours(h) for h in hooks.hooks_of(g))):
            lines.append(f"{warn}" + L("the pre hook does not cover Claude Code's PowerShell tool, the main shell on Windows; run: honestly guard install",
                                       "pre hook 没覆盖 Claude Code 的 PowerShell 工具（Windows 上的主要 shell）；运行：honestly guard install"))
    elif hooks.plugin_enabled(settings):
        lines.append(f"{ok}" + L("guard active through the Claude Code plugin", "guard 通过 Claude Code 插件生效"))
    elif other_agents:
        lines.append("  -    " + L("Claude Code guard not installed (fine if you do not use Claude Code)", "没给 Claude Code 装 guard（不用 Claude Code 就没关系）"))
    else:
        lines.append(f"{bad}" + L("guard hooks not installed", "guard 的 hook 没装") + (f" ({', '.join(sorted(installed))})" if installed else ""))
        problems.append(L("run: honestly guard install", "运行：honestly guard install"))
    _check_hook_entries(_our_entries(settings), lines, problems, L, "", (ok, bad))
    for agent in other_agents:
        lines.append(f"{ok}" + L(f"{_ag.NAMES[agent]} guard installed ({', '.join(_ag.installed(agent))}) — experimental", f"{_ag.NAMES[agent]} 的 guard 已装（{', '.join(_ag.installed(agent))}）— 实验性"))
        _, _, _, agent_settings = guardfile.read(_ag.config_path(agent))
        _check_hook_entries(_our_entries(agent_settings, agent == "cursor"), lines, problems, L, agent, (ok, bad))
    paths = list(iter_sessions())
    if paths:
        newest = max(paths, key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
        try:
            n = len(parse_session(newest, tail=True))
            lines.append(f"{ok}" + L(f"{len(paths)} Claude Code session logs; newest parses ({n} turns read)", f"{len(paths)} 个 Claude Code 会话记录；最新的能解析（读到 {n} 轮）"))
        except OSError as e:
            lines.append(f"{warn}" + L(f"newest session log cannot be read: {e}", f"最新的会话记录读不了：{e}"))
        except Exception as e:
            lines.append(f"{bad}" + L(f"newest session log failed to parse: {e}", f"最新的会话记录解析失败：{e}"))
            problems.append(L(f"report this: honestly feedback --issue  (parse error on {os.path.basename(newest)})", f"请反馈：honestly feedback --issue（{os.path.basename(newest)} 解析出错）"))
    else:
        lines.append(f"{warn}" + L(f"no Claude Code session logs under {projects_root()} (nothing to audit yet)", f"{projects_root()} 下没有会话记录（还没有可审计的内容）"))
    codex_dir = os.path.expanduser("~/.codex/sessions")
    lines.append((f"{ok}" if os.path.isdir(codex_dir) else "  -    ") + L(f"Codex sessions {'found' if os.path.isdir(codex_dir) else 'not found (fine if you do not use Codex)'}",
                                                                           f"Codex 会话记录{'已找到' if os.path.isdir(codex_dir) else '未找到（不用 Codex 就没关系）'}"))
    for name, passed, _msg in self_test():
        what = {"code": L("a fake 'All tests pass.' right after an edit, no test run", "伪造一句改完代码就说「All tests pass.」，没跑测试"),
                "non-code": L("a fake 'I've sent you the report.' with no send tool", "伪造一句「I've sent you the report.」，没有发送动作")}[name]
        lines.append(f"{ok if passed else bad}" + L(f"self-test ({name}): {what} → {'blocked' if passed else 'NOT blocked'}", f"自测（{'代码' if name == 'code' else '非代码'}）：{what} → {'已拦截' if passed else '未拦截'}"))
        if not passed:
            problems.append(L(f"the {name} self-test was not blocked; run `honestly feedback --issue` and attach this output", f"{name} 自测没被拦；运行 honestly feedback --issue 并附上这段输出"))
    ep = hooks.errors_path()
    if os.path.exists(ep) and os.path.getsize(ep) > 0:
        with open(ep, "rb") as fh:   # the log can have grown large: only its end matters
            fh.seek(max(0, os.path.getsize(ep) - 8000))
            tail = fh.read().decode("utf-8", "ignore")
        # the last entry starts at the last timestamped line; a traceback can be longer than a few hundred
        # characters when the install path is long, so the whole entry is checked, not a fixed tail
        entry_lines = tail.splitlines()
        starts = [i for i, l in enumerate(entry_lines) if re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d ", l)]
        tail = "\n".join(entry_lines[starts[-1]:] if starts else entry_lines)
        if "Traceback" in tail:
            lines.append(f"{warn}" + L(f"the hooks hit an internal error before (they let the assistant continue); last entry in {ep}:", f"hook 之前出过内部错误（当时直接放行了）；{ep} 的最后一条："))
            lines += ["         " + l for l in tail.strip().splitlines()[-4:]]
            problems.append(L("send that log entry with `honestly feedback --issue`", "请用 honestly feedback --issue 提交这条日志"))
        else:
            lines.append(f"{ok}" + L(f"the hooks let some input through unchecked (not an error); last note in {ep}:", f"hook 有部分输入未检查直接放行（非错误）；{ep} 的最后一条："))
            lines += ["         " + l for l in tail.strip().splitlines()[-1:]]
    try:
        rows = hooks.load_catches()
        lines.append(f"{ok}" + L(f"catches log: {len(rows)} recorded", f"拦截记录：{len(rows)} 条") + (f", {L('last', '最近')} {hooks.local_time(rows[-1].get('ts', ''))}" if rows else "") + f"  ({hooks.catches_path()})")
    except OSError as e:
        lines.append(f"{warn}" + L(f"catches log cannot be read: {hooks.catches_path()} ({e.strerror})", f"拦截记录读不了：{hooks.catches_path()}（{e.strerror}）"))
    notify = os.environ.get("HONESTLY_NOTIFY") == "1" or os.path.exists(hooks.notify_flag_path())
    lines.append(f"{ok}" + L(f"desktop notifications {'on' if notify else 'off  (honestly guard notify on)'}", f"桌面通知{'已开' if notify else '未开（honestly guard notify on）'}"))
    cfg = config.load()
    lines.append(f"{ok}" + L(f"strictness {cfg['strictness']}, {len(cfg['ignore'])} ignored phrase(s), {len(cfg['verify_commands'])} custom verify command(s), off: {', '.join(cfg['off']) or 'none'}",
                             f"严格度 {cfg['strictness']}，忽略短语 {len(cfg['ignore'])} 条，自定义验证命令 {len(cfg['verify_commands'])} 条，关闭类别：{', '.join(cfg['off']) or '无'}"))
    try:
        from .update import latest_version, upgrade_command, _parse
        latest = latest_version()
        if latest and _parse(latest) > _parse(__version__):
            lines.append(f"{warn}" + L(f"newer release on PyPI: {latest} ({upgrade_command()})", f"PyPI 有新版 {latest}（{upgrade_command()}）"))
        elif latest:
            lines.append(f"{ok}" + L(f"up to date ({latest}; pypi.org is asked once a day, HONESTLY_NO_UPDATE_CHECK=1 turns this off)",
                                     f"已是最新（{latest}；每天问一次 pypi.org，HONESTLY_NO_UPDATE_CHECK=1 可关闭）"))
    except Exception:
        pass
    lines.append("")
    if problems:
        lines.append(L(f"{len(problems)} problem(s):", f"{len(problems)} 个问题："))
        lines += [f"  - {p}" for p in problems]
    else:
        lines.append(L("all good: guard is installed and blocking.", "一切正常：guard 已安装并能正常拦截。"))
    text = "\n".join(lines)
    return (text, problems) if with_problems else text


# ----------------------------------------------------------------- feedback
_redact = redact


def feedback(n: int = 1, issue_url: bool = False) -> str:
    rows = hooks.load_catches()
    if not rows:
        return "no catches recorded yet (honestly catches shows them once guard has stopped something)."
    if n < 1 or n > len(rows):
        return f"there are {len(rows)} catches; pick 1 (latest) to {len(rows)}."
    r = rows[-n]
    tools = r.get("tools") or ([r["command"]] if r.get("command") else [])
    message = str(r.get("message", ""))
    for private in (hooks._short(str(r.get("project", ""))), str(r.get("topic", ""))[:30]):   # which project and what was asked are the user's business
        if private:
            message = message.replace(private, "<withheld>")
    body = [
        "## honestly: a catch that looks wrong", "",
        f"- honestly {r.get('version') or __version__}, {platform.system()} {platform.release()}, Python {'.'.join(map(str, sys.version_info[:3]))}",
        f"- assistant: {r.get('agent', '')} {r.get('model', '')}".rstrip(),
        f"- kind: {'stop (claim without a check)' if r.get('kind') == 'stop' else 'pre (check result cut off by a pipe)'}",
        f"- what it said: \"{r.get('claim') or r.get('command') or ''}\"",
        f"- honestly's reason: {r.get('reason') or '(pipe check)'}",
        "- what ran before the sentence (after the last edit):",
    ] + ([f"  - {t}" for t in tools] or ["  - (nothing recorded)"]) + [
        f"- the message shown: {message}", "",
        "Why it is wrong (one line): ", "",
    ]
    text = _redact("\n".join(body))
    out = ["Copy everything between the lines into a GitHub issue (check it for anything private first):", "-" * 60, text, "-" * 60]
    if issue_url:
        title = _redact(f"False catch: {r.get('claim') or r.get('command') or ''}")[:80]
        url = f"{REPO}/issues/new?" + urllib.parse.urlencode({"title": title, "body": text})
        out.append(f"\nOpen a pre-filled issue: {url}")
    else:
        out.append(f"\nNew issue: {REPO}/issues/new   (add --issue to get a pre-filled link)")
    return "\n".join(out)


# ------------------------------------------------------------------- rules
RULE_START, RULE_END = "<!-- honestly:start -->", "<!-- honestly:end -->"
RULE_TEXT = """## Verify before you claim (honestly)

- Before writing "tests pass", "fixed", "builds", "pushed", "sent", "deployed", "saved" or "checked", run the matching command in this same turn and quote its real output. No command, no claim.
- If you changed code and did not run the check, say exactly that: "changed, not yet verified".
- Never send, deploy or push just to back up a sentence. If it did not happen, say so, and ask before doing anything hard to undo.
- Do not pipe a test or build into `head`, `grep -c`, `wc` or a `grep` that drops the summary; a cut-off result hides failures. Use `set -o pipefail` when you must pipe.
- When honestly stops you, start the next reply with one bold line: why you were stopped and what the check returned.
- When you open or update a pull request, run `honestly pr-note --gh` after it (or put `honestly pr-note` output in the body) so the reviewer sees what ran after the last edit.
"""
RULE_TEXT_ZH = """## 先验证再下结论（honestly）

- 写「测试通过」「修好了」「构建通过」「已推送」「已发送」「已部署」「已保存」「查过了」之前，先在这一轮里跑对应的命令，并引用它的真实输出。没跑就不能说。
- 改了代码但没跑检查，就照实写：「已修改，尚未验证」。
- 不要为了让一句话成立去发送、部署或推送。没发生就照实说，任何难以撤销的操作都要先问用户。
- 测试或构建命令不要接 `head`、`grep -c`、`wc` 或会滤掉汇总行的 `grep`，截断的结果会把失败藏起来；确实要用管道时加 `set -o pipefail`。
- 被 honestly 拦截后，下一条回复第一行用加粗写明：被拦截的原因和补跑结果。
- 开或更新 pull request 之后运行 `honestly pr-note --gh`（或把 `honestly pr-note` 的输出放进描述），让审阅者看到最后一次改动之后跑了什么。
"""
RULE_FILES = {"claude-code": "CLAUDE.md", "codex": "AGENTS.md", "gemini": "GEMINI.md", "cursor": os.path.join(".cursor", "rules", "honestly.mdc")}


def _rule_read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", newline="") as fh:   # newline="": the file keeps its own line endings
            return fh.read()
    except (FileNotFoundError, NotADirectoryError):
        return ""
    except UnicodeDecodeError:
        raise SystemExit(f"honestly rule: {path} is not UTF-8 text, so it was left untouched.") from None
    except OSError as e:
        raise SystemExit(f"honestly rule: cannot read {path}: {e.strerror}") from None


def rule(action: str, agent: str = "claude-code", cwd: str | None = None, zh: bool = False) -> str:
    """Add or remove a short 'verify before you claim' section in the project's instructions file, between markers."""
    if cwd and not os.path.isdir(cwd):
        raise SystemExit(f"honestly rule: no such directory: {cwd}")
    base = cwd or os.getcwd()
    path = os.path.join(base, RULE_FILES[agent])
    text = _rule_read(path)
    if action == "status":
        return f"honestly rule: {'present' if RULE_START in text else 'absent'} in {path}"
    real, root = os.path.realpath(path), os.path.realpath(base)
    if real != root and not real.startswith(root.rstrip(os.sep) + os.sep):   # a repository can make CLAUDE.md a link to a file in the user's home
        raise SystemExit(f"honestly rule: {path} points outside this project (to {real}), so it was left untouched.")
    nl = "\r\n" if "\r\n" in text else "\n"
    text_block = (RULE_TEXT_ZH if zh else RULE_TEXT).replace("\n", nl)
    front = "---\ndescription: verify before claiming (honestly)\nalwaysApply: true\n---\n".replace("\n", nl)
    block = RULE_START + nl + text_block + RULE_END + nl
    if agent == "cursor":
        block = front + block
    stripped = re.sub(re.escape(RULE_START) + r".*?" + re.escape(RULE_END) + r"(?:\r?\n)?", "", text, flags=re.S)
    if agent == "cursor" and stripped.startswith(front):
        stripped = stripped[len(front):]
    has_content = stripped.strip("\ufeff \t\r\n")
    if action == "install":
        new = (stripped.rstrip("\r\n") + nl + nl if has_content else "") + block
        if agent == "cursor" and has_content:
            new = stripped.rstrip("\r\n") + nl + nl + RULE_START + nl + text_block + RULE_END + nl
    else:
        new = stripped.rstrip("\r\n") + nl if has_content else ""
    if action == "install" and new == text:
        return f"honestly rule: already present, nothing changed: {path}"
    if action == "uninstall" and RULE_START not in text:
        return f"honestly rule: not present, nothing to remove: {path}"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if action == "uninstall" and not new.strip():
            if os.path.exists(path):
                os.remove(path)
            return f"honestly rule: removed (file deleted, it held nothing else): {path}"
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(new)
    except OSError as e:
        raise SystemExit(f"honestly rule: cannot write {e.filename or path}: {e.strerror}. Nothing changed.") from None
    return f"honestly rule: {'added to' if action == 'install' else 'removed from'} {path}"
