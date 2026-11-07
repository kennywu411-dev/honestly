"""Deterministic rules: what counts as a claim, an edit, and verification.

Precision over recall. A claim is flagged only when the same turn shows a
code edit and no category-matching verification after it. Anything we
cannot see (subagents, background tasks, the user's own terminal, piped
exit codes) is marked unverifiable, never unbacked.
"""
from __future__ import annotations
import os
import re
import functools
import shlex
import sys
from dataclasses import dataclass

# ----------------------------------------------------------------- claims
CLAIM_PATTERNS = [
    ("tests_pass", re.compile(
        r"((?:all (?:the )?)?tests? (?:are |all )?(?:now )?pass(?:es|ed|ing)?\b(?!\s+(?:a|an|the|its|this|that|my|our|your|each|every|some|any|\w+ (?:to|into|through|as|along|down))\b)(?!\s+\d[\d.]*\s*(?:%|for|as|to|into|instead)\b)(?!\s+(?:whole|raw|plain|real|negative|positive|fractional|decimal)\b)(?!\s+(?:percent(?:age)?s?|values?|numbers?|arguments?|args|strings?|integers?|ints|floats?|decimals?|fractions?|inputs?|params|parameters?|objects?|dicts?|lists?|arrays?|mocks?|fixtures?|data|None|null|True|False|kwargs|cents|prices?|amounts?)\b)"
        r"|\btest suite (?:now )?pass(?:es|ed)?\b|\btests? (?:are|is) (?:all |now )?green\b"
        r"|\b\d+ (tests? )?passed\b|\d+ 个?(测试|用例)(全部|都|均)?通过|测试(全部|都|已|已经|均)?通过|用例(全部|都)?通过)", re.I), {"test"}),
    ("checks_pass", re.compile(
        r"(checks? (all )?pass(es|ed)?\b|lint(ing)? pass(es|ed)?\b|type ?check(s|ing)? pass(es|ed)?\b|build pass(es|ed)?\b|检查(结果)?[:：]?\s*(全部|都|均)?通过|全部通过|lint (全部)?通过|\b0 (错误|warnings?|errors?))", re.I), {"test", "build"}),   # "10 errors" is not "0 errors"
    ("build_ok", re.compile(
        r"(build (succeeded|succeeds|passed|passes|is green|ok)|compiles? (cleanly|fine|ok)|编译通过|构建(成功|通过)|打包(成功|完成)|类型检查通过|lint 通过|ruff 也?通过)", re.I), {"build", "test", "run"}),
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
        r"|已修复|修复了|修好了|修复完成|bug 已解决|问题已解决)", re.I), {"test", "build", "render", "exercise"}),  # "fixed bed reactor", "fixed-point", "fixed width" are adjectives, not a claim; running the fixed code (a repro script, a snippet, curl) counts
    ("verified", re.compile(r"(\b(?:is|are|was|were|been|all|now|I|we|both|everything)\s+verified\b(?!\s+(?:wording|results?|numbers?|data|version|claims?|facts?)\b)|\bverified\b(?=\s*(?:$|[.,;:!)]|by\b|against\b|with\b|that\b|in\b))|\bI('ve| have) (tested|checked|confirmed)\b|已验证|验证通过|核对无误|确认无误|跑通了|实测(通过|可用|正常)|检查过了)", re.I), {"verified"}),  # needs a run, a read or a screenshot in the turn
]
from . import noncode as _noncode  # noqa: E402  (claims about sending, deploying, downloading, saving, checking, scheduling)
CLAIM_PATTERNS[-1:-1] = [(name, pat, {name}) for name, pat in _noncode.CLAIMS]


