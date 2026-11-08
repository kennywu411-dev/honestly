"""Read a shell command the way a shell does: enough of sh, bash and PowerShell's shape to say which commands a line runs,
what each one writes, and whether its result can still be seen. Nothing here is ever executed.

Linear in the length of the input and bounded: past MAX_BYTES, MAX_PIPELINES, MAX_WORDS or MAX_DEPTH the reader stops and marks
the script `truncated`, and callers treat that as "could not check". It never raises on any string.
"""
from __future__ import annotations
import functools
import os
import re
from dataclasses import dataclass, field

MAX_BYTES = 1_000_000       # a longer command is not read at all
MAX_PIPELINES = 4000        # pipelines in one script, nested ones included
MAX_WORDS = 4096            # words kept for one simple command; the rest are read and dropped
MAX_DEPTH = 24              # nested subshells, groups, substitutions
MAX_NESTED_SHELLS = 8       # `bash -c`, `bash <<EOF`, `eval` inside each other

_WS = re.compile(r"[ \t\r\f\v]+")
_PLAIN = re.compile(r"[^\s\\'\"`$&|;()<>]+")
_RESERVED = re.compile(r"(?:if|then|elif|else|fi|for|select(?=\s+\w+\s+in\b)|while|until|do|done|case|esac|function|in|\{|\}|!|\[\[|\]\])(?=[\s;&|()<>]|$)")
_STOP = {"then", "elif", "else", "fi", "do", "done", "esac", "}"}
_ASSIGN = re.compile(r"[A-Za-z_]\w*\+?=")
_REDIR = re.compile(r"<<<|<<-|<<|<&|<>|>>|>\||>&|>|<|&>>|&>")
_NAME = re.compile(r"[A-Za-z_]\w*")


@dataclass
class Word:
    raw: str                # as written
    text: str               # quotes and escapes removed; expansions kept as written
    quoted: bool = False    # some part of it was quoted
    subs: list = field(default_factory=list)   # scripts run by `$(...)`, backticks, `<(...)`, `>(...)`


@dataclass
class Redirect:
    fd: str
    op: str
    target: str


@dataclass
class Heredoc:
    term: str
    quoted: bool
    strip_tabs: bool
    body: str = ""
    end: int = -1           # offset just past the terminator line


@dataclass
class Command:
    kind: str = "simple"    # simple, subshell, group, if, loop, for, case, function, arith, test
    words: list = field(default_factory=list)
    assigns: list = field(default_factory=list)
    redirects: list = field(default_factory=list)
    heredocs: list = field(default_factory=list)
    parts: list = field(default_factory=list)   # child (role, Script) pairs of a compound command
    name: str = ""          # a function's name, a for loop's variable, `until` for an inverted loop
    items: list = field(default_factory=list)   # a for loop's word list, a case's (patterns) per arm
    start: int = 0
    end: int = 0

    @property
    def argv(self) -> list:
        return [w.text for w in self.words]


@dataclass
class Pipeline:
    commands: list = field(default_factory=list)
    ops: list = field(default_factory=list)     # "|" or "|&" between commands
    negated: bool = False
    sep: str = ""           # what follows: &&, ||, ;, &, newline, ;; or nothing
    start: int = 0
    end: int = 0


@dataclass
class Script:
    src: str
    pipelines: list = field(default_factory=list)
    truncated: bool = False


