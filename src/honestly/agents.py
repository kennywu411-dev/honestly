"""Other assistants: how each one calls a hook, what it stores on disk, and how to install the guard into it.

Claude Code is handled in hooks.py / claude_code.py and Codex transcripts in codex.py; this module adds the
Codex, Cursor and Gemini CLI hook contracts and the Cursor and Gemini CLI transcript parsers.

Contracts (from the vendors' docs, 2026-10; marked experimental in the README until each is confirmed on a real machine):
  codex    ~/.codex/hooks.json      Stop {decision:block, reason}; PreToolUse hookSpecificOutput.permissionDecision=deny
  cursor   ~/.cursor/hooks.json     stop {followup_message}; beforeShellExecution {permission:deny, user_message, agent_message}
  gemini   ~/.gemini/settings.json  AfterAgent {decision:deny, reason, systemMessage}; BeforeTool {decision:deny, reason, systemMessage}
"""
from __future__ import annotations

import glob
import json
import os
import re

from .claude_code import Event, Turn

MARK = "honestly hook"
NAMES = {"claude-code": "Claude Code", "codex": "Codex", "cursor": "Cursor", "gemini": "Gemini CLI"}
SUPPORTED = tuple(NAMES)
SHELL_TOOLS = {"Bash", "shell", "shell_command", "exec", "exec_command", "local_shell", "container.exec", "run_shell_command", "Shell", "run_terminal_cmd", "terminal"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "write_file", "replace", "edit_file", "edit", "apply_patch", "StrReplace", "Write"}


# ------------------------------------------------------------ transcripts: Cursor
def cursor_sessions(root: str | None = None):
    root = root or os.path.expanduser("~/.cursor/projects")
    yield from sorted(glob.glob(os.path.join(root, "*", "agent-transcripts", "*", "*.jsonl")) +
                      glob.glob(os.path.join(root, "*", "agent-transcripts", "*.jsonl")))


def _tool_event(name: str, inp, ts: str = "") -> Event:
    inp = inp if isinstance(inp, dict) else {}
    cmd = inp.get("command") or inp.get("cmd") or inp.get("commandLine") or ""
    if isinstance(cmd, list):
        cmd = " ".join(str(x) for x in cmd)
    if name in SHELL_TOOLS or (cmd and not any(k in inp for k in ("file_path", "path", "target_file"))):
        return Event("tool", name="Bash", text=str(cmd), ts=ts)
    path = inp.get("file_path") or inp.get("target_file") or inp.get("path") or inp.get("relative_workspace_path") or ""
    if name in EDIT_TOOLS or (path and re.search(r"(edit|write|replace|patch)", name, re.I)):
        return Event("tool", name="Edit", text=str(path), ts=ts)
    return Event("tool", name=name or "tool", text=str(path or inp.get("query") or inp.get("prompt") or ""), ts=ts)


def cursor_parse(path: str):
    """Cursor's hook-visible transcript: one JSON object per line with role and message; tool inputs are kept, tool outputs are not."""
    session = os.path.splitext(os.path.basename(path))[0][:40]
    turns: list[Turn] = []
    cur: Turn | None = None
    project = re.split(r"[\\/]agent-transcripts", path)[0].split(os.sep)[-1] if "agent-transcripts" in path else ""
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if not isinstance(r, dict):
                continue
            role = r.get("role")
            msg = r.get("message") if isinstance(r.get("message"), dict) else {}
            content = msg.get("content")
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            if not isinstance(content, list):
                continue
            if role == "user":
                texts = [str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                if not texts or any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                    continue
                prompt = re.sub(r"</?user_query>", "", " ".join(texts)).strip()
                if cur is not None:
                    turns.append(cur)
                cur = Turn(session=session, index=len(turns), version="", prompt=prompt[:200], agent="cursor", project=project)
            elif role == "assistant":
                if cur is None:
                    cur = Turn(session=session, index=0, version="", prompt="", agent="cursor", project=project)
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        cur.events.append(Event("text", text=str(b.get("text") or "")))
                    elif b.get("type") == "tool_use":
                        cur.events.append(_tool_event(str(b.get("name") or ""), b.get("input")))
    if cur is not None:
        turns.append(cur)
    return turns


# --------------------------------------------------------- transcripts: Gemini CLI
def gemini_sessions(root: str | None = None):
    root = root or os.path.expanduser("~/.gemini/tmp")
    yield from sorted(glob.glob(os.path.join(root, "*", "chats", "session-*.jsonl")) + glob.glob(os.path.join(root, "*", "chats", "session-*.json")))


def _parts_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(p.get("text") or "") if isinstance(p, dict) else str(p) for p in content)
    if isinstance(content, dict):
        return str(content.get("text") or "")
    return ""


