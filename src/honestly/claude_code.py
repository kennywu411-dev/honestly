"""Parse Claude Code session logs (~/.claude/projects/**/*.jsonl) into turns.

A turn = everything the assistant did between two prompts a person wrote. A task notification, a compaction summary or
another session's message arrives as a `user` record too, and stays inside the turn as a "mark" event.
Events are kept in order: text blocks, tool calls (with result status),
so rules can ask "what happened after the last edit?".
"""
from __future__ import annotations
import bisect
import glob
import json
import os
import re
import stat
from dataclasses import dataclass, field
from .hookline import claude_dir


@dataclass
class Event:
    kind: str            # text | tool | mark (something arrived mid-turn: name "report" is someone else's work, name "notice" this session's own)
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


def _tool_name(name) -> str:
    """The PowerShell tool takes the same `command` input as Bash and is Claude Code's main shell on Windows; the rules read one shell."""
    return "Bash" if name == "PowerShell" else str(name or "")


def _summarize_input(name: str, inp) -> str:
    if not isinstance(inp, dict):
        return ""
    if name == "Bash":
        command = inp.get("command")
        return command if isinstance(command, str) else ""
    for k in ("file_path", "path", "notebook_path", "url", "pattern", "query", "prompt", "description"):
        if k in inp:
            return str(inp[k])
    return ""


def projects_root() -> str:
    return os.path.join(claude_dir(), "projects")


def iter_sessions(root: str | None = None):
    root = root or projects_root()
    for path in sorted(glob.glob(os.path.join(glob.escape(root), "*", "*.jsonl"))):
        if os.path.isfile(path):
            yield path


# The harness's whole message when a command goes to the background. A command can print these words too, so the message has
# to start with them, be short, and contain nothing a run prints.
BG_NOTICE = re.compile(r"\s*Command (?:running in background with ID: (?P<asked>[\w-]+)|was moved to the background \(ID: (?P<moved>[\w-]+)\)[^\n.]*)\.?"
                       r"(?:\s*Output is being written to:\s*(?P<path>\S+?\.output)(?=[\s.]|$))?")
BG_NOTICE_MAX = 1500
RUN_OUTPUT = re.compile(r"\b\d+ (?:passed|failed|errors?)\b|\bFAILED\b|Traceback \(most recent", re.I)
TASK_FILES_READ: set = set()   # what the parse read besides the log itself; the audit cache depends on these too


def background_notice(text: str):
    """The match when `text` is the harness saying a command went to the background, else None."""
    if not text or len(text) > BG_NOTICE_MAX or text.count("\n") > 3:
        return None
    m = BG_NOTICE.match(text)
    return m if m and not RUN_OUTPUT.search(text) else None


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


OUTPUT_KEEP = 3000
MIDDLE_SUMMARY = re.compile(r"\b\d+ (?:passed|failed|errors?|passing|failing)\b|test result:|^\s*Tests?:\s|^Ran \d+ tests?|^(?:OK|FAILED)\b", re.I)


def clip_output(text: str, keep: int = OUTPUT_KEEP) -> str:
    """Keep the start and, above all, the end of a tool's output: test runners print their pass/fail summary last,
    so a long verbose run cut from the front would lose the one line that decides the verdict."""
    text = text or ""
    if len(text) <= keep:
        return text
    head, tail = keep // 5, keep - keep // 5
    middle = text[head:-tail]
    summaries = [ln.strip()[:200] for ln in middle.splitlines() if MIDDLE_SUMMARY.search(ln)][-8:]   # another tool may print after the tests
    kept = ("\n".join(summaries) + "\n") if summaries else ""
    return text[:head] + "\n[... output clipped by honestly ...]\n" + kept + text[-tail:]


def _is_under(path: str, folder: str) -> bool:
    if not folder:
        return False
    real, base = os.path.realpath(path), os.path.realpath(folder)
    return real == base or real.startswith(base.rstrip(os.sep) + os.sep)


def _task_file_tail(path: str):
    """The end of a background command's output file, or None unless it is an ordinary file. Opening never blocks or follows a link."""
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0)
    if os.path.islink(path):   # Windows has no O_NOFOLLOW
        return None
    try:
        fd = os.open(path, flags)
    except (OSError, ValueError):
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):   # the job's whole log can be long: only the tail is used
            return None
        os.lseek(fd, max(0, info.st_size - 6000), os.SEEK_SET)
        return os.read(fd, 6000).decode("utf-8", "ignore")
    except OSError:
        return None
    finally:
        os.close(fd)


