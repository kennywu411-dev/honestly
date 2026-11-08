"""Other assistants: how each one calls a hook, what it stores on disk, and how to install the guard into it.

Claude Code is handled in hooks.py / claude_code.py and Codex transcripts in codex.py; this module adds the
Codex, Cursor and Gemini CLI hook contracts and the Cursor and Gemini CLI transcript parsers.

Contracts (from the vendors' docs, 2026-10; marked experimental in the README until each is confirmed on a real machine):
  codex    ~/.codex/hooks.json      Stop {decision:block, reason}; PreToolUse hookSpecificOutput.permissionDecision=deny
  cursor   ~/.cursor/hooks.json     stop {followup_message}; beforeShellExecution {permission:deny, user_message, agent_message}
  gemini   ~/.gemini/settings.json  AfterAgent {decision:deny, reason, systemMessage}; BeforeTool {decision:deny, reason, systemMessage}
"""
from __future__ import annotations

import json
import os
import re

from . import hookline

MARK = hookline.MARK
NAMES = {"claude-code": "Claude Code", "codex": "Codex", "cursor": "Cursor", "gemini": "Gemini CLI"}
SUPPORTED = tuple(NAMES)
SHELL_TOOLS = {"Bash", "shell", "shell_command", "exec", "exec_command", "local_shell", "container.exec", "run_shell_command", "Shell", "run_terminal_cmd", "terminal"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "write_file", "replace", "edit_file", "edit", "apply_patch", "StrReplace"}


# ------------------------------------------------------------ transcripts: Cursor
def cursor_sessions(root: str | None = None):
    import glob
    root = root or os.path.join(os.path.expanduser("~"), ".cursor", "projects")
    yield from sorted(glob.glob(os.path.join(root, "*", "agent-transcripts", "*", "*.jsonl")) +
                      glob.glob(os.path.join(root, "*", "agent-transcripts", "*.jsonl")))


def _tool_event(name: str, inp, ts: str = ""):
    from .claude_code import Event
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


# `user` records of Gemini CLI that no person wrote: its preamble, a compression summary, its loop warning, a hook's feedback
GEMINI_INJECTED = ("<session_context>", "<state_snapshot>", "System: Potential loop detected")
NOT_GEMINI_PROMPT = tuple(m.encode() for m in GEMINI_INJECTED) + ("⚠️ honestly".encode("utf-8"), b"\\u26a0\\ufe0f honestly")
CURSOR_USER = re.compile(rb'"role":\s*"user"')
GEMINI_USER = re.compile(rb'"type":\s*"user"')


def _cursor_prompt_row(line: bytes) -> bool:
    return CURSOR_USER.search(line) is not None and b'"tool_result"' not in line


def _gemini_prompt_row(line: bytes) -> bool:
    return GEMINI_USER.search(line) is not None and b"functionResponse" not in line and not any(mark in line for mark in NOT_GEMINI_PROMPT)


def cursor_parse(path: str, start: int = 0):
    """Cursor's hook-visible transcript: one JSON object per line with role and message; tool inputs are kept, tool outputs are not."""
    from .claude_code import Event, Turn
    session = os.path.splitext(os.path.basename(path))[0][:40]
    turns: list[Turn] = []
    cur: Turn | None = None
    project = re.split(r"[\\/]agent-transcripts", path)[0].split(os.sep)[-1] if "agent-transcripts" in path else ""
    with open(path, encoding="utf-8", errors="ignore") as fh:
        if start > 0:
            fh.seek(start)
            fh.readline()   # drop the partial line
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
    import glob
    root = root or os.path.join(os.path.expanduser("~"), ".gemini", "tmp")
    yield from sorted(glob.glob(os.path.join(root, "*", "chats", "session-*.jsonl")) + glob.glob(os.path.join(root, "*", "chats", "session-*.json")))


def _parts_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(p.get("text") or "") if isinstance(p, dict) else str(p) for p in content)
    if isinstance(content, dict):
        return str(content.get("text") or "")
    return ""


def _gemini_records(path: str, start: int = 0):
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
        if start > 0:
            fh.seek(start)
            fh.readline()   # drop the partial line
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if isinstance(r, dict):
                yield r


SHELL_TRAILER = re.compile(r"^(?:Process Group PGID: |Background PIDs: |Signal: |Exit Code: |Error: \(none\)$)")   # lines the tool adds after a command's own output
EXIT_CODE = re.compile(r"^Exit Code: (\d{1,9})\s*$")
SHELL_LEADER = re.compile(r"^(?:Command|Directory): ")


