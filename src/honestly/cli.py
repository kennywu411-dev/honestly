"""The command line. Importing this module stays cheap, because a hook starts it before every shell command: what a command needs is imported inside it."""
from __future__ import annotations
import os
import sys


def _since_cutoff(spec):
    if not spec:
        return None
    import datetime as dt, re
    m = re.fullmatch(r"(\d+)([dwm])", spec.strip())
    if not m:
        raise SystemExit("--since takes a number followed by d, w or m, e.g. 30d")
    days = int(m.group(1)) * {"d": 1, "w": 7, "m": 30}[m.group(2)]
    try:
        return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    except OverflowError:
        return None   # further back than any log: everything


ALL_AGENTS = ("claude-code", "codex", "cursor", "gemini")


def _audited(path, parse, cfg_sig, use_cache, extra=""):
    from . import cache
    from .audit import audit_turns
    if use_cache:
        hit = cache.get(path, cfg_sig + extra)
        if hit is not None:
            return hit
    from .claude_code import TASK_FILES_READ
    TASK_FILES_READ.clear()
    try:
        out = audit_turns(parse(path))
    except Exception as e:   # one log that cannot be read costs that log, not the whole audit
        SKIPPED.append((path, e))
        return []
    if use_cache:
        cache.put(path, cfg_sig + extra, out, deps=sorted(TASK_FILES_READ))
    return out


SKIPPED: list = []


def _report_skipped() -> None:
    if SKIPPED:
        path, e = SKIPPED[0]
        print(f"honestly: skipped {len(SKIPPED)} session log(s) that could not be read, first {path}: {e.__class__.__name__}: {e}", file=sys.stderr)
        SKIPPED.clear()


def _session_dir(path: str, agent: str) -> str:
    """Where a session ran, without parsing it: its own project's settings judge it, wherever `audit` is run from."""
    import json, re
    if agent == "cursor":
        return ""   # the transcript does not say
    if agent == "gemini":
        from . import agents as _ag
        return _ag._gemini_project(path)
    try:
        with open(path, "rb") as fh:
            m = re.search(rb'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"', fh.read(1 << 16))
        return json.loads(b'"' + m.group(1) + b'"') if m else ""
    except (OSError, ValueError):
        return ""


def _file_time(path: str) -> str:
    import datetime as dt
    try:
        return dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    except (OSError, ValueError, OverflowError):
        return ""


def collect(root_claude=None, root_codex=None, agents=ALL_AGENTS, since=None, project=None, use_cache=True, cursor_root=None, gemini_root=None):
    import json
    from . import agents as _ag, claude_code, codex, config
    from .audit import finding_key
    cutoff = _since_cutoff(since)
    timed, sessions, cfg_of = [], 0, {}

    def read(path, parse, agent, extra=""):
        nonlocal sessions
        sessions += 1
        where = _session_dir(path, agent)
        if where not in cfg_of:   # the user's settings plus that project's, the same ones its hooks used
            cfg_of[where] = config.load(where) if where else config.load_user()
        cfg = cfg_of[where]
        config.apply(cfg)
        cfg_sig = json.dumps(cfg, sort_keys=True, ensure_ascii=False)
        stamp = _file_time(path)   # a transcript with no clock (Cursor) is placed by its file
        timed.extend((f, f.ts or stamp) for f in _audited(path, parse, cfg_sig, use_cache, extra))

    if "claude-code" in agents:
        for path in claude_code.iter_sessions(root_claude):
            subs = claude_code.subagent_files(path)
            read(path, claude_code.parse_session, "claude-code", "|".join(f"{os.path.getsize(s)}:{os.path.getmtime(s)}" for s in subs))
    if "codex" in agents:
        for path in codex.iter_sessions(root_codex):
            read(path, codex.parse_session, "codex")
    if "cursor" in agents:
        for path in _ag.cursor_sessions(cursor_root):
            read(path, _ag.cursor_parse, "cursor")
    if "gemini" in agents:
        for path in _ag.gemini_sessions(gemini_root):
            read(path, _ag.gemini_parse, "gemini")
    findings = [f for f, when in timed if not cutoff or when >= cutoff]
    if project:
        findings = [f for f in findings if project.lower() in (f.project or "").lower()]
    _report_skipped()
    seen, deduped = set(), []
    for f in findings:
        key = finding_key(f)
        if key in seen:
            continue
        seen.add(key); deduped.append(f)
    return deduped, sessions, len(findings) - len(deduped)


