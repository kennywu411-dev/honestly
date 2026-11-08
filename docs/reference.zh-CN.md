# 参考

版本、存了什么、退出码、类别、设置和输出格式。English: [reference.md](reference.md).

## 版本与弃用

版本号是 `MAJOR.MINOR.PATCH`。1.0 之前，MINOR 起 MAJOR 的作用。

| 发布类型 | 可以包含 | 不可以包含 |
|---|---|---|
| PATCH | 修一处误拦或一处漏判；改错的文字；修崩溃 | 关掉某个类别；改变某个严格度拦什么；改变默认值、退出码、参数或输出字段 |
| MINOR | 以上都可以，且在 changelog 最前面的 **Behaviour changes** 下列出 | 不按下面的通知就删掉东西 |

**任何发布都不能让默认放过更多虚假结论。** `tests/test_must_catch.py` 列出了必须抓住的谎话，它必须通过。从这个清单里拿掉一条，属于要在 changelog 里写明并说明理由的决定，只能放在 MINOR 发布里。

**某次发布被证明有错时，** 它会在 PyPI 上被 yank，下一个 PATCH 恢复之前的行为，changelog 写明要避开哪个版本。这条规则来自 0.7.3 和 0.7.4：0.7.3 在一个 patch 发布里停止拦截代码以外的结论，几小时后 0.7.4 又撤回了。

**弃用。** 要去掉的命令、参数、设置或输出字段，至少再保留一个 MINOR 发布，运行时在 stderr 打印警告（绝不写进 stdout 的 JSON），并在 changelog 的 **Deprecated** 下列出。Python 版本只在 MINOR 发布里停止支持，且提前一个 MINOR 发布通知。

## 支持的版本

| 内容 | 支持范围 |
|---|---|
| honestly | PyPI 上的最新版本。修复只进最新版，不回到旧版 |
| Python | 3.9 到 3.13 |
| 系统 | Linux、macOS、Windows：CI 在三者上都跑测试 |

| 助手 | Hook | 依据 |
|---|---|---|
| Claude Code | 支持 | 真实会话 |
| Codex | 支持 | 在 Codex CLI 0.163 上真实跑过 |
| Gemini CLI | 实验性 | 真实 CLI（0.67），模型接口换成本地替身；还没有真实模型的会话 |
| Cursor | 实验性 | 按官方文档实现，测试覆盖文档里的输入输出；没有在真实机器上跑过 |

安全问题的报告方式见 [SECURITY.md](../SECURITY.md)。

## 存了什么，怎么删

所有内容都在 `~/.honestly` 下，只有你的账户能读（文件夹 0700，文件 0600；Windows 上由用户目录自身的权限保护）。这里的内容都不会发到任何地方。hook 从不联网。`honestly catches` 和 `honestly doctor` 每天最多问一次 pypi.org 有没有新版（失败时每 6 小时一次），这个请求不包含你工作的任何内容。设 `HONESTLY_NO_UPDATE_CHECK=1` 可关掉。没有遥测。

| 文件 | 内容 |
|---|---|
| `~/.honestly/catches.jsonl` | 每次拦截一行：时间、助手、模型、项目路径、你的提问前 80 个字符、那句结论、原因、命令、提示内容、最后几个工具。写入前会抹掉 token、家目录路径和邮箱；这是模式匹配，不能保证抹干净，所以请当作私密文件。到 4 MB 时轮转 |
| `~/.honestly/cache/` | 每个会话的判定结果，带回复和命令输出的引文，同样先抹掉敏感内容。90 天没用过的条目会被删除；`honestly audit --clear-cache` 或 `honestly purge` 可以清空 |
| `~/.honestly/hook-errors.log` | 内部错误和 hook 跳过的输入。到 4 MB 时轮转 |
| `~/.honestly/config.json`、`trusted.json` | 你的设置，以及你信任的项目文件 |
| `~/.honestly/notices.json` | 哪些一行提示你已经看过 |
| `~/.honestly/notify`、`notify.last` | 通知已开；上一次通知的时间 |
| `~/.honestly/update-check.json` | 上次检查 PyPI 的时间和查到的版本 |
| `~/.honestly/honestly-card.*`、`honestly-catches.*` | 你要求生成的卡片 |
| `<设置文件>.bak-honestly-<时间>` | `guard install` 或 `uninstall` 改动之前的助手设置文件 |
| `.honestly.json`，以及 `CLAUDE.md`、`AGENTS.md`、`GEMINI.md` 或 `.cursor/rules/honestly.mdc` 里的一段 | 只出现在你运行过 `--project` 或 `honestly rule install` 的项目里 |

全部删除：

