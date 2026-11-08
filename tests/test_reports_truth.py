"""Report numbers, checked against fixtures whose answers are known by hand."""
import json
import os
import re
import time

import pytest

from honestly import cli, hooks, report, update
from honestly.audit import Finding

ED = lambda p: ("Edit", {"file_path": p}, "ok")
PASS = ("Bash", "pytest -q", "12 passed in 1s")
LS = ("Bash", "ls", "a")
_id = [0]


def rows(prompt, events, reply, cwd, base, start=0, model="m"):
    out, n = [], [start]

    def ts():
        n[0] += 1
        return f"{base}{n[0]:02d}.000Z"

    out.append({"type": "user", "message": {"role": "user", "content": prompt}, "origin": {"kind": "human"}, "cwd": cwd, "timestamp": ts()})
    for name, inp, res in events:
        _id[0] += 1
        tid = f"t{_id[0]}"
        out.append({"type": "assistant", "message": {"role": "assistant", "model": model, "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp if isinstance(inp, dict) else {"command": inp}}]}, "cwd": cwd, "timestamp": ts()})
        out.append({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": res}]}, "cwd": cwd, "timestamp": ts()})
    out.append({"type": "assistant", "message": {"role": "assistant", "model": model, "content": [{"type": "text", "text": reply}]}, "cwd": cwd, "timestamp": ts()})
    return out


def write(path, rs):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HONESTLY_NO_UPDATE_CHECK", "1")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def audit(capsys, *args):
    cli.main(["audit", "--no-cache", *args])
    return capsys.readouterr().out


def summary(capsys, *args):
    return json.loads(audit(capsys, "--summary-json", *args))


# ------------------------------------------------------------------ de-duplication
def test_a_fork_counts_once_and_says_so(home, capsys):
    rs = rows("go", [ED("/w/a/x.py")], "All tests pass.", "/w/a", "2026-11-01T10:00:")
    write(f"{home}/.claude/projects/-w-a/s.jsonl", rs)
    write(f"{home}/.claude/projects/-w-a/fork.jsonl", rs)
    s = summary(capsys)
    assert s["by_verdict"] == {"unbacked": 1} and s["duplicates_removed_forks"] == 1


def test_two_sessions_in_one_minute_are_not_forks(home, capsys):
    write(f"{home}/.claude/projects/-w-a/1.jsonl", rows("a", [ED("/w/a/x.py")], "All tests pass.", "/w/a", "2026-11-01T10:00:"))
    write(f"{home}/.claude/projects/-w-a/2.jsonl", rows("b", [ED("/w/a/x.py")], "All tests pass.", "/w/a", "2026-11-01T10:00:", start=30))
    s = summary(capsys)
    assert s["by_verdict"] == {"unbacked": 2} and s["duplicates_removed_forks"] == 0


def test_two_sessions_at_the_same_instant_are_not_forks(home, capsys):
    write(f"{home}/.claude/projects/-w-a/1.jsonl", rows("a", [ED("/w/a/x.py")], "All tests pass.", "/w/a", "2026-11-01T10:00:"))
    write(f"{home}/.claude/projects/-w-a/2.jsonl", rows("a", [ED("/w/a/x.py")], "All tests pass.", "/w/a", "2026-11-01T10:00:"))
    assert summary(capsys)["by_verdict"] == {"unbacked": 2}


def test_a_later_verified_turn_is_not_swallowed(home, capsys):
    rs = rows("c", [ED("/w/e/x.py")], "The whole test suite passes.", "/w/e", "2026-11-01T11:00:")
    rs += rows("d", [ED("/w/e/x.py"), PASS], "The whole test suite passes.", "/w/e", "2026-11-01T11:00:", start=10)
    write(f"{home}/.claude/projects/-w-e/s.jsonl", rs)
    assert summary(capsys)["by_verdict"] == {"unbacked": 1, "backed": 1}


def test_two_projects_are_never_merged(home, capsys):
    write(f"{home}/.claude/projects/-w-c/s.jsonl", rows("e", [LS], "Published to npm.", "/w/c", "2026-11-01T12:00:"))
    write(f"{home}/.claude/projects/-w-d/s.jsonl", rows("f", [LS], "Published to npm.", "/w/d", "2026-11-01T12:00:"))
    assert summary(capsys)["by_verdict"] == {"unbacked": 2}


def cursor(home, name, text="All tests pass."):
    write(f"{home}/.cursor/projects/p/agent-transcripts/{name}.jsonl", [
        {"role": "user", "message": {"content": [{"type": "text", "text": "fix"}]}},
        {"role": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "/w/e.py"}}]}},
        {"role": "assistant", "message": {"content": [{"type": "text", "text": text}]}}])
    return f"{home}/.cursor/projects/p/agent-transcripts/{name}.jsonl"


def test_cursor_sessions_with_no_clock_are_never_merged(home, capsys):
    cursor(home, "a"), cursor(home, "b")
    assert summary(capsys, "--agent", "cursor")["by_verdict"] == {"unbacked": 2}


def test_since_places_a_session_with_no_clock_by_its_file(home, capsys):
    old = cursor(home, "old")
    os.utime(old, (time.time() - 40 * 86400,) * 2)
    cursor(home, "new")
    assert summary(capsys, "--agent", "cursor", "--since", "30d")["by_verdict"] == {"unbacked": 1}
    assert summary(capsys, "--agent", "cursor", "--since", "60d")["by_verdict"] == {"unbacked": 2}


# ------------------------------------------------------------------ filters and sessions
@pytest.fixture
def two(home):
    write(f"{home}/.claude/projects/-w-beta/b.jsonl", rows("b", [ED("/w/beta/x.py"), PASS], "All tests pass.", "/w/beta", "2026-11-01T10:00:"))
    write(f"{home}/.claude/projects/-w-alpha/a.jsonl", rows("a", [ED("/w/alpha/x.py")], "All tests pass.", "/w/alpha", "2026-11-01T11:00:"))
    write(f"{home}/.claude/projects/-w-gamma/g.jsonl", rows("g", [], "Hello.", "/w/gamma", "2026-11-01T12:00:"))
    return home


def test_sessions_follow_the_filter(two, capsys):
    out = audit(capsys, "--project", "beta")
    assert "Sessions: 1 of 3 read" in out
    s = summary(capsys, "--project", "beta")
    assert s["sessions"] == 1 and s["sessions_read"] == 3


def test_no_filter_keeps_the_plain_count(two, capsys):
    assert "Sessions: 3 " in audit(capsys)
    assert summary(capsys)["sessions"] == 3


def test_a_filter_that_removes_everything_says_that(two, capsys):
    out = audit(capsys, "--project", "nomatch")
    assert "none contained a checkable claim" not in out and "No claim matches --project nomatch" in out and "3 session" in out


def test_summary_json_carries_what_the_text_shows(two, capsys):
    s = summary(capsys)
    assert s["schema"] == 1 and s["claims_in_scope"] == 2 and s["decided"] == 2 and s["rate"] == 0.5


def test_not_this_turn_is_counted_apart(home, capsys):
    rs = rows("a", [("Bash", "sendmail a@b.c", "ok")], "Here you go.", "/w/a", "2026-11-01T10:00:")
    rs += rows("b", [], "I've emailed the maintainer.", "/w/a", "2026-11-01T10:00:", start=20)   # a recap: the send was an earlier turn's
    write(f"{home}/.claude/projects/-w-a/a.jsonl", rs)
    s = summary(capsys)
    assert s["total_claims"] == 1 and s["claims_in_scope"] == 0


def test_root_flags_are_where_it_looked(home, capsys):
    out = audit(capsys, "--root", str(home / "nowhere"))
    assert str(home / "nowhere") in out


def test_claude_config_dir_moves_the_logs_too(home, capsys, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / "alt"))
    write(f"{home}/alt/projects/-w-a/a.jsonl", rows("a", [ED("/w/a/x.py")], "All tests pass.", "/w/a", "2026-11-01T10:00:"))
    assert summary(capsys)["by_verdict"] == {"unbacked": 1}


