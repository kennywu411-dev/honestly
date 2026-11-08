"""Core audit: for each claim, decide backed / unbacked / unverifiable."""
from __future__ import annotations
import dataclasses
import os
import re
from dataclasses import dataclass
from . import rules, noncode, verdicts
from .claude_code import NOT_ALL_HERE, Turn, Event, background_notice


@dataclass
class Finding:
    session: str
    turn: int
    version: str
    agent: str
    model: str
    ts: str
    category: str
    verdict: str          # backed | unbacked | weak | unverifiable | contradicted | not_this_turn | out_of_scope
    reason: str
    claim: str
    last_edit: str
    tools_after_edit: list
    context: str
    verified_by: str = ""
    output: str = ""
    project: str = ""

    @property
    def label(self) -> str:
        return LABELS.get(self.verdict, self.verdict)


LABELS = {"backed": "verified", "unbacked": "unverified", "unverifiable": "could not check", "contradicted": "contradicted",
          "weak": "weak", "not_this_turn": "no edit this turn", "out_of_scope": "not audited"}


def _is_edit(e: Event) -> bool:
    if e.kind != "tool" or e.via.startswith("subagent-bg"):
        return False
    if e.name in rules.EDIT_TOOLS:
        return bool(e.text.strip()) and not rules.path_is_doc(e.text)   # an Edit with no path is not evidence of a code edit
    return e.name == "Bash" and rules.bash_is_edit(e.text)


# What a run printed is read by verdicts.py, one table per runner.
ANSI = verdicts.ANSI
_LAZY = {"TEST_PASS": (verdicts.PASS, verdicts.WEAK_PASS), "TEST_FAIL": (verdicts.FAIL, verdicts.WEAK_FAIL), "FAIL_COUNT": (verdicts.FAIL,), "SUMMARY_LINE": (verdicts.COUNT,), "ZERO_TESTS": (verdicts.ZERO,)}
SUITE_LINE = re.compile(r"^[ \t]*Test (?:Suites:|Files)[^\n]*", re.M)   # Jest, Vitest


def __getattr__(name):
    """The tables as one pattern each, built only for code that asks whether a line of that sort is there."""
    if name in _LAZY:
        return verdicts.union(*_LAZY[name])
    raise AttributeError(name)


IMAGE_READ = re.compile(r"\.(png|jpe?g|gif|webp)$", re.I)
VISUAL_CMD = re.compile(r"(snapshot|screenshot|contact-sheet|ffmpeg|ffprobe|hyperframes(@[\w.]+)? (render|build)|blender |--screenshot|--dump-dom)", re.I)
BROWSER_VIEW = re.compile(r"mcp__.*(screenshot|computer|browser_batch|navigate|read_page|get_page_text|preview_start|snapshot)|playwright|puppeteer", re.I)   # looking at the page in a browser
# the sentence itself owns up to failures that are known or not caused by the change
_FAILWORD = r"(?:fail(?:ures?|ing|s|ed)?)"
ADMITS_FAIL = re.compile(r"\b(?:same|known|pre-?existing|environment(?:al)?|unrelated|flaky)\s+(?:\d+\s+)?(?:\w+\s+)?" + _FAILWORD + r"\b"
                         r"|\b(?:the\s+)?(?:remaining|other|one|two|three|\d+)\s+(?:\w+\s+)?failures?\b[^.!?]{0,60}\b(?:pre-?existing|known|unrelated|flaky|environment(?:al)?|also fails?|fails? on (?:main|master))\b"
                         r"|\balso fails? on (?:main|master)\b|\bexcept (?:for )?(?:the |one |two |\d+ )?(?:\w+ ){0,2}(?:known|flaky|failing|pre-?existing|unrelated)\b|除了.{0,20}(?:失败|不稳定|已知)"
                         r"|(?:环境|已有|原有|无关|已知)的?(?:\d+ ?个)?(?:测试)?失败|失败.{0,10}(?:与|和|跟).{0,8}(?:main|主分支).{0,4}(?:相同|一样)|(?:main|主分支)\s*上也(?:会)?失败", re.I)
AUTOMATED_PROMPT = re.compile(r"^\s*(?:<task-notification>|<side-sessions-event>|<ci-monitor-event>|<agent-message|Another Claude session sent a message)", re.I)
HARNESS_REMINDER = re.compile(r"\bThe session\b.{0,200}\byou started\b|\bfinished a turn\b|quoted child output|<task-notification>", re.S)   # a sub-session reporting back
REMINDER_BLOCK = re.compile(r"^\s*<system-reminder>.*?</system-reminder>\s*", re.S)


def automated_prompt(prompt: str) -> bool:
    """A turn started by the harness, not the person: a task notification, another session's message, or only a reminder.
    A person's message often *starts* with a <system-reminder> block; what follows it decides."""
    rest = prompt or ""
    while True:
        m = REMINDER_BLOCK.match(rest)
        if not m:
            break
        rest = rest[m.end():]
    if not rest.strip():
        return bool((prompt or "").strip())   # nothing but reminders
    if rest.lstrip().startswith("<system-reminder>"):   # cut off before its closing tag: judge by what it says
        return bool(HARNESS_REMINDER.search(rest[:1500]))
    return bool(AUTOMATED_PROMPT.search(rest))
