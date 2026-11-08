"""honestly's own folder, ~/.honestly: private, bounded in size, and removable with one command.

What is written here describes private work, so the folder is 0700 and its files 0600. Nothing is followed through a symlink:
a link planted under one of these names must not turn a log write into a write somewhere else.
"""
from __future__ import annotations

import errno
import os
import shutil
import stat

POSIX_MODES = os.name != "nt"   # on Windows mode bits protect nothing and every file reads as loose: the user profile's own permissions do this job
MAX_LOG_BYTES = 4 << 20   # then the log becomes <name>.1, replacing the previous one
RECORDED = ("catches.jsonl", "catches.jsonl.1", "hook-errors.log", "hook-errors.log.1", "update-check.json", "notices.json", "notify.last",
            "honestly-card.svg", "honestly-card.png", "honestly-catches.svg", "honestly-catches.png")


def folder() -> str:
    return os.path.join(os.path.expanduser("~"), ".honestly")


def _private_folder(path: str) -> None:
    os.makedirs(path, mode=0o700, exist_ok=True)
    if POSIX_MODES and os.path.abspath(path).startswith(os.path.abspath(folder())):
        here = os.lstat(path)
        if stat.S_ISDIR(here.st_mode) and stat.S_IMODE(here.st_mode) & 0o077:
            os.chmod(path, 0o700)


def open_private(path: str, mode: str = "w"):
    """A text file only this user can read. Raises OSError when `path` is a symlink."""
    if os.path.islink(path):   # O_NOFOLLOW below also closes the race, where the system has it
        raise OSError(errno.ELOOP, "refusing to write through a symlink", path)
    _private_folder(os.path.dirname(path) or ".")
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if mode == "a" else os.O_TRUNC) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags, 0o600)
    try:
        if POSIX_MODES and hasattr(os, "fchmod") and stat.S_IMODE(os.fstat(fd).st_mode) & 0o077:
            os.fchmod(fd, 0o600)
        return os.fdopen(fd, mode, encoding="utf-8")
    except BaseException:
        os.close(fd)
        raise


def append_line(path: str, line: str) -> None:
    """One more line in a log that rotates at MAX_LOG_BYTES. A failure is the caller's to swallow."""
    try:
        if os.lstat(path).st_size > MAX_LOG_BYTES:
            os.replace(path, path + ".1")
    except OSError:
        pass
    with open_private(path, "a") as fh:
        fh.write(line if line.endswith("\n") else line + "\n")


def tighten() -> None:
    """Bring a folder made by an older version, or by a command with a loose umask, to 0700 and 0600."""
    if not POSIX_MODES:
        return
    top = folder()
    try:
        info = os.lstat(top)
    except OSError:
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_IMODE(info.st_mode) & 0o077:   # this runs on every hook: an already private folder costs one call
        return
    for base, _dirs, files in os.walk(top, followlinks=False):
        for name in [base] + [os.path.join(base, f) for f in files]:
            try:
                info = os.lstat(name)
                if not stat.S_ISLNK(info.st_mode) and stat.S_IMODE(info.st_mode) & 0o077:
                    os.chmod(name, 0o700 if stat.S_ISDIR(info.st_mode) else 0o600)
            except OSError:
                pass


def purge(everything: bool = False, dry_run: bool = False) -> list:
    """Delete what honestly recorded, keeping the settings; with `everything`, the whole folder. Returns the paths. Links are removed, not followed."""
    top = folder()
    if not os.path.lexists(top):
        return []
    if everything:
        targets = [os.path.join(top, n) for n in sorted(os.listdir(top))] if not os.path.islink(top) else []
    else:
        targets = [os.path.join(top, n) for n in RECORDED + ("cache",) if os.path.lexists(os.path.join(top, n))]
    if dry_run:
        return targets
    for path in targets:
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
        except OSError:
            pass
    if everything:
        try:
            os.rmdir(top)
        except OSError:
            pass
    return targets
