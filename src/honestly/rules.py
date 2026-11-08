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
from . import shell as _sh

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
    r"((?:\d+|[一二三四五六七八九十几多])类[：:]|types? of claims?|claim (?:types|categories)|kinds? of claims?|(?:只|仅|都|全部)?保存在(?:本地|仓库|数据库|服务器|云端)|(?:is|are) (?:only |all )?(?:stored|kept) (?:in|on|locally)|\b(?:the )?(?:user|you|they|he|she|someone|the team|the maintainers?) (?:sent|said|asked|replied|pushed|deployed|saved|checked|downloaded)\b|(?:用户|你|他|她|对方|他们)(?:已经|刚|刚刚)?(?:发了|发来|发过|推了|部署了|保存了|查了|下载了)|接下来|下一步|我会|我将|我来|然后再|正在|还没|尚未|未验证|未经验证|not yet|haven'?t|hasn'?t|(?:AI|助手|智能体|模型|Claude|Codex|agent)[^。！？\n]{0,30}?(?:就说|又说|说了|声称|宣称|谎称|报告说)|\b(?:the|your|my|an?) (?:agent|AI|assistant|model)\b[^.!?\n]{0,40}?\b(?:says|said|claims|claimed|reports|reported|insists|insisted)\b|不能说|不敢说|没法说|无法(?:确认|保证|断言|说)|不能(?:确认|保证|断言)|还不能|(?:没有|没)(?:实际)?(?:运行|跑)(?:过)?(?:任何)?(?:测试|pytest|用例)(?![^。！？.!?]*(?:现在|刚才|已经|然后|随后))|can'?t (?:say|claim|confirm|promise|guarantee)|cannot (?:say|claim|confirm|guarantee)|\bunverified\b|\bnot verified\b|(?:did not|didn'?t|do not|don'?t) (?:run|execute) (?:the |any )?(?:tests?|pytest|test suite)\b(?![^.!?]*\b(?:now|then|after that|so I ran)\b)|nothing (?:is|was|has been)|\bnot \w+ yet\b|isn'?t \w+ yet|should pass|应该(能|会)|等.{0,8}(完成|渲染|通过|通知)|通知我|被标记|标记为|标记\"|syntax[- ]?check|只做了语法检查"
    r"|需要你|请你|你可以|you can|\?|？|待验证"
    r"|\b[1-9]\d* failed\b|\d+ 个?失败|but (?:now |still )?fail|但.{0,12}(报错|失败|出错|不过)"
  # honest partial results are not a pass claim
    r"|\bupstream\b|according to|\bin (?:v\d|version \d|python ?\d|node ?\d|chrome ?\d|#\d)|上游|按照?文档|文档(说|写|里)|之前已|已修复的|曾经|\b(?:pass(?:ed|es)?|green|succeeded)\s+(?:\w+\s+){0,2}?(?:earlier|previously)\b(?![^.!?]*\b(?:now|still|again|after)\b)|\b(?:earlier|previously)[, ]+(?:the |all )?(?:tests?|checks?|runs?)\b(?![^.!?]*\b(?:now|still|again|after)\b)"  # someone else fixed it, somewhere else
    r"|通过率|通过的(条件|用例|标准)|position:\s*fixed|transaction"
    r"|我也会|我还会|我再|完成后会|之后会|会出现在|默认保存|通常保存|一般保存|会保存到|核实过的|核对过的|验证过的|下载完成后|不会丢"  # future, generic behaviour, adjectives, state
    r"|意思是[:：]|\b(you|he|she|they) (said|say|wrote|claimed)\b|你说|他说|它说|审查员|reviewer (said|wrote)"  # explaining or quoting, not claiming
    r"|\bprevious(?:ly| (?:run|session|turn|attempt|time|conversation))\b(?![^.!?]*\b(?:now|still|again)\b)|yesterday|last (?:week|run|time)|only on \w+ (?:but|and)|only (?:on|in) (?:linux|mac|windows|ci)\b"  # another time or place
    r"|\[J\]|\bet al\b|\bdoi\b|\bvol\.\s*\d|\bpp\.\s*\d|\bISBN\b|\bISSN\b"  # bibliography entries
    r"|\bI'?m re-?(running|rendering|testing|checking)\b|\bto (check|verify|confirm)\b"  # says a check is still coming
    r"|(?:命令|脚本|它|这条|这个|运行后|跑完|执行后)[^，。,；;]{0,4}会(?:显示|提示|打印|输出|告诉你)|\b(?:it|this|that|the (?:command|script|tool|run|output))\s+will\s+(?:show|print|display|tell you|report)\b"  # describes what a command will do
    r"|\d[\d.,]*\s*[KMGT]i?B\s*(?:/|of)\s*\d[\d.,]*\s*[KMGT]i?B"  # a progress fraction such as 635 GB / 680 GB
    r"|\b(?:the|a|stop|honestly(?:'s)?)\s+hook\s+(?:stopped|blocked|held|caught|flagged)\s+(?:me|this|the|my|it)\b|\bhonestly\s+(?:stopped|blocked|held|caught|flagged|stepped in)\b|被\s*(?:honestly|hook|钩子|stop ?hook)\s*拦|(?:我|回复|这条回复|上一条回复)(?:刚才|之前)?被拦(?:下|截|住)?|拦(?:截|下)(?:的)?原因"
    r"|\bbecause I (?:had )?(?:said|claimed)\b|\bI (?:had )?(?:said|claimed)\b[^.!?\n]{0,80}\b(?:without|before (?:I|running|re-?checking|checking)|but (?:hadn'?t|had not|didn'?t|did not))\b)", re.I)  # explaining a block: "the hook stopped me because I said..."
# sentences that open with a progress word or an explanation ("Running the tests now.", "That means ...")
NOT_A_CLAIM_START = re.compile(r"(?:running|re-running|checking|verifying|now (?:running|re-?running|checking|verifying|testing|building|rendering|let)|next"
                               r"|(?:意思是|也就是说|换句话说|即|比如|例如|e\.g\.|i\.e\.|that means|this means|in other words|for example|meaning)\b)", re.I)
# forward-looking words only disqualify a claim when they come BEFORE it ("if tests pass" vs "tests pass, even if X")
PREFIX_NOT_CLAIM = re.compile(r"(准备|will |I'll|I’ll|we'll|next,? I|let me|going to|while |如果|\bif |一旦|\bonce |^then |直到|\buntil\b|\bbefore (?:I|we|my|the|this)\b|make sure|\bensure\b)", re.I)   # "make sure tests pass" is an instruction; "tests pass, make sure to…" still a claim
# a step written for the reader: what they will see and what it means ("跑测试，看到 12 passed 就说明环境配好了", "you should see 12 passed").
# Judged around the match: an expectation verb right before it, or "see X" right before and "就说明 / means" right after.
_ZH_GAP, _EN_GAP = r"\s*[:：]?\s*[「“\"'`]?[^，。；;:：！!？?\n]{0,8}$", r"\s*[:\"“'`]?[^.,;:!?\n]{0,24}$"   # "看到测试全部通过", "see all 12 tests pass"
READER_SEES = re.compile(r"(?:会|将|应该|应当|就能|才能)[^，。；;！!？?\n]{0,12}?(?:看到|看见|显示|打印出?|输出|出现|提示)" + _ZH_GAP +
                         r"|\b(?:you|they|it|this|that|the (?:output|terminal|console|page|screen|command|script|run))(?:'ll|’ll| will| should| would)\s+"
                         r"(?:see|get|notice|print|show|display|output|say)\b" + _EN_GAP + r"|\bwhen (?:you|they) (?:see|get)\b", re.I)
SEE_BEFORE = re.compile(r"(?:看到|看见)(?!了)" + _ZH_GAP + r"|\bseeing\b" + _EN_GAP, re.I)   # the reader sees; "输出 12 passed，就说明…" is the agent's output
MEANS_AFTER = re.compile(r"^\s*[」”\"'`]?\s*(?:的话|[，,]?\s*(?:就|即|便|则|才)(?:说明|代表|表示|意味着|证明|是|行|算|可|好|对|成功|没问题|完成|OK\b))"
                         r"|^\s*[\"”'`]?\s*(?:means|tells you|shows|confirms|indicates)\b", re.I)
OWN_RUN = re.compile(r"(?:我|我们)(?:刚才|刚刚|已经|已|也|又|再|先)?(?:跑|运行|执行|测|试|看到|看了)|(?:刚才|刚刚|刚)(?:跑|运行|执行|测)|(?:跑|运行|执行|测试)(?:了|过)|看到了"
                     r"|\bI (?:ran|re-?ran|saw|got|just|have)\b|\bI'?ve\b|\bwe (?:ran|saw|got)\b|\bran\b", re.I)   # the agent's own run: still a claim


def _reader_step(sent: str, start: int, end: int) -> bool:
    if OWN_RUN.search(sent):
        return False
    before = sent[:start]
    return bool(READER_SEES.search(before) or (SEE_BEFORE.search(before) and MEANS_AFTER.search(sent[end:])))


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
        if len(sent) > 400 or NOT_A_CLAIM.search(sent) or NOT_A_CLAIM_START.match(sent):
            continue
        low = sent.lower()
        if any(p in low for p in IGNORE_PHRASES):
            continue
        for name, pat, kinds in CLAIM_PATTERNS:
            if name in DISABLED:
                continue
            m = pat.search(sent)
            if m and not _inside_quotes(sent, m.start(), m.end()) and not _inside_link(sent, m.start(), m.end()) and not PREFIX_NOT_CLAIM.search(sent[:m.start()]) \
                    and not _reader_step(sent, m.start(), m.end()):
                hits.append(ClaimHit(name, sent, kinds))
                break
    return hits