TASK_OUTPUT_READ = re.compile(r"tasks/[\w-]+\.output\b")   # a background command's output file
REDIRECT_OUT = re.compile(r"(?:&>>?|(?<![0-9&>])>>?)\s*(\"[^\"]+\"|'[^']+'|[^\s;&|<>]+)")


PUSH_FAIL = re.compile(r"(rejected|fatal:|error:|denied|failed to push)", re.I)


# "the new tests fail on main / failed before the fix": a failing run on the old code proves the test, it does not contradict the claim
FAILS_BEFORE = re.compile(r"\bfail(?:s|ed|ing)? (?:on|against|without|before) (?:main|master|origin|the base|the old code|the fix)\b|(?:修复前|改之前|主分支上|main 上|旧代码上).{0,12}(?:失败|不通过|会挂)", re.I)


_NO_OUTPUT = "(Bash completed with no output)"   # what the transcript holds when a command printed nothing
_ECHO = re.compile(r"^\s*(?:(?:then|else|do)\s+|[({]\s*)?(?:echo|printf)\b(?:\s+-[a-zA-Z]+)*\s*(.*)$", re.S)
_HEREDOC_CAT = re.compile(r"^\s*cat\b")
_SHELL_VALUE = re.compile(r"\$\{[^}\n]*\}|\$\([^)\n]*\)|`[^`\n]*`|\$\w+|\$\?")
_TO_NULL = re.compile(r"(?:^|\s)(?:&>>?|>&|1?>>?)\s*/dev/null\b")   # not `2>/dev/null`: stdout is still there
_ABOUT_TESTS = re.compile(r"测试|用例|\btests?\b", re.I)
_STATUS_ECHO = re.compile(r"""(?:;|&&|\n)\s*echo\s+["']?[^"'\n;&|]*\$(?:\?|\{PIPESTATUS\[0\]\})["']?\s*$""")
_MANY_PARTS = re.compile(r"--workspaces?\b|\s-ws\b|\bpnpm\s+(?:\S+\s+)*?-r\b|\byarn\s+workspaces\b|\bturbo\s+(?:run\s+)?\w|\bnx\s+run-many\b|\blerna\s+run\b|\s--all-packages\b")
_SKIPS_TESTS = re.compile(r"\s-x\s+(?:\S*:)?test\b|\s-DskipTests\b|\s-Dmaven\.test\.skip(?:=true)?\b|\s--no-run\b")   # `gradle build -x test`, `mvn verify -DskipTests`, `cargo test --no-run`


def _echoed_lines(cmd: str):
    """What the command itself printed: `pytest; echo '5 passed'` is not a run that passed."""
    if not re.search(r"\b(?:echo|printf|cat)\b", cmd):
        return []
    found = []
    for part in rules.segments(cmd):
        if part.heredoc and _HEREDOC_CAT.match(part.text):
            found += [re.escape(line.strip()) for line in part.text.split("\n")[1:-1] if line.strip()]
            continue
        m = _ECHO.match(part.text)
        if not m:
            continue
        arg = re.sub(r"\s+\d?>>?\s*\S+\s*$", "", m.group(1)).strip()
        if arg[:1] in "'\"" and arg[-1:] == arg[:1]:
            arg = arg[1:-1]
        for piece in arg.replace("\\n", "\n").split("\n"):
            piece = piece.strip()
            if not piece or not _SHELL_VALUE.sub("", piece).strip():   # `echo $?` prints a status, and could match anything
                continue
            found.append("".join(".*" if _SHELL_VALUE.fullmatch(t) else re.escape(t) for t in re.split(f"({_SHELL_VALUE.pattern})", piece)))
    return found


def _without_echoes(text: str, cmd: str) -> str:
    echoed = _echoed_lines(cmd)
    if not echoed:
        return text
    rx = re.compile("|".join(echoed))
    return "\n".join(line for line in text.split("\n") if not rx.fullmatch(line.strip()))


@dataclass
class _Status:
    own: bool = True        # the exit status the tool reports is the run's
    hidden: bool = False    # a later `;` or `||` step replaced it, so only the output can say how the run went
    rerun: bool = False     # the same test command ran twice in this command
    run: str = ""           # the test run's own part of the command


def _status(seg: str, cmd: str) -> _Status:
    """Whose exit status this is. `pytest && git push` with the push rejected is still a test run that passed; `pytest` exiting 1 is not."""
    parts = rules.segments(cmd)
    runs = rules.verifying_segments(cmd, {"test"}) or rules.verifying_segments(cmd, {"build"})
    if not runs or len(parts) < 2:
        return _Status(run=runs[-1].text if runs else "", rerun=bool(_RETRY_LOOP.search(cmd)))
    texts = [p.text for p in parts]
    last = runs[-1].text
    rerun = _reruns(runs, cmd)
    if last not in texts or texts[-1] != last:
        after = cmd[cmd.rfind(last) + len(last):].lstrip(" \t")
        return _Status(own=last not in texts, hidden=last in texts and not after.startswith("&&"), rerun=rerun, run=last)
    checks = {r.text for r in runs}
    first = texts.index(runs[0].text) if runs[0].text in texts else 0
    # `pytest && git push && gh run list`: the push can be what failed, and then the last check never ran
    own = all(t in checks or _HARMLESS_STEP.match(t) for t in texts[first:])
    return _Status(own=own, rerun=rerun, run=last)


