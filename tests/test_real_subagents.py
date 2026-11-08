"""Subagent work, read on every assistant, in the shapes the real CLIs wrote."""
import os

import pytest

from real_fixture import load
from test_real_turns import held, stop


@pytest.mark.parametrize("name,claim", [("08b", "All tests pass"), ("08c", "All tests pass"), ("08l", "All tests pass")])
def test_claude_subagent_work_is_read(tmp_path, name, claim):
    p = load(tmp_path, "claude", name, claim)
    assert held(stop(p, claim + "."))


@pytest.mark.parametrize("name", ["08a", "08j"])
def test_claude_a_subagents_passing_run_backs_the_claim(tmp_path, name):
    p = load(tmp_path, "claude", name, "All 5 tests pass")
    assert stop(p, "All 5 tests pass.") is None


def test_codex_a_subagents_passing_run_backs_the_claim(tmp_path):
    p = load(tmp_path, "codex", "08a", "All 5 tests pass")
    assert stop(p, "All 5 tests pass.", "codex") is None


def test_codex_a_subagents_edit_counts(tmp_path):
    p = load(tmp_path, "codex", "08c", "All tests pass")
    assert held(stop(p, "All tests pass.", "codex"))


def test_gemini_a_subagents_passing_run_backs_the_claim(tmp_path):
    p = load(tmp_path, "gemini", "08a", "All 5 tests pass")
    assert stop(p, "All 5 tests pass.", "gemini") is None


def test_gemini_a_subagents_edit_counts(tmp_path):
    p = load(tmp_path, "gemini", "08c", "All tests pass")
    assert held(stop(p, "All tests pass.", "gemini"))


def test_codex_a_subagent_whose_record_is_gone_stays_could_not_check(tmp_path):
    p = load(tmp_path, "codex", "08a", "All 5 tests pass")
    for f in os.listdir(os.path.dirname(p)):
        if os.path.join(os.path.dirname(p), f) != p:
            os.remove(os.path.join(os.path.dirname(p), f))
    assert stop(p, "All 5 tests pass.", "codex") is None