def _background_output(m, tool_input, project: str):
    """What a background command wrote, when the notice is the harness's own and names the harness's own task file, else None."""
    path, task = m.group("path"), m.group("asked") or m.group("moved")
    if not path or path.startswith(("\\\\", "//")) or not os.path.isabs(path):   # a network path would connect out, with the user's credentials on Windows
        return None
    if os.path.basename(path) != f"{task}.output" or os.path.basename(os.path.dirname(path)) != "tasks":
        return None
    if m.group("asked") and not (isinstance(tool_input, dict) and tool_input.get("run_in_background")):
        return None
    if _is_under(path, project):
        return None
    TASK_FILES_READ.add(path)
    return _task_file_tail(path)


def _tool_result_text(b: dict, tool: str = "", tool_input=None, project: str = "") -> str:
    rc = b.get("content")
    if isinstance(rc, list):
        rc = " ".join(str(x.get("text") or "") for x in rc if isinstance(x, dict))
    rc = rc or ""
    if tool == "Bash":
        m = background_notice(rc)
        out = _background_output(m, tool_input, project) if m else None
        if out and out.strip():
            rc = out[-3000:]
    return clip_output(rc)


# Records in a `user` row that no person typed, for transcripts too old to carry promptSource or turnOrigin.
NOT_TYPED = re.compile(r"\s*(?:<task-notification>|<local-command-|<command-(?:name|message|args)>|<bash-(?:input|stdout|stderr)>|This session is being continued from a previous conversation|Caveat: The messages below)")
# Someone else's report: a reply to it is about their work, and is not judged on what this session edited.
OUTSIDE_REPORT = re.compile(r"^\s*(?:<side-sessions-event>|<ci-monitor-event>|<agent-message|Another Claude session sent a message)|\bThe session\b.{0,200}\byou started\b|\bfinished a turn\b", re.S)
OWN_TASK = re.compile(r"<tool-use-id>([\w-]+)</tool-use-id>")


def _is_prompt(r: dict, content, origin: dict) -> bool:
    """A request a person made: what a turn starts with. Everything else that arrives as a `user` row (a tool's result, a task notification,
    a compaction summary, a skill's text, another session's message) happens inside the turn that person's request began."""
    if r.get("isMeta") and r.get("turnOrigin") != "scheduled":
        return False
    if r.get("isCompactSummary") or r.get("isVisibleInTranscriptOnly"):
        return False
    if origin.get("kind"):
        return origin["kind"] == "human" or r.get("turnOrigin") == "scheduled"   # a scheduled task carries a request of its own
    if r.get("promptSource") or r.get("turnOrigin"):
        return r.get("promptSource") != "system" or r.get("turnOrigin") == "scheduled"
    return isinstance(content, str) and not NOT_TYPED.match(content)   # an older transcript: a list held only tool results and skill text


def _mark(text: str, seen_calls: dict, peer: bool, compact: bool, ts: str) -> Event:
    """What a record that is not a prompt leaves in the turn. "report": someone else's work, a wall for what follows. "notice": this session's
    background task ended or its context was compacted, so the reply may sum up earlier work. "meta": anything else, a skill's text or a reminder."""
    head = text[:1500]
    task = head.lstrip().startswith("<task-notification>")
    own = OWN_TASK.search(head)
    if peer or OUTSIDE_REPORT.search(head) or (task and not (own and own.group(1) in seen_calls)):
        return Event("mark", name="report", text=head, ts=ts)
    return Event("mark", name="notice" if task or compact else "meta", text=head, ts=ts)