# ------------------------------------------------------------ edits & paths
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
DOC_EXT = {".md", ".txt", ".rst", ".csv", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".mp4", ".mp3", ".wav", ".srt", ".log", ".example", ".b64", ".jsonl", ".mdc"}
# source files whatever folder they sit in; a program's output sent to one of these is code too (`python gen.py > src/gen.py`)
SOURCE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".sh", ".zsh", ".bash", ".go", ".rs", ".java", ".kt", ".swift", ".c", ".cc", ".cpp", ".h", ".hpp", ".rb", ".php", ".vue", ".svelte", ".pl", ".lua"}
CODE_TXT = re.compile(r"(?:^|/)(?:CMakeLists\.txt|(?:[\w.-]*[-_.])?(?:requirements|constraints)(?:[-_.][\w.-]*)?\.(?:txt|in)|requirements/[^/]+\.(?:txt|in))$", re.I)   # code in a .txt
# directories and file names that hold notes rather than code; anchored, so `src/prompts/builder.py` or `proj/tmp/app.py` stay code
DOC_DIRS = re.compile(
    r"(^docs?/|/docs?/|/memory/|/scratchpad/|/(?:reports?|notes?|research_notes)/[^/]*\.(?:md|txt|rst|csv|json|html|pdf)$|/\.claude/projects/"
    r"|(?:^|/)(?:README|CHANGELOG|HANDOFF|PROMPTS?)(?:[^/]*\.(?:md|txt|rst))?$|(?:^|/)(?:AGENTS|CLAUDE|GEMINI)\.md$|(?:^|/)\.env(?:\.[\w.-]+)?$|(?:^|/)\.gitignore$|(?:^|/)\.gitattributes$|(?:^|/)\.git/|(?:^|/)\.\w+ignore$|(?:^|/)LICENSE[^/]*$"
    r"|(?:^|/)(?:data|datasets|live|runs|outputs?|results|logs|cache)/(?:[^/]+/)*[^/]+\.(?:json|csv|tsv|parquet|xml)$"   # data and state files a script writes, not code
    r"|side-session-notes|Application Support/Claude|(^|/)\.agent/|(^|/)\.(?:claude|vscode|idea)/|state\.json$|progress\.md|日志|复盘|方案|笔记|文案|计划|清单|情报|记录|台账"
    r"|^/tmp/|^/private/tmp/|^/var/tmp/|^/dev/shm/|^/var/folders/|AppData/Local/Temp/|/Temp/claude)", re.I)
ALWAYS_SCRATCH = re.compile(r"/scratchpad/|/\.claude/projects/|^/tmp/|^/private/tmp/|^/var/tmp/|^/dev/shm/|^/var/folders/|AppData/Local/Temp/|/Temp/claude|^[A-Za-z]:/(?:Temp|tmp)/", re.I)
TMP_CWD = re.compile(r"(^|\s)cd (?:(?:/private)?/tmp(?:/|$)|\S*scratchpad(?:/|$))")
INTERP_HEADS = re.compile(r"^(?:python[\d.]*|pypy[\d.]*|node|bun|deno|bash|zsh|sh|dash|ruby|perl|php|psql|sqlite3)$")
_CODE_HEADS = re.compile(r"^(?:python[\d.]*|pypy[\d.]*|node|bun|deno|ruby|perl|php)$")
WRITE_MARK = re.compile(r"(write_text\(|write_bytes\(|open\([^)]*['\"](?:[wax][bt]?\+?|r[bt]?\+[bt]?)['\"]|\.write\(|writeFileSync|appendFileSync|copyFileSync|renameSync|unlinkSync|rmSync|fs\.write|fs\.append|fs\.copy|fs\.rename|fs\.unlink|fs\.rm\b|fs\.promises"
                        r"|shutil\.(?:copy\w*|move|rmtree)|os\.(?:rename|renames|replace|remove|unlink|rmdir|removedirs)\b|Path\([^)]*\)[\w./()'\"]*\.(?:touch|unlink|rename|replace|rmdir)\(|\.touch\(|\.unlink\(|\.rename\(\s*(?:['\"]|Path\()"
                        r"|fileinput\.[^\n]*inplace\s*=\s*(?:True|1)|Bun\.write|Deno\.(?:writeTextFile|writeFile|remove|rename|copyFile)|File\.(?:write|delete|rename)|FileUtils\.|IO\.write|file_put_contents|fopen\([^)]*['\"][wax]"
                        r"|open\s*\(?[^;\n]*['\"]\+?>{1,2}['\"]|\bunlink\b\s*\(?\s*['\"\$])")
_NOT_A_FILE_WRITE = re.compile(r"(?:\bsys\.(?:stdout|stderr)(?:\.buffer)?|\bprocess\.(?:stdout|stderr)|\bconsole|\b(?:response|res|self\.wfile|sock|socket|conn|writer|hasher|hash|digest|md5|sha\d*))\.write\(")
_MEMORY_FILE = re.compile(r"(\w+)\s*=\s*(?:io\.)?(?:StringIO|BytesIO)\(")
QUOTED_PATH = re.compile(r"['\"]([^'\"\n]+\.(?:py|js|mjs|cjs|ts|tsx|jsx|html|css|scss|json|toml|yaml|yml|sh|zsh|go|rs|java|kt|swift|c|cc|cpp|h|rb|php|sql|tex|ipynb|vue|svelte|glsl|cfg|ini|md|txt|rst|csv|log|jsonl))['\"]")
HEADER_PATH = re.compile(r"(?:^|\s)\"?((?:~|/|\.{1,2}/)?[\w./~\-\u4e00-\u9fff]+/[\w.\-\u4e00-\u9fff]+\.[A-Za-z0-9]{1,5})\"?")
COMMIT_MSG = re.compile(r"(-m\s+(\"[^\"]*\"|'[^']*')|<[^<>\s]+@[^<>\s]+>)")
PIPEFAIL_ON = re.compile(r"\bset\b[^;&|\n]{0,80}?\s-[a-zA-Z]*o[a-zA-Z]*\s+pipefail\b|\b(?:ba|z|k|da)?sh\s+(?:-\S+\s+){0,8}-[a-zA-Z]*o\s+pipefail\b|\bsetopt\s+pipe_?fail\b|\bshopt\b[^;&|\n]{0,20}?\s-[a-z]*o[a-z]*\b[^;&|\n]{0,20}?\bpipefail\b", re.I)
PIPEFAIL_OFF = re.compile(r"\bset\s+\+o\s+pipefail\b|\bunsetopt\s+pipe_?fail\b", re.I)
NOT_A_RUN = re.compile(r"(?:^|\s)(?:--collect-only|--co|--version|--help|-h|--list-tests|--listTests|--list|--dry-run|--showconfig|--showConfig|--show-config|--fixtures|--fixtures-per-test|--markers|--no-run|-list|--setup-only|--setup-plan|--cache-show|--init|--print-config|--install-types|--watch|--watchAll)(?=[\s=]|$)|\bmake\b[^|;&\n]*\s(?:-n|--just-print)\b")
_V_IS_VERSION = re.compile(r"^(?:pytest|py\.test|tsc|mvn|mvnw|gradle|gradlew|node|deno|bun|go|cargo|rustc|ruff|mypy|black|eslint|prettier|biome|tox|nox|jest|vitest|mocha|rspec)$")
NOTE = None   # set by hooks: where "could not check" is written down


def _note_once(where: str, msg: str) -> None:
    if NOTE is not None:
        NOTE(where, msg)


def pipe_stages(text: str) -> list:
    """`a | b |& c` -> ["a ", " b ", " c"]; `||` is a list operator, not a pipe."""
    return re.split(r"(?<!\|)\|&?(?!\|)", text)


def path_is_doc(path: str) -> bool:
    if not path:
        return False
    path = path.replace("\\", "/").strip()   # Claude Code on Windows writes native paths
    if ALWAYS_SCRATCH.search(path):
        return True
    if CODE_TXT.search(path) or re.search(r"(?:^|/)\.git/hooks/", path):
        return False
    ext = os.path.splitext(path)[1].lower()
    if ext in SOURCE_EXT or ext == ".sql":
        return bool(re.search(r"(?:^|/)\.git/", path))   # source code is code in `src/memory/`, `src/docs/` or `src/计划/`
    return ext in DOC_EXT or bool(DOC_DIRS.search(path))


@dataclass
class Segment:
    text: str
    heredoc: bool = False
    interp: bool = False   # heredoc fed to an interpreter (code), else data
    unit: object = None    # the pipeline as read by shell.py


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


def _as_segment(u) -> Segment:
    docs = [c for c in u.pipeline.commands if c.heredocs]
    interp = False
    if docs:
        real = _sh.unwrap(docs[0].argv)
        interp = bool(real and INTERP_HEADS.match(_sh.head_name(real[0])))
    return Segment(u.text, bool(docs), interp, u)


def _units(cmd) -> tuple:
    return _sh.units(cmd) if isinstance(cmd, str) else ()


def segments(cmd: str):
    """The pipelines of a shell command, in the order they run, with loops and conditionals opened up. A heredoc block stays with its command."""
    return [_as_segment(u) for u in _units(cmd) if u.level == 0]


CODE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".css", ".scss", ".json", ".toml", ".yaml", ".yml", ".sh", ".zsh", ".go", ".rs", ".java", ".kt", ".swift", ".c", ".cc", ".cpp", ".h", ".rb", ".php", ".sql", ".tex", ".ipynb", ".vue", ".svelte", ".glsl", ".txt.j2", ".cfg", ".ini"}


@functools.lru_cache(maxsize=512)
def shell_env(cmd: str) -> dict:
    """`VAR=value` assignments of the shell part of a command, `export VAR=value` too; a heredoc body is another language (`S=sys.argv[1]`)."""
    env = {}
    for u in _units(cmd):
        env.update(u.env)
    return env


def _resolve_vars(text: str, whole_cmd: str) -> str:
    return _sh.resolve(text, shell_env(whole_cmd))


# ------------------------------------------------------------ what a command writes
_AUTHORS = {"cat", "echo", "printf", "sed", "gsed", "awk", "gawk", "perl", "jq", "cp", "mv", "tee", "print", "Write-Output", "Set-Content"}
_SCRATCH_NAMES = {"out", "output", "status", "log", "result", "results", "tmp", "temp", "stdout", "stderr", "foo", "bar", "baz", "a", "b", "c", "x", "y", "z"}
_SCRATCH_EXT = {".out", ".stamp", ".tmp", ".bak", ".orig", ".rej", ".pid", ".lock"}
_TEMP_VAR = re.compile(r"^\$\{?(?:TMPDIR|TMP|TEMP|RUNNER_TEMP|TEMPDIR)\b|^\$\(mktemp\b|^`mktemp\b")
_KNOWN_SOURCE_DIRS = {"src", "lib", "app", "tests", "test", "pkg", "cmd", "internal"}
_GIT_FLAGS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}


def _positional(args: list, values: set = frozenset()) -> list:
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            out += args[i + 1:]
            break
        if a.startswith("-") and a != "-":
            i += 2 if a in values else 1
            continue
        out.append(a)
        i += 1
    return out


def _git_args(real: list) -> list:
    """`git -C x --no-pager status` -> ["status"]."""
    i = 1
    while i < len(real) and real[i].startswith("-"):
        i += 2 if real[i] in _GIT_FLAGS_WITH_VALUE else 1
    return real[i:]


