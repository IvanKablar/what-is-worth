# What is Worth?

**English** · [Deutsch](README.de.md) · [Español](README.es.md) · [中文](README.zh.md) · [日本語](README.ja.md) · [Русский](README.ru.md)

What is Worth? shows how much API value your AI coding agents consume. Its focus is not the calendar month but the subscription window, from one weekly reset to the next. For every account it also measures what one percentage point of the weekly quota is worth in dollars.

Claude Code is supported today. Further agents can be added as adapters. Everything runs locally: no account, no proxy, no data sent anywhere. The only network request downloads the LiteLLM price list once a day.

## Features

- **Overview since the weekly reset** for the signed-in account: usage, API value, value per percentage point, pace, and when the limit will be reached.
- **Breakdown** by day, model and project. A project is a git repository. Worktrees and subdirectories count towards their main repository.
- **All accounts in one table**, each in its own weekly window with its own reset time.
- **Plan cost against API value:** each plan's list price per week, and a factor of API value per percentage point over what one percentage point costs on the plan.
- **Totals for all accounts:** today, this week, this month and all time.
- **Earlier weeks** on the account's reset schedule.
- **Claude Code status line** with weekly usage, cost since reset, value per percentage point, countdown, and the cost of the session and of the last query.
- **Reports** per day, week and month over the whole history.
- **Six languages:** German, English, Spanish, Chinese, Japanese and Russian.

Example status line:

```
Week 51% · $8.04 since reset · Reset Mon 01:00 (3d 7h left) · Session $24.12 · Query $2.34
```

## Requirements

- Python 3.11 or later. No other packages are needed.
- Git, for project detection and releases.
- Claude Code, which keeps its transcripts in `~/.claude/projects/`.

## Installation

1. Clone the repository, for example to `~/what-is-worth`.
2. Create a release. It exports the last commit to `~/.local/share/what-is-worth/app`:

   ```
   scripts/release.sh
   ```

3. Put `wiw` on your path:

   ```
   ln -s ~/.local/share/what-is-worth/app/bin/wiw ~/.local/bin/wiw
   ```

4. Add the status line to `~/.claude/settings.json`:

   ```json
   "statusLine": {
     "type": "command",
     "command": "/home/<user>/.local/share/what-is-worth/app/bin/wiw statusline",
     "padding": 0
   }
   ```

5. Read everything once. About 2,700 transcripts take 10 to 20 seconds:

   ```
   wiw sync
   ```

By default Claude Code deletes transcripts after 30 days. To keep your history, set a high `cleanupPeriodDays` in `~/.claude/settings.json`. Data that is already in the ledger stays there even when its transcript is deleted later.

## Usage

| Command | Effect |
|---|---|
| `wiw` | overview since the last weekly reset, same as `wiw overview` |
| `wiw overview --weeks 10` | overview with ten earlier weeks |
| `wiw report day` | cost per day, likewise `week` and `month`, optionally with `--since 2026-09-01` |
| `wiw sync` | read new data, otherwise happens automatically |
| `wiw sync --rebuild` | re-read existing transcripts, for example after changed parsing rules |
| `wiw reprice` | recompute every cost with the current price list |

Inside Claude Code, open the overview with `! wiw`. No model is involved, so it costs no tokens.

On every refresh the status line reads only the new lines of its own session. At most every five minutes it also starts a background run over all transcripts.

## Configuration

| Variable | Meaning | Default |
|---|---|---|
| `WIW_LANG` | language: `de`, `en`, `es`, `zh`, `ja` or `ru` | system language, else English |
| `WIW_DATA_DIR` | location of the ledger and the release | `~/.local/share/what-is-worth` |
| `WIW_CONFIG_DIR` | location of price overrides | `~/.config/what-is-worth` |
| `WIW_CACHE_DIR` | price list cache | `~/.cache/what-is-worth` |
| `WIW_CLAUDE_DIRS` | additional Claude config directories, separated by `:` | `~/.claude` and `CLAUDE_CONFIG_DIR` |

Your own prices, for example for a model LiteLLM does not know yet, go into `~/.config/what-is-worth/prices.json`. The keys are LiteLLM's, prices are per token:

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

