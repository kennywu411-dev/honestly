from __future__ import annotations
import argparse
import json
import os
import random
import re
import sys
from dataclasses import asdict
from . import claude_code, codex
from .audit import audit_turns
from .report import text_report, write_card, colorize, want_color


def _since_cutoff(spec):
    if not spec:
        return None
    import datetime as dt
    m = re.fullmatch(r"(\d+)([dwm])", spec.strip())
    if not m:
        raise SystemExit("--since takes a number followed by d, w or m, e.g. 30d")
    days = int(m.group(1)) * {"d": 1, "w": 7, "m": 30}[m.group(2)]
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")


ALL_AGENTS = ("claude-code", "codex", "cursor", "gemini")


def _audited(path, parse, cfg_sig, use_cache, extra=""):
    from . import cache
    if use_cache:
        hit = cache.get(path, cfg_sig + extra)
        if hit is not None:
            return hit
    out = audit_turns(parse(path))
    if use_cache:
        cache.put(path, cfg_sig + extra, out)
    return out


def collect(root_claude=None, root_codex=None, agents=ALL_AGENTS, since=None, project=None, use_cache=True, cursor_root=None, gemini_root=None):
    from . import config
    cfg = config.load(os.getcwd())
    config.apply(cfg)   # the user's ignore list and custom checks apply to the audit too
    cfg_sig = json.dumps(cfg, sort_keys=True, ensure_ascii=False)
    cutoff = _since_cutoff(since)
    findings, sessions = [], 0
    if "claude-code" in agents:
        for path in claude_code.iter_sessions(root_claude):
            sessions += 1
            subs = claude_code.subagent_files(path)
            extra = "|".join(f"{os.path.getsize(s)}:{os.path.getmtime(s)}" for s in subs)
            findings.extend(_audited(path, claude_code.parse_session, cfg_sig, use_cache, extra))
    if "codex" in agents:
        for path in codex.iter_sessions(root_codex):
            sessions += 1
            findings.extend(_audited(path, codex.parse_session, cfg_sig, use_cache))
    from . import agents as _ag
    if "cursor" in agents:
        for path in _ag.cursor_sessions(cursor_root):
            sessions += 1
            findings.extend(_audited(path, _ag.cursor_parse, cfg_sig, use_cache))
    if "gemini" in agents:
        for path in _ag.gemini_sessions(gemini_root):
            sessions += 1
            findings.extend(_audited(path, _ag.gemini_parse, cfg_sig, use_cache))
    if project:
        findings = [f for f in findings if project.lower() in (f.project or "").lower()]
    if cutoff:
        findings = [f for f in findings if (f.ts or "9999") >= cutoff]
    seen, deduped = set(), []
    for f in findings:
        key = (f.category, f.claim, f.last_edit[:60], str(f.ts or "")[:16])
        if key in seen:
            continue
        seen.add(key); deduped.append(f)
    return deduped, sessions, len(findings) - len(deduped)


def cmd_audit(a):
    agents = tuple(a.agent) if a.agent else ALL_AGENTS
    findings, sessions, dups = collect(a.root, a.codex_root, agents, a.since, project=a.project, use_cache=not a.no_cache, cursor_root=a.cursor_root, gemini_root=a.gemini_root)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            for f in findings:
                d = asdict(f); d["label"] = f.label
                fh.write(json.dumps(d, ensure_ascii=False) + "\n")
        print(f"wrote {len(findings)} findings to {a.json}", file=sys.stderr)
    if a.summary_json:
        from .audit import summarize
        s = summarize(findings); s["sessions"] = sessions; s["duplicates_removed_forks"] = dups
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return
    report = text_report(findings, sessions, dups)
    print(colorize(report) if want_color() else report)


def cmd_share(a):
    findings, sessions, _ = collect(a.root, a.codex_root, since=a.since, project=a.project, use_cache=not a.no_cache, cursor_root=a.cursor_root, gemini_root=a.gemini_root)
    out = a.out or os.path.expanduser("~/.honestly")
    written = write_card(findings, sessions, out)
    for p in written:
        print(p)
    if not any(p.endswith(".png") for p in written):
        print("PNG not written: no rsvg-convert, Chrome or Edge found. The .svg above opens in any browser; "
              "screenshot it there, or install one of those and run honestly share again.", file=sys.stderr)


