"""API list prices from LiteLLM, with optional local overrides.

Rules applied on top of the per-token rates:

* Long-context tiers (`*_above_<N>k_tokens`): when a request's prompt
  exceeds the threshold, the whole request uses the higher rates. ccusage
  bills only the tokens above the threshold, which undercounts.
* Fast mode doubles the price (Opus 5, Opus 5.5, Opus 4.8).
* Data residency other than "global" adds 10 %.
* Web searches cost a flat fee per request.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .i18n import t
from .model import TokenCounts, UsageEvent
from .sources.claude_code import GLOBAL_GEOS

LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
MAX_CACHE_AGE_S = 24 * 3600
FAST_MULTIPLIER = 2.0
GEO_MULTIPLIER = 1.1
DEFAULT_WEB_SEARCH_USD = 0.01
_TIER = re.compile(r"_above_(\d+)k_tokens$")
_DATE_SUFFIX = re.compile(r"-\d{8}$")

# Status values stored with each cost.
PRICED = "priced"
UNPRICED = "unpriced"


@dataclass(frozen=True)
class Cost:
    usd: float
    status: str


class PriceBook:
    def __init__(self, rates: dict[str, dict[str, Any]], version: str) -> None:
        self._rates = rates
        self.version = version

    @classmethod
    def load(
        cls, cache_dir: Path, overrides_path: Path | None = None, offline: bool = False
    ) -> "PriceBook":
        cache_file = cache_dir / "litellm-prices.json"
        stale = not cache_file.exists() or time.time() - cache_file.stat().st_mtime > MAX_CACHE_AGE_S
        if stale and not offline:
            try:
                with urllib.request.urlopen(LITELLM_URL, timeout=20) as response:
                    payload = response.read()
                json.loads(payload)  # refuse to cache a broken download
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file.write_bytes(payload)
            except (OSError, ValueError):
                if not cache_file.exists():
                    raise RuntimeError(t("error.prices")) from None
        raw = cache_file.read_bytes()
        rates = {k: v for k, v in json.loads(raw).items() if isinstance(v, dict)}
        digest = hashlib.sha256(raw)
        if overrides_path and overrides_path.exists():
            override_raw = overrides_path.read_bytes()
            for model, values in json.loads(override_raw).items():
                rates[model] = {**rates.get(model, {}), **values}
            digest.update(override_raw)
        return cls(rates, digest.hexdigest()[:12])

    def rates_for(self, model: str) -> dict[str, Any] | None:
        for candidate in (model, _DATE_SUFFIX.sub("", model), f"anthropic/{model}"):
            rates = self._rates.get(candidate)
            if rates and "input_cost_per_token" in rates:
                return rates
        return None

    def cost(self, event: UsageEvent) -> Cost:
        rates = self.rates_for(event.model)
        if rates is None:
            return Cost(0.0, UNPRICED)
        usd = token_cost(event.tokens, rates)
        if event.speed == "fast":
            usd *= FAST_MULTIPLIER
        if event.inference_geo not in GLOBAL_GEOS:
            usd *= GEO_MULTIPLIER
        search = rates.get("search_context_cost_per_query") or {}
        usd += event.tokens.web_search_requests * search.get(
            "search_context_size_medium", DEFAULT_WEB_SEARCH_USD
        )
        return Cost(usd, PRICED)


def _tier_suffix(rates: dict[str, Any], prompt_tokens: int) -> str:
    """Suffix of the highest long-context tier the prompt exceeds, or ''."""
    thresholds = {
        int(match.group(1))
        for key in rates
        if key.startswith("input_cost_per_token") and (match := _TIER.search(key))
    }
    exceeded = [t for t in thresholds if prompt_tokens > t * 1000]
    return f"_above_{max(exceeded)}k_tokens" if exceeded else ""


def token_cost(tokens: TokenCounts, rates: dict[str, Any]) -> float:
    suffix = _tier_suffix(rates, tokens.prompt_tokens)

    def rate(base: str) -> float:
        value = rates.get(base + suffix, rates.get(base))
        return float(value or 0.0)

    input_rate = rate("input_cost_per_token")
    write_5m = rate("cache_creation_input_token_cost") or input_rate * 1.25
    write_1h = (
        float(rates.get(f"cache_creation_input_token_cost_above_1hr{suffix}") or 0)
        or float(rates.get("cache_creation_input_token_cost_above_1hr") or 0)
        or input_rate * 2
    )
    return (
        tokens.input * input_rate
        + (tokens.output + tokens.reasoning) * rate("output_cost_per_token")
        + tokens.cache_read * rate("cache_read_input_token_cost")
        + tokens.cache_write_5m * write_5m
        + tokens.cache_write_1h * write_1h
    )