class _Reader:
    def __init__(self, src: str, depth: int = 0, budget: list | None = None):
        self.s, self.i, self.n = src, 0, len(src)
        self.depth = depth
        self.pending = []
        self.budget = budget if budget is not None else [MAX_PIPELINES]
        self.truncated = False

    # ------------------------------------------------------------ characters
    def _newline(self):
        """Step over a newline; the bodies of the heredocs opened on that line start here."""
        self.i += 1
        if self.pending:
            for h in self.pending:
                self._read_heredoc(h)
            self.pending = []

    def _read_heredoc(self, h: Heredoc):
        s, n, pos, term = self.s, self.n, self.i, h.term
        start = pos
        while pos <= n:
            nl = s.find("\n", pos)
            end = n if nl < 0 else nl
            if s[pos:end].strip() == term:
                h.body = s[start:pos].rstrip("\n") if pos > start else ""
                self.i = h.end = n if nl < 0 else nl + 1
                return
            if nl < 0:
                break
            pos = nl + 1
        h.body, self.i, h.end = s[start:], n, n   # no terminator: a shell reads to the end too

    def _skip_blank(self):
        """Blanks, line continuations and comments; not newlines."""
        s, n = self.s, self.n
        while self.i < n:
            m = _WS.match(s, self.i)
            if m:
                self.i = m.end()
                continue
            ch = s[self.i]
            nxt = s[self.i + 1] if self.i + 1 < n else ""
            if (ch == "\\" or ch == "`") and (nxt == "\n" or (nxt == "\r" and s[self.i + 2:self.i + 3] == "\n")):
                self.i += 2 if nxt == "\n" else 3   # `\` in sh, a backtick in PowerShell
            elif ch == "#":
                nl = s.find("\n", self.i)
                self.i = n if nl < 0 else nl
            else:
                return

    def _skip_separators(self):
        while self.i < self.n:
            self._skip_blank()
            if self.i < self.n and self.s[self.i] == "\n":
                self._newline()
            elif self.i < self.n and self.s[self.i] == ";" and not self.s.startswith(";;", self.i):
                self.i += 1
            else:
                return

    def _reserved(self):
        m = _RESERVED.match(self.s, self.i)
        return m.group(0) if m else ""

    # ------------------------------------------------------------ words
    def _word(self):
        s, n = self.s, self.n
        start, text, quoted, subs = self.i, [], False, []
        while self.i < n:
            m = _PLAIN.match(s, self.i)
            if m:
                text.append(m.group(0))
                self.i = m.end()
                if self.i < n and s[self.i] == "(" and text and text[-1].endswith("=") and len(text) == 1:   # x=(a b)
                    end = self._balanced(self.i)
                    text.append(s[self.i:end])
                    self.i = end
                continue
            ch = s[self.i]
            if ch == "\\":
                nxt = s[self.i + 1] if self.i + 1 < n else ""
                if not nxt:
                    self.i += 1
                elif nxt == "\n":
                    self.i += 2
                elif nxt == "\r" and s[self.i + 2:self.i + 3] == "\n":
                    self.i += 3
                elif nxt and (nxt.isalnum() or nxt in "_.-"):   # `C:\proj\x`, `.\gradlew`: a Windows path, not an escape
                    text.append("\\")
                    self.i += 1
                else:
                    text.append(nxt)
                    quoted = True
                    self.i += 2
            elif ch == "'":
                j = s.find("'", self.i + 1)
                j = n if j < 0 else j
                text.append(s[self.i + 1:j])
                quoted, self.i = True, min(j + 1, n)
            elif ch == '"':
                self._dquote(text, subs)
                quoted = True
            elif ch == "`":
                if not self._backtick(text, subs):
                    text.append("`")
                    self.i += 1
            elif ch == "$":
                self._dollar(text, subs)
            elif ch in "<>" and self.i + 1 < n and s[self.i + 1] == "(" and not text:
                body = self._nested(self.i + 2)
                subs.append(body)
                text.append(s[start:self.i])
            else:
                break
        if self.i == start:
            return None
        return Word(s[start:self.i], "".join(text), quoted, subs)

    def _dquote(self, text, subs):
        s, n = self.s, self.n
        self.i += 1
        while self.i < n:
            ch = s[self.i]
            if ch == '"':
                self.i += 1
                return
            if ch == "\\" and self.i + 1 < n:
                nxt = s[self.i + 1]
                if nxt == "\n":
                    pass
                elif nxt in '"\\$`':
                    text.append(nxt)
                else:
                    text.append("\\" + nxt)
                self.i += 2
            elif ch == "$":
                self._dollar(text, subs)
            elif ch == "`":
                if not self._backtick(text, subs):
                    text.append("`")
                    self.i += 1
            else:
                j = self.i + 1
                while j < n and s[j] not in '"\\$`':
                    j += 1
                text.append(s[self.i:j])
                self.i = j

    def _balanced(self, start: int) -> int:
        """The offset past the `)` that closes the `(` at start, skipping quotes."""
        s, n, depth, i = self.s, self.n, 0, start
        while i < n:
            ch = s[i]
            if ch == "\\":
                i += 2
                continue
            if ch == "'":
                j = s.find("'", i + 1)
                i = n if j < 0 else j + 1
                continue
            if ch == '"':
                i += 1
                while i < n and s[i] != '"':
                    i += 2 if s[i] == "\\" else 1
                i += 1
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        return n

    def _dollar(self, text, subs):
        s, n = self.s, self.n
        nxt = s[self.i + 1] if self.i + 1 < n else ""
        start = self.i
        if nxt == "(":
            if s.startswith("$((", self.i):
                end = self._balanced(self.i + 1)
                if s[end - 2:end] == "))":   # `$((1<<3))` is arithmetic: no command, no heredoc
                    text.append(s[start:end])
                    self.i = end
                    return
            subs.append(self._nested(self.i + 2))
            text.append(s[start:self.i])
        elif nxt == "{":
            depth, i = 0, self.i + 1
            while i < n:
                if s[i] == "\\":
                    i += 2
                    continue
                if s[i] == "{":
                    depth += 1
                elif s[i] == "}":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            text.append(s[start:min(i, n)])
            self.i = min(i, n)
        elif nxt == "'":    # $'...' with its own escapes
            i = self.i + 2
            out = []
            while i < n and s[i] != "'":
                if s[i] == "\\" and i + 1 < n:
                    out.append({"n": "\n", "t": "\t"}.get(s[i + 1], s[i + 1]))
                    i += 2
                else:
                    out.append(s[i])
                    i += 1
            text.append("".join(out))
            self.i = min(i + 1, n)
        else:
            m = _NAME.match(s, self.i + 1)
            if m:
                text.append(s[start:m.end()])
                self.i = m.end()
            elif nxt and nxt in "?#@*!$-0123456789":
                text.append(s[start:self.i + 2])
                self.i += 2
            else:
                text.append("$")
                self.i += 1

    def _nested(self, pos: int):
        """A `$(` or `<(` body starting at pos, read by this same reader so a heredoc inside it works."""
        self.i = pos
        if self.depth >= MAX_DEPTH:
            self.truncated = True
            self.i = self.n
            return Script(self.s, [], True)
        self.depth += 1
        pending, self.pending = self.pending, []
        lst = self._list(closing=")")
        self.pending = pending + self.pending
        self.depth -= 1
        self._skip_separators()
        if self.i < self.n and self.s[self.i] == ")":
            self.i += 1
        return Script(self.s, lst)

    def _backtick(self, text, subs) -> bool:
        s, n, i = self.s, self.n, self.i + 1
        while i < n and s[i] != "`":
            i += 2 if s[i] == "\\" else 1
        if i >= n:
            return False    # no partner: PowerShell's escape character, not a substitution
        inner = s[self.i + 1:i].replace("\\`", "`")
        if self.depth >= MAX_DEPTH:
            self.truncated = True
        else:
            r = _Reader(inner, self.depth + 1, self.budget)
            script = r.read()
            subs.append(script)
            self.truncated = self.truncated or script.truncated
        text.append(s[self.i:i + 1])
        self.i = i + 1
        return True

    # ------------------------------------------------------------ grammar
    def read(self) -> Script:
        out = []
        while self.i < self.n and not self.truncated:
            out += self._list()
            self._skip_blank()
            if self.i < self.n:     # a stray `)`, `fi`, `;;`: step over it and go on
                m = _RESERVED.match(self.s, self.i)
                self.i = m.end() if m else self.i + 1
        return Script(self.s, out, self.truncated)

    def _list(self, closing: str = "", stops=()):
        out = []
        glued = False
        while self.i < self.n:
            before = self.i
            self._skip_separators()
            glued = glued and self.i == before
            if self.i >= self.n or self.truncated:
                break
            ch = self.s[self.i]
            if ch == ")" or self.s.startswith(";;", self.i) or self.s.startswith(";&", self.i):
                break
            if self._reserved() in _STOP:
                break
            p = self._pipeline()
            if p is None:
                break
            if out and glued:   # `(Get-Content a) -replace 'x','y' | Set-Content a`, `[IO.File]::Write("a", "b")`: PowerShell's one statement
                p.start = out[-1].start
            out.append(p)
            self.budget[0] -= 1
            if self.budget[0] < 0:
                self.truncated = True
                self.i = self.n
                break
            self._skip_blank()
            if self.i >= self.n:
                break
            s, i = self.s, self.i
            glued = True
            if s.startswith("&&", i) or s.startswith("||", i):
                glued = False
                p.sep = s[i:i + 2]
                self.i += 2
            elif s.startswith(";;", i) or s.startswith(";&", i):
                p.sep = ";;"
                break
            elif s[i] == ";":
                glued = False
                p.sep = ";"
                self.i += 1
            elif s[i] == "&" and not s.startswith("&>", i):
                glued = False
                p.sep = "&"
                self.i += 1
            elif s[i] == "\n":
                glued = False
                p.sep = "\n"
                self._newline()
        return out

    def _pipeline(self):
        self._skip_blank()
        p = Pipeline(start=self.i)
        while self._reserved() == "!":
            p.negated = not p.negated
            self.i += 1
            self._skip_blank()
        p.start = self.i
        while True:
            c = self._command()
            if c is None:
                break
            p.commands.append(c)
            p.end = c.end
            if len(p.commands) > 1:
                self.budget[0] -= 1
                if self.budget[0] < 0:
                    self.truncated = True
                    self.i = self.n
                    break
            self._skip_blank()
            s, i = self.s, self.i
            if s.startswith("|&", i):
                p.ops.append("|&")
                self.i += 2
            elif s.startswith("|", i) and not s.startswith("||", i):
                p.ops.append("|")
                self.i += 1
            else:
                break
            self._skip_separators_after_pipe()
        return p if p.commands else None

    def _skip_separators_after_pipe(self):
        while self.i < self.n:
            self._skip_blank()
            if self.i < self.n and self.s[self.i] == "\n":
                self._newline()
            else:
                return

    def _command(self):
        self._skip_blank()
        if self.i >= self.n:
            return None
        s, start = self.s, self.i
        ch = s[start]
        if ch == "(":
            if s.startswith("((", start):
                end = self._balanced(start)
                if s[end - 2:end] == "))":
                    self.i = end
                    return self._finish(Command(kind="arith", start=start))
            return self._finish(self._block("subshell", 1, ")", start))
        word = self._reserved()
        if word == "{":
            return self._finish(self._block("group", 1, "}", start))
        if word == "if":
            return self._finish(self._if(start))
        if word in ("while", "until"):
            return self._finish(self._loop(start, word))
        if word in ("for", "select"):
            return self._finish(self._for(start, word))
        if word == "case":
            return self._finish(self._case(start))
        if word == "function":
            self.i += len(word)
            self._skip_blank()
            m = _NAME.match(s, self.i) or re.compile(r"\S+").match(s, self.i)
            name = m.group(0) if m else ""
            self.i = m.end() if m else self.i
            self._skip_blank()
            if s.startswith("()", self.i):
                self.i += 2
            return self._function(name, start)
        if word == "[[":
            return self._test(start)
        return self._simple(start)

    def _sub(self, closing="", stops=()):
        if self.depth >= MAX_DEPTH:
            self.truncated = True
            self.i = self.n
            return Script(self.s, [], True)
        self.depth += 1
        lst = self._list(closing, stops)
        self.depth -= 1
        return Script(self.s, lst)

    def _block(self, kind, width, closer, start):
        self.i += width
        body = self._sub(closing=closer if closer == ")" else "", stops=("}",))
        self._skip_separators()
        if closer == ")":
            if self.i < self.n and self.s[self.i] == ")":
                self.i += 1
        elif self._reserved() == "}":
            self.i += 1
        return Command(kind=kind, parts=[("body", body)], start=start)

    def _expect(self, word):
        self._skip_separators()
        if self._reserved() == word:
            self.i += len(word)
            return True
        return False

    def _if(self, start):
        c = Command(kind="if", start=start)
        self.i += 2
        c.parts.append(("cond", self._sub(stops=("then",))))
        if self._expect("then"):
            c.parts.append(("then", self._sub(stops=("elif", "else", "fi"))))
        while True:
            self._skip_separators()
            word = self._reserved()
            if word == "elif":
                self.i += 4
                c.parts.append(("cond2", self._sub(stops=("then",))))
                if self._expect("then"):
                    c.parts.append(("then2", self._sub(stops=("elif", "else", "fi"))))
            elif word == "else":
                self.i += 4
                c.parts.append(("else", self._sub(stops=("fi",))))
            else:
                break
        self._expect("fi")
        return c

    def _loop(self, start, word):
        c = Command(kind="loop", name=word, start=start)
        self.i += len(word)
        c.parts.append(("cond", self._sub(stops=("do",))))
        if self._expect("do"):
            c.parts.append(("body", self._sub(stops=("done",))))
        self._expect("done")
        return c

    def _for(self, start, word):
        c = Command(kind="for", start=start)
        self.i += len(word)
        self._skip_blank()
        m = _NAME.match(self.s, self.i)
        if m:
            c.name = m.group(0)
            self.i = m.end()
        self._skip_separators_after_pipe()
        if self._reserved() == "in":
            self.i += 2
            c.items = []
            while True:
                self._skip_blank()
                if self.i >= self.n or self.s[self.i] in ";\n":
                    break
                w = self._word()
                if w is None:
                    break
                c.items.append(w)
        else:
            c.items = None   # `for x; do`: the positional parameters
        if self._expect("do"):
            c.parts.append(("body", self._sub(stops=("done",))))
        self._expect("done")
        return c

    def _case(self, start):
        c = Command(kind="case", start=start)
        self.i += 4
        self._skip_blank()
        c.name = (self._word() or Word("", "")).text
        self._skip_separators_after_pipe()
        if self._reserved() == "in":
            self.i += 2
        while self.i < self.n and not self.truncated:
            self._skip_separators()
            if self._reserved() == "esac":
                self.i += 4
                break
            if self.i < self.n and self.s[self.i] == "(":
                self.i += 1
            pats = []
            while self.i < self.n:
                self._skip_blank()
                w = self._word()
                if w is not None:
                    pats.append(w.text)
                self._skip_blank()
                if self.i < self.n and self.s[self.i] == "|":
                    self.i += 1
                    continue
                break
            if self.i < self.n and self.s[self.i] == ")":
                self.i += 1
            elif not pats:
                self.i += 1
            c.items.append(pats)
            c.parts.append(("arm", self._sub(stops=("esac",))))
            self._skip_blank()
            if self.s.startswith(";;&", self.i):
                self.i += 3
            elif self.s.startswith(";;", self.i) or self.s.startswith(";&", self.i):
                self.i += 2
        return c

    def _function(self, name, start):
        self._skip_separators()
        body = self._command()
        c = Command(kind="function", name=name, start=start)
        if body is not None:
            c.parts.append(("body", Script(self.s, [Pipeline(commands=[body], start=body.start, end=body.end)])))
        c.end = self.i
        return c

    def _test(self, start):
        """`[[ a > b ]]`: nothing inside redirects."""
        j = self.s.find("]]", start)
        end = self.n if j < 0 else j + 2
        words = self.s[start:end].split()
        self.i = end
        c = Command(kind="test", words=[Word(w, w) for w in words], start=start)
        return self._finish(c)

    def _finish(self, c: Command):
        """Redirections after a compound command."""
        while True:
            self._skip_blank()
            if self.i >= self.n or not self._redirect(c):
                break
        c.end = self.i
        return c

    def _redirect(self, c: Command) -> bool:
        s, i, n = self.s, self.i, self.n
        fd = ""
        j = i
        while j < n and s[j].isdigit():
            j += 1
        if j > i and j < n and s[j] in "<>":
            fd, i = s[i:j], j
        elif s[i] == "*" and i + 1 < n and s[i + 1] == ">":   # PowerShell: all streams
            fd, i = "*", i + 1
        if i >= n:
            return False
        if s[i] in "<>" and i + 1 < n and s[i + 1] == "(":
            return False    # a process substitution is a word
        m = _REDIR.match(s, i)
        if not m:
            return False
        op = m.group(0)
        self.i = m.end()
        self._skip_blank()
        if op in ("<<", "<<-"):
            w = self._word()
            term = w.text.replace("\\", "") if w else ""   # `<<\EOF` is quoted too
            h = Heredoc(term, bool(w and (w.quoted or "\\" in w.raw)), op == "<<-")
            c.heredocs.append(h)
            if w is not None:
                self.pending.append(h)
            return True
        w = self._word()
        c.redirects.append(Redirect(fd, op, w.text if w else ""))
        if w is not None and w.subs:
            c.parts += [("redirect", x) for x in w.subs]
        return True

    def _simple(self, start):
        s, n = self.s, self.n
        c = Command(start=start)
        last = start
        while self.i < n:
            self._skip_blank()
            if self.i >= n:
                break
            ch = s[self.i]
            if ch in "\n;|)":
                break
            if ch == "&" and not s.startswith("&>", self.i):
                break
            if ch == "(":
                if len(c.words) == 1 and s.startswith("()", self.i):
                    self.i += 2
                    return self._function(c.words[0].text, start)
                word = c.words[-1] if c.words else None
                if word is not None and s[self.i - 1] not in " \t" and re.search(r"[\w]$", word.raw):   # PowerShell's `[IO.File]::WriteAllText("a", "b")`
                    end = self._balanced(self.i)
                    word.raw += s[self.i:end]
                    word.text += s[self.i:end]
                    self.i = last = end
                    continue
                break
            if self._redirect(c):
                last = self.i
                continue
            if ch in "<>" and self.i + 1 < n and s[self.i + 1] != "(":
                self.i += 1
                continue
            w = self._word()
            if w is None:
                self.i += 1     # nothing a word can start with: step over it
                continue
            last = self.i
            if not c.words and _ASSIGN.match(w.raw):
                c.assigns.append(w)
            elif len(c.words) < MAX_WORDS:
                c.words.append(w)
        c.end = last
        if not (c.words or c.assigns or c.redirects or c.heredocs):
            return None
        return c


