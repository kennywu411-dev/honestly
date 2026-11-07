"""User-adjustable rules, so a false flag can be silenced in one command instead of waiting for a release.

Two files, both optional and both plain JSON:
  ~/.honestly/config.json      applies everywhere
  <project>/.honestly.json     applies to one project (merged on top; lists are unioned)

Keys:
  strictness       "strict" | "normal" | "lenient"   what guard blocks (see STRICTNESS)
  ignore           ["fixed bed reactor", ...]        a sentence containing one of these is never a claim
  verify_commands  ["make verify", ...]              commands that count as running the tests
  off              ["sent", "checked", ...]          claim categories switched off
  language         "auto" | "zh" | "en"              language of guard messages
"""
from __future__ import annotations

import json
import os
import re

from . import rules

STRICTNESS = {
    "strict": ("unbacked", "contradicted", "weak"),   # also blocks claims judged only by looking at an image
    "normal": ("unbacked", "contradicted"),
    "lenient": ("contradicted",),                      # only when the check actually failed; the pipe check is off
}
LIST_KEYS = ("ignore", "verify_commands", "off")
DEFAULTS = {"strictness": "normal", "ignore": [], "verify_commands": [], "off": [], "language": "auto"}
PROJECT_FILE = ".honestly.json"


def user_path() -> str:
    return os.path.join(os.path.expanduser("~/.honestly"), "config.json")


def project_path(cwd: str | None) -> str:
    return os.path.join(cwd or os.getcwd(), PROJECT_FILE)


def _read(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
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
            pass
        raise


def _clean(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if k in LIST_KEYS:
            out[k] = [str(x).strip() for x in (v if isinstance(v, list) else [v]) if str(x).strip()]
        elif k == "strictness":
            out[k] = v if v in STRICTNESS else "normal"
        elif k == "language":
            out[k] = v if v in ("auto", "zh", "en") else "auto"
    return out


def load(cwd: str | None = None) -> dict:
    cfg = dict(DEFAULTS)
    for path in (user_path(), project_path(cwd)):
        for k, v in _clean(_read(path)).items():
            cfg[k] = sorted(set(cfg[k]) | set(v)) if k in LIST_KEYS else v
    return cfg


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
    return "\n".join(lines)