NOT_A_CLAIM = re.compile(
    r"((?:\d+|[一二三四五六七八九十几多])类[：:]|types? of claims?|claim (?:types|categories)|kinds? of claims?|(?:只|仅|都|全部)?保存在(?:本地|仓库|数据库|服务器|云端)|(?:is|are) (?:only |all )?(?:stored|kept) (?:in|on|locally)|\b(?:the )?(?:user|you|they|he|she|someone|the team|the maintainers?) (?:sent|said|asked|replied|pushed|deployed|saved|checked|downloaded)\b|(?:用户|你|他|她|对方|他们)(?:已经|刚|刚刚)?(?:发了|发来|发过|推了|部署了|保存了|查了|下载了)|接下来|下一步|我会|我将|我来|然后再|正在|还没|尚未|未验证|未经验证|not yet|haven'?t|hasn'?t|(?:AI|助手|智能体|模型|Claude|Codex|agent)[^。！？\n]{0,30}?(?:就说|又说|说了|声称|宣称|谎称|报告说)|\b(?:the|your|my|an?) (?:agent|AI|assistant|model)\b[^.!?\n]{0,40}?\b(?:says|said|claims|claimed|reports|reported|insists|insisted)\b|不能说|不敢说|没法说|无法(?:确认|保证|断言|说)|不能(?:确认|保证|断言)|还不能|(?:没有|没)(?:实际)?(?:运行|跑)(?:过)?(?:任何)?(?:测试|pytest|用例)(?![^。！？.!?]*(?:现在|刚才|已经|然后|随后))|can'?t (?:say|claim|confirm|promise|guarantee)|cannot (?:say|claim|confirm|guarantee)|\bunverified\b|\bnot verified\b|(?:did not|didn'?t|do not|don'?t) (?:run|execute) (?:the |any )?(?:tests?|pytest|test suite)\b(?![^.!?]*\b(?:now|then|after that|so I ran)\b)|nothing (?:is|was|has been)|\bnot \w+ yet\b|isn'?t \w+ yet|should pass|应该(能|会)|等.{0,8}(完成|渲染|通过|通知)|通知我|被标记|标记为|标记\"|^running|^re-running|^checking|^verifying|^now (?:running|re-?running|checking|verifying|testing|building|rendering|let)|^next|syntax[- ]?check|只做了语法检查"
    r"|需要你|请你|你可以|you can|\?|？|待验证"
    r"|\b[1-9]\d* failed\b|\d+ 个?失败|but (?:now |still )?fail|但.{0,12}(报错|失败|出错|不过)"
  # honest partial results are not a pass claim
    r"|\bupstream\b|according to|\bin (?:v\d|version \d|python ?\d|node ?\d|chrome ?\d|#\d)|上游|按照?文档|文档(说|写|里)|之前已|已修复的|曾经|\b(?:pass(?:ed|es)?|green|succeeded)\s+(?:\w+\s+){0,2}?(?:earlier|previously)\b(?![^.!?]*\b(?:now|still|again|after)\b)|\b(?:earlier|previously)[, ]+(?:the |all )?(?:tests?|checks?|runs?)\b(?![^.!?]*\b(?:now|still|again|after)\b)"  # someone else fixed it, somewhere else
    r"|通过率|通过的(条件|用例|标准)|position:\s*fixed|transaction"
    r"|我也会|我还会|我再|完成后会|之后会|会出现在|默认保存|通常保存|一般保存|会保存到|核实过的|核对过的|验证过的|下载完成后|不会丢"  # future, generic behaviour, adjectives, state
    r"|^(意思是|也就是说|换句话说|即|比如|例如|e\.g\.|i\.e\.|that means|this means|in other words|for example|meaning)\b|意思是[:：]|\b(you|he|she|they) (said|say|wrote|claimed)\b|你说|他说|它说|审查员|reviewer (said|wrote)"  # explaining or quoting, not claiming
    r"|\bprevious(?:ly| (?:run|session|turn|attempt|time|conversation))\b(?![^.!?]*\b(?:now|still|again)\b)|yesterday|last (?:week|run|time)|only on \w+ (?:but|and)|only (?:on|in) (?:linux|mac|windows|ci)\b"  # another time or place
    r"|\[J\]|\bet al\b|\bdoi\b|\bvol\.\s*\d|\bpp\.\s*\d|\bISBN\b|\bISSN\b"  # bibliography entries
    r"|\bI'?m re-?(running|rendering|testing|checking)\b|\bto (check|verify|confirm)\b"  # says a check is still coming
    r"|(?:命令|脚本|它|这条|这个|运行后|跑完|执行后)[^，。,；;]{0,4}会(?:显示|提示|打印|输出|告诉你)|\b(?:it|this|that|the (?:command|script|tool|run|output))\s+will\s+(?:show|print|display|tell you|report)\b"  # describes what a command will do
    r"|\d[\d.,]*\s*[KMGT]i?B\s*(?:/|of)\s*\d[\d.,]*\s*[KMGT]i?B"  # a progress fraction such as 635 GB / 680 GB
    r"|\b(?:the|a|stop|honestly(?:'s)?)\s+hook\s+(?:stopped|blocked|held|caught|flagged)\s+(?:me|this|the|my|it)\b|\bhonestly\s+(?:stopped|blocked|held|caught|flagged|stepped in)\b|被\s*(?:honestly|hook|钩子|stop ?hook)\s*拦|(?:我|回复|这条回复|上一条回复)(?:刚才|之前)?被拦(?:下|截|住)?|拦(?:截|下)(?:的)?原因"
    r"|\bbecause I (?:had )?(?:said|claimed)\b|\bI (?:had )?(?:said|claimed)\b[^.!?\n]{0,80}\b(?:without|before (?:I|running|re-?checking|checking)|but (?:hadn'?t|had not|didn'?t|did not))\b)", re.I)  # explaining a block: "the hook stopped me because I said..."
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


LINK_TEXT = re.compile(r"\[[^\[\]\n]*\]\([^)\s]*\)")


def _inside_link(sent: str, start: int, end: int) -> bool:
    return any(m.start() < start and end <= m.end() for m in LINK_TEXT.finditer(sent))


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
            if m and not _inside_quotes(sent, m.start(), m.end()) and not _inside_link(sent, m.start(), m.end()) and not PREFIX_NOT_CLAIM.search(sent[:m.start()]):
                hits.append(ClaimHit(name, sent, kinds))
                break
    return hits


# ------------------------------------------------------------ edits & paths
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
DOC_EXT = {".md", ".txt", ".rst", ".csv", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".mp4", ".mp3", ".wav", ".srt", ".log", ".example", ".b64", ".jsonl", ".mdc"}
# directories and file names that hold notes rather than code; anchored, so `src/prompts/builder.py` or `proj/tmp/app.py` stay code
DOC_DIRS = re.compile(
    r"(^docs?/|/docs?/|/memory/|/scratchpad/|/(?:reports?|notes?|research_notes)/[^/]*\.(?:md|txt|rst|csv|json|html|pdf)$|/\.claude/projects/"
    r"|(?:^|/)(?:README|CHANGELOG|HANDOFF|PROMPTS?)(?:[^/]*\.(?:md|txt|rst))?$|(?:^|/)(?:AGENTS|CLAUDE|GEMINI)\.md$|(?:^|/)\.env(?:\.[\w.-]+)?$|(?:^|/)\.gitignore$|(?:^|/)\.gitattributes$|(?:^|/)\.git/|(?:^|/)\.\w+ignore$|(?:^|/)LICENSE[^/]*$"
    r"|(?:^|/)(?:data|datasets|live|runs|outputs?|results|logs|cache)/(?:[^/]+/)*[^/]+\.(?:json|csv|tsv|parquet|xml)$"   # data and state files a script writes, not code
    r"|side-session-notes|Application Support/Claude|(^|/)\.agent/|(^|/)\.claude/|state\.json$|progress\.md|日志|复盘|方案|笔记|文案|计划|清单|情报|记录|台账"
    r"|^/tmp/|^/private/tmp/|^/var/folders/|AppData/Local/Temp/|/Temp/claude)", re.I)
