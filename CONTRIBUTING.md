# Contributing

Thanks for helping. Most useful contributions are small: one command shape the hooks misjudge, one test runner whose output is read wrong, one false catch from a real session.

## Set up

```bash
git clone https://github.com/kennywu411-dev/honestly && cd honestly
python -m venv .venv && . .venv/bin/activate
pip install -e . pytest
pytest -q
```

No other dependencies: honestly uses the Python standard library only (3.9+), and new code should too.

If you have honestly's guard installed, it will refuse a test run whose result a pipe hides (`pytest | head`, `| grep -c`) in your own agent sessions. Run the suite without such a pipe, or with `set -o pipefail;` in front.

## Where things live

| File | What it decides |
|---|---|
| `src/honestly/claims.py` | which sentences are claims |
| `src/honestly/rules.py` | which segments of a shell command are edits and which are test/build runs |
| `src/honestly/noncode.py` | what backs a claim about anything but code |
| `src/honestly/hooks.py` | the two hooks: `pre` (before a shell command) and `stop` (before the reply is shown) |
| `src/honestly/audit.py` | whether a command's output backs, contradicts or does not back a claim |
| `src/honestly/verdicts.py` | what each test runner, compiler and linter prints, one table per tool, and how a run is read from it |
| `src/honestly/prnote.py` | `honestly pr-note` |
| `src/honestly/report.py`, `support.py`, `config.py` | reports and cards; `doctor`, `feedback`, `rule`; settings |
| `src/honestly/claude_code.py`, `codex.py`, `agents.py` | transcript parsers for each assistant |

`tests/e2e/` runs the real assistants against a stand-in model (no key, macOS, not part of `pytest`). Run it when a parser or a hook contract changes: see its README.

## Fixing a misjudged case

1. Write the case as a test first. Pre-hook cases call `hooks.pre_hook({"tool_name": "Bash", "tool_input": {"command": cmd}})`; output cases call `audit.judge_output`. The `tests/test_v06*.py` files are short examples.
2. Add the opposite case too: a command or output that must stay allowed. Most regressions are false catches, not misses.
3. Make the smallest change in the rule that fixes it, and keep the comment on the line saying which real command it is for. A test runner read wrong: run it for real, add the output under `tests/fixtures/runner_outputs/<runner>/` as `<case>.txt` with a `<case>.json` (command, exit code, expected verdict), and fix its table in `verdicts.py`. `python tests/confusion.py tests/fixtures/runner_outputs` prints how each verdict compares.
4. Use a temporary `HOME` so the hooks' files stay out of your own. `pytest -q` must pass on your machine; CI runs Linux, macOS and Windows on Python 3.9 to 3.13.

Changing what holds or a default takes a minor release; see the version policy in [docs/reference.md](docs/reference.md). `tests/test_must_catch.py` must keep passing, and a fix must not make a false claim easier to pass.

## Reporting instead

A false catch or a missed claim from a real session is just as useful as a patch. `honestly feedback` prints an issue-ready report with your home path, tokens and e-mail addresses redacted; the issue templates say what else helps.

Issues labelled `good first issue` are scoped to one rule and one test file.
