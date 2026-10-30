"""Deterministic rules: what counts as a claim, an edit, and verification.

Precision over recall. A claim is flagged only when the same turn shows a
code edit and no category-matching verification after it. Anything we
cannot see (subagents, background tasks, the user's own terminal, piped
exit codes) is marked unverifiable, never unbacked.
"""
from __future__ import annotations
import os
import re
import shlex
from dataclasses import dataclass

# ----------------------------------------------------------------- claims
CLAIM_PATTERNS = [
    ("tests_pass", re.compile(
        r"((?:all (?:the )?)?tests? (?:are |all )?(?:now )?pass(?:es|ed|ing)?\b(?!\s+(?:a|an|the|its|this|that|my|our|your|each|every|some|any|\w+ (?:to|into|through|as|along|down))\b)"
        r"|\b\d+ (tests? )?passed\b|\d+ 个?(测试|用例)(全部|都|均)?通过|测试(全部|都|已|已经|均)?通过|用例(全部|都)?通过)", re.I), {"test"}),
    ("checks_pass", re.compile(
        r"(checks? (all )?pass(es|ed)?\b|lint(ing)? pass(es|ed)?\b|type ?check(s|ing)? pass(es|ed)?\b|build pass(es|ed)?\b|检查(结果)?[:：]?\s*(全部|都|均)?通过|全部通过|lint (全部)?通过|\b0 (错误|warnings?|errors?))", re.I), {"test", "build"}),   # "10 errors" is not "0 errors"
    ("build_ok", re.compile(
        r"(build (succeeded|passed|passes|is green|ok)|compiles? (cleanly|fine|ok)|编译通过|构建(成功|通过)|打包(成功|完成)|类型检查通过|lint 通过|ruff 也?通过)", re.I), {"build", "test", "run"}),
    ("rendered", re.compile(
        r"(render(ed|ing)? (is )?(complete|finished|done)(?!\s+(?:on|by|in|at|before)\b)|渲染(完成|成功|好了|出来了)|已渲染|成片(渲染)?(完成|已出)|已经渲染)", re.I), {"render", "run"}),
    ("pushed", re.compile(
        r"(\b(?:is|are|was|were|been|got|all|both|everything)\s+pushed\b(?!\s+(?:back|down|through|out|aside|into|onto|over|forward|around|away|up against)\b)|\bpushed\b(?=\s*(?:$|[.,;:!)(\]]|to\b|up to\b|it\b|and\b|everything\b|both\b|the (?:branch|commit|commits|fix|change|changes|code|tag|tags|PR)\b|\S+/\S+))"
        r"|\bgit pushed\b|已推送|推送(完成|成功|到了))", re.I), {"push"}),  # "pushed back", "pushed the button" are not git
    ("committed", re.compile(
        r"(\bcommitted\b(?=\s*(?:$|[.,;:!)(\]]|and\b|it\b|everything\b|both\b|as\b|with\b|on\b|to (?:git|the repo|main|master|\S+ branch)\b|the (?:fix|change|changes|code|files?|work)\b|\d))"
        r"|已提交到?(仓库|git|分支|主分支)|提交了 ?commit|打了 ?(tag|标签))", re.I), {"commit"}),  # "committed to the plan", "committed to memory" are not git
    ("fixed", re.compile(
        r"((?:\b(?:is|are|was|were|now|got|been|just|I|we|it's|that's|bug|issue|problem|error|crash|leak|typo|regression)\s+fixed\b(?!\s+(?:at|bed|point|width|size|length|rate|cost|income|price|position|number|value|set|interval|schedule|header|layout|effect|asset|term)\b)"
        r"|\bfixed\b(?!\.\w)(?=\s*(?:$|[.,;:!)\]]|the\b|it\b|this\b|that\b|both\b|all\b|these\b|those\b|in\b|by\b|and\b|now\b|with\b|via\b|up\b|a\b|an\b|my\b|your\b|our\b|\d)))"
        r"|已修复|修复了|修好了|修复完成|bug 已解决|问题已解决)", re.I), {"test", "build", "render"}),  # "fixed bed reactor", "fixed-point", "fixed width" are adjectives, not a claim  # a generic script run is not evidence that a fix works
    ("verified", re.compile(r"(\b(?:is|are|was|were|been|all|now|I|we|both|everything)\s+verified\b(?!\s+(?:wording|results?|numbers?|data|version|claims?|facts?)\b)|\bverified\b(?=\s*(?:$|[.,;:!)]|by\b|against\b|with\b|that\b|in\b))|\bI('ve| have) (tested|checked|confirmed)\b|已验证|验证通过|核对无误|确认无误|跑通了|实测(通过|可用|正常)|检查过了)", re.I), {"verified"}),  # needs a run, a read or a screenshot in the turn
]
from . import noncode as _noncode  # noqa: E402  (claims about sending, deploying, downloading, saving, checking, scheduling)
CLAIM_PATTERNS[-1:-1] = [(name, pat, {name}) for name, pat in _noncode.CLAIMS]


