"""Trim real recordings into the small fixtures under tests/fixtures/real/: make_fixtures.py <recordings dir>.
Only the records and fields the parsers read are kept, and every machine path is replaced, so nothing private goes into the repository."""
import glob, json, os, re, shutil, sys
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "fixtures", "real")
PICK = {
    "claude": {"01-noedit-check-claim": "01", "07a-retry-honest": "07a", "07b-retry-repeated": "07b", "08a-sub-runs-pass": "08a", "08b-sub-runs-fail": "08b", "08c-sub-edits-no-test": "08c", "08j-main-edit-sub-edit-sub-tests-pass": "08j",
               "08l-bg-sub-edits-after-main-test": "08l", "09d-bg-still-running": "09d", "09e-bg-pass-notified": "09e", "09f-bg-fail-notified": "09f", "09j-bg-exit-nonzero-no-summary-read": "09j",
               "12c-autocompact-after-test-fail": "12c", "12d-autocompact-after-test-pass": "12d", "02-failed-run-claim": "02"},
    "codex": {"01-noedit-check-claim": "01", "07a-retry-honest": "07a", "08a-sub-runs-pass": "08a", "08c-sub-edits-no-test": "08c", "09c-bg-claim-before-done": "09c", "09e-long-default-yield-fail": "09e", "09f-long-default-yield-pass": "09f", "15g-patch-body-has-cmd-key": "15g"},
    "gemini": {"07f-hold-loop-edits": "07f", "07g-retry-tool-then-honest": "07g", "08a-sub-runs-pass": "08a", "08c-sub-edits-no-test": "08c", "09b-bg-fail-read-later": "09b", "09a-bg-pass-read-later": "09a", "09c-bg-claim-before-done": "09c", "12e-compress-test-fail": "12e"},
}
USER_FIELDS = ("type", "isSidechain", "message", "origin", "promptSource", "turnOrigin", "isMeta", "isCompactSummary", "isVisibleInTranscriptOnly", "timestamp", "version", "cwd", "promptId")


def scrub(s):
    s = re.sub(r"/private/var/tmp/[\w./-]*?/proj", "/work/proj", s)
    s = re.sub(r"/private/tmp/claude-\d+/[^\s\"\\]*?/tasks/", "__TASKS__/", s)
    s = re.sub(r"/private/var/tmp/[\w./-]*?/(home|ccfg)[\w./-]*", "/work/home", s)
    s = re.sub(r"/private/tmp/claude-\d+/[^\s\"\\]*", "/tmp/scratch", s)
    s = re.sub(r"-private-var-tmp-[\w-]*", "-work-proj", s)
    return re.sub(r"/Users/[^/\s\"\\]+", "/Users/someone", s)


def claude(src, name):
    d = os.path.join(OUT, "claude", name)
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    mains = [f for f in glob.glob(os.path.join(src, "*.jsonl")) if not os.path.basename(f).startswith("agent-")]
    for f in mains[:1]:
        keep(f, os.path.join(d, "session.jsonl"))
    for f in glob.glob(os.path.join(src, "agent-*")):
        sub = os.path.join(d, "session", "subagents"); os.makedirs(sub, exist_ok=True)
        if f.endswith(".jsonl"):
            keep(f, os.path.join(sub, os.path.basename(f)))
        else:
            with open(f, encoding="utf-8") as a, open(os.path.join(sub, os.path.basename(f)), "w", encoding="utf-8") as b:
                b.write(scrub(a.read()))


def keep(src, dst):
    with open(src, encoding="utf-8") as a, open(dst, "w", encoding="utf-8") as b:
        for line in a:
            r = json.loads(line)
            if r.get("type") not in ("user", "assistant"):
                continue
            r = {k: r[k] for k in USER_FIELDS if k in r}
            m = r.get("message") or {}
            r["message"] = {k: m[k] for k in ("role", "model", "content") if k in m}
            b.write(scrub(json.dumps(r, ensure_ascii=False)) + "\n")


