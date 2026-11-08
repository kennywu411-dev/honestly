# Changelog

## 0.7.4 (2026-11-08)

- **0.7.3 let too many lies through, and this undoes it.** Claims about anything but code hold a reply again. An earlier pass no longer excuses "fixed", or "tests pass" after a lint run. Please do not stay on 0.7.3.
- A filtered or cut-off run that shows no result no longer backs "tests pass" or "fixed": it was *could not check* and now holds the reply. This is what lets the pre hook stay out of the way when a run is only being searched for one thing.
- `tests/test_must_catch.py` lists the lies that must be caught.

## 0.7.3 (2026-11-08)

- **It holds far less.** A hold costs a turn, and every recent reply hold on the author's machine was wrong. Over the same 60 days this goes from 9 flags to 5, of which 4 hold a reply; of 113 recorded command refusals, 0.7.2 would still refuse 6 and this refuses none. `honestly config strictness strict` restores all of the following.
- Claims about anything other than code (sent, deployed, downloaded, saved, checked, scheduled, verified) no longer hold a reply. `honestly audit` still lists them.
- A pass earlier in the turn followed by an edit is `weak` when the sentence says "fixed", or says "tests pass" and a lint, type or build check ran after the edit. With nothing after the edit, "tests pass" still holds, and so do a run that failed and a claim with no run at all.
- The pre hook refuses only a whole run whose result is gone: `pytest | head`, `| grep -c`, `| wc`, `| Out-Null`. Looking for one thing is allowed: `pytest -rs | grep SKIP`, `pytest -k spikes | head`, `pytest tests/test_a.py | head`.
- A failure word from another step of the command no longer contradicts a deploy or download claim: the step itself has to fail (`failed to`, `deploy failed`, `HTTP 422`, `error:` at the start of a line). Closes #23.
- A hook call with no session is not recorded as a catch, so a script trying the hook does not fill `honestly catches`. The doctor's self-test checks the code claim only.

## 0.7.2 (2026-11-08)