NOT_A_CLAIM = re.compile(
    r"((?:\d+|[一二三四五六七八九十几多])类[：:]|types? of claims?|claim (?:types|categories)|kinds? of claims?|(?:只|仅|都|全部)?保存在(?:本地|仓库|数据库|服务器|云端)|(?:is|are) (?:only |all )?(?:stored|kept) (?:in|on|locally)|\b(?:the )?(?:user|you|they|he|she|someone|the team|the maintainers?) (?:sent|said|asked|replied|pushed|deployed|saved|checked|downloaded)\b|(?:用户|你|他|她|对方|他们)(?:已经|刚|刚刚)?(?:发了|发来|发过|推了|部署了|保存了|查了|下载了)|接下来|下一步|我会|我将|我来|然后再|正在|还没|尚未|未验证|not yet|haven'?t|hasn'?t|nothing (?:is|was|has been)|\bnot \w+ yet\b|isn'?t \w+ yet|should pass|应该(能|会)|等.{0,8}(完成|渲染|通过|通知)|通知我|被标记|标记为|标记\"|^running|^re-running|^checking|^verifying|^now (?:running|re-?running|checking|verifying|testing|building|rendering|let)|^next|syntax[- ]?check|只做了语法检查"
    r"|需要你|请你|你可以|you can|\?|？|待验证"
    r"|\b[1-9]\d* failed\b|\d+ 个?失败|but (?:now |still )?fail|但.{0,12}(报错|失败|出错|不过)"  # honest partial results are not a pass claim
    r"|\bupstream\b|according to|\bin (?:v\d|version \d|python ?\d|node ?\d|chrome ?\d|#\d)|上游|按照?文档|文档(说|写|里)|之前已|已修复的|曾经"  # someone else fixed it, somewhere else
    r"|通过率|通过的(条件|用例|标准)|position:\s*fixed|transaction"
    r"|我也会|我还会|我再|完成后会|之后会|会出现在|默认保存|通常保存|一般保存|会保存到|核实过的|核对过的|验证过的|下载完成后|不会丢"  # future, generic behaviour, adjectives, state
    r"|^(意思是|也就是说|换句话说|即|比如|例如|e\.g\.|i\.e\.|that means|this means|in other words|for example|meaning)\b|意思是[:：]|\b(you|he|she|they) (said|say|wrote|claimed)\b|你说|他说|它说|审查员|reviewer (said|wrote)"  # explaining or quoting, not claiming
    r"|\bprevious|yesterday|last (?:week|run|time)|only on \w+ (?:but|and)|only (?:on|in) (?:linux|mac|windows|ci)\b"  # another time or place
    r"|\[J\]|\bet al\b|\bdoi\b|\bvol\.\s*\d|\bpp\.\s*\d|\bISBN\b|\bISSN\b"  # bibliography entries
    r"|\bI'?m re-?(running|rendering|testing|checking)\b|\bto (check|verify|confirm)\b)", re.I)  # says a check is still coming