def _gemini_result(res) -> tuple:
    """(what the tool printed, its exit code or None). 0.67 keeps a call's result as functionResponse parts and wraps a shell command's
    output as `<untrusted_context>\\nOutput: ...\\nExit Code: 1\\n...`. Only the lines at the very end are the tool's: a test can print `Error: ...` itself."""
    if isinstance(res, list):
        res = "\n".join(_function_response(p) if isinstance(p, dict) and isinstance(p.get("functionResponse"), dict) else _parts_text([p]) for p in res)
    elif isinstance(res, dict):
        res = res.get("llmContent") or res.get("output") or res.get("content") or json.dumps(res, ensure_ascii=False)
    text = res if isinstance(res, str) else _parts_text(res)
    lines = text.split("\n")
    wrapped = bool(lines) and lines[0].strip() == "<untrusted_context>" and lines[-1].strip() == "</untrusted_context>"
    if wrapped:
        lines = lines[1:-1]
    code = None
    if wrapped or any(line.startswith("Output: ") for line in lines):
        while lines and SHELL_TRAILER.match(lines[-1]):
            m = EXIT_CODE.match(lines.pop())
            code = int(m.group(1)) if m and code is None else code
        while lines and SHELL_LEADER.match(lines[0]):
            lines.pop(0)
        if lines and lines[0].startswith("Output: "):
            lines[0] = lines[0][len("Output: "):]
    return "\n".join(lines).strip("\n"), code


def _function_response(part: dict) -> str:
    r = part["functionResponse"].get("response")
    return str(r.get("output") or r.get("error") or "") if isinstance(r, dict) else str(r or "")


def _gemini_project(path: str) -> str:
    """The folder the session ran in: the recording's header no longer names it, a `.project_root` file next to `chats/` does."""
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(path)), ".project_root"), encoding="utf-8", errors="ignore") as fh:
            return fh.read().strip()
    except OSError:
        return ""


MOVED_TO_BACKGROUND = re.compile(r"moved to background \(PID: (\d+)\)")


def _merge_gemini_subagents(path: str, turns: list) -> None:
    """A subagent records its work in chats/<the session's id>/<its id>.jsonl (header `kind: subagent`). Its tool calls are placed in the turn they happened in."""
    import glob
    from .claude_code import merge_into_turns
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            sid = json.loads(fh.readline()).get("sessionId")
    except (OSError, ValueError, AttributeError):
        return
    if not isinstance(sid, str) or not sid:
        return
    events = []
    for f in sorted(glob.glob(os.path.join(glob.escape(os.path.dirname(path)), glob.escape(sid), "*.jsonl"))):
        agent_id = os.path.splitext(os.path.basename(f))[0]
        found = [e for t in gemini_parse(f, subagents=False) for e in t.events if e.kind == "tool" and e.ts]
        for e in found:
            e.via = f"subagent:{agent_id}"
        events.extend(found)
    if events and merge_into_turns(turns, events):
        for t in turns:
            for e in t.events:
                if e.kind == "tool" and e.name == "Agent":
                    e.name = "Agent:read"


