import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whatisworth.ingest import reprice, sync  # noqa: E402
from whatisworth.ledger import Ledger  # noqa: E402
from whatisworth.model import TokenCounts, UsageEvent  # noqa: E402
from whatisworth.pricing import PriceBook, token_cost  # noqa: E402
from whatisworth.sources.claude_code import ClaudeCodeSource  # noqa: E402

RATES = {
    "claude-opus-5-5": {
        "input_cost_per_token": 4e-06,
        "output_cost_per_token": 2e-05,
        "cache_read_input_token_cost": 2e-07,
        "cache_creation_input_token_cost": 5e-06,
        "cache_creation_input_token_cost_above_1hr": 8e-06,
        "search_context_cost_per_query": {"search_context_size_medium": 0.01},
    },
    "claude-haiku-5-5": {
        "input_cost_per_token": 1e-07,
        "output_cost_per_token": 5e-07,
        "input_cost_per_token_above_100k_tokens": 5e-07,
        "output_cost_per_token_above_100k_tokens": 2.5e-06,
    },
}


def assistant(msg_id, ts, output, *, req="req_1", model="claude-opus-5-5", sidechain=False, **usage):
    u = {"input_tokens": 10, "output_tokens": output, "cache_read_input_tokens": 0,
         "cache_creation_input_tokens": 0}
    u.update(usage)
    return json.dumps({
        "type": "assistant", "timestamp": ts, "sessionId": "s1", "requestId": req,
        "cwd": "/home/x/proj", "isSidechain": sidechain,
        "message": {"id": msg_id, "model": model, "usage": u},
    })


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "claude"
    project = root / "projects" / "-home-x-proj"
    project.mkdir(parents=True)
    ledger = Ledger(tmp_path / "ledger.sqlite")
    prices = PriceBook(RATES, "test")
    return project, ClaudeCodeSource([root]), ledger, prices


def totals(ledger):
    return ledger.conn.execute("SELECT COUNT(*), SUM(output), SUM(cost_usd) FROM events").fetchone()


def test_duplicates_keep_most_complete_copy(env):
    project, source, ledger, prices = env
    (project / "s1.jsonl").write_text("\n".join([
        assistant("msg_a", "2026-10-20T10:00:00Z", 5),
        assistant("msg_a", "2026-10-20T10:00:01Z", 50),
        assistant("msg_a", "2026-10-20T10:00:02Z", 50),
    ]) + "\n")
    sync(ledger, [source], prices)
    count, output, _ = totals(ledger)
    assert (count, output) == (1, 50)


def test_sidechain_replay_does_not_replace_main_copy(env):
    project, source, ledger, prices = env
    (project / "s1.jsonl").write_text(assistant("msg_a", "2026-10-20T10:00:00Z", 50) + "\n")
    (project / "s1").mkdir()
    (project / "s1" / "agent.jsonl").write_text(
        assistant("msg_a", "2026-10-20T10:05:00Z", 80, req="req_2", sidechain=True) + "\n"
    )
    sync(ledger, [source], prices)
    row = ledger.conn.execute("SELECT output, sidechain FROM events").fetchone()
    assert tuple(row) == (50, 0)


def test_incremental_read_and_partial_line(env):
    project, source, ledger, prices = env
    path = project / "s1.jsonl"
    first = assistant("msg_a", "2026-10-20T10:00:00Z", 5) + "\n"
    partial = assistant("msg_b", "2026-10-20T10:01:00Z", 7)
    path.write_text(first + partial[:20])
    sync(ledger, [source], prices)
    assert totals(ledger)[0] == 1
    path.write_text(first + partial + "\n")
    sync(ledger, [source], prices)
    assert totals(ledger)[0] == 2


