"""0.6.1: a leading VAR=value does not hide a piped test run from the pre hook (issue #1)."""
from honestly import hooks


def _deny(cmd):
    return hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": cmd}}) is not None


def test_env_prefixed_piped_test_is_denied():
    for cmd in ["CI=1 pytest | tail",
                "NODE_ENV=test npm test | tail -20",
                "cd app && CI=1 go test ./... | tail",
                "FOO=1 BAR=2 cargo test 2>&1 | head",
                'PYTHONPATH="src lib" pytest -q | tail -3',
                "RUST_LOG= cargo test | grep -v warn"]:
        assert _deny(cmd), cmd


def test_env_prefix_alone_or_on_a_non_check_still_passes():
    for cmd in ["CI=1", "FOO=bar ls | head", "CI=1 cat build.log | tail",
                "NODE_ENV=test npm install | tail", "set -o pipefail; CI=1 pytest | tail",
                "CI=1 pytest -q"]:
        assert not _deny(cmd), cmd