def _git_writes(real: list):
    a = _git_args(real)
    if not a:
        return None
    sub, rest = a[0], a[1:]
    has = lambda *f: any(x in f for x in rest)
    if has("--help", "-h"):
        return None
    if sub == "checkout":
        if has("-b", "-B", "--orphan"):
            return None
        if "--" in rest:
            return rest[rest.index("--") + 1:] or [None]
        return [None]
    if sub == "restore":
        if has("--staged", "-S") and not has("--worktree", "-W"):
            return None
        return _positional(rest, {"--source", "-s", "--pathspec-from-file"}) or [None]
    if sub == "switch":
        return None if has("-c", "-C", "--create", "--force-create") else [None]
    if sub == "merge":
        return None if has("--abort", "--quit") else [None]
    if sub == "pull":
        return None if has("--dry-run") else [None]
    if sub == "rebase":
        return None if has("--abort", "--quit", "--show-current-patch", "--edit-todo") else [None]
    if sub in ("cherry-pick", "revert"):
        return None if has("--abort", "--quit") else [None]
    if sub == "am":
        return None if has("--abort", "--quit", "--show-current-patch") else [None]
    if sub == "apply":
        return None if has("--check", "--stat", "--numstat", "--summary", "--cached") else [None]
    if sub == "stash":
        return [None] if not rest or rest[0] in ("push", "save", "pop", "apply") or rest[0].startswith("-") else None
    if sub == "mv":
        p = _positional(rest)
        return p or [None]
    if sub == "rm":
        return None if has("--cached", "-n", "--dry-run") else (_positional(rest) or [None])
    if sub == "reset":
        return [None] if has("--hard") else None
    if sub == "clean":
        flags = "".join(x[1:] for x in rest if x.startswith("-") and not x.startswith("--"))
        return [None] if "f" in flags and "n" not in flags else None
    return None


def _sed_writes(real: list):
    args, files, script, i = real[1:], [], False, 0
    inplace = False
    while i < len(args):
        a = args[i]
        if a in ("--help", "--version"):
            return None
        if a == "--":
            files += args[i + 1:]
            break
        if a.startswith("--"):
            inplace = inplace or a.startswith("--in-place")
            if a in ("--expression", "--file"):
                script = True
                i += 1
            elif a.startswith(("--expression=", "--file=")):
                script = True
            i += 1
            continue
        if a.startswith("-") and len(a) > 1:
            letters = a[1:]
            if letters[0] == "i" or re.fullmatch(r"[Enrsuz]*i[a-zA-Z.]*", letters):
                inplace = True
                if letters == "i" and i + 1 < len(args) and args[i + 1] == "":   # BSD: `-i ''`
                    i += 1
            elif letters[-1] in "ef":
                script = True
                i += 1
            i += 1
            continue
        if not script:
            script = True
        else:
            files.append(a)
        i += 1
    return (files or [None]) if inplace else None


def _perl_writes(real: list):
    args, files, i, inplace, script = real[1:], [], 0, False, False
    while i < len(args):
        a = args[i]
        if a.startswith("-") and len(a) > 1 and not a.startswith("--"):
            letters = a[1:]
            if re.match(r"[a-zA-Z0-9]*i", letters) and "e" not in letters.split("i")[0]:
                inplace = True
            if "e" in letters.split(".")[0]:
                script = True
                i += 1
            i += 1
            continue
        if not script:
            script = True
        else:
            files.append(a)
        i += 1
    return (files or [None]) if inplace else None


def _dest_writes(h: str, args: list):
    """cp, mv, install, ln, rsync: the destination; a move takes its sources away too."""
    t = None
    pos, i = [], 0
    while i < len(args):
        a = args[i]
        if a in ("-t", "--target-directory"):
            t = args[i + 1] if i + 1 < len(args) else None
            i += 2
            continue
        if a in ("-m", "--mode", "-o", "--owner", "-g", "--group", "-S", "--suffix"):
            i += 2
            continue
        if a.startswith("-") and a != "-":
            i += 1
            continue
        pos.append(a)
        i += 1
    if t is None and len(pos) < 2:
        return None
    sources, dest = (pos, t) if t is not None else (pos[:-1], pos[-1])
    out = []
    if os.path.splitext(dest)[1] or (not dest.endswith("/") and dest not in (".", "..") and not all(os.path.splitext(s)[1] for s in sources)):
        out.append(dest)
    elif dest in (".", "./"):
        out += [os.path.basename(s) for s in sources]
    else:
        out += [dest.rstrip("/") + "/" + os.path.basename(s.rstrip("/")) for s in sources]
    if h == "mv":
        out += sources
    return out


_PKG_ADD = {"npm": {"install", "i", "add", "uninstall", "un", "rm", "remove", "update", "up"}, "pnpm": {"add", "remove", "rm", "update", "up", "install", "i"}, "yarn": {"add", "remove", "upgrade", "up"}, "bun": {"add", "remove", "rm", "update", "install", "i"},
            "uv": {"add", "remove"}, "poetry": {"add", "remove"}, "pdm": {"add", "remove"}, "cargo": {"add", "remove", "rm"}, "bundle": {"add", "remove"}, "composer": {"require", "remove"}, "pipenv": {"install", "uninstall"}, "go": {"get"}, "rye": {"add", "remove"}}
_PKG_NEEDS_NAME = {"npm", "pnpm", "bun", "pipenv"}


def _verb_writes(real: list, c):
    """The files this command changes by itself. None: it changes nothing. A None inside the list: something changes, but the text does not say what."""
    h = _sh.head_name(real[0])
    args = real[1:]
    low = h.lower()
    if low == "git":
        return _git_writes(real)
    if low in ("sed", "gsed"):
        return _sed_writes(real)
    if low in ("perl", "ruby"):
        return _perl_writes(real)
    if low in ("awk", "gawk"):
        for i, a in enumerate(args):
            if (a == "-i" and args[i + 1:i + 2] == ["inplace"]) or a in ("--include=inplace", "-iinplace"):
                return [x for x in _positional(args[i + 2:])[1:]] or [None]
        return None
    if low == "tee":
        return [a for a in _positional(args) if a]
    if low == "patch":
        if any(a in ("--dry-run", "-C", "--check", "--version", "--help", "-v") for a in args):
            return None
        return [None]
    if low in ("ed", "ex", "vi", "vim", "nvim", "red"):
        cmds = [args[i + 1] for i, a in enumerate(args[:-1]) if a == "-c" or (a.startswith("-") and a.endswith("c") and not a.startswith("--"))]
        batch = low in ("ed", "red") or any(a in ("-e", "-es", "-s", "-E", "-Es", "--headless", "-sc", "-esc", "-ec") or a.startswith("-s") for a in args)
        if not batch or not (low in ("ed", "red") or any(re.search(r"\b(?:w|wq|x|wa|xa|update)\b|\|x$", x) for x in cmds)):
            return None
        return [a for a in _positional(args, {"-c", "-sc", "-ec", "-esc"}) if a not in cmds] or [None]
    if low in ("cp", "mv", "install", "ln", "rsync", "ditto", "gcp", "gmv"):
        return _dest_writes(low, args)
    if low in ("rm", "unlink", "shred", "trash", "grm"):
        out = []
        for a in _positional(args):
            ext = os.path.splitext(a.rstrip("/"))[1].lower()
            if ext in CODE_EXT or os.path.basename(a.rstrip("/")) in _KNOWN_SOURCE_DIRS:
                out.append(a)
        return out or None
    if low == "dd":
        return [a[3:] for a in args if a.startswith("of=")] or None
    if low in ("truncate", "gtruncate"):
        return _positional(args, {"-s", "--size", "-r", "--reference"}) or None
    if low == "find" and "-delete" in args:
        for i, a in enumerate(args[:-1]):
            if a in ("-name", "-iname") and os.path.splitext(args[i + 1])[1].lower() in CODE_EXT:
                return [args[i + 1]]
        return None
    # fixers rewrite code; formatters keep its meaning by contract and do not count
    fix = None
    if low == "ruff" or low == "eslint":
        fix = any(a in ("--fix", "--unsafe-fixes", "--fix-only") for a in args)
    elif low == "biome":
        fix = any(a in ("--write", "--apply", "--fix") for a in args) and args[:1] != ["format"]
    elif low == "cargo" or low == "go":
        fix = args[:1] == ["fix"]
    elif low == "2to3":
        fix = "-w" in args or "--write" in args
    elif low == "comby":
        fix = any(a in ("-in-place", "-i") for a in args)
    elif low == "autoflake":
        fix = any(a in ("-i", "--in-place") for a in args)
    elif low in ("pyupgrade", "jscodeshift", "codemod", "sd", "ast-grep-rewrite", "semgrep-fix"):
        fix = bool(args)
    if fix:
        return [None]
    if low in _PKG_ADD and args and args[0] in _PKG_ADD[low]:
        if low in _PKG_NEEDS_NAME and not _positional(args[1:], {"-w", "--workspace", "--prefix", "-C", "--filter", "-F"}):
            return None
        return [None]
    if low == "npm" and args[:1] == ["version"]:
        return None
    return None