# forward-looking words only disqualify a claim when they come BEFORE it ("if tests pass" vs "tests pass, even if X")
PREFIX_NOT_CLAIM = re.compile(r"(准备|will |I'll|I’ll|we'll|next,? I|let me|going to|while |如果|\bif |一旦|\bonce |^then |直到|\buntil\b|\bbefore (?:I|we|my|the|this)\b|make sure|\bensure\b)", re.I)   # "make sure tests pass" is an instruction; "tests pass, make sure to…" still a claim
REMOTE_RUN = re.compile(r"(kaggle|冒烟|压力测试|\bCI\b|notebook|公榜|提交版|提交前检查|runpod|colab|github actions|workflow run)", re.I)
QUOTES = "\"“”「」『』"
APOSTROPHE_QUOTE = re.compile(r"(?<!\w)['’]|['’](?!\w)")   # a straight or curly quote that is not inside a word (I've, user's)


@dataclass
class ClaimHit:
    category: str
    sentence: str
    evidence_kinds: set


def split_sentences(text: str):
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith(">"))
    text = re.sub(r"`([^`\n]*)`", r"\1", text)   # keep the words inside inline code: file names and commands are what the claim is about
    text = "\n".join(l for l in text.splitlines() if not re.match(r"\s*(#{1,6}\s|\|)", l) and not re.match(r"\s*\*\*[^*\n]{1,80}\*\*\s*[:：]?\s*$", l))   # headings, table rows, bold-only lines
    text = re.sub(r"(?m)^\s*(?:[-*+]\s+)?(?:\[[ xX]\]\s+)?", "", text)                        # list markers, checkboxes
    parts = re.split(r"(?<=[。！!\.?？])\s+|\n+|(?<=[。！？])", text)   # a question ends a sentence too
    return [p.strip() for p in parts if p and p.strip()]


def _quote_count(s: str) -> int:
    return sum(s.count(q) for q in QUOTES) + len(APOSTROPHE_QUOTE.findall(s))


def _inside_quotes(sent: str, start: int, end: int) -> bool:
    return _quote_count(sent[:start]) >= 1 and _quote_count(sent[end:]) >= 1


IGNORE_PHRASES: tuple = ()        # set by config.apply(): a sentence containing one of these is never a claim
DISABLED: frozenset = frozenset()  # set by config.apply(): claim categories switched off


def find_claims(text: str):
    hits = []
    for sent in split_sentences(text):
        if len(sent) > 400 or NOT_A_CLAIM.search(sent):
            continue
        low = sent.lower()
        if any(p in low for p in IGNORE_PHRASES):
            continue
        for name, pat, kinds in CLAIM_PATTERNS:
            if name in DISABLED:
                continue
            m = pat.search(sent)
            if m and not _inside_quotes(sent, m.start(), m.end()) and not PREFIX_NOT_CLAIM.search(sent[:m.start()]):
                hits.append(ClaimHit(name, sent, kinds))
                break
    return hits


# ------------------------------------------------------------ edits & paths
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
DOC_EXT = {".md", ".txt", ".rst", ".csv", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".mp4", ".mp3", ".wav", ".srt", ".log", ".example", ".b64", ".jsonl", ".mdc"}
# directories and file names that hold notes rather than code; anchored, so `src/prompts/builder.py` or `proj/tmp/app.py` stay code
DOC_DIRS = re.compile(
    r"(^docs?/|/docs?/|/memory/|/scratchpad/|/(?:reports?|notes?|research_notes)/[^/]*\.(?:md|txt|rst|csv|json|html|pdf)$|/\.claude/projects/"
    r"|(?:^|/)(?:README|CHANGELOG|HANDOFF|PROMPTS?)(?:[^/]*\.(?:md|txt|rst))?$|(?:^|/)(?:AGENTS|CLAUDE|GEMINI)\.md$|(?:^|/)\.env(?:\.[\w.-]+)?$|(?:^|/)\.gitignore$|(?:^|/)\.gitattributes$|(?:^|/)LICENSE[^/]*$"
    r"|side-session-notes|Application Support/Claude|(^|/)\.agent/|(^|/)\.claude/|state\.json$|progress\.md|日志|复盘|方案|笔记|文案|计划|清单|情报|记录|台账"
    r"|^/tmp/|^/private/tmp/|^/var/folders/|AppData/Local/Temp/|/Temp/claude)", re.I)
