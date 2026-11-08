"""The block goes into a public pull request. What an agent wrote is shown as inert text, and what it wrote about other things stays out."""
import re

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