- **False holds, found by a blind re-read.** A language-model agent labelled every flag from 60 days of the author's sessions from the sheet alone, and the result was far below the 12/13 the README reported for 0.7.0: 1 correct, 7 wrong, 7 unsure of 15. That sheet cut long commands off, so the turns were then read in full, and six were real false holds. Tests a commit or push hook ran now back a claim when the output has a test count; what the command said itself (`git commit -m "12 passed"`) and a lint hook's `0 errors` do not. A project script's own `[OK]` lines back a checks-pass claim when the run is clean. A clean `--dry-run` backs a sentence about the dry run (`空跑测试通过`). `sleep $((t-now))` backs "scheduled". A test count relayed from another session's report, which no run in the turn printed, and a sentence under an "已提交：" or "Committed:" heading, when a pass and a commit came before the edit, are *could not check*. The same 60 days now give 9 flags instead of 15, and a blind pass with whole commands gives 4 correct, 4 wrong, 1 unsure; see [docs/precision.md](docs/precision.md).
- **A failure no longer reads as a pass.** A summary with a non-zero failure count no longer backs "tests pass" because it also holds a pass marker: `Failed!  - Failed: 2, Passed: 7` (dotnet), `Test Count: 9, Passed: 7, Failed: 2` (NUnit), `Failures: 0, Errors: 2` (Maven), `3 passed, 1 warning, 1 error` (pytest), `2 tests failed out of 9` (CTest), `[  FAILED  ] 2 tests` (GoogleTest), ` 2 fail` (bun), `# fail 2` (TAP), `9 runs, 12 assertions, 2 failures` (minitest), `2 failures, 0 errors` (clojure.test), `5 successes / 2 failures` (busted). RSpec, ExUnit and XCTest failures were *could not check* and now contradict the claim. So do `Test Suites: 1 failed` above `Tests: 5 passed` (Jest and Vitest, a file that failed to load), Playwright's `1 failed` above `5 passed`, and a verdict after the counts: `BUILD FAILURE`, tox's `evaluation failed`, nox's `* tests: failed`, an npm workspace's `Lifecycle script` error, turbo's `Failed: web#test`. Coloured output is read without its escape codes. A log line that only mentions a count ("retried after 2 failures", "errors: 2") does not count.
- One failing target is not cancelled by the next one passing: `dotnet test` on a solution and `cargo test --no-fail-fast`, as `go test` already was, and with `make test` or `npm test` around them too. `9 tests, 0 failures` (ExUnit) and `Executed 9 tests, with 0 failures` (XCTest) back a claim; XCTest's `(0 unexpected)` means the failures were expected, and Swift Testing's `Test run with 3 tests passed` is not voided by an empty XCTest run before it. More runs that tested nothing: `0 tests, 0 failures`, `0 runs, 0 assertions`, dotnet's `No test matches the given testcase filter`. `mvn clean test`, `./gradlew :app:test` and the like are test runs.
- **Windows: Claude Code's PowerShell tool.** It is the main shell there, but the pre hook matched `Bash` only and the transcript parser dropped the tool's command. So the pre hook never ran, and a test run there backed nothing, which held a true "tests pass". If you installed with pip, run `honestly guard install` again; `honestly doctor` warns about an install that predates this. Plugin users get it with the update. Tested with the tool's documented input, not on a Windows machine with Claude Code.
- PowerShell and cmd are read like the POSIX tools they stand for: `Select-Object -First` and `-SkipLast` like `head`, `-Last` like `tail`, `Select-String`, `findstr` and `find` like `grep`, `Measure-Object` like `wc`, `Out-Null` as discarding everything. `$LASTEXITCODE` read after a pipe counts like `${PIPESTATUS[0]}`, `Invoke-Pester` is a test run, `.\gradlew.bat test` and `go.exe test` are read without the extension, and `pwsh -c`, `powershell -Command` and `cmd /c` run what they quote. `Set-Content`, `Add-Content`, `Out-File`, `[IO.File]::WriteAllText` and `"x" > file` of authored text are edits; `pytest | Out-File log.txt` is not. Other cmdlets (`Get-Content pytest.ini | Select-Object -First 5`) are not test runs. A pipe or a PowerShell backtick at the end of a line goes on to the next one, on every shell. Closes #3.
- **Gemini CLI: the stop hook never held anything.** Running the real CLI (0.67) with its model API replaced by a local stand-in showed the recording no longer has the documented shape: a tool's result is a `user` record, which split one prompt into several turns; results are `functionResponse` parts wrapped in `<untrusted_context>`; a failed command's call still says `status: success`. All fixed, with tests in that shape. In the same runs a piped `pytest` is refused and never runs, "All tests pass" with no run or after a failed run is held, and a real pass goes through. No real model session has confirmed it, so it stays experimental. For #5.
- A malformed Gemini record or odd hook input no longer loses the check for the rest of the turn. The new patterns are timed on awkward output in `tests/test_redos.py`.
- CI: `actions/checkout` 7, `actions/setup-python` 7, `github/codeql-action` 4.

## 0.7.1 (2026-11-08)

