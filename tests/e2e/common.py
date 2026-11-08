"""Shared pieces of the real-CLI runners: per-scenario folders, fake check commands, a clean environment, result scoring.

Where things live (see README.md): HONESTLY_E2E_HOME holds the installed CLIs, results and recordings; HONESTLY_E2E_BOX holds the throwaway HOME and
project of each scenario; HONESTLY_E2E_BIN is the honestly under test (default: the one next to this Python)."""
import json, os, shutil, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
S = os.environ.get("HONESTLY_E2E_HOME") or os.path.expanduser("~/.cache/honestly-e2e")
REPO = os.path.dirname(os.path.dirname(HERE))
HONESTLY = os.environ.get("HONESTLY_E2E_BIN") or os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "honestly")
WRAP = os.path.join(HERE, "hookwrap.py")
# A temp folder, but not /tmp, /private/tmp, /var/folders or a "scratchpad" folder: a project there is judged differently, and only 15d means to test that.
BOX = os.environ.get("HONESTLY_E2E_BOX") or "/private/var/tmp/honestly-e2e"

# Every real CLI runs under this: no network except loopback (nothing can reach a real API), no route to the keychain daemons.
SEATBELT = """(version 1)(allow default)
(deny network-outbound)(allow network-outbound (remote ip "localhost:*"))(allow network-outbound (remote unix-socket))
(deny mach-lookup (global-name "com.apple.SecurityServer") (global-name "com.apple.securityd.xpc") (global-name "com.apple.security.agent") (global-name "com.apple.security.agent.login"))"""
LOCKED = ["/usr/bin/sandbox-exec", "-p", SEATBELT]

FAKE_PASS = ("5 passed in 0.1s", 0)
FAKE_FAIL = ("1 failed, 4 passed in 0.1s", 1)
BIG_FAIL = '#!/bin/sh\ni=0; while [ $i -lt 8000 ]; do echo "test_case_$i PASSED padding padding padding padding"; i=$((i+1)); done\necho "1 failed, 7999 passed in 9.1s"\nexit 1\n'
BIG_PASS = '#!/bin/sh\ni=0; while [ $i -lt 8000 ]; do echo "test_case_$i PASSED padding padding padding padding"; i=$((i+1)); done\necho "8000 passed in 9.1s"\nexit 0\n'


def write_pytest(box, fake=FAKE_PASS, script=None):
    path = os.path.join(box["bin"], "pytest")
    with open(path, "w") as fh:
        fh.write(script or f'#!/bin/sh\necho ran >> "{box["home"]}/pytest-ran"\necho "{fake[0]}"\nexit {fake[1]}\n')
    os.chmod(path, 0o755)


def sandbox(cli, name, fake=FAKE_PASS, script=None):
    root = os.path.join(BOX, cli, name)
    shutil.rmtree(root, ignore_errors=True)
    home, proj, bin_ = os.path.join(root, "home"), os.path.join(root, "proj"), os.path.join(root, "home", "bin")
    os.makedirs(proj); os.makedirs(bin_)
    box = dict(root=root, home=home, proj=proj, bin=bin_, hooklog=os.path.join(root, "hooklog"))
    write_pytest(box, fake, script)
    # Nothing here may reach the macOS keychain. A CLI that shells out to `security` gets this logger, which reports "not found" / "failed".
    sec = os.path.join(bin_, "security")
    with open(sec, "w") as fh:
        fh.write(f'#!/bin/sh\necho "$(date +%H:%M:%S) $*" >> "{root}/keychain-calls.log"\n[ "$1" = "-i" ] && cat >> "{root}/keychain-calls.log"\nexit 44\n')
    os.chmod(sec, 0o755)
    with open(os.path.join(proj, "app.py"), "w") as fh:
        fh.write("x = 0\n")
    subprocess.run(["git", "init", "-q"], cwd=proj)
    return box