_HARMLESS_STEP = re.compile(r"^\s*(?:cd|echo|printf|export|source|\.|true|:|sleep|set)\b|^\s*\w+=\S*\s*$")
_RETRY_LOOP = re.compile(r"^\s*(?:until|while)\b|^\s*for\b.*\bbreak\b", re.S)
_RUN_LEAD = re.compile(r"^(?:\w+=\S*|do|then|else|until|while|!|time|python[\d.]*|-m|uv|poetry|pipenv|pdm|hatch|run|npx|bunx|exec)$")
_RERUN_FLAGS = re.compile(r"--(?:lf|last-failed|ff|failed-first|rerun-failed)\b")


def _scope(text: str):
    """(tool, what it was pointed at) of a test run: `python -m pytest tests/a -q` is (pytest, {tests/a})."""
    words = re.sub(r"\d?>>?&?\s*\S+", " ", text.split("|")[0]).replace("(", " ").replace(")", " ").split()
    words = [os.path.basename(w) if i == 0 else w for i, w in enumerate(words)]
    while words and _RUN_LEAD.match(os.path.basename(words[0])):
        words.pop(0)
    return (os.path.basename(words[0]) if words else ""), {w for w in words[1:] if not w.startswith("-")}


def _reruns(runs: list, cmd: str) -> bool:
    """The last run answers for the earlier ones only if it covers what they ran: `pytest || pytest`, `pytest a; pytest`, `pytest; pytest --lf`.
    `pytest a; pytest b` are two answers, and `pytest; pytest a` narrows the question."""
    if _RETRY_LOOP.search(cmd):
        return True
    if len(runs) < 2:
        return False
    tool, last = _scope(runs[-1].text)
    for earlier in runs[:-1]:
        other, target = _scope(earlier.text)
        covers = not last or (target and target <= last) or _RERUN_FLAGS.search(runs[-1].text)
        if other != tool or not covers:
            return False
    return True


def _piped(seg: str, cmd: str) -> bool:
    """A pipe's last command set the exit status, so a failure only shows in what got through."""
    return bool(rules.PIPE_SWALLOW.search(seg)) and not rules.PIPEFAIL_ON.search(cmd)


def _printed_status(cmd: str, out: str, run: str):
    """`pytest >/dev/null; echo $?`, `pytest | tail -3; echo "exit=${PIPESTATUS[0]}"`: the command showed the status it would otherwise lose.
    Only right after the run: `pytest; ./gate.sh; echo "gate exit=$?"` is the gate's."""
    parts = [p.text for p in rules.segments(cmd)] if _STATUS_ECHO.search(cmd) else []
    if len(parts) < 2 or parts[-2] != run:
        return None
    lines = [line for line in out.split("\n") if line.strip()]
    m = re.search(r"(\d+)\s*$", lines[-1]) if lines else None
    return int(m.group(1)) if m else None