def cmd_audit(a):
    import json
    from dataclasses import asdict
    from .redact import strip_controls
    from .report import text_report, colorize, want_color
    if a.clear_cache:
        from . import cache
        print(f"honestly: cleared {cache.clear()} cache entries ({cache.cache_dir()})")
        return 0
    agents = tuple(a.agent) if a.agent else ALL_AGENTS
    findings, sessions, dups = collect(a.root, a.codex_root, agents, a.since, project=a.project, use_cache=not a.no_cache, cursor_root=a.cursor_root, gemini_root=a.gemini_root)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            for f in findings:
                d = asdict(f); d["label"] = f.label
                fh.write(json.dumps(d, ensure_ascii=False) + "\n")
        print(f"wrote {len(findings)} findings to {a.json}", file=sys.stderr)
    filtered = " ".join(x for x in (f"--project {a.project}" if a.project else "", f"--since {a.since}" if a.since else "") if x)
    if a.summary_json:
        from .audit import summarize
        from .report import stats
        s, st = summarize(findings), stats(findings)
        s.update(schema=1, sessions=len({f.session for f in findings}) if filtered else sessions, sessions_read=sessions, duplicates_removed_forks=dups,
                 claims_in_scope=sum(st["counts"].values()), decided=st["decided"], rate=None if st["rate"] is None else round(st["rate"], 4))
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return
    looked = [x for x in (a.root, a.codex_root, a.cursor_root, a.gemini_root) if x]
    report = strip_controls(text_report(findings, sessions, dups, filtered, looked))   # it quotes replies: nothing in them may drive the terminal
    print(colorize(report) if want_color() else report)


def cmd_share(a):
    from .report import write_card
    findings, sessions, _ = collect(a.root, a.codex_root, since=a.since, project=a.project, use_cache=not a.no_cache, cursor_root=a.cursor_root, gemini_root=a.gemini_root)
    if not findings:
        print("Nothing to put on a card yet: no checkable claims in your session logs.", file=sys.stderr)
        return 0
    from . import store
    out = a.out or store.folder()
    written = write_card(findings, sessions, out)
    for p in written:
        print(p)
    if not any(p.endswith(".png") for p in written):
        print("PNG not written: no rsvg-convert, Chrome or Edge found. The .svg above opens in any browser; "
              "screenshot it there, or install one of those and run honestly share again.", file=sys.stderr)


def cmd_explain(a):
    from .redact import strip_controls
    findings, _, _ = collect(a.root, a.codex_root, since=a.since, project=a.project, use_cache=not a.no_cache, cursor_root=a.cursor_root, gemini_root=a.gemini_root)
    flagged = [f for f in findings if f.verdict in ("unbacked", "contradicted")]
    if not flagged:
        print("nothing flagged"); return
    if a.n < 1 or a.n > len(flagged):
        print(f"honestly explain: there are {len(flagged)} flagged claims; pick 1 to {len(flagged)}.", file=sys.stderr)
        return 1
    f = flagged[a.n - 1]
    show = lambda text: print(strip_controls(text))
    show(f"[{a.n}/{len(flagged)}] {f.label}  ·  {f.category}  ·  {f.agent} {f.model or f.version}  ·  session {f.session[:8]} turn {f.turn}  ·  {f.ts[:19]}")
    show(f"project: {f.project or '-'}")
    show(f"claim:   {f.claim}")
    show(f"context: …{f.context}…")
    show(f"last code edit: {f.last_edit or '-'}")
    show("tools after it (the last 8 at most):" if f.tools_after_edit else "tools after it: (none)")
    for t in f.tools_after_edit:
        show(f"  - {t}")
    if f.output:
        show(f"output:  {f.output}")
    show(f"why: {f.reason}")


