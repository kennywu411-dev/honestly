# honestly

[![tests](https://github.com/kennywu411-dev/honestly/actions/workflows/tests.yml/badge.svg)](https://github.com/kennywu411-dev/honestly/actions/workflows/tests.yml) [![PyPI](https://img.shields.io/pypi/v/honestly)](https://pypi.org/project/honestly/) ![python](https://img.shields.io/badge/python-3.9%2B-blue) ![deps](https://img.shields.io/badge/dependencies-none-success)

**Coding agents report "tests pass", "fixed", "sent", "deployed" without always doing it. `honestly` checks, at the moment the sentence is written, whether the action behind it actually ran in that turn, and stops the reply when it did not.**

![honestly: your coding agent said "tests pass". Did it run them?](https://raw.githubusercontent.com/kennywu411-dev/honestly/main/assets/cover.png)

## The problem, in one paragraph

An agent edits `login.py`, remembers that the tests passed ten minutes ago, and writes *"Fixed, all 12 tests pass"*. Nothing was run after the edit. The reply looks identical to a true one, so the mistake surfaces later: in CI, on a colleague's machine, in production. The same happens with *"I've emailed the maintainer"*, *"deployed to staging"*, *"saved to report.csv"*, *"I checked the docs"*. `honestly` reads the transcript of the current turn, finds the claim, looks for the matching command or tool call after the last code edit, reads its output, and blocks the claim when there is nothing behind it. Deterministic rules, no model, no API key, nothing leaves your machine.

## Install in one minute

```bash
pip install honestly            # Python 3.9+, standard library only (pipx install honestly / uv tool install honestly also work)
honestly guard install          # two hooks into ~/.claude/settings.json (--dry-run shows them first)
honestly doctor                 # checks the install and runs two live self-tests
```

`doctor` ends like this when everything is in place (`--lang zh` for Chinese; `honestly` on its own prints a short overview):

```
  ok   self-test (code): a fake 'All tests pass.' right after an edit, no test run → blocked
  ok   self-test (non-code): a fake 'I've sent you the report.' with no send tool → blocked
all good: guard is installed and blocking.
```

Other assistants. Codex is verified end to end on a real machine (Codex CLI 0.163: the guard denied a piped `pytest` and named the model and project); Cursor and Gemini CLI follow their vendors' hook docs and stay experimental until a user confirms them (see [What it is not](#what-it-is-not)):

```bash
honestly guard install --agent codex     # ~/.codex/hooks.json     (Codex asks you to approve new hooks once: /hooks)
honestly guard install --agent cursor    # ~/.cursor/hooks.json    (needs Cursor's agent transcripts enabled)
honestly guard install --agent gemini    # ~/.gemini/settings.json
honestly guard status                    # all four at once; `guard uninstall [--agent ...]` removes only honestly's entries
```

## What you see when it catches something

![honestly guard stopping a stale "tests pass" claim](https://raw.githubusercontent.com/kennywu411-dev/honestly/main/assets/demo.gif)

The hook writes one plain sentence into the chat, in the language of the conversation, naming the assistant, the model, the project and the conversation:

```
⚠️ honestly stepped in: Claude Code (claude-opus-5-5) in project docpilot, answering "fix the login bug"
said "Fixed the login bug, all 12 tests pass" but ran no check after editing login.py.
It has been told to run one first.
```

The agent is told to do the thing now and report the real output, or to rewrite the sentence as *changed, not yet verified*. Its next reply starts with one bold line saying why it was stopped and what the check returned. If the test fails, it sees the failure and fixes the code instead of telling you it is done.

A second hook runs before each shell command: a test or build piped through `tail`, `head`, `grep`, `awk`, `wc` or `tee` without `set -o pipefail` returns the last command's exit code, so a failure would look like a pass. The command is refused with the one-line fix. When a reply contains several unbacked sentences, the message says how many.

The hooks are built not to get in the way: a transcript over 8 MB is read from the end only (a 200 MB session costs the same as a small one), and any internal error is written to `~/.honestly/hook-errors.log` and lets the assistant continue; `honestly doctor` shows it.

```bash
honestly catches              # everything guard stopped this week, by project and assistant (--lang zh)
honestly catches --card       # the same as a 1200×630 image you can post
honestly guard notify on      # also show each catch as a desktop notification (macOS, Linux, Windows)
```

Every catch is appended to `~/.honestly/catches.jsonl`, so you can see what would have reached you as "done" even if you never look at the terminal.

## What it catches

Fourteen kinds of claim. For each, `honestly` knows what counts as proof and what the output must say.

| The agent writes | What has to be on the transcript, after the last code edit |
|---|---|
| tests pass, 12 passed, all green | a test runner (pytest, unittest, Jest, Vitest, Mocha, Go, Cargo, Maven, Gradle, .NET, Swift, Flutter…) whose last summary line says passed, not failed |
| lint / type check / checks pass | tsc, ESLint, Ruff, mypy, pyright, Clippy, go vet, golangci-lint, Biome, Prettier --check… with a clean result |
| build ok, compiles | a build or compile command that succeeded |
| rendered, exported the video | ffmpeg, ffprobe, remotion, hyperframes render… |
| pushed, submitted | `git push`, `kaggle … push/submit`, with no rejection in the output |
| committed, tagged | `git commit` / `git tag` after the edit |
| fixed, resolved, works now | a test, check or render after the fix; a generic script run is not proof that a fix works |
| sent, emailed, replied, "sent you the file" | a send/reply/SendUserFile tool, `gh pr comment`, sendmail… |
| deployed, published, is live | vercel, fly, kubectl apply, docker push, firebase deploy, `gh release create`, twine upload… |
| downloaded | curl -o, wget, yt-dlp, git clone, hf_hub_download, brew install… or a listing showing the files |
| saved / exported to *file* | a write of that very file, a redirect or `-o` naming it |
| checked, looked it up, confirmed in the docs | Read, Grep, WebSearch, WebFetch, a browser tool, grep/curl/gh… |
| scheduled | CronCreate, a scheduled-task tool, crontab, launchctl |
| verified, tested end to end, 跑通了 | any run or check; a sentence that names a tool (docker, pytest…) needs that tool |

What it refuses to flag, on purpose: plans ("I'll run the tests"), questions, quoted text, code blocks, headings and tables, sentences whose subject is the user ("you sent me…"), descriptions of state ("the data is stored locally"), bibliography titles ("fixed bed reactor"), and replies that only summarise an earlier turn. Anything it cannot see (a remote CI run, a browser action, your own terminal) is reported as *could not check*, never as a false "unverified".

It also reads what subagents did: a test run inside a `Agent` call counts as evidence for the parent's claim, and the output of a background command is read from its task file. Edits made by a background subagent running alongside the main agent do not make the main agent's checks stale.

## Make it yours

A false catch should cost you one command, not a wait for the next release.

```bash
honestly ignore "fixed bed reactor"      # sentences containing this are never claims (--remove, --list)
honestly config strictness strict        # strict: also block "fixed" judged only from a screenshot
honestly config strictness lenient       # lenient: block only when the check it ran actually failed
honestly config verify "make verify"     # your own command counts as running the tests
honestly config off sent,checked         # switch categories off (config on … switches them back)
honestly config language en              # force the message language (auto: follows the conversation)
honestly config                          # show everything in effect
```

Settings live in `~/.honestly/config.json`. Add `--project` to write `./.honestly.json` instead, which is merged on top for that repository and can be committed so the whole team gets the same rules.

To reduce catches at the source, add a short "verify before you claim" section to the project instructions the agent reads:

```bash
honestly rule install                    # CLAUDE.md; --agent codex → AGENTS.md, gemini → GEMINI.md, cursor → .cursor/rules/; --lang zh
```

When a catch looks wrong, one command turns it into an issue-ready text with paths and tokens redacted:

```bash
honestly feedback                        # the latest catch; `honestly feedback 2` for the one before; --issue adds a pre-filled link
```

## Put the evidence in the pull request

An agent's "all tests pass" in a PR description is its word. `honestly pr-note` replaces it with what the transcript shows: the last code edit on this branch, every test and build that ran after it, the summary line each one printed, and the claims that had nothing behind them.

```bash
gh pr create --fill          # or let the agent open it
honestly pr-note --gh        # adds the block to this branch's PR; run again after more work and it replaces itself
```

What the reviewer sees:

> **✅ Tests ran after the last code edit and passed: `132 passed in 2.60s`**
>
> Last code edit: `src/honestly/prnote.py` at 10-31 10:57 (2 other files edited before it).
>
> | Check after the last edit | Result | Output |
> |---|---|---|
> | `pytest -q` | ✅ passed | `132 passed in 2.60s` |
>
> Agent claims in this work: 12 verified, 0 unverified, 0 contradicted, 1 could not check.

When the agent edited after its last test run, the block says so (`⚠️ No test or build ran after the last code edit`) and lists the claims it could not back. A run that collected no tests, or a test piped through `tail` that printed no summary, is shown as such, never as a pass.

- The window is the work since the branch left its base (`--base`, `--since 2h` to change it). Sessions opened in the repository count whole; a session opened elsewhere counts only for the turns that `cd` into it or edit files in it.
- It reads Claude Code, Codex, Cursor and Gemini CLI transcripts on your machine; nothing is uploaded except the block you put in the PR. Home paths, e-mails and token-like strings are redacted. Without `--gh` it only prints; `--out file.md` writes a file.
- `--check` exits 1 unless a test ran after the last edit and passed: a local pre-push gate.
- `honestly rule install` tells the agent to run `honestly pr-note --gh` itself whenever it opens a PR.

## Audit your history

The same rules run over every past session on the machine and give you a number.

```bash
honestly audit                # Claude Code, Codex, Cursor and Gemini CLI logs, de-duplicated across forked sessions
honestly audit --since 30d    # last 30 days only (also 8w, 3m); --project name limits to one project
honestly explain 3            # the full timeline behind the 3rd flagged claim: the edit, every tool after it, the output
honestly share                # a card in ~/.honestly/ (SVG, plus PNG when Chrome, Edge or rsvg-convert is present)
```

![honestly audit on the author's sessions](https://raw.githubusercontent.com/kennywu411-dev/honestly/main/assets/hero.png)

The report breaks the number down by assistant and model, by project, by week (so you can see whether a new model or a new rule file changed anything), and lists why each *could not check* happened. Those are the author's own numbers with the 0.5.3 rules: 125 sessions, 334 of 352 decided claims verified. On the code claims: 167 verified, 16 flagged, 17 could not check, 10 judged only from a screenshot. On the non-code claims: 167 verified, 2 flagged, 63 could not check. One GitHub issue reports the same pattern from another team's logs: of 357 "tests pass" claims in 150 Claude Code sessions, [80 had no run behind them](https://github.com/anthropics/claude-code/issues/104504) (one team's sessions, not a population estimate, as the issue itself says); a benchmark reports it on ML tasks ([57% of frontier-agent runs take a planted shortcut](https://arxiv.org/abs/2608.30724), and telling the agent not to barely helps).

## How a claim is judged

1. **Scope: one turn.** Everything the agent did between your prompt and its reply, including what its subagents did.
2. **Last code edit.** `Edit`/`Write` tools, `sed -i`, `cat > file`, heredocs that write files. Edits to docs, logs, notes, memory, `.env`, temp dirs or agent state do not count.
3. **Matching check after it.** The table above. A custom `verify_commands` entry counts as a test.
4. **Its output.** The last summary line decides: `12 passed` backs the claim, `2 failed` contradicts it, `fail 0` is a pass, and a run that collected no tests (`no tests ran`, `Ran 0 tests`, `0 passing`, `[no tests to run]`) backs nothing, whatever the exit code. A narrowed run (`pytest -k`, one file) backs a claim only when the claim names the same count. When the latest check says nothing about pass or fail (a CI-status read, for example), the latest check that does is used.
5. **Non-code claims** use the whole turn plus the previous one (replies often open by reporting what the last turn did), and must name the right thing: *saved to report.csv* needs a write of `report.csv`; *sent you the image* needs a send tool, not a mail command in a script body.
6. **Visual fixes.** "Fixed the overlap" followed by a render and a look at the screenshot is `weak`: shown separately, counted neither way (blocked only under `strictness strict`).
7. **Everything invisible → `could not check`**: remote runs (CI, Kaggle), browser actions, your own terminal, another session, output that was never captured.

Forked sessions are de-duplicated so the same turn is counted once. Rule details and every exclusion are in [`src/honestly/rules.py`](https://github.com/kennywu411-dev/honestly/blob/main/src/honestly/rules.py) and [`src/honestly/noncode.py`](https://github.com/kennywu411-dev/honestly/blob/main/src/honestly/noncode.py).

## Precision

Every rule change was followed by a labelling round over every claim the audit flagged. Each flagged claim was labelled twice: once by the author reading the full turn, once by a language-model agent given only the label sheet and no access to the first pass. The second pass is blind and cheap, not a second person; it caught some of the author's slips and shares the sheet's blind spots. Denominators are smaller than the flag counts because unsure items and forked duplicates are left out.

| Round | Flagged `unverified` | Precision, pass 1 (author) | Precision, pass 2 (LLM agent, blind) | What was fixed next |
|---|---|---|---|---|
| 1 | 38 | 18/32 (56%) | 22/32 (69%) | doc/log/memory edits counted as code edits; versioned `hyperframes@x check` missed |
| 2 | 22 | 10/19 (53%) | 11/21 (52%) | variable paths, `.agent/state.json`, heredoc bodies; judge output by the last summary line |
| 6 | 12 | 12/12 | 11/11 (+1 unsure) | quote-aware multi-line splitting; writing heredocs never count as verification |
| non-code | 41 | 0/41 | 5/41 | summaries, previous-turn work and background jobs were being flagged; now structural rules, 0 flags on the same logs |
| 0.5.3 (current rules) | 18 | 14/18 correct, 4 unsure, 0 wrong | not done | the 0.5.3 fixes; one pass only, not blind |

Rounds 3–5, the 0.5.3 pass and the recall study are in [docs/precision.md](https://github.com/kennywu411-dev/honestly/blob/main/docs/precision.md). **Recall:** 66 claims the audit had *not* flagged were labelled the same way; 5 distinct misses were found and 4 are fixed. `honestly` still prefers *could not check* over a wrong flag. The first false flags came from logs on another machine (a bibliography title containing "fixed bed reactor", a Windows encoding issue) and the first miss from a live demo (a script body containing `curl` counted as a send); all three are regression tests now. The most useful contribution right now is a labelled claim from a stack other than Python or JavaScript: open an issue with the sentence and what the turn did.

## What it is not

- **Not a judge of correctness or test adequacy.** "Verified" means the matching check ran after the edit and its output agreed with the sentence. It does not mean the code is right or that the test covers the change.
- **Not a leaderboard.** The per-model table is your sessions only.
- **Not affiliated** with Anthropic, OpenAI, Cursor or Google. Independent, MIT.
- **Guard for Cursor and Gemini CLI is experimental.** Their hooks are implemented from the vendors' documentation and covered by tests against the documented payloads, but have not yet been exercised on a real machine; `honestly guard install --agent … --dry-run` shows exactly what would be written. Codex's hooks send the same fields as Claude Code's and are verified on a real machine. Cursor's hook-visible transcripts keep tool inputs but not tool outputs, so under Cursor a claim can be *unverified* (no check at all) but never *contradicted*.
- **Nothing leaves your machine.** The one network call is `honestly catches` or `honestly doctor` asking PyPI at most once a day whether a newer release exists, to print one line about `pip install -U honestly`; the hooks never go online. `HONESTLY_NO_UPDATE_CHECK=1` turns it off.
- Tested on Linux, macOS and Windows (CI), Python 3.9–3.13, 145 tests. Parsed sessions are cached under `~/.honestly/cache/` (keyed on file, rules and config; `--no-cache` bypasses it). Rules were tuned on one developer's sessions (Python, JS, video tooling, Kaggle) and corrected with logs from two other machines; other stacks are covered by synthetic tests only. Expect a false flag or two: `honestly ignore` silences it on the spot and `honestly feedback` turns it into an issue-ready report. Previously published as `sober-cli`.

## Related work

[groundtruth](https://github.com/vnmoorthy/groundtruth) blocks unbacked "done" claims with keyword matching; [superpowers](https://github.com/obra/superpowers) asks for verification in a skill (prompt-level). `honestly` differs in reading command *output*, covering non-code claims, reading subagent transcripts, scoring your history across agents and models, and refusing to count what it cannot see.

中文说明见 [README.zh-CN.md](https://github.com/kennywu411-dev/honestly/blob/main/README.zh-CN.md)。
