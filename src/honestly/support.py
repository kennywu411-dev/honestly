"""`honestly doctor` (is the install working?) and `honestly feedback` (turn a wrong catch into an issue-ready text)."""
from __future__ import annotations

import json
import os
import platform
import re
import sys
import tempfile
import urllib.parse

from . import __version__, config, hooks
from .claude_code import iter_sessions, parse_session

REPO = "https://github.com/kennywu411-dev/honestly"


# ------------------------------------------------------------------- doctor
def _hook_cmds(settings: dict) -> list[str]:
    """The command lines guard installed, one per distinct executable."""
    out = []
    hk = settings.get("hooks") if isinstance(settings.get("hooks"), dict) else {}
    for ev in hk:
        for g in hooks.groups_of(hk, ev):
            for h in hooks.hooks_of(g):
                if hooks._ours(h):
                    out.append(str(h.get("command", "")))
    return list(dict.fromkeys(out))


def _hook_cmd_paths(settings: dict) -> list[str]:
    return list(dict.fromkeys(c.split(" hook ", 1)[0].strip().strip('"') for c in _hook_cmds(settings)))


def _hook_runs(cmd: str) -> tuple:
    """Run the installed hook line through a POSIX shell with an empty event, the way the assistant will: (ran, detail)."""
    import shutil, subprocess
    sh = shutil.which("bash") or shutil.which("sh")
    if not sh:
        return (None, "no bash/sh found to try the hook line")
    try:
        r = subprocess.run([sh, "-c", cmd.replace("hook stop", "hook pre", 1)], input=b"{}", capture_output=True, timeout=20)
    except Exception as e:
        return (False, f"{e.__class__.__name__}: {e}")
    err = r.stderr.decode("utf-8", "ignore").strip().splitlines()
    return (r.returncode == 0, err[-1] if err and r.returncode != 0 else "")