Then run `wiw reprice`.

## How costs are calculated

**Data source.** Claude Code writes every API response with its token counts into one transcript per session, and subagents and workflows into files of their own. A response often appears several times. What is Worth? keeps the fully streamed copy per message id and prefers the main conversation over replays in subagents.

**Prices.** Rates come from LiteLLM. They cover input, output, cache reads and both cache lifetimes of five minutes and one hour. On top come the doubled price of fast mode, a 10 % surcharge for data residency, web searches at $10 per 1,000, and long-context tiers. When a prompt exceeds the threshold, for example over 100,000 tokens on Haiku 5.5, the whole request pays the higher rate, not just the excess.

**Subscription windows and accounts.** Only the status line learns usage, reset time and the signed-in account. It records them on every refresh. Each response belongs to the account that was signed in at its time. A `/login` applies to all running sessions at once.

**Value per percentage point.** An account's cost since the first usage reading in the window, divided by the increase in usage since then. Claude Code reports whole percent only, so the value appears after an increase of 5 points, which keeps the rounding error below about 20 %.

**Cost of a query.** All responses of a session from one input to the next, subagents included.

## Accuracy

- **Against ccusage:** for August to October 2026, tokens and costs matched per month and model. Since then What is Worth? fixes two counting errors ccusage still has, affecting about 0.01 % of the cost.
- **Price rates:** every model in use was checked against Anthropic's official pricing page. The table is in `scripts/official_prices.json`.
- **Independent check:** `scripts/verify_projects.py` recomputes all transcripts without the program code and compares per project with the ledger. Optionally it adds a ccusage export:

  ```
  npx ccusage@latest claude session --json --offline > /tmp/cc.json
  python3 scripts/verify_projects.py /tmp/cc.json
  ```

- **Against Claude Code's own counter:** the sum per session is about 1 % lower, because Claude Code does not write some background calls to the transcript.

Plan prices are list prices without tax from claude.com/pricing: Pro $20, Max 5x $100, Max 20x $200 per month. The pricing page lists Max only as "from $100", so the Max 20x price is the previously known one. Actual prices may differ by currency, tax, annual billing and discounts.

All amounts are API equivalents at list prices. On a Pro or Max subscription they are reference values, not a bill.

## Known limitations

- **Accounts only from installation on.** Transcripts do not contain the account. Costs before the first status line refresh appear as "unattributed".
- **Account switches without a status line.** If you only use `claude -p` or the IDE after a login, the switch is noticed at the next refresh of a terminal status line.
- **Declined first attempts.** When a model declines before any output and another one answers, the fallback is priced correctly. Whether the declined attempt costs anything depends on its category, which the transcript does not contain, so it is not counted.
- **Deleted worktrees.** Worktrees deleted before their first sync cannot be mapped to a repository and appear under their folder name.
- **One machine.** Each machine keeps its own ledger.

## Structure

```
src/whatisworth/
  model.py                 records shared by all sources: response, query, limit, account
  sources/base.py          interface for sources
  sources/claude_code.py   Claude Code adapter
  ledger.py                SQLite ledger
  ingest.py                incremental reading with a lock
  pricing.py               LiteLLM prices with overrides
  projects.py              working directory → git repository
  insights.py              windows, accounts, totals, value per percentage point
  statusline.py            status line
  cli.py                   commands
  i18n.py, format.py, locales/   languages and formats
```

The ledger stores tokens and raw facts. Costs are computed on reading and can be recomputed with `wiw reprice`. Projects and accounts are assigned only when evaluating. A new source, such as Gemini, is one more adapter that produces the same records.

## Development

```
python3 -m pytest -q tests
bin/wiw            # run the working copy
scripts/release.sh # release the last commit
```

The status line and `wiw` run only from the release, so unfinished changes in the working copy never run live. Run `scripts/release.sh` after every commit that should go live.

New texts go into every file in `src/whatisworth/locales/`. A test checks that all languages have the same keys and placeholders.

## Planned

- Gemini CLI as a second source, read from the OTel telemetry log rather than the chat files. Only the log also records router and summarizer calls.
- A browser dashboard on the same evaluation.
- Project rules for folders that cannot be mapped automatically.
