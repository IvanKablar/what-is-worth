# What is Worth?

[English](README.md) · [Deutsch](README.de.md) · [Español](README.es.md) · **中文** · [日本語](README.ja.md) · [Русский](README.ru.md)

What is Worth? 显示 AI 编程助手消耗了多少 API 价值。它关注的不是自然月，而是订阅周期，即从一次每周重置到下一次。它还会为每个账户测算每周额度中一个百分点值多少美元。

目前支持 Claude Code。其他助手可以通过适配器加入。所有内容都在本地运行：无需账户，没有代理，不发送任何数据。唯一的网络请求是每天下载一次 LiteLLM 价格表。

## 功能

- **自每周重置以来的概览**，针对当前登录的账户：用量、API 价值、每个百分点的价值、速度，以及预计何时达到限额。
- **细分**：按日期、模型和项目。项目即 git 仓库，worktree 和子目录计入其主仓库。
- **所有账户一览表**，每个账户按自己的每周周期和重置时间显示。
- **套餐价格与 API 价值对比**：每个套餐的每周标价，以及倍数：每个百分点的 API 价值除以套餐中每个百分点的费用。
- **所有账户合计**：今天、本周、本月和全部历史。
- **往周**：按该账户的重置周期显示。
- **Claude Code 状态栏**：每周用量、重置以来的费用、每个百分点的价值、倒计时，以及本次会话和上一次请求的费用。
- **报表**：按日、周、月统计全部历史。
- **六种语言**：德语、英语、西班牙语、中文、日语和俄语。

状态栏示例：

```
本周 51% · 重置以来 US$8.04 · 重置 周一 01:00（剩余 3 天 7 小时） · 会话 US$24.12 · 本次请求 US$2.34
```

## 环境要求

- Python 3.11 或更高版本，无需其他软件包。
- Git，用于识别项目和发布版本。
- Claude Code，其记录保存在 `~/.claude/projects/`。

## 安装

1. 克隆仓库，例如到 `~/what-is-worth`。
2. 创建发布版本。它会把最新提交导出到 `~/.local/share/what-is-worth/app`：

   ```
   scripts/release.sh
   ```

3. 把 `wiw` 加入路径：

   ```
   ln -s ~/.local/share/what-is-worth/app/bin/wiw ~/.local/bin/wiw
   ```

4. 在 `~/.claude/settings.json` 中加入状态栏：

   ```json
   "statusLine": {
     "type": "command",
     "command": "/home/<用户>/.local/share/what-is-worth/app/bin/wiw statusline",
     "padding": 0
   }
   ```

5. 首次读取全部数据。约 2,700 份记录需要 10 到 20 秒：

   ```
   wiw sync
   ```

Claude Code 默认在 30 天后删除记录。如需保留历史，请在 `~/.claude/settings.json` 中把 `cleanupPeriodDays` 设得足够大。已读入账本的数据即使记录文件之后被删除也会保留。

## 使用

| 命令 | 作用 |
|---|---|
| `wiw` | 自上次每周重置以来的概览，等同于 `wiw overview` |
| `wiw overview --weeks 10` | 显示前十周的概览 |
| `wiw report day` | 每日费用，也可用 `week` 和 `month`，可加 `--since 2026-09-01` |
| `wiw sync` | 读取新数据，通常会自动进行 |
| `wiw sync --rebuild` | 重新读取现有记录，例如在读取规则变更后 |
| `wiw reprice` | 按当前价格表重新计算所有费用 |

在 Claude Code 中可用 `! wiw` 打开概览。不涉及模型，因此不消耗 token。

状态栏每次刷新只读取本会话的新内容。最多每五分钟还会在后台读取一次全部记录。

## 配置

| 变量 | 含义 | 默认值 |
|---|---|---|
| `WIW_LANG` | 语言：`de`、`en`、`es`、`zh`、`ja` 或 `ru` | 系统语言，否则为英语 |
| `WIW_DATA_DIR` | 账本和发布版本的位置 | `~/.local/share/what-is-worth` |
| `WIW_CONFIG_DIR` | 自定义价格的位置 | `~/.config/what-is-worth` |
| `WIW_CACHE_DIR` | 价格表缓存 | `~/.cache/what-is-worth` |
| `WIW_CLAUDE_DIRS` | 额外的 Claude 配置目录，用 `:` 分隔 | `~/.claude` 和 `CLAUDE_CONFIG_DIR` |

自定义价格（例如 LiteLLM 尚未收录的模型）写入 `~/.config/what-is-worth/prices.json`。键名与 LiteLLM 相同，价格按每个 token 计：

```json
{
  "claude-new-model": {
    "input_cost_per_token": 0.000004,
    "output_cost_per_token": 0.00002,
    "cache_read_input_token_cost": 0.0000002,
    "cache_creation_input_token_cost": 0.000005,
    "cache_creation_input_token_cost_above_1hr": 0.000008
  }
}
```