```bash
honestly guard uninstall --agent all     # 从每个助手的设置里拿掉 honestly 的条目
honestly rule uninstall                  # 在每个装过规则的项目里运行（其他助手加 --agent）
honestly purge --all                     # 删除整个 ~/.honestly；要在你自己的终端里运行
pip uninstall honestly
```

插件在 Claude Code 里卸载。只运行 `honestly purge` 会删除记录下来的内容、保留设置；`--dry-run` 先列出来。清除要在你自己的终端里运行，因为 guard 拦下了什么的记录不该由助手来抹掉。

## 退出码

所有命令被中断时退出 130，读取输出的一方关闭时退出 141（`honestly audit | head`）。

| 命令 | 0 | 1 | 2 |
|---|---|---|---|
| `honestly hook stop`、`hook pre` | 总是 0。判定结果在 stdout 的 JSON 里，内部错误不能挡住助手 | | |
| `pr-note --check` | 最后一次修改之后有测试通过，或这段时间里没有 agent 改过代码 | 其他情况（见下），或出错 | 参数错误 |
| `pr-note` | 证据块已写出 | 不是仓库、`--base` 或 `--since` 有误、没有 `gh`、没有 pull request | 参数错误 |
| `doctor` | 没有问题 | 至少一个问题 | 参数错误 |
| `audit`、`share` | 报告已写出，包括空报告 | 文件写不了 | `--since` 或参数错误 |
| `explain`、`feedback` | 已显示，或没有可显示的 | 编号超出范围 | 参数错误 |
| `catches` | 报告已写出，包括空报告 | 记录读不了 | `--days` 小于 1 |
| `purge` | 已完成，或没有可删的 | 不是在你自己的终端里运行 | 参数错误 |
| `config`、`ignore` | 已完成，或本来就是这样 | 设置文件损坏，所以什么都没改 | 值或类别不对 |
| `guard` | 已完成，或本来就是这样 | 读不了 Claude Code 的设置文件 | 参数错误 |

`pr-note --check` 在没有 agent 修改时返回 0，是因为这时 agent 没有什么可声称的。这不代表代码测过。证据块会写明是哪种情况：

| 标题 | 含义 | `--check` |
|---|---|---|
| ✅ Tests ran after the last code edit and passed | 最后一次修改之后完整跑过测试并通过，且之后没有代码文件被写入 | 0 |
| ℹ️ No code edit by an agent in this window | 没有要检查的 | 0 |
| ❌ The last test run ... failed | | 1 |
| ❌ A test run ... failed, and no later run covered the same tests | 只有同一个工具跑相同或更大范围的测试才能消除失败 | 1 |
| ⚠️ Only a narrowed test run ran | `-k`、单个文件、更深的文件夹、`--lf` | 1 |
| ⚠️ No test ran ..., only a build or lint check | | 1 |
| ⚠️ No test or build ran | | 1 |
| ⚠️ A test ran ..., but its output shows no pass/fail line | 管道藏住了结果、读的是 CI 状态，或 Cursor（不记录输出） | 1 |
| ⚠️ The test run ... collected no tests | | 1 |
| ⚠️ Code files were written or removed after the last test | 有人改过、格式化工具、`git pull`、合并或切换分支。请重新跑测试 | 1 |
| ⚠️ The last code edit is not in this working tree | 这些证据可能属于另一个分支 | 1 |

证据块读的是本机的会话记录和当前目录树的文件。它判断不了测试之后写入的文件内容是否真的变了，也看不到在别的机器上做的工作。

## 类别

`honestly config` 总是打印当前的清单。`honestly config off` 和 `on` 用这些名字。每一类需要什么依据，见 README 的表。

| 名字 | 助手说的是 |
|---|---|
| `tests_pass` | 测试通过 |
| `checks_pass` | lint、类型检查或检查通过 |
| `build_ok` | 构建成功、能编译 |
| `rendered` | 渲染完成 |
| `pushed` | 已推送或已提交到平台 |
| `committed` | 已 commit 或打了 tag |
| `fixed` | 修好了 |
| `sent` | 已发送、发了邮件、已发布消息或已回复 |
| `deployed` | 已部署、已发布或已上线 |
| `downloaded` | 已下载 |
| `saved` | 已保存或导出到某文件 |
| `scheduled` | 定时任务设好了 |
| `checked` | 查过了或核对过 |
| `verified` | 验证过或端到端测过 |

## 设置

两个 JSON 文件，都是可选的。`~/.honestly/config.json` 处处生效。`.honestly.json` 只对一个项目生效：从当前文件夹到仓库根目录之间最近的那个；不在仓库里时只看当前文件夹。

