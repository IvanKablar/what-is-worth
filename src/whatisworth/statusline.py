"""Claude Code status line: `wiw statusline`, fed JSON on stdin.

Each call records what only the status line knows (rate limits, the signed-in
account, Claude Code's own session cost), reads the session's new transcript
lines, and prints one line. A full sync of all transcripts runs in the
background at most every few minutes. It never blocks for long and never
prints a traceback.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from . import insights, plans
from .config import Config
from .format import countdown, factor, pct as fmt_pct, usd, weekday_time
from .i18n import t
from .ingest import SyncBusy, sync, sync_lock
from .ledger import Ledger
from .model import AccountObservation, LimitObservation
from .pricing import PriceBook
from .sources.claude_code import ClaudeCodeSource, signed_in_account

SOURCE = ClaudeCodeSource.name
FULL_SYNC_EVERY_S = 300


def record(ledger: Ledger, data: dict, account: dict | None, now_ms: int) -> None:
    account_id = account["id"] if account else None
    if account:
        ledger.record_account(
            AccountObservation(SOURCE, now_ms, account["id"], account["label"], account["plan"])
        )
    limits = data.get("rate_limits") or {}
    observations = []
    for kind in ("five_hour", "seven_day"):
        window = limits.get(kind) or {}
        if isinstance(window.get("resets_at"), (int, float)):
            observations.append(
                LimitObservation(
                    SOURCE, now_ms, kind, int(window["resets_at"]), "statusline",
                    used_pct=window.get("used_percentage"), account=account_id,
                )
            )
    ledger.upsert_limits(observations)
    session = data.get("session_id")
    cost = (data.get("cost") or {}).get("total_cost_usd")
    if session and isinstance(cost, (int, float)):
        ledger.record_reported_cost(SOURCE, session, float(cost), now_ms)
    ledger.commit()


def session_files(transcript: str | None) -> list[Path]:
    if not transcript:
        return []
    main = Path(transcript)
    files = [main] if main.exists() else []
    subagents = main.with_suffix("") / "subagents"
    if subagents.is_dir():
        files.extend(sorted(subagents.rglob("*.jsonl")))
    return files


def read_session(cfg: Config, ledger: Ledger, transcript: str | None) -> None:
    files = session_files(transcript)
    if not files:
        return
    try:
        prices = PriceBook.load(cfg.cache_dir, cfg.price_overrides_path, offline=True)
        with sync_lock(cfg.lock_path, wait=False):
            sync(ledger, [ClaudeCodeSource()], prices, only=files)
    except (SyncBusy, RuntimeError, sqlite3.OperationalError):
        pass  # a background sync is running or prices are not cached yet


def maybe_start_full_sync(ledger: Ledger, now_s: int) -> None:
    last = ledger.get_meta("last_full_sync")
    if last and now_s - int(last) < FULL_SYNC_EVERY_S:
        return
    ledger.set_meta("last_full_sync", str(now_s))  # avoid a burst of starts
    ledger.commit()
    launcher = Path(__file__).resolve().parents[2] / "bin" / "wiw"
    subprocess.Popen(
        [str(launcher), "sync", "--no-wait", "--quiet"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def render(ledger: Ledger, data: dict, account: dict | None, now_s: int) -> str:
    account_id = account["id"] if account else None
    parts: list[str] = []
    window = insights.current_window(ledger, SOURCE, account_id, now_s)
    if window:
        ranges = insights.ranges_for_account(
            insights.account_intervals(ledger, SOURCE), account_id, window.start_ms, now_s * 1000 + 1,
            include_unknown=False,
        )
        spent = insights.totals(ledger, SOURCE, ranges).cost
        week = (t("status.week", pct=fmt_pct(window.used_pct)) if window.used_pct is not None
                else t("status.week_unknown"))
        parts.append(f"{week} · {t('status.since_reset', value=usd(spent))}")
        m = insights.measured(ledger, SOURCE, account_id, window, now_s * 1000)
        if m and m.per_pct is not None:
            text = t("status.per_pct", value=usd(m.per_pct))
            plan_pct = plans.price_per_pct(account["plan"] if account else None)
            if plan_pct:
                text += f" ({factor(m.per_pct / plan_pct)})"
            parts.append(text)
        parts.append(t("status.reset", when=weekday_time(window.end_s), countdown=countdown(window.end_s - now_s)))
    session = data.get("session_id")
    if session:
        session_total = insights.totals(ledger, SOURCE, [(0, 2**62)], session).cost
        parts.append(t("status.session", value=usd(session_total)))
        query = insights.query_cost(ledger, SOURCE, session, now_s * 1000)
        if query is not None:
            parts.append(t("status.query", value=usd(query)))
    return " · ".join(parts) or t("status.no_data")


def run(cfg: Config) -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        data = {}
    now_s = int(time.time())
    try:
        ledger = Ledger(cfg.ledger_path, timeout=2)
        account = signed_in_account()
        try:
            record(ledger, data, account, now_s * 1000)
        except sqlite3.OperationalError:
            pass  # busy ledger: skip recording this time
        read_session(cfg, ledger, data.get("transcript_path"))
        line = render(ledger, data, account, now_s)
        maybe_start_full_sync(ledger, now_s)
        ledger.close()
    except Exception as exc:  # the status line must always print something
        line = f"What is Worth?: {type(exc).__name__}"
    print(line)
    return 0