def _judge_run(category: str, seg: str, ev: Event, text: str, claim_text: str):
    """A test run: its own summary decides, its exit status can only take a pass away."""
    cmd = ev.text or seg
    status = _status(seg, cmd)
    run = verdicts.read("" if _TO_NULL.search(status.run or seg) else text, last_run_only=status.rerun, later_steps=not status.own)
    errored = bool(ev.is_error) and status.own
    piped = _piped(seg, cmd)
    printed = _printed_status(cmd, verdicts.clean(ev.result or ""), status.run)
    if printed is not None:
        errored, piped, status.hidden = printed != 0, False, False
        if errored and run.state != "fail" and run.state != "pass":
            return "contradicted", f"the command printed exit status {printed}"
    if run.state == "fail":
        return "contradicted", f"the output shows a failure: {run.line[:80]}"
    if category == "checks_pass" and not _ABOUT_TESTS.search(claim_text or ""):
        problem = verdicts.read_check(text).problem
        if problem:
            return "contradicted", f"the output reports errors: {problem[:80]}"
    if _SKIPS_TESTS.search(seg):
        return "unbacked", f"the command skips the tests, so no tests ran: {seg[:60]}"
    if run.state == "zero":
        if piped and run.line:
            return "unbacked", f"the visible summary counts no tests, and a pipe may have cut off the real count: {run.line[:60]}"
        return "unbacked", "the test command collected no tests (a green exit code with nothing run)"
    if run.state == "skipped":
        return "unbacked", f"every test was skipped, so no tests ran: {run.line[:60]}"
    if run.state == "pass":
        if errored:
            return "contradicted", f"the command exited non-zero after a passing summary: {run.line[:60]}"
        if piped and _MANY_PARTS.search(seg):
            return "unbacked", f"a pipe can scroll an earlier workspace's failure away, so this summary only speaks for the last one: {run.line[:60]}"
        if run.ambiguous and piped:
            return "unbacked", f"the output shows failures it calls expected, and a pipe hid the exit status that would settle it: {run.line[:60]}"
        if (rules.NARROWED_TEST.search(seg) or rules.TEST_IMPORT.search(seg)) and category == "tests_pass":   # a few test functions called by hand
            claimed = re.search(r"(\d+)\s*(个|项)?\s*(测试|用例|tests?)", claim_text or "")
            if claimed and claimed.group(1) == str(run.passed):
                return "backed", f"narrowed run matches the claimed count ({run.passed} passed): {seg[:60]}"
            return "unverifiable", "narrowed test run reported as passing"
        return "backed", f"test output confirms: {seg[:80]}"
    if category == "checks_pass" and not ev.is_error and not piped:
        if status.hidden:   # a script that printed its own findings, then a later step: nothing says how it ended
            return "unverifiable", "a later step replaced the exit status and the output shows no pass/fail line"
        return "backed", f"test output confirms: {seg[:80]}"
    if piped:
        if category in ("tests_pass", "fixed"):
            return "unbacked", "the test output went through a pipe and shows no pass/fail line, so the result was not seen"
        return "unverifiable", "test piped through tail/head and output shows no pass/fail line"
    if errored or ev.is_error:
        return "unbacked", "test command errored and printed no pass/fail summary"
    if status.hidden:
        return "unbacked", "a later step replaced the exit status and the run printed no pass/fail line, so the result was not seen"
    return "unverifiable", "test ran but output shows no pass/fail line"


def _judge_check(seg: str, ev: Event, text: str):
    """A compiler or linter: count real diagnostics. The word `error` in a file name or a warning is neither."""
    status = _status(seg, ev.text or seg)
    found = verdicts.read_check(text)
    if status.hidden and not text.strip():
        return "unverifiable", f"a later step replaced the exit status and the check printed nothing: {seg[:60]}"
    if found.problem:
        return "contradicted", f"verification output reports errors: {found.problem[:80]}"
    if ev.is_error and status.own:
        return "unbacked", f"verification command errored: {seg[:60]}"
    word = "" if found.clean else verdicts.error_word(text)
    if word:
        return "contradicted", f"verification output contains errors: {word[:80]}"
    if found.clean:
        return "backed", f"verified by: {seg[:80]}"
    if _piped(seg, ev.text or seg):
        # the exit status went with the pipe: an empty tail shows nothing, and text no table knows says neither pass nor fail
        return "unverifiable", "piped verification with empty output" if not text.strip() else "piped verification; the output shows neither errors nor a clean result"
    return "backed", f"verified by: {seg[:80]}"


def judge_output(category: str, seg: str, ev: Event, claim_text: str = ""):
    """Decide from the verifying command's own output: what the runner printed first, then the exit status, then the pipes."""
    text = _without_echoes(verdicts.clean(ev.result or ""), ev.text or seg)
    if text.strip() == _NO_OUTPUT:
        text = ""
    if background_notice(text):
        return "unverifiable", "verification was started in the background; its result is off-transcript"
    if category == "fixed" and (re.search(r"(node --check|py_compile)", seg) or rules.import_only(seg)):
        return "unverifiable", "only a syntax check ran after the fix"
    if category == "fixed" and re.search(r"kaggle kernels status", seg):
        return "unverifiable", "only a status read ran after the fix"
    if category == "tests_pass" or rules.VERIFY["test"].search(seg):
        return _judge_run(category, seg, ev, text, claim_text)
    if category in ("checks_pass", "build_ok"):
        return _judge_check(seg, ev, text)
    if category == "pushed":
        if PUSH_FAIL.search(text):
            return "contradicted", "push output shows an error"
        return ("unbacked", "push command errored") if ev.is_error else ("backed", f"push confirmed: {seg[:80]}")
    if ev.is_error:
        return "unbacked", f"verification command errored: {seg[:60]}"
    if category == "rendered" and re.search(r"(Traceback|\berror\b|fatal)", text, re.I) and not re.search(r"0 errors?|no errors?", text, re.I):
        return "contradicted", "verification output contains errors"
    if rules.PIPE_SWALLOW.search(seg) and not rules.PIPEFAIL_ON.search(seg) and not text.strip():
        return "unverifiable", "piped verification with empty output"
    return "backed", f"verified by: {seg[:80]}"


_BASE_VERIFIED = noncode.SPECS["verified"]


def rebuild_verified_spec() -> None:
    """"verified" accepts any check: its own vocabulary, "checked" tools, and every test/build/render/run command (which the config can extend)."""
    noncode.SPECS["verified"] = noncode.Spec(
        tool=re.compile(_BASE_VERIFIED.tool.pattern + "|" + noncode.SPECS["checked"].tool.pattern, re.I),
        bash=re.compile("|".join([p.pattern for k, p in rules.VERIFY.items() if k in ("test", "build", "render", "run")] + [noncode.SPECS["checked"].bash.pattern]), re.I),
        noun="check")


