# Reference

Versions, what is stored, exit codes, categories, settings and output formats. 中文版：[reference.zh-CN.md](reference.zh-CN.md).

## Versions and deprecation

Versions are `MAJOR.MINOR.PATCH`. Until 1.0, MINOR does the job of MAJOR.

| Release | May contain | May not contain |
|---|---|---|
| PATCH | A fix for one false hold or one missed claim; wrong text; a crash | Switching a category off; changing what a strictness level holds; changing a default, an exit code, a flag or an output field |
| MINOR | Any of those, listed first in the changelog under **Behaviour changes** | Dropping something without the notice below |

**A release must not let more false claims through by default.** `tests/test_must_catch.py` lists the lies that must be caught, and it has to pass. Taking a case off that list is a decision the changelog states and explains, in a MINOR release.

**When a release turns out wrong,** it is yanked from PyPI, the next PATCH restores the earlier behaviour, and the changelog names the version to avoid. 0.7.3 and 0.7.4 are why this rule exists: 0.7.3 stopped holding claims about anything but code in a patch release, and 0.7.4 undid it a few hours later.

**Deprecation.** A command, flag, setting or output field that is going away keeps working for at least one MINOR release, prints a warning on stderr (never into JSON on stdout), and is listed in the changelog under **Deprecated**. A Python version is dropped only in a MINOR release, after one MINOR release of notice.

## Supported versions

| What | Supported |
|---|---|
| honestly | The latest release on PyPI. Fixes go there, not into older releases |
| Python | 3.9 to 3.13 |
| Systems | Linux, macOS and Windows: the suite runs on all three in CI |

| Assistant | Hooks | What backs that |
|---|---|---|
| Claude Code | Supported | Real sessions |
| Codex | Supported | A real run on Codex CLI 0.163 |
| Gemini CLI | Experimental | The real CLI (0.67) with its model API replaced by a local stand-in; no real model session yet |
| Cursor | Experimental | Written from the vendor's documentation and tested against the documented payloads; never run on a real machine |

Security reports: see [SECURITY.md](../SECURITY.md).

## What is stored, and how to remove it