@functools.lru_cache(maxsize=256)
def parse(src: str) -> Script:
    """The script `src` holds. Too long to read: an empty script marked truncated."""
    if not isinstance(src, str):
        return Script("", [], False)
    if len(src) > MAX_BYTES:
        return Script(src, [], True)
    r = _Reader(src)
    return r.read()


def text_of(script: Script, p: Pipeline) -> str:
    """A pipeline as written, with the heredoc bodies it owns."""
    src = script.src
    head = src[p.start:p.end]
    docs = [h for c in p.commands for h in c.heredocs]
    if not docs or any(0 <= h.end <= p.end for h in docs):
        return head
    tail = "".join("\n" + (h.body + "\n" if h.body else "") + h.term for h in docs)
    return head + tail


# ------------------------------------------------------------ the command behind the wrappers
_VALUE_FLAGS = {
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "exec": {"-a"},
    "time": {"-f", "--format", "-o", "--output"},
    "nice": {"-n", "--adjustment"},
    "ionice": {"-c", "-n", "-p", "--class", "--classdata"},
    "sudo": {"-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt", "-C", "-r", "-t"},
    "doas": {"-u", "-C"},
    "stdbuf": {"-i", "-o", "-e", "--input", "--output", "--error"},
    "caffeinate": {"-t", "-w"},
    "timeout": {"-k", "-s", "--kill-after", "--signal"},
    "gtimeout": {"-k", "-s", "--kill-after", "--signal"},
    "xvfb-run": {"-e", "-f", "-n", "-p", "-s", "--error-file", "--auth-file", "--server-num", "--xauth-protocol", "--server-args"},
    "xargs": {"-I", "-L", "-n", "-P", "-s", "-d", "-E", "-a", "-J", "-R", "-S", "--max-args", "--max-procs", "--replace", "--delimiter", "--arg-file", "--max-lines", "--max-chars"},
    "parallel": {"-j", "-S", "-a", "--jobs", "--arg-file", "--delay", "--timeout"},
    "npx": {"-p", "--package", "-c", "--call"},
    "bunx": {"-p", "--package"},
    "uvx": {"--from", "--with", "--python", "-p", "--with-requirements", "--index", "--index-url"},
    "uv run": {"--with", "--with-requirements", "--with-editable", "--python", "-p", "--project", "--directory", "--group", "--extra", "--env-file", "--index", "--index-url", "--package", "--script", "--config-file", "--cache-dir", "-C"},
    "conda run": {"-n", "--name", "-p", "--prefix", "--cwd"},
    "docker run": {"-e", "--env", "-v", "--volume", "-w", "--workdir", "-u", "--user", "--name", "-p", "--publish", "--network", "--net", "--entrypoint", "--env-file", "-h", "--hostname", "-m", "--memory", "--platform", "--mount", "-l", "--label", "--pull", "--cpus", "--add-host", "--link", "--tmpfs", "--device", "--restart"},
    "docker exec": {"-e", "--env", "-u", "--user", "-w", "--workdir", "--env-file"},
    "docker compose": {"-e", "--env", "-u", "--user", "-w", "--workdir", "--index", "--name", "-v", "--volume", "-p", "--publish", "--entrypoint", "-f", "--file", "--project-name", "--env-file"},
    "ssh": {"-i", "-p", "-l", "-o", "-F", "-J", "-L", "-R", "-D", "-b", "-c", "-E", "-e", "-m", "-O", "-Q", "-S", "-W", "-w"},
    "flock": {"-w", "--timeout", "-E"},
    "script": {"-c", "-t"},
}
_PLAIN_WRAPPERS = {"env", "command", "builtin", "exec", "time", "nice", "ionice", "nohup", "sudo", "doas", "stdbuf", "caffeinate", "chronic", "unbuffer", "timeout", "gtimeout", "xvfb-run", "xargs", "parallel", "npx", "bunx", "pnpx", "uvx", "ssh", "flock", "coverage-run", "nyc", "c8", "dotenvx-run"}
_RUN_WRAPPERS = {"poetry": "run", "pipenv": "run", "pdm": "run", "hatch": "run", "rye": "run", "devbox": "run"}
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
WIN_EXT = re.compile(r"\.(?:exe|cmd|bat|ps1)$", re.I)