def _code_of(real: list, c):
    """(language, code) when the command gives an interpreter code to run: `python -c`, `node -e`, `python3 - <<EOF`."""
    h = _sh.head_name(real[0])
    if not _CODE_HEADS.match(h):
        return None
    lang = re.sub(r"[\d.]+$", "", h)
    args = real[1:]
    if lang == "deno" and args[:1] == ["eval"]:
        return "js", " ".join(args[1:])
    if lang == "bun" and args[:1] == ["run"]:
        args = args[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if lang in ("python", "pypy") and a in ("-W", "-X"):
            i += 2
            continue
        if a == "-":
            break
        if not a.startswith("-"):
            return None     # a script file; a heredoc is its input, not code
        if lang in ("python", "pypy") and a.lstrip("-").endswith("c") and not a.startswith("--") and i + 1 < len(args):
            return "python", args[i + 1]
        if lang == "python" and a.lstrip("-").endswith("m"):
            return None
        if lang in ("node", "bun") and a in ("-e", "--eval", "-p", "--print") and i + 1 < len(args):
            return "js", args[i + 1]
        if lang in ("ruby", "perl") and "e" in a[1:] and i + 1 < len(args):
            return lang, args[i + 1]
        if lang == "php" and a == "-r" and i + 1 < len(args):
            return "php", args[i + 1]
        i += 1
    if c is not None and c.heredocs:
        return ("js" if lang in ("node", "bun", "deno") else lang), "\n".join(h2.body for h2 in c.heredocs)
    return None


_STRING = re.compile(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`(?:[^`\\]|\\.)*`')
_MODE_TEXT = re.compile(r"^(?:[rwax]?[bt]?\+?[bt]?|\+?[<>]{1,2}|)$")


def _blank_strings(code: str) -> str:
    """Words inside string literals are not code; open modes and Perl's `'>'` stay, so a write can still be seen."""
    def rep(m):
        s = m.group(0)
        q = s[0]
        inner = s[1:-1]
        return s if _MODE_TEXT.match(inner) and len(s) < 8 else q + "_" * min(len(inner), 8) + q
    return _STRING.sub(rep, code[:200_000])


def _code_marks_a_write(code: str) -> bool:
    bare = _blank_strings(code)
    if not WRITE_MARK.search(bare):
        return False
    memory = set(_MEMORY_FILE.findall(bare))
    rest = _NOT_A_FILE_WRITE.sub("", bare)
    for name in memory:
        rest = re.sub(r"\b" + re.escape(name) + r"\.write\(", "", rest)
    return bool(WRITE_MARK.search(rest))


_SHELL_OUT_LIST = re.compile(r"(?:subprocess\.\w+|Popen|check_call|check_output|spawnSync|spawn|execFileSync)\(\s*(?:\[([^\]]{0,600})\]|['\"]([\w./-]+)['\"]\s*,\s*\[([^\]]{0,600})\])")
_SHELL_OUT_TEXT = re.compile(r"(?:os\.system|os\.popen|subprocess\.\w+|execSync|shell_exec|system)\(\s*(['\"])((?:(?!\1).){1,600})\1")
_LIST_ITEM = re.compile(r"sys\.executable|process\.execPath|'([^']*)'|\"([^\"]*)\"")


def _code_shell_lines(code: str) -> list:
    """Shell commands a script spells out: `subprocess.run(['sed', '-i', ...])`, `os.system('pytest')`."""
    code = code[:200_000]
    out = [m.group(2) for m in _SHELL_OUT_TEXT.finditer(code)]
    for m in _SHELL_OUT_LIST.finditer(code):
        items = []
        if m.group(2):
            items.append(m.group(2))
        for it in _LIST_ITEM.finditer(m.group(1) or m.group(3) or ""):
            items.append("python" if it.group(0).startswith(("sys.", "process.")) else (it.group(1) if it.group(1) is not None else it.group(2)))
        if items:
            out.append(shlex.join(items))
    return out[:32]


TEMP_PATH = re.compile(r"^(?:/private/tmp/|/tmp/|/var/tmp/|/dev/shm/|/var/folders/)|(?:^|/)scratchpad(?:/|$)|AppData/Local/Temp|/Temp/claude|^\$\{?TMPDIR|^[A-Za-z]:[\\/](?:Temp|tmp)[\\/]")
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
    if re.match(r"^tempfile\.|^(?:Named)?TemporaryFile\b|^mkdtemp\b|^mkstemp\b", expr):
        return "/tmp/tempfile"
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
_OTHER_WRITE = re.compile(r"os\.(?:remove|unlink|rmdir|removedirs)\b|shutil\.rmtree|\.unlink\(|\.rename\(|fileinput\.|appendFileSync|copyFileSync|renameSync|unlinkSync|rmSync|fs\.(?:append|copy|rename|unlink|rm)\b|Bun\.write|Deno\.|File\.|FileUtils\.|IO\.write|file_put_contents|fopen\(|\bunlink\b|\bopen\s*\(?\s*my\b|\bopen\s*\(?[^;\n]*['\"]\+?>")


def _write_paths(code: str, whole_cmd: str, argv: list) -> list:
    """Every write target the script names, resolved as far as the text allows; None for one it does not."""
    env = shell_env(whole_cmd) if whole_cmd else {}
    out = []
    for n, m in enumerate(WRITE_ARG.finditer(code)):
        if n >= 200:
            return [None]
        expr = next(g for g in m.groups() if g)
        path = _expr_path(expr, code, argv)
        if path is not None and TEMP_PATH.search(path):
            out.append(path)
            continue
        lits = QUOTED_PATH.findall(expr)
        if lits:   # `os.path.join(base, 'report.md')`: the file's name decides what it is
            path = lits[-1] if path is None or path == lits[-1] else path.rstrip("/") + "/" + lits[-1]
        out.append(None if path is None else _sh.expanduser(_sh.resolve(path, env)))
    return out


def writes_only_scratch(seg: Segment, whole_cmd: str = "") -> bool:
    """An interpreter heredoc whose every write goes to a temp or scratch path (a test harness, a probe page) authors no code.
    Any write it cannot follow (an unresolved variable, a mode in a variable) makes it an edit."""
    head, _, code = seg.text.partition("\n")
    return _code_only_scratch(code or seg.text, head, seg, whole_cmd)


def _code_only_scratch(code: str, head: str, seg, whole_cmd: str) -> bool:
    bare = _blank_strings(code)
    if UNTRACKED_WRITE.search(bare) or _OTHER_WRITE.search(_NOT_A_FILE_WRITE.sub("", bare)):
        return False
    try:
        toks = shlex.split(head.split("<<", 1)[0])
    except ValueError:
        toks = head.split("<<", 1)[0].split()
    env = shell_env(whole_cmd) if whole_cmd else {}
    argv = [_sh.resolve(t, env) for t in (toks[toks.index("-") + 1:] if "-" in toks else [])]
    targets = _write_paths(code, whole_cmd, argv)
    if not targets or None in targets:
        return False
    targets = _under_cd(targets, seg, whole_cmd)
    return all(TEMP_PATH.search(t) or path_is_doc(t) for t in targets)


def _under_cd(paths: list, seg: Segment, whole_cmd: str) -> list:
    """Relative paths placed under the `cd` before the segment: `cd proj/.claude && python3 - <<EOF ... open('launch.json', 'w')`
    writes proj/.claude/launch.json, which is tool config, not `launch.json` of unknown kind."""
    if not whole_cmd or all(not p or os.path.isabs(_sh.expanduser(p)) for p in paths):
        return paths
    here = seg_dir(whole_cmd, seg.text)
    if not here:
        return paths
    return [p if not p or os.path.isabs(_sh.expanduser(p)) else os.path.join(here, p) for p in paths]


PS_WRITE = re.compile(r"(?:^|[|{])[ \t]*(?:set-content|add-content|out-file)\b([^|;}\n]*)", re.I)   # PowerShell's `cat > file`
PS_WRITE_SOURCE = re.compile(r"""["'$(@]|get-content\b|gc\b|echo\b|write-output\b|if\b""", re.I)
PS_FILE_WRITE = re.compile(r"""\[(?:System\.)?IO\.File\]::(?:WriteAll(?:Text|Lines|Bytes)|AppendAll(?:Text|Lines))\([ \t]*["']([^"']+)["']""", re.I)   # [IO.File]::WriteAllText("src/app.py", ...)   # what is piped in was authored here, unlike `pytest | Out-File log.txt`
PS_PATH_PARAM = re.compile(r"-(?:file)?path|-literalpath|-pspath", re.I)
PS_VALUE_PARAM = re.compile(r"-(?:value|encoding|width|inputobject|stream|filter|include|exclude|credential)", re.I)
_QUOTE_SPAN = re.compile(r"\"[^\"\\]*(?:\\.[^\"\\]*)*\"|'[^']*'")


def _ps_write_target(args: str) -> str:
    """The file a Set-Content / Add-Content / Out-File writes: -Path's value, or the first argument that is not a parameter."""
    toks = re.findall(r"\"[^\"]*\"|'[^']*'|\S+", args)
    for t, nxt in zip(toks, toks[1:] + [""]):
        if PS_PATH_PARAM.fullmatch(t):
            return nxt.strip("\"'")
    skip = False
    for t in toks:
        if skip:
            skip = False
        elif t.startswith("-"):
            skip = bool(PS_VALUE_PARAM.fullmatch(t))
        else:
            return t.strip("\"'")
    return ""


def _target_counts(t, authored: bool, u, whole_cmd: str = "") -> bool:
    """Does writing to this target change code? A target the text cannot name counts when the verb itself changes code."""
    if t is None:
        return True
    env = dict(shell_env(whole_cmd)) if whole_cmd else {}
    if u is not None:
        env.update(u.env)
    t = _sh.resolve(t, env).strip()
    if not t or t.startswith("/dev/") or t.lower() in _sh.DEV_NULL:
        return False
    if "$" in t or "`" in t:
        if _TEMP_VAR.match(t):
            return False
        tail = re.split(r"[$`)}]", t)[-1].lstrip("/")
        ext = os.path.splitext(tail)[1].lower()
        return (ext in SOURCE_EXT if not authored else ext in CODE_EXT) and not path_is_doc(tail)   # `$PWD/src/app.py` is code; a bare `$OUT` says nothing
    cwd = u.cwd if u is not None else ""
    path = t
    if cwd and not t.startswith(("/", "~")) and not re.match(r"[A-Za-z]:[\\/]", t):
        path = os.path.join(cwd, t)
    path = _sh.expanduser(path)
    if cwd and TMP_CWD.search("cd " + cwd):
        return False
    if path_is_doc(path):
        return False
    base = os.path.basename(t.rstrip("/"))
    ext = os.path.splitext(base)[1].lower()
    if not authored:
        return ext in SOURCE_EXT
    if ext in _SCRATCH_EXT or (not ext and "/" not in t and base in _SCRATCH_NAMES):
        return False
    return True


def _stage_authored(p) -> bool:
    """Does what this stage writes come from the agent (`echo`, `cat <<EOF`, a quoted literal), rather than from a program's output?"""
    first = p.commands[0]
    if first.kind != "simple":
        return True
    if first.heredocs or not first.words:
        return True
    w = first.words[0]
    if w.quoted and len(first.words) == 1:
        return True     # PowerShell: `"x = 1" > src/app.py`
    if w.raw.startswith("@"):
        return True
    return _sh.head_name(w.text) in _AUTHORS


def _unit_writes(u, whole_cmd: str = "") -> list:
    """(target, authored) pairs for what this pipeline writes by itself."""
    out = []
    p = u.pipeline
    for c in p.commands:
        if c.kind != "simple":
            continue
        authored = _stage_authored(p)
        for r in c.redirects:
            if r.op in (">", ">>", ">|", "&>", "&>>", "<>") or (r.op == ">&" and not re.fullmatch(r"\d+|-", r.target)):
                out.append((r.target, authored if not (c.words and _sh.head_name(c.words[0].text) == "git") else False))
        if not c.words:
            continue
        real = _sh.unwrap(c.argv)
        if not real:
            continue
        verb = _verb_writes(real, c)
        if verb:
            h = _sh.head_name(real[0]).lower()
            out += [(t, authored if h == "tee" else True) for t in verb]
    for r in u.outer:
        if r.op in (">", ">>", ">|", "&>", "&>>", "<>"):
            out.append((r.target, True))
    return out


def _unit_code(u):
    """The code an interpreter stage of this pipeline runs, as (language, code, command)."""
    for c in u.pipeline.commands:
        if c.kind == "simple" and c.words:
            real = _sh.unwrap(c.argv)
            if real:
                code = _code_of(real, c)
                if code:
                    return code[0], code[1], c
    return None


