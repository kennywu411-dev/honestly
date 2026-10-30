"""A one-line "newer version available" note at the end of `honestly catches`.

Checks PyPI at most once a day, only from the CLI (never from the hooks), with a short timeout, and
never fails the command. Set HONESTLY_NO_UPDATE_CHECK=1 to turn it off entirely.
"""
from __future__ import annotations

import json
import os
import re
import time

PYPI_URL = "https://pypi.org/pypi/honestly/json"
CACHE_TTL = 24 * 3600


def cache_path() -> str:
    return os.path.join(os.path.expanduser("~/.honestly"), "update-check.json")


def _parse(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def _fetch_latest(timeout: float = 2.0) -> str:
    import urllib.request
    with urllib.request.urlopen(PYPI_URL, timeout=timeout) as r:
        return str(json.load(r)["info"]["version"])


def latest_version(now: float | None = None) -> str:
    """Latest version on PyPI, from the daily cache when it is fresh; '' when the network is unavailable."""
    if os.environ.get("HONESTLY_NO_UPDATE_CHECK") == "1":
        return ""
    now = now if now is not None else time.time()
    try:
        with open(cache_path(), encoding="utf-8") as fh:
            c = json.load(fh)
        if now - float(c.get("ts", 0)) < CACHE_TTL:
            return str(c.get("latest", ""))
    except Exception:
        pass
    try:
        latest = _fetch_latest()
    except Exception:
        return ""
    try:
        os.makedirs(os.path.dirname(cache_path()), exist_ok=True)
        with open(cache_path(), "w", encoding="utf-8") as fh:
            json.dump({"ts": now, "latest": latest}, fh)
    except Exception:
        pass
    return latest


def update_note(current: str, zh: bool = False) -> str:
    """One line when a newer release exists, otherwise ''."""
    latest = latest_version()
    if not latest or _parse(latest) <= _parse(current):
        return ""
    if zh:
        return f"有新版 {latest}（你用的是 {current}）：pip install -U honestly"
    return f"A newer honestly is out: {latest} (you have {current}). Update with: pip install -U honestly"