def head_name(word: str) -> str:
    """`/usr/bin/pytest`, `.\\gradlew.bat` -> `pytest`, `gradlew`."""
    return WIN_EXT.sub("", re.split(r"[\\/]", word[-512:])[-1])


def _skip_flags(argv: list, i: int, values: set) -> int:
    while i < len(argv):
        a = argv[i]
        if a == "--":
            return i + 1
        if not a.startswith("-") or a == "-":
            return i
        i += 2 if a in values else 1
    return i


def unwrap(argv: list, limit: int = 12) -> list:
    """The command that really runs: `time timeout 60 uv run --frozen pytest -q` is `pytest -q`."""
    argv = list(argv)
    for _ in range(limit):
        if not argv:
            return argv
        h = head_name(argv[0])
        if len(argv) > 1 and re.fullmatch(r"\$\w+", argv[0]) and argv[1] == "=":   # PowerShell's `$x = pytest` runs it
            argv = argv[2:]
            continue
        two = h + " " + argv[1] if len(argv) > 1 else h
        if h in ("cargo", "rustup") and len(argv) > 1 and argv[1].startswith("+"):   # `cargo +nightly test`
            argv = [argv[0]] + argv[2:]
            continue
        if h == "env":
            i = _skip_flags(argv, 1, _VALUE_FLAGS["env"])
            while i < len(argv) and _ASSIGN.match(argv[i]):
                i += 1
            argv = argv[i:]
        elif h == "command" and len(argv) > 1 and argv[1] in ("-v", "-V"):
            return argv
        elif h in ("timeout", "gtimeout"):
            i = _skip_flags(argv, 1, _VALUE_FLAGS[h])
            argv = argv[i + 1:]     # the duration
        elif h == "script":
            i = _skip_flags(argv, 1, _VALUE_FLAGS["script"])
            argv = argv[i + 1:]     # the typescript file
        elif h == "flock":
            i = _skip_flags(argv, 1, _VALUE_FLAGS["flock"])
            argv = argv[i + 1:]     # the lock file
        elif h == "ssh":
            i = _skip_flags(argv, 1, _VALUE_FLAGS["ssh"])
            argv = argv[i + 1:]     # the host
        elif h == "parallel":
            i = _skip_flags(argv, 1, _VALUE_FLAGS["parallel"])
            rest = argv[i:]
            argv = rest[:rest.index(":::")] if ":::" in rest else rest
        elif h in _PLAIN_WRAPPERS:
            argv = argv[_skip_flags(argv, 1, _VALUE_FLAGS.get(h, set())):]
        elif two == "uv run":
            argv = argv[_skip_flags(argv, 2, _VALUE_FLAGS["uv run"]):]
        elif two == "uv tool" and len(argv) > 2 and argv[2] == "run":
            argv = argv[_skip_flags(argv, 3, _VALUE_FLAGS["uvx"]):]
        elif h in _RUN_WRAPPERS and len(argv) > 1 and argv[1] == _RUN_WRAPPERS[h]:
            rest = argv[_skip_flags(argv, 2, {"-e", "--env"}):]
            if h in ("hatch", "pdm", "devbox") and rest and not re.match(r"(?:python[\d.]*|pytest|tox|nox|mypy|ruff|coverage)$", rest[0]):
                return argv     # `hatch run test` names a script
            argv = rest
        elif h in ("conda", "mamba", "micromamba") and len(argv) > 1 and argv[1] == "run":
            argv = argv[_skip_flags(argv, 2, _VALUE_FLAGS["conda run"]):]
        elif two == "bundle exec" or two in ("pnpm exec", "pnpm dlx", "yarn dlx", "yarn exec", "npm exec", "bun x", "mise exec", "mise x", "asdf exec", "pyenv exec", "rbenv exec"):
            argv = argv[_skip_flags(argv, 2, {"-c", "--package", "-p"}):]
        elif two == "dotenv run" or two == "dotenvx run":
            argv = argv[_skip_flags(argv, 2, set()):]
        elif two == "direnv exec":
            argv = argv[3:]
        elif h in ("docker", "podman") and len(argv) > 2 and argv[1] == "run":
            i = _skip_flags(argv, 2, _VALUE_FLAGS["docker run"])
            argv = argv[i + 1:]     # the image
        elif h in ("docker", "podman") and len(argv) > 2 and argv[1] == "exec":
            i = _skip_flags(argv, 2, _VALUE_FLAGS["docker exec"])
            argv = argv[i + 1:]     # the container
        elif h in ("docker-compose", "podman-compose") and len(argv) > 2 and argv[1] in ("exec", "run"):
            i = _skip_flags(argv, 2, _VALUE_FLAGS["docker compose"])
            argv = argv[i + 1:]
        elif h in ("docker", "podman") and len(argv) > 3 and argv[1] == "compose":
            i = _skip_flags(argv, 2, _VALUE_FLAGS["docker compose"])
            if i < len(argv) and argv[i] in ("exec", "run"):
                j = _skip_flags(argv, i + 1, _VALUE_FLAGS["docker compose"])
                argv = argv[j + 1:]
            else:
                return argv
        elif two == "kubectl exec":
            argv = argv[argv.index("--") + 1:] if "--" in argv else []
        elif two == "nix develop" or two == "nix shell":
            flag = "-c" if "-c" in argv else "--command" if "--command" in argv else ""
            if not flag:
                return argv
            argv = argv[argv.index(flag) + 1:]
        elif h == "find" and any(a in argv for a in ("-exec", "-execdir", "-ok", "-okdir")):
            k = min(argv.index(a) for a in ("-exec", "-execdir", "-ok", "-okdir") if a in argv)
            rest = argv[k + 1:]
            for end in (";", "+"):
                if end in rest:
                    rest = rest[:rest.index(end)]
                    break
            argv = rest
        elif h == "coverage" and len(argv) > 1 and argv[1] == "run":
            rest = argv[_skip_flags(argv, 2, {"--source", "--rcfile", "--include", "--omit", "--data-file", "--concurrency", "--context", "--parallel-mode"}):]
            if rest[:1] == ["-m"]:
                rest = rest[1:]
            argv = rest
        elif re.fullmatch(r"python[\d.]*|pypy[\d.]*", h) and len(argv) > 3 and argv[1] == "-m" and argv[2] == "coverage" and argv[3] == "run":
            argv = ["coverage"] + argv[3:]
        else:
            return argv
    return argv