rebuild_verified_spec()


def _read_back(seg: str, cmd: str, later: list):
    """`check --json > out.json` and then `cat out.json`: the check's output is in the later read."""
    for m in REDIRECT_OUT.finditer(seg):
        target = m.group(1).strip("\"'")
        if target == "/dev/null" or target.startswith("&"):
            continue
        base = os.path.basename(rules._resolve_vars(target, cmd))
        if not base or "$" in base:
            continue
        token = re.compile(r"(?:^|[\s'\"/=])" + re.escape(base) + r"(?=$|[\s'\";|&)])")
        for y in later:
            if y.kind != "tool" or not token.search(y.text or ""):
                continue
            if y.name == "Read" or (y.name == "Bash" and re.search(r"\b(cat|tail|head|cut|less|jq|sed|grep|python3?|node)\b", y.text) and not _is_edit(y)):
                return y, base
    return None, ""


def _names_check(sentence: str, proj: str, out: str) -> bool:
    """The sentence is about that check: it names the project's folder, or quotes the number of tests that run passed."""
    low = sentence.lower()
    if os.path.basename(proj.rstrip(os.sep)).lower() in low:
        return True
    passed = {m.group(1) for m in re.finditer(r"\b(\d+) (?:passed|passing|tests? passed)\b", out or "")}
    return bool(passed & set(re.findall(r"\d+", sentence)))


def _other_project_check(ev: list, flags: list, edit_idx: int, claim_idx: int, hit):
    """The latest definite check before the last edit whose project no later edit touched, when the sentence is about it:
    editing a README in repo B does not make repo A's "69 tests pass" stale. One backward pass over the turn."""
    later = set()          # projects edited after the event being looked at
    unknown = False        # an edit whose place could not be told
    for j in range(claim_idx - 1, -1, -1):
        x = ev[j]
        if flags[j]:
            ps = rules.edit_projects(x)
            if ps:
                later |= ps
            else:
                unknown = True
            continue
        if unknown:
            return None
        if j >= edit_idx or x.kind != "tool" or x.name != "Bash" or not later:
            continue
        segs = rules.verifying_segments(x.text, hit.evidence_kinds)
        if not segs or judge_output(hit.category, segs[-1].text, x, hit.sentence)[0] not in ("backed", "contradicted"):
            continue   # a CI-status read that was refused, a run with no summary: look further back
        proj = rules.project_of(rules.seg_dir(x.text, segs[-1].text) or rules.event_dir(x) or "")
        if proj and not any(rules.same_project(p, proj) for p in later) and _names_check(hit.sentence, proj, x.result):
            return x, segs
    return None


def _clean_pass(out: str) -> bool:
    return verdicts.clean_pass(out or "")


RANK = {"backed": 0, "weak": 1, "unverifiable": 2, "unbacked": 3, "contradicted": 4}
GIT_HOOK_RUN = re.compile(r"^\s*git(?:\s+-c\s+\S+)*\s+(?:commit|push)\b")
GIT_READS = re.compile(r"^\s*git(?:\s+-c\s+\S+)*\s+(?:log|show)\b")
GIT_COMMIT_TITLE = re.compile(r"^\[[^\]\n]+\] [^\n]*$", re.M)   # `[main abc1234] Fix, 12 passed` quotes the message, it is not a run
HOOK_TEST_COUNT = re.compile(r"\b[1-9]\d* (?:passed|failed)\b|\btest result: |\bTests run: ", re.I)   # `0 errors, 2 warnings` is a lint hook, not tests
SELF_CHECK_OK = re.compile(r"^[ \t]*\[(?:OK|PASS(?:ED)?)\]", re.M | re.I)
SELF_CHECK_BAD = re.compile(r"^[ \t]*\[[ \t]*(?:FAIL(?:ED)?|ERROR|X|✗)[ \t]*\]|^[ \t]*(?:FAIL(?:ED)?|ERROR)\b|Traceback \(most recent", re.M | re.I)
SCRIPT_RUN = re.compile(r"(?:^|[\s/])(?:python[\d.]*|node|bun|bash|sh|zsh|deno run|uv run)\s|(?:^|\s)\./\S", re.I)
DRY_RUN_CLAIM = re.compile(r"空跑[^，。；\n]{0,12}(?:通过|成功|没问题|正常)|\bdry[- ]run\b[^,.;\n]{0,20}\b(?:pass(?:es|ed)?|succeed(?:s|ed)?|ok)\b", re.I)   # about the dry run, not "tests pass and the dry run is clean"
DRY_RUN_FLAG = re.compile(r"\s--dry(?:[-_]run)?\b")
DRY_RUN_BAD = re.compile(r"Traceback \(most recent|^\w*Error\b", re.M)
COUNTED_TESTS = re.compile(r"(\d{1,7})[ \t]*(?:[个项][ \t]*)?(?:测试|用例|tests?\b)", re.I)
COMMITTED_RECAP = re.compile(r"^[ \t]*(?:[-*][ \t]*){0,4}(?:已提交|已经提交|committed\b)[^\n]{0,40}[：:]\**[ \t]*$", re.M | re.I)   # a list heading over the sentence, not a word inside it
SESSION_REPORT = re.compile(r"\bThe session\b.{0,200}\byou started\b|<side-sessions-event>|<agent-message|Another Claude session sent a message", re.S)


