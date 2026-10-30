from honestly.audit import Finding
from honestly.report import text_report, svg_card, colorize, want_color

def _f(verdict, cat="tests_pass", agent="claude-code", model="m"):
    return Finding("s", 0, "1.0", agent, model, "2026", cat, verdict, "r", "claim", "Edit: x.py", [], "ctx")

def test_report_and_card():
    fs = [_f("backed")] * 8 + [_f("unbacked")] * 2 + [_f("unverifiable")]
    txt = text_report(fs, 3, 0)
    assert "80.0%" in txt and "unverified" in txt
    svg = svg_card(fs, 3)
    assert svg.startswith("<svg") and ">80<tspan" in svg and "%</tspan>" in svg


def test_empty_report_distinguishes_no_logs_from_no_claims():
    assert "No session logs found" in text_report([], 0, 0)
    out = text_report([], 5, 0)
    assert "Scanned 5 session(s)" in out and "No session logs" not in out


def test_colorize_keeps_layout_and_is_off_for_pipes(monkeypatch):
    import io, re
    fs = [_f("backed")] * 8 + [_f("unbacked")] * 2 + [_f("unverifiable")]
    txt = text_report(fs, 3, 0)
    col = colorize(txt)
    assert re.sub(r"\x1b\[[0-9;]*m", "", col) == txt          # colour never changes the text
    assert "\x1b[32m" in col and "\x1b[31m" in col
    assert not want_color(io.StringIO())                        # a pipe or file gets plain text
