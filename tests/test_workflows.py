"""The release path is part of what users trust. These read the workflow files as text: no YAML library, like everything else here."""
import glob
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS = sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml")))
pytestmark = pytest.mark.skipif(not WORKFLOWS, reason="the sdist does not ship .github")


def _text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _read(name):
    return _text(os.path.join(ROOT, ".github", "workflows", name))


@pytest.mark.parametrize("path", WORKFLOWS, ids=os.path.basename)
def test_every_action_is_pinned_to_a_commit(path):
    uses = re.findall(r"uses:\s*(\S+)(.*)", _text(path))
    assert uses
    for action, rest in uses:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", action), action
        assert re.search(r"#\s*v\d", rest), f"{action} needs a version comment, for Dependabot and for people"


@pytest.mark.parametrize("path", WORKFLOWS, ids=os.path.basename)
def test_every_checkout_drops_its_credentials(path):
    text = _text(path)
    assert text.count("actions/checkout@") == text.count("persist-credentials: false")


@pytest.mark.parametrize("path", WORKFLOWS, ids=os.path.basename)
def test_nothing_is_granted_at_the_top_of_a_workflow(path):
    assert re.search(r"^permissions: \{\}$", _text(path), re.M)


@pytest.mark.parametrize("path", WORKFLOWS, ids=os.path.basename)
def test_no_untrusted_trigger_or_expression_in_a_script(path):
    text = _text(path)
    assert "pull_request_target" not in text and "workflow_run" not in text
    for block in re.findall(r"run:(.*?)(?=\n\s*(?:- |[\w-]+:)|\Z)", text, re.S):
        assert "${{" not in block, block


def test_the_release_publishes_with_a_short_lived_identity():
    text = _read("release.yml")
    assert "gh-action-pypi-publish@" in text and "secrets." not in text and "password" not in text
    build, publish = text.split("\n  publish:")
    assert "id-token" not in build
    assert "id-token: write" in publish and "name: pypi" in publish and "needs: build" in publish
    assert "attestations: true" in publish


def test_the_release_builds_with_pinned_tools_and_a_fixed_time():
    text = _read("release.yml")
    assert "--require-hashes -r .github/release/requirements.txt" in text
    assert "SOURCE_DATE_EPOCH" in text and "--no-isolation" in text
    assert "tomllib" in text and "$TAG" in text    # the tag must match the version in pyproject.toml
    assert "pytest" in text and "twine check --strict" in text


def test_the_pinned_tools_have_hashes():
    lines = _text(os.path.join(ROOT, ".github", "release", "requirements.txt"))
    assert re.search(r"^setuptools==", lines, re.M) and "--hash=sha256:" in lines


def test_dependabot_watches_the_actions_and_the_release_tools():
    text = _text(os.path.join(ROOT, ".github", "dependabot.yml"))
    assert "github-actions" in text and "pip" in text and "/.github/release" in text


def test_security_policy_says_what_is_stored_and_what_is_sent():
    text = _text(os.path.join(ROOT, "SECURITY.md"))
    for word in ("Report a vulnerability", "~/.honestly", "purge", "pypi.org", "on by default", "trust", "Supported versions", "provenance"):
        assert word in text, word


def test_the_release_steps_are_written_down():
    text = _text(os.path.join(ROOT, "docs", "release.md"))
    for word in ("Trusted Publisher", "release.yml", "pypi", "git tag -s"):
        assert word in text, word
