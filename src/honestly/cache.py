"""Per-session cache of audit findings, so a repeated `honestly audit` costs milliseconds instead of a full re-parse.

A session's entry is keyed on the file's size and mtime, its subagent files, the rule sources and the active config,
so any of those changing invalidates it. Stored under ~/.honestly/cache/; safe to delete at any time.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict

from .audit import Finding


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


def get(path: str, extra: str = ""):
    try:
        with open(os.path.join(cache_dir(), key(path, extra) + ".json"), encoding="utf-8") as fh:
            rows = json.load(fh)
        return [Finding(**r) for r in rows]
    except Exception:
        return None


def put(path: str, extra: str, findings) -> None:
    try:
        os.makedirs(cache_dir(), exist_ok=True)
        tmp = os.path.join(cache_dir(), key(path, extra) + ".json")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump([asdict(f) for f in findings], fh, ensure_ascii=False)
    except Exception:
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
