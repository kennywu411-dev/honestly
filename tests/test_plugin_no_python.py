"""The plugin's hook line when Python cannot run it: the user is told at the end of a reply, and a shell command is not slowed or nagged."""
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _command(event):
    with open(os.path.join(ROOT, "hooks", "hooks.json"), encoding="utf-8") as fh:
        return json.load(fh)["hooks"][event][0]["hooks"][0]["command"].replace("${CLAUDE_PLUGIN_ROOT}", ROOT)


@pytest.mark.skipif(os.name == "nt" or not shutil.which("sh"), reason="runs the hook line through a POSIX shell, as Claude Code does")
def test_no_python_tells_the_user_at_stop(tmp_path):
    out = subprocess.run(["/bin/sh", "-c", _command("Stop")], input="{}", capture_output=True, text=True, env={"PATH": str(tmp_path)})
    assert out.returncode == 0
    message = json.loads(out.stdout)["systemMessage"]
    assert "not checking" in message and "Python" in message


@pytest.mark.skipif(os.name == "nt" or not shutil.which("sh"), reason="runs the hook line through a POSIX shell, as Claude Code does")
def test_no_python_stays_quiet_before_a_command(tmp_path):
    out = subprocess.run(["/bin/sh", "-c", _command("PreToolUse")], input="{}", capture_output=True, text=True, env={"PATH": str(tmp_path)})
    assert out.returncode == 0 and out.stdout == ""


@pytest.mark.skipif(os.name == "nt" or not shutil.which("sh"), reason="runs the hook line through a POSIX shell, as Claude Code does")
def test_with_python_the_hook_runs_as_before(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path), PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", ""))
    env.pop("CLAUDE_CONFIG_DIR", None)
    out = subprocess.run(["/bin/sh", "-c", _command("Stop")], input=json.dumps({"last_assistant_message": "hello", "stop_hook_active": False}), capture_output=True, text=True, env=env)
    assert out.returncode == 0 and "not checking" not in out.stdout