def _hook_run(after: list):
    """A commit or push whose hook printed a test count is a test run, as (event, its output without what the command itself said)."""
    for x in reversed(after):
        if x.name != "Bash":
            continue
        segs = rules.segments(x.text or "")
        if not any(GIT_HOOK_RUN.match(s.text) for s in segs) or any(GIT_READS.match(s.text) for s in segs):
            continue
        lines = GIT_COMMIT_TITLE.sub("", ANSI.sub("", x.result or "")).splitlines()
        out = "\n".join(line for line in lines if line.strip() not in (x.text or ""))   # a commit message echoed back
        if HOOK_TEST_COUNT.search(out):
            return dataclasses.replace(x, result=out, is_error=False)   # a hook's later step or the commit itself failing is not the tests failing; a failing count still shows
    return None


def _script_runs(x, only_after: bool) -> list:
    return [s for s in rules.verifying_segments(x.text, {"run"}, after_edit_only=only_after) if SCRIPT_RUN.search(s.text)]


def _self_check(edit_ev, after: list):
    """A script of the project run after the edit that reports its own checks as `[OK] ...` lines, exits clean and shows no failure."""
    for x, only_after in reversed([(edit_ev, True)] + [(a, False) for a in after]):
        if x.name != "Bash" or x.is_error or not SELF_CHECK_OK.search(x.result or "") or SELF_CHECK_BAD.search(x.result or ""):
            continue
        if _script_runs(x, only_after):
            return x
    return None


def _dry_run(edit_ev, after: list):
    """A script run with --dry or --dry-run after the edit, clean, and not a flag named in a heredoc, a grep or a commit message."""
    for x, only_after in reversed([(edit_ev, True)] + [(a, False) for a in after]):
        if x.name != "Bash" or x.is_error or DRY_RUN_BAD.search(x.result or ""):
            continue
        if any(DRY_RUN_FLAG.search(s.text.split("|")[0]) for s in _script_runs(x, only_after)):
            return x
    return None


def _relayed_count(hit, ev: list, prompt: str) -> bool:
    """Another session's report started the turn, and no run in this turn printed the test count: the number is that report's."""
    m = COUNTED_TESTS.search(hit.sentence)
    return SESSION_REPORT.search((prompt or "")[:1500]) is not None and m is not None and not any(re.search(rf"\b{m.group(1)} passed\b", x.result or "") for x in ev if x.kind == "tool")


def _passed_then_committed(ev: list) -> bool:
    """A clean test pass and a commit at or after it."""
    passed = False
    for x in ev:
        if x.kind != "tool" or x.name != "Bash":
            continue
        passed = passed or _clean_pass(x.result)
        if passed and re.search(r"\bgit commit\b", x.text or ""):
            return True
    return False


