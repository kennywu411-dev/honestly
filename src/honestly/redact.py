"""Scrubbing for text that leaves the machine (`pr-note`, `feedback`, cards) or is stored on it (catches, cache, logs).

Each pattern is anchored on something rare (a prefix, `://`, a key name) or on a run with a bounded character class, so the
whole pass stays linear: the callers run it on whatever a command printed.
"""
from __future__ import annotations

import os
import re
import unicodedata

HIDDEN = "<redacted>"
MAX_INPUT = 1 << 20

PEM_BLOCK = re.compile(r"-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----.*?(?:-----END [A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----|\Z)", re.S)
# a prefix a vendor puts on its tokens: enough on its own, whatever surrounds it
PREFIXED = re.compile(r"(?<![A-Za-z0-9])(?:"
                      r"gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,}|glpat-[A-Za-z0-9_-]{16,}"
                      r"|npm_[A-Za-z0-9]{16,}|pypi-[A-Za-z0-9_-]{16,}|hf_[A-Za-z0-9]{20,}"
                      r"|sk-[A-Za-z0-9_-]{12,}|[rs]k_(?:live|test)_[A-Za-z0-9]{10,}|whsec_[A-Za-z0-9]{10,}"
                      r"|xox[a-z]-[A-Za-z0-9-]{10,}|xapp-[A-Za-z0-9-]{10,}"
                      r"|AIza[A-Za-z0-9_-]{30,}|ya29\.[A-Za-z0-9_-]{20,}"
                      r"|(?:AKIA|ASIA|ABIA|ACCA|AGPA|AIDA|AIPA|AROA|ANPA|ANVA)[A-Z0-9]{16}"
                      r"|eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}(?:\.[A-Za-z0-9_-]*)?)")
WEBHOOK = re.compile(r"https?://(?:hooks\.slack\.com|discord(?:app)?\.com/api/webhooks|[\w.-]{1,60}\.webhook\.office\.com)[^\s'\"<>)]*", re.I)
URL_USER = re.compile(r"(://)[^\s/'\"<>]{0,512}@")
URL_QUERY = re.compile(r"(https?://[^\s?#'\"<>]{1,2048}\?)[^\s#'\"<>)]+", re.I)
URL_HOST = re.compile(r"(://(?:<redacted>@)?)([A-Za-z0-9.-]{1,253})")
PRIVATE_HOST = re.compile(r"(?:^|\.)(?:internal|corp|local|lan|intranet|intra)(?:\.|$)", re.I)
PRIVATE_IP = re.compile(r"(?<![\d.])(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?![\d.])")
AUTH_HEADER = re.compile(r"(?i)\b((?:proxy-)?authorization[\"']?\s*[:=]\s*)(?:(?:bearer|basic|token|digest|negotiate|apikey)\s+)?(\"[^\"\n]*\"|'[^'\n]*'|[^\s'\"]+)")
COOKIE_HEADER = re.compile(r"(?i)\b((?:set-)?cookie[\"']?\s*[:=]\s*)[^'\"\n]+")
BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}")
ASSIGNMENT = re.compile(r"(?<![\w.-])([\w.-]{1,128})([\"']?\s*[=:]\s*)(\"[^\"\n]*\"|'[^'\n]*'|[^\s'\"]+)")
SECRET_NAME = re.compile(r"(?i)password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|auth(?!or)|credential|private[_-]?key|session[_-]?id|cookie")
SECRET_LONG_FLAG = re.compile(r"(?i)((?:^|\s)--[\w-]{0,60}(?:password|passwd|token|secret|api-?key|auth(?!or)|credential)[\w-]{0,60}[=\s]+)(\"[^\"\n]*\"|'[^'\n]*'|\S+)")
SECRET_SHORT_FLAG = re.compile(r"((?:^|\s)(?:-p|-u)[=\s]?)(\"[^\"\n]*\"|'[^'\n]*'|\S+)")
UUID = re.compile(r"(?<![0-9a-fA-F-])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9a-fA-F-])")
LONG_RUN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9+/=_-]{20,}")
HEX_RUN = re.compile(r"[0-9a-fA-F]{32,}")
BASE32_RUN = re.compile(r"[A-Z2-7]{32,}")
EMAIL_DOMAIN = re.compile(r"@[\w-]{1,63}\.[\w.]{1,253}")
EMAIL_LOCAL = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._+-")
HOME_DIR = re.compile(r"(?<![\w.-])(?:/Users|/home)/[^/\s'\"]+|(?<![\w/])/root(?=/)|(?<![A-Za-z])[A-Za-z]:[\\/]+Users[\\/]+[^\\/\n'\"]+", re.I)
UNC_ROOT = re.compile(r"(?<![\w\\])\\\\+[\w.-]+\\+[\w$.-]+")
CARD_NUMBER = re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])")


