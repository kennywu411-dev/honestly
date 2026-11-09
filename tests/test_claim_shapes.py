"""Sentences written while generalising the detector, none of them from a labelled corpus. They guard the rules, and a failure here means a rule got narrower.

Left out on purpose: "Read through the code." reads as an order as easily as a report, and a transliterated name (卡罗尔已推送) cannot be told from a noun.
"""
import pytest

from honestly import rules

CLAIMS = """\
* Fixed the crash
**Build**: ok
**Deployed**
**Fixed** the leak.
**Lint**: clean
**Pushed**
**Saved**
**Sent**
**Tested**
**Tests pass**
**Tests**: pass
**lint**：通过
**单测全过**
**已上线**
**已推送到 main**
**已验证**
**构建**：成功
**测试**：全过
*Fixed the bug*
- **Pushed** to origin
- Build: passing
- Committed the hotfix
- Deploy: done
- Deployed the worker
- Fixed the leak
- Lint: clean
- Push: done
- Pushed
- Render: complete
- Saved
- Sent
- Tested
- Tests: passing
- [x] Fixed the crash
- [x] 已部署
- 下载：完成
- 已上线
- 已发布
- 已推送到 dev
- 已提交热修
- 已验证
- 推送：完成
- 部署：完成
0 test failures.
1) Deployed to prod
1.2.3 已发布。
100% passing.
112 of 112 tests passed.
112 passed in 4.1s.
112 passed.
112/112 tests pass.
12 passed, 0 failed, 1 skipped.
12 passed, 3 skipped.
12 tests pass.
12 tests passed, none failed.
12 tests, 0 failures.
12 个测试通过
12 个测试都过了
12 个用例全过
12/12 green.
120 个用例通过
120/120 通过
2 个提交已推送
2 个文件已提交
2. Saved to out.csv
300 passed in 12s.
300 个测试通过
47 个单测全过。
47 个测试全部通过，0 失败。
47 个测试都通过了。
8 个测试全过
8/8 passed.
8/8 通过
96 tests passed.
96 个测试全过
96/96 通过
API deployed.
API 已部署
Added a cron entry.
Added to crontab.
Addressed the review comment.
After looking at the logs I found the race, added a lock and the crash is gone.
Alarm set.
All 10 files are downloaded.
All 12 pass.
All 12 tests still pass.
All 230 tests are passing.
All 300 tests passed.
All 8 tests pass.
All 96 tests pass.
All CI checks are green.
All changes committed.
All checks are green.
All checks passed.
All clear.
All commits are pushed.
All committed.
All done, tests pass.
All files downloaded.
All fixed.
All green.
All pass.
All pushed.
All saved.
All scheduled.
All sorted now.
All sorted.
All specs pass.
All tests are still green.
All tests pass locally.
All tests pass, shall I merge?
All tests passed locally.
All tests still pass.
All tests succeeded.
All the tests pass now.
All three tests pass.
All unit tests pass.
All working now.
All working.
Alright, it's fixed now.
Amended the commit.
Archive downloaded.
Back to normal.
Backup saved to backup.tar.gz.
Backup scheduled.
Both tests pass.
Branch is up on GitHub.
Bug is fixed.
Build and tests are green.
Build complete.
Build finished.
Build green.
Build is OK.
Build is good.
Build is passing.
Build passes and tests are green.
Build still passes.
Build successful.
Build went through.
Build works.
Build: green
Builds fine.
Builds now.
Built OK, want a tag?
Built fine.
CC'd Bob.
CI green.
CI is all green.
CI is green now.
CI is green on the PR.
CI is passing on main.
CI ok
CI passed on the branch.
CI passes now.
CI passes on the PR.
CI went green.
CI 也绿了
CI 全绿了
CI 全过了
CI 已通过
CI 没问题
CI 绿了。
CI 绿灯
CI 过了
CI 过了。
CI 过啦
CI 通过
Can't reproduce it anymore.
Changelog sent.
Changes are committed.
Changes are pushed.
Changes are up.
Changes saved.
Checked `config.py`.
Checked and it's fine.
Checked everything.
Checked in the fix.
Checked it.
Checked the API docs.
Checked the changelog and it's there.
Checked the changelog.
Checked the docs and it's supported.
Checked the file.
Checked the migration.
Checked the schema.
Checked the source.
Checked: no other callers.
Checkout works again.
Checks out.
Clean build.
Cleared the blocker.
Clip rendered.
Cloned it.
Cloned the repo.
Comment posted.
Commented on PR #12.
Commented on the issue.
Commented on the ticket.
Commit created.
Commit is done.
Commit pushed.
Commit succeeded.
Commit's in.
Commits pushed.
Committed 2 files.
Committed all changes.
Committed and pushed to main.
Committed as 7e5c3bf.
Committed as `abc1234`.
Committed everything to main.
Committed it.
Committed locally.
Committed my changes.
Committed on `main`.
Committed the change.
Committed the changes to main.
Committed the fix as abc1234.
Committed the hotfix.
Committed the migration.
Committed this.
Committed to develop.
Committed to feature/x.
Committed to the feature branch.
Committed with message "fix".
Committed, next up is the docs.
Committed, not pushed.
Committed, pushed and deployed.
Compilation succeeded.
Compile is clean.
Compile succeeded.
Compiled OK.
Compiled fine.
Compiled without errors.
Compiles clean.
Compiles fine.
Compiles now.
Completed.
Config saved.
Confirmed OK.
Confirmed in the changelog.
Confirmed in the source.
Confirmed it works.
Confirmed it.
Confirmed the fix.
Confirmed the migration works.
Confirmed working now.
Confirmed: it works.
Conflict resolved.
Corrected the typo.
Crash fixed.
Created `report.md`.
Created a commit.
Created out.csv.
Cron added.
Cron entry added.
Cron is set.
Cron job installed.
Cron job is set up.
Cron job set.
Crontab updated.
Cross-checked the numbers.
Cypress passes.
Dataset is downloaded.
Deadlock fixed.
Deadlock resolved.
Deploy complete.
Deploy done.
Deploy is done.
Deploy went through.
Deploy: done
Deployed and verified.
Deployed the API to Fly.
Deployed the app.
Deployed the fix to prod.
Deployed the fix.
Deployed the latest build.
Deployed the migration.
Deployed the new version.
Deployed the worker.
Deployed to Fly.
Deployed to Vercel.
Deployed to `staging`.
Deployed to prod.
Deployed to production.
Deployed; let me know if anything looks off.
Deployment done.
Deployment finished.
Deployment successful.
Digest scheduled.
Docs are live.
Docs published.
Doesn't crash anymore.
Done with the fix.
Done — all green.
Done!
Done, pushed to main.
Done: tests pass and the branch is pushed.
Double checked.
Double-checked the numbers.
Download done.
Download is complete.
Download succeeded.
Download's done.
Downloaded `weights.bin`.
Downloaded all 12 files.
Downloaded both files.
Downloaded everything.
Downloaded it to data/.
Downloaded the archive.
Downloaded the checkpoint.
Downloaded the dataset.
Downloaded the dump.
Downloaded the file to `data/raw.csv`.
Downloaded the logs.
Downloaded the model to `models/`.
Downloaded the repo.
Downloaded the weights.
Downloaded the zip.
Downloaded to models/.
Dropped a note in Slack.
Dry run passed.
Dry-run passes.
Dug into the code.
Dug through the logs.
Dump downloaded.
E2E tests passed.
ESLint found no problems.
ESLint passes.
Each test passed.
Email went out.
Emailed Bob.
Emailed the report to Bob.
Emailed the team.
Encoded the video.
Errors are gone.
Every test passes.
Everything green.
Everything is fixed.
Everything is passing.
Everything is saved.
Everything is scheduled.
Everything is working now.
Everything passes now.
Everything works now.
Everything's committed.
Everything's done and pushed.
Everything's pushed.
Everything's working.
Exception is gone.
Export complete.
Export finished.
Exported it as PDF.
Exported the chart to `chart.png`.
Exported the data.
Exported the report.
Exported the rows to rows.csv.
Exported the table to table.csv.
Exported the video.
Exported to CSV.
Exported to out.xlsx.
Fetched everything.
Fetched the data.
Fetched the dump.
Fetched the model.
Fetched the weights.
File downloaded.
File written.
Filed a bug.
Final cut rendered.
Finally fixed.
Finished rendering.
Finished the render.
Finished.
Fired off the email.
Fix pushed.
Fixed `auth.py` so the token refreshes.
Fixed a race in the scheduler.
Fixed a typo.
Fixed all of them.
Fixed an off-by-one.
Fixed bad regex.
Fixed both.
Fixed broken import.
Fixed by bumping the timeout.
Fixed everything.
Fixed flaky test.
Fixed in `src/app.py`.
Fixed it now.
Fixed race condition.
Fixed that.
Fixed the bug.
Fixed the crash and deployed to staging.
Fixed the failing CI job.
Fixed the failing test.
Fixed the flaky retry.
Fixed the issue.
Fixed the login redirect loop.
Fixed the memory leak.
Fixed the null pointer in `parse_config`.
Fixed the off-by-one in the pager.
Fixed the pagination bug.
Fixed the regression.
Fixed the timeout.
Fixed them all.
Fixed this by adding a guard.
Fixed this.
Fixed two bugs.
Fixed up the imports.
Fixed, should I also add a test?
Force pushed.
Force-pushed the branch.
Formatting passes.
Forwarded it to Bob.
Full suite green.
Full test suite passes.
Gave it a spin.
Generated `chart.png`.
Generated out.pdf.
Git commit succeeded.
Git push succeeded.
Good news: the crash is fixed.
Good to merge.
Grabbed the model.
Gradle build succeeded.
Green CI.
Green build.
Grepped for it.
Grepped the code.
Had a look.
Hotfix committed.
Hotfix is live.
Hotfix pushed.
I checked it.
I checked the config.
I checked the logs and found nothing.
I checked the logs.
I checked the migration.
I checked the schema.
I checked with `grep`.
I committed it.
I confirmed it in the docs.
I confirmed it in the source.
I deployed it to prod.
I downloaded the dataset.
I emailed the team.
I grepped the repo.
I have fixed the bug.
I left a comment on the issue.
I looked at it.
I looked at the code.
I looked at the logs.
I looked it up.
I looked through the logs.
I patched the leak.
I pushed it.
I pushed to main.
I ran it again and it passes.
I ran it and it works now.
I ran it, it works.
I ran the script and it works.
I read `auth.py`.
I read auth.py.
I read the changelog.
I read the docs and it's supported.
I read the migration.
I read the source.
I read through the changelog.
I reviewed the code.
I reviewed the diff.
I rewrote the parser, updated the fixtures and pushed everything to the feature branch.
I saved it to disk.
I scheduled the job.
I searched for usages.
I searched the repo and found no other callers.
I sent the report.
I sent you the report.
I set a reminder for tomorrow.
I tested it by hand.
I tested the endpoint.
I tested the fix.
I tested the migration on staging.
I tested the upload.
I traced the failure to a stale cache, cleared it and all tests pass now.
I verified it with curl.
I verified it.
I verified the migration.
I verified the output.
I wrote it to `out.csv`.
I've checked.
I've committed everything.
I've fixed the crash.
I've pushed to main.
I've read the code.
I've scheduled a reminder.
I've sent it.
I've sent the invite.
I've verified it.
I've verified the numbers.
I've written the report to `report.md`.
In prod now.
Integration tests passed.
Invite sent.
Invoice sent.
Issue is resolved now.
It builds now.
It builds.
It checks out.
It compiles and runs.
It compiles now.
It compiles without warnings.
It is deployed.
It still compiles.
It works again.
It's all working.
It's been committed.
It's been pushed.
It's deployed to prod.
It's in production.
It's live now.
It's on prod.
It's saved.
It's scheduled for 8am.
It's up and running.
It's up on GitHub.
It's working now.
It's working.
Jest is green.
Jest: 30 passed.
Job is scheduled.
Just fixed it.
Just pushed.
Just sent it.
Landed on main.
Landed the fix.
Landing page is live.
Leak fixed.
Left a comment on the PR.
Lint OK.
Lint and tests pass.
Lint green.
Lint is clean.
Lint is green.
Lint ok.
Lint passes now.
Lint ✅
Lint's clean.
Lint, types and tests are green.
Lint-free.
Lint: OK
Lints clean.
Live at https://example.com/app.
Live now.
Live on staging.
Log saved to run.log.
Logs downloaded.
Looked at auth.py.
Looked at the docs.
Looked at the schema.
Looked into it.
Looked over the migration.
Looked through the code.
Looked up the docs.
Looped in Bob.
Made the commit.
Mail sent.
Mailed it.
Merge conflict resolved.
Message delivered.
Messaged the team.
Migration committed.
Migration deployed.
Migration is live.
Migration plan saved.
Migration pushed.
Migration scheduled for 2am.
Mocha passes.
Model downloaded.
Nailed it.
New version deployed.
No compile errors.
No failing tests.
No lint issues.
No linter warnings.
No longer reproduces.
No more errors.
No more timeouts.
No more warnings.
No mypy errors.
No type errors now.
Notification sent.
Notified Bob.
Notified the reviewer.
Now fixed.
Now live on prod.
Now working.
OK 了
OK, that's fixed.
Okay, fixed.
On the schedule.
Opened a ticket.
Output is at out/a.csv.
Output saved to out.csv.
PR comment posted.
PR 的检查都过了
PR 评论发了
Package published.
Pagination works now.
Passes CI.
Passes all checks.
Passes lint.
Passes mypy.
Passes tests.
Passes type checks.
Patch released.
Patched it.
Patched the bug.
Persisted to disk.
Persisted.
Pinged the team.
Pipeline passed.
Playwright tests pass.
Posted a reply.
Posted a status update.
Posted in Slack.
Posted on the issue.
Posted the changelog.
Posted the comment on the PR.
Posted the summary in Slack.
Posted the update in #general.
Pre-commit passes.
Problem fixed.
Problem is gone.
Problem solved.
Prod is updated.
Published 1.2.3 to PyPI.
Published it.
Published the changelog.
Published the docs.
Published the release.
Published to PyPI.
Published to the registry.
Published v2.
Published.
Pulled down the data.
Pulled it down.
Pulled the Docker image.
Pulled the dataset.
Pulled the dump.
Pulled the weights.
Push complete.
Push succeeded.
Push went through.
Pushed 2 commits.
Pushed and opened a PR.
Pushed everything to GitHub.
Pushed feature/x.
Pushed it up.
Pushed live.
Pushed my branch.
Pushed my changes.
Pushed the branch and opened a PR.
Pushed the commit.
Pushed the commits to main.
Pushed the fix.
Pushed the hotfix.
Pushed the migration.
Pushed the tag.
Pushed to `main`.
Pushed to `origin/main`.
Pushed to dev.
Pushed to develop.
Pushed to feature/x.
Pushed to my branch.
Pushed to origin.
Pushed to origin/main.
Pushed to the `fix/login` branch.
Pushed to the fork.
Pushed to the remote.
Pushed up the branch.
Pushed, you can pull now.
Pushed.
Put it in out/.
Queued it for 8am.
Ran 12 tests in 0.3s, OK.
Ran 40 tests: OK.
Ran the script and it works.
Ran the script, works.
Ran the suite, green.
Ran the tests, all pass.
Re-rendered both versions.
Re-rendered the video.
Redeployed.
Regression fixed.
Regression suite is green.
Released 1.2.3.
Released it.
Released the hotfix.
Released the new version.
Released to prod.
Released.
Reminder added.
Reminder created.
Reminder is set.
Reminder set for 8am.
Render OK.
Render done.
Render is complete.
Render succeeded.
Rendered 3 clips.
Rendered both versions.
Rendered in 1080p.
Rendered it at 4K.
Rendered the final video to out/final.mp4.
Rendered the outro.
Rendered the teaser.
Rendered the trailer.
Rendered, take a look.
Rendering complete.
Rendering finished.
Rendering is done.
Repaired the config.
Replied in the thread.
Replied on the issue.
Replied to Alice.
Replied to Bob on Slack.
Replied to Carol.
Replied to the PR comment.
Replied to the customer.
Replied to the email.
Replied to the reviewer.
Repo cloned.
Report is saved to out.csv.
Report sent.
Resolved the bug.
Resolved the conflict.
Resolved.
Results are in results.csv.
Results saved to results.csv.
Retry logic fixed.
Reviewed the diff.
Reviewed the logs.
Reviewed the migration.
Rolled it out.
Rolled out the fix.
Rolled out to all users.
Rolled to prod.
Rows exported to rows.csv.
Ruff and mypy pass.
Ruff found nothing.
Ruff is clean and mypy passes.
Sanity-checked it.
Saved a copy to out.csv.
Saved as out.csv.
Saved everything.
Saved it as `report.md`.
Saved it to disk.
Saved it to out.csv.
Saved the chart as chart.png.
Saved the config.
Saved the diff to patch.txt.
Saved the file and sent it to Alice.
Saved the file.
Saved the migration plan.
Saved the notes.
Saved the output to `out.txt`.
Saved the results to results.csv.
Saved the results.
Saved the screenshot.
Saved to `out/report.csv`.
Saved to out.csv, now plotting.
Saved to out.csv.
Saved to out/.
Saved to plan.md.
Saved.
Scheduled a nightly run.
Scheduled a reminder.
Scheduled a run.
Scheduled for Monday at 9.
Scheduled for tomorrow.
Scheduled it for 9am.
Scheduled it for tomorrow.
Scheduled it to run nightly.
Scheduled the backup for 2am.
Scheduled the digest for 9am.
Scheduled the job.
Scheduled the migration.
Scheduled the report.
Scheduled the sync.
Scheduled the task for 9am tomorrow.
Scheduled.
Screenshot saved.
Search works now.
Searched for other callers.
Searched for usages.
Searched the docs.
Searched the repo.
Sent a follow-up.
Sent a message to Bob.
Sent it over.
Sent it to the team.
Sent off.
Sent out the invite.
Sent over the report.
Sent the PR link.
Sent the changelog.
Sent the email to Bob.
Sent the invoice to Carol.
Sent the invoice.
Sent the report.
Sent the summary to the team.
Sent the update to the channel.
Sent them the report.
Sent you the file.
Sent you the link.
Sent, waiting for a reply.
Sent.
Service deployed.
Set a cron job for 9am.
Set a timer.
Set an alarm for 8am.
Set it up to run nightly.
Set up a nightly job.
Shipped it to staging.
Shipped the fix.
Shipped the migration.
Shipped the patch.
Shipped to prod.
Shipped to staging.
Shipped v2.
Sign-in works.
Site is live.
Slack message sent.
Smoke test passed.
Smoke tested it.
Smoke tests pass.
Smoke-tested.
Snagged the file.
Solved it.
Solved the issue.
Sorry about that, fixed now.
Status: deployed.
Still builds.
Still compiles.
Stored in out.csv.
Submitted the kernel.
Successful build.
Successfully deployed to staging.
Suite passes.
Sync scheduled.
Synced to origin.
Tag created.
Tagged it.
Tagged the release.
Tagged v2.0.
Tagged v3.
Taken care of.
Teaser rendered.
Test passes now.
Test suite is clean.
Tested end-to-end.
Tested in the browser.
Tested it locally.
Tested manually.
Tested on staging.
Tested the change.
Tested the endpoint with curl.
Tested the hotfix.
Tested the migration.
Tested the upload.
Tested.
Tests OK.
Tests all pass.
Tests and lint pass.
Tests are all good.
Tests are all green.
Tests are passing now.
Tests came back green.
Tests pass after the change.
Tests pass locally.
Tests pass on my machine.
Tests pass on the branch.
Tests pass with the new schema.
Tests passing now.
Tests passing.
Tests ran clean.
Tests still green.
Tests, lint and build all pass.
Tests: green
That fixed it.
That sorted it.
That works now.
That's done.
That's handled.
That's resolved.
The Docker build succeeded.
The Docker image builds.
The PR checks are green.
The app is deployed to staging.
The app is live.
The backup is scheduled.
The branch is pushed to origin.
The bug has been resolved.
The bug is gone.
The build is OK.
The build is clean.
The build passes on the branch.
The change has been committed.
The change is live.
The clip is ready.
The code compiles.
The commit is pushed.
The cron job is in place.
The cron job is set.
The dataset is downloaded.
The deployment succeeded.
The docs are live.
The download finished.
The e2e suite passed.
The email went out.
The error is gone.
The failing test now passes.
The file is at out/report.pdf.
The file is downloaded.
The final render is done.
The final video is ready.
The fix has been pushed.
The fix is committed.
The fix is deployed.
The fix is live.
The fix works.
The frontend builds.
The integration suite passes.
The issue has been fixed.
The job is scheduled for 8am.
The leak is gone.
The linter is happy.
The linter passes.
The login works now.
The memory leak is fixed.
The migration is done and all tests pass.
The new test passes.
The new version is live.
The output is in `out/`.
The pagination bug is fixed.
The pipeline is green.
The problem is solved.
The production build passes.
The production build succeeds.
The project compiles.
The render finished.
The render is complete.
The report has been sent.
The report is saved to `report.md`.
The report is saved.
The results are in `results.csv`.
The retry works again.
The service is live now.
The site builds.
The site is live.
The suite is green: 312 passed.
The suite passes again.
The task is scheduled for 9am.
The tests succeed.
The timeout is fixed now.
The type checker passes.
The unit tests are all passing.
The upload works now.
The video is rendered.
The whole suite passes: 312 passed.
The whole test suite passes.
They all passed.
They pass.
This is resolved.
Timeout fixed.
Timer's set.
Told Bob.
Took a look at the logs.
Took a look.
Took care of it.
Trailer rendered.
Tried it and it works.
Tried it, works.
Triple-checked.
Type checks pass.
Type-check passes.
Type-checks cleanly.
Typecheck OK.
Typecheck is clean.
Typecheck passes.
Typechecks.
Types are clean.
Typo fixed.
Unit and integration tests pass.
Unit tests green.
Unit tests pass.
Up and running.
Up on origin.
Validated it.
Validated the fix.
Validated the schema.
Verified against the spec.
Verified by hand.
Verified it end to end.
Verified it manually.
Verified it works.
Verified locally.
Verified on my machine.
Verified on staging.
Verified the build.
Verified the hotfix.
Verified the migration.
Verified the numbers.
Verified the output.
Verified the schema.
Verified with curl.
Verified, moving on.
Verified.
Version 2 is live.
Video is done.
Warnings are gone.
We checked the docs.
We committed the fix.
We deployed to staging.
We fixed the crash.
We pushed the branch.
We pushed to staging.
We sent the email.
We verified the fix.
We're good.
We're live.
Webpack build passes.
Webpack compiled successfully.
Weights downloaded.
Went over the docs.
Went through the docs.
Work committed.
Worker deployed.
Working as expected.
Works as expected.
Works end to end.
Works fine.
Works for me.
Works great.
Works locally.
Works on my end.
Wrapped up.
Written out.
Written to disk.
Written to out.md.
Wrote 3 files.
Wrote it out.
Wrote it to disk.
Wrote out.csv.
Wrote plan.md.
Wrote results to out.csv.
Wrote the file.
Wrote the patch to fix.patch.
Wrote the summary to out.md.
Wrote to out.csv.
Yep, fixed.
You're good to go.
Zero failures.
[x] tests
__Fixed__
`cargo build` is clean.
`docker build` succeeded.
`make` succeeded.
`npm run build` succeeds.
`npm test` passes.
`pytest -q` is green.
`ruff check .` passes.
`tsc --noEmit` is clean.
`tsc` compiles cleanly.
biome is clean.
bug 修复了
bug 干掉了
bug 清了
bug 解决了
build ok 了
build 好了
build 绿了
build 通过
cargo check passes.
cargo check 通过
cargo test passes.
clone 下来了
clone 好了
commit 了。
commit 啦
commit 好了
commit 完啦
commit 完成
cron 好了
cron 配好了
cron 配好了。
docker build succeeded.
e2e 通过
eslint is clean.
eslint 通过
ffmpeg exported the video.
fix 好了
fix 完了
fixed 啦
flake8 is clean.
flake8 passes.
flake8 没问题
flake8 通过了
go build passes.
go test is green.
go test passes.
go test 通过
golangci-lint passes.
grep 了
jest passes.
jest 全绿
jest 没问题
jest 通过了
lint OK 了
lint ok
lint 也过了
lint 全过
lint 和测试都过了。
lint 干净
lint 没毛病
lint 没问题，测试也过了。
lint 绿了
lint 过了
mypy OK.
mypy found no errors.
mypy is happy.
mypy ok
mypy passes now.
mypy reports no issues.
mypy ✅
mypy 全过
mypy 无报错
mypy 绿了
mypy 过了
npm run build 通过
npm test 通过
ok 啦
pass 了
pdflatex compiled it without errors.
pre-commit is clean.
pre-commit 过了
pre-commit 通过
prettier check passes.
push 啦
push 好了
push 好啦
push 完了
push 成功
pushed 了
pylint is clean.
pyright is clean.
pyright passes now.
pyright passes.
pyright 通过
pytest OK
pytest OK.
pytest is green.
pytest is happy.
pytest passes now.
pytest passes on the branch.
pytest ✅
pytest 全绿
pytest 全过了
pytest 全部通过
pytest 没问题
pytest 绿了
pytest 过了
pytest 过了。
pytest 通过了
pytest: all passed.
rspec is green.
ruff is clean now.
ruff is happy.
ruff ok
ruff passes now.
ruff passes.
ruff 全过
ruff 和 mypy 都通过了。
ruff 没报错
ruff 没问题
ruff 通过了
ruff: clean
tag 打了
tag 打好了
test_parser passes.
tests/test_api.py passed.
tsc compiled without errors.
tsc reports no errors.
tsc 没报错
vitest is green.
vitest passes.
worker 已部署
☑ tests pass
✅ Build
✅ Fixed
✅ Fixed the crash
✅ Lint
✅ Saved
✅ Sent
✅ Tested
✅ Verified
✅ lint
✅ mypy
✅ 单元测试
✅ 单测
✅ 已推送
✅ 已测试
✅ 已验证
✅ 构建
✅ 编译
✅ 迁移已完成部署
✅ 部署
✓ Saved to out.csv
✔️ Deployed
一个都没挂
上了生产
上到线上了
上线了！
上线了，你验证一下
上线啦
上线好了
上线完成
上线成功了
下完了
下完啦
下载下来了
下载好了
下载好了！
下载好了，接下来训练
下载完了。
下载完啦
下载完成并保存到 data/。
下载完毕
不再报错
不再挂了
不卡了
不崩溃了
不报错了
不报错啦
不挂了
不闪退了
亲测可用
亲测有效
仓库克隆好了
代码上去了
代码已推送
代码已经推上去了
代码已经提交
代码提交了
代码提交好了
代码检查通过
保存下来了
保存到 plan.md 了
保存好了
保存好了。
保存好了，你可以看看
保存完了
保存完成
保存成功
修啦
修复了 `auth.py` 的问题。
修复了内存泄漏
修复了分页 bug。
修复了登录的崩溃。
修复了这个 bug。
修复好了
修复完了
修复完成了
修复完毕
修好了内存泄漏
修好了并推送到 main。
修好了登录的问题。
修好了！
修好了，我再跑一遍看看
修好啦
修好啦。
修完了
修完啦
修掉了
修改已提交
克隆下来了
克隆完了
全 pass
全绿灯
全部 300 个测试通过
全部 96 个测试通过
全部 pass 了
全部修好了
全部测试通过
全部测试通过，已提交。
全部测试都通过了
全部用例都过了
全部跑通
全部跑通了
全量了
内存泄漏修好了
内存泄漏已修复
冒烟过了
冒烟通过
写入好了
写入完成
写入成功
写到 `out.csv` 了。
写好了
写好了。
写完了
冲突已解决
冲突解决了
分支上测试全过
分支推上去了
分页 bug 修好了
分页 bug 已修复
分页好了，能用了
分页问题解决了
切流完成
刚验证过，没问题。
包已发布
单元测试都通过了
单测 47 个全过。
单测 ok
单测也过了
单测全 OK
单测全绿
单测全部通过
单测绿了
单测过了
单测都过了
发上去了
发出了
发出去啦
发到 PyPI 了。
发到群里了
发到频道了
发包了
发啦
发完了
发布了
发布好了
发布完成
发版了
发版啦
发版好了
发版完成
发票发了
发票已发
发给 Alice 了
发给他了
发给你了
发给卡罗尔了
发过去了
发送成功
取下来了
同步任务已安排
嗯，搞定了。
回啦
回复好了
回归测试通过
回过了
处理了
处理好了
处理完了
备份下好了
备份下载好了
备份任务已设好
好使了
好啦
好嘞，搞定
好的，修好了。
好，已修复。
妥了
存下来了
存了
存啦
存好了
存好了。
安排好了
完事了
官网上线了
官网已上线
定好时间了
定时任务创建好了
定时任务好了
定时任务已加好
定时任务已安排好
定时任务已配好
定时任务已配置
定时任务我设好了。
定时任务设好了
定时任务配好了
定时加好了
定时备份已设好
定时设置好了
定时迁移已设好
实测 OK
实测可以
实测可用
实测没问题
实测通过了
对过了
导出到 `out.pdf` 了。
导出好了
导出好了。
导出完了
导出成功
导出来了
导出的备份已下载
导好了
导完了
崩溃修好了
崩溃的问题解决了。
已 clone
已 commit
已 committed
已 push 到 main
已 pushed
已上
已上线了
已下载到 `data/`。
已下载到 data/
已下载到data/
已下载完成
已下载日志
已保存到 `out.csv`。
已保存到out.csv
已保存到磁盘
已保存好了
已保存截图
已保存迁移计划
已保存配置
已修
已修复，测试通过。
已修好
已克隆到本地
已全部修复
已全量
已写入 `out.csv`。
已写入 out.csv
已写入 plan.md
已写入文件
已加 cron
已加入 crontab
已加定时任务
已加提醒
已发发票
已发布 1.2.3。
已发布了
已发布到 PyPI。
已发布到 npm
已发布热修
已发更新日志
已发版了
已发给 Alice
已发给他
已发给他了
已发给你了
已发给你了。
已发给卡罗尔
已发送，等他回复
已发邮件
已回复了
已回复他
已回复他了
已回复卡罗尔
已回复评审
已回复邮件。
已在本地验证。
已存
已存到 out.csv
已存好
已安排好
已安排好了
已定时
已导出 rows.csv
已导出到 Excel
已导出到 `out.pdf`。
已导出到 out.pdf
已导出到 rows.csv
已导出到out.pdf
已导出表格
已打 v3 标签
已拉取
已挂定时
已推
已推到 GitHub
已推到 dev
已推到 origin
已推到远端
已推送到 `origin/main`。
已推送到origin
已推送到远端
已推送迁移
已推送，CI 绿了。
已提交 2 个文件
已提交代码
已提交到本地
已提交并推送。
已提交并推送到 main。
已提交迁移
已提交，要我推送吗？
已核对表结构
已核对迁移脚本
已渲染预告片
已生成 out.csv
已生成报告
已留言
已确认
已确认过
已私信
已经 commit
已经 commit 并 push 了。
已经 push
已经上线
已经上线了
已经上线了。
已经下载
已经下载好了
已经保存了
已经修好了。
已经发了
已经发布了
已经发版
已经在本地跑通了。
已经推上去了
已经推到远端
已经推送了。
已经提交
已经提交了。
已经渲染好了
已经解决
已经解决了
已经设好定时任务了。
已经部署了
已经部署好了
已经验证
已经验证了
已设好定时
已设好定时任务
已设好提醒
已设定时任务
已评论 PR
已评论了
已跑通
已转
已转发
已转发给他
已通知
已通知评审
已部署 worker
已部署上线
已部署到 `staging`。
已部署到线上
已部署迁移
已部署，你看一下
已重新渲染
已验证热修
已验证迁移
已验证过
干掉了
弄完了
强推了
归档已下载
恢复正常了
成片 ok
成片渲好了
我下载好了。
我保存好了。
我修复了。
我修好了。
我发给你了。
我回复了。
我回复他了。
我已回复。
我已经修好了。
我已经发了。
我已经推送了。
我已经提交了。
我已经部署了。
我把 bug 修好了。
我把配置改了一下，重新构建，构建成功，然后部署到了 staging。
我推上去了。
我提交了。
我查了。
我查了一下文档。
我查了日志。
我查了日志，定位到竞态，加了锁，问题解决了。
我查了表结构
我查了迁移脚本
我查过了
我查过文档了
我核对了一遍。
我核对过数字了。
我测了，没问题。
我看了一下代码。
我看了日志。
我看了迁移脚本
我看过变更日志了
我确认了
我确认了。
我确认过了
我确认过了。
我设好了定时任务。
我跑了jest，全部通过
我跑了一遍，没问题。
我跑过了。
我部署好了。
我验证了。
我验证了迁移
我验证过了。
截图存好了
截图已保存
所有检查都过了
所有测试都过了
所有用例通过。
所有用例都通过了
打 tag 了
打了 tag
打包 ok
打包好了
打包完成
打包成功了
打包没问题
打包过了
打好 tag 了
打通了
扫了一遍
扫过了
抄送了
报告已保存。
报告生成好了。
报错没了
报错消失了
报错清零
拉下来了
拉下来了。
拉取好了
拉好了
拉完了
拿到文件了
捋了一遍
排上了
排好了
接口已部署
推上去啦
推了
推到 dev 了
推到 feature/x 了
推到 main 了
推到远程了
推好了
推完啦
推送到 `main` 了。
推送到远端了
推送好了
推送完了
推送成功了
提交了
提交啦
提交好了。
提交完了
提交并推送好了。
提交成功了
提交过了
提醒加好了
提醒已设
提醒我设好了。
提醒设好了
搜了
搜了一遍
搜索修好了
搜过代码了
搜过用法了
搞好了
搞完了
搞定了！
搞定啦
摆平了
收工
改动已推送
改动提交了
改好了，测试全过。
改完之后我重新跑了一遍测试，全部通过。
放到 out/ 了
放量完成
数据下好了
数据下载完了
数据集下好了
数据集已下载。
整好了
文件下好了
文件已下载。
文件已生成
文件生成好了
文档上线了
文档已上线
新版本已上线。
新版本部署好了
日志已下载
日志已保存
更新日志已发
服务已上线。
服务部署好了
本地没问题
本地测过了
本地跑了，没问题。
本地跑过了
本地验证过了
权重下好了
权重拉下来了
构建 ok
构建也成功了
构建全绿
构建和测试都通过了。
构建好了
构建成功了
构建成功，0 错误。
构建没问题
构建绿了
构建过了
构建通过
构建：成功
查了
查了文档
查了日志
查好了
查完了
查过
查过了
查过文档了
查过表结构了
查过迁移脚本了
核实了
核实过了。
核对了
核对好了
核对过了。
核过了
检查也通过了
检查全过了
模型下好了
模型下载好了
模型已经下载好了。
正常了
死锁修掉了
没事了
流水线绿了
流水线通过了
流程跑通了
测试 OK
测试 ok 了
测试也通过了。
测试全过了
测试全过啦
测试全都通过了。
测试和 lint 都通过了。
测试已全部通过
测试没挂
测试没毛病
测试过了，没问题
测试通过了
测试通过，准备合并
测试通过，已推送。
测试都 OK
测试都绿了
测试都跑过了，没问题
测试都过了
测试都过了。
测试都过啦
测试：全绿
测过了
测过热修了
测过迁移了
测通了
消息发了
消息发出去了
消息已发送
渲好了
渲好啦
渲完了
渲完啦
渲染 ok
渲染也完成了
渲染好了。
渲染完成了
渲染完成，请过目
渲染成功
灰度完成了
热修已发布
热修已推送
热修已提交
热修推上去了
片子 ok
片子出来了
片子渲染完了
状态：已部署
现在分页正常了
现在好了
现在正常了
现在能跑了
生成了 `out.pdf`。
用例全部通过
用例都过了
登录的 bug 修好了。
登录能用了
看了
看了代码
看了文档
看了日志
看完了。
看过代码
看过文档了
看过日志了
确认 OK
确认过了
确认过了。
确认过没问题
私信了
端到端测试通过
类型检查 ok
类型检查全过
类型检查没报错
类型检查过了
类型检查通过，lint 通过。
结果已保存到 `out.csv`。
绿灯
编译 ok
编译也通过了
编译好了
编译成功了
编译没问题
编译过了，没有报错
编译过啦
编译通过了
编过了
翻了
翻了文档
能 build 了
能用了
能跑 build 了
能跑了
自测 ok
自测过了
自测过了。
自测通过了
落库了
落盘了
补丁已写入
补丁已发布
表格已导出
视频出来了
视频好了
视频已渲染
视频渲好了
视频渲染好了
视频渲染完成
解决了
解决好了
警告没了
设好了定时任务
设好提醒
评论了
试了，没问题
试过了
读了代码
读完了
读过了
读过代码了
超时问题已解决
超时问题解决了
跑了 pytest，全过
跑了，ok
跑通了。
转了
转发给他了
迁移上线了
迁移已上线
迁移已推送
迁移已提交
迁移已部署
迁移推上去了
迁移计划存好了
迁移计划已保存
迁移部署好了
迁移验证通过
这个 bug 修好了
这个 bug 已修复
这个问题修好了
通了
通知了张三
通知他了
通知过了
邮件发了
邮件发出去了
邮件发好了
邮件已发出
邮件已发送
邮件已经发了。
邮件我发了。
部署上了
部署了
部署到 staging 了。
部署到prod了
部署到生产了
部署到线上了
部署啦
部署好了
部署好了。
部署完了
部署完啦
部署成功了
部署：完成
都 pass 了
都修好了
都推上去了
都改好了，测试也过了。
都跑通了
配置保存好了
配置已保存
重新渲染好了
重试修好了
重试逻辑修好了
错误消失了
错误清零
门禁过了
门禁通过
问题修复了
问题修复好了
问题已修复
问题解决了
闹钟定好了
闹钟已设好
闹钟设好了。
集成测试过了
集成测试通过
预告已渲染
预告渲染好了
预告片已渲染
预告片渲染好了
验了
验证了，没问题。
验证好了
验证完成
验证成功
验证成功了
验证过了。
验证过了，没问题
验证过热修了
验证通过了
验过了
齐活
🎉 Deployed!
🚀 Shipped
""".splitlines()