def F(verdict, project="/w/a", agent="claude-code", model="m", ts="2026-11-01T10:00:00.000Z", claim="c"):
    return Finding("s", 0, "", agent, model, ts, "tests_pass", verdict, "r", claim, "", [], "", project=project)


# ------------------------------------------------------------------ tables
def test_same_named_projects_stay_apart():
    fs = [F("backed", "/client-a/site")] * 3 + [F("unbacked", "/client-b/site")] * 3
    out = report.text_report(fs, 2, 0)
    assert "client-a/site" in out and "client-b/site" in out and re.search(r"client-a/site\s+100%", out) and re.search(r"client-b/site\s+0%", out)
    assert not re.search(r"^\s+site\s", out, re.M)


def test_a_generic_folder_still_shows_its_parent():
    fs = [F("backed", "/w/shop/src")] * 3 + [F("unbacked", "/w/blog")] * 3
    out = report.text_report(fs, 2, 0)
    assert "shop/src" in out and re.search(r"^\s+blog\s", out, re.M)


def test_wide_characters_keep_the_columns_straight():
    fs = [F("backed", "/w/论文准备")] * 3 + [F("unbacked", "/w/blog")] * 3
    lines = [l for l in report.text_report(fs, 2, 0).splitlines() if "decided)" in l and "%" in l and ("论文" in l or "blog" in l)]
    assert len(lines) == 2
    assert len({report._cells(l[:l.index("%")]) for l in lines}) == 1


