"""Command line: `wiw` (overview), `wiw sync`, `wiw report`, `wiw reprice`."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta

from . import insights, plans, projects
from .config import load_config
from .format import counted, countdown, date_range, factor, full_date, left, pct, right, usd, weekday_time, width
from .i18n import localize_argparse, t
from .ingest import SyncBusy, reprice, sync, sync_lock
from .ledger import Ledger
from .pricing import PriceBook
from .sources import available_sources, create_sources
from .sources.claude_code import ClaudeCodeSource, signed_in_account

_LABELS = ("account", "window", "usage", "value", "per_pct", "plan", "factor", "pace", "limit", "note", "unpriced")


def _prices(cfg, offline: bool) -> PriceBook:
    return PriceBook.load(cfg.cache_dir, cfg.price_overrides_path, offline=offline)


def _line(key: str, text: str) -> None:
    """One `Label  value` line of the overview, aligned for every language."""
    columns = max(width(t(f"label.{k}")) for k in _LABELS) + 2
    print(left(t(f"label.{key}"), columns) + text)


def cmd_sync(args, cfg) -> int:
    started = time.monotonic()
    ledger = Ledger(cfg.ledger_path)
    try:
        with sync_lock(cfg.lock_path, wait=not args.no_wait):
            stats = sync(
                ledger, create_sources(args.source), _prices(cfg, args.offline),
                full=args.full, rebuild=args.rebuild,
            )
            ledger.set_meta("last_full_sync", str(int(time.time())))
            ledger.commit()
    except SyncBusy as exc:
        print(exc, file=sys.stderr)
        return 0
    finally:
        ledger.close()
    if not args.quiet:
        print(t("sync.done", read=stats.files_read, seen=stats.files_seen, events=stats.events,
                limits=stats.limits, bad=stats.bad_lines, secs=f"{time.monotonic() - started:.1f}"))
    return 0


def cmd_reprice(args, cfg) -> int:
    ledger = Ledger(cfg.ledger_path)
    try:
        with sync_lock(cfg.lock_path):
            n = reprice(ledger, _prices(cfg, args.offline))
    finally:
        ledger.close()
    print(t("reprice.done", n=n))
    return 0


def _period_label(ts_ms: int, period: str) -> str:
    moment = datetime.fromtimestamp(ts_ms / 1000)
    if period == "week":
        monday = moment.date() - timedelta(days=moment.weekday())
        return t("report.week", date=f"{monday:%Y-%m-%d}")
    return moment.strftime("%Y-%m-%d" if period == "day" else "%Y-%m")


def cmd_report(args, cfg) -> int:
    ledger = Ledger(cfg.ledger_path)
    since_ms = 0
    if args.since:
        since_ms = int(datetime.strptime(args.since, "%Y-%m-%d").timestamp() * 1000)
    rows = ledger.conn.execute(
        "SELECT ts, model, cwd, total, cost_usd, price_status FROM events WHERE ts >= ? ORDER BY ts",
        (since_ms,),
    ).fetchall()
    repos = ledger.repo_map() if args.period == "project" else {}
    rules = projects.load_rules(cfg.project_rules_path)
    ledger.close()
    groups: dict[str, list[float]] = {}
    unpriced: dict[str, set[str]] = {}
    for r in rows:
        if args.period == "project":
            label = projects.label(r["cwd"], projects.known_repo(r["cwd"], repos), rules)
        else:
            label = _period_label(r["ts"], args.period)
        g = groups.setdefault(label, [0, 0, 0.0])
        g[0] += 1
        g[1] += r["total"]
        g[2] += r["cost_usd"]
        if r["price_status"] != "priced":
            unpriced.setdefault(label, set()).add(r["model"])
    from .format import count

    items = list(groups.items())
    if args.period == "project":
        items.sort(key=lambda kv: kv[1][2], reverse=True)
    head = t("col.project") if args.period == "project" else t("col.period")
    cols = min(max([width(head)] + [width(label) for label, _ in items]), 40) + 2
    print(left(head, cols) + right(t("col.responses"), 12) + right(t("col.tokens"), 18)
          + right(t("col.usd"), 16))
    for label, (n, tokens, cost) in items:
        note = "  " + t("report.unpriced", models=", ".join(sorted(unpriced[label]))) if label in unpriced else ""
        print(left(label, cols) + right(count(n), 12) + right(count(tokens), 18) + right(usd(cost), 16) + note)
    return 0


def cmd_statusline(args, cfg) -> int:
    from .statusline import run

    return run(cfg)


def _bar(value: float, maximum: float, size: int = 24) -> str:
    filled = round(size * value / maximum) if maximum > 0 else 0
    return "█" * filled + "·" * (size - filled)


def _print_breakdown(title: str, items: list[tuple[str, float]], limit: int) -> None:
    if not items:
        return
    print(f"\n{title}")
    shown = items[:limit]
    top = max(v for _, v in shown)
    for name, value in shown:
        print(f"  {left(name, 28)} {right(usd(value), 13)}  {_bar(value, top)}")
    rest = sum(v for _, v in items[limit:])
    if rest:
        print(f"  {left(t('section.other'), 28)} {right(usd(rest), 13)}")


def _sync_quietly(cfg) -> None:
    ledger = Ledger(cfg.ledger_path)
    try:
        with sync_lock(cfg.lock_path, wait=False):
            sync(ledger, [ClaudeCodeSource()], _prices(cfg, offline=False))
    except SyncBusy:
        pass
    finally:
        ledger.close()


def _limit_forecast(window: insights.Window, now_s: int) -> str | None:
    """When the weekly limit runs out at the current pace, from the account's own usage."""
    if not window.used_pct:
        return None
    elapsed_days = max((now_s - window.start_s) / 86400, 1 / 24)
    remaining_days = max((window.end_s - now_s) / 86400, 0)
    pct_per_day = window.used_pct / elapsed_days
    at_reset = window.used_pct + pct_per_day * remaining_days
    if at_reset <= 100:
        return t("forecast.at_reset", pct=pct(at_reset))
    hit_s = int(now_s + (100 - window.used_pct) / pct_per_day * 86400)
    return t("forecast.hit", when=weekday_time(hit_s), countdown=countdown(hit_s - now_s))


