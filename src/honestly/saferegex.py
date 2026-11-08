"""Decide whether a pattern taken from a command matches a line, without `re`.

A grep in somebody's pipeline can hold anything, `(.*)*X` included, and `re` would backtrack on it for minutes inside a hook with a
10 second timeout. This is a Thompson simulation of the common subset: time is bounded by pattern size times text size, whatever the
pattern is. Anything outside the subset (back references, look-around) or over the limits gives None: "could not tell".
"""
from __future__ import annotations

MAX_PATTERN = 400
MAX_STATES = 400
MAX_STEPS = 400_000
MAX_DEPTH = 32

_DIGIT = frozenset("0123456789")
_WORD = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
_SPACE = frozenset(" \t\n\r\f\v")
_CLASSES = {"d": (_DIGIT, False), "D": (_DIGIT, True), "w": (_WORD, False), "W": (_WORD, True), "s": (_SPACE, False), "S": (_SPACE, True)}
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "f": "\f", "v": "\v"}
_POSIX = {"digit": _DIGIT, "space": _SPACE, "alpha": frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"), "upper": frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
          "lower": frozenset("abcdefghijklmnopqrstuvwxyz"), "alnum": _WORD - {"_"}, "word": _WORD, "punct": frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")}


class _Unsupported(Exception):
    pass


# A program is a list of instructions: ("set", chars, negated, next), ("any", next), ("split", a, b), ("jump", a), ("bol", next), ("eol", next), ("wb", wanted, next), ("match",)
class _Parser:
    def __init__(self, pattern: str, ignore_case: bool):
        self.p, self.i, self.icase = pattern, 0, ignore_case
        self.prog: list = []
        self.depth = 0

    def _emit(self, *ins) -> int:
        if len(self.prog) >= MAX_STATES:
            raise _Unsupported
        self.prog.append(list(ins))
        return len(self.prog) - 1

    # A fragment is parsed to a small tree first, so `{m,n}` can repeat it.
    def parse(self):
        tree = self._alt()
        if self.i < len(self.p):
            raise _Unsupported
        return tree

    def _alt(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise _Unsupported
        branches = [self._seq()]
        while self.i < len(self.p) and self.p[self.i] == "|":
            self.i += 1
            branches.append(self._seq())
        self.depth -= 1
        return ("alt", branches) if len(branches) > 1 else branches[0]

    def _seq(self):
        items = []
        while self.i < len(self.p) and self.p[self.i] not in "|)":
            items.append(self._repeat())
        return ("seq", items)

    def _repeat(self):
        atom = self._atom()
        while self.i < len(self.p):
            ch = self.p[self.i]
            if ch == "*":
                atom, self.i = ("rep", atom, 0, None), self.i + 1
            elif ch == "+":
                atom, self.i = ("rep", atom, 1, None), self.i + 1
            elif ch == "?":
                atom, self.i = ("rep", atom, 0, 1), self.i + 1
            elif ch == "{":
                j = self.p.find("}", self.i)
                body = self.p[self.i + 1:j] if j > 0 else ""
                parts = body.split(",")
                if j < 0 or not body or len(parts) > 2 or not all(x.isdigit() or x == "" for x in parts) or not parts[0].isdigit():
                    break   # a literal `{`
                lo = int(parts[0])
                hi = lo if len(parts) == 1 else (int(parts[1]) if parts[1] else None)
                if lo > 64 or (hi is not None and hi > 64):
                    raise _Unsupported
                atom, self.i = ("rep", atom, lo, hi), j + 1
            else:
                break
            if self.i < len(self.p) and self.p[self.i] in "?+":   # lazy and possessive say nothing about whether it matches
                self.i += 1
        return atom

    def _atom(self):
        ch = self.p[self.i]
        self.i += 1
        if ch == "(":
            if self.p.startswith("?:", self.i):
                self.i += 2
            elif self.p.startswith("?", self.i):
                raise _Unsupported
            inner = self._alt()
            if self.i >= len(self.p) or self.p[self.i] != ")":
                raise _Unsupported
            self.i += 1
            return inner
        if ch == ".":
            return ("any",)
        if ch == "^":
            return ("bol",)
        if ch == "$":
            return ("eol",)
        if ch == "[":
            return self._class()
        if ch == "\\":
            if self.i >= len(self.p):
                raise _Unsupported
            e = self.p[self.i]
            self.i += 1
            if e in _CLASSES:
                chars, neg = _CLASSES[e]
                return ("set", chars, neg)
            if e in ("b", "<", ">"):
                return ("wb", True)
            if e == "B":
                return ("wb", False)
            if e.isdigit() or e in "AZzGkgpPuUxN":
                raise _Unsupported
            return ("set", frozenset(self._folded(_ESCAPES.get(e, e))), False)
        if ch in "*+?":
            raise _Unsupported
        return ("set", frozenset(self._folded(ch)), False)

    def _folded(self, ch: str) -> str:
        return ch.lower() + ch.upper() if self.icase else ch

    def _class(self):
        p, i, n = self.p, self.i, len(self.p)
        neg = i < n and p[i] == "^"
        if neg:
            i += 1
        chars, first = set(), True
        while True:
            if i >= n:
                raise _Unsupported
            ch = p[i]
            if ch == "]" and not first:
                i += 1
                break
            first = False
            if ch == "[" and p.startswith("[:", i):
                j = p.find(":]", i)
                if j < 0 or p[i + 2:j] not in _POSIX:
                    raise _Unsupported
                chars |= _POSIX[p[i + 2:j]]
                i = j + 2
                continue
            if ch == "\\" and i + 1 < n:
                e = p[i + 1]
                i += 2
                if e in _CLASSES:
                    if _CLASSES[e][1]:
                        raise _Unsupported
                    chars |= _CLASSES[e][0]
                    continue
                ch = _ESCAPES.get(e, e)
            else:
                i += 1
            if i + 1 < n and p[i] == "-" and p[i + 1] != "]":
                hi = p[i + 1]
                i += 2
                if hi == "\\" and i < n:
                    hi = p[i]
                    i += 1
                if ord(hi) - ord(ch) > 512 or ord(hi) < ord(ch):
                    raise _Unsupported
                chars |= {chr(c) for c in range(ord(ch), ord(hi) + 1)}
            else:
                chars.add(ch)
        self.i = i
        if self.icase:
            chars |= {c.lower() for c in chars} | {c.upper() for c in chars}
        return ("set", frozenset(chars), neg)

    # ---- tree to instructions: each node is compiled to enter at the returned index and leave to `nxt`
    def compile(self, node, nxt: int) -> int:
        kind = node[0]
        if kind == "seq":
            for item in reversed(node[1]):
                nxt = self.compile(item, nxt)
            return nxt
        if kind == "alt":
            entries = [self.compile(b, nxt) for b in node[1]]
            at = entries[-1]
            for e in reversed(entries[:-1]):
                at = self._emit("split", e, at)
            return at
        if kind == "set":
            return self._emit("set", node[1], node[2], nxt)
        if kind == "any":
            return self._emit("any", nxt)
        if kind in ("bol", "eol"):
            return self._emit(kind, nxt)
        if kind == "wb":
            return self._emit("wb", node[1], nxt)
        if kind == "rep":
            atom, lo, hi = node[1], node[2], node[3]
            if hi is None:
                loop = self._emit("split", -1, nxt)
                body = self.compile(atom, loop)
                self.prog[loop][1] = body
                entry = loop
            else:
                entry = nxt
                for _ in range(hi - lo):
                    body = self.compile(atom, entry)
                    entry = self._emit("split", body, nxt)
            for _ in range(lo):
                entry = self.compile(atom, entry)
            return entry
        raise _Unsupported


class Program:
    __slots__ = ("prog", "start", "steps")

    def __init__(self, prog, start):
        self.prog, self.start = prog, start
        self.steps = 0

    def search(self, text: str):
        """True or False; None when the step budget ran out."""
        prog, n = self.prog, len(text)
        seen = [-1] * len(prog)
        current: list = []

        def add(states: list, pc: int, pos: int) -> bool:
            stack = [pc]
            while stack:
                pc = stack.pop()
                if seen[pc] == pos:
                    continue
                seen[pc] = pos
                self.steps += 1
                ins = prog[pc]
                op = ins[0]
                if op == "jump":
                    stack.append(ins[1])
                elif op == "split":
                    stack.append(ins[2])
                    stack.append(ins[1])
                elif op == "bol":
                    if pos == 0:
                        stack.append(ins[1])
                elif op == "eol":
                    if pos == n:
                        stack.append(ins[1])
                elif op == "wb":
                    a = pos > 0 and text[pos - 1] in _WORD
                    b = pos < n and text[pos] in _WORD
                    if (a != b) == ins[1]:
                        stack.append(ins[2])
                elif op == "match":
                    return True
                else:
                    states.append(pc)
            return False

        for pos in range(n + 1):
            if self.steps > MAX_STEPS:
                return None
            if add(current, self.start, pos):
                return True
            if pos == n:
                break
            ch = text[pos]
            following: list = []
            for pc in current:
                ins = prog[pc]
                if ins[0] == "any":
                    ok, to = ch != "\n", ins[1]
                else:
                    ok, to = (ch in ins[1]) != ins[2], ins[3]
                if ok and add(following, to, pos + 1):
                    return True
            # threads added for pos + 1 were marked with that position; the next start joins them there
            current = following
        return False


def compile(pattern: str, ignore_case: bool = False):
    """A Program, or None when the pattern is too large or outside the subset. Malformed patterns are None too."""
    if not isinstance(pattern, str) or len(pattern) > MAX_PATTERN:
        return None
    try:
        parser = _Parser(pattern, ignore_case)
        tree = parser.parse()
        accept = parser._emit("match")
        start = parser.compile(tree, accept)
    except (_Unsupported, RecursionError, ValueError, OverflowError):
        return None
    return Program(parser.prog, start)