def test_a_small_rise_is_flat_and_singulars_read():
    fs = [F("backed", ts="2026-10-05T10:00:00Z")] * 2 + [F("unbacked", ts="2026-10-05T10:00:00Z")] * 1 + [F("backed", ts="2026-10-19T10:00:00Z")] * 2000 + [F("unbacked", ts="2026-10-19T10:00:00Z")] * 999
    assert "flat 0 points" not in report.trend(fs) and "up 0" not in report.trend(fs) and "flat from" in report.trend(fs)
    assert "1 verified / 1 decided claim)" in report.text_report([F("backed")], 1, 0)


def test_the_could_not_check_row_does_not_name_what_is_read():
    out = report.text_report([F("backed"), F("unverifiable")], 1, 0)
    assert "subagents" not in out and "piped exit codes" not in out


def test_an_explain_shows_the_output(home, capsys):
    ev = [ED("/w/a/x.py")] + [("Bash", f"echo s{i}", "o") for i in range(10)] + [("Bash", "pytest -q", "E assert 1 == 2\n2 failed, 10 passed in 1s")]
    write(f"{home}/.claude/projects/-w-a/a.jsonl", rows("a", ev, "All tests pass.", "/w/a", "2026-11-01T10:00:"))
    cli.main(["explain", "1", "--no-cache"])
    out = capsys.readouterr().out
    assert "2 failed, 10 passed" in out and "last 8" in out


@pytest.mark.parametrize("argv", [["explain", "9"], ["explain", "0"], ["feedback", "9"]])
def test_an_out_of_range_pick_is_an_error(home, capsys, argv):
    write(f"{home}/.claude/projects/-w-a/a.jsonl", rows("a", [ED("/w/a/x.py")], "All tests pass.", "/w/a", "2026-11-01T10:00:"))
    hooks._record("stop", {"cwd": "/w/a"}, None, "m", claim="c")
    assert cli.main(argv + (["--no-cache"] if argv[0] == "explain" else [])) == 1


# ------------------------------------------------------------------ the cards
def card_texts(svg):
    return re.findall(r">([^<>]+)</(?:text|tspan)>", svg)


def test_the_card_does_not_call_a_failed_check_nothing():
    svg = report.svg_card([F("backed")] * 7 + [F("unbacked")] * 12 + [F("contradicted")], 3)
    t = " ".join(card_texts(svg))
    assert "unverified or contradicted" in t and "13 times it said" in t and "a failed check" in t
    plain = " ".join(card_texts(report.svg_card([F("backed")] * 7 + [F("unbacked")] * 12, 3)))
    assert "unverified or contradicted" not in plain and "a failed check" not in plain


def test_the_card_bar_stays_inside_its_margins():
    svg = report.svg_card([F("backed")] * 10000 + [F("unbacked")] + [F("unverifiable")], 1)
    rects = [(float(a), float(b)) for a, b in re.findall(r'<rect x="([\d.]+)" y="452" width="([\d.]+)"', svg)]
    assert rects[-1][0] + rects[-1][1] <= 1116.01


def test_one_claim_is_one_claim_on_the_card():
    assert "1 of 1 claim had" in " ".join(card_texts(report.svg_card([F("backed")], 1)))


def catch(kind, msg="m", agent="claude-code"):
    return {"kind": kind, "agent": agent, "message": msg}


