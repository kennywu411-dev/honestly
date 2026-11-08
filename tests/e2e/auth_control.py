"""If `security` had returned a Claude Code login during a run, would it have been sent instead of the dummy key?
A fake credential is served by the logger on PATH; the run has no network except the stand-in. Prints only the class of what arrived."""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
from standin import Standin
CL = os.path.join(S, "clis/claude/node_modules/.bin/claude")
FAKE = json.dumps({"claudeAiOauth": {"accessToken": "hx-fake-access-token", "refreshToken": "hx-fake-refresh-token", "expiresAt": 9999999999999, "scopes": ["user:inference", "user:profile"], "subscriptionType": "max"}})
for label, with_key in (("dummy API key set", True), ("no API key at all", False)):
    st = Standin(); box = sandbox("keychain", "auth-control-" + ("key" if with_key else "nokey"))
    with open(os.path.join(box["bin"], "security"), "w") as fh:
        fh.write(f"#!/bin/sh\necho \"$(date +%H:%M:%S) $*\" >> \"{box['root']}/keychain-calls.log\"\ncase \"$*\" in *find-generic-password*) echo '{FAKE}'; exit 0;; esac\nexit 44\n")
    cfg = os.path.join(box["root"], "ccfg"); os.makedirs(cfg)
    extra = {"ANTHROPIC_API_KEY": "standin-dummy"} if with_key else {}
    env = clean_env(box, ANTHROPIC_BASE_URL=st.url, CLAUDE_CONFIG_DIR=cfg, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", DISABLE_AUTOUPDATER="1", DISABLE_TELEMETRY="1", DISABLE_ERROR_REPORTING="1", **extra)
    st.reset(main=[[{"text": "hello"}]])
    r = subprocess.run(LOCKED + [CL, "-p", "hi", "--model", "claude-sonnet-5", "--dangerously-skip-permissions"], env=env, cwd=box["proj"], capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    print(label, "-> rc", r.returncode, "auth classes at the stand-in:", dict(st.auth_seen), "| security calls:", len(keychain_calls(box)), "| writes:", sum("add-generic" in x or "delete-generic" in x for x in keychain_calls(box)), "| result:", r.stdout.strip()[:60])
