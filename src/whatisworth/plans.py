"""Subscription list prices, to set API value against what a plan costs.

Prices are monthly list prices in USD without tax, from claude.com/pricing
(checked 22.10.2026). Actual prices differ with currency, tax, annual billing
and discounts, so every figure based on them is labelled as list price.
"""

from __future__ import annotations

WEEKS_PER_MONTH = 52 / 12

MONTHLY_LIST_PRICE_USD = {
    "claude_pro": 20.0,
    "claude_max_5x": 100.0,
    # The pricing page only says "from $100" for Max; $200 is the known 20x price.
    "claude_max_20x": 200.0,
}


def plan_id(organization_type: str | None, rate_limit_tier: str | None) -> str:
    """Normalize Claude's account fields to one plan id, e.g. "claude_max_5x"."""
    base = organization_type or ""
    tier = rate_limit_tier or ""
    if base == "claude_max":
        if "20x" in tier:
            return "claude_max_20x"
        if "5x" in tier:
            return "claude_max_5x"
    return base


def monthly_price(plan: str | None) -> float | None:
    return MONTHLY_LIST_PRICE_USD.get(plan or "")


def weekly_price(plan: str | None) -> float | None:
    monthly = monthly_price(plan)
    return None if monthly is None else monthly / WEEKS_PER_MONTH


def price_per_pct(plan: str | None) -> float | None:
    """What one percentage point of the weekly quota costs on the plan."""
    weekly = weekly_price(plan)
    return None if weekly is None else weekly / 100