def _home_forms() -> list:
    home = os.environ.get("HOME") or os.path.expanduser("~")
    if not home or len(home.strip("/\\")) < 2:
        return []
    forms = {home, unicodedata.normalize("NFC", home), unicodedata.normalize("NFD", home)}
    return sorted(forms, key=len, reverse=True)


def _scrub_home(s: str) -> str:
    for form in _home_forms():
        s = re.sub(re.escape(form) + r"(?![\w.-])", "~", s)
    return HOME_DIR.sub("~", s)


def _is_secret_name(key: str, sep: str) -> bool:
    if SECRET_NAME.search(key):
        return True
    low = key.lower()
    if low.endswith(("_pass", "-pass", ".pass", "_key", "-key", ".key")) or key == "PASS":
        return True
    return low in ("pass", "key") and "=" in sep


def _assignment(m) -> str:
    if not _is_secret_name(m.group(1), m.group(2)):
        return m.group(0)
    return m.group(1) + m.group(2) + HIDDEN


def _classes_flip(text: str) -> float:
    """How often neighbouring characters change class (lower, upper, digit). Words and camelCase rarely do, random tokens do all the time."""
    kinds = ["l" if c.islower() else "u" if c.isupper() else "d" for c in text if c.isalnum()]
    if len(kinds) < 2:
        return 0.0
    return sum(a != b for a, b in zip(kinds, kinds[1:])) / (len(kinds) - 1)


def _looks_random(run: str) -> bool:
    core = run.strip("=-_/+")
    if len(core) < 20:
        return False
    if HEX_RUN.fullmatch(core) or BASE32_RUN.fullmatch(core):
        return True
    alnum = "".join(c for c in core if c.isalnum())
    if len(alnum) < 20:
        return False
    digits = sum(c.isdigit() for c in alnum)
    flips = _classes_flip(core)
    if flips >= 0.33 or (digits >= 6 and flips >= 0.2):
        return True
    return any(len(p) >= 24 and (p.isdigit() or p.isalpha() and (p.islower() or p.isupper())) and p != "" for p in re.split(r"[/+=_-]", core))


def _long_run(m) -> str:
    run = m.group(0)
    return HIDDEN if _looks_random(run) else run


def _emails(s: str) -> str:
    out, pos = [], 0
    for m in EMAIL_DOMAIN.finditer(s):
        start = m.start()
        low = start
        while low > pos and start - low < 64 and s[low - 1] in EMAIL_LOCAL:
            low -= 1
        if low == start:
            continue
        out.append(s[pos:low])
        out.append("<email>")
        pos = m.end()
    out.append(s[pos:])
    return "".join(out)


def _host(m) -> str:
    host = m.group(2)
    return m.group(1) + "<host>" if PRIVATE_HOST.search(host) else m.group(0)


def _luhn(digits: str) -> bool:
    total = 0
    for i, c in enumerate(reversed(digits)):
        n = int(c)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _card(m) -> str:
    digits = re.sub(r"\D", "", m.group(0))
    return HIDDEN if 13 <= len(digits) <= 19 and _luhn(digits) else m.group(0)


def strip_controls(s: str) -> str:
    """Terminal escapes, bidi overrides and zero-width characters go; tabs and line breaks stay."""
    return "".join(c for c in s if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf", "Co", "Cs"))


def redact(s: str) -> str:
    """Secrets, addresses and home directories out of `s`. The result is stable: redacting it again changes nothing."""
    s = str(s or "")[:MAX_INPUT]
    s = PEM_BLOCK.sub(HIDDEN, s)
    s = WEBHOOK.sub(HIDDEN, s)
    s = URL_USER.sub(lambda m: m.group(1) + HIDDEN + "@", s)
    s = URL_QUERY.sub(lambda m: m.group(1) + HIDDEN, s)
    s = PREFIXED.sub(HIDDEN, s)
    s = AUTH_HEADER.sub(lambda m: m.group(1) + HIDDEN, s)
    s = COOKIE_HEADER.sub(lambda m: m.group(1) + HIDDEN, s)
    s = BEARER.sub(lambda m: m.group(1) + HIDDEN, s)
    s = ASSIGNMENT.sub(_assignment, s)
    s = SECRET_LONG_FLAG.sub(lambda m: m.group(1) + HIDDEN, s)
    s = SECRET_SHORT_FLAG.sub(lambda m: m.group(1) + HIDDEN, s)
    s = _scrub_home(s)
    s = UNC_ROOT.sub("<host>", s)
    s = UUID.sub(HIDDEN, s)
    s = LONG_RUN.sub(_long_run, s)
    s = _emails(s)
    s = URL_HOST.sub(_host, s)
    s = PRIVATE_IP.sub("<host>", s)
    return CARD_NUMBER.sub(_card, s)