TMP_CWD = re.compile(r"(^|\s)cd (/private/tmp|/tmp|\S*scratchpad)")
INTERP = re.compile(r"(python3?|node|bash|zsh|\bsh|ruby|perl|psql|sqlite3|uv run|\.venv/bin/python3?)\b[^\n]*<<")
WRITE_MARK = re.compile(r"(write_text\(|write_bytes\(|open\([^)]*['\"](?:[wax][bt]?\+?|r[bt]?\+[bt]?)['\"]|\.write\(|writeFileSync|fs\.write|fs\.promises|shutil\.(copy|move)|os\.(?:rename|replace)|Path\([^)]*\)\.touch|\.touch\()")
PLAIN_EDIT = re.compile(r"(sed -i|\btee\b|cat >>?|(^|[\s)])>>?(?![=>])\s*[^&>/ \n=]|git checkout --|git checkout \S+ -- |git reset --hard|git stash (pop|apply)|git revert|git apply|(?:^|\|)\s*(?:sudo\s+)?patch\b)")   # `patch` only as the verb: `grep mock.patch` reads
PLAIN_EDIT_EXCLUDE = re.compile(r"(>\s*/dev/null|2>&1|&>)")
REDIRECT_TARGET = re.compile(r"(?:cat >>? ?|tee -a |tee |[\s)]>>?(?![=>]) ?)\"?([\w./~\-一-鿿 ]+?\.[A-Za-z0-9]+)\"?(?=\s|$|&|;|\|)")
QUOTED_PATH = re.compile(r"['\"]([^'\"\n]+\.(?:py|js|mjs|cjs|ts|tsx|jsx|html|css|scss|json|toml|yaml|yml|sh|zsh|go|rs|java|kt|swift|c|cc|cpp|h|rb|php|sql|tex|ipynb|vue|svelte|glsl|cfg|ini|md|txt|rst|csv|log|jsonl))['\"]")
HEADER_PATH = re.compile(r"(?:^|\s)\"?((?:~|/|\.{1,2}/)?[\w./~\-\u4e00-\u9fff]+/[\w.\-\u4e00-\u9fff]+\.[A-Za-z0-9]{1,5})\"?")
COMMIT_MSG = re.compile(r"(-m\s+(\"[^\"]*\"|'[^']*')|<[^<>\s]+@[^<>\s]+>)")
HEREDOC_HEAD = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?")
_QUOTE_SPAN = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'")
PIPEFAIL_ON = re.compile(r"\bset\b[^;&|\n]{0,80}?\s-[a-zA-Z]*o\s+pipefail\b|\b(?:ba|z|k|da)?sh\s+(?:-\S+\s+){0,8}-o\s+pipefail\b|\bsetopt\s+pipe_?fail\b", re.I)
PIPEFAIL_OFF = re.compile(r"\bset\s+\+o\s+pipefail\b|\bunsetopt\s+pipe_?fail\b", re.I)
NOT_A_RUN = re.compile(r"(--collect-only|--co\b|--version|--help|(?:^|\s)-h\b|--list-tests|--list|--dry-run|--showconfig|--fixtures\b|--markers\b|--no-run\b|(?:^|\s)-list\b|\bgo test\s+(?:-\S+\s+)*-c\b"
                       r"|\b(?:tox|nox)\s+(?:-\S+\s+)*-l\b|\bmake\b[^|;&]*\s(?:-n|--just-print)\b)")


def heredoc_head(line: str):
    """The first `<<WORD` on the line that is not inside a quoted string (`echo 'a<<b'; pytest` has no heredoc)."""
    if "<<" not in line:
        return None
    spans = []
    for q in _QUOTE_SPAN.finditer(line):
        if not re.search(r"<<-?\s*$", line[:q.start()]):   # `<<'EOF'`: the quote belongs to the heredoc head
            spans.append((q.start(), q.end()))
    for m in HEREDOC_HEAD.finditer(line):
        if not any(a <= m.start() < b for a, b in spans):
            return m
    return None


def pipe_stages(text: str) -> list:
    """`a | b |& c` -> ["a ", " b ", " c"]; `||` is a list operator, not a pipe (segments() splits on it already)."""
    return re.split(r"(?<!\|)\|&?(?!\|)", text)


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
        while line.rstrip().endswith("\\") and i + 1 < len(lines):   # `pytest tests/ \` + newline + `  -q | tail`
            line = line.rstrip()[:-1] + " " + lines[i + 1]
            i += 1
        m = heredoc_head(line)
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
ASSIGN = re.compile(r"(?m)(?:^|[;&|]\s*)\s*(\w+)=\"?([^\"\n;&|]+)\"?")


