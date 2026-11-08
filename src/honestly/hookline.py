"""What a hook entry written by honestly looks like, in one place.

The plugin's entry point imports this on every hook, so it stays small: no rule tables here.
"""
from __future__ import annotations

import os
import re
from collections import namedtuple

MARK = "honestly hook"
NAMES = ("honestly", "sober")   # sober is the package's previous name

Entry = namedtuple("Entry", "exe which agent module")

_REST = r"(?P<module>\s+-m\s+honestly(?:\.cli)?)?\s+hook\s+(?P<which>stop|pre)(?:\s+--agent\s+(?P<agent>[\w-]+))?(?:\s+\#\s*(?P<mark>honestly|sober)\s+hook)?\s*$"
_QUOTED_WORD = re.compile(r"""\s*(?P<exe>(?:"[^"]*"|'[^']*'|[^\s"'])+)""" + _REST)
_BARE_WORD = re.compile(r"\s*(?P<exe>\S+)" + _REST)   # older versions quoted only for a space, so a path can hold a lone quote
_PLAIN = re.compile(r"[\w@%+=:,./-]+", re.ASCII)
_WINDOWS = re.compile(r"^[A-Za-z]:[\\/]|^(?:\\\\|//)")


def stem(path: str) -> str:
    return os.path.splitext(re.split(r"[\\/]", path)[-1])[0].lower()


def _unquote(word: str) -> str:
    if "\\" in word:
        return word.strip("\"'")   # a Windows path: shell rules would eat the backslashes
    import shlex
    try:
        return "".join(shlex.split(word, posix=True))
    except ValueError:
        return word


def parse_line(command: str):
    """The Entry a hook line runs, or None when it is anything other than exactly our own line: a user's script that
    only mentions the words, or adds `&& something`, is theirs."""
    if "hook" not in command:
        return None
    m = _QUOTED_WORD.match(command) or _BARE_WORD.match(command)
    if not m:
        return None
    exe = _unquote(m.group("exe"))
    if not (m.group("module") or m.group("mark") or stem(exe) in NAMES):
        return None
    return Entry(exe, m.group("which"), m.group("agent"), bool(m.group("module")))


def _parse_args(command: str, args: list):
    module = args[:2] == ["-m", "honestly"] or args[:2] == ["-m", "honestly.cli"]
    rest = args[2:] if module else args
    if not all(isinstance(a, str) for a in args) or rest[:1] != ["hook"] or rest[1:2] not in (["stop"], ["pre"]):
        return None
    tail = rest[2:]
    if tail and not (len(tail) == 2 and tail[0] == "--agent"):
        return None
    if not (module or stem(command) in NAMES):
        return None
    return Entry(command, rest[1], tail[1] if tail else None, module)


def parse_entry(hook):
    """The Entry of one entry in a settings file, shell form or exec form; None when it is not ours."""
    if not isinstance(hook, dict) or not isinstance(hook.get("command"), str):
        return None
    if isinstance(hook.get("args"), list):
        return _parse_args(hook["command"], hook["args"])
    return parse_line(hook["command"])


def is_ours(hook) -> bool:
    return parse_entry(hook) is not None


def plain_word(path: str) -> bool:
    """No shell needs this path quoted."""
    return bool(_PLAIN.fullmatch(path))


def is_windows_path(path: str) -> bool:
    return bool(_WINDOWS.match(path))


def shell_word(path: str) -> str:
    """The path as one word on a hook line. POSIX quoting makes `$(...)`, backticks, quotes and parentheses inert. A Windows
    path may be read by Git Bash, cmd or PowerShell, and double quotes are the only ones they share."""
    if plain_word(path):
        return path
    if is_windows_path(path):
        return f'"{path}"'
    import shlex
    return shlex.quote(path)


def _interpreter_exists(path: str) -> bool:
    """A script whose interpreter went away (`brew upgrade`, a deleted venv) exists and still cannot start."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(1024)
    except OSError:
        return False
    if not head.startswith(b"#!"):
        return True
    lines = head.decode("utf-8", "ignore").splitlines()
    words = lines[0][2:].split()
    if not words:
        return False
    if len(lines) > 1 and lines[1].startswith("'''exec'"):   # pip's trampoline for an interpreter path with a space or a long path
        m = re.match(r"""'''exec' (?:"([^"]+)"|(\S+))""", lines[1])
        if m:
            return os.path.exists(m.group(1) or m.group(2))
    return os.path.exists(words[0])


def runnable(exe: str) -> bool:
    """True when the program of a hook entry can start. A file alone is not enough: it needs its execute bit and its interpreter."""
    if not exe:
        return False
    if not re.search(r"[\\/]", exe):
        import shutil
        return shutil.which(exe) is not None
    if os.name == "nt":
        return os.path.exists(exe) or os.path.exists(exe + ".exe")   # exists() does not try PATHEXT, and pip's launcher strips .exe from argv[0]
    return os.path.isfile(exe) and os.access(exe, os.X_OK) and _interpreter_exists(exe)
