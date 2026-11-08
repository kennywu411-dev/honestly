"""What goes out through `pr-note` and `feedback` is scrubbed on every path, not only the obvious one."""
import os
import urllib.parse

from honestly import hooks, prnote, support

TOKEN = "gh" + "p_" + "Ab1Cd2Ef3Gh4" * 3
KEY_ID = "AK" + "IA" + "ABCD1234EFGH5678"


def _evidence(**kw):
    ev = prnote.Evidence(root="/r", window="since x", cutoff="c", sessions=1, agents=["claude-code"])
    for k, v in kw.items():
        setattr(ev, k, v)
    return ev


def test_the_reason_beside_a_flagged_claim_is_scrubbed():
    reason = f"the send call errored: Bash: curl -X POST -H 'Authorization: Bearer {TOKEN}' https://x"
    block = prnote.render(_evidence(flagged=[("contradicted", "All tests pass.", reason)], claims={"contradicted": 1}), "0")
    assert TOKEN not in block
    assert "the send call errored" in block


def test_every_field_of_a_note_is_scrubbed():
    check = prnote.Check("test", f"pytest -k {TOKEN}", "failed", f"1 failed {KEY_ID}", "2026-01-01T00:00:00Z", after_edit=True)
    ev = _evidence(last_edit=f"src/{TOKEN}.py", last_edit_ts="2026-01-01T00:00:00Z", edited_files=["a"], checks=[check],
                   flagged=[("unverified", f"Fixed with {KEY_ID}.", f"verification command errored: GH_TOKEN={TOKEN} npm run build")],
                   window=f"since {TOKEN}")
    block = prnote.render(ev, "0")
    assert TOKEN not in block and KEY_ID not in block


def _record(tmp_path, monkeypatch, claim="", command="", **kw):
    monkeypatch.setattr(hooks, "catches_path", lambda: str(tmp_path / "c.jsonl"))
    hooks._record("stop" if claim else "pre", {"cwd": "/work/acme-merger"}, None, "held", claim=claim, command=command, **kw)


def _issue_query(text):
    url = text.split("Open a pre-filled issue: ")[1]
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)


def test_the_issue_link_title_is_scrubbed(tmp_path, monkeypatch):
    _record(tmp_path, monkeypatch, claim=f"Pushed with {TOKEN} and {KEY_ID}, all tests pass.")
    out = support.feedback(1, issue_url=True)
    q = _issue_query(out)
    assert TOKEN[:30] not in q["title"][0] and "AKIA" not in q["title"][0]
    assert TOKEN not in out and KEY_ID not in out


def test_the_issue_link_title_is_scrubbed_for_a_refused_command(tmp_path, monkeypatch):
    _record(tmp_path, monkeypatch, command=f"GITHUB_TOKEN={TOKEN} pytest | head")
    assert TOKEN[:30] not in _issue_query(support.feedback(1, issue_url=True))["title"][0]


def test_feedback_keeps_private_names_out_of_the_issue(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "catches_path", lambda: str(tmp_path / "c.jsonl"))
    plain = 'honestly blocked this reply: Claude Code in project acme-merger, answering "the layoff plan", said "x".'
    turn = type("T", (), {"prompt": "the layoff plan", "agent": "claude-code", "model": "", "session": "s", "index": 0, "project": ""})()
    hooks._record("stop", {"cwd": "/work/acme-merger"}, turn, plain, claim="All tests pass.")
    out = support.feedback(1)
    assert "acme-merger" not in out and "layoff" not in out
    assert "All tests pass." in out


def test_redaction_is_the_shared_one():
    from honestly.redact import redact
    assert support._redact is redact
    assert os.path.basename(prnote.__file__) == "prnote.py"