def cmd_catches(a):
    from .hooks import catches_report, _lang_zh
    from .redact import strip_controls
    from .update import update_note
    from . import __version__, config
    from .hooks import catches_path, catches_unreadable
    why = catches_unreadable()
    if why:
        print(f"honestly: cannot read {catches_path()}: {why}", file=sys.stderr)
        return 1
    zh = _lang_zh(config.load(), "") if a.lang == "auto" else a.lang == "zh"
    print(strip_controls(catches_report(a.days, zh=zh)))
    if a.card:
        from .hooks import load_catches
        from .report import write_catches_card
        from . import store
        out = a.out or store.folder()
        rows = load_catches(a.days)
        if not rows:
            print("No card written: nothing was caught in this window.", file=sys.stderr)
        for p in write_catches_card(rows, a.days, out) if rows else []:
            print("wrote", p)
    note = update_note(__version__, zh=zh)   # once a day, CLI only, never from the hooks
    if note:
        print("\n" + note)


def cmd_guard(a):
    from .hooks import guard, set_notify, notify_flag_path
    if a.action == "notify":
        if a.value is None:
            print(f"honestly guard: desktop notifications {'on' if os.path.exists(notify_flag_path()) else 'off'}"); return
        if a.dry_run:
            print(f"honestly guard would turn desktop notifications {a.value}"); return
        print(set_notify(a.value == "on")); return
    if a.value is not None:
        return _usage_error(f"honestly guard {a.action}: {a.value!r} only goes with `guard notify`")
    agent = a.agent or ("all" if a.action == "status" else "claude-code")
    print(guard(a.action, dry_run=a.dry_run, agent=agent))


def cmd_ignore(a):
    from . import config
    if a.list or not a.phrase:
        print(config.show(None)); return
    fn = config.remove_from if a.remove else config.add_to
    print(fn("ignore", a.phrase, project=a.project))
    _project_hint(a)


def cmd_config(a):
    from . import config
    if not a.key:
        print(config.show(None)); return
    k, v = a.key, (a.value or "")
    if k == "strictness" and v not in config.STRICTNESS:
        return _usage_error(f"honestly config strictness: pick one of {', '.join(config.STRICTNESS)}")
    if k == "language" and v not in ("auto", "zh", "en"):
        return _usage_error("honestly config language: pick auto, zh or en")
    if k in ("strictness", "language"):
        print(config.set_value(k, v, project=a.project)); _project_hint(a); return
    if k in ("off", "on"):
        cats = [c.strip() for c in v.split(",") if c.strip()]
        if not cats:
            sys.exit(_usage_error(f"honestly config {k}: name a category, e.g. honestly config {k} fixed  (categories: {', '.join(config.CATEGORIES)})"))
        unknown = [c for c in cats if c not in config.CATEGORIES] if k == "off" else []
        if unknown:
            return _usage_error(f"honestly config off: no category called {', '.join(unknown)}  (categories: {', '.join(config.CATEGORIES)})")
        for cat in cats:
            print((config.add_to if k == "off" else config.remove_from)("off", cat, project=a.project))
        _project_hint(a)
        return
    if k in ("verify", "unverify"):
        if not v.strip():
            sys.exit(_usage_error(f'honestly config {k}: give the command, e.g. honestly config {k} "make smoke"'))
        print((config.add_to if k == "verify" else config.remove_from)("verify_commands", v, project=a.project)); _project_hint(a); return
    raise SystemExit("usage: honestly config [strictness strict|normal|lenient | language auto|zh|en | off CAT[,CAT] | on CAT | verify \"CMD\" | unverify \"CMD\"] [--project]")


def _project_hint(a):
    from . import config
    if a.project and config.ignored_settings(os.getcwd()):
        print("this file relaxes the rules, so it takes effect after you run `honestly trust` in your own terminal")