- A run that tested nothing no longer backs a "tests pass" claim for four more runners: PHPUnit (`No tests executed!`), `dotnet test` (`No test is available in ...`), Deno (`ok | 0 passed | 0 failed`) and RSpec (`0 examples, 0 failures`). An RSpec run such as `5 examples, 0 failures` now backs one; before, it was *could not check*. Deno's `ok | 0 passed` line was also taken for a Go package line, which skipped the zero-test check. Closes #2; thanks to @Sonike for #7, the project's first outside pull request.
- The pre hook's pattern for a piped `{ ...; }` group no longer backtracks exponentially on a long run of redirections such as `9>9>9>...`; a 26-step run took 6 s and each extra step quadrupled it (CodeQL py/redos). `2>&-` is now recognised as a redirection, so `{ pytest; } 2>&- | head` is held like `2>&1 | head`.
- A step written for the reader is not a claim: "跑测试，看到 `12 passed` 就说明环境配好了", "你会看到 12 passed", "练习页会打印 12 passed", "you should see 12 passed", "when you see 12 passed, …", "seeing 12 passed means …". The sentence has to frame the result as something the reader will see (an expectation verb right before it, or "see X" followed by "就说明 / 即可 / means"). The agent's own result is still a claim: "12 passed，环境配好了", "跑了测试，看到 12 passed，说明…", "我跑了测试…", "看到了 12 passed", "pytest 输出 12 passed，就说明…". Replayed over 60 days of the author's sessions, the only two sentences that stop counting are the ones from the held reply.
- A write to a relative path is placed under the `cd` before it: `cd proj/.claude && python3 - <<'EOF' … open('launch.json', 'w')` edits `.claude/launch.json`, tool config rather than code, so it no longer makes a later sentence need a test run. The same holds for scripts that `cd` into a scratch or temp folder and write there. Editor settings under `.vscode/` and `.idea/` are not code, like `.claude/`.
- A held reply names the project, not the tool folder the shell was in (「notes」, not 「.claude」), and names the file a shell edit wrote (`launch.json`), not the folder it `cd`'d into.

## 0.7.0 (2026-11-07)

A pre-release review reproduced every item below before it was fixed; each one is now a regression test (`tests/test_v070.py`, `tests/test_precision.py`).

**The stop check holds far fewer honest replies.** Every claim the 0.6 rules would have flagged in 60 days of the author's sessions (219 sessions, 55 held replies) was read by hand, and each kind of false hold was fixed at the rule level. Replayed with 0.7.0, 12 replies are held. 11 are real unverified claims (tests reported as passing after a later code edit with no rerun, "fixed" with nothing run after the edit, a file reported as saved that was never written, and the README demo); the other one relays an earlier result from another project without naming it. An independent review then tried 40 unverified turns and 50 honest ones against these rules; its cases are part of the tests.
- A progress note written mid-turn ("Fixed. Re-taking the frames.") is backed by a real check or a look at the output that followed it in the same turn. A sentence that was false when written stays false, and a check that passed when the sentence was written is never undone by later work.
- Running the project's own code backs "fixed": a script, `python -m pkg`, a snippet that imports a project module, `node app.js`, `./bin/tool`, `curl localhost`. Reading a file, installing a package, fetching a web page or `make clean` does not. Calling the test functions directly (`python -c "import test_x; ..."`) counts as a narrowed test run: it backs "4 tests pass" when its output says 4 passed.
- An edit in another git repository does not make a test run in this one stale when the sentence names that repository or quotes the number of tests that passed. A command that moves between folders is placed by the `cd` before each step.
- Not code edits: a script that writes only into a temp or scratch directory, `.git/` internals and ignore files, data and state files under `data/`, `runs/`, `results/`, `outputs/`, `logs/`, `live/`. A `>` inside quotes (`echo "name <a@b>"`) is not a redirect; a quoted target (`> "src/config.py"`) still is. A shell heredoc (`bash <<'EOF'`) is read for both edits and checks.
- Not runs: a file name in a `for` loop's word list or in `git add`. A command ending in `>/dev/null` was taken for a dev server and ignored; it is a check again.
- Newly recognised checks: `hyperframes lint`, syntax checks (`ast.parse`, `bash -n`, `php -l`), `python build.py`. `python -c "import json; print(...)"` is no longer taken for an import check.
- Reading results: a check whose output went to a file (`> log`, `&> log`) is judged from the later read of that same file; a test summary decides even when a later command on the same line fails (`pytest && git push`, push rejected); an unrelated command that crashes later does not undo an earlier passing run; a browser preview after the edit is a visual check, like a snapshot; a background task's output read after the edit is *could not check*; a file the turn showed with `ls` backs "saved".
- Not claims: an explanation of a bug ("the tests pass 10 for 10% off"), "Forward Deployed Engineer" and link text, "你已保存的简历", "跑完它会显示写入了几行", a download progress such as "635 GB / 680 GB", "已经发到对话里了" (the text is in the reply), and an explanation of why the previous reply was held. Failures the sentence owns up to ("the same 2 environment failures as main", "the one failure also fails on main", "except one known flaky test") are not a contradiction.
- A reply to a task notification or another session's report usually summarises earlier turns: a save or send it mentions that is not in the turn is *could not check*, not *unverified*. A person's own message that merely starts with a status reminder is still the person's. A file written in the previous turn backs "saved".