def shell_body(argv: list, stage_doc: str | None = None):
    """(text, options) when this command hands text to a shell: `bash -c '...'`, `eval '...'`, `bash <<EOF`. Options are the shell's own flags."""
    if not argv:
        return None
    h = head_name(argv[0]).lower()
    if h == "eval":
        return " ".join(argv[1:]), []
    if h == "cmd" and len(argv) > 2 and argv[1].lower() in ("/c", "/k"):
        return " ".join(argv[2:]), []
    if h in ("pwsh", "powershell"):
        for i, a in enumerate(argv[1:], 1):
            if a.lower() in ("-c", "-co", "-com", "-comm", "-comma", "-comman", "-command"):
                return " ".join(argv[i + 1:]), []
        return None
    if h not in _SHELLS:
        return None
    opts, i = [], 1
    while i < len(argv):
        a = argv[i]
        if a in ("-o", "+o", "-O", "+O") and i + 1 < len(argv):
            opts += [a, argv[i + 1]]
            i += 2
            continue
        if a == "--" or not a.startswith(("-", "+")):
            break
        opts.append(a)
        if a.startswith("--"):
            i += 1
            continue
        if "c" in a[1:]:   # `-c`, `-lc`, `-ec`, `-euc`
            return (argv[i + 1] if i + 1 < len(argv) else ""), opts
        if a.endswith("o") and i + 1 < len(argv):   # `-euo pipefail`
            opts.append(argv[i + 1])
            i += 1
        i += 1
    if stage_doc is not None and (i >= len(argv) or "-s" in opts):
        return stage_doc, opts
    return None


def expanduser(path: str) -> str:
    """os.path.expanduser with one answer on every system. A null byte or a lone surrogate means this is no path: it stays as written,
    where POSIX raises and Windows would make up another user's home. On Windows the `/` after `~` becomes the home folder's `\\`."""
    if not path.startswith("~") or "\x00" in path:
        return path
    try:
        path.encode("utf-8")
        out = os.path.expanduser(path)
    except (ValueError, UnicodeError):
        return path
    return out.replace("/", os.sep) if out != path and os.sep != "/" else out


