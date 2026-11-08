"""`honestly pr-note`: the verification evidence behind a branch, as a block for the pull-request description.

It reads the local agent transcripts of this repository (Claude Code, Codex, Cursor, Gemini CLI) since the branch
left its base, finds the last code edit and the test/build commands that ran, and writes what they printed. A reviewer
sees "132 passed after the last edit" or "no test ran after the last edit" instead of the agent's word for it.
"""
from __future__ import annotations
import datetime as dt
import html
import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field

from . import audit, claude_code, codex, rules, verdicts
from . import agents as _ag
from .programs import program

START, END = "<!-- honestly:pr-note -->", "<!-- /honestly:pr-note -->"
SHELL = set(_ag.SHELL_TOOLS) | {"Bash"}


# ------------------------------------------------------------------ git
def _git(args: list, cwd: str) -> str:
    # settings in the repository's own .git/config that would run a program: a downloaded repository can come with one
    safe = ["-c", "log.showSignature=false", "-c", "core.fsmonitor=false", "-c", "core.sshCommand=", "-c", "diff.external="]
    r = subprocess.run([program("git"), *safe, *args], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def repo_root(cwd: str) -> str:
    root = _git(["rev-parse", "--show-toplevel"], cwd)
    if not root:
        raise SystemExit("honestly pr-note: not inside a git repository")
    return os.path.realpath(root)


def base_ref(root: str, base: str | None) -> str:
    if base:
        if base.startswith("-"):
            raise SystemExit(f"honestly pr-note: --base takes a branch, not {base!r}")
        return base
    head = _git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], root)   # origin/main
    if head and not head.startswith("-"):   # a ref can be named like an option, and this name goes on a git command line
        return head
    for cand in ("origin/main", "origin/master", "main", "master"):
        if _git(["rev-parse", "--verify", "--quiet", cand], root):
            return cand
    return ""


def _utc(iso: str) -> str:
    """Any ISO timestamp → 'YYYY-MM-DDTHH:MM:SS' in UTC, the form transcripts use, so strings compare."""
    d = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.astimezone()
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def window_start(root: str, base: str, since: str | None) -> tuple[str, str]:
    """(utc cutoff, how it was chosen). --since wins; otherwise the commit the branch grew from."""
    if since:
        m = re.fullmatch(r"(\d+)([mhdw])", since.strip())
        if m:
            secs = int(m.group(1)) * {"m": 60, "h": 3600, "d": 86400, "w": 604800}[m.group(2)]
            t = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=secs)
            return t.strftime("%Y-%m-%dT%H:%M:%S"), f"last {since}"
        try:
            return _utc(since), f"since {since}"
        except ValueError:
            raise SystemExit("honestly pr-note: --since takes 30m, 2h, 3d, 1w or an ISO time such as 2026-10-31T09:00") from None
    mb = _git(["merge-base", "HEAD", base], root) if base else ""
    ref = mb or "HEAD"
    when = _git(["log", "-1", "--format=%cI", ref], root)
    if not when:
        return "1970-01-01T00:00:00", "all history"
    label = f"since the branch left {base}" if mb and mb != _git(["rev-parse", "HEAD"], root) else "since the last commit"
    return _utc(when), label


# ------------------------------------------------------------- transcripts
def _encoded(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]", "-", path)


def _inside(project: str, root: str) -> bool:
    if not project:
        return False
    p = os.path.realpath(project)
    return p == root or p.startswith(root + os.sep)


def _recent(path: str, cutoff: str) -> bool:
    mtime = dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return mtime >= cutoff


def mentions(text: str, root: str) -> bool:
    """A command or path that names the repository (`cd ~/code/app && pytest`, an edit of /abs/app/x.py)."""
    if not text:
        return False
    home = os.path.expanduser("~")
    forms = {root}
    if root.startswith(home + os.sep):
        forms.add("~" + root[len(home):])
        forms.add("$HOME" + root[len(home):])
    return any(re.search(re.escape(f) + r"(?![\w.-])", text) for f in forms)


def _path_forms(root: str) -> list:
    home = os.path.expanduser("~")
    forms = [root]
    if root.startswith(home + os.sep):
        forms += ["~" + root[len(home):], "$HOME" + root[len(home):]]
    return forms