@functools.lru_cache(maxsize=512)
def shell_env(cmd: str) -> dict:
    """`VAR=value` assignments in the shell part of a command; a heredoc body is another language (`S=sys.argv[1]`)."""
    keep, term = [], None
    for line in cmd.split("\n"):
        if term is not None:
            if line.strip() == term:
                term = None
            continue
        keep.append(line)
        m = heredoc_head(line)
        if m:
            term = m.group(1)
    return dict(ASSIGN.findall("\n".join(keep)))


def _resolve_vars(text: str, whole_cmd: str) -> str:
    env = shell_env(whole_cmd)
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


TEMP_PATH = re.compile(r"^(?:/private/tmp/|/tmp/|/var/folders/)|(?:^|/)scratchpad(?:/|$)|AppData/Local/Temp|/Temp/claude|^\$TMPDIR")
WRITE_ARG = re.compile(r"\bopen\(\s*(?P<a>[^,()]+?(?:\([^()]*\)[^,()]*?)?)\s*,\s*(?:mode\s*=\s*)?['\"](?:[wax][bt]?\+?|r[bt]?\+[bt]?)['\"]"
                       r"|\((?P<g>[^()]*\([^()]*\)[^()]*)\)\.write_(?:text|bytes)\("
                       r"|(?P<b>\b[\w.]+(?:\([^()]*\))?)\.write_(?:text|bytes)\("
                       r"|fs\.(?:promises\.)?writeFile\(\s*(?P<f>[^,]+),"
                       r"|writeFileSync\(\s*(?P<c>[^,]+),"
                       r"|shutil\.(?:copy\w*|move)\(\s*[^,]+,\s*(?P<d>[^,)]+)"
                       r"|os\.(?:rename|replace)\(\s*[^,]+,\s*(?P<e>[^,)]+)")


def _expr_path(expr: str, body: str, argv: list, depth: int = 0):
    """Best effort: the path a Python/JS expression starts with (a literal, a variable assigned in the script, sys.argv[n])."""
    expr = expr.strip()
    if depth > 5 or not expr:
        return None
    m = re.match(r"^(?:pathlib\.)?(?:Path|PurePath|os\.path\.join|os\.path\.expanduser|os\.path\.abspath|str|path\.join|path\.resolve)\(\s*(.*)", expr)
    if m:
        return _expr_path(m.group(1), body, argv, depth + 1)
    m = re.match(r"^[frbuFRBU]{0,2}(['\"`])(.*?)\1", expr)
    if m:
        lit = m.group(2)
        v = re.match(r"^(?:\{|\$\{)(\w+)\}", lit)
        return _expr_path(v.group(1), body, argv, depth + 1) if v else lit
    m = re.match(r"^(?:sys\.argv|process\.argv)\[(\d+)\]", expr)
    if m:
        i = int(m.group(1)) - (1 if expr.startswith("sys") else 2)
        return argv[i] if 0 <= i < len(argv) else None
    m = re.match(r"^([A-Za-z_]\w*)", expr)
    if m:
        hits = re.findall(rf"(?:^|[;\n])\s*(?:const |let |var )?{m.group(1)}\s*=(?!=)\s*([^;\n]+)", body)
        return _expr_path(hits[-1], body, argv, depth + 1) if hits else None
    return None


UNTRACKED_WRITE = re.compile(r"\.touch\(|fs\.write(?!File(?:Sync)?\()|open\([^)'\"]*,\s*(?:mode\s*=\s*)?[A-Za-z_]\w*\s*[,)]")   # writes whose target this module cannot follow


def writes_only_scratch(seg: Segment, whole_cmd: str = "") -> bool:
    """An interpreter heredoc whose every write goes to a temp or scratch path (a test harness, a probe page) authors no code.
    Any write it cannot follow (an unresolved variable, a mode in a variable) makes it an edit."""
    body = seg.text
    if UNTRACKED_WRITE.search(body):
        return False
    head = body.split("\n", 1)[0]
    try:
        toks = shlex.split(head.split("<<", 1)[0])
    except ValueError:
        toks = head.split("<<", 1)[0].split()
    env = shell_env(whole_cmd)
    def resolve(t):
        return re.sub(r"\$\{?(\w+)\}?", lambda m: env.get(m.group(1), m.group(0)), t)
    argv = [resolve(t) for t in (toks[toks.index("-") + 1:] if "-" in toks else [])]
    targets = []
    for n, m in enumerate(WRITE_ARG.finditer(body)):
        if n >= 200:
            return False
        expr = next(g for g in m.groups() if g)
        path = _expr_path(expr, body, argv)
        if path is None:
            return False
        targets.append(os.path.expanduser(resolve(path)))
    return bool(targets) and all(TEMP_PATH.search(t) or path_is_doc(t) for t in targets)


def segment_is_edit(seg: Segment, whole_cmd: str = "") -> bool:
    if seg.heredoc and re.match(r"^\s*(?:\S*/)?(?:bash|sh|zsh|dash)\b[^<\n]*<<", seg.text):
        body = seg.text.split("\n", 1)[1].rsplit("\n", 1)[0] if "\n" in seg.text else ""
        return bash_is_edit(body)
    if seg.heredoc and seg.interp:
        if not WRITE_MARK.search(seg.text) or writes_only_scratch(seg, whole_cmd):
            return False
    elif seg.heredoc:
        if not re.search(r"(cat >>?|\btee\b)", seg.text.split("\n", 1)[0]):
            return False
    else:
        c = COMMIT_MSG.sub(" ", PLAIN_EDIT_EXCLUDE.sub(" ", seg.text))
        bare = _QUOTE_SPAN.sub(lambda q: q.group(0)[0] + "x" * (len(q.group(0)) - 2) + q.group(0)[-1], c)
        if not PLAIN_EDIT.search(bare):   # `echo "name <a@b>"`: a ">" inside quotes redirects nothing
            return False
        raw = [t.strip("\"'") for t in re.findall(r"(?<![0-9&>])>>?\s*(\"[^\"]+\"|'[^']+'|[^\s;&|<>]+)", c) if t != "/dev/null"]
        if raw and "sed -i" not in c and all(path_is_doc(t) for t in raw):
            return False   # `echo .claude/ >> .git/info/exclude`: no code file is written
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


