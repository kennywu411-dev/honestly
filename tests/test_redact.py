"""Everything that leaves the machine or is stored on it goes through `redact`. Every format here leaked at some point.
The tokens are random strings built at run time, so no file in this repository looks like a credential."""
import random
import string
import time

import pytest

from honestly.redact import redact, strip_controls

random.seed(7)
ALNUM = string.ascii_letters + string.digits
HEX = "0123456789abcdef"
UPPER = string.ascii_uppercase + string.digits
LOWER = string.ascii_lowercase + string.digits


def R(n, alphabet=ALNUM):
    return "".join(random.choice(alphabet) for _ in range(n))


def token(prefix, n=36, alphabet=ALNUM):
    return prefix + R(n, alphabet)


SECRETS = {
    "GitHub classic": token("gh" + "p_"),
    "GitHub OAuth": token("gh" + "o_"),
    "GitHub fine-grained": "github" + "_pat_" + R(22) + "_" + R(59),
    "GitHub all lowercase": token("gh" + "p_", 36, LOWER),
    "legacy 40-hex token": R(40, HEX),
    "npm": token("np" + "m_"),
    "PyPI": "py" + "pi-AgEIcHlwaS5vcmc" + R(120),
    "AWS access key id": "AK" + "IA" + R(16, UPPER),
    "AWS temporary key id": "AS" + "IA" + R(16, UPPER),
    "AWS secret, bare": R(16) + "/" + R(7) + "/" + R(16),
    "AWS session token": "FwoGZXIvYXdzE" + R(30) + "/" + R(30) + "+" + R(30),
    "OpenAI": token("s" + "k-", 48),
    "OpenAI project": "s" + "k-proj-" + R(40) + "_" + R(40),
    "Anthropic": "s" + "k-ant-api03-" + R(90) + "-" + R(6) + "AA",
    "Slack bot": "xo" + "xb-" + R(11, string.digits) + "-" + R(12, string.digits) + "-" + R(24),
    "Stripe": "s" + "k_live_" + R(24),
    "Google API key": "AI" + "za" + R(35),
    "JWT": "ey" + "JhbGciOiJIUzI1NiJ9." + "eyJzdWIiOiIxMjM0NTYifQ." + R(43),
    "64-hex secret": R(64, HEX),
    "base32": R(32, "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"),
    "letters only, mixed case": R(40, string.ascii_letters),
    "lowercase and digits": R(36, LOWER),
    "Slack webhook": "https://hooks.slack.com/services/T" + R(8) + "/B" + R(8) + "/" + R(24),
    "credit card": "4242 4242 4242 4242",
}


@pytest.mark.parametrize("name", sorted(SECRETS))
def test_a_bare_secret_does_not_survive(name):
    s = SECRETS[name]
    out = redact(f"before {s} after")
    assert s not in out
    assert s[-10:] not in out, out
    assert "before" in out and "after" in out


@pytest.mark.parametrize("name", ["GitHub classic", "npm", "Slack bot", "JWT", "AWS access key id", "OpenAI"])
@pytest.mark.parametrize("wrap", ["{}.", "({})", "`{}`", "x/{}", "{}-", "'{}'", '"{}",', "{}:", "key {};"])
def test_punctuation_around_a_token_does_not_save_it(name, wrap):
    s = SECRETS[name]
    assert s[-10:] not in redact(wrap.format(s))


@pytest.mark.parametrize("raw,gone", [
    ("AWS_SECRET_ACCESS_KEY=" + R(16) + "/" + R(7) + "/" + R(16), None),
    ("DB_PASSWORD=hunter2", "hunter2"),
    ("DB_PASS=hunter2", "hunter2"),
    ("mysql_pass: hunter2", "hunter2"),
    ("STRIPE_KEY=short-secret-1", "short-secret-1"),
    ('APP_SECRET="two words here"', "two words"),
    ("export API_TOKEN=abc123", "abc123"),
    ('{"password": "hunter2"}', "hunter2"),
    ("curl -H 'Authorization: Bearer abcdef0123456789abcd'", "abcdef0123456789abcd"),
    ("curl -H 'Authorization: Basic dXNlcjpwYXNz'", "dXNlcjpwYXNz"),
    ('curl -H "Authorization: token shorttok"', "shorttok"),
    ("curl -H 'X-Api-Key: shortkey123'", "shortkey123"),
    ("curl -H 'Cookie: session=abcdef012345'", "abcdef012345"),
    ("curl -u alice:hunter2 https://x", "hunter2"),
    ("mysql -uroot -phunter2 db", "hunter2"),
    ("tool --password=hunter2", "hunter2"),
    ("tool --token-value hunter2", "hunter2"),
    ("sshpass -p hunter2 ssh h", "hunter2"),
    ("https://alice:hunter2pw@db.example.com/x", "hunter2pw"),
    ("https://onlytoken@github.com/o/r.git", "onlytoken"),
    ("postgres://u:p@ss@db.example.com/x", "p@ss"),
    ("https://api.example.com/v1?key=abc123short&sig=z9", "abc123short"),
    ("alice.smith+tag@corp.example.com", "alice.smith"),
    ("ssh deploy@10.1.2.3", "deploy"),
    ("https://grafana.internal.corp.example/d/x", "grafana"),
    ("connect to 192.168.1.20 now", "192.168.1.20"),
    ("/Users/bob/secret-client/app.py", "/Users/bob"),
    ("/home/bob/secret-client/app.py", "/home/bob"),
    ("C:\\Users\\Bob\\secret-client\\app.py", "Bob"),
    ("C:/Users/Bob/secret-client/app.py", "Bob"),
    ("C:\\Users\\Bob Smith\\AppData\\x", "Bob Smith"),
    ("C:\\\\Users\\\\Bob\\\\a.py", "Bob"),
    ("c:\\users\\bob\\a.py", "bob"),
])
def test_named_secrets_paths_and_addresses(raw, gone):
    out = redact(raw)
    assert out != raw
    if gone:
        assert gone not in out, out


