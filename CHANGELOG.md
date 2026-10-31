# Changelog

## 0.6.0 (2026-10-31)

- **`honestly pr-note`**: the verification evidence behind a branch, as a block for the pull-request description. It reads this repository's local agent transcripts (Claude Code, Codex, Cursor, Gemini CLI) since the branch left its base and writes the last code edit, every test and build that ran after it with the summary line each printed, and the claims that had nothing behind them. `--gh` puts it into the branch's open PR and replaces its own earlier block on the next run; `--check` exits 1 unless a test ran after the last edit and passed; `--since` / `--base` change the window. Suggested by a reader on X.
- Sessions opened in a parent folder count only for the turns that work in the repository: each edit and check is attributed to the directory it ran in (`cd repo && …`, `for d in a b; do cd $d …`), so a command that edits elsewhere and only later `cd`s here is not credited to it. Test results printed by a pre-commit hook count as a test run after the edit. Commands still running are not reported.
- `honestly rule install` now also tells the agent to run `honestly pr-note --gh` after opening or updating a PR. The no-argument overview lists the new command.

## 0.5.5 (2026-10-31)

- A test run that collected nothing (`no tests ran`, `Ran 0 tests`, `running 0 tests`, `[no tests to run]`, `No tests found`, `0 passing`, `Tests run: 0`) no longer backs a "tests pass" claim: the claim is *unverified* and blocked under normal strictness. Suggested by a reader on X.

## 0.5.4 (2026-10-30)

- `doctor` missed an internal hook error when the traceback was longer than the last 600 characters of `hook-errors.log` (long install paths do that) and reported it as a harmless note. The whole last log entry is checked now.
- A test fixture no longer carries a developer's user name.

## 0.5.3 (2026-10-30)

Fixes from a review of 0.5.2 (a code review, a public-surface audit and a fresh-install test on an empty home directory).

- **Windows: desktop notification text was interpolated into a PowerShell command.** A reply sentence could run code when `guard notify on` was set. The text now travels in environment variables; macOS escapes the AppleScript string; Linux passes `--`.
- **Windows: the hook command was written with backslashes**, which the POSIX shell that runs hooks strips, so the guard was installed but never ran. Paths are written with forward slashes; `doctor` now runs the installed hook line through the shell and reports failure.
- Rules: `src/prompts/builder.py`, `proj/tmp/app.py`, `app/reports/views.py` are code again (the doc-path rule is anchored); `#` comments are stripped before splitting commands (an apostrophe in a comment no longer swallows the next command); `patch` is an edit only as the verb; `0 errors` needs a word boundary; "the test passes a mock client" is not a claim; `?` ends a sentence; `until`, `before I`, `make sure`, `ensure` only disqualify what follows them; `pip install pytest` and `pip list | grep pytest` are not test runs; a `go test` output with a `FAIL` line is contradicted even next to `ok` lines.
- PreToolUse: `--log` no longer disarms the pipe check (`pytest --log-cli-level … | tail`); `--collect-only`, `--version`, `--help` are not runs; the message names the actual pipe (`grep`, `wc` …).
- `guard`: odd-shaped `settings.json` (`"hooks": null`, a string where a list is expected) no longer crashes; an unreadable file makes `install`/`uninstall` exit 1 and leaves the file alone; repeated installs say so and write no new backup; `uninstall` with nothing installed says so.
- `doctor`: exits 1 when it lists a problem; `HONESTLY_NO_UPDATE_CHECK=1` is respected (it was not); the PyPI check is named in the output; the hook command line is printed once.
- `share`: the PNG is reported correctly when Chrome exits non-zero on its first run but still writes the file; a stale PNG from an earlier run is removed first.
- `catches` and `doctor` show local time; `config verify` / `off` without a value exit with a usage line instead of writing an empty entry; `rule install --dir` refuses a missing directory; `rule status` shows all four files; `rule install` on a file that already has the section says so; `--version`.
- `feedback` redacts `KEY=value` credentials, `-p`, `--token`, `user:pass@host`, bearer tokens and token-like runs (paths and constant names are kept).
- Stop hook reads only the tail of a background task's `.output` file; input it let through unchecked (non-JSON stdin, a missing or empty transcript) leaves a one-line note in `hook-errors.log`.
- Help text names all four assistants; `pyproject` requires setuptools ≥ 77 for its license metadata and lists Python 3.9–3.13; the CI workflow has read-only permissions.
- Docs: the second labelling pass is described as what it was (a language-model agent given the sheet); the current rule set's flags were labelled once more; precision denominators explained; 130 tests.

