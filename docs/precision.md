# Precision and recall

`honestly` is useful only if its flags are right. This document records how the rules were tuned, what was measured, and what is still unknown. All numbers come from one developer's own session logs unless stated otherwise; nothing here is a benchmark of any model.

## Data

- 87 Claude Code sessions (2,340 turns) for the code-claim rounds; 101 sessions for the non-code round; 125 sessions in the current (0.5.3) report.
- Turns duplicated by forked sessions are counted once.
- The labelling sheets contain excerpts of private sessions and are not published. The audit itself can be re-run on any machine: `honestly audit --json findings.jsonl`.

## Method

Every rule change was followed by a labelling round over every claim the audit flagged as `unverified`. Each flagged claim was labelled twice: a first pass by the author, reading the full turn in the transcript; a second pass by a language-model agent given only the label sheet (the claim, its context, the last edit, the tools after it, the verifying command's output and the audit's reason) and no access to the first pass's labels. The second pass is blind and cheap, not a second person: it caught some of the author's slips (round 1 below) and it shares the sheet's blind spots (round 1 again).

Each pass's precision is reported separately: the flags that pass judged correct, over the flags it could judge. Unsure items and forked duplicates are left out of the denominator, which is why the denominators are smaller than the flag counts. Agreement between the two passes is given after the table.