# ------------------------------------------------------------ the commands in the order they run
DEV_NULL = {"/dev/null", "nul", "$null", "null"}
_STATUS_READ = re.compile(r"\$\?|\$\{\?\}|\$\{?(?:PIPESTATUS|pipestatus|status)\b|\$LASTEXITCODE\b(?!\s*=[^=])", re.I)
_FAIL_WORD = re.compile(r"fail|error|bad|broke|red\b|失败|错误", re.I)
_CONDITIONS = {"test", "[", "[[", "which", "type", "hash", "pgrep", "command"}
_STATE_WORDS = {"export", "declare", "typeset", "readonly", "local", "cd", "pushd", "chdir", "Set-Location", "sl", "Push-Location", "popd", "Pop-Location", "set", "shopt", "setopt", "unsetopt", "exit", "logout"}
_FUNCTION_HEADS = {"eval", "cmd", "pwsh", "powershell"}


@dataclass
class Unit:
    script: Script
    pipeline: Pipeline
    text: str
    guard: str = "yes"       # will it run? "yes", "maybe" (behind a condition) or "no"
    cwd: str | None = ""     # "" nothing said, None could not be told
    env: dict = field(default_factory=dict)
    pipefail: bool = False
    masked: bool = False     # its exit status is lost to whatever follows (`|| true`, `; echo done`)
    dropped: bool = False    # its output goes nowhere (`> /dev/null`, or captured and never used)
    level: int = 0           # 0: a command of the script itself; above: inside `bash -c`, `$(...)`, a heredoc given to a shell
    tail: list = field(default_factory=list)      # commands reading this one's output from an enclosing pipeline
    outer: list = field(default_factory=list)     # redirections of an enclosing group or loop
    own_echo: list = field(default_factory=list)  # text the same command line prints by itself afterwards, when that text is no proof
    reads_status: bool = False    # the very next command reads PIPESTATUS or $?
    cwd_after: str | None = ""    # the directory it leaves behind


class _State:
    __slots__ = ("env", "cwd", "pipefail", "errexit", "funcs", "exited", "calls")

    def __init__(self, env=None, cwd="", pipefail=False, errexit=False, funcs=None):
        self.env, self.cwd, self.pipefail, self.errexit = env if env is not None else {}, cwd, pipefail, errexit
        self.funcs, self.exited, self.calls = funcs if funcs is not None else {}, False, 0

    def child(self):
        c = _State(dict(self.env), self.cwd, self.pipefail, self.errexit, dict(self.funcs))
        c.calls = self.calls
        return c


class _Stage:
    """A stage of a pipeline runs in a subshell. Most stages change nothing, so the copy is only made when one does."""
    __slots__ = ("_parent", "_copy")

    def __init__(self, parent):
        self._parent, self._copy = parent, None

    def real(self):
        if self._copy is None:
            self._copy = self._parent.child()
        return self._copy


class _Ctx:
    __slots__ = ("guard", "tail", "masked", "dropped", "level", "outer", "shells")

    def __init__(self, guard="yes", tail=(), masked=False, dropped=False, level=0, outer=(), shells=0):
        self.guard, self.tail, self.masked, self.dropped, self.level, self.outer, self.shells = guard, list(tail), masked, dropped, level, list(outer), shells

    def but(self, **kw):
        c = _Ctx(self.guard, self.tail, self.masked, self.dropped, self.level, self.outer, self.shells)
        for k, v in kw.items():
            setattr(c, k, v)
        return c


def _may_wrap(h: str) -> bool:
    """Could this command hand text to a shell (`xargs sh -c ...`, `timeout 5 bash -c ...`)? Only then is unwrapping it worth the time."""
    return h in _PLAIN_WRAPPERS or h in _RUN_WRAPPERS or h in ("uv", "bundle", "pnpm", "yarn", "npm", "bun", "mise", "asdf", "pyenv", "rbenv", "dotenv", "dotenvx", "direnv", "docker", "podman", "docker-compose", "podman-compose", "kubectl", "nix", "find", "coverage", "conda", "mamba", "micromamba", "script", "gtimeout")


def _weaker(a: str, b: str) -> str:
    order = {"no": 0, "maybe": 1, "yes": 2}
    return a if order[a] <= order[b] else b


def stdout_dropped(c: Command) -> bool:
    """`> /dev/null`, `&> /dev/null`, `2>&1 >/dev/null`, `*> $null`: nothing the command prints reaches anyone."""
    for r in c.redirects:
        if r.target.lower() in DEV_NULL and (r.op in ("&>", "&>>") or (r.op in (">", ">>", ">|") and r.fd in ("", "1", "*"))):
            return True
    return False


def _single(p: Pipeline):
    return p.commands[0] if len(p.commands) == 1 and p.commands[0].kind == "simple" else None


def _head(p: Pipeline) -> str:
    c = _single(p)
    return head_name(c.words[0].text) if c and c.words else ""


def _literal_status(p: Pipeline):
    h = _head(p)
    v = True if h in ("true", ":") else False if h == "false" else None
    if v is None:
        return None
    return (not v) if p.negated else v


def _is_condition(p: Pipeline) -> bool:
    if p.commands and p.commands[0].kind == "test":
        return True
    c = _single(p)
    if not c or not c.words:
        return False
    h = _head(p)
    argv = c.argv
    if h in _CONDITIONS:
        return h != "command" or (len(argv) > 1 and argv[1] in ("-v", "-V"))
    return h in ("grep", "egrep", "fgrep", "rg") and any(a in ("-q", "--quiet", "--silent") or (a.startswith("-") and not a.startswith("--") and "q" in a) for a in argv[1:])


def _pipe_raw(script: Script, p: Pipeline) -> str:
    return script.src[p.start:min(p.end, p.start + 2000)]


def _reports_failure(script: Script, p: Pipeline) -> bool:
    """`|| exit 1`, `|| echo FAILED`: what runs after a failure says so."""
    raw = _pipe_raw(script, p)
    if re.search(r"(?:^|[\s;{(])(?:exit|return)\s+(?:[1-9]|\$)", raw) or _head(p) == "false":
        return True
    return bool(re.search(r"(?:^|[\s;{(])(?:echo|printf|print)\b", raw) and _FAIL_WORD.search(raw))


def _status_masked(script: Script, i: int, inherited: bool, errexit: bool) -> bool:
    pipes = script.pipelines
    p = pipes[i]
    if p.sep == "&":
        return True
    if i + 1 >= len(pipes) or p.sep in ("", ";;"):
        return inherited
    nxt = pipes[i + 1]
    if p.sep == "&&":
        return False
    if p.sep == "||":
        return not _reports_failure(script, nxt)
    return not errexit and not _STATUS_READ.search(_pipe_raw(script, nxt))


