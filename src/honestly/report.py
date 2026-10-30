"""Human-readable audit report and the shareable card."""
from __future__ import annotations
import html
import os
import pathlib
import re
import subprocess
from collections import Counter, defaultdict

GENERIC_DIRS = {"工程文件", "src", "video", "web", "app", "frontend", "backend", "project", "code", "repo", "scratchpad"}
HEADLINE = {"backed": "verified", "unbacked": "unverified", "unverifiable": "could not check", "contradicted": "contradicted"}


def stats(findings):
    inscope = [f for f in findings if f.verdict in ("backed", "unbacked", "unverifiable", "contradicted", "weak")]
    c = Counter(f.verdict for f in inscope)
    decided = c["backed"] + c["unbacked"] + c["contradicted"]
    rate = (c["backed"] / decided) if decided else None
    by_agent = defaultdict(Counter)
    for f in inscope:
        key = f"{f.agent} {f.model or f.version}".strip()
        by_agent[key][f.verdict] += 1
    reasons = Counter(f.reason.split(":")[0] for f in inscope if f.verdict in ("unbacked", "contradicted"))
    unverifiable_why = Counter(f.reason.split(":")[0].split(";")[0] for f in inscope if f.verdict == "unverifiable")
    by_project = defaultdict(Counter)
    for f in inscope:
        parts = [x for x in re.split(r"[\\/]", (getattr(f, "project", "") or "").rstrip("/\\")) if x]
        name = parts[-1] if parts else "(unknown)"
        if name in GENERIC_DIRS and len(parts) >= 2:
            name = parts[-2] + "/" + name
        by_project[name][f.verdict] += 1
    return {"counts": dict(c), "decided": decided, "rate": rate, "by_agent": {k: dict(v) for k, v in by_agent.items()},
            "by_project": {k: dict(v) for k, v in by_project.items()}, "reasons": reasons.most_common(5),
            "unverifiable_why": unverifiable_why.most_common(6)}


def text_report(findings, sessions: int, duplicates: int) -> str:
    s = stats(findings)
    c = s["counts"]
    lines = []
    rate = s["rate"]
    lines.append("honestly audit")
    lines.append("=" * 60)
    if rate is None:
        if sessions and sum(c.values()):
            lines.append(f"Found {sum(c.values())} claim(s), but none could be decided either way.")
            lines.append(f"  could not check {c.get('unverifiable', 0)}   evidence is off-transcript (subagents, background, piped exit codes, remote runs)")
            if c.get("weak"):
                lines.append(f"  weak            {c.get('weak', 0)}   a visual fix judged by looking at a rendered image")
            lines.append("  Run `honestly audit --json findings.jsonl` to see each one with context.")
            return "\n".join(lines)
        if sessions == 0:
            lines.append("No session logs found.")
            lines.append("  looked in: ~/.claude/projects (Claude Code), ~/.codex/sessions (Codex),")
            lines.append("             ~/.cursor/projects/*/agent-transcripts (Cursor), ~/.gemini/tmp/*/chats (Gemini CLI)")
            lines.append("  Plain Claude/ChatGPT/Gemini web chat keeps no logs on disk, so there is nothing to audit.")
            lines.append("  If your logs live elsewhere: honestly audit --root <dir> or --codex-root <dir>")
        else:
            lines.append(f"Scanned {sessions} session(s), but none contained a checkable claim.")
            lines.append("  A checkable claim is the agent saying \"tests pass\", \"fixed\", \"build ok\", \"pushed\"")
            lines.append("  about code it edited in that same turn. Short chats, questions and reading-only")
            lines.append("  sessions produce none. Come back after a few coding sessions.")
        return "\n".join(lines)
    lines.append(f"Verification rate: {rate*100:.1f}%   ({c.get('backed',0)} verified / {s['decided']} decided claims)")
    lines.append(f"Sessions: {sessions}   Claims about this turn's work: {sum(c.values())}   (forked duplicates removed: {duplicates})")
    lines.append("")
    lines.append(f"  verified        {c.get('backed',0):4}   the check or action behind the claim is on the transcript and succeeded")
    lines.append(f"  unverified      {c.get('unbacked',0):4}   it claimed success (tests pass, fixed, sent, deployed, saved...) with nothing behind it")
    lines.append(f"  contradicted    {c.get('contradicted',0):4}   the check or action it ran says otherwise")
    lines.append(f"  could not check {c.get('unverifiable',0):4}   evidence is off-transcript (subagents, background, piped exit codes, remote runs)")
    if c.get("weak"):
        lines.append(f"  weak            {c.get('weak',0):4}   a visual fix judged by looking at a rendered image; not counted either way")
    if s.get("unverifiable_why"):
        lines.append("")
        lines.append("Why it could not check:")
        for why, n in s["unverifiable_why"]:
            lines.append(f"  {n:3}  {why[:90]}")
    lines.append("")
    if len(s["by_agent"]) > 1:
        lines.append("By agent / model:")
        for k, v in sorted(s["by_agent"].items(), key=lambda kv: -sum(kv[1].values())):
            d = v.get("backed", 0) + v.get("unbacked", 0) + v.get("contradicted", 0)
            r = f"{v.get('backed',0)/d*100:.0f}%" if d else "n/a"
            lines.append(f"  {k:40} {r:>5}  ({d} decided, {v.get('unverifiable',0)} could not check)")
        lines.append("")
    projects = [(k, v) for k, v in s["by_project"].items() if (v.get("backed", 0) + v.get("unbacked", 0) + v.get("contradicted", 0)) >= 3]
    if len(projects) > 1:
        lines.append("By project (3+ decided claims):")
        for k, v in sorted(projects, key=lambda kv: -sum(kv[1].values()))[:8]:
            d = v.get("backed", 0) + v.get("unbacked", 0) + v.get("contradicted", 0)
            lines.append(f"  {k[:40]:40} {v.get('backed',0)/d*100:4.0f}%  ({d} decided)")
        lines.append("")
    if s["reasons"]:
        lines.append("Most common problems:")
        for reason, n in s["reasons"]:
            lines.append(f"  {n:3}  {reason}")
        lines.append("")
    ex = [f for f in findings if f.verdict in ("unbacked", "contradicted")][:3]
    if ex:
        lines.append("Examples (run `honestly audit --json findings.jsonl` for all, with context):")
        for f in ex:
            lines.append(f"  - [{f.category}] \"{f.claim[:90]}\"")
            lines.append(f"      last edit: {f.last_edit[:80].splitlines()[0] if f.last_edit else '-'}")
            lines.append(f"      {f.reason}")
    lines.append("")
    lines.append("Deterministic rules, standard library only, nothing leaves your machine. `could not check` is not a pass.")
    t = trend(findings)
    if t:
        lines.append("")
        lines.append(t)
    return "\n".join(lines)


