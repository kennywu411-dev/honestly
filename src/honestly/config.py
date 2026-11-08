"""User-adjustable rules, so a false flag can be silenced in one command instead of waiting for a release.

Two files, both optional and both plain JSON:
  ~/.honestly/config.json      applies everywhere
  <project>/.honestly.json     applies to one project. It may only tighten: anything that relaxes the rules
                               takes effect after `honestly trust` records this exact file (see load)

Keys:
  strictness       "strict" | "normal" | "lenient"   what guard blocks (see STRICTNESS)
  ignore           ["fixed bed reactor", ...]        a sentence containing one of these is never a claim
  verify_commands  ["make verify", ...]              commands that count as running the tests
  off              ["sent", "checked", ...]          claim categories switched off
  language         "auto" | "zh" | "en"              language of guard messages
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time

from . import rules

STRICTNESS = {
    "strict": ("unbacked", "contradicted", "weak"),   # also claims about anything other than code, weak evidence, and a filter or a head on a narrowed test run
    "normal": ("unbacked", "contradicted"),            # claims about code only, and pipes that hide a whole run's result
    "lenient": ("contradicted",),                      # only when the check actually failed; the pipe check is off
}
LIST_KEYS = ("ignore", "verify_commands", "off")
DEFAULTS = {"strictness": "normal", "ignore": [], "verify_commands": [], "off": [], "language": "auto"}
PROJECT_FILE = ".honestly.json"
MAX_CONFIG_BYTES = 64 * 1024
STRICTNESS_RANK = {"lenient": 0, "normal": 1, "strict": 2}
NOTICES_KEPT = 200


def user_path() -> str:
    return os.path.join(os.path.expanduser("~/.honestly"), "config.json")


def project_path(cwd: str | None) -> str:
    return os.path.join(cwd or os.getcwd(), PROJECT_FILE)


def _read_small_file(path: str):
    """The file's bytes, or None unless it is an ordinary file of a sensible size. A repository can ship a symlink to /dev/zero or
    a FIFO under this name, so nothing is read before that is known, and opening never blocks."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
    except (OSError, ValueError):
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CONFIG_BYTES:
            return None
        chunks, left = [], MAX_CONFIG_BYTES + 1
        while left > 0:
            chunk = os.read(fd, left)
            if not chunk:
                break
            chunks.append(chunk)
            left -= len(chunk)
        data = b"".join(chunks)
        return data if len(data) <= MAX_CONFIG_BYTES else None
    except OSError:
        return None
    finally:
        os.close(fd)


def _read(path: str) -> dict:
    data = _read_small_file(path)
    if data is None:
        return {}
    try:
        d = json.loads(data.decode("utf-8"))
        return d if isinstance(d, dict) else {}
    except (ValueError, RecursionError):
        return {}


def _write(path: str, d: dict) -> None:
    write_json_atomic(path, d, backup=False)


