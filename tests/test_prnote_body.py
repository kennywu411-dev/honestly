"""The block goes into a public pull request. What an agent wrote is shown as inert text, and what it wrote about other things stays out."""
import json
import os
import re
import subprocess

import pytest

from honestly import prnote

MARKUP = "![x](https://attacker.example/p.png) @octocat <img src=x onerror=alert(1)> </details> <!-- /honestly:pr-note --> [click](http://evil.example) **bold** all tests pass."


def _note(*flagged, window="since x"):
    ev = prnote.Evidence(root="/r", window=window, cutoff="c", sessions=1, agents=["claude-code"], flagged=list(flagged), claims={"unverified": len(flagged)})
    return prnote.render(ev, "0")


def _inline_code_removed(block):
    return re.sub(r"`[^`\n]*`", "", block)


def test_a_claim_cannot_add_markup_or_mention_anyone():
    block = _inline_code_removed(_note(("unverified", MARKUP, "no check", "tests_pass")))
    for bad in ("![x]", "@octocat", "<img", "[click]", "**bold**"):
        assert bad not in block, block
    assert block.count("</details>") == 1


def test_the_reason_is_inert_too():
    block = _inline_code_removed(_note(("contradicted", "All tests pass.", f"the send call errored: {MARKUP}", "tests_pass")))
    for bad in ("![x]", "@octocat", "<img"):
        assert bad not in block


def test_a_claim_cannot_end_the_block_early():
    block = _note(("unverified", MARKUP, "no check", "tests_pass"))
    assert block.count(prnote.END) == 1 and block.rstrip().endswith(prnote.END)
    assert "<!--" not in block.replace(prnote.START, "").replace(prnote.END, "")
    assert prnote.splice(prnote.splice("Human text", block), "NEW\n") == "Human text\n\nNEW\n"


def test_a_pipe_or_backtick_cannot_break_the_formatting():
    block = _note(("unverified", "a|b `c` all tests pass.", "x|y `z`", "tests_pass"))
    line = next(line for line in block.splitlines() if line.startswith("- *unverified*"))
    assert line.count("`") == 4


def test_a_branch_name_cannot_add_markup():
    block = _note(window="since the branch left origin/<b>x</b>@octocat")
    assert "<b>" not in block and "@octocat" not in block
    assert "since the branch left origin/" in block


def test_a_sentence_about_something_else_stays_out():
    block = _note(("unverified", "I've emailed the lawyer about the Acme layoff and my visa problem.", "no send tool", "sent"))
    assert "lawyer" not in block and "Acme" not in block and "visa" not in block
    assert "send" in block.lower()


def test_a_reason_about_something_else_stays_out():
    block = _note(("contradicted", "Deployed the Acme site.", "the deploy call errored: Bash: ssh prod-acme deploy", "deployed"))
    assert "Acme" not in block and "prod-acme" not in block


def test_a_claim_about_this_code_is_still_shown():
    block = _note(("unverified", "All 12 tests pass.", "no verification command after the last edit", "tests_pass"))
    assert "All 12 tests pass." in block and "no verification command after the last edit" in block


def test_a_note_poisoned_by_an_older_version_is_healed_on_the_next_run():
    old = prnote.START + "\nx <!-- /honestly:pr-note --> stale ghp_old\n" + prnote.END + "\n"
    assert prnote.splice("Human text\n\n" + old + "\nafter", "NEW\n") == "Human text\n\nNEW\n\nafter"


def _fake_gh(monkeypatch, body="own", number=3, url="https://github.com/me/repo/pull/3"):
    calls = []
    def run(args, **kw):
        calls.append(args)
        out = json.dumps({"number": number, "body": body, "url": url}) if args[1:3] == ["pr", "view"] else ""
        return subprocess.CompletedProcess(args, 0, out, "")
    monkeypatch.setattr(prnote.subprocess, "run", run)
    return calls


def test_a_url_edits_the_pull_request_it_names(monkeypatch):
    url = "https://github.com/other/repo/pull/7"
    calls = _fake_gh(monkeypatch, body="theirs", number=7, url=url)
    prnote.update_pr("/r", "BLOCK\n", url)
    edit = calls[-1]
    assert edit[1:3] == ["pr", "edit"] and edit[3] == url


def test_no_argument_edits_this_branchs_pull_request_by_its_url(monkeypatch):
    calls = _fake_gh(monkeypatch)
    prnote.update_pr("/r", "BLOCK\n")
    assert calls[-1][3] == "https://github.com/me/repo/pull/3"


@pytest.mark.parametrize("bad", ["--repo=evil/x", "-R", "7; rm x", "https://evil.example/x", "7 8", ""])
def test_anything_else_is_refused(monkeypatch, bad):
    calls = _fake_gh(monkeypatch)
    if bad == "":
        prnote.update_pr("/r", "BLOCK\n", bad)
        return
    with pytest.raises(SystemExit):
        prnote.update_pr("/r", "BLOCK\n", bad)
    assert not calls


@pytest.mark.parametrize("good", ["7", "https://github.com/o/r/pull/7", "https://github.example.com/o/r/pull/7"])
def test_a_number_or_a_pull_request_url_is_accepted(monkeypatch, good):
    calls = _fake_gh(monkeypatch)
    prnote.update_pr("/r", "BLOCK\n", good)
    assert calls[0][3] == good


def test_the_skills_grant_only_the_exact_commands():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("pr-note", "catches"):
        with open(os.path.join(root, "skills", name, "SKILL.md"), encoding="utf-8") as fh:
            grant = next(line for line in fh if line.startswith("allowed-tools:"))
        assert ":*" not in grant, grant
