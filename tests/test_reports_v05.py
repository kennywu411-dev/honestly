"""Weekly trend, catches card, project rule."""
import os
from honestly import report, support
from honestly.audit import Finding


def _f(ts, verdict):
    return Finding("s", 1, "", "claude-code", "m", ts, "tests_pass", verdict, "r", "c", "", [], "", "", "", "")


def test_trend_needs_two_weeks_and_reports_direction():
    assert report.trend([_f("2026-10-05T10:00:00", "backed")]) == ""
    fs = [_f("2026-10-05T10:00:00", "backed"), _f("2026-10-06T10:00:00", "unbacked"),
          _f("2026-10-13T10:00:00", "backed"), _f("2026-10-14T10:00:00", "backed"), _f("2026-10-15T10:00:00", "backed")]
    t = report.trend(fs)
    assert "2026-W41" in t and "2026-W42" in t and "50%" in t and "100%" in t and "up 50 points" in t
    assert "By week" in report.text_report(fs, sessions=2, duplicates=0)


def test_catches_card_is_valid_svg_and_counts(tmp_path):
    rows = [{"kind": "pre", "agent": "codex", "message": "piped"},
            {"kind": "stop", "agent": "claude-code", "message": "⚠️ honestly stepped in: x said <done>"}]
    svg = report.catches_card(rows, 7)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>") and "&lt;done&gt;" in svg
    assert ">2<" in svg and "Claude Code 1" in svg and "Codex 1" in svg
    written = report.write_catches_card(rows, 7, str(tmp_path))
    assert written[0].endswith("honestly-catches.svg") and os.path.getsize(written[0]) > 1000
    assert "Nothing stopped yet" in report.catches_card([], 7)


def test_rule_install_status_uninstall(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# mine\n\nkeep this\n")
    assert "added" in support.rule("install", "claude-code", str(tmp_path))
    text = (tmp_path / "CLAUDE.md").read_text()
    assert text.startswith("# mine") and support.RULE_START in text and "pipefail" in text
    assert "already present" in support.rule("install", "claude-code", str(tmp_path))      # idempotent
    assert text == (tmp_path / "CLAUDE.md").read_text()
    assert "present" in support.rule("status", "claude-code", str(tmp_path))
    assert "removed" in support.rule("uninstall", "claude-code", str(tmp_path))
    assert (tmp_path / "CLAUDE.md").read_text() == "# mine\n\nkeep this\n"
    assert "added" in support.rule("install", "cursor", str(tmp_path))
    assert (tmp_path / ".cursor" / "rules" / "honestly.mdc").read_text().startswith("---\ndescription")
    assert "removed" in support.rule("uninstall", "cursor", str(tmp_path)) and not (tmp_path / ".cursor" / "rules" / "honestly.mdc").exists()