def _own_echo(script: Script, i: int) -> list:
    out = []
    pipes = script.pipelines
    for j in range(i + 1, min(len(pipes), i + 6)):
        if pipes[j - 1].sep == "&&":
            break
        c = _single(pipes[j])
        if not c or not c.words or _head(pipes[j]) not in ("echo", "printf", "Write-Output", "Write-Host"):
            continue
        words = [a for a in c.argv[1:] if not re.fullmatch(r"-[neE]+", a)]
        if words and "$" not in " ".join(words):
            out.append(" ".join(words).replace("\\n", "\n").strip())
    return out


def _set_options(st: _State, argv: list):
    h = argv[0].lower()
    args = argv[1:]
    def flip(name, on):
        name = name.lower().replace("_", "")
        if name == "pipefail":
            st.pipefail = on
        elif name == "errexit":
            st.errexit = on
    if h == "set":
        i = 0
        while i < len(args):
            a = args[i]
            if a in ("-o", "+o"):
                if i + 1 < len(args):
                    flip(args[i + 1], a == "-o")
                i += 2
                continue
            if a[:1] in "-+" and len(a) > 1:
                letters = a[1:]
                if "e" in letters:
                    st.errexit = a[0] == "-"
                if "o" in letters and i + 1 < len(args):
                    flip(args[i + 1], a[0] == "-")
                    i += 2
                    continue
            i += 1
    elif h == "shopt":
        flags = "".join(a[1:] for a in args if a.startswith("-"))
        names = [a for a in args if not a.startswith("-")]
        if "o" in flags and ("s" in flags or "u" in flags):
            for n in names:
                flip(n, "s" in flags)
    elif h in ("setopt", "unsetopt"):
        for n in args:
            flip(n, h == "setopt")


def _apply_opts(st: _State, opts: list):
    i = 0
    while i < len(opts):
        a = opts[i]
        if a in ("-o", "+o") and i + 1 < len(opts):
            _set_options(st, ["set", a, opts[i + 1]])
            i += 2
            continue
        if a.startswith("-") and not a.startswith("--") and a.endswith("o") and i + 1 < len(opts):
            _set_options(st, ["set", a, opts[i + 1]])
            i += 2
            continue
        if a.startswith("-") and not a.startswith("--") and "e" in a:
            st.errexit = True
        i += 1


def resolve(text: str, env: dict) -> str:
    """Put known variables into a word; what is not known stays as written."""
    if "$" not in text or not env:
        return text
    return re.sub(r"\$\{?(\w+)\}?", lambda m: env.get(m.group(1), m.group(0)), text)


def _next_cwd(st: _State, argv: list, certain: bool):
    args = argv[1:]
    while args and args[0].startswith("-") and args[0] != "-":
        args = args[1:]
    if not args:
        st.cwd = "~" if head_name(argv[0]) == "cd" else st.cwd
        return
    target = resolve(args[0], st.env)
    if re.match(r"(?:\$\(|`)[^)`]*(?:\bmktemp\b|[\s'\"]/tmp/|[\s'\"]/private/tmp/)", target):
        st.cwd = "/tmp/from-a-substitution"   # `T=$(mktemp -d); cd "$T"`
        return
    if target == "-" or "$(" in target or "`" in target or re.search(r"\$\{[^}]*[:#%/]", target) or not certain:
        st.cwd = None
        return
    target = re.sub(r"^\$\{?HOME\}?(?=/|$)", "~", target)
    if target.startswith("$"):
        m = re.match(r"\$\{?\w+\}?(.*)", target)
        st.cwd = None if m else target
        return
    if st.cwd and st.cwd != "~" and not (target.startswith(("/", "~")) or re.match(r"[A-Za-z]:[\\/]", target)):
        base = st.cwd.rstrip("/\\")
        st.cwd = base + "\\" + target.replace("/", "\\") if re.match(r"[A-Za-z]:\\", st.cwd) else base + "/" + target
    else:
        st.cwd = target


def _case_hits(word: str, pats: list) -> bool:
    import fnmatch
    return any(fnmatch.fnmatchcase(word, p) for p in pats)


def _walk_script(script: Script, st: _State, ctx: _Ctx, out: list):
    pipes = script.pipelines
    last, last_cond = None, False
    for idx, p in enumerate(pipes):
        if len(out) > 2 * MAX_PIPELINES:
            return
        g = "no" if st.exited else ctx.guard
        prev = pipes[idx - 1].sep if idx else ""
        if prev == "&&":
            if last is False:
                g = "no"
            elif last_cond:
                g = _weaker(g, "maybe")
        elif prev == "||":
            g = "no" if last is True else _weaker(g, "maybe")
        masked = _status_masked(script, idx, ctx.masked, st.errexit)
        _walk_pipeline(script, idx, p, g, masked, st, ctx, out)
        status = _literal_status(p)
        if prev == "&&" and last is False:
            status = False
        elif prev == "||" and last is True:
            status = True
        last, last_cond = status, _is_condition(p)


def _walk_pipeline(script: Script, idx: int, p: Pipeline, g: str, masked: bool, st: _State, ctx: _Ctx, out: list):
    pipes = script.pipelines
    if any(c.kind == "simple" for c in p.commands):
        only = _single(p)
        nxt = pipes[idx + 1] if idx + 1 < len(pipes) else None
        unit = Unit(script, p, text_of(script, p), g, st.cwd, st.env, st.pipefail, masked,
                    ctx.dropped or bool(only and stdout_dropped(only)), ctx.level, list(ctx.tail), list(ctx.outer),
                    _own_echo(script, idx) if masked else [],
                    bool(nxt and p.sep in (";", "\n", "&&", "||") and _STATUS_READ.search(_pipe_raw(script, nxt))))
        out.append(unit)
    else:
        unit = None
    alone = len(p.commands) == 1
    for k, c in enumerate(p.commands):
        inner_st = st if alone else _Stage(st)   # a pipeline's stages run in subshells
        if c.kind == "simple":
            _walk_simple(script, p, k, c, g, masked, inner_st, ctx, out)
        else:
            _walk_compound(c, g, masked, inner_st.real() if not alone else inner_st, ctx.but(tail=p.commands[k + 1:] + ctx.tail), out)
    if unit is not None:
        unit.cwd_after = st.cwd