def _file_mentions(path: str, root: str) -> bool:
    """Cheap pre-filter for sessions opened elsewhere: does the raw file contain the repository path at all?"""
    needles = [f.encode("utf-8") for f in _path_forms(root)] + [json.dumps(f)[1:-1].encode("utf-8") for f in _path_forms(root)]
    keep = max(len(n) for n in needles)
    prev = b""
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(4 << 20)
            if not chunk:
                return False
            buf = prev + chunk
            if any(n in buf for n in needles):
                return True
            prev = buf[-keep:]


def relevant(e, turn, root: str) -> bool:
    return _inside(turn.project, root) or mentions(e.text, root)


def collect_turns(root: str, cutoff: str, agents=("claude-code", "codex", "cursor", "gemini"), claude_root=None, codex_root=None):
    """Turns that worked on this repository at or after the cutoff, grouped by session, oldest session first.
    A session opened in the repository counts whole; one opened elsewhere counts only for the turns that name it
    (`cd /path/to/repo && …`, an edit of a file under it)."""
    sessions = []
    if "claude-code" in agents:
        base = claude_root or claude_code.projects_root()
        enc = _encoded(root)
        for path in claude_code.iter_sessions(base):
            if not _recent(path, cutoff):
                continue
            d = os.path.basename(os.path.dirname(path))
            own = d == enc or d.startswith(enc + "-")
            if own or _file_mentions(path, root):
                sessions.append(claude_code.parse_session(path))
    if "codex" in agents:
        for path in codex.iter_sessions(codex_root):
            if _recent(path, cutoff) and _file_mentions(path, root):
                sessions.append(codex.parse_session(path))
    if "cursor" in agents:
        for path in _ag.cursor_sessions():
            if _recent(path, cutoff) and _file_mentions(path, root):
                sessions.append(_ag.cursor_parse(path))
    if "gemini" in agents:
        for path in _ag.gemini_sessions():
            if _recent(path, cutoff) and _file_mentions(path, root):
                sessions.append(_ag.gemini_parse(path))
    out = []
    for turns in sessions:
        kept = [t for t in turns if (t.ts or "") >= cutoff and (_inside(t.project, root) or any(relevant(e, t, root) for e in t.events))]
        if kept:
            out.append(kept)
    out.sort(key=lambda ts: ts[0].ts or "")
    return out