def _fake_session(d: str, rows: list) -> str:
    tp = os.path.join(d, f"s{len(os.listdir(d))}.jsonl")
    with open(tp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return tp


def self_test() -> list:
    """Feed guard two fake turns and see whether it blocks: a code claim ('All tests pass.' right after an edit, no test
    run) and a non-code claim ('I've sent you the file.' with no send tool). Returns [(name, blocked, message)]."""
    d = tempfile.mkdtemp(prefix="honestly-doctor-")
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
    saved = (hooks.catches_path, hooks._notify)
    hooks.catches_path = lambda: os.path.join(d, "catches.jsonl")   # never pollute the real log
    hooks._notify = lambda *a, **k: None
    results = []
    try:
        for name, tp, last in (("code", code, "Fixed. All tests pass."), ("non-code", noncode, "I've sent you the report.")):
            try:
                out = hooks.stop_hook({"transcript_path": tp, "cwd": d, "last_assistant_message": last, "stop_hook_active": False})
            except Exception as e:
                out = {"error": str(e)}
            results.append((name, bool(out and out.get("decision") == "block"), (out or {}).get("systemMessage", "") or str(out)))
    finally:
        hooks.catches_path, hooks._notify = saved
    return results


def doctor(zh: bool | None = None, with_problems: bool = False):
    """The report as text; with_problems=True returns (text, problems) so the CLI can exit non-zero."""
    if zh is None:
        zh = hooks._lang_zh(config.load(), os.environ.get("LANG", ""))
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
    sp = hooks.settings_path()
    settings = {}
    if os.path.exists(sp):
        try:
            settings = json.load(open(sp, encoding="utf-8"))
            lines.append(f"{ok}" + L(f"Claude Code settings readable: {sp}", f"Claude Code 设置文件可读：{sp}"))
        except Exception as e:
            lines.append(f"{bad}" + L(f"settings file is not valid JSON: {sp} ({e})", f"设置文件不是合法 JSON：{sp}（{e}）"))
            problems.append(L(f"fix the JSON in {sp} (a backup may exist next to it)", f"修复 {sp} 里的 JSON（旁边可能有备份）"))
    else:
        lines.append(f"{warn}" + L(f"no Claude Code settings file at {sp}", f"没有 Claude Code 设置文件：{sp}"))
    _hk = settings.get("hooks") if isinstance(settings.get("hooks"), dict) else {}
    installed = {ev for ev in _hk if any(hooks._ours(h) for g in hooks.groups_of(_hk, ev) for h in hooks.hooks_of(g))}
    if {"Stop", "PreToolUse"} <= installed:
        lines.append(f"{ok}" + L("guard hooks installed (Stop, PreToolUse)", "guard 的两个 hook 已装（Stop、PreToolUse）"))
    else:
        lines.append(f"{bad}" + L("guard hooks not installed", "guard 的 hook 没装") + (f" ({', '.join(sorted(installed))})" if installed else ""))
        problems.append(L("run: honestly guard install", "运行：honestly guard install"))
    for exe in _hook_cmd_paths(settings):
        if exe == "honestly":
            import shutil
            found = shutil.which("honestly")
            lines.append((f"{ok}" + L(f"hook command 'honestly' resolves to {found}", f"hook 命令 honestly 指向 {found}")) if found
                         else (f"{bad}" + L("hook command 'honestly' is not on PATH for non-interactive shells", "hook 命令 honestly 不在非交互 shell 的 PATH 里")))
            if not found:
                problems.append(L("run `honestly guard install` from the environment where honestly is installed, so the hook gets a full path",
                                  "在装了 honestly 的环境里运行 honestly guard install，让 hook 写成完整路径"))
        else:
            exists = os.path.exists(exe)
            lines.append(f"{ok if exists else bad}" + L(f"hook command exists: {exe}", f"hook 命令存在：{exe}"))
            if not exists:
                problems.append(L("the hook points to a missing file; run: honestly guard install", "hook 指向的文件不存在；运行：honestly guard install"))
    for cmd in _hook_cmds(settings)[:1]:
        ran, detail = _hook_runs(cmd)
        if ran is None:
            continue
        lines.append(f"{ok if ran else bad}" + L(f"hook line runs through the shell: {cmd.split('  #')[0]}", f"hook 命令行能在 shell 里跑：{cmd.split('  #')[0]}") + (f"  ({detail})" if detail else ""))
        if not ran:
            problems.append(L("the hook line fails when a shell runs it (the assistant would skip the guard silently); run `honestly guard install` again and send this output with `honestly feedback --issue`",
                              "hook 命令行在 shell 里跑不起来（助手会静默跳过 guard）；重新 honestly guard install，并用 honestly feedback --issue 发来这段输出"))
    for agent in ("codex", "cursor", "gemini"):
        from . import agents as _ag
        on = _ag.installed(agent)
        if on:
            lines.append(f"{ok}" + L(f"{_ag.NAMES[agent]} guard installed ({', '.join(on)}) — experimental", f"{_ag.NAMES[agent]} 的 guard 已装（{', '.join(on)}）— 实验性"))
    paths = list(iter_sessions())
    if paths:
        newest = max(paths, key=os.path.getmtime)
        try:
            n = len(parse_session(newest, tail=True))
            lines.append(f"{ok}" + L(f"{len(paths)} Claude Code session logs; newest parses ({n} turns read)", f"{len(paths)} 个 Claude Code 会话记录；最新的能解析（读到 {n} 轮）"))
        except Exception as e:
            lines.append(f"{bad}" + L(f"newest session log failed to parse: {e}", f"最新的会话记录解析失败：{e}"))
            problems.append(L(f"report this: honestly feedback --issue  (parse error on {os.path.basename(newest)})", f"请反馈：honestly feedback --issue（{os.path.basename(newest)} 解析出错）"))
    else:
        lines.append(f"{warn}" + L("no Claude Code session logs under ~/.claude/projects (nothing to audit yet)", "~/.claude/projects 下没有会话记录（还没有可审计的内容）"))
    codex_dir = os.path.expanduser("~/.codex/sessions")
    lines.append((f"{ok}" if os.path.isdir(codex_dir) else "  -    ") + L(f"Codex sessions {'found' if os.path.isdir(codex_dir) else 'not found (fine if you do not use Codex)'}",
                                                                           f"Codex 会话记录{'已找到' if os.path.isdir(codex_dir) else '未找到（不用 Codex 就没关系）'}"))
    for name, passed, msg in self_test():
        what = {"code": L("a fake 'All tests pass.' right after an edit, no test run", "伪造一句改完代码就说「All tests pass.」，没跑测试"),
                "non-code": L("a fake 'I've sent you the report.' with no send tool", "伪造一句「I've sent you the report.」，没有发送动作")}[name]
        lines.append(f"{ok if passed else bad}" + L(f"self-test ({name}): {what} → {'blocked' if passed else 'NOT blocked'}", f"自测（{'代码' if name == 'code' else '非代码'}）：{what} → {'已拦' if passed else '没拦'}"))
        if not passed:
            problems.append(L(f"the {name} self-test was not blocked; run `honestly feedback --issue` and attach this output", f"{name} 自测没被拦；运行 honestly feedback --issue 并附上这段输出"))
    ep = hooks.errors_path()
    if os.path.exists(ep) and os.path.getsize(ep) > 0:
        with open(ep, encoding="utf-8", errors="ignore") as fh:
            tail = fh.read()[-8000:]
        # the last entry starts at the last timestamped line; a traceback can be longer than a few hundred
        # characters when the install path is long, so the whole entry is checked, not a fixed tail
        entry_lines = tail.splitlines()
        starts = [i for i, l in enumerate(entry_lines) if re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d ", l)]
        tail = "\n".join(entry_lines[starts[-1]:] if starts else entry_lines)
        if "Traceback" in tail:
            lines.append(f"{warn}" + L(f"the hooks hit an internal error before (they let the assistant continue); last entry in {ep}:", f"hook 之前出过内部错误（当时直接放行了）；{ep} 的最后一条："))
            lines += ["         " + l for l in tail.strip().splitlines()[-4:]]
            problems.append(L("send that log entry with `honestly feedback --issue`", "把这条日志用 honestly feedback --issue 发过来"))
        else:
            lines.append(f"{ok}" + L(f"the hooks let some input through unchecked (not an error); last note in {ep}:", f"hook 有几次没看就放行了（不是错误）；{ep} 的最后一条："))
            lines += ["         " + l for l in tail.strip().splitlines()[-1:]]
    rows = hooks.load_catches()
    lines.append(f"{ok}" + L(f"catches log: {len(rows)} recorded", f"拦截记录：{len(rows)} 条") + (f", {L('last', '最近')} {hooks.local_time(rows[-1].get('ts', ''))}" if rows else "") + f"  ({hooks.catches_path()})")
    notify = os.environ.get("HONESTLY_NOTIFY") == "1" or os.path.exists(hooks.notify_flag_path())
    lines.append(f"{ok}" + L(f"desktop notifications {'on' if notify else 'off  (honestly guard notify on)'}", f"桌面通知{'已开' if notify else '未开（honestly guard notify on）'}"))
    cfg = config.load()
    lines.append(f"{ok}" + L(f"strictness {cfg['strictness']}, {len(cfg['ignore'])} ignored phrase(s), {len(cfg['verify_commands'])} custom verify command(s), off: {', '.join(cfg['off']) or 'none'}",
                             f"严格度 {cfg['strictness']}，忽略短语 {len(cfg['ignore'])} 条，自定义验证命令 {len(cfg['verify_commands'])} 条，关闭类别：{', '.join(cfg['off']) or '无'}"))
    try:
        from .update import latest_version, _parse
        latest = latest_version()
        if latest and _parse(latest) > _parse(__version__):
            lines.append(f"{warn}" + L(f"newer release on PyPI: {latest} (pip install -U honestly)", f"PyPI 有新版 {latest}（pip install -U honestly）"))
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
        lines.append(L("all good: guard is installed and blocking.", "一切正常：guard 已装上并且能拦。"))
    text = "\n".join(lines)
    return (text, problems) if with_problems else text


# ----------------------------------------------------------------- feedback
SECRET_ASSIGN = re.compile(r"(?i)\b([\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|auth|credential|private[_-]?key)[\w.-]*)(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)")
SECRET_FLAG = re.compile(r"(?i)((?:^|\s)(?:-p|--password|--token|--api-key|--secret|-u|--user|--auth)[=\s]?)(\"[^\"]*\"|'[^']*'|\S+)")
URL_CREDS = re.compile(r"(://)[^\s/@:]+:[^\s/@]+@")
LONG_TOKEN = re.compile(r"(?<![\w/.-])[A-Za-z0-9_+\-]{20,}(?![\w/.-])")   # no `/`: a path is not a token
BEARER = re.compile(r"(?i)(bearer\s+)\S+")


def _redact(s: str) -> str:
    """Paths under $HOME, e-mails, credential assignments and flags, URL user:pass and long token-like runs."""
    home = os.path.expanduser("~")
    s = s.replace(home, "~")
    s = SECRET_ASSIGN.sub(lambda m: m.group(0) if m.group(3).lower() == "bearer" else m.group(1) + m.group(2) + "<redacted>", s)
    s = BEARER.sub(r"\1<redacted>", s)
    s = SECRET_FLAG.sub(lambda m: m.group(1) + "<redacted>", s)
    s = URL_CREDS.sub(r"\1<redacted>@", s)
    s = LONG_TOKEN.sub(lambda m: m.group(0) if re.fullmatch(r"[A-Z0-9_]+|[A-Za-z_]+|[a-z0-9_]+", m.group(0)) else "<redacted>", s)   # constant names and words stay
    s = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "<email>", s)
    return s


def feedback(n: int = 1, issue_url: bool = False) -> str:
    rows = hooks.load_catches()
    if not rows:
        return "no catches recorded yet (honestly catches shows them once guard has stopped something)."
    if n < 1 or n > len(rows):
        return f"there are {len(rows)} catches; pick 1 (latest) to {len(rows)}."
    r = rows[-n]
    tools = r.get("tools") or ([r["command"]] if r.get("command") else [])
    body = [
        "## honestly: a catch that looks wrong", "",
        f"- honestly {r.get('version') or __version__}, {platform.system()} {platform.release()}, Python {'.'.join(map(str, sys.version_info[:3]))}",
        f"- assistant: {r.get('agent', '')} {r.get('model', '')}".rstrip(),
        f"- kind: {'stop (claim without a check)' if r.get('kind') == 'stop' else 'pre (check piped through tail/head)'}",
        f"- project: {hooks._short(r.get('project', ''))}",
        f"- what it said: \"{r.get('claim') or r.get('command') or ''}\"",
        f"- honestly's reason: {r.get('reason') or '(pipe check)'}",
        "- what ran before the sentence (after the last edit):",
    ] + ([f"  - {t}" for t in tools] or ["  - (nothing recorded)"]) + [
        f"- the message shown: {r.get('message', '')}", "",
        "Why it is wrong (one line): ", "",
    ]
    text = _redact("\n".join(body))
    out = ["Copy everything between the lines into a GitHub issue (check it for anything private first):", "-" * 60, text, "-" * 60]
    if issue_url:
        title = f"False catch: {(r.get('claim') or r.get('command') or '')[:60]}"
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
- Never pipe a test or build through `tail` / `head` without `set -o pipefail`; a cut-off result hides failures.
- When honestly stops you, start the next reply with one bold line: why you were stopped and what the check returned.
"""
RULE_TEXT_ZH = """## 先验证再下结论（honestly）

- 写「测试通过」「修好了」「构建通过」「已推送」「已发送」「已部署」「已保存」「查过了」之前，先在这一轮里跑对应的命令，并引用它的真实输出。没跑就不能说。
- 改了代码但没跑检查，就照实写：「已修改，尚未验证」。
- 测试或构建命令不要接 `tail` / `head` 又不加 `set -o pipefail`，截断的结果会把失败藏起来。
- 被 honestly 拦下后，下一条回复第一行用加粗写明：为什么被拦、补跑的结果是什么。
"""
RULE_FILES = {"claude-code": "CLAUDE.md", "codex": "AGENTS.md", "gemini": "GEMINI.md", "cursor": os.path.join(".cursor", "rules", "honestly.mdc")}


def rule(action: str, agent: str = "claude-code", cwd: str | None = None, zh: bool = False) -> str:
    """Add or remove a short 'verify before you claim' section in the project's instructions file, between markers."""
    if cwd and not os.path.isdir(cwd):
        raise SystemExit(f"honestly rule: no such directory: {cwd}")
    path = os.path.join(cwd or os.getcwd(), RULE_FILES[agent])
    text_block = RULE_TEXT_ZH if zh else RULE_TEXT
    block = RULE_START + "\n" + text_block + RULE_END + "\n"
    if agent == "cursor":
        block = "---\ndescription: verify before claiming (honestly)\nalwaysApply: true\n---\n" + block
    text = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    if action == "status":
        return f"honestly rule: {'present' if RULE_START in text else 'absent'} in {path}"
    stripped = re.sub(re.escape(RULE_START) + r".*?" + re.escape(RULE_END) + r"\n?", "", text, flags=re.S)
    if agent == "cursor":
        stripped = re.sub(r"\A---\ndescription: verify before claiming \(honestly\)\nalwaysApply: true\n---\n", "", stripped)
    if action == "install":
        new = (stripped.rstrip("\n") + "\n\n" if stripped.strip() else "") + block
        if agent == "cursor":
            new = block if not stripped.strip() else stripped.rstrip("\n") + "\n\n" + RULE_START + "\n" + text_block + RULE_END + "\n"
    else:
        new = stripped.rstrip("\n") + "\n" if stripped.strip() else ""
    if action == "install" and new == text:
        return f"honestly rule: already present, nothing changed: {path}"
    if action == "uninstall" and RULE_START not in text:
        return f"honestly rule: not present, nothing to remove: {path}"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if action == "uninstall" and not new.strip():
        if os.path.exists(path):
            os.remove(path)
        return f"honestly rule: removed (file deleted, it held nothing else): {path}"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new)
    return f"honestly rule: {'added to' if action == 'install' else 'removed from'} {path}"