然后运行 `wiw reprice`。

## 计算方式

**数据来源。** Claude Code 把每个 API 回复及其 token 数写入每个会话的记录文件，子代理和工作流写入各自的文件。同一回复常出现多次。What is Worth? 按消息 ID 保留完整流式传输的那份，并优先采用主对话而非子代理中的重放。

**价格。** 费率来自 LiteLLM，涵盖输入、输出、缓存读取以及五分钟和一小时两种缓存时长。此外还包括快速模式的双倍价格、数据驻留 10% 的附加费、每 1,000 次 10 美元的网页搜索，以及长上下文分档。若提示超过阈值（例如 Haiku 5.5 超过 100,000 个 token），整个请求都按较高费率计费，而不只是超出部分。

**订阅周期与账户。** 只有状态栏能得知用量、重置时间和当前登录的账户，并在每次刷新时记录。每个回复归属于当时登录的账户。一次 `/login` 同时作用于所有正在运行的会话。

**每个百分点的价值。** 账户自本周期首次用量读数以来的费用，除以此后用量的增长。Claude Code 只报告整数百分比，因此在增长达到 5 个百分点后才显示该值，使舍入误差保持在约 20% 以下。

**一次请求的费用。** 会话中从一次输入到下一次输入之间的所有回复，包括子代理。

## 准确性

- **与 ccusage 对比：** 2026 年 8 月至 10 月，按月份和模型统计的 token 与费用完全一致。此后 What is Worth? 修正了 ccusage 仍存在的两个计数错误，影响约 0.01% 的费用。
- **费率：** 所有使用中的模型都已与 Anthropic 官方价格页面核对，表格位于 `scripts/official_prices.json`。
- **独立校验：** `scripts/verify_projects.py` 不使用程序代码重新计算全部记录，并按项目与账本比较。还可以加入 ccusage 导出：

  ```
  npx ccusage@latest claude session --json --offline > /tmp/cc.json
  python3 scripts/verify_projects.py /tmp/cc.json
  ```

- **与 Claude Code 自身计数器对比：** 每个会话的合计约低 1%，因为 Claude Code 不会把部分后台调用写入记录。

套餐价格为 claude.com/pricing 上不含税的标价：Pro 每月 20 美元，Max 5x 100 美元，Max 20x 200 美元。价格页面对 Max 只写“100 美元起”，因此 Max 20x 采用此前已知的价格。实际价格可能因币种、税费、按年付费和折扣而不同。

所有金额都是按标价计算的 API 等值。在 Pro 或 Max 订阅下，它们是参考值，而不是账单。

## 已知限制

- **账户仅自安装起记录。** 记录文件中不包含账户。首次状态栏刷新之前的费用显示为“无法归属”。
- **无状态栏时切换账户。** 如果登录后只使用 `claude -p` 或 IDE，切换会在下一次终端状态栏刷新时才被发现。
- **被拒绝的首次尝试。** 当一个模型在输出前拒绝、由另一个模型回答时，后备回复的价格计算正确。被拒绝的尝试是否收费取决于其类别，而记录中没有类别，因此不计入。
- **已删除的 worktree。** 在首次读取前已删除的 worktree 无法对应到仓库，会以文件夹名显示。
- **单台机器。** 每台机器维护自己的账本。

## 结构

```
src/whatisworth/
  model.py                 所有来源共用的记录：回复、请求、限额、账户
  sources/base.py          来源接口
  sources/claude_code.py   Claude Code 适配器
  ledger.py                SQLite 账本
  ingest.py                带锁的增量读取
  pricing.py               LiteLLM 价格及自定义价格
  projects.py              工作目录 → git 仓库
  insights.py              周期、账户、合计、每个百分点的价值
  statusline.py            状态栏
  cli.py                   命令
  i18n.py, format.py, locales/   语言与格式
```

账本保存 token 和原始事实。费用在读取时计算，可用 `wiw reprice` 重新计算。项目和账户只在分析时归属。新的来源（例如 Gemini）只需再写一个产生相同记录的适配器。

## 开发

```
python3 -m pytest -q tests
bin/wiw            # 运行工作副本
scripts/release.sh # 发布最新提交
```

状态栏和 `wiw` 只从发布版本运行，因此工作副本中未完成的修改不会在线运行。每次需要上线的提交后，请运行 `scripts/release.sh`。

新文本需要加入 `src/whatisworth/locales/` 中的每个文件。测试会检查所有语言的键和占位符是否一致。

## 计划

- 将 Gemini CLI 作为第二个来源，从 OTel 遥测日志而非聊天文件读取。只有日志还记录了路由器和摘要器的调用。
- 基于同一分析的浏览器仪表板。
- 针对无法自动归属的文件夹的项目规则。
