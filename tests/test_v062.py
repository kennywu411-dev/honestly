"""0.6.2: `|&` and a `{ ...; }` group piped into head are refused like a plain pipe."""
from honestly import hooks


def _deny(cmd):
    return hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": cmd}}) is not None


def test_pipe_ampersand_and_brace_group_are_denied():
    for cmd in ["pytest |& head",
                "npm test |& head -40",
                "{ pytest; } | head",
                "{ cd app && pytest -q; } 2>&1 | head -5",
                "{ CI=1 go test ./...; } |& grep -c ok"]:
        assert _deny(cmd), cmd


def test_groups_without_a_check_or_with_pipefail_pass():
    for cmd in ["{ ls; cat a.txt; } | head",
                "{ echo a; echo b; } | sort",
                "set -o pipefail; { pytest; } | head",
                "{ pytest; } > out.txt",
                "pytest || true"]:
        assert not _deny(cmd), cmd


def test_plugin_entry_runs_from_checkout_and_steps_aside_for_guard(tmp_path):
    import json, os, subprocess, sys
    run = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "run.py")
    event = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "pytest |& head"}})
    env = dict(os.environ, HOME=str(tmp_path), USERPROFILE=str(tmp_path), CLAUDE_CONFIG_DIR=str(tmp_path / "cfg"))
    out = subprocess.run([sys.executable, run, "hook", "pre"], input=event, capture_output=True, text=True, env=env, encoding="utf-8")
    assert '"deny"' in out.stdout
    (tmp_path / "cfg").mkdir()
    exe = tmp_path / "bin" / "honestly"
    def settings(command):
        (tmp_path / "cfg" / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": command}]}]}}))
        return subprocess.run([sys.executable, run, "hook", "pre"], input=event, capture_output=True, text=True, env=env, encoding="utf-8")
    out = settings(f'"{exe}" hook pre  # honestly hook')
    assert '"deny"' in out.stdout   # the guard entry points at a binary that is gone (pip uninstall): the plugin keeps checking
    exe.parent.mkdir()
    exe.write_text("")
    out = settings(f'"{exe}" hook pre  # honestly hook')
    assert out.returncode == 0 and out.stdout.strip() == ""   # a working guard install: the plugin steps aside
    for broken in ({"hooks": ["x"]}, {"hooks": {"Stop": ["str"]}}, {"hooks": {"Stop": [{"hooks": ["s"]}]}}):
        (tmp_path / "cfg" / "settings.json").write_text(json.dumps(broken))
        out = subprocess.run([sys.executable, run, "hook", "pre"], input=event, capture_output=True, text=True, env=env, encoding="utf-8")
        assert out.returncode == 0 and '"deny"' in out.stdout   # odd settings never crash the hook


def test_plugin_manifests_are_consistent():
    import json, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    plugin = json.load(open(os.path.join(root, ".claude-plugin", "plugin.json"), encoding="utf-8"))
    market = json.load(open(os.path.join(root, ".claude-plugin", "marketplace.json"), encoding="utf-8"))
    from honestly import __version__
    assert plugin["version"] == __version__
    assert market["plugins"][0]["name"] == plugin["name"] == "honestly"
    hooks = json.load(open(os.path.join(root, "hooks", "hooks.json"), encoding="utf-8"))["hooks"]
    assert set(hooks) == {"Stop", "PreToolUse"}


def test_quoted_test_words_are_not_a_check_but_inline_code_is():
    from honestly import rules
    v = lambda c: bool(rules.verifying_segments(c, {"test", "run"}))
    assert not v('gh pr create --title "fix: pytest |& tail" --body "pytest passes"')
    assert not v("git tag -m 'run pytest' v1")
    assert v('uv run python -c "import evalkit.cli"')
    assert v('bash -c "pytest -q"')
    assert v('pytest -k "login and not slow"')


def test_pr_note_shows_command_without_subshell_env_prefix():
    from honestly import prnote
    assert prnote._show("HOME=$(mktemp -d) .venv/bin/python -m pytest -q") == ".venv/bin/python -m pytest -q"


def test_group_or_pipe_quoted_in_an_argument_is_not_a_run():
    notes = 'gh release create v1 --notes "- refuses \\`pytest |& tail\\` and \\`{ cd app && pytest; } | tail\\`.\n- see this release\'s PR (#4)" | tail -1'
    assert not _deny(notes)
    assert not _deny("git commit -m 'catch { pytest; } | tail' | head -1")
    assert _deny('{ pytest -q; } | head -3 && gh release create v1 --notes "done"')
