# Security

honestly runs as a hook inside your coding agent, on your machine. It reads the current session's transcript, and what it prints goes back into the model. So a bug here can reach your files, your credentials and your agent. Please treat it that way when you report one.

## Reporting a vulnerability

Use GitHub's **Report a vulnerability** button on the repository's Security tab, not a public issue. You will get a reply within a few days, and a fix or a plan within two weeks for anything that lets honestly run something, leak something, or be turned off from outside. Say whether you want credit.

Worth reporting: making honestly execute something, leaking transcript content, damaging a settings file, steering the agent through a hook message, or letting a repository or a tool's output switch the guard off or forge a passing result.

## Supported versions

Fixes go into the latest release on PyPI. Update with `pip install -U honestly` or `/plugin update honestly`. The version and deprecation policy is in [docs/reference.md](docs/reference.md).

## What it stores

Everything is under `~/.honestly`, which is private to your account (folder 0700, files 0600; on Windows, your user profile's own permissions protect it):

| File | What it holds |
|---|---|
| `catches.jsonl` | one line per catch: the project path, the start of the prompt, the claim, the commands around it |
| `cache/` | what `honestly audit` found in each session, with quotes from replies and command output |
| `hook-errors.log` | internal errors and input the hook could not read |
| `config.json`, `trusted.json` | your settings, and the project files you trusted |
| `notices.json`, `notify`, `notify.last`, `update-check.json` | small state files |

Tokens, home paths, e-mail addresses and similar are scrubbed before anything is written. Scrubbing is pattern matching and cannot catch everything, so treat these files as private. Logs rotate at 4 MB. `honestly purge` deletes what was recorded (`--dry-run` lists it first, `--all` also deletes your settings). `honestly guard uninstall` removes the hooks but leaves this folder.

## What it sends

The hooks never use the network. Two things can:

- **A version check, on by default.** `honestly catches` and `honestly doctor` ask `pypi.org` at most once a day (every 6 hours while that fails) for the latest version number. Nothing about you or your work is in the request. `HONESTLY_NO_UPDATE_CHECK=1` turns it off.
- **`honestly pr-note --gh`**, when you or an agent run it, posts a block to a pull request through the GitHub CLI: the file last edited, the first line of each check and the line it printed, and flagged claims about the code. A sentence about anything else appears only as its kind. Everything goes through the same scrubbing, so read the block before a public repository gets it.

`honestly feedback` and share cards send nothing; you decide where they go. Rendering a card to PNG starts `rsvg-convert` or a headless browser on your machine, with a temporary profile.

## What it trusts

- **A repository is not trusted.** Its `.honestly.json` can only make the rules stricter until you run `honestly trust` in your own terminal, which records that exact file. If the file changes, its relaxing settings are ignored again. Names, paths and sentences from a repository or a reply are treated as data in hook messages.
- **Tool output is not trusted as an instruction.** Output can still be forged by code you run: a test suite can print `12 passed`. honestly reads what a command printed; it does not sandbox it.
- **Your own account is.** honestly is not a sandbox. An agent with shell access can edit `~/.honestly` or its own settings. honestly catches mistakes and false claims, not a determined agent running as you.
- **When a check cannot finish in time**, the hook stops, says so, and logs it. It does not block the assistant, so "not checked" is not "passed".

## Releases

From the release that follows this file, packages are built and published by `.github/workflows/release.yml` with PyPI trusted publishing, with no stored token, and carry provenance you can verify on the package's PyPI page. Earlier releases were uploaded by hand and have no provenance. The steps are in [docs/release.md](docs/release.md).

The Claude Code plugin installs from this repository rather than from PyPI, so it follows what is on the default branch.
