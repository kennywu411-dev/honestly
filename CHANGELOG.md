# Changelog

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

- Renamed from `sober-cli` to `honestly`. Guard-first positioning; `honestly catches`; 21 fixes from an independent review (Codex CLI tool names and exit codes, Windows paths and encoding, apostrophes, headings and tables, read-only pipelines).

## 0.2.x (2026-10-27 – 28)

- Weak-evidence tier, recall labelling, `--since`, per-project tables, Windows CI, share card; false flags found in other users' logs fixed ("fixed bed reactor", UTF-8 on Windows).

## 0.1.0 (2026-10-27)

- First release as `sober-cli`: audit of Claude Code and Codex transcripts, Stop and PreToolUse hooks for Claude Code.