TMP_CWD = re.compile(r"(^|\s)cd (/private/tmp|/tmp|\S*scratchpad)")
INTERP = re.compile(r"(python3?|node|bash|zsh|\bsh|ruby|perl|psql|sqlite3|uv run|\.venv/bin/python3?)\b[^\n]*<<")
WRITE_MARK = re.compile(r"(write_text\(|open\([^)]*['\"][wa]\+?['\"]|\.write\(|writeFileSync|fs\.write|shutil\.(copy|move)|os\.rename|Path\([^)]*\)\.touch)")
PLAIN_EDIT = re.compile(r"(sed -i|\btee\b|cat >>?|(^|[\s)])>>?(?![=>])\s*[^&>/ \n=]|git checkout --|git checkout \S+ -- |git reset --hard|git stash (pop|apply)|git revert|git apply|(?:^|\|)\s*(?:sudo\s+)?patch\b)")   # `patch` only as the verb: `grep mock.patch` reads
PLAIN_EDIT_EXCLUDE = re.compile(r"(>\s*/dev/null|2>&1|&>)")
REDIRECT_TARGET = re.compile(r"(?:cat >>? ?|tee -a |tee |[\s)]>>?(?![=>]) ?)\"?([\w./~\-一-鿿 ]+?\.[A-Za-z0-9]+)\"?(?=\s|$|&|;|\|)")
QUOTED_PATH = re.compile(r"['\"]([^'\"\n]+\.(?:py|js|mjs|cjs|ts|tsx|jsx|html|css|scss|json|toml|yaml|yml|sh|zsh|go|rs|java|kt|swift|c|cc|cpp|h|rb|php|sql|tex|ipynb|vue|svelte|glsl|cfg|ini|md|txt|rst|csv|log|jsonl))['\"]")
HEADER_PATH = re.compile(r"(?:^|\s)\"?((?:~|/|\.{1,2}/)?[\w./~\-\u4e00-\u9fff]+/[\w.\-\u4e00-\u9fff]+\.[A-Za-z0-9]{1,5})\"?")
COMMIT_MSG = re.compile(r"(-m\s+(\"[^\"]*\"|'[^']*')|<[^<>\s]+@[^<>\s]+>)")
HEREDOC_HEAD = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?")


def path_is_doc(path: str) -> bool:
    if not path:
        return False
    path = path.replace("\\", "/")   # Claude Code on Windows writes native paths
    ext = os.path.splitext(path.strip())[1].lower()
    return ext in DOC_EXT or bool(DOC_DIRS.search(path))


@dataclass
class Segment:
    text: str
    heredoc: bool = False
    interp: bool = False   # heredoc fed to an interpreter (code), else data


def _split_shell(line: str):
    """Split on && || ; and newline outside quotes (keeps for/if blocks loosely together)."""
    out, buf, q, i = [], [], None, 0
    while i < len(line):
        ch = line[i]
        if q:
            buf.append(ch)
            if ch == q and (i == 0 or line[i - 1] != "\\"):
                q = None
        elif ch in ("'", '"'):
            q = ch; buf.append(ch)
        elif line.startswith("&&", i) or line.startswith("||", i):
            out.append("".join(buf)); buf = []; i += 1
        elif ch == ";" and not re.match(r";\s*(do|then|fi|done)\b", line[i:]):
            out.append("".join(buf)); buf = []
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf))
    return [x.strip() for x in out if x.strip()]


