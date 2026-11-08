"""What counts as a claim: a clause of the reply that states a result as fact.

A reply is read in four steps, and each decision stays inside the clause it belongs to:
  1. sentences, keeping bold and list text and the original characters (`hit.sentence` is findable in the reply);
  2. clauses, split at punctuation and at conjunctions;
  3. mood: what stands before a result word in its clause (negated, planned, conditional, an instruction, an
     obligation, a hypothetical, a general truth, someone else's) and what follows it;
  4. a lexicon per category, in which a passive such as "pushed" needs a subject about the work.

Deterministic, standard library only, and every pattern is linear: gaps are bounded, and most clauses are
dismissed by a word lookup before any pattern runs.
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass

# the evidence each category asks for (see rules.VERIFY and noncode.SPECS)
EVIDENCE = {
    "tests_pass": {"test"}, "checks_pass": {"test", "build"}, "build_ok": {"build", "test", "run"}, "rendered": {"render", "run"},
    "pushed": {"push"}, "committed": {"commit"}, "fixed": {"test", "build", "render", "exercise"}, "sent": {"sent"},
    "deployed": {"deployed"}, "downloaded": {"downloaded"}, "saved": {"saved"}, "scheduled": {"scheduled"},
    "checked": {"checked"}, "verified": {"verified"},
}


@dataclass
class ClaimHit:
    category: str
    sentence: str          # the original characters of the sentence, findable in the reply
    evidence_kinds: set
    clause: str = ""       # the clause that made the claim, normalised (lower case, no bold, code and quotes as tokens)
    closing: bool = False  # a bare sign-off ("Done.", "好了。"): it adds nothing to a claim of its category made earlier in the turn


# ------------------------------------------------------------------ sentences
FENCE = re.compile(r"```.*?```|~~~.*?~~~", re.S)
SKIP_LINE = re.compile(r"[ \t]*(?:>|#{1,6}[ \t]|\|)")   # quotes, headings, table rows
LIST_MARK = re.compile(r"[ \t]*(?:(?:[-*+•]|\d{1,3}[.)])[ \t]+)?(?:\[([ xX])\][ \t]+)?")
CODE = re.compile(r"`[^`\n]*`")
QUOTED = re.compile(r"\"[^\"\n]{0,400}\"|“[^”\n]{0,400}”|「[^」\n]{0,400}」|『[^』\n]{0,400}』|‘[^’\n]{0,400}’|(?<!\w)'[^'\n]{1,400}'(?!\w)")
QUOTE_CHAR = re.compile(r"[\"“「『‘']")
LINK = re.compile(r"\[[^\[\]\n]{0,400}\]\([^)\s]{0,800}\)")
SESSION_LINK = re.compile(r"\]\(#local_")
STRIKE = re.compile(r"~~[^~\n]{0,400}~~")
MASK = ""
_CLOSERS = r"[*_”’）)」』\"'" + MASK + r"]{0,8}"
ENDS = re.compile(r"[。！？]+" + _CLOSERS + r"|[.!?]+" + _CLOSERS + r"(?=\s|$)")
ABBREV = re.compile(r"(?:^|[\s(])(?:e\.g|i\.e|vs|cf|fig|approx)$", re.I)
MAX_SENTENCE, MAX_CLAUSE = 1500, 400
MAX_JUDGED = 28000   # characters of distinct sentences with a result word in them: about 35 ms of work


def _masked(line: str) -> str:
    """The same length as the line, with inline code and quoted text blanked: a full stop in there ends nothing."""
    if "`" in line:
        line = CODE.sub(lambda m: MASK * len(m.group()), line)
    if QUOTE_CHAR.search(line):
        line = QUOTED.sub(lambda m: MASK * len(m.group()), line)
    return line


def _pieces(line: str):
    masked, start = _masked(line), 0
    for m in ENDS.finditer(masked):
        if masked[m.start()] == "." and (ABBREV.search(masked[max(0, m.start() - 8):m.start()]) or masked[m.start() - 1:m.start()] == "/"):
            continue   # "e.g. this", "go test ./... passes"
        piece = line[start:m.end()].strip()
        if piece:
            yield piece
        start = m.end()
    tail = line[start:].strip()
    if tail:
        yield tail


def _lines(text: str):
    """Each line of prose as (text after its list marker, checkbox state)."""
    if "```" in text or "~~~" in text:
        text = FENCE.sub("\n", text)
    for line in text.split("\n"):
        if not line or SKIP_LINE.match(line):
            continue
        m = LIST_MARK.match(line)
        yield line[m.end():], m.group(1)


def split_sentences(text: str) -> list:
    """The sentences of a reply as they were written: bold and inline code stay, list markers and checkboxes go."""
    return [p for line, _ in _lines(text) for p in _pieces(line)]


# ------------------------------------------------------------------ normalising a sentence
TEST_CMD = re.compile(r"^(?:\S{0,60}/)?(?:python\d? -m )?(?:pytest|py\.test|jest|vitest|mocha|rspec|unittest|tox|nox|phpunit)\b|^(?:npm|pnpm|yarn|bun)(?: run)? test\b|^(?:go|cargo|deno|dotnet|swift|flutter|mix|make) test\b|^test_\w|^tests?/|_test\.\w{1,5}$|^[\w./-]{0,60}test[\w-]{0,40}\.\w{1,5}$")
LINT_CMD = re.compile(r"^(?:\S{0,60}/)?(?:ruff|mypy|pyright|flake8|pylint|black|isort|eslint|prettier|biome|tsc|shellcheck|golangci-lint|pre-commit)\b|^cargo (?:clippy|check)\b|^go vet\b|^(?:npm|pnpm|yarn)(?: run)? (?:lint|typecheck)\b")
BUILD_CMD = re.compile(r"^(?:npm|pnpm|yarn|bun)(?: run)? build\b|^(?:cargo|go|docker|swift|dotnet|vite|next) build\b|^make$|^make build\b")
FILEISH = re.compile(r"^[\w./~-]{0,200}\.[a-z0-9]{1,6}$|/$")
CSS_FIXED = re.compile(r"position: ?fixed;?")
WS = re.compile(r"\s+")
CJK_LATIN = re.compile(r"(?<=[\u4e00-\u9fff])(?=[a-z0-9])|(?<=[a-z0-9])(?=[\u4e00-\u9fff])")
TERMINAL_ESCAPE = re.compile(r"\x1b\[[0-9;?]{0,20}[ -/]{0,4}[@-~]|\x1b[@-_]?")   # what a terminal hides, the words around it still say
UNDERLINE_BOLD = re.compile(r"(?<!\w)__|__(?!\w)")
TOKEN_QUOTE, TOKEN_LINK, TOKEN_STRUCK = " xquotex ", " xlinkx ", " xstruckx "   # opaque words: what they hide is not said by the reply


def _code_token(m) -> str:
    """Inline code is one opaque word: it can name what a clause is about, but what it says is not said by the reply."""
    body = m.group()[1:-1].strip().lower()
    if TEST_CMD.search(body):
        return " xtestx "
    if LINT_CMD.search(body):
        return " xlintx "
    if BUILD_CMD.search(body):
        return " xbuildx "
    return " xfilex " if FILEISH.search(body) else " xcodex "


def _normalise(raw: str) -> str:
    s = TERMINAL_ESCAPE.sub("", raw) if "\x1b" in raw else raw
    if "`" in s:
        s = CODE.sub(_code_token, s)
    if "](" in s:
        if SESSION_LINK.search(s):
            return ""   # "[that session](#local_x) did it": another session's work
        s = LINK.sub(TOKEN_LINK, s)
    if QUOTE_CHAR.search(s):
        s = QUOTED.sub(TOKEN_QUOTE, s)
    if "~~" in s:
        s = STRIKE.sub(TOKEN_STRUCK, s)
    if "__" in s:
        s = UNDERLINE_BOLD.sub("", s)
    s = s.replace("*", "").replace("’", "'").replace("\ufe0f", "").lower()
    if "fixed" in s:
        s = CSS_FIXED.sub(" xcodex ", s)
    if "up and running" in s:
        s = s.replace("up and running", "up-and-running")   # one idiom, not two clauses
    if not s.isascii():
        s = CJK_LATIN.sub(" ", s.replace("啦", "了").replace("咯", "了"))   # "已pushed", "测试OK", "修好啦"
    return WS.sub(" ", s).strip()


# ------------------------------------------------------------------ clauses
PAREN = re.compile(r"[(（]([^()（）]{0,300})[)）]")
SEP = re.compile(r",(?!\d)|(?<!\d),|[，;；、()（）→]|:(?=\s|$)|：|—+|\s-{1,2}>?\s| and | but | so | then | plus | however |但是|(?<!不)但|不过|然而|并且|而且|(?<!合)并(?![未非没不发行列入且])|然后|同时|所以|因此")
TRIM = " \t.。!！…~"
AND_SEPS = frozenset({"and", "then", "plus", "并", "并且", "而且", "然后"})
CARRY_SEPS = AND_SEPS | {",", "，"}


@dataclass
class Clause:
    start: int
    text: str
    sep: str          # the separator before it
    question: bool = False


def _clauses(s: str) -> list:
    out, start, sep = [], 0, ""
    for m in SEP.finditer(s):
        _add_clause(out, s, start, m.start(), sep)
        start, sep = m.end(), m.group().strip()
    _add_clause(out, s, start, len(s), sep)
    return out


def _add_clause(out: list, s: str, a: int, b: int, sep: str) -> None:
    raw = s[a:b]
    text = raw.strip(TRIM)
    if not text:
        return
    question = text.endswith(("?", "？"))
    if question:
        text = text.rstrip("?？ ")
    out.append(Clause(a + raw.index(text[0]) if text else a, text, sep, question))


# ------------------------------------------------------------------ marks
POSITIVE_MARK = re.compile("[✅☑✔✓🟢🎉🚀✨👍💚]")
NEGATIVE_MARK = re.compile("[❌✗✘🔴🚫⛔⏳🚧⬜◻⚠☐]")


# ------------------------------------------------------------------ mood: what stands before the result word
_ACTOR_ZH = (r"(?:[张王李赵刘陈杨黄吴周徐孙胡朱高林何郭马罗][三四五六七八九明华伟强军磊敏静丽芳洋勇杰涛超]|[小老阿][王李张刘陈赵杨黄吴周]|小明|小红|小刚"
             r"|同事|同学|用户|客户|对方|运维|运营|财务|官方|上游|社区|团队|别人|其他人|有人|大家|他们?|她们?|它|你们?|您|老板|产品经理?|产品|测试同事|客服|甲方|维护者|作者|机器人|接口|框架|服务器"
             r"|新版本|旧版本|该版本|此版本|本版本|版本\s?v?\d[\w.]{0,10}|alice|bob|carol|dave|dana|eve|frank|grace|tom|jack|mike|jane|john|sam|sarah|mary|peter|paul|david|james|emma|lucy|amy|anna|kate|lisa|chris|alex|ben|dan|kevin|jason|eric|ryan|nick|steve|tony|qa|bot)")
ZH_ACTOR = re.compile(_ACTOR_ZH + r"\s?(?:(?:已经|已|都|也|刚刚|刚|之前|早就|又|还|前天|昨天|当天|今天|亲自|自己)\s?){0,3}$")
ZH_RELEASE_NAMES = re.compile(r"(?:新版本|旧版本|该版本|此版本|本版本|版本\s?v?\d[\w.]{0,10}|接口|框架|服务器|产品)\s?(?:(?:已经|已|都|也)\s?){0,2}$")   # a release can be what went live, but not who fixed the bug
ZH_VETO = re.compile(
    r"没有?|未(?!来)|并非|不是|不能|不敢|不可|不要|不用|不必|没法|无法|难以|别|勿|"
    r"接下来|下一步|然后再|准备|打算|^计划|计划(?:让|要|在|把|下周|明天|今天|先)|目标|我去|我来|我会|我将|我要|我再|我也会|我还会|还要|还得|需要|必须|应该|应当|想要|希望|待|正在|"
    r"如果|要是|假如|假设|倘若|若|万一|一旦|只有|只要|除非|就算|即使|即便|哪怕|无论|不管|是否|有没有|是不是|当(?![前时然天])|等到|^等|"
    r"请|麻烦|记得|务必|确保|别忘|你可以|你能|您可以|可以|点击|试试|你跑|你试|"
    r"因为|由于|原因是|导致|看起来|似乎|好像|貌似|其实|疑似|可能|也许|或许|大概|估计|只是|"
    r"上次|之前已|曾经|昨天|上周|以前|当时|有时|部分|一半|大多|多数|"
    r"默认|通常|一般|每次|每条|总是|支持|负责|规定|要求|控制|系统|平台|看板|徽章|调度器|字段|按钮|页面显示|标签|界面|表单|弹窗|写着|标着|表示已|"
    r"说(?!明|的)|被|看到.{0,24}就|(?:现在|先|我|再|还在|继续)等|(?<!次)就(?:是|全部|都|能|可以)?\s?$|就是|标成|标记成|像是|只按|只在|能先|可以先|声称|反馈|被标记|标记为|通知我|只做了语法检查|语法检查|会(?:显示|提示|打印|输出|告诉你)")
ZH_ADJ = re.compile(r"(?:不|(?<![开体聚机学协])会|将|(?<![主需只想还])要|(?<![功性可智])能够?|再|才|被|想|说明|意味着|代表|里写的?|上写的?)\s?$")
ZH_AFTER = re.compile(r"\s?(?:了?\s?(?:吗|么|呢|没有?\s?$|什么|哪些|哪里|多少)|回我|告诉我|跟我说|叫我|通知我|发我|还是不行|也不行|还不行|(?:以|之)?后|之?前|时候?|的(?!话)|才|再(?!看|查)|就|率|与否|不等于|不代表|不意味|只是|是因为|事件|次数)")
EN_VETO = re.compile(
    r"\b(?:not|never|no|none|nothing|nobody|neither|nor|cannot|without|hardly|barely|unable)\b|n't\b"
    r"|\b(?:fail(?:s|ed)?|refus(?:es|ed)|going|about|have|has|had|trying|supposed|required|ought) to\b"
    r"|\b(?:will|shall|gonna|would|could|might|may|must|should|need|needs|want|wants|intend|intends|goal|aim|todo|hope|hopes)\b|\b(?:plan|plans|planned|planning) to\b|\bthe plan is\b"
    r"|'ll\b|\bcan\b(?! confirm)|\blet me\b|\blet's\b|\blets\b"
    r"|\b(?:if|unless|once|when|whenever|until|till|whether|lest|assuming|assume|provided|suppose|supposing|imagine|even though|in case|as soon as|how many|how much|to see)\b"
    r"|\b(?:looks?|looked|seems?|seemed|appears?|appeared|maybe|perhaps|probably|likely|apparently|presumably|supposedly|allegedly)\b"
    r"|\b(?:because|since|due to|is that|the reason)\b"
    r"|\b(?:claims?|claimed|tells?|told|mentioned|mentions|thinks?|thought|believes?|believed|assumes?|assumed|expects?|expected|hoped|insists?|insisted|asked|asks|wrote|writes)\b"
    r"|(?<!i )(?<!we )\bonly\b|\b(?:half|some|few|several|most|many)\b"
    r"|\b(?:dashboard|badge|toast|banner|widget|progress bar|status page|calendar|gate|the tool|this tool|branch protection|like this)\b"
    r"|\b(?:to|be|being)\s*$"
    r"|(?:^|[,;] ?)you\b|\byou(?: should| will| can| could| may| might| need| must| would|'ll)\b"
    r"|^(?:please |now )?(?:check|ensure|make sure|be sure|confirm|verify|see|wait|remember|validate|go ahead|don't forget)\b"
    r"|^(?:please |now )?(?:run|try|test(?! suite)|use|set|rename|merge(?! conflict)|add|save|send|deploy|push|commit|fix|install|update|create|open|click|press|keep|look|read)\b\s+\S")
REPORTED = re.compile(r"\b(?:say|says|said|reports|reported|shows|showed|lists|displays|prints|logs)\b")
TOOL_SUBJECT = re.compile(r"(?:^|\s)(?:the )?(?:output|run|log|summary|result|xtestx|xlintx|xbuildx|pytest|jest|vitest|mocha|ruff|mypy|pyright|eslint|tsc|clippy|flake8|pylint|shellcheck|cargo|go|npm|ci)\s*$")
AFTER = re.compile(r"\b(?:after|before)\b")
AFTER_PHRASE = re.compile(r"\b(?:after|before) (?:(?:the|this|that|my|these|our) (?:\w{1,30} )?(?:change|changes|fix|refactor|edit|edits|update|upgrade|patch|rebase|merge|migration|rewrite|cleanup)\b|\w{1,30}ing\b|(?:i|we) \w{1,30}ed\b)")
QUESTION_START = re.compile(r"(?:is|are|was|were|did|does|do|has|have|had(?! a look)|can(?!')|could|should|would|will|shall|am|what's|what|where|why|how|who)\b")
LEADING_CONDITION = re.compile(r"(?:if|once|when|whenever|after|as soon as|assuming|provided|unless|until|before|even if|suppose|per|according to)\b|如果|要是|假如|假设|倘若|万一|一旦|只要|只有|除非|就算|即使|即便|哪怕|等到")
PAST_FIRST_PERSON = re.compile(r"(?:once|after|when|before) (?:i|we)\b")
OTHER_SUBJECT = re.compile(r"(?:the|a|an|this|that|these|those|he|she|they|you|someone|somebody|everyone|nobody|his|her|their|your)\b|(?!i\b|we\b|also\b|then\b|just\b|now\b)[a-z][\w-]{0,30} [a-z]{1,30}ed\b")


def _before_vetoed(prefix: str) -> bool:
    """Does what stands before a result word in its clause keep that word from being a claim?"""
    if not prefix:
        return False
    if EN_VETO.search(prefix) or (not prefix.isascii() and ZH_VETO.search(prefix)):
        return True
    m = REPORTED.search(prefix)
    if m and m.start() > 0 and not TOOL_SUBJECT.search(prefix[:m.start()]):
        return True
    return bool(AFTER.search(prefix) and not AFTER_PHRASE.search(prefix))


# ------------------------------------------------------------------ mood: what follows the result word
SUFFIX_VETO = re.compile(r"\b(?:because|even though|as you|too early|too late|too soon|prematurely|old|before|not|isn't|doesn't|don't|won't|for the wrong reason|by accident|by mistake|accidentally|twice|half the time|sometimes|intermittently|doesn't mean|does not mean|don't mean|if|unless|while|locally and fail|a million times|\d{1,9} times|on (?:her|his|their) (?:laptop|machine|branch)|on every|on each|every (?:time|minute|hour|day|night|week|month|keystroke|request|commit|push|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|over http|stale|wrong|malformed)\b")
BY_AGENT = re.compile(r"^(?: [\w.~/#-]{1,40}){0,3}? (?:by|via) (?!\w{1,30}ing\b)")
ELSEWHERE_FIX = re.compile(r"\b(?:upstream|in (?:v?\d|version|release|python|node|chrome|#\d|the (?:next|last|latest|previous|new|current)\b|an? (?:earlier|later|newer|previous|recent)\b))")
EMPTY_OBJECT = re.compile(r" (?:nothing|none|no \w)")
ADJECTIVE_USE = re.compile(r" (?!the\b|a\b|an\b|it\b|this\b|that\b|these\b|those\b|my\b|our\b|your\b|all\b|both\b|to\b|as\b|at\b|in\b|on\b|by\b|for\b|from\b|with\b|and\b|\d)[\w-]{1,30}(?: [\w-]{1,30})? (?:is|are|was|were|must|can|will|should|get|gets|may|might|need|needs|have|has)\b")
ADJECTIVE_PLURAL = re.compile(r" (?!tests\b|bugs\b)[a-z-]{2,30}s (?!to\b|in\b|on\b|at\b|for\b|from\b|via\b|into\b|with\b|as\b|and\b|or\b|by\b|under\b|using\b|now\b|too\b|again\b|here\b|there\b|today\b|already\b|first\b|that\b|which\b|who\b|where\b|when\b|while\b|after\b|before\b|because\b|but\b|across\b|everywhere\b|locally\b|\w{1,30}ly\b|\w{1,30}ed\b)[a-z]{2,}")
WHICH_TAIL = re.compile(r"which\b(?! (?:means|confirms|should|lets|closes|resolves|fixes|is (?:good|great|what)))")
PARTIAL = re.compile(r"\b[1-9]\d{0,6} (?:\w{1,20} )?(?:tests? )?(?:failed|failing|fail)\b|(?<!\d)[1-9]\d{0,6} ?个?(?:用例|测试)?(?:失败|没过|未通过)|其余失败|\bstill fail|\bbut (?:now |still )?(?:fail|crash|error|break)|\bbut .{0,30}\b(?:fail|fails|failed|failing|crashes|errors?|broken)\b|但.{0,12}(?:报错|失败|出错|不过|错误)")
ZH_BUG_TAIL = re.compile(r"两次|多次|重复|导致|造成|错误|旧表|损坏")
BAD_CONSEQUENCE = re.compile(r"(?<![不没无])(?:报错|失败|崩|丢|重复|闪烁|翻倍|泄[漏露]|溢出|黑屏|超时)")
PARTIAL_CATEGORIES = frozenset({"tests_pass", "checks_pass", "build_ok"})
UNVERIFIED_TAIL = re.compile(r"(?:haven't|hasn't|have not|has not|didn't|did not|not|never|without|can't|cannot)(?: (?:yet|actually|been|really|fully)){0,3} (?:run|ran|running|tested|test|verified|verify|confirm|confirmed|checked|exercised)\b"
                             r"|(?:没有?|还没|尚未|未|并未|不能说|不能确认|无法确认)\s?(?:跑|运行|执行|验证|测试|测过|确认|实测|自测|说)")
COVERS_FIX = frozenset({"tests_pass", "checks_pass"})   # their evidence is a subset of what backs "fixed"
SIGN_OFF = re.compile(r"(?:all )?done|all good|all set|all clear|good to go|you're good to go|we're good|nailed it|took care of it|taken care of|wrapped up|finished|completed|好了|可以了|现在可以了|ok\s?了|搞定了?|都搞定了?|全部搞定|搞完了|弄完了|完事了|齐活|妥了|收工|没事了")

ADVERBS = frozenset("also just now then finally successfully already and so ok okay yes yep great good nice first second third next lastly manually quickly locally all both again actually simply double triple cross smoke 已 已经 都 也 刚 刚刚 现在 全部 本地".split())
AUX = frozenset("is are was were got get gets getting".split())
FIRST_PERSON = frozenset({"i", "we", "i've", "we've", "i'd", "we'd", "我", "我们"})
PRONOUNS = frozenset("it this that these those everything they all both".split())
CONTRACTED = {"it's": "it", "that's": "that", "this's": "this", "everything's": "everything", "they're": "they", "what's": "what"}
NOT_A_HEAD = frozenset("the a an this that these those my our your all both it they everything now just".split())
HOW_IT_WORKS = re.compile(r" (?:over|behind|via|using|through|with|across|under|inside|per|in (?:a|an|the (?:\w{1,20} )?(?:cookie|variable|database|cache|session|memory|config|repo)|memory|redis|\w{1,20}db)\b|\w{1,30}ly\b)")
PAST_AUX = frozenset({"was", "were", "been", "got"})
MACHINERY = frozenset("thread pod process row offset packet frame token cookie session request response event header byte buffer socket query transaction record key value element component template function method class object variable button".split())   # what a bug story is about
SENTENCE_START = frozenset("the a an this that these those his her their my our your some any who which what when where how why if".split())
ACTORS = frozenset("alice bob carol dave dana eve frank grace heidi ivan judy mallory oscar peggy trudy victor walter wendy tom jack mike jane john sam sarah mary peter paul david james emma lucy amy anna kate lisa chris alex ben dan kevin jason eric ryan nick steve tony he she they you someone somebody everyone nobody user users customer customers client clients server browser bot bots ci qa ops sre team admin maintainer maintainers vendor upstream github stripe kubernetes k8s renovate dependabot jenkins who which".split())
TELEGRAM_TAIL = re.compile(r"(?: (?:successfully|now|locally|again|ok|fine))?(?: (?:to|on|in|at|for|as|into|with|via|by) (?:[\w./~:#-]{1,120} ?){1,5})?")
ACTIVE_PRONOUNS = frozenset("it this that these those they".split())   # "They fixed it": a subject, not an ellipsis like "Bug fixed"
GENERIC_START = frozenset("each every any only some new generated most many other old".split())
WORK_PLURALS = frozenset("changes commits fixes edits updates patches bugs tests branches results".split())
DETERMINERS = frozenset("the these those all both my our everything they".split())

SUBJECTS = {
    "pushed": "branch branches commit commits change changes fix fixes code tag tags pr work patch notebook notebooks version release edit edits update updates head main master feature kernel",
    "committed": "change changes fix fixes code work patch file files edit edits update updates commit commits",
    "fixed": "bug bugs issue issues problem problems error errors crash crashes leak leaks typo typos regression regressions failure failures race deadlock exception exceptions warning warnings test tests results flake hang timeout mismatch defect glitch fault vulnerability cve conflict conflicts",
    "rendered": "video videos clip clips mp4 film intro outro scene scenes animation frames version cut output movie render",
    "deployed": "app service site fix change changes version release build update api backend frontend server",
    "downloaded": "dataset datasets data file files model models weights image images artifact artifacts checkpoint archive zip pdf repo repository",
    "saved": "file files report reports results result csv pdf doc docs document notes summary changes",
    "scheduled": "job jobs task tasks cron run runs reminder reminders backup backups",
    "sent": "email emails mail message messages reply replies comment comments report invite notification file",
    "verified": "fix change changes output result results behavior behaviour claim flow",
    "checked": "",
}
SUBJECTS = {k: frozenset(v.split()) | PRONOUNS for k, v in SUBJECTS.items()}


def _telegram(subject: list, tail: str) -> bool:
    """"Config saved.", "Backup saved to backup.tar.gz.": a bare noun and a participle report a result. An article or a person makes it a sentence
    about something else, and so does a tail that goes on after its place ("Apps deployed on Fly can use the volume")."""
    return len(subject) <= 3 and subject[0] not in SENTENCE_START and not ACTORS.intersection(subject) and len(tail.split()) <= 4


def _passive_ok(category: str, toks: list, tail: str) -> bool:
    """`toks` stands before a participle and is not the speaker: is it a subject about the work, and is this a report and not a general truth?"""
    allow = SUBJECTS.get(category)
    if allow is None:
        return False
    last = toks[-1]
    aux = None
    if last in AUX:
        aux, subject = last, toks[:-1]
    elif last == "been" and len(toks) >= 2 and toks[-2] in ("has", "have", "had"):
        aux, subject = "been", toks[:-2]
    elif last == "been" and len(toks) >= 2 and toks[-2] in CONTRACTED:
        aux, subject = "been", toks[:-2] + [CONTRACTED[toks[-2]]]
    elif last in CONTRACTED:
        aux, subject = "is", toks[:-1] + [CONTRACTED[last]]
    else:
        subject = toks
    if aux in ("get", "gets", "getting"):
        return False
    if not subject:
        return aux is not None
    if subject[0] in GENERIC_START and (aux is not None or subject[0] in ("each", "every", "any", "only", "some")):
        return False
    if aux is None:
        if subject[-1] in ACTIVE_PRONOUNS or len(subject) > 5 or TELEGRAM_TAIL.fullmatch(tail) is None:
            return False   # "They fixed it", "The cron scheduled a duplicate run": a subject and an object, not a telegram
        if subject[-1].strip("-") not in allow and not _telegram(subject, tail):
            return False
    else:
        nouns = [t for t in subject if t not in NOT_A_HEAD]
        if nouns and not any(t in allow for t in nouns) and not (aux in PAST_AUX and category != "verified" and not ACTORS.intersection(nouns) and not MACHINERY.intersection(nouns)):
            return False   # "This function is saved in utils.py": "this" only points at the noun
        if aux == "are" and subject[0] not in DETERMINERS and subject[-1] not in WORK_PLURALS:
            return False   # "Events are pushed to the queue", "Files are saved to ~/.config": how things work, not what was done
        if aux in ("is", "are") and HOW_IT_WORKS.match(tail):
            return False   # "The service is deployed behind nginx", "The result is saved in a variable"
    if SUFFIX_VETO.search(tail) or BY_AGENT.match(tail):
        return False
    return not (category == "fixed" and ELSEWHERE_FIX.search(tail))


def _verb_ok(category: str, text: str, m, passive: bool, blocked_left: bool) -> bool:
    """A verb in the past: fine bare or after I/we, and, when `passive`, after a subject about the work."""
    prefix, tail = text[:m.start()], text[m.end():]
    if _before_vetoed(prefix) or (not prefix.isascii() and ZH_ACTOR.search(prefix) is not None):
        return False
    toks = prefix.split()
    while toks and toks[-1] in ADVERBS:
        toks.pop()
    if not toks:
        return not blocked_left and not ADJECTIVE_USE.match(tail) and not ADJECTIVE_PLURAL.match(tail) and not EMPTY_OBJECT.match(tail)
    if toks[-1] in FIRST_PERSON or (toks[-1] in ("have", "had") and len(toks) >= 2 and toks[-2] in ("i", "we")):
        return not EMPTY_OBJECT.match(tail)
    return passive and _passive_ok(category, toks, tail)


# ------------------------------------------------------------------ the lexicon
ACTIVE, VERB, STATUS, WEAK, WHOLE, ZH, ZH_BARE, ZH_WHOLE, ZH_SUBJECT = "active", "verb", "status", "weak", "whole", "zh", "zh_bare", "zh_whole", "zh_subject"
_GAP = r"(?:'s|'re)?(?: (?:all|now|still|again|also|both|just|already|fully|finally|successfully|are|is|was|were|have|has|had|been|do|did|does|ran|run|went|came back|come back)){0,4}"
_PASS_GUARD = (r"(?! (?:xcodex|xquotex|a|an|the|its|this|that|my|our|your|each|every|some|any|rate|\w{1,30} (?:to|into|through|as|along|down))\b)"
               r"(?! \d[\d.]{0,12} ?(?:%|for|as|to|into|instead)\b)(?! (?:whole|raw|plain|real|negative|positive|fractional|decimal)\b)"
               r"(?! (?:percent(?:age)?s?|values?|numbers?|arguments?|args|strings?|integers?|ints|floats?|decimals?|fractions?|inputs?|params|parameters?|objects?|dicts?|lists?|arrays?|mocks?|fixtures?|data|none|null|true|false|kwargs|cents|prices?|amounts?)\b)")
_PASS = r"pass(?:es|ed|ing)?\b" + _PASS_GUARD
_OK = r"(?:green|clean(?:ly)?|ok|okay|good|fine|happy|succeed(?:s|ed)?|successful|works?|working|went through)\b"
_T_TESTS = r"(?:tests?|test suite|test cases?|test run|suite|specs?|pytest|py\.test|jest|vitest|mocha|playwright|cypress|phpunit|junit|ctest|nextest|npm test|npm run test|yarn test|pnpm test|go test(?: [\w./-]{1,40})?|cargo test|rspec|unittest|xtestx|test_\w{1,60}|[\w./-]{1,60}_test\.\w{1,5}|tests?/[\w./-]{1,60})"
_LINTERS = r"(?:lints?|lint(?:ing|er)|ruff(?: check)?|mypy|pyright|tsc|eslint|clippy|go vet|shellcheck|flake8|pylint|prettier(?: check)?|biome|golangci-lint|pre-commit|xlintx)"
_T_CHECKS = rf"(?:{_LINTERS}|cargo (?:check|clippy)|ci|pipeline|checks?|types?|type ?checkers?|type ?checks?|type-?check(?:ing)?|typecheck(?:ing)?|static analysis|format(?:ting)?(?: check)?|hyperframes check)"
_T_BUILD = r"(?:(?:[\w.-]{1,20} )?builds?|npm run build|xbuildx|compil(?:e|ation|er))"
_T_RENDER = r"(?:re-?render(?:ing)?|render(?:ing)?|hyperframes render)"
_DONE = r"(?:complete[d]?|finished|done|ok|okay|succeeded|successful)\b"
_EXT = r"(?:md|txt|json|jsonl|csv|tsv|png|jpe?g|gif|webp|svg|mp4|mov|mp3|wav|pdf|docx?|xlsx?|pptx?|html?|py|js|ts|yaml|yml|toml|tex|srt|zip|gz|ipynb|log)"
_FILE = rf"(?:xfilex|[\w./~-]{{1,120}}\.{_EXT}\b|[\w.~-]{{1,60}}/[\w./~-]{{0,120}})"
_EXT_FILE = rf"(?:xfilex|[\w./~一-鿿-]{{1,120}}\.{_EXT}\b)"
_ZG = r"[\s\da-z个项条例组都全部均也已经仍然还是现在第一次就共跑完了遍结果]{0,14}?"
_ZEND = r"(?=\s?(?:了|$))"
_Z_DONE = r"(?:完成|完毕|成功|好了|好啦|完了|结束)"   # what any step can have reached
_Z_PASS = r"(?:通过|全过|全绿|全部通过|绿了|绿灯|全绿灯|没问题|没毛病|没挂|ok|okay|全\s?ok|全\s?pass|all\s?pass|全部\s?pass|pass\s?了|过了|跑过了|没有失败|无失败)"
_Z_T_TESTS = r"(?:测试|单测|单元测试|集成测试|回归测试|回归|用例|xtestx|pytest|jest|vitest|mocha|playwright|cypress|npm test|go test|cargo test)"
_Z_T_CHECKS = rf"(?:{_LINTERS}|cargo (?:check|clippy)|ci|门禁|流水线|类型检查|代码检查|检查结果|检查(?!过了)|hyperframes check)"
_Z_T_BUILD = r"(?:构建|编译|打包|build|npm run build|cargo build|xbuildx)"
_BUGGY = r"(?:bug|问题|崩溃|错误|报错|漏洞|异常|隐患|故障|缺陷|冲突|警告|死锁|泄漏|超时|issue)"
_DOCS = rf"(?:官方)?(?:文档|代码|日志|配置|源码|手册|说明|注释|changelog|readme|release notes|{_FILE})"


def _r(*alts: str):
    return re.compile("|".join(alts))


LEXICON = {
    "tests_pass": [
        (_r(rf"\b{_T_TESTS}{_GAP} (?:{_PASS}|{_OK})"), STATUS),
        (_r(r"\b\d{1,7}(?:/\d{1,7})? (?:of \d{1,7} )?(?:[a-z]{1,20} )?(?:tests? )?pass(?:ed|ing)\b", r"\bpassed (?:all )?\d{1,7}(?:/\d{1,7})? (?:\w{1,20} )?tests?\b",
            r"\bthey (?:all |now |still ){0,2}pass(?:ed)?\b", r"\ball of them pass(?:ed)?\b", r"\ball \d{1,7} pass(?:ed)?\b", r"\bboth pass(?:ed)?\b", r"\beverything (?:now |still )?pass(?:es|ed)\b",
            r"\beverything(?:'s| is) (?:now )?green\b", r"\bpass(?:es|ed)? (?:all|the whole|the full|the entire|its|every)(?: \d{1,7}| the)?(?: \w{1,20})? (?:tests?|suite|test suite)\b",
            r"\b(?:clean|green) (?:test )?run\b", r"\bfull suite green\b", r"\bgreen across the board\b", r"\b\d{1,7}/\d{1,7} (?:green|ok|okay)\b", r"\beverything(?:'s| is)?(?: now)? (?:passing|green)\b", r"\b100% (?:pass(?:ing|ed)?|green)\b", rf"\bpass(?:es|ed)? (?:the |all )?{_T_TESTS}\b"), STATUS),
        (_r(r"\b(?:no|0|zero) (?:test )?fail(?:ures?|ed)\b", r"\bno (?:failing )?tests? fail(?:ed|ing|ures?)?\b", r"\bno failing tests?\b"), WEAK),
        (re.compile(r"(?:all green|all passing|all pass(?:ed)?|still green)$"), WHOLE),
        (_r(rf"{_Z_T_TESTS}{_ZG}({_Z_PASS}{_ZEND})", r"\d{1,7}\s?/\s?\d{1,7}\s?(通过)" + _ZEND), ZH),
        (re.compile(r"(?:全绿|全绿灯|绿灯|都过了|全过了|都通过了?|全\s?pass|都\s?pass\s?了|全部\s?pass\s?了|pass\s?了|(?:一个)?都没挂)$"), ZH_WHOLE),
    ],
    "checks_pass": [
        (_r(rf"\b{_T_CHECKS}{_GAP} (?:{_PASS}|{_OK})", rf"\b{_T_CHECKS} no (?:issues?|errors?)\b", rf"\b{_LINTERS} (?:reports?|found|finds|shows?) (?:0|no|zero|nothing)\b", rf"\bpass(?:es|ed)? (?:the |all )?{_T_CHECKS}\b"), STATUS),
        (re.compile(r"(?:lint[- ]free|type-?checks|green ci|ci green)$"), WHOLE),
        (_r(r"\b0 (?:\w{1,20} )?(?:errors?|warnings?)\b", rf"\b(?:no|zero) (?:{_LINTERS}|type) (?:errors?|issues?|warnings?)\b", r"^no issues(?: found)?\b", r"^(?:zero|no) (?:errors?|warnings?)$"), STATUS),
        (_r(rf"{_Z_T_CHECKS}{_ZG}((?:{_Z_PASS}|干净|无报错|没报错|没有报错|无错误)" + _ZEND + ")", rf"没有\s?(?:{_LINTERS}|类型)\s?报错", r"\b0\s?个?错误"), ZH),
        (re.compile(r"全部通过了?$"), ZH_WHOLE),
    ],
    "build_ok": [
        (_r(rf"\b{_T_BUILD}{_GAP} (?:{_PASS}|{_OK}|complete[d]?\b|finished\b)", r"\bno (?:build|compile|compilation) errors?\b", r"\b(?:it|this|the (?:image|package|project|app|code|crate|bundle)|docker image|image|package|project|app|bundle)(?: now)? builds\b",
            r"\bbuilt (?:successfully|cleanly|fine|ok)\b", r"\bbuilt (?:the )?(?:\w{1,20} )?(?:bundle|image|package|artifact|binary|container)\b", r"\bcompil(?:es|ed) (?:clean|cleanly|fine|ok|successfully|without \w{1,20})", r"\b(?:compiles|builds)(?: now| again)?$", r"\bcompiled [\w ]{1,30} without errors\b"), STATUS),
        (re.compile(r"(?:compiles(?: now| again)?|compiled|built|builds(?: \w{1,20})?|(?:green|clean|successful) build)$"), WHOLE),
        (_r(rf"{_Z_T_BUILD}{_ZG}((?:{_Z_PASS}|{_Z_DONE}|无错误|无报错|没报错|没有报错|跑通了?)" + _ZEND + ")", r"能\s?(?:编译|构建|build|跑\s?build)\s?了", r"已完成\s?(?:编译|构建|打包)", r"编(?:译)?过了"), ZH),
    ],
    "rendered": [
        (_r(r"\b(?:re-?)?rendered\b(?! with\b)"), VERB),
        (_r(r"\bencoded (?:the )?(?:video|clip|mp4|film|movie)\b"), ACTIVE),
        (_r(rf"\b{_T_RENDER}{_GAP} {_DONE}(?! (?:on|by|in|at|before)\b)", r"\b(?:done|finished) rendering\b", r"\bfinished (?:the )?render\b", r"\b(?:mp4|video|clip|final cut|output video|film|movie)(?: is| has)? (?:now )?(?:ready|done|finished)\b", r"\bffmpeg (?:has )?(?:finished|exported|rendered|encoded)\b"), STATUS),
        (_r(rf"(?:渲染|渲|重渲|重新渲染|render|hyperframes render)\s?(?:已经?|都|也|全部)?\s?((?:{_Z_DONE}|出来了|跑完了?|ok)" + _ZEND + ")", r"已经?(?:重新)?渲染", r"已完成\s?渲染", r"成片(?:已出|出来了|好了|做好了)", r"(?:视频|片子|成片)(?:已经?)?\s?(?:好了|做好了|生成了|已生成|出来了|ok)", r"成片(?:渲染)?完成", r"出片了", r"视频已生成"), ZH),
    ],
    "pushed": [
        (_r(r"\b(?:force[- ]?|git )?pushed\b(?! (?:back|down|through|out|aside|into|onto|over|forward|around|away|up against|the button|a button|button|the limit|the limits|the envelope)\b)"), VERB),
        (_r(r"\bsubmitted(?: (?:to \w{1,30}|the (?:notebook|kernel|prediction|entry|run)s?))?$", r"\blanded (?:on|in) \S{1,30}", r"\blanded the (?:fix|change|patch|pr)\b", r"\bsynced to (?:origin|the remote|remote|github|gitlab)\b"), ACTIVE),
        (_r(r"\b(?:it|this|branch|the branch|branch [\w./-]{1,40}|changes|the changes|everything|fix|the fix|commits?|the commits?)(?:'s| is| are)(?: now)? (?:up )?on (?:origin|the remote|remote|github|gitlab)\b", rf"\b(?:git )?push(?:ing)?{_GAP} (?:{_DONE}|went through)", r"^up on (?:origin|github|gitlab|the remote)\b", r"\b(?:changes|commits?|branch|fix|everything)(?:'s| is| are) up$"), STATUS),
        (_r(r"已经?推送", r"已完成\s?推送", rf"推送\s?(?:{_Z_DONE}|到了)", r"推送到\s?\S{1,30}\s?了", rf"push\s?(?:了|上去了|{_Z_DONE})", r"已\s?push", r"已经\s?push", r"已推上去", r"推上去了", r"推到远[端程]了", r"推到\s?\S{1,20}\s?了", r"已经?推到\s?\S{1,20}", r"推[完好]了", r"已\s?pushed", r"(?:代码|分支|改动|提交)(?:已经?)?上去了", r"强推(?:了|完成|好了)", r"已强推", r"已提交到\s?kaggle", r"提交到\s?kaggle\s?了", r"(?:代码|分支|改动|提交)(?:已经?)?传上去了", r"同步到(?:远端|远程|origin)了?"), ZH),
        (re.compile(r"(?:推了|已推)$"), ZH_WHOLE),
    ],
    "committed": [
        (_r(r"\bcommitted\b(?! to (?:memory|the (?:plan|idea|goal|approach|team|project|cause|database)|a |an |this |that |our |my |your |doing|\w{1,30}ing\b)|\bcommitted to the \w{1,30} in\b)", r"\bchecked in\b"), VERB),
        (_r(r"\b(?:made|created) (?:a |an |the )?(?:commit|tag)\b", r"\b(?:commit|tag)(?: [\w.-]{1,40})? created\b", r"\btagged\b(?= the\b| v?\d| it\b|$)", rf"\b(?:git )?commit(?:ting)?{_GAP} {_DONE}", r"\bamended (?:the |my )?commit\b", r"\bcommit(?:'s| is) in$"), STATUS),
        (_r(r"已经?提交(?=\s?(?:$|了|到(?!\s?kaggle)|commit|代码|改动|修改|变更|热修|补丁|迁移|脚本|配置|文档|\d{1,5}\s?个(?:文件|提交|改动)|[0-9a-f]{6,40}))", rf"提交\s?{_Z_DONE}", r"提交到\s?(?:main|master|仓库|git|分支|主分支|远端)\S{0,10}\s?了"), ZH_SUBJECT),
        (_r(r"提交了\s?commit", r"提交过了", r"已完成\s?提交", r"(?:tag|标签)\s?打了", r"已\s?commit", r"已经\s?commit", rf"commit\s?(?:了|{_Z_DONE})", r"已打\s?\S{0,12}\s?(?:tag|标签)", r"打\s?(?:tag|标签)\s?了", r"打(?:好了?|了)\s?(?:tag|标签)", r"打好\s?(?:tag|标签)了?", r"(?:tag|标签)\s?(?:已打|打好了)", r"提交\s?\w{4,40}\s?已创建", r"把.{0,30}提交了", r"(?:改动|代码|文件|修改)(?:已经?)?提交了"), ZH),
        (re.compile(r"提交了$"), ZH_WHOLE),
    ],
    "fixed": [
        (_r(r"\bfixed\b(?![-.]\w)(?! (?:at|bed|point|width|size|length|rate|cost|income|price|position|number|value|set|interval|schedule|header|layout|effect|asset|term|costs|prices|rates|assets)\b)", r"\b(?:resolved|solved|patched|repaired|corrected|squashed|addressed)\b"), VERB),
        (_r(r"\bworks? (?:now|again)\b", r"\bworking (?:now|again)\b", r"\bnow (?:it )?works\b", r"\bnow working\b", r"\beverything (?:now )?works\b", r"\bit (?:now )?works$", r"^(?:the )?(?!builds?\b|tests?\b|lint\b|ci\b|checks?\b)[\w-]{2,20} works(?: now| again)?$", r"\bthe fix works\b", r"\b(?:everything|it|that)(?:'s| is)(?: now)? working\b", r"\bdone with the fix\b", r"\b(?:that|this) fixed it\b",
            r"\bno more (?:\w{1,20} )?(?:crash|error|failure|exception|warning|bug|issue|leak|hang|timeout)(?:e?s)?\b", r"\b(?:crash|bug|error|failure|exception|issue|problem|leak|hang|warning)(?:e?s)?(?: (?:is|are|has been|have been))? gone\b", r"\b(?:that|this) (?:fixed|sorted|solved|resolved) it\b", r"\bcleared the (?:blocker|error|issue|bug|conflict)\b",
            r"\bno longer (?:crash|fail|error|hang|throw|leak|reproduce)\w{0,4}\b", r"\b(?:doesn't|does not|don't|won't) (?:crash|fail|hang|error|throw|leak|flake)\w{0,4} any ?more\b", r"\bcan(?:'t|not) reproduce(?: it| the \w{1,20})? any ?more\b",
            r"\bworks? (?:fine|great|as expected|correctly|properly)$", r"\bworking as expected$", r"\b(?:it|everything)(?:'s| is) all working\b"), STATUS),
        (re.compile(r"(?:(?:all |that's |it's |this is |that is |it is )?done|sorted(?: it| out| now)?|(?:that's |it's )?handled|all good|all set|all clear|good to go|you're good to go|good to merge|we're good|nailed it|took care of it|taken care of|back to normal|(?:it's |it is |we're )?up-and-running|wrapped up|finished|completed|that did it|works|working)$"), WHOLE),
        (_r(r"fix\s?(?:好了|完了)", r"不(?:再)?(?:闪退|卡|挂|超时|出错)了", rf"{_BUGGY}\s?(?:已经?|都)?\s?(?:清了|清零|干掉了)", r"已经?(?:全部|都)?修复", r"修复了", rf"修复\s?{_Z_DONE}", r"已经?修好", r"修好[了啦]", r"修完了", rf"修了(?:{_BUGGY}.{{0,8}})?$", rf"修掉了(?:.{{0,12}}{_BUGGY}.{{0,4}})?$", r"已经?解决", r"解决好了", rf"{_BUGGY}\s?(?:已经?(?:解决|修复)了?|(?:解决|修复)了)", r"已?搞定[了啦]?", r"都搞定", r"全部搞定", r"搞好了", r"弄好了", rf"{_BUGGY}\s?(?:已经?)?处理(?:好|完)了", r"fix(?:ed)?\s?了", r"已\s?fix", r"不报错了", r"不再报错了?", r"不崩(?:溃)?了", r"不再崩溃了?", r"能用了", r"恢复正常了", r"正常了$", r"已完成\s?修复", rf"{_BUGGY}\s?(?:已经?|都)?\s?(?:消失了|没了)"), ZH),
        (re.compile(r"(?:好了|可以了|现在可以了|现在好了|ok\s?了|已修|能跑了|现在能跑了|干掉了|摆平了|整好了|搞完了|弄完了|处理了|处理好了|处理完了|完事了|齐活|妥了|收工|没事了|好使了|通了|打通了)$"), ZH_WHOLE),
        (re.compile(r"跑起来了"), ZH_SUBJECT),
        (re.compile(r"解决了$"), ZH_WHOLE),
    ],
    "sent": [
        (_r(r"\bsent\b(?! back\b)", r"\bdelivered\b"), VERB),
        (_r(r"\b(?:email|mail|message|report|invite|reply)s? went out\b"), STATUS),
        (_r(r"\bposted\b"), VERB),
        (_r(r"\b(?:e-?mailed|mailed|replied|commented|messaged|dm'?d|dmed|pinged|notified|forwarded)\b", r"\b(?:filed|opened) (?:an?|the) (?:\w{1,20} )?(?:issue|ticket|bug|pr|pull request)\b", r"\bleft (?:a|the) (?:\w{1,20} )?(?:review|comment)\b", r"\bshared (?:it |the \w{1,20} )?with\b", r"\bfired off\b", r"\btold (?!me\b|us\b|you\b)\w", r"\blooped in\b", r"\bcc'?d\b", r"\bdropped (?:a|the) (?:note|message|line|comment)\b"), ACTIVE),
        (_r(r"已发送", r"发送(?:成功|了|完成)", r"发好了", r"发完了", r"发出了", r"回复好了", r"回过了", r"已私信", r"私信了", r"抄送了", r"通知过了", r"已发出", r"回复过了", r"已经?发给(?!.{0,12}的)", r"发给.{1,20}了", r"(?:图|截图|文件|对比图|视频|成片|抽帧图?|消息|邮件|评论|发票|报告|通知|账单)\s?我?(?:已经?)?发了?$", r"已发$", r"已发(?![现生布送出版给到表起内的])[\u4e00-\u9fff]{2,6}$", r"我(?:已经?)?回复(?:他|她|你|了)", r"回复(?:他|她|你)了", r"已评论", r"已留言", r"已通知", r"通知到了", r"通知了", r"通知(?:他|她|你)了", r"转发了", r"已转发", r"转发给.{1,20}了", r"已发邮件", r"发邮件给.{1,20}了", r"把.{0,20}发给了", r"已告知", r"已转告", r"已抄送", r"发(?:他|她|你)了"), ZH),
        (_r(r"已回复", r"已经?发到(?!对话|这里|你这)", r"发到(?!对话|这里).{1,20}了", r"发过去了", r"发出去了"), ZH_SUBJECT),
        (re.compile(r"(?:发了|回了|已发|回复了|评论了|已转|转了)$"), ZH_WHOLE),
    ],
    "deployed": [
        (_r(r"\b(?:re)?deployed\b(?! (?:engineers?|engineering|models?|versions?|apps?|services?|systems?|roles?|positions?|instances?|environments?|code|state|contracts?|artifacts?|builds?)\b)", r"\bwent live\b"), VERB),
        (_r(r"\bshipped\b", r"\breleased\b(?! (?:the|a) (?:lock|mutex|semaphore|memory|handle|resource|connection)\b)", r"\bpublished\b(?= to\b| v?\d| the\b| it\b| on\b|$)"), VERB),
        (_r(r"\brolled (?:it |this |that )?out\b", r"\bpushed to (?:prod|production)\b", r"^live at\b", r"\bpromoted to (?:prod|production|staging)\b", r"\buploaded to (?:pypi|npm|the registry)\b", r"\bcut (?:a|the) release\b", r"\brolled (?:it )?to (?:prod|production|staging)\b"), ACTIVE),
        (_r(rf"\bdeploy(?:ment)?{_GAP} (?:{_DONE}|went through)", r"\b(?:version|v)\s?[\w.]{1,12} is (?:now )?live\b", r"^(?:now )?live (?:on|in) ", r"\bprod(?:uction)?(?: is)? (?:now )?(?:updated|up to date)\b", r"^(?:now )?live(?: now)?$", r"^we're live\b", r"\b(?:it|this|(?:the )?(?!feed\b|connection\b|stream\b|video\b|view\b|chat\b|reload\b|preview\b|data\b|session\b|socket\b|camera\b|server\b|what\b|who\b)[\w-]{2,20})(?:'s| is)(?: now)? live\b", r"\b(?:the )?(?:changes|docs|fixes|updates) are(?: now)? live\b", r"\b(?:now |running )in (?:prod|production)\b", r"\b(?:it's|it is|this is) (?:in|on) (?:prod|production)\b", r"^in prod(?:uction)?(?: now)?$"), STATUS),
        (_r(r"已经?部署", rf"部署\s?(?:{_Z_DONE}|上去了|上了|了$)", r"部署到\s?\S{1,20}\s?了", r"已经?上线(?=\s?(?:$|了|到))", rf"上线\s?(?:{_Z_DONE}|了$)", r"已经?发布(?=\s?(?:$|到|至|在|了|v?\d|热修|补丁|修复|迁移|新版))", r"已完成\s?(?:部署|发布|上线)", rf"发布\s?{_Z_DONE}", r"已经?发版", rf"发版\s?(?:{_Z_DONE}|了$)", r"发布了$", r"上到(?:生产|线上)了?", r"上生产了", r"已上生产", rf"(?:灰度|放量|切流)\s?{_Z_DONE}", r"已全量", r"全量了$", r"发上去了", r"发包了", r"上了生产", r"已上$", r"已经?推到生产", r"推到生产了", r"(?:npm|pypi)\s?包?\s?已发", r"线上(?:已经?)?(?:更新|生效)", r"已上传到?\s?(?:pypi|npm)"), ZH),
    ],
    "downloaded": [
        (_r(r"\b(?:re-?)?downloaded\b", r"\bcloned\b"), VERB),
        (_r(r"\b(?:fetched|grabbed|snagged|pulled|retrieved|got) (?:the |a |an |\d{1,6} )?(?:\w{1,20} )?(?:file|files|dataset|data|model|models|weights|image|images|artifact|artifacts|archive|checkpoint|zip|tarball|dump|backup|logs?|snapshot|database|db)\b", r"\b(?:fetched|grabbed|snagged) (?:it|everything)\b", r"\bpulled (?:it |them )?down\b"), ACTIVE),
        (_r(rf"\bdownload{_GAP} {_DONE}"), STATUS),
        (_r(r"已经?下载", r"已完成\s?下载", rf"下载\s?(?:{_Z_DONE}|到了)", r"下[好完]了", r"(?:下载|clone|克隆|拉|取|抓)\s?下来了", r"拉[好完]了", r"拉下来了", rf"(?:克隆|clone)\s?{_Z_DONE}", r"已\s?(?:克隆|clone)", r"抓下来了", r"下下来了", r"(?:模型|文件|数据集?|权重)已拿到", r"拿到(?:模型|文件|数据集?|权重)了", rf"拉取\s?{_Z_DONE}", r"已拉取"), ZH),
    ],
    "saved": [
        (_r(r"\bsaved\b(?! (?:time|memory|money|bytes|tokens|\d{1,9} ?(?:%|ms|s|kb|mb|gb|lines?|bytes))\b)", r"\bwritten\b(?! (?:by|in)\b)", r"\bexported(?= (?:to|as)\b)"), VERB),
        (_r(r"\bwrote (?:it |them |(?:the |a )?\w{1,20} |\d[\d,]{0,9} \w{1,20} )?to\b", r"\bwrote \d[\d,]{0,9} \w{1,20}\b", r"\bwrote (?:the |a |\d[\d,]{0,9} )?(?:report|file|summary|notes?|doc|document|results?|output|rows|lines|csv|pdf|log)\b", rf"\bwrote {_FILE}", r"\bexported (?:to|as|the|it)\b", rf"\bstored (?:in|at|to) {_FILE}", rf"\b(?:created|generated) {_FILE}", r"\b(?:persisted|dumped) (?:\w{1,20} )?to\b", r"\bwrote (?:it|them) out\b", rf"^put (?:it|them) (?:in|at|into) {_FILE}"), ACTIVE),
        (re.compile(r"(?:persisted)$"), WHOLE),
        (_r(rf"\b(?:output|report|results?|file) (?:is|are) (?:in|at) {_FILE}", r"\boutput (?:saved|written) to\b", rf"\bexport{_GAP} {_DONE}"), STATUS),
        (_r(r"已保存", r"已导出", r"已完成\s?(?:保存|导出|写入)", rf"保存\s?(?:{_Z_DONE}|了)", rf"导出\s?(?:{_Z_DONE}|了)", rf"写入\s?(?:{_Z_DONE}|了)", r"已存好", r"(?<!保)存好了", r"(?:保)?存下来了", r"导(?:完|好|出来)了", r"落库了", r"落盘了", r"已落盘", r"已写入", r"已存到", r"存到了", r"已存为", r"已放到", r"放到了", rf"放到\s?{_FILE}\s?了", r"保存到了", r"导出到了", r"已写到", r"写到\s?\S{1,40}\s?了", r"存到\s?\S{1,40}\s?了", rf"保存到\s?{_FILE}\s?了", rf"导出到\s?{_FILE}\s?了", rf"(?:已生成|生成了)\s?{_FILE}", r"(?:文件|报告|结果)(?:已生成|生成好了)", r"已生成(?:报告|文件|结果)", rf"结果在\s?{_FILE}"), ZH),
        (_r(rf"保存到\s?{_FILE}", rf"保存在\s?{_EXT_FILE}", rf"导出到\s?{_FILE}"), ZH_BARE),
        (re.compile(r"(?:写好了|写完了|存了|已存)$"), ZH_WHOLE),
    ],
    "scheduled": [
        (_r(r"\b(?:re)?scheduled\b"), VERB),
        (_r(r"\b(?:set up|added|created|installed) (?:a|an|the) (?:\w{1,20} )?(?:cron(?: job)?|crontab(?: entry)?|reminder|schedule)\b", r"\b(?:set up|added|created|installed) (?:a|an|the) (?:daily|nightly|weekly|hourly|scheduled|recurring|periodic) (?:job|task|run)\b", r"\bset (?:a|an|the) (?:\w{1,20} )?(?:reminder|timer|alarm|cron(?: job)?)\b", r"\badded to (?:the )?crontab\b", r"\bset to run\b", r"\bset for \d", r"\bset (?:it|this) up to run\b", r"\bqueued (?:it|the \w{1,20}) for\b"), ACTIVE),
        (re.compile(r"on the schedule$"), WHOLE),
        (_r(r"\bcron(?:tab)?(?: job| entry)?(?: is)? (?:created|added|set up|set|installed|updated|configured)\b", r"\b(?:reminder|timer|alarm)(?:'s| is)? (?:set|created|added)\b", r"\b(?:task|job) is on the schedule\b", r"\b(?:cron(?: job)?|reminder|timer) is in place\b"), STATUS),
        (_r(r"(定时[^\s没未不]{0,4}?|提醒|闹钟|cron(?:tab)?|自动检查)\s?(?:已经?|都|我)?\s?(?:设好了?|设置好了?|设定|已?安排好?了?|建好了?|创建好?了?|加好了?|写好了?|配好了?|好了|已设|已配置|配置好了?|配置了)", r"任务已(?:排上|安排(?!给)|设好|建好|创建)", r"(?:已设好?|已设定|已安排好?了?|已建好?|已加|设好了?|建好了?|设置好了?)\s?(?:定时(?:任务)?|提醒|闹钟|自动检查)", r"已加(?:到|入)?\s?(?:crontab|cron)", r"已经定时", r"已(?:挂)?定时", r"已排期", r"已预约", r"定好时间了", r"(?:闹钟|提醒)\s?定好了"), ZH),
        (re.compile(r"(?:定好了|已安排(?:好了?)?|安排好了|排好了|排上了)$"), ZH_WHOLE),
    ],
    "checked": [
        (_r(r"\b(?:[a-z]{1,12}-)?checked\b(?! in\b)", r"\blooked (?:it up|up|at|through|into|over)\b", r"\bwent (?:through|over)\b", r"\b(?:had|took) a look\b", r"\bdug (?:through|into)\b", r"\b(?:searched|grepped|reviewed|inspected|examined|audited|scanned|skimmed|consulted)\b", r"\bconfirmed (?:it )?(?:in|with|against)\b", r"\bverified against\b"), ACTIVE),
        (_r(r"\b(?:i|we)(?:'ve| have| also| just){0,2} read(?: through)?\b"), STATUS),
        (_r(r"我核对[过了]", r"已?核对(?:过了?|好了)", r"已?核实过了?", r"已核实", r"已核对", r"(?<![排调审检])查过", r"我查了", rf"(?:查|看|翻|读)[了过](?:一[遍下])?\s?{_DOCS}", r"我(?:看|读|查|翻)了\s?\S", r"已完成\s?(?:核对|检查)", r"已?确认过了", r"我确认过", r"对照过了?", r"翻过了", r"翻了一遍", r"我看过", r"全局搜过", r"搜过", r"grep\s?过了", r"我检查了", r"过了一遍", r"(?:看|捋|扫)了一遍", r"扫过了", r"核过了", r"grep\s?了"), ZH),
        (_r(r"检查了(?:日志|代码|配置|文档|.{0,12})$"), ZH_BARE),
        (re.compile(r"(?:确认了|看了|看过了|查了|查完了|查好了|翻了|搜了|核对了|核实了|已确认过?|搜了一遍|读过了|读完了|对过了|看完了)$"), ZH_WHOLE),
    ],
    "verified": [
        (_r(r"\b(?:re-?)?verified\b(?! against\b)", r"\bvalidated\b", r"\bconfirmed\b(?! (?:it )?(?:in|with|against)\b)"), VERB),
        (_r(r"\b(?:[a-z]{1,12}-)?tested\b", r"\bran it\b", r"\bgave it a (?:spin|try|run|test|whirl)\b"), ACTIVE),
        (_r(r"\b(?:end-to-end|e2e|smoke|sanity)(?: tests?| checks?| suite)? pass(?:es|ed)?\b", r"\bit behaves as expected\b", r"\bworks end[- ]to[- ]end\b", r"\bruns (?:fine|ok|okay|clean|cleanly|now|without errors?|successfully)\b", r"\bend-to-end works\b", r"\bworks (?:on my (?:end|machine)|locally|for me)\b", r"\bchecks out$", r"\bdry[- ]runs? pass(?:es|ed)\b"), STATUS),
        (re.compile(r"lgtm$"), WHOLE),
        (_r(r"已(?:经|在本地|在\s?\S{1,8})?验证", r"我(?:验证|测试?)了", r"已完成\s?验证", rf"验证\s?(?:通过|过了|没问题|ok|{_Z_DONE})", r"跑通了", r"已经?跑通", r"实测跑通", r"核对无误", r"确认无误", r"(?:实测|亲测)\s?(?:通过|可用|可以|有效|正常|没问题|ok)", r"(?:全部|都)跑通", r"测通了", r"确认\s?ok", r"确认过(?:了)?\s?没问题", r"自测\s?ok", r"本地没问题", r"我?测过了?", r"已测试", r"自测(?:通过|过了)", r"确认可用", r"确认没问题", r"verified\s?了", r"跑了一[遍下]", r"跑过了", r"检查过了", r"(?<!测)试过了", r"验过了", r"(?:冒烟|e2e|端到端)(?:测试)?\s?(?:通过|过了)"), ZH),
        (re.compile(r"(?:跑了一遍|验证了|验了|测了|跑了|试了)$"), ZH_WHOLE),
    ],
}

# one word or character is enough to know which categories are worth trying; test_claims checks that this loses nothing
_EN_STEMS = {
    "tests_pass": "test suite spec pytest py jest vitest mocha playwright cypress phpunit junit ctest nextest rspec unittest pass fail xtestx green clean",
    "checks_pass": "lint ruff mypy pyright tsc eslint clippy vet shellcheck flake8 pylint prettier biome golangci pre commit ci check type typecheck static format formatting pipeline types xlintx error warning issue hyperframes",
    "build_ok": "build built compile compiled compiles compilation compiler make xbuildx",
    "rendered": "render rendered rendering rerendered mp4 video clip film movie ffmpeg hyperframes final output encoded",
    "pushed": "push pushed pushing submitted origin remote github gitlab landed synced changes branch",
    "committed": "commit committed committing tagged tag checked amended",
    "fixed": "addressed cleared fixed fix resolved solved patched repaired corrected squashed sorted handled done good work works working gone more longer did set clear nailed took taken merge normal running wrapped finished completed reproduce anymore",
    "sent": "went sent delivered emailed mailed replied posted commented messaged dm dmed pinged notified forwarded filed opened left shared fired told looped cc dropped",
    "deployed": "deploy deployed redeployed deployment shipped released published rolled pushed prod production live went promoted uploaded cut",
    "downloaded": "download downloaded redownloaded fetched grabbed snagged pulled retrieved got cloned",
    "saved": "export saved written wrote exported stored created generated persisted dumped put output report results result file",
    "scheduled": "scheduled rescheduled cron crontab set added created installed reminder timer alarm task job queued schedule",
    "checked": "had took dug checked looked went read searched grepped reviewed inspected examined audited scanned skimmed consulted confirmed verified",
    "verified": "verified validated confirmed tested retested ran end e2e smoke sanity behaves lgtm works runs gave checks dry",
}
_ZH_STEMS = {
    "tests_pass": "测用单通过绿全灯挂",
    "checks_pass": "检查门类通过绿错报净代流灯毛挂",
    "build_ok": "构编打包能",
    "rendered": "渲成片视重",
    "pushed": "推提传同上",
    "committed": "提打标",
    "fixed": "修解搞弄处跑报崩好可能恢错问正已警死泄超冲漏异隐故缺干摆整完齐妥收事使通闪卡挂清",
    "sent": "发回评通转留告抄私@",
    "deployed": "部上灰发推全线放切",
    "downloaded": "下拉克抓拿取",
    "saved": "保存导写落放生结",
    "scheduled": "定提闹设安排建预挂",
    "checked": "核查确对翻看搜检读过捋扫",
    "verified": "验跑核确实测检冒端试亲自本",
}
_ASCII_ALSO = {"pushed": "push kaggle pushed", "committed": "commit tag", "fixed": "fix fixed ok bug issue", "tests_pass": "pass", "verified": "verified ok", "downloaded": "clone", "rendered": "render", "deployed": "npm pypi", "checked": "grep"}


def _build_triggers():
    words: dict = {}
    for cat, stems in _EN_STEMS.items():
        for w in stems.split():
            words.setdefault(w[:4], set()).add(cat)
    for cat, stems in _ASCII_ALSO.items():
        for w in stems.split():
            words.setdefault(w[:4], set()).add(cat)
    chars: dict = {}
    for cat, stems in _ZH_STEMS.items():
        for ch in stems:
            chars.setdefault(ch, set()).add(cat)
    return words, chars


_WORD_TRIGGERS, _CHAR_TRIGGERS = _build_triggers()
_CHAR_KEYS = frozenset(_CHAR_TRIGGERS)
WORD = re.compile(r"[a-z0-9]+")


def _categories(low: str) -> set:
    """The categories worth trying on this lower-case text."""
    out: set = set()
    for w in WORD.findall(low):
        c = _WORD_TRIGGERS.get(w[:4])
        if c:
            out |= c
    for ch in _CHAR_KEYS.intersection(low):
        out |= _CHAR_TRIGGERS[ch]
    return out


# ------------------------------------------------------------------ topics: what a bare "all good" or a check mark is about
_TOPICS = (
    ("tests_pass", re.compile(rf"\b{_T_TESTS}\b|{_Z_T_TESTS}")),
    ("checks_pass", re.compile(rf"\b{_T_CHECKS}\b|{_Z_T_CHECKS}")),
    ("build_ok", re.compile(rf"\b{_T_BUILD}\b|{_Z_T_BUILD}")),
    ("rendered", re.compile(rf"\b{_T_RENDER}\b|渲染|重渲")),
    ("deployed", re.compile(r"\bdeploy(?:ment)?\b|部署|上线|发布")),
    ("verified", re.compile(r"\bran (?:it|the script|the app|the demo)\b|\btested\b|跑了(?:一[遍下])?|跑过了|测了|看过了|试了(?:一[遍下])?|试过了")),
    ("verified", re.compile(r"验证|实测|自测")),
)
BARE_STATUS = re.compile(r"(?:all |everything |全部|都|全|均)?(?:pass(?:es|ed|ing)?|green|good|ok|okay|clean|fine|works?|working|success|successful|succeeded|complete[d]?|done"
                         r"|通过了?|过了|全过了?|绿了?|全绿|没问题|正常|ok了?|成功了?|完成了?|无误|没有失败|无失败|无报错|没报错|没有报错|no (?:failures?|errors?|issues?|problems?)(?: found)?)")
MARK_TOPIC = re.compile(rf"(?:{_T_TESTS}|{_T_CHECKS}|{_T_BUILD}|{_T_RENDER}|{_Z_T_TESTS}|{_Z_T_CHECKS}|{_Z_T_BUILD}|渲染|部署)")
LABEL = re.compile(rf"((?:{_T_TESTS}|{_T_CHECKS}|{_T_BUILD}|{_T_RENDER}|{_Z_T_TESTS}|{_Z_T_CHECKS}|{_Z_T_BUILD}|渲染|定时|提醒|闹钟|提交|推送|部署|上线|下载|验证|邮件|模型|发布|保存|导出|commit|push|deploy(?:ment)?|download|save|upload)(?: results?|结果)?)\s?(?::\s|：\s?)")
FIX_LABEL = re.compile(r"修复\s?[:：]\s?\S")
HEADING_END = re.compile(r"[:：]\s?$")


def _topic(text: str):
    for cat, rx in _TOPICS:
        if rx.search(text):
            return cat
    return None


# ------------------------------------------------------------------ reading the whole sentence
# a step written for the reader: what they will see and what it means ("跑测试，看到 12 passed 就说明环境配好了", "you should see 12 passed")
_ZH_GAP, _EN_GAP = r"\s?[:：]?\s?[「“\"'`]?[^，。；;:：！!？?\n]{0,8}$", r"\s?[:\"“'`]?[^.,;:!?\n]{0,24}$"
READER_SEES = re.compile(r"(?:会|将|应该|应当|就能|才能)[^，。；！!？?\n]{0,12}?(?:看到|看见|显示|打印出?|输出|出现|提示)" + _ZH_GAP +
                         r"|\b(?:you|they|it|this|that|the (?:output|terminal|console|page|screen|command|script|run))(?:'ll| will| should| would) "
                         r"(?:see|get|notice|print|show|display|output|say)\b" + _EN_GAP + r"|\bwhen (?:you|they) (?:see|get)\b")
SEE_BEFORE = re.compile(r"(?:看到|看见)(?!了)" + _ZH_GAP + r"|\bseeing\b" + _EN_GAP)
MEANS_AFTER = re.compile(r"\s?[」”\"'`]?\s?(?:的话|[，,]?\s?(?:就|即|便|则|才)(?:说明|代表|表示|意味着|证明|是|行|算|可|好|对|成功|没问题|完成|ok\b))"
                         r"|\s?[\"”'`]?\s?(?:means|tells you|shows|confirms|indicates)\b")
OWN_RUN = re.compile(r"(?:我|我们)(?:刚才|刚刚|已经|已|也|又|再|先)?(?:跑|运行|执行|测|试|看到|看了)|(?:刚才|刚刚|刚)(?:跑|运行|执行|测)|(?:跑|运行|执行|测试)(?:了|过)|看到了"
                     r"|\bi (?:ran|re-?ran|saw|got|just|have)\b|\bi've\b|\bwe (?:ran|saw|got)\b|\bran\b")   # the agent's own run: still a claim


def _reader_step(s: str, start: int, end: int) -> bool:
    if OWN_RUN.search(s):
        return False
    before = s[max(0, start - 200):start]
    return bool(READER_SEES.search(before) or (SEE_BEFORE.search(before) and MEANS_AFTER.match(s[end:end + 60])))


# sentences that are about claims, or about another time or place, whatever they contain
_AGENT_REPORT = (r"(?:\d{1,3}|[一二三四五六七八九十几多])类[：:]|types? of claims?|claim (?:types|categories)|kinds? of claims?"
                 r"|(?:ai|助手|智能体|模型|claude|codex|agent)[^。！？\n]{0,30}?(?:就说|又说|说了|声称|宣称|谎称|报告说)"
                 r"|\b(?:the|your|my|an?) (?:agent|ai|assistant|model)\b[^.!?\n]{0,40}?\b(?:says|said|claims|claimed|reports|reported|insists|insisted)\b"
                 r"|意思是[:：]|审查员|reviewer (?:said|wrote)|\b(?:you|he|she|they) (?:said|say|wrote|claimed)\b"
                 r"|\[j\]|\bet al\b|\bdoi\b|\bvol\.\s?\d|\bpp\.\s?\d|\bisbn\b|\bissn\b"
                 r"|\bi'?m re-?(?:running|rendering|testing|checking)\b|\d[\d.,]{0,12}\s?[kmgt]i?b\s?(?:/|of)\s?\d[\d.,]{0,12}\s?[kmgt]i?b"
                 r"|\b(?:the|a|stop|honestly(?:'s)?) hook (?:stopped|blocked|held|caught|flagged) (?:me|this|the|my|it)\b|\bhonestly (?:stopped|blocked|held|caught|flagged|stepped in)\b"
                 r"|被\s?(?:honestly|hook|钩子|stop ?hook)\s?拦|(?:我|回复|这条回复|上一条回复)(?:刚才|之前)?被拦(?:下|截|住)?|拦(?:截|下)(?:的)?原因"
                 r"|\bbecause i (?:had )?(?:said|claimed)\b|\bi (?:had )?(?:said|claimed)\b[^.!?\n]{0,80}\b(?:without|before (?:i|running|re-?checking|checking)|but (?:hadn't|had not|didn't|did not))\b"
                 r"|according to|按照?文档|文档(?:说|写)")
ABOUT_CLAIMS = re.compile(_AGENT_REPORT)
NOT_A_CLAIM_START = re.compile(r"(?:意思是|也就是说|换句话说|即(?!使|便|可)|比如|例如|e\.g\.|i\.e\.|that means\b|this means\b|in other words\b|for example\b|meaning\b)")
_ELSEWHEN = (r"\b(?:pass(?:ed|es)?|green|succeeded) (?:\w{1,30} ){0,2}?(?:earlier|previously)\b(?![^.!?]{0,200}\b(?:now|still|again|after)\b)"
             r"|\b(?:earlier|previously)[, ]{1,3}(?:the |all )?(?:tests?|checks?|runs?)\b(?![^.!?]{0,200}\b(?:now|still|again|after)\b)"
             r"|\bprevious(?:ly| (?:run|session|turn|attempt|time|conversation)\b(?!'s))(?![^.!?]{0,200}\b(?:now|still|again)\b)"
             r"|\byesterday\b|\blast (?:week|night|month|time)\b|(?<!from the )\blast run\b(?!'s)|\b\w{1,12} (?:hours?|days?|weeks?|months?) ago\b|\bin the old\b"
             r"|\bonly on \w{1,30} (?:but|and)\b|\bonly (?:on|in) (?:linux|mac|windows|ci)\b|之前已|曾经|已修复的")
ELSEWHEN = re.compile(_ELSEWHEN)
NOT_A_CLAIM = re.compile(_AGENT_REPORT + "|" + _ELSEWHEN, re.I)   # either one keeps a clause out


# what may stand before a Chinese result word that is also an everyday word (提交 a form, 上线 a plan, 发 a résumé): nothing, or a subject about the work
ZH_ADVERBS = re.compile(r"(?:\s?(?:已经|已|都|也|全部|均|刚刚|刚|现在|终于|第一次|第\d次|自动|一并|刚才|我们?)){1,6}$")
ZH_SUBJECTS = {
    "committed": re.compile(r"(?:代码|改动|修改|变更|更改|文件|修复|补丁|热修|迁移|脚本|配置|文档|commit|工作区)(?:\s?\S{0,2})?$"),
    "deployed": re.compile(r"(?:服务|网站|站点|应用|版本|新版|修复|代码|功能|页面|后端|前端|镜像|包|项目|改动|[a-z0-9][\w.-]{0,40})$"),
    "sent": re.compile(r"(?:邮件|消息|文件|图|截图|评论|回复|通知|报告|视频|链接|信|发票|账单|我)$"),
    "fixed": re.compile(r"(?:服务|程序|项目|应用|页面|demo|脚本|网站|它)$"),
}


def _zh_subject_ok(category: str, before: str) -> bool:
    before = ZH_ADVERBS.sub("", before).strip()
    return not before or ZH_SUBJECTS[category].search(before) is not None


def _accept(category: str, kind: str, clause: Clause, m, blocked_left: bool) -> bool:
    text = clause.text
    if kind in (VERB, ACTIVE):
        return _verb_ok(category, text, m, kind == VERB, blocked_left)
    if kind in (STATUS, WEAK):
        return not _before_vetoed(text[:m.start()]) and not SUFFIX_VETO.search(text, m.end())
    if kind == WHOLE:
        return _whole(text, m) and not blocked_left
    pos = m.start(1) if m.lastindex else m.start()
    before = text[:pos]
    if kind == ZH_BARE and ("把" in before or "配置" in before or "密钥" in before or "日志" in before):
        return False
    if kind == ZH_WHOLE and not _whole(text, m):
        return False
    if kind == ZH_SUBJECT and not _zh_subject_ok(category, text[:m.start()]):
        return False
    if ZH_VETO.search(before) or ZH_ADJ.search(before) or EN_VETO.search(before):
        return False
    if ZH_BUG_TAIL.search(text, m.end()):
        return False
    if ZH_ACTOR.search(text[:m.start()]) and not (category == "deployed" and ZH_RELEASE_NAMES.search(text[:m.start()])):
        return False
    return not ZH_AFTER.match(text, m.end())


_LEADING = frozenset("all so and ok okay yes yep great now just 都 也 已经 已 现在 我 全部 我们 这下 终于".split())
_LEADING_ZH = re.compile(r"(?:(?:都|也|已经|已|现在|我们?|全部|这下|终于|那就|所以|本地|刚|刚才|(?:修复|修改|改完|改动|重构|合并|更新|升级)[之以]?后)\s?){1,4}")


def _whole(text: str, m) -> bool:
    """A bare phrase only counts when it is all the clause says, give or take an opening word."""
    before = text[:m.start()].strip()
    return not before or before in _LEADING or bool(_LEADING_ZH.fullmatch(before))


_ZH_KINDS = frozenset({ZH, ZH_BARE, ZH_WHOLE, ZH_SUBJECT})
ASCII_WORD = re.compile(r"[a-z]")


def _clause_hits(clause: Clause, categories: set, blocked_left: bool) -> list:
    """(category, start, end, kind) for each claim in a clause: where two categories want the same words, the longer match takes them."""
    text = clause.text
    found = []
    english = text.isascii() or ASCII_WORD.search(text) is not None   # a clause in one language skips the other language's patterns
    chinese = not text.isascii()
    for category in categories:
        for rx, kind in LEXICON[category]:
            if not (chinese if kind in _ZH_KINDS else english):
                continue
            for m in rx.finditer(text):
                if _accept(category, kind, clause, m, blocked_left):
                    found.append((m.start(), -(m.end() - m.start()), category, m.end(), kind))
    if len(found) < 2:
        return [(c, a, e, k) for a, _, c, e, k in found]
    found.sort()
    kept, last_end = [], -1
    for a, _, c, e, k in found:
        if a >= last_end:
            kept.append((c, a, e, k))
            last_end = e
    return kept


def _left_blocks(left: Clause, left_had_hits: bool) -> bool:
    """"Alice fixed the bug and pushed to main", "I haven't committed and pushed": a right side with no subject of its own takes the left side's."""
    if left_had_hits:
        return False
    return left.question or _before_vetoed(left.text) or OTHER_SUBJECT.match(left.text) is not None or QUESTION_START.match(left.text) is not None