# ------------------------------------------------------------ projects
CD_DIR = re.compile(r"(?:^|[;&|(\n]\s*)cd\s+(\"[^\"\n]+\"|'[^'\n]+'|[^\s;&|]+)")
GIT_C = re.compile(r"\bgit\s+-C\s+(\"[^\"\n]+\"|'[^'\n]+'|[^\s;&|]+)")
ABS_LITERAL = re.compile(r"['\"]((?:/|~/)[^'\"\n]+?\.[A-Za-z0-9]{1,5})['\"]")
_ROOTS: dict = {}
_GIT_ROOTS: set = set()


def project_of(path: str):
    """The project a path belongs to: the nearest directory with a `.git`, else the first two levels under the
    home directory (~/Documents/foo). None when the path is relative, temporary or unknown."""
    if not path:
        return None
    p = os.path.normpath(os.path.expanduser(path))
    if not os.path.isabs(p) or TEMP_PATH.search(p):
        return None
    if p in _ROOTS:
        return _ROOTS[p]
    root, d = None, p
    for _ in range(40):
        if os.path.exists(os.path.join(d, ".git")):
            root = d
            _GIT_ROOTS.add(d)
            break
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    if root is None:
        home = os.path.expanduser("~")
        if p.startswith(home + os.sep):
            parts = os.path.relpath(p, home).split(os.sep)
            root = os.path.join(home, *parts[:2]) if len(parts) >= 2 else None
        else:
            parts = p.strip(os.sep).split(os.sep)
            root = os.sep + os.path.join(*parts[:2]) if len(parts) >= 2 else None
    _ROOTS[p] = root
    return root


def same_project(a: str, b: str) -> bool:
    """One project, or a repository nested inside another repository (a submodule, a vendored checkout).
    A folder that only got its name from the home-directory fallback contains nothing."""
    if a == b:
        return True
    inner, outer = (a, b) if len(a) > len(b) else (b, a)
    return outer in _GIT_ROOTS and inner.startswith(outer.rstrip(os.sep) + os.sep)


def seg_dir(cmd: str, seg_text: str):
    """The directory a segment of a command ran in: the last `cd` before it (`cd a && build && cd b && pytest` -> b)."""
    pos = cmd.find(seg_text.split("\n", 1)[0][:200])
    if pos < 0:
        return None
    cds = [m for m in CD_DIR.finditer(cmd) if m.start() < pos]
    if cds:
        return os.path.expanduser(_resolve_vars(cds[-1].group(1).strip("\"'"), cmd))
    m = GIT_C.search(seg_text)
    return os.path.expanduser(_resolve_vars(m.group(1).strip("\"'"), cmd)) if m else None


def event_dir(e):
    """Where a tool call worked: an Edit/Write's file, a Bash command's `cd`/`git -C` directory or the first absolute path it names.
    A command that moves between two directories (`cd a && build && cd b && pytest`) has no single place: None."""
    if e.name in EDIT_TOOLS:
        return os.path.expanduser((e.text or "").strip()) or None
    if e.name != "Bash":
        return None
    cmd = e.text or ""
    dirs = {os.path.expanduser(_resolve_vars(m.group(1).strip("\"'"), cmd)) for m in list(CD_DIR.finditer(cmd)) + list(GIT_C.finditer(cmd))}
    if len(dirs) > 1:
        return None
    if dirs:
        return dirs.pop()
    m = ABS_LITERAL.search(cmd)
    if m:
        return os.path.expanduser(m.group(1))
    for m in ABS_TOKEN.finditer(_resolve_vars(cmd, cmd)):   # `G=~/proj; mkdir -p $G/sub`: the first project path it names
        p = m.group(1)
        if not TOOL_PATH.search(p) and not TEMP_PATH.search(p):
            return os.path.expanduser(p)
    return None


def edit_projects(e):
    """The projects an edit wrote to, from each editing segment's own targets (an absolute path, or a relative one under the
    `cd` before it). None when any of them cannot be placed."""
    if e.name in EDIT_TOOLS:
        p = project_of((e.text or "").strip())
        return {p} if p else None
    cmd = e.text or ""
    out = set()
    for seg in segments(cmd):
        if not segment_is_edit(seg, cmd):
            continue
        here = seg_dir(cmd, seg.text)
        targets = [os.path.expanduser(_resolve_vars(t.strip(), cmd)) for t in segment_targets(seg, cmd) if t.strip()] or [""]
        for t in targets:
            path = t if os.path.isabs(t) else (os.path.join(here, t) if here else (event_dir(e) if not t else None))
            p = project_of(path or "")
            if not p:
                return None
            out.add(p)
    return out or None


ABS_TOKEN = re.compile(r"(?:^|[\s=:(])((?:/|~/)[\w.@+\-\u4e00-\u9fff/]+)")
TOOL_PATH = re.compile(r"/(?:s?bin|site-packages|\.venv|venv|node_modules|\.cache|\.local)/|^/(?:usr|opt|bin|sbin|etc|dev|System|Library|Applications)/")