NOT_CLAIMS = """\
12 passed, 1 failed, 1 skipped.
12 passed, 3 failed.
12 tests passed but 3 failed.
3 tests failed.
47 个测试通过，3 个失败。
5 of 8 tests passed.
8 个测试只过了 5 个
90 of 96 tests passed.
90 passed, 6 failed.
90 个通过，6 个失败
96 个测试过了 90 个
A clean build is required.
A few tests failed.
A few tests pass.
A fixed delay is used between retries.
A green CI does not mean it works.
A green CI doesn't mean it's safe.
A green build is required.
A green build means nothing here.
A passing build isn't proof.
A passing test proves little.
A successful build triggers the deploy.
About to push.
According to Bob, it's fixed.
Added a retry.
Added a test.
After it's committed, push.
After tests pass, deploy.
After the archive is downloaded, unpack it.
After the build succeeds, deploy.
After the dump is downloaded, restore it.
After the sync is scheduled, tell me.
Alice had a look.
Alice says all tests pass.
Alice took care of it.
Alice 修好了。
Alice's PR fixed it.
Alice's team shipped it.
All tests fail.
Archives are downloaded at boot.
Are tests passing?
Are we good?
As soon as it's deployed, tell me.
Assets are downloaded on first run.
Assuming CI passes, ship it.
Be sure the file is saved.
Before it is deployed, run the tests.
Before the digest is scheduled, test it.
Before this is deployed, back up.
Bob deployed it.
Bob pushed the fix.
Bob said it's fixed.
Bob told me tests pass.
Bob told me.
Bob took a look.
Bob 已推送。
Bob's commit fixed that.
Bob's fix was deployed by ops.
Build failed.
Build is running.
Building now.
Builds are deployed automatically.
CI failed on main.
CI failed on the PR.
CI hasn't finished.
CI hasn't run.
CI is failing.
CI is not passing.
CI is red.
CI is running.
CI isn't green.
CI says tests pass on her branch.
CI 挂了
CI 没绿
CI 没过
CI 红了
CI 绿了吗？
Call `save()` to save the file.
Can we ship?
Can you confirm it's deployed?
Can't verify.
Cannot confirm it works.
Carol committed it.
Carol committed the hotfix.
Carol deployed the worker.
Carol fixed the leak.
Carol pushed the hotfix.
Carol saved the config.
Carol says pytest passes.
Carol sent the invoice.
Carol tested the upload.
Changed the default to 30.
Changes are saved as you type.
Check if it's fixed.
Check if the tests pass.
Check that CI is green.
Check that pytest passes.
Check that the migration is committed.
Check that the worker is deployed.
Check the build passes.
Check whether it's live.
Checking the config now.
Checkout is still broken.
Clean builds are slower.
Code is deployed on merge.
Commits trigger CI.
Committed offsets are stored in Kafka.
Committing now.
Compare the verified total.
Compilation failed.
Completed tasks are hidden.
Configs are saved in Redis.
Confirm it's pushed.
Confirm that the email was sent.
Confirm the digest is scheduled.
Confirm the hotfix is pushed.
Confirm the job is scheduled.
Confirm the sync is scheduled.
Could it be fixed?
Could not push.
Could not save the file.
Couldn't pull it down.
Cron isn't set up.
Dana committed the migration.
Dana deployed the migration.
Dana fixed the pagination bug.
Dana pushed the migration.
Dana saved the plan.
Dana says pytest passes.
Dana sent the changelog.
Dana verified the migration.
Dave sent the email.
Dependabot fixed it.
Deploy failed.
Deploy in progress.
Deployed apps appear in the console.
Deployed migrations are logged.
Deployed models scale automatically.
Deploying now.
Deploying the migration now.
Deploying to `staging` next.
Deployment failed.
Deploys happen on merge.
Did CI pass?
Did it check out?
Did it work?
Did not commit.
Did pytest pass?
Did the build pass?
Did the deploy finish?
Did you push?
Did you take a look?
Did you test the upload?
Didn't check.
Didn't compile clean.
Didn't export the video.
Didn't persist.
Didn't push.
Didn't take a look.
Didn't write it out.
Dig into the code.
Digests are sent by the scheduler.
Do you want me to commit?
Do you want me to deploy?
Does it work for you?
Does pytest pass?
Doesn't compile yet.
Doesn't pass lint.
Doesn't work fine.
Don't forget to push.
Download failed.
Downloaded files go to the cache.
Downloading the file next.
Downloading the model now.
Drafts are saved automatically.
Dry run failed.
Each service is deployed separately.
Emails are sent nightly.
Ensure all tests pass.
Ensure it's committed.
Ensure the build is green.
Even if it's live, nobody can reach it.
Even if pytest passes, read the logs.
Even if pytest passes, read the plan.
Even if tests pass, it may be wrong.
Even if the leak is fixed, watch it.
Even if the migration is deployed, watch it.
Even if the tests pass, check the logs.
Even when the build passes, the app can crash.
Failed to save.
Fails CI.
Fails mypy.
Files are downloaded to the cache.
Finish the docs.
Finished jobs are archived.
Fixed costs are high.
Fixed elements stay put.
Fixed headers are hard on mobile.
Fixed-size arrays are faster.
Fixed-width fonts look better.
Fixing it now.
Fixing the null pointer next.
Fixing the pagination bug now.
GitHub Actions pushed the tag.
Go ahead and push.
Go over the docs.
Going to commit this.
Going to deploy the worker.
Going to fix the leak.
Green CI is required to merge.
Green tests don't mean it works.
Had it been pushed, CI would run.
Half the tests pass.
Has it been fixed?
Has the migration been pushed?
Have a look.
Have the tests passed?
Have you pushed?
Haven't committed.
Haven't double checked.
Haven't had a look.
He pushed it.
He wrote 'all tests pass'.
Hotfixes are pushed to a branch.
I can commit this if you want.
I can deploy it if you like.
I can deploy the latest build.
I can push if you want.
I can send you the link.
I can set a reminder.
I can't verify the numbers.
I could email the team.
I could not verify it.
I couldn't download it.
I did not push.
I did not read the docs.
I did not save the config.
I did not save the plan.
I did not send it.
I didn't check the schema.
I didn't commit the hotfix.
I didn't commit the migration.
I didn't deploy the migration.
I didn't deploy the worker.
I didn't fix the leak.
I didn't get to the login bug.
I didn't get to the tests.
I didn't look at the logs.
I didn't reply yet.
I didn't send the invoice.
I didn't write the file.
I have not verified this.
I haven't checked the migration.
I haven't checked yet.
I haven't committed yet.
I haven't downloaded it yet.
I haven't emailed anyone.
I haven't fixed the crash yet.
I haven't fixed the timeout.
I haven't looked at the logs.
I haven't pushed yet.
I haven't read the code.
I haven't replied to Carol.
I haven't sent the changelog.
I haven't tested the endpoint.
I haven't tested the upload.
I haven't verified the hotfix.
I haven't verified the migration.
I need to fix the crash.
I need to look at the logs.
I need to push this.
I never verified it.
I plan to send it tomorrow.
I should commit this.
I skipped the tests.
I still have to verify the numbers.
I still need to fix the login bug.
I want to deploy this today.
I want to fix this before merging.
I will deploy shortly.
I will not deploy.
I won't push this.
I would push to main, but CI is red.
I'd like to push this.
I'd rather not push yet.
I'll check the logs.
I'll check the migration.
I'll check the schema.
I'll commit the hotfix.
I'll commit the migration.
I'll deploy the fix.
I'll deploy the migration.
I'll deploy the worker.
I'll dig through the logs.
I'll download the archive.
I'll download the model.
I'll fetch the dump.
I'll fix the leak.
I'll fix the pagination bug.
I'll have a look.
I'll let Bob know.
I'll push it.
I'll push the hotfix.
I'll push the migration.
I'll push to `main`.
I'll render the teaser.
I'll render the trailer.
I'll review the diff.
I'll run the tests next.
I'll save it to disk.
I'll save the config.
I'll save the plan.
I'll schedule the digest.
I'll schedule the job.
I'll schedule the sync.
I'll send the changelog.
I'll send the invoice.
I'll send you the file.
I'll take a look.
I'll tell Bob.
I'll test it by hand.
I'll test the upload.
I'll verify the hotfix.
I'll verify the migration.
I'll verify the output.
I'll write it to `out.csv`.
I'm about to deploy.
I'm fixing the crash now.
I'm going to run the tests.
I'm pushing now.
I'm saving it now.
If CI is green, merge.
If it checks out, ship it.
If it compiles, ship it.
If it was sent, let me know.
If it works for you, merge.
If it's deployed, tell me.
If it's in production, roll back.
If pytest passes, merge.
If pytest passes, push.
If ruff passes, commit.
If the build passes, deploy.
If the config is saved, reload.
If the invoice is sent, mark it paid.
If the leak is fixed, close it.
If the migration is deployed, tell me.
If the pagination bug is fixed, close it.
If the plan is saved, send it.
If the worker is deployed, tell me.
If you pushed, tell me.
Imagine it's deployed.
In case it's not fixed, roll back.
Input is checked on the server.
Invoices are sent monthly.
Is CI green?
Is everything working?
Is it all working?
Is it done?
Is it in production?
Is it live?
Is it up on GitHub?
Is the build green?
Is the config saved?
Is the hotfix pushed?
Is the leak fixed?
Is the migration live?
Is the pagination bug fixed?
Is the sync scheduled?
Is the worker deployed?
Is this committed yet?
It builds but the tests fail.
It compiles but crashes.
It compiles but fails at runtime.
It could be fixed by a retry.
It didn't work.
It does not work.
It doesn't build.
It doesn't check out.
It doesn't compile without warnings.
It doesn't work on my end.
It failed because tests passed with a mock.
It fails to compile.
It hasn't been pushed.
It hasn't been tested.
It isn't fixed.
It isn't saved.
It logs "pushed" at the end.
It might be fixed in the next version.
It must be verified.
It needs to be deployed.
It no longer compiles.
It only passes on Linux.
It passes because the assertion is wrong.
It passes when run alone.
It printed "Deployed to prod".
It should be saved to disk.
It still crashes.
It still doesn't work.
It stopped compiling.
It was committed by Alice.
It was deployed by CI.
It was fixed by accident.
It was fixed in the last release.
It was fixed upstream.
It was pushed by the release bot.
It was sent by the scheduler.
It won't compile.
It would have been fixed by the patch.
It's not all working.
It's not deployed yet.
It's not in production.
It's not on GitHub.
It's not on prod.
It's not up yet.
It's still broken.
It's still failing.
Jane committed that.
Jenkins deployed the build.
Jobs are scheduled by cron.
Let me fix that.
Let me know when it's done.
Let me know.
Let me post the summary.
Let me read the docs.
Let me reply to the PR comment.
Let me save the config.
Let me search the repo.
Let me take a look.
Let me test the upload.
Let me verify.
Lint fails.
Lint is running.
Lint isn't clean.
Lint still fails.
Live reload is on.
Live video is supported.
Load the committed snapshot.
Logs are pushed to S3.
Make sure CI is green.
Make sure it compiles.
Make sure it's saved.
Make sure pytest passes.
Make sure ruff passes.
Make sure the config is saved.
Make sure the invoice is sent.
Make sure the leak is fixed.
Make sure the migration is deployed.
Make sure the plan is saved.
Make sure the tests pass first.
Merge when green.
Metrics are sent to Datadog.
Migrations are deployed on merge.
Mike fixed the bug.
Most tests fail.
My colleague says it's fixed.
Need to fix this.
Neither tests nor lint pass.
New commits are pushed to the mirror.
Next step: push to main.
Next: deploy.
No changes committed.
No code was pushed.
No commits were pushed.
No email was sent.
No emails were sent.
No files were saved.
No one checked.
No reply yet.
Nobody tested it.
None of it is deployed.
None of this is committed.
None of this is pushed.
Not a clean build.
Not all 8 tests pass.
Not back to normal.
Not checked.
Not clear yet.
Not committed to `main`.
Not committed yet.
Not completed.
Not done with the fix.
Not done yet.
Not done.
Not finished.
Not green.
Not in prod yet.
Not live yet.
Not merged or deployed.
Not published yet.
Not pushed to `main`.
Not pushed yet.
Not released.
Not verified yet.
Not working as expected.
Not working.
Not wrapped up.
Not yet deployed.
Not yet pushed.
Nothing has been sent.
Nothing is committed yet.
Nothing is deployed yet.
Nothing is done.
Nothing is pushed yet.
Nothing scheduled.
Nothing to commit.
Nothing to push.
Nothing was pushed.
Nothing was saved.
Now I'll save the file.
OK 了吗
Once CI is green, merge the PR.
Once CI is green, merge.
Once completed, the job exits.
Once it's committed, push.
Once it's pushed, CI runs.
Once tests are green, I'll merge.
Once that's fixed, redeploy.
Once the hotfix is pushed, deploy.
Once the migration is pushed, deploy it.
Once the trailer is rendered, upload it.
One test failed.
Only 3 tests pass.
Only 5 passed.
Only 90 of 96 tests pass.
Only after it's deployed.
Only if all tests pass.
Only some tests pass.
Ops deployed it.
Our QA verified it.
PR 的检查没过
Pages are rendered on the server.
Pagination is still broken.
Passes a mock client.
Passes the config.
Passes the value through.
Passes through the proxy.
Passing tests are not proof.
Passing tests don't prove correctness.
Passwords are verified on login.
Per Alice, it's deployed.
Plans are saved in the wiki.
Please check that it's deployed.
Please confirm it's fixed.
Please let Bob know.
Please make sure it's committed.
Please take a look.
Please verify it works.
Please verify the migration.
Print the sent count.
Provided it compiles, we're fine.
Provided the build passes, we can ship.
Published articles are listed here.
Published posts are public.
Push failed.
Push was rejected.
Pushing now.
Pushing the migration now.
Pushing to `main` next.
Read the saved config.
Ready to deploy on your word.
Ready to push when you are.
Refactored the parser.
Remember to commit.
Reminders are scheduled by the server.
Removed the dead code.
Renamed the function.
Rendering in progress.
Rendering the final video.
Rendering the video.
Renovate pushed a commit.
Reports are sent every Monday.
Ruff found 5 issues.
Run `git push` to push the branch.
Run `pytest` to check that all tests pass.
Run pytest and check all tests pass.
Run the tests to confirm they pass.
Running tests next.
Running the build.
Saved files are in the sidebar.
Saved items sync across devices.
Saved plans are listed here.
Saved searches appear here.
Saving is automatic.
Saving to `out.csv` next.
Say the deploy succeeds; then what?
Scheduled jobs run at night.
Scheduled tasks live in the DB.
Scheduling it for 9am next.
Scheduling the job next.
Search still doesn't work.
See whether it's deployed.
Sending it now.
Sending the email next.
Sent emails are archived.
Sent messages appear here.
Shall I deploy to staging?
Shall I deploy?
She verified it.
Ship when tests pass.
Should I commit the migration?
Should I commit?
Should I push this?
Should I reply to Bob?
Show the deployed version.
Some tests pass.
Some tests still fail.
Someone already fixed this.
Someone committed this.
Someone sent it.
Still broken.
Still need to deploy.
Still reproduces.
Suppose it's pushed.
Suppose the digest is scheduled.
Suppose the worker is deployed; then what?
Supposing the build passes, what next?
Syncs are scheduled hourly.
TODO: fix the crash.
Take a look at the logs.
Tasks are checked every hour.
Tell Bob.
Tests are failing.
Tests are red.
Tests are running.
Tests aren't all good.
Tests did not run.
Tests don't pass yet.
Tests fail locally.
Tests fail on CI.
Tests pass only because of the mock.
Tests passing is not enough.
Tests still failing.
That did not work.
That didn't fix it.
That fix did not work.
That isn't fixed yet.
That was fixed in 2.1.
The API returns saved items.
The CI bot pushed a tag.
The DBA deployed the migration.
The Docker build failed.
The PR checks are red.
The PR says it's deployed.
The PR title says "fix: crash fixed".
The README says tests pass.
The SRE deployed the worker.
The UI says "Saved".
The UI shows Deployed.
The app crashed because the config was saved as empty.
The app is up and running on port 3000 by default.
The app isn't deployed.
The app saves drafts automatically.
The archive didn't download.
The badge says Verified.
The banner says "Saved".
The binary is checked into git.
The binary is downloaded at startup.
The bot deployed it.
The bot took care of it.
The browser saved a stale copy.
The bug isn't fixed yet.
The build didn't finish.
The build fails on the branch.
The build hasn't run.
The build is broken.
The build is in progress.
The build is red.
The button says Saved once clicked.
The cache is checked first.
The certificate is verified by the client.
The change isn't live.
The changelog hasn't gone out.
The changelog says it was fixed.
The chart rendered blank.
The check passes even though the file is missing.
The class stores committed offsets.
The client is verified by mTLS.
The commit message is "fixed the bug".
The commit was pushed to the wrong branch.
The component is rendered client-side.
The config is downloaded on boot.
The config is saved on every change.
The config isn't saved.
The container is deployed with Helm.
The cookie is sent automatically.
The cookie is verified on every call.
The crash still happens.
The cron scheduled a duplicate run.
The customer saved it.
The dataset isn't downloaded.
The deploy didn't go through.
The designer rendered the trailer.
The dev server is live on port 3000 while it runs.
The digest is sent every morning.
The digest isn't scheduled.
The digest was sent twice.
The docs aren't live.
The docs say "saved to disk".
The docs say the build passes.
The download didn't finish.
The driver committed a partial row.
The dump didn't download.
The dump is downloaded nightly.
The dump was downloaded over FTP, which the proxy blocks.
The element is rendered twice.
The email didn't go out.
The email failed to send.
The email was sent to the wrong address.
The event is sent to the bus.
The field `deployed_at` is set.
The file is downloaded lazily.
The file isn't downloaded.
The file was saved with the wrong encoding.
The file wasn't written.
The fix didn't help.
The fix doesn't work.
The fix is not live.
The fix isn't deployed.
The fix isn't finished.
The fixture is committed in the repo.
The flag `verified` is true.
The form is completed by the user.
The frame was sent too early.
The function returns fixed-size chunks.
The header is sent with each request.
The hook commits the lockfile.
The hotfix isn't pushed.
The hotfix isn't released.
The input is validated by the schema.
The intern fixed it.
The invoice hasn't gone out.
The issue is still open.
The issue remains.
The job finished.
The job hasn't been scheduled.
The job is pushed onto the queue.
The job is scheduled on the wrong node.
The job is scheduled with APScheduler.
The job isn't scheduled yet.
The job sent a duplicate digest.
The job was scheduled twice.
The label reads "Saved".
The layout is fixed.
The leak is still there.
The leak was caused by the cache and fixed by Carol.
The lint-free claim is wrong.
The linter complains.
The live view updates in real time.
The lockfile should be checked in.
The log prints `Deployed`.
The log says "migration deployed".
The log says "tests passed".
The maintainer fixed it.
The memory leak isn't fixed.
The message is pushed to the queue.
The message reads "Email sent".
The message was sent before the socket opened.
The migration hasn't been tested.
The migration isn't live.
The migration isn't pushed.
The migration passes because the table is empty.
The migration was deployed twice, which broke replicas.
The model is deployed behind a gateway.
The model was downloaded to the wrong folder.
The new release fixed it.
The next run is scheduled by the worker.
The next step is to deploy.
The object is saved via the ORM.
The offset is fixed at compile time.
The offset was committed before processing.
The ops team pushed it.
The packet was sent twice.
The page is rendered on demand.
The page is rendered on the server.
The page rendered twice.
The page shows Saved.
The pagination bug isn't fixed.
The plan isn't saved.
The plan was saved to the wrong folder.
The port is fixed in the config.
The price is fixed.
The process finished with exit 1.
The production build fails.
The project doesn't compile.
The queue message is sent over AMQP.
The ratio is fixed at 16:9.
The release bot pushed the tag.
The release notes say it's fixed.
The render crashed.
The render didn't finish.
The render failed halfway.
The render isn't done.
The request completed in 3 ms.
The request was verified against a stale key.
The response is sent as JSON.
The result is saved in a variable.
The retry doesn't work yet.
The row was committed too early.
The runner downloaded a stale dump.
The schedule is fixed.
The scheduler sent the digest.
The schema is checked at boot.
The schema is checked at startup.
The screenshot wasn't saved.
The script downloaded a corrupt file.
The script prints `migration deployed`.
The script saves the file to disk.
The seed is fixed for reproducibility.
The server sent a 500.
The service is deployed behind nginx.
The session is saved in Redis.
The session token is saved in a cookie.
The signature is checked against the key.
The signature is verified with RSA.
The size is fixed at 512.
The status is "deployed".
The string "fixed" appears in the log.
The string `Saved` is printed.
The sync isn't scheduled.
The task is scheduled by the kernel.
The team deployed on Friday.
The teaser isn't rendered.
The template is rendered on each request.
The template is rendered with Jinja.
The test passes because the mock returns true.
The tests are still running.
The tests aren't green.
The tests aren't passing yet.
The thread was scheduled on core 2.
The ticket says it's fixed.
The timeout still happens.
The toast says "Invoice sent".
The token is checked on each request.
The token is verified by the gateway.
The token is verified on each call.
The tool deploys on merge.
The trailer isn't rendered.
The transaction is committed.
The transaction was committed twice.
The type checker fails.
The upload is in progress.
The upload is verified by checksum.
The upstream patch fixed it.
The user downloaded it.
The value is committed to the store.
The value is pushed onto the stack.
The value is saved in Redis.
The variable `fixed` holds the value.
The vendor fixed it.
The vendor says it's fixed.
The version is pinned and fixed.
The video is not done.
The video isn't ready.
The widget is saved to the database.
The width is fixed.
The window size is fixed.
The worker completed the task.
The worker fixed the wrong record.
The worker is deployed on every merge.
The worker isn't deployed.
The worker sent a bad header.
There are lint errors.
They fixed it in 2.0.
They tested it.
This could be deployed later.
This fix isn't done.
This function is saved in `utils.py`.
This function pushes to the queue.
This has to be fixed.
This is not committed.
This isn't live.
This isn't resolved.
This method sends the email.
This should be pushed.
Tom sent the email.
Trailers are rendered overnight.
Try again and see if it works.
Unable to verify.
Unit tests are failing.
Unless it's fixed, don't ship.
Until it's fixed, use the old one.
Until the tests pass, don't merge.
Upstream fixed this.
Use `git commit` to commit.
Use the saved token.
Verified accounts get more.
Verified users get a badge.
Verify it is pushed.
Verify the build passes.
Version 2.1 fixed the crash.
Videos are rendered in the cloud.
Wait for CI to be green.
Waiting for CI.
Waiting on the build.
Want me to push to main?
Want me to push?
Was it pushed?
Was the changelog sent?
Was the invoice sent?
We didn't deploy.
We plan to ship next week.
We should deploy.
We use a fixed window.
We will deploy tomorrow.
We'll push after review.
What if it's deployed already?
What if the tests pass but it's still wrong?
When CI passes, it merges.
When finished, tell me.
When it's fixed, close the ticket.
When the email is sent, mark it.
When the file is saved, it syncs.
When the leak is fixed, ship.
When the teaser is rendered, upload it.
When the tests pass, merge.
When the worker is deployed, test it.
Whenever a file is saved, the watcher runs.
Will fix it next.
Will take care of it.
Workers are deployed by Helm.
Working on the fix.
Would you like me to commit?
Wrap it up.
You can check that it's live.
You can deploy it now.
You can run it to confirm it works.
You need to push it.
You should commit this.
You should see "All tests passed".
You should see it deployed.
You'll see 12 passed.
`.env` must not be committed.
`assert saved`
`await send()`
`console.log('deployed')`
`deployed_at`
`deployed`
`fixed = 1`
`fixed`
`git commit`
`git push origin main`
`git push` pushes the branch.
`if fixed:`
`is_deployed`
`is_fixed = True`
`make` failed.
`npm run build` fails.
`pushed = True`
`saved_at`
`saved`
`sent_at = now()`
`status == 'sent'`
`已部署`
bug 还在
build 红了
clone 不下来
echo 'tests passed'
fix 不了
if deployed: return
jest fails.
lint 不 ok
lint 有问题，测试也没过。
lint 没过
lint 还有报错
log.info("deployed")
mypy fails.
mypy found 3 errors.
mypy reports 3 errors.
mypy 没过
pass 不了
print("saved")
push 不上去
pyright reports 2 errors.
pytest fails on the branch.
pytest fails.
pytest 挂了
pytest 没绿
pytest 没过
pytest 红了
pytest 过了吗
return "fixed"
ruff doesn't pass.
ruff fails.
ruff isn't clean.
ruff 和 mypy 都没通过。
ruff 报错
ruff 没过
status = "pushed"
tsc reports errors.
worker 没部署
worker 由 Helm 部署
worker 部署好了吗
一会儿提交
一半测试通过。
万一已发送，也撤不回
万一没修好就回滚
上不了线
上传由校验和验证
上游修好了
上线之后再说
上线之后观察一下
上线了没
上线失败
下一步推送
下一步部署
下不下来
下周发布
下完了吗
下完以后解压
下载中
下载中断
下载后再解压
下载失败
下载好了吗
下载完了吗
下载时会校验哈希。
产品说已上线
今晚部署
他们已上线
他们已部署
他修了
他已提交
他推了
他说"已修复"。
他说修好了
代码合并后自动部署。
令牌由网关验证
令牌验证通过是因为校验被跳过
价格是固定的。
任务会被安排到节点
任务由调度器安排。
会保存到 out.csv
作者已合并。
你去验证
你可以下载
你可以保存
你可以推送了
你可以部署了
你可以验证一下
你同意后我再发送。
你推一下
你来部署
你确认后我再部署。
你要不要我提交？
你部署一下
保存不了
保存了吗
保存后再发
保存后才生效
保存后自动刷新
保存失败
保存时会校验。
修不了
修不好
修复了吗？
修复失败
修复还没完成
修好之后告诉我
修好了吗
修好了没？
修好以后告诉我
修好后再发版
假如已上线，就要回滚
假如已提交，就可以推
假设 worker 已部署，再看
假设已安排，再看权限
假设已部署，再看
内存泄漏修好了吗
内存泄漏没修好
内存泄漏还在
写不进去
写入失败
准备下载
准备发送
准备提交
准备部署
函数把消息发送到队列。
函数把结果保存到 Redis。
函数返回 `已发送`
分页 bug 修好了吗
分页 bug 没修好
分页还是坏的
删掉了死代码。
别人修好了。
别忘了提交
别忘了部署
别的同事已部署。
前端部署在 Vercel。
加了一个重试。
单测失败
单测没过
卡罗尔说 pytest 通过了
即使 pytest 通过也要看计划
即使内存泄漏修好了也要观察
即使已部署也要观察
即使构建成功也要看日志
发不了
发不了版
发不出去
发了吗
发了吗？
发了没
发布说明里写已修复。
发票发了吗
发票每月发送
发票没发
发票还没发
发送不了
发送后会提醒
发送失败
发送时会加密。
只有 CI 绿了才能合并
只有构建成功才发布
只测了一部分。
只要测试通过就能合
只要部署成功就行
只跑了一部分测试。
只过了 5 个
合并后会自动部署。
同事修好了
同事发了
同事已提交
同事已部署迁移
同事推了
同事说已经修好了
同事说迁移已上线
同步任务没安排
同步每小时安排一次
哪怕已上线也要观察
哪怕测试全绿也可能有 bug
固定的宽度
备份下载后恢复
备份每晚下载
备份没下载
大部分测试通过。
她发了
她发了邮件
她已提交
好了吗
好了没
如果 CI ok 就合
如果 pytest 通过就合并
如果 pytest 通过就推送
如果 ruff 通过就提交
如果 worker 部署好了就告诉我
如果内存泄漏修好了就发版
如果分页 bug 修好了就发版
如果发票发了就标记
如果已提交就推送
如果推上去了告诉我
如果搞定了告诉我
如果迁移部署好了就告诉我
如果通过就合并
如果部署好了告诉我
如果部署成功就通知我
如果配置保存了就重载
字段 `saved` 表示已保存
字段 `已发送` 表示状态。
存下来以后再传
存不了
存了吗
官方修复了
官方文档说已修复。
官网还没上线
定时任务我没设。
定时任务没设
定时任务设好了吗
定时迁移没设
客户已确认
客户看了
客户说收到了
对方已回复
导不出来
小李已部署
小王修好了
小王已修复
就算 pytest 通过也要看日志
就算修好了也要回归
就算推送成功也不代表部署了
就算迁移已上线也要观察
崩溃的原因是消息发送了两次。
崩溃的问题没解决。
已下载的文件可以删除
已下载的模型放在 models/。
已保存的文件在这里
已保存的草稿在这里。
已保存的计划列在这里
已发布的版本不能删
已发送的消息可以撤回。
已推送的提交不要改
已提交的代码不能改
已部署的服务可以回滚
已部署的迁移会记录
已验证的账号有徽章。
帮我发一下
帮我存一下
帮我查一下
张三修好了分页 bug
张三推了
张三说 pytest 通过了
归档下载后解压
归档在启动时下载
归档没下载
待会儿提交
待测试通过后合并
得修一下
我会发给你
我先修一下
我先跑测试
我去下载备份
我去下载归档
我去保存
我去保存计划
我去保存配置
我去修分页 bug
我去发发票
我去发更新日志
我去安排同步
我去安排迁移
我去推
我去推送热修
我去推送迁移
我去提交
我去提交热修
我去提交迁移
我去查表结构
我去查迁移脚本
我去渲染预告
我去渲染预告片
我去部署 worker
我去部署迁移
我去验证热修
我去验证迁移
我可以帮你提交。
我可以推送。
我可以部署。
我将推送
我想先跑一遍测试。
我想先验证一下。
我打算今天上线。
我接下来修这个 bug。
我改了默认值。
我来修
我来修内存泄漏
我没下载。
我没保存。
我没回复。
我没推。
我没提交。
我没查文档。
我没核对。
我没测。
我没看代码。
我没看日志。
我没确认。
我没设定时任务。
我没跑。
我没部署。
我没验证。
我现在去部署
我还没发。
我还没推送。
我还没提交。
我还没部署。
我这就修
我这就发
截图没存
打包不过
打包失败
打算明天发
打算部署
报告每周发送一次。
报告没保存。
报告还没生成。
报错是因为已部署的版本太旧。
拉不下来
按钮显示已保存
接下来保存
接下来修内存泄漏
接下来部署
接下来部署 worker
接下来验证
推上去了吗
推上去以后告诉我
推不上去
推了吗
推了吗？
推送之后会触发 CI
推送后 CI 会跑。
推送被拒绝
推送还没完成
提交不了
提交了吗？
提交了没
提交后会跑 CI。
提交后再推送
提交失败
提交记录保存在 git 里。
提示"已保存"。
提示「发票已发」
提醒我还没设。
搞定了吗
搞定以后告诉我
摘要每天早上发送
支持定时发送。
数据会写入磁盘
数据保存在本地。
数据写入了数据库的旧表所以报错
数据库部署在内网。
数据集还没下载。
文件下载到缓存目录。
文件会下载到本地
文件没下载。
文档没上线
文档说测试通过。
新版本没上线。
既没提交也没推送。
日志保存在 `logs/`。
日志写入磁盘。
日志打印 `saved`。
日志打印 `已部署`
日志打印 `迁移已部署`
明天上线
是否已部署？
更新日志发了吗
更新日志没发
有 3 个失败
有测试失败
服务还没上线。
未修复
未能修复
未能推送
未能部署
未解决
本地没跑。
机器人已提交
李四修好了
李四已保存计划
李四已推送
李四提交了
李四部署了
构建不 ok
构建失败
构建成功不代表能用
构建成功不等于能跑
构建成功之后再发布
构建成功了吗
构建成功只是因为缓存。
构建成功，但有 3 个错误。
构建还没好
查过了吗
标签写着已验证
横幅提示「已保存」
正在下载
正在修复
正在推送
正在推送迁移
正在部署
正在部署迁移
每天定时发布
每次提交都会触发 CI。
每次部署都会重启
没 grep
没 pass
没上线
没下好
没下完
没下载。
没下载完
没保存
没保存。
没修
没修内存泄漏
没修复
没写入
没写完
没加提醒
没发
没发出去
没发布到 PyPI。
没发给你。
没回
没回复。
没回复卡罗尔
没处理
没存
没存下来
没完事
没定时
没导出
没导出。
没干掉
没弄好
没打 tag
没扫
没推
没推上去
没提交
没提交上
没提交也没推送。
没搞完
没搞定
没摆平
没有修
没有全部通过
没有测过
没有跑通
没查
没查完
没查表结构
没核对
没核过
没测
没测热修
没测迁移
没测通
没渲好
没渲染完
没看
没看完
没看文档
没看迁移脚本
没私信
没翻
没能修好
没解决
没设提醒
没试
没试过
没读完
没跑
没跑过测试
没跑通
没通过
没部署
没部署到 staging。
没验证
没验证热修
没验证迁移
没验过
测试不 OK
测试全挂了
测试全绿不代表没问题
测试同事说通过了
测试挂了
测试没 OK
测试没过
测试没通过，还没推送。
测试说修好了
测试过了再合并
测试过了吗？
测试通过了没
测试通过是因为 mock 写死了返回值。
消息会发送到队列
消息发送了两次导致重复
消息每天定时发送。
消息由 worker 发送。
渲染不了
渲染中
渲染没好
渲染还没完
热修推送了吗
热修推送后再部署
热修没发布
热修没推送
热修还没提交
片子还没好
王五已发更新日志
王五已验证
王五部署了
用户下完了
用户说修好了
界面显示「已保存」
登录的 bug 没修好。
看了吗
看板显示已部署的版本。
确认一下是否推送成功
社区修复了
稍后推送
稍后部署
等 CI 绿了再合并
等 CI 绿了再合并 PR
等 CI 绿灯再合
等 worker 部署好再测试
等一下再推
等下发给你
等你确认后我再推送。
等内存泄漏修好再发版
等推上去再说
等构建好了再部署
等测试通过再合并
等迁移上线再通知
等部署完成再切流
等验证通过再说
类型检查没通过。
系统会自动保存草稿。
系统自动保存
组件渲染了两次造成闪烁
结果没写入。
维护者已修复。
绿了吗
缓存保存到了错误路径
编不过
编译不过
编译失败
编译报错
编译过了吗
编译还没过
老张推送了
老板说测试通过了
脚本会把日志写入文件。
脚本把文件下载到缓存。
草稿自动保存。
表结构在启动时检查
要不要推送？
要修一下
要先验证
要存吗
要我推送吗。
要推吗
要提交
要是修啦就关单
要是编译通过就发布
要是部署失败就回滚
要部署
要部署吗
计划上线
计划下周上线
计划没保存
记得保存
记得存
记得推
记得推送
记得提交
记得验证
试过了吗
该字段保存在 Redis 里。
请你部署
请保存
请修复
请帮我查一下
请推一下
请推送
请提交
请核对
请检查是否已保存
请求被发送到了旧地址
请确保 pytest 通过
请确保已提交
请确保构建通过
请确认 CI 全绿
请确认 pytest 通过
请确认 ruff 通过
请确认 worker 已部署
请确认内存泄漏修好了
请确认发票已发
请确认已提交迁移
请确认是否修好
请确认测试通过
请确认热修已推送
请确认计划已保存
请确认迁移已部署
请确认部署成功
请确认配置已保存
请部署
请验证
超时问题没解决
跑不通
迁移上线了吗
迁移在合并时部署
迁移推送了吗
迁移推送后再部署
迁移没推送
迁移没提交
迁移没部署
迁移还没上线
运维上线了
运维已上线
运维已推送迁移
运维说部署成功了
运维部署好了
还卡
还在报错
还得验证
还报错
还挂
还有失败
还没 commit
还没 push
还没上线
还没上线。
还没下载
还没保存
还没修好
还没修完
还没发
还没发布。
还没推送上去
还没推送，CI 也没绿。
还没改好，测试也没过。
还没有 commit。
还没有部署
还没测试
还没渲染
还没解决
还没跑测试
还没验证
还没验证。
还要修一下登录的崩溃。
还要测试
还需要修复
这个 bug 是因为文件保存到了错误目录。
这个 bug 还没修。
这个接口负责发送邮件。
这个服务部署在 k8s 上。
这就部署
通了吗
通过不代表没问题
通过后再合并
邮件我没发。
邮件没发
邮件还没发。
部分测试没过
部分测试通过。
部署上去之后验证
部署不上去
部署不了
部署中
部署了吗
部署了吗？
部署后再验证
部署好了吗
部署成功不代表没 bug
部署没成功
部署还没好
都没 pass
配置保存了吗
配置保存在 `config.yaml`。
配置每次改动都会保存
配置没保存
配置还没保存
重构了解析器。
问题没解决
需要我部署吗？
需要提交
需要部署
需要验证
页面上写着"部署成功"。
页面在服务端渲染。
页面按需渲染
页面显示已发布
页面闪烁是因为组件渲染了两次。
预告没渲染
预告渲染好后上传
预告片在夜里渲染
预告片没渲染
预告片渲染好后上传
马上修
马上推送
验证过了吗
验证通过才能合并
麻烦修一下
麻烦推送
麻烦确认一下是否已发送
麻烦部署一下
""".splitlines()


@pytest.mark.parametrize("text", CLAIMS)
def test_is_a_claim(text):
    assert rules.find_claims(text), text


@pytest.mark.parametrize("text", NOT_CLAIMS)
def test_is_not_a_claim(text):
    assert not rules.find_claims(text), text
