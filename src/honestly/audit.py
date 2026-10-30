"""Core audit: for each claim, decide backed / unbacked / unverifiable."""
from __future__ import annotations
import re
from dataclasses import dataclass, asdict
from . import rules, noncode
from .claude_code import Turn, Event


@dataclass
class Finding:
    session: str
    turn: int
    version: str
    agent: str
    model: str
    ts: str
    category: str
    verdict: str          # backed | unbacked | weak | unverifiable | contradicted | not_this_turn | out_of_scope
    reason: str
    claim: str
    last_edit: str
    tools_after_edit: list
    context: str
    verified_by: str = ""
    output: str = ""
    project: str = ""

    @property
    def label(self) -> str:
        return LABELS.get(self.verdict, self.verdict)


LABELS = {"backed": "verified", "unbacked": "unverified", "unverifiable": "could not check", "contradicted": "contradicted",
          "weak": "weak", "not_this_turn": "no edit this turn", "out_of_scope": "not audited"}


def _is_edit(e: Event) -> bool:
    if e.kind != "tool" or e.via.startswith("subagent-bg"):
        return False
    if e.name in rules.EDIT_TOOLS:
        return bool(e.text.strip()) and not rules.path_is_doc(e.text)   # an Edit with no path is not evidence of a code edit
    return e.name == "Bash" and rules.bash_is_edit(e.text)


TEST_PASS = re.compile(r"\b(\d+) passed\b|\bOK\b(?! to)|tests? passed|\bPASS(ED)?\b|✓|全部通过|fail(ed|ures)?[: ]+0\b|\b0 failed|\bpass \d+"
                       r"|test result: ok|\b\d+ passing\b|Tests run: \d+, Failures: 0, Errors: 0|Passed!|^ok\s+\S+|All checks passed|No issues found|\b0 errors?\b", re.I | re.M)
TEST_FAIL = re.compile(r"\b[1-9]\d* failed\b|\bFAILED\b|^ERROR:|\bERROR\b(?! 0)|Traceback|AssertionError|\berror\[|errors? occurred|npm ERR|\bFAIL\b(?![: ]+0)|fail(ed|ures)?[: ]+[1-9]"
                       r"|test result: FAILED|\b[1-9]\d* failing\b|Failures: [1-9]|Errors: [1-9]|Failed: [1-9]|^FAIL\s|panic:|build failed|compilation failed|error TS\d+|\[error\]", re.I | re.M)
SUMMARY_LINE = re.compile(r"(\b\d+ (passed|failed|error)s?\b[^\n]*|\bRan \d+ tests?[^\n]*\n?\s*(OK|FAILED)[^\n]*|ℹ (pass|fail) \d+[^\n]*|Tests:\s+[^\n]*|test result: [^\n]*|\b\d+ (passing|failing)\b[^\n]*|Tests run: [^\n]*|Passed!|Failed![^\n]*)", re.I)
IMAGE_READ = re.compile(r"\.(png|jpe?g|gif|webp)$", re.I)
VISUAL_CMD = re.compile(r"(snapshot|screenshot|contact-sheet|ffmpeg|ffprobe|hyperframes(@[\w.]+)? (render|build)|blender )", re.I)


def _last_summary(out: str) -> str:
    """The last pass/fail summary in the output decides; earlier runs in the same command are history."""
    hits = [m.group(0) for m in SUMMARY_LINE.finditer(out)]
    if not hits:
        return out
    # a pytest summary like "2 failed, 17 passed" spans one line: take everything from the last summary start
    tail = out[out.rfind(hits[-1]):]
    return tail[:400]
PUSH_FAIL = re.compile(r"(rejected|fatal:|error:|denied|failed to push)", re.I)