def trend(findings, weeks: int = 8) -> str:
    """Verification rate per ISO week, newest last. Empty when fewer than two weeks have a decided claim."""
    import datetime
    from collections import defaultdict
    by_week = defaultdict(lambda: [0, 0])   # week -> [backed, decided]
    for f in findings:
        if f.verdict not in ("backed", "unbacked", "contradicted") or not f.ts:
            continue
        try:
            d = datetime.datetime.fromisoformat(str(f.ts)[:19])
        except Exception:
            continue
        y, w, _ = d.isocalendar()
        key = f"{y}-W{w:02d}"
        by_week[key][1] += 1
        if f.verdict == "backed":
            by_week[key][0] += 1
    keys = sorted(by_week)[-weeks:]
    if len(keys) < 2:
        return ""
    lines = ["By week (verified / decided):"]
    for k in keys:
        b, n = by_week[k]
        rate = b / n if n else 0
        bar = "█" * round(rate * 20) + "░" * (20 - round(rate * 20))
        lines.append(f"  {k}  {bar} {rate * 100:3.0f}%  ({b}/{n})")
    first, last = by_week[keys[0]], by_week[keys[-1]]
    if first[1] and last[1]:
        delta = (last[0] / last[1] - first[0] / first[1]) * 100
        lines.append(f"  {'up' if delta > 0 else 'down' if delta < 0 else 'flat'} {abs(delta):.0f} points from {keys[0]} to {keys[-1]}")
    return "\n".join(lines)