def codex(src, name):
    day = os.path.join(OUT, "codex", name, "sessions", "2026", "11", "09")
    shutil.rmtree(os.path.join(OUT, "codex", name), ignore_errors=True); os.makedirs(day)
    for f in glob.glob(os.path.join(src, "*.jsonl")):
        with open(f, encoding="utf-8") as a, open(os.path.join(day, os.path.basename(f)), "w", encoding="utf-8") as b:
            for line in a:
                r = json.loads(line)
                t, p = r.get("type"), r.get("payload") or {}
                if t == "session_meta":
                    p = {k: p.get(k) for k in ("id", "session_id", "cwd", "model", "source", "thread_source", "parent_thread_id")}
                elif t == "turn_context":
                    p = {k: p.get(k) for k in ("cwd", "model")}
                elif t == "event_msg":
                    item = p.get("item") if isinstance(p.get("item"), dict) else {}
                    if not (p.get("type") == "item_completed" and item.get("type") in ("UserMessage", "HookPrompt")):
                        continue
                elif t == "response_item":
                    if p.get("role") in ("developer",) or (p.get("role") == "user" and "environment_context" in json.dumps(p)) or p.get("type") in ("reasoning", "tool_search_output", "tool_search_call"):
                        continue
                    p = {k: v for k, v in p.items() if k != "internal_chat_message_metadata_passthrough"}
                else:
                    continue
                b.write(scrub(json.dumps({"timestamp": r.get("timestamp"), "type": t, "payload": p}, ensure_ascii=False)) + "\n")


def gemini(src, name):
    base = os.path.join(OUT, "gemini", name, "proj")
    shutil.rmtree(os.path.join(OUT, "gemini", name), ignore_errors=True); chats = os.path.join(base, "chats"); os.makedirs(chats)
    with open(os.path.join(base, ".project_root"), "w") as fh:
        fh.write("/work/proj")
    subs = [f for f in glob.glob(os.path.join(src, "*.jsonl")) if not os.path.basename(f).startswith("session-")]
    main = [f for f in glob.glob(os.path.join(src, "session-*.jsonl"))][0]
    sid = json.loads(open(main, encoding="utf-8").readline()).get("sessionId")
    for f, dst in [(main, os.path.join(chats, os.path.basename(main)))] + [(s, os.path.join(chats, sid, os.path.basename(s))) for s in subs]:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(f, encoding="utf-8") as a, open(dst, "w", encoding="utf-8") as b:
            for line in a:
                r = json.loads(line)
                if "$set" in r or "$patch" in r:
                    continue
                r.pop("thoughts", None); r.pop("tokens", None)
                c = r.get("content")
                if isinstance(c, list) and c and isinstance(c[0], dict) and str(c[0].get("text") or "").startswith("<session_context>"):
                    r["content"] = [{"text": "<session_context>\n(trimmed)\n</session_context>"}] + c[1:]
                if isinstance(c, str) and len(c) > 600:
                    r["content"] = c[:200] + " (trimmed)"
                if isinstance(c, list) and c and isinstance(c[0], dict) and len(str(c[0].get("text") or "")) > 600 and not str(c[0].get("text")).startswith("<session_context>"):
                    r["content"] = [{"text": str(c[0]["text"])[:200] + " (trimmed)"}]
                b.write(scrub(json.dumps(r, ensure_ascii=False)) + "\n")


if __name__ == "__main__":
    rec = sys.argv[1]
    for src, name in PICK["claude"].items():
        claude(os.path.join(rec, "claude-guard", src), name)
    for src, name in PICK["codex"].items():
        codex(os.path.join(rec, "codex", src), name)
    for src, name in PICK["gemini"].items():
        gemini(os.path.join(rec, "gemini", src), name)
    codex(os.path.join(rec, "codex-versions", "codex140"), "v140")
    keep(glob.glob(os.path.join(rec, "claude-sdk", "stream", "*.jsonl"))[0], os.path.join(OUT, "claude", "sdk.jsonl"))