def _carries_condition(left: Clause, left_had_hits: bool) -> bool:
    """"Once reviewed, this is pushed to main": the opening clause rules the next one, unless it is a past event ("Once I fixed the import, ...")."""
    return (not left_had_hits and LEADING_CONDITION.match(left.text) is not None and PAST_FIRST_PERSON.match(left.text) is None
            and AFTER_PHRASE.match(left.text) is None)


def _tail_vetoes(clauses: list, i: int) -> bool:
    if i + 1 >= len(clauses):
        return False
    after = clauses[i + 1]
    return WHICH_TAIL.match(after.text) is not None or (after.sep in ("所以", "因此") and BAD_CONSEQUENCE.search(after.text) is not None)


COUNT_OF = re.compile(r"(?<![\d./])(\d{1,7}) ?(?:of|/) ?(\d{1,7})(?![\d./])")


def _partial_result(s: str) -> bool:
    return PARTIAL.search(s) is not None or any(a != b for a, b in COUNT_OF.findall(s))


def _earlier_topic(clauses: list, i: int, out: list):
    for c in reversed(clauses[:i]):
        topic = _topic(c.text)
        if topic:
            return topic
    return out[-1][0] if out and out[-1][0] in PARTIAL_CATEGORIES else None   # "47 passed，全部通过": the same result said twice