def _unit_is_edit(u, whole_cmd: str = "") -> bool:
    if u.guard == "no":
        return False
    text = u.text
    io = PS_FILE_WRITE.search(text)
    if io:
        return not path_is_doc(io.group(1).replace("\\", "/"))
    bare = _QUOTE_SPAN.sub(lambda q: q.group(0)[0] + "x" * (len(q.group(0)) - 2) + q.group(0)[-1], text) if "-" in text and re.search(r"content|out-file", text, re.I) else text
    ps = PS_WRITE.search(bare)
    if ps:
        target, source = _ps_write_target(text[ps.start(1):ps.end(1)]), text[:ps.start()]
        if not target or target.startswith("$") or (source.strip() and not PS_WRITE_SOURCE.match(source.lstrip())):
            return False   # no known target (`$env:TEMP\\x`), or a program's output
        return not all(path_is_doc(t) for t in _under_cd([target.replace("\\", "/")], Segment(text, unit=u), whole_cmd))
    if any(_target_counts(t, authored, u, whole_cmd) for t, authored in _unit_writes(u, whole_cmd)):
        return True
    code = _unit_code(u)
    if code and _code_is_edit(code[1], u, whole_cmd):
        return True
    return False


def _code_is_edit(code: str, u, whole_cmd: str) -> bool:
    if _code_marks_a_write(code):
        head = u.text.split("\n", 1)[0]
        if not _code_only_scratch(code, head, Segment(u.text, unit=u), whole_cmd):
            return True
    return any(bash_is_edit(line) for line in _code_shell_lines(code))


def segment_targets(seg: Segment, whole_cmd: str = ""):
    u = seg.unit if seg.unit is not None else _first_unit(seg.text)
    code = _unit_code(u) if u is not None else None
    if seg.heredoc and seg.interp or code:
        body = code[1] if code else seg.text
        header = _resolve_vars(seg.text.split("\n", 1)[0], whole_cmd)
        hpaths = [h for h in HEADER_PATH.findall(header) if "<<" not in h]
        paths = QUOTED_PATH.findall(body)
        if hpaths and ("sys.argv" in body or not paths):
            paths = hpaths + paths
        written = [t for t in _write_paths(body, whole_cmd, hpaths) if t]
        if written:
            coded = [t for t in written if not path_is_doc(t)]
            return coded or written
        coded = [t for t in paths if os.path.splitext(t)[1].lower() in CODE_EXT and not path_is_doc(t)]
        docs = [t for t in paths if path_is_doc(t)]
        if docs and not coded:
            return docs
        return coded or paths
    if u is None:
        return []
    out = []
    for t, _ in _unit_writes(u, whole_cmd):
        if t and not t.startswith("/dev/") and t.lower() not in _sh.DEV_NULL:
            out.append(_sh.resolve(t, shell_env(whole_cmd) if whole_cmd else {}))
    return out


def _first_unit(text: str):
    us = _units(text)
    return us[0] if us else None


def segment_is_edit(seg: Segment, whole_cmd: str = "") -> bool:
    u = seg.unit if seg.unit is not None else _first_unit(seg.text)
    if u is None:
        return False
    if _unit_is_edit(u, whole_cmd):
        return True
    body = _shell_text_of(u)   # `bash <<EOF` and `bash -c`: what runs inside decides
    return bool(body) and bash_is_edit(body)


def _shell_text_of(u) -> str:
    for k, c in enumerate(u.pipeline.commands):
        if c.kind == "simple" and c.words:
            real = _sh.unwrap(c.argv)
            doc = "\n".join(h.body for h in c.heredocs) if c.heredocs else (_sh._literal_stdin(u.pipeline.commands[k - 1]) if k else None)
            found = _sh.shell_body(real, doc) if real else None
            if found:
                return found[0]
    return ""


# ------------------------------------------------------------ projects
CD_DIR = re.compile(r"(?:^|[;&|(\n][ \t]*)cd[ \t]+(\"[^\"\n]+\"|'[^'\n]+'|[^\s;&|]+)")
GIT_C = re.compile(r"\bgit\s+-C\s+(\"[^\"\n]+\"|'[^'\n]+'|[^\s;&|]+)")
_ROOTS: dict = {}
_GIT_ROOTS: set = set()


def project_of(path: str):
    """The project a path belongs to: the nearest directory with a `.git`, else the first two levels under the
    home directory (~/Documents/foo). None when the path is relative, temporary or unknown."""
    if not path or path.startswith(("\\\\", "//")):   # a network path in a command: looking at it would connect out
        return None
    p = os.path.normpath(_sh.expanduser(path))
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


_DIR_FLAGS = {"git": {"-C"}, "make": {"-C", "--directory"}, "gmake": {"-C", "--directory"}, "npm": {"--prefix"}, "pnpm": {"-C", "--dir"}, "yarn": {"--cwd"}, "uv": {"--directory", "--project"}, "poetry": {"-C", "--directory"}, "cargo": {"-C"}}


def _dir_flag(argv: list):
    """The directory a tool is told to work in: `git -C x`, `make -C x`, `npm --prefix x`."""
    if not argv:
        return None
    flags = _DIR_FLAGS.get(_sh.head_name(argv[0]))
    if not flags:
        return None
    for i, a in enumerate(argv[1:], 1):
        if a in flags and i + 1 < len(argv):
            return argv[i + 1]
        for f in flags:
            if f.startswith("--") and a.startswith(f + "="):
                return a[len(f) + 1:]
    return None


def seg_dir(cmd: str, seg_text: str):
    """The directory a segment of a command ran in: the last `cd` before it (`cd a && build && cd b && pytest` -> a/b)."""
    head = seg_text.split("\n", 1)[0]
    hit = None
    for u in _units(cmd):
        if u.text == seg_text or u.text.split("\n", 1)[0] == head:
            hit = u
            break
    if hit is None:
        return None
    if hit.cwd:
        return _sh.expanduser(hit.cwd)
    for c in hit.pipeline.commands:
        d = _dir_flag(c.argv) if c.kind == "simple" else None
        if d:
            return _sh.expanduser(_sh.resolve(d, hit.env))
    return None


def event_dir(e):
    """Where a tool call worked: an Edit/Write's file, a Bash command's `cd` or `-C` directory, or the one absolute path its single command names.
    A command that moves between two directories, or that mixes commands with and without a place, has no single place: None."""
    if e.name in EDIT_TOOLS:
        return _sh.expanduser((e.text or "").strip()) or None
    if e.name != "Bash":
        return None
    cmd = e.text if isinstance(e.text, str) else ""
    us = _sh.units(cmd)
    dirs = set()
    named, placeless = [], False
    for u in us:
        if u.level or u.guard == "no":
            continue
        after = u.cwd_after
        if after is None:
            return None
        if after:
            dirs.add(after.rstrip("/\\") or after)
        for c in u.pipeline.commands:
            if c.kind != "simple" or not c.words:
                continue
            argv = c.argv
            flag = _dir_flag(argv)
            if flag:
                dirs.add(_sh.resolve(flag, u.env).rstrip("/\\"))
                continue
            h = _sh.head_name(argv[0])
            if h in ("cd", "pushd", "popd", "chdir", "Set-Location", "sl", "export"):
                continue
            place = None
            for a in argv[1:]:
                a = _sh.resolve(a, u.env)
                if a.startswith("-") or "://" in a:
                    continue
                m = ABS_TOKEN.match(a)
                if m and not TOOL_PATH.search(m.group(1)) and not TEMP_PATH.search(m.group(1)) and not a.startswith("/dev/"):
                    place = m.group(1)
                    break
            if place:
                named.append(place)
            else:
                placeless = True
    if len(dirs) > 1:
        return None
    if dirs:
        return _sh.expanduser(dirs.pop())
    if named and not placeless:
        return _sh.expanduser(named[0])
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
        targets = [_sh.expanduser(_resolve_vars(t.strip(), cmd)) for t in segment_targets(seg, cmd) if t.strip()] or [""]
        for t in targets:
            path = t if os.path.isabs(t) else (os.path.join(here, t) if here else (event_dir(e) if not t else None))
            p = project_of(path or "")
            if not p:
                return None
            out.add(p)
    return out or None


ABS_TOKEN = re.compile(r"((?:/|~/)[\w.@+\-\u4e00-\u9fff/]+)")
TOOL_PATH = re.compile(r"/(?:s?bin|site-packages|\.venv|venv|node_modules|\.cache|\.local)/|^/(?:usr|opt|bin|sbin|etc|dev|System|Library|Applications)/")


def bash_is_edit(cmd: str) -> bool:
    """Does this command change code? Decided command by command, each by what it writes and where."""
    if not isinstance(cmd, str):
        return False
    return any(_unit_is_edit(u, cmd) for u in _sh.units(cmd))


def too_big(cmd) -> bool:
    """The reader gave up before the end of the command: what it does could not be checked."""
    if not (isinstance(cmd, str) and _sh.too_big(cmd)):
        return False
    _note_once("stop", f"a shell command too long to read in full ({len(cmd)} bytes): judged as could not check")
    return True