| 键 | 取值 | 默认 | 设置方式 | 两个文件都有时 |
|---|---|---|---|---|
| `strictness` | `strict`、`normal`、`lenient` | `normal` | `honestly config strictness strict` | 更严的优先；项目要放宽须先被信任 |
| `language` | `auto`、`zh`、`en` | `auto` | `honestly config language zh` | 以项目的为准 |
| `ignore` | 短语；含其中一个的句子永远不算结论 | 无 | `honestly ignore "短语"`、`--remove`、`--list` | 两个清单都生效，项目的要先被信任 |
| `verify_commands` | 算作跑测试的命令 | 无 | `honestly config verify "make verify"`、`unverify` | 两个清单都生效，项目的要先被信任 |
| `off` | 类别名 | 无 | `honestly config off sent,checked`、`on` | 两个清单都生效，项目的要先被信任 |

这些命令加 `--project` 就写到项目的文件里。

**仓库不能自己放宽规则。** 项目文件是跟着代码来的，所以其中的 `off`、`ignore`、`verify_commands` 和更低的 `strictness` 都会被忽略，并有一行提示，直到你在自己的终端里运行 `honestly trust`。它记录的是这个文件本身；文件一变，这些设置又会被忽略（`--list`、`--remove`）。`honestly doctor` 会列出项目文件放宽了什么。

**它也不强制任何事。** 清单是相加的，所以个人的 `off` 和 `ignore` 在项目里照样生效，项目也无法替关掉某个类别的人重新打开。

**`audit`** 用你的设置加上每个会话自己项目的文件来判定，不管你从哪里运行。不知道所在文件夹的会话（Cursor）只用你的设置。**`pr-note`** 用你的设置加上这个仓库的文件。

不是合法 JSON 的文件会被忽略，`honestly config` 和 `honestly doctor` 会说明。修改设置的命令不会碰它。

| 严格度 | 拦下回复的情况 | 拒绝命令的情况 |
|---|---|---|
| `strict` | 没有依据或失败的结论，以及只看截图判断的修复 | 管道藏住一次运行的结果，包括缩小范围的运行上的过滤或 `head` |
| `normal` | 没有依据或失败的结论 | 管道藏住一次完整运行的结果 |
| `lenient` | 只拦输出里显示的失败。命令报错退出但没打印可识别的失败时不拦 | 从不 |

**提示语言。** 用 `auto` 时，对话任何一方用中文，提示就用中文，否则用英文。英文句子里的中文文件名不算。没有可读的内容时（`doctor`、`catches`），由系统语言决定：`LC_ALL`、`LC_MESSAGES`、`LANG`，然后是 macOS 或 Windows 的语言。hook 提示、`catches` 和 `doctor` 有两种语言，`rule install` 用 `--lang`。`audit`、`explain`、`share`、`feedback`、`pr-note`、`config`、`guard` 和卡片是英文。

| 环境变量 | 作用 |
|---|---|
| `CLAUDE_CONFIG_DIR` | Claude Code 存放设置和记录的位置 |
| `HONESTLY_NO_UPDATE_CHECK=1` | 不检查 PyPI。只有值 `1` 算数 |
| `HONESTLY_NOTIFY=1` | 打开通知，等同于 `honestly guard notify on` |

## 输出格式

格式遵守上面的规则：字段含义只在 MINOR 发布里改变，删除字段要先走弃用。任何发布都可能增加新字段。

`honestly audit --summary-json` 打印一个对象：

| 字段 | 含义 |
|---|---|
| `schema` | 这个格式的版本，现在是 1 |
| `total_claims` | 所有被读成结论的句子，包括只是总结之前工作的 |
| `claims_in_scope` | 报告统计的那些：`Claims checked` |
| `decided` | 已验证、无支撑和被反驳 |
| `rate` | 已验证除以可判定，0 到 1；没有可判定时为 `null` |
| `by_verdict`、`by_category` | 计数，用下面的判定名 |
| `sessions` | 读过的会话；有 `--project` 或 `--since` 时是其中有匹配结论的 |
| `sessions_read` | 读过的会话 |
| `duplicates_removed_forks` | 作为分叉会话里的副本被去掉的条数 |

`honestly audit --json FILE` 每条结论写一个对象：`session`、`turn`、`version`、`agent`、`model`、`ts`、`category`、`verdict`、`label`、`reason`、`claim`、`last_edit`、`tools_after_edit`、`context`、`verified_by`、`output`、`project`、`trace`。它原样引用回复和命令，请当作私密文件。

| `verdict` | `label`，即报告里的说法 |
|---|---|
| `backed` | verified |
| `unbacked` | unverified |
| `contradicted` | contradicted |
| `unverifiable` | could not check |
| `weak` | weak |
| `not_this_turn` | no edit this turn |
| `out_of_scope` | not audited |

`~/.honestly/catches.jsonl` 没有版本，不是稳定格式。