def cmd_trust(a):
    from . import config
    from .redact import strip_controls
    if a.list:
        rows = config.trusted_files()
        for path, same in rows:
            print(f"{'trusted' if same else 'changed since you trusted it, so ignored'}: {strip_controls(path)}")
        if not rows:
            print("no project file is trusted")
        return
    if a.remove:
        print(strip_controls(config.untrust(os.getcwd())))
        return
    if not (hasattr(sys.stdin, "isatty") and sys.stdin.isatty()):
        raise SystemExit("honestly trust needs your own terminal: an agent or a script must not be able to turn off its own guard.")
    relaxes = config.project_relaxes(os.getcwd())
    path = config.project_path(os.getcwd())
    if not relaxes:
        print(strip_controls(f"{path} relaxes nothing, so there is nothing to trust."))
        return
    settings = config._clean(config._read(path))
    print(strip_controls(f"{path} would relax the rules for this project:"))
    for key in relaxes:
        name = key.split(":")[0]
        print(strip_controls(f"  {name}: {settings.get(name)}")[:300])
    if input("Trust this exact file? Type yes: ").strip().lower() != "yes":
        print("not trusted")
        return
    print(strip_controls(config.trust(os.getcwd())))


def cmd_purge(a):
    from . import store
    from .redact import strip_controls
    planned = store.purge(everything=a.all, dry_run=True)
    for path in planned:
        print(strip_controls(path))
    if not planned:
        print("nothing to remove")
        return
    if a.dry_run:
        return
    if not (hasattr(sys.stdin, "isatty") and sys.stdin.isatty()):
        raise SystemExit("honestly purge needs your own terminal: the record of what the guard caught is not an agent's to erase.")
    what = "everything above, settings and trust included" if a.all else "the files above; your settings stay"
    if input(f"Delete {what}? Type yes: ").strip().lower() != "yes":
        print("nothing removed")
        return
    store.purge(everything=a.all)
    print(f"removed {len(planned)} item{'s' if len(planned) != 1 else ''}")


def cmd_feedback(a):
    from .hooks import load_catches
    from .redact import strip_controls
    from .support import feedback
    from .hooks import catches_path, catches_unreadable
    why = catches_unreadable()
    if why:
        print(f"honestly: cannot read {catches_path()}: {why}", file=sys.stderr)
        return 1
    total = len(load_catches())
    if total and not 1 <= a.n <= total:
        print(strip_controls(feedback(a.n)), file=sys.stderr)
        return 1
    print(strip_controls(feedback(a.n, issue_url=a.issue)))


def cmd_rule(a):
    from .support import rule, RULE_FILES
    if a.action == "status" and not a.agent:
        for agent in RULE_FILES:
            print(rule("status", agent, a.dir, zh=a.lang == "zh"))
        return
    print(rule(a.action, a.agent or "claude-code", a.dir, zh=a.lang == "zh"))


def cmd_pr_note(a):
    from . import prnote
    agents = tuple(a.agent) if a.agent else None
    ev, block = prnote.run(os.getcwd(), base=a.base, since=a.since, agents=agents, claude_root=a.root, codex_root=a.codex_root)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(block)
        print(f"wrote {a.out}", file=sys.stderr)
    if a.gh:
        print(prnote.update_pr(prnote.repo_root(os.getcwd()), block, a.pr))
    elif not a.out:
        print(block, end="")
    if a.check and ev.status not in ("pass", "no-edit"):
        sys.exit(1)


def cmd_doctor(a):
    from .redact import strip_controls
    from .support import doctor
    text, problems = doctor(zh=None if a.lang == "auto" else a.lang == "zh", with_problems=True)
    print(strip_controls(text))
    if problems:
        sys.exit(1)


def cmd_sample(a):
    import json, random
    try:
        with open(a.findings, encoding="utf-8") as fh:
            rows = [json.loads(l) for l in fh]
        rows = [r for r in rows if r["verdict"] == a.verdict and not r["session"].startswith(tuple(a.exclude))]
    except (ValueError, KeyError, TypeError):
        print(f"honestly sample: {a.findings} is not a findings file (make one with honestly audit --json)", file=sys.stderr)
        return 1
    random.Random(a.seed).shuffle(rows)
    per, picked = {}, []
    for r in rows:
        if per.get(r["session"], 0) >= a.per_session:
            continue
        per[r["session"]] = per.get(r["session"], 0) + 1
        picked.append(r)
        if len(picked) >= a.n:
            break
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(f"# Label sheet: {len(picked)} claims judged `{a.verdict}` by the audit\n\n")
        fh.write("For each item answer: **TP** (the audit is right), **FP** (the audit is wrong), or **UNSURE**.\n\n")
        for i, r in enumerate(picked, 1):
            fh.write(f"## {i}. [{r['category']}] session {r['session'][:8]} turn {r['turn']} ({r.get('agent','')} {r['version']})\n")
            fh.write(f"- claim: {r['claim']}\n- context: …{r['context']}…\n- last edit: {r['last_edit'] or '(none)'}\n")
            fh.write("- tools after last edit: " + ("; ".join(r['tools_after_edit']) if r['tools_after_edit'] else "(none)") + "\n")
            if r.get("verified_by"):
                fh.write(f"- verifying command segment: {r['verified_by']}\n- its output (first 300 chars): {r.get('output','')}\n")
            fh.write(f"- audit reason: {r['reason']}\n- label: \n\n")
    with open(a.out.replace('.md', '.jsonl'), "w", encoding="utf-8") as fh:
        for r in picked:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(picked)} items to {a.out}")