def _strip_comments(text: str) -> str:
    """Drop `# …` to the end of the line outside quotes: an apostrophe in a comment must not swallow the next command."""
    out, q, i, n = [], None, 0, len(text)
    while i < n:
        ch = text[i]
        if q:
            out.append(ch)
            if ch == q and text[i - 1] != "\\":
                q = None
        elif ch in ("'", '"'):
            q = ch; out.append(ch)
        elif ch == "#" and (i == 0 or text[i - 1] in " \t;&|(\n"):
            j = text.find("\n", i)
            if j == -1:
                break
            i = j
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def segments(cmd: str):
    """Split a shell command into segments; a heredoc block is one segment.
    Quotes are respected across lines, so a multi-line commit message stays inside its git commit segment."""
    lines = cmd.split("\n")
    blocks = {}
    flat = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = HEREDOC_HEAD.search(line)
        if m:
            term = m.group(1)
            block = [line[m.start():]]
            j = i + 1
            while j < len(lines) and lines[j].strip() != term:
                block.append(lines[j]); j += 1
            if j < len(lines):
                block.append(lines[j]); j += 1
            key = f"__HD{len(blocks)}__"
            blocks[key] = "\n".join(block)
            flat.append(line[:m.start()] + key)
            i = j
        else:
            flat.append(line); i += 1
    text = _strip_comments("\n".join(flat))
    out = []
    for seg in _split_shell(text.replace("\n", " ; ")):
        key = next((k for k in blocks if k in seg), None)
        if key:
            body = blocks[key]
            seg_text = seg.replace(key, body)
            head = seg.replace(key, body.split("\n", 1)[0])
            out.append(Segment(seg_text, heredoc=True, interp=bool(INTERP.search(head))))
        else:
            out.append(Segment(seg))
    return out


CODE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".css", ".scss", ".json", ".toml", ".yaml", ".yml", ".sh", ".zsh", ".go", ".rs", ".java", ".kt", ".swift", ".c", ".cc", ".cpp", ".h", ".rb", ".php", ".sql", ".tex", ".ipynb", ".vue", ".svelte", ".glsl", ".txt.j2", ".cfg", ".ini"}
ASSIGN = re.compile(r"(?m)^\s*(\w+)=\"?([^\"\n;&|]+)\"?")


def _resolve_vars(text: str, whole_cmd: str) -> str:
    env = dict(ASSIGN.findall(whole_cmd))
    def rep(m):
        return env.get(m.group(1), m.group(0))
    return re.sub(r"\$\{?(\w+)\}?", rep, text)


def segment_targets(seg: Segment, whole_cmd: str = ""):
    if seg.heredoc and seg.interp:
        header = _resolve_vars(seg.text.split("\n", 1)[0], whole_cmd)
        hpaths = [h for h in HEADER_PATH.findall(header) if "<<" not in h]
        paths = QUOTED_PATH.findall(seg.text)
        if hpaths and ("sys.argv" in seg.text or not paths):
            paths = hpaths + paths
        code = [t for t in paths if os.path.splitext(t)[1].lower() in CODE_EXT and not path_is_doc(t)]
        docs = [t for t in paths if path_is_doc(t)]
        if docs and not code:
            return docs
        return code or paths
    if seg.heredoc:
        return REDIRECT_TARGET.findall(_resolve_vars(seg.text.split("\n", 1)[0], whole_cmd))
    c = PLAIN_EDIT_EXCLUDE.sub(" ", _resolve_vars(seg.text, whole_cmd))
    t = REDIRECT_TARGET.findall(c)
    if "sed -i" in c:
        try:
            toks = shlex.split(c)
        except ValueError:
            toks = c.split()
        if toks:
            t.append(toks[-1])
    return t