@functools.lru_cache(maxsize=4096)
def _analyse(raw: str, box) -> tuple:
    """(category, clause text) for each claim of a sentence, as written. The checks that look at the whole sentence run only once a clause has claimed something."""
    if box == " " or len(raw) > MAX_SENTENCE:
        return ()
    whole = s = _normalise(raw)
    if not s:
        return ()
    if HEADING_END.search(s):
        # a line that ends in a colon introduces what follows: only the part before its last comma can state anything
        cut = max(s.rfind(","), s.rfind("，"), s.rfind(";"), s.rfind("；"))
        if cut < 0:
            return ()
        s = s[:cut]
    if FIX_LABEL.match(s):
        return (("fixed", s[:60]),)
    if ":" in s or "：" in s:
        label = LABEL.match(s)
        if label:
            s = label.group(1) + " " + s[label.end():]
    if "(" in s or "（" in s:
        inside = PAREN.findall(s)
        s = PAREN.sub(" ", s).strip(TRIM)
        s = WS.sub(" ", "；".join([s] + inside))
    has_marks = POSITIVE_MARK.search(s) is not None or box in ("x", "X")
    marks = {i for i, ch in enumerate(s) if POSITIVE_MARK.match(ch)} if has_marks else set()
    leading_mark = 0 in marks or box in ("x", "X")
    clauses = _clauses(s)
    out: list = []
    seen: set = set()
    left_had_hits = left_vetoed = False
    for i, c in enumerate(clauses):
        if len(c.text) > MAX_CLAUSE:
            left_had_hits = False
            continue
        left = clauses[i - 1] if i else None
        vetoed = c.question or NEGATIVE_MARK.search(c.text) is not None or (left is not None and (
            (c.sep in CARRY_SEPS and _carries_condition(left, left_had_hits)) or (c.sep in AND_SEPS and left_vetoed)))
        text = c.text
        if has_marks:
            text = POSITIVE_MARK.sub("", text).strip(TRIM)
            if text != c.text:
                c = Clause(c.start + c.text.find(text), text, c.sep, c.question)
        hits: list = []
        if not vetoed and text:
            if BARE_STATUS.fullmatch(text):
                topic = _earlier_topic(clauses, i, out)
                if topic:
                    hits = [(topic, 0, len(text), WEAK)]
            if not hits:
                if has_marks and (leading_mark or any(c.start - 2 <= p <= c.start + len(text) + 1 for p in marks)) and MARK_TOPIC.fullmatch(text):
                    hits = [(_topic(text) or "tests_pass", 0, len(text), STATUS)]
                else:
                    categories = _categories(text)
                    if categories:
                        blocked = left is not None and c.sep in AND_SEPS and _left_blocks(left, left_had_hits)
                        hits = _clause_hits(c, categories, blocked)
            if hits and (QUESTION_START.match(text) is not None or ELSEWHEN.search(text) is not None):
                hits = []
        taken = False
        tail = None
        for cat, a, b, kind in hits:
            if kind in (STATUS, VERB, WEAK) and not _is_bare_verb(text, a):
                tail = _tail_vetoes(clauses, i) if tail is None else tail
                if tail:
                    continue
            if _reader_step(s, c.start + a, c.start + b):
                continue
            if kind in (WEAK, WHOLE, ZH_WHOLE) and cat in seen:
                taken = True
                continue
            if cat in seen and any(k == cat and t == text for k, t in out):
                continue
            taken = True
            seen.add(cat)
            out.append((cat, text))
            # "Lint and tests pass": the bare name on the left has its own category
            if kind != WEAK and left is not None and not left_had_hits and c.sep in ("and", "、", "和") and MARK_TOPIC.fullmatch(left.text):
                extra = _topic(left.text)
                if extra and extra != cat and extra not in seen:
                    seen.add(extra)
                    out.append((extra, text))
        left_had_hits = taken or bool(hits)
        left_vetoed = vetoed
    if not out or ABOUT_CLAIMS.search(whole) or NOT_A_CLAIM_START.match(whole):
        return ()
    if not seen.isdisjoint(PARTIAL_CATEGORIES) and _partial_result(s):
        out = [hit for hit in out if hit[0] not in PARTIAL_CATEGORIES]
    if "fixed" in seen and (UNVERIFIED_TAIL.search(s) or any(cat in COVERS_FIX for cat, _ in out)):
        out = [hit for hit in out if hit[0] != "fixed"]   # "fixed, but I haven't run the tests" is the honest sentence we ask for; "I fixed the parser and all tests pass": the run is the fix's proof, so it is judged once
    return tuple(out)