# ------------------------------------------------------------ verification
VERIFY = {
    "test": re.compile(r"(\bpytest\b|python3? -m pytest|python3? -m unittest|\bunittest\b|\btox\b|\bnox\b|hatch test|poetry run pytest|uv run pytest"
                       r"|npm (run )?test|pnpm (run )?test|yarn (run )?test|bun (run )?test|deno test|manage\.py test|(?:bin/)?rails test|artisan test|\bjust test|hatch run test|pdm (run )?test|npx (jest|vitest|mocha|ava|playwright test|cypress run)|\bjest\b|\bvitest\b|\bmocha\b"
                       r"|\bgo test\b|cargo test|cargo nextest|\bcargo t\b|\bnpm t\b|\bpy\.test\b|bazel test|\bgotestsum\b|\bsbt\b[^|;&\n]*\btest\b|\bdart test\b|node\s+(?:-\S+\s+)*--test\b|mvnw?\b[^|;&\n]*\s(?:test|verify)\b|gradlew?\b[^|;&\n]*\s(?:\S*:)?(?:test|check)\b|dotnet test|swift test|xcodebuild test|flutter test|mix test|bundle exec rspec|\brspec\b|rake test|\bphpunit\b|\bpest\b|\bctest\b|make test|make check|\binvoke-pester\b"
                       r"|(?:(?:^|[\s;&|(])(?:\S*/)?(?:python[\d.]*|uv run(?:\s+python[\d.]*)?|poetry run(?:\s+python[\d.]*)?|pipenv run(?:\s+python[\d.]*)?|hatch run|pdm run|node|bun|deno run|bash|sh|zsh|ruby|go run|tsx)\s+(?:-\S+\s+)*|^\s*|(?<![\w/.-])\./)(?:[\w.~/-]*/)?(?:eval\.py|[\w-]*_test\.(?:go|py|ts|js)|[\w-]*test[\w-]*\.(?:sh|py)|check[\w-]*\.sh|run_tests[\w.]*|validate[\w-]*\.py|check[\w-]*\.py|verify[\w-]*\.py|gate\.py)\b|gh pr checks|gh run (view|list|watch)|statusCheckRollup)", re.I),
    "build": re.compile(r"(\btsc\b|\beslint\b|prettier --check|\bbiome\b|\bruff\b|\bmypy\b|\bpyright\b|black --check|\bflake8\b|\bpylint\b|\bisort --check"
                        r"|npm run build|pnpm (run )?build|yarn (run )?build|(?:npm run|pnpm( run)?|yarn( run)?) (?:lint|typecheck|type-check)\b|vite build|next build|cargo (build|check|clippy)|cargo fmt --check|go build|go vet|staticcheck|golangci-lint"
                        r"|mvnw?\b[^|;&\n]*\s(?:compile|package|verify)\b|gradlew?\b[^|;&\n]*\s(?:\S*:)?(?:build|assemble|check)\b|dotnet build|swift build|xcodebuild|\bmake\b(?!\s+(?:clean|distclean|install|uninstall|help|fmt|format|docs?|run|dev|serve|start|watch|migrate|deploy|publish|up|down|logs|shell)\b)|\bphpstan\b|\bpsalm\b|\brubocop\b|\bshellcheck\b|terraform validate|docker build"
                        r"|hyperframes(@[\w.]+)? (?:check|lint|validate|inspect)|tectonic|xelatex|latexmk|pdflatex|pdftotext|pdfinfo|python[\d.]*(?:\s+-[A-Za-z]+)*\s+-m py_compile|"
                        r"(?:(?:^|[\s;&|(])(?:\S*/)?(?:python[\d.]*|uv run(?:\s+python[\d.]*)?|poetry run(?:\s+python[\d.]*)?|pipenv run(?:\s+python[\d.]*)?|hatch run|pdm run|node|bun|deno run|bash|sh|zsh|ruby|go run|tsx)\s+(?:-\S+\s+)*|^\s*|(?<![\w/.-])\./)(?:[\w.~/-]*/)?(?:validate[\w-]*\.py|check[\w-]*\.py|verify[\w-]*\.py|lint[\w-]*\.py|qc\.py|build[\w-]*\.(?:py|sh))\b"
                        r"|ast\.parse\(|\bcompileall\b|\b(?:ba|z)?sh -n\b|\bphp -l\b|\bruby -c\b)", re.I),   # syntax checks
    "render": re.compile(r"(hyperframes(@[\w.]+)? (render|build)|\bffmpeg\b|\bffprobe\b|(?:npx )?remotion render|manim |blender |music[\w-]*\.sh|render[\w-]*\.sh)", re.I),
    "push": re.compile(r"(git push|kaggle kernels push|kaggle competitions submit|kernels push)", re.I),
    "commit": re.compile(r"(git commit|git tag)", re.I),
    "run": re.compile(r"(python[\d.]*(?:\s+-[A-Za-z]+)*\s+(?:\S+\.py|-m (?!http)|-c\b|- <<)|node \S+\.(m?js|ts)|node --check|npx (?!remotion)\S+|\bcurl\b|bash \S+\.sh|\bsh \S+\.sh|\./\S+|cargo run|go run|\bmake\b|docker (build|compose up|run)|kaggle kernels (status|output)|uv run (python|pytest|ruff|mypy|-q python|-q pytest)|\.venv/bin/python)", re.I),
}
# Named here and not in VERIFY: VERIFY is also searched anywhere in a line elsewhere, and these words are ordinary English or too short for that.
_MORE_TEST = re.compile(r"(?:playwright test|cypress run|ava\b|wdio\b|nose2\b|python[\d.]* -m (?:nose2|doctest|tests?\b[\w.]*|[\w.]+\.tests?\b)|cargo (?:llvm-cov|tarpaulin)|richgo test|zig (?:build )?test|meson test|ninja test|cmake --build\b.*--target test|buck2? test|lein test|stack test|cabal test|dune test|bats\b|elm-test\b|busted\b|karma start|prove\b|shellspec\b|R CMD check|Rscript .*testthat|julia .*Pkg\.test|nix flake check|act\b|composer test|turbo test|ward\b)", re.I)
_TEST_SCRIPT_FILE = re.compile(r"(?:^|/)(?:tests?/[\w./-]+\.(?:py|sh|js|mjs|cjs|ts)|test[\w.-]*\.(?:js|mjs|cjs|ts|sh|py)|[\w-]*\.(?:test|spec)\.(?:js|mjs|cjs|ts|tsx))$", re.I)
PIPE_SWALLOW = re.compile(r"\|&?\s*(?:(tail|head|ghead|gtail|grep|egrep|ggrep|zgrep|rg|awk|gawk|sed|gsed|wc|sort|uniq|cut|tee|less|more|cat|true|false|dd|read|while|perl|python[\d.]*|ruby|node|stdbuf|command|timeout|(?i:select-object|select|select-string|sls|measure-object|measure|out-null|findstr))\b|[:>({])")   # the pipeline exits with the last command's status (`|&` pipes stderr too); PowerShell's cmdlets are not case-sensitive
NARROWED_TEST = re.compile(r"(pytest[^|\n]*\s-k\s|--testNamePattern|-t ['\"]|pytest[^|\n]*\s[\w/]+\.py::|pytest\s+[\w/]+\.py\b)", re.I)
OPAQUE_TOOLS = {"Agent", "Task", "Monitor", "mcp__terminal__run_in_terminal", "Workflow"}


NON_VERIFY_VERB = re.compile(r"^\s*(export |cd |pip3? |pipx |uv (?:pip|add|sync|lock|tool|remove)\b|poetry (?:add|install|lock|remove|show)\b|pdm (?:add|install|lock|remove)\b|pipenv (?:install|uninstall|lock)\b|npm (?:install|i|ci|ls|list|view|info|uninstall|un|rm|remove|update|up|why|explain|outdated|audit)\b|yarn (?:add|install|remove|why|list|info|upgrade)\b|pnpm (?:add|install|i|remove|rm|list|ls|why|update|up|outdated)\b|bun (?:add|install|i|remove|rm|update|pm)\b|apt(?:-get)? |conda |mamba |gem |bundle (?:add|remove|install)\b|composer (?:require|remove|install|update)\b|go (?:get|install|mod)\b|cargo (?:install|add|remove)\b|ls\b|cat\b|grep\b|rg\b|ag\b|ack\b|fd\b|echo\b|printf\b|find\b|wc\b|head\b|tail\b|sed\b|awk\b|less\b|more\b|diff\b|jq\b|cut\b|sort\b|uniq\b|xargs\b|stat\b|tree\b|nl\b|bat\b|column\b|brew\b|which\b|pkill\b|pgrep\b|killall\b|kill\b|sleep\b|until\b|while\b|mkdir\b|rmdir\b|touch\b|chmod\b|chown\b|ln\b|file\b|strings\b|hash\b|alias\b|unset\b|test\b|\[\s|say\b|vim?\b|nvim\b|nano\b|code\b|emacs\b|pydoc\d?\b|help\b|info\b|tar\b|unzip\b|zip\b|wget\b|cp\b|mv\b|rm\b|git (add|status|log|diff|remote|config|stash|checkout|grep|show|blame|rm|mv|merge|rebase|pull|fetch|switch|branch|cherry-pick|am|apply|restore|reset|clean|revert|cat-file|ls-files|rev-parse|rev-list)\b|gh (?!run\b|pr checks\b|workflow\b)\S+|ps\b|lsof\b|open\b|df\b|du\b|date\b|man\b|type\b|history\b|whatis\b|apropos\b|tldr\b|command -v\b|docker (?:compose )?logs\b|docker pull\b|kubectl logs\b|journalctl\b|\w+=|(?i:(?:get|test|select|set|new|copy|move|remove|stop|start|write|out|format|measure|sort|where|foreach|tee|add|clear|convert|export|import|compare)-\w+|gc|gci|sls|findstr|where(?:\.exe)?|python[\d.]*(?:\.exe)? -m (?:pip|pydoc))\b)")
_SERVER_HEADS = {"uvicorn", "gunicorn", "hypercorn", "serve", "http-server", "live-server", "nodemon", "pytest-watch", "ptw"}
_SERVER_LINE = re.compile(r"(?:python[\d.]* -m (?:http\.server|uvicorn|gunicorn)|flask run|streamlit run|next (?:dev|start)|vite(?: (?:dev|serve|preview)\b|$| --)|vitest (?:dev|watch)\b|cargo watch\b)", re.I)


def posix_probe(text: str) -> str:
    """`.\\gradlew.bat test`, `go.exe test`, `.\\scripts\\run_tests.ps1`: read a Windows command like the POSIX one. Only for matching; never executed."""
    return WIN_EXT.sub("", WIN_SEP.sub("/", text))
WIN_EXT = re.compile(r"(?<=[\w-])\.(?:exe|cmd|bat|ps1)\b", re.I)
WIN_SEP = re.compile(r"(?<=[\w.])\\(?=[\w.])")


TEST_IMPORT = re.compile(r"(?:^|[\s;'\"(])(?:import\s+(?:[\w.]+\.)?test_\w+|from\s+(?:[\w.]+\.)?test_\w+\s+import)\b", re.M)   # a snippet that runs the test functions itself
TEST_CALL = re.compile(r"\btest_\w*\s*\(|getattr\(|startswith\(\s*['\"]test_")
_RUNNER_CALL = re.compile(r"\bpytest\.main\(|\bunittest\.main\(|\bunittest\.TextTestRunner\(|\bnose2?\.\w*main\(|\bdoctest\.testmod\(")
PY_C = re.compile(r"python[\d.]*(?:\s+-[A-Za-z]+)*\s+-c\s*(['\"])(.*?)(?<!\\)\1", re.S)
IMPORT_STMT = re.compile(r"\s*(?:import\s+[\w.]+(?:\s+as\s+\w+)?(?:\s*,\s*[\w.]+(?:\s+as\s+\w+)?)*|from\s+[\w.]+\s+import\s+[\w*]+(?:\s+as\s+\w+)?(?:\s*,\s*\w+(?:\s+as\s+\w+)?)*)\s*")


def import_only(cmd: str) -> bool:
    """`python -c "import foo"`: an import check, nothing more (`import json; print(...)` is not)."""
    m = PY_C.search(cmd[:200_000])
    if not m:
        return False
    stmts = [x for x in re.split(r"[;\n]", m.group(2)) if x.strip()]
    return bool(stmts) and all(IMPORT_STMT.fullmatch(x[:400]) for x in stmts)


_STDLIB = frozenset(getattr(sys, "stdlib_module_names", ()) or (
    "abc argparse array ast asyncio base64 bisect bz2 calendar cmath codecs collections colorsys concurrent configparser contextlib copy csv ctypes "
    "dataclasses datetime decimal difflib dis email enum errno filecmp fnmatch fractions functools gc getpass glob gzip hashlib heapq hmac html http "
    "importlib inspect io ipaddress itertools json keyword linecache locale logging lzma math mimetypes multiprocessing numbers operator os pathlib "
    "pickle pkgutil platform plistlib pprint queue random re sched secrets select shlex shutil signal site socket sqlite3 ssl stat statistics string "
    "struct subprocess sys sysconfig tarfile tempfile textwrap threading time timeit tokenize tomllib traceback types typing unicodedata unittest "
    "urllib uuid warnings wave weakref xml zipfile zlib").split())