# Column widths of the accounts table.
_ACC, _PLAN, _USE, _RESET, _VALUE, _PER, _WEEK, _FACTOR = 26, 9, 17, 12, 13, 13, 12, 9


def _accounts_table(ledger, source: str, now_s: int, current_id: str | None) -> None:
    accounts = insights.known_accounts(ledger, source)
    if not accounts:
        return
    intervals = insights.account_intervals(ledger, source)
    start = insights.tracking_start_ms(ledger, source)
    print(f"\n{t('accounts.title')}")
    print("  " + left(t("col.account"), _ACC) + left(t("col.plan"), _PLAN) + right(t("col.usage"), _USE)
          + "  " + left(t("col.reset"), _RESET) + right(t("col.value"), _VALUE) + right(t("col.per_pct"), _PER)
          + right(t("col.plan_week"), _WEEK) + right(t("col.factor"), _FACTOR))
    earliest = now_s
    summed = 0.0
    for acc in accounts:
        window = insights.current_window(ledger, source, acc.id, now_s)
        mark = "*" if acc.id == current_id else " "
        head = " " + mark + left(acc.label, _ACC) + left(insights.plan_name(acc.plan), _PLAN)
        if window is None:
            print(head + right("–", _USE) + "  " + left("–", _RESET))
            continue
        earliest = min(earliest, window.start_s)
        ranges = insights.ranges_for_account(
            intervals, acc.id, window.start_ms, now_s * 1000 + 1, include_unknown=False
        )
        cost = insights.totals(ledger, source, ranges).cost
        summed += cost
        m = insights.measured(ledger, source, acc.id, window, now_s * 1000)
        per_pct = usd(m.per_pct) if m and m.per_pct is not None else t("accounts.pending")
        used = pct(window.used_pct)
        if acc.id != current_id and window.seen_ms:
            used += f" ({weekday_time(window.seen_ms // 1000)})"
        weekly = plans.weekly_price(acc.plan)
        ratio = (factor(m.per_pct / plans.price_per_pct(acc.plan))
                 if weekly is not None and m and m.per_pct is not None else "–")
        print(head + right(used, _USE) + "  " + left(weekday_time(window.end_s), _RESET)
              + right(usd(cost), _VALUE) + right(per_pct, _PER)
              + right(usd(weekly) if weekly is not None else "–", _WEEK) + right(ratio, _FACTOR))
    label_cols = _ACC + _PLAN + _USE + 2 + _RESET
    if start and earliest * 1000 < start:
        unknown = insights.totals(ledger, source, [(earliest * 1000, start)]).cost
        summed += unknown
        print("  " + left(t("accounts.unattributed", since=weekday_time(start // 1000)), label_cols)
              + right(usd(unknown), _VALUE))
    print("  " + left(t("accounts.total", since=weekday_time(earliest)), label_cols) + right(usd(summed), _VALUE))
    print("  " + t("accounts.footnote"))
    print("  " + t("accounts.plan_note"))


def _totals_block(ledger, source: str, now_s: int) -> None:
    """Absolute costs of all accounts: today, this week, this month, all time."""
    first = insights.first_event_ms(ledger, source)
    if first is None:
        return
    end = now_s * 1000 + 1
    starts = insights.calendar_starts(now_s)
    rows = [(t(f"totals.{k}"), starts[k]) for k in ("today", "week", "month")]
    rows.append((t("totals.all", since=full_date(first / 1000)), first))
    label_cols = max(width(label) for label, _ in rows) + 2
    print(f"\n{t('totals.title')}")
    for label, start in rows:
        print("  " + left(label, label_cols) + right(usd(insights.totals(ledger, source, [(start, end)]).cost), 14))


def cmd_overview(args, cfg) -> int:
    source = ClaudeCodeSource.name
    if not args.no_sync:
        _sync_quietly(cfg)
    ledger = Ledger(cfg.ledger_path)
    now_s = int(time.time())
    account = signed_in_account()
    account_id = account["id"] if account else None
    window = insights.current_window(ledger, source, account_id, now_s)
    print(t("overview.title"))
    if account:
        _line("account", f"{account['label']} ({insights.plan_name(account['plan'])})")
    if window is None:
        print(t("overview.no_window"))
        _accounts_table(ledger, source, now_s, account_id)
        _totals_block(ledger, source, now_s)
        ledger.close()
        return 0

    intervals = insights.account_intervals(ledger, source)
    ranges = insights.ranges_for_account(
        intervals, account_id, window.start_ms, now_s * 1000 + 1, include_unknown=False
    )
    totals = insights.totals(ledger, source, ranges)
    tracked_ms = sum(b - a for a, b in ranges)
    start = insights.tracking_start_ms(ledger, source)

    _line("window", f"{date_range(window.start_s, window.end_s)}, {countdown(window.end_s - now_s)}")
    _line("usage", pct(window.used_pct))
    _line("value", t("overview.value", cost=usd(totals.cost),
                     sessions=counted(len(totals.sessions), "session"),
                     responses=counted(totals.responses, "response")))
    m = insights.measured(ledger, source, account_id, window, now_s * 1000)
    if m and m.per_pct is not None:
        _line("per_pct", t("overview.per_pct", value=usd(m.per_pct), since=weekday_time(m.since_ms // 1000),
                           cost=usd(m.cost), points=f"{m.pct_increase:.0f}"))
    elif m:
        _line("per_pct", t("overview.per_pct_pending", since=weekday_time(m.since_ms // 1000), cost=usd(m.cost),
                           points=f"{m.pct_increase:.0f}", needed=insights.MIN_PCT_INCREASE))
    plan = account["plan"] if account else None
    if plans.monthly_price(plan) is not None:
        _line("plan", t("overview.plan", monthly=usd(plans.monthly_price(plan)), plan=insights.plan_name(plan),
                        weekly=usd(plans.weekly_price(plan))))
        if m and m.per_pct is not None:
            _line("factor", t("overview.factor", factor=factor(m.per_pct / plans.price_per_pct(plan)),
                              value=usd(m.per_pct), plan_pct=usd(plans.price_per_pct(plan))))
    if tracked_ms >= 12 * 3600 * 1000:
        _line("pace", t("overview.pace", value=usd(totals.cost / (tracked_ms / 86_400_000))))
    forecast = _limit_forecast(window, now_s)
    if forecast:
        _line("limit", forecast)
    if start and start > window.start_ms:
        _line("note", t("overview.tracking_note", since=weekday_time(start // 1000)))
    if totals.unpriced_models:
        _line("unpriced", ", ".join(sorted(totals.unpriced_models)))

    _print_breakdown(t("section.by_day"), insights.breakdown(ledger, source, ranges, "day"), 7)
    _print_breakdown(t("section.by_model"), insights.breakdown(ledger, source, ranges, "model"), 6)
    # Projects span accounts, so they cover the whole window including unattributed costs.
    whole = [(window.start_ms, now_s * 1000 + 1)]
    _print_breakdown(t("section.by_project_all", since=weekday_time(window.start_s)),
                     insights.breakdown(ledger, source, whole, "project", projects.load_rules(cfg.project_rules_path)), 10)
    _accounts_table(ledger, source, now_s, account_id)
    _totals_block(ledger, source, now_s)

    history = insights.past_windows(ledger, source, account_id, window, args.weeks)
    if history:
        rows = []
        for w in history:
            r = insights.ranges_for_account(intervals, account_id, w.start_ms, w.end_ms)
            cost = insights.totals(ledger, source, r).cost
            per_pct = usd(cost / w.max_used_pct) if w.max_used_pct else "–"
            mark = "" if w.observed else " *"
            rows.append((date_range(w.start_s, w.end_s) + mark, usd(cost), pct(w.max_used_pct), per_pct))
        period_cols = max(width(r[0]) for r in rows + [(t("col.period"),)]) + 2
        print(f"\n{t('history.title')}")
        print("  " + left(t("col.period"), period_cols) + right(t("col.value"), 14) + right(t("col.peak"), 10)
              + right(t("col.per_pct"), 14))
        for period, cost, peak, per_pct in rows:
            print("  " + left(period, period_cols) + right(cost, 14) + right(peak, 10) + right(per_pct, 14))
        print("  " + t("history.footnote"))
    ledger.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    cfg.ensure_dirs()
    localize_argparse()
    parser = argparse.ArgumentParser(prog="wiw", description=t("help.description"))
    sub = parser.add_subparsers(dest="command", required=True, metavar=t("help.command"))

    p = sub.add_parser("sync", help=t("help.sync"))
    p.add_argument("--full", action="store_true", help=t("help.full"))
    p.add_argument("--rebuild", action="store_true", help=t("help.rebuild"))
    p.add_argument("--no-wait", action="store_true", help=t("help.no_wait"))
    p.add_argument("--source", action="append", choices=available_sources(), help=t("help.source"))
    p.add_argument("--offline", action="store_true", help=t("help.offline"))
    p.add_argument("--quiet", action="store_true", help=t("help.quiet"))
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("overview", help=t("help.overview"))
    p.add_argument("--weeks", type=int, default=6, help=t("help.weeks"))
    p.add_argument("--no-sync", action="store_true", help=t("help.no_sync"))
    p.set_defaults(func=cmd_overview)

    p = sub.add_parser("statusline", help=t("help.statusline"))
    p.set_defaults(func=cmd_statusline)

    p = sub.add_parser("reprice", help=t("help.reprice"))
    p.add_argument("--offline", action="store_true", help=t("help.offline"))
    p.set_defaults(func=cmd_reprice)

    p = sub.add_parser("report", help=t("help.report"))
    p.add_argument("period", choices=["day", "week", "month", "project"], help=t("help.period"))
    p.add_argument("--since", help=t("help.since"))
    p.set_defaults(func=cmd_report)

    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        argv = ["overview"]  # plain `wiw` shows the overview
    args = parser.parse_args(argv)
    return args.func(args, cfg)
