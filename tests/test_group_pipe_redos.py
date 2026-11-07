"""GROUP_PIPE must not backtrack exponentially on a run of redirections (CodeQL py/redos)."""
import time

from honestly import hooks


def test_long_redirect_run_is_fast():
    cmd = "{ pytest; }" + "9>" * 40 + "x"
    start = time.perf_counter()
    hooks.GROUP_PIPE.search(cmd)
    hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": cmd}})
    assert time.perf_counter() - start < 1.0


def test_group_redirections_still_recognized():
    for cmd in ["{ pytest; } 2>&1 | head",
                "{ pytest; } >&2 | head",
                "{ pytest; } 2>&1 >&2 | head",
                "{ pytest; } 2>&- | head",
                "{ CI=1 go test ./...; } |& grep -c ok"]:
        assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": cmd}}) is not None, cmd
    for cmd in ["{ pytest; } | tail -n 1", "{ ls; } 2>&1 | head", "set -o pipefail; { pytest; } 2>&1 | head"]:
        assert hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": cmd}}) is None, cmd
