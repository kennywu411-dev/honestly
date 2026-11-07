"""Entry point for the Claude Code plugin: runs honestly from this checkout, no pip install needed.

    python3 hooks/run.py hook stop     (what the plugin's hooks call)
    python3 hooks/run.py pr-note --gh  (any other honestly command)

When `honestly guard install` has already put honestly's hooks into ~/.claude/settings.json,
the plugin's hooks step aside so a reply is not checked twice.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))


def _guard_installed() -> bool:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    path = os.path.join(base, "settings.json")
    try:
        with open(path, encoding="utf-8") as f:
            hooks = (json.load(f) or {}).get("hooks") or {}
    except Exception:
        return False
    for groups in hooks.values():
        for group in groups or []:
            for h in (group or {}).get("hooks") or []:
                if "honestly hook" in str(h.get("command", "")):
                    return True
    return False


def main() -> int:
    args = sys.argv[1:]
    if sys.version_info < (3, 9):
        return 0   # never block the assistant because of an old interpreter
    if args[:1] == ["hook"] and _guard_installed():
        return 0
    from honestly.cli import main as cli_main
    return cli_main(args) or 0


if __name__ == "__main__":
    sys.exit(main())