def bash_is_edit(cmd: str) -> bool:
    if WIN_DRIVE.search(cmd):
        cmd = cmd.replace("\\", "/")   # only for path matching; this copy is not executed
    segs = segments(cmd)
    if segs and TMP_CWD.search(segs[0].text):
        return False
    if re.search(r"((?:^|[\s=\"'(])/private/tmp/|(?:^|[\s=\"'(])/tmp/|(?:^|[\s=\"'(])/var/folders/|/scratchpad\b|AppData/Local/Temp|tempfile\.|mkdtemp\(|NamedTemporaryFile|TemporaryDirectory)", cmd) and not re.search(r"(sed -i|write_text|write_bytes|writeFile|open\([^)]*['\"](?:[wax]|r[bt]?\+))", cmd):
        return False
    return any(segment_is_edit(s, cmd) for s in segs)


# ------------------------------------------------------------ verification
VERIFY = {
    "test": re.compile(r"(\bpytest\b|python3? -m pytest|python3? -m unittest|\bunittest\b|\btox\b|\bnox\b|hatch test|poetry run pytest|uv run pytest"
                       r"|npm (run )?test|pnpm (run )?test|yarn (run )?test|bun (run )?test|deno test|manage\.py test|(?:bin/)?rails test|artisan test|\bjust test|hatch run test|pdm (run )?test|npx (jest|vitest|mocha|ava|playwright test|cypress run)|\bjest\b|\bvitest\b|\bmocha\b"
                       r"|\bgo test\b|cargo test|cargo nextest|\bcargo t\b|\bnpm t\b|\bpy\.test\b|bazel test|\bgotestsum\b|\bsbt\b[^|;&\n]*\btest\b|\bdart test\b|node\s+(?:-\S+\s+)*--test\b|mvnw? (test|verify)|gradlew? (test|check)|dotnet test|swift test|xcodebuild test|flutter test|mix test|bundle exec rspec|\brspec\b|rake test|\bphpunit\b|\bpest\b|\bctest\b|make test|make check"
                       r"|(?:(?:^|[\s;&|(])(?:\S*/)?(?:python[\d.]*|uv run(?:\s+python[\d.]*)?|poetry run(?:\s+python[\d.]*)?|pipenv run(?:\s+python[\d.]*)?|hatch run|pdm run|node|bun|deno run|bash|sh|zsh|ruby|go run|tsx)\s+(?:-\S+\s+)*|^\s*|(?<![\w/.-])\./)(?:[\w.~/-]*/)?(?:eval\.py|[\w-]*_test\.(?:go|py|ts|js)|[\w-]*test[\w-]*\.(?:sh|py)|check[\w-]*\.sh|run_tests[\w.]*|validate[\w-]*\.py|check[\w-]*\.py|verify[\w-]*\.py|gate\.py)\b|gh pr checks|gh run (view|list|watch)|statusCheckRollup)", re.I),
    "build": re.compile(r"(\btsc\b|\beslint\b|prettier --check|\bbiome\b|\bruff\b|\bmypy\b|\bpyright\b|black --check|\bflake8\b|\bpylint\b|\bisort --check"
                        r"|npm run build|pnpm (run )?build|yarn (run )?build|(?:npm run|pnpm( run)?|yarn( run)?) (?:lint|typecheck|type-check)\b|vite build|next build|cargo (build|check|clippy)|cargo fmt --check|go build|go vet|staticcheck|golangci-lint"
                        r"|mvnw? (compile|package|verify)|gradlew? (build|assemble|check)|dotnet build|swift build|xcodebuild|\bmake\b(?!\s+(?:clean|distclean|install|uninstall|help|fmt|format)\b)|\bphpstan\b|\bpsalm\b|\brubocop\b|\bshellcheck\b|terraform validate|docker build"
                        r"|hyperframes(@[\w.]+)? (?:check|lint|validate|inspect)|tectonic|xelatex|latexmk|pdflatex|pdftotext|pdfinfo|python[\d.]*(?:\s+-[A-Za-z]+)*\s+-m py_compile|"
                        r"(?:(?:^|[\s;&|(])(?:\S*/)?(?:python[\d.]*|uv run(?:\s+python[\d.]*)?|poetry run(?:\s+python[\d.]*)?|pipenv run(?:\s+python[\d.]*)?|hatch run|pdm run|node|bun|deno run|bash|sh|zsh|ruby|go run|tsx)\s+(?:-\S+\s+)*|^\s*|(?<![\w/.-])\./)(?:[\w.~/-]*/)?(?:validate[\w-]*\.py|check[\w-]*\.py|verify[\w-]*\.py|lint[\w-]*\.py|qc\.py|build[\w-]*\.(?:py|sh))\b"
                        r"|ast\.parse\(|\bcompileall\b|\b(?:ba|z)?sh -n\b|\bphp -l\b|\bruby -c\b)", re.I),   # syntax checks
    "render": re.compile(r"(hyperframes(@[\w.]+)? (render|build)|\bffmpeg\b|\bffprobe\b|npx remotion render|manim |blender |music[\w-]*\.sh|render[\w-]*\.sh)", re.I),
    "push": re.compile(r"(git push|kaggle kernels push|kaggle competitions submit|kernels push)", re.I),
    "commit": re.compile(r"(git commit|git tag)", re.I),
    "run": re.compile(r"(python[\d.]*(?:\s+-[A-Za-z]+)*\s+(?:\S+\.py|-m (?!http)|-c\b|- <<)|node \S+\.(m?js|ts)|node --check|npx (?!remotion)\S+|\bcurl\b|bash \S+\.sh|\bsh \S+\.sh|\./\S+|cargo run|go run|\bmake\b|docker (build|compose up|run)|kaggle kernels (status|output)|uv run (python|pytest|ruff|mypy|-q python|-q pytest)|\.venv/bin/python)", re.I),
}
PIPE_SWALLOW = re.compile(r"\|&?\s*(tail|head|grep|egrep|rg|awk|sed|wc|sort|uniq|cut|tee|less|more)\b")   # the pipeline exits with the last command's status (`|&` pipes stderr too)
NARROWED_TEST = re.compile(r"(pytest[^|\n]*\s-k\s|--testNamePattern|-t ['\"]|pytest[^|\n]*\s[\w/]+\.py::|pytest\s+[\w/]+\.py\b)", re.I)
OPAQUE_TOOLS = {"Agent", "Task", "Monitor", "mcp__terminal__run_in_terminal", "Workflow"}