# libraries and tools: importing them reads data or runs a tool, it does not exercise the project's own code
NOT_PROJECT = frozenset("pip pipx venv virtualenv ensurepip pytest build twine setuptools wheel black ruff mypy isort flake8 pylint pyright pyflakes bandit autopep8 IPython "
                        "jupyter notebook nbconvert pre_commit tox nox huggingface_hub kaggle gdown numpy pandas PIL requests httpx yaml toml tomli "
                        "matplotlib scipy sklearn torch transformers bs4 lxml openpyxl docx pptx fitz pypdf cv2 tqdm rich click typer playwright "
                        "selenium boto3 anthropic openai pydantic fastapi django flask sqlalchemy starlette uvicorn gunicorn aiohttp attr attrs celery redis psycopg psycopg2 "
                        "tensorflow keras spacy nltk jinja2 markdown dotenv seaborn plotly networkx sympy statsmodels xgboost lightgbm".split())
_VERSION_ONLY = re.compile(r"^\s*import\s+\w+\s*[;\n]\s*print\(\s*\w+\.(?:__version__|VERSION|version)\s*\)\s*$")
LOCAL_HOST = re.compile(r"^(?:https?://)?(?:[^/@\s]*@)?(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(?:[:/?#]|$)|^:\d+", re.I)


def _project_imports(code: str) -> bool:
    if _VERSION_ONLY.match(code):
        return False
    names = []
    for stmt in re.split(r"[;\n]", _blank_strings(code)):
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


_TOOL_HEADS = {"pip", "pip3", "pipx", "uv", "npm", "npx", "pnpm", "yarn", "bun", "ruff", "black", "mypy", "isort", "flake8", "pylint", "pytest", "tsc", "eslint", "prettier", "configure", "gradlew", "mvnw", "coverage", "tox", "nox", "wheel", "twine"}


def _script_of(real: list):
    """(script, its arguments) when an interpreter runs a file."""
    h = _sh.head_name(real[0])
    args = real[1:]
    if h == "go" and args[:1] == ["run"]:
        return (args[1], args[2:]) if len(args) > 1 else None
    if h == "deno" and args[:1] == ["run"]:
        args = args[1:]
    elif h == "bun" and args[:1] == ["run"]:
        args = args[1:]
    elif not re.match(r"^(?:python[\d.]*|pypy[\d.]*|node|bun|deno|ruby|php|perl|tsx|ts-node|bash|sh|zsh|dash)$", h):
        return None
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-W", "-X", "-r", "--require", "--import", "--loader"):
            i += 2
            continue
        if a == "--":
            i += 1
            break
        if a == "-" or (a.startswith("-") and (a.endswith("c") or a.endswith("m") or a in ("-e", "--eval", "-p", "--print", "--test", "--check"))):
            return None
        if not a.startswith("-"):
            break
        i += 1
    return (args[i], args[i + 1:]) if i < len(args) else None


def _exercises(real: list, c=None) -> bool:
    if not real or not_a_run(real):
        return False
    h = _sh.head_name(real[0])
    args = real[1:]
    low = h.lower()
    if re.match(r"^(?:python[\d.]*|pypy[\d.]*)$", h):
        i = 0
        while i < len(args):
            a = args[i]
            if a in ("-W", "-X"):
                i += 2
                continue
            if a == "-m":
                mod = (args[i + 1] if i + 1 < len(args) else "").split(".")[0]
                return bool(mod) and mod not in _STDLIB and mod not in NOT_PROJECT
            if not a.startswith("-") or a == "-":
                break
            if a.endswith("c") and not a.startswith("--") and i + 1 < len(args):
                return _project_imports(args[i + 1])
            i += 1
        code = _code_of(real, c)
        if code:
            return _project_imports(code[1])
        if i < len(args) and args[i] != "-":
            return bool(re.search(r"\.py[wz]?$", args[i])) and "site-packages" not in args[i]
        return False
    if low in ("curl", "wget", "http", "https", "xh", "httpie"):
        return any(LOCAL_HOST.match(a) for a in args if not a.startswith("-"))
    if low in ("node", "tsx", "ts-node", "bun", "deno", "ruby", "php"):
        s = _script_of(real)
        return bool(s) and (bool(re.search(r"\.(?:m?js|cjs|tsx?|rb|php)$", s[0])) or (low == "node" and not s[0].startswith("-")))
    if low in ("bash", "sh", "zsh", "dash"):
        s = _script_of(real)
        return bool(s) and bool(re.search(r"\.(?:sh|bash|zsh)$", s[0]))
    if low == "go" or low == "cargo" or low == "dotnet" or low == "swift":
        return args[:1] == ["run"]
    if low == "java":
        return bool(args) and (args[0] == "-jar" or not args[0].startswith("-"))
    if "/" in real[0] or "\\" in real[0]:
        written = real[0].replace("\\", "/")
        if low in _TOOL_HEADS or re.search(r"(?:^|/)(?:\.?venv|node_modules|site-packages)/", written) or written.startswith("/usr/") or written.startswith("/bin/"):
            return False
        return not re.search(r"\.(?:md|txt|rst|json|ya?ml|toml|lock)$", written, re.I)
    return False


def exercises_code(probe: str, seg: Segment) -> bool:
    """A command that runs the project's own code after a fix: a script, `python -m pkg`, a snippet that imports a project
    module, `node app.js`, `./bin/tool`, `curl localhost`. Reading a file, installing a package, asking for --help or querying a website does not."""
    for u in _units(probe):
        for c in u.pipeline.commands:
            if c.kind == "simple" and c.words:
                real = _sh.unwrap(c.argv)
                c2 = c
                if not c.heredocs and seg is not None and seg.heredoc and seg.unit is not None:
                    c2 = next((x for x in seg.unit.pipeline.commands if x.heredocs), c)
                return _exercises(real, c2)
    return False


def not_a_run(real: list) -> bool:
    """`pytest --collect-only`, `tox list`, `ruff format`: the tool is named, but nothing gets tested or checked."""
    if not real:
        return True
    h = _sh.head_name(real[0]).lower()
    args = real[1:]
    if NOT_A_RUN.search(" ".join(args)[:4000]):
        return True
    if "-V" in args and _V_IS_VERSION.match(h):
        return True
    if "-v" in args and h in ("tsc", "mvn", "mvnw", "gradle", "gradlew", "node"):
        return True
    sub = args[0] if args else ""
    if h == "go" and sub == "test" and "-c" in args[1:]:
        return True
    if h in ("tox", "nox") and ("-l" in args or sub in ("list", "l", "config", "c", "devenv", "depends", "d")):
        return True
    if h == "vitest" and sub in ("list", "dev", "watch"):
        return True
    if h == "cargo" and sub == "nextest" and args[1:2] in (["list"], ["show-config"]):
        return True
    if h == "ruff" and sub in ("format", "rule", "config", "linter", "clean", "version", "server"):
        return True
    if h == "biome" and sub in ("format", "explain", "init", "version", "rage"):
        return True
    if h == "tsc" and sub == "--showConfig":
        return True
    if h in ("gradle", "gradlew") and sub in ("tasks", "dependencies", "properties", "projects", "help"):
        return True
    if h in ("make", "gmake") and any(re.fullmatch(r"-[a-zA-Z]*n[a-zA-Z]*|--just-print|--recon|-[a-zA-Z]*q[a-zA-Z]*", a) for a in args):
        return True
    return False


_TEST_NAME = re.compile(r"(?:^|[:_/-])(?:tests?|specs?|e2e|unit|integration)(?:$|[:_/-])|^ci$", re.I)
_WATCH_NAME = re.compile(r"(?:^|[:_-])(?:watch|dev|serve|start|ui|debug|update)(?:$|[:_-])", re.I)
_LINT_NAME = re.compile(r"(?:^|[:_-])(?:lint|typecheck|type-check|types|tsc|check|format:check|fmt:check)(?:$|[:_-])", re.I)
_BUILD_NAME = re.compile(r"(?:^|[:_-])(?:build|compile|bundle|dist)(?:$|[:_-])", re.I)
_MAKE_NOT_BUILD = {"clean", "distclean", "install", "uninstall", "help", "fmt", "format", "doc", "docs", "run", "dev", "serve", "start", "watch", "migrate", "deploy", "publish", "up", "down", "logs", "shell", "fix"}
_PM_BUILTINS = {"add", "install", "i", "ci", "remove", "rm", "un", "uninstall", "list", "ls", "why", "explain", "info", "view", "update", "up", "upgrade", "outdated", "audit", "init", "create", "config", "set", "cache", "store", "link", "unlink", "publish", "pack", "login", "logout", "version", "dedupe", "prune", "rebuild", "import", "patch", "exec", "dlx", "x", "node", "bin", "root", "pm"}


def _skip_opts(args: list, values: set) -> list:
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in values else 1
    return args[i:]