def _parse(path: str, sidechain: bool = False, start: int = 0):
    """Turns of one transcript. sidechain=True reads a subagent file (every record there is marked isSidechain)."""
    session = os.path.splitext(os.path.basename(path))[0]
    turns: list[Turn] = []
    cur: Turn | None = None
    results: dict[str, tuple] = {}   # tool_use_id -> (is_error, text)
    calls: dict[str, tuple] = {}     # tool_use_id -> (tool name, its input)
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
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        name, inp = calls.get(b.get("tool_use_id", ""), ("", None))
                        results[b.get("tool_use_id", "")] = (bool(b.get("is_error")), _tool_result_text(b, name, inp, project))
            text = content if isinstance(content, str) else " ".join(str(b.get("text") or "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")
            if not text.strip():
                continue
            if FEEDBACK.match(text) or _is_prompt(r, content, origin):
                if cur is not None:
                    turns.append(cur)
                cur = Turn(session=session, index=len(turns), version=version, prompt=text[:2000], ts=ts, project=project)
            else:
                if cur is None:   # a transcript that starts here: a tail read drops it, a whole one judges it as before
                    cur = Turn(session=session, index=len(turns), version=version, prompt=text[:2000] if start == 0 else "", ts=ts, project=project)
                else:
                    cur.events.append(_mark(text, calls, origin.get("kind") == "peer", bool(r.get("isCompactSummary")) or text.lstrip().startswith("This session is being continued"), ts))
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
                    calls[str(b.get("id") or "")] = (_tool_name(b.get("name")), b.get("input"))
                    cur.events.append(Event("tool", name=_tool_name(b.get("name")), text=_summarize_input(_tool_name(b.get("name")), b.get("input")),
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
    d = glob.escape(d)
    return sorted(f for f in glob.glob(os.path.join(d, "agent-*.jsonl")) + glob.glob(os.path.join(d, "workflows", "*", "agent-*.jsonl")) if os.path.isfile(f))


def _iso_epoch(ts: str) -> float:
    import datetime
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _merged_by_time(events: list, incoming: list) -> list:
    """`incoming` placed among `events`, each before the first event with a later timestamp. One pass: a subagent can make thousands of calls."""
    incoming = sorted(incoming, key=lambda e: e.ts)
    out, j = [], 0
    for x in events:
        if x.ts:
            while j < len(incoming) and incoming[j].ts < x.ts:
                out.append(incoming[j])
                j += 1
        out.append(x)
    out.extend(incoming[j:])
    return out


def _merge_subagents(path: str, turns: list, since_ts: str = "") -> int:
    """Put every tool call a subagent made into the parent turn, in timestamp order, so a test the subagent ran counts and an
    edit it made is seen. The Agent call that spawned it is then no longer opaque. Returns the number of merged events."""
    merged = 0
    by_tool_use = {}
    since = _iso_epoch(since_ts) - 120 if since_ts else 0.0
    starts = sorted((t.ts, i) for i, t in enumerate(turns) if t.ts)
    keys = [ts for ts, _ in starts]
    arriving: dict[int, list] = {}
    for f in subagent_files(path):
        try:
            if since and os.path.getmtime(f) < since:
                continue   # finished before the window we hold: nothing of it can land in these turns
            events = [e for t in _parse(f, sidechain=True) for e in t.events if e.kind == "tool" and e.ts]
        except Exception:
            continue   # one subagent's file that cannot be read costs that file, not the parent's whole turn
        agent_id = os.path.basename(f)[len("agent-"):-len(".jsonl")]
        meta = {}
        try:
            with open(f[:-len(".jsonl")] + ".meta.json", encoding="utf-8") as fh:
                meta = json.load(fh)
        except Exception:
            pass
        if not events:
            continue
        bg = str(meta.get("requestShape") or "") == "background"
        by_tool_use[str(meta.get("toolUseId") or "")] = len(events)
        for e in events:
            e.via = f"subagent{'-bg' if bg else ''}:{agent_id}"   # a background subagent runs alongside the parent: its edits do not stale the parent's checks
            at = bisect.bisect_right(keys, e.ts) - 1
            if at >= 0:   # else earlier than every turn we hold (tail parse): not ours to place
                arriving.setdefault(starts[at][1], []).append(e)
                merged += 1
    for i, incoming in arriving.items():
        turns[i].events = _merged_by_time(turns[i].events, incoming)
    if by_tool_use:
        for t in turns:
            for e in t.events:
                if e.kind == "tool" and e.name in ("Agent", "Task") and by_tool_use.get(e.tool_use_id):
                    e.name = e.name + ":read"   # its transcript was read and merged: not opaque any more
    return merged


FEEDBACK = re.compile(r"\s*(?:Stop hook feedback|⚠️ honestly)")   # a Stop hook sending the agent back: judged with the turn it answers, by hooks.stop_hook


TAIL_THRESHOLD = 8 * 1024 * 1024
TAIL_WINDOW = 3 * 1024 * 1024
SCAN_CHUNK = 4 * 1024 * 1024
USER_ROW = re.compile(rb'"type":\s*"user"')   # inside a tool's output these quotes are escaped, so a quoted transcript does not match


SESSION_SCAN_LIMIT = 200 * 1024 * 1024
NOT_ALL_HERE = ("being continued from a previous conversation", "Linked sessions now")   # the work may be in an earlier file or another session


def session_tools(path: str):
    """Every tool call in the whole transcript, for "did anything in this session ever do that?". Hooks read only the end of a big file, and this must
    not miss an action far back. None when it cannot be known: a file too big to scan in a hook, a session continued from an earlier one, or one
    with linked sessions whose work it may be reporting."""
    events = []
    try:
        if os.path.getsize(path) > SESSION_SCAN_LIMIT:
            return None
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if any(mark in line for mark in NOT_ALL_HERE):
                    return None
                if '"tool_use"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                msg = r.get("message") if isinstance(r, dict) else None
                content = msg.get("content") if isinstance(msg, dict) else None
                for b in content if isinstance(content, list) else []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        name = _tool_name(b.get("name"))
                        events.append(Event("tool", name=name, text=_summarize_input(name, b.get("input"))))
    except OSError:
        return None
    return events


def _claude_prompt_row(line: bytes) -> bool:
    return USER_ROW.search(line) is not None and b'"tool_result"' not in line


def prompt_offset(path: str, is_prompt, count: int) -> int:
    """Where the `count`-th last prompt's line starts, found by walking the file backwards without decoding any JSON; 0 when it has fewer."""
    found, pos, partial = 0, os.path.getsize(path), b""
    with open(path, "rb") as fh:
        while pos > 0:
            step = min(SCAN_CHUNK, pos)
            pos -= step
            fh.seek(pos)
            buf = fh.read(step) + partial
            if pos > 0:
                first = buf.find(b"\n")
                if first < 0:
                    partial = buf
                    continue
                partial, body, base = buf[:first], buf[first + 1:], pos + first + 1
            else:
                body, base, partial = buf, 0, b""
            end = len(body)
            while end > 0:
                start = body.rfind(b"\n", 0, end - 1) + 1
                if is_prompt(body[start:end]):
                    found += 1
                    if found >= count:
                        return base + start
                end = start
    return 0


def tail_start(path: str, is_prompt, count: int = 2, light: bool = False) -> int:
    """The `start` to give a parser: 0 for a file small enough to read whole. `light` is a fixed tail, for when only names are wanted."""
    size = os.path.getsize(path)
    if light:
        return max(0, size - TAIL_WINDOW)
    if size <= TAIL_THRESHOLD:
        return 0
    return max(0, prompt_offset(path, is_prompt, count) - 1)   # the parser drops what comes before the next newline


def parse_session(path: str, subagents: bool = True, tail: bool = False, min_turns: int = 2, light: bool = False):
    """All turns of a session. tail=True (the Stop hook) reads a big file from its min_turns-th last prompt: the turns themselves are read
    whole, however long, because the edit a claim is judged against can be anywhere in them. light=True reads a fixed tail, for names only."""
    if light:
        return _parse(path, start=tail_start(path, _claude_prompt_row, light=True))
    if tail and os.path.getsize(path) > TAIL_THRESHOLD:
        want = min_turns
        while True:
            start = tail_start(path, _claude_prompt_row, want)
            turns = _parse(path, start=start)
            if start == 0 or sum(1 for t in turns if t.prompt and not FEEDBACK.match(t.prompt)) >= min_turns:
                break
            want *= 4   # some user rows are not prompts: read further back
        if start > 0 and turns and not turns[0].prompt:
            turns = turns[1:]
        if subagents and turns:
            _merge_subagents(path, turns, turns[0].ts)
        return turns
    turns = _parse(path)
    if subagents and turns:
        _merge_subagents(path, turns)
    return turns