## 0.5.2 (2026-10-30)

- New visual identity: cover, hero and demo (English and Chinese) regenerated; share cards use the same palette.
- README images use absolute URLs so the PyPI page renders them; precision and recall study moved to `docs/precision.md`.
- Package description and keywords updated.

## 0.5.1 (2026-10-29)

- A test command quoted as an argument to another program (`codex exec "… pytest | tail"`, `echo '…' > notes`) is no longer treated as a swallowed pipeline; `bash -c "…"` still is.
- Codex guard verified end to end on a real machine (Codex CLI 0.163): PreToolUse and Stop send the same fields as Claude Code.

## 0.5.0 (2026-10-29)

- Configurable rules: `~/.honestly/config.json` and `./.honestly.json` (strictness strict / normal / lenient, ignored phrases, custom verify commands, categories off, message language); `honestly ignore`, `honestly config`.
- `honestly doctor`: install check with two live self-tests (a code claim and a non-code claim that must be blocked), hook error log, PyPI version note.
- `honestly feedback`: a catch as issue-ready text with paths, tokens and e-mails redacted; `--issue` gives a pre-filled link.
- Subagent transcripts (`<session>/subagents/agent-*.jsonl`) merged into the parent turn by timestamp; background Bash output read from the task file; a background subagent's edits do not stale the parent's checks; reading a background task's output no longer makes a claim "could not check" when that subagent was merged.
- Guard for Codex, Cursor and Gemini CLI from the vendors' hook documentation (experimental); Cursor and Gemini CLI transcript parsers; `honestly audit` reads all four assistants.
- `honestly audit`: weekly trend, `--project` filter, `--cursor-root` / `--gemini-root`, per-session cache (`--no-cache` to bypass; a warm run takes well under a second).
- `honestly catches --card`: a 1200×630 share card of what guard stopped; `--lang zh|en`.
- `honestly rule install`: a short "verify before you claim" section for CLAUDE.md, AGENTS.md, GEMINI.md or Cursor rules, in English or Chinese.
- Hooks: a stop message names how many further sentences in the same reply have no evidence; big transcripts (> 8 MB) are read from the end only; any internal error is logged to `~/.honestly/hook-errors.log` and never blocks the assistant.
- Rules: pipes through grep / awk / wc / tee also lose the exit code; sentences whose subject is the user and descriptions of state ("stored locally") are not claims.
- `honestly` with no arguments prints an overview and the guard status. Chinese output for `catches` and `doctor`.
- READMEs rewritten; hero, audit card and cover regenerated. 107 tests.

## 0.4.2 (2026-10-29)

- A script name used only as an argument (`sed -n 1,60p src/eval.py | head`) no longer counts as a test run; sed, awk, diff, jq and similar are never checks.
- Harness tags (`<system-reminder>`, `<task-notification>`) stripped from the conversation preview.
- When the latest check after an edit says nothing about pass/fail (a CI-status read), the latest check that does is used.
- Inline code is kept in claim text, so "saved to `report.csv`" names its file.

## 0.4.1 (2026-10-28)

- Heredoc and script bodies are not evidence of any action; a previous-turn write backs a "saved" claim only when it wrote the named file; "sent to the chat" needs a real send tool. Found by a live demo.

## 0.4.0 (2026-10-28)

- Seven non-code claim types: sent, deployed, downloaded, saved, checked, scheduled, verified, with the whole turn plus the previous turn as the evidence window.
- `honestly guard notify on|off` desktop notifications; plain-language hook messages naming the assistant, model, project and conversation.

## 0.3.0 (2026-10-28)

- Renamed from `sober-cli` to `honestly`. Guard-first positioning; `honestly catches`; 21 fixes from a review by a second agent (Codex CLI tool names and exit codes, Windows paths and encoding, apostrophes, headings and tables, read-only pipelines).

## 0.2.x (2026-10-27 – 28)

- Weak-evidence tier, recall labelling, `--since`, per-project tables, Windows CI, share card; false flags found in other users' logs fixed ("fixed bed reactor", UTF-8 on Windows).

## 0.1.0 (2026-10-27)

- First release as `sober-cli`: audit of Claude Code and Codex transcripts, Stop and PreToolUse hooks for Claude Code.