def gemini_parse(path: str, start: int = 0, subagents: bool = True):
    """Gemini CLI chat recording: message records (type user | gemini) with content parts and, for gemini, toolCalls[{name,args,result,status}]."""
    from .claude_code import Event, Turn, clip_output
    session = os.path.splitext(os.path.basename(path))[0].replace("session-", "")[:40]
    turns: list[Turn] = []
    cur: Turn | None = None
    model = ""
    project = _gemini_project(path)
    compressed = False
    background: dict[str, Event] = {}   # the PID of a command moved to the background -> the command
    records = list(_gemini_records(path, start))
    latest = {r["id"]: i for i, r in enumerate(records) if isinstance(r.get("id"), str)}   # a record is updated by appending it again under the same id
    for i, r in enumerate(records):
        if "$patch" in r or "$set" in r or "$rewindTo" in r or latest.get(r["id"] if isinstance(r.get("id"), str) else "", i) != i:
            continue
        if isinstance(r.get("projectHash"), str) and not r.get("type"):
            dirs = r.get("directories")
            project = str(dirs[0]) if isinstance(dirs, list) and dirs else project
            continue
        t = r.get("type")
        ts = str(r.get("timestamp") or "")
        if t == "user":
            content = r.get("content")
            if isinstance(content, list) and any(isinstance(p, dict) and "functionResponse" in p for p in content):
                continue   # a tool's result is sent back as a `user` record: the same turn goes on
            text = _parts_text(content).lstrip()
            if text.startswith("<session_context>"):
                continue   # the CLI's own preamble, not a prompt
            if text.startswith(GEMINI_INJECTED):   # a compression or a loop warning happens inside the turn
                compressed = compressed or text.startswith("<state_snapshot>")
                if cur is not None:
                    cur.events.append(Event("mark", name="notice" if text.startswith("<state_snapshot>") else "meta", text=text[:1500], ts=ts))
                continue
            if compressed and cur is not None and _parts_text(content)[:200] == cur.prompt:
                compressed = False   # compression records the prompt it is answering again
                continue
            if cur is not None:
                turns.append(cur)
            compressed = False
            cur = Turn(session=session, index=len(turns), version=model, prompt=_parts_text(content)[:200], ts=ts, agent="gemini", model=model, project=project)
        elif t == "gemini":
            if cur is None:
                cur = Turn(session=session, index=0, version=model, prompt="", ts=ts, agent="gemini", project=project)
            if isinstance(r.get("model"), str) and not cur.model:
                cur.model = model = r["model"]
            calls = r.get("toolCalls")
            for call in calls if isinstance(calls, list) else []:
                if not isinstance(call, dict):
                    continue
                ev = _tool_event(str(call.get("name") or ""), call.get("args"), ts)
                res, code = _gemini_result(call.get("result"))
                ev.result = clip_output(res)
                st = str(call.get("status") or "").lower()
                ev.is_error = True if st in ("error", "failed", "cancelled") else (False if st in ("success", "ok", "done") else None)
                if code is not None:
                    ev.is_error = code != 0   # the call itself is "success" when the command ran and failed
                if ev.name == "invoke_agent":
                    ev.name = "Agent"   # work this record cannot see, until the subagent's own record is read
                moved = MOVED_TO_BACKGROUND.search(res[:300])
                if moved and ev.name == "Bash":
                    background[moved.group(1)] = ev
                    ev.task, ev.running = moved.group(1), True
                args = call.get("args") if isinstance(call.get("args"), dict) else {}
                command = background.get(str(args.get("pid"))) if ev.name == "read_background_output" else None
                if command is not None and res.strip():   # the command's own output, whenever it was asked for
                    command.result, command.running = clip_output(re.sub(r"^Full Log Output:\n?", "", res)), False
                cur.events.append(ev)
            text = _parts_text(r.get("content"))
            if text.strip():
                cur.events.append(Event("text", text=text, ts=ts))
    if cur is not None:
        turns.append(cur)
    if subagents and turns:
        _merge_gemini_subagents(path, turns)
    return turns


# ------------------------------------------------------------ hook payloads
TEXT_FIELDS = ("cwd", "transcript_path", "last_assistant_message", "model")


def normalize(agent: str, which: str, data: dict) -> dict:
    """The fields the two hooks need, whatever the assistant calls them. A field of the wrong type is dropped: the rest can still be checked."""
    d = {k: v for k, v in data.items() if k not in TEXT_FIELDS or isinstance(v, str)}
    if agent == "cursor":
        roots = d.get("workspace_roots")
        d.setdefault("cwd", roots[0] if isinstance(roots, list) and roots and isinstance(roots[0], str) else "")
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
            if str(d.get("tool_name") or "") in EDIT_TOOLS or str(cmd).lstrip().startswith("*** Begin Patch"):
                return d   # an edit's text is what it writes, never a command: apply_patch hands its whole patch over as `command`
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


def warn(agent: str, plain: str) -> dict | None:
    """A message for the user that does not stop the assistant (used when a held reply is answered without evidence)."""
    if agent == "cursor":
        return None   # Cursor's stop hook can only send the agent another turn, which would be a second block
    return {"systemMessage": plain}


def parser_for(agent: str, tail: bool = False, light: bool = False):
    """Transcript parser for an agent. tail=True (the Stop hook) reads a big file from its last two prompts on;
    light=True reads a fixed tail, for when only the names in a message are wanted."""
    from . import claude_code, codex
    if agent == "claude-code" or agent not in ("codex", "cursor", "gemini"):
        if light:
            return lambda p: claude_code.parse_session(p, light=True)
        return (lambda p: claude_code.parse_session(p, tail=True)) if tail else claude_code.parse_session
    parse, is_prompt = {"codex": (codex.parse_session, codex.is_prompt_row), "cursor": (cursor_parse, _cursor_prompt_row), "gemini": (gemini_parse, _gemini_prompt_row)}[agent]
    if not (tail or light):
        return parse
    def parse_tail(path: str):
        whole_json = agent == "gemini" and path.endswith(".json")
        return parse(path, 0 if whole_json else claude_code.tail_start(path, is_prompt, light=light))
    return parse_tail


