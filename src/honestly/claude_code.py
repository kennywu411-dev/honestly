"""Parse Claude Code session logs (~/.claude/projects/**/*.jsonl) into turns.

A turn = everything the assistant did between two human prompts.
Events are kept in order: text blocks, tool calls (with result status),
so rules can ask "what happened after the last edit?".
"""
from __future__ import annotations
import glob
import json
import os
import re
from dataclasses import dataclass, field


@dataclass
class Event:
    kind: str            # text | tool
    name: str = ""       # tool name for kind=tool
    text: str = ""       # text block, or command/path summary for tools
    tool_use_id: str = ""
    is_error: bool | None = None
    ts: str = ""
    result: str = ""
    via: str = ""       # 'subagent:<id>' when the event ran inside a subagent and was merged into the parent turn


@dataclass
class Turn:
    session: str
    index: int
    version: str
    prompt: str
    events: list = field(default_factory=list)
    ts: str = ""
    agent: str = "claude-code"
    model: str = ""
    project: str = ""


def _summarize_input(name: str, inp) -> str:
    if not isinstance(inp, dict):
        return ""
    if name == "Bash":
        return inp.get("command", "") or ""
    for k in ("file_path", "path", "notebook_path", "url", "pattern", "query", "prompt", "description"):
        if k in inp:
            return str(inp[k])
    return ""


def iter_sessions(root: str | None = None):
    root = root or os.path.expanduser("~/.claude/projects")
    for path in sorted(glob.glob(os.path.join(root, "*", "*.jsonl"))):
        yield path


BG_OUTPUT = re.compile(r"Output is being written to:\s*(\S+\.output)")


def _records(path: str, start: int = 0):
    """JSON records of a transcript; with start > 0 reading begins at that byte offset, after the next newline."""
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


def _tool_result_text(b: dict) -> str:
    rc = b.get("content")
    if isinstance(rc, list):
        rc = " ".join(str(x.get("text") or "") for x in rc if isinstance(x, dict))
    rc = rc or ""
    m = BG_OUTPUT.search(rc)
    if m and os.path.exists(m.group(1)):   # a background command: its real output is in the task file, when it still exists
        try:
            with open(m.group(1), encoding="utf-8", errors="ignore") as fh:
                out = fh.read()
            if out.strip():
                rc = out[-3000:]
        except Exception:
            pass
    return rc[:3000]


