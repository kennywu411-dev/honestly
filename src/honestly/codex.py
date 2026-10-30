"""Parse Codex (OpenAI) session logs (~/.codex/sessions/**/rollout-*.jsonl) into turns.

Codex writes `response_item` records: messages (user/assistant/developer), `custom_tool_call`
(name "exec" with a JS-ish input holding cmd:"...", or "apply_patch" with a patch body) and their
`*_output` records, plus `function_call`/`function_call_output` for shell-style tools.
"""
from __future__ import annotations
import glob
import json
import os
import re
from .claude_code import Event, Turn

CMD_IN_INPUT = re.compile(r"cmd\s*:\s*\"((?:\\.|[^\"\\])*)\"")
PATCH_FILES = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", re.M)


def iter_sessions(root: str | None = None):
    root = root or os.path.expanduser("~/.codex/sessions")
    yield from sorted(glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True))


def _unescape(s: str) -> str:
    try:
        return json.loads('"' + s + '"')
    except Exception:
        return s.replace('\\"', '"').replace("\\n", "\n")


def _dig(d, *keys):
    """d[k1][k2]... when every level is a dict and the leaf is a string, else None."""
    for k in keys:
        d = d.get(k) if isinstance(d, dict) else None
    return d if isinstance(d, str) else None


def _command_from_call(name: str, payload: dict) -> tuple[str, str]:
    """Return (tool_kind, text) where tool_kind is Bash / Edit / other."""
    inp0 = payload.get("input")
    if isinstance(inp0, str) and CMD_IN_INPUT.search(inp0):
        name = "exec"   # the desktop app wraps shell calls in a JS runner; the cmd is what matters
    if name in ("exec", "shell", "shell_command", "exec_command", "container.exec", "local_shell"):   # desktop app + Codex CLI names
        inp = payload.get("input")
        args = payload.get("arguments")
        if isinstance(inp, str):
            m = CMD_IN_INPUT.search(inp)
            if m:
                return "Bash", _unescape(m.group(1))
            return "Bash", inp
        if isinstance(args, str):
            try:
                a = json.loads(args)
            except Exception:
                return "Bash", args
            if not isinstance(a, dict):
                return "Bash", args
            cmd = a.get("cmd") or a.get("command") or ""
            if isinstance(cmd, list):
                cmd = " ".join(str(x) for x in cmd if x is not None)
            return "Bash", str(cmd)
        return "Bash", ""
    if name == "apply_patch":
        body = payload.get("input") or payload.get("arguments") or ""
        if isinstance(body, str) and body.startswith("{"):
            try:
                body = json.loads(body).get("patch", body)
            except Exception:
                pass
        files = PATCH_FILES.findall(body if isinstance(body, str) else "")
        return "Edit", " ".join(files) or "patch"
    return name or "tool", ""


def parse_session(path: str):
    session = os.path.splitext(os.path.basename(path))[0].replace("rollout-", "")[:40]
    turns: list[Turn] = []
    cur: Turn | None = None
    model = ""
    project = ""
    pending: dict[str, Event] = {}   # call_id -> event, to attach outputs
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if not isinstance(r, dict):
                continue
            t = r.get("type")
            p = r.get("payload") if isinstance(r.get("payload"), dict) else {}
            ts = str(r.get("timestamp") or "")
            if t in ("turn_context", "session_meta") and isinstance(p.get("cwd"), str):
                project = p["cwd"]
            if t in ("turn_context", "world_state", "session_meta"):
                m = (_dig(p, "model") or _dig(p, "state", "collaboration_mode", "model")
                     or _dig(p, "collaboration_mode", "model") or _dig(p, "model_name"))
                model = m or model
                if cur is not None and not cur.model:
                    cur.model = model; cur.version = model
                continue
            item = p.get("item") if isinstance(p.get("item"), dict) else {}
            if t == "event_msg" and p.get("type") == "item_completed" and item.get("type") == "UserMessage":
                text = " ".join(str(c.get("text") or "") for c in (item.get("content") or []) if isinstance(c, dict))
                if cur is not None:
                    turns.append(cur)
                cur = Turn(session=session, index=len(turns), version=model, prompt=text[:200], ts=ts, agent="codex", model=model, project=project)
                continue
            if t != "response_item":
                continue
            kind = p.get("type")
            if cur is None:
                cur = Turn(session=session, index=0, version=model, prompt="", ts=ts, agent="codex", model=model)
            if kind == "message" and p.get("role") == "assistant":
                text = " ".join(str(c.get("text") or "") for c in (p.get("content") or []) if isinstance(c, dict))
                if text.strip():
                    cur.events.append(Event("text", text=text, ts=ts))
            elif kind in ("custom_tool_call", "function_call"):
                tool, text = _command_from_call(str(p.get("name") or ""), p)
                ev = Event("tool", name=tool, text=text, tool_use_id=str(p.get("call_id") or ""), ts=ts)
                cur.events.append(ev)
                if ev.tool_use_id:
                    pending[ev.tool_use_id] = ev
            elif kind in ("custom_tool_call_output", "function_call_output"):
                out = p.get("output")
                if isinstance(out, list):
                    out = " ".join(str(c.get("text") or "") for c in out if isinstance(c, dict))
                out = str(out or "")
                ev = pending.get(str(p.get("call_id") or ""))
                if ev is not None:
                    ev.result = out[:3000]
                    ev.is_error = bool(re.search(r"(exit(?:ed with)? code:? [1-9]|\"exit_code\":\s*[1-9]|Traceback|command not found|No such file|^Script failed|Command blocked by)", out[:500], re.I | re.M))
    if cur is not None:
        turns.append(cur)
    return turns