def svg_card(findings, sessions: int) -> str:
    """1200x630 share card. Dark, one accent per verdict, system fonts only (renders offline)."""
    s = stats(findings)
    c = s["counts"]
    backed = c.get("backed", 0)
    unver = c.get("unbacked", 0) + c.get("contradicted", 0)
    unknown = c.get("unverifiable", 0)
    decided = s["decided"]
    rate = s["rate"]
    W, H = 1200, 630
    PAD = 84
    BG, INK, MUTED, DIM, LINE = "#0a0a0b", "#f2f1ec", "#8b8b90", "#55555b", "#232327"
    GREEN, RED, GREY = "#f2f1ec", "#e9b949", "#3a3a40"
    SANS = "SF Pro Display, Segoe UI Variable Display, Segoe UI, Helvetica Neue, Helvetica, Arial, sans-serif"
    MONO = "SF Mono, Menlo, Consolas, Liberation Mono, monospace"

    big = f"{rate*100:.0f}" if rate is not None else "n/a"
    pct = "%" if rate is not None else ""

    # segmented bar: 4px gaps, rounded ends, a non-zero segment is never thinner than 10px
    total = max(1, backed + unver + unknown)
    bar_x, bar_y, bar_w, bar_h, gap = PAD, 452, W - 2 * PAD, 14, 4
    segs = [(GREEN, backed), (RED, unver), (GREY, unknown)]
    nonzero = [n for _, n in segs if n]
    usable = bar_w - gap * (len(nonzero) - 1 if nonzero else 0)
    bars, x = [], bar_x
    if not nonzero:
        bars.append(f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="7" fill="{LINE}"/>')
    for color, n in segs:
        if not n:
            continue
        w = max(10.0, usable * n / total)
        bars.append(f'<rect x="{x:.1f}" y="{bar_y}" width="{w:.1f}" height="{bar_h}" rx="7" fill="{color}"/>')
        x += w + gap

    # three stat rows on the right
    col_x = 700
    stat_rows = [(GREEN, backed, "verified", "a check ran after the last edit"),
                 (RED, unver, "unverified", "claimed success, no check behind it"),
                 (MUTED if unknown else GREY, unknown, "could not check", "evidence lives off the transcript")]
    rows = []
    for i, (color, n, label, sub) in enumerate(stat_rows):
        y = 150 + i * 92
        rows.append(f'<rect x="{col_x}" y="{y - 30}" width="3" height="60" rx="1.5" fill="{color}"/>')
        rows.append(f'<text x="{col_x + 24}" y="{y + 2}" font-size="40" font-weight="600" fill="{INK}" letter-spacing="-1">{n}</text>')
        nx = col_x + 24 + 26 * len(str(n)) + 14
        rows.append(f'<text x="{nx}" y="{y + 2}" font-size="24" font-weight="500" fill="{INK}">{label}</text>')
        rows.append(f'<text x="{col_x + 24}" y="{y + 30}" font-size="17" fill="{MUTED}">{sub}</text>')

    if decided == 0:
        verdict_line = "No checkable claim yet. Come back after a few coding sessions."
    elif unver:
        verdict_line = f'{unver} time{"s" if unver != 1 else ""} it said "done" with nothing behind it'
    else:
        verdict_line = 'Every "done" had the action behind it'

    head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{SANS}">\n'
            f'<defs><radialGradient id="glow" cx="0.12" cy="0" r="0.9">'
            f'<stop offset="0" stop-color="#17171a"/><stop offset="1" stop-color="{BG}"/></radialGradient></defs>\n'
            f'<rect width="{W}" height="{H}" fill="url(#glow)"/>\n')
    body = [
        f'<text x="{PAD}" y="86" font-size="22" font-weight="600" fill="{INK}" letter-spacing="0.5">honestly</text>',
        f'<text x="{PAD + 118}" y="86" font-size="22" fill="{MUTED}">Did my coding agent verify what it claimed?</text>',
        f'<line x1="{PAD}" y1="108" x2="{W - PAD}" y2="108" stroke="{LINE}" stroke-width="1"/>',
        f'<text x="{PAD - 6}" y="318" font-size="{208 if rate is not None else 150}" font-weight="700" fill="{INK}" letter-spacing="-10">{big}'
        f'<tspan font-size="96" font-weight="600" fill="{MUTED}" letter-spacing="0" dx="6">{pct}</tspan></text>',
        f'<text x="{PAD}" y="372" font-size="24" fill="{MUTED}">verification rate</text>',
        f'<text x="{PAD}" y="404" font-size="19" fill="{DIM}">{backed} of {decided} claims had a check that ran after the last code edit</text>',
        *rows, *bars,
        f'<text x="{PAD}" y="508" font-size="26" font-weight="500" fill="{INK}">{verdict_line}</text>',
        f'<line x1="{PAD}" y1="548" x2="{W - PAD}" y2="548" stroke="{LINE}" stroke-width="1"/>',
        f'<text x="{PAD}" y="585" font-size="17" fill="{DIM}">{sessions} session{"s" if sessions != 1 else ""} read locally. Deterministic rules, no model, no API key.</text>',
        f'<text x="{W - PAD}" y="585" font-size="17" fill="{MUTED}" text-anchor="end" font-family="{MONO}">pip install honestly</text>',
    ]
    return head + "\n".join(body) + "\n</svg>"