Everything is under `~/.honestly`, private to your account (folder 0700, files 0600; on Windows, your user profile's own permissions protect it). Nothing here is sent anywhere. The hooks never use the network. `honestly catches` and `honestly doctor` ask pypi.org at most once a day (every 6 hours while that fails) whether a newer release exists; that request sends nothing about your work. `HONESTLY_NO_UPDATE_CHECK=1` turns it off. There is no telemetry.

| File | What it holds |
|---|---|
| `~/.honestly/catches.jsonl` | One line per catch: time, assistant, model, project path, the first 80 characters of your prompt, the claim, the reason, the command, the message, the last tools. Tokens, home paths and e-mail addresses are scrubbed first; that is pattern matching and cannot catch everything, so treat it as private. Rotates at 4 MB |
| `~/.honestly/cache/` | Findings per session, with quotes from replies and command output, scrubbed the same way. Entries unused for 90 days are removed; `honestly audit --clear-cache` or `honestly purge` empties it |
| `~/.honestly/hook-errors.log` | Internal errors and input the hooks skipped. Rotates at 4 MB |
| `~/.honestly/config.json`, `trusted.json` | Your settings, and the project files you trusted |
| `~/.honestly/notices.json` | Which one-line notices you have already seen |
| `~/.honestly/notify`, `notify.last` | Notifications on; the time of the last one |
| `~/.honestly/update-check.json` | The time of the last PyPI check and the version it found |
| `~/.honestly/honestly-card.*`, `honestly-catches.*` | Cards you asked for |
| `<settings file>.bak-honestly-<time>` | The assistant's settings file as it was before `guard install` or `uninstall` changed it |
| `.honestly.json`, and a section in `CLAUDE.md`, `AGENTS.md`, `GEMINI.md` or `.cursor/rules/honestly.mdc` | Only in a project where you ran `--project` or `honestly rule install` |

To remove everything:

```bash
honestly guard uninstall --agent all     # takes honestly's entries out of each assistant's settings
honestly rule uninstall                  # in each project where you installed the rule (--agent for the others)
honestly purge --all                     # the whole of ~/.honestly; run it in your own terminal
pip uninstall honestly
```

The plugin is removed from inside Claude Code. `honestly purge` alone deletes what was recorded and keeps your settings; `--dry-run` lists it first. Purging needs your own terminal, because the record of what the guard caught is not an agent's to erase.

## Exit codes

Every command also exits 130 when interrupted, and 141 when whatever was reading its output closed it (`honestly audit | head`).

| Command | 0 | 1 | 2 |
|---|---|---|---|
| `honestly hook stop`, `hook pre` | Always. The decision is in the JSON on stdout, and an internal error must not stop the assistant | | |
| `pr-note --check` | A test passed after the last edit, or no agent edited code in the window | Anything else (see below), or an error | Bad arguments |
| `pr-note` | The note was written | Not a repository, a bad `--base` or `--since`, no `gh`, no pull request | Bad arguments |
| `doctor` | No problem | At least one problem | Bad arguments |
| `audit`, `share` | Report written, including an empty one | A file could not be written | Bad `--since` or arguments |
| `explain`, `feedback` | Shown, or nothing to show | A number out of range | Bad arguments |
| `catches` | Report written, including an empty one | The log could not be read | `--days` under 1 |
| `purge` | Done, or nothing to remove | Not run from your own terminal | Bad arguments |
| `config`, `ignore` | Done, or already so | The settings file is broken, so nothing was changed | A bad value or category |
| `guard` | Done, or already so | The Claude Code settings file cannot be read | Bad arguments |

`pr-note --check` gives no pass with no agent edit because there is then nothing for an agent to have claimed. It does not mean the code was tested. The note says which case it is:

| Headline | Meaning | `--check` |
|---|---|---|
| ✅ Tests ran after the last code edit and passed | A whole-suite run after the last edit passed, and no code file was written since | 0 |
| ℹ️ No code edit by an agent in this window | Nothing to check | 0 |
| ❌ The last test run ... failed | | 1 |
| ❌ A test run ... failed, and no later run covered the same tests | Only the same tool on the same or a wider set of tests clears a failure | 1 |
| ⚠️ Only a narrowed test run ran | `-k`, one file, a deeper folder, `--lf` | 1 |
| ⚠️ No test ran ..., only a build or lint check | | 1 |
| ⚠️ No test or build ran | | 1 |
| ⚠️ A test ran ..., but its output shows no pass/fail line | A pipe hid it, a CI status read, or Cursor, which records no output | 1 |
| ⚠️ The test run ... collected no tests | | 1 |
| ⚠️ Code files were written or removed after the last test | A person, a formatter, `git pull`, a merge or a branch switch. Run the tests again | 1 |
| ⚠️ The last code edit is not in this working tree | The evidence may belong to another branch | 1 |

The note reads transcripts on this machine and the files in this tree. It cannot tell whether a file written after the test holds different content, and it cannot see work done on another machine.

## Categories

`honestly config` always prints the current list. Use these names with `honestly config off` and `on`. What each one needs as proof is in the README table.

| Name | The agent says |
|---|---|
| `tests_pass` | The tests pass |
| `checks_pass` | Lint, type checks or checks pass |
| `build_ok` | The build succeeded, it compiles |
| `rendered` | A render finished |
| `pushed` | It was pushed or submitted |
| `committed` | It was committed or tagged |
| `fixed` | It is fixed |
| `sent` | It was sent, emailed, posted or replied to |
| `deployed` | It was deployed or published, or is live |
| `downloaded` | It was downloaded |
| `saved` | It was saved or exported to a file |
| `scheduled` | A job was scheduled |
| `checked` | It looked something up or checked it |
| `verified` | It verified or tested something end to end |

## Settings

Two JSON files, both optional. `~/.honestly/config.json` applies everywhere. `.honestly.json` applies to one project: the nearest one between the current folder and the repository root, and outside a repository only the current folder's.

| Key | Values | Default | Set with | With both files |
|---|---|---|---|---|
| `strictness` | `strict`, `normal`, `lenient` | `normal` | `honestly config strictness strict` | The stricter wins; the project's may loosen it only once trusted |
| `language` | `auto`, `zh`, `en` | `auto` | `honestly config language zh` | The project's wins |
| `ignore` | Phrases; a sentence containing one is never a claim | none | `honestly ignore "phrase"`, `--remove`, `--list` | Both lists apply, the project's once trusted |
| `verify_commands` | Commands that count as running the tests | none | `honestly config verify "make verify"`, `unverify` | Both lists apply, the project's once trusted |
| `off` | Category names | none | `honestly config off sent,checked`, `on` | Both lists apply, the project's once trusted |

Add `--project` to any of these commands to write the project's file.

**A repository cannot relax the rules by itself.** A project file comes with the code, so its `off`, `ignore`, `verify_commands` and a lower `strictness` are ignored, with one line saying so, until you run `honestly trust` in your own terminal. That records this exact file; if it changes, they are ignored again (`--list`, `--remove`). `honestly doctor` lists what a project file relaxes.

**It does not enforce anything either.** Lists add up, so a person's own `off` and `ignore` still apply in a project, and a project cannot switch a category back on for someone who switched it off.

**`audit`** judges each session with your settings plus that session's own project file, wherever you run it from. A session whose folder is unknown (Cursor) uses your settings alone. **`pr-note`** uses your settings plus the repository's.

A file that is not valid JSON is ignored, and `honestly config` and `honestly doctor` say so. Commands that change settings refuse to touch it.

| Strictness | Holds a reply on | Refuses a command when |
|---|---|---|
| `strict` | An unbacked or failed claim, and a fix judged only from a screenshot | A pipe hides a run's result, including a filter or `head` on a narrowed run |
| `normal` | An unbacked or failed claim | A pipe hides a whole run's result |
| `lenient` | Only a failure the output shows. A command that exits with an error and prints no recognised failure is not held | Never |

**Message language.** With `auto`, Chinese from either side of the conversation makes the message Chinese, and otherwise it is English. A Chinese file name in an English sentence does not count. With nothing to read, as in `doctor` and `catches`, the system language decides: `LC_ALL`, `LC_MESSAGES`, `LANG`, then the macOS or Windows language. Hook messages, `catches` and `doctor` come in both languages, and `rule install` takes `--lang`. `audit`, `explain`, `share`, `feedback`, `pr-note`, `config`, `guard` and the cards are in English.

| Environment variable | Effect |
|---|---|
| `CLAUDE_CONFIG_DIR` | Where Claude Code keeps its settings and logs |
| `HONESTLY_NO_UPDATE_CHECK=1` | No PyPI check. Only the value `1` counts |
| `HONESTLY_NOTIFY=1` | Notifications on, like `honestly guard notify on` |

## Output formats

Formats follow the rules above: a field's meaning changes only in a MINOR release, and a field is removed only after a deprecation. New fields can appear in any release.

`honestly audit --summary-json` prints one object:

| Field | Meaning |
|---|---|
| `schema` | This format's version, now 1 |
| `total_claims` | Every sentence read as a claim, including those that only summarise earlier work |
| `claims_in_scope` | The ones the report counts: `Claims checked` |
| `decided` | Verified, unverified and contradicted |
| `rate` | Verified over decided, 0 to 1, or `null` with nothing decided |
| `by_verdict`, `by_category` | Counts, using the verdict names below |
| `sessions` | Sessions read, or with `--project` or `--since` those with a matching claim |
| `sessions_read` | Sessions read |
| `duplicates_removed_forks` | Findings dropped as copies in forked sessions |

`honestly audit --json FILE` writes one object per claim: `session`, `turn`, `version`, `agent`, `model`, `ts`, `category`, `verdict`, `label`, `reason`, `claim`, `last_edit`, `tools_after_edit`, `context`, `verified_by`, `output`, `project`, `trace`. It quotes replies and commands as they are, so treat it as private.

| `verdict` | `label`, as the report says it |
|---|---|
| `backed` | verified |
| `unbacked` | unverified |
| `contradicted` | contradicted |
| `unverifiable` | could not check |
| `weak` | weak |
| `not_this_turn` | no edit this turn |
| `out_of_scope` | not audited |

`~/.honestly/catches.jsonl` has no version and is not a stable format.