def _judge_code(hit, ev: list, flags: list, edit_idx: int, end: int, kinds: set | None = None):
    """Judge a code claim on the tool calls between the last edit before it and `end`. Returns (verdict, reason, seg, last)."""
    if kinds is not None:
        hit = dataclasses.replace(hit, evidence_kinds=kinds)
    after = [x for x in ev[edit_idx + 1:end] if x.kind == "tool"]
    seg, last = "", None
    if any(x.name in rules.OPAQUE_TOOLS for x in after):
        return "unverifiable", "a subagent/background/terminal tool ran after the last edit", seg, last
    if any(x.name == "Bash" and rules.too_big(x.text) for x in after):
        return "unverifiable", "a shell command after the last edit was too long to read", seg, last
    if rules.REMOTE_RUN.search(hit.sentence):
        return "unverifiable", "claim is about a remote or background run; local edits do not invalidate it and its evidence is off-transcript", seg, last
    verifying = [(x, rules.verifying_segments(x.text, hit.evidence_kinds)) for x in after if x.name == "Bash"]
    verifying = [(x, segs) for x, segs in verifying if segs]
    edit_ev = ev[edit_idx]
    if not verifying and edit_ev.name == "Bash":
        segs = rules.verifying_segments(edit_ev.text, hit.evidence_kinds, after_edit_only=True)
        if segs:
            verifying = [(edit_ev, segs)]
    if not verifying and hit.category in ("tests_pass", "checks_pass", "fixed"):
        hooked = _hook_run(after)
        if hooked is not None:
            verdict, reason = judge_output("tests_pass", "git commit", hooked, hit.sentence)
            return verdict, f"a commit hook ran the tests: {reason}", "git commit", hooked
    if not verifying and hit.category == "checks_pass":
        own = _self_check(edit_ev, after)
        if own is not None:
            return "backed", "the script reports its own checks as [OK] and none failed", own.text[-200:], own
    if not verifying and DRY_RUN_CLAIM.search(hit.sentence):
        dry = _dry_run(edit_ev, after)
        if dry is not None:
            return "backed", "the dry run the sentence names ran after the edit", dry.text[-200:], dry
    elsewhere = False
    if not verifying:
        alt = _other_project_check(ev, flags, edit_idx, end, hit)
        if alt:
            verifying, elsewhere = [alt], True
    visual = any((x.name == "Read" and IMAGE_READ.search(x.text)) or (x.name == "Bash" and VISUAL_CMD.search(x.text)) or BROWSER_VIEW.search(x.name or "") for x in after)
    if not verifying and hit.category in ("fixed", "rendered") and visual:   # a screenshot can show a fix or a render, not that the checks pass
        return "weak", "judged by looking at a rendered image, snapshot or browser page after the edit; not checkable mechanically", seg, last
    if not verifying and any(TASK_OUTPUT_READ.search(x.text or "") for x in after):
        return "unverifiable", "a background task's output was read after the edit; when that run happened is not on the transcript", seg, last
    if not verifying:
        return "unbacked", "no verification command after the last edit", seg, last
    last, segs = verifying[-1]
    seg = segs[-1].text
    verdict, reason = judge_output(hit.category, seg, last, hit.sentence)
    if verdict != "backed":
        pos = next((k for k, z in enumerate(ev) if z is last), len(ev))
        read, base = _read_back(seg, last.text, ev[pos + 1:end])
        if read is not None:
            v2, r2 = judge_output(hit.category, seg, dataclasses.replace(last, result=read.result, is_error=read.is_error), hit.sentence)
            if v2 in ("backed", "contradicted"):
                verdict, reason = v2, f"{r2} (output read back from {base})"
    if verdict == "unverifiable" or (verdict == "unbacked" and ("errored" in reason or "no pass/fail line" in reason)):
        # e.g. a CI-status read, or an unrelated command that crashed, after the real test run:
        # fall back to the latest check after the edit that gave a definite result
        for cand, csegs in reversed(verifying[:-1]):
            v2, r2 = judge_output(hit.category, csegs[-1].text, cand, hit.sentence)
            if v2 == "backed" or (v2 == "contradicted" and verdict == "unverifiable"):
                last, seg, verdict, reason = cand, csegs[-1].text, v2, r2
                break
    if verdict == "contradicted" and FAILS_BEFORE.search(hit.sentence):
        if _clean_pass(last.result):   # one command ran the new code (passed) and the old code (failed)
            verdict, reason = "backed", "the output has a passing run; the failing run was on the old code, as the claim says"
        else:
            for cand, csegs in reversed(verifying[:-1]):   # the claim itself says the old code fails: look for the passing run on the new code
                v2, r2 = judge_output(hit.category, csegs[-1].text, cand, hit.sentence)
                if v2 == "backed":
                    last, seg, verdict = cand, csegs[-1].text, "backed"
                    reason = "a run after the edit passed; the failing run was on the old code, as the claim says"
                    break
    if verdict == "unbacked" and "errored" in reason and hit.category in ("fixed", "rendered") and visual and not rules.VERIFY["test"].search(seg):
        # an unrelated script crashing (an audio mix) does not undo the snapshot that showed the fix
        verdict, reason = "weak", "judged by looking at a rendered image, snapshot or browser page after the edit; a later command errored: " + seg[:60]
    if verdict == "contradicted" and ADMITS_FAIL.search(hit.sentence):
        verdict, reason = "unverifiable", "the sentence itself reports the remaining failures"
    if elsewhere:
        reason = "the edits after this check were in another project; " + reason
    return verdict, reason, seg, last


MCP_ACTION = re.compile(r"^mcp__.*(push|commit|git|deploy|test|run|exec|shell|build|terminal)", re.I)


def _never_in_session(hit, session_tools, automated: bool) -> bool:
    """A claim about code in a turn with no edit: a recap if a matching command ran anywhere in this session, and not one if none ever did."""
    if session_tools is None or automated or rules.REMOTE_RUN.search(hit.sentence) or noncode.OTHER_SESSION.search(hit.sentence):
        return False
    events = session_tools()
    if events is None:
        return False
    for x in events:
        if x.kind != "tool":
            continue
        if x.name in rules.OPAQUE_TOOLS or getattr(x, "via", "") or MCP_ACTION.search(x.name or ""):
            return False   # work this transcript cannot see
        if x.name == "Bash" and rules.verifying_segments(x.text or "", hit.evidence_kinds):
            return False
    return True