def test_sync_is_idempotent(env):
    project, source, ledger, prices = env
    (project / "s1.jsonl").write_text(assistant("msg_a", "2026-10-20T10:00:00Z", 5) + "\n")
    sync(ledger, [source], prices)
    before = tuple(totals(ledger))
    sync(ledger, [source], prices, full=True)
    assert tuple(totals(ledger)) == before
    assert reprice(ledger, prices) == 1
    assert tuple(totals(ledger)) == before


def test_quota_limits_are_recorded(env):
    project, source, ledger, prices = env
    line = json.dumps({"type": "assistant", "timestamp": "2026-10-21T18:06:00Z",
                       "quotaLimits": {"rateLimitType": "seven_day", "resetsAt": 1792756800,
                                       "status": "rejected"},
                       "message": {"id": "x", "model": "<synthetic>", "usage": {}}})
    (project / "s1.jsonl").write_text(line + "\n")
    sync(ledger, [source], prices)
    row = ledger.conn.execute("SELECT kind, resets_at FROM limit_observations").fetchone()
    assert tuple(row) == ("seven_day", 1792756800)
    assert totals(ledger)[0] == 0  # synthetic messages are never billed


def test_cache_tiers_split_and_priced():
    tokens = TokenCounts(cache_write_5m=1_000_000, cache_write_1h=1_000_000)
    assert token_cost(tokens, RATES["claude-opus-5-5"]) == pytest.approx(5 + 8)


def test_long_context_tier_applies_to_whole_request():
    small = TokenCounts(input=100_000, output=1_000_000)
    large = TokenCounts(input=100_001, output=1_000_000)
    rates = RATES["claude-haiku-5-5"]
    assert token_cost(small, rates) == pytest.approx(100_000 * 1e-07 + 0.5)
    assert token_cost(large, rates) == pytest.approx(100_001 * 5e-07 + 2.5)


def test_fast_geo_and_web_search_surcharges():
    prices = PriceBook(RATES, "test")
    base = dict(source="t", event_key="k", timestamp_ms=0, model="claude-opus-5-5",
                tokens=TokenCounts(output=1_000_000, web_search_requests=2))
    assert prices.cost(UsageEvent(**base)).usd == pytest.approx(20 + 0.02)
    assert prices.cost(UsageEvent(**base, speed="fast")).usd == pytest.approx(40 + 0.02)
    assert prices.cost(UsageEvent(**base, inference_geo="us")).usd == pytest.approx(22 + 0.02)
    unknown = UsageEvent(**{**base, "model": "claude-new-9"})
    assert prices.cost(unknown).status == "unpriced"


def test_cache_split_larger_than_total_is_scaled_down():
    from whatisworth.sources.claude_code import token_counts

    tokens = token_counts({"cache_creation_input_tokens": 333_992,
                           "cache_creation": {"ephemeral_1h_input_tokens": 351_354,
                                              "ephemeral_5m_input_tokens": 0}})
    assert (tokens.cache_write_1h, tokens.cache_write_5m) == (333_992, 0)


def test_fully_streamed_copy_wins_over_larger_early_copy(env):
    project, source, ledger, prices = env
    (project / "s1.jsonl").write_text("\n".join([
        assistant("msg_a", "2026-10-20T10:00:00Z", 3, cache_creation_input_tokens=16_255),
        assistant("msg_a", "2026-10-20T10:00:05Z", 212, cache_creation_input_tokens=9_002),
    ]) + "\n")
    sync(ledger, [source], prices)
    assert ledger.conn.execute("SELECT output FROM events").fetchone()[0] == 212


def test_rebuild_rereads_existing_files_and_keeps_deleted_ones(env):
    project, source, ledger, prices = env
    keep = project / "old.jsonl"
    keep.write_text(assistant("msg_old", "2026-10-01T10:00:00Z", 5) + "\n")
    (project / "s1.jsonl").write_text(assistant("msg_a", "2026-10-20T10:00:00Z", 5) + "\n")
    sync(ledger, [source], prices)
    keep.unlink()
    sync(ledger, [source], prices, rebuild=True)
    assert totals(ledger)[0] == 2
