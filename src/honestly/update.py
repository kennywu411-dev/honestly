"""A one-line "newer version available" note at the end of `honestly catches`.

Checks PyPI at most once a day, only from the CLI (never from the hooks), with a short timeout, and
never fails the command. Set HONESTLY_NO_UPDATE_CHECK=1 to turn it off entirely.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

from . import store

PYPI_URL = "https://pypi.org/pypi/honestly/json"
CACHE_TTL = 24 * 3600
RETRY_AFTER_FAILURE = 6 * 3600   # offline, every command would otherwise wait for the timeout


def cache_path() -> str:
    return os.path.join(os.path.expanduser("~/.honestly"), "update-check.json")


VERSION = re.compile(r"\d+(?:\.\d+)*(?:(?:a|b|rc|\.post|\.dev)\d+)*")   # this string gets printed, so it must be a version and nothing else


def _version_or_nothing(v) -> str:
    v = str(v or "")
    return v if VERSION.fullmatch(v) else ""


def _parse(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def _fetch_latest(timeout: float = 2.0) -> str:
    import urllib.request
    with urllib.request.urlopen(PYPI_URL, timeout=timeout) as r:
        return str(json.load(r)["info"]["version"])


def _remember(now: float, latest: str, failed: bool = False) -> None:
    try:
        with store.open_private(cache_path()) as fh:
            json.dump({"ts": now, "latest": latest, "failed": failed}, fh)
    except Exception:
        pass


def latest_version(now: float | None = None) -> str:
    """Latest version on PyPI, from the daily cache when it is fresh; '' when the network is unavailable."""
    if os.environ.get("HONESTLY_NO_UPDATE_CHECK") == "1":
        return ""
    now = now if now is not None else time.time()
    try:
        with open(cache_path(), encoding="utf-8") as fh:
            c = json.load(fh)
        age = now - float(c.get("ts", 0))
        if 0 <= age < (RETRY_AFTER_FAILURE if c.get("failed") else CACHE_TTL):
            return _version_or_nothing(c.get("latest"))
    except Exception:
        pass
    try:
        latest = _version_or_nothing(_fetch_latest())
    except Exception:
        _remember(now, "", failed=True)
        return ""
    _remember(now, latest)
    return latest


def upgrade_command(prefix: str | None = None, argv0: str | None = None) -> str:
    """The command that upgrades this copy: pipx and uv leave a file in the tool's environment, the plugin runs from its own entry point."""
    prefix = prefix if prefix is not None else sys.prefix
    argv0 = argv0 if argv0 is not None else (sys.argv[0] if sys.argv else "")
    if re.search(r"[\\/]hooks[\\/]run\.py$", argv0):
        return "claude plugin update honestly@honestly"
    if os.path.exists(os.path.join(prefix, "pipx_metadata.json")):
        return "pipx upgrade honestly"
    if os.path.exists(os.path.join(prefix, "uv-receipt.toml")):
        return "uv tool upgrade honestly"
    return "pip install -U honestly"


def update_note(current: str, zh: bool = False) -> str:
    """One line when a newer release exists, otherwise ''."""
    latest = latest_version()
    if not latest or _parse(latest) <= _parse(current):
        return ""
    if zh:
        return f"有新版 {latest}（你用的是 {current}）：{upgrade_command()}"
    return f"A newer honestly is out: {latest} (you have {current}). Update with: {upgrade_command()}"
