"""Reset windows, account attribution and aggregation.

Shared by the status line, the terminal overview and a later dashboard.

Accounts: the transcripts do not say which account paid for a response.
The status line records which account was signed in and when; a response
belongs to the account of the stretch it falls into. Responses from before
the first recorded stretch are "unattributed" and counted for every account.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .format import day_label
from . import projects
from .ledger import Ledger

WEEK_S = 7 * 24 * 3600
# Claude Code reports usage in whole percent, so a reading can be off by up
# to one point. Five points keep that error at or below about 20 %.
MIN_PCT_INCREASE = 5


@dataclass(frozen=True)
class Window:
    start_s: int
    end_s: int  # the reset moment
    used_pct: float | None = None  # last reported usage
    max_used_pct: float | None = None
    observed: bool = True  # False when extrapolated from a later reset
    seen_ms: int | None = None  # when the usage was last reported

    @property
    def start_ms(self) -> int:
        return self.start_s * 1000

    @property
    def end_ms(self) -> int:
        return self.end_s * 1000


@dataclass
class Totals:
    cost: float = 0.0
    responses: int = 0
    tokens: int = 0
    sessions: set[str] = field(default_factory=set)
    unpriced_models: set[str] = field(default_factory=set)


# accounts -------------------------------------------------------------------


def account_intervals(ledger: Ledger, source: str) -> list[tuple[int, int, str]]:
    """(start_ms, end_ms, account_id) stretches, each until the next switch."""
    rows = ledger.conn.execute(
        "SELECT account_id, first_seen FROM account_observations "
        "WHERE source = ? ORDER BY first_seen",
        (source,),
    ).fetchall()
    intervals = []
    for i, row in enumerate(rows):
        end = rows[i + 1]["first_seen"] if i + 1 < len(rows) else 2**62
        intervals.append((row["first_seen"], end, row["account_id"]))
    return intervals


def ranges_for_account(
    intervals: list[tuple[int, int, str]],
    account: str | None,
    start_ms: int,
    end_ms: int,
    include_unknown: bool = True,
) -> list[tuple[int, int]]:
    """Parts of [start, end) that belong to `account`, plus, unless excluded,
    the time before any account was recorded."""
    if account is None or not intervals:
        return [(start_ms, end_ms)] if include_unknown else []
    ranges = []
    first_known = intervals[0][0]
    if include_unknown and start_ms < first_known:
        ranges.append((start_ms, min(end_ms, first_known)))
    for a, b, acc in intervals:
        if acc == account and b > start_ms and a < end_ms:
            ranges.append((max(a, start_ms), min(b, end_ms)))
    return ranges


@dataclass(frozen=True)
class Account:
    id: str
    label: str
    plan: str
    last_seen_ms: int


_PLAN_NAMES = {
    "claude_pro": "Pro", "claude_max": "Max", "claude_max_5x": "Max 5x", "claude_max_20x": "Max 20x",
    "claude_team": "Team", "claude_enterprise": "Enterprise",
}


def plan_name(plan: str | None) -> str:
    return _PLAN_NAMES.get(plan or "", plan or "–")


def known_accounts(ledger: Ledger, source: str) -> list[Account]:
    """Every account the status line has seen, most recently used first."""
    rows = ledger.conn.execute(
        "SELECT account_id, MAX(last_seen) AS last_seen, "
        "(SELECT label FROM account_observations b WHERE b.account_id = a.account_id "
        " AND b.source = a.source AND label IS NOT NULL ORDER BY last_seen DESC LIMIT 1) AS label, "
        "(SELECT plan FROM account_observations b WHERE b.account_id = a.account_id "
        " AND b.source = a.source AND plan IS NOT NULL ORDER BY last_seen DESC LIMIT 1) AS plan "
        "FROM account_observations a WHERE source = ? GROUP BY account_id ORDER BY last_seen DESC",
        (source,),
    ).fetchall()
    return [Account(r["account_id"], r["label"] or r["account_id"][:8], r["plan"] or "", r["last_seen"]) for r in rows]


def tracking_start_ms(ledger: Ledger, source: str) -> int | None:
    row = ledger.conn.execute(
        "SELECT MIN(first_seen) FROM account_observations WHERE source = ?", (source,)
    ).fetchone()
    return row[0]


def label_for(ledger: Ledger, account: str | None) -> str | None:
    if account is None:
        return None
    row = ledger.conn.execute(
        "SELECT label FROM account_observations WHERE account_id = ? AND label IS NOT NULL "
        "ORDER BY last_seen DESC LIMIT 1",
        (account,),
    ).fetchone()
    return row["label"] if row else account[:8]


@dataclass(frozen=True)
class Measured:
    """Cost of one account against its usage increase, both since `since_ms`."""

    cost: float
    pct_increase: float
    since_ms: int

    @property
    def per_pct(self) -> float | None:
        """None until the increase is large enough for whole-percent readings."""
        if self.pct_increase < MIN_PCT_INCREASE:
            return None
        return self.cost / self.pct_increase


def measured(
    ledger: Ledger, source: str, account: str | None, window: "Window", now_ms: int
) -> Measured | None:
    """Value per usage percent, from recorded data only.

    Uses the first and the latest usage the status line reported in this
    window and only responses that certainly belong to `account`, so
    unattributed history never distorts the result.
    """
    if account is None:
        return None
    row = ledger.conn.execute(
        "SELECT first_seen, first_used_pct, last_used_pct FROM limit_observations "
        "WHERE source = ? AND kind = 'seven_day' AND origin = 'statusline' "
        "AND account = ? AND resets_at = ?",
        (source, account, window.end_s),
    ).fetchone()
    if row is None or row["first_used_pct"] is None or row["last_used_pct"] is None:
        return None
    ranges = ranges_for_account(
        account_intervals(ledger, source), account, row["first_seen"], now_ms + 1,
        include_unknown=False,
    )
    cost = totals(ledger, source, ranges).cost
    return Measured(cost, row["last_used_pct"] - row["first_used_pct"], row["first_seen"])


# windows --------------------------------------------------------------------


def current_window(ledger: Ledger, source: str, account: str | None, now_s: int) -> Window | None:
    """The running weekly window of `account`, from status line reports."""
    row = ledger.conn.execute(
        "SELECT resets_at, last_used_pct, max_used_pct, last_seen FROM limit_observations "
        "WHERE source = ? AND kind = 'seven_day' AND origin = 'statusline' AND account = ? "
        "AND resets_at > ? ORDER BY resets_at LIMIT 1",
        (source, account or "", now_s),
    ).fetchone()
    if row is None:
        return None
    return Window(
        row["resets_at"] - WEEK_S, row["resets_at"], row["last_used_pct"], row["max_used_pct"],
        seen_ms=row["last_seen"],
    )


def past_windows(
    ledger: Ledger, source: str, account: str | None, current: Window, count: int
) -> list[Window]:
    """Earlier windows on the same weekly grid as `current`.

    Weekly resets of one account sit on a fixed 7-day grid, so earlier
    windows are extrapolated backwards. A window counts as observed when a
    reset on exactly that boundary was seen, with its peak usage if known.
    """
    seen = {
        row["resets_at"]: row["max_used_pct"]
        for row in ledger.conn.execute(
            "SELECT resets_at, MAX(max_used_pct) AS max_used_pct FROM limit_observations "
            "WHERE source = ? AND kind = 'seven_day' AND (account = ? OR account = '') "
            "GROUP BY resets_at",
            (source, account or ""),
        )
    }
    first_ts = ledger.conn.execute("SELECT MIN(ts) FROM events WHERE source = ?", (source,)).fetchone()[0]
    windows = []
    end = current.start_s
    while len(windows) < count and first_ts is not None and end * 1000 > first_ts:
        windows.append(Window(end - WEEK_S, end, None, seen.get(end), observed=end in seen))
        end -= WEEK_S
    return windows


# aggregation ----------------------------------------------------------------


def _where(ranges: list[tuple[int, int]]) -> tuple[str, list[int]]:
    if not ranges:
        return "0", []
    clause = " OR ".join("(ts >= ? AND ts < ?)" for _ in ranges)
    return f"({clause})", [v for r in ranges for v in r]


def totals(ledger: Ledger, source: str, ranges: list[tuple[int, int]], session: str | None = None) -> Totals:
    clause, params = _where(ranges)
    sql = (
        "SELECT session_id, model, total, cost_usd, price_status FROM events "
        f"WHERE source = ? AND {clause}"
    )
    args: list = [source, *params]
    if session:
        sql += " AND session_id = ?"
        args.append(session)
    result = Totals()
    for r in ledger.conn.execute(sql, args):
        result.cost += r["cost_usd"]
        result.responses += 1
        result.tokens += r["total"]
        if r["session_id"]:
            result.sessions.add(r["session_id"])
        if r["price_status"] != "priced":
            result.unpriced_models.add(r["model"])
    return result


def breakdown(
    ledger: Ledger, source: str, ranges: list[tuple[int, int]], by: str
) -> list[tuple[str, float]]:
    """Cost per model, project or local day, largest first (days in order)."""
    clause, params = _where(ranges)
    rows = ledger.conn.execute(
        f"SELECT ts, model, cwd, cost_usd FROM events WHERE source = ? AND {clause}",
        [source, *params],
    ).fetchall()
    sums: dict[str, float] = {}
    repos = ledger.repo_map() if by == "project" else {}
    for r in rows:
        if by == "model":
            key = r["model"]
        elif by == "project":
            key = projects.label(r["cwd"], repos.get(r["cwd"]))
        else:
            key = day_label(r["ts"] / 1000)
        sums[key] = sums.get(key, 0.0) + r["cost_usd"]
    items = list(sums.items())
    if by != "day":
        items.sort(key=lambda kv: kv[1], reverse=True)
    return items


def calendar_starts(now_s: int) -> dict[str, int]:
    """Local start of today, this week (Monday) and this month, in epoch ms."""
    from datetime import datetime, timedelta

    today = datetime.fromtimestamp(now_s).replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    return {k: int(v.timestamp() * 1000) for k, v in (("today", today), ("week", monday), ("month", month))}


def first_event_ms(ledger: Ledger, source: str) -> int | None:
    return ledger.conn.execute("SELECT MIN(ts) FROM events WHERE source = ?", (source,)).fetchone()[0]


def query_cost(ledger: Ledger, source: str, session: str, now_ms: int) -> float | None:
    """Cost of the latest query of a session, subagents included."""
    row = ledger.conn.execute(
        "SELECT MAX(ts) FROM prompts WHERE source = ? AND session_id = ?", (source, session)
    ).fetchone()
    if row[0] is None:
        return None
    return totals(ledger, source, [(row[0], now_ms + 1)], session).cost

