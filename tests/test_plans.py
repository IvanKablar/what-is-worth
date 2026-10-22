import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whatisworth import plans  # noqa: E402


@pytest.mark.parametrize("org, tier, expected", [
    ("claude_max", "default_claude_max_5x", "claude_max_5x"),
    ("claude_max", "default_claude_max_20x", "claude_max_20x"),
    ("claude_pro", "default_claude_ai", "claude_pro"),
    ("claude_max", None, "claude_max"),
])
def test_plan_id(org, tier, expected):
    assert plans.plan_id(org, tier) == expected


def test_prices_per_week_and_percent():
    assert plans.weekly_price("claude_max_5x") == pytest.approx(100 * 12 / 52)
    assert plans.price_per_pct("claude_pro") == pytest.approx(20 * 12 / 52 / 100)
    assert plans.monthly_price("claude_max") is None  # unknown size: no guess