def _gemini_records(path: str):
    if path.endswith(".json"):
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                d = json.load(fh)
        except Exception:
            return
        for r in (d.get("messages") if isinstance(d, dict) else d) or []:
            if isinstance(r, dict):
                yield r
        return
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if isinstance(r, dict):
                yield r


def gemini_parse(path: str):
    """Gemini CLI chat recording: message records (type user | gemini) with content parts and, for gemini, toolCalls[{name,args,result,status}]."""
    session = os.path.splitext(os.path.basename(path))[0].replace("session-", "")[:40]
    turns: list[Turn] = []
    cur: Turn | None = None
    model = ""
    project = ""
    for r in _gemini_records(path):
        if "$patch" in r or "$set" in r or "$rewindTo" in r:
            continue
        if isinstance(r.get("projectHash"), str) and not r.get("type"):
            dirs = r.get("directories")
            project = str(dirs[0]) if isinstance(dirs, list) and dirs else project
            continue
        t = r.get("type")
        ts = str(r.get("timestamp") or "")
        if t == "user":
            if cur is not None:
                turns.append(cur)
            cur = Turn(session=session, index=len(turns), version=model, prompt=_parts_text(r.get("content"))[:200], ts=ts, agent="gemini", model=model, project=project)
        elif t == "gemini":
            if cur is None:
                cur = Turn(session=session, index=0, version=model, prompt="", ts=ts, agent="gemini", project=project)
            if isinstance(r.get("model"), str) and not cur.model:
                cur.model = model = r["model"]
            for call in r.get("toolCalls") or []:
                if not isinstance(call, dict):
                    continue
                ev = _tool_event(str(call.get("name") or ""), call.get("args"), ts)
                res = call.get("result")
                if isinstance(res, dict):
                    res = res.get("llmContent") or res.get("output") or res.get("content") or json.dumps(res, ensure_ascii=False)
                ev.result = _parts_text(res)[:3000] if not isinstance(res, str) else res[:3000]
                st = str(call.get("status") or "").lower()
                ev.is_error = True if st in ("error", "failed", "cancelled") else (False if st in ("success", "ok", "done") else None)
                cur.events.append(ev)
            text = _parts_text(r.get("content"))
            if text.strip():
                cur.events.append(Event("text", text=text, ts=ts))
    if cur is not None:
        turns.append(cur)
    return turns


# ------------------------------------------------------------ hook payloads
def normalize(agent: str, which: str, data: dict) -> dict:
    """The fields the two hooks need, whatever the assistant calls them."""
    d = dict(data)
    if agent == "cursor":
        roots = d.get("workspace_roots")
        d.setdefault("cwd", roots[0] if isinstance(roots, list) and roots else "")
        if which == "stop":
            d["stop_hook_active"] = bool(d.get("loop_count"))   # loop_count counts our own follow-ups
            d.setdefault("last_assistant_message", "")
        else:
            d["tool_name"] = "Bash"
            d["tool_input"] = {"command": d.get("command") or ""}
    elif agent == "gemini":
        if which == "stop":
            d["last_assistant_message"] = _parts_text(d.get("prompt_response")) if not isinstance(d.get("prompt_response"), str) else d.get("prompt_response")
        else:
            ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
            if str(d.get("tool_name") or "") in SHELL_TOOLS or "command" in ti:
                d["tool_name"] = "Bash"
                d["tool_input"] = {"command": ti.get("command") or ""}
    elif agent == "codex":
        if which == "pre":
            ti = d.get("tool_input") if isinstance(d.get("tool_input"), dict) else {}
            cmd = ti.get("command") or ti.get("cmd") or ""
            if isinstance(cmd, list):
                cmd = " ".join(str(x) for x in cmd)
            if str(d.get("tool_name") or "") in SHELL_TOOLS or cmd:
                d["tool_name"] = "Bash"
                d["tool_input"] = {"command": str(cmd)}
    return d


