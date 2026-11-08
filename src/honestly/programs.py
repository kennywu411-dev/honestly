"""Which file runs when honestly starts another program.

On Windows, a bare name is looked up in the current directory before System32, and hooks run in the project: a repository's
powershell.exe or git.exe would be the one that runs. An empty PATH entry does the same on POSIX.
"""
from __future__ import annotations

import os


def program(name: str, windows: bool | None = None) -> str:
    """The path to run `name` from, never the current directory. On a POSIX system with a clean PATH, the bare name, as before."""
    windows = os.name == "nt" if windows is None else windows
    entries = os.environ.get("PATH", "").split(os.pathsep)
    if not windows and "" not in entries and "." not in entries:
        return name
    here = os.path.realpath(os.getcwd())
    extensions = [e for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e] if windows else [""]
    for entry in entries:
        if not os.path.isabs(entry) or os.path.realpath(entry) == here:
            continue
        for ext in extensions:
            path = os.path.join(entry, name + ext)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
    raise FileNotFoundError(name)
