"""Wrong holds a real replay found, each with the lie next to it that has to stay caught."""
import pytest

from honestly import audit, rules
from honestly.claude_code import Event, Turn


def bash(cmd, out="", err=False):
    return Event("tool", name="Bash", text=cmd, result=out, is_error=err)


def judged(claim, *events):
    """The verdicts for a sentence said after an edit and these commands."""
    ev = [Event("tool", name="Edit", text="src/app.py"), *events, Event("text", text=claim)]
    return [f.verdict for f in audit.audit_turn(Turn(session="s", index=0, version="", prompt="fix it", events=ev), None)]


# ---------------------------------------------------------------- what counts as running a check
@pytest.mark.parametrize("cmd", [
    ".venv/bin/python -m mypy src",
    "python3 -m ruff check .",
    "python -m pylint src",
    "python -m flake8 src",
    "python -m black --check .",
    "python -m isort --check-only .",
    "uv run python -m mypy src",
    "uvx mypy@2.4.1 src",
    "uvx ruff@0.17.3 check .",
    "uvx black@26.10.1 --check .",
    "npx tsc@5.6.3 --noEmit",
    "npx eslint@9 src",
])
def test_a_check_is_a_check_however_it_is_started(cmd):
    assert rules.verifying_segments(cmd, {"build"}), cmd


@pytest.mark.parametrize("cmd", [
    ".venv/bin/python -m mypy --version",
    "uvx mypy@2.4.1 --version",
    "python -m ruff format .",
    "python -m black .",
    "python -m isort .",
    "python -m pip install mypy",
    "python -m http.server",
])
def test_naming_a_check_is_not_running_it(cmd):
    assert not rules.verifying_segments(cmd, {"build"}), cmd