NON_VERIFY_VERB = re.compile(r"^\s*(export |cd |pip3? |pipx |uv (?:pip|add|sync|lock|tool)\b|poetry (?:add|install|lock)\b|npm (?:install|i|ci|ls|list|view|info)\b|yarn (?:add|install)\b|pnpm (?:add|install|i)\b|apt(?:-get)? |conda |ls\b|cat\b|grep\b|rg\b|echo\b|printf\b|find\b|wc\b|head\b|tail\b|sed\b|awk\b|less\b|more\b|diff\b|jq\b|cut\b|sort\b|uniq\b|xargs\b|stat\b|tree\b|nl\b|bat\b|column\b|brew\b|which\b|pkill\b|kill\b|sleep\b|until\b|while\b|mkdir\b|cp\b|mv\b|rm\b|git (add|status|log|diff|remote|config|stash|checkout)|gh (?!run\b|pr checks\b|workflow\b)\S+|ps\b|lsof\b|open\b|df\b|du\b|date\b|man\b|type\b|history\b|whatis\b|apropos\b|tldr\b|command -v\b|docker (?:compose )?logs\b|kubectl logs\b|journalctl\b|\w+=)")
SERVER = re.compile(r"(uvicorn|http\.server|\bserve\b|(?<!/)\bdev\b(?!/)|--watch|streamlit run|gunicorn|flask run|next dev|vite\b)", re.I)


INTERP_INLINE = re.compile(r"(?:^|[\s/])(?:bash|sh|zsh|dash|python[\d.]*|node|bun|deno|ruby|perl)\s+(?:-\w+\s+)*-l?[ce]\b")
QUOTED_ARG = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'")


TEST_IMPORT = re.compile(r"(?:^|[\s;'\"(])(?:import\s+(?:[\w.]+\.)?test_\w+|from\s+(?:[\w.]+\.)?test_\w+\s+import)\b", re.M)   # a snippet that runs the test functions itself
TEST_CALL = re.compile(r"\btest_\w*\s*\(|getattr\(|startswith\(\s*['\"]test_")
PY_C = re.compile(r"python[\d.]*(?:\s+-[A-Za-z]+)*\s+-c\s*(['\"])(.*?)(?<!\\)\1", re.S)
IMPORT_STMT = re.compile(r"\s*(?:import\s+[\w.]+(?:\s+as\s+\w+)?(?:\s*,\s*[\w.]+(?:\s+as\s+\w+)?)*|from\s+[\w.]+\s+import\s+[\w*]+(?:\s+as\s+\w+)?(?:\s*,\s*\w+(?:\s+as\s+\w+)?)*)\s*")


def import_only(cmd: str) -> bool:
    """`python -c "import foo"`: an import check, nothing more (`import json; print(...)` is not)."""
    m = PY_C.search(cmd)
    if not m:
        return False
    stmts = [x for x in re.split(r"[;\n]", m.group(2)) if x.strip()]
    return bool(stmts) and all(IMPORT_STMT.fullmatch(x) for x in stmts)


_STDLIB = frozenset(getattr(sys, "stdlib_module_names", ()) or (
    "abc argparse array ast asyncio base64 bisect bz2 calendar cmath codecs collections colorsys concurrent configparser contextlib copy csv ctypes "
    "dataclasses datetime decimal difflib dis email enum errno filecmp fnmatch fractions functools gc getpass glob gzip hashlib heapq hmac html http "
    "importlib inspect io ipaddress itertools json keyword linecache locale logging lzma math mimetypes multiprocessing numbers operator os pathlib "
    "pickle pkgutil platform plistlib pprint queue random re sched secrets select shlex shutil signal site socket sqlite3 ssl stat statistics string "
    "struct subprocess sys sysconfig tarfile tempfile textwrap threading time timeit tokenize tomllib traceback types typing unicodedata unittest "
    "urllib uuid warnings wave weakref xml zipfile zlib").split())
# libraries and tools: importing them reads data or runs a tool, it does not exercise the project's own code
NOT_PROJECT = frozenset("pip pipx venv virtualenv ensurepip pytest build twine setuptools wheel black ruff mypy isort flake8 pylint pyright IPython "
                        "jupyter notebook nbconvert pre_commit tox nox huggingface_hub kaggle gdown numpy pandas PIL requests httpx yaml toml tomli "
                        "matplotlib scipy sklearn torch transformers bs4 lxml openpyxl docx pptx fitz pypdf cv2 tqdm rich click typer playwright "
                        "selenium boto3 anthropic openai".split())