def segment_is_edit(seg: Segment, whole_cmd: str = "") -> bool:
    if seg.heredoc and seg.interp:
        if not WRITE_MARK.search(seg.text):
            return False
    elif seg.heredoc:
        if not re.search(r"(cat >>?|\btee\b)", seg.text.split("\n", 1)[0]):
            return False
    else:
        c = COMMIT_MSG.sub(" ", PLAIN_EDIT_EXCLUDE.sub(" ", seg.text))
        if not PLAIN_EDIT.search(c):
            return False
        # a plain `cmd > file` only authors a file when the verb writes agent-authored content;
        # `pytest > log`, `honestly audit > summary.json`, `ffmpeg ... > x` are program output, not code edits
        if not re.search(r"(sed -i|\btee\b|cat >>?|git checkout --|git checkout \S+ -- |git reset --hard|git stash (pop|apply)|git revert|git apply|(?:^|\|)\s*(?:sudo\s+)?patch\b)", c):
            if not re.match(r"\s*(cat|echo|printf|tee|sed|awk|perl|jq|cp|mv)\b", c):
                return False
    targets = [t.strip() for t in segment_targets(seg, whole_cmd)]
    if targets and all(path_is_doc(t) for t in targets):
        return False
    head = seg.text.split("\n", 1)[0]
    if not targets and re.search(r"(cat >>?|\btee\b|[\s)]>>?)\s*\"?\$", head):
        return False   # redirect into an unresolved variable: unknown target, do not count as a code edit
    return True


WIN_DRIVE = re.compile(r"\b[A-Za-z]:\\")


def bash_is_edit(cmd: str) -> bool:
    if WIN_DRIVE.search(cmd):
        cmd = cmd.replace("\\", "/")   # only for path matching; this copy is not executed
    segs = segments(cmd)
    if segs and TMP_CWD.search(segs[0].text):
        return False
    if re.search(r"((?:^|[\s=\"'(])/private/tmp/|(?:^|[\s=\"'(])/tmp/|(?:^|[\s=\"'(])/var/folders/|scratchpad|AppData/Local/Temp|tempfile\.|mkdtemp\(|NamedTemporaryFile|TemporaryDirectory)", cmd) and not re.search(r"(sed -i|write_text|open\([^)]*['\"][wa])", cmd):
        return False
    return any(segment_is_edit(s, cmd) for s in segs)


# ------------------------------------------------------------ verification
VERIFY = {
    "test": re.compile(r"(\bpytest\b|python3? -m pytest|python3? -m unittest|\bunittest\b|\btox\b|\bnox\b|hatch test|poetry run pytest|uv run pytest"
                       r"|npm (run )?test|pnpm (run )?test|yarn (run )?test|bun test|deno test|npx (jest|vitest|mocha|ava|playwright test|cypress run)|\bjest\b|\bvitest\b|\bmocha\b"
                       r"|\bgo test\b|cargo test|cargo nextest|mvnw? (test|verify)|gradlew? (test|check)|dotnet test|swift test|xcodebuild test|flutter test|mix test|bundle exec rspec|\brspec\b|rake test|\bphpunit\b|\bpest\b|\bctest\b|make test|make check"
                       r"|src/eval\.py|\beval\.py|_test\.(go|py|ts|js)\b|scripts?/[\w-]*test[\w-]*\.(sh|py)|\bcheck\.sh|run_tests|gh pr checks|gh run (view|list|watch)|statusCheckRollup|validate[\w_]*\.py|check[\w_]*\.py|verify[\w_]*\.py|gate\.py)", re.I),
    "build": re.compile(r"(\btsc\b|\beslint\b|prettier --check|\bbiome\b|\bruff\b|\bmypy\b|\bpyright\b|black --check|\bflake8\b|\bpylint\b|\bisort --check"
                        r"|npm run build|pnpm (run )?build|yarn (run )?build|vite build|next build|cargo (build|check|clippy)|cargo fmt --check|go build|go vet|staticcheck|golangci-lint"
                        r"|mvnw? (compile|package|verify)|gradlew? (build|assemble|check)|dotnet build|swift build|xcodebuild|\bmake\b|\bphpstan\b|\bpsalm\b|\brubocop\b|\bshellcheck\b|terraform validate|docker build"
                        r"|hyperframes(@[\w.]+)? check|tectonic|xelatex|latexmk|pdflatex|pdftotext|pdfinfo|python3? -m py_compile|python3? -c ['\"]import |validate[\w_]*\.py|check[\w_]*\.py|verify[\w_]*\.py|lint[\w_]*\.py|qc\.py|build\.log)", re.I),
    "render": re.compile(r"(hyperframes(@[\w.]+)? (render|build)|\bffmpeg\b|\bffprobe\b|npx remotion render|manim |blender |music[\w-]*\.sh|render[\w-]*\.sh)", re.I),
    "push": re.compile(r"(git push|kaggle kernels push|kaggle competitions submit|kernels push)", re.I),
    "commit": re.compile(r"(git commit|git tag)", re.I),
    "run": re.compile(r"(python3? (-I )?\S+\.py|python3? -m (?!http)|python3? -c|python3? - <<|node \S+\.(m?js|ts)|node --check|npx (?!remotion)\S+|\bcurl\b|bash \S+\.sh|\bsh \S+\.sh|\./\S+|cargo run|go run|\bmake\b|docker (build|compose up|run)|kaggle kernels (status|output)|uv run (python|pytest|ruff|mypy|-q python|-q pytest)|\.venv/bin/python)", re.I),
}
PIPE_SWALLOW = re.compile(r"\|\s*(tail|head|grep|egrep|rg|awk|sed|wc|sort|uniq|cut|tee|less|more)\b")   # the pipeline exits with the last command's status
NARROWED_TEST = re.compile(r"(pytest[^|\n]*\s-k\s|--testNamePattern|-t ['\"]|pytest[^|\n]*\s[\w/]+\.py::|pytest\s+[\w/]+\.py\b)", re.I)
OPAQUE_TOOLS = {"Agent", "Task", "Monitor", "mcp__terminal__run_in_terminal", "Workflow"}


