import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whatisworth import insights  # noqa: E402
from whatisworth.ledger import Ledger  # noqa: E402
from whatisworth.model import AccountObservation, LimitObservation  # noqa: E402

DAY_MS = 86_400_000


def test_ranges_keep_own_and_unknown_time_only():
    intervals = [(100, 200, "a"), (200, 300, "b"), (300, 2**62, "a")]
    assert insights.ranges_for_account(intervals, "a", 0, 400) == [(0, 100), (100, 200), (300, 400)]
    assert insights.ranges_for_account(intervals, "b", 0, 400) == [(0, 100), (200, 300)]
    assert insights.ranges_for_account([], "a", 0, 400) == [(0, 400)]


def test_account_switches_become_stretches(tmp_path):
    ledger = Ledger(tmp_path / "l.sqlite")
    for at, acc in [(10, "a"), (20, "a"), (30, "b"), (40, "a")]:
        ledger.record_account(AccountObservation("s", at, acc))
    assert insights.account_intervals(ledger, "s") == [(10, 30, "a"), (30, 40, "b"), (40, 2**62, "a")]


def test_current_and_past_windows_follow_the_weekly_grid(tmp_path):
    ledger = Ledger(tmp_path / "l.sqlite")
    reset = 1_792_756_800
    week = insights.WEEK_S
    ledger.upsert_limits([
        LimitObservation("s", 1, "seven_day", reset, "statusline", used_pct=40, account="a"),
        LimitObservation("s", 1, "seven_day", reset - 2 * week, "transcript"),
        LimitObservation("s", 1, "seven_day", reset - week + 3600, "transcript"),  # other grid
    ])
    ledger.conn.execute(
        "INSERT INTO events (source, event_key, ts, model, input, output, cache_read, cache_write_5m,"
        " cache_write_1h, reasoning, web_search, total, cost_usd, price_status, price_version)"
        " VALUES ('s', 'k', ?, 'm', 0, 0, 0, 0, 0, 0, 0, 0, 1.0, 'priced', 'v')",
        ((reset - 4 * week) * 1000 + DAY_MS,),
    )
    ledger.commit()
    current = insights.current_window(ledger, "s", "a", reset - 3600)
    assert (current.start_s, current.end_s, current.used_pct) == (reset - week, reset, 40)
    past = insights.past_windows(ledger, "s", "a", current, 10)
    assert [w.end_s for w in past] == [reset - week, reset - 2 * week, reset - 3 * week]
    assert [w.observed for w in past] == [False, True, False]


def test_measured_value_ignores_unattributed_history(tmp_path):
    ledger = Ledger(tmp_path / "l.sqlite")
    reset, start = 1_792_994_400, 1_792_994_400_000 - 3 * DAY_MS
    def add(key, ts, cost):
        ledger.conn.execute(
            "INSERT INTO events (source, event_key, ts, model, input, output, cache_read, cache_write_5m,"
            " cache_write_1h, reasoning, web_search, total, cost_usd, price_status, price_version)"
            " VALUES ('s', ?, ?, 'm', 0, 0, 0, 0, 0, 0, 0, 0, ?, 'priced', 'v')", (key, ts, cost))
    add("before", start - DAY_MS, 500.0)  # before tracking: may be another account
    ledger.record_account(AccountObservation("s", start, "a"))
    ledger.upsert_limits([LimitObservation("s", start, "seven_day", reset, "statusline", used_pct=70, account="a")])
    add("after", start + 1000, 30.0)
    ledger.upsert_limits([LimitObservation("s", start + 2000, "seven_day", reset, "statusline", used_pct=75, account="a")])
    ledger.commit()
    window = insights.current_window(ledger, "s", "a", reset - 3600)
    m = insights.measured(ledger, "s", "a", window, start + 5000)
    assert (m.cost, m.pct_increase, m.per_pct) == (30.0, 5.0, 6.0)
    assert insights.Measured(30.0, 4.0, 0).per_pct is None