**Correctness**
- A failing test run whose output was longer than 3000 characters could back a "tests pass" claim: only the start of the output was kept, and test runners print their summary last. Long output now keeps the start, the end and any summary lines in between.
- A test command split over lines with a trailing backslash (`pytest tests/ \` newline `-q | tail`) slipped past the pipe check.
- **The pre-command check now stays quiet unless a pipe actually keeps the result from the agent.** It only looks at tools that print a pass/fail verdict (test runners, builds, linters) and refuses a pipe that cuts off the summary (`pytest | head`, `sed -n 1,20p`, `awk 'NR<=10'`), discards or counts the output (`grep -q`, `| wc -l` on a test run), filters the summary out (a `grep` whose pattern matches no failure line, `grep -v warning`), cuts off the final verdict of a build that prints it last (`npm run build | head`, `docker build`, `xcodebuild`), or keeps only the last lines of npm workspaces. `pytest | tail`, `go test ./... | tail`, `cargo test | tail` and `make test | tail` (each repeats a failure at the end), `| tee`, `| cat`, a `grep` or `jq` that keeps the failure lines, compiler and lint output piped into `head`, document tools such as `pdftotext`, and project scripts are left alone; the stop check still reads the summary before the agent may say the tests pass. Replayed against the 73 commands the previous rules refused on the author's machine since 2026-10-31, the new rules refuse 3, each one a pipe that really hid the summary; on a set of 250 everyday commands from a review, 9 are refused. A test tool that only appears as an argument or after the pipe is not a run (`docker logs app | grep pytest`, `man pytest`, `git show HEAD:tox.ini`, `gh repo edit --add-topic pytest`, `/path/bin/pip install pytest`, `brew install ruff`, `make run`, `xcodebuild -list`, `cargo test --no-run`). Block messages say how the result was lost, name the pipe that lost it, and suggest a fix that works (`| tail -n 40`, not `pipefail` with `head`, which fails even when the tests pass). More runners are recognised: `npm t`, `cargo t`, `py.test`, `node --test`, `bazel test`, `gotestsum`, `sbt test`, `dart test`, `mvn clean test`, `pnpm --filter web test`, `yarn workspace web test`.
- `pipefail` must actually be turned on before the pipe (`set -o pipefail`, `set -euo pipefail`, `bash -o pipefail -c`, zsh `setopt pipefail`); the word in a comment or an `echo` no longer counts, and `set +o pipefail` turns it off again. Reading `${PIPESTATUS[0]}` is accepted.
- A heredoc fed to a shell (`bash <<'EOF'`) is checked; `<<` inside quotes is not a heredoc.
- More test and lint commands are recognised: `manage.py test`, `rails test`, `artisan test`, `bun run test`, `just test`, `hatch run test`, `pdm test`, `npm run lint` / `typecheck`. `make clean`, `make install` and `make help` are not build checks.
- A run that tested nothing (`12 deselected`, `0 passed`) or that errored without printing a summary backs no "tests pass" claim; `pytest --collect-only` is not a run.
- "Test suite passes" and "the tests are green" are recognised as claims; "tests passed earlier" is not a claim about now, unless the sentence goes on to say "now" or "still". A Go run with an empty package (`[no test files]`) or a Cargo run whose doc-tests report `0 passed` still backs "tests pass". "The new tests pass with the fix and fail on main" is backed by the passing run on the new code; the failing run on the old code does not contradict it. An honest "I did not run the tests, so I can't say they pass" is not a claim. Nor is a sentence that reports what an agent said ("the agent said all tests pass").

**Install and robustness**
- Settings files are written atomically (a temporary file next to the real one, then a rename; symlinked dotfiles are written through) and backups never overwrite each other.
- `honestly guard install` respects `CLAUDE_CONFIG_DIR`.
- The plugin's hooks step aside only for a guard install that still works (a `pip uninstall` leaves a dead entry behind), recognise the old `sober` name, and never crash on an unusual settings file. They call `python3` and fall back to `python` when it is missing (Windows often has only `python`).
- `pr-note --gh` without the GitHub CLI explains what to do instead of printing a traceback.
- `honestly doctor` lists a project `.honestly.json` that relaxes the rules.
- The agent's answer to a held reply is now checked too, together with the edits that came before the block. If it still claims a pass with nothing behind it, the reply is not held a second time (that could loop), but a visible notice says it is unverified. Before, the answer was not looked at.
- Desktop notifications (opt-in) are quieter: only a held reply notifies, never a refused command, and at most one every 5 minutes.

**Language**
- Messages follow the system language: `LC_ALL`, then `LC_MESSAGES`, then `LANG`; with none set (apps started from the macOS Dock or the Windows Start menu), the macOS or Windows UI language. The conversation's language still wins when it is Chinese.
- Clearer block messages: "⚠️ honestly blocked this reply:" / "⚠️ honestly blocked this command:" and "⚠️ honestly 已拦截：" / "已拦截该命令：", with the same formal wording in `catches`, `doctor` and the rules text.

**Project**
- README: a real recorded Claude Code session at the top (English and Chinese), a language switch, plain counts instead of percentages, and a section on sharing real cases; package and plugin descriptions say Cursor and Gemini CLI support is experimental.
- Issue forms for real catches, false catches and missed claims; SECURITY.md with private vulnerability reporting.
- CI runs Python 3.9, 3.10, 3.11, 3.12 and 3.13.
- Fixes a false catch: a `gh` command whose arguments name a test tool was refused as a test run.

## 0.6.3 (2026-11-07)

- Desktop notifications (`honestly guard notify on`) are limited to one every 30 seconds, so a burst of catches no longer stacks up dozens of them.
- Fixes a false catch added in 0.6.2: a `{ ...; } | tail` group written inside a quoted argument (a release note, a commit message) was read as a command that runs. Groups are now looked for outside quotes only.

## 0.6.2 (2026-11-07)

- **Claude Code plugin.** The repository is now also a plugin marketplace: `/plugin install honestly --marketplace kennywu411-dev/honestly` installs the two hooks plus `/honestly:pr-note` and `/honestly:catches`, running honestly from the plugin's own copy with no pip install. When `honestly guard install` has already added the hooks, the plugin's hooks step aside so a reply is not checked twice.
- The pre-command hook now also refuses `pytest |& tail` (a pipe that carries stderr too) and a group piped as a whole, `{ cd app && pytest; } | tail`.
- `pr-note` no longer lists a command as a check because a test tool is named inside its quoted arguments (`gh pr create --title "... pytest ..."`), and shows `HOME=$(mktemp -d) pytest` as `pytest`. Inline code (`python -c "..."`, `bash -c "..."`) still counts. Found by running `pr-note` on this release's own PR.
- `CONTRIBUTING.md`: setup, where each rule lives, and how to turn a misjudged case into a test.

## 0.6.1 (2026-11-07)

- The pre-command hook no longer lets a piped test run through when the command starts with an environment assignment: `CI=1 pytest | tail`, `NODE_ENV=test npm test | tail -20` and `cd app && CI=1 go test ./... | tail` are refused like their unprefixed forms. The leading `VAR=value` words are now removed before the command is classified, as the transcript audit already did. Reported by Matt Abate in #1.

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