def clean_env(box, **extra):
    """Nothing is inherited from the session this runs in: its keys, tokens and CLAUDE_* settings must not reach a CLI under test."""
    env = {"HOME": box["home"], "PATH": os.pathsep.join([box["bin"], "/opt/homebrew/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]),
           "LANG": "en_US.UTF-8", "TERM": "dumb", "SHELL": "/bin/bash", "TMPDIR": os.path.join(box["root"], "tmp"), "USER": os.environ.get("USER", "x"),
           "HONESTLY_NO_UPDATE_CHECK": "1", "HX_KEYCHAIN_LOG": os.path.join(box["root"], "keychain-calls.log")}
    os.makedirs(env["TMPDIR"], exist_ok=True)
    env.update(extra)
    return env


def keychain_calls(box):
    p = os.path.join(box["root"], "keychain-calls.log")
    return open(p, encoding="utf-8", errors="replace").read().splitlines() if os.path.exists(p) else []


def security_agent_up():
    """SecurityAgent is the process that draws macOS keychain dialogs. Read-only check."""
    return subprocess.run(["pgrep", "-x", "SecurityAgent"], capture_output=True).returncode == 0


def watch_keychain():
    """Stop the whole run if a keychain dialog appears while CLIs are running."""
    import signal, threading
    if security_agent_up():
        print("SecurityAgent is already up; not starting real CLIs."); sys.exit(3)
    def loop():
        while True:
            time.sleep(1)
            if security_agent_up():
                with open(os.path.join(S, "results", "KEYCHAIN-POPUP.txt"), "a") as fh:
                    fh.write(time.strftime("%F %T") + " SecurityAgent appeared during " + " ".join(sys.argv) + "\n")
                print("KEYCHAIN DIALOG: stopping this run", flush=True)
                os.killpg(os.getpgrp(), signal.SIGTERM)
    threading.Thread(target=loop, daemon=True).start()


def hooks_log(box):
    p = os.path.join(box["hooklog"], "hooks.jsonl")
    return [json.loads(l) for l in open(p, encoding="utf-8")] if os.path.exists(p) else []


def catches(box):
    p = os.path.join(box["home"], ".honestly/catches.jsonl")
    return [json.loads(l) for l in open(p, encoding="utf-8")] if os.path.exists(p) else []


def hook_errors(box):
    p = os.path.join(box["home"], ".honestly/hook-errors.log")
    return open(p, encoding="utf-8").read() if os.path.exists(p) else ""


def wrap_hooks(path, box, events, slow=None):
    """Route the installed hook lines through hookwrap.py; `slow` = (event, timeout value in the CLI's unit, seconds to sleep) really reaches the timeout."""
    d = json.load(open(path))
    for ev, label in events:
        h = d["hooks"][ev][-1]["hooks"][0]
        base = h["command"].split("  #")[0]
        cmd = f"{WRAP} {box['hooklog']} {label} {base}  # honestly hook"
        if slow and slow[0] == ev:
            cmd = f"sleep {slow[2]}; " + cmd
            h["timeout"] = slow[1]
        h["command"] = cmd
    json.dump(d, open(path, "w"), indent=2)


def parse_stdin(h):
    try:
        return json.loads(h["stdin"])
    except Exception:
        return {}


def summarize(name, form, sc, box, st, outs, trans):
    hk = hooks_log(box)
    return dict(name=name, form=form, expect=sc["expect"], runs=outs,
                requests=[dict(kind=x["kind"], n=x.get("n"), last=x.get("since_assistant", "")[-1500:],
                               reply=[{k: (v if k != "input" else str(v)[:120]) for k, v in b.items()} for b in x.get("reply", [])]) for x in st.log if x["kind"] not in ("get", "aux")],
                hooks=[dict(label=h["label"], ms=h["ms"], rc=h["rc"], stdout=h["stdout"][:900], stderr=h["stderr"][:300], stop_hook_active=parse_stdin(h).get("stop_hook_active"),
                            fields=sorted(parse_stdin(h).keys()), tool=parse_stdin(h).get("tool_name"), tool_input=str(parse_stdin(h).get("tool_input"))[:300],
                            lam=str(parse_stdin(h).get("last_assistant_message") or parse_stdin(h).get("prompt_response") or "")[:300]) for h in hk],
                catches=[dict(kind=c.get("kind"), claim=c.get("claim"), reason=c.get("reason"), message=c.get("message"), command=c.get("command")) for c in catches(box)],
                auth_seen=dict(st.auth_seen), keychain_calls=keychain_calls(box)[:40], hook_errors=hook_errors(box)[-1500:], pytest_ran=os.path.exists(os.path.join(box["home"], "pytest-ran")),
                script_left=len(st.main), sub_left=len(st.sub), transcripts=[(os.path.basename(f), os.path.getsize(f)) for f in trans], box=box["root"])


def score(s):
    """(holds, warns, denies, reached the model, PASS/FAIL against `expect`). A hold counts from catches, so the plain plugin form scores too."""
    stop_c = [c for c in s["catches"] if c["kind"] == "stop"]
    pre_c = [c for c in s["catches"] if c["kind"] == "pre"]
    holds = len(stop_c); denies = len(pre_c)
    phrase = ("not held a second time", "没有再拦")
    warns = sum(1 for h in s["hooks"] if h["label"] == "stop" and any(x in h["stdout"] for x in phrase))
    if not s["hooks"]:   # the plugin form runs unwrapped: read what the CLI showed
        warns = sum(1 for r in s["runs"] for x in r.get("shown_to_user") or [] if any(y in str(x) for y in phrase))
    reached = any("⚠️ honestly" in r["last"] or "\\u26a0\\ufe0f honestly" in r["last"] for r in s["requests"])
    e = s["expect"]
    if e == "hold": ok = holds == 1 and warns == 0 and reached
    elif e == "hold+warn": ok = holds == 1 and warns == 1
    elif e == "at-most-1-hold": ok = holds <= 1
    elif e == "nohold": ok = holds == 0 and denies == 0
    elif e == "refuse": ok = denies >= 1 and not s["pytest_ran"]
    elif e == "allow": ok = denies == 0 and holds == 0
    else: ok = None   # info: recorded, not scored
    return holds, warns, denies, reached, ("info" if ok is None else "PASS" if ok else "FAIL")


def line(s):
    holds, warns, denies, reached, verdict = score(s)
    if s.get("auth_seen", {}).get("OTHER"):
        verdict = "AUTH"   # a credential other than the dummy reached the stand-in; the value is not kept anywhere
    return f'{verdict:4} {s["name"]:38} exp={s["expect"]:14} holds={holds} warns={warns} denies={denies} reached_model={reached!s:5} pytest={s["pytest_ran"]!s:5} left={s["script_left"]}/{s["sub_left"]} result={str(s["runs"][-1]["result"])[:56]!r} rc={[r["rc"] for r in s["runs"]]} errlog={bool(s["hook_errors"])}'


def save(s, group):
    d = os.path.join(S, "results", group)
    os.makedirs(d, exist_ok=True)
    json.dump(s, open(os.path.join(d, s["name"] + ".json"), "w"), ensure_ascii=False, indent=1)
    return s


def copy_recordings(group, name, files):
    dest = os.path.join(S, "recordings", group, name)
    shutil.rmtree(dest, ignore_errors=True); os.makedirs(dest)
    for f in files:
        if os.path.isfile(f) and os.path.getsize(f) < 3_000_000:
            shutil.copy(f, dest)