def judge_output(category: str, seg: str, ev: Event, claim_text: str = ""):
    """Decide from the verifying command's own output; fall back to exit status / pipes."""
    out = ev.result or ""
    if re.search(r"running in background|Output is being written to", out, re.I):
        return "unverifiable", "verification was started in the background; its result is off-transcript"
    if category == "fixed" and re.search(r"(node --check|py_compile|python3? -c ['\"]import )", seg):
        return "unverifiable", "only a syntax check ran after the fix"
    if category in ("tests_pass", "checks_pass") or (category == "fixed" and rules.VERIFY["test"].search(seg)):
        summ = _last_summary(out)
        if TEST_FAIL.search(summ) and not TEST_PASS.search(summ):
            return "contradicted", "last test summary shows failures"
        if TEST_FAIL.search(summ) and TEST_PASS.search(summ) and re.search(r"\b[1-9]\d* failed", summ):
            return "contradicted", "last test summary shows failures alongside passes"
        if TEST_PASS.search(summ) or (category == "checks_pass" and not TEST_FAIL.search(out) and not ev.is_error):
            if rules.NARROWED_TEST.search(seg) and category == "tests_pass":
                claimed = re.search(r"(\d+)\s*(个|项)?\s*(测试|用例|tests?)", claim_text or "")
                passed = re.search(r"\b(\d+) passed\b", summ)
                if claimed and passed and claimed.group(1) == passed.group(1):
                    return "backed", f"narrowed run matches the claimed count ({passed.group(1)} passed): {seg[:60]}"
                return "unverifiable", "narrowed test run reported as passing"
            return "backed", f"test output confirms: {seg[:80]}"
        if rules.PIPE_SWALLOW.search(seg) and "pipefail" not in seg:
            return "unverifiable", "test piped through tail/head and output shows no pass/fail line"
        if ev.is_error:
            return "unbacked", "test command errored"
        return "unverifiable", "test ran but output shows no pass/fail line"
    if category == "pushed":
        if PUSH_FAIL.search(out):
            return "contradicted", "push output shows an error"
        return ("unbacked", "push command errored") if ev.is_error else ("backed", f"push confirmed: {seg[:80]}")
    if ev.is_error:
        return "unbacked", f"verification command errored: {seg[:60]}"
    if category in ("build_ok", "rendered") and re.search(r"(Traceback|\berror\b|fatal)", out, re.I) and not re.search(r"0 errors?|no errors?", out, re.I):
        return "contradicted", "verification output contains errors"
    if rules.PIPE_SWALLOW.search(seg) and "pipefail" not in seg and not out.strip():
        return "unverifiable", "piped verification with empty output"
    return "backed", f"verified by: {seg[:80]}"


_BASE_VERIFIED = noncode.SPECS["verified"]


def rebuild_verified_spec() -> None:
    """"verified" accepts any check: its own vocabulary, "checked" tools, and every test/build/render/run command (which the config can extend)."""
    noncode.SPECS["verified"] = noncode.Spec(
        tool=re.compile(_BASE_VERIFIED.tool.pattern + "|" + noncode.SPECS["checked"].tool.pattern, re.I),
        bash=re.compile("|".join([p.pattern for k, p in rules.VERIFY.items() if k in ("test", "build", "render", "run")] + [noncode.SPECS["checked"].bash.pattern]), re.I),
        noun="check")


rebuild_verified_spec()