def test_refusals_are_not_counted_as_said_done_on_the_card():
    t = " ".join(card_texts(report.catches_card([catch("stop")] * 2 + [catch("pre")] * 3, 7)))
    assert "2 times my coding agent" in t and "5 times my coding agent" not in t and "each one is a claim" not in t


def test_a_card_of_refusals_only_says_no_one_said_done():
    t = " ".join(card_texts(report.catches_card([catch("pre")] * 3, 7)))
    assert "said “done” without" not in t and "3 commands" in t


def test_the_card_says_last_day_and_one_time():
    t = " ".join(card_texts(report.catches_card([catch("stop")], 1)))
    assert "last day" in t and "1 days" not in t and "time stopped" in t and "times stopped" not in t


def test_a_card_meant_for_posting_carries_no_private_text():
    t = " ".join(card_texts(report.catches_card([catch("stop", "⚠️ honestly blocked this reply: Claude Code in project private-client, answering \"secret plan\"")], 7)))
    assert "private-client" not in t and "secret plan" not in t


# ------------------------------------------------------------------ catches
def test_catches_counts_only_held_replies_as_said_done(home):
    for k in ("stop", "stop", "pre", "pre", "pre"):
        hooks._record(k, {"cwd": "/w/a"}, None, "m", claim="c")
    en, zh = hooks.catches_report(7, zh=False), hooks.catches_report(7, zh=True)
    assert "blocked my coding agent 2 times" in en and "refused 3 commands" in en and "5 times" not in en
    assert "2 次" in zh and "拒绝了 3 条" in zh and "5 次未经检查" not in zh


def test_a_refusal_is_logged_under_the_assistant_that_made_it(home):
    hooks.pre_hook({"command": "pytest | head", "cwd": "/w/a", "conversation_id": "c"}, "cursor")
    assert hooks.load_catches()[-1]["agent"] == "cursor"
    assert "Cursor" in hooks.catches_report(7, zh=False).split("By assistant:")[1]


def test_catches_shows_same_named_projects_apart(home):
    hooks._record("stop", {"cwd": "/client-a/site"}, None, "m", claim="c")
    hooks._record("stop", {"cwd": "/client-b/site"}, None, "m", claim="c")
    out = hooks.catches_report(7, zh=False)
    assert "client-a/site" in out and "client-b/site" in out


def test_catches_redacts_what_it_prints(home):
    hooks._record("stop", {"cwd": "/w/a"}, None, "said key sk-abc123def456ghi789jkl012mno ask bob@corp.example.com", claim="c")
    out = hooks.catches_report(7, zh=False)
    assert "sk-abc123" not in out and "bob@corp.example.com" not in out


@pytest.mark.parametrize("n", ["0", "-1", "x"])
def test_days_must_be_a_positive_number(home, n, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["catches", "--days", n])
    assert e.value.code == 2


def test_the_window_reads_for_one_day(home):
    hooks._record("stop", {"cwd": "/w/a"}, None, "m", claim="c")
    out = hooks.catches_report(1, zh=False)
    assert "last day" in out and "last 1 days" not in out


def test_the_update_note_follows_lang(home, capsys, monkeypatch):
    monkeypatch.delenv("HONESTLY_NO_UPDATE_CHECK")
    os.makedirs(os.path.dirname(update.cache_path()), exist_ok=True)
    json.dump({"ts": time.time(), "latest": "9.9.9"}, open(update.cache_path(), "w"))
    cli.main(["catches", "--lang", "zh"])
    assert "有新版" in capsys.readouterr().out
    cli.main(["catches", "--lang", "en"])
    assert "A newer honestly" in capsys.readouterr().out


def test_an_update_check_that_fails_is_not_repeated_by_every_command(home, monkeypatch):
    monkeypatch.delenv("HONESTLY_NO_UPDATE_CHECK")
    calls = []

    def boom(timeout=2.0):
        calls.append(1)
        raise OSError("offline")

    monkeypatch.setattr(update, "_fetch_latest", boom)
    for _ in range(3):
        assert update.latest_version() == ""
    assert len(calls) == 1


def test_cards_can_be_read_by_a_screen_reader_and_by_eye():
    for svg in (report.svg_card([F("backed")], 1), report.catches_card([catch("stop")], 7)):
        assert '<title' in svg and '<desc' in svg and 'role="img"' in svg
        assert "#55555b" not in svg   # 2.67:1 on this background, under the 4.5:1 that small text needs