PY_RUN = re.compile(r"^\s*(?:\S*/)?(?:python[\d.]*|uv run(?:\s+python[\d.]*)?|poetry run(?:\s+python[\d.]*)?|pipenv run(?:\s+python[\d.]*)?)(?:\s+-(?![cm]\b)[A-Za-z]+)*\s+(?P<rest>\S.*)", re.S)
EXERCISE_CMD = re.compile(r"^\s*(?:\S*/)?(?:node|deno run|bun(?:\s+run)?|tsx|ts-node|npx\s+(?:tsx|ts-node))\s+(?:-\S+\s+)*[\w./~-]+\.(?:m?js|cjs|tsx?)\b"
                          r"|^\s*(?:go run|cargo run|dotnet run|swift run|java\s+-jar)\b|^\s*(?:ruby|php)\s+[\w./~-]+\.(?:rb|php)\b|^\s*\.{1,2}/[\w./-]+"
                          r"|^\s*(?:curl|wget|https?)\b[^|;&]*\b(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])", re.I)


def _project_imports(code: str) -> bool:
    names = []
    for stmt in re.split(r"[;\n]", code):
        m = re.match(r"\s*from\s+(\.*)([\w.]*)\s+import\b", stmt)
        if m:
            if m.group(1):
                return True   # a relative import is the project's own code
            names.append(m.group(2))
            continue
        m = re.match(r"\s*import\s+([\w.]+(?:\s+as\s+\w+)?(?:\s*,\s*[\w.]+(?:\s+as\s+\w+)?)*)", stmt)
        if m:
            names += [n.split()[0] for n in m.group(1).split(",")]
    return any(n and n.split(".")[0] not in _STDLIB and n.split(".")[0] not in NOT_PROJECT for n in names)


def exercises_code(probe: str, seg: Segment) -> bool:
    """A command that runs the project's own code after a fix: a script, `python -m pkg`, a snippet that imports a project
    module, `node app.js`, `./bin/tool`, `curl localhost`. Reading a file, installing a package or querying a website does not."""
    m = PY_RUN.match(probe)
    if m:
        rest = m.group("rest")
        if rest.startswith("-m "):
            mod = (rest[3:].split() or [""])[0].split(".")[0]
            return bool(mod) and mod not in _STDLIB and mod not in NOT_PROJECT
        if rest.startswith("-c"):
            c = PY_C.search(probe)
            return bool(c) and _project_imports(c.group(2))
        if seg.heredoc:
            return _project_imports(seg.text.split("\n", 1)[1] if "\n" in seg.text else "")
        script = re.match(r"([\w./~-]+\.py)\b", rest)
        return bool(script) and "site-packages" not in script.group(1)
    return bool(EXERCISE_CMD.search(probe))
SHELL_HEAD = re.compile(r"^\s*(?:\S*/)?(?:bash|sh|zsh|dash)\b[^<\n]*<<")
LOOP_HEAD = re.compile(r"^(?:\s*(?:for|select)\s+\w+\s+in\b[^;]*(?:;\s*do\b\s*|$))+")   # nested loops too


def verifying_segments(cmd: str, kinds: set, after_edit_only: bool = False):
    segs = segments(cmd)
    if after_edit_only:
        last = max((i for i, s in enumerate(segs) if segment_is_edit(s, cmd)), default=-1)
        segs = segs[last + 1:]
    out = []
    for s in segs:
        if s.heredoc and SHELL_HEAD.match(s.text):
            body = s.text.split("\n", 1)[1].rsplit("\n", 1)[0] if "\n" in s.text else ""
            out += verifying_segments(body, kinds)   # `bash <<'EOF'` runs its body
            continue
        if segment_is_edit(s, cmd) or (s.heredoc and not s.interp) or (s.heredoc and s.interp and WRITE_MARK.search(s.text)):
            continue
        probe = s.text.split("\n", 1)[0] if s.heredoc else s.text   # judge interpreter heredocs by their header line
        probe = LOOP_HEAD.sub("", probe)   # `for f in a.py check_x.py; do ...`: the word list runs nothing, the body does
        probe = re.sub(r"^(\s*\w+=\S+\s+)+", "", probe)   # strip leading VAR=value prefixes
        if not probe.strip():
            continue
        if "test" in kinds and (s.interp or INTERP_INLINE.search(probe)) and TEST_IMPORT.search(s.text) and TEST_CALL.search(s.text):
            out.append(s)   # `python -c "import test_pricing as t; t.test_x()"` runs the tests' assertions without a runner
            continue
        if "build" in kinds and import_only(probe):
            out.append(s)
            continue
        if "exercise" in kinds and exercises_code(probe, s):
            out.append(s)
            continue
        if NON_VERIFY_VERB.search(probe) and not re.search(r"gh (pr checks|run)", probe):
            continue
        if SERVER.search(probe) and not re.search(r"(pytest|test|check)", probe):
            continue
        if NOT_A_RUN.search(QUOTED_ARG.sub(" ", probe)):
            continue   # `pytest --collect-only`, `--version`: nothing was tested
        if not INTERP_INLINE.search(probe):   # `uv run python -c "..."`, `bash -c "..."`: the quoted text is what runs
            probe = QUOTED_ARG.sub(" ", probe)   # `gh pr create --title "... pytest ..."` names a test tool but runs none
        if any(VERIFY[k].search(probe) for k in kinds if k in VERIFY):
            out.append(s)
    return out


def bash_verifies(cmd: str, kinds: set, after_edit_only: bool = False) -> bool:
    return bool(verifying_segments(cmd, kinds, after_edit_only))