def catches_card(rows, days: int) -> str:
    """1200x630 share card for what guard stopped. Same design language as the audit card."""
    from collections import Counter
    W, H, PAD = 1200, 630, 84
    BG, INK, MUTED, DIM, LINE = "#0a0a0b", "#f2f1ec", "#8b8b90", "#55555b", "#232327"
    RED, AMBER, GREY = "#e9b949", "#f2f1ec", "#3a3a40"
    SANS = "SF Pro Display, Segoe UI Variable Display, Segoe UI, Helvetica Neue, Helvetica, Arial, sans-serif"
    MONO = "SF Mono, Menlo, Consolas, Liberation Mono, monospace"
    n = len(rows)
    stop = sum(1 for r in rows if r.get("kind") == "stop")
    pre = n - stop
    by_agent = Counter(str(r.get("agent") or "").replace("claude-code", "Claude Code").replace("codex", "Codex").replace("gemini", "Gemini CLI").replace("cursor", "Cursor") for r in rows)
    top = ", ".join(f"{k} {v}" for k, v in by_agent.most_common(2) if k) or "no assistant yet"
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    col_x = 700
    stat_rows = [(RED, stop, "said \u201cdone\u201d", "with nothing behind it: no test, no send, no save"),
                 (AMBER, pre, "cut-off checks", "tests piped through tail/head, failures hidden"),
                 (GREY, len(by_agent), "assistant" + ("s" if len(by_agent) != 1 else ""), esc(top))]
    rws = []
    for i, (color, v, label, sub) in enumerate(stat_rows):
        y = 150 + i * 92
        rws.append(f'<rect x="{col_x}" y="{y - 30}" width="3" height="60" rx="1.5" fill="{color}"/>')
        rws.append(f'<text x="{col_x + 24}" y="{y + 2}" font-size="40" font-weight="600" fill="{INK}" letter-spacing="-1">{v}</text>')
        nx = col_x + 24 + 26 * len(str(v)) + 14
        rws.append(f'<text x="{nx}" y="{y + 2}" font-size="24" font-weight="500" fill="{INK}">{label}</text>')
        rws.append(f'<text x="{col_x + 24}" y="{y + 30}" font-size="17" fill="{MUTED}">{sub}</text>')
    last = ""
    if rows:
        last = esc(re.sub(r"^\u26a0\ufe0f\s*", "", str(rows[-1].get("message", "")))[:88]) + ("…" if len(str(rows[-1].get("message", ""))) > 88 else "")
    verdict = (f'{n} time{"s" if n != 1 else ""} my coding agent said \u201cdone\u201d without doing it' if n
               else "Nothing stopped yet. Either every claim had its check, or guard is not installed.")
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{SANS}">\n'
            f'<defs><radialGradient id="glow" cx="0.12" cy="0" r="0.9"><stop offset="0" stop-color="#17171a"/><stop offset="1" stop-color="{BG}"/></radialGradient></defs>\n'
            f'<rect width="{W}" height="{H}" fill="url(#glow)"/>\n')
    body = [
        f'<text x="{PAD}" y="86" font-size="22" font-weight="600" fill="{INK}" letter-spacing="0.5">honestly</text>',
        f'<text x="{PAD + 118}" y="86" font-size="22" fill="{MUTED}">What the guard stopped in the last {days} days</text>',
        f'<line x1="{PAD}" y1="108" x2="{W - PAD}" y2="108" stroke="{LINE}" stroke-width="1"/>',
        f'<text x="{PAD - 6}" y="318" font-size="208" font-weight="700" fill="{INK}" letter-spacing="-10">{n}</text>',
        f'<text x="{PAD}" y="372" font-size="24" fill="{MUTED}">times stopped</text>',
        f'<text x="{PAD}" y="404" font-size="19" fill="{DIM}">each one is a claim that would have reached me as \u201cdone\u201d</text>',
        *rws,
        f'<text x="{PAD}" y="470" font-size="26" font-weight="500" fill="{INK}">{esc(verdict)}</text>',
        f'<text x="{PAD}" y="506" font-size="17" fill="{MUTED}" font-family="{MONO}">{last}</text>' if last else "",
        f'<line x1="{PAD}" y1="548" x2="{W - PAD}" y2="548" stroke="{LINE}" stroke-width="1"/>',
        f'<text x="{PAD}" y="585" font-size="17" fill="{DIM}">Caught at the moment it was said, before the reply reached me. Local only, no model, no API key.</text>',
        f'<text x="{W - PAD}" y="585" font-size="17" fill="{MUTED}" text-anchor="end" font-family="{MONO}">pip install honestly</text>',
    ]
    return head + "\n".join(b for b in body if b) + "\n</svg>"


