# End-to-end check: the real CLIs, a stand-in model

The unit tests feed honestly the shapes we think the assistants write. This check runs the assistants. Each scenario starts the real Claude Code, Codex CLI or Gemini CLI with honestly's real hooks, a scripted model and a fake `pytest`, and scores what happened against what should have happened. It is how we learned that Gemini CLI's stop hook had never worked while every unit test was green.

It is not part of `pytest`. Run it by hand, or from the `e2e` workflow on GitHub (manual, macOS).

## Run it

macOS only for now: it relies on `sandbox-exec`.

```bash
pip install -e . pexpect pyte
export HONESTLY_E2E_HOME=~/.cache/honestly-e2e     # the default: CLIs, results and recordings go here
tests/e2e/setup.sh                                 # npm-installs the CLIs there
PYTHON=$(which python) tests/e2e/run_all.sh        # about 6 minutes; exit code 1 when a scored scenario fails
cat $HONESTLY_E2E_HOME/results/summary.md          # the matrix
```

One CLI or a few scenarios (prefix match):

```bash
python tests/e2e/run_codex.py 09 12
python tests/e2e/run_claude.py --form plugin 01 04
python tests/e2e/show.py $HONESTLY_E2E_HOME/results/codex/09e-*.json    # what the model and the hooks each received
```

## What it cannot touch

- **No account and no real key.** The model is `standin.py`, on 127.0.0.1, with a dummy key. It keeps no auth value: each run only counts dummy, none or other, and `summary.py` reports anything other than the dummy.
- **No network beyond loopback, and no route to the keychain.** Every CLI runs under `sandbox-exec` (`LOCKED` in `common.py`).
- **A throwaway HOME for every scenario**, under `HONESTLY_E2E_BOX` (default `/private/var/tmp/honestly-e2e`). Not `/tmp`: honestly judges a project there differently, and only scenario 15d means to test that.
- **The keychain, twice over.** A logging stand-in for `security` is first on PATH. `setup.sh` replaces Gemini CLI's native keychain module with a logging stub. The runners stop if macOS's `SecurityAgent` appears.

Never run a card command (`honestly share`, `catches --card`) under a fake HOME from here.

## Scenarios

Each scenario is one row of the `scenarios()` table in `run_claude.py`, `run_codex.py` or `run_gemini.py`: the replies the model gives in order, the fake `pytest`, and `expect`.

| `expect` | Passes when |
|---|---|
| `hold` | the reply was held once, the hold reached the model, and no "still says" notice followed |
| `hold+warn` | held once, then the repeated claim got the notice and was not held again |
| `at-most-1-hold` | however often the model repeats itself, one hold |
| `nohold` | nothing held, nothing refused |
| `refuse` | the command was refused and the test never ran |
| `allow` | nothing refused and nothing held |
| `notice` | not held, and the person was told it could not be checked |
| `info` | recorded, not scored |

The numbers mean the same on every CLI:

| Prefix | Situation |
|---|---|
| 00 | installed as a user would, with no extra flags |
| 01–02 | a claim with no check, or after a failed one |
| 03–05 | a real pass; `pytest \| head` refused; `pytest \| tail` allowed |
| 06 | a non-code claim with nothing behind it |
| 07 | the retry after a hold: honest, repeated, after a run, in a loop |
| 08 | a subagent runs the tests or edits the code |
| 09 | a background or long-running command, read later or not at all |
| 10 | a very long turn, over 8 MB |
| 11 | `--resume`, `--continue`, `--fork-session` |
| 12 | compaction in the middle of a turn |
| 13 | Chinese replies |
| 14 | the hook really runs past its timeout |
| 15 | the rest: big outputs, odd tool shapes, a project under `/tmp`, no transcript |

Beyond the tables: `claude_market.py` (the plugin installed as the README says, and with no Python), `claude_tui.py` and `codex_trust.py` (the real terminal UI in a pty: what the person sees, and Codex's hook review), `claude_sdk_shape.py` (prompts sent as content blocks), `codex_versions.py` (older Codex, needs extra installs), `race_flush.py` (why the stand-in waits before replying), `time_hooks.py` with `gen_transcripts.py` (hook time on 1, 50 and 500 MB).

## Things that will bite

- The stand-in waits 0.6 s before each reply, like a model. With no wait at all Claude Code's stop hook can read a transcript that has not been written yet, and results go wrong. At 50 ms they are right (`race_flush.py`).
- A scripted reply must not repeat itself much: Gemini CLI's own loop detector steps in.
- Claude Code starts subagents in the background by default. A script has to end the turn, then wait for the notification, as `08a` does.
- A new CLI version can change what it writes. That is the point: a failure here after an upgrade is usually the news.

## Keeping fixtures

`make_fixtures.py <recordings>` trims recordings into `tests/fixtures/real/`, which the unit tests read: only the records and fields the parsers use, with every machine path replaced. Look at the diff before committing one.
