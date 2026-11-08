"""Rendering a card must not touch the user's browser profile or keychain, and the test suite must never start a real browser."""
from honestly import report


def _capture(tmp_path, monkeypatch):
    seen = []
    def fake_run(cmd, **kw):
        seen.append(cmd)
        return None
    monkeypatch.setattr(report, "_run", fake_run)
    svg = tmp_path / "c.svg"
    svg.write_text("<svg/>", encoding="utf-8")
    assert report.svg_to_png(str(svg), str(tmp_path / "c.png")) is False
    return [c for c in seen if c[0] != "rsvg-convert"]


def test_a_browser_runs_with_a_mock_keychain_and_its_own_profile(tmp_path, monkeypatch):
    browsers = _capture(tmp_path, monkeypatch)
    assert browsers
    for cmd in browsers:
        assert "--use-mock-keychain" in cmd
        assert any(a.startswith("--user-data-dir=") for a in cmd)


def test_the_temporary_profile_is_removed(tmp_path, monkeypatch):
    import os
    profile = _capture(tmp_path, monkeypatch)[0]
    path = next(a.split("=", 1)[1] for a in profile if a.startswith("--user-data-dir="))
    assert not os.path.exists(path)


def test_the_suite_never_starts_a_browser():
    import subprocess
    assert report._run is not subprocess.run   # conftest replaces it for every test