def write_catches_card(rows, days: int, out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    svg_path = os.path.join(out_dir, "honestly-catches.svg")
    with open(svg_path, "w", encoding="utf-8") as fh:
        fh.write(catches_card(rows, days))
    written = [svg_path]
    png_path = os.path.join(out_dir, "honestly-catches.png")
    if svg_to_png(svg_path, png_path):
        written.append(png_path)
    return written


def write_card(findings, sessions: int, out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    svg_path = os.path.join(out_dir, "honestly-card.svg")
    with open(svg_path, "w", encoding="utf-8") as fh:
        fh.write(svg_card(findings, sessions))
    written = [svg_path]
    png_path = os.path.join(out_dir, "honestly-card.png")
    if svg_to_png(svg_path, png_path):
        written.append(png_path)
    return written


def svg_to_png(svg_path: str, png_path: str) -> bool:
    """rsvg-convert, else a headless Chrome/Edge screenshot; False when neither is available."""
    pf, pf86, lad = os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), os.environ.get("LOCALAPPDATA", "")
    browsers = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium",
                os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"), os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(lad, "Google", "Chrome", "Application", "chrome.exe") if lad else "",
                os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"), os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
                "/usr/bin/google-chrome", "/usr/bin/microsoft-edge",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "google-chrome", "chromium", "chromium-browser", "msedge"]
    attempts = [["rsvg-convert", "-w", "1200", "-o", png_path, svg_path]]
    for b in browsers:
        if not b:
            continue
        attempts.append([b, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--screenshot={png_path}", "--window-size=1200,630", pathlib.Path(svg_path).resolve().as_uri()])
    try:
        if os.path.exists(png_path):
            os.remove(png_path)   # a stale file must not pass as this run's output
    except Exception:
        pass
    for cmd in attempts:
        try:
            subprocess.run(cmd, check=False, capture_output=True, timeout=90)
        except Exception:
            continue
        if os.path.exists(png_path) and os.path.getsize(png_path) > 0:
            return True   # a first-run Chrome exits non-zero and still writes the screenshot: the file decides
    return False


def want_color(stream=None) -> bool:
    """ANSI colour only on an interactive terminal that understands it, never into a file or pipe."""
    import sys
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR") or not hasattr(stream, "isatty") or not stream.isatty():
        return False
    if os.name == "nt":
        return bool(os.environ.get("WT_SESSION") or os.environ.get("ANSICON") or os.environ.get("TERM_PROGRAM") or os.environ.get("TERM"))
    return os.environ.get("TERM", "dumb") != "dumb"


_ANSI = {"bold": "\033[1m", "dim": "\033[2m", "green": "\033[32m", "red": "\033[31m", "yellow": "\033[33m", "grey": "\033[90m", "reset": "\033[0m"}
_ROW_COLORS = [("  verified ", "green"), ("  unverified ", "red"), ("  contradicted ", "red"), ("  could not check ", "grey"), ("  weak ", "yellow")]


def colorize(text: str) -> str:
    """Bold the headline numbers, tint the verdict rows, dim the explanations. Layout is unchanged."""
    import re
    out = []
    for line in text.splitlines():
        if line == "honestly audit" or line.endswith(":") and not line.startswith(" "):
            line = f"{_ANSI['bold']}{line}{_ANSI['reset']}"
        elif line.startswith("Verification rate:"):
            line = re.sub(r"(\d+\.\d%)", lambda m: f"{_ANSI['bold']}{m.group(1)}{_ANSI['reset']}", line, count=1)
        elif line.startswith("=") and set(line) == {"="}:
            line = f"{_ANSI['grey']}{line}{_ANSI['reset']}"
        else:
            for prefix, color in _ROW_COLORS:
                if line.startswith(prefix):
                    m = re.match(r"(\s+\S+(?: \S+){0,2}\s+\d+)(\s+.*)?$", line)
                    if m:
                        line = f"{_ANSI[color]}{m.group(1)}{_ANSI['reset']}{_ANSI['dim']}{m.group(2) or ''}{_ANSI['reset']}"
                    break
        out.append(line)
    return "\n".join(out)