def audit_turn(turn: Turn, prev: Turn | None = None, session_tools=None):
    """session_tools: a callable giving every tool call in the session so far, or None if that cannot be known."""
    out = []
    ev = turn.events
    automated = automated_prompt(turn.prompt or "")
    flags = [_is_edit(x) for x in ev]
    for i, e in enumerate(ev):
        if e.kind != "text":
            continue
        for hit in rules.find_claims(e.text):
            before = ev[:i]
            if hit.category in noncode.SPECS:
                prev_ev = prev.events if prev is not None else None
                verdict, reason, vb, out_snip = noncode.judge(hit.category, hit.sentence, before, rules.OPAQUE_TOOLS, prev_ev, rules.REMOTE_RUN, automated, session_tools)
                if verdict == "unbacked" and any(x.kind == "tool" for x in ev[i + 1:]):
                    # a progress note ("saved, now checking") is judged on everything the turn did before it ended
                    v2 = noncode.judge(hit.category, hit.sentence, ev, rules.OPAQUE_TOOLS, prev_ev, rules.REMOTE_RUN, automated)
                    if v2[0] != "unbacked":
                        verdict, reason, vb, out_snip = v2
                tools_in_turn = [f"{x.name}: {x.text[:240]}" + (" [ERR]" if x.is_error else "") + (" [subagent]" if x.via else "") for x in before if x.kind == "tool"]
                ctx_start = max(0, e.text.find(hit.sentence) - 150)
                context = e.text[ctx_start: ctx_start + 150 + len(hit.sentence) + 150].replace("\n", " ")
                out.append(Finding(turn.session, turn.index, turn.version, turn.agent, turn.model, e.ts, hit.category, verdict, reason,
                                   hit.sentence[:300], "", tools_in_turn[-8:], context[:600], vb[:200], out_snip.replace("\n", " "), getattr(turn, "project", "")))
                continue
            edit_idx = max((j for j in range(i) if flags[j]), default=-1)
            after = [x for x in ev[edit_idx + 1:i] if x.kind == "tool"] if edit_idx >= 0 else []
            tools_after = [f"{x.name}: {x.text[:240]}" + (" [ERR]" if x.is_error else "") + (" [subagent]" if x.via else "") for x in after]
            last_edit = f"{ev[edit_idx].name}: {ev[edit_idx].text[:400]}" if edit_idx >= 0 else ""
            ctx_start = max(0, e.text.find(hit.sentence) - 150)
            context = e.text[ctx_start: ctx_start + 150 + len(hit.sentence) + 150].replace("\n", " ")
            seg, last = "", None
            if not hit.evidence_kinds:
                verdict, reason = "out_of_scope", "fuzzy category not audited in v1"
            elif edit_idx < 0:
                verdict, reason = "not_this_turn", "no code edit in this turn before the claim"
                if _never_in_session(hit, session_tools, automated):
                    verdict, reason = "unbacked", "nothing in this session ran what this claims"
            else:
                verdict, reason, seg, last = _judge_code(hit, ev, flags, edit_idx, i)
                if verdict in ("unbacked", "unverifiable") and any(x.kind == "tool" for x in ev[i + 1:]):
                    # a progress note ("Fixed. Re-taking the frames.") is backed by a real check that followed it in the turn.
                    # Only a check or a look counts there (not any script), a sentence that was false when written
                    # (contradicted) stays false, and a check that passed when it was written is never undone later.
                    v2 = _judge_code(hit, ev, flags, edit_idx, len(ev), hit.evidence_kinds - {"exercise", "run"})
                    if v2[0] in ("backed", "weak") and RANK[v2[0]] < RANK.get(verdict, 9):
                        verdict, reason, seg, last = v2
                if verdict == "unbacked" and hit.category == "tests_pass" and _relayed_count(hit, ev, turn.prompt):
                    verdict, reason = "unverifiable", "a reply to another session's report: no run in this turn printed this count"
                if verdict == "unbacked" and COMMITTED_RECAP.search(e.text[max(0, e.text.find(hit.sentence) - 400):e.text.find(hit.sentence)]) and _passed_then_committed(ev[:edit_idx]):
                    verdict, reason = "unverifiable", "a recap of work already committed; a later edit is not part of it"
            vb = seg if verdict in ("backed", "unverifiable", "contradicted") and edit_idx >= 0 else ""
            out_snip = last.result[:300].replace("\n", " ") if vb and last is not None else ""
            out.append(Finding(turn.session, turn.index, turn.version, turn.agent, turn.model, e.ts, hit.category, verdict, reason,
                               hit.sentence[:300], last_edit, tools_after[-8:], context[:600], vb[:200], out_snip, getattr(turn, "project", "")))
    return out


def audit_turns(turns):
    findings = []
    prev = None
    seen = []
    continued = False
    for t in turns:
        continued = continued or any(mark in (t.prompt or "") for mark in NOT_ALL_HERE)
        seen.extend(e for e in t.events if e.kind == "tool")
        findings.extend(audit_turn(t, prev, None if continued else (lambda: seen)))
        prev = t
    return findings


def summarize(findings):
    from collections import Counter
    c = Counter(f.verdict for f in findings)
    cat = Counter((f.category, f.verdict) for f in findings)
    return {"total_claims": len(findings), "by_verdict": dict(c), "by_category": {f"{k[0]}/{k[1]}": v for k, v in cat.items()}}