# --------------------------------------------------------------- installers
def config_path(agent: str) -> str:
    if agent == "claude-code":
        from .hooks import settings_path
        return settings_path()
    if agent == "codex":
        return os.path.join(_codex_home(), "hooks.json")
    return os.path.join(os.path.expanduser("~"), *{"cursor": (".cursor", "hooks.json"), "gemini": (".gemini", "settings.json")}[agent])


def _codex_home() -> str:
    return os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")


def codex_hook_hash(group: dict, event: str) -> str:
    """The hash Codex (0.167) stores for a hook someone trusted, in `[hooks.state."<hooks.json>:<event>:<group>:<hook>"]` of its config.toml.
    A hook whose line changed, say after installing honestly somewhere else, no longer matches, and Codex stops running it until it is reviewed again."""
    import hashlib
    hook = next(h for h in group.get("hooks") or [] if _is_ours(h))
    identity = {"event_name": event, "hooks": [{"async": False, "command": hook.get("command"), "timeout": hook.get("timeout"), "type": "command"}]}
    if event != "stop":   # Codex does not match on Stop
        identity["matcher"] = group.get("matcher", "")
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def codex_trust() -> tuple:
    """(state, detail) of honestly's hooks in Codex: "trusted"; "untrusted", never reviewed; "changed", reviewed but the hook line is different now; "unknown", could not read.
    Codex silently skips a hook in the last two states, and `codex exec` never asks."""
    try:
        with open(config_path("codex"), encoding="utf-8") as fh:
            hooks = (json.load(fh).get("hooks") or {})
    except (OSError, ValueError, AttributeError):
        return "unknown", ""
    try:
        with open(os.path.join(_codex_home(), "config.toml"), encoding="utf-8", errors="replace") as fh:
            config = fh.read()
    except FileNotFoundError:
        config = ""
    except OSError:
        return "unknown", ""
    state = "trusted"
    for event, key in (("Stop", "stop"), ("PreToolUse", "pre_tool_use")):
        groups = hooks.get(event) if isinstance(hooks.get(event), list) else []
        at = next((i for i, g in enumerate(groups) if isinstance(g, dict) and any(_is_ours(h) for h in g.get("hooks") or [])), None)
        if at is None:
            continue
        hook_at = next(i for i, h in enumerate(groups[at]["hooks"]) if _is_ours(h))
        m = re.search(r'\[hooks\.state\."[^"\n]*hooks\.json:' + key + f":{at}:{hook_at}" + r'"\]\s*\n\s*trusted_hash\s*=\s*"sha256:([0-9a-f]+)"', config)
        if not m:
            return "untrusted", key
        if m.group(1) != codex_hook_hash(groups[at], key):
            state = "changed"
    return state, ""


CODEX_REVIEW = "open `codex` once and choose \"Trust all and continue\" (or run /hooks inside it)"


def _is_ours(h) -> bool:
    return hookline.is_ours(h)


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


def installed(agent: str) -> list[str]:
    from . import guardfile
    try:
        _, _, _, obj = guardfile.read(config_path(agent))
    except guardfile.Refused:
        return []
    return guardfile.hook_events(obj, agent == "cursor")


def guard(agent: str, action: str, exe: str, dry_run: bool = False) -> str:
    """install | uninstall | status for codex, cursor or gemini. The file is backed up first; only our own entries are touched."""
    from . import hooks as _hooks
    path = config_path(agent)
    name = NAMES[agent]
    flat = agent == "cursor"
    if action == "status":
        line = _hooks._status_line(name, path, flat)
        if agent == "codex" and installed(agent) and codex_trust()[0] in ("untrusted", "changed"):
            line += f"; Codex will not run them until you {CODEX_REVIEW}"
        return line
    top = {"version": 1} if flat else None
    result, after = _hooks._guard_edit(name, path, action, entries(agent, exe) if action == "install" else {}, dry_run, flat, top)
    if dry_run:
        return f"honestly guard would write this `hooks` section into {path}:\n" + json.dumps({"hooks": after.get("hooks", {})}, ensure_ascii=False, indent=2)
    if result == "unchanged":
        return (f"honestly guard ({name}): already installed, nothing changed ({path})" if action == "install"
                else f"honestly guard ({name}): not installed, nothing to remove ({path})")
    note = {"codex": f"  Codex does not run a new or changed hook until you trust it, and `codex exec` skips it without a word: {CODEX_REVIEW}.",
            "cursor": "  Cursor shows hook-visible transcripts only when they are enabled; the stop hook needs them to see what was said.",
            "gemini": ""}[agent]
    return f"honestly guard ({name}): {action}ed → {path}" + ("\n" + note if note and action == "install" else "")