def write_json_atomic(path: str, obj, backup: bool = True) -> None:
    """Write JSON so that a crash or a concurrent writer never leaves a half-written file.

    The temporary file is created next to the real target (a symlinked dotfile is written through, not replaced),
    then moved over it with os.replace. With backup=True the previous file is copied to a backup whose name is never
    reused, so an install followed by an uninstall in the same second keeps the original.
    """
    import shutil, tempfile, time
    target = os.path.realpath(path)
    folder = os.path.dirname(target) or "."
    os.makedirs(folder, exist_ok=True)
    if backup and os.path.exists(target):
        stem = target + ".bak-honestly-" + time.strftime("%Y%m%d%H%M%S")
        bak, n = stem, 1
        while os.path.exists(bak):
            bak, n = f"{stem}-{n}", n + 1
        shutil.copy2(target, bak)
    fd, tmp = tempfile.mkstemp(prefix=".honestly-", suffix=".json", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        if os.path.exists(target):
            shutil.copymode(target, tmp)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass   # the temporary file is already gone; the original error below is the one that matters
        raise


def _clean(d: dict) -> dict:
    """The settings a file holds, with anything of the wrong shape dropped: a bad value must never take the guard down."""
    out = {}
    for k, v in d.items():
        if k in LIST_KEYS:
            out[k] = [str(x).strip() for x in (v if isinstance(v, list) else [v]) if str(x).strip()]
        elif k == "strictness" and isinstance(v, str) and v in STRICTNESS:
            out[k] = v
        elif k == "language" and isinstance(v, str) and v in ("auto", "zh", "en"):
            out[k] = v
    return out


def _relaxing(settings: dict, strictness: str) -> list:
    """Which of these settings make the guard hold less than `strictness` and the user's own lists would."""
    out = [k for k in LIST_KEYS if settings.get(k)]
    wanted = settings.get("strictness")
    if wanted and STRICTNESS_RANK[wanted] < STRICTNESS_RANK[strictness]:
        out.append(f"strictness: {wanted}")
    return out


def load(cwd: str | None = None) -> dict:
    """The user's settings, then the project's. A project file comes with the code, so whoever wrote the code wrote it: it may
    tighten, and may relax only once the user has trusted that exact file."""
    cfg = dict(DEFAULTS)
    for k, v in _clean(_read(user_path())).items():
        cfg[k] = sorted(set(cfg[k]) | set(v)) if k in LIST_KEYS else v
    path = project_path(cwd)
    project = _clean(_read(path))
    trusted = bool(_relaxing(project, cfg["strictness"])) and is_trusted(path)
    for k, v in project.items():
        if k in LIST_KEYS:
            if trusted:
                cfg[k] = sorted(set(cfg[k]) | set(v))
        elif k != "strictness" or trusted or STRICTNESS_RANK[v] >= STRICTNESS_RANK[cfg[k]]:
            cfg[k] = v
    return cfg


# ------------------------------------------------------------------- trust
def trust_path() -> str:
    return os.path.join(os.path.expanduser("~/.honestly"), "trusted.json")


def notices_path() -> str:
    return os.path.join(os.path.expanduser("~/.honestly"), "notices.json")


def _trust_key(path: str) -> str:
    folder, name = os.path.split(os.path.abspath(path))
    return os.path.join(os.path.realpath(folder), name)


def _digest(path: str):
    """The hash of a project file; None for a symlink, which could point at a file trusted for another folder."""
    try:
        if stat.S_ISLNK(os.lstat(path).st_mode):
            return None
    except (OSError, ValueError):
        return None
    data = _read_small_file(path)
    return hashlib.sha256(data).hexdigest() if data is not None else None


def is_trusted(path: str) -> bool:
    digest = _digest(path)
    return bool(digest) and _read(trust_path()).get(_trust_key(path)) == digest


def project_relaxes(cwd: str | None = None) -> list:
    """What the project file would relax, trusted or not."""
    user = _clean(_read(user_path()))
    return _relaxing(_clean(_read(project_path(cwd))), user.get("strictness", DEFAULTS["strictness"]))


def ignored_settings(cwd: str | None = None) -> list:
    """What the project file wants to relax and is being refused."""
    relaxes = project_relaxes(cwd)
    return [] if not relaxes or is_trusted(project_path(cwd)) else relaxes


def trust(cwd: str | None = None) -> str:
    path = project_path(cwd)
    digest = _digest(path)
    if digest is None:
        return f"not trusted: {path} is missing, a symlink, or not an ordinary small file"
    d = _read(trust_path())
    d[_trust_key(path)] = digest
    write_json_atomic(trust_path(), d, backup=False)
    return f"trusted {path}; if the file changes, its settings are ignored again until you trust it again"


def untrust(cwd: str | None = None) -> str:
    path = project_path(cwd)
    d = _read(trust_path())
    if d.pop(_trust_key(path), None) is None:
        return f"not trusted anyway: {path}"
    write_json_atomic(trust_path(), d, backup=False)
    return f"no longer trusted: {path}"


def trusted_files() -> list:
    return [(p, _digest(p) == h) for p, h in sorted(_read(trust_path()).items())]


def first_notice(cwd: str | None, session: str) -> bool:
    """True once per conversation and version of the file, so the note is seen and does not nag."""
    key = hashlib.sha256(f"{_trust_key(project_path(cwd))}|{_digest(project_path(cwd))}|{session}".encode("utf-8", "replace")).hexdigest()
    seen = _read(notices_path())
    if key in seen:
        return False
    seen[key] = time.time()
    newest = sorted(seen.items(), key=lambda kv: kv[1] if isinstance(kv[1], (int, float)) else 0)[-NOTICES_KEPT:]
    try:
        write_json_atomic(notices_path(), dict(newest), backup=False)
    except OSError:
        pass
    return True


_BASE_TEST = rules.VERIFY["test"]


def apply(cfg: dict) -> None:
    """Push the config into the rule tables. Idempotent; called by the hooks and the CLI before judging anything."""
    rules.IGNORE_PHRASES = tuple(p.lower() for p in cfg.get("ignore", []))
    rules.DISABLED = frozenset(cfg.get("off", []))
    extra = [re.escape(c) for c in cfg.get("verify_commands", [])]
    rules.VERIFY["test"] = re.compile(_BASE_TEST.pattern + ("|" + "|".join(extra) if extra else ""), _BASE_TEST.flags)
    from . import hooks, audit   # rebuilt tables that were derived from VERIFY at import time
    hooks.TEST_LIKE = re.compile("|".join(p.pattern for k, p in rules.VERIFY.items() if k in ("test", "build")), re.I)
    hooks.PRE_EXTRA = re.compile("|".join(extra)) if extra else None
    audit.rebuild_verified_spec()


def blocked_verdicts(cfg: dict) -> tuple:
    return STRICTNESS.get(cfg.get("strictness", "normal"), STRICTNESS["normal"])


# ------------------------------------------------------------------ editing
def set_value(key: str, value, project: bool = False, cwd: str | None = None) -> str:
    path = project_path(cwd) if project else user_path()
    d = _read(path)
    if key == "strictness" and value not in STRICTNESS:
        return f"strictness must be one of {', '.join(STRICTNESS)}"
    if key == "language" and value not in ("auto", "zh", "en"):
        return "language must be auto, zh or en"
    d[key] = value
    _write(path, d)
    return f"{key} = {value}  ({path})"


def add_to(key: str, value: str, project: bool = False, cwd: str | None = None) -> str:
    path = project_path(cwd) if project else user_path()
    d = _read(path)
    lst = [str(x) for x in d.get(key, []) if str(x).strip()]
    if value in lst:
        return f"already in {key}: {value!r}  ({path})"
    lst.append(value)
    d[key] = lst
    _write(path, d)
    return f"added to {key}: {value!r}  ({path})"


def remove_from(key: str, value: str, project: bool = False, cwd: str | None = None) -> str:
    path = project_path(cwd) if project else user_path()
    d = _read(path)
    lst = [str(x) for x in d.get(key, []) if str(x) != value]
    if len(lst) == len(d.get(key, [])):
        return f"not in {key}: {value!r}  ({path})"
    d[key] = lst
    _write(path, d)
    return f"removed from {key}: {value!r}  ({path})"


def show(cwd: str | None = None) -> str:
    cfg = load(cwd)
    lines = [f"strictness       {cfg['strictness']}   (blocks: {', '.join(blocked_verdicts(cfg))})",
             f"language         {cfg['language']}",
             f"ignore           {', '.join(repr(x) for x in cfg['ignore']) or '(none)'}",
             f"verify_commands  {', '.join(repr(x) for x in cfg['verify_commands']) or '(none)'}",
             f"off              {', '.join(cfg['off']) or '(none)'}",
             "", f"files: {user_path()}" + (" (exists)" if os.path.exists(user_path()) else " (not created yet)"),
             f"       {project_path(cwd)}" + (" (exists)" if os.path.exists(project_path(cwd)) else " (none)")]
    ignored = ignored_settings(cwd)
    if ignored:
        lines.append(f"       ignored from that file until you run `honestly trust`: {', '.join(ignored)}")
    elif project_relaxes(cwd):
        lines.append(f"       you trusted that file: {', '.join(project_relaxes(cwd))}")
    return "\n".join(lines)