def _common(p):
    p.add_argument("--project", default=None, help="only sessions whose project path contains this text")
    p.add_argument("--no-cache", action="store_true", help="re-parse every session instead of using ~/.honestly/cache")
    p.add_argument("--cursor-root", default=None, help="Cursor projects dir (default ~/.cursor/projects)")
    p.add_argument("--gemini-root", default=None, help="Gemini CLI tmp dir (default ~/.gemini/tmp)")


OVERVIEW = """honestly {v}: did your coding agent actually do what it said?

  honestly guard install     stop unverified "done" claims in Claude Code (--agent codex | cursor | gemini)
  honestly doctor            check the install and run two live self-tests
  honestly catches           what guard stopped this week   (--card for a shareable image)
  honestly audit             score your past sessions        (--since 30d, --project name)
  honestly explain N         the story behind a flagged claim
  honestly share             the score as a card
  honestly ignore "phrase"   silence a false catch           (honestly config: strictness, language, custom checks)
  honestly trust             let this project's .honestly.json relax the rules (needs your own terminal)
  honestly feedback          turn a wrong catch into an issue-ready text
  honestly pr-note --gh      put the branch's test evidence into its pull request
  honestly purge             delete what honestly recorded (catches, logs, cache)

guard: {status}\nhonestly --help for everything.
"""


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise ValueError(text)
    return value