def _walk_simple(script: Script, p: Pipeline, k: int, c: Command, g: str, masked: bool, st, ctx: _Ctx, out: list):
    argv = c.argv
    h = head_name(argv[0]) if argv else ""
    changes = bool(c.assigns or c.parts or c.heredocs or any(w.subs for w in c.words)) or h in _STATE_WORDS or h in _FUNCTION_HEADS or h in _SHELLS or (argv and _may_wrap(h))
    if not changes and (isinstance(st, _Stage) or not getattr(st, "funcs", None)):
        return
    if isinstance(st, _Stage):
        st = st.real()
    for w in c.assigns:
        name = w.text.split("=", 1)[0].rstrip("+")
        if not c.words and g == "yes":
            st.env[name] = w.text.split("=", 1)[1]
    if argv:
        if h in ("export", "declare", "typeset", "readonly", "local") and g == "yes":
            for a in argv[1:]:
                if "=" in a and _ASSIGN.match(a):
                    n, v = a.split("=", 1)
                    st.env[n.rstrip("+")] = v
        elif h in ("cd", "pushd", "chdir", "Set-Location", "sl", "Push-Location", "popd", "Pop-Location"):
            if h in ("popd", "Pop-Location"):
                st.cwd = None
            else:
                _next_cwd(st, argv, g == "yes")
        elif h in ("set", "shopt", "setopt", "unsetopt") and g == "yes":
            _set_options(st, [h] + argv[1:])
        elif h in ("exit", "logout") and g == "yes":
            st.exited = True
    # text run by substitutions in the words
    for w in list(c.assigns) + list(c.words):
        for sub in w.subs:
            if isinstance(sub, Script):
                _walk_script(sub, st.child(), ctx.but(guard=g, tail=[], masked=True if (c.words or masked) else False, dropped=_capture_dropped(c, w, script.src), level=ctx.level + 1), out)
    for d in c.heredocs:
        if not d.quoted and "$(" in d.body and ctx.shells < MAX_NESTED_SHELLS:
            inner = parse('echo "' + d.body.replace('"', '\\"') + '"')
            _walk_script(inner, st.child(), ctx.but(guard=g, tail=[], level=ctx.level + 1, shells=ctx.shells + 1, dropped=True, masked=True), out)
    for _, sub in c.parts:
        _walk_script(sub, st.child(), ctx.but(guard=g, tail=[], level=ctx.level + 1), out)
    if not argv:
        return
    real = unwrap(argv)
    tail = p.commands[k + 1:] + ctx.tail
    if real and real[0] in st.funcs and st.calls < 64:   # a function of this script
        st.calls += 1
        _walk_compound(st.funcs[real[0]], g, masked, st, ctx.but(tail=tail), out)
        return
    if ctx.shells >= MAX_NESTED_SHELLS:
        return
    doc = "\n".join(d.body for d in c.heredocs) if c.heredocs else None
    if doc is None and k > 0:
        doc = _literal_stdin(p.commands[k - 1])
    if doc is None:
        for r in c.redirects:
            if r.op == "<<<":
                doc = r.target
    body = shell_body(real, doc)
    if body is None:
        return
    text, opts = body
    if not text:
        return
    if head_name(real[0]) == "eval":
        child = st      # text given to `eval` runs in this very shell
    else:
        child = _State(dict(st.env), st.cwd, False, False, {})
        _apply_opts(child, opts)
    _walk_script(parse(text), child, ctx.but(guard=g, masked=masked, tail=tail, level=ctx.level + 1, shells=ctx.shells + 1, dropped=ctx.dropped or stdout_dropped(c)), out)


@functools.lru_cache(maxsize=32)
def _names_read(src: str) -> frozenset:
    return frozenset(re.findall(r"\$\{?(\w+)", src))


def _capture_dropped(c: Command, w: Word, src: str) -> bool:
    if c.words:
        return head_name(c.words[0].text) not in ("echo", "printf", "print", "cat", "Write-Output")
    return w.text.split("=", 1)[0] not in _names_read(src)


def _literal_stdin(c: Command):
    """What `echo 'x' |`, `printf 'x' |` or `cat <<EOF |` feeds the next stage, when the text is written out."""
    if c.kind != "simple" or not c.words:
        return None
    h = head_name(c.words[0].text)
    if h == "cat" and c.heredocs and len(c.words) == 1:
        return "\n".join(d.body for d in c.heredocs)
    if h in ("echo", "printf"):
        args = [a for a in c.argv[1:] if not re.fullmatch(r"-[neE]+", a)]
        return " ".join(args).replace("\\n", "\n")
    return None


def _branch(sub: Script, st: _State, ctx: _Ctx, out: list):
    """A body that may or may not run: what it does to the shell cannot be counted on, and a `cd` in it leaves the directory unknown."""
    child = st.child()
    _walk_script(sub, child, ctx, out)
    if child.cwd != st.cwd and ctx.guard != "no":
        st.cwd = None


def _walk_compound(c: Command, g: str, masked: bool, st: _State, ctx: _Ctx, out: list):
    drop = ctx.dropped or stdout_dropped(c)
    outer = ctx.outer + list(c.redirects)
    in_ctx = ctx.but(dropped=drop, outer=outer, guard=g, masked=masked)
    if c.kind == "subshell":
        for _, sub in c.parts:
            _walk_script(sub, st.child(), in_ctx, out)
    elif c.kind == "group":
        for _, sub in c.parts:
            _walk_script(sub, st, in_ctx, out)
    elif c.kind == "if":
        status = None
        for role, sub in c.parts:
            if role.startswith("cond"):
                status = _literal_status(sub.pipelines[-1]) if sub.pipelines else None
                _walk_script(sub, st, in_ctx.but(masked=False), out)
            elif role.startswith("then"):
                branch = "no" if status is False else g if status is True else _weaker(g, "maybe")
                if status is True:
                    _walk_script(sub, st, in_ctx.but(guard=branch), out)
                else:
                    _branch(sub, st, in_ctx.but(guard=branch), out)
            else:
                branch = "no" if status is True else g if status is False else _weaker(g, "maybe")
                if status is False:
                    _walk_script(sub, st, in_ctx.but(guard=branch), out)
                else:
                    _branch(sub, st, in_ctx.but(guard=branch), out)
    elif c.kind == "loop":
        status = None
        for role, sub in c.parts:
            if role == "cond":
                status = _literal_status(sub.pipelines[-1]) if sub.pipelines else None
                if c.name == "until" and status is not None:
                    status = not status
                _walk_script(sub, st, in_ctx.but(masked=False), out)
            else:
                branch = "no" if status is False else g if status is True else _weaker(g, "maybe")
                _branch(sub, st, in_ctx.but(guard=branch), out)
    elif c.kind == "for":
        branch = g if c.items else ("no" if c.items is not None else _weaker(g, "maybe"))
        for _, sub in c.parts:
            _branch(sub, st, in_ctx.but(guard=branch), out)
    elif c.kind == "case":
        literal = "$" not in c.name and "`" not in c.name
        hit = False
        for pats, (_, sub) in zip(c.items, c.parts):
            if literal:
                now = not hit and _case_hits(c.name, pats)
                hit = hit or now
                branch = g if now else "no"
            else:
                branch = _weaker(g, "maybe")
            _branch(sub, st, in_ctx.but(guard=branch), out)
    elif c.kind == "function":
        st.funcs[c.name] = c.parts[0][1].pipelines[0].commands[0] if c.parts else Command(kind="arith")


@functools.lru_cache(maxsize=256)
def units(src: str) -> tuple:
    """Every pipeline of the command in the order it runs, with what is known about each. Compound commands are opened up;
    the bodies of `bash -c`, `eval`, `$(...)` and heredocs fed to a shell come after their parent with a higher level."""
    script = parse(src)
    out = []
    _walk_script(script, _State(), _Ctx(), out)
    return tuple(out)


def too_big(src: str) -> bool:
    """The reader stopped before the end: treat whatever the command does as "could not check"."""
    return parse(src).truncated
