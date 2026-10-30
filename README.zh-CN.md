# honestly

[![tests](https://github.com/kennywu411-dev/honestly/actions/workflows/tests.yml/badge.svg)](https://github.com/kennywu411-dev/honestly/actions/workflows/tests.yml) [![PyPI](https://img.shields.io/pypi/v/honestly)](https://pypi.org/project/honestly/) ![python](https://img.shields.io/badge/python-3.9%2B-blue) ![deps](https://img.shields.io/badge/dependencies-none-success)

**AI 编程助手报告的"测试通过、已修复、已发送、已部署"，有一部分从未实际执行。`honestly` 在这句话写出来的那一刻，核对这一轮记录里有没有对应的动作，没有就拦下回复。**

![honestly：AI 助手说「测试通过了」，它真的跑了吗？](https://raw.githubusercontent.com/kennywu411-dev/honestly/main/assets/cover.zh.png)

## 它解决什么问题

助手改了 `login.py`，记得十分钟前测试是通过的，于是写下"修好了，12 个测试全部通过"。改完之后其实什么都没跑。这句话和真的一模一样，所以错误要到后面才暴露：CI 里、同事机器上、线上。"邮件已发给维护者""已部署到 staging""已保存到 report.csv""我查过文档了"也是同一回事。`honestly` 读取当前这一轮的记录，找到这句结论，在最后一次代码修改之后找对应的命令或工具调用，读它的输出，没有依据就拦下。全部是确定性规则，不调模型、不要 API key、不上传任何东西。

## 一分钟装好

```bash
pip install honestly            # Python 3.9+，只用标准库（pipx install honestly / uv tool install honestly 也行）
honestly guard install          # 往 ~/.claude/settings.json 写两个 hook（--dry-run 先看会写什么）
honestly doctor --lang zh       # 体检安装，并现场做两次自测
```

`doctor` 全部正常时最后几行是（直接敲 `honestly` 不带参数会打印一份导览）：

```
  ok   自测（代码）：伪造一句改完代码就说「All tests pass.」，没跑测试 → 已拦
  ok   自测（非代码）：伪造一句「I've sent you the report.」，没有发送动作 → 已拦
一切正常：guard 已装上并且能拦。
```

其他助手。Codex 已在真实机器上端到端验证（Codex CLI 0.163：guard 拒绝了接管道的 `pytest`，并写明了模型和项目）；Cursor 和 Gemini CLI 按各家 hook 文档实现，在有用户确认之前标为实验性（见[它不是什么](#它不是什么)）：

```bash
honestly guard install --agent codex     # ~/.codex/hooks.json（Codex 会要求你在 /hooks 里批准一次）
honestly guard install --agent cursor    # ~/.cursor/hooks.json（需要开启 Cursor 的 agent transcripts）
honestly guard install --agent gemini    # ~/.gemini/settings.json
honestly guard status                    # 四家一起看；guard uninstall [--agent …] 只删 honestly 自己写的条目
```

## 拦到时你看到什么

![honestly 拦下一条没跑测试的"测试通过"](https://raw.githubusercontent.com/kennywu411-dev/honestly/main/assets/demo.zh.gif)

hook 往聊天窗口写一句大白话，用对话本身的语言，写明是哪个助手、哪个模型、哪个项目、哪段对话：

```
⚠️ honestly 拦了一下：Claude Code（claude-opus-5-5）在「docpilot」项目回复「修一下登录接口的 bug」这个问题时
说「登录接口的 bug 已修复，12 个测试全部通过」，但改完 login.py 之后没有跑过任何检查。已经要求它先跑了再说。
```

助手被要求现在就去做并报告真实输出，做不了就把那句话改成"已修改，尚未验证"。它的下一条回复第一行会用加粗写明：为什么被拦、补跑的结果是什么。测试要是失败，它看到的是失败，就会去改代码，而不是告诉你已经搞定。

第二个 hook 在每条 shell 命令执行前检查：测试或构建命令接了 `| tail` `| head` `| grep` `| awk` `| wc` `| tee` 又没加 `set -o pipefail`，退出码就是最后那个命令的，失败会显示得像通过。这种命令会被拒绝，并附上一行改法。一条回复里有好几句没依据时，提示会说明还有几句。

hook 不会碍事：超过 8 MB 的记录只从末尾读（200 MB 的会话和小会话一样快）；它自己出了任何内部错误都只写进 `~/.honestly/hook-errors.log` 然后放行，`honestly doctor` 会显示出来。

```bash
honestly catches --lang zh    # 这周拦了什么，按项目和助手分
honestly catches --card       # 同样的内容做成一张 1200×630 的图，可以直接发
honestly guard notify on      # 每次拦截同时弹桌面通知（macOS、Linux、Windows）
```

每次拦截都追加到 `~/.honestly/catches.jsonl`，不看终端也能回头看"本来会以'搞定了'的样子到你眼前的"都有哪些。

## 它拦什么

十四类结论。每一类都定义了什么算依据、输出必须说什么。

| 助手写的是 | 记录里必须有（在最后一次代码修改之后） |
|---|---|
| 测试通过、12 passed、全绿 | 测试命令（pytest、unittest、Jest、Vitest、Mocha、Go、Cargo、Maven、Gradle、.NET、Swift、Flutter……），且最后一行汇总是 passed 不是 failed |
| lint / 类型检查 / 检查通过 | tsc、ESLint、Ruff、mypy、pyright、Clippy、go vet、golangci-lint、Biome、Prettier --check……且结果干净 |
| 构建通过、能编译 | 成功的构建或编译命令 |
| 已渲染、视频导出了 | ffmpeg、ffprobe、remotion、hyperframes render…… |
| 已推送、已提交到 Kaggle | `git push`、`kaggle … push/submit`，且输出里没有 rejected |
| 已 commit、打了 tag | 修改之后的 `git commit` / `git tag` |
| 修好了、解决了、现在能用了 | 修改之后的测试、检查或渲染；随便跑个脚本不算修好的证据 |
| 已发送、已回复、"图发你了" | 发送/回复/SendUserFile 工具、`gh pr comment`、sendmail…… |
| 已部署、已发布、已上线 | vercel、fly、kubectl apply、docker push、firebase deploy、`gh release create`、twine upload…… |
| 已下载 | curl -o、wget、yt-dlp、git clone、hf_hub_download、brew install……或列出文件的 ls |
| 已保存 / 已导出到某文件 | 写入了这个文件本身，或指向它的重定向、`-o` |
| 查过了、核对过、文档里确认了 | Read、Grep、WebSearch、WebFetch、浏览器工具、grep/curl/gh…… |
| 定时任务设好了 | CronCreate、定时任务工具、crontab、launchctl |
| 验证过、跑通了、实测通过 | 任何运行或检查；句子里点名了某个工具（docker、pytest……）就必须出现那个工具 |

它刻意不标的：计划（"我接下来跑测试"）、提问、引用、代码块、标题和表格、主语是用户的句子（"你发给我的……"）、状态描述（"数据只保存在本地"）、文献标题（"fixed bed reactor"）、只是总结上一轮的回复。看不到的东西（远程 CI、浏览器操作、你自己的终端）一律记为"无法核实"，不会变成冤枉的"无支撑"。

子代理做的事也算：`Agent` 调用里跑的测试是主助手结论的依据，后台命令的输出从任务文件里读回来。和主助手并行运行的后台子代理所做的修改，不会让主助手自己的检查作废。

## 按你的习惯调

一次误拦的代价应该是一条命令，不是等下一版。

```bash
honestly ignore "fixed bed reactor"      # 含这个短语的句子永远不算结论（--remove 删掉，--list 查看）
honestly config strictness strict        # 严格：只看截图判断的"修好了"也拦
honestly config strictness lenient       # 宽松：只拦"跑了检查但检查失败"的
honestly config verify "make verify"     # 你自己的命令算作跑测试
honestly config off sent,checked         # 关掉某几类（config on … 再打开）
honestly config language zh              # 固定提示语言（auto：跟随对话）
honestly config                          # 看当前生效的全部设置
```

设置在 `~/.honestly/config.json`。加 `--project` 写到 `./.honestly.json`，对这个仓库单独生效，可以提交进仓库让整个团队共用一套规则。

从源头减少拦截，往助手读的项目说明里加一小段"先验证再下结论"：

```bash
honestly rule install --lang zh          # 写进 CLAUDE.md；--agent codex → AGENTS.md，gemini → GEMINI.md，cursor → .cursor/rules/
```

觉得某次拦错了，一条命令把它整理成可以直接贴进 issue 的文本，路径和密钥已脱敏：

```bash
honestly feedback                        # 最近一次；honestly feedback 2 是上一次；--issue 多给一个预填好的链接
```

## 审计历史记录

同一套规则跑一遍本机所有历史会话，给你一个数。

```bash
honestly audit                # 读 Claude Code、Codex、Cursor、Gemini CLI 的记录，分叉会话去重
honestly audit --since 30d    # 只看最近 30 天（也支持 8w、3m）；--project 名字 只看一个项目
honestly explain 3            # 第 3 条被标记结论的完整时间线：修改、之后的每个工具、输出
honestly share                # 在 ~/.honestly/ 生成分享卡（SVG；有 Chrome、Edge 或 rsvg-convert 时同时出 PNG）
```

![honestly audit 在作者会话上的结果](https://raw.githubusercontent.com/kennywu411-dev/honestly/main/assets/hero.png)

报告按助手和模型、按项目、按周分项（换了模型或加了规则文件有没有变化一眼能看出来），并列出每一条"无法核实"的原因。上面是作者自己在 0.5.3 规则下的数字：125 个会话，352 条可判定结论中 334 条已验证。代码类：167 条已验证、16 条标记、17 条无法核实、10 条只凭截图判断。非代码类：167 条已验证、2 条标记、63 条无法核实。另一个团队的记录里也有同样的模式：一条 GitHub issue 报告了 150 个 Claude Code 会话里的 357 条"测试通过"，[80 条背后没有运行](https://github.com/anthropics/claude-code/issues/104504)（issue 自己说明这只是一个团队的会话，不是总体估计）；基准测试在 ML 任务上也看到了（[57% 的前沿智能体运行会走预埋的捷径](https://arxiv.org/abs/2608.30724)，叮嘱它别这么做几乎没用）。

## 一条结论是怎么判的

1. **范围：一轮。** 你的提问到它的回复之间做的所有事，包括子代理做的。
2. **最后一次代码修改。** `Edit`/`Write` 工具、`sed -i`、`cat > file`、写文件的 heredoc。改文档、日志、笔记、记忆、`.env`、临时目录、agent 状态文件不算。
3. **之后有没有对应的检查。** 见上表。`verify_commands` 里的自定义命令算测试。
4. **输出说了什么。** 最后一行汇总说了算：`12 passed` 支持结论，`2 failed` 反驳，`fail 0` 是通过；一个测试都没收集到的运行（`no tests ran`、`Ran 0 tests`、`0 passing`、`[no tests to run]`）什么都不支持，退出码是绿的也一样。缩小范围的运行（`pytest -k`、单个文件）只在结论写了同样的数量时才算。最后一次检查没说通过还是失败（比如只是读 CI 状态），就用前面最近一次说了的。
5. **非代码结论**看整轮加上一轮（回复经常开头先汇报上一轮做了什么），而且必须对得上：说"已保存到 report.csv"就得写过 `report.csv`；说"图发你了"得有发送工具，脚本正文里出现 mail 命令不算。
6. **视觉修复。** "重叠修好了"后面跟着渲染和看截图，记为"弱"：单独列出，不算验证也不算无支撑（只有 `strictness strict` 才拦）。
7. **看不见的一律"无法核实"**：远程运行（CI、Kaggle）、浏览器操作、你自己的终端、其他会话、没有捕获的输出。

分叉的会话会去重，同一轮只算一次。全部规则和排除项在 [`src/honestly/rules.py`](https://github.com/kennywu411-dev/honestly/blob/main/src/honestly/rules.py) 和 [`src/honestly/noncode.py`](https://github.com/kennywu411-dev/honestly/blob/main/src/honestly/noncode.py)。

## 精确率

每次改规则之后都做一轮标注：审计标记出来的每一条结论都标两遍。第一遍由作者读完整的一轮来标；第二遍由一个大模型 agent 只看标注表（那句话、最后一次修改、之后的工具、审计给的理由）来标，看不到第一遍的结果。第二遍是盲标、也便宜，但不是第二个人：它抓出过作者的几处疏漏，也和标注表有同样的盲区。分母比标记条数少，是因为去掉了"不确定"和分叉会话的重复项。

| 轮次 | 标记为无支撑 | 第一遍精确率（作者） | 第二遍精确率（大模型 agent，盲标） | 之后修了什么 |
|---|---|---|---|---|
| 1 | 38 | 18/32（56%） | 22/32（69%） | 文档/日志/记忆的修改被当成代码修改；带版本号的 `hyperframes@x check` 没识别 |
| 2 | 22 | 10/19（53%） | 11/21（52%） | 变量路径、`.agent/state.json`、heredoc 正文；按最后一行汇总判输出 |
| 6 | 12 | 12/12 | 11/11（+1 不确定） | 识别引号的多行切句；写文件的 heredoc 永远不算验证 |
| 非代码 | 41 | 0/41 | 5/41 | 总结句、上一轮的工作、后台任务都被标了；改成结构性规则后同一批记录上 0 条标记 |
| 0.5.3（现行规则） | 18 | 14/18 正确、4 不确定、0 错 | 未做 | 0.5.3 的修复；只标了一遍，非盲标 |

第 3 到 5 轮、0.5.3 这一遍和召回率研究见 [docs/precision.md](https://github.com/kennywu411-dev/honestly/blob/main/docs/precision.md)。**召回率：**对 66 条审计没有标记的结论做了同样的标注，找到 5 处不同的漏判，4 处已修；`honestly` 仍然宁可"无法核实"也不冤枉。最早的误报来自另一台机器的记录（英文文献标题里的 "fixed bed reactor"、Windows 编码），最早的漏判来自一次现场演示（脚本正文里的 `curl` 被当成了发送）；这三件事现在都是回归测试。眼下最有用的贡献是 Python、JavaScript 之外技术栈上的一条带标注的结论：开一个 issue，写上那句话和那一轮做了什么。

## 它不是什么

- **不判断代码对不对，也不判断测试够不够。**"已验证"只表示对应的检查在修改之后跑过、输出和那句话一致，不代表代码是对的、也不代表测试覆盖了改动。
- **不是排行榜。**按模型的表只统计你自己的会话。
- **与 Anthropic、OpenAI、Cursor、Google 无关。**独立项目，MIT 许可。
- **Cursor 和 Gemini CLI 的拦截是实验性的。**它们的 hook 按各家文档实现，测试覆盖了文档里的输入输出格式，但还没有在真实机器上跑过；Codex 的 hook 字段和 Claude Code 完全一致，已真机验证；`honestly guard install --agent … --dry-run` 会把要写的内容原样打出来。Cursor 给 hook 看的记录只有工具输入没有工具输出，所以在 Cursor 下一条结论可能是"无支撑"（根本没检查），但不会是"被反驳"。
- **不上传任何东西。**唯一的联网动作是 `honestly catches` 或 `honestly doctor` 每天最多问一次 PyPI 有没有新版，有就印一行 `pip install -U honestly`；hook 本身从不联网。设 `HONESTLY_NO_UPDATE_CHECK=1` 可关掉。
- CI 覆盖 Linux、macOS、Windows 和 Python 3.9–3.13，132 个测试。解析过的会话缓存在 `~/.honestly/cache/`（按文件、规则、配置失效；`--no-cache` 跳过）。规则先按一个人的会话（Python、JS、视频工具、Kaggle）调，再用另外两台机器的记录校正；其他技术栈只有合成测试覆盖。预期会遇到一两次误拦：`honestly ignore` 当场消掉，`honestly feedback` 一条命令生成可以直接提交的 issue。旧包名 `sober-cli`。

## 相关项目

[groundtruth](https://github.com/vnmoorthy/groundtruth) 用关键词匹配拦没有依据的"完成"；[superpowers](https://github.com/obra/superpowers) 在 skill 里要求验证（提示词层面）。`honestly` 的不同在于读命令的*输出*、覆盖非代码结论、读子代理的记录、跨助手和模型给历史打分，以及看不见的一律不算。

English README: [README.md](https://github.com/kennywu411-dev/honestly/blob/main/README.md).