The rules are tuned for precision over recall. Anything the audit cannot see (a subagent, a background job, the user's own terminal, a remote CI or Kaggle run, a piped command whose summary line was swallowed) is reported as `could not check`, never as `unverified`.

## Code claims (tests pass, checks pass, build ok, rendered, pushed, committed, fixed)

| Round | Flagged | Precision, pass 1 (author) | Precision, pass 2 (LLM agent, blind) | Main fix afterwards |
|---|---|---|---|---|
| 1 | 38 | 18/32 | 22/32 | edits to docs, logs and memory files counted as code edits; versioned `hyperframes@x check` not recognised |
| 2 | 22 | 10/19 | 11/21 | variable paths, `.agent/state.json`, heredoc bodies; verdict from the last summary line; `fail 0` is a pass |
| 3 | 27 | — | 13/23 | heredoc header lost whitespace (regression); semicolons inside quotes split sentences |
| 4–5 | 19 → 13 | 12/13 | — | environment-variable prefixes, LaTeX tools; remote and background runs moved to `could not check` |
| 6 | 12 | 12/12 | 11/11 (+1 unsure) | quote-aware splitting of multi-line commands; file-writing heredocs never count as verification |
| after 6 (0.5.0–0.5.2) | 18 | — | — | evidence for "fixed" narrowed to test, check or render commands; background starts and pure syntax checks moved to `could not check`; not re-labelled at the time |
| 0.5.3 | 18 (16 code, 2 non-code) | 14/18 correct, 4 unsure, 0 wrong | not done | anchored doc-path rule, comment stripping, `patch` as a verb only, `0 errors` boundary, transitive "passes", question marks, Go `FAIL` lines; see CHANGELOG |
| 0.7.0 | 13 | 12/13 | — | one pass, not blind; see the 0.7.2 re-read below |
| 0.7.1, re-read | 15 | — | 1/8 (+7 unsure) | on a sheet that cut commands off; led to the 0.7.2 fixes |
| 0.7.2 (current rules) | 9 | — | 4/8 (+1 unsure) | whole commands in the sheet; see below |

Agreement between the two passes on round 2: `unverified` 18/19, `verified` 33/39, `contradicted` 8/8. On round 6: `unverified` 11/11, `verified` 32/36.

The one lesson worth repeating: in round 1 several correct flags were labelled as false positives because the label sheet truncated commands to 100 characters and hid the `pytest` that ran right after a heredoc. Read the whole command.

The 0.5.3 pass was done once, by the author, from `honestly audit --json` output, after the rule changes in that release; it is weaker than the two-pass rounds above and a blind second pass has not been run on it. The four unsure items: a fix to a scheduled job whose only check was reading the job's log (`grep`, which the rules do not count as verification); two "lint passes" sentences whose command text was cut off in the sheet; and one `contradicted` verdict read from a log file rather than from the check's own output. The fourteen correct flags are the familiar shape: an edit, then "tests pass" / "fixed" / "check passes" with no command after the edit, or with the earlier run now stale.

## The 0.7.2 re-read

The 12/13 for 0.7.0 was one pass, not blind, and it did not hold up.

For 0.7.2 a language-model agent labelled every flag from the last 60 days of the author's sessions, with no other labels and no access to the code or the transcripts. It was asked to mark a flag `correct` when the sentence states the assistant's own result as fact and nothing after the last edit backs it; `wrong` when the sentence is not such a claim, when a run after the edit does back it, or when the edit could not have affected what is claimed; `unsure` when the sheet does not let it tell.

| Rules | Sheet | Flags | Correct | Wrong | Unsure |
|---|---|---|---|---|---|
| 0.7.1 | commands cut at 400 characters, tools at 240 | 15 | 1 | 7 | 7 |
| 0.7.2 | whole commands, the reply around the claim | 9 | 4 | 4 | 1 |

The two rows are different sheets as well as different rules, so the gap between them is not all from the fixes. Reading the fifteen turns in full showed false holds in six of them, and those six are what 0.7.2 changed.

Of the 9 flags that remain:

- Two of the four correct flags are ordinary stale passes (`hyperframes check` passed, then a label moved, then "check passes"), one more is a suite passed before a last edit to a module the tests import, and the last is a staged demo the author asked for.
- Three of the four wrong flags are the same shape as a stale pass, but with a last edit that could not have touched what the sentence claims (a new reporting script, an f-string split in an analysis script). The rules hold these on purpose: telling a harmless edit from a harmful one takes reading the code, and the shape is the one the tool exists to catch.
- The fourth wrong flag is the README's own demo: four assertions run by hand after "you don't have to run pytest", then "all 4 tests pass". The labeller took the assertions as a real run. The rules do not.
- The unsure one says a file was saved; nothing in the turn wrote it and the sheet could not show why.

So the fair summary is 4 of 8 by the labeller's reading, on nine flags from one developer's logs. It is a small sample and the number is not a benchmark.

## 0.7.3 was a mistake

To hold less, 0.7.3 stopped holding claims about anything but code, and treated an earlier pass as good enough for "fixed", and for "tests pass" after a lint run. A check of 24 typical lies then found it held 5. A baseline test run followed by an edit and "Fixed" went through, which is the shape this tool exists for. It also gained almost nothing: the only non-code flag left in 60 days was a saved file that does not exist.

0.7.4 restores all of it. The one part that stays is the pre hook refusing only a whole run whose result is gone, because that loses no catch: a filtered run that shows no result no longer backs "tests pass". `tests/test_must_catch.py` now lists the lies that must be caught, so the same mistake fails the suite.

## Recall

Recall was estimated once, on a sample of 66 claims the audit had *not* flagged (30 `could not check`, 30 `not this turn`, 6 `weak`), labelled in two blind passes.

| Pass | Miss | OK | Unsure |
|---|---|---|---|
| 1 | 2 | 63 | 1 |
| 2 | 3 | 48 | 15 |

Five distinct suspected misses after de-duplication. Four were fixed by rule changes (`evals/` scripts are not tests; the word "background" no longer triggers the remote-run rule; a narrowed test run backs a claim when the counts match; a commit claim needs a commit). The remaining known miss is a progress checklist read as a claim. Set against the 12–18 flags the same rounds produced, five misses put recall somewhere between roughly 55% and 75%, depending on how the 15 unsure items of pass 2 are counted; the sample is small and the interval wide, and the number is not reported anywhere as a headline. `could not check` is not a pass.

## Non-code claims (sent, deployed, downloaded, saved, checked, scheduled, verified)

The first version of these rules flagged 41 claims on 101 sessions. Both labelling passes agreed almost all were wrong (pass 1: 0 correct, 37 wrong, 4 unsure; pass 2: 5 correct, 28 wrong, 8 unsure). The shared sources of error:

- summaries that repeat work from earlier turns or other sessions, in a turn with no tool call at all;
- status reports after a background task, where the turn only read the task's output or listed files;
- work done in the previous turn reported at the start of this one;
- adjectives and product descriptions ("downloaded data", "verified wording", "stored locally by default");
- plans and instructions to the user;
- evidence commands the vocabulary did not know (`grep`, `gh api`, `osascript` as checks; `hf_hub_download`, `brew install` as downloads).

The fix was structural rather than lexical: a turn with no tool calls is `not this turn`; the previous turn's tools count as evidence; a turn that read a background task's output, a subagent, a browser or another session is `could not check`; `checked` is never `contradicted`; a `verified` claim that names a tool needs that tool. After the change the 41 flags went to zero on the same logs, with 134 claims backed, 46 `could not check`, 12 `not this turn`. Two first-person claims in tool-less turns ("I looked at the camera code", "I checked everything") are deliberately let through: a known trade of recall for precision.

## False flags and misses found outside the author's logs

- A log from a Windows machine (Python 3.13, 34 sessions) produced 4 flags, all wrong: the sentence was a bibliography title and "fixed" in "fixed bed reactor" is an adjective. The same output showed mojibake from reading UTF-8 logs with the Windows default encoding. Fixed in 0.2.2: `fixed` counts only as a completion verb; bibliography entries are never claims; all file I/O is UTF-8. On the author's logs the change removed 6 claims, all adjective uses or CSS `position: fixed`, and no real claim.
- A live demo produced a miss: a script body containing `curl` was accepted as evidence for "sent". Fixed in 0.4.1: heredoc and script bodies are not evidence of any action; "sent to the chat" needs a send tool.
- A self-check on the author's logs (0.4.2) found a false guard denial: `sed -n 1,60p src/eval.py | head` was treated as a test run because a test script's name appeared as an argument. A script name now needs a runner in front of it to count.

All three are regression tests.

## Known limits

- The 0.5.3 rule changes were checked by one labelling pass, not two.
- Recall is estimated on one small sample. A larger labelled set, especially from other stacks, is the most useful contribution: run `honestly feedback` on a wrong catch, or open an issue with a claim that should have been caught.
- "Fixed" is inherently vague. When the fix is visual, looking at a screenshot is the real verification and no tool can see the look; such claims are reported as `weak` and kept out of the headline rate.
- The rules were tuned on one developer's sessions (Python, JavaScript, video tooling, Kaggle) and corrected with logs from two other machines. Other stacks are covered by synthetic tests only.