NON_VERIFY_VERB = re.compile(r"^\s*(export |cd |pip3? |pipx |uv (?:pip|add|sync|lock|tool)\b|poetry (?:add|install|lock)\b|npm (?:install|i|ci|ls|list|view|info)\b|yarn (?:add|install)\b|pnpm (?:add|install|i)\b|apt(?:-get)? |conda |ls\b|cat\b|grep\b|rg\b|echo\b|printf\b|find\b|wc\b|head\b|tail\b|sed\b|awk\b|less\b|more\b|diff\b|jq\b|cut\b|sort\b|uniq\b|xargs\b|stat\b|tree\b|nl\b|bat\b|column\b|brew\b|which\b|pkill\b|kill\b|sleep\b|until\b|while\b|mkdir\b|cp\b|mv\b|rm\b|git (add|status|log|diff|remote|config|stash|checkout)|ps\b|lsof\b|open\b|df\b|du\b|date\b|\w+=)")
SERVER = re.compile(r"(uvicorn|http\.server|\bserve\b|\bdev\b|--watch|streamlit run|gunicorn|flask run|next dev|vite\b)", re.I)


def verifying_segments(cmd: str, kinds: set, after_edit_only: bool = False):
    segs = segments(cmd)
    if after_edit_only:
        last = max((i for i, s in enumerate(segs) if segment_is_edit(s, cmd)), default=-1)
        segs = segs[last + 1:]
    out = []
    for s in segs:
        if segment_is_edit(s, cmd) or (s.heredoc and not s.interp) or (s.heredoc and s.interp and WRITE_MARK.search(s.text)):
            continue
        probe = s.text.split("\n", 1)[0] if s.heredoc else s.text   # judge interpreter heredocs by their header line
        probe = re.sub(r"^(\s*\w+=\S+\s+)+", "", probe)   # strip leading VAR=value prefixes
        if NON_VERIFY_VERB.search(probe) and not re.search(r"gh (pr checks|run)", probe):
            continue
        if SERVER.search(probe) and not re.search(r"(pytest|test|check)", probe):
            continue
        if any(VERIFY[k].search(probe) for k in kinds if k in VERIFY):
            out.append(s)
    return out


def bash_verifies(cmd: str, kinds: set, after_edit_only: bool = False) -> bool:
    return bool(verifying_segments(cmd, kinds, after_edit_only))