# -------------------------------------------------------------- the disk
def _epoch(ts: str):
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def _is_code(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in rules.CODE_EXT and not rules.path_is_doc(path) and os.path.basename(path) != ".honestly.json"


def _listed(args: list, root: str) -> list:
    return [p for p in _git(args + ["-z"], root).split("\0") if p]


def changed_after(root: str, ts: str) -> list:
    """Code files in this tree that changed after `ts`, whoever changed them: a person, a formatter, `git pull`, a merge, a
    branch switch. A file's time says it for edits. A rename keeps its time, so a path new to HEAD or renamed since is judged by
    its inode change time, and a deletion leaves no time at all, so it counts as changed: not knowing is not a pass."""
    since = _epoch(ts)
    if since is None:
        return []
    known = set(_listed(["ls-tree", "-r", "--name-only", "HEAD"], root))
    renamed = _listed(["log", "-m", "--diff-filter=R", "-M", "--name-only", "--format=", f"--since={ts}", "HEAD"], root)
    gone = _listed(["log", "-m", "--diff-filter=D", "-M", "--name-only", "--format=", f"--since={ts}", "HEAD"], root)
    gone += _listed(["diff", "--name-only", "--diff-filter=D", "-M"], root) + _listed(["diff", "--cached", "--name-only", "--diff-filter=D", "-M"], root)
    out = []
    for path in _listed(["ls-files", "--cached", "--others", "--exclude-standard"], root):
        if not _is_code(path):
            continue
        try:
            st = os.stat(os.path.join(root, path))
        except OSError:
            continue
        when = max(st.st_mtime, st.st_ctime) if path not in known or path in renamed else st.st_mtime
        if when > since:
            out.append(path)
    out += [p for p in gone if _is_code(p) and not os.path.exists(os.path.join(root, p))]
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- evidence
@dataclass
class Check:
    kind: str        # test | build
    command: str
    result: str      # passed | narrowed | failed | no tests | no result line
    line: str        # the summary line it printed
    ts: str
    after_edit: bool = False
    runner: str = ""   # which test tool, so a failure is only cleared by the same tool
    scope: tuple = ()  # what narrowed it (`-k x`, a file); empty for the whole suite


@dataclass
class Evidence:
    root: str
    window: str
    cutoff: str
    sessions: int = 0
    agents: list = field(default_factory=list)
    last_edit: str = ""
    last_edit_ts: str = ""
    edited_files: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    claims: dict = field(default_factory=dict)
    flagged: list = field(default_factory=list)
    changed: list = field(default_factory=list)   # code on disk that changed after the deciding test
    gone: list = field(default_factory=list)      # files the agent edited that are not in this working tree

    @property
    def after(self) -> list:
        return [c for c in self.checks if c.after_edit]

    @property
    def verdict(self) -> tuple:
        """(status, the check that decides it), from the transcript alone. A failure stands until the same tool passes on
        the same or a wider set of tests: a narrower run, another tool or a build says nothing about what failed."""
        if not self.last_edit:
            return "no-edit", None
        tests = [c for c in self.after if c.kind == "test"]
        if not tests:
            builds = self.after
            return ("no-test", builds[-1]) if builds else ("none", None)
        failing, passed, narrowed = [], None, None
        for c in tests:
            if c.result == "failed":
                failing.append(c)
            elif c.result in ("passed", "narrowed"):
                failing = [f for f in failing if not _covers(c, f)]
                if c.result == "passed":
                    passed = c
                else:
                    narrowed = c
        if failing:
            return "fail", failing[-1]
        if passed:
            return "pass", passed
        if narrowed:
            return "narrowed", narrowed
        return "unclear", tests[-1]

    @property
    def status(self) -> str:
        """pass | fail | none | no-test | narrowed | unclear | no-edit | stale | elsewhere.
        What is on disk can only take back a good result; a failure or a missing run stays what it is."""
        status = self.verdict[0]
        if status in ("pass", "narrowed"):
            if self.changed:
                return "stale"
            if self.last_edit in self.gone:
                return "elsewhere"
        return status


def _covers(run: Check, failed: Check) -> bool:
    return run.runner == failed.runner and (not run.scope or run.scope == failed.scope)


RUNNER_WRAP = re.compile(r"^(?:\S*/)?(?:python[\d.]*\s+-m\s+|uv run\s+(?:python[\d.]*\s+-m\s+)?|poetry run\s+(?:python[\d.]*\s+-m\s+)?|pipenv run\s+|npx\s+|bunx\s+)", re.I)
NARROW_VALUE = {"-k", "-m", "-t", "-g", "-p", "-run", "--run", "--grep", "--filter", "--package", "--testNamePattern", "--testPathPattern", "--tests"}
NARROW_FLAG = {"--lf", "--last-failed", "--changed", "--onlyChanged", "--only-changed", "--failed", "--bail-on-first"}
OTHER_VALUE = {"-n", "-c", "-o", "-j", "-p", "--tb", "--cov", "--timeout", "--reporter", "--config", "--maxfail", "--numprocesses", "--workers", "--durations", "--color", "--rootdir", "-w"}
WHOLE = {".", "./...", "...", "all", "tests", "test", "spec", "specs", "src"}
REDIRECT = re.compile(r"^\d?[<>]")


def scope_of(seg: str, root: str = "") -> tuple:
    """(runner, what narrows it). A top-level folder such as `tests/` is the whole suite; a file, a deeper folder or a filter is not."""
    head = rules.pipe_stages(seg.strip().split("\n")[0])[0]
    m = rules.VERIFY["test"].search(head)
    if not m:
        return head.strip(), ()
    runner = RUNNER_WRAP.sub("", m.group(0).strip()).lower()
    try:
        toks = shlex.split(head[m.end():])
    except ValueError:
        toks = head[m.end():].split()
    scope, i = [], 0
    while i < len(toks):
        t = toks[i]
        i += 1
        name = t.split("=", 1)[0]
        if REDIRECT.match(t) or t == "--":
            i += t in (">", ">>", "2>", "2>>")
        elif name in NARROW_FLAG:
            scope.append(t)
        elif name in NARROW_VALUE:
            scope.append(t)
            if "=" not in t and i < len(toks):
                scope.append(toks[i])
                i += 1
        elif t.startswith("-"):
            if name in OTHER_VALUE and "=" not in t and i < len(toks) and not toks[i].startswith("-"):
                i += 1
        else:
            target = t.rstrip("/")
            top_level = root and "/" not in target and os.path.isdir(os.path.join(root, target))
            if target not in WHOLE and not top_level and not t.isdigit():
                scope.append(t)
    return runner, tuple(scope)


def _summary_line(kind: str, out: str) -> str:
    out = out or ""
    line = verdicts.summary_line(out) if kind == "test" else ""
    if not line:
        lines = [l.strip() for l in out.strip().splitlines() if l.strip() and not l.strip().startswith(("[", "Output is being"))]
        line = lines[-1] if lines else ""
    return re.sub(r"\s+", " ", line).strip(" =")[:120]


CI_READ = re.compile(r"\bgh (?:pr checks|run (?:view|list|watch))\b|statusCheckRollup", re.I)   # a remote run's status, not a run on this tree


def _judge(kind: str, seg: str, e, root: str = "") -> str:
    if CI_READ.search(seg):
        return "no result line"
    verdict, why = audit.judge_output("tests_pass" if kind == "test" else "build_ok", seg, e)
    if verdict == "backed":
        return "narrowed" if kind == "test" and scope_of(seg, root)[1] else "passed"
    if verdict == "contradicted":
        return "failed"
    if verdict == "unbacked":
        if "no tests" in why:
            return "no tests"
        return "failed" if e.is_error or "errored" in why else "no result line"   # a pipe that hid the result says nothing either way
    return "narrowed" if why.startswith("narrowed") else "no result line"


CD = re.compile(r"(?:^|[;{]|\bdo|\bthen|\belse)\s*cd\s+(\"[^\"]+\"|'[^']+'|[^\s;&|]+)")


def _expand(path: str) -> str:
    path = path.strip("\"'")
    if path.startswith("$HOME"):
        path = "~" + path[5:]
    return os.path.expanduser(path)


def _walk(e, turn):
    """Each segment of a shell command with the directory it runs in: the last `cd` before it, else the session's
    directory; "" when that `cd` cannot be resolved (`for d in a b; do cd $d`)."""
    where, unresolved = turn.project or "", False
    for seg in rules.segments(e.text):
        cds = CD.findall(seg.text.split("\n")[0])
        if cds:
            arg = cds[-1]
            unresolved = "$" in arg.replace("$HOME", "")
            if not unresolved:
                d = _expand(arg)
                where = d if os.path.isabs(d) else os.path.join(where, d)
        yield seg, ("" if unresolved else where)


def _here(where: str, e, root: str) -> bool:
    return _inside(os.path.realpath(where), root) if where else mentions(e.text, root)


def _edit_place(e, turn) -> tuple:
    """(target file or "", directory the edit ran in or "") for a code edit."""
    if e.name in rules.EDIT_TOOLS or e.name in _ag.EDIT_TOOLS:
        return e.text.strip().split("\n")[0], turn.project or ""
    last_where = turn.project or ""
    for seg, where in _walk(e, turn):
        last_where = where
        if rules.segment_is_edit(seg, e.text):
            targets = [t for t in rules.segment_targets(seg, e.text) if re.search(r"[./]", t) and t not in SHELL_WORDS]
            if not targets:   # `sed -i … gate.py; done`: take the last file-looking word of the editing line
                exts = "|".join(re.escape(x[1:]) for x in sorted(rules.CODE_EXT, key=len, reverse=True))
                targets = re.findall(r"(?<![\w'\"/])([\w./~-]+\.(?:" + exts + r"))(?![\w])", seg.text.split("\n")[0])[-1:]
            return (targets[0] if targets else ""), where
    return "", last_where


SHELL_WORDS = {"done", "fi", "then", "do", "else", "esac", "EOF"}
ENV_PREFIX = re.compile(r"^(\s*(?:export\s+)?\w+=(\$\([^)]*\)|\"[^\"]*\"|'[^']*'|\S+)\s+)+")   # `HOME=$(mktemp -d) pytest` shows as `pytest`


def _show(seg: str) -> str:
    seg = ENV_PREFIX.sub("", seg.strip().split("\n")[0])
    if re.match(r"git commit\b", seg):
        return "git commit (its pre-commit hook ran the checks)"
    return seg


def edit_in_repo(e, turn, root: str) -> str | None:
    """The edited file relative to the repository (or "a shell edit"), or None when the edit was somewhere else."""
    target, where = _edit_place(e, turn)
    if target:
        p = _expand(target)
        if not os.path.isabs(p):
            if not where:
                return target if mentions(e.text, root) else None
            p = os.path.join(where, p)
        p = os.path.realpath(p)
        return os.path.relpath(p, root) if _inside(p, root) else None
    if where:
        return "a shell edit" if _inside(os.path.realpath(where), root) else None
    return "a shell edit" if mentions(e.text, root) else None   # `for d in repo other; do cd $d && …`


def gather(root: str, cutoff: str, window: str, sessions_turns: list) -> Evidence:
    ev = Evidence(root=root, window=window, cutoff=cutoff, sessions=len(sessions_turns))
    events = []          # (ts, event, edited file or None) across sessions, in time order
    owner = {}           # id(event) -> its turn
    findings = []
    for turns in sessions_turns:
        ag = turns[0].agent
        if ag not in ev.agents:
            ev.agents.append(ag)
        findings.extend(audit.audit_turns(turns))
        for t in turns:
            for e in t.events:
                if e.kind != "tool":
                    continue
                owner[id(e)] = t
                target = edit_in_repo(e, t, root) if audit._is_edit(e) else None
                if target is not None or relevant(e, t, root):
                    events.append((e.ts or t.ts or "", e, target))   # target None: not an edit of this repository
    events.sort(key=lambda x: x[0])
    edited = []
    last_edit_i = -1
    for i, (ts, _e, target) in enumerate(events):
        if target is not None:
            last_edit_i = i
            if target not in edited:
                edited.append(target)
            ev.last_edit, ev.last_edit_ts = target, ts
    ev.edited_files = edited
    for i, (ts, e, _) in enumerate(events):
        if e.name not in SHELL or not e.text:
            continue
        if e.is_error is None and not e.result:
            continue   # still running (or never returned): nothing to report yet
        same = i == last_edit_i   # `sed -i … && pytest` / `python - <<EOF (writes) … && ruff check`: only what follows the edit counts
        turn = owner[id(e)]
        here_text = {seg.text for seg, where in _walk(e, turn) if _here(where, e, root)}
        after_edit = same or i > last_edit_i >= 0
        found = False
        commit_here = any(rules.VERIFY["commit"].search(t) for t in here_text)
        hooked = audit._hook_run([e]) if commit_here else None   # the commit's own hook ran the tests; a message echoed back (`[main abc] 12 passed`) is not that
        for kind in ("test", "build"):
            segs = [sg for sg in rules.verifying_segments(e.text, {kind}, after_edit_only=same) if sg.text in here_text]
            if not segs:
                continue
            seg = segs[-1].text.strip().split("\n")[0]
            if hooked is not None:   # `ruff check x && git commit`: the test summary in the output is the commit hook's
                break
            runner, scope = scope_of(seg, root) if kind == "test" else ("", ())
            ev.checks.append(Check(kind, _show(seg)[:160], _judge(kind, seg, e, root), _summary_line(kind, e.result), ts, after_edit, runner, scope))
            found = True
            break   # one row per command; a test run counts before a build
        if not found and hooked is not None:
            ev.checks.append(Check("test", _show("git commit"), _judge("test", "pytest", hooked), _summary_line("test", hooked.result), ts, after_edit, "git commit"))
    decided = {"backed": "verified", "unbacked": "unverified", "contradicted": "contradicted", "unverifiable": "could not check"}
    for f in findings:
        if f.verdict in decided:
            ev.claims[decided[f.verdict]] = ev.claims.get(decided[f.verdict], 0) + 1
            if f.verdict in ("unbacked", "contradicted"):
                ev.flagged.append((decided[f.verdict], f.claim, f.reason, f.category))
    return ev


# ------------------------------------------------------------------ render
def _local(ts: str) -> str:
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%m-%d %H:%M")
    except Exception:
        return ts[:16]


def _code(s: str) -> str:
    """Inert inline code: GitHub renders no markup, mention or image inside it. A comment marker would still end the block, so it goes too."""
    s = s.replace("<!--", "<! --").replace("-->", "-- >").replace("|", "\\|").replace("`", "'")
    s = re.sub(r"\s+", " ", s).strip()
    return f"`{s}`" if s else ""


def _plain(s: str) -> str:
    """Text outside code: nothing in it can become markup or a mention."""
    s = html.escape(re.sub(r"\s+", " ", s), quote=False).replace("@", "&#64;")
    return re.sub(r"([\\`*_\[\]!~|])", r"\\\1", s)


# Claims about anything but the code on this branch: what the sentence said is the user's business, that one was flagged is the reviewer's.
OFF_TOPIC = {"sent": "sending something", "deployed": "a deployment", "downloaded": "a download", "saved": "saving a file", "checked": "looking something up",
             "scheduled": "scheduling something", "verified": "checking something"}


def _flagged_line(item: tuple, redact) -> str:
    label, claim, why = item[:3]
    about = OFF_TOPIC.get(item[3] if len(item) > 3 else "")
    if about:
        return f"- *{label}*: a sentence about {about} (not shown: it is not about this code)"
    return f"- *{label}*: {_code(redact(claim)[:200])} ({_code(redact(why)[:200])})"


HEAD = {
    "pass": "✅ Tests ran after the last code edit and passed",
    "fail": "❌ The last test run after the last code edit failed",
    "fail-open": "❌ A test run after the last code edit failed, and no later run covered the same tests",
    "none": "⚠️ No test or build ran after the last code edit",
    "no-test": "⚠️ No test ran after the last code edit, only a build or lint check",
    "narrowed": "⚠️ Only a narrowed test run ran after the last code edit, not the whole suite",
    "unclear": "⚠️ A test ran after the last code edit, but its output shows no pass/fail line",
    "no-tests": "⚠️ The test run after the last code edit collected no tests",
    "no-edit": "ℹ️ No code edit by an agent in this window",
    "stale": "⚠️ Code changed after the last test, so its result does not cover what is here now",
    "elsewhere": "⚠️ The last code edit is not in this working tree, so this evidence may belong to another branch",
}


def render(ev: Evidence, version: str, max_rows: int = 8) -> str:
    from .redact import redact as _redact
    names = {"claude-code": "Claude Code", "codex": "Codex", "cursor": "Cursor", "gemini": "Gemini CLI"}
    after = ev.after
    status, decisive = ev.verdict
    head = HEAD[ev.status]
    if status == "fail" and decisive is not [c for c in after if c.kind == "test"][-1]:
        head = HEAD["fail-open"]
    elif status == "unclear" and decisive.result == "no tests":
        head = HEAD["no-tests"]
    if ev.status in ("pass", "fail", "narrowed") and decisive.line:
        head += f": {_code(_redact(decisive.line))}"
    lines = [START, "### Verification evidence", "", f"**{head}**", ""]
    if ev.last_edit:
        more = len(ev.edited_files) - 1
        lines.append(f"Last code edit: {_code(_redact(ev.last_edit))} at {_local(ev.last_edit_ts)}"
                     + (f" ({more} other file{'s' if more != 1 else ''} edited before it)" if more > 0 else "") + ".")
    if ev.changed:
        shown = ", ".join(_code(_redact(p)) for p in ev.changed[:5])
        lines += ["", f"Changed after the last test: {shown}" + (f" and {len(ev.changed) - 5} more" if len(ev.changed) > 5 else "") + ". Run the tests again to cover them."]
    if ev.gone:
        lines += ["", "Edited in these sessions but not in this working tree: " + ", ".join(_code(_redact(p)) for p in ev.gone[:5]) + (f" and {len(ev.gone) - 5} more" if len(ev.gone) > 5 else "") + "."]
    rows = after if after else []
    if rows:
        seen, uniq = set(), []
        for c in reversed(rows):            # newest run of each command
            if c.command in seen:
                continue
            seen.add(c.command); uniq.append(c)
        uniq = list(reversed(uniq))[-max_rows:]
        lines += ["", "| Check after the last edit | Result | Output |", "|---|---|---|"]
        icon = {"passed": "✅ passed", "narrowed": "⚠️ narrowed run", "failed": "❌ failed", "no tests": "⚠️ no tests collected", "no result line": "⚠️ no pass/fail line"}
        for c in uniq:
            lines.append(f"| {_code(_redact(c.command))} | {icon.get(c.result, c.result)} | {_code(_redact(c.line))} |")
    before = len([c for c in ev.checks if not c.after_edit])
    if before and not ev.last_edit:
        lines += ["", f"{before} check run{'s' if before != 1 else ''} in this window, none of them after an agent's code edit."]
    elif before:
        lines.append("")
        lines.append(f"{before} earlier check run{'s' if before != 1 else ''} before the last edit {'are' if before != 1 else 'is'} not counted.")
    if ev.claims:
        order = ["verified", "unverified", "contradicted", "could not check"]
        lines += ["", "Agent claims in this work: " + ", ".join(f"{ev.claims.get(k, 0)} {k}" for k in order) + "."]
    if ev.flagged:
        lines += ["", "<details><summary>Claims with nothing behind them</summary>", ""]
        for item in ev.flagged[:6]:
            lines.append(_flagged_line(item, _redact))
        lines += ["", "</details>"]
    who = ", ".join(names.get(a, a) for a in ev.agents)
    src = (f"Read from {ev.sessions} local {who} session{'s' if ev.sessions != 1 else ''} that worked in this repository"
           if ev.sessions else "No local agent session worked in this repository")
    lines += ["", f"<sub>{src}, {_plain(_redact(ev.window))}, by [honestly](https://github.com/kennywu411-dev/honestly) {version}. "
              "Home paths, e-mails and tokens are redacted.</sub>", END]
    return "\n".join(lines) + "\n"


def splice(body: str, block: str) -> str:
    """Replace an earlier honestly block in a PR body, or append one."""
    body = body or ""
    pat = re.compile(re.escape(START) + r".*" + re.escape(END) + r"\n?", re.S)   # to the last end marker: an older note could hold one in a quoted sentence
    if pat.search(body):
        return pat.sub(lambda _: block, body, count=1)
    return (body.rstrip("\n") + "\n\n" if body.strip() else "") + block


# --------------------------------------------------------------------- gh
PR_REF = re.compile(r"\d+|https://[^\s/]+/[^\s/]+/[^\s/]+/pull/\d+/?")


def update_pr(root: str, block: str, pr: str | None = None) -> str:
    if pr and not PR_REF.fullmatch(pr):
        raise SystemExit(f"honestly pr-note: --pr takes a pull request number or URL, not {pr!r}")
    try:
        gh = program("gh")
        r = subprocess.run([gh, "pr", "view", *( [pr] if pr else [] ), "--json", "number,body,url"], cwd=root, capture_output=True, text=True)
    except FileNotFoundError:
        raise SystemExit("honestly pr-note: --gh needs the GitHub CLI (https://cli.github.com), which was not found on PATH.\n"
                         "Without it: honestly pr-note > pr-note.md, then paste the file into the pull request.") from None
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip().splitlines()
        raise SystemExit("honestly pr-note: no pull request found for this branch"
                         + (f" ({msg[-1]})" if msg else "") + ".\nCreate one with the note in it:\n"
                         "  honestly pr-note > pr-note.md && gh pr create --fill --body-file pr-note.md")
    info = json.loads(r.stdout)
    new = splice(info.get("body") or "", block)
    if new == (info.get("body") or ""):
        return f"honestly pr-note: {info.get('url')} already has this note, nothing changed"
    target = str(info.get("url") or info["number"])   # the URL: a bare number would mean this repository's pull request of that number, whichever one was read
    w = subprocess.run([gh, "pr", "edit", target, "--body-file", "-"], cwd=root, input=new, capture_output=True, text=True)
    if w.returncode != 0:
        raise SystemExit("honestly pr-note: gh pr edit failed: " + (w.stderr or w.stdout).strip())
    return f"honestly pr-note: updated {info.get('url')}"


def run(cwd: str, base: str | None = None, since: str | None = None, agents=None, claude_root=None, codex_root=None):
    from . import __version__
    root = repo_root(cwd)
    b = base_ref(root, base)
    cutoff, window = window_start(root, b, since)
    turns = collect_turns(root, cutoff, agents or ("claude-code", "codex", "cursor", "gemini"), claude_root, codex_root)
    ev = gather(root, cutoff, window, turns)
    status, decisive = ev.verdict
    if status in ("pass", "narrowed"):
        ev.changed = changed_after(root, decisive.ts)
    ev.gone = [p for p in ev.edited_files if p != "a shell edit" and not os.path.exists(os.path.join(root, p))]
    return ev, render(ev, __version__)
