"""Per-session cache of audit findings, so a repeated `honestly audit` costs milliseconds instead of a full re-parse.

A session's entry is keyed on the file's size and mtime, its subagent files, the rule sources and the active config,
so any of those changing invalidates it. Stored under ~/.honestly/cache/; safe to delete at any time.
"""
from __future__ import annotations

import hashlib
import json
import os
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


def key(path: str, extra: str = "") -> str:
    st = os.stat(path)
    h = hashlib.sha1(f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime_ns}|{rules_signature()}|{extra}".encode("utf-8"))
    return h.hexdigest()


def _well_formed(f: Finding) -> bool:
    tools = f.tools_after_edit
    return (all(isinstance(v, str) for k, v in vars(f).items() if k not in ("turn", "tools_after_edit")) and isinstance(f.turn, int)
            and isinstance(tools, list) and all(isinstance(t, str) for t in tools))


def get(path: str, extra: str = ""):
    try:
        with open(os.path.join(cache_dir(), key(path, extra) + ".json"), encoding="utf-8") as fh:
            rows = json.load(fh)
        found = [Finding(**r) for r in rows]
        return found if all(_well_formed(f) for f in found) else None   # a damaged entry is a miss: the session is read again
    except Exception:
        return None


def _scrubbed(value):
    if isinstance(value, str):
        return redact(value)
    return [_scrubbed(v) for v in value] if isinstance(value, list) else value


def put(path: str, extra: str, findings) -> None:
    """Findings quote replies, commands and their output, so they are scrubbed first. Written whole or not at all."""
    final = os.path.join(cache_dir(), key(path, extra) + ".json")
    tmp = f"{final}.{os.getpid()}.tmp"
    try:
        with store.open_private(tmp) as fh:
            json.dump([{k: _scrubbed(v) for k, v in asdict(f).items()} for f in findings], fh, ensure_ascii=False)
        os.replace(tmp, final)
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