def audit_turn(turn: Turn, prev: Turn | None = None):
    out = []
    ev = turn.events
    for i, e in enumerate(ev):
        if e.kind != "text":
            continue
        for hit in rules.find_claims(e.text):
            before = ev[:i]
            if hit.category in noncode.SPECS:
                verdict, reason, vb, out_snip = noncode.judge(hit.category, hit.sentence, before, rules.OPAQUE_TOOLS,
                                                              prev.events if prev is not None else None, rules.REMOTE_RUN)
                tools_in_turn = [f"{x.name}: {x.text[:240]}" + (" [ERR]" if x.is_error else "") + (" [subagent]" if x.via else "") for x in before if x.kind == "tool"]
                ctx_start = max(0, e.text.find(hit.sentence) - 150)
                context = e.text[ctx_start: ctx_start + 150 + len(hit.sentence) + 150].replace("\n", " ")
                out.append(Finding(turn.session, turn.index, turn.version, turn.agent, turn.model, e.ts, hit.category, verdict, reason,
                                   hit.sentence[:300], "", tools_in_turn[-8:], context[:600], vb[:200], out_snip.replace("\n", " "), getattr(turn, "project", "")))
                continue
            edit_idx = max((j for j, x in enumerate(before) if _is_edit(x)), default=-1)
            after = [x for x in before[edit_idx + 1:] if x.kind == "tool"] if edit_idx >= 0 else []
            tools_after = [f"{x.name}: {x.text[:240]}" + (" [ERR]" if x.is_error else "") + (" [subagent]" if x.via else "") for x in after]
            last_edit = f"{ev[edit_idx].name}: {ev[edit_idx].text[:400]}" if edit_idx >= 0 else ""
            ctx_start = max(0, e.text.find(hit.sentence) - 150)
            context = e.text[ctx_start: ctx_start + 150 + len(hit.sentence) + 150].replace("\n", " ")
            if not hit.evidence_kinds:
                verdict, reason = "out_of_scope", "fuzzy category not audited in v1"
            elif edit_idx < 0:
                verdict, reason = "not_this_turn", "no code edit in this turn before the claim"
            elif any(x.name in rules.OPAQUE_TOOLS for x in after):
                verdict, reason = "unverifiable", "a subagent/background/terminal tool ran after the last edit"
            elif rules.REMOTE_RUN.search(hit.sentence):
                verdict, reason = "unverifiable", "claim is about a remote or background run; local edits do not invalidate it and its evidence is off-transcript"
            else:
                verifying = [(x, rules.verifying_segments(x.text, hit.evidence_kinds)) for x in after if x.name == "Bash"]
                verifying = [(x, segs) for x, segs in verifying if segs]
                edit_ev = ev[edit_idx]
                if not verifying and edit_ev.name == "Bash":
                    segs = rules.verifying_segments(edit_ev.text, hit.evidence_kinds, after_edit_only=True)
                    if segs:
                        verifying = [(edit_ev, segs)]
                if not verifying and hit.category in ("fixed", "rendered", "checks_pass") and any(
                        (x.name == "Read" and IMAGE_READ.search(x.text)) or (x.name == "Bash" and VISUAL_CMD.search(x.text)) for x in after):
                    verdict, reason = "weak", "judged by looking at a rendered image or snapshot after the edit; not checkable mechanically"
                elif not verifying:
                    verdict, reason = "unbacked", "no verification command after the last edit"
                else:
                    last, segs = verifying[-1]
                    seg = segs[-1].text
                    verdict, reason = judge_output(hit.category, seg, last, hit.sentence)
                    if verdict == "unverifiable":   # e.g. a CI-status read after the real test run: fall back to the latest check that gave a definite result
                        for cand, csegs in reversed(verifying[:-1]):
                            v2, r2 = judge_output(hit.category, csegs[-1].text, cand, hit.sentence)
                            if v2 in ("backed", "contradicted"):
                                last, seg, verdict, reason = cand, csegs[-1].text, v2, r2
                                break
            vb = locals().get("seg", "") if verdict in ("backed", "unverifiable", "contradicted") and edit_idx >= 0 else ""
            out_snip = (locals().get("last").result[:300].replace("\n", " ") if vb and locals().get("last") else "")
            out.append(Finding(turn.session, turn.index, turn.version, turn.agent, turn.model, e.ts, hit.category, verdict, reason,
                               hit.sentence[:300], last_edit, tools_after[-8:], context[:600], vb[:200], out_snip, getattr(turn, "project", "")))
            seg = ""; last = None
    return out


def audit_turns(turns):
    findings = []
    prev = None
    for t in turns:
        findings.extend(audit_turn(t, prev))
        prev = t
    return findings


def summarize(findings):
    from collections import Counter
    c = Counter(f.verdict for f in findings)
    cat = Counter((f.category, f.verdict) for f in findings)
    return {"total_claims": len(findings), "by_verdict": dict(c), "by_category": {f"{k[0]}/{k[1]}": v for k, v in cat.items()}}