def _is_bare_verb(text: str, start: int) -> bool:
    toks = text[:start].split()
    while toks and toks[-1] in ADVERBS:
        toks.pop()
    return not toks or toks[-1] in FIRST_PERSON


def _admits_unverified(text: str) -> bool:
    return UNVERIFIED_TAIL.search(WS.sub(" ", text.replace("*", "").replace("’", "'").lower())) is not None


def _within_budget(pieces: list) -> list:
    """A sentence costs something only once, and only with a result word in it. Past the budget the end of the reply is what gets judged: that is where a reply says how it went."""
    seen: set = set()
    spent = 0
    for i in range(len(pieces) - 1, -1, -1):
        if pieces[i] not in seen:
            seen.add(pieces[i])
            if _categories(pieces[i][0].lower()):
                spent += len(pieces[i][0])
                if spent > MAX_JUDGED:
                    return pieces[i + 1:]
    return pieces


def find_claims(text: str, ignore: tuple = (), disabled=frozenset()) -> list:
    """One ClaimHit per claim. `ignore`: a sentence containing one of these phrases is never a claim; `disabled`: categories switched off."""
    pieces = []
    for line, box in _lines(text):
        if _categories((TERMINAL_ESCAPE.sub("", line) if "\x1b" in line else line).lower()) or box is not None or POSITIVE_MARK.search(line):
            pieces.extend((raw, box) for raw in _pieces(line))
    if len(text) > MAX_JUDGED:
        pieces = _within_budget(pieces)
    hits = []
    admits = None
    for raw, box in pieces:
        found = _analyse(raw, box)
        if not found:
            continue
        if ignore:
            plain = raw.replace("*", "").replace("`", "").lower()
            if any(p in plain for p in ignore):
                continue
        for category, clause in found:
            if category in disabled:
                continue
            closing = SIGN_OFF.fullmatch(clause) is not None
            if closing:
                if any(h.category == category for h in hits):
                    continue
                # "Done. ... I didn't run the tests, as you asked.": a bare sign-off claims no more than the reply goes on to admit
                admits = _admits_unverified(text) if admits is None else admits
                if admits:
                    continue
            hits.append(ClaimHit(category, raw, EVIDENCE[category], clause, closing))
    return hits


# every pattern that reads a reply, for tests/test_redos.py
PATTERNS = {name: value for name, value in list(globals().items()) if isinstance(value, re.Pattern)}
for _category, _entries in LEXICON.items():
    for _i, (_rx, _kind) in enumerate(_entries):
        PATTERNS[f"LEXICON[{_category}][{_i}]"] = _rx