def emit(agent: str, which: str, plain: str, instruction: str) -> dict:
    """Format a block for the assistant that is listening."""
    if agent == "cursor":
        if which == "stop":
            return {"followup_message": plain + "\n" + instruction}
        return {"permission": "deny", "user_message": plain, "agent_message": plain + "\n" + instruction}
    if agent == "gemini":
        return {"decision": "deny", "reason": plain + "\n" + instruction, "systemMessage": plain}
    # claude-code and codex share the contract
    if which == "stop":
        return {"decision": "block", "reason": plain + "\n" + instruction, "systemMessage": plain}
    return {"systemMessage": plain, "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                           "permissionDecisionReason": plain + "\n" + instruction}}


def parser_for(agent: str, tail: bool = False):
    """Transcript parser for an agent; tail=True asks for the cheap end-of-file read used by the hooks."""
    if agent == "claude-code" and tail:
        from .claude_code import parse_session
        return lambda p: parse_session(p, tail=True)
    if agent == "codex":
        from .codex import parse_session
        return parse_session
    if agent == "cursor":
        return cursor_parse
    if agent == "gemini":
        return gemini_parse
    from .claude_code import parse_session
    return parse_session


# --------------------------------------------------------------- installers
def config_path(agent: str) -> str:
    return {"codex": "~/.codex/hooks.json", "cursor": "~/.cursor/hooks.json", "gemini": "~/.gemini/settings.json",
            "claude-code": "~/.claude/settings.json"}[agent].replace("~", os.path.expanduser("~"), 1)


def _is_ours(h) -> bool:
    return isinstance(h, dict) and MARK in str(h.get("command", ""))


def entries(agent: str, exe: str) -> dict:
    stop = f"{exe} hook stop --agent {agent}  # {MARK}"
    pre = f"{exe} hook pre --agent {agent}  # {MARK}"
    if agent == "codex":
        return {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": stop, "timeout": 30}]}],
                "PreToolUse": [{"matcher": "", "hooks": [{"type": "command", "command": pre, "timeout": 10}]}]}
    if agent == "cursor":
        return {"stop": [{"type": "command", "command": stop, "timeout": 30, "loop_limit": 2}],
                "beforeShellExecution": [{"type": "command", "command": pre, "timeout": 10}]}
    if agent == "gemini":
        return {"AfterAgent": [{"hooks": [{"name": "honestly", "type": "command", "command": stop, "timeout": 30000}]}],
                "BeforeTool": [{"matcher": "run_shell_command", "hooks": [{"name": "honestly", "type": "command", "command": pre, "timeout": 10000}]}]}
    raise ValueError(agent)


def _strip_ours(agent: str, groups: list) -> list:
    if agent == "cursor":
        return [h for h in groups if not _is_ours(h)]
    return [g for g in groups if not any(_is_ours(h) for h in (g.get("hooks") or []))]


def installed(agent: str) -> list[str]:
    path = config_path(agent)
    try:
        cfg = json.load(open(path, encoding="utf-8"))
    except Exception:
        return []
    hooks = cfg.get("hooks") if isinstance(cfg.get("hooks"), dict) else {}
    out = []
    for ev, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        if agent == "cursor":
            if any(_is_ours(h) for h in groups):
                out.append(ev)
        elif any(_is_ours(h) for g in groups if isinstance(g, dict) for h in (g.get("hooks") or [])):
            out.append(ev)
    return out


def guard(agent: str, action: str, exe: str, dry_run: bool = False) -> str:
    """install | uninstall | status for codex, cursor or gemini. The file is backed up first; only our own entries are touched."""
    path = config_path(agent)
    name = NAMES[agent]
    try:
        cfg = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    except Exception as e:
        return f"cannot read {path}: {e}"
    if not isinstance(cfg, dict):
        cfg = {}
    if action == "status":
        on = installed(agent)
        return f"honestly guard ({name}): {'installed for ' + ', '.join(on) if on else 'not installed'} ({path})"
    hooks = cfg.setdefault("hooks", {})
    if agent == "cursor":
        cfg.setdefault("version", 1)
    for ev, groups in entries(agent, exe).items():
        current = hooks.get(ev) if isinstance(hooks.get(ev), list) else []
        current = _strip_ours(agent, current)
        if action == "install":
            current = current + groups
        if current:
            hooks[ev] = current
        else:
            hooks.pop(ev, None)
    if action == "uninstall":
        for ev in list(hooks):
            if isinstance(hooks[ev], list):
                hooks[ev] = _strip_ours(agent, hooks[ev])
                if not hooks[ev]:
                    del hooks[ev]
    if dry_run:
        return f"honestly guard would write this `hooks` section into {path}:\n" + json.dumps({"hooks": hooks}, ensure_ascii=False, indent=2)
    if os.path.exists(path):
        import shutil, time
        shutil.copy(path, path + ".bak-honestly-" + time.strftime("%Y%m%d%H%M%S"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    note = {"codex": "  Codex asks you to review new hooks once: run /hooks inside Codex.",
            "cursor": "  Cursor shows hook-visible transcripts only when they are enabled; the stop hook needs them to see what was said.",
            "gemini": ""}[agent]
    return f"honestly guard ({name}): {action}ed → {path}" + ("\n" + note if note and action == "install" else "")