@pytest.mark.parametrize("raw,gone", [
    ("-----BEGIN RSA PRIVATE KEY-----\n" + R(60) + "+/" + R(2) + "\n" + R(64) + "\n-----END RSA PRIVATE KEY-----", "PRIVATE KEY-----\n"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA" + R(10) + "/" + R(30) + "\n-----END OPENSSH PRIVATE KEY-----", "b3BlbnNzaC1"),
    ("-----BEGIN PRIVATE KEY-----\\n" + R(30) + "/" + R(30) + "\\n-----END PRIVATE KEY-----", "\\n"),
    ("-----BEGIN PRIVATE KEY-----\n" + R(40) + "\ntruncated, no end line", "truncated"),
])
def test_private_key_blocks_go_whole(raw, gone):
    out = redact(raw)
    assert gone not in out, out
    assert raw[40:60] not in out


@pytest.mark.parametrize("home,raw,gone", [
    ("/Users/jose\u0301", "/Users/jos\u00e9/app.py", "jos"),
    ("/Users/\u5f20\u4e09", "/Users/\u5f20\u4e09/\u9879\u76ee/app.py", "\u5f20\u4e09"),
    ("/data/homes/alice", "/data/homes/alice/app.py", "alice"),
])
def test_the_home_directory_in_any_form(monkeypatch, home, raw, gone):
    monkeypatch.setenv("HOME", home)
    out = redact(raw)
    assert gone not in out and out.startswith("~"), out


def test_a_home_that_is_a_prefix_of_another_name_is_not_cut(monkeypatch):
    monkeypatch.setenv("HOME", "/data/al")
    assert redact("/data/alice/x.py") == "/data/alice/x.py"


def test_a_root_home_does_not_rewrite_every_slash(monkeypatch):
    monkeypatch.setenv("HOME", "/")
    assert redact("/etc/hosts") == "/etc/hosts"


@pytest.mark.parametrize("text", [
    "HONESTLY_NO_UPDATE_CHECK",
    "test_a_pattern_stays_fast_on_awkward_output",
    "getUserAuthenticationTokenFromRemoteServer",
    "src/honestly/claude_code.py",
    "tests/test_v072_regression_1234.py",
    "tests/test_must_catch.py::test_a_claim_with_a_long_name",
    "node_modules/@babel/preset-env/lib/index.js",
    "my-long-project-name-goes-right-here",
    "All tests pass: 12 passed in 0.10s",
    "=== 3 failed, 12 passed, 1 warning in 0.12s ===",
    "Author: Kenny",
    "settings.local.json",
    "version 10.1.2 is out",
    "pytest --tb=short -q tests/test_prnote.py",
    "https://github.com/kennywu411-dev/honestly/pull/4",
    "the build took 12345678 ms",
])
def test_ordinary_text_stays_readable(text):
    assert redact(text) == text


@pytest.mark.parametrize("unit", ["a.", "a", "a@", "-a", "a=", "/a", "--", "=", " ", "\n", "token", "://", "-----BEGIN PRIVATE KEY-----", "http://a?", "a-", "1 "])
def test_it_stays_fast_on_awkward_input(unit):
    text = unit * (64000 // len(unit))
    start = time.perf_counter()
    redact(text)
    assert time.perf_counter() - start < 2.0


def test_redaction_is_stable():
    once = redact("password=hunter2 " + SECRETS["GitHub classic"] + " alice@corp.example.com")
    assert redact(once) == once


def test_control_characters_go_but_lines_stay():
    assert strip_controls("a\x1b]0;x\x07b\tc\nd\u202ee\u200bf\x9bg") == "a]0;xb\tc\ndefg"


def test_the_real_home_counts_when_the_variable_says_otherwise(monkeypatch):
    monkeypatch.setenv("HOME", "/c/Users/bob")
    monkeypatch.setattr("os.path.expanduser", lambda p: "/data/homes/bob" if p == "~" else p)
    assert redact("/data/homes/bob/app.py") == "~/app.py"
    assert redact("/c/Users/bob/app.py") == "~/app.py"