def _usage_error(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


EXIT_CODES = """exit codes:
  0    done (a hook always exits 0, also when it holds a reply: the hold is in its JSON)
  1    it could not do what was asked, or it found a problem: doctor found one, pr-note --check saw no passing test, a file could not be read or written
  2    the command line is wrong
  130  interrupted (Ctrl-C)
  141  whatever was reading the output closed it (`honestly audit | head`)
"""
HOOK_AGENTS = ("claude-code", "codex", "cursor", "gemini")


def _set_up_streams(utf8: bool = False) -> None:
    """Output never fails on a character the terminal lacks. Hooks always speak UTF-8; for people, the terminal's encoding is kept (and a
    PYTHONIOENCODING they set), except that a Windows redirect, which defaults to the locale code page, becomes UTF-8."""
    if not utf8 and sys.platform == "win32" and not os.environ.get("PYTHONIOENCODING"):
        utf8 = not (hasattr(sys.stdout, "isatty") and sys.stdout.isatty())
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(**({"encoding": "utf-8", "errors": "replace"} if utf8 else {"errors": "replace"}))
            except Exception:
                pass


def _silence_stdout() -> None:
    """After a failed write, point stdout at nothing, so the interpreter's flush on the way out has nothing to complain about."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
    except Exception:
        pass


def _flush_stdout() -> None:
    if sys.stdout is not None:
        sys.stdout.flush()


def _hook_args(args: list):
    """(which, agent) from what follows `hook`, or None. The marker comment arrives as plain words when the line runs in a shell without `#` comments (cmd.exe)."""
    if "#" in args:
        args = args[:args.index("#")]
    if not args or args[0] not in ("stop", "pre"):
        return None
    if len(args) == 1:
        return args[0], "claude-code"
    if len(args) == 3 and args[1] == "--agent" and args[2] in HOOK_AGENTS:
        return args[0], args[2]
    return None


def _run_hook(args: list) -> int:
    """The assistant is waiting on this. Whatever goes wrong here, it exits 0 and says nothing: exit 2 would mean "block", and a bug must not stop the assistant."""
    try:
        _set_up_streams(utf8=True)
        parsed = _hook_args(args)
        if parsed is None:
            from .hooks import _note
            _note("args", f"hook started with arguments this version does not know: {args}; nothing checked")
            return 0
        event = _take_event()
        if parsed[0] == "pre" and event is not None and _cannot_be_refused(event):
            return 0
        from .hooks import run_hook
        run_hook(*parsed)
        _flush_stdout()
    except BaseException:
        _silence_stdout()
    return 0


def _take_event():
    """Read the hook's event, leaving it readable for the code that judges it. None when there is no stdin."""
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:
        return None
    import io
    event = stream.read()
    sys.stdin = io.TextIOWrapper(io.BytesIO(event), encoding="utf-8", errors="replace")
    return event


CAN_HIDE_A_RESULT = (b"|", b"<", b">", b"`", b"$(", b"$'", b"\\u00")   # a pipe, a redirect, a capture, a process substitution, or one of them spelled as an escape


def _cannot_be_refused(event: bytes) -> bool:
    """The pre hook refuses a command that keeps a result from the agent, and every way of doing that needs one of these characters. A well-formed
    event with none of them needs no rule table loaded, which is what makes most commands cheap. `2>&1` hides nothing. conftest.py checks every
    refusal in the test suite against this, so a new kind of refusal that this would skip fails there."""
    body = event.replace(b"2>&1", b"")
    if any(mark in body for mark in CAN_HIDE_A_RESULT):
        return False
    import json
    try:
        data = json.loads(event)
    except (ValueError, RecursionError):
        return False
    if not isinstance(data, dict):
        return False
    folder = data.get("cwd") or (data.get("workspace_roots") or [""])[0] if isinstance(data.get("workspace_roots") or [], list) else data.get("cwd")
    while isinstance(folder, str) and folder:   # a repository's .honestly.json can make the hook say something once per conversation: that takes the long way
        if os.path.lexists(os.path.join(folder, ".honestly.json")):
            return False
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    return True


def _dispatch(args: list):
    import argparse
    from . import __version__
    p = argparse.ArgumentParser(prog="honestly", description="Block unverified \"tests pass / fixed / pushed\" claims from coding agents, and audit past sessions.",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=EXIT_CODES)
    p.add_argument("--version", action="version", version=f"honestly {__version__}")
    sub = p.add_subparsers(dest="cmd", required=False)
    pa = sub.add_parser("audit", help="scan Claude Code, Codex, Cursor and Gemini CLI session logs and print the report")
    pa.add_argument("--root", default=None, help="Claude Code projects dir (default ~/.claude/projects, or under $CLAUDE_CONFIG_DIR)")
    pa.add_argument("--codex-root", default=None, help="Codex sessions dir (default ~/.codex/sessions)")
    pa.add_argument("--agent", action="append", choices=["claude-code", "codex", "cursor", "gemini"], help="limit to one assistant (repeatable)")
    pa.add_argument("--since", default=None, help="only claims from the last N days/weeks/months, e.g. 30d, 8w, 3m")
    pa.add_argument("--json", default=None, help="also write every finding as JSONL")
    pa.add_argument("--summary-json", action="store_true", help="print machine-readable counts instead of the report")
    pa.add_argument("--clear-cache", action="store_true", help="empty ~/.honestly/cache and stop")
    _common(pa); pa.set_defaults(fn=cmd_audit)
    ps = sub.add_parser("share", help="write a shareable card (SVG, and PNG when a converter is available)")
    ps.add_argument("--root", default=None, help="Claude Code projects dir (default ~/.claude/projects, or under $CLAUDE_CONFIG_DIR)")
    ps.add_argument("--codex-root", default=None, help="Codex sessions dir (default ~/.codex/sessions)")
    ps.add_argument("--out", default=None, help="output directory (default ~/.honestly)")
    ps.add_argument("--since", default=None, help="e.g. 30d, 8w, 3m")
    _common(ps); ps.set_defaults(fn=cmd_share)
    pe = sub.add_parser("explain", help="show the full timeline behind the n-th flagged claim")
    pe.add_argument("n", type=int); pe.add_argument("--root", default=None); pe.add_argument("--codex-root", default=None); pe.add_argument("--since", default=None)
    _common(pe); pe.set_defaults(fn=cmd_explain)
    pc = sub.add_parser("catches", help="what guard stopped recently (reads ~/.honestly/catches.jsonl)")
    pc.add_argument("--days", type=_positive_int, default=7, help="window in days (default 7)")
    pc.add_argument("--card", action="store_true", help="also write a shareable card (SVG, and PNG when a converter is available)")
    pc.add_argument("--lang", choices=["auto", "zh", "en"], default="auto")
    pc.add_argument("--out", default=None, help="directory for the card (default ~/.honestly)")
    pc.set_defaults(fn=cmd_catches)
    pg = sub.add_parser("guard", help="install / uninstall the hooks (Claude Code by default; --agent codex | cursor | gemini | all)")
    pg.add_argument("action", choices=["install", "uninstall", "status", "notify"])
    pg.add_argument("value", nargs="?", choices=["on", "off"], help="for notify: on | off")
    pg.add_argument("--dry-run", action="store_true", help="print the resulting hooks section without writing")
    pg.add_argument("--agent", choices=["claude-code", "codex", "cursor", "gemini", "all"], default=None, help="which assistant (default: claude-code; status shows all)")
    pg.set_defaults(fn=cmd_guard)
    pi = sub.add_parser("ignore", help="never treat sentences containing this phrase as a claim (one command to silence a false catch)")
    pi.add_argument("phrase", nargs="?"); pi.add_argument("--remove", action="store_true"); pi.add_argument("--list", action="store_true")
    pi.add_argument("--project", action="store_true", help="write to ./.honestly.json instead of ~/.honestly/config.json")
    pi.set_defaults(fn=cmd_ignore)
    pcf = sub.add_parser("config", help="show or change strictness, language, switched-off categories and custom verify commands")
    pcf.add_argument("key", nargs="?", choices=["strictness", "language", "off", "on", "verify", "unverify"]); pcf.add_argument("value", nargs="?")
    pcf.add_argument("--project", action="store_true", help="write to ./.honestly.json instead of ~/.honestly/config.json")
    pcf.set_defaults(fn=cmd_config)
    pt = sub.add_parser("trust", help="let this project's .honestly.json relax the rules; recorded for this exact file (needs your own terminal)")
    pt.add_argument("--remove", action="store_true", help="stop trusting this project's file"); pt.add_argument("--list", action="store_true", help="show every trusted file")
    pt.set_defaults(fn=cmd_trust)
    pu = sub.add_parser("purge", help="delete what honestly recorded under ~/.honestly (catches, logs, cache, cards); needs your own terminal")
    pu.add_argument("--all", action="store_true", help="also delete your settings and trusted files"); pu.add_argument("--dry-run", action="store_true", help="only list what would go")
    pu.set_defaults(fn=cmd_purge)
    pf = sub.add_parser("feedback", help="turn a catch that looks wrong into an issue-ready text (latest by default)")
    pf.add_argument("n", type=int, nargs="?", default=1, help="1 = latest catch, 2 = the one before, ..."); pf.add_argument("--issue", action="store_true", help="also print a pre-filled GitHub issue link")
    pf.set_defaults(fn=cmd_feedback)
    pr = sub.add_parser("rule", help="add a short 'verify before you claim' section to the project's CLAUDE.md / AGENTS.md / GEMINI.md / Cursor rules")
    pr.add_argument("action", choices=["install", "uninstall", "status"]); pr.add_argument("--agent", choices=["claude-code", "codex", "gemini", "cursor"], default=None, help="default: claude-code; status shows all four")
    pr.add_argument("--dir", default=None, help="project directory (default: current)"); pr.add_argument("--lang", choices=["en", "zh"], default="en")
    pr.set_defaults(fn=cmd_rule)
    pn = sub.add_parser("pr-note", help="the verification evidence behind this branch (last edit, tests that ran after it, flagged claims) as a pull-request block")
    pn.add_argument("--gh", action="store_true", help="put the block into this branch's open PR description with gh (replaces an earlier one)")
    pn.add_argument("--pr", default=None, help="with --gh: PR number or URL (default: the PR of the current branch)")
    pn.add_argument("--base", default=None, help="base branch the work started from (default: origin's default branch)")
    pn.add_argument("--since", default=None, help="override the window: 30m, 2h, 3d, 1w or an ISO time")
    pn.add_argument("--agent", action="append", choices=["claude-code", "codex", "cursor", "gemini"], help="limit to one assistant (repeatable)")
    pn.add_argument("--out", default=None, help="write the block to a file instead of stdout")
    pn.add_argument("--check", action="store_true", help="exit 1 unless a test ran after the last code edit and passed")
    pn.add_argument("--root", default=None, help=argparse.SUPPRESS); pn.add_argument("--codex-root", default=None, help=argparse.SUPPRESS)
    pn.set_defaults(fn=cmd_pr_note)
    pd = sub.add_parser("doctor", help="check the install: hooks, paths, logs, and a live self-test of the guard")
    pd.add_argument("--lang", choices=["auto", "zh", "en"], default="auto"); pd.set_defaults(fn=cmd_doctor)
    ph = sub.add_parser("hook", help="(internal) run as the assistant's hook; reads the hook event as JSON on stdin")
    ph.add_argument("which", choices=["stop", "pre"]); ph.add_argument("--agent", choices=["claude-code", "codex", "cursor", "gemini"], default="claude-code")
    ph.set_defaults(fn=lambda a: _run_hook([a.which, "--agent", a.agent]))
    pm = sub.add_parser("sample", help="(maintainers) draw a labelling sample from a findings JSONL")
    pm.add_argument("findings"); pm.add_argument("--verdict", default="unbacked"); pm.add_argument("--n", type=int, default=100)
    pm.add_argument("--per-session", type=int, default=8); pm.add_argument("--seed", type=int, default=42)
    pm.add_argument("--exclude", nargs="*", default=[]); pm.add_argument("--out", default=".honestly-labels/label_sheet.md")
    pm.set_defaults(fn=cmd_sample)
    a = p.parse_args(args)
    if not a.cmd:
        from .hooks import guard
        status = "; ".join(l.split(": ", 1)[1].split(" (")[0] + " for " + l.split("(")[1].split(")")[0] for l in guard("status", agent="all").splitlines() if "installed for" in l or "active through" in l) or "not installed (honestly guard install)"
        print(OVERVIEW.format(v=__version__, status=status)); return 0
    from . import store
    store.tighten()
    try:
        return a.fn(a)
    finally:
        store.tighten()


def _say(message: str) -> None:
    try:
        print(message, file=sys.stderr)
    except Exception:
        pass


def _failed(e: Exception) -> int:
    if isinstance(e, OSError):
        if e.filename:
            _say(f"honestly: cannot use {e.filename}: {e.strerror}")
        elif isinstance(e, FileNotFoundError):
            _say("honestly: the current folder no longer exists. cd to another folder and try again.")
        else:
            _say(f"honestly: {e}")
    elif isinstance(e, OverflowError):
        _say("honestly: that number is too large.")
    else:
        _say(f"honestly: unexpected error: {e.__class__.__name__}: {e}. Set HONESTLY_DEBUG=1 to see where; please report it with honestly feedback --issue.")
    if os.environ.get("HONESTLY_DEBUG"):
        import traceback
        traceback.print_exc()
    return 1


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["hook"] and "-h" not in args and "--help" not in args:
        return _run_hook(args[1:])
    _set_up_streams()
    try:
        rc = _dispatch(args)
        _flush_stdout()
        return rc or 0
    except SystemExit:   # argparse's own exit, a refusal with its message, a command's exit code
        try:
            _flush_stdout()
        except BrokenPipeError:
            _silence_stdout()
            raise SystemExit(141) from None
        raise
    except BrokenPipeError:
        _silence_stdout()
        return 141
    except KeyboardInterrupt:
        _silence_stdout()
        return 130
    except Exception as e:
        return _failed(e)


if __name__ == "__main__":
    sys.exit(main())