def _task_names(real: list):
    """(tool, the script or target names it runs) for package managers and task runners; None for anything else."""
    h = _sh.head_name(real[0]).lower()
    args = real[1:]
    if h in ("make", "gmake", "bmake"):
        return "make", [a for a in _positional(args, {"-C", "-f", "--file", "-j", "--jobs", "-l", "-o", "-W", "-I", "--directory", "--load-average"}) if "=" not in a]
    if h == "npm":
        rest = _skip_opts(args, {"--prefix", "-w", "--workspace", "-C"})
        if not rest:
            return "npm", []
        if rest[0] in ("test", "t", "tst"):
            return "npm", ["test"]
        if rest[0] in ("run", "run-script", "rum", "urn"):
            rest = _skip_opts(rest[1:], {"--prefix", "-w", "--workspace"})
            return "npm", rest[:1]
        return "npm", []
    if h == "pnpm":
        rest = _skip_opts(args, {"-C", "--dir", "--filter", "-F", "--workspace-concurrency", "--reporter"})
        if not rest:
            return "pnpm", []
        if rest[0] in ("test", "t", "tst"):
            return "pnpm", ["test"]
        if rest[0] == "run":
            return "pnpm", _skip_opts(rest[1:], {"--filter", "-F"})[:1]
        return "pnpm", ([] if rest[0] in _PM_BUILTINS else rest[:1])
    if h == "yarn":
        rest = _skip_opts(args, {"--cwd"})
        if rest[:1] == ["workspace"]:
            rest = rest[2:]
        elif rest[:2] == ["workspaces", "run"]:
            rest = rest[2:]
        elif rest[:2] == ["workspaces", "foreach"]:
            rest = _skip_opts(rest[2:], {"--since", "--from", "--include", "--exclude", "-j", "--jobs"})
        if rest[:1] == ["run"]:
            rest = rest[1:]
        return "yarn", ([] if not rest or rest[0] in _PM_BUILTINS else rest[:1])
    if h == "bun":
        if args[:1] == ["test"]:
            return "bun", ["test"]
        if args[:1] == ["run"] and len(args) > 1 and not re.search(r"\.\w+$", args[1]):
            return "bun", args[1:2]
        return None
    if h == "turbo":
        rest = _skip_opts(args, {"--filter", "-F", "--concurrency"})
        if rest[:1] == ["run"]:
            rest = rest[1:]
        return "turbo", rest[:1]
    if h == "nx":
        if args[:1] == ["run"] and len(args) > 1:
            return "nx", [args[1].split(":")[-1]]
        if args[:1] in (["run-many"], ["affected"]):
            for i, a in enumerate(args):
                if a in ("-t", "--target", "--targets") and i + 1 < len(args):
                    return "nx", [args[i + 1]]
                if a.startswith(("--target=", "--targets=")):
                    return "nx", [a.split("=", 1)[1]]
            return "nx", []
        return "nx", args[:1]
    if h == "lerna":
        return "lerna", args[1:2] if args[:1] == ["run"] else []
    if h in ("just", "task", "cake"):
        return h, _positional(args, {"-f", "--justfile", "--taskfile", "-d", "--dir", "-t"})[:1]
    if h == "mise":
        return "mise", _positional(args[1:])[:1] if args[:1] in (["run"], ["r"]) else []
    if h == "rake":
        names = _positional(args, {"-f", "--rakefile", "-I"})
        return "rake", names or ["test"]
    if h in ("hatch", "pdm", "devbox") and args[:1] == ["run"] and len(args) > 1:
        return h, args[1:2]
    if h == "earthly":
        return "earthly", [a.lstrip("+") for a in args if a.startswith("+")][:1]
    if h == "composer":
        return "composer", args[:1] if args[:1] == ["test"] else []
    return None


def _task_kinds(tool: str, names: list) -> set:
    if tool in ("make",):
        if not names:
            return {"build", "run"}
        out = set()
        for n in names:
            if n in _MAKE_NOT_BUILD:
                if n in ("run", "dev", "serve", "start"):
                    out.add("run")
                continue
            if _TEST_NAME.search(n) or n == "check":
                out |= {"test", "run"}
            else:
                out |= {"build", "run"}
        return out
    out = set()
    for n in names:
        if _WATCH_NAME.search(n):
            continue
        if _TEST_NAME.search(n) or (tool in ("just", "task", "mise") and n in ("check", "ci")):
            out.add("test")
        elif _LINT_NAME.search(n) or _BUILD_NAME.search(n):
            out.add("build")
    return out


def command_line(real: list) -> str:
    """A command in one spelling, however it was typed: its name without a path or a Windows suffix, single spaces, no wrappers."""
    return " ".join([_sh.head_name(real[0])] + real[1:])[:4000]


def non_verifying(line: str) -> bool:
    """Reading, installing and moving around: `cat`, `pip`, `git status`. Not `test.sh`, whose name only starts like `test`."""
    return _matches(NON_VERIFY_VERB, line) and not re.match(r"gh (?:pr checks|run)\b", line)


def _matches(rx, line: str) -> bool:
    """The pattern has to match at the command itself, and cover its whole name: `pytest-watch` is not `pytest`."""
    m = rx.match(line)
    if not m:
        return False
    return m.end() >= len(line.split(" ", 1)[0])


def command_kinds(argv: list) -> set:
    """What a simple command is, from the command itself and never from a word in its arguments:
    "test", "build", "render", "push", "commit", "run"."""
    return set(_command_kinds_of(tuple(argv), VERIFY["test"].pattern))


@functools.lru_cache(maxsize=2048)
def _command_kinds_of(words: tuple, _pattern: str) -> set:
    argv = list(words)
    real = _sh.unwrap(argv)
    if not real:
        return set()
    line = command_line(real)
    h = _sh.head_name(real[0]).lower()
    if h == "git":
        a = _git_args(real)
        sub = a[0] if a else ""
        rest = a[1:]
        if sub == "push":
            return set() if any(x in ("-n", "--dry-run", "--help", "-h") for x in rest) else {"push"}
        if sub == "commit":
            return set() if any(x in ("--dry-run", "--help", "-h") for x in rest) else {"commit"}
        if sub == "tag":
            return {"commit"} if rest and not any(x in ("-l", "--list", "-d", "--delete", "-v", "--verify", "--help") for x in rest) else set()
        return set()
    if not_a_run(real):
        return set()
    if non_verifying(line):
        return set()
    written = " ".join(real)[:4000].replace("\\", "/")
    out = set()
    if _sh.head_name(argv[0]) != _sh.head_name(real[0]) or argv[0] != real[0]:
        outer = command_line(argv)
        if _matches(VERIFY["run"], outer) and not non_verifying(outer):
            out.add("run")
    task = _task_names(real)
    if task:
        out |= _task_kinds(*task)
        if task[0] in ("yarn", "pnpm") and task[1] and task[1][0] in real[1:] and task[1][0] not in ("yarn", "pnpm", "npm", "npx"):   # `yarn jest`: a package's own command, not a script
            out |= _command_kinds_of(tuple(real[real.index(task[1][0], 1):]), _pattern)
        if _config_verify(line) or _config_verify(written):
            out.add("test")   # the user's own `verify_commands` can name a script (`make verify`, `npm run ci:full`)
        return out
    if _is_server(real, line):
        return out
    if _config_verify(line) or _config_verify(written):
        out.add("test")
    for kind, rx in VERIFY.items():
        if kind in ("push", "commit"):
            continue
        if _matches(rx, line) or _matches(rx, written):
            out.add(kind)
    if _matches(_MORE_TEST, line):
        out.add("test")
    s = _script_of(real)
    if s:
        file_line = " ".join([s[0].replace("\\", "/")] + s[1])[:4000]
        base_line = " ".join([os.path.basename(s[0].replace("\\", "/"))] + s[1])[:4000]
        for kind in ("test", "build", "render"):
            if _matches(VERIFY[kind], file_line) or _matches(VERIFY[kind], base_line):
                out.add(kind)
        if _TEST_SCRIPT_FILE.search(s[0].replace("\\", "/")):
            out.add("test")
    elif h.endswith(".py") or "/" in real[0] or real[0].startswith("."):
        base = os.path.basename(real[0].replace("\\", "/")) + " " + " ".join(real[1:])
        for kind in ("test", "build", "render"):
            if _matches(VERIFY[kind], base[:4000]):
                out.add(kind)
    return out


_BASE_TEST_PATTERN = VERIFY["test"].pattern


@functools.lru_cache(maxsize=8)
def _user_verify(pattern: str):
    """`verify_commands` from the config: config.apply appends them, escaped, to the test pattern."""
    extra = pattern[len(_BASE_TEST_PATTERN):].lstrip("|") if pattern.startswith(_BASE_TEST_PATTERN) else ""
    return re.compile(extra, re.I) if extra else None


def _config_verify(line: str) -> bool:
    rx = _user_verify(VERIFY["test"].pattern)
    return bool(rx and rx.match(line))


def _is_server(real: list, line: str) -> bool:
    h = _sh.head_name(real[0]).lower()
    return h in _SERVER_HEADS or bool(_SERVER_LINE.match(line)) or any(a in ("--watch", "--watchAll", "--serve") for a in real[1:])


def stage_kinds(u, kinds: set) -> bool:
    """Does a stage of this pipeline do one of these kinds of check?"""
    for k, c in enumerate(u.pipeline.commands):
        if c.kind != "simple" or not c.words:
            continue
        real = _sh.unwrap(c.argv)
        if not real or _sh.shell_body(real, "" if c.heredocs or k else None):
            continue
        code = _code_of(real, c)
        if code:
            lang, text = code
            if "test" in kinds and ((TEST_IMPORT.search(text) and TEST_CALL.search(text)) or _RUNNER_CALL.search(_blank_strings(text))):
                return True
            for line in _code_shell_lines(text):
                if bash_verifies(line, kinds):
                    return True
            if "build" in kinds and lang == "python" and not c.heredocs and (_is_import_only_code(text) or "ast.parse(" in text):
                return True
            if "exercise" in kinds and lang == "python" and _project_imports(text):
                return True
            if "exercise" in kinds and lang != "python" and re.search(r"\brequire\(\s*['\"]\.|\bfrom\s+['\"]\.|\bimport\(\s*['\"]\.", text):
                return True
            if "run" in kinds and not _code_marks_a_write(text):
                return True
            continue
        if "exercise" in kinds and _exercises(real, c):
            return True
        if command_kinds(c.argv) & kinds:
            return True
    return False


def _is_import_only_code(code: str) -> bool:
    stmts = [x for x in re.split(r"[;\n]", code) if x.strip()]
    return bool(stmts) and all(IMPORT_STMT.fullmatch(x[:400]) for x in stmts)


def verifying_segments(cmd: str, kinds: set, after_edit_only: bool = False):
    units = list(_units(cmd))
    if after_edit_only:
        last = max((i for i, u in enumerate(units) if _unit_is_edit(u, cmd)), default=-1)
        units = units[last + 1:]
    out = []
    for u in units:
        if u.guard == "no":
            continue    # `false && pytest`, `if false; then pytest; fi`, `exit 0; pytest`
        if u.dropped and u.masked:
            continue    # `pytest > /dev/null || true`: neither the output nor the exit status comes back
        code = _unit_code(u)
        if code and code[2].heredocs and _code_is_edit(code[1], u, cmd):
            continue    # a script that writes files is an edit, whatever else it does
        if stage_kinds(u, kinds):
            out.append(_as_segment(u))
    return out


def bash_verifies(cmd: str, kinds: set, after_edit_only: bool = False) -> bool:
    return bool(verifying_segments(cmd, kinds, after_edit_only))


def _unit_named(cmd: str, seg_text: str):
    head = seg_text.split("\n", 1)[0]
    for u in _units(cmd):
        if u.text == seg_text or u.text.split("\n", 1)[0] == head:
            return u
    return None


def run_unproven(cmd: str, seg_text: str) -> bool:
    """For judge_output. The exit status says nothing about this run (`|| true`, `; echo done`, `[ -f x ] && pytest`): only a pass/fail line in its output can."""
    u = _unit_named(cmd, seg_text)
    return bool(u and (u.masked or u.guard == "maybe"))


def without_own_echo(out: str, cmd: str, seg_text: str) -> str:
    """For judge_output. `./run_tests.sh || echo ok`: the `ok` comes from the command line itself and proves nothing about the run."""
    u = _unit_named(cmd, seg_text)
    if not u or not u.own_echo:
        return out
    lines = (out or "").split("\n")
    for text in u.own_echo:
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == text:
                del lines[i]
                break
    return "\n".join(lines)