def _parse(path: str, sidechain: bool = False, start: int = 0):
    """Turns of one transcript. sidechain=True reads a subagent file (every record there is marked isSidechain)."""
    session = os.path.splitext(os.path.basename(path))[0]
    turns: list[Turn] = []
    cur: Turn | None = None
    results: dict[str, tuple] = {}   # tool_use_id -> (is_error, text)
    version = ""
    project = ""
    for r in _records(path, start):
        if bool(r.get("isSidechain")) != sidechain:
            continue  # subagent lines live in their own files; keep each thread separate
        t = r.get("type")
        version = r.get("version") if isinstance(r.get("version"), str) else version
        project = r.get("cwd") if isinstance(r.get("cwd"), str) else project
        msg = r.get("message") if isinstance(r.get("message"), dict) else {}
        origin = r.get("origin") if isinstance(r.get("origin"), dict) else {}
        ts = str(r.get("timestamp") or "")
        content = msg.get("content")
        if t == "user":
            human = origin.get("kind") == "human" or isinstance(content, str)
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        results[b.get("tool_use_id", "")] = (bool(b.get("is_error")), _tool_result_text(b))
                if any(isinstance(b, dict) and b.get("type") == "text" for b in content) and origin.get("kind") == "human":
                    human = True
            if human:
                prompt = content if isinstance(content, str) else " ".join(
                    str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text")
                if cur is not None:
                    turns.append(cur)
                cur = Turn(session=session, index=len(turns), version=version, prompt=prompt[:200], ts=ts, project=project)
        elif t == "assistant" and isinstance(content, list):
            if cur is None:
                cur = Turn(session=session, index=0, version=version, prompt="", ts=ts)
            if isinstance(msg.get("model"), str) and not cur.model:
                cur.model = msg["model"]
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    cur.events.append(Event("text", text=str(b.get("text") or ""), ts=ts))
                elif b.get("type") == "tool_use":
                    cur.events.append(Event("tool", name=str(b.get("name") or ""), text=_summarize_input(str(b.get("name") or ""), b.get("input")),
                                           tool_use_id=str(b.get("id") or ""), ts=ts))
    if cur is not None:
        turns.append(cur)
    for turn in turns:
        for e in turn.events:
            if e.kind == "tool" and e.tool_use_id in results:
                e.is_error, e.result = results[e.tool_use_id]
    return turns


def subagent_files(path: str) -> list[str]:
    """Subagent transcripts of a session: <session-dir>/subagents/agent-*.jsonl (workflow agents one level deeper)."""
    d = os.path.join(os.path.splitext(path)[0], "subagents")
    if not os.path.isdir(d):
        return []
    return sorted(glob.glob(os.path.join(d, "agent-*.jsonl")) + glob.glob(os.path.join(d, "workflows", "*", "agent-*.jsonl")))


def _iso_epoch(ts: str) -> float:
    import datetime
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _merge_subagents(path: str, turns: list, since_ts: str = "") -> int:
    """Put every tool call a subagent made into the parent turn, in timestamp order, so a test the subagent ran counts and an
    edit it made is seen. The Agent call that spawned it is then no longer opaque. Returns the number of merged events."""
    merged = 0
    by_tool_use = {}
    since = _iso_epoch(since_ts) - 120 if since_ts else 0.0
    for f in subagent_files(path):
        if since and os.path.getmtime(f) < since:
            continue   # finished before the window we hold: nothing of it can land in these turns
        agent_id = os.path.basename(f)[len("agent-"):-len(".jsonl")]
        meta = {}
        try:
            with open(f[:-len(".jsonl")] + ".meta.json", encoding="utf-8") as fh:
                meta = json.load(fh)
        except Exception:
            pass
        events = [e for t in _parse(f, sidechain=True) for e in t.events if e.kind == "tool" and e.ts]
        if not events:
            continue
        bg = str(meta.get("requestShape") or "") == "background"
        for e in events:
            e.via = f"subagent{'-bg' if bg else ''}:{agent_id}"   # a background subagent runs alongside the parent: its edits do not stale the parent's checks
        by_tool_use[str(meta.get("toolUseId") or "")] = len(events)
        for e in events:
            turn = None
            for t in turns:
                if t.ts and t.ts <= e.ts:
                    turn = t
            if turn is None:
                continue   # earlier than every turn we hold (tail parse): not ours to place
            pos = next((i for i, x in enumerate(turn.events) if x.ts and x.ts > e.ts), len(turn.events))
            turn.events.insert(pos, e)
            merged += 1
    if by_tool_use:
        for t in turns:
            for e in t.events:
                if e.kind == "tool" and e.name in ("Agent", "Task") and by_tool_use.get(e.tool_use_id):
                    e.name = e.name + ":read"   # its transcript was read and merged: not opaque any more
    return merged


TAIL_THRESHOLD = 8 * 1024 * 1024
TAIL_WINDOW = 3 * 1024 * 1024


def parse_session(path: str, subagents: bool = True, tail: bool = False, min_turns: int = 2):
    """All turns of a session. tail=True (the hooks) reads only the end of a big file: a window from the end, doubled
    until it holds min_turns user turns, so a 200 MB session costs the same as a small one."""
    start = 0
    if tail:
        size = os.path.getsize(path)
        if size > TAIL_THRESHOLD:
            window = TAIL_WINDOW
            while True:
                start = max(0, size - window)
                turns = _parse(path, start=start)
                if start == 0 or sum(1 for t in turns if t.prompt) >= min_turns:
                    break
                window *= 2
            if start > 0 and turns and not turns[0].prompt:
                turns = turns[1:]   # the first turn in the window began before it: incomplete, drop it
            if subagents and turns:
                _merge_subagents(path, turns, turns[0].ts)
            return turns
    turns = _parse(path)
    if subagents and turns:
        _merge_subagents(path, turns)
    return turns
