"""Per-session cache of audit findings, so a repeated `honestly audit` costs milliseconds instead of a full re-parse.

A session's entry is keyed on the file's size and mtime, its subagent files, the rule sources and the active config, and it also
remembers the background task files it read, so any of those changing invalidates it. Stored under ~/.honestly/cache/, one entry per
session (`honestly audit --clear-cache` empties it); safe to delete at any time.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict

from . import store
from .audit import Finding
from .redact import redact


def cache_dir() -> str:
    return os.path.join(os.path.expanduser("~/.honestly"), "cache")


_RULES_SIG = ""


def rules_signature() -> str:
    """Hash of the rule sources: a rule change must not serve stale verdicts, whatever the version string says."""
    global _RULES_SIG
    if not _RULES_SIG:
        h = hashlib.sha1()
        here = os.path.dirname(__file__)
        for name in sorted(os.listdir(here)):
            if name.endswith(".py") and name != "cache.py":
                with open(os.path.join(here, name), "rb") as fh:
                    h.update(fh.read())
        _RULES_SIG = h.hexdigest()[:16]
    return _RULES_SIG


def _session_prefix(path: str) -> str:
    return hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()[:20]


def key(path: str, extra: str = "") -> str:
    st = os.stat(path)
    state = hashlib.sha1(f"{st.st_size}|{st.st_mtime_ns}|{rules_signature()}|{extra}".encode("utf-8")).hexdigest()
    return f"{_session_prefix(path)}-{state[:24]}"


def _dep_state(path: str):
    st = os.stat(path)
    return [st.st_size, st.st_mtime_ns]


def _well_formed(f: Finding) -> bool:
    tools = f.tools_after_edit
    return (all(isinstance(v, str) for k, v in vars(f).items() if k not in ("turn", "tools_after_edit")) and isinstance(f.turn, int)
            and isinstance(tools, list) and all(isinstance(t, str) for t in tools))


def get(path: str, extra: str = ""):
    try:
        with open(os.path.join(cache_dir(), key(path, extra) + ".json"), encoding="utf-8") as fh:
            entry = json.load(fh)
        for dep, state in entry["deps"].items():
            # a background task's output is part of what the verdict was made from. A task file that is gone cannot be read again: what it said still stands.
            if os.path.exists(dep) and _dep_state(dep) != state:
                return None
        found = [Finding(**r) for r in entry["findings"]]
        return found if all(_well_formed(f) for f in found) else None   # a damaged entry is a miss: the session is read again
    except Exception:
        return None


def _scrubbed(value):
    if isinstance(value, str):
        return redact(value)
    return [_scrubbed(v) for v in value] if isinstance(value, list) else value


_pruned = False
UNUSED_FOR = 90 * 24 * 3600


def _prune_unused(folder: str) -> None:
    """Once per run: sessions whose logs are gone leave entries nothing will ask for again."""
    global _pruned
    if _pruned:
        return
    _pruned = True
    limit = time.time() - UNUSED_FOR
    for entry in os.scandir(folder):
        if entry.stat().st_mtime < limit:
            os.remove(entry.path)


def put(path: str, extra: str, findings, deps=()) -> None:
    """Findings quote replies, commands and their output, so they are scrubbed first. Written whole or not at all, and one entry per
    session: a new one replaces the session's older ones, so the cache does not grow every time a log does."""
    folder = cache_dir()
    name = key(path, extra) + ".json"
    final = os.path.join(folder, name)
    tmp = f"{final}.{os.getpid()}.tmp"
    try:
        entry = {"deps": {d: _dep_state(d) for d in deps if os.path.exists(d)}, "findings": [{k: _scrubbed(v) for k, v in asdict(f).items()} for f in findings]}
        with store.open_private(tmp) as fh:
            json.dump(entry, fh, ensure_ascii=False)
        os.replace(tmp, final)
        prefix = _session_prefix(path) + "-"
        for other in os.listdir(folder):
            if other.startswith(prefix) and other != name:
                os.remove(os.path.join(folder, other))
        _prune_unused(folder)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def clear() -> int:
    n = 0
    if os.path.isdir(cache_dir()):
        for name in os.listdir(cache_dir()):
            if name.endswith(".json"):
                try:
                    os.remove(os.path.join(cache_dir(), name)); n += 1
                except Exception:
                    pass
    return n