def cmd_explain(a):
    findings, _, _ = collect(a.root, a.codex_root, since=a.since, project=a.project, use_cache=not a.no_cache, cursor_root=a.cursor_root, gemini_root=a.gemini_root)
    flagged = [f for f in findings if f.verdict in ("unbacked", "contradicted")]
    if not flagged:
        print("nothing flagged"); return
    if a.n < 1 or a.n > len(flagged):
        print(f"pick 1..{len(flagged)}"); return
    f = flagged[a.n - 1]
    print(f"[{a.n}/{len(flagged)}] {f.label}  ·  {f.category}  ·  {f.agent} {f.model or f.version}  ·  session {f.session[:8]} turn {f.turn}  ·  {f.ts[:19]}")
    print(f"project: {f.project or '-'}")
    print(f"claim:   {f.claim}")
    print(f"context: …{f.context}…")
    print(f"last code edit: {f.last_edit or '-'}")
    print("tools after it:" if f.tools_after_edit else "tools after it: (none)")
    for t in f.tools_after_edit:
        print(f"  - {t}")
    print(f"why: {f.reason}")


def cmd_catches(a):
    from .hooks import catches_report, _is_zh
    from .update import update_note
    from . import __version__
    print(catches_report(a.days, zh=None if a.lang == "auto" else a.lang == "zh"))
    if a.card:
        from .hooks import load_catches
        from .report import write_catches_card
        out = a.out or os.path.expanduser("~/.honestly")
        for p in write_catches_card(load_catches(a.days), a.days, out):
            print("wrote", p)
    note = update_note(__version__, zh=_is_zh(os.environ.get("LANG", "")))   # once a day, CLI only, never from the hooks
    if note:
        print("\n" + note)


def cmd_guard(a):
    from .hooks import guard, set_notify
    if a.action == "notify":
        print(set_notify((a.value or "on") == "on")); return
    agent = a.agent or ("all" if a.action == "status" else "claude-code")
    print(guard(a.action, dry_run=a.dry_run, agent=agent))


def cmd_ignore(a):
    from . import config
    if a.list or not a.phrase:
        print(config.show(os.getcwd())); return
    fn = config.remove_from if a.remove else config.add_to
    print(fn("ignore", a.phrase, project=a.project))


def cmd_config(a):
    from . import config
    if not a.key:
        print(config.show(os.getcwd())); return
    k, v = a.key, (a.value or "")
    if k in ("strictness", "language"):
        print(config.set_value(k, v, project=a.project)); return
    if k in ("off", "on"):
        cats = [c.strip() for c in v.split(",") if c.strip()]
        if not cats:
            raise SystemExit(f"honestly config {k}: name a category, e.g. honestly config {k} fixed  (categories: honestly config)")
        for cat in cats:
            print((config.add_to if k == "off" else config.remove_from)("off", cat, project=a.project))
        return
    if k in ("verify", "unverify"):
        if not v.strip():
            raise SystemExit(f'honestly config {k}: give the command, e.g. honestly config {k} "make smoke"')
        print((config.add_to if k == "verify" else config.remove_from)("verify_commands", v, project=a.project)); return
    raise SystemExit("usage: honestly config [strictness strict|normal|lenient | language auto|zh|en | off CAT[,CAT] | on CAT | verify \"CMD\" | unverify \"CMD\"] [--project]")


def cmd_feedback(a):
    from .support import feedback
    print(feedback(a.n, issue_url=a.issue))


def cmd_rule(a):
    from .support import rule, RULE_FILES
    if a.action == "status" and not a.agent:
        for agent in RULE_FILES:
            print(rule("status", agent, a.dir, zh=a.lang == "zh"))
        return
    print(rule(a.action, a.agent or "claude-code", a.dir, zh=a.lang == "zh"))


def cmd_doctor(a):
    from .support import doctor
    text, problems = doctor(zh=None if a.lang == "auto" else a.lang == "zh", with_problems=True)
    print(text)
    if problems:
        sys.exit(1)


def cmd_hook(a):
    from .hooks import run_hook
    sys.exit(run_hook(a.which, a.agent or "claude-code"))


def cmd_sample(a):
    rows = [json.loads(l) for l in open(a.findings, encoding="utf-8")]
    rows = [r for r in rows if r["verdict"] == a.verdict and not r["session"].startswith(tuple(a.exclude))]
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
  honestly doctor            check the install and run a live self-test
  honestly catches           what guard stopped this week   (--card for a shareable image)
  honestly audit             score your past sessions        (--since 30d, --project name, explain N, share)
  honestly ignore "phrase"   silence a false catch           (honestly config: strictness, language, custom checks)
  honestly feedback          turn a wrong catch into an issue-ready text

guard: {status}\nhonestly --help for everything.
"""


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):  # Windows redirects default to the locale code page
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    from . import __version__
    p = argparse.ArgumentParser(prog="honestly", description="Audit how often your coding agent verified what it claimed.")
    p.add_argument("--version", action="version", version=f"honestly {__version__}")
    sub = p.add_subparsers(dest="cmd", required=False)
    pa = sub.add_parser("audit", help="scan Claude Code, Codex, Cursor and Gemini CLI session logs and print the report")
    pa.add_argument("--root", default=None, help="Claude Code projects dir (default ~/.claude/projects)")
    pa.add_argument("--codex-root", default=None, help="Codex sessions dir (default ~/.codex/sessions)")
    pa.add_argument("--agent", action="append", choices=["claude-code", "codex", "cursor", "gemini"], help="limit to one assistant (repeatable)")
    pa.add_argument("--since", default=None, help="only claims from the last N days/weeks/months, e.g. 30d, 8w, 3m")
    pa.add_argument("--json", default=None, help="also write every finding as JSONL")
    pa.add_argument("--summary-json", action="store_true", help="print machine-readable counts instead of the report")
    _common(pa); pa.set_defaults(fn=cmd_audit)
    ps = sub.add_parser("share", help="write a shareable card (SVG, and PNG when a converter is available)")
    ps.add_argument("--root", default=None, help="Claude Code projects dir (default ~/.claude/projects)")
    ps.add_argument("--codex-root", default=None, help="Codex sessions dir (default ~/.codex/sessions)")
    ps.add_argument("--out", default=None, help="output directory (default ~/.honestly)")
    ps.add_argument("--since", default=None, help="e.g. 30d, 8w, 3m")
    _common(ps); ps.set_defaults(fn=cmd_share)
    pe = sub.add_parser("explain", help="show the full timeline behind the n-th flagged claim")
    pe.add_argument("n", type=int); pe.add_argument("--root", default=None); pe.add_argument("--codex-root", default=None); pe.add_argument("--since", default=None)
    _common(pe); pe.set_defaults(fn=cmd_explain)
    pc = sub.add_parser("catches", help="what guard stopped recently (reads ~/.honestly/catches.jsonl)")
    pc.add_argument("--days", type=int, default=7, help="window in days (default 7)")
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
    pf = sub.add_parser("feedback", help="turn a catch that looks wrong into an issue-ready text (latest by default)")
    pf.add_argument("n", type=int, nargs="?", default=1, help="1 = latest catch, 2 = the one before, ..."); pf.add_argument("--issue", action="store_true", help="also print a pre-filled GitHub issue link")
    pf.set_defaults(fn=cmd_feedback)
    pr = sub.add_parser("rule", help="add a short 'verify before you claim' section to the project's CLAUDE.md / AGENTS.md / GEMINI.md / Cursor rules")
    pr.add_argument("action", choices=["install", "uninstall", "status"]); pr.add_argument("--agent", choices=["claude-code", "codex", "gemini", "cursor"], default=None, help="default: claude-code; status shows all four")
    pr.add_argument("--dir", default=None, help="project directory (default: current)"); pr.add_argument("--lang", choices=["en", "zh"], default="en")
    pr.set_defaults(fn=cmd_rule)
    pd = sub.add_parser("doctor", help="check the install: hooks, paths, logs, and a live self-test of the guard")
    pd.add_argument("--lang", choices=["auto", "zh", "en"], default="auto"); pd.set_defaults(fn=cmd_doctor)
    ph = sub.add_parser("hook", help="(internal) run as the assistant's hook; reads the hook event as JSON on stdin")
    ph.add_argument("which", choices=["stop", "pre"]); ph.add_argument("--agent", choices=["claude-code", "codex", "cursor", "gemini"], default="claude-code")
    ph.set_defaults(fn=cmd_hook)
    pm = sub.add_parser("sample", help="(maintainers) draw a labelling sample from a findings JSONL")
    pm.add_argument("findings"); pm.add_argument("--verdict", default="unbacked"); pm.add_argument("--n", type=int, default=100)
    pm.add_argument("--per-session", type=int, default=8); pm.add_argument("--seed", type=int, default=42)
    pm.add_argument("--exclude", nargs="*", default=[]); pm.add_argument("--out", default=".honestly-labels/label_sheet.md")
    pm.set_defaults(fn=cmd_sample)
    a = p.parse_args(argv)
    if not a.cmd:
        from .hooks import guard
        status = "; ".join(l.split(": ", 1)[1].split(" (")[0] + " for " + l.split("(")[1].split(")")[0] for l in guard("status", agent="all").splitlines() if "installed for" in l) or "not installed (honestly guard install)"
        print(OVERVIEW.format(v=__version__, status=status)); return
    a.fn(a)


if __name__ == "__main__":
    main()
